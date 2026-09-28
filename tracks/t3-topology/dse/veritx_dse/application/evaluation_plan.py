"""The evaluation plan — where backend choice belongs.

The planner asks every registered adapter one question per requested
analysis, applies a DETERMINISTIC selection law, and returns a plan.
It never executes anything and never silently downgrades semantics: an
analysis with no qualifying backend is a BLOCKED or UNSUPPORTED row
with a reason, not a substitution.
"""
from __future__ import annotations

from dataclasses import dataclass

from veritx_dse.application.evaluation_context import (
    CanonicalEvaluationContext,
)
from veritx_dse.application.evaluation_question import EvaluationQuestion
from veritx_dse.backend.adapter import (
    BackendAssessment, BackendReadiness, ModelFidelity, SupportLevel,
)
from veritx_dse.backend.registry import BackendRegistry


class EvaluationPlanError(ValueError):
    """The planning request itself was malformed."""


@dataclass(frozen=True)
class PlannedAnalysis:
    """One requested question and the federation's adjudicated answer."""

    question: EvaluationQuestion
    backend_id: str | None
    fidelity: ModelFidelity | None
    support: SupportLevel
    readiness: BackendReadiness
    qualification_profile: str | None
    reason: str | None
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationPlan:
    """The complete plan for one canonical context."""

    design_hash: str
    resolved_fabric_hash: str
    analyses: tuple[PlannedAnalysis, ...]

    def ready(self, question: EvaluationQuestion) -> PlannedAnalysis | None:
        for analysis in self.analyses:
            if analysis.question is question and \
                    analysis.readiness is BackendReadiness.READY:
                return analysis
        return None


#: deterministic preference when several backends qualify for one
#: question. Order is the LAW, stated here once: earlier beats later.
#: Installation order in the registry can never alter selection.
_QUESTION_PREFERENCE: dict[EvaluationQuestion, tuple[str, ...]] = {
    EvaluationQuestion.NETWORK_COMPLETION: ("BOOKSIM_STANDALONE",),
    EvaluationQuestion.SYSTEM_MAKESPAN: ("ASTRA2_EMBEDDED_BOOKSIM",),
    EvaluationQuestion.COMMUNICATION_EXPOSURE: ("ASTRA2_EMBEDDED_BOOKSIM",),
    EvaluationQuestion.PER_RANK_COMPLETION: ("ASTRA2_EMBEDDED_BOOKSIM",),
}


class EvaluationPlanner:
    """Deterministic backend selection over a registry.

    Selection law, in order:
      1. query every registered adapter for the question;
      2. drop UNSUPPORTED assessments (they cannot represent);
      3. among the rest, prefer READY over BLOCKED/UNAVAILABLE;
      4. prefer an explicitly requested backend when it qualifies;
      5. otherwise apply the stated per-question preference order;
      6. ties beyond that are refused loudly, never broken silently;
      7. when nothing qualifies, emit an UNSUPPORTED/BLOCKED/UNAVAILABLE
         row carrying the best (deterministic) refusal reason.
    """

    def plan(
        self,
        context: CanonicalEvaluationContext,
        questions: tuple[EvaluationQuestion, ...],
        registry: BackendRegistry,
        *,
        requested_backend: str | None = None,
    ) -> EvaluationPlan:
        if not questions:
            raise EvaluationPlanError(
                "plan() needs at least one evaluation question")
        seen: set[EvaluationQuestion] = set()
        for question in questions:
            if not isinstance(question, EvaluationQuestion):
                raise EvaluationPlanError(
                    f"questions must be EvaluationQuestion values, got "
                    f"{question!r}")
            if question in seen:
                raise EvaluationPlanError(
                    f"duplicate evaluation question {question!r}")
            seen.add(question)

        analyses = tuple(
            self._plan_one(context, question, registry, requested_backend)
            for question in questions)
        fabric_hash = context.bundle.resolved_fabric_hash
        if callable(fabric_hash):
            fabric_hash = fabric_hash()  # RT v1 accessor vs canonical attr
        return EvaluationPlan(
            design_hash=context.design_hash,
            resolved_fabric_hash=fabric_hash,
            analyses=analyses)

    def _plan_one(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
        registry: BackendRegistry,
        requested_backend: str | None,
    ) -> PlannedAnalysis:
        assessments: list[tuple[str, BackendAssessment]] = []
        for adapter in registry.adapters():
            assessments.append(
                (adapter.backend_id, adapter.assess(context, question)))
        representable = [(bid, a) for bid, a in assessments
                         if a.support is not SupportLevel.UNSUPPORTED]
        if not representable:
            # deterministic: report the registry-order-first refusal; an
            # UNSUPPORTED row is unbound (no backend could represent), so
            # backend_id stays None while the refusal reason is named.
            first_backend, first = assessments[0]
            return PlannedAnalysis(
                question=question, backend_id=None, fidelity=None,
                support=SupportLevel.UNSUPPORTED,
                readiness=first.readiness,
                qualification_profile=None,
                reason=first.reason
                or "no registered backend represents this question",
                limitations=())

        def rank(entry: tuple[str, BackendAssessment]) -> tuple[int, int]:
            backend_id, assessment = entry
            preference = (_QUESTION_PREFERENCE.get(question, ())
                          .index(backend_id)
                          if backend_id in
                          _QUESTION_PREFERENCE.get(question, ())
                          else len(_QUESTION_PREFERENCE.get(question, ())))
            readiness_rank = {BackendReadiness.READY: 0,
                              BackendReadiness.BLOCKED: 1,
                              BackendReadiness.UNAVAILABLE: 2}[
                                  assessment.readiness]
            return (readiness_rank, preference)

        representable.sort(key=rank)
        if requested_backend is not None:
            for backend_id, assessment in representable:
                if backend_id == requested_backend:
                    return _planned(question, backend_id, assessment)
        best_backend, best = representable[0]
        return _planned(question, best_backend, best)


def _planned(question: EvaluationQuestion, backend_id: str,
             assessment: BackendAssessment) -> PlannedAnalysis:
    fidelity = assessment.fidelity \
        if assessment.readiness is BackendReadiness.READY else None
    return PlannedAnalysis(
        question=question, backend_id=backend_id, fidelity=fidelity,
        support=assessment.support, readiness=assessment.readiness,
        qualification_profile=assessment.qualification_profile,
        reason=assessment.reason, limitations=assessment.limitations)


__all__ = [
    "EvaluationPlan", "EvaluationPlanError", "EvaluationPlanner",
    "PlannedAnalysis",
]
