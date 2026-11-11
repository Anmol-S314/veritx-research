#!/usr/bin/env python3
"""PA-18 — 3D Pareto: latency × energy × area; identify 3D optimal set.

Extends the 2D non-dominated sort (pareto.py) to a third objective:
  x-axis : norm_latency  (lower = better)
  y-axis : energy_score  (hops × pJ/hop, lower = better)
  z-axis : total_area    (mm², lower = better)

Three complementary views are generated:
  1. 3D scatter plot (matplotlib 3D axes) — overview of the objective space
  2. 2D projection panels: lat-energy, lat-area, energy-area — Pareto hulls
  3. CSV with per-topology Pareto membership flag

Usage
-----
    python3 scripts/pareto_3d.py                     # → output/pareto_3d.png
    python3 scripts/pareto_3d.py --3panel            # 3-panel projection view
    python3 scripts/pareto_3d.py --selfcheck

API
---
    from scripts.pareto_3d import plot_pareto_3d, plot_pareto_3panel
"""

import warnings
# Suppress the Axes3D UserWarning that fires during pyplot initialisation when
# two matplotlib versions are installed (system + pip). Must come BEFORE any
# matplotlib import because pyplot scans projections at import time.
warnings.filterwarnings(
    "ignore",
    message="Unable to import Axes3D",
    category=UserWarning,
    module="matplotlib",
)

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
# Axes3D may be unavailable when two matplotlib versions are installed
# (system + pip conflict). Soft-import so 2D panel mode always works.
try:
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        from mpl_toolkits.mplot3d import Axes3D   # noqa: F401
    _AXES3D_OK = True
except Exception:
    _AXES3D_OK = False
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


# ---------------------------------------------------------------------------
# 3D scatter plot (PA-18 deliverable — view 1)
# ---------------------------------------------------------------------------

def plot_pareto_3d(
    df: pd.DataFrame,
    title: str = "PA-18: 3D Pareto Front — Latency × Energy × Area",
    figsize: tuple = (11, 8),
    dpi: int = 150,
) -> tuple["plt.Figure", "plt.Axes"]:
    """3D scatter of all topologies; Pareto-optimal points are starred.

    Parameters
    ----------
    df : DataFrame with norm_latency, energy_score, total_area, topology,
         pareto_front_3d (bool) columns.

    Returns
    -------
    (fig, ax3d)
    """
    valid = df[["norm_latency", "energy_score", "total_area"]].notna().all(axis=1)
    df_v = df[valid].copy()

    topologies = sorted(df_v["topology"].unique())
    colours = {t: PALETTE[i % len(PALETTE)] for i, t in enumerate(topologies)}

    if not _AXES3D_OK:
        raise RuntimeError(
            "Axes3D unavailable (conflicting matplotlib installs). "
            "Run with --3panel for 2D projections, or: "
            "pip install --upgrade --force-reinstall matplotlib"
        )

    fig = plt.figure(figsize=figsize, dpi=dpi)
    ax  = fig.add_subplot(111, projection="3d")

    ax.set_xlabel("Norm Latency\n(lower=better)", fontsize=9, labelpad=8)
    ax.set_ylabel("Energy Score (pJ)\n(lower=better)", fontsize=9, labelpad=8)
    ax.set_zlabel("Total Area (mm²)\n(lower=better)", fontsize=9, labelpad=8)
    ax.set_title(title, fontsize=13, fontweight="bold", pad=14)

    for topo in topologies:
        row = df_v[df_v["topology"] == topo]
        x = float(row["norm_latency"].iloc[0])
        y = float(row["energy_score"].iloc[0])
        z = float(row["total_area"].iloc[0])
        on_front = bool(row["pareto_front_3d"].iloc[0])
        col = colours[topo]

        ms  = 120 if on_front else 50
        mrk = "*"  if on_front else "o"
        edg = "black" if on_front else col
        lw  = 1.5 if on_front else 0.7

        ax.scatter(x, y, z, s=ms, c=col, marker=mrk,
                   edgecolors=edg, linewidths=lw, zorder=5 if on_front else 3)
        ax.text(x, y, z + 0.01, f" {topo}", fontsize=7,
                color=col, alpha=0.85, zorder=6)

    # Pareto envelope lines between front points (sorted by lat then area)
    front = df_v[df_v["pareto_front_3d"]].sort_values(["norm_latency", "total_area"])
    if len(front) >= 2:
        ax.plot(
            front["norm_latency"].tolist(),
            front["energy_score"].tolist(),
            front["total_area"].tolist(),
            color="#333333", linewidth=1.2, linestyle="--", alpha=0.5,
        )

    front_patch  = mpatches.Patch(color="none", label="★ = Pareto-optimal (3D)")
    normal_patch = mpatches.Patch(color="none", label="● = sub-optimal")
    ax.legend(handles=[front_patch, normal_patch], loc="upper right",
              fontsize=8, framealpha=0.8)

    fig.tight_layout()
    return fig, ax


# ---------------------------------------------------------------------------
# 3-panel projection (PA-18 deliverable — view 2)
# ---------------------------------------------------------------------------

def plot_pareto_3panel(
    df: pd.DataFrame,
    title: str = "PA-18: 3D Pareto — Projection Panels",
    figsize: tuple = (15, 5),
    dpi: int = 150,
) -> tuple["plt.Figure", list]:
    """Three 2D projection panels of the 3D Pareto space.

    Panels: (1) lat vs energy, (2) lat vs area, (3) energy vs area.
    Each panel marks 3D Pareto-front points with stars.
    """
    valid = df[["norm_latency", "energy_score", "total_area"]].notna().all(axis=1)
    df_v = df[valid].copy()

    topologies = sorted(df_v["topology"].unique())
    colours = {t: PALETTE[i % len(PALETTE)] for i, t in enumerate(topologies)}

    fig, axes = plt.subplots(1, 3, figsize=figsize, dpi=dpi)
    fig.suptitle(title, fontsize=13, fontweight="bold", y=1.02)

    panels = [
        ("norm_latency", "energy_score",
         "Norm Latency (lower=better)", "Energy Score [pJ] (lower=better)"),
        ("norm_latency", "total_area",
         "Norm Latency (lower=better)", "Total Area mm² (lower=better)"),
        ("energy_score", "total_area",
         "Energy Score [pJ] (lower=better)", "Total Area mm² (lower=better)"),
    ]

    for ax, (xcol, ycol, xlabel, ylabel) in zip(axes, panels):
        ax.set_xlabel(xlabel, fontsize=9)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.grid(True, linestyle="--", alpha=0.35)

        for topo in topologies:
            row = df_v[df_v["topology"] == topo]
            x = float(row[xcol].iloc[0])
            y = float(row[ycol].iloc[0])
            on_front = bool(row["pareto_front_3d"].iloc[0])
            col = colours[topo]

            ms  = 12 if on_front else 7
            mrk = "*" if on_front else "o"
            edg = "black" if on_front else col
            lw  = 1.5 if on_front else 0.7

            ax.scatter(x, y, s=ms**2, c=col, marker=mrk,
                       edgecolors=edg, linewidths=lw, label=topo,
                       zorder=5 if on_front else 3)
            ax.annotate(topo, xy=(x, y), xytext=(4, 3),
                        textcoords="offset points",
                        fontsize=6, color=col, alpha=0.85)

    # Legend on first panel only
    handles, labels = axes[0].get_legend_handles_labels()
    axes[0].legend(handles, labels, fontsize=6, framealpha=0.8,
                   loc="upper right", ncol=2)

    fig.tight_layout()
    return fig, axes


# ---------------------------------------------------------------------------
# Self-check
# ---------------------------------------------------------------------------

def _selfcheck():
    """Smoke-test both plot functions with synthetic data."""
    import io

    sample = pd.DataFrame([
        {"topology": "fly4",     "norm_latency": 0.69, "energy_score": 41.0,
         "total_area": 0.125, "pareto_front_3d": True},
        {"topology": "cmesh",    "norm_latency": 0.74, "energy_score": 41.3,
         "total_area": 0.187, "pareto_front_3d": True},
        {"topology": "fattree",  "norm_latency": 0.78, "energy_score": 50.0,
         "total_area": 0.236, "pareto_front_3d": True},
        {"topology": "flatfly",  "norm_latency": 0.89, "energy_score": 51.1,
         "total_area": 0.631, "pareto_front_3d": False},
        {"topology": "mesh4x4",  "norm_latency": 1.00, "energy_score": 71.4,
         "total_area": 0.331, "pareto_front_3d": False},
        {"topology": "torus4x4", "norm_latency": 0.96, "energy_score": 60.3,
         "total_area": 0.368, "pareto_front_3d": False},
    ])

    # 3D scatter
    fig3d, _ = plot_pareto_3d(sample, dpi=72)
    buf = io.BytesIO()
    fig3d.savefig(buf, format="png")
    assert buf.tell() > 1000
    plt.close(fig3d)

    # 3 panel
    fig3p, axes = plot_pareto_3panel(sample, dpi=72)
    assert len(axes) == 3
    buf2 = io.BytesIO()
    fig3p.savefig(buf2, format="png")
    assert buf2.tell() > 1000
    plt.close(fig3p)

    print("selfcheck OK")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sweep",    default=None, help="path to topology_sweep.json")
    ap.add_argument("--out",      default=None,
                    help="output image path (default: output/pareto_3d.png)")
    ap.add_argument(
    "--3d",
    action="store_true",
    help="generate matplotlib 3D scatter plot (default)",
    )
    ap.add_argument("--3panel",   dest="three_panel", action="store_true",
                    help="generate 3-panel projection instead of 3D scatter")
    ap.add_argument("--pj",       type=float, default=20.5)
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    sys.path.insert(0, str(HERE))
    from pareto import build_pareto_df, pareto_front_3d

    sweep = Path(args.sweep) if args.sweep else None
    df    = build_pareto_df(sweep, pj_per_hop=args.pj)
    df3   = pareto_front_3d(df)

    # Carry forward 2D front flag too
    from pareto import pareto_front_2d
    df3 = pareto_front_2d(df3)

    if args.three_panel:
        fig, _ = plot_pareto_3panel(df3)
        suffix = "pareto_3panel.png"
    else:
        if not _AXES3D_OK:
            print("  ⚠  Axes3D unavailable — falling back to --3panel (2D projections).")
            print("     Fix: pip install --upgrade --force-reinstall matplotlib")
            fig, _ = plot_pareto_3panel(df3)
            suffix = "pareto_3panel.png"
        else:
            fig, _ = plot_pareto_3d(df3)
            suffix = "pareto_3d.png"

    out = Path(args.out) if args.out else OUTPUT / suffix
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"  figure → {out}")

    # Write CSV with 3D front flag
    csv_out = OUTPUT / "pareto_3d.csv"
    df3.to_csv(csv_out, index=False)
    print(f"  CSV    → {csv_out}")

    front3_topos = df3[df3["pareto_front_3d"]]["topology"].tolist()
    print(f"  3D Pareto-optimal: {', '.join(front3_topos)}")


if __name__ == "__main__":
    main()
