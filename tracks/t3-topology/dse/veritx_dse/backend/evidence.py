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
    producer_*            source revision and dirt (NOT tool identity)

evidence-v2: the persisted ``backend-evidence.json`` is the
run-STABLE scientific half only (``ScientificBackendEvidence``, contract
``veritx/backend-scientific-evidence/v2``). Measured wall time, absolute
paths and host platform text are execution-attempt metadata; they live
in the separate ``execution-attempt.json`` record (contract
``veritx/execution-attempt/v1``) and never enter any scientific digest.
The v1 document shape (which embedded those fields in the same file)
remains readable history: its bytes still hash to the same digest and
its scientific fields mean exactly what they meant before.

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
ATTEMPT_FILE = "execution-attempt.json"

# evidence-v2 contract identities. The v2 scientific document is the ONLY
# input to EvidenceRef.sha256 -> EvidenceArtifact -> NetworkWindowBinding
# -> wave_d_chain -> PerformanceResult identity. The attempt record is a
# sibling artifact, never hashed into that chain.
SCIENTIFIC_EVIDENCE_SCHEMA_VERSION = \
    "veritx/backend-scientific-evidence/v2"
EXECUTION_ATTEMPT_SCHEMA_VERSION = "veritx/execution-attempt/v1"


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


# The exact run-stable field set of the v2 scientific evidence document.
_SCIENTIFIC_FIELDS = (
    "backend_config_hash",
    "backend_input_hash",
    "resolved_fabric_hash",
    "fabric_hash",
    "route_equivalence",
    "route_expected_sha256",
    "route_executed_sha256",
    "route_pairs_compared",
    "qualification",
    "semantic_loss",
    "stats",
    "exit_status",
    "workload_hash",
    "seed",
    "seed_policy",
    "rendered_inputs",
    "invocation_args",
    "booksim_binary_sha256",
    "producer_source_revision",
    "producer_source_dirty",
    "producer_source_dirty_digest",
    "execution_transport",
    "parser_version",
)


@dataclass(frozen=True)
class ScientificBackendEvidence:
    """The run-stable scientific half of certified backend evidence (v2).

    Every field here is a property of the scientific claim (what was
    executed, from which bytes, with what result); none varies between
    two identical deterministic runs in different directories. The
    canonical JSON of this document is exactly what ``EvidenceRef.sha256``
    covers, so this identity propagates unchanged into ``EvidenceArtifact``,
    the network window binding, the Wave-D chain and the PerformanceResult.

    Runtime facts (wall time, absolute command/backend paths, host
    platform text) are NOT here; they belong to ``ExecutionAttempt`` and
    never enter a scientific digest.
    """

    backend_config_hash: str
    backend_input_hash: str
    resolved_fabric_hash: str
    fabric_hash: str
    route_equivalence: str
    route_expected_sha256: str
    route_executed_sha256: str
    route_pairs_compared: int
    qualification: str
    semantic_loss: tuple[dict[str, Any], ...]
    stats: dict[str, Any]
    exit_status: int
    workload_hash: str | None
    seed: int | None
    seed_policy: str
    rendered_inputs: tuple[dict[str, Any], ...]
    invocation_args: tuple[tuple[str, str], ...]
    booksim_binary_sha256: str | None
    producer_source_revision: str | None
    producer_source_dirty: bool | None
    producer_source_dirty_digest: str | None
    execution_transport: str
    parser_version: str

    def __post_init__(self):
        for name in ("backend_config_hash", "backend_input_hash",
                     "resolved_fabric_hash", "fabric_hash",
                     "route_expected_sha256", "route_executed_sha256"):
            _require_hex64(getattr(self, name), name)
        for name in ("route_equivalence", "qualification",
                     "execution_transport", "parser_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise BackendEvidenceError(
                    f"{name} must be a non-empty string, got {value!r}")
        if type(self.route_pairs_compared) is not int or \
                self.route_pairs_compared < 0:
            raise BackendEvidenceError(
                "route_pairs_compared must be a non-negative int, got "
                f"{self.route_pairs_compared!r}")
        if type(self.exit_status) is not int:
            raise BackendEvidenceError(
                f"exit_status must be an int, got {self.exit_status!r}")
        stats_sha256_of(self.stats)
        if self.booksim_binary_sha256 is not None:
            _require_hex64(self.booksim_binary_sha256,
                           "booksim_binary_sha256")
        if self.producer_source_dirty_digest is not None:
            _require_hex64(self.producer_source_dirty_digest,
                           "producer_source_dirty_digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCIENTIFIC_EVIDENCE_SCHEMA_VERSION,
            "backend_config_hash": self.backend_config_hash,
            "backend_input_hash": self.backend_input_hash,
            "resolved_fabric_hash": self.resolved_fabric_hash,
            "fabric_hash": self.fabric_hash,
            "route_equivalence": self.route_equivalence,
            "route_expected_sha256": self.route_expected_sha256,
            "route_executed_sha256": self.route_executed_sha256,
            "route_pairs_compared": self.route_pairs_compared,
            "qualification": self.qualification,
            "semantic_loss": [dict(row) for row in self.semantic_loss],
            "stats": dict(self.stats),
            "exit_status": self.exit_status,
            "workload_hash": self.workload_hash,
            "seed": self.seed,
            "seed_policy": self.seed_policy,
            "rendered_inputs": [dict(row)
                                for row in self.rendered_inputs],
            "invocation_args": {k: v for k, v in self.invocation_args},
            "booksim_binary_sha256": self.booksim_binary_sha256,
            "producer_source_revision": self.producer_source_revision,
            "producer_source_dirty": self.producer_source_dirty,
            "producer_source_dirty_digest":
                self.producer_source_dirty_digest,
            "execution_transport": self.execution_transport,
            "parser_version": self.parser_version,
        }

    def digest(self) -> str:
        """The scientific evidence digest: sha256 of the canonical bytes.

        This is the exact value ``write_evidence`` returns as
        ``EvidenceRef.sha256`` for a v2 document.
        """
        return evidence_sha256_of(self.to_dict())

    @classmethod
    def from_dict(cls, doc: Any) -> "ScientificBackendEvidence":
        if not isinstance(doc, dict):
            raise BackendEvidenceError(
                "scientific evidence must be a JSON object")
        if doc.get("schema_version") != SCIENTIFIC_EVIDENCE_SCHEMA_VERSION:
            raise BackendEvidenceError(
                f"scientific evidence must declare schema_version "
                f"{SCIENTIFIC_EVIDENCE_SCHEMA_VERSION!r}, got "
                f"{doc.get('schema_version')!r}")
        expected = {"schema_version", *_SCIENTIFIC_FIELDS}
        if set(doc) != expected:
            raise BackendEvidenceError(
                f"scientific evidence field mismatch; "
                f"missing={sorted(expected - set(doc))}, "
                f"extra={sorted(set(doc) - expected)}")
        loss = doc["semantic_loss"]
        rendered = doc["rendered_inputs"]
        args = doc["invocation_args"]
        if not isinstance(loss, list) or \
                not all(isinstance(r, dict) for r in loss):
            raise BackendEvidenceError(
                "semantic_loss must be a list of objects")
        if not isinstance(rendered, list) or \
                not all(isinstance(r, dict) for r in rendered):
            raise BackendEvidenceError(
                "rendered_inputs must be a list of objects")
        if not isinstance(args, dict):
            raise BackendEvidenceError(
                "invocation_args must be an object")
        return cls(
            backend_config_hash=doc["backend_config_hash"],
            backend_input_hash=doc["backend_input_hash"],
            resolved_fabric_hash=doc["resolved_fabric_hash"],
            fabric_hash=doc["fabric_hash"],
            route_equivalence=doc["route_equivalence"],
            route_expected_sha256=doc["route_expected_sha256"],
            route_executed_sha256=doc["route_executed_sha256"],
            route_pairs_compared=doc["route_pairs_compared"],
            qualification=doc["qualification"],
            semantic_loss=tuple(dict(r) for r in loss),
            stats=dict(doc["stats"]),
            exit_status=doc["exit_status"],
            workload_hash=doc["workload_hash"],
            seed=doc["seed"],
            seed_policy=doc["seed_policy"],
            rendered_inputs=tuple(dict(r) for r in rendered),
            invocation_args=tuple((k, v) for k, v in args.items()),
            booksim_binary_sha256=doc["booksim_binary_sha256"],
            producer_source_revision=doc["producer_source_revision"],
            producer_source_dirty=doc["producer_source_dirty"],
            producer_source_dirty_digest=
                doc["producer_source_dirty_digest"],
            execution_transport=doc["execution_transport"],
            parser_version=doc["parser_version"])


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

    v2 documents are validated against the CLOSED
    ``veritx/backend-scientific-evidence/v2`` schema: exactly the
    scientific fields, no leaked-back attempt metadata, no extras; the
    canonical validated document is returned. Unversioned documents are
    historical v1 and keep their legacy acceptance semantics. Any other
    declared generation refuses — an unknown schema is never read as a
    known one.

    Every consumption path (reuse, authenticated proof, control-plane
    verification) must pass bytes through this before using any field.
    """
    if not isinstance(doc, dict):
        raise BackendEvidenceError(
            f"evidence document must be a JSON object, got "
            f"{type(doc).__name__}")
    version = doc.get("schema_version")
    if version == SCIENTIFIC_EVIDENCE_SCHEMA_VERSION:
        return ScientificBackendEvidence.from_dict(doc).to_dict()
    if version is None:
        return _validate_legacy_v1(doc)
    raise BackendEvidenceError(
        f"unsupported evidence schema_version {version!r}; refusing to "
        f"read an unknown generation as a known one")


@dataclass(frozen=True)
class ExecutionAttempt:
    """Run-varying execution facts, outside every scientific identity.

    Contract ``veritx/execution-attempt/v1``. The measured wall time, the
    absolute command/backend paths and the host platform text are honest
    diagnostics of ONE attempt; two identical deterministic runs will
    (and must) disagree here without that disagreement touching the
    scientific evidence digest or any downstream result identity.
    """

    wall_time_s: float
    command: tuple[str, ...]
    backend_dir: str
    run_dir: str
    producer_tool_identity: str

    def __post_init__(self):
        if isinstance(self.wall_time_s, bool) or \
                not isinstance(self.wall_time_s, (int, float)) or \
                self.wall_time_s < 0:
            raise BackendEvidenceError(
                f"wall_time_s must be a non-negative number, got "
                f"{self.wall_time_s!r}")
        if not self.command or not all(
                isinstance(part, str) and part for part in self.command):
            raise BackendEvidenceError(
                "command must be a non-empty sequence of non-empty "
                "strings")
        for name in ("backend_dir", "run_dir"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise BackendEvidenceError(
                    f"{name} must be a non-empty string, got {value!r}")
        if not isinstance(self.producer_tool_identity, str):
            raise BackendEvidenceError(
                "producer_tool_identity must be a string")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EXECUTION_ATTEMPT_SCHEMA_VERSION,
            "wall_time_s": self.wall_time_s,
            "command": list(self.command),
            "backend_dir": self.backend_dir,
            "run_dir": self.run_dir,
            "producer_tool_identity": self.producer_tool_identity,
        }


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
    "EVIDENCE_FILE",
    "BackendEvidenceError",
    "ATTEMPT_FILE",
    "EXECUTION_ATTEMPT_SCHEMA_VERSION",
    "SCIENTIFIC_EVIDENCE_SCHEMA_VERSION",
    "EvidenceArtifact",
    "EvidenceRef",
    "ExecutionAttempt",
    "ExecutionAttemptRef",
    "LEGACY_PARSER_VERSION",
    "PARSER_VERSION",
    "ScientificBackendEvidence",
    "canonical_evidence_json",
    "evidence_sha256",
    "evidence_sha256_of",
    "read_evidence",
    "read_verified_evidence",
    "stats_sha256_of",
    "validate_evidence_document",
    "write_evidence",
    "write_execution_attempt",
]
