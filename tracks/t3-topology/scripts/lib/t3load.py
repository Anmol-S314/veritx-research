#!/usr/bin/env python3
"""t3load.py — unified comparison/visualization loading for T3 (Phase 2b).

Single home for the logic previously triplicated across the comparison and
visualization scripts:

* ``compare_json`` — tolerant compare-result loader (summary-vs-results
  layouts, honest_latency||latency aggregation). Canonicalizes to
  list[{name, mean, std, n}]. Replaces compare_bars.load_result and
  compare_heatmap.load_result (heatmap adapts via the mean field).
* ``load_sweep`` — single sweep parser returning list[dict]. Filter params
  preserve each tool's current semantics (no plot-data changes):
    - strict_ok=True  -> compare_curves ok-only (status=="ok" + latency!=None)
    - keep_all=True   -> analysis keep-all+NaN (no filtering; NaN handling
                         happens downstream in the DataFrame cast)
    - default         -> generate_dashboard latency!=None (valid points only)
  Aggregate's third parser maps to keep_all=True + its own
  "topology+injection_rate both missing -> skip" check on top.
* ``find_sweep`` — single discovery: CONFIG/T3_RESULTS env walk with the
  plot_curves candidate order as canonical.
* ``saturation_point`` — single cliff-detection implementation
  (latency > k * zero-load, default k=2.0). Accepts either a pandas
  DataFrame slice (injection_rate/latency_cycles columns, as used by
  plot_curves/analysis) or a sequence of (rate, latency[, ...]) pairs
  (as used by generate_dashboard/compare_curves).
* ``PALETTE`` + ``LINESTYLES`` — canonical styling. Adopts compare_curves'
  10-color tab10 set. NOTE: plot_curves previously used a muted
  seaborn-style palette; it now uses this canonical set (visual color
  change only, no data change). compare_bars' 6 colors are a prefix of
  this set, so n<=6 plots are unchanged.

Import pattern (mirrors lib.t3log/lib.t3models, script-mode safe)::

    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE))
    from lib.t3load import compare_json, load_sweep, find_sweep, ...
"""
from __future__ import annotations

import json
import os
import statistics
from pathlib import Path
from typing import Optional

# scripts/lib/t3load.py -> tracks/t3-topology
_HERE = Path(__file__).resolve().parent          # scripts/lib
_SCRIPTS = _HERE.parent                          # scripts/
_TRACK = _SCRIPTS.parent                         # tracks/t3-topology
_RESULTS = _TRACK / "results"

# Canonical styling (adopted from compare_curves.py).
PALETTE = [
    "#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]
LINESTYLES = ["-", "--", "-.", ":"]


def input_label(spec: str) -> tuple[str, Path]:
    """Parse one LABEL:PATH input spec (Phase 4e uniform rule).

    Explicit `LABEL:PATH` wins; a bare path falls back to its stem — never
    parent.name or a "/".split slice, both of which mislabel absolute paths
    ("/tmp/x.json" -> "tmp"). Returns (label, path). Used by compare_bars,
    compare_curves, and compare_heatmap so --json behaves identically.
    """
    label, sep, path = spec.partition(":")
    if not sep:
        p = Path(spec)
        return p.stem, p
    p = Path(path)
    return (label or p.stem), p


def compare_json(path: str | Path) -> list[dict]:
    """Compare JSON -> summary list [{name, mean, std, n}].

    Tolerant schema handler for summary-vs-results layouts with
    honest_latency||latency aggregation:

    * dict with 'summary' list -> normalize each entry (mean required).
    * dict with 'results' list -> group raw rows by name||topology.
    * bare list -> same grouping as 'results'.
    * otherwise -> ValueError (same message as compare_bars).
    """
    p = Path(path)
    try:
        data = json.loads(p.read_text())
    except OSError as e:
        raise ValueError(f"{p}: unreadable ({e})")
    if isinstance(data, dict) and isinstance(data.get("summary"), list):
        out: list[dict] = []
        for s in data["summary"]:
            if not isinstance(s, dict):
                continue
            m = s.get("mean")
            if not isinstance(m, (int, float)):
                continue
            name = s.get("name") or s.get("topology") or "?"
            std = s.get("std", 0.0)
            if not isinstance(std, (int, float)):
                std = 0.0
            n = s.get("n", 1)
            try:
                n_int = int(n) if isinstance(n, (int, float)) else 1
            except (TypeError, ValueError):
                n_int = 1
            out.append({
                "name": str(name),
                "mean": float(m),
                "std": float(std),
                "n": n_int,
            })
        return out
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        rows = data["results"]
    elif isinstance(data, list):
        rows = data
    else:
        raise ValueError(f"{p}: no 'summary' or 'results' list found")
    groups: dict[str, list[float]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        v = r.get("honest_latency", r.get("latency"))
        if not isinstance(v, (int, float)):
            continue
        groups.setdefault(str(r.get("name") or r.get("topology") or "?"), []).append(float(v))
    return [
        {"name": n, "mean": statistics.mean(vs),
         "std": statistics.stdev(vs) if len(vs) > 1 else 0.0, "n": len(vs)}
        for n, vs in sorted(groups.items())
    ]


def load_sweep(path: str | Path, *, strict_ok: bool = False,
               keep_all: bool = False) -> list[dict]:
    """Load a topology_sweep.json file -> list[dict] (filtered).

    Single parser; filter params preserve each tool's current semantics:

    * strict_ok=True  -> compare_curves ok-only: status=="ok" AND
      latency_cycles is not None. (Type/topology conversion still happens
      in the caller, which drops unconvertible rows — same as before.)
    * keep_all=True   -> analysis keep-all+NaN: no filtering; downstream
      DataFrame casts None->NaN. Also used by aggregate's sweep/generic
      readers (aggregate adds its own "both topology and injection_rate
      missing -> skip" check for generic files).
    * default         -> generate_dashboard latency!=None: keep every row
      whose latency_cycles is not None, regardless of status.

    Non-dict entries are skipped in all modes (compare_curves behavior;
    harmless for valid sweeps which are all dicts).

    Raises ValueError for unreadable files / non-list JSON (same messages
    as compare_curves.load_sweep).
    """
    p = Path(path)
    try:
        data = json.loads(p.read_text())
    except OSError as e:
        raise ValueError(f"{p}: unreadable ({e})")
    if not isinstance(data, list):
        raise ValueError(f"{p}: expected a JSON list of sweep rows")
    out: list[dict] = []
    for r in data:
        if not isinstance(r, dict):
            continue
        if keep_all:
            out.append(r)
            continue
        if strict_ok:
            if r.get("status") != "ok":
                continue
            if r.get("latency_cycles") is None:
                continue
            out.append(r)
            continue
        # default: dashboard latency!=None
        if r.get("latency_cycles") is None:
            continue
        out.append(r)
    return out


def find_sweep(results_dir: str | Path | None = None,
               config: str | None = None) -> Path | None:
    """Locate topology_sweep.json -> Path or None.

    Single discovery with the plot_curves candidate order as canonical:

    * results_dir given -> search <dir>/topology_sweep.json,
      <dir>/<config>/topology_sweep.json, <dir>/baseline/topology_sweep.json
      (explicit dir wins; env is ignored). Used by aggregate (--results)
      and dashboard (results_dir derived from --config).
    * results_dir None -> CONFIG/T3_RESULTS env walk:
      $T3_RESULTS/topology_sweep.json, $T3_RESULTS/<config>/...,
      $T3_RESULTS/baseline/..., then
      RESULTS/<config>/..., RESULTS/baseline/..., RESULTS/... .
      Used by plot_curves/analysis defaults.

    config defaults to $CONFIG or "baseline". Returns the first candidate
    that exists, else None (callers fall back to a canonical non-existing
    path for error-message parity).
    """
    cfg = config or os.environ.get("CONFIG", "baseline")
    if results_dir is not None:
        rdir = Path(results_dir)
        for c in (rdir / "topology_sweep.json",
                  rdir / cfg / "topology_sweep.json",
                  rdir / "baseline" / "topology_sweep.json"):
            if c.exists():
                return c
        return None
    t3_res = os.environ.get("T3_RESULTS")
    candidates: list[Path] = []
    if t3_res:
        candidates.extend([
            Path(t3_res) / "topology_sweep.json",
            Path(t3_res) / cfg / "topology_sweep.json",
            Path(t3_res) / "baseline" / "topology_sweep.json",
        ])
    candidates.extend([
        _RESULTS / cfg / "topology_sweep.json",
        _RESULTS / "baseline" / "topology_sweep.json",
        _RESULTS / "topology_sweep.json",
    ])
    for c in candidates:
        if c.exists():
            return c
    return None


def saturation_point(curve, k: float = 2.0) -> Optional[float]:
    """Injection rate where latency first exceeds k x zero-load, else None.

    Single implementation replacing plot_curves._saturation_point,
    analysis.summarise's inline check, and
    generate_dashboard.saturation_point (all hardcoded k=2.0; callers
    pass k explicitly — compare_curves now forwards its --k flag).

    Accepts:

    * pandas DataFrame slice with injection_rate + latency_cycles columns
      (plot_curves/analysis; assumed sorted by the caller, re-sorted here
      for robustness — idempotent on sorted inputs).
    * sequence of [rate, latency] / [rate, latency, hops] / (rate, latency)
      pairs (dashboard/compare_curves; sorted internally).
    * sequence of dicts with injection_rate/latency_cycles (or rate/latency)
      keys.

    Returns float(rate) or None. NaN zero-load/latencies never trigger
    (NaN comparisons are False), matching the original NaN-safe behavior.
    """
    # DataFrame path (duck-typed to avoid a hard pandas dependency).
    try:
        cols = getattr(curve, "columns", None)
        iloc = getattr(curve, "iloc", None)
        loc = getattr(curve, "loc", None)
        if cols is not None and iloc is not None and loc is not None \
                and "injection_rate" in cols and "latency_cycles" in cols:
            if len(curve) < 2:
                return None
            try:
                pts = curve.sort_values("injection_rate")
            except Exception:
                pts = curve
            try:
                zl = float(pts["latency_cycles"].iloc[0])
            except (TypeError, ValueError, IndexError):
                return None
            if zl != zl:  # NaN zero-load -> no saturation
                return None
            threshold = k * zl
            try:
                sat = pts.loc[pts["latency_cycles"] > threshold, "injection_rate"]
            except Exception:
                return None
            try:
                empty = bool(sat.empty)
            except Exception:
                return None
            if empty:
                return None
            try:
                return float(sat.iloc[0])
            except (TypeError, ValueError, IndexError):
                return None
    except Exception:
        return None

    if isinstance(curve, dict):
        return None
    try:
        pts_list = list(curve)  # type: ignore[arg-type]
    except TypeError:
        return None
    if len(pts_list) < 2:
        return None
    pairs: list[tuple[float, float]] = []
    for pt in pts_list:
        try:
            if isinstance(pt, dict):
                r = pt.get("injection_rate", pt.get("rate"))
                lat = pt.get("latency_cycles", pt.get("latency"))
                pairs.append((float(r), float(lat)))  # type: ignore[arg-type]
            elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
                pairs.append((float(pt[0]), float(pt[1])))
            else:
                continue
        except (TypeError, ValueError, IndexError, KeyError):
            continue
    if len(pairs) < 2:
        return None
    pairs.sort(key=lambda x: x[0])
    zl = pairs[0][1]
    if isinstance(zl, float) and zl != zl:  # NaN
        return None
    try:
        threshold = k * zl
    except TypeError:
        return None
    for rate, lat in pairs:
        try:
            if lat > threshold:
                return float(rate)
        except TypeError:
            continue
    return None
