"""veritx_dse.workload.graph — the explicit Wave-D semantic workload.

This is the smallest versioned input seam that lets a product intent
declare WHAT is communicated, rather than shipping a packet trace and
hoping the semantics can be reverse-engineered (they cannot — a trace
has no operation ids, no phase and no collective kind).

    WaveDWorkload = parallelism + semantics + declared operations

Every operation is explicit: a collective (kind, participants, payload),
a P2P transfer (src, dst, payload) or a multicast (source, destinations,
payload, replication). Nothing is inferred from model shape.

``workload_id`` is the content hash of exactly that declaration. The
OperationGraph built from it binds the same content plus its parents, so
the chain

    WaveDWorkload → OperationGraph → LogicalMessageArtifact
                  → PhysicalTrafficArtifact

is fully content-addressed from the declared workload down to the wire.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from veritx_dse.core.errors import InvalidInput
from veritx_dse.core.artifact import content_hash
from veritx_dse.core.artifact import FrozenMap, ImmutableError, freeze, thaw
from .operations import (
    KIND_COLLECTIVE, KIND_MULTICAST, KIND_P2P, CollectiveIntent,
    MulticastIntent, OperationGraph, OperationNode, P2PTransfer,
)
from veritx_dse.model.parallelism import ParallelismArtifact
from .semantics import WaveDWorkloadSemantics
from veritx_dse.core.artifact import (
    require_embedded_id, require_fields, require_schema_version, require_type_tag,
)

WAVED_WORKLOAD_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/WaveDWorkload"

# The closed set of declared operation kinds a Wave-D workload may carry.
WAVED_OPERATION_KINDS = (KIND_COLLECTIVE, KIND_P2P, KIND_MULTICAST)

_DETAIL_FIELDS = {
    KIND_COLLECTIVE: {"collective_id", "collective_kind", "participants",
                      "payload_bytes"},
    KIND_P2P: {"transfer_id", "src_rank", "dst_rank", "payload_bytes"},
    KIND_MULTICAST: {"multicast_id", "source_rank", "destinations",
                     "payload_bytes", "replication"},
}


@dataclass(frozen=True)
class WaveDOperation:
    """One declared operation (semantic content, not a scheduling hint)."""

    operation_id: str
    kind: str
    owner: int
    phase: str
    step: int
    deps: tuple[str, ...]
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, str) or not self.operation_id:
            raise InvalidInput("operation_id must be a non-empty string")
        if self.kind not in WAVED_OPERATION_KINDS:
            raise InvalidInput(
                f"wave_d operation kind {self.kind!r} outside "
                f"{WAVED_OPERATION_KINDS}")
        if type(self.owner) is not int or isinstance(self.owner, bool) \
                or self.owner < 0:
            raise InvalidInput("owner must be a non-negative rank")
        if self.phase not in ("PREFILL", "DECODE"):
            raise InvalidInput(
                f"phase must be PREFILL or DECODE, got {self.phase!r}")
        if type(self.step) is not int or isinstance(self.step, bool) \
                or self.step < 0:
            raise InvalidInput("step must be a non-negative int")
        if not isinstance(self.deps, tuple):
            raise InvalidInput("deps must be a tuple of operation ids")
        if not isinstance(self.detail, (dict, FrozenMap)):
            raise InvalidInput("detail must be an object")
        allowed = _DETAIL_FIELDS[self.kind]
        unknown = set(self.detail) - allowed
        if unknown:
            raise InvalidInput(
                f"{self.kind} operation {self.operation_id!r} has unknown "
                f"detail fields {sorted(unknown)}")
        try:
            object.__setattr__(self, "detail", freeze(self.detail))
        except ImmutableError as exc:
            raise InvalidInput(
                f"operation detail is not canonical: {exc}") from None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id, "kind": self.kind,
            "owner": self.owner, "phase": self.phase, "step": self.step,
            "deps": list(self.deps), "detail": thaw(self.detail),
        }


def _operation_from_dict(d: Any) -> WaveDOperation:
    require_fields(d, {"operation_id", "kind", "owner", "phase", "step",
                       "deps", "detail"}, "wave_d operation")
    for key in ("operation_id", "kind", "owner", "phase", "step", "deps",
                "detail"):
        if key not in d:
            raise InvalidInput(f"wave_d operation is missing {key!r}")
    if not isinstance(d["deps"], list):
        raise InvalidInput("wave_d operation deps must be a list")
    if not isinstance(d["detail"], dict):
        raise InvalidInput("wave_d operation detail must be an object")
    return WaveDOperation(
        operation_id=d["operation_id"], kind=d["kind"], owner=d["owner"],
        phase=d["phase"], step=d["step"], deps=tuple(d["deps"]),
        detail=d["detail"])


@dataclass(frozen=True)
class WaveDWorkload:
    """One explicit, versioned Wave-D semantic workload declaration."""

    parallelism: ParallelismArtifact
    semantics: WaveDWorkloadSemantics
    operations: tuple[WaveDOperation, ...]
    schema_version: int = WAVED_WORKLOAD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.parallelism, ParallelismArtifact):
            raise InvalidInput(
                "parallelism must be a ParallelismArtifact")
        if not isinstance(self.semantics, WaveDWorkloadSemantics):
            raise InvalidInput(
                "semantics must be a WaveDWorkloadSemantics")
        if not isinstance(self.operations, tuple) or not self.operations:
            raise InvalidInput(
                "a wave_d workload must declare at least one operation")
        seen: set[str] = set()
        for op in self.operations:
            if not isinstance(op, WaveDOperation):
                raise InvalidInput(
                    "operations must contain WaveDOperation records")
            if op.operation_id in seen:
                raise InvalidInput(
                    f"duplicate wave_d operation_id {op.operation_id!r}")
            seen.add(op.operation_id)
        for op in self.operations:
            for dep in op.deps:
                if dep not in seen:
                    raise InvalidInput(
                        f"wave_d operation {op.operation_id!r} depends on "
                        f"unknown operation {dep!r}")

    # ── identity ──────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "parallelism_id": self.parallelism.parallelism_id(),
            "wave_d_semantics_id": self.semantics.semantics_id(),
            "operations": [op.to_dict() for op in self.operations],
        }

    def workload_id(self) -> str:
        return content_hash(_HASH_TYPE_TAG, self.schema_version,
                            self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_dict(), "workload_id": self.workload_id()}

    # ── lowering to the graph (one declared op → one node) ────────────
    def to_graph(self) -> OperationGraph:
        nodes: list[OperationNode] = []
        collectives: list[CollectiveIntent] = []
        p2p: list[P2PTransfer] = []
        multicasts: list[MulticastIntent] = []
        for op in self.operations:
            detail = thaw(op.detail)
            if op.kind == KIND_COLLECTIVE:
                link = {"collective_id": detail["collective_id"]}
                collectives.append(CollectiveIntent(
                    kind=detail["collective_kind"],
                    participants=tuple(detail["participants"]),
                    payload_bytes=detail["payload_bytes"],
                    collective_id=detail["collective_id"]))
            elif op.kind == KIND_P2P:
                link = {"transfer_id": detail["transfer_id"]}
                p2p.append(P2PTransfer(
                    src_rank=detail["src_rank"], dst_rank=detail["dst_rank"],
                    payload_bytes=detail["payload_bytes"],
                    transfer_id=detail["transfer_id"]))
            else:
                link = {"multicast_id": detail["multicast_id"]}
                multicasts.append(MulticastIntent(
                    source_rank=detail["source_rank"],
                    destinations=tuple(detail["destinations"]),
                    payload_bytes=detail["payload_bytes"],
                    replication=detail["replication"],
                    multicast_id=detail["multicast_id"]))
            nodes.append(OperationNode(
                operation_id=op.operation_id, kind=op.kind, phase=op.phase,
                owner=op.owner, step=op.step, deps=op.deps, detail=link))
        return OperationGraph(
            parallelism=self.parallelism, semantics=self.semantics,
            workload_id=self.workload_id(), nodes=tuple(nodes),
            collectives=tuple(collectives), p2p_transfers=tuple(p2p),
            multicasts=tuple(multicasts))

    # ── parsing ───────────────────────────────────────────────────────
    @classmethod
    def from_dict(cls, d: Any, *,
                  parallelism: ParallelismArtifact | None = None,
                  semantics: WaveDWorkloadSemantics | None = None,
                  strict: bool = False) -> "WaveDWorkload":
        """Parse a workload document.

        Two forms, deliberately separated:

        * authoring form (``strict=False``, no parents supplied): the
          document carries inline ``parallelism``/``semantics`` objects;
        * persisted form (``strict=True``, parents supplied): the
          document carries parent IDs only and the verified parents are
          passed in by the loader — parent documents are never trusted
          out of the JSON.
        """
        require_fields(d, {
            "type", "schema_version", "parallelism", "semantics",
            "operations", "parallelism_id", "wave_d_semantics_id",
            "workload_id",
        }, "wave_d workload")
        if strict:
            require_type_tag(d, _HASH_TYPE_TAG, "wave_d workload")
            require_schema_version(d, WAVED_WORKLOAD_SCHEMA_VERSION,
                                   "wave_d workload")
            for key in ("operations", "parallelism_id",
                        "wave_d_semantics_id", "workload_id"):
                if key not in d:
                    raise InvalidInput(
                        f"persisted wave_d workload is missing {key!r}")
            if "parallelism" in d or "semantics" in d:
                raise InvalidInput(
                    "persisted wave_d workload must reference its parents "
                    "by ID, not embed them")
            if parallelism is None or semantics is None:
                raise InvalidInput(
                    "strict wave_d workload parsing requires the verified "
                    "parallelism and semantics parents")
            if d["parallelism_id"] != parallelism.parallelism_id():
                raise InvalidInput(
                    "wave_d workload parallelism_id does not match the "
                    "verified parallelism parent")
            if d["wave_d_semantics_id"] != semantics.semantics_id():
                raise InvalidInput(
                    "wave_d workload wave_d_semantics_id does not match "
                    "the verified semantics parent")
        else:
            if "type" in d and d["type"] != _HASH_TYPE_TAG:
                raise InvalidInput(
                    f"wave_d workload type tag {d['type']!r} is not "
                    f"{_HASH_TYPE_TAG!r}")
            if parallelism is None:
                if "parallelism" not in d:
                    raise InvalidInput(
                        "wave_d workload needs an inline parallelism "
                        "document or a verified parallelism parent")
                parallelism = ParallelismArtifact.from_dict(d["parallelism"])
            if semantics is None:
                if "semantics" not in d:
                    raise InvalidInput(
                        "wave_d workload needs an inline semantics "
                        "document or a verified semantics parent")
                semantics = WaveDWorkloadSemantics.from_dict(d["semantics"])
        if not isinstance(d.get("operations"), list):
            raise InvalidInput("wave_d workload operations must be a list")
        art = cls(parallelism=parallelism, semantics=semantics,
                  operations=tuple(_operation_from_dict(o)
                                   for o in d["operations"]),
                  schema_version=d.get("schema_version",
                                       WAVED_WORKLOAD_SCHEMA_VERSION))
        if strict:
            require_embedded_id(d, "workload_id", art.workload_id(),
                                "wave_d workload")
        elif d.get("workload_id") not in (None, art.workload_id()):
            raise InvalidInput("workload_id does not match content")
        return art


__all__ = [
    "WAVED_OPERATION_KINDS", "WAVED_WORKLOAD_SCHEMA_VERSION",
    "WaveDOperation", "WaveDWorkload",
]
