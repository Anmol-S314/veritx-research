"""tests/test_gate_v2_union_evidence.py — Gate V2 findings, as tests.

Slice 2c Gate V2: the union inventory was incomplete and the proposed
canonical schema contained semantic errors. These tests CAPTURE the
findings before any workload-authority merge, so the merge cannot quietly
delete them.

Two kinds of test live here:

  * assertions on behaviour that must SURVIVE the merge, and
  * ``xfail(strict=True)`` markers pinning behaviour that is CURRENTLY
    WRONG. A strict xfail turns into a failure the moment the behaviour
    is fixed, so the marker cannot rot: fixing the defect forces the test
    to be updated, with the evidence attached.

Nothing here changes production code.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

from veritx_dse.workload.canonical import (  # noqa: E402
    ALL_DIMENSIONS, Parallelism, WorkloadArtifact, WorkloadError,
    artifact_from_trace_rows, build_broadcast_op, build_collective_op,
    build_compute_op, build_expert_begin_op,
)
from veritx_dse.workload.lowering import rows_from_artifact  # noqa: E402

CHAKRA = (REPO / "third_party" / "astra-sim" / "extern"
          / "graph_frontend" / "chakra" / "src" / "converter"
          / "llm_converter.py")


def layer_row(name, comp_ns, inp, wt, out, comm="NONE", size=0,
              tag="BATCH_1"):
    return (name, str(comp_ns), "LOCAL", str(inp), "LOCAL", str(wt),
            "LOCAL", str(out), comm, str(size), tag)


def para(**kw):
    base = dict(tp=2, dp=1, ep=2, pp=1)
    base.update(kw)
    return Parallelism(**base)


def artifact(ops, *, num_participants=4, parallelism=None):
    return WorkloadArtifact(
        workload_id="w", source_kind="test",
        parallelism=parallelism or Parallelism(tp=1, dp=4),
        num_participants=num_participants, ops=tuple(ops))


# ── A. the participant namespace is NOT the parallelism geometry ────────
class TestParticipantNamespace:
    """`num_participants` is the rank space the TRACE addresses.

    verify_place: `serve._parallelism_from_cluster` sets ``dp`` to the
    number of INSTANCES and takes tp/ep/pp from the FIRST instance, while
    ``num_participants`` is the per-instance NPU count. For a two-instance
    cluster with tp=4 those differ: world_size = 8, participants = 4.
    Deriving participant_count from world_size would silently break
    multi-instance serving.
    """

    def test_world_size_and_participant_count_are_different_quantities(
            self):
        para_multi = Parallelism(tp=4, ep=1, pp=1, dp=2)  # 2 instances
        world = para_multi.tp * para_multi.pp * para_multi.ep * para_multi.dp
        per_instance = 4
        assert world == 8 and per_instance == 4
        art = artifact(
            [build_collective_op("g0", "ALLREDUCE", bytes=4096,
                                 participants=(0, 1, 2, 3),
                                 scope=ALL_DIMENSIONS)],
            num_participants=per_instance, parallelism=para_multi)
        # the trace's ranks validate against the PARTICIPANT space
        assert art.num_participants == 4

    def test_ranks_beyond_the_participant_space_refuse(self):
        para_multi = Parallelism(tp=4, ep=1, pp=1, dp=2)
        with pytest.raises(WorkloadError, match="out of range"):
            artifact(
                [build_collective_op("g0", "ALLREDUCE", bytes=4,
                                     participants=(0, 4, 5, 6),
                                     scope=ALL_DIMENSIONS)],
                num_participants=4, parallelism=para_multi)

    def test_serving_canonicalizer_derives_dp_from_instance_count(self):
        from veritx_dse.workload.serve import _parallelism_from_cluster
        cluster = {"nodes": [{"instances": [
            {"tp_size": 4, "ep_size": 1, "pp_size": 1},
            {"tp_size": 4, "ep_size": 1, "pp_size": 1}]}]}
        got = _parallelism_from_cluster(cluster, source="t")
        assert (got.tp, got.pp, got.ep, got.dp) == (4, 1, 1, 2)
        assert got.tp * got.pp * got.ep * got.dp == 8   # world_size


# ── C. EXPERT_END carries the combine collective ────────────────────────
class TestExpertEndIsNotPayloadFree:
    def test_expert_end_preserves_combine_collective(self):
        rows = [
            layer_row("attention", 1000, 2048, 4096, 2048),
            ("EXPERT 0 ALLGATHER:1,0 4096",),
            layer_row("mlp.expert", 300, 128, 256, 128),
            ("EXPERT END REDUCESCATTER:1,0 4096",),
            layer_row("o_proj", 500, 1024, 2048, 1024),
        ]
        art = artifact_from_trace_rows(
            rows, workload_id="w", parallelism=para(), num_participants=2)
        ends = [op for op in art.ops if op.kind == "EXPERT_END"]
        assert len(ends) == 1
        end = ends[0]
        assert end.comm_kind == "REDUCESCATTER"
        assert end.bytes == 4096
        assert end.participants == (0, 1)
        assert rows_from_artifact(art).rows == rows

    def test_expert_begin_also_carries_its_collective(self):
        op = build_expert_begin_op(0, comm_kind="ALLGATHER", bytes=4096,
                                   participants=(0, 1),
                                   scope=ALL_DIMENSIONS)
        assert op.comm_kind == "ALLGATHER" and op.bytes == 4096
        assert op.kind == "EXPERT_BEGIN"


# ── B. PIM markers are SILENTLY DROPPED today ───────────────────────────
class TestPimSemantics:
    """LLMServingSim emits PIM markers and Chakra consumes them.

    ``artifact_from_trace_rows`` currently does
    ``if marker == "PIM": continue`` — silent semantic loss. This test
    pins the LOSS so the merge cannot inherit it by accident; it flips to
    a preservation test when PIM_BEGIN/PIM_END exist in the canonical
    graph.
    """

    PIM_ROWS = [
        ("PIM 0",),
        layer_row("attention", 1000, 2048, 4096, 2048),
        ("PIM 1",),
        layer_row("attention", 1000, 2048, 4096, 2048),
        ("PIM END",),
    ]

    @pytest.mark.xfail(strict=True,
                       reason="Gate V2 finding B: PIM markers are dropped by "
                              "the canonicalizer (canonical.py:587). Fix by "
                              "adding PIM_BEGIN/PIM_END to the canonical "
                              "operation vocabulary.")
    def test_pim_markers_survive_canonicalization(self):
        art = artifact_from_trace_rows(
            self.PIM_ROWS, workload_id="w", parallelism=para(),
            num_participants=2)
        kinds = [op.kind for op in art.ops]
        assert "PIM_BEGIN" in kinds and "PIM_END" in kinds

    def test_pim_markers_are_currently_absent_from_the_artifact(self):
        """The loss itself, asserted, so it is visible and dated."""
        art = artifact_from_trace_rows(
            self.PIM_ROWS, workload_id="w", parallelism=para(),
            num_participants=2)
        kinds = [op.kind for op in art.ops]
        assert not any("PIM" in k for k in kinds), kinds
        # the input rows cannot be regenerated from the artifact either
        assert rows_from_artifact(art).rows != self.PIM_ROWS

    def test_the_no_argument_append_is_repaired(self):
        """F17a is FIXED: the source no longer contains the broken call.

        Gate V2.1 replaced ``pim_parent_nodes.append()`` with an explicit
        no-predecessor branch (the first PIM block in group 0 has no parent
        to append; a dummy would invent a dependency).
        """
        vendored = (REPO / "third_party" / "astra-sim" / "extern"
                    / "graph_frontend" / "chakra" / "src" / "converter"
                    / "llm_converter.py")
        if not vendored.exists():
            pytest.skip("vendored chakra converter not present")
        assert "pim_parent_nodes.append()" not in vendored.read_text(), (
            "the no-argument append came back")


# ── F. scope absence must never become "ALL" ────────────────────────────
class TestScopeAbsenceIsNotAll:
    """The row projection collapses `None` and `ALL` today.

    ``rows_from_artifact`` merges a collective into its COMPUTE row's comm
    column; ``_comm_field`` emits the bare kind unless scope is a list.
    Both ``"ALL"`` and ``None`` are "not a list", so both render bare.
    """

    @staticmethod
    def _comm_column(collective):
        comp = build_compute_op("c0", duration_ns=100)
        art = artifact([comp, collective], num_participants=4)
        return rows_from_artifact(art).rows[0][8]

    def test_all_scope_emits_the_bare_form(self):
        op = build_collective_op("g0", "ALLREDUCE", bytes=4,
                                 participants=(0, 1),
                                 scope=ALL_DIMENSIONS)
        assert self._comm_column(op) == "ALLREDUCE"     # bare = ALL

    def test_explicit_vector_emits_the_mask(self):
        op = build_collective_op("g0", "ALLREDUCE", bytes=4,
                                 participants=(0, 1),
                                 scope=[True, False, False, False])
        assert self._comm_column(op) == "ALLREDUCE:1,0,0,0"

    @pytest.mark.xfail(strict=True,
                       reason="Gate V2 finding F: an undeclared scope renders "
                              "the SAME bare form as an explicit ALL, so the "
                              "backend cannot tell 'all dimensions' from "
                              "'nobody declared'. The canonical lowering must "
                              "refuse None unless the target proves a meaning.")
    def test_undeclared_scope_does_not_look_like_all(self):
        declared = build_collective_op("g0", "ALLREDUCE", bytes=4,
                                       participants=(0, 1),
                                       scope=ALL_DIMENSIONS)
        undeclared = build_collective_op("g1", "ALLREDUCE", bytes=4,
                                         participants=(0, 1),
                                         scope=ALL_DIMENSIONS)
        object.__setattr__(undeclared, "scope", None)  # Wave-D migration
        assert self._comm_column(undeclared) != self._comm_column(declared)


# ── G. BROADCAST must carry an explicit source ──────────────────────────
class TestBroadcastSource:
    def test_legacy_broadcast_keeps_an_explicit_non_first_source(self):
        op = build_broadcast_op("g0", bytes=2048, participants=(0, 1, 2, 3),
                                source=2)
        assert op.src == 2 and op.src != op.participants[0]
        art = artifact([op], num_participants=4)
        assert art.ops[0].to_dict()["src"] == 2

    def test_legacy_broadcast_refuses_a_missing_source(self):
        with pytest.raises(WorkloadError, match="explicit source"):
            build_broadcast_op("g0", bytes=2048, participants=(0, 1, 2, 3))

    def test_waved_broadcast_still_expands_from_participants_zero(self):
        """The Wave-D root assumption, preserved BEHAVIOURALLY.

        The v1 CollectiveIntent carries no source field, so its historical
        root is participants[0]; migration must record that explicitly so
        existing packets stay identical. The v2 path
        (LogicalMessageArtifactV2) honours the declared source — see
        tests/test_logical_messages_v2.py. Behavioural, not a source-text
        check: moving the expansion into a shared helper must not fail a
        pin that the packets are unchanged.
        """
        from veritx_dse.workload.messages import _expand_collective
        from veritx_dse.workload.operations import CollectiveIntent
        ci = CollectiveIntent("BROADCAST", (0, 1, 2, 3), 2048, "c0")
        triples, rec = _expand_collective(ci)
        assert {src for _, src, _ in triples} == {0}
        assert {dst for _, _, dst in triples} == {1, 2, 3}
        assert rec.message_count == len(triples) == 3


# ── H. SEND/RECV are identity-bearing roles ────────────────────────────
class TestP2PRoles:
    def test_legacy_send_and_recv_are_distinct_kinds(self):
        from veritx_dse.workload.canonical import build_p2p_op
        send = build_p2p_op("t0", "SEND", bytes=300, src=0, dst=2)
        recv = build_p2p_op("t1", "RECV", bytes=300, src=0, dst=2)
        assert send.kind == "SEND" and recv.kind == "RECV"
        assert send.to_dict()["kind"] != recv.to_dict()["kind"]

    def test_waved_p2p_is_a_complete_transfer(self):
        from veritx_dse.workload.operations import P2PTransfer
        t = P2PTransfer(0, 2, 300, "t0")
        assert (t.src_rank, t.dst_rank) == (0, 2)
        # one Wave-D P2P == one logical transfer; a legacy standalone
        # SEND/RECV has no proven pairing rule and must not be merged
        assert t.__class__.__name__ == "P2PTransfer"


# ── M. divisibility belongs to the SCHEDULE, not the declaration ────────
class TestDivisibilityIsAScheduleLaw:
    def test_the_canonical_declaration_accepts_non_chunkable_payloads(self):
        """ALLREDUCE k=3, B=1000 is a VALID workload declaration."""
        op = build_collective_op("g0", "ALLREDUCE", bytes=1000,
                                 participants=(0, 1, 2),
                                 scope=ALL_DIMENSIONS)
        art = artifact([op], num_participants=3)
        assert art.ops[0].bytes == 1000

    def test_the_pinned_ring_schedule_refuses_uneven_chunks(self):
        """The exact RING lowering refuses; no rounding, no substitution."""
        from veritx_dse.core.errors import UnsupportedSchedule
        from veritx_dse.workload.collectives import collective_schedule
        with pytest.raises(UnsupportedSchedule, match="B % k"):
            collective_schedule("ALLREDUCE", 3, 1000)

    def test_waved_graph_refuses_at_lowering_not_at_declaration(self):
        from veritx_dse.core.errors import UnsupportedSchedule
        from veritx_dse.model.parallelism import ParallelismArtifact
        from veritx_dse.workload.messages import LogicalMessageArtifact
        from veritx_dse.workload.operations import (
            KIND_COLLECTIVE, CollectiveIntent, OperationGraph,
            OperationNode,
        )
        from veritx_dse.workload.semantics import WaveDWorkloadSemantics
        pa = ParallelismArtifact(1, 1, 1, 3)
        coll = CollectiveIntent("ALLREDUCE", (0, 1, 2), 1000, "c0")
        graph = OperationGraph(          # declaration: accepted
            parallelism=pa,
            semantics=WaveDWorkloadSemantics(phase="DECODE"),
            workload_id="w",
            nodes=(OperationNode("n0", KIND_COLLECTIVE, "DECODE", 0, 0, (),
                                 {"collective_id": "c0"}),),
            collectives=(coll,))
        with pytest.raises(UnsupportedSchedule, match="B % k"):
            LogicalMessageArtifact(graph=graph)   # lowering: refused


# ── J. legacy compressed-default hashes must validate AS-IS ─────────────
class TestLegacyCompressedDefaults:
    def test_defaults_are_omitted_from_the_serialized_form(self):
        op = build_compute_op("c0", duration_ns=100)
        d = op.to_dict()
        assert "input_loc" not in d and "batch_tag" not in d

    def test_the_identity_hash_covers_exactly_that_form(self):
        art = artifact([build_compute_op("c0", duration_ns=100)])
        identity_ops = art._identity_dict()["ops"]
        assert identity_ops == [art.ops[0].to_dict()]

    def test_a_roundtrip_through_the_legacy_document_is_stable(self):
        art = artifact([build_compute_op("c0", duration_ns=100,
                                         input_bytes=8),
                        build_collective_op("g0", "ALLREDUCE", bytes=64,
                                            participants=(0, 1),
                                            scope=ALL_DIMENSIONS)],
                       num_participants=2)
        again = WorkloadArtifact.from_dict(art.serialize())
        assert again.artifact_hash == art.artifact_hash
        assert again.serialize() == art.serialize()
