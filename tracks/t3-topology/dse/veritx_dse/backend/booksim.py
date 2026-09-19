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

from .bundle import ResolvedFabricBundle
from .contracts import (
    BackendConfigArtifact, BackendConfigError, BackendInputError,
    BackendInputManifest, BackendTarget, CertificationEffect,
    ParameterOwner, RenderedInput, RepresentationStatus, SemanticBinding,
    SemanticDimension, sha256_bytes,
)

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

_SEED_DEFAULT = 1
_LATENCY_THRES = 1000000000000000.0
_SAMPLE_PERIOD_MIN = 200
_SAMPLE_PERIOD_MARGIN = 1000


class BookSimLoweringError(ValueError):
    """The semantic fabric cannot be lowered to BookSim — fail closed."""


class BookSimRouteError(ValueError):
    """Executed route realization is missing/divergent — refuse the run."""


class BackendMaterializationError(ValueError):
    """Rendered inputs cannot be materialized/verified — fail closed."""


# ── closed parameter ownership table (B3.7b §8) ────────────────────────
# Every rendered BookSim config key must appear here with exactly one
# owner; every key emitted by the renderer must be listed. An emitted
# key without an owner is an error.

BOOKSIM_STANDALONE_OWNERSHIP: dict[str, ParameterOwner] = {
    # topology projection (renderer-translated from the artifact)
    "topology": ParameterOwner.BACKEND_PROFILE,
    "network_file": ParameterOwner.BACKEND_PROFILE,
    "routing_function": ParameterOwner.FABRIC_DERIVED,
    # router/VC/flow behavior
    "num_vcs": ParameterOwner.FABRIC_DERIVED,
    "vc_buf_size": ParameterOwner.FABRIC_DERIVED,
    "wait_for_tail_credit": ParameterOwner.FABRIC_DERIVED,
    "hold_switch_for_packet": ParameterOwner.FABRIC_DERIVED,
    "vc_allocator": ParameterOwner.FABRIC_DERIVED,
    "sw_allocator": ParameterOwner.FABRIC_DERIVED,
    "alloc_iters": ParameterOwner.FABRIC_DERIVED,
    "credit_delay": ParameterOwner.FABRIC_DERIVED,
    "routing_delay": ParameterOwner.FABRIC_DERIVED,
    "vc_alloc_delay": ParameterOwner.FABRIC_DERIVED,
    "sw_alloc_delay": ParameterOwner.FABRIC_DERIVED,
    "st_prepare_delay": ParameterOwner.FABRIC_DERIVED,
    "st_final_delay": ParameterOwner.FABRIC_DERIVED,
    "input_speedup": ParameterOwner.FABRIC_DERIVED,
    "output_speedup": ParameterOwner.FABRIC_DERIVED,
    "internal_speedup": ParameterOwner.FABRIC_DERIVED,
    "output_buffer_size": ParameterOwner.FABRIC_DERIVED,
    # backend profile pins (no fabric artifact models these yet)
    "arb_type": ParameterOwner.BACKEND_PROFILE,
    "classes": ParameterOwner.BACKEND_PROFILE,
    "subnets": ParameterOwner.BACKEND_PROFILE,
    "router": ParameterOwner.BACKEND_PROFILE,
    "buffer_policy": ParameterOwner.BACKEND_PROFILE,
    "max_samples": ParameterOwner.BACKEND_PROFILE,
    "sim_type": ParameterOwner.BACKEND_PROFILE,
    "latency_thres": ParameterOwner.BACKEND_PROFILE,
    # workload / execution inputs
    "traffic": ParameterOwner.WORKLOAD_DERIVED,
    "sample_period": ParameterOwner.WORKLOAD_DERIVED,
    "seed": ParameterOwner.EXECUTION_POLICY,
    "routing_dump_file": ParameterOwner.EXECUTION_POLICY,
}

# Rendered in a fixed order so the config bytes are deterministic.
_CFG_KEY_ORDER: tuple[str, ...] = (
    "topology", "network_file", "routing_function",
    "num_vcs", "vc_buf_size", "wait_for_tail_credit",
    "hold_switch_for_packet", "vc_allocator", "sw_allocator", "alloc_iters",
    "arb_type", "credit_delay", "routing_delay", "vc_alloc_delay",
    "sw_alloc_delay", "st_prepare_delay", "st_final_delay",
    "input_speedup", "output_speedup", "internal_speedup",
    "output_buffer_size", "classes", "subnets", "router", "buffer_policy",
    "traffic", "sample_period", "max_samples", "sim_type", "latency_thres",
    "seed", "routing_dump_file",
)

# Artifact parameters that are projection semantics, not BookSim cfg keys.
_PROJECTION_ONLY_KEYS = frozenset({"routing_class",
                                   "channel_latency_cycles"})


def _assert_ownership() -> None:
    if set(_CFG_KEY_ORDER) != set(BOOKSIM_STANDALONE_OWNERSHIP):
        missing = set(_CFG_KEY_ORDER) - set(BOOKSIM_STANDALONE_OWNERSHIP)
        extra = set(BOOKSIM_STANDALONE_OWNERSHIP) - set(_CFG_KEY_ORDER)
        raise BookSimLoweringError(
            f"ownership table does not match the rendered key set "
            f"(missing {sorted(missing)}, extra {sorted(extra)})")


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

    params = (
        ("channel_latency_cycles", latency),
        ("classes", 1),
        ("arb_type", "round_robin"),
        ("alloc_iters", rb.allocator_iterations),
        ("buffer_policy", "private"),
        ("credit_delay", rb.credit_return_latency_cycles),
        ("hold_switch_for_packet", 1 if rb.hold_switch_for_packet else 0),
        ("input_speedup", rb.input_speedup),
        ("internal_speedup", float(rb.internal_speedup)),
        ("latency_thres", _LATENCY_THRES),
        ("max_samples", 1),
        ("num_vcs", vc.vc_count),
        ("output_buffer_size",
         rb.output_stage_depth_flits_per_vc * vc.vc_count),
        ("output_speedup", rb.output_speedup),
        ("router", "iq"),
        ("routing_class", selected),
        ("routing_delay", rb.route_compute_cycles),
        ("routing_function", "min"),
        ("sim_type", "latency"),
        ("st_final_delay", rb.switch_traversal_cycles),
        ("st_prepare_delay", 0),
        ("subnets", 1),
        ("sw_alloc_delay", rb.switch_alloc_cycles),
        ("sw_allocator", rb.switch_allocator.value),
        ("topology", "anynet"),
        ("vc_alloc_delay", rb.vc_alloc_cycles),
        ("vc_allocator", rb.vc_allocator.value),
        ("vc_buf_size", rb.input_buffer_depth_flits_per_vc),
        ("wait_for_tail_credit",
         1 if rb.vc_reuse_policy is VCReusePolicy.WAIT_FOR_TAIL_CREDIT
         else 0),
    )
    if serving:
        # Embedded mode: every flit comes from the host via sim_send;
        # background demand traffic must stay off (legacy serving cfg does
        # the same with injection_rate = 0.0).
        params = params + (
            ("injection_rate", 0.0),
            ("traffic", "uniform"),
        )
    params = tuple(sorted(params))

    def bind(dimension, source, status, fields, reason="", effect=None):
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
            certification_effect=effect)

    t_hash, a_hash = topo.topology_hash(), att.attachment_hash()
    rra_hash, vc_hash = rra.resolved_route_hash(), vc.vc_assignment_hash()
    pf_hash, rb_hash = pf.packet_format_hash(), rb.router_behavior_hash()
    ad_hash = ad.address_decode_hash()

    bindings = (
        bind(SemanticDimension.TOPOLOGY_GRAPH, t_hash,
             RepresentationStatus.DERIVED_EXACT,
             (("topology_kind", "anynet"),
              ("parse_back", "required before spawn") if not serving
              else ("parse_back", "required at preparation"))),
        bind(SemanticDimension.ENDPOINT_ATTACHMENT, a_hash,
             RepresentationStatus.EXACT,
             (("node_lines", att.endpoint_count),
              ("ports", "assigned by BookSim; port ids not represented"))),
        bind(SemanticDimension.CHANNEL_WIDTH, t_hash,
             RepresentationStatus.BACKEND_IRRELEVANT, (),
             reason="BookSim is a flit-count timing model: flit channels "
                    "transfer one flit per cycle and no width-dependent "
                    "serialization/occupancy exists"),
        bind(SemanticDimension.CHANNEL_LATENCY, t_hash,
             RepresentationStatus.EXACT,
             (("anynet_link_weight", latency),)),
        bind(SemanticDimension.ROUTE_WEIGHT, t_hash,
             RepresentationStatus.EXACT, (("route_weight", 1),)),
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
             if serving else None),
        bind(SemanticDimension.VC_COUNT, vc_hash,
             RepresentationStatus.EXACT, (("num_vcs", vc.vc_count),)),
        bind(SemanticDimension.VC_CLASS_ASSIGNMENT, vc_hash,
             RepresentationStatus.EXACT if vc_class_exact
             else RepresentationStatus.COARSENED,
             (("classes", 1),),
             reason=vc_class_reason),
        bind(SemanticDimension.VC_ROUTING_CLASS, vc_hash,
             RepresentationStatus.EXACT,
             (("routing_function", "min"),)),
        bind(SemanticDimension.VC_TRANSITIONS, vc_hash,
             RepresentationStatus.EXACT if transitions_exact
             else RepresentationStatus.UNREPRESENTABLE,
             tuple(),
             reason="" if transitions_exact else
             "BookSim never migrates a packet between VCs; the artifact's "
             "cross-VC transitions have no backend realization",
             effect=None if transitions_exact
             else CertificationEffect.BLOCKS_EXACT_FABRIC),
        bind(SemanticDimension.ESCAPE_VCS, vc_hash,
             RepresentationStatus.EXACT if not vc.escape_vcs
             else RepresentationStatus.UNREPRESENTABLE,
             tuple(),
             reason="" if not vc.escape_vcs else
             "the certified profile has no escape-VC mechanism; a fabric "
             "that designates escape VCs for deadlock freedom is not "
             "representable",
             effect=None if not vc.escape_vcs
             else CertificationEffect.BLOCKS_EXACT_FABRIC),
        bind(SemanticDimension.FLIT_WIDTH, pf_hash,
             RepresentationStatus.DERIVED_EXACT if serving
             else RepresentationStatus.BACKEND_IRRELEVANT,
             (("flit_bytes", serving_flit_bytes),) if serving else (),
             reason="BookSim counts flits; no width/serialization model"
             if not serving else ""),
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
             if serving else ""),
        bind(SemanticDimension.HEADER_LAYOUT, pf_hash,
             RepresentationStatus.BACKEND_IRRELEVANT, (),
             reason="no header decode exists in the timing model"),
        bind(SemanticDimension.HEADER_REPLICATION, pf_hash,
             RepresentationStatus.BACKEND_IRRELEVANT, (),
             reason="header bytes are not modeled per flit"),
        bind(SemanticDimension.BUFFER_ORGANIZATION, rb_hash,
             RepresentationStatus.EXACT, (("buffer_policy", "private"),)),
        bind(SemanticDimension.INPUT_BUFFER_DEPTH, rb_hash,
             RepresentationStatus.EXACT,
             (("vc_buf_size", rb.input_buffer_depth_flits_per_vc),)),
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
               else 0),)),
        bind(SemanticDimension.CREDIT_RETURN_LATENCY, rb_hash,
             RepresentationStatus.EXACT,
             (("credit_delay", rb.credit_return_latency_cycles),)),
        bind(SemanticDimension.VC_REUSE_POLICY, rb_hash,
             RepresentationStatus.EXACT,
             (("wait_for_tail_credit",
               1 if rb.vc_reuse_policy is VCReusePolicy.WAIT_FOR_TAIL_CREDIT
               else 0),)),
        bind(SemanticDimension.VC_ALLOCATOR, rb_hash,
             RepresentationStatus.EXACT,
             (("vc_allocator", rb.vc_allocator.value),)),
        bind(SemanticDimension.SWITCH_ALLOCATOR, rb_hash,
             RepresentationStatus.EXACT,
             (("sw_allocator", rb.switch_allocator.value),)),
        bind(SemanticDimension.ALLOCATOR_ITERATIONS, rb_hash,
             RepresentationStatus.EXACT,
             (("alloc_iters", rb.allocator_iterations),)),
        bind(SemanticDimension.HOLD_SWITCH_FOR_PACKET, rb_hash,
             RepresentationStatus.EXACT,
             (("hold_switch_for_packet",
               1 if rb.hold_switch_for_packet else 0),)),
        bind(SemanticDimension.INPUT_SPEEDUP, rb_hash,
             RepresentationStatus.EXACT,
             (("input_speedup", rb.input_speedup),)),
        bind(SemanticDimension.OUTPUT_SPEEDUP, rb_hash,
             RepresentationStatus.EXACT,
             (("output_speedup", rb.output_speedup),)),
        bind(SemanticDimension.INTERNAL_SPEEDUP, rb_hash,
             RepresentationStatus.DERIVED_EXACT,
             (("internal_speedup", float(rb.internal_speedup)),)),
        bind(SemanticDimension.ROUTE_COMPUTE_CYCLES, rb_hash,
             RepresentationStatus.EXACT,
             (("routing_delay", rb.route_compute_cycles),)),
        bind(SemanticDimension.VC_ALLOC_CYCLES, rb_hash,
             RepresentationStatus.EXACT,
             (("vc_alloc_delay", rb.vc_alloc_cycles),)),
        bind(SemanticDimension.SWITCH_ALLOC_CYCLES, rb_hash,
             RepresentationStatus.EXACT,
             (("sw_alloc_delay", rb.switch_alloc_cycles),)),
        bind(SemanticDimension.SWITCH_TRAVERSAL_CYCLES, rb_hash,
             RepresentationStatus.DERIVED_EXACT,
             (("st_prepare_delay", 0),
              ("st_final_delay", rb.switch_traversal_cycles)),
             reason=""),
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
             RepresentationStatus.EXACT, (("subnets", 1),)),
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
        if key in BOOKSIM_STANDALONE_OWNERSHIP:
            continue
        # The serving target adds one profile pin (injection_rate); its
        # complete table is enforced by backend.serving.render_serving_config.
        if serving and key == "injection_rate":
            continue
        raise BookSimLoweringError(
            f"emitted parameter {key!r} has no ownership entry")
    return artifact


# ── deterministic rendering ─────────────────────────────────────────────

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
                 for key in _CFG_KEY_ORDER]
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
        seed_policy="explicit" if seed is not None else "pinned_default",
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
        }


def run_certified_booksim(
        prepared: PreparedBackend, *,
        run_dir: Path,
        repo_root: Path,
        timeout: int = 60,
        runner: Any | None = None,
        binary: Path | None = None,
) -> CertifiedBookSimEvidence:
    """Execute one prepared certified standalone BookSim run.

    Order: revalidate bundle → identity checks → materialize →
    parse-back topology → verify hashes IMMEDIATELY BEFORE spawn → run →
    executed-route proof → parse stats. Any tamper/stale input refuses.
    """
    import time

    from veritx_dse.core.errors import BookSimError, TimeoutError
    from veritx_dse.simulation.booksim import find_booksim_bin, parse_output

    config, manifest, rendered = (prepared.config, prepared.manifest,
                                  prepared.rendered)
    bundle = prepared.bundle

    try:
        bundle.revalidate()
    except ValueError as exc:
        raise BookSimLoweringError(
            f"bundle failed revalidation before execution: {exc}") from exc
    if config.backend_config_hash() != manifest.backend_config_hash:
        raise BackendMaterializationError(
            "manifest does not bind this backend config artifact")
    if config.fabric_hash != bundle.fabric.fabric_hash() or \
            config.resolved_fabric_hash != \
            bundle.resolved_fabric.resolved_fabric_hash():
        raise BackendMaterializationError(
            "backend config does not bind the supplied bundle")

    backend_dir = Path(run_dir) / "backend"
    materialize_backend(rendered, manifest, backend_dir)
    verify_anynet_roundtrip(bundle, backend_dir / TOPOLOGY_FILE)
    # Re-verify the exact bytes the child is about to execute.
    verify_materialized(manifest, backend_dir)

    bin_path = Path(binary) if binary is not None \
        else find_booksim_bin(repo_root)
    cmd = (str(bin_path), CONFIG_FILE)
    if runner is None:
        from veritx_dse.core.process import supervised_run

        def runner(c, cwd, t):
            return supervised_run(c, cwd=cwd, timeout=t,
                                  on_timeout="complete")

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

    binary_hash = None
    try:
        binary_hash = sha256_bytes(bin_path.read_bytes())
    except OSError:
        binary_hash = None

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
        booksim_binary_sha256=binary_hash,
    )


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
    "PreparedBackend",
    "RenderedBackend",
    "TraceSummary",
    "bind_booksim_inputs",
    "compare_route_realization",
    "exact_flit_bytes",
    "lower_booksim_projection",
    "lower_booksim_standalone",
    "materialize_backend",
    "prepare_booksim_standalone",
    "render_booksim_standalone",
    "render_topology_anynet",
    "run_certified_booksim",
    "verify_anynet_roundtrip",
    "verify_materialized",
]
