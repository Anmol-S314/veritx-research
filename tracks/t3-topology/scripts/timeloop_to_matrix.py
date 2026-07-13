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


def sizes_from_configs():
    """Every distinct node count present in configs/ (sorted).

    A traffic matrix must be exactly nodes x nodes, but that's a per-topology
    constraint, not a global one -- so we emit one matrix per distinct size and
    let a sweep mix 16- and 64-node topologies freely. Nothing is hardcoded: add
    a config of any size and its matrix appears.
    """
    from run_experiments import nodes_from_cfg  # same dir; single source of truth

    cfgs = sorted((Path(__file__).parent.parent / "configs").glob("*.cfg"))
    sizes = {c.stem: nodes_from_cfg(c) for c in cfgs}
    unknown = [k for k, v in sizes.items() if not v]
    if unknown:
        print(f"  ⚠  can't derive node count for: {', '.join(unknown)} — no matrix "
              f"will be generated for them, so they'll be skipped in a matrix sweep.")
    known = sorted({s for s in sizes.values() if s})
    if not known:
        sys.exit("✗ could not derive any node count from configs/ — pass -n explicitly.")
    return known


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stats",
                    help="Timeloop *.stats.txt; '{n}' is replaced by the node "
                         "count, so each size uses the arch that was mapped for it")
    ap.add_argument("-n", "--nodes", default="auto",
                    help="NoC node count. 'auto' (default) emits one matrix for "
                         "every distinct node count in configs/*.cfg.")
    ap.add_argument("-o", "--out", default="traffic_matrix_{n}.txt",
                    help="output path; '{n}' is replaced by the node count")
    args = ap.parse_args()

    sizes = sizes_from_configs() if args.nodes == "auto" else [int(args.nodes)]
    if len(sizes) > 1 and "{n}" not in args.out:
        sys.exit(f"✗ configs/ span {len(sizes)} node counts {sizes}, but -o has no "
                 f"'{{n}}' placeholder — they'd overwrite each other.")

    wrote = 0
    for n in sizes:
        stats = Path(args.stats.replace("{n}", str(n)))
        if not stats.exists():
            # Better to emit no matrix than one built from another size's mapping:
            # run_experiments then skips this topology loudly instead of driving it
            # with traffic that describes a different machine.
            print(f"  ⚠  {stats} missing — no {n}-node matrix (run `make timeloop`)")
            continue
        levels = parse_levels(stats.read_text())
        out = args.out.replace("{n}", str(n))
        write_matrix(build_traffic_matrix(levels, n), out)
        acc = ", ".join(f"{l['name']}={l['accesses'] * l['instances']}" for l in levels)
        print(f"  wrote {n}x{n} matrix -> {out}   [{acc}]")
        wrote += 1

    if not wrote:
        sys.exit("✗ no traffic matrices written — no Timeloop stats found.")


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
    assert len(m) == 4 and all(len(r) == 4 for r in m)             # square NxN
    assert all(v >= 0 for row in m for v in row)                   # non-negative weights
    assert abs(max(sum(r) for r in m) - 1.0) < 1e-9               # normalized: max row sum = 1
    col = lambda c: sum(m[s][c] for s in range(4))
    assert col(0) > col(2), m                                     # node 0 (mem controller) is a hotspot
    print("selfcheck OK")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--selfcheck":
        _selfcheck()
    else:
        main()
