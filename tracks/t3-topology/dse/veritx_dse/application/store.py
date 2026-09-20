"""veritx_dse.application.store — local deterministic resource store.

The smallest practical persistence: content-identified JSON files under
one root, atomic writes, no mutation. ``<root>/<kind>/<id>.json``.
Identical content rewrites idempotently; different content under an
existing content-derived id refuses (CONFLICT). No database, no server.

Wording discipline: this store is write-once through its API. It is
NOT tamper-evident on read — scientific consumers must use verified
loaders (result validation, ``read_verified_evidence``), never raw
``store.get()``. Raw ``get()`` is inspection/internal storage access.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .errors import ControlPlaneError, ErrorCode

RESOURCE_KINDS = ("intent", "design", "workload", "plan", "experiment",
                  "attempt", "result", "comparison", "links", "study")


class ResourceStore:
    """Filesystem resource store (locations, never identities)."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, kind: str, resource_id: str) -> Path:
        if kind not in RESOURCE_KINDS:
            raise ControlPlaneError(
                ErrorCode.INTERNAL_ERROR,
                f"unknown resource kind {kind!r}", operation="store")
        if not resource_id or "/" in resource_id or resource_id in (
                ".", ".."):
            raise ControlPlaneError(
                ErrorCode.INTERNAL_ERROR,
                f"invalid resource id {resource_id!r}", operation="store")
        return self.root / kind / f"{resource_id}.json"

    def put(self, kind: str, resource_id: str,
            payload: dict[str, Any]) -> Path:
        """Persist once. Same bytes: idempotent. Different bytes: CONFLICT."""
        from veritx_dse.core.recovery import atomic_write
        from veritx_dse.core.spec import canonical_json
        path = self._path(kind, resource_id)
        try:
            body = canonical_json(payload)
        except (TypeError, ValueError) as exc:
            raise ControlPlaneError(
                ErrorCode.INTERNAL_ERROR,
                f"resource {kind}/{resource_id} is not canonical-JSON "
                f"serializable: {exc}",
                operation="store", resource_id=resource_id) from exc
        digest = hashlib.sha256(body.encode()).hexdigest()
        if path.is_file():
            existing = path.read_bytes()
            if hashlib.sha256(existing).hexdigest() != digest:
                raise ControlPlaneError(
                    ErrorCode.CONFLICT,
                    f"{kind}/{resource_id} already persists different "
                    f"content; resources are immutable",
                    operation="store", resource_id=resource_id)
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        with atomic_write(path) as tmp:
            tmp.write_text(body)
        return path

    def get(self, kind: str, resource_id: str) -> dict[str, Any]:
        path = self._path(kind, resource_id)
        if not path.is_file():
            raise ControlPlaneError(
                ErrorCode.NOT_FOUND,
                f"unknown {kind} resource {resource_id!r}",
                operation="inspect", resource_id=resource_id)
        try:
            data = json.loads(path.read_text())
        except ValueError as exc:
            raise ControlPlaneError(
                ErrorCode.INTERNAL_ERROR,
                f"stored {kind}/{resource_id} is corrupt: {exc}",
                operation="inspect", resource_id=resource_id) from exc
        if not isinstance(data, dict):
            raise ControlPlaneError(
                ErrorCode.INTERNAL_ERROR,
                f"stored {kind}/{resource_id} must be an object",
                operation="inspect", resource_id=resource_id)
        return data

    def exists(self, kind: str, resource_id: str) -> bool:
        return self._path(kind, resource_id).is_file()


__all__ = ["RESOURCE_KINDS", "ResourceStore"]
