"""veritx_dse.model.topology_artifact — materialized fabric truth (Wave B3.1).

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

from .topology_ir import from_dict as _ir_from_dict
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .compile_model import CompileRequest, NocConfig, TopologyFamily
from .compile_model import _as_int, _as_str
from .placement import NodeInventory

TOPOLOGY_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/TopologyArtifact"

_CONCENTRATION_DEFAULT = {
    "mesh": 1, "torus": 1, "ring": 1, "concentrated_mesh": 4,
    "flatfly": 1, "custom": 1, "gec_express": 1,
}
_DEFAULT_LINK_WIDTH_BITS = 64
_DEFAULT_LINK_LATENCY_CYCLES = 1

class TopologyError(ValueError, SemanticError):
    """Unmaterializable topology family/params (fail closed, no fallback)."""

class MaterializedFamily(Enum):
    """How a TopologyArtifact was derived.

Rationale: docs/decisions/modules/model.md
    """
    MESH = "mesh"
    TORUS = "torus"
    RING = "ring"
    CONCENTRATED_MESH = "concentrated_mesh"
    FLATFLY = "flatfly"
    GEC_EXPRESS = "gec_express"
    GEC_MECS = "gec_mecs"
    SROTA = "srota"
    CUSTOM = "custom"

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
            raise TopologyError(
                "physical_link.channel_ids must be a non-empty tuple")
        for cid in self.channel_ids:
            _as_int("channel_ids", cid, minimum=0)
        if len(set(self.channel_ids)) != len(self.channel_ids):
            raise TopologyError(
                "physical_link.channel_ids must not contain duplicates")
        if self.length_mm is not None:
            if isinstance(self.length_mm, bool) or not isinstance(
                    self.length_mm, (int, float)):
                raise TopologyError(
                    "physical_link.length_mm must be a number")
            if not math.isfinite(float(self.length_mm)) or self.length_mm < 0:
                raise TopologyError(
                    "physical_link.length_mm must be finite and >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {"physical_link_id": self.physical_link_id,
                "channel_ids": list(self.channel_ids),
                "length_mm": self.length_mm}

    @classmethod
    def from_dict(cls, d: Any) -> PhysicalLink:
        _strict_keys(d, frozenset({
            "physical_link_id", "channel_ids", "length_mm"}), "physical_link")
        cids = _need(d, "channel_ids", "physical_link")
        if not isinstance(cids, list):
            raise TopologyError(
                "physical_link.channel_ids must be a list")
        return cls(
            physical_link_id=_need(d, "physical_link_id", "physical_link"),
            channel_ids=tuple(cids),
            length_mm=d.get("length_mm"),
        )

@dataclass(frozen=True)
class SharedLink:
    """One driver feeding many taps over a single shared wire (a bus).

    Deliberately NOT a DirectedChannel: a shared wire has one driver and many
    sinks, and the taps contend for one wire slot per cycle. Lowering it to
    point-to-point channels would model N independent wires instead.
    """

    shared_link_id: int
    src_router: int
    taps: tuple[int, ...]
    width_bits: int
    latency_cycles: int

    def __post_init__(self):
        _as_int("shared_link_id", self.shared_link_id, minimum=0)
        _as_int("src_router", self.src_router, minimum=0)
        _as_int("width_bits", self.width_bits, minimum=1)
        _as_int("latency_cycles", self.latency_cycles, minimum=0)
        if not isinstance(self.taps, tuple) or not self.taps:
            raise TopologyError("shared_link.taps must be a non-empty tuple")
        for tap in self.taps:
            _as_int("taps", tap, minimum=0)
            if tap == self.src_router:
                raise TopologyError(
                    f"shared_link {self.shared_link_id} drives itself")
        if len(set(self.taps)) != len(self.taps):
            raise TopologyError(
                "shared_link.taps must not contain duplicates")

    def to_dict(self) -> dict[str, Any]:
        return {"shared_link_id": self.shared_link_id,
                "src_router": self.src_router,
                "taps": list(self.taps),
                "width_bits": self.width_bits,
                "latency_cycles": self.latency_cycles}

    @classmethod
    def from_dict(cls, d: Any) -> SharedLink:
        _strict_keys(d, frozenset({
            "shared_link_id", "src_router", "taps", "width_bits",
            "latency_cycles"}), "shared_link")
        taps = _need(d, "taps", "shared_link")
        if not isinstance(taps, list):
            raise TopologyError("shared_link.taps must be a list")
        return cls(
            shared_link_id=_need(d, "shared_link_id", "shared_link"),
            src_router=_need(d, "src_router", "shared_link"),
            taps=tuple(taps),
            width_bits=_need(d, "width_bits", "shared_link"),
            latency_cycles=_need(d, "latency_cycles", "shared_link"),
        )

@dataclass(frozen=True)
class TopologyArtifact:
    family: MaterializedFamily
    routers: tuple[Router, ...]
    channels: tuple[DirectedChannel, ...]
    physical_links: tuple[PhysicalLink, ...] = ()
    shared_links: tuple[SharedLink, ...] = ()
    schema_version: int = TOPOLOGY_SCHEMA_VERSION

    def __post_init__(self):
        if not isinstance(self.family, MaterializedFamily):
            raise TopologyError("family must be a MaterializedFamily")
        for seq_name in ("routers", "channels", "physical_links",
                         "shared_links"):
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
        link_ids = [p.physical_link_id for p in self.physical_links]
        if len(link_ids) != len(set(link_ids)):
            raise TopologyError("physical link ids must be unique")
        known_channels = set(cids)
        known_links = set(link_ids)
        channel_owner: dict[int, int] = {}
        for link in self.physical_links:
            for cid in link.channel_ids:
                if cid not in known_channels:
                    raise TopologyError(
                        f"physical link {link.physical_link_id} references "
                        f"missing channel {cid}")
                if cid in channel_owner:
                    raise TopologyError(
                        f"channel {cid} is assigned to both physical link "
                        f"{channel_owner[cid]} and {link.physical_link_id}")
                channel_owner[cid] = link.physical_link_id
        for c in self.channels:
            if c.physical_link_id is not None \
                    and c.physical_link_id not in known_links:
                raise TopologyError(
                    f"channel {c.channel_id} references missing physical "
                    f"link {c.physical_link_id}")
        shared_ids = [s.shared_link_id for s in self.shared_links]
        if shared_ids != list(range(len(shared_ids))):
            raise TopologyError("shared link ids must be contiguous from 0")
        for s in self.shared_links:
            if s.src_router not in valid:
                raise TopologyError(
                    f"shared link {s.shared_link_id} drives a missing router")
            for tap in s.taps:
                if tap not in valid:
                    raise TopologyError(
                        f"shared link {s.shared_link_id} taps a missing "
                        f"router {tap}")

    def _port_count(self, router_id: int) -> int:
        """Port ids above the local seats: the larger of in- and out-degree.

        A directed fabric can have more inputs than outputs at a router, so
        the bound must cover both. For a symmetric family this is unchanged.

        Shared wires count as ports too: a shared segment occupies one OUTPUT
        port at its driver and one INPUT port per tap, exactly like a
        point-to-point channel does. Counting only `channels` here would
        under-count a mixed fabric (one express dimension, one plain) and
        reject a correct port map — which is the SROTA case.
        """
        seats = self.routers[router_id].seat_capacity
        out = sum(1 for c in self.channels if c.src_router == router_id)
        inn = sum(1 for c in self.channels if c.dst_router == router_id)
        out += sum(1 for s in self.shared_links
                   if s.src_router == router_id)
        inn += sum(1 for s in self.shared_links if router_id in s.taps)
        return seats + max(out, inn)

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
        d: dict[str, Any] = {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "family": self.family.value,
            "routers": [r.to_dict() for r in self.routers],
            "channels": [c.to_dict() for c in self.channels],
            "physical_links": [p.to_dict() for p in self.physical_links],
        }
        # Emitted only when present, so a point-to-point fabric's identity is
        # untouched by the arrival of shared-wire support.
        if self.shared_links:
            d["shared_links"] = [s.to_dict() for s in self.shared_links]
        return d

    def topology_hash(self) -> str:
        from veritx_dse.core.artifact import content_id
        return content_id(f"{_HASH_TYPE_TAG}/v{self.schema_version}",
                          self.canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        d = self.canonical_dict()
        d["topology_hash"] = self.topology_hash()
        return d

    @classmethod
    def from_dict(cls, d: Any) -> TopologyArtifact:
        _strict_keys(d, frozenset({
            "type", "schema_version", "family", "routers", "channels",
            "physical_links", "shared_links", "topology_hash"}), "topology")
        try:
            family = MaterializedFamily(_need(d, "family", "topology"))
        except ValueError:
            raise TopologyError(f"unknown family {d.get('family')!r}") from None
        routers = tuple(Router.from_dict(r) for r in _need(d, "routers", "topology"))
        channels = tuple(DirectedChannel.from_dict(c)
                         for c in _need(d, "channels", "topology"))
        raw_links = d.get("physical_links", [])
        if not isinstance(raw_links, list):
            raise TopologyError("topology.physical_links must be a list")
        links = tuple(PhysicalLink.from_dict(p) for p in raw_links)
        raw_shared = d.get("shared_links", [])
        if not isinstance(raw_shared, list):
            raise TopologyError("topology.shared_links must be a list")
        shared = tuple(SharedLink.from_dict(s) for s in raw_shared)
        artifact = cls(family=family, routers=routers, channels=channels,
                       physical_links=links, shared_links=shared,
                       schema_version=_need(d, "schema_version", "topology"))
        supplied = d.get("topology_hash")
        if supplied is not None and supplied != artifact.topology_hash():
            raise TopologyError("topology_hash does not match content")
        return artifact

def _family_of(noc: NocConfig) -> MaterializedFamily:
    tf = noc.topology_family or TopologyFamily.MESH
    mapping = {
        TopologyFamily.MESH: MaterializedFamily.MESH,
        TopologyFamily.TORUS: MaterializedFamily.TORUS,
        TopologyFamily.CONCENTRATED_MESH: MaterializedFamily.CONCENTRATED_MESH,
    }
    if tf not in mapping:
        if tf == TopologyFamily.CUSTOM:
            raise TopologyError(
                "topology_family 'custom' carries no parameters: an explicit "
                "graph is the input, not a family. Use "
                "topology_ir.materialize_ir(TopologyIR) — "
                "no silent fallback")
        raise TopologyError(
            f"topology_family {tf.value!r} is not materializable: it is "
            "RECOGNIZED and AUTHORABLE but has no canonical materializer "
            "yet (materializable: mesh, torus, concentrated_mesh, flatfly, "
            "custom-via-TopologyIR) — no silent fallback. See "
            "docs/product/topology-family-registry.yaml")
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
    return _artifact(family, adj, coordinates, concentration,
                     width_bits, latency_cycles)

def _artifact(family: MaterializedFamily, adj: dict[int, list[int]],
              coordinates: dict[int, tuple[int, ...]], concentration: int,
              width_bits: int, latency_cycles: int) -> TopologyArtifact:
    """Shared canonical construction: routers, ports, dense channel ids.

    One construction path for every family, so canonical ordering cannot
    drift between materializers.
    """
    routers = tuple(
        Router(router_id=r, coordinates=coordinates[r],
               seat_capacity=concentration)
        for r in sorted(adj)
    )
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

def _srota_ports(x: int, y: int, k: int, *,
                mecs_row: bool, mecs_col: bool
                ) -> list[tuple[str, list[tuple[int, int]], bool]]:
    """Output direction ports of router (x, y), in the SOURCE's fixed order.

    srota.hpp is explicit that this order is the single contract between the
    builder and the routing function, and that presence is identical whether
    a dimension runs express or plain mesh -- only the wiring behind the port
    changes. Returning ``(direction, taps, shared)`` here keeps that contract
    in one place instead of transcribing it into the builder and the router
    separately.
    """
    out: list[tuple[str, list[tuple[int, int]], bool]] = []
    if x > 0:
        out.append(("XNEG", ([(xx, y) for xx in range(x - 1, -1, -1)]
                             if mecs_row else [(x - 1, y)]), mecs_row))
    if x < k - 1:
        out.append(("XPOS", ([(xx, y) for xx in range(x + 1, k)]
                             if mecs_row else [(x + 1, y)]), mecs_row))
    if y > 0:
        out.append(("YNEG", ([(x, yy) for yy in range(y - 1, -1, -1)]
                             if mecs_col else [(x, y - 1)]), mecs_col))
    if y < k - 1:
        out.append(("YPOS", ([(x, yy) for yy in range(y + 1, k)]
                             if mecs_col else [(x, y + 1)]), mecs_col))
    return out

_SROTA_REVERSE = {"XNEG": "XPOS", "XPOS": "XNEG", "YNEG": "YPOS",
                  "YPOS": "YNEG"}

def materialize_srota(*, k: int, concentration: int, mecs_row: bool,
                      mecs_col: bool,
                      width_bits: int = _DEFAULT_LINK_WIDTH_BITS,
                      latency_cycles: int = _DEFAULT_LINK_LATENCY_CYCLES
                      ) -> TopologyArtifact:
    """Materialize the SROTA Plane D: concentrated mesh + MECS express.

    MECS express channels are MULTIDROP by construction (TOPO-003 3.1: one
    driver per segment per direction, with drop-off points at every router
    along the span), so they become ``SharedLink`` objects, never flattened
    into independent point-to-point wires. A dimension with express off gets
    ordinary nearest-neighbour links instead, exactly as the source does.

    Latency note: the source's drop latency (1 or 2) and its fixed 1-cycle
    channel latency are pinned by the intent/config, not invented here; the
    caller passes the channel latency it qualified.
    """
    _as_int("k", k, minimum=2)
    _as_int("concentration", concentration, minimum=1)
    _as_int("width_bits", width_bits, minimum=1)
    _as_int("latency_cycles", latency_cycles, minimum=0)

    coords = {(x, y): (x, y) for y in range(k) for x in range(k)}

    def rid(cell: tuple[int, int]) -> int:
        x, y = cell
        return y * k + x

    ports = {cell: _srota_ports(cell[0], cell[1], k, mecs_row=mecs_row,
                                mecs_col=mecs_col)
             for cell in coords}

    shared: list[SharedLink] = []
    channels: list[DirectedChannel] = []
    for cell in sorted(coords):
        for index, (direction, taps, is_shared) in enumerate(ports[cell]):
            src_port = concentration + index
            if is_shared:
                shared.append(SharedLink(
                    shared_link_id=len(shared), src_router=rid(cell),
                    taps=tuple(rid(t) for t in taps), width_bits=width_bits,
                    latency_cycles=latency_cycles))
                continue
            neighbour = taps[0]
            back = _SROTA_REVERSE[direction]
            dst_index = next(i for i, (d, _t, _s)
                             in enumerate(ports[neighbour]) if d == back)
            channels.append(DirectedChannel(
                channel_id=len(channels), src_router=rid(cell),
                src_port=src_port, dst_router=rid(neighbour),
                dst_port=concentration + dst_index, width_bits=width_bits,
                latency_cycles=latency_cycles))

    return TopologyArtifact(
        family=MaterializedFamily.SROTA,
        routers=tuple(Router(router_id=rid(cell), coordinates=coords[cell],
                             seat_capacity=concentration)
                      for cell in sorted(coords, key=rid)),
        channels=tuple(channels),
        shared_links=tuple(shared))

def _gec_mecs_wires(k: int, o: int, d: int, *, concentration: int,
                     width_bits: int, latency_cycles: int
                     ) -> tuple[list[int], list[SharedLink]]:
    """Plane-D-style router set plus the GEC MECS express wires.

    GEC's express wires are NOT directional. ``pout = c + 2*o`` — one wire
    per dimension per group — and a wire's taps are every OTHER coordinate in
    that dimension, ordered by ``GEC::_PeerIndex`` (ascending, self skipped).
    The group is ``peer_index // d`` and the tap is ``peer_index % d``, which
    is exactly what ``dor_gec`` stamps into ``Flit::drop``.

    Deriving this any other way (e.g. as separate +x/-x wires, which is what
    SROTA does) puts the tap on the wrong router, so the two fabrics must not
    share a tap rule.
    """
    wires: list[SharedLink] = []
    for y in range(k):
        for x in range(k):
            src = y * k + x
            for axis in ("x", "y"):
                peers = [q for q in range(k) if q != (x if axis == "x" else y)]
                for group in range(o):
                    taps = tuple(
                        (y * k + peers[idx]) if axis == "x"
                        else (peers[idx] * k + x)
                        for idx in range(group * d, (group + 1) * d))
                    if not taps:
                        raise TopologyError(
                            f"UNSUPPORTED: GEC wire (router {src}, {axis}, "
                            f"group {group}) has no taps; o*d must cover "
                            "k-1 peers exactly")
                    wires.append(SharedLink(
                        shared_link_id=len(wires), src_router=src,
                        taps=taps, width_bits=width_bits,
                        latency_cycles=latency_cycles))
    return [0], wires


def materialize_gec_mecs(*, k: int, concentration: int, o: int, d: int,
                         width_bits: int = _DEFAULT_LINK_WIDTH_BITS,
                         latency_cycles: int = _DEFAULT_LINK_LATENCY_CYCLES
                         ) -> TopologyArtifact:
    """Materialize GEC multidrop (MECS) express: shared wires only.

    Every express wire is a shared resource — one driver, many contending
    taps — so it becomes a ``SharedLink`` and never a point-to-point channel.
    With MECS there are no ordinary channels at all (``_channels = 0`` in the
    source for the d>1 case), which is why a fabric like this needs a flit
    width derived from wires rather than channels.
    """
    _as_int("k", k, minimum=2)
    _as_int("concentration", concentration, minimum=1)
    _as_int("o", o, minimum=1)
    _as_int("d", d, minimum=2)
    if o * d != k - 1:
        raise TopologyError(
            f"the GEC source law o*d == k-1 is violated: o({o}) x d({d}) = "
            f"{o * d} != k-1 ({k - 1})")
    coords = {(x, y): (x, y) for y in range(k) for x in range(k)}

    def rid(cell: tuple[int, int]) -> int:
        x, y = cell
        return y * k + x

    _unused, shared = _gec_mecs_wires(
        k, o, d, concentration=concentration, width_bits=width_bits,
        latency_cycles=latency_cycles)
    return TopologyArtifact(
        family=MaterializedFamily.GEC_MECS,
        routers=tuple(Router(router_id=rid(cell), coordinates=coords[cell],
                             seat_capacity=concentration)
                      for cell in sorted(coords, key=rid)),
        channels=(),
        shared_links=tuple(shared))


def materialize_flatfly(*, k: int, n: int, concentration: int = 1,
                        width_bits: int = _DEFAULT_LINK_WIDTH_BITS,
                        latency_cycles: int = _DEFAULT_LINK_LATENCY_CYCLES
                        ) -> TopologyArtifact:
    """Materialize a k-ary n-fly flattened butterfly (PURE point-to-point).

Rationale: docs/decisions/modules/model.md
    """
    _as_int("k", k, minimum=2)
    _as_int("n", n, minimum=1)
    _as_int("concentration", concentration, minimum=1)
    _as_int("width_bits", width_bits, minimum=1)
    _as_int("latency_cycles", latency_cycles, minimum=0)

    router_count = k ** n
    coords = {r: tuple((r // k ** i) % k for i in range(n))
              for r in range(router_count)}
    adj: dict[int, list[int]] = {r: [] for r in range(router_count)}
    for r in range(router_count):
        rc = coords[r]
        for i in range(n):
            for v in range(k):
                if v == rc[i]:
                    continue
                other = list(rc)
                other[i] = v
                oid = 0
                for d in range(n):
                    oid += other[d] * (k ** d)
                if oid != r and oid not in adj[r]:
                    adj[r].append(oid)
    adj = {r: sorted(peers) for r, peers in adj.items()}
    expected_deg = (k - 1) * n
    bad = {r: len(p) for r, p in adj.items() if len(p) != expected_deg}
    if bad:
        raise TopologyError(
            f"flatfly k={k} n={n}: routers with degree != (k-1)*n={expected_deg}: "
            f"{sorted(bad.items())[:4]}")
    return _artifact(MaterializedFamily.FLATFLY, adj, coords, concentration,
                     width_bits, latency_cycles)

def _require_express_law(intent: Any) -> None:
    """Enforce the source grouping law for GEC-EXPRESS intents.

    The fork's law (gec.cpp): groups x dests == grid_side - 1, and
    EXPRESS is exactly dests == 1 (each express channel reaches one
    destination — pure point-to-point). Anything else is a different
    physical mode, never a parameter tweak.
    """
    groups = intent.express_channel_groups_per_dimension
    dests = intent.destinations_per_express_channel
    k = intent.grid_side_length
    if groups is None or dests is None:
        raise TopologyError(
            "GEC-EXPRESS requires express_channel_groups_per_dimension "
            "and destinations_per_express_channel")
    if dests != 1:
        raise TopologyError(
            f"GEC-EXPRESS requires destinations_per_express_channel == "
            f"1, got {dests} (dests > 1 is MULTIDROP/MECS)")
    if groups * dests != k - 1:
        raise TopologyError(
            f"GEC source law violated: groups({groups}) x dests({dests}) "
            f"!= k-1 ({k - 1})")

def materialize_gec_express(*, k: int, concentration: int = 1,
                            width_bits: int = _DEFAULT_LINK_WIDTH_BITS,
                            latency_cycles: int = _DEFAULT_LINK_LATENCY_CYCLES
                            ) -> TopologyArtifact:
    """Materialize a GEC point-to-point express graph (PURE p2p).

Rationale: docs/decisions/modules/model.md
    """
    _as_int("k", k, minimum=2)
    _as_int("concentration", concentration, minimum=1)
    _as_int("width_bits", width_bits, minimum=1)
    _as_int("latency_cycles", latency_cycles, minimum=0)
    adj: dict[int, list[int]] = {r: [] for r in range(k * k)}
    for y in range(k):
        for x in range(k):
            r = y * k + x
            for xx in range(k):
                if xx != x:
                    adj[r].append(y * k + xx)
            for yy in range(k):
                if yy != y:
                    adj[r].append(yy * k + x)
    adj = {r: sorted(peers) for r, peers in adj.items()}
    expected_deg = 2 * (k - 1)
    bad = {r: len(p) for r, p in adj.items() if len(p) != expected_deg}
    if bad:
        raise TopologyError(
            f"gec_express k={k}: degree != 2(k-1)={expected_deg}: "
            f"{sorted(bad.items())[:4]}")
    coords = {r: (r % k, r // k) for r in range(k * k)}
    return _artifact(MaterializedFamily.GEC_EXPRESS, adj, coords,
                     concentration, width_bits, latency_cycles)

def fat_tree_graph(*, switch_radix: int, level_count: int):
    """The canonical k-ary L-level fat-tree as a `TopologyIR`.

    Routers are numbered tier-major: level 0 (edge) first, then the tiers
    above. Every router carries `switch_radix` seats, so the edge tier can
    hold the endpoints while the upper tiers simply have unused seats.

    Edges: every router in tier i links to `switch_radix` routers in tier
    i+1, spread so each upper-tier router receives `switch_radix` links —
    the defining property of a fat-tree (constant bisection).

    Source form: docs/decisions/modules/model.md; ports per switch = k,
    middle tier = k^(L-1) switches per level.
    """
    k, levels = int(switch_radix), int(level_count)
    if k < 2 or levels < 1:
        raise TopologyError(
            f"a fat-tree needs switch_radix >= 2 and level_count >= 1, got "
            f"k={k}, L={levels}")
    per_tier = k ** (levels - 1)
    links: list[list[int]] = []
    for tier in range(levels - 1):
        up_base, lo_base = (tier + 1) * per_tier, tier * per_tier
        for lo in range(per_tier):
            for uplink in range(k):
                up = (lo + uplink) % per_tier
                links.append([lo_base + lo, up_base + up])
    return _ir_from_dict({
        "name": f"fattree_k{k}_l{levels}",
        "kind": "custom",
        "nodes": levels * per_tier,
        "links": links,
        "link_attrs": {"bandwidth_GBs": 50.0, "latency_ns": 500.0},
    })


def flattened_butterfly_graph(*, radix: int, dimensions: int):
    """k-ary n-flat-flattened-butterfly as a `TopologyIR`.

    k^n routers; in each of the n dimensions the k^(n-1) groups that share
    the remaining coordinates form a clique. Degree is therefore exactly
    n*(k-1) — the constanta-radix property that gives a flat-flattened
    butterfly its bisection. Source form: networks/fly.cpp (`_nodes =
    powi(k, n)`).

    Note this is the SAME generator as GEC express (`row + column cliques`),
    which is why a 16-router GEC-express and a k=4/n=2 flat-flattened
    butterfly are the same graph.
    """
    k, n = int(radix), int(dimensions)
    if k < 2 or n < 2:
        raise TopologyError(
            f"a flattened butterfly needs radix >= 2 and dimensions >= 2, "
            f"got k={k}, n={n}")
    total = k ** n
    links: list[list[int]] = []
    for node in range(total):
        digits = []
        rest = node
        for _ in range(n):
            digits.append(rest % k)
            rest //= k
        for dim in range(n):
            base = digits[dim]
            for other in range(base + 1, k):
                peer = sum((other if d == dim else digits[d]) * k ** d
                           for d in range(n))
                if peer > node:
                    links.append([node, peer])
    return _ir_from_dict({
        "name": f"flatfly_k{k}_n{n}",
        "kind": "custom",
        "nodes": total,
        "links": links,
        "link_attrs": {"bandwidth_GBs": 50.0, "latency_ns": 500.0},
    })


def dragonfly_graph(*, radix: int, group_count: int):
    """Canonical dragonfly: `group_count` groups of `radix` routers.

    Routers inside a group form a clique (the local links); each router
    carries one global link to a router in every other group. Source form:
    networks/dragonfly.cpp (`_a` routers per group, `_g` groups).
    """
    p, g = int(radix), int(group_count)
    if p < 2 or g < 2:
        raise TopologyError(
            f"a dragonfly needs radix >= 2 and group_count >= 2, got "
            f"p={p}, g={g}")
    links: list[list[int]] = []
    for group in range(g):
        for a in range(p):
            node = group * p + a
            for b in range(a + 1, p):
                links.append([node, group * p + b])
    for src_group in range(g):
        for dst_group in range(src_group + 1, g):
            for a in range(p):
                links.append([src_group * p + a,
                              dst_group * p + ((a + src_group) % p)])
    return _ir_from_dict({
        "name": f"dragonfly_p{p}_g{g}",
        "kind": "custom",
        "nodes": g * p,
        "links": links,
        "link_attrs": {"bandwidth_GBs": 50.0, "latency_ns": 500.0},
    })


def k_ary_tree_graph(*, radix: int, tiers: int):
    """k-ary tree of `tiers` levels above the leaves, as a `TopologyIR`.

    Covers `qtree` and `tree4`, which are the same graph generator at
    different fixed radices. Nodes are numbered breadth-first: the root is
    0, and each internal node i has children k*i+1 .. k*i+k. Leaves are the
    last k^tiers nodes. Source form: networks/qtree.cpp, networks/tree4.cpp.
    """
    k, t = int(radix), int(tiers)
    if k < 2 or t < 1:
        raise TopologyError(
            f"a k-ary tree needs radix >= 2 and tiers >= 1, got k={k}, "
            f"t={t}")
    internal = (k ** t - 1) // (k - 1)
    links: list[list[int]] = []
    for parent in range(internal):
        for child in range(k * parent + 1, k * parent + k + 1):
            links.append([parent, child])
    return _ir_from_dict({
        "name": f"tree_k{k}_t{t}",
        "kind": "custom",
        "nodes": internal + k ** t,
        "links": links,
        "link_attrs": {"bandwidth_GBs": 50.0, "latency_ns": 500.0},
    })


#: The extension point. A family is ONE entry: the field names its intent
#: accepts, and the builder turns those into a `TopologyIR`. Both the field
#: names and the graph live together, so a new family cannot half-exist.
STRUCTURED_FAMILIES: dict[str, dict[str, Any]] = {
    "flattened_butterfly": {
        "fields": ("radix", "dimensions"),
        "build": lambda p: flattened_butterfly_graph(
            radix=p["radix"], dimensions=p["dimensions"]),
        "booksim": "fly",
    },
    "dragonfly": {
        "fields": ("radix", "group_count"),
        "build": lambda p: dragonfly_graph(
            radix=p["radix"], group_count=p["group_count"]),
        "booksim": "dragonflynew",
    },
    "qtree": {
        "fields": ("radix", "tiers"),
        "build": lambda p: k_ary_tree_graph(
            radix=p["radix"], tiers=p["tiers"]),
        "booksim": "qtree",
    },
    "tree4": {
        "fields": ("radix", "tiers"),
        "build": lambda p: k_ary_tree_graph(
            radix=p["radix"], tiers=p["tiers"]),
        "booksim": "tree4",
    },
    "fat_tree": {
        "fields": ("radix", "tiers"),
        "build": lambda p: fat_tree_graph(
            switch_radix=p["radix"], level_count=p["tiers"]),
        "booksim": "fattree",
        # A fat-tree switch has `radix` ports, so the edge tier holds
        # `radix` endpoints each. Without this every router seats 1 and a
        # 16-agent design is refused against only 8 seats.
        "seat_capacity": lambda p: p["radix"],
    },
}


def structured_graph(family: str, params: dict) -> Any:
    """Build the canonical graph for a structured family."""
    spec = STRUCTURED_FAMILIES.get(family)
    if spec is None:
        raise TopologyError(
            f"unknown structured family {family!r}; known: "
            f"{sorted(STRUCTURED_FAMILIES)}")
    missing = sorted(set(spec["fields"]) - set(params))
    if missing:
        raise TopologyError(
            f"family {family!r} is missing {missing}")
    return spec["build"](params)


def _edge_key(links) -> frozenset:
    """Undirected edge set from `(u, v)` pairs or `Link` objects.

    A shared link expands to one edge per tap: a bus is a set of
    point-to-point adjacencies for recognition purposes. A DIRECTED link is
    skipped — direction is not expressible in an undirected family graph.
    """
    out = set()
    for link in links:
        if hasattr(link, "sinks"):
            if link.directed:
                continue
            for sink in link.sinks:
                u, v = link.src, sink
                if u != v:
                    out.add((u, v) if u < v else (v, u))
        else:
            u, v = link[0], link[1]
            out.add((u, v) if u < v else (v, u))
    return frozenset(out)


def _grid_graph(nodes: int, *, wrap: bool):
    """k x k mesh (wrap=False) or torus (wrap=True), or None if not square."""
    k = math.isqrt(nodes)
    if k * k != nodes or k < 2:
        return None
    links = []
    for y in range(k):
        for x in range(k):
            n = y * k + x
            if x + 1 < k or wrap:
                links.append((n, y * k + (x + 1) % k))
            if y + 1 < k or wrap:
                links.append((n, ((y + 1) % k) * k + x))
    return links


def _expected_edges(family: str, params: dict) -> int | None:
    """Edge count computed arithmetically — never by building the graph.

    The cheap necessary condition that stops recognition from allocating
    before a match is even possible. Without it a 1000x1000 probe built a
    2M-link grid to compare against two edges.
    """
    k = params.get("radix") or params.get("side_length")
    if family in ("mesh", "torus"):
        if not k:
            return None
        return 2 * k * (k - 1) if family == "mesh" else 2 * k * k
    if family == "flattened_butterfly":
        n = params["dimensions"]
        return k ** n * n * (k - 1) // 2
    if family == "dragonfly":
        p, g = params["radix"], params["group_count"]
        return g * p * (p - 1) // 2 + g * (g - 1) // 2 * p
    if family in ("qtree", "tree4"):
        t = params["tiers"]
        return (k ** t - 1) // (k - 1) + k ** t - 1
    if family == "fat_tree":
        t = params["tiers"]
        return t * k ** t // 2
    return None


def _param_candidates(family: str, nodes: int):
    """Parameters whose canonical graph has EXACTLY `nodes` routers.

    Filtered arithmetically BEFORE anything is built, and bounded by integer
    roots rather than `range(2, nodes + 1)` — an unbounded sweep is a million
    iterations at nodes=1e6 and buys nothing.
    """
    def powers():
        for n in range(1, nodes.bit_length() + 2):
            root = round(nodes ** (1.0 / n))
            for k in {root - 1, root, root + 1}:
                if k >= 2 and k ** n == nodes:
                    yield k, n

    def root(n: int, degree: int) -> int:
        if degree < 1:
            return n
        k = int(n ** (1.0 / degree)) + 2
        while k > 1 and k ** degree > n:
            k -= 1
        return max(k, 1)

    if family == "flattened_butterfly":
        for k, n in powers():
            if n >= 2:
                yield {"radix": k, "dimensions": n}
    elif family == "dragonfly":
        for p in range(2, math.isqrt(nodes) + 1):
            if nodes % p == 0 and nodes // p >= 2:
                yield {"radix": p, "group_count": nodes // p}
    elif family in ("qtree", "tree4"):
        for t in range(1, 9):
            if t == 1:
                if nodes - 1 >= 2:
                    yield {"radix": nodes - 1, "tiers": 1}
                continue
            for k in range(2, root(nodes, t) + 1):
                leaves = k ** t
                if (leaves - 1) // (k - 1) + leaves == nodes:
                    yield {"radix": k, "tiers": t}
    elif family == "fat_tree":
        for t in range(2, 9):
            for k in range(2, root(nodes, t - 1) + 1):
                if t * k ** (t - 1) == nodes:
                    yield {"radix": k, "tiers": t}


def recognize_family(nodes: int, links) -> tuple[str, dict[str, Any]] | None:
    """Exact-match a graph against the canonical family generators.

    Returns `(family, params)` or None. EXACT edge-set equality, never a
    degree or diameter heuristic: a near-miss must stay an explicit graph,
    because claiming a family buys that family's routing and certificate.

    This lets a synthesized candidate be re-declared as the family it
    actually is. Without it every candidate compiles as AnyNet and is scored
    under generic min-hop routing — a 4x4 mesh scored 734176 that way
    against 488806 natively, so the optimiser chose on a biased surface.
    """
    target = _edge_key(links)
    if not target:
        return None

    def matches(family: str, params: dict) -> bool:
        expected = _expected_edges(family, params)
        if expected is None or expected != len(target):
            return False          # cheap reject: never build to find out
        if family in ("mesh", "torus"):
            built = _grid_graph(nodes, wrap=(family == "torus"))
            return built is not None and _edge_key(built) == target
        try:
            graph = structured_graph(family, params)
        except (TopologyError, KeyError, ValueError, TypeError):
            return False
        return graph.nodes == nodes and _edge_key(graph.links) == target

    k_root = math.isqrt(nodes)
    if k_root * k_root == nodes and k_root >= 2:
        for family in ("mesh", "torus"):
            params = {"side_length": k_root, "concentration": 1}
            if matches(family, params):
                return family, params

    for family in STRUCTURED_FAMILIES:
        for params in _param_candidates(family, nodes):
            if matches(family, params):
                return family, params
    return None


def materialize_ir(ir: Any, *,
                   width_bits: int = _DEFAULT_LINK_WIDTH_BITS,
                   latency_cycles: int = _DEFAULT_LINK_LATENCY_CYCLES,
                   seat_capacity: int = 1,
                   coordinates: dict[int, tuple[int, ...]] | None = None
                   ) -> TopologyArtifact:
    """Materialize an explicit topology description (TopologyIR) to a
    canonical TopologyArtifact.

Rationale: docs/decisions/modules/model.md
    """
    from .topology_ir import (
        TopologyIR, expand, link_latency_cycles, link_width_bits,
    )
    if not isinstance(ir, TopologyIR):
        raise TopologyError(
            f"materialize_ir expects a TopologyIR, got {type(ir).__name__}")
    _as_int("width_bits", width_bits, minimum=1)
    _as_int("latency_cycles", latency_cycles, minimum=0)
    _as_int("seat_capacity", seat_capacity, minimum=1)

    m = expand(ir)

    # A per-link latency override cannot be expressed in sub-cycle units:
    # refuse rather than silently flatten it to the uniform default.
    if latency_cycles < 1 and any(link.latency_ns is not None
                                  for link in m.links):
        raise TopologyError(
            "materialize_ir: per-link latency_ns needs latency_cycles >= 1 "
            "(a sub-cycle fabric cannot express a slower link); got "
            f"latency_cycles={latency_cycles}")

    if coordinates is None:
        coords = {r: () for r in m.nodes}
    else:
        missing = sorted(set(m.nodes) - set(coordinates))
        if missing:
            raise TopologyError(
                f"materialize_ir: coordinates supplied but missing for "
                f"routers {missing[:8]}")
        for r, c in coordinates.items():
            if not isinstance(c, tuple) or not all(
                    type(x) is int and x >= 0 for x in c):
                raise TopologyError(
                    f"materialize_ir: coordinates[{r}] must be a tuple of "
                    f"non-negative ints, got {c!r}")
        coords = dict(coordinates)

    # One entry per (src, dst): an undirected link contributes both
    # directions, a directed link one. Ports are numbered per router from its
    # local seats, so an unchanged graph keeps its canonical channel order.
    spec: dict[tuple[int, int], Any] = {}
    for link in m.links:
        if link.shared:
            continue
        for dst in link.sinks:
            spec[(link.src, dst)] = link
            if not link.directed:
                spec[(dst, link.src)] = link
    out_neighbours = {r: sorted(d for (s, d) in spec if s == r)
                      for r in m.nodes}
    in_neighbours = {r: sorted(s for (s, d) in spec if d == r)
                     for r in m.nodes}
    out_port = {(r, d): seat_capacity + i
                for r, peers in out_neighbours.items()
                for i, d in enumerate(peers)}
    in_port = {(r, s): seat_capacity + i
               for r, peers in in_neighbours.items()
               for i, s in enumerate(peers)}
    raw = sorted((r, out_port[(r, d)], d, in_port[(d, r)]) for (r, d) in spec)
    channels = tuple(
        DirectedChannel(
            channel_id=i, src_router=sr, src_port=sp, dst_router=dr,
            dst_port=dp,
            width_bits=link_width_bits(spec[(sr, dr)], ir, width_bits),
            latency_cycles=link_latency_cycles(spec[(sr, dr)], ir,
                                               latency_cycles))
        for i, (sr, sp, dr, dp) in enumerate(raw))

    shared = tuple(
        SharedLink(shared_link_id=i, src_router=link.src, taps=link.sinks,
                   width_bits=link_width_bits(link, ir, width_bits),
                   latency_cycles=link_latency_cycles(link, ir,
                                                      latency_cycles))
        for i, link in enumerate(l for l in m.links if l.shared))

    return TopologyArtifact(
        family=MaterializedFamily.CUSTOM,
        routers=tuple(
            Router(router_id=r, coordinates=coords[r],
                   seat_capacity=seat_capacity)
            for r in sorted(m.nodes)),
        channels=channels,
        shared_links=shared)

def materialize_topology_intent(inventory: NodeInventory, intent: Any, *,
                                width_bits: int = _DEFAULT_LINK_WIDTH_BITS,
                                latency_cycles: int = _DEFAULT_LINK_LATENCY_CYCLES
                                ) -> TopologyArtifact:
    """Typed topology intent -> `TopologyArtifact`. THE materialization seam.

Rationale: docs/decisions/modules/model.md
    """
    from veritx_dse.model.topology_intent import (
        ConcentratedMeshIntent, ExplicitTopologyIntent, FatTreeIntent,
        FlatFlyIntent, GecTopologyIntent, MeshIntent, SrotaIntent,
        TorusIntent,
    )
    if isinstance(intent, ExplicitTopologyIntent):
        return materialize_ir(intent.graph, width_bits=width_bits,
                              latency_cycles=latency_cycles)
    if getattr(intent, "kind", None) == "structured":
        seats = STRUCTURED_FAMILIES[intent.family].get("seat_capacity")
        return materialize_ir(
            structured_graph(intent.family, intent.params),
            width_bits=width_bits, latency_cycles=latency_cycles,
            seat_capacity=(seats(intent.params) if seats else 1))
    if isinstance(intent, MeshIntent):
        family, radix, conc = (MaterializedFamily.MESH, intent.side_length,
                               intent.concentration)
    elif isinstance(intent, ConcentratedMeshIntent):
        family, radix, conc = (MaterializedFamily.CONCENTRATED_MESH,
                               intent.side_length, intent.concentration)
    elif isinstance(intent, TorusIntent):
        family, radix, conc = (MaterializedFamily.TORUS, intent.side_length,
                               intent.concentration)
    elif isinstance(intent, FlatFlyIntent):
        return materialize_flatfly(
            k=intent.radix_per_dimension, n=intent.dimension_count,
            concentration=intent.concentration, width_bits=width_bits,
            latency_cycles=latency_cycles)
    elif isinstance(intent, GecTopologyIntent):
        from veritx_dse.model.topology_intent import GecMode
        if intent.mode == GecMode.MESH:
            # GEC mesh mode is exactly the nearest-neighbor k×k mesh:
            # gec.cpp builds only N/E/S/W links, uses X-then-Y DOR, and
            # pins every channel to one cycle. Lower to the canonical mesh
            # artifact rather than introducing a duplicate family.
            return materialize_family(
                MaterializedFamily.MESH,
                endpoint_count=inventory.agent_count,
                concentration=intent.concentration,
                radix=intent.grid_side_length,
                width_bits=width_bits, latency_cycles=1)
        if intent.mode == GecMode.EXPRESS:
            _require_express_law(intent)
            return materialize_gec_express(
                k=intent.grid_side_length,
                concentration=intent.concentration,
                width_bits=width_bits, latency_cycles=latency_cycles)
        if intent.mode == GecMode.MULTIDROP:
            # Every tap is a real shared resource (SharedLink), never a
            # flattened point-to-point link. The intent already enforced
            # o*d == k-1 and d >= 2.
            return materialize_gec_mecs(
                k=intent.grid_side_length,
                concentration=intent.concentration,
                o=intent.express_channel_groups_per_dimension,
                d=intent.destinations_per_express_channel,
                width_bits=width_bits, latency_cycles=latency_cycles)
        if intent.mode == GecMode.HYBRID:
            # The multidrop gap this used to cite is CLOSED: shared wires
            # materialize and route (see materialize_gec_mecs). What remains
            # is specific to hybrid, so the refusal says that instead of
            # blaming a bridge that now exists.
            raise TopologyError(
                "UNSUPPORTED: GEC-HYBRID is mesh edges PLUS the MECS express "
                "layer, and its routing function (hybrid_gec) chooses "
                "between a mesh step and a MECS jump AT RUNTIME from live "
                "credit -- `take_mesh = (mesh_cost < mecs_cost)` in "
                "networks/gec.cpp. A runtime choice has no deterministic "
                "first-hop table, so RouteArtifactV3 cannot express it and "
                "static acyclicity is the wrong proof obligation: it needs "
                "the escape-subnetwork method (ESCAPE_SUBNETWORK_THEOREM is "
                "already in the deadlock-proof vocabulary). The materializer "
                "is a separate, smaller piece: mesh channels plus MECS "
                "shared wires, with 2*d VCs for the two hop-phase halves.")
        raise TopologyError(
            f"UNSUPPORTED: GEC mode {intent.mode.value!r} has no "
            "canonical materializer")
    elif isinstance(intent, SrotaIntent):
        # Plane D only. Island placement, the Valiant shape and the control
        # plane are additional structures the canonical artifact does not
        # carry yet, so they refuse rather than being dropped.
        from veritx_dse.model.srota_intent import SrotaPathShape, SrotaPlane
        if SrotaPathShape.VALIANT in intent.path_shapes:
            raise TopologyError(
                "UNSUPPORTED: the canonical SROTA artifact carries the "
                "direct row/column shapes only; VALIANT needs the "
                "two-leg rank split (4 VC sets) and is not materialized")
        if SrotaPlane.CONTROL in intent.planes:
            raise TopologyError(
                "UNSUPPORTED: Plane C is a second BookSim subnet with its "
                "own REQ/RSP/SNP VC structure; a single canonical artifact "
                "cannot carry two packet planes yet")
        if intent.island_columns:
            raise TopologyError(
                "UNSUPPORTED: island columns wrap routers in a rate "
                "regulator whose state the canonical artifact does not "
                "carry; refuse rather than materialize an unwrapped fabric")
        return materialize_srota(
            k=intent.side_length, concentration=intent.concentration,
            mecs_row=intent.mecs_row, mecs_col=intent.mecs_col,
            width_bits=width_bits, latency_cycles=latency_cycles)
    elif isinstance(intent, FatTreeIntent):
        return materialize_ir(
            fat_tree_graph(switch_radix=intent.switch_radix,
                           level_count=intent.level_count),
            width_bits=width_bits, latency_cycles=latency_cycles,
            seat_capacity=intent.switch_radix)
    else:
        raise TopologyError(
            f"UNSUPPORTED: topology intent kind "
            f"{getattr(intent, 'kind', type(intent).__name__)!r} has no "
            "canonical materializer — no silent fallback")
    return materialize_family(
        family, endpoint_count=inventory.agent_count,
        concentration=conc, radix=radix, width_bits=width_bits,
        latency_cycles=latency_cycles)

def materialize_topology(inventory: NodeInventory,
                         cr_or_noc: CompileRequest | NocConfig
                         ) -> TopologyArtifact:
    """Materialize a topology from hardware inventory and GUIDED knobs.

Rationale: docs/decisions/modules/model.md
    """
    intent = getattr(cr_or_noc, "topology", None)
    if intent is not None:
        from veritx_dse.model.topology_intent import TopologyIntent
        if isinstance(intent, TopologyIntent):
            noc_ctl = getattr(cr_or_noc, "noc_controls", None)
            width = getattr(noc_ctl, "link_width", None)
            if width is None:
                width = getattr(getattr(cr_or_noc, "noc_config", None),
                                "link_width", None)
            return materialize_topology_intent(
                inventory, intent,
                width_bits=(width if width is not None
                            else _DEFAULT_LINK_WIDTH_BITS))

    explicit = getattr(cr_or_noc, "explicit_topology", None)
    if explicit is not None:
        from veritx_dse.model.topology_ir import TopologyIR
        if not isinstance(explicit, TopologyIR):
            raise TopologyError(
                f"explicit_topology must be a TopologyIR, got "
                f"{type(explicit).__name__}")
        noc_check = getattr(cr_or_noc, "noc_config", cr_or_noc)
        if isinstance(noc_check, NocConfig) and \
                noc_check.topology_family is not None:
            raise TopologyError(
                "a request must express EXACTLY ONE topology source: a "
                "topology_family AND an explicit graph are both declared")
        width = getattr(noc_check, "link_width", None) \
            if isinstance(noc_check, NocConfig) else None
        kwargs = {}
        if width is not None:
            kwargs["width_bits"] = width
        return materialize_ir(explicit, **kwargs)

    noc = getattr(cr_or_noc, "noc_config", cr_or_noc)
    if not isinstance(noc, NocConfig):
        raise TopologyError("expected a CompileRequest or NocConfig")
    family = _family_of(noc)
    concentration = _concentration_of(family, noc)
    width = noc.link_width if noc.link_width is not None else _DEFAULT_LINK_WIDTH_BITS
    return materialize_family(
        family, endpoint_count=inventory.agent_count,
        concentration=concentration, radix=noc.radix, width_bits=width)
