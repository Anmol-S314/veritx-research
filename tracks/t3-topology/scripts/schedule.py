#!/usr/bin/env python3
"""A multicast-aware KV schedule for GQA decode, placed on the real Wormhole grid. (T3)

This is the constructive capstone. serving_multicast.py showed that reading each KV head
ONCE and sharing it beats re-reading it g times (up to ~5.4x throughput). This says HOW:
the concrete mapping of query heads, KV heads, and context onto physical cores, and the
traffic it produces -- validated against the pinned Wormhole geometry (scripts/wormhole.py).

THE DECOMPOSITION. GQA decode attention factors onto a 2D grid as two primitives a plain
mesh/torus already does natively -- which is *why* the topology never needed to be fancy:

    ROWS  = KV groups.   The g query heads that share a KV head sit along one row.
            The KV head is read from DRAM ONCE and MULTICAST along the row to all g.
            -> this is the g-fold DRAM saving. Row-multicast.

    COLS  = query heads within a group (short context)   OR
            sequence chunks of one head (long context, KV streamed).
            When context is split, partial attention is COMBINED down the column with
            an online-softmax reduce. Column-reduce.

So: multicast on the group axis kills the redundant DRAM reads; reduce on the sequence
axis handles a KV cache too big for one core's L1. Neither needs a special topology --
row-broadcast and column-reduce are what 2D fabrics are built for.

PHYSICAL MAP (Wormhole 80-Tensix worker grid, 8 cols x 10 rows, DRAM in cols x=0,5):
    core at (col, row)  ->  KV head = row index,  query head = row*g + col
    KV head's cache is read from the DRAM column and multicast across its row.
Because DRAM sits in an INTERIOR column (x=5, splitting the array), a KV head feeds its
row from the middle -- the multicast fans out both directions, halving the span.

KV STREAMS, it does not reside: at long context the cache dwarfs L1 (1.5 MB), so it is
streamed from DRAM in tiles, each tile multicast to the row and consumed online
(FlashAttention-decode style). L1 holds only a working window. DRAM bandwidth is the wall
(decode_roofline.py), and the schedule's job is to not waste it on redundant reads.

    python3 scripts/schedule.py [--selfcheck]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import wormhole


class GQA:
    def __init__(self, name, layers, n_q, n_kv, d_head):
        self.name, self.layers = name, layers
        self.n_q, self.n_kv, self.d_head = n_q, n_kv, d_head

    @property
    def g(self):
        return self.n_q // self.n_kv


LLAMA70B = GQA("Llama-3-70B", layers=80, n_q=64, n_kv=8, d_head=128)


def build_map(model, soc=None):
    """Assign query heads to physical worker cores. Returns:
        placement: {(x,y): (kv_head, query_head)}
        rows:      {kv_head: [ (x,y), ... ]}  the cores that share that KV head
        dram_for:  {kv_head: (x,y)}  the DRAM endpoint feeding that head's row
    """
    soc = soc or wormhole.load()
    workers = soc["nodes"]["functional_workers"]
    dram = soc["nodes"]["dram"]

    ys = sorted({y for _, y in workers})            # 10 worker rows
    xs = sorted({x for x, _ in workers})            # 8 worker columns
    assert len(xs) >= model.g, f"need {model.g} columns for a group, have {len(xs)}"

    placement, rows, dram_for = {}, {}, {}
    for kv in range(model.n_kv):                     # one KV head per worker row
        y = ys[kv]
        row_cores = [(x, y) for x in xs][:model.g]   # g query heads across the row
        rows[kv] = row_cores
        for col, (x, _) in enumerate(row_cores):
            placement[(x, y)] = (kv, kv * model.g + col)
        # feed the row from the nearest DRAM endpoint (interior col 5 splits the row)
        dram_for[kv] = min(dram, key=lambda d: abs(d[1] - y) + abs(d[0] - 5))
    return placement, rows, dram_for


def kv_bytes_per_head(model, seq, dtype=2, c=1):
    """K and V for one head over the whole context, per layer, compressed by c."""
    return 2 * model.d_head * seq * dtype / c


def traffic(model, seq, soc=None, dtype=2, c=1):
    """DRAM and NoC hop-byte traffic per layer per step, schedule vs naive."""
    soc = soc or wormhole.load()
    _, rows, dram_for = build_map(model, soc)
    grid = soc["grid"]
    kvh = kv_bytes_per_head(model, seq, dtype, c)

    dram_sched = dram_naive = 0.0
    noc_sched = noc_naive = 0.0
    for kv, cores in rows.items():
        d = dram_for[kv]
        # DRAM: schedule reads the head once; naive reads it once PER query head (g).
        dram_sched += kvh
        dram_naive += kvh * len(cores)
        # NoC hop-bytes. Naive: each core pulls the head from DRAM independently.
        noc_naive += sum(kvh * wormhole.torus_hops(d, core, grid) for core in cores)
        # Schedule: one multicast tree over the row = each link on the tree carries the
        # bytes once. Tree links = union of shortest paths DRAM->each core.
        links = set()
        for core in cores:
            links |= _path_links(d, core, grid)
        noc_sched += kvh * len(links)
    return {
        "dram_sched": dram_sched, "dram_naive": dram_naive,
        "dram_reduction": dram_naive / dram_sched,
        "noc_sched": noc_sched, "noc_naive": noc_naive,
        "noc_ratio": noc_sched / noc_naive,
    }


def _path_links(a, b, grid):
    """Links on a row-first torus path a->b, as a set of frozenset endpoints."""
    X, Y = grid
    links, cur = set(), list(a)
    # x first (torus: step toward b the short way), then y
    for axis, size in ((0, X), (1, Y)):
        while cur[axis] != b[axis]:
            step = 1 if (b[axis] - cur[axis]) % size <= size // 2 else -1
            nxt = list(cur)
            nxt[axis] = (cur[axis] + step) % size
            links.add(frozenset({tuple(cur), tuple(nxt)}))
            cur = nxt
    return links


def _selfcheck():
    m = LLAMA70B
    soc = wormhole.load()
    placement, rows, dram_for = build_map(m, soc)

    # every query head placed on a DISTINCT core
    heads = [qh for (_kv, qh) in placement.values()]
    assert len(heads) == len(set(heads)) == m.n_kv * m.g, f"{len(heads)} heads placed"
    assert set(heads) == set(range(m.n_q)), "not exactly the n_q query heads"

    # each KV head multicast to exactly g cores (its whole group)
    for kv, cores in rows.items():
        assert len(cores) == m.g, (kv, len(cores))
        assert len({y for _, y in cores}) == 1, "a group must share one physical row"

    # THE payoff: schedule reads the KV cache g-fold less than naive -- exactly.
    t = traffic(m, 32768, soc)
    assert abs(t["dram_reduction"] - m.g) < 1e-9, t["dram_reduction"]

    # and it does NOT stress the NoC: the multicast tree moves FEWER hop-bytes than the
    # naive independent pulls (shared links vs g separate paths). This is why the idle
    # NoC (decode_roofline.py: 4x headroom) absorbs it with room to spare.
    assert t["noc_ratio"] < 1.0, t["noc_ratio"]

    # tie-back: the g-fold DRAM cut is exactly what drove serving_multicast.py's 5.4x.
    print(f"selfcheck OK — {m.n_q} query heads on {len({*placement})} cores; "
          f"DRAM {t['dram_reduction']:.0f}x less; NoC {t['noc_ratio']:.2f}x of naive (less)")


def main():
    m = LLAMA70B
    soc = wormhole.load()
    placement, rows, dram_for = build_map(m, soc)
    print(f"\n  Multicast-aware GQA decode schedule — {m.name} on {soc['arch']}")
    print(f"  {m.n_q} query heads, {m.n_kv} KV heads, group g={m.g}; "
          f"{len(placement)} of {len(soc['nodes']['functional_workers'])} Tensix used\n")

    print(f"  Physical layout (row = KV head, columns = its {m.g} query heads):")
    for kv in list(rows)[:3]:
        xs = [x for x, _ in rows[kv]]
        y = rows[kv][0][1]
        print(f"    KV head {kv}: row y={y}, cols x={xs}, fed from DRAM {dram_for[kv]}"
              f"  (multicast along the row)")
    print(f"    ... {m.n_kv} rows total\n")

    print(f"  Traffic per layer per decode step (BF16), schedule vs naive re-fetch:\n")
    print(f"    {'context':>8} {'DRAM sched':>11} {'DRAM naive':>11} {'DRAM cut':>9} "
          f"{'NoC vs naive':>13}")
    for seq in (8192, 32768, 131072):
        t = traffic(m, seq, soc)
        print(f"    {seq:>7}  {t['dram_sched'] / 1e6:>9.1f}MB {t['dram_naive'] / 1e6:>9.1f}MB "
              f"{t['dram_reduction']:>7.0f}x {t['noc_ratio']:>11.2f}x")

    print(f"\n  The DRAM column is the win: each KV head crosses the memory bus ONCE, not")
    print(f"  {m.g} times. The NoC column shows the cost is MORE than paid for — the")
    print(f"  multicast tree moves fewer hop-bytes than {m.g} independent DRAM pulls,")
    print(f"  because the group shares links. So the idle NoC absorbs it with room to")
    print(f"  spare, and DRAM -- the actual bottleneck -- carries {m.g}x less.")

    print(f"\n  Why no exotic topology: 'share a KV head with its group' = ROW-MULTICAST,")
    print(f"  'combine context chunks' = COLUMN-REDUCE. A plain mesh/torus does both")
    print(f"  natively. The schedule is the lever; the graph shape is not.")

    print(f"\n  Long context: the KV cache dwarfs L1 (1.5 MB), so it STREAMS from DRAM in")
    print(f"  tiles -- each tile read once, multicast to its row, consumed online. When a")
    print(f"  single core cannot keep up with one head's context, split it down the")
    print(f"  column and online-softmax reduce (uses the {10 - m.n_kv} spare rows or batches).")


if __name__ == "__main__":
    _selfcheck() if "--selfcheck" in sys.argv else main()
