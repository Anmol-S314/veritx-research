"""Compute provenance must survive lowering and gate comparison (§4.4).

Compute durations are only as trustworthy as their source. The lowering
carries the request's compute source into the graph provenance, and the
comparison refuses candidates whose compute origins disagree — a QUALIFIED
fabric result never implies qualified compute timing.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

from veritx_dse.application.comparison import (  # noqa: E402
    ComparisonContract,
    check_compatibility,
)
from veritx_dse.application.errors import ControlPlaneError  # noqa: E402
from veritx_dse.model.compile_model import CompileRequestV3  # noqa: E402
from veritx_dse.model.compile_request_v4 import (  # noqa: E402
    CompileRequestV4, migrate_v3_to_v4,
)
from veritx_dse.model.compute_intent import (  # noqa: E402
    ComputeIntent, ComputeSource, ComputeStage,
)
from veritx_dse.workload.intent_lowering import (  # noqa: E402
    lower_compile_workload,
)

EX = REPO / "tracks/t3-topology/examples"


def _v4() -> CompileRequestV4:
    d = json.loads((EX / "dense_1b_16tiles-v3.json").read_text())
    d.pop("design_hash", None)
    d.pop("guardrail_hash", None)
    d["agents"] = [{"kind": "compute_tile", "count": 16, "data_width": 256,
                    "addr_width": 64, "protocol": "AXI"}]
    d["noc_config"] = dict(d["noc_config"])
    d["noc_config"].update(topology_family=None, radix=None,
                           concentration=None)
    return migrate_v3_to_v4(CompileRequestV3.from_dict(d))


def _stages(n: int = 2) -> tuple:
    return tuple(
        ComputeStage(stage_id=f"layer{i}", duration_ns=100,
                     input_bytes=4096, weight_bytes=8192,
                     output_bytes=2048, owner=0)
        for i in range(n))


def test_lowering_carries_a_declared_compute_source():
    source = ComputeSource(kind="declared",
                           detail="chosen for the study",
                           reference="")
    assert source.specified
    request = dataclasses.replace(
        _v4(), compute=ComputeIntent(stages=_stages(), source=source))
    lowered = lower_compile_workload(request)
    assert lowered.graph.provenance["compute_source"]["kind"] == "declared"


def test_lowering_carries_a_measured_compute_source():
    source = ComputeSource(kind="measured", detail="",
                           reference="silicon run 2026-03-14")
    request = dataclasses.replace(
        _v4(), compute=ComputeIntent(stages=_stages(), source=source))
    lowered = lower_compile_workload(request)
    assert lowered.graph.provenance["compute_source"]["kind"] == "measured"


def test_lowering_without_compute_marks_origin_unspecified():
    lowered = lower_compile_workload(_v4())
    assert lowered.graph.provenance["compute_source"]["kind"] == "unspecified"


def _record(**over):
    base = {
        "resource_type": "result",
        "status": "SUCCEEDED",
        "execution_transport": "SUPERVISED_PROCESS",
        "fabric_hash": "sha256:f",
        "workload_hash": "sha256:w",
        "mapping_hash": "sha256:m",
        "backend_target": "BOOKSIM_STANDALONE",
        "backend_profile": "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1",
        "backend_semantics": "v1",
        "execution_mode": "LIVE_CANONICAL_EXECUTION",
        "seed_policy": "deterministic:[42]",
        "seed": 42,
        "metric_schema": "v1",
        "producer": {"binary_sha256": "ab" * 32},
        "loss_digest": "sha256:l",
    }
    base.update(over)
    return base


def _contract():
    return ComparisonContract(
        comparison_kind="DESIGN_COMPARISON",
        allowed_variations=(),
        metric_ids=(),
    )


def test_matching_compute_origins_compare():
    a = _record(compute_source={"kind": "measured"})
    b = _record(compute_source={"kind": "measured"})
    report = check_compatibility(a, b, _contract())
    assert report["verdict"] == "COMPATIBLE"


def test_divergent_compute_origins_refuse():
    a = _record(compute_source={"kind": "measured"})
    b = _record(compute_source={"kind": "declared"})
    with pytest.raises(ControlPlaneError, match="compute_source"):
        check_compatibility(a, b, _contract())


def test_unknown_origins_match_only_each_other():
    a = _record()
    b = _record()
    assert "compute_source" not in a
    report = check_compatibility(a, b, _contract())
    assert report["verdict"] == "COMPATIBLE"


def test_known_origin_against_unknown_refuses():
    a = _record(compute_source={"kind": "measured"})
    b = _record()
    with pytest.raises(ControlPlaneError, match="compute_source"):
        check_compatibility(a, b, _contract())
