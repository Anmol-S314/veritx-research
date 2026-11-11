"""veritx_dse.model.attachment — AgentAttachmentArtifact (B3.1, B3.1c, B3.1d).

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

from dataclasses import dataclass
from typing import Any

from .compile_model import AgentKind, _as_int, _as_str
from .placement import AgentInstance, NodeInventory
from .topology_artifact import TopologyArtifact

ATTACHMENT_SCHEMA_VERSION = 3
_HASH_TYPE_TAG = "srota/AgentAttachment"

class AttachmentError(ValueError, SemanticError):
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

Rationale: docs/decisions/modules/model.md
    """

    data_width_bits: int
    address_width_bits: int
    protocol: str
    clock_domain: str | None
    power_domain: str | None

    def __post_init__(self):
        _as_int("data_width_bits", self.data_width_bits, minimum=8)
        _as_int("address_width_bits", self.address_width_bits, minimum=8)
        _as_str("protocol", self.protocol, allow_empty=False)
        for name in ("clock_domain", "power_domain"):
            value = getattr(self, name)
            if value is not None:
                _as_str(name, value, allow_empty=False)

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
    """One fabric-addressable attachment: agent, seat, interface.

    `router_id`/`port_id` are the INGRESS location: where this agent's
    traffic enters the fabric. A fabric whose terminals eject somewhere else
    (the multi-stage Fly) also declares the EGRESS location, which is a
    different router and/or port. `None` means "the ingress seat also
    ejects", which is what every pre-existing fabric means, so the
    serialized bytes and hash of every existing attachment are unchanged.
    """

    endpoint_id: int
    agent: AgentInstance
    router_id: int
    port_id: int
    interface: AgentInterfaceDescriptor
    egress_router_id: int | None = None
    egress_port_id: int | None = None
    group_name: str | None = None

    def __post_init__(self):
        _as_int("endpoint_id", self.endpoint_id, minimum=0)
        _as_int("router_id", self.router_id, minimum=0)
        _as_int("port_id", self.port_id, minimum=0)
        if self.group_name is not None:
            _as_str("group_name", self.group_name, allow_empty=False)
            if not all(ch.isalnum() or ch in "-_" for ch in self.group_name):
                raise AttachmentError("group_name must be alphanumeric plus hyphen and underscore")
        if (self.egress_router_id is None) != (self.egress_port_id is None):
            raise AttachmentError(
                "an endpoint must declare egress_router_id AND egress_port_id "
                "together, or neither (neither means the ingress seat ejects)")
        if self.egress_router_id is not None:
            _as_int("egress_router_id", self.egress_router_id, minimum=0)
            _as_int("egress_port_id", self.egress_port_id, minimum=0)
        if not isinstance(self.agent, AgentInstance):
            raise AttachmentError(
                f"agent must be AgentInstance, got {type(self.agent).__name__}")
        if not isinstance(self.interface, AgentInterfaceDescriptor):
            raise AttachmentError(
                f"interface must be AgentInterfaceDescriptor, got "
                f"{type(self.interface).__name__}")

    @property
    def symmetric(self) -> bool:
        """Whether this agent injects and ejects through the same seat."""
        return self.egress_router_id is None

    def ingress_location(self) -> tuple[int, int]:
        return self.router_id, self.port_id

    def egress_location(self) -> tuple[int, int]:
        if self.egress_router_id is None:
            return self.router_id, self.port_id
        return self.egress_router_id, self.egress_port_id

    def to_dict(self) -> dict[str, Any]:
        d = {"endpoint_id": self.endpoint_id, "agent": self.agent.to_dict(),
             "router_id": self.router_id, "port_id": self.port_id,
             "interface": self.interface.to_dict()}
        # Unnamed legacy attachments retain their exact bytes and identity.
        if self.group_name is not None:
            d["group_name"] = self.group_name
        if self.egress_router_id is not None:
            # Emitted ONLY for an asymmetric attachment, so every symmetric
            # attachment keeps its exact old bytes and hash.
            d["egress"] = {"router_id": self.egress_router_id,
                           "port_id": self.egress_port_id}
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "Endpoint":
        _strict_keys(d, frozenset({"endpoint_id", "agent", "router_id",
                                   "port_id", "interface", "egress", "group_name"}),
                     "endpoint")
        egress = d.get("egress")
        if egress is not None:
            _strict_keys(egress, frozenset({"router_id", "port_id"}),
                         "endpoint.egress")
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
            group_name=d.get("group_name"),
            agent=AgentInstance(
                group_index=_need(agent, "group_index", "endpoint.agent"),
                instance_index=_need(agent, "instance_index", "endpoint.agent"),
                kind=kind),
            router_id=_need(d, "router_id", "endpoint"),
            port_id=_need(d, "port_id", "endpoint"),
            interface=AgentInterfaceDescriptor.from_dict(
                _need(d, "interface", "endpoint")),
            egress_router_id=(None if egress is None
                              else _need(egress, "router_id",
                                         "endpoint.egress")),
            egress_port_id=(None if egress is None
                            else _need(egress, "port_id", "endpoint.egress")),
        )

def _expected_universe(design) -> set[tuple[int, int, AgentKind]]:
    groups = getattr(design, "agents", None)
    if groups is None:
        raise AttachmentError("design must expose .agents")
    return {(group_index, instance_index, group.kind)
            for group_index, group in enumerate(groups)
            for instance_index in range(group.count)}

def _inventory_universe(inventory: NodeInventory) -> set[tuple[int, int, AgentKind]]:
    return {(a.group_index, a.instance_index, a.kind)
            for a in inventory.agents}

def _format_delta(name: str, missing: set, extra: set) -> str:
    parts = []
    if missing:
        parts.append(f"missing {len(missing)}: {sorted(missing, key=str)[:3]}")
    if extra:
        parts.append(f"extra {len(extra)}: {sorted(extra, key=str)[:3]}")
    return f"{name} does not match the design agent universe ({'; '.join(parts)})"

@dataclass(frozen=True)
class AgentAttachmentArtifact:
    """Hardware attachment identity: topology seats + agent interfaces.

Rationale: docs/decisions/modules/model.md
    """

    topology_hash: str
    endpoints: tuple[Endpoint, ...]
    schema_version: int = ATTACHMENT_SCHEMA_VERSION

    def __post_init__(self):
        if not isinstance(self.topology_hash, str) or not self.topology_hash:
            raise AttachmentError("topology_hash must be a non-empty string")
        if not isinstance(self.endpoints, tuple) or not self.endpoints:
            raise AttachmentError("endpoints must be a non-empty tuple")
        if not isinstance(self.schema_version, int) or \
                self.schema_version != ATTACHMENT_SCHEMA_VERSION:
            raise AttachmentError(
                f"unsupported attachment schema_version "
                f"{self.schema_version!r} (expected "
                f"{ATTACHMENT_SCHEMA_VERSION})")
        for e in self.endpoints:
            if not isinstance(e, Endpoint):
                raise AttachmentError(
                    f"endpoints must contain Endpoint, got {type(e).__name__}")
        eids = [e.endpoint_id for e in self.endpoints]
        if eids != list(range(len(eids))):
            raise AttachmentError("endpoint ids must be contiguous from 0")
        seen: set[tuple[int, int]] = set()
        seats: set[tuple[int, int]] = set()
        names: dict[int, str | None] = {}
        for e in self.endpoints:
            index = e.agent.group_index
            if index in names and names[index] != e.group_name:
                raise AttachmentError("inconsistent group_name within Agent group")
            names[index] = e.group_name
            coords = (e.agent.group_index, e.agent.instance_index)
            if coords in seen:
                raise AttachmentError(
                    f"duplicate agent attachment: {e.agent.instance_id}")
            seen.add(coords)
            if (e.router_id, e.port_id) in seats:
                raise AttachmentError(
                    f"duplicate seat: router {e.router_id} port {e.port_id}")
            seats.add((e.router_id, e.port_id))
        if any(name is not None for name in names.values()):
            if None in names.values() or len(set(names.values())) != len(names):
                raise AttachmentError("group_name must be unique and declared for every Agent group")
        if any(not e.symmetric for e in self.endpoints) \
                and not all(not e.symmetric for e in self.endpoints):
            # A mixed attachment would make "does this endpoint eject here?"
            # mean two things in one artifact; refuse instead of inferring.
            raise AttachmentError(
                "an attachment is either symmetric everywhere or declares an "
                "egress location for every endpoint")
        if not self.endpoints[0].symmetric:
            egress: set[tuple[int, int]] = set()
            for e in self.endpoints:
                loc = e.egress_location()
                if loc in egress:
                    raise AttachmentError(
                        f"duplicate egress seat: router {loc[0]} port "
                        f"{loc[1]}")
                egress.add(loc)

    @property
    def endpoint_count(self) -> int:
        return len(self.endpoints)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "topology_hash": self.topology_hash,
            "endpoints": [e.to_dict() for e in self.endpoints],
        }

    def attachment_hash(self) -> str:
        from veritx_dse.core.artifact import content_id
        return content_id(f"{_HASH_TYPE_TAG}/v{self.schema_version}",
                          self.canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        d = self.canonical_dict()
        d["attachment_hash"] = self.attachment_hash()
        return d

    def validate_against_topology(self,
                                  topology: TopologyArtifact) -> None:
        """Prove hardware-local attachment legality (no design context).

        This is the helper FabricArtifact uses: it proves only what the
        topology alone can prove — router existence, seat capacity and
        at-most-once seat occupancy. It must not require DesignRevision,
        NodeInventory or MappingArtifact (B3.1d boundary).
        """
        if not isinstance(topology, TopologyArtifact):
            raise AttachmentError("topology must be a TopologyArtifact")
        if self.topology_hash != topology.topology_hash():
            raise AttachmentError(
                "topology_hash does not match the materialized topology")
        by_router = {r.router_id: r for r in topology.routers}
        seats: set[tuple[int, int]] = set()
        for e in self.endpoints:
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
            seat = (e.router_id, e.port_id)
            if seat in seats:
                raise AttachmentError(
                    f"duplicate seat: router {e.router_id} port {e.port_id}")
            seats.add(seat)
            if not e.symmetric:
                erouter_id, eport_id = e.egress_location()
                erouter = by_router.get(erouter_id)
                if erouter is None:
                    raise AttachmentError(
                        f"endpoint {e.endpoint_id} egresses at router "
                        f"{erouter_id}, which is not in the topology")
                if not 0 <= eport_id < erouter.ejection_capacity:
                    raise AttachmentError(
                        f"endpoint {e.endpoint_id} egress port {eport_id} is "
                        f"outside router {erouter_id} ejection capacity "
                        f"{erouter.ejection_capacity}")

    def validate_against(self, design, inventory: NodeInventory,
                         topology: TopologyArtifact) -> None:
        """Prove topology seats + the complete design agent universe.

Rationale: docs/decisions/modules/model.md
        """
        if not isinstance(inventory, NodeInventory):
            raise AttachmentError("inventory must be a NodeInventory")
        groups = getattr(design, "agents", None)
        if groups is None:
            raise AttachmentError("design must expose .agents")
        self.validate_against_topology(topology)

        expected = _expected_universe(design)
        inventory_actual = _inventory_universe(inventory)
        if inventory_actual != expected:
            raise AttachmentError(_format_delta(
                "inventory", expected - inventory_actual,
                inventory_actual - expected))
        actual = {(e.agent.group_index, e.agent.instance_index, e.agent.kind)
                  for e in self.endpoints}
        if actual != expected:
            raise AttachmentError(_format_delta(
                "attachment", expected - actual, actual - expected))

        for e in self.endpoints:
            group_index = e.agent.group_index
            group = groups[group_index]
            if e.group_name != getattr(group, "group_name", None):
                raise AttachmentError(
                    f"endpoint {e.endpoint_id} group_name {e.group_name!r} "
                    f"does not match Agent group {group_index} group_name "
                    f"{getattr(group, 'group_name', None)!r}; rebuild attachment after identity changes")
            if not 0 <= e.agent.instance_index < group.count:
                raise AttachmentError(
                    f"endpoint {e.endpoint_id} instance_index "
                    f"{e.agent.instance_index} is outside Agent group "
                    f"{group_index} count {group.count}")
            if e.agent.kind != group.kind:
                raise AttachmentError(
                    f"endpoint {e.endpoint_id} kind {e.agent.kind.value!r} "
                    f"does not match Agent group {group_index} kind "
                    f"{group.kind.value!r}")
            expected_iface = descriptor_of_group(group)
            if e.interface != expected_iface:
                raise AttachmentError(
                    f"endpoint {e.endpoint_id} interface descriptor does "
                    f"not match Agent group {group_index}: "
                    f"{e.interface.to_dict()} != {expected_iface.to_dict()}")

    @classmethod
    def from_dict(cls, d: Any) -> "AgentAttachmentArtifact":
        if not isinstance(d, dict):
            raise AttachmentError(
                f"attachment must be an object, got {type(d).__name__}")
        if d.get("schema_version") in (1, 2):
            raise AttachmentError(
                f"AgentAttachmentArtifact schema v{d['schema_version']} is "
                "refused: v1 has no interface descriptor and v2 over-bound "
                "identity to design/mapping hashes. Rebuild from "
                "DesignRevision + NodeInventory + TopologyArtifact — no "
                "silent migration")
        _strict_keys(d, frozenset({
            "type", "schema_version", "topology_hash", "endpoints",
            "attachment_hash"}), "attachment")
        if d.get("type") != _HASH_TYPE_TAG:
            raise AttachmentError(
                f"attachment type tag {d.get('type')!r} is not "
                f"{_HASH_TYPE_TAG!r}")
        endpoints = _need(d, "endpoints", "attachment")
        if not isinstance(endpoints, list):
            raise AttachmentError("attachment.endpoints must be a list")
        artifact = cls(
            topology_hash=_need(d, "topology_hash", "attachment"),
            endpoints=tuple(Endpoint.from_dict(e) for e in endpoints),
            schema_version=_need(d, "schema_version", "attachment"),
        )
        supplied = d.get("attachment_hash")
        if supplied is None or supplied != artifact.attachment_hash():
            raise AttachmentError(
                "attachment_hash missing or does not match content")
        return artifact

def derive_attachment(*, design, inventory: NodeInventory,
                      topology: TopologyArtifact) -> AgentAttachmentArtifact:
    """Bind every hardware AgentInstance to a topology local seat.

Rationale: docs/decisions/modules/model.md
    """
    if not isinstance(inventory, NodeInventory):
        raise AttachmentError("inventory must be a NodeInventory")
    if not isinstance(topology, TopologyArtifact):
        raise AttachmentError("topology must be a TopologyArtifact")
    groups = getattr(design, "agents", None)
    if groups is None:
        raise AttachmentError("design must expose .agents")

    expected = _expected_universe(design)
    inventory_actual = _inventory_universe(inventory)
    if inventory_actual != expected:
        raise AttachmentError(_format_delta(
            "inventory", expected - inventory_actual,
            inventory_actual - expected))

    seats = [(r.router_id, s)
             for r in topology.routers
             for s in range(r.seat_capacity)]
    if len(seats) < inventory.agent_count:
        raise AttachmentError(
            f"topology has {len(seats)} seats but {inventory.agent_count} "
            "agents must attach")
    # A fabric with a direction-specific ejection namespace (the multi-stage
    # Fly) attaches each agent to an ingress seat AND an egress slot. The
    # slots are enumerated in the same canonical order as the seats, which is
    # the construction's own terminal order -- never an invented pairing.
    egress_seats: list[tuple[int, int]] | None = None
    if any(r.egress_seat_capacity is not None for r in topology.routers):
        egress_seats = [(r.router_id, s)
                        for r in topology.routers
                        for s in range(r.ejection_capacity)]
        if len(egress_seats) != len(seats):
            raise AttachmentError(
                f"topology has {len(seats)} ingress seats but "
                f"{len(egress_seats)} egress slots: a fabric whose terminals "
                "eject somewhere other than they inject must pair them "
                "one-to-one")
    endpoints = tuple(
        Endpoint(endpoint_id=i, agent=agent, router_id=seats[i][0],
                 port_id=seats[i][1],
                 interface=descriptor_of_group(groups[agent.group_index]),
                 group_name=getattr(groups[agent.group_index], "group_name", None),
                 egress_router_id=(None if egress_seats is None
                                   else egress_seats[i][0]),
                 egress_port_id=(None if egress_seats is None
                                 else egress_seats[i][1]))
        for i, agent in enumerate(inventory.agents)
    )
    artifact = AgentAttachmentArtifact(
        topology_hash=topology.topology_hash(),
        endpoints=endpoints,
    )
    artifact.validate_against(design, inventory, topology)
    return artifact
