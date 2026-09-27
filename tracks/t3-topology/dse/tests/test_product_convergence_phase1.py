"""PHASE 1 — optimization product authority (PRODUCT-CONVERGENCE-V1).

DEFECT: `ProductService._parse_definition` accepted `domain`, `objectives`,
`constraints`, `method`, `selection` and `seed`, and `_run_optimization`
then constructed `OptimizationDefinition(domain=…, objectives=…,
constraints=…, method=…)`. `selection`, `seed` and the whole budget were
parsed and DROPPED.

That was not cosmetic: `OptimizationStudyView._select` reads
`definition.selection`, so a caller asking for `selection="none"` silently
got `min_first_objective` selection instead.

These tests pin the whole chain the brief names:

    HTTP/Studio body -> ProductService -> persisted definition
      -> OptimizationDefinition -> OptimizationStudyView
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.optimization.definition import (  # noqa: E402
    SELECTION_POLICIES, Constraint, DomainParam, Objective,
    OptimizationDefinition,
)
from veritx_dse.product.service import ProductService  # noqa: E402


def _body(**kw):
    base = {
        "domain": [{"name": "link_width", "values": [32, 64, 128]}],
        "objectives": [{"metric": "completion_cycles", "direction": "MIN"}],
        "constraints": [{"metric": "completion_cycles", "op": "<=",
                         "threshold": 1e9}],
        "method": "random",
        "selection": "lexicographic",
        "seed": 4242,
        "budget": {"max_candidates": 3, "max_evaluations": 2},
    }
    base.update(kw)
    return base


def _to_definition(doc: dict) -> OptimizationDefinition:
    """The EXACT construction `_run_optimization` performs."""
    return OptimizationDefinition(
        domain=tuple(DomainParam(d["name"], tuple(d["values"]))
                     for d in doc["domain"]),
        objectives=tuple(Objective(o["metric"], o["direction"])
                         for o in doc["objectives"]),
        constraints=tuple(Constraint(c["metric"], c["op"], c["threshold"])
                          for c in doc["constraints"]),
        method=doc["method"],
        budget=doc["budget"],
        seed=doc["seed"],
        selection=doc["selection"])


# ══ the round trip the brief requires ══════════════════════════════════

def test_request_round_trips_into_the_definition_unchanged():
    """domain, method, selection, seed, budget, objectives, constraints."""
    doc = ProductService._parse_definition(_body())
    d = _to_definition(doc)
    assert d.method == "random"
    assert d.selection == "lexicographic"
    assert d.seed == 4242
    assert d.budget == {"max_candidates": 3, "max_evaluations": 2}
    # Domain values are put in CANONICAL order by the backend (sorted by
    # canonical JSON rendering), so declaration order never changes identity
    # or enumeration. For [32, 64, 128] that is lexicographic on the string
    # form, i.e. (128, 32, 64) — deterministic, and NOT numeric order.
    # PHASE 3 must therefore present canonical order, not the declared one.
    assert [(p.name, tuple(p.values)) for p in d.domain] == \
        [("link_width", (128, 32, 64))]
    assert d.domain[0].values == DomainParam("link_width",
                                             (32, 64, 128)).values
    assert [(o.metric, o.direction) for o in d.objectives] == \
        [("completion_cycles", "MIN")]
    assert [(c.metric, c.op) for c in d.constraints] == \
        [("completion_cycles", "<=")]


def test_selection_survives_and_changes_study_semantics():
    """The functional consequence: `selection` is read by `_select`."""
    for policy in SELECTION_POLICIES:
        doc = ProductService._parse_definition(_body(selection=policy))
        assert _to_definition(doc).selection == policy


def test_an_absent_selection_normalizes_to_the_backend_default():
    doc = ProductService._parse_definition(_body(selection=None))
    assert doc["selection"] == "min_first_objective"
    # ...and the pinned default is not invented here.
    assert OptimizationDefinition(
        domain=(DomainParam("link_width", (64,)),),
        objectives=(Objective("completion_cycles", "MIN"),),
    ).selection == "min_first_objective"


def test_seed_survives_for_random_and_is_not_invented_for_grid():
    assert _to_definition(
        ProductService._parse_definition(_body())).seed == 4242
    grid = ProductService._parse_definition(
        _body(method="grid", seed=None, selection=None))
    assert _to_definition(grid).seed is None


def test_budget_is_expressible_and_reaches_the_definition():
    """The budget was not expressible on the product API at all."""
    doc = ProductService._parse_definition(_body())
    assert doc["budget"] == {"max_candidates": 3, "max_evaluations": 2}
    assert _to_definition(doc).budget == {"max_candidates": 3,
                                          "max_evaluations": 2}


def test_absent_budget_is_exhaustive_not_a_silent_cap():
    doc = ProductService._parse_definition({
        "domain": [{"name": "link_width", "values": [64]}]})
    assert doc["budget"] == {}
    assert _to_definition(doc).budget == {}


# ══ no silently ignored field ═════════════════════════════════════════

def test_an_unknown_option_is_REFUSED_not_dropped():
    with pytest.raises(Exception, match="unknown optimization option"):
        ProductService._parse_definition(_body(frobnicate=1))


def test_a_misspelled_known_option_is_REFUSED():
    """`seeds` is not `seed`. It must refuse, not be silently ignored."""
    body = _body()
    body["seeds"] = 7
    with pytest.raises(Exception, match="unknown optimization option"):
        ProductService._parse_definition(body)


def test_every_accepted_key_is_propagated():
    """The keys the parser accepts and the keys the definition consumes must
    be the same set — that equality IS the no-drop guarantee."""
    import inspect
    src = inspect.getsource(ProductService._parse_definition)
    returned = src[src.index("return {"):]
    for key in ProductService._OPTIMIZATION_KEYS:
        assert f'"{key}"' in returned, (
            f"option {key!r} is accepted but never returned — it would be "
            "silently dropped")


# ══ fail-closed on invalid values ═════════════════════════════════════

def test_backend_refuses_an_unsupported_method_through_the_product_parser():
    doc = ProductService._parse_definition(_body(method="bayes"))
    with pytest.raises(Exception, match="refused"):
        _to_definition(doc)


def test_backend_refuses_a_bad_budget_through_the_product_parser():
    doc = ProductService._parse_definition(
        _body(budget={"max_candidates": 0}))
    with pytest.raises(Exception, match="positive int"):
        _to_definition(doc)


def test_a_non_object_budget_is_refused():
    with pytest.raises(Exception, match="budget must be an object"):
        ProductService._parse_definition(_body(budget=[3]))
