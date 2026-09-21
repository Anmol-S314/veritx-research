"""veritx_dse.waved.messages — LogicalMessageArtifact (D3, §20/§24–§26).

One lowering: OperationGraph + intents → canonical LogicalMessages.

Exactly one schedule per collective kind (§21), pinned:

    ALLREDUCE ring · REDUCESCATTER ring · ALLGATHER ring
    ALLTOALL direct · BROADCAST root fanout

Each generated message is content-derived and carries the operation id,
phase, src/dst logical ranks, payload bytes, traffic class and the
schedule order key. The artifact identity binds its direct parents
(§25): operation_graph_id, collective schedule identities, replication
schedule, canonical ordered message contents.

Conservation is per operation class (§26) — never a generic byte law.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import (
    ConservationFailed, EvidenceInvalid, InvalidInput, UnsupportedSchedule,
)
from veritx_dse.core.artifact import content_hash
from .operations import (
    CollectiveIntent, MulticastIntent, OperationGraph, P2PTransfer,
    REPLICATION_SOURCE, SCHEDULES,
)
from .oracles import ref_collective
from veritx_dse.core.artifact import (
    require_embedded_id, require_fields, require_schema_version, require_type_tag,
)

LOGICAL_MESSAGE_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/WavedLogicalMessages"

DEFAULT_TRAFFIC_CLASS = "DEFAULT"


class _TrafficClassAuthority:
    """Wave-D's view onto the Wave-B VC authority (§30).

    The supported traffic-class names are validated at physical-binding
    time against ``VCAssignmentArtifact.traffic_class_to_vcs``; here we
    only assign classes to messages. One class per message, from the
    workload declaration or the pinned default.
    """

    def __init__(self, class_name: str):
        if not isinstance(class_name, str) or not class_name:
            raise InvalidInput("traffic class must be a non-empty string")
        self.class_name = class_name


@dataclass(frozen=True)
class LogicalMessage:
    """One scheduled logical network message (§24)."""

    message_id: str
    operation_id: str
    phase: str
    src_rank: int
    dst_rank: int
    payload_bytes: int
    traffic_class: str
    step: int
    seq: int

    def canonical(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id, "operation_id": self.operation_id,
            "phase": self.phase, "src_rank": self.src_rank,
            "dst_rank": self.dst_rank, "payload_bytes": self.payload_bytes,
            "traffic_class": self.traffic_class, "step": self.step,
            "seq": self.seq,
        }


@dataclass(frozen=True)
class CollectiveScheduleRecord:
    """The pinned schedule identity actually selected for one intent."""

    collective_id: str
    kind: str
    algorithm: str
    k: int
    payload_bytes: int
    steps: int
    message_count: int
    message_bytes: int
    per_rank_sent: int
    aggregate_payload: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "collective_id": self.collective_id, "kind": self.kind,
            "algorithm": self.algorithm, "k": self.k,
            "payload_bytes": self.payload_bytes, "steps": self.steps,
            "message_count": self.message_count,
            "message_bytes": self.message_bytes,
            "per_rank_sent": self.per_rank_sent,
            "aggregate_payload": self.aggregate_payload,
        }

    @property
    def schedule_id(self) -> str:
        return content_hash("srota/WavedCollectiveSchedule", 1, self.to_dict())


def _expand_collective(ci: CollectiveIntent) -> tuple[
        list[tuple[int, int, int]], CollectiveScheduleRecord]:
    """Pinned schedule → ordered (step, src_idx, dst_idx) triples."""
    k, B = ci.k, ci.payload_bytes
    ref = ref_collective(ci.kind, k, B)  # raises on divisibility refusal
    triples: list[tuple[int, int, int]] = []
    if ci.kind in ("ALLREDUCE", "REDUCESCATTER", "ALLGATHER"):
        steps = ref["steps"]
        for step in range(steps):
            off = step % (k - 1) + 1
            for i in range(k):
                triples.append((step, i, (i + off) % k))
    elif ci.kind == "ALLTOALL":
        for i in range(k):
            for j in range(k):
                if i != j:
                    triples.append((0, i, j))
    else:  # BROADCAST root fanout: root = participants[0]
        root_idx = 0
        for j in range(1, k):
            triples.append((0, root_idx, j))
    assert len(triples) == ref["message_count"]
    rec = CollectiveScheduleRecord(
        collective_id=ci.collective_id, kind=ci.kind, algorithm=ci.algorithm,
        k=k, payload_bytes=B, steps=ref["steps"],
        message_count=ref["message_count"],
        message_bytes=ref["message_bytes"],
        per_rank_sent=ref["per_rank_sent"],
        aggregate_payload=ref["aggregate_payload"])
    return triples, rec


@dataclass(frozen=True)
class LogicalMessageArtifact:
    """Canonical ordered logical messages + schedule records (§25)."""

    graph: OperationGraph
    traffic_class: str = DEFAULT_TRAFFIC_CLASS
    schema_version: int = LOGICAL_MESSAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.graph, OperationGraph):
            raise InvalidInput("graph must be an OperationGraph")
        tc = _TrafficClassAuthority(self.traffic_class)

        messages: list[LogicalMessage] = []
        schedules: list[CollectiveScheduleRecord] = []
        seq = 0
        node_of_collective: dict[str, str] = {}
        node_of_transfer: dict[str, str] = {}
        node_of_multicast: dict[str, str] = {}
        for n in self.graph.nodes:
            d = n.detail
            if n.kind == "COLLECTIVE" and "collective_id" in d:
                node_of_collective[d["collective_id"]] = n.operation_id
            if n.kind == "P2P" and "transfer_id" in d:
                node_of_transfer[d["transfer_id"]] = n.operation_id
            if n.kind == "MULTICAST" and "multicast_id" in d:
                node_of_multicast[d["multicast_id"]] = n.operation_id

        for ci in self.graph.collectives:
            op_id = node_of_collective.get(ci.collective_id)
            if op_id is None:
                raise InvalidInput(
                    f"collective {ci.collective_id!r} has no operation node")
            triples, rec = _expand_collective(ci)
            schedules.append(rec)
            phase = self.graph.node(op_id).phase
            for step, si, di in triples:
                m = LogicalMessage(
                    message_id=f"{op_id}#{seq}", operation_id=op_id,
                    phase=phase, src_rank=ci.participants[si],
                    dst_rank=ci.participants[di],
                    payload_bytes=rec.message_bytes,
                    traffic_class=tc.class_name, step=step, seq=seq)
                messages.append(m)
                seq += 1
        for tr in self.graph.p2p_transfers:
            op_id = node_of_transfer.get(tr.transfer_id)
            if op_id is None:
                raise InvalidInput(
                    f"P2P transfer {tr.transfer_id!r} has no operation node")
            phase = self.graph.node(op_id).phase
            messages.append(LogicalMessage(
                message_id=f"{op_id}#{seq}", operation_id=op_id,
                phase=phase, src_rank=tr.src_rank, dst_rank=tr.dst_rank,
                payload_bytes=tr.payload_bytes,
                traffic_class=tc.class_name, step=0, seq=seq))
            seq += 1
        for mc in self.graph.multicasts:
            op_id = node_of_multicast.get(mc.multicast_id)
            if op_id is None:
                raise InvalidInput(
                    f"multicast {mc.multicast_id!r} has no operation node")
            phase = self.graph.node(op_id).phase
            for dst in mc.destinations:
                messages.append(LogicalMessage(
                    message_id=f"{op_id}#{seq}", operation_id=op_id,
                    phase=phase, src_rank=mc.source_rank, dst_rank=dst,
                    payload_bytes=mc.payload_bytes,
                    traffic_class=tc.class_name, step=0, seq=seq))
                seq += 1

        object.__setattr__(self, "_messages", tuple(messages))
        object.__setattr__(self, "_schedules", tuple(schedules))

    # ── accessors ─────────────────────────────────────────────────────
    @property
    def messages(self) -> tuple[LogicalMessage, ...]:
        return self._messages

    @property
    def schedules(self) -> tuple[CollectiveScheduleRecord, ...]:
        return self._schedules

    def messages_for_operation(self, operation_id: str
                               ) -> tuple[LogicalMessage, ...]:
        return tuple(m for m in self._messages
                     if m.operation_id == operation_id)

    # ── conservation (§26) against the independent oracle ─────────────
    def validate_against_oracle(self) -> None:
        messages = self._messages
        for ci in self.graph.collectives:
            ref = ref_collective(ci.kind, ci.k, ci.payload_bytes)
            got_count = sum(
                1 for m in messages
                if m.operation_id in
                self._collective_op_ids()[ci.collective_id])
            if got_count != ref["message_count"]:
                raise ConservationFailed(
                    f"collective {ci.collective_id!r}: generated "
                    f"{got_count} messages, schedule requires "
                    f"{ref['message_count']}")
            got_bytes = sum(
                m.payload_bytes for m in messages
                if m.operation_id in
                self._collective_op_ids()[ci.collective_id])
            if got_bytes != ref["aggregate_payload"]:
                raise ConservationFailed(
                    f"collective {ci.collective_id!r}: aggregate payload "
                    f"{got_bytes} != scheduled {ref['aggregate_payload']}")
            per_rank: dict[int, int] = {}
            for m in messages:
                if m.operation_id in \
                        self._collective_op_ids()[ci.collective_id]:
                    per_rank[m.src_rank] = \
                        per_rank.get(m.src_rank, 0) + m.payload_bytes
            if ci.kind != "BROADCAST":
                for p in ci.participants:
                    if per_rank.get(p, 0) != ref["per_rank_sent"]:
                        raise ConservationFailed(
                            f"collective {ci.collective_id!r}: rank {p} "
                            f"sent {per_rank.get(p, 0)}, expected "
                            f"{ref['per_rank_sent']}")
            else:
                root = ci.participants[0]
                if per_rank.get(root, 0) != ref["per_rank_sent"] or \
                        any(v != 0 for r, v in per_rank.items() if r != root):
                    raise ConservationFailed(
                        f"broadcast {ci.collective_id!r}: only the root "
                        f"sends (root sent {per_rank.get(root, 0)}, "
                        f"expected {ref['per_rank_sent']})")
        for tr in self.graph.p2p_transfers:
            ops = self._transfer_op_ids()[tr.transfer_id]
            ms = [m for m in messages if m.operation_id in ops]
            if len(ms) != 1 or ms[0].payload_bytes != tr.payload_bytes:
                raise ConservationFailed(
                    f"P2P {tr.transfer_id!r}: exactly one message carrying "
                    f"{tr.payload_bytes} bytes required, got "
                    f"{len(ms)} message(s)")
        for mc in self.graph.multicasts:
            if mc.replication != REPLICATION_SOURCE:
                raise UnsupportedSchedule(
                    f"replication {mc.replication!r} unsupported")
            ops = self._multicast_op_ids()[mc.multicast_id]
            ms = [m for m in messages if m.operation_id in ops]
            if len(ms) != mc.n:
                raise ConservationFailed(
                    f"multicast {mc.multicast_id!r}: {mc.n} destinations "
                    f"require {mc.n} unicast messages, got {len(ms)}")
            if sum(m.payload_bytes for m in ms) != mc.n * mc.payload_bytes:
                raise ConservationFailed(
                    f"multicast {mc.multicast_id!r}: aggregate "
                    f"{sum(m.payload_bytes for m in ms)} != "
                    f"{mc.n * mc.payload_bytes}")

    def _collective_op_ids(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for n in self.graph.nodes:
            cid = n.detail.get("collective_id")
            if cid is not None:
                out.setdefault(cid, set()).add(n.operation_id)
        return out

    def _transfer_op_ids(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for n in self.graph.nodes:
            tid = n.detail.get("transfer_id")
            if tid is not None:
                out.setdefault(tid, set()).add(n.operation_id)
        return out

    def _multicast_op_ids(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for n in self.graph.nodes:
            mid = n.detail.get("multicast_id")
            if mid is not None:
                out.setdefault(mid, set()).add(n.operation_id)
        return out

    # ── identity (§25) ────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "operation_graph_id": self.graph.operation_graph_id(),
            "schedules": [s.to_dict() for s in self._schedules],
            "replication_schedule": REPLICATION_SOURCE,
            "traffic_class": self.traffic_class,
            "messages": [m.canonical() for m in self._messages],
        }

    def message_artifact_id(self) -> str:
        return content_hash(_HASH_TYPE_TAG, self.schema_version,
                            self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_dict(),
                "message_artifact_id": self.message_artifact_id()}

    # ── strict parsing (persisted-resource contract) ──────────────────
    @classmethod
    def from_dict(cls, d: Any, *, graph: OperationGraph,
                  strict: bool = False) -> "LogicalMessageArtifact":
        """Rebuild the lowering from a VERIFIED graph parent.

        In strict mode the embedded ``operation_graph_id`` and
        ``message_artifact_id`` are required and must match, and every
        stored schedule/message row must equal the recomputed canonical
        content (a tampered row cannot survive verification).
        """
        require_fields(d, {
            "type", "schema_version", "operation_graph_id", "schedules",
            "replication_schedule", "traffic_class", "messages",
            "message_artifact_id",
        }, "logical messages")
        if strict:
            require_type_tag(d, _HASH_TYPE_TAG, "logical messages")
            require_schema_version(d, LOGICAL_MESSAGE_SCHEMA_VERSION,
                                   "logical messages")
            for key in ("operation_graph_id", "schedules",
                        "replication_schedule", "traffic_class",
                        "messages", "message_artifact_id"):
                if key not in d:
                    raise InvalidInput(
                        f"persisted logical messages is missing {key!r}")
            if d["operation_graph_id"] != graph.operation_graph_id():
                raise InvalidInput(
                    "logical messages operation_graph_id does not match "
                    "the verified graph parent")
            if d["replication_schedule"] != REPLICATION_SOURCE:
                raise InvalidInput(
                    "logical messages replication_schedule is not the "
                    "pinned SOURCE_REPLICATION schedule")
        elif "type" in d and d["type"] != _HASH_TYPE_TAG:
            raise InvalidInput(
                f"logical messages type tag {d['type']!r} is not "
                f"{_HASH_TYPE_TAG!r}")
        art = cls(graph=graph,
                  traffic_class=d.get("traffic_class",
                                      DEFAULT_TRAFFIC_CLASS),
                  schema_version=d.get("schema_version",
                                       LOGICAL_MESSAGE_SCHEMA_VERSION))
        if strict:
            require_embedded_id(d, "message_artifact_id",
                                art.message_artifact_id(),
                                "logical messages")
            recomputed = art.identity_dict()
            for key in ("schedules", "messages"):
                if d.get(key) != recomputed[key]:
                    raise EvidenceInvalid(
                        f"persisted logical messages {key} do not equal "
                        "the recomputed canonical content: content "
                        "forged")
        elif d.get("message_artifact_id") not in (
                None, art.message_artifact_id()):
            raise InvalidInput(
                "message_artifact_id does not match content")
        return art


__all__ = [
    "CollectiveIntent", "CollectiveScheduleRecord", "DEFAULT_TRAFFIC_CLASS",
    "LogicalMessage", "LogicalMessageArtifact",
    "LOGICAL_MESSAGE_SCHEMA_VERSION",
]
