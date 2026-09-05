# UCIe Bridge Scaling Results

## Data

```
Bridges   Latency    vs 8-br    BW (B/cyc)   Ranks/bridge
────────────────────────────────────────────────────────────
    1      3648c      +35%          64          128
    2      3758c      +39%         128           64
    4      3189c      +18%         256           32
    8      2710c      base         512           16
   16      2779c       +3%        1024            8
   32      1758c      -35%        2048            4  ← SWEET SPOT
   64        44c      -98%        4096            1
```

## Key Insight

**32 bridges = 4 ranks/bridge = 35% improvement over 8 bridges**

- 8 bridges: each handles 16 ranks → severe contention
- 32 bridges: each handles 4 ranks → manageable
- 64 bridges: each handles 1 rank → zero contention (but 8× area cost)

The relationship is non-linear:
- 1→8 bridges: 25% improvement (3648→2710c)
- 8→32 bridges: 35% improvement (2710→1758c)  
- 32→64 bridges: 97% improvement (1758→44c)

**Recommendation:** 32 bridges is the Pareto-optimal point — 35% improvement for 4× area cost over 8 bridges. Going to 64 eliminates inter-die overhead entirely but costs 8× more silicon.

## For the Paper

The UCIe bridge count is a design knob:
- Too few (1-8): inter-die traffic bottlenecked
- Too many (64): wasted silicon area
- Sweet spot (32): 35% latency reduction, reasonable area
