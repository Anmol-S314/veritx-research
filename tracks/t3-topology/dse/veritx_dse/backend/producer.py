"""veritx_dse.backend.producer — identify exactly what executed.

Reclaimed from the historical ``backend/producer.py``. The binary digest is
the primary statement of what executed; a Git revision alone is NOT proof
of binary provenance. A dirty or unpinned producer may be executed for
diagnosis, but must never silently receive reusable evidence status.
"""
from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ProducerError(ValueError):
    """The producer cannot be identified or is not reusable."""


# Canonical execution-transport values (reclaimed verbatim from the RT
# candidate 26e6f9dc, additive only): the production runner is the only
# transport whose evidence is reusable; anything else is a test fixture.
# The RT backend stack (backend/meshdor.py) imports these names.
EXECUTION_TRANSPORT_SUPERVISED_PROCESS = "SUPERVISED_PROCESS"
EXECUTION_TRANSPORT_TEST_INJECTED = "TEST_INJECTED"


@dataclass(frozen=True)
class ProducerIdentity:
    """Exact identity of the executable that ran."""

    binary_path: str
    binary_sha256: str
    binary_size: int
    source_revision: str | None
    dirty: bool | None
    dirty_digest: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.binary_sha256, str) \
                or len(self.binary_sha256) != 64:
            raise ProducerError(
                f"binary_sha256 must be a 64-char hex digest, got "
                f"{self.binary_sha256!r}")
        if type(self.binary_size) is not int or self.binary_size <= 0:
            raise ProducerError(
                f"binary_size must be a positive int, got "
                f"{self.binary_size!r}")

    @property
    def pinned(self) -> bool:
        """A clean, revision-identified producer."""
        return self.source_revision is not None and self.dirty is False

    @property
    def tool_identity(self) -> str:
        """RT-reclaim compatibility: execution-platform descriptor.

        Historical RT evidence records ``producer_tool_identity`` as the
        platform string captured at resolve time; it is attempt metadata,
        not science. Derived on access so the canonical frozen dataclass
        stays unchanged.
        """
        import platform
        return platform.platform()

    def to_dict(self) -> dict:
        return {
            "binary_path": self.binary_path,
            "binary_sha256": self.binary_sha256,
            "binary_size": self.binary_size,
            "source_revision": self.source_revision,
            "dirty": self.dirty,
            "dirty_digest": self.dirty_digest,
            "pinned": self.pinned,
        }


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _git(repo_root: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(["git", *args], cwd=str(repo_root),
                              stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def resolve_producer_identity(binary: Path, *,
                              repo_root: Path | None = None
                              ) -> ProducerIdentity:
    """SHA-256 + size (+ git revision/dirty state when a repo is given)."""
    path = Path(binary)
    if not path.is_file():
        raise ProducerError(f"BookSim binary not found: {path}")
    if path.stat().st_size == 0:
        raise ProducerError(f"BookSim binary is empty: {path}")
    try:
        digest, size = _sha256_file(path)
    except OSError as exc:
        raise ProducerError(
            f"BookSim binary is unreadable: {path}: {exc}") from exc
    revision: str | None = None
    dirty: bool | None = None
    dirty_digest: str | None = None
    if repo_root is not None:
        root = Path(repo_root)
        revision = _git(root, "rev-parse", "HEAD")
        status = _git(root, "status", "--porcelain")
        if status is not None:
            dirty = bool(status)
            if dirty:
                # dirty-content digest: the observed tree delta, not a
                # wall-clock or path observation
                dirty_digest = hashlib.sha256(
                    (status + "\n" + digest).encode()).hexdigest()
    return ProducerIdentity(
        binary_path=str(path), binary_sha256=digest, binary_size=size,
        source_revision=revision, dirty=dirty, dirty_digest=dirty_digest)


def recheck_binary_digest(identity: ProducerIdentity) -> None:
    """Prove the binary cannot have changed since identification."""
    path = Path(identity.binary_path)
    if not path.is_file():
        raise ProducerError(
            f"BookSim binary disappeared after identification: {path}")
    digest, size = _sha256_file(path)
    if digest != identity.binary_sha256 or size != identity.binary_size:
        raise ProducerError(
            "BookSim binary changed between identification and execution "
            f"({identity.binary_sha256} -> {digest}); refusing to execute "
            "an unidentified producer")


def assert_pinned_producer(identity: ProducerIdentity) -> None:
    """Reusable evidence requires a pinned (clean, revisioned) producer."""
    if identity.source_revision is None:
        raise ProducerError(
            "producer source revision is unknown: a binary digest alone "
            "cannot certify provenance for reusable evidence")
    if identity.dirty:
        raise ProducerError(
            "producer tree is DIRTY; a dirty build may be executed for "
            "diagnosis but cannot receive reusable evidence status")


__all__ = [
    "ProducerError", "ProducerIdentity", "assert_pinned_producer",
    "recheck_binary_digest", "resolve_producer_identity",
]
