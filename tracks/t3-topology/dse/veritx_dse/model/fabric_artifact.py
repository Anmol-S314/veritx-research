"""veritx_dse.model.fabric_artifact — canonical hardware fabric identity.

``FabricArtifact`` is the single content-addressed root of one fully
resolved NoC/NI **hardware** fabric. It is composition only: it owns no
derivation algorithm and embeds no child artifact bodies. Its children are
already-resolved semantic authorities:

    TopologyArtifact
    AgentAttachmentArtifact
    VCResourceArtifact
    RoutingRealizationArtifact
    PacketFormatArtifact
    RouterBehaviorArtifact
    AddressDecodeArtifact
            |
            v
       FabricArtifact

It works identically for deterministic and adaptive routing: routing
internals are hidden behind ``routing_realization_hash`` and no
route-policy-specific field appears here.

Fabric identity answers only "is this the same hardware fabric?". It
deliberately excludes design intent, rank placement, node inventory,
verification certificates, backend configuration, runs, seeds and
provenance. Two designs that resolve to the same hardware share a fabric.

Schema v1 supports exactly one semantic plane (``PlaneComposition``).
Multi-plane hardware, clock-domain crossing and power-domain crossing are
explicitly unmodelled: they fail closed rather than being approximated.
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

from dataclasses import dataclass
from enum import Enum
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.core.route_artifact import RouteArtifact
from veritx_dse.model.address_decode import AddressDecodeArtifact
from veritx_dse.model.attachment import AgentAttachmentArtifact
from veritx_dse.model.packet_format import (
    FieldMutability, FlitFieldRole, PacketFormatArtifact,
)
from veritx_dse.model.resolved_route import ResolvedRouteArtifact
from veritx_dse.model.router_behavior import (
    InputVCPacketPolicy, RouterBehaviorArtifact, VCAllocationScope,
)
from veritx_dse.model.routing_policy import RoutingPolicyDefinition
from veritx_dse.model.routing_realization import (
    RoutingRealizationArtifact, RoutingRealizationKind,
)
from veritx_dse.model.routing_relation import RoutingRelationArtifact
from veritx_dse.model.routing_resource_binding import (
    RoutingResourceBindingArtifact,
)
from veritx_dse.model.topology_artifact import TopologyArtifact
from veritx_dse.model.vc_assignment import VCAssignmentArtifact
from veritx_dse.model.vc_resource import VCResourceArtifact

FABRIC_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/FabricArtifact"

_DEFAULT_DOMAIN = "DEFAULT"


class FabricArtifactError(ValueError, SemanticError):
    """The fabric composition is invalid or unsupported — fail closed."""


def _as_hash(name: str, value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(c not in "0123456789abcdef" for c in value):
        raise FabricArtifactError(
            f"{name} must be a 64-character lowercase hex digest")
    return value


def _require_enum(name: str, enum_cls: type[Enum], value: Any) -> None:
    if not isinstance(value, enum_cls):
        raise FabricArtifactError(
            f"{name} must be a {enum_cls.__name__}, got "
            f"{type(value).__name__}")


def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise FabricArtifactError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise FabricArtifactError(
            f"{where} has unknown fields: {sorted(unknown)}")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise FabricArtifactError(
            f"{where} is missing required field {key!r}")
    return d[key]


def _enum(name: str, enum_cls: type[Enum], value: Any) -> Enum:
    if not isinstance(value, str):
        raise FabricArtifactError(
            f"{name} must be a string enum value, got "
            f"{type(value).__name__}")
    try:
        return enum_cls(value)
    except ValueError:
        raise FabricArtifactError(
            f"unknown {name} {value!r}; known: "
            f"{[member.value for member in enum_cls]}") from None


def _require_instance(name: str, value: Any, cls: type) -> None:
    if not isinstance(value, cls):
        raise FabricArtifactError(
            f"{name} must be a {cls.__name__}, got {type(value).__name__}")


# ── vocabulary ────────────────────────────────────────────────────────────

class PlaneComposition(Enum):
    """Semantic plane composition of the fabric."""

    SINGLE_PLANE = "single_plane"


# ── the artifact ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FabricArtifact:
    """Content-addressed root over resolved hardware child identities."""

    topology_hash: str
    attachment_hash: str
    vc_resource_hash: str
    routing_realization_hash: str
    packet_format_hash: str
    router_behavior_hash: str
    address_decode_hash: str
    plane_composition: PlaneComposition
    schema_version: int = FABRIC_SCHEMA_VERSION
    fabric_hash: str = ""

    def __post_init__(self):
        for name in ("topology_hash", "attachment_hash", "vc_resource_hash",
                     "routing_realization_hash", "packet_format_hash",
                     "router_behavior_hash", "address_decode_hash"):
            _as_hash(name, getattr(self, name))
        _require_enum("plane_composition", PlaneComposition,
                      self.plane_composition)
        if self.plane_composition is not PlaneComposition.SINGLE_PLANE:
            raise FabricArtifactError(
                f"UNSUPPORTED plane composition "
                f"{self.plane_composition.value!r} in v1 (only "
                "SINGLE_PLANE; multi-plane hardware requires explicit "
                "per-plane semantics and a schema extension)")
        if type(self.schema_version) is not int or \
                self.schema_version != FABRIC_SCHEMA_VERSION:
            raise FabricArtifactError(
                f"unsupported fabric schema_version {self.schema_version!r} "
                f"(expected {FABRIC_SCHEMA_VERSION})")
        expected = self._compute_hash()
        if self.fabric_hash:
            _as_hash("fabric_hash", self.fabric_hash)
            if self.fabric_hash != expected:
                raise FabricArtifactError(
                    "fabric_hash does not match content")
        else:
            object.__setattr__(self, "fabric_hash", expected)

    # ── identity ───────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "topology_hash": self.topology_hash,
            "attachment_hash": self.attachment_hash,
            "vc_resource_hash": self.vc_resource_hash,
            "routing_realization_hash": self.routing_realization_hash,
            "packet_format_hash": self.packet_format_hash,
            "router_behavior_hash": self.router_behavior_hash,
            "address_decode_hash": self.address_decode_hash,
            "plane_composition": self.plane_composition.value,
        }

    def _compute_hash(self) -> str:
        return content_id(f"{_HASH_TYPE_TAG}/v{self.schema_version}",
                          self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["fabric_hash"] = self._compute_hash()
        return d

    # ── persisted parsing (validate, never repair) ─────────────────────
    @classmethod
    def from_dict(cls, d: Any) -> "FabricArtifact":
        allowed = frozenset({
            "type", "schema_version", "topology_hash", "attachment_hash",
            "vc_resource_hash", "routing_realization_hash",
            "packet_format_hash", "router_behavior_hash",
            "address_decode_hash", "plane_composition", "fabric_hash",
        })
        _strict_keys(d, allowed, "fabric")
        if _need(d, "type", "fabric") != _HASH_TYPE_TAG:
            raise FabricArtifactError(
                f"fabric type must be {_HASH_TYPE_TAG!r}, got "
                f"{d.get('type')!r}")
        fabric_hash = _need(d, "fabric_hash", "fabric")
        _as_hash("fabric_hash", fabric_hash)
        return cls(
            topology_hash=_need(d, "topology_hash", "fabric"),
            attachment_hash=_need(d, "attachment_hash", "fabric"),
            vc_resource_hash=_need(d, "vc_resource_hash", "fabric"),
            routing_realization_hash=_need(d, "routing_realization_hash",
                                           "fabric"),
            packet_format_hash=_need(d, "packet_format_hash", "fabric"),
            router_behavior_hash=_need(d, "router_behavior_hash", "fabric"),
            address_decode_hash=_need(d, "address_decode_hash", "fabric"),
            plane_composition=_enum(
                "plane composition", PlaneComposition,
                _need(d, "plane_composition", "fabric")),
            schema_version=_need(d, "schema_version", "fabric"),
            fabric_hash=fabric_hash,
        )

    # ── common hardware DAG ────────────────────────────────────────────
    def _validate_common(
            self, *, topology: TopologyArtifact,
            attachment: AgentAttachmentArtifact,
            vc_resource: VCResourceArtifact,
            routing_realization: RoutingRealizationArtifact,
            packet_format: PacketFormatArtifact,
            router_behavior: RouterBehaviorArtifact,
            address_decode: AddressDecodeArtifact) -> None:
        """Prove the shared child DAG for both routing branches."""
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

        # 1. every root hash exactly equals the supplied child hash
        roots = (
            ("topology_hash", self.topology_hash, topology.topology_hash()),
            ("attachment_hash", self.attachment_hash,
             attachment.attachment_hash()),
            ("vc_resource_hash", self.vc_resource_hash,
             vc_resource.artifact_hash),
            ("routing_realization_hash", self.routing_realization_hash,
             routing_realization.routing_realization_hash),
            ("packet_format_hash", self.packet_format_hash,
             packet_format.packet_format_hash),
            ("router_behavior_hash", self.router_behavior_hash,
             router_behavior.router_behavior_hash),
            ("address_decode_hash", self.address_decode_hash,
             address_decode.address_decode_hash),
        )
        for name, root, child in roots:
            if root != child:
                raise FabricArtifactError(
                    f"{name} does not match the supplied child artifact")

        # 2. explicit cross-child seam coherence (do not trust root strings)
        seams = (
            ("packet_format.topology_hash",
             packet_format.topology_hash, self.topology_hash),
            ("packet_format.attachment_hash",
             packet_format.attachment_hash, self.attachment_hash),
            ("packet_format.vc_resource_hash",
             packet_format.vc_resource_hash, self.vc_resource_hash),
            ("router_behavior.vc_resource_hash",
             router_behavior.vc_resource_hash, self.vc_resource_hash),
            ("address_decode.attachment_hash",
             address_decode.attachment_hash, self.attachment_hash),
            ("routing_realization.topology_hash",
             routing_realization.topology_hash, self.topology_hash),
            ("routing_realization.vc_resource_hash",
             routing_realization.vc_resource_hash, self.vc_resource_hash),
        )
        for name, actual, expected in seams:
            if actual != expected:
                raise FabricArtifactError(
                    f"broken fabric seam: {name} is {actual!r}, expected "
                    f"{expected!r}")

        # 3. attachment/topology seat legality
        try:
            attachment.validate_against_topology(topology)
        except ValueError as exc:
            raise FabricArtifactError(
                f"attachment is not legal for the topology: {exc}") from exc

        # 4. clock-domain gate (no CDC artifact exists in v1)
        clock_domains = {
            endpoint.interface.clock_domain or _DEFAULT_DOMAIN
            for endpoint in attachment.endpoints}
        if len(clock_domains) > 1:
            raise FabricArtifactError(
                "UNSUPPORTED: fabric endpoints span multiple clock domains "
                f"{sorted(clock_domains)}; FabricArtifact v1 has no "
                "clock-crossing artifact (synchronizers, asynchronous FIFOs, "
                "mesochronous behaviour or conversion latency) and refuses "
                "to model multi-clock hardware as ordinary links")

        # 5. power-domain gate (no isolation artifact exists in v1)
        power_domains = {
            endpoint.interface.power_domain or _DEFAULT_DOMAIN
            for endpoint in attachment.endpoints}
        if len(power_domains) > 1:
            raise FabricArtifactError(
                "UNSUPPORTED: fabric endpoints span multiple power domains "
                f"{sorted(power_domains)}; FabricArtifact v1 has no "
                "power-domain artifact (isolation, level shifting, "
                "power-crossing or retention semantics) and refuses to model "
                "multi-power-domain hardware as ordinary links")

        # 6. concrete VC resource universe
        if vc_resource.vc_count < 1:
            raise FabricArtifactError("vc_resource.vc_count must be >= 1")

        # 7. child semantic validation (authority stays with the child)
        try:
            packet_format.validate_against(topology, attachment, vc_resource)
        except ValueError as exc:
            raise FabricArtifactError(
                f"packet format is not legal for the fabric: {exc}") from exc
        try:
            router_behavior.validate_against(vc_resource)
        except ValueError as exc:
            raise FabricArtifactError(
                f"router behavior is not legal for the fabric: {exc}") from exc
        try:
            address_decode.validate_against_attachment(attachment)
        except ValueError as exc:
            raise FabricArtifactError(
                f"address decode is not legal for the fabric: {exc}") from exc

        # 8. packet/router structural composition seam
        roles = {field.role: field for field in packet_format.fields}
        if FlitFieldRole.FLIT_TYPE not in roles \
                or FlitFieldRole.VC_ID not in roles:
            raise FabricArtifactError(
                "packet format is missing the structural FLIT_TYPE/VC_ID "
                "roles required for router packet semantics")
        if roles[FlitFieldRole.VC_ID].mutability is not \
                FieldMutability.HOP_LOCAL:
            raise FabricArtifactError(
                "packet format VC_ID must retain HOP_LOCAL mutability")
        if router_behavior.input_vc_packet_policy is not \
                InputVCPacketPolicy.ONE_PACKET_AT_A_TIME:
            raise FabricArtifactError(
                "router behavior must retain ONE_PACKET_AT_A_TIME input VC "
                "packet policy")
        if router_behavior.vc_allocation_scope is not \
                VCAllocationScope.PACKET:
            raise FabricArtifactError(
                "router behavior must retain PACKET VC allocation scope")

        # 9. root self-integrity
        if self.fabric_hash != self._compute_hash():
            raise FabricArtifactError("fabric_hash does not match content")

    # ── deterministic branch ───────────────────────────────────────────
    def validate_against_deterministic(
            self, *, topology: TopologyArtifact,
            attachment: AgentAttachmentArtifact,
            vc_resource: VCResourceArtifact,
            routing_realization: RoutingRealizationArtifact,
            packet_format: PacketFormatArtifact,
            router_behavior: RouterBehaviorArtifact,
            address_decode: AddressDecodeArtifact,
            route: RouteArtifact,
            resolved_route: ResolvedRouteArtifact,
            vc_assignment: VCAssignmentArtifact) -> None:
        """Prove the common DAG and the deterministic routing sources."""
        self._validate_common(
            topology=topology, attachment=attachment, vc_resource=vc_resource,
            routing_realization=routing_realization,
            packet_format=packet_format, router_behavior=router_behavior,
            address_decode=address_decode)
        if routing_realization.kind is not RoutingRealizationKind.DETERMINISTIC:
            raise FabricArtifactError(
                "validate_against_deterministic requires a DETERMINISTIC "
                "routing realization; the adaptive branch must use "
                "validate_against_adaptive")
        _require_instance("route", route, RouteArtifact)
        _require_instance("resolved_route", resolved_route,
                          ResolvedRouteArtifact)
        _require_instance("vc_assignment", vc_assignment,
                          VCAssignmentArtifact)
        try:
            routing_realization.validate_against_deterministic(
                topology=topology, attachment=attachment, route=route,
                resolved_route=resolved_route, vc_assignment=vc_assignment,
                vc_resource=vc_resource)
        except ValueError as exc:
            raise FabricArtifactError(
                f"deterministic routing sources are not legal for the "
                f"fabric: {exc}") from exc

    # ── adaptive branch ────────────────────────────────────────────────
    def validate_against_adaptive(
            self, *, topology: TopologyArtifact,
            attachment: AgentAttachmentArtifact,
            vc_resource: VCResourceArtifact,
            routing_realization: RoutingRealizationArtifact,
            packet_format: PacketFormatArtifact,
            router_behavior: RouterBehaviorArtifact,
            address_decode: AddressDecodeArtifact,
            policy: RoutingPolicyDefinition,
            relation: RoutingRelationArtifact,
            binding: RoutingResourceBindingArtifact) -> None:
        """Prove the common DAG and the adaptive routing sources."""
        self._validate_common(
            topology=topology, attachment=attachment, vc_resource=vc_resource,
            routing_realization=routing_realization,
            packet_format=packet_format, router_behavior=router_behavior,
            address_decode=address_decode)
        if routing_realization.kind is not RoutingRealizationKind.ADAPTIVE:
            raise FabricArtifactError(
                "validate_against_adaptive requires an ADAPTIVE routing "
                "realization; the deterministic branch must use "
                "validate_against_deterministic")
        _require_instance("policy", policy, RoutingPolicyDefinition)
        _require_instance("relation", relation, RoutingRelationArtifact)
        _require_instance("binding", binding, RoutingResourceBindingArtifact)
        try:
            routing_realization.validate_against_adaptive(
                topology=topology, policy=policy, relation=relation,
                vc_resource=vc_resource, binding=binding)
        except ValueError as exc:
            raise FabricArtifactError(
                f"adaptive routing sources are not legal for the fabric: "
                f"{exc}") from exc


# ── builders (composition only) ───────────────────────────────────────────

def _compose(*, topology: TopologyArtifact,
             attachment: AgentAttachmentArtifact,
             vc_resource: VCResourceArtifact,
             routing_realization: RoutingRealizationArtifact,
             packet_format: PacketFormatArtifact,
             router_behavior: RouterBehaviorArtifact,
             address_decode: AddressDecodeArtifact) -> FabricArtifact:
    for name, value, cls in (
            ("topology", topology, TopologyArtifact),
            ("attachment", attachment, AgentAttachmentArtifact),
            ("vc_resource", vc_resource, VCResourceArtifact),
            ("routing_realization", routing_realization,
             RoutingRealizationArtifact),
            ("packet_format", packet_format, PacketFormatArtifact),
            ("router_behavior", router_behavior, RouterBehaviorArtifact),
            ("address_decode", address_decode, AddressDecodeArtifact)):
        _require_instance(name, value, cls)
    return FabricArtifact(
        topology_hash=topology.topology_hash(),
        attachment_hash=attachment.attachment_hash(),
        vc_resource_hash=vc_resource.artifact_hash,
        routing_realization_hash=routing_realization.routing_realization_hash,
        packet_format_hash=packet_format.packet_format_hash,
        router_behavior_hash=router_behavior.router_behavior_hash,
        address_decode_hash=address_decode.address_decode_hash,
        plane_composition=PlaneComposition.SINGLE_PLANE,
    )


def make_deterministic_fabric(
        *, topology: TopologyArtifact,
        attachment: AgentAttachmentArtifact,
        vc_resource: VCResourceArtifact,
        routing_realization: RoutingRealizationArtifact,
        packet_format: PacketFormatArtifact,
        router_behavior: RouterBehaviorArtifact,
        address_decode: AddressDecodeArtifact,
        route: RouteArtifact,
        resolved_route: ResolvedRouteArtifact,
        vc_assignment: VCAssignmentArtifact) -> FabricArtifact:
    """Compose and validate a deterministic-routing hardware fabric."""
    fabric = _compose(
        topology=topology, attachment=attachment, vc_resource=vc_resource,
        routing_realization=routing_realization, packet_format=packet_format,
        router_behavior=router_behavior, address_decode=address_decode)
    fabric.validate_against_deterministic(
        topology=topology, attachment=attachment, vc_resource=vc_resource,
        routing_realization=routing_realization, packet_format=packet_format,
        router_behavior=router_behavior, address_decode=address_decode,
        route=route, resolved_route=resolved_route,
        vc_assignment=vc_assignment)
    return fabric


def make_adaptive_fabric(
        *, topology: TopologyArtifact,
        attachment: AgentAttachmentArtifact,
        vc_resource: VCResourceArtifact,
        routing_realization: RoutingRealizationArtifact,
        packet_format: PacketFormatArtifact,
        router_behavior: RouterBehaviorArtifact,
        address_decode: AddressDecodeArtifact,
        policy: RoutingPolicyDefinition,
        relation: RoutingRelationArtifact,
        binding: RoutingResourceBindingArtifact) -> FabricArtifact:
    """Compose and validate an adaptive-routing hardware fabric."""
    fabric = _compose(
        topology=topology, attachment=attachment, vc_resource=vc_resource,
        routing_realization=routing_realization, packet_format=packet_format,
        router_behavior=router_behavior, address_decode=address_decode)
    fabric.validate_against_adaptive(
        topology=topology, attachment=attachment, vc_resource=vc_resource,
        routing_realization=routing_realization, packet_format=packet_format,
        router_behavior=router_behavior, address_decode=address_decode,
        policy=policy, relation=relation, binding=binding)
    return fabric
