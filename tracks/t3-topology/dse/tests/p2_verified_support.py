"""Genuine authenticated-backend fixtures for certified test ports (A4).

Law: ``evaluation_authority == "certified-backend"`` is descriptive. The
authority is Worker B's ``AuthenticatedBackendEvaluation``, built by
``authenticate_backend_evaluation`` (persisted evidence bytes ->
EvidenceRef -> EvidenceArtifact -> NetworkWindowBinding ->
VerifiedPerformanceResult -> canonical RequirementReport) and re-proved
by ``verify_authenticated_backend_evaluation``. Test ports that want
certified Pareto science build their proof through this module.

Nothing here is a BookSim execution, but nothing is a bare shape either:
the evidence document is PERSISTED (``write_evidence``) and the real
builder dereferences its bytes, so the proof is as strong as the
persisted-evidence boundary allows. ``build_verified`` remains the
synthetic A3-shape helper used by refusal attacks.

Certified metrics come ONLY from the FROZEN certified registry over
``claims.verified_result``. Tests that need analytic stand-in metrics
(``latency``/``area``) construct their OWN frozen test registry through
``MetricRegistryBuilder`` — never production globals; the producers read
a ``wave_d_chain.test_metrics`` overlay carried inside the verified
result, never the evaluator's ``objective_values``.
"""
from __future__ import annotations

import math
import tempfile
from collections.abc import Mapping
from fractions import Fraction
from pathlib import Path
from typing import Any

from veritx_dse.application.authenticated_evaluation import (
    authenticate_backend_evaluation,
)
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.requirements import (
    report_identity,
    verify_performance_result,
)
from veritx_dse.backend.evidence import stats_sha256_of, write_evidence
from veritx_dse.core.time import QTime
from veritx_dse.optimization.evaluators import (
    AUTHORITY_CERTIFIED_BACKEND,
    CandidateEvaluation,
)
from veritx_dse.optimization.metric_registry import (
    CERTIFIED_METRIC_REGISTRY,
    CertifiedMetricRegistry,
    MetricRegistryBuilder,
)
from veritx_dse.performance.model import (
    ClockDef,
    PerformanceModel,
    ResourceDef,
)
from veritx_dse.performance.network import (
    WINDOW_KIND_BARRIER,
    NetworkWindowBinding,
)
from veritx_dse.performance.result import (
    PerformanceEventGraph,
    build_performance_result,
)
from veritx_dse.performance.scheduler import schedule_workload
from veritx_dse.performance.workload import (
    EVENT_NETWORK_TRAFFIC_WINDOW,
    TemporalEvent,
    TemporalWorkload,
)
from veritx_dse.workload.intent_lowering import lower_compile_workload

CLOCK_HZ = 10 ** 9
_CONFIG_HASH = "0" * 64
_INPUT_HASH = "1" * 64
_PRODUCER = "b" * 64
_TRAFFIC_ID = "test-traffic"

#: Analytic stand-in metrics carried by certified test doubles.
OVERLAY_METRICS = ("latency", "area")


def _canonical_metrics(metrics: Mapping | None) -> dict[str, float] | None:
    """Only finite real values can ride the canonical chain overlay."""
    out: dict[str, float] = {}
    for key, value in (metrics or {}).items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        number = float(value)
        if math.isfinite(number):
            out[str(key)] = number
    return out or None


def _stats(cycles: int) -> dict[str, Any]:
    return {"completion_time": int(cycles), "delivered": 1, "pkt_count": 1}


def _assemble(request: Any, *, cycles: int, metrics: Mapping | None,
              resolved_fabric_hash: str, evidence_sha256: str,
              stats: dict[str, Any]):
    """(lowered graph, VerifiedPerformanceResult) for a v3 request."""
    graph = lower_compile_workload(request).graph
    clock = Fraction(CLOCK_HZ)
    model = PerformanceModel(
        clocks=(ClockDef("network", clock),),
        resources=(ResourceDef("fabric.network_window", "EXCLUSIVE",
                               capacity=1),),
        network_clock="network")
    event = TemporalEvent("network_traffic_window",
                          EVENT_NETWORK_TRAFFIC_WINDOW, QTime.zero())
    temporal = TemporalWorkload(performance_model=model, events=(event,))
    chain: dict[str, Any] = {
        "design_hash": request.design_hash(),
        "workload_graph_id": graph.workload_id(),
        "physical_traffic_id": _TRAFFIC_ID,
        "resolved_fabric_hash": resolved_fabric_hash,
    }
    if metrics is not None:
        chain["test_metrics"] = dict(metrics)
    binding = NetworkWindowBinding(
        workload_parent_id=graph.workload_id(), schema_version=2,
        physical_traffic_id=_TRAFFIC_ID,
        backend_config_hash=_CONFIG_HASH, backend_input_hash=_INPUT_HASH,
        evidence_sha256=evidence_sha256,
        stats_sha256=stats_sha256_of(stats),
        network_clock_hz=clock, window_kind=WINDOW_KIND_BARRIER,
        duration=QTime.from_cycles(int(cycles), clock))
    egraph = PerformanceEventGraph(
        workload=temporal, network_binding=binding, wave_d_chain=chain)
    schedule = schedule_workload(
        temporal, network_durations=egraph.network_durations())
    perf = build_performance_result(graph=egraph, schedule=schedule)
    return graph, verify_performance_result(perf, workload=temporal)


def _compile(request: Any):
    compilation = FabricCompiler().compile(request)
    if compilation.status != "COMPILED" or compilation.bundle is None:
        raise AssertionError(
            f"test fixture request did not compile: {compilation.status}")
    return compilation


def build_verified(request: Any, *, cycles: int = 100,
                   metrics: Mapping | None = None):
    """SYNTHETIC A3-shape verified result (no persisted evidence).

    Deliberately has no authenticated proof: used by refusal attacks to
    prove a synthetic result cannot become authoritative.
    """
    compilation = _compile(request)
    # Canonical ResolvedFabric stores its hash as an attribute (not a
    # method like the RT lineage exposed it).
    resolved = compilation.bundle.resolved_fabric.resolved_fabric_hash
    stats = _stats(cycles)
    return _assemble(request, cycles=cycles, metrics=metrics,
                     resolved_fabric_hash=resolved,
                     evidence_sha256="2" * 64, stats=stats)


def build_authenticated(request: Any, *, cycles: int = 100,
                        metrics: Mapping | None = None,
                        evidence_root: Any = None):
    """(graph, verified_result, proof) with a genuine evidence chain."""
    from veritx_dse.backend.evidence import ScientificBackendEvidence
    compilation = _compile(request)
    # Canonical ResolvedFabric stores its hash as an attribute (not a
    # method like the RT lineage exposed it).
    resolved = compilation.bundle.resolved_fabric.resolved_fabric_hash
    stats = _stats(cycles)
    # Canonical scientific evidence (§26 Option 2): the persisted
    # document speaks the canonical schema. Digests bound by the
    # proof (trace/input, config, stats, producer) match the binding
    # exactly; the remaining identifiers are synthetic but
    # self-consistent hex. Stats ride verbatim so the stats digest
    # agrees with the binding.
    evidence_doc = ScientificBackendEvidence(
        prepared_id="2" * 64,
        profile_id="CERTIFIED_BOOKSIM_MESH_DOR_XY_V1",
        projection_semantics_version="test",
        config_sha256=_CONFIG_HASH,
        trace_sha256=_INPUT_HASH,
        topology_sha256=None,
        resolved_fabric_hash=resolved,
        physical_traffic_id="3" * 64,
        message_artifact_id="4" * 64,
        binary_sha256=_PRODUCER,
        binary_size=1,
        producer_source_revision=None,
        producer_dirty=False,
        seed=0,
        parser_version="veritx/booksim-stats-parser/v1",
        execution_fidelity="QUALIFIED",
        route_observation="DOMAIN_QUALIFIED_ROUTE_NOT_OBSERVED",
        stats=dict(stats),
        exit_status=0,
        transport="SUPERVISED_PROCESS").to_dict()
    root = Path(tempfile.mkdtemp(
        prefix="p2-proof-",
        dir=str(evidence_root) if evidence_root is not None else None))
    ref = write_evidence(root, evidence_doc)
    graph, verified = _assemble(
        request, cycles=cycles, metrics=metrics,
        resolved_fabric_hash=resolved, evidence_sha256=ref.sha256,
        stats=stats)
    proof = authenticate_backend_evaluation(
        compilation=compilation, workload=graph,
        verified_result=verified, evidence_path=ref.path,
        producer_identity=_PRODUCER)
    return graph, verified, proof


def _overlay_extractor(metric: str):
    def extract(verified: Any) -> float | None:
        chain = verified.get("wave_d_chain") \
            if isinstance(verified, Mapping) else None
        metrics = chain.get("test_metrics") \
            if isinstance(chain, Mapping) else None
        if not isinstance(metrics, Mapping):
            return None
        return metrics.get(metric)
    return extract


def build_test_metric_registry(*, version: str = "test-overlay-v1",
                               latency: Any = None,
                               ) -> CertifiedMetricRegistry:
    """A frozen TEST-OWNED registry (never a production global).

    Extends the product built-ins with the analytic stand-in producers
    used by certified test doubles. ``latency`` overrides the latency
    producer (used by the non-finite-value attack).
    """
    builder = MetricRegistryBuilder(version, base=CERTIFIED_METRIC_REGISTRY)
    builder.register("latency",
                     latency if latency is not None
                     else _overlay_extractor("latency"),
                     producer_id="test-overlay-latency")
    builder.register("area", _overlay_extractor("area"),
                     producer_id="test-overlay-area")
    return builder.freeze()


#: Module-level frozen test registry for the standard certified doubles.
TEST_METRIC_REGISTRY = build_test_metric_registry()


def run_certified_mechanics_for_tests(base: Any, definition: Any, port: Any,
                                      metric_registry: Any) -> Any:
    """Research-classified exercise of the certified pipeline mechanics.

    C1 removed every overridable certified-evaluator seam: the PUBLIC
    ``optimize_certified`` always builds ``RealCandidateEvaluator`` via a
    module-private factory. Tests needing synthetic evaluators exercise
    the optimizer's certified MECHANICS (verifier authority, frozen
    registry extraction, eligibility) through this test/research path,
    which is classified ANALYTIC_RESEARCH and therefore can NEVER
    manufacture a CERTIFIED_PRODUCT result.
    """
    from veritx_dse.optimization.result import Optimizer
    # C4: certified *mechanics* without certification authority — the core
    # accepts certified claims but can never classify them CERTIFIED_PRODUCT.
    return Optimizer()._optimize_core(
        base, definition, port,
        accept_certified_claims=True,
        metric_registry=metric_registry)


def certified_evaluation(candidate: Any, *, cycles: int = 100,
                         objective_values: dict[str, Any] | None = None,
                         locked: dict[str, Any] | None = None,
                         status: str = "EVALUATED",
                         error: str | None = None,
                         compilation_status: str = "COMPILED",
                         evidence_root: Any = None,
                         ) -> CandidateEvaluation:
    """A certified CandidateEvaluation carrying Worker B's proof.

    EVALUATED outcomes carry a genuine ``AuthenticatedBackendEvaluation``;
    the analytic stand-in metric values are stashed in the verified
    result's ``wave_d_chain.test_metrics`` so the registered overlay
    producers can extract them. Non-EVALUATED statuses carry no
    measurements and therefore no proof.
    """
    request = candidate.request
    design_hash = request.design_hash()
    if status != "EVALUATED":
        return CandidateEvaluation(
            candidate_id=candidate.candidate_id, design_hash=design_hash,
            status=status, objective_values={},
            locked_consequences=dict(locked or {}),
            compilation_status=compilation_status, error=error,
            performance_result_id=None,
            evaluation_authority=AUTHORITY_CERTIFIED_BACKEND)
    graph, verified, proof = build_authenticated(
        request, cycles=cycles, metrics=_canonical_metrics(objective_values),
        evidence_root=evidence_root)
    report = proof.requirement_report
    return CandidateEvaluation(
        candidate_id=candidate.candidate_id, design_hash=design_hash,
        status="EVALUATED",
        objective_values=dict(objective_values or {}),
        locked_consequences=dict(locked or {}),
        compilation_status="COMPILED", error=error,
        performance_result_id=verified["resource_id"],
        requirement_report=report,
        requirement_report_id=report_identity(report),
        evaluation_authority=AUTHORITY_CERTIFIED_BACKEND,
        workload=graph, verified_performance_result=verified,
        authenticated_proof=proof)


__all__ = [
    "CLOCK_HZ", "OVERLAY_METRICS", "TEST_METRIC_REGISTRY",
    "build_authenticated", "build_test_metric_registry", "build_verified",
    "certified_evaluation", "run_certified_mechanics_for_tests",
]
