"""tests/test_logical_messages_v2.py — M1.2: logical messages from the graph.

`LogicalMessageArtifactV2` is built from ONE traversal of
`WorkloadGraph.ordered_operations()`. There is no OperationGraph parent and
no CollectiveIntent/P2PTransfer/MulticastIntent side list. The parent
identity is `workload_id`, the participant namespace is the graph's
`participant_count` (WORKLOAD-UNION-MATRIX F15), and BROADCAST honours its
declared source instead of assuming participants[0].
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.core.artifact import EvidenceInvalid, InvalidInput  # noqa: E402
from veritx_dse.core.errors import UnsupportedSemantics  # noqa: E402
from veritx_dse.model.parallelism import ParallelismArtifact  # noqa: E402
from veritx_dse.workload.canonical_graph import (  # noqa: E402
    KIND_COLLECTIVE, KIND_COMPUTE, KIND_EXPERT_BEGIN, KIND_EXPERT_END,
    KIND_MULTICAST, KIND_P2P, KIND_PIM_CHANNEL, KIND_PIM_END, OperationNode,
    WorkloadGraph, WorkloadSemantics, collective_detail, compute_detail,
    expert_detail, multicast_detail, p2p_detail, pim_detail, pim_end_detail,
)
from veritx_dse.workload.collectives import collective_schedule  # noqa: E402
from veritx_dse.workload.messages import (  # noqa: E402
    LogicalMessageArtifactV2,
)

PARALLELISM = ParallelismArtifact(tp=4, pp=1, ep=1, dp=2)
WORLD = 8
PARTICIPANTS = 4          # the multi-instance law: 4 != 8


def graph(*ops, participant_count=PARTICIPANTS):
    return WorkloadGraph(parallelism=PARALLELISM,
                         participant_count=participant_count,
                         operations=tuple(ops),
                         semantics=WorkloadSemantics())


def collective(op_id, kind="ALLREDUCE", *, participants=(0, 1, 2, 3),
               payload=1024, scope=None, source=None):
    return OperationNode(op_id, KIND_COLLECTIVE, (),
                         collective_detail(
                             collective_kind=kind, participants=participants,
                             payload_bytes=payload,
                             participant_count=PARTICIPANTS, scope=scope,
                             source=source))


class TestKindSemantics:
    def test_broadcast_uses_the_declared_source_not_participants_zero(self):
        a = LogicalMessageArtifactV2(
            graph(collective("bc", "BROADCAST", source=2)))
        assert len(a.messages) == 3
        assert {m.src_rank for m in a.messages} == {2}
        assert {m.dst_rank for m in a.messages} == {0, 1, 3}

    def test_collective_message_count_equals_the_pinned_schedule(self):
        a = LogicalMessageArtifactV2(graph(collective("ar", "ALLREDUCE")))
        ref = collective_schedule("ALLREDUCE", 4, 1024)
        assert len(a.messages) == ref["message_count"]
        assert len(a.schedules) == 1
        assert a.schedules[0].collective_id == "ar"
        assert a.schedules[0].algorithm == "RING"
        a.validate_conservation()

    def test_alltoall_expands_every_ordered_pair(self):
        a = LogicalMessageArtifactV2(graph(collective("a2a", "ALLTOALL")))
        pairs = {(m.src_rank, m.dst_rank) for m in a.messages}
        assert pairs == {(i, j) for i in range(4) for j in range(4) if i != j}
        a.validate_conservation()

    def test_transfer_is_one_message(self):
        op = OperationNode("t", KIND_P2P, (),
                           p2p_detail(role="TRANSFER", src_rank=0, dst_rank=3,
                                      payload_bytes=64,
                                      participant_count=PARTICIPANTS))
        a = LogicalMessageArtifactV2(graph(op))
        assert [(m.src_rank, m.dst_rank, m.payload_bytes)
                for m in a.messages] == [(0, 3, 64)]
        assert a.schedules == ()

    @pytest.mark.parametrize("role", ["SEND", "RECV"])
    def test_send_recv_refuse_as_not_a_complete_transfer(self, role):
        op = OperationNode("t", KIND_P2P, (),
                           p2p_detail(role=role, src_rank=0, dst_rank=3,
                                      payload_bytes=64,
                                      participant_count=PARTICIPANTS))
        with pytest.raises(UnsupportedSemantics, match="not a complete"):
            LogicalMessageArtifactV2(graph(op))

    def test_multicast_replicates_to_each_declared_destination(self):
        op = OperationNode("mc", KIND_MULTICAST, (),
                           multicast_detail(source_rank=1,
                                            destinations=[0, 2, 3],
                                            payload_bytes=32,
                                            replication="SOURCE_REPLICATION",
                                            participant_count=PARTICIPANTS))
        a = LogicalMessageArtifactV2(graph(op))
        assert {(m.src_rank, m.dst_rank) for m in a.messages} == \
            {(1, 0), (1, 2), (1, 3)}

    def test_expert_region_without_a_collective_is_not_communication(self):
        begin = OperationNode("eb", KIND_EXPERT_BEGIN, (),
                              expert_detail(end=False,
                                            participant_count=PARTICIPANTS))
        end = OperationNode("ee", KIND_EXPERT_END, ("eb",),
                            expert_detail(end=True,
                                          participant_count=PARTICIPANTS))
        a = LogicalMessageArtifactV2(graph(begin, end))
        assert a.messages == ()

    def test_expert_region_with_a_collective_expands_it(self):
        begin = OperationNode("eb", KIND_EXPERT_BEGIN, (),
                              expert_detail(end=False, expert_num=0,
                                            collective_kind="ALLTOALL",
                                            participants=(0, 1, 2, 3),
                                            payload_bytes=256,
                                            participant_count=PARTICIPANTS))
        end = OperationNode("ee", KIND_EXPERT_END, ("eb",),
                            expert_detail(end=True, expert_num=0,
                                          participant_count=PARTICIPANTS))
        a = LogicalMessageArtifactV2(graph(begin, end))
        assert len(a.messages) == 12
        a.validate_conservation()

    def test_compute_and_pim_produce_no_network_message(self):
        ops = (
            OperationNode("c", KIND_COMPUTE, (),
                          compute_detail(duration_ns=10, input_bytes=8,
                                         weight_bytes=8, output_bytes=8,
                                         participant_count=PARTICIPANTS)),
            OperationNode("p", KIND_PIM_CHANNEL, ("c",),
                          pim_detail(channel=0, participant_count=PARTICIPANTS)),
            OperationNode("pe", KIND_PIM_END, ("p",),
                          pim_end_detail(participant_count=PARTICIPANTS)),
        )
        a = LogicalMessageArtifactV2(graph(*ops))
        assert a.messages == ()
        assert a.schedules == ()
        assert a.message_artifact_id()          # identity is still defined


class TestIdentity:
    def test_parent_is_the_workload_and_the_participant_namespace(self):
        a = LogicalMessageArtifactV2(graph(collective("ar")))
        ident = a.identity_dict()
        assert ident["workload_id"] == a.graph.workload_id()
        assert ident["participant_count"] == PARTICIPANTS
        assert ident["participant_count"] != WORLD
        assert "operation_graph_id" not in ident

    def test_participant_count_is_identity_bearing(self):
        a = LogicalMessageArtifactV2(graph(collective("ar")))
        b = LogicalMessageArtifactV2(
            graph(collective("ar"), participant_count=PARTICIPANTS + 1))
        assert a.message_artifact_id() != b.message_artifact_id()

    def test_payload_change_moves_the_message_identity(self):
        a = LogicalMessageArtifactV2(graph(collective("ar", payload=1024)))
        b = LogicalMessageArtifactV2(graph(collective("ar", payload=2048)))
        assert a.message_artifact_id() != b.message_artifact_id()

    def test_source_change_moves_the_broadcast_identity(self):
        a = LogicalMessageArtifactV2(
            graph(collective("bc", "BROADCAST", source=0)))
        b = LogicalMessageArtifactV2(
            graph(collective("bc", "BROADCAST", source=2)))
        assert a.message_artifact_id() != b.message_artifact_id()

    def test_identity_is_deterministic(self):
        g = graph(collective("ar"))
        ids = {LogicalMessageArtifactV2(g).message_artifact_id()
               for _ in range(5)}
        assert len(ids) == 1


class TestStrictLoader:
    def test_round_trip(self):
        g = graph(collective("ar"))
        a = LogicalMessageArtifactV2(g)
        again = LogicalMessageArtifactV2.from_dict(a.to_dict(), graph=g,
                                                   strict=True)
        assert again.message_artifact_id() == a.message_artifact_id()

    def test_tampered_message_row_refuses(self):
        g = graph(collective("ar"))
        a = LogicalMessageArtifactV2(g)
        d = a.to_dict()
        d["messages"][0]["dst_rank"] = 3
        with pytest.raises(EvidenceInvalid):
            LogicalMessageArtifactV2.from_dict(d, graph=g, strict=True)

    def test_another_graph_parent_refuses(self):
        g = graph(collective("ar"))
        other = graph(collective("bc", "BROADCAST", source=1))
        with pytest.raises(InvalidInput, match="workload_id"):
            LogicalMessageArtifactV2.from_dict(
                LogicalMessageArtifactV2(g).to_dict(), graph=other,
                strict=True)

    def test_participant_count_mismatch_refuses(self):
        g = graph(collective("ar"))
        other = graph(collective("ar"), participant_count=PARTICIPANTS + 1)
        d = LogicalMessageArtifactV2(g).to_dict()
        d["participant_count"] = PARTICIPANTS + 1
        with pytest.raises(InvalidInput):
            LogicalMessageArtifactV2.from_dict(d, graph=other, strict=True)
