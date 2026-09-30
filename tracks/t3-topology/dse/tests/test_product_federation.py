"""PROMPT 2 — the product federation workflow.

The sealed BookSim+ASTRA federation as a product resource: plan truth
per question, explicit-backend honesty, unavailable-means-unavailable
execution, independent per-analysis outcomes with shared canonical
parents, and backward-compatible network-only evaluation.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

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
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.product.service import (  # noqa: E402
    ProductConfig, ProductService, parse_request_doc,
)

WORKLOAD = "llama-dense-8b-64tiles"
SMALL = REPO / "tracks/t3-topology/examples/dense_1b_16tiles-v3.json"

NETWORK = EvaluationQuestion.NETWORK_COMPLETION
SYSTEM = EvaluationQuestion.SYSTEM_MAKESPAN

class _ScriptedAdapter:
    """A deterministic federation citizen for product-level tests."""

    def __init__(self, backend_id, questions, *,
                 readiness=BackendReadiness.READY,
                 support=SupportLevel.SUPPORTED,
                 reason=None, fail_execute=None):
        self._id = backend_id
        self._questions = tuple(questions)
        self._readiness = readiness
        self._support = support
        self._reason = reason
        self._fail_execute = fail_execute
        self.executed: list[EvaluationQuestion] = []

    @property
    def backend_id(self) -> str:
        return self._id

    def capabilities(self):
        return tuple(
            BackendCapability(
                question=q, support=SupportLevel.SUPPORTED,
                fidelity=ModelFidelity.SYSTEM_SIMULATION)
            for q in self._questions)

    def assess(self, context, question):
        if question not in self._questions:
            return BackendAssessment(
                backend_id=self._id, question=question,
                support=SupportLevel.UNSUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=ModelFidelity.SYSTEM_SIMULATION,
                qualification_profile=None,
                reason=f"{self._id} answers system questions only",
                required_parents=("design",),
                limitations=())
        return BackendAssessment(
            backend_id=self._id, question=question,
            support=self._support,
            readiness=self._readiness,
            fidelity=ModelFidelity.SYSTEM_SIMULATION,
            qualification_profile="SCRIPTED",
            reason=self._reason,
            required_parents=("design",),
            limitations=())

    def prepare(self, context, question, **kwargs):
        return PreparedExecution(
            backend_id=self._id, projection_identity="wp-scripted",
            qualification_identity="m-scripted",
            backend_config=None, backend_input=None, producer=None,
            native_prepared=SimpleNamespace(marker=question))

    def execute(self, prepared, options):
        self.executed.append(prepared.native_prepared.marker)
        if self._fail_execute is not None:
            raise self._fail_execute
        question = prepared.native_prepared.marker
        return SimpleNamespace(
            question=question, evidence_tier="SCRIPTED_TIER",
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
            metrics=(MetricValue(
                key="system_makespan_cycles", value=1000.0,
                unit="cycles", source_metric_key="aggregate_cycles"),),
            limitations=())

def _service(tmp_path: Path, registry=None, **config_kw) -> ProductService:
    config_kw.setdefault("projects_root", tmp_path / "projects")
    return ProductService(ProductConfig(**config_kw), registry=registry)

def _compiled_revision(svc: ProductService) -> dict:
    pid = svc.create_project(name="federation", workload_id=WORKLOAD)[
        "project"]["project_id"]
    compiled = svc.compile_draft(pid)
    assert compiled["compilation"]["status"] == "COMPILED"
    assert compiled["certificate"]["overall"] == "PASS"
    return compiled

def _wait_job(svc: ProductService, job_id: str,
              timeout_s: int = 600) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        job = svc.get_job(job_id)
        if job["state"] in ("COMPLETED", "REFUSED", "FAILED",
                            "CANCELLED"):
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish in time")

def test_plan_routes_dense_revision_across_backends(tmp_path):
    svc = _service(tmp_path)
    revision = _compiled_revision(svc)
    plan = svc.evaluation_plan(revision["revision_id"])
    rows = {row["question"]: row for row in plan["analyses"]}
    assert set(rows) == {q.value for q in EvaluationQuestion}
    assert rows["NETWORK_COMPLETION"]["backend"] == "BOOKSIM_STANDALONE"
    for question in ("SYSTEM_MAKESPAN", "COMMUNICATION_EXPOSURE",
                     "PER_RANK_COMPLETION"):
        assert rows[question]["backend"] == "ASTRA2_EMBEDDED_BOOKSIM"
    assert plan["design_hash"] == revision["design_hash"]
    assert plan["revision_id"] == revision["revision_id"]
    for row in plan["analyses"]:
        assert row["support"] in ("SUPPORTED", "CONDITIONAL",
                                  "UNSUPPORTED")
        assert row["readiness"] in ("READY", "BLOCKED", "UNAVAILABLE")

def test_explicit_backend_selection_is_honest(tmp_path):
    svc = _service(tmp_path)
    revision = _compiled_revision(svc)
    rid = revision["revision_id"]
    network_booksim = svc.evaluation_plan(
        rid, questions=("NETWORK_COMPLETION",),
        requested_backend="BOOKSIM_STANDALONE")
    assert network_booksim["analyses"][0]["backend"] == \
        "BOOKSIM_STANDALONE"
    system_astra = svc.evaluation_plan(
        rid, questions=("SYSTEM_MAKESPAN",),
        requested_backend="ASTRA2_EMBEDDED_BOOKSIM")
    assert system_astra["analyses"][0]["backend"] == \
        "ASTRA2_EMBEDDED_BOOKSIM"

def test_explicit_astra_for_network_is_unsupported_without_fallback(
        tmp_path):
    svc = _service(tmp_path)
    revision = _compiled_revision(svc)
    plan = svc.evaluation_plan(
        revision["revision_id"], questions=("NETWORK_COMPLETION",),
        requested_backend="ASTRA2_EMBEDDED_BOOKSIM")
    row = plan["analyses"][0]
    assert row["backend"] is None
    assert row["support"] == "UNSUPPORTED"

def test_missing_astra_binary_is_unavailable(tmp_path):
    svc = _service(
        tmp_path, booksim_bin=tmp_path / "no-booksim",
        astra_bin=tmp_path / "no-astra")
    revision = _compiled_revision(svc)
    plan = svc.evaluation_plan(
        revision["revision_id"], questions=("SYSTEM_MAKESPAN",))
    row = plan["analyses"][0]
    assert row["backend"] == "ASTRA2_EMBEDDED_BOOKSIM"
    assert row["readiness"] == "UNAVAILABLE"

def test_unknown_question_and_backend_are_typed_refusals(tmp_path):
    from veritx_dse.application.errors import ControlPlaneError
    svc = _service(tmp_path)
    revision = _compiled_revision(svc)
    with pytest.raises(ControlPlaneError):
        svc.evaluation_plan(revision["revision_id"],
                            questions=("NO_SUCH_QUESTION",))
    with pytest.raises(ControlPlaneError):
        svc.evaluation_plan(revision["revision_id"],
                            requested_backend="NO_SUCH_BACKEND")

def _federated_service(tmp_path: Path, **overrides) -> ProductService:
    astra = _ScriptedAdapter(
        "ASTRA2_EMBEDDED_BOOKSIM",
        (EvaluationQuestion.SYSTEM_MAKESPAN,
         EvaluationQuestion.COMMUNICATION_EXPOSURE),
        **overrides)
    registry = BackendRegistry((astra,))
    return _service(tmp_path, registry=registry), astra

def _submit_and_finish(svc, revision_id, **kw):
    job = svc.submit_evaluation(revision_id, **kw)
    return _wait_job(svc, job["job_id"])

def test_multi_question_execution_has_independent_outcomes(tmp_path):
    svc, astra = _federated_service(tmp_path)
    revision = _compiled_revision(svc)
    job = _submit_and_finish(
        svc, revision["revision_id"],
        questions=("SYSTEM_MAKESPAN", "COMMUNICATION_EXPOSURE"))
    assert job["state"] == "COMPLETED"
    run = svc.get_run(job["result"]["run_id"])
    assert run["status"] == "EVALUATED"
    by_question = {a["question"]: a for a in run["analyses"]}
    assert set(by_question) == {"SYSTEM_MAKESPAN",
                                "COMMUNICATION_EXPOSURE"}
    for analysis in by_question.values():
        assert analysis["status"] == "EVALUATED"
        assert analysis["backend_id"] == "ASTRA2_EMBEDDED_BOOKSIM"
        assert analysis["native_evidence_id"] is not None
        assert analysis["normalized_metrics"]
    assert sorted(q.value for q in astra.executed) == [
        "COMMUNICATION_EXPOSURE", "SYSTEM_MAKESPAN"]
    parents = [tuple(a["native_evidence_id"] for a in [by_question[q]])
               for q in by_question]
    assert len(parents) == 2
    plan = run["evaluation_plan"]
    assert plan["design_hash"] == run["design_hash"]

def test_partial_execution_when_one_leg_refuses(tmp_path):
    svc, astra = _federated_service(tmp_path)
    revision = _compiled_revision(svc)
    job = _submit_and_finish(
        svc, revision["revision_id"],
        questions=("SYSTEM_MAKESPAN", "PER_RANK_COMPLETION"))
    assert job["state"] == "COMPLETED"
    run = svc.get_run(job["result"]["run_id"])
    assert run["status"] == "PARTIAL"
    by_question = {a["question"]: a for a in run["analyses"]}
    assert by_question["SYSTEM_MAKESPAN"]["status"] == "EVALUATED"
    assert by_question["PER_RANK_COMPLETION"]["status"] == "UNSUPPORTED"
    assert by_question["PER_RANK_COMPLETION"]["backend_id"] is None
    assert run["reason"] is not None

def test_failed_execution_is_failed_not_infeasible(tmp_path):
    from veritx_dse.backend.astra_execution import AstraExecutionError
    svc, _ = _federated_service(
        tmp_path, fail_execute=AstraExecutionError("boom"))
    revision = _compiled_revision(svc)
    job = _submit_and_finish(
        svc, revision["revision_id"], questions=("SYSTEM_MAKESPAN",))
    run = svc.get_run(job["result"]["run_id"])
    assert run["status"] == "FAILED"
    assert run["analyses"][0]["status"] == "FAILED"

def test_unavailable_backend_is_not_fabricated(tmp_path):
    svc = _service(
        tmp_path, booksim_bin=tmp_path / "no-booksim",
        astra_bin=tmp_path / "no-astra")
    revision = _compiled_revision(svc)
    job = _submit_and_finish(
        svc, revision["revision_id"], questions=("SYSTEM_MAKESPAN",))
    assert job["state"] == "REFUSED"
    run = svc.get_run(job["result"]["run_id"])
    assert run["status"] == "BACKEND_UNAVAILABLE"
    analysis = run["analyses"][0]
    assert analysis["status"] == "BACKEND_UNAVAILABLE"
    assert analysis["normalized_metrics"] is None
    assert analysis["native_evidence_id"] is None

def test_native_evidence_ids_exist_for_successful_analyses(tmp_path):
    svc, _ = _federated_service(tmp_path)
    revision = _compiled_revision(svc)
    job = _submit_and_finish(
        svc, revision["revision_id"], questions=("SYSTEM_MAKESPAN",))
    run = svc.get_run(job["result"]["run_id"])
    analysis = run["analyses"][0]
    assert analysis["native_evidence_id"] == \
        "native-ASTRA2_EMBEDDED_BOOKSIM-SYSTEM_MAKESPAN"

def test_run_bundle_seals_the_federated_layout(tmp_path):
    from veritx_dse.core.run_bundle import verify_run_bundle
    svc, _ = _federated_service(tmp_path)
    revision = _compiled_revision(svc)
    job = _submit_and_finish(
        svc, revision["revision_id"], questions=("SYSTEM_MAKESPAN",))
    run = svc.get_run(job["result"]["run_id"])
    bundle_dir = svc.store.run_bundle_dir(
        run["project_id"], run["run_id"])
    assert (bundle_dir / "plan.json").is_file()
    assert (bundle_dir / "normalized-evidence.json").is_file()
    summary = verify_run_bundle(bundle_dir)
    assert summary["bundle_id"] == run["bundle_id"][len("sha256:"):]
    verified = svc.verify_run(run["run_id"])
    assert verified["status"] == "VERIFIED"

def test_astra_integrity_reports_facts_not_packets(tmp_path):
    svc, _ = _federated_service(tmp_path)
    revision = _compiled_revision(svc)
    job = _submit_and_finish(
        svc, revision["revision_id"], questions=("SYSTEM_MAKESPAN",))
    run = svc.get_run(job["result"]["run_id"])
    integrity = svc.run_integrity(run["run_id"])
    assert integrity["packet_conservation"] is None
    assert integrity["route_realization"] is None
    entry = integrity["analyses"]["system_makespan"]
    assert entry["backend"] == "ASTRA2_EMBEDDED_BOOKSIM"
    assert entry["evidence_tier"] == "SCRIPTED_TIER"
    assert entry["autonomous_injection_packets"] == 0
    assert entry["namespace_binding"] == "SCRIPTED"
    assert "packet_conservation" not in entry

def test_reproduction_not_available_without_archived_inputs(tmp_path):
    svc, _ = _federated_service(tmp_path)
    revision = _compiled_revision(svc)
    job = _submit_and_finish(
        svc, revision["revision_id"], questions=("SYSTEM_MAKESPAN",))
    run = svc.get_run(job["result"]["run_id"])
    assert run["status"] == "EVALUATED"
    rep = _wait_job(svc, svc.submit_reproduction(
        run["run_id"])["job_id"])
    assert rep["state"] == "COMPLETED"
    entry = rep["result"]["reproductions"]["system_makespan"]
    assert entry["backend"] == "ASTRA2_EMBEDDED_BOOKSIM"
    assert entry["outcome"] == "REPRODUCTION_NOT_AVAILABLE"

def _astra_binary_present() -> bool:
    from veritx_dse.backend.astra import resolve_runtime_binary
    return resolve_runtime_binary() is not None

@pytest.mark.skipif(not _astra_binary_present(),
                    reason="no ASTRA runtime binary in this worktree")
def test_live_astra_evaluation_reproduces(tmp_path):
    """Real ASTRA run through the product, then rerun of the exact
    stored inputs: SCIENTIFICALLY_REPRODUCED with a stable identity."""
    svc = _service(tmp_path)
    revision = _compiled_revision(svc)
    job = _submit_and_finish(
        svc, revision["revision_id"], questions=("SYSTEM_MAKESPAN",))
    run = svc.get_run(job["result"]["run_id"])
    assert run["status"] == "EVALUATED"
    analysis = run["analyses"][0]
    assert analysis["native_evidence_id"] is not None
    rep = _wait_job(svc, svc.submit_reproduction(
        run["run_id"])["job_id"], timeout_s=900)
    assert rep["state"] == "COMPLETED"
    entry = rep["result"]["reproductions"]["system_makespan"]
    assert entry["outcome"] == "SCIENTIFICALLY_REPRODUCED", entry
    assert entry["evidence_id"] == analysis["native_evidence_id"]

def test_compare_marks_model_difference_not_a_winner(tmp_path):
    svc, _ = _federated_service(tmp_path)
    revision = _compiled_revision(svc)
    first = _submit_and_finish(
        svc, revision["revision_id"], questions=("SYSTEM_MAKESPAN",))
    second = _submit_and_finish(
        svc, revision["revision_id"],
        questions=("COMMUNICATION_EXPOSURE",))
    comparison = svc.compare(first["result"]["run_id"],
                             second["result"]["run_id"])
    assert comparison["contract_version"] == 1
    assert comparison["rows"] == [] or all(
        r["comparable"] is False for r in comparison["rows"])

def test_compare_matches_identical_normalized_metrics(tmp_path):
    svc, _ = _federated_service(tmp_path)
    revision = _compiled_revision(svc)
    first = _submit_and_finish(
        svc, revision["revision_id"], questions=("SYSTEM_MAKESPAN",))
    second = _submit_and_finish(
        svc, revision["revision_id"], questions=("SYSTEM_MAKESPAN",))
    comparison = svc.compare(first["result"]["run_id"],
                             second["result"]["run_id"])
    makespan = [r for r in comparison["rows"]
                if r["key"] == "system_makespan_cycles"]
    assert len(makespan) == 1
    assert makespan[0]["comparable"] is True
    assert makespan[0]["reason"] is None
    assert makespan[0]["a"] == makespan[0]["b"] == 1000.0
