"""veritx_dse.core.paths — Single source of truth for all path resolution.

Instead of fragile parent.parent.parent chains, this module discovers
the repo root from the package location and exports all key paths.

Usage:
    from veritx_dse.core.paths import REPO, BOOKSIM_BIN, DSE_DIR
"""

from pathlib import Path

# ── Discover repo root from package location ─────────────────────────────
# veritx_dse/ lives at: <repo>/tracks/t3-topology/dse/veritx_dse/
# (dse inputs live in dse/archive/inputs/ — the live trace stash)
# So 5 levels up from this file = repo root
_THIS_DIR = Path(__file__).resolve().parent          # core/
_PARENT = _THIS_DIR.parent                           # veritx_dse/
_DSE_DIR = _PARENT.parent                            # dse/
_T3_DIR = _DSE_DIR.parent                            # t3-topology/
_TRACKS_DIR = _T3_DIR.parent                         # tracks/
REPO = _TRACKS_DIR.parent                            # veritx-research/

# ── Key directories ─────────────────────────────────────────────────
DSE_DIR = _DSE_DIR
RUNS_DIR = REPO / "runs"
# Immutable run directories (ADR 0001/0003): one dir per realized execution,
# namespaced away from the legacy runs/ booksim|traces|experiments output.
VERITX_RUNS_DIR = RUNS_DIR / "veritx-runs"
RESULTS_DIR = _T3_DIR / "results"
TRACK_RUNS_DIR = _T3_DIR / "runs"
# SYNTH_DIR: the one home for synthesis winners + results (BO/iterative
# topo.anynet, bo_results_N*.json) — the dir the t3 pickers scan first.
# REPO runs/booksim remains as a legacy second home (pickers scan both).
SYNTH_DIR = TRACK_RUNS_DIR / "booksim"
TRACES_DIR = RUNS_DIR / "traces"
BOOKSIM_DIR = REPO / "third_party" / "booksim2" / "src"
ASTRA_DIR = REPO / "third_party" / "astra-sim"
LLMSIM_DIR = REPO / "third_party" / "llmservingsim"


def new_run_dir(command: str, seed: int | None = None, root: Path | None = None) -> Path:
    """Timestamped, seed-stamped run directory for one veritx invocation:

        <root>/<command>/<YYYYmmdd_HHMMSS>_seed<seed>/

    root defaults to RESULTS_DIR; t3 passes results/<CONFIG> so guided runs
    co-locate with their CONFIG instead of scattering across results/.
    Every command writes its result JSON *inside* its run dir (never
    overwriting a previous run), the seed sits in the name for
    reproducibility, and results/ is the single results home — one layout
    for every command. A _2 suffix breaks same-second collisions.
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

