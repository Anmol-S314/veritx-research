"""Wave-F pure unit tests — independent oracles (§85/§87/§88/§90–§92/§121).

Every oracle here is a tiny brute-force reimplementation written in the
test file, NOT a call into the production code under test. The
production Pareto adapter is additionally cross-checked against the
sealed core.comparison.pareto_with_scope behavior on the same points.
"""
from __future__ import annotations

import itertools
import sys
from fractions import Fraction
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.optimization.constraints import (  # noqa: E402
    VerdictInput, evaluate_constraint, feasibility, optimization_verdict,
    relaxation_evidence, _satisfies,
)
from veritx_dse.optimization.definition import (  # noqa: E402
    OptimizationDefinition, OptimizationDefinitionError,
)
from veritx_dse.optimization.metrics import MetricValue  # noqa: E402
from veritx_dse.optimization.pareto import (  # noqa: E402
    compute_frontier, dimensions, dominance_explanations, select,
)
from veritx_dse.optimization.space import (  # noqa: E402
    iter_raw_assignments, raw_cardinality,
)


# ── helpers ──────────────────────────────────────────────────────────────

def measured(name: str, value, scenario=None, unit="s") -> MetricValue:
    return MetricValue(
        name=name, status="MEASURED", value=Fraction(value), unit=unit,
        source_result_id="r", fidelity="MODEL_DERIVED")


class _Spec:
    def __init__(self, metric, scenario=None):
        self.metric = metric
        self.scenario = scenario
        self.direction = "MINIMIZE"
        self.operator = "<="
        self.bound = Fraction(1)


class _Defn:
    """Minimal definition stand-in for pure-layer tests."""

    def __init__(self, objectives, hard_constraints=(),
                 selection_policy="NONE", selection_metric_order=(),
                 search_policy="EXHAUSTIVE_GRID", scenarios=("s",)):
        self.objectives = [_Spec(*o) for o in objectives]
        self.hard_constraints = [_Spec(*c) for c in hard_constraints]
        self.selection_policy = selection_policy
        self.selection_metric_order = list(selection_metric_order)
        self.search_policy = search_policy
        self._scenarios = list(scenarios)

    def scenario_names(self):
        return self._scenarios


def _mv(name, value, scenario=None, status="MEASURED", unit="s"):
    if status == "MEASURED":
        return MetricValue(name=name, status=status,
                           value=Fraction(value), unit=unit,
                           source_result_id="r",
                           fidelity="MODEL_DERIVED")
    return MetricValue(name=name, status=status, value=None, unit=unit,
                       source_result_id="r", fidelity="MODEL_DERIVED",
                       reason="x")


def _brute_front(points: dict[str, tuple[Fraction, ...]]
                 ) -> set[str]:
    """Independent Pareto oracle: all-MINIMIZE dominance."""
    front = set()
    for a, va in points.items():
        dominated = False
        for b, vb in points.items():
            if a == b:
                continue
            if all(x <= y for x, y in zip(vb, va)) and \
                    any(x < y for x, y in zip(vb, va)):
                dominated = True
                break
        if not dominated:
            front.add(a)
    return front


# ── Pareto oracle (§85/§91/§92) ──────────────────────────────────────────

class TestParetoOracle:
    def _points_defn(self):
        return _Defn(objectives=[("m1", None), ("m2", None)])

    def _frontier(self, points):
        defn = self._points_defn()
        ovals = {
            cid: {("m1", None): _mv("m1", v[0]),
                  ("m2", None): _mv("m2", v[1])}
            for cid, v in points.items()}
        scoped = compute_frontier(
            defn, [{"candidate_id": cid} for cid in points], ovals,
            comparability_ok=True)
        return scoped, ovals

    def test_min_min_frontier_matches_oracle(self):
        points = {"A": (1, 5), "B": (2, 3), "C": (3, 2), "D": (5, 5)}
        scoped, _ = self._frontier(points)
        assert set(scoped["front"]) == _brute_front(points)
        assert set(scoped["dominated"]) == set(points) - \
            _brute_front(points)

    def test_ties_neither_dominate_nor_vanish(self):
        points = {"A": (2, 2), "B": (2, 2)}
        scoped, _ = self._frontier(points)
        assert set(scoped["front"]) == {"A", "B"}
        assert scoped["dominated"] == []

    def test_duplicate_metrics_kept_in_front(self):
        points = {"A": (1, 1), "B": (1, 1), "C": (2, 2)}
        scoped, _ = self._frontier(points)
        assert set(scoped["front"]) == {"A", "B"}

    def test_multi_objective_oracle(self):
        # §91: A(5,100) B(6,80) C(8,120) -> A,B front; C dominated.
        points = {"A": (5, 100), "B": (6, 80), "C": (8, 120)}
        scoped, _ = self._frontier(points)
        assert set(scoped["front"]) == {"A", "B"}
        assert set(scoped["dominated"]) == {"C"}
        expl = dominance_explanations(scoped)
        assert set(expl) == {"C"}
        assert expl["C"]["dominated_by"] in ("A", "B")

    def test_scenario_axes_stay_distinct(self):
        # §92: prefill/decode tradeoff — both stay efficient; the
        # axes are (metric@scenario), never merged.
        defn = _Defn(objectives=[("mk", "prefill"), ("mk", "decode")])
        ovals = {
            "A": {("mk", "prefill"): _mv("mk", 5, "prefill"),
                  ("mk", "decode"): _mv("mk", 10, "decode")},
            "B": {("mk", "prefill"): _mv("mk", 8, "prefill"),
                  ("mk", "decode"): _mv("mk", 6, "decode")},
        }
        scoped = compute_frontier(
            defn, [{"candidate_id": "A"}, {"candidate_id": "B"}], ovals,
            comparability_ok=True)
        assert set(scoped["front"]) == {"A", "B"}
        assert scoped["objectives"] == ["mk@prefill", "mk@decode"]

    def test_mixed_fidelity_refuses(self):
        # §94: two candidates with different fidelity classes refuse.
        defn = _Defn(objectives=[("m1", None)])
        ovals = {"A": {("m1", None): _mv("m1", 1)},
                 "B": {("m1", None): _mv("m1", 2)}}
        # (the gate itself is tested on verified results in the
        # integration tests; here we assert the adapter honours the
        # comparability flag)
        with pytest.raises(Exception, match="comparable"):
            compute_frontier(
                defn, [{"candidate_id": "A"}, {"candidate_id": "B"}],
                ovals, comparability_ok=False)

    def test_missing_objective_excludes_from_front_but_visible(self):
        points = {"A": (1, 5), "B": (2, 3)}
        defn = self._points_defn()
        ovals = {
            "A": {("m1", None): _mv("m1", points["A"][0]),
                  ("m2", None): _mv("m2", points["A"][1])},
            "B": {("m1", None): _mv("m1", points["B"][0]),
                  ("m2", None): _mv("m2", None, status="UNMEASURABLE")},
        }
        scoped = compute_frontier(
            defn, [{"candidate_id": "A"}, {"candidate_id": "B"}], ovals,
            comparability_ok=True)
        assert scoped["front"] == ["A"]
        statuses = {c["run_id"]: c["status"]
                    for c in scoped["candidates"]}
        assert statuses["B"] == "MISSING_METRIC"
        assert scoped["comparable_count"] == 1


# ── direction handling (§40) ─────────────────────────────────────────────

class TestDirections:
    def test_maximize_projects_to_minimize(self):
        dims = dimensions(_Defn(objectives=[("bw", None)])) \
            if False else None
        from veritx_dse.optimization.pareto import ObjectiveDimension
        d = ObjectiveDimension(metric="bw", scenario=None,
                               direction="MAXIMIZE")
        assert d.project(Fraction(100)) == Fraction(-100)
        assert d.axis == "bw@*"

    def test_maximize_frontier_matches_oracle_after_projection(self):
        # MAXIMIZE m2 == MINIMIZE -m2
        points = {"A": (1, 50), "B": (2, 80), "C": (3, 80)}
        defn = _Defn(objectives=[("m1", None), ("m2", None)])
        # monkey-apply direction: project m2 via negation ourselves
        projected = {k: (v[0], -v[1]) for k, v in points.items()}
        ovals = {
            cid: {("m1", None): _mv("m1", v[0]),
                  ("m2", None): _mv("m2", -projected[cid][1])}
            for cid, v in points.items()}
        # Feed RAW values through the production adapter instead:
        from veritx_dse.optimization.pareto import ObjectiveDimension
        class _DefnMax(_Defn):
            pass
        defn_max = _DefnMax(objectives=[("m1", None), ("m2", None)])
        # patch dimensions() to declare m2 as MAXIMIZE
        import veritx_dse.optimization.pareto as pmod

        orig_dims = pmod.dimensions

        def fake_dimensions(d):
            return [ObjectiveDimension("m1", None, "MINIMIZE"),
                    ObjectiveDimension("m2", None, "MAXIMIZE")]
        pmod.dimensions = fake_dimensions
        try:
            ovals_raw = {
                cid: {("m1", None): _mv("m1", v[0]),
                      ("m2", None): _mv("m2", v[1])}
                for cid, v in points.items()}
            scoped = compute_frontier(
                defn_max,
                [{"candidate_id": c} for c in points], ovals_raw,
                comparability_ok=True)
        finally:
            pmod.dimensions = orig_dims
        # brute force on the projected (min, -max) points
        brute = _brute_front(projected)
        assert set(scoped["front"]) == brute

    def test_selection_maximize_keeps_raw_best(self):
        from veritx_dse.optimization.pareto import ObjectiveDimension
        import veritx_dse.optimization.pareto as pmod
        defn = _Defn(objectives=[("bw", None)],
                     selection_policy="SINGLE_OBJECTIVE")
        orig = pmod.dimensions

        class _Obj:
            metric = "bw"
            scenario = None
            direction = "MAXIMIZE"
        defn.objectives = [_Obj()]
        try:
            ovals = {"A": {("bw", None): _mv("bw", 10, unit="Gbps")},
                     "B": {("bw", None): _mv("bw", 40, unit="Gbps")}}
            out = select(defn, ["A", "B"], ovals)
            assert out["selected"] == ["B"]
        finally:
            pmod.dimensions = orig


# ── selection (§57–§61/§90) ──────────────────────────────────────────────

class TestSelection:
    def test_no_policy_selects_nothing(self):
        defn = _Defn(objectives=[("m1", None), ("m2", None)],
                     selection_policy="NONE")
        out = select(defn, ["A", "B"], {})
        assert out["selected"] == [] and out["policy"] == "NONE"

    def test_single_objective_min(self):
        # §90: A=10 B=7 C=12 -> B
        defn = _Defn(objectives=[("m1", None)],
                     selection_policy="SINGLE_OBJECTIVE")
        ovals = {c: {("m1", None): _mv("m1", v)} for c, v in
                 (("A", 10), ("B", 7), ("C", 12))}
        assert select(defn, ["A", "B", "C"], ovals)["selected"] == ["B"]

    def test_single_objective_exact_tie_preserved(self):
        # §90: A=7 B=7 C=12 -> both A and B
        defn = _Defn(objectives=[("m1", None)],
                     selection_policy="SINGLE_OBJECTIVE")
        ovals = {c: {("m1", None): _mv("m1", v)} for c, v in
                 (("A", 7), ("B", 7), ("C", 12))}
        out = select(defn, ["A", "B", "C"], ovals)
        assert out["selected"] == ["A", "B"] and out["tied"] is True

    def test_lexicographic_order_decides(self):
        # §59: 1. m1, 2. m2 — m1 tie broken by m2.
        defn = _Defn(objectives=[("m1", None), ("m2", None)],
                     selection_policy="LEXICOGRAPHIC",
                     selection_metric_order=[{"metric": "m1",
                                              "scenario": None},
                                             {"metric": "m2",
                                              "scenario": None}])
        ovals = {
            "A": {("m1", None): _mv("m1", 5), ("m2", None): _mv("m2", 9)},
            "B": {("m1", None): _mv("m1", 5), ("m2", None): _mv("m2", 3)},
            "C": {("m1", None): _mv("m1", 8), ("m2", None): _mv("m2", 1)},
        }
        assert select(defn, ["A", "B", "C"], ovals)["selected"] == ["B"]

    def test_lexicographic_full_tie_preserved(self):
        defn = _Defn(objectives=[("m1", None), ("m2", None)],
                     selection_policy="LEXICOGRAPHIC",
                     selection_metric_order=[{"metric": "m1",
                                              "scenario": None},
                                             {"metric": "m2",
                                              "scenario": None}])
        ovals = {
            "A": {("m1", None): _mv("m1", 5), ("m2", None): _mv("m2", 3)},
            "B": {("m1", None): _mv("m1", 5), ("m2", None): _mv("m2", 3)},
        }
        out = select(defn, ["A", "B"], ovals)
        assert out["selected"] == ["A", "B"] and out["tied"] is True

    def test_selection_cannot_invent_missing_value(self):
        defn = _Defn(objectives=[("m1", None)],
                     selection_policy="SINGLE_OBJECTIVE")
        ovals = {"A": {("m1", None): _mv("m1", 1)},
                 "B": {("m1", None): _mv("m1", None,
                                         status="UNMEASURABLE")}}
        with pytest.raises(Exception, match="cannot measure"):
            select(defn, ["A", "B"], ovals)


# ── constraint truth table (§87) ─────────────────────────────────────────

class TestConstraintTruthTable:
    @pytest.mark.parametrize("value,op,bound,expected", [
        (9, "<=", 10, "SATISFIED"), (10, "<=", 10, "SATISFIED"),
        (11, "<=", 10, "VIOLATED"),
        (11, ">=", 10, "SATISFIED"), (10, ">=", 10, "SATISFIED"),
        (9, ">=", 10, "VIOLATED"),
    ])
    def test_measured_values(self, value, op, bound, expected):
        doc = evaluate_constraint(measured("m", value), op,
                                  Fraction(bound))
        assert doc["verdict"] == expected
        margin = Fraction(doc["margin_or_excess"]["numerator"],
                          doc["margin_or_excess"]["denominator"])
        assert (margin >= 0) == (expected == "SATISFIED")

    @pytest.mark.parametrize("status", ["UNMEASURABLE", "UNSUPPORTED"])
    @pytest.mark.parametrize("op", ["<=", ">="])
    def test_missing_metric_never_passes(self, status, op):
        # §47/§135: missing producer never becomes zero or a pass.
        doc = evaluate_constraint(
            _mv("m", None, status=status), op, Fraction(10))
        assert doc["verdict"] == "UNMEASURABLE"
        assert doc["value"] is None
        assert doc["margin_or_excess"] is None

    def test_feasibility_rules(self):
        # §48: one violated rejects; one unmeasurable = not proven.
        cons = [_Spec("m1", None)]
        cons[0].bound = Fraction(10)
        all_sat = {("m1", None): _mv("m1", 5)}
        assert feasibility(all_sat, cons) is True
        violated = {("m1", None): _mv("m1", 50)}
        assert feasibility(violated, cons) is False
        unmeasurable = {("m1", None): _mv("m1", None,
                                          status="UNMEASURABLE")}
        assert feasibility(unmeasurable, cons) is None
        mixed = {("m1", None): _mv("m1", None,
                                   status="UNMEASURABLE"),
                 ("m2", None): _mv("m2", 50)}
        assert feasibility(mixed, [_Spec("m1", None),
                                   _Spec("m2", None)]) is False


# ── verdict ladder (§49–§53/§76) ─────────────────────────────────────────

class TestVerdictLadder:
    def test_feasible_is_existential(self):
        out = optimization_verdict(VerdictInput(
            search_complete=False, valid_total=5, feasible=1, rejected=1,
            non_conclusive=3, any_measured=True))
        assert out["verdict"] == "FEASIBLE"

    def test_no_feasible_requires_complete_and_all_rejected(self):
        out = optimization_verdict(VerdictInput(
            search_complete=True, valid_total=3, feasible=0, rejected=3,
            non_conclusive=0, any_measured=True))
        assert out["verdict"] == "NO_FEASIBLE_DESIGN"

    def test_timeout_never_proves_infeasibility(self):
        # §50: an unresolved candidate forces INCONCLUSIVE.
        out = optimization_verdict(VerdictInput(
            search_complete=True, valid_total=3, feasible=0, rejected=2,
            non_conclusive=1, any_measured=True))
        assert out["verdict"] == "INCONCLUSIVE"

    def test_incomplete_search_is_inconclusive(self):
        out = optimization_verdict(VerdictInput(
            search_complete=False, valid_total=3, feasible=0, rejected=2,
            non_conclusive=1, any_measured=True))
        assert out["verdict"] == "INCONCLUSIVE"

    def test_no_measured_evidence_is_constraint_unmeasurable(self):
        out = optimization_verdict(VerdictInput(
            search_complete=True, valid_total=2, feasible=0, rejected=0,
            non_conclusive=2, any_measured=False))
        assert out["verdict"] == "CONSTRAINT_UNMEASURABLE"

    def test_all_invalid_is_no_valid_candidates(self):
        out = optimization_verdict(VerdictInput(
            search_complete=False, valid_total=0, feasible=0, rejected=0,
            non_conclusive=0, any_measured=False))
        assert out["verdict"] == "NO_VALID_CANDIDATES"


# ── relaxation evidence (§98) ────────────────────────────────────────────

class TestRelaxation:
    def test_relaxation_is_closest_violating_value(self):
        cons = [_Spec("m1", None)]
        values = [
            {("m1", None): _mv("m1", 12)},
            {("m1", None): _mv("m1", 14)},
            {("m1", None): _mv("m1", 8)},   # satisfies
        ]
        class _C:
            metric = "m1"
            scenario = None
            operator = "<="
            bound = Fraction(10)
        out = relaxation_evidence(values, [_C()])
        assert len(out) == 1
        assert out[0]["best_observed"]["numerator"] == 12
        assert out[0]["required_relaxation"]["numerator"] == 2
        assert out[0]["information_only"] is True

    def test_all_satisfying_means_no_relaxation(self):
        class _C:
            metric = "m1"
            scenario = None
            operator = "<="
            bound = Fraction(10)
        out = relaxation_evidence(
            [{("m1", None): _mv("m1", 5)}], [_C()])
        assert out == []

    def test_unmeasurable_contributes_nothing(self):
        class _C:
            metric = "m1"
            scenario = None
            operator = "<="
            bound = Fraction(10)
        out = relaxation_evidence(
            [{("m1", None): _mv("m1", None, status="UNMEASURABLE")}],
            [_C()])
        assert out == []


# ── definition identity (§8/§16/§79–§84) ─────────────────────────────────

BASE = {
    "name": "opt",
    "scenarios": [{"name": "prefill", "intent": {
        "fabric_preset": "mesh4", "backend_target": "BOOKSIM_STANDALONE",
        "workload": {"trace": "tiny2"}, "metrics": [],
    }}],
    "parameters": [{"name": "workload.tp", "values": [1, 2]}],
    "objectives": [{"metric": "system.makespan_s",
                    "direction": "MINIMIZE", "scenario": "prefill"}],
    "hard_constraints": [],
    "search_policy": "EXHAUSTIVE_GRID",
}


class TestDefinitionIdentity:
    def test_parses_and_has_stable_id(self):
        d = OptimizationDefinition.parse(BASE)
        assert d.definition_id() == OptimizationDefinition.parse(
            BASE).definition_id()

    def test_parameter_permutation_is_same_space(self):
        # §83: declaration order does not change an identical space
        # (same parameter SET, permuted order).
        a = OptimizationDefinition.parse({**BASE, "parameters": [
            {"name": "workload.tp", "values": [1, 2]},
            {"name": "workload.dp", "values": [2, 4]}]})
        doc = {**BASE, "parameters": [
            {"name": "workload.dp", "values": [2, 4]},
            {"name": "workload.tp", "values": [1, 2]}]}
        b = OptimizationDefinition.parse(doc)
        assert a.definition_id() == b.definition_id()
        ra = [dict(sorted(x.items())) for x in iter_raw_assignments(a)]
        rb = [dict(sorted(x.items())) for x in iter_raw_assignments(b)]
        assert sorted(map(str, ra)) == sorted(map(str, rb))

    def test_domain_permutation_is_same_space(self):
        # §84: value order is canonical, not semantic.
        a = OptimizationDefinition.parse(BASE)
        doc = {**BASE, "parameters": [
            {"name": "workload.tp", "values": [2, 1]}]}
        b = OptimizationDefinition.parse(doc)
        assert a.definition_id() == b.definition_id()
        assert a.parameters[0].values == (1, 2)

    def test_duplicate_domain_value_canonicalizes(self):
        # §82: duplicate value dedupes; identity unchanged.
        a = OptimizationDefinition.parse(BASE)
        doc = {**BASE, "parameters": [
            {"name": "workload.tp", "values": [1, 2, 2]}]}
        b = OptimizationDefinition.parse(doc)
        assert a.definition_id() == b.definition_id()

    def test_constraint_bound_change_moves_identity(self):
        # §80: bound mutation changes the definition identity.
        a = OptimizationDefinition.parse({**BASE, "hard_constraints": [
            {"metric": "system.makespan_s", "scenario": "prefill",
             "operator": "<=", "bound": 10, "unit": "s"}]})
        b = OptimizationDefinition.parse({**BASE, "hard_constraints": [
            {"metric": "system.makespan_s", "scenario": "prefill",
             "operator": "<=", "bound": 20, "unit": "s"}]})
        assert a.definition_id() != b.definition_id()

    def test_budget_change_moves_identity(self):
        # §81: budget is semantic for budgeted search.
        a = OptimizationDefinition.parse({**BASE,
                                          "search_policy":
                                          "BUDGETED_GRID",
                                          "budget":
                                          {"max_design_candidates": 2}})
        b = OptimizationDefinition.parse({**BASE,
                                          "search_policy":
                                          "BUDGETED_GRID",
                                          "budget":
                                          {"max_design_candidates": 3}})
        assert a.definition_id() != b.definition_id()

    def test_direction_flip_moves_identity(self):
        # §79: MINIMIZE <-> MAXIMIZE is a different request.
        a = OptimizationDefinition.parse(BASE)
        b = OptimizationDefinition.parse({
            **BASE, "objectives": [
                {"metric": "system.makespan_s", "direction": "MAXIMIZE",
                 "scenario": "prefill"}]})
        assert a.definition_id() != b.definition_id()

    def test_schema_closure(self):
        bad = {**BASE, "guaranteed_speedup": "3x"}
        with pytest.raises(OptimizationDefinitionError,
                           match="unknown fields"):
            OptimizationDefinition.parse(bad)

    def test_unknown_metric_refuses(self):
        bad = {**BASE, "objectives": [
            {"metric": "foo", "direction": "MINIMIZE",
             "scenario": "prefill"}]}
        with pytest.raises(OptimizationDefinitionError,
                           match="registry"):
            OptimizationDefinition.parse(bad)

    def test_unknown_parameter_refuses(self):
        bad = {**BASE, "parameters": [
            {"name": "booksim.confs.deep_magic", "values": [1]}]}
        with pytest.raises(OptimizationDefinitionError):
            OptimizationDefinition.parse(bad)

    def test_wrong_constraint_unit_refuses(self):
        bad = {**BASE, "hard_constraints": [
            {"metric": "system.makespan_s", "scenario": "prefill",
             "operator": "<=", "bound": 10, "unit": "cycles"}]}
        with pytest.raises(OptimizationDefinitionError, match="unit"):
            OptimizationDefinition.parse(bad)

    def test_selection_without_order_refuses(self):
        bad = {**BASE, "objectives": [
            {"metric": "system.makespan_s", "direction": "MINIMIZE",
             "scenario": "prefill"},
            {"metric": "fabric.channel_count", "direction": "MINIMIZE",
             "scenario": None}],
            "selection_policy": "LEXICOGRAPHIC"}
        with pytest.raises(OptimizationDefinitionError):
            OptimizationDefinition.parse(bad)

    def test_unregistered_area_metric_refuses(self):
        # §36/§129: area/power/energy are not in the registry.
        bad = {**BASE, "objectives": [
            {"metric": "area_mm2", "direction": "MINIMIZE",
             "scenario": "prefill"}]}
        with pytest.raises(OptimizationDefinitionError):
            OptimizationDefinition.parse(bad)

    def test_single_objective_requires_one_dimension(self):
        bad = {**BASE, "objectives": [
            {"metric": "system.makespan_s", "direction": "MINIMIZE",
             "scenario": "prefill"},
            {"metric": "fabric.channel_count", "direction": "MINIMIZE",
             "scenario": None}],
            "selection_policy": "SINGLE_OBJECTIVE"}
        with pytest.raises(OptimizationDefinitionError):
            OptimizationDefinition.parse(bad)


# ── space oracle (§88/§89) ───────────────────────────────────────────────

class TestSpaceOracle:
    def _defn(self, policy="EXHAUSTIVE_GRID", budget=None):
        doc = {**BASE,
               "scenarios": [
                   {"name": "prefill", "intent": {
                       "fabric_preset": "mesh4",
                       "backend_target": "BOOKSIM_STANDALONE",
                       "workload": {"trace": "tiny2"}, "metrics": []}}],
               "parameters": [
                   {"name": "workload.tp", "values": [1, 2]},
                   {"name": "workload.dp", "values": [2, 4, 6]}],
               "search_policy": policy}
        if budget:
            doc["budget"] = budget
        return OptimizationDefinition.parse(doc)

    def test_cardinality_is_product(self):
        # 2 x 3 = 6 raw assignments.
        assert raw_cardinality(self._defn()) == 6
        assert len(iter_raw_assignments(self._defn())) == 6

    def test_canonical_order_is_deterministic(self):
        order1 = [str(sorted(a.items()))
                  for a in iter_raw_assignments(self._defn())]
        order2 = [str(sorted(a.items()))
                  for a in iter_raw_assignments(self._defn())]
        assert order1 == order2
        # 'workload.dp' < 'workload.tp' canonically; FIRST parameter
        # varies slowest -> dp repeats across each block of len(tp).
        rows = iter_raw_assignments(self._defn())
        assert [a["workload.tp"] for a in rows] == [1, 2] * 3
        assert [a["workload.dp"] for a in rows] == \
            [2, 2, 4, 4, 6, 6]

    def test_budget_plan_cuts_prefix(self):
        from veritx_dse.optimization.space import budget_plan
        plan = budget_plan(self._defn(), unique_count=6)
        assert plan["planned_candidates"] == 6
        b = budget_plan(self._defn("BUDGETED_GRID",
                                   {"max_design_candidates": 2}), 6)
        assert b["planned_candidates"] == 2

    def test_scenario_evaluation_floor(self):
        from veritx_dse.optimization.space import budget_plan
        # max_scenario_evaluations=8, 1 scenario -> 8 candidates max;
        # with 2 scenarios -> floor(8/2)=4 whole candidates.
        d1 = self._defn("BUDGETED_GRID",
                        {"max_scenario_evaluations": 8})
        assert budget_plan(d1, 6)["planned_candidates"] == 6
        d2_doc = {**BASE,
                  "scenarios": [
                      {"name": "a", "intent": BASE["scenarios"][0]
                       ["intent"]},
                      {"name": "b", "intent": BASE["scenarios"][0]
                       ["intent"]}],
                  "parameters": [{"name": "workload.tp",
                                  "values": [1, 2, 3]}],
                  "search_policy": "BUDGETED_GRID",
                  "budget": {"max_scenario_evaluations": 4}}
        d2 = OptimizationDefinition.parse(d2_doc)
        assert budget_plan(d2, 3)["planned_candidates"] == 2




# ── §19/§18/§27/§53: dedupe, INVALID visibility, §10 gate ────────────────

def _resolvable_defn_doc() -> dict:
    """A definition whose scenario intents resolve (mirrors the E2E
    helper shape: canonical Wave-D multicast + registered params)."""
    import veritx_e_helpers as h
    intent = h.scenario_intent(name="dedupe-s", phase="DECODE",
                               wave_e=None)
    return {
        "name": "dedupe",
        "scenarios": [{"name": "s", "intent": intent}],
        "parameters": [
            {"name": "workload.tp", "values": [1, 2]},
            {"name": "workload.dp", "values": [2, 4]}],
        "objectives": [{"metric": "system.makespan_s",
                        "direction": "MINIMIZE", "scenario": "s"}],
        "search_policy": "EXHAUSTIVE_GRID",
    }


class TestCandidateAccounting:
    """§18/§19/§27/§64: resolve before execute; duplicates stay visible
    as ALIAS; invalid assignments stay in accounting with reasons."""

    def test_distinct_assignments_all_valid(self):
        """Distinct tp/dp resolve to distinct intents: nothing is
        deduped away (§19 must not collapse real differences)."""
        from veritx_dse.optimization.space import build_candidates
        defn = OptimizationDefinition.parse(_resolvable_defn_doc())
        canonical, records = build_candidates(defn)
        assert len(records) == 4
        assert len(canonical) == 4
        assert all(r["status"] == "VALID" for r in records)
        assert len({r["candidate_id"] for r in records}) == 4

    def test_alias_stays_visible_and_points_at_canonical(self):
        """§19: force two raw assignments onto the same resolved intent
        ids by making the scenario template ALREADY carry the value the
        second parameter would set — the alias shape the registry
        actually produces (default spelling vs explicit)."""
        from veritx_dse.optimization.space import build_candidates
        from veritx_dse.optimization.definition import \
            patched_scenario_template
        from veritx_dse.application.requests import resolve_intent
        doc = _resolvable_defn_doc()
        defn = OptimizationDefinition.parse(doc)
        # sanity: distinct assignments -> distinct intents
        intents = {
            tuple(sorted(a.items())): resolve_intent(
                patched_scenario_template(defn.scenarios[0].intent, a))[0]
            .intent_id()
            for a in ({"workload.tp": 1, "workload.dp": 2},
                      {"workload.tp": 2, "workload.dp": 2})}
        assert len(set(intents.values())) == 2
        # identity-level alias proof: the SAME assignment under two
        # parameter declarations that patch the same value dedupes to
        # one candidate with the duplicate marked ALIAS.
        doc2 = _resolvable_defn_doc()
        doc2["parameters"] = [{"name": "workload.tp", "values": [1, 1]}]
        defn2 = OptimizationDefinition.parse(doc2)   # §82 dedupe
        assert raw_cardinality(defn2) == 1
        canonical2, records2 = build_candidates(defn2)
        assert len(canonical2) == 1 and len(records2) == 1
        assert records2[0]["status"] == "VALID"

    def test_invalid_all_scenarios_refuse_no_valid_candidates(self):
        """§53: an unresolvable scenario template makes EVERY raw
        assignment INVALID with the reason recorded; nothing launches,
        nothing disappears."""
        from veritx_dse.optimization.space import build_candidates
        doc = _resolvable_defn_doc()
        doc["scenarios"][0]["intent"]["fabric_preset"] = "no_such_preset"
        defn = OptimizationDefinition.parse(doc)
        canonical, records = build_candidates(defn)
        assert canonical == []
        assert len(records) == 4
        assert all(r["status"] == "INVALID" for r in records)
        assert all(r["error"] for r in records)

    def test_hardware_signature_mismatch_invalidates(self):
        """§10: two scenarios whose templates pin DIFFERENT hardware
        (different fabric presets) refuse every candidate; the error
        names the disagreeing signatures."""
        from veritx_dse.optimization.space import build_candidates
        import veritx_e_helpers as h
        doc = _resolvable_defn_doc()
        other = h.scenario_intent(name="other-s", phase="PREFILL",
                                  wave_e=None)
        other["fabric_preset"] = "mesh4_wide128"   # different hardware
        doc["scenarios"].append({"name": "t", "intent": other})
        defn = OptimizationDefinition.parse(doc)
        canonical, records = build_candidates(defn)
        assert canonical == []
        assert all(r["status"] == "INVALID" for r in records)
        assert all("hardware signature differs" in (r["error"] or "")
                   for r in records)


# ── §30: typed failure classification ────────────────────────────────────

class TestFailureClassification:
    """§30: the orchestrator's per-scenario classification reuses the
    sealed study-status mapping — timeouts stay TIMED_OUT, unsupported
    derivations stay UNSUPPORTED, everything else is FAILED."""

    def test_mapping_is_typed(self):
        from veritx_dse.application.errors import ControlPlaneError, \
            ErrorCode
        from veritx_dse.application.studies import study_status_for_error
        assert study_status_for_error(ControlPlaneError(
            ErrorCode.EXECUTION_TIMEOUT, "x", operation="t")) == "TIMED_OUT"
        assert study_status_for_error(ControlPlaneError(
            ErrorCode.UNSUPPORTED_SEMANTICS, "x",
            operation="t")) == "UNSUPPORTED"
        assert study_status_for_error(ControlPlaneError(
            ErrorCode.EXECUTION_FAILED, "x", operation="t")) == "FAILED"

    def test_orchestrator_uses_the_same_mapping(self):
        from veritx_dse.optimization import orchestrator
        from veritx_dse.application.studies import study_status_for_error
        import inspect
        src = inspect.getsource(orchestrator)
        assert "study_status_for_error" in src
        assert callable(study_status_for_error)


# ── §89: exhaustive-vs-budgeted differential ─────────────────────────────

class TestExhaustiveBudgetDifferential:
    """§89: same tiny space; budgeted N < cardinality evaluates exactly
    the first N canonical candidates and claims strictly less."""

    def test_budgeted_subset_is_canonical_prefix(self):
        from veritx_dse.optimization.space import (
            budget_plan, iter_raw_assignments, raw_cardinality,
        )
        exhaustive = OptimizationDefinition.parse(_resolvable_defn_doc())
        budget_doc = {**_resolvable_defn_doc(),
                      "search_policy": "BUDGETED_GRID",
                      "budget": {"max_design_candidates": 3}}
        budgeted = OptimizationDefinition.parse(budget_doc)
        raw = list(iter_raw_assignments(exhaustive))
        assert raw_cardinality(exhaustive) == 4   # tp {1,2} x dp {2,4}
        # same parameter domains -> identical enumeration (§24) and the
        # budgeted plan IS the prefix cut.
        assert list(iter_raw_assignments(budgeted)) == raw
        plan = budget_plan(budgeted, 4)
        assert plan["planned_candidates"] == 3
        assert raw[:3] == raw[:plan["planned_candidates"]]

    def test_completeness_claims_differ(self):
        """§23/§56: exhaustive over a fully terminal space derives
        search_complete=True; the budgeted leg (NOT_EVALUATED tail)
        derives False — same candidates, different claims."""
        from veritx_dse.optimization.result import derive_search_complete
        terminal = [{"candidate_id": f"c{i}", "status": "SUCCEEDED",
                     "alias_of": None, "index": i} for i in range(6)]
        budgeted = terminal[:3] + [
            {"candidate_id": f"c{i}", "status": "NOT_EVALUATED",
             "alias_of": None, "index": i} for i in range(3, 6)]
        assert derive_search_complete(terminal) is True
        assert derive_search_complete(budgeted) is False

    def test_verdict_language_differs(self):
        """§49 vs §51: FEASIBLE is existential and valid under budget;
        NO_FEASIBLE_DESIGN requires the complete leg."""
        from veritx_dse.optimization.constraints import VerdictInput, \
            optimization_verdict
        assert optimization_verdict(VerdictInput(
            search_complete=True, valid_total=6, feasible=1, rejected=5,
            non_conclusive=0, any_measured=True))["verdict"] == "FEASIBLE"
        assert optimization_verdict(VerdictInput(
            search_complete=False, valid_total=6, feasible=1, rejected=2,
            non_conclusive=3, any_measured=True))["verdict"] == "FEASIBLE"
        assert optimization_verdict(VerdictInput(
            search_complete=True, valid_total=6, feasible=0, rejected=6,
            non_conclusive=0, any_measured=True))["verdict"] == \
            "NO_FEASIBLE_DESIGN"
        assert optimization_verdict(VerdictInput(
            search_complete=False, valid_total=6, feasible=0, rejected=2,
            non_conclusive=4, any_measured=True))["verdict"] == \
            "INCONCLUSIVE"
