"""Conservative candidate-union CDG for BookSim ``hybrid_gec``.

The runtime chooses one of two outputs from live credit at each hop. This
module deliberately includes BOTH outputs at every router/destination and
all VC transitions permitted by the source's X-then-Y phase split. Therefore
an acyclic graph is a sound per-instance over-approximation: every runtime
resource dependency is an edge in this graph. A cycle is inconclusive (the
selector may never realize it); this is not an escape-subnetwork proof and
does not model allocator fairness or buffer availability.

Port, tap, cost and VC semantics are transcribed from
``third_party/booksim2/src/networks/gec.cpp`` (``_BuildNetHybrid`` and
``hybrid_gec``). The graph uses stable per-router maximum-port offsets; this
is a route-analysis identity, not yet a canonical hybrid topology artifact.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.core.errors import SemanticError
from veritx_dse.model.shared_resource import (
    ResourceKind, ResourceRef, ResourceVC,
)
from veritx_dse.verification.shared_resource_cdg import SharedResourceCDG

GEC_HYBRID_CANDIDATE_CDG_V1 = "GEC_HYBRID_CANDIDATE_CDG_V1"


class GecHybridCandidateError(ValueError, SemanticError):
    """Malformed GEC hybrid parameters or candidate graph."""


@dataclass(frozen=True)
class GecHybridParams:
    k: int
    c: int
    o: int
    d: int
    num_vcs: int

    def __post_init__(self) -> None:
        for name, minimum in (("k", 2), ("c", 1), ("o", 1),
                              ("d", 1), ("num_vcs", 1)):
            value = getattr(self, name)
            if type(value) is not int or value < minimum:
                raise GecHybridCandidateError(
                    f"{name} must be an exact int >= {minimum}")
        if self.o * self.d != self.k - 1:
            raise GecHybridCandidateError(
                "GEC requires o*d == k-1")
        if self.num_vcs < 2 * self.d:
            raise GecHybridCandidateError(
                f"hybrid_gec requires num_vcs >= 2*d ({2 * self.d})")
        if self.vcs_per_tap < 1:
            raise GecHybridCandidateError(
                "hybrid_gec phase half leaves no VC per MECS tap")

    @property
    def router_count(self) -> int:
        return self.k * self.k

    @property
    def node_count(self) -> int:
        return self.router_count * self.c

    @property
    def phase_vcs(self) -> tuple[tuple[int, ...], tuple[int, ...]]:
        half = self.num_vcs // 2
        return (tuple(range(half)), tuple(range(half, 2 * half)))

    @property
    def vcs_per_tap(self) -> int:
        return (self.num_vcs // 2) // self.d

    @property
    def port_stride(self) -> int:
        # Stable identity despite position-dependent mesh degree.
        return self.c + 4 + 2 * self.o


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
    def is_mesh(self) -> bool:
        return self.resource.kind is ResourceKind.CHANNEL


@dataclass(frozen=True)
class GecHybridCandidateCDG:
    nodes: tuple[ResourceVC, ...]
    edges: tuple[tuple[ResourceVC, ResourceVC], ...]
    candidate_count: int
    vc_count: int

    def find_cycle(self) -> list[ResourceVC] | None:
        return SharedResourceCDG(
            nodes=self.nodes, edges=self.edges, partition_to_vcs={}
        ).find_cycle()

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "proof_method": GEC_HYBRID_CANDIDATE_CDG_V1,
            "nodes": [[resource.to_dict(), vc]
                      for resource, vc in self.nodes],
            "edges": [[[a[0].to_dict(), a[1]],
                       [b[0].to_dict(), b[1]]] for a, b in self.edges],
            "candidate_count": self.candidate_count,
            "vc_count": self.vc_count,
        }


def _mesh_degree(x: int, y: int, k: int) -> int:
    return int(x > 0) + int(x < k - 1) + int(y > 0) + int(y < k - 1)


def _mesh_port_offset(x: int, y: int, k: int, direction: str) -> int:
    present = tuple(d for d, yes in (
        ("W", x > 0), ("E", x < k - 1),
        ("N", y > 0), ("S", y < k - 1)) if yes)
    return present.index(direction)


def gec_hybrid_candidates(
        params: GecHybridParams, *, src_router: int,
        dest_node: int) -> tuple[GecHybridCandidate, ...]:
    """Both source-legal outputs at a nonlocal hybrid routing context."""
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
    mesh_degree = _mesh_degree(x, y, k)
    if phase == 0:
        direction = "E" if dx > x else "W"
        mesh_hops = abs(dx - x)
        mesh_next = y * k + (x + (1 if dx > x else -1))
        peer_idx = dx if dx < x else dx - 1
        mecs_next = y * k + dx
        mecs_base = c + mesh_degree
    else:
        direction = "S" if dy > y else "N"
        mesh_hops = abs(dy - y)
        mesh_next = (y + (1 if dy > y else -1)) * k + x
        peer_idx = dy if dy < y else dy - 1
        mecs_next = dy * k + x
        mecs_base = c + mesh_degree + o

    offset = _mesh_port_offset(x, y, k, direction)
    mesh_port = c + offset
    mecs_group, tap = divmod(peer_idx, d)
    mecs_port = mecs_base + mecs_group
    phase_vcs = params.phase_vcs[phase]
    per_tap = params.vcs_per_tap
    mecs_vcs = tuple(range(phase * (params.num_vcs // 2) + tap * per_tap,
                           phase * (params.num_vcs // 2) +
                           (tap + 1) * per_tap))

    return (
        GecHybridCandidate(
            resource=ResourceRef(ResourceKind.CHANNEL,
                                 src_router * params.port_stride + mesh_port),
            next_router=mesh_next, phase=phase, vcs=phase_vcs,
            out_port=mesh_port, mesh_hops=mesh_hops),
        GecHybridCandidate(
            resource=ResourceRef(ResourceKind.SHARED_LINK,
                                 src_router * params.port_stride + mecs_port),
            next_router=mecs_next, phase=phase, vcs=mecs_vcs,
            out_port=mecs_port, tap=tap),
    )


def select_gec_hybrid_candidate(*, mesh_used_credit: int,
                                mecs_used_credit: int,
                                mesh_hops: int) -> str:
    """Mirror ``mesh_used_credit * H < mecs_used_credit``; ties choose MECS."""
    for name, value in (("mesh_used_credit", mesh_used_credit),
                        ("mecs_used_credit", mecs_used_credit),
                        ("mesh_hops", mesh_hops)):
        minimum = 1 if name == "mesh_hops" else 0
        if type(value) is not int or value < minimum:
            raise GecHybridCandidateError(
                f"{name} must be an exact int >= {minimum}")
    return ("mesh" if mesh_used_credit * mesh_hops < mecs_used_credit
            else "mecs")


def build_gec_hybrid_candidate_cdg(
        params: GecHybridParams) -> GecHybridCandidateCDG:
    """Build the union of all possible consecutive resource/VC dependencies.

    Both alternatives are included at every hop. The source's phase order
    permits X->X, X->Y, and Y->Y VC transitions; Y->X is impossible because
    the router resolves X before Y. Thus an acyclic result proves the exact
    runtime-selected route subset is acyclic for this parameter instance.
    """
    if not isinstance(params, GecHybridParams):
        raise GecHybridCandidateError("params must be GecHybridParams")
    hops: dict[tuple[int, int], tuple[GecHybridCandidate, ...]] = {}
    node_set: set[ResourceVC] = set()
    candidate_count = 0
    for src in range(params.router_count):
        for dest in range(params.node_count):
            row = gec_hybrid_candidates(params, src_router=src,
                                        dest_node=dest)
            hops[(src, dest)] = row
            candidate_count += len(row)
            for hop in row:
                node_set.update((hop.resource, vc) for vc in hop.vcs)

    edges: set[tuple[ResourceVC, ResourceVC]] = set()
    for (_src, dest), first_hops in hops.items():
        for first in first_hops:
            next_hops = hops[(first.next_router, dest)]
            for second in next_hops:
                if first.phase > second.phase:
                    raise GecHybridCandidateError(
                        "candidate route violates X-before-Y phase order")
                for vc_in in first.vcs:
                    for vc_out in second.vcs:
                        edges.add(((first.resource, vc_in),
                                   (second.resource, vc_out)))

    return GecHybridCandidateCDG(
        nodes=tuple(sorted(node_set)), edges=tuple(sorted(edges)),
        candidate_count=candidate_count, vc_count=params.num_vcs)


__all__ = [
    "GEC_HYBRID_CANDIDATE_CDG_V1", "GecHybridCandidateError",
    "GecHybridParams", "GecHybridCandidate", "GecHybridCandidateCDG",
    "gec_hybrid_candidates", "select_gec_hybrid_candidate",
    "build_gec_hybrid_candidate_cdg",
]
