#!/usr/bin/env python3
"""Write the release manifest that binds a release candidate to its facts.

Binds: release SHA + dirty state, container image identity, backend build
manifests, schema versions, tool versions, and validation report digests.
A released artifact without this manifest is not a release.

Usage:
    python3 scripts/write_release_manifest.py \
        --container-digest "$VERITX_TOOLS_IMAGE" \
        --backend-manifest third_party/booksim2/src/booksim.build-manifest.json \
        --validation-report validation/reports/REPORT.md \
        --out release-manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tracks" / "t3-topology" / "dse"))

RELEASE_MANIFEST_SCHEMA_VERSION = 1


def _sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=REPO_ROOT,
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return None


def _tool_version(cmd: list[str]) -> str | None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return (proc.stdout or proc.stderr).splitlines()[0].strip() or None


def _schema_versions() -> dict[str, object]:
    out: dict[str, object] = {}
    try:
        from veritx_dse.backend.booksim_projection import (
            BOOKSIM_PROJECTION_SCHEMA_VERSION, TRACE_SCHEDULE_VERSION,
        )
        from veritx_dse.backend.evidence import (
            EVIDENCE_SCHEMA_VERSION, PARSER_VERSION,
        )
        from veritx_dse.core.run_bundle import RUN_BUNDLE_SCHEMA_VERSION
        from veritx_dse.model.compile_model import (
            COMPILE_REQUEST_SCHEMA_VERSION, COMPILER_SEMANTICS_VERSION,
        )
        out = {
            "compile_request": COMPILE_REQUEST_SCHEMA_VERSION,
            "compiler_semantics": COMPILER_SEMANTICS_VERSION,
            "prepared_booksim": BOOKSIM_PROJECTION_SCHEMA_VERSION,
            "trace_schedule": TRACE_SCHEDULE_VERSION,
            "backend_evidence": EVIDENCE_SCHEMA_VERSION,
            "booksim_parser": PARSER_VERSION,
            "run_bundle": RUN_BUNDLE_SCHEMA_VERSION,
        }
    except Exception as exc:  # noqa: BLE001
        out = {"error": f"{type(exc).__name__}: {exc}"}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(REPO_ROOT / "release-manifest.json"))
    ap.add_argument("--container-digest", default=None)
    ap.add_argument("--backend-manifest", action="append", default=[])
    ap.add_argument("--validation-report", action="append", default=[])
    args = ap.parse_args()

    backends = []
    for rel in args.backend_manifest:
        path = (REPO_ROOT / rel) if not Path(rel).is_absolute() else Path(rel)
        doc = None
        if path.is_file():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                doc = None
        backends.append({"path": rel, "sha256": _sha256(path), "manifest": doc})

    reports = []
    for rel in args.validation_report:
        path = (REPO_ROOT / rel) if not Path(rel).is_absolute() else Path(rel)
        reports.append({"path": rel, "sha256": _sha256(path)})

    manifest = {
        "schema_version": RELEASE_MANIFEST_SCHEMA_VERSION,
        "release_sha": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(_git("status", "--porcelain")),
        "container": {"image": args.container_digest,
                      "pinned_by_digest": bool(
                          args.container_digest
                          and "@sha256:" in args.container_digest)},
        "tools": {
            "python": sys.version.split()[0],
            "gpp": _tool_version(["g++", "--version"]),
            "verilator": _tool_version(["verilator", "--version"]),
        },
        "schema_versions": _schema_versions(),
        "backends": backends,
        "validation_reports": reports,
    }
    out = Path(args.out)
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
