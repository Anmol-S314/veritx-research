"""veritx_dse.core.paths — Single source of truth for all path resolution.

Rationale: docs/decisions/modules/core.md
"""

from pathlib import Path
import sys

_THIS_DIR = Path(__file__).resolve().parent
_PARENT = _THIS_DIR.parent
_DSE_DIR = _PARENT.parent
_T3_DIR = _DSE_DIR.parent
_TRACKS_DIR = _T3_DIR.parent
REPO = _TRACKS_DIR.parent

DSE_DIR = _DSE_DIR
RUNS_DIR = REPO / "runs"
VERITX_RUNS_DIR = RUNS_DIR / "veritx-runs"
RESULTS_DIR = _T3_DIR / "results"
TRACES_DIR = RUNS_DIR / "traces"
BOOKSIM_DIR = REPO / "third_party" / "booksim2" / "src"
ASTRA_DIR = REPO / "third_party" / "astra-sim"
LLMSIM_DIR = REPO / "third_party" / "llmservingsim"

def new_run_dir(command: str, seed: int | None = None, root: Path | None = None) -> Path:
    """Timestamped, seed-stamped run directory for one veritx invocation:

Rationale: docs/decisions/modules/core.md
    """
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    home = Path(root) if root is not None else RESULTS_DIR
    base = home / command / f"{ts}_seed{0 if seed is None else seed}"
    d = base
    i = 2
    while d.exists():
        d = base.with_name(f"{base.name}_{i}")
        i += 1
    d.mkdir(parents=True)
    return d

_EXECUTABLE_SUFFIX = ".exe" if sys.platform == "win32" else ""
BOOKSIM_BIN = BOOKSIM_DIR / f"booksim{_EXECUTABLE_SUFFIX}"
ASTRA_BS_BIN = (
    ASTRA_DIR / "astra-sim" / "network_frontend"
    / "booksim2" / "bin" / f"AstraSim_BookSim2{_EXECUTABLE_SUFFIX}"
)
CHAKRA_TO_ET = ASTRA_DIR / "astra-sim" / "bin" / f"chakra_to_et{_EXECUTABLE_SUFFIX}"

def _verify():
    """Check that critical paths exist. Called once at import."""
    assert REPO.exists(), f"REPO not found: {REPO}"
    assert DSE_DIR.exists(), f"DSE_DIR not found: {DSE_DIR}"

