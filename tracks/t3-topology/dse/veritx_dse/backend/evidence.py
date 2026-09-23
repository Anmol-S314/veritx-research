"""veritx_dse.backend.evidence — content-authenticated evidence discipline.

Reclaimed from the historical ``backend/evidence.py`` (p1-product /
p1b / p1x lineage), re-parented onto the current canonical artifacts and
the Slice-31 ``PreparedBookSimInput``.

Two identities, deliberately distinct:

  * ``EvidenceRef``           external identity of the PERSISTED BYTES
                              (path + sha256). A naked path is never
                              reusable.
  * ``ScientificBackendEvidence``  internal identity of what the bytes
                              MEAN: the prepared input, the exact
                              producer, the parser version and the parsed
                              measurements. Execution-attempt metadata
                              (wall time, paths, host) is NOT part of it.

Reuse requires the bytes digest, the prepared input digests, the producer
binary digest and the parser/schema version all to agree.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veritx_dse.core.artifact import canonical_bytes, content_hash

EVIDENCE_FILE = "backend-evidence.json"

EVIDENCE_SCHEMA_VERSION = 1
PARSER_VERSION = "veritx/booksim-stats-parser/v1"
_EVIDENCE_DOMAIN = "srota/ScientificBackendEvidence"

#: execution transports (only the supervised process is reusable)
EXECUTION_TRANSPORT_SUPERVISED_PROCESS = "SUPERVISED_PROCESS"
EXECUTION_TRANSPORT_TEST_INJECTED = "TEST_INJECTED"

_HEX = frozenset("0123456789abcdef")


class BackendEvidenceError(ValueError):
    """Evidence disagrees with its reference — fail closed."""


def canonical_evidence_json(evidence: dict[str, Any]) -> str:
    try:
        return canonical_bytes(evidence).decode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BackendEvidenceError(
            f"evidence is not canonical-JSON serializable: {exc}") from exc


def evidence_sha256_of(evidence: dict[str, Any]) -> str:
    return hashlib.sha256(
        canonical_evidence_json(evidence).encode()).hexdigest()


def require_hex64(value: Any, where: str) -> str:
    """Accept the canonical ``sha256:<hex>`` form or a bare hex digest.

    Slice-31 prepared-input identities use ``content_hash`` (prefixed);
    evidence digests are bare. Both are the same digest.
    """
    bare = value[7:] if isinstance(value, str) \
        and value.startswith("sha256:") else value
    if not isinstance(bare, str) or len(bare) != 64 \
            or any(c not in _HEX for c in bare):
        raise BackendEvidenceError(
            f"{where} must be a 64-char lowercase hex digest, got {value!r}")
    return value


def require_finite(value: Any, where: str) -> float:
    """No NaN/Inf may enter reusable scientific evidence."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BackendEvidenceError(
            f"{where} must be a real number, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise BackendEvidenceError(
            f"{where} must be finite, got {number!r}")
    return number


@dataclass(frozen=True)
class EvidenceRef:
    """External content identity for one persisted evidence file."""

    path: str
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path:
            raise BackendEvidenceError(
                f"evidence path must be a non-empty string, got {self.path!r}")
        require_hex64(self.sha256, "evidence sha256")


def _reject_constant(value: str) -> Any:
    raise BackendEvidenceError(f"evidence JSON must not contain {value}")


def read_evidence(path: Path) -> dict[str, Any]:
    """Inspection only. Never reusable: no digest verification."""
    raw = json.loads(Path(path).read_text(),
                     parse_constant=_reject_constant)
    if not isinstance(raw, dict):
        raise BackendEvidenceError(
            f"evidence file {path} must contain a JSON object")
    return raw


def write_evidence(directory: Path, evidence: dict[str, Any]) -> EvidenceRef:
    """Write canonical evidence; return its external content identity."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / EVIDENCE_FILE
    payload = canonical_evidence_json(evidence)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    if path.exists():
        existing = path.read_bytes()
        if hashlib.sha256(existing).hexdigest() != digest:
            raise BackendEvidenceError(
                f"{path} already holds different evidence; refusing to "
                "overwrite a scientific claim")
        return EvidenceRef(path=str(path), sha256=digest)
    from veritx_dse.core.recovery import atomic_write
    with atomic_write(path) as tmp:
        tmp.write_text(payload, encoding="utf-8")
    return EvidenceRef(path=str(path), sha256=digest)


def read_verified_evidence(ref: EvidenceRef) -> dict[str, Any]:
    """Read evidence only if its bytes match the external identity."""
    if not isinstance(ref, EvidenceRef):
        raise BackendEvidenceError(
            "verified evidence read requires an EvidenceRef, got "
            f"{type(ref).__name__}; a naked path carries no content "
            "identity and cannot be reused")
    try:
        raw = Path(ref.path).read_bytes()
    except OSError as exc:
        raise BackendEvidenceError(
            f"evidence file {ref.path} unreadable: {exc}") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if digest != ref.sha256:
        raise BackendEvidenceError(
            f"evidence file {ref.path} digest {digest} does not match the "
            f"reference {ref.sha256}; the persisted result was modified "
            "after execution — refusing reuse")
    try:
        data = json.loads(raw.decode("utf-8"),
                          parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, BackendEvidenceError) as exc:
        raise BackendEvidenceError(
            f"evidence file {ref.path} is not valid evidence JSON: "
            f"{exc}") from exc
    if not isinstance(data, dict):
        raise BackendEvidenceError(
            f"evidence file {ref.path} must contain a JSON object")
    return data


@dataclass(frozen=True)
class ExecutionAttempt:
    """Run-varying facts. NOT part of scientific identity."""

    wall_time_s: float
    run_dir: str
    binary_path: str
    command: tuple[str, ...]
    host: str
    platform: str
    transport: str = EXECUTION_TRANSPORT_SUPERVISED_PROCESS

    def to_dict(self) -> dict[str, Any]:
        return {
            "wall_time_s": round(float(self.wall_time_s), 6),
            "run_dir": self.run_dir,
            "binary_path": self.binary_path,
            "command": list(self.command),
            "host": self.host,
            "platform": self.platform,
            "transport": self.transport,
        }


@dataclass(frozen=True)
class ScientificBackendEvidence:
    """Run-stable facts about one executed backend run."""

    prepared_id: str
    profile_id: str
    projection_semantics_version: str
    config_sha256: str
    trace_sha256: str
    topology_sha256: str | None
    resolved_fabric_hash: str
    physical_traffic_id: str
    message_artifact_id: str
    binary_sha256: str
    binary_size: int
    producer_source_revision: str | None
    producer_dirty: bool | None
    seed: int
    parser_version: str
    execution_fidelity: str
    route_observation: str
    stats: dict[str, Any]
    exit_status: int
    transport: str
    schema_version: int = EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("prepared_id", "config_sha256", "trace_sha256",
                     "resolved_fabric_hash", "physical_traffic_id",
                     "message_artifact_id"):
            value = getattr(self, name)
            if value is not None:
                require_hex64(value, name)
        if self.topology_sha256 is not None:
            require_hex64(self.topology_sha256, "topology_sha256")
        if not isinstance(self.stats, dict) or not self.stats:
            raise BackendEvidenceError(
                "evidence without parsed stats is not a measurement")
        for key, value in self.stats.items():
            if isinstance(value, float):
                require_finite(value, f"stats.{key}")
        if self.schema_version != EVIDENCE_SCHEMA_VERSION:
            raise BackendEvidenceError(
                f"unsupported evidence schema_version "
                f"{self.schema_version!r}")

    #: True only for a real supervised production execution
    @property
    def reusable(self) -> bool:
        return (self.transport == EXECUTION_TRANSPORT_SUPERVISED_PROCESS
                and self.execution_fidelity != "TEST_INJECTED"
                and self.exit_status == 0)

    def scientific_payload(self) -> dict[str, Any]:
        """Everything run-stable. Attempt metadata is absent by design."""
        return {
            "type": _EVIDENCE_DOMAIN,
            "schema_version": self.schema_version,
            "prepared_id": self.prepared_id,
            "profile_id": self.profile_id,
            "projection_semantics_version":
                self.projection_semantics_version,
            "config_sha256": self.config_sha256,
            "trace_sha256": self.trace_sha256,
            "topology_sha256": self.topology_sha256,
            "resolved_fabric_hash": self.resolved_fabric_hash,
            "physical_traffic_id": self.physical_traffic_id,
            "message_artifact_id": self.message_artifact_id,
            "binary_sha256": self.binary_sha256,
            "binary_size": self.binary_size,
            "producer_source_revision": self.producer_source_revision,
            "producer_dirty": self.producer_dirty,
            "seed": self.seed,
            "parser_version": self.parser_version,
            "execution_fidelity": self.execution_fidelity,
            "route_observation": self.route_observation,
            "stats": self.stats,
            "exit_status": self.exit_status,
            "transport": self.transport,
        }

    def evidence_id(self) -> str:
        return content_hash(_EVIDENCE_DOMAIN, self.schema_version,
                            self.scientific_payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.scientific_payload(), "evidence_id": self.evidence_id()}

    def stats_sha256(self) -> str:
        return hashlib.sha256(
            canonical_evidence_json(self.stats).encode()).hexdigest()


@dataclass(frozen=True)
class ExecutionRecord:
    """One execution: scientific evidence + separated attempt metadata."""

    evidence: ScientificBackendEvidence
    attempt: ExecutionAttempt
    ref: EvidenceRef | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence": self.evidence.to_dict(),
            "attempt": self.attempt.to_dict(),
            "evidence_ref": (None if self.ref is None
                             else {"path": self.ref.path,
                                   "sha256": self.ref.sha256}),
        }


def verify_reusable_record(record: ExecutionRecord, *,
                           prepared_id: str, config_sha256: str,
                           trace_sha256: str, binary_sha256: str
                           ) -> ScientificBackendEvidence:
    """Every condition required before evidence may be reused."""
    evidence = record.evidence
    if not evidence.reusable:
        raise BackendEvidenceError(
            "evidence was not produced by a supervised production "
            f"execution (transport={evidence.transport}, "
            f"exit={evidence.exit_status}); it is not reusable")
    if evidence.prepared_id != prepared_id:
        raise BackendEvidenceError(
            "evidence prepared_id does not match the prepared input")
    if evidence.config_sha256 != config_sha256 \
            or evidence.trace_sha256 != trace_sha256:
        raise BackendEvidenceError(
            "evidence prepared-input digests do not match the prepared "
            "input")
    if evidence.binary_sha256 != binary_sha256:
        raise BackendEvidenceError(
            "evidence was produced by a different BookSim binary; "
            "refusing reuse")
    if evidence.parser_version != PARSER_VERSION:
        raise BackendEvidenceError(
            f"evidence parser version {evidence.parser_version!r} is not "
            f"the supported {PARSER_VERSION!r}")
    return evidence


def read_reusable_record(ref: EvidenceRef, **conditions: Any
                         ) -> ScientificBackendEvidence:
    """Digest-verified read + full reuse gating."""
    data = read_verified_evidence(ref)
    evidence_doc = data.get("evidence")
    if not isinstance(evidence_doc, dict):
        raise BackendEvidenceError(
            "evidence file does not carry an evidence document")
    evidence = ScientificBackendEvidence(
        prepared_id=evidence_doc.get("prepared_id"),
        profile_id=evidence_doc.get("profile_id"),
        projection_semantics_version=evidence_doc.get(
            "projection_semantics_version"),
        config_sha256=evidence_doc.get("config_sha256"),
        trace_sha256=evidence_doc.get("trace_sha256"),
        topology_sha256=evidence_doc.get("topology_sha256"),
        resolved_fabric_hash=evidence_doc.get("resolved_fabric_hash"),
        physical_traffic_id=evidence_doc.get("physical_traffic_id"),
        message_artifact_id=evidence_doc.get("message_artifact_id"),
        binary_sha256=evidence_doc.get("binary_sha256"),
        binary_size=evidence_doc.get("binary_size"),
        producer_source_revision=evidence_doc.get("producer_source_revision"),
        producer_dirty=evidence_doc.get("producer_dirty"),
        seed=evidence_doc.get("seed"),
        parser_version=evidence_doc.get("parser_version"),
        execution_fidelity=evidence_doc.get("execution_fidelity"),
        route_observation=evidence_doc.get("route_observation"),
        stats=evidence_doc.get("stats"),
        exit_status=evidence_doc.get("exit_status"),
        transport=evidence_doc.get("transport"),
        schema_version=evidence_doc.get("schema_version",
                                        EVIDENCE_SCHEMA_VERSION),
    )
    return verify_reusable_record(
        ExecutionRecord(evidence=evidence,
                        attempt=ExecutionAttempt(
                            wall_time_s=0.0, run_dir="", binary_path="",
                            command=(), host="", platform="")),
        **conditions)


__all__ = [
    "BackendEvidenceError", "EVIDENCE_FILE", "EVIDENCE_SCHEMA_VERSION",
    "EvidenceRef", "ExecutionAttempt", "ExecutionRecord",
    "PARSER_VERSION", "ScientificBackendEvidence",
    "EXECUTION_TRANSPORT_SUPERVISED_PROCESS",
    "EXECUTION_TRANSPORT_TEST_INJECTED", "canonical_evidence_json",
    "evidence_sha256_of", "read_evidence", "read_reusable_record",
    "read_verified_evidence", "require_finite", "require_hex64",
    "verify_reusable_record", "write_evidence",
]
