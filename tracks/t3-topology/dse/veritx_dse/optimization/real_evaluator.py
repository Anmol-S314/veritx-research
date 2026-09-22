"""veritx_dse.optimization.real_evaluator — real CandidateEvaluationPort.

The production route (fake stays unit-only):

    candidate CompileRequest (v3)
      -> FabricCompiler.compile()              (LOCKED consequences)
      -> lower_compile_workload()              (P1C WorkloadGraph)
      -> assert_traffic_classes_bound()        (pre-spawn gate)
      -> FabricEvaluator.evaluate()            (P1B authenticated perf)
      -> authenticate_backend_evaluation()     (A4 evidence-chain proof)
      -> CandidateEvaluation (proof + evidenced objectives only)

Feasibility law: `evaluation_status` preserves the REAL taxonomy and
is never collapsed. EVALUATED means compiled AND backend-evaluated
(binding product requirements may still fail — those candidates keep
their measurements and a typed reason, and the Optimizer makes them
ineligible). Compile-phase refusals (INVALID or UNSUPPORTED compiler
verdicts) are COMPILE_FAILED; lowering refusals are INVALID or
UNSUPPORTED; backend-phase outcomes stay BACKEND_UNAVAILABLE /
FAILED / UNSUPPORTED. Whatever provenance exists is still bound
(locked consequences, performance_result_id) — visible, auditable,
never Pareto-eligible. `compilation_status` separately keeps the
FabricCompiler verdict.

Objectives are evidenced measurements only: metrics the registered
metric authority can extract from the carried VerifiedPerformanceResult
(network completion cycles/timestamp from the authenticated window
binding). There is deliberately no area/latency-analytic key: unmeasured
is absent, never faked. Widening the metric set means binding a new
qualified producer (metric_authority.py), not adding a key here.

A4 proof: every EVALUATED outcome (including a requirement-violating
one) carries the `AuthenticatedBackendEvaluation` built by Worker B's
evidence-chain authority, so the Optimizer can verify the proof and
extract authoritative metrics from the derived claims instead of
trusting the `certified-backend` label or the evaluator's own objective
values. A non-EVALUATED outcome carries no measurements and therefore no
proof.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from veritx_dse.application.authenticated_evaluation import (
    authenticate_backend_evaluation,
)
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.fabric_evaluator import (
    BACKEND_UNAVAILABLE,
    EVALUATED,
    FAILED,
    STANDALONE_BACKEND,
    UNSUPPORTED,
    EvaluationOptions,
    FabricEvaluator,
)
from veritx_dse.application.requirements import (
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
    AUTHORITY_CERTIFIED_BACKEND,
    CandidateEvaluation,
    EvaluationError,
    locked_consequences_of,
)
from veritx_dse.optimization.metric_authority import (
    extract_authoritative_metrics,
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
            objective_values: dict[str, float] | None = None,
            workload: Any = None,
            verified_performance_result: Any = None,
            authenticated_proof: Any = None,
            ) -> CandidateEvaluation:
    """Build a non-success outcome (or a requirement-violating EVALUATED
    outcome when measurements exist). The status is the evaluator's own
    taxonomy value and is never collapsed into UNSUPPORTED here."""
    return CandidateEvaluation(
        candidate_id=candidate_id, design_hash=design_hash,
        status=status, objective_values=dict(objective_values or {}),
        locked_consequences=dict(locked or {}),
        compilation_status=compilation_status, error=error,
        performance_result_id=performance_result_id,
        requirement_report=requirement_report,
        requirement_report_id=(report_identity(requirement_report)
                               if requirement_report is not None else None),
        evaluation_authority=AUTHORITY_CERTIFIED_BACKEND,
        workload=workload,
        verified_performance_result=verified_performance_result,
        authenticated_proof=authenticated_proof)


def _verified_objectives(verified: Any) -> dict[str, float]:
    """Evidenced measurements only, from the registered metric authority
    over the VERIFIED performance result. No analytic stand-ins and no
    bare backend statistics: a metric with no registered producer is
    absent, never faked."""
    return extract_authoritative_metrics(verified)


class RealCandidateEvaluator:
    """Production port: every candidate through the real pipeline.

    Storage layout: run_root/<candidate_id>/<eval-slot>/ holds one
    evaluation's backend evidence. The candidate directory derives from
    candidate identity (stable transport, never scientific identity) and
    each evaluation gets a fresh OS-atomic slot via
    ``tempfile.mkdtemp()``, so the SAME evaluator instance can evaluate
    the SAME candidate repeatedly without overwriting a previous
    evaluation's evidence. No timestamp, PID or random token ever feeds
    a scientific identity: digests remain content-based.
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
            # Compile-phase refusal: ALL compiler verdicts (INVALID or
            # UNSUPPORTED) map to COMPILE_FAILED, kept distinct from the
            # backend-phase BACKEND_UNAVAILABLE/FAILED/UNSUPPORTED below;
            # the compiler's own verdict stays in compilation_status.
            return _refuse(
                candidate.candidate_id, expected_hash,
                "COMPILE_FAILED", compilation.status,
                compilation.error or compilation.status)
        if compilation.bundle is None:
            raise EvaluationError(
                "FabricCompiler returned COMPILED without a bundle — "
                "refusing to bind fabricated LOCKED consequences")
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
                candidate.candidate_id, expected_hash, UNSUPPORTED,
                "COMPILED",
                f"lowering spans classes {list(lowered.classes)}: "
                f"multi-class refused until a per-operation message "
                f"artifact lands", locked)
        self.calls += 1
        # Collision-free per-evaluation evidence slot. The candidate
        # directory is stable transport; mkdtemp() is the OS-atomic
        # uniqueness mechanism (the path is transport, not science), so
        # re-evaluating the same candidate with the same evaluator both
        # completes and never overwrites a prior slot.
        candidate_dir = self.run_root / candidate.candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)
        run_dir = Path(tempfile.mkdtemp(dir=str(candidate_dir),
                                        prefix="eval-"))
        outcome = FabricEvaluator().evaluate(
            compilation, lowered.graph,
            EvaluationOptions(
                backend=STANDALONE_BACKEND, traffic_class=unified,
                network_clock_hz=self.network_clock_hz,
                timeout_s=self.timeout_s,
                require_quiescence=self.require_quiescence,
                run_dir=str(run_dir), binary=self.binary,
                repo_root=self.repo_root))
        if outcome.status != EVALUATED:
            if outcome.status not in (BACKEND_UNAVAILABLE, UNSUPPORTED,
                                      FAILED):
                raise EvaluationError(
                    f"FabricEvaluator returned unknown status "
                    f"{outcome.status!r} — refusing to collapse an "
                    "unknown outcome into the status taxonomy")
            return _refuse(
                candidate.candidate_id, expected_hash, outcome.status,
                "COMPILED",
                f"{outcome.status}: {outcome.reason}", locked,
                outcome.performance_result_id)
        if outcome.performance_result is None:
            raise EvaluationError(
                "FabricEvaluator returned EVALUATED without a verified "
                "performance result — refusing to bind measurements that "
                "do not exist")
        # A4: the authoritative proof is Worker B's evidence-chain
        # authentication, built from the live outcome's persisted
        # evidence; the canonical report comes from the proof.
        proof = authenticate_backend_evaluation(
            compilation=compilation, workload=lowered.graph,
            verified_result=outcome.performance_result,
            evidence_path=outcome.evidence_path,
            producer_identity=outcome.producer_identity)
        report = proof.requirement_report
        objectives = _verified_objectives(outcome.performance_result)
        if not report_passes(report):
            bad = [e for e in report.get("entries", [])
                   if e.get("binding") and
                   e.get("verdict") != "SATISFIED"]
            # Simulated successfully, product requirements failed: the
            # evaluation stays EVALUATED with its measurements and a
            # typed reason; the Optimizer makes it Pareto-ineligible.
            # Never relabel a measured run as UNSUPPORTED.
            return _refuse(
                candidate.candidate_id, expected_hash, EVALUATED,
                "COMPILED",
                "binding requirements not satisfied: " + "; ".join(
                    f"[{e.get('requirement_index')}:"
                    f"{e.get('traffic_class')}/"
                    f"{e.get('qos_class')}={e.get('verdict')}]"
                    for e in bad) or "unsatisfied",
                locked, outcome.performance_result_id, report,
                objective_values=objectives,
                workload=lowered.graph,
                verified_performance_result=outcome.performance_result,
                authenticated_proof=proof)
        return CandidateEvaluation(
            candidate_id=candidate.candidate_id,
            design_hash=expected_hash, status="EVALUATED",
            objective_values=objectives,
            locked_consequences=locked, compilation_status="COMPILED",
            error=None,
            performance_result_id=outcome.performance_result_id,
            requirement_report=report,
            requirement_report_id=report_identity(report),
            evaluation_authority=AUTHORITY_CERTIFIED_BACKEND,
            workload=lowered.graph,
            verified_performance_result=outcome.performance_result,
            authenticated_proof=proof)


__all__ = ["RealCandidateEvaluator"]
