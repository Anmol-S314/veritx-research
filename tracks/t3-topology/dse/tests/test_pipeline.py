"""Contract tests for veritx_dse.cli.pipeline — orchestration layer.

run_compare's happy path is exercised live through the CLI (test_integration);
here we pin the rest: aggregation/printing, run history, results viewer, run
diffing, and LaTeX generation — all with real files in a temp runs/ tree.
"""
import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.cli import pipeline as pl
from veritx_dse.core.logging import Ctx


@pytest.fixture
def runs(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "RUNS_DIR", tmp_path)
    return tmp_path


# ── compare: aggregation, error branches, tables ─────────────────────────

class TestRunCompare:
    def test_timeout_and_booksim_error_branches_recorded(self, tmp_path, monkeypatch):
        from veritx_dse.cli.pipeline import TimeoutError as PLTimeout, BookSimError
        calls = {"n": 0}

        def fake_eval(ctx, topo, trace, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PLTimeout("sim timed out")
            raise BookSimError("booksim exploded")

        monkeypatch.setattr(pl, "run_topology_eval", fake_eval)
        topos = [("meshA", type("T", (), {"backend": "mesh", "params": {"k": 4, "n": 2}, "edges": lambda s: 4})()),
                 ("meshB", type("T", (), {"backend": "mesh", "params": {"k": 4, "n": 2}, "edges": lambda s: 6})())]
        res = pl.run_compare(Ctx(verbosity=0), "t.trace", topos, seeds=1)
        assert res.results[0]["error"] == "timeout"
        assert "exploded" in res.results[1]["error"]
        # Failed candidates stay VISIBLE as agg rows with the error recorded
        # (PR follow-up: silent exclusion hid exactly the runs that
        # invalidate a comparison); the winner printer ignores them.
        assert len(res.summary) == 2
        assert all("error" in s and s["n"] == 0 and "mean" not in s
                   for s in res.summary)
        assert {s["error"] for s in res.summary} == {"timeout", "booksim exploded"}

    def test_summary_aggregates_multi_seed(self, monkeypatch):
        def fake_eval(ctx, topo, trace, seed=None, **kw):
            return {"latency": 100.0 + (seed % 2) * 10, "nodes": 4, "edges": 4, "unstable": False}
        monkeypatch.setattr(pl, "run_topology_eval", fake_eval)
        topo = type("T", (), {"backend": "mesh", "params": {"k": 4, "n": 2}, "edges": lambda s: 4})()
        res = pl.run_compare(Ctx(verbosity=0), "t.trace", [("m", topo)], seeds=2, seed_base=42)
        s = res.summary[0]
        assert s["n"] == 2 and s["mean"] == 105.0 and s["max"] - s["min"] == 10
        assert res.seeds == [42, 43]


class TestPrintTables:
    def test_compare_table_stable_and_unstable(self, runs, capsys):
        res = pl.CompareResult(trace="t.trace", seeds=[42],
                               results=[], summary=[
            {"name": "mesh", "nodes": 4, "edges": 4, "mean": 10.0, "std": 0.5,
             "min": 9.5, "max": 10.5, "n": 2, "n_unstable": 0},
            {"name": "torus", "nodes": 4, "edges": 8, "mean": 12.0, "std": 3.0,
             "min": 9.0, "max": 15.0, "n": 2, "n_unstable": 1},
        ])
        pl.print_compare_table(Ctx(verbosity=1), res)
        out = capsys.readouterr().out
        assert "Unstable" in out and "1/2" in out and "Winner: mesh" in out
        # Persistence moved to cmd_compare (results/compare/<ts>_seed<n>/);
        # printing is side-effect-free so callers can't double-save.

    def test_compare_table_stable_path_has_t_stat(self, runs, capsys):
        res = pl.CompareResult(trace="t.trace", seeds=[42, 43], results=[], summary=[
            {"name": "a", "nodes": 4, "edges": 4, "mean": 10.0, "std": 0.1,
             "min": 9.9, "max": 10.1, "n": 2, "n_unstable": 0},
            {"name": "b", "nodes": 4, "edges": 4, "mean": 14.0, "std": 0.1,
             "min": 13.9, "max": 14.1, "n": 2, "n_unstable": 0},
        ])
        pl.print_compare_table(Ctx(verbosity=1), res)
        out = capsys.readouterr().out
        assert "Winner: a" in out and "faster" in out and "t=" in out

    def test_sweep_table_both_sim_types(self, capsys):
        results = [{"name": "mesh", "nodes": 4, "edges": 4, "latency": 20.5, "hops": 1.5},
                   {"name": "bad", "nodes": 0, "edges": 0, "error": "timeout"}]
        pl.print_sweep_table(Ctx(verbosity=1), results, "latency")
        out = capsys.readouterr().out
        assert "Latency" in out and "Best: mesh" in out and "Spread:" in out
        pl.print_sweep_table(Ctx(verbosity=1), results, "throughput")
        assert "Throughput" in capsys.readouterr().out


# ── run history / results / diff ─────────────────────────────────────────

def _mk_run(exp, name, manifest=None, extra=None):
    d = exp / name
    d.mkdir(parents=True)
    if manifest is not None:
        (d / "manifest.json").write_text(json.dumps(manifest))
    for fname, content in (extra or {}).items():
        (d / fname).write_text(content)
    return d


class TestListRuns:
    def test_missing_experiments_dir_fails(self, runs, capsys):
        pl.list_runs(Ctx(verbosity=0))
        assert "No experiments directory yet" in capsys.readouterr().err

    def test_lists_and_inspects_runs(self, runs, capsys):
        exp = runs / "experiments"
        _mk_run(exp, "run_b", manifest={
            "timestamp": "2026-09-09T10:00:00", "duration_s": 12,
            "model": "/x/llama.json", "eval": {"latency": 55.5}, "cert": "ok"})
        _mk_run(exp, "run_a")                       # no manifest → "?" row
        pl.list_runs(Ctx(verbosity=1))
        out = capsys.readouterr().out
        assert "run_b" in out and "55.5c" in out and "run_a" in out

        pl.list_runs(Ctx(verbosity=1), run_id="run_b")
        out = capsys.readouterr().out
        assert "Run: run_b" in out and "manifest.json" in out

    def test_run_id_not_found(self, runs, capsys):
        (runs / "experiments").mkdir()
        pl.list_runs(Ctx(verbosity=0), run_id="ghost")
        assert "Run not found" in capsys.readouterr().err

    def test_corrupt_manifest_inspect_does_not_crash(self, runs, capsys):
        exp = runs / "experiments"
        _mk_run(exp, "run_x", manifest=None)
        (exp / "run_x" / "manifest.json").write_text("{corrupt")
        pl.list_runs(Ctx(verbosity=1), run_id="run_x")
        assert "Run: run_x" in capsys.readouterr().out


class TestShowResults:
    def test_missing_dir_and_no_results(self, runs, capsys):
        pl.show_results(Ctx(verbosity=0))
        assert "No booksim results yet" in capsys.readouterr().err
        (runs / "booksim").mkdir()
        pl.show_results(Ctx(verbosity=0))
        assert "No results in" in capsys.readouterr().err

    def test_renders_all_three_json_shapes(self, runs, capsys):
        bs = runs / "booksim"
        bs.mkdir()
        (bs / "compare_x.json").write_text(json.dumps(
            {"summary": [{"name": "mesh", "mean": 10.0, "std": 0.2,
                          "min": 9.8, "max": 10.2, "n": 2}]}))
        (bs / "sweep_y.json").write_text(json.dumps(
            [{"name": "torus", "latency": 12.0, "hops": 2}]))
        (bs / "pareto_z.json").write_text(json.dumps({"weird": "shape"}))
        pl.show_results(Ctx(verbosity=0))
        out = capsys.readouterr().out
        assert "compare_x" in out and "10.00c" in out
        assert "sweep_y" in out and "12.00c" in out
        assert "pareto_z" in out


class TestDiffRuns:
    def test_needs_two_runs(self, runs, capsys):
        pl.diff_runs(Ctx(verbosity=0))
        assert "No experiments yet" in capsys.readouterr().err
        exp = runs / "experiments"
        _mk_run(exp, "only_one")
        pl.diff_runs(Ctx(verbosity=0))
        assert "Need at least 2 runs" in capsys.readouterr().err

    def test_diff_reports_latency_delta_and_changed_keys(self, runs, capsys):
        exp = runs / "experiments"
        _mk_run(exp, "runA", manifest={"eval": {"latency": 10.0}, "model": "a.json"})
        _mk_run(exp, "runB", manifest={"eval": {"latency": 12.5}, "model": "b.json"},
                extra={"only_b.txt": "x"})
        _mk_run(exp, "runC", manifest={}, extra={"only_c.txt": "x"})
        pl.diff_runs(Ctx(verbosity=1), "runA", "runB")
        out = capsys.readouterr().out
        assert "Diff: runA vs runB" in out
        assert "eval.latency" in out and "12.50c" in out and "+2.50c" in out
        assert "model" in out and "CHANGED" in out
        assert "only_b.txt" in out

    def test_diff_missing_run_id(self, runs, capsys):
        exp = runs / "experiments"
        _mk_run(exp, "runA"); _mk_run(exp, "runB")
        pl.diff_runs(Ctx(verbosity=0), "ghost", "runB")
        assert "Run not found" in capsys.readouterr().err


# ── LaTeX generation ─────────────────────────────────────────────────────

class TestGenerateLatex:
    def _write(self, tmp_path, data):
        p = tmp_path / "res.json"
        p.write_text(json.dumps(data))
        return str(p)

    def test_summary_format_with_winner_star(self, tmp_path):
        p = self._write(tmp_path, {"summary": [
            {"name": "mesh", "edges": 4, "mean": 10.0, "std": 0.5, "min": 9.5, "max": 10.5},
            {"name": "torus", "edges": 8, "mean": 12.0, "std": 0.7, "min": 11.0, "max": 13.0},
        ]})
        tex = pl.generate_latex(Ctx(verbosity=0), p, "Cap", "tab:x")
        assert r"\caption{Cap}" in tex and r"\label{tab:x}" in tex
        assert r"$\star$" in tex.splitlines()[9] or "mesh" in tex
        star_line = [l for l in tex.splitlines() if "mesh" in l and r"\\" in l][0]
        assert r"$\star$" in star_line                # winner marked

    def test_pareto_agg_format(self, tmp_path):
        p = self._write(tmp_path, {
            "traces": ["llama7b"], "agg": [
                {"name": "mesh", "edges": 4, "lat_llama7b": 10.0, "mean_lat": 10.0},
                {"name": "torus", "edges": 8, "lat_llama7b": 14.0, "mean_lat": 14.0}]})
        tex = pl.generate_latex(Ctx(verbosity=0), p, "P", "tab:p")
        assert "llama7b" in tex and "14.0c" in tex

    def test_unreadable_json_yields_comment(self, tmp_path):
        p = tmp_path / "broken.json"
        p.write_text("{nope")
        tex = pl.generate_latex(Ctx(verbosity=0), str(p), "C", "L")
        assert tex.startswith("% Error reading")

    def test_unknown_format_raises(self, tmp_path):
        p = self._write(tmp_path, {"neither": []})
        with pytest.raises(ValueError, match="Unknown JSON format"):
            pl.generate_latex(Ctx(verbosity=0), p, "C", "L")
