#!/usr/bin/env python3
"""Sweep GlobalBuffer capacity against DRAM traffic (T3).

The attention projection Z(MxN) = A(MxK) . B(KxN) reads A once but re-streams B
from DRAM once per pass over the output rows. How many passes depends entirely
on whether B fits in the GlobalBuffer: at 32 kB it does not (a 768x768 INT8
weight matrix is 576 kB), so B is re-fetched and DRAM traffic is ~48x the
operand size. That is a memory-capacity result, not a topology result -- no NoC
fixes it, which is exactly why it has to be measured before the topology sweep
means anything.

This runs the mapper once per buffer size and reports the DRAM per-tensor reads.

  python3 scripts/gb_sweep.py                    # default ladder, 16 PEs
  python3 scripts/gb_sweep.py -n 64 --sizes 32 256 1024

ponytail: capacity only. Banking, ports, and multi-level buffers are separate
knobs -- add them when this curve stops explaining the traffic.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).parent
TRACK = HERE.parent
RESULTS = TRACK / "results"

sys.path.insert(0, str(HERE))
from run_timeloop import run_one  # noqa: E402
from timeloop_to_matrix import parse_levels  # noqa: E402

# 32 kB is the shipped buffer; 1024 kB comfortably holds a 768x768 INT8 weight
# tile (576 kB), so the curve should flatten before the top of the ladder. If it
# does not, the mapper is spilling for some reason other than capacity.
DEFAULT_SIZES = [32, 64, 128, 256, 512, 1024]


def dram_tensors(stats: Path) -> dict:
    """DRAM per-tensor access counts from a mapper stats file."""
    levels = parse_levels(stats.read_text())
    dram = next((l for l in levels if "DRAM" in l["name"].upper()), None)
    return dram["tensors"] if dram else {}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--nodes", type=int, default=16, help="PE count (default 16)")
    ap.add_argument("--sizes", type=int, nargs="+", default=DEFAULT_SIZES,
                    help=f"GlobalBuffer sizes in kB (default {DEFAULT_SIZES})")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()
    if args.selfcheck:
        return _selfcheck()

    if not shutil.which("timeloop-mapper"):
        sys.exit("✗ timeloop-mapper not on PATH — run inside the tools image.")

    base = yaml.safe_load((TRACK / "timeloop" / "arch.yaml").read_text())
    problem = yaml.safe_load((TRACK / "timeloop" / "problem.yaml").read_text())
    dims = problem["problem"]["instance"]
    # Operand sizes at 1 byte/word -- the floor DRAM traffic can never go below.
    word_bytes = base["arch"]["arithmetic"].get("word-bits", 8) // 8
    a_min = dims["M"] * dims["K"] * word_bytes
    b_min = dims["K"] * dims["N"] * word_bytes

    print(f"  GEMM M={dims['M']} N={dims['N']} K={dims['K']} — "
          f"A={a_min/1024:.0f} kB, B={b_min/1024:.0f} kB (compulsory DRAM reads)")

    rows = []
    for kb in args.sizes:
        arch = yaml.safe_load(yaml.safe_dump(base))  # deep copy per run
        for level in arch["arch"]["storage"]:
            if level["name"] == "GlobalBuffer":
                level["sizeKB"] = kb
        stats = run_one(args.nodes, arch, tag=f"gb{kb}")
        if not stats:
            print(f"     ⚠  {kb} kB failed — skipped")
            continue
        t = dram_tensors(stats)
        a, b = t.get("A", 0), t.get("B", 0)
        rows.append({
            "global_buffer_kB": kb,
            "dram_reads_A": a,
            "dram_reads_B": b,
            "dram_total": a + b,
            # How many times each operand crossed the DRAM boundary. 1.0 = fetched
            # once = compulsory-miss-only. Anything above that is capacity thrash.
            "A_refetch": round(a / (a_min / word_bytes), 2) if a_min else 0,
            "B_refetch": round(b / (b_min / word_bytes), 2) if b_min else 0,
        })

    if not rows:
        sys.exit("✗ every buffer size failed — see results/timeloop_gb*.log")

    dest = Path(args.out or RESULTS / "gb_sweep.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"nodes": args.nodes, "gemm": dims, "rows": rows}, indent=2))

    print(f"\n  {'GB (kB)':>8}  {'DRAM A':>10}  {'DRAM B':>12}  {'total':>12}  "
          f"{'B re-fetch':>11}")
    best = min(r["dram_total"] for r in rows)
    for r in rows:
        flag = "  <-- floor" if r["dram_total"] == best else ""
        print(f"  {r['global_buffer_kB']:>8}  {r['dram_reads_A']:>10,}  "
              f"{r['dram_reads_B']:>12,}  {r['dram_total']:>12,}  "
              f"{r['B_refetch']:>10.2f}x{flag}")
    print(f"  -> {dest}")


def _selfcheck():
    sample = ("=== DRAM ===\n    Utilized instances (max) : 1\n"
              "    A:\n        Actual scalar reads (per-instance) : 98304\n"
              "    B:\n        Actual scalar reads (per-instance) : 4718592\n")
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(sample)
    t = dram_tensors(Path(f.name))
    assert t == {"A": 98304, "B": 4718592}, t
    # the shipped 32 kB case: B (768*768 = 589,824 words) re-fetched 8x
    assert t["B"] / (768 * 768) == 8.0, t["B"] / (768 * 768)
    print("selfcheck OK")


if __name__ == "__main__":
    main()
