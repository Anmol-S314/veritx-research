"""veritx_dse.model.routing_relation_materialize — MinAdapt source semantics.

Materialize the exact source-level SROTA semantic relation for the
``MIN_ADAPT_MESH`` routing policy:

    TopologyArtifact + RoutingPolicyDefinition
        -> RoutingRelationArtifact

Semantics (normalized, no backend VC numbers):

  * at the destination: exactly one EJECT;
  * ``current_role == "escape"``: the DOR_XY escape channel only,
    ``next_role = "escape"``, priority 0;
  * ``current_role == "adaptive"``: the DOR_XY escape channel
    (priority 0) plus one action per differing coordinate dimension that
    steps exactly one Manhattan unit toward the destination
    (``next_role = "adaptive"``, priority 1);
  * ``current_role is None`` (injection): the same normalized first-network
    envelope as the adaptive role.

The escape channel is taken from the already-certified schema-v2 DOR_XY
``RouteArtifact`` — this module never reimplements XY. Concrete VC ids,
BookSim ranges, allocator selection, and deadlock certification are out of
scope.

The same physical channel may legitimately appear twice in one decision
(e.g. ``(X, adaptive, 1)`` and ``(X, escape, 0)``): different routing
resource roles are different semantic actions.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from veritx_dse.core.artifact import thaw
from veritx_dse.core.route_artifact import (
    DOR_XY, RouteArtifact, RouteArtifactError,
)
from veritx_dse.model.routing_policy import (
    CandidateMode, DeadlockProofObligation, DecisionScope, PathMode,
    RandomnessMode, RoutingPolicyDefinition, RoutingResourceRoleKind,
    RuntimeObservation, SelectionLocus,
)
from veritx_dse.model.routing_relation import (
    RoutingAction, RoutingActionKind, RoutingContext, RoutingDecision,
    RoutingRelationArtifact, RoutingRelationError, build_routing_relation,
)
from veritx_dse.model.topology_artifact import (
    MaterializedFamily, TopologyArtifact,
)

MIN_ADAPT_ALGORITHM = "per_hop_min_adaptive"
ADAPTIVE_ROLE = "adaptive"
ESCAPE_ROLE = "escape"

ADAPTIVE_PRIORITY = 1
ESCAPE_PRIORITY = 0

_ADAPTIVE_ROLE_KIND = RoutingResourceRoleKind.ADAPTIVE
_ESCAPE_ROLE_KIND = RoutingResourceRoleKind.ESCAPE
_ALLOWED_ROLE_TRANSITIONS = (
    (ADAPTIVE_ROLE, ADAPTIVE_ROLE),
    (ADAPTIVE_ROLE, ESCAPE_ROLE),
    (ESCAPE_ROLE, ESCAPE_ROLE),
)
# The only runtime observation the MinAdapt profile may carry is the router
# allocator's credit visibility; it selects among legal candidates but does
# not change the legal-action envelope materialized here.
_ALLOWED_OBSERVATIONS = ((), (RuntimeObservation.OUTPUT_CREDIT_OCCUPANCY,))
_ELIGIBLE_FAMILIES = (MaterializedFamily.MESH,
                      MaterializedFamily.CONCENTRATED_MESH)


class RoutingRelationMaterializationError(ValueError):
    """The policy/topology cannot be materialized exactly — fail closed."""


def _unsupported(reason: str) -> RoutingRelationMaterializationError:
    return RoutingRelationMaterializationError(f"UNSUPPORTED: {reason}")


def _check_min_adapt_policy(policy: RoutingPolicyDefinition) -> None:
    if not isinstance(policy, RoutingPolicyDefinition):
        raise RoutingRelationMaterializationError(
            "policy must be a RoutingPolicyDefinition")
    problems: list[str] = []
    if policy.algorithm != MIN_ADAPT_ALGORITHM:
        problems.append(f"algorithm {policy.algorithm!r}")
    if policy.algorithm_version != 1:
        problems.append(f"algorithm_version {policy.algorithm_version!r}")
    if thaw(policy.parameters) != {}:
        problems.append(f"parameters {thaw(policy.parameters)!r}")
    if policy.path_mode != PathMode.MINIMAL:
        problems.append(f"path_mode {policy.path_mode.value}")
    if policy.decision_scope != DecisionScope.PER_HOP:
        problems.append(f"decision_scope {policy.decision_scope.value}")
    if policy.candidate_mode != CandidateMode.CANDIDATE_SET:
        problems.append(f"candidate_mode {policy.candidate_mode.value}")
    if policy.selection_locus != SelectionLocus.ROUTER_ALLOCATOR:
        problems.append(f"selection_locus {policy.selection_locus.value}")
    if policy.randomness != RandomnessMode.NONE:
        problems.append("randomness is not NONE")
    if policy.state_requirements:
        problems.append("policy requires routing state")
    if policy.runtime_observations not in _ALLOWED_OBSERVATIONS:
        problems.append("unsupported runtime observations")
    roles = tuple((r.id, r.kind) for r in policy.resource_roles)
    if roles != ((ADAPTIVE_ROLE, _ADAPTIVE_ROLE_KIND),
                 (ESCAPE_ROLE, _ESCAPE_ROLE_KIND)):
        problems.append("resource roles are not exactly adaptive/escape")
    if policy.allowed_role_transitions != _ALLOWED_ROLE_TRANSITIONS:
        problems.append("role transitions do not match the MinAdapt profile")
    if policy.deadlock_proof_obligation \
            != DeadlockProofObligation.ESCAPE_SUBFUNCTION:
        problems.append("deadlock proof obligation is not ESCAPE_SUBFUNCTION")
    if problems:
        raise _unsupported(
            "only the MIN_ADAPT_MESH routing policy profile can be "
            "materialized here (" + "; ".join(problems) + ")")


def _require_mesh_grid(
        topology: TopologyArtifact) -> dict[int, tuple[int, int]]:
    """Prove the router graph is a regular non-wrap rectangular 2D mesh.

    Family is necessary but never sufficient: coordinates and the exact
    directed channel set are validated independently.
    """
    if not isinstance(topology, TopologyArtifact):
        raise RoutingRelationMaterializationError(
            "topology must be a TopologyArtifact")
    if topology.family not in _ELIGIBLE_FAMILIES:
        raise _unsupported(
            f"family {topology.family.value!r} is not a non-wrap 2D mesh")
    coordinates: dict[int, tuple[int, int]] = {}
    for router in topology.routers:
        coords = router.coordinates
        if len(coords) != 2:
            raise _unsupported(
                f"router {router.router_id} does not have 2D coordinates")
        coordinates[router.router_id] = (coords[0], coords[1])
    if len(set(coordinates.values())) != len(coordinates):
        raise _unsupported("router coordinates are not unique")
    xs = sorted({x for x, _y in coordinates.values()})
    ys = sorted({y for _x, y in coordinates.values()})
    complete = {(x, y) for x in xs for y in ys}
    if set(coordinates.values()) != complete:
        raise _unsupported("router coordinates are not a complete rectangle")
    id_of = {coords: rid for rid, coords in coordinates.items()}

    directed: dict[tuple[int, int], int] = {}
    for channel in topology.channels:
        key = (channel.src_router, channel.dst_router)
        if key in directed:
            raise _unsupported(
                f"parallel directed links {key[0]}->{key[1]} are not "
                "MinAdapt mesh semantics")
        directed[key] = channel.channel_id
    for src, dst in directed:
        (x1, y1) = coordinates[src]
        (x2, y2) = coordinates[dst]
        if abs(x1 - x2) + abs(y1 - y2) != 1:
            raise _unsupported(
                f"channel {src}->{dst} is not an orthogonal mesh link "
                "(diagonal, wrap or extra link)")
    for (x, y), router_id in id_of.items():
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbour = (x + dx, y + dy)
            if neighbour not in id_of:
                continue
            other = id_of[neighbour]
            if (router_id, other) not in directed \
                    or (other, router_id) not in directed:
                raise _unsupported(
                    f"mesh link between routers {router_id} and {other} "
                    "must exist in both directions")
    return coordinates


def _escape_channels(
        topology: TopologyArtifact,
        coordinates: Mapping[int, tuple[int, int]],
) -> dict[tuple[int, int], int]:
    try:
        artifact = RouteArtifact.from_topology(
            topology, name="min_adapt_escape",
            routing_classes=(DOR_XY,))
    except RouteArtifactError as exc:
        raise _unsupported(
            f"DOR_XY escape routing failed on this topology: {exc}"
        ) from exc
    return {(src, dst): channel
            for (_cls, src, dst), channel in artifact.entries.items()}


def _channel_by_pair(
        topology: TopologyArtifact) -> dict[tuple[int, int], int]:
    return {(c.src_router, c.dst_router): c.channel_id
            for c in topology.channels}


def _forward(channel_id: int, role: str, priority: int) -> RoutingAction:
    return RoutingAction(
        kind=RoutingActionKind.FORWARD, channel_id=channel_id,
        next_role_id=role, priority=priority)


def _eject() -> RoutingAction:
    return RoutingAction(kind=RoutingActionKind.EJECT, channel_id=None,
                         next_role_id=None, priority=ESCAPE_PRIORITY)


def _min_adapt_decisions(
        topology: TopologyArtifact,
        coordinates: Mapping[int, tuple[int, int]],
        escape_channels: Mapping[tuple[int, int], int],
) -> tuple[RoutingDecision, ...]:
    id_of = {coords: rid for rid, coords in coordinates.items()}
    by_pair = _channel_by_pair(topology)
    decisions: list[RoutingDecision] = []
    for router_id in sorted(coordinates):
        for destination in sorted(coordinates):
            for role in (None, ADAPTIVE_ROLE, ESCAPE_ROLE):
                context = RoutingContext(
                    router_id=router_id, destination_router_id=destination,
                    current_role_id=role)
                if router_id == destination:
                    decisions.append(RoutingDecision(context, (_eject(),)))
                    continue
                escape = _forward(escape_channels[(router_id, destination)],
                                  ESCAPE_ROLE, ESCAPE_PRIORITY)
                if role == ESCAPE_ROLE:
                    decisions.append(RoutingDecision(context, (escape,)))
                    continue
                (x, y) = coordinates[router_id]
                (dx, dy) = coordinates[destination]
                actions = [escape]
                if x != dx:
                    step = (x + (1 if dx > x else -1), y)
                    actions.append(_forward(by_pair[(router_id, id_of[step])],
                                            ADAPTIVE_ROLE, ADAPTIVE_PRIORITY))
                if y != dy:
                    step = (x, y + (1 if dy > y else -1))
                    actions.append(_forward(by_pair[(router_id, id_of[step])],
                                            ADAPTIVE_ROLE, ADAPTIVE_PRIORITY))
                decisions.append(RoutingDecision(context, tuple(actions)))
    return tuple(decisions)


def materialize_routing_relation(
        topology: TopologyArtifact,
        policy: RoutingPolicyDefinition,
) -> RoutingRelationArtifact:
    """Materialize the exact MinAdapt mesh legal-action relation.

    Raises RoutingRelationMaterializationError for any policy or topology
    outside the exact MIN_ADAPT_MESH contract; nothing is approximated.
    """
    _check_min_adapt_policy(policy)
    coordinates = _require_mesh_grid(topology)
    escape_channels = _escape_channels(topology, coordinates)
    decisions = _min_adapt_decisions(topology, coordinates, escape_channels)
    try:
        return build_routing_relation(policy, topology, decisions)
    except RoutingRelationError as exc:
        raise RoutingRelationMaterializationError(
            f"min_adapt relation failed total validation: {exc}") from exc
