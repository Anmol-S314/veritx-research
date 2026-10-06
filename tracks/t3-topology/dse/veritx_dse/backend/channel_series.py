"""veritx_dse.backend.channel_series — MEASURED per-channel load over time.

A channel-load series answers what the backend's counters saw *per
sampling window*: per logical channel, flits per window (and stall
samples where the fork exposes them). It is read from the fork's
``channel_timeseries.json`` dump, never scraped from stdout, and never
mixed with DERIVED EXPECTED load (which has no time axis at all —
requesting a series for the derived source is a typed refusal, not a
flat line).

Sampling is lossy by declaration: windows are aggregates, not a
replayable trace. Loom's scrubber scrubs window aggregates.

Conventions follow backend/channel_measurements.py: frozen dataclasses,
refuse-everything validation, counted-not-attributed honesty. Ragged
windows, negative counts, duplicate channel ids, and zero-window runs
refuse rather than rescale.

Rationale: docs/decisions/modules/backend.md
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Mapping

SCHEMA_VERSION = 2

SERIES_FILENAME = "channel_timeseries.json"

# Run-hash token rule: names outside this set are unresolvable, never an
# escape. Mirrors the gateway endpoint guard so library callers get the
# same NO_RUN (not a misleading NO_MEASURED) on hostile input.
_RUN_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]*\Z")

# Logical-channel id packing (single home for the mapping; the fork owns
# the pack, this module owns the decode):
#   id = subnet * 100_000_000 + router_id * 10_000 + output_port
# Limits are enforced fork-side (channel_activity.hpp); decode here is
# pure arithmetic and refuses out-of-range fields rather than wrapping.
_SUBNET_BASE = 100_000_000
_ROUTER_BASE = 10_000
_MAX_PORT = 10_000


def decode_logical_channel_id(packed: int) -> tuple[int, int, int]:
    """Decode a packed channel id to (subnet, router_id, output_port)."""
    if type(packed) is not int or packed < 0:
        raise SeriesMalformed(
            f"logical channel id {packed!r} is not a non-negative int")
    subnet, rest = divmod(packed, _SUBNET_BASE)
    router_id, port = divmod(rest, _ROUTER_BASE)
    if port >= _MAX_PORT:
        raise SeriesMalformed(
            f"logical channel id {packed} has an out-of-range port "
            f"field {port}")
    return (subnet, router_id, port)

CAPACITY_FORMULA = (
    "flits_per_window/(window_cycles*link_capacity_flits_per_cycle)"
)


class SeriesRefusal(ValueError):
    """A channel-load series cannot be served.

    ``code`` is one of NO_RUN (nothing stored for this run), NO_MEASURED
    (the run predates counters or carries no measurements), NO_TIME_AXIS
    (a series was requested for a sourceless-of-time source such as
    DERIVED load), PERIOD_MISMATCH (stored period differs from the
    requested one), or MALFORMED (the stored bytes are not a v2 series).
    The loom API maps the first four onto client refusals; MALFORMED is
    an internal error, never a client response shape.
    """

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(f"{code}: {reason}")
        self.code = code


class SeriesNotFound(SeriesRefusal):
    """Nothing usable stored for this run."""

    def __init__(self, code: str = "NO_RUN", reason: str = "") -> None:
        super().__init__(code, reason or "no stored series for this run")


class SeriesPeriodMismatch(SeriesRefusal):
    """The stored sampling period differs from the requested one."""

    def __init__(self, stored: int, requested: int) -> None:
        super().__init__(
            "PERIOD_MISMATCH",
            f"stored sample period is {stored} cycles, requested "
            f"{requested} — refusing to resample silently")


class SeriesEmpty(SeriesRefusal):
    """The stored series carries zero windows: no measurements."""

    def __init__(self, reason: str = "zero windows") -> None:
        super().__init__("NO_MEASURED", reason)


class SeriesMalformed(SeriesRefusal):
    """The stored bytes are not a v2 channel-load series."""

    def __init__(self, reason: str) -> None:
        super().__init__("MALFORMED", reason)


def no_time_axis(source: str) -> SeriesRefusal:
    """Refusal for a series requested from a sourceless-of-time source."""
    return SeriesRefusal(
        "NO_TIME_AXIS",
        f"source {source!r} has no time axis — refusing to serve a "
        "flat line as a series")


def _need_nonneg_int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SeriesMalformed(f"{where} must be a non-negative int, "
                              f"got {value!r}")
    return value


def _need_pos_int(value: Any, where: str) -> int:
    if (isinstance(value, bool) or not isinstance(value, int)
            or value <= 0):
        raise SeriesMalformed(f"{where} must be a positive int, "
                              f"got {value!r}")
    return value


def _need_pos_number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SeriesMalformed(f"{where} must be a positive number, "
                              f"got {value!r}")
    number = float(value)
    if not number > 0:
        raise SeriesMalformed(f"{where} must be positive, got {value!r}")
    return number


def _need_nonempty_str(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise SeriesMalformed(f"{where} must be a non-empty string, "
                              f"got {value!r}")
    return value


@dataclass(frozen=True)
class ChannelSeries:
    """One logical channel's per-window measured counters."""

    logical_channel_id: int
    flits_per_window: tuple[int, ...]
    window_cycles: tuple[int, ...]
    stalls_per_window: tuple[int, ...] | None


@dataclass(frozen=True)
class SeriesProvenance:
    """Which backend produced this series, from which inputs."""

    backend: str
    version: str
    binary_hash: str
    input_hashes: tuple[str, ...]


@dataclass(frozen=True)
class ChannelLoadSeriesArtifact:
    """MEASURED per-channel load sampled over windows.

    ``capacity_formula`` is the utilization definition, stored inline so
    a reader never applies a different one silently. Utilization for a
    channel is total flits divided by ``cycles_sampled *
    link_capacity_flits_per_cycle``, where ``cycles_sampled`` is the
    sum of the true per-window spans (``window_cycles``). Spans are
    global to the sampler (one poll clock): epoch edges and the
    trailing partial window carry shorter spans, and the denominator
    uses them — assuming full nominal periods would understate
    utilization silently. ``stalls_per_window`` is None (not zeros)
    when the fork does not expose stall counters.
    ``time_resets_observed`` counts BookSim wall-clock resets (one per
    sim after the first): windows telescope across resets by
    re-baselining, so conservation holds for any sim count.
    """

    schema_version: int
    run_hash: str
    sample_period_cycles: int
    num_windows: int
    time_resets_observed: int
    capacity_formula: str
    link_capacity_flits_per_cycle: float
    channels: tuple[ChannelSeries, ...]
    provenance: SeriesProvenance

    def flits_total(self) -> int:
        """Measured flits across all channels and windows."""
        return sum(sum(c.flits_per_window) for c in self.channels)

    def cycles_sampled(self) -> int:
        """True sampled cycles: sum of window spans (global)."""
        if not self.channels:
            return 0
        return sum(self.channels[0].window_cycles)


def _parse_provenance(value: Any) -> SeriesProvenance:
    if not isinstance(value, Mapping):
        raise SeriesMalformed("provenance must be an object")
    raw_hashes = value.get("input_hashes")
    if (not isinstance(raw_hashes, list)
            or any(not isinstance(h, str) or not h for h in raw_hashes)):
        raise SeriesMalformed(
            "provenance.input_hashes must be a list of non-empty strings")
    return SeriesProvenance(
        backend=_need_nonempty_str(value.get("backend"),
                                   "provenance.backend"),
        version=_need_nonempty_str(value.get("version"),
                                   "provenance.version"),
        binary_hash=_need_nonempty_str(value.get("binary_hash"),
                                       "provenance.binary_hash"),
        input_hashes=tuple(raw_hashes),
    )


def _parse_channel(entry: Any, num_windows: int) -> ChannelSeries:
    if not isinstance(entry, Mapping):
        raise SeriesMalformed("channel entry must be an object")
    channel_id = _need_nonneg_int(
        entry.get("logical_channel_id"), "logical_channel_id")
    raw_flits = entry.get("flits_per_window")
    if (not isinstance(raw_flits, list)
            or len(raw_flits) != num_windows
            or any(isinstance(v, bool) or not isinstance(v, int) or v < 0
                   for v in raw_flits)):
        raise SeriesMalformed(
            f"channel {channel_id}: flits_per_window must be "
            f"{num_windows} non-negative ints")
    if "stalls_per_window" not in entry:
        raise SeriesMalformed(
            f"channel {channel_id}: stalls_per_window key is missing "
            "— the fork must emit an explicit null when it exposes "
            "no stall counters")
    raw_stalls = entry["stalls_per_window"]
    stalls: tuple[int, ...] | None
    if raw_stalls is None:
        stalls = None
    elif (not isinstance(raw_stalls, list)
            or len(raw_stalls) != num_windows
            or any(isinstance(v, bool) or not isinstance(v, int) or v < 0
                   for v in raw_stalls)):
        raise SeriesMalformed(
            f"channel {channel_id}: stalls_per_window must be null or "
            f"{num_windows} non-negative ints")
    else:
        stalls = tuple(raw_stalls)
    raw_spans = entry.get("window_cycles")
    if (not isinstance(raw_spans, list)
            or len(raw_spans) != num_windows
            or any(isinstance(v, bool) or not isinstance(v, int) or v <= 0
                   for v in raw_spans)):
        raise SeriesMalformed(
            f"channel {channel_id}: window_cycles must be "
            f"{num_windows} positive ints (true per-window spans)")
    return ChannelSeries(
        logical_channel_id=channel_id,
        flits_per_window=tuple(raw_flits),
        window_cycles=tuple(raw_spans),
        stalls_per_window=stalls,
    )


def parse_series_document(doc: Any) -> ChannelLoadSeriesArtifact:
    """Validate a raw series document. Refuses everything malformed.

    Zero windows is an empty run, not an empty chart: SeriesEmpty.
    """
    if not isinstance(doc, dict):
        raise SeriesMalformed(
            f"series document must be an object, got "
            f"{type(doc).__name__}")
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise SeriesMalformed(
            f"series schema_version {doc.get('schema_version')!r} is not "
            f"{SCHEMA_VERSION} — refusing to parse an unknown version")
    num_windows = doc.get("num_windows")
    if num_windows == 0:
        raise SeriesEmpty()
    if (isinstance(num_windows, bool) or not isinstance(num_windows, int)
            or num_windows < 0):
        raise SeriesMalformed("num_windows must be a non-negative int, "
                              f"got {num_windows!r}")
    raw_channels = doc.get("channels")
    if not isinstance(raw_channels, list):
        raise SeriesMalformed("channels must be a list")
    channels = tuple(_parse_channel(e, num_windows) for e in raw_channels)
    seen = set()
    reference_spans: tuple[int, ...] | None = None
    for channel in channels:
        if channel.logical_channel_id in seen:
            raise SeriesMalformed(
                f"logical_channel_id "
                f"{channel.logical_channel_id} appears twice — "
                "refusing an ambiguous series")
        seen.add(channel.logical_channel_id)
        # Spans are global to the one sampler: disagreeing spans mean
        # the dump was spliced or corrupted — refuse, never average.
        if reference_spans is None:
            reference_spans = channel.window_cycles
        elif channel.window_cycles != reference_spans:
            raise SeriesMalformed(
                f"channel {channel.logical_channel_id}: window_cycles "
                "disagree with the series span grid — refusing a "
                "spliced series")
    formula = doc.get("capacity_formula")
    if formula != CAPACITY_FORMULA:
        raise SeriesMalformed(
            "capacity_formula must be the frozen definition "
            f"{CAPACITY_FORMULA!r}, got {formula!r} — a series with a "
            "different utilization definition is not comparable")
    return ChannelLoadSeriesArtifact(
        schema_version=SCHEMA_VERSION,
        run_hash=_need_nonempty_str(doc.get("run_hash"), "run_hash"),
        sample_period_cycles=_need_pos_int(
            doc.get("sample_period_cycles"), "sample_period_cycles"),
        num_windows=num_windows,
        time_resets_observed=_need_nonneg_int(
            doc.get("time_resets_observed"), "time_resets_observed"),
        capacity_formula=CAPACITY_FORMULA,
        link_capacity_flits_per_cycle=_need_pos_number(
            doc.get("link_capacity_flits_per_cycle"),
            "link_capacity_flits_per_cycle"),
        channels=channels,
        provenance=_parse_provenance(doc.get("provenance")),
    )


def load_series(path: str) -> ChannelLoadSeriesArtifact:
    """Read and validate a series dump file. Fails closed throughout."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            doc = json.load(handle)
    except FileNotFoundError:
        raise SeriesNotFound(
            "NO_RUN", f"no series file at {path}") from None
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise SeriesMalformed(f"cannot decode series file at "
                              f"{path}: {exc}") from None
    return parse_series_document(doc)


def series_for_run(run_hash: str,
                   store_dir: str,
                   expect_period_cycles: int | None = None,
                   ) -> ChannelLoadSeriesArtifact:
    """Load the stored series for a run hash.

    Layout: ``<store_dir>/<run_hash>/channel_timeseries.json``. A missing
    run directory is NO_RUN; a run directory without a series file is
    NO_MEASURED (the run predates counters). ``expect_period_cycles``
    refuses PERIOD_MISMATCH instead of resampling.
    """
    if not isinstance(run_hash, str) or not _RUN_TOKEN.match(run_hash):
        raise SeriesNotFound("NO_RUN", f"invalid run hash {run_hash!r}")
    run_dir = os.path.join(store_dir, run_hash)
    if not os.path.isdir(run_dir):
        raise SeriesNotFound(
            "NO_RUN", f"no stored run {run_hash!r} under {store_dir}")
    try:
        artifact = load_series(os.path.join(run_dir, SERIES_FILENAME))
    except SeriesNotFound:
        raise SeriesNotFound(
            "NO_MEASURED",
            f"run {run_hash!r} has no {SERIES_FILENAME} — the run "
            "predates sampled counters") from None
    if (expect_period_cycles is not None
            and artifact.sample_period_cycles != expect_period_cycles):
        raise SeriesPeriodMismatch(
            artifact.sample_period_cycles, expect_period_cycles)
    return artifact


def utilization_table(
        artifact: ChannelLoadSeriesArtifact,
        ) -> list[dict[str, Any]]:
    """Per-channel utilization, sorted descending.

    Utilization is total flits over the TRUE sampled capacity
    (cycles_sampled * link_capacity_flits_per_cycle) defined by the
    artifact's frozen capacity formula. Peak is the hottest window's
    own rate (flits[i] / span[i] / capacity). Sorted by utilization
    so the top-N congested links read off the head.
    """
    sampled = artifact.cycles_sampled()
    capacity = sampled * artifact.link_capacity_flits_per_cycle
    rows = []
    for channel in artifact.channels:
        total = sum(channel.flits_per_window)
        peak = 0.0
        for flits, span in zip(channel.flits_per_window,
                               channel.window_cycles):
            rate = (flits / span
                    / artifact.link_capacity_flits_per_cycle)
            if rate > peak:
                peak = rate
        rows.append({
            "logical_channel_id": channel.logical_channel_id,
            "flits_total": total,
            "cycles_sampled": sampled,
            "utilization": total / capacity if capacity else 0.0,
            "peak_window_utilization": peak,
            "has_stalls": channel.stalls_per_window is not None,
        })
    rows.sort(key=lambda r: r["utilization"], reverse=True)
    return rows
