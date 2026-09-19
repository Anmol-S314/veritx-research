"""veritx_dse.model.resolved_fabric — ResolvedFabric (Wave B3.5b).

ResolvedFabric answers exactly one question:

    Which exact design and rank placement are bound to this exact
    hardware fabric?

It is the only place design identity and mapping identity meet hardware
identity. The root equation is:

    resolved_fabric_hash = H(design_hash, mapping_hash, fabric_hash)

with canonical JSON and domain separation (``srota/ResolvedFabric/v1\\0``).
It is not backend execution, not verification evidence, and not a
candidate/search record.

    fabric_hash       = resolved NoC/NI hardware semantics
    resolved_fabric   = design_hash + mapping_hash + fabric_hash

Seam obligations discharged here (the previously deferred B2/B3 parent
relations):

  * design_hash matches the design revision;
  * mapping_hash matches the mapping artifact;
  * fabric_hash matches the FabricArtifact, whose complete child DAG is
    revalidated (never trust a root hash alone), including the address
    decode against ``design.address_map`` + attachment;
  * attachment.validate_against(design, inventory, topology): complete
    design agent universe, idle agents included, interfaces and seats
    legal;
  * mapping placement seam: every mapping.placements[].agent must be an
    attached AgentInstance, by exact identity
    (group_index, instance_index, kind) — not by instance_id string;
  * rank-space seam: mapping.rank_count == inventory.rank_count and the
    mapping ranks are exactly the inventory logical rank ids;
  * design/inventory geometry seam: inventory.parallelism equals the
    workload's TP/PP/EP/DP shape and inventory.ranks is exactly the
    canonical rank namespace recomputed for that shape (equal world size
    with different geometry is refused);
  * idle compute agents remain legal (mapped => attached, never the
    inverse; non-compute hardware needs no rank placement).

FabricArtifact deliberately does not perform the design/inventory/
mapping checks; that boundary is fixed by B3.1d.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .address_decode import AddressDecodeArtifact
from .fabric_artifact import FabricArtifact
from .mapping import MappingArtifact
from .placement import (
    LogicalRank, NodeInventory, ParallelismShape, coords_of,
)

RESOLVED_FABRIC_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/ResolvedFabric"


class ResolvedFabricError(ValueError):
    """The design/mapping/fabric binding is invalid — fail closed."""


def _as_str(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ResolvedFabricError(f"{name} must be a non-empty string")
    return value


def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise ResolvedFabricError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise ResolvedFabricError(
            f"{where} has unknown fields: {sorted(unknown)}")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise ResolvedFabricError(
            f"{where} is missing required field {key!r}")
    return d[key]


@dataclass(frozen=True)
class ResolvedFabric:
    """Design + mapping bound to one resolved hardware fabric.

    The dataclass field is ``artifact_hash`` for consistency with the
    other semantic artifacts; the canonical public accessor is
    ``resolved_fabric_hash()`` and the persisted JSON key is
    ``resolved_fabric_hash``.
    """

    design_hash: str
    mapping_hash: str
    fabric_hash: str

    schema_version: int = RESOLVED_FABRIC_SCHEMA_VERSION
    artifact_hash: str = ""

    def __post_init__(self):
        for name in ("design_hash", "mapping_hash", "fabric_hash"):
            _as_str(name, getattr(self, name))
        if type(self.schema_version) is not int or \
                self.schema_version != RESOLVED_FABRIC_SCHEMA_VERSION:
            raise ResolvedFabricError(
                f"unsupported resolved-fabric schema_version "
                f"{self.schema_version!r} (expected "
                f"{RESOLVED_FABRIC_SCHEMA_VERSION})")
        expected = self._compute_hash()
        if self.artifact_hash and self.artifact_hash != expected:
            raise ResolvedFabricError(
                "resolved_fabric_hash does not match content")
        if not self.artifact_hash:
            object.__setattr__(self, "artifact_hash", expected)

    # ── identity ───────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "design_hash": self.design_hash,
            "mapping_hash": self.mapping_hash,
            "fabric_hash": self.fabric_hash,
        }

    def _compute_hash(self) -> str:
        from veritx_dse.core.spec import canonical_json
        body = (f"{_HASH_TYPE_TAG}/v{self.schema_version}\0"
                + canonical_json(self.identity_dict()))
        return hashlib.sha256(body.encode()).hexdigest()

    def resolved_fabric_hash(self) -> str:
        return self._compute_hash()

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["resolved_fabric_hash"] = self.resolved_fabric_hash()
        return d

    # ── persisted parsing (self-integrity only) ────────────────────────
    @classmethod
    def from_dict(cls, d: Any) -> "ResolvedFabric":
        allowed = frozenset({
            "type", "schema_version", "design_hash", "mapping_hash",
            "fabric_hash", "resolved_fabric_hash",
        })
        _strict_keys(d, allowed, "resolved_fabric")
        if _need(d, "type", "resolved_fabric") != _HASH_TYPE_TAG:
            raise ResolvedFabricError(
                f"unexpected artifact type {d.get('type')!r}")
        if _need(d, "schema_version", "resolved_fabric") != \
                RESOLVED_FABRIC_SCHEMA_VERSION:
            raise ResolvedFabricError(
                f"unsupported resolved-fabric schema_version "
                f"{d.get('schema_version')!r}")
        return cls(
            design_hash=_need(d, "design_hash", "resolved_fabric"),
            mapping_hash=_need(d, "mapping_hash", "resolved_fabric"),
            fabric_hash=_need(d, "fabric_hash", "resolved_fabric"),
            schema_version=d["schema_version"],
            artifact_hash=_need(d, "resolved_fabric_hash",
                                "resolved_fabric"),
        )

    # ── full seam validation ───────────────────────────────────────────
    def validate_against(self, *, design, inventory: NodeInventory,
                         mapping: MappingArtifact,
                         topology,
                         attachment,
                         router_route,
                         resolved_route,
                         vc_assignment,
                         packet_format,
                         router_behavior,
                         address_decode: AddressDecodeArtifact,
                         fabric: FabricArtifact) -> None:
        """Prove design+mapping really apply to this fabric.

        Order: root hash checks, attachment/design/inventory seam,
        mapping/attachment seam, rank-space seam, then the complete
        FabricArtifact DAG.
        """
        if not isinstance(inventory, NodeInventory):
            raise ResolvedFabricError(
                f"inventory must be a NodeInventory, got "
                f"{type(inventory).__name__}")
        if not isinstance(mapping, MappingArtifact):
            raise ResolvedFabricError(
                f"mapping must be a MappingArtifact, got "
                f"{type(mapping).__name__}")
        if not isinstance(fabric, FabricArtifact):
            raise ResolvedFabricError(
                f"fabric must be a FabricArtifact, got "
                f"{type(fabric).__name__}")
        if not isinstance(address_decode, AddressDecodeArtifact):
            raise ResolvedFabricError(
                f"address_decode must be an AddressDecodeArtifact, got "
                f"{type(address_decode).__name__}")
        if not hasattr(design, "design_hash"):
            raise ResolvedFabricError(
                "design must expose design_hash()")

        # 1. direct root hashes
        if self.design_hash != design.design_hash():
            raise ResolvedFabricError(
                "design_hash does not match the design revision")
        if self.mapping_hash != mapping.mapping_hash():
            raise ResolvedFabricError(
                "mapping_hash does not match the mapping artifact")
        if self.fabric_hash != fabric.fabric_hash():
            raise ResolvedFabricError(
                "fabric_hash does not match the FabricArtifact")

        # 1b. design <-> inventory parallelism geometry + rank namespace.
        # Equal world size is not enough: TP=4/PP=1 and TP=2/PP=2 both have
        # four ranks 0..3 but DIFFERENT logical coordinates.
        if not hasattr(design, "workload"):
            raise ResolvedFabricError("design must expose workload")
        expected_shape = ParallelismShape(
            tp=design.workload.tp, pp=design.workload.pp,
            ep=design.workload.ep, dp=design.workload.dp)
        if inventory.parallelism != expected_shape:
            raise ResolvedFabricError(
                f"NodeInventory parallelism "
                f"{inventory.parallelism.to_dict()} does not match design "
                f"workload {expected_shape.to_dict()}")
        expected_ranks = tuple(
            LogicalRank(rank=r,
                        **coords_of(r, tp=expected_shape.tp,
                                    pp=expected_shape.pp,
                                    ep=expected_shape.ep,
                                    dp=expected_shape.dp))
            for r in range(expected_shape.world_size))
        if inventory.ranks != expected_ranks:
            raise ResolvedFabricError(
                "NodeInventory logical ranks do not match the design's "
                "canonical rank namespace (rank id/coordinate mismatch)")

        # 2. attachment against design/inventory/topology
        try:
            attachment.validate_against(design, inventory, topology)
        except ValueError as exc:
            raise ResolvedFabricError(
                f"attachment does not bind design+inventory+topology: "
                f"{exc}") from exc

        # 3. mapping placement seam: exact AgentInstance identity
        attached = {(e.agent.group_index, e.agent.instance_index,
                     e.agent.kind)
                    for e in attachment.endpoints}
        for placement in mapping.placements:
            key = (placement.agent.group_index,
                   placement.agent.instance_index, placement.agent.kind)
            if key not in attached:
                raise ResolvedFabricError(
                    f"mapping rank {placement.rank} references unattached "
                    f"AgentInstance {placement.agent} "
                    f"(group {key[0]}, instance {key[1]}, kind "
                    f"{key[2].value!r})")

        # 4. rank-space seam
        if mapping.rank_count != inventory.rank_count:
            raise ResolvedFabricError(
                f"mapping has {mapping.rank_count} ranks but NodeInventory "
                f"declares {inventory.rank_count}")
        mapping_ranks = [p.rank for p in mapping.placements]
        inventory_ranks = [r.rank for r in inventory.ranks]
        if mapping_ranks != inventory_ranks:
            raise ResolvedFabricError(
                f"mapping ranks {mapping_ranks[:4]}... do not match the "
                f"inventory logical ranks {inventory_ranks[:4]}...")

        # 5. the complete hardware DAG (FabricArtifactError propagates).
        #    Passing design.address_map here proves the supplied decode
        #    artifact corresponds exactly to the design address map, while
        #    keeping design identity out of fabric identity.
        fabric.validate_against(
            topology=topology, attachment=attachment,
            router_route=router_route, resolved_route=resolved_route,
            vc_assignment=vc_assignment, packet_format=packet_format,
            router_behavior=router_behavior, address_decode=address_decode,
            address_map=design.address_map)


def make_resolved_fabric(*, design, inventory: NodeInventory,
                         mapping: MappingArtifact,
                         topology,
                         attachment,
                         router_route,
                         resolved_route,
                         vc_assignment,
                         packet_format,
                         router_behavior,
                         address_decode: AddressDecodeArtifact,
                         fabric: FabricArtifact) -> ResolvedFabric:
    """Bind design + mapping to an already-composed FabricArtifact.

    Composition only: no child is rederived.
    """
    artifact = ResolvedFabric(
        design_hash=design.design_hash(),
        mapping_hash=mapping.mapping_hash(),
        fabric_hash=fabric.fabric_hash(),
    )
    artifact.validate_against(
        design=design, inventory=inventory, mapping=mapping,
        topology=topology, attachment=attachment, router_route=router_route,
        resolved_route=resolved_route, vc_assignment=vc_assignment,
        packet_format=packet_format, router_behavior=router_behavior,
        address_decode=address_decode, fabric=fabric)
    return artifact
