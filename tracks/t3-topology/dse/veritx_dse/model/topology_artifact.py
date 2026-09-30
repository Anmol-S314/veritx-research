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
            "physical_links", "topology_hash"}), "topology")
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
        artifact = cls(family=family, routers=routers, channels=channels,
                       physical_links=links,
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
    from .topology_ir import TopologyIR, expand
    if not isinstance(ir, TopologyIR):
        raise TopologyError(
            f"materialize_ir expects a TopologyIR, got {type(ir).__name__}")
    _as_int("width_bits", width_bits, minimum=1)
    _as_int("latency_cycles", latency_cycles, minimum=0)
    _as_int("seat_capacity", seat_capacity, minimum=1)

    m = expand(ir)
    adj: dict[int, list[int]] = {v: [] for v in m.nodes}
    for u, v in m.edges:
        adj[u].append(v)
        adj[v].append(u)
    adj = {r: sorted(peers) for r, peers in adj.items()}

    if coordinates is None:
        coords = {r: () for r in adj}
    else:
        missing = sorted(set(adj) - set(coordinates))
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

    return _artifact(MaterializedFamily.CUSTOM, adj, coords, seat_capacity,
                     width_bits, latency_cycles)

def materialize_topology_intent(inventory: NodeInventory, intent: Any, *,
                                width_bits: int = _DEFAULT_LINK_WIDTH_BITS,
                                latency_cycles: int = _DEFAULT_LINK_LATENCY_CYCLES
                                ) -> TopologyArtifact:
    """Typed topology intent -> `TopologyArtifact`. THE materialization seam.

Rationale: docs/decisions/modules/model.md
    """
    from veritx_dse.model.topology_intent import (
        ConcentratedMeshIntent, ExplicitTopologyIntent, FatTreeIntent,
        FlatFlyIntent, GecTopologyIntent, MeshIntent, TorusIntent,
    )
    if isinstance(intent, ExplicitTopologyIntent):
        return materialize_ir(intent.graph, width_bits=width_bits,
                              latency_cycles=latency_cycles)
    if getattr(intent, "kind", None) == "structured":
        return materialize_ir(structured_graph(intent.family, intent.params),
                              width_bits=width_bits,
                              latency_cycles=latency_cycles)
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
        if intent.mode == GecMode.EXPRESS:
            _require_express_law(intent)
            return materialize_gec_express(
                k=intent.grid_side_length,
                concentration=intent.concentration,
                width_bits=width_bits, latency_cycles=latency_cycles)
        if intent.mode == GecMode.MULTIDROP:
            raise TopologyError(
                "UNSUPPORTED: GEC-MECS (multidrop) is a shared tapped "
                "channel, not representable as independent directed "
                "channels without semantic loss (single-slot contention "
                "+ drop addressing + per-tap credit lanes). A canonical "
                "multidrop resource is the missing bridge — flattening "
                "taps to point-to-point links is REFUSED, never "
                "approximated.")
        if intent.mode == GecMode.HYBRID:
            raise TopologyError(
                "UNSUPPORTED: GEC-HYBRID inherits the MECS multidrop "
                "gap plus two-domain VC/routing semantics. Refused until "
                "the multidrop resource + hybrid qualification exist.")
        raise TopologyError(
            f"UNSUPPORTED: GEC mode {intent.mode.value!r} has no "
            "canonical materializer. GEC-MESH degrades to a plain mesh "
            "graph but is NOT assumed equivalent without the PHASE D "
            "equivalence ruling — declare a mesh instead.")
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
