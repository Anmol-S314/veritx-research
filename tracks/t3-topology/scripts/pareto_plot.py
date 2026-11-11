#!/usr/bin/env python3
"""PA-17 — Replot all results on energy axes: x=norm_latency, y=energy_score.

Generates a 2D Pareto plot (Week-5 axis update):
  x-axis : norm_latency  — latency relative to mesh4x4 (lower = better)
  y-axis : energy_score  — hops_avg × pJ/hop  (lower = better)

Each topology is plotted as a labelled scatter point. Pareto-front points
are highlighted and connected by a step-wise Pareto envelope.

Usage
-----
    python3 scripts/pareto_plot.py                   # → output/pareto_2d.png
    python3 scripts/pareto_plot.py --out /tmp/p.pdf
    python3 scripts/pareto_plot.py --selfcheck

API
---
    from scripts.pareto_plot import plot_pareto_2d
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

# Curated palette (consistent with plot_curves.py)
PALETTE = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52",
    "#8172B2", "#937860", "#DA8BC3", "#8C8C8C",
    "#CCB974", "#64B5CD",
]


def plot_pareto_2d(
    df: pd.DataFrame,
    title: str = "PA-17: 2D Pareto Front — Latency vs Energy Score",
    figsize: tuple = (10, 7),
    dpi: int = 150,
    annotate: bool = True,
) -> tuple["plt.Figure", "plt.Axes"]:
    """Plot 2D Pareto scatter with front envelope.

    Parameters
    ----------
    df       : DataFrame with columns norm_latency, energy_score, topology,
               pareto_front (bool).
    title    : figure title.
    figsize  : (width, height) in inches.
    dpi      : output DPI.
    annotate : if True, annotate each point with the topology name.

    Returns
    -------
    (fig, ax) — matplotlib Figure and Axes.
    """
    valid = df[["norm_latency", "energy_score"]].notna().all(axis=1)
    df_v = df[valid].copy()

    topologies = sorted(df_v["topology"].unique())
    colours = {t: PALETTE[i % len(PALETTE)] for i, t in enumerate(topologies)}

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    ax.set_xlabel("Normalised Latency (vs mesh4x4, lower = better)",
                  fontsize=12, labelpad=8)
    ax.set_ylabel("Energy Score — hops × pJ/hop  [pJ/packet]  (lower = better)",
                  fontsize=12, labelpad=8)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    ax.grid(True, linestyle="--", alpha=0.35)

    # ---- scatter all topologies -------------------------------------------
    for topo in topologies:
        row = df_v[df_v["topology"] == topo]
        x = float(row["norm_latency"].iloc[0])
        y = float(row["energy_score"].iloc[0])
        on_front = bool(row["pareto_front"].iloc[0])
        col = colours[topo]

        marker = "★" if on_front else "o"
        ms = 14 if on_front else 9
        zorder = 5 if on_front else 3
        edge = "black" if on_front else col

        ax.scatter(x, y, s=ms**2, color=col, edgecolors=edge,
                   linewidths=1.5 if on_front else 0.8,
                   zorder=zorder, label=topo)

        if annotate:
            offset = (7, 6) if on_front else (5, 4)
            ax.annotate(
                topo,
                xy=(x, y),
                xytext=offset,
                textcoords="offset points",
                fontsize=8 if on_front else 7,
                fontweight="bold" if on_front else "normal",
                color=col,
                alpha=0.9,
            )

    # ---- Pareto envelope (step-wise staircase) ----------------------------
    front = df_v[df_v["pareto_front"]].sort_values("norm_latency")
    if len(front) >= 2:
        fx = front["norm_latency"].tolist()
        fy = front["energy_score"].tolist()

        # Staircase: walk along the Pareto front
        sx, sy = [fx[0]], [fy[0]]
        for i in range(1, len(fx)):
            sx.append(fx[i])
            sy.append(fy[i - 1])   # horizontal step
            sx.append(fx[i])
            sy.append(fy[i])       # vertical step

        ax.plot(sx, sy, color="#333333", linewidth=1.5, linestyle="--",
                alpha=0.6, zorder=2, label="Pareto envelope")

    # ---- mesh4x4 reference cross ------------------------------------------
    mesh_row = df_v[df_v["topology"] == "mesh4x4"]
    if not mesh_row.empty:
        mx = float(mesh_row["norm_latency"].iloc[0])
        my = float(mesh_row["energy_score"].iloc[0])
        ax.axvline(x=mx, color="#888888", linewidth=1.0,
                   linestyle=":", alpha=0.5, zorder=1)
        ax.axhline(y=my, color="#888888", linewidth=1.0,
                   linestyle=":", alpha=0.5, zorder=1)

    # ---- corner annotation ------------------------------------------------
    ax.annotate(
        "← better latency",
        xy=(0.02, 0.04), xycoords="axes fraction",
        fontsize=8, color="#555555", style="italic",
    )
    ax.annotate(
        "↓ better energy",
        xy=(0.98, 0.96), xycoords="axes fraction",
        fontsize=8, color="#555555", style="italic",
        ha="right",
    )

    # ---- legend -----------------------------------------------------------
    front_patch = mpatches.Patch(facecolor="none", edgecolor="black",
                                  linewidth=1.5, label="Pareto-optimal (★)")
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(
        handles + [front_patch],
        labels + [front_patch.get_label()],
        loc="upper right", fontsize=8, framealpha=0.85,
        ncol=max(1, len(topologies) // 7),
    )

    fig.tight_layout()
    return fig, ax


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _selfcheck():
    """Smoke-test plot_pareto_2d with synthetic data."""
    import io

    sample = pd.DataFrame([
        {"topology": "fly4",    "norm_latency": 0.69, "energy_score": 41.0,
         "total_area": 0.125, "pareto_front": True},
        {"topology": "cmesh",   "norm_latency": 0.74, "energy_score": 41.3,
         "total_area": 0.187, "pareto_front": True},
        {"topology": "fattree", "norm_latency": 0.78, "energy_score": 50.0,
         "total_area": 0.236, "pareto_front": False},
        {"topology": "mesh4x4", "norm_latency": 1.00, "energy_score": 71.4,
         "total_area": 0.331, "pareto_front": False},
    ])

    fig, ax = plot_pareto_2d(sample, dpi=72)
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    assert buf.tell() > 1000, "figure too small"
    plt.close(fig)
    print("selfcheck OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sweep",  default=None, help="path to topology_sweep.json")
    ap.add_argument("--out",    default=None,
                    help="output image path (default: output/pareto_2d.png)")
    ap.add_argument("--pj",     type=float, default=20.5,
                    help="pJ per hop (default: 20.5)")
    ap.add_argument("--title",  default="PA-17: 2D Pareto Front — Latency vs Energy Score")
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    sys.path.insert(0, str(HERE))
    from pareto import build_pareto_df, pareto_front_2d

    sweep = Path(args.sweep) if args.sweep else None
    df    = build_pareto_df(sweep, pj_per_hop=args.pj)
    df2   = pareto_front_2d(df)

    fig, ax = plot_pareto_2d(df2, title=args.title)

    out = Path(args.out) if args.out else OUTPUT / "pareto_2d.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"  figure → {out}")

    front_topos = df2[df2["pareto_front"]]["topology"].tolist()
    print(f"  Pareto front: {', '.join(front_topos)}")


if __name__ == "__main__":
    main()
