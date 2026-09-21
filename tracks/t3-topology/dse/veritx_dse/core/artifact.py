"""veritx_dse.core.artifact — the ONE artifact primitive.

Everything content-addressed in this repository uses exactly one
implementation of four rules:

    canonical serialization   sorted keys, tight separators, UTF-8, ASCII
    content identity          domain-separated SHA-256
    immutability              a frozen value tree with no caller aliasing
    strict parsing            closed shapes for PERSISTED artifacts

These rules were previously implemented three times
(``waved/identity.py``, ``waved/immutable.py``, ``waved/strict.py``) plus a
second content-id convention inside ``wavee/result.py``. The duplicates were
behaviourally identical for plain JSON and subtly different for frozen
containers — worse than merely redundant, because a hash that depends on the
representation used to carry a value can be changed by changing the carrier.

Both hash conventions survive verbatim, because artifact identities are
sealed and may not move:

    content_id(domain, payload)          -> bare hex digest
    content_hash(tag, version, payload)  -> "sha256:" + id over "tag/vN\\0"

``tests/test_artifact_primitives.py`` pins canonical bytes and real artifact
identities to values captured before this merge.

Relationship to the two other immutability helpers (both deliberately NOT
merged here): ``core.route_artifact.py::_freeze`` encodes objects as sorted
tuple-of-pairs and ``backend.contracts._freeze_json`` uses a path-aware
frozen map whose error messages carry a field path. Both are sealed Wave-B
code, both feed content hashes, and both enforce different validation
policies. Merging them would move sealed hashes for a naming preference;
that is a Wave-B decision, not an artifact-primitive one.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any, Iterable, Iterator

from veritx_dse.core.errors import VeritXError


# ── errors ───────────────────────────────────────────────────────────────
class ArtifactError(VeritXError):
    """Base class for artifact-contract failures (fail closed)."""

    code = "ARTIFACT_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidInput(ArtifactError):
    """Malformed input: bad types, out-of-range values, missing fields.

    Formerly ``waved.errors.InvalidInput``. The Wave-D modules re-export
    this exact class, so ``raise``/``except`` sites are unchanged.
    """

    code = "INVALID_INPUT"


class EvidenceInvalid(ArtifactError):
    """Persisted artifact identity failed verification.

    Formerly ``waved.errors.EvidenceInvalid``; re-exported there.
    """

    code = "EVIDENCE_INVALID"


class ImmutableError(TypeError):
    """A value cannot be represented as an immutable canonical value."""


# ── canonical serialization ──────────────────────────────────────────────
def canonical_bytes(payload: Any) -> bytes:
    """Deterministic UTF-8 JSON bytes for ``payload``.

    Frozen containers (``FrozenMap``/tuples) are thawed to their plain JSON
    form first, so the canonical bytes of an artifact never depend on the
    representation used to carry it.
    """
    return json.dumps(thaw(payload), sort_keys=True,
                      separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def content_id(domain: str, payload: Any) -> str:
    """Domain-separated SHA-256 over the canonical payload (bare digest).

    ``domain`` is the full domain-separation string; callers that version
    their artifacts pass ``f"{type_tag}/v{schema_version}"``. Domain
    separation prevents cross-artifact hash confusion.
    """
    body = (domain + "\0").encode("utf-8") + canonical_bytes(payload)
    return hashlib.sha256(body).hexdigest()


def content_hash(type_tag: str, schema_version: int, payload: Any) -> str:
    """Versioned content identity, prefixed for self-description."""
    return "sha256:" + content_id(f"{type_tag}/v{schema_version}", payload)


# ── immutability ─────────────────────────────────────────────────────────
class FrozenMap(Mapping):
    """An immutable, hashable, canonically ordered mapping.

    Items are sorted by key at construction so iteration, equality and
    hashing are order-independent; nested containers are frozen too.
    Any mutation attempt raises (no ``__setitem__`` exists at all).
    """

    __slots__ = ("_items", "_hash")

    def __init__(self, items: Any = ()):
        if isinstance(items, Mapping):
            pairs = list(items.items())
        else:
            pairs = list(items)
        frozen: list[tuple[str, Any]] = []
        for key, value in pairs:
            if not isinstance(key, str):
                raise ImmutableError(
                    f"mapping keys must be strings, got {key!r}")
            frozen.append((key, freeze(value)))
        frozen.sort(key=lambda kv: kv[0])
        self._items = tuple(frozen)
        self._hash: int | None = None

    def __getitem__(self, key: str) -> Any:
        for k, v in self._items:
            if k == key:
                return v
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (k for k, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, FrozenMap):
            return self._items == other._items
        if isinstance(other, Mapping):
            return dict(self._items) == {k: freeze(v)
                                         for k, v in other.items()}
        return NotImplemented

    def __hash__(self) -> int:
        if self._hash is None:
            self._hash = hash(self._items)
        return self._hash

    def __repr__(self) -> str:
        return f"FrozenMap({dict(self._items)!r})"

    def __reduce__(self):
        # Pickle as a plain dict; construction re-freezes.
        return (FrozenMap, (dict(self._items),))


def freeze(value: Any) -> Any:
    """Deep-copy ``value`` into an immutable canonical representation."""
    if isinstance(value, FrozenMap):
        return value
    if isinstance(value, Mapping):
        return FrozenMap(value)
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    if isinstance(value, (str, bool, int)) or value is None:
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ImmutableError(
                f"non-finite float {value!r} is outside the canonical "
                "JSON domain")
        return value
    raise ImmutableError(
        f"{type(value).__name__} is not a canonical immutable value")


def thaw(value: Any) -> Any:
    """Convert a frozen value tree back to plain JSON types."""
    if isinstance(value, FrozenMap):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [thaw(v) for v in value]
    if isinstance(value, Mapping):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw(v) for v in value]
    return value


# ── strict parsing (persisted artifacts only) ────────────────────────────
def require_fields(d: Any, allowed: Iterable[str], where: str) -> None:
    """Refuse unknown fields (a persisted document has a closed shape)."""
    if not isinstance(d, dict):
        raise InvalidInput(f"{where} must be an object")
    unknown = set(d) - set(allowed)
    if unknown:
        raise InvalidInput(
            f"{where} has unknown fields: {sorted(unknown)}")


def require_type_tag(d: dict[str, Any], tag: str, where: str) -> None:
    if d.get("type") != tag:
        raise InvalidInput(
            f"{where} type tag {d.get('type')!r} is not {tag!r}")


def require_schema_version(d: dict[str, Any], expected: int,
                           where: str) -> None:
    if d.get("schema_version") != expected:
        raise InvalidInput(
            f"{where} schema_version {d.get('schema_version')!r} is not "
            f"the supported v{expected}")


def require_embedded_id(d: dict[str, Any], field: str,
                        recomputed: str, where: str) -> None:
    """The embedded ID must be PRESENT and equal the recomputed ID."""
    embedded = d.get(field)
    if not isinstance(embedded, str) or not embedded:
        raise EvidenceInvalid(
            f"{where} has no embedded {field}: refusing unauthenticated "
            "persisted content")
    if embedded != recomputed:
        raise EvidenceInvalid(
            f"{where} embeds {field} {embedded} but recomputes to "
            f"{recomputed}: content forged")


__all__ = [
    "ArtifactError",
    "EvidenceInvalid",
    "FrozenMap",
    "ImmutableError",
    "InvalidInput",
    "canonical_bytes",
    "content_hash",
    "content_id",
    "freeze",
    "require_embedded_id",
    "require_fields",
    "require_schema_version",
    "require_type_tag",
    "thaw",
]
