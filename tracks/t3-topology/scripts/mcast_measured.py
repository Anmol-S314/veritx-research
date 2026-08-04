#!/usr/bin/env python3
"""Official Tenstorrent multicast throughput curves, extracted from their silicon study. (T3)

SOURCE: tenstorrent/tt-low-level-documentation, data_movement_doc/multicast_schemes/
        "Multicast Schemes.md" (commit ae7661c8, Oct 2025) -- the deliverable of
        tenstorrent/tt-metal#22519 "[DM]: Document and test all possible multicast
        schemes with NOC" (closed). Metric: sustained multicast-write throughput in
        bytes/cycle vs destination grid size, measured on Wormhole B0 and Blackhole P100.

The numbers below were extracted PIXEL-LEVEL from the published plot images
(images/plots/WH_noloopback.png) with an axis-calibration script (31.746-0.01036*y for
NoC0, 29.28-0.00595*y for NoC1) -- see the git history / hardware README for the
extraction. This is the LOOPBACK-DISABLED dataset: the sender is excluded from the
destination grid, which is exactly TT-Metalium's default for noc_async_write_multicast
and the geometry of our KV row-broadcast.

WHAT THE CURVES SAY (the correction this file exists to make explicit):
  * For sender placements that share the congested write path with the write-ACK
    return path (row-shared on NoC1, column-shared on NoC0), sustained throughput
    DEGRADES with grid size -- up to ~15% from 2x2 to 7x7 (the self-interference loop).
  * For our geometry -- a row multicast on NoC0 (schemes 5/8, "sender outside grid,
    shared row", NoC0 routes these well) -- throughput is essentially FLAT in fanout:
    30.59 -> 29.79 B/cyc across 4..49 destinations (<3% total).
  * Absolute floor: even the worst (misconfigured) case sustains ~26 B/cyc, i.e. ~0.82
    of a 32 B/cyc link. Our KV row feed is 14.6 GB/s -> >=1.8x headroom in EVERY case.

So the "multicast ~free in fanout" premise of serving_multicast.py / decode_e2e.py is
VINDICATED for the correct NoC+placement choice (and quantified to <3% over our fanout
range), and FALSIFIED for the wrong one -- which is now a design constraint with a
silicon citation, not a hand-wave.

WHICH SCHEME IS OURS: the schedule multicasts one KV head along a row of g cores
(sender at row head, receivers along the row, sender excluded). That is "sender
outside the destination grid, sharing the row" -- scheme 5 (BL corner) / 8 (TR corner).
Readers default to NOC0 (RISCV_0), and on NoC0 the row-shared schemes are the GOOD
ones. Requirement: do NOT run the row multicast on NoC1 (row-shared on NoC1 is the
self-interference case).

    python3 scripts/mcast_measured.py [--selfcheck]
"""
import sys

# Grid sizes the study swept (square m x m destination grids), Wormhole B0.
GRIDS = [2, 3, 4, 5, 6, 7]

# bytes/cycle vs grid size, 10 sender-placement schemes (order as the study's
# Schemes_Grid_Diagram.png: 1-4 sender inside grid at the 4 corners; 5-7 outside
# grid BL; 8-10 outside grid TR; 5/8 row-shared, 6/9 col-shared, 7/10 no-share).
# None = not resolvable at that grid in the plot (curve covered/off-axis).
NOC0 = {  # loopback disabled, Wormhole B0, NoC instance 0
    1: [30.96, 30.62, None, None, 27.80, 26.89],
    2: [None, 30.45, 29.79, 28.97, 28.03, None],
    3: [None, 30.30, 29.69, 28.85, 28.09, 26.91],
    4: [30.88, 30.57, 29.85, 28.93, 27.85, 26.97],
    5: [30.59, 30.39, 30.16, 30.04, 29.90, 29.79],   # <- ours: row-shared BL
    6: [30.56, 29.99, 29.25, 28.52, 27.53, 26.29],   #    col-shared BL (bad on NoC0)
    7: [None, 30.40, 30.20, 30.06, 29.92, 29.80],    #    no-share BL
    8: [30.77, 30.50, 30.34, 30.25, 30.06, 29.92],   #    row-shared TR
    9: [30.71, 30.11, 29.30, 28.40, 27.48, 26.34],   #    col-shared TR (bad on NoC0)
    10: [30.64, 30.35, 30.11, 29.99, 29.85, 29.75],  #    no-share TR
}

NOC1 = {
    1: [28.77, None, None, 28.17, 27.51, None],
    2: [None, None, 28.47, 28.13, 27.47, 26.67],
    3: [28.61, 28.69, 28.63, None, 27.83, 26.84],
    4: [28.76, None, None, None, 27.80, 26.75],
    5: [28.72, 28.72, 28.71, 28.28, 27.32, 26.15],   # row-shared BL (bad on NoC1)
    6: [28.66, 28.68, 28.66, 28.63, 28.71, 28.63],   # col-shared BL (good on NoC1)
    7: [28.74, 28.65, 28.71, 28.70, 28.68, 28.71],
    8: [28.74, 28.74, 28.53, 28.01, 27.19, 26.19],   # row-shared TR (bad on NoC1)
    9: [28.78, 28.77, 28.74, 28.74, 28.79, 28.75],
    10: [28.70, 28.82, 28.80, 28.66, 28.75, 28.67],
}

LINK_BCYC = 32.0             # one Wormhole NoC link: 256 bit/cyc @ 1 GHz = 32 B/cyc
OUR_SCHEMES = (5, 8)         # row-shared placements = the KV row-broadcast geometry
OUR_NOC = 0                  # readers default to NOC0; row-shared is GOOD there
ROW_FEED_GBS = 14.6          # decode_e2e.py's DRAM-per-endpoint x eps, the row's feed


def at(noc_table, scheme, grid):
    """bytes/cycle at a grid size (linear interpolation between measured points)."""
    xs = NOC0 if noc_table is None else noc_table
    vals = [v for g, v in zip(GRIDS, xs[scheme]) if v is not None]
    if not vals:
        return None
    if grid <= GRIDS[0]:
        return vals[0]
    if grid >= GRIDS[-1]:
        return vals[-1]
    for i in range(len(GRIDS) - 1):
        a, b = GRIDS[i], GRIDS[i + 1]
        va, vb = xs[scheme][i], xs[scheme][i + 1]
        if va is None or vb is None:
            continue
        if a <= grid <= b:
            return va + (vb - va) * (grid - a) / (b - a)
    return vals[-1]


def ours(grid=7):
    """Throughput of the KV row-multicast geometry (row-shared on NoC0), bytes/cycle.
    Conservatively pick the WORSE of the two row-shared schemes at that grid."""
    a = at(NOC0, 5, grid)
    b = at(NOC0, 8, grid)
    return min(a, b)


def worst(grid=7):
    """Worst-case sustained throughput across ALL schemes and BOTH NoCs at a grid."""
    vals = [v for tbl in (NOC0, NOC1) for s in range(1, 11)
            if (v := at(tbl, s, grid)) is not None]
    return min(vals)


def _selfcheck():
    # flatness of OUR geometry across the whole 4..49-destination sweep (<4% total)
    lo, hi = ours(2), ours(7)
    assert 0 <= (ours(2) - ours(7)) / ours(2) < 0.04, (lo, hi)
    # the misconfigured case (row-shared on NoC1) degrades >=3x MORE than ours
    # (the reason the design constraint exists: NoC0 for the row multicast)
    bad_noc1 = at(NOC1, 5, 2) - at(NOC1, 5, 7)
    our_drop = ours(2) - ours(7)
    assert bad_noc1 > 3 * our_drop, (bad_noc1, our_drop)
    # even the worst case keeps >= 0.8 of a full link
    assert worst(7) >= 0.8 * LINK_BCYC, worst(7)
    # headroom vs the schedule's row feed: ours >= 2x, worst >= 1.5x
    assert ours(7) >= 2.0 * ROW_FEED_GBS, ours(7)
    assert worst(7) >= 1.5 * ROW_FEED_GBS, worst(7)
    print(f"selfcheck OK — ours(row-shared NoC0): {ours(2):.2f}->{ours(7):.2f} B/cyc "
          f"({100*(1-ours(7)/ours(2)):.1f}% drop, 4..49 dests); worst-case {worst(7):.2f}; "
          f"row feed {ROW_FEED_GBS:.1f} GB/s -> headroom {ours(7)/ROW_FEED_GBS:.2f}x "
          f"(ours) / {worst(7)/ROW_FEED_GBS:.2f}x (worst)")


def main():
    print(f"\n  Official multicast curves, Wormhole B0, loopback disabled (sender excluded)")
    print(f"  source: tt-low-level-documentation 'Multicast Schemes' study (issue #22519)\n")
    print(f"  {'scheme':>7} {'desc':<22} " + "  ".join(f"{g}x{g}" for g in GRIDS))
    desc = {1: "inside TL", 2: "inside TR", 3: "inside BR", 4: "inside BL",
            5: "outside row BL", 6: "outside col BL", 7: "outside none BL",
            8: "outside row TR", 9: "outside col TR", 10: "outside none TR"}
    for s in range(1, 11):
        r = "  ".join(f"{v if v else 0:5.2f}" if v else "   --" for v in NOC0[s])
        mark = " <- ours" if s in OUR_SCHEMES else ""
        print(f"  NoC0 {s:>4} {desc[s]:<22} {r}{mark}")
    for s in range(1, 11):
        r = "  ".join(f"{v if v else 0:5.2f}" if v else "   --" for v in NOC1[s])
        mark = " <- bad on NoC1" if s in OUR_SCHEMES else ""
        print(f"  NoC1 {s:>4} {desc[s]:<22} {r}{mark}")

    print(f"\n  OUR geometry (KV row-broadcast, sender excluded, NOC0, row-shared):")
    print(f"    {ours(2):.2f} B/cyc at 2x2  ->  {ours(7):.2f} B/cyc at 7x7 "
          f"({100*(1-ours(7)/ours(2)):.1f}% total drop across 4..49 destinations)")
    print(f"    => multicast throughput is essentially FLAT in fanout for this placement.")
    print(f"  CONSTRAINT (from the study): row-shared on NoC1 or col-shared on NoC0 loses")
    print(f"    up to ~15% (30.9->26.3). Run the row multicast on NOC0, not NOC1.")
    print(f"  IMPLICATION for the decode model: row feed {ROW_FEED_GBS:.1f} GB/s vs")
    print(f"    sustained {ours(7):.1f} GB/s (ours) / {worst(7):.1f} GB/s (worst-case):")
    print(f"    headroom {ours(7)/ROW_FEED_GBS:.1f}x even at 49 destinations; DRAM still binds.")


if __name__ == "__main__":
    _selfcheck() if "--selfcheck" in sys.argv else main()
