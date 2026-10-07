"""gec_mecs_route — the canonical GEC-MECS hop rule, derived independently.

Why this file exists
--------------------
GEC's MECS mode is the first shared-wire fabric that already has a canonical
intent, so it is the right thing to qualify a new shared-resource route
representation against. To qualify it, the compiler must derive the hop rule
ITSELF and then be compared with what the simulator actually executes — a
re-implementation checked against the original is the only version of this
that is worth anything.

The rule below is transcribed from ``third_party/booksim2/src/networks/gec.cpp``
(``dor_gec``) and is stated in source terms, not in terms of the code that
will consume it:

    router != dest_router:
      if px != dx:  peer_idx = (dx < px) ? dx : dx - 1        (row hop)
                    out_port = c + peer_idx / d
      else:         peer_idx = (dy < py) ? dy : dy - 1        (column hop)
                    out_port = c + o + peer_idx / d
      drop = peer_idx % d
      vc range = [drop * (num_vcs/d), drop * (num_vcs/d) + num_vcs/d - 1]
    router == dest_router:
      out_port = dest % c          (local terminal)
      drop     = -1                (not a shared port)
      vc range = [0, num_vcs - 1]

Three properties of that rule are the reason a plain channel id cannot
describe it, and they are exactly what ``RouteDecision`` was introduced for:

  * the WIRE is ``out_port`` (one per router, per dimension, per group);
  * the EXIT is ``drop`` — two packets on the same wire to different
    destinations are the same resource and different taps;
  * the VCs a hop may use are NOT the whole VC set — they are the slice the
    tap owns, which is what stops the VC allocator conflating two taps.

Nothing here is wired into the compiler yet. It exists so the differential in
``tests/test_gec_mecs_differential.py`` can compare an independent derivation
against the simulator's own executed realization, before any of it is trusted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.core.errors import SemanticError

class GecMecsRouteError(ValueError, SemanticError):
    """The declared GEC-MECS shape cannot describe a hop — fail closed."""

def _as_int(name: str, value: Any, *, minimum: int) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise GecMecsRouteError(f"{name} must be an exact int, got {value!r}")
    if value < minimum:
        raise GecMecsRouteError(f"{name} must be >= {minimum}, got {value}")
    return value

@dataclass(frozen=True)
class GecMecsParams:
    """The shape of a GEC-MECS fabric, in the source's own parameter names.

    ``mesh`` and ``hybrid`` are deliberately absent: this rule is the
    deterministic ``dor_gec`` MECS case only. Mesh-mode GEC lowers to the
    canonical mesh, and hybrid chooses at runtime, so neither is a
    deterministic decision table and neither belongs here.
    """

    k: int
    c: int
    o: int
    d: int
    num_vcs: int

    def __post_init__(self) -> None:
        _as_int("k", self.k, minimum=2)
        _as_int("c", self.c, minimum=1)
        _as_int("o", self.o, minimum=1)
        _as_int("d", self.d, minimum=2)
        _as_int("num_vcs", self.num_vcs, minimum=1)
        if self.o * self.d != self.k - 1:
            raise GecMecsRouteError(
                f"the source law o*d == k-1 is violated: o({self.o}) x "
                f"d({self.d}) = {self.o * self.d} != k-1 ({self.k - 1})")
        if self.num_vcs < self.d:
            raise GecMecsRouteError(
                f"num_vcs({self.num_vcs}) < d({self.d}): every tap needs at "
                "least one VC of its own, or two taps share a VC and the "
                "partition the proof relies on is not real")
        if self.num_vcs % self.d:
            raise GecMecsRouteError(
                f"num_vcs({self.num_vcs}) must divide by d({self.d}): the "
                "source floors the per-tap slice, and a floored slice leaves "
                "VCs no tap owns — refuse rather than silently strand them")

    @property
    def router_count(self) -> int:
        return self.k * self.k

    @property
    def node_count(self) -> int:
        return self.k * self.k * self.c

    @property
    def vcs_per_tap(self) -> int:
        return self.num_vcs // self.d

@dataclass(frozen=True)
class GecMecsHop:
    """One executed first-hop realization, in the source's terms.

    ``next_router`` is carried because it is what the tap resolves TO: the
    wire is the same for every tap, so nothing about ``port`` determines
    where the packet lands.
    """

    src_router: int
    dest_node: int
    dest_router: int
    port: int
    drop: int
    vc_start: int
    vc_end: int
    next_router: int
    dimension: str          # "x", "y", or "local"
    group: int              # express group index, -1 when local

    @property
    def is_shared(self) -> bool:
        return self.drop >= 0

    @property
    def vc_slice(self) -> tuple[int, int]:
        return (self.vc_start, self.vc_end)

def _tap_vector(params: GecMecsParams, router: int, axis: str
                ) -> tuple[int, ...]:
    """The routers one express wire from ``router`` taps, in registration order.

    GEC's express wires are NOT directional: ``pout = c + 2*o`` (one wire
    per dimension per group), not ``c + 4*o``. A wire in dimension x carries
    every OTHER column, ordered by ``GEC::_PeerIndex`` — ascending column
    with self skipped (``gec.cpp``:508). That ordering IS the tap contract:
    the builder registers taps in it and the routing function stamps
    ``Flit::drop`` with an index into it, so deriving it any other way (e.g.
    as separate +x/-x wires, which is what SROTA does) puts the tap on the
    wrong router.
    """
    px, py = router % params.k, router // params.k
    if axis == "x":
        return tuple(py * params.k + q for q in range(params.k) if q != px)
    return tuple(q * params.k + px for q in range(params.k) if q != py)

def derive_gec_mecs_hop(params: GecMecsParams, *, src_router: int,
                        dest_node: int) -> GecMecsHop:
    """The deterministic first hop a packet at ``src_router`` takes to
    ``dest_node``, transcribed from ``dor_gec``."""
    if not 0 <= src_router < params.router_count:
        raise GecMecsRouteError(
            f"router {src_router} is outside the {params.router_count} "
            "routers this fabric has")
    if not 0 <= dest_node < params.node_count:
        raise GecMecsRouteError(
            f"destination node {dest_node} is outside the {params.node_count} "
            "terminals this fabric has")
    dest_router = dest_node // params.c
    if src_router == dest_router:
        return GecMecsHop(
            src_router=src_router, dest_node=dest_node,
            dest_router=dest_router, port=dest_node % params.c, drop=-1,
            vc_start=0, vc_end=params.num_vcs - 1, next_router=src_router,
            dimension="local", group=-1)

    px, py = src_router % params.k, src_router // params.k
    dx, dy = dest_router % params.k, dest_router // params.k
    if px != dx:
        dimension = "x"
        peer_idx = dx if dx < px else dx - 1
        base = params.c
    else:
        dimension = "y"
        peer_idx = dy if dy < py else dy - 1
        base = params.c + params.o

    group, drop = divmod(peer_idx, params.d)
    port = base + group
    per_tap = params.vcs_per_tap
    vc_start = drop * per_tap
    vc_end = vc_start + per_tap - 1

    taps = _tap_vector(params, src_router, dimension)
    if drop >= len(taps):
        # Cannot happen for a conformant shape; a guard so a future change to
        # the tap order fails loudly instead of indexing past the wire.
        raise GecMecsRouteError(          # pragma: no cover - defensive
            f"router {src_router} {dimension}-wire has {len(taps)} taps but "
            f"the rule named tap {drop}")
    return GecMecsHop(
        src_router=src_router, dest_node=dest_node, dest_router=dest_router,
        port=port, drop=drop, vc_start=vc_start, vc_end=vc_end,
        next_router=taps[drop], dimension=dimension, group=group)

def derive_gec_mecs_table(params: GecMecsParams) -> tuple[GecMecsHop, ...]:
    """Every (router, terminal) first hop, in the dump's own iteration order."""
    return tuple(
        derive_gec_mecs_hop(params, src_router=r, dest_node=n)
        for r in range(params.router_count)
        for n in range(params.node_count)
    )

__all__ = [
    "GecMecsRouteError", "GecMecsParams", "GecMecsHop",
    "derive_gec_mecs_hop", "derive_gec_mecs_table",
]
