#!/usr/bin/env python3
"""PA-08 — Bisection bandwidth reference table per topology (analytical).

Computes the bisection bandwidth of every topology in configs/ using
closed-form formulas from the NoC literature.  No simulation required —
this is an *analytical sanity anchor* for the Booksim saturation results.

Bisection bandwidth = number of links crossing the minimum cut that
divides the network into two equal halves.  Higher bisection → higher
aggregate throughput capacity → saturation at higher injection rates.

Topology formulas
-----------------
  mesh    k-ary n-cube (no wrap):  bisection = k^(n-1)  links across one dim
  torus   k-ary n-cube (wrap):     bisection = 2 × k^(n-1)  (wrap doubles it)
  fattree k-ary n-tree:            bisection = (k/2)^n × k  (full at root)
  flatfly k-ary n-flat:            bisection ≈ k^(n-1) × ⌈(k-1)/2⌉
  cmesh   concentrated mesh:       bisection = k × c  (c = concentration)
  fly     butterfly k-ary n-fly:   bisection = k^(n-1)  (one stage cut)
  tree4   4-ary 3-tree:            bisection = root_degree  (bottleneck at root)
  qtree   quad-tree:               bisection = root_degree
  dragonfly:                       bisection = a × h  (groups × global ch.)

Usage
-----
    python3 scripts/bisection_bw.py                     # print table + write CSV
    python3 scripts/bisection_bw.py --selfcheck         # regression tests
    python3 scripts/bisection_bw.py --out /tmp/bw.csv   # custom output path

API
---
    from scripts.bisection_bw import bisection_table, parse_cfg_params
"""

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Optional

HERE    = Path(__file__).parent
TRACK   = HERE.parent
CONFIGS = TRACK / "configs"
OUTPUT  = TRACK / "output"


# ---------------------------------------------------------------------------
# Config parser — extract topology type and parameters from Booksim .cfg
# ---------------------------------------------------------------------------

def parse_cfg_params(cfg_path: Path) -> dict:
    """Parse a Booksim .cfg file into a dict of key→value.

    Handles:
      - `key = value;` lines  (with optional C-style // comments)
      - bare `key = value` (no semicolon)
      - ignores full-line comments

    Returns a dict with string keys and string values (caller casts).
    """
    params = {}
    text = cfg_path.read_text()
    for line in text.splitlines():
        # Strip C-style // comments
        line = re.sub(r"//.*", "", line).strip()
        if not line:
            continue
        m = re.match(r"(\w+)\s*=\s*(.+?)\s*;?\s*$", line)
        if m:
            params[m.group(1)] = m.group(2).strip()
    return params


def _int(params: dict, key: str, default: int = 0) -> int:
    try:
        return int(params.get(key, default))
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Bisection formulas
# ---------------------------------------------------------------------------

def _bisection_mesh(k: int, n: int) -> tuple[int, int, str]:
    """k-ary n-cube mesh (no wraparound)."""
    nodes = k ** n
    bisection = k ** (n - 1)
    return nodes, bisection, f"k^(n-1) = {k}^{n-1}"


def _bisection_torus(k: int, n: int) -> tuple[int, int, str]:
    """k-ary n-cube torus (wraparound doubles bisection vs mesh)."""
    nodes = k ** n
    bisection = 2 * k ** (n - 1)
    return nodes, bisection, f"2×k^(n-1) = 2×{k}^{n-1}"


def _bisection_fattree(k: int, n: int) -> tuple[int, int, str]:
    """k-ary n-tree fat tree. Full bisection at root level."""
    nodes = k ** n
    # Each level l has (k/2)^l × k links going up.
    # Bisection at root level = (k/2)^(n-1) × k
    bisection = (k // 2) ** (n - 1) * k
    return nodes, bisection, f"(k/2)^(n-1)×k = ({k}//2)^{n-1}×{k}"


def _bisection_flatfly(k: int, n: int) -> tuple[int, int, str]:
    """k-ary n-flat (flattened butterfly)."""
    nodes = k ** n
    # Each router connects to (k-1) others per dimension.
    # Bisection ≈ k^(n-1) × ⌈(k-1)/2⌉
    bisection = k ** (n - 1) * ((k - 1 + 1) // 2)
    return nodes, bisection, f"k^(n-1)×⌈(k-1)/2⌉"


def _bisection_cmesh(k: int, n: int, c: int) -> tuple[int, int, str]:
    """Concentrated mesh — k-ary n-cube with c nodes per router."""
    num_routers = k ** n
    nodes = num_routers * c
    # Bisection in the mesh dimension, each link carries c concentrated nodes
    bisection = k ** (n - 1)
    return nodes, bisection, f"k^(n-1) = {k}^{n-1} (c={c} concentrated)"


def _bisection_butterfly(k: int, n: int) -> tuple[int, int, str]:
    """k-ary n-fly butterfly."""
    nodes = k ** n
    # Each stage has k^(n-1) switches, each with k outputs → bisection = k^(n-1)
    bisection = k ** (n - 1)
    return nodes, bisection, f"k^(n-1) = {k}^{n-1} (one stage cut)"


def _bisection_tree(k: int, n: int) -> tuple[int, int, str]:
    """Generic tree (tree4 / qtree). Root is the bottleneck."""
    nodes = k ** n  # leaf nodes
    # Root has k children → k links at root = bisection
    bisection = k
    return nodes, bisection, f"root_degree = {k}"


def _bisection_dragonfly(k: int) -> tuple[int, int, str]:
    """Dragonfly with parameter p=k.
    a = 2p (routers/group), h = p (global channels), nodes = 2p² per group,
    g = 2p²+1 groups, total = 2p²×(2p²+1).
    Bisection = a × h = 2p × p = 2p².
    """
    p = k
    a = 2 * p          # routers per group
    h = p              # global channels per router
    nodes_per_group = a * p  # 2p²
    groups = 2 * p * p + 1
    nodes = nodes_per_group * groups
    bisection = a * h  # 2p²
    return nodes, bisection, f"a×h = {a}×{h} = {bisection} (p={p})"


# ---------------------------------------------------------------------------
# Main table builder
# ---------------------------------------------------------------------------

def bisection_table(configs_dir: Optional[Path] = None) -> list[dict]:
    """Build bisection bandwidth table for all configs in the directory.

    Returns list of dicts with keys:
        topology, topo_type, num_nodes, k, n, c,
        bisection_links, bisection_bw_per_node, notes
    """
    cdir = configs_dir or CONFIGS
    rows = []
    seen = set()

    for cfg_path in sorted(cdir.glob("*.cfg")):
        p = parse_cfg_params(cfg_path)
        topo_type = p.get("topology", "unknown")
        stem = cfg_path.stem

        # Avoid exact duplicates (e.g. mesh4x4.cfg and mesh.cfg with same params)
        k = _int(p, "k", 4)
        n = _int(p, "n", 2)
        c = _int(p, "c", 1)

        dedup_key = (topo_type, k, n, c)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        nodes = bisection = 0
        notes = ""

        if topo_type == "mesh":
            nodes, bisection, notes = _bisection_mesh(k, n)
        elif topo_type == "torus":
            nodes, bisection, notes = _bisection_torus(k, n)
        elif topo_type in ("fattree",):
            nodes, bisection, notes = _bisection_fattree(k, n)
        elif topo_type in ("flatfly",):
            nodes, bisection, notes = _bisection_flatfly(k, n)
        elif topo_type in ("cmesh",):
            nodes, bisection, notes = _bisection_cmesh(k, n, c)
        elif topo_type in ("fly",):
            nodes, bisection, notes = _bisection_butterfly(k, n)
        elif topo_type in ("tree4", "qtree"):
            nodes, bisection, notes = _bisection_tree(k, n)
        elif topo_type in ("dragonfly", "dragonflynew"):
            nodes, bisection, notes = _bisection_dragonfly(k)
        elif topo_type == "anynet":
            nodes, bisection, notes = 0, 0, "anynet: topology-dependent (no formula)"
        else:
            notes = f"unknown topology type: {topo_type}"

        bw_per_node = round(bisection / nodes, 4) if nodes > 0 else 0.0

        rows.append({
            "topology":              stem,
            "topo_type":             topo_type,
            "num_nodes":             nodes,
            "k":                     k,
            "n":                     n,
            "c":                     c,
            "bisection_links":       bisection,
            "bisection_bw_per_node": bw_per_node,
            "notes":                 notes,
        })

    return rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _selfcheck():
    """Regression tests for bisection formulas."""
    import tempfile, os

    # mesh 4×4: k=4, n=2 → 16 nodes, bisection = 4^1 = 4
    n, b, _ = _bisection_mesh(4, 2)
    assert n == 16 and b == 4, f"mesh 4×4: expected 16 nodes, 4 bisection, got {n}, {b}"

    # torus 4×4: k=4, n=2 → 16 nodes, bisection = 2×4^1 = 8
    n, b, _ = _bisection_torus(4, 2)
    assert n == 16 and b == 8, f"torus 4×4: expected 16 nodes, 8 bisection, got {n}, {b}"

    # fattree k=4, n=2 → 16 nodes, bisection = (4/2)^1 × 4 = 2×4 = 8
    n, b, _ = _bisection_fattree(4, 2)
    assert n == 16 and b == 8, f"fattree 4-ary 2-tree: expected 16 nodes, 8 bisection, got {n}, {b}"

    # flatfly k=4, n=2 → 16 nodes, bisection = 4^1 × ⌈3/2⌉ = 4×2 = 8
    n, b, _ = _bisection_flatfly(4, 2)
    assert n == 16 and b == 8, f"flatfly 4×2: expected 16 nodes, 8 bisection, got {n}, {b}"

    # butterfly k=4, n=2 → 16 nodes, bisection = 4^1 = 4
    n, b, _ = _bisection_butterfly(4, 2)
    assert n == 16 and b == 4, f"fly 4×2: expected 16 nodes, 4 bisection, got {n}, {b}"

    # cmesh k=2, n=2, c=4 → 16 nodes, bisection = 2^1 = 2
    n, b, _ = _bisection_cmesh(2, 2, 4)
    assert n == 16 and b == 2, f"cmesh 2×2 c=4: expected 16 nodes, 2 bisection, got {n}, {b}"

    # tree k=4, n=3 → 64 leaf nodes, bisection = 4
    n, b, _ = _bisection_tree(4, 3)
    assert n == 64 and b == 4, f"tree 4-ary 3-tree: expected 64 nodes, 4 bisection, got {n}, {b}"

    # dragonfly p=2 → 72 nodes, bisection = 2p² = 8
    n, b, _ = _bisection_dragonfly(2)
    assert n == 72 and b == 8, f"dragonfly p=2: expected 72 nodes, 8 bisection, got {n}, {b}"

    # Parse a synthetic .cfg
    with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as f:
        f.write("topology = mesh;\nk = 4;\nn = 2;\nrouting_function = dor;\n")
        tmp = f.name
    params = parse_cfg_params(Path(tmp))
    assert params["topology"] == "mesh"
    assert params["k"] == "4"
    os.unlink(tmp)

    # Full table on real configs
    table = bisection_table()
    assert len(table) > 0, "bisection_table() returned empty"
    # mesh4x4 should be present with correct values
    mesh_rows = [r for r in table if r["topo_type"] == "mesh"]
    assert len(mesh_rows) >= 1, "no mesh topology found in table"
    assert mesh_rows[0]["bisection_links"] == 4

    print("selfcheck OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--configs", default=None,
                    help="configs directory (default: track/configs)")
    ap.add_argument("--out", default=None,
                    help="output CSV path (default: output/bisection_bw.csv)")
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    cdir = Path(args.configs) if args.configs else CONFIGS
    table = bisection_table(cdir)

    if not table:
        sys.exit("No configs found — nothing to compute.")

    # Print table
    print("\n=== PA-08: Bisection Bandwidth Reference Table ===\n")
    hdr = f"  {'topology':<20s} {'type':<14s} {'nodes':>5s} {'bisect':>7s} {'BW/node':>8s}  notes"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for r in sorted(table, key=lambda x: -x["bisection_bw_per_node"]):
        print(f"  {r['topology']:<20s} {r['topo_type']:<14s} "
              f"{r['num_nodes']:>5d} {r['bisection_links']:>7d} "
              f"{r['bisection_bw_per_node']:>8.4f}  {r['notes']}")

    # Write CSV
    out = Path(args.out) if args.out else OUTPUT / "bisection_bw.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(table[0].keys()))
        w.writeheader()
        w.writerows(table)
    print(f"\n  → {out}  ({len(table)} topologies)")


if __name__ == "__main__":
    main()
