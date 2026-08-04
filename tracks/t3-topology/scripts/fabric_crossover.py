#!/usr/bin/env python3
"""The fabric crossover — what replaces Ethernet, and when (T3)

fabric_sweep.py's verdict: sharded KV at the 5.4x headline point needs ~2.5 TB/s of
die-to-die delivery, and a 4x4 mesh of 100GbE has ~50 GB/s bisection = ~49x short.
This file asks the follow-up: WHAT IF the fabric is not Ethernet? Three levers, with
the physics straight:

  L1 PROTOCOL (Ethernet -> UEC / UALink / InfiniBand / CXL / optical). Every packet
     fabric rides the SAME die-edge SERDES budget, so protocol alone buys nothing
     but the per-port rate multiplier (12.5 -> 100 -> 200 -> 400 GB/s/direction).
  L2 DIE I/O (ports per die). The real constraint: pins, SERDES area, power. Today's
     Wormhole n300d ships 4x 100GbE per die; a next-gen (Blackhole-class) die can
     put more links on the edge.
  L3 TOPOLOGY (mesh vs torus vs fat-tree at 16 dies). Moves BISECTION at constant
     total egress: L = {4 mesh, 8 torus, 8 fat-tree}. And fabric_sweep Q1 measured
     that dim_order on a torus SKIPS the middle dies, breaking switch-replicated
     multicast coverage -> the fat tree is the only L=8 topology that works with the
     multicast primitive. This is the one genuinely new name this file contributes.

Crossover, computed and selfchecked: bisection B = L x port_rate must reach the
remote-KV demand D ~= 2460 GB/s at the headline operating point:

  - L=4 mesh: needs r >= 615 GB/s (5 Tb/s-class ports) -- on NO roadmap, ever.
  - L=8 (fat-tree): needs r >= 307.5 GB/s = 2.5 Tb/s-class ports. Only
    co-packaged-optics 3.2T (2027+) clears that at Wormhole-class I/O; OR 1.6T-class
    ports (UEC / UALink 2.0, 2026) clear it on a die with 2x the links (degree-8 I/O:
    L=16, just twice the wires -- no topology magic, the die-I/O lever).
  - The per-die egress view closes MUCH earlier (per-die remote demand is only
    ~154 GB/s): 4x 800GbE ports already have 2.6x headroom. Egress is not the wall.

VERDICT: the sharded-KV fabric is a ~2027 problem, and Ethernet's OWN successors
solve it -- UEC 1.6/3.2T, or the same SERDES repackaged as UALink/co-packaged optics
-- on a FAT-TREE-CLASS die array, which is the one L=8 topology that does not break
switch-replicated multicast. That is fabric_sweep's "~10x today's fabric" with the
topology now named and the I/O lever quantified.

CXL is NOT in this race: memory semantics change the question (coherence pulls lines
locally instead of multicast packets -- a different product design), so it gets an
informational row, not a verdict. NVLink-class I/O (1.8 TB/s per die) closes everything
but is proprietary to NVIDIA silicon.

HONEST SOFT SPOTS: UEC/UALink/CXL4.0/3.2T-optical rates are roadmap (2026-27), not
shipped; "degree-8" is a die-I/O assumption, not a named part; CXL's coherence story
is one paragraph here, not a model; the fat-tree's ENERGY cost at this layer is
computed below (SERDES hops only -- the FINDINGS.md 1.65x is the ON-DIE layer and
does not transfer to fixed-length chip-to-chip links).

RUN: python3 scripts/fabric_crossover.py --selfcheck
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # sibling-script imports
import fabric_sweep as fs           # headline operating point, demand, bisection model
import serving_multicast as sm      # QUITEX constants (cap, bw)

# ---- demand, pinned to the headline point (single source of truth: fabric_sweep) --
D = fs.remote_kv_gbps()                    # ~2460 GB/s, KV sharded across 16 dies
PER_DIE = D / fs.N_DIES                    # ~154 GB/s per die (uniform sharding)

# ---- the supply side: per-direction GB/s per port, grouped by lever and era -------
# (port_rate, name, era, semantics)
TECH = [
    (12.5, "100GbE (today)",           "2023", "packet"),
    (50.0, "400GbE",                   "2024", "packet"),
    (100.0, "800GbE / IB-XDR",         "2025", "packet"),
    (128.0, "CXL 3.1 (PCIe6 x16)",     "2025", "memory"),
    (200.0, "UEC 1.6T / UALink 2.0",   "2026", "packet"),
    (256.0, "CXL 4.0 (PCIe7 x16)",     "2027", "memory"),
    (400.0, "Co-packaged optics 3.2T", "2027", "packet"),
]

# ---- topology levers at 16 dies ---------------------------------------------------
# L = bisection links (each 1 port per direction at rate r): mesh 4, torus/FFT 8.
# degree-8 I/O doubles parallel links -> L=16 on the same array shape (2x the wires).
TOPOS = {"mesh 4x4": 4, "torus/FFT 4x4": 8, "degree-8 array": 16}

PORTS_PER_DIE = (4, 8)                   # Wormhole-class vs next-gen die I/O

# ---- energy at the fabric layer: does the fat-tree penalty transfer? -------------
# FINDINGS.md's 1.65x is the ON-DIE NoC layer (router pJ/B/hop + on-die wire pJ/mm;
# the fat-tree travels 42.7 mm vs the mesh's 26.0 mm at radix 6.7 vs 5.0).
# Die-to-die is a different physics: SERDES per-bit energy is FIXED per link, links
# are fixed-length, so a topology costs only HOPS. Ranged: 4 pJ/bit (100GbE-class
# copper SERDES) to 10 pJ/bit (optical transceiver incl. laser).
SERDES_PJ_BIT = (4.0, 10.0)
# hops = exact average Manhattan distance over ordered pairs (excluding self):
# 4x4 mesh 2.67 (8/3: marginal E=4/3 per dim, incl. same-axis pairs), torus 2.0,
# fat-tree 16 leaves = 4
HOPS = {"mesh 4x4": 8 / 3, "torus 4x4": 2.0, "fat-tree 16 (L=8)": 4.0}
BOX_W = 3000.0                            # 8x n300d-class cards + host, order-of-magnitude


def fabric_power_w(hops, pj_bit):
    """Watts of fabric energy at the headline traffic (D GB/s) for the given hops."""
    return D * 1e9 * 8 * pj_bit * 1e-12 * hops   # B/s * bits * J/bit * hops


def bisection_gbps(topology_links, port_rate):
    return topology_links * port_rate


def per_die_egress_gbps(ports, port_rate):
    return ports * port_rate


def crossover_port_rate(topology_links):
    """GB/s per port (per direction) at which the bisection view closes."""
    return D / topology_links


def _selfcheck():
    # demand must match fabric_sweep's pinned operating point
    assert abs(D - 2460) < 100, D
    assert abs(PER_DIE - 154) < 10, PER_DIE
    # crossover values: mesh never on any roadmap (>= 615 GB/s/port = 4.9 Tb/s)
    mesh_need = crossover_port_rate(TOPOS["mesh 4x4"])
    assert 600 < mesh_need < 630, mesh_need
    # L=8 needs 2.5 Tb/s-class ports: 3.2T closes, 1.6T stays short
    l8_need = crossover_port_rate(TOPOS["torus/FFT 4x4"])
    assert 300 < l8_need < 315, l8_need
    assert bisection_gbps(TOPOS["torus/FFT 4x4"], 200.0) < D     # 1.6T still short
    assert bisection_gbps(TOPOS["torus/FFT 4x4"], 400.0) > D     # 3.2T closes
    # degree-8 I/O (L=16) closes at 1.6T
    assert bisection_gbps(TOPOS["degree-8 array"], 200.0) > D
    # egress view closes at 4x 800GbE
    assert per_die_egress_gbps(4, 100.0) > PER_DIE
    assert per_die_egress_gbps(4, 12.5) < PER_DIE               # 4x 100GbE is short
    # energy: FFT-vs-torus hop delta must be a small share of the box (4 pJ/bit case);
    # the worst-case optical FFT absolute must stay under 30% of the box power
    delta = fabric_power_w(HOPS["fat-tree 16 (L=8)"], SERDES_PJ_BIT[0]) - \
            fabric_power_w(HOPS["torus 4x4"], SERDES_PJ_BIT[0])
    assert 150 < delta < 165, delta
    assert fabric_power_w(HOPS["fat-tree 16 (L=8)"], SERDES_PJ_BIT[1]) / BOX_W < 0.30
    print(f"selfcheck OK -- mesh needs {mesh_need:.0f} GB/s/port (no roadmap); "
          f"L=8 fat-tree needs {l8_need:.0f} (=2.5 Tb/s: 1.6T short, 3.2T closes); "
          f"degree-8 + 1.6T closes; egress closes at 4x800GbE; "
          f"fabric energy {delta:.0f} W FFT-vs-torus delta @4 pJ/bit")


def main():
    print(f"\n  Fabric crossover: what replaces Ethernet for sharded KV, and when")
    print(f"  demand (pinned): {D:.0f} GB/s remote KV at the {sm.MODELS[1].name} "
          f"{fs.SEQ//1024}K / batch-{fs.B} headline point; per-die {PER_DIE:.0f} GB/s\n")

    print(f"  {'fabric':<28}{'GB/s/port':>10}{'era':>8}{'bisection @ L=8':>18}"
          f"{'per-die egress x4':>19}")
    for r, name, era, sem in TECH:
        if sem == "memory":
            print(f"  {name:<28}{r:>10.0f}{era:>8}{'':>18}{'':>19}   (memory semantics --"
                  f" different lever, see below)")
            continue
        b = bisection_gbps(TOPOS["torus/FFT 4x4"], r)
        tag = "CLOSES" if b >= D else f"{D/b:.1f}x short"
        e = per_die_egress_gbps(4, r)
        etag = "ok" if e >= PER_DIE else f"{PER_DIE/e:.1f}x short"
        print(f"  {name:<28}{r:>10.0f}{era:>8}{f'{b:>6.0f} {tag}':>18}{f'{e:>6.0f} {etag}':>19}")

    print(f"\n  crossover by topology (bisection view, GB/s per port needed = {D:.0f}/L):")
    for tname, links in TOPOS.items():
        need = crossover_port_rate(links)
        nearest = next((f"{name} ({era})" for r, name, era, sem in TECH
                        if sem == "packet" and r >= need), "nothing on any roadmap")
        print(f"    {tname:<16} L={links:<3} needs {need:>5.0f} GB/s/port "
              f"({need*8:.0f} Gb/s) -> {nearest}")

    print(f"\n  VERDICT: sharded KV closes only on fat-tree-class L=8 + 3.2T-class ports")
    print(f"  (2027, co-packaged optics) or degree-8 I/O + 1.6T (UEC/UALink, 2026) --")
    print(f"  and the fat tree is the ONLY L=8 topology that preserves switch-replicated")
    print(f"  multicast coverage (torus dim_order skips the middle dies, measured in")
    print(f"  fabric_sweep Q1). CXL = memory semantics, a different product question;")
    print(f"  NVLink-class = proprietary. That is '~10x today's fabric' with the name.")

    print(f"\n  ENERGY at the fabric layer -- SERDES physics; a topology costs HOPS only")
    print(f"  (links are fixed-length, pJ/bit is fixed):")
    print(f"      FINDINGS.md's 1.65x is the ON-DIE layer (wire mm + radix) and does")
    print(f"      NOT transfer to chip-to-chip links")
    for hname, hops in HOPS.items():
        lo = fabric_power_w(hops, SERDES_PJ_BIT[0])
        hi = fabric_power_w(hops, SERDES_PJ_BIT[1])
        print(f"      {hname:<20} {lo:>4.0f}-{hi:>4.0f} W "
              f"({lo/BOX_W*100:.0f}-{hi/BOX_W*100:.0f}% of a ~{BOX_W/1000:.0f} kW box)")
    delta_lo = fabric_power_w(HOPS["fat-tree 16 (L=8)"], SERDES_PJ_BIT[0]) - \
               fabric_power_w(HOPS["torus 4x4"], SERDES_PJ_BIT[0])
    delta_hi = fabric_power_w(HOPS["fat-tree 16 (L=8)"], SERDES_PJ_BIT[1]) - \
               fabric_power_w(HOPS["torus 4x4"], SERDES_PJ_BIT[1])
    print(f"      fat-tree-vs-torus delta {delta_lo:.0f}-{delta_hi:.0f} W "
          f"({delta_lo/BOX_W*100:.0f}-{delta_hi/BOX_W*100:.0f}% of the box) -- the price")
    print(f"      of the only L=8 topology that works (the torus it replaces is")
    print(f"      disqualified on multicast coverage). The mesh does not compete on")
    print(f"      energy either: it cannot carry the load at all.")

    _selfcheck()


if __name__ == "__main__":
    main()
