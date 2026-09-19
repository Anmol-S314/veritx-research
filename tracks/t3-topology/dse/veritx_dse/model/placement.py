"""veritx_dse.model.placement — node semantics (Wave B2).

"node" was overloaded: a Workload rank, a CompileRequest agent, a BookSim
node, and an RTL router are four different objects. Sizing a fabric off
the wrong one is exactly how a 4-active-rank workload came to share a
name with a 64-router fabric.

This module names the universes:

    AgentGroup (Agent: kind, count)
        ↓ expand
    AgentInstance            — one hardware agent, globally unambiguous
    LogicalRank              — one model rank, as 4D parallel coords
    NodeInventory            — the explicit counts, never one integer

A B2 MappingArtifact binds LogicalRank → AgentInstance only. Fabric
attachment (agent → endpoint → router) is a B3 relationship and is
deliberately absent here.

Canonical design-rank ordering: tp varies fastest, then ep, then dp,
then pp slowest. This defines the Srota DESIGN rank namespace only. It
does NOT yet prove that a trace rank, an ASTRA rank, or an LLMServingSim
rank uses the same assignment — that executed-rank equivalence belongs to
backend workload lowering.
"""
from __future__ import annotations

from dataclasses import dataclass

from .compile_model import AgentKind, CompileRequest, _as_enum, _as_int


@dataclass(frozen=True)
class ParallelismShape:
    """The 4D parallelism dimensions a rank namespace is defined over.

    Fields are SIZES (each >= 1), not coordinate indices.
    """

    tp: int
    pp: int
    ep: int
    dp: int

    def __post_init__(self):
        for name in ("tp", "pp", "ep", "dp"):
            _as_int(name, getattr(self, name), minimum=1)

    @property
    def world_size(self) -> int:
        return self.tp * self.pp * self.ep * self.dp

    def to_dict(self) -> dict[str, int]:
        return {"tp": self.tp, "pp": self.pp, "ep": self.ep, "dp": self.dp}


def _dimension(name: str, value: object) -> int:
    return _as_int(name, value, minimum=1)


def _coordinate(name: str, value: object, size: int) -> int:
    _as_int(name, value, minimum=0)
    if value >= size:
        raise ValueError(f"{name} coordinate {value} outside {name}={size}")
    return value


def rank_of(tp_i: int, pp_i: int, ep_i: int, dp_i: int, *,
            tp: int, pp: int, ep: int, dp: int) -> int:
    """Global rank from 4D coordinates under the canonical order."""
    _dimension("tp", tp)
    _dimension("pp", pp)
    _dimension("ep", ep)
    _dimension("dp", dp)
    _coordinate("tp", tp_i, tp)
    _coordinate("pp", pp_i, pp)
    _coordinate("ep", ep_i, ep)
    _coordinate("dp", dp_i, dp)
    return ((pp_i * dp + dp_i) * ep + ep_i) * tp + tp_i


def coords_of(rank: int, *, tp: int, pp: int, ep: int,
              dp: int) -> dict[str, int]:
    """Inverse of rank_of: 4D coordinates for a global rank."""
    _dimension("tp", tp)
    _dimension("pp", pp)
    _dimension("ep", ep)
    _dimension("dp", dp)
    _as_int("rank", rank, minimum=0)
    world = tp * pp * ep * dp
    if rank >= world:
        raise ValueError(f"rank {rank} outside world_size={world}")
    tp_i = rank % tp
    rest = rank // tp
    ep_i = rest % ep
    rest //= ep
    dp_i = rest % dp
    pp_i = rest // dp
    return {"tp": tp_i, "pp": pp_i, "ep": ep_i, "dp": dp_i}


@dataclass(frozen=True)
class AgentInstance:
    """One concrete hardware agent, uniquely identified in a design.

    ``group_index`` is the ordered position of the source Agent group in
    CompileRequest.agents; that order is semantic because
    AddressRange.target_agent_idx indexes it. Two Agent groups of the
    same kind therefore never collide, because the group index is part
    of the identity.
    """

    group_index: int
    instance_index: int
    kind: AgentKind

    def __post_init__(self):
        _as_int("group_index", self.group_index, minimum=0)
        _as_int("instance_index", self.instance_index, minimum=0)
        _as_enum("kind", self.kind, AgentKind)

    @property
    def instance_id(self) -> str:
        return (f"agent_group[{self.group_index}]/"
                f"{self.kind.value}[{self.instance_index}]")

    def to_dict(self) -> dict[str, object]:
        return {"group_index": self.group_index,
                "instance_index": self.instance_index,
                "kind": self.kind.value}


@dataclass(frozen=True)
class LogicalRank:
    """One model rank: global rank id + its parallelism coordinate indices.

    ``rank`` is the global id; ``tp``/``pp``/``ep``/``dp`` are COORDINATES
    (indices into the shape), never the shape sizes.
    """

    rank: int
    tp: int
    pp: int
    ep: int
    dp: int

    def __post_init__(self):
        for name in ("rank", "tp", "pp", "ep", "dp"):
            _as_int(name, getattr(self, name), minimum=0)

    def to_dict(self) -> dict[str, int]:
        return {"rank": self.rank, "tp": self.tp, "pp": self.pp,
                "ep": self.ep, "dp": self.dp}


@dataclass(frozen=True)
class NodeInventory:
    """The explicit node universes, side by side.

    agent_count        — hardware agents the fabric carries
    rank_count         — model ranks the workload must place
    compute_instances  — agents a rank may occupy

    Self-checking: agent identities are unique, the rank namespace is
    exactly [0, world_size), and every rank's stored coordinates match
    the declared parallelism shape.
    """

    parallelism: ParallelismShape
    agents: tuple[AgentInstance, ...]
    ranks: tuple[LogicalRank, ...]

    def __post_init__(self):
        if not isinstance(self.parallelism, ParallelismShape):
            raise ValueError(
                f"parallelism must be ParallelismShape, got "
                f"{type(self.parallelism).__name__}")
        if not isinstance(self.agents, tuple):
            raise ValueError("agents must be a tuple of AgentInstance")
        if not isinstance(self.ranks, tuple):
            raise ValueError("ranks must be a tuple of LogicalRank")
        for a in self.agents:
            if not isinstance(a, AgentInstance):
                raise ValueError(
                    f"agents must contain AgentInstance, got {type(a).__name__}")
        for r in self.ranks:
            if not isinstance(r, LogicalRank):
                raise ValueError(
                    f"ranks must contain LogicalRank, got {type(r).__name__}")

        ids = [a.instance_id for a in self.agents]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate agent instance identity in inventory")

        world = self.parallelism.world_size
        if len(self.ranks) != world:
            raise ValueError(
                f"ranks count {len(self.ranks)} != parallelism world_size {world}")
        if [r.rank for r in self.ranks] != list(range(world)):
            raise ValueError("ranks must be contiguous from 0 with no gaps")
        shape = self.parallelism
        for r in self.ranks:
            expected = coords_of(r.rank, tp=shape.tp, pp=shape.pp,
                                 ep=shape.ep, dp=shape.dp)
            stored = {"tp": r.tp, "pp": r.pp, "ep": r.ep, "dp": r.dp}
            if stored != expected:
                raise ValueError(
                    f"rank {r.rank} stores coordinates {stored} but canonical "
                    f"coordinates for this shape are {expected}")

    @property
    def agent_count(self) -> int:
        return len(self.agents)

    @property
    def rank_count(self) -> int:
        return len(self.ranks)

    @property
    def compute_instances(self) -> tuple[AgentInstance, ...]:
        return tuple(a for a in self.agents if a.kind == AgentKind.COMPUTE_TILE)

    def instances_of(self, kind: AgentKind) -> tuple[AgentInstance, ...]:
        _as_enum("kind", kind, AgentKind)
        return tuple(a for a in self.agents if a.kind == kind)

    def to_dict(self) -> dict[str, object]:
        return {
            "parallelism": self.parallelism.to_dict(),
            "agents": [a.to_dict() for a in self.agents],
            "ranks": [r.to_dict() for r in self.ranks],
        }


def build_inventory(cr: CompileRequest) -> NodeInventory:
    """Expand agent groups and workload parallelism into explicit nodes."""
    shape = ParallelismShape(
        tp=cr.workload.tp,
        pp=cr.workload.pp,
        ep=cr.workload.ep,
        dp=cr.workload.dp,
    )
    agents = tuple(
        AgentInstance(group_index=group_index, instance_index=instance_index,
                      kind=group.kind)
        for group_index, group in enumerate(cr.agents)
        for instance_index in range(group.count)
    )
    # One arithmetic source: coords_of is the inverse of rank_of.
    ranks = tuple(
        LogicalRank(rank=rank,
                    **coords_of(rank, tp=shape.tp, pp=shape.pp,
                                ep=shape.ep, dp=shape.dp))
        for rank in range(shape.world_size)
    )
    return NodeInventory(parallelism=shape, agents=agents, ranks=ranks)
