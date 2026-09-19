"""veritx_dse.model.attachment — AgentAttachmentArtifact (Wave B3.1).

B2 stops at LogicalRank -> AgentInstance. B3.1 owns the next relationship:

    AgentInstance -> Endpoint (fabric-addressable attachment) -> RouterPort

Every hardware AgentInstance attaches, compute or not, including idle
compute instances — an active LogicalRank is not required to attach an
agent. Endpoint ids are canonical fabric attachment ids assigned densely
in (router_id, port_id) order; AddressRange.target_agent_idx identifies
an Agent group and does NOT assign endpoint ids (§8).

Parent hashes: topology_hash + mapping_hash. The artifact also performs
the deferred B2 parent-binding check: every AgentInstance a MappingArtifact
places must exist in the NodeInventory and be attached here.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .compile_model import AgentKind, _as_int
from .mapping import MappingArtifact
from .placement import AgentInstance, NodeInventory
from .topology_artifact import TopologyArtifact

ATTACHMENT_SCHEMA_VERSION = 1
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
class Endpoint:
    """One fabric-addressable attachment: agent, router, local seat port."""

    endpoint_id: int
    agent: AgentInstance
    router_id: int
    port_id: int

    def __post_init__(self):
        _as_int("endpoint_id", self.endpoint_id, minimum=0)
        _as_int("router_id", self.router_id, minimum=0)
        _as_int("port_id", self.port_id, minimum=0)
        if not isinstance(self.agent, AgentInstance):
            raise AttachmentError(
                f"agent must be AgentInstance, got {type(self.agent).__name__}")

    def to_dict(self) -> dict[str, Any]:
        return {"endpoint_id": self.endpoint_id, "agent": self.agent.to_dict(),
                "router_id": self.router_id, "port_id": self.port_id}

    @classmethod
    def from_dict(cls, d: Any) -> Endpoint:
        _strict_keys(d, frozenset({"endpoint_id", "agent", "router_id",
                                   "port_id"}), "endpoint")
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
        )


@dataclass(frozen=True)
class AgentAttachmentArtifact:
    topology_hash: str
    mapping_hash: str
    endpoints: tuple[Endpoint, ...]
    schema_version: int = ATTACHMENT_SCHEMA_VERSION

    def __post_init__(self):
        if not isinstance(self.topology_hash, str) or not self.topology_hash:
            raise AttachmentError("topology_hash must be a non-empty string")
        if not isinstance(self.mapping_hash, str) or not self.mapping_hash:
            raise AttachmentError("mapping_hash must be a non-empty string")
        if not isinstance(self.endpoints, tuple) or not self.endpoints:
            raise AttachmentError("endpoints must be a non-empty tuple")
        if not isinstance(self.schema_version, int) or \
                self.schema_version != ATTACHMENT_SCHEMA_VERSION:
            raise AttachmentError(
                f"unsupported attachment schema_version "
                f"{self.schema_version!r}")
        eids = [e.endpoint_id for e in self.endpoints]
        if eids != list(range(len(eids))):
            raise AttachmentError("endpoint ids must be contiguous from 0")
        seen: set[str] = set()
        seats: set[tuple[int, int]] = set()
        for e in self.endpoints:
            if not isinstance(e, Endpoint):
                raise AttachmentError(
                    f"endpoints must contain Endpoint, got {type(e).__name__}")
            if e.agent.instance_id in seen:
                raise AttachmentError(
                    f"duplicate agent attachment: {e.agent.instance_id}")
            seen.add(e.agent.instance_id)
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

    @classmethod
    def from_dict(cls, d: Any) -> AgentAttachmentArtifact:
        _strict_keys(d, frozenset({
            "type", "schema_version", "topology_hash", "mapping_hash",
            "endpoints", "attachment_hash"}), "attachment")
        endpoints = _need(d, "endpoints", "attachment")
        if not isinstance(endpoints, list):
            raise AttachmentError("attachment.endpoints must be a list")
        artifact = cls(
            topology_hash=_need(d, "topology_hash", "attachment"),
            mapping_hash=_need(d, "mapping_hash", "attachment"),
            endpoints=tuple(Endpoint.from_dict(e) for e in endpoints),
            schema_version=_need(d, "schema_version", "attachment"),
        )
        supplied = d.get("attachment_hash")
        if supplied is not None and supplied != artifact.attachment_hash():
            raise AttachmentError("attachment_hash does not match content")
        return artifact


def derive_attachment(inventory: NodeInventory,
                      mapping: MappingArtifact,
                      topology: TopologyArtifact) -> AgentAttachmentArtifact:
    """Bind every hardware AgentInstance to a topology local seat.

    Baseline policy: routers in id order, seats 0..capacity-1 within each
    router, agents in canonical NodeInventory order. Deterministic, no
    optimizer. Also performs the deferred B2 parent-binding check: every
    agent the mapping places must exist in the inventory and be attached.
    """
    seats = [(r.router_id, s)
             for r in topology.routers
             for s in range(r.seat_capacity)]
    if len(seats) < inventory.agent_count:
        raise AttachmentError(
            f"topology has {len(seats)} seats but {inventory.agent_count} "
            "agents must attach")
    endpoints = tuple(
        Endpoint(endpoint_id=i, agent=agent, router_id=seats[i][0],
                 port_id=seats[i][1])
        for i, agent in enumerate(inventory.agents)
    )
    by_id = {e.agent.instance_id for e in endpoints}
    for placement in mapping.placements:
        if placement.agent.instance_id not in by_id:
            raise AttachmentError(
                f"mapping places rank {placement.rank} on "
                f"{placement.agent.instance_id}, which is not in the "
                "inventory/attachment")
    return AgentAttachmentArtifact(
        topology_hash=topology.topology_hash(),
        mapping_hash=mapping.mapping_hash(),
        endpoints=endpoints,
    )
