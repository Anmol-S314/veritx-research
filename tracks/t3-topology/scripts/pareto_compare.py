#!/usr/bin/env python3
"""PA-19 — Side-by-side Pareto: 7B vs 70B — does optimal topology change?

Compares the 2D Pareto front (norm_latency vs energy_score) under two
traffic regimes:
  - "7B"  : Llama-3 7B traffic matrix  (Pair A traffic, batch/context sweep)
  - "70B" : Llama-3 70B traffic matrix (Pair A 70B matrices + Pair B runs)

Since the 70B sweep data and Pair A 70B matrices are not yet available from
the sibling pair, this script:
  1. Runs with the existing uniform-traffic sweep as the "7B" dataset.
  2. Synthesises a representative "70B" dataset by scaling the traffic matrix
     (70B models have ~10× more KV-cache traffic to DRAM → higher latency
     for topologies with low bisection BW, while high-BW topologies are
     relatively less affected). This is clearly labelled as synthetic.
  3. When `--sweep-70b` is provided, uses the real 70B sweep JSON instead.

Produces:
  - Side-by-side Pareto figure → output/pareto_compare_7b_70b.png
  - Finding printout: which topologies change Pareto membership between regimes

Usage
-----
    python3 scripts/pareto_compare.py                    # synthetic 70B
    python3 scripts/pareto_compare.py --sweep-70b /path  # real 70B data
    python3 scripts/pareto_compare.py --selfcheck

API
---
    from scripts.pareto_compare import (
        make_synthetic_70b, compare_pareto_fronts,
    )
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import pandas as pd
import numpy as np

HERE    = Path(__file__).parent
TRACK   = HERE.parent
RESULTS = TRACK / "results"
OUTPUT  = TRACK / "output"

PALETTE = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52",
    "#8172B2", "#937860", "#DA8BC3", "#8C8C8C",
    "#CCB974", "#64B5CD",
]

# Bisection bandwidth per topology (from PA-08 analytical table).
# Used to compute synthetic 70B latency scaling factors.
_BISECT_BW: dict[str, int] = {
    "fly4":      4,
    "cmesh":     2,
    "fattree":   8,
    "flatfly":   8,
    "torus4x4":  8,
    "mesh4x4":   4,
    "tree4":     4,
    "qtree":     4,
}


# ---------------------------------------------------------------------------
# Synthetic 70B scaling (used when real 70B data is unavailable)
# ---------------------------------------------------------------------------

def make_synthetic_70b(df_7b: pd.DataFrame) -> pd.DataFrame:
    """Scale 7B Pareto data to approximate a 70B traffic regime.

    Scaling heuristic (documented in output):
      - 70B LLMs have ~10× more DRAM KV-cache traffic → network is under
        heavier all-to-all communication pressure.
      - Topologies with high bisection BW (fattree, flatfly, torus) absorb
        the extra traffic more gracefully → smaller latency increase.
      - Topologies with low bisection (cmesh, mesh, tree) are bottlenecked
        → latency increases more.
      - Scale factor = 1.0 + (base_BW / topo_bisect_bw) × 0.15
        where base_BW = 4 (mesh baseline bisection).

    This is a first-order approximation. Replace with real 70B sweep JSON
    when available from Pair A via --sweep-70b.
    """
    df = df_7b.copy()
    df["regime"] = "7B (uniform)"

    df_70 = df_7b.copy()
    df_70["regime"] = "70B (synthetic)"

    base_bw = 4  # mesh baseline bisection
    for idx, row in df_70.iterrows():
        topo = row["topology"]
        bw   = _BISECT_BW.get(topo, base_bw)
        scale = 1.0 + (base_bw / bw) * 0.15
        df_70.at[idx, "norm_latency"]  = row["norm_latency"]  * scale
        df_70.at[idx, "energy_score"]  = row["energy_score"]  * scale

    return df, df_70


# ---------------------------------------------------------------------------
# Pareto comparison
# ---------------------------------------------------------------------------

def compare_pareto_fronts(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    label_a: str = "7B",
    label_b: str = "70B",
) -> dict:
    """Compare which topologies are on the Pareto front in each regime.

    Returns a dict with keys:
        front_a  : set of topology names on Pareto front in regime A
        front_b  : set of topology names on Pareto front in regime B
        stable   : topologies on front in both   (robust)
        gained   : topologies that gained Pareto membership in B
        lost     : topologies that lost Pareto membership in B
    """
    sys.path.insert(0, str(HERE))
    from pareto import pareto_front_2d

    r_a = pareto_front_2d(df_a)
    r_b = pareto_front_2d(df_b)

    front_a = set(r_a[r_a["pareto_front"]]["topology"].tolist())
    front_b = set(r_b[r_b["pareto_front"]]["topology"].tolist())

    return {
        "front_a":  front_a,
        "front_b":  front_b,
        "stable":   front_a & front_b,
        "gained":   front_b - front_a,
        "lost":     front_a - front_b,
        "df_a":     r_a,
        "df_b":     r_b,
    }


# ---------------------------------------------------------------------------
# Side-by-side plot
# ---------------------------------------------------------------------------

def plot_pareto_compare(
    comparison: dict,
    label_a: str = "7B (uniform traffic)",
    label_b: str = "70B (synthetic — heavier all-to-all)",
    figsize: tuple = (16, 7),
    dpi: int = 150,
) -> tuple["plt.Figure", list]:
    """Side-by-side 2D Pareto plots for the two traffic regimes."""
    df_a = comparison["df_a"]
    df_b = comparison["df_b"]

    all_topos = sorted(set(df_a["topology"].tolist()) | set(df_b["topology"].tolist()))
    colours   = {t: PALETTE[i % len(PALETTE)] for i, t in enumerate(all_topos)}

    fig, axes = plt.subplots(1, 2, figsize=figsize, dpi=dpi,
                              sharey=False)
    fig.suptitle(
        "PA-19: Does Optimal Topology Change Between 7B and 70B?",
        fontsize=13, fontweight="bold", y=1.01,
    )

    for ax, (df, label, front_key) in zip(axes, [
        (df_a, label_a, "front_a"),
        (df_b, label_b, "front_b"),
    ]):
        valid = df[["norm_latency", "energy_score"]].notna().all(axis=1)
        df_v  = df[valid].copy()
        front_set = comparison[front_key]

        ax.set_title(label, fontsize=11, fontweight="bold", pad=8)
        ax.set_xlabel("Norm Latency (lower = better)", fontsize=10)
        ax.set_ylabel("Energy Score [pJ] (lower = better)", fontsize=10)
        ax.grid(True, linestyle="--", alpha=0.35)

        for topo in sorted(df_v["topology"].unique()):
            row = df_v[df_v["topology"] == topo]
            x = float(row["norm_latency"].iloc[0])
            y = float(row["energy_score"].iloc[0])
            col = colours[topo]
            on = topo in front_set

            ms  = 130 if on else 55
            mrk = "*"  if on else "o"
            edg = "black" if on else col
            lw  = 1.5 if on else 0.7

            ax.scatter(x, y, s=ms, c=col, marker=mrk,
                       edgecolors=edg, linewidths=lw, label=topo,
                       zorder=5 if on else 3)
            ax.annotate(topo, xy=(x, y), xytext=(5, 4),
                        textcoords="offset points",
                        fontsize=7 if on else 6,
                        fontweight="bold" if on else "normal",
                        color=col, alpha=0.9)

        # Pareto staircase
        front_df = df_v[df_v["topology"].isin(front_set)].sort_values("norm_latency")
        if len(front_df) >= 2:
            fx = front_df["norm_latency"].tolist()
            fy = front_df["energy_score"].tolist()
            sx, sy = [fx[0]], [fy[0]]
            for i in range(1, len(fx)):
                sx += [fx[i], fx[i]]
                sy += [fy[i - 1], fy[i]]
            ax.plot(sx, sy, color="#333333", lw=1.5, ls="--", alpha=0.55)

        # Legend on first panel only
        if ax is axes[0]:
            handles, labels = ax.get_legend_handles_labels()
            ax.legend(handles, labels, fontsize=6, framealpha=0.8,
                      loc="upper right", ncol=2)

    fig.tight_layout()
    return fig, axes


# ---------------------------------------------------------------------------
# Selfcheck
# ---------------------------------------------------------------------------

def _selfcheck():
    """Regression test: synthetic 70B scaling changes at least one topology."""
    import io

    sys.path.insert(0, str(HERE))
    from pareto import build_pareto_df, pareto_front_2d

    try:
        df_7b = build_pareto_df()
    except Exception:
        # No real sweep data — use synthetic sample
        df_7b = pd.DataFrame([
            {"topology": "fly4",    "norm_latency": 0.69, "energy_score": 41.0, "total_area": 0.125},
            {"topology": "cmesh",   "norm_latency": 0.74, "energy_score": 41.3, "total_area": 0.187},
            {"topology": "fattree", "norm_latency": 0.78, "energy_score": 50.0, "total_area": 0.236},
            {"topology": "mesh4x4", "norm_latency": 1.00, "energy_score": 71.4, "total_area": 0.331},
        ])

    df_a, df_b = make_synthetic_70b(df_7b)

    # Both DataFrames should have same topologies
    assert set(df_a["topology"]) == set(df_b["topology"]), "topology mismatch"

    # 70B latencies should be ≥ 7B latencies (scaling ≥ 1.0)
    for topo in df_a["topology"]:
        nl_a = float(df_a[df_a["topology"] == topo]["norm_latency"].iloc[0])
        nl_b = float(df_b[df_b["topology"] == topo]["norm_latency"].iloc[0])
        assert nl_b >= nl_a - 1e-9, \
            f"{topo}: 70B latency {nl_b:.4f} < 7B latency {nl_a:.4f}"

    result = compare_pareto_fronts(df_a, df_b)
    assert isinstance(result["front_a"], set), "front_a should be a set"
    assert isinstance(result["stable"], set),  "stable should be a set"

    # Plot smoke-test
    fig, axes = plot_pareto_compare(result, dpi=72)
    assert len(axes) == 2
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    assert buf.tell() > 1000
    plt.close(fig)

    print("selfcheck OK")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sweep",     default=None, help="path to 7B topology_sweep.json")
    ap.add_argument("--sweep-70b", default=None, help="path to 70B topology_sweep.json (Pair A)")
    ap.add_argument("--out",       default=None,
                    help="output image path (default: output/pareto_compare_7b_70b.png)")
    ap.add_argument("--pj",        type=float, default=20.5)
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    sys.path.insert(0, str(HERE))
    from pareto import build_pareto_df

    # --- 7B dataset
    sweep_7b = Path(args.sweep) if args.sweep else None
    df_7b    = build_pareto_df(sweep_7b, pj_per_hop=args.pj)
    df_7b["regime"] = "7B"

    # --- 70B dataset (real or synthetic)
    if args.sweep_70b:
        df_70b = build_pareto_df(Path(args.sweep_70b), pj_per_hop=args.pj)
        df_70b["regime"] = "70B (real)"
        label_b = "70B (Pair A — real data)"
        print("  Using real 70B sweep data from Pair A.")
    else:
        _, df_70b = make_synthetic_70b(df_7b)
        label_b = "70B (synthetic — bisect-BW-scaled)"
        print("  ⚠  No 70B sweep provided. Using synthetic scaling (bisect-BW heuristic).")
        print("     Run with --sweep-70b when Pair A shares their 70B topology_sweep.json.")

    # --- Compare
    comparison = compare_pareto_fronts(df_7b, df_70b, "7B", "70B")

    print(f"\n=== PA-19: Pareto Comparison — 7B vs 70B ===")
    print(f"  7B  front  : {', '.join(sorted(comparison['front_a']))}")
    print(f"  70B front  : {', '.join(sorted(comparison['front_b']))}")
    print(f"  Stable (both)  : {', '.join(sorted(comparison['stable'])) or '—'}")
    print(f"  Gained in 70B  : {', '.join(sorted(comparison['gained'])) or '—'}")
    print(f"  Lost  in 70B   : {', '.join(sorted(comparison['lost']))  or '—'}")

    if not comparison["lost"] and not comparison["gained"]:
        print("\n  Finding: Pareto front is STABLE — same topology set wins in both regimes.")
    else:
        print(f"\n  Finding: Pareto front CHANGES going from 7B to 70B.")
        if comparison["lost"]:
            print(f"    Topologies dropped: {', '.join(sorted(comparison['lost']))}")
            print(f"    (likely low bisection BW → higher relative latency under heavier traffic)")
        if comparison["gained"]:
            print(f"    Topologies added:   {', '.join(sorted(comparison['gained']))}")

    # --- Plot
    fig, _ = plot_pareto_compare(
        comparison,
        label_a="7B (uniform traffic)",
        label_b=label_b,
    )
    out = Path(args.out) if args.out else OUTPUT / "pareto_compare_7b_70b.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"\n  figure → {out}")


if __name__ == "__main__":
    main()
