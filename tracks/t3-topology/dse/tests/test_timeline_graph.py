"""tests/test_timeline_graph.py — M3: the timeline over WorkloadGraph.

build_timeline_graph is the runtime timeline entry point: op order is
the graph's total order, COMPUTE legs are identical, comm bytes come
from each kind's closed detail. Composition, stall math and verdicts
are the shared core — proven here by parity with the artifact path on
equivalent operations.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.model.parallelism import ParallelismArtifact  # noqa: E402
from veritx_dse.workload.canonical import (  # noqa: E402
    Parallelism, WorkloadArtifact, build_collective_op, build_compute_op,
)
from veritx_dse.workload.canonical_graph import (  # noqa: E402
    KIND_COLLECTIVE, OperationNode, WorkloadGraph, WorkloadSemantics,
    collective_detail, compute_detail,
)
from veritx_dse.workload.timeline import (  # noqa: E402
    BackendBinding, OpService, ServiceBinding, TimelineError,
    build_timeline, build_timeline_graph,
)

PA = ParallelismArtifact(tp=1, pp=1, ep=1, dp=4)
BINDING = ServiceBinding(
    compute=BackendBinding("c", "COMPUTE_MODEL", ns_per_cycle=2.0),
    net=BackendBinding("b", "NETWORK_CYCLE_SIMULATION", ns_per_cycle=2.0))


def _services():
    return {"c1": OpService(compute_cycles=100),
            "a1": OpService(net_cycles=500)}


def _artifact():
    return WorkloadArtifact(
        workload_id="t", source_kind="handbuilt",
        parallelism=Parallelism(), num_participants=4,
        ops=(build_compute_op("c1", duration_ns=1000),
             build_collective_op("a1", "ALLREDUCE", bytes=4096,
                                 participants=(0, 1, 2, 3), scope="ALL")))


def _graph():
    return WorkloadGraph(
        parallelism=PA, participant_count=4,
        operations=(
            OperationNode("c1", "COMPUTE", (), compute_detail(
                duration_ns=1000, participant_count=4)),
            OperationNode("a1", KIND_COLLECTIVE, ("c1",),
                          collective_detail(
                              collective_kind="ALLREDUCE",
                              participants=(0, 1, 2, 3), payload_bytes=4096,
                              participant_count=4, scope="ALL"))),
        semantics=WorkloadSemantics())


class TestGraphParity:
    def test_same_records_same_verdict(self):
        svc = _services()
        t_art = build_timeline(_artifact(), BINDING, svc)
        t_graph = build_timeline_graph(_graph(), BINDING, svc)
        assert [o.op_id for o in t_graph.ops] == \
            [o.op_id for o in t_art.ops]
        assert [o.legs for o in t_graph.ops] == \
            [o.legs for o in t_art.ops]
        assert [o.finish for o in t_graph.ops] == \
            [o.finish for o in t_art.ops]
        assert t_graph.attribution.verdict == t_art.attribution.verdict
        assert t_graph.service_totals == t_art.service_totals
        assert t_graph.artifact_hash == _graph().workload_id()

    def test_missing_service_refuses(self):
        with pytest.raises(TimelineError):
            build_timeline_graph(_graph(), BINDING, {})

    def test_ambiguous_order_refuses(self):
        ops = (OperationNode("c1", "COMPUTE", (), compute_detail(
            duration_ns=1000, participant_count=4)),
            OperationNode("c2", "COMPUTE", (), compute_detail(
                duration_ns=1000, participant_count=4)))
        g = WorkloadGraph(parallelism=PA, participant_count=4,
                          operations=ops, semantics=WorkloadSemantics())
        with pytest.raises(Exception):
            build_timeline_graph(g, BINDING, {"c1": OpService(
                compute_cycles=10), "c2": OpService(compute_cycles=10)})
