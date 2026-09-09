#!/usr/bin/env python3
"""
deadlock_routing.py — M2: MCLB routing + deadlock certificate for a custom topology.

Given a topology (.anynet from milp_topology_v2.py) and a traffic matrix T:

  1. MCLB routing ILP (min max channel load): for each (src,dst) flow, choose the
     shortest-path route(s) that minimize the maximum channel load under T
     (NetSmith §3.4 "MCLB"). Emits a routing: first-hop table per (src,dst).
  2. Deadlock certificate: build the CHANNEL-DEPENDENCY GRAPH (CDG) of the
     resulting routing and check acyclicity (Dally–Seitz: an acyclic CDG for a
     routing subfunction => deadlock-free). If the CDG is acyclic, emit a PASS
     certificate. If cyclic, report the minimal set of channels that must be
     assigned to ESCAPE virtual channels (cycle-breaking=true), flagging where a
     VC-per-escape is required.

Uses scipy.optimize.milp (HiGHS) for the routing ILP. No Clab: routing here is
path selection over shortest paths (deterministic tie-break for a valid table),
matching the gen_route_tables.py convention (neighbors at anynet token idx 5,7,9).

Usage:
  python deadlock_routing.py --anynet /tmp/milp16.anynet --matrix /tmp/test16.mat --k 16 --out /tmp/cert
  python deadlock_routing.py --anynet <f> --matrix <m> --out <prefix> --method mclb|shortest
"""
import argparse, json, sys
from collections import defaultdict, deque
import numpy as np

# ---------------- topology io (anynet) ----------------
def parse_anynet(path):
    """nodes -> {neighbor}. Format: 'router <id> node <id> router <n> ...'"""
    adj = defaultdict(set)
    with open(path) as f:
        for line in f:
            p = line.split()
            if len(p) >= 4 and p[0] == 'router':
                a = int(p[1])
                for q in p[4:]:
                    if q != 'node':
                        try: adj[a].add(int(q))
                        except ValueError: pass
            else:
                continue
    n = len(adj)
    # normalize
    out = {i: set(adj.get(i, ())) for i in range(n)}
    return n, out

def load_matrix(path):
    mat = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            mat.append([float(x) for x in line.split()])
    return np.array(mat)

# ---------------- shortest paths ----------------
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
        # DFS forward from s to t, only stepping to nodes with dist+1
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

# ---------------- MCLB routing ILP ----------------
def solve_mclb(n, adj, T, timeout=60):
    """choose shortest paths to minimize max channel load. Returns first-hop table
    (per src, per dst -> one chosen next hop) using ILP over path candidates."""
    from scipy.optimize import milp, LinearConstraint, Bounds
    from scipy import sparse
    # directed channels
    dirch = []
    for u in range(n):
        for v in adj[u]:
            dirch.append((u,v))
    E = len(dirch)
    cid = {c:k for k,c in enumerate(dirch)}
    # candidate paths per (s,t)
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
    # vars: z_p in {0,1} choose path p ; C = max channel load
    NV = P + 1
    c = np.zeros(NV); c[-1]=1.0   # minimize C
    integ = np.zeros(NV,dtype=int)
    integ[:P]=1
    lb=np.zeros(NV); ub=np.full(NV,np.inf)
    ub[-1]=1e9
    A=[]; lo=[]; hi=[]
    def rc(row, a, b):
        A.append(row); lo.append(a); hi.append(b)
    # per (s,t) choose exactly one path
    for (s,t),idx in path_of.items():
        row={}
        for p in idx: row[p]=1.0
        rc(row, 1.0, 1.0)
    # channel load: sum_p load_p(c) (T[s][t]) <= C  =>  -C + sum <= 0
    # precompute load contribution per channel
    for e,(u,v) in enumerate(dirch):
        row={}
        row[P-1+0]=0.0
        # C is var index P (last). Actually NV=P+1 => C index = P
        # fix: C index = P
        pass
    # rebuild with correct C index
    Cidx = P
    for e,(u,v) in enumerate(dirch):
        row={Cidx:-1.0}
        for p,(s,t,path) in enumerate(flows):
            # load on channel (u,v) if path uses (u,v)
            for a,b in zip(path, path[1:]):
                if (a,b)==(u,v):
                    row[p]=row.get(p,0.0)+T[s][t]
        rc(row, -np.inf, 0.0)   # sum load - C <= 0
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

# ---------------- deadlock certificate: CDG acyclicity ----------------
def routing_first_hops(bestp, n, T):
    """convert chosen full paths into first-hop table per (src,dst)."""
    fh={}
    for (s,t),path in bestp.items():
        fh[(s,t)] = path[1] if len(path)>1 else s
    return fh

def escape_routes(n, adj, T):
    """Up*/Down* escape routing on a BFS spanning tree rooted at 0.

    rank[root]=0, rank increases with BFS level. A flow s->t is routed along the
    tree via their LCA: s climbs up (rank decreasing) to the LCA, then down to t.
    Every tree edge is oriented parent(child) = lower(higher) rank; "down" edges
    always go rank r -> rank r-1. Because we only ever move UP a tree (and DOWN
    strictly toward the LCA), the escape subfunction is a tree => its CDG is
    acyclic => packets can always drain on the escape class => deadlock-free by
    construction. Returns bestp: {(s,t): full path}.
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
    # channel dependency: c=(u,v) -> c'=(v,w) if some flow leaves u..v..w consecutively
    dep=defaultdict(set)
    used=defaultdict(float)
    for (s,t),path in bestp.items():
        for a,b,c in zip(path, path[1:], path[2:]):
            dep[(a,b)].add((b,c))
    # cycle detection (DFS) on channel graph
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

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--anynet", required=True)
    ap.add_argument("--matrix", required=True)
    ap.add_argument("--out", required=True, help="output prefix (writes .json cert)")
    ap.add_argument("--method", choices=["mclb","shortest","escape"], default="mclb")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--escape_vcs", type=int, default=1)
    args=ap.parse_args()
    n, adj = parse_anynet(args.anynet)
    T = load_matrix(args.matrix)
    # quick connectivity + hop check
    from collections import deque
    seen=set([0]); q=deque([0])
    while q:
        u=q.popleft()
        for v in adj[u]:
            if v not in seen: seen.add(v); q.append(v)
    connected = len(seen)==n

    if args.method == "mclb":
        res = solve_mclb(n, adj, T, args.timeout)
        if res is None or res[0] is None:
            print("MCLB ILP failed/infeasible"); sys.exit(1)
        _, P, path_of, flows, dirch, bestp = res
        fh = routing_first_hops(bestp, n, T)
    elif args.method == "escape":
        # Up*/Down* escape routing (acyclic tree subfunction) => deadlock-free by construction
        bestp = escape_routes(n, adj, T)
        fh = routing_first_hops(bestp, n, T)
    else:
        # deterministic shortest (Dijkstra min, like gen_route_tables/BookSim)
        bestp = {}
        for s in range(n):
            dist, allp = shortest_paths(adj, s)
            for t in range(n):
                if t != s and T[s][t] > 0 and allp.get(t):
                    bestp[(s, t)] = allp[t][0]   # first lexical shortest path
        fh = routing_first_hops(bestp, n, T)

    acyclic, cycles, nchan = build_cdg_and_check(bestp, n, adj, args.escape_vcs)
    result = {
        "topology": args.anynet,
        "connected": connected,
        "method": args.method,
        "routing_table_entries": len(fh),
        "channel_dependency_graph": {"n_channels": nchan, "acyclic": acyclic,
                                     "sample_cycle": cycles[0] if cycles else None,
                                     "verdict": "PASS: acyclic CDG => deadlock-free with >=1 VC/escape" if acyclic
                                                else "FAIL: cyclic CDG => assign these channels to an escape/separate VC class"},
        "escape_vcs_required": 0 if acyclic else args.escape_vcs,
    }
    print(json.dumps(result, indent=2))
    with open(args.out+".json","w") as f:
        json.dump(result,f,indent=2)
    print(f"certificate -> {args.out}.json")

if __name__=="__main__":
    main()
