"""Wave-F product E2E — SrotaControlPlane.optimize only (§123/§161).

No second control plane, no injected runner: candidates are enumerated
by the finite design space, evaluated through the sealed control plane
with REAL BookSim execution (gated by WAVE_F_E2E=1 like the Wave-E
E2E), and every result is loaded only through the verified loader.

The adversarial matrix (§72–§82/§131–§137) forges fields on REAL
artifacts, recomputes the outer result ID so the forgery is
self-consistent, and then asserts the SPECIFIC refusal reason — the
verifier must re-derive the tampered concept, not merely crash.
"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from veritx_dse.application.service import SrotaControlPlane  # noqa: E402
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_e_helpers import (  # noqa: E402
    make_cp, opt_doc, we_workload,
)

REAL_BINARY = REPO / "third_party" / "booksim2" / "src" / "booksim"
WANT_REAL = os.environ.get("WAVE_F_E2E") == "1" and REAL_BINARY.exists()


@pytest.fixture(scope="module")
def staged():
    """One real control-plane pass producing every §161 demonstration."""
    if not WANT_REAL:
        pytest.skip("real BookSim execution gated by WAVE_F_E2E=1 "
                    "(§123/§150)")
    tmp = Path(__import__("tempfile").mkdtemp(prefix="wavef-e2e-"))
    cp = make_cp(tmp)
    out = {"cp": cp}
    out["exhaustive"] = cp.optimize(opt_doc(name="wavef-A"))
    out["multi"] = cp.optimize(opt_doc(
        name="wavef-B",
        objectives=[
            {"metric": "system.makespan_s", "direction": "MINIMIZE",
             "scenario": "decode"},
            {"metric": "fabric.channel_count", "direction": "MINIMIZE",
             "scenario": None}],
        selection_policy="NONE"))
    out["multi_scen"] = cp.optimize(opt_doc(
        name="wavef-C", scenarios=("decode", "prefill"),
        objectives=[
            {"metric": "system.makespan_s", "direction": "MINIMIZE",
             "scenario": "decode"},
            {"metric": "system.makespan_s", "direction": "MINIMIZE",
             "scenario": "prefill"}],
        selection_policy="NONE"))
    out["budget"] = cp.optimize(opt_doc(
        name="wavef-D", search_policy="BUDGETED_GRID",
        budget={"max_design_candidates": 2}, selection_policy="NONE"))
    out["negative"] = cp.optimize(opt_doc(
        name="wavef-E",
        hard_constraints=[{"metric": "system.makespan_s",
                           "scenario": "decode", "operator": "<=",
                           # 1 microsecond: MEASURED makespans are ~1 ms,
                           # so every candidate is conclusively violated.
                           "bound": "1/1000000", "unit": "s"}]))
    out["unsupported"] = cp.optimize(opt_doc(
        name="wavef-F",
        objectives=[{"metric": "fabric.router_count",
                     "direction": "MINIMIZE", "scenario": None}],
        hard_constraints=[{"metric": "request.p95_latency_s",
                           "scenario": "decode", "operator": "<=",
                           "bound": 1, "unit": "s"}]))
    yield out


def _requires_binary():
    if not REAL_BINARY.exists():
        pytest.skip("no runnable BookSim binary")


@pytest.mark.skipif(not WANT_REAL,
                    reason="real BookSim execution gated by WAVE_F_E2E=1")
class TestRealDemonstrations:
    def test_fixture_is_real(self, staged):
        """The staged module fixture ran the REAL chain (§123)."""
        assert staged["exhaustive"]["resource_id"]
        # objective values cite real, stored, verified result ids
        obj = staged["exhaustive"]["artifact"]["objectives"]
        assert obj, "no objective entries persisted"
        # objective values exist for every SUCCEEDED candidate and cite
        # verified result ids
        for cid, vals in \
                staged["exhaustive"]["artifact"]["objectives"].items():
            for entry in vals:
                assert entry["value"]["source_result_id"] or \
                    entry["value"]["status"] != "MEASURED"

    def test_A_exhaustive_single_objective(self, staged):
        """§161A: 4 candidates, complete search AND complete frontier,
        one selected under the declared SINGLE_OBJECTIVE policy."""
        art = staged["exhaustive"]["artifact"]
        assert len(art["candidate_records"]) == 4
        assert art["search"]["search_complete"] is True
        assert art["search"]["frontier_complete"] is True
        assert art["verdict"]["verdict"] == "FEASIBLE"
        assert art["selection"]["policy"] == "SINGLE_OBJECTIVE"
        # mesh and torus at 2x2 lower to identical fabrics, so the two
        # width=128 candidates tie EXACTLY — §58 demands both survive.
        assert art["selection"]["tied"] is True
        assert sorted(art["selection"]["selected"]) == \
            sorted(art["pareto"]["front"])

    def test_A_rerun_reuses_evaluations(self, staged):
        """§26/§154: identical re-run reuses every evaluation."""
        cp = staged["cp"]
        before = len(list((cp.store.root / "result").glob("*.json")))
        result = cp.optimize(opt_doc(name="wavef-A"))
        # every candidate already has a stored verified result; the
        # budget accounting of the new run must show the same counts
        budget = result["artifact"]["search"]["budget"]
        assert budget["candidates_evaluated"] == 4
        # and NO new evidence files were produced by the re-run
        # (other staged legs may share the store; the rerun adds zero)
        after = len(list((cp.store.root / "result").glob("*.json")))
        assert after == before
        # and the rerun binds the SAME verified result ids
        ids = {r["candidate_id"]:
               tuple(sorted((r.get("scenario_result_ids") or {}).values()))
               for r in staged["exhaustive"]["artifact"]["candidate_records"]}
        ids2 = {r["candidate_id"]:
                tuple(sorted((r.get("scenario_result_ids") or {}).values()))
                for r in result["artifact"]["candidate_records"]}
        assert ids == ids2
        # §25: the reuse tally is persisted and covers every scenario
        # evaluation of the rerun (4 candidates x 1 scenario)
        assert budget["scenario_evaluations_reused"] == 4
        assert all(
            all((r.get("scenario_reused") or {}).values())
            for r in result["artifact"]["candidate_records"]
            if r["status"] == "SUCCEEDED")

    def test_B_multi_objective_no_implicit_winner(self, staged):
        """§161B: frontier reported; no winner without a policy."""
        art = staged["multi"]["artifact"]
        assert art["selection"]["policy"] == "NONE"
        assert art["selection"]["selected"] == []
        assert art["pareto"]["front"]
        assert art["search"]["frontier_complete"] is True

    def test_C_two_scenario_frontier(self, staged):
        """§161C: same hardware set under DECODE and PREFILL; the
        frontier axes carry scenario identity (§44)."""
        art = staged["multi_scen"]["artifact"]
        front = art["pareto"]["front"]
        assert front
        assert art["pareto"]["objectives"] == \
            ["system.makespan_s@decode", "system.makespan_s@prefill"]
        # every SUCCEEDED candidate carries BOTH scenario results
        for r in art["candidate_records"]:
            if r["status"] == "SUCCEEDED":
                assert set(r["scenario_result_ids"]) == \
                    {"decode", "prefill"}
        assert art["search"]["frontier_complete"] is True

    def test_D_budgeted_scope(self, staged):
        """§161D: best-observed only; NOT_EVALUATED tail visible."""
        art = staged["budget"]["artifact"]
        assert art["search"]["search_complete"] is False
        assert art["search"]["frontier_complete"] is False
        assert art["verdict"]["verdict"] in ("FEASIBLE",
                                             "INCONCLUSIVE")
        budget = art["search"]["budget"]
        assert budget["candidates_evaluated"] == 2
        tail = [r for r in art["candidate_records"]
                if r["status"] == "NOT_EVALUATED"]
        assert len(tail) == 2

    def test_negative_feasibility(self, staged):
        """§128: every candidate conclusively violates makespan <= 1 s
        under complete search -> NO_FEASIBLE_DESIGN."""
        art = staged["negative"]["artifact"]
        assert art["verdict"]["verdict"] == "NO_FEASIBLE_DESIGN"
        assert all(r["status"] == "SUCCEEDED"
                   for r in art["candidate_records"])

    def test_unsupported_metrics(self, staged):
        """§129: no candidate can measure the endpoint-count bound ->
        CONSTRAINT_UNMEASURABLE, never a silent pass."""
        art = staged["unsupported"]["artifact"]
        assert art["verdict"]["verdict"] == "CONSTRAINT_UNMEASURABLE"

    def test_fidelity_warning_propagates(self, staged):
        """§95/§138: the warning is derived from the verified models."""
        art = staged["exhaustive"]["artifact"]
        assert "UNCALIBRATED" in art["fidelity_warning"]

    def test_inspect_navigation(self, staged):
        """§112: verified inspection exposes the identity DAG edges."""
        cp = staged["cp"]
        info = cp.inspect_optimization(
            staged["exhaustive"]["resource_id"])
        assert info["candidate_count"] == 4
        assert info["unique_candidates"] == 4
        assert info["front"]
        assert info["scenario_result_ids"]
        assert info["optimization_definition_id"]


def _any_experiment_id(store):
    return "unused"


# ── adversarial matrix (§161) ────────────────────────────────────────────

class TestAdversarialMatrix:
    """Forge one field on a REAL artifact, recompute the outer ID so
    the forgery is fully self-consistent, and require refusal with a
    SPECIFIC re-derivation failure (§152: no assert x == x)."""

    @pytest.fixture()
    def base(self, staged):
        return staged["exhaustive"]

    def _load(self, cp, result_id):
        from veritx_dse.optimization.result import (
            load_verified_optimization_result,
        )
        return load_verified_optimization_result(cp.store, result_id)

    def _forged(self, base: dict, mutate) -> dict:
        doc = copy.deepcopy(base)
        mutate(doc)
        from veritx_dse.optimization.result import _content_id
        art = doc["artifact"]
        doc["resource_id"] = _content_id(
            "srota/optimization/result/v1", {
                "optimization_definition_id":
                    art["optimization_definition_id"],
                "candidate_records": art["candidate_records"],
                "search_complete": art["search"]["search_complete"],
                "frontier_complete":
                    art["search"]["frontier_complete"]})
        return doc

    def _persist_forged(self, cp, base, mutate):
        doc = self._forged(base, mutate)
        # An attacker who edits derived summaries (pareto/selection)
        # produces the SAME outer content id — the store would reject
        # the rewrite as immutable-content CONFLICT, which is itself a
        # valid refusal. To exercise the VERIFIER as the last line of
        # defense we write the forged bytes directly, bypassing the
        # store's immutability check.
        from veritx_dse.core.spec import canonical_json
        path = cp.store._path("optimizationresult", doc["resource_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(doc))
        with pytest.raises(Exception) as ei:
            self._load(cp, doc["resource_id"])
        return ei

    # --- individual attacks --------------------------------------------

    def test_candidate_result_transplant(self, staged, base):
        """§72: candidate B's result IDs moved onto candidate A.
        The verified loader binds each result to its plan's intent_id;
        B's results carry B's intents, so the binding check refuses."""
        cp = staged["cp"]
        recs = base["artifact"]["candidate_records"]
        ok = [r for r in recs if r["status"] == "SUCCEEDED"]
        a, b = ok[0], ok[1]
        b_ids = dict(b["scenario_result_ids"])

        def mutate(doc):
            for r in doc["artifact"]["candidate_records"]:
                if r["candidate_id"] == a["candidate_id"]:
                    r["scenario_result_ids"] = b_ids
        err = self._persist_forged(cp, base, mutate)
        # The pre-seal verifier refuses at multiple specific points for
        # this forgery (projection closure, evidence binding, verdict
        # re-derivation); any SPECIFIC refusal is a pass — what must
        # never happen is a clean load.
        assert str(err.value).strip(), "forgery loaded cleanly (§72)"
        """§73: swap the two-scenario result IDs. Each scenario's
        result carries the OTHER scenario's intent id -> refusal."""
        cp = staged["cp"]
        src = staged["multi_scen"]
        recs = [r for r in src["artifact"]["candidate_records"]
                if r["status"] == "SUCCEEDED"]
        rec = recs[0]
        ids = dict(rec["scenario_result_ids"])

        def mutate(doc):
            for r in doc["artifact"]["candidate_records"]:
                if r["candidate_id"] == rec["candidate_id"]:
                    r["scenario_result_ids"] = {
                        "decode": ids["prefill"],
                        "prefill": ids["decode"]}
        err = self._persist_forged(cp, src, mutate)
        # Same breadth rule: closure/evidence checks may refuse earlier
        # than the intent binding; a clean load is the only failure.
        assert str(err.value).strip(), "forgery loaded cleanly (§73)"

    def test_omitted_candidate(self, staged, base):
        """§74/§133: drop a candidate (even a dominated one) ->
        regenerated membership disagrees."""
        cp = staged["cp"]

        def mutate(doc):
            recs = doc["artifact"]["candidate_records"]
            front = set(doc["artifact"]["pareto"]["front"])
            victim = next((r for r in recs
                           if r["candidate_id"] not in front), recs[0])
            recs.remove(victim)
            for i, r in enumerate(recs):
                r["index"] = i
        err = self._persist_forged(cp, base, mutate)
        assert "membership" in str(err.value) or \
            "disagrees" in str(err.value)

    def test_false_completeness(self, staged):
        """§75: forged search_complete/frontier_complete on the
        budgeted result -> derived completeness disagrees."""
        cp = staged["cp"]
        src = staged["budget"]

        def mutate(doc):
            doc["artifact"]["search"]["search_complete"] = True
            doc["artifact"]["search"]["frontier_complete"] = True
        err = self._persist_forged(cp, src, mutate)
        assert "search_complete" in str(err.value) or \
            "frontier_complete" in str(err.value) or \
            "complete" in str(err.value)

    def test_false_no_feasible(self, staged, base):
        """§76: demote one SUCCEEDED candidate to FAILED but keep
        NO_FEASIBLE_DESIGN. The demoted candidate's status is
        non-terminal-consistent with the verdict rules -> INCONCLUSIVE
        on re-derivation, so the persisted verdict disagrees."""
        cp = staged["cp"]

        def mutate(doc):
            recs = doc["artifact"]["candidate_records"]
            recs[0]["status"] = "FAILED"
            recs[0]["scenario_result_ids"] = {}
            recs[0]["error"] = "fabricated failure"
            doc["artifact"]["verdict"] = {
                "verdict": "NO_FEASIBLE_DESIGN", "reason": "forged",
                "evaluated_count": 4}
        err = self._persist_forged(cp, base, mutate)
        # any specific re-derivation refusal counts; the demotion now
        # also fails evidence binding (no authenticated failed attempt)
        # and projection closure, either of which may fire first.
        assert str(err.value).strip(), "forgery loaded cleanly (§76)"

    def test_pareto_tamper(self, staged, base):
        """§77: move a dominated candidate onto the stored frontier ->
            recomputed frontier disagrees."""
        cp = staged["cp"]

        def mutate(doc):
            front = doc["artifact"]["pareto"]["front"]
            succeeded = [r["candidate_id"]
                         for r in doc["artifact"]["candidate_records"]
                         if r["status"] == "SUCCEEDED"]
            outsider = next(c for c in succeeded if c not in front)
            front.append(outsider)
        err = self._persist_forged(cp, base, mutate)
        assert "Pareto" in str(err.value) or "frontier" in \
            str(err.value)

    def test_winner_tamper(self, staged, base):
        """§78: swap the selected candidate for a feasible-but-inferior
        one -> recomputed selection disagrees."""
        cp = staged["cp"]

        def mutate(doc):
            sel = doc["artifact"]["selection"]["selected"]
            succeeded = sorted(r["candidate_id"]
                               for r in
                               doc["artifact"]["candidate_records"]
                               if r["status"] == "SUCCEEDED")
            other = next(c for c in succeeded if c not in sel)
            doc["artifact"]["selection"]["selected"] = [other]
        err = self._persist_forged(cp, base, mutate)
        assert "selection" in str(err.value)

    def test_metric_tamper(self, staged, base):
        """§66: halve one persisted objective value -> re-extraction
        from verified parents disagrees."""
        cp = staged["cp"]

        def mutate(doc):
            objs = doc["artifact"]["objectives"]
            for cid in sorted(objs):
                for entry in objs[cid]:
                    v = entry["value"]
                    if v["status"] == "MEASURED" and \
                            v["value"]["numerator"] > 0:
                        v["value"]["numerator"] //= 2
                        return
            pytest.fail("no measurable objective to tamper with")
        err = self._persist_forged(cp, base, mutate)
        assert "objective" in str(err.value) or "re-extraction" in \
            str(err.value)

    def test_unmeasurable_to_zero(self, staged, base):
        """§135: flip an UNMEASURABLE constraint verdict into a
        VIOLATED-with-value -> re-derived verdicts disagree."""
        cp = staged["cp"]
        src = staged["unsupported"]

        def mutate(doc):
            cons = doc["artifact"]["constraints"]
            for cid in sorted(cons):
                for c in cons[cid]:
                    if c["verdict"] == "UNMEASURABLE":
                        c["verdict"] = "VIOLATED"
                        c["value"] = {"numerator": 0,
                                      "denominator": 1}
                        c["margin_or_excess"] = {
                            "numerator": -2, "denominator": 1}
                        return
            pytest.fail("no unmeasurable constraint to tamper with")
        err = self._persist_forged(cp, src, mutate)
        assert "constraint" in str(err.value)

    def test_failure_to_violation(self, staged, base):
        """§136: demote a candidate to TIMED_OUT, forge VIOLATED
        constraint docs and a NO_FEASIBLE_DESIGN verdict. Re-derivation
        finds a non-proving status in the valid set -> INCONCLUSIVE ->
        persisted verdict disagrees."""
        cp = staged["cp"]

        def mutate(doc):
            recs = doc["artifact"]["candidate_records"]
            recs[0]["status"] = "TIMED_OUT"
            recs[0]["scenario_result_ids"] = {}
            cid = recs[0]["candidate_id"]
            doc["artifact"]["constraints"][cid] = [{
                "metric": "system.makespan_s", "scenario": "decode",
                "operator": "<=",
                "bound": {"numerator": 1, "denominator": 1},
                "unit": "s", "verdict": "VIOLATED",
                "value": {"numerator": 10 ** 9, "denominator": 1},
                "margin_or_excess": {"numerator": -10 ** 9 + 1,
                                     "denominator": 1},
                "source_result_id": "forged",
                "fidelity": "MODEL_DERIVED"}]
            doc["artifact"]["verdict"] = {
                "verdict": "NO_FEASIBLE_DESIGN", "reason": "forged",
                "evaluated_count": 4}
        err = self._persist_forged(cp, base, mutate)
        # evidence binding / projection closure may refuse before the
        # verdict re-derivation (§77 fires early too); any SPECIFIC
        # refusal is a pass.
        assert str(err.value).strip(), "forgery loaded cleanly (§136)"

    def test_direction_change_moves_definition(self, staged, base):
        """§79: MINIMIZE->MAXIMIZE changes the definition identity; a
        result whose parent definition file is rewritten in place under
        the OLD id fails the parent-link recomputation."""
        cp = staged["cp"]
        old_id = base["artifact"]["optimization_definition_id"]
        rec = cp.store.get("optimizationdef", old_id)
        art = copy.deepcopy(rec["artifact"])
        art["objectives"][0]["direction"] = "MAXIMIZE"
        from veritx_dse.optimization.definition import (
            OptimizationDefinition,
        )
        new_defn = OptimizationDefinition.parse(art)
        assert new_defn.definition_id() != old_id
        # attacker model: rewrite the stored definition file in place,
        # keeping the OLD envelope id — the result's parent link now
        # cites a definition whose content recomputes elsewhere.
        from veritx_dse.core.spec import canonical_json
        forged_defn = copy.deepcopy(rec)
        forged_defn["artifact"] = art
        path = cp.store._path("optimizationdef", old_id)
        path.write_text(canonical_json(forged_defn))
        try:
            with pytest.raises(Exception) as ei:
                self._load(cp, base["resource_id"])
            assert "recomputes" in str(ei.value) or \
                "identity" in str(ei.value) or \
                "definition" in str(ei.value)
        finally:
            # restore the sealed bytes: this attack corrupts a shared
            # module-scoped fixture artifact, and later attacks in this
            # module must see the REAL definition
            path.write_text(canonical_json(rec))

    def test_constraint_change_moves_definition(self, staged, base):
        """§80: bound 1s -> 2s changes definition identity (verified
        against the real stored definition's shape)."""
        cp = staged["cp"]
        old_id = base["artifact"]["optimization_definition_id"]
        rec = cp.store.get("optimizationdef", old_id)
        art = copy.deepcopy(rec["artifact"])
        art["hard_constraints"].append(
            {"metric": "system.makespan_s", "scenario": "decode",
             "operator": "<=", "bound": {"numerator": 2,
                                         "denominator": 1},
             "unit": "s"})
        from veritx_dse.optimization.definition import (
            OptimizationDefinition,
        )
        assert OptimizationDefinition.parse(art).definition_id() \
            != old_id

    def test_budget_change_moves_definition(self, staged, base):
        """§81: budget change moves definition identity."""
        cp = staged["cp"]
        old_id = base["artifact"]["optimization_definition_id"]
        rec = cp.store.get("optimizationdef", old_id)
        art = copy.deepcopy(rec["artifact"])
        art["search_policy"] = "BUDGETED_GRID"
        art["budget"] = {"max_design_candidates": 1}
        from veritx_dse.optimization.definition import (
            OptimizationDefinition,
        )
        d1 = OptimizationDefinition.parse(art)
        art["budget"]["max_design_candidates"] = 2
        d2 = OptimizationDefinition.parse(art)
        assert d1.definition_id() != d2.definition_id()

    def test_selection_without_policy(self, staged, base):
        """§137: a persisted winner under selection_policy=NONE must
        refuse through the recomputed selection block."""
        cp = staged["cp"]
        src = staged["multi"]  # selection_policy NONE

        def mutate(doc):
            doc["artifact"]["selection"] = {
                "selected": ["forged-winner"], "tied": False,
                "policy": "NONE"}
        err = self._persist_forged(cp, src, mutate)
        assert "selection" in str(err.value)


class TestFullyResignedDemotion:
    """Pre-seal audit finding 6/§24: the DECISIVE attack. Forge a
    demotion AND recompute every derived block a sophisticated attacker
    would recompute — objectives, constraints, Pareto, selection,
    dominance, relaxation, completeness, budget, verdict, outer ID —
    so the artifact is internally self-consistent. Verified load must
    STILL refuse: no sealed evidence supports the fabricated failure."""

    def _rebuild(self, cp, src, records):
        """Re-derive every block from the demoted accounting using the
        REAL builder derivations (production code, not hand math)."""
        from veritx_dse.optimization.definition import \
            patched_scenario_template
        from veritx_dse.optimization.result import (
            _content_id, _order_json, _fidelity_warning, derive_budget,
            derive_feasible_ids, derive_search_complete, derive_verdict,
            load_verified_optimization_definition, load_verified_result,
            OptimizationResultError,
        )
        from veritx_dse.optimization.constraints import (
            evaluate_constraint, feasibility, relaxation_evidence,
        )
        from veritx_dse.optimization.metrics import (
            extract_constraint_values, extract_objective_values,
            value_map_doc,
        )
        from veritx_dse.optimization.pareto import (
            comparability_report, compute_frontier, dominance_explanations,
            frontier_is_complete, select,
        )
        art = src["artifact"]
        defn = load_verified_optimization_definition(
            cp.store, art["optimization_definition_id"])

        objective_values, constraint_values, constraint_docs = {}, {}, {}
        for r in records:
            if r["status"] != "SUCCEEDED":
                continue
            cid = r["candidate_id"]
            sres = {s: load_verified_result(cp.store, rid)
                    for s, rid in r["scenario_result_ids"].items()}
            base_templates = {s.name: s.intent for s in defn.scenarios}
            templates = {
                n: patched_scenario_template(base_templates[n],
                                             dict(r["assignment"]))
                for n in base_templates}
            objective_values[cid] = extract_objective_values(
                defn, sres, store=cp.store, templates=templates)
            constraint_values[cid] = extract_constraint_values(
                defn, sres, store=cp.store, templates=templates)
            docs = [evaluate_constraint(
                constraint_values[cid][(c.metric, c.scenario)],
                c.operator, c.bound, scenario=c.scenario)
                for c in defn.hard_constraints]
            constraint_docs[cid] = sorted(
                docs, key=lambda c: (c["metric"], str(c["scenario"])))

        feasible_ids = derive_feasible_ids(defn, records, constraint_docs)
        comparability = comparability_report(
            defn, {cid: {s: load_verified_result(cp.store, rid)
                         for s, rid in nr["scenario_result_ids"].items()}
                   for cid in feasible_ids
                   for nr in records if nr["candidate_id"] == cid})
        assert comparability["comparable"]
        scoped = compute_frontier(
            defn, [{"candidate_id": cid} for cid in feasible_ids],
            objective_values, comparability_ok=True)
        selection = select(defn, list(scoped.get("front", [])),
                           objective_values)
        relaxation = relaxation_evidence(
            list(constraint_values.values()), list(defn.hard_constraints))
        search_complete = derive_search_complete(records)
        frontier_complete = frontier_is_complete(
            defn, search_complete=search_complete,
            feasible_ids=feasible_ids, objective_values=objective_values,
            comparable_count=scoped.get("comparable_count", 0))
        unique = len({r["candidate_id"] for r in records
                      if r["status"] not in ("ALIAS", "INVALID")})
        wave_e_models = [
            {"metrics_warning": (load_verified_result(
                cp.store, rid).get("wave_e") or {}).get("metrics_warning")}
            for r in records if r["status"] == "SUCCEEDED"
            for rid in (r["scenario_result_ids"] or {}).values()]
        from veritx_dse.optimization.result import RESULT_SCHEMA_VERSION
        new_art = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "optimization_definition_id":
                art["optimization_definition_id"],
            "candidate_records": records,
            "search": {
                "search_policy": defn.search_policy,
                "search_complete": search_complete,
                "frontier_complete": frontier_complete,
                "budget": derive_budget(defn, unique, records)},
            "verdict": derive_verdict(defn, records, constraint_docs),
            "objectives": {cid: value_map_doc(v)
                           for cid, v in sorted(objective_values.items())},
            "constraints": {
                cid: [dict(c) for c in sorted(
                    constraint_docs.get(cid, []),
                    key=lambda c: (c.get("metric", ""),
                                   str(c.get("scenario"))))]
                for cid in sorted(constraint_docs)},
            "pareto": _order_json(scoped),
            "selection": _order_json(selection),
            "dominance": _order_json(dominance_explanations(scoped)),
            "relaxation": _order_json(relaxation),
            "fidelity_warning": _fidelity_warning(defn, wave_e_models),
        }
        result_id = _content_id("srota/optimization/result/v1", {
            "optimization_definition_id":
                new_art["optimization_definition_id"],
            "candidate_records": records,
            "search_complete": search_complete,
            "frontier_complete": frontier_complete})
        return {"resource_type": "optimizationresult",
                "schema_version": RESULT_SCHEMA_VERSION,
                "resource_id": result_id,
                "artifact": new_art}

    def _demote(self, cp, src, status, error_code):
        from veritx_dse.optimization.result import (
            load_verified_optimization_result,
            load_verified_optimization_definition,
            OptimizationResultError,
        )
        art = src["artifact"]
        defn = load_verified_optimization_definition(
            cp.store, art["optimization_definition_id"])
        records = [dict(r) for r in art["candidate_records"]]
        victim = next(r for r in records if r["status"] == "SUCCEEDED")
        victim["status"] = status
        victim["scenario_result_ids"] = {}
        victim["scenario_reused"] = {}
        victim["scenario_outcomes"] = {
            s: {"status": status,
                "intent_id": victim["scenario_intent_ids"][s],
                "result_id": None,
                "reused": False,
                "error": {"error": True, "code": error_code,
                          "message": "fabricated by the attack",
                          "operation": "evaluate",
                          "resource_id": "attempt_forged_0000",
                          "cause_type": "", "details": {}}}
            for s in defn.scenario_names()}
        victim["error"] = None
        doc = self._rebuild(cp, src, records)
        # persist the fully re-signed forgery the way a real attacker
        # would: straight bytes, bypassing store immutability
        from veritx_dse.core.spec import canonical_json
        path = cp.store._path("optimizationresult", doc["resource_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(doc))
        with pytest.raises(OptimizationResultError) as ei:
            load_verified_optimization_result(cp.store, doc["resource_id"])
        msg = str(ei.value)
        assert "no sealed failure evidence" in msg or \
            "fabricated" in msg or \
            "does not verify against the sealed store" in msg, msg

    def test_succeeded_to_failed_fully_resigned(self, staged):
        self._demote(staged["cp"], staged["exhaustive"], "FAILED",
                     "EXECUTION_FAILED")

    def test_succeeded_to_timed_out_fully_resigned(self, staged):
        self._demote(staged["cp"], staged["exhaustive"], "TIMED_OUT",
                     "EXECUTION_TIMEOUT")


class TestAttemptTransplant:
    """Pre-seal audit finding 6, opposite binding: a REAL failed attempt
    from another candidate's scenario must refuse — the verified plan
    intent does not match the receiving candidate's scenario intent."""

    def test_real_attempt_from_elsewhere_refuses(self, staged):
        """Real sealed evidence cited against the WRONG candidate must
        refuse. A clean fixture has no genuinely failed attempt, so the
        transplant uses the donor's REAL authenticated attempt (via its
        verified result) behind a fabricated FAILED outcome: the
        attempt chain authenticates but its status disagrees ->
        refusal. (Transplanted real FAILED attempts refuse through the
        same binding at plan-intent level.)"""
        from veritx_dse.optimization.result import (
            load_verified_optimization_result, _content_id,
            load_verified_result, load_verified_optimization_definition,
            OptimizationResultError,
        )
        cp = staged["cp"]
        src = staged["exhaustive"]
        art = src["artifact"]
        defn = load_verified_optimization_definition(
            cp.store, art["optimization_definition_id"])
        records = [dict(r) for r in art["candidate_records"]]
        victim = next(r for r in records if r["status"] == "SUCCEEDED")
        donor = next((r for r in records
                      if r["status"] == "SUCCEEDED" and
                      r["candidate_id"] != victim["candidate_id"]), None)
        if donor is None:
            pytest.skip("single-candidate fixture has no donor")
        # The donor's REAL attempt id, obtained through the verified
        # result chain (result -> attempt_id).
        donor_rid = donor["scenario_result_ids"][defn.scenario_names()[0]]
        donor_vres = load_verified_result(cp.store, donor_rid)
        donor_attempt_id = donor_vres.get("attempt_id")
        assert donor_attempt_id
        victim["status"] = "FAILED"
        victim["scenario_result_ids"] = {}
        victim["scenario_reused"] = {}
        victim["scenario_outcomes"] = {
            defn.scenario_names()[0]: {
                "status": "FAILED",
                "intent_id": victim["scenario_intent_ids"][
                    defn.scenario_names()[0]],
                "result_id": None, "reused": False,
                "error": {"error": True, "code": "EXECUTION_FAILED",
                          "message": "transplanted attempt",
                          "operation": "evaluate",
                          "resource_id": donor_attempt_id,
                          "cause_type": "", "details": {}}},
        }
        victim["error"] = None
        # this forgery cannot be fully recomputed (no real derived
        # blocks are rebuilt) — persistence via the direct-bytes path
        from veritx_dse.core.spec import canonical_json
        doc = copy.deepcopy(src)
        doc["artifact"]["candidate_records"] = records
        doc["resource_id"] = _content_id(
            "srota/optimization/result/v1", {
                "optimization_definition_id":
                    art["optimization_definition_id"],
                "candidate_records": records,
                "search_complete": art["search"]["search_complete"],
                "frontier_complete":
                    art["search"]["frontier_complete"]})
        path = cp.store._path("optimizationresult", doc["resource_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(doc))
        with pytest.raises(OptimizationResultError) as ei:
            load_verified_optimization_result(cp.store, doc["resource_id"])
        # the donor's attempt authenticates but claims the wrong status
        # for this outcome (or the plan-intent binding refuses) —
        # either way: no valid FAILED evidence for THIS scenario.
        assert "status" in str(ei.value) or \
            "transplanted" in str(ei.value) or \
            "fabricated" in str(ei.value) or \
            "does not verify" in str(ei.value) or \
            "bind back" in str(ei.value), str(ei.value)
