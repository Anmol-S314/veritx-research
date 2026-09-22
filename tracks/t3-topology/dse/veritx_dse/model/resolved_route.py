"""veritx_dse.model.resolved_route — endpoint-resolved routing identity.

A router-level route table is not a fabric routing truth: it says how
traffic moves between ROUTERS, while a fabric is routed between ENDPOINTS
whose attachment to routers is a separate artifact.

    TopologyArtifact ──► RouteArtifact (class-aware, exact channels)
            │                     │
            ▼                     ▼
    AgentAttachmentArtifact ──► ResolvedRouteArtifact
                                      │
                                      ▼
                              VCAssignmentArtifact (later)

ResolvedRouteArtifact binds exactly those three parents and owns the
endpoint interpretation:

  * endpoint → router mapping, copied from the attachment;
  * the routing-class axis, in the parent route's exact order;
  * an expanded endpoint route-table digest covering every
    (endpoint_src, endpoint_dst, routing_class) row with the exact first
    network channel selected by the class-specific router table;
  * LOCAL_EJECTION for endpoint pairs sharing a router: local traffic
    takes no network hop and no channel is fabricated.

The expanded table itself is not stored. The compact digest plus
deterministic re-derivation from the three parents is sufficient, and
validate_against() recomputes the digest, so a fabricated endpoint-table
hash cannot pass.

Identity vs transport: ``resolved_route_hash()`` covers the semantic fields
including ``endpoint_route_table_hash``. ``validate_against()`` proves the
parents accept each other and that the digest really is the expansion of
their entries. Schema v1 (classless next-router expansion) is refused on
the authoritative path; there is no migration here.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.core.route_artifact import RouteArtifact
from veritx_dse.model.attachment import AgentAttachmentArtifact
from veritx_dse.model.topology_artifact import TopologyArtifact

RESOLVED_ROUTE_SCHEMA_VERSION = 2
_HASH_TYPE_TAG = "srota/ResolvedRouteArtifact"
_ENDPOINT_TABLE_DOMAIN = "srota/ResolvedRouteArtifact/endpoint-table/v2"
LOCAL_EJECTION = "LOCAL_EJECTION"


class ResolvedRouteError(ValueError):
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
                self.schema_version != RESOLVED_ROUTE_SCHEMA_VERSION:
            raise ResolvedRouteError(
                f"unsupported resolved-route schema_version "
                f"{self.schema_version!r} (expected "
                f"{RESOLVED_ROUTE_SCHEMA_VERSION})")
        expected = self._compute_hash()
        if self.artifact_hash and self.artifact_hash != expected:
            raise ResolvedRouteError(
                "artifact_hash does not match content")

    # ── identity ───────────────────────────────────────────────────────
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

    def resolved_route_hash(self) -> str:
        return self._compute_hash()

    def to_dict(self) -> dict[str, Any]:
        d = self.canonical_dict()
        d["artifact_hash"] = self._compute_hash()
        return d

    # ── serialization (self-integrity only) ────────────────────────────
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

    # ── seam validation (parent legality) ──────────────────────────────
    def validate_against(self, topology: TopologyArtifact,
                         attachment: AgentAttachmentArtifact,
                         router_route: RouteArtifact) -> None:
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
        if not isinstance(router_route, RouteArtifact):
            raise ResolvedRouteError("router_route must be a RouteArtifact")
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
        # Parent-chain seams: each parent must accept the SAME topology,
        # not merely agree on an independently declared hash.
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
