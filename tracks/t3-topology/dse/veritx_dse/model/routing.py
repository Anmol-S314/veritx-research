"""veritx_dse.model.routing — compiler-owned route derivation (P1.2).

The routing-function problem, stated plainly: the legacy derivation
computed strings (``dim_order``/``dor``/``min_adapt``) while the
bundle independently built ``ANYNET_MIN_HOPS`` routes — derived text
that controlled no hardware semantics. This module is the single
place where the product compiler chooses routing:

    CompileRequest.dependencies + TopologyArtifact
        ↓ derive_route()
    RouteArtifact (LOCKED — no user field exists for it)

Policy (P1A slice): MESH and CONCENTRATED_MESH route DOR_XY
(dimension-order XY over the router grid — deterministic, proven by
construction-time termination walk plus the P1.4 CDG certificate).
Anything else (TORUS, RING, …) is UNSUPPORTED_SEMANTICS at the
service boundary: representability is not certification, and silent
minimum-hop fallback would certify a route set the deadlock theorem
does not cover.

``request`` is a load-bearing parameter even though the MVP policy
keys off family alone: it is type-checked (fail-closed), and future
policy (dependency-driven class choice) consumes it.
"""
from __future__ import annotations

from typing import Any

from veritx_dse.core.route_artifact import (
    DOR_XY,
    RouteArtifact,
    RouteArtifactError,
)
from veritx_dse.model.topology_artifact import MaterializedFamily

# Families the P1A compiler certifies routing for. Everything else
# refuses — including TORUS, whose wraparound needs a different
# deadlock theorem and gets its own class later.
_CERTIFIED_FAMILIES = (
    MaterializedFamily.MESH,
    MaterializedFamily.CONCENTRATED_MESH,
)


def derive_route(*, request: Any, topology: Any) -> RouteArtifact:
    """Derive the product RouteArtifact for a materialized topology.

    LOCKED semantics: the caller supplies intent + topology; the
    routing class is chosen here, never by user override (no such
    field exists on NocConfig — structurally inexpressible).
    """
    from veritx_dse.model.compile_model import CompileRequest
    if not isinstance(request, CompileRequest):
        raise RouteArtifactError(
            f"derive_route requires a CompileRequest, got "
            f"{type(request).__name__}")
    family = getattr(topology, "family", None)
    if family not in _CERTIFIED_FAMILIES:
        raise RouteArtifactError(
            f"UNSUPPORTED: no certified routing derivation for topology "
            f"family {getattr(family, 'value', family)!r} — P1A certifies "
            f"MESH and CONCENTRATED_MESH (DOR_XY) only; refusing silent "
            f"minimum-hop fallback")
    return RouteArtifact.from_topology(
        topology, name="srota-compile", routing_classes=(DOR_XY,))


__all__ = ["derive_route"]
