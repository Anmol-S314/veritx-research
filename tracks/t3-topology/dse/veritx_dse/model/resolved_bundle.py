"""veritx_dse.model.resolved_bundle — ResolvedFabricBundle (B3.7a).

A lowerer must receive the ACTUAL semantic objects needed to revalidate
the DAG — never a root hash alone. Because ResolvedFabric stores only
(design_hash, mapping_hash, fabric_hash), proving its binding requires the
design revision, inventory and mapping objects too; the bundle carries
them all.

Constructing a bundle already validates; ``revalidate()`` re-runs the two
root seams immediately before lowering so a caller cannot lower from a
bundle assembled around a stale/tampered child.

    fabrication.validate_against(all children)          (hardware DAG)
    resolved_fabric.validate_against(design, inventory, mapping, ..., fabric)
                                                        (design/mapping seam)

There is deliberately no persisted "bundle artifact": the bundle is an
in-memory proof carrier, and every child is separately content-addressed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.core.route_artifact import RouteArtifact
from veritx_dse.model.address_decode import AddressDecodeArtifact
from veritx_dse.model.attachment import AgentAttachmentArtifact
from veritx_dse.model.fabric_artifact import FabricArtifact
from veritx_dse.model.mapping import MappingArtifact
from veritx_dse.model.packet_format import PacketFormatArtifact
from veritx_dse.model.placement import NodeInventory
from veritx_dse.model.resolved_fabric import ResolvedFabric
from veritx_dse.model.resolved_route import ResolvedRouteArtifact
from veritx_dse.model.router_behavior import RouterBehaviorArtifact
from veritx_dse.model.topology_artifact import TopologyArtifact
from veritx_dse.model.vc_assignment import VCAssignmentArtifact


class ResolvedFabricBundleError(ValueError):
    """The bundle cannot be validated as one semantic fabric — fail closed."""


@dataclass(frozen=True)
def _hash_of(obj: Any, name: str) -> str:
    """Read a child-artifact hash that may be a method (RT v1) or a
    stored attribute (canonical v2). Identity comes from the child;
    this shim only normalizes the accessor."""
    value = getattr(obj, name)
    return value() if callable(value) else value

class ResolvedFabricBundle:
    """The complete, revalidated semantic fabric a lowerer consumes."""

    design: Any
    inventory: NodeInventory
    mapping: MappingArtifact
    topology: TopologyArtifact
    attachment: AgentAttachmentArtifact
    router_route: RouteArtifact
    resolved_route: ResolvedRouteArtifact
    vc_assignment: VCAssignmentArtifact
    packet_format: PacketFormatArtifact
    router_behavior: RouterBehaviorArtifact
    address_decode: AddressDecodeArtifact
    fabric: FabricArtifact
    resolved_fabric: ResolvedFabric

    # ── validation ─────────────────────────────────────────────────────
    def revalidate(self) -> None:
        """Re-prove the complete hardware DAG and the design/mapping seam.

        Raises the child artifact's own error type (FabricArtifactError /
        ResolvedFabricError) — callers wrap into their lowering error.
        """
        # Child-hash accessor shims: RT v1 exposes hashes as methods,
        # canonical v2 as stored attributes (veritx-integrate adapter).
        fabric_validate = getattr(self.fabric, "validate_against", None) \
            or self.fabric.validate_against_deterministic
        fabric_validate(
            topology=self.topology, attachment=self.attachment,
            router_route=self.router_route,
            resolved_route=self.resolved_route,
            vc_assignment=self.vc_assignment,
            packet_format=self.packet_format,
            router_behavior=self.router_behavior,
            address_decode=self.address_decode)
        resolved_validate = getattr(self.resolved_fabric,
                                    "validate_against", None) \
            or self.resolved_fabric.validate_against_deterministic
        resolved_validate(
            design=self.design, inventory=self.inventory,
            mapping=self.mapping, topology=self.topology,
            attachment=self.attachment, router_route=self.router_route,
            resolved_route=self.resolved_route,
            vc_assignment=self.vc_assignment,
            packet_format=self.packet_format,
            router_behavior=self.router_behavior,
            address_decode=self.address_decode, fabric=self.fabric)

    # ── evidence convenience ───────────────────────────────────────────
    def root_hashes(self) -> dict[str, str]:
        return {
            "resolved_fabric_hash": _hash_of(self.resolved_fabric, "resolved_fabric_hash"),
            "fabric_hash": _hash_of(self.fabric, "fabric_hash"),
            "design_hash": self.resolved_fabric.design_hash,
            "mapping_hash": self.resolved_fabric.mapping_hash,
            "topology_hash": _hash_of(self.topology, "topology_hash"),
            "attachment_hash": _hash_of(self.attachment, "attachment_hash"),
            "router_route_hash": _hash_of(self.router_route, "artifact_hash"),
            "resolved_route_hash": _hash_of(self.resolved_route, "resolved_route_hash"),
            "vc_assignment_hash": _hash_of(self.vc_assignment, "vc_assignment_hash"),
            "packet_format_hash": _hash_of(self.packet_format, "packet_format_hash"),
            "router_behavior_hash": _hash_of(self.router_behavior, "router_behavior_hash"),
            "address_decode_hash": _hash_of(self.address_decode, "address_decode_hash"),
        }


def make_resolved_fabric_bundle(
        *,
        design: Any,
        inventory: NodeInventory,
        mapping: MappingArtifact,
        topology: TopologyArtifact,
        attachment: AgentAttachmentArtifact,
        router_route: RouteArtifact,
        resolved_route: ResolvedRouteArtifact,
        vc_assignment: VCAssignmentArtifact,
        packet_format: PacketFormatArtifact,
        router_behavior: RouterBehaviorArtifact,
        address_decode: AddressDecodeArtifact,
        fabric: FabricArtifact,
        resolved_fabric: ResolvedFabric,
) -> ResolvedFabricBundle:
    """Compose AND validate the bundle (composition only, no rederivation)."""
    bundle = ResolvedFabricBundle(
        design=design, inventory=inventory, mapping=mapping,
        topology=topology, attachment=attachment,
        router_route=router_route, resolved_route=resolved_route,
        vc_assignment=vc_assignment, packet_format=packet_format,
        router_behavior=router_behavior, address_decode=address_decode,
        fabric=fabric, resolved_fabric=resolved_fabric)
    try:
        bundle.revalidate()
    except ValueError as exc:
        raise ResolvedFabricBundleError(
            f"resolved fabric bundle failed validation: {exc}") from exc
    return bundle


__all__ = [
    "ResolvedFabricBundle",
    "ResolvedFabricBundleError",
    "make_resolved_fabric_bundle",
]
