"""Canonical transport view of existing topology-owned resource identities.

Channels/wires keep their legacy serialization. Tap ORDER is semantic, not
canonicalized by sorting; no capacity or clock binding is inferred.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any

from veritx_dse.core.artifact import (
    FrozenMap, content_id, freeze, thaw, require_fields,
    require_type_tag, require_schema_version, require_embedded_id,
)
from veritx_dse.core.errors import InvalidInput
from veritx_dse.model.shared_resource import ResourceKind, ResourceRef


class TransportKind(str, Enum):
    POINT_TO_POINT = "POINT_TO_POINT"
    MULTIDROP = "MULTIDROP"


def exact_int(name: str, value: Any, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise InvalidInput(f"{name} must be an exact int >= {minimum}")


@dataclass(frozen=True)
class TransportResource:
    ref: ResourceRef
    source: int
    destinations: tuple[int, ...]
    width_bits: int
    latency_cycles: int
    plane: str = "d"
    capacity: int | None = None
    clock_domain: str | None = None
    power_domain: str | None = None
    properties: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self):
        if not isinstance(self.ref, ResourceRef):
            raise InvalidInput("transport requires a topology-owned ResourceRef")
        exact_int("source", self.source)
        exact_int("width_bits", self.width_bits, 1)
        exact_int("latency_cycles", self.latency_cycles)
        if not isinstance(self.destinations, tuple) or not self.destinations:
            raise InvalidInput("transport destinations must be a nonempty tuple")
        for dest in self.destinations:
            exact_int("destination", dest)
        if len(set(self.destinations)) != len(self.destinations) or self.source in self.destinations:
            raise InvalidInput("duplicate destination or self-driven transport")
        if not self.ref.is_shared and len(self.destinations) != 1:
            raise InvalidInput("point-to-point transport has exactly one destination")
        for name in ("plane", "clock_domain", "power_domain"):
            value = getattr(self, name)
            if (value is None and name != "plane"):
                continue
            if not isinstance(value, str) or not value:
                raise InvalidInput(f"{name} must be a nonempty string")
        if self.capacity is not None:
            exact_int("capacity", self.capacity, 1)
        properties = freeze(self.properties)
        if not isinstance(properties, FrozenMap):
            raise InvalidInput("transport properties must be an object")
        object.__setattr__(self, "properties", properties)

    @property
    def kind(self):
        return TransportKind.MULTIDROP if self.ref.is_shared else TransportKind.POINT_TO_POINT

    def landing(self, tap: int | None) -> int:
        if self.ref.is_shared:
            exact_int("tap", tap)
            if tap >= len(self.destinations):
                raise InvalidInput("tap is outside the canonical destination sequence")
            return self.destinations[tap]
        if tap is not None:
            raise InvalidInput("point-to-point transport cannot have a tap")
        return self.destinations[0]

    def to_dict(self):
        return {"ref": self.ref.to_dict(), "kind": self.kind.value,
                "source": self.source, "destinations": list(self.destinations),
                "width_bits": self.width_bits, "latency_cycles": self.latency_cycles,
                "plane": self.plane, "capacity": self.capacity,
                "clock_domain": self.clock_domain, "power_domain": self.power_domain,
                "properties": thaw(self.properties)}

    @classmethod
    def from_dict(cls, d):
        names = {"ref", "kind", "source", "destinations", "width_bits", "latency_cycles",
                 "plane", "capacity", "clock_domain", "power_domain", "properties"}
        require_fields(d, names, "transport resource")
        if set(d) != names or type(d["destinations"]) is not list:
            raise InvalidInput("transport resource requires its complete versioned record")
        resource = cls(ResourceRef.from_dict(d["ref"]), d["source"], tuple(d["destinations"]),
                       d["width_bits"], d["latency_cycles"], d["plane"], d["capacity"],
                       d["clock_domain"], d["power_domain"], freeze(d["properties"]))
        if d["kind"] != resource.kind.value:
            raise InvalidInput("transport kind disagrees with resource identity")
        return resource


@dataclass(frozen=True)
class ResourceGraph:
    topology_hash: str
    routers: tuple[int, ...]
    resources: tuple[TransportResource, ...]

    def __post_init__(self):
        if not isinstance(self.topology_hash, str) or not self.topology_hash:
            raise InvalidInput("resource graph requires parent topology identity")
        if not isinstance(self.routers, tuple) or not self.routers:
            raise InvalidInput("resource graph requires routers")
        for router in self.routers:
            exact_int("router", router)
        if tuple(sorted(set(self.routers))) != self.routers:
            raise InvalidInput("resource graph routers must be sorted and unique")
        if not isinstance(self.resources, tuple) or any(
                not isinstance(r, TransportResource) for r in self.resources):
            raise InvalidInput("resources must be an immutable tuple of transports")
        refs = [r.ref for r in self.resources]
        if len(set(refs)) != len(refs):
            raise InvalidInput("duplicate canonical transport identity")
        known = set(self.routers)
        if any(r.source not in known or not set(r.destinations) <= known for r in self.resources):
            raise InvalidInput("transport names a missing router")
        object.__setattr__(self, "resources", tuple(sorted(self.resources, key=lambda r: r.ref)))
        object.__setattr__(self, "_index", MappingProxyType({r.ref: r for r in self.resources}))

    def resource(self, ref: ResourceRef) -> TransportResource:
        try:
            return self._index[ref]
        except KeyError:
            raise InvalidInput(f"resource {ref} is not in the canonical graph") from None

    def identity_dict(self):
        return {"type": "veritx/ResourceGraph", "schema_version": 1,
                "topology_hash": self.topology_hash, "routers": list(self.routers),
                "resources": [r.to_dict() for r in self.resources]}

    def artifact_id(self):
        return content_id("veritx/ResourceGraph/v1", self.identity_dict())

    def to_dict(self):
        return {**self.identity_dict(), "artifact_id": self.artifact_id()}

    @classmethod
    def from_dict(cls, d):
        require_fields(d, {"type", "schema_version", "topology_hash", "routers", "resources", "artifact_id"}, "resource graph")
        require_type_tag(d, "veritx/ResourceGraph", "resource graph")
        if type(d.get("schema_version")) is not int:
            raise InvalidInput("resource graph schema version must be an exact int")
        require_schema_version(d, 1, "resource graph")
        if type(d.get("routers")) is not list or type(d.get("resources")) is not list:
            raise InvalidInput("resource graph routers/resources must be JSON lists")
        graph = cls(d.get("topology_hash"), tuple(d["routers"]),
                    tuple(TransportResource.from_dict(r) for r in d["resources"]))
        require_embedded_id(d, "artifact_id", graph.artifact_id(), "resource graph")
        return graph

    def validate_against(self, topology):
        expected = resource_graph_from_topology(topology)
        if self != expected:
            raise InvalidInput("resource graph differs from its topology-owned resources")


def resource_graph_from_topology(topology, *, plane="d") -> ResourceGraph:
    from veritx_dse.model.topology_artifact import TopologyArtifact
    if not isinstance(topology, TopologyArtifact):
        raise InvalidInput("resource graph adapter requires a TopologyArtifact")
    # Re-read the versioned concrete types, not just their stored identities.
    topology = TopologyArtifact.from_dict(topology.to_dict())
    resources = [TransportResource(
        ResourceRef(ResourceKind.CHANNEL, ch.channel_id), ch.src_router, (ch.dst_router,),
        ch.width_bits, ch.latency_cycles, plane=plane,
        properties=freeze({"src_port": ch.src_port, "dst_port": ch.dst_port,
                           "route_weight": ch.route_weight, "physical_link_id": ch.physical_link_id}))
        for ch in topology.channels]
    resources.extend(TransportResource(
        ResourceRef(ResourceKind.SHARED_LINK, wire.shared_link_id), wire.src_router, wire.taps,
        wire.width_bits, wire.latency_cycles, plane=plane) for wire in topology.shared_links)
    return ResourceGraph(topology.topology_hash(), tuple(r.router_id for r in topology.routers), tuple(resources))
