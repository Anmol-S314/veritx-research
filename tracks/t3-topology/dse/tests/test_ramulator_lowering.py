"""Contract tests for the MemoryArtifact → Ramulator trace lowering (15a).

Mapping vectors, conservation, transcription pin, manifest. No Ramulator
import, no execution (15b) — the lowering is pure.
"""
import re
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.core.memory import AddressMappingPolicy
from veritx_dse.workload.canonical import (
    Parallelism, WorkloadArtifact, build_compute_op)
from veritx_dse.workload.lowering import LoweringError
from veritx_dse.workload.memory_lowering import (
    MAPPING_ALGORITHM, MemorySystemDesign, RamulatorGeometry,
    addr_vec_for_tx, expand_access, hbm3_16gb_8hi_geometry,
    lower_to_ramulator_trace, resolve_memory,
)

DESIGN = MemorySystemDesign(hbm_devices=(0,))
POLICY = AddressMappingPolicy(name="contiguous_aligned_v1", version=1,
                              alignment_bytes=64, parameters={})


def _tiny_geo(**kw):
    d = {"dram_class": "TEST", "org_preset": "T", "timing_preset": "T",
         "controller": "C", "channels": 1, "pseudo_channels": 1,
         "sids": 1, "bankgroups": 2, "banks": 2, "rows": 64,
         "columns": 64, "transaction_bytes": 64}
    d.update(kw)
    return RamulatorGeometry(**d)


def _artifact():
    ops = (build_compute_op("op0", 100, input_bytes=1024,
                            weight_bytes=8192, output_bytes=512),)
    wl = WorkloadArtifact(workload_id="w", source_kind="test",
                          parallelism=Parallelism(), num_participants=1,
                          ops=ops)
    return resolve_memory(wl, DESIGN, policy=POLICY).artifact


# ── mapping vectors ─────────────────────────────────────────────────────

class TestAddrVec:
    def test_origin_and_column_walk(self):
        g = _tiny_geo()
        assert addr_vec_for_tx(0, g) == (0, 0, 0, 0, 0, 0, 0)
        assert addr_vec_for_tx(1, g) == (0, 0, 0, 0, 0, 0, 1)
        assert addr_vec_for_tx(63, g) == (0, 0, 0, 0, 0, 0, 63)

    def test_bank_then_row_order(self):
        g = _tiny_geo()
        # 64 columns fill, then bank (col fastest, bank next) ...
        assert addr_vec_for_tx(64, g) == (0, 0, 0, 0, 1, 0, 0)
        # ... 2 banks × 2 bankgroups, then row slowest
        assert addr_vec_for_tx(64 * 4, g) == (0, 0, 0, 0, 0, 1, 0)

    def test_capacity_refuses_never_wraps(self):
        g = _tiny_geo()
        with pytest.raises(LoweringError, match="exceeds backend capacity"):
            addr_vec_for_tx(64 * 64 * 4, g)

    def test_unknown_mapping_refused(self):
        with pytest.raises(LoweringError, match="unsupported"):
            lower_to_ramulator_trace(_artifact(), _tiny_geo(),
                                     out_path="/tmp/x.trace",
                                     mapping="random_v9")


# ── expansion + conservation ────────────────────────────────────────────

class TestLowering:
    def test_aligned_access_expands_exactly(self, tmp_path):
        art = _artifact()
        man = lower_to_ramulator_trace(art, _tiny_geo(),
                                       out_path=tmp_path / "t.trace")
        d = man.to_dict()
        # 1024+8192+512 = 9728B / 64 = 152 tx, zero padding (64-aligned)
        assert d["counts"] == {"semantic_accesses": 3, "transactions": 152,
                               "read_transactions": 144,
                               "write_transactions": 8}
        assert d["bytes"]["logical_read_bytes"] == 9216
        assert d["bytes"]["logical_write_bytes"] == 512
        assert d["bytes"]["front_padding_bytes"] == 0
        assert d["bytes"]["back_padding_bytes"] == 0
        assert d["coverage"] == {"lowered_accesses": 3,
                                 "total_accesses": 3}
        assert d["semantic_losses"] == [] and d["unsupported"] == []
        lines = (tmp_path / "t.trace").read_text().splitlines()
        assert len(lines) == 152
        assert lines[0].startswith("R ") and lines[-1].startswith("W ")

    def test_unaligned_tail_becomes_explicit_padding(self, tmp_path):
        art = _artifact()
        geo = _tiny_geo(transaction_bytes=100)
        man = lower_to_ramulator_trace(art, geo,
                                       out_path=tmp_path / "t.trace")
        d = man.to_dict()
        gen = d["bytes"]["generated_read_bytes"] + \
            d["bytes"]["generated_write_bytes"]
        log = d["bytes"]["logical_read_bytes"] + \
            d["bytes"]["logical_write_bytes"]
        pad = d["bytes"]["front_padding_bytes"] + \
            d["bytes"]["back_padding_bytes"]
        assert log == 9728 and gen == log + pad and pad > 0

    def test_stream_order_preserved(self, tmp_path):
        art = _artifact()
        lower_to_ramulator_trace(art, _tiny_geo(),
                                 out_path=tmp_path / "t.trace")
        kinds = [l.split()[0]
                 for l in (tmp_path / "t.trace").read_text().splitlines()]
        # op0: input+weight READs (144 lines) then output WRITEs (8)
        assert set(kinds[:144]) == {"R"} and set(kinds[144:]) == {"W"}

    def test_flat_byte_address_emitted_per_line(self, tmp_path):
        """req.addr correctness (2026-09-18): every line carries the flat
        tx byte address = tx_index * transaction_bytes — the controller's
        coalescing/forwarding equality key. Distinct transactions must
        have distinct flat addresses even when addr_vecs repeat."""
        art = _artifact()
        geo = _tiny_geo()  # tx = 64B
        man = lower_to_ramulator_trace(art, geo,
                                       out_path=tmp_path / "t.trace")
        lines = (tmp_path / "t.trace").read_text().splitlines()
        rows = [l.split() for l in lines]
        assert all(len(r) == 3 for r in rows), \
            "every line must be the 3-token extended form"
        flats = [int(r[1]) for r in rows]
        # flat addresses are exact tx multiples; reads strictly increasing
        assert all(f % 64 == 0 for f in flats)
        read_flats = flats[:144]
        assert read_flats == sorted(read_flats)
        assert read_flats[0] == 0
        # every flat address maps to exactly one addr_vec and vice versa:
        # distinct physical locations never share a coalescing key
        pairs = {(r[1], r[2]) for r in rows}
        assert len(pairs) == len(rows)

    def test_distinct_txs_same_addr_vec_get_distinct_keys(self, tmp_path):
        """The aliasing case that motivated the fix: two DIFFERENT
        transactions must never share a coalescing key."""
        art = _artifact()
        man = lower_to_ramulator_trace(art, _tiny_geo(),
                                       out_path=tmp_path / "t.trace")
        lines = (tmp_path / "t.trace").read_text().splitlines()
        seen = {}
        for l in lines:
            op, flat, vec = l.split()
            if op == "W":
                # within writes, distinct flats with identical vec = the
                # old bug (key aliasing across physical locations)
                seen.setdefault(vec, set()).add(flat)
        # every addr_vec maps to exactly one flat address and vice versa
        for vec, flats in seen.items():
            assert len(flats) == 1, f"aliased keys for {vec}: {flats}"

    def test_expand_access_returns_flat_addresses(self):
        art = _artifact()
        geo = _tiny_geo()
        acc = art.accesses[0]
        region = {r.region_id: r for r in art.regions}[acc.region_id]
        vecs, flats, fp, bp = expand_access(acc, region.base_address, geo)
        assert len(vecs) == len(flats) == 16  # 1024B / 64B
        assert flats == [i * 64 for i in range(16)]
        assert fp == 0 and bp == 0

    def test_trace_hash_matches_file(self, tmp_path):
        import hashlib
        art = _artifact()
        man = lower_to_ramulator_trace(art, _tiny_geo(),
                                       out_path=tmp_path / "t.trace")
        assert man.to_dict()["trace_sha256"] == \
            "sha256:" + hashlib.sha256(
                (tmp_path / "t.trace").read_bytes()).hexdigest()

    def test_manifest_links_artifact_and_stream(self, tmp_path):
        art = _artifact()
        man = lower_to_ramulator_trace(art, _tiny_geo(),
                                       out_path=tmp_path / "t.trace")
        d = man.to_dict()
        assert d["source_memory_artifact_hash"] == art.artifact_hash
        assert d["access_stream_hash"] == art.access_stream_hash
        assert d["mapping_algorithm"] == MAPPING_ALGORITHM
        assert d["backend"] == "ramulator"

    def test_oversize_artifact_refused(self, tmp_path):
        art = _artifact()  # 9728B demand vs a 2-tx toy backend
        geo = _tiny_geo(columns=1, bankgroups=1, banks=1, rows=1,
                        transaction_bytes=64)
        with pytest.raises(LoweringError, match="capacity"):
            lower_to_ramulator_trace(art, geo,
                                     out_path=tmp_path / "t.trace")

    def test_geometry_validation(self):
        with pytest.raises(LoweringError):
            _tiny_geo(rows=0)
        with pytest.raises(LoweringError):
            _tiny_geo(dram_class="")


# ── transcription pin (vendored tree, no import needed) ─────────────────

class TestTranscriptionPin:
    REPO = DSE.parent.parent.parent
    PRESET_FILE = REPO / "third_party" / "ramulator2" / "python" / \
        "ramulator" / "dram" / "hbm3.py"

    def test_vendored_preset_matches_transcription(self):
        text = self.PRESET_FILE.read_text()
        m = re.search(r'"HBM3_16Gb_8hi":\s*\{([^}]+)\}', text)
        assert m, "preset missing from vendored tree"
        body = m.group(1)
        for key, val in [("pseudochannel", "2"), ("sid", "2"),
                         ("bankgroup", "4"), ("bank", "4")]:
            assert re.search(rf'"{key}":\s*{val}\b', body), key
        assert '"row": 1 << 14' in body
        assert '"column": (1 << 5) << 3' in body  # 256

    def test_factory_carries_transcribed_values(self):
        g = hbm3_16gb_8hi_geometry()
        assert (g.pseudo_channels, g.sids, g.bankgroups, g.banks,
                g.rows, g.columns) == (2, 2, 4, 4, 16384, 256)
        assert g.transaction_bytes == 64
        assert g.capacity_bytes() == 1 * 2 * 2 * 4 * 4 * 16384 * 256 * 64

    def test_prefetch_basis_in_vendored_spec(self):
        spec = (self.REPO / "third_party" / "ramulator2" / "src" /
                "ramulator" / "dram" / "impl" / "HBM3.cpp").read_text()
        assert "internal_prefetch_size = 8" in spec
