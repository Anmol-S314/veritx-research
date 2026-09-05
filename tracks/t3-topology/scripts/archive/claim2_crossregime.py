#!/usr/bin/env python3
"""Claim-2 experiment: cross-regime topology synthesis + evaluation.
Regimes: CHAT (ShareGPT) vs AGENTIC (SWE-bench), real LLMServingSim traces.
Synthesize per-regime and robust (elementwise-max matrix); evaluate
priced-latency on every window of both regimes."""
import pickle, sys, statistics
import numpy as np
from collections import defaultdict

sys.path.insert(0, 'tracks/t3-topology/scripts')
import importlib.util
spec=importlib.util.spec_from_file_location("m2","tracks/t3-topology/scripts/milp_topology_v2.py")
m2=importlib.util.module_from_spec(spec)
try: spec.loader.exec_module(m2)
except SystemExit: pass

data=pickle.load(open('/tmp/regime_windows.pkl','rb'))
K=8; xy=m2.grid_xy(K)

def avg_mats(regime):
    ms=data[regime]['mats']
    n=len(ms[0])
    return [[sum(m[i][j] for m in ms)/len(ms) for j in range(n)] for i in range(n)]

Tchat=avg_mats('CHAT'); Tagent=avg_mats('AGENTIC')

def synth(T, iters=8000, seed=42):
    T=np.array(T)
    adj_base=defaultdict(set)
    for r in range(64):
        rr,cc=divmod(r,K)
        if cc>0: adj_base[r].add(r-1)
        if cc<K-1: adj_base[r].add(r+1)
        if rr>0: adj_base[r].add(r-K)
        if rr<K-1: adj_base[r].add(r+K)
    base_edges=set()
    for u in adj_base:
        for v in adj_base[u]: base_edges.add((min(u,v),max(u,v)))
    cand=[]
    for u in range(64):
        for v in range(u+1,64):
            x1,y1=xy[u]; x2,y2=xy[v]
            d=max(abs(x1-x2)+abs(y1-y2),1)
            if d<=7 and (u,v) not in base_edges: cand.append((u,v))
    m2.set_costs(5.0,1.0)
    return m2.sa_synthesize(T, xy, sorted(base_edges), cand, radix=12,
        iters=iters, seed=seed, priced=True)

def eval_topo(adj, regime):
    vals=[m2.priced_geodesic(np.array(T), adj, xy) for T in data[regime]['mats']]
    return statistics.mean(vals), max(vals)

Tc, sc = synth(Tchat)
Ta, sa_ = synth(Tagent)
Trob=[[max(Tchat[i][j],Tagent[i][j]) for j in range(64)] for i in range(64)]
Tr, sr = synth(Trob)
print("synthesis complete")

print(f"{'topo':>10} | {'CHAT mean':>9} {'CHAT max':>8} | {'AGEN mean':>9} {'AGEN max':>8} | worst")
for name, adj in [("T_chat",Tc),("T_agentic",Ta),("T_robust",Tr)]:
    mc,xc = eval_topo(adj,'CHAT'); ma,xa = eval_topo(adj,'AGENTIC')
    print(f"{name:>10} | {mc:9.2f} {xc:8.2f} | {ma:9.2f} {xa:8.2f} | {max(xc,xa):6.2f}")

pickle.dump({'Tc':{k:sorted(v) for k,v in Tc.items()},
             'Ta':{k:sorted(v) for k,v in Ta.items()},
             'Tr':{k:sorted(v) for k,v in Tr.items()}},
            open('/tmp/regime_topos.pkl','wb'))
print("saved /tmp/regime_topos.pkl")
