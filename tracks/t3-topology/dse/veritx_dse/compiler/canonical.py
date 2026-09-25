"""veritx_dse.compiler.canonical — canonical candidate compiler.

One orchestration path that takes an exact ``CompileRequest``, an exact
placement (``NodeInventory`` + ``MappingArtifact``), and an **explicit
compiler-owned candidate recipe**, and mechanically derives the sealed
artifact DAG through ``ResolvedFabric``.

    CompileRequest + Inventory + Mapping + candidate recipe
            |
            v
    one orchestration path
            |
            v
    ResolvedFabric

This module compiles exactly ONE fully specified candidate. It does NOT:

    * choose a routing algorithm or deterministic vs adaptive;
    * choose VC count, VC partition, escape resources;
    * choose packet limits or router buffers;
    * derive the mapping (mapping is a candidate dimension and is supplied);
    * search, rank, score or evaluate requirements;
    * run verification or certificates;
    * lower to a backend or write any output.

Those choices are candidate semantics and must be supplied explicitly.
Candidate generation/search lives above this seam and funnels every
candidate through this exact compiler.

Terminal identity is ``ResolvedFabric.resolved_fabric_hash``. The
``CompiledFabric`` bundle returned here is orchestration transport only:
it carries no independent content hash and is not another semantic
artifact.
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any

from veritx_dse.model.address_decode import (
    AddressDecodeArtifact, derive_address_decode,
)
from veritx_dse.model.attachment import (
    AgentAttachmentArtifact, derive_attachment,
)
from veritx_dse.model.compile_model import (
    COMPILER_SEMANTICS_VERSION, CompileRequest,
)
from veritx_dse.model.fabric_artifact import (
    FabricArtifact, make_adaptive_fabric, make_deterministic_fabric,
)
from veritx_dse.model.mapping import MappingArtifact
from veritx_dse.model.packet_format import (
    PacketFormatArtifact, derive_packet_format,
)
from veritx_dse.model.placement import NodeInventory, ParallelismShape
from veritx_dse.model.resolved_fabric import (
    ResolvedFabric, make_resolved_adaptive_fabric,
    make_resolved_deterministic_fabric,
)
from veritx_dse.model.resolved_route import (
    ResolvedRouteArtifact, derive_resolved_route,
)
from veritx_dse.model.router_behavior import (
    RouterBehaviorArtifact, derive_router_behavior,
)
from veritx_dse.model.routing_materialize import materialize_route_artifact
from veritx_dse.model.routing_policy import RoutingPolicyDefinition
from veritx_dse.model.routing_realization import (
    RoutingRealizationArtifact, make_adaptive_routing_realization,
    make_deterministic_routing_realization,
)
from veritx_dse.model.routing_relation import RoutingRelationArtifact
from veritx_dse.model.routing_relation_materialize import (
    materialize_routing_relation,
)
from veritx_dse.model.routing_resource_binding import (
    RoutingResourceBindingArtifact,
)
from veritx_dse.model.topology_artifact import (
    TopologyArtifact, materialize_topology,
)
from veritx_dse.model.vc_assignment import (
    VCAssignmentArtifact, make_vc_assignment_artifact,
)
from veritx_dse.model.vc_resource import (
    VCResourceArtifact, vc_resources_from_assignment,
)

# Presentation-only route name. Route identity excludes it.
ROUTE_ARTIFACT_NAME = "canonical_candidate"


class CompileStage(Enum):
    """Stable stage vocabulary for failure attribution."""

    INPUT = "INPUT"
    TOPOLOGY = "TOPOLOGY"
    ATTACHMENT = "ATTACHMENT"
    ROUTING = "ROUTING"
    VC = "VC"
    PACKET_FORMAT = "PACKET_FORMAT"
    ROUTER_BEHAVIOR = "ROUTER_BEHAVIOR"
    ADDRESS_DECODE = "ADDRESS_DECODE"
    ROUTING_REALIZATION = "ROUTING_REALIZATION"
    FABRIC = "FABRIC"
    RESOLVED_FABRIC = "RESOLVED_FABRIC"


class CanonicalCompileError(ValueError, SemanticError):
    """A compile stage failed; the original cause is preserved."""

    def __init__(self, stage: CompileStage, cause: str):
        self.stage = stage
        self.cause = cause
        super().__init__(f"stage={stage.value}: cause={cause}")


@contextmanager
def _stage(stage: CompileStage):
    """Attribute any semantic ValueError to a stable compile stage."""
    try:
        yield
    except CanonicalCompileError:
        raise
    except ValueError as exc:
        raise CanonicalCompileError(stage, str(exc)) from exc


# ── strict input helpers (shape only; children own semantic legality) ──────

def _as_int(name: str, value: Any) -> int:
    if type(value) is not int:
        raise CanonicalCompileError(
            CompileStage.INPUT,
            f"{name} must be an exact int, got {type(value).__name__}")
    return value


def _as_positive_int(name: str, value: Any) -> int:
    value = _as_int(name, value)
    if value < 1:
        raise CanonicalCompileError(
            CompileStage.INPUT, f"{name} must be >= 1, got {value}")
    return value


def _as_str(name: str, value: Any, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not allow_empty):
        raise CanonicalCompileError(
            CompileStage.INPUT, f"{name} must be a non-empty string")
    return value


def _normalize_int_tuple(name: str, value: Any, *,
                         allow_empty: bool) -> tuple[int, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (tuple, list)):
        raise CanonicalCompileError(
            CompileStage.INPUT, f"{name} must be a sequence of ints")
    values = tuple(_as_int(f"{name} entry", entry) for entry in value)
    if not values and not allow_empty:
        raise CanonicalCompileError(
            CompileStage.INPUT, f"{name} must be non-empty")
    return values


def _normalize_traffic_pairs(
        name: str, value: Any) -> tuple[tuple[str, tuple[int, ...]], ...]:
    items = _as_pair_items(name, value, allow_empty=False)
    rows: list[tuple[str, tuple[int, ...]]] = []
    seen: set[str] = set()
    for item in items:
        cls = _as_str(f"{name} class name", item[0])
        if cls in seen:
            raise CanonicalCompileError(
                CompileStage.INPUT, f"{name} has duplicate class {cls!r}")
        seen.add(cls)
        vcs = _normalize_int_tuple(f"{name} VCs for {cls!r}", item[1],
                                   allow_empty=False)
        rows.append((cls, vcs))
    rows.sort(key=lambda row: row[0])
    return tuple(rows)


def _normalize_vc_class_pairs(
        name: str, value: Any) -> tuple[tuple[int, str], ...]:
    items = _as_pair_items(name, value)
    rows: list[tuple[int, str]] = []
    seen: set[int] = set()
    for item in items:
        vc = _as_int(f"{name} VC", item[0])
        if vc in seen:
            raise CanonicalCompileError(
                CompileStage.INPUT, f"{name} has duplicate VC {vc}")
        seen.add(vc)
        rows.append((vc, _as_str(f"{name} routing class", item[1])))
    rows.sort(key=lambda row: row[0])
    return tuple(rows)


def _normalize_int_pairs(name: str, value: Any, *,
                         allow_empty: bool) -> tuple[tuple[int, int], ...]:
    items = _as_pair_items(name, value, allow_empty=allow_empty)
    rows = [(_as_int(f"{name} source", item[0]),
             _as_int(f"{name} target", item[1])) for item in items]
    return tuple(sorted(rows))


def _normalize_role_pairs(
        name: str, value: Any) -> tuple[tuple[str, tuple[int, ...]], ...]:
    items = _as_pair_items(name, value)
    rows: list[tuple[str, tuple[int, ...]]] = []
    seen: set[str] = set()
    for item in items:
        role = _as_str(f"{name} role id", item[0])
        if role in seen:
            raise CanonicalCompileError(
                CompileStage.INPUT, f"{name} has duplicate role {role!r}")
        seen.add(role)
        vcs = _normalize_int_tuple(f"{name} VCs for {role!r}", item[1],
                                   allow_empty=False)
        rows.append((role, vcs))
    rows.sort(key=lambda row: row[0])
    return tuple(rows)


def _as_pair_items(name: str, value: Any, *,
                   allow_empty: bool = True) -> list[Any]:
    if isinstance(value, Mapping):
        items = list(value.items())
    elif isinstance(value, (tuple, list)):
        items = list(value)
    else:
        raise CanonicalCompileError(
            CompileStage.INPUT,
            f"{name} must be a mapping or a sequence of pairs")
    if not items and not allow_empty:
        raise CanonicalCompileError(
            CompileStage.INPUT, f"{name} must be non-empty")
    for item in items:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise CanonicalCompileError(
                CompileStage.INPUT, f"{name} entries must be pairs")
    return items


def _require_instance(name: str, value: Any, cls: type) -> None:
    if not isinstance(value, cls):
        raise CanonicalCompileError(
            CompileStage.INPUT,
            f"{name} must be a {cls.__name__}, got {type(value).__name__}")


# ── candidate recipe value objects (compiler inputs, not artifacts) ────────

@dataclass(frozen=True)
class FabricCompileSettings:
    """Compiler-owned hardware choices not currently design intent."""

    max_packet_flits: int
    input_buffer_depth_flits_per_vc: int
    output_stage_depth_flits_per_vc: int

    def __post_init__(self):
        object.__setattr__(
            self, "max_packet_flits",
            _as_positive_int("max_packet_flits", self.max_packet_flits))
        object.__setattr__(
            self, "input_buffer_depth_flits_per_vc",
            _as_positive_int("input_buffer_depth_flits_per_vc",
                             self.input_buffer_depth_flits_per_vc))
        object.__setattr__(
            self, "output_stage_depth_flits_per_vc",
            _as_positive_int("output_stage_depth_flits_per_vc",
                             self.output_stage_depth_flits_per_vc))


@dataclass(frozen=True)
class DeterministicVCSpec:
    """Explicit deterministic VC semantics; every field is required."""

    vc_count: int
    traffic_class_to_vcs: Any
    vc_to_routing_class: Any
    allowed_transitions: Any
    escape_vcs: Any
    derivation: str

    def __post_init__(self):
        object.__setattr__(self, "vc_count",
                           _as_positive_int("vc_count", self.vc_count))
        object.__setattr__(
            self, "traffic_class_to_vcs",
            _normalize_traffic_pairs("traffic_class_to_vcs",
                                     self.traffic_class_to_vcs))
        object.__setattr__(
            self, "vc_to_routing_class",
            _normalize_vc_class_pairs("vc_to_routing_class",
                                      self.vc_to_routing_class))
        object.__setattr__(
            self, "allowed_transitions",
            _normalize_int_pairs("allowed_transitions",
                                 self.allowed_transitions, allow_empty=True))
        object.__setattr__(
            self, "escape_vcs",
            _normalize_int_tuple("escape_vcs", self.escape_vcs,
                                 allow_empty=True))
        object.__setattr__(self, "derivation",
                           _as_str("derivation", self.derivation,
                                   allow_empty=True))


@dataclass(frozen=True)
class VCResourceSpec:
    """Explicit adaptive VC resource universe (no routing-role labels)."""

    vc_count: int
    traffic_class_to_vcs: Any
    allowed_transitions: Any
    derivation: str

    def __post_init__(self):
        object.__setattr__(self, "vc_count",
                           _as_positive_int("vc_count", self.vc_count))
        object.__setattr__(
            self, "traffic_class_to_vcs",
            _normalize_traffic_pairs("traffic_class_to_vcs",
                                     self.traffic_class_to_vcs))
        object.__setattr__(
            self, "allowed_transitions",
            _normalize_int_pairs("allowed_transitions",
                                 self.allowed_transitions, allow_empty=True))
        object.__setattr__(self, "derivation",
                           _as_str("derivation", self.derivation,
                                   allow_empty=True))


@dataclass(frozen=True)
class RoutingRoleBindingSpec:
    """Explicit routing-role -> VC partition for adaptive candidates."""

    role_to_vcs: Any

    def __post_init__(self):
        object.__setattr__(
            self, "role_to_vcs",
            _normalize_role_pairs("role_to_vcs", self.role_to_vcs))


# ── compiled result bundle (transport only; no independent hash) ──────────

@dataclass(frozen=True)
class CompiledDeterministicRouting:
    """Branch-specific children of a deterministic compile."""

    route: RouteArtifact
    resolved_route: ResolvedRouteArtifact
    vc_assignment: VCAssignmentArtifact


@dataclass(frozen=True)
class CompiledAdaptiveRouting:
    """Branch-specific children of an adaptive compile."""

    routing_relation: RoutingRelationArtifact
    routing_resource_binding: RoutingResourceBindingArtifact


@dataclass(frozen=True)
class CompiledFabric:
    """Every canonical object produced by one candidate compile."""

    design: CompileRequest
    inventory: NodeInventory
    mapping: MappingArtifact
    topology: TopologyArtifact
    attachment: AgentAttachmentArtifact
    vc_resource: VCResourceArtifact
    routing_realization: RoutingRealizationArtifact
    packet_format: PacketFormatArtifact
    router_behavior: RouterBehaviorArtifact
    address_decode: AddressDecodeArtifact
    fabric: FabricArtifact
    resolved_fabric: ResolvedFabric
    routing: CompiledDeterministicRouting | CompiledAdaptiveRouting


# ── shared orchestration helpers ──────────────────────────────────────────

def _validate_inputs(*, design: CompileRequest, inventory: NodeInventory,
                     mapping: MappingArtifact,
                     routing_policy: RoutingPolicyDefinition) -> None:
    _require_instance("design", design, CompileRequest)
    _require_instance("inventory", inventory, NodeInventory)
    _require_instance("mapping", mapping, MappingArtifact)
    _require_instance("routing_policy", routing_policy,
                      RoutingPolicyDefinition)
    if design.compiler_semantics_version != COMPILER_SEMANTICS_VERSION:
        raise CanonicalCompileError(
            CompileStage.INPUT,
            f"unsupported compiler_semantics_version "
            f"{design.compiler_semantics_version!r} (this build implements "
            f"{COMPILER_SEMANTICS_VERSION})")
    shape = ParallelismShape(
        tp=design.workload.tp, pp=design.workload.pp,
        ep=design.workload.ep, dp=design.workload.dp)
    if inventory.parallelism != shape:
        raise CanonicalCompileError(
            CompileStage.INPUT,
            f"inventory parallelism {inventory.parallelism.to_dict()} does "
            f"not match design geometry {shape.to_dict()}")
    if mapping.rank_count != inventory.rank_count:
        raise CanonicalCompileError(
            CompileStage.INPUT,
            f"mapping rank_count {mapping.rank_count} != inventory "
            f"rank_count {inventory.rank_count}")
    if tuple(placement.rank for placement in mapping.placements) \
            != tuple(rank.rank for rank in inventory.ranks):
        raise CanonicalCompileError(
            CompileStage.INPUT,
            "mapping does not place exactly the inventory rank sequence")


def _derive_common_hardware(
        *, design: CompileRequest, topology: TopologyArtifact,
        attachment: AgentAttachmentArtifact, vc_resource: VCResourceArtifact,
        settings: FabricCompileSettings
) -> tuple[PacketFormatArtifact, RouterBehaviorArtifact,
           AddressDecodeArtifact]:
    with _stage(CompileStage.PACKET_FORMAT):
        packet_format = derive_packet_format(
            topology, attachment, vc_resource,
            max_packet_flits=settings.max_packet_flits)
    with _stage(CompileStage.ROUTER_BEHAVIOR):
        router_behavior = derive_router_behavior(
            vc_resource=vc_resource,
            arbitration=design.noc_config.arbitration,
            buffer_depth_flits=settings.input_buffer_depth_flits_per_vc,
            output_stage_depth_flits=settings.output_stage_depth_flits_per_vc)
    with _stage(CompileStage.ADDRESS_DECODE):
        address_decode = derive_address_decode(design=design,
                                               attachment=attachment)
    return packet_format, router_behavior, address_decode


# ── deterministic candidate compiler ──────────────────────────────────────

def compose_deterministic_candidate(
        *, design: CompileRequest, inventory: NodeInventory,
        mapping: MappingArtifact, topology: TopologyArtifact,
        attachment: AgentAttachmentArtifact, route: RouteArtifact,
        resolved_route: ResolvedRouteArtifact,
        vc_assignment: VCAssignmentArtifact,
        settings: FabricCompileSettings) -> CompiledFabric:
    """THE one deterministic derivation engine (C2.1).

    Given explicit candidate semantics — the route, resolved route and VC
    assignment (which V2 and V3 may obtain by different intent
    interpretation) — compose every downstream artifact and the terminal
    ``ResolvedFabric``. Both ``compile_deterministic_candidate`` and the v3
    orchestration entry call THIS function; no second sequencer exists.
    """
    _require_instance("vc_assignment", vc_assignment, VCAssignmentArtifact)
    _require_instance("settings", settings, FabricCompileSettings)

    with _stage(CompileStage.VC):
        vc_resource = vc_resources_from_assignment(vc_assignment)
    with _stage(CompileStage.ROUTING_REALIZATION):
        routing_realization = make_deterministic_routing_realization(
            topology=topology, attachment=attachment, route=route,
            resolved_route=resolved_route, vc_assignment=vc_assignment,
            vc_resource=vc_resource)
    packet_format, router_behavior, address_decode = _derive_common_hardware(
        design=design, topology=topology, attachment=attachment,
        vc_resource=vc_resource, settings=settings)
    with _stage(CompileStage.FABRIC):
        fabric = make_deterministic_fabric(
            topology=topology, attachment=attachment, vc_resource=vc_resource,
            routing_realization=routing_realization,
            packet_format=packet_format, router_behavior=router_behavior,
            address_decode=address_decode, route=route,
            resolved_route=resolved_route, vc_assignment=vc_assignment)
    with _stage(CompileStage.RESOLVED_FABRIC):
        resolved_fabric = make_resolved_deterministic_fabric(
            design=design, inventory=inventory, mapping=mapping,
            topology=topology, attachment=attachment, vc_resource=vc_resource,
            routing_realization=routing_realization,
            packet_format=packet_format, router_behavior=router_behavior,
            address_decode=address_decode, fabric=fabric, route=route,
            resolved_route=resolved_route, vc_assignment=vc_assignment)
    return CompiledFabric(
        design=design, inventory=inventory, mapping=mapping, topology=topology,
        attachment=attachment, vc_resource=vc_resource,
        routing_realization=routing_realization, packet_format=packet_format,
        router_behavior=router_behavior, address_decode=address_decode,
        fabric=fabric, resolved_fabric=resolved_fabric,
        routing=CompiledDeterministicRouting(
            route=route, resolved_route=resolved_route,
            vc_assignment=vc_assignment))


def compile_deterministic_candidate(
        *, design: CompileRequest, inventory: NodeInventory,
        mapping: MappingArtifact, routing_policy: RoutingPolicyDefinition,
        vc_spec: DeterministicVCSpec,
        settings: FabricCompileSettings) -> CompiledFabric:
    """Compile one fully specified deterministic candidate."""
    _validate_inputs(design=design, inventory=inventory, mapping=mapping,
                     routing_policy=routing_policy)
    _require_instance("vc_spec", vc_spec, DeterministicVCSpec)
    _require_instance("settings", settings, FabricCompileSettings)

    with _stage(CompileStage.TOPOLOGY):
        topology = materialize_topology(inventory, design)
    with _stage(CompileStage.ATTACHMENT):
        attachment = derive_attachment(design=design, inventory=inventory,
                                       topology=topology)
    with _stage(CompileStage.ROUTING):
        route = materialize_route_artifact(routing_policy, topology,
                                           name=ROUTE_ARTIFACT_NAME)
        resolved_route = derive_resolved_route(topology, attachment, route)
    with _stage(CompileStage.VC):
        vc_assignment = make_vc_assignment_artifact(
            resolved_route=resolved_route,
            vc_count=vc_spec.vc_count,
            traffic_class_to_vcs=vc_spec.traffic_class_to_vcs,
            vc_to_routing_class=vc_spec.vc_to_routing_class,
            allowed_transitions=vc_spec.allowed_transitions,
            escape_vcs=vc_spec.escape_vcs,
            derivation=vc_spec.derivation)
    return compose_deterministic_candidate(
        design=design, inventory=inventory, mapping=mapping,
        topology=topology, attachment=attachment, route=route,
        resolved_route=resolved_route, vc_assignment=vc_assignment,
        settings=settings)


# ── adaptive candidate compiler ───────────────────────────────────────────

def compile_adaptive_candidate(
        *, design: CompileRequest, inventory: NodeInventory,
        mapping: MappingArtifact, routing_policy: RoutingPolicyDefinition,
        vc_resource_spec: VCResourceSpec,
        role_binding_spec: RoutingRoleBindingSpec,
        settings: FabricCompileSettings) -> CompiledFabric:
    """Compile one fully specified adaptive candidate."""
    _validate_inputs(design=design, inventory=inventory, mapping=mapping,
                     routing_policy=routing_policy)
    _require_instance("vc_resource_spec", vc_resource_spec, VCResourceSpec)
    _require_instance("role_binding_spec", role_binding_spec,
                      RoutingRoleBindingSpec)
    _require_instance("settings", settings, FabricCompileSettings)

    with _stage(CompileStage.TOPOLOGY):
        topology = materialize_topology(inventory, design)
    with _stage(CompileStage.ATTACHMENT):
        attachment = derive_attachment(design=design, inventory=inventory,
                                       topology=topology)
    with _stage(CompileStage.ROUTING):
        routing_relation = materialize_routing_relation(topology,
                                                        routing_policy)
    with _stage(CompileStage.VC):
        vc_resource = VCResourceArtifact(
            vc_count=vc_resource_spec.vc_count,
            vc_ids=tuple(range(vc_resource_spec.vc_count)),
            traffic_class_to_vcs=vc_resource_spec.traffic_class_to_vcs,
            allowed_transitions=vc_resource_spec.allowed_transitions,
            derivation=vc_resource_spec.derivation)
        routing_resource_binding = RoutingResourceBindingArtifact(
            policy_hash=routing_policy.policy_hash,
            vc_resource_hash=vc_resource.artifact_hash,
            role_to_vcs=role_binding_spec.role_to_vcs)
    with _stage(CompileStage.ROUTING_REALIZATION):
        routing_realization = make_adaptive_routing_realization(
            topology=topology, policy=routing_policy,
            relation=routing_relation, vc_resource=vc_resource,
            binding=routing_resource_binding)
    packet_format, router_behavior, address_decode = _derive_common_hardware(
        design=design, topology=topology, attachment=attachment,
        vc_resource=vc_resource, settings=settings)
    with _stage(CompileStage.FABRIC):
        fabric = make_adaptive_fabric(
            topology=topology, attachment=attachment, vc_resource=vc_resource,
            routing_realization=routing_realization,
            packet_format=packet_format, router_behavior=router_behavior,
            address_decode=address_decode, policy=routing_policy,
            relation=routing_relation, binding=routing_resource_binding)
    with _stage(CompileStage.RESOLVED_FABRIC):
        resolved_fabric = make_resolved_adaptive_fabric(
            design=design, inventory=inventory, mapping=mapping,
            topology=topology, attachment=attachment, vc_resource=vc_resource,
            routing_realization=routing_realization,
            packet_format=packet_format, router_behavior=router_behavior,
            address_decode=address_decode, fabric=fabric,
            policy=routing_policy, relation=routing_relation,
            binding=routing_resource_binding)
    return CompiledFabric(
        design=design, inventory=inventory, mapping=mapping, topology=topology,
        attachment=attachment, vc_resource=vc_resource,
        routing_realization=routing_realization, packet_format=packet_format,
        router_behavior=router_behavior, address_decode=address_decode,
        fabric=fabric, resolved_fabric=resolved_fabric,
        routing=CompiledAdaptiveRouting(
            routing_relation=routing_relation,
            routing_resource_binding=routing_resource_binding))
