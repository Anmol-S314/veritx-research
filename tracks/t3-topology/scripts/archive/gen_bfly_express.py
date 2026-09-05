#!/usr/bin/env python3
"""Generate power-of-2 express mesh anynet with per-link wire latencies.
Skips {1,2,4} pitches per dimension (mod K). 64 nodes -> 320 undirected
links, degree 10, mean span 2.70. Beat GEC-express on latency-per-wire
budget by 22% (see CALIBRATION-RESULTS-R10R11.md)."""
import sys
K = int(sys.argv[1]) if len(sys.argv) > 1 else 8
SKIPS = [1,2,4]
pos = {i:(i%K,i//K) for i in range(K*K)}
adj = {i:set() for i in range(K*K)}
for n,(x,y) in pos.items():
    for s in SKIPS:
        for dx,dy in ((s,0),(-s,0),(0,s),(0,-s)):
            nx,ny=(x+dx)%K,(y+dy)%K
            m=ny*K+nx
            if m!=n: adj[n].add(m)
out=[];lats=[]
for n in range(K*K):
    toks=[f'router {n}', f'node {n}']
    for m in sorted(adj[n]):
        x1,y1=pos[n]; x2,y2=pos[m]
        lat=max(abs(x1-x2)+abs(y1-y2),1); lats.append(lat)
        toks+=['router',str(m),str(lat)]
    out.append(' '.join(toks))
dest = sys.argv[2] if len(sys.argv)>2 else 'bfly_priced.anynet'
open(dest,'w').write('\n'.join(out)+'\n')
print(f"{len(lats)} directed links ({len(lats)//2} undirected), mean span {sum(lats)/len(lats):.2f} -> {dest}")
