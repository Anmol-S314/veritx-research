"""Per-traffic-class evidence carried by a verified performance result.

BookSim reports per-class flit counters and per-class latency by trace
class INDEX; the canonical class NAME comes from the same trace class map
the projection rendered.  This module owns the one closed shape that can
travel inside a ``PerformanceResult`` document:

``traffic_class_metrics`` = {
    "schema_version": 1,
    "evidence_sha256": "<evidence bytes digest>",
    "stats_sha256": "<parsed stats digest>",
    "flit_width_bits": <positive int or null>,
    "class_names": ["<canonical trace class>", ...],
    "classes": [
        {"traffic_class": "<canonical name>",
         "trace_class_index": <dense trace index>,
         "flits_injected": <non-negative int or null>,
         "flits_accepted": <non-negative int or null>,
         "bytes_injected": {"num": n, "den": d} or null,
         "bytes_accepted": {"num": n, "den": d} or null,
         "latency": {"packet_latency_avg": <finite number>, ...}},
    ],
}

Absent readings stay absent (null / missing key) — they are never
zero-filled.  Byte movement is derived from the measured flit count and
the canonical packet format's flit width; when either is missing there is
no byte claim and class bandwidth stays UNMEASURABLE.

Rationale: docs/decisions/modules/performance.md
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

TRAFFIC_CLASS_METRICS_SCHEMA_VERSION = 1

#: The per-class latency fields the BookSim fork prints inside each
#: ``Class N:`` block.  Kept in the same order as the metric registry's
#: ``BOOKSIM_PER_CLASS_LATENCY_METRICS`` so both surfaces read one set.
TRAFFIC_CLASS_LATENCY_FIELDS = (
    "packet_latency_avg", "flit_latency_avg", "p50", "p95", "p99",
    "pkt_count", "honest_latency",
)

_TOP_KEYS = frozenset({
    "schema_version", "evidence_sha256", "stats_sha256",
    "flit_width_bits", "class_names", "classes",
})
_CLASS_KEYS = frozenset({
    "traffic_class", "trace_class_index", "flits_injected",
    "flits_accepted", "bytes_injected", "bytes_accepted", "latency",
})
_HEX = frozenset("0123456789abcdef")


class TrafficClassMetricsError(ValueError):
    """A per-class evidence block is malformed or cannot be bound."""


def _hex64(value: Any, where: str) -> str:
    bare = value[7:] if isinstance(value, str) \
        and value.startswith("sha256:") else value
    if not isinstance(bare, str) or len(bare) != 64 \
            or any(c not in _HEX for c in bare):
        raise TrafficClassMetricsError(
            f"{where} must be a 64-char lowercase hex digest, got {value!r}")
    return bare


def _class_index(value: Any) -> int | None:
    """A trace-class index from an int or its canonical JSON string key."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdigit() \
            and str(int(value)) == value:
        return int(value)
    return None


def _non_negative_int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TrafficClassMetricsError(
            f"{where} must be a non-negative integer, got {value!r}")
    return value


def _finite_number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TrafficClassMetricsError(
            f"{where} must be a real number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise TrafficClassMetricsError(
            f"{where} must be finite, got {value!r}")
    return number


def _fraction_doc(value: Any, where: str) -> dict[str, int] | None:
    if value is None:
        return None
    if isinstance(value, Fraction):
        return {"num": value.numerator, "den": value.denominator}
    if not isinstance(value, Mapping) or set(value) != {"num", "den"}:
        raise TrafficClassMetricsError(
            f"{where} must be null or {{num, den}}, got {value!r}")
    num, den = value["num"], value["den"]
    if isinstance(num, bool) or not isinstance(num, int) or num < 0 \
            or isinstance(den, bool) or not isinstance(den, int) or den <= 0:
        raise TrafficClassMetricsError(
            f"{where} must have a non-negative integer num and a positive "
            f"integer den, got {value!r}")
    return {"num": num, "den": den}


def _fraction(value: Any, where: str) -> Fraction | None:
    doc = _fraction_doc(value, where)
    if doc is None:
        return None
    return Fraction(doc["num"], doc["den"])


def _bytes_for_flits(flits: int | None, flit_width_bits: int | None
                     ) -> dict[str, int] | None:
    if flits is None or flit_width_bits is None:
        return None
    value = Fraction(flits * flit_width_bits, 8)
    return {"num": value.numerator, "den": value.denominator}


@dataclass(frozen=True)
class ClassMeasurement:
    """One class's measured readings, as carried by the verified result."""

    traffic_class: str
    trace_class_index: int
    flits_injected: int | None
    flits_accepted: int | None
    bytes_injected: Fraction | None
    bytes_accepted: Fraction | None
    latency: tuple[tuple[str, float], ...]

    def latency_value(self, field: str) -> float | None:
        for name, value in self.latency:
            if name == field:
                return value
        return None


def _parse_row(row: Mapping[str, Any]) -> ClassMeasurement:
    name = row["traffic_class"]
    if not isinstance(name, str) or not name:
        raise TrafficClassMetricsError(
            f"traffic_class must be a non-empty string, got {name!r}")
    index = row["trace_class_index"]
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise TrafficClassMetricsError(
            f"traffic_class_metrics[{name}].trace_class_index must be a "
            f"non-negative integer, got {index!r}")
    injected = (None if row["flits_injected"] is None else
                _non_negative_int(row["flits_injected"],
                                 f"traffic_class_metrics[{name}].flits_injected"))
    accepted = (None if row["flits_accepted"] is None else
                _non_negative_int(row["flits_accepted"],
                                  f"traffic_class_metrics[{name}].flits_accepted"))
    bytes_injected = _fraction(row["bytes_injected"],
                               f"traffic_class_metrics[{name}].bytes_injected")
    bytes_accepted = _fraction(row["bytes_accepted"],
                               f"traffic_class_metrics[{name}].bytes_accepted")
    latency_doc = row["latency"]
    if not isinstance(latency_doc, Mapping):
        raise TrafficClassMetricsError(
            f"traffic_class_metrics[{name}].latency must be an object")
    unknown = set(latency_doc) - set(TRAFFIC_CLASS_LATENCY_FIELDS)
    if unknown:
        raise TrafficClassMetricsError(
            f"traffic_class_metrics[{name}].latency has unknown fields "
            f"{sorted(unknown)}")
    latency: list[tuple[str, float]] = []
    for field in TRAFFIC_CLASS_LATENCY_FIELDS:
        if field not in latency_doc:
            continue
        raw = latency_doc[field]
        if field == "pkt_count":
            latency.append((field, float(_non_negative_int(
                raw, f"traffic_class_metrics[{name}].latency.{field}"))))
        else:
            latency.append((field, _finite_number(
                raw, f"traffic_class_metrics[{name}].latency.{field}")))
    return ClassMeasurement(
        traffic_class=name,
        trace_class_index=index,
        flits_injected=injected, flits_accepted=accepted,
        bytes_injected=bytes_injected, bytes_accepted=bytes_accepted,
        latency=tuple(latency))


def validate_traffic_class_metrics(block: Any) -> dict[str, Any]:
    """Validate a closed per-class block and return it unchanged."""
    if not isinstance(block, Mapping):
        raise TrafficClassMetricsError(
            "traffic_class_metrics must be an object, got "
            f"{type(block).__name__}")
    if set(block) != _TOP_KEYS:
        raise TrafficClassMetricsError(
            f"traffic_class_metrics fields must be exactly {sorted(_TOP_KEYS)}, "
            f"got {sorted(block)}")
    if block["schema_version"] != TRAFFIC_CLASS_METRICS_SCHEMA_VERSION:
        raise TrafficClassMetricsError(
            f"unsupported traffic_class_metrics schema_version "
            f"{block['schema_version']!r}")
    _hex64(block["evidence_sha256"], "traffic_class_metrics.evidence_sha256")
    _hex64(block["stats_sha256"], "traffic_class_metrics.stats_sha256")
    width = block["flit_width_bits"]
    if width is not None and (
            isinstance(width, bool) or not isinstance(width, int)
            or width <= 0):
        raise TrafficClassMetricsError(
            f"traffic_class_metrics.flit_width_bits must be a positive "
            f"integer or null, got {width!r}")
    rows = block["classes"]
    if not isinstance(rows, list) or not rows:
        raise TrafficClassMetricsError(
            "traffic_class_metrics.classes must be a non-empty list")
    class_names = block["class_names"]
    if not isinstance(class_names, list) or not class_names \
            or any(not isinstance(name, str) or not name
                   for name in class_names) \
            or len(set(class_names)) != len(class_names) \
            or class_names != sorted(class_names):
        raise TrafficClassMetricsError(
            "traffic_class_metrics.class_names must be a sorted, "
            "distinct, non-empty list of class names")
    seen: set[str] = set()
    seen_indices: set[int] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise TrafficClassMetricsError(
                "each traffic_class_metrics class entry must be an object")
        if set(row) != _CLASS_KEYS:
            raise TrafficClassMetricsError(
                f"traffic class entry fields must be exactly "
                f"{sorted(_CLASS_KEYS)}, got {sorted(row)}")
        measurement = _parse_row(row)
        if measurement.traffic_class in seen:
            raise TrafficClassMetricsError(
                f"traffic_class_metrics repeats class "
                f"{measurement.traffic_class!r}")
        if measurement.trace_class_index in seen_indices:
            raise TrafficClassMetricsError(
                f"traffic_class_metrics repeats trace class index "
                f"{measurement.trace_class_index}")
        if measurement.trace_class_index >= len(class_names) \
                or class_names[measurement.trace_class_index] \
                != measurement.traffic_class:
            raise TrafficClassMetricsError(
                f"traffic_class_metrics[{measurement.traffic_class!r}] "
                f"trace_class_index {measurement.trace_class_index} does "
                f"not name that class in class_names {class_names!r}")
        seen.add(measurement.traffic_class)
        seen_indices.add(measurement.trace_class_index)
        for field, flits, stored in (
                ("bytes_injected", measurement.flits_injected,
                 measurement.bytes_injected),
                ("bytes_accepted", measurement.flits_accepted,
                 measurement.bytes_accepted)):
            expected = (None if flits is None or width is None
                        else Fraction(flits * width, 8))
            if stored != expected:
                raise TrafficClassMetricsError(
                    f"traffic_class_metrics[{measurement.traffic_class}]."
                    f"{field} is not flits x flit_width_bits / 8 "
                    f"({stored!r} vs {expected!r})")
            if stored is not None and stored < 0:
                raise TrafficClassMetricsError(
                    f"traffic_class_metrics[{measurement.traffic_class}]."
                    f"{field} is negative")
    return dict(block)


def parse_traffic_class_metrics(
        block: Any) -> tuple[ClassMeasurement, ...]:
    """Validate then expose the block's readings as measurements."""
    validate_traffic_class_metrics(block)
    return tuple(_parse_row(row) for row in block["classes"])


def build_traffic_class_metrics(
        *,
        stats: Mapping[str, Any],
        class_names: tuple[str, ...],
        flit_width_bits: int | None,
        evidence_sha256: str,
        stats_sha256: str,
) -> dict[str, Any] | None:
    """Build the closed block from parsed BookSim stats.

    Returns ``None`` when the stats carry no per-class reading.  A class
    the stats omit is simply absent (never zero); a per-class index the
    canonical map does not name refuses the whole block (never guessed).
    """
    if not isinstance(stats, Mapping):
        return None
    counters = stats.get("flits_by_class")
    latency_stats = stats.get("latency_by_class")
    has_counters = isinstance(counters, Mapping) and bool(counters)
    has_latency = isinstance(latency_stats, Mapping) and bool(latency_stats)
    if not has_counters and not has_latency:
        return None
    names = tuple(class_names or ())
    if not names:
        raise TrafficClassMetricsError(
            "per-class readings are present but the canonical trace class "
            "map is unavailable; refusing to guess class names")
    if any(not isinstance(name, str) or not name for name in names) \
            or len(set(names)) != len(names) \
            or list(names) != sorted(names):
        raise TrafficClassMetricsError(
            f"class_names must be distinct, non-empty and sorted, got "
            f"{names!r}")
    if flit_width_bits is not None and (
            isinstance(flit_width_bits, bool)
            or not isinstance(flit_width_bits, int)
            or flit_width_bits <= 0):
        raise TrafficClassMetricsError(
            f"flit_width_bits must be a positive integer or null, got "
            f"{flit_width_bits!r}")

    rows: dict[int, dict[str, Any]] = {}

    def _row(raw_index: Any, where: str) -> dict[str, Any]:
        index = _class_index(raw_index)
        if index is None or index >= len(names):
            raise TrafficClassMetricsError(
                f"{where} index {raw_index!r} is outside the canonical class "
                f"map {list(names)}; refusing to guess a class name")
        return rows.setdefault(index, {
            "traffic_class": names[index],
            "trace_class_index": index,
            "flits_injected": None, "flits_accepted": None,
            "bytes_injected": None, "bytes_accepted": None,
            "latency": {}})

    if has_counters:
        seen: set[int] = set()
        for raw_index, counter_row in counters.items():
            index = _class_index(raw_index)
            if index is None or index >= len(names):
                raise TrafficClassMetricsError(
                    f"flits_by_class index {raw_index!r} is outside the "
                    f"canonical class map {list(names)}")
            if index in seen:
                raise TrafficClassMetricsError(
                    f"flits_by_class repeats class index {index}")
            seen.add(index)
            if not isinstance(counter_row, Mapping):
                raise TrafficClassMetricsError(
                    f"flits_by_class[{raw_index}] is not a counter mapping")
            row = _row(raw_index, "flits_by_class")
            injected = counter_row.get("injected")
            accepted = counter_row.get("accepted")
            if injected is not None:
                row["flits_injected"] = _non_negative_int(
                    injected, f"flits_by_class[{raw_index}].injected")
            if accepted is not None:
                row["flits_accepted"] = _non_negative_int(
                    accepted, f"flits_by_class[{raw_index}].accepted")

    if has_latency:
        seen = set()
        for raw_index, latency_row in latency_stats.items():
            index = _class_index(raw_index)
            if index is None or index >= len(names):
                raise TrafficClassMetricsError(
                    f"latency_by_class index {raw_index!r} is outside the "
                    f"canonical class map {list(names)}")
            if index in seen:
                raise TrafficClassMetricsError(
                    f"latency_by_class repeats class index {index}")
            seen.add(index)
            if not isinstance(latency_row, Mapping):
                raise TrafficClassMetricsError(
                    f"latency_by_class[{raw_index}] is not a latency mapping")
            row = _row(raw_index, "latency_by_class")
            for field in TRAFFIC_CLASS_LATENCY_FIELDS:
                raw = latency_row.get(field)
                if raw is None:
                    continue
                if field == "pkt_count":
                    row["latency"][field] = _non_negative_int(
                        raw, f"latency_by_class[{raw_index}].{field}")
                else:
                    row["latency"][field] = _finite_number(
                        raw, f"latency_by_class[{raw_index}].{field}")

    classes: list[dict[str, Any]] = []
    for index in sorted(rows):
        row = rows[index]
        if row["flits_injected"] is None and row["flits_accepted"] is None \
                and not row["latency"]:
            continue
        row["bytes_injected"] = _bytes_for_flits(
            row["flits_injected"], flit_width_bits)
        row["bytes_accepted"] = _bytes_for_flits(
            row["flits_accepted"], flit_width_bits)
        row["latency"] = dict(sorted(row["latency"].items()))
        classes.append(row)
    if not classes:
        return None
    block = {
        "schema_version": TRAFFIC_CLASS_METRICS_SCHEMA_VERSION,
        "evidence_sha256": _hex64(
            evidence_sha256, "traffic_class_metrics.evidence_sha256"),
        "stats_sha256": _hex64(
            stats_sha256, "traffic_class_metrics.stats_sha256"),
        "flit_width_bits": flit_width_bits,
        "class_names": list(names),
        "classes": classes,
    }
    return validate_traffic_class_metrics(block)


__all__ = [
    "ClassMeasurement",
    "TRAFFIC_CLASS_LATENCY_FIELDS",
    "TRAFFIC_CLASS_METRICS_SCHEMA_VERSION",
    "TrafficClassMetricsError",
    "build_traffic_class_metrics",
    "parse_traffic_class_metrics",
    "validate_traffic_class_metrics",
]
