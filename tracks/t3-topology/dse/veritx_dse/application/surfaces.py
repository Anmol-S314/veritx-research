"""veritx_dse.application.surfaces — one intent from every surface.

Python, CLI, API and T3 construct the SAME canonical intent document and
parse it through the SAME ``parse_intent``. Transport metadata (flag
order, JSON key order, routes, directories, labels) never enters
semantic identity — proven by cross-surface equivalence tests.
"""
from __future__ import annotations

from typing import Any

from .requests import Intent, resolve_intent


def python_intent(doc: Any) -> Intent:
    """Internal Python entry point (documented research script path)."""
    resolved, _, _ = resolve_intent(doc)
    return resolved


def api_intent(doc: Any) -> Intent:
    """API adapter entry (decode request -> Intent, no backend logic)."""
    resolved, _, _ = resolve_intent(doc)
    return resolved


def t3_intent(doc: Any) -> Intent:
    """T3 adapter entry (T3 forwards intent documents, not semantics)."""
    resolved, _, _ = resolve_intent(doc)
    return resolved


def cli_intent(*, request_file: str | None = None,
               document: Any | None = None) -> Intent:
    """CLI adapter entry (file or inline document -> Intent)."""
    import json
    from pathlib import Path
    if (request_file is None) == (document is None):
        from .errors import intent_error
        raise intent_error(
            "cli: pass exactly one of --request or an inline document",
            operation="cli")
    if request_file is not None:
        try:
            doc = json.loads(Path(request_file).read_text())
        except (OSError, ValueError) as exc:
            from .errors import intent_error
            raise intent_error(
                f"cli: cannot read request file {request_file}: {exc}",
                operation="cli",
                cause_type=type(exc).__name__) from exc
    else:
        doc = document
    resolved, _, _ = resolve_intent(doc)
    return resolved


__all__ = ["api_intent", "cli_intent", "python_intent", "t3_intent"]
