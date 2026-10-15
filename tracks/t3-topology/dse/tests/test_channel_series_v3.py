"""Sampled channel-load series v3 (simulation-overlay Phase D).

v3 adds the MEASURED queue / arb-wait / Tx split and the occupancy
integral (fork Phase A). A v2 series must keep parsing with those fields
absent — never synthesised as zeros — so an older run reads as "the split
was never measured".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

cs = pytest.importorskip("veritx_dse.backend.channel_series")
gateway = pytest.importorskip("veritx_dse.gateway.simulation_series")


def _channel(cid: int, split: bool = True, **over):
    entry = {
        "logical_channel_id": cid,
        "flits_per_window": [10, 20, 30],
        "window_cycles": [100, 100, 100],
        "stalls_per_window": None,
    }
    if split:
        entry.update({
            "queue_cycles_per_window": [5, 7, 9],
            "arb_wait_cycles_per_window": [1, 2, 3],
            "tx_flits_per_window": [10, 20, 30],
            "tx_busy_cycles_per_window": [40, 40, 40],
            "occupancy_flit_cycles_per_window": [200, 300, 400],
            "queue_max_per_window": [7, 9, 11],
            "arb_max_per_window": [3, 4, 5],
            "occupancy_max_per_window": [4, 5, 6],
        })
    entry.update(over)
    return entry


def _doc(schema_version: int = 3, channels=None, **over):
    doc = {
        "schema_version": schema_version,
        "run_hash": "a" * 64,
        "sample_period_cycles": 100,
        "num_windows": 3,
        "time_resets_observed": 0,
        "capacity_formula": cs.CAPACITY_FORMULA,
        "link_capacity_flits_per_cycle": 1,
        "channels": channels if channels is not None else [_channel(0), _channel(1)],
        "provenance": {
            "backend": "BOOKSIM_STANDALONE",
            "version": "veritx-fork",
            "binary_hash": "b" * 64,
            "input_hashes": ["c" * 64],
        },
    }
    doc.update(over)
    return doc


# ---- reader -----------------------------------------------------------

def test_v3_parses_and_exposes_the_split():
    art = cs.parse_series_document(_doc())
    assert art.schema_version == 3
    ch = art.channels[0]
    assert ch.has_split()
    assert ch.queue_cycles_per_window == (5, 7, 9)
    assert ch.arb_wait_cycles_per_window == (1, 2, 3)
    assert ch.tx_flits_per_window == (10, 20, 30)
    assert ch.occupancy_flit_cycles_per_window == (200, 300, 400)
    # (queue 21 + arb 6) / tx 60
    assert ch.per_hop_latency_mean() == pytest.approx(27 / 60)
    # integral 900 over 300 sampled cycles
    assert ch.cycle_depth_mean(art.cycles_sampled()) == pytest.approx(3.0)


def test_v2_still_parses_with_the_split_absent():
    art = cs.parse_series_document(_doc(schema_version=2, channels=[_channel(0, split=False)]))
    assert art.schema_version == 2
    ch = art.channels[0]
    assert not ch.has_split()
    assert ch.queue_cycles_per_window is None
    assert ch.per_hop_latency_mean() is None
    assert ch.cycle_depth_mean(art.cycles_sampled()) is None


def test_v3_missing_key_refuses():
    entry = _channel(0)
    del entry["tx_flits_per_window"]
    with pytest.raises(cs.SeriesMalformed):
        cs.parse_series_document(_doc(channels=[entry]))


def test_v3_negative_value_refuses():
    with pytest.raises(cs.SeriesMalformed):
        cs.parse_series_document(
            _doc(channels=[_channel(0, arb_wait_cycles_per_window=[1, -2, 3])]))


def test_v3_ragged_window_refuses():
    with pytest.raises(cs.SeriesMalformed):
        cs.parse_series_document(
            _doc(channels=[_channel(0, occupancy_flit_cycles_per_window=[1, 2])]))


def test_unknown_version_refuses():
    with pytest.raises(cs.SeriesMalformed):
        cs.parse_series_document(_doc(schema_version=4))


# ---- utilization table ------------------------------------------------

def test_utilization_table_carries_the_split_columns():
    rows = cs.utilization_table(cs.parse_series_document(_doc()))
    assert rows
    row = rows[0]
    assert row["has_split"] is True
    assert row["queue_cycles_total"] == 21
    assert row["arb_wait_cycles_total"] == 6
    assert row["tx_flits_total"] == 60
    assert row["per_hop_latency_mean_cycles"] == pytest.approx(27 / 60)
    assert row["mean_queued_flits_per_output"] == pytest.approx(3.0)
    assert row["peak_queued_flits"] == 6   # max(occupancy_max_per_window)
    assert row["peak_arb_wait_cycles"] == 5


def test_utilization_table_v2_columns_are_none_not_zero():
    rows = cs.utilization_table(
        cs.parse_series_document(_doc(schema_version=2, channels=[_channel(0, split=False)])))
    row = rows[0]
    assert row["has_split"] is False
    assert row["queue_cycles_total"] is None
    assert row["mean_queued_flits_per_output"] is None
    assert row["peak_queued_flits"] is None


# ---- gateway ----------------------------------------------------------

def _store(tmp_path: Path, doc: dict) -> Path:
    run = "d" * 64
    run_dir = tmp_path / run
    run_dir.mkdir()
    (run_dir / cs.SERIES_FILENAME).write_text(json.dumps(doc))
    return tmp_path, run


def test_link_detail_serves_the_measured_breakdown(tmp_path):
    store, run = _store(tmp_path, _doc(channels=[_channel(7)]))
    detail = gateway.link_detail(Path(store), run, "7")
    assert detail["breakdown"]["source"] == "measured"
    assert detail["breakdown"]["queue_cycles"] == 21
    assert detail["breakdown"]["arb_wait_cycles"] == 6
    assert detail["breakdown"]["tx_flits"] == 60
    assert detail["breakdown"]["per_hop_latency_mean_cycles"] == pytest.approx(27 / 60)
    assert detail["breakdown"]["mean_queued_flits_per_output"] == pytest.approx(3.0)
    assert detail["breakdown_absence"] is None


def test_link_detail_v2_names_the_absence(tmp_path):
    store, run = _store(tmp_path, _doc(schema_version=2, channels=[_channel(7, split=False)]))
    detail = gateway.link_detail(Path(store), run, "7")
    assert detail["breakdown"] is None
    assert "schema v2" in detail["breakdown_absence"]


def test_series_payload_v2_emits_null_not_empty_arrays(tmp_path):
    store, run = _store(tmp_path, _doc(schema_version=2, channels=[_channel(7, split=False)]))
    payload = gateway.series_payload(Path(store), run)
    entry = payload["channels"][0]
    assert entry["queue_cycles_per_window"] is None
    assert entry["occupancy_flit_cycles_per_window"] is None
