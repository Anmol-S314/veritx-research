"""PROMPT 4 — compare normalized federated evidence (Step 7).

Per-metric compatibility (same question + key + unit + dimensional
coordinates + compatible fidelity + acceptable qualification), else
comparable=false with the exact reason and no delta. Cross-model
numbers are labeled MODEL DIFFERENCE, never ranked — the API carries
no cross-model flag, so truthful incomparability IS the cross-model
behavior.

Also the use_candidate gate: a federated study candidate (policy-bound
objectives, provenance rows) still adopts as a DRAFT derived from the
base revision, never mutating it.
"""
from __future__ import annotations

import copy
import sys
import time
from pathlib import Path
from types import SimpleNamespace

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.backend.adapter import (  # noqa: E402
    BackendAssessment, BackendCapability, BackendReadiness, ModelFidelity,
    PreparedExecution, SupportLevel,
)
from veritx_dse.backend.normalized_evidence import (  # noqa: E402
    MetricValue, NormalizedBackendEvidence,
)
from veritx_dse.backend.registry import BackendRegistry  # noqa: E402
from veritx_dse.optimization.candidate import make_candidate  # noqa: E402
from veritx_dse.product.service import (  # noqa: E402
    ProductConfig, ProductService, parse_request_doc,
)

WORKLOAD = "llama-dense-8b-64tiles"
SYSTEM = EvaluationQuestion.SYSTEM_MAKESPAN
EXPOSURE = EvaluationQuestion.COMMUNICATION_EXPOSURE

METRICS = {
    SYSTEM: (("system_makespan_cycles", 6070.0, "cycles"),),
    EXPOSURE: (("communication_exposure_cycles", 1200.0, "cycles"),),
}


class _ScriptedAdapter:
    """Deterministic federation citizen with per-question metric keys."""

    def __init__(self, backend_id="ASTRA2_EMBEDDED_BOOKSIM"):
        self._id = backend_id

    @property
    def backend_id(self) -> str:
        return self._id

    def capabilities(self):
        return tuple(
            BackendCapability(
                question=q, support=SupportLevel.SUPPORTED,
                fidelity=ModelFidelity.SYSTEM_SIMULATION)
            for q in (SYSTEM, EXPOSURE))

    def assess(self, context, question):
        return BackendAssessment(
            backend_id=self._id, question=question,
            support=SupportLevel.SUPPORTED,
            readiness=BackendReadiness.READY,
            fidelity=ModelFidelity.SYSTEM_SIMULATION,
            qualification_profile="SCRIPTED", reason=None,
            required_parents=("design",), limitations=())

    def prepare(self, context, question, **kwargs):
        return PreparedExecution(
            backend_id=self._id, projection_identity="wp-scripted",
            qualification_identity="m-scripted",
            backend_config=None, backend_input=None, producer=None,
            native_prepared=SimpleNamespace(marker=question))

    def execute(self, prepared, options):
        return SimpleNamespace(
            question=prepared.native_prepared.marker,
            evidence_tier="SCRIPTED_TIER",
            expansion_authority="scripted", status="EXECUTED",
            autonomous_injection_packets=0,
            participant_statistics_present=True,
            namespace_binding="SCRIPTED", namespace_id="ns-scripted",
            rank_to_endpoint=((0, 0), (1, 1)),
            aggregate_cycles=1000, aggregate_exposed_comm=100)

    def normalize(self, context, question, prepared, native_result):
        resolved = context.bundle.resolved_fabric.resolved_fabric_hash
        resolved_hash = resolved() if callable(resolved) else resolved
        return NormalizedBackendEvidence(
            backend_id=self._id, question=question,
            model_fidelity=ModelFidelity.SYSTEM_SIMULATION,
            canonical_parent_ids=(
                context.design_hash, resolved_hash,
                context.workload_id, "wp-scripted"),
            native_evidence_id=f"native-{self._id}-{question.value}",
            qualification="SCRIPTED_TIER",
            producer_identity="s" * 64,
            metrics=tuple(
                MetricValue(key=key, value=value, unit=unit,
                            source_metric_key=key)
                for key, value, unit in METRICS[question]),
            limitations=())


def _service(tmp_path, **overrides):
    registry = BackendRegistry((_ScriptedAdapter(
        overrides.pop("backend_id", "ASTRA2_EMBEDDED_BOOKSIM")),))
    overrides.setdefault("projects_root", tmp_path / "projects")
    return ProductService(ProductConfig(**overrides), registry=registry)


def _compiled_revision(svc):
    pid = svc.create_project(name="compare", workload_id=WORKLOAD)[
        "project"]["project_id"]
    compiled = svc.compile_draft(pid)
    assert compiled["compilation"]["status"] == "COMPILED"
    return compiled


def _wait_job(svc, job_id, timeout_s=600):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        job = svc.get_job(job_id)
        if job["state"] in ("COMPLETED", "REFUSED", "FAILED",
                            "CANCELLED"):
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish in time")


def _run(svc, revision_id, **kw):
    job = svc.submit_evaluation(revision_id, **kw)
    done = _wait_job(svc, job["job_id"])
    assert done["state"] == "COMPLETED"
    run = svc.get_run(done["result"]["run_id"])
    assert run["status"] == "EVALUATED"
    return run


# ── Step 7: same model compares; different models do not ───────────────

def test_same_model_rows_are_comparable_with_no_winner(tmp_path):
    svc = _service(tmp_path)
    revision = _compiled_revision(svc)
    run_a = _run(svc, revision["revision_id"],
                 questions=("SYSTEM_MAKESPAN",
                            "COMMUNICATION_EXPOSURE"))
    run_b = _run(svc, revision["revision_id"],
                 questions=("SYSTEM_MAKESPAN",
                            "COMMUNICATION_EXPOSURE"))
    compared = svc.compare(run_a["run_id"], run_b["run_id"])
    assert compared["contract_version"] == 1
    assert compared["compatibility"]["compatible"] is True
    assert len(compared["rows"]) == 2
    for row in compared["rows"]:
        assert row["comparable"] is True
        assert row["reason"] is None
        assert row["a"] == row["b"]
    # no ranking anywhere: no winner, no delta, no verdict
    assert "winner" not in compared
    assert all("delta" not in row and "winner" not in row
               for row in compared["rows"])


def test_different_questions_are_model_difference_not_a_delta(tmp_path):
    """Same run shape, disjoint questions: every row is one-sided and
    names the other side's different question as a MODEL DIFFERENCE."""
    svc = _service(tmp_path)
    revision = _compiled_revision(svc)
    run_system = _run(svc, revision["revision_id"],
                      questions=("SYSTEM_MAKESPAN",))
    run_exposure = _run(svc, revision["revision_id"],
                        questions=("COMMUNICATION_EXPOSURE",))
    compared = svc.compare(run_system["run_id"],
                           run_exposure["run_id"])
    assert compared["rows"]
    for row in compared["rows"]:
        assert row["comparable"] is False
        assert row["reason"]
        # disjoint questions: each row is one-sided; the reason says
        # absence, never a performance claim
        assert "absent" in row["reason"]


def test_same_key_under_different_questions_is_model_difference(
        tmp_path):
    """The sharp case: both sides measure `completion_cycles`, but one
    from NETWORK_COMPLETION and the other per-rank — incomparable with
    the exact questions named."""
    svc = _service(tmp_path)
    revision = _compiled_revision(svc)
    run = _run(svc, revision["revision_id"],
               questions=("SYSTEM_MAKESPAN",))
    side_a = copy.deepcopy(run)
    side_b = copy.deepcopy(run)
    # both sides measure the same key under different questions
    for analysis in side_a["analyses"]:
        for metric in analysis["normalized_metrics"]:
            metric["key"] = "completion_cycles"
    for analysis in side_b["analyses"]:
        analysis["question"] = "PER_RANK_COMPLETION"
        for metric in analysis["normalized_metrics"]:
            metric["key"] = "completion_cycles"
    compared = svc._compare_federated(side_a, side_b)
    assert compared["rows"]
    reasons = " | ".join(row["reason"] or "" for row in compared["rows"])
    for row in compared["rows"]:
        assert row["comparable"] is False
        assert "MODEL DIFFERENCE" in (row["reason"] or "")
    # both questions are named across the rows: neither side's model
    # is presented as the other's performance
    assert "SYSTEM_MAKESPAN" in reasons
    assert "PER_RANK_COMPLETION" in reasons


def test_backend_fidelity_qualification_unit_coords_mismatch(tmp_path):
    svc = _service(tmp_path)
    revision = _compiled_revision(svc)
    run = _run(svc, revision["revision_id"],
               questions=("SYSTEM_MAKESPAN",))

    def _compared(mutator):
        side_a = copy.deepcopy(run)
        side_b = copy.deepcopy(run)
        mutator(side_b)
        return svc._compare_federated(side_a, side_b)["rows"]

    rows = _compared(
        lambda side: side["analyses"].__setitem__(0, {
            **side["analyses"][0],
            "backend_id": "OTHER_BACKEND"}))
    assert rows and all(r["comparable"] is False for r in rows)
    assert "MODEL DIFFERENCE" in rows[0]["reason"]

    rows = _compared(
        lambda side: side["analyses"].__setitem__(0, {
            **side["analyses"][0],
            "model_fidelity": "FULL_SYSTEM_SIMULATION"}))
    assert rows and all(r["comparable"] is False for r in rows)
    assert "model difference" in rows[0]["reason"].lower()

    rows = _compared(
        lambda side: side["analyses"].__setitem__(0, {
            **side["analyses"][0], "qualification": "DIFFERENT"}))
    assert rows and all(r["comparable"] is False for r in rows)
    assert "qualification" in rows[0]["reason"].lower()

    def _reunit(side):
        analysis = copy.deepcopy(side["analyses"][0])
        metrics = copy.deepcopy(analysis["normalized_metrics"])
        metrics[0]["unit"] = "ns"
        analysis["normalized_metrics"] = metrics
        side["analyses"][0] = analysis
    rows = _compared(_reunit)
    assert rows and all(r["comparable"] is False for r in rows)
    assert "unit" in rows[0]["reason"].lower()

    def _redim(side):
        analysis = copy.deepcopy(side["analyses"][0])
        metrics = copy.deepcopy(analysis["normalized_metrics"])
        metrics[0]["dimensions"] = [["rank", "0"]]
        analysis["normalized_metrics"] = metrics
        side["analyses"][0] = analysis
    rows = _compared(_redim)
    assert rows and all(r["comparable"] is False for r in rows)
    assert "absent" in rows[0]["reason"].lower()


# ── use_candidate still yields a draft from the base revision ───────────

def _federated_study_record(svc, pid, revision, patch):
    base = parse_request_doc(revision["request"])
    candidate = make_candidate(base, patch)
    return {
        "schema_version": 1,
        "optimization_id": "opt-federated-1",
        "project_id": pid,
        "base_revision_id": revision["revision_id"],
        "created_at": "t",
        "definition": {
            "domain": [{"name": "link_width", "values": [32, 64]}],
            "objectives": [
                {"metric": "system_makespan_cycles",
                 "direction": "MIN", "question": "SYSTEM_MAKESPAN",
                 "backend_id": "ASTRA2_EMBEDDED_BOOKSIM"}],
            "constraints": [], "method": "grid",
            "budget": {}, "selection": "min_first_objective",
            "seed": None},
        "study": {
            "contract_version": 2,
            "candidates": [{
                "candidate_id": candidate.candidate_id,
                "guided_patch": dict(candidate.guided_patch),
                "design_hash": candidate.request.design_hash(),
                "compilation_status": "COMPILED",
                "evaluation_status": "EVALUATED",
                "objective_provenance": [{
                    "metric_key": "system_makespan_cycles",
                    "question": "SYSTEM_MAKESPAN",
                    "backend_id": "ASTRA2_EMBEDDED_BOOKSIM",
                    "model_fidelity": "SYSTEM_SIMULATION",
                    "qualification": "SCRIPTED_TIER",
                    "native_evidence_id": "native-x",
                    "unit": "cycles", "value": 6070.0}],
            }],
            "selected_candidate_id": candidate.candidate_id,
        },
        "candidate_runs": [],
        "selected_candidate_id": candidate.candidate_id,
    }, candidate


def test_use_candidate_adopts_federated_candidate_as_draft(tmp_path):
    """Gate: use_candidate semantics unchanged — the selected
    federated candidate becomes a DRAFT derived from the base
    revision; the base revision itself is never mutated and an
    explicit compile is still required for a new revision."""
    svc = _service(tmp_path)
    revision = _compiled_revision(svc)
    pid = revision["project_id"]
    rid = revision["revision_id"]
    stored = svc.store.load_revision(pid, rid)
    before = copy.deepcopy(stored)
    record, candidate = _federated_study_record(
        svc, pid, stored, {"link_width": 64})
    svc.store.create_optimization(pid, record)

    draft = svc.use_candidate("opt-federated-1",
                              candidate.candidate_id)
    assert draft["derived_from_optimization_id"] == "opt-federated-1"
    assert draft["derived_from_candidate_id"] == candidate.candidate_id
    assert draft["adopted_from_revision_id"] == rid

    # the base revision is byte-identical: adoption wrote the draft,
    # never the revision
    after = svc.store.load_revision(pid, rid)
    assert after["design_hash"] == before["design_hash"]
    assert after["request"] == before["request"]
    # the draft IS the studied design (identity, not resemblance)
    adopted = parse_request_doc(
        svc.store.load_draft(pid)["request"])
    assert adopted.design_hash() == candidate.request.design_hash()
    # and it is still a draft: no new revision exists yet
    assert [r["revision_id"] for r in
            svc.store.list_revisions(pid)] == [rid]
