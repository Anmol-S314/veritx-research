"""veritx_dse.backend.booksim — canonical standalone BookSim lowering (B3.7b).

One profile, one lowerer, one renderer, one certified execution seam:

    ResolvedFabricBundle
        └─ lower_booksim_standalone()  → BackendConfigArtifact
             └─ render_booksim_standalone() → exact input bytes (path-free)
                  └─ bind_booksim_inputs() → BackendInputManifest
                       └─ materialize_backend() → run-owned backend/ dir
                            └─ run_certified_booksim() → evidence

What makes this different from the legacy ``simulation/booksim.py`` path:

  * lowering starts from validated semantic artifacts and never from a
    legacy ``Topology`` preset;
  * the topology is the ACTUAL materialized router/channel/attachment
    graph, rendered as an AnyNet file and parsed back before spawn;
  * a closed ownership table classifies every rendered parameter;
  * the certified profile REQUIRES a route-realization proof: the BookSim
    fork's ``routing_dump_file`` seam (VeritX B3.7b patch) writes the
    built all-pairs first-hop table, which is compared mechanically
    against the authoritative RouteArtifact. A missing or divergent dump
    refuses the run. Configuration names are never route evidence;
  * the executed input bytes are hash-verified immediately before spawn,
    so a file modified after planning cannot execute.

Route-cost/latency coupling: AnyNet's Dijkstra uses each link's numeric
value as BOTH channel latency and route cost (anynet.cpp). Certified v1
therefore requires uniform channel latency and ``route_weight == 1`` for
every channel — then weighted shortest path is exactly min-hop and the
hop-count ANYNET_MIN_HOPS authority is representable. Heterogeneous
latency is refused (UNSUPPORTED), never approximated.

Deliberately NOT emitted: BookSim's ``packet_size``. Trace-driven packet
length comes from each trace record (tracetrafficmanager.cpp), so a
config-level packet_size would be a false packetization authority. The
manifest/runner validates every trace packet against
``PacketFormatArtifact.max_packet_flits`` instead.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veritx_dse.core.anynet import parse_anynet_file
from veritx_dse.core.route_artifact import ANYNET_MIN_HOPS
from veritx_dse.model.router_behavior import (
    AllocatorPolicy, VCReusePolicy,
)

from .booksim_profile import (
    BOOKSIM_SERVING_PROFILE as SERVING_PROFILE_SPEC,
    BOOKSIM_STANDALONE_PROFILE as STANDALONE_PROFILE_SPEC,
)
from veritx_dse.model.resolved_bundle import ResolvedFabricBundle
from .contracts import (
    BackendConfigArtifact, BackendConfigError, BackendInputError,
    BackendInputManifest, BackendTarget, CertificationEffect,
    ExecutionQualification,
    ParameterOwner, RenderedInput, RepresentationStatus, SemanticBinding,
    SemanticDimension, sha256_bytes,
)
from .producer import (
    EXECUTION_TRANSPORT_SUPERVISED_PROCESS,
    EXECUTION_TRANSPORT_TEST_INJECTED, ProducerError,
    resolve_producer_identity,
)
from .evidence import PARSER_VERSION

BOOKSIM_STANDALONE_PROFILE = "CERTIFIED_BOOKSIM_ANYNET_V1"
SERVING_BOOKSIM2_PROFILE = "CERTIFIED_SERVING_BOOKSIM2_V1"
BOOKSIM_BACKEND_SEMANTICS_VERSION = "booksim2-fork+B3.7b-anynet-dump"
SERVING_BOOKSIM2_SEMANTICS_VERSION = \
    "booksim2-fork+B3.7c-embedded-injection"
BOOKSIM_LOWERER_VERSION = "B37/1"

CONFIG_FILE = "config.cfg"
TOPOLOGY_FILE = "topology.anynet"
WORKLOAD_FILE = "workload.trace"
ROUTE_DUMP_FILE = "routing.dump"

# Execution-transport identity. Only SUPERVISED_PROCESS evidence is
# reusable/certifiable; TEST_INJECTED products are unit-test fixtures
# that can never enter the reuse API (enforced in producer's binding
# check, not by caller discipline).
EXECUTION_TRANSPORT_SUPERVISED = EXECUTION_TRANSPORT_SUPERVISED_PROCESS
EXECUTION_TRANSPORT_TEST = EXECUTION_TRANSPORT_TEST_INJECTED

_SEED_DEFAULT = 1
SEED_POLICY_PINNED_DEFAULT = "pinned_default"
SEED_POLICY_EXPLICIT = "explicit"
_SEED_POLICIES = frozenset({SEED_POLICY_PINNED_DEFAULT, SEED_POLICY_EXPLICIT})
_CFG_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;]*);$")
_SAMPLE_PERIOD_MIN = 200
_SAMPLE_PERIOD_MARGIN = 1000

# Authoritative profile/version identity per BookSim target. A forged
# artifact can recompute its own hash; it cannot change what its target's
# certified lowering must be.
_EXPECTED_BOOKSIM_IDENTITY: dict[BackendTarget, tuple[str, str, str]] = {
    BackendTarget.BOOKSIM_STANDALONE: (
        BOOKSIM_STANDALONE_PROFILE, BOOKSIM_BACKEND_SEMANTICS_VERSION,
        BOOKSIM_LOWERER_VERSION),
    BackendTarget.SERVING_BOOKSIM2: (
        SERVING_BOOKSIM2_PROFILE, SERVING_BOOKSIM2_SEMANTICS_VERSION,
        BOOKSIM_LOWERER_VERSION),
}


class BookSimLoweringError(ValueError):
    """The semantic fabric cannot be lowered to BookSim — fail closed."""


class BookSimRouteError(ValueError):
    """Executed route realization is missing/divergent — refuse the run."""


class BackendMaterializationError(ValueError):
    """Rendered inputs cannot be materialized/verified — fail closed."""


# ── closed parameter ownership (B3.7g) ──────────────────────────────────
# One source of truth: backend/booksim_profile.py audits every config
# field the active certified path reads, with owner class and source
# location. The lowerer and renderer emit active audited fields only;
# BACKEND_PROFILE fields carry explicit pinned values from the profile,
# so no result-affecting value comes from a compiled BookSim default.

BOOKSIM_STANDALONE_OWNERSHIP: dict[str, ParameterOwner] = \
    STANDALONE_PROFILE_SPEC.ownership()

# Rendered in a fixed order so the config bytes are deterministic.
# The set must equal the profile's active field set (asserted below).
BOOKSIM_CONFIG_KEY_ORDER: tuple[str, ...] = (
    # topology + projection
    "topology", "network_file", "routing_function",
    # fabric-derived router/VC/flow behavior
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


def _assert_ownership() -> None:
    active = set(STANDALONE_PROFILE_SPEC.active_names())
    serving_active = set(SERVING_PROFILE_SPEC.active_names())
    if active != serving_active:
        raise BookSimLoweringError(
            "standalone and serving profiles audit different field sets")
    if set(BOOKSIM_CONFIG_KEY_ORDER) != active:
        missing = set(BOOKSIM_CONFIG_KEY_ORDER) - active
        extra = active - set(BOOKSIM_CONFIG_KEY_ORDER)
        raise BookSimLoweringError(
            f"config key order does not match the audited active field set "
            f"(unemitted {sorted(missing)}, unlisted {sorted(extra)})")
    for name in active:
        if not STANDALONE_PROFILE_SPEC.source_of(name):
            raise BookSimLoweringError(
                f"audited field {name!r} has no source location")


_assert_ownership()


# ── lowering preconditions ──────────────────────────────────────────────

def _selected_routing_class(bundle: ResolvedFabricBundle) -> str:
    classes = [d.id for d in bundle.router_route.routing_classes]
    if ANYNET_MIN_HOPS not in classes:
        raise BookSimLoweringError(
            f"UNSUPPORTED: certified BookSim profile realizes only "
            f"{ANYNET_MIN_HOPS}; route artifact classes are {classes}")
    vc_classes = {cls for _vc, cls in
                  bundle.vc_assignment.vc_to_routing_class}
    if vc_classes != {ANYNET_MIN_HOPS}:
        raise BookSimLoweringError(
            f"UNSUPPORTED: certified BookSim executes one global routing "
            f"function, but VCs map to routing classes {sorted(vc_classes)}; "
            "per-VC routing-class separation is not representable")
    return ANYNET_MIN_HOPS


def _uniform_link_latency(bundle: ResolvedFabricBundle) -> int:
    """The single link latency, or refuse.

    AnyNet uses the link's numeric value as both channel latency and
    Dijkstra distance (networks/anynet.cpp), so the hop-count
    ANYNET_MIN_HOPS authority is only realizable when every link has the
    same cost. Heterogeneous latency is refused, never approximated.
    """
    latencies = {c.latency_cycles for c in bundle.topology.channels}
    if len(latencies) != 1:
        raise BookSimLoweringError(
            f"UNSUPPORTED: AnyNet couples link latency and route cost; "
            f"heterogeneous channel latencies {sorted(latencies)} would "
            "let BookSim route by weighted shortest path, diverging from "
            "the hop-count RouteArtifact. Separate the semantics or use "
            "uniform latency")
    latency = next(iter(latencies))
    if latency < 1:
        raise BookSimLoweringError(
            f"UNSUPPORTED: certified BookSim requires channel latency >= 1 "
            f"cycle, got {latency}")
    weights = {c.route_weight for c in bundle.topology.channels}
    if weights != {1}:
        raise BookSimLoweringError(
            f"UNSUPPORTED: RouteArtifact {ANYNET_MIN_HOPS} is hop-count "
            f"semantics but channels carry route_weight {sorted(weights)}; "
            "weighted routing is not modeled by this profile")
    pairs: dict[tuple[int, int], int] = {}
    for c in bundle.topology.channels:
        key = (c.src_router, c.dst_router)
        pairs[key] = pairs.get(key, 0) + 1
    parallel = sorted(k for k, n in pairs.items() if n > 1)
    if parallel:
        raise BookSimLoweringError(
            f"UNSUPPORTED: AnyNet cannot represent parallel channels "
            f"between routers {parallel[:3]} (last mention wins in its "
            "parser); parallel-hop realization is ambiguous")
    return latency


def _vc_exactness(vc) -> tuple[bool, str]:
    """Whether the VC class->VC assignment reduces to BookSim's model."""
    if len(vc.traffic_class_to_vcs) == 1:
        (_cls, vcs), = vc.traffic_class_to_vcs
        if vcs == vc.vc_ids:
            return True, ""
    return False, (
        "BookSim trace traffic runs every flow in one class over all VCs; "
        "this artifact assigns traffic classes to VC subsets that the "
        "backend does not execute")


def _transitions_exact(vc) -> bool:
    return vc.allowed_transitions == tuple(
        (i, i) for i in vc.vc_ids)


# ── lowering ────────────────────────────────────────────────────────────

def exact_flit_bytes(packet_format: Any) -> int:
    """Exact bits->bytes conversion for the embedded frontend.

    The ASTRA BookSim frontend takes ``--booksim2-flit-bytes`` and
    divides message bytes by it (Booksim2NetworkApi::sim_send). A width
    that is not byte-exact has no representation; refusing here is what
    keeps a 64-BIT flit from silently becoming the legacy 64-BYTE value.
    """
    bits = packet_format.flit_width_bits
    if bits % 8 != 0:
        raise BookSimLoweringError(
            f"UNSUPPORTED: flit width {bits} bits is not byte-exact "
            f"(flit_bytes = bits/8 required); the embedded frontend takes "
            "an integer number of bytes")
    return bits // 8


def lower_booksim_standalone(
        bundle: ResolvedFabricBundle, *,
        profile: str = BOOKSIM_STANDALONE_PROFILE) -> BackendConfigArtifact:
    """Lower one validated fabric to the certified standalone BookSim
    projection. Raises BookSimLoweringError for UNSUPPORTED fabrics."""
    if profile != BOOKSIM_STANDALONE_PROFILE:
        raise BookSimLoweringError(
            f"unknown standalone BookSim profile {profile!r}")
    return lower_booksim_projection(
        bundle, target=BackendTarget.BOOKSIM_STANDALONE, profile=profile,
        semantics_version=BOOKSIM_BACKEND_SEMANTICS_VERSION,
        lowerer_version=BOOKSIM_LOWERER_VERSION)


def lower_booksim_projection(
        bundle: ResolvedFabricBundle, *, target: BackendTarget,
        profile: str, semantics_version: str,
        lowerer_version: str) -> BackendConfigArtifact:
    """The one BookSim fabric projection, parameterized by backend target.

    Standalone and embedded serving share every fabric-derived parameter;
    only packet/delimitation/route-evidence claims differ, because the
    embedded frontend injects messages through Booksim2NetworkApi instead
    of consuming a trace.
    """
    if target not in (BackendTarget.BOOKSIM_STANDALONE,
                      BackendTarget.SERVING_BOOKSIM2):
        raise BookSimLoweringError(
            f"unsupported BookSim backend target {target.value}")
    serving = target is BackendTarget.SERVING_BOOKSIM2
    try:
        bundle.revalidate()
    except ValueError as exc:
        raise BookSimLoweringError(
            f"bundle failed revalidation before lowering: {exc}") from exc

    topo, att = bundle.topology, bundle.attachment
    rr, rra, vc = bundle.router_route, bundle.resolved_route, \
        bundle.vc_assignment
    pf, rb = bundle.packet_format, bundle.router_behavior
    ad, fabric = bundle.address_decode, bundle.fabric

    selected = _selected_routing_class(bundle)
    latency = _uniform_link_latency(bundle)
    serving_flit_bytes = exact_flit_bytes(pf) if serving else None

    vc_class_exact, vc_class_reason = _vc_exactness(vc)
    transitions_exact = _transitions_exact(vc)

    # VC-range globals are derived exactly as InitializeRoutingMap computes
    # them from num_vcs (they are not consulted for ANY_TYPE trace flits,
    # but they are emitted explicitly instead of inherited).
    half = vc.vc_count // 2

    fabric_params = (
        ("channel_latency_cycles", latency),
        ("alloc_iters", rb.allocator_iterations),
        ("buffer_policy", "private"),
        ("credit_delay", rb.credit_return_latency_cycles),
        ("hold_switch_for_packet", 1 if rb.hold_switch_for_packet else 0),
        ("input_speedup", rb.input_speedup),
        ("internal_speedup", float(rb.internal_speedup)),
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
        ("routing_function", "min"),
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
    profile_spec = SERVING_PROFILE_SPEC if serving \
        else STANDALONE_PROFILE_SPEC
    combined = dict(fabric_params)
    for name, value in profile_spec.pinned_values().items():
        if name in combined:
            raise BookSimLoweringError(
                f"parameter {name!r} is both fabric-derived and "
                "profile-pinned")
        combined[name] = value
    expected_owner = profile_spec.ownership()
    for name in combined:
        if name in _PROJECTION_ONLY_KEYS:
            continue
        if name not in expected_owner:
            raise BookSimLoweringError(
                f"emitted parameter {name!r} is not in the audited active "
                "field set")
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
             (("topology_kind", "anynet"),
              ("parse_back", "required before spawn") if not serving
              else ("parse_back", "required at preparation")),
             domain="the full materialized router/channel graph "
                    "(parallel channels already refused by lowering)"),
        bind(SemanticDimension.ENDPOINT_ATTACHMENT, a_hash,
             RepresentationStatus.EXACT,
             (("node_lines", att.endpoint_count),
              ("ports", "assigned by BookSim; port ids not represented")),
             domain="one endpoint->seat binding each; BookSim reassigns "
                    "port ids"),
        bind(SemanticDimension.CHANNEL_WIDTH, t_hash,
             RepresentationStatus.BACKEND_IRRELEVANT, (),
             reason="BookSim is a flit-count timing model: flit channels "
                    "transfer one flit per cycle and no width-dependent "
                    "serialization/occupancy exists"),
        bind(SemanticDimension.CHANNEL_LATENCY, t_hash,
             RepresentationStatus.EXACT,
             (("anynet_link_weight", latency),),
             domain="uniform channel latency >= 1 cycle only (AnyNet "
                    "couples latency and route cost)"),
        bind(SemanticDimension.ROUTE_WEIGHT, t_hash,
             RepresentationStatus.EXACT, (("route_weight", 1),),
             domain="every channel route_weight == 1 only"),
        bind(SemanticDimension.ROUTE_REALIZATION, rra_hash,
             RepresentationStatus.UNREPRESENTABLE if serving
             else RepresentationStatus.EXACT,
             (("routing_function", "min"),
              ("routing_class", selected),
              ("route_evidence", "no embedded route dump") if serving
              else ("route_evidence", ROUTE_DUMP_FILE)),
             reason="the embedded BookSim frontend exposes no executed-route "
                    "dump; route execution is not proven for serving"
             if serving else "",
             effect=CertificationEffect.BLOCKS_EXACT_FABRIC
             if serving else None,
             domain="" if serving else
             "ANYNET_MIN_HOPS with uniform unit-cost links; the executed "
             "first-hop table is compared mechanically"),
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
             (("routing_function", "min"),),
             domain="all VCs map to the selected ANYNET_MIN_HOPS class"),
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
             "the certified profile has no escape-VC mechanism; a fabric "
             "that designates escape VCs for deadlock freedom is not "
             "representable",
             effect=None if not vc.escape_vcs
             else CertificationEffect.BLOCKS_EXACT_FABRIC,
             domain="escape_vcs == () (trivial policy) only"
             if not vc.escape_vcs else ""),
        bind(SemanticDimension.FLIT_WIDTH, pf_hash,
             RepresentationStatus.DERIVED_EXACT if serving
             else RepresentationStatus.BACKEND_IRRELEVANT,
             (("flit_bytes", serving_flit_bytes),) if serving else (),
             reason="BookSim counts flits; no width/serialization model"
             if not serving else "",
             domain="flit_width_bits % 8 == 0 only (exact bits->bytes)"
             if serving else ""),
        bind(SemanticDimension.PACKET_DELIMITATION, pf_hash,
             RepresentationStatus.UNREPRESENTABLE if serving
             else RepresentationStatus.COARSENED,
             (("packet_size", "not emitted (trace-record authority)"),)
             if not serving else (("injection", "sim_send per message"),),
             reason="the embedded frontend injects ceil(bytes/flit_bytes) "
                    "flits as one packet per sim_send; BOUNDED_WORMHOLE "
                    "fragmentation and packet delimitation are not "
                    "executed"
             if serving else
             "BookSim executes the packet boundaries encoded in the "
             "trace records; it does not model BOUNDED_WORMHOLE "
             "fragmentation"),
        bind(SemanticDimension.PACKET_MAX_FLITS, pf_hash,
             RepresentationStatus.UNREPRESENTABLE if serving
             else RepresentationStatus.DERIVED_EXACT,
             (("trace_validation",
               f"1 <= packet_size <= {pf.max_packet_flits}"),)
             if not serving else
             (("embedded_mtu", "not proven/deferred to Wave D"),),
             reason="max_packet_flits is not enforced for embedded "
                    "sim_send traffic; the optional embedded-MTU "
                    "fragmentation mechanism is not activated or proven"
             if serving else "",
             domain="" if serving else
             "every trace packet size in [1, max_packet_flits] only"),
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
            backend_target=target,
            backend_profile=profile,
            backend_semantics_version=semantics_version,
            lowerer_version=lowerer_version,
            resolved_fabric_hash=bundle.resolved_fabric
            .resolved_fabric_hash(),
            fabric_hash=fabric.fabric_hash(),
            normalized_parameters=params,
            semantic_bindings=bindings,
        )
    except BackendConfigError as exc:  # pragma: no cover - contract bug
        raise BookSimLoweringError(
            f"lowering produced an invalid backend artifact: {exc}") from exc
    for key, _value in artifact.normalized_parameters:
        if key in _PROJECTION_ONLY_KEYS:
            continue
        if key not in BOOKSIM_STANDALONE_OWNERSHIP:
            raise BookSimLoweringError(
                f"emitted parameter {key!r} has no ownership entry")
    return artifact


# ── deterministic rendering ─────────────────────────────────────────────

def assert_canonical_booksim_projection(
        bundle: ResolvedFabricBundle,
        config: BackendConfigArtifact) -> BackendConfigArtifact:
    """Prove ``config`` IS the canonical lowering of ``bundle``.

    A BackendConfigArtifact can be internally hash-consistent, bind the
    right fabric/resolved identities, and still not be the authorized
    lowering of that fabric (recomputed hash + forged parameters). This
    re-derives the expected artifact for the config's target/profile
    identity and requires complete canonical identity equality. Hash
    consistency alone is never accepted.

    Returns the freshly derived canonical artifact.
    """
    if config.backend_target not in _EXPECTED_BOOKSIM_IDENTITY:
        raise BookSimLoweringError(
            f"no canonical BookSim lowering for target "
            f"{config.backend_target.value}")
    profile, semantics, lowerer = _EXPECTED_BOOKSIM_IDENTITY[
        config.backend_target]
    if config.backend_profile != profile:
        raise BookSimLoweringError(
            f"noncanonical backend_profile {config.backend_profile!r}; "
            f"{config.backend_target.value} requires {profile!r}")
    if config.backend_semantics_version != semantics:
        raise BookSimLoweringError(
            f"noncanonical backend_semantics_version "
            f"{config.backend_semantics_version!r}; expected {semantics!r}")
    if config.lowerer_version != lowerer:
        raise BookSimLoweringError(
            f"noncanonical lowerer_version {config.lowerer_version!r}; "
            f"expected {lowerer!r}")
    if config.fabric_hash != bundle.fabric.fabric_hash():
        raise BookSimLoweringError(
            "config fabric_hash does not match the supplied bundle")
    if config.resolved_fabric_hash != \
            bundle.resolved_fabric.resolved_fabric_hash():
        raise BookSimLoweringError(
            "config resolved_fabric_hash does not match the supplied "
            "bundle")
    expected = lower_booksim_projection(
        bundle, target=config.backend_target, profile=profile,
        semantics_version=semantics, lowerer_version=lowerer)
    actual_identity = config.identity_dict()
    expected_identity = expected.identity_dict()
    if actual_identity != expected_identity:
        differing = sorted(
            key for key in set(actual_identity) | set(expected_identity)
            if actual_identity.get(key) != expected_identity.get(key))
        raise BookSimLoweringError(
            f"noncanonical BookSim artifact: it does not equal the "
            f"canonical lowering of this bundle (differs in "
            f"{differing})")
    return expected


def parse_booksim_config_values(text: str) -> dict[str, str]:
    """Parse a rendered BookSim config into name -> raw value strings.

    The single parser for rendered certified configs (runner gate checks
    and the serving consumption validator both use it). Fail-closed:
    malformed non-comment lines and duplicate keys are refused rather
    than silently skipped or last-one-wins.
    """
    values: dict[str, str] = {}
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        m = _CFG_LINE_RE.match(line)
        if not m:
            raise BookSimLoweringError(
                f"malformed certified config line {line_no}: {raw!r}")
        key, value = m.group(1), m.group(2).strip()
        if key in values:
            raise BookSimLoweringError(
                f"duplicate certified config key {key!r} at line {line_no}")
        values[key] = value
    return values


def verify_rendered_profile_gates(rendered_values: dict[str, str]) -> None:
    """Verify the exact bytes about to execute satisfy every site pin gate.

    The static source audit proves these gates make inactive backend
    source paths unreachable; this is the runtime half: the rendered
    config must actually hold them. Mechanism gates are declaration-only
    here. No C++ source is scanned at runtime.
    """
    from .source_audit import (GATED_READ_SITES, SourceAuditError,
                               verify_site_gates)
    try:
        verify_site_gates(GATED_READ_SITES, rendered_values)
    except SourceAuditError as exc:
        raise BookSimLoweringError(
            f"rendered config violates certified profile gates: {exc}"
        ) from exc


@dataclass(frozen=True)
class TraceSummary:
    dialect: str
    num_packets: int
    max_timestamp: int
    endpoint_count: int


@dataclass(frozen=True)
class RenderedBackend:
    files: tuple[tuple[str, bytes], ...]
    sample_period: int
    trace_summary: TraceSummary

    def file(self, logical_name: str) -> bytes:
        for name, data in self.files:
            if name == logical_name:
                return data
        raise BackendMaterializationError(
            f"no rendered file {logical_name!r}")


def _render_anynet(bundle: ResolvedFabricBundle) -> bytes:
    topo, att = bundle.topology, bundle.attachment
    by_router: dict[int, list[int]] = {}
    for ep in att.endpoints:
        by_router.setdefault(ep.router_id, []).append(ep.endpoint_id)
    outgoing: dict[int, list[Any]] = {}
    for c in topo.channels:
        outgoing.setdefault(c.src_router, []).append(c)
    lines: list[str] = []
    for r in range(topo.router_count):
        parts = [f"router {r}"]
        for node in sorted(by_router.get(r, ())):
            parts.append(f"node {node}")
        for c in sorted(outgoing.get(r, ()),
                        key=lambda c: (c.dst_router, c.channel_id)):
            parts.append(f"router {c.dst_router} {c.latency_cycles}")
        lines.append(" ".join(parts))
    return ("\n".join(lines) + "\n").encode()


def render_topology_anynet(bundle: ResolvedFabricBundle) -> bytes:
    """Exact AnyNet render of the materialized topology + attachment."""
    return _render_anynet(bundle)


def _format_cfg_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    raise BookSimLoweringError(
        f"cannot render config value {value!r} ({type(value).__name__})")


def _scan_trace(trace_bytes: bytes, *, endpoint_count: int,
                max_packet_flits: int) -> TraceSummary:
    """Strictly validate the BookSim trace grammar (both dialects).

    Mirrors tracetrafficmanager.cpp: first data line decides CSV vs
    whitespace; blank and '#'/'%' lines are skipped; nodes must be within
    the attachment universe; packet sizes positive and within the
    PacketFormatArtifact cap. Any violation refuses the certified run.
    """
    try:
        text = trace_bytes.decode()
    except UnicodeDecodeError as exc:
        raise BookSimLoweringError(f"workload trace is not UTF-8: {exc}")
    dialect = None
    num = 0
    max_ts = 0
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line[0] in ("#", "%"):
            continue
        if dialect is None:
            dialect = "csv" if "," in line else "whitespace"
        if dialect == "csv":
            fields = [f.strip() for f in line.split(",")]
            if len(fields) < 5:
                raise BookSimLoweringError(
                    f"trace line {line_no}: CSV dialect needs at least 5 "
                    f"fields (timestamp,src,dst,type,packet_size): {line!r}")
            if not re.fullmatch(r"\d+", fields[0]):
                # Header row: skip like tracetrafficmanager.cpp.
                if num == 0:
                    continue
                raise BookSimLoweringError(
                    f"trace line {line_no}: non-numeric timestamp "
                    f"{fields[0]!r}")
            try:
                ts, src, dst = int(fields[0]), int(fields[1]), int(fields[2])
                size = int(fields[4])
            except ValueError as exc:
                raise BookSimLoweringError(
                    f"trace line {line_no}: non-integer field: {exc}")
            if not fields[3]:
                raise BookSimLoweringError(
                    f"trace line {line_no}: empty type field")
        else:
            parts = line.split()
            if len(parts) < 5:
                raise BookSimLoweringError(
                    f"trace line {line_no}: whitespace dialect needs "
                    f"cyc src cl dst sz: {line!r}")
            try:
                ts, src = int(parts[0]), int(parts[1])
                int(parts[2])  # class: inert metadata in single-class runs
                dst, size = int(parts[3]), int(parts[4])
            except ValueError as exc:
                raise BookSimLoweringError(
                    f"trace line {line_no}: non-integer field: {exc}")
        if ts < 0:
            raise BookSimLoweringError(
                f"trace line {line_no}: negative timestamp {ts}")
        if not (0 <= src < endpoint_count) or not (0 <= dst < endpoint_count):
            raise BookSimLoweringError(
                f"trace line {line_no}: node outside [0, {endpoint_count}): "
                f"src={src} dst={dst}")
        if size < 1:
            raise BookSimLoweringError(
                f"trace line {line_no}: non-positive packet_size {size}")
        if size > max_packet_flits:
            raise BookSimLoweringError(
                f"trace line {line_no}: packet_size {size} exceeds "
                f"PacketFormatArtifact.max_packet_flits "
                f"{max_packet_flits}")
        num += 1
        if ts > max_ts:
            max_ts = ts
    if dialect is None:
        raise BookSimLoweringError("workload trace has no parseable packets")
    return TraceSummary(dialect=dialect, num_packets=num,
                        max_timestamp=max_ts, endpoint_count=endpoint_count)


def render_booksim_standalone(
        bundle: ResolvedFabricBundle, config: BackendConfigArtifact, *,
        workload_trace: bytes, seed: int | None = None) -> RenderedBackend:
    """Render exact, path-free backend inputs from artifact + workload."""
    if config.backend_target is not BackendTarget.BOOKSIM_STANDALONE:
        raise BookSimLoweringError(
            f"config target {config.backend_target.value} is not "
            f"{BackendTarget.BOOKSIM_STANDALONE.value}")
    assert_canonical_booksim_projection(bundle, config)
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
    sample_period = max(_SAMPLE_PERIOD_MIN,
                        summary.max_timestamp + 1 + _SAMPLE_PERIOD_MARGIN)

    params = dict(config.normalized_parameters)
    missing = [k for k in ("routing_class", "channel_latency_cycles",
                           "topology") if k not in params]
    if missing:
        raise BookSimLoweringError(
            f"config is missing projection parameters {missing}")

    values: dict[str, Any] = {
        "network_file": TOPOLOGY_FILE,
        "traffic": f"trace({WORKLOAD_FILE})",
        "sample_period": sample_period,
        "seed": _SEED_DEFAULT if seed is None else seed,
        "routing_dump_file": ROUTE_DUMP_FILE,
    }
    for key, value in config.normalized_parameters:
        if key in _PROJECTION_ONLY_KEYS:
            continue
        if key in values:
            raise BookSimLoweringError(
                f"duplicate rendered parameter {key!r}")
        values[key] = value
    unowned = set(values) - set(BOOKSIM_STANDALONE_OWNERSHIP)
    if unowned:
        raise BookSimLoweringError(
            f"rendered parameters without an owner: {sorted(unowned)}")
    missing_keys = set(BOOKSIM_STANDALONE_OWNERSHIP) - set(values)
    if missing_keys:
        raise BookSimLoweringError(
            f"ownership table keys not rendered: {sorted(missing_keys)}")

    cfg_lines = [f"{key} = {_format_cfg_value(values[key])};"
                 for key in BOOKSIM_CONFIG_KEY_ORDER]
    cfg = ("\n".join(cfg_lines) + "\n").encode()
    files = ((CONFIG_FILE, cfg), (TOPOLOGY_FILE, _render_anynet(bundle)),
             (WORKLOAD_FILE, workload_trace))
    return RenderedBackend(files=tuple(sorted(files)),
                           sample_period=sample_period,
                           trace_summary=summary)


# ── input binding ───────────────────────────────────────────────────────

_ROLE_BY_NAME = {CONFIG_FILE: "booksim_config",
                 TOPOLOGY_FILE: "topology",
                 WORKLOAD_FILE: "workload"}


def bind_booksim_inputs(
        config: BackendConfigArtifact, rendered: RenderedBackend, *,
        workload_hash: str, seed: int | None = None) -> BackendInputManifest:
    """Bind exact execution inputs to a path-independent config artifact."""
    if sha256_bytes(rendered.file(WORKLOAD_FILE)) != workload_hash:
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
        invocation_args=(("config-file", CONFIG_FILE),),
    )


@dataclass(frozen=True)
class PreparedBackend:
    """A lowered + rendered + input-bound certified backend invocation."""

    bundle: ResolvedFabricBundle
    config: BackendConfigArtifact
    rendered: RenderedBackend
    manifest: BackendInputManifest


def prepare_booksim_standalone(
        bundle: ResolvedFabricBundle, *, workload_trace: bytes,
        seed: int | None = None,
        profile: str = BOOKSIM_STANDALONE_PROFILE) -> PreparedBackend:
    config = lower_booksim_standalone(bundle, profile=profile)
    rendered = render_booksim_standalone(
        bundle, config, workload_trace=workload_trace, seed=seed)
    manifest = bind_booksim_inputs(
        config, rendered, workload_hash=sha256_bytes(workload_trace),
        seed=seed)
    return PreparedBackend(bundle=bundle, config=config, rendered=rendered,
                           manifest=manifest)


def _canonical_seed_argument(
        manifest: BackendInputManifest) -> int | None:
    """Map certified seed policy to the renderer's seed argument.

    ``pinned_default`` means the certified default seed and is rendered
    as ``seed=None``; ``explicit`` must carry that exact non-negative
    integer. Any other policy is refused.
    """
    policy, seed = manifest.seed_policy, manifest.seed
    if policy == SEED_POLICY_PINNED_DEFAULT:
        if seed != _SEED_DEFAULT:
            raise BookSimLoweringError(
                f"seed_policy={SEED_POLICY_PINNED_DEFAULT} requires the "
                f"certified default seed {_SEED_DEFAULT}, got {seed!r}")
        return None
    if policy == SEED_POLICY_EXPLICIT:
        if type(seed) is not int or seed < 0:
            raise BookSimLoweringError(
                f"seed_policy={SEED_POLICY_EXPLICIT} requires a "
                f"non-negative int seed, got {seed!r}")
        return seed
    raise BookSimLoweringError(
        f"unsupported seed_policy {policy!r}; certified standalone runs "
        f"use {sorted(_SEED_POLICIES)}")


def assert_canonical_prepared_booksim(
        prepared: PreparedBackend) -> None:
    """Prove the whole prepared chain, not its pieces independently:

        bundle -> canonical config -> exact rendered bytes
               -> exact canonical BackendInputManifest

    A canonical config paired with forged rendered bytes and a freshly
    recomputed, internally valid manifest is refused here: the workload
    bytes are taken as the execution-input authority, the renderer is
    re-run for the manifest's seed intent, every file is compared by
    exact bytes, and the manifest is re-bound and compared by complete
    identity. Hash consistency alone is never accepted at any boundary.
    """
    bundle, config = prepared.bundle, prepared.config
    rendered, manifest = prepared.rendered, prepared.manifest
    assert_canonical_booksim_projection(bundle, config)
    try:
        workload = rendered.file(WORKLOAD_FILE)
    except BackendMaterializationError as exc:
        raise BookSimLoweringError(
            f"prepared backend does not contain the canonical workload "
            f"input: {exc}") from exc
    seed_arg = _canonical_seed_argument(manifest)
    expected_rendered = render_booksim_standalone(
        bundle, config, workload_trace=workload, seed=seed_arg)
    supplied_names = [name for name, _ in rendered.files]
    expected_names = [name for name, _ in expected_rendered.files]
    if len(set(supplied_names)) != len(supplied_names):
        raise BookSimLoweringError(
            "prepared backend rendered files contain duplicate logical "
            "names; the canonical file set has one entry per name")
    extra = sorted(set(supplied_names) - set(expected_names))
    missing = sorted(set(expected_names) - set(supplied_names))
    if extra or missing:
        raise BookSimLoweringError(
            f"prepared backend file set is not canonical (missing "
            f"{missing}, extra {extra})")
    for name, data in expected_rendered.files:
        if rendered.file(name) != data:
            raise BookSimLoweringError(
                f"rendered {name!r} is not the canonical rendering of this "
                f"config/workload/seed (byte mismatch); a fresh manifest "
                f"does not authorize these bytes")
    if rendered.sample_period != expected_rendered.sample_period or \
            rendered.trace_summary != expected_rendered.trace_summary:
        raise BookSimLoweringError(
            "rendered trace summary/sample_period is not the canonical "
            "derivation from the workload bytes")
    expected_manifest = bind_booksim_inputs(
        config, expected_rendered, workload_hash=sha256_bytes(workload),
        seed=seed_arg)
    actual_identity = manifest.identity_dict()
    expected_identity = expected_manifest.identity_dict()
    if actual_identity != expected_identity:
        differing = sorted(
            key for key in set(actual_identity) | set(expected_identity)
            if actual_identity.get(key) != expected_identity.get(key))
        raise BookSimLoweringError(
            f"prepared manifest is not the canonical binding of the "
            f"rendered inputs (differs in {differing})")


# ── materialization / verification ──────────────────────────────────────

def _write_bytes_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def materialize_backend(rendered: RenderedBackend,
                        manifest: BackendInputManifest,
                        directory: Path) -> dict[str, Path]:
    """Write exact bytes into a run-owned dir; refuse content conflicts."""
    directory.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, data in rendered.files:
        record = manifest.input(name)
        actual = sha256_bytes(data)
        if actual != record.sha256 or len(data) != record.size:
            raise BackendMaterializationError(
                f"rendered {name!r} does not match the manifest "
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


def verify_materialized(manifest: BackendInputManifest,
                        directory: Path) -> None:
    """Re-hash every input; called immediately before process spawn."""
    for record in manifest.rendered_inputs:
        path = directory / record.logical_name
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise BackendMaterializationError(
                f"materialized input {record.logical_name!r} unreadable: "
                f"{exc}") from exc
        actual = sha256_bytes(data)
        if actual != record.sha256:
            raise BackendMaterializationError(
                f"materialized input {record.logical_name!r} was modified "
                f"after planning: sha {actual} != {record.sha256} — "
                "refusing to execute")
        if len(data) != record.size:
            raise BackendMaterializationError(
                f"materialized input {record.logical_name!r} size changed "
                f"({len(data)} != {record.size}) — refusing to execute")


def verify_anynet_roundtrip(bundle: ResolvedFabricBundle,
                            anynet_path: Path) -> dict[str, int]:
    """Parse the rendered anynet back and compare with the topology."""
    graph = parse_anynet_file(anynet_path)
    expected_nodes = {ep.endpoint_id: ep.router_id
                      for ep in bundle.attachment.endpoints}
    if graph.node_router != expected_nodes:
        raise BackendMaterializationError(
            "rendered anynet node attachments do not match "
            "AgentAttachmentArtifact")
    if graph.n_routers != bundle.topology.router_count:
        raise BackendMaterializationError(
            f"rendered anynet has {graph.n_routers} routers, topology has "
            f"{bundle.topology.router_count}")
    expected_edges = {(c.src_router, c.dst_router)
                      for c in bundle.topology.channels}
    rendered_edges = {(a, b) for a, bs in graph.router_adj.items()
                      for b in bs}
    if rendered_edges != expected_edges:
        missing = sorted(expected_edges - rendered_edges)[:3]
        extra = sorted(rendered_edges - expected_edges)[:3]
        raise BackendMaterializationError(
            f"rendered anynet adjacency does not match topology channels "
            f"(missing {missing}, extra {extra})")
    expected_weights = {(c.src_router, c.dst_router): c.latency_cycles
                        for c in bundle.topology.channels}
    if graph.router_weight != expected_weights:
        mismatch = [(k, graph.router_weight.get(k), v)
                    for k, v in sorted(expected_weights.items())
                    if graph.router_weight.get(k) != v][:3]
        raise BackendMaterializationError(
            f"rendered anynet link weights do not match topology channel "
            f"latencies (first mismatches: {mismatch})")
    return {"routers": graph.n_routers, "nodes": graph.n_nodes,
            "directed_edges": len(expected_edges)}


# ── executed-route proof ────────────────────────────────────────────────

_DUMP_RE = re.compile(
    r"^src_router (\d+) dst_node (\d+) next_router (\d+) port (\d+)$")


def expected_route_table(bundle: ResolvedFabricBundle,
                         config: BackendConfigArtifact
                         ) -> dict[tuple[int, int], int]:
    """Expected executed first-hop table: (router, endpoint) -> next router.

    Derived from RouteArtifact for the artifact's selected routing class
    and every attached endpoint. This is the semantic expectation the
    executed dump is compared against; exported so golden corpora can
    pin it without executing the backend.
    """
    selected = dict(config.normalized_parameters)["routing_class"]
    endpoints = bundle.attachment.endpoints
    e2r = dict(bundle.resolved_route.endpoint_to_router)
    channels = {c.channel_id: c for c in bundle.topology.channels}
    entries = bundle.router_route.entries
    expected: dict[tuple[int, int], int] = {}
    for r in range(bundle.topology.router_count):
        for ep in endpoints:
            dst_router = e2r[ep.endpoint_id]
            if r == dst_router:
                expected[(r, ep.endpoint_id)] = r
                continue
            key = (selected, r, dst_router)
            if key not in entries:
                raise BookSimRouteError(
                    f"RouteArtifact has no entry for {key!r}")
            channel = channels[entries[key]]
            if channel.src_router != r:
                raise BookSimRouteError(
                    f"RouteArtifact ({selected},{r},{dst_router}) -> "
                    f"channel {channel.channel_id} leaves router "
                    f"{channel.src_router}, not {r}")
            expected[(r, ep.endpoint_id)] = channel.dst_router
    return expected


def compare_route_realization(
        bundle: ResolvedFabricBundle, config: BackendConfigArtifact,
        dump_path: Path) -> dict[str, Any]:
    """Mechanically compare the executed first-hop table with the
    authoritative RouteArtifact (all routers x all attached endpoints)."""
    selected = dict(config.normalized_parameters)["routing_class"]
    try:
        text = dump_path.read_text()
    except OSError as exc:
        raise BookSimRouteError(
            f"BookSim produced no route dump at {dump_path} ({exc}); the "
            "certified profile requires executed-route evidence") from exc
    executed: dict[tuple[int, int], int] = {}
    for line_no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _DUMP_RE.match(line)
        if not m:
            raise BookSimRouteError(
                f"route dump line {line_no} is malformed: {line!r}")
        src, node, nxt, _port = (int(g) for g in m.groups())
        key = (src, node)
        if key in executed:
            raise BookSimRouteError(
                f"route dump repeats (src_router={src}, dst_node={node})")
        executed[key] = nxt

    expected = expected_route_table(bundle, config)

    missing = sorted(set(expected) - set(executed))
    extra = sorted(set(executed) - set(expected))
    if missing or extra:
        raise BookSimRouteError(
            f"executed route dump coverage differs from the expected "
            f"table (missing {missing[:3]}, extra {extra[:3]})")
    mismatches = [(k, expected[k], executed[k])
                  for k in sorted(expected) if expected[k] != executed[k]]
    if mismatches:
        raise BookSimRouteError(
            f"executed route realization diverges from RouteArtifact in "
            f"{len(mismatches)} entries, e.g. {mismatches[:3]} — the "
            "fabric is NOT executed as declared")

    from veritx_dse.core.spec import canonical_json
    return {
        "status": "EXACT",
        "routing_class": selected,
        "pairs_compared": len(expected),
        "expected_sha256": hashlib.sha256(canonical_json(
            [[r, e, expected[(r, e)]] for r, e in sorted(expected)]
        ).encode()).hexdigest(),
        "executed_sha256": hashlib.sha256(canonical_json(
            [[r, e, executed[(r, e)]] for r, e in sorted(executed)]
        ).encode()).hexdigest(),
    }


# ── certified execution ─────────────────────────────────────────────────

def execution_qualification(
        config: BackendConfigArtifact) -> ExecutionQualification:
    """What a run of this artifact is — never a blanket "certified".

    Derived strictly from the bindings:
      * UNSUPPORTED_EXECUTION present  -> EXECUTION_UNSUPPORTED (refuse)
      * BLOCKS_EXACT_FABRIC present    -> EXECUTED_BLOCKED_FROM_EXACT
      * all exact/irrelevant           -> EXECUTED_EXACT
      * otherwise                      -> EXECUTED_WITH_DECLARED_LOSS
    """
    effects = {b.certification_effect for b in config.semantic_bindings}
    if CertificationEffect.UNSUPPORTED_EXECUTION in effects:
        return ExecutionQualification.EXECUTION_UNSUPPORTED
    if CertificationEffect.BLOCKS_EXACT_FABRIC in effects:
        return ExecutionQualification.EXECUTED_BLOCKED_FROM_EXACT
    if config.exact_fabric_eligible():
        return ExecutionQualification.EXECUTED_EXACT
    return ExecutionQualification.EXECUTED_WITH_DECLARED_LOSS


def assert_executable(config: BackendConfigArtifact) -> ExecutionQualification:
    """Refuse UNSUPPORTED_EXECUTION before any process/materialization."""
    qualification = execution_qualification(config)
    if qualification is ExecutionQualification.EXECUTION_UNSUPPORTED:
        blocked = ", ".join(
            b.dimension.value for b in config.semantic_bindings
            if b.certification_effect is
            CertificationEffect.UNSUPPORTED_EXECUTION)
        target = config.backend_target.value
        raise BookSimLoweringError(
            f"UNSUPPORTED_EXECUTION: refusing to run {target} with "
            f"unresolved semantics: {blocked}")
    return qualification


@dataclass(frozen=True)
class CertifiedBookSimEvidence:
    """Everything a certified standalone BookSim run must carry."""

    backend_config_hash: str
    backend_input_hash: str
    resolved_fabric_hash: str
    fabric_hash: str
    route_equivalence: str
    route_expected_sha256: str
    route_executed_sha256: str
    route_pairs_compared: int
    exact_fabric_eligible: bool
    qualification: str
    semantic_loss: tuple[dict[str, Any], ...]
    stats: dict[str, Any]
    exit_status: int
    wall_time_s: float
    command: tuple[str, ...]
    backend_dir: str
    workload_hash: str | None = None
    seed: int | None = None
    seed_policy: str = ""
    rendered_inputs: tuple[dict[str, Any], ...] = ()
    invocation_args: tuple[tuple[str, str], ...] = ()
    booksim_binary_sha256: str | None = None
    producer_source_revision: str | None = None
    producer_source_dirty: bool | None = None
    producer_source_dirty_digest: str | None = None
    producer_tool_identity: str = ""
    execution_transport: str = EXECUTION_TRANSPORT_SUPERVISED
    parser_version: str = PARSER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_config_hash": self.backend_config_hash,
            "backend_input_hash": self.backend_input_hash,
            "resolved_fabric_hash": self.resolved_fabric_hash,
            "fabric_hash": self.fabric_hash,
            "route_equivalence": self.route_equivalence,
            "route_expected_sha256": self.route_expected_sha256,
            "route_executed_sha256": self.route_executed_sha256,
            "route_pairs_compared": self.route_pairs_compared,
            "exact_fabric_eligible": self.exact_fabric_eligible,
            "qualification": self.qualification,
            "semantic_loss": [dict(row) for row in self.semantic_loss],
            "stats": dict(self.stats),
            "exit_status": self.exit_status,
            "wall_time_s": self.wall_time_s,
            "command": list(self.command),
            "backend_dir": self.backend_dir,
            "workload_hash": self.workload_hash,
            "seed": self.seed,
            "seed_policy": self.seed_policy,
            "rendered_inputs": [dict(row) for row in self.rendered_inputs],
            "invocation_args": {k: v
                                for k, v in self.invocation_args},
            "booksim_binary_sha256": self.booksim_binary_sha256,
            "producer_source_revision": self.producer_source_revision,
            "producer_source_dirty": self.producer_source_dirty,
            "producer_source_dirty_digest":
                self.producer_source_dirty_digest,
            "producer_tool_identity": self.producer_tool_identity,
            "execution_transport": self.execution_transport,
            "parser_version": self.parser_version,
        }


def _execute_prepared(
        prepared: PreparedBackend, *,
        run_dir: Path,
        repo_root: Path,
        timeout: int,
        binary: Path | None,
        transport: str,
        runner: Any,
) -> CertifiedBookSimEvidence:
    """Shared certified-execution core (transport-explicit).

    Only ``run_qualified_booksim`` (authoritative supervised process
    runner) may emit reusable ``EXECUTED_*`` evidence; the test-only
    seam below passes an injected runner with the TEST transport whose
    products the reuse API mechanically refuses.

    Order: revalidate bundle → canonical config → canonical prepared
    inputs (exact render + manifest binding) → qualification guard →
    producer identity (canonical absolute path, pre-spawn digest, fail
    closed) → materialize → parse-back topology → verify hashes
    IMMEDIATELY BEFORE spawn → runtime profile gates → fresh route-output
    slot → final producer recheck → run → executed-route proof → parse
    stats. Any tamper/stale/forged/unidentified input refuses before
    materialization or spawn.
    """
    import time

    from veritx_dse.core.errors import BookSimError, TimeoutError
    from veritx_dse.simulation.booksim import parse_output

    config, manifest, rendered = (prepared.config, prepared.manifest,
                                  prepared.rendered)
    bundle = prepared.bundle

    try:
        bundle.revalidate()
    except ValueError as exc:
        raise BookSimLoweringError(
            f"bundle failed revalidation before execution: {exc}") from exc
    assert_canonical_booksim_projection(bundle, config)
    if config.backend_config_hash() != manifest.backend_config_hash:
        raise BackendMaterializationError(
            "manifest does not bind this backend config artifact")
    if config.fabric_hash != bundle.fabric.fabric_hash() or \
            config.resolved_fabric_hash != \
            bundle.resolved_fabric.resolved_fabric_hash():
        raise BackendMaterializationError(
            "backend config does not bind the supplied bundle")
    # Whole-chain proof: canonical config -> exact rendered bytes ->
    # exact canonical input manifest. Refuses before any filesystem
    # materialization or process spawn.
    assert_canonical_prepared_booksim(prepared)
    qualification = assert_executable(config)

    bin_path = _resolve_producer_path(binary, repo_root)
    # B-FINAL: identify the exact producer BEFORE spawn (and before any
    # filesystem materialization) and bind it into the evidence. An
    # unreadable binary refuses here — certified evidence never carries
    # an unknown producer digest.
    producer = resolve_producer_identity(bin_path, repo_root=Path(repo_root))

    backend_dir = Path(run_dir) / "backend"
    materialize_backend(rendered, manifest, backend_dir)
    verify_anynet_roundtrip(bundle, backend_dir / TOPOLOGY_FILE)
    # Re-verify the exact bytes the child is about to execute.
    verify_materialized(manifest, backend_dir)
    # Runtime half of the profile-gate proof: the exact rendered bytes must
    # satisfy every site pin gate before anything spawns.
    verify_rendered_profile_gates(parse_booksim_config_values(
        (backend_dir / CONFIG_FILE).read_text()))

    # B-FINAL.2: the executed-route output must be fresh output of THIS
    # attempt. A pre-existing routing.dump (e.g. from an earlier attempt
    # sharing the directory) is stale/ambiguous: it is refused, never
    # silently accepted as current evidence and never silently deleted.
    # Certified re-execution belongs in a new attempt directory.
    route_dump_path = backend_dir / ROUTE_DUMP_FILE
    if route_dump_path.exists():
        raise BookSimRouteError(
            f"refusing certified execution: {route_dump_path} already "
            f"exists before spawn; a certified attempt requires a fresh "
            f"attempt output slot")

    cmd = (str(bin_path), CONFIG_FILE)

    # B-FINAL.1: close the hash-to-exec window. The producer was
    # identified before materialization for early refusal; rehash the
    # exact bytes about to spawn and require the identical producer. A
    # binary replaced in between invalidates the planned execution — it
    # must be restarted, never silently adopted.
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
            f"certified BookSim timed out after {timeout}s",
            returncode=res.returncode, stdout=res.stdout, stderr=res.stderr)
    if res.returncode != 0:
        raise BookSimError(
            f"certified BookSim exited {res.returncode}",
            returncode=res.returncode, stdout=res.stdout, stderr=res.stderr)

    stats = parse_output(res.stdout or "")
    if stats.get("delivered", 0) == 0:
        raise BookSimError(
            "certified BookSim delivered 0 packets — topology cannot carry "
            "this workload",
            returncode=res.returncode, stdout=res.stdout, stderr=res.stderr)
    if "latency" not in stats:
        raise BookSimError(
            "certified BookSim produced no latency measurement",
            returncode=res.returncode, stdout=res.stdout, stderr=res.stderr)

    route = compare_route_realization(
        bundle, config, backend_dir / ROUTE_DUMP_FILE)

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


def _resolve_producer_path(binary: Path | None,
                           repo_root: Path) -> Path:
    """Canonicalize the producer to one absolute resolved path.

    A relative executable path must never be hashed under one working
    directory and executed under another: the path is resolved strictly
    (symlinks included) before any hashing, and that same absolute path
    feeds the initial digest, the pre-spawn recheck, argv and evidence.
    """
    from veritx_dse.simulation.booksim import find_booksim_bin
    raw = binary if binary is not None else find_booksim_bin(repo_root)
    try:
        return Path(raw).resolve(strict=True)
    except OSError as exc:
        raise ProducerError(
            f"cannot resolve execution producer {raw}: {exc}; refusing "
            f"to hash one path and execute another") from exc


def run_qualified_booksim(
        prepared: PreparedBackend, *,
        run_dir: Path,
        repo_root: Path,
        timeout: int = 60,
        binary: Path | None = None,
) -> CertifiedBookSimEvidence:
    """Execute one prepared BookSim run via the authoritative process.

    This is the ONLY entry point that can emit reusable ``EXECUTED_*``
    evidence: it always spawns the identified BookSim binary through the
    supervised process runner. There is no runner parameter — injected
    transports live behind the explicitly test-only seam below, whose
    products the reuse API mechanically refuses.
    """
    from veritx_dse.core.process import supervised_run

    def _supervised(c: Any, cwd: str, t: int) -> Any:
        return supervised_run(c, cwd=cwd, timeout=t, on_timeout="complete")

    return _execute_prepared(
        prepared, run_dir=run_dir, repo_root=repo_root, timeout=timeout,
        binary=binary, transport=EXECUTION_TRANSPORT_SUPERVISED,
        runner=_supervised)


def _run_qualified_booksim_with_runner_for_test(
        prepared: PreparedBackend, *,
        run_dir: Path,
        repo_root: Path,
        timeout: int = 60,
        runner: Any = None,
        binary: Path | None = None,
) -> CertifiedBookSimEvidence:
    """Test-only execution seam with an injected transport.

    Unit tests use this to exercise validation ordering, refusal paths
    and semantic classification without spawning BookSim. Products carry
    ``execution_transport=TEST_INJECTED`` and can NEVER pass
    ``verify_reusable_evidence`` — a fake runner that never executes the
    binary cannot fabricate reusable ``EXECUTED_*`` evidence.
    """
    if runner is None:
        raise BookSimLoweringError(
            "test seam requires an explicit injected runner")
    return _execute_prepared(
        prepared, run_dir=run_dir, repo_root=repo_root, timeout=timeout,
        binary=binary, transport=EXECUTION_TRANSPORT_TEST, runner=runner)


def run_certified_booksim(
        prepared: PreparedBackend, **kwargs: Any) -> CertifiedBookSimEvidence:
    """Compatibility alias for :func:`run_qualified_booksim`.

    The old name overstated lossy runs; callers should read
    ``evidence.qualification`` rather than treating success as
    exact-fabric certification.
    """
    return run_qualified_booksim(prepared, **kwargs)


__all__ = [
    "BOOKSIM_BACKEND_SEMANTICS_VERSION",
    "BOOKSIM_LOWERER_VERSION",
    "BOOKSIM_STANDALONE_OWNERSHIP",
    "BOOKSIM_STANDALONE_PROFILE",
    "SERVING_BOOKSIM2_PROFILE",
    "SERVING_BOOKSIM2_SEMANTICS_VERSION",
    "BackendMaterializationError",
    "BookSimLoweringError",
    "BookSimRouteError",
    "CertifiedBookSimEvidence",
    "EXECUTION_TRANSPORT_SUPERVISED",
    "EXECUTION_TRANSPORT_TEST",
    "PreparedBackend",
    "RenderedBackend",
    "SEED_POLICY_EXPLICIT",
    "SEED_POLICY_PINNED_DEFAULT",
    "TraceSummary",
    "assert_canonical_prepared_booksim",
    "bind_booksim_inputs",
    "compare_route_realization",
    "execution_qualification",
    "expected_route_table",
    "_run_qualified_booksim_with_runner_for_test",
    "assert_executable",
    "assert_canonical_booksim_projection",
    "parse_booksim_config_values",
    "verify_rendered_profile_gates",
    "exact_flit_bytes",
    "lower_booksim_projection",
    "lower_booksim_standalone",
    "materialize_backend",
    "prepare_booksim_standalone",
    "render_booksim_standalone",
    "render_topology_anynet",
    "run_certified_booksim",
    "run_qualified_booksim",
    "verify_anynet_roundtrip",
    "verify_materialized",
]
