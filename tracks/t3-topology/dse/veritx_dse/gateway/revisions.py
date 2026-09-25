"""veritx_dse.gateway.revisions — immutable design-revision continuity.

The Studio must not resubmit raw engine JSON between stages. A compile
produces an immutable *revision*; later stages (evaluate, optimize) name the
revision and the gateway re-derives the canonical request from the stored
intent. The revision id is a content hash of the intent plus the compiled
identities, so editing a design produces a new revision and an old Run can
never be shown as the current revision.

Only the *intent* (preset/policy/overrides/name) and the compiled identities
are persisted; the canonical request and views are re-derived on read. A
compiler change that alters the identities is detected and refused rather
than silently reinterpreted.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veritx_dse.core.artifact import content_hash
from veritx_dse.gateway.errors import Conflict, NotFound

REVISION_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Revision:
    revision_id: str
    intent: dict[str, Any]
    design_hash: str
    resolved_fabric_hash: str
    schema_version: int = REVISION_SCHEMA_VERSION

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/DesignRevision",
            "schema_version": self.schema_version,
            "intent": self.intent,
            "design_hash": self.design_hash,
            "resolved_fabric_hash": self.resolved_fabric_hash,
        }


def revision_id_for(*, intent: dict[str, Any], design_hash: str,
                    resolved_fabric_hash: str) -> str:
    return content_hash("srota/DesignRevision", REVISION_SCHEMA_VERSION, {
        "intent": intent,
        "design_hash": design_hash,
        "resolved_fabric_hash": resolved_fabric_hash,
    })


class RevisionStore:
    """A content-addressed store of immutable design revisions."""

    def __init__(self, root: Path):
        self._root = Path(root)

    def _path(self, revision_id: str) -> Path:
        if not revision_id or "/" in revision_id or "\\" in revision_id \
                or revision_id in (".", ".."):
            raise Conflict(f"invalid revision id {revision_id!r}")
        return self._root / f"{revision_id}.json"

    def put(self, revision: Revision) -> Revision:
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._path(revision.revision_id)
        payload = json.dumps(revision.identity_dict(), indent=2,
                             sort_keys=True) + "\n"
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(payload)
        tmp.replace(path)
        return revision

    def get(self, revision_id: str) -> Revision:
        path = self._path(revision_id)
        if not path.is_file():
            raise NotFound(f"no such revision: {revision_id}")
        doc = json.loads(path.read_text())
        return Revision(
            revision_id=revision_id, intent=doc["intent"],
            design_hash=doc["design_hash"],
            resolved_fabric_hash=doc["resolved_fabric_hash"],
            schema_version=doc.get("schema_version", REVISION_SCHEMA_VERSION))

    def list_ids(self) -> list[str]:
        if not self._root.is_dir():
            return []
        return sorted(p.stem for p in self._root.glob("*.json"))


__all__ = ["Revision", "RevisionStore", "revision_id_for",
           "REVISION_SCHEMA_VERSION"]
