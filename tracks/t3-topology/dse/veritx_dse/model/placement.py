"""veritx_dse.model.placement — node semantics (Wave B2).

"node" was overloaded: a Workload rank, a CompileRequest agent, a BookSim
node, and an RTL router are four different objects. Sizing a fabric off
the wrong one is exactly how a 4-active-rank workload came to share a
name with a 64-router fabric.

This module names the universes:

    AgentGroup (Agent: kind, count)
        ↓ expand
    AgentInstance            — one hardware agent
    LogicalRank              — one model rank, as 4D parallel coords
    NodeInventory            — the explicit counts, never one integer

Rank→agent binding and any endpoint/router attachment are NOT here: that
is MappingArtifact, so placement can never be inferred from a name.
"""
from __future__ import annotations

from dataclasses import dataclass

from .compile_model import AgentKind, CompileRequest, _as_enum, _as_int

# Canonical rank flattening: tp varies fastest, then ep, then dp, then pp
# slowest. One place defines this order; no caller may assume another.
_RANK_ORDER = ("tp", "ep", "dp", "pp")


def rank_of(tp_i: int, pp_i: int, ep_i: int, dp_i: int, *,
            tp: int, pp: int, ep: int, dp: int) -> int:
    """Global rank from 4D coordinates under the canonical order."""
    _as_int("pp", pp, minimum=1)
    if not 0 <= pp_i < pp:
        raise ValueError(f"pp coord {pp_i} outside pp={pp}")
    return ((pp_i * dp + dp_i) * ep + ep_i) * tp + tp_i


def coords_of(rank: int, *, tp: int, pp: int, ep: int, dp: int) -> dict[str, int]:
    """Inverse of rank_of: 4D coordinates for a global rank."""
    _as_int("rank", rank, minimum=0)
    tp_i = rank % tp
    rest = rank // tp
    ep_i = rest % ep
    rest //= ep
    dp_i = rest % dp
    pp_i = rest // dp
    if pp_i >= pp:
        raise ValueError(
            f"rank {rank} outside tp={tp} pp={pp} ep={ep} dp={dp} world")
    return {"tp": tp_i, "pp": pp_i, "ep": ep_i, "dp": dp_i}


@dataclass(frozen=True)
class AgentInstance:
    """One concrete hardware agent, expanded from an Agent group."""

    kind: AgentKind
    index: int  # 0-based within its AgentGroup

    def __post_init__(self):
        _as_enum("kind", self.kind, AgentKind)
        _as_int("index", self.index, minimum=0)

    @property
    def instance_id(self) -> str:
        return f"{self.kind.value}[{self.index}]"

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind.value, "index": self.index}


@dataclass(frozen=True)
class LogicalRank:
    """One model rank as parallelism coordinates + its global rank."""

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

    agent_count   — hardware agents the fabric carries
    rank_count    — model ranks the workload must place
    compute_instances — agents a rank may occupy

    These are deliberately separate properties. A fabric may carry more
    compute instances than active ranks (or fewer, which is infeasible);
    that fact is now visible instead of hidden behind one "nodes" integer.
    """

    agents: tuple[AgentInstance, ...]
    ranks: tuple[LogicalRank, ...]

    def __post_init__(self):
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
        if [r.rank for r in self.ranks] != list(range(len(self.ranks))):
            raise ValueError("ranks must be contiguous from 0 with no gaps")

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
            "agents": [a.to_dict() for a in self.agents],
            "ranks": [r.to_dict() for r in self.ranks],
        }


def build_inventory(cr: CompileRequest) -> NodeInventory:
    """Expand agent groups and workload parallelism into explicit nodes."""
    agents: list[AgentInstance] = []
    for group in cr.agents:
        for i in range(group.count):
            agents.append(AgentInstance(kind=group.kind, index=i))
    ranks: list[LogicalRank] = []
    w = cr.workload
    for pp_i in range(w.pp):
        for dp_i in range(w.dp):
            for ep_i in range(w.ep):
                for tp_i in range(w.tp):
                    rank = rank_of(tp_i, pp_i, ep_i, dp_i,
                                   tp=w.tp, pp=w.pp, ep=w.ep, dp=w.dp)
                    ranks.append(LogicalRank(rank=rank, tp=tp_i, pp=pp_i,
                                             ep=ep_i, dp=dp_i))
    ranks.sort(key=lambda r: r.rank)
    return NodeInventory(agents=tuple(agents), ranks=tuple(ranks))
