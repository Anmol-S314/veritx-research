"""veritx_dse.model.mapping — MappingArtifact (Wave B2).

A workload's tp/pp/ep/dp counts do not say WHICH hardware agent each
rank runs on. Two runs with swapped per-rank placement share a rank
multiset but execute different work on different agents; they are not
equivalent.

MappingArtifact answers exactly one question:

    which hardware AgentInstance hosts each logical workload rank?

It does NOT answer which endpoint or router that agent attaches to —
that is a B3 fabric relationship, and no fabric field is representable
here. The artifact is derived (never hand-authored for the baseline
path), content-addressed, schema-versioned, and fails closed.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .compile_model import AgentKind, CompileRequest, _as_enum, _as_int
from .placement import AgentInstance, build_inventory

MAPPING_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/MappingArtifact"


class MappingError(ValueError):
    """Invalid placement (fail-closed, never guessed or oversubscribed)."""


def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise MappingError(f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise MappingError(f"{where} has unknown fields: {sorted(unknown)}")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise MappingError(f"{where} is missing required field {key!r}")
    return d[key]


@dataclass(frozen=True)
class RankPlacement:
    """One rank's resolved home: the AgentInstance that hosts it."""

    rank: int
    agent: AgentInstance

    def __post_init__(self):
        _as_int("rank", self.rank, minimum=0)
        if not isinstance(self.agent, AgentInstance):
            raise MappingError(
                f"agent must be AgentInstance, got {type(self.agent).__name__}")

    def to_dict(self) -> dict[str, Any]:
        return {"rank": self.rank, "agent": self.agent.to_dict()}

    @classmethod
    def from_dict(cls, d: Any) -> RankPlacement:
        _strict_keys(d, frozenset({"rank", "agent"}), "placement")
        agent = _need(d, "agent", "placement")
        _strict_keys(agent, frozenset({"group_index", "instance_index", "kind"}),
                     "placement.agent")
        try:
            kind = AgentKind(_need(agent, "kind", "placement.agent"))
        except ValueError:
            raise MappingError(
                f"placement.agent.kind unknown: {agent.get('kind')!r}") from None
        return cls(
            rank=_need(d, "rank", "placement"),
            agent=AgentInstance(
                group_index=_need(agent, "group_index", "placement.agent"),
                instance_index=_need(agent, "instance_index", "placement.agent"),
                kind=kind,
            ),
        )


@dataclass(frozen=True)
class MappingArtifact:
    """Content-addressed, one-to-one LogicalRank → AgentInstance placement."""

    placements: tuple[RankPlacement, ...]
    schema_version: int = MAPPING_SCHEMA_VERSION

    def __post_init__(self):
        if not isinstance(self.placements, tuple):
            raise MappingError("placements must be a tuple of RankPlacement")
        for p in self.placements:
            if not isinstance(p, RankPlacement):
                raise MappingError(
                    f"placements must contain RankPlacement, got "
                    f"{type(p).__name__}")
        try:
            version = _as_int("schema_version", self.schema_version)
        except ValueError as e:
            raise MappingError(str(e)) from None
        if version != MAPPING_SCHEMA_VERSION:
            raise MappingError(
                f"unsupported mapping schema_version {self.schema_version} "
                f"(this build implements v{MAPPING_SCHEMA_VERSION})")
        ranks = [p.rank for p in self.placements]
        if ranks != list(range(len(ranks))):
            raise MappingError("placements must be contiguous from rank 0")
        seen: dict[str, int] = {}
        for p in self.placements:
            if p.agent.kind != AgentKind.COMPUTE_TILE:
                raise MappingError(
                    f"rank {p.rank} is hosted by a {p.agent.kind.value} agent; "
                    "only compute instances may host workload ranks")
            prior = seen.get(p.agent.instance_id)
            if prior is not None:
                raise MappingError(
                    f"duplicate agent placement: {p.agent.instance_id} is "
                    f"assigned to ranks {prior} and {p.rank}")
            seen[p.agent.instance_id] = p.rank

    @property
    def rank_count(self) -> int:
        """Active ranks. Deliberately not the fabric's agent count."""
        return len(self.placements)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "placements": [p.to_dict() for p in self.placements],
        }

    def mapping_hash(self) -> str:
        from veritx_dse.core.spec import canonical_json
        body = (f"{_HASH_TYPE_TAG}/v{self.schema_version}\0"
                + canonical_json(self.canonical_dict()))
        return hashlib.sha256(body.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version,
                "placements": [p.to_dict() for p in self.placements],
                "mapping_hash": self.mapping_hash()}

    @classmethod
    def from_dict(cls, d: Any) -> MappingArtifact:
        _strict_keys(d, frozenset({"schema_version", "placements",
                                   "mapping_hash"}), "mapping")
        version = _need(d, "schema_version", "mapping")
        placements = _need(d, "placements", "mapping")
        supplied = _need(d, "mapping_hash", "mapping")
        if not isinstance(placements, list):
            raise MappingError("mapping.placements must be a list")
        artifact = cls(
            schema_version=version,
            placements=tuple(RankPlacement.from_dict(p) for p in placements),
        )
        if supplied != artifact.mapping_hash():
            raise MappingError("mapping_hash does not match content")
        return artifact


def derive_mapping(cr: CompileRequest) -> MappingArtifact:
    """Bind every rank to a distinct compute instance, deterministically.

    Baseline P1 policy: rank r takes the r-th compute instance in
    canonical NodeInventory order. This is not an optimizer and not
    physical placement. If the workload has more ranks than compute
    instances the placement is infeasible and refused — never
    oversubscribed or modulo-mapped.
    """
    inventory = build_inventory(cr)
    compute = inventory.compute_instances
    if inventory.rank_count > len(compute):
        raise MappingError(
            f"workload needs {inventory.rank_count} ranks but design has only "
            f"{len(compute)} compute instances")
    placements = tuple(
        RankPlacement(rank=r.rank, agent=compute[r.rank])
        for r in inventory.ranks
    )
    return MappingArtifact(placements=placements)
