"""Sampled channel-load series (track SPEC Phase 1): contract + reader.

Layer A pins the frozen dump shape as an executable contract (runs
without the reader). Layer B exercises the typed reader
(``veritx_dse.backend.channel_series``).

Reconciled contract (reader landed mid-track and is authoritative on
details): logical channels are integer ids joining to the certified
channel table (T6 convention — display labels are a Studio concern);
the dump carries the frozen ``capacity_formula`` verbatim and a
provenance block; zero windows is NO_MEASURED, never an empty chart;
a requested period that disagrees is PERIOD_MISMATCH, never a silent
resample; windows are preserved element-wise.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

cs = pytest.importorskip(
    "veritx_dse.backend.channel_series",
    reason="typed series reader has not landed (parallel track)",
)

SCHEMA_VERSION = 2
CLIENT_REFUSAL_CODES = {"NO_RUN", "NO_MEASURED", "NO_TIME_AXIS",
                        "PERIOD_MISMATCH"}

try:
    from veritx_dse.backend.channel_series import (  # noqa: E402
        CAPACITY_FORMULA as _FROZEN_FORMULA,
    )
except ImportError:  # reader track has not landed; shape-only fallback
    _FROZEN_FORMULA = ("flits_per_window/(window_cycles*"
                         "link_capacity_flits_per_cycle")


class ShapeViolation(ValueError):
    """Executable mirror of the frozen shape contract (Layer A only)."""


def _dump(**over):
    doc = {
        "schema_version": SCHEMA_VERSION,
        "run_hash": "deadbeef" * 8,
        "sample_period_cycles": 100,
        "num_windows": 4,
        "time_resets_observed": 0,
        "capacity_formula": _FROZEN_FORMULA,
        "link_capacity_flits_per_cycle": 1,
        "channels": [
            {
                "logical_channel_id": 0,
                "flits_per_window": [10, 20, 30, 40],
                "window_cycles": [100, 100, 100, 100],
                "stalls_per_window": [1, 2, 3, 4],
            },
            {
                "logical_channel_id": 1,
                "flits_per_window": [5, 5, 5, 5],
                "window_cycles": [100, 100, 100, 100],
                "stalls_per_window": None,
            },
        ],
        "provenance": {
            "backend": "BOOKSIM_FORK",
            "version": "test",
            "binary_hash": "00" * 16,
            "input_hashes": ["11" * 16],
        },
    }
    doc.update(over)
    return doc


def _assert_shape(doc):
    """Mirror of the frozen shape; the reader must enforce the same."""
    if not isinstance(doc, dict):
        raise ShapeViolation("series dump must be a mapping")
    for key in ("schema_version", "run_hash", "sample_period_cycles",
                "num_windows", "time_resets_observed",
                "capacity_formula",
                "link_capacity_flits_per_cycle", "channels", "provenance"):
        if key not in doc:
            raise ShapeViolation(f"missing required key {key!r}")
    resets = doc["time_resets_observed"]
    if (isinstance(resets, bool) or not isinstance(resets, int)
            or resets < 0):
        raise ShapeViolation("time_resets_observed must be a "
                             "non-negative int")
    if doc["schema_version"] != SCHEMA_VERSION:
        raise ShapeViolation("unknown schema_version")
    if (isinstance(doc["sample_period_cycles"], bool)
            or not isinstance(doc["sample_period_cycles"], int)
            or doc["sample_period_cycles"] <= 0):
        raise ShapeViolation("sample_period_cycles must be a positive int")
    n = doc["num_windows"]
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise ShapeViolation("num_windows must be a non-negative int")
    cap = doc["link_capacity_flits_per_cycle"]
    if (isinstance(cap, bool) or not isinstance(cap, (int, float))
            or cap <= 0):
        raise ShapeViolation("link_capacity must be a positive number")
    if (not isinstance(doc["capacity_formula"], str)
            or not doc["capacity_formula"]):
        raise ShapeViolation("capacity_formula must be a non-empty string")
    prov = doc["provenance"]
    if not isinstance(prov, dict):
        raise ShapeViolation("provenance must be a mapping")
    for key in ("backend", "version", "binary_hash", "input_hashes"):
        if key not in prov:
            raise ShapeViolation(f"provenance missing {key!r}")
    if not isinstance(doc["channels"], list):
        raise ShapeViolation("channels must be a list")
    for ch in doc["channels"]:
        for key in ("logical_channel_id", "flits_per_window",
                    "window_cycles", "stalls_per_window"):
            if key not in ch:
                raise ShapeViolation(f"channel missing {key!r}")
        spans = ch["window_cycles"]
        if (not isinstance(spans, list) or len(spans) != n
                or any(isinstance(v, bool) or not isinstance(v, int)
                       or v <= 0 for v in spans)):
            raise ShapeViolation("window_cycles must be positive ints "
                                 "of length num_windows")
        cid = ch["logical_channel_id"]
        if isinstance(cid, bool) or not isinstance(cid, int) or cid < 0:
            raise ShapeViolation("logical_channel_id must be a "
                                 "non-negative int (T6 channel-table key)")
        wins = ch["flits_per_window"]
        if (not isinstance(wins, list) or len(wins) != n
                or any(isinstance(v, bool) or not isinstance(v, int)
                       or v < 0 for v in wins)):
            raise ShapeViolation("flit windows must be non-negative ints "
                                 "of length num_windows")
        stalls = ch["stalls_per_window"]
        if stalls is not None and (
                not isinstance(stalls, list) or len(stalls) != n
                or any(isinstance(v, bool) or not isinstance(v, int)
                       or v < 0 for v in stalls)):
            raise ShapeViolation("stall windows must be null or "
                                 "non-negative ints of length num_windows")


# ---------------- Layer A: frozen-shape contract ----------------

def test_valid_dump_conforms_to_frozen_shape():
    _assert_shape(_dump())


def test_null_stalls_conform():
    doc = _dump()
    doc["channels"][0]["stalls_per_window"] = None
    _assert_shape(doc)


@pytest.mark.parametrize("key", ["schema_version", "run_hash",
                                 "sample_period_cycles", "num_windows",
                                 "time_resets_observed",
                                 "capacity_formula",
                                 "link_capacity_flits_per_cycle",
                                 "channels", "provenance"])
def test_missing_key_violates_shape(key):
    doc = _dump()
    del doc[key]
    with pytest.raises(ShapeViolation):
        _assert_shape(doc)


def test_schema_mismatch_violates_shape():
    with pytest.raises(ShapeViolation):
        _assert_shape(_dump(schema_version=999))


def test_ragged_flit_windows_violate_shape():
    doc = _dump()
    doc["channels"][0]["flits_per_window"] = [1, 2]
    with pytest.raises(ShapeViolation):
        _assert_shape(doc)


def test_negative_counts_violate_shape():
    doc = _dump()
    doc["channels"][1]["flits_per_window"] = [5, -1, 5, 5]
    with pytest.raises(ShapeViolation):
        _assert_shape(doc)


def test_string_channel_id_violates_shape():
    # Display labels ("R3,3->R4,3") are a Studio formatting concern;
    # artifact identity joins to the integer channel table.
    doc = _dump()
    doc["channels"][0]["logical_channel_id"] = "R0,0->R1,0"
    with pytest.raises(ShapeViolation):
        _assert_shape(doc)


def test_empty_series_is_wellformed_but_means_no_measurement():
    # num_windows == 0 with consistent (empty) vectors is well-formed as
    # data; the READER must still refuse it (Layer B), never chart it.
    _assert_shape(_dump(num_windows=0, channels=[]))


# ---------------- Layer B: reader integration ----------------

def _write(tmp_path, doc):
    import json
    path = tmp_path / "channel_timeseries.json"
    path.write_text(json.dumps(doc))
    return path


def _store_run(tmp_path, run_hash, doc):
    import json
    run_dir = tmp_path / run_hash
    run_dir.mkdir()
    (run_dir / "channel_timeseries.json").write_text(json.dumps(doc))
    return str(tmp_path)


def test_dump_carries_the_frozen_capacity_formula(tmp_path):
    doc = _dump()
    art = cs.load_series(_write(tmp_path, doc))
    assert art.capacity_formula == cs.CAPACITY_FORMULA


def test_reader_preserves_windows_elementwise(tmp_path):
    doc = _dump()
    art = cs.load_series(_write(tmp_path, doc))
    by_id = {c.logical_channel_id: c for c in art.channels}
    assert list(by_id[0].flits_per_window) == [10, 20, 30, 40]
    assert by_id[1].stalls_per_window is None


def test_window_sums_conserve_against_cumulative_totals(tmp_path):
    # Synthetic pair: cumulative totals (T6 shape) and series windows for
    # the same channels. Conservation is exact equality, never rescaling.
    doc = _dump()
    cumulative = {0: 100, 1: 20}
    art = cs.load_series(_write(tmp_path, doc))
    assert art.flits_total() == 120
    for ch in art.channels:
        assert (sum(ch.flits_per_window)
                == cumulative[ch.logical_channel_id])


def test_duplicate_channel_id_is_refused(tmp_path):
    doc = _dump()
    doc["channels"].append(dict(doc["channels"][0]))
    with pytest.raises(cs.SeriesRefusal) as exc:
        cs.load_series(_write(tmp_path, doc))
    assert exc.value.code == "MALFORMED"


def test_empty_run_is_refused_not_charted(tmp_path):
    doc = _dump(num_windows=0, channels=[])
    with pytest.raises(cs.SeriesRefusal) as exc:
        cs.load_series(_write(tmp_path, doc))
    assert exc.value.code in CLIENT_REFUSAL_CODES


def test_period_mismatch_is_refused_not_resampled(tmp_path):
    run_hash = "ab" * 32
    store = _store_run(tmp_path, run_hash, _dump())
    with pytest.raises(cs.SeriesRefusal) as exc:
        cs.series_for_run(run_hash, store, expect_period_cycles=999)
    assert exc.value.code == "PERIOD_MISMATCH"
    ok = cs.series_for_run(run_hash, store, expect_period_cycles=100)
    assert ok.sample_period_cycles == 100


def test_unknown_run_hash_is_refused(tmp_path):
    with pytest.raises(cs.SeriesRefusal) as exc:
        cs.series_for_run("00" * 32, str(tmp_path))
    assert exc.value.code == "NO_RUN"


def test_run_without_series_is_no_measured(tmp_path):
    (tmp_path / ("cd" * 32)).mkdir()
    with pytest.raises(cs.SeriesRefusal) as exc:
        cs.series_for_run("cd" * 32, str(tmp_path))
    assert exc.value.code == "NO_MEASURED"


def test_null_stalls_load_and_do_not_shift_utilization(tmp_path):
    doc = _dump()
    art = cs.load_series(_write(tmp_path, doc))
    rows = {r["logical_channel_id"]: r
            for r in cs.utilization_table(art)}
    # Channel 1 carries null stalls: 20 flits over 4x100 windows.
    assert rows[1]["utilization"] == pytest.approx(20 / 400)
    assert rows[1]["has_stalls"] is False
    assert rows[0]["has_stalls"] is True


def test_utilization_table_is_sorted_descending(tmp_path):
    doc = _dump()
    art = cs.load_series(_write(tmp_path, doc))
    rows = cs.utilization_table(art)
    utils = [r["utilization"] for r in rows]
    assert utils == sorted(utils, reverse=True)
    # 100 flits over 4x100 windows beats 20 over the same span.
    assert rows[0]["logical_channel_id"] == 0
    assert rows[0]["flits_total"] == 100
    assert rows[0]["utilization"] == pytest.approx(100 / 400)


def test_epoch_edge_spans_conserve_and_drive_the_denominator(tmp_path):
    # A reset epoch leaves a short edge slice (span 50, not 200):
    # conservation is exact and utilization divides by TRUE spans.
    doc = _dump(time_resets_observed=2)
    for ch in doc["channels"]:
        ch["window_cycles"] = [200, 200, 50, 200]
    art = cs.load_series(_write(tmp_path, doc))
    assert art.time_resets_observed == 2
    assert art.cycles_sampled() == 650
    assert art.flits_total() == 120
    rows = {r["logical_channel_id"]: r
            for r in cs.utilization_table(art)}
    # Channel 0: 100 flits over 650 true cycles, not 4x100 nominal.
    assert rows[0]["utilization"] == pytest.approx(100 / 650)
    assert rows[0]["cycles_sampled"] == 650
    # Peak is the hottest window's own rate: the 30-flit edge slice
    # over its true 50-cycle span (a nominal-period denominator
    # would have reported 30/200 and hidden the burst).
    assert rows[0]["peak_window_utilization"] == pytest.approx(30 / 50)


def test_disagreeing_spans_are_refused_not_averaged(tmp_path):
    doc = _dump()
    doc["channels"][1]["window_cycles"] = [100, 100, 100, 99]
    with pytest.raises(cs.SeriesRefusal) as exc:
        cs.load_series(_write(tmp_path, doc))
    assert exc.value.code == "MALFORMED"


def test_v1_dump_is_refused_as_unknown_version(tmp_path):
    # Strict pin: a v1 document (no spans/resets) is a different
    # schema, not a degenerate v2.
    doc = _dump(schema_version=1)
    for ch in doc["channels"]:
        del ch["window_cycles"]
    del doc["time_resets_observed"]
    with pytest.raises(cs.SeriesRefusal) as exc:
        cs.load_series(_write(tmp_path, doc))
    assert exc.value.code == "MALFORMED"


def test_missing_window_cycles_is_refused(tmp_path):
    doc = _dump()
    del doc["channels"][0]["window_cycles"]
    with pytest.raises(cs.SeriesRefusal) as exc:
        cs.load_series(_write(tmp_path, doc))
    assert exc.value.code == "MALFORMED"


# ---------------------------------------------------------------------------
# Layer C — parent additions: id decode (single home) + token guard.
# ---------------------------------------------------------------------------

def test_decode_logical_channel_id_round_trips_packing():
    packed = 2 * 100_000_000 + 37 * 10_000 + 5
    assert cs.decode_logical_channel_id(packed) == (2, 37, 5)
    assert cs.decode_logical_channel_id(0) == (0, 0, 0)


def test_decode_logical_channel_id_refuses_bad_input():
    for bad in (-1, "3", 3.0, True):
        with pytest.raises(Exception):
            cs.decode_logical_channel_id(bad)


def test_series_for_run_refuses_traversal_as_no_run(tmp_path):
    with pytest.raises(cs.SeriesNotFound) as exc:
        cs.series_for_run("..", str(tmp_path))
    assert exc.value.code == "NO_RUN"
    with pytest.raises(cs.SeriesNotFound) as exc:
        cs.series_for_run("a/b", str(tmp_path))
    assert exc.value.code == "NO_RUN"


def test_series_for_run_accepts_tagged_hash_token(tmp_path):
    # Lexer-safe tagged hashes (sha256-<hex>) must pass the token guard
    # and then fail as NO_RUN (missing dir), never as a token refusal.
    with pytest.raises(cs.SeriesNotFound) as exc:
        cs.series_for_run("sha256-" + "0" * 64, str(tmp_path))
    assert exc.value.code == "NO_RUN"
