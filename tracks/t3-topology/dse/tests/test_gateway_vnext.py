"""Studio vNext gateway contract.

The gateway is thin: it parses, calls canonical services, and returns
linkage. These tests pin the vNext routes and refusal codes; they do
not re-test the science (adapters, promotion and registries own that).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from fastapi.testclient import TestClient  # noqa: E402

from veritx_dse.gateway.app import GatewayConfig, create_app  # noqa: E402

@pytest.fixture()
def client(tmp_path):
    cfg = GatewayConfig(store_root=tmp_path / "store",
                        runs_root=tmp_path / "runs")
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(cfg))

def _revision(client):
    project = client.post(
        "/api/v1/projects",
        json={"name": "VNext",
              "workload_id": "llama-dense-8b-64tiles"}).json()
    pid = project["project"]["project_id"]
    compiled = client.post(f"/api/v1/projects/{pid}/compile")
    assert compiled.status_code == 200, compiled.text
    body = compiled.json()
    assert body["compilation"]["status"] == "COMPILED", body
    return body["revision_id"], pid

def _wait_job(client, job_id, timeout_s=120):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["state"] in ("COMPLETED", "REFUSED", "FAILED",
                            "CANCELLED"):
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish in time")

def _demands(n):
    return [[0.0 if i == j else 1.0 for j in range(n)] for i in range(n)]

def _body(engine, nodes, k, **over):
    body = {
        "engine": engine,
        "definition": {"nodes": nodes, "layout": "grid", "k": k,
                       "radix": 4, "max_len": 1.5,
                       "bandwidth_GBs": 256.0, "latency_ns": 1.0,
                       "objective": "geodesic"},
        "traffic": {"dimension": nodes, "values": _demands(nodes),
                    "unit": "messages",
                    "aggregation": "sum_over_workload",
                    "source_artifact_id": "test-workload",
                    "namespace": "router"},
        "seed": 7, "steps": 2, "iters": 2, "max_edges": 40,
    }
    body.update(over)
    return body

def test_synthesis_engines_lists_honest_scope(client):
    body = client.get("/api/v1/synthesis/engines").json()
    engines = {e["engine"]: e for e in body["engines"]}
    assert {"milp_tmcf", "bo_gp", "rho_iterative", "grpo_group"} <= set(
        engines)
    assert engines["rho_iterative"]["completeness"] == "UNBOUNDED"
    assert engines["bo_gp"]["completeness"] == "BUDGETED"
    assert "optimality" in engines["milp_tmcf"]

def test_unknown_engine_refused(client):
    rid, _pid = _revision(client)
    resp = client.post(f"/api/v1/revisions/{rid}/synthesize",
                       json=_body("not_an_engine", 9, 3))
    assert resp.status_code in (400, 422), resp.text

def test_dimension_mismatch_refused(client):
    rid, _pid = _revision(client)
    body = _body("rho_iterative", 9, 3)
    body["traffic"]["dimension"] = 4
    resp = client.post(f"/api/v1/revisions/{rid}/synthesize", json=body)
    assert resp.status_code == 200, resp.text
    job = _wait_job(client, resp.json()["job_id"])
    assert job["state"] == "REFUSED", job
    assert job["error_code"] == "INVALID_INTENT", job

def _run_synthesis(client, engine, nodes, k):
    rid, pid = _revision(client)
    submitted = client.post(f"/api/v1/revisions/{rid}/synthesize",
                            json=_body(engine, nodes, k))
    assert submitted.status_code == 200, submitted.text
    job = _wait_job(client, submitted.json()["job_id"])
    assert job["state"] == "COMPLETED", job
    return rid, pid, job["result"]

def test_rho_synthesis_produces_candidate_and_library_entry(client):
    rid, _pid, result = _run_synthesis(client, "rho_iterative", 9, 3)
    synthesis = client.get(
        f"/api/v1/syntheses/{result['synthesis_id']}").json()
    assert synthesis["engine"] == "rho_iterative"
    assert synthesis["solver_status"] == "FEASIBLE"
    gen = synthesis["generator_objective"]
    assert gen["is_measured_performance"] is False
    assert synthesis["completeness"]["completeness"] == "UNBOUNDED"
    assert "best observed" in synthesis["completeness_claim"]
    assert synthesis["may_claim_optimality"] is False
    assert synthesis["node_count"] == 9

    detail = client.get(
        f"/api/v1/candidates/{result['candidate_id']}").json()
    assert detail["origin"]["kind"] == "synthesis"
    assert detail["adopted"] is False
    assert detail["diff_vs_seed"]["added"] is not None

    lib = client.get("/api/v1/candidates",
                     params={"origin": "synthesis"}).json()
    assert lib["count"] >= 1

def test_bo_synthesis_is_budgeted(client):
    _, _, result = _run_synthesis(client, "bo_gp", 9, 3)
    synthesis = client.get(
        f"/api/v1/syntheses/{result['synthesis_id']}").json()
    assert synthesis["completeness"]["completeness"] == "BUDGETED"
    assert synthesis["may_claim_optimality"] is False

def test_milp_synthesis_end_to_end(client):
    _, _, result = _run_synthesis(client, "milp_tmcf", 4, 2)
    synthesis = client.get(
        f"/api/v1/syntheses/{result['synthesis_id']}").json()
    assert synthesis["solver_status"] in (
        "OPTIMAL", "FEASIBLE", "TIME_LIMIT")
    assert synthesis["candidate"]["status"] == "SUCCEEDED"

def test_candidate_filters_reject_unknown_keys(client):
    resp = client.get("/api/v1/candidates", params={"nope": "1"})
    assert resp.status_code in (400, 422), resp.text

def test_unknown_candidate_is_an_error(client):
    resp = client.get("/api/v1/candidates/nope")
    assert resp.status_code in (400, 404), resp.text

def test_promote_candidate_writes_draft_not_revision(client):
    rid, pid, result = _run_synthesis(client, "rho_iterative", 9, 3)
    resp = client.post(
        f"/api/v1/candidates/{result['candidate_id']}/promote",
        json={"project_id": pid})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["derived_from_candidate_id"] == result["candidate_id"]
    assert body["compile_required"] is True
    detail = client.get(
        f"/api/v1/candidates/{result['candidate_id']}").json()
    assert detail["adopted"] is True
    assert detail["adopted_project_id"] == pid
    assert rid

def test_promote_unknown_candidate_refused(client):
    resp = client.post("/api/v1/candidates/nope/promote",
                       json={"project_id": "nope"})
    assert resp.status_code in (400, 404), resp.text

def test_capability_explorer_ladder_and_status(client):
    body = client.get("/api/v1/capabilities/explorer").json()
    assert body["ladder"] == ["INTENT", "MATERIALIZED", "VERIFIED",
                              "PROJECTED", "EXECUTABLE", "QUALIFIED",
                              "PRODUCT"]
    rows = {c["id"]: c for c in body["capabilities"]}
    assert rows["COMM-006"]["status"] == "AVAILABLE"
    assert rows["COMM-006"]["ladder"]["EXECUTABLE"] == "CONDITIONAL"
    vocab = {"AVAILABLE", "EXPERIMENTAL", "RESEARCH", "HISTORICAL",
             "BLOCKED", "NOT APPLICABLE"}
    assert {c["status"] for c in body["capabilities"]} <= vocab
    assert body["archaeology"], "archaeology ledger must be exposed"

def test_capability_detail_unknown_refused(client):
    resp = client.get("/api/v1/capabilities/NOPE-999")
    assert resp.status_code in (400, 404), resp.text

def test_wave_e_metrics_are_modelled_never_measured(client):
    body = client.get("/api/v1/metrics/wave-e").json()
    assert body["epistemic"] == "MODELLED"
    assert body["measured"] is False
    assert body["qualification"] == \
        "PREDICTIVE_VALIDATION_NOT_ESTABLISHED"
    names = {m["metric"] for m in body["metrics"]}
    assert {"makespan", "critical_path"} <= names
    for metric in body["metrics"]:
        assert metric["measured"] is False
    assert body["not_scalar"], "non-scalar decisions must be explicit"

def test_federated_metrics_catalog(client):
    body = client.get("/api/v1/metrics/federated").json()
    assert body["metrics"], "federated catalog must not be empty"

def test_energy_authorities_stay_separate(client):
    body = client.get("/api/v1/energy/authorities").json()
    assert len(body["authorities"]) == 6
    assert body["bridge_ert_status"] == "PLACEHOLDER"
    mecs = client.get("/api/v1/energy/authorities",
                      params={"family": "gec_mecs"}).json()
    assert mecs["booksim_native_verdict"] == "INVALID"

def test_reuse_unknown_run_refused(client):
    resp = client.get("/api/v1/runs/nope/reuse")
    assert resp.status_code in (400, 404), resp.text

def test_synthesis_completeness_panel(client):
    _, _, result = _run_synthesis(client, "grpo_group", 9, 3)
    panel = client.get(
        f"/api/v1/syntheses/{result['synthesis_id']}/completeness").json()
    assert panel["may_claim_optimality"] is False
    assert "best observed" in panel["claim"]

def test_optimization_completeness_unknown_refused(client):
    resp = client.get("/api/v1/optimizations/nope/completeness")
    assert resp.status_code in (400, 404), resp.text
