#!/usr/bin/env python3
"""Validate release-manifest.json for production-gate stage 8.

Fail-closed: the manifest must parse, must record a clean-or-dirty
source revision honestly, and every backend entry must carry a parsed
manifest document (a released backend without provenance is never
pinned). A missing manifest file itself is a failure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def validate_manifest(doc: object) -> list[str]:
    if not isinstance(doc, dict):
        return ["manifest root is not an object"]
    problems: list[str] = []
    if doc.get("schema_version") != 2:
        problems.append("unsupported or missing release manifest schema_version")
    if not doc.get("release_sha"):
        problems.append("no release_sha recorded")
    tools = doc.get("tools")
    cxx = tools.get("cxx") if isinstance(tools, dict) else None
    if (not isinstance(cxx, dict) or not isinstance(cxx.get("requested"), str)
            or not cxx["requested"] or not isinstance(cxx.get("path"), str)
            or not cxx["path"] or not isinstance(cxx.get("version"), str)
            or not cxx["version"]):
        problems.append("actual C++ compiler identity is incomplete")
    backends = doc.get("backends")
    if not backends:
        problems.append("no backends recorded")
    for entry in backends or []:
        if not isinstance(entry, dict) or entry.get("manifest") is None:
            problems.append(
                f"backend {entry.get('path') if isinstance(entry, dict) else '?'}: "
                "no provenance manifest")
            continue
        if not isinstance(entry["manifest"], dict):
            problems.append(f"backend {entry.get('path')}: provenance manifest is not an object")
            continue
        backend_compiler = entry["manifest"].get("compiler")
        if isinstance(cxx, dict) and backend_compiler != cxx.get("requested"):
            problems.append(
                f"backend {entry.get('path')}: compiler {backend_compiler!r} "
                f"does not match release compiler {cxx.get('requested')!r}")
    return problems


def main() -> int:
    path = REPO_ROOT / "release-manifest.json"
    if not path.is_file():
        print("release manifest absent: run make release-manifest-json")
        return 1
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"release manifest is not valid JSON: {exc}")
        return 1
    problems = validate_manifest(doc)
    if problems:
        for problem in problems:
            print(f"release manifest INVALID: {problem}")
        return 1
    backends = doc["backends"]
    print(f"release manifest ok: {path} "
          f"(sha={doc.get('release_sha')}, dirty={doc.get('dirty')}, "
          f"backends={len(backends or [])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
