"""veritx_dse.product.qualification — one machine-readable authority.

The Studio and the gateway both read ``docs/production/ENGINE-QUALIFICATION.json``.
Neither parses the prose markdown at runtime, and neither carries a
hand-copied duplicate (the drift the audit flagged in
``gateway/qualification.py``).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from veritx_dse.core.paths import REPO

QUALIFICATION_JSON = REPO / "docs" / "production" / "ENGINE-QUALIFICATION.json"


class QualificationError(ValueError):
    """The qualification authority is missing or malformed."""


def load_qualification(path: Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else QUALIFICATION_JSON
    if not target.is_file():
        raise QualificationError(
            f"engine qualification authority not found: {target}")
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationError(
            f"engine qualification authority is unreadable: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(
            document.get("engines"), dict):
        raise QualificationError(
            "engine qualification authority must carry an 'engines' object")
    return document


@lru_cache(maxsize=1)
def qualification_view() -> dict[str, Any]:
    """The v1 qualification view served to Studio."""
    document = load_qualification()
    return {
        "contract_version": 1,
        "validation_sha": document.get("validation_sha"),
        "engines": document["engines"],
        "workload_levels": document.get("workload_levels", {}),
    }


__all__ = [
    "QUALIFICATION_JSON", "QualificationError", "load_qualification",
    "qualification_view",
]
