"""Phase 13 — requirements-driven fabric compiler.

Contract under test (plan §17): requirements stop being inert data and
actively gate synthesis. Verdicts are FEASIBLE (with Pareto evidence over
the feasible set) or NO_FEASIBLE_DESIGN (with violation evidence and
relaxation information). Hard requirements are never silently relaxed:
a constraint the candidate record cannot measure (bandwidth floor today)
fails closed as CONSTRAINT_UNMEASURABLE, not as a pass.

Tests live at the compiler seam — compile_fabric(request, evaluate) — with
a stub evaluate callable standing in for BookSim. The Pareto stage is the
REAL Phase-8 pareto_with_scope (never re-implemented here).
"""
import pytest

from veritx_dse.model.compile_model import QoSClass, Requirement
from veritx_dse.synthesis.compiler import (
    CompilerRequest,
    InvalidCompilerRequest,
    compile_fabric,
)


def _req(**kw) -> Requirement:
    defaults = dict(qos_class=QoSClass.LATENCY_CRITICAL,
                    latency_ceiling_cycles=100.0, binding=True)
    defaults.update(kw)
    return Requirement(**defaults)


def _cand(name: str, latency: float, **extra) -> dict:
    """Candidate entry whose evaluate() yields a SynthResult-shaped dict."""
    d = {"name": name, "topology": "anynet", "seed": 0, "fidelity": "NETWORK_SIMULATION"}
    d.update(extra)
    return d


def _ok_eval(latency_by_name: dict):
    def evaluate(cand: dict) -> dict:
        return {
            "name": cand["name"], "topology": cand.get("topology", "anynet"),
            "backend": cand.get("topology", "anynet"),
            "nodes": cand.get("nodes", 16), "edges": cand.get("edges", 32),
            "latency": latency_by_name[cand["name"]], "status": "ok",
            "error": None, "seed": cand.get("seed", 0),
            "provenance": "stub", "extra": {},
        }
    return evaluate


# ── FEASIBLE ──────────────────────────────────────────────────────────────────

def test_feasible_verdict_with_pareto_evidence():
    req = CompilerRequest(
        requirements=[_req()],
        candidates=[_cand("a", 61.5), _cand("b", 80.0)],
        search_budget={"requested_evaluations": 2},
    )
    out = compile_fabric(req, _ok_eval({"a": 61.5, "b": 80.0}))
    assert out["verdict"] == "FEASIBLE"
    assert out["scope"]["feasible"] == 2
    assert out["pareto"]["candidate_count"] == 2
    assert set(out["pareto"]["front"]) == {"a"}  # 61.5 dominates 80.0


def test_single_constraint_violation_makes_candidate_infeasible():
    req = CompilerRequest(
        requirements=[_req(latency_ceiling_cycles=50.0)],
        candidates=[_cand("a", 61.5), _cand("b", 40.0)],
    )
    out = compile_fabric(req, _ok_eval({"a": 61.5, "b": 40.0}))
    assert out["verdict"] == "FEASIBLE"
    statuses = {c["candidate_id"]: c["status"] for c in out["candidates"]}
    assert statuses == {"a": "CONSTRAINT_VIOLATION", "b": "FEASIBLE"}
    # Violated candidate remains visible with its verdict evidence.
    viol = out["candidates"][0]
    assert viol["constraint_verdicts"][0]["satisfied"] is False
    assert viol["constraint_verdicts"][0]["measured"] == 61.5


# ── NO_FEASIBLE_DESIGN ────────────────────────────────────────────────────────

def test_no_feasible_design_reports_violations_and_relaxation():
    req = CompilerRequest(
        requirements=[_req(latency_ceiling_cycles=50.0)],
        candidates=[_cand("a", 61.5), _cand("b", 72.0)],
    )
    out = compile_fabric(req, _ok_eval({"a": 61.5, "b": 72.0}))
    assert out["verdict"] == "NO_FEASIBLE_DESIGN"
    assert out["pareto"] is None
    viol = out["violated_constraints"]
    assert len(viol) == 1
    assert viol[0]["constraint"]["kind"] == "latency_ceiling"
    assert viol[0]["best_measured"] == 61.5
    assert viol[0]["margin_needed"] == pytest.approx(11.5)
    relax = out["relaxation_information"]
    # Tightest ceiling that would admit the best measured candidate.
    assert relax["minimal_ceiling_admitting_best"] == 61.5
    assert relax["per_constraint"]["latency_ceiling[latency_critical]"]["violations"] == 2


def test_empty_candidate_set_is_invalid_request_not_exhausted_search():
    with pytest.raises(InvalidCompilerRequest, match="candidate"):
        compile_fabric(CompilerRequest(requirements=[_req()], candidates=[]),
                       _ok_eval({}))


# ── fail-closed evaluation gaps ───────────────────────────────────────────────

def test_failed_evaluation_stays_visible_and_fails_closed():
    def failing_eval(cand: dict) -> dict:
        if cand["name"] == "boom":
            return {"name": "boom", "status": "error", "error": "booksim timeout",
                    "latency": None, "extra": {}}
        return _ok_eval({"good": 42.0})(cand)

    req = CompilerRequest(
        requirements=[_req()],
        candidates=[_cand("boom", 0.0), _cand("good", 42.0)],
    )
    out = compile_fabric(req, failing_eval)
    assert out["verdict"] == "FEASIBLE"
    statuses = {c["candidate_id"]: c["status"] for c in out["candidates"]}
    assert statuses["boom"] == "EVALUATION_FAILED"
    boom = next(c for c in out["candidates"] if c["candidate_id"] == "boom")
    assert "booksim timeout" in boom["error"]
    assert boom["constraint_verdicts"] == []  # never fabricated
    assert out["scope"]["evaluation_failed"] == 1


def test_unmeasurable_bandwidth_floor_never_silent_pass():
    req = CompilerRequest(
        requirements=[_req(bandwidth_floor_gbps=10.0, latency_ceiling_cycles=None)],
        candidates=[_cand("a", 61.5)],
    )
    out = compile_fabric(req, _ok_eval({"a": 61.5}))
    statuses = {c["status"] for c in out["candidates"]}
    assert statuses == {"CONSTRAINT_UNMEASURABLE"}
    # Audit #3: all-unmeasurable is unanswerable, never a measured refusal.
    assert out["verdict"] == "CONSTRAINT_UNMEASURABLE"
    assert out["violated_constraints"] == []
    assert out["relaxation_information"] is None
    assert out["unmeasurable_reasons"]["constraint_unmeasurable"] == 1


# ── verdict truth table (spec F) ──────────────────────────────────────

def _truth_table(cands, evaluate):
    req = CompilerRequest(requirements=[_req(latency_ceiling_cycles=50.0)],
                          candidates=cands)
    return compile_fabric(req, evaluate)


def _violator(name):
    return _cand(name, 500.0)


def _crasher(name):
    return {"name": name, "topology": "anynet", "seed": 0}


def _boom_eval(names):
    def evaluate(cand):
        if cand["name"] in names:
            raise RuntimeError("sim died")
        return _ok_eval({cand["name"]: 500.0})(cand)
    return evaluate


def test_all_violations_is_no_feasible_design():
    cands = [_violator(f"v{i}") for i in range(10)]
    out = _truth_table(cands, _ok_eval({c["name"]: 500.0 for c in cands}))
    assert out["verdict"] == "NO_FEASIBLE_DESIGN"
    assert out["relaxation_information"] is not None
    assert out["pareto"] is None


def test_violations_plus_crashes_is_inconclusive():
    cands = [_violator(f"v{i}") for i in range(4)] + \
        [_crasher(f"c{i}") for i in range(6)]
    out = _truth_table(cands, _boom_eval({f"c{i}" for i in range(6)}))
    assert out["verdict"] == "INCONCLUSIVE"
    assert out["pareto"] is None and out["relaxation_information"] is None
    assert out["inconclusive_reasons"]["evaluation_failed"] == 6


def test_unmeasurable_mixed_with_crashes_is_inconclusive():
    req = CompilerRequest(
        requirements=[_req(qos_class=QoSClass.BANDWIDTH,
                           bandwidth_floor_gbps=10.0,
                           latency_ceiling_cycles=None)],
        candidates=[_cand(f"u{i}", 42.0) for i in range(6)] + [
            _crasher(f"c{i}") for i in range(4)],
    )
    lats = {f"u{i}": 42.0 for i in range(6)}
    out = compile_fabric(
        req, lambda c: _boom_eval({f"c{i}" for i in range(4)})(c)
        if c["name"].startswith("c") else _ok_eval(lats)(c))
    assert out["verdict"] == "INCONCLUSIVE"
    assert out["pareto"] is None and out["relaxation_information"] is None
    assert out["violated_constraints"] == []


def test_proven_violation_beats_unmeasurable_at_candidate_level():
    req = CompilerRequest(
        requirements=[_req(latency_ceiling_cycles=50.0),
                      _req(qos_class=QoSClass.BANDWIDTH,
                           bandwidth_floor_gbps=10.0,
                           latency_ceiling_cycles=None)],
        candidates=[_cand("v", 500.0)],
    )
    out = compile_fabric(req, _ok_eval({"v": 500.0}))
    rec = out["candidates"][0]
    assert rec["status"] == "CONSTRAINT_VIOLATION"
    assert rec["unmeasurable"]  # sibling unknown retained as evidence


def test_all_violated_with_unmeasurable_siblings_is_no_feasible():
    req = CompilerRequest(
        requirements=[_req(latency_ceiling_cycles=50.0),
                      _req(qos_class=QoSClass.BANDWIDTH,
                           bandwidth_floor_gbps=10.0,
                           latency_ceiling_cycles=None)],
        candidates=[_cand(f"v{i}", 500.0) for i in range(10)],
    )
    out = compile_fabric(
        req, _ok_eval({f"v{i}": 500.0 for i in range(10)}))
    assert out["verdict"] == "NO_FEASIBLE_DESIGN"
    assert out["relaxation_information"] is not None


def test_violated_plus_pure_unmeasurable_is_inconclusive():
    req = CompilerRequest(
        requirements=[_req(latency_ceiling_cycles=50.0),
                      _req(qos_class=QoSClass.BANDWIDTH,
                           bandwidth_floor_gbps=10.0,
                           latency_ceiling_cycles=None)],
        candidates=[_cand(f"v{i}", 500.0) for i in range(4)] + [
            _cand(f"u{i}", 42.0) for i in range(6)],
    )
    lats = {f"v{i}": 500.0 for i in range(4)}
    lats.update({f"u{i}": 42.0 for i in range(6)})
    out = compile_fabric(req, _ok_eval(lats))
    assert out["verdict"] == "INCONCLUSIVE"
    assert out["pareto"] is None and out["relaxation_information"] is None
    assert out["violated_constraints"] == []
    assert out["inconclusive_reasons"]["constraint_violation"] == 4
    assert out["inconclusive_reasons"]["constraint_unmeasurable"] == 6


def test_violations_plus_pruned_is_inconclusive():
    cands = [_violator(f"v{i}") for i in range(4)] + [
        {"name": f"p{i}", "pruned": True, "pruning_reason": "budget"}
        for i in range(6)]
    out = _truth_table(cands, _ok_eval({f"v{i}": 500.0 for i in range(4)}))
    assert out["verdict"] == "INCONCLUSIVE"
    assert out["pareto"] is None and out["relaxation_information"] is None
    assert out["inconclusive_reasons"]["pruned"] == 6


def test_all_crashes_is_inconclusive():
    cands = [_crasher(f"c{i}") for i in range(10)]
    out = _truth_table(cands, _boom_eval({f"c{i}" for i in range(10)}))
    assert out["verdict"] == "INCONCLUSIVE"
    assert out["pareto"] is None and out["relaxation_information"] is None


def test_all_pruned_is_inconclusive():
    cands = [{"name": f"p{i}", "pruned": True, "pruning_reason": "budget"}
             for i in range(10)]
    out = _truth_table(cands, _ok_eval({}))
    assert out["verdict"] == "INCONCLUSIVE"
    assert out["pareto"] is None and out["relaxation_information"] is None


def test_one_feasible_among_crashes_is_feasible():
    cands = [_cand("good", 42.0)] + [_crasher(f"c{i}") for i in range(9)]
    out = _truth_table(cands, lambda c: _boom_eval({"x"})(c)
                       if c["name"] != "good"
                       else _ok_eval({"good": 42.0})(c))
    assert out["verdict"] == "FEASIBLE"
    assert out["pareto"] is not None


# ── soft vs hard ──────────────────────────────────────────────────────────────

def test_non_binding_requirement_is_recorded_not_enforced():
    req = CompilerRequest(
        requirements=[_req(latency_ceiling_cycles=10.0, binding=False)],
        candidates=[_cand("a", 61.5)],
    )
    out = compile_fabric(req, _ok_eval({"a": 61.5}))
    assert out["verdict"] == "FEASIBLE"  # soft ceiling violated → still feasible
    assert out["request"]["soft_requirements"] and not out["request"]["hard_constraints"]


# ── INVALID_REQUEST: incoherent specs fail closed ────────────────────────────

def test_binding_requirement_without_any_bound_is_invalid():
    with pytest.raises(InvalidCompilerRequest, match="no bound"):
        compile_fabric(CompilerRequest(
            requirements=[_req(latency_ceiling_cycles=None,
                               bandwidth_floor_gbps=None)],
            candidates=[_cand("a", 61.5)]), _ok_eval({"a": 61.5}))


def test_nonpositive_bounds_are_invalid():
    with pytest.raises(InvalidCompilerRequest):
        compile_fabric(CompilerRequest(
            requirements=[_req(latency_ceiling_cycles=0.0)],
            candidates=[_cand("a", 61.5)]), _ok_eval({"a": 61.5}))
    with pytest.raises(InvalidCompilerRequest):
        compile_fabric(CompilerRequest(
            requirements=[_req(bandwidth_floor_gbps=-1.0, latency_ceiling_cycles=None)],
            candidates=[_cand("a", 61.5)]), _ok_eval({"a": 61.5}))


def test_unknown_qos_class_string_fails_closed():
    with pytest.raises(Exception):
        CompilerRequest.from_dict({
            "requirements": [{"qos_class": "turbo", "latency_ceiling_cycles": 50.0,
                              "binding": True}],
            "candidates": [{"name": "a"}],
        })


# ── candidate records preserve the full evidence set ─────────────────────────

def test_pruned_candidates_carried_visibly_and_never_evaluated():
    calls = []

    def eval_spy(cand):
        calls.append(cand["name"])
        return _ok_eval({"a": 61.5})(cand)

    req = CompilerRequest(
        requirements=[_req()],
        candidates=[_cand("a", 61.5), {"name": "p", "topology": "anynet",
                                       "pruned": True,
                                       "pruning_reason": "edge budget exceeded"}],
    )
    out = compile_fabric(req, eval_spy)
    assert calls == ["a"]  # pruned candidate never evaluated
    p = next(c for c in out["candidates"] if c["candidate_id"] == "p")
    assert p["status"] == "PRUNED"
    assert p["pruning_reason"] == "edge budget exceeded"
    assert out["scope"]["pruned"] == 1


def test_search_budget_records_requested_vs_executed():
    req = CompilerRequest(
        requirements=[_req()],
        candidates=[_cand("a", 61.5), _cand("b", 62.0)],
        search_budget={"requested_evaluations": 10},
    )
    out = compile_fabric(req, _ok_eval({"a": 61.5, "b": 62.0}))
    assert out["search_budget"] == {"requested_evaluations": 10, "executed": 2}


def test_evaluation_exception_becomes_failed_candidate_not_crash():
    def raising_eval(cand):
        if cand["name"] == "x":
            raise RuntimeError("binary missing")
        return _ok_eval({"ok1": 30.0})(cand)

    req = CompilerRequest(
        requirements=[_req()],
        candidates=[_cand("x", 0.0), _cand("ok1", 30.0)],
    )
    out = compile_fabric(req, raising_eval)
    x = next(c for c in out["candidates"] if c["candidate_id"] == "x")
    assert x["status"] == "EVALUATION_FAILED"
    assert "binary missing" in x["error"]


# ── provenance / honesty ─────────────────────────────────────────────────────

def test_seed_policy_and_single_sample_basis_stated():
    req = CompilerRequest(
        requirements=[_req()],
        candidates=[_cand("a", 61.5)],
        seed_policy={"seed": 7, "replication": 1},
    )
    out = compile_fabric(req, _ok_eval({"a": 61.5}))
    assert out["request"]["seed_policy"] == {"seed": 7, "replication": 1}
    # n=1 honesty: the verdict must state the sampling basis, never imply CI.
    assert out["request"]["sampling_basis"] == "single_sample_no_confidence_interval"


def test_pareto_uses_real_phase8_gate_mixed_fidelity_refused():
    from veritx_dse.core.comparison import ComparisonSpecError
    req = CompilerRequest(
        requirements=[_req()],
        candidates=[_cand("a", 61.5, fidelity="NETWORK_SIMULATION"),
                    _cand("b", 62.0, fidelity="ANALYTICAL_ESTIMATE")],
    )
    with pytest.raises(ComparisonSpecError):
        compile_fabric(req, _ok_eval({"a": 61.5, "b": 62.0}))


def test_from_dict_round_trip_and_compile():
    d = {
        "requirements": [{"qos_class": "latency_critical",
                          "latency_ceiling_cycles": 100.0, "binding": True}],
        "candidates": [{"name": "a", "topology": "anynet", "seed": 0}],
        "seed_policy": {"seed": 0, "replication": 1},
    }
    req = CompilerRequest.from_dict(d)
    out = compile_fabric(req, _ok_eval({"a": 61.5}))
    assert out["verdict"] == "FEASIBLE"
    assert out["candidates"][0]["seed"] == 0
