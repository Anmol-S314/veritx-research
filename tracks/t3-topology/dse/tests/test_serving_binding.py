"""Serving binding is explicit AND compatibility-checked (§12).

A catalog count is not readiness. A binding is accepted only when the
cluster can actually describe the design: same serving rank count, an
internally consistent TP/EP geometry, and the same model. The tracked
catalog currently contains NO compatible design×cluster pair, so serving
execution is honestly blocked — these tests pin the refusals.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.product.service import (  # noqa: E402
    ProductConfig, ProductService, ProductServiceError,
)

QWEEN = "qwen3-moe-tp2-ep4-16tiles"          # 8 ranks, Qwen MoE
MOE_SMALL = "qwen3-32b-tp2-16tiles"           # real 2-rank design

QWEN2 = ("third_party/llmservingsim/configs/cluster/"
         "single_node_moe_single_instance.json")      # 2 ranks, Qwen
INCONSISTENT = ("third_party/llmservingsim/configs/cluster/"
                "dual_node_kv_remote.json")           # ep4 > tp2 span
LLAMA8 = ("third_party/llmservingsim/configs/cluster/"
          "single_node_4_instance_2TP.json")          # 8 ranks, Llama


def _service(tmp_path: Path) -> ProductService:
    return ProductService(ProductConfig(projects_root=tmp_path / "projects"))


def _serving_readiness(plan: dict) -> str:
    return next(a for a in plan["analyses"]
                if a["question"] == "SERVING_TTFT")["readiness"]


def test_serving_is_blocked_until_explicitly_bound(tmp_path):
    svc = _service(tmp_path)
    p = svc.create_project(name="q", workload_id=QWEEN)
    rid = svc.compile_draft(p["project"]["project_id"])["revision_id"]
    assert _serving_readiness(svc.evaluation_plan(rid)) == "BLOCKED"
    assert svc.serving_binding(p["project"]["project_id"])["binding"] is None


def test_binding_refuses_a_rank_mismatch(tmp_path):
    svc = _service(tmp_path)
    pid = svc.create_project(name="q", workload_id=QWEEN)["project"]["project_id"]
    svc.compile_draft(pid)
    with pytest.raises(ProductServiceError, match="rank"):
        svc.bind_serving(pid, {"cluster_config": QWEN2})   # serves 2, design 8
    assert svc.serving_binding(pid)["binding"] is None


def test_binding_refuses_an_internally_inconsistent_cluster(tmp_path):
    svc = _service(tmp_path)
    pid = svc.create_project(name="q", workload_id=MOE_SMALL)["project"]["project_id"]
    svc.compile_draft(pid)
    with pytest.raises(ProductServiceError, match="internally inconsistent"):
        svc.bind_serving(pid, {"cluster_config": INCONSISTENT})
    assert svc.serving_binding(pid)["binding"] is None


def test_binding_refuses_a_model_mismatch(tmp_path):
    svc = _service(tmp_path)
    pid = svc.create_project(name="q", workload_id=QWEEN)["project"]["project_id"]
    svc.compile_draft(pid)
    # 8 ranks match, but the cluster profiles Llama, not the Qwen design
    with pytest.raises(ProductServiceError, match="profiles"):
        svc.bind_serving(pid, {"cluster_config": LLAMA8})
    assert svc.serving_binding(pid)["binding"] is None


def test_binding_refuses_a_missing_cluster_config(tmp_path):
    svc = _service(tmp_path)
    pid = svc.create_project(name="q", workload_id=QWEEN)["project"]["project_id"]
    with pytest.raises(ProductServiceError):
        svc.bind_serving(pid, {"cluster_config": "no/such/config.json"})
