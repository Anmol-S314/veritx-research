#!/usr/bin/env python3
"""PA-15 — Area-constrained topology ranking.

Filters topologies to those within an area budget (default: <10% overhead
vs mesh4x4), then ranks them by best latency performance.

This answers: "Given a fixed silicon area budget, which topology
delivers the best latency?"

Usage
-----
    python3 scripts/area_ranking.py                       # default budget
    python3 scripts/area_ranking.py --budget 0.15         # 15% overhead
    python3 scripts/area_ranking.py --selfcheck

API
---
    from scripts.area_ranking import area_constrained_ranking
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

HERE    = Path(__file__).parent
TRACK   = HERE.parent
RESULTS = TRACK / "results"
OUTPUT  = TRACK / "output"

# Default area budget: topologies within 10% area overhead of mesh4x4
DEFAULT_BUDGET = 0.10  # 10% overhead
BASELINE_TOPO  = "mesh4x4"


def area_constrained_ranking(
    df: pd.DataFrame,
    budget: float = DEFAULT_BUDGET,
    baseline_topo: str = BASELINE_TOPO,
) -> pd.DataFrame:
    """Rank topologies by latency, filtered to area budget.

    Parameters
    ----------
    df             : sweep DataFrame with 'total_area' column
    budget         : max fractional area overhead vs baseline (e.g. 0.10 = 10%)
    baseline_topo  : topology to use as area baseline (default: mesh4x4)

    Returns
    -------
    DataFrame with columns:
        topology, zero_load_latency, total_area, area_overhead_pct,
        saturation_rate, within_budget, rank
    Sorted by zero_load_latency (lower = better).
    """
    ok = df[df["status"] == "ok"].copy()

    # Get baseline area from the baseline topology
    baseline_rows = ok[ok["topology"] == baseline_topo]
    if baseline_rows.empty or baseline_rows["total_area"].isna().all():
        raise ValueError(f"No valid area data for baseline topology '{baseline_topo}'")
    baseline_area = baseline_rows["total_area"].iloc[0]
    area_limit = baseline_area * (1.0 + budget)

    # Per-topology summary at zero-load (lowest injection rate)
    summary_rows = []
    for topo, grp in ok.groupby("topology"):
        grp_s = grp.sort_values("injection_rate")
        zero_lat = grp_s["latency_cycles"].iloc[0]
        area = grp_s["total_area"].iloc[0] if pd.notna(grp_s["total_area"].iloc[0]) else None

        # Saturation rate (threshold method)
        sat_rate = None
        if len(grp_s) >= 2:
            zl = grp_s["latency_cycles"].iloc[0]
            sat_rows = grp_s[grp_s["latency_cycles"] > 2.0 * zl]
            if not sat_rows.empty:
                sat_rate = sat_rows["injection_rate"].iloc[0]

        overhead_pct = None
        within = None
        if area is not None:
            overhead_pct = round((area - baseline_area) / baseline_area * 100, 2)
            within = area <= area_limit

        summary_rows.append({
            "topology":          topo,
            "zero_load_latency": round(zero_lat, 3),
            "total_area":        round(area, 6) if area is not None else None,
            "area_overhead_pct": overhead_pct,
            "saturation_rate":   sat_rate,
            "within_budget":     within,
        })

    result = pd.DataFrame(summary_rows)

    # Sort by latency (best first) and assign rank
    result = result.sort_values("zero_load_latency").reset_index(drop=True)
    result["rank"] = result.index + 1

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _selfcheck():
    """Regression tests for area-constrained ranking."""
    sample = pd.DataFrame([
        # fly4: best latency, low area
        {"topology": "fly4",    "injection_rate": 0.01, "latency_cycles": 16.58,
         "total_area": 0.1246, "status": "ok"},
        {"topology": "fly4",    "injection_rate": 0.08, "latency_cycles": 24.13,
         "total_area": 0.1246, "status": "ok"},
        # cmesh: good latency, lower area than mesh
        {"topology": "cmesh",   "injection_rate": 0.01, "latency_cycles": 17.75,
         "total_area": 0.1873, "status": "ok"},
        {"topology": "cmesh",   "injection_rate": 0.08, "latency_cycles": 222.8,
         "total_area": 0.1873, "status": "ok"},
        # mesh4x4: baseline
        {"topology": "mesh4x4", "injection_rate": 0.01, "latency_cycles": 23.91,
         "total_area": 0.3313, "status": "ok"},
        {"topology": "mesh4x4", "injection_rate": 0.08, "latency_cycles": 29.54,
         "total_area": 0.3313, "status": "ok"},
        # torus: slightly more area than mesh
        {"topology": "torus4x4","injection_rate": 0.01, "latency_cycles": 23.05,
         "total_area": 0.3676, "status": "ok"},
        {"topology": "torus4x4","injection_rate": 0.08, "latency_cycles": 28.01,
         "total_area": 0.3676, "status": "ok"},
        # tree4: much higher area
        {"topology": "tree4",   "injection_rate": 0.01, "latency_cycles": 28.88,
         "total_area": 0.9707, "status": "ok"},
        {"topology": "tree4",   "injection_rate": 0.08, "latency_cycles": 503.35,
         "total_area": 0.9707, "status": "ok"},
        # dragonfly: unstable everywhere — excluded
        {"topology": "dragonfly16", "injection_rate": 0.01, "latency_cycles": 741.16,
         "total_area": 1.7327, "status": "unstable"},
    ])

    result = area_constrained_ranking(sample, budget=0.10)

    # Should have 5 topologies (dragonfly excluded — unstable)
    assert len(result) == 5, f"expected 5 topologies, got {len(result)}"

    # mesh4x4 area = 0.3313, 10% budget = 0.3644
    # fly4 (0.1246) ✓, cmesh (0.1873) ✓, mesh4x4 (0.3313) ✓,
    # torus (0.3676) ✗ (>0.3644), tree4 (0.9707) ✗
    within = result[result["within_budget"] == True]
    assert len(within) == 3, f"expected 3 within budget, got {len(within)}"
    assert set(within["topology"]) == {"fly4", "cmesh", "mesh4x4"}, \
        f"unexpected within-budget set: {set(within['topology'])}"

    # Ranking by latency: fly4 < cmesh < mesh4x4 < torus < tree4
    assert result.iloc[0]["topology"] == "fly4"
    assert result.iloc[1]["topology"] == "cmesh"

    # fly4 overhead should be negative (smaller than mesh)
    fly4_row = result[result["topology"] == "fly4"].iloc[0]
    assert fly4_row["area_overhead_pct"] < 0, "fly4 should have negative overhead vs mesh"

    # tree4 should not be within budget
    tree4_row = result[result["topology"] == "tree4"].iloc[0]
    assert not tree4_row["within_budget"], "tree4 should not be within budget"

    print("selfcheck OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sweep", default=None, help="path to topology_sweep.json")
    ap.add_argument("--budget", type=float, default=DEFAULT_BUDGET,
                    help=f"area budget as fraction (default: {DEFAULT_BUDGET})")
    ap.add_argument("--baseline", default=BASELINE_TOPO,
                    help=f"baseline topology for area comparison (default: {BASELINE_TOPO})")
    ap.add_argument("--out", default=None,
                    help="output CSV path (default: output/area_constrained_ranking.csv)")
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    sys.path.insert(0, str(HERE))
    from analysis import load_sweep_df

    df = load_sweep_df(args.sweep)
    result = area_constrained_ranking(df, budget=args.budget, baseline_topo=args.baseline)

    budget_pct = args.budget * 100
    print(f"\n=== PA-15: Area-Constrained Topology Ranking ===")
    print(f"  Budget: ≤{budget_pct:.0f}% overhead vs {args.baseline}\n")

    within = result[result["within_budget"] == True]
    outside = result[result["within_budget"] == False]

    print(f"  {'rank':>4s} {'topology':<20s} {'latency':>8s} {'area':>9s} "
          f"{'overhead':>9s} {'sat_rate':>9s} {'budget':>6s}")
    print(f"  {'-'*4} {'-'*20} {'-'*8} {'-'*9} {'-'*9} {'-'*9} {'-'*6}")

    for _, r in result.iterrows():
        area_s = f"{r['total_area']:.4f}" if pd.notna(r['total_area']) else "—"
        oh_s = f"{r['area_overhead_pct']:+.1f}%" if pd.notna(r.get('area_overhead_pct')) else "—"
        sat_s = f"{r['saturation_rate']:.3f}" if r['saturation_rate'] else "—"
        budget_s = "✓" if r['within_budget'] else "✗"
        print(f"  {r['rank']:>4d} {r['topology']:<20s} {r['zero_load_latency']:>8.3f} "
              f"{area_s:>9s} {oh_s:>9s} {sat_s:>9s} {budget_s:>6s}")

    if not within.empty:
        best = within.iloc[0]
        print(f"\n  ★ Best within budget: {best['topology']} "
              f"(latency={best['zero_load_latency']:.3f}, "
              f"area overhead={best['area_overhead_pct']:+.1f}%)")
    else:
        print(f"\n  ⚠ No topologies within {budget_pct:.0f}% area budget")

    # Write CSV
    out = Path(args.out) if args.out else OUTPUT / "area_constrained_ranking.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(out, index=False)
    print(f"\n  → {out}  ({len(result)} topologies, {len(within)} within budget)")


if __name__ == "__main__":
    main()
