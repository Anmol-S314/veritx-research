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

#: Machine-readable campaign ledgers beyond the V-experiments. Each is a
#: stable JSON document projected verbatim (selected fields); their
#: narrative context remains in the linked prose documents.
_MUTATIONS_DOC = "mutations.json"
_METAMORPHIC_DOC = "metamorphic.json"
_ENGINES_DOC = "engines.json"
_INTERVENTION_DOC = "intervention.json"


def _mutations_view(path: Path) -> dict[str, Any]:
    """Mutation ledger: every injected fault and whether the canonical
    gates caught it. A mutation caught=false would be a hole in the
    evidence chain — rendered as data, never upgraded."""
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValidationError(f"{path} is not a mutation ledger")
    return {
        "kind": "MUTATIONS",
        "document": path.name,
        "caught": sum(1 for r in rows if r.get("caught")),
        "total": len(rows),
        "mutations": [{
            "name": r.get("name"),
            "caught": bool(r.get("caught")),
            "expected": r.get("expected"),
            "detail": r.get("detail"),
        } for r in rows],
    }


def _metamorphic_view(path: Path) -> dict[str, Any]:
    """Metamorphic ledger: invariant probes (non-physical fields must not
    move physics) with pass state and observations verbatim."""
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValidationError(f"{path} is not a metamorphic ledger")
    return {
        "kind": "METAMORPHIC",
        "document": path.name,
        "passed": sum(1 for r in rows if r.get("passed")),
        "total": len(rows),
        "probes": [{
            "name": r.get("name"),
            "invariant": r.get("invariant"),
            "passed": bool(r.get("passed")),
            "detail": r.get("detail"),
            "observations": r.get("observations") or {},
        } for r in rows],
    }


def _engines_view(path: Path) -> dict[str, Any]:
    """Engine gate ledger: per-engine qualification batteries with
    per-check verdicts (e.g. the Ramulator 16/16 memory battery)."""
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValidationError(f"{path} is not an engine gate ledger")
    return {
        "kind": "ENGINES",
        "document": path.name,
        "engines": [{
            "name": r.get("name"),
            "passed": bool(r.get("passed")),
            "detail": r.get("detail"),
            "checks": [
                {"name": c[0], "passed": bool(c[1]), "detail":
                 (c[2] if len(c) > 2 else "")}
                for c in (r.get("checks") or [])
                if isinstance(c, (list, tuple)) and len(c) >= 2
            ],
        } for r in rows],
    }


def _intervention_view(path: Path) -> dict[str, Any]:
    """Intervention ledger: schedule perturbation rows with measured
    completions — the causal (not correlational) evidence for schedule
    binding. Verbatim rows; no verdict is recomputed."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValidationError(f"{path} is not an intervention ledger")
    return {
        "kind": "INTERVENTION",
        "document": path.name,
        "supported": bool(doc.get("supported")),
        "problems": list(doc.get("problems") or []),
        "rows": list(doc.get("rows") or []),
    }

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
        # Machine-readable campaign ledgers, projected verbatim (selected
        # fields). Prose campaigns are listed so Trust can link them; their
        # contents are intentionally absent from this view.
        "mutations": _mutations_view(reports_dir / _MUTATIONS_DOC),
        "metamorphic": _metamorphic_view(reports_dir / _METAMORPHIC_DOC),
        "engines": _engines_view(reports_dir / _ENGINES_DOC),
        "intervention": _intervention_view(reports_dir / _INTERVENTION_DOC),
        "prose_campaigns": [{"document": name} for name in PROSE_REPORTS],
        "findings_document": FINDINGS_DOC,
    }


__all__ = [
    "FINDINGS_DOC", "PROSE_REPORTS", "VALIDATION_REPORTS_DIR",
    "ValidationError", "validation_campaigns",
]
