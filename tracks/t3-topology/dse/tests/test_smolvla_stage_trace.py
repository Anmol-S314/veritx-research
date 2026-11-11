"""Tests for the SmolVLA vision/prefill/denoise stage trace tool."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "smolvla_stage_trace.py"
TRACE = Path(__file__).resolve().parents[2] / "data" / "lerobot" / "smolvla_vla_trace.jsonl"


def _load_tool():
    spec = importlib.util.spec_from_file_location("smolvla_stage_trace", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


trace = _load_tool()

METADATA = {
    "payload_bytes": 2359296,
    "image_resolution": [256, 256],
    "chunk_size": 50,
    "n_action_steps": 50,
    "num_denoise_steps": 10,
}


def _row(stage: str, duration_ms: float, *, timestamp_s: float = 123.0, **meta):
    row = {
        "timestamp_s": timestamp_s,
        "stage": stage,
        "duration_ms": duration_ms,
    }
    row.update(METADATA)
    row.update(meta)
    return row


def _valid_rows(*, timestamp_s: float = 123.0):
    rows = [
        _row("vision_encoder", 100.0, timestamp_s=timestamp_s),
        _row("vlm_prefill", 200.0, timestamp_s=timestamp_s),
    ]
    rows.extend(
        _row(f"action_denoise_step_{index}", 10.0, timestamp_s=timestamp_s)
        for index in range(10)
    )
    rows.extend(
        [
            _row("action_denoise_total", 100.0, timestamp_s=timestamp_s),
            _row("policy_total", 450.0, timestamp_s=timestamp_s),
            _row("other", 50.0, timestamp_s=timestamp_s),
        ]
    )
    return rows


def _stages(rows):
    return [row["stage"] for row in rows]


def test_valid_trace_normalizes_in_fixed_stage_order():
    rows = list(reversed(_valid_rows()))

    groups = trace.validate_rows(rows)
    assert len(groups) == 1
    assert _stages(groups[0]) == list(trace.STAGE_ORDER)

    normalized = trace.normalize_rows(rows)
    assert _stages(normalized) == list(trace.STAGE_ORDER)
    assert [row["duration_ms"] for row in normalized] == [
        100.0,
        200.0,
        *([10.0] * 10),
        100.0,
        450.0,
        50.0,
    ]
    assert {row["timestamp_s"] for row in normalized} == {123.0}
    assert all(row["payload_bytes"] == 2359296 for row in normalized)
    assert all(row["image_resolution"] == [256, 256] for row in normalized)
    assert all(row["chunk_size"] == 50 for row in normalized)
    assert all(row["n_action_steps"] == 50 for row in normalized)
    assert all(row["num_denoise_steps"] == 10 for row in normalized)


def test_multiple_groups_are_sorted_by_timestamp():
    newer = _valid_rows(timestamp_s=200.0)
    older = _valid_rows(timestamp_s=100.0)

    normalized = trace.normalize_rows([*newer, *older])

    assert [row["timestamp_s"] for row in normalized[::15]] == [100.0, 200.0]
    assert _stages(normalized[:15]) == list(trace.STAGE_ORDER)


def test_missing_stage_fails_closed():
    rows = _valid_rows()
    rows = [row for row in rows if row["stage"] != "action_denoise_step_5"]

    with pytest.raises(trace.TraceError) as excinfo:
        trace.validate_rows(rows)

    assert excinfo.value.field == "action_denoise_step_5"
    assert "missing required stage" in str(excinfo.value)


def test_negative_duration_fails_closed():
    rows = _valid_rows()
    for row in rows:
        if row["stage"] == "action_denoise_step_3":
            row["duration_ms"] = -1.0

    with pytest.raises(trace.TraceError) as excinfo:
        trace.validate_rows(rows)

    assert excinfo.value.field == "duration_ms"
    assert ">= 0" in str(excinfo.value)


def test_denoise_total_sum_mismatch_fails_closed():
    rows = _valid_rows()
    for row in rows:
        if row["stage"] == "action_denoise_total":
            row["duration_ms"] = 101.0

    with pytest.raises(trace.TraceError) as excinfo:
        trace.validate_rows(rows)

    assert excinfo.value.field == "action_denoise_total"
    assert "does not equal the sum" in str(excinfo.value)


def test_policy_total_sum_mismatch_fails_closed():
    rows = _valid_rows()
    for row in rows:
        if row["stage"] == "policy_total":
            row["duration_ms"] = 460.0

    with pytest.raises(trace.TraceError) as excinfo:
        trace.validate_rows(rows)

    assert excinfo.value.field == "policy_total"
    assert "tolerance" in str(excinfo.value)


def test_sum_tolerance_is_stated_and_enforced():
    rows = _valid_rows()
    for row in rows:
        if row["stage"] == "policy_total":
            row["duration_ms"] = 450.005
    trace.validate_rows(rows)  # 0.005 ms is inside the 0.01 ms tolerance

    for row in rows:
        if row["stage"] == "policy_total":
            row["duration_ms"] = 450.02
    with pytest.raises(trace.TraceError):
        trace.validate_rows(rows)


def test_metadata_must_be_uniform_within_group():
    rows = _valid_rows()
    for row in rows:
        if row["stage"] == "vlm_prefill":
            row["chunk_size"] = 25

    with pytest.raises(trace.TraceError) as excinfo:
        trace.validate_rows(rows)

    assert excinfo.value.field == "chunk_size"
    assert "not uniform" in str(excinfo.value)


def test_cli_round_trip_is_idempotent(tmp_path):
    source = tmp_path / "input.jsonl"
    output = tmp_path / "output.jsonl"
    output_again = tmp_path / "output-again.jsonl"
    rows = list(reversed(_valid_rows()))
    source.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "normalize",
            "--input",
            str(source),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    normalized = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(normalized) == 15
    assert _stages(normalized) == list(trace.STAGE_ORDER)
    assert [row["timestamp_s"] for row in normalized] == [123.0] * 15

    checked = subprocess.run(
        [sys.executable, str(TOOL), "validate", "--input", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr
    assert "valid: 1 group(s), 15 row(s)" in checked.stdout

    again = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "normalize",
            "--input",
            str(output),
            "--output",
            str(output_again),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert again.returncode == 0, again.stderr
    assert output_again.read_bytes() == output.read_bytes()


def test_cli_invalid_trace_writes_no_partial_output(tmp_path):
    source = tmp_path / "input.jsonl"
    output = tmp_path / "output.jsonl"
    rows = [
        row
        for row in _valid_rows()
        if row["stage"] != "action_denoise_step_9"
    ]
    source.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "normalize",
            "--input",
            str(source),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "action_denoise_step_9" in completed.stderr
    assert not output.exists()


def test_committed_trace_parses_and_has_ten_denoise_steps():
    with TRACE.open("r", encoding="utf-8") as source:
        rows = trace.read_jsonl(source)
    groups = trace.validate_rows(rows)

    assert len(groups) == 1
    assert _stages(groups[0]) == list(trace.STAGE_ORDER)

    denoise_rows = [
        row for row in rows if row["stage"].startswith("action_denoise_step_")
    ]
    assert len(denoise_rows) == 10
    assert _stages(denoise_rows) == list(trace.DENOISE_STAGES)
    assert all(row["num_denoise_steps"] == 10 for row in denoise_rows)
    assert all(row["duration_ms"] >= 0 for row in rows)
    assert all(row["chunk_size"] == 50 for row in rows)
    assert all(row["n_action_steps"] == 50 for row in rows)
    assert all(row["image_resolution"] == [256, 256] for row in rows)
    assert all(row["payload_bytes"] == 2359296 for row in rows)

    by_stage = {row["stage"]: row for row in groups[0]}
    assert by_stage["policy_total"]["duration_ms"] > 0
    assert by_stage["other"]["duration_ms"] >= 0
