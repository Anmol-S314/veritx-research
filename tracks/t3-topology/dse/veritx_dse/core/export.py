"""export.py — reproducible artifact/export bundle (plan §22, Phase 18+).

One bounded operation: bundle an immutable run directory into a single
checksummed archive suitable for hand-off. Content identity is the
SHA-256 of the deterministic export manifest (sorted path→sha256 map) —
identical run content produces an identical manifest checksum. The
tar.gz embeds gzip mtime and is honestly reported as a transport
artifact, not as reproducible content.

Signing honesty (§22): the seam is checksummed, not cryptographically
signed. The bundle self-describes as CHECKSUMMED_UNSIGNED; the optional
HMAC path (VERITX_EXPORT_HMAC_KEY) produces HMAC_SIGNED. Nothing here
implies PKI-grade identity or authenticity.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import os
import tarfile
from pathlib import Path
from typing import Any

# Never baked into a bundle: runtime debris, environment-absolute noise.
EXCLUDE_NAMES = {"log.log", "err.log", "*.pyc"}
EXCLUDE_DIRS = {"__pycache__", ".git"}

BUNDLE_SCHEMA_VERSION = 1


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _included_files(run_dir: Path) -> list[Path]:
    files: list[Path] = []
    for p in sorted(run_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(run_dir)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if any(rel.match(pat) for pat in EXCLUDE_NAMES):
            continue
        files.append(p)
    return files


def export_run(run_dir: str | Path, out_dir: str | Path, *,
               run_id: str | None = None) -> dict[str, Any]:
    """Bundle one immutable run into <out_dir>/<run_id>.tar.gz + checksums.

    Returns structured output: bundle path, per-file checksums, bundle
    checksum, signing class. Raises (fail closed) if the run dir is not
    a recognizable immutable run.
    """
    src = Path(run_dir)
    manifest_path = src / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(
            f"not a recognized immutable run (missing manifest.json): {src}")

    rid = run_id or src.name
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    files = _included_files(src)

    # Per-file checksums, path-keyed, sorted (content-identity foundation).
    checksums = {str(p.relative_to(src)): _sha256_file(p) for p in files}

    doc = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "run_id": rid,
        "signing": "CHECKSUMMED_UNSIGNED",
        "file_count": len(files),
        "files": checksums,
    }

    # HMAC path — explicitly labeled, never implied to be PKI.
    key = os.environ.get("VERITX_EXPORT_HMAC_KEY")
    if key:
        mac = hmac_mod.new(key.encode(), digestmod=hashlib.sha256)
        for rel in sorted(checksums):
            mac.update(f"{rel}:{checksums[rel]}\n".encode())
        doc["signing"] = "HMAC_SIGNED"
        doc["hmac_sha256"] = mac.hexdigest()

    manifest_name = "export.manifest.json"
    manifest_bytes = json.dumps(doc, indent=2, sort_keys=True).encode() + b"\n"
    (out / manifest_name).write_bytes(manifest_bytes)

    # Content identity = checksum of the deterministic manifest (per-file
    # checksums). The tar.gz itself embeds gzip mtime, so its bytes are NOT
    # reproducible — it is the transport artifact, checksummed separately.
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    (out / "export.manifest.sha256").write_text(manifest_sha256 + "\n")

    tar_path = out / f"{rid}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        for p in files:
            tf.add(p, arcname=str(p.relative_to(src)))
        tf.add(out / manifest_name, arcname=manifest_name)

    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "status": "OK",
        "run_id": rid,
        "bundle": str(tar_path),
        "manifest_sha256": manifest_sha256,
        "archive_sha256": _sha256_file(tar_path),
        "signing": doc["signing"],
        "file_count": len(files),
        "manifest": str(out / manifest_name),
    }


__all__ = ["export_run", "BUNDLE_SCHEMA_VERSION"]
