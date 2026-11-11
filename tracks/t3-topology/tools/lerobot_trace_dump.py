#!/usr/bin/env python3
"""Normalize LeRobot inference records into flat JSONL stage rows.

The input is a stream of JSON objects (dicts or one JSON object per line) that a
LeRobot deployment emits around ``PolicyRunner.predict``.  Each input record
becomes four output rows in a fixed order: ``preprocessing``, ``policy``,
``postprocessing`` and ``total``.  The output is deliberately flat so a fabric
trace importer can consume it without knowing LeRobot's object model.

Stdlib only.  The recorder is not a LeRobot dependency and does not import or
modify LeRobot.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterable, Iterator, Mapping, Sequence
import json
import math
import numbers
from pathlib import Path
import sys
from typing import Any, TextIO

REQUIRED_STAGES: tuple[str, ...] = ("preprocessing", "policy", "postprocessing")
ROW_STAGES: tuple[str, ...] = REQUIRED_STAGES + ("total",)


class TraceRecordError(ValueError):
    """A LeRobot-shaped record cannot be normalized without guessing."""

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        record_index: int | None = None,
    ) -> None:
        self.field = field
        self.record_index = record_index
        prefix = f"record {record_index}: " if record_index is not None else ""
        suffix = f" (field {field!r})" if field else ""
        super().__init__(prefix + message + suffix)


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
    record_index: int | None,
    minimum: float | None = 0.0,
) -> float:
    if not _is_number(value):
        raise TraceRecordError(
            "expected a finite number", field=field, record_index=record_index
        )
    result = float(value)
    if minimum is not None and result < minimum:
        raise TraceRecordError(
            f"expected a value >= {minimum:g}, got {result:g}",
            field=field,
            record_index=record_index,
        )
    return result


def _optional_int(
    value: Any, field: str, *, record_index: int | None
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise TraceRecordError(
            "expected a non-negative integer or null",
            field=field,
            record_index=record_index,
        )
    result = int(value)
    if result < 0:
        raise TraceRecordError(
            f"expected a value >= 0, got {result}", field=field, record_index=record_index
        )
    return result


def _optional_resolution(
    value: Any, *, record_index: int | None
) -> list[int] | str | None:
    """Accept ``[height, width]`` or a non-empty ``"HxW"`` string."""
    if value is None:
        return None
    if isinstance(value, str):
        if not value.strip():
            raise TraceRecordError(
                "image_resolution string must not be empty",
                field="image_resolution",
                record_index=record_index,
            )
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) != 2:
            raise TraceRecordError(
                "image_resolution must be [height, width] or a string",
                field="image_resolution",
                record_index=record_index,
            )
        pair: list[int] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, numbers.Integral):
                raise TraceRecordError(
                    "image_resolution entries must be positive integers",
                    field="image_resolution",
                    record_index=record_index,
                )
            number = int(item)
            if number <= 0:
                raise TraceRecordError(
                    "image_resolution entries must be positive integers",
                    field="image_resolution",
                    record_index=record_index,
                )
            pair.append(number)
        return pair
    raise TraceRecordError(
        "image_resolution must be [height, width], a string, or null",
        field="image_resolution",
        record_index=record_index,
    )


def normalize_record(
    record: Mapping[str, Any], *, record_index: int | None = None
) -> list[dict[str, Any]]:
    """Return four normalized rows, or raise ``TraceRecordError``.

    Required input fields: ``capture_time`` (seconds), ``server_durations``
    with all three stage keys (seconds), and ``duration_s`` (seconds).
    Optional fields: ``payload_bytes``, ``image_resolution``, ``chunk_size``,
    ``n_action_steps``.  Extra fields are ignored.
    """
    if not isinstance(record, Mapping):
        raise TraceRecordError(
            "expected a JSON object", record_index=record_index
        )

    capture_time = _number(
        record.get("capture_time"), "capture_time", record_index=record_index
    )

    durations = record.get("server_durations")
    if not isinstance(durations, Mapping):
        raise TraceRecordError(
            "expected an object with preprocessing/policy/postprocessing seconds",
            field="server_durations",
            record_index=record_index,
        )
    stage_seconds: dict[str, float] = {}
    for stage in REQUIRED_STAGES:
        if stage not in durations:
            raise TraceRecordError(
                "missing required stage", field=stage, record_index=record_index
            )
        stage_seconds[stage] = _number(
            durations[stage],
            f"server_durations.{stage}",
            record_index=record_index,
        )

    total_seconds = _number(
        record.get("duration_s"), "duration_s", record_index=record_index
    )
    payload_bytes = _optional_int(
        record.get("payload_bytes"), "payload_bytes", record_index=record_index
    )
    image_resolution = _optional_resolution(
        record.get("image_resolution"), record_index=record_index
    )
    chunk_size = _optional_int(
        record.get("chunk_size"), "chunk_size", record_index=record_index
    )
    n_action_steps = _optional_int(
        record.get("n_action_steps"), "n_action_steps", record_index=record_index
    )

    def row(stage: str, seconds: float) -> dict[str, Any]:
        # Insertion order is the documented output order.
        return {
            "timestamp_s": capture_time,
            "stage": stage,
            "duration_ms": seconds * 1000.0,
            "payload_bytes": payload_bytes,
            "image_resolution": list(image_resolution)
            if isinstance(image_resolution, list)
            else image_resolution,
            "chunk_size": chunk_size,
            "n_action_steps": n_action_steps,
        }

    return [row(stage, stage_seconds[stage]) for stage in REQUIRED_STAGES] + [
        row("total", total_seconds)
    ]


def read_records(stream: TextIO) -> Iterator[Mapping[str, Any]]:
    """Parse one JSON object per non-blank line, with line-numbered errors."""
    for line_number, line in enumerate(stream, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TraceRecordError(
                f"line {line_number}: invalid JSON: {exc.msg}"
            ) from exc
        if not isinstance(value, Mapping):
            raise TraceRecordError(
                f"line {line_number}: expected a JSON object"
            )
        yield value


def normalize_records(
    records: Iterable[Mapping[str, Any]],
) -> Iterator[dict[str, Any]]:
    """Yield normalized rows in record order and fixed stage order."""
    for record_index, record in enumerate(records, start=1):
        yield from normalize_record(record, record_index=record_index)


def write_rows(rows: Iterable[Mapping[str, Any]], stream: TextIO) -> int:
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


def convert(input_stream: TextIO, output_stream: TextIO) -> int:
    """Validate and normalize the whole input before writing any row.

    Buffering first makes the CLI fail closed: a bad record produces no partial
    output file or partial stdout trace.
    """
    rows = list(normalize_records(read_records(input_stream)))
    return write_rows(rows, output_stream)


def instrumentation_snippet() -> str:
    """Return the documented patch for LeRobot's ``policy_runner.py``.

    The string is documentation, not an importable LeRobot module.  It shows a
    roughly 30-line change that writes one LeRobot-shaped record per completed
    prediction when ``LEROBOT_TRACE_JSONL`` is set.
    """
    return INSTRUMENTATION_SNIPPET


INSTRUMENTATION_SNIPPET = '''\
# Apply to a LeRobot checkout, not to this repository.
# src/lerobot/inference/policy_runner.py: add at module scope after the imports.
import json as _trace_json
import os as _trace_os
import time as _trace_time

_TRACE_JSONL = _trace_os.environ.get("LEROBOT_TRACE_JSONL", "")

def _trace_chunk(observation, chunk, features):
    """Write one record per completed prediction when LEROBOT_TRACE_JSONL is set."""
    if not _TRACE_JSONL:
        return
    rgb = next((f.shape for f in features if f.kind == "rgb"), None)
    stages = chunk.server_durations
    record = {
        "capture_time": observation.capture_time,
        "server_durations": {
            "preprocessing": stages["preprocessing"],
            "policy": stages["policy"],
            "postprocessing": stages["postprocessing"],
        },
        # End-to-end arrival-to-result on the same monotonic clock.
        "duration_s": _trace_time.perf_counter() - observation.capture_time,
        # Decoded RGB bytes, not Zenoh wire bytes or JPEG q90 sizes.
        "payload_bytes": sum(
            int(observation.features[f.name].nbytes) for f in features if f.kind == "rgb"
        ),
        "image_resolution": [int(rgb[0]), int(rgb[1])] if rgb is not None else None,
        "chunk_size": int(len(chunk.canonical_actions)),
        "n_action_steps": int(chunk.execution_steps),
    }
    with open(_TRACE_JSONL, "a", encoding="utf-8") as sink:
        sink.write(_trace_json.dumps(record, separators=(",", ":")) + "\\n")

# In PolicyRunner.predict, replace the final `return ActionChunk(...)` with:
        chunk = ActionChunk(
            model_actions=model,
            canonical_actions=canonical,
            provenance=provenance or ActionProvenance(
                capture_time=observation.capture_time,
                task=observation.task,
                task_version=observation.task_version,
                observation_id=observation.observation_id,
            ),
            execution_steps=len(canonical),
            server_durations={
                "preprocessing": preprocessed_at - started,
                "policy": prediction.predicted_at - preprocessed_at,
                "postprocessing": finished - prediction.predicted_at,
            },
        )
        _trace_chunk(observation, chunk, self.capabilities.features)
        return chunk
'''


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lerobot_trace_dump.py",
        description=(
            "Normalize LeRobot inference records into preprocessing/policy/"
            "postprocessing/total JSONL rows."
        ),
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--input",
        type=Path,
        metavar="PATH",
        help="read JSONL records from PATH (default: stdin)",
    )
    source.add_argument(
        "--stdin",
        action="store_true",
        help="read JSONL records from stdin (the default)",
    )
    sink = parser.add_mutually_exclusive_group()
    sink.add_argument(
        "--output",
        type=Path,
        metavar="PATH",
        help="write JSONL rows to PATH (default: stdout)",
    )
    sink.add_argument(
        "--stdout",
        action="store_true",
        help="write JSONL rows to stdout (the default)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.input is not None:
            with args.input.open("r", encoding="utf-8") as source:
                rows = list(normalize_records(read_records(source)))
        else:
            rows = list(normalize_records(read_records(sys.stdin)))

        if args.output is not None:
            with args.output.open("w", encoding="utf-8") as sink:
                write_rows(rows, sink)
        else:
            write_rows(rows, sys.stdout)
    except TraceRecordError as exc:
        print(f"lerobot_trace_dump: {exc}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError) as exc:
        print(f"lerobot_trace_dump: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
