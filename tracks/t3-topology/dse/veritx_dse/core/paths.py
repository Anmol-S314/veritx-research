"""veritx_dse.core.paths — Single source of truth for all path resolution.

Instead of fragile parent.parent.parent chains, this module discovers
the repo root from the package location and exports all key paths.

Usage:
    from veritx_dse.core.paths import REPO, BOOKSIM_BIN, DSE_DIR
"""

from pathlib import Path

# ── Discover repo root from package location ─────────────────────────────
# veritx_dse/ lives at: <repo>/tracks/t3-topology/dse/veritx_dse/
# So 5 levels up from this file = repo root
_THIS_DIR = Path(__file__).resolve().parent          # core/
_PARENT = _THIS_DIR.parent                           # veritx_dse/
_DSE_DIR = _PARENT.parent                            # dse/
_T3_DIR = _DSE_DIR.parent                            # t3-topology/
_TRACKS_DIR = _T3_DIR.parent                         # tracks/
REPO = _TRACKS_DIR.parent                            # veritx-research/

# ── Key directories ─────────────────────────────────────────────────────
DSE_DIR = _DSE_DIR
RUNS_DIR = REPO / "runs"
TRACES_DIR = RUNS_DIR / "traces"
BOOKSIM_DIR = REPO / "third_party" / "booksim2" / "src"
ASTRA_DIR = REPO / "serving" / "astra-sim"
LLMSIM_DIR = REPO / "serving" / "LLMServingSim"

# ── Key binaries ────────────────────────────────────────────────────────
BOOKSIM_BIN = BOOKSIM_DIR / "booksim"
ASTRA_BS_BIN = (
    ASTRA_DIR / "astra-sim" / "network_frontend"
    / "booksim2" / "bin" / "AstraSim_BookSim2"
)
CHAKRA_TO_ET = ASTRA_DIR / "astra-sim" / "bin" / "chakra_to_et"

# ── Verify paths exist at import time ───────────────────────────────────
def _verify():
    """Check that critical paths exist. Called once at import."""
    assert REPO.exists(), f"REPO not found: {REPO}"
    assert DSE_DIR.exists(), f"DSE_DIR not found: {DSE_DIR}"
    # BOOKSIM_BIN may not be built yet — that's OK

