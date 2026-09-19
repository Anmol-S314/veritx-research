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
    booksim_binary_sha256 producer observation (B4 composes identity)

Overwriting an evidence file with DIFFERENT content is refused: two
different scientific claims must not share a path.
"""
from __future__ import annotations

import hashlib
import json
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


def write_evidence(directory: Path, evidence: dict[str, Any]) -> dict[str, str]:
    """Write canonical evidence; return {'path', 'sha256'}.

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
        return {"path": str(path), "sha256": digest}
    from veritx_dse.core.recovery import atomic_write
    with atomic_write(path) as tmp:
        tmp.write_text(payload)
    return {"path": str(path), "sha256": digest}


__all__ = [
    "EVIDENCE_FILE",
    "BackendEvidenceError",
    "canonical_evidence_json",
    "evidence_sha256",
    "evidence_sha256_of",
    "read_evidence",
    "write_evidence",
]
