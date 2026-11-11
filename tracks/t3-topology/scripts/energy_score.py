#!/usr/bin/env python3
"""PA-11 — Energy score: hops_avg × Accelergy/Timeloop energy per hop.

Rescales BookSim hop counts with an explicitly supplied NoC calibration or
an illustrative constant. This remains a proxy, not measured NoC energy.

Stage 2 of the energy evaluation axis:
  Stage 1 (PA-09): energy_proxy = hops_avg × packet_size  (dimensionless proxy)
  Stage 2 (PA-11): energy_score = hops_avg × pJ_per_hop   (pJ, from Accelergy)
  Stage 3 (PA-12): validate proxy ranking vs real Booksim total_power

The pJ-per-hop figure comes from energy.json's NoC-related component (if
available), or from a configurable default (NOC_PJ_PER_HOP env-var, default
20.5 pJ — representative of a 45nm 5-port router at 1GHz from Timeloop
synthesis studies).

Usage
-----
    python3 scripts/energy_score.py                          # augment + print
    python3 scripts/energy_score.py --selfcheck              # regression tests
    python3 scripts/energy_score.py --out output/energy_score.csv

API
---
    from scripts.energy_score import add_energy_score, load_pj_per_hop
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

HERE    = Path(__file__).parent
TRACK   = HERE.parent
RESULTS = TRACK / "results"
OUTPUT  = TRACK / "output"

# Default pJ/hop estimate — representative 45nm 5-port NoC router.
# Override via NOC_PJ_PER_HOP env-var or energy.json.
DEFAULT_PJ_PER_HOP = 20.5


def load_pj_per_hop(energy_json_path: Optional[Path] = None) -> float:
    """Load per-hop energy (pJ) from energy.json or env-var fallback.

    Priority:
      1. NOC_PJ_PER_HOP environment variable
      2. energy.json → noc_pj_per_hop (explicit NoC calibration only)
      3. DEFAULT_PJ_PER_HOP constant (20.5 pJ)
    """
    val = os.environ.get("NOC_PJ_PER_HOP")
    p = energy_json_path or RESULTS / "energy.json"
    if val is None and p.exists():
        data = json.loads(p.read_text())
        # Accelerator pJ/compute is not NoC pJ/hop. Never substitute it.
        val = data.get("noc_pj_per_hop")
    if val is None:
        return DEFAULT_PJ_PER_HOP
    if isinstance(val, bool):
        raise ValueError("NoC pJ/hop must be finite and positive")
    pj = float(val)
    if not math.isfinite(pj) or pj <= 0:
        raise ValueError("NoC pJ/hop must be finite and positive")
    return pj


def add_energy_score(
    df: pd.DataFrame,
    pj_per_hop: Optional[float] = None,
) -> pd.DataFrame:
    """Add 'energy_score' column = hops_avg × pj_per_hop (pJ per packet).

    Parameters
    ----------
    df         : DataFrame with at least 'hops_avg' column.
    pj_per_hop : energy per hop in pJ. If None, loaded from energy.json / env.

    Returns
    -------
    DataFrame with added columns:
        energy_score     : hops_avg × pj_per_hop  (pJ per packet)
        pj_per_hop       : the constant used (same for all rows)
    """
    df = df.copy()
    _pj = pj_per_hop if pj_per_hop is not None else load_pj_per_hop()
    df["pj_per_hop"]    = _pj
    df["energy_score"]  = df["hops_avg"] * _pj  # NaN propagates cleanly
    return df


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _selfcheck():
    """Regression tests for energy_score computation."""
    sample = pd.DataFrame([
        {"topology": "mesh4x4",   "hops_avg": 3.48, "status": "ok"},
        {"topology": "fattree16", "hops_avg": 2.44, "status": "ok"},
        {"topology": "fly4",      "hops_avg": 2.00, "status": "ok"},
        {"topology": "anynet16",  "hops_avg": None, "status": "no_output"},
    ])

    pj = 20.5
    result = add_energy_score(sample, pj_per_hop=pj)

    # Check energy_score computed correctly
    assert "energy_score" in result.columns
    assert "pj_per_hop" in result.columns

    mesh_score = result[result["topology"] == "mesh4x4"]["energy_score"].iloc[0]
    expected = 3.48 * 20.5
    assert abs(mesh_score - expected) < 0.01, f"expected {expected}, got {mesh_score}"

    fly_score = result[result["topology"] == "fly4"]["energy_score"].iloc[0]
    assert abs(fly_score - 2.0 * 20.5) < 0.01

    # NaN propagation for failed topologies
    anynet_score = result[result["topology"] == "anynet16"]["energy_score"].iloc[0]
    assert pd.isna(anynet_score), "anynet16 with no hops should get NaN energy_score"

    # pj_per_hop constant broadcast
    assert (result["pj_per_hop"] == 20.5).all()

    # Ranking: fly4 < fattree16 < mesh4x4 by energy_score
    ok = result[result["status"] == "ok"].sort_values("energy_score")
    ranking = ok["topology"].tolist()
    assert ranking == ["fly4", "fattree16", "mesh4x4"], f"unexpected ranking: {ranking}"

    import tempfile
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
        path = Path(directory) / "energy.json"
        path.write_text(json.dumps({"total_pj_per_compute": 9999}))
        assert load_pj_per_hop(path) == DEFAULT_PJ_PER_HOP
        path.write_text(json.dumps({"noc_pj_per_hop": 7.2}))
        assert load_pj_per_hop(path) == 7.2
        with patch.dict(os.environ, {"NOC_PJ_PER_HOP": "8.1"}):
            assert load_pj_per_hop(path) == 8.1
        for invalid in (True, -1, 0, "NaN", "Infinity"):
            path.write_text(json.dumps({"noc_pj_per_hop": invalid}))
            try:
                load_pj_per_hop(path)
            except ValueError:
                pass
            else:
                raise AssertionError(f"accepted invalid NoC calibration: {invalid!r}")

    print("selfcheck OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sweep", default=None,
                    help="path to topology_sweep.json")
    ap.add_argument("--energy-json", default=None,
                    help="path to energy.json with explicit noc_pj_per_hop calibration")
    ap.add_argument("--out", default=None,
                    help="output CSV path (default: output/energy_score.csv)")
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    sys.path.insert(0, str(HERE))
    from analysis import load_sweep_df

    df = load_sweep_df(args.sweep)
    energy_path = Path(args.energy_json) if args.energy_json else None
    pj = load_pj_per_hop(energy_path)
    df = add_energy_score(df, pj_per_hop=pj)

    print(f"\n=== PA-11: Energy Score (hops × {pj:.1f} pJ/hop) ===\n")

    ok = df[df["status"] == "ok"].copy()
    if ok.empty:
        print("  No valid rows.")
        return

    # Per-topology summary at lowest injection rate
    summary = (ok.sort_values("injection_rate")
               .groupby("topology")
               .first()
               .sort_values("energy_score"))

    print(f"  {'topology':<20s} {'hops_avg':>9s} {'energy_score':>13s} {'total_power':>12s}")
    print(f"  {'-'*20} {'-'*9} {'-'*13} {'-'*12}")
    for topo, row in summary.iterrows():
        hops_str = f"{row['hops_avg']:.3f}" if pd.notna(row['hops_avg']) else "—"
        es_str = f"{row['energy_score']:.2f} pJ" if pd.notna(row['energy_score']) else "—"
        tp_str = f"{row['total_power']:.3f}" if pd.notna(row.get('total_power')) else "—"
        print(f"  {topo:<20s} {hops_str:>9s} {es_str:>13s} {tp_str:>12s}")

    # Write CSV
    out = Path(args.out) if args.out else OUTPUT / "energy_score.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\n  → {out}  ({len(df)} rows)")


if __name__ == "__main__":
    main()
