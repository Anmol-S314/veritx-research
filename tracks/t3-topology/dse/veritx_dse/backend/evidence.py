"""veritx_dse.backend.evidence — certified backend-evidence persistence (B3.7e).

B3.7a/b already bind the scientific identity (BackendConfigArtifact,
BackendInputManifest) and B3.7b's runner returns the executed facts. This
module is the thin persistence seam: one canonical JSON file per run,
content-addressed, refusing to overwrite different evidence.

The evidence file intentionally contains NO new identity. It is a
derived view of already-verified facts:

    backend_config_hash   path-independent fabric projection
    backend_input_hash    workload + seed + rendered inputs + invocation
    resolved_fabric_hash  design+mapping+fabric binding
    fabric_hash           hardware identity
    route_equivalence     executed-route proof status
    rendered_inputs       logical role -> content sha256 (the actual bytes)
    invocation_args       command-line-only semantics
    booksim_binary_sha256 producer identity (B-FINAL binds it pre-spawn;
                          B3.7-era "observation" wording is obsolete)
    producer_*            source revision, dirt, tool identity

The file ``backend-evidence.json`` is a fixed run-owned filename; it is
content-*identified* (not content-addressed) by the external
``EvidenceRef.sha256`` returned at write time. Reuse must go through
``read_verified_evidence``/``verify_reusable_evidence`` (producer.py),
which refuse when the persisted bytes no longer match the reference
digest. A naked path without a trusted digest is inspection only.

Overwriting an evidence file with DIFFERENT content is refused: two
different scientific claims must not share a path.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EVIDENCE_FILE = "backend-evidence.json"


class BackendEvidenceError(ValueError):
    """Existing evidence disagrees with the new evidence — fail closed."""


def canonical_evidence_json(evidence: dict[str, Any]) -> str:
    from veritx_dse.core.spec import canonical_json
    try:
        return canonical_json(evidence)
    except (TypeError, ValueError) as exc:
        raise BackendEvidenceError(
            f"evidence is not canonical-JSON serializable: {exc}") from exc


def evidence_sha256_of(evidence: dict[str, Any]) -> str:
    return hashlib.sha256(
        canonical_evidence_json(evidence).encode()).hexdigest()


def evidence_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_evidence(path: Path) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text())
    if not isinstance(raw, dict):
        raise BackendEvidenceError(
            f"evidence file {path} must contain a JSON object")
    return raw


@dataclass(frozen=True)
class EvidenceRef:
    """External content identity for one persisted evidence file.

    The digest is external to the bytes it authenticates: it is returned
    by ``write_evidence`` and must be supplied back to
    ``read_verified_evidence`` on every reuse. Wave C stores this as part
    of its run/result resource; Wave B callers must never reuse a naked
    path without it.
    """

    path: str
    sha256: str

    def __post_init__(self):
        if not isinstance(self.path, str) or not self.path:
            raise BackendEvidenceError(
                f"evidence path must be a non-empty string, got "
                f"{self.path!r}")
        if not isinstance(self.sha256, str) or len(self.sha256) != 64 \
                or any(c not in "0123456789abcdef"
                       for c in self.sha256):
            raise BackendEvidenceError(
                f"evidence sha256 must be a 64-char hex digest, got "
                f"{self.sha256!r}")


def _reject_constant(value: str) -> Any:
    raise BackendEvidenceError(
        f"evidence JSON must not contain {value}")


def write_evidence(directory: Path, evidence: dict[str, Any]) -> EvidenceRef:
    """Write canonical evidence; return its external content identity.

    Idempotent for identical content; refuses to overwrite different
    content at the same path.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / EVIDENCE_FILE
    payload = canonical_evidence_json(evidence)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    if path.exists():
        existing = path.read_text()
        if hashlib.sha256(existing.encode()).hexdigest() != digest:
            raise BackendEvidenceError(
                f"{path} already holds different evidence; refusing to "
                "overwrite a scientific claim")
        return EvidenceRef(path=str(path), sha256=digest)
    from veritx_dse.core.recovery import atomic_write
    with atomic_write(path) as tmp:
        tmp.write_text(payload)
    return EvidenceRef(path=str(path), sha256=digest)


def read_verified_evidence(ref: EvidenceRef) -> dict[str, Any]:
    """Read evidence only if its bytes match the external identity.

    Reads the exact bytes, requires ``sha256(bytes) == ref.sha256``,
    then parses (refusing non-finite JSON constants and non-object
    documents). Any substitution of the persisted result fields refuses
    here, before binding checks. A naked path without a trusted digest
    is inspection only — use ``read_evidence`` and do not reuse it.
    """
    if not isinstance(ref, EvidenceRef):
        raise BackendEvidenceError(
            f"verified evidence read requires an EvidenceRef, got "
            f"{type(ref).__name__}; a naked path carries no content "
            f"identity and cannot be reused")
    try:
        raw = Path(ref.path).read_bytes()
    except OSError as exc:
        raise BackendEvidenceError(
            f"evidence file {ref.path} unreadable: {exc}") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if digest != ref.sha256:
        raise BackendEvidenceError(
            f"evidence file {ref.path} digest {digest} does not match "
            f"the reference {ref.sha256}; the persisted result was "
            f"modified after execution — refusing reuse")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BackendEvidenceError(
            f"evidence file {ref.path} is not UTF-8: {exc}") from exc
    try:
        data = json.loads(text, parse_constant=_reject_constant)
    except (ValueError, BackendEvidenceError) as exc:
        raise BackendEvidenceError(
            f"evidence file {ref.path} is not valid evidence JSON: "
            f"{exc}") from exc
    if not isinstance(data, dict):
        raise BackendEvidenceError(
            f"evidence file {ref.path} must contain a JSON object")
    return data


__all__ = [
    "EVIDENCE_FILE",
    "BackendEvidenceError",
    "EvidenceRef",
    "canonical_evidence_json",
    "evidence_sha256",
    "evidence_sha256_of",
    "read_evidence",
    "read_verified_evidence",
    "write_evidence",
]
