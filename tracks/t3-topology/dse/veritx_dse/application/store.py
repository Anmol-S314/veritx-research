"""veritx_dse.application.store — typed durable resource store.

The first durable application persistence boundary: four resource kinds,
content- or identity-addressed, written once, never overwritten with
conflicting content.

    <root>/
        intents/<intent_id>.json            CompileIntentRecord
        designs/<design_hash>.json          CompileRequest (canonical)
        resolved/<resolved_fabric_hash>.json  ResolvedFabric (canonical)
        resolutions/<intent_id>.json        CompileResolution
        .store.lock                         POSIX advisory write lock

A hidden lock file is the only extra artifact. No SQLite, no manifest
index, no aliases, no "latest".

WHAT THIS STORE IS NOT (YET)

It persists the durable COMPILE RESOLUTION ROOT only: the semantic intent
declaration, the exact canonical design, the exact ResolvedFabric, and the
resolution link between them. It deliberately does NOT persist the full
compiled DAG (topology, attachment, route, VC assignment/resource, packet
format, router behavior, address decode, FabricArtifact) and does NOT
persist a ``CompiledFabric`` object (no pickle, JSON only).

Those artifacts remain available from a live Slice-23 compile. A restart
recovers the resolution root, not a directly lowerable backend artifact
set; backend lowering is a later concern and may motivate typed
child-artifact persistence or deterministic reconstruction.

WRITE-ONCE SEMANTICS

Identities are immutable. A missing resource is written atomically; an
existing resource holding the SAME canonical content is an idempotent
success; an existing resource holding DIFFERENT content under the same key
fails closed (never "repaired"). Existing bytes are never overwritten with
conflicting content.

DURABILITY

Writes publish a unique same-directory temporary file with flush + fsync,
``os.replace``, then an fsync of the destination directory. The
check-existing -> publish sequence is serialized across processes by an
``fcntl.flock`` on ``<root>/.store.lock``. Readers are lock-free because
final-file publication is atomic.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veritx_dse.application.compile_intent import CompileIntent
from veritx_dse.application.resources import (
    CompileIntentRecord, CompileResolution, ResourceValidationError,
)
from veritx_dse.model.compile_model import (
    COMPILER_SEMANTICS_VERSION, CompileRequest,
)
from veritx_dse.model.resolved_fabric import ResolvedFabric

_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")

_DIRECTORY_FOR_KIND = {
    "intent": "intents",
    "design": "designs",
    "resolved": "resolved",
    "resolution": "resolutions",
}


class ResourceStoreError(Exception):
    """Expected store-domain failure (not corruption or a missing file)."""


class ResourceNotFoundError(ResourceStoreError):
    """A requested resource does not exist."""


class ResourceConflictError(ResourceStoreError):
    """A resource key already holds different canonical content."""


class ResourceCorruptionError(ResourceStoreError):
    """A stored resource is malformed, mis-keyed, or self-inconsistent."""


@dataclass(frozen=True)
class StoredCompileResolution:
    """Transport bundle for a fully validated committed resolution.

    Carries no independent hash; every member is validated before the
    bundle is returned.
    """

    intent_record: CompileIntentRecord
    design: CompileRequest
    resolved_fabric: ResolvedFabric
    resolution: CompileResolution


def _reject_constant(token: str) -> Any:
    # json.loads would otherwise accept NaN/Infinity, which are not JSON.
    raise ValueError(f"non-JSON numeric constant {token!r} is not allowed")


def _canonical_bytes(document: Any) -> bytes:
    """Deterministic, transport-independent JSON bytes: one trailing newline."""
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8") + b"\n"


def _flush_and_sync(handle: Any) -> None:
    handle.flush()
    os.fsync(handle.fileno())


def _sync_directory(directory: Path) -> None:
    fd = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class ResourceStore:
    """Typed, write-once, verified resource store rooted at an explicit path."""

    def __init__(self, root: str | os.PathLike[str]):
        if root is None:
            raise ResourceStoreError(
                "ResourceStore root is required; there is no implicit "
                "default, environment variable, or repository-relative "
                "store location")
        self._root = Path(root)
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            for directory in _DIRECTORY_FOR_KIND.values():
                (self._root / directory).mkdir(exist_ok=True)
        except OSError as exc:
            raise ResourceStoreError(
                f"could not create store root {self._root}: {exc}") from exc
        self._lock_path = self._root / ".store.lock"
        try:
            self._lock_path.touch(exist_ok=True)
        except OSError as exc:
            raise ResourceStoreError(
                f"could not create store lock {self._lock_path}: {exc}",
            ) from exc
        try:
            _sync_directory(self._root)
        except OSError:
            # Durability best-effort at construction; not a semantic fact.
            pass

    # -- public typed API -------------------------------------------------

    def put_intent(self, intent: CompileIntent) -> CompileIntentRecord:
        record = CompileIntentRecord.from_intent(intent)
        self._put_resource("intent", record.intent_id, record.to_dict())
        return record

    def load_intent_record(self, intent_id: str) -> CompileIntentRecord:
        return self._load_resource("intent", intent_id,
                                   self._parse_intent_record)

    def put_design(self, design: CompileRequest) -> None:
        self._require_current_design(design)
        self._put_resource("design", design.design_hash(), design.to_dict())

    def load_design(self, design_hash: str) -> CompileRequest:
        return self._load_resource("design", design_hash, self._parse_design)

    def put_resolved(self, resolved: ResolvedFabric) -> None:
        if not isinstance(resolved, ResolvedFabric):
            raise ResourceStoreError(
                f"resolved must be a ResolvedFabric, got "
                f"{type(resolved).__name__}")
        self._put_resource("resolved", resolved.resolved_fabric_hash,
                           resolved.to_dict())

    def load_resolved(self, resolved_fabric_hash: str) -> ResolvedFabric:
        return self._load_resource("resolved", resolved_fabric_hash,
                                   self._parse_resolved)

    def put_resolution(self, resolution: CompileResolution) -> None:
        if not isinstance(resolution, CompileResolution):
            raise ResourceStoreError(
                f"resolution must be a CompileResolution, got "
                f"{type(resolution).__name__}")
        self._put_resource("resolution", resolution.intent_id,
                           resolution.to_dict())

    def load_resolution(self, intent_id: str) -> CompileResolution:
        return self._load_resource("resolution", intent_id,
                                   self._parse_resolution)

    def commit_resolution(self, *, intent: CompileIntent,
                          design: CompileRequest,
                          resolved_fabric: ResolvedFabric
                          ) -> CompileResolution:
        """Persist intent -> design -> resolved -> resolution (commit marker).

        The resolution write is LAST. A failure before it may leave orphan
        content-addressed resources but no committed resolution; retrying is
        idempotent.
        """
        from veritx_dse.application.resources import make_compile_resolution
        resolution = make_compile_resolution(
            intent=intent, design=design, resolved_fabric=resolved_fabric)
        self.put_intent(intent)
        self.put_design(design)
        self.put_resolved(resolved_fabric)
        self.put_resolution(resolution)
        return resolution

    def load_committed(self, intent_id: str) -> StoredCompileResolution:
        """Load and fully validate a committed resolution and its parents."""
        resolution = self.load_resolution(intent_id)
        intent_record = self.load_intent_record(intent_id)
        design = self.load_design(resolution.design_hash)
        resolved_fabric = self.load_resolved(resolution.resolved_fabric_hash)
        try:
            resolution.validate_against(intent_record, design, resolved_fabric)
        except ResourceValidationError as exc:
            raise ResourceCorruptionError(
                f"committed resolution {intent_id} is inconsistent: {exc}",
            ) from exc
        return StoredCompileResolution(
            intent_record=intent_record, design=design,
            resolved_fabric=resolved_fabric, resolution=resolution)

    # -- key / path helpers ----------------------------------------------

    @staticmethod
    def _require_key(key: Any) -> str:
        if not isinstance(key, str) or not _HEX64.match(key):
            raise ResourceStoreError(
                f"resource key must be a canonical 64-character lowercase "
                f"hex id, got {key!r}")
        return key

    def _path(self, kind: str, key: str) -> Path:
        return self._root / _DIRECTORY_FOR_KIND[kind] / f"{key}.json"

    def _require_current_design(self, design: Any) -> None:
        if not isinstance(design, CompileRequest):
            raise ResourceStoreError(
                f"design must be a CompileRequest, got "
                f"{type(design).__name__}")
        if design.compiler_semantics_version != COMPILER_SEMANTICS_VERSION:
            raise ResourceStoreError(
                "this store persists current compiler semantics only "
                f"(v{COMPILER_SEMANTICS_VERSION}); got "
                f"compiler_semantics_version="
                f"{design.compiler_semantics_version!r}. Load the legacy "
                "document and run migrate_design() explicitly, then store "
                "the migrated design. The store never auto-migrates.")

    # -- write path -------------------------------------------------------

    @contextmanager
    def _write_lock(self) -> Iterator[None]:
        fd = os.open(str(self._lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _atomic_write(self, path: Path, document: Any) -> None:
        data = _canonical_bytes(document)
        directory = path.parent
        tmp_path: str | None = None
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(directory), prefix=f".{path.name}.", suffix=".tmp")
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                _flush_and_sync(handle)
            os.replace(tmp_path, str(path))
            tmp_path = None
            _sync_directory(directory)
        except OSError as exc:
            raise ResourceStoreError(
                f"could not publish resource {path}: {exc}") from exc
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _put_resource(self, kind: str, key: str, document: dict[str, Any]
                      ) -> None:
        self._require_key(key)
        path = self._path(kind, key)
        payload = _canonical_bytes(document)
        parse = _PARSERS[kind]
        with self._write_lock():
            if path.is_symlink():
                raise ResourceCorruptionError(
                    f"refusing to write through symlink {path}")
            if path.exists():
                existing = self._read_document(path, key)
                try:
                    parsed = parse(existing, key)
                except ResourceStoreError:
                    raise
                except Exception as exc:
                    raise ResourceCorruptionError(
                        f"existing resource {path} is not a valid "
                        f"{kind}: {exc}") from exc
                if _canonical_bytes(parsed.to_dict()) == payload:
                    return  # idempotent
                raise ResourceConflictError(
                    f"resource {path} already holds different canonical "
                    "content for the same key; refusing to overwrite")
            self._atomic_write(path, document)

    # -- read path --------------------------------------------------------

    def _read_document(self, path: Path, key: str) -> dict[str, Any]:
        self._require_key(key)
        if path.is_symlink():
            raise ResourceCorruptionError(
                f"refusing to read resource through symlink {path}")
        try:
            raw = path.read_bytes()
        except FileNotFoundError as exc:
            raise ResourceNotFoundError(
                f"resource not found: {path}") from exc
        except OSError as exc:
            raise ResourceStoreError(
                f"could not read resource {path}: {exc}") from exc
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ResourceCorruptionError(
                f"resource {path} is not valid UTF-8") from exc
        try:
            document = json.loads(text, parse_constant=_reject_constant)
        except ValueError as exc:
            raise ResourceCorruptionError(
                f"resource {path} is not valid JSON: {exc}") from exc
        if not isinstance(document, dict):
            raise ResourceCorruptionError(
                f"resource {path} must be a JSON object")
        return document

    def _load_resource(self, kind: str, key: str,
                       parse: Callable[[dict[str, Any], str], Any]) -> Any:
        self._require_key(key)
        path = self._path(kind, key)
        document = self._read_document(path, key)
        try:
            return parse(document, key)
        except ResourceStoreError:
            raise
        except Exception as exc:
            raise ResourceCorruptionError(
                f"resource {path} is not a valid {kind}: {exc}") from exc

    # -- typed parsers (identity must match the filename key) -------------

    @staticmethod
    def _parse_intent_record(document: dict[str, Any], key: str
                             ) -> CompileIntentRecord:
        record = CompileIntentRecord.from_dict(document)
        if record.intent_id != key:
            raise ResourceCorruptionError(
                f"intent record identity {record.intent_id} does not match "
                f"its key {key}")
        return record

    @staticmethod
    def _parse_design(document: dict[str, Any], key: str) -> CompileRequest:
        design = CompileRequest.from_dict(document)
        if design.compiler_semantics_version != COMPILER_SEMANTICS_VERSION:
            raise ResourceStoreError(
                "stored design is not current-semantics "
                f"(v{design.compiler_semantics_version}); this store holds "
                "current canonical resources, not migration inputs")
        if design.design_hash() != key:
            raise ResourceCorruptionError(
                f"stored design identity {design.design_hash()} does not "
                f"match its key {key}")
        return design

    @staticmethod
    def _parse_resolved(document: dict[str, Any], key: str
                        ) -> ResolvedFabric:
        resolved = ResolvedFabric.from_dict(document)
        if resolved.resolved_fabric_hash != key:
            raise ResourceCorruptionError(
                "stored resolved fabric identity "
                f"{resolved.resolved_fabric_hash} does not match its key "
                f"{key}")
        return resolved

    @staticmethod
    def _parse_resolution(document: dict[str, Any], key: str
                          ) -> CompileResolution:
        resolution = CompileResolution.from_dict(document)
        if resolution.intent_id != key:
            raise ResourceCorruptionError(
                f"stored resolution identity {resolution.intent_id} does "
                f"not match its key {key}")
        return resolution


_PARSERS: dict[str, Callable[[dict[str, Any], str], Any]] = {
    "intent": ResourceStore._parse_intent_record,
    "design": ResourceStore._parse_design,
    "resolved": ResourceStore._parse_resolved,
    "resolution": ResourceStore._parse_resolution,
}
