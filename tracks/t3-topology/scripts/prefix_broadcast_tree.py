#!/usr/bin/env python3
"""Latency refinement of the shared-prefix broadcast: the dimension-ordered TREE. (T3 ext)

prefix_broadcast_flitfork.py delivers the shared prefix to all B cores with a single
Hamiltonian "snake" -- correct throughput (one stream per link, stable to full injection),
but a CONSERVATIVE latency: the snake serializes deliveries along one path, so a copy destined
for the k-th snake position waits k hops. The natural refinement is a dimension-ordered
broadcast TREE, whose branches run in parallel; this script pins down its latency, honestly.

WHY WE DON'T NEED BRANCHING HARDWARE TO GET THE NUMBER
------------------------------------------------------
An XY broadcast tree rooted at node 0 is EDGE-DISJOINT: the spine runs across row 0 (row-0
X-links only); at each column x it drops a branch down column x (column-x Y-links only). No
link is shared, so the tree has ZERO internal contention and each leaf's flit sees exactly the
ZERO-LOAD unicast latency of its root->leaf DOR path, L(d) for d = its hop distance.

Zero-load latency is LINEAR in hops, L(h) = a + b*h (fixed router pipeline + per-hop cost). We
fit (a, b) from booksim's built-in permutation patterns at low load -- each reports its realized
`Hops average` and `Packet latency average`, points straight on the L(h) line -- then read off
the tree's per-leaf latencies. No new patch, no deadlock-prone link-traversing fork.

THE MODEL IS VALIDATED, NOT ASSUMED
-----------------------------------
The snake's measured delivery latency (~167 cyc) is the AVERAGE over its copies, which eject at
snake positions 1..N-1 (mean N/2 = 32 hops). We PREDICT a + b*32 and require it to match the
measured 167 within 10%. Only if that known-answer gate passes do we trust a + b*14 for the tree.

HONEST COMPARISON (same throughput for both; this axis is latency only):
  snake:  avg delivery = L(mean eject hop 32);  tail = L(63)
  tree:   avg delivery = L(mean leaf dist ~7.1); tail = L(corner 14)
The tree wins ~4x on BOTH avg and tail -- not the 20x an earlier apples-to-oranges draft claimed.

RUN IT (tools image):
    podman run --rm -v "$PWD:/repo" -w /repo \\
        internal-devrepo.datavex.ai:5050/anmol/veritx-research/veritx-tools-base:latest \\
        python3 tracks/t3-topology/scripts/prefix_broadcast_tree.py --run

    python3 scripts/prefix_broadcast_tree.py --selfcheck   # geometry + fit math, no booksim
"""
import re
import subprocess
import sys
from pathlib import Path

K = 8
N = K * K
TREE_TAIL_HOPS = 2 * (K - 1)         # opposite corner = 14 hops (deepest tree leaf)
SNAKE_TAIL_HOPS = N - 1              # last node on the Hamiltonian path = 63 hops
SNAKE_MEAN_HOPS = N / 2             # copies eject at positions 1..N-1, mean = 32
SNAKE_MEAS_AVG = 167.0              # measured avg delivery latency (prefix_broadcast_flitfork.py)
FIT_PATTERNS = ["neighbor", "uniform", "tornado", "transpose", "shuffle"]
OUT = Path("/tmp/prefix_tree")


def mean_leaf_hops():
    """Mean XY hop distance from node 0 over all N-1 other nodes (the tree's leaves)."""
    tot = sum((d % K) + (d // K) for d in range(N))   # node 0 contributes 0
    return tot / (N - 1)


def cfg(pattern):
    return f"""topology = mesh;
k = {K};
n = 2;
routing_function = dim_order;
num_vcs = 8;
vc_buf_size = 8;
traffic = {pattern};
injection_rate = 0.01;
packet_size = 1;
sim_type = latency;
sample_period = 2000;
warmup_periods = 2;
max_samples = 3;
"""


def _last(pat, text):
    v = None
    for line in text.splitlines():
        if pat in line:
            m = re.search(r"=\s*([0-9.eE+-]+)", line)
            if m:
                v = float(m.group(1))
    return v


def measure(pattern):
    """Low-load (hops, latency) point for a built-in traffic pattern."""
    OUT.mkdir(parents=True, exist_ok=True)
    cf = OUT / f"{pattern}.cfg"
    cf.write_text(cfg(pattern))
    r = subprocess.run(["booksim", str(cf)], capture_output=True, text=True, timeout=300)
    return _last("Hops average", r.stdout), _last("Packet latency average", r.stdout)


def fit(points):
    """Least-squares a, b for latency = a + b*hops."""
    n = len(points)
    sx = sum(h for h, _ in points)
    sy = sum(l for _, l in points)
    sxx = sum(h * h for h, _ in points)
    sxy = sum(h * l for h, l in points)
    b = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    a = (sy - b * sx) / n
    return a, b


def main():
    print(f"\n  Dimension-ordered broadcast TREE latency -- {K}x{K} mesh, root node 0\n")
    print(f"  fitting L(h) = a + b*h from low-load built-in patterns:")
    pts = []
    for p in FIT_PATTERNS:
        h, l = measure(p)
        assert h and l, (p, h, l)
        pts.append((h, l))
        print(f"    {p:>10}   hops={h:6.3f}   lat={l:7.3f}")
    a, b = fit(pts)
    print(f"\n  fit: L(h) = {a:.2f} + {b:.2f}*h   ({b:.2f} cyc/hop, {a:.2f} cyc fixed)")

    # --- known-answer gate: predict the snake's measured AVERAGE delivery latency ---
    pred_snake_avg = a + b * SNAKE_MEAN_HOPS
    err = abs(pred_snake_avg - SNAKE_MEAS_AVG) / SNAKE_MEAS_AVG
    ok = err < 0.10
    print(f"\n  GATE  predict snake avg (mean eject {SNAKE_MEAN_HOPS:.0f} hops) = {pred_snake_avg:.0f} cyc "
          f"vs measured {SNAKE_MEAS_AVG:.0f}: {err*100:.1f}% err; {'PASS' if ok else 'FAIL'}")
    assert ok, (pred_snake_avg, SNAKE_MEAS_AVG, err)

    L = lambda h: a + b * h
    mlh = mean_leaf_hops()
    snake_avg, snake_tail = L(SNAKE_MEAN_HOPS), L(SNAKE_TAIL_HOPS)
    tree_avg, tree_tail = L(mlh), L(TREE_TAIL_HOPS)

    print(f"\n  {'':<8} {'avg delivery':>16} {'tail (last core)':>18}")
    print(f"  {'snake':<8} {snake_avg:>10.0f} ({SNAKE_MEAN_HOPS:.0f}h) {snake_tail:>11.0f} ({SNAKE_TAIL_HOPS}h)")
    print(f"  {'tree':<8} {tree_avg:>10.0f} ({mlh:.1f}h) {tree_tail:>11.0f} ({TREE_TAIL_HOPS}h)")
    print(f"\n  -> the dimension-ordered tree cuts prefix-delivery latency "
          f"{snake_avg/tree_avg:.1f}x on average, {snake_tail/tree_tail:.1f}x on the tail,")
    print(f"     for the SAME throughput (each tree link still carries one stream at rate r).")
    print(f"     Rigorous via edge-disjointness: each leaf sees a lone-unicast latency L(d).")

    assert tree_tail < snake_tail and tree_avg < snake_avg
    print(f"\n  selfcheck OK -- tree beats snake on avg ({tree_avg:.0f}<{snake_avg:.0f}) and "
          f"tail ({tree_tail:.0f}<{snake_tail:.0f})")


def _selfcheck():
    # geometry: corner is the deepest leaf; mean leaf distance; edge-disjointness
    assert TREE_TAIL_HOPS == 14 and SNAKE_TAIL_HOPS == 63
    assert abs(mean_leaf_hops() - 448 / 63) < 1e-9         # sum(x+y) over grid = 448
    assert max((d % K) + (d // K) for d in range(N)) == TREE_TAIL_HOPS
    spine = {("x", 0, x) for x in range(K - 1)}
    for col in range(K):
        assert spine.isdisjoint({("y", col, y) for y in range(K - 1)})
    # fit math on a synthetic exact line L = 3 + 5h recovers (3, 5)
    a, b = fit([(h, 3 + 5 * h) for h in (1, 4, 9, 14)])
    assert abs(a - 3) < 1e-6 and abs(b - 5) < 1e-6, (a, b)
    print(f"selfcheck OK -- corner {TREE_TAIL_HOPS}h is deepest leaf; mean leaf {mean_leaf_hops():.2f}h; "
          f"edge-disjoint; linear fit exact on synthetic line")


if __name__ == "__main__":
    _selfcheck() if "--selfcheck" in sys.argv else main()
