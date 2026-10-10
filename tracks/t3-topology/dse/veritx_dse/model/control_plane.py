"""The SROTA SR-C control plane (Plane C) as a canonical artifact.

Plane C is a SECOND subnet, not a recolouring of Plane D. It is a
conventional VC-buffered router on a plain mesh — no express layer, no side
buffer, no islands — carrying REQ/RSP/SNP on three independent VCs and using
plain XY (``srota.cpp`` ``_ComputeSizePlaneC`` / ``srota_planec_xy``).

The artifact records exactly the structure the simulator builds, derived
from the Plane D fabric so the two planes cannot disagree on grid size or
concentration (both planes serve the same tiles, so the node count must
match across subnets). It does NOT simulate the control plane's traffic or
claim its timing: it is the declared second plane, structurally checked.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.core.errors import SemanticError

CONTROL_PLANE_SCHEMA_VERSION = 1

#: VC-002 3.2: REQ / RSP / SNP on three independent VCs.
PLANEC_VCS: tuple[str, ...] = ("REQ", "RSP", "SNP")

#: The declared routing realization of Plane C (plain XY). It is its own
#: routing class because Plane C is a SEPARATE subnet: the Plane D route
#: artifact does not describe it, and the two must never be conflated.
PLANE_C_ROUTING_CLASS = "SROTA_PLANEC_XY"


class ControlPlaneError(ValueError, SemanticError):
    """The declared control plane is malformed or inconsistent."""


@dataclass(frozen=True)
class ControlPlaneArtifact:
    """The SR-C control plane: a fixed mesh subnet with its own VC structure."""

    k: int
    c: int
    subnet: int = 1
    vcs: tuple[str, ...] = PLANEC_VCS
    routing: str = "xy"
    schema_version: int = CONTROL_PLANE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or \
                self.schema_version != CONTROL_PLANE_SCHEMA_VERSION:
            raise ControlPlaneError(
                f"unsupported control-plane schema_version "
                f"{self.schema_version!r}")
        for name, value, minimum in (("k", self.k, 2), ("c", self.c, 1),
                                     ("subnet", self.subnet, 1)):
            if type(value) is not int or value < minimum:
                raise ControlPlaneError(
                    f"{name} must be an exact int >= {minimum}")
        if tuple(self.vcs) != PLANEC_VCS:
            raise ControlPlaneError(
                "Plane C carries exactly REQ/RSP/SNP on three independent "
                f"VCs; got {list(self.vcs)}")
        if self.routing != "xy":
            raise ControlPlaneError(
                "Plane C is plain XY (srota_planec_xy); got "
                f"{self.routing!r}")

    @property
    def router_count(self) -> int:
        return self.k * self.k

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/ControlPlane",
            "schema_version": self.schema_version,
            "k": self.k, "c": self.c, "subnet": self.subnet,
            "vcs": list(self.vcs), "routing": self.routing,
        }

    @property
    def content_hash(self) -> str:
        from veritx_dse.core.artifact import content_id
        return content_id("srota/ControlPlane/v1", self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_dict(), "content_hash": self.content_hash}

    def validate_against(self, topology: Any) -> None:
        """The two planes must serve the same grid and concentration."""
        from veritx_dse.model.topology_artifact import TopologyArtifact
        if not isinstance(topology, TopologyArtifact):
            raise ControlPlaneError(
                f"topology must be a TopologyArtifact, got "
                f"{type(topology).__name__}")
        if "c" not in topology.planes:
            raise ControlPlaneError(
                "the topology does not declare Plane C, so there is no "
                "second plane for this artifact to describe")
        seats = {r.seat_capacity for r in topology.routers}
        if len(seats) != 1:
            raise ControlPlaneError(
                "Plane C needs a uniform concentration to match Plane D; "
                f"got {sorted(seats)}")
        n = topology.router_count
        k = int(n ** 0.5)
        if k * k != n:
            raise ControlPlaneError(
                f"Plane C is a square mesh; Plane D has {n} routers")
        if self.k != k or self.c != next(iter(seats)):
            raise ControlPlaneError(
                f"Plane C declares k={self.k}, c={self.c} but Plane D is "
                f"k={k}, c={next(iter(seats))}; both planes serve the same "
                "tiles, so their node counts must match")


def materialize_control_plane(topology: Any) -> ControlPlaneArtifact:
    """Derive Plane C's fixed structure from the Plane D fabric."""
    from veritx_dse.model.topology_artifact import TopologyArtifact
    if not isinstance(topology, TopologyArtifact):
        raise ControlPlaneError(
            f"topology must be a TopologyArtifact, got "
            f"{type(topology).__name__}")
    if "c" not in topology.planes:
        raise ControlPlaneError(
            "materialize_control_plane needs a topology that declares "
            f"Plane C; declared planes are {list(topology.planes)}")
    n = topology.router_count
    k = int(n ** 0.5)
    if k * k != n:
        raise ControlPlaneError(
            f"Plane C is a square mesh; Plane D has {n} routers")
    seats = {r.seat_capacity for r in topology.routers}
    if len(seats) != 1:
        raise ControlPlaneError(
            f"Plane C needs a uniform concentration; got {sorted(seats)}")
    artifact = ControlPlaneArtifact(k=k, c=next(iter(seats)))
    artifact.validate_against(topology)
    return artifact


__all__ = [
    "CONTROL_PLANE_SCHEMA_VERSION",
    "PLANE_C_ROUTING_CLASS",
    "PLANEC_VCS",
    "ControlPlaneError",
    "ControlPlaneArtifact",
    "materialize_control_plane",
]
