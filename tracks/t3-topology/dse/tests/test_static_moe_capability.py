"""Declared MoE schedules are executable, not inferred expert/token semantics."""
from __future__ import annotations

import dataclasses
import json

import pytest

from veritx_dse.application import product_registry as registry
from veritx_dse.application.design_view_v2 import _capability_consequences
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.core.paths import REPO
from veritx_dse.core.errors import InvalidInput
from veritx_dse.product.service import parse_request_doc
from veritx_dse.workload.intent_lowering import lower_compile_workload


@pytest.fixture(autouse=True)
def _fresh_registry():
    registry.clear_cache()
    yield
    registry.clear_cache()


def _qwen():
    path = REPO / "tracks/t3-topology/examples/qwen3_moe_tp2_ep4_16tiles-v4.json"
    return parse_request_doc(json.loads(path.read_text()))


def test_qwen_capability_impact_does_not_deny_declared_static_execution():
    request = _qwen()
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED"
    lowered = lower_compile_workload(request)
    assert {tc for _, tc in lowered.traffic_class_by_operation} == {
        "tp_collective", "ep_dispatch", "ep_combine"}
    consequences = {c["capability_id"]: c for c in
                    _capability_consequences(request.to_dict(), compilation)}
    for cid in ("COMM-006", "WORK-002"):
        row = consequences[cid]
        assert row["wiring"] == "WIRED"
        assert row["reason"] is None
        for stage in ("DERIVABLE", "VERIFIABLE", "PROJECTABLE", "EXECUTABLE"):
            assert row["stages"][stage] in ("YES", "CONDITIONAL")
        assert row["stages"]["QUALIFIED"] == "CONDITIONAL"
    assert consequences["WORK-002"]["choice"] == "declared static MoE schedule"
    assert "not inferred" in consequences["WORK-002"]["claim_scope"]


def test_declared_collectives_registry_does_not_deny_multiclass_execution():
    row = registry.capability_consequence("WORK-005")
    assert "multi-class execution is not available" not in row["claim_scope"]
    assert "COND-SINGLE-COMM-CLASS" not in row["conditions"]
    assert row["stages"]["QUALIFIED"] == "CONDITIONAL"
    for cid in ("WORK-002", "WORK-005"):
        assert set(registry.capability_consequence(cid)["conditions"]) <= set(registry.conditions())


def test_moe_model_shape_does_not_invent_dispatch_or_combine():
    request = _qwen()
    request = dataclasses.replace(request, workload=dataclasses.replace(
        request.workload, collectives=()), compute=dataclasses.replace(
            request.compute, stages=()))
    with pytest.raises(InvalidInput, match="no collectives and no compute"):
        lower_compile_workload(request)
    row = registry.capability_consequence("WORK-009")
    assert row["wiring"] == "NOT_AVAILABLE"
    assert row["stages"]["DERIVABLE"] == "NO"
    assert "not authorable" in row["claim_scope"]


def test_qwen_preset_does_not_claim_general_static_or_serving_qualification():
    row = registry.preset_spec("qwen3-moe-tp2-ep4-16tiles")
    assert row["guided_eligible"] is False
    assert "DERIVABLE NO" not in row["reason"]
    assert "serving qualification is separate" in row["reason"]
