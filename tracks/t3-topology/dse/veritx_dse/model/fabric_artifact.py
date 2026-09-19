"""veritx_dse.model.fabric_artifact — FabricArtifact (Wave B3.5a).

FabricArtifact is the single root identity of one resolved NoC/NI
hardware fabric. It is composition only: every child is an already
resolved semantic authority, and this module never rederives routes, VC
counts, packet widths, arbitration or topology.

    TopologyArtifact
          │
    AgentAttachmentArtifact
          │
    RouteArtifact (router-level, schema v2)
          │
    ResolvedRouteArtifact
          │
    VCAssignmentArtifact
          │
    ┌─────┴──────┐
    ▼            ▼
PacketFormat  RouterBehavior
    └─────┬──────┘
          ▼
     FabricArtifact          ← this module

Identity boundary (frozen):

    fabric_hash       = identity of resolved NoC/NI hardware semantics
    resolved_fabric   = design_hash + mapping_hash + fabric_hash

FabricArtifact therefore contains NO design_hash, mapping_hash, workload,
requirements, candidate/search provenance, backend configuration, run
ids, seeds, git SHAs, metrics, or verification evidence. Evidence is not
part of the architecture it certifies.

``FabricArtifact.validate_against`` proves the whole child DAG — not just
that six root hashes look right. Individually valid children that cannot
form one DAG (a Frankenstein fabric) are refused.

IMPORTANT NAMING NOTE: do not confuse this class with
``veritx_dse.core.fabric.FabricArtifact``, which is a legacy
executed/backend-evidence object (topology string, BookSim-ish config
hashes). That object is untouched by B3.5 and will be migrated/renamed in
B3.7; this module never imports it.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Any

from veritx_dse.core.route_artifact import RouteArtifact

from .attachment import AgentAttachmentArtifact
from .packet_format import PacketFormatArtifact
from .resolved_route import ResolvedRouteArtifact
from .router_behavior import RouterBehaviorArtifact
from .topology_artifact import TopologyArtifact
from .vc_assignment import VCAssignmentArtifact

FABRIC_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/Fabric"


class FabricArtifactError(ValueError):
    """The fabric composition is invalid or unproven — fail closed."""


def _as_str(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise FabricArtifactError(f"{name} must be a non-empty string")
    return value


def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise FabricArtifactError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise FabricArtifactError(
            f"{where} has unknown fields: {sorted(unknown)}")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise FabricArtifactError(
            f"{where} is missing required field {key!r}")
    return d[key]


class PlaneComposition(Enum):
    """How many semantic planes one fabric identity covers.

    v1 supports exactly one plane. Legacy rtlgen multi-plane experiments
    are NOT imported or certified here; true multi-plane support requires
    a schema that binds explicit per-plane fabrics/routes/VCs.
    """

    SINGLE_PLANE = "single_plane"


@dataclass(frozen=True)
class FabricArtifact:
    """Root hardware identity: the exact resolved NoC/NI semantics.

    The dataclass field is ``artifact_hash`` for consistency with the
    other semantic artifacts; the canonical public accessor is
    ``fabric_hash()`` and the persisted JSON key is ``fabric_hash``.
    """

    topology_hash: str
    attachment_hash: str
    resolved_route_hash: str
    vc_assignment_hash: str
    packet_format_hash: str
    router_behavior_hash: str

    plane_composition: PlaneComposition

    schema_version: int = FABRIC_SCHEMA_VERSION
    artifact_hash: str = ""

    def __post_init__(self):
        for name in ("topology_hash", "attachment_hash",
                     "resolved_route_hash", "vc_assignment_hash",
                     "packet_format_hash", "router_behavior_hash"):
            _as_str(name, getattr(self, name))
        if not isinstance(self.plane_composition, PlaneComposition):
            raise FabricArtifactError(
                "plane_composition must be a PlaneComposition")
        if self.plane_composition is not PlaneComposition.SINGLE_PLANE:
            raise FabricArtifactError(
                f"UNSUPPORTED plane composition "
                f"{self.plane_composition.value!r} in v1")
        if type(self.schema_version) is not int or \
                self.schema_version != FABRIC_SCHEMA_VERSION:
            raise FabricArtifactError(
                f"unsupported fabric schema_version "
                f"{self.schema_version!r} (expected {FABRIC_SCHEMA_VERSION})")
        expected = self._compute_hash()
        if self.artifact_hash and self.artifact_hash != expected:
            raise FabricArtifactError(
                "fabric_hash does not match content")
        if not self.artifact_hash:
            object.__setattr__(self, "artifact_hash", expected)

    # ── identity ───────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "topology_hash": self.topology_hash,
            "attachment_hash": self.attachment_hash,
            "resolved_route_hash": self.resolved_route_hash,
            "vc_assignment_hash": self.vc_assignment_hash,
            "packet_format_hash": self.packet_format_hash,
            "router_behavior_hash": self.router_behavior_hash,
            "plane_composition": self.plane_composition.value,
        }

    def _compute_hash(self) -> str:
        from veritx_dse.core.spec import canonical_json
        body = (f"{_HASH_TYPE_TAG}/v{self.schema_version}\0"
                + canonical_json(self.identity_dict()))
        return hashlib.sha256(body.encode()).hexdigest()

    def fabric_hash(self) -> str:
        return self._compute_hash()

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["fabric_hash"] = self.fabric_hash()
        return d

    # ── persisted parsing (self-integrity only) ────────────────────────
    @classmethod
    def from_dict(cls, d: Any) -> "FabricArtifact":
        allowed = frozenset({
            "type", "schema_version", "topology_hash", "attachment_hash",
            "resolved_route_hash", "vc_assignment_hash",
            "packet_format_hash", "router_behavior_hash",
            "plane_composition", "fabric_hash",
        })
        _strict_keys(d, allowed, "fabric")
        if _need(d, "type", "fabric") != _HASH_TYPE_TAG:
            raise FabricArtifactError(
                f"unexpected artifact type {d.get('type')!r}")
        if _need(d, "schema_version", "fabric") != FABRIC_SCHEMA_VERSION:
            raise FabricArtifactError(
                f"unsupported fabric schema_version "
                f"{d.get('schema_version')!r}")
        raw_plane = _need(d, "plane_composition", "fabric")
        if not isinstance(raw_plane, str):
            raise FabricArtifactError(
                "plane_composition must be a string enum value")
        try:
            plane = PlaneComposition(raw_plane)
        except ValueError:
            raise FabricArtifactError(
                f"unknown plane composition {raw_plane!r}; known: "
                f"{[m.value for m in PlaneComposition]}") from None
        return cls(
            topology_hash=_need(d, "topology_hash", "fabric"),
            attachment_hash=_need(d, "attachment_hash", "fabric"),
            resolved_route_hash=_need(d, "resolved_route_hash", "fabric"),
            vc_assignment_hash=_need(d, "vc_assignment_hash", "fabric"),
            packet_format_hash=_need(d, "packet_format_hash", "fabric"),
            router_behavior_hash=_need(d, "router_behavior_hash", "fabric"),
            plane_composition=plane,
            schema_version=d["schema_version"],
            artifact_hash=_need(d, "fabric_hash", "fabric"),
        )

    # ── parent/DAG legality ────────────────────────────────────────────
    def validate_against(self, *,
                         topology: TopologyArtifact,
                         attachment: AgentAttachmentArtifact,
                         router_route: RouteArtifact,
                         resolved_route: ResolvedRouteArtifact,
                         vc_assignment: VCAssignmentArtifact,
                         packet_format: PacketFormatArtifact,
                         router_behavior: RouterBehaviorArtifact) -> None:
        """Prove the complete child DAG, not just six root hash strings.

        DesignRevision/NodeInventory/MappingArtifact deliberately do not
        appear here: this is hardware identity. Their seam lives in
        ResolvedFabric.
        """
        if not isinstance(topology, TopologyArtifact):
            raise FabricArtifactError(
                f"topology must be a TopologyArtifact, got "
                f"{type(topology).__name__}")
        if not isinstance(attachment, AgentAttachmentArtifact):
            raise FabricArtifactError(
                f"attachment must be an AgentAttachmentArtifact, got "
                f"{type(attachment).__name__}")
        if not isinstance(router_route, RouteArtifact):
            raise FabricArtifactError(
                f"router_route must be a RouteArtifact, got "
                f"{type(router_route).__name__}")
        if not isinstance(resolved_route, ResolvedRouteArtifact):
            raise FabricArtifactError(
                f"resolved_route must be a ResolvedRouteArtifact, got "
                f"{type(resolved_route).__name__}")
        if not isinstance(vc_assignment, VCAssignmentArtifact):
            raise FabricArtifactError(
                f"vc_assignment must be a VCAssignmentArtifact, got "
                f"{type(vc_assignment).__name__}")
        if not isinstance(packet_format, PacketFormatArtifact):
            raise FabricArtifactError(
                f"packet_format must be a PacketFormatArtifact, got "
                f"{type(packet_format).__name__}")
        if not isinstance(router_behavior, RouterBehaviorArtifact):
            raise FabricArtifactError(
                f"router_behavior must be a RouterBehaviorArtifact, got "
                f"{type(router_behavior).__name__}")

        root_checks = (
            ("topology_hash", self.topology_hash,
             topology.topology_hash()),
            ("attachment_hash", self.attachment_hash,
             attachment.attachment_hash()),
            ("resolved_route_hash", self.resolved_route_hash,
             resolved_route.resolved_route_hash()),
            ("vc_assignment_hash", self.vc_assignment_hash,
             vc_assignment.vc_assignment_hash()),
            ("packet_format_hash", self.packet_format_hash,
             packet_format.packet_format_hash()),
            ("router_behavior_hash", self.router_behavior_hash,
             router_behavior.router_behavior_hash()),
        )
        for name, recorded, actual in root_checks:
            if recorded != actual:
                raise FabricArtifactError(
                    f"{name} does not match the supplied artifact")

        try:
            attachment.validate_against_topology(topology)
        except ValueError as exc:
            raise FabricArtifactError(
                f"attachment is not legal for topology: {exc}") from exc
        try:
            router_route.validate_against(topology)
        except ValueError as exc:
            raise FabricArtifactError(
                f"router_route is not legal for topology: {exc}") from exc

        try:
            resolved_route.validate_against(topology, attachment,
                                            router_route)
        except ValueError as exc:
            raise FabricArtifactError(
                f"resolved_route does not bind "
                f"topology+attachment+router_route: {exc}") from exc
        try:
            vc_assignment.validate_against(resolved_route)
        except ValueError as exc:
            raise FabricArtifactError(
                f"vc_assignment does not bind resolved_route: {exc}") from exc
        try:
            packet_format.validate_against(topology, attachment,
                                           vc_assignment)
        except ValueError as exc:
            raise FabricArtifactError(
                f"packet_format does not bind "
                f"topology+attachment+vc_assignment: {exc}") from exc
        try:
            router_behavior.validate_against(vc_assignment)
        except ValueError as exc:
            raise FabricArtifactError(
                f"router_behavior does not bind vc_assignment: {exc}") from exc


def make_fabric_artifact(
        *,
        topology: TopologyArtifact,
        attachment: AgentAttachmentArtifact,
        router_route: RouteArtifact,
        resolved_route: ResolvedRouteArtifact,
        vc_assignment: VCAssignmentArtifact,
        packet_format: PacketFormatArtifact,
        router_behavior: RouterBehaviorArtifact,
        plane_composition: PlaneComposition = PlaneComposition.SINGLE_PLANE,
) -> FabricArtifact:
    """Compose the root hardware identity from already-resolved children.

    Composition only: children are never rederived here.
    """
    artifact = FabricArtifact(
        topology_hash=topology.topology_hash(),
        attachment_hash=attachment.attachment_hash(),
        resolved_route_hash=resolved_route.resolved_route_hash(),
        vc_assignment_hash=vc_assignment.vc_assignment_hash(),
        packet_format_hash=packet_format.packet_format_hash(),
        router_behavior_hash=router_behavior.router_behavior_hash(),
        plane_composition=plane_composition,
    )
    artifact.validate_against(
        topology=topology, attachment=attachment, router_route=router_route,
        resolved_route=resolved_route, vc_assignment=vc_assignment,
        packet_format=packet_format, router_behavior=router_behavior)
    return artifact
