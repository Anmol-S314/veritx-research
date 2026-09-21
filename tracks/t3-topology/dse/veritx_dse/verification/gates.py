"""veritx_dse.verification.gates — pre-spawn and post-drain gates.

A gate is a VERIFIER: it inspects a model/workload artifact (or sealed
backend evidence) and either passes or refuses. It is not part of the
artifact it checks, and it must not be.

Ownership (slice 2b): these gates used to live on the Wave-D artifact
module (``waved/backend.py``) and partly inside the artifacts
themselves. Moving an artifact must not move its checker.

Dependency law: this module imports ``core`` and ``verification`` only.
It must NOT import ``backend`` — the trace-projection differential needs
the renderer and therefore lives with the renderer in
``backend/projection.py``. A verification module importing a backend is
how the DAG gets a cycle.
"""
from __future__ import annotations

from typing import Any

from veritx_dse.core.errors import BackendFailure
from veritx_dse.verification.reference_semantics import (
    verify_logical_messages_reference, verify_packetization_reference,
)


def assert_workload_ready(pt) -> None:
    """Every artifact-level gate before any backend spawn (§24/§22).

    Order is deliberate: the logical/physical seam, then the intrinsic
    message conservation, then the independent reference differentials,
    then the physical conservation laws. A backend must never receive
    traffic from an artifact that failed any of these.

    This is artifact-only by design. The rendered-trace projection is a
    property of the RENDERER and is checked in backend/projection.py
    immediately after rendering, where the grammar lives.
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
