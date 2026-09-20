"""veritx_dse.waved.strict — strict parsing rules for persisted artifacts.

Convenience parsing (``from_dict`` defaults) accepts a minimal document:
it exists so tests and in-process code can rebuild an object. A
PERSISTED scientific resource is a different contract. Loading one must
prove:

    exact type tag
    exact supported schema_version
    embedded resource ID present
    requested/file ID == embedded ID
    recomputed ID == embedded ID
    unknown fields refused
    all required parent IDs present and equal to the verified parents

``strict=True`` on the artifact parsers turns those rules on; the
verified loaders in ``veritx_dse.application.waved_resources`` are the
only callers that matter, and they are the only scientific trust path.
"""
from __future__ import annotations

from typing import Any, Iterable

from .errors import EvidenceInvalid, InvalidInput


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
    "require_embedded_id", "require_fields", "require_schema_version",
    "require_type_tag",
]
