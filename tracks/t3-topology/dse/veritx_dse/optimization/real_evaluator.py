"""veritx_dse.optimization.real_evaluator — real CandidateEvaluationPort.

The production route (fake stays unit-only):

    candidate CompileRequest (v3)
      -> FabricCompiler.compile()              (LOCKED consequences)
      -> lower_compile_workload()              (P1C WorkloadGraph)
      -> assert_traffic_classes_bound()        (pre-spawn gate)
      -> FabricEvaluator.evaluate()            (P1B authenticated perf)
      -> RequirementEvaluator.evaluate()       (P1C RequirementReport)
      -> CandidateEvaluation (evidenced objectives only)

Feasibility law (no optimizer changes needed — enforced by status):
EVALUATED here means compiled AND backend-evaluated AND all binding
requirements SATISFIED. Anything else maps to COMPILE_FAILED/
UNSUPPORTED/INVALID with the true cause in `error` and whatever
provenance exists still bound (locked consequences,
performance_result_id) — visible, auditable, never Pareto-eligible.
Binding-failed evaluations are NOT relabeled successes; the error names
the failing entries.

Objectives are evidenced measurements only: network completion cycles
(+ wall-time when a valid clock was declared) plus backend-reported
numerics. There is deliberately no area/latency-analytic key: unmeasured
is absent, never faked. Widening the metric set means binding a new
qualified producer, not adding a key here.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.fabric_evaluator import (
    STANDALONE_BACKEND,
    EvaluationOptions,
    FabricEvaluator,
)
from veritx_dse.application.requirements import (
    RequirementEvaluator,
    report_identity,
    report_passes,
)
from veritx_dse.core.errors import (
    InvalidInput,
    MappingInvalid,
    UnsupportedSchedule,
    UnsupportedSemantics,
)
from veritx_dse.model.compile_model import CompileRequestV3
from veritx_dse.optimization.evaluators import (
    CandidateEvaluation,
    EvaluationError,
    locked_consequences_of,
)
from veritx_dse.workload.intent_lowering import (
    assert_traffic_classes_bound,
    lower_compile_workload,
)


def _refuse(candidate_id: str, design_hash: str, status: str,
            compilation_status: str, error: str,
            locked: dict[str, Any] | None = None,
            performance_result_id: str | None = None,
            requirement_report: dict[str, Any] | None = None,
            ) -> CandidateEvaluation:
    return CandidateEvaluation(
        candidate_id=candidate_id, design_hash=design_hash,
        status=status, objective_values={},
        locked_consequences=dict(locked or {}),
        compilation_status=compilation_status, error=error,
        performance_result_id=performance_result_id,
        requirement_report=requirement_report,
        requirement_report_id=(report_identity(requirement_report)
                               if requirement_report is not None else None))


def _real_objectives(outcome: Any) -> dict[str, float]:
    """Evidenced measurements only. No analytic stand-ins."""
    window = outcome.network_traffic_window or {}
    objectives: dict[str, float] = {}
    if window.get("window_cycles") is not None:
        objectives["completion_cycles"] = \
            float(window["window_cycles"])
    if window.get("wall_time_ns") is not None:
        objectives["completion_ns"] = float(window["wall_time_ns"])
    for key, value in (outcome.metrics or {}).items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and math.isfinite(value):
            objectives.setdefault(str(key), float(value))
    return objectives


class RealCandidateEvaluator:
    """Production port: every candidate through the real pipeline.

    run_root/<candidate_id>/ isolates each candidate's backend evidence;
    directory names derive from candidate identity, so execution order
    never changes scientific identity.
    """

    def __init__(self, *, binary: str | Path,
                 network_clock_hz: int | None = None,
                 timeout_s: int = 300,
                 run_root: str | Path,
                 repo_root: str | Path | None = None,
                 require_quiescence: bool = True):
        if not binary:
            raise EvaluationError("real adapter needs a backend binary")
        self.binary = str(binary)
        self.network_clock_hz = network_clock_hz
        self.timeout_s = timeout_s
        self.run_root = Path(run_root)
        self.repo_root = repo_root
        self.require_quiescence = require_quiescence
        self.calls = 0

    def evaluate(self, candidate: Any) -> CandidateEvaluation:
        request = candidate.request
        if not isinstance(request, CompileRequestV3):
            raise EvaluationError(
                f"real adapter takes a v3 candidate request, got "
                f"{type(request).__name__}")
        expected_hash = request.design_hash()
        compilation = FabricCompiler().compile(request)
        if compilation.status != "COMPILED":
            return _refuse(
                candidate.candidate_id, expected_hash,
                "COMPILE_FAILED"
                if compilation.status == "INVALID" else "UNSUPPORTED",
                compilation.status, compilation.error or compilation.status)
        assert compilation.bundle is not None
        locked = locked_consequences_of(compilation)
        try:
            lowered = lower_compile_workload(request)
            assert_traffic_classes_bound(
                lowered, compilation.bundle.vc_assignment)
        except (InvalidInput, UnsupportedSemantics, UnsupportedSchedule,
                MappingInvalid) as exc:
            return _refuse(
                candidate.candidate_id, expected_hash,
                "INVALID" if isinstance(exc, InvalidInput)
                else "UNSUPPORTED",
                "COMPILED", f"{type(exc).__name__}: {exc}", locked)
        unified = lowered.unified_traffic_class
        if unified is None:
            return _refuse(
                candidate.candidate_id, expected_hash, "UNSUPPORTED",
                "COMPILED",
                f"lowering spans classes {list(lowered.classes)}: "
                f"multi-class refused until a per-operation message "
                f"artifact lands", locked)
        self.calls += 1
        run_dir = self.run_root / candidate.candidate_id
        run_dir.mkdir(parents=True, exist_ok=True)
        outcome = FabricEvaluator().evaluate(
            compilation, lowered.graph,
            EvaluationOptions(
                backend=STANDALONE_BACKEND, traffic_class=unified,
                network_clock_hz=self.network_clock_hz,
                timeout_s=self.timeout_s,
                require_quiescence=self.require_quiescence,
                run_dir=str(run_dir), binary=self.binary,
                repo_root=self.repo_root))
        if outcome.status != "EVALUATED" or \
                outcome.performance_result is None:
            return _refuse(
                candidate.candidate_id, expected_hash, "UNSUPPORTED",
                "COMPILED",
                f"{outcome.status}: {outcome.reason}", locked,
                outcome.performance_result_id)
        report = RequirementEvaluator.evaluate(
            request, lowered.graph, outcome.performance_result)
        if not report_passes(report):
            bad = [e for e in report.get("entries", [])
                   if e.get("binding") and
                   e.get("verdict") != "SATISFIED"]
            return _refuse(
                candidate.candidate_id, expected_hash, "UNSUPPORTED",
                "COMPILED",
                "binding requirements not satisfied: " + "; ".join(
                    f"[{e.get('requirement_index')}:"
                    f"{e.get('traffic_class')}/"
                    f"{e.get('qos_class')}={e.get('verdict')}]"
                    for e in bad) or "unsatisfied",
                locked, outcome.performance_result_id, report)
        return CandidateEvaluation(
            candidate_id=candidate.candidate_id,
            design_hash=expected_hash, status="EVALUATED",
            objective_values=_real_objectives(outcome),
            locked_consequences=locked, compilation_status="COMPILED",
            error=None,
            performance_result_id=outcome.performance_result_id,
            requirement_report=report,
            requirement_report_id=report_identity(report))


__all__ = ["RealCandidateEvaluator"]
