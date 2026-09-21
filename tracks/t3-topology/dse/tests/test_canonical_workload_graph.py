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
from veritx_dse.core.errors import InvalidInput as InputError  # noqa: E402
from veritx_dse.model.parallelism import ParallelismArtifact  # noqa: E402
from veritx_dse.workload.canonical_graph import (  # noqa: E402
    ALL_KINDS, KIND_COLLECTIVE, KIND_COMPUTE, KIND_EXPERT_BEGIN,
    KIND_EXPERT_END, KIND_MULTICAST, KIND_P2P, KIND_PIM_CHANNEL, KIND_PIM_END,
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


def chain(*ops):
    """Link operations into the explicit dependency chain that positional
    source grammars (LLMServingSim/ET rows, Phase-9 ops) migrate to."""
    out = []
    previous: tuple[str, ...] = ()
    for op in ops:
        out.append(OperationNode(op.operation_id, op.kind, previous,
                                 op.detail, op.owner, op.phase, op.step,
                                 op.label))
        previous = (op.operation_id,)
    return tuple(out)


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
            OperationNode("k6", KIND_PIM_CHANNEL, (), pim_detail(channel=1)),
            OperationNode("k7", KIND_PIM_END, (), pim_end_detail()),
        ]
        g = graph(*chain(*ops))
        assert {op.kind for op in g.operations} == set(ALL_KINDS)

    def test_unknown_kind_refuses_immediately(self):
        """F14 ruling: unknown operations never enter a valid workload."""
        with pytest.raises(InvalidInput, match="unknown kind"):
            OperationNode("x", "NOPE", (), None)

    def test_detail_schema_is_closed_per_kind(self):
        with pytest.raises(InvalidInput, match="unknown fields"):
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
        with pytest.raises(InvalidInput, match="not a participating rank"):
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
        with pytest.raises(InvalidInput, match="P2P role"):
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
        with pytest.raises(InvalidInput, match="requires a collective_kind"):
            expert_detail(participants=(0, 1), payload_bytes=8,
                          participant_count=PARTICIPANTS)

    def test_marker_without_a_collective_is_legal(self):
        assert expert_detail(expert_num=1,
                             participant_count=PARTICIPANTS)["collective_kind"] \
            is None


class TestRegionStructure:
    def test_unclosed_expert_region_refuses(self):
        with pytest.raises(InputError, match="unclosed EXPERT_BEGIN"):
            graph(*chain(
                compute("k0"),
                OperationNode("e0", KIND_EXPERT_BEGIN, (),
                              expert_detail(participant_count=4)),
                compute("k1")))

    def test_stray_expert_end_refuses(self):
        with pytest.raises(InvalidInput, match="stray EXPERT_END"):
            graph(*chain(
                compute("k0"),
                OperationNode("e1", KIND_EXPERT_END, (),
                              expert_detail(end=True, participant_count=4))))

    def test_balanced_expert_region_passes(self):
        g = graph(*chain(
            compute("k0"),
            OperationNode("e0", KIND_EXPERT_BEGIN, (),
                          expert_detail(expert_num=0, participant_count=4)),
            compute("k1"),
            OperationNode("e1", KIND_EXPERT_END, (),
                          expert_detail(end=True, participant_count=4))))
        assert not g.requires_pim

    def test_unclosed_and_stray_pim_refuse(self):
        """PIM is a STATE MACHINE, not nesting: active -> END."""
        with pytest.raises(InvalidInput, match="ends while PIM mode"):
            graph(*chain(compute("k0"),
                         OperationNode("p0", KIND_PIM_CHANNEL, (),
                                       pim_detail(channel=0))))
        with pytest.raises(InvalidInput, match="stray PIM_END"):
            graph(*chain(compute("k0"),
                         OperationNode("p1", KIND_PIM_END, (),
                                       pim_end_detail())))

    def test_consecutive_channel_markers_are_legal(self):
        """The producer emits a marker per channel, even for EMPTY
        channels: PIM 0 / PIM 1 / rows / PIM END is one PIM session."""
        g = graph(*chain(
            OperationNode("p0", KIND_PIM_CHANNEL, (),
                          pim_detail(channel=0)),
            OperationNode("p1", KIND_PIM_CHANNEL, (),
                          pim_detail(channel=1)),
            compute("k1"),
            OperationNode("p2", KIND_PIM_END, (), pim_end_detail())))
        assert [op.detail.get("channel") for op in g.of_kind(
            KIND_PIM_CHANNEL)] == [0, 1]

    def test_two_separate_pim_sessions_are_legal(self):
        g = graph(*chain(
            OperationNode("p0", KIND_PIM_CHANNEL, (),
                          pim_detail(channel=0)),
            OperationNode("p1", KIND_PIM_END, (), pim_end_detail()),
            compute("k1"),
            OperationNode("p2", KIND_PIM_CHANNEL, (),
                          pim_detail(channel=0)),
            OperationNode("p3", KIND_PIM_END, (), pim_end_detail())))
        assert len(g.of_kind(KIND_PIM_END)) == 2

    def test_channel_must_be_a_strict_non_negative_int(self):
        with pytest.raises(InvalidInput, match="channel"):
            pim_detail(channel=-1)
        with pytest.raises(InvalidInput, match="channel"):
            pim_detail(channel=True)

    def test_pim_region_survives_with_its_channel(self):
        g = graph(*chain(
            compute("k0"),
            OperationNode("p0", KIND_PIM_CHANNEL, (), pim_detail(channel=1)),
            compute("k1"),
            OperationNode("p1", KIND_PIM_END, (), pim_end_detail())))
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
        """Strict completeness fires first: a persisted graph MUST carry
        its identity field (2.5.2), so a deleted id is a missing-field
        refusal, not an unauthenticated-content refusal."""
        doc = graph(compute("c0")).to_dict()
        del doc["workload_id"]
        with pytest.raises(InvalidInput, match="missing canonical field"):
            WorkloadGraph.from_dict(doc, strict=True)

    def test_empty_embedded_id_refuses_as_unauthenticated(self):
        doc = graph(compute("c0")).to_dict()
        doc["workload_id"] = ""
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


# ══ PHASE 2.5 — authority hardening (adversarial strict-reader matrix) ══

def _node_doc(**over):
    base = compute("c0").to_dict()
    base.update(over)
    return base


class TestDetailClosureIsExact:
    """2.5.1 — a strict reader is adversarial: exact key set, and every
    field semantically revalidated (it may not trust the builders)."""

    @pytest.mark.parametrize("kind,detail,missing", [
        (KIND_COMPUTE, {"duration_ns": 1}, "batch_tag"),
        (KIND_COLLECTIVE, {"collective_kind": "ALLREDUCE"}, "source"),
        (KIND_P2P, {"src_rank": 0, "dst_rank": 1}, "role"),
        (KIND_MULTICAST, {"source_rank": 0, "destinations": (1,),
                          "payload_bytes": 1}, "replication"),
        (KIND_PIM_CHANNEL, {}, "channel"),
    ])
    def test_missing_canonical_field_refuses(self, kind, detail, missing):
        with pytest.raises(InvalidInput, match="missing canonical field"):
            OperationNode.from_dict(
                {"operation_id": "x", "kind": kind, "deps": (),
                 "owner": None, "phase": None, "step": None, "label": "",
                 "detail": detail}, strict=True, participant_count=4)

    def test_pim_end_carrying_anything_refuses(self):
        with pytest.raises(InvalidInput, match="unknown fields"):
            OperationNode.from_dict(
                {"operation_id": "x", "kind": KIND_PIM_END, "deps": (),
                 "owner": None, "phase": None, "step": None, "label": "",
                 "detail": {"channel": 0}},
                strict=True, participant_count=4)

    def test_unknown_field_still_refuses(self):
        with pytest.raises(InvalidInput, match="unknown fields"):
            OperationNode.from_dict(_node_doc(
                detail={**compute("c0").detail, "fabric_rank": 1}),
                strict=True, participant_count=4)

    def test_readers_revalidate_semantics_not_just_keys(self):
        """Complete keys but a semantically invalid value must refuse."""
        d = compute("c0").detail
        bad = {**d, "duration_ns": -5}
        with pytest.raises(InvalidInput, match="duration_ns"):
            OperationNode.from_dict(_node_doc(detail=bad), strict=True,
                                    participant_count=4)


class TestStrictCompleteness:
    """2.5.2 — strict mode requires the complete persisted shape."""

    def test_node_missing_persisted_field_refuses(self):
        doc = _node_doc()
        del doc["step"]
        with pytest.raises(InvalidInput, match="missing canonical field"):
            OperationNode.from_dict(doc, strict=True, participant_count=4)

    def test_semantics_missing_field_refuses(self):
        with pytest.raises(InvalidInput, match="missing canonical field"):
            WorkloadSemantics.from_dict({"phase": None}, strict=True)

    def test_non_strict_authoring_still_uses_defaults(self):
        node = OperationNode.from_dict(
            {"operation_id": "c0", "kind": KIND_COMPUTE,
             "detail": compute("c0").detail})
        assert node.owner is None and node.deps == ()


class TestOwnerNamespace:
    """2.5.3 — the participant law applies to owner as well."""

    def test_owner_outside_the_participant_namespace_refuses(self):
        node = OperationNode("c0", KIND_COMPUTE, (),
                             compute_detail(duration_ns=1), owner=4)
        with pytest.raises(InvalidInput, match="owner 4 is outside"):
            graph(node)                       # participant_count == 4

    def test_same_owner_is_legal_in_a_wider_namespace(self):
        node = OperationNode("c0", KIND_COMPUTE, (),
                             compute_detail(duration_ns=1), owner=4)
        g = graph(node, participant_count=8)
        assert g.participant_count == 8

    def test_world_size_does_not_widen_the_namespace(self):
        """world_size == 8 must not make owner=4 legal at count==4."""
        assert PARALLELISM.world_size == 8
        node = OperationNode("c0", KIND_COMPUTE, (),
                             compute_detail(duration_ns=1), owner=7)
        with pytest.raises(InvalidInput, match="owner 7 is outside"):
            graph(node)


class TestCollectiveArity:
    """2.5.4 — a one-rank collective never enters a valid graph."""

    def test_single_participant_collective_refuses(self):
        with pytest.raises(InvalidInput, match="needs >= 2"):
            collective("c0", participants=(0,))

    def test_single_participant_expert_collective_refuses(self):
        with pytest.raises(InvalidInput, match="needs >= 2"):
            expert_detail(collective_kind="ALLGATHER", participants=(0,),
                          payload_bytes=8, participant_count=4)

    def test_broadcast_needs_the_root_plus_a_destination(self):
        with pytest.raises(InvalidInput, match="needs >= 2"):
            collective("c0", kind="BROADCAST", participants=(0,), source=0)

    def test_divisibility_is_still_schedule_only(self):
        """Arity is a declaration law; divisibility is not."""
        g = graph(collective("c0", participants=(0, 1, 2), payload=1000))
        assert g.by_id("c0").detail["payload_bytes"] == 1000


class TestBroadcastSourceStrictness:
    """2.5.5 — True == 1 must not smuggle a boolean into a rank."""

    @pytest.mark.parametrize("source", [True, False, 1.0, "1", 2.0, None])
    def test_bad_source_type_refuses(self, source):
        with pytest.raises((InvalidInput, UnsupportedSemantics)):
            collective("c0", kind="BROADCAST", participants=(0, 1, 2, 3),
                       source=source)

    def test_out_of_range_source_refuses(self):
        with pytest.raises(InvalidInput, match="not a participating rank"):
            collective("c0", kind="BROADCAST", participants=(0, 1),
                       source=7)

    def test_integer_source_is_accepted(self):
        assert collective("c0", kind="BROADCAST", source=2) \
            .detail["source"] == 2


class TestExpertCollectiveVocabulary:
    """2.5.6 — the expert grammar carries no broadcast root."""

    def test_expert_broadcast_refuses(self):
        with pytest.raises(UnsupportedSemantics, match="expert source"):
            expert_detail(collective_kind="BROADCAST", participants=(0, 1),
                          payload_bytes=8, participant_count=4)

    @pytest.mark.parametrize("kind", ["ALLREDUCE", "ALLGATHER",
                                      "REDUCESCATTER", "ALLTOALL"])
    def test_supported_expert_collectives_are_accepted(self, kind):
        node = expert_detail(collective_kind=kind, participants=(0, 1),
                             payload_bytes=8, participant_count=4)
        assert node["collective_kind"] == kind


class TestMemoryLocationGrammar:
    """2.5.7 — the sealed trace grammar, ported (never BANANA:7)."""

    @pytest.mark.parametrize("loc", [
        "LOCAL", "REMOTE:0", "REMOTE:0.1", "CXL", "CXL:1", "STORAGE",
    ])
    def test_admitted_forms(self, loc):
        node = compute("c0", input_loc=loc)
        assert node.detail["input_loc"] == loc

    @pytest.mark.parametrize("loc", [
        "BANANA:7", "LOCAL:abc", "REMOTE:", "REMOTE:0.", "REMOTE:.1",
        "local", "HBM", "",
    ])
    def test_malformed_forms_refuse(self, loc):
        with pytest.raises(InvalidInput, match="location|malformed"):
            compute("c0", input_loc=loc)

    def test_grammar_is_checked_before_memory_lowering(self):
        """A bad location must die at graph construction, not in Ramulator."""
        with pytest.raises(InvalidInput):
            graph(compute("c0", weight_loc="BANANA:7"))


class TestSemanticsHardening:
    """2.5.8/9/10 — deep freeze, descriptor provenance, phase agreement."""

    def test_shape_is_deeply_frozen(self):
        shape = {"num_layers": 32, "hidden_size": 4096}
        sem = WorkloadSemantics(shape=shape)
        shape["num_layers"] = 999
        assert sem.shape["num_layers"] == 32

    def test_shape_field_rules(self):
        with pytest.raises(InvalidInput, match="unsupported fields"):
            WorkloadSemantics(shape={"num_heads": 32})
        with pytest.raises(InvalidInput, match="must be an int"):
            WorkloadSemantics(shape={"num_layers": -1})
        assert WorkloadSemantics(shape=None).shape is None

    def test_shape_moves_identity(self):
        a = graph(compute("c0"), semantics=WorkloadSemantics(
            shape={"num_layers": 1}))
        b = graph(compute("c0"), semantics=WorkloadSemantics(
            shape={"num_layers": 2}))
        assert a.workload_id() != b.workload_id()

    def test_descriptor_name_is_provenance_not_identity(self):
        same_hash = "sha256:" + "a" * 64
        a = graph(compute("c0"), semantics=WorkloadSemantics(
            model_descriptor_hash=same_hash, model_descriptor_name="llama"))
        b = graph(compute("c0"), semantics=WorkloadSemantics(
            model_descriptor_hash=same_hash, model_descriptor_name="qwen"))
        assert a.workload_id() == b.workload_id()

    def test_descriptor_hash_is_semantics(self):
        a = graph(compute("c0"), semantics=WorkloadSemantics(
            model_descriptor_hash="sha256:" + "a" * 64))
        b = graph(compute("c0"), semantics=WorkloadSemantics(
            model_descriptor_hash="sha256:" + "b" * 64))
        assert a.workload_id() != b.workload_id()

    def test_global_and_per_op_phase_must_agree(self):
        with pytest.raises(InvalidInput, match="one graph, one phase"):
            graph(OperationNode("c0", KIND_COMPUTE, (),
                                compute_detail(duration_ns=1),
                                phase="PREFILL"),
                  semantics=WorkloadSemantics(phase="DECODE"))

    def test_absence_of_global_phase_permits_declared_op_phases(self):
        g = graph(OperationNode("c0", KIND_COMPUTE, (),
                                compute_detail(duration_ns=1),
                                phase="DECODE"))
        assert g.semantics.phase is None


class TestRegionOrderingLaw:
    """2.5.11/2.5.12 — region membership comes from the DEPENDENCY order.

    Construction order is excluded from identity, so it may not carry
    region semantics either. A marker-bearing graph must therefore have a
    UNIQUE dependency-derived order.
    """

    MARKERS = (compute("k0"),
               OperationNode("e0", KIND_EXPERT_BEGIN, (),
                             expert_detail(expert_num=0,
                                           participant_count=4)),
               compute("k1"),
               OperationNode("e1", KIND_EXPERT_END, (),
                             expert_detail(end=True, participant_count=4)))

    def test_explicit_chain_passes(self):
        g = graph(*chain(*self.MARKERS))
        assert g.require_total_order()[0].operation_id == "k0"

    def test_ambiguous_marker_graph_refuses(self):
        with pytest.raises(InvalidInput, match="unique dependency"):
            graph(*self.MARKERS)

    def test_marker_free_graph_keeps_partial_order_freedom(self):
        """Independent operations are legal when no region depends on order."""
        g = graph(compute("a"), compute("b"))
        assert {op.operation_id for op in g.ordered_operations()} == {"a", "b"}
        with pytest.raises(InvalidInput, match="unique dependency"):
            g.require_total_order()

    def test_construction_permutation_keeps_identity_and_membership(self):
        chained = chain(*self.MARKERS)
        a = graph(*chained)
        b = graph(*reversed(chained))       # same DAG, different tuple order
        assert a.workload_id() == b.workload_id()
        assert [op.operation_id for op in a.require_total_order()] == \
            [op.operation_id for op in b.require_total_order()]

    def test_region_membership_is_derived_from_the_dependency_order(self):
        g = graph(*chain(*self.MARKERS))
        order = [op.operation_id for op in g.require_total_order()]
        begin = order.index("e0")
        end = order.index("e1")
        assert order[begin + 1:end] == ["k1"]

    def test_dependency_order_can_place_a_compute_outside_a_region(self):
        """An operation that depends on the END is outside the region."""
        ops = chain(*self.MARKERS)
        after = OperationNode("k2", KIND_COMPUTE, ("e1",),
                              compute_detail(duration_ns=1))
        g = graph(*(ops + (after,)))
        order = [op.operation_id for op in g.require_total_order()]
        assert order.index("k2") > order.index("e1")

    def test_ordered_operations_is_stable_and_total_for_chains(self):
        g = graph(*chain(compute("a"), compute("b"), compute("c")))
        assert [op.operation_id for op in g.ordered_operations()] == \
            ["a", "b", "c"]
        assert [op.operation_id for op in g.require_total_order()] == \
            ["a", "b", "c"]


class TestNoAliasingAcrossGraphs:
    """2c.2.1 — a frozen node must not change because a graph touched it.

    The authority previously wrote its participant namespace INTO the
    caller's node (`object.__setattr__(op, "_participant_count", ...)`).
    Constructing a second graph then mutated state reachable from the
    first — a frozen dataclass that silently changes depending on which
    graph referenced it last.
    """

    @staticmethod
    def _rank_node():
        return OperationNode("c0", KIND_COLLECTIVE, (),
                             collective_detail(
                                 collective_kind="ALLREDUCE",
                                 participants=(0, 1),
                                 payload_bytes=8, participant_count=None))

    def test_same_node_in_two_graphs_leaves_it_unchanged(self):
        node = self._rank_node()
        before = node.to_dict()
        g4 = WorkloadGraph(parallelism=PARALLELISM, participant_count=4,
                           operations=(node,))
        after_first = node.to_dict()
        g8 = WorkloadGraph(parallelism=PARALLELISM, participant_count=8,
                           operations=(node,))
        assert node.to_dict() == before == after_first
        assert g4.to_dict() == g4.to_dict()
        assert g4.workload_id() == g4.workload_id()
        assert g8.workload_id() == g8.workload_id()
        assert g4.workload_id() != g8.workload_id()

    def test_graph_serialization_is_unaffected_by_a_later_graph(self):
        node = self._rank_node()
        g4 = WorkloadGraph(parallelism=PARALLELISM, participant_count=4,
                           operations=(node,))
        frozen = g4.to_dict()
        WorkloadGraph(parallelism=PARALLELISM, participant_count=8,
                      operations=(node,))
        assert g4.to_dict() == frozen

    def test_node_has_no_namespace_state_at_all(self):
        node = self._rank_node()
        assert not hasattr(node, "_participant_count")
        assert set(node.to_dict()) == {"operation_id", "kind", "deps",
                                       "owner", "phase", "step", "detail",
                                       "label"}
        assert not any("participant" in f for f in node.to_dict())

    def test_out_of_namespace_node_refuses_in_a_narrow_graph(self):
        """rank 5 is legal in count=8 and refused in count=4 — with the
        SAME node object and no mutation between attempts."""
        node = OperationNode("c0", KIND_COLLECTIVE, (),
                             collective_detail(
                                 collective_kind="ALLREDUCE",
                                 participants=(0, 5, 6, 7),
                                 payload_bytes=8, participant_count=None))
        snapshot = node.to_dict()
        with pytest.raises(InvalidInput, match="participant namespace"):
            WorkloadGraph(parallelism=PARALLELISM, participant_count=4,
                          operations=(node,))
        assert node.to_dict() == snapshot, "the failed graph mutated it"
        g8 = WorkloadGraph(parallelism=PARALLELISM, participant_count=8,
                           operations=(node,))
        assert g8.participant_count == 8
        assert node.to_dict() == snapshot
        with pytest.raises(InvalidInput, match="owner 5 is outside"):
            WorkloadGraph(parallelism=PARALLELISM, participant_count=4,
                          operations=(OperationNode(
                              "o0", KIND_COMPUTE, (),
                              compute_detail(duration_ns=1), owner=5),))

    def test_direct_construction_validates_bounds_at_the_graph(self):
        """Structure is checked at the node; BOUNDS at the graph."""
        node = OperationNode("c0", KIND_COLLECTIVE, (),
                             collective_detail(
                                 collective_kind="ALLREDUCE",
                                 participants=(0, 1, 2),
                                 payload_bytes=8, participant_count=None))
        assert node.detail["participants"] == (0, 1, 2)   # node: legal
        with pytest.raises(InvalidInput, match="participant namespace"):
            WorkloadGraph(parallelism=PARALLELISM, participant_count=2,
                          operations=(node,))                 # graph: refuse
        # the same node in a wide enough namespace is fine
        g = WorkloadGraph(parallelism=PARALLELISM, participant_count=4,
                          operations=(node,))
        assert g.participant_count == 4
