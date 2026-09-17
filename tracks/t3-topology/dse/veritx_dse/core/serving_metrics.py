"""veritx_dse.core.serving_metrics — canonical serving vocabulary (Phase 5).

Every serving number states unit/producer/fidelity/scope/derivation.
Units are pinned at the scheduler source: request fields are sim-clock
ticks, and the sim clock runs at FREQ=1GHz (serving/__main__.py), so
1 tick = 1 ns BY CONVENTION — recorded here, never converted silently.
The builder below performs NO unit conversion at all, except wall_time,
which is supervisor-measured seconds and labeled as such.

Naming ruling (closes the Phase-1 residual): the program text's
SYSTEM_SIMULATION shorthand denotes the code's SYSTEM_SERVING_SIMULATION
category (runs.py, arch §13.1). Source wins; no rename.

Deliberately absent: backend_exposed_communication is DEFINED in the
vocabulary but marked UNSOURCED — the controller parses per-iteration
exposed cycles, yet no serving output (CSV/stdout) emits them. Wiring
an emitter is serving-loop instrumentation (a later phase), not
something to backfill by parsing prose here.
"""
from __future__ import annotations

import ast
import csv
from pathlib import Path
from typing import Any

from .runs import metric

# Version of THIS vocabulary (result bundles carry it; bump on any
# name/unit/derivation change — it deliberately forks comparability).
SERVING_METRIC_SCHEMA = 1

_TICK_NS = ("sim-clock ticks at FREQ=1GHz "
            "(serving/__main__: FREQ = 1000_000_000); 1 tick = 1 ns")

VOCABULARY: dict[str, dict[str, str]] = {
    "sim_clock": {
        "unit": "ns",
        "producer": "llmservingsim",
        "scope": "run",
        "source": "max(end_time) over retired requests; equals the "
                  "backend-reported Total clocks",
        "derivation": _TICK_NS,
    },
    "request_arrival_time": {
        "unit": "ns",
        "producer": "llmservingsim",
        "scope": "per_request",
        "source": "CSV arrival column (per-request artifact, hash kept)",
        "derivation": _TICK_NS,
    },
    "request_completion_time": {
        "unit": "ns",
        "producer": "llmservingsim",
        "scope": "per_request",
        "source": "CSV end_time column",
        "derivation": _TICK_NS,
    },
    "request_latency": {
        "unit": "ns",
        "producer": "llmservingsim",
        "scope": "per_request",
        "source": "CSV latency column; bundle carries the mean",
        "derivation": "end_time - arrival, per request.py:add_latency; "
                      "bundle mean over retired requests; " + _TICK_NS,
    },
    "TTFT": {
        "unit": "ns",
        "producer": "llmservingsim",
        "scope": "per_request",
        "source": "CSV TTFT column; bundle carries the mean",
        "derivation": "first-token time - arrival, per request.py:set_ttft; "
                      + _TICK_NS,
    },
    "TPOT": {
        "unit": "ns",
        "producer": "llmservingsim",
        "scope": "per_request",
        "source": "CSV TPOT column; bundle carries the mean",
        "derivation": "floor((latency - ttft) / (output_tokens - 1)), "
                      "0 for single-token output, per request.py:add_latency; "
                      + _TICK_NS,
    },
    "ITL": {
        "unit": "ns",
        "producer": "llmservingsim",
        "scope": "per_request",
        "source": "CSV ITL column (per-token gap list); bundle carries "
                  "the mean over all gaps of all retired requests",
        "derivation": "successive completion deltas, per "
                      "request.py:add_itl; " + _TICK_NS,
    },
    "requests_submitted": {
        "unit": "requests",
        "producer": "llmservingsim",
        "scope": "run",
        "source": "spec num_reqs (requested work)",
        "derivation": "count, no conversion",
    },
    "requests_retired": {
        "unit": "requests",
        "producer": "llmservingsim",
        "scope": "run",
        "source": "per-request CSV data-row count",
        "derivation": "count, no conversion",
    },
    "wall_time": {
        "unit": "s",
        "producer": "veritx",
        "scope": "run",
        "source": "supervisor-measured execution duration",
        "derivation": "WALL seconds, not simulated time — never compared "
                      "against sim_clock",
    },
    "backend_exposed_communication": {
        "unit": "cycles",
        "producer": "UNSOURCED",
        "scope": "run",
        "source": "NONE — parsed per-iteration by the controller but "
                  "emitted by no serving output; wiring an emitter is a "
                  "later serving-loop change",
        "derivation": "undefined until sourced; must not be backfilled",
    },
}

_REQUIRED_COLUMNS = ("instance id", "request id", "arrival", "end_time",
                     "latency", "TTFT", "TPOT", "ITL")


def _mean(ints: list[int]) -> int:
    return sum(ints) // len(ints)


def build_serving_metrics(csv_path: Any, *, num_requested: int,
                          fidelity: str, wall_time_s: float) -> dict:
    """Typed metric bundle from the authoritative per-request CSV.

    Raises ValueError(RETIREMENT_MISMATCH) unless every requested
    request retired, and ValueError on missing columns — malformed
    artifacts fail loudly, never as partial metrics.
    """
    path = Path(csv_path)
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in _REQUIRED_COLUMNS
                   if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"result CSV missing column(s) {missing}: "
                             f"{path}")
        rows = list(reader)
    if len(rows) != num_requested:
        raise ValueError(f"RETIREMENT_MISMATCH: retired {len(rows)} of "
                         f"{num_requested} requested ({path})")

    def _col(name: str) -> list[int]:
        return [int(r[name]) for r in rows]

    itl_gaps: list[int] = []
    for r in rows:
        gaps = ast.literal_eval(r["ITL"])
        if not isinstance(gaps, list):
            raise ValueError(f"result CSV has non-list ITL: {r['ITL']!r}")
        itl_gaps.extend(int(g) for g in gaps)

    def _typed(name: str, value: Any) -> dict[str, Any]:
        entry = VOCABULARY[name]
        producer = entry["producer"]
        return metric(name, value, entry["unit"], producer=producer,
                      fidelity=fidelity, scope=entry["scope"],
                      derivation=entry["derivation"])

    metrics: dict[str, Any] = {
        "requests_submitted": _typed("requests_submitted", num_requested),
        "requests_retired": _typed("requests_retired", len(rows)),
        "sim_clock": _typed("sim_clock", max(_col("end_time"))),
        "request_latency": _typed("request_latency",
                                  _mean(_col("latency"))),
        "TTFT": _typed("TTFT", _mean(_col("TTFT"))),
        "TPOT": _typed("TPOT", _mean(_col("TPOT"))),
        "wall_time": _typed("wall_time", round(wall_time_s, 3)),
    }
    # No token gaps observed → no ITL metric, never a fabricated 0.
    if itl_gaps:
        metrics["ITL"] = _typed("ITL", _mean(itl_gaps))
    return {"schema": SERVING_METRIC_SCHEMA, "metrics": metrics}
