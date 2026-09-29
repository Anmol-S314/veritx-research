"""veritx_dse.backend.reproduce — re-execute and compare a BookSim bundle.

Rationale: docs/decisions/modules/backend.md
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from veritx_dse.backend.booksim_execution import parse_booksim_stats
from veritx_dse.backend.booksim_projection import (
    CONFIG_FILE, ROUTE_DUMP_FILE, TOPOLOGY_FILE, TRACE_FILE,
)
from veritx_dse.backend.evidence import (
    BackendEvidenceError, EvidenceRef, ScientificBackendEvidence,
    admit_for_certified_product, canonical_hex64, read_verified_evidence,
    validate_evidence_document,
)
from veritx_dse.core.run_bundle import RunBundleError, verify_run_bundle

_EVIDENCE_NAME = "backend-evidence.json"
_INPUT_NAMES = (CONFIG_FILE, TRACE_FILE, TOPOLOGY_FILE)


def _admitted_evidence(run_dir: Path) -> ScientificBackendEvidence:
    """Digest-admit the bundle's evidence document.

Rationale: docs/decisions/modules/backend.md
    """
    path = run_dir / _EVIDENCE_NAME
    if not path.is_file():
        raise RunBundleError(
            f"{run_dir} holds no {_EVIDENCE_NAME}; not a BookSim run bundle")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RunBundleError(f"{path} is unreadable: {exc}") from exc
    ref = EvidenceRef(path=str(path),
                      sha256=hashlib.sha256(raw).hexdigest())
    try:
        data = read_verified_evidence(ref)
    except BackendEvidenceError as exc:
        raise RunBundleError(
            f"evidence bytes failed digest admission: {exc}") from exc
    scientific = data.get("evidence")
    if not isinstance(scientific, dict):
        raise RunBundleError(f"{path} is not a booksim evidence document")
    try:
        validated = validate_evidence_document(scientific)
        evidence = ScientificBackendEvidence.from_dict(validated)
        admit_for_certified_product(evidence)
    except BackendEvidenceError as exc:
        raise RunBundleError(
            "stored evidence is not reproducible certified evidence: "
            f"{exc}") from exc
    return evidence


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical_stats(value: Any) -> Any:
    """JSON-canonical form for stats comparison.

Rationale: docs/decisions/modules/backend.md
    """
    if isinstance(value, dict):
        return {str(key): _canonical_stats(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical_stats(item) for item in value]
    return value


def _pinned_binary(evidence: ScientificBackendEvidence,
                   binary: str | Path | None,
                   attempt_binary: Any) -> Path:
    """Resolve the reproduction binary pinned to the evidence identity.

Rationale: docs/decisions/modules/backend.md
    """
    from veritx_dse.core.build_manifest import (
        BuildManifestError, load_and_verify_manifest, manifest_path_for,
    )
    if binary is None:
        binary = attempt_binary
    if evidence.build_manifest_sha256 is None:
        raise RunBundleError(
            "evidence binds no build manifest; the reproduction "
            "producer cannot be proven")
    if not binary or not Path(binary).is_file():
        raise RunBundleError(
            f"reproduce needs the backend binary; none at {binary!r} "
            "(pass --binary)")
    candidate = Path(binary)
    digest = _sha256_file(candidate)
    if canonical_hex64(digest, "reproduction binary") != \
            canonical_hex64(evidence.binary_sha256, "binary_sha256"):
        raise RunBundleError(
            "reproduction binary does not match the evidence producer "
            f"({digest} != {evidence.binary_sha256}) — refusing to "
            "reproduce with another binary")
    manifest_path = manifest_path_for(candidate)
    try:
        manifest = load_and_verify_manifest(candidate)
    except BuildManifestError as exc:
        raise RunBundleError(
            f"reproduction binary manifest unverifiable: {exc}") from exc
    if manifest is None:
        raise RunBundleError(
            "reproduction binary carries no verifiable build manifest; "
            "its qualification cannot be proven")
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise RunBundleError(
            f"reproduction manifest unreadable: {exc}") from exc
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if canonical_hex64(manifest_sha, "reproduction manifest") != \
            canonical_hex64(evidence.build_manifest_sha256 or "",
                            "build_manifest_sha256"):
        raise RunBundleError(
            "reproduction binary manifest is not the manifest the "
            "evidence was qualified against — refusing a "
            "differently-built producer")
    if manifest.binary_size != evidence.binary_size:
        raise RunBundleError(
            "reproduction binary size does not match the evidence "
            "producer size — refusing a replaced binary")
    return candidate


def reproduce_booksim_run_bundle(
        run_dir: str | Path, *, binary: str | Path | None = None,
        timeout: int = 600) -> dict[str, Any]:
    """Verify, re-execute and compare; refuse any scientific divergence."""
    root = Path(run_dir)
    verify_summary = verify_run_bundle(root)
    evidence = _admitted_evidence(root)
    try:
        attempt_doc = json.loads((root / _EVIDENCE_NAME).read_text())
    except (OSError, ValueError) as exc:
        raise RunBundleError(
            f"evidence document unreadable for attempt lookup: {exc}"
        ) from exc
    bin_path = _pinned_binary(
        evidence, binary,
        (attempt_doc.get("attempt", {}) or {}).get("binary_path"))

    with tempfile.TemporaryDirectory(prefix="veritx-reproduce-") as tmp:
        work = Path(tmp)
        for name in _INPUT_NAMES:
            src = root / name
            if src.is_file():
                shutil.copy2(src, work / name)
        for name, bound in ((CONFIG_FILE, evidence.config_sha256),
                            (TRACE_FILE, evidence.trace_sha256),
                            (TOPOLOGY_FILE, evidence.topology_sha256)):
            staged = work / name
            if bound is None:
                if staged.is_file():
                    raise RunBundleError(
                        f"reproduction staged an unexpected {name} the "
                        f"evidence never named")
                continue
            if not staged.is_file():
                raise RunBundleError(
                    f"bundle lacks the {name} input the evidence names; "
                    f"cannot reproduce identical inputs")
            digest = _sha256_file(staged)
            if canonical_hex64(digest, name) != \
                    canonical_hex64(bound, name):
                raise RunBundleError(
                    f"reproduction input {name} does not match the "
                    f"evidence digest — refusing approximate inputs")
        cmd = [str(bin_path), CONFIG_FILE]
        proc = subprocess.run(
            cmd, cwd=str(work), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=timeout, shell=False)
        if proc.returncode != 0:
            raise RunBundleError(
                f"reproduction backend exited {proc.returncode}: "
                f"{(proc.stderr or '')[-300:]}")

        new_stats = parse_booksim_stats(proc.stdout, proc.stderr)
        if _canonical_stats(new_stats) != _canonical_stats(evidence.stats):
            raise RunBundleError(
                "reproduction diverges from the stored science: stats "
                f"{_canonical_stats(new_stats)} != "
                f"{_canonical_stats(evidence.stats)}")

        stored_dump = evidence.route_dump_sha256
        if stored_dump is not None:
            dump_path = work / ROUTE_DUMP_FILE
            if not dump_path.is_file():
                raise RunBundleError(
                    "reproduction produced no route dump while the stored "
                    "evidence claims one")
            new_dump = hashlib.sha256(dump_path.read_bytes()).hexdigest()
            if canonical_hex64(new_dump, "route dump") != \
                    canonical_hex64(stored_dump, "route_dump_sha256"):
                raise RunBundleError(
                    "reproduction route realization diverges from the "
                    f"stored dump ({new_dump} != {stored_dump})")
    return {"matched": True, "bundle_id": verify_summary["bundle_id"],
            "stats": new_stats, "route_dump_sha256": stored_dump}


__all__ = ["reproduce_booksim_run_bundle"]
