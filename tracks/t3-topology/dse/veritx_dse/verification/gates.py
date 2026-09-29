"""veritx_dse.verification.gates — pre-spawn and post-drain gates.

Rationale: docs/decisions/modules/verification.md
"""
from __future__ import annotations

from typing import Any

from veritx_dse.core.errors import BackendFailure
from veritx_dse.verification.reference_semantics import (
    verify_logical_messages_reference, verify_packetization_reference,
)


def assert_workload_ready(pt) -> None:
    """Every artifact-level gate before any backend spawn (§24/§22).

Rationale: docs/decisions/modules/verification.md
    """
    pt.validate_against_bundle()
    pt.logical.validate_conservation()
    verify_logical_messages_reference(pt.logical)
    pt.validate_conservation()
    verify_packetization_reference(pt)


def verify_backend_quiescence(summary: dict[str, Any],
                              counters: dict[str, Any]) -> None:
    """§21: the backend must have drained exactly the derived traffic.

    Uses only sealed Wave-B evidence counters (delivered packets, flit
    injected/accepted totals). A missing counter is a hard failure, not
    a skipped check: quiescence cannot be asserted from silence.
    """
    expected_packets = summary["num_packets"]
    expected_flits = summary["flits_total"]
    delivered = counters.get("delivered_packets")
    injected = counters.get("flits_injected")
    accepted = counters.get("flits_accepted")
    if delivered != expected_packets:
        raise BackendFailure(
            f"backend delivered {delivered!r} packets, expected "
            f"{expected_packets} — trace did not drain exactly")
    if injected != expected_flits or accepted != expected_flits:
        raise BackendFailure(
            f"backend flit counters injected={injected!r} "
            f"accepted={accepted!r}, expected {expected_flits} each")


__all__ = ["assert_workload_ready", "verify_backend_quiescence"]
