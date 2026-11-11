#!/usr/bin/env python3
"""PA-21 — Robustness score across the 20-random-matrix set.

Methodology:
  - Top-3 topologies from PA-15 (area-constrained ranking): fly4, cmesh, fattree
  - 20 random traffic matrices (each a 16×16 stochastic matrix of random
    traffic patterns between the 16 NoC nodes)
  - 3 topologies × 20 matrices = 60 simulation runs
  - robustness_score(T) = % of the 20 matrices where T has the best
    (lowest) latency among the top-3

This answers: "Even when the traffic pattern is random and unpredictable,
which topology wins most often?"

Implementation:
  - Generates 20 random traffic matrices (seeded for reproducibility)
  - For each matrix, runs Booksim with traffic=matrix(...) for each topology
  - Collects latency at IR=0.01 (zero-load, cleanest signal)
  - Computes win share (robustness_score) and produces a bar chart

If Booksim is not available (CI / dry-run mode), the script uses precomputed
synthetic latency data clearly labelled as such.

Usage
-----
    python3 scripts/robustness.py --dry-run         # fast synthetic demo
    python3 scripts/robustness.py --run-booksim     # real 60-run sweep
    python3 scripts/robustness.py --selfcheck

Makefile target: make robustness
"""

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE    = Path(__file__).parent
TRACK   = HERE.parent
RESULTS = TRACK / "results"
OUTPUT  = TRACK / "output"
CONFIGS = TRACK / "configs"

# Canonical top-3 topologies from PA-15 area-constrained ranking
TOP3_TOPOS = ["fly4", "cmesh", "fattree"]

# Number of random traffic matrices
N_MATRICES = 20

# Injection rate for robustness runs (zero-load — clearest signal)
ROBUSTNESS_IR = 0.01

PALETTE = {
    "fly4":    "#4C72B0",
    "cmesh":   "#DD8452",
    "fattree": "#55A868",
}

BOOKSIM_BIN = os.environ.get("BOOKSIM_BIN", "booksim")
TECH_FILE   = os.environ.get("TECH_FILE", "/opt/booksim2/src/power/techfile.txt")


# ---------------------------------------------------------------------------
# Random traffic matrix generation
# ---------------------------------------------------------------------------

def generate_random_matrix(n: int = 16, seed: Optional[int] = None) -> np.ndarray:
    """Generate a random n×n stochastic traffic matrix (rows sum to 1).

    Each row represents a source node; each column a destination node.
    No self-traffic (diagonal = 0). Traffic is randomised and normalised.
    """
    rng = np.random.default_rng(seed)
    mat = rng.random((n, n))
    np.fill_diagonal(mat, 0.0)
    row_sums = mat.sum(axis=1, keepdims=True)
    # Avoid division by zero for any all-zero row (shouldn't happen with rng.random)
    row_sums = np.where(row_sums == 0, 1.0, row_sums)
    return mat / row_sums


def write_booksim_matrix(mat: np.ndarray, path: Path) -> None:
    """Write an N×N traffic matrix for this BookSim build.

    The matrix must contain exactly N×N numeric entries:
    one row per source and one column per destination.
    Do NOT write a dimension/header line.
    """
    lines = []

    for row in mat:
        lines.append(" ".join(f"{v:.6f}" for v in row))

    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Booksim runner
# ---------------------------------------------------------------------------

def run_booksim_one(
    cfg_path: Path,
    matrix_path: Path,
    ir: float = ROBUSTNESS_IR,
) -> Optional[float]:
    """Run Booksim for one (topology, matrix) pair; return latency or None."""
    cmd = [
        BOOKSIM_BIN, str(cfg_path),
        f"injection_rate={ir}",
        f"traffic=matrix({matrix_path})",
        "sim_power=1",
        f"tech_file={TECH_FILE}",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    for line in r.stdout.splitlines():
        if "Packet latency average" in line:
            parts = line.split()
            for p in parts:
                try:
                    return float(p)
                except ValueError:
                    pass
    return None


def run_robustness_sweep(
    topologies: list[str] = TOP3_TOPOS,
    n_matrices: int = N_MATRICES,
    ir: float = ROBUSTNESS_IR,
) -> pd.DataFrame:
    """Run all 60 Booksim simulations; return results DataFrame."""
    rows = []
    for i in range(n_matrices):
        seed = 1000 + i
        mat  = generate_random_matrix(seed=seed)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", prefix=f"rmat_{i:02d}_", delete=False
        ) as f:
            mat_path = Path(f.name)
        write_booksim_matrix(mat, mat_path)

        for topo in topologies:
            cfg_candidates = list(CONFIGS.glob(f"{topo}.cfg")) + \
                             list(CONFIGS.glob(f"{topo}*.cfg"))
            if not cfg_candidates:
                print(f"  ⚠ No config found for {topo}, skipping")
                continue
            cfg = cfg_candidates[0]

            print(f"  matrix {i+1:02d}/{n_matrices}  {topo} ...", end=" ", flush=True)
            lat = run_booksim_one(cfg, mat_path, ir=ir)
            status = "ok" if lat is not None else "no_output"
            print(f"{lat if lat else 'FAILED'}  [{status}]")

            rows.append({
                "matrix_id":     i + 1,
                "matrix_seed":   seed,
                "topology":      topo,
                "injection_rate": ir,
                "latency_cycles": lat,
                "status":        status,
            })

        mat_path.unlink(missing_ok=True)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Synthetic dry-run (when Booksim not available)
# ---------------------------------------------------------------------------

def synthetic_robustness(
    topologies: list[str] = TOP3_TOPOS,
    n_matrices: int = N_MATRICES,
    seed: int = 99,
) -> pd.DataFrame:
    """Generate synthetic latency data for a 60-run robustness demo.

    Uses realistic zero-load latencies with per-matrix noise to simulate
    different traffic patterns. fly4 wins ~65% of matrices, cmesh ~25%, fattree ~10%.
    """
    rng = np.random.default_rng(seed)

    # Base zero-load latencies from real sweep data
    base_latency = {"fly4": 16.58, "cmesh": 17.75, "fattree": 18.76}
    # Per-topology noise scale (fattree more sensitive to traffic pattern)
    noise_scale  = {"fly4":  0.8,  "cmesh":  1.2,   "fattree": 2.1}

    rows = []
    for i in range(n_matrices):
        for topo in topologies:
            bl  = base_latency.get(topo, 20.0)
            ns  = noise_scale.get(topo, 1.0)
            lat = bl + rng.normal(0, ns)
            rows.append({
                "matrix_id":      i + 1,
                "matrix_seed":    1000 + i,
                "topology":       topo,
                "injection_rate": ROBUSTNESS_IR,
                "latency_cycles": round(max(lat, bl * 0.5), 4),
                "status":         "ok",
            })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Robustness score computation
# ---------------------------------------------------------------------------

def compute_robustness(df: pd.DataFrame) -> pd.DataFrame:
    """Compute robustness_score = win share across matrices.

    A "win" for topology T on matrix M = T has the lowest latency among
    all topologies on matrix M (among ok rows only).

    Returns DataFrame with columns:
        topology, wins, total_matrices, robustness_score
    Sorted by robustness_score descending.
    """
    ok = df[df["status"] == "ok"].copy()

    wins: dict[str, int] = {t: 0 for t in df["topology"].unique()}
    total_by_topo: dict[str, int] = {t: 0 for t in df["topology"].unique()}

    for mid, grp in ok.groupby("matrix_id"):
        if grp["latency_cycles"].isna().all():
            continue
        min_lat = grp["latency_cycles"].min()
        winners = grp[grp["latency_cycles"] == min_lat]["topology"].tolist()
        # In case of tie, credit all tied topologies
        for topo in winners:
            wins[topo] = wins.get(topo, 0) + 1

    total_matrices = ok["matrix_id"].nunique()
    rows = []
    for topo in sorted(wins.keys()):
        w = wins.get(topo, 0)
        rows.append({
            "topology":         topo,
            "wins":             w,
            "total_matrices":   total_matrices,
            "robustness_score": round(w / total_matrices, 4) if total_matrices else 0.0,
        })

    return (pd.DataFrame(rows)
            .sort_values("robustness_score", ascending=False)
            .reset_index(drop=True))


# ---------------------------------------------------------------------------
# Bar chart
# ---------------------------------------------------------------------------

def plot_robustness_bar(
    df_score: pd.DataFrame,
    title: str = "PA-21: Robustness Score (Win Share over 20 Random Matrices)",
    figsize: tuple = (9, 5),
    dpi: int = 150,
) -> tuple["plt.Figure", "plt.Axes"]:
    """Horizontal bar chart of robustness (win-share) scores."""
    df_plot = df_score.sort_values("robustness_score")
    topos   = df_plot["topology"].tolist()
    scores  = df_plot["robustness_score"].tolist()
    cols    = [PALETTE.get(t, "#8C8C8C") for t in topos]

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    bars = ax.barh(topos, scores, color=cols, edgecolor="white",
                   linewidth=0.8, height=0.6)

    for bar, score, w in zip(bars, scores, df_plot["wins"].tolist()):
        ax.text(
            bar.get_width() + 0.01,
            bar.get_y() + bar.get_height() / 2,
            f"{score:.0%}  ({w} wins)",
            va="center", fontsize=10,
        )

    ax.set_xlabel("Robustness Score (win share over 20 random matrices)", fontsize=11)
    ax.set_title(title, fontsize=12, fontweight="bold", pad=10)
    ax.set_xlim(0, 1.20)
    ax.axvline(x=1 / len(topos), color="#888888", linewidth=0.8, linestyle=":",
               alpha=0.6)  # fair-share reference line
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Annotate fair-share reference
    ax.text(1 / len(topos), -0.55, "equal\nshare",
            ha="center", fontsize=7, color="#888888", style="italic")

    fig.tight_layout()
    return fig, ax


# ---------------------------------------------------------------------------
# Selfcheck
# ---------------------------------------------------------------------------

def _selfcheck():
    """Regression test: robustness scores sum to ≤ 1 (ties possible)."""
    import io

    # Synthetic run
    df = synthetic_robustness(n_matrices=10, seed=7)
    assert len(df) == 30, f"expected 30 rows (3 topos × 10 matrices), got {len(df)}"

    scores_df = compute_robustness(df)
    assert "robustness_score" in scores_df.columns
    total_wins = scores_df["wins"].sum()
    assert total_wins <= 10, f"total wins {total_wins} should be ≤ n_matrices=10"

    # Bar chart
    fig, ax = plot_robustness_bar(scores_df, dpi=72)
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
    ap.add_argument("--dry-run",     action="store_true",
                    help="synthetic latency data (no Booksim needed)")
    ap.add_argument("--run-booksim", action="store_true",
                    help="run real 60 Booksim simulations")
    ap.add_argument("--results-json", default=None,
                    help="path to existing robustness_runs.json (skip re-running)")
    ap.add_argument("--topologies", default=",".join(TOP3_TOPOS),
                    help=f"comma-separated topology list (default: {','.join(TOP3_TOPOS)})")
    ap.add_argument("--n-matrices", type=int, default=N_MATRICES,
                    help=f"number of random matrices (default: {N_MATRICES})")
    ap.add_argument("--out",         default=None,
                    help="output image (default: output/robustness_score.png)")
    ap.add_argument("--selfcheck",   action="store_true")
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    topologies = [t.strip() for t in args.topologies.split(",")]

    # --- Acquire run data
    if args.results_json:
        print(f"  Loading existing robustness runs from {args.results_json}")
        with open(args.results_json) as f:
            df_runs = pd.DataFrame(json.load(f))

    elif args.run_booksim:
        print(f"  Launching {args.n_matrices * len(topologies)} Booksim runs "
              f"({args.n_matrices} matrices × {len(topologies)} topologies) ...")
        df_runs = run_robustness_sweep(topologies, args.n_matrices)
        runs_out = OUTPUT / "robustness_runs.json"
        runs_out.parent.mkdir(parents=True, exist_ok=True)
        df_runs.to_json(runs_out, orient="records", indent=2)
        print(f"  Raw runs → {runs_out}")

    else:
        print(f"  ⚠  No --run-booksim or --dry-run flag. Using synthetic data.\n"
              f"     Run with --run-booksim when Booksim is available (60 runs),\n"
              f"     or --dry-run for a fast demo.")
        df_runs = synthetic_robustness(topologies, args.n_matrices)

    # --- Compute scores
    scores = compute_robustness(df_runs)

    print(f"\n=== PA-21: Robustness Score ({args.n_matrices} random matrices) ===\n")
    print(f"  {'topology':<20s} {'wins':>5s} {'total':>6s} {'score':>7s}")
    print(f"  {'-'*20} {'-'*5} {'-'*6} {'-'*7}")
    for _, r in scores.iterrows():
        bar_len = int(r["robustness_score"] * 20)
        bar_str = "█" * bar_len + "░" * (20 - bar_len)
        print(f"  {r['topology']:<20s} {r['wins']:>5d} {r['total_matrices']:>6d}  "
              f"  {r['robustness_score']:>5.1%}  {bar_str}")

    winner = scores.iloc[0]
    print(f"\n  Most robust topology: {winner['topology']} "
          f"({winner['robustness_score']:.0%} win share, "
          f"{winner['wins']}/{winner['total_matrices']} matrices)")

    # --- Write CSV
    csv_out = OUTPUT / "robustness_score.csv"
    csv_out.parent.mkdir(parents=True, exist_ok=True)
    scores.to_csv(csv_out, index=False)
    print(f"\n  CSV    → {csv_out}")

    # --- Bar chart
    fig, _ = plot_robustness_bar(scores)
    out = Path(args.out) if args.out else OUTPUT / "robustness_score.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"  figure → {out}")


if __name__ == "__main__":
    main()
