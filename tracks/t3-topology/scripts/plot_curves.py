#!/usr/bin/env python3
"""PA-03 — Latency-throughput curves with labelled saturation points.

Reusable plot_curves() function that mirrors the dashboard's Plotly logic but
outputs publication-quality matplotlib figures (PNG/SVG/PDF).

Features
--------
* Cliff-detection saturation (latency > k × zero-load latency; default k=2.0,
  matching generate_dashboard.py's saturation_point()).
* Dotted vertical saturation-point lines with per-topology labels.
* Optional secondary y-axis for hops_avg (energy proxy).
* Accepts either a raw sweep JSON path or a pandas DataFrame produced by
  analysis.load_sweep_df() / aggregate.load_aggregate_df().

Usage
-----
    python3 scripts/plot_curves.py                       # → results/latency_curves.png
    python3 scripts/plot_curves.py --out /tmp/fig.pdf
    python3 scripts/plot_curves.py --sweep results/topology_sweep.json
    python3 scripts/plot_curves.py --selfcheck

API
---
    from scripts.plot_curves import plot_curves

    fig, ax = plot_curves(df)           # pass in a sweep DataFrame
    fig.savefig("paper_fig.pdf", bbox_inches="tight")
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import warnings

# The image carries two matplotlib installs (apt + pip); the 3D toolkit
# import guard warns on every run although all our charts are 2D.
warnings.filterwarnings("ignore", message="Unable to import Axes3D")

import matplotlib.pyplot as plt
import matplotlib.lines as mlines
import pandas as pd
import numpy as np

HERE    = Path(__file__).parent
TRACK   = HERE.parent
RESULTS = TRACK / "results"

sys.path.insert(0, str(HERE))
from lib.t3load import PALETTE, find_sweep, saturation_point  # noqa: E402
# NOTE (Phase 2b): PALETTE is now the canonical compare_curves 10-color
# tab10 set from lib.t3load (previously a muted seaborn-style set here).
# Colors change; curve data does not.


# ---------------------------------------------------------------------------
# Saturation detection (delegates to lib.t3load — single implementation)
# ---------------------------------------------------------------------------

def _saturation_point(pts: pd.DataFrame, k: float = 2.0) -> Optional[float]:
    """Return the injection rate where latency first exceeds k × zero-load.

    Delegates to lib.t3load.saturation_point (single implementation).
    Kept as a thin wrapper for backward compat (selfcheck + external
    callers import this name).

    Parameters
    ----------
    pts : DataFrame slice for one topology, must have columns
          injection_rate and latency_cycles, sorted ascending by rate.
    k   : multiplier threshold (default 2.0 — same as dashboard).

    Returns
    -------
    float | None
    """
    return saturation_point(pts, k=k)


# ---------------------------------------------------------------------------
# Core plot function  (PA-03 deliverable)
# ---------------------------------------------------------------------------

def plot_curves(
    data:          "pd.DataFrame | str | Path",
    k:             float  = 2.0,
    figsize:       tuple  = (10, 6),
    title:         str    = "Latency vs Injection Rate",
    show_hops:     bool   = False,
    palette:       list   = PALETTE,
    dpi:           int    = 150,
    sat_alpha:     float  = 0.6,
    marker:        str    = "o",
    markersize:    int    = 5,
    linewidth:     float  = 1.8,
) -> tuple["plt.Figure", "plt.Axes"]:
    """Plot latency-throughput curves with labelled saturation points.

    Parameters
    ----------
    data       : pandas DataFrame from analysis.load_sweep_df(), OR a path to
                 a topology_sweep.json file.
    k          : saturation threshold multiplier (latency > k × zero-load).
    figsize    : (width, height) inches.
    title      : figure title.
    show_hops  : if True, add a secondary y-axis for hops_avg (energy proxy).
    palette    : list of hex colour strings.
    dpi        : figure DPI.
    sat_alpha  : alpha for saturation marker and dotted line.
    marker     : matplotlib marker style.
    markersize : marker size.
    linewidth  : line width.

    Returns
    -------
    (fig, ax) — matplotlib Figure and primary Axes.
    """
    # ---- load data --------------------------------------------------------
    if isinstance(data, (str, Path)):
        p = Path(data)
        if not p.exists():
            raise FileNotFoundError(f"No sweep file at {p}")
        sys.path.insert(0, str(HERE))
        from analysis import load_sweep_df
        df = load_sweep_df(p)
    else:
        df = data.copy()

    df_ok = df[df["status"] == "ok"].copy()
    if df_ok.empty:
        raise ValueError("No valid data rows (status='ok') in the sweep.")

    topologies = sorted(df_ok["topology"].unique())
    colours    = {t: palette[i % len(palette)] for i, t in enumerate(topologies)}

    # ---- figure setup -----------------------------------------------------
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    ax.set_xlabel("Injection Rate (flits/cycle/node)", fontsize=12)
    ax.set_ylabel("Avg Packet Latency (cycles)",       fontsize=12)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    ax.grid(True, linestyle="--", alpha=0.4)

    ax2: Optional["plt.Axes"] = None
    if show_hops and "hops_avg" in df_ok.columns and df_ok["hops_avg"].notna().any():
        ax2 = ax.twinx()
        ax2.set_ylabel("Avg Hops (energy proxy)", fontsize=11, color="#555555")
        ax2.tick_params(axis="y", labelcolor="#555555")

    sat_handles = []  # legend entry for saturation markers

    # ---- per-topology traces ----------------------------------------------
    for topo in topologies:
        grp = df_ok[df_ok["topology"] == topo].sort_values("injection_rate")
        x   = grp["injection_rate"].to_numpy()
        y   = grp["latency_cycles"].to_numpy()
        col = colours[topo]

        ax.plot(x, y, color=col, marker=marker, markersize=markersize,
                linewidth=linewidth, label=topo, zorder=3)

        # Saturation point
        sat = _saturation_point(grp, k=k)
        if sat is not None:
            sat_lat = float(
                grp.loc[grp["injection_rate"] == sat, "latency_cycles"].iloc[0]
                if sat in grp["injection_rate"].values
                else np.interp(sat, x, y)
            )
            # Dotted vertical line up to the curve
            ax.axvline(x=sat, color=col, linestyle=":", linewidth=1.2,
                       alpha=sat_alpha, zorder=2)
            # Diamond marker at saturation point
            ax.plot(sat, sat_lat, marker="D", color=col, markersize=8,
                    alpha=sat_alpha, zorder=4, linestyle="None")
            # Label slightly above the marker
            ax.annotate(
                f"{topo}\nsat@{sat:.3f}",
                xy=(sat, sat_lat),
                xytext=(6, 6),
                textcoords="offset points",
                fontsize=7,
                color=col,
                alpha=0.85,
            )

        # Optional hops secondary axis
        if ax2 is not None:
            hops = grp["hops_avg"].to_numpy(dtype=float)
            valid = ~np.isnan(hops)
            if valid.any():
                ax2.plot(x[valid], hops[valid], color=col, linewidth=0.9,
                         linestyle="--", alpha=0.55, zorder=1)

    # ---- legend -----------------------------------------------------------
    sat_proxy = mlines.Line2D([], [], color="grey", linestyle=":",
                              marker="D", markersize=6, label=f"Sat. point (k={k})")
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles + [sat_proxy],
              labels  + [sat_proxy.get_label()],
              loc="upper left", fontsize=9, framealpha=0.8,
              ncol=max(1, len(topologies) // 8))

    if ax2 is not None:
        _h2, _l2 = ax2.get_legend_handles_labels()
        if _h2:  # twin axis often carries unlabeled artists; empty legend warns
            ax2.legend(loc="upper right", fontsize=8, framealpha=0.7)

    fig.tight_layout()
    return fig, ax


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _selfcheck():
    """Smoke-test plot_curves with in-memory synthetic data."""
    import io

    sample = pd.DataFrame([
        {"topology": "mesh4x4",   "injection_rate": r, "latency_cycles": lc,
         "hops_avg": h, "energy_proxy": h * 128, "status": "ok"}
        for r, lc, h in [
            (0.002, 20.0, 2.78), (0.005, 20.7, 2.88),
            (0.01,  21.9, 2.92), (0.02,  23.2, 2.84), (0.03, 164.0, 2.95)
        ]
    ] + [
        {"topology": "fattree16", "injection_rate": r, "latency_cycles": lc,
         "hops_avg": h, "energy_proxy": h * 128, "status": "ok"}
        for r, lc, h in [
            (0.002, 14.8, 1.74), (0.005, 15.1, 1.73),
            (0.01,  16.0, 1.78), (0.02,  17.8, 1.76), (0.03, 175.0, 1.76)
        ]
    ])
    sample["area_mm2"] = None
    sample["traffic"]  = "test"

    fig, ax = plot_curves(sample, k=2.0, show_hops=True, dpi=72)

    # Check saturation logic: mesh4x4 — zero_load=20, threshold=40, sat@0.03 (164>40)
    grp = sample[sample["topology"] == "mesh4x4"].sort_values("injection_rate")
    sat = _saturation_point(grp, k=2.0)
    assert sat == 0.03, f"expected sat=0.03, got {sat}"

    # fattree: zero_load=14.8, threshold=29.6 — 175>29.6 → sat@0.03
    grp2 = sample[sample["topology"] == "fattree16"].sort_values("injection_rate")
    sat2 = _saturation_point(grp2, k=2.0)
    assert sat2 == 0.03, f"expected sat2=0.03, got {sat2}"

    # Figure should have two lines (one per topology)
    lines = [l for l in ax.get_lines() if l.get_label() in ("mesh4x4", "fattree16")]
    assert len(lines) == 2, f"expected 2 topology lines, got {len(lines)}"

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    assert buf.tell() > 1000, "figure too small — likely empty"
    plt.close(fig)

    print("selfcheck OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sweep", default=None,
                    help="path to topology_sweep.json (default: results/topology_sweep.json)")
    ap.add_argument("--out", default=None,
                    help="output image path (default: results/latency_curves.png)")
    ap.add_argument("--k", type=float, default=2.0,
                    help="saturation threshold multiplier (default 2.0)")
    ap.add_argument("--hops", action="store_true",
                    help="add secondary y-axis for hops_avg")
    ap.add_argument("--title", default="Latency vs Injection Rate",
                    help="plot title")
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    import os
    config = os.environ.get("CONFIG", "baseline")

    if args.sweep:
        sweep = Path(args.sweep)
    else:
        # Single discovery via lib.t3load.find_sweep (canonical
        # CONFIG/T3_RESULTS env walk, plot_curves order). Falls back to the
        # canonical non-existing path for error-message parity.
        found = find_sweep()
        sweep = found if found is not None else RESULTS / config / "topology_sweep.json"

    out = Path(args.out) if args.out else sweep.parent / "latency_curves.png"

    try:
        fig, ax = plot_curves(sweep, k=args.k, show_hops=args.hops, title=args.title)
    except (FileNotFoundError, ValueError, OSError, KeyError, json.JSONDecodeError) as e:
        print(f"  ✗ plot failed: {e}", file=sys.stderr)
        sys.exit(1)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"  figure → {out}")


if __name__ == "__main__":
    main()
