"""Multi-channel memory: geometry profiles, the interleave, and the gate.

The finding these tests encode: adding channels is NOT a performance flag.
Two things are needed and both are pinned here —

  1. a multi-controller driver (a channel count the backend can execute);
  2. a CHANNEL-INTERLEAVED address order. The sequential order puts the
     channel almost last, so a streaming workload fills channel 0 for a
     whole 1 MB block before touching channel 1: the channels are then used
     SEQUENTIALLY and extra channels buy nothing. Measured on an identical
     131,072-transaction trace: 8 blocked channels 1,026,219 cycles vs 8
     interleaved 128,539 vs 1 channel 1,031,343 — the 8x is the interleave.
"""
import sys
import tempfile
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.backend import ramulator_adapter as A
from veritx_dse.simulation import ramulator as sim
from veritx_dse.workload.memory_lowering import (
    ADDR_VEC_ORDERS,
    CHANNEL_INTERLEAVED,
    MAPPING_ALGORITHM,
    RamulatorGeometry,
    addr_vec_for_tx,
    hbm3_16gb_8hi_geometry,
)

ONE = "CERTIFIED_RAMULATOR_HBM3_V1"
EIGHT = "CERTIFIED_RAMULATOR_HBM3_8CH_V1"

def test_both_profiles_are_registered_with_distinct_envelopes():
    assert set(A.MEMORY_GEOMETRY_PROFILES) == {ONE, EIGHT}
    assert A.certified_geometry(ONE).channels == 1
    assert A.certified_geometry(EIGHT).channels == 8
    assert A.certified_geometry(EIGHT).capacity_bytes() == \
        8 * A.certified_geometry(ONE).capacity_bytes()

def test_the_limitation_text_follows_the_profile_not_a_constant():
    assert "single-channel" in A.memory_limitations(ONE)[2]
    assert "8 independent channels" in A.memory_limitations(EIGHT)[2]
    assert A.RAMULATOR_LIMITATIONS == A.memory_limitations(A.DEFAULT_MEMORY_PROFILE)

def test_an_unknown_profile_refuses_rather_than_defaulting():
    with pytest.raises(A.RamulatorSemanticRefusal, match="unknown memory geometry"):
        A.memory_geometry_profile("CERTIFIED_RAMULATOR_MADE_UP")

def test_the_evidence_identity_is_per_profile():
    """A different geometry must not share a config hash with another."""
    from veritx_dse.workload.memory_lowering import backend_config_payload
    g1, g8 = A.certified_geometry(ONE), A.certified_geometry(EIGHT)
    h1 = backend_config_payload(g1, MAPPING_ALGORITHM)
    h8 = backend_config_payload(g8, CHANNEL_INTERLEAVED)
    assert h1 != h8

def _manifest(channels, mapping):
    from veritx_dse.workload.memory_lowering import (
        MemoryLoweringManifest, backend_config_payload)
    g = hbm3_16gb_8hi_geometry(num_channels=channels)
    import hashlib
    return MemoryLoweringManifest(
        schema_version=1, source_memory_artifact_hash="x",
        access_stream_hash="y", backend="ramulator", lowerer="l",
        mapping_algorithm=mapping,
        backend_config_hash="sha256:" + hashlib.sha256(
            backend_config_payload(g, mapping)).hexdigest(),
        geometry=g.to_dict(), transaction_bytes=64,
        counts={}, bytes={}, coverage={}, transformations=[],
        semantic_losses=[], unsupported=[], trace_sha256="z")

def test_audited_channel_counts_execute_and_others_refuse():
    assert sim._check_supported(_manifest(1, MAPPING_ALGORITHM)) is None
    assert sim._check_supported(_manifest(8, CHANNEL_INTERLEAVED)) is None
    reason = sim._check_supported(_manifest(2, CHANNEL_INTERLEAVED))
    assert reason is not None and "audited" in reason

def test_an_unaudited_mapping_refuses():
    reason = sim._check_supported(_manifest(8, "something_else_v9"))
    assert reason is not None and "unsupported" in reason
    assert sim.SUPPORTED_MAPPINGS == {
        MAPPING_ALGORITHM, CHANNEL_INTERLEAVED}

def test_channel_is_high_order_in_the_sequential_mapping():
    """The bug, stated as a test: 16k consecutive tx all on channel 0."""
    g = hbm3_16gb_8hi_geometry(num_channels=8)
    assert {addr_vec_for_tx(i, g)[0] for i in range(4)} == {0}
    assert addr_vec_for_tx(16384, g)[0] == 1
    assert ADDR_VEC_ORDERS[MAPPING_ALGORITHM][-2] == "channel"

def test_channel_is_low_order_in_the_interleaved_mapping():
    g = hbm3_16gb_8hi_geometry(num_channels=8)
    assert [addr_vec_for_tx(i, g, mapping=CHANNEL_INTERLEAVED)[0]
            for i in range(8)] == list(range(8))
    assert ADDR_VEC_ORDERS[CHANNEL_INTERLEAVED][0] == "channel"

def test_the_interleave_still_covers_the_whole_address_space():
    """Interleaving changes the ORDER, never the capacity or the set."""
    g = hbm3_16gb_8hi_geometry(num_channels=8)
    seen = {addr_vec_for_tx(i, g, mapping=CHANNEL_INTERLEAVED)
            for i in range(20000)}
    assert len(seen) == 20000
    assert {v[0] for v in seen} == set(range(8))

def test_an_unknown_mapping_refuses():
    from veritx_dse.workload.lowering import LoweringError
    with pytest.raises(LoweringError, match="unsupported"):
        addr_vec_for_tx(0, hbm3_16gb_8hi_geometry(), mapping="nope")

def test_one_channel_returns_its_dict_unchanged():
    d = {"cycles": 10, "row_hits": 3}
    assert sim.merge_channel_stats(d) is d
    assert sim.merge_channel_stats([d]) == d

def test_many_channels_sum_counters_and_max_the_drain():
    merged = sim.merge_channel_stats([
        {"cycles": 100, "row_hits": 5, "row_conflicts": 2, "num_read_reqs": 10,
         "avg_read_latency": 10.0},
        {"cycles": 250, "row_hits": 7, "row_conflicts": 1, "num_read_reqs": 30,
         "avg_read_latency": 20.0},
    ])
    assert merged["cycles"] == 250
    assert merged["row_hits"] == 12
    assert merged["row_conflicts"] == 3
    assert merged["avg_read_latency"] == pytest.approx(17.5)

def test_a_stat_absent_from_every_channel_stays_absent():
    merged = sim.merge_channel_stats([{"cycles": 1}, {"cycles": 2}])
    assert merged == {"cycles": 2}

def test_empty_or_malformed_stats_merge_to_nothing():
    assert sim.merge_channel_stats([]) == {}
    assert sim.merge_channel_stats("nope") == {}
    assert sim.merge_channel_stats([{"cycles": 1}, "junk"]) == {"cycles": 1}
