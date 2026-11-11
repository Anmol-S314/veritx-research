"""Deployment builder contract (catalogs + in-memory preview).

Rationale: docs/design/reviews/deployment-builder.md.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from fastapi.testclient import TestClient  # noqa: E402

from veritx_dse.application.deployment_builder import (  # noqa: E402
    deployment_hardware_catalog,
    deployment_model_catalog,
)
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.gateway.app import (  # noqa: E402
    DeploymentPreviewBody, GatewayConfig, create_app,
)

QWEN = "Qwen/Qwen3-30B-A3B-Instruct-2507"
MODEL_SOURCE = ("third_party/llmservingsim/configs/model/Qwen/"
                "Qwen3-30B-A3B-Instruct-2507.json")
DEEPSEEK = "deepseek-ai/DeepSeek-V3.2-Exp"
DEEPSEEK_SOURCE = (
    "tracks/t3-topology/data/models/deepseek-ai/DeepSeek-V3.2-Exp.json")
TRACE = "third_party/llmservingsim/workloads/example_trace.jsonl"

PREVIEW = {
    "name": "Qwen3-30B on B200",
    "model_name": QWEN,
    "hardware": "B200",
    "tp_size": 2,
    "pp_size": 1,
    "ep_size": 2,
    "dp_instances": 1,
    "max_num_seqs": 32,
    "max_num_batched_tokens": 2048,
    "trace": TRACE,
    "num_reqs": 10,
    "topology": {"kind": "mesh", "side_length": 2, "concentration": 1},
    "link_width_bits": 128,
    "hbm_controllers_per_rank": 0,
}

@pytest.fixture()
def _client(tmp_path: Path):
    cfg = GatewayConfig(store_root=tmp_path / "store",
                        runs_root=tmp_path / "runs",
                        prewarm_capability_probe=False)
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(cfg))

def _preview(client: TestClient, **overrides) -> dict:
    body = dict(PREVIEW)
    body.update(overrides)
    response = client.post("/api/v1/deployment-intent/preview", json=body)
    assert response.status_code == 200, response.text
    return response.json()

# ---------------------------------------------------------------------------
# Catalogs
# ---------------------------------------------------------------------------

def test_model_catalog_maps_qwen3_geometry_and_is_deterministic(
        _client: TestClient) -> None:
    payload = _client.get("/api/v1/catalog/deployment-models").json()
    assert payload["contract_version"] == 1
    models = payload["models"]
    assert models == sorted(models, key=lambda entry: entry["model_name"])

    entry = next(model for model in models
                 if model["model_name"] == QWEN)
    assert entry["source"] == MODEL_SOURCE
    assert entry["model_family"] == "mixture_of_experts"
    assert entry["geometry"] == {
        "layers": 48,
        "hidden": 2048,
        "heads": 32,
        "kv_heads": 4,
        "head_dim": 128,
        "attention": "gqa",
        "kv_bytes_per_token_per_layer": 2 * 4 * 128 * 2,
        "experts": 128,
        "top_k": 8,
        "dtype_bytes": 2,
    }
    assert entry["digest"] == "sha256:" + hashlib.sha256(
        (REPO / MODEL_SOURCE).read_bytes()).hexdigest()

    assert deployment_model_catalog() == deployment_model_catalog()


def test_model_catalog_lists_deepseek_v32_mla_overlay(
        _client: TestClient) -> None:
    payload = _client.get("/api/v1/catalog/deployment-models").json()
    models = payload["models"]
    assert models == sorted(
        models, key=lambda entry: (entry["model_name"], entry["source"]))

    entry = next(model for model in models
                 if model["model_name"] == DEEPSEEK)
    assert entry["source"] == DEEPSEEK_SOURCE
    assert entry["model_family"] == "mixture_of_experts"
    assert entry["geometry"] == {
        "layers": 61,
        "hidden": 7168,
        "heads": 128,
        "kv_heads": 128,
        "head_dim": 56,
        "attention": "mla",
        "kv_bytes_per_token_per_layer": (512 + 64) * 2 + 128 + 4,
        "indexer_bytes_per_token_per_layer": 128 + (128 // 128) * 4,
        "experts": 256,
        "top_k": 8,
        "dtype_bytes": 2,
    }
    assert entry["digest"] == "sha256:" + hashlib.sha256(
        (REPO / DEEPSEEK_SOURCE).read_bytes()).hexdigest()


def test_hardware_catalog_marks_b200_datasheet_and_keeps_measured_profile(
        _client: TestClient) -> None:
    payload = _client.get("/api/v1/catalog/deployment-hardware").json()
    assert payload["contract_version"] == 1
    hardware = {entry["hardware_id"]: entry
                for entry in payload["hardware"]}
    assert len(hardware) == len(payload["hardware"])

    b200 = hardware["B200"]
    assert b200 == {
        "hardware_id": "B200",
        "display_name": "NVIDIA B200",
        "memory_bytes": 192_000_000_000,
        "memory_bandwidth_bytes_per_s": 8_000_000_000_000,
        "link_bandwidth_bytes_per_s": 1_800_000_000_000,
        "provenance": "NVIDIA DGX B200 datasheet",
        "timing": "DATASHEET",
        "serving_profile": False,
    }

    measured = hardware["RTXPRO6000"]
    assert measured["timing"] == "MEASURED"
    assert measured["serving_profile"] is True

    assert deployment_hardware_catalog() == deployment_hardware_catalog()


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

def test_preview_qwen3_tp2_ep2_on_b200_compiles(
        _client: TestClient) -> None:
    body = _preview(_client)
    assert body["status"] == "OK"
    assert body["issues"] == []
    assert body["report"]["status"] == "OK"
    assert body["report"]["deployment"]["model_name"] == QWEN
    assert body["report"]["deployment"]["hardware"] == "B200"
    assert body["report"]["deployment"]["pd_type"] is None
    assert body["report"]["deployment"]["tp"] == 2
    assert body["report"]["deployment"]["ep"] == 2
    assert body["report"]["deployment"]["pp"] == 1
    assert body["compile"] == {"status": "COMPILED", "error": None}

    request = body["request"]
    assert request["schema_version"] == 4
    assert request["workload"]["tp"] == 2
    assert request["workload"]["ep"] == 1
    assert request["workload"]["pp"] == 1
    assert [collective["kind"]
            for collective in request["workload"]["collectives"]] == [
        "allreduce", "allgather", "reducescatter"]


def test_preview_deepseek_v32_mla_tp8_ep8_compiles(
        _client: TestClient) -> None:
    body = _preview(
        _client, model_name=DEEPSEEK, tp_size=8, ep_size=8,
        topology={"kind": "mesh", "side_length": 3, "concentration": 1})
    assert body["status"] == "OK", body["issues"]
    assert body["issues"] == []
    assert body["compile"] == {"status": "COMPILED", "error": None}

    report = body["report"]
    assert report["deployment"]["model_name"] == DEEPSEEK
    assert report["deployment"]["hardware"] == "B200"
    assert report["deployment"]["tp"] == 8
    assert report["deployment"]["ep"] == 8
    assert report["deployment"]["ranks"] == 8
    assert report["model"] == {
        "layers": 61,
        "hidden": 7168,
        "heads": 128,
        "kv_heads": 128,
        "head_dim": 56,
        "attention": "mla",
        "kv_bytes_per_token_per_layer": (512 + 64) * 2 + 128 + 4,
        "indexer_bytes_per_token_per_layer": 128 + (128 // 128) * 4,
        "experts": 256,
        "top_k": 8,
        "dtype_bytes": 2,
        "weights_bytes": None,
    }

    # Replicated MLA latent (512) + decoupled RoPE key (64), plus the sparse
    # indexer (fp8 keys + one fp32 scale per 128 elements), for 61 layers.
    expected_kv = 61 * ((512 + 64) * 2 + 128 + 4)
    assert expected_kv == 78_324
    assert report["derived"]["kv_bytes_per_token"] == expected_kv

    # The legacy GQA formula would treat 128 KV heads at hidden/heads=56 per
    # head, which is an order of magnitude larger and must not be reported.
    legacy_gqa = 2 * 61 * 128 * 56 * 2
    assert legacy_gqa == 1_748_992
    assert report["derived"]["kv_bytes_per_token"] != legacy_gqa

    request = body["request"]
    assert request["workload"]["tp"] == 8
    assert request["workload"]["ep"] == 1
    assert [collective["kind"]
            for collective in request["workload"]["collectives"]] == [
        "allreduce", "allgather", "reducescatter"]


def test_preview_refuses_pipeline_parallel(_client: TestClient) -> None:
    body = _preview(_client, pp_size=2)
    assert body["status"] == "REFUSED"
    assert [issue["code"] for issue in body["issues"]] == [
        "PIPELINE_PARALLEL_UNSUPPORTED"]
    assert body["request"] is None
    assert body["compile"] is None
    assert body["report"]["status"] == "REFUSED"


def test_preview_refuses_unknown_model(_client: TestClient) -> None:
    body = _preview(_client, model_name="vendor/Not-A-Model")
    assert body["status"] == "REFUSED"
    assert [issue["code"] for issue in body["issues"]] == ["MODEL_UNKNOWN"]
    assert body["request"] is None
    assert body["compile"] is None


def test_preview_refuses_unknown_hardware(_client: TestClient) -> None:
    body = _preview(_client, hardware="B900")
    assert body["status"] == "REFUSED"
    assert [issue["code"] for issue in body["issues"]] == ["HARDWARE_UNKNOWN"]
    assert body["request"] is None
    assert body["compile"] is None


def test_preview_refuses_arbitrary_trace_path(
        _client: TestClient, tmp_path: Path) -> None:
    arbitrary = tmp_path / "trace.jsonl"
    arbitrary.write_text(
        '{"input_toks": 1, "output_toks": 1, "arrival_time_ns": 0}\n',
        encoding="utf-8")
    body = _preview(_client, trace=str(arbitrary))
    assert body["status"] == "REFUSED"
    assert [issue["code"] for issue in body["issues"]] == ["TRACE_UNKNOWN"]
    assert body["request"] is None
    assert body["compile"] is None


ALL_MODELS = [
    ("Qwen/Qwen3-30B-A3B-Instruct-2507", 2),
    ("Qwen/Qwen3-32B", 1),
    ("meta-llama/Llama-3.1-70B", 1),
    ("meta-llama/Llama-3.1-8B", 1),
    ("microsoft/Phi-mini-MoE-instruct", 2),
    ("mistralai/Mixtral-8x7B-v0.1", 2),
]


@pytest.mark.parametrize("hardware", ["B200", "H100", "RTXPRO6000"])
@pytest.mark.parametrize("model_name,ep_size", ALL_MODELS)
def test_every_tracked_model_previews_and_compiles(
        _client: TestClient, model_name: str, ep_size: int,
        hardware: str) -> None:
    body = _preview(
        _client, model_name=model_name, hardware=hardware,
        tp_size=2, ep_size=ep_size)
    assert body["status"] == "OK", body["issues"]
    assert body["compile"] == {"status": "COMPILED", "error": None}
    assert body["request"]["schema_version"] == 4
    assert body["request"]["workload"]["ep"] == 1
    assert body["report"]["deployment"]["ranks"] == 2


def test_pd_is_not_offered_and_pd_bodies_are_rejected(
        _client: TestClient) -> None:
    assert "pd_type" not in DeploymentPreviewBody.model_fields
    assert "pd_type" not in PREVIEW

    body = dict(PREVIEW)
    body["pd_type"] = "prefill"
    response = _client.post("/api/v1/deployment-intent/preview", json=body)
    assert response.status_code == 422

    preview = _preview(_client)
    assert preview["status"] == "OK"
    assert preview["report"]["deployment"]["pd_type"] is None
