#!/usr/bin/env python3
"""Does the fat-tree still win once ENERGY is counted? (T3)

Area said yes (1.27x area for 1.90x speed). But floonoc_calibrate.py found the
crossbar is 88% of per-hop energy, and crossbar energy is O(radix^2) -- so the
fat-tree's radix-6.7 routers are intrinsically hungrier than the mesh's radix-5.
It also does not obviously save hops. This is the check.

    NoC energy = flits * avg_hops(topology) * per_hop_energy(radix)

Traffic VOLUME is identical across the three runs (same TOG, same mapping, only
booksim_config_path differed), so it cancels: the energy RATIO needs only hops
and per-hop energy. That is the whole point -- we do not need the flit count.

HOPS are analytic, not measured. The raw BookSim logs from the sweep were lost,
and for these regular topologies under uniform traffic the closed forms are
exact anyway:

  mesh  8x8 : mean Manhattan distance, 2 * (k^2-1)/(3k) = 5.25 hops
  fattree   : up to the nearest common ancestor and back down. With k=4, n=3:
                 3/63 of destinations share a level-1 switch -> 2 hops
                12/63 share a level-2 switch                 -> 4 hops
                48/63 need the root                          -> 6 hops
              -> 5.43 hops
  fly       : one central crossbar -> 1 hop (but at radix 64)

CAVEAT: uniform-random destinations. The real traffic is compute<->DRAM (32
ports each), not uniform, and placement matters. This biases nothing obviously
in either direction, but it is an approximation and a measured hop count from
BookSim would supersede it.

    python3 scripts/energy_verdict.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from floonoc_calibrate import crossbar_pj, reg_pj  # Accelergy's own formulas

# Booksim's `flit_size` is in BYTES, not bits:
#     num_flits = pkt_size/flit_size + (pkt_size % flit_size ? 1 : 0)   [Interconnect.cpp:221]
# and TOGSim's packets are byte-sized DRAM requests. Every .icnt in the sweep set
# flit_size = 32, i.e. 32 BYTES = 256 bits. An earlier version of this file read
# it as 32 bits and under-reported per-flit energy 8x. Topology RATIOS were
# unaffected (the same flit size is used in every run), but the absolute pJ were
# wrong, so they are corrected here.
FLIT_BITS = 32 * 8      # 32-byte flits
# Prefill = BERT-base encoder, autotune mapping. (An earlier revision carried a
# stale mesh figure of 759,544 here; the sweep's mesh is 719,178 and that is what
# FINDINGS.md reports. The stale number inflated the fat-tree's speedup 1.80 -> 1.90.)
CYCLES = {"fly": 303_850, "fattree": 400_147, "mesh": 719_178}
# Decode = LLAMA-4 TP8 GQA, 10,240-token KV cache. Memory-bound, and the regime
# that actually runs in production -- so it gets its own EDP column.
DECODE = {"fly": 59_050, "fattree": 73_725, "mesh": 98_128}
RADIX = {"mesh": 5.0, "fattree": 6.7, "fly": 64.0}
# silicon area (routers + repeaters) from wire_area.py
SILICON_UM2 = {"mesh": 1_810_770.0, "fattree": 2_292_715.0, "fly": 1_021_823.0}


# TOGSim's traffic is strictly BIPARTITE, and this changes the hop counts a lot.
# Simulator.cc:237 (get_dest_node):
#   a request  goes to  num_cores*ports_per_core + dram_channel   -> node 32..63
#   a reply    goes to  core_id*ports_per_core + ...              -> node 0..31
# so nodes 0-31 are COMPUTE and 32-63 are DRAM, and there is NO compute-to-compute
# traffic. Every packet crosses between the halves.
#
# An earlier version of this file assumed uniform-random destinations and got
# 5.25 hops for the mesh. That is the wrong distribution: on a row-major 8x8 mesh
# the compute half is rows 0-3 and the DRAM half is rows 4-7, so every packet must
# also cross the midline. The true figure is 6.625 -- 26% higher -- and since the
# fat-tree/mesh EDP came out at 1.01x, a 26% hop error is decisive.
N_COMPUTE = 32
N_TOTAL = 64


def avg_hops(topo):
    """Mean hops for COMPUTE<->DRAM traffic only. Enumerated, not approximated."""
    compute = range(N_COMPUTE)              # nodes 0..31
    dram = range(N_COMPUTE, N_TOTAL)        # nodes 32..63

    if topo == "mesh":                      # 8x8, row-major: id = 8*row + col
        k = 8
        tot = sum(abs(s // k - d // k) + abs(s % k - d % k)
                  for s in compute for d in dram)
        return tot / (N_COMPUTE * (N_TOTAL - N_COMPUTE))

    if topo == "fattree":                   # k=4, n=3 -> 64 leaves
        k, n = 4, 3

        def hops(a, b):
            """Up to the nearest common ancestor and back down."""
            for level in range(1, n + 1):
                if a // (k ** level) == b // (k ** level):
                    return 2 * level
            return 2 * n                    # different roots: full height

        tot = sum(hops(s, d) for s in compute for d in dram)
        return tot / (N_COMPUTE * (N_TOTAL - N_COMPUTE))

    if topo == "fly":
        return 1.0                          # single central crossbar
    raise ValueError(topo)


# --- wire energy --------------------------------------------------------------
# Routers are only half the story. Every hop also drives a physical link, and a
# NoC's wires burn real power. Omitting them (as the first version of this file
# did) flatters whichever topology has the LONGEST links.
#
# E_wire = length_mm * bits * WIRE_PJ_PER_MM_PER_BIT
#
# 0.1 pJ/mm/bit at 45nm/1.0V: C_wire ~ 0.2 pF/mm, E = 0.5*C*V^2 at 50% activity.
# It is UNCALIBRATED -- FlooNoC's 0.15 pJ/B/hop is explicitly "the routers only
# consume 596 pJ" (Sec. VI-D), so it anchors the router and says NOTHING about
# links. Published repeated-RC on-chip wires span 0.08-0.4 pJ/bit/mm, so 0.1 is
# at the optimistic end of the range rather than above it.
#
# AND IT DOES NOT MATTER. Sweep it from 0.0 to 0.4 and the fat-tree's energy
# ratio moves 1.67x -> 1.65x; EDP is 0.92-0.93x (prefill) and 1.24-1.26x (decode)
# throughout. The reason is arithmetic, not luck: the fat-tree's ROUTER energy is
# 1.67x the mesh's and its WIRE energy is 1.64x. Two nearly equal ratios, so ANY
# blend of them lands in the same place. `_selfcheck` pins this invariance.
#
# This kills the earlier claim (PITFALLS 11) that adding wires flipped the
# verdict. It did not. What flipped it was a WRONG PATH LENGTH -- the fat-tree
# was hand-waved at 105.5 mm when its measured path is 41.4 mm on the very same
# grid. Wires were the scapegoat; the bug was the ruler.
WIRE_PJ_PER_MM_PER_BIT = 0.1

# Path lengths now come from floorplan.py, which places the nodes where they
# actually are. The version of this file that reviewers would have seen invented
# its own floorplan -- "64 tiles on an 8x8 grid at a 3.767 mm pitch" -- and that
# was wrong: nodes 32-63 are DRAM CHANNELS, i.e. an HBM PHY strip on the die
# edge, not 32 compute-sized tiles. Pricing them as tiles gave the DRAM region
# half the die, doubled the die in y, and stretched every path. It cut the
# fat-tree's path 105.5 -> 42.7 mm when fixed, so it was not a rounding error.
from floorplan import path_mm, die_side_mm      # noqa: E402


def router_pj(topo):
    """One hop of ROUTER energy = buffer write + crossbar + buffer read."""
    r = int(round(RADIX[topo]))
    return crossbar_pj(r, FLIT_BITS) + 2 * reg_pj(FLIT_BITS)


def wire_pj(topo, W=None):
    """Energy to drive the flit down every link on its measured physical path."""
    return path_mm(topo, W) * FLIT_BITS * WIRE_PJ_PER_MM_PER_BIT


def per_hop_pj(topo):
    """Kept for the selfcheck: router energy of a single hop."""
    return router_pj(topo)


def evaluate(W=None):
    rows = {}
    for t in CYCLES:
        h = avg_hops(t)
        rp = router_pj(t) * h                 # router energy, all hops
        wp = wire_pj(t, W)                    # wire energy, measured path
        rows[t] = {"radix": RADIX[t], "avg_hops": round(h, 2),
                   "path_mm": round(path_mm(t, W), 1),
                   "router_pJ": round(rp, 1), "wire_pJ": round(wp, 1),
                   "total_pJ": round(rp + wp, 1),
                   "wire_share_pct": round(100 * wp / (rp + wp), 1)}
    base = rows["mesh"]
    for t, r in rows.items():
        r["energy_vs_mesh"] = round(r["total_pJ"] / base["total_pJ"], 2)
        r["speedup_vs_mesh"] = round(CYCLES["mesh"] / CYCLES[t], 2)
        r["area_vs_mesh"] = round(SILICON_UM2[t] / SILICON_UM2["mesh"], 2)
        r["edp_vs_mesh"] = round(r["energy_vs_mesh"] / r["speedup_vs_mesh"], 2)
        r["decode_speedup"] = round(DECODE["mesh"] / DECODE[t], 2)
        r["decode_edp"] = round(r["energy_vs_mesh"] / r["decode_speedup"], 2)
    return rows


def main():
    rows = evaluate()

    print(f"\n  NoC energy per delivered flit ({FLIT_BITS}-bit flits), ROUTERS + WIRES")
    print(f"  traffic volume is identical across runs, so it cancels\n")
    print(f"  {'topology':<9} {'radix':>6} {'hops':>6} {'path mm':>8} {'router pJ':>10} "
          f"{'wire pJ':>9} {'wire%':>6} {'total':>9} {'energy':>7} {'speed':>7} {'EDP':>7}")
    for t in ("mesh", "fattree", "fly"):
        r = rows[t]
        print(f"  {t:<9} {r['radix']:>6.1f} {r['avg_hops']:>6.2f} {r['path_mm']:>8.1f} "
              f"{r['router_pJ']:>10.1f} {r['wire_pJ']:>9.1f} {r['wire_share_pct']:>5.1f}% "
              f"{r['total_pJ']:>9.1f} {r['energy_vs_mesh']:>6.2f}x "
              f"{r['speedup_vs_mesh']:>6.2f}x {r['edp_vs_mesh']:>6.2f}x")
    print(f"\n  (energy/speed/EDP RELATIVE TO MESH; lower energy and EDP are better)")

    ft = rows["fattree"]
    print(f"\n  WIRES DOMINATE: {rows['mesh']['wire_share_pct']}% of the mesh's NoC energy,"
          f" {ft['wire_share_pct']}% of the fat-tree's.")
    print(f"  A router-only model (what most papers publish, and what this script did")
    print(f"  before) hides that, and flatters whichever topology has the longest links.")

    print(f"\n  EDP vs mesh, both regimes (energy / speedup; < 1.00 beats the mesh):\n")
    print(f"    {'topology':<9} {'energy':>7} {'prefill':>8} {'EDP':>7}   {'decode':>7} {'EDP':>7}")
    for t in ("mesh", "fattree", "fly"):
        r = rows[t]
        print(f"    {t:<9} {r['energy_vs_mesh']:>6.2f}x {r['speedup_vs_mesh']:>7.2f}x "
              f"{r['edp_vs_mesh']:>6.2f}x   {r['decode_speedup']:>6.2f}x {r['decode_edp']:>6.2f}x")

    # The die-size sweep is WORTHLESS: every length scales linearly with the die,
    # so all ratios are scale-invariant and the sweep is flat by construction. It
    # was flat in the old model too -- at the wrong constant. It never tested
    # anything. The floorplan's SHAPE is the free variable, and the one constant
    # that actually moves the verdict is how deep the HBM PHY strip is: give the
    # 32 memory channels tile-sized cells and the fat-tree's path explodes.
    print(f"\n  Sensitivity — the real free variable is the HBM PHY strip depth:\n")
    print(f"    {'PHY depth':>10} {'ft path mm':>11} {'ft energy':>10} {'prefill EDP':>12} {'decode EDP':>11}  winner")
    import floorplan
    keep = floorplan.PHY_DEPTH_MM
    for d in (0.5, 2.0, 5.0, 10.0, 30.1):
        floorplan.PHY_DEPTH_MM = d
        f = evaluate()["fattree"]
        win = "fattree" if f["edp_vs_mesh"] < 1 else "mesh"
        note = "  <- old model (DRAM as tiles)" if d == 30.1 else ""
        print(f"    {d:>9.1f}mm {f['path_mm']:>11.1f} {f['energy_vs_mesh']:>9.2f}x "
              f"{f['edp_vs_mesh']:>11.2f}x {f['decode_edp']:>10.2f}x  {win}{note}")
    floorplan.PHY_DEPTH_MM = keep

    ft, m = rows["fattree"], rows["mesh"]
    print(f"\n  FAT-TREE VERDICT — it SPLITS by regime")
    print(f"    performance : {ft['speedup_vs_mesh']}x prefill, {ft['decode_speedup']}x decode")
    print(f"    silicon area: {ft['area_vs_mesh']}x")
    print(f"    NoC energy  : {ft['energy_vs_mesh']}x   (loses — {ft['path_mm'] / m['path_mm']:.2f}x farther to travel)")
    print(f"    prefill EDP : {ft['edp_vs_mesh']}x   ({'BEATS' if ft['edp_vs_mesh'] < 1 else 'loses to'} the mesh)")
    print(f"    decode EDP  : {ft['decode_edp']}x   ({'BEATS' if ft['decode_edp'] < 1 else 'loses to'} the mesh)")
    print(f"\n  Hops are still not distance: the fat-tree takes FEWER hops"
          f" ({ft['avg_hops']} vs {m['avg_hops']})")
    print(f"  but travels {ft['path_mm'] / m['path_mm']:.2f}x farther"
          f" ({ft['path_mm']:.0f} mm vs {m['path_mm']:.0f} mm). Dimension-order routing on a mesh")
    print(f"  traverses exactly the Manhattan distance, so the mesh is WIRE-OPTIMAL by")
    print(f"  construction — no topology can beat it on distance, only on hops and radix.")
    print(f"  The open question is whether the extra distance BUYS enough speed. In")
    print(f"  prefill it does ({ft['speedup_vs_mesh']}x > {ft['energy_vs_mesh']}x); in decode the")
    print(f"  speedup collapses to {ft['decode_speedup']}x (the VPU saturates) and it does not.")

    fly = rows["fly"]
    print(f"\n  The crossbar (`fly`) is an energy catastrophe: {fly['energy_vs_mesh']}x the mesh,")
    print(f"  EDP {fly['edp_vs_mesh']}x / {fly['decode_edp']}x. A radix-64 crossbar burns"
          f" {fly['router_pJ']:,.0f} pJ of")
    print(f"  router energy per flit — it was never a real option.")


def _selfcheck():
    # Hop counts are THE load-bearing assumption -- EDP came out near 1.0, so a
    # small hop error flips the verdict. Pin them against hand-derived values.
    #
    # mesh: mean |dx| over two uniform 0..7 coords = (k^2-1)/(3k) = 2.625, and
    # mean |dy| from rows{0..3} to rows{4..7} = 4.0  ->  6.625
    assert abs(avg_hops("mesh") - 6.625) < 1e-9, avg_hops("mesh")
    # fattree: compute (leaves 0-31) and DRAM (leaves 32-63) sit in DIFFERENT
    # level-2 subtrees, so EVERY compute<->DRAM packet must climb to the root.
    # Hence exactly 2*n = 6 hops, always -- no averaging.
    assert abs(avg_hops("fattree") - 6.0) < 1e-9, avg_hops("fattree")
    assert avg_hops("fly") == 1.0
    # the fat-tree is now SHORTER than the mesh under the real (bipartite)
    # traffic -- the reverse of what the uniform-traffic assumption implied.
    assert avg_hops("fattree") < avg_hops("mesh"), "fattree should be shorter here"
    # HOP LENGTH must match real silicon. FlooNoC's compute tile is 1.5 x 0.75 mm
    # in 12nm (their Fig. 6 floorplan), so a hop is ~1.12 mm; scaled to our 45nm
    # that is ~4.2 mm. Ours is 3.92 mm -- 0.93x. If this drifts far, the die is
    # wrong and every wire number with it.
    import floorplan
    ours = floorplan.path_mm("mesh") / avg_hops("mesh")
    floo_45 = ((1.5 + 0.75) / 2) * (45 / 12)
    assert 0.5 <= ours / floo_45 <= 2.0, f"hop length {ours:.2f}mm is {ours / floo_45:.1f}x FlooNoC's"

    # crossbar energy must be superlinear in radix, or the O(radix^2) argument fails.
    # Needs the Accelergy CSVs, so only assert it where they exist.
    from floonoc_calibrate import CROSSBAR_CSV, crossbar_pj
    if not CROSSBAR_CSV.exists():
        print("selfcheck OK (energy asserts skipped — run in the tools image)")
        return
    e5, e10 = crossbar_pj(5, 32), crossbar_pj(10, 32)
    assert e10 / e5 > 3.5, f"crossbar energy not quadratic in radix: {e10 / e5:.1f}x"

    # THE INVARIANCE. The wire constant is uncalibrated (FlooNoC's 0.15 pJ/B/hop is
    # routers only), so the verdict must not depend on it. Across the full published
    # range -- and even at ZERO wire energy -- the fat-tree's EDP must stay put.
    # If this ever fails, the wire constant has become load-bearing and must be
    # calibrated before anything is published.
    global WIRE_PJ_PER_MM_PER_BIT
    keep = WIRE_PJ_PER_MM_PER_BIT
    edps = []
    for w in (0.0, 0.05, 0.1, 0.2, 0.4):
        WIRE_PJ_PER_MM_PER_BIT = w
        edps.append(evaluate()["fattree"]["edp_vs_mesh"])
    WIRE_PJ_PER_MM_PER_BIT = keep
    assert max(edps) - min(edps) < 0.05, f"verdict now DEPENDS on the wire constant: {edps}"
    assert all(e < 1.0 for e in edps), f"fattree should win prefill at every wire cost: {edps}"
    print(f"selfcheck OK (fattree prefill EDP {min(edps):.2f}-{max(edps):.2f}x "
          f"across wire 0.0-0.4 pJ/mm/bit — invariant)")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--selfcheck":
        _selfcheck()
    else:
        main()
