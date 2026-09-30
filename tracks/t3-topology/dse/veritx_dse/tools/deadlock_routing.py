#!/usr/bin/env python3
"""deadlock_routing.py — M2: MCLB routing + deadlock certificate for a custom topology.

Rationale: docs/decisions/modules/tools.md
"""
import argparse, hashlib, json, sys
from collections import defaultdict, deque
import numpy as np

def assert_unit_weights(path):
    """PR D stopgap (verified-PRD §6.4/§7.1): the certifier's route replica
    computes hop-count distances while BookSim's AnyNet Dijkstra uses the
    stored link weight as edge distance. On a weighted topology the
    certified route set would NOT be the executed route set — so weighted
    AnyNet is rejected on this certification path instead of silently
    certifying an unweighted projection.

Rationale: docs/decisions/modules/tools.md
    """
    try:
        from ..core.anynet import parse_anynet_file
    except ImportError:
        import sys as _sys
        from pathlib import Path as _P
        _pkg_root = str(_P(__file__).resolve().parents[1])
        if _pkg_root not in _sys.path:
            _sys.path.insert(0, _pkg_root)
        from core.anynet import parse_anynet_file
    g = parse_anynet_file(path)
    if g.has_non_unit_weights:
        lines = ", ".join(f"line {ln} (w={w})" for ln, w in g.non_unit_weights[:5])
        raise ValueError(
            f"weighted AnyNet is not certifiable by this path (BookSim's "
            f"Dijkstra uses link weights; the certifier's replica is "
            f"hop-count): non-unit weights at {lines}. Either use unit "
            f"weights or extend the replica to consume weights (PR D).")

def parse_anynet(path):
    """nodes -> {neighbor}. Delegates to core.anynet — the ONE parser
    implementing BookSim's anynet.cpp grammar (both line dialects,
    auto-symmetrized router-router edges, sequential-id check).

Rationale: docs/decisions/modules/tools.md
    """
    try:
        from ..core.anynet import parse_anynet_pair
    except ImportError:
        import sys as _sys
        from pathlib import Path as _P
        _pkg_root = str(_P(__file__).resolve().parents[1])
        if _pkg_root not in _sys.path:
            _sys.path.insert(0, _pkg_root)
        from core.anynet import parse_anynet_pair
    return parse_anynet_pair(path)

def load_matrix(path):
    """Load an N×N traffic matrix, failing loudly on malformed input
    (empty, ragged, non-square, NaN/Inf, negative)."""
    mat = []
    with open(path) as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'): continue
            try:
                mat.append([float(x) for x in line.split()])
            except ValueError as e:
                raise SystemExit(f"ERROR: {path}:{line_no}: non-numeric matrix entry ({e})")
    if not mat:
        raise SystemExit(f"ERROR: {path}: no matrix data (empty file or comments only)")
    widths = {len(row) for row in mat}
    if len(widths) != 1:
        raise SystemExit(f"ERROR: {path}: ragged matrix — rows have widths {sorted(widths)}")
    n = len(mat)
    if widths != {n}:
        raise SystemExit(f"ERROR: {path}: matrix must be square NxN, got {n}x{widths.pop()}")
    arr = np.array(mat)
    if not np.all(np.isfinite(arr)):
        raise SystemExit(f"ERROR: {path}: matrix contains NaN or Inf entries")
    if (arr < 0).any():
        raise SystemExit(f"ERROR: {path}: negative traffic entries (min {arr.min():g})")
    return arr

def shortest_paths(adj, s):
    """all simple shortest paths s->t (length = dist), via BFS layering + DFS forward."""
    n = len(adj)
    dist = [ -1 ]*n; dist[s]=0; q=deque([s])
    while q:
        u=q.popleft()
        for v in adj[u]:
            if dist[v]<0: dist[v]=dist[u]+1; q.append(v)
    allp = {}
    for t in range(n):
        if t==s or dist[t]<0: continue
        paths=[]
        def dfs(cur, acc):
            if cur==t:
                paths.append(tuple(acc)); return
            for v in sorted(adj[cur]):
                if dist[v]==dist[cur]+1:
                    acc.append(v); dfs(v,acc); acc.pop()
        dfs(s,[s])
        allp[t]=tuple(paths)
    return dist, allp

def solve_mclb(n, adj, T, timeout=60):
    """choose shortest paths to minimize max channel load. Returns first-hop table
    (per src, per dst -> one chosen next hop) using ILP over path candidates."""
    from scipy.optimize import milp, LinearConstraint, Bounds
    from scipy import sparse
    dirch = []
    for u in range(n):
        for v in adj[u]:
            dirch.append((u,v))
    E = len(dirch)
    cid = {c:k for k,c in enumerate(dirch)}
    flows = []
    path_of = {}
    for s in range(n):
        dist, allp = shortest_paths(adj, s)
        for t in range(n):
            if t==s or T[s][t]==0: continue
            plist = allp.get(t)
            if not plist: continue
            idx0 = len(flows)
            for p in plist:
                flows.append((s,t,p))
            path_of[(s,t)] = list(range(idx0, len(flows)))
    P = len(flows)
    NV = P + 1
    c = np.zeros(NV); c[-1]=1.0
    integ = np.zeros(NV,dtype=int)
    integ[:P]=1
    lb=np.zeros(NV); ub=np.full(NV,np.inf)
    ub[-1]=1e9
    A=[]; lo=[]; hi=[]
    def rc(row, a, b):
        A.append(row); lo.append(a); hi.append(b)
    for (s,t),idx in path_of.items():
        row={}
        for p in idx: row[p]=1.0
        rc(row, 1.0, 1.0)
    for e,(u,v) in enumerate(dirch):
        row={}
        row[P-1+0]=0.0
        pass
    Cidx = P
    for e,(u,v) in enumerate(dirch):
        row={Cidx:-1.0}
        for p,(s,t,path) in enumerate(flows):
            for a,b in zip(path, path[1:]):
                if (a,b)==(u,v):
                    row[p]=row.get(p,0.0)+T[s][t]
        rc(row, -np.inf, 0.0)
    ncon=len(A)
    data=[];ri=[];ci=[]
    for r,row in enumerate(A):
        for var,coef in row.items():
            ri.append(r); ci.append(var); data.append(coef)
    M=sparse.coo_matrix((data,(ri,ci)),shape=(ncon,NV)).tocsr()
    res=milp(c=c,constraints=LinearConstraint(M,np.array(lo),np.array(hi)),
             integrality=integ,bounds=Bounds(lb,ub),options={"time_limit":timeout})
    if res.x is None:
        return (None, P, path_of, flows, dirch, {})
    z=np.round(res.x[:P])
    bestp={}
    for (s,t),idx in path_of.items():
        sel=[p for p in idx if z[p]>0.5]
        if sel: bestp[(s,t)]=flows[sel[0]][2]
    return (res, P, path_of, flows, dirch, bestp)

def routing_first_hops(bestp, n, T):
    """convert chosen full paths into first-hop table per (src,dst)."""
    fh={}
    for (s,t),path in bestp.items():
        fh[(s,t)] = path[1] if len(path)>1 else s
    return fh

def escape_routes(n, adj, T):
    """Up*/Down* escape routing on a BFS spanning tree rooted at 0.

Rationale: docs/decisions/modules/tools.md
    """
    from collections import deque
    root = 0
    rank = [-1]*n; parent = [-1]*n
    rank[root] = 0; q = deque([root])
    while q:
        u = q.popleft()
        for v in sorted(adj[u]):
            if rank[v] < 0:
                rank[v] = rank[u]+1; parent[v] = u; q.append(v)
    bestp = {}
    for s in range(n):
        for t in range(n):
            if s == t or T[s][t] == 0: continue
            a, b = s, t
            ra, rb = rank[a], rank[b]
            path_a, path_b = [], []
            while ra > rb:
                path_a.append(parent[a]); a = parent[a]; ra -= 1
            while rb > ra:
                path_b.append(parent[b]); b = parent[b]; rb -= 1
            while a != b:
                path_a.append(parent[a]); a = parent[a]
                path_b.append(parent[b]); b = parent[b]
            path_b.reverse()
            route = [s] + path_a + path_b + [t]
            r = []
            for x in route:
                if not r or r[-1] != x: r.append(x)
            bestp[(s, t)] = tuple(r)
    return bestp

def build_cdg_and_check(bestp, n, adj, escape_vcs=1):
    """Dally–Seitz: build CDG over channels (each hop = channel dependency).
    Acyclic CDG with >=1 VC (or escape VC) => deadlock-free.
    Returns (acyclic, cycle_info, n_channels)."""
    dirch={(u,v) for u in range(n) for v in adj[u]}
    dep=defaultdict(set)
    used=defaultdict(float)
    for (s,t),path in bestp.items():
        for a,b,c in zip(path, path[1:], path[2:]):
            dep[(a,b)].add((b,c))
    WHITE,GREY,BLACK=0,1,2
    col={c:WHITE for c in dirch}
    stack=[]
    cycles=[]
    def dfs(c0):
        col[c0]=GREY; stack.append(c0)
        for c1 in dep[c0]:
            if col[c1]==WHITE:
                if dfs(c1): return True
            elif col[c1]==GREY:
                cycles.append(stack[stack.index(c1):]+[c1])
                return True
        col[c0]=BLACK; stack.pop()
        return False
    acyclic=True
    for c in dirch:
        if col[c]==WHITE and dfs(c):
            acyclic=False
            break
    return acyclic, cycles[:1], len(dirch)

def is_connected(adj, n):
    """BFS reachability from node 0 — every node must be routable."""
    from collections import deque
    seen = {0}
    q = deque([0])
    while q:
        u = q.popleft()
        for v in adj[u]:
            if v not in seen:
                seen.add(v); q.append(v)
    return len(seen) == n

def booksim_first_hop_table(n, adj):
    """The first-hop table BookSim's AnyNet actually builds.

    Delegates to core.route_artifact — the canonical home of the
    routing-truth replica since Phase 10 (this module keeps a thin
    re-export so existing callers/tests keep working; ONE
    implementation lives in core).
    """
    from veritx_dse.core.route_artifact import _anynet_replica_first_hops
    return _anynet_replica_first_hops(n, adj)

def booksim_route_paths(n, adj):
    """Full node paths BookSim executes, reconstructed from its first-hop
    table (all-pairs). Feeds build_cdg_and_check unchanged."""
    fh = booksim_first_hop_table(n, adj)
    paths = {}
    for (s, t), nxt in fh.items():
        path = [s, nxt]
        cur = nxt
        for _ in range(n):
            if cur == t:
                break
            cur = fh[(cur, t)]
            path.append(cur)
        paths[(s, t)] = tuple(path)
    return paths

def export_route_table(fh, out_prefix):
    """Write the (src,dst,next_hop) table as CSV for cert<->sim diffing."""
    with open(out_prefix + ".routes.csv", "w") as f:
        f.write("src,dst,next_hop\n")
        for (s, t) in sorted(fh):
            f.write(f"{s},{t},{fh[(s, t)]}\n")

def shortest_route_table(n, adj, T):
    """Deterministic shortest routing: first lexical shortest path per flow
    (matches gen_route_tables/BookSim tie-breaking)."""
    bestp = {}
    for s in range(n):
        dist, allp = shortest_paths(adj, s)
        for t in range(n):
            if t != s and T[s][t] > 0 and allp.get(t):
                bestp[(s, t)] = allp[t][0]
    return bestp

class MclbInfeasible(Exception):
    """MCLB ILP failed or found no feasible path assignment."""

def route(n, adj, T, method="mclb", timeout=60):
    """Dispatch a routing method → (bestp, first_hop_table).

    Raises MclbInfeasible when the mclb ILP fails (caller decides exit
    semantics — this module stays IO-free).
    """
    if method == "mclb":
        res = solve_mclb(n, adj, T, timeout)
        if res is None or res[0] is None:
            raise MclbInfeasible("MCLB ILP failed/infeasible")
        _res, _P, _path_of, _flows, _dirch, bestp = res
        return bestp, routing_first_hops(bestp, n, T)
    if method == "escape":
        bestp = escape_routes(n, adj, T)
        return bestp, routing_first_hops(bestp, n, T)
    if method == "booksim":
        bestp = booksim_route_paths(n, adj)
        return bestp, routing_first_hops(bestp, n, T)
    if method == "shortest":
        bestp = shortest_route_table(n, adj, T)
        return bestp, routing_first_hops(bestp, n, T)
    raise ValueError(f"unknown routing method: {method!r}")

def deadlock_certificate(n, adj, T, anynet_path, method="mclb",
                         escape_vcs=1, timeout=60):
    """Pure decision core: route the flows, check the CDG, emit the cert dict.

    Everything a test (or a caller) needs — connectivity, method dispatch,
    acyclicity verdict, escape-VC requirement — with zero IO. Raises
    MclbInfeasible; prints nothing; writes nothing.
    """
    bestp, fh = route(n, adj, T, method=method, timeout=timeout)
    acyclic, cycles, nchan = build_cdg_and_check(bestp, n, adj, escape_vcs)
    result = {
        "topology": anynet_path,
        "connected": is_connected(adj, n),
        "method": method,
        "routing_table_entries": len(fh),
        "channel_dependency_graph": {
            "n_channels": nchan, "acyclic": acyclic,
            "sample_cycle": cycles[0] if cycles else None,
            "verdict": ("PASS: acyclic physical-channel CDG under "
                        f"{method} routing => deadlock-free at that scope "
                        "(no escape-VC discipline is implemented or claimed; "
                        "min_anynet exposes all VCs on the selected hop)")
                       if acyclic
                       else "FAIL: cyclic CDG => assign these channels to an escape/separate VC class"},
        "escape_vcs_required": 0 if acyclic else escape_vcs,
    }
    if method == "booksim":
        from veritx_dse.core.route_artifact import RouteArtifact
        import os
        art = RouteArtifact.from_adjacency(
            adj, name=os.path.splitext(os.path.basename(str(anynet_path)))[0])
        result["route_artifact"] = art.serialize()
    return result

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--anynet", required=True)
    ap.add_argument("--matrix", required=True)
    ap.add_argument("--out", required=True, help="output prefix (writes .json cert)")
    ap.add_argument("--method", choices=["mclb", "shortest", "escape", "booksim"], default="booksim",
                    help="routing the certificate evaluates. DEFAULT CHANGED "
                         "(PR D): 'booksim' — the routes BookSim's AnyNet "
                         "actually executes. The old default 'mclb' certified "
                         "route set A while the simulator executed route set B.")
    ap.add_argument("--export-table", action="store_true", default=True,
                    help="write the BookSim-exact (src,dst,next_hop) table "
                         "as <out>.routes.csv (permanent cert<->sim diff seam). "
                         "DEFAULT ON (PR D): the certified route table is "
                         "evidence and must be persisted + hashed.")
    ap.add_argument("--no-export-table", dest="export_table", action="store_false")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--escape_vcs", type=int, default=1)
    args = ap.parse_args()
    try:
        assert_unit_weights(args.anynet)
    except ValueError as e:
        print(str(e))
        sys.exit(2)
    n, adj = parse_anynet(args.anynet)
    T = load_matrix(args.matrix)
    try:
        result = deadlock_certificate(n, adj, T, args.anynet,
                                      method=args.method,
                                      escape_vcs=args.escape_vcs,
                                      timeout=args.timeout)
    except MclbInfeasible as e:
        print(e)
        sys.exit(1)
    print(json.dumps(result, indent=2))
    with open(args.out + ".json", "w") as f:
        json.dump(result, f, indent=2)
    print(f"certificate -> {args.out}.json")
    if args.export_table:
        export_route_table(booksim_first_hop_table(n, adj), args.out)
        fh_sha = hashlib.sha256(open(args.out + ".routes.csv", "rb").read()).hexdigest()
        result["route_table"] = {"path": args.out + ".routes.csv",
                                 "sha256": fh_sha}
        with open(args.out + ".json", "w") as f:
            json.dump(result, f, indent=2)
        print(f"route table -> {args.out}.routes.csv (sha256 {fh_sha[:16]}…)")

if __name__=="__main__":
    main()
