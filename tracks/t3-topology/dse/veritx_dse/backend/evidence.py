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

#: v2: the run-stable scientific payload also binds the BUILD provenance
#: that established producer qualification: ``build_manifest_sha256`` (the
#: exact build manifest the binary was verified against) and
#: ``build_recipe_version``. A v1 document cannot prove which manifest (or
#: recipe) qualified its binary, so the generations are declared
#: incompatible: v1 is refused, never silently reread as v2.
EVIDENCE_SCHEMA_VERSION = 2
#: parser generation (independent of the evidence-schema generation)
PARSER_VERSION = "veritx/booksim-stats-parser/v2"
LEGACY_PARSER_VERSION = "veritx/evidence-parser/v0-unversioned"
ATTEMPT_FILE = "execution-attempt.json"
EXECUTION_ATTEMPT_SCHEMA_VERSION = "veritx/execution-attempt/v1"
_EVIDENCE_ARTIFACT_DOMAIN = "veritx/evidence-artifact/v1"
_EVIDENCE_DOMAIN = "srota/ScientificBackendEvidence"

#: execution transports (only the supervised process is reusable)
EXECUTION_TRANSPORT_SUPERVISED_PROCESS = "SUPERVISED_PROCESS"
EXECUTION_TRANSPORT_TEST_INJECTED = "TEST_INJECTED"

_HEX = frozenset("0123456789abcdef")

#: Closed vocabularies for the run-stable scientific fields. An unknown
#: token is not a known measurement: a reader must never treat an invented
#: fidelity or transport as qualified, and a self-consistent document with
#: an impossible combination must refuse even though its evidence_id
#: recomputes.
EXECUTION_FIDELITIES = frozenset({
    "QUALIFIED", "DIAGNOSTIC_UNPINNED_PRODUCER", "TEST_INJECTED",
})
ROUTE_OBSERVATIONS = frozenset({
    "DOMAIN_QUALIFIED_ROUTE_NOT_OBSERVED", "EXECUTED_ROUTE_OBSERVED",
})
EXECUTION_TRANSPORTS = frozenset({
    EXECUTION_TRANSPORT_SUPERVISED_PROCESS, EXECUTION_TRANSPORT_TEST_INJECTED,
})


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


def stats_sha256_of(stats: dict[str, Any]) -> str:
    """Canonical digest of the parsed stats mapping."""
    if not isinstance(stats, dict) or not stats:
        raise BackendEvidenceError(
            "evidence without parsed stats is not a measurement")
    return hashlib.sha256(
        canonical_evidence_json(stats).encode()).hexdigest()


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
    #: exact build manifest the binary was verified against, and its recipe
    #: version. Required for a certified-product admission: without them the
    #: evidence cannot prove WHICH manifest established qualification.
    build_manifest_sha256: str | None = None
    build_recipe_version: str | None = None
    schema_version: int = EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("prepared_id", "config_sha256", "trace_sha256",
                     "resolved_fabric_hash", "physical_traffic_id",
                     "message_artifact_id"):
            value = getattr(self, name)
            if value is not None:
                require_hex64(value, name)
        require_hex64(self.binary_sha256, "binary_sha256")
        if self.topology_sha256 is not None:
            require_hex64(self.topology_sha256, "topology_sha256")
        if self.build_manifest_sha256 is not None:
            require_hex64(self.build_manifest_sha256,
                          "build_manifest_sha256")
        if self.build_recipe_version is not None \
                and (not isinstance(self.build_recipe_version, str)
                     or not self.build_recipe_version):
            raise BackendEvidenceError(
                "build_recipe_version must be a non-empty string or null")
        if type(self.seed) is not int or isinstance(self.seed, bool) \
                or self.seed < 0:
            raise BackendEvidenceError(
                f"seed must be a non-negative int, got {self.seed!r}")
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
        # Closed vocabularies + cross-field impossibility. Content
        # authenticity (the evidence_id) is necessary but not sufficient:
        # a self-consistent document can still describe a run that cannot
        # exist, and must refuse before it can be read as a measurement.
        if self.transport not in EXECUTION_TRANSPORTS:
            raise BackendEvidenceError(
                f"unknown execution transport {self.transport!r}")
        if self.execution_fidelity not in EXECUTION_FIDELITIES:
            raise BackendEvidenceError(
                f"unknown execution_fidelity {self.execution_fidelity!r}")
        if self.route_observation not in ROUTE_OBSERVATIONS:
            raise BackendEvidenceError(
                f"unknown route_observation {self.route_observation!r}")
        if self.producer_dirty is not None \
                and not isinstance(self.producer_dirty, bool):
            raise BackendEvidenceError(
                "producer_dirty must be a bool or null")
        if self.execution_fidelity == "QUALIFIED":
            if self.transport != EXECUTION_TRANSPORT_SUPERVISED_PROCESS:
                raise BackendEvidenceError(
                    "QUALIFIED fidelity over a non-supervised transport is "
                    "impossible")
            if self.producer_source_revision is None:
                raise BackendEvidenceError(
                    "QUALIFIED fidelity requires a known producer source "
                    "revision")
            if self.producer_dirty is not False:
                raise BackendEvidenceError(
                    "QUALIFIED fidelity requires producer_dirty to be False")
            if self.exit_status != 0:
                raise BackendEvidenceError(
                    "QUALIFIED evidence cannot carry a nonzero exit status")
        if self.transport == EXECUTION_TRANSPORT_TEST_INJECTED \
                and self.execution_fidelity != "TEST_INJECTED":
            raise BackendEvidenceError(
                "TEST_INJECTED transport must carry TEST_INJECTED fidelity")

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
            "build_manifest_sha256": self.build_manifest_sha256,
            "build_recipe_version": self.build_recipe_version,
        }

    def evidence_id(self) -> str:
        return content_hash(_EVIDENCE_DOMAIN, self.schema_version,
                            self.scientific_payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.scientific_payload(), "evidence_id": self.evidence_id()}

    @classmethod
    def from_dict(cls, doc: Any) -> "ScientificBackendEvidence":
        """Rebuild validated evidence from a persisted scientific document.

        Closed field set (exactly what to_dict emits — no extras, no
        missing keys), type-tag and schema-version pinned, and the
        embedded evidence_id must equal the recomputed one: a forged or
        transplanted document cannot pass. This is the read half of the
        write/read contract validate_evidence_document enforces.
        """
        if not isinstance(doc, dict):
            raise BackendEvidenceError(
                f"evidence document must be a JSON object, got "
                f"{type(doc).__name__}")
        expected = {
            "type", "schema_version", "prepared_id", "profile_id",
            "projection_semantics_version", "config_sha256",
            "trace_sha256", "topology_sha256", "resolved_fabric_hash",
            "physical_traffic_id", "message_artifact_id", "binary_sha256",
            "binary_size", "producer_source_revision", "producer_dirty",
            "seed", "parser_version", "execution_fidelity",
            "route_observation", "stats", "exit_status", "transport",
            "build_manifest_sha256", "build_recipe_version",
            "evidence_id",
        }
        unknown = set(doc) - expected
        if unknown:
            raise BackendEvidenceError(
                f"evidence document has unknown fields: "
                f"{sorted(unknown)}")
        missing = expected - set(doc)
        if missing:
            raise BackendEvidenceError(
                f"evidence document is missing required fields: "
                f"{sorted(missing)}")
        if doc["type"] != _EVIDENCE_DOMAIN:
            raise BackendEvidenceError(
                f"evidence type must be {_EVIDENCE_DOMAIN!r}, got "
                f"{doc['type']!r}")
        for name in ("binary_size", "seed", "exit_status"):
            if not isinstance(doc[name], int) \
                    or isinstance(doc[name], bool):
                raise BackendEvidenceError(
                    f"evidence field {name!r} must be an exact int, got "
                    f"{type(doc[name]).__name__}")
        evidence = cls(
            prepared_id=doc["prepared_id"], profile_id=doc["profile_id"],
            projection_semantics_version=doc[
                "projection_semantics_version"],
            config_sha256=doc["config_sha256"],
            trace_sha256=doc["trace_sha256"],
            topology_sha256=doc["topology_sha256"],
            resolved_fabric_hash=doc["resolved_fabric_hash"],
            physical_traffic_id=doc["physical_traffic_id"],
            message_artifact_id=doc["message_artifact_id"],
            binary_sha256=doc["binary_sha256"],
            binary_size=doc["binary_size"],
            producer_source_revision=doc["producer_source_revision"],
            producer_dirty=doc["producer_dirty"],
            seed=doc["seed"], parser_version=doc["parser_version"],
            execution_fidelity=doc["execution_fidelity"],
            route_observation=doc["route_observation"],
            stats=doc["stats"], exit_status=doc["exit_status"],
            transport=doc["transport"],
            build_manifest_sha256=doc["build_manifest_sha256"],
            build_recipe_version=doc["build_recipe_version"],
            schema_version=doc["schema_version"])
        if evidence.evidence_id() != doc["evidence_id"]:
            raise BackendEvidenceError(
                "evidence_id does not match the recomputed content "
                "identity — document tampered with or transplanted")
        return evidence

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


def admit_for_certified_product(
        evidence: "ScientificBackendEvidence") -> None:
    """THE single admission rule for evidence entering a certified product.

    Content authenticity (a valid ``evidence_id``) is not admission: a
    document can hash correctly and still describe a diagnostic, dirty,
    unpinned or test-injected run. This function is the one place that
    decides qualification; call sites must not re-implement it.

    Requires: supervised production transport, QUALIFIED fidelity, a known
    producer source revision, a clean (not dirty) producer, exit 0, and a
    verified build manifest + recipe bound into the evidence.
    ``TEST_INJECTED``, diagnostic, dirty, unpinned, unknown-build and
    unmanifested runs are refused.
    """
    if not isinstance(evidence, ScientificBackendEvidence):
        raise BackendEvidenceError(
            "certified-product admission requires "
            f"ScientificBackendEvidence, got {type(evidence).__name__}")
    if evidence.transport != EXECUTION_TRANSPORT_SUPERVISED_PROCESS:
        raise BackendEvidenceError(
            f"evidence transport {evidence.transport!r} is not a supervised "
            "production process; it cannot enter a certified product")
    if evidence.execution_fidelity != "QUALIFIED":
        raise BackendEvidenceError(
            f"evidence execution_fidelity {evidence.execution_fidelity!r} "
            "is not QUALIFIED; it cannot enter a certified product")
    if evidence.producer_source_revision is None:
        raise BackendEvidenceError(
            "producer source revision is unknown; a binary digest alone "
            "cannot certify provenance for a certified product")
    if evidence.producer_dirty is not False:
        raise BackendEvidenceError(
            f"producer dirty state {evidence.producer_dirty!r} is not False; "
            "a dirty or unknown build cannot enter a certified product")
    if evidence.exit_status != 0:
        raise BackendEvidenceError(
            f"evidence exit_status {evidence.exit_status!r} is not 0; a "
            "failed execution cannot enter a certified product")
    if evidence.build_manifest_sha256 is None:
        raise BackendEvidenceError(
            "evidence binds no build manifest; qualification cannot be "
            "traced to a verified build — it cannot enter a certified product")
    if evidence.build_recipe_version is None:
        raise BackendEvidenceError(
            "evidence binds no build recipe version; it cannot enter a "
            "certified product")


def verify_reusable_record(record: ExecutionRecord, *,
                           prepared_id: str, config_sha256: str,
                           trace_sha256: str, binary_sha256: str
                           ) -> ScientificBackendEvidence:
    """Every condition required before evidence may be reused."""
    evidence = record.evidence
    admit_for_certified_product(evidence)
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
    """Digest-verified read + schema validation + full reuse gating.

    No alternate reader: the persisted bytes are verified against the
    external ``EvidenceRef`` digest, then the document must pass the
    canonical ``validate_evidence_document`` (which recomputes and checks
    the embedded ``evidence_id``), then ``admit_for_certified_product``.
    """
    data = read_verified_evidence(ref)
    evidence_doc = data.get("evidence")
    if not isinstance(evidence_doc, dict):
        raise BackendEvidenceError(
            "evidence file does not carry an evidence document")
    validated = validate_evidence_document(evidence_doc)
    evidence = ScientificBackendEvidence.from_dict(validated)
    return verify_reusable_record(
        ExecutionRecord(evidence=evidence,
                        attempt=ExecutionAttempt(
                            wall_time_s=0.0, run_dir="", binary_path="",
                            command=(), host="", platform="")),
        **conditions)


# Fields every unversioned historical (v1) consumer needed. v1 predates
# the schema marker, so there is no closed field set to enforce; these
# are the minimum keys that make the document readable as certified
# evidence at all.
_LEGACY_V1_REQUIRED_FIELDS = ("backend_input_hash", "stats")


def _validate_legacy_v1(doc: dict[str, Any]) -> dict[str, Any]:
    """Acceptance rules for unversioned historical evidence (v1).

    The old consumers checked only the binding keys they needed and
    treated every other field as informational, so this preserves that
    permissiveness: require the minimum evidence keys, accept and return
    the historical extras unchanged. The v1 producer acceptance
    semantics (including ``producer_tool_identity``) live in the reuse
    binding, not here.
    """
    for key in _LEGACY_V1_REQUIRED_FIELDS:
        if key not in doc:
            raise BackendEvidenceError(
                f"legacy v1 evidence is missing {key!r}")
    stats_sha256_of(doc["stats"])
    return doc


def validate_evidence_document(doc: Any) -> dict[str, Any]:
    """The one generation-aware evidence-schema authority.

    Current-version documents are validated against the CLOSED
    scientific-evidence schema: exactly the scientific fields, no
    leaked-back attempt metadata, no extras; the canonical validated
    document is returned. Unversioned documents are historical v1 and
    keep their legacy acceptance semantics. Any other declared
    generation refuses — an unknown schema is never read as a known one.

    Every consumption path (reuse, authenticated proof, control-plane
    verification) must pass bytes through this before using any field.
    """
    if not isinstance(doc, dict):
        raise BackendEvidenceError(
            f"evidence document must be a JSON object, got "
            f"{type(doc).__name__}")
    version = doc.get("schema_version")
    if version == EVIDENCE_SCHEMA_VERSION:
        return ScientificBackendEvidence.from_dict(doc).to_dict()
    if version is None:
        return _validate_legacy_v1(doc)
    raise BackendEvidenceError(
        f"unsupported evidence schema_version {version!r}; refusing to "
        f"read an unknown generation as a known one")


@dataclass(frozen=True)


class ExecutionAttemptRef:
    """External content identity for one persisted attempt record.

    Deliberately NOT an ``EvidenceRef``: an attempt record authenticates
    nothing scientific and must never be passed to evidence-reuse APIs.
    """

    path: str
    sha256: str

    def __post_init__(self):
        if not isinstance(self.path, str) or not self.path:
            raise BackendEvidenceError(
                f"attempt path must be a non-empty string, got "
                f"{self.path!r}")
        if not isinstance(self.sha256, str) or len(self.sha256) != 64 \
                or any(c not in "0123456789abcdef"
                       for c in self.sha256):
            raise BackendEvidenceError(
                f"attempt sha256 must be a 64-char hex digest, got "
                f"{self.sha256!r}")


def write_execution_attempt(directory: Path,
                            attempt: dict[str, Any]) \
        -> ExecutionAttemptRef:
    """Persist the attempt record beside the scientific evidence.

    Idempotent for identical content; refuses to overwrite a different
    attempt at the same path (one attempt slot, one attempt). The record
    is canonical JSON but its digest is never mixed into the scientific
    chain.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ATTEMPT_FILE
    payload = canonical_evidence_json(attempt)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    if path.exists():
        existing = path.read_text()
        if hashlib.sha256(existing.encode()).hexdigest() != digest:
            raise BackendEvidenceError(
                f"{path} already holds a different execution attempt; "
                "refusing to overwrite attempt history")
        return ExecutionAttemptRef(path=str(path), sha256=digest)
    from veritx_dse.core.recovery import atomic_write
    with atomic_write(path) as tmp:
        tmp.write_text(payload)
    return ExecutionAttemptRef(path=str(path), sha256=digest)


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
            require_hex64(getattr(self, name), name)

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

        The document must already have passed ``read_verified_evidence``
        AND ``validate_evidence_document``: only then can the ref digest
        be trusted as the raw-bytes identity and the fields be read as
        the declared generation's contract. ``parser_version`` is stamped
        from the document when the producer wrote one; historical
        documents predate versioning and get the legacy tag, so a
        different reader is a different claim.
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
        # The label order preserves v1 artifact identity exactly: v1
        # documents carry host platform text and it remains the label.
        # v2 documents carry no platform text, so the authenticated
        # transport is the stable label.
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
    "BackendEvidenceError", "EVIDENCE_FILE", "EVIDENCE_SCHEMA_VERSION",
    "EvidenceRef", "ExecutionAttempt", "ExecutionRecord",
    "PARSER_VERSION", "ScientificBackendEvidence",
    "EXECUTION_TRANSPORT_SUPERVISED_PROCESS",
    "EXECUTION_TRANSPORT_TEST_INJECTED", "canonical_evidence_json",
    "evidence_sha256_of", "read_evidence", "read_reusable_record",
    "read_verified_evidence", "require_finite", "require_hex64",
    "verify_reusable_record", "write_evidence",
]
