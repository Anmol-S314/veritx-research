"""route_artifact_v3 — a route whose steps may name SHARED wires.

Why a new version rather than a change to v2
--------------------------------------------
RouteArtifact v2 persists, per (routing class, src, dst), ONE INTEGER
channel id. That integer is the artifact's identity: it is hashed, recorded
in qualification records and compared against simulator dumps. Changing its
meaning in place would silently invalidate every recorded identity, and
would reinterpret historical artifacts as describing something they do not.

So v2 keeps its meaning and its bytes. v3 carries a ``RouteDecision``
instead — resource + tap + landing router + VC partition — and only fabrics
that actually have shared wires opt into it.

What v3 adds that v2 could not express
--------------------------------------
``next_router`` is carried, not derived. For a private channel the landing
router IS the channel's sink; for a shared wire the wire is identical for
every tap, so the resource determines nothing about where the packet lands.

How to read this artifact
-------------------------
``decisions`` is the executed first-hop relation the simulator is compared
against, per (src_router, destination TERMINAL). The hops are the same ones
the differential tests prove, so an artifact built here is a claim that has
already been checked against the fork rather than a fresh assertion.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import SemanticError
from veritx_dse.model.shared_resource import (
    ResourceKind,
    ResourceRef,
    RouteDecision,
    SharedResourceError,
)
from veritx_dse.verification.shared_resource_cdg import (
    SharedResourceCDG,
    build_shared_resource_cdg,
)

ROUTE_ARTIFACT_V3_SCHEMA_VERSION = 3
_HASH_TYPE_TAG = "srota/RouteArtifact/v3"

class RouteArtifactV3Error(ValueError, SemanticError):
    """The v3 route table is malformed or inconsistent — fail closed."""

@dataclass(frozen=True)
class RouteArtifactV3:
    """A class-aware route realization whose steps may be shared wires.

    ``partition_to_vcs`` maps a hop's ``vc_partition`` to the concrete VCs
    that implement it. The two are deliberately separate: a partition is a
    routing-rule output, while which VCs realise it is a VC-layer decision,
    and the dependency proof works over the concrete VCs. That separation is
    what lets one representation cover shape-, rank-, tap- and phase-based
    policies without this file knowing which of them it is looking at.
    """

    routing_class: str
    topology_hash: str
    routers: tuple[int, ...]
    decisions: Mapping[tuple[int, int], RouteDecision]
    partition_to_vcs: Mapping[int, tuple[int, ...]]
    allowed_transitions: tuple[tuple[int, int], ...]
    #: Destination TERMINAL -> the router it attaches to. Empty means the
    #: identity, which is only sound when a terminal id is also a router id
    #: (concentration 1). A concentrated fabric must fill it in, because
    #: "does this hop end the route?" is a question about the destination
    #: router, not about the terminal number.
    terminal_to_router: Mapping[int, int] = field(default_factory=dict)

    schema_version: int = ROUTE_ARTIFACT_V3_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.routing_class, str) or not self.routing_class:
            raise RouteArtifactV3Error("routing_class must be a non-empty str")
        if not isinstance(self.topology_hash, str) or not self.topology_hash:
            raise RouteArtifactV3Error("topology_hash must be a non-empty str")
        if self.schema_version != ROUTE_ARTIFACT_V3_SCHEMA_VERSION:
            raise RouteArtifactV3Error(
                f"unsupported route artifact schema_version "
                f"{self.schema_version!r}; this build writes v"
                f"{ROUTE_ARTIFACT_V3_SCHEMA_VERSION}")
        if not isinstance(self.routers, tuple) or not self.routers:
            raise RouteArtifactV3Error("routers must be a non-empty tuple")
        if list(self.routers) != sorted(set(self.routers)):
            raise RouteArtifactV3Error(
                "routers must be sorted and de-duplicated; the artifact's "
                "identity must not depend on insertion order")
        if not isinstance(self.decisions, Mapping) or not self.decisions:
            raise RouteArtifactV3Error("decisions must be a non-empty mapping")

    @property
    def shared_resource_count(self) -> int:
        """Distinct shared wires this table routes over."""
        return len({d.resource for d in self.decisions.values()
                    if d.resource.is_shared})

    @property
    def private_resource_count(self) -> int:
        return len({d.resource for d in self.decisions.values()
                    if not d.resource.is_shared})

    def shared_resource_cdg(self) -> SharedResourceCDG:
        """The concrete (resource, VC) dependency graph for this route.

        Raises rather than returning a partial graph: an inconsistent table
        has no dependency graph, and a caller that treats "could not build"
        as "no cycle" would certify a fabric nothing checked.
        """
        try:
            return build_shared_resource_cdg(
                decisions=dict(self.decisions),
                partition_to_vcs=dict(self.partition_to_vcs),
                allowed_transitions=self.allowed_transitions,
                routers=self.routers,
                node_to_router=dict(self.terminal_to_router))
        except SharedResourceError as exc:
            raise RouteArtifactV3Error(str(exc)) from exc

    def validate_against(self, topology: Any) -> None:
        """Prove the route's resources are legal for the declared fabric.

        The strongest available check is the wire count: the materializer
        emitted one SharedLink per driven wire, and the route names one
        resource per wire. If those disagree, the route describes a fabric
        that was not built, and every proof computed from it is about the
        wrong network. That cross-check is a parent-recomputation check, not
        a stored claim, so a fabricated route cannot pass it.
        """
        from veritx_dse.model.topology_artifact import TopologyArtifact
        if not isinstance(topology, TopologyArtifact):
            raise RouteArtifactV3Error(
                f"topology must be a TopologyArtifact, got "
                f"{type(topology).__name__}")
        if self.topology_hash != topology.topology_hash():
            raise RouteArtifactV3Error(
                "topology_hash does not match the materialized topology")
        declared = len(topology.shared_links)
        used = self.shared_resource_count
        if declared != used:
            raise RouteArtifactV3Error(
                f"the fabric declares {declared} shared wire(s) but the "
                f"route names {used}: the route does not describe this "
                "topology")
        routers = {r.router_id for r in topology.routers}
        for (src, _node), decision in self.decisions.items():
            if src not in routers:
                raise RouteArtifactV3Error(
                    f"route step from router {src} names a router outside "
                    "the materialized topology")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "routing_class": self.routing_class,
            "topology_hash": self.topology_hash,
            "routers": list(self.routers),
            "decisions": [
                [s, d, decision.to_dict()]
                for (s, d), decision in sorted(self.decisions.items())
            ],
            "partition_to_vcs": {str(p): list(v)
                                 for p, v in sorted(
                                     self.partition_to_vcs.items())},
            "allowed_transitions": [list(pair)
                                    for pair in self.allowed_transitions],
            "terminal_to_router": [[node, router] for node, router in
                                   sorted(self.terminal_to_router.items())],
        }

    def to_dict(self) -> dict[str, Any]:
        d = self.canonical_dict()
        d["schema_version"] = self.schema_version
        d["route_artifact_id"] = self.route_artifact_id()
        return d

    def route_artifact_id(self) -> str:
        return content_id(f"{_HASH_TYPE_TAG}/v{self.schema_version}",
                          self.canonical_dict())

    @classmethod
    def from_dict(cls, d: Any) -> RouteArtifactV3:
        if not isinstance(d, dict):
            raise RouteArtifactV3Error(
                f"route artifact must be an object, got {type(d).__name__}")
        allowed = frozenset({
            "routing_class", "topology_hash", "routers", "decisions",
            "partition_to_vcs", "allowed_transitions", "terminal_to_router",
            "schema_version", "route_artifact_id"})
        unknown = sorted(set(d) - allowed)
        if unknown:
            raise RouteArtifactV3Error(
                f"route artifact has unknown fields {unknown}")
        for field in ("routing_class", "topology_hash", "routers",
                      "decisions", "partition_to_vcs"):
            if field not in d:
                raise RouteArtifactV3Error(
                    f"route artifact is missing required field {field!r}")
        raw_decisions = d["decisions"]
        if not isinstance(raw_decisions, list):
            raise RouteArtifactV3Error("decisions must be a list")
        decisions: dict[tuple[int, int], RouteDecision] = {}
        for row in raw_decisions:
            if (not isinstance(row, list) or len(row) != 3
                    or type(row[0]) is not int or type(row[1]) is not int):
                raise RouteArtifactV3Error(
                    f"decision row {row!r} must be [src, dst, decision]")
            key = (row[0], row[1])
            if key in decisions:
                raise RouteArtifactV3Error(
                    f"decisions repeat (src_router={key[0]}, "
                    f"dst_node={key[1]})")
            decisions[key] = RouteDecision.from_dict(row[2])
        raw_partitions = d["partition_to_vcs"]
        if not isinstance(raw_partitions, Mapping):
            raise RouteArtifactV3Error(
                "partition_to_vcs must be an object keyed by partition id")
        partitions: dict[int, tuple[int, ...]] = {}
        for key, vcs in raw_partitions.items():
            try:
                partition = int(key)
            except (TypeError, ValueError):
                raise RouteArtifactV3Error(
                    f"partition key {key!r} is not an integer id") from None
            if isinstance(vcs, (str, bytes)) or not isinstance(vcs, list):
                raise RouteArtifactV3Error(
                    f"partition {partition} must map to a list of VCs")
            partitions[partition] = tuple(vcs)
        raw_transitions = d.get("allowed_transitions")
        if raw_transitions is None:
            raise RouteArtifactV3Error(
                "route artifact is missing required field "
                "'allowed_transitions'")
        if not isinstance(raw_transitions, list):
            raise RouteArtifactV3Error("allowed_transitions must be a list")
        transitions: list[tuple[int, int]] = []
        for pair in raw_transitions:
            if (not isinstance(pair, list) or len(pair) != 2
                    or any(type(v) is not int for v in pair)):
                raise RouteArtifactV3Error(
                    f"allowed transition {pair!r} must be [vc_in, vc_out]")
            transitions.append((pair[0], pair[1]))
        raw_nodes = d.get("terminal_to_router") or []
        if not isinstance(raw_nodes, list):
            raise RouteArtifactV3Error("terminal_to_router must be a list")
        terminal_to_router: dict[int, int] = {}
        for pair in raw_nodes:
            if (not isinstance(pair, list) or len(pair) != 2
                    or any(type(v) is not int for v in pair)):
                raise RouteArtifactV3Error(
                    f"terminal_to_router row {pair!r} must be [node, router]")
            terminal_to_router[pair[0]] = pair[1]
        return cls(
            routing_class=d["routing_class"],
            topology_hash=d["topology_hash"],
            routers=tuple(d["routers"]),
            decisions=decisions,
            partition_to_vcs=partitions,
            allowed_transitions=tuple(transitions),
            terminal_to_router=terminal_to_router,
            schema_version=d.get("schema_version",
                                 ROUTE_ARTIFACT_V3_SCHEMA_VERSION))

def route_artifact_v3_for_gec_mecs(
        params: Any, *, topology_hash: str,
        routing_class: str = "DOR_GEC_MECS"
) -> RouteArtifactV3:
    """Build v3 from the differential-proven GEC-MECS hop rule.

    Resource ids: GEC gives a router ``c + 2*o`` output ports and the
    express ports are the shared ones, so a wire is named by
    ``router * (c + 2*o) + port`` — a per-router port offset in a global
    space. The local terminal port is a PRIVATE channel (one driver, one
    sink) and is marked as such, so it can never alias a shared wire with
    the same port number.

    Partitions: the tap is the partition, so a hop's VC slice is exactly the
    slice its tap owns. A hop that ends the route carries no partition — it
    consumes whatever VC brought the packet in and imposes nothing on a
    successor, because it has none.

    ``terminal_to_router`` is filled in from the shape: with concentration c,
    terminal n attaches to router ``n // c``. Without it, a c>1 fabric would
    be mis-read as having no terminal hops at all, because a terminal number
    is not a router number.
    """
    from veritx_dse.model.gec_mecs_route import (
        GecMecsParams,
        derive_gec_mecs_table,
    )
    if not isinstance(params, GecMecsParams):
        raise RouteArtifactV3Error(
            f"params must be a GecMecsParams, got {type(params).__name__}")
    stride = params.c + 2 * params.o

    decisions: dict[tuple[int, int], RouteDecision] = {}
    for hop in derive_gec_mecs_table(params):
        resource_id = hop.src_router * stride + hop.port
        if hop.is_shared:
            decision = RouteDecision(
                resource=ResourceRef(ResourceKind.SHARED_LINK, resource_id),
                next_router=hop.next_router, vc_partition=hop.drop,
                tap=hop.drop)
        else:
            decision = RouteDecision(
                resource=ResourceRef(ResourceKind.CHANNEL, resource_id),
                next_router=hop.next_router, vc_partition=0)
        decisions[(hop.src_router, hop.dest_node)] = decision

    per_tap = params.vcs_per_tap
    partitions = {drop: tuple(range(drop * per_tap, (drop + 1) * per_tap))
                  for drop in range(params.d)}
    vcs = tuple(range(params.num_vcs))
    transitions = tuple((a, b) for a in vcs for b in vcs)
    return RouteArtifactV3(
        routing_class=routing_class, topology_hash=topology_hash,
        routers=tuple(range(params.router_count)), decisions=decisions,
        partition_to_vcs=partitions, allowed_transitions=transitions,
        terminal_to_router={node: node // params.c
                            for node in range(params.node_count)})

__all__ = [
    "RouteArtifactV3Error", "RouteArtifactV3", "ShapePolicyRoute",
    "shape_policy_route_for_srota",
    "route_artifact_v3_for_gec_mecs",
    "route_artifact_v3_for_srota_row_first", "ROUTE_ARTIFACT_V3_SCHEMA_VERSION",
]

def route_artifact_v3_for_srota_row_first(
        params: Any, *, topology_hash: str,
        routing_class: str = "SROTA_O1TURN_ROW_FIRST"
) -> RouteArtifactV3:
    """Build v3 from the differential-proven SROTA row-first hop rule.

    Resource ids: SROTA's output ports are [0,c) local followed by the
    direction ports, four at most, so a port is offset by ``c + 4`` in a
    global space. A direction port is a shared wire (one driver, many taps);
    the local terminal port is a private channel.

    ONE partition covers everything: the row-first shape is a single shape,
    so a packet never needs a VC to keep two shapes apart. That is exactly
    why this configuration is the cheapest real proof of the representation
    — and why its dependency graph is acyclic for a reason (there is no
    shape mixing to separate) rather than by luck.
    """
    from veritx_dse.model.srota_rowfirst_route import (
        SrotaRowFirstParams,
        derive_srota_rowfirst_table,
    )
    if not isinstance(params, SrotaRowFirstParams):
        raise RouteArtifactV3Error(
            f"params must be a SrotaRowFirstParams, got "
            f"{type(params).__name__}")
    if params.num_vcs != 1:
        raise RouteArtifactV3Error(
            "the row-first single-shape artifact carries one VC; a larger "
            "count needs an explicit partition policy, which this builder "
            "does not invent")
    stride = params.c + 4

    decisions: dict[tuple[int, int], RouteDecision] = {}
    for hop in derive_srota_rowfirst_table(params):
        resource_id = hop.src_router * stride + hop.port
        if hop.is_shared:
            decision = RouteDecision(
                resource=ResourceRef(ResourceKind.SHARED_LINK, resource_id),
                next_router=hop.next_router, vc_partition=0, tap=hop.drop)
        else:
            decision = RouteDecision(
                resource=ResourceRef(ResourceKind.CHANNEL, resource_id),
                next_router=hop.next_router, vc_partition=0)
        decisions[(hop.src_router, hop.dest_node)] = decision

    return RouteArtifactV3(
        routing_class=routing_class, topology_hash=topology_hash,
        routers=tuple(range(params.router_count)), decisions=decisions,
        partition_to_vcs={0: (0,)}, allowed_transitions=((0, 0),),
        terminal_to_router={node: node // params.c
                            for node in range(params.node_count)})


@dataclass(frozen=True)
class ShapePolicyRoute:
    """A route whose shape is chosen AT RUNTIME, proved as a union.

    SROTA's ``vc_policy=shape`` picks row-first or column-first per flow from
    live telemetry load, so ``(src, dst) -> one decision`` is not a function
    and no single table can hold it. The obligation therefore changes:

        the UNION of every realizable choice, with the choices separated by
        VC, must be acyclic

    which is exactly the static check the simulator runs on its own
    ``srota_cdg_radix`` abstraction. That the two agree is the point: this
    type exists so the canonical proof and the fork's check are the same
    claim, not two claims that happen to both pass.

    Distinct from RouteArtifactV3 on purpose. A deterministic table and an
    adaptive union are different objects with different proof obligations,
    and collapsing them would let an adaptive design be certified by a
    method that only ever saw one of its choices.
    """

    routing_class: str
    topology_hash: str
    routers: tuple[int, ...]
    #: (src, dst) -> every decision the runtime may take for that pair.
    choices: Mapping[tuple[int, int], tuple[RouteDecision, ...]]
    partition_to_vcs: Mapping[int, tuple[int, ...]]
    allowed_transitions: tuple[tuple[int, int], ...]
    terminal_to_router: Mapping[int, int] = field(default_factory=dict)
    shape_of_partition: Mapping[int, str] = field(default_factory=dict)

    schema_version: int = ROUTE_ARTIFACT_V3_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.routing_class or not self.topology_hash:
            raise RouteArtifactV3Error(
                "routing_class and topology_hash must be non-empty")
        if not self.choices:
            raise RouteArtifactV3Error("choices must be non-empty")
        for key, options in self.choices.items():
            if not isinstance(options, tuple) or not options:
                raise RouteArtifactV3Error(
                    f"choices[{key!r}] must be a non-empty tuple; a pair "
                    "with no realizable choice is not a route")
            for option in options:
                if not isinstance(option, RouteDecision):
                    raise RouteArtifactV3Error(
                        f"choices[{key!r}] must hold RouteDecision values")

    @property
    def shape_count(self) -> int:
        return len({d.vc_partition for options in self.choices.values()
                    for d in options})

    @property
    def shared_resource_count(self) -> int:
        return len({d.resource for options in self.choices.values()
                    for d in options if d.resource.is_shared})

    def shared_resource_cdg(self) -> SharedResourceCDG:
        """The union graph: every realizable choice contributes edges."""
        return build_shared_resource_cdg(
            decisions=dict(self.choices),
            partition_to_vcs=dict(self.partition_to_vcs),
            allowed_transitions=self.allowed_transitions,
            routers=self.routers,
            node_to_router=dict(self.terminal_to_router))

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "routing_class": self.routing_class,
            "topology_hash": self.topology_hash,
            "routers": list(self.routers),
            "choices": [
                [s, d, [option.to_dict() for option in sorted(
                    options, key=lambda o: (o.vc_partition, o.next_router))]]
                for (s, d), options in sorted(self.choices.items())
            ],
            "partition_to_vcs": {str(p): list(v)
                                 for p, v in sorted(
                                     self.partition_to_vcs.items())},
            "allowed_transitions": [list(pair)
                                    for pair in self.allowed_transitions],
            "shape_of_partition": {str(p): s for p, s
                                   in sorted(self.shape_of_partition.items())},
        }

    def route_artifact_id(self) -> str:
        return content_id(f"{_HASH_TYPE_TAG}/shape-policy/v"
                          f"{self.schema_version}", self.canonical_dict())

    def validate_against(self, topology: Any) -> None:
        """The same parent check as the deterministic artifact."""
        from veritx_dse.model.topology_artifact import TopologyArtifact
        if not isinstance(topology, TopologyArtifact):
            raise RouteArtifactV3Error(
                f"topology must be a TopologyArtifact, got "
                f"{type(topology).__name__}")
        if self.topology_hash != topology.topology_hash():
            raise RouteArtifactV3Error(
                "topology_hash does not match the materialized topology")
        declared = len(topology.shared_links)
        if declared != self.shared_resource_count:
            raise RouteArtifactV3Error(
                f"the fabric declares {declared} shared wire(s) but the "
                f"union names {self.shared_resource_count}")


def shape_policy_route_for_srota(
        params: Any, *, topology_hash: str,
        routing_class: str = "SROTA_O1TURN_SHAPE_POLICY"
) -> ShapePolicyRoute:
    """Union the row-first and column-first shapes under their VC partition.

    The partition map and the legal transitions come from the canonical
    ``SrotaShapeVCPartitionPolicy`` — the same artifact the fork's
    ``srota_vc_policy=shape`` implements — so the proof is over the VCs the
    design actually has.
    """
    from veritx_dse.model.srota_rowfirst_route import (
        SrotaRowFirstParams,
        derive_srota_columnfirst_table,
        derive_srota_rowfirst_table,
    )
    from veritx_dse.model.srota_shape_vc_policy import (
        SrotaShapeVCPartitionPolicy,
    )
    if not isinstance(params, SrotaRowFirstParams):
        raise RouteArtifactV3Error(
            f"params must be a SrotaRowFirstParams, got "
            f"{type(params).__name__}")
    policy = SrotaShapeVCPartitionPolicy.derive(2)
    stride = params.c + 4
    shapes = (("row", derive_srota_rowfirst_table(params), 0),
              ("column", derive_srota_columnfirst_table(params), 1))

    merged: dict[tuple[int, int], list[RouteDecision]] = {}
    for _shape, table, partition in shapes:
        for hop in table:
            resource_id = hop.src_router * stride + hop.port
            if hop.is_shared:
                decision = RouteDecision(
                    resource=ResourceRef(ResourceKind.SHARED_LINK,
                                         resource_id),
                    next_router=hop.next_router,
                    vc_partition=partition, tap=hop.drop)
            else:
                decision = RouteDecision(
                    resource=ResourceRef(ResourceKind.CHANNEL, resource_id),
                    next_router=hop.next_router, vc_partition=partition)
            merged.setdefault((hop.src_router, hop.dest_node),
                              []).append(decision)

    return ShapePolicyRoute(
        routing_class=routing_class, topology_hash=topology_hash,
        routers=tuple(range(params.router_count)),
        choices={key: tuple(options) for key, options in merged.items()},
        partition_to_vcs=policy.partition_to_vcs,
        allowed_transitions=policy.allowed_transitions,
        terminal_to_router={node: node // params.c
                            for node in range(params.node_count)},
        shape_of_partition={partition: shape
                            for partition, (shape, _vcs)
                            in enumerate(policy.shape_to_vcs)})
