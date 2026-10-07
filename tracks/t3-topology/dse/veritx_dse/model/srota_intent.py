"""model/srota_intent — first-class Srota fabric intent (v4).

Architectural intent ONLY for the Srota NoC as executed by the vendored
BookSim model (third_party/booksim2 SROTA.md, rev 0.3):

- Plane D: k x k concentrated mesh (concentration c) + MECS express layer
- O1TURN-XY routing with row / column / valiant path shapes
- VC-002 router policy (spec-literal shared VCs through rank-split sets)
- QoS island columns with column-first island routing
- Plane C: fixed XY control mesh (REQ/RSP/SNP); Plane T: bounded-staleness
  telemetry vectors

What this module REFUSES (debug-only simulator knobs, never design
intent): congestion thresholds, epoch lengths, VC counts and buffer
sizes, allocators, pipeline delays, speedups, seeds, sample periods,
and any other BookSim configuration scalar. ``from_dict`` rejects unknown
fields, so smuggling one fails closed instead of silently riding along.

Cross-field laws come from the sources, not from taste:

- islands require the full express layer (row AND column MECS): the
  simulator refuses an island map without both (srota.cpp), because a
  route to an island column would otherwise traverse arbitrary routers;
- Plane D is mandatory: a Srota fabric without its data plane is not a
  fabric;
- concentration >= 2: Plane D is a *concentrated* mesh by definition; a
  c=1 design is a plain mesh and must declare ``mesh`` instead;
- side-buffer enable and watermark are jointly required: neither can be
  defaulted without silently inventing a different router.

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar

from veritx_dse.core.errors import SemanticError
from veritx_dse.model.topology_intent_base import TopologyIntent

class SrotaIntentError(ValueError, SemanticError):
    """The declared Srota intent cannot represent a physical structure."""


class SrotaPathShape(Enum):
    """Allowed O1TURN-XY path shapes (ROUTE-001 section 14.1)."""

    ROW = "row"
    COLUMN = "column"
    VALIANT = "valiant"


class SrotaVCPolicy(Enum):
    """VC-002 router policy variants (srota.hpp design note section 3)."""

    NONE = "none"
    SHAPE = "shape"
    RANK = "rank"
    ONESHAPE = "oneshape"


class SrotaPlane(Enum):
    """Planes present in the fabric (TOPO-003 section 13.2)."""

    DATA = "d"
    CONTROL = "c"
    TELEMETRY = "t"


def _as_int(name: str, value: Any, *, minimum: int) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise SrotaIntentError(f"{name} must be an int, got {value!r}")
    if value < minimum:
        raise SrotaIntentError(
            f"{name} must be >= {minimum}, got {value}")
    return value


def _as_bool(name: str, value: Any) -> bool:
    if type(value) is not bool:
        raise SrotaIntentError(f"{name} must be a bool, got {value!r}")
    return value


def _coerce_enum(name: str, value: Any, enum: Any) -> Any:
    if isinstance(value, enum):
        return value
    if isinstance(value, str):
        try:
            return enum(value)
        except ValueError:
            pass
    raise SrotaIntentError(
        f"{name} must be one of "
        f"{sorted(e.value for e in enum)}, got {value!r}")


def _coerce_enum_set(name: str, value: Any, enum: Any) -> Any:
    if isinstance(value, str) or not isinstance(value, (set, frozenset,
                                                        list, tuple)):
        raise SrotaIntentError(
            f"{name} must be a collection of "
            f"{sorted(e.value for e in enum)}, got {value!r}")
    return frozenset(_coerce_enum(name, v, enum) for v in value)


@dataclass(frozen=True)
class SrotaIntent(TopologyIntent):
    """An authorable Srota fabric: concentrated mesh + MECS + islands.

    ``side_length`` is the number of ROUTERS per side (k; validated 4..32
    in the reference model, enforced minimum 2 below which no express span
    exists). ``concentration`` is endpoints per router. The island map is
    carried as a sorted column tuple — the config bitmap in canonical form.
    """

    kind: ClassVar[str] = "srota"

    side_length: int
    concentration: int
    mecs_row: bool
    mecs_col: bool
    drop_latency: int
    planes: frozenset[SrotaPlane]
    island_columns: tuple[int, ...]
    path_shapes: frozenset[SrotaPathShape]
    vc_policy: SrotaVCPolicy
    sidebuf_enable: bool
    sidebuf_watermark: int | None
    tel_period: int
    tel_latency: int

    def __post_init__(self):
        _as_int("side_length", self.side_length, minimum=2)
        _as_int("concentration", self.concentration, minimum=2)
        object.__setattr__(self, "mecs_row",
                           _as_bool("mecs_row", self.mecs_row))
        object.__setattr__(self, "mecs_col",
                           _as_bool("mecs_col", self.mecs_col))
        if self.drop_latency not in (1, 2):
            raise SrotaIntentError(
                "drop_latency must be 1 or 2 "
                f"(TOPO_DROP_LATENCY), got {self.drop_latency!r}")
        planes = _coerce_enum_set("planes", self.planes, SrotaPlane)
        object.__setattr__(self, "planes", planes)
        if SrotaPlane.DATA not in planes:
            raise SrotaIntentError(
                "planes must include the data plane ('d'): a Srota fabric "
                "without Plane D is not a fabric")
        if not isinstance(self.island_columns, tuple):
            raise SrotaIntentError(
                "island_columns must be a tuple of column indices, got "
                f"{self.island_columns!r}")
        seen: set[int] = set()
        for col in self.island_columns:
            _as_int("island_columns[]", col, minimum=0)
            if col >= self.side_length:
                raise SrotaIntentError(
                    f"island column {col} is outside the k={self.side_length} "
                    "fabric")
            if col in seen:
                raise SrotaIntentError(
                    f"island column {col} is declared twice")
            seen.add(col)
        object.__setattr__(self, "island_columns",
                           tuple(sorted(self.island_columns)))
        shapes = _coerce_enum_set("path_shapes", self.path_shapes,
                                  SrotaPathShape)
        if not shapes:
            raise SrotaIntentError(
                "path_shapes must enable at least one of "
                "row/column/valiant")
        object.__setattr__(self, "path_shapes", shapes)
        object.__setattr__(self, "vc_policy",
                           _coerce_enum("vc_policy", self.vc_policy,
                                        SrotaVCPolicy))
        object.__setattr__(self, "sidebuf_enable",
                           _as_bool("sidebuf_enable", self.sidebuf_enable))
        if self.sidebuf_enable:
            if self.sidebuf_watermark is None:
                raise SrotaIntentError(
                    "an enabled side buffer needs an explicit "
                    "sidebuf_watermark: no default is assumed")
            _as_int("sidebuf_watermark", self.sidebuf_watermark, minimum=1)
        elif self.sidebuf_watermark is not None:
            raise SrotaIntentError(
                "sidebuf_watermark without sidebuf_enable is contradictory")
        _as_int("tel_period", self.tel_period, minimum=1)
        _as_int("tel_latency", self.tel_latency, minimum=1)
        if self.island_columns and not (self.mecs_row and self.mecs_col):
            raise SrotaIntentError(
                "island columns require the full express layer "
                "(mecs_row and mecs_col): without express reach a route "
                "to an island column traverses arbitrary routers")

    def parameters(self) -> dict[str, Any]:
        return {
            "side_length": self.side_length,
            "concentration": self.concentration,
            "mecs_row": self.mecs_row,
            "mecs_col": self.mecs_col,
            "drop_latency": self.drop_latency,
            "planes": sorted(p.value for p in self.planes),
            "island_columns": list(self.island_columns),
            "path_shapes": sorted(s.value for s in self.path_shapes),
            "vc_policy": self.vc_policy.value,
            "sidebuf_enable": self.sidebuf_enable,
            "sidebuf_watermark": self.sidebuf_watermark,
            "tel_period": self.tel_period,
            "tel_latency": self.tel_latency,
        }

    @classmethod
    def from_dict(cls, d: Any) -> "SrotaIntent":
        """Strict ingestion: unknown fields refuse (no knob smuggling)."""
        if not isinstance(d, dict):
            raise SrotaIntentError(
                f"srota intent must be an object, got {type(d).__name__}")
        allowed = frozenset({
            "kind", "side_length", "concentration", "mecs_row", "mecs_col",
            "drop_latency", "planes", "island_columns", "path_shapes",
            "vc_policy", "sidebuf_enable", "sidebuf_watermark",
            "tel_period", "tel_latency",
        })
        unknown = sorted(set(d) - allowed)
        if unknown:
            raise SrotaIntentError(
                f"srota intent has unknown fields {unknown}: simulator "
                "knobs (congestion thresholds, epoch lengths, VC counts, "
                "allocators, delays, speedups, seeds) are not design intent")
        if "kind" in d and d["kind"] != "srota":
            raise SrotaIntentError(
                f"srota intent kind must be 'srota', got {d['kind']!r}")
        for seq_field in ("planes", "island_columns", "path_shapes"):
            if seq_field not in d:
                continue
            value = d[seq_field]
            if isinstance(value, str) or not isinstance(
                    value, (list, tuple, set, frozenset)):
                raise SrotaIntentError(
                    f"srota intent {seq_field!r} must be a collection, "
                    f"got {value!r}")
        try:
            return cls(
                side_length=d["side_length"],
                concentration=d["concentration"],
                mecs_row=d["mecs_row"],
                mecs_col=d["mecs_col"],
                drop_latency=d["drop_latency"],
                planes=d["planes"],
                island_columns=tuple(d["island_columns"]),
                path_shapes=d["path_shapes"],
                vc_policy=d["vc_policy"],
                sidebuf_enable=d["sidebuf_enable"],
                sidebuf_watermark=d["sidebuf_watermark"],
                tel_period=d["tel_period"],
                tel_latency=d["tel_latency"],
            )
        except KeyError as exc:
            raise SrotaIntentError(
                f"srota intent is missing required field {exc}") from exc


__all__ = [
    "SrotaIntent",
    "SrotaIntentError",
    "SrotaPathShape",
    "SrotaPlane",
    "SrotaVCPolicy",
]
