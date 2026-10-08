"""Source-legal GEC hybrid candidates and their topology-bound union route.

Credit selects mesh versus MECS afresh at every hop; both are modeled. VC
eligibility is X/Y phase followed by tap slice, not an invented escape role.
The verifier owns acyclicity; this module owns the executable route relation.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Mapping

from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import SemanticError
from veritx_dse.model.shared_resource import (
    ResourceKind, ResourceRef, ResourceVC, RouteDecision,
)
from veritx_dse.model.topology_artifact import (
    MaterializedFamily, TopologyArtifact, materialize_gec_hybrid,
)

GEC_HYBRID_ROUTING_CLASS = "GEC_HYBRID_XY_CANDIDATE_UNION"


class GecHybridCandidateError(ValueError, SemanticError):
    """Malformed GEC hybrid parameters, topology binding, or candidates."""


@dataclass(frozen=True)
class GecHybridParams:
    k: int
    c: int
    o: int
    d: int
    num_vcs: int

    def __post_init__(self):
        for name, minimum in (("k", 2), ("c", 1), ("o", 1),
                              ("d", 1), ("num_vcs", 1)):
            if type(getattr(self, name)) is not int or getattr(self, name) < minimum:
                raise GecHybridCandidateError(f"{name} must be an exact int >= {minimum}")
        if self.o * self.d != self.k - 1:
            raise GecHybridCandidateError("GEC requires o*d == k-1")
        if self.num_vcs < 2 * self.d:
            raise GecHybridCandidateError(
                f"hybrid_gec requires num_vcs >= 2*d ({2 * self.d})")
        if self.vcs_per_tap < 1:
            raise GecHybridCandidateError("hybrid_gec phase half leaves no VC per MECS tap")

    @property
    def router_count(self):
        return self.k * self.k

    @property
    def node_count(self):
        return self.router_count * self.c

    @property
    def phase_vcs(self):
        half = self.num_vcs // 2
        return tuple(range(half)), tuple(range(half, 2 * half))

    @property
    def vcs_per_tap(self):
        return (self.num_vcs // 2) // self.d

    @property
    def port_stride(self):
        return self.c + 4 + 2 * self.o

    @property
    def allowed_transitions(self):
        x, y = self.phase_vcs
        return tuple(sorted((a, b) for phase_in, incoming in enumerate((x, y))
                            for phase_out, outgoing in enumerate((x, y))
                            if phase_in <= phase_out for a in incoming for b in outgoing))

    def to_dict(self):
        return {name: getattr(self, name) for name in ("k", "c", "o", "d", "num_vcs")}


@dataclass(frozen=True)
class GecHybridCandidate:
    resource: ResourceRef
    next_router: int
    phase: int
    vcs: tuple[int, ...]
    out_port: int
    tap: int | None = None
    mesh_hops: int = 1

    @property
    def is_mesh(self):
        return self.resource.kind is ResourceKind.CHANNEL


def _mesh_degree(x, y, k):
    return int(x > 0) + int(x < k - 1) + int(y > 0) + int(y < k - 1)


def _mesh_port_offset(x, y, k, direction):
    present = tuple(d for d, yes in (("W", x > 0), ("E", x < k - 1),
                                    ("N", y > 0), ("S", y < k - 1)) if yes)
    return present.index(direction)


def gec_hybrid_candidates(params: GecHybridParams, *, src_router: int,
                          dest_node: int) -> tuple[GecHybridCandidate, ...]:
    """The two outputs of networks/gec.cpp::hybrid_gec, before credit choice."""
    if not isinstance(params, GecHybridParams):
        raise GecHybridCandidateError("params must be GecHybridParams")
    if type(src_router) is not int or not 0 <= src_router < params.router_count:
        raise GecHybridCandidateError("src_router is outside the GEC grid")
    if type(dest_node) is not int or not 0 <= dest_node < params.node_count:
        raise GecHybridCandidateError("dest_node is outside the GEC terminals")
    dest_router = dest_node // params.c
    if src_router == dest_router:
        return ()
    k, c, o, d = params.k, params.c, params.o, params.d
    x, y = src_router % k, src_router // k
    dx, dy = dest_router % k, dest_router // k
    phase = 0 if x != dx else 1
    degree = _mesh_degree(x, y, k)
    if phase == 0:
        direction = "E" if dx > x else "W"
        distance = abs(dx - x)
        mesh_next = y * k + x + (1 if dx > x else -1)
        peer_idx = dx if dx < x else dx - 1
        mecs_next = y * k + dx
        base = c + degree
    else:
        direction = "S" if dy > y else "N"
        distance = abs(dy - y)
        mesh_next = (y + (1 if dy > y else -1)) * k + x
        peer_idx = dy if dy < y else dy - 1
        mecs_next = dy * k + x
        base = c + degree + o
    mesh_port = c + _mesh_port_offset(x, y, k, direction)
    group, tap = divmod(peer_idx, d)
    mecs_port = base + group
    start = phase * (params.num_vcs // 2) + tap * params.vcs_per_tap
    return (
        GecHybridCandidate(ResourceRef(ResourceKind.CHANNEL,
                                      src_router * params.port_stride + mesh_port),
                           mesh_next, phase, params.phase_vcs[phase], mesh_port,
                           mesh_hops=distance),
        GecHybridCandidate(ResourceRef(ResourceKind.SHARED_LINK,
                                      src_router * params.port_stride + mecs_port),
                           mecs_next, phase, tuple(range(start, start + params.vcs_per_tap)),
                           mecs_port, tap=tap),
    )


def select_gec_hybrid_candidate(*, mesh_used_credit: int, mecs_used_credit: int,
                                mesh_hops: int) -> str:
    for name, value in (("mesh_used_credit", mesh_used_credit),
                        ("mecs_used_credit", mecs_used_credit), ("mesh_hops", mesh_hops)):
        minimum = 1 if name == "mesh_hops" else 0
        if type(value) is not int or value < minimum:
            raise GecHybridCandidateError(f"{name} must be an exact int >= {minimum}")
    return "mesh" if mesh_used_credit * mesh_hops < mecs_used_credit else "mecs"


def bound_gec_hybrid_candidates(params, topology):
    """Bind source ports/taps to real artifact resources, never port-offset IDs."""
    if not isinstance(topology, TopologyArtifact) or topology.family is not MaterializedFamily.GEC_HYBRID:
        raise GecHybridCandidateError("topology must be GEC_HYBRID")
    expected = materialize_gec_hybrid(k=params.k, concentration=params.c, o=params.o, d=params.d)
    channels = {(ch.src_router, ch.dst_router): ch for ch in topology.channels}
    wires = {(w.src_router, w.taps): w for w in topology.shared_links}
    if topology.routers != expected.routers or len(channels) != len(topology.channels) or set(channels) != {
            (ch.src_router, ch.dst_router) for ch in expected.channels}:
        raise GecHybridCandidateError("hybrid mesh geometry does not match params")
    if len(wires) != len(topology.shared_links) or set(wires) != {
            (w.src_router, w.taps) for w in expected.shared_links}:
        raise GecHybridCandidateError("hybrid shared wire tap ordering does not match params")
    result = {}
    for src in range(params.router_count):
        x, y = src % params.k, src // params.k
        for dest in range(params.node_count):
            options = []
            for hop in gec_hybrid_candidates(params, src_router=src, dest_node=dest):
                if hop.is_mesh:
                    resource = ResourceRef(ResourceKind.CHANNEL, channels[(src, hop.next_router)].channel_id)
                else:
                    coord = x if hop.phase == 0 else y
                    target = hop.next_router % params.k if hop.phase == 0 else hop.next_router // params.k
                    peers = [q for q in range(params.k) if q != coord]
                    group = peers.index(target) // params.d
                    selected = peers[group * params.d:(group + 1) * params.d]
                    taps = tuple(y * params.k + q if hop.phase == 0 else q * params.k + x for q in selected)
                    wire = wires[(src, taps)]
                    if wire.taps[hop.tap] != hop.next_router:
                        raise GecHybridCandidateError("hybrid tap lands on the wrong router")
                    resource = ResourceRef(ResourceKind.SHARED_LINK, wire.shared_link_id)
                options.append(replace(hop, resource=resource))
            result[(src, dest)] = tuple(options)
    return result


@dataclass(frozen=True)
class GecHybridDependencyGraph:
    """Model-owned concrete dependency data; verification owns cycle checks."""

    nodes: tuple[ResourceVC, ...]
    edges: tuple[tuple[ResourceVC, ResourceVC], ...]
    partition_to_vcs: Mapping[int, tuple[int, ...]]


@dataclass(frozen=True)
class GecHybridRoute:
    params: GecHybridParams
    topology_hash: str
    choices: Mapping[tuple[int, int], tuple[RouteDecision, ...]]
    routing_class: str = GEC_HYBRID_ROUTING_CLASS
    schema_version: int = 1

    def __post_init__(self):
        if (not isinstance(self.params, GecHybridParams)
                or not isinstance(self.topology_hash, str) or not self.topology_hash):
            raise GecHybridCandidateError("route needs params and topology_hash")
        if self.routing_class != GEC_HYBRID_ROUTING_CLASS or type(self.schema_version) is not int or self.schema_version != 1:
            raise GecHybridCandidateError("unknown hybrid route class/schema")
        if not isinstance(self.choices, Mapping) or not self.choices:
            raise GecHybridCandidateError("hybrid route needs candidate choices")
        for key, options in self.choices.items():
            if (not isinstance(key, tuple) or len(key) != 2
                    or any(type(v) is not int for v in key)
                    or not 0 <= key[0] < self.params.router_count
                    or not 0 <= key[1] < self.params.node_count
                    or not isinstance(options, tuple) or not options
                    or any(not isinstance(option, RouteDecision) for option in options)):
                raise GecHybridCandidateError("hybrid choices require valid contexts and immutable decision tuples")
        object.__setattr__(self, "choices", MappingProxyType(dict(self.choices)))

    @property
    def routers(self):
        return tuple(range(self.params.router_count))

    @property
    def terminal_to_router(self):
        return {n: n // self.params.c for n in range(self.params.node_count)}

    @property
    def partition_to_vcs(self):
        return {vc: (vc,) for vc in range(self.params.num_vcs)}

    @property
    def allowed_transitions(self):
        return self.params.allowed_transitions

    def canonical_dict(self):
        return {"routing_class": self.routing_class, "topology_hash": self.topology_hash,
                "params": self.params.to_dict(),
                "choices": [[s, d, [option.to_dict() for option in options]]
                            for (s, d), options in sorted(self.choices.items())]}

    def route_artifact_id(self):
        return content_id("srota/GecHybridRoute/v1", self.canonical_dict())

    def validate_against(self, topology):
        if self.topology_hash != topology.topology_hash():
            raise GecHybridCandidateError("hybrid topology_hash mismatch")
        expected = gec_hybrid_route_for_topology(self.params, topology)
        if self.choices != expected.choices:
            raise GecHybridCandidateError("hybrid choices differ from the complete source candidate union")

    def shared_resource_cdg(self) -> GecHybridDependencyGraph:
        nodes, edges = set(), set()
        terminals = self.terminal_to_router
        transitions = set(self.allowed_transitions)
        for (src, dest), options in self.choices.items():
            if src == terminals[dest]:
                continue
            for first in options:
                a = (first.resource, first.vc_partition)
                nodes.add(a)
                if first.next_router == terminals[dest]:
                    continue
                for second in self.choices[(first.next_router, dest)]:
                    b = (second.resource, second.vc_partition)
                    nodes.add(b)
                    if (a[1], b[1]) not in transitions:
                        raise GecHybridCandidateError("hybrid candidate violates phase VC order")
                    edges.add((a, b))
        return GecHybridDependencyGraph(
            tuple(sorted(nodes)), tuple(sorted(edges)),
            MappingProxyType(self.partition_to_vcs))


def gec_hybrid_route_for_topology(params: GecHybridParams,
                                  topology: TopologyArtifact) -> GecHybridRoute:
    candidates = bound_gec_hybrid_candidates(params, topology)
    choices = {}
    for key, options in candidates.items():
        src, dest = key
        if options:
            choices[key] = tuple(RouteDecision(hop.resource, hop.next_router, vc, hop.tap)
                                 for hop in options for vc in hop.vcs)
        else:
            # Ejection has no outgoing dependency; its namespace is outside
            # actual transit channels and is never included in the CDG.
            choices[key] = (RouteDecision(ResourceRef(ResourceKind.CHANNEL,
                                                      len(topology.channels) + dest), src),)
    return GecHybridRoute(params, topology.topology_hash(), choices)
