"""veritx_dse.model.routing — compiler-owned route derivation (P1.2).

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

from typing import Any

from veritx_dse.core.route_artifact import (
    DOR_TORUS_XY,
    DOR_XY,
    FLATFLY_MIN,
    RouteArtifact,
    RouteArtifactError,
)
from veritx_dse.core.route_artifact import ANYNET_MIN_HOPS
from veritx_dse.model.routing_materialize import (
    WEIGHTED_SHORTEST_PATH,
)
from veritx_dse.model.topology_artifact import MaterializedFamily

_CERTIFIED_FAMILIES = (
    MaterializedFamily.MESH,
    MaterializedFamily.CONCENTRATED_MESH,
)

_POLICY_BY_FAMILY: dict[MaterializedFamily, str] = {
    MaterializedFamily.MESH: DOR_XY,
    MaterializedFamily.CONCENTRATED_MESH: DOR_XY,
    MaterializedFamily.TORUS: DOR_TORUS_XY,
    MaterializedFamily.FLATFLY: FLATFLY_MIN,
    MaterializedFamily.GEC_EXPRESS: ANYNET_MIN_HOPS,
    MaterializedFamily.CUSTOM: ANYNET_MIN_HOPS,
}


def _weighted_shortest_path_policy() -> Any:
    """The canonical deterministic minimum-weight routing policy.

Rationale: docs/decisions/modules/model.md
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


def _anynet_min_hops_policy() -> Any:
    """The SEALED minimum-hop policy: the BookSim AnyNet replica.

Rationale: docs/decisions/modules/model.md
    """
    from veritx_dse.model.routing_policy import (
        CandidateMode, DecisionScope, DeadlockProofObligation, PathMode,
        RandomnessMode, RoutingPolicyDefinition, RoutingResourceRole,
        RoutingResourceRoleKind, SelectionLocus,
    )
    return RoutingPolicyDefinition(
        id=ANYNET_MIN_HOPS,
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
        parameters={"weight_metric": "hop_count",
                    "tie_break_policy": "anynet_ascending_min"},
    )


def _certified_mapping_text() -> str:
    """Render the certified family -> policy mapping FROM the table.

    DERIVED, never hand-written. The previous diagnostic hard-coded
    "WEIGHTED_SHORTEST_PATH for explicit custom graphs" while
    `_POLICY_BY_FAMILY[CUSTOM]` was `ANYNET_MIN_HOPS`; a derived string
    cannot drift from the table it describes.
    """
    return "; ".join(
        f"{fam.value} -> {_POLICY_BY_FAMILY[fam]}"
        for fam in sorted(_POLICY_BY_FAMILY, key=lambda f: f.value)
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
            f"{getattr(family, 'value', family)!r} \u2014 the certified "
            f"mapping is [{_certified_mapping_text()}]; other families have "
            "no certified routing yet. Refusing rather than guessing a "
            "route semantic.")
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
    if policy_id == DOR_TORUS_XY:
        try:
            return RouteArtifact.from_topology(
                topology, name="srota-compile",
                routing_classes=(DOR_TORUS_XY,))
        except RouteArtifactError as exc:
            raise RouteArtifactError(
                f"UNSUPPORTED: DOR_TORUS_XY could not be realized: "
                f"{exc}") from exc
    if policy_id == FLATFLY_MIN:
        # Minimal lowest-dimension-first; DETERMINISTIC_CDG per (k, n)
        # shape discharged downstream — never by-construction here.
        try:
            return RouteArtifact.from_topology(
                topology, name="srota-compile",
                routing_classes=(FLATFLY_MIN,))
        except RouteArtifactError as exc:
            raise RouteArtifactError(
                f"UNSUPPORTED: FLATFLY_MIN could not be realized: "
                f"{exc}") from exc
    if policy_id == ANYNET_MIN_HOPS:
        from veritx_dse.model.routing_materialize import (
            materialize_route_artifact,
        )
        try:
            return materialize_route_artifact(
                _anynet_min_hops_policy(), topology, name="srota-compile")
        except Exception as exc:
            raise RouteArtifactError(
                f"UNSUPPORTED: the declared routing policy {policy_id!r} "
                f"could not be realized on family "
                f"{getattr(family, 'value', family)!r}: {exc}") from exc
    if policy_id == WEIGHTED_SHORTEST_PATH:
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
