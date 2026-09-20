"""veritx_dse.application.legacy — historical-run migration policy.

Runs and result JSONs that predate Wave C are classified, never
rewritten. A legacy run can be listed and forensically inspected, but
it is never upgraded to a verified EvaluationResult: without the
complete Wave-B evidence chain (canonical inputs, producer identity,
EvidenceRef) there is nothing to verify.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def classify_legacy_run(path: str | Path) -> dict[str, Any]:
    """Classify one historical run directory or result file."""
    import json
    target = Path(path)
    if target.is_file() and target.suffix == ".json":
        try:
            doc = json.loads(target.read_text())
        except ValueError:
            return {"path": str(target), "class": "UNREADABLE",
                    "reason": "not valid JSON"}
        if isinstance(doc, dict) and doc.get("resource_type") == "result" \
                and "evidence_ref" in doc:
            return {"path": str(target), "class": "WAVE_C_RESULT",
                    "reason": "typed Wave-C result; verify via "
                              "verify_reusable_evidence"}
        return {"path": str(target), "class": "LEGACY_RESULT",
                "reason": "predates Wave-C evidence chain; inspectable, "
                          "never auto-upgraded to verified"}
    if target.is_dir():
        markers = ["manifest.json", "state.json", "plan.json",
                   "backend-evidence.json"]
        found = sorted(m.name for m in target.iterdir()
                       if m.name in markers) if target.exists() else []
        if not target.exists():
            return {"path": str(target), "class": "NOT_FOUND",
                    "reason": "no such run directory"}
        return {"path": str(target), "class": "LEGACY_RESULT",
                "reason": f"historical run dir (markers: {found}); "
                          f"inspectable, never auto-upgraded"}
    return {"path": str(target), "class": "NOT_FOUND",
            "reason": "no such path"}


__all__ = ["classify_legacy_run"]
