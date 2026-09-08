#!/usr/bin/env python3
"""PA-01 — Python analysis framework for T3 topology sweep results.

Loads results/topology_sweep.json (from either Booksim or ASTRA-Sim sweep)
into a pandas DataFrame with columns:
    topology, injection_rate, latency_cycles, hops_avg, energy_proxy,
    area_mm2, status

Unified Schema Support:
  - Booksim (run_experiments.py): uniform/matrix traffic, hop-based latency
  - ASTRA-Sim (run_astrasim.py): Chakra workload, collective communication

Both write topology_sweep.json with compatible schema, so downstream analysis
treats them uniformly.

Energy proxy = hops_avg * PACKET_SIZE_BITS  (NoC-side; accelerator-side EDP
lives in energy.json from energy_report.py).

Usage
-----
    python3 scripts/analysis.py                          # pretty-print summary
    python3 scripts/analysis.py --selfcheck              # regression guard

API
---
    from scripts.analysis import load_sweep_df, summarise

    df = load_sweep_df()          # full DataFrame (valid + failed rows)
    df_ok = df[df.status == "ok"] # valid rows only
    print(summarise(df))
"""

import json
import sys
import argparse
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths — resolved relative to this file so the module works from any cwd
# ---------------------------------------------------------------------------
HERE   = Path(__file__).parent
TRACK  = HERE.parent
RESULTS = TRACK / "results"

# NoC energy proxy constant (32-bit flit × 4 flits/packet = 128 bits).
# Override via PACKET_SIZE_BITS env-var for different workloads.
import os
PACKET_SIZE_BITS: int = int(os.environ.get("PACKET_SIZE_BITS", 128))

# Area figures (mm²) from Timeloop / synthesis — populated from energy.json
# when available, else None.  Loaded once at module import.
def _load_area() -> float | None:
    p = RESULTS / "energy.json"
    if p.exists():
        try:
            data = json.loads(p.read_text())
            return data.get("area_mm2")
        except Exception:
            pass
    return None

_AREA_MM2: float | None = _load_area()


# ---------------------------------------------------------------------------
# Core loader  (PA-01 deliverable)
# ---------------------------------------------------------------------------

def load_sweep_df(path: str | Path | None = None) -> pd.DataFrame:
    """Load topology_sweep.json into a tidy pandas DataFrame.

    Parameters
    ----------
    path : optional path to a sweep JSON file; defaults to
           results/topology_sweep.json next to this script's track root.

    Returns
    -------
    pd.DataFrame with columns:
        topology        str   — config stem (e.g. "mesh4x4", "fattree16")
        injection_rate  float — flit injection rate per cycle per node
        latency_cycles  float — packet latency average (NaN for failed runs)
        hops_avg        float — average hop count (NaN for failed runs)
        energy_proxy    float — hops_avg × PACKET_SIZE_BITS (NaN when missing)
        area_mm2        float — from energy.json (same value for all rows, or NaN)
        traffic         str   — traffic pattern string
        status          str   — "ok" | "no_output" | "timeout" | …
    """
    if path:
        p = Path(path)
    else:
        config = os.environ.get("CONFIG", "baseline")
        t3_res = os.environ.get("T3_RESULTS")
        candidates = []
        if t3_res:
            candidates.extend([
                Path(t3_res) / "topology_sweep.json",
                Path(t3_res) / config / "topology_sweep.json",
                Path(t3_res) / "baseline" / "topology_sweep.json",
            ])
        candidates.extend([
            RESULTS / config / "topology_sweep.json",
            RESULTS / "baseline" / "topology_sweep.json",
            RESULTS / "topology_sweep.json",
        ])
        p = next((c for c in candidates if c.exists()), candidates[0])

    if not p.exists():
        raise FileNotFoundError(
            f"No sweep JSON at {p}.\n"
            "Run: make sim   (or: python3 scripts/run_experiments.py)"
        )

    raw: list[dict] = json.loads(p.read_text())
    df = pd.DataFrame(raw)

    # Normalise columns — ensure required columns exist even in older JSON files
    for col in ("latency_cycles", "hops_avg", "traffic", "status"):
        if col not in df.columns:
            df[col] = None

    # Cast numerics (failed rows have None/null → NaN)
    df["injection_rate"]  = pd.to_numeric(df["injection_rate"],  errors="coerce")
    df["latency_cycles"]  = pd.to_numeric(df["latency_cycles"],  errors="coerce")
    df["hops_avg"]        = pd.to_numeric(df["hops_avg"],        errors="coerce")

    # Derived columns
    df["energy_proxy"] = df["hops_avg"] * PACKET_SIZE_BITS  # NaN propagates cleanly
    df["area_mm2"]     = _AREA_MM2  # scalar broadcast; NaN if energy.json absent

    # Canonical column order
    df = df[["topology", "injection_rate", "latency_cycles",
             "hops_avg", "energy_proxy", "area_mm2", "traffic", "status"]]

    return df


# ---------------------------------------------------------------------------
# Summary helper
# ---------------------------------------------------------------------------

def summarise(df: pd.DataFrame) -> pd.DataFrame:
    """Return a per-topology summary table (valid rows only).

    Columns: topology, n_ok, zero_load_latency, sat_rate, max_energy_proxy
    """
    ok = df[df["status"] == "ok"].copy()
    if ok.empty:
        return pd.DataFrame(columns=["topology", "n_ok",
                                     "zero_load_latency", "sat_rate",
                                     "max_energy_proxy"])

    rows = []
    for topo, grp in ok.groupby("topology"):
        grp_s = grp.sort_values("injection_rate")
        zero_load = grp_s["latency_cycles"].iloc[0]
        # Saturation: first rate where latency > 2× zero-load (matches dashboard logic)
        sat = grp_s.loc[grp_s["latency_cycles"] > 2.0 * zero_load, "injection_rate"]
        sat_rate = float(sat.iloc[0]) if not sat.empty else None
        rows.append({
            "topology":          topo,
            "n_ok":              len(grp_s),
            "zero_load_latency": round(zero_load, 3),
            "sat_rate":          sat_rate,
            "max_energy_proxy":  round(grp_s["energy_proxy"].max(), 3),
        })

    return pd.DataFrame(rows).set_index("topology").sort_values("zero_load_latency")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _selfcheck():
    """Regression guard — verifiable without a real Booksim environment."""
    import tempfile, json

    sample = [
        {"topology": "mesh4x4", "injection_rate": 0.002,
         "latency_cycles": 20.0,  "hops_avg": 2.78, "status": "ok",
         "traffic": "matrix(test.txt)", "returncode": 0},
        {"topology": "mesh4x4", "injection_rate": 0.03,
         "latency_cycles": 164.0, "hops_avg": 2.95, "status": "ok",
         "traffic": "matrix(test.txt)", "returncode": 0},
        {"topology": "anynet16", "injection_rate": 0.002,
         "latency_cycles": None,  "hops_avg": None,  "status": "no_output",
         "traffic": "matrix(test.txt)", "returncode": 255},
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(sample, f)
        tmp = f.name

    df = load_sweep_df(tmp)

    # Schema checks
    assert set(["topology", "injection_rate", "latency_cycles",
                "hops_avg", "energy_proxy", "area_mm2",
                "traffic", "status"]).issubset(df.columns), df.columns

    # Failed rows → NaN, not None
    import math
    failed = df[df["status"] == "no_output"]
    assert failed["latency_cycles"].isna().all(), "nulls should become NaN"
    assert failed["energy_proxy"].isna().all(), "energy_proxy should be NaN when hops_avg is NaN"

    # Energy proxy on valid rows
    ok_row = df[(df["topology"] == "mesh4x4") & (df["injection_rate"] == 0.002)]
    expected_ep = 2.78 * 128
    assert abs(float(ok_row["energy_proxy"].iloc[0]) - expected_ep) < 0.01, \
        f"energy_proxy mismatch: {ok_row['energy_proxy'].iloc[0]} != {expected_ep}"

    # Summarise
    s = summarise(df)
    assert "mesh4x4" in s.index, "mesh4x4 should appear in summary"
    assert s.loc["mesh4x4", "zero_load_latency"] == 20.0
    # saturation: 164 > 2×20 = 40 → sat_rate = 0.03
    assert s.loc["mesh4x4", "sat_rate"] == 0.03, s.loc["mesh4x4", "sat_rate"]

    print("selfcheck OK")
    Path(tmp).unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sweep", default=None,
                    help="path to sweep JSON (default: results/topology_sweep.json)")
    ap.add_argument("--selfcheck", action="store_true",
                    help="run internal regression tests and exit")
    ap.add_argument("--all", action="store_true",
                    help="print full DataFrame (not just summary)")
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    df = load_sweep_df(args.sweep)

    print(f"\n=== Sweep DataFrame ({'all rows' if args.all else 'valid only'}) ===")
    print(f"  Packet size constant : {PACKET_SIZE_BITS} bits")
    print(f"  Area (from energy.json): {_AREA_MM2} mm²\n")

    if args.all:
        with pd.option_context("display.max_rows", None, "display.float_format", "{:.4f}".format):
            print(df.to_string(index=False))
    else:
        print("\n=== Per-topology Summary ===\n")
        s = summarise(df)
        with pd.option_context("display.float_format", "{:.3f}".format):
            print(s.to_string())
        failed = df[df["status"] != "ok"]["topology"].unique()
        if len(failed):
            print(f"\n  Topologies with no valid data: {', '.join(sorted(failed))}")


if __name__ == "__main__":
    main()
