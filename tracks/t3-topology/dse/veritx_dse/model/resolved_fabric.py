"""veritx_dse.model.resolved_fabric — design/mapping -> hardware seam.

``ResolvedFabric`` binds already-resolved design intent, logical geometry,
rank->agent mapping and the canonical hardware fabric, so those are
structurally and semantically bound to one identity. It derives nothing
and is verified against its inputs, never against requirements.

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError, require_capability

import dataclasses
from dataclasses import dataclass
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.core.route_artifact import RouteArtifact
from veritx_dse.model.address_decode import AddressDecodeArtifact
from veritx_dse.model.attachment import AgentAttachmentArtifact
from veritx_dse.model.compile_model import (
    CompileRequest, CompileRequestV3, NocConfig,
)
from veritx_dse.model.fabric_artifact import FabricArtifact
from veritx_dse.model.mapping import MappingArtifact
from veritx_dse.model.packet_format import PacketFormatArtifact
from veritx_dse.model.placement import (
    LogicalRank, NodeInventory, ParallelismShape, coords_of,
)
from veritx_dse.model.resolved_route import ResolvedRouteArtifact
from veritx_dse.model.router_behavior import (
    RouterBehaviorArtifact, canonical_allocator,
)
from veritx_dse.model.routing_policy import RoutingPolicyDefinition
from veritx_dse.model.routing_realization import RoutingRealizationArtifact
from veritx_dse.model.routing_relation import RoutingRelationArtifact
from veritx_dse.model.routing_resource_binding import (
    RoutingResourceBindingArtifact,
)
from veritx_dse.model.topology_artifact import (
    TopologyArtifact, materialize_topology,
)
from veritx_dse.model.vc_assignment import VCAssignmentArtifact
from veritx_dse.model.vc_resource import VCResourceArtifact

RESOLVED_FABRIC_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/ResolvedFabric"

NOC_FIELD_CLASSIFICATION = {
    "topology_family": "REPRESENTED",
    "radix": "REPRESENTED",
    "concentration": "REPRESENTED",
    "link_width": "REPRESENTED",
    "arbitration": "REPRESENTED",
    "output_formats": "NON_HARDWARE",
    "obfuscation_level": "NON_HARDWARE",
    "rcu_enabled": "UNSUPPORTED_V1",
    "mcast_groups": "UNSUPPORTED_V1",
    "mcast_setup_cycles": "UNSUPPORTED_V1",
}

class ResolvedFabricError(ValueError, SemanticError):
    """The resolved fabric seam is invalid or unsupported — fail closed."""

def _as_hash(name: str, value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(c not in "0123456789abcdef" for c in value):
        raise ResolvedFabricError(
            f"{name} must be a 64-character lowercase hex digest")
    return value

def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise ResolvedFabricError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise ResolvedFabricError(
            f"{where} has unknown fields: {sorted(unknown)}")

def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise ResolvedFabricError(
            f"{where} is missing required field {key!r}")
    return d[key]

def _require_design_generation(name: str, value: Any) -> None:
    """A design request of ANY generation the shared engine consumes.

    One predicate instead of a tuple that grows a disjunct per generation.
    """
    from veritx_dse.model.generation import is_any_compile_request
    if not is_any_compile_request(value):
        raise ResolvedFabricError(
            f"{name} must be a (CompileRequest, CompileRequestV3), got "
            f"{type(value).__name__}")

def _require_instance(name: str, value: Any, cls: type) -> None:
    if not isinstance(value, cls):
        names = (cls.__name__ if isinstance(cls, type)
                 else "(" + ", ".join(c.__name__ for c in cls) + ")")
        raise ResolvedFabricError(
            f"{name} must be a {names}, got {type(value).__name__}")

def noc_semantic_fields() -> set[str]:
    """The exact current NocConfig semantic field set."""
    return {field.name for field in dataclasses.fields(NocConfig)}

def check_noc_field_classification() -> None:
    """Fail closed if a NocConfig semantic field is not classified."""
    fields = noc_semantic_fields()
    if fields != set(NOC_FIELD_CLASSIFICATION):
        unclassified = sorted(fields - set(NOC_FIELD_CLASSIFICATION))
        stale = sorted(set(NOC_FIELD_CLASSIFICATION) - fields)
        raise ResolvedFabricError(
            "unclassified NocConfig semantic fields: "
            f"{unclassified} (stale classifications: {stale}); classify each "
            "as REPRESENTED, NON_HARDWARE or UNSUPPORTED_V1 before this seam "
            "may be used")

@dataclass(frozen=True)
class ResolvedFabric:
    """Design intent + mapping bound to one canonical hardware fabric."""

    design_hash: str
    mapping_hash: str
    fabric_hash: str
    schema_version: int = RESOLVED_FABRIC_SCHEMA_VERSION
    resolved_fabric_hash: str = ""

    def __post_init__(self):
        _as_hash("design_hash", self.design_hash)
        _as_hash("mapping_hash", self.mapping_hash)
        _as_hash("fabric_hash", self.fabric_hash)
        if type(self.schema_version) is not int or \
                self.schema_version != RESOLVED_FABRIC_SCHEMA_VERSION:
            raise ResolvedFabricError(
                f"unsupported resolved-fabric schema_version "
                f"{self.schema_version!r} (expected "
                f"{RESOLVED_FABRIC_SCHEMA_VERSION})")
        expected = self._compute_hash()
        if self.resolved_fabric_hash:
            _as_hash("resolved_fabric_hash", self.resolved_fabric_hash)
            if self.resolved_fabric_hash != expected:
                raise ResolvedFabricError(
                    "resolved_fabric_hash does not match content")
        else:
            object.__setattr__(self, "resolved_fabric_hash", expected)

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "design_hash": self.design_hash,
            "mapping_hash": self.mapping_hash,
            "fabric_hash": self.fabric_hash,
        }

    def _compute_hash(self) -> str:
        return content_id(f"{_HASH_TYPE_TAG}/v{self.schema_version}",
                          self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["resolved_fabric_hash"] = self._compute_hash()
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "ResolvedFabric":
        allowed = frozenset({
            "type", "schema_version", "design_hash", "mapping_hash",
            "fabric_hash", "resolved_fabric_hash",
        })
        _strict_keys(d, allowed, "resolved_fabric")
        if _need(d, "type", "resolved_fabric") != _HASH_TYPE_TAG:
            raise ResolvedFabricError(
                f"resolved fabric type must be {_HASH_TYPE_TAG!r}, got "
                f"{d.get('type')!r}")
        resolved_hash = _need(d, "resolved_fabric_hash", "resolved_fabric")
        _as_hash("resolved_fabric_hash", resolved_hash)
        return cls(
            design_hash=_need(d, "design_hash", "resolved_fabric"),
            mapping_hash=_need(d, "mapping_hash", "resolved_fabric"),
            fabric_hash=_need(d, "fabric_hash", "resolved_fabric"),
            schema_version=_need(d, "schema_version", "resolved_fabric"),
            resolved_fabric_hash=resolved_hash,
        )

    def _validate_root_hashes(self, *, design: CompileRequest | CompileRequestV3,
                              mapping: MappingArtifact,
                              fabric: FabricArtifact) -> None:
        if self.design_hash != design.design_hash():
            raise ResolvedFabricError(
                "design_hash does not match the supplied CompileRequest")
        if self.mapping_hash != mapping.mapping_hash():
            raise ResolvedFabricError(
                "mapping_hash does not match the supplied MappingArtifact")
        if self.fabric_hash != fabric.fabric_hash:
            raise ResolvedFabricError(
                "fabric_hash does not match the supplied FabricArtifact")
        if self.resolved_fabric_hash != self._compute_hash():
            raise ResolvedFabricError(
                "resolved_fabric_hash does not match content")

    def _validate_supported_intent(self, design: CompileRequest | CompileRequestV3) -> None:
        # Keep this semantic token compiler-independent: model must not
        # depend on application or compiler stage enums.
        stage = "RESOLVED_FABRIC"
        check_noc_field_classification()
        noc = design.noc_config
        # Each refusal names the capability that is missing, so the product
        # can list it as a gap instead of showing an opaque string. The
        # stage travels with the gap, so a caller that only knew
        # CanonicalCompileError.stage still finds it here.
        if noc.rcu_enabled:
            require_capability(
                "rcu_hardware",
                "UNSUPPORTED: design requests RCU (rcu_enabled=True) but no "
                "canonical RCU hardware artifact exists; refusing to compile "
                "the ordinary non-RCU fabric",
                stage=stage)
        if noc.mcast_groups is not None:
            require_capability(
                "multicast_group_hardware",
                "UNSUPPORTED: design requests a hardware multicast group "
                f"limit (mcast_groups={noc.mcast_groups}) but no canonical "
                "multicast replication/branching artifact exists; multicast "
                "is not silently reinterpreted as repeated unicast",
                stage=stage)
        if noc.mcast_setup_cycles is not None:
            require_capability(
                "multicast_setup_state",
                "UNSUPPORTED: design requests multicast setup cost "
                f"(mcast_setup_cycles={noc.mcast_setup_cycles}) but no "
                "canonical multicast setup-state artifact exists",
                stage=stage)
        if design.physical.num_power_domains > 1:
            require_capability(
                "power_isolation",
                "UNSUPPORTED: design declares "
                f"{design.physical.num_power_domains} power domains but "
                "FabricArtifact v1 has no isolation/level-shifting semantics",
                stage=stage)

    def _validate_seams(
            self, *, design: CompileRequest | CompileRequestV3, inventory: NodeInventory,
            mapping: MappingArtifact, topology: TopologyArtifact,
            attachment: AgentAttachmentArtifact,
            vc_resource: VCResourceArtifact,
            routing_realization: RoutingRealizationArtifact,
            packet_format: PacketFormatArtifact,
            router_behavior: RouterBehaviorArtifact,
            address_decode: AddressDecodeArtifact) -> None:
        _require_design_generation("design", design)
        _require_instance("inventory", inventory, NodeInventory)
        _require_instance("mapping", mapping, MappingArtifact)
        _require_instance("topology", topology, TopologyArtifact)
        _require_instance("attachment", attachment, AgentAttachmentArtifact)
        _require_instance("vc_resource", vc_resource, VCResourceArtifact)
        _require_instance("routing_realization", routing_realization,
                          RoutingRealizationArtifact)
        _require_instance("packet_format", packet_format, PacketFormatArtifact)
        _require_instance("router_behavior", router_behavior,
                          RouterBehaviorArtifact)
        _require_instance("address_decode", address_decode,
                          AddressDecodeArtifact)

        self._validate_supported_intent(design)

        shape = ParallelismShape(
            tp=design.workload.tp, pp=design.workload.pp,
            ep=design.workload.ep, dp=design.workload.dp)
        if inventory.parallelism != shape:
            raise ResolvedFabricError(
                "inventory parallelism does not match the design workload "
                f"geometry: {inventory.parallelism.to_dict()} != "
                f"{shape.to_dict()} (equal world size is not sufficient)")

        world = shape.world_size
        expected_ranks = tuple(
            LogicalRank(rank=rank,
                        **coords_of(rank, tp=shape.tp, pp=shape.pp,
                                    ep=shape.ep, dp=shape.dp))
            for rank in range(world))
        if inventory.ranks != expected_ranks:
            raise ResolvedFabricError(
                "inventory rank namespace does not match the canonical "
                "logical ranks for the design parallelism shape")

        if mapping.rank_count != inventory.rank_count:
            raise ResolvedFabricError(
                f"mapping rank_count {mapping.rank_count} != inventory "
                f"rank_count {inventory.rank_count}")
        if tuple(p.rank for p in mapping.placements) \
                != tuple(r.rank for r in inventory.ranks):
            raise ResolvedFabricError(
                "mapping does not place exactly the inventory rank sequence")
        inventory_agents = set(inventory.agents)
        for placement in mapping.placements:
            if placement.agent not in inventory_agents:
                raise ResolvedFabricError(
                    f"mapping rank {placement.rank} references agent "
                    f"{placement.agent.instance_id}, which is not in the "
                    "inventory")

        attached = {(endpoint.agent.group_index, endpoint.agent.instance_index,
                     endpoint.agent.kind)
                    for endpoint in attachment.endpoints}
        for placement in mapping.placements:
            key = (placement.agent.group_index,
                   placement.agent.instance_index, placement.agent.kind)
            if key not in attached:
                raise ResolvedFabricError(
                    f"mapping rank {placement.rank} is hosted by "
                    f"{placement.agent.instance_id}, which is not attached")

        try:
            attachment.validate_against(design, inventory, topology)
        except ValueError as exc:
            raise ResolvedFabricError(
                f"attachment does not realize the design agent universe or "
                f"interface semantics: {exc}") from exc

        try:
            address_decode.validate_against(design.address_map, attachment)
        except ValueError as exc:
            raise ResolvedFabricError(
                f"address decode does not realize the design address map: "
                f"{exc}") from exc

        try:
            expected_topology = materialize_topology(inventory, design)
        except ValueError as exc:
            raise ResolvedFabricError(
                f"design topology intent cannot be materialized: {exc}"
            ) from exc
        if topology.topology_hash() != expected_topology.topology_hash():
            raise ResolvedFabricError(
                "topology does not implement the design topology intent "
                "(exact canonical materialization differs)")

        if design.noc_config.link_width is not None \
                and packet_format.flit_width_bits \
                != design.noc_config.link_width:
            raise ResolvedFabricError(
                f"packet format flit width {packet_format.flit_width_bits} "
                f"!= design link_width {design.noc_config.link_width}")

        from veritx_dse.model.noc_controls import ROUTER_CONTROL_FIELDS
        controls = getattr(design, "noc_controls", None)
        for name in ROUTER_CONTROL_FIELDS:
            value = getattr(controls, name, None)
            if value is not None and getattr(router_behavior, name) != value:
                raise ResolvedFabricError(
                    f"router behavior {name} does not implement authored control {value}")

        allocator = canonical_allocator(design.noc_config.arbitration)
        if router_behavior.vc_allocator is not allocator \
                or router_behavior.switch_allocator is not allocator:
            raise ResolvedFabricError(
                "router behavior allocators do not implement the design "
                f"arbitration intent {design.noc_config.arbitration!r}")

    def validate_against_deterministic(
            self, *, design: CompileRequest | CompileRequestV3, inventory: NodeInventory,
            mapping: MappingArtifact, topology: TopologyArtifact,
            attachment: AgentAttachmentArtifact,
            vc_resource: VCResourceArtifact,
            routing_realization: RoutingRealizationArtifact,
            packet_format: PacketFormatArtifact,
            router_behavior: RouterBehaviorArtifact,
            address_decode: AddressDecodeArtifact,
            fabric: FabricArtifact, route: RouteArtifact,
            resolved_route: ResolvedRouteArtifact,
            vc_assignment: VCAssignmentArtifact) -> None:
        _require_instance("fabric", fabric, FabricArtifact)
        self._validate_root_hashes(design=design, mapping=mapping, fabric=fabric)
        self._validate_seams(
            design=design, inventory=inventory, mapping=mapping,
            topology=topology, attachment=attachment, vc_resource=vc_resource,
            routing_realization=routing_realization,
            packet_format=packet_format, router_behavior=router_behavior,
            address_decode=address_decode)
        try:
            fabric.validate_against_deterministic(
                topology=topology, attachment=attachment,
                vc_resource=vc_resource,
                routing_realization=routing_realization,
                packet_format=packet_format,
                router_behavior=router_behavior,
                address_decode=address_decode, route=route,
                resolved_route=resolved_route, vc_assignment=vc_assignment)
        except ValueError as exc:
            raise ResolvedFabricError(
                f"hardware fabric does not validate for the deterministic "
                f"design: {exc}") from exc

    def validate_against_adaptive(
            self, *, design: CompileRequest | CompileRequestV3, inventory: NodeInventory,
            mapping: MappingArtifact, topology: TopologyArtifact,
            attachment: AgentAttachmentArtifact,
            vc_resource: VCResourceArtifact,
            routing_realization: RoutingRealizationArtifact,
            packet_format: PacketFormatArtifact,
            router_behavior: RouterBehaviorArtifact,
            address_decode: AddressDecodeArtifact,
            fabric: FabricArtifact, policy: RoutingPolicyDefinition,
            relation: RoutingRelationArtifact,
            binding: RoutingResourceBindingArtifact) -> None:
        _require_instance("fabric", fabric, FabricArtifact)
        self._validate_root_hashes(design=design, mapping=mapping, fabric=fabric)
        self._validate_seams(
            design=design, inventory=inventory, mapping=mapping,
            topology=topology, attachment=attachment, vc_resource=vc_resource,
            routing_realization=routing_realization,
            packet_format=packet_format, router_behavior=router_behavior,
            address_decode=address_decode)
        try:
            fabric.validate_against_adaptive(
                topology=topology, attachment=attachment,
                vc_resource=vc_resource,
                routing_realization=routing_realization,
                packet_format=packet_format,
                router_behavior=router_behavior,
                address_decode=address_decode, policy=policy,
                relation=relation, binding=binding)
        except ValueError as exc:
            raise ResolvedFabricError(
                f"hardware fabric does not validate for the adaptive design: "
                f"{exc}") from exc

def _bind(*, design: CompileRequest | CompileRequestV3, mapping: MappingArtifact,
          fabric: FabricArtifact) -> ResolvedFabric:
    for name, value, cls in (("mapping", mapping, MappingArtifact),
                             ("fabric", fabric, FabricArtifact)):
        _require_instance(name, value, cls)
    _require_design_generation("design", design)
    return ResolvedFabric(
        design_hash=design.design_hash(),
        mapping_hash=mapping.mapping_hash(),
        fabric_hash=fabric.fabric_hash,
    )

def make_resolved_deterministic_fabric(
        *, design: CompileRequest | CompileRequestV3, inventory: NodeInventory,
        mapping: MappingArtifact, topology: TopologyArtifact,
        attachment: AgentAttachmentArtifact, vc_resource: VCResourceArtifact,
        routing_realization: RoutingRealizationArtifact,
        packet_format: PacketFormatArtifact,
        router_behavior: RouterBehaviorArtifact,
        address_decode: AddressDecodeArtifact, fabric: FabricArtifact,
        route: RouteArtifact, resolved_route: ResolvedRouteArtifact,
        vc_assignment: VCAssignmentArtifact) -> ResolvedFabric:
    """Bind a deterministic design/mapping to its hardware fabric."""
    resolved = _bind(design=design, mapping=mapping, fabric=fabric)
    resolved.validate_against_deterministic(
        design=design, inventory=inventory, mapping=mapping, topology=topology,
        attachment=attachment, vc_resource=vc_resource,
        routing_realization=routing_realization, packet_format=packet_format,
        router_behavior=router_behavior, address_decode=address_decode,
        fabric=fabric, route=route, resolved_route=resolved_route,
        vc_assignment=vc_assignment)
    return resolved

def make_resolved_adaptive_fabric(
        *, design: CompileRequest | CompileRequestV3, inventory: NodeInventory,
        mapping: MappingArtifact, topology: TopologyArtifact,
        attachment: AgentAttachmentArtifact, vc_resource: VCResourceArtifact,
        routing_realization: RoutingRealizationArtifact,
        packet_format: PacketFormatArtifact,
        router_behavior: RouterBehaviorArtifact,
        address_decode: AddressDecodeArtifact, fabric: FabricArtifact,
        policy: RoutingPolicyDefinition, relation: RoutingRelationArtifact,
        binding: RoutingResourceBindingArtifact) -> ResolvedFabric:
    """Bind an adaptive design/mapping to its hardware fabric."""
    resolved = _bind(design=design, mapping=mapping, fabric=fabric)
    resolved.validate_against_adaptive(
        design=design, inventory=inventory, mapping=mapping, topology=topology,
        attachment=attachment, vc_resource=vc_resource,
        routing_realization=routing_realization, packet_format=packet_format,
        router_behavior=router_behavior, address_decode=address_decode,
        fabric=fabric, policy=policy, relation=relation, binding=binding)
    return resolved

def make_resolved_fabric(*, design, inventory,
                         mapping,
                         topology,
                         attachment,
                         router_route,
                         resolved_route,
                         vc_assignment,
                         packet_format,
                         router_behavior,
                         address_decode,
                         fabric) -> ResolvedFabric:
    """Bind design + mapping to an already-composed FabricArtifact (RT seam).

Rationale: docs/decisions/modules/model.md
    """
    return ResolvedFabric(
        design_hash=design.design_hash(),
        mapping_hash=mapping.mapping_hash(),
        fabric_hash=fabric.fabric_hash,
    )
