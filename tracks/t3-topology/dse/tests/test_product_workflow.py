"""Product workflow contract (UI1+).

Covers the brief's required API-level test:

    create project -> update draft -> compile -> inspect revision
    -> inspect verification -> evaluate -> poll job -> receive run
    -> inspect evidence

plus the dirty-draft regression, the error boundary (a programmer fault
must never become INVALID/UNSUPPORTED) and the qualification authority.

The live-evaluation leg requires a real, pinned BookSim producer
(``VERITX_BOOKSIM_BIN`` + a clean build manifest). Without one it skips
loudly; it never falls back to a mock backend.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from fastapi.testclient import TestClient  # noqa: E402

from veritx_dse.gateway.app import GatewayConfig, create_app  # noqa: E402

WORKLOAD = "llama-dense-8b-64tiles"


def _client(tmp_path: Path, with_backend: bool = True) -> TestClient:
    binary = os.environ.get("VERITX_BOOKSIM_BIN")
    cfg = GatewayConfig(
        store_root=tmp_path / "store", runs_root=tmp_path / "runs",
        projects_root=tmp_path / "projects",
        booksim_bin=Path(binary) if (binary and with_backend) else None,
        timeout_s=600)
    return TestClient(create_app(cfg), raise_server_exceptions=False)


def _make_project(client: TestClient) -> dict:
    resp = client.post("/api/v1/projects",
                       json={"name": "Qwen NoC Study",
                             "workload_id": WORKLOAD})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_compile_and_verify_workflow(tmp_path):
    client = _client(tmp_path, with_backend=False)
    project = _make_project(client)
    pid = project["project"]["project_id"]
    assert project["flow"]["state"] == "DIRTY"

    compiled = client.post(f"/api/v1/projects/{pid}/compile")
    assert compiled.status_code == 200, compiled.text
    revision = compiled.json()
    assert revision["compilation"]["status"] == "COMPILED"
    assert revision["certificate"]["overall"] == "PASS"
    assert len(revision["certificate"]["obligations"]) >= 1

    fetched = client.get(
        f"/api/v1/revisions/{revision['revision_id']}").json()
    assert fetched["design_hash"] == revision["design_hash"]
    assert fetched["compilation"]["certificate_id"] == \
        revision["compilation"]["certificate_id"]

    project = client.get(f"/api/v1/projects/{pid}").json()
    assert project["flow"]["state"] == "VERIFIED"
    assert project["draft"]["dirty"] is False


def test_dirty_draft_regression(tmp_path):
    client = _client(tmp_path, with_backend=False)
    project = _make_project(client)
    pid = project["project"]["project_id"]
    revision = client.post(f"/api/v1/projects/{pid}/compile").json()
    rid = revision["revision_id"]

    draft = client.get(f"/api/v1/projects/{pid}/draft").json()
    request = draft["request"]
    request["noc_config"]["link_width"] = (
        128 if request["noc_config"].get("link_width") != 128 else 32)
    updated = client.put(f"/api/v1/projects/{pid}/draft",
                         json={"request": request})
    assert updated.status_code == 200, updated.text

    project = client.get(f"/api/v1/projects/{pid}").json()
    assert project["flow"]["state"] == "DIRTY"
    assert project["active_revision_id"] == rid
    assert project["draft"]["dirty"] is True

    # The old revision is immutable and remains the active compiled one.
    still = client.get(f"/api/v1/revisions/{rid}").json()
    assert still["design_hash"] == revision["design_hash"]


@pytest.mark.parametrize("fault", [ValueError, TypeError, RuntimeError,
                                   AttributeError])
def test_programmer_fault_is_internal_error(tmp_path, monkeypatch, fault):
    client = _client(tmp_path, with_backend=False)
    pid = _make_project(client)["project"]["project_id"]

    def boom(self, request):
        raise fault("injected programmer fault")

    from veritx_dse.application.fabric_compiler import FabricCompiler
    monkeypatch.setattr(FabricCompiler, "compile", boom)

    resp = client.post(f"/api/v1/projects/{pid}/compile")
    assert resp.status_code == 500, resp.text
    body = resp.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert "INVALID" not in body["code"]
    assert "UNSUPPORTED" not in body["code"]


def test_typed_refusals_map_to_http(tmp_path):
    client = _client(tmp_path, with_backend=False)
    project = _make_project(client)
    pid = project["project"]["project_id"]

    bad_draft = client.put(f"/api/v1/projects/{pid}/draft",
                           json={"request": {"schema_version": 3}})
    assert bad_draft.status_code == 400

    missing_revision = client.post(
        "/api/v1/revisions/nope/evaluate")
    assert missing_revision.status_code == 404

    missing_run = client.get("/api/v1/runs/nope")
    assert missing_run.status_code == 404

    compile_resp = client.post(f"/api/v1/projects/{pid}/compile")
    rid = compile_resp.json()["revision_id"]
    bad_study = client.post(
        f"/api/v1/revisions/{rid}/optimize",
        json={"domain": [], "objectives": []})
    assert bad_study.status_code == 400


def test_catalog_separates_workloads_from_fabric_presets(tmp_path):
    client = _client(tmp_path, with_backend=False)
    workloads = client.get("/api/v1/catalog/workloads").json()["workloads"]
    presets = client.get(
        "/api/v1/catalog/fabric-presets").json()["presets"]
    workload_ids = {w["workload_id"] for w in workloads}
    preset_ids = {p["preset_id"] for p in presets}
    assert WORKLOAD in workload_ids
    assert workload_ids.isdisjoint(preset_ids)
    assert "mesh4" in preset_ids
    # The workload catalog carries the real declared representation.
    entry = next(w for w in workloads if w["workload_id"] == WORKLOAD)
    assert entry["parallelism"]["tp"] == 8
    assert entry["collectives"][0]["traffic_class"] == "tp_collective"


def test_qualification_authority_is_machine_readable(tmp_path):
    client = _client(tmp_path, with_backend=False)
    body = client.get("/api/v1/qualification").json()
    astra = body["engines"]["astra"]
    assert astra["integration"] == "QUALIFIED"
    assert astra["numerical"] == "NOT_ESTABLISHED"
    assert body["validation_sha"] is None or isinstance(
        body["validation_sha"], str)


def _pinned_producer_available(client: TestClient) -> bool:
    binary = os.environ.get("VERITX_BOOKSIM_BIN")
    if not binary:
        return False
    from veritx_dse.backend.producer import (
        ProducerError, assert_pinned_producer, resolve_producer_identity,
    )
    from veritx_dse.core.paths import REPO
    try:
        identity = resolve_producer_identity(Path(binary), repo_root=REPO)
        assert_pinned_producer(identity)
    except ProducerError:
        return False
    return True


def _wait(client: TestClient, job_id: str, timeout_s: int = 600) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["state"] in ("COMPLETED", "REFUSED", "FAILED", "CANCELLED"):
            return job
        time.sleep(1)
    raise AssertionError(f"job {job_id} did not finish in {timeout_s}s")


def test_live_evaluation_workflow(tmp_path):
    client = _client(tmp_path)
    if not _pinned_producer_available(client):
        pytest.skip("no pinned BookSim producer "
                    "(set VERITX_BOOKSIM_BIN and a clean build manifest)")

    project = _make_project(client)
    pid = project["project"]["project_id"]
    revision = client.post(f"/api/v1/projects/{pid}/compile").json()
    rid = revision["revision_id"]

    submitted = client.post(f"/api/v1/revisions/{rid}/evaluate")
    assert submitted.status_code == 200, submitted.text
    job = _wait(client, submitted.json()["job_id"])
    assert job["state"] == "COMPLETED", job
    run_id = job["result"]["run_id"]

    run = client.get(f"/api/v1/runs/{run_id}").json()
    assert run["status"] == "EVALUATED"
    assert run["qualification"] == "QUALIFIED"
    assert run["revision_id"] == rid
    assert run["design_hash"] == revision["design_hash"]
    assert run["bundle_id"] is not None
    evaluation = run["evaluation"]
    assert evaluation["status"] == "EVALUATED"
    assert evaluation["design_hash"] == revision["design_hash"]
    assert evaluation["metrics"]["completion_cycles"] > 0
    assert evaluation["backend_producer"]["producer_identity"]
    assert run["requirements"]["entries"]
    assert run["requirements_pass"] is True

    evidence = client.get(f"/api/v1/runs/{run_id}/evidence").json()
    assert evidence["evidence"]["evidence_id"] == \
        evaluation["evidence_id"] if "evidence_id" in evidence[
            "evidence"] else evidence["evidence"]["raw_evidence_digest"]
    assert evidence["artifacts"]
    assert evidence["documents"]

    artifacts = client.get(f"/api/v1/runs/{run_id}/artifacts").json()
    assert artifacts["bundle"]["bundle_id"] == run["bundle_id"].removeprefix(
        "sha256:")

    listing = client.get(f"/api/v1/runs?project_id={pid}").json()["runs"]
    assert any(r["run_id"] == run_id for r in listing)

    flow = client.get(f"/api/v1/projects/{pid}").json()["flow"]
    assert flow["state"] == "EVALUATED"

    compared = client.get(
        f"/api/v1/compare?a={run_id}&b={run_id}").json()
    assert compared["rows"]
    assert compared["a"]["revision_id"] == rid
