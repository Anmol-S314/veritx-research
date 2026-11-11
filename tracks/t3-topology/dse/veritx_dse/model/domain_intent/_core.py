"""_core — shared error + schema version.

Split out of veritx_dse.model.domain_intent; the package __init__
re-exports every public name, so importers are unchanged.

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

SCHEMA_VERSION = 1


class DomainIntentError(ValueError, SemanticError):
    """The declared domain/reset/crossing intent is invalid or unsupported."""
