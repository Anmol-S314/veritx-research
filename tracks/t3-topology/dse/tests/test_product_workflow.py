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

import json
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
                       json={"name": "Llama Dense 8B Study",
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


def _digest(value: str) -> str:
    return str(value).split(":", 1)[-1]


def test_revision_topology_view_matches_the_certificate(tmp_path):
    """The Topology view is the certified graph, not a redrawn intent."""
    client = _client(tmp_path, with_backend=False)
    pid = _make_project(client)["project"]["project_id"]
    revision = client.post(f"/api/v1/projects/{pid}/compile").json()
    rid = revision["revision_id"]
    compilation = revision["compilation"]
    assert compilation["status"] == "COMPILED"
    assert "topology_hash" in compilation["artifact_hashes"]

    resp = client.get(f"/api/v1/revisions/{rid}/topology")
    assert resp.status_code == 200, resp.text
    view = resp.json()

    assert view["contract_version"] == 1
    assert view["revision_id"] == rid
    assert view["design_hash"] == revision["design_hash"]
    assert view["topology_hash"].startswith("sha256:")
    assert _digest(view["topology_hash"]) == _digest(
        compilation["artifact_hashes"]["topology_hash"])
    assert view["family"] == revision["design"]["noc_guided"][
        "topology_family"]

    routers = view["routers"]
    assert routers, "a compiled fabric always has routers"
    router_ids = [r["router_id"] for r in routers]
    assert len(router_ids) == len(set(router_ids))
    assert view["counts"]["routers"] == len(routers)
    assert view["counts"]["channels"] == len(view["channels"])
    assert view["counts"]["endpoints"] == len(view["endpoints"])
    assert view["counts"]["seats"] == sum(
        r["seat_capacity"] for r in routers)

    router_set = set(router_ids)
    for channel in view["channels"]:
        assert channel["src_router"] in router_set
        assert channel["dst_router"] in router_set
        assert channel["src_router"] != channel["dst_router"]
        assert channel["width_bits"] > 0

    assert view["endpoints"], "agent seats are part of the certified graph"
    for endpoint in view["endpoints"]:
        assert endpoint["router_id"] in router_set
        assert endpoint["port_id"] >= 0
        assert endpoint["kind"] in {
            "compute_tile", "hbm_controller", "nic", "peripheral",
            "ucie_port"}

    links = view["physical_links"]
    if links:
        owner = {cid: link["physical_link_id"]
                 for link in links for cid in link["channel_ids"]}
        for channel in view["channels"]:
            if channel.get("physical_link_id") is not None:
                assert owner[channel["channel_id"]] == \
                    channel["physical_link_id"]
    else:
        # Physical-link grouping is optional in the artifact. When it is
        # absent every channel must say so, and the renderer collapses the
        # directed channel set into undirected pairs itself.
        assert all(c.get("physical_link_id") is None
                   for c in view["channels"])

    # an unknown revision is a refusal, never an invented empty fabric
    missing = client.get("/api/v1/revisions/nope/topology")
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"


def test_topology_view_rederives_legacy_revisions_and_verifies_the_hash(
        tmp_path):
    """Revisions stored before the projection existed are re-derived and
    checked against the topology_hash the certificate already recorded."""
    client = _client(tmp_path, with_backend=False)
    pid = _make_project(client)["project"]["project_id"]
    revision = client.post(f"/api/v1/projects/{pid}/compile").json()
    rid = revision["revision_id"]

    stored_path = next(tmp_path.rglob(f"revisions/{rid}.json"))
    stored = json.loads(stored_path.read_text(encoding="utf-8"))
    certified = stored["topology"]
    assert certified is not None
    del stored["topology"]
    stored_path.write_text(json.dumps(stored), encoding="utf-8")

    again = client.get(f"/api/v1/revisions/{rid}/topology")
    assert again.status_code == 200, again.text
    redervied = again.json()
    assert redervied["topology_hash"] == certified["topology_hash"]
    assert redervied["counts"] == certified["counts"]

    # tampering with the recorded hash must fail closed (422), never
    # return a graph the certificate does not cover
    tampered = json.loads(stored_path.read_text(encoding="utf-8"))
    tampered["compilation"]["artifact_hashes"]["topology_hash"] = \
        "sha256:" + "0" * 64
    stored_path.write_text(json.dumps(tampered), encoding="utf-8")

    refused = client.get(f"/api/v1/revisions/{rid}/topology")
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "EVIDENCE_INVALID"


def test_refused_attempt_preserves_active_revision(tmp_path):
    """The r01 -> r02 screen: a refused compile must not displace the
    usable revision, move the latest run, or offer r02 for execution."""
    client = _client(tmp_path, with_backend=False)
    project = _make_project(client)
    pid = project["project"]["project_id"]

    r1 = client.post(f"/api/v1/projects/{pid}/compile").json()
    assert r1["compilation"]["status"] == "COMPILED"
    assert r1["certificate"]["overall"] == "PASS"
    r1_id = r1["revision_id"]

    # A qualified run against r01 (seeded directly: no backend needed to
    # test the scoping invariant).
    from veritx_dse.product.service import ProductConfig, ProductService
    svc = ProductService(ProductConfig(projects_root=tmp_path / "projects"))
    svc.store.create_run(pid, {
        "schema_version": 1, "run_id": "run-r01-qualified",
        "project_id": pid, "revision_id": r1_id,
        "design_hash": r1["design_hash"],
        "display_name": "seeded r01 run",
        "backend": "booksim", "status": "EVALUATED",
        "qualification": "QUALIFIED", "requirements_pass": True,
        "started_at": "t", "completed_at": "t", "bundle_id": None,
        "evaluation": {"metrics": {"completion_cycles": 3259}},
    })

    # Break the draft (torus has no certified routing derivation) and
    # compile the refused attempt.
    draft = client.get(f"/api/v1/projects/{pid}/draft").json()
    draft["request"]["noc_config"]["topology_family"] = "torus"
    put = client.put(f"/api/v1/projects/{pid}/draft",
                     json={"request": draft["request"]})
    assert put.status_code == 200, put.text
    r2 = client.post(f"/api/v1/projects/{pid}/compile").json()
    assert r2["compilation"]["status"] == "UNSUPPORTED"
    assert r2["compilation"]["error"]
    r2_id = r2["revision_id"]
    assert r2_id != r1_id

    project = client.get(f"/api/v1/projects/{pid}").json()
    # Attempt recorded, active untouched.
    assert project["active_revision_id"] == r1_id
    assert project["latest_attempt_revision_id"] == r2_id
    assert project["latest_attempt"]["revision_id"] == r2_id
    assert project["latest_attempt"]["compilation_status"] == "UNSUPPORTED"
    assert "torus" in (project["latest_attempt"]["error"] or "")
    # The draft still needs fixing, not a recompile of the same refusal.
    assert project["draft"]["dirty"] is True
    assert project["flow"]["state"] == "REFUSED"
    assert project["flow"]["next_action"] == "EDIT_DRAFT"
    assert "torus" in project["flow"]["reason"]
    # The latest run stays scoped to the active revision.
    assert project["latest_active_run"]["run_id"] == "run-r01-qualified"
    assert project["latest_active_run"]["revision_id"] == r1_id

    # No topology exists for the refused attempt; r01's stays available.
    no_fabric = client.get(f"/api/v1/revisions/{r2_id}/topology")
    assert no_fabric.status_code == 409, no_fabric.text
    fabric = client.get(f"/api/v1/revisions/{r1_id}/topology")
    assert fabric.status_code == 200, fabric.text
    assert fabric.json()["counts"]["routers"] >= 1

    # r02 can never be submitted for evaluation.
    refused_eval = client.post(f"/api/v1/revisions/{r2_id}/evaluate",
                               json={"backend": None})
    assert refused_eval.status_code == 409, refused_eval.text
    assert refused_eval.json()["code"] == "CONFLICT"


def _bundle_run(svc, tmp_path: Path, *, run_id: str) -> dict:
    """Create a project + run whose bundle verifies, from a real finalize."""
    from veritx_dse.core.run_bundle import finalize_run_bundle

    pid = svc.create_project(name="bundle run", workload_id=WORKLOAD)[
        "project"]["project_id"]
    bundle_dir = svc.store.run_bundle_dir(pid, run_id)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "evidence.json").write_text('{"a": {"b": 1}}',
                                              encoding="utf-8")
    manifest = finalize_run_bundle(bundle_dir)
    svc.store.create_run(pid, {
        "schema_version": 1, "run_id": run_id, "project_id": pid,
        "revision_id": "r1", "design_hash": "sha256:x", "backend": "booksim",
        "status": "EVALUATED", "qualification": "QUALIFIED",
        "bundle_id": "sha256:" + manifest["bundle_id"],
        "evaluation": None, "requirements": None, "producer": None,
        "evidence": None, "display_name": None, "started_at": None,
        "completed_at": None, "requirements_pass": None, "reason": None,
    })
    return {"project_id": pid, "run_id": run_id, "bundle_dir": bundle_dir}


def _bundle_run_with_evidence(svc, tmp_path: Path, *, run_id: str,
                              stats: dict, route_observation: str,
                              route_dump: str | None) -> Path:
    """A verifying bundle whose backend-evidence.json carries given stats."""
    import json as _json
    from veritx_dse.core.run_bundle import finalize_run_bundle

    pid = svc.create_project(name="integrity run", workload_id=WORKLOAD)[
        "project"]["project_id"]
    bundle_dir = svc.store.run_bundle_dir(pid, run_id)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "evidence": {
            "route_observation": route_observation,
            "route_dump_sha256": route_dump,
            "stats": stats,
        },
        "attempt": {},
    }
    (bundle_dir / "backend-evidence.json").write_text(_json.dumps(doc),
                                                      encoding="utf-8")
    (bundle_dir / "evidence.json").write_text("{}", encoding="utf-8")
    manifest = finalize_run_bundle(bundle_dir)
    svc.store.create_run(pid, {
        "schema_version": 1, "run_id": run_id, "project_id": pid,
        "revision_id": "r1", "design_hash": "sha256:x", "backend": "booksim",
        "status": "EVALUATED", "qualification": "QUALIFIED",
        "bundle_id": "sha256:" + manifest["bundle_id"],
        "evaluation": None, "requirements": None, "producer": None,
        "evidence": {"evidence_id": "ev-1"}, "display_name": None,
        "started_at": None, "completed_at": None,
        "requirements_pass": None, "reason": None,
    })
    return bundle_dir


def test_run_integrity_view_contract(tmp_path):
    """ExecutionIntegrityView: conservation + route realization projected
    from authenticated evidence. Absent counters are NOT AVAILABLE, never
    zero; conservation needs both counters; first-hop scope is explicit."""
    from veritx_dse.product.service import ProductConfig, ProductService

    svc = ProductService(ProductConfig(projects_root=tmp_path / "projects"))
    _bundle_run_with_evidence(
        svc, tmp_path, run_id="run-int-1",
        stats={
            "loaded_trace_packets": 300,
            "injected_trace_packets": 300,
            "delivered_packets": 300,
            "flits_injected": 2700,
            "flits_accepted": 2700,
            # no declared_packets / declared_flits emitted by this backend
        },
        route_observation="EXECUTED_ROUTE_OBSERVED",
        route_dump="a" * 64)

    client = TestClient(create_app(GatewayConfig(
        store_root=tmp_path / "store", runs_root=tmp_path / "runs",
        projects_root=tmp_path / "projects")), raise_server_exceptions=False)
    resp = client.get("/api/v1/runs/run-int-1/integrity")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["contract_version"] == 1

    packets = body["packet_conservation"]
    assert packets["loaded"] == {"value": 300, "availability": "MEASURED"}
    # Absent counter is NOT AVAILABLE, never 0 (§18).
    assert packets["declared"] == {
        "value": None, "availability": "NOT_AVAILABLE"}
    assert packets["verdict"] == "CONSERVED"

    flits = body["flit_conservation"]
    assert flits["declared"]["availability"] == "NOT_AVAILABLE"
    assert flits["verdict"] == "CONSERVED"

    route = body["route_realization"]
    assert route["status"] == "OBSERVED"
    assert route["scope"] == "destination-aware first-hop realization"
    # Mandatory scope honesty: full path is never claimed.
    assert route["full_path_claimed"] is False
    assert route["realized_digest"] == "a" * 64


def test_run_integrity_view_honesty_fallbacks(tmp_path):
    """Missing counters yield NOT_MEASURED conservation and NOT_OBSERVED
    routing — the view never upgrades absence into a positive claim."""
    from veritx_dse.product.service import ProductConfig, ProductService

    svc = ProductService(ProductConfig(projects_root=tmp_path / "projects"))
    _bundle_run_with_evidence(
        svc, tmp_path, run_id="run-int-2",
        stats={"loaded_trace_packets": 5},  # delivered absent; no flits
        route_observation="DOMAIN_QUALIFIED_ROUTE_NOT_OBSERVED",
        route_dump=None)

    client = TestClient(create_app(GatewayConfig(
        store_root=tmp_path / "store", runs_root=tmp_path / "runs",
        projects_root=tmp_path / "projects")), raise_server_exceptions=False)
    body = client.get("/api/v1/runs/run-int-2/integrity").json()
    assert body["packet_conservation"]["delivered"]["availability"] \
        == "NOT_AVAILABLE"
    assert body["packet_conservation"]["verdict"] == "NOT_MEASURED"
    assert body["flit_conservation"]["verdict"] == "NOT_MEASURED"
    assert body["route_realization"]["status"] == "NOT_OBSERVED"
    assert body["route_realization"]["full_path_claimed"] is False
    assert body["route_realization"]["realized_digest"] is None


def test_verify_run_endpoint_contract(tmp_path):
    """POST /api/v1/runs/{id}/verify delegates to the RunBundle authority."""
    from veritx_dse.product.service import ProductConfig, ProductService

    svc = ProductService(ProductConfig(projects_root=tmp_path / "projects"))
    made = _bundle_run(svc, tmp_path, run_id="run-verify-1")

    client = TestClient(create_app(GatewayConfig(
        store_root=tmp_path / "store", runs_root=tmp_path / "runs",
        projects_root=tmp_path / "projects")), raise_server_exceptions=False)

    resp = client.post("/api/v1/runs/run-verify-1/verify")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["contract_version"] == 1
    assert body["status"] == "VERIFIED"
    assert body["bundle_id"].startswith("sha256:")
    assert body["files_checked"] >= 1

    # Unknown run -> typed 404.
    missing = client.post("/api/v1/runs/run-nope/verify")
    assert missing.status_code == 404, missing.text
    assert missing.json()["code"] == "NOT_FOUND"

    # Tampered content -> EVIDENCE_INVALID, never a trusted verdict.
    (made["bundle_dir"] / "evidence.json").write_text('{"a": {"b": 2}}',
                                                     encoding="utf-8")
    tampered = client.post("/api/v1/runs/run-verify-1/verify")
    assert tampered.status_code == 422, tampered.text
    assert tampered.json()["code"] == "EVIDENCE_INVALID"

    # A run with no bundle (refused evaluation) cannot be verified.
    pid = svc.create_project(name="no bundle", workload_id=WORKLOAD)[
        "project"]["project_id"]
    svc.store.create_run(pid, {
        "schema_version": 1, "run_id": "run-nobundle", "project_id": pid,
        "revision_id": "r1", "design_hash": "sha256:x", "backend": None,
        "status": "REFUSED", "qualification": None, "bundle_id": None,
        "evaluation": None, "requirements": None, "producer": None,
        "evidence": None, "display_name": None, "started_at": None,
        "completed_at": None, "requirements_pass": None, "reason": "x",
    })
    nobundle = client.post("/api/v1/runs/run-nobundle/verify")
    assert nobundle.status_code == 409, nobundle.text
    assert nobundle.json()["code"] == "CONFLICT"


def test_reproduce_endpoint_contract(tmp_path):
    """POST /api/v1/runs/{id}/reproduce submits a Job over the canonical
    reproduce authority; the job result distinguishes the scientific
    outcome and never implies host/wall-time metadata must match."""
    from veritx_dse.product.service import ProductConfig, ProductService

    svc = ProductService(ProductConfig(projects_root=tmp_path / "projects"))
    _bundle_run(svc, tmp_path, run_id="run-repro-1")

    client = TestClient(create_app(GatewayConfig(
        store_root=tmp_path / "store", runs_root=tmp_path / "runs",
        projects_root=tmp_path / "projects")), raise_server_exceptions=False)

    # No backend configured -> the submit itself refuses (503), the user's
    # first indication is never a failed job.
    nobin = client.post("/api/v1/runs/run-repro-1/reproduce")
    assert nobin.status_code == 503, nobin.text
    assert nobin.json()["code"] == "EXECUTION_FAILED"

    # Unknown run -> typed 404.
    missing = client.post("/api/v1/runs/run-nope/reproduce")
    assert missing.status_code == 404, missing.text

    # The job path itself (backend present) is exercised by the CLI leg;
    # here we pin the service-level adapter shape with a stubbed authority.
    from veritx_dse.application.errors import ErrorCode

    svc2 = ProductService(ProductConfig(
        projects_root=tmp_path / "projects2",
        booksim_bin=Path("/bin/true")))
    _bundle_run(svc2, tmp_path, run_id="run-repro-2")

    captured = {}

    def fake_reproduce(run_dir, *, binary=None, timeout=600):
        captured["run_dir"] = str(run_dir)
        captured["binary"] = str(binary)
        return {"matched": True, "bundle_id": "0" * 64,
                "stats": {"completion_cycles": 17},
                "route_dump_sha256": "1" * 64}

    import veritx_dse.backend.reproduce as reproduce_mod
    real = reproduce_mod.reproduce_booksim_run_bundle
    reproduce_mod.reproduce_booksim_run_bundle = fake_reproduce
    try:
        view = svc2.submit_reproduction("run-repro-2")
        assert view["kind"] == "REPRODUCTION"
        job_id = view["job_id"]
        for _ in range(100):
            job = svc2.get_job(job_id)
            if job["state"] in ("COMPLETED", "FAILED", "REFUSED"):
                break
            time.sleep(0.05)
        assert job["state"] == "COMPLETED", job
        result = job["result"]
        assert result["outcome"] == "SCIENTIFICALLY_REPRODUCED"
        assert result["reproduced_stats"] == {
            "completion_cycles": 17}
        assert captured["binary"].endswith("true")
    finally:
        reproduce_mod.reproduce_booksim_run_bundle = real

    # Divergence (authority raises) becomes EVIDENCE_INVALID, not a 500.
    from veritx_dse.core.run_bundle import RunBundleError

    def diverging(run_dir, *, binary=None, timeout=600):
        raise RunBundleError("reproduction diverges from stored science")

    real = reproduce_mod.reproduce_booksim_run_bundle
    reproduce_mod.reproduce_booksim_run_bundle = diverging
    try:
        view = svc2.submit_reproduction("run-repro-2")
        job_id = view["job_id"]
        for _ in range(100):
            job = svc2.get_job(job_id)
            if job["state"] in ("COMPLETED", "FAILED", "REFUSED"):
                break
            time.sleep(0.05)
        assert job["state"] == "REFUSED"
        assert job["error_code"] == ErrorCode.EVIDENCE_INVALID.value
        assert "diverges" in (job["error_message"] or "")
    finally:
        reproduce_mod.reproduce_booksim_run_bundle = real
