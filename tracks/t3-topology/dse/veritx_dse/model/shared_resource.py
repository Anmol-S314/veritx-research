"""shared_resource — naming a routing resource that may be a SHARED wire.

Why this module exists
----------------------
A point-to-point fabric has one kind of routing resource: a directed channel
with an integer id. A multidrop fabric (SROTA's MECS express layer, GEC's
MECS) has a second: one driver feeding many contending taps over a single
wire.

The previous representation could not name that second thing. A route was a
single integer ``channel_id``, which silently asserts "the resource you take
IS the resource you leave by". On a shared wire that assertion is false: the
wire is fixed, but *where you get off* depends on the packet (the tap), and
two packets to different taps contend for the same wire slot.

So a route step is modeled as a DECISION, not an index:

    resource      which wire do I take
    tap           where do I get off it (None for a private channel)
    next_router   the router that decision lands me at
    vc_partition  which VC partition this hop requires

Three consequences that are the whole point of splitting it this way:

1. ``next_router`` must be carried, not derived. For a private channel the
   destination is the channel's ``dst_router``; for a shared wire the wire is
   the same for every tap, so nothing about the resource determines where the
   packet lands. Deriving it would be a wrong answer that looks right.

2. ``tap`` is not decoration. It is what makes the shared wire's contention
   addressable, and it is what the VC eligibility rule keys on.

3. ``vc_partition`` is an opaque small integer here. This module deliberately
   does NOT know what a partition means — rank, shape, tap, phase, or nothing
   at all. Resolving a partition to concrete VCs is the VC layer's job, and
   the dependency proof works over the CONCRETE VCs that resolution yields.
   That is what keeps one abstraction covering SROTA, GEC multicast-drop and
   GEC hybrid without teaching this file about any of them.

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from veritx_dse.core.errors import SemanticError

class SharedResourceError(ValueError, SemanticError):
    """A resource reference or route decision is malformed — fail closed."""

class ResourceKind(str, Enum):
    """The closed set of routing resources.

    ``CHANNEL`` is one driver, one receiver (a private directed channel).
    ``SHARED_LINK`` is one driver, many receivers (a multidrop wire). The two
    are never interchangeable: a private channel has exactly one destination
    and therefore no tap, while a shared wire has many and therefore must
    name one.
    """

    CHANNEL = "CHANNEL"
    SHARED_LINK = "SHARED_LINK"

def _as_int(name: str, value: Any, *, minimum: int = 0) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise SharedResourceError(
            f"{name} must be an exact int, got {value!r}")
    if value < minimum:
        raise SharedResourceError(f"{name} must be >= {minimum}, got {value}")
    return value

@dataclass(frozen=True, order=True)
class ResourceRef:
    """Which routing resource a hop takes, named by kind AND id.

    The kind is part of the identity, not a hint: ``CHANNEL:7`` and
    ``SHARED_LINK:7`` are different resources that must never collide in a
    dependency graph. Folding the kind into one integer id space would let a
    shared wire alias a private channel and hide a real dependency.
    """

    kind: ResourceKind
    resource_id: int

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ResourceKind):
            try:
                object.__setattr__(self, "kind", ResourceKind(self.kind))
            except ValueError:
                raise SharedResourceError(
                    f"resource kind must be one of "
                    f"{[k.value for k in ResourceKind]}, got "
                    f"{self.kind!r}") from None
        _as_int("resource_id", self.resource_id)

    @property
    def is_shared(self) -> bool:
        return self.kind is ResourceKind.SHARED_LINK

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "resource_id": self.resource_id}

    @classmethod
    def from_dict(cls, d: Any) -> ResourceRef:
        if not isinstance(d, dict):
            raise SharedResourceError(
                f"resource must be an object, got {type(d).__name__}")
        unknown = set(d) - {"kind", "resource_id"}
        if unknown:
            raise SharedResourceError(
                f"resource has unknown fields {sorted(unknown)}")
        if "kind" not in d or "resource_id" not in d:
            raise SharedResourceError(
                "resource needs both 'kind' and 'resource_id'")
        return cls(kind=ResourceKind(d["kind"]),
                   resource_id=d["resource_id"])

    def __str__(self) -> str:                      # pragma: no cover - display
        return f"{self.kind.value}:{self.resource_id}"

@dataclass(frozen=True)
class RouteDecision:
    """One deterministic routing step: resource, tap, landing router, partition.

    ``next_router`` is REQUIRED (not derived from the resource) because a
    shared wire does not determine where a packet leaves it. This is the
    field whose absence made shared-resource routing inexpressible.
    """

    resource: ResourceRef
    next_router: int
    vc_partition: int = 0
    tap: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.resource, ResourceRef):
            raise SharedResourceError(
                f"resource must be a ResourceRef, got "
                f"{type(self.resource).__name__}")
        _as_int("next_router", self.next_router)
        _as_int("vc_partition", self.vc_partition)
        if self.resource.is_shared:
            if self.tap is None:
                raise SharedResourceError(
                    f"{self.resource} is a shared wire: a decision that takes "
                    "it MUST name the tap it exits by — without the tap two "
                    "packets to different destinations are indistinguishable")
            _as_int("tap", self.tap)
        elif self.tap is not None:
            raise SharedResourceError(
                f"{self.resource} is a private channel with exactly one "
                f"destination, so it cannot name tap {self.tap}: a tap here "
                "would describe a resource that does not exist")

    def to_dict(self) -> dict[str, Any]:
        return {"resource": self.resource.to_dict(),
                "next_router": self.next_router,
                "vc_partition": self.vc_partition,
                "tap": self.tap}

    @classmethod
    def from_dict(cls, d: Any) -> RouteDecision:
        if not isinstance(d, dict):
            raise SharedResourceError(
                f"route decision must be an object, got {type(d).__name__}")
        unknown = set(d) - {"resource", "next_router", "vc_partition", "tap"}
        if unknown:
            raise SharedResourceError(
                f"route decision has unknown fields {sorted(unknown)}")
        if "resource" not in d or "next_router" not in d:
            raise SharedResourceError(
                "route decision needs both 'resource' and 'next_router'")
        return cls(resource=ResourceRef.from_dict(d["resource"]),
                   next_router=d["next_router"],
                   vc_partition=d.get("vc_partition", 0),
                   tap=d.get("tap"))

#: A concrete resource+VC pair. The dependency graph's NODE type.
#:
#: Deliberately (resource, vc) and never (resource, partition): a partition
#: is a SET of VCs, and collapsing a set into one node can merge two
#: dependencies that VC separation exists specifically to keep apart. The
#: proof is only ever about concrete resources.
ResourceVC = tuple[ResourceRef, int]

__all__ = [
    "SharedResourceError", "ResourceKind", "ResourceRef", "RouteDecision",
    "ResourceVC",
]
