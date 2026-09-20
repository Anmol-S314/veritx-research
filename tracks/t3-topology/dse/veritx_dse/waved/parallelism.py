"""veritx_dse.waved.parallelism — ParallelismArtifact (D1, §4/§5/§7/§8/§9).

One immutable, strict, versioned Wave-D authority for rank-space
geometry. Identity covers exactly (schema_version, tp, pp, ep, dp):

    parallelism_id = H("srota/WavedParallelism", v, TP, PP, EP, DP)

``world_size`` is DERIVED (R = TP·PP·EP·DP) and is never an independent
identity field: two artifacts with the same four dimensions are the same
geometry, whatever integer they were constructed from.

Group derivation is total and law-checked (§9): for every family every
rank appears in exactly one group, groups are disjoint, and
Σ group sizes = R. The "PP family" is stages, not collectives: a stage
holds all ranks with one pp index.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.model.placement import coords_of, rank_of  # authority reuse

from .errors import InvalidInput
from .identity import content_hash
from .oracles import ref_coords, ref_group_members, ref_rank
from .strict import (
    require_embedded_id, require_fields, require_schema_version,
    require_type_tag,
)

SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/WavedParallelism"

# Group families that produce collective participant sets. PP is a stage
# partition, not a collective family (a stage spans every other axis).
COLLECTIVE_FAMILIES = ("TP", "EP", "DP")
ALL_FAMILIES = ("TP", "PP", "EP", "DP")


@dataclass(frozen=True)
class Group:
    """One communication group: a family, its fixed coordinate key, and
    the member ranks in canonical order."""

    family: str
    index: tuple[int, ...]   # the fixed coordinate key (t,p,e,d) minus the
                             # varying axis; PP uses (p,)
    members: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"family": self.family, "index": list(self.index),
                "members": list(self.members)}


@dataclass(frozen=True)
class ParallelismArtifact:
    """Versioned Wave-D rank-space geometry (identity = 4 dimensions)."""

    tp: int
    pp: int
    ep: int
    dp: int
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("tp", "pp", "ep", "dp"):
            v = getattr(self, name)
            if type(v) is not int or isinstance(v, bool) or v < 1:
                raise InvalidInput(
                    f"parallelism {name} must be a positive int, got {v!r}")
        if type(self.schema_version) is not int \
                or self.schema_version != SCHEMA_VERSION:
            raise InvalidInput(
                f"unsupported parallelism schema_version "
                f"{self.schema_version!r} (expected {SCHEMA_VERSION})")

    # ── derived quantities (never identity fields) ────────────────────
    @property
    def world_size(self) -> int:
        return self.tp * self.pp * self.ep * self.dp

    def sizes(self) -> tuple[int, int, int, int]:
        return (self.tp, self.pp, self.ep, self.dp)

    def rank_of(self, t: int, p: int, e: int, d: int) -> int:
        """Canonical rank of coordinates, via the Wave-B authority."""
        try:
            return rank_of(t, p, e, d, tp=self.tp, pp=self.pp,
                           ep=self.ep, dp=self.dp)
        except ValueError as exc:
            raise InvalidInput(str(exc)) from None

    def coords_of(self, rank: int) -> dict[str, int]:
        try:
            return coords_of(rank, tp=self.tp, pp=self.pp, ep=self.ep,
                             dp=self.dp)
        except ValueError as exc:
            raise InvalidInput(str(exc)) from None

    # ── identity ───────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        return {"type": _HASH_TYPE_TAG, "schema_version": self.schema_version,
                "tp": self.tp, "pp": self.pp, "ep": self.ep, "dp": self.dp}

    def parallelism_id(self) -> str:
        return content_hash(_HASH_TYPE_TAG, self.schema_version,
                            self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_dict(),
                "world_size": self.world_size,
                "parallelism_id": self.parallelism_id()}

    @classmethod
    def from_dict(cls, d: Any, *, strict: bool = False
                  ) -> "ParallelismArtifact":
        """Parse a parallelism document.

        ``strict=True`` is the persisted-resource contract: exact type
        tag, exact schema version, required embedded ID, unknown fields
        refused. The caller (a verified loader) still owns the
        requested-filename vs embedded-ID comparison.
        """
        allowed = {"type", "schema_version", "tp", "pp", "ep",
                   "dp", "world_size", "parallelism_id"}
        require_fields(d, allowed, "parallelism")
        if strict:
            require_type_tag(d, _HASH_TYPE_TAG, "parallelism")
            require_schema_version(d, SCHEMA_VERSION, "parallelism")
            for key in ("tp", "pp", "ep", "dp", "world_size",
                        "parallelism_id"):
                if key not in d:
                    raise InvalidInput(
                        f"persisted parallelism is missing {key!r}")
        elif "type" in d and d["type"] != _HASH_TYPE_TAG:
            raise InvalidInput(
                f"parallelism type tag {d['type']!r} is not "
                f"{_HASH_TYPE_TAG!r}")
        if "world_size" in d:
            # Self-integrity only: the stored world size must equal the
            # derived one (it is not part of identity).
            expected = (d.get("tp", 0) or 1) * (d.get("pp", 0) or 1) \
                * (d.get("ep", 0) or 1) * (d.get("dp", 0) or 1)
            if d["world_size"] != expected:
                raise InvalidInput(
                    f"stored world_size {d['world_size']} != derived "
                    f"{expected}")
        art = cls(tp=d["tp"], pp=d["pp"], ep=d["ep"], dp=d["dp"],
                  schema_version=d.get("schema_version", SCHEMA_VERSION))
        if strict:
            require_embedded_id(d, "parallelism_id", art.parallelism_id(),
                                "parallelism")
        elif "parallelism_id" in d \
                and d["parallelism_id"] != art.parallelism_id():
            raise InvalidInput(
                "parallelism_id does not match content")
        return art

    # ── group derivation (§9) ──────────────────────────────────────────
    def groups(self, family: str) -> tuple[Group, ...]:
        """All groups of one family, in canonical order. PP = stages."""
        if family not in ALL_FAMILIES:
            raise InvalidInput(
                f"unknown group family {family!r} (families: "
                f"{ALL_FAMILIES})")
        out: list[Group] = []
        for p in range(self.pp):
            for d in range(self.dp):
                for e in range(self.ep):
                    for t in range(self.tp):
                        coords = (t, p, e, d)
                        if family == "PP":
                            key = (p,)
                            if (t, e, d) != (0, 0, 0):
                                continue
                            members = tuple(
                                ref_rank(i, p, j, k, tp=self.tp, pp=self.pp,
                                         ep=self.ep, dp=self.dp)
                                for i in range(self.tp)
                                for j in range(self.ep)
                                for k in range(self.dp))
                        else:
                            if family == "TP":
                                if t != 0:
                                    continue
                                members = tuple(
                                    ref_rank(i, p, e, d, tp=self.tp,
                                             pp=self.pp, ep=self.ep,
                                             dp=self.dp)
                                    for i in range(self.tp))
                                key = (p, e, d)
                            elif family == "EP":
                                if e != 0:
                                    continue
                                members = tuple(
                                    ref_rank(t, p, i, d, tp=self.tp,
                                             pp=self.pp, ep=self.ep,
                                             dp=self.dp)
                                    for i in range(self.ep))
                                key = (t, p, d)
                            else:  # DP
                                if d != 0:
                                    continue
                                members = tuple(
                                    ref_rank(t, p, e, i, tp=self.tp,
                                             pp=self.pp, ep=self.ep,
                                             dp=self.dp)
                                    for i in range(self.dp))
                                key = (t, p, e)
                        out.append(Group(family=family, index=key,
                                         members=members))
        return tuple(out)

    def group_of(self, family: str, rank: int) -> Group:
        """The one family group containing ``rank`` (law: exactly one)."""
        c = self.coords_of(rank)
        members = ref_group_members(family, self.sizes(),
                                    (c["tp"], c["pp"], c["ep"], c["dp"]))
        if family == "TP":
            key = (c["pp"], c["ep"], c["dp"])
        elif family == "EP":
            key = (c["tp"], c["pp"], c["dp"])
        elif family == "DP":
            key = (c["tp"], c["pp"], c["ep"])
        else:
            key = (c["pp"],)
        return Group(family=family, index=key, members=members)

    def validate_group_laws(self) -> None:
        """Mechanical §9 proof: coverage, disjointness, cardinality."""
        for family in ALL_FAMILIES:
            gs = self.groups(family)
            seen: list[int] = []
            for g in gs:
                if len(set(g.members)) != len(g.members):
                    raise ConservationLikeError(
                        f"{family} group {g.index} has duplicate members")
                seen.extend(g.members)
            if sorted(seen) != list(range(self.world_size)):
                raise ConservationLikeError(
                    f"{family} groups do not cover ranks exactly once")

    def cross_check_against_oracle(self) -> None:
        """Independent-oracle cross-check of the rank bijection (§26)."""
        for r in range(self.world_size):
            c = self.coords_of(r)
            got = self.rank_of(c["tp"], c["pp"], c["ep"], c["dp"])
            if got != r:
                raise ConservationLikeError(
                    f"rank bijection broken at {r}: got {got}")
            if ref_coords(r, tp=self.tp, pp=self.pp, ep=self.ep,
                          dp=self.dp) != \
                    (c["tp"], c["pp"], c["ep"], c["dp"]):
                raise ConservationLikeError(
                    f"coords disagree with the independent oracle at "
                    f"rank {r}")


class ConservationLikeError(InvalidInput):
    """A structural group/bijection law failed inside ParallelismArtifact.

    Named distinctly for test targeting; still an INVALID_INPUT-class
    refusal because the artifact itself cannot be valid if these fail.
    """


__all__ = [
    "ALL_FAMILIES", "COLLECTIVE_FAMILIES", "ConservationLikeError", "Group",
    "ParallelismArtifact", "SCHEMA_VERSION",
]
