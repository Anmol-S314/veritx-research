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
    for name in ("_n_nodes", "_T_matrix", "_events", "_xy", "_scorer",
                 "_booksim_workdir", "_best_params", "_best_lat", "_eval_count"):
        monkeypatch.setattr(bo, name, getattr(bo, name))


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


@pytest.mark.parametrize("update", [
    {"participants": [0, 99]}, {"participants": [99, 0]},
    {"participants": [0, True]}, {"participants": [0, 0]},
    {"participants": [0]}, {"participants": "01"},
    {"size_bytes": 0}, {"size_bytes": True}, {"size_bytes": None},
    {"pattern": "broadcast"}, {"pattern": None}, {"priority": "1"},
])
def test_invalid_analytical_demand_is_typed_refusal(update):
    from veritx_dse.synthesis.event_objective import score_topology
    collective = {"tensor": "t", "participants": [0, 1],
                  "size_bytes": 64, "pattern": "allreduce", **update}
    with pytest.raises(SynthesisTrafficError):
        score_topology(_connected_pair(), [(0, 0), (1, 0)], _events([collective]))


def test_unreachable_analytical_candidate_is_not_numeric_success():
    from veritx_dse.synthesis.event_objective import score_topology
    with pytest.raises(SynthesisTrafficError, match="unreachable"):
        score_topology({0: set(), 1: set()}, [(0, 0), (1, 0)], _events([
            {"participants": [0, 1], "size_bytes": 64, "pattern": "allreduce"}]))


def test_analytical_refusal_does_not_become_bo_winner(monkeypatch):
    monkeypatch.setattr(bo, "generate_topology", lambda *a, **kw: _connected_pair())
    monkeypatch.setattr(bo, "_scorer", "analytical")
    monkeypatch.setattr(bo, "_n_nodes", 2)
    monkeypatch.setattr(bo, "_xy", [(0, 0), (1, 0)])
    monkeypatch.setattr(bo, "_events", _events([
        {"participants": [0, 99], "size_bytes": 64, "pattern": "allreduce"}]))
    monkeypatch.setattr(bo, "_best_lat", float("inf"))
    monkeypatch.setattr(bo, "_best_params", None)
    with pytest.raises(bo.EvaluationFailed, match="in-namespace"):
        bo.objective([4, 2, 4, 0.5, 0.5])
    assert bo._best_params is None
    assert bo._best_lat == float("inf")


def test_analytical_success_is_labelled_cost_not_latency(monkeypatch, capsys):
    from veritx_dse.synthesis.event_objective import score_topology
    events = _events([{"participants": [0, 1], "size_bytes": 64,
                       "pattern": "allreduce"}])
    adj, xy = _connected_pair(), [(0, 0), (1, 0)]
    expected, _ = score_topology(adj, xy, events)
    assert expected > 0
    monkeypatch.setattr(bo, "generate_topology", lambda *a, **kw: adj)
    for name, value in [("_scorer", "analytical"), ("_n_nodes", 2),
                        ("_xy", xy), ("_events", events),
                        ("_best_lat", float("inf")), ("_best_params", None)]:
        monkeypatch.setattr(bo, name, value)
    assert bo.objective([4, 2, 4, 0.5, 0.5]) == expected / 1e9
    assert "cost_cycles_x_bytes / 1e9=" in capsys.readouterr().out


@pytest.mark.parametrize("nodes", [0, -1, 3, 6])
def test_bo_main_refuses_invalid_node_counts_before_scoring(monkeypatch, nodes):
    monkeypatch.setattr(sys, "argv", ["bo", "--nodes", str(nodes)])
    with pytest.raises(SystemExit) as error:
        bo.main()
    assert error.value.code == 2


@pytest.mark.parametrize("scorer", ["analytical", "booksim"])
def test_main_excludes_failed_candidates_without_a_winner(monkeypatch, tmp_path, scorer):
    source = tmp_path / ("input.trace" if scorer == "booksim" else "input.json")
    source.write_text("0 0 0 1 64\n" if scorer == "booksim" else json.dumps(_events([
        {"participants": [0, 99], "size_bytes": 64, "pattern": "allreduce"}])))
    told = []
    class Optimizer:
        def __init__(self, *args, **kwargs):
            pass
        def ask(self):
            return [4, 2, 4, 0.5, 0.5]
        def tell(self, *args):
            told.append(args)
    monkeypatch.setattr(bo, "Optimizer", Optimizer)
    monkeypatch.setattr(bo, "_best_params", None)
    monkeypatch.setattr(bo, "_best_lat", float("inf"))
    monkeypatch.setattr(bo, "generate_topology", lambda *a, **kw: {
        0: {1}, 1: {0, 2}, 2: {1, 3}, 3: {2}})
    if scorer == "booksim":
        def fail(*args):
            raise bo.EvaluationFailed("bounded fake engine failure")
        monkeypatch.setattr(bo, "evaluate_topology", fail)
        monkeypatch.setattr(bo, "load_study_events", lambda *a: pytest.fail(
            "BookSim trace replay must not parse analytical JSON"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["bo", "--traffic", str(source), "--nodes", "4",
                                      "--scorer", scorer, "--iters", "1"])
    with pytest.raises(SystemExit) as error:
        bo.main()
    assert error.value.code == 1
    assert told == []
    result = json.loads((tmp_path / "runs/booksim/bo_results_N4.json").read_text())
    assert result["all_evals"] == []
    assert len(result["failed_evals"]) == 10
    assert result["best_params"] is None
    assert not (tmp_path / "runs/booksim/topo.anynet").exists()
    if scorer == "analytical":
        assert "best_latency" not in result
        assert result["best_objective"] is None
        assert result["objective_unit"] == "cycles_x_bytes / 1e9"
    else:
        assert result["best_latency"] is None
        assert result["objective_unit"] == "latency_cycles"


def test_evaluation_failed_is_an_exception_with_reason():
    err = bo.EvaluationFailed("booksim exit 1 in runs/x")
    assert isinstance(err, Exception)
    assert "booksim exit 1" in str(err)


if __name__ == "__main__":
    sys.exit("run with: pytest tests/test_bo_evaluation_honesty.py -q")
