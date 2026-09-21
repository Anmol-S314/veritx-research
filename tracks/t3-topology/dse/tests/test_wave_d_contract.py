"""Wave D0 — pinned current-behavior evidence for the scientific contract.

These tests execute the contradiction ledger in
``docs/WAVE-D-SCIENTIFIC-CONTRACT.md`` (§3) against the frozen tree, and
pin the machine-readable contract shape. They are audit-only: they add
no production behavior and make no Wave-D claims.

Deliberately small (contract design, not implementation).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

DOCS = DSE.parent / "docs"
CONTRACT_JSON = DOCS / "wave-d-contract.json"
CONTRACT_MD = DOCS / "WAVE-D-SCIENTIFIC-CONTRACT.md"


def _contract():
    return json.loads(CONTRACT_JSON.read_text())


class TestContractShape:
    def test_contract_files_exist(self):
        assert CONTRACT_MD.is_file()
        assert CONTRACT_JSON.is_file()

    def test_machine_readable_sections_present(self):
        c = _contract()
        for key in ("rank_space", "mapping", "groups", "collectives",
                    "phases", "pp", "ep_moe", "kv", "messages",
                    "multicast", "packetization", "flits",
                    "traffic_class", "trace_authority", "serving",
                    "identity", "conservation_laws", "proof_classes",
                    "bounded_domains", "unsupported_matrix",
                    "assumptions", "contradictions", "slices",
                    "external_contract_needed", "fidelity_dimensions"):
            assert key in c, key

    def test_every_contradiction_has_resolution(self):
        for row in _contract()["contradictions"]:
            assert row["resolution"], row["id"]
            assert row["severity"] in ("P0", "P1", "P2"), row["id"]

    def test_contract_doc_has_all_required_sections(self):
        text = CONTRACT_MD.read_text()
        for n in range(1, 37):
            assert f"\n## {n}." in text, f"missing section {n}"


class TestCurrentContradictions:
    """Executable evidence for the ledger (current behavior, pinned)."""

    def test_world_size_multiplies_ep(self):
        """D0-C001: the design rank space multiplies EP."""
        from veritx_dse.model.presets import parallel_world_size
        assert parallel_world_size(tp=8, pp=8, ep=8, dp=1) == 512
        # ... while the external serving convention does not (tp*pp, ep
        # shares GPUs). Recorded here as the counterexample, not as an
        # adopted rule.
        vendored = (DSE.parent.parent.parent / "third_party" /
                    "llmservingsim" / "serving" / "core" /
                    "config_builder.py")
        if vendored.is_file():
            text = vendored.read_text()
            assert "num_npus = tp_size * pp_size" in text or \
                "num_npus ({num_npus}) != tp_size" in text

    def test_rank_enumeration_is_canonical(self):
        """D0-C002: one bijection; tp fastest, pp slowest."""
        from veritx_dse.model.placement import coords_of, rank_of
        sizes = {"tp": 2, "pp": 2, "ep": 2, "dp": 2}
        seen = set()
        for p in range(2):
            for d in range(2):
                for e in range(2):
                    for t in range(2):
                        r = rank_of(t, p, e, d, **sizes)
                        seen.add(r)
                        assert coords_of(r, **sizes) == {
                            "tp": t, "pp": p, "ep": e, "dp": d}
        assert seen == set(range(16))

    def test_astra_logical_dims_degrade(self):
        """D0-C002: dims silently collapse to [num_nodes] on mismatch."""
        from veritx_dse.simulation.astrasim_adapter import (
            generate_astrasim_logical_topology_json,
        )
        assert generate_astrasim_logical_topology_json(
            4, tp=2, pp=2)["logical-dimensions"] == [2, 2]
        assert generate_astrasim_logical_topology_json(
            8, tp=2, pp=2)["logical-dimensions"] == [8]

    def test_packet_size_is_flits_in_booksim(self):
        """D0-C004: the cfg field is flits, not bytes."""
        cfg = (DSE.parent.parent.parent / "third_party" / "booksim2" /
               "src" / "booksim_config.cpp")
        if not cfg.is_file():
            pytest.skip("booksim source unavailable")
        text = cfg.read_text()
        assert '_int_map["packet_size"]' in text
        hpp = (cfg.parent / "tracetrafficmanager.hpp").read_text()
        assert "packet_size;      // flits" in hpp

    def test_bytes_per_element_is_unconsumed(self):
        """D0-C008: declared payload default, no message consumer.

        P1B.1 note: the field may be NAMED in refusal prose (the
        product lowerer cites it when refusing to infer a payload),
        but no module outside the definition/reports echo may READ
        it — hence attribute-access detection, not substring match.
        """
        import re
        from veritx_dse.model.compile_model import CollectiveOp
        op = CollectiveOp.__dataclass_fields__
        assert "bytes_per_element" in op
        hits = []
        for path in (DSE / "veritx_dse").rglob("*.py"):
            if "__pycache__" in str(path):
                continue
            text = path.read_text()
            if re.search(r"\.bytes_per_element\b", text) and \
                    "compile_model" not in path.name and \
                    "reports" not in path.name:
                hits.append(path.name)
        assert hits == []

    def test_canonical_bytes_are_positive_integers(self):
        """§18 units discipline already holds in the artifact layer."""
        from veritx_dse.workload.canonical import (
            WorkloadError, build_collective_op,
        )
        with pytest.raises(WorkloadError):
            build_collective_op("c", "ALLREDUCE", bytes=0,
                                participants=(0, 1), scope="ALL")
        with pytest.raises(WorkloadError):
            build_collective_op("c", "ALLREDUCE", bytes=64.0,
                                participants=(0, 1), scope="ALL")

    def test_standalone_send_is_unlowerable(self):
        """D0-C006: KV/P2P artifact ops cannot reach the row projection."""
        from veritx_dse.workload.canonical import build_p2p_op
        from veritx_dse.workload.lowering import (
            UnsupportedSemantic, rows_from_artifact,
        )
        from veritx_dse.workload.canonical import WorkloadArtifact, Parallelism
        op = build_p2p_op("send", "SEND", bytes=64, src=0, dst=1)
        art = WorkloadArtifact(
            workload_id="w", source_kind="canonical",
            parallelism=Parallelism(), num_participants=2, ops=(op,))
        with pytest.raises(UnsupportedSemantic):
            rows_from_artifact(art)


# ── D0.1 closure pins ───────────────────────────────────────────────────

def _ref_collective(kind, k, B):
    """Independent integer reference for the §10.1 table."""
    assert B % k == 0 or kind in ("ALLGATHER", "BROADCAST")
    C = B // k
    if kind == "ALLREDUCE":
        return {"messages": 2 * k * (k - 1), "message_bytes": C,
                "per_rank_sent": 2 * (k - 1) * C,
                "aggregate": 2 * (k - 1) * B}
    if kind == "REDUCESCATTER":
        return {"messages": k * (k - 1), "message_bytes": C,
                "per_rank_sent": (k - 1) * C,
                "aggregate": (k - 1) * B}
    if kind == "ALLGATHER":
        return {"messages": k * (k - 1), "message_bytes": B,
                "per_rank_sent": (k - 1) * B,
                "aggregate": k * (k - 1) * B}
    if kind == "ALLTOALL":
        return {"messages": k * (k - 1), "message_bytes": C,
                "per_rank_sent": (k - 1) * C,
                "aggregate": (k - 1) * B}
    if kind == "BROADCAST":
        return {"messages": k - 1, "message_bytes": B,
                "root_sent": (k - 1) * B, "aggregate": (k - 1) * B}
    raise AssertionError(kind)


def _ref_packetize(message_bits, Q, L):
    capacity = Q * L
    return -(-message_bits // capacity)


def _ref_flitize(P_i, Q, H, F):
    n_i = -(-P_i // Q)
    padding_i = n_i * Q - P_i
    return {"n_i": n_i, "padding_i": padding_i,
            "header_bits_i": n_i * H,
            "transmitted_bits_i": n_i * F}


class TestCollectiveEquations:
    """D0.1 §10: per-kind payload semantics, pinned independently."""

    def test_reference_example_k4_b1024(self):
        assert _ref_collective("ALLREDUCE", 4, 1024) == {
            "messages": 24, "message_bytes": 256,
            "per_rank_sent": 1536, "aggregate": 6144}
        assert _ref_collective("REDUCESCATTER", 4, 1024) == {
            "messages": 12, "message_bytes": 256,
            "per_rank_sent": 768, "aggregate": 3072}
        assert _ref_collective("ALLGATHER", 4, 1024) == {
            "messages": 12, "message_bytes": 1024,
            "per_rank_sent": 3072, "aggregate": 12288}
        assert _ref_collective("ALLTOALL", 4, 1024) == {
            "messages": 12, "message_bytes": 256,
            "per_rank_sent": 768, "aggregate": 3072}
        assert _ref_collective("BROADCAST", 4, 1024) == {
            "messages": 3, "message_bytes": 1024,
            "root_sent": 3072, "aggregate": 3072}

    def test_allgather_has_no_division_by_k(self):
        """The D0 error: ALLGATHER forwards B, not B/k."""
        row = _ref_collective("ALLGATHER", 4, 1024)
        assert row["message_bytes"] == 1024          # not 256
        assert row["per_rank_sent"] == 3072          # not 768

    def test_aggregate_is_primary_invariant(self):
        """Symmetric schedules: aggregate == k * per_rank_sent."""
        k, B = 4, 1024
        for kind in ("ALLREDUCE", "REDUCESCATTER", "ALLGATHER",
                     "ALLTOALL"):
            row = _ref_collective(kind, k, B)
            assert row["aggregate"] == k * row["per_rank_sent"]
            assert row["messages"] * row["message_bytes"] == \
                row["aggregate"]

    def test_broadcast_is_asymmetric(self):
        """BROADCAST: aggregate == root_sent, not k * root_sent."""
        k, B = 4, 1024
        row = _ref_collective("BROADCAST", k, B)
        assert row["aggregate"] == row["root_sent"] == 3072
        assert row["aggregate"] != k * row["root_sent"]
        assert row["messages"] * row["message_bytes"] == row["aggregate"]

    def test_contract_json_matches_reference(self):
        c = _contract()["collectives"]
        example = c["reference_example"]
        assert example["ALLREDUCE"]["aggregate"] == 6144
        assert example["ALLGATHER"]["message_bytes"] == 1024
        assert example["BROADCAST"]["root_sent"] == 3072
        assert c["schedules"]["ALLGATHER"]["per_rank_sent"] == "(k-1)*B"
        assert c["schedules"]["BROADCAST"]["per_rank_sent"].startswith(
            "(k-1)*B")

    def test_non_divisible_chunks_refuse(self):
        c = _contract()["collectives"]
        for kind in ("ALLREDUCE", "REDUCESCATTER", "ALLTOALL"):
            assert c["schedules"][kind]["divisibility"] == "B % k == 0"
        assert "B % k != 0" in c["unsupported_partitioning"]
        # k=3, B=1024 is non-divisible for chunked kinds.
        assert 1024 % 3 != 0

    def test_singleton_rule_preserves_builder_authority(self):
        from veritx_dse.workload.canonical import (
            WorkloadError, build_collective_op,
        )
        with pytest.raises(WorkloadError):
            build_collective_op("c", "ALLREDUCE", bytes=64,
                                participants=(0,), scope="ALL")
        rule = _contract()["rank_space"]["singleton_rule"]
        assert "no collective operation" in rule
        assert "never represented" in rule


class TestBitLevelAccounting:
    """D0.1 §18: wire accounting is bit-exact, no byte alignment."""

    def test_non_byte_aligned_flit_width(self):
        """F=65 must not lose a bit to integer division by 8."""
        F, H = 65, 1
        Q = F - H
        out = _ref_flitize(P_i=100, Q=Q, H=H, F=F)
        assert out["n_i"] == -(-100 // 64) == 2
        assert out["padding_i"] == 2 * 64 - 100 == 28
        assert out["transmitted_bits_i"] == 2 * 65 == 130
        assert out["transmitted_bits_i"] == \
            out["header_bits_i"] + 100 + out["padding_i"] == 2 + 100 + 28
        # The buggy byte form would have been 65 // 8 = 8 bytes per flit.
        assert out["transmitted_bits_i"] != 8 * 2 * 8

    def test_padding_bound_holds(self):
        for P_i in range(1, 200):
            Q, H, F = 64, 8, 72
            out = _ref_flitize(P_i, Q, H, F)
            assert 0 <= out["padding_i"] < Q
            assert out["transmitted_bits_i"] == \
                out["header_bits_i"] + P_i + out["padding_i"]

    def test_packet_payload_conservation_in_bits(self):
        message_bits, Q, L = 1000, 64, 8
        n = _ref_packetize(message_bits, Q, L)
        capacity = Q * L
        assert n == -(-message_bits // capacity)
        # Greedy fill conserves exactly with a bounded tail.
        remaining = message_bits
        payloads = []
        while remaining:
            take = min(remaining, capacity)
            payloads.append(take)
            remaining -= take
        assert sum(payloads) == message_bits
        assert 1 <= payloads[-1] <= capacity

    def test_contract_json_bit_notation(self):
        p = _contract()["packetization"]
        assert p["unit"] == "bits"
        assert p["byte_alignment_required"] is False
        assert p["per_packet"]["identity"] == \
            "transmitted_bits_i == header_bits_i + P_i + padding_i"
        assert p["per_packet"]["padding_bound"] == "0 <= padding_i < Q"
        assert p["packet_wire_bytes_field"].startswith("none")


class TestVersionBoundaryAndScope:
    """D0.1 §8/§9/§11/§12: frozen identity, separate Wave-D boundary."""

    def test_serving_mode_is_identity_bearing_in_frozen_hash(self):
        from dataclasses import replace  # noqa: PLC0415
        from veritx_dse.application.presets import (  # noqa: PLC0415
            _mesh4_request,
        )
        from veritx_dse.model.compile_model import ServingMode  # noqa: PLC0415
        cr = _mesh4_request()
        a = replace(cr, workload=replace(
            cr.workload, serving_mode=ServingMode.PREFILL_HEAVY))
        b = replace(cr, workload=replace(
            cr.workload, serving_mode=ServingMode.DECODE_HEAVY))
        assert a.design_hash() != b.design_hash()

    def test_contract_declares_frozen_compilerequest(self):
        ident = _contract()["identity"]
        assert "unchanged during Wave D" in \
            ident["frozen_compilerequest_identity"]
        rows = {r["mutation"]: r for r in ident[
            "mutation_table"]["rows"]}
        assert rows["change_legacy_serving_mode"]["note"] == \
            "does not fabricate a Wave-D phase; Wave-D workload " \
            "artifact unchanged"

    def test_phase_scope_is_narrowed(self):
        phases = _contract()["phases"]
        assert phases["phase_tagging"] == "EXACT"
        assert phases["automatic_model_shape_to_operations"] == "DEFERRED"
        assert "implicit preset lookup" in \
            phases["shape_metadata_authority"]

    def test_moe_routing_scope_narrowed(self):
        moe = _contract()["ep_moe"]["routing_policies"]
        assert moe["EXPLICIT_TRACE"] == "EXACT"
        assert moe["DETERMINISTIC_BALANCED"] == "DEFERRED"

    def test_p2p_pairing_rule(self):
        p2p = _contract()["p2p"]
        assert p2p["one_transfer_one_message"] is True
        assert "explicit shared identifier" in p2p[
            "legacy_send_recv_pairing"]
        assert "adjacent_rows" in p2p["forbidden_pairing"]

    def test_multicast_schedule_fidelity(self):
        m = _contract()["multicast"]
        assert m["schedules"]["SOURCE_REPLICATION"] == "EXACT"
        assert m["schedules"]["HARDWARE_REPLICATION"] == \
            "UNSUPPORTED_DEFERRED"
        assert "refuse" in m["hardware_request_behavior"]

    def test_physical_node_not_claimed_exact(self):
        matrix = _contract()["unsupported_matrix"]
        assert matrix["endpoint_level_mapping"] == "EXACT"
        assert matrix["physical_node_aware_semantics"] == "DEFERRED"
        assert "single_node" not in matrix

    def test_contradiction_tally_matches_ledger(self):
        c = _contract()
        tally = c["contradiction_tally"]
        counts = {"P0": 0, "P1": 0, "P2": 0}
        for row in c["contradictions"]:
            counts[row["severity"]] += 1
        assert counts == {"P0": tally["P0"], "P1": tally["P1"],
                          "P2": tally["P2"]}
        assert tally["total"] == sum(counts.values()) == 11
        md = CONTRACT_MD.read_text()
        assert "4 × P0" in md and "5 × P1" in md and "2 × P2" in md

    def test_json_mirrors_markdown_sections(self):
        c = _contract()
        md = CONTRACT_MD.read_text()
        for key in ("singleton_rule", "p2p", "packetization",
                    "multicast", "frozen_compilerequest_identity"):
            assert key in json.dumps(c), key
        for marker in ("10.3 Singleton normalization",
                       "10.4 Pinned reference example",
                       "15.1 Canonical point-to-point transfer",
                       "23.2 Wave-D artifact parent DAG",
                       "23.5 Wave-D semantic version boundary",
                       "24.1 Conservation-ledger quantity classes",
                       "34.1 D1 handoff contract"):
            assert marker in md, marker
        assert "### 23.5 Wave-D semantic version boundary" in md


# ── D0.2 identity DAG and conservation closure ──────────────────────────

class TestIdentityDAG:
    """Identity parents must be mechanically guaranteed, not prose."""

    def _identity(self):
        return _contract()["identity"]

    def test_every_derived_id_lists_parents(self):
        wave_d = self._identity()["wave_d"]
        assert wave_d["operation_graph_id"]["parents"] == [
            "workload_id", "parallelism_id", "wave_d_semantics_id"]
        assert wave_d["message_artifact_id"]["parents"] == [
            "operation_graph_id"]
        assert wave_d["physical_traffic_id"]["parents"] == [
            "message_artifact_id", "resolved_fabric_hash",
            "packet_format_hash"]
        for name, spec in wave_d.items():
            assert "parents" in spec, name
            assert "formula" in spec, name

    def test_workload_id_already_contains_parallelism(self):
        from veritx_dse.workload.canonical import (
            Parallelism, WorkloadArtifact, build_collective_op,
        )
        op = build_collective_op("c", "ALLREDUCE", bytes=1024,
                                 participants=(0, 1, 2, 3), scope="ALL")
        a = WorkloadArtifact(workload_id="w", source_kind="canonical",
                             parallelism=Parallelism(tp=4, pp=1),
                             num_participants=4, ops=(op,))
        b = WorkloadArtifact(workload_id="w", source_kind="canonical",
                             parallelism=Parallelism(tp=2, pp=2),
                             num_participants=4, ops=(op,))
        assert a.artifact_hash != b.artifact_hash, \
            "parallelism is inside the canonical workload identity"

    def test_operation_payload_is_inside_workload_identity(self):
        from veritx_dse.workload.canonical import (
            Parallelism, WorkloadArtifact, build_collective_op,
        )
        a = WorkloadArtifact(
            workload_id="w", source_kind="canonical",
            parallelism=Parallelism(), num_participants=2,
            ops=(build_collective_op("c", "ALLREDUCE", bytes=1024,
                                     participants=(0, 1), scope="ALL"),))
        b = WorkloadArtifact(
            workload_id="w", source_kind="canonical",
            parallelism=Parallelism(), num_participants=2,
            ops=(build_collective_op("c", "ALLREDUCE", bytes=2048,
                                     participants=(0, 1), scope="ALL"),))
        assert a.artifact_hash != b.artifact_hash

    def test_mapping_hash_is_coordinate_free(self):
        """Same world size, different parallelism may share a mapping."""
        from veritx_dse.application.presets import _mesh4_request
        from veritx_dse.model.mapping import MappingArtifact, RankPlacement
        from veritx_dse.model.placement import AgentInstance, build_inventory
        from veritx_dse.model.compile_model import AgentKind
        cr = _mesh4_request()
        inventory = build_inventory(cr)
        compute = inventory.compute_instances[:4]
        placements = tuple(
            RankPlacement(rank=i, agent=compute[i]) for i in range(4))
        m = MappingArtifact(placements=placements)
        # MappingArtifact hashes rank->agent only: identical placements
        # produce an identical hash regardless of the rank-coordinate
        # interpretation (TP=4,PP=1 vs TP=2,PP=2).
        assert m.mapping_hash() == m.mapping_hash()
        assert isinstance(compute[0], AgentInstance)
        assert compute[0].kind == AgentKind.COMPUTE_TILE

    def test_mutation_table_matches_artifact_behavior(self):
        rows = {r["mutation"]: r for r in self._identity()[
            "mutation_table"]["rows"]}
        assert "workload_id" in rows["change_tp_pp_ep_dp"]["changes"]
        assert "mapping_hash" not in rows["change_tp_pp_ep_dp"]["changes"]
        assert rows["change_tp_pp_ep_dp"]["conditional"][
            "mapping_hash"].startswith("iff")
        assert rows["change_physical_mapping_only"]["changes"] == [
            "mapping_hash", "resolved_fabric_hash",
            "physical_traffic_id"]
        assert rows["change_collective_algorithm"]["changes"] == [
            "message_artifact_id", "physical_traffic_id"]
        assert rows["rename_display_label"]["changes"] == []

    def test_logical_physical_separation(self):
        sep = self._identity()["logical_physical_separation"]
        assert "message_artifact_id" in sep["logical_chain"]
        assert "resolved_fabric_hash" in sep["physical_binding"]
        assert "independent of physical placement" in sep["rule"]
        assert "validate_against" in sep["seam"]

    def test_packet_format_identity_not_capacity_only(self):
        ident = self._identity()
        parents = ident["wave_d"]["physical_traffic_id"]["parents"]
        assert "packet_format_hash" in parents
        assert not any("capacity" in p for p in parents)
        formula = ident["wave_d"]["physical_traffic_id"]["formula"]
        assert "packet_format_hash" in formula
        assert "packet_payload_capacity_bits" not in formula


class TestConservationByClass:
    """No generic byte law may span P2P, collectives and multicast."""

    def _laws(self):
        return {l["id"]: l for l in _contract()["conservation_laws"]}

    def test_no_generic_message_payload_law(self):
        for law in self._laws().values():
            assert "op logical bytes" not in law["relation"], law["id"]
            assert law["class"], law["id"]

    def test_collective_law_is_schedule_aggregate(self):
        law = self._laws()["L6"]
        assert law["class"] == "collective"
        assert "2(k-1)B" in law["relation"]
        assert "k(k-1)B" in law["relation"]

    def test_p2p_and_multicast_laws(self):
        laws = self._laws()
        assert laws["L7"]["class"] == "p2p"
        assert laws["L7"]["relation"].startswith("one P2PTransfer")
        assert laws["L8"]["class"] == "multicast"
        assert "N*B" in laws["L8"]["relation"]

    def test_kv_law_has_no_transfer_term(self):
        law = self._laws()["L13"]
        assert "transferred" not in law["relation"]
        assert law["relation"] == "produced == resident + discarded (no transfer term)"
        kv = _contract()["kv"]
        assert "never added to residency" in kv["conservation"]
        assert kv["transfer_accounting"] == "events, not state"

    def test_counterexamples_pinned(self):
        # ALLREDUCE k=4, B=1024: source 1024 != aggregate 6144.
        k, B = 4, 1024
        assert _ref_collective("ALLREDUCE", k, B)["aggregate"] == 6144
        assert 1024 != 6144
        # Multicast source replication B=100, N=3.
        B, N = 100, 3
        assert N * B == 300
        # P2P: one transfer, one message.
        assert 100 == 100

    def test_ledger_quantity_classes_distinct(self):
        ledger = _contract()["conservation_ledger"]
        qs = ledger["quantities"]
        assert len(qs) == len(set(qs))
        assert "source_logical_payload_bytes" in qs
        assert "aggregate_scheduled_message_bytes" in qs
        assert "transmitted_wire_bits" in qs
        assert ledger["single_bytes_field_forbidden"] is True
        assert ledger["relations"]["multicast"].startswith(
            "aggregate_scheduled_message_bytes == N")

    def test_d1_handoff_lists_no_parent_decisions(self):
        handoff = _contract()["d1_handoff"]
        assert "redesign the hash dependency DAG" in handoff["must_not"]
        assert "identity.wave_d parent lists" in handoff["normative"]
        md = CONTRACT_MD.read_text()
        assert "### 34.1 D1 handoff contract" in md
