"""Multi-plane VC binding: each traffic class rides exactly ONE subnet.

A single flat ``VCAssignmentArtifact`` cannot describe a multi-plane
fabric. Plane C is a SECOND subnet with its own REQ/RSP/SNP VCs, and its
VC index space is independent of Plane D's. Two traffic classes on
different subnets therefore share NO VC resource even when their
subnet-local indices coincide — exactly the case the flat class/VC
admission misreads as a subset overlap.

This artifact binds each traffic class to a subnet and carries one
``VCAssignmentArtifact`` per subnet. Subnet 0 is the primary Plane D
assignment (which also travels as ``bundle.vc_assignment``); the
secondaries are the additional planes. It is a STRUCTURAL binding: a
secondary subnet's routing authority is its own declared route
(``control_plane.py``), never a proof of the primary plane's
deadlock-freedom, and no traffic/timing claim is made for it here.
"""
from __future__ import annotations

import hashlib

from dataclasses import dataclass
from typing import Any

from veritx_dse.core.errors import SemanticError
from veritx_dse.core.spec import canonical_json

from .control_plane import (
    PLANE_C_ROUTING_CLASS,
    ControlPlaneArtifact,
    ControlPlaneError,
    materialize_control_plane,
)
from .vc_assignment import VCAssignmentArtifact

MULTI_PLANE_VC_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/MultiPlaneVCAssignment"


class MultiPlaneVCError(ValueError, SemanticError):
    """The multi-plane VC binding is malformed or inconsistent."""


def _require_assignment(value: Any, where: str) -> VCAssignmentArtifact:
    if not isinstance(value, VCAssignmentArtifact):
        raise MultiPlaneVCError(
            f"{where} must be a VCAssignmentArtifact, got "
            f"{type(value).__name__}")
    return value


@dataclass(frozen=True)
class MultiPlaneVCAssignment:
    """Per-subnet VC structure plus the class -> subnet binding."""

    primary: VCAssignmentArtifact
    #: (subnet, assignment) for subnet >= 1, sorted by subnet.
    secondary: tuple[tuple[int, VCAssignmentArtifact], ...]
    #: (traffic_class, subnet), sorted by class name.
    traffic_class_to_subnet: tuple[tuple[str, int], ...]
    schema_version: int = MULTI_PLANE_VC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_assignment(self.primary, "primary")
        if type(self.schema_version) is not int or \
                self.schema_version != MULTI_PLANE_VC_SCHEMA_VERSION:
            raise MultiPlaneVCError(
                f"unsupported multi-plane vc schema_version "
                f"{self.schema_version!r}")
        if not isinstance(self.secondary, tuple) or not self.secondary:
            raise MultiPlaneVCError(
                "a multi-plane binding needs at least one secondary subnet")
        seen_subnets: list[int] = []
        for row in self.secondary:
            if not isinstance(row, tuple) or len(row) != 2:
                raise MultiPlaneVCError(
                    "secondary entries must be (subnet, assignment) pairs")
            subnet, assignment = row
            if type(subnet) is not int or subnet < 1:
                raise MultiPlaneVCError("secondary subnets must be ints >= 1")
            if subnet in seen_subnets:
                raise MultiPlaneVCError(
                    f"secondary subnet {subnet} declared twice")
            _require_assignment(assignment, f"secondary subnet {subnet}")
            seen_subnets.append(subnet)
        if seen_subnets != sorted(set(seen_subnets)):
            raise MultiPlaneVCError(
                "secondary subnets must be sorted and unique")
        if 0 in seen_subnets:
            raise MultiPlaneVCError("subnet 0 is the primary, not a secondary")
        if not isinstance(self.traffic_class_to_subnet, tuple) or \
                not self.traffic_class_to_subnet:
            raise MultiPlaneVCError(
                "traffic_class_to_subnet must be a non-empty tuple")
        binding: dict[str, int] = {}
        previous: str | None = None
        for row in self.traffic_class_to_subnet:
            if not isinstance(row, tuple) or len(row) != 2:
                raise MultiPlaneVCError(
                    "traffic_class_to_subnet entries must be (class, subnet) "
                    "pairs")
            cls, subnet = row
            if not isinstance(cls, str) or not cls:
                raise MultiPlaneVCError(
                    "traffic class names must be non-empty strings")
            if cls in binding:
                raise MultiPlaneVCError(
                    f"traffic class {cls!r} bound to a subnet twice")
            if previous is not None and cls <= previous:
                raise MultiPlaneVCError(
                    "traffic_class_to_subnet must be sorted by class name")
            previous = cls
            if type(subnet) is not int or subnet < 0:
                raise MultiPlaneVCError("subnet ids must be ints >= 0")
            if subnet != 0 and subnet not in seen_subnets:
                raise MultiPlaneVCError(
                    f"traffic class {cls!r} rides undeclared subnet "
                    f"{subnet}")
            binding[cls] = subnet
        # The binding is the AUTHORITY for which class rides which plane.
        # ``primary`` is the flat Plane-D derivation, produced before the
        # split, so it may over-declare a class the binding routes to a
        # secondary subnet; that entry is simply never exercised on Plane D.
        # A secondary subnet, by contrast, may only declare the classes the
        # binding places on it, and every bound class must be declared by
        # the assignment that owns its subnet.
        for subnet, assignment in self.secondary:
            for cls, _vcs in assignment.traffic_class_to_vcs:
                if cls not in binding:
                    raise MultiPlaneVCError(
                        f"subnet {subnet} declares traffic class {cls!r} "
                        f"with no class->subnet binding")
                if binding[cls] != subnet:
                    raise MultiPlaneVCError(
                        f"traffic class {cls!r} is declared by subnet "
                        f"{subnet} but bound to subnet {binding[cls]}")
        for cls, subnet in binding.items():
            owner = self.assignment_for(subnet)
            if cls not in {c for c, _v in owner.traffic_class_to_vcs}:
                raise MultiPlaneVCError(
                    f"traffic class {cls!r} is bound to subnet {subnet} "
                    f"but that subnet's assignment does not declare it")

    def _assignments(self) -> tuple[tuple[int, VCAssignmentArtifact], ...]:
        return ((0, self.primary),) + self.secondary

    def subnets(self) -> tuple[int, ...]:
        return tuple(subnet for subnet, _a in self._assignments())

    def assignment_for(self, subnet: int) -> VCAssignmentArtifact:
        for declared, assignment in self._assignments():
            if declared == subnet:
                return assignment
        raise MultiPlaneVCError(f"no VC assignment for subnet {subnet}")

    def subnet_of(self, traffic_class: str) -> int:
        for cls, subnet in self.traffic_class_to_subnet:
            if cls == traffic_class:
                return subnet
        raise MultiPlaneVCError(
            f"traffic class {traffic_class!r} is not bound to a subnet")

    def classes_on(self, subnet: int) -> tuple[str, ...]:
        return tuple(cls for cls, s in self.traffic_class_to_subnet
                     if s == subnet)

    def routing_class_for(self, subnet: int) -> str:
        """The single routing class a secondary subnet declares.

        Plane D's routing classes are owned by the primary route artifact;
        this is only defined for the declared secondary planes.
        """
        assignment = self.assignment_for(subnet)
        classes = {rc for _vc, rc in assignment.vc_to_routing_class}
        if len(classes) != 1:
            raise MultiPlaneVCError(
                f"secondary subnet {subnet} declares routing classes "
                f"{sorted(classes)}; a declared plane carries exactly one")
        return next(iter(classes))

    def content_hash(self) -> str:
        body = (f"{_HASH_TYPE_TAG}/v{self.schema_version}\0"
                + canonical_json(self.identity_dict()))
        return hashlib.sha256(body.encode()).hexdigest()

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "primary": self.primary.vc_assignment_hash(),
            "secondary": [
                [subnet, assignment.vc_assignment_hash()]
                for subnet, assignment in self.secondary
            ],
            "traffic_class_to_subnet": [
                [cls, subnet] for cls, subnet in self.traffic_class_to_subnet
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity_dict(),
            "artifact_hash": self.content_hash(),
            "primary_assignment": self.primary.to_dict(),
            "secondary_assignments": [
                [subnet, assignment.to_dict()]
                for subnet, assignment in self.secondary
            ],
        }


def plane_c_vc_assignment(
        control_plane: ControlPlaneArtifact,
        classes: tuple[str, ...]) -> VCAssignmentArtifact:
    """The declared VC structure of Plane C: REQ/RSP/SNP on plain XY.

    Plane C's routing authority is the control-plane artifact itself (there
    is no deterministic route table for a plain XY mesh), so its content
    hash stands in for ``resolved_route_hash``.
    """
    if not isinstance(control_plane, ControlPlaneArtifact):
        raise MultiPlaneVCError(
            f"control_plane must be a ControlPlaneArtifact, got "
            f"{type(control_plane).__name__}")
    bound = tuple(sorted(set(classes)))
    if not bound:
        raise MultiPlaneVCError(
            "Plane C was declared but no traffic class rides it")
    vc_count = len(control_plane.vcs)
    return VCAssignmentArtifact(
        resolved_route_hash=control_plane.content_hash,
        vc_count=vc_count,
        vc_ids=tuple(range(vc_count)),
        traffic_class_to_vcs=tuple(
            (cls, tuple(range(vc_count))) for cls in bound),
        vc_to_routing_class=tuple(
            (vc, PLANE_C_ROUTING_CLASS) for vc in range(vc_count)),
        allowed_transitions=tuple((vc, vc) for vc in range(vc_count)),
        escape_vcs=(),
        derivation=(
            f"Plane C subnet {control_plane.subnet} (control-plane "
            f"{control_plane.content_hash[:18]}…): {list(control_plane.vcs)} "
            f"on {control_plane.routing}; declared structure only"),
    )


def materialize_multi_plane_vc(
        *,
        primary: VCAssignmentArtifact,
        topology: Any,
) -> MultiPlaneVCAssignment | None:
    """Bind classes to subnets when the topology declares Plane C, else None.

    Plane D is subnet 0 and Plane C is subnet 1. Classes are dealt round
    robin in sorted order, so the first class stays on the data plane; this
    is the SAME rule the BookSim projection renders as ``class_subnet``,
    now derived once here instead of separately at the renderer.
    """
    _require_assignment(primary, "primary")
    planes = getattr(topology, "planes", ())
    if "c" not in planes:
        return None
    try:
        control_plane = materialize_control_plane(topology)
    except ControlPlaneError as exc:
        raise MultiPlaneVCError(str(exc)) from exc
    classes = tuple(cls for cls, _vcs in primary.traffic_class_to_vcs)
    if len(classes) < 2:
        # A single-class multi-plane fabric is refused by the projection
        # qualifier ("needs traffic on BOTH planes"), not here: compilation
        # stays structural and the renderer owns that refusal.
        return None
    subnet_count = 1 + 1  # primary + the single declared Plane C subnet
    binding = tuple(
        (cls, idx % subnet_count) for idx, cls in enumerate(classes))
    on_c = tuple(cls for cls, subnet in binding if subnet == control_plane.subnet)
    on_d = tuple(cls for cls, subnet in binding if subnet == 0)
    if not on_c or not on_d:
        raise MultiPlaneVCError(
            "a multi-plane fabric must place at least one class on each "
            f"plane; class->subnet binding is {list(binding)}")
    secondary = ((control_plane.subnet,
                  plane_c_vc_assignment(control_plane, on_c)),)
    return MultiPlaneVCAssignment(
        primary=primary, secondary=secondary, traffic_class_to_subnet=binding)


__all__ = [
    "MULTI_PLANE_VC_SCHEMA_VERSION",
    "MultiPlaneVCError",
    "MultiPlaneVCAssignment",
    "materialize_multi_plane_vc",
    "plane_c_vc_assignment",
]
