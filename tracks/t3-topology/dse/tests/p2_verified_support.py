"""Genuine verified-performance fixtures for certified test ports (A3).

Law: ``evaluation_authority == "certified-backend"`` is descriptive;
the proof is a ``VerifiedPerformanceResult`` that passes B's boundary
plus a RequirementReport the Optimizer can independently re-derive.
Test ports that want certified Pareto science build their evidence
through this module — a real lowered WorkloadGraph, a real
TemporalWorkload and network binding, a result that passes
``verify_performance_result``, and the report
``RequirementEvaluator.evaluate`` produces from exactly those objects.

Nothing here is a backend: the network window is a declared synthetic
duration, which is legitimate for testing the OPTIMIZER's proof
machinery. Production measurements still come from RealCandidateEvaluator.
"""
from __future__ import annotations

from fractions import Fraction
from typing import Any

from veritx_dse.application.requirements import (
    RequirementEvaluator,
    report_identity,
    verify_performance_result,
)
from veritx_dse.core.time import QTime
from veritx_dse.optimization.evaluators import (
    AUTHORITY_CERTIFIED_BACKEND,
    CandidateEvaluation,
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


def build_verified(request: Any, *, cycles: int = 100):
    """(lowered WorkloadGraph, VerifiedPerformanceResult) for a v3 request.

    The window duration is ``cycles / CLOCK_HZ`` exactly, so the
    authenticated completion cycles recover to ``cycles`` and the
    report's latency verdict is under test control through ``cycles``.
    """
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
    binding = NetworkWindowBinding(
        workload_parent_id=graph.workload_id(), schema_version=2,
        physical_traffic_id="test-traffic",
        backend_config_hash="0" * 64, backend_input_hash="1" * 64,
        evidence_sha256="2" * 64, stats_sha256="3" * 64,
        network_clock_hz=clock, window_kind=WINDOW_KIND_BARRIER,
        duration=QTime.from_cycles(int(cycles), clock))
    egraph = PerformanceEventGraph(
        workload=temporal, network_binding=binding,
        wave_d_chain={"design_hash": request.design_hash(),
                      "workload_graph_id": graph.workload_id()})
    schedule = schedule_workload(
        temporal, network_durations=egraph.network_durations())
    perf = build_performance_result(graph=egraph, schedule=schedule)
    return graph, verify_performance_result(perf, workload=temporal)


def certified_evaluation(candidate: Any, *, cycles: int = 100,
                         objective_values: dict[str, Any] | None = None,
                         locked: dict[str, Any] | None = None,
                         status: str = "EVALUATED",
                         error: str | None = None,
                         compilation_status: str = "COMPILED",
                         ) -> CandidateEvaluation:
    """A certified CandidateEvaluation carrying REAL proof for EVALUATED.

    Non-EVALUATED statuses carry no measurements and therefore no proof
    (the Optimizer never demands proof for a non-success outcome).
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
    graph, verified = build_verified(request, cycles=cycles)
    report = RequirementEvaluator.evaluate(request, graph, verified)
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
        workload=graph, verified_performance_result=verified)


__all__ = ["CLOCK_HZ", "build_verified", "certified_evaluation"]
