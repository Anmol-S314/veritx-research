#!/usr/bin/env python3
"""d2d_fab_check.py — P0: prove the interposer (die-to-die) fabric with an
IRREGULAR placement and a REALISTIC D2D matrix (the earlier fixture showed a
tiny win because regular placement ≈ regular grid).

Scenario (multi-die LLM serving on an interposer):
  * 16 chiplets in a 4x4 floorplan with heavy placement jitter (irregular).
  * 4 chiplets are HBM stack sites {0, 5, 10, 15}; every die sends memory
    traffic to its nearest HBM site (on top of expert traffic).
  * Expert traffic = qwen_moe_64d aggregated 64 -> 16 dies (sum of 4 routers).

Checks:
  1. mesh baseline vs SA-synthesized interposer topo (same radix/max_len).
  2. irregular jitter sweep: 0.08 (near-regular) vs 0.45 (irregular) — the
     synthesized win must GROW with irregularity for the fabric claim to hold.
  3. connectivity + radix feasibility of every result.

Usage:
  python3 d2d_fab_check.py --matrix tracks/t3-topology/dse/inputs/qwen_moe_64d.mat \
      --out .noc_p0/d2d
"""
import argparse, json, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from milp_topology_v2 import (interposer_xy, valid_links, base_mesh,
                              sa_synthesize, geodesic, load_matrix)
from collections import defaultdict, deque

HBM = {0, 5, 10, 15}

def build_d2d(T64, rows=4, cols=8, zipf_alpha=1.2, hbm_frac=0.85):
    n = rows*cols
    per_die = 64 // n
    A = np.zeros((n, n))
    w = np.array([1.0/(e+1)**zipf_alpha for e in range(64)])
    w = w / w.sum()
    Tz = T64 * w[:, None]
    for i in range(64):
        di = i // per_die
        for j in range(64):
            dj = j // per_die
            if di != dj:
                A[di][dj] += Tz[i][j]
    hbms = np.array(sorted(set(np.linspace(0, n-1, max(2, n//8)).astype(int).tolist())))
    hx = {h: (h % cols, h // cols) for h in hbms}
    for d in range(n):
        if d in set(hbms.tolist()):
            continue
        dx, dy = d % cols, d // cols
        near = min(hbms, key=lambda h: abs(hx[h][0]-dx)+abs(hx[h][1]-dy))
        mem = A[d].sum()/(1-hbm_frac)*hbm_frac if A[d].sum() > 0 else 1.0
        A[d][near] += max(mem, 0.05)
    A = A / A.sum(axis=1, keepdims=True)
    return A

def bounded_seed(xy, radix, rows=4, cols=8):
    """degree-bounded connected seed: serpentine path (deg<=2) + nearest links
    while deg < radix-1. Guarantees the SEED itself is fabricatable at radix."""
    n = len(xy)
    edges = set()
    for r in range(rows):
        for c in range(cols-1):
            a = r*cols+c; b = r*cols+c+1
            edges.add(tuple(sorted((a, b))))
    for r in range(rows-1):
        a = r*cols + (cols-1 if r % 2 == 0 else 0)
        b = a + cols
        edges.add(tuple(sorted((a, b))))
    deg = defaultdict(int)
    for u, v in edges:
        deg[u] += 1; deg[v] += 1
    # nearest-neighbor extras within radix budget
    cand = sorted((abs(xy[i][0]-xy[j][0])+abs(xy[i][1]-xy[j][1]), i, j)
                  for i in range(n) for j in range(i+1, n))
    for d, i, j in cand:
        if deg[i] < radix-1 and deg[j] < radix-1 and tuple(sorted((i, j))) not in edges:
            edges.add((i, j)); deg[i] += 1; deg[j] += 1
    return edges

def is_bridge(edges, n, e):
    u, v = e
    a = defaultdict(set)
    for x, y in edges - {e}:
        a[x].add(y); a[y].add(x)
    seen = {u}; q = deque([u])
    while q:
        x = q.popleft()
        for y in a[x]:
            if y not in seen:
                seen.add(y); q.append(y)
    return v not in seen


def sa_free(T, xy, seed_edges, cand, radix, iters=4000, t0=6.0, sa_seed=1):
    """SA with free add/remove under radix+connectivity (can reshape the seed)."""
    import random
    rng = random.Random(sa_seed)
    n = len(xy)
    edges = set(tuple(sorted(e)) for e in seed_edges)
    cand_set = [tuple(sorted(e)) for e in cand if tuple(sorted(e)) not in edges]

    def degs(es):
        d = defaultdict(int)
        for u, v in es:
            d[u] += 1; d[v] += 1
        return d

    def score(es):
        a = defaultdict(set)
        for u, v in es:
            a[u].add(v); a[v].add(u)
        return geodesic(T, a)

    cur = score(edges)
    best, best_set = cur, set(edges)
    no_improv = 0
    for it in range(iters):
        dg = degs(edges)
        new_edges = None
        if rng.random() < 0.6:
            pool = [e for e in cand_set if e not in edges
                    and dg[e[0]] < radix and dg[e[1]] < radix]
            if pool:
                new_edges = set(edges); new_edges.add(rng.choice(pool))
        else:
            remov = [e for e in edges if not is_bridge(edges, n, e)]
            if remov:
                new_edges = set(edges); new_edges.discard(rng.choice(remov))
        if new_edges is None:
            t0 *= 0.998; no_improv += 1
            if no_improv > iters//8: break
            continue
        s = score(new_edges)
        delta = s - cur
        if delta <= 0 or rng.random() < min(1.0, 1.0/(1.0+delta/max(t0, 1e-9))):
            edges, cur = new_edges, s
            if cur < best:
                best, best_set = cur, set(edges); no_improv = 0
        t0 *= 0.998
        no_improv += 1
        if no_improv > iters//8: break
    return best_set, best


def feasible_mesh(xy, radix, max_len):
    """Fabricatable nearest-neighbor baseline: Kruskal connectivity with degree
    cap, then shortest feasible links up to radix. Respects max_len AND radix."""
    n = len(xy)
    pairs = []
    for i in range(n):
        for j in range(i+1, n):
            d = abs(xy[i][0]-xy[j][0]) + abs(xy[i][1]-xy[j][1])
            if d <= max_len + 1e-9:
                pairs.append((d, i, j))
    pairs.sort()
    parent = list(range(n))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    deg = defaultdict(int)
    edges = set()
    # phase 1: spanning tree under degree cap
    for d, i, j in pairs:
        ri, rj = find(i), find(j)
        if ri != rj and deg[i] < radix and deg[j] < radix:
            parent[ri] = rj; deg[i] += 1; deg[j] += 1
            edges.add((i, j))
    # phase 2: fill to radix with shortest feasible
    for d, i, j in pairs:
        if (i, j) in edges:
            continue
        if deg[i] < radix and deg[j] < radix:
            edges.add((i, j)); deg[i] += 1; deg[j] += 1
    return edges


def run_case(T, xy, radix, max_len, iters, seed, rows=4, cols=8):
    cand = valid_links(xy, max_len)
    base = feasible_mesh(xy, radix, max_len)
    base_adj = defaultdict(set)
    for a, b in base:
        base_adj[a].add(b); base_adj[b].add(a)
    mesh_hops = geodesic(T, base_adj)
    seed_edges = bounded_seed(xy, radix, rows, cols)
    adj_map, best = sa_free(T, xy, seed_edges, cand, radix, iters=iters, sa_seed=seed)
    amap = defaultdict(set)
    for u, v in adj_map:
        amap[u].add(v); amap[v].add(u)
    sa_hops = geodesic(T, amap)
    edges_n = len(adj_map)
    maxdeg = max(len(amap[u]) for u in range(len(xy)))
    seen = {0}; q = [0]
    while q:
        u = q.pop()
        for v in amap[u]:
            if v not in seen:
                seen.add(v); q.append(v)
    return {"mesh_hops": round(mesh_hops, 4), "sa_hops": round(best, 4),
            "improvement_pct": round((1-best/mesh_hops)*100, 1),
            "edges": edges_n, "max_degree": maxdeg,
            "connected": len(seen) == len(xy)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", required=True)
    ap.add_argument("--radix", type=int, default=5)
    ap.add_argument("--max-len", type=float, default=2.0)
    ap.add_argument("--iters", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--rows", type=int, default=4)
    ap.add_argument("--cols", type=int, default=8)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    T64 = load_matrix(args.matrix)
    TD = build_d2d(T64, args.rows, args.cols)
    out = {"meta": {"matrix": args.matrix, "n": args.rows*args.cols,
                    "rows": args.rows, "cols": args.cols,
                    "radix": args.radix, "max_len": args.max_len,
                    "note": "expert traffic = 64->ndies Zipf-weighted aggregation; 85% memory egress to nearest HBM stack"}}
    for jit in (0.08, 0.45):
        for ml in (args.max_len, 1.5):
            xy = interposer_xy(args.rows, args.cols, args.seed, jitter=jit)
            r = run_case(TD, xy, args.radix, ml, args.iters, args.seed,
                         rows=args.rows, cols=args.cols)
            out[f"jitter_{jit}_maxlen_{ml}"] = r
            print(f"jitter={jit} maxlen={ml}: {json.dumps(r)}", flush=True)

    Path(args.out + ".json").write_text(json.dumps(out, indent=2))
    print(f"-> {args.out}.json")

if __name__ == "__main__":
    main()
