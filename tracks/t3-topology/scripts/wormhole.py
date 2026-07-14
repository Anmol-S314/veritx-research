#!/usr/bin/env python3
"""The Tenstorrent Wormhole NoC, from the vendor's own SoC descriptor. (T3, Gate 0)

PITFALLS 11c is "the nodes are not tiles": we spent two days pricing 64 NoC nodes as
64 compute tiles when they were 32 injection ports on 2 cores plus 32 DRAM channels.
This module exists so that mistake cannot be repeated on the new target. Nothing here
is inferred, described, or remembered -- it is parsed from
`hw/wormhole_b0_80_arch.yaml`, vendored verbatim from tt-metal.

WHAT THE CHIP ACTUALLY IS
  NoC grid       : 10 x 12 = 120 nodes   (NOT "8x10" -- that is only the Tensix subset)
  Tensix workers : 80   x in {1,2,3,4,6,7,8,9}, y in {1..5, 7..11}
  DRAM endpoints : 18   in COLUMNS x=0 and x=5  -- INTERIOR, not an edge strip
  Ethernet       : 16   in ROWS y=0 and y=6
  ARC / PCIe     : 1 / 1
  router-only    : 4
  -------------------------------------------------------------------------
  every one of the 120 nodes is accounted for; `_selfcheck` asserts it.

  Topology  : 2D TORUS (wraparound), TWO unidirectional NoC planes (NOC0, NOC1)
              running in OPPOSITE directions.        [tt-metal METALIUM_GUIDE.md]
  Routing   : row-first dimension-order (X then Y).  [docs.tenstorrent.com]
  L1        : 1,499,136 B per Tensix -> ~114 MiB on chip
  DRAM      : 12 GiB total, 288 GB/s                 [tt-metal FlashAttention report]

THE TWO FACTS THAT MATTER MOST, AND THEY CUT AGAINST OUR OWN PLAN

  1. DRAM SITS IN INTERIOR COLUMNS (x=0 and x=5), not on the die edge. Column 5 runs
     straight down the MIDDLE of the Tensix array, splitting it into two 4-wide
     halves. `floorplan.py` models TPU DRAM as an edge PHY strip; that is right for a
     TPU and WRONG here. Do not reuse it for Wormhole without re-deriving.

  2. THE NOC CARRIES BOTH KINDS OF TRAFFIC. tt-metal, on the Tensix RISC cores:
     "RISC0 and RISC1 are capable of issuing NoC transfers to move data from
      L1 <-> L1 and L1 <-> DRAM."
     There is ONE fabric. The tile-to-tile / memory-fabric split that PLAN.md was
     built around is a false dichotomy on this chip. See PLAN.md section 2.

    python3 scripts/wormhole.py [--selfcheck]
"""
import sys
from pathlib import Path

import yaml

HW = Path(__file__).parent.parent / "hw" / "wormhole_b0_80_arch.yaml"

# Node classes in the descriptor. `harvested_workers` is empty on the 80-core part
# (real n150 cards harvest a row down to 72 -- the descriptor is the full die).
KINDS = ("functional_workers", "dram", "eth", "arc", "pcie",
         "router_only", "harvested_workers")


def _coords(v):
    """Descriptor coords are "x-y" strings, sometimes nested (dram is banks x endpoints)."""
    out = []
    for item in (v or []):
        for c in (item if isinstance(item, list) else [item]):
            x, y = map(int, str(c).split("-"))
            out.append((x, y))
    return out


def load(path=HW):
    d = yaml.safe_load(path.read_text())
    return {
        "grid": (d["grid"]["x_size"], d["grid"]["y_size"]),
        "nodes": {k: _coords(d.get(k)) for k in KINDS},
        "l1_bytes": d["worker_l1_size"],
        "dram_bank_bytes": d["dram_bank_size"],
        "n_dram_banks": len(d["dram"]),
        "arch": d["arch_name"],
    }


def node_type(soc):
    """(x, y) -> kind. The census, inverted -- this is what a traffic model needs."""
    return {xy: k for k, v in soc["nodes"].items() for xy in v}


def torus_hops(a, b, grid):
    """Row-first DOR on a wraparound torus: |dx| and |dy| take the SHORT way round.

    This is the whole reason Tenstorrent chose a torus -- the wraparound halves the
    worst-case distance. On a 10x12 mesh the far corner is 20 hops; on the torus it
    is 11.
    """
    X, Y = grid
    dx = min(abs(a[0] - b[0]), X - abs(a[0] - b[0]))
    dy = min(abs(a[1] - b[1]), Y - abs(a[1] - b[1]))
    return dx + dy


def _selfcheck():
    soc = load()
    X, Y = soc["grid"]
    n = soc["nodes"]

    # GATE 0. Every NoC node must be classified. If this fails we do not know what the
    # chip is, and no traffic model may be written. This is the check PITFALLS 11c
    # says we should have run BEFORE the last study, not after it.
    total = sum(len(v) for v in n.values())
    assert total == X * Y, f"census {total} != grid {X}x{Y}={X * Y} — NODES UNACCOUNTED FOR"

    # no two kinds may claim the same coordinate
    seen = [xy for v in n.values() for xy in v]
    assert len(seen) == len(set(seen)), "a NoC node is claimed by two kinds"

    assert (X, Y) == (10, 12), f"grid moved: {X}x{Y}"
    assert len(n["functional_workers"]) == 80
    assert len(n["dram"]) == 18 and soc["n_dram_banks"] == 6

    # DRAM is INTERIOR, in two columns -- not an edge strip. This is the fact that
    # invalidates reusing floorplan.py's TPU layout, so pin it.
    dram_x = {x for x, _ in n["dram"]}
    assert dram_x == {0, 5}, f"DRAM columns moved: {dram_x}"
    assert 5 in dram_x, "column 5 splits the Tensix array — the whole point"

    # Tensix form two 4-wide blocks either side of the DRAM column
    wx = sorted({x for x, _ in n["functional_workers"]})
    assert wx == [1, 2, 3, 4, 6, 7, 8, 9], wx

    # the torus must actually be shorter than a mesh would be, or there is no reason
    # for Tenstorrent to have built one
    far = torus_hops((0, 0), (X // 2, Y // 2), (X, Y))
    assert far == X // 2 + Y // 2 == 11, far
    assert torus_hops((0, 0), (X - 1, Y - 1), (X, Y)) == 2, "wraparound not working"

    print(f"selfcheck OK — {total} NoC nodes, all classified; "
          f"{len(n['functional_workers'])} Tensix, DRAM in columns {sorted(dram_x)}")


def main():
    soc = load()
    X, Y = soc["grid"]
    n = soc["nodes"]
    print(f"\n  {soc['arch']} — NoC grid {X} x {Y} = {X * Y} nodes\n")
    for k, v in n.items():
        if not v:
            continue
        xs = sorted({x for x, _ in v})
        ys = sorted({y for _, y in v})
        print(f"    {k:20s} {len(v):>4}   x={xs}\n{'':26s}y={ys}")
    print(f"\n    L1 per Tensix : {soc['l1_bytes'] / 1024:,.0f} KiB"
          f"  ->  {len(n['functional_workers']) * soc['l1_bytes'] / 2**20:.0f} MiB on-chip")
    print(f"    DRAM          : {soc['n_dram_banks']} banks x "
          f"{soc['dram_bank_bytes'] / 2**30:.0f} GiB = "
          f"{soc['n_dram_banks'] * soc['dram_bank_bytes'] / 2**30:.0f} GiB")
    print(f"\n  Topology : 2D TORUS, 2 unidirectional planes (NOC0/NOC1, opposite dirs)")
    print(f"  Routing  : row-first dimension-order (X then Y)")
    print(f"\n  DRAM is in INTERIOR columns {sorted({x for x, _ in n['dram']})} — column 5 splits")
    print(f"  the Tensix array in half. It is NOT an edge PHY strip, so floorplan.py's")
    print(f"  TPU layout does not transfer.\n")


if __name__ == "__main__":
    _selfcheck() if "--selfcheck" in sys.argv else main()
