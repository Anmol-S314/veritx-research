#!/usr/bin/env python3
"""Link cost for the PyTorchSim topology sweep — repeaters (silicon) + tracks (metal).

Supersedes a first version of this file that was wrong in two ways. Both errors
flattered the mesh, and both are worth stating because the conclusion moved:

  1. DATATYPE. It priced the compute tile with an 8-bit `intmac` (466 um^2).
     PyTorchSim runs float32 (tests build tensors with torch.randn), so the right
     primitive is `fpmac` -- roughly 8x the area. The tile is much bigger, the
     die is much bigger, and every wire is therefore much longer.

  2. WIRE AREA IS NOT SILICON AREA. It charged `length * bits * metal_pitch` as
     though metal competed with logic for die area. It does not: NoC links route
     on upper metal OVER the cells. What a long link actually costs is
       (a) REPEATERS, which are real silicon, and
       (b) ROUTING TRACKS, which are a finite resource -- a feasibility limit,
           not an area adder.
     Charging metal as silicon roughly tripled the fat-tree's apparent cost.

So: silicon = routers + repeaters. Metal = track demand, reported as a
utilization check that can FAIL rather than as an area tax.

    python3 scripts/wire_area.py [--pitch-sweep]
"""
import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

NODES = 64
GRID = 8                 # the 64 NoC endpoints spread over the die as an 8x8 grid
# Booksim's flit_size is in BYTES (Interconnect.cpp:221), so the sweep's
# `flit_size = 32` is 32 BYTES = 256 bits. This is the PHYSICAL LINK WIDTH, so it
# sets how many metal tracks a channel needs and how many repeaters it carries.
FLIT_BITS = 32 * 8       # 256-bit links

# --- 45nm physical constants -------------------------------------------------
# Global-metal pitch. Wide NoC links go on thick upper metal, which is COARSER
# than the 0.2um intermediate pitch the previous version used.
METAL_PITCH_UM = 0.4
METAL_LAYERS_FOR_NOC = 2     # how many upper layers the NoC may claim
# Optimal repeater spacing for global wires at 45nm is a few hundred um; below
# this a link needs no repeater at all.
REPEATER_SPACING_UM = 400.0
# One repeater = an inverter pair, per bit, per span. Small but it adds up:
# a 64-node fat-tree has thousands of them.
REPEATER_UM2_PER_BIT = 2.0

# Router areas from pytorchsim_area.py (Accelergy, radix-scaled crossbar+buffers).
ROUTER_UM2 = {"mesh": 1_663_314.0, "fattree": 1_842_155.0, "fly": 870_271.0}
CYCLES = {"fly": 303_850, "fattree": 400_147, "mesh": 759_544}

# Channel counts from Booksim's own constructors (see pytorchsim_area.shape).
CHANNELS = {"mesh": 256, "fattree": 256, "fly": 64}


def tile_pitch_um(mac_um2, macs_total=2 * 2 * 128 * 128, logic_density=0.6):
    """Die side / GRID, from the compute that actually has to fit on it.

    PyTorchSim's TPUv3-class config: 2 cores x 2 systolic arrays of 128x128.
    `logic_density` is the fraction of die that is MACs -- the rest is SRAM,
    control, PHY. 0.6 is generous to the mesh (a denser die = shorter wires).
    """
    die_um2 = macs_total * mac_um2 / logic_density
    return math.sqrt(die_um2) / GRID


def link_lengths(topo, pitch):
    """[(length_um, count)] for every channel in the topology."""
    if topo == "mesh":                    # nearest neighbour, one pitch each
        return [(pitch, CHANNELS["mesh"])]
    if topo == "fattree":                 # k=4, n=3; 128 channels per level
        k, n = 4, 3
        # a level-L switch serves k^L tiles = a sqrt(k^L)-wide patch of floorplan
        return [(math.sqrt(k ** L) * pitch, 128) for L in range(1, n)]
    if topo == "fly":                     # every node -> one central router
        c = (GRID - 1) / 2.0
        mean = sum(abs(x - c) + abs(y - c)
                   for x in range(GRID) for y in range(GRID)) / NODES
        return [(mean * pitch, NODES)]
    raise ValueError(topo)


def repeater_um2(topo, pitch):
    """Silicon cost of the links: repeaters only. Metal is not silicon."""
    total = 0.0
    for length, count in link_lengths(topo, pitch):
        spans = max(0, int(length / REPEATER_SPACING_UM))   # 0 for a short link
        total += count * spans * FLIT_BITS * REPEATER_UM2_PER_BIT
    return total


def track_demand(topo, pitch):
    """(demanded_tracks, available_tracks) at the die's worst cut.

    Bisection: half the channels must cross the die midline in the worst case.
    Available = die width / metal pitch, times the layers the NoC may use.
    """
    die_side = pitch * GRID
    available = (die_side / METAL_PITCH_UM) * METAL_LAYERS_FOR_NOC
    # crude bisection: mesh cuts GRID channels per row; fat-tree's top level all
    # crosses; fly's links all converge through the middle.
    if topo == "mesh":
        crossing = GRID * 2          # 8 columns x 2 directions
    elif topo == "fattree":
        crossing = 128               # the entire top level spans the die
    else:
        crossing = NODES // 2
    return crossing * FLIT_BITS, available


def evaluate(mac_um2):
    pitch = tile_pitch_um(mac_um2)
    rows = {}
    for t in ROUTER_UM2:
        rep = repeater_um2(t, pitch)
        dem, avail = track_demand(t, pitch)
        rows[t] = {
            "router_um2": round(ROUTER_UM2[t], 1),
            "repeater_um2": round(rep, 1),
            "silicon_um2": round(ROUTER_UM2[t] + rep, 1),
            "tracks_demanded": int(dem),
            "tracks_available": int(avail),
            "routable": dem <= avail,
            "cycles": CYCLES[t],
        }
    base = rows["mesh"]
    for r in rows.values():
        r["speedup_vs_mesh"] = round(base["cycles"] / r["cycles"], 2)
        r["area_vs_mesh"] = round(r["silicon_um2"] / base["silicon_um2"], 2)
        r["perf_per_area"] = round(r["speedup_vs_mesh"] / r["area_vs_mesh"], 2)
    return pitch, rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mac-um2", type=float, default=None,
                    help="MAC area; default: query Accelergy for an fpmac")
    ap.add_argument("--pitch-sweep", action="store_true")
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()
    if args.selfcheck:
        return _selfcheck()

    mac_um2 = args.mac_um2
    if mac_um2 is None:
        from area_report import check_estimators, run_accelergy
        check_estimators()
        arch = {"architecture": {"version": 0.3, "subtree": [{"name": "system", "local": [
            {"name": "FPMAC", "class": "fpmac",
             "attributes": {"technology": 45, "exponent": 8, "mantissa": 23,
                            "n_instances": 1}},
        ]}]}}
        mac_um2 = run_accelergy(arch)["FPMAC"]
        print(f"  Accelergy fpmac (fp32, 45nm): {mac_um2:,.0f} um^2 per MAC")

    pitch, rows = evaluate(mac_um2)
    die_mm = pitch * GRID / 1000
    print(f"  65,536 MACs -> die {die_mm:.1f} mm a side, tile pitch {pitch:.0f} um\n")
    print(f"  {'topology':<9} {'routers':>11} {'repeaters':>11} {'silicon':>11} "
          f"{'tracks':>14} {'speedup':>8} {'area':>7} {'perf/area':>10}")
    for t in ("mesh", "fattree", "fly"):
        r = rows[t]
        tk = f"{r['tracks_demanded']:,}/{r['tracks_available']:,}"
        flag = "" if r["routable"] else "  UNROUTABLE"
        print(f"  {t:<9} {r['router_um2']:>11,.0f} {r['repeater_um2']:>11,.0f} "
              f"{r['silicon_um2']:>11,.0f} {tk:>14} {r['speedup_vs_mesh']:>7.2f}x "
              f"{r['area_vs_mesh']:>6.2f}x {r['perf_per_area']:>9.2f}x{flag}")

    out = HERE.parent / "results" / "wire_area.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"mac_um2": mac_um2, "tile_pitch_um": round(pitch, 1),
                               "topologies": rows}, indent=2))
    ft = rows["fattree"]
    win = "fat-tree" if ft["perf_per_area"] > 1 else "mesh"
    print(f"\n  VERDICT: {win} wins on perf/area (fat-tree = {ft['perf_per_area']}x)")
    print(f"  -> {out}")

    if args.pitch_sweep:
        print(f"\n  Sensitivity — MAC area sets the die, the die sets wire length:\n")
        print(f"  {'MAC um2':>9} {'die mm':>7} {'fattree area':>13} {'perf/area':>10}  winner")
        for m in (100, 466, 1000, 2000, 3400, 6000, 10000):
            p, rr = evaluate(m)
            f = rr["fattree"]
            w = "fattree" if f["perf_per_area"] > 1 else "mesh"
            print(f"  {m:>9,} {p * GRID / 1000:>6.1f}  {f['area_vs_mesh']:>12.2f}x "
                  f"{f['perf_per_area']:>9.2f}x  {w}")


def _selfcheck():
    # a fat-tree's links are strictly longer than a mesh's, so it needs strictly
    # more repeaters at any pitch where repeaters exist at all
    p = 2000.0
    assert repeater_um2("fattree", p) > repeater_um2("mesh", p)
    # short links need NO repeaters -- the model must not charge for them
    assert repeater_um2("mesh", 100.0) == 0.0, "a 100um link needs no repeater"
    # tile pitch must grow with MAC area (bigger compute -> bigger die)
    assert tile_pitch_um(3400) > tile_pitch_um(466)
    # fp32 MACs must give a plausible die: 65k fp32 MACs is a big chip, >10mm
    assert tile_pitch_um(3400) * GRID / 1000 > 10
    # the fat-tree's top level must dominate its track demand
    d_ft, _ = track_demand("fattree", 1000)
    d_m, _ = track_demand("mesh", 1000)
    assert d_ft > d_m, (d_ft, d_m)
    print("selfcheck OK")


if __name__ == "__main__":
    main()
