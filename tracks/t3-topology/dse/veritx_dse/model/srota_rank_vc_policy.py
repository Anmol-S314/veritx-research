"""SROTA hop-rank VC partition policy (``srota_vc_policy=rank``).

The fork's rank policy assigns a packet's VC set from its position in the
path, not from which shape chose it:

    rank = SrotaRankBase(shape) + (turned ? 1 : 0)

with ``SrotaRankBase`` 0 for the direct shapes and the Valiant first leg,
and 2 for the Valiant second leg (srota.hpp). The direct shapes therefore
share ranks 0/1 — pre-turn / post-turn — which is O1TURN's own two-set
answer, while a Valiant path's second leg occupies ranks 2/3 so its second
turn cannot share a set with its first.

This is the only policy the fork accepts for Valiant (``shape`` and
``oneshape`` both ``exit(-1)`` with Valiant enabled), so it is the policy
that makes Valiant expressible at all.

The model keeps one VC per rank and requires ``num_vcs == rank count``:
the fork's own CDG check is per SET (``nsets``), and a proof over more VCs
per set would be proving a different graph than the simulator checks. A
design that needs extra VCs for its dependency graph is therefore refused
rather than silently given a partition the fork would not use.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import SemanticError

SROTA_RANK_VC_POLICY_SCHEMA_VERSION = 1

_DIRECT_RANKS = (0, 1)
_VALIANT_RANKS = (0, 1, 2, 3)

class SrotaRankVCPolicyError(ValueError, SemanticError):
    """The hop-rank partition policy is malformed or unsupported."""

@dataclass(frozen=True)
class SrotaRankVCPartitionPolicy:
    """Canonical VC allocation for the SROTA hop-rank policy.

    Ranks 0/1 are the direct shapes' pre-turn/post-turn sets; ranks 2/3 are
    the Valiant second leg's, and exist only when Valiant is enabled.
    """

    num_vcs: int
    valiant: bool
    rank_to_vcs: tuple[tuple[int, tuple[int, ...]], ...]
    unused_vcs: tuple[int, ...] = ()
    schema_version: int = SROTA_RANK_VC_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.num_vcs) is not int or self.num_vcs < 2:
            raise SrotaRankVCPolicyError("num_vcs must be an int >= 2")
        if type(self.valiant) is not bool:
            raise SrotaRankVCPolicyError("valiant must be a bool")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise SrotaRankVCPolicyError(
                f"unsupported schema_version {self.schema_version!r}")
        if not isinstance(self.rank_to_vcs, tuple) or any(
                not isinstance(row, tuple) or len(row) != 2
                or type(row[0]) is not int or not isinstance(row[1], tuple)
                or any(type(vc) is not int for vc in row[1])
                for row in self.rank_to_vcs):
            raise SrotaRankVCPolicyError(
                "rank_to_vcs must contain int ranks and integer VC tuples")
        if not isinstance(self.unused_vcs, tuple) or any(
                type(vc) is not int for vc in self.unused_vcs):
            raise SrotaRankVCPolicyError(
                "unused_vcs must be a tuple of exact ints")
        expected = tuple((rank, (rank,)) for rank in self.ranks)
        if self.rank_to_vcs != expected or self.unused_vcs:
            raise SrotaRankVCPolicyError(
                "rank_to_vcs must map each rank to exactly its own VC, with "
                "no unused VCs; the fork's proof is per VC set")
        if self.num_vcs != len(self.ranks):
            raise SrotaRankVCPolicyError(
                f"the rank policy has {len(self.ranks)} sets, so num_vcs "
                f"must be {len(self.ranks)}, got {self.num_vcs}")

    @property
    def ranks(self) -> tuple[int, ...]:
        return _VALIANT_RANKS if self.valiant else _DIRECT_RANKS

    @classmethod
    def derive(cls, *, valiant: bool) -> "SrotaRankVCPartitionPolicy":
        ranks = _VALIANT_RANKS if valiant else _DIRECT_RANKS
        return cls(
            num_vcs=len(ranks), valiant=valiant,
            rank_to_vcs=tuple((rank, (rank,)) for rank in ranks))

    @property
    def nsets(self) -> int:
        return len(self.ranks)

    @property
    def partition_to_vcs(self) -> dict[int, tuple[int, ...]]:
        return {rank: vcs for rank, vcs in self.rank_to_vcs}

    @property
    def allowed_transitions(self) -> tuple[tuple[int, int], ...]:
        """Rank never decreases within a packet's path."""
        return tuple((a, b) for a in self.ranks for b in self.ranks if a <= b)

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/RankVCPartitionPolicy",
            "schema_version": self.schema_version,
            "num_vcs": self.num_vcs,
            "valiant": self.valiant,
            "rank_to_vcs": [[rank, list(vcs)]
                            for rank, vcs in self.rank_to_vcs],
            "unused_vcs": list(self.unused_vcs),
        }

    @property
    def policy_hash(self) -> str:
        return content_id(
            f"srota/RankVCPartitionPolicy/v{self.schema_version}",
            self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_dict(), "policy_hash": self.policy_hash}


__all__ = [
    "SrotaRankVCPolicyError",
    "SrotaRankVCPartitionPolicy",
    "SROTA_RANK_VC_POLICY_SCHEMA_VERSION",
]
