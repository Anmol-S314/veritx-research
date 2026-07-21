#!/usr/bin/env python3
"""PA-02 — Aggregate ALL Booksim run results into one master dataset.

Reads every results/*.json in the track's results directory **plus** the
embedded run history in results/history.json, tags each record with a
commit hash, deduplicates, and writes aggregate.csv.

Sources merged (in priority order):
  1. results/topology_sweep.json  — current run (per-rate raw records)
  2. results/history.json         — up to 20 past runs (curves already
                                    flattened per generate_dashboard.py)
  3. Any other results/*.json     — must contain list[dict] with at least
                                    {topology, injection_rate, latency_cycles}

Output: results/aggregate.csv
Columns: run_sha, run_no, topology, injection_rate, latency_cycles,
         hops_avg, energy_proxy, area_mm2, traffic, status, source_file

Usage
-----
    python3 scripts/aggregate.py
    python3 scripts/aggregate.py --selfcheck
    python3 scripts/aggregate.py --out /tmp/my_aggregate.csv

API
---
    from scripts.aggregate import load_aggregate_df

    df = load_aggregate_df()   # full history + current sweep merged
"""

import json
import sys
import argparse
import subprocess
from pathlib import Path
from typing import Optional

import pandas as pd

HERE    = Path(__file__).parent
TRACK   = HERE.parent
RESULTS = TRACK / "results"

PACKET_SIZE_BITS: int = 128   # must match analysis.py


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git_sha(default: str = "local") -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=TRACK, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Source readers
# ---------------------------------------------------------------------------

def _records_from_sweep(path: Path, sha: str, run_no: int) -> list[dict]:
    """Convert a flat topology_sweep.json list into aggregate rows."""
    raw: list[dict] = json.loads(path.read_text())
    rows = []
    for r in raw:
        rows.append({
            "run_sha":        sha,
            "run_no":         run_no,
            "topology":       r.get("topology"),
            "injection_rate": r.get("injection_rate"),
            "latency_cycles": r.get("latency_cycles"),
            "hops_avg":       r.get("hops_avg"),
            "traffic":        r.get("traffic", "unknown"),
            "status":         r.get("status", "unknown"),
            "source_file":    path.name,
        })
    return rows


def _records_from_history(path: Path) -> list[dict]:
    """Flatten history.json (list of run dicts with embedded curves) into rows."""
    hist: list[dict] = json.loads(path.read_text())
    rows = []
    for h in hist:
        sha    = h.get("sha",  "unknown")
        run_no = h.get("run",  0)
        curves = h.get("curves", {})
        for topo, pts in curves.items():
            for pt in pts:
                # pts are [injection_rate, latency_cycles, hops_avg?]
                rate    = pt[0]
                latency = pt[1]
                hops    = pt[2] if len(pt) > 2 else None
                rows.append({
                    "run_sha":        sha,
                    "run_no":         run_no,
                    "topology":       topo,
                    "injection_rate": rate,
                    "latency_cycles": latency,
                    "hops_avg":       hops,
                    "traffic":        "history",
                    "status":         "ok",
                    "source_file":    "history.json",
                })
    return rows


def _records_from_generic_json(path: Path, sha: str, run_no: int) -> list[dict]:
    """Best-effort parse of any other results/*.json that looks like a sweep."""
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    rows = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        if "topology" not in r and "injection_rate" not in r:
            continue   # not a sweep record
        rows.append({
            "run_sha":        r.get("sha", sha),
            "run_no":         r.get("run", run_no),
            "topology":       r.get("topology"),
            "injection_rate": r.get("injection_rate"),
            "latency_cycles": r.get("latency_cycles"),
            "hops_avg":       r.get("hops_avg"),
            "traffic":        r.get("traffic", "unknown"),
            "status":         r.get("status", "unknown"),
            "source_file":    path.name,
        })
    return rows


# ---------------------------------------------------------------------------
# Master loader  (PA-02 deliverable)
# ---------------------------------------------------------------------------

def load_aggregate_df(results_dir: Optional[Path] = None,
                      out_path:    Optional[Path] = None) -> pd.DataFrame:
    """Collect all results/*.json + history.json into a single DataFrame.

    Parameters
    ----------
    results_dir : directory to scan (default: track/results).
    out_path    : if given, write aggregate.csv to this path.

    Returns
    -------
    pd.DataFrame tagged with run_sha, columns identical to analysis.py output
    plus run_sha, run_no, source_file.
    """
    rdir   = results_dir or RESULTS
    sha    = _git_sha()
    all_rows: list[dict] = []

    # 1. Current sweep — always freshest
    sweep_path = rdir / "topology_sweep.json"
    if sweep_path.exists():
        all_rows.extend(_records_from_sweep(sweep_path, sha, run_no=0))

    # 2. History (embedded curves from past dashboard runs)
    hist_path = rdir / "history.json"
    if hist_path.exists():
        all_rows.extend(_records_from_history(hist_path))

    # 3. Any other *.json in results/
    skip = {sweep_path.name, hist_path.name,
            "energy.json", "sanity_result.json"}
    for p in sorted(rdir.glob("*.json")):
        if p.name in skip:
            continue
        all_rows.extend(_records_from_generic_json(p, sha, run_no=-1))

    if not all_rows:
        raise RuntimeError(
            f"No usable JSON found in {rdir}.\n"
            "Run: make sim  (or: python3 scripts/run_experiments.py)"
        )

    df = pd.DataFrame(all_rows)

    # Cast types
    for col in ("injection_rate", "latency_cycles", "hops_avg"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Derived columns
    df["energy_proxy"] = df["hops_avg"] * PACKET_SIZE_BITS
    df["area_mm2"]     = None   # populated from energy.json if present
    _ejson = rdir / "energy.json"
    if _ejson.exists():
        try:
            df["area_mm2"] = json.loads(_ejson.read_text()).get("area_mm2")
        except Exception:
            pass

    # Deduplicate: history.json rows shadow topology_sweep if same sha+topo+rate
    # Priority: sweep (run_no=0) wins over history rows with the same sha
    df = df.drop_duplicates(
        subset=["run_sha", "topology", "injection_rate"],
        keep="first"
    )

    # Canonical column order
    df = df[["run_sha", "run_no", "topology", "injection_rate",
             "latency_cycles", "hops_avg", "energy_proxy", "area_mm2",
             "traffic", "status", "source_file"]]

    df = df.sort_values(["run_no", "topology", "injection_rate"]).reset_index(drop=True)

    if out_path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)
        print(f"  aggregate.csv → {out_path}  ({len(df)} rows, "
              f"{df['run_sha'].nunique()} unique commits)")

    return df


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _selfcheck():
    import tempfile, json as _json

    sweep_data = [
        {"topology": "mesh4x4",  "injection_rate": 0.002, "latency_cycles": 20.0,
         "hops_avg": 2.78, "traffic": "matrix(t.txt)", "status": "ok"},
        {"topology": "fattree16","injection_rate": 0.002, "latency_cycles": 14.8,
         "hops_avg": 1.74, "traffic": "matrix(t.txt)", "status": "ok"},
    ]
    hist_data = [
        {"run": 1, "sha": "abc1234", "msg": "first", "date": "2026-01-01",
         "latency": {"mesh4x4": 21.0},
         "curves": {"mesh4x4": [[0.002, 21.0, 2.80], [0.01, 25.0, 2.85]]},
         "saturation": {"mesh4x4": None}, "hops": {}, "matrix": None, "levels": None},
    ]

    with tempfile.TemporaryDirectory() as td:
        tp = Path(td)
        (tp / "topology_sweep.json").write_text(_json.dumps(sweep_data))
        (tp / "history.json").write_text(_json.dumps(hist_data))

        df = load_aggregate_df(results_dir=tp)

    # schema
    assert "run_sha" in df.columns
    assert "energy_proxy" in df.columns

    # history rows included
    assert "abc1234" in df["run_sha"].values, df["run_sha"].unique()

    # dedup: mesh4x4@0.002 from history + sweep — only one per sha
    mesh_002 = df[(df["topology"] == "mesh4x4") & (df["injection_rate"] == 0.002)]
    shas = mesh_002["run_sha"].unique()
    assert len(shas) == len(set(shas)), "duplicate sha+topo+rate rows!"

    # energy proxy
    row = df[(df["topology"] == "fattree16") & (df["injection_rate"] == 0.002)]
    assert abs(float(row["energy_proxy"].iloc[0]) - 1.74 * 128) < 0.1

    print("selfcheck OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", default=None,
                    help="results directory (default: tracks/t3-topology/results)")
    ap.add_argument("--out", default=None,
                    help="output CSV path (default: results/aggregate.csv)")
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    rdir     = Path(args.results) if args.results else RESULTS
    out_path = Path(args.out)     if args.out     else rdir / "aggregate.csv"

    df = load_aggregate_df(results_dir=rdir, out_path=out_path)

    print(f"\n  {len(df)} total rows | {df['run_sha'].nunique()} commits "
          f"| {df['topology'].nunique()} topologies")
    print(f"  status counts:\n{df['status'].value_counts().to_string()}")


if __name__ == "__main__":
    main()
