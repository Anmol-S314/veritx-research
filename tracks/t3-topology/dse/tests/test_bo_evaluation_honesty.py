"""Regression tests: BO evaluation honesty (§4.1) and traffic refusal (§4.2).

A failed BookSim evaluation must raise EvaluationFailed with the real
reason — never return 1000.0, 1e9, NaN, or any other plausible-looking
number. Missing or demand-less traffic must refuse (SynthesisTrafficError),
never invent an allreduce.

No engine run here: the binary is stubbed (/bin/false, /bin/echo, a small
printing script) or subprocess is monkeypatched, so every case is fast.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from veritx_dse.synthesis import bo_synthesizer as bo
from veritx_dse.synthesis.traffic import SynthesisTrafficError
import veritx_dse.core.paths as paths


@pytest.fixture(autouse=True)
def _matrix_mode(monkeypatch):
    """Force matrix mode: the trace global would bypass T entirely."""
    monkeypatch.setattr(bo, "_trace_path", None, raising=False)


def _connected_pair():
    return {0: {1}, 1: {0}}


def _matrix():
    import numpy as np
    return np.array([[0.0, 1.0], [1.0, 0.0]])


def test_booksim_nonzero_exit_is_evaluation_failed(monkeypatch, tmp_path):
    """BookSim fails -> EVALUATION_FAILED, never a numeric fallback."""
    monkeypatch.setattr(paths, "BOOKSIM_BIN", Path("/bin/false"))
    with pytest.raises(bo.EvaluationFailed, match="exit 1"):
        bo.evaluate_topology(_connected_pair(), _matrix(), str(tmp_path))


def test_booksim_missing_binary_is_evaluation_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(
        paths, "BOOKSIM_BIN", Path("/nonexistent/booksim-missing"))
    with pytest.raises(bo.EvaluationFailed, match="failed to launch"):
        bo.evaluate_topology(_connected_pair(), _matrix(), str(tmp_path))


def test_output_without_latency_line_is_evaluation_failed(
        monkeypatch, tmp_path):
    """/bin/echo exits 0 but emits no latency figure -> EVALUATION_FAILED."""
    monkeypatch.setattr(paths, "BOOKSIM_BIN", Path("/bin/echo"))
    with pytest.raises(bo.EvaluationFailed, match="no 'Packet latency average'"):
        bo.evaluate_topology(_connected_pair(), _matrix(), str(tmp_path))


def test_booksim_timeout_is_evaluation_failed(monkeypatch, tmp_path):
    """A hung BookSim run is a failed evaluation, not a 60-second mystery."""
    def _hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=60)
    monkeypatch.setattr(subprocess, "run", _hang)
    with pytest.raises(bo.EvaluationFailed, match="[Tt]imed out"):
        bo.evaluate_topology(_connected_pair(), _matrix(), str(tmp_path))


def test_disconnected_candidate_is_evaluation_failed(tmp_path):
    """Disconnected graphs never enter the objective, even as 1e9."""
    with pytest.raises(bo.EvaluationFailed, match="disconnected"):
        bo.evaluate_topology({0: set(), 1: set()}, _matrix(), str(tmp_path))


def test_successful_run_returns_measured_latency(monkeypatch, tmp_path):
    """The happy path still returns the parsed figure (no behavior change)."""
    script = tmp_path / "fake-booksim.sh"
    script.write_text("#!/bin/sh\n"
                      "echo 'Packet latency average = 12.5'\n")
    script.chmod(0o755)
    monkeypatch.setattr(paths, "BOOKSIM_BIN", script)
    assert bo.evaluate_topology(
        _connected_pair(), _matrix(), str(tmp_path)) == 12.5


def test_failed_evaluation_is_not_a_plausible_number(monkeypatch, tmp_path):
    """Belt and braces: none of the failure modes may return 1000.0 or 1e9."""
    monkeypatch.setattr(paths, "BOOKSIM_BIN", Path("/bin/false"))
    with pytest.raises(bo.EvaluationFailed):
        bo.evaluate_topology(_connected_pair(), _matrix(), str(tmp_path))
    monkeypatch.setattr(paths, "BOOKSIM_BIN", Path("/bin/echo"))
    with pytest.raises(bo.EvaluationFailed):
        bo.evaluate_topology(_connected_pair(), _matrix(), str(tmp_path))


def _events(collectives):
    return {"meta": {"num_tiles": 2}, "collectives": collectives}


def test_missing_traffic_source_refuses(tmp_path):
    with pytest.raises(SynthesisTrafficError, match="not found or unreadable"):
        bo.load_study_events(str(tmp_path / "no-such-file.json"))


def test_malformed_traffic_source_refuses(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(SynthesisTrafficError, match="not an events model"):
        bo.load_study_events(str(bad))


def test_events_model_without_collectives_refuses(tmp_path):
    bare = tmp_path / "bare.json"
    bare.write_text(json.dumps({"meta": {"num_tiles": 2}}))
    with pytest.raises(SynthesisTrafficError, match="no collectives"):
        bo.load_study_events(str(bare))


def test_demand_less_events_model_refuses(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps(_events([])))
    with pytest.raises(SynthesisTrafficError, match="no collectives"):
        bo.load_study_events(str(empty))


def test_real_events_model_loads(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_events([
        {"tensor": "t", "participants": [0, 1],
         "size_bytes": 8192, "priority": 2, "pattern": "allreduce"},
    ])))
    events = bo.load_study_events(str(good))
    assert events["collectives"][0]["tensor"] == "t"


def test_evaluation_failed_is_an_exception_with_reason():
    err = bo.EvaluationFailed("booksim exit 1 in runs/x")
    assert isinstance(err, Exception)
    assert "booksim exit 1" in str(err)


if __name__ == "__main__":
    sys.exit("run with: pytest tests/test_bo_evaluation_honesty.py -q")
