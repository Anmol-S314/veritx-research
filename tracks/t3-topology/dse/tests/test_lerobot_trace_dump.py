"""Synthetic tests for the standalone LeRobot trace normalizer."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "lerobot_trace_dump.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("lerobot_trace_dump", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


trace = _load_tool()


def _record(**overrides):
    record = {
        "capture_time": 123.5,
        "server_durations": {
            "preprocessing": 0.0125,
            "policy": 0.030,
            "postprocessing": 0.005,
        },
        "duration_s": 0.050,
        "payload_bytes": 921600,
        "image_resolution": [480, 640],
        "chunk_size": 50,
        "n_action_steps": 25,
    }
    record.update(overrides)
    return record


def test_valid_record_emits_four_rows_in_stage_order():
    rows = trace.normalize_record(_record())

    assert [row["stage"] for row in rows] == [
        "preprocessing",
        "policy",
        "postprocessing",
        "total",
    ]
    assert [row["duration_ms"] for row in rows] == [12.5, 30.0, 5.0, 50.0]
    assert {row["timestamp_s"] for row in rows} == {123.5}
    assert {row["payload_bytes"] for row in rows} == {921600}
    assert all(row["image_resolution"] == [480, 640] for row in rows)
    assert {row["chunk_size"] for row in rows} == {50}
    assert {row["n_action_steps"] for row in rows} == {25}
    assert list(rows[0]) == [
        "timestamp_s",
        "stage",
        "duration_ms",
        "payload_bytes",
        "image_resolution",
        "chunk_size",
        "n_action_steps",
    ]


def test_missing_stage_fails_closed():
    record = _record()
    del record["server_durations"]["policy"]

    with pytest.raises(trace.TraceRecordError) as excinfo:
        trace.normalize_record(record)

    assert excinfo.value.field == "policy"
    assert "missing required stage" in str(excinfo.value)


def test_negative_duration_fails_closed():
    record = _record()
    record["server_durations"]["preprocessing"] = -0.001

    with pytest.raises(trace.TraceRecordError) as excinfo:
        trace.normalize_record(record)

    assert excinfo.value.field == "server_durations.preprocessing"
    assert ">= 0" in str(excinfo.value)


def test_optional_fields_absent_become_nulls():
    minimal = _record()
    for key in ("payload_bytes", "image_resolution", "chunk_size", "n_action_steps"):
        del minimal[key]

    rows = trace.normalize_record(minimal)
    assert len(rows) == 4
    for row in rows:
        assert row["payload_bytes"] is None
        assert row["image_resolution"] is None
        assert row["chunk_size"] is None
        assert row["n_action_steps"] is None
        assert row["duration_ms"] >= 0


def test_cli_round_trip_through_jsonl_files(tmp_path):
    source = tmp_path / "records.jsonl"
    output = tmp_path / "rows.jsonl"
    records = [_record(), _record(capture_time=124.0, duration_s=0.060)]
    source.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(TOOL), "--input", str(source), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 8
    assert [row["stage"] for row in rows] == [
        "preprocessing",
        "policy",
        "postprocessing",
        "total",
    ] * 2
    assert [row["timestamp_s"] for row in rows[::4]] == [123.5, 124.0]
    assert [row["duration_ms"] for row in rows[:4]] == [12.5, 30.0, 5.0, 50.0]


def test_cli_invalid_record_writes_no_partial_output(tmp_path):
    source = tmp_path / "records.jsonl"
    output = tmp_path / "rows.jsonl"
    bad = _record()
    del bad["server_durations"]["postprocessing"]
    source.write_text(
        json.dumps(_record()) + "\n" + json.dumps(bad) + "\n", encoding="utf-8"
    )

    completed = subprocess.run(
        [sys.executable, str(TOOL), "--input", str(source), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "postprocessing" in completed.stderr
    assert not output.exists()


def test_cli_stdin_stdout_filter():
    source = json.dumps(_record()) + "\n"

    completed = subprocess.run(
        [sys.executable, str(TOOL), "--stdin", "--stdout"],
        input=source,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    rows = [json.loads(line) for line in completed.stdout.splitlines()]
    assert [row["stage"] for row in rows] == [
        "preprocessing",
        "policy",
        "postprocessing",
        "total",
    ]


def test_instrumentation_snippet_documents_policy_runner_hooks():
    snippet = trace.instrumentation_snippet()

    for stage in ("preprocessing", "policy", "postprocessing"):
        assert f'"{stage}"' in snippet
    assert '"capture_time"' in snippet
    assert "policy_runner.py" in snippet
    assert "server_durations" in snippet
