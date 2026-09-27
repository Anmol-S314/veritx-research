"""generation — which design-request generation an object is.

WHY THIS EXISTS
===============

The compiler has ONE derivation engine that serves every generation of design
request. Gates that used to ask `isinstance(design, CompileRequest)` or
`isinstance(design, (CompileRequest, CompileRequestV3))` therefore had to grow
a third disjunct every time a generation was added, and a missed one showed up
as a confusing downstream AttributeError rather than a clear refusal.

This module answers the question ONCE:

    v2  CompileRequest        schema 2, compiler semantics 1/2
    v3  CompileRequestV3      schema 3, compiler semantics 3
    v4  CompileRequestV4      schema 4, compiler semantics 4

The check is by SHAPE for v4 (schema_version + the v4-only `noc_controls`)
because importing `CompileRequestV4` into every consumer would create import
cycles for no benefit. The v2/v3 checks stay isinstance checks against the
frozen classes.

THIS IS NOT A SEMANTIC BRIDGE. It answers "can the shared engine consume
this?" — never "is this design equivalent to that one?".
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
