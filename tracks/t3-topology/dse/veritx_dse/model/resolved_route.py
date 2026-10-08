"""veritx_dse.model.resolved_route — endpoint-resolved routing identity.

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.core.route_artifact import RouteArtifact
from veritx_dse.model.attachment import AgentAttachmentArtifact
from veritx_dse.model.gec_hybrid_route import GecHybridRoute
from veritx_dse.model.topology_artifact import TopologyArtifact

RESOLVED_ROUTE_SCHEMA_VERSION = 2
#: v3 carries a RouteArtifactV3 whose first hop is a resource+tap decision
#: rather than an integer channel id. The row SHAPE differs, so the endpoint
#: table hash is computed under its own domain: two tables that differ only
#: in how a hop is written must not collide.
RESOLVED_ROUTE_V3_SCHEMA_VERSION = 3
_RESOLVED_ROUTE_SCHEMA_VERSIONS = (RESOLVED_ROUTE_SCHEMA_VERSION,
                                   RESOLVED_ROUTE_V3_SCHEMA_VERSION)
_HASH_TYPE_TAG = "srota/ResolvedRouteArtifact"
_ENDPOINT_TABLE_DOMAIN = "srota/ResolvedRouteArtifact/endpoint-table/v2"
_ENDPOINT_TABLE_DOMAIN_V3 = "srota/ResolvedRouteArtifact/endpoint-table/v3"

def _endpoint_table_domain(schema_version: int) -> str:
    if schema_version == RESOLVED_ROUTE_V3_SCHEMA_VERSION:
        return _ENDPOINT_TABLE_DOMAIN_V3
    return _ENDPOINT_TABLE_DOMAIN
LOCAL_EJECTION = "LOCAL_EJECTION"

class ResolvedRouteError(ValueError, SemanticError):
    """The endpoint-resolved routing binding is invalid — fail closed."""

def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise ResolvedRouteError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise ResolvedRouteError(
            f"{where} has unknown fields: {sorted(unknown)}")

def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise ResolvedRouteError(f"{where} is missing required field {key!r}")
    return d[key]

def _router_route_classes(router_route: RouteArtifact) -> tuple[str, ...]:
    definitions = router_route.routing_classes
    if not definitions:
        raise ResolvedRouteError(
            "router route does not declare routing classes (schema v2 "
            "requires RoutingClassDefinition entries)")
    return tuple(d.id for d in definitions)

@dataclass(frozen=True)
class ResolvedRouteArtifact:
    """Endpoint-resolved, class-aware routing for one candidate fabric."""

    topology_hash: str
    attachment_hash: str
    router_route_hash: str
    endpoint_to_router: tuple[tuple[int, int], ...]
    routing_classes: tuple[str, ...]
    endpoint_route_table_hash: str
    schema_version: int = RESOLVED_ROUTE_SCHEMA_VERSION
    artifact_hash: str = ""

    def __post_init__(self):
        for name in ("topology_hash", "attachment_hash", "router_route_hash",
                     "endpoint_route_table_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ResolvedRouteError(f"{name} must be a non-empty string")
        if not isinstance(self.endpoint_to_router, tuple) \
                or not self.endpoint_to_router:
            raise ResolvedRouteError(
                "endpoint_to_router must be a non-empty tuple")
        for index, pair in enumerate(self.endpoint_to_router):
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise ResolvedRouteError(
                    f"endpoint_to_router[{index}] must be an "
                    "(endpoint_id, router_id) pair")
            eid, router_id = pair
            if type(eid) is not int or type(router_id) is not int:
                raise ResolvedRouteError(
                    f"endpoint_to_router[{index}] must be exact integers, "
                    f"got {pair!r}")
            if router_id < 0:
                raise ResolvedRouteError(
                    f"endpoint {eid} references router {router_id} < 0")
        eids = [e for e, _ in self.endpoint_to_router]
        if eids != list(range(len(eids))):
            raise ResolvedRouteError(
                "endpoint ids must be contiguous from 0")
        if not isinstance(self.routing_classes, tuple) \
                or not self.routing_classes:
            raise ResolvedRouteError("routing_classes must be non-empty")
        for cls in self.routing_classes:
            if not isinstance(cls, str) or not cls:
                raise ResolvedRouteError(
                    "routing class ids must be non-empty strings")
        if len(set(self.routing_classes)) != len(self.routing_classes):
            raise ResolvedRouteError("routing class ids must be unique")
        if type(self.schema_version) is not int or \
                self.schema_version not in _RESOLVED_ROUTE_SCHEMA_VERSIONS:
            raise ResolvedRouteError(
                f"unsupported resolved-route schema_version "
                f"{self.schema_version!r} (expected one of "
                f"{_RESOLVED_ROUTE_SCHEMA_VERSIONS})")
        expected = self._compute_hash()
        if self.artifact_hash and self.artifact_hash != expected:
            raise ResolvedRouteError(
                "artifact_hash does not match content")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "topology_hash": self.topology_hash,
            "attachment_hash": self.attachment_hash,
            "router_route_hash": self.router_route_hash,
            "endpoint_to_router": [list(p) for p in self.endpoint_to_router],
            "routing_classes": list(self.routing_classes),
            "endpoint_route_table_hash": self.endpoint_route_table_hash,
        }

    def _compute_hash(self) -> str:
        return content_id(
            f"{_HASH_TYPE_TAG}/v{self.schema_version}", self.canonical_dict())

    def _domain(self) -> str:
        return _endpoint_table_domain(self.schema_version)

    def resolved_route_hash(self) -> str:
        return self._compute_hash()

    def to_dict(self) -> dict[str, Any]:
        d = self.canonical_dict()
        d["artifact_hash"] = self._compute_hash()
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "ResolvedRouteArtifact":
        """Deserialize and verify SELF-integrity only.

        Parent legality (topology/attachment/router route) is a seam check:
        call ``validate_against`` after loading. Schema v1 is refused.
        """
        _strict_keys(d, frozenset({
            "type", "schema_version", "topology_hash", "attachment_hash",
            "router_route_hash", "endpoint_to_router", "routing_classes",
            "endpoint_route_table_hash", "artifact_hash"}), "resolved_route")
        if _need(d, "type", "resolved_route") != _HASH_TYPE_TAG:
            raise ResolvedRouteError(
                f"resolved_route type must be {_HASH_TYPE_TAG!r}, got "
                f"{d.get('type')!r}")
        schema_version = _need(d, "schema_version", "resolved_route")
        if schema_version == 1:
            raise ResolvedRouteError(
                "ResolvedRouteArtifact schema v1 is refused on the "
                "authoritative path (classless next-router expansion); "
                "rebuild from a v2 RouteArtifact — no silent migration")
        raw_pairs = _need(d, "endpoint_to_router", "resolved_route")
        if not isinstance(raw_pairs, list) or not raw_pairs:
            raise ResolvedRouteError(
                "endpoint_to_router must be a non-empty list of pairs")
        pairs: list[tuple[int, int]] = []
        for index, row in enumerate(raw_pairs):
            if type(row) is not list or len(row) != 2:
                raise ResolvedRouteError(
                    f"endpoint_to_router[{index}] must be a two-element "
                    f"list, got {row!r}")
            eid, router_id = row
            if type(eid) is not int or type(router_id) is not int:
                raise ResolvedRouteError(
                    f"endpoint_to_router[{index}] must contain exact "
                    f"integers, got {row!r}")
            pairs.append((eid, router_id))
        raw_classes = _need(d, "routing_classes", "resolved_route")
        if not isinstance(raw_classes, list) or not raw_classes:
            raise ResolvedRouteError(
                "routing_classes must be a non-empty list of strings")
        classes: list[str] = []
        for index, class_id in enumerate(raw_classes):
            if not isinstance(class_id, str) or not class_id:
                raise ResolvedRouteError(
                    f"routing_classes[{index}] must be a non-empty string, "
                    f"got {class_id!r}")
            classes.append(class_id)
        artifact = cls(
            topology_hash=_need(d, "topology_hash", "resolved_route"),
            attachment_hash=_need(d, "attachment_hash", "resolved_route"),
            router_route_hash=_need(d, "router_route_hash", "resolved_route"),
            endpoint_to_router=tuple(pairs),
            routing_classes=tuple(classes),
            endpoint_route_table_hash=_need(
                d, "endpoint_route_table_hash", "resolved_route"),
            schema_version=schema_version,
        )
        supplied = d.get("artifact_hash")
        if supplied is not None and supplied != artifact._compute_hash():
            raise ResolvedRouteError("artifact_hash does not match content")
        return artifact

    def validate_against(self, topology: TopologyArtifact,
                         attachment: AgentAttachmentArtifact,
                         router_route: Any) -> None:
        """Prove every reference is legal against the declared parents.

        This recomputes the endpoint route table from the parents' entries
        and compares its digest with the stored one, so a fabricated
        endpoint-table hash cannot survive parent validation.
        """
        if not isinstance(topology, TopologyArtifact):
            raise ResolvedRouteError("topology must be a TopologyArtifact")
        if not isinstance(attachment, AgentAttachmentArtifact):
            raise ResolvedRouteError(
                "attachment must be an AgentAttachmentArtifact")
        from veritx_dse.model.route_artifact_v3 import (
            RouteArtifactV3, ShapePolicyRoute,
        )
        from veritx_dse.model.srota_rank_route import RankPolicyRoute
        if isinstance(router_route,
                      (RouteArtifactV3, ShapePolicyRoute, RankPolicyRoute,
                       GecHybridRoute)):
            return self._validate_against_v3(topology, attachment,
                                             router_route)
        if not isinstance(router_route, RouteArtifact):
            raise ResolvedRouteError("router_route must be a RouteArtifact")
        if self.schema_version != RESOLVED_ROUTE_SCHEMA_VERSION:
            raise ResolvedRouteError(
                f"a schema v{self.schema_version} resolved route cannot be "
                "validated against a v2 router route")
        if self.topology_hash != topology.topology_hash():
            raise ResolvedRouteError(
                "topology_hash does not match the materialized topology")
        if self.attachment_hash != attachment.attachment_hash():
            raise ResolvedRouteError(
                "attachment_hash does not match the attachment artifact")
        if self.router_route_hash != router_route.artifact_hash:
            raise ResolvedRouteError(
                "router_route_hash does not match the router route artifact")
        if router_route.schema_version != 2:
            raise ResolvedRouteError(
                "router route is not schema v2 (class-aware channel "
                "realization) — refusing to resolve endpoints against it")
        expected_classes = _router_route_classes(router_route)
        if self.routing_classes != expected_classes:
            raise ResolvedRouteError(
                f"routing_classes {list(self.routing_classes)} do not match "
                f"the router route classes {list(expected_classes)} "
                "(order is part of routing identity)")
        expected_pairs = tuple(
            (e.endpoint_id, e.router_id) for e in attachment.endpoints)
        if self.endpoint_to_router != expected_pairs:
            raise ResolvedRouteError(
                "endpoint_to_router does not match the attachment")
        for _eid, router_id in self.endpoint_to_router:
            if not 0 <= router_id < topology.router_count:
                raise ResolvedRouteError(
                    f"endpoint references router {router_id} outside the "
                    f"materialized topology")
        attachment.validate_against_topology(topology)
        router_route.validate_against(topology)
        recomputed = _endpoint_table_hash(_endpoint_route_table(
            self.endpoint_to_router, self.routing_classes,
            router_route.entries))
        if self.endpoint_route_table_hash != recomputed:
            raise ResolvedRouteError(
                "endpoint_route_table_hash does not match the expansion of "
                "the parent router route (fabricated endpoint tables are "
                "refused)")

    def _validate_against_v3(self, topology: TopologyArtifact,
                             attachment: AgentAttachmentArtifact,
                             router_route: Any) -> None:
        """The v3 seam check: same shape, decision-valued rows."""
        if self.schema_version != RESOLVED_ROUTE_V3_SCHEMA_VERSION:
            raise ResolvedRouteError(
                f"a schema v{self.schema_version} resolved route cannot be "
                "validated against a v3 router route")
        router_route.validate_against(topology)
        if self.topology_hash != topology.topology_hash():
            raise ResolvedRouteError(
                "topology_hash does not match the materialized topology")
        if self.attachment_hash != attachment.attachment_hash():
            raise ResolvedRouteError(
                "attachment_hash does not match the attachment artifact")
        if self.router_route_hash != router_route.route_artifact_id():
            raise ResolvedRouteError(
                "router_route_hash does not match the shared-resource route")
        if self.routing_classes != (router_route.routing_class,):
            raise ResolvedRouteError(
                f"routing_classes {list(self.routing_classes)} do not match "
                f"the v3 route class {router_route.routing_class!r}")
        expected_pairs = tuple(
            (e.endpoint_id, e.router_id) for e in attachment.endpoints)
        if self.endpoint_to_router != expected_pairs:
            raise ResolvedRouteError(
                "endpoint_to_router does not match the attachment")
        attachment.validate_against_topology(topology)
        recomputed = _endpoint_table_hash_v3(_endpoint_route_table_v3(
            self.endpoint_to_router, router_route.routing_class,
            router_route))
        if self.endpoint_route_table_hash != recomputed:
            raise ResolvedRouteError(
                "endpoint_route_table_hash does not match the v3 expansion "
                "of the parent route (fabricated endpoint tables are "
                "refused)")

def _endpoint_route_table(
        endpoint_to_router: tuple[tuple[int, int], ...],
        routing_classes: tuple[str, ...],
        router_entries: Mapping[tuple[str, int, int], int],
) -> list[list[Any]]:
    by_id = dict(endpoint_to_router)
    rows: list[list[Any]] = []
    for src in range(len(endpoint_to_router)):
        for dst in range(len(endpoint_to_router)):
            if src == dst:
                continue
            inj, eje = by_id[src], by_id[dst]
            for cls in routing_classes:
                if inj == eje:
                    rows.append([src, dst, cls, LOCAL_EJECTION, None])
                else:
                    key = (cls, inj, eje)
                    if key not in router_entries:
                        raise ResolvedRouteError(
                            f"router route has no {cls} entry for "
                            f"({inj},{eje}) needed by endpoint flow "
                            f"({src}->{dst})")
                    channel_id = router_entries[key]
                    if type(channel_id) is not int:
                        raise ResolvedRouteError(
                            f"router route {cls} entry for ({inj},{eje}) "
                            f"has non-integer channel id {channel_id!r}")
                    rows.append([src, dst, cls, "ROUTED", channel_id])
    return rows

def _endpoint_table_hash(rows: list[list[Any]]) -> str:
    return content_id(_ENDPOINT_TABLE_DOMAIN, rows)

def _endpoint_table_hash_v3(rows: list[list[Any]]) -> str:
    return content_id(_ENDPOINT_TABLE_DOMAIN_V3, rows)

def _router_of_node(route: Any, node: int) -> int:
    """The router a destination TERMINAL attaches to.

    A terminal number is not a router number once concentration exceeds one,
    so the route's own map is the authority. Falling back to the identity
    would silently mis-read local delivery as a transit hop.
    """
    return dict(route.terminal_to_router).get(node, node)

def _route_choices(route: Any, key: tuple[int, int]) -> tuple[Any, ...]:
    """Every decision a route may take for one pair, as a tuple.

    A deterministic route holds one; an adaptive (union) route holds several,
    and the endpoint row must carry ALL of them — recording only the first
    would certify an adaptive design against one of its choices.
    """
    from veritx_dse.model.route_artifact_v3 import ShapePolicyRoute
    from veritx_dse.model.srota_rank_route import RankPolicyRoute
    if isinstance(route, (ShapePolicyRoute, RankPolicyRoute, GecHybridRoute)):
        return tuple(route.choices.get(key, ()))
    decision = route.decisions.get(key)
    return () if decision is None else (decision,)


def _endpoint_route_table_v3(
        endpoint_to_router: tuple[tuple[int, int], ...],
        routing_class: str,
        route: Any,
) -> list[list[Any]]:
    """Expand endpoint flows into first-hop DECISIONS.

    Every terminal of a destination router must yield the same hop. If they
    do not, the route is not a function of the routers and there is no
    endpoint-resolved route to record — refuse rather than pick one.
    """
    by_id = dict(endpoint_to_router)
    nodes_of_router: dict[int, list[int]] = {}
    for node, router in sorted(route.terminal_to_router.items()):
        nodes_of_router.setdefault(router, []).append(node)
    rows: list[list[Any]] = []
    for src in range(len(endpoint_to_router)):
        for dst in range(len(endpoint_to_router)):
            if src == dst:
                continue
            inj, eje = by_id[src], by_id[dst]
            if inj == eje:
                rows.append([src, dst, routing_class, LOCAL_EJECTION, None])
                continue
            candidates = nodes_of_router.get(eje)
            if not candidates:
                raise ResolvedRouteError(
                    f"destination router {eje} (endpoint {dst}) has no "
                    "terminal in the route's terminal map; the route cannot "
                    "be bound to this attachment")
            first: tuple[Any, ...] | None = None
            for node in candidates:
                choices = _route_choices(route, (inj, node))
                if not choices:
                    raise ResolvedRouteError(
                        f"route has no {routing_class} entry for "
                        f"({inj},{node}) needed by endpoint flow "
                        f"({src}->{dst})")
                if first is None:
                    first = choices
                elif choices != first:
                    raise ResolvedRouteError(
                        f"endpoint flow {src}->{dst} reaches router {eje} "
                        "whose terminals disagree on the first hop "
                        f"({first} vs {choices}); the route is not a "
                        "function of the routers, so no endpoint-resolved "
                        "route can be recorded")
            rows.append([src, dst, routing_class, "ROUTED",
                         [d.to_dict() for d in first]])
    return rows

def derive_resolved_route_v3(topology: TopologyArtifact,
                             attachment: AgentAttachmentArtifact,
                             router_route: Any) -> ResolvedRouteArtifact:
    """Bind a shared-resource route (deterministic or union) to the fabric."""
    from veritx_dse.model.route_artifact_v3 import (
        RouteArtifactV3, ShapePolicyRoute,
    )
    from veritx_dse.model.srota_rank_route import RankPolicyRoute
    if not isinstance(topology, TopologyArtifact):
        raise ResolvedRouteError("topology must be a TopologyArtifact")
    if not isinstance(attachment, AgentAttachmentArtifact):
        raise ResolvedRouteError(
            "attachment must be an AgentAttachmentArtifact")
    if not isinstance(router_route,
                      (RouteArtifactV3, ShapePolicyRoute, RankPolicyRoute,
                       GecHybridRoute)):
        raise ResolvedRouteError(
            f"derive_resolved_route_v3 needs a RouteArtifactV3, a "
            f"ShapePolicyRoute or a RankPolicyRoute, got "
            f"{type(router_route).__name__}")
    router_route.validate_against(topology)
    pairs = tuple((e.endpoint_id, e.router_id) for e in attachment.endpoints)
    for _eid, router_id in pairs:
        if not 0 <= router_id < topology.router_count:
            raise ResolvedRouteError(
                f"attachment references router {router_id} outside the "
                "materialized topology")
    classes = (router_route.routing_class,)
    rows = _endpoint_route_table_v3(pairs, router_route.routing_class,
                                    router_route)
    artifact = ResolvedRouteArtifact(
        topology_hash=topology.topology_hash(),
        attachment_hash=attachment.attachment_hash(),
        router_route_hash=router_route.route_artifact_id(),
        endpoint_to_router=pairs,
        routing_classes=classes,
        endpoint_route_table_hash=_endpoint_table_hash_v3(rows),
        schema_version=RESOLVED_ROUTE_V3_SCHEMA_VERSION,
    )
    # Parent legality is a seam check; do it here so a caller cannot forget.
    artifact.validate_against(topology, attachment, router_route)
    return artifact

def derive_resolved_route(topology: TopologyArtifact,
                          attachment: AgentAttachmentArtifact,
                          router_route: RouteArtifact
                          ) -> ResolvedRouteArtifact:
    """Bind a class-aware router route to a materialized topology and the
    endpoint attachment, and compute the expanded endpoint routing hash."""
    if not isinstance(topology, TopologyArtifact):
        raise ResolvedRouteError("topology must be a TopologyArtifact")
    if not isinstance(attachment, AgentAttachmentArtifact):
        raise ResolvedRouteError(
            "attachment must be an AgentAttachmentArtifact")
    from veritx_dse.model.route_artifact_v3 import RouteArtifactV3
    if isinstance(router_route, RouteArtifactV3):
        # Reached by a shared-wire fabric whose route rule IS derived and
        # qualified (so ROUTING succeeded), but whose endpoint expansion has
        # not been built for v3. Name the real gap: the v2 refusal message
        # ("must be a RouteArtifact") would read as a type error and hide it.
        raise ResolvedRouteError(
            "UNSUPPORTED: this design routes over shared wires and produced "
            f"a v3 route ({router_route.routing_class}, "
            f"{len(router_route.decisions)} decisions). The resolved-route "
            "stage expands a v2 channel-id realization into an endpoint "
            "table and has no v3 equivalent yet, so the route cannot be "
            "bound to the attachment. The deadlock proof for this route is "
            "available from RouteArtifactV3.shared_resource_cdg(); what is "
            "missing is the endpoint expansion and the VC derivation that "
            "follow it")
    if not isinstance(router_route, RouteArtifact):
        raise ResolvedRouteError("router_route must be a RouteArtifact")
    if router_route.schema_version != 2:
        raise ResolvedRouteError(
            "derive_resolved_route requires a schema v2 RouteArtifact "
            "(class-aware channel realization); v1 is refused — rebuild "
            "from a v2 router route")
    pairs = tuple((e.endpoint_id, e.router_id) for e in attachment.endpoints)
    for _eid, router_id in pairs:
        if not 0 <= router_id < topology.router_count:
            raise ResolvedRouteError(
                f"attachment references router {router_id} outside the "
                "materialized topology")
    classes = _router_route_classes(router_route)
    rows = _endpoint_route_table(pairs, classes, router_route.entries)
    artifact = ResolvedRouteArtifact(
        topology_hash=topology.topology_hash(),
        attachment_hash=attachment.attachment_hash(),
        router_route_hash=router_route.artifact_hash,
        endpoint_to_router=pairs,
        routing_classes=classes,
        endpoint_route_table_hash=_endpoint_table_hash(rows),
    )
    artifact.validate_against(topology, attachment, router_route)
    return artifact
