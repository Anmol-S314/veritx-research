#!/usr/bin/env python3
"""ensemble_synthesize.py — P0: robustness — optimize topology over an ENSEMBLE
of MoE traffic matrices, not a single matrix.

Ensemble construction (from one trace-derived base matrix):
  top{k}    row i keeps its top-k entries (renormalized)  — expert fanout k
  uniform   all-to-all equal traffic                       — worst-case serving
  phase{j}  j-th random sparse phase (each src picks m random dsts)
            — serving-time skew / routing churn

Objective modes:
  mean   minimize average traffic-weighted hops across train members
  worst  minimize the maximum across train members

Evaluation is honest ML-style: synthesize on TRAIN members, report on held-out
TEST members, vs (a) single-matrix-trained topo, (b) mesh baseline. Also reports
min bisection bandwidth (traffic-agnostic sparsest-cut-style floor).

Usage:
  python3 ensemble_synthesize.py --matrix dse/inputs/qwen_moe_64d.mat --k 8 \
      --radix 5 --max-len 2 --iters 3000 --out .noc_p0/ensemble
"""
import argparse, json, sys, random
from pathlib import Path
import numpy as np
from collections import defaultdict, deque

sys.path.insert(0, str(Path(__file__).resolve().parent))
from milp_topology_v2 import grid_xy, valid_links, base_mesh, load_matrix

# ---------------- ensemble ----------------
def build_ensemble(T, ks=(1, 2, 4, 8), n_phases=6, m_phase=8, seed=13):
    ens = {}
    n = T.shape[0]
    for k in ks:
        A = np.zeros_like(T)
        for i in range(n):
            idx = np.argsort(T[i])[::-1][:k]
            w = T[i][idx]
            s = w.sum()
            if s > 0:
                A[i][idx] = w/s
        ens[f"top{k}"] = A
    U = np.ones_like(T) - np.eye(n)*np.ones(n)
    U = U / U.sum(axis=1, keepdims=True)
    ens["uniform"] = U
    rng = np.random.default_rng(seed)
    for j in range(n_phases):
        A = np.zeros_like(T)
        for i in range(n):
            dsts = rng.choice([x for x in range(n) if x != i], size=m_phase, replace=False)
            w = rng.dirichlet(np.ones(m_phase))
            A[i][dsts] = w
        ens[f"phase{j}"] = A
    return ens

# ---------------- graph utils ----------------
def adj_of(n, edges):
    a = defaultdict(set)
    for u, v in edges:
        a[u].add(v); a[v].add(u)
    return a

def apsp_hops(adj, n):
    D = []
    for s in range(n):
        d = [-1]*n; d[s] = 0; q = deque([s])
        while q:
            u = q.popleft()
            for v in adj[u]:
                if d[v] < 0:
                    d[v] = d[u]+1; q.append(v)
        D.append(d)
    return D

def whops(T, D, n):
    tot = ws = 0.0
    for i in range(n):
        for j in range(n):
            if i != j and T[i][j] > 0:
                d = D[i][j]
                tot += T[i][j]*(d if d > 0 else 1e6)
                ws += T[i][j]
    return tot/max(ws, 1e-12)

def min_bisection(adj, n, tries=200, seed=3):
    """random-bisect lower-bound estimate of bisection bandwidth (edges crossing)."""
    rng = random.Random(seed)
    best = None
    nodes = list(range(n))
    for _ in range(tries):
        rng.shuffle(nodes)
        S = set(nodes[:n//2])
        c = sum(1 for u in S for v in adj[u] if v not in S)
        best = c if best is None else min(best, c)
    return best

# ---------------- SA over ensemble objective ----------------
def sa_ensemble(mats, xy, base_edges, cand, radix, iters=3000, t0=6.0, seed=1,
                obj="mean", log=None):
    rng = random.Random(seed)
    n = len(xy)
    base = set(tuple(sorted(e)) for e in base_edges)
    cand_set = [tuple(sorted(e)) for e in cand if tuple(sorted(e)) not in base]
    edges = set(base)

    def score(edgeset):
        a = adj_of(n, edgeset)
        D = apsp_hops(a, n)
        vals = [whops(M, D, n) for M in mats]
        return max(vals) if obj == "worst" else sum(vals)/len(vals), vals

    cur, _ = score(edges)
    best, best_set = cur, set(edges)
    no_improv = 0
    for it in range(iters):
        mv = rng.random()
        new_edges = None
        if mv < 0.65 or len(edges) <= len(base):
            pool = [e for e in cand_set if e not in edges]
            deg = defaultdict(int)
            for u, v in edges:
                deg[u] += 1; deg[v] += 1
            pool = [e for e in pool if deg[e[0]] < radix and deg[e[1]] < radix]
            if pool:
                new_edges = set(edges); new_edges.add(rng.choice(pool))
        else:
            removable = [e for e in edges if e not in base and not is_bridge(edges, n, e)]
            if removable:
                new_edges = set(edges); new_edges.discard(rng.choice(removable))
        if new_edges is None:
            t0 *= 0.998; no_improv += 1
            if no_improv > iters//8: break
            continue
        new_score, _ = score(new_edges)
        delta = new_score - cur
        if delta <= 0 or rng.random() < min(1.0, 1.0/(1.0+delta/max(t0, 1e-9))):
            edges = new_edges; cur = new_score
            if cur < best:
                best, best_set = cur, set(edges); no_improv = 0
        t0 *= 0.998
        no_improv += 1
        if no_improv > iters//8: break
    return best_set, best

def is_bridge(edges, n, e):
    u, v = e
    a = adj_of(n, edges - {e})
    seen = {u}; q = deque([u])
    while q:
        x = q.popleft()
        for y in a[x]:
            if y not in seen:
                seen.add(y); q.append(y)
    return v not in seen

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", required=True)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--radix", type=int, default=5)
    ap.add_argument("--max-len", type=float, default=2.0)
    ap.add_argument("--iters", type=int, default=3000)
    ap.add_argument("--obj", choices=["mean", "worst"], default="mean")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    T = load_matrix(args.matrix)
    n = T.shape[0]
    kk = int(round(np.sqrt(n)))
    assert kk*kk == n
    xy = grid_xy(kk)
    cand = valid_links(xy, args.max_len)
    base = base_mesh(xy)

    ens = build_ensemble(T)
    train_names = ["top1", "top2", "top4", "top8", "uniform"]
    test_names = [x for x in ens if x not in train_names]
    train_mats = [ens[x] for x in train_names]

    # baselines
    mesh_edges = set(tuple(sorted(e)) for e in base)
    # single-matrix SA (ledger baseline behavior)
    single_set, _ = sa_ensemble([T], xy, base, cand, args.radix, args.iters, seed=args.seed, obj="mean")
    # ensemble SA
    ens_set, _ = sa_ensemble(train_mats, xy, base, cand, args.radix, args.iters,
                             seed=args.seed, obj=args.obj)

    def evaluate(edgeset):
        a = adj_of(n, edgeset)
        D = apsp_hops(a, n)
        per = {nm: round(whops(ens[nm], D, n), 4) for nm in ens}
        mb = min_bisection(a, n)
        deg = max(len(a[i]) for i in range(n))
        return {"per_member": per,
                "train_mean": round(np.mean([per[x] for x in train_names]), 4),
                "test_mean": round(np.mean([per[x] for x in test_names]), 4),
                "worst_member": max(per.values()),
                "min_bisection": mb, "max_degree": deg}

    res = {
        "meta": {"matrix": args.matrix, "n": n, "radix": args.radix,
                 "max_len": args.max_len, "iters": args.iters, "obj": args.obj,
                 "train": train_names, "test": test_names},
        "mesh": evaluate(mesh_edges),
        "single_matrix_sa": evaluate(single_set),
        f"ensemble_{args.obj}_sa": evaluate(ens_set),
    }
    Path(args.out + ".json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    main()
