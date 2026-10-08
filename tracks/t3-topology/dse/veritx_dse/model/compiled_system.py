"""Canonical compiled root over child artifacts, not a flattened mega-document.

Phase A retains the resolved hardware bundle and legacy qualified routing.
Normalized network children are additional derived views, never independent
truth. Missing subsystem children mean NOT MATERIALIZED, never neutral policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.core.artifact import (
    content_id, require_fields, require_type_tag, require_schema_version,
    require_embedded_id, canonical_bytes,
)
from veritx_dse.core.errors import EvidenceInvalid, InvalidInput


def _identity(obj, accessor):
    value = getattr(obj, accessor)
    return value() if callable(value) else value


@dataclass(frozen=True)
class CompiledSystemArtifact:
    request: Any
    fabric: Any
    network_certificate: Any
    resource_graph: Any
    allocation: Any
    routing_policy: Any = None
    dependency_proof: Any = None
    access_system: Any = None
    sidebands: Any = None
    clock_domains: Any = None
    control_plane: Any = None
    adaptive: Any = None
    normalization_refusal: str | None = None

    def child_identities(self):
        children = dict(self.fabric.root_hashes())
        children.update({
            "authored_design": self.request.design_hash(),
            "legacy_node_inventory": content_id("veritx/LegacyNodeInventory/v1", self.fabric.inventory.to_dict()),
            "resource_graph": self.resource_graph.artifact_id(),
            "resource_allocation": self.allocation.artifact_id(),
            "network_certificate": self.network_certificate.certificate_id(),
        })
        for name, obj, accessor in (
                ("routing_policy", self.routing_policy, "artifact_id"),
                ("dependency_proof", self.dependency_proof, "artifact_id"),
                ("access_system", self.access_system, "policy_hash"),
                ("sidebands", self.sidebands, "content_hash"),
                ("clock_domains", self.clock_domains, "content_hash"),
                ("legacy_control_plane", self.control_plane, "content_hash")):
            children[name] = _identity(obj, accessor) if obj is not None else None
        if self.adaptive is not None:
            children.update({"adaptive_policy": self.adaptive.policy.policy_hash,
                             "adaptive_relation": self.adaptive.relation.relation_hash,
                             "adaptive_allocation": self.adaptive.esc_resource.artifact_hash,
                             "adaptive_binding": self.adaptive.binding.binding_hash,
                             "adaptive_fabric": _identity(self.adaptive.fabric, "fabric_hash"),
                             "resolved_adaptive_fabric": _identity(self.adaptive.resolved_fabric, "resolved_fabric_hash")})
        return children

    def identity_dict(self):
        return {"type": "veritx/CompiledSystemArtifact", "schema_version": 1,
                "system_semantics_version": 1, "design_identity": self.request.design_hash(),
                "children": self.child_identities(),
                "scopes": {"hardware": "LEGACY_CERTIFICATE_OBLIGATIONS",
                           "routing": "NORMALIZED_TRANSIT" if self.routing_policy is not None else "LEGACY_ADAPTER_RETAINED",
                           "extensions": "DECLARED_V5_STRUCTURE_ONLY",
                           "control_plane": "DECLARED_STRUCTURE_ONLY",
                           "transactions": "NOT_MATERIALIZED", "domain_execution": "NOT_MODELED",
                           "physical": "LEGACY_TOPOLOGY_HINTS_ONLY"}}

    def system_hash(self):
        return content_id("veritx/CompiledSystemArtifact/v1", self.identity_dict())

    def to_dict(self):
        return {**self.identity_dict(), "system_hash": self.system_hash(),
                "normalization_refusal": self.normalization_refusal}

    def revalidate(self):
        from veritx_dse.verification.system_certificate import revalidate_compiled_system
        revalidate_compiled_system(self)

    @classmethod
    def from_dict(cls, d, *, parents: CompiledSystemArtifact):
        """Resolve a durable root against supplied child artifacts and reprove.

        This is not a hash-only read. Child loading stays with each versioned
        reader; the resolver supplies those children before root admission.
        """
        fields = {"type", "schema_version", "system_semantics_version", "design_identity",
                  "children", "scopes", "system_hash", "normalization_refusal"}
        require_fields(d, fields, "compiled system")
        require_type_tag(d, "veritx/CompiledSystemArtifact", "compiled system")
        if type(d.get("schema_version")) is not int or type(d.get("system_semantics_version")) is not int:
            raise InvalidInput("system schema/semantics versions must be exact ints")
        require_schema_version(d, 1, "compiled system")
        if not isinstance(parents, cls):
            raise InvalidInput("compiled system requires resolved child artifacts")
        parents.revalidate()
        if canonical_bytes({key: d.get(key) for key in parents.identity_dict()}) != canonical_bytes(parents.identity_dict()):
            raise EvidenceInvalid("system root differs from revalidated child identities/scopes")
        require_embedded_id(d, "system_hash", parents.system_hash(), "compiled system")
        return parents
