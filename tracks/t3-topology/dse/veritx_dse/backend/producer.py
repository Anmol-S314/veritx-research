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
    #: True only when a build-time manifest verified the binary against
    #: the source revision/dirty state observed AT BUILD. Ambient git HEAD
    #: is not build provenance and never sets this.
    manifest_verified: bool = False
    #: identity of the manifest that established qualification, and the
    #: build recipe it was produced by. Bound into evidence so a certified
    #: product can name exactly which manifest qualified its binary.
    build_manifest_sha256: str | None = None
    build_recipe_version: str | None = None

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
        if self.build_manifest_sha256 is not None \
                and (not isinstance(self.build_manifest_sha256, str)
                     or len(self.build_manifest_sha256) != 64):
            raise ProducerError(
                "build_manifest_sha256 must be a 64-char hex digest or null")

    @property
    def pinned(self) -> bool:
        """A clean, revision-identified, manifest-verified producer."""
        return (self.source_revision is not None and self.dirty is False
                and self.manifest_verified
                and self.build_manifest_sha256 is not None
                and self.build_recipe_version is not None)

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
            "manifest_verified": self.manifest_verified,
            "build_manifest_sha256": self.build_manifest_sha256,
            "build_recipe_version": self.build_recipe_version,
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
                              repo_root: Path | None = None,
                              manifest_path: Path | None = None,
                              require_manifest_recipe: str | None = None
                              ) -> ProducerIdentity:
    """SHA-256 + size, plus BUILD-TIME provenance when a manifest exists.

    A verified build-time manifest is authoritative: it names the source
    revision and dirty state observed when the binary was built, so a
    binary built at A stays attributed to A even after the tree is
    checked out at B. With no manifest, only ambient git state is
    available and ``manifest_verified`` stays False, so the producer can
    never be pinned for reusable evidence.
    """
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
    from veritx_dse.core.build_manifest import (
        BuildManifestError, load_and_verify_manifest, manifest_path_for,
    )
    effective_manifest = Path(manifest_path) if manifest_path is not None \
        else manifest_path_for(path)
    try:
        manifest = load_and_verify_manifest(
            path, path=effective_manifest,
            recipe_version=require_manifest_recipe)
    except BuildManifestError as exc:
        raise ProducerError(str(exc)) from exc
    if manifest is not None:
        manifest_sha256 = hashlib.sha256(
            effective_manifest.read_bytes()).hexdigest()
        dirty_digest = None
        if manifest.source_dirty:
            dirty_digest = hashlib.sha256(
                (str(manifest.source_revision) + "\n" + digest)
                .encode()).hexdigest()
        return ProducerIdentity(
            binary_path=str(path), binary_sha256=digest, binary_size=size,
            source_revision=manifest.source_revision,
            dirty=manifest.source_dirty, dirty_digest=dirty_digest,
            manifest_verified=True,
            build_manifest_sha256=manifest_sha256,
            build_recipe_version=manifest.recipe_version)
    revision: str | None = None
    dirty: bool | None = None
    dirty_digest = None
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
        source_revision=revision, dirty=dirty, dirty_digest=dirty_digest,
        manifest_verified=False)


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
    """Reusable evidence requires a manifest-verified, clean producer.

    Ambient git HEAD is not build provenance: without a verified
    build-time manifest the binary cannot be attributed to the source it
    was built from, so it is never pinned.
    """
    if not identity.manifest_verified:
        raise ProducerError(
            "producer has no verified build-time manifest; ambient git "
            "state cannot attribute a binary to a source revision — "
            "reusable evidence is refused (build with a manifest)")
    if identity.source_revision is None:
        raise ProducerError(
            "producer source revision is unknown: a binary digest alone "
            "cannot certify provenance for reusable evidence")
    if identity.dirty:
        raise ProducerError(
            "producer tree is DIRTY; a dirty build may be executed for "
            "diagnosis but cannot receive reusable evidence status")
    if identity.build_manifest_sha256 is None \
            or identity.build_recipe_version is None:
        raise ProducerError(
            "producer does not bind a build manifest identity/recipe; "
            "reusable evidence is refused")


__all__ = [
    "ProducerError", "ProducerIdentity", "assert_pinned_producer",
    "recheck_binary_digest", "resolve_producer_identity",
]
