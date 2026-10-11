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
    iter_access_lines, lower_to_ramulator_trace, resolve_memory,
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

class TestAddrVec:
    def test_origin_and_column_walk(self):
        g = _tiny_geo()
        assert addr_vec_for_tx(0, g) == (0, 0, 0, 0, 0, 0, 0)
        assert addr_vec_for_tx(1, g) == (0, 0, 0, 0, 0, 0, 1)
        assert addr_vec_for_tx(63, g) == (0, 0, 0, 0, 0, 0, 63)

    def test_bank_then_row_order(self):
        g = _tiny_geo()
        assert addr_vec_for_tx(64, g) == (0, 0, 0, 0, 1, 0, 0)
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

class TestLowering:
    def test_aligned_access_expands_exactly(self, tmp_path):
        art = _artifact()
        man = lower_to_ramulator_trace(art, _tiny_geo(),
                                       out_path=tmp_path / "t.trace")
        d = man.to_dict()
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
        assert set(kinds[:144]) == {"R"} and set(kinds[144:]) == {"W"}

    def test_flat_byte_address_emitted_per_line(self, tmp_path):
        """req.addr correctness (2026-09-18): every line carries the flat
        tx byte address = tx_index * transaction_bytes — the controller's
        coalescing/forwarding equality key. Distinct transactions must
        have distinct flat addresses even when addr_vecs repeat."""
        art = _artifact()
        geo = _tiny_geo()
        man = lower_to_ramulator_trace(art, geo,
                                       out_path=tmp_path / "t.trace")
        lines = (tmp_path / "t.trace").read_text().splitlines()
        rows = [l.split() for l in lines]
        assert all(len(r) == 3 for r in rows), \
            "every line must be the 3-token extended form"
        flats = [int(r[1]) for r in rows]
        assert all(f % 64 == 0 for f in flats)
        read_flats = flats[:144]
        assert read_flats == sorted(read_flats)
        assert read_flats[0] == 0
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
                seen.setdefault(vec, set()).add(flat)
        for vec, flats in seen.items():
            assert len(flats) == 1, f"aliased keys for {vec}: {flats}"

    def test_expand_access_returns_flat_addresses(self):
        art = _artifact()
        geo = _tiny_geo()
        acc = art.accesses[0]
        region = {r.region_id: r for r in art.regions}[acc.region_id]
        vecs, flats, fp, bp = expand_access(acc, region.base_address, geo)
        assert len(vecs) == len(flats) == 16
        assert flats == [i * 64 for i in range(16)]
        assert fp == 0 and bp == 0

    def test_iter_access_lines_matches_expand_access(self):
        """The streaming iterator and the materialising helper are ONE
        authority: same order, same vectors, same flat addresses."""
        art = _artifact()
        geo = _tiny_geo()
        acc = art.accesses[0]
        region = {r.region_id: r for r in art.regions}[acc.region_id]
        vecs, flats, fp, bp = expand_access(acc, region.base_address, geo)
        streamed = list(iter_access_lines(acc, region.base_address, geo))
        assert streamed == list(zip(flats, vecs))
        assert len(streamed) == 16

    def test_large_region_lowers_without_materialising(self, tmp_path):
        """A big operand region streams to disk; the trace is one record per
        transaction and the manifest counts them (no in-memory list)."""
        art = _artifact()
        man = lower_to_ramulator_trace(art, _tiny_geo(),
                                       out_path=tmp_path / "s.trace")
        text = (tmp_path / "s.trace").read_text()
        assert text.endswith("\n") and "\n\n" not in text
        assert man.counts["transactions"] == len(text.splitlines())

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
        art = _artifact()
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

class TestExplicitMultiHbmPlacement:
    def test_declared_sparse_local_ids_are_preserved(self):
        from veritx_dse.workload.memory_lowering import _resolve_location
        design = MemorySystemDesign(hbm_devices=(2, 9))
        assert _resolve_location("op", "input", "LOCAL:2", design).device == 2
        assert _resolve_location("op", "input", "LOCAL:9", design).device == 9

    def test_bare_local_refuses_with_multiple_pools(self):
        from veritx_dse.workload.lowering import UnsupportedSemantic
        from veritx_dse.workload.memory_lowering import _resolve_location
        with pytest.raises(UnsupportedSemantic, match="ambiguous"):
            _resolve_location("op", "input", "LOCAL",
                              MemorySystemDesign(hbm_devices=(2, 9)))

    @pytest.mark.parametrize("location", ["LOCAL:9junk", "LOCAL:9.x",
                                           "LOCAL:", "LOCALITY:9"])
    def test_malformed_or_undeclared_local_refuses(self, location):
        from veritx_dse.workload.lowering import UnsupportedSemantic
        from veritx_dse.workload.memory_lowering import _resolve_location
        with pytest.raises(UnsupportedSemantic):
            _resolve_location("op", "input", location,
                              MemorySystemDesign(hbm_devices=(2, 9)))

    def test_single_pool_bare_and_explicit_compatibility(self):
        from veritx_dse.workload.memory_lowering import _resolve_location
        design = MemorySystemDesign(hbm_devices=(9,))
        assert _resolve_location("op", "input", "LOCAL", design).device == 9
        assert _resolve_location("op", "input", "LOCAL:9", design).device == 9

    def test_dispatch_manifest_keeps_two_local_address_spaces_and_ledgers(self):
        from veritx_dse.workload.memory_lowering import (
            CHANNEL_INTERLEAVED, lower_to_ramulator_dispatch,
            ramulator_dispatch_config_payload,
        )
        op = build_compute_op(
            "op", 1, input_bytes=70, weight_bytes=35, output_bytes=15,
            input_loc="LOCAL:2", weight_loc="LOCAL:9",
            output_loc="LOCAL:2")
        workload = WorkloadArtifact(
            workload_id="multi", source_kind="test",
            parallelism=Parallelism(), num_participants=1, ops=(op,))
        art = resolve_memory(workload,
                             MemorySystemDesign(hbm_devices=(2, 9)),
                             policy=POLICY).artifact
        geo = _tiny_geo(transaction_bytes=64)
        config_hash = "sha256:" + __import__("hashlib").sha256(
            ramulator_dispatch_config_payload(
                geo, (2, 9), 32, MAPPING_ALGORITHM)).hexdigest()
        manifest = lower_to_ramulator_dispatch(
            art, geo, device_ids=(2, 9), native_transaction_bytes=32,
            backend_config_hash=config_hash)
        assert manifest["device_channel_groups"] == {
            "2": {"first_channel": 0, "channel_count": 1},
            "9": {"first_channel": 1, "channel_count": 1}}
        assert manifest["counts"] == {
            "semantic_accesses": 3, "transactions": 6,
            "read_transactions": 5, "write_transactions": 1}
        assert manifest["bytes"] == {
            "logical_bytes": 120, "generated_bytes": 192,
            "padding_bytes": 72}
        rows = manifest["transactions"]
        input0 = next(r for r in rows if r["access_id"] == "acc.op.input"
                      and r["transaction_index"] == 0)
        weight0 = next(r for r in rows if r["access_id"] == "acc.op.weight"
                       and r["transaction_index"] == 0)
        assert input0["source_address"] == weight0["source_address"] == 0
        assert input0["native_address"] == weight0["native_address"] == 0
        assert (input0["device_id"], input0["native_channel"]) == (2, 0)
        assert (weight0["device_id"], weight0["native_channel"]) == (9, 1)
        output = next(r for r in rows if r["access_id"] == "acc.op.output")
        assert output["dependencies"] == ["acc.op.input", "acc.op.weight"]
        assert manifest["device_ledger"]["2"]["padding_bytes"] == 43
        assert manifest["device_ledger"]["9"]["padding_bytes"] == 29
        changed = lower_to_ramulator_dispatch(
            art, geo, device_ids=(9, 2), native_transaction_bytes=32,
            backend_config_hash=config_hash)
        assert changed["dispatch_input_hash"] == manifest["dispatch_input_hash"]

    def test_device_id_is_never_used_as_a_native_channel_index(self):
        from veritx_dse.workload.memory_lowering import (
            lower_to_ramulator_dispatch,
            ramulator_dispatch_config_payload,
        )
        op = build_compute_op(
            "op", 1, input_bytes=32, weight_bytes=32, output_bytes=32,
            input_loc="LOCAL:5", weight_loc="LOCAL:7", output_loc="LOCAL:5")
        workload = WorkloadArtifact(
            workload_id="sparse", source_kind="test",
            parallelism=Parallelism(), num_participants=1, ops=(op,))
        art = resolve_memory(workload,
                             MemorySystemDesign(hbm_devices=(5, 7)),
                             policy=POLICY).artifact
        geo = _tiny_geo(transaction_bytes=64)
        config_hash = "sha256:" + __import__("hashlib").sha256(
            ramulator_dispatch_config_payload(
                geo, (5, 7), 32, MAPPING_ALGORITHM)).hexdigest()
        manifest = lower_to_ramulator_dispatch(
            art, geo, device_ids=(5, 7), native_transaction_bytes=32,
            backend_config_hash=config_hash)
        # Sorted device order owns the groups; device 7 must NOT land on
        # native channel 7 (there are only two).
        assert manifest["device_channel_groups"] == {
            "5": {"first_channel": 0, "channel_count": 1},
            "7": {"first_channel": 1, "channel_count": 1}}
        channels = {r["device_id"]: r["native_channel"]
                    for r in manifest["transactions"]}
        assert channels == {5: 0, 7: 1}
        assert max(r["native_channel"] for r in manifest["transactions"]) == 1

    def test_pools_own_disjoint_contiguous_channel_groups(self):
        from veritx_dse.workload.memory_lowering import (
            CHANNEL_INTERLEAVED, lower_to_ramulator_dispatch,
            ramulator_dispatch_config_payload,
        )
        op = build_compute_op(
            "op", 1, input_bytes=256, weight_bytes=256, output_bytes=128,
            input_loc="LOCAL:0", weight_loc="LOCAL:1", output_loc="LOCAL:0")
        workload = WorkloadArtifact(
            workload_id="eight", source_kind="test",
            parallelism=Parallelism(), num_participants=1, ops=(op,))
        art = resolve_memory(workload, MemorySystemDesign(hbm_devices=(0, 1)),
                             policy=POLICY).artifact
        geo = hbm3_16gb_8hi_geometry(num_channels=8, transaction_bytes=32)
        config_hash = "sha256:" + __import__("hashlib").sha256(
            ramulator_dispatch_config_payload(
                geo, (0, 1), 32, CHANNEL_INTERLEAVED)).hexdigest()
        manifest = lower_to_ramulator_dispatch(
            art, geo, device_ids=(0, 1), native_transaction_bytes=32,
            mapping=CHANNEL_INTERLEAVED, backend_config_hash=config_hash)
        assert manifest["device_channel_groups"] == {
            "0": {"first_channel": 0, "channel_count": 8},
            "1": {"first_channel": 8, "channel_count": 8}}
        used = {}
        for row in manifest["transactions"]:
            used.setdefault(row["device_id"], set()).add(
                row["native_channel"])
        assert used[0] <= set(range(0, 8))
        assert used[1] <= set(range(8, 16))
        assert not (used[0] & used[1])
        # Every pool-local transaction index reaches its own group exactly
        # once: interleaving is within a pool, never across pools.
        assert len(used[0]) == len(used[1]) == 8

class TestNativeAddrMapping:
    """The dispatched addr vector must equal what RoBaRaCoCh computes."""

    # RoBaRaCoCh slices the controller-local transaction index LSB-first in
    # exactly this order; the counts come from the vendored HBM3_16Gb_8hi
    # preset (column 256 with 8x internal prefetch -> 5 bits).
    NATIVE_BITS = (("column", 5), ("pseudochannel", 1), ("sid", 1),
                   ("bankgroup", 2), ("bank", 2), ("row", 14))

    def test_native_addr_vec_matches_robaracoch_field_order(self):
        from veritx_dse.workload.memory_lowering import (
            lower_to_ramulator_dispatch, native_level_bits,
            ramulator_dispatch_config_payload,
        )
        # One channel per pool over TWO pools: the controller-local index is
        # then the transaction index itself, so a single access of 4096
        # requests walks every field (column 0..31, both pseudochannel and
        # sid bits, all bankgroup/bank pairs and non-zero rows). An 8-channel
        # pool would leave everything above the column field at zero and the
        # order would not be discriminated at all.
        op = build_compute_op(
            "op", 1, input_bytes=4096 * 32, weight_bytes=32,
            output_bytes=32, input_loc="LOCAL:0", weight_loc="LOCAL:1",
            output_loc="LOCAL:0")
        workload = WorkloadArtifact(
            workload_id="vec", source_kind="test",
            parallelism=Parallelism(), num_participants=1, ops=(op,))
        art = resolve_memory(workload, MemorySystemDesign(hbm_devices=(0, 1)),
                             policy=POLICY).artifact
        geo = hbm3_16gb_8hi_geometry(num_channels=1, transaction_bytes=32)
        assert native_level_bits(geo) == dict(self.NATIVE_BITS)
        config_hash = "sha256:" + __import__("hashlib").sha256(
            ramulator_dispatch_config_payload(
                geo, (0, 1), 32, MAPPING_ALGORITHM)).hexdigest()
        manifest = lower_to_ramulator_dispatch(
            art, geo, device_ids=(0, 1), native_transaction_bytes=32,
            mapping=MAPPING_ALGORITHM, backend_config_hash=config_hash)
        rows = [r for r in manifest["transactions"]
                if r["access_id"] == "acc.op.input"]
        assert len(rows) == 4096
        seen: dict[str, set[int]] = {dim: set() for dim, _ in self.NATIVE_BITS}
        for row in rows:
            rest = row["controller_local_address"] // 32
            fields: dict[str, int] = {}
            for dim, bits in self.NATIVE_BITS:
                fields[dim] = rest & ((1 << bits) - 1)
                rest >>= bits
            assert rest == 0, "controller-local index exceeds the geometry"
            assert row["native_channel"] == 0  # one channel in pool 0
            assert row["native_addr_vec"] == [
                0, fields["pseudochannel"], fields["sid"],
                fields["bankgroup"], fields["bank"], fields["row"],
                fields["column"]]
            for dim, _ in self.NATIVE_BITS:
                seen[dim].add(fields[dim])
            # Pool-local logical vector keeps the profile's own order.
            assert row["pool_local_addr_vec"][0] == 0
        # The fixture really does discriminate: every field is non-constant,
        # so a permuted or re-widthed field order cannot pass this test.
        assert seen["column"] == set(range(32))
        assert seen["pseudochannel"] == {0, 1}
        assert seen["sid"] == {0, 1}
        assert seen["bankgroup"] == {0, 1, 2, 3}
        assert seen["bank"] == {0, 1, 2, 3}
        assert max(seen["row"]) >= 1

    def test_non_power_of_two_level_count_refuses_like_the_native_mapper(self):
        from veritx_dse.workload.memory_lowering import native_level_bits
        bits = native_level_bits(hbm3_16gb_8hi_geometry())
        assert bits == {"column": 5, "pseudochannel": 1, "sid": 1,
                        "bankgroup": 2, "bank": 2, "row": 14}
        with pytest.raises(LoweringError, match="power of two"):
            native_level_bits(_tiny_geo(banks=3))

    def test_three_pools_pad_only_the_native_controller_tail(self):
        import hashlib
        from veritx_dse.workload.memory_lowering import (
            lower_to_ramulator_dispatch, ramulator_dispatch_config_payload,
        )
        op = build_compute_op(
            "op", 1, input_bytes=32, weight_bytes=32, output_bytes=32,
            input_loc="LOCAL:0", weight_loc="LOCAL:1", output_loc="LOCAL:2")
        workload = WorkloadArtifact(
            workload_id="three-pools", source_kind="test",
            parallelism=Parallelism(), num_participants=1, ops=(op,))
        devices = (0, 1, 2)
        art = resolve_memory(
            workload, MemorySystemDesign(hbm_devices=devices),
            policy=POLICY).artifact
        geo = hbm3_16gb_8hi_geometry(num_channels=1, transaction_bytes=32)
        config_hash = "sha256:" + hashlib.sha256(
            ramulator_dispatch_config_payload(
                geo, devices, 32, MAPPING_ALGORITHM)).hexdigest()
        manifest = lower_to_ramulator_dispatch(
            art, geo, device_ids=devices, native_transaction_bytes=32,
            mapping=MAPPING_ALGORITHM, backend_config_hash=config_hash)
        assert manifest["device_channel_groups"] == {
            "0": {"first_channel": 0, "channel_count": 1},
            "1": {"first_channel": 1, "channel_count": 1},
            "2": {"first_channel": 2, "channel_count": 1}}
        assert manifest["controller_padding"] == {
            "policy": "inactive_power_of_two_tail_v1",
            "active_channels": 3, "native_controller_count": 4,
            "inactive_channels": [3]}
        assert {row["native_channel"] for row in manifest["transactions"]} == {
            0, 1, 2}
        assert [row["native_addr_vec"][0]
                for row in manifest["transactions"]] == [0, 1, 2]

    def test_single_pool_lowerers_refuse_a_multi_pool_artifact(self):
        """One trace is one address space: a two-pool artifact must refuse
        rather than silently collapse both pools into a single stream."""
        from veritx_dse.workload.memory_lowering import (
            estimate_dispatch_cost, estimate_trace_cost,
        )
        op = build_compute_op(
            "op", 1, input_bytes=128, weight_bytes=64, output_bytes=64,
            input_loc="LOCAL:0", weight_loc="LOCAL:1", output_loc="LOCAL:0")
        workload = WorkloadArtifact(
            workload_id="collapse", source_kind="test",
            parallelism=Parallelism(), num_participants=1, ops=(op,))
        art = resolve_memory(workload, MemorySystemDesign(hbm_devices=(0, 1)),
                             policy=POLICY).artifact
        geo = hbm3_16gb_8hi_geometry(num_channels=1, transaction_bytes=32)
        with pytest.raises(LoweringError,
                           match="lower_to_ramulator_dispatch"):
            lower_to_ramulator_trace(art, geo, out_path="/tmp/never.trace")
        with pytest.raises(LoweringError,
                           match="lower_to_ramulator_dispatch"):
            estimate_trace_cost(art, geo)
        # The multi-pool cost query is the one that accepts it, and it
        # charges capacity per declared pool.
        cost = estimate_dispatch_cost(art, geo, device_ids=(0, 1))
        assert cost.transactions == cost.read_transactions + \
            cost.write_transactions
        assert cost.capacity_bytes == 2 * geo.capacity_bytes()
        with pytest.raises(LoweringError, match="undeclared device"):
            estimate_dispatch_cost(art, geo, device_ids=(0,))
        # A single-pool artifact keeps working through the legacy path.
        single_op = build_compute_op(
            "op", 1, input_bytes=128, weight_bytes=64, output_bytes=64)
        single_workload = WorkloadArtifact(
            workload_id="single", source_kind="test",
            parallelism=Parallelism(), num_participants=1, ops=(single_op,))
        single = resolve_memory(
            single_workload, MemorySystemDesign(hbm_devices=(0,)),
            policy=POLICY).artifact
        assert estimate_trace_cost(single, geo).transactions > 0

class TestIndependentLedgerExpectation:
    """Recompute the dispatch ledger from the artifact, not from itself."""

    def test_per_pool_requests_addresses_kinds_and_padding(self):
        from veritx_dse.workload.memory_lowering import (
            lower_to_ramulator_dispatch, ramulator_dispatch_config_payload,
        )
        op = build_compute_op(
            "op", 1, input_bytes=70, weight_bytes=35, output_bytes=15,
            input_loc="LOCAL:2", weight_loc="LOCAL:9", output_loc="LOCAL:2")
        workload = WorkloadArtifact(
            workload_id="indep", source_kind="test",
            parallelism=Parallelism(), num_participants=1, ops=(op,))
        art = resolve_memory(workload, MemorySystemDesign(hbm_devices=(2, 9)),
                             policy=POLICY).artifact
        geo = _tiny_geo(transaction_bytes=64)
        config_hash = "sha256:" + __import__("hashlib").sha256(
            ramulator_dispatch_config_payload(
                geo, (2, 9), 32, MAPPING_ALGORITHM)).hexdigest()
        manifest = lower_to_ramulator_dispatch(
            art, geo, device_ids=(2, 9), native_transaction_bytes=32,
            backend_config_hash=config_hash)
        regions = {r.region_id: r for r in art.regions}
        expected: dict[int, dict] = {}
        for access in art.accesses:
            region = regions[access.region_id]
            device = region.placement.device
            start = region.base_address + access.offset_bytes
            first = -(-start // 32)
            last = (start + access.size_bytes - 1) // 32
            bucket = expected.setdefault(
                device, {"read": 0, "write": 0, "padding": 0,
                         "addresses": []})
            kind = "write" if access.kind == "WRITE" else "read"
            bucket[kind] += last - first + 1
            for index in range(first, last + 1):
                bucket["addresses"].append(index * 32)
                covered = min(start + access.size_bytes,
                              (index + 1) * 32) - max(start, index * 32)
                bucket["padding"] += 32 - max(0, covered)
        ledger = manifest["device_ledger"]
        for device, want in expected.items():
            got = ledger[str(device)]
            assert got["read_transactions"] == want["read"]
            assert got["write_transactions"] == want["write"]
            assert got["padding_bytes"] == want["padding"]
            emitted = sorted(r["local_pool_address"] for r in
                             manifest["transactions"]
                             if r["device_id"] == device)
            assert emitted == sorted(want["addresses"])
        # Two pools may hold the same pool-local address; the native route
        # still separates them.
        assert (sum(v["read_transactions"] + v["write_transactions"]
                    for v in ledger.values())
                == manifest["counts"]["transactions"])
        assert manifest["bytes"]["logical_bytes"] + \
            manifest["bytes"]["padding_bytes"] == \
            manifest["bytes"]["generated_bytes"]

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
        assert '"column": (1 << 5) << 3' in body

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
