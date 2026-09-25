"""veritx_dse.core.run_bundle — durable, verifiable run bundles (C3).

A run bundle is a directory of scientific artifacts plus a
``checksums.json`` that content-addresses every one of them. It supports:

  * ``finalize_run_bundle`` — atomically publish a complete checksum
    manifest over the run directory (fsync file + directory);
  * ``verify_run_bundle`` — recompute and compare WITHOUT re-running any
    simulator, refusing a missing, tampered or extra file;
  * ``bundle_id`` — a path-independent content identity (relative paths
    only, never absolute scratch locations).

This is deliberately functions over a directory, not a manager hierarchy.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterator

from .errors import SemanticError

RUN_BUNDLE_SCHEMA_VERSION = 1
CHECKSUMS_NAME = "checksums.json"
MANIFEST_NAME = "manifest.json"
_ALGORITHM = "sha256"


class RunBundleError(ValueError, SemanticError):
    """The run bundle is missing, incomplete, tampered or unsupported."""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_bundle_files(run_dir: Path) -> Iterator[tuple[str, Path]]:
    root = Path(run_dir)
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != CHECKSUMS_NAME:
            yield path.relative_to(root).as_posix(), path


def bundle_id(files: dict[str, str]) -> str:
    """Path-independent content identity over ``{relative_path: sha256}``.

    Only relative paths and digests enter the hash, so two bundles with the
    same science have the same id regardless of where they live on disk.
    """
    canonical = json.dumps(
        {"algorithm": _ALGORITHM,
         "files": {k: files[k] for k in sorted(files)}},
        sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def finalize_run_bundle(run_dir: str | Path) -> dict[str, Any]:
    """Publish ``checksums.json`` over the run directory, atomically.

    The manifest is built in a temp file, fsynced, then renamed into place
    and the directory fsynced, so a crash mid-finalize cannot leave a
    partially valid bundle.
    """
    root = Path(run_dir)
    if not root.is_dir():
        raise RunBundleError(f"run directory does not exist: {root}")
    files = {rel: _sha256_file(path) for rel, path in _iter_bundle_files(root)}
    if not files:
        raise RunBundleError(f"run directory {root} holds no artifacts")
    doc = {
        "schema_version": RUN_BUNDLE_SCHEMA_VERSION,
        "algorithm": _ALGORITHM,
        "bundle_id": bundle_id(files),
        "file_count": len(files),
        "files": {k: files[k] for k in sorted(files)},
    }
    target = root / CHECKSUMS_NAME
    fd, tmp_name = tempfile.mkstemp(dir=str(root), prefix=".checksums-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, indent=2, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    _fsync_dir(root)
    return doc


def _load_checksums(run_dir: Path) -> dict[str, Any]:
    path = run_dir / CHECKSUMS_NAME
    if not path.is_file():
        raise RunBundleError(
            f"{run_dir} is not a finalized run bundle (no {CHECKSUMS_NAME})")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunBundleError(f"{path} is unreadable: {exc}") from exc
    if not isinstance(doc, dict):
        raise RunBundleError(f"{path} is not a JSON object")
    if doc.get("schema_version") != RUN_BUNDLE_SCHEMA_VERSION:
        raise RunBundleError(
            f"unsupported run bundle schema_version "
            f"{doc.get('schema_version')!r} (this build implements "
            f"{RUN_BUNDLE_SCHEMA_VERSION})")
    if doc.get("algorithm") != _ALGORITHM:
        raise RunBundleError(
            f"unsupported checksum algorithm {doc.get('algorithm')!r}")
    if not isinstance(doc.get("files"), dict) or not doc["files"]:
        raise RunBundleError(f"{path} declares no files")
    return doc


def verify_run_bundle(run_dir: str | Path) -> dict[str, Any]:
    """Verify a finalized bundle without re-running any simulator.

    Refuses a missing file, a tampered file, an extra file, a manifest that
    disagrees with its own ``bundle_id``, and a schema generation this
    build does not implement.
    """
    root = Path(run_dir)
    doc = _load_checksums(root)
    recorded: dict[str, str] = doc["files"]

    actual = {rel: _sha256_file(path)
              for rel, path in _iter_bundle_files(root)}
    missing = sorted(set(recorded) - set(actual))
    extra = sorted(set(actual) - set(recorded))
    if missing:
        raise RunBundleError(
            f"run bundle is incomplete: missing {missing[:5]}"
            + (" ..." if len(missing) > 5 else ""))
    if extra:
        raise RunBundleError(
            f"run bundle has undeclared files {extra[:5]}"
            + (" ..." if len(extra) > 5 else ""))
    tampered = sorted(rel for rel in recorded if recorded[rel] != actual[rel])
    if tampered:
        raise RunBundleError(
            f"run bundle is tampered: {tampered[:5]}"
            + (" ..." if len(tampered) > 5 else ""))

    computed_id = bundle_id(recorded)
    if doc.get("bundle_id") != computed_id:
        raise RunBundleError(
            "run bundle bundle_id does not match its file digests "
            "(manifest edited)")

    manifest = root / MANIFEST_NAME
    if manifest.is_file():
        try:
            mdoc = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RunBundleError(f"{manifest} is unreadable: {exc}") from exc
        if not isinstance(mdoc, dict) or "schema_version" not in mdoc:
            raise RunBundleError(f"{manifest} is not a versioned manifest")
    return {"file_count": doc["file_count"], "bundle_id": computed_id}
