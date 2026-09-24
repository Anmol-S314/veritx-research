"""veritx_dse.core.build_manifest — build-time binary provenance.

Ambient ``git rev-parse HEAD`` at execution time is NOT build provenance:
a binary built at commit A, left untouched while the tree is checked out
at commit B, is attributed to B. A manifest written AT BUILD TIME binds
the source revision and dirty state observed while building to the exact
binary bytes that were produced. Execution then verifies the binary
against the manifest, so the A→B counterexample is detected: the manifest
still says A, or (with no manifest) the producer is not pinned and reusable
evidence is refused.

The manifest is canonical JSON beside the binary:

    <binary>.build-manifest.json
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veritx_dse.core.artifact import canonical_bytes

BUILD_MANIFEST_SCHEMA_VERSION = 1
BUILD_MANIFEST_TYPE = "srota/BuildManifest"
BUILD_MANIFEST_SUFFIX = ".build-manifest.json"

_FIELDS = frozenset({
    "type", "schema_version", "source_revision", "source_dirty",
    "binary_sha256", "binary_size", "compiler", "compiler_version",
    "build_config", "compile_flags", "recipe_version",
})


class BuildManifestError(ValueError):
    """A build manifest is malformed, missing or does not match the binary."""


def manifest_path_for(binary: Path) -> Path:
    return Path(str(binary) + BUILD_MANIFEST_SUFFIX)


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
    import subprocess
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(repo_root), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


@dataclass(frozen=True)
class BuildManifest:
    source_revision: str | None
    source_dirty: bool
    binary_sha256: str
    binary_size: int
    compiler: str
    compiler_version: str
    build_config: str
    compile_flags: tuple[str, ...]
    recipe_version: str
    schema_version: int = BUILD_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != BUILD_MANIFEST_SCHEMA_VERSION:
            raise BuildManifestError(
                f"unsupported build manifest schema_version "
                f"{self.schema_version!r}")
        if self.source_revision is not None \
                and (not isinstance(self.source_revision, str)
                     or not self.source_revision):
            raise BuildManifestError("source_revision must be a string or null")
        if not isinstance(self.source_dirty, bool):
            raise BuildManifestError("source_dirty must be a bool")
        if not isinstance(self.binary_sha256, str) or len(self.binary_sha256) != 64 \
                or any(c not in "0123456789abcdef"
                       for c in self.binary_sha256):
            raise BuildManifestError("binary_sha256 must be a 64-char hex digest")
        if type(self.binary_size) is not int or self.binary_size <= 0:
            raise BuildManifestError("binary_size must be a positive int")
        for name in ("compiler", "compiler_version", "build_config",
                     "recipe_version"):
            if not isinstance(getattr(self, name), str):
                raise BuildManifestError(f"{name} must be a string")
        if not isinstance(self.compile_flags, tuple) \
                or not all(isinstance(f, str) for f in self.compile_flags):
            raise BuildManifestError("compile_flags must be a tuple of strings")
        if not self.recipe_version:
            raise BuildManifestError("recipe_version must be non-empty")

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": BUILD_MANIFEST_TYPE,
            "schema_version": self.schema_version,
            "source_revision": self.source_revision,
            "source_dirty": self.source_dirty,
            "binary_sha256": self.binary_sha256,
            "binary_size": self.binary_size,
            "compiler": self.compiler,
            "compiler_version": self.compiler_version,
            "build_config": self.build_config,
            "compile_flags": list(self.compile_flags),
            "recipe_version": self.recipe_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.identity_dict()

    @classmethod
    def from_dict(cls, d: Any) -> "BuildManifest":
        if not isinstance(d, dict):
            raise BuildManifestError("build manifest must be an object")
        unknown = set(d) - _FIELDS
        if unknown:
            raise BuildManifestError(
                f"build manifest has unknown fields {sorted(unknown)}")
        missing = _FIELDS - set(d)
        if missing:
            raise BuildManifestError(
                f"build manifest is missing fields {sorted(missing)}")
        if d["type"] != BUILD_MANIFEST_TYPE:
            raise BuildManifestError(
                f"build manifest type {d['type']!r} is not {BUILD_MANIFEST_TYPE!r}")
        return cls(
            source_revision=d["source_revision"],
            source_dirty=d["source_dirty"],
            binary_sha256=d["binary_sha256"],
            binary_size=d["binary_size"],
            compiler=d["compiler"],
            compiler_version=d["compiler_version"],
            build_config=d["build_config"],
            compile_flags=tuple(d["compile_flags"]),
            recipe_version=d["recipe_version"],
            schema_version=d["schema_version"])


def write_build_manifest(
        binary: Path, *,
        repo_root: Path | None = None,
        recipe_version: str,
        compiler: str = "",
        compiler_version: str = "",
        build_config: str = "",
        compile_flags: tuple[str, ...] = (),
        out: Path | None = None) -> Path:
    """Write the build-time manifest for ``binary`` (atomic)."""
    path = Path(binary)
    if not path.is_file():
        raise BuildManifestError(f"binary not found: {path}")
    digest, size = _sha256_file(path)
    revision: str | None = None
    dirty = False
    if repo_root is not None:
        root = Path(repo_root)
        revision = _git(root, "rev-parse", "HEAD")
        status = _git(root, "status", "--porcelain")
        dirty = bool(status) if status is not None else True
    manifest = BuildManifest(
        source_revision=revision, source_dirty=dirty,
        binary_sha256=digest, binary_size=size, compiler=compiler,
        compiler_version=compiler_version, build_config=build_config,
        compile_flags=tuple(compile_flags), recipe_version=recipe_version)
    target = Path(out) if out is not None else manifest_path_for(path)
    from veritx_dse.core.recovery import atomic_write
    with atomic_write(target) as tmp:
        tmp.write_bytes(canonical_bytes(manifest.to_dict()))
    return target


def verify_build_manifest(binary: Path, manifest: BuildManifest, *,
                          recipe_version: str | None = None) -> None:
    """Prove the binary bytes are exactly what the manifest was built from."""
    path = Path(binary)
    if not path.is_file():
        raise BuildManifestError(f"binary not found: {path}")
    digest, size = _sha256_file(path)
    if digest != manifest.binary_sha256 or size != manifest.binary_size:
        raise BuildManifestError(
            f"binary {path} does not match its build manifest "
            f"({manifest.binary_sha256}/{manifest.binary_size} -> "
            f"{digest}/{size}); the binary was rebuilt or replaced after the "
            "manifest was written")
    if recipe_version is not None and recipe_version != manifest.recipe_version:
        raise BuildManifestError(
            f"build manifest recipe_version {manifest.recipe_version!r} is "
            f"not the expected {recipe_version!r}")


def load_and_verify_manifest(binary: Path, *,
                             path: Path | None = None,
                             recipe_version: str | None = None
                             ) -> BuildManifest | None:
    """Load the adjacent manifest and verify it, or return None if absent."""
    manifest_path = Path(path) if path is not None \
        else manifest_path_for(Path(binary))
    if not manifest_path.is_file():
        return None
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BuildManifestError(
            f"build manifest {manifest_path} is unreadable: {exc}") from exc
    manifest = BuildManifest.from_dict(raw)
    verify_build_manifest(Path(binary), manifest,
                          recipe_version=recipe_version)
    return manifest


__all__ = [
    "BUILD_MANIFEST_SCHEMA_VERSION", "BUILD_MANIFEST_SUFFIX",
    "BUILD_MANIFEST_TYPE", "BuildManifest", "BuildManifestError",
    "load_and_verify_manifest", "manifest_path_for", "verify_build_manifest",
    "write_build_manifest",
]
