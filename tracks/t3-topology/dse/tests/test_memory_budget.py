"""Memory leg cost, budget and the bandwidth-model bound (scaling).

The cycle-accurate leg is linear in transactions and single-threaded, so
the only honest options at scale are: bound it, or answer with a
differently-labelled model. These tests pin both, plus the estimate's
agreement with the lowering it predicts.
"""
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
    DEFAULT_MAX_TRANSACTIONS,
    MemorySystemDesign, RamulatorGeometry,
    bandwidth_model_stream_ns, estimate_trace_cost,
    hbm3_16gb_8hi_geometry, lower_to_ramulator_trace,
    peak_bandwidth_bytes_per_s, resolve_memory,
)

DESIGN = MemorySystemDesign(hbm_devices=(0,))
POLICY = AddressMappingPolicy(name="contiguous_aligned_v1", version=1,
                              alignment_bytes=64, parameters={})

def _artifact(weight_bytes: int = 8192, input_bytes: int = 1024):
    ops = (build_compute_op("op0", 100, input_bytes=input_bytes,
                            weight_bytes=weight_bytes, output_bytes=512),)
    wl = WorkloadArtifact(workload_id="w", source_kind="test",
                          parallelism=Parallelism(), num_participants=1,
                          ops=ops)
    return resolve_memory(wl, DESIGN, policy=POLICY).artifact

def _geo(**kw):
    d = {"dram_class": "HBM3", "org_preset": "HBM3_16Gb_8hi",
         "timing_preset": "HBM3_6400Mbps", "controller": "HBM34",
         "channels": 1, "pseudo_channels": 2, "sids": 2, "bankgroups": 4,
         "banks": 4, "rows": 16384, "columns": 256,
         "transaction_bytes": 64}
    d.update(kw)
    return RamulatorGeometry(**d)

def test_estimate_matches_the_manifest_it_predicts(tmp_path):
    art = _artifact()
    geo = hbm3_16gb_8hi_geometry()
    cost = estimate_trace_cost(art, geo)
    manifest = lower_to_ramulator_trace(art, geo, out_path=tmp_path / "t.trace")
    counts = manifest.to_dict()["counts"]
    assert cost.transactions == counts["transactions"]
    assert cost.read_transactions == counts["read_transactions"]
    assert cost.write_transactions == counts["write_transactions"]

def test_estimate_is_cheap_and_does_not_write_a_trace(tmp_path):
    art = _artifact(weight_bytes=64 * 1000)
    geo = hbm3_16gb_8hi_geometry()
    cost = estimate_trace_cost(art, geo)
    assert cost.transactions >= 1000
    assert list(tmp_path.iterdir()) == []
    assert cost.generated_bytes == cost.transactions * 64

def test_capacity_fit_is_reported_not_assumed():
    art = _artifact()
    big = _geo(rows=1, columns=1, channels=1, pseudo_channels=1, sids=1,
               bankgroups=1, banks=1)
    cost = estimate_trace_cost(art, big)
    assert not cost.fits_capacity
    assert estimate_trace_cost(art, hbm3_16gb_8hi_geometry()).fits_capacity

def test_unknown_region_refuses():
    art = _artifact()
    geo = hbm3_16gb_8hi_geometry()
    broken = art.__class__(**{**art.__dict__, "accesses": art.accesses})
    object.__setattr__(broken, "accesses", ())
    cost = estimate_trace_cost(broken, geo)
    assert cost.transactions == 0

def test_peak_bandwidth_is_derived_from_the_audited_preset():
    assert peak_bandwidth_bytes_per_s(_geo()) == 6400 * 10**6 * 8
    assert peak_bandwidth_bytes_per_s(_geo(channels=8)) == 6400 * 10**6 * 8 * 8

def test_an_unaudited_preset_refuses_to_guess_a_rate():
    with pytest.raises(LoweringError, match="no audited peak bandwidth"):
        peak_bandwidth_bytes_per_s(_geo(timing_preset="MADE_UP_9000"))

def test_the_bandwidth_bound_is_a_lower_bound_label_ready():
    art = _artifact(weight_bytes=64 * 1_000_000)
    geo = _geo()
    cost = estimate_trace_cost(art, geo)
    ns = bandwidth_model_stream_ns(cost, geo)
    bw = peak_bandwidth_bytes_per_s(geo)
    assert ns == round(cost.generated_bytes / bw * 1e9)
    assert 1_000_000 < ns < 2_000_000

def test_an_8b_model_passes_one_channel_on_the_bandwidth_model():
    """The honest headline: one HBM3 channel cannot feed an 8B model."""
    geo = _geo(channels=1)
    from veritx_dse.workload.memory_lowering import MemoryTraceCost
    seven_gb = MemoryTraceCost(
        transactions=109_000_000, read_transactions=109_000_000,
        write_transactions=0, generated_bytes=109_000_000 * 64,
        capacity_bytes=geo.capacity_bytes())
    ns = bandwidth_model_stream_ns(seven_gb, geo)
    assert 100_000_000 < ns < 200_000_000
    assert seven_gb.transactions > DEFAULT_MAX_TRANSACTIONS
