"""P0.11: the legacy RT result readers stay out of production reachability.

``application/results.py`` keeps historical RT-vocabulary result readers
for the Wave-D/E seal tests. No production module (anything under
``veritx_dse`` other than that file) may reach them, including through an
aliased module import (``import ... as r; r.load_verified_result(...)``).
This is checked with the AST, not a text grep.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

_MODULE = "veritx_dse.application.results"
_LEGACY = frozenset({
    "load_verified_result", "load_verified_attempt",
    "load_verified_experiment", "load_verified_comparison",
    "load_verified_study", "load_verified_studyrun",
})
_OWNER = DSE / "veritx_dse" / "application" / "results.py"


def _production_files() -> list[Path]:
    return sorted(
        p for p in (DSE / "veritx_dse").rglob("*.py")
        if p != _OWNER and "__pycache__" not in p.parts)


def _offenders(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (
                node.module == _MODULE
                or (node.level >= 1 and node.module == "results")):
            for alias in node.names:
                if alias.name in _LEGACY:
                    found.append(f"direct import {alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _MODULE:
                    aliases.add(alias.asname or alias.name.rsplit(".", 1)[-1])
    # attribute access through an aliased module import
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _LEGACY \
                and isinstance(node.value, ast.Name) \
                and node.value.id in aliases:
            found.append(f"aliased call {node.value.id}.{node.attr}")
        if isinstance(node, ast.Name) and node.id in _LEGACY:
            # a bare name can only be a legacy reader if it was imported;
            # direct imports are already flagged above, so flag defensively.
            found.append(f"name {node.id}")
    return found


def test_no_production_module_reaches_the_legacy_result_readers():
    offenders = [(str(p.relative_to(DSE)), why)
                 for p in _production_files()
                 for why in _offenders(p)]
    assert not offenders, offenders


def test_canonical_design_loader_is_the_reachable_surface():
    text = _OWNER.read_text(encoding="utf-8")
    assert "def load_verified_design(" in text
    # the legacy readers are present but documented as legacy/test-only
    assert "LEGACY BOUNDARY" in text
