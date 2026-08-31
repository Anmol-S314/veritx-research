#!/usr/bin/env python3
"""milp_exactness.py — P0: 64-node optimality-gap study (coarse-to-fine).

At N=64 the TMCF MILP does not converge on this box (memory), so exactness is
approached hierarchically:

  1. COARSE: cluster the 8x8 grid into 4x4 supernodes (2x2 blocks); aggregate
     traffic; solve the TMCF MILP EXACTLY at n=16 (HiGHS, continuous flows,
     ~250 link binaries).
  2. LIFT: expand supernode links to physical node-pair links (closest pair);
     wire intra-block links up to radix.
  3. REFINE: SA at n=64 seeded from the lift.
  4. STABILITY: multi-seed plain-SA from mesh seed (5 seeds).

Reported: mesh / each SA seed / coarse-to-fine traffic-weighted hops, plus the
16-node exact optimum value (aggregated objective) as the coarse design point.

Usage:
  python3 milp_exactness.py --matrix tracks/t3-topology/dse/inputs/qwen_moe_64d.mat \
      --out .noc_p0/exactness
"""
import argparse, json, sys
from pathlib import Path
import numpy as np
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from milp_topology_v2 import (grid_xy, valid_links, base_mesh, geodesic,
                              sa_synthesize, solve_tmcf, load_matrix)

def cluster_matrix(T, kk=8, block=2):
    """64 -> 16 supernode aggregation (sum of block traffic)."""
    nb = kk // block
    A = np.zeros((nb*nb, nb*nb))
    for i in range(kk):
        for j in range(kk):
            si = (i//block)*nb + (j//block)
            for y in range(kk):
                for x in range(kk):
                    sj = (y//block)*nb + (x//block)
                    if si != sj:
                        A[si][sj] += T[i*kk+j][y*kk+x]
    A = A / A.sum(axis=1, keepdims=True)
    return A

def lift(sup_edges, kk=8, block=2, radix=5):
    """supernode links -> physical links (closest node pair across blocks)."""
    nb = kk // block
    xy = grid_xy(kk)
    def sup_of(node):
        r, c = divmod(node, kk)
        return (r//block)*nb + (c//block)
    def center(s):
        r, c = divmod(s, nb)
        nodes = [ (r*block+di)*kk + c*block+dj for di in range(block) for dj in range(block)]
        return nodes
    edges = set()
    deg = defaultdict(int)
    # inter-block links: closest physical pair between the two blocks
    for (s, t) in sup_edges:
        ns, nt = center(s), center(t)
        best = min(((abs(xy[a][0]-xy[b][0])+abs(xy[a][1]-xy[b][1]), a, b)
                    for a in ns for b in nt), key=lambda x: x[0])
        _, a, b = best
        e = tuple(sorted((a, b)))
        if deg[a] < radix and deg[b] < radix:
            edges.add(e); deg[a] += 1; deg[b] += 1
        else:
            # fallback: any feasible pair
            for a2 in ns:
                for b2 in nt:
                    e2 = tuple(sorted((a2, b2)))
                    if deg[a2] < radix and deg[b2] < radix:
                        edges.add(e2); deg[a2] += 1; deg[b2] += 1
                        break
                else:
                    continue
                break
    # intra-block wiring (ring of 4 = degree 2)
    for s in range(nb*nb):
        nodes = center(s)
        for x, y in zip(nodes, nodes[1:]):
            e = tuple(sorted((x, y)))
            if deg[x] < radix and deg[y] < radix:
                edges.add(e); deg[x] += 1; deg[y] += 1
    return edges

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", required=True)
    ap.add_argument("--radix", type=int, default=5)
    ap.add_argument("--max-len", type=float, default=2.0)
    ap.add_argument("--iters", type=int, default=6000)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    T = load_matrix(args.matrix)
    kk = 8
    xy = grid_xy(kk)
    cand = valid_links(xy, args.max_len)
    base = base_mesh(xy)

    # baselines
    base_adj = defaultdict(set)
    for a, b in base:
        base_adj[a].add(b); base_adj[b].add(a)
    mesh_hops = geodesic(T, base_adj)

    # multi-seed plain SA
    sa_runs = []
    for sd in range(1, args.seeds+1):
        adj, best = sa_synthesize(T, xy, base, cand, args.radix, iters=args.iters, seed=sd)
        sa_runs.append(round(best, 4))
        print(f"SA seed {sd}: {best:.4f}", flush=True)

    # coarse-to-fine
    T16 = cluster_matrix(T, kk, 2)
    xy16 = grid_xy(4)
    cand16 = valid_links(xy16, args.max_len)
    base16 = base_mesh(xy16)
    res, all_links, Lidx, dem, dir_edges, eid, L, F, E, xv_f, fv_f = solve_tmcf(
        T16, xy16, base16, cand16, args.radix, args.timeout, max_nodes=20)
    if res.x is None:
        print("coarse MILP failed"); sys.exit(1)
    xv = np.round(res.x[:L])
    sup_chosen = [e for e, k in Lidx.items() if xv[k] > 0.5]
    coarse_val = float(res.fun)
    db = getattr(res, "mip_dual_bound", None)
    status = str(res.message)
    print(f"coarse MILP (n=16): obj={coarse_val:.1f} dual_bound={db} status={status}", flush=True)

    lifted = lift(sup_chosen, kk, 2, args.radix)
    lift_adj = defaultdict(set)
    for a, b in lifted:
        lift_adj[a].add(b); lift_adj[b].add(a)
    lift_hops = geodesic(T, lift_adj)
    # refine at n=64: lifted structure protected, SA adds shortcuts within radix
    adj_ref, ref_best = sa_synthesize(T, xy, lifted, cand, args.radix, iters=args.iters, seed=99)

    out = {
        "meta": {"matrix": args.matrix, "radix": args.radix, "max_len": args.max_len,
                 "iters": args.iters, "seeds": args.seeds},
        "mesh_hops": round(mesh_hops, 4),
        "sa_multi_seed": {"runs": sa_runs, "best": min(sa_runs),
                          "mean": round(float(np.mean(sa_runs)), 4),
                          "std": round(float(np.std(sa_runs)), 4)},
        "coarse_milp_n16": {"obj_total_hops": round(coarse_val, 1),
                            "dual_bound": None if db is None else round(float(db), 1),
                            "status": status},
        "lifted_hops": round(lift_hops, 4),
        "refined_hops": round(ref_best, 4),
        "gap_best_vs_mesh_pct": round((1-min(min(sa_runs), ref_best)/mesh_hops)*100, 1),
    }
    Path(args.out + ".json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
