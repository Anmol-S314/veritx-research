#!/usr/bin/env python3
"""Real die area for the T3 accelerator, from Accelergy (T3 — Wk13 Pareto).

Why this is a separate step and not part of Timeloop:

  Timeloop *can* replace its internal area model with an Accelergy ART, but the
  pinned Timeloop (2022) hard-asserts on ERT `version: 0.3` and Accelergy 0.4
  emits `0.4` (and an empty ERT for this arch). Unpinning Timeloop drags in the
  barvinok/isl/NTL stack the Dockerfile deliberately avoids. So Timeloop keeps
  doing energy with its built-in PAT model, and Accelergy is queried directly
  for area -- which is strictly better anyway, because Timeloop's area model has
  no notion of the NoC, and the ROUTERS dominate the die.

Every number here comes from a real estimator. `dummy_tables` is removed from the
image on purpose: a component nobody can price makes Accelergy exit non-zero
rather than quietly inventing 1 pJ / 1 um^2.

  python3 scripts/area_report.py -n 16 -o results/area_16.json
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

TRACK = Path(__file__).parent.parent

# Each backend supports only certain nodes, and they do not overlap:
#   Aladdin (regfile, intmac)   -> 40/45nm only
#   Library (isaac_router)      -> 32nm only
#   CACTI  (SRAM/DRAM)          -> 22-180nm, interpolated
# So a single consistent node is impossible with the shipped backends. Rather
# than silently mix them, every component carries the node it was priced at.
TECH = {"regfile": 45, "intmac": 45, "SRAM": 45, "isaac_router": 32}


def accelergy_arch(nodes, rf_entries, gb_kb, word_bits):
    """One entry per component *type*; instance counts are applied afterwards."""
    gb_width = 64  # bits per row; CACTI needs width >= 32
    gb_depth = max(64, (gb_kb * 1024 * 8) // gb_width)
    return {
        "architecture": {
            "version": 0.3,
            "subtree": [{
                "name": "system",
                "local": [
                    {"name": "RegisterFile", "class": "regfile",
                     "attributes": {"technology": TECH["regfile"],
                                    "width": word_bits, "depth": rf_entries}},
                    {"name": "GlobalBuffer", "class": "SRAM",
                     "attributes": {"technology": TECH["SRAM"],
                                    "width": gb_width, "depth": gb_depth}},
                    {"name": "MAC", "class": "intmac",
                     "attributes": {"technology": TECH["intmac"], "width": word_bits}},
                    # The NoC itself. Booksim tells us how the routers perform;
                    # this is what they cost. Fixed-size model -- it does not vary
                    # with radix, so mesh/torus/fattree price the same here.
                    {"name": "Router", "class": "isaac_router",
                     "attributes": {"technology": TECH["isaac_router"],
                                    "width": 256, "datawidth": 256,
                                    "global_cycle_seconds": 1e-9}},
                ],
            }],
        }
    }


def run_accelergy(arch: dict):
    """-> {component: area_um2_per_instance}. Raises if a component can't be priced."""
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "arch.yaml").write_text(yaml.safe_dump(arch, sort_keys=False))
        proc = subprocess.run(["accelergy", "arch.yaml", "-o", ".", "--oprefix", ""],
                              cwd=d, capture_output=True, text=True, timeout=600)
        art = d / "ART.yaml"
        if not art.exists():
            err = [l for l in (proc.stdout + proc.stderr).splitlines()
                   if re.search(r"ERROR|Can not find", l)]
            raise SystemExit("✗ Accelergy could not price the architecture:\n  "
                             + "\n  ".join(err[:4] or ["(see accelergy output)"]))
        tables = yaml.safe_load(art.read_text())["ART"]["tables"]
        return {t["name"].split(".")[-1]: float(t["area"]) for t in tables}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-n", "--nodes", type=int,
                    help="NoC node count == PE count == router count")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()
    if args.selfcheck:
        return _selfcheck()
    if not args.nodes:
        ap.error("-n/--nodes is required")

    arch = yaml.safe_load((TRACK / "timeloop" / "arch.yaml").read_text())["arch"]
    word_bits = arch["arithmetic"].get("word-bits", 8)
    store = {l["name"]: l for l in arch["storage"]}
    rf_entries = store["RegisterFile"]["entries"]
    gb_kb = store["GlobalBuffer"]["sizeKB"]

    per_inst = run_accelergy(accelergy_arch(args.nodes, rf_entries, gb_kb, word_bits))

    # instance counts: per-PE things scale with the mesh; the buffer is shared.
    counts = {"RegisterFile": args.nodes, "MAC": args.nodes,
              "Router": args.nodes, "GlobalBuffer": 1}
    comps = {}
    for name, count in counts.items():
        if name not in per_inst:
            continue
        comps[name] = {
            "instances": count,
            "area_um2_each": round(per_inst[name], 2),
            "area_um2_total": round(per_inst[name] * count, 2),
            "technology_nm": TECH[{"RegisterFile": "regfile", "MAC": "intmac",
                                   "GlobalBuffer": "SRAM", "Router": "isaac_router"}[name]],
        }
    total = sum(c["area_um2_total"] for c in comps.values())
    out = {
        "nodes": args.nodes,
        "rf_entries": rf_entries,
        "global_buffer_kB": gb_kb,
        "total_area_um2": round(total, 2),
        "total_area_mm2": round(total / 1e6, 4),
        "components": comps,
    }

    dest = Path(args.out or TRACK / "results" / f"area_{args.nodes}.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2))

    print(f"  {args.nodes}-node die area — {out['total_area_mm2']} mm^2 "
          f"({out['total_area_um2']:,.0f} um^2)")
    for name, c in sorted(comps.items(), key=lambda kv: -kv[1]["area_um2_total"]):
        pct = c["area_um2_total"] / total * 100 if total else 0
        bar = "#" * int(round(pct / 3))
        print(f"    {name:<13} x{c['instances']:<4} {c['area_um2_total']:>12,.0f} um^2 "
              f"{pct:5.1f}%  {bar}")
    print(f"  -> {dest}")


def _selfcheck():
    a = accelergy_arch(nodes=16, rf_entries=64, gb_kb=32, word_bits=8)
    local = {c["name"]: c for c in a["architecture"]["subtree"][0]["local"]}
    assert set(local) == {"RegisterFile", "GlobalBuffer", "MAC", "Router"}, local
    # 32kB at 64b rows = 4096 rows; CACTI needs width>=32, depth>=64
    assert local["GlobalBuffer"]["attributes"]["depth"] == 4096
    assert local["GlobalBuffer"]["attributes"]["width"] >= 32
    # a tiny buffer must still clear CACTI's depth floor rather than be refused
    small = accelergy_arch(16, 64, 1, 8)["architecture"]["subtree"][0]["local"]
    assert {c["name"]: c for c in small}["GlobalBuffer"]["attributes"]["depth"] >= 64
    # technology is an int: accelergy evals attribute values, so bare "45nm" is a
    # SyntaxError (invalid decimal literal), not a string
    assert all(isinstance(c["attributes"]["technology"], int) for c in local.values())
    print("selfcheck OK")


if __name__ == "__main__":
    main()
