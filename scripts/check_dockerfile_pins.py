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


def _arg_defaults(text: str) -> dict[str, str]:
    defaults: dict[str, str] = {}
    for raw in text.splitlines():
        match = re.match(r"\s*ARG\s+([A-Za-z_][A-Za-z0-9_]*)=(\S+)", raw)
        if match:
            defaults[match.group(1)] = match.group(2)
    return defaults


def _from_pinned(ref: str, defaults: dict[str, str]) -> bool:
    """A base image is pinned only by an immutable ``@sha256:`` digest.

    A bare ``${ARG}`` is pinned when the ARG's default carries a digest.
    """
    ref = ref.strip()
    if "@sha256:" in ref:
        return True
    match = re.match(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", ref)
    if match:
        return "@sha256:" in defaults.get(match.group(1), "")
    return False


def main() -> int:
    text = DOCKERFILE.read_text(encoding="utf-8")
    defaults = _arg_defaults(text)
    offenders = []
    for raw in text.splitlines():
        match = re.match(r"\s*FROM\s+(\S+)", raw)
        if match and not _from_pinned(match.group(1), defaults):
            offenders.append(raw.strip())
    for block in _run_blocks(text):
        if "git clone" not in block:
            continue
        if not _pinned(block):
            offenders.append(block.splitlines()[0])
    if offenders:
        print("UNPINNED Dockerfile reference(s) — pin by digest/commit (C8):")
        for line in offenders:
            print(f"  {line}")
        return 1
    print("Dockerfile base image is digest-pinned and clones are pinned by commit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
