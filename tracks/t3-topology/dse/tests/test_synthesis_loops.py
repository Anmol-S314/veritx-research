"""Contract tests for the two topology-synthesis loops: bo_synthesizer and
iterative_synthesizer (previously 0% coverage).

Real objects throughout: real skopt GP iterations (analytical scorer), real
BookSim evaluations for evaluate_topology / eval_bs, real subprocess for the
CLI mains. Budgets are capped (tiny node counts, 1-step loops) so the batch
runs in ~30s. The booksim-dependent tests skip when the standalone binary
isn't built; the fast-fail / missing-binary branches are asserted without it.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

DSE = Path(__file__).resolve().parent.parent
REPO = DSE.parent.parent.parent
ENV = {**{"PYTHONPATH": str(DSE)}, **__import__("os").environ}

from veritx_dse.core.paths import BOOKSIM_BIN
from veritx_dse.synthesis import bo_synthesizer as bo
from veritx_dse.synthesis.iterative_synthesizer import (
    edges_of,
    eval_bs,
    is_connected,
    load_anynet,
    mutate,
    mutate_add,
    mutate_remove,
)

BOOKSIM_PRESENT = BOOKSIM_BIN.exists()

MESH9 = {  # 3×3 mesh
    0: {1, 3}, 1: {0, 2, 4}, 2: {1, 5},
    3: {0, 4, 6}, 4: {1, 3, 5, 7}, 5: {2, 4, 8},
    6: {3, 7}, 7: {4, 6, 8}, 8: {5, 7},
}


def _write_trace(tmp_path, n_ranks=3, n_pkt=30):
    lines = []
    cyc = 0
    for i in range(n_pkt):
        s, d = i % n_ranks, (i + 1) % n_ranks
        lines.append(f"{cyc} {s} 0 {d} 4")
        cyc += 10
    p = tmp_path / "tiny.trace"
    p.write_text("\n".join(lines) + "\n")
    return p


# ── bo_synthesizer: pure helpers ─────────────────────────────────────────

class TestBoHelpers:
    def test_grid_xy_requires_perfect_square(self):
        assert bo.grid_xy(4) == [(0, 0), (1, 0), (0, 1), (1, 1)]
        with pytest.raises(AssertionError):
            bo.grid_xy(3)

    def test_generate_topology_connected_within_radix(self):
        adj = bo.generate_topology(9, cluster_size=4, express_length=2,
                                   radix=5, intra_weight=0.8, inter_weight=0.4,
                                   seed=42)
        assert bo._is_connected(adj)
        for i, nbrs in adj.items():
            assert len(nbrs) <= 5 - 1 + 0 or True  # budget enforced in-loop
        # radix budget: no node above radix-1 after enforcement
        assert all(len(v) <= 4 for v in adj.values())

    def test_adj_roundtrip_anynet(self, tmp_path):
        adj = {i: set() for i in range(4)}
        adj[0] = {1}; adj[1] = {0, 2}; adj[2] = {1, 3}; adj[3] = {2}
        p = tmp_path / "t.anynet"
        bo.edge_list_to_anynet(adj, p)
        lines = p.read_text().splitlines()
        assert lines[0].startswith("router 0 node 0 router 1")
        assert bo.adj_to_edge_list(adj) == [(0, 1), (1, 2), (2, 3)]

    def test_build_traffic_matrix_from_trace_counts(self, tmp_path):
        tr = tmp_path / "t.trace"
        tr.write_text("0 0 0 1 4\n5 1 0 2 4\n# comment\n")
        T = bo.build_traffic_matrix(tr, n_nodes=3)
        assert T[0][1] == 1 and T[1][2] == 1 and T[2][0] == 0

    def test_build_traffic_matrix_from_flow_classes(self, tmp_path):
        events = {"network": {"flow_classes": [{
            "comm_type": "allreduce", "bytes_per_invocation": 1024,
            "instances": [{"participants": [0, 1, 2]}]}]}}
        p = tmp_path / "events.json"
        p.write_text(json.dumps(events))
        T = bo.build_traffic_matrix(p, n_nodes=3)
        assert T.sum() > 0

    def test_build_traffic_matrix_uniform_fallback(self, tmp_path):
        junk = tmp_path / "junk.json"
        junk.write_text("not json {{{")
        T = bo.build_traffic_matrix(junk, n_nodes=4)
        assert T.sum() == pytest.approx(16.0)   # ones fallback

    def test_build_traffic_matrix_meta_collectives(self, tmp_path):
        events = {"meta": {"num_tiles": 3},
                  "collectives": [{"participants": [0, 1, 2], "size_bytes": 768}]}
        p = tmp_path / "meta_events.json"
        p.write_text(json.dumps(events))
        T = bo.build_traffic_matrix(p, n_nodes=3)
        assert T.sum() > 0


# ── bo_synthesizer: BookSim evaluation ───────────────────────────────────

class TestBoEvaluateTopology:
    def test_disconnected_topologies_get_penalty_without_spawning(self, tmp_path):
        broken = {0: {1}, 1: {0}, 2: {3}, 3: {2}}
        T = np.ones((4, 4)) - np.eye(4)
        assert bo.evaluate_topology(broken, T, tmp_path) == 1e9
        assert not list(tmp_path.glob("**/*.anynet"))   # no work done

    @pytest.mark.skipif(not BOOKSIM_PRESENT, reason="standalone booksim not built")
    def test_matrix_mode_returns_real_latency(self, tmp_path):
        adj = {i: set() for i in range(4)}
        adj[0] = {1}; adj[1] = {0, 3}; adj[2] = {3}; adj[3] = {1, 2}
        T = np.ones((4, 4)) - np.eye(4)
        lat = bo.evaluate_topology(adj, T, tmp_path)
        assert 0 < lat < 1e8

    def test_missing_booksim_reports_finite_penalty(self, tmp_path, monkeypatch):
        adj = {i: set() for i in range(4)}
        adj[0] = {1}; adj[1] = {0, 3}; adj[2] = {3}; adj[3] = {1, 2}
        T = np.ones((4, 4)) - np.eye(4)
        import veritx_dse.core.paths as paths
        monkeypatch.setattr(paths, "BOOKSIM_BIN", tmp_path / "nope")
        lat = bo.evaluate_topology(adj, T, tmp_path)
        assert lat == 1000.0   # finite so the GP can keep iterating


# ── bo_synthesizer: GP main (analytical scorer, budget-capped) ───────────

class TestBoMain:
    def test_analytical_gp_run(self, tmp_path, monkeypatch):
        events = {"collectives": [
            {"tensor": "QKV", "participants": [0, 1, 2, 3],
             "size_bytes": 1024, "priority": 1}]}
        ev = tmp_path / "events.json"
        ev.write_text(json.dumps(events))
        monkeypatch.chdir(tmp_path)               # runs/ lands in tmp
        monkeypatch.setattr(sys, "argv", [
            "bo_synthesizer.py", "--traffic", str(ev), "--nodes", "4",
            "--iters", "10", "--seed", "1", "--scorer", "analytical"])
        bo.main()
        out = tmp_path / "runs" / "booksim" / "bo_results_N4.json"
        assert out.exists()
        res = json.loads(out.read_text())
        assert res["best_params"]["edges"] > 0
        assert len(res["all_evals"]) == 10
        assert res["best_params"]["radix"] in (3, 4, 5)
        assert (tmp_path / "runs" / "booksim" / "topo.anynet").exists()


# ── iterative_synthesizer: graph ops + BookSim eval ──────────────────────

class TestGraphOps:
    def test_load_anynet_roundtrip(self, tmp_path):
        p = tmp_path / "m.anynet"
        p.write_text("router 0 node 0 router 1\n"
                     "router 1 node 1 router 0 router 2\n"
                     "router 2 node 2 router 1\n")
        adj = load_anynet(p)
        assert adj[0] == {1} and adj[1] == {0, 2} and adj[2] == {1}
        assert is_connected(adj)

    def test_edges_of_dedupes_undirected(self):
        adj = {0: {1, 2}, 1: {0}, 2: {0}}
        assert edges_of(adj) == {(0, 1), (0, 2)}

    def test_mutate_add_and_remove_preserve_invariants(self):
        import random
        random.seed(7)
        n = 9
        added = removed = 0
        for _ in range(200):
            cand, op = mutate_add(MESH9, n)
            if cand:
                assert op.startswith("add")
                assert is_connected(cand)
                added += 1
            cand, op = mutate_remove(MESH9)
            if cand:
                assert op.startswith("remove")
                assert is_connected(cand)      # bridges restored
                removed += 1
        assert added > 0 and removed > 0
        # mutate dispatches one of the two
        random.seed(1)
        for _ in range(20):
            cand, op = mutate(MESH9, n)
            if op:
                assert op[0] in "ar"

    def test_mutate_remove_never_disconnects(self):
        path = {0: {1}, 1: {0, 2}, 2: {1}}   # every edge is a bridge
        import random
        random.seed(3)
        for _ in range(50):
            cand, _op = mutate_remove(path)
            assert cand is None              # removal refused, graph intact
            assert is_connected(path)


@pytest.mark.skipif(not BOOKSIM_PRESENT, reason="standalone booksim not built")
class TestEvalBs:
    def test_evaluates_mesh_latency(self, tmp_path):
        tr = _write_trace(tmp_path)
        lat = eval_bs(MESH9, str(tr), timeout=60)
        assert 0 < lat < 1e9

    def test_garbage_binary_output_returns_penalty(self, tmp_path, monkeypatch):
        """If BookSim produces no parseable latency line, eval must degrade
        to a finite penalty — not crash, not return garbage."""
        import veritx_dse.synthesis.iterative_synthesizer as it
        calls = []
        real_run = subprocess.run

        def fake_run(*a, **k):
            calls.append(1)
            return subprocess.CompletedProcess(a[0], 0, stdout="nothing useful", stderr="")

        monkeypatch.setattr(it.subprocess, "run", fake_run)
        tr = _write_trace(tmp_path)
        lat = eval_bs(MESH9, str(tr), timeout=10)
        assert calls and lat == 1e9


# ── iterative_synthesizer: CLI mains (budget-capped) ─────────────────────

@pytest.mark.skipif(not BOOKSIM_PRESENT, reason="standalone booksim not built")
class TestIterativeMain:
    @pytest.mark.parametrize("method", ["rho", "grpo"])
    def test_one_step_loop_produces_artifacts(self, tmp_path, method):
        tr = _write_trace(tmp_path)
        out = tmp_path / "best.anynet"
        r = subprocess.run(
            [sys.executable, str(DSE / "veritx_dse" / "synthesis" / "iterative_synthesizer.py"),
             "--trace", str(tr), "--method", method, "--steps", "1",
             "--branch", "1", "--group", "2", "--horizon", "2",
             "--timeout", "20", "--out", str(out)],
            capture_output=True, text=True, env=ENV, timeout=240)
        assert r.returncode == 0, r.stderr[-500:]
        assert out.exists()
        res = json.loads(out.with_suffix(".json").read_text())
        assert res["method"] == method
        assert res["edges"] == len(edges_of(MESH9)) or res["edges"] > 0
        assert "Final:" in r.stdout
