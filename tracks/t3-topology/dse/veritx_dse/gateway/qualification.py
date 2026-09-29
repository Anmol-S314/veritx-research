"""Canonical qualification registry surfaced to the Studio (C9).

Rationale: docs/decisions/modules/gateway.md
"""
from __future__ import annotations

from typing import Any

from veritx_dse.product.qualification import qualification_view as _view


def qualification_view() -> dict[str, Any]:
    return _view()


__all__ = ["qualification_view"]
