"""veritx_dse.product.validation — machine-readable validation authority.

Projects ``validation/reports/V*.json`` (machine-readable experiment
reports) into a stable ValidationCampaignView for the Trust page. The
Markdown campaign reports (MUTATIONS / METAMORPHIC / INTERVENTION /
ENGINES) and FINDINGS.md are referenced by link, never parsed: prose is
unstable and the program forbids building UI on unstable prose (§34).
Where a finding is referenced by a machine-readable check, its id is
surfaced as data; the narrative lives in the linked document.

Projection rules (§48): select fields, group checks, attach presentation
labels. Verdicts, independence classes and quarantine state are copied
verbatim from the reports — never recomputed, never upgraded.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from veritx_dse.core.paths import REPO

VALIDATION_REPORTS_DIR = REPO / "validation" / "reports"

#: Machine-readable campaign reports: rendered as structured data.
_EXPERIMENT_GLOB = "V*.json"

#: Prose campaign reports: linked, never parsed (§34).
PROSE_REPORTS = (
    "MUTATIONS.md", "METAMORPHIC.md", "INTERVENTION.md",
    "ENGINES.md", "PRODUCTION-WORKLOAD-TRUST.md",
)
FINDINGS_DOC = "FINDINGS.md"


class ValidationError(ValueError):
    """The validation authority directory is missing or malformed."""


def _load_report(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{path} is unreadable: {exc}") from exc
    if not isinstance(doc, dict) or not doc.get("id"):
        raise ValidationError(f"{path} is not a validation report")
    return doc


def _check_view(check: dict[str, Any]) -> dict[str, Any]:
    """One check row: identity + verdict + the evidence it already carries."""
    return {
        "name": check.get("name"),
        "authority_class": check.get("authority_class"),
        "independence": check.get("independence"),
        "verdict": check.get("verdict"),
        "detail": check.get("detail"),
        "values": check.get("values"),
        "finding": check.get("finding"),
        "quarantined": bool(check.get("quarantined")),
    }


def _experiment_view(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": doc["id"],
        "title": doc.get("title"),
        "status": doc.get("status"),
        "passed": bool(doc.get("passed")),
        "workload": doc.get("workload"),
        "profile_id": doc.get("profile_id"),
        "fabric": doc.get("fabric"),
        "authority": doc.get("authority"),
        "veritx": doc.get("veritx"),
        "sweep": doc.get("sweep"),
        "quarantined_findings": doc.get("quarantined_findings") or [],
        "checks": [_check_view(c) for c in doc.get("checks", [])],
    }


@lru_cache(maxsize=1)
def validation_campaigns() -> dict[str, Any]:
    """The v1 ValidationCampaignView served to Studio."""
    reports_dir = Path(VALIDATION_REPORTS_DIR)
    if not reports_dir.is_dir():
        raise ValidationError(
            f"validation reports directory not found: {reports_dir}")
    experiments = [
        _experiment_view(_load_report(path))
        for path in sorted(reports_dir.glob(_EXPERIMENT_GLOB))
    ]
    if not experiments:
        raise ValidationError(
            f"no machine-readable experiment reports in {reports_dir}")
    return {
        "contract_version": 1,
        "experiments": experiments,
        # Prose campaigns are listed so Trust can link them; their
        # contents are intentionally absent from this view.
        "prose_campaigns": [{"document": name} for name in PROSE_REPORTS],
        "findings_document": FINDINGS_DOC,
    }


__all__ = [
    "FINDINGS_DOC", "PROSE_REPORTS", "VALIDATION_REPORTS_DIR",
    "ValidationError", "validation_campaigns",
]
