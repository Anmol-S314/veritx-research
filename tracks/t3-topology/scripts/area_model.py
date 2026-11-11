#!/usr/bin/env python3
"""PA-14 — Area overhead model: router port count + link count per topology.

Computes per-topology area overhead from first principles:
  - Number of routers
  - Ports per router (based on topology degree + concentration)
  - Total inter-router links
  - Computed area estimate (ports × unit area)
  - Booksim total_area from sweep data (ground truth comparison)

The area model uses topology parameters from configs/*.cfg to derive
the network graph structure analytically.

Usage
-----
    python3 scripts/area_model.py                       # print + write CSV
    python3 scripts/area_model.py --selfcheck           # regression tests
    python3 scripts/area_model.py --out /tmp/area.csv

API
---
    from scripts.area_model import area_table, topology_graph_params
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

HERE    = Path(__file__).parent
TRACK   = HERE.parent
CONFIGS = TRACK / "configs"
RESULTS = TRACK / "results"
OUTPUT  = TRACK / "output"

# Unit area per port (mm² @ 45nm, from Booksim/Orion models)
# Calibrated so mesh4x4 computed area ≈ Booksim total_area
UNIT_AREA_PER_PORT = 0.0165  # mm² per router port


def _parse_cfg(cfg_path: Path) -> dict:
    """Parse Booksim config file into parameter dict."""
    params = {}
    for line in cfg_path.read_text().splitlines():
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


def topology_graph_params(cfg_path: Path) -> dict:
    """Derive graph-level parameters from a topology config.

    Returns dict with:
        topology, topo_type, num_nodes, num_routers, ports_per_router,
        total_links, concentration, notes
    """
    p = _parse_cfg(cfg_path)
    topo = p.get("topology", "unknown")
    stem = cfg_path.stem
    k = _int(p, "k", 4)
    n = _int(p, "n", 2)
    c = _int(p, "c", 1)

    num_nodes = num_routers = ports_per_router = total_links = 0
    concentration = 1
    notes = ""

    if topo == "mesh":
        # k-ary n-cube mesh: k^n nodes, each router has 2n network + 1 local ports
        num_nodes = k ** n
        num_routers = num_nodes
        # Interior router: 2n directions + 1 local port
        # Edge/corner routers have fewer, but we use the max (worst case for area)
        ports_per_router = 2 * n + 1
        # Links: n × k^(n-1) × (k-1) — each dimension has k-1 links per row
        total_links = n * (k ** (n - 1)) * (k - 1)
        concentration = 1

    elif topo == "torus":
        # k-ary n-cube torus: same router count, all routers have 2n+1 ports
        num_nodes = k ** n
        num_routers = num_nodes
        ports_per_router = 2 * n + 1
        # Links: n × k^n (each dimension, every router has a link to neighbor)
        total_links = n * (k ** n)
        concentration = 1

    elif topo == "fattree":
        # k-ary n-tree: k^n terminal nodes, (2k)^(n-1) × n switch levels
        # Each switch: k down + k up ports (except root: k down only)
        num_nodes = k ** n
        # Routers at each level l: (k/2)^l × (k^n / k) ... simplified:
        # Total switches = n × (k/2)^(n-1) for a 2-level tree
        num_routers = n * (k // 2) ** (n - 1) if n > 1 else k
        # Each switch has 2k ports (k up + k down), except top level (k down only)
        ports_per_router = 2 * k
        total_links = num_nodes * n  # each node traverses n levels
        concentration = 1

    elif topo == "flatfly":
        # k-ary n-flat: k^n nodes, k^n routers (c=1) or k^n/c routers
        num_nodes = k ** n * c
        num_routers = k ** n
        # Each router: n×(k-1) network ports + c local ports
        ports_per_router = n * (k - 1) + c
        # Links per dimension: each router connects to k-1 others
        total_links = num_routers * n * (k - 1) // 2
        concentration = c

    elif topo in ("cmesh", "srota"):
        # Concentrated mesh: (k^n) routers, each with c terminals
        num_routers = k ** n
        num_nodes = num_routers * c
        # Router ports: 2n mesh ports + c local ports
        ports_per_router = 2 * n + c
        total_links = n * (k ** (n - 1)) * (k - 1)
        concentration = c
        if topo == "srota":
            notes = "srota: modelled as cmesh (MECS express channels not included)"

    elif topo == "fly":
        # Butterfly: k^n nodes, n stages of k^(n-1) switches, each k×k
        num_nodes = k ** n
        num_routers = n * (k ** (n - 1))
        ports_per_router = 2 * k  # k inputs + k outputs
        total_links = (n - 1) * (k ** (n - 1)) * k  # links between stages
        concentration = 1

    elif topo in ("tree4", "qtree"):
        # Tree: k^n leaf nodes, multi-level hierarchy
        num_nodes = k ** n
        # Level l has k^(n-1-l) switches (l=0 = leaf level)
        num_routers = sum(k ** i for i in range(n))
        ports_per_router = k + 1  # k children + 1 parent (root has k children, 0 parent)
        total_links = num_nodes - 1  # tree has N-1 edges
        concentration = 1
        notes = "tree topology — root is the bottleneck"

    elif topo in ("dragonfly", "dragonflynew"):
        # Dragonfly with parameter p=k
        pp = k
        a = 2 * pp              # routers per group
        h = pp                  # global channels per router
        num_nodes = a * pp * (2 * pp * pp + 1)  # 2p² × (2p²+1)
        groups = 2 * pp * pp + 1
        num_routers = a * groups
        # Each router: p terminal + (a-1) local + h global ports
        ports_per_router = pp + (a - 1) + h
        # Global links: each router has h global links
        total_links = num_routers * h // 2 + num_routers * (a - 1) // 2
        concentration = pp
        notes = f"dragonfly p={pp}, {groups} groups"

    elif topo == "anynet":
        notes = "anynet: custom topology (no analytical model)"

    else:
        notes = f"unknown topology: {topo}"

    # Computed area estimate
    computed_area = round(num_routers * ports_per_router * UNIT_AREA_PER_PORT, 4)

    return {
        "topology":          stem,
        "topo_type":         topo,
        "num_nodes":         num_nodes,
        "num_routers":       num_routers,
        "ports_per_router":  ports_per_router,
        "total_links":       total_links,
        "concentration":     concentration,
        "computed_area_mm2": computed_area,
        "notes":             notes,
    }


def area_table(
    configs_dir: Optional[Path] = None,
    sweep_path: Optional[Path] = None,
) -> list[dict]:
    """Build area overhead table for all topologies.

    Joins analytical model with Booksim's total_area from sweep data.
    """
    cdir = configs_dir or CONFIGS
    rows = []
    seen = set()

    # Load Booksim areas from sweep data if available
    booksim_areas = {}
    sp = sweep_path or RESULTS / "topology_sweep.json"
    if sp.exists():
        try:
            sweep = json.loads(sp.read_text())
            for r in sweep:
                topo = r.get("topology")
                area = r.get("total_area")
                if topo and area is not None and topo not in booksim_areas:
                    booksim_areas[topo] = area
        except Exception:
            pass

    for cfg_path in sorted(cdir.glob("*.cfg")):
        params = topology_graph_params(cfg_path)
        stem = params["topology"]
        dedup_key = (params["topo_type"], params["num_nodes"])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        # Join with Booksim area
        params["booksim_area_mm2"] = booksim_areas.get(stem)

        # Area ratio vs mesh4x4
        mesh_area = booksim_areas.get("mesh4x4")
        if mesh_area and params["booksim_area_mm2"]:
            params["area_ratio_vs_mesh"] = round(
                params["booksim_area_mm2"] / mesh_area, 4
            )
        else:
            params["area_ratio_vs_mesh"] = None

        rows.append(params)

    return rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _selfcheck():
    """Regression tests for area model."""
    import tempfile, os

    # mesh 4×4: 16 routers, 5 ports each (up/down/left/right/local), 24 links
    with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False, prefix="mesh4x4") as f:
        f.write("topology = mesh;\nk = 4;\nn = 2;\nrouting_function = dor;\n")
        tmp = Path(f.name)
    r = topology_graph_params(tmp)
    os.unlink(tmp)

    assert r["num_nodes"] == 16, f"mesh: expected 16 nodes, got {r['num_nodes']}"
    assert r["num_routers"] == 16, f"mesh: expected 16 routers, got {r['num_routers']}"
    assert r["ports_per_router"] == 5, f"mesh: expected 5 ports, got {r['ports_per_router']}"
    # Links: 2 dims × 4^1 × 3 = 24
    assert r["total_links"] == 24, f"mesh: expected 24 links, got {r['total_links']}"
    assert r["computed_area_mm2"] > 0

    # torus 4×4: 16 routers, 5 ports each, 32 links (wrap-around)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False, prefix="torus4x4") as f:
        f.write("topology = torus;\nk = 4;\nn = 2;\n")
        tmp = Path(f.name)
    r = topology_graph_params(tmp)
    os.unlink(tmp)
    assert r["num_nodes"] == 16
    assert r["total_links"] == 32, f"torus: expected 32 links, got {r['total_links']}"

    # cmesh k=2, n=2, c=4: 4 routers × (4+4)=8 ports
    with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as f:
        f.write("topology = cmesh;\nk = 2;\nn = 2;\nc = 4;\n")
        tmp = Path(f.name)
    r = topology_graph_params(tmp)
    os.unlink(tmp)
    assert r["num_nodes"] == 16, f"cmesh: expected 16 nodes, got {r['num_nodes']}"
    assert r["num_routers"] == 4, f"cmesh: expected 4 routers, got {r['num_routers']}"
    assert r["ports_per_router"] == 8, f"cmesh: expected 8 ports (4 mesh + 4 local), got {r['ports_per_router']}"

    # Full table on real configs
    table = area_table()
    assert len(table) > 0, "area_table() returned empty"

    # Area should be positive for known topologies
    for row in table:
        if row["topo_type"] != "anynet":
            assert row["computed_area_mm2"] > 0, f"{row['topology']}: area should be > 0"

    print("selfcheck OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--configs", default=None)
    ap.add_argument("--sweep", default=None, help="path to topology_sweep.json")
    ap.add_argument("--out", default=None,
                    help="output CSV path (default: output/area_overhead.csv)")
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    cdir = Path(args.configs) if args.configs else CONFIGS
    sweep = Path(args.sweep) if args.sweep else None
    table = area_table(cdir, sweep)

    if not table:
        sys.exit("No configs found.")

    # Print table
    print("\n=== PA-14: Area Overhead Model ===\n")
    print(f"  {'topology':<20s} {'type':<14s} {'nodes':>5s} {'rtrs':>5s} "
          f"{'ports':>5s} {'links':>5s} {'comp_area':>9s} {'booksim':>9s} {'ratio':>6s}")
    print(f"  {'-'*20} {'-'*14} {'-'*5} {'-'*5} {'-'*5} {'-'*5} {'-'*9} {'-'*9} {'-'*6}")

    for r in sorted(table, key=lambda x: x.get("booksim_area_mm2") or x["computed_area_mm2"]):
        ba = f"{r['booksim_area_mm2']:.4f}" if r.get("booksim_area_mm2") else "—"
        ratio = f"{r['area_ratio_vs_mesh']:.2f}×" if r.get("area_ratio_vs_mesh") else "—"
        print(f"  {r['topology']:<20s} {r['topo_type']:<14s} "
              f"{r['num_nodes']:>5d} {r['num_routers']:>5d} "
              f"{r['ports_per_router']:>5d} {r['total_links']:>5d} "
              f"{r['computed_area_mm2']:>9.4f} {ba:>9s} {ratio:>6s}")

    # Write CSV
    out = Path(args.out) if args.out else OUTPUT / "area_overhead.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(table[0].keys())
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(table)
    print(f"\n  → {out}  ({len(table)} topologies)")


if __name__ == "__main__":
    main()
