#!/usr/bin/env python3
"""PA-20 — Topology stability metric: % of traffic patterns where same topology wins.

Computes a "stability score" per topology:
  stability_score(T) = fraction of traffic patterns where T is on the Pareto front

Across traffic patterns (batch size, context length, model size sweeps), we ask:
  "For what fraction of operating conditions does topology T stay Pareto-optimal?"

A topology with stability_score = 1.0 is always on the Pareto front regardless
of the traffic pattern. A topology with 0.0 never wins anywhere.

Input
-----
A directory of sweep JSON files, each corresponding to one traffic pattern.
File naming convention: topology_sweep_<label>.json
  e.g. topology_sweep_batch1.json, topology_sweep_context4096.json

If no sweep directory is supplied, the script generates synthetic pattern
variation by perturbing the existing sweep with small noise to demonstrate
the stability metric. (Clearly labelled as synthetic.)

Usage
-----
    python3 scripts/stability.py                        # synthetic demo
    python3 scripts/stability.py --sweep-dir /path      # real multi-pattern sweeps
    python3 scripts/stability.py --selfcheck

API
---
    from scripts.stability import compute_stability_scores
"""

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
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
# Core stability computation
# ---------------------------------------------------------------------------

def compute_stability_scores(
    pattern_dfs: list[tuple[str, pd.DataFrame]],
    pj_per_hop: float = 20.5,
) -> pd.DataFrame:
    """Compute Pareto-front stability scores across traffic patterns.

    Parameters
    ----------
    pattern_dfs : list of (label, DataFrame) pairs.
                  Each DataFrame has columns: topology, norm_latency, energy_score
                  (one row per topology — the zero-load operating point).
    pj_per_hop  : used if energy_score is not pre-computed.

    Returns
    -------
    DataFrame with columns:
        topology, wins, total_patterns, stability_score (0.0–1.0),
        patterns_on_front (list of labels where this topology is Pareto-optimal)
    Sorted by stability_score descending.
    """
    sys.path.insert(0, str(HERE))
    from pareto import pareto_front_2d

    all_topos = set()
    for _, df in pattern_dfs:
        all_topos.update(df["topology"].tolist())

    wins: dict[str, int] = {t: 0 for t in all_topos}
    on_front: dict[str, list[str]] = {t: [] for t in all_topos}
    total = len(pattern_dfs)

    for label, df in pattern_dfs:
        result = pareto_front_2d(df)
        front_topos = result[result["pareto_front"]]["topology"].tolist()
        for t in front_topos:
            wins[t] = wins.get(t, 0) + 1
            on_front.setdefault(t, []).append(label)

    rows = []
    for topo in sorted(all_topos):
        w = wins.get(topo, 0)
        rows.append({
            "topology":          topo,
            "wins":              w,
            "total_patterns":    total,
            "stability_score":   round(w / total, 4) if total > 0 else 0.0,
            "patterns_on_front": "; ".join(on_front.get(topo, [])),
        })

    return (pd.DataFrame(rows)
            .sort_values("stability_score", ascending=False)
            .reset_index(drop=True))


# ---------------------------------------------------------------------------
# Synthetic pattern generation (demo when real multi-pattern data unavailable)
# ---------------------------------------------------------------------------

def _make_synthetic_patterns(
    df_base: pd.DataFrame,
    n_patterns: int = 10,
    noise_scale: float = 0.05,
    seed: int = 42,
) -> list[tuple[str, pd.DataFrame]]:
    """Perturb base Pareto data to simulate different traffic patterns.

    Each pattern adds Gaussian noise to norm_latency and energy_score
    (scale = noise_scale × original value). This mimics variation across
    batch sizes / context lengths / model configurations.
    """
    rng = np.random.default_rng(seed)
    patterns = []

    for i in range(n_patterns):
        label = f"pattern_{i+1:02d}"
        df_p  = df_base.copy()

        for col in ("norm_latency", "energy_score"):
            valid = df_p[col].notna()
            noise = rng.normal(0, noise_scale, valid.sum())
            df_p.loc[valid, col] = (df_p.loc[valid, col] * (1.0 + noise)).clip(lower=0.01)

        patterns.append((label, df_p))

    return patterns


# ---------------------------------------------------------------------------
# Bar chart
# ---------------------------------------------------------------------------

def plot_stability_bar(
    df: pd.DataFrame,
    title: str = "PA-20: Topology Stability Score",
    figsize: tuple = (10, 6),
    dpi: int = 150,
) -> tuple["plt.Figure", "plt.Axes"]:
    """Horizontal bar chart of stability scores per topology."""
    df_plot = df.sort_values("stability_score")
    topos   = df_plot["topology"].tolist()
    scores  = df_plot["stability_score"].tolist()
    cols    = [PALETTE[i % len(PALETTE)] for i in range(len(topos))]

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    bars = ax.barh(topos, scores, color=cols, edgecolor="white",
                   linewidth=0.7, height=0.65)

    # Annotate bars with score
    for bar, score in zip(bars, scores):
        ax.text(bar.get_width() + 0.01, bar.get_y() + bar.get_height() / 2,
                f"{score:.0%}", va="center", fontsize=9)

    ax.set_xlabel("Stability Score (fraction of patterns on Pareto front)", fontsize=11)
    ax.set_title(title, fontsize=13, fontweight="bold", pad=10)
    ax.set_xlim(0, 1.12)
    ax.axvline(x=1.0, color="#333333", linewidth=0.8, linestyle="--", alpha=0.5)
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    return fig, ax


# ---------------------------------------------------------------------------
# Selfcheck
# ---------------------------------------------------------------------------

def _selfcheck():
    """Regression test: stability scores sum correctly."""
    import io

    # Synthetic patterns: topo A always wins, B wins half the time, C never
    patterns = []
    for i in range(4):
        df = pd.DataFrame([
            {"topology": "A", "norm_latency": 0.5, "energy_score": 10.0},
            {"topology": "B", "norm_latency": 0.7 + i * 0.1, "energy_score": 40.0},
            {"topology": "C", "norm_latency": 1.2, "energy_score": 80.0},
        ])
        patterns.append((f"p{i+1}", df))

    result = compute_stability_scores(patterns)

    # A should have stability_score = 1.0 (always on front — best on both axes)
    a_score = float(result[result["topology"] == "A"]["stability_score"].iloc[0])
    assert a_score == 1.0, f"A should always be on front, got {a_score}"

    # C should have score = 0.0 (always dominated)
    c_score = float(result[result["topology"] == "C"]["stability_score"].iloc[0])
    assert c_score == 0.0, f"C should never be on front, got {c_score}"

    # Bar chart smoke-test
    fig, ax = plot_stability_bar(result, dpi=72)
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    assert buf.tell() > 500
    plt.close(fig)

    print("selfcheck OK")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sweep-dir", default=None,
                    help="directory with topology_sweep_*.json files")
    ap.add_argument("--sweep",     default=None,
                    help="base sweep JSON for synthetic demo")
    ap.add_argument("--n-patterns", type=int, default=10,
                    help="number of synthetic patterns to generate (default: 10)")
    ap.add_argument("--noise",      type=float, default=0.05,
                    help="noise scale for synthetic patterns (default: 0.05)")
    ap.add_argument("--pj",         type=float, default=20.5)
    ap.add_argument("--out",        default=None,
                    help="output image (default: output/stability_score.png)")
    ap.add_argument("--selfcheck",  action="store_true")
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    sys.path.insert(0, str(HERE))
    from pareto import build_pareto_df

    if args.sweep_dir:
        # Load real multi-pattern sweeps
        sweep_dir = Path(args.sweep_dir)
        pattern_files = sorted(sweep_dir.glob("topology_sweep_*.json"))
        if not pattern_files:
            raise SystemExit(f"No topology_sweep_*.json files found in {sweep_dir}")

        patterns = []
        for pf in pattern_files:
            label = pf.stem.replace("topology_sweep_", "")
            df_p  = build_pareto_df(pf, pj_per_hop=args.pj)
            patterns.append((label, df_p))

        print(f"  Loaded {len(patterns)} real traffic patterns from {sweep_dir}")
        synthetic = False

    else:
        # Synthetic demo
        sweep = Path(args.sweep) if args.sweep else None
        df_base = build_pareto_df(sweep, pj_per_hop=args.pj)
        patterns = _make_synthetic_patterns(
            df_base, n_patterns=args.n_patterns, noise_scale=args.noise)
        print(f"  ⚠  No --sweep-dir provided. Generated {args.n_patterns} synthetic "
              f"patterns (noise={args.noise:.0%}). Use --sweep-dir with real "
              f"batch/context sweep JSONs when available.")
        synthetic = True

    # Compute stability
    result = compute_stability_scores(patterns, pj_per_hop=args.pj)

    print(f"\n=== PA-20: Topology Stability Score "
          f"({'synthetic' if synthetic else 'real'} — {len(patterns)} patterns) ===\n")
    print(f"  {'topology':<20s} {'wins':>5s} {'total':>6s} {'score':>7s}")
    print(f"  {'-'*20} {'-'*5} {'-'*6} {'-'*7}")
    for _, r in result.iterrows():
        print(f"  {r['topology']:<20s} {r['wins']:>5d} {r['total_patterns']:>6d} "
              f"  {r['stability_score']:>5.1%}")

    # Write CSV
    csv_out = OUTPUT / "stability_score.csv"
    csv_out.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(csv_out, index=False)
    print(f"\n  → {csv_out}")

    # Plot
    fig, _ = plot_stability_bar(result)
    out = Path(args.out) if args.out else OUTPUT / "stability_score.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"  figure → {out}")


if __name__ == "__main__":
    main()
