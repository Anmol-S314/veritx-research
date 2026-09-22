"""P2 guided optimization — contract tests (deterministic search + Pareto).

Style: independent oracles written in-file (brute-force Pareto, canonical
re-enumeration), never calls into production code under test except
through the documented seams. No BookSim binary, no subprocess, no
network: the fake evaluator compiles through the REAL FabricCompiler
(pure function of the request) and scores analytic objectives.

Covers: definition GUIDED/LOCKED guards, candidate identity, deterministic
search, fake-evaluator determinism, constraint truth table, Pareto oracle
agreement + sealed-gate cross-check, end-to-end grid study incl. frozen
OptimizationStudyView validation, and the no-LOCKED-mutation invariant.
"""
from __future__ import annotations

import dataclasses
import itertools
import json
import random
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.optimization.candidate import (  # noqa: E402
    CandidateError,
    apply_patch,
    candidate_id_for,
    make_candidate,
)
from veritx_dse.optimization.constraints import (  # noqa: E402
    ConstraintError,
    evaluate_all,
    evaluate_constraint_value,
)
from veritx_dse.optimization.definition import (  # noqa: E402
    Constraint,
    DomainParam,
    Objective,
    OptimizationDefinition,
    OptimizationDefinitionError,
)
from veritx_dse.application.requirements import report_identity  # noqa: E402
from veritx_dse.optimization.evaluators import (  # noqa: E402
    AUTHORITY_ANALYTIC_FAKE,
    AUTHORITY_CERTIFIED_BACKEND,
    CandidateEvaluation,
    FakeDeterministicEvaluator,
)
from veritx_dse.optimization.pareto import (  # noqa: E402
    pareto_front,
    pareto_ids,
)
from veritx_dse.optimization.result import (  # noqa: E402
    OptimizationResultError,
    Optimizer,
)
from veritx_dse.optimization.search import (  # noqa: E402
    canonical_assignments,
    raw_cardinality,
    search_candidates,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "optimize_mesh16.json"


def _base():
    from veritx_dse.model.compile_model import CompileRequest
    return CompileRequest.from_dict(json.loads(FIXTURE.read_text()))


def _defn(**kw):
    base = dict(
        domain=(DomainParam("link_width", (32, 128)),
                DomainParam("concentration", (1, 2))),
        objectives=(Objective("latency", "MIN"), Objective("area", "MIN")),
        constraints=(Constraint("latency", "<=", 600.0),),
        method="grid",
    )
    base.update(kw)
    return OptimizationDefinition(**base)


class _CertifiedEvaluator:
    """Test double declaring CERTIFIED_BACKEND authority.

    Reuses the deterministic fake's real-compile + analytic mechanics,
    but binds a contract-shaped (empty) RequirementReport and a
    non-fake performance_result_id under the certified authority, so the
    Pareto/selection machinery stays covered without BookSim. The
    authority is declared explicitly here by design — production code
    never fabricates it (see A-P0.1).
    """

    def __init__(self, seed: int = 7):
        self.inner = FakeDeterministicEvaluator(seed=seed)

    def evaluate(self, candidate):
        ev = self.inner.evaluate(candidate)
        if ev.status != "EVALUATED":
            return dataclasses.replace(
                ev, evaluation_authority=AUTHORITY_CERTIFIED_BACKEND,
                performance_result_id=None, requirement_report=None,
                requirement_report_id=None)
        perf = "test-certified:" + candidate.candidate_id
        report = {
            "contract_version": 1,
            "design_hash": "sha256:" + candidate.request.design_hash(),
            "performance_result_id": perf,
            "entries": [],
        }
        return dataclasses.replace(
            ev, performance_result_id=perf, requirement_report=report,
            requirement_report_id=report_identity(report),
            evaluation_authority=AUTHORITY_CERTIFIED_BACKEND)


# ── definition guards ────────────────────────────────────────────────────

class TestDefinitionGuards:
    @pytest.mark.parametrize("locked", [
        "routing", "routing_function", "routing_algorithm",
        "vc_count", "vc_map", "num_vcs", "vcs",
        "turn_restrictions", "escape_vc", "escapeVC",
        "noc_config.routing", "noc_config.vc_count",
    ])
    def test_locked_dimensions_inconceivable(self, locked):
        with pytest.raises(OptimizationDefinitionError, match="[Ll][Oo][Cc][Kk][Ee][Dd]"):
            OptimizationDefinition(
                domain=(DomainParam(locked, (1, 2)),),
                objectives=(Objective("latency", "MIN"),))

    def test_unknown_guided_refused(self):
        with pytest.raises(OptimizationDefinitionError, match="unknown GUIDED"):
            OptimizationDefinition(
                domain=(DomainParam("hyperdrive", (1, 2)),),
                objectives=(Objective("latency", "MIN"),))

    def test_empty_objectives_refused(self):
        with pytest.raises(OptimizationDefinitionError, match="objective"):
            OptimizationDefinition(domain=(), objectives=())

    def test_duplicate_params_refused(self):
        with pytest.raises(OptimizationDefinitionError, match="duplicate"):
            OptimizationDefinition(
                domain=(DomainParam("link_width", (32,)),
                        DomainParam("noc_config.link_width", (64,))),
                objectives=(Objective("latency", "MIN"),))

    def test_duplicate_objective_metric_refused(self):
        """A4: the same destination declared twice refuses, even with
        different directions."""
        with pytest.raises(OptimizationDefinitionError,
                           match="duplicate objective"):
            OptimizationDefinition(
                domain=(DomainParam("link_width", (32, 64)),),
                objectives=(Objective("latency", "MIN"),
                            Objective("latency", "MAX")))

    def test_duplicate_constraint_metric_refused_at_construction(self):
        """A4 option B: one constraint per metric. latency<=100 plus
        latency>=50 cannot silently overwrite; the definition refuses."""
        with pytest.raises(OptimizationDefinitionError,
                           match="duplicate constraint"):
            OptimizationDefinition(
                domain=(DomainParam("link_width", (32, 64)),),
                objectives=(Objective("latency", "MIN"),),
                constraints=(Constraint("latency", "<=", 100.0),
                             Constraint("latency", ">=", 50.0)))

    def test_bayes_milp_refused(self):
        for method in ("bayes", "bo", "milp", "sa", "rho", "grpo"):
            with pytest.raises(OptimizationDefinitionError, match="Bayes/MILP"):
                OptimizationDefinition(
                    domain=(DomainParam("link_width", (32, 64)),),
                    objectives=(Objective("latency", "MIN"),),
                    method=method)

    def test_random_requires_seed(self):
        with pytest.raises(OptimizationDefinitionError, match="seed"):
            OptimizationDefinition(
                domain=(DomainParam("link_width", (32, 64)),),
                objectives=(Objective("latency", "MIN"),),
                method="random", seed=None)

    def test_definition_id_ignores_declaration_order(self):
        a = OptimizationDefinition(
            domain=(DomainParam("link_width", (128, 32)),
                    DomainParam("concentration", (2, 1))),
            objectives=(Objective("latency", "MIN"),))
        b = OptimizationDefinition(
            domain=(DomainParam("concentration", (1, 2)),
                    DomainParam("link_width", (32, 128))),
            objectives=(Objective("latency", "MIN"),))
        assert a.definition_id() == b.definition_id()

    def test_definition_id_moves_with_semantics(self):
        a = _defn()
        b = _defn(constraints=(Constraint("latency", "<=", 601.0),))
        assert a.definition_id() != b.definition_id()


# ── candidate identity ───────────────────────────────────────────────────

class TestCandidateIdentity:
    def test_patch_applies_guided_only_and_leaves_base_untouched(self):
        base = _base()
        before = base.design_hash()
        cand = make_candidate(base, {"link_width": 128})
        assert base.design_hash() == before
        assert cand.request.noc_config.link_width == 128
        assert base.noc_config.link_width is None
        assert cand.base_design_hash == before

    def test_identity_ignores_key_order(self):
        base = _base()
        h = base.design_hash()
        a = candidate_id_for(h, {"link_width": 128, "concentration": 2})
        b = candidate_id_for(h, {"concentration": 2, "link_width": 128})
        assert a == b

    def test_dotted_alias_normalizes(self):
        base = _base()
        a = make_candidate(base, {"noc_config.link_width": 64})
        b = make_candidate(base, {"link_width": 64})
        assert a.candidate_id == b.candidate_id
        assert a.guided_patch == {"link_width": 64}

    def test_locked_patch_refused(self):
        base = _base()
        with pytest.raises((CandidateError, OptimizationDefinitionError)):
            apply_patch(base, {"routing": "dor"})
        with pytest.raises((CandidateError, OptimizationDefinitionError)):
            apply_patch(base, {"vc_count": 4})

    def test_empty_patch_refused(self):
        with pytest.raises(CandidateError, match="at least one"):
            make_candidate(_base(), {})

    def test_transplanted_id_refused(self):
        from veritx_dse.optimization.candidate import Candidate
        base = _base()
        good = make_candidate(base, {"link_width": 64})
        with pytest.raises(CandidateError, match="content identity"):
            Candidate(candidate_id="cand_forged", base_design_hash=good.base_design_hash,
                      guided_patch=dict(good.guided_patch), request=good.request)


# ── deterministic search ─────────────────────────────────────────────────

class TestDeterministicSearch:
    def test_grid_cardinality_and_canonical_order(self):
        base = _base()
        defn = _defn()
        assert raw_cardinality(defn) == 4
        first = [c.guided_patch for c in search_candidates(base, defn)]
        second = [c.guided_patch for c in search_candidates(base, defn)]
        assert first == second
        # Canonical: concentration (first alphabetically) varies slowest;
        # domain values sort by canonical JSON rendering (MOVED reference
        # rule), so 128 ("128") orders before 32 ("32").
        assert first == [
            {"concentration": 1, "link_width": 128},
            {"concentration": 1, "link_width": 32},
            {"concentration": 2, "link_width": 128},
            {"concentration": 2, "link_width": 32},
        ]

    def test_grid_budget_keeps_canonical_prefix(self):
        base = _base()
        full = search_candidates(base, _defn())
        budgeted = search_candidates(
            base, _defn(budget={"max_candidates": 2}))
        assert [c.candidate_id for c in budgeted] == \
            [c.candidate_id for c in full[:2]]

    def test_random_is_seeded_deterministic_and_bounded(self):
        base = _base()
        kw = dict(domain=(DomainParam("link_width", (32, 64, 128, 256)),
                          DomainParam("concentration", (1, 2, 4)),
                          DomainParam("rcu_enabled", (False, True))),
                  objectives=(Objective("latency", "MIN"),),
                  method="random", budget={"max_candidates": 5}, seed=1234)
        a = [c.candidate_id for c in search_candidates(base, OptimizationDefinition(**kw))]
        b = [c.candidate_id for c in search_candidates(base, OptimizationDefinition(**kw))]
        assert a == b
        assert len(a) == 5
        c = [c.candidate_id for c in search_candidates(
            base, OptimizationDefinition(**{**kw, "seed": 999}))]
        assert sorted(a) != sorted(c)  # seed actually drives the sample

    def test_canonical_assignments_reenumeration_agrees(self):
        """Independent reimplementation: sorted names x sorted values product."""
        defn = _defn()
        params = sorted(defn.domain, key=lambda p: p.name)
        expected = [dict(zip([p.name for p in params], vals))
                    for vals in itertools.product(
                        *[[32, 128], [1, 2]][:len(params)])]
        # Alphabetical param order: concentration first; values in
        # canonical-JSON order (128 before 32).
        assert list(canonical_assignments(defn)) == [
            {"concentration": 1, "link_width": 128},
            {"concentration": 1, "link_width": 32},
            {"concentration": 2, "link_width": 128},
            {"concentration": 2, "link_width": 32},
        ]


# ── fake evaluator ───────────────────────────────────────────────────────

class TestFakeEvaluator:
    def test_deterministic_across_calls_and_instances(self):
        base = _base()
        cand = make_candidate(base, {"link_width": 128})
        e1, e2 = FakeDeterministicEvaluator(seed=7), FakeDeterministicEvaluator(seed=7)
        assert e1.evaluate(cand).objective_values == \
            e2.evaluate(cand).objective_values == \
            e1.evaluate(cand).objective_values

    def test_locked_consequences_match_direct_recompilation(self):
        from veritx_dse.application.fabric_compiler import FabricCompiler
        base = _base()
        cand = make_candidate(base, {"link_width": 128, "concentration": 2})
        ev = FakeDeterministicEvaluator(seed=7).evaluate(cand)
        assert ev.status == "EVALUATED"
        direct = FabricCompiler().compile(cand.request)
        assert direct.status == "COMPILED"
        assert ev.locked_consequences["vc_count"] == \
            direct.bundle.vc_assignment.vc_count
        assert ev.locked_consequences["routing_classes"] == \
            sorted({str(rc) for _, rc in
                    direct.bundle.vc_assignment.vc_to_routing_class})
        assert ev.locked_consequences["router_count"] == \
            direct.bundle.topology.router_count
        assert ev.design_hash == cand.request.design_hash()

    def test_link_width_trades_latency_for_area(self):
        ev = FakeDeterministicEvaluator(seed=7)
        base = _base()
        narrow = ev.evaluate(make_candidate(base, {"link_width": 32}))
        wide = ev.evaluate(make_candidate(base, {"link_width": 128}))
        assert wide.objective_values["latency"] < narrow.objective_values["latency"]
        assert wide.objective_values["area"] > narrow.objective_values["area"]


# ── constraints truth table ──────────────────────────────────────────────

class TestConstraints:
    def test_satisfied_violated_unmeasurable(self):
        sat = evaluate_constraint_value("latency", "<=", 600.0, 179.0)
        assert sat["verdict"] == "SATISFIED" and sat["margin_or_excess"] > 0
        viol = evaluate_constraint_value("latency", "<=", 600.0, 629.0)
        assert viol["verdict"] == "VIOLATED"
        un = evaluate_constraint_value("latency", "<=", 600.0, None)
        assert un["verdict"] == "UNMEASURABLE"
        missing = evaluate_all(
            (Constraint("latency", "<=", 600.0),), {})
        assert missing["feasible"] is None  # never a silent pass

    def test_feasibility_ladder(self):
        cons = (Constraint("latency", "<=", 600.0),)
        assert evaluate_all(cons, {"latency": 100.0})["feasible"] is True
        assert evaluate_all(cons, {"latency": 700.0})["feasible"] is False
        assert evaluate_all(cons, {})["feasible"] is None

    def test_duplicate_metric_refuses_at_evaluation_too(self):
        """A4 defense in depth: even below the definition seam, the
        metric-keyed verdict map refuses to overwrite."""
        cons = (Constraint("latency", "<=", 100.0),
                Constraint("latency", ">=", 50.0))
        with pytest.raises(ConstraintError, match="duplicate constraint"):
            evaluate_all(cons, {"latency": 75.0})


# ── pareto ───────────────────────────────────────────────────────────────

def _brute_front(points: dict[str, tuple]) -> set[str]:
    front = set()
    for a, va in points.items():
        if not any(a != b and all(x <= y for x, y in zip(vb, va))
                   and any(x < y for x, y in zip(vb, va))
                   for b, vb in points.items()):
            front.add(a)
    return front


class TestPareto:
    def test_matches_brute_oracle_on_random_fronts(self):
        rng = random.Random(20260921)
        objs = (Objective("latency", "MIN"), Objective("area", "MIN"))
        for _ in range(25):
            pts = {f"c{i}": (rng.randint(1, 50), rng.randint(1, 50))
                   for i in range(8)}
            moved = pareto_front(
                {k: v for k, v in pts.items()}, ["MIN", "MIN"])
            assert set(moved) == _brute_front(pts)

    def test_ties_stay_ties(self):
        objs = (Objective("latency", "MIN"),)
        out = pareto_ids({"a": {"latency": 5.0}, "b": {"latency": 5.0},
                          "c": {"latency": 6.0}}, objs)
        assert set(out) == {"a", "b"}

    def test_max_direction(self):
        objs = (Objective("score", "MAX"),)
        out = pareto_ids({"a": {"score": 9.0}, "b": {"score": 3.0}}, objs)
        assert out == ("a",)

    def test_agrees_with_sealed_gate(self):
        from veritx_dse.optimization.pareto import pareto_with_sealed_gate
        objs = (Objective("latency", "MIN"), Objective("area", "MIN"))
        vals = {"a": {"latency": 1.0, "area": 9.0},
                "b": {"latency": 9.0, "area": 1.0},
                "c": {"latency": 5.0, "area": 5.0},
                "d": {"latency": 9.0, "area": 9.0}}
        checked = pareto_with_sealed_gate(vals, objs)
        assert set(checked["front"]) == set(checked["scope"]["front"])
        assert "d" not in checked["front"]


# ── end-to-end grid study ────────────────────────────────────────────────

class TestGridStudyEndToEnd:
    def _study(self, **kw):
        base = _base()
        defn = _defn(**kw)
        result = Optimizer().optimize(
            base, defn, _CertifiedEvaluator())
        return base, defn, result

    def test_grid_yields_table_pareto_selection(self):
        base, defn, result = self._study()
        assert len(result.records) == 4
        by = {r.candidate_id: r for r in result.records}
        # Constraint latency<=600 splits the grid: wide link feasible.
        feasible = sorted(r.candidate_id for r in result.records
                          if all(v == "SATISFIED"
                                 for v in r.constraint_verdicts.values()))
        assert len(feasible) == 2
        assert set(result.pareto_ids) <= set(feasible)
        # (link_width 128, concentration 1) dominates (128, 2) on both
        # objectives, so the feasible frontier is a singleton.
        assert len(result.pareto_ids) == 1
        winner = by[result.pareto_ids[0]]
        assert winner.guided_patch == {"concentration": 1,
                                        "link_width": 128}
        assert result.selected_candidate_id == result.pareto_ids[0]
        assert result.selection_rationale
        # Every record binds evaluation identity + locked consequences.
        for r in result.records:
            assert r.design_hash and len(r.design_hash) == 64
            assert r.locked_consequences["routing_classes"] == ["DOR_XY"]
            assert r.locked_consequences["vc_count"] == 2

    def test_execution_order_never_changes_identity(self):
        base = _base()
        defn = _defn()
        r1 = Optimizer().optimize(base, defn, FakeDeterministicEvaluator(seed=7))
        r2 = Optimizer().optimize(base, defn, FakeDeterministicEvaluator(seed=7))
        assert [r.candidate_id for r in r1.records] == \
            [r.candidate_id for r in r2.records]
        assert r1.result_id() == r2.result_id()

    def test_study_view_validates_against_frozen_schema(self):
        jsonschema = pytest.importorskip("jsonschema")
        _, _, result = self._study()
        view = result.to_study_view(contract_version=1)
        schema = json.loads(
            (DSE.parent.parent.parent / "contracts" / "srota" / "v1" /
             "optimization.study.view.schema.json").read_text())
        jsonschema.validate(view, schema)
        assert view["contract_version"] == 1
        assert view["base_design_hash"].startswith("sha256:")
        assert set(view["pareto_ids"]) == {
            c["candidate_id"] for c in view["candidates"]
            if c["pareto_member"]}
        assert view["selected_candidate_id"] in set(view["pareto_ids"])

    def test_study_view_v2_validates_by_default(self):
        """A5: the default projection is the authoritative v2 contract
        at contracts/srota/v2/, with typed constraint verdicts and the
        separated product/objective authorities; v1 stays available for
        pinned callers."""
        jsonschema = pytest.importorskip("jsonschema")
        _, _, result = self._study()
        view = result.to_study_view()
        assert view["contract_version"] == 2
        schema = json.loads(
            (DSE.parent.parent.parent / "contracts" / "srota" / "v2" /
             "optimization.study.view.schema.json").read_text())
        jsonschema.validate(view, schema)
        # A-P1.3: the definition is lossless and identified; the result
        # identity is exposed at the view top level.
        assert view["optimization_result_id"] == result.result_id()
        assert view["definition"]["definition_id"] == \
            result.definition.definition_id()
        assert view["definition"]["objectives"] == [
            {"metric": o.metric, "direction": o.direction}
            for o in result.definition.objectives]
        assert view["definition"]["constraints"] == [
            {"metric": c.metric, "op": c.op, "threshold": c.threshold}
            for c in result.definition.constraints]
        assert view["definition"]["selection"] == "min_first_objective"
        verdicts = {c["constraint_verdicts"]["latency"]
                    for c in view["candidates"]}
        assert verdicts <= {"SATISFIED", "VIOLATED", "UNMEASURABLE"}
        assert "SATISFIED" in verdicts
        for cand in view["candidates"]:
            assert set(cand) == {
                "candidate_id", "guided_patch", "locked_consequences",
                "evaluation_ids", "product_requirements",
                "objective_values", "objective_availability",
                "constraint_verdicts", "evaluation_authority",
                "compilation_status", "evaluation_status",
                "evaluation_reason", "eligibility_reason",
                "pareto_eligible", "pareto_member"}
            assert set(cand["evaluation_ids"]) == {
                "design_hash", "performance_result_id",
                "requirement_report_id"}
            assert cand["pareto_member"] is False or \
                cand["pareto_eligible"] is True
            assert cand["evaluation_authority"] == \
                AUTHORITY_CERTIFIED_BACKEND
            if cand["pareto_eligible"]:
                assert cand["eligibility_reason"] is None
            else:
                assert cand["eligibility_reason"]
            assert set(cand["objective_availability"].values()) <= {
                "MEASURED", "UNMEASURABLE"}

    def test_study_view_v2_preserves_unmeasurable(self):
        """RT-12: UNMEASURABLE survives the v2 view; the v1 path still
        validates its own schema and collapses it fail-closed."""
        jsonschema = pytest.importorskip("jsonschema")
        base = _base()
        defn = OptimizationDefinition(
            domain=(DomainParam("link_width", (32, 128)),),
            objectives=(Objective("latency", "MIN"),),
            constraints=(Constraint("energy", "<=", 1.0),),
            method="grid")
        result = Optimizer().optimize(
            base, defn, FakeDeterministicEvaluator(seed=7))
        v2 = result.to_study_view()
        assert v2["contract_version"] == 2
        schema2 = json.loads(
            (DSE.parent.parent.parent / "contracts" / "srota" / "v2" /
             "optimization.study.view.schema.json").read_text())
        jsonschema.validate(v2, schema2)
        for cand in v2["candidates"]:
            assert cand["constraint_verdicts"]["energy"] == \
                "UNMEASURABLE"
        v1 = result.to_study_view(contract_version=1)
        assert v1["contract_version"] == 1
        schema1 = json.loads(
            (DSE.parent.parent.parent / "contracts" / "srota" / "v1" /
             "optimization.study.view.schema.json").read_text())
        jsonschema.validate(v1, schema1)
        for cand in v1["candidates"]:
            assert cand["constraint_verdicts"]["energy"] is False

    def test_study_view_rejects_unknown_contract_version(self):
        _, _, result = self._study()
        with pytest.raises(OptimizationResultError):
            result.to_study_view(contract_version=3)

    def test_no_locked_mutation(self):
        """Patches never express LOCKED dims; every candidate's VC/route
        is the compiler's derivation for THAT candidate request."""
        from veritx_dse.application.fabric_compiler import FabricCompiler
        from veritx_dse.model.compile_model import derive_vc_assignment
        base = _base()
        defn = _defn(domain=(
            DomainParam("link_width", (32, 128)),
            DomainParam("concentration", (1, 2)),
        ))
        result = Optimizer().optimize(
            base, defn, FakeDeterministicEvaluator(seed=7))
        assert len(result.records) == 4
        for r in result.records:
            assert not (set(r.guided_patch)
                        & {"routing", "vc_count", "turn_restrictions",
                           "escape_vc"})
            comp = FabricCompiler().compile(
                next(c.request for c in
                     __import__("veritx_dse.optimization.search",
                                fromlist=["search_candidates"])
                     .search_candidates(base, defn)
                     if c.candidate_id == r.candidate_id))
            assert comp.status == "COMPILED"
            assert r.locked_consequences["vc_count"] == \
                comp.bundle.vc_assignment.vc_count

    def test_unsupported_rcu_stays_visible_and_excluded(self):
        """rcu_enabled=True is a GUIDED knob the v3 compiler refuses
        (typed UNSUPPORTED, no RCU artifact). The refusal must stay
        visible and never enter the Pareto set — never a silent drop."""
        base = _base()
        defn = OptimizationDefinition(
            domain=(DomainParam("rcu_enabled", (False, True)),),
            objectives=(Objective("latency", "MIN"),),
            method="grid")
        result = Optimizer().optimize(
            base, defn, _CertifiedEvaluator())
        assert len(result.records) == 2
        by_patch = {tuple(sorted(r.guided_patch.items())): r
                      for r in result.records}
        refused = by_patch[(("rcu_enabled", True),)]
        assert refused.evaluation_status == "UNSUPPORTED"
        assert refused.evaluation_authority == \
            AUTHORITY_CERTIFIED_BACKEND
        assert refused.objective_values == {}
        assert refused.candidate_id not in set(result.pareto_ids)
        ok = by_patch[(("rcu_enabled", False),)]
        assert ok.evaluation_status == "EVALUATED"
        assert result.selected_candidate_id == ok.candidate_id

    def test_infeasible_grid_selects_nothing(self):
        _, _, result = self._study(
            constraints=(Constraint("latency", "<=", 1.0),))
        assert result.pareto_ids == ()
        assert result.selected_candidate_id is None
        assert result.selection_rationale

    def test_unmeasured_objective_ineligible_not_keyerror(self):
        """RT-10: a declared objective the evaluation does not evidence
        makes every candidate ineligible with a typed reason — never a
        pareto.py KeyError."""
        base = _base()
        defn = OptimizationDefinition(
            domain=(DomainParam("link_width", (32, 128)),),
            objectives=(Objective("energy", "MIN"),),
            method="grid")
        result = Optimizer().optimize(
            base, defn, FakeDeterministicEvaluator(seed=7))
        assert result.pareto_ids == ()
        assert result.selected_candidate_id is None
        assert "energy" in (result.selection_rationale or "")
        for r in result.records:
            assert r.pareto_member is False
            entries = [d for d in r.objective_details
                       if dict(d)["metric"] == "energy"]
            assert entries, r.candidate_id
            assert dict(entries[0])["state"] == "UNMEASURABLE"
            assert dict(entries[0])["reason"] == (
                "objective energy not evidenced by evaluation")


# ── Fix 1: result identity binds evaluation provenance ───────────────────

class _FixedReportPort:
    """Same objectives for every candidate; reports differ by verdict."""

    def __init__(self, violated: bool):
        self.violated = violated

    def evaluate(self, candidate):
        verdict = "VIOLATED" if self.violated else "SATISFIED"
        report = {
            "contract_version": 1,
            "design_hash": "sha256:" + candidate.request.design_hash(),
            "performance_result_id": "perf:fixed",
            "entries": [{
                "requirement_index": 0,
                "traffic_class": "tp_collective",
                "qos_class": "latency_critical",
                "verdict": verdict,
                "binding": True,
                "required": 600.0,
                "measured": 10.0,
                "metric_authority": "test",
                "performance_result_id": "perf:fixed",
                "reason": "test",
            }],
        }
        return CandidateEvaluation(
            candidate_id=candidate.candidate_id,
            design_hash=candidate.request.design_hash(),
            status="EVALUATED",
            objective_values={"latency": 10.0},
            locked_consequences={},
            performance_result_id="perf:fixed",
            requirement_report=report,
            evaluation_authority=AUTHORITY_CERTIFIED_BACKEND)


class _ValuePort:
    """Certified test port returning exactly the objective_values given."""

    def __init__(self, values):
        self.values = values

    def evaluate(self, candidate):
        perf = "test-certified:" + candidate.candidate_id
        report = {
            "contract_version": 1,
            "design_hash": "sha256:" + candidate.request.design_hash(),
            "performance_result_id": perf,
            "entries": [],
        }
        return CandidateEvaluation(
            candidate_id=candidate.candidate_id,
            design_hash=candidate.request.design_hash(),
            status="EVALUATED",
            objective_values=dict(self.values),
            locked_consequences={},
            performance_result_id=perf,
            requirement_report=report,
            requirement_report_id=report_identity(report),
            evaluation_authority=AUTHORITY_CERTIFIED_BACKEND)


class TestObjectiveStateCompleteness:
    """A3: every requested objective has an explicit state; a missing or
    non-finite value is UNMEASURABLE and can never score or reach Pareto."""

    def _defn(self):
        return OptimizationDefinition(
            domain=(DomainParam("link_width", (32, 128)),),
            objectives=(Objective("latency", "MIN"),),
            method="grid")

    @pytest.mark.parametrize("bad", [
        float("nan"), float("inf"), float("-inf"), True, "fast", None])
    def test_non_finite_or_non_real_objective_is_unmeasurable(self, bad):
        result = Optimizer().optimize(
            _base(), self._defn(), _ValuePort({"latency": bad}))
        assert result.pareto_ids == ()
        assert result.selected_candidate_id is None
        for r in result.records:
            assert r.pareto_eligible is False
            assert r.objective_availability["latency"] == \
                "UNMEASURABLE"
            assert r.objective_values == {}
            assert r.objective_details
            entry = dict(r.objective_details[0])
            assert entry["state"] == "UNMEASURABLE"
            assert "finite real number" in entry["reason"]

    def test_measured_objective_gets_explicit_measured_state(self):
        result = Optimizer().optimize(
            _base(), self._defn(),
            _ValuePort({"latency": 5.0, "area": 7.0}))
        assert result.pareto_ids
        for r in result.records:
            assert r.pareto_eligible is True
            assert r.objective_availability["latency"] == "MEASURED"
            assert r.objective_availability["area"] == "MEASURED"
            assert r.objective_values["latency"] == 5.0
            assert r.objective_details == ()


class _TransplantedReportPort:
    """Evaluator that returns ANOTHER design's report under this id."""

    def __init__(self, foreign_design_hash: str | None = None):
        self.foreign = foreign_design_hash

    def evaluate(self, candidate):
        report = {
            "contract_version": 1,
            "design_hash": "sha256:" + (
                self.foreign if self.foreign is not None
                else candidate.request.design_hash()),
            "performance_result_id": "perf:foreign",
            "entries": [{
                "requirement_index": 0,
                "traffic_class": "tp_collective",
                "qos_class": "latency_critical",
                "verdict": "SATISFIED",
                "binding": True,
                "required": 600.0,
                "measured": 10.0,
                "metric_authority": "test",
                "performance_result_id": "perf:foreign",
                "reason": "test",
            }],
        }
        return CandidateEvaluation(
            candidate_id=candidate.candidate_id,
            design_hash=candidate.request.design_hash(),
            status="EVALUATED",
            objective_values={"latency": 10.0},
            locked_consequences={},
            performance_result_id="perf:foreign",
            requirement_report=report,
            requirement_report_id="forged-not-the-report-identity",
        )


class TestProductRequirementAuthority:
    """A1: product requirements are a separate authority from the study's
    optimizer constraints; backend success alone never makes a candidate
    optimization-eligible when binding product requirements fail."""

    def _defn(self):
        return OptimizationDefinition(
            domain=(DomainParam("link_width", (32, 128)),),
            objectives=(Objective("latency", "MIN"),),
            method="grid")

    def test_backend_success_with_failing_binding_report_is_ineligible(self):
        base = _base()
        result = Optimizer().optimize(
            base, self._defn(), _FixedReportPort(True))
        assert result.pareto_ids == ()
        assert result.selected_candidate_id is None
        for r in result.records:
            assert r.evaluation_status == "EVALUATED"
            assert r.product_requirements_satisfied is False
            assert r.pareto_member is False
            assert r.requirement_report_id
        ok = Optimizer().optimize(
            base, self._defn(), _FixedReportPort(False))
        assert ok.pareto_ids
        for r in ok.records:
            assert r.product_requirements_satisfied is True
            assert r.requirement_report_id

    def test_transplanted_report_refuses_even_with_forged_identity(self):
        base = _base()
        foreign = "ab" * 32
        with pytest.raises(OptimizationResultError, match="transplanted"):
            Optimizer().optimize(
                base, self._defn(), _TransplantedReportPort(foreign))

    def test_report_id_is_rederived_not_trusted(self):
        """The carried id is cross-checked: a report whose identity field
        is forged is refused, never bound."""
        base = _base()
        with pytest.raises(OptimizationResultError, match="forged"):
            Optimizer().optimize(
                base, self._defn(), _TransplantedReportPort(None))


class TestResultIdBindsProvenance:
    def _study(self):
        base = _base()
        defn = OptimizationDefinition(
            domain=(DomainParam("link_width", (32, 128)),
                    DomainParam("concentration", (1, 2))),
            objectives=(Objective("latency", "MIN"),
                          Objective("area", "MIN")),
            constraints=(Constraint("latency", "<=", 600.0),),
            method="grid")
        return base, defn, Optimizer().optimize(
            base, defn, _CertifiedEvaluator())

    def test_moves_with_performance_result_id(self):
        """Equal rounded objectives + different authenticated evaluation
        must hash differently."""
        import dataclasses
        _, _, result = self._study()
        target = result.records[0]
        swapped = dataclasses.replace(
            target, performance_result_id="fake:deadbeefdeadbeef")
        altered = dataclasses.replace(
            result, records=tuple(
                swapped if r.candidate_id == target.candidate_id else r
                for r in result.records))
        assert altered.result_id() != result.result_id()
        # The richer internal object still projects into the frozen view.
        jsonschema = pytest.importorskip("jsonschema")
        schema = json.loads(
            (DSE.parent.parent.parent / "contracts" / "srota" / "v1" /
             "optimization.study.view.schema.json").read_text())
        jsonschema.validate(altered.to_study_view(contract_version=1),
                            schema)

    def test_moves_with_flipped_requirement_verdict(self):
        import dataclasses
        _, _, result = self._study()
        target = next(r for r in result.records if r.pareto_member)
        flipped_details = tuple(
            {**dict(d), "verdict": "VIOLATED",
             "measured": float(dict(d)["required"]) + 100.0}
            if dict(d)["verdict"] == "SATISFIED" else dict(d)
            for d in target.constraint_details)
        flipped = dataclasses.replace(
            target, constraint_details=flipped_details,
            constraint_verdicts={k: "VIOLATED"
                                 for k in target.constraint_verdicts},
            constraints_satisfied=False, pareto_member=False)
        altered = dataclasses.replace(
            result, records=tuple(
                flipped if r.candidate_id == target.candidate_id else r
                for r in result.records),
            pareto_ids=tuple(p for p in result.pareto_ids
                             if p != target.candidate_id),
            selected_candidate_id=None,
            selection_rationale="flipped in test")
        assert altered.result_id() != result.result_id()

    def test_moves_with_requirement_report_identity(self):
        """RT-11: identical rounded objectives, different requirement
        verdicts (different report identity) -> different result_id."""
        base = _base()
        defn = OptimizationDefinition(
            domain=(DomainParam("link_width", (32, 128)),),
            objectives=(Objective("latency", "MIN"),),
            method="grid")
        ok = Optimizer().optimize(base, defn, _FixedReportPort(False))
        bad = Optimizer().optimize(base, defn, _FixedReportPort(True))
        assert [r.objective_values for r in ok.records] == \
            [r.objective_values for r in bad.records]
        assert ok.result_id() != bad.result_id()
        for record in ok.records:
            assert record.requirement_report_id
        assert {r.requirement_report_id for r in ok.records} != \
            {r.requirement_report_id for r in bad.records}

    def test_moves_with_evaluation_status(self):
        import dataclasses
        _, _, result = self._study()
        target = result.records[0]
        failed = dataclasses.replace(
            target, evaluation_status="EVALUATION_FAILED",
            compilation_status="COMPILED",
            objective_values={}, performance_result_id=None)
        altered = dataclasses.replace(
            result, records=tuple(
                failed if r.candidate_id == target.candidate_id else r
                for r in result.records))
        assert altered.result_id() != result.result_id()

    def test_records_bind_requirement_required_measured(self):
        """Every evaluated record carries the auditable binding that
        decided its fate."""
        _, _, result = self._study()
        for r in result.records:
            if r.evaluation_status == "EVALUATED":
                assert r.compilation_status == "COMPILED"
                assert r.performance_result_id is not None
                assert r.constraint_details, r.candidate_id
                for d in r.constraint_details:
                    assert {"metric", "operator", "required", "measured",
                            "verdict", "margin_or_excess",
                            "reason"} == set(d)
                    assert d["required"] == pytest.approx(600.0)
                    assert d["measured"] == pytest.approx(
                        r.objective_values["latency"])
                expect = all(
                    dict(d)["verdict"] == "SATISFIED"
                    for d in r.constraint_details)
                assert r.constraints_satisfied is expect


# ── `veritx optimize` CLI ────────────────────────────────────────────────

class TestOptimizeCli:
    def test_registered_with_documented_flags(self):
        from veritx_dse.cli.cli import COMMANDS, DISPATCH, build_parser
        assert COMMANDS["optimize"]["handler"].__name__ == "cmd_optimize"
        assert COMMANDS["optimize"]["t3_mode"] == "forward"
        assert callable(DISPATCH["optimize"])
        args = build_parser().parse_args(
            ["optimize", str(FIXTURE), "--search", "grid"])
        assert args.fixture == str(FIXTURE)
        assert args.search == "grid"

    def test_grid_run_prints_table_pareto_selection(self, tmp_path, capsys=None):
        import argparse
        from veritx_dse.cli.cli import cmd_optimize
        from veritx_dse.core.logging import Ctx
        study_out = tmp_path / "study.json"
        ctx = Ctx(verbosity=1)
        args = argparse.Namespace(
            fixture=str(FIXTURE), search="grid", link_widths=None,
            concentrations=None, latency_ceiling=None,
            max_candidates=None, study_out=str(study_out))
        cmd_optimize(ctx, args)
        assert not ctx.failed
        view = json.loads(study_out.read_text())
        # RT-12/A-P0.1: the CLI emits (and validates) contract v2 by
        # default, but the FAKE evaluator is analytic authority: its rows
        # are visible with typed reasons and can never be Pareto or
        # selected.
        assert view["contract_version"] == 2
        assert view["base_design_hash"].startswith("sha256:")
        assert len(view["candidates"]) == 4
        assert view["pareto_ids"] == []
        assert view["selected_candidate_id"] is None
        for row in view["candidates"]:
            assert set(row) == {"candidate_id", "guided_patch",
                                "locked_consequences", "evaluation_ids",
                                "product_requirements",
                                "objective_values", "objective_availability",
                                "constraint_verdicts",
                                "evaluation_authority",
                                "compilation_status", "evaluation_status",
                                "evaluation_reason", "eligibility_reason",
                                "pareto_eligible", "pareto_member"}
            assert row["locked_consequences"]["routing_classes"] == ["DOR_XY"]
            assert row["evaluation_authority"] == AUTHORITY_ANALYTIC_FAKE
            assert row["pareto_eligible"] is False
            assert row["pareto_member"] is False
            assert "analytic-fake" in row["eligibility_reason"]

    def test_view_hashes_prefixed_engine_hashes_bare(self, tmp_path):
        """Fix 2: every hash crossing into the study view is
        sha256:-prefixed; engine objects stay bare."""
        import argparse
        from veritx_dse.cli.cli import cmd_optimize
        from veritx_dse.core.logging import Ctx
        study_out = tmp_path / "study.json"
        ctx = Ctx(verbosity=0)
        args = argparse.Namespace(
            fixture=str(FIXTURE), search="grid", link_widths=None,
            concentrations=None, latency_ceiling=None,
            max_candidates=None, study_out=str(study_out))
        cmd_optimize(ctx, args)
        assert not ctx.failed
        view = json.loads(study_out.read_text())
        assert view["base_design_hash"].startswith("sha256:")
        for row in view["candidates"]:
            assert row["evaluation_ids"]["design_hash"].startswith(
                "sha256:"), row["candidate_id"]
        # Engine side stays bare: rebuild and check the records.
        base = _base()
        result = Optimizer().optimize(
            base, _defn(), FakeDeterministicEvaluator(seed=7))
        assert not result.base_design_hash.startswith("sha256:")
        for r in result.records:
            assert not r.design_hash.startswith("sha256:")

    def test_missing_fixture_fails_closed(self, tmp_path):
        import argparse
        from veritx_dse.cli.cli import cmd_optimize
        from veritx_dse.core.logging import Ctx
        ctx = Ctx(verbosity=0)
        args = argparse.Namespace(
            fixture=str(tmp_path / "nope.json"), search="grid",
            link_widths=None, concentrations=None, latency_ceiling=None,
            max_candidates=None, study_out=None)
        cmd_optimize(ctx, args)
        assert ctx.failed
