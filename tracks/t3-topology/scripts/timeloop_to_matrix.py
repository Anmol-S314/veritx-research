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

    Distributes DRAM accesses evenly across tiles with a nearest-neighbor
    bias: each tile talks mainly to adjacent tiles (for data reuse) and
    occasionally to the memory controller (node 0). This avoids the hotspot
    of the pure star pattern while still being clearly suboptimal — students
    should beat it with a real attention mapping.
    """
    import math
    mat = [[0.0] * num_nodes for _ in range(num_nodes)]
    dram = next((l for l in levels if "DRAM" in l["name"].upper()), levels[-1] if levels else None)
    total_access = (dram["accesses"] * dram["instances"]) if dram else 100000
    # Distribute: 60% local (nearest-neighbor ring), 40% memory-controller (node 0)
    local_per_tile = 0.6 * total_access / num_nodes
    mc_per_tile = 0.4 * total_access / num_nodes
    for s in range(num_nodes):
        mc_per_s = mc_per_tile
        # nearest neighbors: s -> (s+1), s -> (s-1), plus self-loop
        neighbors = [(s + 1) % num_nodes, (s - 1) % num_nodes, s]
        per_neighbor = local_per_tile / len(neighbors)
        for d in neighbors:
            mat[s][d] += per_neighbor
        mat[s][0] += mc_per_s  # memory controller traffic
    # Normalize so row sums are comparable to uniform injection rates (~0.05-0.4)
    max_row = max(sum(row) for row in mat)
    if max_row > 0:
        scale = 1.0 / max_row
        for s in range(num_nodes):
            for d in range(num_nodes):
                mat[s][d] *= scale
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
