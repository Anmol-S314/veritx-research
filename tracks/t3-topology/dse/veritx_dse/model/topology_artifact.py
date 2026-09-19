"""veritx_dse.model.topology_artifact — materialized fabric truth (Wave B3.1).

A topology family name ("mesh 8x8") is intent METADATA. The authoritative
topology is the materialized graph:

    routers (with local attachment seats)
    directed channels (the routing/deadlock resource)
    optional physical-link grouping

Sizing rule (spec SROTA_FABRIC_SEMANTICS_V1 §9): router count is derived
from the hardware endpoint count and GUIDED concentration, never from a
hardcoded constant and never from the model rank count. Every AgentInstance
in NodeInventory needs a seat, so the endpoint count is
``NodeInventory.agent_count`` (compute tiles, HBM controllers, NICs,
peripherals, UCIe ports and idle compute instances alike).

TopologyArtifact does NOT depend on AgentAttachmentArtifact: it exposes
seats; the attachment artifact assigns agents to them. No circularity.

Canonical numbering (§7.5): regular families number routers by coordinate
order (row-major); ports are local seats then link ports in ascending
neighbor-id order; channel ids are assigned densely in sorted
(src_router, src_port, dst_router, dst_port) order. Changing these rules
changes identity and requires a schema bump.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .compile_model import CompileRequest, NocConfig, TopologyFamily
from .compile_model import _as_int, _as_str
from .placement import NodeInventory

TOPOLOGY_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/TopologyArtifact"

# Default local seats per router by family (GUIDED concentration overrides).
_CONCENTRATION_DEFAULT = {
    "mesh": 1, "torus": 1, "ring": 1, "concentrated_mesh": 4,
}
# Default per-hop link properties when the request does not carry them.
_DEFAULT_LINK_WIDTH_BITS = 64
_DEFAULT_LINK_LATENCY_CYCLES = 1


class TopologyError(ValueError):
    """Unmaterializable topology family/params (fail closed, no fallback)."""


class MaterializedFamily(Enum):
    MESH = "mesh"
    TORUS = "torus"
    RING = "ring"
    CONCENTRATED_MESH = "concentrated_mesh"


def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise TopologyError(f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise TopologyError(f"{where} has unknown fields: {sorted(unknown)}")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise TopologyError(f"{where} is missing required field {key!r}")
    return d[key]


@dataclass(frozen=True)
class Router:
    router_id: int
    coordinates: tuple[int, ...]
    seat_capacity: int

    def __post_init__(self):
        _as_int("router_id", self.router_id, minimum=0)
        _as_int("seat_capacity", self.seat_capacity, minimum=1)
        if not isinstance(self.coordinates, tuple) or not all(
                type(c) is int and c >= 0 for c in self.coordinates):
            raise TopologyError(
                f"router {self.router_id} coordinates must be a tuple of "
                "non-negative ints")

    def to_dict(self) -> dict[str, Any]:
        return {"router_id": self.router_id,
                "coordinates": list(self.coordinates),
                "seat_capacity": self.seat_capacity}

    @classmethod
    def from_dict(cls, d: Any) -> Router:
        _strict_keys(d, frozenset({"router_id", "coordinates", "seat_capacity"}),
                     "router")
        coords = _need(d, "coordinates", "router")
        if not isinstance(coords, list) or not all(
                type(c) is int and c >= 0 for c in coords):
            raise TopologyError("router.coordinates must be a list of ints")
        return cls(router_id=_need(d, "router_id", "router"),
                   coordinates=tuple(coords),
                   seat_capacity=_need(d, "seat_capacity", "router"))


@dataclass(frozen=True)
class DirectedChannel:
    """Primary routing/deadlock resource. Behavior properties live here."""

    channel_id: int
    src_router: int
    src_port: int
    dst_router: int
    dst_port: int
    width_bits: int
    latency_cycles: int
    route_weight: int = 1
    physical_link_id: int | None = None

    def __post_init__(self):
        for name in ("channel_id", "src_router", "src_port", "dst_router",
                     "dst_port"):
            _as_int(name, getattr(self, name), minimum=0)
        _as_int("width_bits", self.width_bits, minimum=1)
        _as_int("latency_cycles", self.latency_cycles, minimum=0)
        _as_int("route_weight", self.route_weight, minimum=1)
        if self.src_router == self.dst_router:
            raise TopologyError(
                f"channel {self.channel_id} is a self-loop on router "
                f"{self.src_router}")
        if self.physical_link_id is not None:
            _as_int("physical_link_id", self.physical_link_id, minimum=0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id, "src_router": self.src_router,
            "src_port": self.src_port, "dst_router": self.dst_router,
            "dst_port": self.dst_port, "width_bits": self.width_bits,
            "latency_cycles": self.latency_cycles,
            "route_weight": self.route_weight,
            "physical_link_id": self.physical_link_id,
        }

    @classmethod
    def from_dict(cls, d: Any) -> DirectedChannel:
        _strict_keys(d, frozenset({
            "channel_id", "src_router", "src_port", "dst_router", "dst_port",
            "width_bits", "latency_cycles", "route_weight", "physical_link_id",
        }), "channel")
        return cls(
            channel_id=_need(d, "channel_id", "channel"),
            src_router=_need(d, "src_router", "channel"),
            src_port=_need(d, "src_port", "channel"),
            dst_router=_need(d, "dst_router", "channel"),
            dst_port=_need(d, "dst_port", "channel"),
            width_bits=_need(d, "width_bits", "channel"),
            latency_cycles=_need(d, "latency_cycles", "channel"),
            route_weight=d.get("route_weight", 1),
            physical_link_id=d.get("physical_link_id"),
        )


@dataclass(frozen=True)
class PhysicalLink:
    """Optional physical grouping of one or more directed channels."""

    physical_link_id: int
    channel_ids: tuple[int, ...]
    length_mm: float | None = None

    def __post_init__(self):
        _as_int("physical_link_id", self.physical_link_id, minimum=0)
        if not isinstance(self.channel_ids, tuple) or not self.channel_ids:
            raise TopologyError("physical_link.channel_ids must be a non-empty tuple")
        if self.length_mm is not None and self.length_mm < 0:
            raise TopologyError("physical_link.length_mm must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {"physical_link_id": self.physical_link_id,
                "channel_ids": list(self.channel_ids),
                "length_mm": self.length_mm}


@dataclass(frozen=True)
class TopologyArtifact:
    family: MaterializedFamily
    routers: tuple[Router, ...]
    channels: tuple[DirectedChannel, ...]
    physical_links: tuple[PhysicalLink, ...] = ()
    schema_version: int = TOPOLOGY_SCHEMA_VERSION

    def __post_init__(self):
        if not isinstance(self.family, MaterializedFamily):
            raise TopologyError("family must be a MaterializedFamily")
        for seq_name in ("routers", "channels", "physical_links"):
            if not isinstance(getattr(self, seq_name), tuple):
                raise TopologyError(f"{seq_name} must be a tuple")
        if not isinstance(self.schema_version, int) or \
                self.schema_version != TOPOLOGY_SCHEMA_VERSION:
            raise TopologyError(
                f"unsupported topology schema_version {self.schema_version!r} "
                f"(this build implements v{TOPOLOGY_SCHEMA_VERSION})")
        if not self.routers:
            raise TopologyError("topology must contain at least one router")
        rids = [r.router_id for r in self.routers]
        if rids != list(range(len(rids))):
            raise TopologyError("router ids must be contiguous from 0")
        cids = [c.channel_id for c in self.channels]
        if cids != list(range(len(cids))):
            raise TopologyError("channel ids must be contiguous from 0")
        valid = set(rids)
        for c in self.channels:
            if c.src_router not in valid or c.dst_router not in valid:
                raise TopologyError(
                    f"channel {c.channel_id} references a missing router")
            if c.src_port >= self._port_count(c.src_router) or \
                    c.dst_port >= self._port_count(c.dst_router):
                raise TopologyError(
                    f"channel {c.channel_id} port out of range")

    def _port_count(self, router_id: int) -> int:
        seats = self.routers[router_id].seat_capacity
        links = sum(1 for c in self.channels if c.src_router == router_id)
        return seats + links

    @property
    def router_count(self) -> int:
        return len(self.routers)

    @property
    def channel_count(self) -> int:
        return len(self.channels)

    @property
    def seat_capacity(self) -> int:
        """Total local attachment seats across all routers."""
        return sum(r.seat_capacity for r in self.routers)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "family": self.family.value,
            "routers": [r.to_dict() for r in self.routers],
            "channels": [c.to_dict() for c in self.channels],
            "physical_links": [p.to_dict() for p in self.physical_links],
        }

    def topology_hash(self) -> str:
        from veritx_dse.core.spec import canonical_json
        body = (f"{_HASH_TYPE_TAG}/v{self.schema_version}\0"
                + canonical_json(self.canonical_dict()))
        return hashlib.sha256(body.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        d = self.canonical_dict()
        d["topology_hash"] = self.topology_hash()
        return d

    @classmethod
    def from_dict(cls, d: Any) -> TopologyArtifact:
        _strict_keys(d, frozenset({
            "type", "schema_version", "family", "routers", "channels",
            "physical_links", "topology_hash"}), "topology")
        try:
            family = MaterializedFamily(_need(d, "family", "topology"))
        except ValueError:
            raise TopologyError(f"unknown family {d.get('family')!r}") from None
        routers = tuple(Router.from_dict(r) for r in _need(d, "routers", "topology"))
        channels = tuple(DirectedChannel.from_dict(c)
                         for c in _need(d, "channels", "topology"))
        links = tuple(PhysicalLink(physical_link_id=p["physical_link_id"],
                                   channel_ids=tuple(p["channel_ids"]),
                                   length_mm=p.get("length_mm"))
                      for p in d.get("physical_links", []))
        artifact = cls(family=family, routers=routers, channels=channels,
                       physical_links=links,
                       schema_version=_need(d, "schema_version", "topology"))
        supplied = d.get("topology_hash")
        if supplied is not None and supplied != artifact.topology_hash():
            raise TopologyError("topology_hash does not match content")
        return artifact


# ── materialization ─────────────────────────────────────────────────────────

def _family_of(noc: NocConfig) -> MaterializedFamily:
    tf = noc.topology_family or TopologyFamily.MESH
    mapping = {
        TopologyFamily.MESH: MaterializedFamily.MESH,
        TopologyFamily.TORUS: MaterializedFamily.TORUS,
        TopologyFamily.CONCENTRATED_MESH: MaterializedFamily.CONCENTRATED_MESH,
    }
    if tf not in mapping:
        raise TopologyError(
            f"topology_family {tf.value!r} is not materializable in B3.1 "
            "(supported: mesh, torus, concentrated_mesh) — no silent fallback")
    return mapping[tf]


def _concentration_of(family: MaterializedFamily, noc: NocConfig) -> int:
    if noc.concentration is not None:
        return _as_int("concentration", noc.concentration, minimum=1)
    return _CONCENTRATION_DEFAULT[family.value]


def _grid_adjacency(k: int, wrap: bool) -> dict[int, list[int]]:
    """Symmetric mesh/torus adjacency in canonical row-major numbering."""
    adj: dict[int, set[int]] = {r: set() for r in range(k * k)}
    for y in range(k):
        for x in range(k):
            r = y * k + x
            for dx, dy in ((1, 0), (0, 1)):
                nx, ny = x + dx, y + dy
                if nx >= k or ny >= k:
                    if not wrap:
                        continue
                    nx, ny = nx % k, ny % k
                other = ny * k + nx
                if other == r:
                    continue
                adj[r].add(other)
                adj[other].add(r)
    return {r: sorted(peers) for r, peers in adj.items()}


def materialize_family(family: MaterializedFamily, *, endpoint_count: int,
                       concentration: int = 1, radix: int | None = None,
                       width_bits: int = _DEFAULT_LINK_WIDTH_BITS,
                       latency_cycles: int = _DEFAULT_LINK_LATENCY_CYCLES
                       ) -> TopologyArtifact:
    """Materialize one family for a required endpoint count.

    Router count is ``ceil(endpoint_count / concentration)`` rounded up to
    the family's discrete shape (k x k for mesh/torus/concentrated, a line
    for ring). A radix override pins k and must still provide enough seats.
    """
    if not isinstance(family, MaterializedFamily):
        raise TopologyError("family must be a MaterializedFamily")
    _as_int("endpoint_count", endpoint_count, minimum=1)
    _as_int("concentration", concentration, minimum=1)
    _as_int("width_bits", width_bits, minimum=1)
    _as_int("latency_cycles", latency_cycles, minimum=0)
    routers_needed = math.ceil(endpoint_count / concentration)

    if family in (MaterializedFamily.MESH, MaterializedFamily.TORUS,
                  MaterializedFamily.CONCENTRATED_MESH):
        if radix is not None:
            k = _as_int("radix", radix, minimum=1)
        else:
            k = max(1, math.ceil(math.sqrt(routers_needed)))
        if k * k * concentration < endpoint_count:
            raise TopologyError(
                f"radix {k} with concentration {concentration} provides "
                f"{k * k * concentration} seats but {endpoint_count} agents "
                "must attach")
        wrap = family == MaterializedFamily.TORUS
        adj = _grid_adjacency(k, wrap)
        coordinates = {r: (r % k, r // k) for r in range(k * k)}
    elif family == MaterializedFamily.RING:
        if radix is not None:
            n = _as_int("radix", radix, minimum=1)
        else:
            n = max(1, routers_needed)
        if n * concentration < endpoint_count:
            raise TopologyError(
                f"ring of {n} routers with concentration {concentration} "
                f"provides {n * concentration} seats but {endpoint_count} "
                "agents must attach")
        adj = {r: sorted({(r - 1) % n, (r + 1) % n}) if n > 1 else []
               for r in range(n)}
        coordinates = {r: (r,) for r in range(n)}
    else:  # pragma: no cover - enum is closed
        raise TopologyError(f"unhandled family {family}")

    routers = tuple(
        Router(router_id=r, coordinates=coordinates[r],
               seat_capacity=concentration)
        for r in sorted(adj)
    )
    # Canonical ports: local seats first, then link ports in ascending
    # neighbor order. channel_id assigned densely in sorted order.
    link_port: dict[tuple[int, int], int] = {}
    for r in sorted(adj):
        for i, nb in enumerate(adj[r]):
            link_port[(r, nb)] = concentration + i
    raw = sorted(
        (r, link_port[(r, nb)], nb, link_port[(nb, r)])
        for r in sorted(adj) for nb in adj[r]
    )
    channels = tuple(
        DirectedChannel(channel_id=i, src_router=sr, src_port=sp,
                        dst_router=dr, dst_port=dp, width_bits=width_bits,
                        latency_cycles=latency_cycles)
        for i, (sr, sp, dr, dp) in enumerate(raw)
    )
    return TopologyArtifact(family=family, routers=routers, channels=channels)


def materialize_topology(inventory: NodeInventory,
                         cr_or_noc: CompileRequest | NocConfig
                         ) -> TopologyArtifact:
    """Materialize a topology from hardware inventory and GUIDED knobs.

    NocConfig can express mesh, torus and concentrated mesh; ring/custom/
    anynet arrive via TopologyIR in a later wave. GEC and fat-tree are
    refused rather than silently downgraded to mesh.
    """
    noc = (cr_or_noc.noc_config if isinstance(cr_or_noc, CompileRequest)
           else cr_or_noc)
    if not isinstance(noc, NocConfig):
        raise TopologyError("expected a CompileRequest or NocConfig")
    family = _family_of(noc)
    concentration = _concentration_of(family, noc)
    width = noc.link_width if noc.link_width is not None else _DEFAULT_LINK_WIDTH_BITS
    return materialize_family(
        family, endpoint_count=inventory.agent_count,
        concentration=concentration, radix=noc.radix, width_bits=width)

