#!/usr/bin/env python3
"""Timeloop -> Booksim traffic-matrix bridge (T3).

Parses a Timeloop `*.stats.txt` and emits an N x N traffic matrix in the format
Booksim's `matrix(<file>)` pattern reads (see tracks/t3-topology/booksim-ext).

Turning Timeloop's per-level access counts into a *tile-to-tile* NoC traffic
matrix is the core T3 research question (programme Wk6) — it depends on how the
workload is spatially mapped onto tiles. `build_traffic_matrix()` ships a
deliberately simple placeholder so the whole pipeline runs end to end; students
replace THAT ONE FUNCTION with their real attention/FFN spatial model.
"""
import re, sys, argparse
from pathlib import Path


def parse_levels(stats_text: str):
    """Per storage level: {name, instances, accesses}.
    accesses = sum of 'Actual scalar reads/fills/updates (per-instance)' over all
    tensors in that level (excludes algorithmic/gated/skipped/metadata lines)."""
    levels, cur, inst, acc = [], None, 1, 0
    for line in stats_text.splitlines():
        m = re.match(r'\s*=== (.+?) ===', line)
        if m:
            if cur and cur != '__ARITH__':
                levels.append({"name": cur, "instances": inst, "accesses": acc})
            cur, inst, acc = m.group(1), 1, 0
            continue
        if not cur:
            continue
        mi = re.search(r'Utilized instances \(max\)\s*:\s*(\d+)', line)
        if mi:
            inst = int(mi.group(1))
        ma = re.search(r'Actual scalar (reads|fills|updates) \(per-instance\)\s*:\s*(\d+)', line)
        if ma:
            acc += int(ma.group(2))
    if cur and cur != '__ARITH__':
        levels.append({"name": cur, "instances": inst, "accesses": acc})
    return levels


def build_traffic_matrix(levels, num_nodes):
    """PLACEHOLDER spatial model — replace this for real T3 work (Wk6).

    First-order model: the outermost level (DRAM) exchanges data with the
    compute tiles, so put star traffic between a memory-controller node (0) and
    every other tile, weighted by DRAM word accesses. This is NOT a real
    tile-to-tile model; it only exists so the pipeline runs end to end.
    """
    mat = [[0.0] * num_nodes for _ in range(num_nodes)]
    dram = next((l for l in levels if "DRAM" in l["name"].upper()), levels[-1] if levels else None)
    if not dram or num_nodes < 2:
        return mat
    per_tile = dram["accesses"] * dram["instances"] / (num_nodes - 1)
    for d in range(1, num_nodes):
        mat[0][d] = per_tile   # memory controller -> tile
        mat[d][0] = per_tile   # tile -> memory controller
    return mat


def write_matrix(mat, path):
    with open(path, "w") as f:
        f.write("# Timeloop-derived traffic matrix (row=src tile, col=dst tile)\n")
        for row in mat:
            f.write(" ".join(f"{v:g}" for v in row) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stats", help="Timeloop *.stats.txt")
    ap.add_argument("-n", "--nodes", type=int, required=True, help="NoC node count (must match the topology)")
    ap.add_argument("-o", "--out", default="traffic_matrix.txt")
    args = ap.parse_args()

    levels = parse_levels(Path(args.stats).read_text())
    write_matrix(build_traffic_matrix(levels, args.nodes), args.out)
    print(f"  parsed {len(levels)} levels; wrote {args.nodes}x{args.nodes} matrix -> {args.out}")
    for l in levels:
        print(f"    {l['name']}: {l['accesses'] * l['instances']} word accesses ({l['instances']} inst)")


def _selfcheck():
    sample = ("=== __ARITH__ ===\n  Actual scalar reads (per-instance) : 5\n"
              "=== DRAM ===\n  Utilized instances (max) : 2\n"
              "  Actual scalar reads (per-instance) : 100\n"
              "  Algorithmic scalar reads (per-instance) : 999\n"
              "  Actual scalar fills (per-instance) : 0\n"
              "  Actual scalar metadata reads (per-instance) : 7\n")
    levels = parse_levels(sample)
    assert [l["name"] for l in levels] == ["DRAM"], levels          # arith skipped
    assert levels[0]["accesses"] == 100, levels                     # algorithmic/metadata excluded
    m = build_traffic_matrix(levels, 4)
    assert len(m) == 4 and all(len(r) == 4 for r in m)
    assert m[0][1] == 200 / 3 and m[0][0] == 0, m                   # 100*2 inst / 3 tiles
    print("selfcheck OK")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--selfcheck":
        _selfcheck()
    else:
        main()
