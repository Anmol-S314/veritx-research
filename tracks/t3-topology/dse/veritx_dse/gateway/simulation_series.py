"""veritx_dse.gateway.simulation_series — Phase 3 loom simulation API logic.

Consumes the frozen Phase-2 reader
(``veritx_dse.backend.channel_series``) — a hard import, never a stub:
if the reader is absent or broken this module fails loudly at import.

The endpoint logic below (``load_table`` / ``series_payload`` /
``link_detail``) is reader-independent: every function takes an
explicit store root and reads nothing else. Only the four frozen
refusal names plus the spec-§2 artifact field names are assumed; row
shapes belong to the reader and are never indexed here except through
``utilization_table`` passthrough in ``load_table``.

Rationale: docs/decisions/modules/gateway.md
"""
from __future__ import annotations

import re as _re
from pathlib import Path
from typing import Any

from veritx_dse.backend.channel_series import (
    SCHEMA_VERSION,
    ChannelLoadSeriesArtifact,
    SeriesRefusal,
    load_series,
    series_for_run,
    utilization_table,
)
from veritx_dse.core.errors import InvalidInput
from veritx_dse.core.errors import UnsupportedSemantics
from veritx_dse.gateway.errors import NotFound

# Provenance marker: the active reader. Pinned by contract test.
_READER = "backend.channel_series"


def _series_refusal(code: str, message: str) -> SeriesRefusal:
    # Only the four frozen names are contractual; the real
    # reader's constructor is not, so adapt defensively.
    try:
        return SeriesRefusal(code, message)  # type: ignore[call-arg]
    except TypeError:
        exc = SeriesRefusal(message)  # type: ignore[call-arg]
        exc.code = code
        return exc


_SOURCES = ("derived", "measured")

_RUN_TOKEN = _re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


def _guard_run_token(run: str) -> None:
    # Belt and braces beside the reader's own token guard: the API
    # resolves nothing that is not a single path token. Traversal
    # collapses to NO_RUN, never an escape.
    if not isinstance(run, str) or not _RUN_TOKEN.match(run):
        raise _series_refusal("NO_RUN", f"no such run: {run!r}")


def _guard_no_fixture(artifact: Any) -> None:
    # Live routes never serve fixture bytes, whatever the reader checks.
    prov = getattr(artifact, "provenance", None)
    backend = (prov.get("backend") if isinstance(prov, dict)
               else getattr(prov, "backend", None))
    if backend == "fixture":
        raise _series_refusal(
            "STALE_FIXTURE",
            "series claims a fixture backend: live routes never serve "
            "fixture bytes")


def load_table(store_dir: Path, run: str,
               source: str) -> dict[str, Any]:
    """Per-channel utilization table for one run.

    ``measured`` is served from the sampled-counters artifact. ``derived``
    has no server-side producer (Studio's client-side derivation remains
    its authority), so requesting it here is a typed refusal, not an
    interpolated table.
    """
    if source not in _SOURCES:
        raise InvalidInput(
            f"source must be one of {list(_SOURCES)}, got {source!r}")
    if source == "derived":
        raise UnsupportedSemantics(
            "derived utilization has no server-side producer: the loom "
            "simulation API serves measured channel load only; derived "
            "load remains the Studio client's own derivation")
    _guard_run_token(run)
    artifact = series_for_run(run, str(Path(store_dir)))
    _guard_no_fixture(artifact)
    return {
        "run": run,
        "source": "measured",
        "capacity_formula": artifact.capacity_formula,
        "link_capacity_flits_per_cycle": (
            artifact.link_capacity_flits_per_cycle),
        "sample_period_cycles": artifact.sample_period_cycles,
        "num_windows": artifact.num_windows,
        "cycles_sampled": artifact.cycles_sampled(),
        "time_resets_observed": artifact.time_resets_observed,
        "channels": utilization_table(artifact),
        "provenance": artifact.provenance,
    }


def series_payload(store_dir: Path, run: str,
                   source: str | None = None) -> dict[str, Any]:
    """The full sampled series for scrubbing. Derived data has no time
    axis, so ``source=derived`` is refused, never answered with a flat
    line."""
    if source == "derived":
        raise _series_refusal(
            "NO_TIME_AXIS",
            "derived load has no time axis: the series endpoint serves "
            "measured window aggregates only")
    _guard_run_token(run)
    artifact = series_for_run(run, str(Path(store_dir)))
    _guard_no_fixture(artifact)
    # Explicit shape, never asdict: channel entries are not required to
    # be dataclasses by the frozen contract.
    return {
        "source": "measured",
        "run_hash": artifact.run_hash,
        "schema_version": artifact.schema_version,
        "sample_period_cycles": artifact.sample_period_cycles,
        "num_windows": artifact.num_windows,
        "cycles_sampled": artifact.cycles_sampled(),
        "time_resets_observed": artifact.time_resets_observed,
        "capacity_formula": artifact.capacity_formula,
        "link_capacity_flits_per_cycle": (
            artifact.link_capacity_flits_per_cycle),
        "channels": [
            {"logical_channel_id": entry.logical_channel_id,
             "flits_per_window": list(entry.flits_per_window),
             "window_cycles": list(entry.window_cycles),
             "stalls_per_window": (
                 list(entry.stalls_per_window)
                 if entry.stalls_per_window is not None else None)}
            for entry in artifact.channels
        ],
        "provenance": artifact.provenance,
    }


def link_detail(store_dir: Path, run: str,
                channel: str) -> dict[str, Any]:
    """Selected-link detail. ``breakdown`` is None: the Phase-0 spike
    verdict is ABSENT (no per-channel wait/Tx counters exist) — an
    absent segment is named, never interpolated."""
    _guard_run_token(run)
    artifact = series_for_run(run, str(Path(store_dir)))
    _guard_no_fixture(artifact)
    match = None
    for entry in artifact.channels:
        if str(entry.logical_channel_id) == channel:
            match = entry
            break
    if match is None:
        raise NotFound(f"run {run} has no measured channel {channel!r}")
    total = sum(match.flits_per_window)
    denom = (artifact.cycles_sampled()
             * artifact.link_capacity_flits_per_cycle)
    return {
        "run": run,
        "source": "measured",
        "logical_channel_id": match.logical_channel_id,
        "utilization": total / denom,
        "total_flits": total,
        "stalls_total": (
            sum(match.stalls_per_window)
             if match.stalls_per_window is not None else None),
        "breakdown": None,
        "breakdown_absence": (
            "arb-wait / active-Tx split is not a measured counter "
            "(Phase-0 spike verdict: ABSENT)"),
        "capacity_formula": artifact.capacity_formula,
        "sample_period_cycles": artifact.sample_period_cycles,
        "num_windows": artifact.num_windows,
        "cycles_sampled": artifact.cycles_sampled(),
        "time_resets_observed": artifact.time_resets_observed,
    }


__all__ = [
    "SCHEMA_VERSION", "ChannelLoadSeriesArtifact", "SeriesRefusal",
    "load_series", "series_for_run", "utilization_table",
    "load_table", "series_payload", "link_detail",
]
