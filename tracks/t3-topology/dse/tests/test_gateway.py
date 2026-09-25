"""Studio gateway contract (C9).

The gateway is thin: it parses, calls canonical services, and returns
evidence-bearing results. These tests pin the contract and the refusal
codes; they do not re-test the science.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from fastapi.testclient import TestClient  # noqa: E402

from veritx_dse.core.run_bundle import finalize_run_bundle  # noqa: E402
from veritx_dse.gateway.app import GatewayConfig, create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    cfg = GatewayConfig(store_root=tmp_path / "store",
                        runs_root=tmp_path / "runs")
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(cfg))


def test_qualification_marks_astra_numerics_unestablished(client):
    body = client.get("/qualification").json()
    assert body["engines"]["astra"]["numerical"] == "NOT_ESTABLISHED"
    assert body["engines"]["astra"]["integration"] == "QUALIFIED"


def test_workloads_lists_presets(client):
    body = client.get("/workloads").json()
    ids = {w["id"] for w in body["workloads"]}
    assert "preset:mesh4" in ids


def test_compile_preset_returns_resolved_fabric(client):
    resp = client.post("/compile", json={
        "preset": "mesh4", "policy": "baseline_deterministic_v2"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["resolved_fabric_hash"]) == 64
    assert body["vc_count"] >= 1


def test_compile_rejects_bad_policy(client):
    resp = client.post("/compile", json={
        "preset": "mesh4", "policy": "no_such_policy"})
    assert resp.status_code == 400


def test_runs_lists_and_verifies_finalized_bundle(client, tmp_path):
    run = tmp_path / "runs" / "run-1"
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(
        json.dumps({"schema_version": 1}), encoding="utf-8")
    (run / "backend-evidence.json").write_text(
        json.dumps({"evidence": {"stats": {}}, "attempt": {}}),
        encoding="utf-8")
    finalize_run_bundle(run)

    listing = client.get("/runs").json()["runs"]
    assert listing[0]["run_id"] == "run-1"
    assert listing[0]["status"] == "VERIFIED"

    detail = client.get("/runs/run-1").json()
    assert detail["bundle_id"] == listing[0]["bundle_id"]
    assert detail["manifest"]["schema_version"] == 1

    ev = client.get("/runs/run-1/evidence").json()
    assert "evidence" in ev


def test_runs_reports_invalid_bundle(client, tmp_path):
    run = tmp_path / "runs" / "bad"
    run.mkdir(parents=True)
    (run / "x").write_text("y", encoding="utf-8")
    finalize_run_bundle(run)
    (run / "x").write_text("tampered", encoding="utf-8")
    listing = client.get("/runs").json()["runs"]
    assert listing[0]["status"] == "INVALID"
    assert client.get("/runs/bad").status_code == 409


def test_runs_rejects_path_traversal(client):
    assert client.get("/runs/..%2Fsecret").status_code in (400, 404)


def test_evaluate_without_backend_is_503(client):
    resp = client.post("/evaluate", json={"request": {}})
    assert resp.status_code == 503
