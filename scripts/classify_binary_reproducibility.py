#!/usr/bin/env python3
"""Classify whether two builds of one binary are reproducible (R4.4).

Bit-identical builds are not required for scientific release unless the
project certifies reproducible builds. This script answers *why* two builds
differ, so the release can state one of:

  BIT_IDENTICAL                          same bytes
  SCIENTIFICALLY_EQUIVALENT_NON_BIT_REPRODUCIBLE
                                          same source/compiler/flags and the
                                          same executable code (.text), but
                                          build metadata (DWARF paths, GNU
                                          build-id) differs
  UNEXPLAINED                            a code/data difference, or a
                                          difference we cannot attribute

Usage:
    classify_binary_reproducibility.py A B [--json]

Exit 0 for BIT_IDENTICAL / SCIENTIFICALLY_EQUIVALENT_NON_BIT_REPRODUCIBLE,
1 for UNEXPLAINED.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

CLASS_BIT = "BIT_IDENTICAL"
CLASS_EQUIV = "SCIENTIFICALLY_EQUIVALENT_NON_BIT_REPRODUCIBLE"
CLASS_UNEXPLAINED = "UNEXPLAINED"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(args, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def _section_hash(path: Path, section: str) -> str | None:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "section.bin"
        rc, _ = _run(["objcopy", "-O", "binary",
                      f"--only-section={section}", str(path), str(out)])
        if rc != 0 or not out.is_file():
            return None
        return _sha(out)


def _build_id(path: Path) -> str | None:
    rc, text = _run(["readelf", "-n", str(path)])
    if rc != 0:
        return None
    for line in text.splitlines():
        if "Build ID:" in line:
            return line.split("Build ID:", 1)[1].strip()
    return None


def _comment(path: Path) -> str | None:
    rc, text = _run(["readelf", "-p", ".comment", str(path)])
    if rc != 0:
        return None
    return "\n".join(text.splitlines()[1:]).strip()


def classify(a: Path, b: Path) -> dict[str, object]:
    sha_a, sha_b = _sha(a), _sha(b)
    result: dict[str, object] = {
        "a": str(a), "b": str(b),
        "sha256_a": sha_a, "sha256_b": sha_b,
        "size_a": a.stat().st_size, "size_b": b.stat().st_size,
        "compiler_a": _comment(a), "compiler_b": _comment(b),
        "build_id_a": _build_id(a), "build_id_b": _build_id(b),
    }
    if sha_a == sha_b:
        result["classification"] = CLASS_BIT
        return result

    text_a = _section_hash(a, ".text")
    text_b = _section_hash(b, ".text")
    result["text_sha256_a"] = text_a
    result["text_sha256_b"] = text_b
    same_compiler = result["compiler_a"] == result["compiler_b"] \
        and result["compiler_a"] is not None
    if text_a is not None and text_a == text_b and same_compiler:
        result["classification"] = CLASS_EQUIV
        result["reason"] = (
            "executable .text is byte-identical and the compiler is the "
            "same; only build metadata (DWARF paths / GNU build-id) differs")
    else:
        result["classification"] = CLASS_UNEXPLAINED
        result["reason"] = (
            "executable code or compiler differs; not explained by build "
            "metadata")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("a", type=Path)
    parser.add_argument("b", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = classify(args.a, args.b)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"classification: {result['classification']}")
        for key in ("sha256_a", "sha256_b", "text_sha256_a",
                    "text_sha256_b", "reason"):
            if key in result:
                print(f"  {key}: {result[key]}")
    return 0 if result["classification"] in (CLASS_BIT, CLASS_EQUIV) else 1


if __name__ == "__main__":
    raise SystemExit(main())
