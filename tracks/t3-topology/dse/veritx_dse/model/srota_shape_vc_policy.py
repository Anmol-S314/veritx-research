"""SROTA direct-shape VC partition policy.

This records the BookSim ``srota_vc_policy=shape`` partition: row-first
and column-first use disjoint contiguous VC ranges. It does not encode which
shape runtime selects or certify the resulting routes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import SemanticError

SROTA_SHAPE_VC_POLICY_SCHEMA_VERSION = 1
_SHAPES = ("row", "column")


class SrotaShapeVCPolicyError(ValueError, SemanticError):
    """The direct-shape partition policy is malformed or unsupported."""


@dataclass(frozen=True)
class SrotaShapeVCPartitionPolicy:
    """Canonical VC allocation for the two direct SROTA path shapes.

    BookSim divides ``num_vcs`` by two using integer division and leaves any
    remainder unused. ``shape_to_vcs`` records only the VCs that can carry
    each shape; transitions never cross between the two sets.
    """

    num_vcs: int
    shape_to_vcs: tuple[tuple[str, tuple[int, ...]], ...]
    unused_vcs: tuple[int, ...]
    schema_version: int = SROTA_SHAPE_VC_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.num_vcs) is not int or self.num_vcs < 2:
            raise SrotaShapeVCPolicyError("num_vcs must be an int >= 2")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise SrotaShapeVCPolicyError(
                f"unsupported schema_version {self.schema_version!r}")
        if not isinstance(self.shape_to_vcs, tuple) or any(
                not isinstance(row, tuple) or len(row) != 2
                or not isinstance(row[0], str)
                or not isinstance(row[1], tuple)
                or any(type(vc) is not int for vc in row[1])
                for row in self.shape_to_vcs):
            raise SrotaShapeVCPolicyError(
                "shape_to_vcs must contain shape names and integer VC tuples")
        if not isinstance(self.unused_vcs, tuple) or any(
                type(vc) is not int for vc in self.unused_vcs):
            raise SrotaShapeVCPolicyError(
                "unused_vcs must be a tuple of exact ints")
        per_shape = self.num_vcs // 2
        expected = tuple(
            (shape, tuple(range(index * per_shape,
                                (index + 1) * per_shape)))
            for index, shape in enumerate(_SHAPES))
        expected_unused = tuple(range(2 * per_shape, self.num_vcs))
        if self.shape_to_vcs != expected or self.unused_vcs != expected_unused:
            raise SrotaShapeVCPolicyError(
                "shape_to_vcs and unused_vcs must match the canonical "
                "contiguous two-way partition")

    @classmethod
    def derive(cls, num_vcs: int) -> "SrotaShapeVCPartitionPolicy":
        if type(num_vcs) is not int or num_vcs < 2:
            raise SrotaShapeVCPolicyError("num_vcs must be an int >= 2")
        per_shape = num_vcs // 2
        return cls(
            num_vcs=num_vcs,
            shape_to_vcs=tuple(
                (shape, tuple(range(index * per_shape,
                                    (index + 1) * per_shape)))
                for index, shape in enumerate(_SHAPES)),
            unused_vcs=tuple(range(2 * per_shape, num_vcs)),
        )

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/ShapeVCPartitionPolicy",
            "schema_version": self.schema_version,
            "num_vcs": self.num_vcs,
            "shape_to_vcs": [[shape, list(vcs)]
                             for shape, vcs in self.shape_to_vcs],
            "unused_vcs": list(self.unused_vcs),
        }

    @property
    def policy_hash(self) -> str:
        return content_id(
            f"srota/ShapeVCPartitionPolicy/v{self.schema_version}",
            self.identity_dict())

    @property
    def partition_to_vcs(self) -> dict[int, tuple[int, ...]]:
        return {partition: vcs
                for partition, (_shape, vcs)
                in enumerate(self.shape_to_vcs)}

    @property
    def allowed_transitions(self) -> tuple[tuple[int, int], ...]:
        return tuple((src, dst)
                     for _shape, vcs in self.shape_to_vcs
                     for src in vcs for dst in vcs)

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_dict(), "policy_hash": self.policy_hash}

    @classmethod
    def from_dict(cls, value: Any) -> "SrotaShapeVCPartitionPolicy":
        expected = {"type", "schema_version", "num_vcs", "shape_to_vcs",
                    "unused_vcs", "policy_hash"}
        if not isinstance(value, dict) or set(value) != expected:
            raise SrotaShapeVCPolicyError(
                "policy must contain exactly " + ", ".join(sorted(expected)))
        if value["type"] != "srota/ShapeVCPartitionPolicy":
            raise SrotaShapeVCPolicyError("unrecognized policy type")
        try:
            rows = value["shape_to_vcs"]
            unused = value["unused_vcs"]
            if not isinstance(rows, list) or not isinstance(unused, list):
                raise TypeError
            if any(not isinstance(row, list) or len(row) != 2
                   or not isinstance(row[0], str)
                   or not isinstance(row[1], list) for row in rows):
                raise TypeError
            artifact = cls(
                num_vcs=value["num_vcs"],
                shape_to_vcs=tuple(
                    (row[0], tuple(row[1])) for row in rows),
                unused_vcs=tuple(unused),
                schema_version=value["schema_version"],
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, SrotaShapeVCPolicyError):
                raise
            raise SrotaShapeVCPolicyError(
                "policy contains malformed partition data") from exc
        if value["policy_hash"] != artifact.policy_hash:
            raise SrotaShapeVCPolicyError("policy_hash does not match policy")
        return artifact


__all__ = ["SrotaShapeVCPolicyError", "SrotaShapeVCPartitionPolicy"]
