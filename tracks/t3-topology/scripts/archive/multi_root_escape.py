#!/usr/bin/env python3
"""multi_root_escape.py — P1: Multi-root escape tree sweep.

Root choice changes tree capacity (root 0 is arbitrary). This script:
  1. Tries multiple roots (0, center node, highest-degree node, random)
  2. For each root, extracts the escape tree and measures:
     - tree depth (lower = faster drain)
     - avg unweighted path length (lower = better escape routes)
     - sparsest cut of the tree (higher = more bisection BW on escape)
  3. Reports the best root and the difference

Usage:
  python3 multi_root_escape.py --anynet .noc_p0/custom_v2.anynet \
      --matrix tracks/t3-topology/dse/inputs/qwen_moe_64d.mat
"""
import argparse
import json
import random
from collections import defaultdict, deque
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deadlock_routing import parse_anynet, load_matrix


def bfs_tree(adj, n, root):
    """BFS spanning tree from root. Returns (tree_adj, parent, rank, depth)."""
    rank = [-1] * n
    parent = [-1] * n
    rank[root] = 0
    q = deque([root])
    tree_adj = defaultdict(set)
    while q:
        u = q.popleft()
        for v in sorted(adj[u]):
            if rank[v] < 0:
                rank[v] = rank[u] + 1
                parent[v] = u
                q.append(v)
                tree_adj[u].add(v)
                tree_adj[v].add(u)
    depth = max(rank) if all(r >= 0 for r in rank) else -1
    return tree_adj, parent, rank, depth


def tree_path_len(parent, rank, s, t):
    """Compute path length from s to t on the tree."""
    a, b = s, t
    length = 0
    while rank[a] > rank[b]:
        a = parent[a]; length += 1
    while rank[b] > rank[a]:
        b = parent[b]; length += 1
    while a != b:
        a = parent[a]; b = parent[b]; length += 2
    return length


def tree_avg_path(parent, rank, n):
    """Average path length over all (s,t) pairs on the tree."""
    total = 0; count = 0
    for s in range(n):
        for t in range(n):
            if s != t:
                total += tree_path_len(parent, rank, s, t)
                count += 1
    return total / max(count, 1)


def tree_bisection(tree_adj, n):
    """Count edges crossing the median bisection of the tree."""
    # Use BFS level as proxy: split at median rank
    rank_vals = []
    q = deque([0])
    visited = {0}
    # Get all ranks from tree_adj
    for u in tree_adj:
        for v in tree_adj[u]:
            if v not in visited:
                visited.add(v)
    # Compute ranks via BFS from node 0
    rank = [-1] * n
    rank[0] = 0
    q = deque([0])
    while q:
        u = q.popleft()
        for v in tree_adj[u]:
            if rank[v] < 0:
                rank[v] = rank[u] + 1
                q.append(v)
    
    median = sorted(rank)[n // 2]
    part_a = set(i for i in range(n) if rank[i] <= median and rank[i] >= 0)
    part_b = set(i for i in range(n) if rank[i] > median and rank[i] >= 0)
    cut = sum(1 for u in part_a for v in tree_adj[u] if v in part_b)
    return cut, len(part_a), len(part_b)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anynet", required=True)
    ap.add_argument("--matrix", default=None)
    ap.add_argument("--roots", default=None, help="comma-separated root ids (default: auto)")
    ap.add_argument("--n-random", type=int, default=5, help="number of random roots to try")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    n, adj = parse_anynet(args.anynet)
    adj_dict = {i: set(adj.get(i, ())) for i in range(n)}

    # Determine roots to try
    if args.roots:
        roots = [int(x) for x in args.roots.split(",")]
    else:
        # Auto: node 0, highest-degree, center (min max-rank), random
        roots = [0]
        # Highest degree
        max_deg_node = max(range(n), key=lambda i: len(adj_dict[i]))
        roots.append(max_deg_node)
        # Center (BFS from 0, pick node with min max-distance)
        dist_matrix = [[-1]*n for _ in range(n)]
        for s in range(n):
            dist_matrix[s][s] = 0
            q = deque([s])
            while q:
                u = q.popleft()
                for v in adj_dict[u]:
                    if dist_matrix[s][v] < 0:
                        dist_matrix[s][v] = dist_matrix[s][u] + 1
                        q.append(v)
        eccentricity = [max(dist_matrix[i]) for i in range(n)]
        center = min(range(n), key=lambda i: eccentricity[i])
        roots.append(center)
        # Random
        rng = random.Random(42)
        for _ in range(args.n_random):
            r = rng.randint(0, n - 1)
            if r not in roots:
                roots.append(r)

    T = None
    if args.matrix and Path(args.matrix).exists():
        T = load_matrix(args.matrix)

    print(f"Multi-root escape tree sweep: {n} nodes, {len(roots)} roots")
    print(f"{'root':<8} {'depth':<8} {'avg_path':<10} {'tree_edges':<12} {'bisect':<8} {'status'}")
    print("-" * 60)

    results = []
    for root in roots:
        tree_adj, parent, rank, depth = bfs_tree(adj_dict, n, root)
        tree_edges = sum(len(v) for v in tree_adj.values()) // 2
        avg_path = tree_avg_path(parent, rank, n)
        bisect, pa, pb = tree_bisection(tree_adj, n)
        
        # Weighted avg path if matrix available
        if T is not None:
            import numpy as np
            Tnp = np.array(T) if not isinstance(T, np.ndarray) else T
            weighted_total = 0; weight_sum = 0
            for s in range(n):
                for t in range(n):
                    if s != t:
                        w = Tnp[s][t]
                        pl = tree_path_len(parent, rank, s, t)
                        weighted_total += w * pl
                        weight_sum += w
            weighted_avg = weighted_total / max(weight_sum, 1e-12)
        else:
            weighted_avg = avg_path

        connected = all(r >= 0 for r in rank)
        status = "OK" if connected else "DISCONNECTED"
        
        results.append({
            "root": root, "depth": depth, "avg_path": round(avg_path, 3),
            "weighted_avg": round(weighted_avg, 3), "tree_edges": tree_edges,
            "bisect": bisect, "connected": connected,
        })
        print(f"{root:<8} {depth:<8} {avg_path:<10.3f} {tree_edges:<12} {bisect:<8} {status}")

    # Find best
    valid = [r for r in results if r["connected"]]
    if valid:
        best_depth = min(valid, key=lambda r: r["depth"])
        best_path = min(valid, key=lambda r: r["weighted_avg"])
        best_bisect = max(valid, key=lambda r: r["bisect"])
        
        print(f"\nBest by depth:     root={best_depth['root']} (depth={best_depth['depth']})")
        print(f"Best by avg path:  root={best_path['root']} (weighted={best_path['weighted_avg']})")
        print(f"Best by bisection: root={best_bisect['root']} (cut={best_bisect['bisect']})")
        
        if best_depth["root"] != 0:
            print(f"\n⚠️  root=0 is NOT optimal! Consider root={best_depth['root']} for better escape tree.")

    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2))
        print(f"\n-> {args.out}")


if __name__ == "__main__":
    main()
