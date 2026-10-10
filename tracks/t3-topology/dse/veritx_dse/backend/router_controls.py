"""Authored IQ-router controls; legacy profile identities remain unchanged."""
from dataclasses import replace

from veritx_dse.model.noc_controls import ROUTER_CONTROL_FIELDS

CONTROLLED_SUFFIX = "_ROUTER_CONTROLS_V1"
CONTROLLED_SEMANTICS_SUFFIX = "+authored-router/v1"

# Explicit namespace, never strip arbitrary strings into a qualified profile.
BASE_PROFILE_IDS = (
    "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1",
    "CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1",
    "CERTIFIED_BOOKSIM_CMESH_DOR_XY_V1",
    "CERTIFIED_BOOKSIM_ANYNET_V1",
    "CERTIFIED_BOOKSIM_TORUS_DOR_XY_V1",
    "CERTIFIED_BOOKSIM_FLATFLY_MIN_V1",
    "CERTIFIED_BOOKSIM_GEC_MECS_V1",
    "CERTIFIED_BOOKSIM_GEC_HYBRID_V1",
    "CERTIFIED_BOOKSIM_SROTA_ROW_FIRST_V1",
)
CONTROLLED_BASE = {p + CONTROLLED_SUFFIX: p for p in BASE_PROFILE_IDS}

NATIVE_FIELDS = {
    "input_buffer_depth_flits_per_vc": ("vc_buf_size", "buffer.cpp"),
    "credit_return_latency_cycles": ("credit_delay", "routers/router.cpp"),
    "allocator_iterations": ("alloc_iters", "allocators/allocator.cpp"),
    "route_compute_cycles": ("routing_delay", "routers/iq_router.cpp"),
    "vc_alloc_cycles": ("vc_alloc_delay", "routers/iq_router.cpp"),
    "switch_alloc_cycles": ("sw_alloc_delay", "routers/iq_router.cpp"),
    "switch_traversal_cycles": ("st_final_delay", "routers/router.cpp"),
}


def base_profile_id(profile_id):
    return CONTROLLED_BASE.get(profile_id, profile_id)


def has_router_controls(controls):
    return any(getattr(controls, name, None) is not None for name in ROUTER_CONTROL_FIELDS)


def controlled_profile(base):
    from veritx_dse.backend.booksim_projection import ConfigRead, ParameterOwner
    overridden = {name for name, _ in NATIVE_FIELDS.values()}
    overridden.update(("st_prepare_delay", "vc_allocator", "sw_allocator", "buf_size"))
    rows = tuple(row for row in base.audit if row.name not in overridden)
    rows += tuple(ConfigRead(key, ParameterOwner.CANONICAL, source,
                  note=f"authored canonical RouterBehaviorArtifact.{field}")
                  for field, (key, source) in NATIVE_FIELDS.items())
    # Crossbar latency is the sum; per-VC storage must not be replaced by
    # a shared total buffer cap. iSLIP is the supported exact allocator.
    rows += (
        ConfigRead("st_prepare_delay", ParameterOwner.BACKEND_PROFILE,
                   "routers/router.cpp", 0),
        ConfigRead("buf_size", ParameterOwner.BACKEND_PROFILE, "buffer.cpp", -1),
        ConfigRead("vc_allocator", ParameterOwner.BACKEND_PROFILE,
                   "routers/iq_router.cpp", "islip"),
        ConfigRead("sw_allocator", ParameterOwner.BACKEND_PROFILE,
                   "routers/iq_router.cpp", "islip"),
    )
    return replace(base, profile_id=base.profile_id + CONTROLLED_SUFFIX,
                   semantics_version=base.semantics_version + CONTROLLED_SEMANTICS_SUFFIX,
                   audit=rows)


def qualify_router_controls(parents):
    from veritx_dse.backend.booksim_projection import SemanticLoss, select_booksim_profile
    from veritx_dse.model.router_behavior import AllocatorPolicy
    bundle = parents.source_bundle
    controls = getattr(getattr(bundle, "design", None), "noc_controls", None)
    if not has_router_controls(controls):
        raise SemanticLoss("authored router profile requires explicit controls")
    behavior = bundle.router_behavior
    if (bundle.design.design_hash() != parents.resolved_fabric.design_hash
            or bundle.fabric.fabric_hash != parents.resolved_fabric.fabric_hash
            or bundle.fabric.router_behavior_hash != behavior.router_behavior_hash):
        raise SemanticLoss("router controls/behavior do not belong to the sealed design and fabric")
    behavior.validate_against(parents.vc_resource)
    for field in ROUTER_CONTROL_FIELDS:
        value = getattr(controls, field)
        if value is not None and getattr(behavior, field) != value:
            raise SemanticLoss(f"router behavior does not execute authored {field}={value}")
    if (behavior.vc_allocator is not AllocatorPolicy.ISLIP
            or behavior.switch_allocator is not AllocatorPolicy.ISLIP):
        raise SemanticLoss("authored router execution currently proves iSLIP only; round-robin is not substituted")
    if behavior.vc_alloc_cycles != 1 or behavior.switch_alloc_cycles != 1:
        raise SemanticLoss("installed IQ-router allocation queues are qualified for one-cycle VC/switch allocation only; multi-cycle allocation aborts in native queue revalidation")
    base = select_booksim_profile(replace(parents, source_bundle=None))
    if base.profile_id not in BASE_PROFILE_IDS:
        raise SemanticLoss("no authored IQ-router profile covers this routing policy")
    if (base.profile_id == "CERTIFIED_BOOKSIM_SROTA_ROW_FIRST_V1"
            and getattr(bundle.design.topology, "sidebuf_enable", True)):
        raise SemanticLoss("SROTA side-buffer storage/pipeline differs from the IQ router; authored IQ controls require sidebuf_enable=false")
    if base.pinned_values().get("sw_allocator", "islip") != "islip":
        raise SemanticLoss("this routing profile requires a specialized allocator; iSLIP is not substituted")
    return base


def render_router_controls(base_text, parents):
    from veritx_dse.backend.booksim_projection import CONFIG_KEY_ORDER, parse_config_values
    qualify_router_controls(parents)
    values = parse_config_values(base_text)
    behavior = parents.source_bundle.router_behavior
    values.update({key: str(getattr(behavior, field))
                   for field, (key, _source) in NATIVE_FIELDS.items()})
    values.update(st_prepare_delay="0", buf_size="-1", vc_allocator="islip", sw_allocator="islip")
    order = list(CONFIG_KEY_ORDER) + sorted(set(values) - set(CONFIG_KEY_ORDER))
    return "".join(f"{key} = {values[key]};\n" for key in order if key in values)
