#!/usr/bin/env python3
"""Where the 64 NoC nodes actually SIT on the die. (T3)

Everything about the energy verdict rests on wire length, and every earlier
version of this study got wire length from a floorplan that does not exist:

    "64 tiles on an 8x8 grid at a 3.767 mm pitch"

That is wrong twice, and both errors inflate the die:

  1. THE NODES ARE NOT TILES. PyTorchSim's config is `num_cores: 2` with
     `icnt_injection_ports_per_core: 16`. Nodes 0-15 are SIXTEEN INJECTION PORTS
     OF ONE CORE, and 16-31 are core 1's. They are ports on two big cores, not
     32 independent compute tiles scattered across the die. Ports of the same
     core are physically close.

  2. DRAM CHANNELS ARE NOT TILES EITHER. Nodes 32-63 are memory channels. In
     silicon those are controllers + PHYs at the DIE EDGE, next to the HBM
     stacks. Modelling them as 32 tiles occupying half the die doubles the die
     area and stretches every compute<->DRAM path.

The node NUMBERING is fixed by BookSim (row-major over an 8x8 grid: id = 8*row +
col) and by TOGSim (0-31 compute, 32-63 DRAM). Together those force the layout:

    rows 0-1  = core 0's 16 ports   (ids  0-15)   \
    rows 2-3  = core 1's 16 ports   (ids 16-31)   /  compute, W x W mm, 908 mm^2
    rows 4-7  = the 32 DRAM channels (ids 32-63)  -> an HBM PHY STRIP, ~2 mm deep

    +--------------------------------+  y=0
    |         core 0  (rows 0,1)     |
    |         core 1  (rows 2,3)     |   compute square, W = 30.1 mm
    +--------------------------------+  y=W
    |####  HBM PHY strip (rows 4-7) #|   PHY_DEPTH_MM = 2.0, NOT 4 tile rows
    +--------------------------------+

The one substantive change from the old model is the last line. Rows 4-7 were
priced as 32 TILES, each a full 3.767 mm pitch, so the DRAM region alone was
half the die -- 454 mm^2 of silicon for what is really a 60 mm^2 PHY strip. That
inflated the die 2x in y, and every compute<->DRAM path with it.

Link lengths for every topology are MEASURED from these coordinates (Manhattan --
wires route on a Manhattan grid) rather than assumed to be one tile pitch per hop.

The LOGICAL topology (who is adjacent to whom, how many hops) still comes from
BookSim. This module only says how far apart the two endpoints of each logical
link physically are. Those are separate questions and conflating them is exactly
what went wrong.

    python3 scripts/floorplan.py [--selfcheck]
"""
import math
import sys

N_COMPUTE = 32
N_TOTAL = 64
GRID = 8                 # BookSim's 8x8: id = GRID*row + col

# Compute silicon, same basis as wire_area.py: 2 cores x 2 systolic 128x128 of
# fp32 MACs at 8,316 um^2 (Accelergy fpmac, 45nm), 60% logic density. The compute
# region is whatever square holds that. This is the ONE size constant, and it is
# swept in energy_verdict.py because the verdict turns on it.
MACS = 2 * 2 * 128 * 128
FPMAC_UM2 = 8316.0
LOGIC_DENSITY = 0.6

# Depth of the HBM PHY strip that holds all 32 memory-channel controllers. Real
# HBM PHYs are 1-2 mm deep. The old model gave this region 454 mm^2 -- half the
# die -- by treating each channel as a compute-sized tile.
PHY_DEPTH_MM = 2.0


def die_side_mm(mac_um2=FPMAC_UM2, macs=MACS, density=LOGIC_DENSITY):
    """Side of the square COMPUTE region, mm. The PHY strip sits below it."""
    return math.sqrt(macs * mac_um2 / density) / 1000.0


def positions(W=None, phy_depth=None):
    """node id -> (x, y) in mm. The floorplan, and the only place it is defined."""
    W = die_side_mm() if W is None else W
    # read the module global at CALL time, not def time -- the sensitivity sweep
    # in energy_verdict.py rebinds PHY_DEPTH_MM, and a default arg would freeze it.
    phy_depth = PHY_DEPTH_MM if phy_depth is None else phy_depth
    px = W / GRID                  # x pitch: 8 columns across the compute region
    py = W / 4.0                   # y pitch: compute is only 4 rows deep (0-3)
    pd = phy_depth / 4.0           # y pitch inside the PHY strip (rows 4-7)
    pos = {}
    for i in range(N_TOTAL):
        row, col = i // GRID, i % GRID
        x = (col + 0.5) * px
        if row < 4:                                    # compute ports
            y = (row + 0.5) * py
        else:                                          # DRAM channel PHYs
            y = W + (row - 4 + 0.5) * pd
        pos[i] = (x, y)
    return pos


def dist(pos, a, b):
    """Manhattan mm between two nodes."""
    return abs(pos[a][0] - pos[b][0]) + abs(pos[a][1] - pos[b][1])


# --- routes: which nodes/switches a packet physically passes through ----------

def _mesh_route(s, d, k=8):
    """Dimension-order route over the LOGICAL 8x8 grid (id = k*row + col)."""
    path, cur = [s], s
    while cur % k != d % k:                       # x first
        cur += 1 if d % k > cur % k else -1
        path.append(cur)
    while cur // k != d // k:                     # then y
        cur += k if d // k > cur // k else -k
        path.append(cur)
    return path


def _fattree_switches(pos, k=4, n=3):
    """Level-L switch sits at the centroid of the leaves it serves."""
    sw = {}
    for L in range(1, n + 1):
        for g in range(N_TOTAL // k ** L):
            leaves = range(g * k ** L, (g + 1) * k ** L)
            sw[(L, g)] = (sum(pos[i][0] for i in leaves) / k ** L,
                          sum(pos[i][1] for i in leaves) / k ** L)
    return sw


def path_mm(topo, W=None):
    """Mean PHYSICAL link length a compute<->DRAM packet traverses, in mm.

    Averaged over all 32x32 compute-DRAM pairs -- the only traffic there is
    (Simulator.cc:237: requests go to nodes 32-63, replies to 0-31; there is no
    compute-to-compute traffic).
    """
    pos = positions(W)
    pairs = [(s, d) for s in range(N_COMPUTE) for d in range(N_COMPUTE, N_TOTAL)]

    if topo == "mesh":
        tot = sum(sum(dist(pos, a, b) for a, b in zip(r, r[1:]))
                  for s, d in pairs for r in [_mesh_route(s, d)])

    elif topo == "fattree":
        k, n = 4, 3
        sw = _fattree_switches(pos, k, n)

        def md(p, q):
            return abs(p[0] - q[0]) + abs(p[1] - q[1])

        def one(s, d):
            # climb to the nearest common ancestor, then back down
            top = next((L for L in range(1, n + 1)
                        if s // k ** L == d // k ** L), n)
            up = [pos[s]] + [sw[(L, s // k ** L)] for L in range(1, top + 1)]
            down = [sw[(L, d // k ** L)] for L in range(top, 0, -1)] + [pos[d]]
            legs = up + down
            return sum(md(a, b) for a, b in zip(legs, legs[1:]))

        tot = sum(one(s, d) for s, d in pairs)

    elif topo == "fly":
        # one central crossbar, placed at the centroid of everything it serves
        cx = sum(p[0] for p in pos.values()) / N_TOTAL
        cy = sum(p[1] for p in pos.values()) / N_TOTAL
        tot = sum(abs(pos[s][0] - cx) + abs(pos[s][1] - cy) +
                  abs(pos[d][0] - cx) + abs(pos[d][1] - cy) for s, d in pairs)
    else:
        raise ValueError(topo)

    return tot / len(pairs)


def mean_link_mm(topo, W=None):
    """Mean length of a SINGLE link — for repeater counting, not path energy."""
    pos = positions(W)
    if topo == "mesh":
        k = 8
        links = [(i, i + 1) for i in range(N_TOTAL) if i % k != k - 1]
        links += [(i, i + k) for i in range(N_TOTAL - k)]
    elif topo == "fattree":
        k, n = 4, 3
        sw = _fattree_switches(pos, k, n)
        p = dict(pos)
        p.update({f"s{L}{g}": v for (L, g), v in sw.items()})
        links = [(i, f"s1{i // k}") for i in range(N_TOTAL)]
        links += [(f"s{L}{g}", f"s{L + 1}{g // k}")
                  for L in range(1, n) for g in range(N_TOTAL // k ** L)]
        return sum(abs(p[a][0] - p[b][0]) + abs(p[a][1] - p[b][1])
                   for a, b in links) / len(links)
    elif topo == "fly":
        cx = sum(q[0] for q in pos.values()) / N_TOTAL
        cy = sum(q[1] for q in pos.values()) / N_TOTAL
        return sum(abs(q[0] - cx) + abs(q[1] - cy) for q in pos.values()) / N_TOTAL
    else:
        raise ValueError(topo)
    return sum(dist(pos, a, b) for a, b in links) / len(links)


def _selfcheck():
    W = die_side_mm()
    pos = positions(W)
    assert len(pos) == N_TOTAL

    # THE correction: the 32 DRAM nodes live in a thin PHY strip, not in 32
    # tile-sized cells. If this ever regresses, the die doubles and every wire
    # number in the study is wrong again.
    dram_y = [pos[i][1] for i in range(N_COMPUTE, N_TOTAL)]
    assert max(dram_y) - min(dram_y) < PHY_DEPTH_MM, "DRAM strip has grown into tiles"
    assert min(dram_y) >= W, "DRAM must sit outside the compute region"
    # compute ports stay inside the compute square
    assert all(0 < pos[i][0] < W and 0 < pos[i][1] < W for i in range(N_COMPUTE))
    # logical mesh neighbours must be PHYSICAL neighbours -- that is the whole
    # premise of a mesh, and the placement has to honour it.
    assert dist(pos, 0, 1) < W / 4, "horizontal mesh link should be one x pitch"
    assert dist(pos, 0, GRID) < W / 2, "vertical mesh link should be one y pitch"

    for t in ("mesh", "fattree", "fly"):
        assert 0 < path_mm(t) < 40 * W, t

    # THE INVARIANT. Dimension-order routing on a mesh whose logical grid IS its
    # physical grid traverses exactly the Manhattan distance from src to dst --
    # the shortest path any wire can take. Every other topology hauls the packet
    # through an intermediate switch, so it can only detour. The mesh is
    # wire-optimal BY CONSTRUCTION, and no rewiring can beat it on distance.
    pairs = [(s, d) for s in range(N_COMPUTE) for d in range(N_COMPUTE, N_TOTAL)]
    lower_bound = sum(dist(pos, s, d) for s, d in pairs) / len(pairs)
    assert abs(path_mm("mesh") - lower_bound) < 1e-9, (path_mm("mesh"), lower_bound)
    for t in ("fattree", "fly"):
        assert path_mm(t) > path_mm("mesh"), (t, path_mm(t))

    assert die_side_mm(10000) > die_side_mm(1000)
    print("selfcheck OK")


def main():
    W = die_side_mm()
    print(f"\n  Compute region : {W:.1f} x {W:.1f} mm  ({W * W:,.0f} mm^2), rows 0-3")
    print(f"                   core 0 = rows 0-1 (ids 0-15), core 1 = rows 2-3 (16-31)")
    print(f"  HBM PHY strip  : {W:.1f} x {PHY_DEPTH_MM} mm, rows 4-7 (ids 32-63)")
    print(f"  x pitch {W / GRID:.2f} mm, y pitch {W / 4:.2f} mm\n")
    print(f"  {'topology':<9} {'mean link mm':>13} {'path mm':>9}   (compute<->DRAM)")
    for t in ("mesh", "fattree", "fly"):
        print(f"  {t:<9} {mean_link_mm(t):>13.2f} {path_mm(t):>9.1f}")
    print(f"\n  OLD model (32 DRAM channels priced as 32 full compute TILES):")
    print(f"    mesh 25.0 / fattree 105.5 / fly 15.1 mm")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--selfcheck":
        _selfcheck()
    else:
        main()
