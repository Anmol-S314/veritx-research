"""veritx_dse.model.attachment — AgentAttachmentArtifact (Wave B3.1, B3.1c).

B2 stops at LogicalRank -> AgentInstance. B3.1 owns the next relationship:

    AgentInstance -> Endpoint (fabric-addressable attachment) -> RouterPort

Every hardware AgentInstance attaches, compute or not, including idle
compute instances — an active LogicalRank is not required to attach an
agent. Endpoint ids are canonical fabric attachment ids assigned densely
in (router_id, port_id) order; AddressRange.target_agent_idx identifies
an Agent group and does NOT assign endpoint ids (§8).

B3.1c completes the interface authority the spec promised: an Endpoint is
not just "an agent on a seat", it also owns the immutable NI/interface
descriptor of the Agent group it was derived from:

    AgentInterfaceDescriptor
        data_width_bits
        address_width_bits
        protocol
        clock_domain
        power_domain

Parents: design_hash + topology_hash + mapping_hash. Deriving interface
semantics from the customer design makes design_hash a real parent, and
lets validation discharge the deferred B2 parent-binding obligation:

  * every AgentInstance's group_index exists in the design;
  * instance_index < group.count;
  * AgentInstance.kind == parent Agent group kind;
  * the endpoint interface descriptor equals the parent Agent group's
    data_width/addr_width/protocol/clock/power semantics;
  * every seat exists in the TopologyArtifact;
  * every MappingArtifact placement points at the SAME AgentInstance
    (full identity, not merely the same instance_id string).

v1 attachments (no design parent, no interface descriptor) are refused on
load — no silent migration.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .compile_model import AgentKind, _as_int, _as_str
from .mapping import MappingArtifact
from .placement import AgentInstance, NodeInventory
from .topology_artifact import TopologyArtifact

ATTACHMENT_SCHEMA_VERSION = 2
_HASH_TYPE_TAG = "srota/AgentAttachment"


class AttachmentError(ValueError):
    """Unprovable attachment (fail-closed, never guessed)."""


def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise AttachmentError(f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise AttachmentError(f"{where} has unknown fields: {sorted(unknown)}")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise AttachmentError(f"{where} is missing required field {key!r}")
    return d[key]


@dataclass(frozen=True)
class AgentInterfaceDescriptor:
    """Immutable interface semantics of one endpoint's parent Agent group.

    This is NI-level hardware semantics, derived from the design revision
    and owned by the attachment artifact — not inferred later from a
    backend configuration.
    """

    data_width_bits: int
    address_width_bits: int
    protocol: str
    clock_domain: str | None
    power_domain: str | None

    def __post_init__(self):
        _as_int("data_width_bits", self.data_width_bits, minimum=8)
        _as_int("address_width_bits", self.address_width_bits, minimum=8)
        _as_str("protocol", self.protocol)
        for name in ("clock_domain", "power_domain"):
            value = getattr(self, name)
            if value is not None:
                _as_str(name, value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "data_width_bits": self.data_width_bits,
            "address_width_bits": self.address_width_bits,
            "protocol": self.protocol,
            "clock_domain": self.clock_domain,
            "power_domain": self.power_domain,
        }

    @classmethod
    def from_dict(cls, d: Any) -> "AgentInterfaceDescriptor":
        _strict_keys(d, frozenset({
            "data_width_bits", "address_width_bits", "protocol",
            "clock_domain", "power_domain"}), "endpoint.interface")
        return cls(
            data_width_bits=_need(d, "data_width_bits", "endpoint.interface"),
            address_width_bits=_need(d, "address_width_bits",
                                     "endpoint.interface"),
            protocol=_need(d, "protocol", "endpoint.interface"),
            clock_domain=_need(d, "clock_domain", "endpoint.interface"),
            power_domain=_need(d, "power_domain", "endpoint.interface"),
        )


def descriptor_of_group(group: Any) -> AgentInterfaceDescriptor:
    """Interface descriptor of one CompileRequest Agent group."""
    return AgentInterfaceDescriptor(
        data_width_bits=group.data_width,
        address_width_bits=group.addr_width,
        protocol=group.protocol,
        clock_domain=group.clock_domain,
        power_domain=group.power_domain,
    )


@dataclass(frozen=True)
class Endpoint:
    """One fabric-addressable attachment: agent, seat, interface."""

    endpoint_id: int
    agent: AgentInstance
    router_id: int
    port_id: int
    interface: AgentInterfaceDescriptor

    def __post_init__(self):
        _as_int("endpoint_id", self.endpoint_id, minimum=0)
        _as_int("router_id", self.router_id, minimum=0)
        _as_int("port_id", self.port_id, minimum=0)
        if not isinstance(self.agent, AgentInstance):
            raise AttachmentError(
                f"agent must be AgentInstance, got {type(self.agent).__name__}")
        if not isinstance(self.interface, AgentInterfaceDescriptor):
            raise AttachmentError(
                f"interface must be AgentInterfaceDescriptor, got "
                f"{type(self.interface).__name__}")

    def to_dict(self) -> dict[str, Any]:
        return {"endpoint_id": self.endpoint_id, "agent": self.agent.to_dict(),
                "router_id": self.router_id, "port_id": self.port_id,
                "interface": self.interface.to_dict()}

    @classmethod
    def from_dict(cls, d: Any) -> "Endpoint":
        _strict_keys(d, frozenset({"endpoint_id", "agent", "router_id",
                                   "port_id", "interface"}), "endpoint")
        agent = _need(d, "agent", "endpoint")
        _strict_keys(agent, frozenset({"group_index", "instance_index", "kind"}),
                     "endpoint.agent")
        try:
            kind = AgentKind(_need(agent, "kind", "endpoint.agent"))
        except ValueError:
            raise AttachmentError(
                f"endpoint.agent.kind unknown: {agent.get('kind')!r}") from None
        return cls(
            endpoint_id=_need(d, "endpoint_id", "endpoint"),
            agent=AgentInstance(
                group_index=_need(agent, "group_index", "endpoint.agent"),
                instance_index=_need(agent, "instance_index", "endpoint.agent"),
                kind=kind),
            router_id=_need(d, "router_id", "endpoint"),
            port_id=_need(d, "port_id", "endpoint"),
            interface=AgentInterfaceDescriptor.from_dict(
                _need(d, "interface", "endpoint")),
        )


@dataclass(frozen=True)
class AgentAttachmentArtifact:
    design_hash: str
    topology_hash: str
    mapping_hash: str
    endpoints: tuple[Endpoint, ...]
    schema_version: int = ATTACHMENT_SCHEMA_VERSION

    def __post_init__(self):
        for name in ("design_hash", "topology_hash", "mapping_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise AttachmentError(
                    f"{name} must be a non-empty string")
        if not isinstance(self.endpoints, tuple) or not self.endpoints:
            raise AttachmentError("endpoints must be a non-empty tuple")
        if not isinstance(self.schema_version, int) or \
                self.schema_version != ATTACHMENT_SCHEMA_VERSION:
            raise AttachmentError(
                f"unsupported attachment schema_version "
                f"{self.schema_version!r} (expected "
                f"{ATTACHMENT_SCHEMA_VERSION})")
        eids = [e.endpoint_id for e in self.endpoints]
        if eids != list(range(len(eids))):
            raise AttachmentError("endpoint ids must be contiguous from 0")
        seen: set[tuple[int, int]] = set()
        seats: set[tuple[int, int]] = set()
        for e in self.endpoints:
            if not isinstance(e, Endpoint):
                raise AttachmentError(
                    f"endpoints must contain Endpoint, got {type(e).__name__}")
            coords = (e.agent.group_index, e.agent.instance_index)
            if coords in seen:
                raise AttachmentError(
                    f"duplicate agent attachment: {e.agent.instance_id}")
            seen.add(coords)
            if (e.router_id, e.port_id) in seats:
                raise AttachmentError(
                    f"duplicate seat: router {e.router_id} port {e.port_id}")
            seats.add((e.router_id, e.port_id))

    @property
    def endpoint_count(self) -> int:
        return len(self.endpoints)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "design_hash": self.design_hash,
            "topology_hash": self.topology_hash,
            "mapping_hash": self.mapping_hash,
            "endpoints": [e.to_dict() for e in self.endpoints],
        }

    def attachment_hash(self) -> str:
        from veritx_dse.core.spec import canonical_json
        body = (f"{_HASH_TYPE_TAG}/v{self.schema_version}\0"
                + canonical_json(self.canonical_dict()))
        return hashlib.sha256(body.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        d = self.canonical_dict()
        d["attachment_hash"] = self.attachment_hash()
        return d

    # ── parent legality ────────────────────────────────────────────────
    def validate_against(self, design, topology: TopologyArtifact,
                         mapping: MappingArtifact) -> None:
        """Prove design/interface/topology/mapping references are legal."""
        if not isinstance(topology, TopologyArtifact):
            raise AttachmentError("topology must be a TopologyArtifact")
        if not isinstance(mapping, MappingArtifact):
            raise AttachmentError("mapping must be a MappingArtifact")
        groups = getattr(design, "agents", None)
        if groups is None or not hasattr(design, "design_hash"):
            raise AttachmentError(
                "design must expose .agents and .design_hash()")
        if self.design_hash != design.design_hash():
            raise AttachmentError(
                "design_hash does not match the design revision")
        if self.topology_hash != topology.topology_hash():
            raise AttachmentError(
                "topology_hash does not match the materialized topology")
        if self.mapping_hash != mapping.mapping_hash():
            raise AttachmentError(
                "mapping_hash does not match the mapping artifact")
        by_router = {r.router_id: r for r in topology.routers}
        by_coords: dict[tuple[int, int], Endpoint] = {}
        for e in self.endpoints:
            by_coords[(e.agent.group_index, e.agent.instance_index)] = e
            group_index = e.agent.group_index
            if not 0 <= group_index < len(groups):
                raise AttachmentError(
                    f"endpoint {e.endpoint_id} references Agent group "
                    f"{group_index}, outside the design's "
                    f"{len(groups)} groups")
            group = groups[group_index]
            if e.agent.kind != group.kind:
                raise AttachmentError(
                    f"endpoint {e.endpoint_id} kind {e.agent.kind.value!r} "
                    f"does not match Agent group {group_index} kind "
                    f"{group.kind.value!r}")
            if not 0 <= e.agent.instance_index < group.count:
                raise AttachmentError(
                    f"endpoint {e.endpoint_id} instance_index "
                    f"{e.agent.instance_index} is outside Agent group "
                    f"{group_index} count {group.count}")
            expected = descriptor_of_group(group)
            if e.interface != expected:
                raise AttachmentError(
                    f"endpoint {e.endpoint_id} interface descriptor does "
                    f"not match Agent group {group_index}: "
                    f"{e.interface.to_dict()} != {expected.to_dict()}")
            router = by_router.get(e.router_id)
            if router is None:
                raise AttachmentError(
                    f"endpoint {e.endpoint_id} references router "
                    f"{e.router_id}, which is not in the topology")
            if not 0 <= e.port_id < router.seat_capacity:
                raise AttachmentError(
                    f"endpoint {e.endpoint_id} port {e.port_id} is outside "
                    f"router {e.router_id} seat capacity "
                    f"{router.seat_capacity}")
        for placement in mapping.placements:
            endpoint = by_coords.get(
                (placement.agent.group_index,
                 placement.agent.instance_index))
            if endpoint is None:
                raise AttachmentError(
                    f"mapping places rank {placement.rank} on "
                    f"{placement.agent.instance_id}, which is not in the "
                    "inventory/attachment")
            if endpoint.agent != placement.agent:
                raise AttachmentError(
                    f"mapping places rank {placement.rank} on "
                    f"{placement.agent}, but the attachment bound "
                    f"{endpoint.agent}")

    @classmethod
    def from_dict(cls, d: Any) -> "AgentAttachmentArtifact":
        if not isinstance(d, dict):
            raise AttachmentError(
                f"attachment must be an object, got {type(d).__name__}")
        if d.get("schema_version") == 1:
            raise AttachmentError(
                "AgentAttachmentArtifact schema v1 is refused: it has no "
                "design_hash parent and no endpoint interface descriptor; "
                "rebuild with v2 — no silent migration")
        _strict_keys(d, frozenset({
            "type", "schema_version", "design_hash", "topology_hash",
            "mapping_hash", "endpoints", "attachment_hash"}), "attachment")
        endpoints = _need(d, "endpoints", "attachment")
        if not isinstance(endpoints, list):
            raise AttachmentError("attachment.endpoints must be a list")
        artifact = cls(
            design_hash=_need(d, "design_hash", "attachment"),
            topology_hash=_need(d, "topology_hash", "attachment"),
            mapping_hash=_need(d, "mapping_hash", "attachment"),
            endpoints=tuple(Endpoint.from_dict(e) for e in endpoints),
            schema_version=_need(d, "schema_version", "attachment"),
        )
        supplied = d.get("attachment_hash")
        if supplied is None or supplied != artifact.attachment_hash():
            raise AttachmentError(
                "attachment_hash missing or does not match content")
        return artifact


def derive_attachment(inventory: NodeInventory,
                      mapping: MappingArtifact,
                      topology: TopologyArtifact,
                      design) -> AgentAttachmentArtifact:
    """Bind every hardware AgentInstance to a topology local seat.

    Baseline policy: routers in id order, seats 0..capacity-1 within each
    router, agents in canonical NodeInventory order. Deterministic, no
    optimizer.

    ``design`` is the CompileRequest the inventory was built from: the
    endpoint interface descriptor and design_hash parent come from it,
    and ``validate_against`` discharges the B2 parent-binding checks.
    """
    if not isinstance(inventory, NodeInventory):
        raise AttachmentError("inventory must be a NodeInventory")
    if not isinstance(mapping, MappingArtifact):
        raise AttachmentError("mapping must be a MappingArtifact")
    if not isinstance(topology, TopologyArtifact):
        raise AttachmentError("topology must be a TopologyArtifact")
    groups = getattr(design, "agents", None)
    if groups is None or not hasattr(design, "design_hash"):
        raise AttachmentError("design must expose .agents and .design_hash()")
    seats = [(r.router_id, s)
             for r in topology.routers
             for s in range(r.seat_capacity)]
    if len(seats) < inventory.agent_count:
        raise AttachmentError(
            f"topology has {len(seats)} seats but {inventory.agent_count} "
            "agents must attach")
    endpoints = tuple(
        Endpoint(endpoint_id=i, agent=agent, router_id=seats[i][0],
                 port_id=seats[i][1],
                 interface=descriptor_of_group(groups[agent.group_index]))
        for i, agent in enumerate(inventory.agents)
    )
    artifact = AgentAttachmentArtifact(
        design_hash=design.design_hash(),
        topology_hash=topology.topology_hash(),
        mapping_hash=mapping.mapping_hash(),
        endpoints=endpoints,
    )
    artifact.validate_against(design, topology, mapping)
    return artifact
