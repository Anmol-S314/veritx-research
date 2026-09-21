"""veritx_dse.backend.meshdor — certified native-mesh DOR_XY lowering (P1B).

CERTIFIED_BOOKSIM_ANYNET_V1 is sealed and untouched; this module is the
parallel certified path for native-mesh DOR_XY fabrics
(CERTIFIED_BOOKSIM_MESH_DOR_XY_V1). It reuses every topology-independent
authority and duplicates only what is genuinely profile-specific:

REUSED (never reimplemented): ResolvedFabricBundle revalidation,
TraceSummary/trace grammar (`_scan_trace`), config value formatting,
seed discipline, BackendConfigArtifact/BackendInputManifest identity,
materialization + pre-spawn hash verification, profile-gate mechanics,
quiescence gates, route-dump FORMAT, stats parsing, producer identity,
CertifiedBookSimEvidence, PreparedBackend/RenderedBackend carriers,
pre-spawn workload gates + trace projection (`assert_projection_ready`,
`render_waved_trace`).

PROFILE-SPECIFIC (new here): the narrow domain checks (square MESH,
seat 1, identity-prefix attachment, DOR_XY-only VCs, unit latency and
weights, no parallel channels), the native-mesh render (`topology=mesh,
k, n`, no AnyNet file), the mesh shape verification (replaces the
AnyNet parse-back), the native-mesh route-dump comparison (covers every
native node, attached or idle), and the canonical-identity asserts.

Narrow certified domain (mirrors meshdor_profile.py): family MESH,
square k x k, seat_capacity 1, identity-prefix attachment (endpoint i
-> router i, E <= N), DOR_XY route class with all VCs bound to it,
uniform channel latency 1, unit route weights, no parallel channels.
CONCENTRATED_MESH, TORUS, RING and non-DOR classes are UNSUPPORTED
(their own proofs, later) — never silently approximated.

Native-mesh facts (read from third_party/booksim2/src, proven by the
qualification tests in tests/test_p1b_meshdor_profile.py): mesh ==
KNCube native (`_nodes == _size`, node n <-> router n, x = id % k),
links latency 1 under the pinned `use_noc_latency=1`, trace-only
addressing with self-loop skip for idle nodes, and the P1B dump hook
(KNCube::DumpDorRoutes) calling the CONFIGURED `dim_order_mesh`
function per (router, node) pair.
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any

from veritx_dse.model.topology_artifact import MaterializedFamily

from .booksim import (
    BackendMaterializationError, BookSimLoweringError, BookSimRouteError,
    PreparedBackend, RenderedBackend, SEED_POLICY_EXPLICIT,
    SEED_POLICY_PINNED_DEFAULT, _SEED_DEFAULT,
    _canonical_seed_argument, _format_cfg_value, _scan_trace,
)
from .contracts import (
    BackendConfigArtifact, BackendConfigError, BackendInputError,
    BackendInputManifest, BackendTarget, CertificationEffect,
    ExecutionQualification, RenderedInput, RepresentationStatus,
    SemanticBinding, SemanticDimension, sha256_bytes,
)
from .evidence import PARSER_VERSION
from .meshdor_profile import (
    MESH_DOR_BACKEND_SEMANTICS_VERSION, MESH_DOR_LOWERER_VERSION,
    MESH_DOR_PROFILE, MESH_DOR_PROFILE_ID,
    MESH_DOR_ROUTING_FUNCTION_VALUE, MESH_DOR_SITES,
)
from .producer import (
    EXECUTION_TRANSPORT_SUPERVISED_PROCESS as _SUPERVISED,
)
from .producer import ProducerError

MESHDOR_CONFIG_FILE = "config.cfg"
MESHDOR_WORKLOAD_FILE = "workload.trace"
MESHDOR_ROUTE_DUMP_FILE = "routing.dump"

_MESH_N_DIMS = 2

# Rendered in a fixed order so the config bytes are deterministic.
# Must equal the mesh profile's active field set (asserted at import).
MESHDOR_CONFIG_KEY_ORDER: tuple[str, ...] = (
    # topology + projection
    "topology", "k", "n", "routing_function",
    # fabric-derived router/VC/flow behavior (same code paths as AnyNet)
    "num_vcs", "vc_buf_size", "wait_for_tail_credit",
    "hold_switch_for_packet", "vc_allocator", "sw_allocator", "alloc_iters",
    "arb_type", "credit_delay", "routing_delay", "vc_alloc_delay",
    "sw_alloc_delay", "st_prepare_delay", "st_final_delay",
    "input_speedup", "output_speedup", "internal_speedup",
    "output_buffer_size", "buffer_policy",
    # VC-range globals derived from num_vcs
    "read_request_begin_vc", "read_request_end_vc",
    "read_reply_begin_vc", "read_reply_end_vc",
    "write_request_begin_vc", "write_request_end_vc",
    "write_reply_begin_vc", "write_reply_end_vc",
    # native-mesh backend constant (pinned, never a compiled default)
    "use_noc_latency",
    # explicit backend-profile pins (no compiled defaults)
    "router", "classes", "subnets", "link_failures", "priority",
    "vc_priority_donation", "vc_busy_when_full", "vc_prioritize_empty",
    "vc_shuffle_requests", "speculative", "spec_check_elig",
    "spec_check_cred", "spec_mask_by_reqs", "spec_sw_allocator", "noq",
    "buf_size", "use_read_write", "injection_rate",
    "injection_rate_uses_flits", "injection_process", "class_priority",
    "read_request_subnet", "read_reply_subnet", "write_request_subnet",
    "write_reply_subnet", "sim_count", "warmup_periods", "measure_stats",
    "pair_stats", "warmup_thres", "acc_warmup_thres", "stopping_thres",
    "acc_stopping_thres", "include_queuing", "print_csv_results",
    "deadlock_warn_timeout", "print_activity", "viewer_trace", "sim_power",
    "max_samples", "sim_type", "latency_thres",
    # workload / execution inputs
    "traffic", "sample_period", "seed", "routing_dump_file",
)

# Artifact parameters that are projection semantics, not BookSim cfg keys.
_PROJECTION_ONLY_KEYS = frozenset({"routing_class",
                                   "channel_latency_cycles"})

_DUMP_RE = re.compile(
    r"^src_router (\d+) dst_node (\d+) next_router (\d+) port (\d+)$")


def _assert_mesh_ownership() -> None:
    if set(MESHDOR_CONFIG_KEY_ORDER) != MESH_DOR_PROFILE.active_names():
        missing = set(MESHDOR_CONFIG_KEY_ORDER) - \
            MESH_DOR_PROFILE.active_names()
        extra = MESH_DOR_PROFILE.active_names() - \
            set(MESHDOR_CONFIG_KEY_ORDER)
        raise BookSimLoweringError(
            f"mesh config key order does not match the audited active "
            f"field set (unemitted {sorted(missing)}, "
            f"unlisted {sorted(extra)})")
    for name in MESH_DOR_PROFILE.active_names():
        if not MESH_DOR_PROFILE.source_of(name):
            raise BookSimLoweringError(
                f"audited mesh field {name!r} has no source location")


_assert_mesh_ownership()


class MeshDorMaterializationError(ValueError):
    """Rendered mesh inputs cannot be materialized/verified — fail closed."""


# ── narrow domain checks ────────────────────────────────────────────────

def _mesh_shape(bundle: Any) -> int:
    """The mesh radix k, or refuse (square MESH, seat 1 only)."""
    topo = bundle.topology
    if topo.family != MaterializedFamily.MESH:
        raise BookSimLoweringError(
            f"UNSUPPORTED: the certified mesh-DOR profile covers "
            f"TopologyArtifact.family MESH only, got "
            f"{getattr(topo.family, 'value', topo.family)!r} "
            f"(CONCENTRATED_MESH needs its own concentration proof; "
            f"TORUS needs its own deadlock theorem)")
    for r in topo.routers:
        if r.seat_capacity != 1:
            raise BookSimLoweringError(
                f"UNSUPPORTED: the certified mesh-DOR profile covers "
                f"seat_capacity 1 only (router {r.router_id} has "
                f"{r.seat_capacity})")
    n = topo.router_count
    k = math.isqrt(n)
    if k * k != n or k < 1:
        raise BookSimLoweringError(
            f"UNSUPPORTED: the certified mesh-DOR profile covers square "
            f"k x k meshes only, got {n} routers")
    return k


def _mesh_attachment(bundle: Any) -> None:
    """Identity-prefix attachment, or refuse.

    derive_attachment fills router-id-ordered seats from the canonical
    inventory order, so endpoint i -> router i for every attached
    endpoint. A permuted (or sparse) attachment would silently relabel
    the native node universe, so anything else refuses here — the
    renderer never remaps endpoint ids to node ids.
    """
    n = bundle.topology.router_count
    endpoints = bundle.attachment.endpoints
    if len(endpoints) > n:
        raise BookSimLoweringError(
            f"UNSUPPORTED: {len(endpoints)} attached endpoints exceed the "
            f"{n} native mesh nodes")
    ids = sorted(e.endpoint_id for e in endpoints)
    if ids != list(range(len(endpoints))):
        raise BookSimLoweringError(
            "UNSUPPORTED: endpoint ids are not dense 0..E-1; the native "
            "mesh node universe cannot be addressed without a remap proof")
    for e in endpoints:
        if e.router_id != e.endpoint_id:
            raise BookSimLoweringError(
                f"UNSUPPORTED: endpoint {e.endpoint_id} attaches to "
                f"router {e.router_id}, not to its native node; the "
                f"certified mesh-DOR profile covers identity-prefix "
                f"attachments only")


def _mesh_routing_class(bundle: Any) -> str:
    """DOR_XY with every VC bound to it, or refuse (never weaken DOR)."""
    from veritx_dse.core.route_artifact import DOR_XY
    classes = [d.id for d in bundle.router_route.routing_classes]
    if DOR_XY not in classes:
        raise BookSimLoweringError(
            f"UNSUPPORTED: the certified mesh-DOR profile realizes "
            f"DOR_XY only; route artifact classes are {classes}")
    vc_classes = {cls for _vc, cls in
                  bundle.vc_assignment.vc_to_routing_class}
    if vc_classes != {DOR_XY}:
        raise BookSimLoweringError(
            f"UNSUPPORTED: the certified mesh-DOR profile executes one "
            f"DOR routing function, but VCs map to routing classes "
            f"{sorted(vc_classes)}")
    return DOR_XY


def _mesh_link_semantics(bundle: Any) -> None:
    """Unit latency/weights and no parallel channels, or refuse.

    Native mesh links are latency 1 (no per-link control exists), DOR
    ignores route weights (a non-unit weight would leave a fabric
    semantic unexecuted), and parallel channels have no native
    representation (last-mention-wins ambiguity, as with AnyNet).
    """
    latencies = {c.latency_cycles for c in bundle.topology.channels}
    if latencies != {1}:
        raise BookSimLoweringError(
            f"UNSUPPORTED: native mesh links are latency 1; channels "
            f"carry latencies {sorted(latencies)}")
    weights = {c.route_weight for c in bundle.topology.channels}
    if weights != {1}:
        raise BookSimLoweringError(
            f"UNSUPPORTED: DOR_XY is hop-count semantics but channels "
            f"carry route_weight {sorted(weights)}")
    pairs: dict[tuple[int, int], int] = {}
    for c in bundle.topology.channels:
        key = (c.src_router, c.dst_router)
        pairs[key] = pairs.get(key, 0) + 1
    parallel = sorted(k for k, v in pairs.items() if v > 1)
    if parallel:
        raise BookSimLoweringError(
            f"UNSUPPORTED: parallel channels between routers "
            f"{parallel[:3]} have no native mesh representation")


def _vc_exactness(vc: Any) -> tuple[bool, str]:
    """Mirror of the standalone single-class VC exactness predicate."""
    if len(vc.traffic_class_to_vcs) == 1:
        (_cls, vcs), = vc.traffic_class_to_vcs
        if vcs == vc.vc_ids:
            return True, ""
    return False, (
        "BookSim trace traffic runs every flow in one class over all VCs; "
        "this artifact assigns traffic classes to VC subsets that the "
        "backend does not execute")


def _transitions_exact(vc: Any) -> bool:
    return vc.allowed_transitions == tuple(
        (i, i) for i in vc.vc_ids)


# ── lowering ────────────────────────────────────────────────────────────

def lower_meshdor_standalone(
        bundle: Any,
        *,
        profile: str = MESH_DOR_PROFILE_ID) -> BackendConfigArtifact:
    """Lower one validated mesh-DOR fabric to the certified native-mesh
    BookSim projection. Raises BookSimLoweringError for UNSUPPORTED."""
    if profile != MESH_DOR_PROFILE_ID:
        raise BookSimLoweringError(
            f"unknown mesh-DOR BookSim profile {profile!r}")
    try:
        bundle.revalidate()
    except ValueError as exc:
        raise BookSimLoweringError(
            f"bundle failed revalidation before lowering: {exc}") from exc

    from veritx_dse.model.router_behavior import VCReusePolicy
    topo, att = bundle.topology, bundle.attachment
    rr, rra, vc = bundle.router_route, bundle.resolved_route, \
        bundle.vc_assignment
    pf, rb = bundle.packet_format, bundle.router_behavior
    ad, fabric = bundle.address_decode, bundle.fabric

    k = _mesh_shape(bundle)
    _mesh_attachment(bundle)
    selected = _mesh_routing_class(bundle)
    _mesh_link_semantics(bundle)

    vc_class_exact, vc_class_reason = _vc_exactness(vc)
    transitions_exact = _transitions_exact(vc)
    half = vc.vc_count // 2

    fabric_params = (
        ("channel_latency_cycles", 1),
        ("alloc_iters", rb.allocator_iterations),
        ("buffer_policy", "private"),
        ("credit_delay", rb.credit_return_latency_cycles),
        ("hold_switch_for_packet", 1 if rb.hold_switch_for_packet else 0),
        ("input_speedup", rb.input_speedup),
        ("internal_speedup", float(rb.internal_speedup)),
        ("k", k),
        ("n", _MESH_N_DIMS),
        ("num_vcs", vc.vc_count),
        ("output_buffer_size",
         rb.output_stage_depth_flits_per_vc * vc.vc_count),
        ("output_speedup", rb.output_speedup),
        ("read_reply_begin_vc", half),
        ("read_reply_end_vc", vc.vc_count - 1),
        ("read_request_begin_vc", 0),
        ("read_request_end_vc", half - 1),
        ("routing_class", selected),
        ("routing_delay", rb.route_compute_cycles),
        ("routing_function", MESH_DOR_ROUTING_FUNCTION_VALUE),
        ("st_final_delay", rb.switch_traversal_cycles),
        ("st_prepare_delay", 0),
        ("sw_alloc_delay", rb.switch_alloc_cycles),
        ("sw_allocator", rb.switch_allocator.value),
        ("vc_alloc_delay", rb.vc_alloc_cycles),
        ("vc_allocator", rb.vc_allocator.value),
        ("vc_buf_size", rb.input_buffer_depth_flits_per_vc),
        ("wait_for_tail_credit",
         1 if rb.vc_reuse_policy is VCReusePolicy.WAIT_FOR_TAIL_CREDIT
         else 0),
        ("write_reply_begin_vc", half),
        ("write_reply_end_vc", vc.vc_count - 1),
        ("write_request_begin_vc", 0),
        ("write_request_end_vc", half - 1),
    )
    combined = dict(fabric_params)
    for name, value in MESH_DOR_PROFILE.pinned_values().items():
        if name in combined:
            raise BookSimLoweringError(
                f"parameter {name!r} is both fabric-derived and "
                "profile-pinned")
        combined[name] = value
    expected_owner = MESH_DOR_PROFILE.ownership()
    for name in combined:
        if name in _PROJECTION_ONLY_KEYS:
            continue
        if name not in expected_owner:
            raise BookSimLoweringError(
                f"emitted parameter {name!r} is not in the audited mesh "
                "active field set")
    params = tuple(sorted(combined.items()))

    def bind(dimension, source, status, fields, reason="", effect=None,
             domain=""):
        if effect is None:
            effect = (CertificationEffect.NONE if status in (
                RepresentationStatus.EXACT,
                RepresentationStatus.DERIVED_EXACT,
                RepresentationStatus.BACKEND_IRRELEVANT)
                else CertificationEffect.FIDELITY_DOWNGRADE)
        return SemanticBinding(
            dimension=dimension, source_identity=source,
            representation_status=status,
            backend_fields=tuple(sorted(fields)), reason=reason,
            certification_effect=effect, supported_domain=domain)

    t_hash, a_hash = topo.topology_hash(), att.attachment_hash()
    rra_hash, vc_hash = rra.resolved_route_hash(), vc.vc_assignment_hash()
    pf_hash, rb_hash = pf.packet_format_hash(), rb.router_behavior_hash()
    ad_hash = ad.address_decode_hash()

    bindings = (
        bind(SemanticDimension.TOPOLOGY_GRAPH, t_hash,
             RepresentationStatus.DERIVED_EXACT,
             (("topology_kind", "mesh"), ("k", k), ("n", _MESH_N_DIMS),
              ("parse_back", "mesh shape re-derived at spawn")),
             domain="a square k x k MESH grid rendered as native k/n; "
                    "native node n <-> router n; Srota row-major "
                    "numbering equals the native decomposition"),
        bind(SemanticDimension.ENDPOINT_ATTACHMENT, a_hash,
             RepresentationStatus.EXACT,
             (("node_lines", att.endpoint_count),
              ("ports", "native 1:1 node<->router; no port reassignment")),
             domain="identity-prefix attachments only (endpoint i -> "
                    "router i, E <= N); native nodes beyond the attached "
                    "prefix provably inject nothing (trace-scoped "
                    "addressing plus the backend self-loop skip) and "
                    "their forwarding is proven by the full-table dump"),
        bind(SemanticDimension.CHANNEL_WIDTH, t_hash,
             RepresentationStatus.BACKEND_IRRELEVANT, (),
             reason="BookSim is a flit-count timing model: flit channels "
                    "transfer one flit per cycle and no width-dependent "
                    "serialization/occupancy exists"),
        bind(SemanticDimension.CHANNEL_LATENCY, t_hash,
             RepresentationStatus.EXACT, (("native_link_latency", 1),),
             domain="uniform channel latency == 1 only (native mesh "
                    "links are latency 1 under use_noc_latency=1)"),
        bind(SemanticDimension.ROUTE_WEIGHT, t_hash,
             RepresentationStatus.EXACT, (("route_weight", 1),),
             domain="every channel route_weight == 1 only"),
        bind(SemanticDimension.ROUTE_REALIZATION, rra_hash,
             RepresentationStatus.EXACT,
             (("routing_function", MESH_DOR_ROUTING_FUNCTION_VALUE),
              ("routing_class", selected),
              ("route_evidence", MESHDOR_ROUTE_DUMP_FILE)),
             domain="DOR_XY on a native square mesh; the configured "
                    "dim_order_mesh function is probed per (router, "
                    "node) pair and the executed first-hop table is "
                    "compared mechanically"),
        bind(SemanticDimension.VC_COUNT, vc_hash,
             RepresentationStatus.EXACT, (("num_vcs", vc.vc_count),),
             domain="all vc_count >= 1"),
        bind(SemanticDimension.VC_CLASS_ASSIGNMENT, vc_hash,
             RepresentationStatus.EXACT if vc_class_exact
             else RepresentationStatus.COARSENED,
             (("classes", 1),),
             reason=vc_class_reason,
             domain="a single traffic class mapped to all VCs only"
             if vc_class_exact else ""),
        bind(SemanticDimension.VC_ROUTING_CLASS, vc_hash,
             RepresentationStatus.EXACT,
             (("routing_function", MESH_DOR_ROUTING_FUNCTION_VALUE),),
             domain="all VCs map to DOR_XY"),
        bind(SemanticDimension.VC_TRANSITIONS, vc_hash,
             RepresentationStatus.EXACT if transitions_exact
             else RepresentationStatus.UNREPRESENTABLE,
             tuple(),
             reason="" if transitions_exact else
             "BookSim never migrates a packet between VCs; the artifact's "
             "cross-VC transitions have no backend realization",
             effect=None if transitions_exact
             else CertificationEffect.BLOCKS_EXACT_FABRIC,
             domain="allowed_transitions == identity (VC-preserving) "
                    "only" if transitions_exact else ""),
        bind(SemanticDimension.ESCAPE_VCS, vc_hash,
             RepresentationStatus.EXACT if not vc.escape_vcs
             else RepresentationStatus.UNREPRESENTABLE,
             tuple(),
             reason="" if not vc.escape_vcs else
             "the certified mesh profile has no escape-VC mechanism; a "
             "fabric that designates escape VCs is not representable",
             effect=None if not vc.escape_vcs
             else CertificationEffect.BLOCKS_EXACT_FABRIC,
             domain="escape_vcs == () (trivial policy) only"
             if not vc.escape_vcs else ""),
        bind(SemanticDimension.FLIT_WIDTH, pf_hash,
             RepresentationStatus.BACKEND_IRRELEVANT, (),
             reason="BookSim counts flits; no width/serialization model"),
        bind(SemanticDimension.PACKET_DELIMITATION, pf_hash,
             RepresentationStatus.COARSENED,
             (("packet_size", "not emitted (trace-record authority)"),),
             reason="BookSim executes the packet boundaries encoded in "
                    "the trace records; it does not model BOUNDED_WORMHOLE "
                    "fragmentation"),
        bind(SemanticDimension.PACKET_MAX_FLITS, pf_hash,
             RepresentationStatus.DERIVED_EXACT,
             (("trace_validation",
               f"1 <= packet_size <= {pf.max_packet_flits}"),),
             domain="every trace packet size in [1, max_packet_flits] only"),
        bind(SemanticDimension.HEADER_LAYOUT, pf_hash,
             RepresentationStatus.BACKEND_IRRELEVANT, (),
             reason="no header decode exists in the timing model"),
        bind(SemanticDimension.HEADER_REPLICATION, pf_hash,
             RepresentationStatus.BACKEND_IRRELEVANT, (),
             reason="header bytes are not modeled per flit"),
        bind(SemanticDimension.BUFFER_ORGANIZATION, rb_hash,
             RepresentationStatus.EXACT, (("buffer_policy", "private"),),
             domain="buffer_organization=PER_INPUT_PORT_PER_VC only "
                    "(artifact-enforced)"),
        bind(SemanticDimension.INPUT_BUFFER_DEPTH, rb_hash,
             RepresentationStatus.EXACT,
             (("vc_buf_size", rb.input_buffer_depth_flits_per_vc),),
             domain="any depth >= 1 flit per VC"),
        bind(SemanticDimension.OUTPUT_STAGE_DEPTH, rb_hash,
             RepresentationStatus.COARSENED,
             (("output_buffer_size",
               rb.output_stage_depth_flits_per_vc * vc.vc_count),),
             reason="BookSim's output queue is per output PORT, not per VC; "
                    "aggregate capacity depth*VCs approximates per-VC "
                    "staging without per-VC occupancy isolation"),
        bind(SemanticDimension.FLOW_CONTROL, rb_hash,
             RepresentationStatus.EXACT,
             (("wait_for_tail_credit",
               1 if rb.vc_reuse_policy is VCReusePolicy.WAIT_FOR_TAIL_CREDIT
               else 0),),
             domain="flow_control=CREDIT only (artifact-enforced)"),
        bind(SemanticDimension.CREDIT_RETURN_LATENCY, rb_hash,
             RepresentationStatus.EXACT,
             (("credit_delay", rb.credit_return_latency_cycles),),
             domain="any non-negative credit delay"),
        bind(SemanticDimension.VC_REUSE_POLICY, rb_hash,
             RepresentationStatus.EXACT,
             (("wait_for_tail_credit",
               1 if rb.vc_reuse_policy is VCReusePolicy.WAIT_FOR_TAIL_CREDIT
               else 0),),
             domain="both artifact policies map 1:1 to wait_for_tail_credit"),
        bind(SemanticDimension.VC_ALLOCATOR, rb_hash,
             RepresentationStatus.EXACT,
             (("vc_allocator", rb.vc_allocator.value),),
             domain="AllocatorPolicy values islip/round_robin"),
        bind(SemanticDimension.SWITCH_ALLOCATOR, rb_hash,
             RepresentationStatus.EXACT,
             (("sw_allocator", rb.switch_allocator.value),),
             domain="AllocatorPolicy values islip/round_robin"),
        bind(SemanticDimension.ALLOCATOR_ITERATIONS, rb_hash,
             RepresentationStatus.EXACT,
             (("alloc_iters", rb.allocator_iterations),),
             domain="iterations >= 1"),
        bind(SemanticDimension.HOLD_SWITCH_FOR_PACKET, rb_hash,
             RepresentationStatus.EXACT,
             (("hold_switch_for_packet",
               1 if rb.hold_switch_for_packet else 0),),
             domain="both boolean values"),
        bind(SemanticDimension.INPUT_SPEEDUP, rb_hash,
             RepresentationStatus.EXACT,
             (("input_speedup", rb.input_speedup),),
             domain="positive integer speedups"),
        bind(SemanticDimension.OUTPUT_SPEEDUP, rb_hash,
             RepresentationStatus.EXACT,
             (("output_speedup", rb.output_speedup),),
             domain="positive integer speedups"),
        bind(SemanticDimension.INTERNAL_SPEEDUP, rb_hash,
             RepresentationStatus.DERIVED_EXACT,
             (("internal_speedup", float(rb.internal_speedup)),),
             domain="positive integers converted exactly to float"),
        bind(SemanticDimension.ROUTE_COMPUTE_CYCLES, rb_hash,
             RepresentationStatus.EXACT,
             (("routing_delay", rb.route_compute_cycles),),
             domain="non-negative cycles; BookSim routing stage"),
        bind(SemanticDimension.VC_ALLOC_CYCLES, rb_hash,
             RepresentationStatus.EXACT,
             (("vc_alloc_delay", rb.vc_alloc_cycles),),
             domain="non-negative cycles; BookSim VC-allocation stage"),
        bind(SemanticDimension.SWITCH_ALLOC_CYCLES, rb_hash,
             RepresentationStatus.EXACT,
             (("sw_alloc_delay", rb.switch_alloc_cycles),),
             domain="non-negative cycles; BookSim switch-allocation stage"),
        bind(SemanticDimension.SWITCH_TRAVERSAL_CYCLES, rb_hash,
             RepresentationStatus.DERIVED_EXACT,
             (("st_prepare_delay", 0),
              ("st_final_delay", rb.switch_traversal_cycles)),
             reason="",
             domain="non-negative cycles; split st_prepare=0 + st_final"),
        bind(SemanticDimension.OUTPUT_DELAY_CYCLES, rb_hash,
             RepresentationStatus.UNREPRESENTABLE, (),
             reason="BookSim's output_delay field is registered but not "
                    "read by the iq router in this fork (verified by "
                    "source grep); the artifact value has no executed "
                    "effect"),
        bind(SemanticDimension.ADDRESS_DECODE, ad_hash,
             RepresentationStatus.BACKEND_IRRELEVANT, (),
             reason="the timing backend has no address-dependent state or "
                    "behavior; addresses remain protocol payload"),
        bind(SemanticDimension.PLANE_COMPOSITION, fabric.fabric_hash(),
             RepresentationStatus.EXACT, (("subnets", 1),),
             domain="PlaneComposition.SINGLE_PLANE only"),
    )

    try:
        artifact = BackendConfigArtifact(
            backend_target=BackendTarget.BOOKSIM_STANDALONE,
            backend_profile=profile,
            backend_semantics_version=MESH_DOR_BACKEND_SEMANTICS_VERSION,
            lowerer_version=MESH_DOR_LOWERER_VERSION,
            resolved_fabric_hash=bundle.resolved_fabric
            .resolved_fabric_hash(),
            fabric_hash=fabric.fabric_hash(),
            normalized_parameters=params,
            semantic_bindings=bindings,
        )
    except BackendConfigError as exc:  # pragma: no cover - contract bug
        raise BookSimLoweringError(
            f"mesh lowering produced an invalid backend artifact: "
            f"{exc}") from exc
    for key, _value in artifact.normalized_parameters:
        if key in _PROJECTION_ONLY_KEYS:
            continue
        if key not in MESH_DOR_PROFILE.ownership():
            raise BookSimLoweringError(
                f"emitted mesh parameter {key!r} has no ownership entry")
    return artifact


# ── deterministic rendering ─────────────────────────────────────────────

def assert_canonical_meshdor_projection(
        bundle: Any,
        config: BackendConfigArtifact) -> BackendConfigArtifact:
    """Prove ``config`` IS the canonical mesh-DOR lowering of ``bundle``.

    Same closed-world discipline as the AnyNet canonical assert: the
    expected artifact for the config's profile identity is re-derived
    and required identical. Hash consistency alone is never accepted.
    """
    if config.backend_target is not BackendTarget.BOOKSIM_STANDALONE:
        raise BookSimLoweringError(
            f"no canonical mesh-DOR lowering for target "
            f"{config.backend_target.value}")
    if config.backend_profile != MESH_DOR_PROFILE_ID:
        raise BookSimLoweringError(
            f"noncanonical backend_profile {config.backend_profile!r}; "
            f"mesh-DOR requires {MESH_DOR_PROFILE_ID!r}")
    if config.backend_semantics_version != \
            MESH_DOR_BACKEND_SEMANTICS_VERSION:
        raise BookSimLoweringError(
            f"noncanonical backend_semantics_version "
            f"{config.backend_semantics_version!r}; expected "
            f"{MESH_DOR_BACKEND_SEMANTICS_VERSION!r}")
    if config.lowerer_version != MESH_DOR_LOWERER_VERSION:
        raise BookSimLoweringError(
            f"noncanonical lowerer_version {config.lowerer_version!r}; "
            f"expected {MESH_DOR_LOWERER_VERSION!r}")
    if config.fabric_hash != bundle.fabric.fabric_hash():
        raise BookSimLoweringError(
            "config fabric_hash does not match the supplied bundle")
    if config.resolved_fabric_hash != \
            bundle.resolved_fabric.resolved_fabric_hash():
        raise BookSimLoweringError(
            "config resolved_fabric_hash does not match the supplied "
            "bundle")
    expected = lower_meshdor_standalone(bundle)
    actual_identity = config.identity_dict()
    expected_identity = expected.identity_dict()
    if actual_identity != expected_identity:
        differing = sorted(
            key for key in set(actual_identity) | set(expected_identity)
            if actual_identity.get(key) != expected_identity.get(key))
        raise BookSimLoweringError(
            f"noncanonical mesh-DOR artifact: it does not equal the "
            f"canonical lowering of this bundle (differs in "
            f"{differing})")
    return expected


def verify_meshdor_profile_gates(rendered_values: dict[str, str]) -> None:
    """Mesh render must satisfy the mesh site-gate table (not AnyNet's)."""
    from .source_audit import SourceAuditError, verify_site_gates
    try:
        verify_site_gates(MESH_DOR_SITES, rendered_values)
    except SourceAuditError as exc:
        raise BookSimLoweringError(
            f"rendered mesh config violates certified profile gates: "
            f"{exc}") from exc


def render_meshdor_standalone(
        bundle: Any, config: BackendConfigArtifact, *,
        workload_trace: bytes, seed: int | None = None) -> RenderedBackend:
    """Render exact, path-free native-mesh backend inputs.

    No topology file exists on this path: the mesh shape travels as the
    derived `k`/`n` config values (re-verified at spawn by
    verify_mesh_projection) and behaviorally by the executed route dump.
    """
    assert_canonical_meshdor_projection(bundle, config)
    if config.fabric_hash != bundle.fabric.fabric_hash():
        raise BookSimLoweringError(
            "config fabric_hash does not match the supplied bundle")
    if config.resolved_fabric_hash != \
            bundle.resolved_fabric.resolved_fabric_hash():
        raise BookSimLoweringError(
            "config resolved_fabric_hash does not match the supplied "
            "bundle")
    if seed is not None and (type(seed) is not int or seed < 0):
        raise BookSimLoweringError(
            f"seed must be a non-negative int or None, got {seed!r}")

    summary = _scan_trace(
        workload_trace,
        endpoint_count=bundle.attachment.endpoint_count,
        max_packet_flits=bundle.packet_format.max_packet_flits)
    from .booksim import _SAMPLE_PERIOD_MIN as _SP_MIN
    from .booksim import _SAMPLE_PERIOD_MARGIN as _SP_MARGIN
    sample_period = max(_SP_MIN, summary.max_timestamp + 1 + _SP_MARGIN)

    params = dict(config.normalized_parameters)
    for key in ("routing_class", "channel_latency_cycles", "k", "n",
                "topology"):
        if key not in params:
            raise BookSimLoweringError(
                f"config is missing projection parameter {key!r}")

    values: dict[str, Any] = {
        "traffic": f"trace({MESHDOR_WORKLOAD_FILE})",
        "sample_period": sample_period,
        "seed": _SEED_DEFAULT if seed is None else seed,
        "routing_dump_file": MESHDOR_ROUTE_DUMP_FILE,
    }
    for key, value in config.normalized_parameters:
        if key in _PROJECTION_ONLY_KEYS:
            continue
        if key in values:
            raise BookSimLoweringError(
                f"duplicate rendered mesh parameter {key!r}")
        values[key] = value
    unowned = set(values) - set(MESH_DOR_PROFILE.ownership())
    if unowned:
        raise BookSimLoweringError(
            f"rendered mesh parameters without an owner: {sorted(unowned)}")
    missing_keys = set(MESH_DOR_PROFILE.ownership()) - set(values)
    if missing_keys:
        raise BookSimLoweringError(
            f"mesh ownership table keys not rendered: "
            f"{sorted(missing_keys)}")

    cfg_lines = [f"{key} = {_format_cfg_value(values[key])};"
                 for key in MESHDOR_CONFIG_KEY_ORDER]
    cfg = ("\n".join(cfg_lines) + "\n").encode()
    files = ((MESHDOR_CONFIG_FILE, cfg),
             (MESHDOR_WORKLOAD_FILE, workload_trace))
    return RenderedBackend(files=tuple(sorted(files)),
                           sample_period=sample_period,
                           trace_summary=summary)


# ── input binding ───────────────────────────────────────────────────────

_ROLE_BY_NAME = {MESHDOR_CONFIG_FILE: "booksim_config",
                 MESHDOR_WORKLOAD_FILE: "workload"}


def bind_meshdor_inputs(
        config: BackendConfigArtifact, rendered: RenderedBackend, *,
        workload_hash: str, seed: int | None = None) -> BackendInputManifest:
    """Bind exact mesh execution inputs to a path-independent artifact."""
    if sha256_bytes(rendered.file(MESHDOR_WORKLOAD_FILE)) != workload_hash:
        raise BackendInputError(
            "workload_hash does not match the rendered workload bytes")
    try:
        inputs = tuple(
            RenderedInput(role=_ROLE_BY_NAME[name], logical_name=name,
                          sha256=sha256_bytes(data), size=len(data))
            for name, data in rendered.files)
    except KeyError as exc:
        raise BackendInputError(
            f"rendered file {exc.args[0]!r} has no input role") from exc
    return BackendInputManifest(
        backend_config_hash=config.backend_config_hash(),
        workload_hash=workload_hash,
        execution_mode="REAL_SIMULATION",
        seed=_SEED_DEFAULT if seed is None else seed,
        seed_policy=(SEED_POLICY_EXPLICIT if seed is not None
                     else SEED_POLICY_PINNED_DEFAULT),
        rendered_inputs=inputs,
        invocation_args=(("config-file", MESHDOR_CONFIG_FILE),),
    )


def prepare_meshdor_standalone(
        bundle: Any, *, workload_trace: bytes,
        seed: int | None = None,
        profile: str = MESH_DOR_PROFILE_ID) -> PreparedBackend:
    config = lower_meshdor_standalone(bundle, profile=profile)
    rendered = render_meshdor_standalone(
        bundle, config, workload_trace=workload_trace, seed=seed)
    manifest = bind_meshdor_inputs(
        config, rendered, workload_hash=sha256_bytes(workload_trace),
        seed=seed)
    return PreparedBackend(bundle=bundle, config=config,
                           rendered=rendered, manifest=manifest)


def assert_canonical_prepared_meshdor(prepared: PreparedBackend) -> None:
    """Whole-chain proof for the mesh path (mirrors the AnyNet assert)."""
    bundle, config = prepared.bundle, prepared.config
    rendered, manifest = prepared.rendered, prepared.manifest
    assert_canonical_meshdor_projection(bundle, config)
    try:
        workload = rendered.file(MESHDOR_WORKLOAD_FILE)
    except Exception as exc:
        from .booksim import BackendMaterializationError
        raise BookSimLoweringError(
            f"prepared mesh backend does not contain the canonical "
            f"workload input: {exc}") from exc
    seed_arg = _canonical_seed_argument(manifest)
    expected_rendered = render_meshdor_standalone(
        bundle, config, workload_trace=workload, seed=seed_arg)
    supplied_names = [name for name, _ in rendered.files]
    expected_names = [name for name, _ in expected_rendered.files]
    if len(set(supplied_names)) != len(supplied_names):
        raise BookSimLoweringError(
            "prepared mesh backend rendered files contain duplicate "
            "logical names")
    extra = sorted(set(supplied_names) - set(expected_names))
    missing = sorted(set(expected_names) - set(supplied_names))
    if extra or missing:
        raise BookSimLoweringError(
            f"prepared mesh backend file set is not canonical (missing "
            f"{missing}, extra {extra})")
    for name, data in expected_rendered.files:
        if rendered.file(name) != data:
            raise BookSimLoweringError(
                f"rendered mesh {name!r} is not the canonical rendering "
                f"of this config/workload/seed (byte mismatch)")
    if rendered.sample_period != expected_rendered.sample_period or \
            rendered.trace_summary != expected_rendered.trace_summary:
        raise BookSimLoweringError(
            "rendered mesh trace summary/sample_period is not the "
            "canonical derivation from the workload bytes")
    expected_manifest = bind_meshdor_inputs(
        config, expected_rendered, workload_hash=sha256_bytes(workload),
        seed=seed_arg)
    actual_identity = manifest.identity_dict()
    expected_identity = expected_manifest.identity_dict()
    if actual_identity != expected_identity:
        differing = sorted(
            key for key in set(actual_identity) | set(expected_identity)
            if actual_identity.get(key) != expected_identity.get(key))
        raise BookSimLoweringError(
            f"prepared mesh manifest is not the canonical binding of the "
            f"rendered inputs (differs in {differing})")


# ── mesh shape verification (replaces the AnyNet parse-back) ────────────

def verify_mesh_projection(bundle: Any, config: BackendConfigArtifact,
                           rendered: RenderedBackend) -> dict[str, int]:
    """Re-derive the mesh shape from the bundle and require the rendered
    config to equal it, with no topology file in between.

    k/n travel as config VALUES (not a parsed file), so the spawn-time
    proof re-derives them from the artifact and compares. Behavioral
    equivalence is proven per run by the executed route dump; this
    proves the shape claim the dump executes under.
    """
    from .booksim import parse_booksim_config_values
    params = dict(config.normalized_parameters)
    k = _mesh_shape(bundle)
    _mesh_attachment(bundle)
    if params.get("k") != k or params.get("n") != _MESH_N_DIMS:
        raise MeshDorMaterializationError(
            f"config mesh shape k={params.get('k')} n={params.get('n')} "
            f"is not the bundle shape k={k} n={_MESH_N_DIMS}")
    if params.get("topology") != "mesh" or \
            params.get("routing_function") != \
            MESH_DOR_ROUTING_FUNCTION_VALUE:
        raise MeshDorMaterializationError(
            "config is not a native-mesh DOR projection "
            f"(topology={params.get('topology')!r}, "
            f"routing_function={params.get('routing_function')!r})")
    names = sorted(name for name, _ in rendered.files)
    if names != sorted([MESHDOR_CONFIG_FILE, MESHDOR_WORKLOAD_FILE]):
        raise MeshDorMaterializationError(
            f"mesh backend file set {names} is not exactly "
            f"[config.cfg, workload.trace] (no topology file exists on "
            f"this path)")
    cfg_values = parse_booksim_config_values(
        rendered.file(MESHDOR_CONFIG_FILE).decode())
    if cfg_values.get("k") != str(k) or \
            cfg_values.get("n") != str(_MESH_N_DIMS):
        raise MeshDorMaterializationError(
            "rendered mesh config k/n do not equal the bundle shape")
    fresh = _scan_trace(
        rendered.file(MESHDOR_WORKLOAD_FILE),
        endpoint_count=bundle.attachment.endpoint_count,
        max_packet_flits=bundle.packet_format.max_packet_flits)
    if fresh != rendered.trace_summary:
        raise MeshDorMaterializationError(
            "rendered mesh trace summary is not the canonical scan of "
            "the workload bytes")
    return {"routers": bundle.topology.router_count,
            "nodes": bundle.topology.router_count,
            "mesh_k": k}


# ── native-mesh route-dump comparison ───────────────────────────────────

def compare_meshdor_route_realization(
        bundle: Any, config: BackendConfigArtifact,
        dump_path: Path) -> dict[str, Any]:
    """Mechanically compare the executed native-mesh first-hop table with
    the authoritative DOR_XY RouteArtifact — every native node, attached
    or idle.

    Native node n <-> router n is proven by the lowering's
    identity-prefix check (re-asserted here before trusting it): an
    attached endpoint maps to its own id, and an idle native node IS its
    router. Proving the idle nodes' forwarding is what shows unused
    terminals neither inject (they cannot address the trace) nor alter
    routing. Same dump grammar as AnyNet, so the row parser is shared in
    shape (duplicated here so the sealed AnyNet compare stays untouched).
    """
    from veritx_dse.core.route_artifact import DOR_XY
    params = dict(config.normalized_parameters)
    if params.get("routing_class") != DOR_XY:
        raise BookSimRouteError(
            f"mesh route comparison requires routing_class DOR_XY, got "
            f"{params.get('routing_class')!r}")
    e2r = dict(bundle.resolved_route.endpoint_to_router)
    for ep, r in sorted(e2r.items()):
        if ep != r:
            raise BookSimRouteError(
                f"endpoint {ep} maps to router {r}: the mesh comparison "
                f"requires identity-prefix attachment")
    n_routers = bundle.topology.router_count
    try:
        text = dump_path.read_text()
    except OSError as exc:
        raise BookSimRouteError(
            f"BookSim produced no mesh route dump at {dump_path} ({exc}); "
            f"the certified mesh profile requires executed-route "
            f"evidence") from exc
    executed: dict[tuple[int, int], int] = {}
    for line_no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _DUMP_RE.match(line)
        if not m:
            raise BookSimRouteError(
                f"mesh route dump line {line_no} is malformed: {line!r}")
        src, node, nxt, _port = (int(g) for g in m.groups())
        key = (src, node)
        if key in executed:
            raise BookSimRouteError(
                f"mesh route dump repeats (src_router={src}, "
                f"dst_node={node})")
        executed[key] = nxt

    channels = {c.channel_id: c for c in bundle.topology.channels}
    entries = bundle.router_route.entries
    expected: dict[tuple[int, int], int] = {}
    for r in range(n_routers):
        for node in range(n_routers):
            dst_router = node  # identity-prefix, re-proven above
            if r == dst_router:
                expected[(r, node)] = r
                continue
            key = (DOR_XY, r, dst_router)
            if key not in entries:
                raise BookSimRouteError(
                    f"RouteArtifact has no DOR_XY entry for {key!r}")
            channel = channels[entries[key]]
            if channel.src_router != r:
                raise BookSimRouteError(
                    f"RouteArtifact (DOR_XY,{r},{dst_router}) -> channel "
                    f"{channel.channel_id} leaves router "
                    f"{channel.src_router}, not {r}")
            expected[(r, node)] = channel.dst_router

    missing = sorted(set(expected) - set(executed))
    extra = sorted(set(executed) - set(expected))
    if missing or extra:
        raise BookSimRouteError(
            f"executed mesh route dump coverage differs from the "
            f"expected table (missing {missing[:3]}, extra {extra[:3]})")
    mismatches = [(k, expected[k], executed[k])
                  for k in sorted(expected) if expected[k] != executed[k]]
    if mismatches:
        raise BookSimRouteError(
            f"executed mesh route realization diverges from the DOR_XY "
            f"RouteArtifact in {len(mismatches)} entries, e.g. "
            f"{mismatches[:3]} — the fabric is NOT executed as declared")

    from veritx_dse.core.spec import canonical_json
    return {
        "status": "EXACT",
        "routing_class": DOR_XY,
        "pairs_compared": len(expected),
        "expected_sha256": hashlib.sha256(canonical_json(
            [[r, e, expected[(r, e)]] for r, e in sorted(expected)]
        ).encode()).hexdigest(),
        "executed_sha256": hashlib.sha256(canonical_json(
            [[r, e, executed[(r, e)]] for r, e in sorted(executed)]
        ).encode()).hexdigest(),
    }


# ── materialization / verification ──────────────────────────────────────

def _write_bytes_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def materialize_mesh_backend(rendered: RenderedBackend,
                             manifest: BackendInputManifest,
                             directory: Path) -> dict[str, Path]:
    """Write exact mesh bytes into a run-owned dir; refuse conflicts."""
    from .booksim import BackendMaterializationError
    directory.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, data in rendered.files:
        record = manifest.input(name)
        actual = sha256_bytes(data)
        if actual != record.sha256 or len(data) != record.size:
            raise BackendMaterializationError(
                f"rendered mesh {name!r} does not match the manifest "
                f"(sha {actual} vs {record.sha256}, size {len(data)} vs "
                f"{record.size})")
        path = directory / name
        if path.exists():
            existing = path.read_bytes()
            if sha256_bytes(existing) != record.sha256:
                raise BackendMaterializationError(
                    f"{path} already exists with different content; "
                    "refusing to overwrite a run-owned input")
        else:
            _write_bytes_atomic(path, data)
        paths[name] = path
    return paths


def verify_materialized_mesh(manifest: BackendInputManifest,
                             directory: Path) -> None:
    """Re-hash every mesh input immediately before spawn."""
    from .booksim import BackendMaterializationError
    for record in manifest.rendered_inputs:
        path = directory / record.logical_name
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise BackendMaterializationError(
                f"materialized mesh input {record.logical_name!r} "
                f"unreadable: {exc}") from exc
        actual = sha256_bytes(data)
        if actual != record.sha256:
            raise BackendMaterializationError(
                f"materialized mesh input {record.logical_name!r} was "
                f"modified after planning: sha {actual} != "
                f"{record.sha256} — refusing to execute")
        if len(data) != record.size:
            raise BackendMaterializationError(
                f"materialized mesh input {record.logical_name!r} size "
                f"changed ({len(data)} != {record.size}) — refusing to "
                f"execute")


# ── certified mesh execution ────────────────────────────────────────────

def execution_qualification_mesh(
        config: BackendConfigArtifact) -> ExecutionQualification:
    """What a mesh-DOR run is (same binding law as the AnyNet path)."""
    effects = {b.certification_effect for b in config.semantic_bindings}
    if CertificationEffect.UNSUPPORTED_EXECUTION in effects:
        return ExecutionQualification.EXECUTION_UNSUPPORTED
    if CertificationEffect.BLOCKS_EXACT_FABRIC in effects:
        return ExecutionQualification.EXECUTED_BLOCKED_FROM_EXACT
    if config.exact_fabric_eligible():
        return ExecutionQualification.EXECUTED_EXACT
    return ExecutionQualification.EXECUTED_WITH_DECLARED_LOSS


def assert_executable_mesh(
        config: BackendConfigArtifact) -> ExecutionQualification:
    """Refuse UNSUPPORTED_EXECUTION before any mesh process spawns."""
    qualification = execution_qualification_mesh(config)
    if qualification is ExecutionQualification.EXECUTION_UNSUPPORTED:
        blocked = ", ".join(
            b.dimension.value for b in config.semantic_bindings
            if b.certification_effect is
            CertificationEffect.UNSUPPORTED_EXECUTION)
        raise BookSimLoweringError(
            f"UNSUPPORTED_EXECUTION: refusing to run the mesh-DOR "
            f"profile with unresolved semantics: {blocked}")
    return qualification


def _execute_prepared_meshdor(
        prepared: PreparedBackend, *,
        run_dir: Path,
        repo_root: Path,
        timeout: int,
        binary: Path | None,
        transport: str,
        runner: Any,
):  # noqa: ANN201 (mirrors the sealed AnyNet core's return type)
    """Shared certified-execution core for the mesh-DOR path.

    Same order and same fail-closed discipline as the sealed AnyNet
    core: revalidate -> canonical config -> canonical prepared inputs
    -> qualification guard -> producer identity (pre-spawn digest) ->
    materialize -> mesh shape verification -> pre-spawn hash
    re-verification -> mesh profile gates -> fresh route-output slot ->
    producer recheck -> run -> executed-route proof -> parse stats.
    """
    import time

    from veritx_dse.core.errors import BookSimError, TimeoutError
    from veritx_dse.simulation.booksim import parse_output

    from .booksim import parse_booksim_config_values
    from .producer import ProducerError, resolve_producer_identity

    config, manifest, rendered = (prepared.config, prepared.manifest,
                                  prepared.rendered)
    bundle = prepared.bundle

    try:
        bundle.revalidate()
    except ValueError as exc:
        raise BookSimLoweringError(
            f"bundle failed revalidation before mesh execution: "
            f"{exc}") from exc
    assert_canonical_meshdor_projection(bundle, config)
    if config.backend_config_hash() != manifest.backend_config_hash:
        raise BackendMaterializationError(
            "manifest does not bind this mesh backend config artifact")
    if config.fabric_hash != bundle.fabric.fabric_hash() or \
            config.resolved_fabric_hash != \
            bundle.resolved_fabric.resolved_fabric_hash():
        raise BackendMaterializationError(
            "mesh backend config does not bind the supplied bundle")
    assert_canonical_prepared_meshdor(prepared)
    qualification = assert_executable_mesh(config)

    from .booksim import _resolve_producer_path
    bin_path = _resolve_producer_path(binary, repo_root)
    producer = resolve_producer_identity(bin_path, repo_root=Path(repo_root))

    backend_dir = Path(run_dir) / "backend"
    materialize_mesh_backend(rendered, manifest, backend_dir)
    verify_mesh_projection(bundle, config, rendered)
    verify_materialized_mesh(manifest, backend_dir)
    verify_meshdor_profile_gates(parse_booksim_config_values(
        (backend_dir / MESHDOR_CONFIG_FILE).read_text()))

    route_dump_path = backend_dir / MESHDOR_ROUTE_DUMP_FILE
    if route_dump_path.exists():
        from .booksim import BookSimRouteError
        raise BookSimRouteError(
            f"refusing certified mesh execution: {route_dump_path} "
            f"already exists before spawn; a certified attempt requires "
            f"a fresh attempt output slot")

    cmd = (str(bin_path), MESHDOR_CONFIG_FILE)

    try:
        spawn_bytes = bin_path.read_bytes()
    except OSError as exc:
        raise ProducerError(
            f"execution producer {bin_path} unreadable immediately "
            f"before spawn: {exc}; refusing") from exc
    if hashlib.sha256(spawn_bytes).hexdigest() != \
            producer.binary_sha256 or \
            len(spawn_bytes) != producer.binary_size:
        raise ProducerError(
            "execution producer changed between resolution and spawn; "
            "refusing — restart the attempt against the new producer")

    t0 = time.perf_counter()
    res = runner(list(cmd), str(backend_dir), timeout)
    wall = round(time.perf_counter() - t0, 3)

    if getattr(res, "timed_out", False):
        raise TimeoutError(
            f"certified mesh BookSim timed out after {timeout}s",
            returncode=res.returncode, stdout=res.stdout, stderr=res.stderr)
    if res.returncode != 0:
        raise BookSimError(
            f"certified mesh BookSim exited {res.returncode}",
            returncode=res.returncode, stdout=res.stdout, stderr=res.stderr)

    stats = parse_output(res.stdout or "")
    if stats.get("delivered", 0) == 0:
        raise BookSimError(
            "certified mesh BookSim delivered 0 packets — topology cannot "
            "carry this workload",
            returncode=res.returncode, stdout=res.stdout, stderr=res.stderr)
    if "latency" not in stats:
        raise BookSimError(
            "certified mesh BookSim produced no latency measurement",
            returncode=res.returncode, stdout=res.stdout, stderr=res.stderr)

    route = compare_meshdor_route_realization(
        bundle, config, backend_dir / MESHDOR_ROUTE_DUMP_FILE)

    from .booksim import CertifiedBookSimEvidence
    return CertifiedBookSimEvidence(
        backend_config_hash=config.backend_config_hash(),
        backend_input_hash=manifest.backend_input_hash(),
        resolved_fabric_hash=config.resolved_fabric_hash,
        fabric_hash=config.fabric_hash,
        route_equivalence=route["status"],
        route_expected_sha256=route["expected_sha256"],
        route_executed_sha256=route["executed_sha256"],
        route_pairs_compared=route["pairs_compared"],
        exact_fabric_eligible=config.exact_fabric_eligible(),
        qualification=qualification.value,
        semantic_loss=config.semantic_loss_summary(),
        stats={k: v for k, v in stats.items()},
        exit_status=int(res.returncode),
        wall_time_s=wall,
        command=cmd,
        backend_dir=str(backend_dir),
        workload_hash=manifest.workload_hash,
        seed=manifest.seed,
        seed_policy=manifest.seed_policy,
        rendered_inputs=tuple(r.identity_dict()
                              for r in manifest.rendered_inputs),
        invocation_args=manifest.invocation_args,
        booksim_binary_sha256=producer.binary_sha256,
        producer_source_revision=producer.source_revision,
        producer_source_dirty=producer.source_dirty,
        producer_source_dirty_digest=producer.source_dirty_digest,
        producer_tool_identity=producer.tool_identity,
        execution_transport=transport,
    )


def run_meshdor_booksim(
        prepared: PreparedBackend, *,
        run_dir: Path,
        repo_root: Path,
        timeout: int = 60,
        binary: Path | None = None,
):  # noqa: ANN201
    """Execute one prepared mesh-DOR run via the authoritative process.

    The ONLY entry point that can emit reusable mesh ``EXECUTED_*``
    evidence. There is no runner parameter — injected transports live
    behind the explicitly test-only seam below.
    """
    from veritx_dse.core.process import supervised_run

    def _supervised(c: Any, cwd: str, t: int) -> Any:
        return supervised_run(c, cwd=cwd, timeout=t, on_timeout="complete")

    return _execute_prepared_meshdor(
        prepared, run_dir=run_dir, repo_root=repo_root, timeout=timeout,
        binary=binary, transport=_SUPERVISED, runner=_supervised)


def _run_meshdor_with_runner_for_test(
        prepared: PreparedBackend, *,
        run_dir: Path,
        repo_root: Path,
        timeout: int = 60,
        runner: Any = None,
        binary: Path | None = None,
):  # noqa: ANN201
    """Test-only mesh execution seam (mirrors the AnyNet test seam)."""
    if runner is None:
        raise BookSimLoweringError(
            "mesh test seam requires an explicit injected runner")
    from .producer import EXECUTION_TRANSPORT_TEST_INJECTED
    return _execute_prepared_meshdor(
        prepared, run_dir=run_dir, repo_root=repo_root, timeout=timeout,
        binary=binary, transport=EXECUTION_TRANSPORT_TEST_INJECTED,
        runner=runner)


# ── workload-facing chain (mirrors projection.py waved_* seams) ──────────

def prepare_meshdor(pt: Any, *, seed: int | None = None
                    ) -> tuple[PreparedBackend, dict[str, Any]]:
    """Pre-spawn gates, then the sealed mesh preparation of canonical
    Wave-D traffic (v1 or v2 artifact — both expose the same seam)."""
    from .projection import assert_projection_ready, render_waved_trace
    summary = assert_projection_ready(pt)
    trace = render_waved_trace(pt)
    prepared = prepare_meshdor_standalone(pt.bundle, workload_trace=trace,
                                          seed=seed)
    return prepared, summary


def run_waved_meshdor(prepared: PreparedBackend, *, run_dir: Path,
                      repo_root: Path, timeout: int, binary: Path,
                      summary: dict[str, Any] | None = None
                      ) -> dict[str, Any]:
    """Sealed mesh execution + conservation summary (§21 discipline)."""
    from veritx_dse.core.errors import BackendFailure
    from veritx_dse.verification.gates import verify_backend_quiescence
    evidence = run_meshdor_booksim(
        prepared, run_dir=run_dir, repo_root=repo_root, timeout=timeout,
        binary=binary)
    if evidence.exit_status != 0:
        raise BackendFailure(
            f"qualified mesh BookSim execution failed with exit status "
            f"{evidence.exit_status}")
    stats = evidence.stats or {}
    counters = {
        "delivered_packets": stats.get("delivered"),
        "flits_injected": stats.get("flits_injected"),
        "flits_accepted": stats.get("flits_accepted"),
        "drain_verdict": stats.get("drain_verdict"),
    }
    if summary is not None:
        verify_backend_quiescence(summary, counters)
    return {"evidence": evidence, "backend_counters": counters}


__all__ = [
    "MESH_DOR_LOWERER_VERSION",
    "MESH_DOR_PROFILE_ID",
    "MESHDOR_CONFIG_FILE",
    "MESHDOR_CONFIG_KEY_ORDER",
    "MESHDOR_ROUTE_DUMP_FILE",
    "MESHDOR_WORKLOAD_FILE",
    "MeshDorMaterializationError",
    "assert_canonical_meshdor_projection",
    "assert_canonical_prepared_meshdor",
    "assert_executable_mesh",
    "bind_meshdor_inputs",
    "compare_meshdor_route_realization",
    "execution_qualification_mesh",
    "lower_meshdor_standalone",
    "materialize_mesh_backend",
    "prepare_meshdor",
    "prepare_meshdor_standalone",
    "render_meshdor_standalone",
    "run_meshdor_booksim",
    "_run_meshdor_with_runner_for_test",
    "run_waved_meshdor",
    "verify_mesh_projection",
    "verify_meshdor_profile_gates",
]
