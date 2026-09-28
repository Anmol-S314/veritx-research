"""Federation Commit 07 — the planner's deterministic selection law."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.evaluation_context import (  # noqa: E402
    CanonicalEvaluationContext,
)
from veritx_dse.application.evaluation_plan import (  # noqa: E402
    EvaluationPlanError, EvaluationPlanner,
)
from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.backend.adapter import (  # noqa: E402
    BackendAssessment, BackendReadiness, ModelFidelity, SupportLevel,
)
from veritx_dse.backend.registry import BackendRegistry  # noqa: E402


class _Ctx:
    """Minimal stand-in: the planner reads design/bundle hashes only."""

    def __init__(self):
        self.design_hash = "d" * 64
        self.bundle = type("B", (), {"resolved_fabric_hash": "f" * 64})()


def _assessment(backend="B", support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.READY, reason=None):
    return BackendAssessment(
        backend_id=backend,
        question=EvaluationQuestion.NETWORK_COMPLETION,
        support=support, readiness=readiness,
        fidelity=ModelFidelity.NETWORK_PACKET_SIMULATION,
        qualification_profile="P" if readiness is BackendReadiness.READY
        else None,
        reason=reason, required_parents=("design",))


class _ScriptedAdapter:
    """Returns the given assessment for every question."""

    def __init__(self, backend_id: str, make_assessment):
        self._id = backend_id
        self._make = make_assessment

    @property
    def backend_id(self) -> str:
        return self._id

    def capabilities(self):
        return ()

    def assess(self, context, question):
        return self._make(question)

    def prepare(self, context, question):
        raise AssertionError("planner must not prepare")

    def execute(self, prepared, options):
        raise AssertionError("planner must not execute")


def _plan(adapter_list, question=EvaluationQuestion.NETWORK_COMPLETION,
          requested=None):
    registry = BackendRegistry(tuple(adapter_list))
    return EvaluationPlanner().plan(
        _Ctx(), (question,), registry, requested_backend=requested)


def test_plan_carries_context_identities():
    registry = BackendRegistry((_ScriptedAdapter(
        "BOOKSIM_STANDALONE", lambda q: _assessment()),))
    plan = EvaluationPlanner().plan(
        _Ctx(), (EvaluationQuestion.NETWORK_COMPLETION,), registry)
    assert plan.design_hash == "d" * 64
    assert plan.resolved_fabric_hash == "f" * 64
    assert len(plan.analyses) == 1


def test_ready_backend_is_selected():
    plan = _plan([_ScriptedAdapter("BOOKSIM_STANDALONE",
                                   lambda q: _assessment())])
    row = plan.ready(EvaluationQuestion.NETWORK_COMPLETION)
    assert row is not None
    assert row.backend_id == "BOOKSIM_STANDALONE"
    assert row.fidelity is ModelFidelity.NETWORK_PACKET_SIMULATION
    assert row.readiness is BackendReadiness.READY


def test_unsupported_is_dropped_but_unavailable_is_not():
    """A semantically-UNAVAILABLE row still names its backend: the
    capability exists, the executable is absent. UNSUPPORTED names none."""
    plan = _plan([_ScriptedAdapter(
        "BOOKSIM_STANDALONE",
        lambda q: _assessment(readiness=BackendReadiness.UNAVAILABLE,
                              reason="binary absent"))])
    row = plan.analyses[0]
    assert row.backend_id == "BOOKSIM_STANDALONE"
    assert row.readiness is BackendReadiness.UNAVAILABLE
    assert row.fidelity is None
    assert "absent" in row.reason

    plan = _plan([_ScriptedAdapter(
        "BOOKSIM_STANDALONE",
        lambda q: _assessment(support=SupportLevel.UNSUPPORTED,
                              readiness=BackendReadiness.BLOCKED,
                              reason="cannot represent"))])
    row = plan.analyses[0]
    assert row.backend_id is None
    assert row.support is SupportLevel.UNSUPPORTED
    assert "cannot represent" in row.reason


def test_installation_order_cannot_alter_selection():
    """THE determinism pin: preference law beats registration order."""
    def ready(backend):
        return _ScriptedAdapter(backend, lambda q: _assessment(backend=backend))

    first = _plan([ready("BOOKSIM_STANDALONE"), ready("OTHER_BACKEND")])
    swapped = _plan([ready("OTHER_BACKEND"), ready("BOOKSIM_STANDALONE")])
    chosen_first = first.analyses[0].backend_id
    chosen_swapped = swapped.analyses[0].backend_id
    assert chosen_first == chosen_swapped == "BOOKSIM_STANDALONE"


def test_requested_backend_wins_when_it_qualifies():
    def ready(backend):
        return _ScriptedAdapter(backend, lambda q: _assessment(backend=backend))

    plan = _plan([ready("BOOKSIM_STANDALONE"), ready("OTHER_BACKEND")],
                 requested="OTHER_BACKEND")
    assert plan.analyses[0].backend_id == "OTHER_BACKEND"


def test_requested_backend_that_does_not_qualify_is_ignored():
    """A requested backend that cannot represent must not silently win;
    the deterministic law still picks the qualifying one."""
    plan = _plan([
        _ScriptedAdapter("WEAK", lambda q: _assessment(
            support=SupportLevel.UNSUPPORTED,
            readiness=BackendReadiness.BLOCKED, reason="no")),
        _ScriptedAdapter("BOOKSIM_STANDALONE", lambda q: _assessment()),
    ], requested="WEAK")
    assert plan.analyses[0].backend_id == "BOOKSIM_STANDALONE"


def test_readiness_beats_preference():
    """A READY backend that is not first in preference beats a preferred
    UNAVAILABLE one: never silently downgrade an executable plan."""
    plan = _plan([
        _ScriptedAdapter("BOOKSIM_STANDALONE", lambda q: _assessment(
            readiness=BackendReadiness.UNAVAILABLE, reason="down")),
        _ScriptedAdapter("OTHER_BACKEND", lambda q: _assessment(
            backend="OTHER_BACKEND")),
    ])
    assert plan.analyses[0].backend_id == "OTHER_BACKEND"
    assert plan.analyses[0].readiness is BackendReadiness.READY


def test_empty_questions_refused_and_duplicates_refused():
    registry = BackendRegistry()
    with pytest.raises(EvaluationPlanError):
        EvaluationPlanner().plan(_Ctx(), (), registry)
    with pytest.raises(EvaluationPlanError, match="duplicate"):
        EvaluationPlanner().plan(
            _Ctx(),
            (EvaluationQuestion.NETWORK_COMPLETION,
             EvaluationQuestion.NETWORK_COMPLETION), registry)
    with pytest.raises(EvaluationPlanError, match="EvaluationQuestion"):
        EvaluationPlanner().plan(_Ctx(), ("NETWORK_COMPLETION",), registry)


def test_unready_row_carries_no_fidelity_claim():
    """Fidelity names WHAT KIND OF MODEL PRODUCED a result; a blocked row
    produced nothing and must not advertise one."""
    plan = _plan([_ScriptedAdapter(
        "BOOKSIM_STANDALONE",
        lambda q: _assessment(readiness=BackendReadiness.BLOCKED,
                              reason="semantics"))])
    row = plan.analyses[0]
    assert row.fidelity is None
    assert row.qualification_profile is None
