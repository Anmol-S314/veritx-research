#!/usr/bin/env python3
"""Fail-closed guard: every third-party import in `veritx_dse` must be
resolvable from tracked sources or a declared dependency (Gate 2).

`tracks/t3-topology/dse/pyproject.toml` is the canonical dependency
declaration. Workstation-global packages must never be relied on
implicitly: the release container only contains what is declared there
plus what the Dockerfile installs.

Resolution order for a top-level import:
  1. stdlib (`sys.stdlib_module_names`) or `veritx_dse` itself → OK;
  2. repo-local module (a basename under `veritx_dse/`, `dse/scripts/`,
     or a package under `third_party/llmservingsim/`) — these ride
     sys.path hacks or PYTHONPATH from tracked sources → OK;
  3. generated stubs (`chakra`, built from tracked astra protos) → OK;
  4. otherwise the import's dist must be in [project] dependencies
     (non-test code) or dependencies + dev extras (tests).

The known runtime surface (pydantic, fastapi, yaml, numpy, scipy,
scikit-optimize) must be both imported AND declared; the final loop
fails if an import exists without a declaration.

Python 3.10 compatible (no tomllib).

Exit 0 when clean, 1 with a violation list otherwise.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DSE = REPO_ROOT / "tracks" / "t3-topology" / "dse"
PKG = DSE / "veritx_dse"
SCRIPTS = DSE / "scripts"
LLMSIM = REPO_ROOT / "third_party" / "llmservingsim"
PYPROJECT = DSE / "pyproject.toml"

GENERATED_STUBS = {
    "chakra": "generated from third_party/astra-sim protos via protoc "
              "(third_party/astra-sim/build/astra_booksim2/build.sh); "
              "shipped at /usr/local/share/chakra",
}

OPTIONAL_FALLBACK = {
    "gen_rtl": "tracks/t3-topology/scripts/rtlgen helper absent in-tree; "
               "tools/flow_certifier.check_cdg_acyclic falls back to "
               "link-level CDG with an explicit 'import_unavailable' verdict",
}

REQUIRED_RUNTIME_SURFACE = ("pydantic", "fastapi", "yaml", "numpy",
                            "scipy", "skopt")

DIST_NAMES = {
    "yaml": "pyyaml",
    "skopt": "scikit-optimize",
}

def _dist_name(top: str) -> str:
    return DIST_NAMES.get(top, top.replace("_", "-"))

def repo_local_tops() -> set[str]:
    tops: set[str] = set()
    for path in PKG.rglob("*.py"):
        if path.name != "__init__.py":
            tops.add(path.stem)
    for sub in PKG.iterdir():
        if sub.is_dir() and (sub / "__init__.py").exists():
            tops.add(sub.name)
    if SCRIPTS.is_dir():
        for path in SCRIPTS.glob("*.py"):
            if path.name != "__init__.py":
                tops.add(path.stem)
    if LLMSIM.is_dir():
        for sub in LLMSIM.iterdir():
            if sub.is_dir() and (sub / "__init__.py").exists():
                tops.add(sub.name)
    return tops

def _parse_list(text: str, key: str) -> list[str]:
    m = re.search(rf"{re.escape(key)}\s*=\s*\[(.*?)\]", text, re.S)
    if not m:
        return []
    out: list[str] = []
    for a, b in re.findall(r'"([^"]+)"|\'([^\']+)\'', m.group(1)):
        out.append(a or b)
    return out

def _req_name(req: str) -> str:
    req = req.strip().split(";")[0].strip()
    m = re.match(r"[A-Za-z0-9_.\-]+", req)
    return (m.group(0) if m else req).lower().replace("_", "-")

def declared() -> tuple[set[str], set[str]]:
    text = PYPROJECT.read_text()
    runtime = {_req_name(r) for r in _parse_list(text, "dependencies")}
    dev_block = text.split("[project.optional-dependencies]", 1)[1] \
        if "[project.optional-dependencies]" in text else ""
    dev = {_req_name(r) for r in _parse_list(dev_block, "dev")}
    return runtime, dev

def imports_of(path: Path) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):
        return []
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                found.append((node.lineno, (a.name or "").split(".")[0]))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.append((node.lineno, node.module.split(".")[0]))
    return found

def _is_import_error_guarded(path: Path, lineno: int) -> bool:
    """True when the import at `lineno` sits inside a try block with a
    handler (ImportError-specific, bare, or broad Exception). Broad
    handlers are only acceptable for modules listed in OPTIONAL_FALLBACK
    with a recorded justification — and the call sites must degrade to
    an explicit degraded verdict, never a silent success."""
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        start = node.lineno
        end = getattr(node, "end_lineno", None) or start
        if not (start <= lineno <= end):
            continue
        if node.handlers:
            return True
    return False

def main() -> int:
    runtime, dev = declared()
    local = repo_local_tops()
    problems: list[str] = []
    observed_runtime: set[str] = set()

    for path in sorted(PKG.rglob("*.py")):
        rel = path.relative_to(DSE).as_posix()
        is_test = (
            rel.startswith("veritx_dse/tests/")
            or path.name.startswith("test_")
            or path.name == "conftest.py"
        )
        allowed = runtime | dev if is_test else runtime
        for lineno, top in imports_of(path):
            if not top or top in sys.stdlib_module_names:
                continue
            if top == "veritx_dse" or top in local or top in GENERATED_STUBS:
                continue
            if top in OPTIONAL_FALLBACK and _is_import_error_guarded(path, lineno):
                continue
            dist = _dist_name(top)
            if dist not in allowed:
                problems.append(
                    f"{rel}:{lineno}: third-party import {top!r} "
                    f"(dist {dist!r}) is not a declared dependency"
                )
            elif not is_test:
                observed_runtime.add(top)

    for module in REQUIRED_RUNTIME_SURFACE:
        if module not in observed_runtime:
            problems.append(
                f"required runtime surface {module!r} is no longer "
                "imported — update REQUIRED_RUNTIME_SURFACE with "
                "justification"
            )
        elif _dist_name(module) not in runtime:
            problems.append(
                f"imported {module!r} is not in [project] dependencies"
            )

    if problems:
        print("PYTHON DEPENDENCY GUARD INVALID — "
              f"{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"python deps valid: {len(runtime)} runtime + {len(dev)} dev deps, "
          f"{len(local)} repo-local tops")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
