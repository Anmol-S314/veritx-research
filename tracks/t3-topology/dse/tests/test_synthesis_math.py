"""Contract tests for the topology-synthesis math: event_objective + milp_topology_v2.

Previously 0% coverage. Style: small deterministic fixtures (2×2 / 4-node
grids), real solves (scipy/HiGHS MILP, simulated annealing), real files for
the CLI paths, subprocess only where `__main__` behavior is the contract.

These are the L2 synthesizer cores: score_topology prices collective
schedules on a candidate topology; milp_topology_v2 GENERATES a topology
minimizing traffic-weighted latency under radix + link-length budgets.
"""
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
ENV = {**{"PYTHONPATH": str(DSE)}, **__import__("os").environ}

from veritx_dse.synthesis import event_objective as eo
from veritx_dse.synthesis.milp_topology_v2 import (
    PIPE_COST,
    WIRE_COST,
    _edge_len,
    base_mesh,
    geodesic,
    grid_xy,
    interposer_xy,
    is_bridge,
    load_matrix,
    priced_geodesic,
    sa_synthesize,
    set_costs,
    solve_tmcf,
    valid_links,
)


# 2×2 grid: node ids 0..3, unit pitches
XY4 = grid_xy(2)
MESH4 = [(0, 1), (0, 2), (1, 3), (2, 3)]          # 2×2 mesh edges
ADJ4 = {0: {1, 2}, 1: {0, 3}, 2: {0, 3}, 3: {1, 2}}

EVENTS = {"collectives": [
    {"tensor": "QKV", "participants": [0, 1, 2, 3], "size_bytes": 1024, "priority": 1},
    {"tensor": "Z", "participants": [0, 1, 2, 3], "size_bytes": 512, "priority": 2},
]}


# ── event_objective: schedules ───────────────────────────────────────────

class TestSchedules:
    def test_ring_is_2k_minus_2_steps_of_k_moves(self):
        s = eo.ring_schedule([0, 1, 2, 3])
        assert len(s) == 2 * (4 - 1) * 4
        assert all(m[2] == pytest.approx(1 / 4) for m in s)
        # step 0 follows the participant ring
        assert (s[0][0], s[0][1]) == (0, 1)

    def test_ring_degenerates_to_empty(self):
        assert eo.ring_schedule([7]) == []
        assert eo.ring_schedule([]) == []

    def test_halving_doubling_for_power_of_two(self):
        s = eo.halving_doubling_schedule([0, 1, 2, 3])
        assert len(s) == 8               # log2(4)=2 stages × k moves
        dists = sorted({m[2] for m in s})
        assert dists == [1 / 4, 2 / 4]   # distance-doubling partners

    def test_non_power_of_two_falls_back_to_ring(self):
        s = eo.halving_doubling_schedule([0, 1, 2])
        assert s == eo.ring_schedule([0, 1, 2])


# ── event_objective: scoring ─────────────────────────────────────────────

class TestScoreTopology:
    def test_feasible_mesh_scores_positive_with_best_algo(self):
        obj, det = eo.score_topology(ADJ4, XY4, EVENTS)
        assert obj > 0 and math.isfinite(obj)
        algos = {d["algo"] for d in det["collectives"]}
        assert algos <= {"ring", "halving_doubling"}
        # priority-1 event must dominate: weight ratio is 4
        (d1, d2) = det["collectives"]
        ratio = d1["cost_cycles_x_bytes"] / d2["cost_cycles_x_bytes"]
        assert ratio == pytest.approx(2.0)   # size 1024 vs 512, same schedule

    def test_priority_weights_scale_objective(self):
        e_hi = {"collectives": [dict(EVENTS["collectives"][0], priority=1)]}
        e_lo = {"collectives": [dict(EVENTS["collectives"][0], priority=2)]}
        obj_hi, _ = eo.score_topology(ADJ4, XY4, e_hi)
        obj_lo, _ = eo.score_topology(ADJ4, XY4, e_lo)
        assert obj_hi == pytest.approx(4 * obj_lo)

    def test_disconnected_topology_penalized_not_crash(self):
        broken = {0: {1}, 1: {0}, 2: {3}, 3: {2}}   # participants cross islands
        obj, det = eo.score_topology(broken, XY4, EVENTS)
        assert obj == 1e15
        assert "infeasible" in det

    def test_unknown_priority_uses_fallback_weight(self):
        e = {"collectives": [dict(EVENTS["collectives"][0], priority=99)]}
        obj_99, _ = eo.score_topology(ADJ4, XY4, e)
        e2 = {"collectives": [dict(EVENTS["collectives"][0], priority=2)]}
        obj_2, _ = eo.score_topology(ADJ4, XY4, e2)
        assert obj_99 == obj_2   # both take the 1.0 fallback

    def test_cli_scores_from_files(self, tmp_path):
        events_p = tmp_path / "events.json"
        events_p.write_text(json.dumps(EVENTS))
        topo_p = tmp_path / "topo.json"
        topo_p.write_text(json.dumps({"edges": {"static_matrix": [list(e) for e in MESH4]}}))
        r = subprocess.run(
            [sys.executable, str(DSE / "veritx_dse" / "synthesis" / "event_objective.py"),
             str(events_p), str(topo_p)],
            capture_output=True, text=True, env=ENV, timeout=60)
        assert r.returncode == 0, r.stderr[-400:]
        assert "objective=" in r.stdout
        assert "best algo=" in r.stdout


# ── milp_topology_v2: layout / feasibility helpers ───────────────────────

class TestLayoutHelpers:
    def test_grid_and_interposer_layouts(self):
        assert grid_xy(2) == [(0, 0), (1, 0), (0, 1), (1, 1)]
        pts = interposer_xy(2, 2, seed=7, jitter=0.08)
        assert len(pts) == 4 and all(0 <= x < 2 + 0.08 and 0 <= y < 2 + 0.08 for x, y in pts)

    def test_valid_links_respect_length_budget(self):
        assert len(valid_links(XY4, max_len=1)) == 4     # mesh edges only
        assert len(valid_links(XY4, max_len=2)) == 6     # + both diagonals

    def test_load_matrix_skips_comments_and_blanks(self, tmp_path):
        p = tmp_path / "t.mat"
        p.write_text("# header\n\n0 1\n1 0\n")
        m = load_matrix(p)
        assert m.shape == (2, 2) and m[0][1] == 1.0

    def test_base_mesh_respects_radix_budget(self):
        edges = base_mesh(XY4, max_nbr=4, radix=2)       # max_deg = radix-1 = 1
        deg = {i: 0 for i in range(4)}
        for a, b in edges:
            deg[a] += 1; deg[b] += 1
        assert max(deg.values()) <= 1

    def test_base_mesh_full_grid_when_radix_allows(self):
        edges = base_mesh(XY4, max_nbr=4, radix=5)
        # 2×2 grid, 4 nearest neighbors ⇒ every node reaches all 3 others: K4
        all_pairs = {(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)}
        assert set(edges) == all_pairs

    def test_edge_len_and_cost_globals(self):
        assert _edge_len(0, 3, XY4) == pytest.approx(math.hypot(1, 1))
        set_costs(7.0, 0.5)
        try:
            from veritx_dse.synthesis import milp_topology_v2 as m
            assert m.PIPE_COST == 7.0 and m.WIRE_COST == 0.5
        finally:
            set_costs(PIPE_COST, WIRE_COST)              # restore for other tests
        from veritx_dse.synthesis import milp_topology_v2 as m
        assert m.PIPE_COST == 3.0 and m.WIRE_COST == 1.0


# ── milp_topology_v2: objectives + bridge detection ──────────────────────

class TestObjectives:
    T4 = [[0, 1, 1, 1], [1, 0, 1, 1], [1, 1, 0, 1], [1, 1, 1, 0]]

    def test_geodesic_counts_hops(self):
        import numpy as np
        obj = geodesic(np.array(self.T4), ADJ4)
        # 2×2 mesh: 2/3 of pairs at 1 hop, 1/3 at 2 hops ⇒ weighted avg = 4/3
        assert obj == pytest.approx(4 / 3)

    def test_priced_geodesic_dominates_hop_count(self):
        import numpy as np
        hops = geodesic(np.array(self.T4), ADJ4)
        priced = priced_geodesic(np.array(self.T4), ADJ4, XY4)
        assert priced >= hops * min(PIPE_COST, WIRE_COST)

    def test_is_bridge_on_path_and_triangle(self):
        path = {0: {1}, 1: {0, 2}, 2: {1}}
        assert is_bridge(path, 0, 1) is True
        tri = {0: {1, 2}, 1: {0, 2}, 2: {0, 1}}
        assert is_bridge(tri, 0, 1) is False


# ── milp_topology_v2: the two synthesizers ───────────────────────────────

class TestSynthesizers:
    def test_tmcf_milp_solves_and_keeps_base_mesh(self):
        import numpy as np
        T = np.ones((4, 4)) - np.eye(4)
        cand = valid_links(XY4, max_len=2)
        res, all_links, Lidx, dem, dir_edges, eid, L, F, E, xv, fv = solve_tmcf(
            T, XY4, MESH4, cand, radix=4, timeout=30)
        assert res.x is not None
        x = np.round(res.x[:L])
        chosen = {e for e, k in Lidx.items() if x[k] > 0.5}
        assert set(MESH4) <= chosen                      # base mesh never dropped

    def test_sa_improves_or_matches_seed_within_radix(self):
        import numpy as np
        T = np.ones((4, 4)) - np.eye(4)
        cand = valid_links(XY4, max_len=2)
        best_adj, best = sa_synthesize(T, XY4, MESH4, cand, radix=4,
                                       iters=300, seed=1)
        base_obj = geodesic(T, ADJ4)
        assert best <= base_obj + 1e-9                   # never worse than seed
        for u, nbrs in best_adj.items():
            assert len(nbrs) <= 4                        # radix respected
        # connectivity preserved (bridges are never removed)
        seen, stack = set(), [0]
        while stack:
            n_ = stack.pop()
            if n_ in seen:
                continue
            seen.add(n_)
            stack.extend(best_adj[n_] - seen)
        assert seen == {0, 1, 2, 3}


# ── milp_topology_v2: CLI contract ───────────────────────────────────────

def _write_matrix(tmp_path):
    p = tmp_path / "t16.mat"
    p.write_text("\n".join(
        " ".join("0" if i == j else "1" for j in range(4)) for i in range(4)))
    return p


class TestMilpCLI:
    def test_sa_mode_writes_anynet_and_json(self, tmp_path):
        mat = _write_matrix(tmp_path)
        out = tmp_path / "c"
        r = subprocess.run(
            [sys.executable, str(DSE / "veritx_dse" / "synthesis" / "milp_topology_v2.py"),
             "--matrix", str(mat), "--layout", "grid", "--method", "sa",
             "--iters", "300", "--out", str(out)],
            capture_output=True, text=True, env=ENV, timeout=120)
        assert r.returncode == 0, r.stderr[-500:]
        assert (out.with_suffix(".anynet")).exists() if False else Path(str(out) + ".anynet").exists()
        stats = json.loads(Path(str(out) + ".json").read_text())["stats"]
        assert stats["nodes"] == 4
        assert "traffic_weighted_avg_hops" in stats
        assert "improvement_pct" in stats["vs_base_mesh"]
        # anynet format: every line is `router i node i router ...`
        first = Path(str(out) + ".anynet").read_text().splitlines()[0]
        assert first.startswith("router 0 node 0")

    def test_milp_mode_reports_optimal_value(self, tmp_path):
        mat = _write_matrix(tmp_path)
        out = tmp_path / "m"
        r = subprocess.run(
            [sys.executable, str(DSE / "veritx_dse" / "synthesis" / "milp_topology_v2.py"),
             "--matrix", str(mat), "--layout", "grid", "--method", "milp",
             "--timeout", "30", "--out", str(out)],
            capture_output=True, text=True, env=ENV, timeout=120)
        assert r.returncode == 0, r.stderr[-500:]
        assert "MILP" in r.stdout and "optimal value" in r.stdout

    def test_sa_accepts_seed_topo_with_protected_links(self, tmp_path):
        mat = _write_matrix(tmp_path)
        seed = tmp_path / "seed.anynet"
        seed.write_text("router 0 node 0 router 1\nrouter 1 node 1 router 0\n")
        out = tmp_path / "s"
        r = subprocess.run(
            [sys.executable, str(DSE / "veritx_dse" / "synthesis" / "milp_topology_v2.py"),
             "--matrix", str(mat), "--layout", "grid", "--method", "sa",
             "--iters", "200", "--seed_topo", str(seed), "--out", str(out)],
            capture_output=True, text=True, env=ENV, timeout=120)
        assert r.returncode == 0, r.stderr[-500:]
        assert "protected links" in r.stdout

    def test_grid_layout_rejects_non_square_n(self, tmp_path):
        mat = tmp_path / "bad.mat"
        mat.write_text("0 1 2\n1 0 1\n2 1 0\n")          # n=3, not k²
        r = subprocess.run(
            [sys.executable, str(DSE / "veritx_dse" / "synthesis" / "milp_topology_v2.py"),
             "--matrix", str(mat), "--layout", "grid", "--out", str(tmp_path / "x")],
            capture_output=True, text=True, env=ENV, timeout=60)
        assert r.returncode != 0
        assert "k^2" in r.stderr or "grid needs" in r.stderr

    def test_interposer_rejects_mismatched_rows_cols(self, tmp_path):
        mat = _write_matrix(tmp_path)                    # n=4
        r = subprocess.run(
            [sys.executable, str(DSE / "veritx_dse" / "synthesis" / "milp_topology_v2.py"),
             "--matrix", str(mat), "--layout", "interposer",
             "--rows", "2", "--cols", "3",              # 6 ≠ 4
             "--out", str(tmp_path / "x")],
            capture_output=True, text=True, env=ENV, timeout=60)
        assert r.returncode != 0
        assert "rows*cols" in r.stderr
