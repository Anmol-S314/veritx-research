"""veritx_dse.backend.analytical — analytical aware/unaware lowering (B3.7d).

The two analytical engines are DIFFERENT backends with different
capabilities and protocols; they get distinct BackendTarget identities and
are never silently substituted after lowering:

    SERVING_ANALYTICAL_AWARE    congestion-aware engine (1-dim only)
    SERVING_ANALYTICAL_UNAWARE  congestion-unaware engine (N-dim, optimistic)

Capability truth from source review:

  * both engines model an abstract topology (logical dimensions) with a
    bandwidth/latency model, not a router graph, routes, VCs, buffers,
    credits or packet headers;
  * the congestion-aware engine supports only flat 1-dim topologies (the
    serving selection code falls back to the unaware engine for N-dim
    clusters);
  * ``network_dims`` is an execution/model policy: it supplies the
    endpoint count and a logical shape, but the lowerer does NOT prove
    that shape corresponds to the materialized TopologyArtifact graph.
    TOPOLOGY_GRAPH is therefore COARSENED (FIDELITY_DOWNGRADE): the
    backend represents endpoint count + supplied shape, not the full
    router/channel graph. Graph->shape equivalence for supported
    families is explicitly deferred (do not infer it here);
  * the network.yml bandwidth (GB/s) and latency (ns) values are
    hardcoded assumptions in the serving/config path, and the fabric
    artifacts contain channel width BITS and latency CYCLES — without an
    explicit clock period and bandwidth-unit derivation, no exact unit
    conversion exists. Executing with fabricated units would be
    scientifically false, so both dimensions are UNREPRESENTABLE with
    UNSUPPORTED_EXECUTION (a STOP condition in the B3.7 contract).

Consequence: these artifacts carry an explicit capability matrix and
refuse execution until units and a representative configuration are
established. That is a correct B3.7 outcome, not a failure.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .bundle import ResolvedFabricBundle
from .contracts import (
    BackendConfigArtifact, BackendConfigError, BackendTarget,
    CertificationEffect, ParameterOwner, RepresentationStatus,
    SemanticBinding, SemanticDimension,
)

ANALYTICAL_AWARE_PROFILE = "CERTIFIED_ANALYTICAL_AWARE_V1"
ANALYTICAL_UNAWARE_PROFILE = "CERTIFIED_ANALYTICAL_UNAWARE_V1"
ANALYTICAL_SEMANTICS_VERSION = "astra-analytical-aware-1dim/unaware-ndim"
ANALYTICAL_LOWERER_VERSION = "B37/1"

ANALYTICAL_OWNERSHIP: dict[str, ParameterOwner] = {
    "npus_count": ParameterOwner.FABRIC_DERIVED,
    "topology_shape": ParameterOwner.EXECUTION_POLICY,
    "network_engine": ParameterOwner.BACKEND_PROFILE,
}


class AnalyticalLoweringError(ValueError):
    """The fabric cannot be represented by this analytical engine."""


@dataclass(frozen=True)
class AnalyticalPrepared:
    """A lowered analytical artifact plus its execution blockers."""

    config: BackendConfigArtifact
    blockers: tuple[dict[str, Any], ...]

    def executable(self) -> bool:
        return not self.blockers


def _validate_dims(network_dims: Any, *, endpoint_count: int,
                   aware: bool) -> tuple[int, ...]:
    if not isinstance(network_dims, (list, tuple)) or not network_dims:
        raise AnalyticalLoweringError(
            "network_dims must be a non-empty list of positive ints")
    dims = []
    for value in network_dims:
        if type(value) is not int or value < 1:
            raise AnalyticalLoweringError(
                f"network_dims entries must be positive ints, got {value!r}")
        dims.append(value)
    product = 1
    for d in dims:
        product *= d
    if product != endpoint_count:
        raise AnalyticalLoweringError(
            f"network_dims {dims} multiply to {product}, but the "
            f"attachment has {endpoint_count} endpoints")
    if aware and len(dims) != 1:
        raise AnalyticalLoweringError(
            f"the congestion-aware analytical engine supports only 1-dim "
            f"topologies; network_dims {dims} must use "
            "SERVING_ANALYTICAL_UNAWARE (or a 1-dim cluster)")
    return tuple(dims)


def _bind(dimension, source, status, fields=(), reason="", effect=None,
          domain=""):
    if effect is None:
        effect = (CertificationEffect.NONE if status in (
            RepresentationStatus.EXACT,
            RepresentationStatus.DERIVED_EXACT,
            RepresentationStatus.BACKEND_IRRELEVANT)
            else CertificationEffect.FIDELITY_DOWNGRADE)
    return SemanticBinding(
        dimension=dimension, source_identity=source,
        representation_status=status, backend_fields=tuple(sorted(fields)),
        reason=reason, certification_effect=effect,
        supported_domain=domain)


def lower_analytical(
        bundle: ResolvedFabricBundle, *, network_dims: Any,
        target: BackendTarget) -> AnalyticalPrepared:
    """Capability matrix for one analytical engine target."""
    if target not in (BackendTarget.SERVING_ANALYTICAL_AWARE,
                      BackendTarget.SERVING_ANALYTICAL_UNAWARE):
        raise AnalyticalLoweringError(
            f"unsupported analytical target {target.value}")
    aware = target is BackendTarget.SERVING_ANALYTICAL_AWARE
    profile = (ANALYTICAL_AWARE_PROFILE if aware
               else ANALYTICAL_UNAWARE_PROFILE)
    try:
        bundle.revalidate()
    except ValueError as exc:
        raise AnalyticalLoweringError(
            f"bundle failed revalidation before lowering: {exc}") from exc

    topo = bundle.topology
    dims = _validate_dims(network_dims,
                          endpoint_count=bundle.attachment.endpoint_count,
                          aware=aware)

    t_hash = topo.topology_hash()
    a_hash = bundle.attachment.attachment_hash()
    rr_hash = bundle.resolved_route.resolved_route_hash()
    vc_hash = bundle.vc_assignment.vc_assignment_hash()
    pf_hash = bundle.packet_format.packet_format_hash()
    rb_hash = bundle.router_behavior.router_behavior_hash()
    ad_hash = bundle.address_decode.address_decode_hash()
    fabric_hash = bundle.fabric.fabric_hash()

    unit_reason = (
        "the analytical engine's network model takes bandwidth (GB/s) and "
        "latency (ns) values, but the fabric artifacts carry channel width "
        "BITS and latency CYCLES; no clock period or bandwidth-unit "
        "derivation exists, so a numeric conversion would be fabricated")
    simple_reason = (
        "the analytical engines model an abstract bandwidth/latency "
        "topology; this hardware semantic has no representation")

    b = (
        _bind(SemanticDimension.TOPOLOGY_GRAPH, t_hash,
              RepresentationStatus.COARSENED,
              (("npus_count", bundle.attachment.endpoint_count),
               ("topology_shape", list(dims))),
              reason="the analytical backend represents the endpoint count "
                     "and an externally supplied logical topology shape "
                     "(network_dims); it does not realize or prove the "
                     "materialized router/channel graph. Shape-to-graph "
                     "equivalence is not established, so this dimension "
                     "is a declared coarsening"),
        _bind(SemanticDimension.ENDPOINT_ATTACHMENT, a_hash,
              RepresentationStatus.UNREPRESENTABLE,
              reason="no endpoint-to-router attachment model " + simple_reason),
        _bind(SemanticDimension.CHANNEL_WIDTH, t_hash,
              RepresentationStatus.UNREPRESENTABLE,
              reason=unit_reason,
              effect=CertificationEffect.UNSUPPORTED_EXECUTION),
        _bind(SemanticDimension.CHANNEL_LATENCY, t_hash,
              RepresentationStatus.UNREPRESENTABLE,
              reason=unit_reason,
              effect=CertificationEffect.UNSUPPORTED_EXECUTION),
        _bind(SemanticDimension.ROUTE_WEIGHT, t_hash,
              RepresentationStatus.UNREPRESENTABLE,
              reason="no weighted-route model " + simple_reason),
        _bind(SemanticDimension.ROUTE_REALIZATION, rr_hash,
              RepresentationStatus.UNREPRESENTABLE,
              reason="the analytical model integrates a bandwidth/latency "
                     "estimate; it does not execute a route table"),
        _bind(SemanticDimension.VC_COUNT, vc_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.VC_CLASS_ASSIGNMENT, vc_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.VC_ROUTING_CLASS, vc_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.VC_TRANSITIONS, vc_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.ESCAPE_VCS, vc_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.FLIT_WIDTH, pf_hash,
              RepresentationStatus.UNREPRESENTABLE,
              reason="flit width feeds the same unresolved bandwidth unit "
                     "conversion"),
        _bind(SemanticDimension.PACKET_DELIMITATION, pf_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.PACKET_MAX_FLITS, pf_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.HEADER_LAYOUT, pf_hash,
              RepresentationStatus.BACKEND_IRRELEVANT, (),
              reason="the analytical model has no wire/packet header state"),
        _bind(SemanticDimension.HEADER_REPLICATION, pf_hash,
              RepresentationStatus.BACKEND_IRRELEVANT, (),
              reason="the analytical model has no wire/packet header state"),
        _bind(SemanticDimension.BUFFER_ORGANIZATION, rb_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.INPUT_BUFFER_DEPTH, rb_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.OUTPUT_STAGE_DEPTH, rb_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.FLOW_CONTROL, rb_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.CREDIT_RETURN_LATENCY, rb_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.VC_REUSE_POLICY, rb_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.VC_ALLOCATOR, rb_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.SWITCH_ALLOCATOR, rb_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.ALLOCATOR_ITERATIONS, rb_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.HOLD_SWITCH_FOR_PACKET, rb_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.INPUT_SPEEDUP, rb_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.OUTPUT_SPEEDUP, rb_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.INTERNAL_SPEEDUP, rb_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.ROUTE_COMPUTE_CYCLES, rb_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.VC_ALLOC_CYCLES, rb_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.SWITCH_ALLOC_CYCLES, rb_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.SWITCH_TRAVERSAL_CYCLES, rb_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.OUTPUT_DELAY_CYCLES, rb_hash,
              RepresentationStatus.UNREPRESENTABLE, reason=simple_reason),
        _bind(SemanticDimension.ADDRESS_DECODE, ad_hash,
              RepresentationStatus.BACKEND_IRRELEVANT, (),
              reason="the analytical model has no address-dependent state"),
        _bind(SemanticDimension.PLANE_COMPOSITION, fabric_hash,
              RepresentationStatus.UNREPRESENTABLE,
              reason="the analytical network model has no plane structure"),
    )

    params = tuple(sorted((
        ("network_engine",
         "congestion_aware" if aware else "congestion_unaware"),
        ("npus_count", bundle.attachment.endpoint_count),
        ("topology_shape", list(dims)),
    )))
    unknown = {k for k, _ in params} - set(ANALYTICAL_OWNERSHIP)
    if unknown:  # pragma: no cover - contract bug
        raise AnalyticalLoweringError(
            f"analytical parameters without an owner: {sorted(unknown)}")
    try:
        artifact = BackendConfigArtifact(
            backend_target=target, backend_profile=profile,
            backend_semantics_version=ANALYTICAL_SEMANTICS_VERSION,
            lowerer_version=ANALYTICAL_LOWERER_VERSION,
            resolved_fabric_hash=bundle.resolved_fabric
            .resolved_fabric_hash(),
            fabric_hash=fabric_hash,
            normalized_parameters=params,
            semantic_bindings=b,
        )
    except BackendConfigError as exc:  # pragma: no cover - contract bug
        raise AnalyticalLoweringError(
            f"lowering produced an invalid analytical artifact: {exc}"
        ) from exc

    blockers = tuple({
        "dimension": row.dimension.value,
        "reason": row.reason,
    } for row in artifact.semantic_bindings
        if row.certification_effect is
        CertificationEffect.UNSUPPORTED_EXECUTION)
    return AnalyticalPrepared(config=artifact, blockers=blockers)


def lower_analytical_aware(bundle: ResolvedFabricBundle, *,
                           network_dims: Any) -> AnalyticalPrepared:
    return lower_analytical(bundle, network_dims=network_dims,
                            target=BackendTarget.SERVING_ANALYTICAL_AWARE)


def lower_analytical_unaware(bundle: ResolvedFabricBundle, *,
                             network_dims: Any) -> AnalyticalPrepared:
    return lower_analytical(bundle, network_dims=network_dims,
                            target=BackendTarget.SERVING_ANALYTICAL_UNAWARE)


def assert_analytical_executable(prepared: AnalyticalPrepared) -> None:
    """Refuse execution while any dimension is UNSUPPORTED_EXECUTION."""
    if prepared.blockers:
        dims = ", ".join(row["dimension"] for row in prepared.blockers)
        raise AnalyticalLoweringError(
            f"UNSUPPORTED: analytical execution is blocked by unresolved "
            f"semantics: {dims}. Establish bandwidth/latency units and a "
            "representative configuration before claiming analytical "
            "execution")


__all__ = [
    "ANALYTICAL_AWARE_PROFILE",
    "ANALYTICAL_LOWERER_VERSION",
    "ANALYTICAL_OWNERSHIP",
    "ANALYTICAL_SEMANTICS_VERSION",
    "ANALYTICAL_UNAWARE_PROFILE",
    "AnalyticalLoweringError",
    "AnalyticalPrepared",
    "assert_analytical_executable",
    "lower_analytical",
    "lower_analytical_aware",
    "lower_analytical_unaware",
]
