"""Latency metric authority — two populations, pinned at the producer.

PHASE 3.2-seal. The parser reclamation restored `honest_latency`, but the
METRIC SCHEMA still filed a qtime mean and request-time percentiles in one
`sim.latency.*` family. BookSim's own source shows they are different
populations:

    third_party/booksim2/src/trafficmanager.cpp

      _plat_stats[c]->AddSample( f->atime - head->ctime );        <- qtime
      _all_latencies[c].push_back( f->atime - <trace request ts> ) <- request
      "Packet latency average = " << _plat_stats[c]->Average()     <- qtime
      sorted_lat(_all_latencies[c]) -> p50/p95/p99/honest_avg      <- request

These tests pin the PRODUCER contract in source (not synthetic parser input)
and the SCHEMA split that follows from it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).parent.parent
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

TM = REPO / "third_party/booksim2/src/trafficmanager.cpp"

@pytest.fixture(scope="module")
def tm_source() -> str:
    assert TM.exists(), f"fork source missing: {TM}"
    return TM.read_text()

def test_stock_mean_comes_from_plat_stats(tm_source):
    """The stock 'Packet latency average' is the _plat_stats mean."""
    assert re.search(
        r'Packet latency average\s*=\s*"\s*<<\s*_plat_stats\[c\]->Average\(\)',
        tm_source), "stock mean is not sourced from _plat_stats"

def test_plat_stats_uses_qtime_ctime(tm_source):
    """_plat_stats is sampled with atime - ctime (the qtime-era semantics)."""
    assert re.search(
        r"_plat_stats\[f->cl\]->AddSample\(\s*f->atime\s*-\s*head->ctime\s*\)",
        tm_source), "_plat_stats no longer samples atime - ctime"

def test_request_vector_is_populated_from_the_original_trace_timestamp(tm_source):
    """_all_latencies is the REQUEST-time vector: atime minus the original
    trace request timestamp (the fork keeps that timestamp in a map)."""
    assert "_all_latencies" in tm_source
    assert re.search(
        r"_all_latencies\[f->cl\]\.push_back\(\s*\(double\)\s*\(\s*f->atime\s*-\s*_rtit->second",
        tm_source), "_all_latencies is not populated from atime - request timestamp"

def test_percentiles_and_honest_mean_share_the_request_vector(tm_source):
    """p50/p95/p99 AND honest_avg are all computed from sorted_lat, which is
    a copy of _all_latencies. One vector, one population."""
    assert re.search(r"std::vector<double>\s+sorted_lat\(\s*_all_latencies\[c\]\s*\)",
                     tm_source), "percentiles are not sorted from _all_latencies"
    block = tm_source.split("std::vector<double> sorted_lat")[1][:900]
    for emitted in (r"\tp50 = ", r"\tp95 = ", r"\tp99 = ", r"honest_avg = "):
        assert emitted in block, f"{emitted} not emitted from the request vector"

def test_the_two_populations_are_emitted_in_the_same_block(tm_source):
    """The confusion risk is real: both appear together, so a reader can
    mistake them for one distribution. The stock mean is emitted first, then
    the request-time percentiles, in the same per-class stats block."""
    i_plat = tm_source.index("Packet latency average = ")
    i_sorted = tm_source.index("std::vector<double> sorted_lat(")
    i_honest = tm_source.index("honest_avg = ")
    assert i_plat < i_sorted < i_honest
    window = tm_source[i_plat:i_honest]
    for emitted in (r"\tp50 = ", r"\tp95 = ", r"\tp99 = "):
        assert emitted in window

def test_metric_schema_is_v2():
    from veritx_dse.application.presets import METRIC_SCHEMA_VERSION
    assert METRIC_SCHEMA_VERSION == "booksim-parse/v2"

def test_qtime_and_request_metrics_are_in_different_families():
    from veritx_dse.application.presets import (
        LATENCY_POPULATIONS, METRIC_DEFINITIONS, STATS_TO_METRIC,
    )
    ids = {d.metric_id for d in METRIC_DEFINITIONS}
    qtime = set(LATENCY_POPULATIONS["booksim_qtime"])
    request = set(LATENCY_POPULATIONS["trace_request"])
    assert qtime <= ids and request <= ids
    assert not (qtime & request), "the two populations must not overlap"

    assert STATS_TO_METRIC["latency"] == "sim.latency.avg_cycles"
    assert STATS_TO_METRIC["honest_latency"] == \
        "sim.trace_request_latency.avg_cycles"
    for key in ("p50", "p95", "p99"):
        assert STATS_TO_METRIC[key].startswith("sim.trace_request_latency.")
    for gone in ("sim.latency.p50_cycles", "sim.latency.p95_cycles",
                 "sim.latency.p99_cycles", "sim.packets.count"):
        assert gone not in ids, f"{gone} still present — ambiguous family"

def test_max_packet_latency_belongs_to_the_qtime_family():
    """'\\tmaximum' follows 'Packet latency average', i.e. _plat_stats->Max()."""
    from veritx_dse.application.presets import STATS_TO_METRIC
    assert STATS_TO_METRIC["max_packet_latency"] == "sim.latency.max_cycles"

def test_pkt_count_belongs_to_the_request_family():
    """pkt_count is sorted_lat.size() == _all_latencies.size()."""
    from veritx_dse.application.presets import STATS_TO_METRIC
    assert STATS_TO_METRIC["pkt_count"] == "sim.trace_request_latency.samples"

def test_every_metric_id_is_defined_and_unique():
    from veritx_dse.application.presets import (
        METRIC_DEFINITIONS, STATS_TO_METRIC, get_metric_definition,
    )
    ids = [d.metric_id for d in METRIC_DEFINITIONS]
    assert len(ids) == len(set(ids)), "duplicate metric id"
    for key, mid in STATS_TO_METRIC.items():
        assert get_metric_definition(mid).metric_id == mid, \
            f"{key} maps to an undefined metric {mid}"

def test_latency_metric_definitions_name_their_population():
    """A consumer reading a latency metric must be told which population it
    is, in the definition text itself."""
    from veritx_dse.application.presets import (
        LATENCY_POPULATIONS, get_metric_definition,
    )
    for mid in LATENCY_POPULATIONS["booksim_qtime"]:
        d = get_metric_definition(mid).definition.lower()
        assert "qtime" in d or "stock" in d, f"{mid} does not name its population"
    for mid in LATENCY_POPULATIONS["trace_request"]:
        d = get_metric_definition(mid).definition.lower()
        assert "request" in d or "_all_latencies" in d, \
            f"{mid} does not name its population"

def test_backward_compatible_avg_id_is_retained_and_explained():
    """`sim.latency.avg_cycles` is kept for compatibility, and its definition
    must warn that it is NOT the request-time distribution."""
    from veritx_dse.application.presets import get_metric_definition
    d = get_metric_definition("sim.latency.avg_cycles").definition.lower()
    assert "not the same population" in d

def test_certified_path_does_not_claim_to_prefer_honest_latency():
    """_execute_prepared parses both keys, requires stock `latency`, and
    stores the full dict. The docs must not say it 'prefers' honest."""
    src = (DSE / "veritx_dse/simulation/booksim.py").read_text()
    assert "certified evidence path and the comparison CLI prefer" not in src
    assert "WHO READS WHAT" in src
    backend = (DSE / "veritx_dse/backend/booksim.py").read_text()
    assert 'if "latency" not in stats:' in backend
