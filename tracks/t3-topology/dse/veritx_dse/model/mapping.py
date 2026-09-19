"""veritx_dse.model.mapping — MappingArtifact (Wave B2.2).

A workload's tp/pp/ep/dp counts do not say WHERE its ranks live. Two
runs with swapped per-rank placement share a rank multiset but execute
different traffic on an asymmetric fabric; they are not equivalent.

MappingArtifact binds each rank to a concrete agent instance and,
when a fabric attachment is supplied, to its endpoint and router.
It is derived (never hand-authored), content-addressed, and fails
closed: an unplaceable rank or a partial endpoint set is refused, not
guessed. Endpoint/router identity is never inferred from a rank index.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .compile_model import AgentKind, CompileRequest, _as_int
from .placement import AgentInstance, Endpoint, NodeInventory, build_inventory

MAPPING_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/MappingArtifact"


class MappingError(ValueError):
    """Unprovable placement (fail-closed, never guessed)."""


def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise MappingError(f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise MappingError(f"{where} has unknown fields: {sorted(unknown)}")


@dataclass(frozen=True)
class RankPlacement:
    """One rank's resolved home: agent instance, and endpoint/router if known."""

    rank: int
    agent: AgentInstance
    endpoint_id: int | None = None
    router: int | None = None

    def __post_init__(self):
        _as_int("rank", self.rank, minimum=0)
        if not isinstance(self.agent, AgentInstance):
            raise MappingError(
                f"agent must be AgentInstance, got {type(self.agent).__name__}")
        if (self.endpoint_id is None) != (self.router is None):
            raise MappingError(
                "endpoint_id and router are both present or both absent")
        if self.endpoint_id is not None:
            _as_int("endpoint_id", self.endpoint_id, minimum=0)
            _as_int("router", self.router, minimum=0)

    def to_dict(self) -> dict[str, Any]:
        return {"rank": self.rank, "agent": self.agent.to_dict(),
                "endpoint_id": self.endpoint_id, "router": self.router}

    @classmethod
    def from_dict(cls, d: Any) -> RankPlacement:
        _strict_keys(d, frozenset({"rank", "agent", "endpoint_id", "router"}),
                     "placement")
        _strict_keys(d["agent"], frozenset({"kind", "index"}), "placement.agent")
        return cls(
            rank=d["rank"],
            agent=AgentInstance(kind=AgentKind(d["agent"]["kind"]),
                                index=d["agent"]["index"]),
            endpoint_id=d.get("endpoint_id"),
            router=d.get("router"),
        )


@dataclass(frozen=True)
class MappingArtifact:
    """Content-addressed rank→agent/endpoint/router placement."""

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
        ranks = [p.rank for p in self.placements]
        if ranks != list(range(len(ranks))):
            raise MappingError("placements must be contiguous from rank 0")
        if _as_int("schema_version", self.schema_version) \
                != MAPPING_SCHEMA_VERSION:
            raise MappingError(
                f"unsupported mapping schema_version {self.schema_version} "
                f"(this build implements v{MAPPING_SCHEMA_VERSION})")

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
        return {"placements": [p.to_dict() for p in self.placements],
                "mapping_hash": self.mapping_hash()}

    @classmethod
    def from_dict(cls, d: Any) -> MappingArtifact:
        _strict_keys(d, frozenset({"placements", "mapping_hash"}), "mapping")
        artifact = cls(placements=tuple(
            RankPlacement.from_dict(p) for p in d["placements"]))
        supplied = d.get("mapping_hash")
        if supplied is not None and supplied != artifact.mapping_hash():
            raise MappingError("mapping_hash does not match content")
        return artifact


def derive_mapping(cr: CompileRequest,
                   endpoints: tuple[Endpoint, ...] | None = None
                   ) -> MappingArtifact:
    """Bind every rank to a distinct compute instance, deterministically.

    Rank r takes compute instance r. If the workload has more ranks than
    compute instances the placement is infeasible and refused — never
    oversubscribed silently. When ``endpoints`` is supplied it must cover
    every rank exactly; a partial attachment is refused rather than filled
    in.
    """
    inventory = build_inventory(cr)
    compute = inventory.compute_instances
    if inventory.rank_count > len(compute):
        raise MappingError(
            f"workload needs {inventory.rank_count} ranks but the fabric "
            f"has only {len(compute)} compute instances")
    attached: dict[int, Endpoint] = {}
    if endpoints is not None:
        if not isinstance(endpoints, tuple):
            raise MappingError("endpoints must be a tuple of Endpoint")
        for e in endpoints:
            if not isinstance(e, Endpoint):
                raise MappingError(
                    f"endpoints must contain Endpoint, got {type(e).__name__}")
            if e.rank in attached:
                raise MappingError(f"duplicate endpoint for rank {e.rank}")
            attached[e.rank] = e
        expected = set(range(inventory.rank_count))
        if set(attached) != expected:
            missing = sorted(expected - set(attached))
            extra = sorted(set(attached) - expected)
            raise MappingError(
                f"endpoint attachment must cover every rank "
                f"(missing={missing}, extra={extra})")
    placements = []
    for r in inventory.ranks:
        e = attached.get(r.rank)
        placements.append(RankPlacement(
            rank=r.rank,
            agent=compute[r.rank],
            endpoint_id=e.endpoint_id if e else None,
            router=e.router if e else None,
        ))
    return MappingArtifact(placements=tuple(placements))
