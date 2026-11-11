"""T3 Topology — shared utilities used by analysis.py, aggregate.py, plot_curves.py.

Import pattern:
    from utils import resolve_paths, load_json, git_sha, sat_k, packet_size_bits

Path resolution strategy
------------------------
1. If the T3_DIR environment variable is set (exported by run/env.sh), it is
   used as the authoritative track root.  All other T3_* env-vars are also
   honoured as overrides.
2. If T3_DIR is unset the path is derived from this file's own location
   (__file__ → scripts/ → t3-topology/).  This keeps the scripts runnable
   without sourcing env.sh (e.g. during unit tests).
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Canonical paths  (all resolved relative to T3_DIR env-var or this file)
# ---------------------------------------------------------------------------

HERE     = Path(__file__).parent            # scripts/
_T3_DIR_ENV = os.environ.get("T3_DIR")
TRACK    = Path(_T3_DIR_ENV) if _T3_DIR_ENV else HERE.parent   # tracks/t3-topology/
REPO     = TRACK.parent.parent             # veritx-research/

def resolve_paths() -> dict:
    """Return a dict of all canonical project paths, honoring env-var overrides.

    Env-vars respected (all optional — all exported by run/env.sh):
        T3_DIR       — track root directory (t3-topology/)
        T3_RESULTS   — override for results directory
        T3_OUTPUT    — override for writable output directory (default: same as results)
        T3_SCRIPTS   — override for scripts directory
    """
    track   = TRACK
    results = Path(os.environ.get("T3_RESULTS", track / "results"))
    output  = Path(os.environ.get("T3_OUTPUT", results))
    scripts = Path(os.environ.get("T3_SCRIPTS", HERE))
    results.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    return {
        "t3_dir":  track,
        "repo":    REPO,
        "track":   track,
        "scripts": scripts,
        "results": results,
        "output":  output,
        "sweep":   results / "topology_sweep.json",
        "history": results / "history.json",
        "energy":  results / "energy.json",
        "matrix":  results / "traffic_matrix.txt",
    }


# ---------------------------------------------------------------------------
# Environment-variable tunables
# ---------------------------------------------------------------------------

def packet_size_bits() -> int:
    """Energy proxy constant: hops_avg × this = energy_proxy."""
    return int(os.environ.get("PACKET_SIZE_BITS", 128))

def sat_k() -> float:
    """Saturation threshold: latency > k × zero_load → saturated."""
    return float(os.environ.get("SAT_K", 2.0))

def sweep_rates() -> list[float]:
    """Injection rate sweep list from RATES env-var."""
    raw = os.environ.get("RATES", "0.002,0.005,0.01,0.02,0.03")
    return [float(r) for r in raw.split(",")]


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def load_json(path: Path) -> list | dict:
    """Load JSON, raising FileNotFoundError with a helpful message if missing."""
    if not path.exists():
        raise FileNotFoundError(
            f"File not found: {path}\n"
            "  Have you run 'make sim' (or 't3 sim') to generate results?"
        )
    return json.loads(path.read_text())


def save_json(data: list | dict, path: Path, *, indent: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=indent))


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def git_sha(cwd: Optional[Path] = None, default: str = "local") -> str:
    """Return the short HEAD commit SHA, or *default* if git is unavailable."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(cwd or REPO),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return default


def git_info(cwd: Optional[Path] = None) -> dict:
    """Return {sha, msg, date} for the current HEAD commit."""
    def _g(args: list, default: str = "") -> str:
        try:
            return subprocess.check_output(
                args, cwd=str(cwd or REPO), text=True, stderr=subprocess.DEVNULL
            ).strip()
        except Exception:
            return default

    return {
        "sha":  _g(["git", "rev-parse", "--short", "HEAD"], "local"),
        "msg":  _g(["git", "log", "-1", "--format=%s"], "(uncommitted)")[:60],
        "date": _g(["git", "log", "-1", "--format=%cd", "--date=short"], ""),
    }


# ---------------------------------------------------------------------------
# Saturation logic  (shared between analysis.py, plot_curves.py, dashboard)
# ---------------------------------------------------------------------------

def saturation_point(
    rates: list[float],
    latencies: list[float],
    k: Optional[float] = None,
) -> Optional[float]:
    """Return the first injection rate where latency exceeds k × zero-load.

    Parameters
    ----------
    rates     : sorted list of injection rates
    latencies : corresponding latency values (same length, same order)
    k         : threshold multiplier; defaults to SAT_K env-var (default 2.0)

    Returns
    -------
    float | None — saturation rate, or None if not reached within the data.
    """
    _k = k if k is not None else sat_k()
    if len(rates) < 2:
        return None
    zero_load = latencies[0]
    threshold = _k * zero_load
    for rate, lat in zip(rates, latencies):
        if lat > threshold:
            return rate
    return None


def saturation_point_gradient(
    rates: list[float],
    latencies: list[float],
    slope_k: float = 5.0,
) -> Optional[float]:
    """Detect saturation via latency-slope analysis (knee detection).

    Instead of a fixed absolute threshold (k × zero-load), this looks at the
    *rate of change* of latency between consecutive sweep points.  When the
    slope of the latency-vs-rate curve exceeds ``slope_k`` times the initial
    (low-load) slope, the network is entering saturation — regardless of the
    absolute latency value.

    This adapts to each topology's natural curve shape: a topology with high
    zero-load latency (e.g. qtree at 39 cycles) and one with low zero-load
    (e.g. fly4 at 16 cycles) will be detected correctly as long as both
    exhibit a steep rise at saturation.

    Parameters
    ----------
    rates      : sorted (ascending) injection rates
    latencies  : corresponding latency values (same length)
    slope_k    : a saturation is flagged when a segment's slope exceeds
                 slope_k × the first segment's slope.  Default 5.0.

    Returns
    -------
    float | None — the injection rate at the start of the steep-rise segment,
                   or None if no such jump is detected.
    """
    if len(rates) < 3:
        return None

    # Compute per-segment slopes  (Δlatency / Δrate)
    segments: list[tuple[float, float]] = []
    for i in range(1, len(rates)):
        dr = rates[i] - rates[i - 1]
        if dr <= 0:
            continue
        dl = latencies[i] - latencies[i - 1]
        segments.append((rates[i], dl / dr))

    if len(segments) < 2:
        return None

    # Baseline slope = first segment (lowest-load region)
    base = abs(segments[0][1])
    if base < 1e-9:
        base = 1e-9   # guard against perfectly flat initial region

    for rate, slope in segments[1:]:
        if slope > 0 and slope / base > slope_k:
            return rate

    return None


# ---------------------------------------------------------------------------
# Output path helper
# ---------------------------------------------------------------------------

def output_path(filename: str, paths: Optional[dict] = None) -> Path:
    """Return a writable output path under T3_OUTPUT (creates dir if needed)."""
    p = paths or resolve_paths()
    dest = p["output"] / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest
