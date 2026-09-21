"""tests/test_canonical_workload_graph.py — slice 2c step 1/2.

The canonical authority's own contract: schema closure, honest absence,
the participant namespace, the eight kinds, structural region laws, and
content identity. Nothing consumes the graph yet, so these tests are the
whole specification of what the migration must preserve.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.core.artifact import EvidenceInvalid, InvalidInput  # noqa: E402
from veritx_dse.core.errors import (  # noqa: E402
    UnsupportedSchedule, UnsupportedSemantics,
)
from veritx_dse.model.parallelism import ParallelismArtifact  # noqa: E402
from veritx_dse.workload.canonical_graph import (  # noqa: E402
    ALL_KINDS, KIND_COLLECTIVE, KIND_COMPUTE, KIND_EXPERT_BEGIN,
    KIND_EXPERT_END, KIND_MULTICAST, KIND_P2P, KIND_PIM_BEGIN, KIND_PIM_END,
    OperationNode, SCOPE_ALL, WorkloadGraph, WorkloadSemantics,
    collective_detail, compute_detail, expert_detail, multicast_detail,
    p2p_detail, pim_detail, pim_end_detail,
)
from veritx_dse.workload.collectives import collective_schedule  # noqa: E402

PARALLELISM = ParallelismArtifact(tp=4, pp=1, ep=1, dp=2)
WORLD = 8
PARTICIPANTS = 4          # the multi-instance law: 4 != 8


def compute(op_id, *, deps=(), duration=100, **kw):
    return OperationNode(op_id, KIND_COMPUTE, deps,
                         compute_detail(duration_ns=duration, **kw))


def collective(op_id, kind="ALLREDUCE", *, deps=(), participants=(0, 1, 2, 3),
               payload=1024, scope=None, source=None):
    return OperationNode(op_id, KIND_COLLECTIVE, deps,
                         collective_detail(
                             collective_kind=kind, participants=participants,
                             payload_bytes=payload,
                             participant_count=PARTICIPANTS, scope=scope,
                             source=source))


def graph(*ops, participant_count=PARTICIPANTS, semantics=None,
          provenance=None):
    return WorkloadGraph(parallelism=PARALLELISM,
                         participant_count=participant_count,
                         operations=tuple(ops),
                         semantics=semantics or WorkloadSemantics(),
                         provenance=provenance)


class TestParticipantNamespace:
    def test_participant_count_is_not_world_size(self):
        g = graph(collective("c0"))
        assert g.parallelism.world_size == WORLD == 8
        assert g.participant_count == 4
        assert g.participant_count != g.parallelism.world_size

    def test_ranks_validate_against_participants_not_world(self):
        """Rank 4 is a legal WORLD rank but outside the trace namespace."""
        with pytest.raises(InvalidInput, match="outside the participant"):
            collective("c0", participants=(0, 1, 4, 5))

    def test_participant_count_is_identity_bearing(self):
        a = graph(collective("c0"), participant_count=4)
        b = graph(collective("c0"), participant_count=8)
        assert a.workload_id() != b.workload_id()


class TestOperationVocabulary:
    def test_all_eight_kinds_are_constructible(self):
        ops = [
            compute("k0"),
            collective("k1"),
            OperationNode("k2", KIND_P2P, (),
                          p2p_detail(role="TRANSFER", src_rank=0, dst_rank=1,
                                     payload_bytes=64,
                                     participant_count=PARTICIPANTS)),
            OperationNode("k3", KIND_MULTICAST, (),
                          multicast_detail(source_rank=0, destinations=(1, 2),
                                           payload_bytes=64,
                                           replication="SOURCE_REPLICATION",
                                           participant_count=PARTICIPANTS)),
            OperationNode("k4", KIND_EXPERT_BEGIN, (),
                          expert_detail(expert_num=0, participant_count=4)),
            OperationNode("k5", KIND_EXPERT_END, (),
                          expert_detail(participant_count=4)),
            OperationNode("k6", KIND_PIM_BEGIN, (), pim_detail(channel=1)),
            OperationNode("k7", KIND_PIM_END, (), pim_end_detail()),
        ]
        g = graph(*ops)
        assert {op.kind for op in g.operations} == set(ALL_KINDS)

    def test_unknown_kind_refuses_immediately(self):
        """F14 ruling: unknown operations never enter a valid workload."""
        with pytest.raises(InvalidInput, match="unknown kind"):
            OperationNode("x", "NOPE", (), None)

    def test_detail_schema_is_closed_per_kind(self):
        with pytest.raises(InvalidInput, match="unknown detail fields"):
            OperationNode("x", KIND_COMPUTE, (),
                          {"duration_ns": 1, "fabric_rank": 3})

    def test_one_payload_per_operation_no_side_lists(self):
        """The node carries its collective; there is no second list."""
        g = graph(collective("c0", payload=2048))
        node = g.by_id("c0")
        assert node.detail["payload_bytes"] == 2048
        assert not hasattr(g, "collectives")
        assert not hasattr(g, "p2p_transfers")
        assert not hasattr(g, "multicasts")


class TestAbsenceIsNotADefault:
    def test_owner_phase_step_default_to_absent(self):
        g = graph(collective("c0"))
        node = g.by_id("c0")
        assert node.owner is None
        assert node.phase is None
        assert node.step is None
        assert node.declared_metadata() == {}

    def test_declared_metadata_is_preserved_exactly(self):
        node = OperationNode("c0", KIND_COLLECTIVE, (),
                             collective_detail(
                                 collective_kind="ALLREDUCE",
                                 participants=(0, 1, 2, 3), payload_bytes=8,
                                 participant_count=4),
                             owner=2, phase="DECODE", step=3)
        g = graph(node)
        assert g.by_id("c0").declared_metadata() == {
            "owner": 2, "phase": "DECODE", "step": 3}

    def test_semantics_absence_is_preserved(self):
        """Phase-9 declared no global phase and no routing policy."""
        g = graph(compute("c0"))
        assert g.semantics.phase is None
        assert g.semantics.routing_policy is None
        assert g.to_dict()["semantics"]["phase"] is None

    def test_absent_metadata_is_identity_bearing(self):
        base = collective("c0")
        declared = OperationNode("c0", KIND_COLLECTIVE, (),
                                 base.detail, phase="DECODE")
        assert graph(base).workload_id() != graph(declared).workload_id()


class TestCollectiveScopeThreeStates:
    def test_none_and_all_are_different_states(self):
        undeclared = graph(collective("c0", scope=None))
        all_dims = graph(collective("c0", scope=SCOPE_ALL))
        assert undeclared.by_id("c0").detail["scope"] is None
        assert all_dims.by_id("c0").detail["scope"] == "ALL"
        # F18: distinct semantics => distinct identity
        assert undeclared.workload_id() != all_dims.workload_id()

    def test_explicit_mask_is_a_third_state(self):
        masked = graph(collective("c0", scope=(True, False, False, False)))
        assert masked.by_id("c0").detail["scope"] == (True, False, False,
                                                      False)
        assert masked.workload_id() != \
            graph(collective("c0", scope=SCOPE_ALL)).workload_id()

    def test_bad_scope_refuses(self):
        with pytest.raises(InvalidInput, match="scope must be"):
            collective("c0", scope=("tp",))
        with pytest.raises(InvalidInput, match="scope must be"):
            collective("c0", scope=())

    def test_broadcast_requires_an_explicit_source(self):
        with pytest.raises(InvalidInput, match="explicit source"):
            collective("c0", kind="BROADCAST")
        node = collective("c0", kind="BROADCAST", source=2)
        assert node.detail["source"] == 2

    def test_broadcast_source_must_be_a_participant(self):
        with pytest.raises(InvalidInput, match="not among"):
            collective("c0", kind="BROADCAST", participants=(0, 1),
                       source=2)

    def test_non_broadcast_refuses_a_source(self):
        with pytest.raises(InvalidInput, match="must not declare a source"):
            collective("c0", kind="ALLREDUCE", source=0)


class TestP2PRoles:
    def test_transfer_send_recv_are_distinct(self):
        roles = {}
        for i, role in enumerate(("TRANSFER", "SEND", "RECV")):
            roles[role] = p2p_detail(role=role, src_rank=0, dst_rank=1,
                                     payload_bytes=8,
                                     participant_count=PARTICIPANTS)
        assert roles["TRANSFER"]["role"] == "TRANSFER"
        assert roles["SEND"]["role"] != roles["RECV"]["role"]

    def test_unknown_role_refuses(self):
        with pytest.raises(InvalidInput, match="p2p role"):
            p2p_detail(role="PAIR", src_rank=0, dst_rank=1, payload_bytes=8,
                       participant_count=PARTICIPANTS)

    def test_same_endpoint_refuses(self):
        with pytest.raises(InvalidInput, match="must differ"):
            p2p_detail(role="TRANSFER", src_rank=1, dst_rank=1,
                       payload_bytes=8, participant_count=PARTICIPANTS)


class TestExpertSemantics:
    def test_expert_end_can_carry_the_combine_collective(self):
        node = OperationNode("e1", KIND_EXPERT_END, (),
                             expert_detail(collective_kind="REDUCESCATTER",
                                           participants=(0, 1), payload_bytes=4096,
                                           participant_count=PARTICIPANTS))
        assert node.detail["collective_kind"] == "REDUCESCATTER"
        assert node.detail["payload_bytes"] == 4096

    def test_expert_begin_can_carry_the_dispatch_collective(self):
        node = OperationNode("e0", KIND_EXPERT_BEGIN, (),
                             expert_detail(expert_num=0,
                                           collective_kind="ALLGATHER",
                                           participants=(0, 1),
                                           payload_bytes=4096,
                                           participant_count=PARTICIPANTS))
        assert node.detail["expert_num"] == 0
        assert node.detail["collective_kind"] == "ALLGATHER"

    def test_payload_without_a_collective_refuses(self):
        with pytest.raises(InvalidInput, match="require a collective_kind"):
            expert_detail(participants=(0, 1), payload_bytes=8,
                          participant_count=PARTICIPANTS)

    def test_marker_without_a_collective_is_legal(self):
        assert expert_detail(expert_num=1,
                             participant_count=PARTICIPANTS)["collective_kind"] \
            is None


class TestRegionStructure:
    def test_unclosed_expert_region_refuses(self):
        with pytest.raises(InvalidInput, match="unclosed EXPERT_BEGIN"):
            graph(compute("k0"),
                  OperationNode("e0", KIND_EXPERT_BEGIN, (),
                                expert_detail(participant_count=4)),
                  compute("k1"))

    def test_stray_expert_end_refuses(self):
        with pytest.raises(InvalidInput, match="stray EXPERT_END"):
            graph(compute("k0"),
                  OperationNode("e1", KIND_EXPERT_END, (),
                                expert_detail(participant_count=4)))

    def test_balanced_expert_region_passes(self):
        g = graph(compute("k0"),
                  OperationNode("e0", KIND_EXPERT_BEGIN, (),
                                expert_detail(expert_num=0,
                                              participant_count=4)),
                  compute("k1"),
                  OperationNode("e1", KIND_EXPERT_END, (),
                                expert_detail(participant_count=4)))
        assert not g.requires_pim

    def test_unclosed_and_stray_pim_regions_refuse(self):
        with pytest.raises(InvalidInput, match="unclosed PIM_BEGIN"):
            graph(compute("k0"),
                  OperationNode("p0", KIND_PIM_BEGIN, (),
                                pim_detail(channel=0)))
        with pytest.raises(InvalidInput, match="stray PIM_END"):
            graph(compute("k0"),
                  OperationNode("p1", KIND_PIM_END, (), pim_end_detail()))

    def test_pim_region_survives_with_its_channel(self):
        g = graph(compute("k0"),
                  OperationNode("p0", KIND_PIM_BEGIN, (),
                                pim_detail(channel=1)),
                  compute("k1"),
                  OperationNode("p1", KIND_PIM_END, (), pim_end_detail()))
        assert g.requires_pim
        assert g.by_id("p0").detail["channel"] == 1


class TestDagAndOrdering:
    def test_dependencies_must_exist(self):
        with pytest.raises(InvalidInput, match="unknown operation"):
            graph(compute("c0", deps=("missing",)))

    def test_cycle_refuses(self):
        a = compute("a", deps=("b",))
        b = compute("b", deps=("a",))
        with pytest.raises(InvalidInput, match="cycle"):
            graph(a, b)

    def test_self_dependency_refuses(self):
        with pytest.raises(InvalidInput, match="depends on itself"):
            compute("a", deps=("a",))

    def test_duplicate_ids_refuse(self):
        with pytest.raises(InvalidInput, match="duplicate operation id"):
            graph(compute("a"), compute("a"))

    def test_identity_is_construction_order_independent(self):
        a, b = compute("a"), compute("b", deps=("a",))
        assert graph(a, b).workload_id() == graph(b, a).workload_id()

    def test_identity_covers_the_dependency_relation(self):
        """Same operations, different DAG => different identity."""
        a, b = compute("a"), compute("b")
        chained = graph(a, OperationNode("b", KIND_COMPUTE, ("a",),
                                         b.detail))
        independent = graph(a, b)
        assert chained.workload_id() != independent.workload_id()


class TestIdentityAndProvenance:
    def test_identity_is_content_derived(self):
        g = graph(collective("c0"))
        assert g.workload_id().startswith("sha256:")
        assert g.to_dict()["workload_id"] == g.workload_id()

    def test_provenance_does_not_move_identity(self):
        a = graph(compute("c0"), provenance={"source": "run-1"})
        b = graph(compute("c0"), provenance={"source": "run-2"})
        assert a.workload_id() == b.workload_id()

    def test_label_does_not_move_identity(self):
        """F23: source spelling is not scientific identity."""
        a = graph(OperationNode("c0", KIND_COMPUTE, (),
                                compute_detail(duration_ns=1), label="attn"))
        b = graph(OperationNode("c0", KIND_COMPUTE, (),
                                compute_detail(duration_ns=1),
                                label="attention_0"))
        assert a.workload_id() == b.workload_id()

    def test_semantics_moves_identity(self):
        a = graph(compute("c0"), semantics=WorkloadSemantics())
        b = graph(compute("c0"),
                  semantics=WorkloadSemantics(phase="DECODE"))
        assert a.workload_id() != b.workload_id()


class TestRoundTrip:
    def test_strict_roundtrip_preserves_identity(self):
        g = graph(compute("c0"), collective("c1", deps=("c0",)),
                  provenance={"run": "r1"})
        doc = g.to_dict()
        again = WorkloadGraph.from_dict(doc, strict=True)
        assert again.workload_id() == g.workload_id()
        assert again.to_dict() == doc

    def test_forged_workload_id_refuses(self):
        doc = graph(compute("c0")).to_dict()
        doc["workload_id"] = "sha256:" + "0" * 64
        with pytest.raises(EvidenceInvalid, match="content forged"):
            WorkloadGraph.from_dict(doc, strict=True)

    def test_missing_embedded_id_refuses_when_strict(self):
        doc = graph(compute("c0")).to_dict()
        del doc["workload_id"]
        with pytest.raises(EvidenceInvalid, match="no embedded"):
            WorkloadGraph.from_dict(doc, strict=True)

    def test_unknown_top_level_field_refuses(self):
        doc = graph(compute("c0")).to_dict()
        doc["extra"] = True
        with pytest.raises(InvalidInput, match="unknown fields"):
            WorkloadGraph.from_dict(doc)

    def test_wrong_type_tag_refuses(self):
        doc = graph(compute("c0")).to_dict()
        doc["type"] = "srota/SomethingElse"
        with pytest.raises(InvalidInput, match="type tag"):
            WorkloadGraph.from_dict(doc)


class TestDeclarationVsSchedule:
    """F9 corrected: a declaration is permissive, a schedule is strict."""

    def test_non_divisible_declaration_is_valid(self):
        g = graph(collective("c0", participants=(0, 1, 2), payload=1000))
        assert g.by_id("c0").detail["payload_bytes"] == 1000

    def test_exact_ring_schedule_refuses_the_same_shape(self):
        with pytest.raises(UnsupportedSchedule, match="B % k"):
            collective_schedule("ALLREDUCE", 3, 1000)

    def test_graph_never_contains_a_schedule_restriction(self):
        """The declaration must not carry a schedule's divisibility law."""
        g = graph(collective("c0", participants=(0, 1, 2), payload=1000))
        doc = g.to_dict()
        assert "steps" not in doc and "schedule" not in str(doc)
