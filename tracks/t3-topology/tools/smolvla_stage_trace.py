#!/usr/bin/env python3
"""Validate and normalize SmolVLA policy-stage JSONL traces.

Schema
------
One *group* is one timed ``predict_action_chunk`` call.  All rows in a group
share the same ``timestamp_s`` (a ``time.perf_counter()`` reading, so it is
monotonic within a process, not wall-clock time).  A group must contain exactly
these 15 stages (this is also the canonical output order):

    vision_encoder
    vlm_prefill
    action_denoise_step_0 ... action_denoise_step_9
    action_denoise_total
    policy_total
    other

Every row has ``timestamp_s``, ``stage`` and ``duration_ms``.  Optional metadata,
uniform within a group when present:

    payload_bytes       non-negative integer (decoded camera bytes)
    image_resolution    [height, width], both positive integers
    chunk_size          positive integer
    n_action_steps      positive integer
    num_denoise_steps   must be 10 when present

Checks
------
* durations and timestamps are finite, non-negative numbers;
* stages are unique within a group and all 15 required stages are present;
* ``action_denoise_total`` equals the sum of the ten denoise-step durations;
* ``policy_total`` equals ``vision_encoder + vlm_prefill + action_denoise_total
  + other``;

both sums within ``SUM_TOLERANCE_MS`` (0.01 ms = 10 microseconds, absolute).
That tolerance is generous compared with the full-precision JSON round-trip
(which is exact to double precision) but tight compared with the ~1.8 s policy
call.

``normalize`` validates the whole input first, then writes groups sorted by
``timestamp_s`` and rows in the fixed stage order.  It fails closed: an invalid
input produces no partial output file.  Extra fields are preserved at the end of
each normalized row (sorted by key) but are not validated.

Stdlib only.  This tool does not import LeRobot or torch.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
import json
import math
import numbers
from pathlib import Path
import sys
from typing import Any, TextIO

NUM_DENOISE_STEPS = 10
DENOISE_STAGES: tuple[str, ...] = tuple(
    f"action_denoise_step_{index}" for index in range(NUM_DENOISE_STEPS)
)
REQUIRED_STAGES: tuple[str, ...] = (
    "vision_encoder",
    "vlm_prefill",
    *DENOISE_STAGES,
    "action_denoise_total",
    "policy_total",
    "other",
)
STAGE_ORDER: tuple[str, ...] = REQUIRED_STAGES
STAGE_INDEX: dict[str, int] = {stage: index for index, stage in enumerate(STAGE_ORDER)}

SUM_TOLERANCE_MS = 0.01

CANONICAL_KEYS: tuple[str, ...] = (
    "timestamp_s",
    "stage",
    "duration_ms",
    "payload_bytes",
    "image_resolution",
    "chunk_size",
    "n_action_steps",
    "num_denoise_steps",
)
OPTIONAL_INT_FIELDS: tuple[str, ...] = (
    "payload_bytes",
    "chunk_size",
    "n_action_steps",
    "num_denoise_steps",
)


class TraceError(ValueError):
    """A stage trace cannot be validated without guessing."""

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        timestamp_s: float | None = None,
        line: int | None = None,
    ) -> None:
        self.field = field
        self.timestamp_s = timestamp_s
        self.line = line
        parts = []
        if line is not None:
            parts.append(f"line {line}")
        if timestamp_s is not None:
            parts.append(f"timestamp_s={timestamp_s!r}")
        prefix = ": ".join(parts)
        suffix = f" (field {field!r})" if field else ""
        super().__init__((prefix + ": " if prefix else "") + message + suffix)


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, numbers.Real)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _number(
    value: Any,
    field: str,
    *,
    timestamp_s: float | None = None,
    line: int | None = None,
    minimum: float | None = 0.0,
) -> float:
    if not _is_number(value):
        raise TraceError(
            "expected a finite number",
            field=field,
            timestamp_s=timestamp_s,
            line=line,
        )
    result = float(value)
    if minimum is not None and result < minimum:
        raise TraceError(
            f"expected a value >= {minimum:g}, got {result:g}",
            field=field,
            timestamp_s=timestamp_s,
            line=line,
        )
    return result


def _optional_int(
    value: Any,
    field: str,
    *,
    timestamp_s: float | None,
    line: int | None,
    minimum: int = 0,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise TraceError(
            f"expected an integer >= {minimum} or null",
            field=field,
            timestamp_s=timestamp_s,
            line=line,
        )
    result = int(value)
    if result < minimum:
        raise TraceError(
            f"expected a value >= {minimum}, got {result}",
            field=field,
            timestamp_s=timestamp_s,
            line=line,
        )
    return result


def _optional_resolution(
    value: Any,
    *,
    timestamp_s: float | None,
    line: int | None,
) -> list[int] | None:
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TraceError(
            "image_resolution must be [height, width] or null",
            field="image_resolution",
            timestamp_s=timestamp_s,
            line=line,
        )
    if len(value) != 2:
        raise TraceError(
            "image_resolution must contain exactly two entries [height, width]",
            field="image_resolution",
            timestamp_s=timestamp_s,
            line=line,
        )
    pair: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, numbers.Integral):
            raise TraceError(
                "image_resolution entries must be positive integers",
                field="image_resolution",
                timestamp_s=timestamp_s,
                line=line,
            )
        number = int(item)
        if number <= 0:
            raise TraceError(
                "image_resolution entries must be positive integers",
                field="image_resolution",
                timestamp_s=timestamp_s,
                line=line,
            )
        pair.append(number)
    return pair


def _metadata(
    row: Mapping[str, Any], *, timestamp_s: float, line: int | None
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "payload_bytes": _optional_int(
            row.get("payload_bytes"), "payload_bytes", timestamp_s=timestamp_s, line=line
        ),
        "image_resolution": _optional_resolution(
            row.get("image_resolution"), timestamp_s=timestamp_s, line=line
        ),
        "chunk_size": _optional_int(
            row.get("chunk_size"),
            "chunk_size",
            timestamp_s=timestamp_s,
            line=line,
            minimum=1,
        ),
        "n_action_steps": _optional_int(
            row.get("n_action_steps"),
            "n_action_steps",
            timestamp_s=timestamp_s,
            line=line,
            minimum=1,
        ),
        "num_denoise_steps": _optional_int(
            row.get("num_denoise_steps"),
            "num_denoise_steps",
            timestamp_s=timestamp_s,
            line=line,
            minimum=1,
        ),
    }
    if (
        metadata["num_denoise_steps"] is not None
        and metadata["num_denoise_steps"] != NUM_DENOISE_STEPS
    ):
        raise TraceError(
            f"num_denoise_steps must be {NUM_DENOISE_STEPS} for this schema, "
            f"got {metadata['num_denoise_steps']}",
            field="num_denoise_steps",
            timestamp_s=timestamp_s,
            line=line,
        )
    return metadata


def _close(left: float, right: float) -> bool:
    return math.isclose(
        left, right, rel_tol=1e-9, abs_tol=SUM_TOLERANCE_MS
    )


def _validate_group(
    timestamp_s: float, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_stage: dict[str, dict[str, Any]] = {}
    for row in rows:
        stage = row["stage"]
        if stage not in STAGE_INDEX:
            raise TraceError(
                f"unknown stage; expected one of {list(STAGE_ORDER)}",
                field="stage",
                timestamp_s=timestamp_s,
            )
        if stage in by_stage:
            raise TraceError(
                "duplicate stage within one timestamp_s group",
                field=stage,
                timestamp_s=timestamp_s,
            )
        by_stage[stage] = row

    missing = [stage for stage in STAGE_ORDER if stage not in by_stage]
    if missing:
        raise TraceError(
            f"missing required stage(s): {missing}",
            field=missing[0],
            timestamp_s=timestamp_s,
        )

    # Metadata must be uniform within the group.  A field may be absent on all
    # rows, but it may not be absent on some rows and present on others.
    for field in (*OPTIONAL_INT_FIELDS, "image_resolution"):
        present = [row[field] is not None for row in by_stage.values()]
        if any(present) and not all(present):
            raise TraceError(
                f"{field} is present on some rows of the group but not all",
                field=field,
                timestamp_s=timestamp_s,
            )
        values = {json.dumps(row[field], sort_keys=True) for row in by_stage.values()}
        if len(values) > 1:
            raise TraceError(
                "metadata is not uniform within the group",
                field=field,
                timestamp_s=timestamp_s,
            )

    durations = {
        stage: float(by_stage[stage]["duration_ms"]) for stage in STAGE_ORDER
    }
    denoise_sum = sum(durations[stage] for stage in DENOISE_STAGES)
    if not _close(durations["action_denoise_total"], denoise_sum):
        raise TraceError(
            "action_denoise_total does not equal the sum of the ten denoise "
            f"steps: {durations['action_denoise_total']:.9f} vs "
            f"{denoise_sum:.9f} ms (tolerance {SUM_TOLERANCE_MS:g} ms)",
            field="action_denoise_total",
            timestamp_s=timestamp_s,
        )

    reconstructed_total = (
        durations["vision_encoder"]
        + durations["vlm_prefill"]
        + durations["action_denoise_total"]
        + durations["other"]
    )
    if not _close(durations["policy_total"], reconstructed_total):
        raise TraceError(
            "policy_total does not equal vision_encoder + vlm_prefill + "
            f"action_denoise_total + other: {durations['policy_total']:.9f} vs "
            f"{reconstructed_total:.9f} ms (tolerance {SUM_TOLERANCE_MS:g} ms)",
            field="policy_total",
            timestamp_s=timestamp_s,
        )

    return [by_stage[stage] for stage in STAGE_ORDER]


def validate_rows(rows: Iterable[Mapping[str, Any]]) -> list[list[dict[str, Any]]]:
    """Return validated groups sorted by timestamp, each in canonical stage order.

    Raises ``TraceError`` on the first problem.  The returned rows are the input
    mappings (not copies); ``normalize_rows`` rebuilds them in canonical key
    order.
    """
    groups: dict[float, list[dict[str, Any]]] = {}
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise TraceError("expected a JSON object", line=index)

        timestamp_s = _number(
            row.get("timestamp_s"), "timestamp_s", line=index
        )
        stage = row.get("stage")
        if not isinstance(stage, str) or not stage:
            raise TraceError(
                "expected a non-empty stage string",
                field="stage",
                timestamp_s=timestamp_s,
                line=index,
            )
        _number(
            row.get("duration_ms"),
            "duration_ms",
            timestamp_s=timestamp_s,
            line=index,
        )
        metadata = _metadata(row, timestamp_s=timestamp_s, line=index)

        normalized_input = dict(row)
        normalized_input["timestamp_s"] = timestamp_s
        normalized_input["stage"] = stage
        normalized_input["duration_ms"] = float(row["duration_ms"])
        normalized_input.update(metadata)
        groups.setdefault(timestamp_s, []).append(normalized_input)

    if not groups:
        raise TraceError("trace contains no rows")

    return [
        _validate_group(timestamp_s, groups[timestamp_s])
        for timestamp_s in sorted(groups)
    ]


def _canonical_row(row: Mapping[str, Any]) -> dict[str, Any]:
    canonical: dict[str, Any] = {}
    for key in CANONICAL_KEYS:
        value = row.get(key)
        if value is not None:
            canonical[key] = list(value) if key == "image_resolution" else value
    for key in sorted(key for key in row if key not in CANONICAL_KEYS):
        canonical[key] = row[key]
    return canonical


def normalize_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate, sort by timestamp then stage, and return canonical-key rows."""
    groups = validate_rows(rows)
    return [_canonical_row(row) for group in groups for row in group]


def read_jsonl(stream: TextIO) -> list[dict[str, Any]]:
    """Parse one JSON object per non-blank line, with line-numbered errors."""
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(stream, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TraceError(
                f"invalid JSON: {exc.msg}", line=line_number
            ) from exc
        if not isinstance(value, Mapping):
            raise TraceError("expected a JSON object", line=line_number)
        rows.append(dict(value))
    return rows


def write_jsonl(rows: Iterable[Mapping[str, Any]], stream: TextIO) -> int:
    """Write deterministic compact JSONL; return the row count."""
    count = 0
    for row in rows:
        stream.write(
            json.dumps(
                row,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            + "\n"
        )
        count += 1
    return count


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smolvla_stage_trace.py",
        description=(
            "Validate or normalize SmolVLA vision/prefill/denoise stage JSONL."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("validate", "validate a stage trace and print a summary"),
        ("normalize", "validate, sort, and write a canonical stage trace"),
    ):
        subparser = subparsers.add_parser(name, help=help_text)
        subparser.add_argument(
            "--input",
            type=Path,
            metavar="PATH",
            help="read JSONL from PATH (default: stdin)",
        )
        if name == "normalize":
            subparser.add_argument(
                "--output",
                type=Path,
                metavar="PATH",
                help="write normalized JSONL to PATH (default: stdout)",
            )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.input is not None:
            with args.input.open("r", encoding="utf-8") as source:
                rows = read_jsonl(source)
        else:
            rows = read_jsonl(sys.stdin)

        groups = validate_rows(rows)

        if args.command == "validate":
            print(
                f"valid: {len(groups)} group(s), "
                f"{sum(len(group) for group in groups)} row(s), "
                f"{len(STAGE_ORDER)} stages per group, "
                f"sum tolerance {SUM_TOLERANCE_MS:g} ms"
            )
            return 0

        normalized = [_canonical_row(row) for group in groups for row in group]
        if args.output is not None:
            with args.output.open("w", encoding="utf-8") as sink:
                write_jsonl(normalized, sink)
        else:
            write_jsonl(normalized, sys.stdout)
    except TraceError as exc:
        print(f"smolvla_stage_trace: {exc}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError) as exc:
        print(f"smolvla_stage_trace: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
