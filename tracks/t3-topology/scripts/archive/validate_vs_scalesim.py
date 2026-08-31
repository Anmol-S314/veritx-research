#!/usr/bin/env python3
"""Validate the capacity-miss model against SCALE-Sim on the SAME layers.

SCALE-Sim and our model split a layer's working set across the hierarchy,
but under different assumptions:

  * SCALE-Sim streams each operand tile through its scratchpad (SRAM) and
    counts the DRAM fills as it runs out of capacity (compulsory + capacity
    misses under its own scratchpad sizes and tiling).
  * Our model (memory_miss_model.py) applies an analytical capacity split
    ws -> scratchpad / shared-L2 / HBM for a buyer-specified hierarchy.

This script feeds BOTH the same layer working sets (computed from the
SCALE-Sim topology CSV, in bytes) and compares the *HBM/DRAM* level per
layer. Agreement within ~2x on the DRAM level means the capacity model
captures the dominant spill correctly; systematic >2x gaps flag a modeling
assumption to revisit.

Usage:
    python3 validate_vs_scalesim.py \
        --topology SCALE-Sim/topologies/llama/llama_small.csv \
        --scalesim SCALE-Sim/outputs/scalesim_llama_small/t3_llama3b_tpuv4/DETAILED_ACCESS_REPORT.csv \
        --scratchpad-kb 16384 --l2-kb 65536
"""
import argparse, csv
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from memory_miss_model import miss_breakdown


def working_sets_from_topology(csv_path, bytes_per_elem=2):
    """Per-layer working set (bytes) from a SCALE-Sim topology CSV.

    SCALE-Sim layers are conv/GEMM: IFMAP HxWxC, FILTER FHxFWxCxN, OFMAP
    HxWxN. Working set = IFMAP + FILTER + OFMAP bytes (bf16 = 2 B/elem).
    """
    ws = []
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            h, w = int(row["IFMAP Height"]), int(row["IFMAP Width"])
            fh, fw = int(row["Filter Height"]), int(row["Filter Width"])
            c, n = int(row["Channels"]), int(row["Num Filter"])
            ws.append((h * w * c + fh * fw * c * n + h * w * n) * bytes_per_elem)
    return ws


def scalesim_dram_bytes(csv_path):
    """Per-layer DRAM read+write bytes from SCALE-Sim DETAILED_ACCESS_REPORT."""
    per_layer = {}
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            clean = {k.strip(): v for k, v in row.items()}
            per_layer[int(clean["LayerID"])] = (
                int(float(clean["DRAM IFMAP Reads"])) +
                int(float(clean["DRAM Filter Reads"])) +
                int(float(clean["DRAM OFMAP Writes"])))
    return per_layer


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--topology", required=True, help="SCALE-Sim topology CSV")
    ap.add_argument("--scalesim", required=True,
                    help="SCALE-Sim DETAILED_ACCESS_REPORT.csv")
    ap.add_argument("--scratchpad-kb", type=int, default=16384)
    ap.add_argument("--l2-kb", type=int, default=65536)
    args = ap.parse_args()

    scratchpad = args.scratchpad_kb * 1024
    l2 = args.l2_kb * 1024

    ws_list = working_sets_from_topology(args.topology)
    ss = scalesim_dram_bytes(args.scalesim)

    print(f"{len(ws_list)} layers, scratchpad {args.scratchpad_kb} KiB, "
          f"L2 {args.l2_kb} KiB")
    print(f"{'layer':>5} {'ws_B':>10} {'model_HBM':>10} {'SCALE-Sim_DRAM':>14} "
          f"{'ratio':>6}")
    model_total = ss_total = 0
    for i, ws in enumerate(ws_list):
        _, _, hbm = miss_breakdown(ws, scratchpad, l2)
        ss_bytes = ss.get(i, 0)
        ratio = (hbm / ss_bytes) if ss_bytes else float("inf")
        model_total += hbm
        ss_total += ss_bytes
        print(f"{i:>5} {ws:>10,} {hbm:>10,} {ss_bytes:>14,} {ratio:>6.2f}")

    print(f"\ntotal: model HBM {model_total:,} vs SCALE-Sim DRAM {ss_total:,} "
          f"({model_total/ss_total:.2f}x)")


if __name__ == "__main__":
    main()