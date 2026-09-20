"""veritx_dse.waved.immutable — transitive immutability for Wave-D artifacts.

A frozen dataclass is only skin deep: a ``dict`` field inside it keeps a
reference to the caller's container, so mutating the caller's dict after
construction silently changes the artifact — and therefore its identity
hash. Wave D forbids that state outright (a "new parent identity with old
child semantics" is the exact failure class Wave B closed).

``freeze`` copies every caller-owned container into an immutable
recursive value tree; ``thaw`` converts it back to plain JSON types at
serialization boundaries. Scalars are validated against the canonical
JSON domain, so a value that cannot be hashed canonically can never
enter an artifact.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Iterator


class ImmutableError(TypeError):
    """A value cannot be represented as an immutable canonical value."""


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


__all__ = ["FrozenMap", "ImmutableError", "freeze", "thaw"]
