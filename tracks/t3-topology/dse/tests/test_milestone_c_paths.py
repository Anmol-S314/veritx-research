"""milestone_c.py resolves its real seams instead of dead paths.

``dse/scripts/milestone_c.py`` used to fail at import: it put ``dse/scripts``
on ``sys.path`` and then imported ``deadlock_routing`` (which lives under
``dse/veritx_dse/tools``), and its CDG check reached for the nonexistent
``dse/scripts/rtlgen``. The RTL generation seam is the track-level emitter at
``tracks/t3-topology/scripts/rtlgen/gen_rtl.py`` and its templates live with
the emitter under ``rtl/mot_htree``.

These pins make the reconciliation durable: the module imports, and its CDG
check resolves the real seam instead of degrading to ``import_unavailable``.

Rationale: docs/decisions/modules/tools.md
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_DSE = Path(__file__).resolve().parent.parent
_MILESTONE_C = _DSE / "scripts" / "milestone_c.py"

# milestone_c resolves ``veritx_dse`` through whatever editable install is on
# the path; put THIS checkout's dse root first so the package under test is
# the local one.
sys.path.insert(0, str(_DSE))

# A row-major 2x2 mesh: the certified-slice topology the seam accepts.
_TINY4 = {0: {1, 2}, 1: {0, 3}, 2: {0, 3}, 3: {1, 2}}


def _load_milestone_c():
    spec = importlib.util.spec_from_file_location("milestone_c", _MILESTONE_C)
    module = importlib.util.module_from_spec(spec)
    sys.modules["milestone_c"] = module
    spec.loader.exec_module(module)
    return module


def test_milestone_c_imports_and_locates_the_real_seam():
    # The import itself is the fix: `from deadlock_routing import parse_anynet`
    # now resolves. Then every path it hands to the RTL seam must be real.
    m = _load_milestone_c()
    assert (m._SEAM_DIR / "gen_rtl.py").is_file(), m._SEAM_DIR
    assert (m._EMITTER_DIR / "gen_rtl_htree.py").is_file(), m._EMITTER_DIR
    # Guardrail-hash verification hashes the emitted router template; it must
    # point at the emitter's copy, not a seam-dir file that does not exist.
    assert (m._EMITTER_DIR / "router_template.sv").is_file()


def test_milestone_c_cdg_check_resolves_the_seam():
    m = _load_milestone_c()
    acyclic, cycles, method = m.check_cdg_acyclic(_TINY4, 4)
    assert acyclic is True
    assert method != "import_unavailable"
