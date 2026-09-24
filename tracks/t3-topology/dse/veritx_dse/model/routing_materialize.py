"""veritx_dse.model.routing_materialize — deterministic policy materialization.

Compile a ``RoutingPolicyDefinition`` into the existing sealed schema-v2
``RouteArtifact`` — but only when the policy has an exact deterministic
singleton realization:

    (current_router, destination) -> exactly one DirectedChannel

Representability profile (anything else is refused, never approximated):

    decision_scope       STATIC
    candidate_mode       SINGLETON
    selection_locus      ROUTE_COMPUTE
    randomness           NONE
    state_requirements   empty
    runtime_observations empty
    resource roles       exactly one, kind DEFAULT
    role transitions     empty or a single DEFAULT self-transition

Supported families (recognized from the validated semantic profile, never
from ``policy.id``):

  * DOR_XY               delegates to the certified RouteArtifact class;
  * ANYNET_MIN_HOPS      delegates to the certified RouteArtifact class;
  * WEIGHTED_SHORTEST_PATH  new producer over directed channels:
        primary key  minimum sum of DirectedChannel.route_weight
        tie-break    lexicographically smallest full channel-id sequence
  * CUSTOM_STATIC        explicit caller-supplied exact table.

``deadlock_proof_obligation`` is descriptive only: changing it must not
change the realized forwarding table, and this module never runs the CDG or
protocol verifiers. ``policy_hash`` never enters ``RouteArtifact`` identity —
intended semantics and exact realized tables are separate objects.
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

import heapq
from collections.abc import Mapping
from enum import Enum
from typing import Any

from veritx_dse.core.artifact import thaw
from veritx_dse.core.route_artifact import (
    ANYNET_MIN_HOPS, DOR_XY, RouteArtifact, RouteArtifactError,
    RoutingClassDefinition,
)
from veritx_dse.model.routing_policy import (
    CandidateMode, DecisionScope, PathMode, RandomnessMode,
    RoutingPolicyDefinition, RoutingResourceRoleKind, SelectionLocus,
)
from veritx_dse.model.topology_artifact import TopologyArtifact

WEIGHTED_SHORTEST_PATH = "WEIGHTED_SHORTEST_PATH"
CUSTOM_STATIC = "CUSTOM_STATIC"

# Exact semantic parameter contracts. Unknown or incompatible parameters are
# refused because they could change forwarding behaviour.
_DOR_IMPLICIT_PARAMETERS: dict[str, Any] = {}
_DOR_EXPLICIT_PARAMETERS = {"dimension_order": ["x", "y"], "wraparound": False}
_ANYNET_PARAMETERS = {"weight_metric": "hop_count",
                      "tie_break_policy": "anynet_ascending_min"}
_WEIGHTED_PARAMETERS = {
    "weight_metric": "route_weight",
    "tie_break_policy": "lexicographic_channel_ids",
}


class RoutingMaterializationError(ValueError, SemanticError):
    """The policy cannot be realized by RouteArtifact — fail closed."""


class _Family(Enum):
    DOR_XY = "dor_xy"
    ANYNET_MIN_HOPS = "anynet_min_hops"
    WEIGHTED_SHORTEST_PATH = "weighted_shortest_path"
    CUSTOM_STATIC = "custom_static"


def _unrepresentable(reason: str) -> RoutingMaterializationError:
    return RoutingMaterializationError(f"UNREPRESENTABLE: {reason}")


def _check_representable(policy: RoutingPolicyDefinition) -> None:
    if not isinstance(policy, RoutingPolicyDefinition):
        raise RoutingMaterializationError(
            "policy must be a RoutingPolicyDefinition")
    if policy.decision_scope != DecisionScope.STATIC:
        raise _unrepresentable(
            f"decision_scope {policy.decision_scope.value} is not STATIC")
    if policy.candidate_mode != CandidateMode.SINGLETON:
        raise _unrepresentable(
            f"candidate_mode {policy.candidate_mode.value} is not SINGLETON")
    if policy.selection_locus != SelectionLocus.ROUTE_COMPUTE:
        raise _unrepresentable(
            f"selection_locus {policy.selection_locus.value} is not "
            "ROUTE_COMPUTE")
    if policy.randomness != RandomnessMode.NONE:
        raise _unrepresentable("randomness is not NONE")
    if policy.state_requirements:
        raise _unrepresentable("policy requires routing state")
    if policy.runtime_observations:
        raise _unrepresentable("policy requires runtime observations")
    roles = policy.resource_roles
    if len(roles) != 1 or roles[0].kind != RoutingResourceRoleKind.DEFAULT:
        raise _unrepresentable(
            "a deterministic RouteArtifact requires exactly one DEFAULT "
            "resource role")
    role_id = roles[0].id
    if policy.allowed_role_transitions not in ((), ((role_id, role_id),)):
        raise _unrepresentable("non-trivial role-transition semantics")


def _classify(policy: RoutingPolicyDefinition) -> _Family:
    _check_representable(policy)
    if policy.path_mode != PathMode.MINIMAL:
        raise _unrepresentable(
            f"path_mode {policy.path_mode.value} requires a relation "
            "artifact, not a singleton table")
    parameters = thaw(policy.parameters)
    if policy.algorithm == "dimension_order":
        if policy.algorithm_version != 1:
            raise _unrepresentable("unsupported dimension_order version")
        if parameters not in (_DOR_IMPLICIT_PARAMETERS,
                              _DOR_EXPLICIT_PARAMETERS):
            raise _unrepresentable(
                f"incompatible DOR parameters {parameters!r}; only x-then-y "
                "non-wrap is certified")
        return _Family.DOR_XY
    if policy.algorithm == "weighted_shortest_path":
        if policy.algorithm_version != 1:
            raise _unrepresentable(
                "unsupported weighted_shortest_path version")
        if parameters == _ANYNET_PARAMETERS:
            return _Family.ANYNET_MIN_HOPS
        if parameters == _WEIGHTED_PARAMETERS:
            return _Family.WEIGHTED_SHORTEST_PATH
        raise _unrepresentable(
            f"unsupported weighted_shortest_path parameters {parameters!r}")
    if policy.algorithm == "custom_static_table":
        if policy.algorithm_version != 1:
            raise _unrepresentable("unsupported custom_static_table version")
        _custom_table_ref(policy)
        return _Family.CUSTOM_STATIC
    raise _unrepresentable(f"unknown deterministic algorithm "
                           f"{policy.algorithm!r}")


def _custom_table_ref(policy: RoutingPolicyDefinition) -> str:
    parameters = thaw(policy.parameters)
    if set(parameters) != {"table_ref"}:
        raise _unrepresentable(
            f"custom static parameters must be exactly {{'table_ref': ...}}, "
            f"got {parameters!r}")
    table_ref = parameters["table_ref"]
    if not isinstance(table_ref, str) or not table_ref:
        raise _unrepresentable("custom table_ref must be a non-empty string")
    return table_ref


# ── new deterministic producer: weighted shortest path ───────────────────

def _weighted_first_hops(
        topology: TopologyArtifact) -> dict[tuple[int, int], int]:
    """First channel of the canonical minimum-weight path for every pair.

    Ordering key is ``(total route_weight, channel-id sequence)``; ties on
    cost are broken by the lexicographically smallest complete channel-id
    sequence, so the result is independent of traversal/set ordering and
    parallel links are considered individually.
    """
    outgoing: dict[int, list] = {r.router_id: [] for r in topology.routers}
    for channel in topology.channels:
        outgoing[channel.src_router].append(channel)
    for channels in outgoing.values():
        channels.sort(key=lambda c: c.channel_id)

    first_hops: dict[tuple[int, int], int] = {}
    for src in sorted(outgoing):
        best: dict[int, tuple[int, tuple[int, ...]]] = {src: (0, ())}
        settled: dict[int, tuple[int, tuple[int, ...]]] = {}
        queue: list[tuple[int, tuple[int, ...], int]] = [(0, (), src)]
        while queue:
            cost, sequence, node = heapq.heappop(queue)
            if node in settled or best.get(node) != (cost, sequence):
                continue
            settled[node] = (cost, sequence)
            for channel in outgoing[node]:
                nxt = channel.dst_router
                if nxt in settled:
                    continue
                candidate = (cost + channel.route_weight,
                             sequence + (channel.channel_id,))
                if nxt not in best or candidate < best[nxt]:
                    best[nxt] = candidate
                    heapq.heappush(queue,
                                   (candidate[0], candidate[1], nxt))
        for dst in sorted(outgoing):
            if dst == src:
                continue
            if dst not in settled:
                raise _unrepresentable(
                    f"no directed path from router {src} to router {dst}")
            first_hops[(src, dst)] = settled[dst][1][0]
    return first_hops


def _weighted_definition() -> RoutingClassDefinition:
    return RoutingClassDefinition(
        id=WEIGHTED_SHORTEST_PATH,
        algorithm="weighted_shortest_path",
        algorithm_version=1,
        parameters=(
            ("edge_cost_field", "route_weight"),
            ("objective", "minimum_total_route_weight"),
            ("tie_break", "lexicographic_channel_id_sequence"),
        ),
    )


# ── materializers ────────────────────────────────────────────────────────

def _materialize_delegated(
        topology: TopologyArtifact, name: str, family: _Family
) -> RouteArtifact:
    routing_class = (DOR_XY if family == _Family.DOR_XY
                     else ANYNET_MIN_HOPS)
    try:
        return RouteArtifact.from_topology(
            topology, name=name, routing_classes=(routing_class,))
    except RouteArtifactError as exc:
        raise _unrepresentable(
            f"{routing_class} cannot be materialized on this topology: "
            f"{exc}") from exc


def _materialize_weighted(
        topology: TopologyArtifact, name: str) -> RouteArtifact:
    first_hops = _weighted_first_hops(topology)
    entries = {(WEIGHTED_SHORTEST_PATH, src, dst): channel
               for (src, dst), channel in sorted(first_hops.items())}
    try:
        return RouteArtifact.from_topology(
            topology, name=name, routing_classes=(_weighted_definition(),),
            entries=entries)
    except RouteArtifactError as exc:
        raise _unrepresentable(
            f"weighted realization failed validation: {exc}") from exc


def _clean_custom_entries(
        custom_entries: Any) -> dict[tuple[int, int], int]:
    if not isinstance(custom_entries, Mapping):
        raise _unrepresentable(
            "CUSTOM_STATIC requires custom_entries as a mapping of "
            "(src_router, dst_router) -> channel_id")
    cleaned: dict[tuple[int, int], int] = {}
    for key, value in custom_entries.items():
        if not isinstance(key, tuple) or len(key) != 2:
            raise _unrepresentable(
                f"custom table key {key!r} must be a "
                "(src_router, dst_router) tuple")
        src, dst = key
        if type(src) is not int or type(dst) is not int:
            raise _unrepresentable(
                f"custom table key {key!r} must contain exact integers")
        if type(value) is not int:
            raise _unrepresentable(
                f"custom table entry {key!r} channel id {value!r} must be "
                "an exact int")
        cleaned[(src, dst)] = value
    return cleaned


def _materialize_custom(
        policy: RoutingPolicyDefinition, topology: TopologyArtifact,
        name: str, custom_entries: Any) -> RouteArtifact:
    if custom_entries is None:
        raise _unrepresentable(
            "CUSTOM_STATIC requires an explicit caller-supplied exact table")
    cleaned = _clean_custom_entries(custom_entries)
    definition = RoutingClassDefinition(
        id=CUSTOM_STATIC,
        algorithm=policy.algorithm,
        algorithm_version=policy.algorithm_version,
        parameters=(("table_ref", _custom_table_ref(policy)),),
    )
    entries = {(CUSTOM_STATIC, src, dst): channel
               for (src, dst), channel in sorted(cleaned.items())}
    try:
        return RouteArtifact.from_topology(
            topology, name=name, routing_classes=(definition,),
            entries=entries)
    except RouteArtifactError as exc:
        raise _unrepresentable(
            f"custom static table failed validation: {exc}") from exc


def materialize_route_artifact(
        policy: RoutingPolicyDefinition,
        topology: TopologyArtifact,
        *,
        name: str,
        custom_entries: Any = None,
) -> RouteArtifact:
    """Materialize the policy into a sealed deterministic RouteArtifact.

    Raises RoutingMaterializationError whenever the policy is not exactly
    representable as ``(current_router, destination) -> one channel``.
    """
    if not isinstance(topology, TopologyArtifact):
        raise RoutingMaterializationError(
            "topology must be a TopologyArtifact")
    if not isinstance(name, str) or not name:
        raise RoutingMaterializationError("name must be a non-empty string")
    family = _classify(policy)
    if family == _Family.CUSTOM_STATIC:
        return _materialize_custom(policy, topology, name, custom_entries)
    if custom_entries is not None:
        raise _unrepresentable(
            f"custom_entries are only valid for CUSTOM_STATIC, not "
            f"{family.value}")
    if family in (_Family.DOR_XY, _Family.ANYNET_MIN_HOPS):
        return _materialize_delegated(topology, name, family)
    return _materialize_weighted(topology, name)
