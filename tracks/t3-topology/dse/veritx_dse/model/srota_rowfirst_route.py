"""srota_rowfirst_route — SROTA Plane D, row-first (O1TURN-XY) hop rule.

The second fabric to be qualified against the shared-resource representation,
and the one that shows why one abstraction has to cover both.

SROTA's MECS wires are NOT GEC's. Both are multidrop, and both are one wire
per (dimension, group) — but:

  * SROTA's wires are DIRECTIONAL: ``XNEG`` and ``XPOS`` are separate wires,
    so the taps of a wire from column px are ``px-1 .. 0`` (westbound) or
    ``px+1 .. k-1`` (eastbound), and the tap index is the DISTANCE minus one.
  * GEC's wires are NOT directional: one wire per dimension per group, whose
    taps are every other column ordered ascending with self skipped, and the
    tap index is the position in that peer list.

Deriving the tap index the same way for both puts the packet off at the
wrong router, so the differential is per fabric and neither may be assumed.

The rule below is transcribed from ``networks/srota.cpp`` (``SrotaRouteCompute``
via ``srota_o1turn``) at ``path_en = row-first only``, the single shape
``tracks/t3-topology/configs/srota16_xy.cfg`` calls the shippable Plane D:

    router == dest_router:            local terminal, port = dest % c
    px != dx:  XNEG if dx < px else XPOS
               drop = |dx - px| - 1,  next = (dx, py)
    else:      YNEG if dy < py else YPOS
               drop = |dy - py| - 1,  next = (px, dy)

Port numbering is the header's contract: [0,c) local, then the dimension
ports in the fixed order XNEG, XPOS, YNEG, YPOS counting only the directions
present at that router. Presence depends only on position, so the map has the
same shape whether a dimension runs express or plain — only the wiring behind
the port changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.core.errors import SemanticError

class SrotaRowFirstRouteError(ValueError, SemanticError):
    """The declared SROTA shape cannot describe a hop — fail closed."""

def _as_int(name: str, value: Any, *, minimum: int) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise SrotaRowFirstRouteError(
            f"{name} must be an exact int, got {value!r}")
    if value < minimum:
        raise SrotaRowFirstRouteError(
            f"{name} must be >= {minimum}, got {value}")
    return value

#: The source's fixed dimension-port order (srota.hpp, "PORT MAP").
_DIRECTIONS = ("XNEG", "XPOS", "YNEG", "YPOS")

@dataclass(frozen=True)
class SrotaRowFirstParams:
    """Plane D shape for the single-shape row-first configuration.

    ``mecs_row``/``mecs_col`` change only what is wired to a port, not the
    port map, so presence is derived from position alone. ``num_vcs`` is 1 in
    the shippable configuration; a larger count is allowed only with an
    explicit whole-fabric partition, which this module does not invent.
    """

    k: int
    c: int
    num_vcs: int = 1
    mecs_row: bool = True
    mecs_col: bool = True

    def __post_init__(self) -> None:
        _as_int("k", self.k, minimum=2)
        _as_int("c", self.c, minimum=1)
        _as_int("num_vcs", self.num_vcs, minimum=1)
        if not self.mecs_row and not self.mecs_col:
            raise SrotaRowFirstRouteError(
                "at least one dimension must carry the express layer: with "
                "both off this is a plain concentrated mesh and belongs to "
                "that family, not to SROTA")

    @property
    def router_count(self) -> int:
        return self.k * self.k

    @property
    def node_count(self) -> int:
        return self.k * self.k * self.c

def _present_directions(px: int, py: int, k: int) -> tuple[str, ...]:
    """The ports of router (px, py), in the source's fixed order."""
    present: list[str] = []
    if px > 0:
        present.append("XNEG")
    if px < k - 1:
        present.append("XPOS")
    if py > 0:
        present.append("YNEG")
    if py < k - 1:
        present.append("YPOS")
    return tuple(present)

@dataclass(frozen=True)
class SrotaRowFirstHop:
    """One executed first hop of the shippable Plane D."""

    src_router: int
    dest_node: int
    dest_router: int
    port: int
    drop: int
    vc_start: int
    vc_end: int
    next_router: int
    direction: str          # XNEG/XPOS/YNEG/YPOS, or "local"

    @property
    def is_shared(self) -> bool:
        return self.drop >= 0

def derive_srota_rowfirst_hop(params: SrotaRowFirstParams, *,
                              src_router: int,
                              dest_node: int) -> SrotaRowFirstHop:
    """The deterministic first hop from ``src_router`` toward ``dest_node``."""
    return _derive_srota_shape_hop(params, src_router=src_router,
                                   dest_node=dest_node, column_first=False)


def _derive_srota_shape_hop(params: SrotaRowFirstParams, *,
                            src_router: int, dest_node: int,
                            column_first: bool) -> SrotaRowFirstHop:
    """One shape's first hop. ``column_first`` swaps the dimension order."""
    if not 0 <= src_router < params.router_count:
        raise SrotaRowFirstRouteError(
            f"router {src_router} is outside the {params.router_count} "
            "routers this fabric has")
    if not 0 <= dest_node < params.node_count:
        raise SrotaRowFirstRouteError(
            f"destination node {dest_node} is outside the "
            f"{params.node_count} terminals this fabric has")
    dest_router = dest_node // params.c

    px, py = src_router % params.k, src_router // params.k
    if src_router == dest_router:
        return SrotaRowFirstHop(
            src_router=src_router, dest_node=dest_node,
            dest_router=dest_router, port=dest_node % params.c, drop=-1,
            vc_start=0, vc_end=params.num_vcs - 1, next_router=src_router,
            direction="local")

    dx, dy = dest_router % params.k, dest_router // params.k
    present = _present_directions(px, py, params.k)
    # Row-first resolves the COLUMN coordinate first, so it takes X whenever
    # X still differs. Column-first resolves the ROW first, so it takes X only
    # once Y already matches. Both are total: when one coordinate matches, the
    # other must still differ (the destination is not the source).
    use_x = (px != dx) if not column_first else (py == dy)
    if use_x:
        # Row first: O1TURN-XY resolves the column coordinate before the row.
        direction = "XNEG" if dx < px else "XPOS"
        drop = abs(dx - px) - 1
        next_router = py * params.k + dx
        if not params.mecs_row:
            # Express off in this dimension: the port is an ordinary
            # nearest-neighbour link with no tap, so the express tap rule
            # above does not describe it. Refuse rather than stamp a tap on
            # a wire that has none.
            raise SrotaRowFirstRouteError(
                "the row dimension carries no express layer (mecs_row=False), "
                "so this hop is a plain nearest-neighbour step and the "
                "express tap rule does not describe it")
    else:
        direction = "YNEG" if dy < py else "YPOS"
        drop = abs(dy - py) - 1
        next_router = dy * params.k + px
        if not params.mecs_col:
            raise SrotaRowFirstRouteError(
                "the column dimension carries no express layer "
                "(mecs_col=False), so this hop is a plain nearest-neighbour "
                "step and the express tap rule does not describe it")

    if direction not in present:
        # Unreachable for a conformant shape; a guard so a future port-order
        # change fails loudly instead of indexing a port that does not exist.
        raise SrotaRowFirstRouteError(          # pragma: no cover - guarded
            f"router {src_router} has no {direction} port "
            f"(present: {present})")
    port = params.c + present.index(direction)
    return SrotaRowFirstHop(
        src_router=src_router, dest_node=dest_node, dest_router=dest_router,
        port=port, drop=drop, vc_start=0, vc_end=params.num_vcs - 1,
        next_router=next_router, direction=direction)

def derive_srota_columnfirst_table(params: SrotaRowFirstParams
                                   ) -> tuple[SrotaRowFirstHop, ...]:
    """The COLUMN-first shape: O1TURN-XY resolving the row before the column.

    The same fabric, the same wires, the same tap rule — only the ORDER of
    the two dimensions changes. That is precisely why the two shapes cannot
    share a VC: row-first contributes row->column dependencies and
    column-first contributes column->row, and their union is the RT-R7
    cycle unless the shapes are separated.
    """
    return _derive_srota_shape_table(params, column_first=True)


def derive_srota_rowfirst_table(params: SrotaRowFirstParams
                                ) -> tuple[SrotaRowFirstHop, ...]:
    """Every (router, terminal) first hop, in the dump's own iteration order."""
    return _derive_srota_shape_table(params, column_first=False)


def _derive_srota_shape_table(params: SrotaRowFirstParams, *,
                              column_first: bool
                              ) -> tuple[SrotaRowFirstHop, ...]:
    return tuple(
        _derive_srota_shape_hop(params, src_router=r, dest_node=n,
                                column_first=column_first)
        for r in range(params.router_count)
        for n in range(params.node_count)
    )

#: The shippable Plane D shape, from configs/srota16_xy.cfg: k=4, c=1,
#: D+T planes, MECS on both dimensions, row-first only, no VC separation.
SHIPPABLE_SROTA_ROW_FIRST = SrotaRowFirstParams(k=4, c=1, num_vcs=1)

__all__ = [
    "SrotaRowFirstRouteError", "SrotaRowFirstParams", "SrotaRowFirstHop",
    "derive_srota_rowfirst_hop", "derive_srota_rowfirst_table",
    "derive_srota_columnfirst_table",
    "SHIPPABLE_SROTA_ROW_FIRST",
]
