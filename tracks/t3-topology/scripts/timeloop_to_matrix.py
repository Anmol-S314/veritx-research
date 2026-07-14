#!/usr/bin/env python3
"""Timeloop -> Booksim traffic-matrix bridge (T3).

Parses a Timeloop `*.stats.txt` and emits an N x N traffic matrix in the format
Booksim's `matrix(<file>)` pattern reads (see tracks/t3-topology/booksim-ext).

Turning Timeloop's per-level access counts into a *tile-to-tile* NoC traffic
matrix is the core T3 research question (programme Wk6) — it depends on how the
workload is spatially mapped onto tiles. `build_traffic_matrix()` implements an
output-stationary mapping of the attention projection GEMM; see its docstring.

ponytail: one mapping (output-stationary), not a mapping framework. A
weight-stationary or row-stationary variant is a second function and a flag,
add it when there's an actual comparison to run.
"""
import re, sys, argparse
from pathlib import Path


def parse_levels(stats_text: str):
    """Per storage level: {name, instances, accesses, tensors}.

    accesses = sum of 'Actual scalar reads/fills/updates (per-instance)' over all
    tensors in that level (excludes algorithmic/gated/skipped/metadata lines).
    tensors = the same, but broken out per data-space ({'A': 4096, 'B': ...}) --
    the spatial model needs to know operands from outputs, not just a total."""
    levels, cur, inst, acc = [], None, 1, 0
    tensors, tname = {}, None
    for line in stats_text.splitlines():
        m = re.match(r'\s*=== (.+?) ===', line)
        if m:
            if cur and cur != '__ARITH__':
                levels.append({"name": cur, "instances": inst,
                               "accesses": acc, "tensors": tensors})
            cur, inst, acc = m.group(1), 1, 0
            tensors, tname = {}, None
            continue
        if not cur:
            continue
        mt = re.match(r'\s{4}(\w+):\s*$', line)  # a data-space header, e.g. "    A:"
        if mt:
            tname = mt.group(1)
            tensors.setdefault(tname, 0)
        mi = re.search(r'Utilized instances \(max\)\s*:\s*(\d+)', line)
        if mi:
            inst = int(mi.group(1))
        ma = re.search(r'Actual scalar (reads|fills|updates) \(per-instance\)\s*:\s*(\d+)', line)
        if ma:
            acc += int(ma.group(2))
            if tname:
                tensors[tname] += int(ma.group(2))
    if cur and cur != '__ARITH__':
        levels.append({"name": cur, "instances": inst,
                       "accesses": acc, "tensors": tensors})
    return levels


MEM_CTRL = 0  # tile 0 hosts the memory controller / DRAM port


def build_traffic_matrix(levels, num_nodes):
    """Output-stationary spatial model for the attention projection GEMM.

    The GEMM is Z(MxN) = A(MxK) . B(KxN). Tiles form a GxG mesh and each tile
    owns one block of Z -- so tile (r,c) needs *all* of A's row-block r and
    *all* of B's column-block c, and nothing else. That is what produces the
    traffic, and it is not uniform-random:

      * A's row-block r is read from DRAM once, lands on tile (r,0), and is
        then passed hand-to-hand ACROSS mesh row r. Every tile in the row
        needs the identical bytes, so it is a row multicast, not G separate
        DRAM reads.
      * B's column-block c likewise enters at tile (0,c) and walks DOWN mesh
        column c.
      * Z never moves during compute (output-stationary) and is written back
        to the memory controller at the end.

    Volumes come from Timeloop's DRAM per-tensor access counts, so the matrix
    describes the mapping Timeloop actually chose -- change the workload or the
    mapper and this moves with it.

    The signature is what the topology sweep is FOR: the row/column multicasts
    are exactly the paths a mesh is good at and a fat-tree pays for, while the
    all-tiles->node-0 writeback is the hotspot a fat-tree handles better than a
    mesh. The old placeholder's uniform ring had neither structure.
    """
    import math

    g = math.isqrt(num_nodes)
    if g * g != num_nodes:
        sys.exit(f"✗ {num_nodes} tiles is not a square mesh — the output-stationary "
                 f"GxG blocking has no sensible shape. Use a square node count.")
    node = lambda r, c: r * g + c  # row-major tile numbering, matches Booksim's mesh

    dram = next((l for l in levels if "DRAM" in l["name"].upper()), None)
    if not dram or not dram["tensors"]:
        sys.exit("✗ no per-tensor DRAM stats — can't build a spatial model. "
                 "Re-run `make timeloop`.")
    t = dram["tensors"]
    # A/B/Z are the data-space names from problem.yaml. Anything Timeloop lists
    # that isn't an output is treated as an operand, so a 3-operand shape still
    # works without editing this.
    a_words = t.get("A", 0)
    b_words = t.get("B", 0)
    z_words = t.get("Z", 0)
    if not (a_words and b_words):
        sys.exit(f"✗ DRAM tensors {list(t)} don't look like the A/B/Z GEMM shape.")

    mat = [[0.0] * num_nodes for _ in range(num_nodes)]

    def inject(dst, words):
        """DRAM -> tile. The memory controller shares tile MEM_CTRL, so data
        destined for that tile never crosses the network."""
        if dst != MEM_CTRL:
            mat[MEM_CTRL][dst] += words

    # --- A: DRAM -> head of each mesh row, then multicast across the row ---
    a_per_row = a_words / g
    for r in range(g):
        inject(node(r, 0), a_per_row)
        for c in range(g - 1):  # hand-to-hand along the row
            mat[node(r, c)][node(r, c + 1)] += a_per_row

    # --- B: DRAM -> head of each mesh column, then multicast down the column ---
    b_per_col = b_words / g
    for c in range(g):
        inject(node(0, c), b_per_col)
        for r in range(g - 1):
            mat[node(r, c)][node(r + 1, c)] += b_per_col

    # --- Z: output-stationary, so it only moves once, at writeback ---
    z_per_tile = z_words / num_nodes
    for n in range(num_nodes):
        if n != MEM_CTRL:
            mat[n][MEM_CTRL] += z_per_tile

    # Normalize so row sums are comparable to Booksim's uniform injection rates.
    max_row = max(sum(row) for row in mat)
    if max_row > 0:
        for row in mat:
            for d in range(num_nodes):
                row[d] /= max_row
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
              "=== DRAM ===\n    Utilized instances (max) : 2\n"
              "    A:\n"
              "        Actual scalar reads (per-instance) : 100\n"
              "        Algorithmic scalar reads (per-instance) : 999\n"
              "        Actual scalar metadata reads (per-instance) : 7\n"
              "    B:\n"
              "        Actual scalar reads (per-instance) : 200\n"
              "    Z:\n"
              "        Actual scalar updates (per-instance) : 40\n")
    levels = parse_levels(sample)
    assert [l["name"] for l in levels] == ["DRAM"], levels          # arith skipped
    assert levels[0]["accesses"] == 340, levels                     # algorithmic/metadata excluded
    assert levels[0]["tensors"] == {"A": 100, "B": 200, "Z": 40}, levels[0]["tensors"]

    m = build_traffic_matrix(levels, 4)                             # 2x2 mesh
    assert len(m) == 4 and all(len(r) == 4 for r in m)             # square NxN
    assert all(v >= 0 for row in m for v in row)                   # non-negative weights
    assert abs(max(sum(r) for r in m) - 1.0) < 1e-9                # normalized: max row sum = 1
    assert all(m[n][n] == 0 for n in range(4)), m                  # no tile talks to itself

    # the mapping's shape, not just its arithmetic: on a 2x2 mesh (nodes 0,1 /
    # 2,3), A row-block 1 must reach tile 2 and multicast to tile 3, while B
    # column-block 1 reaches tile 1 and multicasts down to tile 3.
    assert m[2][3] > 0, "A should multicast across mesh row 1"
    assert m[1][3] > 0, "B should multicast down mesh column 1"
    assert m[3][2] == 0 and m[3][1] == 0, "multicast is one-directional"
    assert m[3][0] > 0, "Z must be written back to the memory controller"
    # B is 2x the volume of A here, so a column hop must outweigh a row hop
    assert m[1][3] > m[2][3], (m[1][3], m[2][3])
    print("selfcheck OK")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--selfcheck":
        _selfcheck()
    else:
        main()
