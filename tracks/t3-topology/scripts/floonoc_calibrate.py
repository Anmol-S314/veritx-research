#!/usr/bin/env python3
"""Calibrate this track's router model against FlooNoC's SILICON numbers.

Everything downstream (pytorchsim_area.py, wire_area.py) rests on a router built
as "crossbar + one input buffer per port". Nobody checked that against a real
chip. If it is off by 10x, every topology conclusion in this track is decoration.

FlooNoC (Fischer/Benini et al., IEEE TVLSI 2025; arXiv 2409.17606) is the anchor:
open RTL, taped out in GF 12nm FinFET, 8x4 mesh, 288 RISC-V cores. It publishes
0.15 pJ/B/hop at 0.8 V for the routers, with 512-bit physical links.

WHY THE ENERGY IS COMPUTED FROM THE CSVs AND NOT FROM ACCELERGY'S ERT:
  Accelergy in this image emits an EMPTY ERT (tables: []) for primitive-only
  architectures -- with or without action counts, at schema 0.3 or 0.4. Its ART
  (area) works fine. Rather than fight it, we apply Accelergy's OWN energy
  formula, read straight out of accelergy-aladdin-plug-in/aladdin_table.py:

      crossbar_energy = csv_energy * n_inputs * (n_outputs/4) * (width/32)
      reg_energy      = csv_energy * width

  This is not a guess. The IDENTICAL formula shape is used for area
  (crossbar_estimate_area, same file), and it reproduces Accelergy's own ART
  answer exactly: 569.5 * 5 * (5/4) * (512/32) = 56,950 um^2, which is what
  Accelergy returns for a 5x5x512 crossbar. `--verify-area` asserts that. If the
  area formula is right, the energy formula off the same CSV row is right.

SCALING (first-order, stated so it can be attacked):
  E ~ C*V^2;  C ~ feature size (12/45);  V^2: (0.8/1.0)^2.  -> 0.171x
  This is not a foundry model. Within 2x of 0.15 pJ/B/hop means the router model
  is sane. A 10x miss means it is not, and nothing downstream survives.

KNOWN WEAKNESS: the input buffer is priced as an Aladdin flip-flop regfile. A
real NoC buffer is an SRAM FIFO and CACTI would model it better -- but CACTI
energy is only reachable through the ERT, which is broken here. The buffer is
~12% of per-hop energy, so this is a second-order error, not a load-bearing one.

    python3 scripts/floonoc_calibrate.py [--verify-area]
"""
import argparse
import csv
import sys
from pathlib import Path

# Aladdin CSV rows at 1 ns latency (the row Accelergy picks for a 1 GHz design).
PLUGIN = Path("/usr/local/share/accelergy/estimation_plug_ins/accelergy-aladdin-plug-in")
CROSSBAR_CSV = PLUGIN / "data" / "crossbar.csv"
REG_CSV = PLUGIN / "data" / "reg.csv"

# --- FlooNoC's published silicon ---------------------------------------------
FLOONOC_PJ_PER_B_PER_HOP = 0.15
FLOONOC_VOLTS = 0.8
FLOONOC_NM = 12
FLOONOC_LINK_BITS = 512      # wide physical links are FlooNoC's whole thesis
FLOONOC_RADIX = 5            # 2D mesh router: N/E/S/W + local

OUR_NM = 45
OUR_NOMINAL_VOLTS = 1.0
SCALE = (FLOONOC_NM / OUR_NM) * (FLOONOC_VOLTS / OUR_NOMINAL_VOLTS) ** 2


def csv_row(path, latency_ns=1):
    """The row Accelergy would pick: first row whose latency >= the target."""
    with open(path) as f:
        for row in csv.DictReader(f):
            if float(row["latency(ns)"]) >= latency_ns:
                return row
    raise SystemExit(f"✗ no usable row in {path}")


def crossbar_pj(radix, width):
    """Accelergy: csv_energy * n_inputs * (n_outputs/4) * (width/32)."""
    e = float(csv_row(CROSSBAR_CSV)["dynamic energy(pJ)"])
    return e * radix * (radix / 4) * (width / 32)


def crossbar_um2(radix, width):
    """Same formula, area column -- used to prove the formula is Accelergy's."""
    a = float(csv_row(CROSSBAR_CSV)["area(um^2)"])
    return a * radix * (radix / 4) * (width / 32)


def reg_pj(width):
    """Accelergy: csv_energy * width. One access = one flit in or out."""
    e = float(csv_row(REG_CSV)["dynamic energy(pJ)"])
    return e * width


def pj_per_byte_per_hop(radix, link_bits):
    """One hop = buffer write + buffer read + crossbar traversal."""
    xbar = crossbar_pj(radix, link_bits)
    wr = reg_pj(link_bits)
    rd = reg_pj(link_bits)
    per_flit_45 = xbar + wr + rd
    per_flit_12 = per_flit_45 * SCALE
    return per_flit_12 / (link_bits / 8), {
        "crossbar_pJ": xbar, "buf_write_pJ": wr, "buf_read_pJ": rd,
        "per_flit_45nm_pJ": per_flit_45, "per_flit_12nm_pJ": per_flit_12}


def _selfcheck():
    """Pin the formulas. Needs the Accelergy CSVs, so it only runs in the image."""
    if not CROSSBAR_CSV.exists():
        print("selfcheck SKIPPED (run inside the tools image — needs Accelergy CSVs)")
        return
    # THE load-bearing check: our formula must reproduce Accelergy's own ART answer.
    # If this drifts, the energy numbers are no longer Accelergy's and the
    # calibration means nothing.
    got = crossbar_um2(FLOONOC_RADIX, FLOONOC_LINK_BITS)
    assert abs(got - 56950.0) < 1.0, f"formula gives {got}, Accelergy's ART said 56950"
    # crossbar is quadratic in radix, linear in width -- the whole thesis of the
    # width-vs-topology argument rests on this asymmetry.
    assert abs(crossbar_pj(10, 32) / crossbar_pj(5, 32) - 4.0) < 1e-6, "not quadratic in radix"
    assert abs(crossbar_pj(5, 64) / crossbar_pj(5, 32) - 2.0) < 1e-6, "not linear in width"
    # and the calibration itself must still pass, or nothing downstream is supported
    got, _ = pj_per_byte_per_hop(FLOONOC_RADIX, FLOONOC_LINK_BITS)
    ratio = got / FLOONOC_PJ_PER_B_PER_HOP
    assert 0.5 <= ratio <= 2.0, f"calibration REGRESSED to {ratio:.2f}x FlooNoC silicon"
    print(f"selfcheck OK (calibration {ratio:.2f}x FlooNoC)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-area", action="store_true",
                    help="assert our formula reproduces Accelergy's own ART answer")
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()
    if args.selfcheck:
        return _selfcheck()

    if args.verify_area:
        got = crossbar_um2(FLOONOC_RADIX, FLOONOC_LINK_BITS)
        assert abs(got - 56950.0) < 1.0, f"formula gives {got}, Accelergy said 56950"
        print(f"  ✓ formula reproduces Accelergy's ART exactly: {got:,.0f} um^2")

    print(f"\n  Calibrating against FlooNoC (12nm silicon, IEEE TVLSI 2025)")
    print(f"  target : {FLOONOC_PJ_PER_B_PER_HOP} pJ/B/hop @ {FLOONOC_VOLTS} V, "
          f"{FLOONOC_LINK_BITS}-bit links, radix-{FLOONOC_RADIX} mesh router")
    print(f"  scale  : {OUR_NM}nm/{OUR_NOMINAL_VOLTS}V -> {FLOONOC_NM}nm/{FLOONOC_VOLTS}V "
          f"= {SCALE:.3f}x  (E~CV^2)\n")

    got, p = pj_per_byte_per_hop(FLOONOC_RADIX, FLOONOC_LINK_BITS)
    ratio = got / FLOONOC_PJ_PER_B_PER_HOP

    print(f"  per-flit @45nm : {p['per_flit_45nm_pJ']:>7.2f} pJ  "
          f"(crossbar {p['crossbar_pJ']:.1f} + buf wr {p['buf_write_pJ']:.1f} "
          f"+ buf rd {p['buf_read_pJ']:.1f})")
    print(f"  per-flit @12nm : {p['per_flit_12nm_pJ']:>7.2f} pJ  "
          f"({FLOONOC_LINK_BITS // 8} bytes/flit)")
    print(f"\n  OUR MODEL : {got:.3f} pJ/B/hop")
    print(f"  FLOONOC   : {FLOONOC_PJ_PER_B_PER_HOP:.3f} pJ/B/hop  (measured silicon)")
    print(f"  RATIO     : {ratio:.2f}x\n")

    if 0.5 <= ratio <= 2.0:
        print(f"  ✓ PASS — within 2x of silicon. The router model is calibrated, so")
        print(f"    the topology comparisons rest on something real.")
    else:
        print(f"  ✗ FAIL — off by {ratio:.1f}x. Do NOT publish the sweep numbers")
        print(f"    until this is fixed; the router model does not describe a chip.")

    print(f"\n  crossbar is {100 * p['crossbar_pJ'] / p['per_flit_45nm_pJ']:.0f}% of "
          f"per-hop energy — which is why radix (i.e. TOPOLOGY) drives it.")

    print(f"\n  sanity: energy must grow with radix, and it must be the crossbar term")
    print(f"    {'radix':>6} {'pJ/B/hop':>10} {'vs FlooNoC':>11}")
    for r in (3, 5, 7, 10):
        v, _ = pj_per_byte_per_hop(r, FLOONOC_LINK_BITS)
        print(f"    {r:>6} {v:>10.3f} {v / FLOONOC_PJ_PER_B_PER_HOP:>10.2f}x")


if __name__ == "__main__":
    main()
