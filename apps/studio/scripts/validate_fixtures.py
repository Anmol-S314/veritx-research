#!/usr/bin/env python3
"""Validate every Studio fixture against the frozen contracts.

For each apps/studio/fixtures/*.json (except the generator itself):
  1. Each non-null view validates against contracts/srota/v1/*.schema.json
     (Draft 2020-12, local files only — no network).
  2. Cross-view linkage: design_hash consistent across design/compilation/
     evaluation/requirements; optimization.base_design_hash matches;
     requirements.performance_result_id matches evaluation's (when both
     present); EVALUATED outcomes carry their required bindings.

Exit 0 iff all fixtures pass. Studio boots from fixtures only, so this is
the gate that keeps the UI honest.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

STUDIO = Path(__file__).resolve().parent.parent  # apps/studio
REPO = STUDIO.parent.parent  # workspace root
SCHEMAS = REPO / "contracts" / "srota" / "v1"
FIXTURE_DIR = STUDIO / "fixtures"

VIEW_SCHEMAS = {
    "design": "design.view.schema.json",
    "compilation": "compilation.view.schema.json",
    "evaluation": "evaluation.view.schema.json",
    "requirements": "requirement.report.schema.json",
    "optimization": "optimization.study.view.schema.json",
}

EXPECTED_FIXTURES = {
    "compiled-mesh",
    "invalid-design",
    "backend-unavailable",
    "evaluated-design",
    "optimization-study",
}


def load_schema(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text())


def check_linkage(doc: dict, errors: list[str]) -> None:
    fid = doc.get("fixture_id", "?")
    design = doc.get("design") or {}
    dh = design.get("design_hash")
    comp = doc.get("compilation")
    if comp and comp.get("design_hash") != dh:
        errors.append(f"{fid}: compilation.design_hash != design.design_hash")
    ev = doc.get("evaluation")
    if ev:
        if ev.get("design_hash") != dh:
            errors.append(f"{fid}: evaluation.design_hash != design.design_hash")
        if ev.get("status") == "EVALUATED":
            for key in (
                "message_artifact_id",
                "physical_traffic_id",
                "backend_producer",
                "evidence",
                "performance_result_id",
                "network_traffic_window",
            ):
                if ev.get(key) is None:
                    errors.append(f"{fid}: EVALUATED missing {key}")
        if ev.get("status") in ("BACKEND_UNAVAILABLE", "FAILED", "UNSUPPORTED"):
            if ev.get("metrics") is not None:
                errors.append(
                    f"{fid}: {ev['status']} must not carry metrics "
                    "(absent metrics are absent, never zero-filled)"
                )
    req = doc.get("requirements")
    if req:
        if req.get("design_hash") != dh:
            errors.append(f"{fid}: requirements.design_hash != design.design_hash")
        if ev and ev.get("performance_result_id") and (
            req.get("performance_result_id") != ev["performance_result_id"]
        ):
            errors.append(f"{fid}: requirements.performance_result_id != evaluation's")
    opt = doc.get("optimization")
    if opt and opt.get("base_design_hash") != dh:
        errors.append(f"{fid}: optimization.base_design_hash != design.design_hash")


def validate_one(path: Path, validators: dict[str, Draft202012Validator]) -> list[str]:
    errors: list[str] = []
    try:
        doc = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return [f"{path.name}: unreadable ({exc})"]
    for view, validator in validators.items():
        payload = doc.get(view)
        if payload is None:
            continue
        for err in validator.iter_errors(payload):
            errors.append(f"{path.name}:{view}: {list(err.path)}: {err.message}")
    if not errors:
        check_linkage(doc, errors)
    return errors


def main() -> int:
    validators = {v: Draft202012Validator(load_schema(s)) for v, s in VIEW_SCHEMAS.items()}
    found = sorted(p.stem for p in FIXTURE_DIR.glob("*.json"))
    errors: list[str] = []
    if set(found) != EXPECTED_FIXTURES:
        errors.append(
            f"fixture set mismatch: found {found}, expected {sorted(EXPECTED_FIXTURES)}"
        )
    for stem in sorted(EXPECTED_FIXTURES):
        path = FIXTURE_DIR / f"{stem}.json"
        if not path.exists():
            errors.append(f"missing fixture {stem}.json")
            continue
        view_errors = validate_one(path, validators)
        if view_errors:
            errors.extend(view_errors)
        else:
            print(f"PASS {stem}.json (views + linkage)")
    if errors:
        print("FAIL:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"All {len(EXPECTED_FIXTURES)} fixtures validate against contracts/srota/v1.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
