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
# NOTE (ownership debt): the WEIGHTED_SHORTEST_PATH class id is owned by
# `model.routing_materialize` (the producer) rather than by
# `core.route_artifact` (the sealed artifact owner), unlike DOR_XY and
# ANYNET_MIN_HOPS which live in the artifact module. Imported here rather
# than re-declared so there is one spelling. Moving it into route_artifact
# would be a rename of a sealed artifact and is deliberately not done here.
from veritx_dse.model.routing_materialize import (
    WEIGHTED_SHORTEST_PATH,
)
from veritx_dse.model.topology_artifact import MaterializedFamily

# Families the P1A compiler certifies routing for. Everything else
# refuses — including TORUS, whose wraparound needs a different
# deadlock theorem and gets its own class later.
_CERTIFIED_FAMILIES = (
    MaterializedFamily.MESH,
    MaterializedFamily.CONCENTRATED_MESH,
)

#: THE DECLARED ROUTING-POLICY TABLE (compiler-owned).
#:
#: This is the canonical authority for "which routing semantic does this
#: topology use". It is DATA, not a branch: an implicit `if CUSTOM:` inside
#: the compiler would be an undocumented semantic, and the point of the
#: table is that the choice is inspectable and has exactly one owner.
#:
#:   DOR_XY                 deadlock-free BY CONSTRUCTION. Dimension-order
#:                          traversal terminates; the ordering IS the proof,
#:                          so no CDG check is needed to certify it.
#:   WEIGHTED_SHORTEST_PATH deadlock-freedom is a PROPERTY TO BE CHECKED,
#:                          not a consequence of the algorithm. It is
#:                          selected for every family DOR cannot express
#:                          because it is the only producer whose semantics
#:                          are defined over canonical DIRECTED channels
#:                          with an explicit, traversal-independent
#:                          tie-break, and it handles parallel links
#:                          individually.
#:
#: `ANYNET_MIN_HOPS` is deliberately NOT the default: its name and its
#: `anynet_ascending_min` tie-break encode a BookSim backend concept, and a
#: backend spelling must not become the canonical routing contract. It
#: stays reachable through `routing_materialize` for callers that ask for
#: it explicitly.
_POLICY_BY_FAMILY: dict[MaterializedFamily, str] = {
    MaterializedFamily.MESH: DOR_XY,
    MaterializedFamily.CONCENTRATED_MESH: DOR_XY,
    # CUSTOM is the Tranche-5 deliverable: an explicit graph has no family
    # materializer to key a policy off, so it takes the one producer whose
    # semantics are defined over canonical directed channels.
    MaterializedFamily.CUSTOM: WEIGHTED_SHORTEST_PATH,
    # TORUS / RING / FLATFLY are deliberately ABSENT. They are not refused
    # because minimum-hop "does not work" — measured on a 5x5 torus it
    # routes and the CDG then reports acyclic=False with a 6-node cycle
    # witness, which is a real and useful scientific verdict. They are
    # absent because widening THEM is a separate, evidence-backed decision
    # that changes an existing contract (torus currently stops at ROUTING
    # with upstream artifacts preserved), and this tranche's purpose is
    # custom fabrics. Adding a family here is a one-line change once that
    # decision is made deliberately.
}


def _weighted_shortest_path_policy() -> Any:
    """The canonical deterministic minimum-weight routing policy.

    Exactly the representability profile `routing_materialize` accepts:
    STATIC / SINGLETON / ROUTE_COMPUTE / randomness NONE, no state, no
    runtime observations, one DEFAULT resource role, no transitions.

    `deadlock_proof_obligation` is DETERMINISTIC_CDG: the OBLIGATION to run
    the channel-VC dependency-graph check is declared here and discharged
    downstream by the normal DEADLOCK_FREE obligation. Declaring it is not
    passing it, and this policy makes no deadlock claim of its own.
    """
    from veritx_dse.model.routing_policy import (
        CandidateMode, DecisionScope, DeadlockProofObligation, PathMode,
        RandomnessMode, RoutingPolicyDefinition, RoutingResourceRole,
        RoutingResourceRoleKind, SelectionLocus,
    )
    from veritx_dse.model.routing_materialize import (
        WEIGHTED_SHORTEST_PATH as _WSP,
    )
    return RoutingPolicyDefinition(
        id=_WSP,
        algorithm="weighted_shortest_path",
        algorithm_version=1,
        path_mode=PathMode.MINIMAL,
        decision_scope=DecisionScope.STATIC,
        candidate_mode=CandidateMode.SINGLETON,
        selection_locus=SelectionLocus.ROUTE_COMPUTE,
        randomness=RandomnessMode.NONE,
        deadlock_proof_obligation=DeadlockProofObligation.DETERMINISTIC_CDG,
        resource_roles=(RoutingResourceRole(
            id="default", kind=RoutingResourceRoleKind.DEFAULT),),
        parameters={"weight_metric": "route_weight",
                    "tie_break_policy": "lexicographic_channel_ids"},
    )


def routing_policy_for(topology: Any) -> str:
    """The declared routing policy id for a materialized topology.

    Public so a caller can INSPECT the choice instead of inferring it from
    compiler behaviour. Raises for an unregistered family rather than
    falling back to a default: an unknown family must never silently
    inherit some other family's routing science.
    """
    family = getattr(topology, "family", None)
    policy = _POLICY_BY_FAMILY.get(family)
    if policy is None:
        raise RouteArtifactError(
            f"UNSUPPORTED: no certified routing policy for topology family "
            f"{getattr(family, 'value', family)!r} \u2014 DOR_XY is certified "
            "for mesh and concentrated_mesh, and WEIGHTED_SHORTEST_PATH for "
            "explicit custom graphs; other families have no certified "
            "routing yet. Refusing rather than guessing a route semantic.")
    return policy


def derive_route(*, request: Any, topology: Any) -> RouteArtifact:
    """Derive the product RouteArtifact for a materialized topology.

    LOCKED semantics: the caller supplies intent + topology; the
    routing class is chosen here, never by user override (no such
    field exists on NocConfig — structurally inexpressible).
    """
    from veritx_dse.model.compile_model import (
        CompileRequest, FabricIntentView,
    )
    # P1C phase-2: the gate accepts the fabric view too. It reads
    # NOTHING from the request (routing is LOCKED off the topology),
    # so the v2 flow is provably identical — the view only lets v3
    # reach the same derivation without a fake-v2 conversion.
    if not isinstance(request, (CompileRequest, FabricIntentView)):
        raise RouteArtifactError(
            f"derive_route requires a CompileRequest or "
            f"FabricIntentView, got "
            f"{type(request).__name__}")
    family = getattr(topology, "family", None)
    policy_id = routing_policy_for(topology)
    if policy_id == DOR_XY:
        # Deadlock-free by construction; no CDG check required.
        return RouteArtifact.from_topology(
            topology, name="srota-compile", routing_classes=(DOR_XY,))
    if policy_id == WEIGHTED_SHORTEST_PATH:
        # Deadlock-freedom is a property the CDG obligation must CHECK. The
        # producer lives in `routing_materialize`; this module only SELECTS
        # the policy and calls it. There is no synthesis/authoring branch
        # here — the topology's family alone decides.
        from veritx_dse.model.routing_materialize import (
            materialize_route_artifact,
        )
        try:
            return materialize_route_artifact(
                _weighted_shortest_path_policy(), topology,
                name="srota-compile")
        except Exception as exc:
            raise RouteArtifactError(
                f"UNSUPPORTED: the declared routing policy "
                f"{policy_id!r} could not be realized on family "
                f"{getattr(family, 'value', family)!r}: {exc}") from exc
    raise RouteArtifactError(
        f"UNSUPPORTED: declared routing policy {policy_id!r} has no "
        "producer in this compiler — refusing silent fallback")


__all__ = ["derive_route", "routing_policy_for"]
