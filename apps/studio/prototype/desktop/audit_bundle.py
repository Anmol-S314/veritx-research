#!/usr/bin/env python3
"""Adversarial bundle audit: every repo-relative file the code reads at runtime
must exist inside the frozen app.

The failure this exists for: the shipped app refused to render an ASTRA fabric
configuration because the parser source it validates against
(`third_party/booksim2/src/booksim_config.cpp`) was not bundled. Nothing caught
it because the packaged tests drove the HTTP API, not that code path.

This resolves `REPO / "a" / "b"` path expressions (and module-level constants
built from them) to real files, reports which ones fall outside the resource
trees the freezer ships, and - given a bundle directory - which are literally
absent from it.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
DSE = REPO / "tracks/t3-topology/dse"

SHIPPED_TREES = [
    "docs/product", "contracts", "validation/experiments",
    "tracks/t3-topology/examples", "tracks/t3-topology/dse/inputs",
    "tracks/t3-topology/dse/models", "tracks/t3-topology/dse/qualification",
    "tracks/t3-topology/dse/docs", "tracks/t3-topology/dse/tests",
    "tracks/t3-topology/dse/veritx_dse",
]
# Shipped as individual files by gateway.spec / stage_resources.py.
SHIPPED_FILES = {
    "third_party/booksim2/src/booksim_config.cpp",
    "third_party/booksim2/src/booksim",
    "third_party/astra-sim/astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2",
    "third_party/ramulator2/python/ramulator",
}
ROOT_NAMES = {"REPO", "repo_root", "repo", "ROOT", "root"}


def flatten(node: ast.AST, strings: dict[str, str],
            chains: dict[str, list[str]]) -> list[str] | None:
    """Flatten `X / "a" / NAME` into ["<REPO>", "a", value], else None."""
    parts: list[str] = []
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        right = node.right
        if isinstance(right, ast.Constant) and isinstance(right.value, str):
            parts.append(right.value)
        elif isinstance(right, ast.Name) and right.id in strings:
            parts.append(strings[right.id])
        else:
            return None
        node = node.left
    tail = list(reversed(parts))
    if isinstance(node, ast.Name) and node.id in ROOT_NAMES:
        return ["<REPO>"] + tail
    if isinstance(node, ast.Attribute) and node.attr in ROOT_NAMES:
        return ["<REPO>"] + tail
    if isinstance(node, ast.Name) and node.id in chains:
        return chains[node.id] + tail
    return None


def scan() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(DSE.rglob("*.py")):
        if "__pycache__" in path.parts or "tests" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        where = str(path.relative_to(REPO))
        strings: dict[str, str] = {}
        chains: dict[str, list[str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    strings[name] = node.value.value
                else:
                    parts = flatten(node.value, strings, chains)
                    if parts:
                        chains[name] = parts
        for node in ast.walk(tree):
            parts = flatten(node, strings, chains)
            if parts is None and isinstance(node, ast.Name):
                parts = chains.get(node.id)
            if not parts or parts[0] != "<REPO>":
                continue
            relative = "/".join(parts[1:])
            if not relative or relative.startswith("runs"):
                continue
            found.setdefault(relative, set()).add(where)
    return found


def main() -> int:
    candidates = scan()
    existing, absent_in_repo = {}, []
    for relative, sources in sorted(candidates.items()):
        target = REPO / relative
        if target.exists():
            existing[relative] = sources
        else:
            absent_in_repo.append(relative)
    risky = {r: s for r, s in existing.items()
             if not any(r == t or r.startswith(t + "/") for t in SHIPPED_TREES)
             and r not in SHIPPED_FILES}
    print(f"resolved repo paths referenced by code: {len(candidates)}")
    print(f"  exist in repository: {len(existing)}")
    print(f"  do not exist (generated/optional at runtime): {len(absent_in_repo)}")
    print(f"  exist but OUTSIDE shipped trees/files: {len(risky)}")
    for relative, sources in sorted(risky.items()):
        print(f"    ! {relative}  <- {', '.join(sorted(sources)[:2])}")
    if len(sys.argv) > 1:
        bundle = Path(sys.argv[1])
        missing = []
        for relative in sorted(existing):
            if not (bundle / relative).exists():
                missing.append(relative)
        print(f"\nbundle {bundle}: {len(missing)} of {len(existing)} referenced files absent")
        for relative in missing[:60]:
            print(f"    - {relative}")
        return 1 if missing else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
