"""veritx_dse.model.topology_ir — TopologyIR v0: one topology, every backend.

A TopologyIR document is a single JSON file describing a fabric once;
translators lower it to each consumer's native format:

  - BookSim cfg (+ .anynet links file for anynet kinds)  -> to_booksim_cfg
  - ASTRA analytical network yml (Ring/Switch per-dim lists) -> to_analytical_yml
  - BookSim anynet links text (gen_star.py format)        -> to_anynet
  - presets.Topology bridge (mesh/torus/ring only)        -> to_preset

Schema vocabulary is InfraGraph-aligned: a fabric is NODES with optional
attrs joined by LINKS with attrs. Template kinds (mesh/torus/ring/star/
switch) expand to materialized nodes+edges; anynet/custom carry explicit
links. ``rtl`` is passthrough attrs for the RTL leg (carried, validated as
a mapping, unused by v0 translators).

Errors raise TopologyError (core.errors) with the file/field named — never
a silent default. In particular:

  - link_attrs.bandwidth_GBs / latency_ns are REQUIRED (the analytical leg
    has no honest fallback);
  - anynet/custom REQUIRE explicit ``dims`` for the yml leg (no honest
    topology-name guess for arbitrary graphs);
  - template kinds REJECT explicit ``links`` (one source of truth).
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
TEMPLATE_KINDS = ("mesh", "torus", "ring", "star", "switch")

#: The closed document schema. Anything outside this set is refused.
_DOC_KEYS = frozenset({
    "name", "kind", "nodes", "params", "links", "link_attrs", "dims",
    "routing", "booksim_params", "rtl",
})

# BookSim routing default per kind. anynet kinds use "min" — mirrors
# cli._write_anynet_cfg (arbitrary graphs have no DOR axes).
DEFAULT_ROUTING = {
    "mesh": "dim_order",
    "torus": "dim_order",
    "ring": "dim_order",
    "star": "min",
    "switch": "min",
    "anynet": "min",
    "custom": "min",
}

# Analytical-leg topology name per kind (None = caller must give dims).
ANALYTICAL_TOPO = {
    "mesh": "Ring",
    "torus": "Ring",
    "ring": "Ring",
    "star": "Switch",
    "switch": "Switch",
    "anynet": None,
    "custom": None,
}

# BookSim cfg defaults. Canonical source is simulation.booksim.BASE_PARAMS
# (model must not import simulation — layering); test_topology_ir asserts
# this dict stays equal to BASE_PARAMS so the two can never drift silently.
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

        INCLUDED: kind, nodes, links, link_attrs. These are the exact
        connectivity semantics; changing any of them changes the design.

        EXCLUDED, deliberately:

          * ``name`` — a LABEL. A synthesized candidate is named
            ``synthesized-<id>`` and the identical hand-authored graph is
            named whatever the user typed. Hashing the name would make
            origin part of design identity, so the same scientific graph
            authored and synthesized would hash differently. That is the
            ownership error this method exists to prevent.
          * ``routing`` / ``booksim_params`` / ``rtl`` — backend and
            collateral POLICY, not graph science.
          * ``dims`` — an analytical-leg projection, not canonical
            connectivity.
        """
        return {
            "kind": self.kind,
            "nodes": self.nodes,
            "links": [list(e) for e in (self.links or [])],
            "link_attrs": dict(sorted(self.link_attrs.items())),
        }


@dataclass
class Materialized:
    """Expanded fabric: node ids + undirected edges (sorted u<v tuples)."""

    nodes: list[int]
    edges: list[tuple[int, int]]


# ── load / validate ─────────────────────────────────────────────────────

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
    for key in ("bandwidth_GBs", "latency_ns"):
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


def _check_links(ir: TopologyIR, source: str) -> None:
    seen: set[tuple[int, int]] = set()
    for i, link in enumerate(ir.links or []):
        if (not isinstance(link, (list, tuple)) or len(link) != 2
                or not all(isinstance(v, int) for v in link)):
            raise TopologyError(
                f"TopologyIR: {source}: links[{i}] must be [src, dst] ints, got {link!r}")
        u, v = link
        if u == v:
            raise TopologyError(f"TopologyIR: {source}: links[{i}] is a self-loop ({u})")
        for v_ in (u, v):
            if not 0 <= v_ < ir.nodes:
                raise TopologyError(
                    f"TopologyIR: {source}: links[{i}] endpoint {v_} out of "
                    f"range [0, {ir.nodes})")
        key = (min(u, v), max(u, v))
        if key in seen:
            raise TopologyError(
                f"TopologyIR: {source}: links[{i}] duplicates {key} (undirected)")
        seen.add(key)


# ── expand ──────────────────────────────────────────────────────────────

def expand(ir: TopologyIR) -> Materialized:
    """Materialize nodes + undirected edges for any kind."""
    if ir.kind in ("mesh", "torus"):
        return _expand_grid(ir, wrap=(ir.kind == "torus"))
    if ir.kind == "ring":
        n = ir.params.get("n", ir.nodes)
        return Materialized(
            nodes=list(range(ir.nodes)),
            edges=[(i, (i + 1) % n) for i in range(n)])
    if ir.kind in ("star", "switch"):
        leaves = ir.params.get("leaves", ir.nodes - 1)
        hub = leaves
        return Materialized(
            nodes=list(range(ir.nodes)),
            edges=[(i, hub) for i in range(leaves)])
    # anynet / custom: symmetrize explicit links (deduped by validation).
    edges = sorted({(min(u, v), max(u, v)) for u, v in (ir.links or [])})
    return Materialized(nodes=list(range(ir.nodes)), edges=edges)


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
    return Materialized(nodes=list(range(ir.nodes)), edges=sorted(edges))


def _key(u: int, v: int) -> tuple[int, int]:
    return (min(u, v), max(u, v))


# ── stats / render ──────────────────────────────────────────────────────

def stats(ir: TopologyIR, m: Materialized | None = None) -> dict:
    """Fabric stats over the materialized graph (BFS diameter)."""
    m = m or expand(ir)
    adj: dict[int, set[int]] = {v: set() for v in m.nodes}
    for u, v in m.edges:
        adj[u].add(v)
        adj[v].add(u)
    degrees = {v: len(adj[v]) for v in m.nodes}
    hist: dict[int, int] = {}
    for d in degrees.values():
        hist[d] = hist.get(d, 0) + 1
    diam, components = _diameter(adj, m.nodes)
    edge_count = len(m.edges)
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
    adj: dict[int, list[int]] = {v: [] for v in m.nodes}
    for u, v in m.edges:
        adj[u].append(v)
        adj[v].append(u)
    lines = [f"{ir.name} [{ir.kind}] nodes={len(m.nodes)} edges={len(m.edges)}"]
    for v in m.nodes:
        lines.append(f"  {v}: {' '.join(map(str, sorted(adj[v])))}")
    return "\n".join(lines) + "\n"


# ── translators ─────────────────────────────────────────────────────────

def to_anynet(ir: TopologyIR, m: Materialized | None = None) -> str:
    """BookSim anynet links text (gen_star.py line format, generalized)."""
    m = m or expand(ir)
    adj: dict[int, list[int]] = {v: [] for v in m.nodes}
    for u, v in m.edges:
        adj[u].append(v)
        adj[v].append(u)
    lines = []
    for v in m.nodes:
        peers = " ".join(f"router {p}" for p in sorted(adj[v]))
        lines.append(f"router {v} node {v} {peers}".rstrip())
    return "\n".join(lines) + "\n"


def to_booksim_cfg(ir: TopologyIR, m: Materialized | None = None,
                    network_file: str | None = None) -> str:
    """BookSim cfg text for the ASTRA embedded leg (and standalone runs).

    anynet kinds (star/switch/anynet/custom) REQUIRE network_file — the
    caller writes to_anynet() output and passes its path (absolute at run
    time; astrasim_adapter absolutizes). No injection_rate is emitted:
    standalone runs set their own, and the ASTRA leg MUST pass
    --booksim2-extra=injection_rate=0.0 (embedded mode owns injection).
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
        # BookSim has no ring topology: a 1-D torus (k=N, n=1) is a ring.
        k = ir.params["k"] if ir.kind == "torus" else ir.params.get("n", ir.nodes)
        lines.append(f"k = {k};")
        lines.append("n = 1;")
    lines.append("traffic = uniform;")
    # Explicit node count for parse_booksim_cfg (closed-form-free topologies
    # must not be guessed). The ASTRA path strips it via _write_sanitized_cfg
    # — BookSim's own parser rejects unknown fields.
    lines.append(f"total_nodes = {ir.nodes};")
    # Topology + routing come last (after k/n) — mirrors build_config(),
    # whose ordering comment marks this as load-bearing for BookSim.
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
    # House style matches ASTRA examples (50.0, 500.0, 936.25): always a
    # float rendering. Semantically identical either way (YAML ints parse
    # to the same double in yaml-cpp), this is purely cosmetic parity.
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


# ── diff report ─────────────────────────────────────────────────────────

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
