"""veritx_dse.compiler.candidate_policy — baseline candidate generation.

The first explicit CANDIDATE GENERATION policy above the Slice-23
canonical candidate compiler. It converts a ``CompileRequest`` into an
explicit candidate plan:

    CompileRequest
          |
          v
    CANDIDATE GENERATION POLICY   (this module)
          |
          v
    explicit mapping / routing / VC / settings
          |
          v
    Slice-23 canonical compiler
          |
          v
    ResolvedFabric

Division of authority:

    candidate_policy:  "Here is a candidate worth compiling."
    canonical compiler: "Given this exact candidate, here is the
                          exact hardware."
    verifier:          "Here is what we can prove about that
                          hardware."
    evaluator:         "Here is how it performs."

This module does NOT compile, claim correctness, prove deadlock freedom,
score performance, or check backend capability. It makes one versioned
statement: ``BASELINE_DETERMINISTIC_V1`` proposes this exact candidate
for this design.

POLICY VOCABULARY

``CandidatePolicy.BASELINE_DETERMINISTIC_V1``
    The only policy implemented. It is one versioned policy, not a
    "default" and not universally preferred. It proposes DOR_XY routing,
    dependency-cycle-derived VC separation, rank-order mapping and the
    historical-baseline compile settings.

``MappingPolicy.RANK_ORDER_V1``
    The only mapping policy. Rank r maps to the r-th canonical compute
    ``AgentInstance`` via the sealed ``derive_mapping(design)``. Candidate
    generation is precisely the layer that owns this choice; Slice 23
    still receives the resulting ``MappingArtifact`` explicitly.

BASELINE_DETERMINISTIC_V1 SEMANTICS (all PROPOSALS, never theorems)

    traffic classes : sorted unique {dependency.source, dependency.target};
                      FAIL CLOSED if none (no invented "default" class)
    blocking cycles : canonical ``DependencyGraph.find_cycles()``
    cycle victims    : per cycle, member minimizing
                      (BLOCKING out-degree, class name) — deterministic,
                      lexically tie-broken, independent of traversal order
    vc_count         : 1 + len(UNIQUE victims)   [authoritative formula]
                      duplicate victims reuse their separated VC; no
                      unused VC is allocated for a duplicate cycle
    traffic class -> : every unique victim gets its own VC (VC1, VC2, ...)
    one VC           in sorted victim order; all other classes -> VC0;
                      every class maps to exactly one VC
    vc -> routing    : every VC maps to DOR_XY (no modulo, no fallback)
    transitions      : identity only  i -> i
    escape_vcs       : ()  (no escape designation)
    collectives      : FAIL CLOSED for any group_size > 1
                      (group_size == 1 consumes no fabric resource)

    No clamp exists here: a design proposing 9 VCs generates 9 VCs.
    Backend/resource capability checks belong downstream.

PROVENANCE IS NOT AUTHORITY

``DeterministicVCSpec.derivation`` records the policy version, chosen
victims and proposed count for diagnostics. Slice 8 excludes derivation
from VC identity; it never acts as semantic authority.

Dependency direction: ``semantic model <- candidate_policy <- future
application / search / DSE``. ``candidate_policy`` may construct inputs
consumed by ``canonical.py``; ``canonical.py`` must never import this
module.
"""
from __future__ import annotations

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

# Historical-baseline candidate settings (Slice-17/Slice-18 canonical
# baseline: input depth 8, output stage 1; Slice-17 deliberately has no
# default for max_packet_flits — the pinned baseline fixtures use 8).
_BASELINE_MAX_PACKET_FLITS = 8
_BASELINE_INPUT_BUFFER_DEPTH_FLITS = 8
_BASELINE_OUTPUT_STAGE_DEPTH_FLITS = 1

# The canonical Slice-10 DOR_XY execution profile this policy proposes.
_DOR_ROUTING_CLASS = "DOR_XY"


class CandidatePolicy(Enum):
    """Closed candidate-generation policy vocabulary."""

    BASELINE_DETERMINISTIC_V1 = "baseline_deterministic_v1"


class MappingPolicy(Enum):
    """Closed mapping-policy vocabulary owned by candidate generation."""

    RANK_ORDER_V1 = "rank_order_v1"


class CandidatePolicyError(ValueError):
    """Candidate generation failed closed; ``reason`` is a stable category."""

    def __init__(self, reason: str, detail: str):
        self.reason = reason
        self.detail = detail
        super().__init__(f"[{reason}] {detail}")


def _require_design(design: Any) -> CompileRequest:
    if not isinstance(design, CompileRequest):
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
            "BASELINE_DETERMINISTIC_V1 requires at least one traffic class "
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
                "BASELINE_DETERMINISTIC_V1 does not yet model "
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
    # Authoritative formula: one separated VC per UNIQUE victim. Duplicate
    # victims (two cycles separable by the same class) reuse that class's
    # VC; no unused VC is allocated from a duplicate cycle discovery.
    separated = {victim: index
                 for index, victim in enumerate(victims, start=1)}
    vc_count = 1 + len(victims)
    traffic = tuple(
        (name, (separated[name],)) if name in separated else (name, (0,))
        for name in classes)
    derivation = (
        f"candidate_policy {CandidatePolicy.BASELINE_DETERMINISTIC_V1.value}: "
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
    """One explicit candidate proposal. No independent artifact hash."""

    policy: CandidatePolicy
    inventory: NodeInventory
    mapping: MappingArtifact
    routing_policy: RoutingPolicyDefinition
    vc_spec: DeterministicVCSpec
    compile_settings: FabricCompileSettings


def generate_baseline_candidate(*,
                                design: CompileRequest) -> CandidatePlan:
    """Propose the ``BASELINE_DETERMINISTIC_V1`` candidate for a design.

    Generation only: no compilation, no proof, no evaluation. Fails closed
    when the design falls outside this policy's supported domain.
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
        policy=CandidatePolicy.BASELINE_DETERMINISTIC_V1,
        inventory=inventory,
        mapping=mapping,
        routing_policy=_dor_xy_policy(),
        vc_spec=_vc_spec(design),
        compile_settings=FabricCompileSettings(
            max_packet_flits=_BASELINE_MAX_PACKET_FLITS,
            input_buffer_depth_flits_per_vc=_BASELINE_INPUT_BUFFER_DEPTH_FLITS,
            output_stage_depth_flits_per_vc=_BASELINE_OUTPUT_STAGE_DEPTH_FLITS,
        ),
    )
