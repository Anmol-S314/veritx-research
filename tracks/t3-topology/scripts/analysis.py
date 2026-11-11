#!/usr/bin/env python3
"""PA-01 — Python analysis framework for T3 topology sweep results.

Loads results/topology_sweep.json into a pandas DataFrame with columns:
    topology, injection_rate, latency_cycles, hops_avg, energy_proxy,
        energy_proxy_total, area_mm2, peak_link_util, total_power,
    router_power, link_power, total_area, traffic, status

FIX (this version):
  - status is now one of "ok" | "unstable" | "no_output" (previously any
    non-null latency was lumped into "ok" even on aborted runs). All
    "valid rows" filtering below uses status == "ok" only, so
    saturation_rate / summarise() are no longer computed over
    aborted/garbage latency values.
  - anynet16 (and any other topology) is kept in the DataFrame regardless
    of status — including no_output rows — so failures stay visible in
    --all output and summarise()'s "no valid data" listing.
  - stderr_snippet column passed through for diagnosing no_output rows
    (e.g. anynet16) directly from the DataFrame.

Energy proxy (legacy) = hops_avg * PACKET_SIZE_BITS. total_power / total_area
come from Booksim's real power/area module (sim_power=1 + tech_file, wired in
run_experiments.py) and are the preferred metrics going forward — they are
available even on runs where hops_avg is missing (Booksim only prints "Hops
average" after a fully converged run; the power/area summary prints
regardless of whether the run aborted as unstable).

Usage
-----
    python3 scripts/analysis.py                          # pretty-print summary
    python3 scripts/analysis.py --all                    # full DataFrame
    python3 scripts/analysis.py --selfcheck              # regression guard

API
---
    from scripts.analysis import (
        load_sweep_df, summarise, add_norm_latency, add_saturation_column,
    )

    df = load_sweep_df()             # full DataFrame (ok + unstable + failed rows, all topologies)
    df = add_norm_latency(df)        # PA-05: adds norm_latency vs mesh4x4 (ok rows only)
    df = add_saturation_column(df)   # PA-06: adds saturation_rate per (topology, traffic)
    df_ok = df[df.status == "ok"]    # converged rows only
"""

import json
import sys
import argparse
from pathlib import Path

import pandas as pd

from utils import saturation_point, saturation_point_gradient

# ---------------------------------------------------------------------------
# Paths — resolved relative to this file so the module works from any cwd
# ---------------------------------------------------------------------------
HERE   = Path(__file__).parent
TRACK  = HERE.parent
RESULTS = TRACK / "results"

# NoC energy proxy constant (legacy, retained for comparison against
# total_power). 32-bit flit × 4 flits/packet = 128 bits by default.
import os
PACKET_SIZE_BITS: int = int(os.environ.get("PACKET_SIZE_BITS", 128))

# Area figures (mm²) from Timeloop / synthesis — populated from energy.json
# when available, else None. Loaded once at module import. Separate from
# total_area (Booksim's own area model, per-row, in topology_sweep.json).
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

    Every topology in the JSON is kept, including ones that fail entirely
    (e.g. anynet16 with status == "no_output" on every row) — filtering
    those out is left to the caller (df[df.status == "ok"]), not the loader.

    Returns
    -------
    pd.DataFrame with columns:
        topology             str   — config stem (e.g. "mesh4x4", "anynet16")
        injection_rate       float — flit injection rate per cycle per node
        latency_cycles       float — packet latency average (NaN for failed/no_output runs;
                                      present but UNTRUSTED for status == "unstable")
        hops_avg             float — average hop count (NaN for failed AND unstable runs)
        energy_proxy         float — hops_avg × PACKET_SIZE_BITS (legacy per-packet; NaN when hops_avg missing)
        energy_proxy_total   float — PA-09: total_hops × bytes_per_link (proportional to total energy)
                                      = hops_avg × (PACKET_SIZE_BITS/8) × injection_rate × num_nodes
        area_mm2             float — from energy.json (same value for all rows, or NaN)
        peak_link_util       float — accepted flit rate average, a link-load proxy
        total_power          float — Booksim power module output (preferred energy metric)
        router_power         float — PA-10: Booksim router-only power (NaN if not available)
        link_power           float — PA-10: Booksim link-only power (NaN if not available)
        total_area           float — Booksim area module output (preferred area metric)
        traffic              str   — traffic pattern string
        status               str   — "ok" | "unstable" | "no_output"
        stderr_snippet       str   — last ~300 chars of stderr, only set on no_output rows
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
    for col in ("latency_cycles", "hops_avg", "peak_link_util",
                "total_power", "router_power", "link_power",
                "total_area", "traffic", "status",
                "stderr_snippet"):
        if col not in df.columns:
            df[col] = None

    # Backfill status for older JSON that predates the 3-way status split:
    # anything not explicitly "unstable"/"no_output" and with a latency value
    # is treated as "ok" (best-effort; new runs always set this correctly).
    df["status"] = df["status"].fillna(
        df["latency_cycles"].apply(lambda v: "ok" if pd.notna(v) else "no_output")
    )

    # Cast numerics (failed/missing rows have None/null → NaN)
    df["injection_rate"]  = pd.to_numeric(df["injection_rate"],  errors="coerce")
    df["latency_cycles"]  = pd.to_numeric(df["latency_cycles"],  errors="coerce")
    df["hops_avg"]        = pd.to_numeric(df["hops_avg"],        errors="coerce")
    df["peak_link_util"]  = pd.to_numeric(df["peak_link_util"],  errors="coerce")
    df["total_power"]     = pd.to_numeric(df["total_power"],     errors="coerce")
    df["router_power"]    = pd.to_numeric(df["router_power"],    errors="coerce")
    df["link_power"]      = pd.to_numeric(df["link_power"],      errors="coerce")
    df["total_area"]      = pd.to_numeric(df["total_area"],      errors="coerce")

    # Derived columns
    df["energy_proxy"] = df["hops_avg"] * PACKET_SIZE_BITS  # NaN propagates cleanly
    df["area_mm2"]     = _AREA_MM2  # scalar broadcast; NaN if energy.json absent

    # PA-09: total energy proxy = hops × bytes_per_link × injection_rate × num_nodes
    # This is proportional to the total NoC energy consumed at this operating point.
    num_nodes = len(df["topology"].unique())  # approximate; each topo may differ
    packet_size_bytes = PACKET_SIZE_BITS / 8
    df["energy_proxy_total"] = (
        df["hops_avg"] * packet_size_bytes * df["injection_rate"] * 16  # 16-node reference
    )  # NaN propagates cleanly for missing hops

    # Canonical column order
    df = df[["topology", "injection_rate", "latency_cycles",
             "hops_avg", "energy_proxy", "energy_proxy_total", "area_mm2",
             "peak_link_util", "total_power", "router_power", "link_power",
             "total_area",
             "traffic", "status", "stderr_snippet"]]

    return df


# ---------------------------------------------------------------------------
# PA-05 — normalised latency vs mesh baseline
# ---------------------------------------------------------------------------

def add_norm_latency(df: pd.DataFrame) -> pd.DataFrame:
    """Add PA-05: normalised latency vs mesh4x4 baseline.

    Only computed from status == "ok" rows on both sides — unstable rows'
    latency values are not converged numbers and would corrupt the ratio.
    Topologies with no "ok" rows at all (e.g. anynet16) get NaN throughout.

    norm_latency = latency_topo / latency_mesh4x4, matched at the same
    injection_rate. NaN where either side is missing or unstable.
    """
    mesh_ok = df[(df["topology"] == "mesh4x4") & (df["status"] == "ok")]
    mesh = mesh_ok[["injection_rate", "latency_cycles"]] \
        .rename(columns={"latency_cycles": "_mesh_latency"})

    out = df.merge(mesh, on="injection_rate", how="left")
    out["norm_latency"] = out["latency_cycles"] / out["_mesh_latency"]
    out.loc[out["status"] != "ok", "norm_latency"] = pd.NA
    out = out.drop(columns="_mesh_latency")
    return out


# ---------------------------------------------------------------------------
# PA-06 — automated saturation-point detection per (topology, traffic)
# ---------------------------------------------------------------------------

def add_saturation_column(df: pd.DataFrame) -> pd.DataFrame:
    """PA-06: adds saturation detection per (topology, traffic) pair.

    Two complementary methods — both are computed for every group:

    1. **saturation_rate** (threshold): the first injection rate where
       latency exceeds k × zero-load latency (k from SAT_K env-var,
       default 2.0). Same cliff-detection logic used by
       generate_dashboard.py. Simple, reproducible, literature-standard.

    2. **saturation_rate_grad** (gradient / knee detection): the first
       injection rate where the latency *slope* between consecutive
       sweep points exceeds slope_k × the initial (low-load) slope.
       This adapts to each topology's natural curve shape — a topology
       with high zero-load latency (e.g. qtree at 39 cycles) and one
       with low zero-load (e.g. fly4 at 16 cycles) are both detected
       correctly, because it measures *relative change in slope*, not
       an absolute latency threshold.

    Only status == "ok" rows are fed in; unstable/aborted runs' garbage
    latency values are excluded.  Topologies with zero "ok" rows (e.g.
    anynet16) get NaN for both columns.

    Adds two columns: saturation_rate, saturation_rate_grad.
    """
    df = df.copy()
    df["saturation_rate"] = pd.NA
    df["saturation_rate_grad"] = pd.NA

    ok = df[df["status"] == "ok"]
    for (topo, traffic), grp in ok.groupby(["topology", "traffic"]):
        grp_s = grp.sort_values("injection_rate")
        rates = grp_s["injection_rate"].tolist()
        lats  = grp_s["latency_cycles"].tolist()

        # Method 1: threshold-based (latency > k × zero-load)
        sat_thresh = saturation_point(rates, lats)
        # Method 2: gradient-based (slope spike relative to baseline slope)
        sat_grad   = saturation_point_gradient(rates, lats)

        mask = (df["topology"] == topo) & (df["traffic"] == traffic)
        df.loc[mask, "saturation_rate"]      = sat_thresh
        df.loc[mask, "saturation_rate_grad"] = sat_grad

    return df


# ---------------------------------------------------------------------------
# Summary helper
# ---------------------------------------------------------------------------

def summarise(df: pd.DataFrame) -> pd.DataFrame:
    """Return a per-topology summary table (status == "ok" rows only).

    Topologies with zero "ok" rows (e.g. anynet16 failing on every rate)
    are absent from this table entirely — they instead show up in the
    "no valid data" listing printed by main() / the no_output check below.

    Columns: topology, n_ok, n_unstable, zero_load_latency, sat_rate,
             sat_rate_grad, max_peak_link_util, max_energy_proxy,
             max_total_power, max_total_area
    """
    ok = df[df["status"] == "ok"].copy()
    unstable_counts = df[df["status"] == "unstable"].groupby("topology").size()

    _empty_cols = ["topology", "n_ok", "n_unstable",
                   "zero_load_latency", "sat_rate", "sat_rate_grad",
                   "max_peak_link_util",
                   "max_energy_proxy", "max_energy_proxy_total",
                   "max_total_power", "max_router_power", "max_link_power",
                   "max_total_area"]
    if ok.empty:
        return pd.DataFrame(columns=_empty_cols)

    rows = []
    for topo, grp in ok.groupby("topology"):
        grp_s = grp.sort_values("injection_rate")
        rates = grp_s["injection_rate"].tolist()
        lats  = grp_s["latency_cycles"].tolist()
        zero_load = lats[0]

        # PA-06 threshold saturation
        sat_thresh = saturation_point(rates, lats)
        # PA-06 gradient saturation (knee detection)
        sat_grad   = saturation_point_gradient(rates, lats)

        # PA-07 peak link utilisation (max across all ok rates)
        max_plu = None
        if "peak_link_util" in grp_s.columns and grp_s["peak_link_util"].notna().any():
            max_plu = round(float(grp_s["peak_link_util"].max()), 4)

        rows.append({
            "topology":              topo,
            "n_ok":                  len(grp_s),
            "n_unstable":            int(unstable_counts.get(topo, 0)),
            "zero_load_latency":     round(zero_load, 3),
            "sat_rate":              sat_thresh,
            "sat_rate_grad":         sat_grad,
            "max_peak_link_util":    max_plu,
            "max_energy_proxy":      round(grp_s["energy_proxy"].max(), 3) if grp_s["energy_proxy"].notna().any() else None,
            "max_energy_proxy_total": round(grp_s["energy_proxy_total"].max(), 3) if "energy_proxy_total" in grp_s.columns and grp_s["energy_proxy_total"].notna().any() else None,
            "max_total_power":       round(grp_s["total_power"].max(), 3) if grp_s["total_power"].notna().any() else None,
            "max_router_power":      round(grp_s["router_power"].max(), 3) if "router_power" in grp_s.columns and grp_s["router_power"].notna().any() else None,
            "max_link_power":        round(grp_s["link_power"].max(), 3) if "link_power" in grp_s.columns and grp_s["link_power"].notna().any() else None,
            "max_total_area":        round(grp_s["total_area"].max(), 3) if grp_s["total_area"].notna().any() else None,
        })

    return pd.DataFrame(rows).set_index("topology").sort_values("zero_load_latency")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _selfcheck():
    """Regression guard — verifiable without a real Booksim environment."""
    import tempfile, json

    # --- Test dataset: covers ok, unstable, no_output, and enough points
    # for both threshold and gradient saturation to trigger ---
    sample = [
        # mesh4x4: 4 ok points — latency rises gently then spikes
        {"topology": "mesh4x4", "injection_rate": 0.01,
         "latency_cycles": 20.0,  "hops_avg": 2.78, "peak_link_util": 0.10,
         "total_power": 25.48, "total_area": 0.3313, "status": "ok",
         "traffic": "matrix(test.txt)", "returncode": 0},
        {"topology": "mesh4x4", "injection_rate": 0.02,
         "latency_cycles": 21.5,  "hops_avg": 2.82, "peak_link_util": 0.20,
         "total_power": 30.0, "total_area": 0.3313, "status": "ok",
         "traffic": "matrix(test.txt)", "returncode": 0},
        {"topology": "mesh4x4", "injection_rate": 0.03,
         "latency_cycles": 23.0,  "hops_avg": 2.90, "peak_link_util": 0.30,
         "total_power": 35.0, "total_area": 0.3313, "status": "ok",
         "traffic": "matrix(test.txt)", "returncode": 0},
        {"topology": "mesh4x4", "injection_rate": 0.05,
         "latency_cycles": 164.0, "hops_avg": 2.95, "peak_link_util": 0.62,
         "total_power": 60.0, "total_area": 0.3313, "status": "ok",
         "traffic": "matrix(test.txt)", "returncode": 0},
        # Unstable/aborted run: hops_avg missing, latency present but should
        # NOT be treated as "ok" nor feed saturation/summary stats.
        {"topology": "mesh4x4", "injection_rate": 0.2,
         "latency_cycles": 596.783, "hops_avg": None, "peak_link_util": 0.7408,
         "total_power": 72.8302, "total_area": 0.331308, "status": "unstable",
         "traffic": "matrix(test.txt)", "returncode": 0},
        # anynet16 — kept in the analysis (not dropped), fails on every rate.
        {"topology": "anynet16", "injection_rate": 0.01,
         "latency_cycles": None,  "hops_avg": None,  "peak_link_util": None,
         "total_power": None, "total_area": None, "status": "no_output",
         "traffic": "uniform", "returncode": 255,
         "stderr_snippet": "error: missing config field"},
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(sample, f)
        tmp = f.name

    df = load_sweep_df(tmp)

    # anynet16 must be present, not dropped
    assert "anynet16" in df["topology"].values, "anynet16 should remain in the DataFrame"
    assert len(df) == 6

    # Schema checks
    expected_cols = {"topology", "injection_rate", "latency_cycles",
                      "hops_avg", "energy_proxy", "energy_proxy_total",
                      "area_mm2",
                      "peak_link_util", "total_power", "router_power",
                      "link_power", "total_area",
                      "traffic", "status", "stderr_snippet"}
    assert expected_cols.issubset(df.columns), df.columns

    # Status split
    assert (df["status"] == "unstable").sum() == 1
    assert (df["status"] == "no_output").sum() == 1
    assert (df["status"] == "ok").sum() == 4

    # no_output row (anynet16) → NaN latency, stderr_snippet preserved
    failed = df[df["status"] == "no_output"]
    assert failed["topology"].iloc[0] == "anynet16"
    assert failed["latency_cycles"].isna().all()
    assert failed["stderr_snippet"].iloc[0] == "error: missing config field"

    # unstable row: latency present, but must not count as ok
    unstable_row = df[df["status"] == "unstable"]
    assert not unstable_row["latency_cycles"].isna().all(), \
        "unstable row keeps its (untrusted) latency value"
    assert pd.isna(unstable_row["hops_avg"].iloc[0])
    assert not pd.isna(unstable_row["total_power"].iloc[0]), \
        "total_power should survive an unstable run"

    # Energy proxy on valid rows
    ok_row = df[(df["topology"] == "mesh4x4") & (df["injection_rate"] == 0.01)]
    expected_ep = 2.78 * 128
    # PA-09: energy_proxy_total check
    expected_ept = 2.78 * (128 / 8) * 0.01 * 16
    actual_ept = float(ok_row["energy_proxy_total"].iloc[0])
    assert abs(actual_ept - expected_ept) < 0.01, \
        f"energy_proxy_total: expected {expected_ept}, got {actual_ept}"
    assert abs(float(ok_row["energy_proxy"].iloc[0]) - expected_ep) < 0.01

    # Summarise — anynet16 absent (zero ok rows); mesh4x4 excludes the unstable row
    s = summarise(df)
    assert "anynet16" not in s.index, "topology with zero ok rows should not appear in summarise()"
    assert "mesh4x4" in s.index
    assert s.loc["mesh4x4", "n_ok"] == 4
    assert s.loc["mesh4x4", "n_unstable"] == 1
    assert s.loc["mesh4x4", "zero_load_latency"] == 20.0
    # PA-06 threshold: 164 > 2×20=40 → sat at 0.05
    assert s.loc["mesh4x4", "sat_rate"] == 0.05, s.loc["mesh4x4", "sat_rate"]
    # PA-06 gradient: slope 0→1 = (21.5-20)/0.01 = 150,
    #   slope 2→3 = (164-23)/0.02 = 7050 → 7050/150 = 47× >> 5× → grad sat at 0.05
    assert s.loc["mesh4x4", "sat_rate_grad"] == 0.05, \
        f"expected mesh4x4 gradient saturation at 0.05, got {s.loc['mesh4x4', 'sat_rate_grad']}"
    # PA-07: peak link util — max across ok rates = 0.62
    assert s.loc["mesh4x4", "max_peak_link_util"] == 0.62, \
        f"expected max_peak_link_util 0.62, got {s.loc['mesh4x4', 'max_peak_link_util']}"

    # PA-05: norm_latency must be NaN for the unstable row and for anynet16
    df_n = add_norm_latency(df)
    unstable_norm = df_n[df_n["status"] == "unstable"]["norm_latency"].iloc[0]
    assert pd.isna(unstable_norm), "unstable row must not get a norm_latency value"
    anynet_norm = df_n[df_n["topology"] == "anynet16"]["norm_latency"].iloc[0]
    assert pd.isna(anynet_norm)
    mesh_row = df_n[(df_n["topology"] == "mesh4x4") & (df_n["injection_rate"] == 0.01)]
    assert abs(float(mesh_row["norm_latency"].iloc[0]) - 1.0) < 1e-9

    # PA-06: add_saturation_column produces both columns; anynet16 gets NaN
    df_sat = add_saturation_column(df)
    assert "saturation_rate" in df_sat.columns
    assert "saturation_rate_grad" in df_sat.columns
    mesh_sat = df_sat[df_sat["topology"] == "mesh4x4"]["saturation_rate"].iloc[0]
    assert mesh_sat == 0.05, f"expected mesh4x4 threshold saturation at 0.05, got {mesh_sat}"
    mesh_sat_g = df_sat[df_sat["topology"] == "mesh4x4"]["saturation_rate_grad"].iloc[0]
    assert mesh_sat_g == 0.05, f"expected mesh4x4 gradient saturation at 0.05, got {mesh_sat_g}"
    anynet_sat = df_sat[df_sat["topology"] == "anynet16"]["saturation_rate"].iloc[0]
    assert pd.isna(anynet_sat)
    anynet_sat_g = df_sat[df_sat["topology"] == "anynet16"]["saturation_rate_grad"].iloc[0]
    assert pd.isna(anynet_sat_g)

    # Gradient-only unit test: gentle rise should NOT trigger
    from utils import saturation_point_gradient
    gentle = saturation_point_gradient(
        [0.01, 0.02, 0.03, 0.05, 0.08],
        [20.0,  20.5,  21.0,  22.0,  23.5])
    assert gentle is None, f"gentle curve should not trigger gradient saturation, got {gentle}"

    # Gradient-only unit test: cliff should trigger
    cliff = saturation_point_gradient(
        [0.01, 0.02, 0.03, 0.05],
        [20.0,  21.0,  22.0,  300.0])
    assert cliff == 0.05, f"cliff at 0.05 should be detected, got {cliff}"

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
    df = add_norm_latency(df)
    df = add_saturation_column(df)

    print(f"\n=== Sweep DataFrame ({'all rows' if args.all else 'valid only'}) ===")
    print(f"  Packet size constant (legacy proxy) : {PACKET_SIZE_BITS} bits")
    print(f"  Area (from energy.json, Timeloop-side): {_AREA_MM2} mm2\n")

    if args.all:
        display_cols = [c for c in df.columns if c not in ("stderr_snippet", "saturation_rate_grad")]
        with pd.option_context("display.max_rows", None, "display.max_columns", None, "display.width", 1000, "display.float_format", "{:.4f}".format):
            print(df[display_cols].to_string(index=False))
    else:
        print("\n=== Per-topology Summary (status == 'ok' rows only) ===\n")
        s = summarise(df)
        with pd.option_context("display.float_format", "{:.3f}".format, "display.width", 160):
            print(s.to_string())

        # PA-06 saturation comparison
        print("\n=== PA-06: Saturation Detection (two methods) ===")
        print("  threshold = first rate where latency > k × zero-load (k=SAT_K)")
        print("  gradient  = first rate where latency slope spikes > 5× baseline slope")
        for topo in s.index:
            t_sat  = s.loc[topo, "sat_rate"]
            g_sat  = s.loc[topo, "sat_rate_grad"]
            t_str  = f"{t_sat:.3f}" if t_sat is not None and not pd.isna(t_sat) else "—"
            g_str  = f"{g_sat:.3f}" if g_sat is not None and not pd.isna(g_sat) else "—"
            print(f"  {topo:20s}  threshold={t_str:>8s}  gradient={g_str:>8s}")

        # PA-07 peak link utilisation
        print("\n=== PA-07: Peak Link Utilisation (max across ok rates) ===")
        for topo in s.index:
            plu = s.loc[topo, "max_peak_link_util"]
            plu_str = f"{plu:.4f}" if plu is not None and not pd.isna(plu) else "—"
            print(f"  {topo:20s}  peak_link_util={plu_str}")

        unstable = df[df["status"] == "unstable"]["topology"].unique()
        if len(unstable):
            print(f"\n  Topologies with unstable/aborted rate points: {', '.join(sorted(unstable))}")
            print("  (their latency at those rates is excluded from the summary above)")

        failed = df[df["status"] == "no_output"]["topology"].unique()
        if len(failed):
            print(f"\n  Topologies with no valid data: {', '.join(sorted(failed))}")
            for t in sorted(failed):
                snippet = df[(df["topology"] == t) & (df["stderr_snippet"].notna())]["stderr_snippet"]
                if not snippet.empty:
                    print(f"    {t} stderr: {snippet.iloc[0]!r}")


if __name__ == "__main__":
    main()