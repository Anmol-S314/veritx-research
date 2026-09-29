"""veritx_dse.compiler.candidate_policy — baseline candidate generation.

Rationale: docs/decisions/modules/compiler.md
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

from dataclasses import dataclass
from enum import Enum
from typing import Any

from veritx_dse.compiler.canonical import (
    DeterministicVCSpec, FabricCompileSettings,
)
from veritx_dse.model.compile_model import (
    COMPILER_SEMANTICS_VERSION, CompileRequest, DepKind,
)
from veritx_dse.model.mapping import MappingArtifact, derive_mapping
from veritx_dse.model.placement import NodeInventory, build_inventory
from veritx_dse.model.routing_policy import (
    CandidateMode, DeadlockProofObligation, DecisionScope, PathMode,
    RandomnessMode, RoutingPolicyDefinition, RoutingResourceRole,
    RoutingResourceRoleKind, SelectionLocus,
)

_BASELINE_MAX_PACKET_FLITS = 8
_BASELINE_INPUT_BUFFER_DEPTH_FLITS = 8
_BASELINE_OUTPUT_STAGE_DEPTH_FLITS = 1

BASELINE_FABRIC_SETTINGS = FabricCompileSettings(
    max_packet_flits=_BASELINE_MAX_PACKET_FLITS,
    input_buffer_depth_flits_per_vc=_BASELINE_INPUT_BUFFER_DEPTH_FLITS,
    output_stage_depth_flits_per_vc=_BASELINE_OUTPUT_STAGE_DEPTH_FLITS,
)

# The canonical Slice-10 DOR_XY execution profile this policy proposes.
_DOR_ROUTING_CLASS = "DOR_XY"


class CandidatePolicy(Enum):
    """Closed candidate-generation policy vocabulary."""

    BASELINE_DETERMINISTIC_V2 = "baseline_deterministic_v2"


class MappingPolicy(Enum):
    """Closed mapping-policy vocabulary owned by candidate generation."""

    RANK_ORDER_V1 = "rank_order_v1"


class CandidatePolicyError(ValueError, SemanticError):
    """Candidate generation failed closed; ``reason`` is a stable category."""

    def __init__(self, reason: str, detail: str):
        self.reason = reason
        self.detail = detail
        super().__init__(f"[{reason}] {detail}")


def _require_design(design: Any) -> CompileRequest:
    from veritx_dse.model.generation import is_any_compile_request
    if not is_any_compile_request(design):
        raise CandidatePolicyError(
            "INPUT",
            f"design must be a CompileRequest, got {type(design).__name__}")
    if design.compiler_semantics_version != COMPILER_SEMANTICS_VERSION:
        raise CandidatePolicyError(
            "INPUT",
            f"unsupported compiler_semantics_version "
            f"{design.compiler_semantics_version!r} (this build implements "
            f"{COMPILER_SEMANTICS_VERSION})")
    return design


def _dor_xy_policy() -> RoutingPolicyDefinition:
    """The canonical Slice-10 DOR_XY execution profile (proposal)."""
    return RoutingPolicyDefinition(
        id="dor_xy", algorithm="dimension_order", algorithm_version=1,
        path_mode=PathMode.MINIMAL, decision_scope=DecisionScope.STATIC,
        candidate_mode=CandidateMode.SINGLETON,
        selection_locus=SelectionLocus.ROUTE_COMPUTE,
        randomness=RandomnessMode.NONE,
        deadlock_proof_obligation=DeadlockProofObligation.DETERMINISTIC_CDG,
        resource_roles=(RoutingResourceRole(
            id="default", kind=RoutingResourceRoleKind.DEFAULT),),
        allowed_role_transitions=(("default", "default"),))


def _traffic_classes(design: CompileRequest) -> tuple[str, ...]:
    """Sorted unique {source, target} over every dependency kind."""
    classes = {
        name
        for dep in design.dependencies.dependencies
        for name in (dep.source, dep.target)
    }
    if not classes:
        raise CandidatePolicyError(
            "UNSUPPORTED_POLICY_DOMAIN",
            "BASELINE_DETERMINISTIC_V2 requires at least one traffic class "
            "from the design dependency graph; this design declares none, "
            "and the policy will not invent a 'default' class absent from "
            "design intent")
    return tuple(sorted(classes))


def _blocking_out_degrees(design: CompileRequest) -> dict[str, int]:
    degrees: dict[str, int] = {}
    for dep in design.dependencies.dependencies:
        if dep.kind is DepKind.BLOCKING:
            degrees[dep.source] = degrees.get(dep.source, 0) + 1
    return degrees


def _cycle_members(cycle: list[str]) -> list[str]:
    """Strip the duplicated closing node the canonical DFS appends."""
    if len(cycle) > 1 and cycle[0] == cycle[-1]:
        return list(cycle[:-1])
    return list(cycle)


def _cycle_victims(design: CompileRequest) -> tuple[str, ...]:
    """Ordered unique victims, one per cycle, by (out-degree, name).

    ORDERING and INDEPENDENT dependencies never enter here: only the
    canonical ``find_cycles()`` BLOCKING subgraph produces separation
    requirements. Victim choice never depends on traversal order.
    """
    degrees = _blocking_out_degrees(design)
    victims: set[str] = set()
    for cycle in design.dependencies.find_cycles():
        members = _cycle_members(cycle)
        victim = min(members, key=lambda name: (degrees.get(name, 0), name))
        victims.add(victim)
    return tuple(sorted(victims))


def _check_collectives(design: CompileRequest) -> None:
    for collective in design.workload.collectives:
        if collective.group_size > 1:
            raise CandidatePolicyError(
                "UNSUPPORTED_POLICY_DOMAIN",
                "BASELINE_DETERMINISTIC_V2 does not yet model "
                "collective-context VC separation; this design declares a "
                f"{collective.kind.value} collective with group_size "
                f"{collective.group_size}, which would change the proposed "
                "VC partition. Candidate-generation support for multi-rank "
                "collectives must be added explicitly before this policy "
                "may generate a candidate for such a design")


def _vc_spec(design: CompileRequest) -> DeterministicVCSpec:
    classes = _traffic_classes(design)
    _check_collectives(design)
    victims = _cycle_victims(design)
    separated = {victim: index
                 for index, victim in enumerate(victims, start=1)}
    vc_count = 1 + len(victims)
    traffic = tuple(
        (name, (separated[name],)) if name in separated else (name, (0,))
        for name in classes)
    derivation = (
        f"candidate_policy {CandidatePolicy.BASELINE_DETERMINISTIC_V2.value}: "
        f"victims={list(victims)}; proposed_vc_count={vc_count}")
    return DeterministicVCSpec(
        vc_count=vc_count,
        traffic_class_to_vcs=traffic,
        vc_to_routing_class=tuple((vc, _DOR_ROUTING_CLASS)
                                  for vc in range(vc_count)),
        allowed_transitions=tuple((vc, vc) for vc in range(vc_count)),
        escape_vcs=(),
        derivation=derivation)


@dataclass(frozen=True)
class CandidatePlan:
    """One explicit candidate proposal. No independent artifact hash.

Rationale: docs/decisions/modules/compiler.md
    """

    policy: CandidatePolicy
    mapping_policy: MappingPolicy
    inventory: NodeInventory
    mapping: MappingArtifact
    routing_policy: RoutingPolicyDefinition
    vc_spec: DeterministicVCSpec
    compile_settings: FabricCompileSettings


def generate_baseline_candidate(*,
                                design: CompileRequest) -> CandidatePlan:
    """Propose the ``BASELINE_DETERMINISTIC_V2`` candidate for a design.

    Generation only: no compilation, no proof, no evaluation. Fails closed
    when the design falls outside this policy's supported domain (legacy
    semantics-v1 designs require explicit migrate_design() first).
    """
    _require_design(design)
    try:
        inventory: NodeInventory = build_inventory(design)
        mapping: MappingArtifact = derive_mapping(design)
    except ValueError as exc:
        raise CandidatePolicyError(
            "MAPPING",
            f"rank-order mapping could not be derived for this design: "
            f"{exc}") from exc
    return CandidatePlan(
        policy=CandidatePolicy.BASELINE_DETERMINISTIC_V2,
        mapping_policy=MappingPolicy.RANK_ORDER_V1,
        inventory=inventory,
        mapping=mapping,
        routing_policy=_dor_xy_policy(),
        vc_spec=_vc_spec(design),
        compile_settings=BASELINE_FABRIC_SETTINGS,
    )
