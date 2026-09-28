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
    problems: list[str] = []
    if not doc.get("release_sha"):
        problems.append("no release_sha recorded")
    backends = doc.get("backends")
    if not backends:
        problems.append("no backends recorded")
    for entry in backends or []:
        if entry.get("manifest") is None:
            problems.append(
                f"backend {entry.get('path')}: no provenance manifest "
                f"(sha={entry.get('sha256')})")
    if problems:
        for problem in problems:
            print(f"release manifest INVALID: {problem}")
        return 1
    print(f"release manifest ok: {path} "
          f"(sha={doc.get('release_sha')}, dirty={doc.get('dirty')}, "
          f"backends={len(backends or [])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
