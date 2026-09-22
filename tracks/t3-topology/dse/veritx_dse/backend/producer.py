"""veritx_dse.backend.producer — execution-producer identity (B-FINAL).

B3.8i proves the input chain end to end:

    bundle -> canonical config -> exact rendered bytes -> canonical manifest

but the evidence still recorded the BookSim binary as a post-run
*observation* (possibly ``None``): a caller could substitute the binary,
rebuild it from a dirty tree, or reuse an evidence file for a different
producer while preserving a false claim. This module binds the producer:

    exact binary bytes (sha256, pre-spawn, fail closed)
    source revision (git HEAD at the repo root, when available)
    dirty-source state and content (tracked diff digest of the worktree)
    tool/environment identity (host platform + harness)

plus the safe-reuse rule: an evidence file is valid for reuse only when
its recorded config hash, input hash and producer digest match the actual
attempt. Evidence that predates producer binding (no recorded digest)
cannot be reused — it can only be re-executed.

What this does NOT claim: the recorded source revision is provenance, not
a rebuild proof. Nothing here proves the binary was built from that tree;
only the binary digest binds what actually executed. A dirty tree is
recorded honestly (revision + diff digest), never laundered into clean.
Scope is tracked sources only: untracked files are excluded by policy
(they are outputs and scratch, not sources), documented wherever the
digest is produced.
"""
from __future__ import annotations

import hashlib
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class ProducerError(ValueError):
    """The execution producer cannot be identified or reused safely."""


# Canonical execution-transport values. The production runner is the only
# transport whose evidence is reusable; anything else is a test fixture.
EXECUTION_TRANSPORT_SUPERVISED_PROCESS = "SUPERVISED_PROCESS"
EXECUTION_TRANSPORT_TEST_INJECTED = "TEST_INJECTED"


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        c in "0123456789abcdef" for c in value)


@dataclass(frozen=True)
class ProducerIdentity:
    """What actually executed a certified backend attempt."""

    binary_sha256: str
    binary_size: int
    source_revision: str | None
    source_dirty: bool | None
    source_dirty_digest: str | None
    tool_identity: str

    def __post_init__(self):
        if not _is_sha256(self.binary_sha256):
            raise ProducerError(
                f"binary_sha256 must be a 64-char hex digest, got "
                f"{self.binary_sha256!r}")
        if type(self.binary_size) is not int or self.binary_size < 1:
            raise ProducerError(
                f"binary_size must be a positive int, got "
                f"{self.binary_size!r}")
        if self.source_revision is not None and (
                not isinstance(self.source_revision, str)
                or not self.source_revision):
            raise ProducerError(
                f"source_revision must be a non-empty string or None, got "
                f"{self.source_revision!r}")
        if self.source_dirty is not None and \
                type(self.source_dirty) is not bool:
            raise ProducerError(
                f"source_dirty must be a bool or None, got "
                f"{self.source_dirty!r}")
        if self.source_dirty_digest is not None and not _is_sha256(
                self.source_dirty_digest):
            raise ProducerError(
                f"source_dirty_digest must be a 64-char hex digest or None, "
                f"got {self.source_dirty_digest!r}")
        if self.source_revision is None and (
                self.source_dirty is not None
                or self.source_dirty_digest is not None):
            raise ProducerError(
                "dirty state without a source revision is meaningless; "
                "record all source fields or none")
        if not isinstance(self.tool_identity, str) or \
                not self.tool_identity:
            raise ProducerError("tool_identity must be a non-empty string")

    @property
    def source_pinned(self) -> bool:
        """A clean checkout at a known revision — the reusable case."""
        return self.source_revision is not None \
            and self.source_dirty is False

    def identity_dict(self) -> dict[str, Any]:
        return {
            "binary_sha256": self.binary_sha256,
            "binary_size": self.binary_size,
            "source_revision": self.source_revision,
            "source_dirty": self.source_dirty,
            "source_dirty_digest": self.source_dirty_digest,
            "tool_identity": self.tool_identity,
        }


def _git_text(repo_root: Path, *args: str) -> str | None:
    """Run git and return stdout, or None when git is unavailable."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def _git_bytes(repo_root: Path, *args: str) -> bytes | None:
    """Run git and return raw stdout bytes (for possibly-binary output)."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def resolve_producer_identity(binary: Path, *,
                              repo_root: Path) -> ProducerIdentity:
    """Identify the exact producer bytes before they are spawned.

    Refuses when the binary cannot be read: certified evidence must never
    claim an execution whose producer digest is unknown. Source revision
    and dirt are recorded when the repo root is a git checkout and left
    explicitly ``None`` otherwise (unpinned provenance, never invented).
    The dirty digest is a content digest: the deterministic bytes of
    ``git diff --no-ext-diff --no-textconv --binary HEAD --`` (staged and
    unstaged tracked changes, including deletions and mode changes), so
    different edits to the same files produce different digests; a clean
    tree hashes the empty diff. Untracked files are excluded by policy.
    The binary digest remains the primary binding either way.
    """
    try:
        data = Path(binary).read_bytes()
    except OSError as exc:
        raise ProducerError(
            f"cannot hash execution producer {binary}: {exc}; refusing to "
            f"produce certified evidence for an unidentified binary"
        ) from exc
    if not data:
        raise ProducerError(
            f"execution producer {binary} is empty; refusing")
    revision = _git_text(repo_root, "rev-parse", "HEAD")
    revision = revision.strip() if revision is not None else None
    dirty: bool | None = None
    dirty_digest: str | None = None
    if revision is not None:
        diff = _git_bytes(repo_root, "diff", "--no-ext-diff",
                          "--no-textconv", "--binary", "HEAD", "--")
        if diff is not None:
            dirty = bool(diff.strip())
            dirty_digest = hashlib.sha256(diff).hexdigest()
    return ProducerIdentity(
        binary_sha256=hashlib.sha256(data).hexdigest(),
        binary_size=len(data),
        source_revision=revision or None,
        source_dirty=dirty,
        source_dirty_digest=dirty_digest,
        tool_identity=platform.platform(),
    )


def assert_pinned_producer(producer: ProducerIdentity) -> None:
    """Refuse evidence-grade reuse from an unpinned or dirty producer.

    Uses the exact ``source_pinned`` invariant: a known revision AND a
    successfully observed clean tree. ``None`` dirt state is never read
    as clean.
    """
    if not producer.source_pinned:
        if producer.source_revision is None:
            raise ProducerError(
                "producer source revision unavailable (no git revision); "
                "refusing evidence-grade reuse — re-execute under a "
                "pinned checkout")
        if producer.source_dirty is None:
            raise ProducerError(
                f"producer dirty-state observation failed at "
                f"{producer.source_revision}; refusing evidence-grade "
                f"reuse — dirt state is unknown, never assumed clean")
        raise ProducerError(
            f"producer source tree is dirty at "
            f"{producer.source_revision}; refusing evidence-grade reuse — "
            f"commit or stash first (dirt "
            f"{producer.source_dirty_digest})")


def _verify_evidence_binding_fields(
        evidence: Mapping[str, Any], *,
        backend_config_hash: str,
        backend_input_hash: str,
        producer: ProducerIdentity) -> None:
    """Field binding for safe reuse (internal primitive).

    NOT a reuse API: it accepts an in-memory mapping and therefore cannot
    authenticate result bytes. The only public reuse operation is
    ``verify_reusable_evidence``, which digest-verifies persisted bytes
    first and then calls this. Enforces the transport invariant (only
    authoritative supervised-process evidence reuses), producer pinning,
    and the recorded config/input/producer identities — generation-aware:
    v2 verifies source revision/dirt only (platform text is attempt
    metadata); historical v1 still verifies ``producer_tool_identity``
    exactly as it did before evidence-v2.
    """
    from .evidence import (
        BackendEvidenceError, SCIENTIFIC_EVIDENCE_SCHEMA_VERSION,
    )
    if evidence.get("execution_transport") != \
            EXECUTION_TRANSPORT_SUPERVISED_PROCESS:
        raise ProducerError(
            "evidence cannot be reused: non-production execution "
            f"transport {evidence.get('execution_transport')!r}; only "
            f"{EXECUTION_TRANSPORT_SUPERVISED_PROCESS} evidence from the "
            f"authoritative process runner is reusable")
    assert_pinned_producer(producer)
    if not isinstance(evidence, Mapping):
        raise ProducerError(
            f"evidence must be a mapping, got {type(evidence).__name__}")
    for key in ("backend_config_hash", "backend_input_hash",
                "booksim_binary_sha256"):
        if key not in evidence:
            raise ProducerError(
                f"evidence cannot be reused: missing {key!r} (predates "
                f"producer binding or malformed)")
    if evidence["backend_config_hash"] != backend_config_hash:
        raise ProducerError(
            "evidence cannot be reused: it describes a different backend "
            "config")
    if evidence["backend_input_hash"] != backend_input_hash:
        raise ProducerError(
            "evidence cannot be reused: it describes different backend "
            "inputs (workload, seed, rendered bytes or invocation)")
    if evidence["booksim_binary_sha256"] != producer.binary_sha256:
        raise ProducerError(
            "evidence cannot be reused: it was produced by a different "
            "binary")
    version = evidence.get("schema_version")
    if version == SCIENTIFIC_EVIDENCE_SCHEMA_VERSION:
        producer_fields = ("producer_source_revision",
                           "producer_source_dirty",
                           "producer_source_dirty_digest")
    elif version is None:
        # Historical v1 acceptance semantics: the platform text WAS part
        # of the reuse binding and must still be verified.
        producer_fields = ("producer_source_revision",
                           "producer_source_dirty",
                           "producer_source_dirty_digest",
                           "producer_tool_identity")
    else:
        raise BackendEvidenceError(
            f"unsupported evidence schema_version {version!r}; refusing "
            f"to reuse evidence from an unknown generation")
    for key in producer_fields:
        if key not in evidence:
            raise ProducerError(
                f"evidence cannot be reused: missing {key!r} (predates "
                f"producer binding)")
    recorded = {
        "source_revision": evidence["producer_source_revision"],
        "source_dirty": evidence["producer_source_dirty"],
        "source_dirty_digest": evidence["producer_source_dirty_digest"],
    }
    actual = {
        "source_revision": producer.source_revision,
        "source_dirty": producer.source_dirty,
        "source_dirty_digest": producer.source_dirty_digest,
    }
    if "producer_tool_identity" in producer_fields:
        recorded["tool_identity"] = evidence["producer_tool_identity"]
        actual["tool_identity"] = producer.tool_identity
    if recorded != actual:
        differing = sorted(k for k in recorded if recorded[k] != actual[k])
        raise ProducerError(
            f"evidence cannot be reused: producer provenance differs in "
            f"{differing}")


def verify_reusable_evidence(
        ref: Any, *,
        backend_config_hash: str,
        backend_input_hash: str,
        producer: ProducerIdentity) -> dict[str, Any]:
    """The one authoritative evidence-reuse operation.

    Proves, in order: the evidence transport is the authoritative
    supervised process; the producer is pinned; the persisted bytes match
    the external content identity (``EvidenceRef.sha256``); the bytes
    parse as evidence; the document passes generation-aware CLOSED-schema
    validation; the recorded config, input and producer identities match
    this attempt. Returns the verified evidence mapping. Anything else
    refuses — callers must not assemble these checks by hand.
    """
    from .evidence import read_verified_evidence, validate_evidence_document
    evidence = validate_evidence_document(read_verified_evidence(ref))
    _verify_evidence_binding_fields(
        evidence, backend_config_hash=backend_config_hash,
        backend_input_hash=backend_input_hash, producer=producer)
    return evidence


__all__ = [
    "EXECUTION_TRANSPORT_SUPERVISED_PROCESS",
    "EXECUTION_TRANSPORT_TEST_INJECTED",
    "ProducerError",
    "ProducerIdentity",
    "assert_pinned_producer",
    "resolve_producer_identity",
    "verify_reusable_evidence",
]
