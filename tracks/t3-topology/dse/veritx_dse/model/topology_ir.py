"""veritx_dse.model.topology_ir — TopologyIR v0: one topology, every backend.

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.errors import TopologyError
from .presets import Topology as PresetTopology

SCHEMA_VERSION = "0"

KINDS = ("mesh", "torus", "ring", "star", "switch", "anynet", "custom")

#: The GLOBAL default link spec, applied to every link that carries no
#: override of its own. See the unknown-key refusal in `from_dict`.
LINK_ATTR_KEYS = ("bandwidth_GBs", "latency_ns")
#: Optional per-link opts, the third element of a `links` entry. A link may
#: override the global bandwidth/latency and may be one-way (`directed`).
LINK_OPTS_KEYS = ("bandwidth_GBs", "latency_ns", "directed")
TEMPLATE_KINDS = ("mesh", "torus", "ring", "star", "switch")

_DOC_KEYS = frozenset({
    "name", "kind", "nodes", "params", "links", "link_attrs", "dims",
    "routing", "booksim_params", "rtl",
})

#: kind -> routing / analytical model. Derived from model/family_registry.py
#: so the taxonomy has one author; these were two more hand-kept tables.
def _by_ir_kind(field: str) -> dict[str, Any]:
    from .family_registry import TOPOLOGY_FAMILIES
    return {kind: spec[field]
            for spec in TOPOLOGY_FAMILIES.values()
            for kind in spec["ir_kinds"]}


DEFAULT_ROUTING = _by_ir_kind("routing")

ANALYTICAL_TOPO = _by_ir_kind("analytical")

BOOKSIM_DEFAULTS: dict[str, Any] = {
    "num_vcs": 4,
    "vc_buf_size": 8,
    "wait_for_tail_credit": 1,
    "vc_allocator": "islip",
    "sw_allocator": "islip",
    "alloc_iters": 1,
    "credit_delay": 1,
    "routing_delay": 0,
    "vc_alloc_delay": 1,
    "sw_alloc_delay": 1,
    "input_speedup": 1,
    "output_speedup": 1,
    "internal_speedup": 1.0,
    "packet_size": 8,
}

@dataclass
class TopologyIR:
    """Validated TopologyIR v0 document."""

    name: str
    kind: str
    nodes: int
    params: dict = field(default_factory=dict)
    links: list | None = None
    link_attrs: dict = field(default_factory=dict)
    dims: list | None = None
    routing: str | None = None
    booksim_params: dict = field(default_factory=dict)
    rtl: dict = field(default_factory=dict)

    @property
    def effective_routing(self) -> str:
        return self.routing or DEFAULT_ROUTING[self.kind]

    def to_dict(self) -> dict:
        """LOSSESS serialization — everything a round trip needs.

        Distinct from `scientific_dict()`, which is the identity-bearing
        projection. Persistence keeps the label and the backend policy;
        design identity keeps only the graph science.
        """
        return {
            "name": self.name,
            "kind": self.kind,
            "nodes": self.nodes,
            "params": dict(self.params),
            "links": [list(e) for e in self.links] if self.links is not None
                     else None,
            "link_attrs": dict(self.link_attrs),
            "dims": [dict(d) for d in self.dims] if self.dims is not None
                    else None,
            "routing": self.routing,
            "booksim_params": dict(self.booksim_params),
            "rtl": dict(self.rtl),
        }

    def scientific_dict(self) -> dict:
        """The GRAPH SCIENCE of this document — the part that is design
        intent, and the only part that may enter a design hash.

Rationale: docs/decisions/modules/model.md
        """
        return {
            "kind": self.kind,
            "nodes": self.nodes,
            "links": [list(e) for e in (self.links or [])],
            "link_attrs": dict(sorted(self.link_attrs.items())),
        }

@dataclass(frozen=True)
class Link:
    """One validated link declaration in its lowered shape.

    `sinks` holds one router for a point-to-point link and many for a shared
    wire (a bus). A `directed` link lowers to ONE channel; an undirected link
    to TWO. A shared wire is one driver feeding many taps and is never lowered
    to independent point-to-point channels.
    """

    src: int
    sinks: tuple[int, ...]
    shared: bool = False
    directed: bool = False
    bandwidth_GBs: float | None = None
    latency_ns: float | None = None

    @property
    def dst(self) -> int:
        """The single sink of a point-to-point link."""
        if self.shared or len(self.sinks) != 1:
            raise TopologyError(
                f"Link.dst is undefined for a shared link with "
                f"{len(self.sinks)} taps")
        return self.sinks[0]

@dataclass
class Materialized:
    """Expanded fabric: node ids + validated links."""

    nodes: list[int]
    links: list[Link] = field(default_factory=list)

    def adjacency(self) -> dict[int, set[int]]:
        """Undirected neighbour sets, for connectivity/diameter stats.

        Direction is ignored here: this is the graph SHAPE, not the channel
        list. A shared wire contributes driver<->each tap.
        """
        adj: dict[int, set[int]] = {v: set() for v in self.nodes}
        for link in self.links:
            for dst in link.sinks:
                adj[link.src].add(dst)
                adj[dst].add(link.src)
        return adj

    def edge_pairs(self) -> list[tuple[int, int]]:
        """Undirected point-to-point pairs (u<v), for structural stats.

        Shared wires are excluded: they are not point-to-point edges.
        """
        pairs: set[tuple[int, int]] = set()
        for link in self.links:
            if link.shared:
                continue
            for dst in link.sinks:
                pairs.add((min(link.src, dst), max(link.src, dst)))
        return sorted(pairs)

def load(path: str | Path) -> TopologyIR:
    """Load + validate a TopologyIR JSON file."""
    p = Path(path)
    try:
        doc = json.loads(p.read_text())
    except FileNotFoundError:
        raise TopologyError(f"TopologyIR: file not found: {p}")
    except json.JSONDecodeError as e:
        raise TopologyError(f"TopologyIR: invalid JSON in {p}: {e}")
    if not isinstance(doc, dict):
        raise TopologyError(f"TopologyIR: {p} must be a JSON object")
    return from_dict(doc, source=str(p))

def from_dict(doc: dict, source: str = "<dict>") -> TopologyIR:
    """Validate a decoded mapping into a TopologyIR.

    CLOSED SCHEMA. Unknown fields are refused rather than dropped: a
    TopologyIR that carries an explicit topology into a CompileRequest is
    design intent, and silently discarding a key the author wrote would
    change the design while claiming to preserve it.
    """
    if not isinstance(doc, dict):
        raise TopologyError(f"TopologyIR: {source} must be a mapping")
    unknown = sorted(set(doc) - set(_DOC_KEYS))
    if unknown:
        raise TopologyError(
            f"TopologyIR: {source}: unknown field(s) {unknown} "
            f"(allowed: {sorted(_DOC_KEYS)})")
    _require(doc, "name", str, source)
    _require(doc, "kind", str, source)
    kind = doc["kind"]
    if kind not in KINDS:
        raise TopologyError(
            f"TopologyIR: {source}: unknown kind {kind!r} (want one of {list(KINDS)})")
    _require(doc, "nodes", int, source)
    nodes = doc["nodes"]
    if nodes <= 0:
        raise TopologyError(f"TopologyIR: {source}: nodes must be > 0, got {nodes}")

    params = doc.get("params", {})
    if not isinstance(params, dict):
        raise TopologyError(f"TopologyIR: {source}: params must be a mapping")
    links = doc.get("links")
    if links is not None and not isinstance(links, list):
        raise TopologyError(f"TopologyIR: {source}: links must be a list of [src, dst]")
    if kind in TEMPLATE_KINDS and links is not None:
        raise TopologyError(
            f"TopologyIR: {source}: kind {kind!r} is a template — links are "
            "generated, not listed (use kind custom/anynet for explicit links)")
    if kind in ("anynet", "custom") and not links:
        raise TopologyError(
            f"TopologyIR: {source}: kind {kind!r} requires explicit links")

    link_attrs = doc.get("link_attrs", {})
    if not isinstance(link_attrs, dict):
        raise TopologyError(f"TopologyIR: {source}: link_attrs must be a mapping")
    # The model carries ONE link spec for the whole topology (`_check_links`
    # treats links as an undirected [u, v] list). An extra key — a per-link
    # list, a width override — cannot be represented, and silently dropping
    # it would simulate a DIFFERENT topology than the one declared. Refuse.
    unknown = sorted(set(link_attrs) - set(LINK_ATTR_KEYS))
    if unknown:
        raise TopologyError(
            f"TopologyIR: {source}: link_attrs has unknown key(s) {unknown}; "
            "link_attrs is the GLOBAL default applied to every link with no "
            "override, so an extra key would be silently dropped and a "
            f"different network simulated. Known keys: "
            f"{sorted(LINK_ATTR_KEYS)}. Per-link overrides belong in the "
            "optional third element of a links entry, not here.")
    for key in LINK_ATTR_KEYS:
        val = link_attrs.get(key)
        if not isinstance(val, (int, float)) or val <= 0:
            raise TopologyError(
                f"TopologyIR: {source}: link_attrs.{key} must be a positive "
                f"number (the analytical leg has no honest fallback), got {val!r}")

    dims = doc.get("dims")
    if dims is not None:
        if not isinstance(dims, list) or not dims:
            raise TopologyError(f"TopologyIR: {source}: dims must be a non-empty list")
        total = 1
        for i, dim in enumerate(dims):
            if not isinstance(dim, dict):
                raise TopologyError(f"TopologyIR: {source}: dims[{i}] must be a mapping")
            for key in ("topology", "count", "bandwidth_GBs", "latency_ns"):
                if dim.get(key) is None:
                    raise TopologyError(
                        f"TopologyIR: {source}: dims[{i}] missing {key!r}")
            if not isinstance(dim["count"], int) or dim["count"] <= 0:
                raise TopologyError(
                    f"TopologyIR: {source}: dims[{i}].count must be a positive int")
            total *= dim["count"]
        if total != nodes:
            raise TopologyError(
                f"TopologyIR: {source}: dims product {total} != nodes {nodes} "
                "(analytical npus_count multiplies per dimension)")

    routing = doc.get("routing")
    if routing is not None and (not isinstance(routing, str) or not routing):
        raise TopologyError(f"TopologyIR: {source}: routing must be a non-empty string")
    booksim_params = doc.get("booksim_params", {})
    if not isinstance(booksim_params, dict):
        raise TopologyError(f"TopologyIR: {source}: booksim_params must be a mapping")
    rtl = doc.get("rtl", {})
    if not isinstance(rtl, dict):
        raise TopologyError(f"TopologyIR: {source}: rtl must be a mapping (passthrough attrs)")

    ir = TopologyIR(
        name=doc["name"], kind=kind, nodes=nodes, params=dict(params),
        links=list(links) if links is not None else None,
        link_attrs=dict(link_attrs),
        dims=[dict(d) for d in dims] if dims is not None else None,
        routing=routing, booksim_params=dict(booksim_params), rtl=dict(rtl),
    )
    _check_counts(ir, source)
    if ir.links is not None:
        _check_links(ir, source)
    return ir

def _require(doc: dict, key: str, typ: type, source: str) -> None:
    val = doc.get(key)
    if not isinstance(val, typ) or (typ is str and not val):
        raise TopologyError(
            f"TopologyIR: {source}: missing/invalid {key!r} (want non-empty {typ.__name__})")

def _int_param(ir: TopologyIR, key: str, default: int, source: str) -> int:
    val = ir.params.get(key, default)
    if not isinstance(val, int) or val <= 0:
        raise TopologyError(
            f"TopologyIR: {source}: params.{key} must be a positive int, got {val!r}")
    return val

def _check_counts(ir: TopologyIR, source: str) -> None:
    """Template param <-> node-count consistency."""
    if ir.kind in ("mesh", "torus"):
        k = _int_param(ir, "k", 0, source) if "k" in ir.params else None
        n = _int_param(ir, "n", 0, source) if "n" in ir.params else None
        if k is None or n is None:
            raise TopologyError(
                f"TopologyIR: {source}: kind {ir.kind!r} requires params.k/n")
        if k ** n != ir.nodes:
            raise TopologyError(
                f"TopologyIR: {source}: k^n = {k}^{n} = {k ** n} != nodes {ir.nodes}")
    elif ir.kind == "ring":
        n = _int_param(ir, "n", ir.nodes, source)
        if n != ir.nodes:
            raise TopologyError(
                f"TopologyIR: {source}: ring params.n {n} != nodes {ir.nodes}")
    elif ir.kind in ("star", "switch"):
        leaves = _int_param(ir, "leaves", ir.nodes - 1, source)
        if leaves + 1 != ir.nodes:
            raise TopologyError(
                f"TopologyIR: {source}: {ir.kind} leaves+1 = {leaves + 1} "
                f"!= nodes {ir.nodes} (hub counts as a node)")

def _parse_link(item: Any, nodes: int, index: int, source: str) -> Link:
    """Validate ONE links entry's shape and lower it to a `Link`.

    Shape only: the three representable forms are accepted here. A value the
    model cannot carry (unknown opts key, out-of-range id, empty tap list) is
    refused, because accepting-and-dropping it would simulate a different
    topology than the one declared.
    """
    where = f"TopologyIR: {source}: links[{index}]"
    if not isinstance(item, (list, tuple)) or len(item) not in (2, 3):
        raise TopologyError(
            f"{where} must be [src, dst], [src, dst, opts] or "
            f"[src, taps, opts], got {item!r}")
    src = item[0]
    if isinstance(src, bool) or not isinstance(src, int):
        raise TopologyError(f"{where} source must be an int router id, got {src!r}")
    _check_router_id(where, "source", src, nodes)
    body = item[1]
    opts = item[2] if len(item) == 3 else {}
    if not isinstance(opts, dict):
        raise TopologyError(
            f"{where} third element must be an opts mapping, got {opts!r}")
    unknown = sorted(set(opts) - set(LINK_OPTS_KEYS))
    if unknown:
        raise TopologyError(
            f"{where} has unknown opts {unknown} "
            f"(known: {sorted(LINK_OPTS_KEYS)})")
    directed = opts.get("directed", False)
    if not isinstance(directed, bool):
        raise TopologyError(
            f"{where} opts.directed must be a bool, got {directed!r}")
    shared = isinstance(body, (list, tuple))
    if shared:
        taps = list(body)
        if not taps:
            raise TopologyError(f"{where} is a shared wire with no taps")
        for tap in taps:
            if isinstance(tap, bool) or not isinstance(tap, int):
                raise TopologyError(
                    f"{where} taps must be int router ids, got {tap!r}")
            _check_router_id(where, "tap", tap, nodes)
            if tap == src:
                raise TopologyError(f"{where} tap {tap} is the driver")
        if len(set(taps)) != len(taps):
            raise TopologyError(f"{where} has duplicate taps {taps}")
        # A shared wire has one driver and many sinks: inherently one-way.
        directed = True
    else:
        if isinstance(body, bool) or not isinstance(body, int):
            raise TopologyError(
                f"{where} destination must be an int router id, got {body!r}")
        _check_router_id(where, "destination", body, nodes)
        if body == src:
            raise TopologyError(f"{where} is a self-loop ({src})")
        taps = [body]
    for name in ("bandwidth_GBs", "latency_ns"):
        val = opts.get(name)
        if val is not None and (isinstance(val, bool)
                                or not isinstance(val, (int, float))
                                or val <= 0):
            raise TopologyError(
                f"{where} opts.{name} must be a positive number, got {val!r}")
    return Link(src=src, sinks=tuple(taps), shared=shared, directed=directed,
                bandwidth_GBs=opts.get("bandwidth_GBs"),
                latency_ns=opts.get("latency_ns"))

def _check_router_id(where: str, role: str, rid: int, nodes: int) -> None:
    if not 0 <= rid < nodes:
        raise TopologyError(f"{where} {role} {rid} out of range [0, {nodes})")

def _check_links(ir: TopologyIR, source: str) -> None:
    """Shape validation only, plus overlap detection.

    Direction, per-link opts and shared wires are all representable now, so
    refusing them here would be a door refusal. What the model still cannot
    represent is refused: unknown opts, bad ids, and a pair declared both
    undirected and directed.
    """
    seen: dict[tuple, int] = {}
    undirected: dict[tuple[int, int], int] = {}
    for i, item in enumerate(ir.links or []):
        link = _parse_link(item, ir.nodes, i, source)
        if link.shared:
            key = ("shared", link.src, tuple(sorted(link.sinks)))
            if key in seen:
                raise TopologyError(
                    f"TopologyIR: {source}: links[{i}] duplicates the shared "
                    f"wire of links[{seen[key]}] (driver {link.src})")
            seen[key] = i
            continue
        src, dst = link.src, link.dst
        canonical = (min(src, dst), max(src, dst))
        if link.directed:
            if canonical in undirected:
                raise TopologyError(
                    f"TopologyIR: {source}: links[{i}] declares directed "
                    f"{src}->{dst}, but links[{undirected[canonical]}] already "
                    "declares an undirected link between them")
            key = ("directed", src, dst)
        else:
            if ("directed", src, dst) in seen or ("directed", dst, src) in seen:
                raise TopologyError(
                    f"TopologyIR: {source}: links[{i}] declares an undirected "
                    f"link between {src} and {dst}, but a directed link "
                    "already declares one direction")
            undirected[canonical] = i
            key = ("undirected", canonical[0], canonical[1])
        if key in seen:
            raise TopologyError(
                f"TopologyIR: {source}: links[{i}] duplicates links["
                f"{seen[key]}] ({key[1]}, {key[2]})")
        seen[key] = i

def expand(ir: TopologyIR) -> Materialized:
    """Materialize nodes + validated links for any kind."""
    if ir.kind in ("mesh", "torus"):
        return _expand_grid(ir, wrap=(ir.kind == "torus"))
    if ir.kind == "ring":
        n = ir.params.get("n", ir.nodes)
        return Materialized(
            nodes=list(range(ir.nodes)),
            links=[Link(src=i, sinks=((i + 1) % n,)) for i in range(n)])
    if ir.kind in ("star", "switch"):
        leaves = ir.params.get("leaves", ir.nodes - 1)
        hub = leaves
        return Materialized(
            nodes=list(range(ir.nodes)),
            links=[Link(src=i, sinks=(hub,)) for i in range(leaves)])
    return Materialized(
        nodes=list(range(ir.nodes)),
        links=[_parse_link(item, ir.nodes, i, "<expand>")
               for i, item in enumerate(ir.links or [])])

def _expand_grid(ir: TopologyIR, wrap: bool) -> Materialized:
    k, n = ir.params["k"], ir.params["n"]
    edges: set[tuple[int, int]] = set()
    for node in range(ir.nodes):
        for dim in range(n):
            stride = k ** dim
            coord = (node // stride) % k
            if coord > 0:
                edges.add(_key(node, node - stride))
            elif wrap and k > 1:
                edges.add(_key(node, node + stride * (k - 1)))
            if coord < k - 1:
                edges.add(_key(node, node + stride))
            elif wrap and k > 1:
                edges.add(_key(node, node - stride * (k - 1)))
    return Materialized(
        nodes=list(range(ir.nodes)),
        links=[Link(src=u, sinks=(v,)) for u, v in sorted(edges)])

def _key(u: int, v: int) -> tuple[int, int]:
    return (min(u, v), max(u, v))

def link_latency_cycles(link: Link, ir: TopologyIR, base_cycles: int) -> int:
    """This link's latency in cycles, relative to the global default.

    The IR carries latency in ns; the artifact carries whole cycles. The
    global `link_attrs.latency_ns` is the baseline, whose cycle value is
    `base_cycles`, so a link declared twice as slow becomes twice as many
    cycles. A link with no override is the baseline.
    """
    base_ns = ir.link_attrs.get("latency_ns")
    ns = link.latency_ns if link.latency_ns is not None else base_ns
    if not base_ns or ns is None:
        return base_cycles
    return max(1, round(base_cycles * (ns / base_ns)))

def link_width_bits(link: Link, ir: TopologyIR, base_width: int) -> int:
    """This link's width in bits, relative to the global default bandwidth.

    Same relative rule as latency: the global bandwidth is the baseline whose
    width is `base_width`, so a link with twice the bandwidth is twice as wide.
    """
    base_bw = ir.link_attrs.get("bandwidth_GBs")
    bw = link.bandwidth_GBs if link.bandwidth_GBs is not None else base_bw
    if not base_bw or bw is None:
        return base_width
    return max(1, round(base_width * (bw / base_bw)))

def stats(ir: TopologyIR, m: Materialized | None = None) -> dict:
    """Fabric stats over the materialized graph (BFS diameter)."""
    m = m or expand(ir)
    adj = m.adjacency()
    degrees = {v: len(adj[v]) for v in m.nodes}
    hist: dict[int, int] = {}
    for d in degrees.values():
        hist[d] = hist.get(d, 0) + 1
    diam, components = _diameter(adj, m.nodes)
    edge_count = len(m.edge_pairs())
    return {
        "name": ir.name,
        "kind": ir.kind,
        "nodes": len(m.nodes),
        "edges": edge_count,
        "avg_degree": round(2 * edge_count / len(m.nodes), 3) if m.nodes else 0.0,
        "max_degree": max(degrees.values()) if degrees else 0,
        "degree_histogram": {str(k): hist[k] for k in sorted(hist)},
        "connected": components == 1,
        "components": components,
        "diameter": diam,
    }

def _diameter(adj: dict[int, set[int]], nodes: list[int]) -> tuple[int | None, int]:
    """Max eccentricity via BFS from every node; components counted."""
    seen_global: set[int] = set()
    components = 0
    diameter = 0
    for src in nodes:
        if src in seen_global:
            continue
        components += 1
        dist = {src: 0}
        queue = deque([src])
        while queue:
            cur = queue.popleft()
            for nxt in adj[cur]:
                if nxt not in dist:
                    dist[nxt] = dist[cur] + 1
                    queue.append(nxt)
        seen_global |= set(dist)
        diameter = max(diameter, max(dist.values()))
    return (diameter if components == 1 else None, components)

def render_ascii(ir: TopologyIR, m: Materialized | None = None,
                 max_nodes: int = 32) -> str:
    """Human-readable adjacency (refuses large fabrics — use stats)."""
    m = m or expand(ir)
    if len(m.nodes) > max_nodes:
        raise TopologyError(
            f"TopologyIR: ascii render capped at {max_nodes} nodes "
            f"({len(m.nodes)} requested) — use stats or format anynet")
    adj = m.adjacency()
    lines = [f"{ir.name} [{ir.kind}] nodes={len(m.nodes)} "
             f"edges={len(m.edge_pairs())}"]
    for v in m.nodes:
        lines.append(f"  {v}: {' '.join(map(str, sorted(adj[v])))}")
    return "\n".join(lines) + "\n"

def to_anynet(ir: TopologyIR, m: Materialized | None = None) -> str:
    """BookSim anynet links text — one directed line per link.

    A directed link appears on its source's line only; an undirected link on
    both. A shared wire is a `multidrop` line (one driver, many taps). A
    per-link latency override is emitted as that channel's weight; a link
    with no override keeps the default and carries no weight token.
    """
    m = m or expand(ir)
    out: dict[int, list[tuple[int, int]]] = {v: [] for v in m.nodes}
    shared: list[Link] = []
    for link in m.links:
        if link.shared:
            shared.append(link)
            continue
        weight = _anynet_weight(link, ir)
        for dst in link.sinks:
            out[link.src].append((dst, weight))
            if not link.directed:
                out[dst].append((link.src, weight))
    lines = []
    for v in m.nodes:
        peers = " ".join(
            f"router {p}" + ("" if w is None else f" {w}")
            for p, w in sorted(out[v], key=lambda pw: (pw[0], -1 if pw[1] is None else pw[1])))
        lines.append(f"router {v} node {v} {peers}".rstrip())
    for link in shared:
        taps = " ".join(f"router {t}" for t in link.sinks)
        weight = _anynet_weight(link, ir)
        tail = "" if weight is None else f" {weight}"
        lines.append(f"multidrop {link.src} {taps}{tail}".rstrip())
    return "\n".join(lines) + "\n"

def _anynet_weight(link: Link, ir: TopologyIR) -> int | None:
    """This link's anynet weight, or None for the default (no token)."""
    if link.latency_ns is None:
        return None
    return link_latency_cycles(link, ir, base_cycles=1)

def to_booksim_cfg(ir: TopologyIR, m: Materialized | None = None,
                    network_file: str | None = None) -> str:
    """BookSim cfg text for the ASTRA embedded leg (and standalone runs).

Rationale: docs/decisions/modules/model.md
    """
    m = m or expand(ir)
    params = dict(BOOKSIM_DEFAULTS)
    params.update(ir.booksim_params)
    lines = [f"// generated by TopologyIR v0: {ir.name} [{ir.kind}]",
             "// ASTRA embedded use requires --booksim2-extra=injection_rate=0.0"]
    for key in ("num_vcs", "vc_buf_size", "packet_size",
                "wait_for_tail_credit", "vc_allocator", "sw_allocator",
                "alloc_iters", "credit_delay", "routing_delay",
                "vc_alloc_delay", "sw_alloc_delay", "input_speedup",
                "output_speedup", "internal_speedup"):
        lines.append(f"{key} = {params[key]};")
    if ir.kind == "mesh":
        lines.append(f"k = {ir.params['k']};")
        lines.append(f"n = {ir.params['n']};")
    elif ir.kind in ("torus", "ring"):
        k = ir.params["k"] if ir.kind == "torus" else ir.params.get("n", ir.nodes)
        lines.append(f"k = {k};")
        lines.append("n = 1;")
    lines.append("traffic = uniform;")
    lines.append(f"total_nodes = {ir.nodes};")
    if ir.kind in ("mesh", "torus", "ring"):
        topo = "mesh" if ir.kind == "mesh" else "torus"
        lines.append(f"topology = {topo};")
    else:
        if not network_file:
            raise TopologyError(
                f"TopologyIR: kind {ir.kind!r} needs a links file — write "
                "to_anynet() output and pass network_file=<path>")
        lines.append("topology = anynet;")
        lines.append(f"network_file = {network_file};")
    lines.append(f"routing_function = {ir.effective_routing};")
    return "\n".join(lines) + "\n"

def to_analytical_yml(ir: TopologyIR) -> str:
    """ASTRA analytical network yml (per-dim topology/count/bandwidth/latency).

    Uses explicit dims when given; otherwise a single dim derived from
    link_attrs (mesh/torus/ring -> Ring, star/switch -> Switch). anynet/
    custom without dims fail — no honest topology-name guess exists.
    """
    dims = ir.dims or _default_dims(ir)
    lines = []
    lines.append(f"topology: [{', '.join(_yml_name(d['topology']) for d in dims)}]")
    lines.append(f"npus_count: [{', '.join(str(d['count']) for d in dims)}]")
    lines.append(f"bandwidth: [{', '.join(_yml_num(d['bandwidth_GBs']) for d in dims)}]")
    lines.append(f"latency: [{', '.join(_yml_num(d['latency_ns']) for d in dims)}]")
    return "\n".join(lines) + "\n"

def _default_dims(ir: TopologyIR) -> list[dict]:
    topo = ANALYTICAL_TOPO[ir.kind]
    if topo is None:
        raise TopologyError(
            f"TopologyIR: kind {ir.kind!r} needs explicit dims for the "
            "analytical leg (no honest topology-name guess for arbitrary graphs)")
    return [{"topology": topo, "count": ir.nodes,
             "bandwidth_GBs": ir.link_attrs["bandwidth_GBs"],
             "latency_ns": ir.link_attrs["latency_ns"]}]

def _yml_name(topology: str) -> str:
    return str(topology)

def _yml_num(val: Any) -> str:
    return f"{float(val):.1f}" if float(val).is_integer() else str(val)

def to_preset(ir: TopologyIR) -> PresetTopology:
    """Bridge to model.presets.Topology (mesh/torus/ring only).

    Lets existing build_config()/run machinery consume IR directly.
    star/switch/anynet/custom have no preset backend — use the anynet
    file path (to_anynet + cfg with network_file) instead.
    """
    if ir.kind == "mesh":
        return PresetTopology(ir.name, "mesh", ir.effective_routing,
                              {"k": ir.params["k"], "n": ir.params["n"]})
    if ir.kind == "torus":
        return PresetTopology(ir.name, "torus", ir.effective_routing,
                              {"k": ir.params["k"], "n": ir.params["n"]})
    if ir.kind == "ring":
        return PresetTopology(ir.name, "torus", ir.effective_routing,
                              {"k": ir.params.get("n", ir.nodes), "n": 1})
    raise TopologyError(
        f"TopologyIR: kind {ir.kind!r} has no presets.Topology backend — "
        "translate via to_anynet() + network_file cfg")

def divergence_report(booksim_cycles: int, analytical_cycles: int) -> dict:
    """Pure divergence math for the diff harness (testable without binaries)."""
    if booksim_cycles <= 0 or analytical_cycles <= 0:
        raise TopologyError(
            "TopologyIR: divergence needs positive cycle counts, got "
            f"booksim={booksim_cycles} analytical={analytical_cycles}")
    denom = max(booksim_cycles, analytical_cycles)
    pct = abs(booksim_cycles - analytical_cycles) / denom * 100.0
    verdict = "agree" if pct < 5 else ("close" if pct < 20 else "diverge")
    return {
        "booksim_cycles": booksim_cycles,
        "analytical_cycles": analytical_cycles,
        "ratio_booksim_over_analytical": round(booksim_cycles / analytical_cycles, 4),
        "divergence_pct": round(pct, 2),
        "verdict": verdict,
    }
