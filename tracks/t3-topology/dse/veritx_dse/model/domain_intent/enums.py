"""enums — domain vocabulary enums (contract §3).

Split out of veritx_dse.model.domain_intent; the package __init__
re-exports every public name, so importers are unchanged.

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

from enum import Enum

# --------------------------------------------------------------------------
# vocabulary (contract §3)
# --------------------------------------------------------------------------

class ClockSourceKind(Enum):
    PLL = "PLL"
    XTAL = "XTAL"
    EXTERNAL = "EXTERNAL"
    DIVIDER = "DIVIDER"


class Polarity(Enum):
    ACTIVE_HIGH = "ACTIVE_HIGH"
    ACTIVE_LOW = "ACTIVE_LOW"


class AssertionMode(Enum):
    ASYNC = "ASYNC"
    SYNC = "SYNC"


class DeassertionMode(Enum):
    """Only SYNC exists. ASYNC deassertion is a typed refusal, not a member.

    Modeling it as an enum member would imply the system supports it. It does
    not, so the value is refused by name in ``ResetChannel.from_dict``.
    """
    SYNC = "SYNC"


class PowerPolicy(Enum):
    ALWAYS_ON = "ALWAYS_ON"
    COLLAPSIBLE = "COLLAPSIBLE"


class SignalKind(Enum):
    SINGLE_BIT = "SINGLE_BIT"
    MULTI_BIT = "MULTI_BIT"
    PULSE = "PULSE"
    BUS = "BUS"


class CrossingMechanism(Enum):
    SYNC_2FF = "SYNC_2FF"
    SYNC_3FF = "SYNC_3FF"
    HANDSHAKE = "HANDSHAKE"
    ASYNC_FIFO = "ASYNC_FIFO"
    UNRESOLVED = "UNRESOLVED"


class PointerEncoding(Enum):
    BINARY = "BINARY"
    GRAY = "GRAY"


class CrossingVerdict(Enum):
    INTENT_VALID = "INTENT_VALID"
    UNRESOLVED_CROSSING = "UNRESOLVED_CROSSING"


class FidelityLevel(Enum):
    HETERO_TIMING_ABSTRACT = "HETERO_TIMING_ABSTRACT"
    NOT_MODELED = "NOT_MODELED"


_SYNC_FLOP_MECHANISMS = frozenset({CrossingMechanism.SYNC_2FF, CrossingMechanism.SYNC_3FF})
_LEVEL_SENSITIVE = frozenset({SignalKind.SINGLE_BIT, SignalKind.PULSE})
_MULTI_BIT = frozenset({SignalKind.MULTI_BIT, SignalKind.BUS})
_REQUIRED_SYNC_STAGES = {
    CrossingMechanism.SYNC_2FF: 2,
    CrossingMechanism.SYNC_3FF: 3,
}
# Handshake flops use the same synchronizer stage vocabulary; anything else is
# an undeclared depth, so it refuses rather than being assumed.
_HANDSHAKE_ALLOWED_STAGES = (None, 2, 3)
