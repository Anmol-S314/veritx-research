"""tests/test_et_graph.py — M3: trace-row projection from WorkloadGraph.

rows_from_graph is the graph → converter-dialect bridge: the same
11-field/marker grammar rows_from_artifact emits, in the graph's total
order. Proven by round trip (source rows → graph → identical rows),
by refusal parity on dialect limits, and by a real converter run with
read-back conservation when the converter is importable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.model.parallelism import ParallelismArtifact  # noqa: E402
from veritx_dse.workload.canonical_graph import (  # noqa: E402
    KIND_COLLECTIVE, OperationNode, WorkloadGraph, WorkloadSemantics,
    collective_detail, compute_detail,
)
from veritx_dse.workload.lowering import (  # noqa: E402
    UnsupportedSemantic, build_lowering_manifest_graph,
    et_readback_conservation_graph, lower_to_et_graph, rows_from_graph,
)
from veritx_dse.workload.migration import (  # noqa: E402
    workload_graph_from_trace_rows,
)

PA = ParallelismArtifact(tp=1, pp=1, ep=1, dp=4)

ROWS = [
    ("layer0", "100", "LOCAL", "1024", "LOCAL", "8192", "LOCAL", "512",
     "NONE", "0", "BATCH_1"),
    ("layer1", "200", "LOCAL", "1024", "LOCAL", "8192", "LOCAL", "512",
     "ALLREDUCE", "4096", "BATCH_1"),
]


def _graph():
    return workload_graph_from_trace_rows(
        ROWS, parallelism=PA, participant_count=4)


class TestRowProjection:
    def test_round_trip_source_rows(self):
        """Source rows → graph → identical rows (the M3 ET proof)."""
        proj = rows_from_graph(_graph())
        assert list(proj.rows) == [tuple(r) for r in ROWS]
        assert proj.header_line.startswith("COLOCATED")

    def test_compute_row_shape(self):
        proj = rows_from_graph(_graph())
        row = proj.rows[0]
        assert len(row) == 11
        assert row[0] == "layer0"
        assert row[8] == "NONE"

    def test_collective_rides_layer_comm_column(self):
        proj = rows_from_graph(_graph())
        assert proj.rows[1][8] == "ALLREDUCE"
        assert proj.rows[1][9] == "4096"
        assert proj.comm_op_by_row[1] == "op1.comm"

    def test_trailing_collective_flushes_standalone(self):
        g = workload_graph_from_trace_rows(
            [("layer0", "100", "LOCAL", "1024", "LOCAL", "8192",
              "LOCAL", "512", "NONE", "0", "BATCH_1")],
            parallelism=PA, participant_count=4)
        from veritx_dse.workload.canonical_graph import OperationNode as N
        ops = tuple(g.operations) + (N(
            "c9", KIND_COLLECTIVE, ("op0",), collective_detail(
                collective_kind="ALLGATHER", participants=(0, 1, 2, 3),
                payload_bytes=2048, participant_count=4, scope=None)),)
        from veritx_dse.workload.canonical_graph import WorkloadGraph as W
        from veritx_dse.workload.canonical_graph import (
            WorkloadSemantics as S)
        g2 = W(parallelism=PA, participant_count=4, operations=ops,
               semantics=S())
        proj = rows_from_graph(g2)
        assert proj.rows[-1][8] == "ALLGATHER"
        assert proj.rows[-1][9] == "2048"


class TestDialectLimits:
    def _op(self, kind, detail, deps=()):
        return OperationNode("x0", kind, deps, detail)

    def test_broadcast_refuses_et_but_projects_for_inspection(self):
        from veritx_dse.workload.canonical_graph import collective_detail
        g = WorkloadGraph(
            parallelism=PA, participant_count=4,
            operations=(OperationNode(
                "b0", KIND_COLLECTIVE, (), collective_detail(
                    collective_kind="BROADCAST", participants=(0, 1, 2, 3),
                    payload_bytes=512, participant_count=4, scope=None,
                    source=1)),),
            semantics=WorkloadSemantics())
        with pytest.raises(UnsupportedSemantic):
            rows_from_graph(g, target="astra_chakra_et")
        proj = rows_from_graph(g, target="inspection")
        assert proj.root_by_row[0] == 1

    def test_p2p_refuses_et(self):
        from veritx_dse.workload.canonical_graph import p2p_detail
        from veritx_dse.workload.canonical_graph import KIND_P2P
        g = WorkloadGraph(
            parallelism=PA, participant_count=4,
            operations=(OperationNode(
                "t0", KIND_P2P, (), p2p_detail(
                    role="TRANSFER", src_rank=0, dst_rank=2,
                    payload_bytes=300, participant_count=4)),),
            semantics=WorkloadSemantics())
        with pytest.raises(UnsupportedSemantic):
            rows_from_graph(g, target="astra_chakra_et")

    def test_multicast_refuses_et(self):
        from veritx_dse.workload.canonical_graph import (
            KIND_MULTICAST, multicast_detail,
        )
        g = WorkloadGraph(
            parallelism=PA, participant_count=4,
            operations=(OperationNode(
                "m0", KIND_MULTICAST, (), multicast_detail(
                    source_rank=0, destinations=(1, 2, 3),
                    payload_bytes=256,
                    replication="SOURCE_REPLICATION",
                    participant_count=4)),),
            semantics=WorkloadSemantics())
        with pytest.raises(UnsupportedSemantic):
            rows_from_graph(g, target="astra_chakra_et")


def _converter_available():
    try:
        import chakra.src.converter.llm_converter  # noqa: F401
        return True
    except ImportError:
        return False


requires_converter = pytest.mark.skipif(
    not _converter_available(), reason="chakra converter not importable")


@requires_converter
class TestRealConverter:
    def test_lower_and_conserve(self, tmp_path):
        g = _graph()
        lowered = lower_to_et_graph(
            g, str(tmp_path / "et" / "tiny"), num_npus=4,
            num_npu_group=1)
        assert lowered.et_count == 4
        cons = et_readback_conservation_graph(
            g, lowered.et_paths, num_npus=4, num_npu_group=1)
        assert cons.comm_bytes_conserved
        manifest = build_lowering_manifest_graph(g, lowered, "astra")
        assert manifest.semantic_losses == []
        assert manifest.logical_bytes == 4096
