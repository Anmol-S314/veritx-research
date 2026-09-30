"""Full-stack Qwen3-30B-A3B TP2+EP4 acceptance (§18).

Runs the PRODUCT path end to end — project → compile → certificate →
plan → evaluate — on the canonical acceptance workload, and asserts
multi-class traffic survives with per-class conservation. No helper
methods: this is the same gateway surface a user drives.

Skips (classified) when the release backends are not built in this tree.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(DSE / "tests"))

WORKLOAD = "qwen3-moe-tp2-ep4-16tiles"
CLUSTER = ("third_party/llmservingsim/configs/cluster/"
           "single_node_moe_single_instance.json")
QUESTION = "NETWORK_COMPLETION"

BOOKSIM = os.environ.get("VERITX_BOOKSIM_BIN")
ASTRA = (REPO / "third_party" / "astra-sim" / "astra-sim" /
         "network_frontend" / "booksim2" / "bin" / "AstraSim_BookSim2")

pytestmark = pytest.mark.skipif(
    not BOOKSIM or not Path(BOOKSIM).is_file() or not ASTRA.is_file(),
    reason="release backends (VERITX_BOOKSIM_BIN + AstraSim_BookSim2) "
           "are not built in this tree")

def _client(tmp_path: Path):
    from fastapi.testclient import TestClient
    from veritx_dse.gateway.app import GatewayConfig, create_app
    cfg = GatewayConfig(
        store_root=tmp_path / "store", runs_root=tmp_path / "runs",
        projects_root=tmp_path / "projects",
        booksim_bin=Path(BOOKSIM), timeout_s=900)
    return TestClient(create_app(cfg), raise_server_exceptions=False)

def test_qwen_full_stack_compile_plan_and_execute(tmp_path):
    from test_gateway_federation import _wait_run

    client = _client(tmp_path)
    created = client.post("/api/v1/projects",
                          json={"name": "Qwen acceptance",
                                "workload_id": WORKLOAD})
    assert created.status_code == 200, created.text
    pid = created.json()["project"]["project_id"]

    entry = next(w for w in client.get("/api/v1/catalog/workloads").json()["workloads"]
                 if w["workload_id"] == WORKLOAD)
    assert entry["model_name"] == "Qwen/Qwen3-30B-A3B-Instruct-2507"
    assert entry["parallelism"] == {"tp": 2, "pp": 1, "ep": 4, "dp": 1}
    classes = {c["traffic_class"] for c in entry["collectives"]}
    assert classes == {"tp_collective", "ep_dispatch", "ep_combine"}

    compiled = client.post(f"/api/v1/projects/{pid}/compile")
    assert compiled.status_code == 200, compiled.text
    revision = compiled.json()
    assert revision["compilation"]["status"] == "COMPILED"
    assert revision["certificate"]["overall"] == "PASS"
    rid = revision["revision_id"]

    assert client.get(f"/api/v1/projects/{pid}/serving-binding").json()[
        "binding"] is None
    bound = client.post(f"/api/v1/projects/{pid}/serving-binding",
                        json={"cluster_config": CLUSTER})
    assert bound.status_code >= 400, bound.text

    plan = client.get(f"/api/v1/revisions/{rid}/evaluation-plan").json()
    rows = {a["question"]: a for a in plan["analyses"]}
    for q in ("NETWORK_COMPLETION", "SYSTEM_MAKESPAN",
              "COMMUNICATION_EXPOSURE", "PER_RANK_COMPLETION"):
        assert rows[q]["readiness"] == "READY", (q, rows[q]["reason"])
    assert rows["SERVING_TTFT"]["readiness"] == "BLOCKED"
    assert rows["SYSTEM_MAKESPAN"]["qualification"][
        "numerical_qualification"] == "LIMITED"

    submitted = client.post(f"/api/v1/revisions/{rid}/evaluate",
                            json={"questions": ["NETWORK_COMPLETION",
                                                "SYSTEM_MAKESPAN"]})
    assert submitted.status_code == 200, submitted.text
    job = _wait_run(client, submitted.json()["job_id"])
    assert job["state"] == "COMPLETED", job
    run_id = job["result"]["run_id"]
    run = client.get(f"/api/v1/runs/{run_id}").json()

    analyses = {a["question"]: a for a in run["analyses"]}
    assert analyses["NETWORK_COMPLETION"]["status"] == "EVALUATED"
    assert analyses["SYSTEM_MAKESPAN"]["status"] == "EVALUATED"
    evidence = client.get(f"/api/v1/runs/{run_id}/evidence").json()
    assert "CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1" in str(evidence)
    net = analyses["NETWORK_COMPLETION"]["normalized_metrics"]
    keyed = {m["key"]: m["value"] for m in net}
    assert keyed["loaded_trace_packets"] == keyed["injected_trace_packets"]
    assert keyed["delivered_packets"] == keyed["injected_trace_packets"]
    assert keyed["flits_injected"] == keyed["flits_accepted"]

    assert run["design_hash"] == revision["design_hash"]

def test_qwen_v4_declared_compute_reaches_ramulator(tmp_path):
    """The v4 acceptance workload declares compute, so DRAM timing has real
    demand and executes through the product (not just 'READY')."""
    from test_gateway_federation import _wait_run

    v4_workload = "qwen3-moe-tp2-ep4-8ranks-declared-compute"
    client = _client(tmp_path)
    created = client.post("/api/v1/projects",
                          json={"name": "Qwen v4 compute",
                                "workload_id": v4_workload})
    assert created.status_code == 200, created.text
    pid = created.json()["project"]["project_id"]
    compiled = client.post(f"/api/v1/projects/{pid}/compile")
    assert compiled.status_code == 200, compiled.text
    revision = compiled.json()
    assert revision["compilation"]["status"] == "COMPILED"
    assert revision["certificate"]["overall"] == "PASS"
    rid = revision["revision_id"]

    plan = client.get(f"/api/v1/revisions/{rid}/evaluation-plan").json()
    dram = next(a for a in plan["analyses"] if a["question"] == "DRAM_TIMING")
    assert dram["readiness"] == "READY", dram["reason"]

    submitted = client.post(f"/api/v1/revisions/{rid}/evaluate",
                            json={"questions": ["DRAM_TIMING"]})
    assert submitted.status_code == 200, submitted.text
    job = _wait_run(client, submitted.json()["job_id"])
    assert job["state"] == "COMPLETED", job
    run = client.get(f"/api/v1/runs/{job['result']['run_id']}").json()
    analysis = next(a for a in run["analyses"]
                    if a["question"] == "DRAM_TIMING")
    assert analysis["status"] == "EVALUATED", analysis["reason"]
    assert analysis["backend_id"] == "RAMULATOR2_HBM3_V1"
    metrics = {m["key"]: m["value"] for m in analysis["normalized_metrics"]}
    assert metrics["completion_cycles"] > 0
