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

def _derive_shared_resource_route(*, request: Any, topology: Any,
                                  family: Any, shared: Any) -> Any | None:
    """A v3 route for a shared-wire fabric, or None if no rule is proven.

    Only families whose hop rule has been checked against the simulator's
    own executed realization appear here. Adding a family to this table is
    the moment its rule becomes trusted, so it is deliberately an explicit
    list rather than a lookup by name.
    """
    from veritx_dse.model.route_artifact_v3 import (
        route_artifact_v3_for_srota_row_first,
    )
    if family is MaterializedFamily.GEC_MECS:
        # A MECS hop's eligible VCs are the TAP's slice, so the route and the
        # VC stage must agree on one count. The VC derivation derives
        # `num_vcs = d` from the same family knowledge (vcs_from_multidrop),
        # which makes each tap own exactly ONE VC and the partition map a
        # function of the tap index — so neither side needs the other to
        # have run first, and neither can disagree.
        from veritx_dse.model.gec_mecs_route import GecMecsParams
        from veritx_dse.model.route_artifact_v3 import (
            route_artifact_v3_for_gec_mecs,
        )
        intent = getattr(request, "topology", None)
        k = getattr(intent, "grid_side_length", None)
        concentration = getattr(intent, "concentration", None)
        o = getattr(intent, "express_channel_groups_per_dimension", None)
        d = getattr(intent, "destinations_per_express_channel", None)
        if None in (k, concentration, o, d):
            return None
        params = GecMecsParams(k=k, c=concentration, o=o, d=d, num_vcs=d)
        artifact = route_artifact_v3_for_gec_mecs(
            params, topology_hash=topology.topology_hash())
        # The route must agree with the fabric it claims to route over; the
        # artifact's own parent check is the wire count.
        artifact.validate_against(topology)
        return artifact
    if family is not MaterializedFamily.SROTA:
        return None
    intent = getattr(request, "topology", None)
    if intent is None or getattr(intent, "kind", None) != "srota":
        return None
    from veritx_dse.model.srota_rowfirst_route import SrotaRowFirstParams
    side_length = getattr(intent, "side_length", None)
    concentration = getattr(intent, "concentration", None)
    if side_length is None or concentration is None:
        return None
    paths = getattr(intent, "path_shapes", frozenset())
    names = {getattr(p, "value", p) for p in paths}
    policy = getattr(getattr(intent, "vc_policy", None), "value", None)
    island_columns = tuple(getattr(topology, "island_columns", ()) or ())
    if island_columns and "column" not in names:
        # Island-bound flows take column-first (srota_isl_route=colfirst,
        # the rule that makes the I-ISL placement invariant hold). A route
        # that carries no column-first choice cannot describe them, so
        # refuse rather than certify a fabric the run would route
        # differently.
        raise RouteArtifactError(
            "UNSUPPORTED: island-bound flows take column-first "
            "(srota_isl_route=colfirst, the rule that makes I-ISL hold), "
            "so an island design needs the column-first shape in its "
            "route: declare path_shapes row+column with vc_policy=shape, "
            "or the rank policy with column. This design declares "
            f"{sorted(names)} under vc_policy={policy!r}")
    if policy == "rank":
        # Hop-rank partition: the only policy the fork accepts for Valiant
        # (`shape` and `oneshape` both exit(-1) with Valiant enabled).
        # Row-first is mandatory in the fork (bit 0 anchors every proof), so
        # a declared Valiant shape implies row-first too.
        if not (bool(getattr(intent, "mecs_row", False))
                and bool(getattr(intent, "mecs_col", False))):
            raise RouteArtifactError(
                "UNSUPPORTED: the rank + Valiant envelope requires the full "
                "express layer (mecs_row and mecs_col); a plain "
                "nearest-neighbour dimension has no tap, so the rank walk "
                "does not describe it")
        from veritx_dse.model.srota_rank_route import (
            rank_policy_route_for_srota,
        )
        artifact = rank_policy_route_for_srota(
            k=side_length, c=concentration,
            shapes=frozenset(names | {"row"}), mecs_row=True, mecs_col=True,
            topology_hash=topology.topology_hash())
        artifact.validate_against(topology)
        return artifact
    effective_d_vcs = 2 if names == {"row", "column"} else 1
    params = SrotaRowFirstParams(
        k=side_length, c=concentration, num_vcs=effective_d_vcs,
        mecs_row=bool(getattr(intent, "mecs_row", False)),
        mecs_col=bool(getattr(intent, "mecs_col", False)))
    if names == {"row", "column"}:
        # Both direct shapes, separated by VC. The route is a UNION: the FIU
        # picks the shape per flow from live telemetry load, so there is no
        # single decision per pair and the obligation is over every
        # realizable choice.
        if policy != "shape":
            raise RouteArtifactError(
                f"UNSUPPORTED: the two direct SROTA shapes are proved with "
                f"the 'shape' VC partition only (one VC set per shape); "
                f"this design declares vc_policy={policy!r}. Any other "
                "policy leaves the shapes sharing VCs, which re-opens "
                "RT-R7")
        from veritx_dse.model.route_artifact_v3 import (
            shape_policy_route_for_srota,
        )
        artifact = shape_policy_route_for_srota(
            params, topology_hash=topology.topology_hash())
        artifact.validate_against(topology)
        return artifact
    if names != {"row"}:
        # Only the single row-first shape has a deterministic derived rule.
        # VALIANT turns twice and closes a cycle on its own (the source
        # refuses shape+Valiant outright), so it is refused rather than
        # routed as if the two-shape proof covered it.
        raise RouteArtifactError(
            f"UNSUPPORTED: the derived SROTA shared-resource rule covers "
            f"the single row-first shape and the row+column pair only; this "
            f"design declares {sorted(names)}")
    return route_artifact_v3_for_srota_row_first(
        params, topology_hash=topology.topology_hash())

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
    shared = getattr(topology, "shared_links", ())
    if shared:
        if family is MaterializedFamily.GEC_HYBRID:
            from veritx_dse.model.gec_hybrid_route import (
                GecHybridParams, gec_hybrid_route_for_topology,
            )
            intent = request.topology
            # One VC per (phase, tap). The VC stage derives the same floor.
            params = GecHybridParams(
                k=intent.grid_side_length, c=intent.concentration,
                o=intent.express_channel_groups_per_dimension,
                d=intent.destinations_per_express_channel,
                num_vcs=2 * intent.destinations_per_express_channel)
            return gec_hybrid_route_for_topology(params, topology)
        # A shared wire has no single destination, so the v2 realization —
        # one channel id per (class, src, dst) — cannot describe a hop over
        # it. Fabrics whose rule has been derived and differentially
        # qualified against the simulator get a v3 route instead; anything
        # else is still refused rather than approximated.
        v3 = _derive_shared_resource_route(request=request, topology=topology,
                                           family=family, shared=shared)
        if v3 is not None:
            return v3
        raise RouteArtifactError(
            f"UNSUPPORTED: the topology declares {len(shared)} shared "
            f"wire(s) (a bus) and family "
            f"{getattr(family, 'value', family)!r} has no derived, "
            "differentially-qualified shared-resource route rule. One "
            "driver feeding many contending taps is not representable as "
            "independent directed channels, so no route can be derived "
            "without inventing one")
    policy_id = routing_policy_for(topology)
    if policy_id == DOR_XY:
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
