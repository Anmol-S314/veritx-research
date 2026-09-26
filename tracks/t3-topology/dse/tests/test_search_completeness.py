"""Search completeness tests (SEARCH-1..SEARCH-6).

AMEND-4: `search.py::search_candidates` truncates with `cands[:limit]` and
kept no completeness fact, so an exhaustive search and a budgeted one were
indistinguishable. These tests prove the restored law.

INVARIANTS UNDER TEST
  1 truncation is identity/evidence-visible
  2 EXHAUSTIVE is never inferred
  3 non-evaluated candidates remain represented
  4 Pareto uses only eligible evaluated candidates (unchanged)
  5 requirement violation stays separate from Pareto eligibility (unchanged)
  6 generated objective != evaluated metric (unchanged)
  7 a synthesis engine cannot manufacture a certificate or evidence
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.optimization.completeness import (
    CompletenessError,
    SearchCompleteness,
    derive,
)
from veritx_dse.optimization.definition import (
    DomainParam,
    Objective,
    OptimizationDefinition,
)


def _defn(values, *, budget=None, method="grid"):
    kw = dict(
        domain=(DomainParam("link_width", tuple(values)),),
        objectives=(Objective(metric="completion_cycles", direction="MIN"),),
        method=method,
        budget=budget or {},
    )
    if method == "random":
        kw["seed"] = 7
    return OptimizationDefinition(**kw)


# ── SEARCH-1: finite exhaustive space reports complete ──────────────────

def test_search_1_exhaustive_is_complete():
    c = derive(_defn([32, 64, 128]), evaluated_count=3)
    assert c.completeness == "EXHAUSTIVE"
    assert c.universe_size == 3
    assert c.not_evaluated_count == 0
    assert c.is_complete
    assert c.may_claim_optimality()
    assert c.claim() == "complete over this declared finite design space"


def test_search_1b_multi_dimension_cardinality():
    d = OptimizationDefinition(
        domain=(DomainParam("link_width", (32, 64)),
                DomainParam("concentration", (1, 2, 4))),
        objectives=(Objective(metric="completion_cycles", direction="MIN"),),
    )
    c = derive(d, evaluated_count=6)
    assert c.universe_size == 6
    assert c.completeness == "EXHAUSTIVE"


# ── SEARCH-2: limit < universe reports incomplete ───────────────────────

def test_search_2_budgeted_is_incomplete():
    c = derive(_defn([32, 64, 128, 256], budget={"max_candidates": 2}),
               evaluated_count=2)
    assert c.completeness == "BUDGETED"
    assert c.universe_size == 4
    assert c.budget == 2
    assert c.not_evaluated_count == 2
    assert not c.is_complete
    assert not c.may_claim_optimality(), \
        "a budgeted search must NEVER be able to claim optimality"


def test_search_2b_budgeted_claim_text_is_honest():
    c = derive(_defn([32, 64, 128, 256], budget={"max_candidates": 2}),
               evaluated_count=2)
    assert c.claim() == "best observed among evaluated candidates"
    assert "complete" not in c.claim()


def test_search_2c_budget_equal_to_universe_is_still_exhaustive():
    """A budget that does not actually truncate does not make the search
    incomplete — completeness follows the evaluated set, not the presence
    of a budget key."""
    c = derive(_defn([32, 64], budget={"max_candidates": 2}),
               evaluated_count=2)
    assert c.completeness == "EXHAUSTIVE"


# ── SEARCH-3: not-evaluated count is visible ────────────────────────────

def test_search_3_not_evaluated_is_visible():
    c = derive(_defn(list(range(10)), budget={"max_candidates": 3}),
               evaluated_count=3)
    assert c.not_evaluated_count == 7
    d = c.to_dict()
    assert d["not_evaluated_count"] == 7
    assert d["completeness"] == "BUDGETED"
    assert d["may_claim_optimality"] is False


def test_search_3b_absence_does_not_look_like_nonexistence():
    """INVARIANT 3: the excluded candidates are accounted for, not dropped."""
    c = derive(_defn(list(range(10)), budget={"max_candidates": 3}),
               evaluated_count=3)
    assert c.evaluated_count + c.not_evaluated_count == c.universe_size


# ── SEARCH-4: incomplete search cannot imply a global optimum ───────────

def test_search_4_optimality_requires_exhaustive():
    budgeted = derive(_defn(list(range(8)), budget={"max_candidates": 4}),
                      evaluated_count=4)
    exhaustive = derive(_defn(list(range(8))), evaluated_count=8)
    assert not budgeted.may_claim_optimality()
    assert exhaustive.may_claim_optimality()


def test_search_4b_exhaustive_cannot_be_claimed_while_incomplete():
    """INVARIANT 2: EXHAUSTIVE is never inferred."""
    with pytest.raises(CompletenessError):
        SearchCompleteness(
            method="grid", universe_size=10, universe_known=True,
            budget=3, evaluated_count=3, not_evaluated_count=7,
            completeness="EXHAUSTIVE")
    with pytest.raises(CompletenessError):
        SearchCompleteness(
            method="random", universe_size=None, universe_known=False,
            budget=None, evaluated_count=5, not_evaluated_count=None,
            completeness="EXHAUSTIVE")


def test_search_4c_unbounded_space_carries_no_size():
    """A seeded subsample cannot bound its own space, so it must not
    fabricate a universe size."""
    c = derive(_defn([1, 2, 3, 4], method="random"), evaluated_count=4)
    assert c.completeness == "UNBOUNDED"
    assert c.universe_known is False
    assert c.universe_size is None
    assert c.not_evaluated_count is None
    assert not c.may_claim_optimality()


# ── SEARCH-5: completeness survives persistence / reopen ────────────────

def test_search_5_completeness_round_trips():
    c = derive(_defn(list(range(10)), budget={"max_candidates": 3}),
               evaluated_count=3)
    back = SearchCompleteness.from_dict(c.to_dict())
    assert back == c
    assert back.completeness == "BUDGETED"
    assert back.not_evaluated_count == 7


def test_search_5b_strict_schema_rejects_unknown_fields():
    c = derive(_defn([32, 64]), evaluated_count=2).to_dict()
    c["surprise"] = 1
    with pytest.raises(CompletenessError):
        SearchCompleteness.from_dict(c)


# ── SEARCH-6: tampered completeness refuses ─────────────────────────────

def test_search_6_tampered_completeness_refuses():
    """Flipping a budgeted search to EXHAUSTIVE on reopen must refuse."""
    c = derive(_defn(list(range(10)), budget={"max_candidates": 3}),
               evaluated_count=3).to_dict()
    c["completeness"] = "EXHAUSTIVE"
    with pytest.raises(CompletenessError):
        SearchCompleteness.from_dict(c)


def test_search_6b_inconsistent_counts_refuse():
    with pytest.raises(CompletenessError):
        SearchCompleteness(
            method="grid", universe_size=10, universe_known=True,
            budget=3, evaluated_count=3, not_evaluated_count=99,
            completeness="BUDGETED")
    with pytest.raises(CompletenessError):
        SearchCompleteness(
            method="grid", universe_size=2, universe_known=True,
            budget=None, evaluated_count=5, not_evaluated_count=0,
            completeness="BUDGETED")


def test_search_6c_overproduction_refuses():
    with pytest.raises(CompletenessError):
        derive(_defn([32, 64]), evaluated_count=5)


# ── identity: completeness is part of the result identity ───────────────

def test_completeness_is_identity_bearing():
    """A budgeted result and an exhaustive result over the SAME space must
    not share a result id — otherwise a truncated study could be presented
    as complete."""
    from veritx_dse.optimization.result import OptimizationResult
    from veritx_dse.optimization.definition import Objective

    d_small = _defn([32, 64], budget={"max_candidates": 1})
    d_full = _defn([32, 64])
    common = dict(base_design_hash="h", records=(), pareto_ids=(),
                  selected_candidate_id=None, selection_rationale=None)
    a = OptimizationResult(definition=d_small,
                           completeness=derive(d_small, 1), **common)
    b = OptimizationResult(definition=d_full,
                           completeness=derive(d_full, 2), **common)
    assert a.completeness.completeness == "BUDGETED"
    assert b.completeness.completeness == "EXHAUSTIVE"
    assert a.result_id() != b.result_id()
