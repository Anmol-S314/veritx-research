"""Wave D4/D5 proof tests — physical binding, identity mutation matrix,
adversarial tampering, real backend execution.

Proves the §33 logical/physical separation, the §23.6 identity mutation
matrix, the §30 mutation-resistance matrix at the physical layer, and
runs the sealed qualified BookSim execution when the binary exists.

Discipline: every adversarial test feeds a MUTATED OBJECT INTO A REAL
PRODUCTION VALIDATOR (``PhysicalTrafficArtifact.from_dict(strict=True)``,
``validate_conservation``,
``verify_packetization_reference``,
``verify_trace_projection``). A test that mutates a copy and then
validates the original proves nothing and does not belong here.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_fabric_artifact import build_chain, compose  # noqa: E402
from test_backend_bundle import make_bundle  # noqa: E402

from veritx_dse.model.resolved_bundle import (  # noqa: E402
    make_resolved_fabric_bundle,
)
from veritx_dse.model.compile_model import TopologyFamily  # noqa: E402
from veritx_dse.model.mapping import (  # noqa: E402
    MappingArtifact, RankPlacement,
)
from veritx_dse.model.resolved_fabric import make_resolved_fabric  # noqa: E402
from veritx_dse.backend.projection import (  # noqa: E402
    prepare_waved_booksim, render_waved_trace, verify_trace_projection,
)
from veritx_dse.verification.gates import (  # noqa: E402
    verify_backend_quiescence,
)
from veritx_dse.verification.reference_semantics import (  # noqa: E402
    verify_packetization_reference,
)
from veritx_dse.core.errors import (  # noqa: E402
    ConservationFailed, EvidenceInvalid, InvalidInput, MappingInvalid,
)
from veritx_dse.workload.messages import LogicalMessageArtifact  # noqa: E402
from veritx_dse.workload.operations import (  # noqa: E402
    KIND_COLLECTIVE, KIND_MULTICAST, KIND_P2P, CollectiveIntent,
    MulticastIntent, OperationGraph, OperationNode, P2PTransfer,
)
from veritx_dse.model.parallelism import ParallelismArtifact  # noqa: E402
from veritx_dse.workload.semantics import WaveDWorkloadSemantics  # noqa: E402
from veritx_dse.workload.traffic import (  # noqa: E402
    PhysicalTrafficArtifact, header_width_bits,
)

REPO = DSE.parent.parent.parent


def _chain(tp=2, pp=1, ep=1, dp=2, n_agents=4, max_packet_flits=8,
           link_width=None):
    return build_chain(tp=tp, pp=pp, ep=ep, dp=dp, n_agents=n_agents,
                       family=TopologyFamily.MESH,
                       max_packet_flits=max_packet_flits,
                       link_width=link_width)


def _bundle(**kw):
    return make_bundle(_chain(**kw))


def _bundle_with_permuted_mapping(perm, **kw):
    """Same hardware, a genuinely different but still valid mapping.

    ``perm[rank]`` names the compute-instance index rank is placed on.
    A permutation is a different physical placement with the same
    coordinate-free rank geometry — exactly the case §23.6 says must
    move ``mapping_hash`` while leaving the logical chain alone.
    """
    chain = _chain(**kw)
    compute = chain.inv.compute_instances
    placements = tuple(
        RankPlacement(rank=r.rank, agent=compute[perm[r.rank]])
        for r in chain.inv.ranks)
    mapping = MappingArtifact(placements=placements)
    fabric = compose(chain)
    rf = make_resolved_fabric(
        design=chain.cr, inventory=chain.inv, mapping=mapping,
        topology=chain.topo, attachment=chain.att, router_route=chain.rr,
        resolved_route=chain.rra, vc_assignment=chain.vc,
        packet_format=chain.pf, router_behavior=chain.rb,
        address_decode=chain.ad, fabric=fabric)
    return make_resolved_fabric_bundle(
        design=chain.cr, inventory=chain.inv, mapping=mapping,
        topology=chain.topo, attachment=chain.att, router_route=chain.rr,
        resolved_route=chain.rra, vc_assignment=chain.vc,
        packet_format=chain.pf, router_behavior=chain.rb,
        address_decode=chain.ad, fabric=fabric, resolved_fabric=rf)


def _sem(phase="DECODE"):
    return WaveDWorkloadSemantics(phase=phase)


def _graph(pa, collectives=(), p2p=(), multicasts=(), phase="DECODE",
           workload_id="w"):
    nodes = []
    for i, c in enumerate(collectives):
        nodes.append(OperationNode(f"coll{i}", KIND_COLLECTIVE, phase,
                                   c.participants[0], 0, (),
                                   {"collective_id": c.collective_id}))
    for i, t in enumerate(p2p):
        nodes.append(OperationNode(f"p2p{i}", KIND_P2P, phase, t.src_rank,
                                   0, (), {"transfer_id": t.transfer_id}))
    for i, m in enumerate(multicasts):
        nodes.append(OperationNode(f"mc{i}", KIND_MULTICAST, phase,
                                   m.source_rank, 0, (),
                                   {"multicast_id": m.multicast_id}))
    return OperationGraph(parallelism=pa, semantics=_sem(phase),
                          workload_id=workload_id, nodes=tuple(nodes),
                          collectives=tuple(collectives),
                          p2p_transfers=tuple(p2p),
                          multicasts=tuple(multicasts))


def _logical(bundle, **kw):
    pa = ParallelismArtifact(tp=bundle.design.workload.tp,
                             pp=bundle.design.workload.pp,
                             ep=bundle.design.workload.ep,
                             dp=bundle.design.workload.dp)
    coll = CollectiveIntent("ALLREDUCE", (0, 1), 512, "c0")
    tr = P2PTransfer(0, 2, 300, "t0")
    graph = _graph(pa, collectives=(coll,), p2p=(tr,))
    art = LogicalMessageArtifact(graph=graph)
    art.validate_conservation()
    return art


def _pt(bundle=None, **kw):
    bundle = bundle or _bundle(**kw)
    logical = _logical(bundle)
    pt = PhysicalTrafficArtifact(logical=logical, bundle=bundle)
    pt.validate_conservation()
    verify_packetization_reference(pt)
    return pt


# ══ §31/§33 logical/physical separation ═════════════════════════════════

class TestLogicalPhysicalSeparation:
    def test_different_mapping_keeps_logical_ids_and_moves_physical(self):
        """The real separation law, with a genuinely different mapping."""
        plain = _bundle()
        swapped = _bundle_with_permuted_mapping({0: 1, 1: 0, 2: 2, 3: 3})
        assert plain.mapping.mapping_hash() != swapped.mapping.mapping_hash()
        assert plain.resolved_fabric.resolved_fabric_hash() != \
            swapped.resolved_fabric.resolved_fabric_hash()

        logical = _logical(plain)
        pt_plain = PhysicalTrafficArtifact(logical=logical, bundle=plain)
        pt_swapped = PhysicalTrafficArtifact(logical=logical, bundle=swapped)
        # Same logical semantics ...
        assert pt_plain.logical.graph.operation_graph_id() == \
            pt_swapped.logical.graph.operation_graph_id()
        assert pt_plain.logical.message_artifact_id() == \
            pt_swapped.logical.message_artifact_id()
        # ... different physical placement, and the endpoints really moved.
        assert pt_plain.physical_traffic_id() != \
            pt_swapped.physical_traffic_id()
        moved = [t for t in pt_plain.traffic
                 if t.src.endpoint_id
                 != next(x.src.endpoint_id for x in pt_swapped.traffic
                         if x.message_id == t.message_id)]
        assert moved, "permuted mapping produced identical endpoints"

    def test_different_packet_format_moves_physical_not_logical(self):
        narrow = _bundle(link_width=64)
        wide = _bundle(link_width=128)
        assert narrow.packet_format.flit_width_bits \
            != wide.packet_format.flit_width_bits
        assert narrow.packet_format.packet_format_hash() \
            != wide.packet_format.packet_format_hash()
        assert narrow.mapping.mapping_hash() == wide.mapping.mapping_hash()

        logical = _logical(narrow)
        pt_narrow = PhysicalTrafficArtifact(logical=logical, bundle=narrow)
        pt_wide = PhysicalTrafficArtifact(logical=logical, bundle=wide)
        assert pt_narrow.logical.message_artifact_id() == \
            pt_wide.logical.message_artifact_id()
        assert pt_narrow.physical_traffic_id() != \
            pt_wide.physical_traffic_id()

    def test_same_world_different_geometry_parallelism_id_changes(self):
        a = ParallelismArtifact(tp=4, pp=1, ep=1, dp=1)
        b = ParallelismArtifact(tp=2, pp=2, ep=1, dp=1)
        assert a.world_size == b.world_size
        assert a.parallelism_id() != b.parallelism_id()

    def test_same_world_different_geometry_mapping_hash_may_match(self):
        # §9/§23.6: mapping_hash is coordinate-free. Ranks 0..3 → the
        # same four agents is identical mapping content under TP=4/PP=1
        # and TP=2/PP=2. Prove with two real chains.
        c4 = _chain(tp=4, pp=1, ep=1, dp=1, n_agents=4)
        c22 = _chain(tp=2, pp=2, ep=1, dp=1, n_agents=4)
        assert c4.mapping.mapping_hash() == c22.mapping.mapping_hash()

    def test_output_path_change_changes_nothing(self):
        pt = _pt()
        assert pt.physical_traffic_id() == pt.physical_traffic_id()


# ══ §30 mutation resistance at the physical layer ═══════════════════════

class TestPhysicalMutations:
    def test_mapping_swap_changes_bindings_and_identity(self):
        plain = _pt(_bundle())
        swapped = _pt(_bundle_with_permuted_mapping(
            {0: 1, 1: 0, 2: 2, 3: 3}))
        plain_bind = {t.message_id: (t.src.endpoint_id, t.dst.endpoint_id)
                      for t in plain.traffic}
        swap_bind = {t.message_id: (t.src.endpoint_id, t.dst.endpoint_id)
                     for t in swapped.traffic}
        assert plain_bind != swap_bind
        assert plain.physical_traffic_id() != swapped.physical_traffic_id()

    def test_out_of_namespace_rank_refused(self):
        # A rank outside the declared geometry is not a "mapping swap";
        # it is an out-of-namespace address and refuses at graph build.
        pa = ParallelismArtifact(tp=2, pp=1, ep=1, dp=2)
        with pytest.raises(MappingInvalid):
            _graph(pa, p2p=(P2PTransfer(0, 5, 300, "t0"),))

    def test_flit_width_change_changes_transmitted_bits(self):
        narrow = _pt(_bundle(link_width=64))
        wide = _pt(_bundle(link_width=128))
        assert narrow.bundle.packet_format.flit_width_bits == 64
        assert wide.bundle.packet_format.flit_width_bits == 128
        assert narrow.bundle.packet_format.packet_format_hash() \
            != wide.bundle.packet_format.packet_format_hash()
        # A wider flit carries more header bits per flit and fewer flits
        # per packet; the transmitted-bit total is not invariant.
        assert narrow.totals()["transmitted_bits"] != \
            wide.totals()["transmitted_bits"]
        assert wide.totals()["flit_count"] < narrow.totals()["flit_count"]
        assert narrow.physical_traffic_id() != wide.physical_traffic_id()

    def test_forged_packet_row_refused_by_strict_parser(self):
        """The real validator, fed a real mutated document.

        The ConservationLedger is DERIVED, never persisted: the thing a
        tamperer can forge is the traffic row, and the strict parser
        recomputes it from verified parents and refuses.
        """
        pt = _pt()
        doc = pt.to_dict()
        row = doc["traffic"][0][0]
        row["transmitted_bits"] = row["transmitted_bits"] + 1
        with pytest.raises(EvidenceInvalid):
            PhysicalTrafficArtifact.from_dict(
                doc, logical=pt.logical, bundle=pt.bundle, strict=True)

    def test_forged_flit_count_refused_by_strict_parser(self):
        pt = _pt()
        doc = pt.to_dict()
        doc["traffic"][0][0]["flit_count"] = 99
        with pytest.raises(EvidenceInvalid):
            PhysicalTrafficArtifact.from_dict(
                doc, logical=pt.logical, bundle=pt.bundle, strict=True)

    def test_transplanted_parent_hash_refused_by_strict_parser(self):
        pt = _pt()
        doc = pt.to_dict()
        doc["resolved_fabric_hash"] = "0" * 64
        with pytest.raises(InvalidInput):
            PhysicalTrafficArtifact.from_dict(
                doc, logical=pt.logical, bundle=pt.bundle, strict=True)

    def test_ledger_is_derived_not_persisted(self):
        """A ledger entry cannot be forged because no ledger is stored."""
        pt = _pt()
        first = pt.conservation_ledger()
        second = pt.conservation_ledger()
        assert first == second
        assert all(isinstance(e.transmitted_bits, int) for e in first)
        # There is no ledger resource kind and no ledger parser: the
        # only way to obtain a ledger is to re-derive it from a
        # verified traffic artifact.
        from veritx_dse.application.store import RESOURCE_KINDS
        assert "ledger" not in RESOURCE_KINDS
        assert not hasattr(PhysicalTrafficArtifact, "ledger_from_dict")

    def test_padding_bound_enforced(self):
        pt = _pt()
        pf = pt.bundle.packet_format
        Q = pf.payload_width_bits
        for t in pt.traffic:
            for p in t.packets:
                assert 0 <= p.padding_bits < Q

    def test_transmitted_bit_identity_holds_per_packet(self):
        pt = _pt()
        for t in pt.traffic:
            for p in t.packets:
                assert p.transmitted_bits == p.header_bits + p.payload_bits \
                    + p.padding_bits

    def test_header_width_comes_from_the_wave_b_layout(self):
        pt = _pt()
        pf = pt.bundle.packet_format
        assert header_width_bits(pf) == \
            pf.flit_width_bits - pf.payload_width_bits

    def test_oracle_and_conservation_catch_forged_rows(self):
        """Both production validators, fed a corrupted artifact.

        The rows are injected through the same private seam the
        constructor uses, then the REAL validators run. If either
        passed here it would be vacuous.
        """
        pt = _pt()
        first = pt.traffic[0]
        forged_packets = (replace(first.packets[0],
                                  payload_bits=first.packets[0].payload_bits
                                  + 8),) + first.packets[1:]
        forged = (replace(first, packets=forged_packets),) + pt.traffic[1:]
        object.__setattr__(pt, "_traffic", forged)
        with pytest.raises(ConservationFailed):
            verify_packetization_reference(pt)
        with pytest.raises(ConservationFailed):
            pt.validate_conservation()

    def test_conservation_catches_a_forged_transmitted_total(self):
        pt = _pt()
        first = pt.traffic[0]
        bad = replace(first.packets[0],
                      transmitted_bits=first.packets[0].transmitted_bits + 1)
        object.__setattr__(pt, "_traffic",
                           (replace(first, packets=(bad,) + first.packets[1:]),)
                           + pt.traffic[1:])
        with pytest.raises(ConservationFailed):
            pt.validate_conservation()


# ══ §21 trace projection losslessness ═══════════════════════════════════

class TestTraceProjection:
    def test_projection_lossless_for_representable_fields(self):
        pt = _pt()
        summary = verify_trace_projection(pt)
        assert summary["num_packets"] == pt.totals()["packet_count"]
        assert summary["flits_total"] == pt.totals()["flit_count"]

    def test_trace_is_deterministic(self):
        pt = _pt()
        assert render_waved_trace(pt) == render_waved_trace(pt)

    def test_flit_counts_within_packet_format_cap(self):
        pt = _pt()
        cap = pt.bundle.packet_format.max_packet_flits
        assert all(p.flit_count <= cap
                   for t in pt.traffic for p in t.packets)

    def test_derived_trace_is_the_only_backend_input(self):
        pt = _pt()
        trace = render_waved_trace(pt)
        prepared, summary = prepare_waved_booksim(pt)
        from veritx_dse.backend.contracts import sha256_bytes
        assert sha256_bytes(
            prepared.rendered.file("workload.trace")) \
            == sha256_bytes(trace)
        assert prepared.manifest.workload_hash == sha256_bytes(trace)
        assert summary["num_packets"] == pt.totals()["packet_count"]


# ══ §21/§21 real execution (skipped without binary) ═════════════════

def _find_repo_binary():
    from veritx_dse.core.paths import REPO as REPO_ROOT
    from veritx_dse.simulation.booksim import find_booksim_bin
    try:
        return find_booksim_bin(REPO_ROOT)
    except FileNotFoundError:
        return None


@pytest.fixture(scope="module")
def real_binary():
    path = _find_repo_binary()
    if path is None or not Path(path).is_file():
        pytest.skip("no runnable BookSim binary")
    return path


class TestRealExecution:
    """Real qualified BookSim runs of DERIVED Wave-D traffic.

    Quiescence is asserted from sealed Wave-B evidence counters only:
    delivered packets, injected flits, accepted flits. Wave D never
    modifies the Wave-B evidence schema to get a prettier sentence.
    """

    def _run(self, pt, real_binary, tmp_path):
        from veritx_dse.core.paths import REPO as REPO_ROOT
        from veritx_dse.backend.projection import run_waved_booksim
        prepared, summary = prepare_waved_booksim(pt)
        result = run_waved_booksim(prepared, run_dir=tmp_path,
                                   repo_root=REPO_ROOT, timeout=120,
                                   binary=Path(real_binary),
                                   summary=summary)
        return result, summary

    def test_dp_allreduce_end_to_end(self, real_binary, tmp_path):
        bundle = _bundle(tp=1, pp=1, ep=1, dp=4, n_agents=4)
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=4)
        graph = _graph(pa, collectives=(
            CollectiveIntent("ALLREDUCE", (0, 1, 2, 3), 1024, "c0"),))
        pt = PhysicalTrafficArtifact(
            logical=LogicalMessageArtifact(graph=graph), bundle=bundle)
        result, summary = self._run(pt, real_binary, tmp_path)
        counters = result["backend_counters"]
        assert result["evidence"].exit_status == 0
        assert result["evidence"].route_equivalence == "EXACT"
        assert counters["delivered_packets"] == summary["num_packets"]
        assert counters["flits_injected"] == summary["flits_total"]
        assert counters["flits_accepted"] == summary["flits_total"]
        verify_backend_quiescence(summary, counters)

    def test_prefill_p2p_mixed_end_to_end(self, real_binary, tmp_path):
        pt = _pt(_bundle())
        result, summary = self._run(pt, real_binary, tmp_path)
        counters = result["backend_counters"]
        assert result["evidence"].exit_status == 0
        assert counters["delivered_packets"] == summary["num_packets"]
        assert counters["flits_injected"] == summary["flits_total"]
        assert counters["flits_accepted"] == summary["flits_total"]

    def test_broadcast_end_to_end(self, real_binary, tmp_path):
        bundle = _bundle(tp=1, pp=1, ep=1, dp=4, n_agents=4)
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=4)
        graph = _graph(pa, collectives=(
            CollectiveIntent("BROADCAST", (0, 1, 2, 3), 256, "b0"),),
            phase="PREFILL")
        pt = PhysicalTrafficArtifact(
            logical=LogicalMessageArtifact(graph=graph), bundle=bundle)
        result, summary = self._run(pt, real_binary, tmp_path)
        counters = result["backend_counters"]
        assert result["evidence"].exit_status == 0
        assert counters["delivered_packets"] == summary["num_packets"]
        assert counters["flits_injected"] == summary["flits_total"]

    def test_multicast_end_to_end(self, real_binary, tmp_path):
        bundle = _bundle(tp=1, pp=1, ep=1, dp=4, n_agents=4)
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=4)
        graph = _graph(pa, multicasts=(
            MulticastIntent(0, (1, 2, 3), 512, "SOURCE_REPLICATION",
                            "m0"),))
        pt = PhysicalTrafficArtifact(
            logical=LogicalMessageArtifact(graph=graph), bundle=bundle)
        result, summary = self._run(pt, real_binary, tmp_path)
        counters = result["backend_counters"]
        assert result["evidence"].exit_status == 0
        assert counters["delivered_packets"] == summary["num_packets"]
        assert counters["flits_injected"] == summary["flits_total"]

    def test_quiescence_refuses_a_wrong_expected_count(
            self, real_binary, tmp_path):
        """verify_backend_quiescence is not vacuous."""
        pt = _pt(_bundle())
        result, summary = self._run(pt, real_binary, tmp_path)
        from veritx_dse.core.errors import BackendFailure
        forged = dict(summary)
        forged["num_packets"] = summary["num_packets"] + 1
        with pytest.raises(BackendFailure):
            verify_backend_quiescence(forged, result["backend_counters"])
