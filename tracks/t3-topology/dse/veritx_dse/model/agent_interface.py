"""Canonical protocol-neutral agent-interface vocabulary.

Rationale: docs/decisions/modules/model.md
"""
from enum import Enum


class InterfaceRole(Enum):
    """Declared role of an agent interface; never inferred from AgentKind.

    INITIATOR issues transactions. TARGET receives transactions.
    BIDIRECTIONAL supports both directions. STREAM_SOURCE and STREAM_SINK are
    directional streaming endpoints; they do not imply transaction completion
    tracking. Protocol-specific mappings are the responsibility of a later
    adapter, not this canonical enum.
    """

    INITIATOR = "INITIATOR"
    TARGET = "TARGET"
    BIDIRECTIONAL = "BIDIRECTIONAL"
    STREAM_SOURCE = "STREAM_SOURCE"
    STREAM_SINK = "STREAM_SINK"


__all__ = ["InterfaceRole"]
