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
        """D0-C008: declared payload default, no message consumer."""
        from veritx_dse.model.compile_model import CollectiveOp
        op = CollectiveOp.__dataclass_fields__
        assert "bytes_per_element" in op
        hits = []
        for path in (DSE / "veritx_dse").rglob("*.py"):
            if "__pycache__" in str(path):
                continue
            text = path.read_text()
            if "bytes_per_element" in text and \
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
