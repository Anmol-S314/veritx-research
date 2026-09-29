"""generation — which design-request generation an object is.

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

from typing import Any

#: The generations the shared derivation engine can consume.
GENERATIONS: tuple[str, ...] = ("v2", "v3", "v4")


def is_v4_request(obj: Any) -> bool:
    """True for a CompileRequestV4, by shape."""
    return (getattr(obj, "schema_version", None) == 4
            and hasattr(obj, "noc_controls")
            and hasattr(obj, "topology"))


def is_v3_request(obj: Any) -> bool:
    from veritx_dse.model.compile_model import CompileRequestV3
    return isinstance(obj, CompileRequestV3)


def is_v2_request(obj: Any) -> bool:
    from veritx_dse.model.compile_model import CompileRequest
    return isinstance(obj, CompileRequest) and not is_v3_request(obj)


def is_any_compile_request(obj: Any) -> bool:
    """True when the shared engine can consume `obj` as a design request."""
    return is_v4_request(obj) or is_v3_request(obj) or is_v2_request(obj)


def generation_of(obj: Any) -> str:
    if is_v4_request(obj):
        return "v4"
    if is_v3_request(obj):
        return "v3"
    if is_v2_request(obj):
        return "v2"
    raise TypeError(f"{type(obj).__name__} is not a design request")


__all__ = ["GENERATIONS", "is_v2_request", "is_v3_request", "is_v4_request",
           "is_any_compile_request", "generation_of"]
