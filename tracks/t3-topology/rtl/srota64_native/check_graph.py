#!/usr/bin/env python3
"""Independent k=8 graph oracle from BookSim SrotaNoC::_BuildExpressDim."""
from collections import Counter
K=8
channels=[]
for axis in (0,1):
    for line in range(K):
        for a in range(K):
            for sign in (-1,1):
                taps=[]
                b=a+sign
                while 0 <= b < K:
                    src=line*K+a if axis==0 else a*K+line
                    dst=line*K+b if axis==0 else b*K+line
                    taps.append((src,dst,len(taps)))
                    b += sign
                if taps:
                    channels.append((axis,line,a,sign,taps))
assert len(channels)==224, len(channels)
assert sum(len(c[4]) for c in channels)==896
assert Counter(axis for axis,*_ in channels)=={0:112,1:112}
# Every ordered distinct same-row or same-column peer has exactly one directed
# segment and its drop equals distance-1, in outward tap order.
by_pair={}
for axis,line,a,sign,taps in channels:
    for src,dst,drop in taps:
        assert (src,dst) not in by_pair
        by_pair[src,dst]=(axis,line,a,sign,drop)
assert len(by_pair)==8*8*7*2
for src in range(64):
    x,y=src%8,src//8
    for dst in range(64):
        dx,dy=dst%8,dst//8
        if src==dst: continue
        if y==dy:
            axis,line,a,sign,drop=by_pair[src,dst]
            assert axis==0 and line==y and a==x and sign==(1 if dx>x else -1)
            assert drop==abs(dx-x)-1
        if x==dx:
            axis,line,a,sign,drop=by_pair[src,dst]
            assert axis==1 and line==x and a==y and sign==(1 if dy>y else -1)
            assert drop==abs(dy-y)-1
# Row-first route's first X segment (if needed), then Y segment at (dx,sy).
for src in range(64):
    x,y=src%8,src//8
    for dst in range(64):
        dx,dy=dst%8,dst//8
        if x!=dx:
            assert (src,y*8+dx) in by_pair
            if y!=dy:
                turn=y*8+dx
                assert (turn,dst) in by_pair
        elif y!=dy:
            assert (src,dst) in by_pair
print("PASS canonical graph: 224 unique directed segments, 896 ordered taps, 4096 pair routes/drop tuples")
