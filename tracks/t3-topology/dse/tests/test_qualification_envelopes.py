"""§13/§17: execution readiness must never imply numerical qualification.

A backend that executes successfully is not automatically a qualified
number. These tests pin the independent dimensions for each certified
backend and refuse a fabricated envelope for an unknown one.
"""
from __future__ import annotations

import sys
from pathlib import Path

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.application.qualification_envelopes import (  # noqa: E402
    DIAGNOSTIC_PROFILE_PREFIX, ESTABLISHED, LIMITED, NOT_ESTABLISHED,
    qualification_envelope,
)


def test_astra_is_not_numerically_established_absolute():
    env = qualification_envelope("ASTRA2_EMBEDDED_BOOKSIM")
    assert env is not None
    assert env["numerical_qualification"] == LIMITED
    assert "NOT_ESTABLISHED" in env["basis"]
    assert env["calibration"] == NOT_ESTABLISHED


def test_every_certified_backend_declares_calibration():
    for backend in ("BOOKSIM_STANDALONE", "ASTRA2_EMBEDDED_BOOKSIM",
                    "RAMULATOR2_HBM3_V1", "CANONICAL_SERVING"):
        env = qualification_envelope(backend)
        assert env is not None, backend
        assert env["numerical_qualification"] in (
            ESTABLISHED, LIMITED, "PARTIAL")
        assert env["calibration"] == NOT_ESTABLISHED, backend
        assert env["basis"]


def test_unknown_backend_has_no_fabricated_envelope():
    assert qualification_envelope(None) is None
    assert qualification_envelope("MADE_UP_BACKEND") is None


def test_certified_profile_keeps_the_certified_envelope():
    env = qualification_envelope(
        "RAMULATOR2_HBM3_V1",
        qualification_profile="CERTIFIED_RAMULATOR_HBM3_V1")
    assert env["numerical_qualification"] == ESTABLISHED
    assert "NOT inherited" not in env["basis"]


def test_diagnostic_profile_never_inherits_the_certified_envelope():
    """A DIAGNOSTIC profile (multi-pool Ramulator dispatch) is a model
    contract: the certified single-pool envelope is NOT its evidence."""
    env = qualification_envelope(
        "RAMULATOR2_HBM3_V1",
        qualification_profile="DIAGNOSTIC_MULTI_HBM_CALLBACK_DISPATCH_V1/"
                              "CERTIFIED_RAMULATOR_HBM3_V1")
    assert env["numerical_qualification"] == LIMITED
    assert env["calibration"] == NOT_ESTABLISHED
    assert "NOT inherited" in env["basis"]
    assert "DIAGNOSTIC_MULTI_HBM_CALLBACK_DISPATCH_V1" in env["basis"]


def test_the_diagnostic_profile_prefix_is_the_backend_spelling():
    """One concept, one spelling: the backend's diagnostic profile ids
    really do start with the marker the envelope switch reads."""
    from veritx_dse.backend.ramulator_adapter import (  # noqa: E402
        MULTI_HBM_DISPATCH_PROFILE,
    )
    assert MULTI_HBM_DISPATCH_PROFILE.startswith(
        DIAGNOSTIC_PROFILE_PREFIX)


def test_plan_view_shows_the_diagnostic_envelope_on_a_diagnostic_row():
    """The user-visible plan row must not advertise an ESTABLISHED
    single-channel envelope next to a DIAGNOSTIC profile."""
    from veritx_dse.application.evaluation_plan import (
        EvaluationPlan, PlannedAnalysis,
    )
    from veritx_dse.application.evaluation_plan_view import (
        evaluation_plan_view,
    )
    from veritx_dse.backend.adapter import (
        BackendReadiness, ModelFidelity, SupportLevel,
    )
    from veritx_dse.application.evaluation_question import EvaluationQuestion
    row = PlannedAnalysis(
        question=EvaluationQuestion.DRAM_TIMING,
        backend_id="RAMULATOR2_HBM3_V1", support=SupportLevel.SUPPORTED,
        readiness=BackendReadiness.READY,
        fidelity=ModelFidelity.MEMORY_CYCLE_SIMULATION,
        qualification_profile=(
            "DIAGNOSTIC_MULTI_HBM_CALLBACK_DISPATCH_V1/"
            "CERTIFIED_RAMULATOR_HBM3_V1"),
        reason=None, limitations=())
    view = evaluation_plan_view(
        EvaluationPlan(design_hash="ab" * 32,
                       resolved_fabric_hash="cd" * 32, analyses=(row,)),
        revision_id=None, design_hash="ab" * 32,
        resolved_fabric_hash="cd" * 32, workload_id="w")
    (analysis,) = view["analyses"]
    assert analysis["qualification_profile"].startswith("DIAGNOSTIC_")
    assert analysis["qualification"]["numerical_qualification"] == LIMITED
    assert "NOT inherited" in analysis["qualification"]["basis"]
    assert analysis["question"] == EvaluationQuestion.DRAM_TIMING.value
