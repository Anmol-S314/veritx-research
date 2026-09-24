"""P0.11: the legacy RT result readers stay out of production reachability.

``application/results.py`` keeps historical RT-vocabulary result readers
for the Wave-D/E seal tests. No production module (anything under
``veritx_dse`` other than that file) may import or call them.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

_LEGACY_IMPORT = re.compile(
    r"from\s+[\w.]*results\s+import\s+[^\n]*\b"
    r"load_verified_(result|attempt|experiment|comparison|study|studyrun)\b")
_LEGACY_CALL = re.compile(
    r"\bload_verified_(result|attempt|experiment|comparison|study|studyrun)\s*\(")
_OWNER = DSE / "veritx_dse" / "application" / "results.py"


def _production_files() -> list[Path]:
    return sorted(
        p for p in (DSE / "veritx_dse").rglob("*.py")
        if p != _OWNER and "__pycache__" not in p.parts)


def test_no_production_module_reaches_the_legacy_result_readers():
    offenders = []
    for path in _production_files():
        text = path.read_text(encoding="utf-8")
        for pattern in (_LEGACY_IMPORT, _LEGACY_CALL):
            for match in pattern.finditer(text):
                offenders.append((str(path.relative_to(DSE)), match.group(0)))
    assert not offenders, offenders


def test_canonical_design_loader_is_not_legacy():
    assert "load_verified_design" in _OWNER.read_text(encoding="utf-8")
