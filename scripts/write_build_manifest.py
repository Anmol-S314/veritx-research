#!/usr/bin/env python3
"""Write a build-time provenance manifest for a built backend binary.

Usage:
    python3 scripts/write_build_manifest.py BINARY \
        --recipe-version booksim2-fork/v1 \
        --compiler g++ --compiler-version "$(g++ -dumpversion)" \
        --build-config Release --flag -O3 --flag -g

Run immediately after building, from the worktree that produced the
binary, so the recorded source revision/dirty state is the build state.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tracks" / "t3-topology" / "dse"))

from veritx_dse.core.build_manifest import write_build_manifest  # noqa: E402


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
    ap.add_argument("binary")
    ap.add_argument("--recipe-version", required=True)
    ap.add_argument("--compiler", default="g++")
    ap.add_argument("--compiler-version", default=None)
    ap.add_argument("--build-config", default="Release")
    ap.add_argument("--flag", action="append", default=[])
    ap.add_argument("--repo-root", default=str(REPO_ROOT))
    args = ap.parse_args()
    compiler_version = args.compiler_version
    if compiler_version is None:
        compiler_version = _compiler_version(args.compiler)
    path = write_build_manifest(
        Path(args.binary), repo_root=Path(args.repo_root),
        recipe_version=args.recipe_version, compiler=args.compiler,
        compiler_version=compiler_version, build_config=args.build_config,
        compile_flags=tuple(args.flag))
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
