#!/usr/bin/env python3
"""Fail-closed guard: the release container must contain the declared
release toolchain (Gate 2 companion).

`release.yml` runs `make release-build` (BookSim + ASTRA-sim + Ramulator)
and the pytest battery *inside* `${VERITX_TOOLS_IMAGE}`, which is built
from the Dockerfile runtime stage. That stage must therefore declare:

  apt: cmake, protobuf-compiler (protoc), g++, make, python3, python3-pip
  pip: pydantic, fastapi, uvicorn, pytest
       (pyyaml arrives via the builder dist-packages copy; the DSE
       dependency declaration in pyproject.toml is the authority there)

Only the runtime stage (after the last FROM) is checked — builder tools
do not ship. Package tokens are matched case-insensitively with version
specifiers/extras stripped.

Exit 0 when clean, 1 with a missing-tool list otherwise.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = REPO_ROOT / "Dockerfile"

REQUIRED_APT = ("cmake", "protobuf-compiler", "g++", "make",
                "python3", "python3-pip")
REQUIRED_PIP = ("pydantic", "fastapi", "uvicorn", "pytest")

def _norm(token: str) -> str:
    token = token.strip().strip("\\").strip()
    token = re.split(r"[<>=!;\[]", token, maxsplit=1)[0].strip()
    return token.lower().strip("\"'")

def main() -> int:
    text = DOCKERFILE.read_text()
    stages = re.split(r"(?m)^FROM\s", text)
    runtime = stages[-1]
    runtime = re.sub(r"(?m)^\s*#.*$", "", runtime)

    apt: set[str] = set()
    for m in re.finditer(
            r"apt-get\s+install\s+(?:-y\s+)?(?:--no-install-recommends\s+)?(.*?)"
            r"(?:&&|$)", runtime, re.S):
        for token in m.group(1).split():
            token = token.strip()
            if not token or token.startswith("-"):
                continue
            apt.add(_norm(token))

    pip: set[str] = set()
    for m in re.finditer(r"pip3?\s+install\s+(.*?)(?:&&|$)", runtime, re.S):
        for token in m.group(1).split():
            token = token.strip()
            if not token or token.startswith("-"):
                continue
            pip.add(_norm(token))

    missing = [f"apt:{p}" for p in REQUIRED_APT if p not in apt]
    missing += [f"pip:{p}" for p in REQUIRED_PIP if p not in pip]
    if missing:
        print("RELEASE TOOLCHAIN INVALID — missing from Dockerfile "
              "runtime stage:")
        for m in missing:
            print(f"  - {m}")
        return 1
    print("release toolchain valid: "
          f"apt {sorted(REQUIRED_APT)} + pip {sorted(REQUIRED_PIP)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
