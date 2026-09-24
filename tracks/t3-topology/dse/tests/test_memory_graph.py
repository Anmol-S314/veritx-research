"""tests/test_memory_graph.py — M3: the memory resolver over WorkloadGraph.

resolve_memory_graph is the runtime memory entry point: COMPUTE operand
bytes/locations come from the graph's closed COMPUTE detail, in the
graph's total order. Allocation, access chaining and conservation are
the shared core — proven here by parity with the artifact path on the
same operations, plus refusal parity.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.model.placement import (  # noqa: E402
    ParallelismShape,
)
from veritx_dse.workload.canonical import (  # noqa: E402
    Parallelism, WorkloadArtifact, build_compute_op,
)
from veritx_dse.workload.canonical_graph import (  # noqa: E402
    KIND_COLLECTIVE, OperationNode, WorkloadGraph, WorkloadSemantics,
    collective_detail, compute_detail,
)
from veritx_dse.workload.lowering import LoweringError  # noqa: E402
from veritx_dse.workload.lowering import UnsupportedSemantic  # noqa: E402
from veritx_dse.workload.memory_lowering import (  # noqa: E402
    MemorySystemDesign, resolve_memory, resolve_memory_graph,
)

DESIGN = MemorySystemDesign(hbm_devices=(0,))
PA = ParallelismShape(tp=1, pp=1, ep=1, dp=1)

BYTES = {"input_bytes": 1024, "weight_bytes": 8192, "output_bytes": 512}


def _graph_ops(suffix_loc="LOCAL"):
    return (
        OperationNode("op0", "COMPUTE", (), compute_detail(
            duration_ns=100, input_loc=suffix_loc, weight_loc=suffix_loc,
            output_loc=suffix_loc, batch_tag="BATCH_1",
            participant_count=1, **BYTES)),
        OperationNode("op1", "COMPUTE", ("op0",), compute_detail(
            duration_ns=100, input_loc=suffix_loc, weight_loc=suffix_loc,
            output_loc=suffix_loc, batch_tag="BATCH_1",
            participant_count=1, **BYTES)),
    )


def _graph(ops=None):
    ops = ops if ops is not None else _graph_ops()
    return WorkloadGraph(parallelism=PA, participant_count=1,
                         operations=ops, semantics=WorkloadSemantics())


def _artifact():
    ops = tuple(build_compute_op(op_id, duration_ns=100, **BYTES)
                for op_id in ("op0", "op1"))
    return WorkloadArtifact(
        workload_id="w", source_kind="test", parallelism=Parallelism(),
        num_participants=1, ops=ops)


class TestGraphParity:
    def test_same_regions_accesses_totals(self):
        from_graph = resolve_memory_graph(_graph(), DESIGN)
        from_art = resolve_memory(_artifact(), DESIGN)
        g, a = from_graph.artifact, from_art.artifact
        assert [r.region_id for r in g.regions] == \
            [r.region_id for r in a.regions]
        assert [r.size_bytes for r in g.regions] == \
            [r.size_bytes for r in a.regions]
        assert [(x.access_id, x.kind, list(x.dependencies))
                for x in g.accesses] == \
            [(x.access_id, x.kind, list(x.dependencies))
             for x in a.accesses]
        assert from_graph.workload_operand_bytes == \
            from_art.workload_operand_bytes == 2 * sum(BYTES.values())
        assert from_graph.conserved()
        assert g.source_workload_hash == _graph().workload_id()

    def test_comm_ops_and_markers_ignored(self):
        pa2 = ParallelismShape(tp=1, pp=1, ep=1, dp=2)
        ops = (OperationNode("c0", KIND_COLLECTIVE, (), collective_detail(
            collective_kind="ALLREDUCE", participants=(0, 1),
            payload_bytes=512, participant_count=2, scope=None)),
            OperationNode("op0", "COMPUTE", ("c0",), compute_detail(
                duration_ns=100, participant_count=2, **BYTES)),
            OperationNode("op1", "COMPUTE", ("op0",), compute_detail(
                duration_ns=100, participant_count=2, **BYTES)))
        g = WorkloadGraph(parallelism=pa2, participant_count=2,
                          operations=ops, semantics=WorkloadSemantics())
        res = resolve_memory_graph(g, DESIGN, issue_node=0)
        assert res.workload_operand_bytes == 2 * sum(BYTES.values())
        assert res.conserved()


class TestGraphRefusals:
    def test_remote_location_refuses(self):
        ops = _graph_ops()
        bad = (OperationNode("op0", "COMPUTE", (), compute_detail(
            duration_ns=100, input_loc="REMOTE:0", weight_loc="LOCAL",
            output_loc="LOCAL", batch_tag="BATCH_1",
            participant_count=1, **BYTES)), ops[1])
        with pytest.raises(UnsupportedSemantic):
            resolve_memory_graph(_graph(bad), DESIGN)

    def test_no_memory_demand_refuses(self):
        ops = (OperationNode("op0", "COMPUTE", (), compute_detail(
            duration_ns=100, input_bytes=None, weight_bytes=None,
            output_bytes=None, participant_count=1)),)
        with pytest.raises(LoweringError):
            resolve_memory_graph(_graph(ops), DESIGN)

    def test_ambiguous_order_refuses(self):
        """The positional memory stream needs a total order: two
        independent ops have none, so resolution refuses rather than
        inventing one."""
        from veritx_dse.core.errors import InvalidInput
        ops = (OperationNode("op0", "COMPUTE", (), compute_detail(
            duration_ns=100, participant_count=1, **BYTES)),
            OperationNode("op1", "COMPUTE", (), compute_detail(
                duration_ns=100, participant_count=1, **BYTES)))
        with pytest.raises(InvalidInput):
            resolve_memory_graph(_graph(ops), DESIGN)

    def test_multi_participant_needs_attribution(self):
        pa2 = ParallelismShape(tp=1, pp=1, ep=1, dp=2)
        ops = (OperationNode("op0", "COMPUTE", (), compute_detail(
            duration_ns=100, participant_count=2, **BYTES)),)
        g = WorkloadGraph(parallelism=pa2, participant_count=2,
                          operations=ops, semantics=WorkloadSemantics())
        with pytest.raises(LoweringError):
            resolve_memory_graph(g, DESIGN)
        res = resolve_memory_graph(g, DESIGN, issue_node=1)
        assert res.conserved()
