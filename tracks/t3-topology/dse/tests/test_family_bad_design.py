from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.model.agent_intent_v4 import (
    AgentIntentV4, OrderingMode, PermissionWindow, ProtocolFamily,
)
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CollectiveDimension,
    CollectiveIntent, CollectiveKind, DependencyGraph, ModelFamily,
    PhysicalContext, WorkloadV3,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.topology_intent import (
    ConcentratedMeshIntent, FatTreeIntent, FlatFlyIntent, FlyIntent,
    GecMode, GecTopologyIntent, MeshIntent, QTreeIntent, RingIntent,
    StructuredTopologyIntent, TorusIntent, Tree4Intent,
)
from veritx_dse.model.srota_intent import (
    SrotaIntent, SrotaPlane, SrotaPathShape, SrotaVCPolicy,
)
from veritx_dse.product.project_top_rtl import (
    GEC_HYBRID_BLOCKER, SROTA_ISLAND_BLOCKER,
    SROTA_SIDEBUT_BLOCKER, SROTA_TELEMETRY_BLOCKER, SROTA_VALIANT_BLOCKER,
    UNSUPPORTED_COMPOSED_FAMILY, _family_adjacency,
    _family_id_from_topology,
    check_composed_family_profile, check_gec_mecs_shared_profile,
    check_hybrid_shared_profile, check_srota_shared_profile,
)

FAMILIES14 = (
    "mesh", "torus", "cmesh", "ring", "flatfly", "fly", "qtree", "tree4",
    "fattree", "dragonflynew", "kncube", "srota", "gec_mecs", "gec_hybrid",
)

BINDING_MUTATIONS = frozenset({
    "mesh", "torus", "cmesh", "ring", "flatfly", "fly", "qtree",
    "tree4", "fattree", "dragonflynew", "kncube", "gec_mecs", "gec_hybrid",
})

ANONYMOUS_INTENTS = {
    "mesh": lambda: MeshIntent(3, 1),
    "torus": lambda: TorusIntent(3, 1),
    "cmesh": lambda: ConcentratedMeshIntent(4, 4),
    "ring": lambda: RingIntent(64),
    "flatfly": lambda: FlatFlyIntent(4, 2, 1),
    "fly": lambda: FlyIntent(4, 3),
    "qtree": lambda: QTreeIntent(4, 3),
    "tree4": lambda: Tree4Intent(4, 3),
    "fattree": lambda: FatTreeIntent(4, 2),
    "dragonflynew": lambda: StructuredTopologyIntent("dragonfly", {"radix": 4, "group_count": 3}),
}


def _family_agents():
    return (
        Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=32, addr_width=64, protocol="AXI", clock_domain="noc_clk", power_domain="pd0"),
        Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=32, addr_width=64, protocol="AXI", clock_domain="noc_clk", power_domain="pd0"),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1, data_width=32, addr_width=64, protocol="AXI", clock_domain="noc_clk", power_domain="pd0"),
    )


def _family_intents():
    return (
        AgentIntentV4(0, protocol=ProtocolFamily.AXI5, ordering=OrderingMode.STRONG, max_outstanding=4, permission_windows=(PermissionWindow("HBM0", readable=True, writable=True, atomic=False),)),
        AgentIntentV4(1, protocol=ProtocolFamily.AXI5, ordering=OrderingMode.STRONG, max_outstanding=4, permission_windows=(PermissionWindow("HBM0", readable=True, writable=False, atomic=False),)),
        AgentIntentV4(2),
    )


def _family_request(intent):
    workload = WorkloadV3(model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, pp=1, ep=1, dp=1, collectives=(CollectiveIntent(kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP, payload_bytes=8192, traffic_class="tp_collective"),))
    return CompileRequestV4(workload=workload, agents=_family_agents(), dependencies=DependencyGraph(()), topology=intent, address_map=AddressMap(ranges=(AddressRange(name="HBM0", base=0x1000, size=0x1000, target_agent_idx=2),)), physical=PhysicalContext(default_clock_freq_mhz=1000), agent_intents=_family_intents())


def _compile(intent):
    request = _family_request(intent)
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error
    return request, compiled


def _refusal(checker, request, compiled):
    try:
        checker(request, compiled)
    except ValueError as exc:
        return str(exc)
    return None


def _drop_last_seat(compiled):
    endpoints = list(compiled.bundle.attachment.endpoints)
    object.__setattr__(compiled.bundle.attachment, "endpoints", tuple(endpoints[:-1]))


def _drop_last_shared_wire(compiled):
    links = list(compiled.bundle.topology.shared_links)
    object.__setattr__(compiled.bundle.topology, "shared_links", tuple(links[:-1]))


def _drop_tap_from_first_wire(compiled):
    links = list(compiled.bundle.topology.shared_links)
    first = links[0]
    object.__setattr__(first, "taps", tuple(first.taps[:-1]))


def _drop_wrap_channels_and_reid(compiled):
    topology = compiled.bundle.topology
    coords = [tuple(router.coordinates) for router in topology.routers]
    kept = tuple(
        channel for channel in topology.channels
        if not any(abs(a - b) == 2 for a, b in zip(coords[channel.src_router], coords[channel.dst_router]))
    )
    object.__setattr__(topology, "channels", tuple(replace(channel, channel_id=index) for index, channel in enumerate(kept)))


def _zero_fly_ejection_seat(compiled):
    routers = list(compiled.bundle.topology.routers)
    target = next(router for router in routers if getattr(router, "egress_seat_capacity", None) not in (None, 0))
    routers[target.router_id] = replace(target, egress_seat_capacity=0)
    object.__setattr__(compiled.bundle.topology, "routers", tuple(routers))


def _bump_first_router_seat(compiled):
    routers = list(compiled.bundle.topology.routers)
    first = routers[0]
    routers[0] = replace(first, seat_capacity=first.seat_capacity + 1)
    object.__setattr__(compiled.bundle.topology, "routers", tuple(routers))


def _srota_intent():
    return SrotaIntent(side_length=4, concentration=1, mecs_row=True, mecs_col=True, drop_latency=1, planes=frozenset({SrotaPlane.DATA}), island_columns=(1,), path_shapes=frozenset({SrotaPathShape.ROW, SrotaPathShape.COLUMN}), vc_policy=SrotaVCPolicy.SHAPE, sidebuf_enable=False, sidebuf_watermark=None, tel_period=32, tel_latency=2)


def _gec_mecs_intent():
    return GecTopologyIntent(GecMode.MULTIDROP, 4, 1, 1, 3)


def _gec_hybrid_intent():
    return GecTopologyIntent(GecMode.HYBRID, 4, 1, 1, 3)


@pytest.mark.parametrize("family", list(ANONYMOUS_INTENTS), ids=list(ANONYMOUS_INTENTS))
def test_correct_anonymous_family_baseline_passes(family):
    request, compiled = _compile(ANONYMOUS_INTENTS[family]())
    assert _refusal(check_composed_family_profile, request, compiled) is None


def test_correct_srota_baseline_passes_shared_profile():
    request, compiled = _compile(_srota_intent())
    assert _refusal(check_srota_shared_profile, request, compiled) is None


def test_correct_gec_mecs_baseline_passes_shared_profile():
    request, compiled = _compile(_gec_mecs_intent())
    assert _refusal(check_gec_mecs_shared_profile, request, compiled) is None


def test_correct_gec_hybrid_baseline_passes_shared_profile():
    request, compiled = _compile(_gec_hybrid_intent())
    assert _refusal(check_hybrid_shared_profile, request, compiled) is None


def test_kncube_family_id_is_unguarded():
    stub = SimpleNamespace(kind="kncube", parameters=lambda: {"k": 4, "n": 2})
    assert _family_id_from_topology(stub) == "kncube"


@pytest.mark.parametrize(("wrap", "expected_channels"), [(False, 24), (True, 36)])
def test_kncube_saved_intent_binds_general_radix_and_dimensions(wrap, expected_channels):
    intent = StructuredTopologyIntent(
        "kncube", {"radix": 3, "dimensions": 2, "wrap": wrap})
    request, compiled = _compile(intent)
    topology = compiled.bundle.topology
    assert len(topology.routers) == 9
    assert len(topology.channels) == expected_channels
    assert {router.coordinates for router in topology.routers} == {
        (x, y) for y in range(3) for x in range(3)}
    assert _refusal(check_composed_family_profile, request, compiled) is None

    changed = replace(request, topology=StructuredTopologyIntent(
        "kncube", {"radix": 3, "dimensions": 2, "wrap": not wrap}))
    message = _refusal(check_composed_family_profile, changed, compiled)
    assert message is not None
    assert UNSUPPORTED_COMPOSED_FAMILY in message
    assert "saved topology intent" in message or "does not match" in message


def test_kncube_supports_arbitrary_dimension_count():
    from veritx_dse.product.project_top_rtl import (
        build_family_router, composed_family_params_from_request,
    )
    intent = StructuredTopologyIntent(
        "kncube", {"radix": 3, "dimensions": 3, "wrap": True})
    request, compiled = _compile(intent)
    topology = compiled.bundle.topology
    assert len(topology.routers) == 27
    assert len(topology.channels) == 162
    assert all(len(router.coordinates) == 3 for router in topology.routers)

    # Independent KNCube source law: node IDs are base-k coordinates and
    # every router has one left/right neighbor in each wrapped dimension.
    expected = {router.router_id: set() for router in topology.routers}
    for node in expected:
        for dim in range(3):
            stride = 3 ** dim
            coordinate = (node // stride) % 3
            expected[node].add(node - stride if coordinate else node + 2 * stride)
            expected[node].add(node + stride if coordinate < 2 else node - 2 * stride)
    actual = {router_id: set(peers) for router_id, peers in
              _family_adjacency(topology).items()}
    assert actual == expected

    params = composed_family_params_from_request(request, compiled)
    assert params.family == "kncube"
    assert params.n_routers == 27
    assert params.topology_id == "kncube"
    files = build_family_router(params, topology)
    assert "N_ROUTERS = 27" in files["noc_pkg.sv"]
    assert files == build_family_router(params, topology)


@pytest.mark.parametrize("family", list(ANONYMOUS_INTENTS), ids=list(ANONYMOUS_INTENTS))
def test_family_refuses_dropped_endpoint_seat(family):
    request, compiled = _compile(ANONYMOUS_INTENTS[family]())
    _drop_last_seat(compiled)
    message = _refusal(check_composed_family_profile, request, compiled)
    assert message is not None, family + ": dropped seat accepted silently"
    assert UNSUPPORTED_COMPOSED_FAMILY in message
    assert "compiled endpoint count does not match agent instances" in message


@pytest.mark.parametrize("label,topo,blocker,fragment", [
    ("valiant_path", {"path_shapes": frozenset({SrotaPathShape.ROW, SrotaPathShape.COLUMN, SrotaPathShape.VALIANT})}, SROTA_VALIANT_BLOCKER, "valiant"),
    ("telemetry_plane", {"planes": frozenset({SrotaPlane.DATA, SrotaPlane.TELEMETRY})}, SROTA_TELEMETRY_BLOCKER, "telemetry"),
    ("control_plane", {"planes": frozenset({SrotaPlane.DATA, SrotaPlane.CONTROL})}, SROTA_TELEMETRY_BLOCKER, "telemetry"),
    ("side_buffer", {"sidebuf_enable": True, "sidebuf_watermark": 4}, SROTA_SIDEBUT_BLOCKER, "side buffer"),
    ("island_column_2", {"island_columns": (2,)}, SROTA_ISLAND_BLOCKER, "island"),
    ("hop_rank_vc_policy", {"vc_policy": SrotaVCPolicy.RANK}, SROTA_VALIANT_BLOCKER, "hop-rank"),
    ("row_only_shapes", {"path_shapes": frozenset({SrotaPathShape.ROW})}, SROTA_ISLAND_BLOCKER, "shapes"),
], ids=["valiant_path", "telemetry_plane", "control_plane", "side_buffer", "island_column_2", "hop_rank_vc_policy", "row_only_shapes"])
def test_srota_shared_profile_refuses_bad_binding(label, topo, blocker, fragment):
    request, compiled = _compile(_srota_intent())
    corrupted = replace(request, topology=replace(request.topology, **topo))
    message = _refusal(check_srota_shared_profile, corrupted, compiled)
    assert message is not None, "srota " + label + " accepted silently"
    assert UNSUPPORTED_COMPOSED_FAMILY in message
    assert blocker in message
    assert fragment in message


def test_srota_shared_profile_refuses_dropped_shared_wire():
    request, compiled = _compile(_srota_intent())
    _drop_last_shared_wire(compiled)
    message = _refusal(check_srota_shared_profile, request, compiled)
    assert message is not None
    assert UNSUPPORTED_COMPOSED_FAMILY in message
    assert "shared wires" in message


@pytest.mark.parametrize("label,topo,fragment", [
    ("pinned_shape_k7_o1_d6", {"grid_side_length": 7, "destinations_per_express_channel": 6}, "k*k = 49 routers"),
    ("pinned_shape_k3_o1_d2", {"grid_side_length": 3, "destinations_per_express_channel": 2}, "k*k = 9 routers"),
    ("hybrid_mode", {"mode": GecMode.HYBRID}, "not gec multidrop"),
], ids=["pinned_shape_k7_o1_d6", "pinned_shape_k3_o1_d2", "hybrid_mode"])
def test_gec_mecs_shared_profile_refuses_bad_binding(label, topo, fragment):
    request, compiled = _compile(_gec_mecs_intent())
    corrupted = replace(request, topology=replace(request.topology, **topo))
    message = _refusal(check_gec_mecs_shared_profile, corrupted, compiled)
    assert message is not None, "gec_mecs " + label + " accepted silently"
    assert UNSUPPORTED_COMPOSED_FAMILY in message
    assert fragment in message


def test_gec_mecs_shared_profile_refuses_dropped_shared_wire():
    request, compiled = _compile(_gec_mecs_intent())
    _drop_last_shared_wire(compiled)
    message = _refusal(check_gec_mecs_shared_profile, request, compiled)
    assert message is not None
    assert UNSUPPORTED_COMPOSED_FAMILY in message
    assert "one row and one column wire per router (32 for 16 routers); got 31" in message


@pytest.mark.parametrize("label,topo,fragment", [
    ("pinned_shape_k7_o1_d6", {"grid_side_length": 7, "destinations_per_express_channel": 6}, "pinned shape"),
    ("multidrop_mode", {"mode": GecMode.MULTIDROP}, "not gec hybrid"),
], ids=["pinned_shape_k7_o1_d6", "multidrop_mode"])
def test_hybrid_shared_profile_refuses_bad_binding(label, topo, fragment):
    request, compiled = _compile(_gec_hybrid_intent())
    corrupted = replace(request, topology=replace(request.topology, **topo))
    message = _refusal(check_hybrid_shared_profile, corrupted, compiled)
    assert message is not None, "gec_hybrid " + label + " accepted silently"
    assert UNSUPPORTED_COMPOSED_FAMILY in message
    assert GEC_HYBRID_BLOCKER in message
    assert fragment in message


def test_hybrid_shared_profile_refuses_dropped_shared_wire():
    request, compiled = _compile(_gec_hybrid_intent())
    _drop_last_shared_wire(compiled)
    message = _refusal(check_hybrid_shared_profile, request, compiled)
    assert message is not None
    assert UNSUPPORTED_COMPOSED_FAMILY in message
    assert GEC_HYBRID_BLOCKER in message
    assert "shared wires" in message


def _not_covered_probe(family):
    if family == "gec_mecs":
        request, compiled = _compile(_gec_mecs_intent())
        _drop_tap_from_first_wire(compiled)
        return check_gec_mecs_shared_profile, request, compiled
    if family == "gec_hybrid":
        request, compiled = _compile(_gec_hybrid_intent())
        _drop_tap_from_first_wire(compiled)
        return check_hybrid_shared_profile, request, compiled
    if family == "kncube":
        request, compiled = _compile(StructuredTopologyIntent(
            "kncube", {"radix": 3, "dimensions": 2, "wrap": False}))
        corrupted = replace(request, topology=StructuredTopologyIntent(
            "kncube", {"radix": 3, "dimensions": 2, "wrap": True}))
        return check_composed_family_profile, corrupted, compiled
    request, compiled = _compile(ANONYMOUS_INTENTS[family]())
    if family == "torus":
        _drop_wrap_channels_and_reid(compiled)
        return check_composed_family_profile, request, compiled
    if family == "fly":
        _zero_fly_ejection_seat(compiled)
        return check_composed_family_profile, request, compiled
    if family in ("qtree", "tree4"):
        _bump_first_router_seat(compiled)
        return check_composed_family_profile, request, compiled
    replacement = {
        "mesh": {"concentration": 2},
        "cmesh": {"concentration": 3},
        "ring": {"router_count": 32},
        "flatfly": {"dimension_count": 3},
        "fattree": {"level_count": 3},
        "dragonflynew": {"params": {"radix": 4, "group_count": 4}},
    }[family]
    corrupted = replace(request, topology=replace(request.topology, **replacement))
    return check_composed_family_profile, corrupted, compiled


@pytest.mark.parametrize("family", sorted(BINDING_MUTATIONS), ids=sorted(BINDING_MUTATIONS))
def test_family_bad_design_knob_has_mutation_witness(family):
    checker, request, compiled = _not_covered_probe(family)
    message = _refusal(checker, request, compiled)
    assert message is not None, family + ": corrupted request/topology binding accepted silently"
    assert UNSUPPORTED_COMPOSED_FAMILY in message
    if family in {"gec_mecs", "gec_hybrid"}:
        assert "tap identity" in message or "saved topology intent" in message


def test_binding_guard_checks_link_attributes_as_well_as_graph_shape():
    request, compiled = _compile(MeshIntent(3, 1))
    channel = compiled.bundle.topology.channels[0]
    object.__setattr__(channel, "width_bits", channel.width_bits + 1)
    message = _refusal(check_composed_family_profile, request, compiled)
    assert message is not None
    assert UNSUPPORTED_COMPOSED_FAMILY in message
    assert "saved topology intent" in message


def test_binding_guard_honors_explicit_link_width():
    from dataclasses import replace

    request = _family_request(MeshIntent(3, 1))
    request = replace(request, noc_controls=replace(request.noc_controls,
                                                     link_width=128))
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error
    assert _refusal(check_composed_family_profile, request, compiled) is None


def test_binding_mutation_witnesses_cover_all_request_bound_families():
    assert set(BINDING_MUTATIONS) | {"srota"} == set(FAMILIES14)
    assert set(BINDING_MUTATIONS) == set(FAMILIES14) - {"srota"}


