#!/usr/bin/env python3
"""PA-24 — Publication-quality figures using real experiment data only.

No synthetic data are generated. Missing required real inputs cause a clear
error instead of silently fabricating a figure.

Outputs PDF and SVG files under output/paper/:
  fig1_latency
  fig2_energy
  fig3_pareto_3d
  fig4_scaling_workloads
  fig5_traffic_heatmap
  fig6_robustness

Usage:
  MPLBACKEND=Agg python3 scripts/paper_figures.py
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
TRACK = HERE.parent
RESULTS = TRACK / "results"
OUTPUT = TRACK / "output"
PAPER = OUTPUT / "paper"

sys.path.insert(0, str(HERE))
from analysis import load_sweep_df

PALETTE = ["#1f4e79", "#d55e00", "#009e73", "#cc79a7", "#0072b2", "#6a3d9a"]
MARKERS = ["o", "s", "^", "D", "P", "X"]


def set_style():
    mpl.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.labelsize": 10,
        "axes.titlesize": 11,
        "legend.fontsize": 8,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "axes.linewidth": 0.8,
        "lines.linewidth": 1.8,
        "lines.markersize": 5,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "savefig.dpi": 300,
    })


def require(path: Path, label: str):
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


def ok_df(path: Path):
    df = load_sweep_df(path)
    return df[(df["status"] == "ok") & df["latency_cycles"].notna()].copy()


def characteristic(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    rows = []
    for topo, grp in df.groupby("topology"):
        g = grp.sort_values("injection_rate")
        valid = g[g[metric].notna()]
        if valid.empty:
            continue
        r = valid.iloc[0]
        rows.append({
            "topology": topo,
            "injection_rate": float(r["injection_rate"]),
            metric: float(r[metric]),
        })
    return pd.DataFrame(rows)


def save(fig, stem):
    PAPER.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "svg"):
        fig.savefig(PAPER / f"{stem}.{ext}", bbox_inches="tight")
    plt.close(fig)
    print(f"  {stem} → {PAPER / (stem + '.pdf')} and .svg")


def fig_latency(df):
    fig, ax = plt.subplots(figsize=(7.0, 4.6))
    for i, topo in enumerate(sorted(df["topology"].unique())):
        g = df[df["topology"] == topo].sort_values("injection_rate")
        ax.plot(g["injection_rate"], g["latency_cycles"],
                label=topo, marker=MARKERS[i % len(MARKERS)],
                color=PALETTE[i % len(PALETTE)])
    ax.set_xlabel("Injection rate (flits/node/cycle)")
    ax.set_ylabel("Average packet latency (cycles)")
    ax.set_title("Latency–throughput characteristics across topologies")
    ax.grid(True, alpha=0.25)
    ax.legend(ncol=2, frameon=False)
    save(fig, "fig1_latency")


def fig_energy(df):
    if df["total_power"].notna().sum() == 0:
        raise ValueError("fig2 requires real BookSim total_power values; none are present.")

    d = characteristic(df, "total_power").sort_values("total_power")
    fig, ax = plt.subplots(figsize=(6.8, 4.4))
    bars = ax.bar(d["topology"], d["total_power"])
    for b, v in zip(bars, d["total_power"]):
        ax.text(b.get_x() + b.get_width()/2, v, f"{v:.3g}",
                ha="center", va="bottom", fontsize=8)
    ax.set_xlabel("Topology")
    ax.set_ylabel("Total power (BookSim units)")
    ax.set_title("Characteristic total power at lowest valid injection rate")
    ax.tick_params(axis="x", rotation=25)
    ax.grid(axis="y", alpha=0.25)
    save(fig, "fig2_energy")


def pareto_frame():
    csv = OUTPUT / "pareto_3d.csv"
    if csv.exists():
        d = pd.read_csv(csv)
    else:
        from pareto import build_pareto_df, pareto_front_3d
        d = pareto_front_3d(build_pareto_df(RESULTS / "topology_sweep.json"))
    needed = ["topology", "norm_latency", "energy_score", "total_area"]
    missing = [c for c in needed if c not in d.columns]
    if missing:
        raise ValueError(f"fig3 missing Pareto columns: {missing}")
    if "pareto_front_3d" not in d.columns:
        from pareto import pareto_front_3d
        d = pareto_front_3d(d)
    d = d.dropna(subset=needed).copy()
    if d.empty:
        raise ValueError("fig3 has no complete real latency/energy/area points.")
    return d


def fig_pareto_3d():
    d = pareto_frame()
    fig = plt.figure(figsize=(7.2, 5.6))
    ax = fig.add_subplot(111, projection="3d")

    for i, (_, r) in enumerate(d.sort_values("topology").iterrows()):
        front = bool(r["pareto_front_3d"])
        ax.scatter(r["norm_latency"], r["energy_score"], r["total_area"],
                   s=110 if front else 55,
                   marker="*" if front else "o",
                   color=PALETTE[i % len(PALETTE)],
                   edgecolors="black" if front else "none")
        ax.text(r["norm_latency"], r["energy_score"], r["total_area"],
                " " + str(r["topology"]), fontsize=7)

    front = d[d["pareto_front_3d"]].sort_values(["norm_latency", "total_area"])
    if len(front) > 1:
        ax.plot(front["norm_latency"], front["energy_score"], front["total_area"],
                linestyle="--", linewidth=1.0, color="black", alpha=0.5)

    ax.set_xlabel("Normalized latency")
    ax.set_ylabel("Energy score (pJ)")
    ax.set_zlabel("Total area (mm²)")
    ax.set_title("Three-objective Pareto space: latency, energy, and area")
    save(fig, "fig3_pareto_3d")


def fig_scaling(s7, s70):
    c7 = characteristic(s7, "latency_cycles").set_index("topology")
    c70 = characteristic(s70, "latency_cycles").set_index("topology")
    common = sorted(set(c7.index) & set(c70.index))
    if not common:
        raise ValueError("fig4 has no common topologies between 7B and 70B sweeps.")

    fig, ax = plt.subplots(figsize=(7.0, 4.8))
    for i, topo in enumerate(common):
        y = [c7.loc[topo, "latency_cycles"], c70.loc[topo, "latency_cycles"]]
        ax.plot([0, 1], y, marker=MARKERS[i % len(MARKERS)],
                color=PALETTE[i % len(PALETTE)], label=topo)
    ax.set_xticks([0, 1], ["7B workload", "70B workload"])
    ax.set_ylabel("Characteristic latency (cycles)")
    ax.set_title("Topology sensitivity across corrected 7B and 70B workloads")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(ncol=2, frameon=False)
    save(fig, "fig4_scaling_workloads")


def load_matrix(path):
    return np.loadtxt(require(path, "Traffic matrix"), comments="#")


def fig_heatmap(m7, m70):
    fig, axes = plt.subplots(1, 2, figsize=(9.0, 4.0), constrained_layout=True)
    for ax, mat, name in zip(axes, [m7, m70], ["7B workload", "70B workload"]):
        im = ax.imshow(mat, aspect="equal")
        ax.set_title(name)
        ax.set_xlabel("Destination tile")
        ax.set_ylabel("Source tile")
        fig.colorbar(im, ax=ax, shrink=0.82, label="Traffic-matrix weight")
    save(fig, "fig5_traffic_heatmap")


def fig_robustness():
    path = require(OUTPUT / "robustness_score.csv", "Real robustness score CSV")
    d = pd.read_csv(path)
    needed = {"topology", "wins", "total_matrices", "robustness_score"}
    if not needed.issubset(d.columns):
        raise ValueError(f"fig6 robustness CSV missing columns: {sorted(needed - set(d.columns))}")
    if (d["total_matrices"] <= 0).all():
        raise ValueError("fig6 robustness CSV contains no real matrix runs.")

    d = d.sort_values("robustness_score")
    fig, ax = plt.subplots(figsize=(6.8, 4.4))
    bars = ax.barh(d["topology"], d["robustness_score"])
    for bar, score, wins, total in zip(bars, d["robustness_score"], d["wins"], d["total_matrices"]):
        ax.text(bar.get_width() + 0.01, bar.get_y() + bar.get_height()/2,
                f"{score:.1%} ({int(wins)}/{int(total)})",
                va="center", fontsize=8)
    ax.set_xlabel("Robustness score (win share)")
    ax.set_title("Robustness across real traffic-matrix experiments")
    ax.set_xlim(0, min(1.15, max(1.0, float(d["robustness_score"].max()) + 0.15)))
    ax.grid(axis="x", alpha=0.25)
    save(fig, "fig6_robustness")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", default=str(RESULTS / "topology_sweep.json"))
    ap.add_argument("--sweep-7b", default=str(RESULTS / "topology_sweep_7b.json"))
    ap.add_argument("--sweep-70b", default=str(RESULTS / "topology_sweep_70b.json"))
    ap.add_argument("--matrix-7b", default=str(RESULTS / "traffic_matrix_7b.txt"))
    ap.add_argument("--matrix-70b", default=str(RESULTS / "traffic_matrix_70b.txt"))
    args = ap.parse_args()

    set_style()
    sweep = require(Path(args.sweep), "Primary real sweep")
    s7p = require(Path(args.sweep_7b), "7B real sweep")
    s70p = require(Path(args.sweep_70b), "70B real sweep")

    df = ok_df(sweep)
    s7 = ok_df(s7p)
    s70 = ok_df(s70p)
    if df.empty or s7.empty or s70.empty:
        raise ValueError("One or more required sweeps contain no real converged rows.")

    fig_latency(df)
    fig_energy(df)
    fig_pareto_3d()
    fig_scaling(s7, s70)
    fig_heatmap(load_matrix(Path(args.matrix_7b)), load_matrix(Path(args.matrix_70b)))
    fig_robustness()
    print("  PA-24 complete: all six figures exported from real data only.")


if __name__ == "__main__":
    main()
