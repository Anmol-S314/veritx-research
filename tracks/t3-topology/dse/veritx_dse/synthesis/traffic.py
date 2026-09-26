"""veritx_dse.synthesis.traffic — canonical synthesis traffic authority.

WHY THIS EXISTS
---------------

The historical MILP generator reads a bare ``.mat`` file::

    def load_matrix(path):
        mat = []
        with open(path) as f:
            for line in f:
                ...
                mat.append([float(x) for x in line.split()])
        return np.array(mat)

That is a research-tool loader. It performs NO validation: a ragged file
raises deep inside numpy, a NaN propagates silently into the objective, and
a negative demand is accepted as ordinary traffic. It also carries no
record of WHERE the traffic came from, so a synthesised topology cannot be
traced back to the workload that justified it.

The canonical path needs the opposite: an explicit, validated, identified
traffic authority with no fallback of any kind.

NO HIDDEN FALLBACK — this is the rule the module exists to enforce:

  * no uniform-traffic default when the source is missing or malformed
  * no partial/lenient parse of a bad file
  * no silently reshaped matrix
  * no negative, NaN or infinite demand
  * no namespace mismatch between the matrix and the router count

Every one of those refuses with a typed error naming the field.

AGGREGATION IS DECLARED, NOT ASSUMED
------------------------------------

A traffic matrix is a PROJECTION of a richer workload. Which messages were
summed, over what span, in what unit — that is science, so it is carried
explicitly rather than implied. A matrix whose aggregation rule is unknown
cannot be reproduced and is therefore not a canonical authority.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from veritx_dse.core.artifact import content_id
from veritx_dse.core.spec import canonical_json

DOMAIN = "veritx/synthesis-traffic-matrix/v1"
SCHEMA_VERSION = 1

#: What the matrix entries measure. Declared, never inferred.
UNITS = ("bytes", "messages", "flits")

#: How the matrix was projected from its source artifact.
AGGREGATION_RULES = (
    "sum_over_window",
    "sum_over_workload",
    "steady_state_rate",
)


class SynthesisTrafficError(ValueError):
    """Invalid or unusable traffic authority (typed, fail-closed)."""


@dataclass(frozen=True)
class SynthesisTrafficMatrix:
    """An NxN traffic demand matrix with declared provenance and units.

    ``values[i][j]`` is the demand from router/endpoint ``i`` to ``j``.
    The diagonal MUST be zero: a node does not send to itself, and a
    nonzero diagonal would be silently dropped by every consumer while
    still moving the matrix identity.
    """

    #: Canonical identity of the artifact this was projected from. Required:
    #: a matrix with no source cannot be traced or invalidated.
    source_artifact_id: str
    #: Namespace the indices live in (e.g. "rank", "router").
    namespace: str
    #: Number of participants. Must equal len(values).
    dimension: int
    values: tuple[tuple[float, ...], ...]
    unit: str
    aggregation: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        if self.schema_version != SCHEMA_VERSION:
            raise SynthesisTrafficError(
                f"schema_version {self.schema_version} != {SCHEMA_VERSION}")
        if not isinstance(self.source_artifact_id, str) or \
                not self.source_artifact_id:
            raise SynthesisTrafficError(
                "source_artifact_id is required — a traffic matrix with no "
                "source cannot be traced or invalidated")
        if not isinstance(self.namespace, str) or not self.namespace:
            raise SynthesisTrafficError("namespace must be a non-empty string")
        if self.unit not in UNITS:
            raise SynthesisTrafficError(
                f"unknown unit {self.unit!r}; supported: {list(UNITS)}")
        if self.aggregation not in AGGREGATION_RULES:
            raise SynthesisTrafficError(
                f"unknown aggregation {self.aggregation!r}; "
                f"supported: {list(AGGREGATION_RULES)}")
        if type(self.dimension) is not int or self.dimension < 2:
            raise SynthesisTrafficError(
                f"dimension must be an int >= 2, got {self.dimension!r}")

        vals = self.values
        if isinstance(vals, list):
            vals = tuple(tuple(r) for r in vals)
            object.__setattr__(self, "values", vals)
        if not isinstance(vals, tuple) or len(vals) != self.dimension:
            raise SynthesisTrafficError(
                f"values must have exactly {self.dimension} rows, got "
                f"{len(vals) if hasattr(vals, '__len__') else '?'}")
        for i, row in enumerate(vals):
            if not isinstance(row, tuple) or len(row) != self.dimension:
                raise SynthesisTrafficError(
                    f"row {i} must have exactly {self.dimension} columns, "
                    f"got {len(row) if hasattr(row, '__len__') else '?'} "
                    "(a ragged matrix is not a matrix)")
            for j, v in enumerate(row):
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    raise SynthesisTrafficError(
                        f"values[{i}][{j}] must be a number, got {v!r}")
                if not math.isfinite(v):
                    raise SynthesisTrafficError(
                        f"values[{i}][{j}] must be finite, got {v!r} "
                        "(NaN/Inf would propagate silently into the "
                        "objective)")
                if v < 0:
                    raise SynthesisTrafficError(
                        f"values[{i}][{j}] must be >= 0, got {v!r} "
                        "(negative demand is not traffic)")
            if row[i] != 0:
                raise SynthesisTrafficError(
                    f"values[{i}][{i}] must be 0 — a node does not send to "
                    f"itself, and a nonzero diagonal would be dropped by "
                    f"every consumer while still moving the identity")

    # ── identity ─────────────────────────────────────────────────────

    def traffic_id(self) -> str:
        return content_id(DOMAIN, {
            "source_artifact_id": self.source_artifact_id,
            "namespace": self.namespace,
            "dimension": self.dimension,
            "values": [list(r) for r in self.values],
            "unit": self.unit,
            "aggregation": self.aggregation,
        })

    def total_demand(self) -> float:
        return float(sum(sum(r) for r in self.values))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "traffic_id": self.traffic_id(),
            "source_artifact_id": self.source_artifact_id,
            "namespace": self.namespace,
            "dimension": self.dimension,
            "values": [list(r) for r in self.values],
            "unit": self.unit,
            "aggregation": self.aggregation,
            "total_demand": self.total_demand(),
        }

    @classmethod
    def from_dict(cls, d: Any) -> "SynthesisTrafficMatrix":
        if not isinstance(d, dict):
            raise SynthesisTrafficError(
                f"traffic matrix must be an object, got {type(d).__name__}")
        allowed = {
            "schema_version", "traffic_id", "source_artifact_id",
            "namespace", "dimension", "values", "unit", "aggregation",
            "total_demand",
        }
        unknown = sorted(set(d) - allowed)
        if unknown:
            raise SynthesisTrafficError(
                f"unknown traffic matrix fields {unknown} (schema close)")
        obj = cls(
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            source_artifact_id=d["source_artifact_id"],
            namespace=d["namespace"],
            dimension=d["dimension"],
            values=tuple(tuple(r) for r in d["values"]),
            unit=d["unit"],
            aggregation=d["aggregation"],
        )
        supplied = d.get("traffic_id")
        if supplied is not None and supplied != obj.traffic_id():
            raise SynthesisTrafficError(
                "traffic_id does not match content — the payload was edited "
                "after it was addressed")
        return obj

    @classmethod
    def from_rows(cls, rows: Sequence[Sequence[float]], *,
                  source_artifact_id: str, namespace: str, unit: str,
                  aggregation: str) -> "SynthesisTrafficMatrix":
        """Strict constructor from raw rows. Dimension is DERIVED, and a
        ragged input is refused rather than truncated."""
        rows = [list(r) for r in rows]
        if not rows:
            raise SynthesisTrafficError("traffic matrix has no rows")
        widths = {len(r) for r in rows}
        if len(widths) != 1:
            raise SynthesisTrafficError(
                f"traffic matrix is ragged: row widths {sorted(widths)}")
        dim = len(rows)
        if widths != {dim}:
            raise SynthesisTrafficError(
                f"traffic matrix must be square: {dim} rows of width "
                f"{widths.pop()}")
        return cls(
            source_artifact_id=source_artifact_id, namespace=namespace,
            dimension=dim, values=tuple(tuple(float(v) for v in r)
                                        for r in rows),
            unit=unit, aggregation=aggregation)

    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())


def from_uniform(n: int, *, demand: float, source_artifact_id: str,
                 namespace: str, unit: str,
                 aggregation: str) -> SynthesisTrafficMatrix:
    """Build a UNIFORM matrix — explicitly, never as a fallback.

    This exists so a caller who genuinely wants uniform traffic must SAY so
    and supply a source identity. Nothing in the canonical path calls it
    implicitly; a missing or malformed source refuses instead.
    """
    if demand <= 0:
        raise SynthesisTrafficError("uniform demand must be positive")
    rows = [[0.0 if i == j else float(demand) for j in range(n)]
            for i in range(n)]
    return SynthesisTrafficMatrix.from_rows(
        rows, source_artifact_id=source_artifact_id, namespace=namespace,
        unit=unit, aggregation=aggregation)


__all__ = [
    "DOMAIN", "SCHEMA_VERSION", "UNITS", "AGGREGATION_RULES",
    "SynthesisTrafficError", "SynthesisTrafficMatrix", "from_uniform",
]
