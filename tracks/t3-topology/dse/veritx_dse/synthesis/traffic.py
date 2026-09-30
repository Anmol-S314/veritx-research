"""veritx_dse.synthesis.traffic — canonical synthesis traffic authority.

Rationale: docs/decisions/modules/synthesis.md
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from veritx_dse.core.artifact import content_id
from veritx_dse.core.spec import canonical_json

DOMAIN = "veritx/synthesis-traffic-matrix/v1"
SCHEMA_VERSION = 1

UNITS = ("bytes", "messages", "flits")

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

Rationale: docs/decisions/modules/synthesis.md
    """

    source_artifact_id: str
    namespace: str
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

    @classmethod
    def from_message_artifact(cls, artifact: Any, *,
                              namespace: str = "rank", unit: str = "bytes",
                              aggregation: str = "sum_over_workload",
                              ) -> "SynthesisTrafficMatrix":
        """Project a canonical logical-message artifact into a demand matrix.

        The artifact supplies the dimension (its ``participant_count``) and
        the provenance (its ``message_artifact_id``), so the matrix is bound
        to exactly the traffic it was derived from — never a bare digest.
        """
        for name in ("messages", "participant_count", "message_artifact_id"):
            if not hasattr(artifact, name):
                raise SynthesisTrafficError(
                    f"traffic projection needs a message artifact with "
                    f"{name!r}; got {type(artifact).__name__}")
        return cls.from_messages(
            artifact.messages,
            source_artifact_id=artifact.message_artifact_id(),
            dimension=int(artifact.participant_count),
            namespace=namespace, unit=unit, aggregation=aggregation)

    @classmethod
    def from_messages(cls, messages: Iterable[Any], *,
                      source_artifact_id: str, dimension: int,
                      namespace: str = "rank", unit: str = "bytes",
                      aggregation: str = "sum_over_workload",
                      ) -> "SynthesisTrafficMatrix":
        """Sum a logical-message stream into an NxN demand matrix.

        ``T[src][dst]`` accumulates the message payload (bytes) — or one per
        message for ``unit="messages"`` — over the WHOLE stream
        (``sum_over_workload``); the caller declares the aggregation, it is
        never inferred. This is the canonical projection: a trace/traffic
        artifact becomes a matrix, and a matrix with no source refuses.

        Refused, not guessed: an out-of-namespace rank, a self-message (a
        nonzero diagonal is not traffic), and ``unit="flits"`` (no flit
        width is a property of this projection).
        """
        if unit not in ("bytes", "messages"):
            raise SynthesisTrafficError(
                f"from_messages supports unit 'bytes' or 'messages'; "
                f"{unit!r} needs a flit width this projection does not own")
        if type(dimension) is not int or dimension < 2:
            raise SynthesisTrafficError(
                f"dimension must be an int >= 2, got {dimension!r}")
        rows = [[0.0] * dimension for _ in range(dimension)]
        n_msgs = 0
        for m in messages:
            try:
                s, d, payload = m.src_rank, m.dst_rank, m.payload_bytes
            except AttributeError:
                raise SynthesisTrafficError(
                    f"a message must carry src_rank/dst_rank/payload_bytes, "
                    f"got {type(m).__name__}") from None
            if not (0 <= s < dimension and 0 <= d < dimension):
                raise SynthesisTrafficError(
                    f"message {getattr(m, 'message_id', '?')!r} addresses "
                    f"{s}->{d}, outside the matrix namespace 0..{dimension - 1}")
            if s == d:
                raise SynthesisTrafficError(
                    f"message {getattr(m, 'message_id', '?')!r} is a "
                    f"self-message ({s}->{d}); a nonzero diagonal is not "
                    "network traffic")
            rows[s][d] += float(payload) if unit == "bytes" else 1.0
            n_msgs += 1
        if n_msgs == 0:
            raise SynthesisTrafficError(
                "the message stream is empty — there is no traffic to "
                "project into a matrix")
        return cls.from_rows(
            rows, source_artifact_id=source_artifact_id, namespace=namespace,
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
