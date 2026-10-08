"""srota_rank_route — SROTA Plane D under the hop-rank VC policy.

Why this is a separate artifact from ``ShapePolicyRoute``: the fork proves
the rank policy by WALKING every enabled (source, destination, shape,
Valiant intermediate) route and labelling each hop with its rank
(``srota.cpp`` ``_CheckCDG``). The continuation at a Valiant intermediate
is not a function of ``(router, destination)`` alone — the same router
carrying a direct packet to ``dst`` continues in rank 0/1, while carrying a
Valiant packet to ``dst`` it continues in rank 2/3. A table keyed only by
``(router, destination)`` cannot hold both, so the generic table-following
CDG would prove a different graph than the simulator checks.

This artifact therefore carries the walk's union graph explicitly, exactly
like the GEC-hybrid candidate graph, and reuses the shared-resource CDG
verdict machinery over it. It still exposes the first-hop ``choices`` the
endpoint-resolution stage needs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import SemanticError
from veritx_dse.model.shared_resource import (
    ResourceKind, ResourceRef, ResourceVC, RouteDecision,
)

_HASH_TYPE_TAG = "srota/RankPolicyRoute"
ROUTE_ARTIFACT_V3_SCHEMA_VERSION = 1

#: The direct shapes share ranks 0/1; Valiant's second leg ranks 2/3.
_ROW_FIRST = frozenset({"row", "valiant_l1", "valiant_l2"})
_SHAPE_NAMES = ("row", "column", "valiant")
_DIRECTIONS = ("XNEG", "XPOS", "YNEG", "YPOS")

class SrotaRankRouteError(ValueError, SemanticError):
    """The declared rank/shape design cannot describe a hop — fail closed."""

def _as_int(name: str, value: Any, *, minimum: int) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise SrotaRankRouteError(
            f"{name} must be an exact int, got {value!r}")
    if value < minimum:
        raise SrotaRankRouteError(
            f"{name} must be >= {minimum}, got {value}")
    return value

def _rank_base(shape: str) -> int:
    return 2 if shape == "valiant_l2" else 0

def _present_directions(px: int, py: int, k: int) -> tuple[str, ...]:
    present: list[str] = []
    if px > 0:
        present.append("XNEG")
    if px < k - 1:
        present.append("XPOS")
    if py > 0:
        present.append("YNEG")
    if py < k - 1:
        present.append("YPOS")
    return tuple(present)

@dataclass(frozen=True)
class _Step:
    port: int
    drop: int
    rank: int
    next_router: int

def _step(shape: str, cur: int, target_router: int, k: int, c: int) -> _Step:
    """One ``SrotaRouteCompute`` hop toward ``target_router`` (row-first or
    column-first). Express is on, so a hop jumps the whole distance and its
    tap is ``|distance| - 1`` (the fork's ``SrotaDimHop``)."""
    x, y = cur % k, cur // k
    tx, ty = target_router % k, target_router // k
    row_first = shape in _ROW_FIRST
    if row_first:
        take_x = (tx != x)
        turned = not take_x
    else:
        take_x = (ty == y)
        turned = take_x
    present = _present_directions(x, y, k)
    if take_x:
        direction = "XNEG" if tx < x else "XPOS"
        drop = abs(tx - x) - 1
        next_router = y * k + tx
    else:
        direction = "YNEG" if ty < y else "YPOS"
        drop = abs(ty - y) - 1
        next_router = ty * k + x
    if direction not in present:            # pragma: no cover - guarded
        raise SrotaRankRouteError(
            f"router {cur} has no {direction} port (present: {present})")
    return _Step(port=c + present.index(direction), drop=drop,
                 rank=_rank_base(shape) + (1 if turned else 0),
                 next_router=next_router)

def _leg(shape: str, src: int, target: int, k: int, c: int
         ) -> list[tuple[int, _Step]]:
    """Every hop of one leg, in traversal order."""
    out: list[tuple[int, _Step]] = []
    cur = src
    guard = 4 * k + 8
    while cur != target:
        if guard <= 0:                      # pragma: no cover - guarded
            raise SrotaRankRouteError(
                f"the {shape} leg from {src} to {target} did not terminate")
        step = _step(shape, cur, target, k, c)
        out.append((cur, step))
        cur = step.next_router
        guard -= 1
    return out

def _walk(shape: str, src: int, dst: int, k: int, c: int,
          intermediate: int | None) -> list[tuple[int, _Step]]:
    """One admitted route as a list of (router, step)."""
    if shape != "valiant":
        return _leg(shape, src, dst, k, c)
    if intermediate is None:                # pragma: no cover - guarded
        raise SrotaRankRouteError("a valiant route needs an intermediate")
    return (_leg("valiant_l1", src, intermediate, k, c)
            + _leg("valiant_l2", intermediate, dst, k, c))

def _resource(cur: int, step: _Step, k: int, c: int) -> ResourceRef:
    resource_id = cur * (c + 4) + step.port
    kind = (ResourceKind.SHARED_LINK if step.drop >= 0
            else ResourceKind.CHANNEL)
    return ResourceRef(kind, resource_id)

@dataclass(frozen=True)
class RankPolicyRoute:
    """The union of every admitted SROTA route under the hop-rank policy."""

    routing_class: str
    topology_hash: str
    routers: tuple[int, ...]
    choices: Mapping[tuple[int, int], tuple[RouteDecision, ...]]
    partition_to_vcs: Mapping[int, tuple[int, ...]]
    allowed_transitions: tuple[tuple[int, int], ...]
    terminal_to_router: Mapping[int, int]
    nodes: tuple[ResourceVC, ...]
    edges: tuple[tuple[ResourceVC, ResourceVC], ...]
    shapes: tuple[str, ...] = ()
    schema_version: int = ROUTE_ARTIFACT_V3_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.routing_class or not self.topology_hash:
            raise SrotaRankRouteError(
                "routing_class and topology_hash must be non-empty")
        if not self.choices:
            raise SrotaRankRouteError("choices must be non-empty")
        if not isinstance(self.partition_to_vcs, Mapping) or not \
                isinstance(self.terminal_to_router, Mapping):
            raise SrotaRankRouteError(
                "partition_to_vcs and terminal_to_router must be mappings")
        if set(self.partition_to_vcs) != \
                set(range(len(self.partition_to_vcs))):
            raise SrotaRankRouteError(
                "rank partitions must be contiguous from 0")
        for key, options in self.choices.items():
            if not isinstance(options, tuple) or not options:
                raise SrotaRankRouteError(
                    f"choices[{key!r}] must be a non-empty tuple")
            for option in options:
                if not isinstance(option, RouteDecision):
                    raise SrotaRankRouteError(
                        f"choices[{key!r}] must hold RouteDecision values")
                if option.vc_partition not in self.partition_to_vcs:
                    raise SrotaRankRouteError(
                        f"choices[{key!r}] names unmapped rank "
                        f"{option.vc_partition}")

    @property
    def shape_count(self) -> int:
        return len(self.shapes)

    @property
    def shared_resource_count(self) -> int:
        return len({resource for resource, _vc in self.nodes
                    if resource.is_shared})

    def shared_resource_cdg(self) -> Any:
        from veritx_dse.verification.shared_resource_cdg import (
            SharedResourceCDG,
        )
        expected = self.recompute()
        return SharedResourceCDG(
            nodes=expected.nodes, edges=expected.edges,
            partition_to_vcs=dict(expected.partition_to_vcs))

    def recompute(self) -> RankPolicyRoute:
        """Rebuild admitted walks; persisted nodes/edges are inspection caches.

        Standalone checks use the declared shape envelope. Certification also
        binds that envelope to the original design and exact topology.
        """
        from math import isqrt
        k = isqrt(len(self.routers))
        if k < 2 or k * k != len(self.routers) or self.routers != tuple(range(k * k)):
            raise SrotaRankRouteError("rank policy requires a complete square router grid")
        c, remainder = divmod(len(self.terminal_to_router), k * k)
        if c < 1 or remainder or self.terminal_to_router != {
                node: node // c for node in range(k * k * c)}:
            raise SrotaRankRouteError("rank terminal binding does not match the grid")
        if self.schema_version != ROUTE_ARTIFACT_V3_SCHEMA_VERSION:
            raise SrotaRankRouteError("unsupported rank route schema")
        expected = rank_policy_route_for_srota(
            k=k, c=c, shapes=frozenset(self.shapes), mecs_row=True,
            mecs_col=True, topology_hash=self.topology_hash,
            routing_class=self.routing_class)
        if self.canonical_dict() != expected.canonical_dict():
            raise SrotaRankRouteError(
                "stored rank choices/partitions/nodes/edges differ from recomputed admitted walks")
        return expected

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "routing_class": self.routing_class,
            "topology_hash": self.topology_hash,
            "routers": list(self.routers),
            "choices": [
                [s, d, [option.to_dict() for option in sorted(
                    options, key=lambda o: (
                        o.vc_partition, o.next_router, o.resource.kind.value,
                        o.resource.resource_id,
                        -1 if o.tap is None else o.tap))]]
                for (s, d), options in sorted(self.choices.items())
            ],
            "partition_to_vcs": {str(p): list(v)
                                 for p, v in sorted(
                                     self.partition_to_vcs.items())},
            "allowed_transitions": [list(pair) for pair in sorted(
                set(self.allowed_transitions))],
            "terminal_to_router": [[node, router] for node, router in
                                   sorted(self.terminal_to_router.items())],
            "nodes": [[resource.to_dict(), vc] for resource, vc in self.nodes],
            "edges": [[[a[0].to_dict(), a[1]], [b[0].to_dict(), b[1]]]
                      for a, b in self.edges],
            "shapes": list(self.shapes),
        }

    def route_artifact_id(self) -> str:
        return content_id(f"{_HASH_TYPE_TAG}/v{self.schema_version}",
                          self.canonical_dict())

    def validate_against(self, topology: Any) -> None:
        from veritx_dse.model.topology_artifact import TopologyArtifact
        if not isinstance(topology, TopologyArtifact):
            raise SrotaRankRouteError(
                f"topology must be a TopologyArtifact, got "
                f"{type(topology).__name__}")
        if self.topology_hash != topology.topology_hash():
            raise SrotaRankRouteError(
                "topology_hash does not match the materialized topology")
        if self.shared_resource_count != len(topology.shared_links):
            raise SrotaRankRouteError(
                f"the fabric declares {len(topology.shared_links)} shared "
                f"wire(s) but the rank union names "
                f"{self.shared_resource_count}")
        routers = {r.router_id for r in topology.routers}
        if set(self.routers) != routers:
            raise SrotaRankRouteError(
                "the rank union's router set does not match the topology")
        self.recompute()
        from veritx_dse.model.route_artifact_v3 import _validate_topology_binding
        _validate_topology_binding(
            decisions=((src, dest, decision)
                       for (src, dest), options in self.choices.items()
                       for decision in options),
            routers=routers, topology=topology,
            terminal_to_router=self.terminal_to_router)


def rank_policy_route_for_srota(
        *, k: int, c: int, shapes: frozenset[str], mecs_row: bool,
        mecs_col: bool, topology_hash: str,
        routing_class: str = "SROTA_O1TURN_RANK"
) -> RankPolicyRoute:
    """Union every admitted route under the hop-rank policy.

    ``shapes`` is the declared shape set; ``valiant`` expands over EVERY
    intermediate, because the fork's check does and the runtime may pick
    any of them.
    """
    _as_int("k", k, minimum=2)
    _as_int("c", c, minimum=1)
    if type(mecs_row) is not bool or type(mecs_col) is not bool:
        raise SrotaRankRouteError("mecs_row/mecs_col must be bools")
    if not mecs_row or not mecs_col:
        raise SrotaRankRouteError(
            "the rank + Valiant envelope requires the full express layer "
            "(mecs_row and mecs_col): a plain nearest-neighbour dimension "
            "has no tap, so the rank walk's MECS rule does not describe it")
    unknown = sorted(set(shapes) - set(_SHAPE_NAMES))
    if unknown:
        raise SrotaRankRouteError(f"unknown path shape(s) {unknown}")
    if "row" not in shapes:
        # The fork refuses any path_en without bit 0: every proof is anchored
        # to row-first. Mirrored so the model and the fork agree.
        raise SrotaRankRouteError(
            "srota_path_en must include row-first (ROUTE-001 14.3); the "
            f"declared shapes {sorted(shapes)} do not")
    valiant = "valiant" in shapes
    from veritx_dse.model.srota_rank_vc_policy import (
        SrotaRankVCPartitionPolicy,
    )
    policy = SrotaRankVCPartitionPolicy.derive(valiant=valiant)
    routers = k * k
    terminals = routers * c

    nodes: set[ResourceVC] = set()
    edges: set[tuple[ResourceVC, ResourceVC]] = set()
    choices: dict[tuple[int, int], list[RouteDecision]] = {}

    def record(src: int, dst: int, walk: list[tuple[int, _Step]]) -> None:
        previous: ResourceVC | None = None
        for cur, step in walk:
            resource = _resource(cur, step, k, c)
            node = (resource, step.rank)
            nodes.add(node)
            if previous is not None and previous != node:
                edges.add((previous, node))
            previous = node
        if walk:
            first_cur, first_step = walk[0]
            decision = RouteDecision(
                resource=_resource(first_cur, first_step, k, c),
                next_router=first_step.next_router,
                vc_partition=first_step.rank,
                tap=first_step.drop if first_step.drop >= 0 else None)
            choices.setdefault((src, dst), []).append(decision)

    for src in range(routers):
        for dst in range(routers):
            if src == dst:
                continue
            for shape in ("row", "column"):
                if shape in shapes:
                    record(src, dst, _walk(shape, src, dst, k, c, None))
            if valiant:
                for intm in range(routers):
                    if intm in (src, dst):
                        continue
                    record(src, dst,
                           _walk("valiant", src, dst, k, c, intm))

    # choices are keyed by (src_router, dest_terminal); the record() helper
    # keyed by dest ROUTER, so expand every terminal of that router.
    expanded: dict[tuple[int, int], tuple[RouteDecision, ...]] = {}
    for (src, dst_router), options in choices.items():
        deduped = tuple(sorted(
            set(options), key=lambda o: (
                o.vc_partition, o.next_router, o.resource.kind.value,
                o.resource.resource_id, -1 if o.tap is None else o.tap)))
        for node in range(dst_router * c, dst_router * c + c):
            expanded[(src, node)] = deduped
    # Local ejection: router x terminal coverage includes the src==dst row,
    # and its port is the terminal's own local port, so it is built per
    # terminal rather than shared across a destination router.
    for src in range(routers):
        for node in range(src * c, src * c + c):
            expanded[(src, node)] = (RouteDecision(
                resource=ResourceRef(ResourceKind.CHANNEL,
                                     src * (c + 4) + (node % c)),
                next_router=src, vc_partition=0),)

    return RankPolicyRoute(
        routing_class=routing_class, topology_hash=topology_hash,
        routers=tuple(range(routers)), choices=expanded,
        partition_to_vcs=policy.partition_to_vcs,
        allowed_transitions=policy.allowed_transitions,
        terminal_to_router={node: node // c for node in range(terminals)},
        nodes=tuple(sorted(nodes)), edges=tuple(sorted(edges)),
        shapes=tuple(sorted(shapes)))


__all__ = [
    "SrotaRankRouteError", "RankPolicyRoute", "rank_policy_route_for_srota",
]
