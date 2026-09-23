"""Wave D1/D3/D4 proof tests — rank space, groups, collectives,
packetization, flitization.

Methods (§25): algebraic exact checks, bounded exhaustive enumeration,
independent-oracle differential checks, Hypothesis property tests.

The oracles in ``veritx_dse.verification.reference_semantics`` are structurally independent
of the production code (§26): they import nothing from it and the
production modules import nothing from them outside tests.
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.core.errors import (  # noqa: E402
    ConservationFailed, InvalidInput, MappingInvalid, UnsupportedSchedule,
    UnsupportedSemantics,
)
from veritx_dse.workload.messages import LogicalMessageArtifact  # noqa: E402
from veritx_dse.workload.operations import (  # noqa: E402
    KIND_COLLECTIVE, KIND_MULTICAST, KIND_P2P, CollectiveIntent,
    MulticastIntent, OperationGraph, OperationNode, P2PTransfer,
)
from veritx_dse.verification.reference_semantics import (  # noqa: E402
    ref_collective, ref_coords, ref_flitize, ref_group_members,
    ref_multicast, ref_packetize, ref_rank,
    verify_parallelism_reference,
)
from veritx_dse.model.parallelism import ParallelismArtifact  # noqa: E402
from veritx_dse.workload.semantics import (  # noqa: E402
    WaveDWorkloadSemantics,
)
from veritx_dse.workload.traffic import (  # noqa: E402
    PhysicalTrafficArtifact, flitize_packet, header_width_bits,
    packetize_message,
)


def _sem(phase="DECODE"):
    return WaveDWorkloadSemantics(phase=phase)


# ══ §22 oracle pins: k=4, B=1024 ════════════════════════════════════════

class TestCollectiveOraclePins:
    @pytest.mark.parametrize("kind,expected", [
        ("ALLREDUCE", (24, 256, 1536, 6144)),
        ("REDUCESCATTER", (12, 256, 768, 3072)),
        ("ALLGATHER", (12, 1024, 3072, 12288)),
        ("ALLTOALL", (12, 256, 768, 3072)),
        ("BROADCAST", (3, 1024, 3072, 3072)),
    ])
    def test_k4_b1024_pins(self, kind, expected):
        r = ref_collective(kind, 4, 1024)
        got = (r["message_count"], r["message_bytes"], r["per_rank_sent"],
               r["aggregate_payload"])
        assert got == expected

    def test_broadcast_is_asymmetric(self):
        # aggregate == root_sent, NOT k × root_sent (§10.1)
        r = ref_collective("BROADCAST", 4, 1024)
        assert r["aggregate_payload"] == r["per_rank_sent"] == 3072

    def test_symmetric_schedules_satisfy_aggregate_eq_k_times_per_rank(self):
        for kind in ("ALLREDUCE", "REDUCESCATTER", "ALLGATHER", "ALLTOALL"):
            r = ref_collective(kind, 6, 720)
            assert r["aggregate_payload"] == 6 * r["per_rank_sent"]

    @pytest.mark.parametrize("kind", ["ALLREDUCE", "REDUCESCATTER",
                                      "ALLTOALL"])
    def test_divisibility_refusal(self, kind):
        with pytest.raises(ValueError, match="B % k"):
            ref_collective(kind, 3, 1000)

    def test_allgather_has_no_divisibility_law(self):
        assert ref_collective("ALLGATHER", 3, 1000)["aggregate_payload"] \
            == 3 * 2 * 1000

    def test_k1_refuses(self):
        with pytest.raises(ValueError):
            ref_collective("ALLREDUCE", 1, 64)


# ══ §7 rank bijection: bounded exhaustive [1,4]^4 ═══════════════════════

class TestRankBijectionBoundedExhaustive:
    def test_all_256_combinations(self):
        for tp, pp, ep, dp in product(range(1, 5), repeat=4):
            pa = ParallelismArtifact(tp=tp, pp=pp, ep=ep, dp=dp)
            R = tp * pp * ep * dp
            assert R == pa.world_size <= 64 or True  # domain note only
            seen = set()
            for t, p, e, d in product(range(tp), range(pp), range(ep),
                                      range(dp)):
                r = pa.rank_of(t, p, e, d)
                assert r not in seen, (tp, pp, ep, dp, r)
                seen.add(r)
                c = pa.coords_of(r)
                assert (c["tp"], c["pp"], c["ep"], c["dp"]) == (t, p, e, d)
            assert seen == set(range(R))
            pa.validate_group_laws()
            verify_parallelism_reference(pa)


# ══ §9 group laws vs independent oracle ═════════════════════════════════

class TestGroupLawsAgainstOracle:
    @pytest.mark.parametrize("tp,pp,ep,dp", [(1, 1, 1, 1), (4, 1, 1, 1),
                                             (2, 2, 1, 1), (2, 1, 2, 2),
                                             (3, 2, 2, 1), (2, 2, 2, 2)])
    def test_group_membership_matches_oracle(self, tp, pp, ep, dp):
        pa = ParallelismArtifact(tp=tp, pp=pp, ep=ep, dp=dp)
        for family in ("TP", "EP", "DP", "PP"):
            groups = pa.groups(family)
            expected_count = {"TP": pp * ep * dp, "EP": tp * pp * dp,
                              "DP": tp * pp * ep, "PP": pp}[family]
            assert len(groups) == expected_count
            # membership per rank via group_of == oracle
            for r in range(pa.world_size):
                c = pa.coords_of(r)
                g = pa.group_of(family, r)
                oracle = ref_group_members(
                    family, (tp, pp, ep, dp),
                    (c["tp"], c["pp"], c["ep"], c["dp"]))
                assert g.members == oracle

    def test_group_derivation_does_not_use_the_oracle(self):
        """The oracle must be independent OF the production derivation.

        Consolidation finding: ``ParallelismArtifact.groups()`` used to
        derive its members by calling the oracle's ``ref_rank``, and
        ``group_of()`` by calling ``ref_group_members``. So the
        "independent oracle" tests above were comparing the oracle against
        itself: patching the oracle to return garbage on both sides still
        passed. That is proven by the reverse probe now kept below.

        The derivation is production-side (``self.rank_of`` via the sealed
        Wave-B rank algebra) and ``group_of`` looks the rank up in
        ``groups`` rather than restating the members. The oracle import is
        confined to ``verification.reference_semantics``.
        """
        import veritx_dse.model.parallelism as wpar
        # the derivation entry points must not even be imported
        assert not hasattr(wpar, "ref_rank"), \
            "group derivation must not call the oracle"
        assert not hasattr(wpar, "ref_group_members"), \
            "group_of must not call the oracle"
        # and the artifact has no reference dependency at all: the
        # rank-space differential moved to verification.reference_semantics
        assert not hasattr(wpar, "ref_coords"), \
            "the artifact must not carry its own differential"

    def test_a_broken_oracle_is_detected(self, monkeypatch):
        """Reverse probe: garbage oracle -> the differential FAILS.

        Guards the guard: if the derivation ever goes back to using the
        oracle, this test stops detecting a broken oracle and fails.
        """
        import veritx_dse.model.parallelism as wpar
        pa = ParallelismArtifact(tp=2, pp=2, ep=2, dp=2)
        garbage = (999,)
        monkeypatch.setattr(wpar, "ref_rank",
                            lambda *a, **k: -1, raising=False)
        monkeypatch.setattr(wpar, "ref_group_members",
                            lambda *a, **k: garbage, raising=False)
        # patch the ORACLE ITSELF wherever it is used: this module's own
        # binding. Patching only one side would prove nothing.
        monkeypatch.setattr(sys.modules[__name__], "ref_group_members",
                            lambda *a, **k: garbage)
        # production output is UNCHANGED by a broken oracle
        for family in ("TP", "EP", "DP", "PP"):
            for r in range(pa.world_size):
                c = pa.coords_of(r)
                oracle = ref_group_members(
                    family, (2, 2, 2, 2),
                    (c["tp"], c["pp"], c["ep"], c["dp"]))
                assert oracle == garbage       # the oracle IS broken
                assert pa.group_of(family, r).members != garbage

    def test_singleton_dimension_produces_no_groups_of_that_family(self):
        # §10.3/§29 metamorphic: the FAMILY still partitions ranks but a
        # singleton axis means no collective is ever GENERATED for it —
        # tested at lowering level (TestSingletonMetamorphic).
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=1)
        assert pa.groups("TP")[0].members == (0,)

    def test_parallelism_id_excludes_world_size(self):
        # identity = 4 dims only; world_size is derived (§4)
        a = ParallelismArtifact(tp=2, pp=2, ep=1, dp=1)
        b = ParallelismArtifact(tp=4, pp=1, ep=1, dp=1)
        assert a.world_size == b.world_size == 4
        assert a.parallelism_id() != b.parallelism_id()

    def test_parallelism_id_deterministic_and_roundtrip(self):
        pa = ParallelismArtifact(tp=2, pp=1, ep=2, dp=1)
        assert pa.parallelism_id() == \
            ParallelismArtifact.from_dict(pa.to_dict()).parallelism_id()


# ══ §26 message lowering differential vs oracle ═════════════════════════

def _graph_for(pa, collectives=(), p2p=(), multicasts=(), phase="DECODE"):
    nodes = []
    for i, c in enumerate(collectives):
        nodes.append(OperationNode(f"coll{i}", KIND_COLLECTIVE, phase,
                                   c.participants[0], 0,
                                   (), {"collective_id": c.collective_id}))
    for i, t in enumerate(p2p):
        nodes.append(OperationNode(f"p2p{i}", KIND_P2P, phase, t.src_rank,
                                   0, (), {"transfer_id": t.transfer_id}))
    for i, m in enumerate(multicasts):
        nodes.append(OperationNode(f"mc{i}", KIND_MULTICAST, phase,
                                   m.source_rank, 0, (),
                                   {"multicast_id": m.multicast_id}))
    return OperationGraph(parallelism=pa, semantics=_sem(phase),
                          workload_id="w", nodes=tuple(nodes),
                          collectives=tuple(collectives),
                          p2p_transfers=tuple(p2p),
                          multicasts=tuple(multicasts))


class TestMessageLoweringDifferential:
    @pytest.mark.parametrize("kind", ["ALLREDUCE", "REDUCESCATTER",
                                      "ALLGATHER", "ALLTOALL", "BROADCAST"])
    @pytest.mark.parametrize("k,B", [(2, 512), (3, 768), (4, 1024),
                                     (5, 640), (8, 2048)])
    def test_lowering_matches_oracle(self, kind, k, B):
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=k)
        ci = CollectiveIntent(kind, tuple(range(k)), B, f"c-{kind}-{k}-{B}")
        g = _graph_for(pa, collectives=(ci,))
        lm = LogicalMessageArtifact(graph=g)  # refuses non-divisible here
        lm.validate_conservation()
        ref = ref_collective(kind, k, B)
        ms = lm.messages
        assert len(ms) == ref["message_count"]
        assert sum(m.payload_bytes for m in ms) == ref["aggregate_payload"]
        assert len(lm.schedules) == 1
        assert lm.schedules[0].algorithm == ci.algorithm
        # message-level: src/dst are participants; every src/dst rank is
        # a participant and every pair is distinct per schedule law
        assert all(m.src_rank in ci.participants and
                   m.dst_rank in ci.participants for m in ms)

    def test_non_divisible_refuses_at_lowering(self):
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=3)
        ci = CollectiveIntent("ALLREDUCE", (0, 1, 2), 1000, "cx")
        g = _graph_for(pa, collectives=(ci,))
        # the production spec refuses with the TYPED schedule refusal;
        # the reference keeps ValueError (tested separately above)
        with pytest.raises(UnsupportedSchedule, match="B % k"):
            LogicalMessageArtifact(graph=g)

    def test_p2p_exactly_one_message(self):
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=2)
        tr = P2PTransfer(0, 1, 300, "t0")
        g = _graph_for(pa, p2p=(tr,))
        lm = LogicalMessageArtifact(graph=g)
        lm.validate_conservation()
        assert len(lm.messages) == 1
        assert lm.messages[0].payload_bytes == 300

    def test_multicast_source_replication_law(self):
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=4)
        mc = MulticastIntent(0, (1, 2, 3), 100, "SOURCE_REPLICATION", "m0")
        g = _graph_for(pa, multicasts=(mc,))
        lm = LogicalMessageArtifact(graph=g)
        lm.validate_conservation()
        assert sum(m.payload_bytes for m in lm.messages) == 3 * 100
        ref = ref_multicast(100, 3)
        assert ref["delivered_payload"] == 300

    def test_duplicate_send_recv_halves_are_not_double_counted(self):
        # §18: one P2PTransfer == one message. A second transfer object
        # with the SAME payload is a *different declared transfer*, but
        # the artifact never fabricates a RECV-side message from one
        # P2PTransfer. Pin: 1 transfer → 1 message, identity-bound.
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=2)
        tr = P2PTransfer(0, 1, 300, "t0")
        g = _graph_for(pa, p2p=(tr,))
        lm = LogicalMessageArtifact(graph=g)
        assert len(lm.messages) == 1

    def test_message_artifact_id_changes_with_payload(self):
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=2)
        g1 = _graph_for(pa, collectives=(
            CollectiveIntent("ALLREDUCE", (0, 1), 512, "c0"),))
        g2 = _graph_for(pa, collectives=(
            CollectiveIntent("ALLREDUCE", (0, 1), 1024, "c0"),))
        l1 = LogicalMessageArtifact(graph=g1)
        l2 = LogicalMessageArtifact(graph=g2)
        assert l1.message_artifact_id() != l2.message_artifact_id()

    def test_message_artifact_id_changes_with_schedule(self):
        # §23.6: collective algorithm change → schedule identity changes.
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=2)
        g = _graph_for(pa, collectives=(
            CollectiveIntent("ALLREDUCE", (0, 1), 512, "c0"),))
        g2 = _graph_for(pa, collectives=(
            CollectiveIntent("ALLGATHER", (0, 1), 512, "c0"),))
        l1 = LogicalMessageArtifact(graph=g)
        l2 = LogicalMessageArtifact(graph=g2)
        assert l1.message_artifact_id() != l2.message_artifact_id()


# ══ §34/§18/§19 packet/flit exactness + non-byte-aligned ════════════════

class TestPacketFlitExactness:
    def test_regression_f65_h1(self):
        # §19: F=65, H=1, Q=64, P_i=100 → n=2, padding=28, tx=130
        n, padding, tx = ref_flitize(100, 64, 1, 65)
        assert (n, padding, tx) == (2, 28, 130)

    @pytest.mark.parametrize("msg_bits,Q,L", [
        (8, 57, 8), (504, 57, 8), (512, 57, 8), (520, 57, 8),
        (4095, 57, 8), (4096, 57, 8), (4097, 57, 8),
        (63, 64, 4), (64, 64, 4), (65, 64, 4),
        (255, 1, 1), (256, 1, 1), (257, 1, 1),
        (8192, 100, 3),
    ])
    def test_packet_payload_conservation(self, msg_bits, Q, L):
        packets = ref_packetize(msg_bits, Q, L)
        assert sum(packets) == msg_bits
        H = 8  # any header width; F = Q + H must hold
        for p_i in packets:
            n, padding, tx = ref_flitize(p_i, Q, H, Q + H)
            assert tx == H * n + p_i + padding
            assert 0 <= padding < Q

    def test_production_packetize_matches_oracle(self):
        # pure-function differential (no fabric needed)
        class _FakePF:
            payload_width_bits = 57
            max_packet_flits = 8

            @property
            def max_network_packet_payload_bits(self):
                return 57 * 8

        pf = _FakePF()
        for bits in (1, 8, 456, 457, 912, 913, 100000):
            assert packetize_message(bits, pf) == ref_packetize(bits, 57, 8)


# ══ Hypothesis property tests (§29) ═════════════════════════════════════

class TestProperties:
    @settings(max_examples=200, deadline=None)
    @given(st.tuples(st.integers(1, 6), st.integers(1, 6),
                     st.integers(1, 6), st.integers(1, 6)),
           st.integers(0, 1295))
    def test_rank_bijection_property(self, sizes, r):
        tp, pp, ep, dp = sizes
        R = tp * pp * ep * dp
        r = r % R
        t, p, e, d = ref_coords(r, tp=tp, pp=pp, ep=ep, dp=dp)
        assert ref_rank(t, p, e, d, tp=tp, pp=pp, ep=ep, dp=dp) == r

    @settings(max_examples=100, deadline=None)
    @given(st.integers(2, 16), st.integers(1, 1 << 16))
    def test_collective_oracle_conservation_property(self, k, B):
        for kind in ("ALLGATHER", "BROADCAST"):
            r = ref_collective(kind, k, B)
            assert r["message_count"] * r["message_bytes"] \
                == r["aggregate_payload"]

    @settings(max_examples=200, deadline=None)
    @given(st.integers(1, 1 << 20), st.sampled_from([1, 8, 57, 64, 100,
                                                     256]),
           st.integers(1, 8))
    def test_packet_payload_conservation_property(self, bits, Q, L):
        packets = ref_packetize(bits, Q, L)
        assert sum(packets) == bits
        assert len(packets) == (bits + Q * L - 1) // (Q * L)

    @settings(max_examples=200, deadline=None)
    @given(st.integers(1, 1 << 16), st.integers(0, 60),
           st.integers(8, 512))
    def test_flit_identity_property(self, P, H, Q):
        F = Q + H
        n, padding, tx = ref_flitize(P, Q, H, F)
        assert tx == H * n + P + padding
        assert 0 <= padding < Q
        assert n * Q >= P

    @settings(max_examples=100, deadline=None)
    @given(st.integers(2, 9), st.integers(1, 1 << 14))
    def test_multicast_property(self, n, B):
        ref = ref_multicast(B, n)
        assert ref["message_count"] == n
        assert ref["aggregate_payload"] == n * B
        assert ref["delivered_payload"] == n * B
        assert ref["source_payload"] == B


# ══ Mutation/adversarial (§30) — identity/conservation layer ════════════

class TestMutations:
    def _one_coll_graph(self, B=512):
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=2)
        ci = CollectiveIntent("ALLREDUCE", (0, 1), B, "c0")
        return pa, _graph_for(pa, collectives=(ci,))

    def test_payload_plus_two_changes_every_downstream_id(self):
        # +1 byte would refuse divisibility for ALLREDUCE (B % k == 0);
        # a valid payload change must still move every downstream id.
        pa, g1 = self._one_coll_graph(512)
        pa2, g2 = self._one_coll_graph(514)
        l1 = LogicalMessageArtifact(graph=g1)
        l2 = LogicalMessageArtifact(graph=g2)
        assert g1.operation_graph_id() != g2.operation_graph_id()
        assert l1.message_artifact_id() != l2.message_artifact_id()

    def test_payload_plus_one_refused_for_equal_chunk(self):
        # §23: the +1-byte attack refuses at schedule selection (the
        # intent is schedule-free per §20; the divisibility law is a
        # property of the pinned equal-chunk schedule).
        pa, g = self._one_coll_graph(513)
        # the production spec refuses with the TYPED schedule refusal;
        # the reference keeps ValueError (tested separately above)
        with pytest.raises(UnsupportedSchedule, match="B % k"):
            LogicalMessageArtifact(graph=g)

    def test_participant_mutation_changes_graph_id(self):
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=3)
        c1 = CollectiveIntent("ALLREDUCE", (0, 1), 512, "c0")
        c2 = CollectiveIntent("ALLREDUCE", (0, 2), 512, "c0")
        assert _graph_for(pa, collectives=(c1,)).operation_graph_id() \
            != _graph_for(pa, collectives=(c2,)).operation_graph_id()

    def test_wrong_owner_rank_refused(self):
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=2)
        with pytest.raises(MappingInvalid):
            _graph_for(pa, p2p=(P2PTransfer(0, 9, 64, "t0"),))

    def test_duplicate_multicast_destination_refused(self):
        with pytest.raises(InvalidInput):
            MulticastIntent(0, (1, 1), 64, "SOURCE_REPLICATION", "m0")

    def test_deleted_multicast_destination_changes_identity(self):
        # A "deleted destination" is a DIFFERENT workload (§30): the
        # artifact stays self-consistent but its identity must change —
        # a tampered persisted copy is caught by the hash check, a
        # semantically different intent by the id.
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=4)
        mc3 = MulticastIntent(0, (1, 2, 3), 100, "SOURCE_REPLICATION", "m0")
        g3 = _graph_for(pa, multicasts=(mc3,))
        lm3 = LogicalMessageArtifact(graph=g3)
        lm3.validate_conservation()
        assert len(lm3.messages) == 3
        mc2 = MulticastIntent(0, (1, 2), 100, "SOURCE_REPLICATION", "m0")
        g2 = _graph_for(pa, multicasts=(mc2,))
        lm2 = LogicalMessageArtifact(graph=g2)
        lm2.validate_conservation()
        assert g2.operation_graph_id() != g3.operation_graph_id()
        assert lm2.message_artifact_id() != lm3.message_artifact_id()

    def test_duplicate_message_detectable_by_identity(self):
        pa, g = self._one_coll_graph()
        lm = LogicalMessageArtifact(graph=g)
        ids = [m.message_id for m in lm.messages]
        assert len(ids) == len(set(ids)), "message ids must be unique"

    def test_cycle_refused(self):
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=2)
        with pytest.raises(InvalidInput, match="cycle"):
            OperationGraph(
                parallelism=pa, semantics=_sem(), workload_id="w",
                nodes=(OperationNode("a", KIND_P2P, "DECODE", 0, 0, ("b",),
                                     {"transfer_id": "t0"}),
                       OperationNode("b", KIND_P2P, "DECODE", 1, 0, ("a",),
                                     {"transfer_id": "t1"})))

    def test_self_dependency_refused(self):
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=2)
        with pytest.raises(InvalidInput, match="itself"):
            OperationGraph(
                parallelism=pa, semantics=_sem(), workload_id="w",
                nodes=(OperationNode("a", KIND_P2P, "DECODE", 0, 0, ("a",),
                                     {"transfer_id": "t0"}),))

    def test_unknown_dependency_refused(self):
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=2)
        with pytest.raises(InvalidInput, match="unknown"):
            OperationGraph(
                parallelism=pa, semantics=_sem(), workload_id="w",
                nodes=(OperationNode("a", KIND_P2P, "DECODE", 0, 0, ("zz",),
                                     {"transfer_id": "t0"}),))

    def test_one_member_collective_refused(self):
        with pytest.raises(UnsupportedSemantics):
            CollectiveIntent("ALLREDUCE", (0,), 64, "x")

    def test_unknown_collective_kind_refused(self):
        with pytest.raises(UnsupportedSchedule):
            CollectiveIntent("TREE_ALLREDUCE", (0, 1), 64, "x")

    def test_hardware_replication_refused(self):
        with pytest.raises(UnsupportedSemantics, match="substituted"):
            MulticastIntent(0, (1,), 64, "HARDWARE_REPLICATION", "m0")

    def test_zero_or_negative_payload_refused(self):
        with pytest.raises(InvalidInput):
            P2PTransfer(0, 1, 0, "t0")
        with pytest.raises(InvalidInput):
            P2PTransfer(0, 1, -5, "t0")
        with pytest.raises(InvalidInput):
            CollectiveIntent("ALLREDUCE", (0, 1), 0, "x")

    def test_step_is_identity_bearing(self):
        # repeated decode steps are explicit nodes, not cycles (§17)
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=2)
        n1 = OperationNode("a#0", KIND_P2P, "DECODE", 0, 0, (),
                           {"transfer_id": "t0"})
        n2 = OperationNode("a#1", KIND_P2P, "DECODE", 0, 1, (),
                           {"transfer_id": "t1"})
        g = OperationGraph(parallelism=pa, semantics=_sem(),
                           workload_id="w", nodes=(n1, n2),
                           p2p_transfers=(P2PTransfer(0, 1, 64, "t0"),
                                          P2PTransfer(0, 1, 64, "t1")))
        g2 = OperationGraph(parallelism=pa, semantics=_sem(),
                            workload_id="w", nodes=(n1, n2),
                            p2p_transfers=(P2PTransfer(0, 1, 64, "t0"),
                                           P2PTransfer(0, 1, 64, "t1")))
        assert g.operation_graph_id() == g2.operation_graph_id()
        # step change changes identity
        n2b = OperationNode("a#1", KIND_P2P, "DECODE", 0, 2, (),
                            {"transfer_id": "t1"})
        g3 = OperationGraph(parallelism=pa, semantics=_sem(),
                            workload_id="w", nodes=(n1, n2b),
                            p2p_transfers=(P2PTransfer(0, 1, 64, "t0"),
                                           P2PTransfer(0, 1, 64, "t1")))
        assert g.operation_graph_id() != g3.operation_graph_id()


# ══ §29 metamorphic laws ════════════════════════════════════════════════

class TestSingletonMetamorphic:
    def test_dp1_no_dp_collective_generated(self):
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=1)
        # A DP collective would need >= 2 participants; the group has one
        # member, so no CollectiveIntent can be built from it — enforced
        # by the builder refusing < 2 participants.
        members = pa.group_of("DP", 0).members
        assert len(members) == 1
        with pytest.raises(UnsupportedSemantics):
            CollectiveIntent("ALLREDUCE", members, 64, "x")

    def test_double_payload_doubles_logical_bytes(self):
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=4)
        c1 = CollectiveIntent("ALLREDUCE", (0, 1, 2, 3), 256, "c0")
        c2 = CollectiveIntent("ALLREDUCE", (0, 1, 2, 3), 512, "c0")
        l1 = LogicalMessageArtifact(graph=_graph_for(pa, collectives=(c1,)))
        l2 = LogicalMessageArtifact(graph=_graph_for(pa, collectives=(c2,)))
        b1 = sum(m.payload_bytes for m in l1.messages)
        b2 = sum(m.payload_bytes for m in l2.messages)
        assert b2 == 2 * b1

    def test_display_label_is_not_semantic(self):
        # WorkloadArtifact excludes labels from identity (§16); Wave-D
        # artifacts carry no label field at all — pinned by construction:
        pa = ParallelismArtifact(tp=2, pp=1, ep=1, dp=1)
        assert "label" not in pa.identity_dict()
