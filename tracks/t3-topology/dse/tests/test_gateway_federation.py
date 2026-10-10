"""PROMPT 2 — federation plan and execution controls over HTTP.

Covers the gateway surface: the evaluation-plan resource (selection,
filtering, explicit backend, typed refusals), the extended evaluate
body (questions pass through, empty body stays network-only BookSim),
and the backend presence summary on health.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from fastapi.testclient import TestClient  # noqa: E402

from veritx_dse.gateway.app import GatewayConfig, create_app  # noqa: E402

WORKLOAD = "llama-dense-8b-64tiles"

def _real_booksim() -> Path | None:
    from veritx_dse.core.paths import REPO as _REPO
    candidate = _REPO / "third_party" / "booksim2" / "src" / "booksim"
    return candidate if candidate.is_file() else None

def _client(tmp_path: Path, **overrides) -> TestClient:
    kw = dict(store_root=tmp_path / "store",
              runs_root=tmp_path / "runs",
              projects_root=tmp_path / "projects", timeout_s=600,
              booksim_bin=_real_booksim())
    kw.update(overrides)
    return TestClient(create_app(GatewayConfig(**kw)),
                      raise_server_exceptions=False)

def _compiled_revision(client: TestClient) -> dict:
    project = client.post(
        "/api/v1/projects",
        json={"name": "Federation", "workload_id": WORKLOAD}).json()
    pid = project["project"]["project_id"]
    compiled = client.post(f"/api/v1/projects/{pid}/compile")
    assert compiled.status_code == 200, compiled.text
    revision = compiled.json()
    assert revision["compilation"]["status"] == "COMPILED"
    return revision

def _wait_run(client: TestClient, job_id: str,
              timeout_s: int = 600) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["state"] in ("COMPLETED", "REFUSED", "FAILED",
                            "CANCELLED"):
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish in time")

def test_plan_loads_with_both_backends(tmp_path):
    client = _client(tmp_path)
    revision = _compiled_revision(client)
    resp = client.get(
        f"/api/v1/revisions/{revision['revision_id']}/evaluation-plan")
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert plan["contract_version"] == 1
    assert plan["revision_id"] == revision["revision_id"]
    rows = {row["question"]: row for row in plan["analyses"]}
    assert rows["NETWORK_COMPLETION"]["backend"] == "BOOKSIM_STANDALONE"
    for question in ("SYSTEM_MAKESPAN", "COMMUNICATION_EXPOSURE",
                     "PER_RANK_COMPLETION"):
        assert rows[question]["backend"] == "ASTRA2_EMBEDDED_BOOKSIM"

def test_plan_supports_question_filter_and_backend_pin(tmp_path):
    client = _client(tmp_path)
    revision = _compiled_revision(client)
    rid = revision["revision_id"]
    filtered = client.get(
        f"/api/v1/revisions/{rid}/evaluation-plan",
        params={"questions": "SYSTEM_MAKESPAN,COMMUNICATION_EXPOSURE"})
    assert filtered.status_code == 200, filtered.text
    assert {row["question"] for row in filtered.json()["analyses"]} == {
        "SYSTEM_MAKESPAN", "COMMUNICATION_EXPOSURE"}
    pinned = client.get(
        f"/api/v1/revisions/{rid}/evaluation-plan",
        params={"questions": "SYSTEM_MAKESPAN",
                "backend": "ASTRA2_EMBEDDED_BOOKSIM"})
    assert pinned.status_code == 200, pinned.text
    assert pinned.json()["analyses"][0]["backend"] == \
        "ASTRA2_EMBEDDED_BOOKSIM"

def test_plan_refuses_unknown_question_and_backend(tmp_path):
    client = _client(tmp_path)
    revision = _compiled_revision(client)
    rid = revision["revision_id"]
    bad_question = client.get(
        f"/api/v1/revisions/{rid}/evaluation-plan",
        params={"questions": "NOPE"})
    assert bad_question.status_code == 400, bad_question.text
    bad_backend = client.get(
        f"/api/v1/revisions/{rid}/evaluation-plan",
        params={"backend": "NOPE"})
    assert bad_backend.status_code == 400, bad_backend.text

def test_explicit_astra_network_plan_does_not_fall_back(tmp_path):
    client = _client(tmp_path)
    revision = _compiled_revision(client)
    resp = client.get(
        f"/api/v1/revisions/{revision['revision_id']}/evaluation-plan",
        params={"questions": "NETWORK_COMPLETION",
                "backend": "ASTRA2_EMBEDDED_BOOKSIM"})
    assert resp.status_code == 200, resp.text
    row = resp.json()["analyses"][0]
    assert row["backend"] is None
    assert row["support"] == "UNSUPPORTED"

def test_old_evaluate_with_no_body_is_network_only(tmp_path):
    client = _client(tmp_path)
    revision = _compiled_revision(client)
    submitted = client.post(
        f"/api/v1/revisions/{revision['revision_id']}/evaluate")
    assert submitted.status_code == 200, submitted.text
    job = _wait_run(client, submitted.json()["job_id"])
    run = client.get(
        f"/api/v1/runs/{job['result']['run_id']}").json()
    assert [a["question"] for a in run["analyses"]] == \
        ["NETWORK_COMPLETION"]
    assert run["analyses"][0]["backend_id"] == "BOOKSIM_STANDALONE"
    assert "evaluation" in run and "requirements" in run

def test_evaluate_body_questions_reach_execution(tmp_path):
    client = _client(tmp_path)
    revision = _compiled_revision(client)
    submitted = client.post(
        f"/api/v1/revisions/{revision['revision_id']}/evaluate",
        json={"questions": ["SYSTEM_MAKESPAN"],
              "backend": "ASTRA2_EMBEDDED_BOOKSIM"})
    assert submitted.status_code == 200, submitted.text
    job = _wait_run(client, submitted.json()["job_id"])
    run = client.get(
        f"/api/v1/runs/{job['result']['run_id']}").json()
    assert [a["question"] for a in run["analyses"]] == ["SYSTEM_MAKESPAN"]
    analysis = run["analyses"][0]
    assert analysis["backend_id"] == "ASTRA2_EMBEDDED_BOOKSIM"

def test_health_reports_backend_presence_without_simulating(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    backends = body["backends"]
    assert set(backends) == {"BOOKSIM_STANDALONE",
                             "ASTRA2_EMBEDDED_BOOKSIM",
                             "RAMULATOR2_HBM3_V1"}
    for entry in backends.values():
        assert entry["state"] in ("PRESENT", "ABSENT")

def test_federation_backends_reports_registry_truth(tmp_path):
    """P5: one owner per fact — registration from the adapters'
    declared capabilities, install presence as install facts."""
    client = _client(tmp_path)
    resp = client.get("/api/v1/federation/backends")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["contract_version"] == 1
    by_id = {b["backend_id"]: b for b in body["backends"]}
    assert {"BOOKSIM_STANDALONE", "ASTRA2_EMBEDDED_BOOKSIM",
            "RAMULATOR2_HBM3_V1"} <= set(by_id)
    for entry in body["backends"]:
        assert entry["registered"] is True
        # The served field is the install-presence probe, named as
        # presence. The misleading `runtime_available` name is gone: no
        # runtime-readiness fact exists to serve.
        assert isinstance(entry["install_present"], bool)
        assert isinstance(entry["install_detail"], str)
        assert "runtime_available" not in entry
        assert "availability_detail" not in entry
        assert entry["capabilities"], \
            f"{entry['backend_id']} declares no capabilities"
        for capability in entry["capabilities"]:
            assert capability["question"]
            assert capability["support"]
            assert capability["fidelity"]
            assert isinstance(capability["limitations"], list)
    network = next(
        c for c in by_id["BOOKSIM_STANDALONE"]["capabilities"]
        if c["question"] == "NETWORK_COMPLETION")
    assert network["support"] == "SUPPORTED"
    makespan = next(
        c for c in by_id["ASTRA2_EMBEDDED_BOOKSIM"]["capabilities"]
        if c["question"] == "SYSTEM_MAKESPAN")
    assert makespan["support"] == "SUPPORTED"
    dram = next(
        c for c in by_id["RAMULATOR2_HBM3_V1"]["capabilities"]
        if c["question"] == "DRAM_TIMING")
    assert dram["support"] == "SUPPORTED"
