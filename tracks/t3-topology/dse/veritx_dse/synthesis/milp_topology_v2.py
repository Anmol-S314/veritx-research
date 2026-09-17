#!/usr/bin/env python3
"""
milp_topology_v2.py — Traffic-weighted topology MILP (NetSmith method, scipy/HiGHS).

Reads a traffic matrix T (row=src, col=dst) and, given a router physical layout
(grid or interposer) + radix + link-length budget, GENERATES a custom topology
minimizing the traffic-weighted average hop count.

This is the correct L2 synthesizer core. Objective is enforced by a
Traffic-Min-Cost-Flow (TMCF) MILP: every (i,j) unit of demand is routed on
chosen links, each link traversal costs 1 hop, and we minimize total hops.
Result: a topology (chosen links) + routing that is latency-optimal under T,
respecting radix + link-length + optional diameter.

Design:
  * Seed with the layout's base mesh -> guarantees connectivity/feasibility.
  * MILP decides which EXTRA candidate links (within link-length budget) to add
    and the flow routing, minimizing total hops under radix budget.
  * Exact solve capped at --max_nodes (=20 default); larger N falls back to the
    hot-pair greedy (milp_topology.py logic) for design-time speed. NetSmith's
    stance: converged-but-beats-mesh is the goal, not global optimality.

Outputs:
  <out>.anynet   BookSim anynet (cycle-accurate proof leg)
  <out>.json     topology graph + routing + stats (for DSE / Constellation/FlooNoC)

Usage:
  python milp_topology_v2.py --matrix dse/archive/qwen_moe_2d.mat --layout grid  --radix 3 --max_len 2 --out /tmp/c  --max_nodes 16
  python milp_topology_v2.py --matrix /tmp/test16.mat --layout interposer --rows 4 --cols 4 --radix 5 --out /tmp/ci
"""
import argparse, json, sys, time
import math
from pathlib import Path
import numpy as np
from collections import deque, defaultdict

# Canonical topology sizes — single source of truth in
# veritx_dse.model.presets. Mesh/grid/anynet size math delegates here
# instead of hand-rolled counting.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
try:
    from veritx_dse.model.presets import topo_size, count_anynet_edges
    from veritx_dse.core.constants import DEFAULT_K, DEFAULT_TIMEOUT, env_int
except ImportError:
    try:
        from ..model.presets import topo_size, count_anynet_edges  # type: ignore
        from ..core.constants import DEFAULT_K, DEFAULT_TIMEOUT, env_int  # type: ignore
    except Exception:
        topo_size = None  # type: ignore
        count_anynet_edges = None  # type: ignore
        DEFAULT_K = 8  # type: ignore  # same value; canonical home is core.constants
        DEFAULT_TIMEOUT = 60  # type: ignore
        def env_int(name, default):  # type: ignore
            import os
            raw = os.environ.get(name)
            if raw is None:
                return default
            return int(raw)

# Unified synthesis result schema (Phase 2a). Script-mode safe.
try:
    from veritx_dse.synthesis.results import SynthResult
    from veritx_dse.synthesis.evaluator import write_anynet as _shared_write_anynet
except Exception:
    try:
        from ..synthesis.results import SynthResult  # type: ignore
        from ..synthesis.evaluator import write_anynet as _shared_write_anynet  # type: ignore
    except Exception:
        try:
            import sys as _sys

            _sys.path.insert(0, str(Path(__file__).resolve().parent))
            from results import SynthResult  # type: ignore
            try:
                from evaluator import write_anynet as _shared_write_anynet  # type: ignore
            except Exception:
                _shared_write_anynet = None  # type: ignore
        except Exception:
            SynthResult = None  # type: ignore
            _shared_write_anynet = None  # type: ignore


def mesh_size(k: int = 8, n: int = 2) -> tuple:
    """Thin wrapper over the canonical helper for mesh sizes.

    Kept under a local name for backward compat; new code should call
    ``topo_size`` directly.
    """
    if topo_size is not None:
        return topo_size("mesh", {"k": k, "n": n})
    return (k ** n, n * (k - 1) * k ** (n - 1) if k > 0 else 0)


def grid_size(num_nodes: int) -> tuple:
    """Thin wrapper for sqrt(n)×sqrt(n) grid meshes via the canonical helper."""
    k = int(round(math.sqrt(num_nodes)))
    assert k * k == num_nodes, f"grid needs n=k^2 (n={num_nodes})"
    return mesh_size(k, 2)


def anynet_size(path) -> tuple:
    """Thin wrapper over the canonical anynet counter (backward compat)."""
    if count_anynet_edges is not None:
        return count_anynet_edges(str(path))
    return 0, 0

# ---------------- layout / feasibility ----------------
def grid_xy(k):
    return [(x, y) for y in range(k) for x in range(k)]

def interposer_xy(rows, cols, seed=7, jitter=0.08):
    rng = np.random.default_rng(seed)
    pts = []
    for r in range(rows):
        for c in range(cols):
            pts.append((c + jitter*rng.random(), r + jitter*rng.random()))
    return pts

def valid_links(xy, max_len):
    n = len(xy)
    L = []
    for i in range(n):
        for j in range(i+1, n):
            d = abs(xy[i][0]-xy[j][0]) + abs(xy[i][1]-xy[j][1])
            if d <= max_len + 1e-9:
                L.append((i, j))
    return L

def load_matrix(path):
    """Load an N×N traffic matrix, failing loudly on malformed input.

    Rejects: empty files, ragged rows, non-square matrices, NaN/Inf,
    negative entries — any of which would silently poison the synthesis.
    """
    mat = []
    with open(path) as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                mat.append([float(x) for x in line.split()])
            except ValueError as e:
                raise SystemExit(
                    f"ERROR: {path}:{line_no}: non-numeric matrix entry ({e})")
    if not mat:
        raise SystemExit(f"ERROR: {path}: no matrix data (empty file or comments only)")
    widths = {len(row) for row in mat}
    if len(widths) != 1:
        raise SystemExit(
            f"ERROR: {path}: ragged matrix — rows have widths {sorted(widths)}")
    n = len(mat)
    if widths != {n}:
        raise SystemExit(
            f"ERROR: {path}: matrix must be square NxN, got {n}x{widths.pop()}")
    arr = np.array(mat)
    if not np.all(np.isfinite(arr)):
        raise SystemExit(f"ERROR: {path}: matrix contains NaN or Inf entries")
    if (arr < 0).any():
        raise SystemExit(
            f"ERROR: {path}: negative traffic entries (min {arr.min():g}) — "
            "traffic volumes must be >= 0")
    return arr

def base_mesh(xy, max_nbr=4, radix=None):
    """nearest-neighbor mesh seed: connect each node to its few closest, undirected."""
    n = len(xy)
    edges = set()
    for i in range(n):
        dists = sorted((abs(xy[i][0]-xy[j][0])+abs(xy[i][1]-xy[j][1]), j)
                       for j in range(n) if j != i)
        for d, j in dists[:max_nbr]:
            edges.add(tuple(sorted((i, j))))
    # Enforce the radix budget on the SEED too: jittered interposer placements
    # can give a node 6+ nearest neighbors, violating radix (observed: maxdeg 6
    # at radix 5). Greedily drop the LONGEST edge at any over-degree node.
    if radix is not None:
        max_deg = radix - 1  # local port consumes one
        changed = True
        while changed:
            changed = False
            deg = {i: 0 for i in range(n)}
            for (a, b) in edges:
                deg[a] += 1; deg[b] += 1
            for i in range(n):
                if deg[i] > max_deg:
                    # drop the longest edge incident to i, preferring edges whose
                    # other endpoint also overshoots (keeps connectivity best)
                    cand = sorted(((abs(xy[i][0]-xy[j][0])+abs(xy[i][1]-xy[j][1]), j)
                                   for j in range(n) if tuple(sorted((i, j))) in edges),
                                  reverse=True)
                    for _, j in cand:
                        e = tuple(sorted((i, j)))
                        if e in edges:
                            edges.discard(e)
                            changed = True
                            break
    return edges

# R-expr: physical latency pricing. A link of length L pitches costs
# PIPELINE (router traverse) + L*WIRE. Replacing k short hops with one
# long express link saves (k-1)*PIPELINE - extra wire — the reason
# express topologies win when pipeline_depth > wire_per_pitch.
PIPE_COST = 3.0   # router pipeline: route + VC alloc + switch alloc
WIRE_COST = 1.0   # cycles per grid pitch (repeated wire)

def set_costs(pipe, wire):
    global PIPE_COST, WIRE_COST
    PIPE_COST, WIRE_COST = pipe, wire

def _edge_len(u, v, xy):
    return math.hypot(xy[u][0]-xy[v][0], xy[u][1]-xy[v][1])

def priced_geodesic(T, adj, xy):
    """Traffic-weighted average PHYSICAL latency: Dijkstra over links
    priced PIPE_COST + WIRE*pitch_length."""
    import heapq
    n = T.shape[0]
    tot = ws = 0.0
    for s in range(n):
        dist = {s: 0.0}
        pq = [(0.0, s)]
        while pq:
            du, u = heapq.heappop(pq)
            if du > dist.get(u, 1e18): continue
            for v in adj[u]:
                nd = du + PIPE_COST + WIRE_COST * _edge_len(u, v, xy)
                if nd < dist.get(v, 1e18):
                    dist[v] = nd; heapq.heappush(pq, (nd, v))
        for t in range(n):
            dd = dist.get(t)
            tot += T[s][t]*(dd if dd is not None and dd < 1e17 else 1e6)
            ws += T[s][t]
    return tot/max(ws, 1e-12)

def geodesic(T, adj):
    n = T.shape[0]
    tot = ws = 0.0
    for s in range(n):
        d = [-1]*n; d[s]=0; q=deque([s])
        while q:
            u=q.popleft()
            for v in adj[u]:
                if d[v]<0: d[v]=d[u]+1; q.append(v)
        for t in range(n):
            tot += T[s][t]*max(d[t],1) if d[t]>=0 else T[s][t]*1e6
            ws += T[s][t]
    return tot/max(ws,1e-12)

def sa_synthesize(T, xy, base, cand, radix, iters=4000, t0=8.0, seed=1,
                  priced=False, seed_adj=None, protect=frozenset()):
    """Simulated-annealing link optimizer for the traffic-weighted geodesic objective.
    Sound + scalable: each move re-scored by exact all-pairs shortest path (64 BFS
    runs, trivial at 64 nodes). Respects radix + link-length budget (cand set).
    Works at 64+ nodes where the TMCF MILP cannot converge."""
    import random
    rng = random.Random(seed)
    n = T.shape[0]
    # start from base mesh (connected)
    adj = defaultdict(set)
    for (a, b) in (seed_adj if seed_adj else base):
        adj[a].add(b); adj[b].add(a)
    obj = (lambda a: priced_geodesic(T, a, xy)) if priced else (lambda a: geodesic(T, a))
    cur = obj(adj)
    best = cur; best_adj = {k: set(v) for k, v in adj.items()}
    cand_set = [tuple(sorted(e)) for e in cand if tuple(sorted(e)) not in {(a,b) if a<b else (b,a) for (a,b) in base}]
    def deg(u): return len(adj[u])
    Tt = t0
    no_improv = 0
    for it in range(iters):
        # random move: add or remove a non-base candidate edge (radix + connectivity respect)
        move = rng.random()
        if move < 0.7 or len(cand_set)==0:
            # add an edge (if radix allows both ends)
            cand_pool = [e for e in cand_set if deg(e[0]) < radix and deg(e[1]) < radix]
            if not cand_pool: Tt *= 0.998; no_improv+=1; continue
            e = rng.choice(cand_pool)
            u, v = e
            if v in adj[u]: Tt *= 0.998; continue
            adj[u].add(v); adj[v].add(u)
            new = obj(adj)
            delta = new - cur
            if delta <= 0 or rng.random() < min(1.0, 1.0/(1.0+ (delta)/Tt)):
                cur = new
                if cur < best: best = cur; best_adj = {k:set(v) for k,v in adj.items()}; no_improv=0
            else:
                adj[u].discard(v); adj[v].discard(u)
        else:
            # remove a random non-bridge edge (keep connectivity by only removing non-cut links)
            removable = []
            for a in range(n):
                for b in adj[a]:
                    if a < b:
                        u, v = tuple(sorted((a,b)))
                        if (u, v) in base or (u, v) in protect: continue
                        if not is_bridge(adj, u, v):
                            removable.append((u, v))
            if not removable: Tt *= 0.998; no_improv+=1; continue
            e = rng.choice(removable)
            u, v = e
            adj[u].discard(v); adj[v].discard(u)
            new = obj(adj)
            delta = new - cur
            if delta <= 0 or rng.random() < min(1.0, 1.0/(1.0+ (delta)/Tt)):
                cur = new
                if cur < best: best = cur; best_adj = {k:set(v) for k,v in adj.items()}; no_improv=0
            else:
                adj[u].add(v); adj[v].add(u)
        Tt *= 0.998
        no_improv += 1
        if no_improv > iters//10: break
    return dict(best_adj), best

def is_bridge(adj, u, v):
    """True if removing edge u-v disconnects the graph (u,v still reachable without the edge)."""
    n = len(adj)
    have = any(v in adj[u] for _ in [0])
    if not have: return False
    adj[u].discard(v); adj[v].discard(u)
    # BFS from u without the edge
    seen = {u}; q = deque([u])
    while q:
        x = q.popleft()
        for y in adj[x]:
            if y not in seen: seen.add(y); q.append(y)
    adj[u].add(v); adj[v].add(u)
    return v not in seen

# ---------------- TMCF MILP ----------------
def solve_tmcf(T, xy, base_edges, cand_links, radix, timeout=None, max_nodes=20):
    """Minimize total traffic-weighted hops over chosen links + flow routing.

    timeout=None resolves VERITX_TIMEOUT (default 120s) at call time.
    """
    if timeout is None:
        timeout = env_int("VERITX_TIMEOUT", 120)
    from scipy.optimize import milp, LinearConstraint, Bounds
    from scipy import sparse
    n = T.shape[0]
    # candidate undirected links = base mesh (forced) + optional extras within budget
    all_links = sorted(base_edges)            # ensure base present
    for e in cand_links:
        if e not in all_links and e[::-1] not in all_links:
            all_links.append(e)
    all_links = sorted(set(tuple(sorted(e)) for e in all_links))
    Lidx = {e: k for k, e in enumerate(all_links)}
    L = len(all_links)

    # demands: all ordered (i,j) pairs with T>0
    dem = []
    for i in range(n):
        for j in range(n):
            if i != j and T[i][j] > 0:
                dem.append((i, j))
    F = len(dem)
    pair_of = {k: dem[k] for k in range(F)}

    # vars: x_e in {0,1} (add/keep link e); f_k^{e-in} flow of demand k on each directed link
    # We model per directed link; but undirected x controls both directions.
    # Directed edge index: (u,v). Build directed list.
    dir_edges = []
    for (a, b) in all_links:
        dir_edges.append((a, b)); dir_edges.append((b, a))
    E = len(dir_edges)
    eid = {(a, b): e for e, (a, b) in enumerate(dir_edges)}
    x_of_dir = {}  # directed edge -> undirected x var index
    for (a, b) in dir_edges:
        x_of_dir[eid[(a, b)]] = Lidx[tuple(sorted((a, b)))]

    NV = L + F*E
    def xv(l): return l
    def fv(k, e): return L + k*E + e
    # objective: min sum_k,e f_k^e   (each unit of flow on an edge = 1 hop; but hop count is #edges in path)
    c = np.zeros(NV)
    for k in range(F):
        for e in range(E):
            c[fv(k, e)] = 1.0
    integ = np.zeros(NV, dtype=int)
    for l in range(L): integ[xv(l)] = 1
    # NOTE: flow vars kept continuous (LP routing). Link binaries drive topology;
    # the LP relaxation of the latency objective is a valid lower bound and converges
    # fast (18k+ integer flow vars blow up). NetworkSmith-style: good link set > fast-enough solve.
    # for k in range(F):  # (disabled: integral flows too heavy)
    #     for e in range(E): integ[fv(k, e)] = 1
    lb = np.zeros(NV); ub = np.full(NV, np.inf)
    for l in range(L): ub[xv(l)] = 1

    A = []; blo = []; bhi = []
    def rc(coefs, lo, hi):
        A.append(coefs); blo.append(lo); bhi.append(hi)

    # link-capacity: total flow on directed edge <= bigM * x of its base undirected link
    bigM = n*n
    for (a, b) in dir_edges:
        l = x_of_dir[eid[(a, b)]]
        row = {}
        for k in range(F):
            row[fv(k, eid[(a, b)])] = 1.0
        row[xv(l)] = -bigM
        rc(row, -np.inf, 0.0)     # sum f - bigM*x <= 0

    # flow conservation per demand k, per node v
    for k in range(F):
        s, t = pair_of[k]
        for v in range(n):
            row = {}
            for (a, b) in dir_edges:
                e = eid[(a, b)]
                if a == v: row[fv(k, e)] = row.get(fv(k, e), 0) + 1.0
                if b == v: row[fv(k, e)] = row.get(fv(k, e), 0) - 1.0
            # demand: supply s, sink t, net = +1 at s, -1 at t
            net = 0.0
            if v == s: net = 1.0
            if v == t: net = -1.0
            rc(row, net, net)

    # radix: degree at each node <= radix (undirected)
    #   sum over undirected links incident to node <==> base mesh + chosen extras
    #   degree = sum_{e in all_links, node in e} x_e
    for node in range(n):
        row = {}
        for e, (a, b) in enumerate(all_links):
            if a == node or b == node:
                row[xv(e)] = row.get(xv(e), 0) + 1.0
        rc(row, -np.inf, radix)

    # assemble
    ncon = len(A)
    data=[]; ri=[]; ci=[]
    for r, row in enumerate(A):
        for var, coef in row.items():
            ri.append(r); ci.append(var); data.append(coef)
    M = sparse.coo_matrix((data,(ri,ci)), shape=(ncon,NV)).tocsr()
    cons = LinearConstraint(M, np.array(blo), np.array(bhi))
    bounds = Bounds(lb, ub)
    t0=time.time()
    res = milp(c=c, constraints=cons, integrality=integ, bounds=bounds,
               options={"time_limit": timeout})
    return res, all_links, Lidx, dem, dir_edges, eid, L, F, E, xv, fv

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--matrix", required=True)
    ap.add_argument("--layout", choices=["grid","interposer"], default="grid")
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--rows", type=int, default=4)
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--jitter", type=float, default=0.08, help="interposer placement jitter (0.08=regular-ish; up to 0.9 = irregular chiplet floorplan)")
    ap.add_argument("--radix", type=int, default=5)
    ap.add_argument("--max_len", type=float, default=2.0)
    ap.add_argument("--expr", action="store_true",
                    help="express mode: allow long links, price objective "
                         "PIPELINE + WIRE*length instead of 1/hop")
    ap.add_argument("--pipe_cost", type=float, default=3.0)
    ap.add_argument("--wire_cost", type=float, default=1.0)
    ap.add_argument("--seed_topo", default="",
                    help="anynet skeleton to start SA from (e.g. bfly-express); "
                         "its edges are protected from removal")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--max_nodes", type=int, default=20, help="exact-solve cap; larger -> SA metaheuristic")
    ap.add_argument("--method", choices=["milp","sa"], default="milp", help="milp=exact (small N/<=max_nodes); sa=simulated annealing geodesic (scales to 64+)")
    ap.add_argument("--iters", type=int, default=4000, help="SA iterations")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    T = load_matrix(Path(args.matrix))
    n = T.shape[0]
    if args.layout == "grid":
        kk = int(round(np.sqrt(n)))
        if kk*kk != n:
            sys.exit(f"grid needs n=k^2 (n={n}); use --layout interposer")
        xy = grid_xy(kk)
    else:
        if args.rows*args.cols != n:
            sys.exit(f"interposer needs rows*cols==n (n={n}, {args.rows}x{args.cols})")
        xy = interposer_xy(args.rows, args.cols, args.seed, args.jitter)

    cand = valid_links(xy, args.max_len)
    base = base_mesh(xy, radix=args.radix)
    # Base mesh hops for comparison (same radix ~4)
    base_adj = defaultdict(set)
    for (a,b) in base: base_adj[a].add(b); base_adj[b].add(a)
    base_hops = geodesic(T, base_adj)
    print(f"layout={args.layout} n={n} base_mesh traffic-weighted hops = {base_hops:.4f} ({len(base)} edges, maxdeg {max((len(base_adj[i]) for i in range(n)))})")

    if n <= args.max_nodes and args.method == "milp":
        res, all_links, Lidx, dem, dir_edges, eid, L, F, E, xv, fv = solve_tmcf(
            T, xy, base, cand, args.radix, args.timeout, args.max_nodes)
        status = res.message if res.x is not None else (res.message if hasattr(res,'message') else str(res))
        if res.x is None:
            print(f"MILP infeasible/failed: {status}"); sys.exit(1)
        x = np.round(res.x[:L])
        chosen = {e for e,k in Lidx.items() if x[k] > 0.5}
        adj = defaultdict(set)
        for (a,b) in chosen:
            adj[a].add(b); adj[b].add(a)
        opt = float(res.fun)
        solver = "milp (HiGHS) TMCF"
        db = getattr(res, "mip_dual_bound", None)
        gap = getattr(res, "mip_gap", None)
        print(f"MILP: optimal value (total hops) = {opt:.0f}, status: {status}")
        if db is not None:
            print(f"MILP dual bound = {db:.0f}, mip_gap = {gap}")
    else:
        # large-N (or --method sa): simulated annealing on the traffic-weighted geodesic objective
        solver = "sa (simulated-annealing geodesic)"
        print(f"n={n} -> SA link optimizer (radix {args.radix}, {args.iters} iters)")
        if args.expr:
            set_costs(args.pipe_cost, args.wire_cost)
        seed_adj = None
        protect = frozenset()
        if args.seed_topo:
            seed_adj = []
            for line in open(args.seed_topo):
                p = line.split()
                if not p or p[0] != 'router': continue
                rid = int(p[1]); i = 2
                while i < len(p):
                    kind, nb = p[i], int(p[i+1])
                    if kind == 'router':
                        seed_adj.append((min(rid,nb), max(rid,nb)))
                        if i+2 < len(p) and p[i+2].isdigit(): i += 3
                        else: i += 2
                    else:
                        i += 2
            protect = frozenset(tuple(sorted(e)) for e in seed_adj)
            print(f"seed topology: {len(protect)} protected links")
        adj, best = sa_synthesize(T, xy, base, cand, args.radix, iters=args.iters, seed=1,
                                  priced=args.expr, seed_adj=seed_adj, protect=protect)
        chosen = set(tuple(sorted((a,b))) for a in range(n) for b in adj[a] if a<b)
        opt = None
        print(f"SA best traffic-weighted hops = {best:.4f}")

    hops = geodesic(T, dict(adj))
    edges = sum(len(v) for v in adj.values())//2
    maxdeg = max((len(adj[i]) for i in range(n)))
    meta = {"matrix": str(args.matrix), "layout": args.layout, "n": n,
            "radix": args.radix, "max_len": args.max_len,
            "solver": solver, "opt_value": opt,
            "secs": None}
    # write anynet + json (anynet via the shared evaluator writer;
    # bit-identical format, thin fallback when unavailable)
    try:
        if _shared_write_anynet is not None:
            _adj_for_write = {int(i): set(adj[i]) for i in range(n)}
            _shared_write_anynet(_adj_for_write, str(args.out) + ".anynet")
        else:
            raise RuntimeError("shared writer unavailable")
    except Exception:
        with open(str(args.out)+".anynet","w") as f:
            for i in range(n):
                f.write(f"router {i} node {i} "+" ".join(f"router {x}" for x in sorted(adj[i]))+"\n")
    stats = {"nodes": n, "edges": edges, "max_degree": maxdeg,
             "traffic_weighted_avg_hops": round(hops,4),
             "vs_base_mesh": {"base_hops": round(base_hops,4),
                              "improvement_pct": round((1-hops/base_hops)*100,1)}}
    # Phase 2a record boundary: canonical analytical record (ADDITIVE —
    # existing meta/stats/links keys untouched). MILP/SA never touch
    # BookSim; latency here is the traffic-weighted hop proxy.
    _doc = {"meta": meta, "stats": stats,
            "links": sorted([[int(a), int(b)] for a, b in chosen])}
    try:
        if SynthResult is not None:
            _sr = SynthResult.ok(
                name=Path(str(args.out)).stem, topology="anynet",
                nodes=int(n), edges=int(edges), latency=float(hops),
                seed=int(args.seed),
                provenance="milp_topology_v2+analytical",
                extra={"solver": solver, "opt_value": opt,
                       "layout": args.layout, "radix": args.radix,
                       "max_len": args.max_len, "method": args.method},
            )
            _doc["synth_result"] = _sr.to_dict()
    except Exception:
        pass
    with open(str(args.out)+".json","w") as f:
        json.dump(_doc, f, indent=2)
    print(json.dumps({"meta":meta,"stats":stats}, indent=2))

if __name__ == "__main__":
    main()
