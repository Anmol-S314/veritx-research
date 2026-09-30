"""Runner tests with a stubbed ProductService — no backends needed."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tracks" / "t3-topology" / "dse"))

import veritx_campaign as campaign  # noqa: E402

class _StubService:
    """Scripted ProductService double: submit -> job -> serving record."""

    def __init__(self, *, job_state="COMPLETED", evidence=None,
                 error=("REFUSED_CODE", "scripted refusal"),
                 submit_error=None):
        self.job_state = job_state
        self.evidence = evidence
        self.error = error
        self.submit_error = submit_error
        self.submitted = []

    def create_project(self, *, name):
        return {"project": {"project_id": "p-stub"}}

    def submit_serving(self, project_id, body):
        self.submitted.append((project_id, body))
        if self.submit_error is not None:
            raise self.submit_error
        return {"job_id": "job-stub"}

    def get_job(self, job_id):
        assert job_id == "job-stub"
        job = {"job_id": job_id, "state": self.job_state, "result": None,
               "error_code": None, "error_message": None}
        if self.job_state == "COMPLETED":
            job["result"] = {"serving_id": "sv-stub"}
        else:
            job["error_code"], job["error_message"] = self.error
        return job

    def get_serving(self, serving_id):
        assert serving_id == "sv-stub"
        return {"serving_id": serving_id, "evidence": self.evidence}

def _evidence(**over):
    doc = {
        "request_count": 3,
        "requests_expected": 3,
        "rounds": 2,
        "instance_count": 1,
        "instances_with_completions": [0],
        "request_metrics": [
            ["r0", 100, 500, 40],
            ["r1", 200, 800, 60],
            ["r2", None, None, 0],
        ],
        "backend_evidence_ids": ["sha256:abc"],
        "machine_id": "m",
        "namespace_id": "n",
    }
    base = {
        "request_count": 3,
        "requests_expected": 3,
        "rounds": 2,
        "machine_id": "m",
        "namespace_id": "n",
        "evidence_ids": ["sha256:abc"],
        "document": doc,
    }
    base.update(over)
    return base

def test_completed_experiment_collects_native_metrics():
    svc = _StubService(evidence=_evidence())
    row = campaign.run_experiment(svc, "p-stub", "demo", "c.json", "d.jsonl",
                                  3)
    assert row["status"] == "COMPLETED"
    metrics = row["metrics"]
    assert metrics["requests_completed"] == 3
    assert metrics["ttft_cycles"]["n"] == 2
    assert metrics["ttft_cycles"]["mean"] == 150.0
    assert metrics["completion_cycles"]["p50"] == 500.0
    assert metrics["makespan_cycles"] == 800.0
    assert metrics["output_tokens_total"] == 100.0
    assert metrics["tokens_per_kilocycle"] == 100.0 / 800.0 * 1000.0
    assert metrics["prefill_cycles"] is None
    assert metrics["network_cycles"] is None

def test_refused_job_records_reason_not_metrics():
    svc = _StubService(job_state="REFUSED")
    row = campaign.run_experiment(svc, "p-stub", "demo", "c.json", "d.jsonl",
                                  3)
    assert row["status"] == "REFUSED"
    assert "REFUSED_CODE" in row["reason"]
    assert row["metrics"] is None

def test_empty_metrics_are_absent_never_zero():
    svc = _StubService(evidence=_evidence(
        document={"request_metrics": [], "request_count": 0,
                  "requests_expected": 2, "rounds": 0}))
    row = campaign.run_experiment(svc, "p-stub", "demo", "c.json", "d.jsonl",
                                  2)
    assert row["status"] == "COMPLETED"
    assert row["metrics"]["ttft_cycles"]["n"] == 0
    assert row["metrics"]["ttft_cycles"]["mean"] is None
    assert row["metrics"]["makespan_cycles"] is None
    assert row["metrics"]["tokens_per_kilocycle"] is None

def test_submit_time_refusal_recorded():
    svc = _StubService(submit_error=ValueError("no such cluster"))
    row = campaign.run_experiment(svc, "p-stub", "demo", "missing", "d.jsonl",
                                  3)
    assert row["status"] == "SUBMIT_REFUSED"
    assert "no such cluster" in row["reason"]
    assert row["metrics"] is None

def test_markdown_table_shows_absent_honestly():
    rows = [
        {"experiment": "ok", "status": "COMPLETED", "reason": None,
         "metrics": {"requests_completed": 1, "requests_expected": 1,
                     "makespan_cycles": 10.0,
                     "ttft_cycles": {"n": 1, "mean": 5.0, "p50": 5.0,
                                     "p95": 5.0, "p99": 5.0},
                     "completion_cycles": {"n": 1, "mean": 10.0, "p50": 10.0,
                                           "p95": 10.0, "p99": 10.0},
                     "tokens_per_kilocycle": 2.0}},
        {"experiment": "bad", "status": "REFUSED",
         "reason": "x" * 100, "metrics": None},
    ]
    table = campaign.markdown_table(rows)
    assert "absent" in table
    assert "COMPLETED" in table and "REFUSED" in table
