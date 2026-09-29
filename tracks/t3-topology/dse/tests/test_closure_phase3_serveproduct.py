"""Serving experiment catalog + per-analysis run backends (phase 3)."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from veritx_dse.gateway.app import GatewayConfig, create_app  # noqa: E402

from test_product_workflow import (  # noqa: E402
    _client, _make_project,
)


def _catalog(client: TestClient) -> dict:
    resp = client.get("/api/v1/catalog/serving-experiments")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_experiment_catalog_lists_only_on_disk_assets(tmp_path):
    client = _client(tmp_path, with_backend=False)
    catalog = _catalog(client)
    assert catalog["contract_version"] == 1
    experiments = catalog["experiments"]
    assert experiments, "no serving experiments listed"
    for entry in experiments:
        assert entry["config_source"].endswith(".json")
        assert entry["trace_source"].endswith(".jsonl")
        assert entry["config_digest"].startswith("sha256:")
        assert entry["trace_digest"].startswith("sha256:")
        assert entry["trace_requests"] >= 0
        facets = entry["facets"]
        assert facets["dense_or_moe"] in ("dense", "moe")
        assert isinstance(facets["multi_instance"], bool)
        assert isinstance(facets["prefill_decode_split"], bool)
        assert isinstance(facets["markers"], list)
        readiness = entry["readiness"]
        assert isinstance(readiness["astra_binary_present"], bool)
        assert isinstance(readiness["booksim_configured"], bool)
        assert isinstance(readiness["model_configs"], dict)


def test_experiment_facets_match_known_configs(tmp_path):
    client = _client(tmp_path, with_backend=False)
    by_id = {e["config_id"]: e
             for e in _catalog(client)["experiments"]}
    moe = by_id.get("single_node_moe_single_instance")
    assert moe is not None
    assert moe["facets"]["dense_or_moe"] == "moe"
    assert moe["facets"]["ep_sizes"] == [2]
    assert moe["facets"]["tp_sizes"] == [2]
    assert "Qwen/Qwen3-30B-A3B-Instruct-2507" in (
        moe["facets"]["models"])
    multi = by_id.get("single_node_multi_instance")
    assert multi is not None
    assert multi["facets"]["multi_instance"] is True
    pd_cfg = by_id.get("single_node_pd_instance")
    assert pd_cfg is not None
    assert pd_cfg["facets"]["prefill_decode_split"] is True
    kv_cfg = by_id.get("dual_node_kv_remote")
    assert kv_cfg is not None
    assert "remote_kv" in kv_cfg["facets"]["markers"]
    assert "dual_node" in kv_cfg["facets"]["markers"]


def test_catalog_gaps_name_unrunnable_models(tmp_path):
    client = _client(tmp_path, with_backend=False)
    gaps = _catalog(client)["gaps"]
    gap_models = [g["model"] for g in gaps]
    # Model configs exist for these with no cluster file referencing
    # them: reported as gaps, never as runnable experiments.
    assert any("Mixtral" in m or "mixtral" in m for m in gap_models), (
        gap_models)
    assert any("Phi" in m or "phi" in m for m in gap_models), gap_models
    for gap in gaps:
        assert gap["source"].endswith(".json")
        assert "not runnable" in gap["reason"]
    runnable_models = set()
    for entry in _catalog(client)["experiments"]:
        runnable_models.update(entry["facets"]["models"])
    for gap in gaps:
        assert gap["model"] not in runnable_models


def test_run_summary_carries_per_analysis_backends(tmp_path):
    client = _client(tmp_path)
    pid = _make_project(client)["project"]["project_id"]
    assert client.post(f"/api/v1/projects/{pid}/compile").status_code == 200
    project = client.get(f"/api/v1/projects/{pid}").json()
    rid = project["active_revision_id"]
    submitted = client.post(
        f"/api/v1/revisions/{rid}/evaluate",
        json={"questions": ["NETWORK_COMPLETION"]})
    assert submitted.status_code == 200, submitted.text
    from test_gateway_federation import _wait_run
    job = _wait_run(client, submitted.json()["job_id"])
    run_id = job["result"]["run_id"]
    runs = client.get(
        f"/api/v1/runs", params={"project_id": pid}).json()["runs"]
    summaries = [r for r in runs if r["run_id"] == run_id]
    assert summaries, runs
    backends = summaries[0]["analysis_backends"]
    assert {"backend_id": "BOOKSIM_STANDALONE",
            "question": "NETWORK_COMPLETION",
            "status": "EVALUATED"} in backends


def test_astra_only_analysis_is_visible_by_family(tmp_path):
    """A run whose top-level backend is not ASTRA still exposes its
    ASTRA analysis family through analysis_backends."""
    client = _client(tmp_path, with_backend=False)
    pid = _make_project(client)["project"]["project_id"]
    assert client.post(f"/api/v1/projects/{pid}/compile").status_code == 200
    project = client.get(f"/api/v1/projects/{pid}").json()
    rid = project["active_revision_id"]
    submitted = client.post(
        f"/api/v1/revisions/{rid}/evaluate",
        json={"questions": ["SYSTEM_MAKESPAN"],
              "backend": "ASTRA2_EMBEDDED_BOOKSIM"})
    assert submitted.status_code == 200, submitted.text
    from test_gateway_federation import _wait_run
    job = _wait_run(client, submitted.json()["job_id"])
    run_id = job["result"]["run_id"]
    run = client.get(f"/api/v1/runs/{run_id}").json()
    families = [a.get("backend_id") for a in run.get("analyses", [])]
    assert "ASTRA2_EMBEDDED_BOOKSIM" in families
    summaries = [r for r in client.get(
        f"/api/v1/runs", params={"project_id": pid}).json()["runs"]
        if r["run_id"] == run_id]
    assert summaries
    assert "ASTRA2_EMBEDDED_BOOKSIM" in [
        b["backend_id"] for b in summaries[0]["analysis_backends"]]
