"""topology_intent_base — the topology-intent base class and its error.

Why this is a separate module: ``SrotaIntent`` lives in its own file and
subclasses ``TopologyIntent``, while ``topology_intent`` registers SROTA in
its kind table. If the base class lived in ``topology_intent``, importing
either module first would import the other mid-initialization and fail.

Keeping the base here breaks that cycle at its source instead of hiding it
behind a deferred import: both modules depend on this one, and neither
depends on the other's initialization order.

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, ClassVar

from veritx_dse.core.errors import SemanticError

class TopologyIntentError(ValueError, SemanticError):
    """The declared topology intent cannot represent a physical structure."""

def _as_int(name: str, value: Any, *, minimum: int) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise TopologyIntentError(f"{name} must be an int, got {value!r}")
    if value < minimum:
        raise TopologyIntentError(
            f"{name} must be >= {minimum}, got {value}")
    return value

class TopologyIntent:
    """Base class. Subclasses declare ``kind`` and their own parameters."""

    kind: ClassVar[str] = ""

    def parameters(self) -> dict[str, Any]:      # pragma: no cover - abstract
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        """LOSSLESS persistence form."""
        return {"kind": self.kind, **self.parameters()}

    def scientific_dict(self) -> dict[str, Any]:
        """IDENTITY projection. Defaults to the lossless form; a variant
        overrides this only to strip something that is not design science
        (e.g. an explicit graph's presentation name)."""
        return self.to_dict()

    def intent_id(self) -> str:
        """Content identity of the DECLARED INTENT (not of the artifact).

        Built from the SCIENTIFIC projection, so an explicit graph's
        presentation name cannot change which design science this is.
        """
        body = json.dumps(self.scientific_dict(), sort_keys=True,
                          separators=(",", ":")).encode()
        return "sha256:" + hashlib.sha256(
            b"veritx/topology-intent/v1\0" + body).hexdigest()

__all__ = ["TopologyIntent", "TopologyIntentError", "_as_int"]
