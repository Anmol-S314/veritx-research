"""Workload coherence: request-declared MSI miss sequences, end to end.

Coherence enters through the v3/v4 request workload (``workload.coherence``),
lowers to KIND_COHERENCE graph ops with author-declared traffic classes, and
joins the intent-class registry so coherence-scoped requirements validate.
The backend path (Plane C subnet binding) is pinned in test_srota_plane_c;
the fanout law in test_workload_traffic; the demand type in
test_workload_graph. This file pins the request seam between them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

from veritx_dse.model.compile_model import (
    CoherenceIntent,
    CoherencePattern,
    CompileRequestV3,
    CompileRequestV3SchemaError,
    DependencyGraph,
    ModelFamily,
    QoSClass,
    RequirementV3,
    WorkloadV3,
    derive_v3_traffic_classes,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.compute_intent import ComputeIntent
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.model.noc_controls import NocControls
from veritx_dse.workload.intent_lowering import lower_compile_workload


def _coherence(**overrides):
    base = dict(pattern=CoherencePattern.READ_SHARED, home_rank=0,
                writer_rank=None, sharers=(1, 2), line_bytes=64, lines=2,
                traffic_class="coherence")
    base.update(overrides)
    return CoherenceIntent(**base)


def _v4_request(*, coherence=(), collectives=()):
    return CompileRequestV4(
        workload=WorkloadV3(model_family=ModelFamily.DENSE_TRANSFORMER,
                            model_name="coherence-probe",
                            tp=4, ep=1, pp=1, dp=1,
                            collectives=tuple(collectives),
                            coherence=tuple(coherence)),
        dependencies=DependencyGraph(()),
        agents=(),
        topology=MeshIntent(side_length=2, concentration=1),
        noc_controls=NocControls(),
        compute=ComputeIntent(stages=()))


def test_coherence_intent_roundtrips_through_dicts():
    intent = _coherence()
    assert CoherenceIntent.from_dict(intent.to_dict()) == intent


def test_coherence_intent_refuses_a_bad_pattern_at_parse():
    with pytest.raises(ValueError, match="CoherencePattern"):
        CoherenceIntent.from_dict({
            "pattern": "MESI_EXCLUSIVE", "home_rank": 0, "writer_rank": None,
            "sharers": [1], "line_bytes": 64, "lines": 1,
            "traffic_class": "coherence"})


def test_v3_document_parses_declared_coherence():
    doc = json.loads((REPO / "tracks/t3-topology/examples/dense_1b_16tiles-v3.json"
                      ).read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    doc["workload"]["coherence"] = [{
        "pattern": "READ_SHARED", "home_rank": 0, "writer_rank": None,
        "sharers": [1, 2], "line_bytes": 64, "lines": 2,
        "traffic_class": "coherence"}]
    request = CompileRequestV3.from_dict(doc)
    assert len(request.workload.coherence) == 1
    assert request.workload.coherence[0].pattern \
        is CoherencePattern.READ_SHARED


def test_v3_document_refuses_malformed_coherence():
    doc = json.loads((REPO / "tracks/t3-topology/examples/dense_1b_16tiles-v3.json"
                      ).read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    doc["workload"]["coherence"] = [{
        "pattern": "READ_SHARED", "home_rank": 0, "writer_rank": None,
        "line_bytes": 64, "lines": 2, "traffic_class": "coherence"}]
    with pytest.raises(CompileRequestV3SchemaError, match="sharers"):
        CompileRequestV3.from_dict(doc)


def test_lowering_expands_declared_coherence_with_its_class():
    request = _v4_request(coherence=[_coherence()])
    lowered = lower_compile_workload(request)
    ops = lowered.graph.of_kind("COHERENCE")
    assert len(ops) == 1
    assert dict(lowered.traffic_class_by_operation)[ops[0].operation_id] \
        == "coherence"
    assert "coherence" in lowered.classes


def test_class_registry_unions_collectives_and_coherence():
    from veritx_dse.model.compile_model import (
        CollectiveDimension, CollectiveIntent, CollectiveKind,
    )
    request = _v4_request(
        collectives=[CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP,
            payload_bytes=64, traffic_class="tp_collective")],
        coherence=[_coherence()])
    assert derive_v3_traffic_classes(request) == ("coherence", "tp_collective")


def test_coherence_scoped_requirement_passes_scope_validation():
    import dataclasses
    from veritx_dse.application.requirements import validate_requirement_scopes
    doc = json.loads((REPO / "tracks/t3-topology/examples/dense_1b_16tiles-v3.json"
                      ).read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    doc["workload"]["coherence"] = [{
        "pattern": "READ_SHARED", "home_rank": 0, "writer_rank": None,
        "sharers": [1, 2], "line_bytes": 64, "lines": 2,
        "traffic_class": "coherence"}]
    request = CompileRequestV3.from_dict(doc)
    scoped = dataclasses.replace(request, requirements=tuple(
        list(request.requirements) + [RequirementV3(
            traffic_class="coherence", qos_class=QoSClass.LATENCY_CRITICAL,
            latency_ceiling_cycles=100000)]))
    assert "coherence" in validate_requirement_scopes(scoped)
