"""Routing-independent allocation plus explicit partition-to-VC resolution."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from types import MappingProxyType

from veritx_dse.core.artifact import (
    FrozenMap, content_id, freeze, thaw, require_fields, require_type_tag,
    require_schema_version, require_embedded_id,
)
from veritx_dse.core.errors import InvalidInput
from veritx_dse.model.resource_graph import exact_int
from veritx_dse.model.vc_resource import VCResourceArtifact


@dataclass(frozen=True)
class ResourceAllocationArtifact:
    resources: VCResourceArtifact
    partitions: tuple[tuple[str, tuple[int, ...]], ...]
    escape_vcs: tuple[int, ...] = ()
    buffer_policy: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self):
        if not isinstance(self.resources, VCResourceArtifact):
            raise InvalidInput("allocation requires concrete VC resources")
        VCResourceArtifact.from_dict(self.resources.to_dict())
        if not isinstance(self.partitions, tuple) or not self.partitions:
            raise InvalidInput("allocation requires explicit partition bindings")
        owners, names = {}, set()
        for name, vcs in self.partitions:
            if not isinstance(name, str) or not name or name in names:
                raise InvalidInput("allocation partitions require unique nonempty names")
            names.add(name)
            if not isinstance(vcs, tuple) or not vcs or tuple(sorted(set(vcs))) != vcs:
                raise InvalidInput("partition VCs must be sorted, unique and nonempty")
            for vc in vcs:
                exact_int("partition VC", vc)
                if vc not in self.resources.vc_ids or vc in owners:
                    raise InvalidInput("partitions must disjointly bind the concrete VC universe")
                owners[vc] = name
        if set(owners) != set(self.resources.vc_ids):
            raise InvalidInput("allocation leaves a concrete VC unbound")
        if not isinstance(self.escape_vcs, tuple) or tuple(sorted(set(self.escape_vcs))) != self.escape_vcs:
            raise InvalidInput("escape VCs must be canonical")
        for vc in self.escape_vcs:
            exact_int("escape VC", vc)
            if vc not in owners:
                raise InvalidInput("escape VC is outside the allocation")
        policy = freeze(self.buffer_policy)
        if not isinstance(policy, FrozenMap):
            raise InvalidInput("buffer policy must be an object; empty means unspecified")
        object.__setattr__(self, "buffer_policy", policy)
        object.__setattr__(self, "partitions", tuple(sorted(self.partitions)))
        object.__setattr__(self, "_partitions", MappingProxyType(dict(self.partitions)))

    def vcs(self, partition: str) -> tuple[int, ...]:
        try:
            return self._partitions[partition]
        except KeyError:
            raise InvalidInput(f"routing names unallocated partition {partition!r}") from None

    def identity_dict(self):
        return {"type": "veritx/ResourceAllocationArtifact", "schema_version": 1,
                "vc_resource_hash": self.resources.artifact_hash,
                "partitions": [[name, list(vcs)] for name, vcs in self.partitions],
                "escape_vcs": list(self.escape_vcs), "buffer_policy": thaw(self.buffer_policy)}

    @cached_property
    def _artifact_id(self):
        return content_id("veritx/ResourceAllocationArtifact/v1", self.identity_dict())

    def artifact_id(self):
        return self._artifact_id

    def to_dict(self):
        return {**self.identity_dict(), "resources": self.resources.to_dict(), "artifact_id": self.artifact_id()}

    @classmethod
    def from_dict(cls, d):
        require_fields(d, {"type", "schema_version", "vc_resource_hash", "partitions", "escape_vcs",
                           "buffer_policy", "resources", "artifact_id"}, "allocation")
        require_type_tag(d, "veritx/ResourceAllocationArtifact", "allocation")
        if type(d.get("schema_version")) is not int:
            raise InvalidInput("allocation schema version must be an exact int")
        require_schema_version(d, 1, "allocation")
        if type(d.get("partitions")) is not list or type(d.get("escape_vcs")) is not list:
            raise InvalidInput("allocation bindings must be JSON lists")
        rows = []
        for row in d["partitions"]:
            if type(row) is not list or len(row) != 2 or type(row[1]) is not list:
                raise InvalidInput("allocation partition must be [name, [VCs]]")
            rows.append((row[0], tuple(row[1])))
        result = cls(VCResourceArtifact.from_dict(d["resources"]), tuple(rows),
                     tuple(d["escape_vcs"]), freeze(d["buffer_policy"]))
        if result.resources.artifact_hash != d["vc_resource_hash"]:
            raise InvalidInput("allocation VC-resource parent mismatch")
        require_embedded_id(d, "artifact_id", result.artifact_id(), "allocation")
        return result


def allocation_from_assignment(assignment, route=None, *, buffer_policy=None):
    from veritx_dse.model.vc_resource import vc_resources_from_assignment
    resources = vc_resources_from_assignment(assignment)
    if route is not None and hasattr(route, "partition_to_vcs"):
        partitions = tuple((str(p), tuple(vcs)) for p, vcs in sorted(route.partition_to_vcs.items()))
    else:
        grouped = {}
        for vc, routing_class in assignment.vc_to_routing_class:
            grouped.setdefault(routing_class, []).append(vc)
        partitions = tuple((name, tuple(vcs)) for name, vcs in sorted(grouped.items()))
    return ResourceAllocationArtifact(resources, partitions, assignment.escape_vcs,
                                      freeze(buffer_policy or {}))
