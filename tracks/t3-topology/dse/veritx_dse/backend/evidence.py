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
    """Inspection-only read (debugging, display). NOT reusable evidence.

    This performs no digest verification: never pass its output to any
    reuse operation. Reuse requires ``read_verified_evidence`` against a
    trusted ``EvidenceRef``.
    """
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


PARSER_VERSION = "veritx/evidence-parser/v1"
LEGACY_PARSER_VERSION = "veritx/evidence-parser/v0-unversioned"
_EVIDENCE_ARTIFACT_DOMAIN = "veritx/evidence-artifact/v1"
_HEX = frozenset("0123456789abcdef")


def stats_sha256_of(stats: dict[str, Any]) -> str:
    """Canonical digest of the parsed stats mapping."""
    if not isinstance(stats, dict) or not stats:
        raise BackendEvidenceError(
            "evidence without parsed stats is not a measurement")
    return hashlib.sha256(
        canonical_evidence_json(stats).encode()).hexdigest()


def _require_hex64(value: Any, where: str) -> None:
    if not isinstance(value, str) or len(value) != 64 \
            or any(c not in _HEX for c in value):
        raise BackendEvidenceError(
            f"{where} must be a 64-char lowercase hex digest, got "
            f"{value!r}")


@dataclass(frozen=True)
class EvidenceArtifact:
    """One executed backend run, content-addressed (M1.4).

    Where ``EvidenceRef`` is the external identity of the persisted bytes,
    this is the internal identity of what those bytes MEAN: the backend
    input they were executed from, the raw bytes themselves, the parser
    version that read them and the stats digest they carry. A result that
    cannot name its evidence_id has evidence it cannot authenticate.
    """

    backend: str
    backend_input_id: str
    backend_input_sha256: str
    raw_evidence_sha256: str
    parser_version: str
    stats_sha256: str

    def __post_init__(self):
        for name in ("backend", "backend_input_id", "parser_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise BackendEvidenceError(
                    f"{name} must be a non-empty string")
        for name in ("backend_input_sha256", "raw_evidence_sha256",
                      "stats_sha256"):
            _require_hex64(getattr(self, name), name)

    @classmethod
    def build(cls, *, backend, backend_input_id, backend_input_sha256,
              raw_evidence_sha256, stats,
              parser_version=PARSER_VERSION) -> "EvidenceArtifact":
        return cls(
            backend=backend, backend_input_id=backend_input_id,
            backend_input_sha256=backend_input_sha256,
            raw_evidence_sha256=raw_evidence_sha256,
            parser_version=parser_version,
            stats_sha256=stats_sha256_of(stats))

    def identity_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "backend_input_id": self.backend_input_id,
            "backend_input_sha256": self.backend_input_sha256,
            "raw_evidence_sha256": self.raw_evidence_sha256,
            "parser_version": self.parser_version,
            "stats_sha256": self.stats_sha256,
        }

    def evidence_id(self) -> str:
        from veritx_dse.core.artifact import content_hash
        return content_hash(_EVIDENCE_ARTIFACT_DOMAIN, 1,
                            self.identity_dict())

    def authenticates(self, *, backend_input_sha256, raw_evidence_sha256,
                      stats) -> bool:
        """True only if these exact inputs name this exact artifact."""
        return (self.backend_input_sha256 == backend_input_sha256
                and self.raw_evidence_sha256 == raw_evidence_sha256
                and self.stats_sha256 == stats_sha256_of(stats))

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, **self.identity_dict(),
                "evidence_id": self.evidence_id()}

    @classmethod
    def from_dict(cls, doc: Any) -> "EvidenceArtifact":
        if not isinstance(doc, dict):
            raise BackendEvidenceError(
                "persisted evidence artifact must be an object")
        expected = {"schema_version", "backend", "backend_input_id",
                    "backend_input_sha256", "raw_evidence_sha256",
                    "parser_version", "stats_sha256", "evidence_id"}
        if set(doc) != expected:
            raise BackendEvidenceError(
                f"evidence artifact field mismatch; "
                f"missing={sorted(expected - set(doc))}, "
                f"extra={sorted(set(doc) - expected)}")
        if doc["schema_version"] != 1:
            raise BackendEvidenceError(
                "unsupported evidence artifact schema")
        obj = cls(backend=doc["backend"],
                  backend_input_id=doc["backend_input_id"],
                  backend_input_sha256=doc["backend_input_sha256"],
                  raw_evidence_sha256=doc["raw_evidence_sha256"],
                  parser_version=doc["parser_version"],
                  stats_sha256=doc["stats_sha256"])
        if doc["evidence_id"] != obj.evidence_id():
            raise BackendEvidenceError(
                "persisted evidence_id does not match the recomputed "
                "identity: content forged")
        return obj

    @classmethod
    def from_verified_evidence(cls, evidence: dict[str, Any], ref
                               ) -> "EvidenceArtifact":
        """Derive the artifact from verified evidence + its EvidenceRef.

        The document must already have passed ``read_verified_evidence``:
        only then can the ref digest be trusted as the raw-bytes identity.
        ``parser_version`` is stamped from the document when the producer
        wrote one; historical documents predate versioning and get the
        legacy tag, so a different reader is a different claim.
        """
        if not isinstance(evidence, dict):
            raise BackendEvidenceError(
                "verified evidence must be a mapping")
        if not isinstance(ref, EvidenceRef):
            raise BackendEvidenceError(
                "an EvidenceArtifact requires an EvidenceRef; a naked "
                "path carries no raw-bytes identity")
        for key in ("backend_input_hash", "stats"):
            if key not in evidence:
                raise BackendEvidenceError(
                    f"verified evidence is missing {key!r}")
        backend = (evidence.get("producer_tool_identity")
                   or evidence.get("execution_transport") or "UNKNOWN")
        return cls.build(
            backend=backend,
            backend_input_id=evidence["backend_input_hash"],
            backend_input_sha256=evidence["backend_input_hash"],
            raw_evidence_sha256=ref.sha256,
            stats=evidence["stats"],
            parser_version=evidence.get("parser_version",
                                        LEGACY_PARSER_VERSION))


__all__ = [
    "EVIDENCE_FILE",
    "BackendEvidenceError",
    "EvidenceArtifact",
    "EvidenceRef",
    "LEGACY_PARSER_VERSION",
    "PARSER_VERSION",
    "canonical_evidence_json",
    "evidence_sha256",
    "evidence_sha256_of",
    "read_evidence",
    "read_verified_evidence",
    "stats_sha256_of",
    "write_evidence",
]
