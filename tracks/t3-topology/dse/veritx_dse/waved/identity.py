"""veritx_dse.waved.identity — canonical hashing helpers.

One hashing convention for every Wave-D artifact:

    <type-tag>/v<schema_version> \0 canonical_json(payload)

Domain separation by type tag prevents cross-artifact hash confusion.
Canonical JSON (sorted keys, no whitespace, UTF-8) is provided by
``veritx_dse.core.spec.canonical_json`` — the same convention the frozen
Wave-B artifacts use.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_bytes(payload: Any) -> bytes:
    """Deterministic UTF-8 JSON bytes for ``payload``."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def content_hash(type_tag: str, schema_version: int, payload: Any) -> str:
    """Domain-separated SHA-256 over the canonical payload."""
    body = (f"{type_tag}/v{schema_version}\0").encode("utf-8") \
        + canonical_bytes(payload)
    return "sha256:" + hashlib.sha256(body).hexdigest()


__all__ = ["canonical_bytes", "content_hash"]
