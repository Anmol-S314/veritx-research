"""Lineage reclamation — CLI pipeline generic-safety behaviours (PHASE 3.1).

These pin the behaviours RECLAIMED from the stronger CLI lineage
(integration/p1-product) into `cli/pipeline.py` and the reusable authority
`model/presets.anynet_usability`. They are SEMANTIC contracts, not history:
nothing here depends on a remote branch being present.

NOT reclaimed, and pinned as such: the historical Phase-8 verdict block in
pipeline.py. `core/comparison.py` is classified LEGACY_INTERNAL in
`application/inventory.py`; the canonical comparability gate is
`application.comparison` over typed results. Reclaiming the old block would
resurrect a second comparison authority, so the CLI winner claim is instead
LABELLED uncertified.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.model.presets import anynet_usability, make_anynet_topo

def _anynet(tmp_path, name, lines):
    p = tmp_path / name
    p.write_text(lines)
    return make_anynet_topo(str(p))

def test_anynet_usability_accepts_a_connected_graph(tmp_path):
    t = _anynet(tmp_path, "ok.anynet",
                "router 0 node 0 router 1\nrouter 1 node 1 router 0\n")
    assert anynet_usability(t) == (True, "")

def test_anynet_usability_distinguishes_four_failures(tmp_path):
    """Missing file / corrupt file / disconnected graph / oversized trace
    must keep FOUR DISTINCT reasons — collapsing them into one shrug hides
    which repair is needed."""
    missing = make_anynet_topo(str(tmp_path / "nope.anynet"))
    ok, reason = anynet_usability(missing)
    assert not ok and "not found" in reason

    empty = tmp_path / "empty.anynet"
    empty.write_text("# only a comment\n")
    ok, reason = anynet_usability(make_anynet_topo(str(empty)))
    assert not ok and "zero routers" in reason

    disc = _anynet(tmp_path, "disc.anynet",
                   "router 0 node 0 router 1\nrouter 1 node 1 router 0\n"
                   "router 2 node 2 router 3\nrouter 3 node 3 router 2\n")
    ok, reason = anynet_usability(disc)
    assert not ok and "unreachable" in reason

    good = _anynet(tmp_path, "good.anynet",
                   "router 0 node 0 router 1\nrouter 1 node 1 router 0\n")
    ok, reason = anynet_usability(good, trace_max_node=9)
    assert not ok and "remap the trace" in reason
    assert anynet_usability(good, trace_max_node=1) == (True, "")

class _Ctx:
    verbosity = 0
    json_mode = False
    failed = False
    log_file = "/dev/null"

    def _append(self, *a, **k):
        pass

def _patch_eval(monkeypatch, behaviour):
    from veritx_dse.cli import pipeline as pl
    from veritx_dse.simulation.booksim import BookSimError

    def fake(ctx, topo, trace, **kw):
        return behaviour(topo, kw)

    monkeypatch.setattr(pl, "run_topology_eval", fake)
    return pl

def test_failed_candidate_stays_visible_in_summary(monkeypatch, tmp_path):
    """Silent exclusion hides exactly the runs that invalidate a comparison."""
    from veritx_dse.simulation.booksim import BookSimError
    from veritx_dse.model.presets import lookup_topo

    def behaviour(topo, kw):
        if topo.backend == "mesh":
            raise BookSimError("boom")
        return {"latency": 10.0, "nodes": 64, "edges": 112}

    pl = _patch_eval(monkeypatch, behaviour)
    res = pl.run_compare(_Ctx(), "t.trace",
                         [("a", lookup_topo("mesh_8x8")),
                          ("b", lookup_topo("torus_8x8"))], seeds=1)
    by = {s["name"]: s for s in res.summary}
    assert "error" in by["a"] and by["a"]["n"] == 0
    assert "mean" in by["b"]

def test_failure_record_reports_topology_size_not_zero(monkeypatch):
    """`nodes: 0` was a lie about what was attempted."""
    from veritx_dse.simulation.booksim import BookSimError
    from veritx_dse.model.presets import lookup_topo

    def behaviour(topo, kw):
        raise BookSimError("boom")

    pl = _patch_eval(monkeypatch, behaviour)
    res = pl.run_compare(_Ctx(), "t.trace", [("a", lookup_topo("mesh_8x8"))],
                         seeds=1)
    rec = res.results[0]
    assert rec["nodes"] == 64 and rec["edges"] == 112

def test_honest_latency_is_preferred_when_present(monkeypatch):
    """The stock plat mean is qtime-based and inflates sparse traces."""
    from veritx_dse.model.presets import lookup_topo

    def behaviour(topo, kw):
        return {"latency": 1000.0, "honest_latency": 12.0,
                "nodes": 64, "edges": 112}

    pl = _patch_eval(monkeypatch, behaviour)
    res = pl.run_compare(_Ctx(), "t.trace", [("a", lookup_topo("mesh_8x8"))],
                         seeds=2)
    assert res.summary[0]["mean"] == 12.0

def test_unusable_anynet_is_skipped_with_a_reason(monkeypatch, tmp_path):
    """A disconnected custom graph must not produce a rankable number."""
    from veritx_dse.model.presets import make_anynet_topo

    def behaviour(topo, kw):
        return {"latency": 1.0, "nodes": 4, "edges": 2}

    pl = _patch_eval(monkeypatch, behaviour)
    disc = tmp_path / "d.anynet"
    disc.write_text("router 0 node 0 router 1\nrouter 1 node 1 router 0\n"
                    "router 2 node 2 router 3\nrouter 3 node 3 router 2\n")
    res = pl.run_compare(_Ctx(), "t.trace",
                         [("d", make_anynet_topo(str(disc)))], seeds=1)
    assert res.summary[0]["n"] == 0
    assert "unusable anynet" in res.summary[0]["error"]

def test_generate_latex_accepts_sweep_list(tmp_path):
    from veritx_dse.cli.pipeline import generate_latex
    p = tmp_path / "sweep.json"
    p.write_text(json.dumps([
        {"name": "mesh_4x4", "edges": 24, "latency": 99.0,
         "honest_latency": 9.0, "hops": 2.0},
        {"name": "torus_8x8", "edges": 128, "latency": 8.0, "hops": 3.0},
    ]))
    tex = generate_latex(_Ctx(), str(p), "cap", "lbl")
    assert "mesh_4x4" in tex and "torus_8x8" in tex
    assert "9.0c" in tex and "99.0c" not in tex

def test_generate_latex_empty_rows_does_not_crash(tmp_path):
    from veritx_dse.cli.pipeline import generate_latex
    p = tmp_path / "empty.json"
    p.write_text(json.dumps({"summary": []}))
    assert "No rows" in generate_latex(_Ctx(), str(p), "c", "l")

def test_legacy_compare_winner_is_labelled_uncertified():
    """cmd_compare must not present an uncertified ranking as canonical
    science. The canonical gate is application.comparison."""
    src = (Path(__file__).parent.parent
           / "veritx_dse/cli/pipeline.py").read_text()
    assert "UNCERTIFIED LEGACY COMPARISON" in src
    assert "qualified product comparison" in src
    assert "evaluate_comparability" not in src
    assert "from ..core.comparison import" not in src
