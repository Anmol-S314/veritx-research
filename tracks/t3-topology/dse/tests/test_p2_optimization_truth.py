"""P1-RT.A8 — mandatory adversarial suite for optimization truth.

One test per mandated case:

 1 real evaluator + missing objective -> UNMEASURABLE/ineligible, no KeyError
 2 missing-objective candidate never Pareto
 3 report identity carried into CandidateRecord
 4 changing verdict/authority changes report identity
 5 transplanted requirement provenance refuses (or moves result identity)
 6 product requirements vs optimization constraints stay separate
 7 VIOLATED survives the study view
 8 UNMEASURABLE survives the study view
 9 duplicate same-metric constraints do not overwrite
10 duplicate objective declaration refuses
11 same evaluator object, same candidate, twice
12 same CLI run root twice immediately, no sleep
13 repeated runs preserve candidate/design identity
14 repeated runs allocate distinct slots

Real-BookSim tests use the vendored binary through the qualified
producer; everything else uses stub ports so the adversarial property is
isolated from backend behavior.
"""
from __future__ import annotations

import argparse
import hashlib
import json

import pytest

from test_p1_optimize_booksim import _fixture as _cli_fixture
from test_p2_real_adapter import _base as _real_base
from test_p2_real_adapter import _port as _real_port

from veritx_dse.application.requirements import report_identity
from veritx_dse.optimization.constraints import (
    ConstraintError,
    evaluate_all,
)
from veritx_dse.optimization.definition import (
    Constraint,
    DomainParam,
    Objective,
    OptimizationDefinition,
    OptimizationDefinitionError,
)
from veritx_dse.optimization.evaluators import (
    CandidateEvaluation,
    FakeDeterministicEvaluator,
)
from veritx_dse.optimization.result import (
    OptimizationResultError,
    Optimizer,
)


# ── stub ports ───────────────────────────────────────────────────────────

def _report_for(design_hash: str, *, verdict: str = "SATISFIED",
                authority: str = "test", perf: str = "perf:fixed") -> dict:
    return {
        "contract_version": 1,
        "design_hash": design_hash,
        "performance_result_id": perf,
        "entries": [{
            "requirement_index": 0,
            "traffic_class": "tp_collective",
            "qos_class": "latency_critical",
            "verdict": verdict,
            "binding": True,
            "required": 600.0,
            "measured": 10.0,
            "metric_authority": authority,
            "performance_result_id": perf,
            "reason": "adversarial-suite",
        }],
    }


class _StubPort:
    """EVALUATED candidate with given values and an optional report."""

    def __init__(self, values, *, report_verdict=None, authority="test"):
        self.values = values
        self.report_verdict = report_verdict
        self.authority = authority

    def evaluate(self, candidate):
        report = None
        if self.report_verdict is not None:
            report = _report_for(
                "sha256:" + candidate.request.design_hash(),
                verdict=self.report_verdict, authority=self.authority)
        return CandidateEvaluation(
            candidate_id=candidate.candidate_id,
            design_hash=candidate.request.design_hash(),
            status="EVALUATED",
            objective_values=dict(self.values),
            locked_consequences={},
            performance_result_id="perf:fixed" if report else None,
            requirement_report=report,
            requirement_report_id=(report_identity(report)
                                   if report is not None else None))


class _ForeignReportPort:
    """Returns another design's report under this candidate's identity."""

    def evaluate(self, candidate):
        foreign = "ab" * 32
        return CandidateEvaluation(
            candidate_id=candidate.candidate_id,
            design_hash=candidate.request.design_hash(),
            status="EVALUATED",
            objective_values={"latency": 10.0},
            locked_consequences={},
            performance_result_id="perf:foreign",
            requirement_report=_report_for("sha256:" + foreign,
                                           perf="perf:foreign"),
            requirement_report_id="forged")


def _defn(**kw):
    base = dict(
        domain=(DomainParam("link_width", (32, 128)),),
        objectives=(Objective("latency", "MIN"),),
        method="grid")
    base.update(kw)
    return OptimizationDefinition(**base)


# ── 1-2: missing objective with the REAL evaluator ──────────────────────

def test_1_missing_objective_unmeasurable_ineligible_no_keyerror(tmp_path):
    result = Optimizer().optimize(
        _real_base(), _defn(objectives=(Objective("area", "MIN"),)),
        _real_port(tmp_path))
    assert len(result.records) == 2
    for record in result.records:
        assert record.evaluation_status == "EVALUATED"
        assert record.pareto_eligible is False
        assert record.objective_availability["area"] == "UNMEASURABLE"
        assert "area" not in record.objective_values
        entries = [dict(d) for d in record.objective_details
                   if d["metric"] == "area"]
        assert entries and entries[0]["state"] == "UNMEASURABLE"


def test_2_missing_objective_candidate_never_pareto(tmp_path):
    result = Optimizer().optimize(
        _real_base(), _defn(objectives=(Objective("area", "MIN"),)),
        _real_port(tmp_path))
    assert result.pareto_ids == ()
    assert result.selected_candidate_id is None
    assert all(r.pareto_member is False for r in result.records)
    assert "area" in (result.selection_rationale or "")


# ── 3-4: report identity transitively carried ───────────────────────────

def test_3_report_identity_in_candidate_record():
    result = Optimizer().optimize(
        _real_base(), _defn(), _StubPort({"latency": 10.0},
                                         report_verdict="SATISFIED"))
    assert result.records
    for record in result.records:
        assert record.requirement_report_id
        assert record.product_requirements_satisfied is True
        assert record.product_requirement_details
    # The bound result identity moves when the report identity moves.
    good = Optimizer().optimize(
        _real_base(), _defn(), _StubPort({"latency": 10.0},
                                         report_verdict="SATISFIED"))
    flipped = Optimizer().optimize(
        _real_base(), _defn(), _StubPort({"latency": 10.0},
                                         report_verdict="VIOLATED"))
    assert good.result_id() != flipped.result_id()


def test_4_changing_verdict_or_authority_moves_report_identity():
    base = _report_for("sha256:" + "cd" * 32)
    base_id = report_identity(base)
    # Every field the report contract binds must move the identity:
    # top-level provenance, per-entry verdict evidence, and per-entry
    # scope. No repr/object identity is involved (canonical JSON only).
    top_level = {
        "design_hash": "sha256:" + "ef" * 32,
        "performance_result_id": "perf:other",
    }
    entries = {
        "requirement_index": 1,
        "traffic_class": "dp_collective",
        "qos_class": "bandwidth_critical",
        "verdict": "VIOLATED",
        "binding": False,
        "required": 601.0,
        "measured": 11.0,
        "metric_authority": "another-authority",
        "performance_result_id": "perf:entry-other",
        "reason": "another reason",
    }
    for field, value in top_level.items():
        mutated = json.loads(json.dumps(base))
        mutated[field] = value
        assert report_identity(mutated) != base_id, field
    for field, value in entries.items():
        mutated = json.loads(json.dumps(base))
        mutated["entries"][0][field] = value
        assert report_identity(mutated) != base_id, field


# ── 5: transplant refusal ───────────────────────────────────────────────

def test_5_transplanted_requirement_provenance_refuses():
    with pytest.raises(OptimizationResultError, match="transplanted"):
        Optimizer().optimize(_real_base(), _defn(), _ForeignReportPort())
    # A report whose design_hash belongs to THIS candidate but whose
    # carried identity is forged is refused too (never trusted).
    class _ForgedIdentity(_ForeignReportPort):
        def evaluate(self, candidate):
            report = _report_for("sha256:" + candidate.request.design_hash(),
                                 perf="perf:foreign")
            return CandidateEvaluation(
                candidate_id=candidate.candidate_id,
                design_hash=candidate.request.design_hash(),
                status="EVALUATED",
                objective_values={"latency": 10.0},
                locked_consequences={},
                performance_result_id="perf:foreign",
                requirement_report=report,
                requirement_report_id="forged")
    with pytest.raises(OptimizationResultError, match="forged"):
        Optimizer().optimize(_real_base(), _defn(), _ForgedIdentity())


# ── 6: separate authorities ─────────────────────────────────────────────

def test_6_product_requirements_and_constraints_stay_separate():
    defn = _defn(constraints=(Constraint("latency", "<=", 5.0),))
    # Product passes, study constraint fails.
    product_ok = Optimizer().optimize(
        _real_base(), defn,
        _StubPort({"latency": 10.0}, report_verdict="SATISFIED"))
    for r in product_ok.records:
        assert r.product_requirements_satisfied is True
        assert r.constraints_satisfied is False
        assert r.constraint_verdicts["latency"] == "VIOLATED"
        assert r.pareto_eligible is False
    # Product binding fails, study constraint passes.
    constraint_ok = Optimizer().optimize(
        _real_base(), _defn(),
        _StubPort({"latency": 10.0}, report_verdict="VIOLATED"))
    for r in constraint_ok.records:
        assert r.product_requirements_satisfied is False
        assert r.constraints_satisfied is True
        assert r.pareto_eligible is False
    # The two authorities answer different questions in one record.
    both = Optimizer().optimize(
        _real_base(), _defn(constraints=(Constraint("latency", "<=", 600.0),)),
        _StubPort({"latency": 10.0}, report_verdict="SATISFIED"))
    for r in both.records:
        assert r.product_requirements_satisfied is True
        assert r.constraints_satisfied is True
        assert r.pareto_eligible is True


# ── 7-8: three-state study semantics survive ────────────────────────────

def test_7_violated_survives_study_view():
    result = Optimizer().optimize(
        _real_base(),
        _defn(constraints=(Constraint("latency", "<=", 1.0),)),
        FakeDeterministicEvaluator(seed=7))
    view = result.to_study_view()
    assert view["contract_version"] == 2
    for cand in view["candidates"]:
        assert cand["constraint_verdicts"]["latency"] == "VIOLATED"
        assert cand["pareto_eligible"] is False
    legacy = result.to_study_view(contract_version=1)
    for cand in legacy["candidates"]:
        assert cand["constraint_verdicts"]["latency"] is False


def test_8_unmeasurable_survives_study_view():
    result = Optimizer().optimize(
        _real_base(),
        _defn(constraints=(Constraint("energy", "<=", 1.0),)),
        FakeDeterministicEvaluator(seed=7))
    view = result.to_study_view()
    assert view["contract_version"] == 2
    for cand in view["candidates"]:
        assert cand["constraint_verdicts"]["energy"] == "UNMEASURABLE"
    legacy = result.to_study_view(contract_version=1)
    for cand in legacy["candidates"]:
        # v1 booleans are LOSSY by design: UNMEASURABLE collapses to
        # false; only v2 preserves the distinction.
        assert cand["constraint_verdicts"]["energy"] is False


# ── 9-10: duplicate identity refuses ────────────────────────────────────

def test_9_duplicate_same_metric_constraints_do_not_overwrite():
    with pytest.raises(OptimizationDefinitionError,
                       match="duplicate constraint"):
        _defn(constraints=(Constraint("latency", "<=", 100.0),
                           Constraint("latency", ">=", 50.0)))
    with pytest.raises(ConstraintError, match="duplicate constraint"):
        evaluate_all((Constraint("latency", "<=", 100.0),
                      Constraint("latency", ">=", 50.0)),
                     {"latency": 75.0})


def test_10_duplicate_objective_declaration_refuses():
    with pytest.raises(OptimizationDefinitionError,
                       match="duplicate objective"):
        _defn(objectives=(Objective("latency", "MIN"),
                          Objective("latency", "MAX")))


# ── 11: same evaluator object, same candidate, twice ────────────────────

def test_11_same_evaluator_same_candidate_twice(tmp_path):
    from veritx_dse.optimization.candidate import make_candidate
    port = _real_port(tmp_path)
    cand = make_candidate(_real_base(), {"link_width": 64})
    first = port.evaluate(cand)
    second = port.evaluate(cand)
    assert first.status == second.status == "EVALUATED"
    assert first.candidate_id == second.candidate_id
    assert first.design_hash == second.design_hash == \
        cand.request.design_hash()
    assert first.objective_values == second.objective_values
    slots = sorted(p for p in (tmp_path / "runs" / cand.candidate_id).iterdir()
                   if p.is_dir())
    assert len(slots) == 2
    assert all(p.name.startswith("eval-") for p in slots)


# ── 12-14: same CLI run root, immediately, no sleep ─────────────────────

def _cli_args(fixture, study_out, run_root):
    return argparse.Namespace(
        fixture=fixture, search="grid", link_widths="64,128",
        concentrations="1", latency_ceiling=None, max_candidates=None,
        study_out=study_out, evaluate="booksim", binary=None,
        network_clock_hz=10 ** 9, run_root=run_root, timeout=600, seed=7)


@pytest.fixture(scope="module")
def two_cli_runs(tmp_path_factory):
    """Two immediate CLI studies against ONE explicit run root (no sleep)."""
    from veritx_dse.cli.cli import cmd_optimize
    from veritx_dse.core.logging import Ctx
    work = tmp_path_factory.mktemp("rt-a8-cli")
    fixture = _cli_fixture(work)
    shared_root = work / "runs"
    views = []
    for tag in ("a", "b"):
        study_out = work / f"study-{tag}.json"
        ctx = Ctx(verbosity=0)
        cmd_optimize(ctx, _cli_args(fixture, str(study_out),
                                    str(shared_root)))
        assert not ctx.failed
        views.append(json.loads(study_out.read_text()))
    return shared_root, views[0], views[1]


def test_12_same_cli_run_root_twice_immediately(two_cli_runs):
    shared_root, first, second = two_cli_runs
    assert first["candidates"] and second["candidates"]
    assert first["pareto_ids"] and second["pareto_ids"]
    tokens = sorted(p for p in shared_root.iterdir() if p.is_dir())
    assert len(tokens) == 2, [p.name for p in tokens]
    assert tokens[0].name != tokens[1].name


def test_13_repeated_runs_preserve_candidate_design_identity(two_cli_runs):
    _, first, second = two_cli_runs
    assert [c["candidate_id"] for c in first["candidates"]] == \
        [c["candidate_id"] for c in second["candidates"]]
    assert [c["evaluation_ids"]["design_hash"]
            for c in first["candidates"]] == \
        [c["evaluation_ids"]["design_hash"]
         for c in second["candidates"]]


def test_14_repeated_runs_allocate_distinct_slots(two_cli_runs):
    shared_root, _, _ = two_cli_runs
    tokens = sorted(p for p in shared_root.iterdir() if p.is_dir())
    digests = []
    for token in tokens:
        found = sorted(
            hashlib.sha256(p.read_bytes()).hexdigest()
            for p in token.rglob("evidence/*.json"))
        assert found, token
        digests.append(found)
    assert digests[0] != digests[1]
