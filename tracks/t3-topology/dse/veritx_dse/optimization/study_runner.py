"""Wave-F study runner — executes a MultiScenarioStudy beside the optimizer.

AUTHORITY (supervisor decision, final): space_multiscenario stays OUT of
Optimizer/result.py/real_evaluator.py. This module is the NEW execution
authority for multi-scenario studies: build/accounting from
space_multiscenario, one federated execution per (candidate, scenario,
question) at most, evidence rows bound per scenario+candidate.

What this module NEVER does:
- certified Pareto/selection (result_class is STUDY_GRADE, never
  CERTIFIED_PRODUCT; ``certified=True`` refuses — the Optimizer stays the
  only certified path);
- backend pinning (planner AUTO only; a ScenarioObjective with
  ``backend_id`` set refuses — pinning is expert execution policy);
- metric extraction (per-question outcomes + native evidence ids ride the
  rows; metric names live in the metric authority, never re-derived
  here);
- double evaluation (ALIAS known_ids + canonical-prefix tail are never
  attempted; verify_tail_agreement re-checks at the end);
- scenario transplant (scenario_request_for + check_hardware_consistent
  gate every execution).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.fabric_evaluator import EVALUATED
from veritx_dse.core.artifact import content_id
from veritx_dse.optimization.space_multiscenario import (
    EVAL_FAILED,
    EVAL_SUCCEEDED,
    EvaluationRow,
    MultiScenarioStudy,
    StudyError,
    accounting_summary,
    build_study_candidates,
    check_hardware_consistent,
    eligible_ids,
    scenario_request_for,
    verify_tail_agreement,
)

STUDY_RUN_DOMAIN = "veritx/multiscenario-study-run/v1"
RESULT_CLASS_STUDY_GRADE = "STUDY_GRADE"


@dataclass
class StudyRunConfig:
    """Execution inputs for run_study (all optional)."""

    registry: Any = None
    run_root: Path | str | None = None
    booksim_options: Any = None
    astra_options: Any = None
    ramulator_options: Any = None


@dataclass(frozen=True)
class ScenarioRunDetail:
    """One executed (candidate, scenario) row with per-question linkage."""

    candidate_id: str
    scenario_id: str
    status: str
    reason: str | None
    compilation_status: str
    questions: tuple[tuple[str, str], ...] = ()
    evidence_ids: tuple[tuple[str, str], ...] = ()
    reused_ids: tuple[tuple[str, str | None], ...] = ()


@dataclass
class StudyRunResult:
    """The executed study: bins + rows + accounting + identity."""

    study_id: str
    result_class: str
    ledger_valid: int
    ledger_aliases: int
    ledger_invalid: int
    ledger_not_evaluated: int
    rows: tuple[ScenarioRunDetail, ...]
    accounting: dict[str, Any]
    result_id: str = ""

    def __post_init__(self):
        if not self.result_id:
            object.__setattr__(self, "result_id", content_id(
                STUDY_RUN_DOMAIN, {
                    "study_id": self.study_id,
                    "result_class": self.result_class,
                    "rows": [
                        {"candidate_id": r.candidate_id,
                         "scenario_id": r.scenario_id,
                         "status": r.status,
                         "reason": r.reason,
                         "questions": [list(q) for q in r.questions],
                         "evidence_ids": [list(e) for e in r.evidence_ids],
                         "reused_ids": [list(e) for e in r.reused_ids]}
                        for r in self.rows],
                    "accounting": self.accounting,
                }))


def _resolve_registry(config: StudyRunConfig):
    if config.registry is not None:
        return config.registry
    from veritx_dse.backend.registry import default_backend_registry
    return default_backend_registry()


def _default_evaluate(config: StudyRunConfig) -> Callable:
    from veritx_dse.application.federated_evaluator import (
        evaluate_federated,
    )
    registry = _resolve_registry(config)

    def run(compilation, questions, run_dir):
        return evaluate_federated(
            compilation, questions, registry,
            booksim_options=config.booksim_options,
            astra_options=config.astra_options,
            ramulator_options=config.ramulator_options,
            run_dir=str(run_dir))
    return run


def _scenario_questions(study: MultiScenarioStudy, scenario_id: str):
    questions: list[Any] = []
    for objective in study.objectives:
        if objective.scenario is not None and \
                objective.scenario != scenario_id:
            continue
        if objective.backend_id is not None:
            raise StudyError(
                f"objective {objective.metric!r} pins backend "
                f"{objective.backend_id!r}: the study runner is AUTO-only "
                "(planner chooses the qualified producer); backend pinning "
                "is expert execution policy, unsupported here")
        if objective.question not in questions:
            questions.append(objective.question)
    if not questions:
        raise StudyError(
            f"scenario {scenario_id!r} has no objective: a scenario with "
            "nothing asked is not executed")
    return tuple(questions)


def run_study(study: MultiScenarioStudy, *,
              config: StudyRunConfig | None = None,
              known_ids: frozenset[str] = frozenset(),
              certified: bool = False,
              evaluate: Callable | None = None,
              ) -> StudyRunResult:
    """Execute every eligible (candidate, scenario) pair, at most once."""
    if certified:
        raise StudyError(
            "certified entry is Optimizer-only (optimize_certified): the "
            "study runner is STUDY_GRADE research, never certified Pareto")
    config = config or StudyRunConfig()
    run = evaluate or _default_evaluate(config)
    if config.run_root is not None:
        root = Path(config.run_root)
        root.mkdir(parents=True, exist_ok=True)
    else:
        import tempfile
        root = Path(tempfile.mkdtemp(prefix="study-run-"))
    ledger = build_study_candidates(study, known_ids)
    eligible = set(eligible_ids(ledger))
    by_id = {c.candidate_id: c for c in ledger.valid}
    details: list[ScenarioRunDetail] = []
    eval_rows: list[EvaluationRow] = []
    compiler = FabricCompiler()
    for candidate_id in [c.candidate_id for c in ledger.valid
                         if c.candidate_id in eligible]:
        candidate = by_id[candidate_id]
        requests = [scenario_request_for(candidate, scenario)
                    for scenario in study.scenarios]
        check_hardware_consistent(requests)
        for scenario, request in zip(study.scenarios, requests):
            sid = scenario.scenario_id
            compilation = compiler.compile(request)
            if compilation.status != "COMPILED":
                details.append(ScenarioRunDetail(
                    candidate_id=candidate_id, scenario_id=sid,
                    status=EVAL_FAILED,
                    reason=f"compilation {compilation.status}: "
                           f"{compilation.error}",
                    compilation_status=compilation.status))
                eval_rows.append(EvaluationRow(
                    candidate_id=candidate_id, scenario_id=sid,
                    status=EVAL_FAILED,
                    reason="compilation refused"))
                continue
            questions = _scenario_questions(study, sid)
            run_dir = root / candidate_id / sid
            run_dir.mkdir(parents=True, exist_ok=True)
            try:
                outcome = run(compilation, questions, run_dir)
            except Exception as exc:
                details.append(ScenarioRunDetail(
                    candidate_id=candidate_id, scenario_id=sid,
                    status=EVAL_FAILED,
                    reason=f"{type(exc).__name__}: {exc}",
                    compilation_status="COMPILED"))
                eval_rows.append(EvaluationRow(
                    candidate_id=candidate_id, scenario_id=sid,
                    status=EVAL_FAILED,
                    reason=f"{type(exc).__name__}: {exc}"))
                continue
            q_status: list[tuple[str, str]] = []
            q_evidence: list[tuple[str, str]] = []
            q_reused: list[tuple[str, str | None]] = []
            ok = True
            for analysis in outcome.analyses:
                qn = analysis.question.value
                q_status.append((qn, analysis.status))
                if analysis.status == EVALUATED and \
                        analysis.native_evidence_id:
                    q_evidence.append((qn, analysis.native_evidence_id))
                else:
                    ok = False
                q_reused.append((qn, analysis.reused_evidence_id))
            details.append(ScenarioRunDetail(
                candidate_id=candidate_id, scenario_id=sid,
                status=EVAL_SUCCEEDED if ok else EVAL_FAILED,
                reason=None if ok else "; ".join(
                    f"{qn} {st}" for qn, st in q_status
                    if st != EVALUATED) or "no evaluated analysis",
                compilation_status="COMPILED",
                questions=tuple(q_status),
                evidence_ids=tuple(q_evidence),
                reused_ids=tuple(q_reused)))
            eval_rows.append(EvaluationRow(
                candidate_id=candidate_id, scenario_id=sid,
                status=EVAL_SUCCEEDED if ok else EVAL_FAILED,
                reason=details[-1].reason))
    accounting = accounting_summary(ledger, eval_rows)
    return StudyRunResult(
        study_id=study.study_id(),
        result_class=RESULT_CLASS_STUDY_GRADE,
        ledger_valid=len(ledger.valid),
        ledger_aliases=len(ledger.aliases),
        ledger_invalid=len(ledger.invalid),
        ledger_not_evaluated=len(ledger.not_evaluated),
        rows=tuple(details),
        accounting=accounting)


def evidence_index(result: StudyRunResult
                   ) -> dict[tuple[str, str, str], str]:
    """(candidate, scenario, question) -> native evidence id (evaluated only)."""
    index: dict[tuple[str, str, str], str] = {}
    for row in result.rows:
        for qn, eid in row.evidence_ids:
            index[(row.candidate_id, row.scenario_id, qn)] = eid
    return index


__all__ = [
    "STUDY_RUN_DOMAIN",
    "RESULT_CLASS_STUDY_GRADE",
    "StudyRunConfig",
    "ScenarioRunDetail",
    "StudyRunResult",
    "evidence_index",
    "run_study",
]
