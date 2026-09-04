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
        T3_SCRIPTS   — override for scripts directory
    """
    track   = TRACK
    results = Path(os.environ.get("T3_RESULTS", track / "results"))
    scripts = Path(os.environ.get("T3_SCRIPTS", HERE))
    results.mkdir(parents=True, exist_ok=True)
    return {
        "t3_dir":  track,
        "repo":    REPO,
        "track":   track,
        "scripts": scripts,
        "results": results,
        "output":  results,
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


# ---------------------------------------------------------------------------
# Output path helper
# ---------------------------------------------------------------------------

def output_path(filename: str, paths: Optional[dict] = None) -> Path:
    """Return a writable path under T3_RESULTS (creates dir if needed)."""
    p = paths or resolve_paths()
    dest = p["results"] / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest
