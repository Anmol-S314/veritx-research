"""veritx_dse.model.attachment — AgentAttachmentArtifact (B3.1, B3.1c, B3.1d).

B2 stops at LogicalRank -> AgentInstance. B3 owns the next relationship:

    AgentInstance -> Endpoint (fabric-addressable attachment) -> RouterPort

Every hardware AgentInstance attaches, compute or not, including idle
compute instances — an active LogicalRank is not required to attach an
agent. Endpoint ids are canonical fabric attachment ids assigned densely
in (router_id, port_id) order; AddressRange.target_agent_idx identifies
an Agent group and does NOT assign endpoint ids (§8).

Interface authority (B3.1c):

    AgentInterfaceDescriptor
        data_width_bits
        address_width_bits
        protocol
        clock_domain
        power_domain

endpoints carry the immutable interface semantics of the Agent group they
were derived from.

Identity boundary (B3.1d). The attachment's ONLY semantic parent is

    topology_hash

because the endpoints reference router/port seat identities from the
TopologyArtifact. DesignRevision and NodeInventory are the derivation and
validation SOURCES, and MappingArtifact is a downstream seam concern — none
of them enter attachment identity:

    fabric_hash       = identity of the resolved hardware fabric
    resolved_fabric   = design_hash + mapping_hash + fabric_hash

so the same hardware fabric under a different workload mapping must keep
the same attachment_hash (and later fabric_hash). Copying the interface
descriptor into the artifact is what lets design-derived hardware
semantics propagate WITHOUT hashing the entire design; an unrelated design
change (batch size, requirement, output format) must not change hardware
identity.

Validation (B3.1d) proves the complete agent universe:

    expected = {(group_index, instance_index, group.kind)
                for every group in design.agents
                for every instance in range(group.count)}

    inventory agents == expected      (no missing, no extra)
    attachment endpoints == expected  (no missing, no extra, no duplicates)

plus per-endpoint group bounds, kind agreement, interface equality with
the parent group, real router seats, and at-most-once seat occupancy.
Every hardware agent attaches — not only agents that currently host a
logical rank. Mapping placement legality is a ResolvedFabric seam check,
not an attachment identity rule.

Schema v1 and v2 attachments are refused on load: v1 has no interface
descriptor; v2 polluted identity with design/mapping hashes. Neither is
silently converted to v3.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .compile_model import AgentKind, _as_int, _as_str
from .placement import AgentInstance, NodeInventory
from .topology_artifact import TopologyArtifact

ATTACHMENT_SCHEMA_VERSION = 3
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
    and copied into the attachment artifact: design-derived semantics
    propagate through the descriptor, not through a design hash.
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

    Identity parent is ``topology_hash`` ONLY. DesignRevision and
    NodeInventory are derivation/validation sources; MappingArtifact is a
    downstream ResolvedFabric seam concern.
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
        for e in self.endpoints:
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

    # ── parent/derivation validation ───────────────────────────────────
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

    def validate_against(self, design, inventory: NodeInventory,
                         topology: TopologyArtifact) -> None:
        """Prove topology seats + the complete design agent universe.

        DesignRevision and NodeInventory are validation sources, not
        identity parents: this proves the attachment corresponds to them
        without hashing them. Hardware-local seat legality is delegated
        to ``validate_against_topology`` so FabricArtifact can prove it
        without design context — no duplicated implementation.
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
            group = groups[group_index]          # safe: actual == expected
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

    Baseline policy: routers in id order, seats 0..capacity-1 within each
    router, agents in canonical NodeInventory order. Deterministic, no
    optimizer.

    Inputs are the design revision (agent universe + interface
    semantics), the NodeInventory (canonical agent order), and the
    TopologyArtifact (seats). MappingArtifact deliberately does not
    participate: rank placement is not hardware attachment identity.
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
    endpoints = tuple(
        Endpoint(endpoint_id=i, agent=agent, router_id=seats[i][0],
                 port_id=seats[i][1],
                 interface=descriptor_of_group(groups[agent.group_index]))
        for i, agent in enumerate(inventory.agents)
    )
    artifact = AgentAttachmentArtifact(
        topology_hash=topology.topology_hash(),
        endpoints=endpoints,
    )
    artifact.validate_against(design, inventory, topology)
    return artifact
