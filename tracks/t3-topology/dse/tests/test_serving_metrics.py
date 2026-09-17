"""Phase 5 — canonical serving metric vocabulary tests.

Every number states producer/fidelity/scope/unit/derivation. Units are
pinned at the scheduler source (request.py: ticks @ FREQ=1GHz ⇒ ns);
no silent conversions exist in the builder (it never sees cycles,
bytes, or wall seconds except wall_time, which is labeled as such).
"""
import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.core.serving_metrics import (
    SERVING_METRIC_SCHEMA,
    VOCABULARY,
    build_serving_metrics,
)

FID = "SYSTEM_SERVING_SIMULATION"

HEADER = ["instance id", "request id", "model", "input", "output",
          "arrival", "end_time", "latency", "queuing_delay",
          "TTFT", "TPOT", "ITL"]


def _csv(tmp_path, rows):
    p = tmp_path / "r.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
    return p


def _row(inst="0", req="0", arr="100", end="1100", lat="1000", qd="50",
         ttft="700", tpot="100", itl="[100,100]"):
    return [inst, req, "m", "10", "12", arr, end, lat, qd, ttft, tpot, itl]


class TestVocabulary:
    def test_minimum_program_names_present(self):
        for name in ("sim_clock", "request_latency", "TTFT", "TPOT",
                     "ITL", "requests_submitted", "requests_retired",
                     "wall_time"):
            assert name in VOCABULARY, f"program-minimum {name} undefined"

    def test_every_entry_has_units_producer_scope(self):
        for name, entry in VOCABULARY.items():
            for key in ("unit", "producer", "scope", "source",
                        "derivation"):
                assert key in entry, f"{name} missing {key}"

    def test_time_units_are_nanoseconds_not_cycles(self):
        for name in ("sim_clock", "request_latency", "TTFT", "TPOT",
                     "ITL"):
            assert VOCABULARY[name]["unit"] == "ns", name

    def test_exposed_comm_marked_unsourced(self):
        entry = VOCABULARY["backend_exposed_communication"]
        assert entry["producer"] == "UNSOURCED", \
            "no emitter produces per-request exposed comm; must stay marked"


class TestBuilder:
    def test_means_and_clock(self, tmp_path):
        p = _csv(tmp_path, [_row(arr="100", end="1100", lat="1000",
                                 ttft="700", tpot="100"),
                            _row(inst="1", req="1", arr="200", end="1500",
                                 lat="1300", ttft="900", tpot="200")])
        bundle = build_serving_metrics(p, num_requested=2, fidelity=FID,
                                       wall_time_s=3.5)
        assert bundle["schema"] == SERVING_METRIC_SCHEMA
        m = bundle["metrics"]
        assert m["requests_retired"]["value"] == 2
        assert m["requests_submitted"]["value"] == 2
        assert m["requests_retired"]["unit"] == "requests"
        assert m["sim_clock"]["value"] == 1500  # max end_time
        assert m["sim_clock"]["unit"] == "ns"
        assert m["TTFT"]["value"] == 800
        assert m["TPOT"]["value"] == 150
        assert m["request_latency"]["value"] == 1150
        assert m["ITL"]["value"] == 100
        for _name, metric in m.items():
            assert metric["fidelity"] == FID, _name
            assert metric["producer"] in ("llmservingsim", "veritx"), \
                _name
        assert m["wall_time"]["producer"] == "veritx"
        assert m["wall_time"]["unit"] == "s"

    def test_retirement_mismatch_named(self, tmp_path):
        p = _csv(tmp_path, [_row()])
        with pytest.raises(ValueError, match="RETIREMENT_MISMATCH"):
            build_serving_metrics(p, num_requested=2, fidelity=FID,
                                  wall_time_s=1.0)

    def test_empty_itl_omitted_not_zeroed(self, tmp_path):
        p = _csv(tmp_path, [_row(itl="[]")])
        m = build_serving_metrics(p, num_requested=1, fidelity=FID,
                                  wall_time_s=1.0)
        assert "ITL" not in m["metrics"], \
            "no token gaps observed → no ITL metric, never a fabricated 0"

    def test_missing_column_fails_loudly(self, tmp_path):
        p = tmp_path / "bad.csv"
        with open(p, "w", newline="") as f:
            csv.writer(f).writerow(["instance id"])
            csv.writer(f).writerow(["0"])
        with pytest.raises(ValueError, match="column"):
            build_serving_metrics(p, num_requested=1, fidelity=FID,
                                  wall_time_s=1.0)
