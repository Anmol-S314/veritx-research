"""Canonical workload-driven traffic projection.

`SynthesisTrafficMatrix.from_messages` is the one projection from a real
logical-message stream into an NxN demand matrix the synthesizers consume.
These tests pin: provenance binding, byte/message units, and that absence
and malformed input REFUSE (never a uniform fallback).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

DSE = Path(__file__).parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.model.compile_model import CompileRequestV3  # noqa: E402
from veritx_dse.synthesis.traffic import (  # noqa: E402
    SynthesisTrafficError, SynthesisTrafficMatrix,
)
from veritx_dse.workload.intent_lowering import lower_compile_workload  # noqa: E402
from veritx_dse.workload.messages import LogicalMessageArtifactV2  # noqa: E402

EX = REPO / "tracks/t3-topology/examples"

def _artifact(name: str) -> LogicalMessageArtifactV2:
    doc = json.loads((EX / name).read_text(encoding="utf-8"))
    req = CompileRequestV3.from_dict(doc)
    return LogicalMessageArtifactV2(lower_compile_workload(req).graph)

class _Msg:
    def __init__(self, mid, src, dst, size):
        self.message_id, self.src_rank, self.dst_rank = mid, src, dst
        self.payload_bytes = size

def test_projection_binds_the_message_artifact():
    art = _artifact("llama_dense_64tiles-v3.json")
    m = SynthesisTrafficMatrix.from_message_artifact(art)
    assert m.source_artifact_id == art.message_artifact_id()
    assert m.dimension == art.participant_count == 8
    assert m.unit == "bytes" and m.aggregation == "sum_over_workload"
    assert m.total_demand() == float(
        sum(msg.payload_bytes for msg in art.messages))

def test_projection_counts_each_direction():
    art = _artifact("llama_dense_64tiles-v3.json")
    m = SynthesisTrafficMatrix.from_message_artifact(art)
    assert all(m.values[i][i] == 0 for i in range(m.dimension))
    assert m.total_demand() > 0

def test_unit_messages_is_a_distinct_identity():
    art = _artifact("llama_dense_64tiles-v3.json")
    by_bytes = SynthesisTrafficMatrix.from_message_artifact(art, unit="bytes")
    by_msgs = SynthesisTrafficMatrix.from_message_artifact(art, unit="messages")
    assert by_msgs.total_demand() == float(len(art.messages))
    assert by_msgs.traffic_id() != by_bytes.traffic_id()

def test_empty_stream_refuses():
    with pytest.raises(SynthesisTrafficError, match="empty"):
        SynthesisTrafficMatrix.from_messages(
            [], source_artifact_id="sha256:x", dimension=4)

def test_out_of_namespace_rank_refuses():
    with pytest.raises(SynthesisTrafficError, match="outside"):
        SynthesisTrafficMatrix.from_messages(
            [_Msg("m", 0, 9, 100)], source_artifact_id="sha256:x", dimension=4)

def test_self_message_refuses():
    with pytest.raises(SynthesisTrafficError, match="self-message"):
        SynthesisTrafficMatrix.from_messages(
            [_Msg("m", 2, 2, 100)], source_artifact_id="sha256:x", dimension=4)

def test_flits_unit_refuses():
    with pytest.raises(SynthesisTrafficError, match="flit width"):
        SynthesisTrafficMatrix.from_messages(
            [_Msg("m", 0, 1, 100)], source_artifact_id="sha256:x", dimension=4,
            unit="flits")

def test_round_trip_preserves_identity():
    art = _artifact("qwen3_moe_tp2_ep4_16tiles-v3.json")
    m = SynthesisTrafficMatrix.from_message_artifact(art)
    back = SynthesisTrafficMatrix.from_dict(m.to_dict())
    assert back.traffic_id() == m.traffic_id()

def test_bo_builder_consumes_the_canonical_matrix(tmp_path):
    from veritx_dse.synthesis.bo_synthesizer import build_traffic_matrix
    art = _artifact("llama_dense_64tiles-v3.json")
    m = SynthesisTrafficMatrix.from_message_artifact(art)
    T = build_traffic_matrix(m, m.dimension)
    assert isinstance(T, np.ndarray)
    assert T.shape == (m.dimension, m.dimension)
    assert float(T.sum()) == m.total_demand()

def test_bo_builder_refuses_a_demandless_source(tmp_path):
    from veritx_dse.synthesis.bo_synthesizer import build_traffic_matrix
    empty = tmp_path / "empty.trace"
    empty.write_text("# only a comment\n")
    with pytest.raises(SynthesisTrafficError):
        build_traffic_matrix(empty, 4)

def test_bo_builder_parses_trace_sizes(tmp_path):
    from veritx_dse.synthesis.bo_synthesizer import build_traffic_matrix
    t = tmp_path / "t.trace"
    t.write_text("0 0 0 1 64\n1 1 0 0 128\n")
    T = build_traffic_matrix(t, 2)
    assert T[0][1] == 64 and T[1][0] == 128
    assert T[0][0] == 0 and T[1][1] == 0

def test_milp_loader_accepts_the_canonical_document(tmp_path):
    from veritx_dse.synthesis.milp_topology_v2 import load_matrix
    art = _artifact("llama_dense_64tiles-v3.json")
    m = SynthesisTrafficMatrix.from_message_artifact(art)
    doc = tmp_path / "m.json"
    doc.write_text(json.dumps(m.to_dict()))
    T = load_matrix(doc)
    assert T.shape == (m.dimension, m.dimension)
    assert float(T.sum()) == m.total_demand()
    assert float(load_matrix(m).sum()) == m.total_demand()
