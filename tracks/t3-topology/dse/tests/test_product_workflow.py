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


def test_project_crud(tmp_path):
    client = _client(tmp_path, with_backend=False)
    pid = _make_project(client)["project"]["project_id"]

    renamed = client.patch(f"/api/v1/projects/{pid}",
                           json={"name": "Renamed Study"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["project"]["name"] == "Renamed Study"
    assert client.get(f"/api/v1/projects/{pid}").json()[
        "project"]["name"] == "Renamed Study"
    listing = client.get("/api/v1/projects").json()["projects"]
    assert any(p["project"]["project_id"] == pid for p in listing)

    blank = client.patch(f"/api/v1/projects/{pid}", json={"name": "   "})
    assert blank.status_code == 400

    deleted = client.delete(f"/api/v1/projects/{pid}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True
    assert client.get(f"/api/v1/projects/{pid}").status_code == 404
    assert client.get("/api/v1/projects").json()["projects"] == []


def test_delete_project_with_running_job_conflicts(tmp_path):
    # A non-terminal job makes delete a conflict, not silent data loss.
    from veritx_dse.application.errors import ErrorCode
    from veritx_dse.product.service import ProductConfig, ProductService

    svc = ProductService(ProductConfig(projects_root=tmp_path / "projects"))
    pid = svc.create_project(name="busy", workload_id=WORKLOAD)[
        "project"]["project_id"]
    svc.store.create_job(pid, {
        "schema_version": 1, "job_id": "job-x", "project_id": pid,
        "kind": "EVALUATION", "revision_id": "r", "state": "RUNNING",
        "submitted_at": "t", "updated_at": "t", "error_code": None,
        "error_message": None, "result": None,
    })
    with pytest.raises(Exception) as exc:
        svc.delete_project(pid)
    assert getattr(exc.value, "code", None) == ErrorCode.CONFLICT
    # The project survives.
    assert svc.store.load_project(pid)["name"] == "busy"


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


def test_tampered_bundle_is_refused(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from veritx_dse.application.errors import ErrorCode
    from veritx_dse.core.run_bundle import finalize_run_bundle
    from veritx_dse.product.service import ProductConfig, ProductService
    from veritx_dse.product.store import ProductStore

    svc = ProductService(ProductConfig(projects_root=tmp_path / "projects"))
    pid = svc.create_project(name="tamper", workload_id=WORKLOAD)[
        "project"]["project_id"]
    run_id = "run-tamper-1"
    bundle_dir = svc.store.run_bundle_dir(pid, run_id)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "evidence.json").write_text('{"a": 1}', encoding="utf-8")
    manifest = finalize_run_bundle(bundle_dir)
    svc.store.create_run(pid, {
        "schema_version": 1, "run_id": run_id, "project_id": pid,
        "revision_id": "r", "design_hash": "sha256:x", "backend": "booksim",
        "status": "EVALUATED", "qualification": "QUALIFIED",
        "bundle_id": "sha256:" + manifest["bundle_id"],
        "evaluation": None, "requirements": None, "producer": None,
        "evidence": None, "display_name": None, "started_at": None,
        "completed_at": None, "requirements_pass": None, "reason": None,
    })
    # A verified read succeeds.
    assert svc.get_run(run_id)["bundle_id"].startswith("sha256:")

    # Tampering with the content after finalize is refused.
    (bundle_dir / "evidence.json").write_text('{"a": 2}', encoding="utf-8")
    with pytest.raises(Exception) as exc:
        svc.get_run(run_id)
    assert getattr(exc.value, "code", None) == ErrorCode.EVIDENCE_INVALID
    with pytest.raises(Exception) as exc2:
        svc.run_evidence(run_id)
    assert getattr(exc2.value, "code", None) == ErrorCode.EVIDENCE_INVALID

    # A recorded bundle_id that disagrees with the content is refused.
    svc2 = ProductService(ProductConfig(projects_root=tmp_path / "projects2"))
    pid2 = svc2.create_project(name="mismatch", workload_id=WORKLOAD)[
        "project"]["project_id"]
    run2 = "run-tamper-2"
    d2 = svc2.store.run_bundle_dir(pid2, run2)
    d2.mkdir(parents=True, exist_ok=True)
    (d2 / "e.json").write_text("{}", encoding="utf-8")
    finalize_run_bundle(d2)
    svc2.store.create_run(pid2, {
        "schema_version": 1, "run_id": run2, "project_id": pid2,
        "revision_id": "r", "design_hash": "sha256:x", "backend": "booksim",
        "status": "EVALUATED", "qualification": "QUALIFIED",
        "bundle_id": "sha256:" + "0" * 64,
        "evaluation": None, "requirements": None, "producer": None,
        "evidence": None, "display_name": None, "started_at": None,
        "completed_at": None, "requirements_pass": None, "reason": None,
    })
    with pytest.raises(Exception) as exc3:
        svc2.get_run(run2)
    assert getattr(exc3.value, "code", None) == ErrorCode.EVIDENCE_INVALID

    # Concurrent revision allocation must be unique (two store instances).
    store_root = tmp_path / "projects3"
    base = ProductStore(store_root)
    from veritx_dse.product.service import parse_request_doc
    draft = parse_request_doc(_workload_request_doc())
    project = base.create_project(
        name="concurrent", draft_doc=draft.to_dict(),
        workload_id=WORKLOAD, source="test")
    cpid = project["project_id"]

    def alloc(_i: int) -> int:
        return ProductStore(store_root).allocate_revision(cpid)

    with ThreadPoolExecutor(max_workers=8) as pool:
        seqs = list(pool.map(alloc, range(16)))
    assert len(set(seqs)) == 16


def _workload_request_doc() -> dict:
    import json
    from pathlib import Path
    from veritx_dse.core.paths import REPO
    return json.loads((REPO / "tracks/t3-topology/examples/"
                       "llama_dense_64tiles-v3.json").read_text())


def test_compare_compatibility_gate(tmp_path):
    from veritx_dse.product.service import ProductConfig, ProductService

    svc = ProductService(ProductConfig(projects_root=tmp_path / "projects"))
    pid = svc.create_project(name="cmp", workload_id=WORKLOAD)[
        "project"]["project_id"]
    rid = svc.compile_draft(pid)["revision_id"]

    def mkrun(run_id: str, workload: str, qualification: str) -> str:
        svc.store.create_run(pid, {
            "schema_version": 1, "run_id": run_id, "project_id": pid,
            "revision_id": rid, "design_hash": "sha256:x",
            "backend": "BOOKSIM_STANDALONE", "status": "EVALUATED",
            "qualification": qualification, "bundle_id": None,
            "evaluation": {"workload_id": workload,
                           "metrics": {"completion_cycles": 100}},
            "requirements": None, "producer": None, "evidence": None,
            "display_name": None, "started_at": None, "completed_at": None,
            "requirements_pass": True, "reason": None,
        })
        return run_id

    a = mkrun("run-a", "wl-a", "QUALIFIED")
    b = mkrun("run-b", "wl-b", "QUALIFIED")
    cross = svc.compare(a, b)
    assert cross["compatibility"]["compatible"] is False
    assert cross["compatibility"]["same_workload"] is False
    assert all(not row["comparable"] for row in cross["rows"])

    d = mkrun("run-d", "wl-a", "QUALIFIED")
    same = svc.compare(a, d)
    assert same["compatibility"]["compatible"] is True
    assert same["rows"][0]["comparable"] is True

    unqualified = mkrun("run-e", "wl-a", None)
    not_qual = svc.compare(a, unqualified)
    assert not_qual["compatibility"]["compatible"] is False
    assert not_qual["compatibility"]["both_qualified"] is False


def test_select_workload_is_a_real_action(tmp_path):
    client = _client(tmp_path, with_backend=False)
    pid = _make_project(client)["project"]["project_id"]
    selected = client.post(f"/api/v1/projects/{pid}/workload",
                           json={"workload_id": WORKLOAD})
    assert selected.status_code == 200, selected.text
    assert selected.json()["workload_id"] == WORKLOAD
    assert selected.json()["source"]

    unknown = client.post(f"/api/v1/projects/{pid}/workload",
                          json={"workload_id": "no-such-workload"})
    assert unknown.status_code == 400


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
    assert evidence["evidence"]["evidence_id"] == run["evidence"]["evidence_id"]
    assert evidence["evidence"]["raw_evidence_digest"] == \
        evaluation["evidence"]["raw_evidence_digest"]
    assert evidence["evidence"]["run_bundle"] == run["bundle_id"]
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
