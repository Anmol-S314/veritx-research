"""v4 declared compute intent — compute and memory demand (2026-09-29).

Compute is DECLARED, never inferred. A v4 document without compute keeps its
pre-compute identity byte-for-byte; a document that declares compute stages
lowers them into the canonical WorkloadGraph in declared order, gives the
memory backend real operands, and refuses malformed intent.

See docs/decisions/compute-memory-intent.md.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).parent.parent
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

from veritx_dse.model.compile_model import CompileRequestV3  # noqa: E402
from veritx_dse.model.compile_request_v4 import (  # noqa: E402
    CompileRequestV4, CompileRequestV4SchemaError, migrate_v3_to_v4,
)
from veritx_dse.model.compute_intent import (  # noqa: E402
    ComputeIntent, ComputeIntentError, ComputeStage,
)
from veritx_dse.workload.intent_lowering import lower_compile_workload  # noqa: E402

EX = REPO / "tracks/t3-topology/examples"

def _v4() -> CompileRequestV4:
    d = json.loads((EX / "dense_1b_16tiles-v3.json").read_text())
    d.pop("design_hash", None)
    d.pop("guardrail_hash", None)
    d["agents"] = [{"kind": "compute_tile", "count": 16, "data_width": 256,
                    "addr_width": 64, "protocol": "AXI"}]
    d["noc_config"] = dict(d["noc_config"])
    d["noc_config"].update(topology_family=None, radix=None, concentration=None)
    return migrate_v3_to_v4(CompileRequestV3.from_dict(d))

def _stages(n: int, *, owner: int | None = 0) -> tuple[ComputeStage, ...]:
    return tuple(
        ComputeStage(stage_id=f"layer{i}", duration_ns=100,
                     input_bytes=4096, weight_bytes=8192,
                     output_bytes=2048, owner=owner)
        for i in range(n))

def _with_compute(request: CompileRequestV4,
                  stages: tuple[ComputeStage, ...]) -> CompileRequestV4:
    return dataclasses.replace(request, compute=ComputeIntent(stages=stages))

def test_v4_without_compute_omits_the_key_and_round_trips():
    r = _v4()
    assert "compute" not in r.to_dict()
    assert CompileRequestV4.from_dict(r.to_dict()).design_hash() \
        == r.design_hash()

def test_declared_compute_is_identity_bearing():
    r = _v4()
    with_compute = _with_compute(r, _stages(3))
    assert with_compute.design_hash() != r.design_hash()
    assert with_compute.to_dict()["compute"]["stages"][0]["stage_id"] \
        == "layer0"
    assert CompileRequestV4.from_dict(
        with_compute.to_dict()).design_hash() == with_compute.design_hash()

def test_duplicate_stage_ids_refuse():
    with pytest.raises(ComputeIntentError):
        ComputeIntent(stages=(
            ComputeStage("a", 1, 1, 1, 1),
            ComputeStage("a", 1, 1, 1, 1)))

def test_negative_or_bool_bytes_refuse():
    with pytest.raises(ComputeIntentError):
        ComputeStage("a", 1, -1, 1, 1)
    with pytest.raises(ComputeIntentError):
        ComputeStage("a", 1, True, 1, 1)

def test_unknown_compute_fields_refuse():
    with pytest.raises(ComputeIntentError):
        ComputeIntent.from_dict({"stages": [], "extra": 1})
    with pytest.raises(CompileRequestV4SchemaError):
        d = _with_compute(_v4(), _stages(1)).to_dict()
        d["compute"]["stages"][0]["invented"] = 1
        CompileRequestV4.from_dict(d)

def test_declared_compute_lowers_to_chained_compute_ops():
    r = _with_compute(_v4(), _stages(4))
    lowered = lower_compile_workload(r)
    compute = [op for op in lowered.graph.operations
               if op.kind == "COMPUTE"]
    assert len(compute) == 4
    assert compute[0].deps == ()
    for prev, cur in zip(compute, compute[1:]):
        assert cur.deps == (prev.operation_id,)
    for op in compute:
        assert op.owner == 0
        detail = op.detail
        assert detail["input_bytes"] == 4096
        assert detail["weight_bytes"] == 8192
        assert detail["output_bytes"] == 2048

def test_compute_only_workload_is_lowerable():
    r = _with_compute(_v4(), _stages(2))
    workload = dataclasses.replace(r.workload, collectives=())
    r = dataclasses.replace(r, workload=workload)
    lowered = lower_compile_workload(r)
    assert [op.kind for op in lowered.graph.operations] == ["COMPUTE",
                                                            "COMPUTE"]

def test_empty_workload_still_refuses():
    from veritx_dse.core.errors import InvalidInput
    r = _v4()
    workload = dataclasses.replace(r.workload, collectives=())
    r = dataclasses.replace(r, workload=workload)
    with pytest.raises(InvalidInput):
        lower_compile_workload(r)

def test_owner_outside_the_participant_namespace_refuses():
    r = _with_compute(_v4(), _stages(2, owner=None))
    stages = dataclasses.replace(ComputeIntent(stages=r.compute.stages))
    bad = dataclasses.replace(
        r, compute=ComputeIntent(stages=tuple(
            dataclasses.replace(s, owner=10 ** 6) for s in stages.stages)))
    with pytest.raises(Exception):
        lower_compile_workload(bad)

def test_declared_compute_resolves_real_memory_demand():
    from veritx_dse.backend.ramulator_adapter import (
        certified_mapping_policy, certified_memory_design,
    )
    from veritx_dse.workload.memory_lowering import resolve_memory_graph

    lowered = lower_compile_workload(_with_compute(_v4(), _stages(3)))
    resolved = resolve_memory_graph(
        lowered.graph, certified_memory_design(),
        policy=certified_mapping_policy())
    assert resolved.artifact.artifact_hash.startswith("sha256:")
    assert len(resolved.artifact.regions) == 9

def test_lowering_view_reports_the_memory_demand():
    from veritx_dse.application.views import lowering_view
    view = lowering_view(_with_compute(_v4(), _stages(4)))
    demand = view["memory_demand"]
    assert demand["compute_count"] == 4
    assert demand["memory_demand_ops"] == 4
    assert demand["total_operand_bytes"] == 4 * (4096 + 8192 + 2048)
    assert demand["has_memory_demand"] is True
