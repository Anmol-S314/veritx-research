#!/usr/bin/env python3
"""PA-16 — 2D Pareto-front computation: latency vs energy score.

Computes the non-dominated set from a collection of topology operating points
using two objectives:
  x-axis  : norm_latency  (normalised vs mesh4x4 — lower is better)
  y-axis  : energy_score  (hops_avg × pJ_per_hop  — lower is better)

Both objectives are minimised: a topology A dominates topology B if
  A.norm_latency ≤ B.norm_latency  AND  A.energy_score ≤ B.energy_score
  (with at least one strict inequality)

The non-dominated set is the Pareto front — the set of points where improving
one objective requires sacrificing the other.

Usage
-----
    python3 scripts/pareto.py                  # print Pareto front + write CSV
    python3 scripts/pareto.py --selfcheck      # unit test with known answer
    python3 scripts/pareto.py --out /tmp/p.csv

API
---
    from scripts.pareto import (
        non_dominated_sort,
        pareto_front_2d,
        pareto_front_3d,
    )
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

HERE    = Path(__file__).parent
TRACK   = HERE.parent
RESULTS = TRACK / "results"
OUTPUT  = TRACK / "output"

# Default pJ/hop — same as energy_score.py; override via NOC_PJ_PER_HOP
_DEFAULT_PJ_PER_HOP = 20.5


# ---------------------------------------------------------------------------
# Core non-dominated sort (works for any number of objectives)
# ---------------------------------------------------------------------------

def non_dominated_sort(
    points: np.ndarray,
    minimize: Optional[list[bool]] = None,
) -> np.ndarray:
    """Return a boolean mask of the non-dominated (Pareto-optimal) points.

    Parameters
    ----------
    points   : (N, D) array — N points, D objectives.
    minimize : list of booleans, one per objective.
                True  → smaller is better (default for all objectives).
                False → larger is better (objective is negated before comparison).

    Returns
    -------
    np.ndarray of shape (N,) with dtype bool.
    True if the point is non-dominated (on the Pareto front).

    Algorithm: O(N²×D) — sufficient for our scales (N < 100 topologies).
    """
    n = len(points)
    if n == 0:
        return np.array([], dtype=bool)

    if minimize is None:
        minimize = [True] * points.shape[1]

    # Flip objectives that should be maximised so we always minimise
    pts = points.copy().astype(float)
    for j, mini in enumerate(minimize):
        if not mini:
            pts[:, j] = -pts[:, j]

    is_pareto = np.ones(n, dtype=bool)
    for i in range(n):
        if not is_pareto[i]:
            continue
        for j in range(n):
            if i == j or not is_pareto[j]:
                continue
            # Does j dominate i?  j ≤ i on all objectives, strict on ≥1
            if np.all(pts[j] <= pts[i]) and np.any(pts[j] < pts[i]):
                is_pareto[i] = False
                break

    return is_pareto


# ---------------------------------------------------------------------------
# 2D Pareto front helper (PA-16 / PA-17 deliverable)
# ---------------------------------------------------------------------------

def pareto_front_2d(
    df: pd.DataFrame,
    x_col: str = "norm_latency",
    y_col: str = "energy_score",
    label_col: str = "topology",
) -> pd.DataFrame:
    """Compute the 2D Pareto front (both objectives minimised).

    Parameters
    ----------
    df        : DataFrame with at least x_col, y_col, and label_col columns.
    x_col     : name of the first objective column (minimised).
    y_col     : name of the second objective column (minimised).
    label_col : name of the label column (e.g. 'topology').

    Returns
    -------
    DataFrame (same rows as input) with added column 'pareto_front' (bool).
    Sorted by x_col ascending.
    """
    df = df.copy()
    valid = df[[x_col, y_col]].notna().all(axis=1)
    pts = df.loc[valid, [x_col, y_col]].to_numpy(dtype=float)

    # Build a full-length bool array (False for invalid/NaN rows, front_mask for valid)
    pareto_col = np.zeros(len(df), dtype=bool)
    if len(pts) > 0:
        front_mask = non_dominated_sort(pts)
        valid_idx = np.where(valid.values)[0]
        for local_i, global_i in enumerate(valid_idx):
            pareto_col[global_i] = bool(front_mask[local_i])
    df["pareto_front"] = pareto_col
    return df.sort_values(x_col)


# ---------------------------------------------------------------------------
# 3D Pareto front helper (PA-18 deliverable)
# ---------------------------------------------------------------------------

def pareto_front_3d(
    df: pd.DataFrame,
    x_col: str = "norm_latency",
    y_col: str = "energy_score",
    z_col: str = "total_area",
    label_col: str = "topology",
) -> pd.DataFrame:
    """Compute the 3D Pareto front (all three objectives minimised).

    Parameters
    ----------
    df        : DataFrame with x_col, y_col, z_col, label_col.
    x_col     : first objective  (norm latency — minimised).
    y_col     : second objective (energy score — minimised).
    z_col     : third objective  (total area   — minimised).
    label_col : topology label column.

    Returns
    -------
    DataFrame with added column 'pareto_front_3d' (bool).
    """
    df = df.copy()
    valid = df[[x_col, y_col, z_col]].notna().all(axis=1)
    pts = df.loc[valid, [x_col, y_col, z_col]].to_numpy(dtype=float)

    # Build a full-length bool array (False for invalid/NaN rows, front_mask for valid)
    pareto_col = np.zeros(len(df), dtype=bool)
    if len(pts) > 0:
        front_mask = non_dominated_sort(pts)
        valid_idx = np.where(valid.values)[0]
        for local_i, global_i in enumerate(valid_idx):
            pareto_col[global_i] = bool(front_mask[local_i])
    df["pareto_front_3d"] = pareto_col
    return df.sort_values(x_col)


# ---------------------------------------------------------------------------
# Build Pareto input table from sweep data (used by PA-16 CLI and PA-17)
# ---------------------------------------------------------------------------

def build_pareto_df(
    sweep_path: Optional[Path] = None,
    pj_per_hop: float = _DEFAULT_PJ_PER_HOP,
) -> pd.DataFrame:
    """Load sweep JSON, compute norm_latency + energy_score, return one row
    per topology (at zero-load injection rate — the cleanest operating point).

    Returns a DataFrame with columns:
        topology, injection_rate, norm_latency, energy_score, total_area,
        zero_load_latency, hops_avg, total_power
    """
    sys.path.insert(0, str(HERE))
    from analysis import load_sweep_df, add_norm_latency

    df = load_sweep_df(sweep_path)
    df = add_norm_latency(df)

    ok = df[df["status"] == "ok"].copy()
    ok["energy_score"] = ok["hops_avg"] * pj_per_hop

    # One representative row per topology: lowest injection rate (zero-load)
    rows = []
    for topo, grp in ok.groupby("topology"):
        grp_s = grp.sort_values("injection_rate")
        row = grp_s.iloc[0].copy()
        rows.append({
            "topology":         topo,
            "injection_rate":   row["injection_rate"],
            "zero_load_latency": row["latency_cycles"],
            "norm_latency":     row["norm_latency"],
            "hops_avg":         row["hops_avg"],
            "energy_score":     row["energy_score"],
            "total_power":      row["total_power"],
            "total_area":       row["total_area"],
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Selfcheck — unit test with known Pareto answer (PA-16 deliverable)
# ---------------------------------------------------------------------------

def _selfcheck():
    """Unit test: 2D Pareto sort on synthetic dataset with known answer.

    Known Pareto front:
      A (0.5, 10) — best latency, good energy
      B (0.7, 6)  — worse latency, best energy  → A and B are non-dominated
      C (0.8, 12) — dominated by both A and B
      D (1.0, 8)  — dominated by B (B ≤ D on both)

    Expected front: {A, B}
    """
    import io

    points = np.array([
        [0.5, 10.0],  # A — non-dominated
        [0.7,  6.0],  # B — non-dominated
        [0.8, 12.0],  # C — dominated by A (A.lat=0.5≤0.8, A.e=10≤12)
        [1.0,  8.0],  # D — dominated by B (B.lat=0.7≤1.0, B.e=6≤8)
    ])

    mask = non_dominated_sort(points)
    assert mask.tolist() == [True, True, False, False], \
        f"Expected [True,True,False,False], got {mask.tolist()}"

    # --- 3D test ---
    # Add a z-axis (area). E is dominated by A on all three; F is new front.
    points3 = np.array([
        [0.5, 10.0, 0.3],   # A — good on all; is it dominated? No.
        [0.7,  6.0, 0.5],   # B — worse area than A; better energy
        [0.8, 12.0, 0.2],   # C — best area but worst latency + energy → C's area is best
        [1.0,  8.0, 0.5],   # D — dominated by B (B≤D on lat, energy, area)
    ])
    # In 3D: A (0.5,10,0.3), B (0.7,6,0.5), C (0.8,12,0.2) are Pareto-optimal
    #   D is dominated by B (0.7≤1.0, 6≤8, 0.5≤0.5 — all ≤, some strict)
    mask3 = non_dominated_sort(points3)
    assert mask3[0] == True,  "A should be on 3D front"
    assert mask3[1] == True,  "B should be on 3D front"
    assert mask3[2] == True,  "C should be on 3D front (best area)"
    assert mask3[3] == False, "D should be dominated"

    # --- DataFrame helper test ---
    sample = pd.DataFrame([
        {"topology": "A", "norm_latency": 0.5, "energy_score": 10.0, "total_area": 0.3},
        {"topology": "B", "norm_latency": 0.7, "energy_score":  6.0, "total_area": 0.5},
        {"topology": "C", "norm_latency": 0.8, "energy_score": 12.0, "total_area": 0.2},
        {"topology": "D", "norm_latency": 1.0, "energy_score":  8.0, "total_area": 0.5},
    ])

    result = pareto_front_2d(sample)
    front = set(result[result["pareto_front"]]["topology"])
    assert front == {"A", "B"}, f"2D front expected {{A,B}}, got {front}"

    result3 = pareto_front_3d(sample)
    front3 = set(result3[result3["pareto_front_3d"]]["topology"])
    assert front3 == {"A", "B", "C"}, f"3D front expected {{A,B,C}}, got {front3}"

    # --- Maximise test: one objective maximised ---
    # If we maximise energy_score (larger=better), then A (energy=10) beats B (6)
    pts_max = np.array([[0.5, 10.0], [0.7, 6.0], [0.8, 12.0]])
    mask_max = non_dominated_sort(pts_max, minimize=[True, False])
    # Maximising energy: C(energy=12) and A(energy=10, best lat) should be front
    # C dominates B (C.lat=0.8 vs B.lat=0.7 — NO! C.lat > B.lat)
    # A: lat=0.5 (best), energy=10; B: lat=0.7, energy=6 — A dominates B on energy
    # C: lat=0.8, energy=12 — C dominates A on energy but A dominates C on latency
    # → front = {A, C}; B dominated by A (A.lat ≤ B.lat AND A.energy ≥ B.energy)
    assert mask_max[0] == True,  "A should be on max-energy front"
    assert mask_max[1] == False, "B should be dominated (A beats on both lat and energy)"
    assert mask_max[2] == True,  "C should be on front (best energy)"

    print("selfcheck OK")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sweep",  default=None, help="path to topology_sweep.json")
    ap.add_argument("--out",    default=None, help="output CSV path (default: output/pareto_2d.csv)")
    ap.add_argument("--pj",     type=float,   default=_DEFAULT_PJ_PER_HOP,
                    help=f"pJ per hop (default: {_DEFAULT_PJ_PER_HOP})")
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    sweep = Path(args.sweep) if args.sweep else None
    df = build_pareto_df(sweep, pj_per_hop=args.pj)

    # 2D front
    df2 = pareto_front_2d(df)

    print(f"\n=== PA-16: 2D Pareto Front (latency vs energy, pJ/hop={args.pj:.1f}) ===\n")
    print(f"  {'topology':<20s} {'norm_lat':>9s} {'energy_pJ':>10s} "
          f"{'total_area':>11s} {'front':>6s}")
    print(f"  {'-'*20} {'-'*9} {'-'*10} {'-'*11} {'-'*6}")

    for _, r in df2.iterrows():
        nl  = f"{r['norm_latency']:.4f}"  if pd.notna(r.get('norm_latency'))  else "—"
        es  = f"{r['energy_score']:.2f}"  if pd.notna(r.get('energy_score'))  else "—"
        ta  = f"{r['total_area']:.4f}"    if pd.notna(r.get('total_area'))    else "—"
        on  = "★" if r["pareto_front"] else " "
        print(f"  {r['topology']:<20s} {nl:>9s} {es:>10s} {ta:>11s} {on:>6s}")

    front_topos = df2[df2["pareto_front"]]["topology"].tolist()
    print(f"\n  Pareto-optimal topologies ({len(front_topos)}): {', '.join(front_topos)}")

    out = Path(args.out) if args.out else OUTPUT / "pareto_2d.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df2.to_csv(out, index=False)
    print(f"\n  → {out}  ({len(df2)} topologies, {len(front_topos)} on front)")


if __name__ == "__main__":
    main()
