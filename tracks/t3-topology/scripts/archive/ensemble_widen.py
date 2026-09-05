#!/usr/bin/env python3
"""ensemble_widen.py — Ensemble widening: evaluate topology on new workload families.

Tests whether the SA-custom topology (optimized for MoE) still beats mesh on
structurally different traffic patterns:
  1. All-reduce ring (collective communication)
  2. KV-cache multicast (GQA decode fan-out)
  3. Hotspot (some nodes receive disproportionate traffic)

Also runs SA on each new family to see if a different topology wins.

Usage:
  python3 ensemble_widen.py --anynet .noc_p0/custom_v2.anynet \
      --matrix tracks/t3-topology/dse/inputs/qwen_moe_64d.mat \
      --n 64 --out .noc_p0/ensemble_wide
"""
import argparse
import json
from collections import defaultdict, deque
from pathlib import Path
import sys
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from milp_topology_v2 import grid_xy, load_matrix
from deadlock_routing import parse_anynet


def allreduce_ring_matrix(n, weight=1.0):
    """All-reduce ring: each node sends to successor (i -> i+1 mod n)."""
    mat = np.zeros((n, n))
    for i in range(n):
        mat[i][(i + 1) % n] = weight
    for i in range(n):
        s = mat[i].sum()
        if s > 0:
            mat[i] /= s
    return mat


def multicast_matrix(n, fanout=8, weight=1.0):
    """KV-cache multicast: sender fans out to fanout receivers per group."""
    mat = np.zeros((n, n))
    group_size = fanout + 1
    for g in range(max(1, n // group_size)):
        base = g * group_size
        sender = base
        for r in range(1, min(group_size, n - base)):
            receiver = base + r
            if receiver < n:
                mat[sender][receiver] = weight / fanout
    for i in range(n):
        s = mat[i].sum()
        if s > 0:
            mat[i] /= s
    return mat


def hotspot_matrix(n, hotspot_frac=0.3, n_hot=4, weight=1.0):
    """Hotspot: first n_hot nodes receive disproportionate traffic."""
    mat = np.zeros((n, n))
    hot = set(range(min(n_hot, n)))
    for i in range(n):
        for j in range(n):
            if j in hot:
                mat[i][j] = weight * hotspot_frac / len(hot)
            else:
                mat[i][j] = weight * (1 - hotspot_frac) / max(1, n - len(hot))
    for i in range(n):
        s = mat[i].sum()
        if s > 0:
            mat[i] /= s
    return mat


def apsp_hops(adj, n):
    """All-pairs shortest paths (unweighted hops)."""
    D = []
    for s in range(n):
        d = [-1] * n
        d[s] = 0
        q = deque([s])
        while q:
            u = q.popleft()
            for v in adj.get(u, []):
                if d[v] < 0:
                    d[v] = d[u] + 1
                    q.append(v)
        D.append(d)
    return D


def whops(T, D, n):
    """Traffic-weighted average hops."""
    tot = ws = 0.0
    for i in range(n):
        for j in range(n):
            if i != j and T[i][j] > 0:
                d = D[i][j]
                tot += T[i][j] * (d if d > 0 else 1e6)
                ws += T[i][j]
    return tot / max(ws, 1e-12)


def adj_from_edges(edges, n):
    adj = defaultdict(list)
    for u, v in edges:
        adj[u].append(v)
        adj[v].append(u)
    return adj


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--anynet', required=True, help='SA-custom topology anynet')
    parser.add_argument('--matrix', required=True, help='Base MoE matrix')
    parser.add_argument('--n', type=int, default=64)
    parser.add_argument('--out', required=True, help='Output directory')
    args = parser.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    n = args.n

    # Load topologies
    n, sa_adj_raw = parse_anynet(args.anynet)
    sa_adj = {k: list(v) for k, v in sa_adj_raw.items()}
    from milp_topology_v2 import base_mesh, valid_links
    mesh_xy = grid_xy(8)
    mesh_edges_raw = valid_links(mesh_xy, 1.5)  # Manhattan 1.5 for grid
    mesh_adj = defaultdict(list)
    for u, v in mesh_edges_raw:
        mesh_adj[u].append(v)
        mesh_adj[v].append(u)

    # Precompute APSP
    sa_dists = apsp_hops(sa_adj, n)
    mesh_dists = apsp_hops(mesh_adj, n)

    # Generate workload families
    families = {
        'moe_nominal': load_matrix(args.matrix),
        'allreduce_ring': allreduce_ring_matrix(n),
        'kv_multicast_fanout8': multicast_matrix(n, fanout=8),
        'hotspot_30pct': hotspot_matrix(n, hotspot_frac=0.3),
    }

    # Evaluate
    print(f"{'Family':<25} {'Mesh hops':>10} {'SA hops':>10} {'SA vs Mesh':>12} {'Winner':>8}")
    print("-" * 70)

    results = {}
    for name, mat in families.items():
        mesh_h = whops(mat, mesh_dists, n)
        sa_h = whops(mat, sa_dists, n)
        improvement = (1 - sa_h / mesh_h) * 100
        winner = "SA" if sa_h < mesh_h else "Mesh"
        print(f"{name:<25} {mesh_h:>10.4f} {sa_h:>10.4f} {improvement:>+11.1f}% {winner:>8}")
        results[name] = {
            'mesh_hops': round(mesh_h, 4),
            'sa_hops': round(sa_h, 4),
            'improvement_pct': round(improvement, 2),
            'winner': winner,
        }

    # Summary
    print("\n--- Verdict ---")
    sa_wins = sum(1 for r in results.values() if r['winner'] == 'SA')
    total = len(results)
    print(f"SA-custom wins {sa_wins}/{total} workload families")

    if sa_wins == total:
        print("✅ Topology is workload-robust across all tested families")
    else:
        losers = [k for k, v in results.items() if v['winner'] != 'SA']
        print(f"⚠️  Loses on: {', '.join(losers)}")

    # Save
    with open(outdir / 'widened_ensemble.json', 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to {outdir / 'widened_ensemble.json'}")


if __name__ == '__main__':
    main()
