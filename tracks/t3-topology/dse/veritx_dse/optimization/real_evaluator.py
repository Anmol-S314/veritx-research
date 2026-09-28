"""veritx_dse.optimization.real_evaluator — real CandidateEvaluationPort.

The production route (fake stays unit-only):

    candidate CompileRequest (v3)
      -> FabricCompiler.compile()              (LOCKED consequences)
      -> lower_compile_workload()              (P1C WorkloadGraph)
      -> assert_traffic_classes_bound()        (pre-spawn gate)
      -> evaluate_federated()                  (plan once, one execution
                                               per question, objectives read)
      -> authenticate_backend_evaluation()     (A4 evidence-chain proof,
                                               network leg only)
      -> CandidateEvaluation (proof + evidenced objectives only)

Feasibility law: `evaluation_status` preserves the REAL taxonomy and
is never collapsed. EVALUATED means compiled AND every requested
question backend-evaluated (binding product requirements may still
fail — those candidates keep their measurements and a typed reason,
and the Optimizer makes them ineligible). Compile-phase refusals
(INVALID or UNSUPPORTED compiler verdicts) are COMPILE_FAILED;
lowering refusals are INVALID or UNSUPPORTED; backend-phase outcomes
stay BACKEND_UNAVAILABLE / FAILED / UNSUPPORTED, plus INCONCLUSIVE
when a native verdict drained without deciding (Ramulator). Whatever
provenance exists is still bound (locked consequences,
performance_result_id, per-objective federation provenance) —
visible, auditable, never Pareto-eligible. `compilation_status`
separately keeps the FabricCompiler verdict.

Federation law: the candidate compiles ONCE, the canonical context is
built ONCE, the planner adjudicates ONCE, and each required question
executes ONCE — objectives only read the analyses their question
produced (three objectives over NETWORK_COMPLETION + DRAM_TIMING is
one BookSim run plus one Ramulator run, not three). A
``requested_backend`` is never invented here: when the definition
constrains an objective to a backend the planner did not select, the
objective is unmeasured with an exact reason — never silently
substituted.

Objectives are evidenced measurements only: network-question metrics
come from the FROZEN certified metric authority over the VERIFIED
network performance result (unchanged sealed path); every other
question's metrics come from that analysis's normalized envelope
(scalar objectives bind dimension-free metrics only). There is
deliberately no area/latency-analytic key: unmeasured is absent,
never faked. Widening the metric set means binding a new qualified
producer (metric_registry.py), not adding a key here.

A4 proof: every network-EVALUATED outcome (including a
requirement-violating one) carries the `AuthenticatedBackendEvaluation`
built by Worker B's evidence-chain authority, so the Optimizer can
verify the proof and extract authoritative metrics from the derived
claims instead of trusting the `certified-backend` label or the
evaluator's own objective values. A non-EVALUATED outcome carries no
network measurements and therefore no proof. Non-network analyses
carry their own native evidence (native_evidence_id in the
provenance); the normalized envelope is a view, never the authority.

Legacy parity: with no ``objectives``/``questions`` (the gateway
single-evaluation path), this port evaluates NETWORK_COMPLETION only
through the certified BookSim leg with the same effective parameters
as before (binary, repo root, network clock, timeout, seed 0,
quiescent default) — the only difference is transport (evidence lives
under analyses/network_completion/ of the slot). Objective values are
bit-identical to the pre-federation path.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from veritx_dse.application.authenticated_evaluation import (
    authenticate_backend_evaluation,
)
from veritx_dse.application.evaluation_question import EvaluationQuestion
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.fabric_evaluator import (
    BACKEND_UNAVAILABLE,
    EVALUATED,
    FAILED,
    UNSUPPORTED,
)
from veritx_dse.application.federated_evaluator import (
    ANALYSIS_EVALUATED,
    ANALYSIS_FAILED,
    ANALYSIS_INCONCLUSIVE,
    ANALYSIS_UNAVAILABLE,
    BookSimRunOptions,
    evaluate_federated,
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
    ObjectiveProvenance,
    locked_consequences_of,
)
from veritx_dse.optimization.metric_registry import (
    CERTIFIED_METRIC_REGISTRY,
)
from veritx_dse.workload.intent_lowering import (
    assert_traffic_classes_bound,
    lower_compile_workload,
)

#: Optimizer-vocabulary status for a native verdict that drained without
#: deciding (Ramulator INCONCLUSIVE). The federated 4-status vocabulary
#: carries it inside the analysis reason (status FAILED + "native memory
#: evidence INCONCLUSIVE: ..."); this port promotes it to an explicit
#: candidate status so UNAVAILABLE memory backends never collapse into
#: infeasible and inconclusive drains never read as crashes.
INCONCLUSIVE = "INCONCLUSIVE"

NETWORK_QUESTION = EvaluationQuestion.NETWORK_COMPLETION


def _refuse(candidate_id: str, design_hash: str, status: str,
            compilation_status: str, error: str,
            locked: dict[str, Any] | None = None,
            performance_result_id: str | None = None,
            requirement_report: dict[str, Any] | None = None,
            objective_values: dict[str, float] | None = None,
            workload: Any = None,
            verified_performance_result: Any = None,
            authenticated_proof: Any = None,
            objective_provenance: dict[str, Any] | None = None,
            objective_unmeasured_reasons: dict[str, str] | None = None,
            federated_analyses: tuple[Any, ...] = (),
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
        authenticated_proof=authenticated_proof,
        objective_provenance=dict(objective_provenance or {}),
        objective_unmeasured_reasons=dict(
            objective_unmeasured_reasons or {}),
        federated_analyses=tuple(federated_analyses or ()))


def _verified_objectives(verified: Any) -> dict[str, float]:
    """Evidenced measurements only, from the FROZEN certified metric
    registry over the VERIFIED performance result. No analytic stand-ins
    and no bare backend statistics: a metric with no registered producer
    is absent, never faked. (Display projection only — the certified
    optimizer path re-extracts from the verified claims.)"""
    return CERTIFIED_METRIC_REGISTRY.extract_all(verified)


def _native_inconclusive(analysis: Any) -> bool:
    """An analysis whose native verdict drained without deciding.

    Two shapes (explicit coupling): the first-class
    ``ANALYSIS_INCONCLUSIVE`` status the federated evaluator emits for
    a non-PASS/non-FAILED native verdict, and the legacy FAILED row
    whose reason carries the ``"native memory evidence {STATUS}"``
    shape. The INCONCLUSIVE token names the native verdict — never a
    crash, never a refusal.
    """
    if getattr(analysis, "status", None) is ANALYSIS_INCONCLUSIVE:
        return True
    reason = getattr(analysis, "reason", None) or ""
    return (getattr(analysis, "status", None) is ANALYSIS_FAILED
            and reason.startswith("native memory evidence ")
            and "INCONCLUSIVE" in reason)


class RealCandidateEvaluator:
    """Production port: every candidate through the real pipeline.

    Storage layout: run_root/<candidate_id>/<eval-slot>/ holds one
    evaluation's federated evidence (plan.json,
    analyses/<question>/...). The candidate directory derives from
    candidate identity (stable transport, never scientific identity)
    and each evaluation gets a fresh OS-atomic slot via
    ``tempfile.mkdtemp()``, so the SAME evaluator instance can evaluate
    the SAME candidate repeatedly without overwriting a previous
    evaluation's evidence. No timestamp, PID or random token ever feeds
    a scientific identity: digests remain content-based.

    ``objectives`` (tuple of Objective) declares which questions must
    execute: the union of objective questions, each once. None means
    the legacy BookSim-only evaluation (NETWORK_COMPLETION through the
    certified leg). ``questions`` overrides explicitly. ``registry``
    injects the federation registry (tests script it; production builds
    the default registry from this port's binary/repo_root — the ASTRA
    binary resolves through the canonical resolver, Ramulator through
    its discovery authority).
    """

    def __init__(self, *, binary: str | Path | None = None,
                 network_clock_hz: int | None = None,
                 timeout_s: int = 300,
                 run_root: str | Path,
                 repo_root: str | Path | None = None,
                 require_quiescence: bool = True,
                 questions: tuple[EvaluationQuestion, ...] | None = None,
                 objectives: tuple[Any, ...] | None = None,
                 registry: Any | None = None,
                 astra_binary: str | Path | None = None,
                 ramulator_vendor_dir: str | Path | None = None,
                 ramulator_python: str | None = None):
        self.questions = None if questions is None else tuple(questions)
        self.objectives = None if objectives is None else tuple(objectives)
        # The BookSim binary is backend-optional: required only when the
        # study asks a network question. An ASTRA-only or Ramulator-only
        # study runs with binary=None; the planner adjudicates every
        # requested question, and evaluate() re-asserts the network
        # requirement before any BookSim-bound options are built, so a
        # None binary can never flow into a network leg. The legacy
        # default (no questions/objectives) still resolves to
        # NETWORK_COMPLETION and therefore still requires BookSim.
        if not binary and NETWORK_QUESTION in self._resolve_questions():
            raise EvaluationError(
                "real adapter needs a backend binary for "
                "NETWORK_COMPLETION — refusing a network study with "
                "no BookSim producer")
        self.binary = str(binary) if binary else None
        self.network_clock_hz = network_clock_hz
        self.timeout_s = timeout_s
        self.run_root = Path(run_root)
        self.repo_root = repo_root
        self.require_quiescence = require_quiescence
        self.registry = registry
        self.astra_binary = astra_binary
        self.ramulator_vendor_dir = ramulator_vendor_dir
        self.ramulator_python = ramulator_python
        self.calls = 0

    def _resolve_questions(self) -> tuple[EvaluationQuestion, ...]:
        """Exactly the questions this evaluation must execute."""
        if self.questions is not None:
            resolved = tuple(self.questions)
        elif self.objectives:
            seen: list[EvaluationQuestion] = []
            for objective in self.objectives:
                question = getattr(objective, "question", None)
                if not isinstance(question, EvaluationQuestion):
                    raise EvaluationError(
                        "federated objectives must carry an "
                        "EvaluationQuestion; "
                        f"{getattr(objective, 'metric', objective)!r} "
                        f"carries {question!r}")
                if question not in seen:
                    seen.append(question)
            resolved = tuple(seen)
        else:
            resolved = (NETWORK_QUESTION,)
        if not resolved:
            raise EvaluationError(
                "no federation question to execute — refusing an "
                "evaluation that would measure nothing")
        for question in resolved:
            if not isinstance(question, EvaluationQuestion):
                raise EvaluationError(
                    f"federation questions must be EvaluationQuestions, "
                    f"got {question!r}")
        return resolved

    def _resolve_registry(self) -> Any:
        """The real federation registry — never a second matrix."""
        if self.registry is not None:
            return self.registry
        from veritx_dse.backend.registry import default_backend_registry
        return default_backend_registry(
            booksim_bin=self.binary, repo_root=self.repo_root,
            astra_bin=self.astra_binary,
            ramulator_vendor_dir=self.ramulator_vendor_dir,
            ramulator_python=self.ramulator_python)

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
        questions = self._resolve_questions()
        # Defense in depth for the backend-optional binary: a None
        # binary must never reach the BookSim-bound execution options.
        # Unreachable through __init__ (which refuses this combination),
        # but re-asserted here so post-construction mutation cannot
        # smuggle a network leg past the constructor gate.
        if NETWORK_QUESTION in questions and self.binary is None:
            raise EvaluationError(
                "real adapter needs a backend binary for "
                "NETWORK_COMPLETION — refusing a network evaluation "
                "with no BookSim producer")
        federated = evaluate_federated(
            compilation, questions, self._resolve_registry(),
            booksim_options=BookSimRunOptions(
                binary=self.binary, repo_root=self.repo_root,
                timeout_s=self.timeout_s,
                network_clock_hz=self.network_clock_hz),
            run_dir=str(run_dir))
        by_question = {a.question: a for a in federated.analyses}
        analyses = tuple(federated.analyses)

        network_analysis = by_question.get(NETWORK_QUESTION)
        if network_analysis is not None and \
                network_analysis.status == ANALYSIS_EVALUATED and \
                federated.network_evaluation is not None:
            return self._evaluated_network(
                candidate, expected_hash, compilation, locked, lowered,
                federated, network_analysis, analyses)

        # No measured network leg. Two honest cases, never collapsed:
        # (a) NETWORK_COMPLETION was not requested and every requested
        #     analysis EVALUATED: the study measured exactly what it
        #     asked — EVALUATED with the bound federated values and
        #     their provenance (no authenticated network proof and no
        #     product RequirementReport exist here; the Optimizer keeps
        #     such candidates visible but product-ineligible with a
        #     typed reason — never Pareto-eligible without a binding
        #     report, never refused as a forgery either);
        # (b) otherwise the exact backend-phase refusal taxonomy per
        #     question (an unavailable memory backend stays unavailable,
        #     never infeasible; an inconclusive native drain stays
        #     INCONCLUSIVE, never a crash).
        values, provenance, miss = self._bind_federated_objectives(
            by_question)
        if NETWORK_QUESTION not in questions and all(
                (row is not None
                 and row.status == ANALYSIS_EVALUATED)
                for row in (by_question.get(q) for q in questions)):
            return CandidateEvaluation(
                candidate_id=candidate.candidate_id,
                design_hash=expected_hash, status=EVALUATED,
                objective_values=values,
                locked_consequences=locked,
                compilation_status="COMPILED", error=None,
                performance_result_id=None,
                requirement_report=None,
                requirement_report_id=None,
                evaluation_authority=AUTHORITY_CERTIFIED_BACKEND,
                workload=lowered.graph,
                verified_performance_result=None,
                authenticated_proof=None,
                objective_provenance=provenance,
                objective_unmeasured_reasons=miss,
                federated_analyses=analyses)
        status, error = _refusal_status(questions, by_question)
        return _refuse(
            candidate.candidate_id, expected_hash, status,
            "COMPILED", error, locked,
            objective_values=values,
            workload=lowered.graph,
            objective_provenance=provenance,
            objective_unmeasured_reasons=miss,
            federated_analyses=analyses)

    def _evaluated_network(self, candidate: Any, expected_hash: str,
                           compilation: Any,
                           locked: dict[str, Any], lowered: Any,
                           federated: Any, network_analysis: Any,
                           analyses: tuple[Any, ...]) -> CandidateEvaluation:
        """The sealed network path: the EXISTING authenticated proof over
        the VERIFIED network performance result, plus federated readings
        for every other requested question."""
        outcome = federated.network_evaluation
        if outcome.performance_result is None:
            raise EvaluationError(
                "Federated NETWORK_COMPLETION returned EVALUATED without "
                "a verified performance result — refusing to bind "
                "measurements that do not exist")
        # A4: the authoritative proof is Worker B's evidence-chain
        # authentication, built from the live outcome's persisted
        # evidence; the canonical report comes from the proof.
        proof = authenticate_backend_evaluation(
            compilation=compilation,
            workload=lowered.graph,
            verified_result=outcome.performance_result,
            evidence_path=outcome.evidence_path,
            producer_identity=outcome.producer_identity)
        report = proof.requirement_report
        objectives = _verified_objectives(outcome.performance_result)
        values = dict(objectives)
        provenance = _network_provenance(
            self.objectives, network_analysis, values)
        extra_values, extra_provenance, miss = \
            self._bind_federated_objectives(
                {a.question: a for a in analyses
                 if a.question is not NETWORK_QUESTION})
        for key, value in extra_values.items():
            if key in values:
                raise EvaluationError(
                    f"federated question answers metric {key!r} that the "
                    f"authenticated network proof already evidences — "
                    f"refusing to overwrite a network measurement with a "
                    f"different model's number")
            values[key] = value
        provenance.update(extra_provenance)
        miss.update(_network_miss_reasons(
            self.objectives, values))
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
                objective_values=values,
                workload=lowered.graph,
                verified_performance_result=outcome.performance_result,
                authenticated_proof=proof,
                objective_provenance=provenance,
                objective_unmeasured_reasons=miss,
                federated_analyses=analyses)
        return CandidateEvaluation(
            candidate_id=candidate.candidate_id,
            design_hash=expected_hash, status="EVALUATED",
            objective_values=values,
            locked_consequences=locked, compilation_status="COMPILED",
            error=None,
            performance_result_id=outcome.performance_result_id,
            requirement_report=report,
            requirement_report_id=report_identity(report),
            evaluation_authority=AUTHORITY_CERTIFIED_BACKEND,
            workload=lowered.graph,
            verified_performance_result=outcome.performance_result,
            authenticated_proof=proof,
            objective_provenance=provenance,
            objective_unmeasured_reasons=miss,
            federated_analyses=analyses)

    def _bind_federated_objectives(
            self, by_question: dict[Any, Any]
            ) -> tuple[dict[str, float], dict[str, Any], dict[str, str]]:
        """Read non-network objectives from their analyses' envelopes.

        Returns (values, provenance, miss-reasons). Network-question
        objectives are never read here — they come from the
        authenticated proof, never from an envelope projection.
        """
        values: dict[str, float] = {}
        provenance: dict[str, Any] = {}
        miss: dict[str, str] = {}
        for objective in (self.objectives or ()):
            metric = getattr(objective, "metric", None)
            question = getattr(objective, "question", None)
            if question is NETWORK_QUESTION:
                continue
            if not isinstance(metric, str) or not metric:
                continue
            analysis = by_question.get(question)
            if analysis is None:
                miss[metric] = (
                    f"question {question.value} was not executed — "
                    f"objective {metric!r} has no analysis to read")
                continue
            constraint = getattr(objective, "backend_id", None)
            if constraint is not None and \
                    analysis.backend_id != constraint:
                miss[metric] = (
                    f"backend constraint {constraint!r} not satisfied: "
                    f"question {question.value} was planned on "
                    f"{analysis.backend_id!r} — never substituted")
                continue
            if analysis.status != ANALYSIS_EVALUATED or \
                    analysis.normalized_evidence is None:
                miss[metric] = (
                    f"question {question.value} on "
                    f"{analysis.backend_id!r} is {analysis.status}: "
                    f"{analysis.reason}")
                continue
            envelope = analysis.normalized_evidence
            scalars = [m for m in envelope.metrics
                       if m.key == metric and m.dimensions == ()]
            if not scalars:
                if any(m.key == metric for m in envelope.metrics):
                    miss[metric] = (
                        f"metric {metric!r} from {question.value} is "
                        f"measured with dimensions only "
                        f"(per-rank/per-request); a scalar objective "
                        f"cannot bind it — no invented key suffixes")
                else:
                    miss[metric] = (
                        f"metric {metric!r} not evidenced by "
                        f"{question.value} on {analysis.backend_id!r}")
                continue
            found = scalars[0]
            fidelity = analysis.model_fidelity
            provenance[metric] = ObjectiveProvenance(
                metric_key=metric, question=question,
                backend_id=analysis.backend_id,
                model_fidelity=(None if fidelity is None
                                else fidelity.value),
                qualification=analysis.qualification,
                native_evidence_id=analysis.native_evidence_id,
                unit=found.unit, value=float(found.value))
            values[metric] = float(found.value)
        return values, provenance, miss


def _network_provenance(objectives: tuple[Any, ...] | None,
                        analysis: Any,
                        values: dict[str, float]) -> dict[str, Any]:
    """Provenance for network-question objectives over the proof.

    Values stay the registry extraction (the authority); the envelope
    contributes transport facts only (backend, fidelity,
    qualification, native evidence id, unit lookup). A metric the proof
    does not evidence gets no provenance — it is unmeasured.
    """
    envelope = analysis.normalized_evidence
    units = {}
    if envelope is not None:
        for row in envelope.metrics:
            if row.dimensions == () and row.key not in units:
                units[row.key] = row.unit
    fidelity = analysis.model_fidelity
    out: dict[str, Any] = {}
    for objective in (objectives or ()):
        if getattr(objective, "question", None) is not NETWORK_QUESTION:
            continue
        metric = getattr(objective, "metric", None)
        if metric in values:
            out[metric] = ObjectiveProvenance(
                metric_key=metric, question=NETWORK_QUESTION,
                backend_id=analysis.backend_id,
                model_fidelity=(None if fidelity is None
                                else fidelity.value),
                qualification=analysis.qualification,
                native_evidence_id=analysis.native_evidence_id,
                unit=units.get(metric), value=values[metric])
    return out


def _network_miss_reasons(objectives: tuple[Any, ...] | None,
                          values: dict[str, float]) -> dict[str, str]:
    """Exact reasons for network objectives the proof did not evidence."""
    miss: dict[str, str] = {}
    for objective in (objectives or ()):
        if getattr(objective, "question", None) is not NETWORK_QUESTION:
            continue
        metric = getattr(objective, "metric", None)
        if isinstance(metric, str) and metric and metric not in values:
            miss[metric] = (
                f"metric {metric!r} not evidenced by the authenticated "
                f"network proof over NETWORK_COMPLETION")
    return miss


def _refusal_status(questions: tuple[EvaluationQuestion, ...],
                    by_question: dict[Any, Any]
                    ) -> tuple[str, str]:
    """The exact backend-phase taxonomy, never collapsed.

    Precedence: FAILED (a backend crashed) > INCONCLUSIVE (a native
    verdict drained without deciding) > BACKEND_UNAVAILABLE (no backend
    could run) > UNSUPPORTED (no backend represents the workload). An
    unavailable memory backend stays unavailable — never infeasible.
    """
    parts = []
    for question in questions:
        analysis = by_question.get(question)
        status = "MISSING" if analysis is None else analysis.status
        reason = "" if analysis is None else (analysis.reason or "")
        parts.append(f"{question.value}: {status}"
                     + (f" ({reason})" if reason else ""))
    details = "; ".join(parts)
    per_question = {q: by_question.get(q) for q in questions}
    statuses = {(None if row is None else row.status)
                for row in per_question.values()}
    if ANALYSIS_FAILED in statuses:
        crashed = [q for q, row in per_question.items()
                   if row is not None
                   and row.status == ANALYSIS_FAILED
                   and not _native_inconclusive(row)]
        if crashed:
            return FAILED, f"{FAILED}: {details}"
        return INCONCLUSIVE, f"{INCONCLUSIVE}: {details}"
    if ANALYSIS_INCONCLUSIVE in statuses:
        return INCONCLUSIVE, f"{INCONCLUSIVE}: {details}"
    if ANALYSIS_UNAVAILABLE in statuses or None in statuses:
        return BACKEND_UNAVAILABLE, f"{BACKEND_UNAVAILABLE}: {details}"
    return UNSUPPORTED, f"{UNSUPPORTED}: {details}"


__all__ = ["INCONCLUSIVE", "RealCandidateEvaluator"]
