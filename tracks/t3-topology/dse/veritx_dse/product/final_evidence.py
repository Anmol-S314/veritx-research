"""Read-only index of the recorded composed-family final-implementation evidence.

The evidence files are the product's own, checked-in acceptance records for the
`COMPOSED_FAMILY` scope (A1–A10). They are not research Verilog presence, not a
selected-project preview and not a physical signoff. This module exposes the
recorded rows and a computed verdict; it never infers a missing row or upgrades
a preview.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from veritx_dse.product.final_implementation import composed_family_verdict

EVIDENCE_ROOT = Path(__file__).resolve().parents[5] / "docs" / "product" / "evidence" / "final-implementation"
_ROWS: tuple[str, ...] = ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10")


def _measured(rows: dict[str, Any]) -> dict[str, Any]:
    picked: dict[str, Any] = {}
    for row in ("A1", "A2", "A8", "A9", "A10"):
        measured = (rows.get(row) or {}).get("measured")
        if measured:
            picked[row] = measured
    return picked


def composed_family_evidence() -> dict[str, Any]:
    families: list[dict[str, Any]] = []
    errors: list[str] = []
    if EVIDENCE_ROOT.is_dir():
        for path in sorted(EVIDENCE_ROOT.glob("*.json")):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
                family = str(document.get("family") or path.stem)
                rows = document.get("rows") or {}
                verdict = composed_family_verdict(family=family, evidence=rows)
                families.append({
                    "family": family,
                    "design_hash": document.get("design_hash"),
                    "final_implementation": verdict["final_implementation"],
                    "open_rows": verdict["open_rows"],
                    "scoped_out_rows": verdict["scoped_out_rows"],
                    "reason": verdict["reason"],
                    "rows": [
                        {"row": row["row"], "status": row["status"], "reason": row.get("reason")}
                        for row in verdict["rows"]
                    ],
                    "measured": _measured(rows),
                    "source": str(path.relative_to(EVIDENCE_ROOT.parents[3])),
                })
            except (OSError, ValueError, KeyError) as exc:
                errors.append(f"{path.name}: {exc}")
    return {
        "contract_version": 1,
        "scope": "COMPOSED_FAMILY",
        "families": families,
        "errors": errors,
        "note": (
            "Family-scoped composed evidence (A1–A10), keyed to the recorded design hash. "
            "It is not a selected-project preview, a different design's evidence does not "
            "transfer, and no physical implementation is claimed."
        ),
    }


__all__ = ["EVIDENCE_ROOT", "composed_family_evidence"]
