"""Canonical qualification registry surfaced to the Studio (C9).

DEPRECATED SHIM. The single authority is now
``docs/production/ENGINE-QUALIFICATION.json`` loaded by
``veritx_dse.product.qualification``. This module no longer carries a
hand-copied duplicate of the release facts; it delegates so old importers
keep working.
"""
from __future__ import annotations

from typing import Any

from veritx_dse.product.qualification import qualification_view as _view


def qualification_view() -> dict[str, Any]:
    return _view()


__all__ = ["qualification_view"]
