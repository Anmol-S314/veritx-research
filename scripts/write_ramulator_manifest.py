#!/usr/bin/env python3
"""Write a build-time provenance manifest for the built Ramulator extension.

Discovers the extension with THIS interpreter (the same one the release
build used — the bindings are interpreter-tagged, so no hardcoded
CPython suffix ever appears here) and writes a build manifest beside it.
A released Ramulator backend without this manifest is never pinned for
reusable evidence.

Usage:
    python3 scripts/write_ramulator_manifest.py \
        --recipe-version ramulator2/v1 --compiler g++ \
        --build-config Release

Exit status is non-zero when no built extension exists: a missing
release backend is a FAILURE, never a silent skip.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tracks" / "t3-topology" / "dse"))

from veritx_dse.core.build_manifest import write_build_manifest  # noqa: E402
from veritx_dse.simulation.ramulator import discover  # noqa: E402


def _compiler_version(compiler: str) -> str:
    if not compiler:
        return ""
    try:
        proc = subprocess.run([compiler, "--version"], capture_output=True,
                              text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (proc.stdout.splitlines() or [""])[0].strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recipe-version", required=True)
    ap.add_argument("--compiler", default="g++")
    ap.add_argument("--compiler-version", default=None)
    ap.add_argument("--build-config", default="Release")
    ap.add_argument("--flag", action="append", default=[])
    ap.add_argument(
        "--source-path", action="append", default=[], dest="source_paths",
        help="repo-relative producer source subtree the dirty check covers "
             "(repeatable; omit for whole-repo legacy semantics)")
    args = ap.parse_args()
    try:
        backend = discover()
    except Exception as exc:  # noqa: BLE001
        print(f"ramulator manifest: discovery failed: {exc}")
        return 1
    if not backend.ready:
        print(f"ramulator manifest: no built extension at {backend.ext_path} "
              f"for interpreter {sys.executable}; build with "
              f"./build.sh in third_party/ramulator2 first")
        return 1
    compiler_version = args.compiler_version
    if compiler_version is None:
        compiler_version = _compiler_version(args.compiler)
    path = write_build_manifest(
        backend.ext_path, repo_root=REPO_ROOT,
        recipe_version=args.recipe_version, compiler=args.compiler,
        compiler_version=compiler_version, build_config=args.build_config,
        compile_flags=tuple(args.flag),
        source_paths=tuple(args.source_paths))
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
