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

from veritx_dse.core.errors import BackendFailure, UnsupportedSemantics
from veritx_dse.verification.reference_semantics import (
    verify_logical_messages_reference, verify_packetization_reference,
)


def assert_vc_admission(pt) -> None:
    """Every message class must be admitted by the fabric VC structure.

    The cross-layer check P1A could not exercise: the VC artifact owns
    ``traffic_class → VCs`` while logical messages carry their own
    class. Before any backend spawn, every message class must exist in
    the fabric's VC map with at least one legal VC, every referenced
    VC must exist, and every referenced VC must map to a routing class
    the resolved route defines. A compiled fabric offering {A, B} with
    DEFAULT messages refuses HERE — never as a silent VC0 injection
    or a backend misroute.

    Raises UnsupportedSemantics: a deterministic semantic mismatch,
    not a backend failure.
    """
    vc = pt.bundle.vc_assignment
    class_to_vcs = dict(vc.traffic_class_to_vcs)
    vc_to_route = dict(vc.vc_to_routing_class)
    route_classes = set(pt.bundle.resolved_route.routing_classes)
    seen: set[str] = set()
    for m in pt.logical.messages:
        cls = m.traffic_class
        if cls in seen:
            continue
        seen.add(cls)
        if cls not in class_to_vcs:
            raise UnsupportedSemantics(
                f"traffic class {cls!r} is not admitted by the fabric "
                f"VC structure (VC classes: {sorted(class_to_vcs)}) — "
                f"refusing to send unadmitted workload traffic")
        vcs = class_to_vcs[cls]
        if not vcs:
            raise UnsupportedSemantics(
                f"traffic class {cls!r} maps to no VC — refusing")
        for v in vcs:
            if v not in vc_to_route:
                raise UnsupportedSemantics(
                    f"traffic class {cls!r} references VC {v} with no "
                    f"routing-class binding — refusing")
            if vc_to_route[v] not in route_classes:
                raise UnsupportedSemantics(
                    f"traffic class {cls!r} VC {v} maps to routing class "
                    f"{vc_to_route[v]!r} outside the resolved route "
                    f"{sorted(route_classes)} — refusing")


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
    # P1B.3: cross-layer admission first — an unadmitted workload must
    # refuse before any conservation/projection work, let alone a spawn.
    assert_vc_admission(pt)
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


__all__ = ["assert_vc_admission", "assert_workload_ready",
           "verify_backend_quiescence"]
