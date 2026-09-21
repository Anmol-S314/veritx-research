"""veritx_dse.waved.operations — OperationGraph (D2, §15–§19, §27–§29).

One immutable deterministic operation graph per (workload, parallelism,
semantics). The graph contains EXACTLY the operations the workload
declares — nothing synthesized, nothing dropped.

Identity is the mechanical parent DAG of §23.2:

    operation_graph_id = H(workload_id, parallelism_id,
                           wave_d_semantics_id, canonical nodes,
                           canonical edges)

DAG laws (§17): every dependency references an existing node, no
self-dependency, acyclic. Repeated decode steps are explicit per-step
nodes (step index in the node), never graph cycles.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .errors import (
    InvalidInput, MappingInvalid, UnsupportedSchedule, UnsupportedSemantics,
)
from veritx_dse.core.artifact import content_hash
from veritx_dse.core.artifact import FrozenMap, ImmutableError, freeze, thaw
from .parallelism import ParallelismArtifact
from .semantics import WaveDWorkloadSemantics
from veritx_dse.core.artifact import (
    require_embedded_id, require_fields, require_schema_version, require_type_tag,
)

OPERATION_GRAPH_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/WavedOperationGraph"

# Operation kinds (§15). Only categories with a supported lowering are
# implemented; the vocabulary is closed.
KIND_COMPUTE = "COMPUTE"
KIND_COLLECTIVE = "COLLECTIVE"
KIND_P2P = "P2P"
KIND_KV_READ = "KV_READ"
KIND_KV_WRITE = "KV_WRITE"
KIND_MULTICAST = "MULTICAST"
KIND_EXPERT_DISPATCH = "EXPERT_DISPATCH"
KIND_EXPERT_COMBINE = "EXPERT_COMBINE"
OPERATION_KINDS = (
    KIND_COMPUTE, KIND_COLLECTIVE, KIND_P2P, KIND_KV_READ, KIND_KV_WRITE,
    KIND_MULTICAST, KIND_EXPERT_DISPATCH, KIND_EXPERT_COMBINE,
)

# Collective kinds with a pinned v1 schedule (§21).
COLLECTIVE_KINDS = ("ALLREDUCE", "REDUCESCATTER", "ALLGATHER", "ALLTOALL",
                    "BROADCAST")
SCHEDULES = {
    "ALLREDUCE": "RING",
    "REDUCESCATTER": "RING",
    "ALLGATHER": "RING",
    "ALLTOALL": "DIRECT",
    "BROADCAST": "ROOT_FANOUT",
}
REPLICATION_SOURCE = "SOURCE_REPLICATION"


def _require(cond: bool, code_exc: Exception) -> None:
    if not cond:
        raise code_exc


@dataclass(frozen=True)
class CollectiveIntent:
    """WHAT is communicated (§20): kind + participants + per-kind payload.

    Payload meaning is per-kind (§10.1): input tensor bytes per rank for
    ALLREDUCE/REDUCESCATTER, local contribution per rank for ALLGATHER,
    total input per rank for ALLTOALL, root payload for BROADCAST.
    """

    kind: str
    participants: tuple[int, ...]
    payload_bytes: int
    collective_id: str

    def __post_init__(self) -> None:
        if self.kind not in COLLECTIVE_KINDS:
            raise UnsupportedSchedule(
                f"collective kind {self.kind!r} has no supported schedule "
                f"(supported: {COLLECTIVE_KINDS})")
        _require(len(self.participants) >= 2, UnsupportedSemantics(
            f"a one-member collective intent is never represented "
            f"(got {len(self.participants)} participants, §10.3)"))
        _require(all(type(p) is int and p >= 0 for p in self.participants),
                 InvalidInput("participant ranks must be non-negative ints"))
        _require(len(set(self.participants)) == len(self.participants),
                 InvalidInput("duplicate participant ranks"))
        _require(type(self.payload_bytes) is int and self.payload_bytes > 0,
                 InvalidInput("payload_bytes must be a positive int"))
        _require(isinstance(self.collective_id, str)
                 and self.collective_id, InvalidInput("collective_id needed"))

    @property
    def k(self) -> int:
        return len(self.participants)

    @property
    def algorithm(self) -> str:
        return SCHEDULES[self.kind]

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "participants": list(self.participants),
                "payload_bytes": self.payload_bytes,
                "collective_id": self.collective_id}


@dataclass(frozen=True)
class P2PTransfer:
    """One semantic transfer = one object = one logical message (§18)."""

    src_rank: int
    dst_rank: int
    payload_bytes: int
    transfer_id: str

    def __post_init__(self) -> None:
        _require(type(self.src_rank) is int and self.src_rank >= 0,
                 InvalidInput("src_rank must be a non-negative int"))
        _require(type(self.dst_rank) is int and self.dst_rank >= 0,
                 InvalidInput("dst_rank must be a non-negative int"))
        _require(self.src_rank != self.dst_rank, InvalidInput(
            "a self-transfer is not a network transfer"))
        _require(type(self.payload_bytes) is int and self.payload_bytes > 0,
                 InvalidInput("payload_bytes must be a positive int"))
        _require(isinstance(self.transfer_id, str) and self.transfer_id,
                 InvalidInput("transfer_id needed"))

    def to_dict(self) -> dict[str, Any]:
        return {"src_rank": self.src_rank, "dst_rank": self.dst_rank,
                "payload_bytes": self.payload_bytes,
                "transfer_id": self.transfer_id}


@dataclass(frozen=True)
class MulticastIntent:
    """One payload, N declared destinations (§27)."""

    source_rank: int
    destinations: tuple[int, ...]
    payload_bytes: int
    replication: str
    multicast_id: str

    def __post_init__(self) -> None:
        _require(type(self.source_rank) is int and self.source_rank >= 0,
                 InvalidInput("source_rank must be a non-negative int"))
        _require(bool(self.destinations), InvalidInput(
            "multicast needs at least one destination"))
        _require(all(type(dd) is int and dd >= 0 for dd in self.destinations),
                 InvalidInput("destination ranks must be non-negative ints"))
        _require(len(set(self.destinations)) == len(self.destinations),
                 InvalidInput("duplicate destination ranks"))
        _require(self.source_rank not in self.destinations, InvalidInput(
            "source is not its own destination"))
        _require(type(self.payload_bytes) is int and self.payload_bytes > 0,
                 InvalidInput("payload_bytes must be a positive int"))
        if self.replication != REPLICATION_SOURCE:
            raise UnsupportedSemantics(
                f"replication {self.replication!r} is unsupported in v1 "
                f"(only {REPLICATION_SOURCE}); hardware/network replication "
                "must refuse, never be substituted")
        _require(isinstance(self.multicast_id, str) and self.multicast_id,
                 InvalidInput("multicast_id needed"))

    @property
    def n(self) -> int:
        return len(self.destinations)

    def to_dict(self) -> dict[str, Any]:
        return {"source_rank": self.source_rank,
                "destinations": list(self.destinations),
                "payload_bytes": self.payload_bytes,
                "replication": self.replication,
                "multicast_id": self.multicast_id}


@dataclass(frozen=True)
class OperationNode:
    """One graph node: exactly one declared operation.

    ``detail`` is the canonical per-kind payload (dict of typed values)
    consumed by lowering; ``step`` distinguishes repeated decode
    instances (identity-bearing; cycles are forbidden).
    """

    operation_id: str
    kind: str
    phase: str
    owner: int                    # owning rank
    step: int
    deps: tuple[str, ...]
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require(isinstance(self.operation_id, str) and self.operation_id,
                 InvalidInput("operation_id needed"))
        _require(self.kind in OPERATION_KINDS, UnsupportedSemantics(
            f"operation kind {self.kind!r} outside the Wave-D vocabulary"))
        _require(self.phase in ("PREFILL", "DECODE"), InvalidInput(
            f"phase must be PREFILL or DECODE, got {self.phase!r}"))
        _require(type(self.owner) is int and self.owner >= 0,
                 InvalidInput("owner must be a non-negative rank"))
        _require(type(self.step) is int and self.step >= 0,
                 InvalidInput("step must be a non-negative int"))
        _require(isinstance(self.deps, tuple), InvalidInput(
            "deps must be a tuple of operation ids"))
        if not isinstance(self.detail, (dict, FrozenMap)):
            raise InvalidInput("detail must be a canonical dict")
        try:
            object.__setattr__(self, "detail", freeze(self.detail))
        except ImmutableError as exc:
            raise InvalidInput(f"detail is not canonical: {exc}") from None

    def canonical(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id, "kind": self.kind,
            "phase": self.phase, "owner": self.owner, "step": self.step,
            "deps": list(self.deps), "detail": thaw(self.detail),
        }


@dataclass(frozen=True)
class OperationGraph:
    """Immutable DAG of declared operations + canonical intents."""

    parallelism: ParallelismArtifact
    semantics: WaveDWorkloadSemantics
    workload_id: str
    nodes: tuple[OperationNode, ...]
    collectives: tuple[CollectiveIntent, ...] = ()
    p2p_transfers: tuple[P2PTransfer, ...] = ()
    multicasts: tuple[MulticastIntent, ...] = ()
    schema_version: int = OPERATION_GRAPH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.parallelism, ParallelismArtifact):
            raise InvalidInput("parallelism must be a ParallelismArtifact")
        if not isinstance(self.semantics, WaveDWorkloadSemantics):
            raise InvalidInput("semantics must be a WaveDWorkloadSemantics")
        if not isinstance(self.workload_id, str) or not self.workload_id:
            raise InvalidInput("workload_id must be a non-empty string")
        if not isinstance(self.nodes, tuple) or not self.nodes:
            raise InvalidInput("nodes must be a non-empty tuple")
        R = self.parallelism.world_size
        by_id: dict[str, OperationNode] = {}
        for n in self.nodes:
            if n.operation_id in by_id:
                raise InvalidInput(
                    f"duplicate operation_id {n.operation_id!r}")
            if n.owner >= R:
                raise MappingInvalid(
                    f"operation {n.operation_id!r} owner rank {n.owner} "
                    f"outside rank space [0, {R})")
            by_id[n.operation_id] = n
        # Read-only index over a dict no one else holds a reference to:
        # the node objects themselves are frozen, so the graph content
        # cannot be mutated after construction.
        object.__setattr__(self, "_by_id", MappingProxyType(by_id))

        # Dependency laws (§17)
        for n in self.nodes:
            for dep in n.deps:
                if dep not in by_id:
                    raise InvalidInput(
                        f"operation {n.operation_id!r} depends on unknown "
                        f"operation {dep!r}")
                if dep == n.operation_id:
                    raise InvalidInput(
                        f"operation {n.operation_id!r} depends on itself")
        # Acyclicity (iterative DFS, deterministic order)
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n.operation_id: WHITE for n in self.nodes}
        for start in self.nodes:
            if color[start.operation_id] != WHITE:
                continue
            stack: list[tuple[str, tuple[str, ...], int]] = \
                [(start.operation_id, start.deps, 0)]
            color[start.operation_id] = GRAY
            while stack:
                nid, deps, i = stack.pop()
                if i < len(deps):
                    stack.append((nid, deps, i + 1))
                    d = deps[i]
                    if color[d] == GRAY:
                        raise InvalidInput(
                            f"operation graph has a cycle through {d!r}")
                    if color[d] == WHITE:
                        color[d] = GRAY
                        stack.append((d, by_id[d].deps, 0))
                else:
                    color[nid] = BLACK

        # Intent rank-space checks
        for ci in self.collectives:
            for p in ci.participants:
                if p >= R:
                    raise MappingInvalid(
                        f"collective {ci.collective_id!r} participant rank "
                        f"{p} outside rank space [0, {R})")
        for tr in self.p2p_transfers:
            for r in (tr.src_rank, tr.dst_rank):
                if r >= R:
                    raise MappingInvalid(
                        f"P2P transfer {tr.transfer_id!r} rank {r} outside "
                        f"rank space [0, {R})")
        for mc in self.multicasts:
            if mc.source_rank >= R or any(d >= R for d in mc.destinations):
                raise MappingInvalid(
                    f"multicast {mc.multicast_id!r} ranks outside rank "
                    f"space [0, {R})")

    # ── identity (§16) ────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "workload_id": self.workload_id,
            "parallelism_id": self.parallelism.parallelism_id(),
            "wave_d_semantics_id": self.semantics.semantics_id(),
            "nodes": [n.canonical() for n in self.nodes],
            "collectives": [c.to_dict() for c in self.collectives],
            "p2p_transfers": [t.to_dict() for t in self.p2p_transfers],
            "multicasts": [m.to_dict() for m in self.multicasts],
        }

    def operation_graph_id(self) -> str:
        return content_hash(_HASH_TYPE_TAG, self.schema_version,
                            self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_dict(),
                "operation_graph_id": self.operation_graph_id()}

    def node(self, operation_id: str) -> OperationNode:
        return self._by_id[operation_id]

    # ── strict parsing (persisted-resource contract) ──────────────────
    @classmethod
    def from_dict(cls, d: Any, *, parallelism: ParallelismArtifact,
                  semantics: WaveDWorkloadSemantics,
                  strict: bool = False) -> "OperationGraph":
        """Rebuild a graph; parents are supplied, never trusted from JSON.

        In strict mode the embedded parent IDs are REQUIRED and must
        equal the verified parents, and the embedded
        ``operation_graph_id`` must equal the recomputed one.
        """
        require_fields(d, {
            "type", "schema_version", "workload_id", "parallelism_id",
            "wave_d_semantics_id", "nodes", "collectives",
            "p2p_transfers", "multicasts", "operation_graph_id",
        }, "operation graph")
        if strict:
            require_type_tag(d, _HASH_TYPE_TAG, "operation graph")
            require_schema_version(d, OPERATION_GRAPH_SCHEMA_VERSION,
                                   "operation graph")
            for key in ("workload_id", "parallelism_id",
                        "wave_d_semantics_id", "nodes", "collectives",
                        "p2p_transfers", "multicasts",
                        "operation_graph_id"):
                if key not in d:
                    raise InvalidInput(
                        f"persisted operation graph is missing {key!r}")
            if d["parallelism_id"] != parallelism.parallelism_id():
                raise InvalidInput(
                    "operation graph parallelism_id does not match the "
                    "verified parallelism parent")
            if d["wave_d_semantics_id"] != semantics.semantics_id():
                raise InvalidInput(
                    "operation graph wave_d_semantics_id does not match "
                    "the verified semantics parent")
        elif "type" in d and d["type"] != _HASH_TYPE_TAG:
            raise InvalidInput(
                f"operation graph type tag {d['type']!r} is not "
                f"{_HASH_TYPE_TAG!r}")

        nodes = tuple(_node_from_dict(n) for n in d["nodes"])
        collectives = tuple(_collective_from_dict(c)
                            for c in d["collectives"])
        p2p = tuple(_p2p_from_dict(t) for t in d["p2p_transfers"])
        multicasts = tuple(_multicast_from_dict(m)
                           for m in d["multicasts"])
        graph = cls(parallelism=parallelism, semantics=semantics,
                    workload_id=d["workload_id"], nodes=nodes,
                    collectives=collectives, p2p_transfers=p2p,
                    multicasts=multicasts,
                    schema_version=d.get("schema_version",
                                         OPERATION_GRAPH_SCHEMA_VERSION))
        if strict:
            require_embedded_id(d, "operation_graph_id",
                                graph.operation_graph_id(),
                                "operation graph")
        elif d.get("operation_graph_id") not in (
                None, graph.operation_graph_id()):
            raise InvalidInput(
                "operation_graph_id does not match content")
        return graph


def _node_from_dict(d: Any) -> OperationNode:
    require_fields(d, {"operation_id", "kind", "phase", "owner", "step",
                       "deps", "detail"}, "operation node")
    for key in ("operation_id", "kind", "phase", "owner", "step",
                "deps"):
        if key not in d:
            raise InvalidInput(f"operation node is missing {key!r}")
    deps = d["deps"]
    if not isinstance(deps, list):
        raise InvalidInput("operation node deps must be a list")
    return OperationNode(operation_id=d["operation_id"], kind=d["kind"],
                         phase=d["phase"], owner=d["owner"],
                         step=d["step"], deps=tuple(deps),
                         detail=d.get("detail") or {})


def _collective_from_dict(d: Any) -> CollectiveIntent:
    require_fields(d, {"kind", "participants", "payload_bytes",
                       "collective_id"}, "collective intent")
    for key in ("kind", "participants", "payload_bytes",
                "collective_id"):
        if key not in d:
            raise InvalidInput(f"collective intent is missing {key!r}")
    if not isinstance(d["participants"], list):
        raise InvalidInput("collective participants must be a list")
    return CollectiveIntent(kind=d["kind"],
                            participants=tuple(d["participants"]),
                            payload_bytes=d["payload_bytes"],
                            collective_id=d["collective_id"])


def _p2p_from_dict(d: Any) -> P2PTransfer:
    require_fields(d, {"src_rank", "dst_rank", "payload_bytes",
                       "transfer_id"}, "P2P transfer")
    for key in ("src_rank", "dst_rank", "payload_bytes", "transfer_id"):
        if key not in d:
            raise InvalidInput(f"P2P transfer is missing {key!r}")
    return P2PTransfer(src_rank=d["src_rank"], dst_rank=d["dst_rank"],
                       payload_bytes=d["payload_bytes"],
                       transfer_id=d["transfer_id"])


def _multicast_from_dict(d: Any) -> MulticastIntent:
    require_fields(d, {"source_rank", "destinations", "payload_bytes",
                       "replication", "multicast_id"}, "multicast intent")
    for key in ("source_rank", "destinations", "payload_bytes",
                "replication", "multicast_id"):
        if key not in d:
            raise InvalidInput(f"multicast intent is missing {key!r}")
    if not isinstance(d["destinations"], list):
        raise InvalidInput("multicast destinations must be a list")
    return MulticastIntent(source_rank=d["source_rank"],
                           destinations=tuple(d["destinations"]),
                           payload_bytes=d["payload_bytes"],
                           replication=d["replication"],
                           multicast_id=d["multicast_id"])


__all__ = [
    "COLLECTIVE_KINDS", "CollectiveIntent", "KIND_COLLECTIVE",
    "KIND_COMPUTE", "KIND_EXPERT_COMBINE", "KIND_EXPERT_DISPATCH",
    "KIND_KV_READ", "KIND_KV_WRITE", "KIND_MULTICAST", "KIND_P2P",
    "MulticastIntent", "OPERATION_KINDS", "OPERATION_GRAPH_SCHEMA_VERSION",
    "OperationGraph", "OperationNode", "P2PTransfer", "REPLICATION_SOURCE",
    "SCHEDULES",
]
