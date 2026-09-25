#!/usr/bin/env python3
"""Fail if the release Dockerfile clones a moving ref (C8).

A `git clone` in the release image path must be pinned to an immutable
commit or a tag: either `--branch <ref>` or a `git checkout <sha>` /
`git fetch --depth 1 origin <sha>` + `git checkout FETCH_HEAD` in the same
RUN. `latest`/bare HEAD clones are refused.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = REPO_ROOT / "Dockerfile"


def _run_blocks(text: str) -> list[str]:
    """Logical RUN instructions (backslash-continued)."""
    blocks: list[str] = []
    current: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if current or line.startswith("RUN "):
            current.append(line)
        if line.endswith("\\"):
            continue
        if current:
            blocks.append("\n".join(current))
            current = []
    return blocks


def _pinned(block: str) -> bool:
    if "--branch" in block and "latest" not in block:
        return True
    if re.search(r"git checkout\s+[0-9a-f]{7,40}", block):
        return True
    if "FETCH_HEAD" in block and re.search(r"origin\s+[0-9a-f]{7,40}", block):
        return True
    return False


def main() -> int:
    text = DOCKERFILE.read_text(encoding="utf-8")
    offenders = []
    for block in _run_blocks(text):
        if "git clone" not in block:
            continue
        if not _pinned(block):
            offenders.append(block.splitlines()[0])
    if offenders:
        print("UNPINNED Dockerfile clone(s) — pin by commit/tag (C8):")
        for line in offenders:
            print(f"  {line}")
        return 1
    print("Dockerfile clones are pinned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
