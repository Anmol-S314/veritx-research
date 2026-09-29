"""veritx_dse.model.compute_intent — declared compute + memory demand (v4).

Compute is DECLARED, never inferred: a v4 request that carries no compute
intent has no compute and no memory demand, exactly as before. This is the
only author of COMPUTE operations, and it exists so the memory backend
(Ramulator) and compute-inclusive schedules have real operands to read.

Rationale: docs/decisions/compute-memory-intent.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.core.errors import SemanticError


class ComputeIntentError(ValueError, SemanticError):
    """A compute intent is malformed (fail-closed)."""


def _u64(value: Any, where: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise ComputeIntentError(f"{where} must be an int >= 0, got {value!r}")
    return value


def _loc(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise ComputeIntentError(f"{where} must be a non-empty string")
    return value


@dataclass(frozen=True)
class ComputeStage:
    """One declared compute stage and the bytes it moves through memory.

    ``stage_id`` is the author's name for the stage; declared order is the
    dependency order (the ET-lowering precedent — order is stated, not
    discovered). ``owner`` is the memory-issuing participant rank; it is
    required at lowering time when the design has more than one participant.
    Locations default to ``LOCAL`` and are validated by the memory lowerer,
    which refuses anything that is not the local pool.
    """

    stage_id: str
    duration_ns: int
    input_bytes: int
    weight_bytes: int
    output_bytes: int
    owner: int | None = None
    input_loc: str = "LOCAL"
    weight_loc: str = "LOCAL"
    output_loc: str = "LOCAL"

    def __post_init__(self) -> None:
        if not isinstance(self.stage_id, str) or not self.stage_id:
            raise ComputeIntentError("stage_id must be a non-empty string")
        for name in ("duration_ns", "input_bytes", "weight_bytes",
                     "output_bytes"):
            _u64(getattr(self, name), f"stage {self.stage_id!r}.{name}")
        if self.owner is not None:
            _u64(self.owner, f"stage {self.stage_id!r}.owner")
        for name in ("input_loc", "weight_loc", "output_loc"):
            _loc(getattr(self, name), f"stage {self.stage_id!r}.{name}")

    @property
    def operand_bytes(self) -> int:
        return self.input_bytes + self.weight_bytes + self.output_bytes

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "duration_ns": self.duration_ns,
            "input_bytes": self.input_bytes,
            "weight_bytes": self.weight_bytes,
            "output_bytes": self.output_bytes,
            "owner": self.owner,
            "input_loc": self.input_loc,
            "weight_loc": self.weight_loc,
            "output_loc": self.output_loc,
        }

    @classmethod
    def from_dict(cls, d: Any) -> "ComputeStage":
        if not isinstance(d, dict):
            raise ComputeIntentError("compute stage must be an object")
        allowed = {
            "stage_id", "duration_ns", "input_bytes", "weight_bytes",
            "output_bytes", "owner", "input_loc", "weight_loc", "output_loc",
        }
        unknown = set(d) - allowed
        if unknown:
            raise ComputeIntentError(
                f"compute stage has unknown fields {sorted(unknown)}")
        missing = {"stage_id", "duration_ns", "input_bytes", "weight_bytes",
                   "output_bytes"} - set(d)
        if missing:
            raise ComputeIntentError(
                f"compute stage is missing fields {sorted(missing)}")
        return cls(
            stage_id=d["stage_id"],
            duration_ns=d["duration_ns"],
            input_bytes=d["input_bytes"],
            weight_bytes=d["weight_bytes"],
            output_bytes=d["output_bytes"],
            owner=d.get("owner"),
            input_loc=d.get("input_loc", "LOCAL"),
            weight_loc=d.get("weight_loc", "LOCAL"),
            output_loc=d.get("output_loc", "LOCAL"),
        )


@dataclass(frozen=True)
class ComputeIntent:
    """An ordered tuple of declared compute stages (empty means none)."""

    stages: tuple[ComputeStage, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.stages, tuple) \
                or not all(isinstance(s, ComputeStage) for s in self.stages):
            raise ComputeIntentError("stages must be a tuple of ComputeStage")
        ids = [s.stage_id for s in self.stages]
        if len(set(ids)) != len(ids):
            raise ComputeIntentError(
                f"compute stage ids must be unique, got {ids}")

    def is_empty(self) -> bool:
        return not self.stages

    @property
    def operand_bytes(self) -> int:
        return sum(s.operand_bytes for s in self.stages)

    def to_dict(self) -> dict[str, Any]:
        return {"stages": [s.to_dict() for s in self.stages]}

    @classmethod
    def from_dict(cls, d: Any) -> "ComputeIntent":
        if d is None:
            return cls()
        if not isinstance(d, dict):
            raise ComputeIntentError("compute intent must be an object")
        unknown = set(d) - {"stages"}
        if unknown:
            raise ComputeIntentError(
                f"compute intent has unknown fields {sorted(unknown)}")
        stages = d.get("stages", [])
        if not isinstance(stages, list):
            raise ComputeIntentError("compute intent 'stages' must be a list")
        return cls(stages=tuple(ComputeStage.from_dict(s) for s in stages))


__all__ = ["ComputeIntent", "ComputeIntentError", "ComputeStage"]
