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
    EvaluationQuestion.DRAM_TIMING: ("RAMULATOR2_HBM3_V1",),
}


class EvaluationPlanner:
    """Deterministic backend selection over a registry.

    Selection law, in order:
      1. query every registered adapter for the question;
      2. an explicitly requested backend is authoritative: unknown is a
         planning error; known returns exactly its row (refusal or
         selection) — never a silent substitution;
      3. drop UNSUPPORTED assessments (they cannot represent);
      4. among the rest, prefer READY over BLOCKED/UNAVAILABLE;
      5. otherwise apply the stated per-question preference order;
      6. ties beyond that are refused loudly, never broken silently
         by registry order;
      7. when nothing qualifies, emit an UNSUPPORTED/BLOCKED/UNAVAILABLE
         row carrying the best (deterministic) refusal reason;
      8. an empty registry is an UNAVAILABLE row, never a crash.
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
        # the bundle's fabric identity is its resolved_fabric child's
        # hash (RT v1 accessor or canonical attribute — same shim the
        # bundle itself uses)
        def _hash_of(obj: object, name: str) -> str:
            value = getattr(obj, name)
            return value() if callable(value) else value
        return EvaluationPlan(
            design_hash=context.design_hash,
            resolved_fabric_hash=_hash_of(
                context.bundle.resolved_fabric, "resolved_fabric_hash"),
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
        if not assessments:
            return PlannedAnalysis(
                question=question, backend_id=None, fidelity=None,
                support=SupportLevel.UNSUPPORTED,
                readiness=BackendReadiness.UNAVAILABLE,
                qualification_profile=None,
                reason="no backend is registered for this evaluation",
                limitations=())
        if requested_backend is not None:
            return self._plan_explicit(
                question, assessments, requested_backend)
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
        best_rank = rank(representable[0])
        contenders = [bid for bid, a in representable
                      if rank((bid, a)) == best_rank]
        if len(set(contenders)) > 1:
            raise EvaluationPlanError(
                f"unresolved tie for {question.value}: backends "
                f"{sorted(set(contenders))} are equally ranked and the "
                f"preference law does not distinguish them; refusing "
                f"rather than breaking the tie by registry order")
        best_backend, best = representable[0]
        return _planned(question, best_backend, best)

    def _plan_explicit(
        self,
        question: EvaluationQuestion,
        assessments: list[tuple[str, BackendAssessment]],
        requested_backend: str,
    ) -> PlannedAnalysis:
        """An explicitly requested backend means exactly that backend.

        Unknown is a planning error. Known returns its own row —
        refusal or selection — never a silent substitution of another
        backend.
        """
        for backend_id, assessment in assessments:
            if backend_id != requested_backend:
                continue
            if assessment.support is SupportLevel.UNSUPPORTED:
                return PlannedAnalysis(
                    question=question, backend_id=None, fidelity=None,
                    support=assessment.support,
                    readiness=assessment.readiness,
                    qualification_profile=None,
                    reason=assessment.reason,
                    limitations=assessment.limitations)
            return _planned(question, backend_id, assessment)
        raise EvaluationPlanError(
            f"requested backend {requested_backend!r} is not registered; "
            f"known backends: "
            f"{sorted(bid for bid, _ in assessments) or 'none'}")


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
