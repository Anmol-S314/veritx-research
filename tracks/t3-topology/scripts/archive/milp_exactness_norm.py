#!/usr/bin/env python3
"""milp_exactness_norm.py — P0: Coarse-to-fine vs plain SA with edge-count normalization.

Re-runs the comparison with proper normalization:
  - Reports edge count, max degree, avg degree for both topologies
  - Only claims superiority if the refined topology is at least as efficient
    (edges × hops product is the fair metric)
  - Multi-seed stability report

Usage:
  python3 milp_exactness_norm.py --matrix dse/inputs/qwen_moe_64d.mat --out .noc_p0/exactness_norm.json
"""
import argparse
import json
import random
import time
from collections import defaultdict, deque
from pathlib import Path
import sys
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from milp_topology_v2 import (
    grid_xy, base_mesh, valid_links, sa_synthesize, geodesic, load_matrix
)


def topology_stats(adj, n=None):
    """Compute edge count, max degree, avg degree."""
    if n is None:
        n = len(adj)
    edges = sum(len(v) for v in adj.values()) // 2
    deg = [len(adj.get(i, [])) for i in range(n)]
    return {
        "edges": edges,
        "max_degree": max(deg) if deg else 0,
        "avg_degree": round(sum(deg) / max(len(deg), 1), 2),
        "total_degree": sum(deg),
    }


def coarse_to_fine(T, xy, base, cand, radix, k_coarse=4, iters_sa=4000):
    """Hierarchical coarse-to-fine: aggregate to k_coarse×k_coarse, solve, lift, refine."""
    n = T.shape[0]
    kk = int(round(np.sqrt(n)))
    assert kk * kk == n, f"n must be perfect square (n={n})"
    
    # Coarse grid
    ck = k_coarse
    coarse_n = ck * ck
    
    # Aggregate matrix: 2×2 blocks → coarse node
    block_size = kk // ck
    T_coarse = np.zeros((coarse_n, coarse_n))
    for ci in range(ck):
        for cj in range(ck):
            for fi in range(block_size):
                for fj in range(block_size):
                    si = ci * block_size + fi
                    sj = cj * block_size + fj
                    for ti in range(ck):
                        for tj in range(ck):
                            for di in range(block_size):
                                for dj in range(block_size):
                                    d_i = ti * block_size + di
                                    d_j = tj * block_size + dj
                                    T_coarse[ci * ck + cj][ti * ck + tj] += T[si * sj + sj][d_i * kk + d_j] if False else T[si][sj]  # placeholder
    
    # Simpler aggregation: just sum blocks
    T_coarse = np.zeros((coarse_n, coarse_n))
    for ci in range(ck):
        for cj in range(ck):
            coarse_src = ci * ck + cj
            for ti in range(ck):
                for tj in range(ck):
                    coarse_dst = ti * ck + tj
                    block_sum = 0
                    for fi in range(block_size):
                        for fj in range(block_size):
                            si = ci * block_size + fi
                            sj = cj * block_size + fj
                            for di in range(block_size):
                                for dj in range(block_size):
                                    d_i = ti * block_size + di
                                    d_j = tj * block_size + dj
                                    if si < n and sj < n and d_i < n and d_j < n:
                                        block_sum += T[si * kk + sj][d_i * kk + d_j]
                    T_coarse[coarse_src][coarse_dst] = block_sum
    
    # Solve coarse
    coarse_xy = grid_xy(ck)
    coarse_base = base_mesh(coarse_xy)
    coarse_cand = valid_links(coarse_xy, 2.0)
    coarse_adj, coarse_hops = sa_synthesize(T_coarse, coarse_xy, coarse_base,
                                             coarse_cand, radix, iters=2000, seed=1)
    
    # Lift: map coarse edges back to physical nodes
    # Each coarse node (ci, cj) maps to block (ci*bs..ci*bs+bs-1, cj*bs..cj*bs+bs-1)
    fine_adj = defaultdict(set)
    
    # Add intra-block rings
    for ci in range(ck):
        for cj in range(ck):
            block_nodes = []
            for fi in range(block_size):
                for fj in range(block_size):
                    ni = (ci * block_size + fi) * kk + (cj * block_size + fj)
                    block_nodes.append(ni)
            for i in range(len(block_nodes)):
                j = (i + 1) % len(block_nodes)
                fine_adj[block_nodes[i]].add(block_nodes[j])
                fine_adj[block_nodes[j]].add(block_nodes[i])
    
    # Add inter-block links from coarse topology
    for ca in coarse_adj:
        for cb in coarse_adj[ca]:
            if ca < cb:
                # Find closest pair of physical nodes
                ai, aj = ca // ck, ca % ck
                bi, bj = cb // ck, cb % ck
                best_dist = float("inf")
                best_pair = None
                for fi in range(block_size):
                    for fj in range(block_size):
                        for gi in range(block_size):
                            for gj in range(block_size):
                                ni = (ai * block_size + fi) * kk + (aj * block_size + fj)
                                nj = (bi * block_size + gi) * kk + (bj * block_size + gj)
                                if ni < n and nj < n:
                                    d = abs(xy[ni][0] - xy[nj][0]) + abs(xy[ni][1] - xy[nj][1])
                                    if d < best_dist:
                                        best_dist = d
                                        best_pair = (ni, nj)
                if best_pair:
                    a, b = best_pair
                    if len(fine_adj[a]) < radix and len(fine_adj[b]) < radix:
                        fine_adj[a].add(b)
                        fine_adj[b].add(a)
    
    # Refine: SA on the lifted skeleton (protected base = lifted edges)
    protected = set()
    for u in range(n):
        for v in fine_adj[u]:
            protected.add(tuple(sorted((u, v))))
    
    refined_adj, refined_hops = sa_synthesize(T, xy, protected, cand, radix,
                                               iters=iters_sa, seed=1)
    
    return coarse_adj, coarse_hops, refined_adj, refined_hops


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--matrix", required=True)
    ap.add_argument("--iters", type=int, default=4000)
    ap.add_argument("--n-seeds", type=int, default=5)
    ap.add_argument("--out", default=".noc_p0/exactness_norm.json")
    args = ap.parse_args()

    T = load_matrix(Path(args.matrix))
    n = T.shape[0]
    kk = int(round(np.sqrt(n)))
    xy = grid_xy(kk)
    base = base_mesh(xy)
    cand = valid_links(xy, 2.0)
    
    # Plain SA multi-seed
    print(f"Plain SA: {args.n_seeds} seeds, {args.iters} iters each")
    plain_results = []
    for seed in range(args.n_seeds):
        t0 = time.time()
        adj, hops = sa_synthesize(T, xy, base, cand, 5, iters=args.iters, seed=seed)
        stats = topology_stats(adj, n)
        dt = time.time() - t0
        plain_results.append({"seed": seed, "hops": hops, "stats": stats, "time": round(dt, 1)})
        print(f"  seed={seed}: hops={hops:.4f}, edges={stats['edges']}, "
              f"maxdeg={stats['max_degree']}, time={dt:.1f}s")
    
    # Coarse-to-fine
    print(f"\nCoarse-to-fine: 4×4 coarse → lift → refine {args.iters} iters")
    t0 = time.time()
    coarse_adj, coarse_hops, refined_adj, refined_hops = coarse_to_fine(
        T, xy, base, cand, 5, iters_sa=args.iters)
    coarse_stats = topology_stats(coarse_adj)
    refined_stats = topology_stats(refined_adj, n)
    c2f_time = time.time() - t0
    print(f"  coarse: hops={coarse_hops:.4f}, edges={coarse_stats['edges']}")
    print(f"  refined: hops={refined_hops:.4f}, edges={refined_stats['edges']}")
    
    # Normalized comparison: edges × hops (cost efficiency)
    plain_best = min(plain_results, key=lambda r: r["hops"])
    plain_efficiency = plain_best["hops"] * plain_best["stats"]["edges"]
    refined_efficiency = refined_hops * refined_stats["edges"]
    
    print(f"\n{'='*60}")
    print(f"NORMALIZED COMPARISON (hops × edges = cost efficiency)")
    print(f"{'='*60}")
    print(f"  Plain SA best:  hops={plain_best['hops']:.4f}, edges={plain_best['stats']['edges']}, "
          f"efficiency={plain_efficiency:.1f}")
    print(f"  Refined:        hops={refined_hops:.4f}, edges={refined_stats['edges']}, "
          f"efficiency={refined_efficiency:.1f}")
    
    if refined_efficiency < plain_efficiency:
        improvement = (1 - refined_efficiency / plain_efficiency) * 100
        print(f"  → Refined is {improvement:.1f}% more efficient (lower is better)")
    else:
        degradation = (refined_efficiency / plain_efficiency - 1) * 100
        print(f"  → Refined is {degradation:.1f}% LESS efficient (plain SA wins on normalized metric)")
    
    # Multi-seed stats
    plain_hops = [r["hops"] for r in plain_results]
    print(f"\n  Plain SA: mean={np.mean(plain_hops):.4f}, std={np.std(plain_hops):.4f}, "
          f"min={min(plain_hops):.4f}, max={max(plain_hops):.4f}")
    
    result = {
        "plain_sa": {
            "best_hops": plain_best["hops"],
            "best_edges": plain_best["stats"]["edges"],
            "efficiency": round(plain_efficiency, 2),
            "mean_hops": round(float(np.mean(plain_hops)), 4),
            "std_hops": round(float(np.std(plain_hops)), 4),
            "seeds": plain_results,
        },
        "coarse_to_fine": {
            "refined_hops": refined_hops,
            "refined_edges": refined_stats["edges"],
            "efficiency": round(refined_efficiency, 2),
            "time": round(c2f_time, 1),
        },
        "verdict": "refined_wins" if refined_efficiency < plain_efficiency else "plain_sa_wins",
    }
    
    Path(args.out).write_text(json.dumps(result, indent=2))
    print(f"\n-> {args.out}")


if __name__ == "__main__":
    main()
