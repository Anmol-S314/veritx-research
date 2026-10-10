"""Executed-configuration evidence index.

Search has already produced evidence: two sweep cohorts hold executed cases
with their authored requests, certificates and measured metrics. The editor
should show what was MEASURED for a configuration, not only what may be
typed. This module assembles that corpus into one index.

It is intentionally shape-agnostic: a case's knobs are read as "the values
this request actually set" by walking the document, never from a per-case
field list, so a new knob is indexed the moment a sweep exercises it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from veritx_dse.core.paths import REPO

#: Coherent cohorts, newest last. A missing directory is skipped, never
#: invented: an absent cohort is an absent fact, not an empty one.
COHORTS: tuple[tuple[str, str], ...] = (
    ("config-sweep", "20261008-summary.json"),
    ("knob-sweep", "20261009-final"),
    ("router-controls", "20261009"),
)

#: Request keys that carry authored knobs. Which FIELDS inside them are
#: knobs is decided by reading what the request set, not by a list here.
_KNOB_BLOCKS = ("noc_controls", "noc_config", "topology")


def _authored(block: Any) -> dict[str, Any]:
    """Only values the document actually set (non-null)."""
    if not isinstance(block, dict):
        return {}
    return {k: v for k, v in block.items() if v is not None}


def knobs_of(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        return {}
    out: dict[str, Any] = {}
    for key in _KNOB_BLOCKS:
        values = _authored(request.get(key))
        if values:
            out[key] = values
    return out


def _metrics(analyses: Any) -> dict[str, Any]:
    """Measured numbers, keyed by evaluation question. Only what executed."""
    out: dict[str, Any] = {}
    for entry in analyses if isinstance(analyses, list) else []:
        if not isinstance(entry, dict):
            continue
        question = entry.get("question")
        if not question:
            continue
        row = {
            "status": entry.get("status"),
            "backend": entry.get("backend_id"),
            "qualification": entry.get("qualification"),
            "fidelity": entry.get("model_fidelity"),
        }
        summary = entry.get("native_summary") or entry.get("metrics") or {}
        if isinstance(summary, dict):
            row["metrics"] = {
                k: v for k, v in summary.items() if isinstance(v, (int, float))
            }
        out[question] = row
    return out


def _walk_case_dir(directory: Path) -> dict[str, Any] | None:
    """One case directory: its authored knobs and whatever outcome it recorded.

    Layout is uniform across cohorts, so one walker serves all of them and a
    new cohort needs no code here. A directory with no request is not a case.
    """
    request_path = directory / "request.json"
    if not request_path.is_file():
        return None
    try:
        document = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    case: dict[str, Any] = {
        "case_id": directory.name,
        "status": None, "reason": None, "stage": None,
        "design_hash": None, "certificate": None,
        "knobs": knobs_of(document.get("request", document)),
        "analyses": {}, "seconds": None,
    }
    for name in ("result.json", "result"):
        path = directory / name
        if not path.is_file():
            continue
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            break
        if not isinstance(result, dict):
            break
        case["status"] = result.get("status", case["status"])
        case["reason"] = result.get("reason", case["reason"])
        case["stage"] = result.get("stage", case["stage"])
        case["design_hash"] = result.get("design_hash", case["design_hash"])
        case["seconds"] = result.get("seconds", case["seconds"])
        case["analyses"] = _metrics(result.get("analyses"))
        artifacts = result.get("artifacts")
        if isinstance(artifacts, dict):
            case["certificate"] = artifacts.get("certificate")
        break
    return case


def _walk_cohort(root: Path, depth: int = 2) -> list[dict[str, Any]]:
    """Every case directory under a cohort root, at one or two levels."""
    if not root.is_dir():
        return []
    found: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        direct = _walk_case_dir(child)
        if direct is not None:
            found.append(direct)
            continue
        if depth > 1:
            found.extend(_walk_cohort(child, depth - 1))
    return found


def _case_from_knob_cohort(root: Path) -> list[dict[str, Any]]:
    summary = root / "results.json"
    if not summary.is_file():
        return []
    try:
        cases = json.loads(summary.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out: list[dict[str, Any]] = []
    for case in cases if isinstance(cases, list) else []:
        if not isinstance(case, dict):
            continue
        directory = root / str(case.get("name", ""))
        knobs: dict[str, Any] = {}
        request = directory / "request.json"
        if request.is_file():
            try:
                document = json.loads(request.read_text(encoding="utf-8"))
                knobs = knobs_of(document.get("request", document))
            except (OSError, json.JSONDecodeError):
                knobs = {}
        out.append({
            "case_id": str(case.get("name", "")),
            "status": case.get("status"),
            "reason": case.get("reason"),
            "stage": case.get("stage"),
            "design_hash": case.get("design_hash"),
            "certificate": (case.get("artifacts") or {}).get("certificate"),
            "knobs": knobs,
            "analyses": _metrics(case.get("analyses")),
            "seconds": case.get("seconds"),
        })
    return out


def _case_from_config_cohort(root: Path, doc: Any) -> list[dict[str, Any]]:
    cases = doc.get("cases") if isinstance(doc, dict) else None
    if not isinstance(cases, list):
        return []
    out: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        network = case.get("verified_network") or {}
        analyses = _metrics(case.get("analyses"))
        if isinstance(network, dict) and network:
            analyses.setdefault("NETWORK_COMPLETION", {
                "status": "EVALUATED",
                "profile": network.get("profile"),
                "fidelity": network.get("fidelity"),
                "metrics": {
                    k: v for k, v in network.items() if isinstance(v, (int, float))
                },
            })
        out.append({
            "case_id": str(case.get("name", "")),
            "status": case.get("status"),
            "reason": case.get("reason"),
            "stage": case.get("stopped_at"),
            "design_hash": case.get("design_hash"),
            "certificate": case.get("certificate"),
            "knobs": {},
            "routers": case.get("routers"),
            "channels": case.get("channels"),
            "analyses": analyses,
            "seconds": case.get("seconds"),
        })
    return out


def evidence_index() -> dict[str, Any]:
    cohorts: list[dict[str, Any]] = []
    total = 0
    for name, target in COHORTS:
        root = REPO / "runs" / name / target if (REPO / "runs" / name).is_dir() else None
        cases: list[dict[str, Any]] = []
        if root is not None:
            if name == "knob-sweep":
                # The generic walker reads the per-case directories, which are
                # the same evidence the cohort summary summarises.
                cases = _walk_cohort(root)
            elif name == "router-controls":
                cases = _walk_cohort(root)
            else:
                path = root / target if root.is_dir() else root
                if path.is_file():
                    try:
                        cases = _case_from_config_cohort(root.parent, json.loads(
                            path.read_text(encoding="utf-8")))
                    except (OSError, json.JSONDecodeError):
                        cases = []
        total += len(cases)
        cohorts.append({
            "cohort": name,
            "cases": cases,
            "evaluated": sum(1 for c in cases if c.get("status") == "EVALUATED"),
        })
    return {
        "type": "veritx/ExecutionEvidence/v1",
        "cohorts": cohorts,
        "case_count": total,
        "notes": (
            "Executed configurations recorded by the sweep cohorts, with the "
            "knobs each request actually authored. A case here is evidence "
            "that its configuration reached a measured outcome; absence is "
            "absence of evidence, not a refusal."
        ),
    }


def match_case(knobs: dict[str, Any], case_knobs: dict[str, Any]) -> dict[str, Any]:
    """Compare two authored-knob maps. Returns agreement and disagreements.

    Structural: it compares whatever keys both sides set. No knob name is
    known here, so a knob added tomorrow is compared the day it appears in
    both a draft and a case.
    """
    agreed: dict[str, Any] = {}
    conflicts: dict[str, Any] = {}
    compared = 0
    for block, values in knobs.items():
        other = case_knobs.get(block)
        if not isinstance(other, dict):
            continue
        for name, value in values.items():
            if name not in other:
                continue
            compared += 1
            (agreed if other[name] == value else conflicts).setdefault(block, {})[name] = {
                "draft": value, "case": other[name],
            }
    return {"compared": compared, "agreed": agreed, "conflicts": conflicts}