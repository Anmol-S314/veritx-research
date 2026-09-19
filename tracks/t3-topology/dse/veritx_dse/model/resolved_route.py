"""veritx_dse.model.resolved_route — ResolvedRouteArtifact (Wave B3.2).

A router-level route table is NOT a fabric routing truth. It says how a
packet moves between ROUTERS; a fabric is routed between ENDPOINTS, whose
attachment to routers is a separate artifact (AgentAttachmentArtifact).

    TopologyArtifact ──► RouteArtifact (router-level)
            │                    │
            ▼                    ▼
    AgentAttachmentArtifact ──► ResolvedRouteArtifact
                                     │
                                     ▼
                              FabricArtifact (later: resolved_route_hash)

ResolvedRouteArtifact binds the exact three parents and owns the endpoint
interpretation: endpoint → router, local traffic as LOCAL_EJECTION (a rank
whose source and destination share a router does not take a network hop),
and an expanded endpoint route-table hash that is independently checkable.

Standalone AnyNet tooling keeps using the router-level RouteArtifact and
makes no endpoint claims — no synthetic attachments are invented here.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .attachment import AgentAttachmentArtifact
from .topology_artifact import TopologyArtifact

RESOLVED_ROUTE_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/ResolvedRouteArtifact"
LOCAL_EJECTION = "LOCAL_EJECTION"
DEFAULT_ROUTING_CLASS = "DEFAULT"


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


@dataclass(frozen=True)
class ResolvedRouteArtifact:
    """Endpoint-resolved routing for one candidate fabric."""

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
        eids = [e for e, _ in self.endpoint_to_router]
        if eids != list(range(len(eids))):
            raise ResolvedRouteError(
                "endpoint ids must be contiguous from 0")
        if not isinstance(self.routing_classes, tuple) or not self.routing_classes:
            raise ResolvedRouteError("routing_classes must be non-empty")
        if type(self.schema_version) is not int or \
                self.schema_version != RESOLVED_ROUTE_SCHEMA_VERSION:
            raise ResolvedRouteError(
                f"unsupported resolved-route schema_version "
                f"{self.schema_version!r}")
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
        from veritx_dse.core.spec import canonical_json
        body = (f"{_HASH_TYPE_TAG}/v{self.schema_version}\0"
                + canonical_json(self.canonical_dict()))
        return hashlib.sha256(body.encode()).hexdigest()

    def resolved_route_hash(self) -> str:
        return self._compute_hash()

    def to_dict(self) -> dict[str, Any]:
        d = self.canonical_dict()
        d["artifact_hash"] = self._compute_hash()
        return d

    # ── serialization (self-integrity only) ────────────────────────────
    @classmethod
    def from_dict(cls, d: Any) -> ResolvedRouteArtifact:
        """Deserialize and verify SELF-integrity only.

        Reference legality against the parents (topology/attachment/router
        route) is a seam check: call ``validate_against`` after loading.
        """
        _strict_keys(d, frozenset({
            "type", "schema_version", "topology_hash", "attachment_hash",
            "router_route_hash", "endpoint_to_router", "routing_classes",
            "endpoint_route_table_hash", "artifact_hash"}), "resolved_route")
        pairs = _need(d, "endpoint_to_router", "resolved_route")
        if not isinstance(pairs, list):
            raise ResolvedRouteError("endpoint_to_router must be a list")
        artifact = cls(
            topology_hash=_need(d, "topology_hash", "resolved_route"),
            attachment_hash=_need(d, "attachment_hash", "resolved_route"),
            router_route_hash=_need(d, "router_route_hash", "resolved_route"),
            endpoint_to_router=tuple((int(p[0]), int(p[1])) for p in pairs),
            routing_classes=tuple(
                _need(d, "routing_classes", "resolved_route")),
            endpoint_route_table_hash=_need(
                d, "endpoint_route_table_hash", "resolved_route"),
            schema_version=_need(d, "schema_version", "resolved_route"),
        )
        supplied = d.get("artifact_hash")
        if supplied is not None and supplied != artifact._compute_hash():
            raise ResolvedRouteError("artifact_hash does not match content")
        return artifact

    # ── seam validation (parent legality) ──────────────────────────────
    def validate_against(self, topology: TopologyArtifact,
                         attachment: AgentAttachmentArtifact,
                         router_route) -> None:
        """Prove every reference is legal against the declared parents."""
        if self.topology_hash != topology.topology_hash():
            raise ResolvedRouteError(
                "topology_hash does not match the materialized topology")
        if self.attachment_hash != attachment.attachment_hash():
            raise ResolvedRouteError(
                "attachment_hash does not match the attachment artifact")
        if self.router_route_hash != getattr(router_route, "artifact_hash", ""):
            raise ResolvedRouteError(
                "router_route_hash does not match the router route artifact")
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
        entries = getattr(router_route, "entries", {})
        by_id = dict(self.endpoint_to_router)
        for src in range(len(self.endpoint_to_router)):
            for dst in range(len(self.endpoint_to_router)):
                if src == dst:
                    continue
                inj, eje = by_id[src], by_id[dst]
                if inj == eje:
                    continue  # LOCAL_EJECTION needs no router entry
                if (inj, eje) not in entries:
                    raise ResolvedRouteError(
                        f"router route has no entry for ({inj},{eje}) needed "
                        f"by endpoint flow ({src}->{dst})")


def _endpoint_route_table(
        endpoint_to_router: tuple[tuple[int, int], ...],
        routing_classes: tuple[str, ...],
        router_entries: dict[tuple[int, int], int],
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
                    rows.append([src, dst, cls, "ROUTED",
                                 int(router_entries[(inj, eje)])])
    return rows


def derive_resolved_route(topology: TopologyArtifact,
                          attachment: AgentAttachmentArtifact,
                          router_route) -> ResolvedRouteArtifact:
    """Bind a router route realization to a materialized topology and the
    endpoint attachment, and compute the expanded endpoint routing hash."""
    from veritx_dse.core.spec import canonical_json

    pairs = tuple((e.endpoint_id, e.router_id) for e in attachment.endpoints)
    for _eid, router_id in pairs:
        if not 0 <= router_id < topology.router_count:
            raise ResolvedRouteError(
                f"attachment references router {router_id} outside the "
                "materialized topology")
    classes = tuple(getattr(router_route, "routing_classes",
                            (DEFAULT_ROUTING_CLASS,)))
    rows = _endpoint_route_table(pairs, classes, dict(router_route.entries))
    table_hash = hashlib.sha256(
        (f"{_HASH_TYPE_TAG}/endpoint-table/v1\0"
         + canonical_json(rows)).encode()).hexdigest()
    artifact = ResolvedRouteArtifact(
        topology_hash=topology.topology_hash(),
        attachment_hash=attachment.attachment_hash(),
        router_route_hash=router_route.artifact_hash,
        endpoint_to_router=pairs,
        routing_classes=classes,
        endpoint_route_table_hash=table_hash,
    )
    artifact.validate_against(topology, attachment, router_route)
    return artifact
