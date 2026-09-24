"""veritx_dse.workload.messages — logical messages over the canonical graph.

ONE lowering: the canonical :class:`WorkloadGraph` → canonical ordered
logical messages.

    COLLECTIVE        pinned schedule over declared participants
    BROADCAST         explicit declared source, never participants[0]
    P2P TRANSFER      one message
    P2P SEND/RECV     refused: not a complete transfer
    MULTICAST         one message per declared destination
    EXPERT_BEGIN/END  declared collective when it has >= 2 participants
    PIM_CHANNEL/END   no network message, ever
    COMPUTE           no network message

There are no communication side lists and no second graph authority: the
WorkloadGraph IS the authority, so the parent identity is ``workload_id``
and the rank namespace is the graph's ``participant_count`` (never the
world rank space).

Exactly one schedule per collective kind, pinned:

    ALLREDUCE ring · REDUCESCATTER ring · ALLGATHER ring
    ALLTOALL direct · BROADCAST root fanout

Conservation is per operation class — never a generic byte law. The
production schedule arithmetic lives in ``workload/collectives.py``; the
independent oracle lives in the test suite, deliberately not here, so a
differential test cannot degenerate into "the spec agrees with itself".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.core.artifact import (
    EvidenceInvalid, InvalidInput, content_hash, require_embedded_id,
    require_fields, require_schema_version, require_type_tag, thaw,
)
from veritx_dse.core.errors import (
    ConservationFailed, UnsupportedSemantics,
)
from veritx_dse.workload.collectives import collective_schedule
from veritx_dse.workload.graph import (
    KIND_COLLECTIVE, KIND_COMPUTE, KIND_EXPERT_BEGIN, KIND_EXPERT_END,
    KIND_MULTICAST, KIND_P2P, KIND_PIM_CHANNEL, KIND_PIM_END, WorkloadGraph,
)

LOGICAL_MESSAGE_SCHEMA_VERSION_V2 = 2
_V2_HASH_TYPE_TAG = "srota/LogicalMessageArtifactV2"

DEFAULT_TRAFFIC_CLASS = "DEFAULT"

#: the pinned algorithm label per collective kind (identity-bearing)
SCHEDULES = {
    "ALLREDUCE": "RING",
    "REDUCESCATTER": "RING",
    "ALLGATHER": "RING",
    "ALLTOALL": "DIRECT",
    "BROADCAST": "ROOT_FANOUT",
}
#: the pinned multicast replication schedule
REPLICATION_SOURCE = "SOURCE_REPLICATION"


class _TrafficClassAuthority:
    """The workload's view onto the VC authority.

    Traffic-class names are validated at physical-binding time against
    ``VCAssignmentArtifact.traffic_class_to_vcs``; here one class is
    assigned per message from the declaration or the pinned default.
    """

    def __init__(self, class_name: str):
        if not isinstance(class_name, str) or not class_name:
            raise InvalidInput("traffic class must be a non-empty string")
        self.class_name = class_name


@dataclass(frozen=True)
class LogicalMessage:
    """One scheduled logical network message."""

    message_id: str
    operation_id: str
    phase: str | None
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
    """The pinned schedule identity actually selected for one operation."""

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
        return content_hash("srota/WavedCollectiveSchedule", 1,
                            self.to_dict())


def _collective_triples(kind: str, participants: tuple[int, ...],
                        payload_bytes: int, *, source: int | None = None
                        ) -> tuple[list[tuple[int, int, int]], dict[str, int]]:
    """Pinned schedule → ordered (step, src_index, dst_index) triples.

    ``source`` is honoured for BROADCAST when declared (the canonical graph
    declares it); an undeclared root is refused here as well, so a caller
    cannot smuggle in the legacy ``participants[0]`` convenience.
    """
    k = len(participants)
    ref = collective_schedule(kind, k, payload_bytes)
    triples: list[tuple[int, int, int]] = []
    if kind in ("ALLREDUCE", "REDUCESCATTER", "ALLGATHER"):
        # F-0004: a ring collective moves data ONLY between logical
        # neighbours. Every step, each rank sends one chunk to its next
        # ring neighbour; the CHUNK ownership rotates, the network edge
        # does not. (The previous offset exchange used all pairs.)
        for step in range(ref["steps"]):
            for i in range(k):
                triples.append((step, i, (i + 1) % k))
    elif kind == "ALLTOALL":
        for i in range(k):
            for j in range(k):
                if i != j:
                    triples.append((0, i, j))
    else:  # BROADCAST fanout from the explicitly declared root
        if source is None:
            raise InvalidInput(
                "BROADCAST requires an explicit source rank; "
                "participants[0] is a legacy convenience, not a law")
        if source not in participants:
            raise InvalidInput(
                f"BROADCAST source {source!r} is not a participant "
                f"{participants!r}")
        root_idx = participants.index(source)
        for j in range(k):
            if j != root_idx:
                triples.append((0, root_idx, j))
    if len(triples) != ref["message_count"]:
        raise ConservationFailed(
            f"{kind} k={k} B={payload_bytes}: generated {len(triples)} "
            f"messages, schedule requires {ref['message_count']}")
    return triples, ref


@dataclass(frozen=True)
class LogicalMessageArtifactV2:
    """Canonical logical messages built from the canonical WorkloadGraph."""

    graph: WorkloadGraph
    traffic_class: str = DEFAULT_TRAFFIC_CLASS
    schema_version: int = LOGICAL_MESSAGE_SCHEMA_VERSION_V2

    def __post_init__(self) -> None:
        if not isinstance(self.graph, WorkloadGraph):
            raise InvalidInput("graph must be a WorkloadGraph")
        if self.schema_version != LOGICAL_MESSAGE_SCHEMA_VERSION_V2:
            raise InvalidInput(
                f"unsupported logical message schema_version "
                f"{self.schema_version!r} (expected "
                f"{LOGICAL_MESSAGE_SCHEMA_VERSION_V2})")
        tc = _TrafficClassAuthority(self.traffic_class)

        messages: list[LogicalMessage] = []
        schedules: list[CollectiveScheduleRecord] = []
        seq = 0
        for op in self.graph.ordered_operations():
            d = thaw(op.detail)
            kind = op.kind
            if kind in (KIND_COMPUTE, KIND_PIM_CHANNEL, KIND_PIM_END):
                continue
            if kind in (KIND_COLLECTIVE, KIND_EXPERT_BEGIN,
                        KIND_EXPERT_END):
                declared = d.get("participants")
                if kind != KIND_COLLECTIVE:
                    # EXPERT regions may declare no collective at all.
                    if not declared or len(declared) < 2:
                        continue      # declared, but not communicating
                participants = tuple(declared)
                ck = d["collective_kind"]
                triples, ref = _collective_triples(
                    ck, participants, d["payload_bytes"],
                    source=d.get("source"))
                schedules.append(CollectiveScheduleRecord(
                    collective_id=op.operation_id, kind=ck,
                    algorithm=SCHEDULES[ck], k=len(participants),
                    payload_bytes=d["payload_bytes"], steps=ref["steps"],
                    message_count=ref["message_count"],
                    message_bytes=ref["message_bytes"],
                    per_rank_sent=ref["per_rank_sent"],
                    aggregate_payload=ref["aggregate_payload"]))
                for step, si, di in triples:
                    messages.append(LogicalMessage(
                        message_id=f"{op.operation_id}#{seq}",
                        operation_id=op.operation_id, phase=op.phase,
                        src_rank=participants[si],
                        dst_rank=participants[di],
                        payload_bytes=ref["message_bytes"],
                        traffic_class=tc.class_name, step=step, seq=seq))
                    seq += 1
            elif kind == KIND_P2P:
                if d["role"] != "TRANSFER":
                    raise UnsupportedSemantics(
                        f"operation {op.operation_id!r}: P2P role "
                        f"{d['role']!r} is not a complete transfer; "
                        f"SEND/RECV pairing is not a proven lowering")
                messages.append(LogicalMessage(
                    message_id=f"{op.operation_id}#{seq}",
                    operation_id=op.operation_id, phase=op.phase,
                    src_rank=d["src_rank"], dst_rank=d["dst_rank"],
                    payload_bytes=d["payload_bytes"],
                    traffic_class=tc.class_name, step=0, seq=seq))
                seq += 1
            elif kind == KIND_MULTICAST:
                for dst in d["destinations"]:
                    messages.append(LogicalMessage(
                        message_id=f"{op.operation_id}#{seq}",
                        operation_id=op.operation_id, phase=op.phase,
                        src_rank=d["source_rank"], dst_rank=dst,
                        payload_bytes=d["payload_bytes"],
                        traffic_class=tc.class_name, step=0, seq=seq))
                    seq += 1
            else:
                raise UnsupportedSemantics(
                    f"operation {op.operation_id!r}: kind {kind!r} has no "
                    f"logical-message semantics")

        object.__setattr__(self, "_messages", tuple(messages))
        object.__setattr__(self, "_schedules", tuple(schedules))

    # ── accessors ─────────────────────────────────────────────────────
    @property
    def messages(self) -> tuple[LogicalMessage, ...]:
        return self._messages

    @property
    def schedules(self) -> tuple[CollectiveScheduleRecord, ...]:
        return self._schedules

    @property
    def participant_count(self) -> int:
        return self.graph.participant_count

    def messages_for_operation(self, operation_id: str
                               ) -> tuple[LogicalMessage, ...]:
        return tuple(m for m in self._messages
                     if m.operation_id == operation_id)

    # ── conservation against the schedule records actually selected ──
    def validate_conservation(self) -> None:
        for rec in self._schedules:
            rows = self.messages_for_operation(rec.collective_id)
            if len(rows) != rec.message_count:
                raise ConservationFailed(
                    f"collective {rec.collective_id!r}: generated "
                    f"{len(rows)} messages, schedule requires "
                    f"{rec.message_count}")
            if sum(m.payload_bytes for m in rows) != rec.aggregate_payload:
                raise ConservationFailed(
                    f"collective {rec.collective_id!r}: aggregate payload "
                    f"does not equal the scheduled "
                    f"{rec.aggregate_payload}")
            if rec.kind != "BROADCAST":
                per_rank: dict[int, int] = {}
                for m in rows:
                    per_rank[m.src_rank] = (per_rank.get(m.src_rank, 0)
                                            + m.payload_bytes)
                for rank, sent in per_rank.items():
                    if sent != rec.per_rank_sent:
                        raise ConservationFailed(
                            f"collective {rec.collective_id!r}: rank "
                            f"{rank} sent {sent} != scheduled "
                            f"{rec.per_rank_sent}")

    # ── identity ──────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _V2_HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "workload_id": self.graph.workload_id(),
            "participant_count": self.graph.participant_count,
            "replication_schedule": REPLICATION_SOURCE,
            "traffic_class": self.traffic_class,
            "schedules": [s.to_dict() for s in self._schedules],
            "messages": [m.canonical() for m in self._messages],
        }

    def message_artifact_id(self) -> str:
        return content_hash(_V2_HASH_TYPE_TAG, self.schema_version,
                            self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_dict(),
                "message_artifact_id": self.message_artifact_id()}

    @classmethod
    def from_dict(cls, d: Any, *, graph: WorkloadGraph,
                  strict: bool = False) -> "LogicalMessageArtifactV2":
        """Rebuild from the VERIFIED graph parent, never from the JSON."""
        require_fields(d, {
            "type", "schema_version", "workload_id", "participant_count",
            "replication_schedule", "traffic_class", "schedules",
            "messages", "message_artifact_id",
        }, "logical messages v2")
        if strict:
            require_type_tag(d, _V2_HASH_TYPE_TAG, "logical messages v2")
            require_schema_version(d, LOGICAL_MESSAGE_SCHEMA_VERSION_V2,
                                   "logical messages v2")
            if d["workload_id"] != graph.workload_id():
                raise InvalidInput(
                    "logical messages v2 workload_id does not match the "
                    "verified WorkloadGraph parent")
            if d["participant_count"] != graph.participant_count:
                raise InvalidInput(
                    "logical messages v2 participant_count does not match "
                    "the verified WorkloadGraph parent")
            if d["replication_schedule"] != REPLICATION_SOURCE:
                raise InvalidInput(
                    "logical messages v2 replication_schedule is not the "
                    "pinned SOURCE_REPLICATION schedule")
        elif "type" in d and d["type"] != _V2_HASH_TYPE_TAG:
            raise InvalidInput(
                f"logical messages v2 type tag {d['type']!r} is not "
                f"{_V2_HASH_TYPE_TAG!r}")
        art = cls(graph=graph,
                  traffic_class=d.get("traffic_class",
                                      DEFAULT_TRAFFIC_CLASS),
                  schema_version=d.get("schema_version",
                                       LOGICAL_MESSAGE_SCHEMA_VERSION_V2))
        if strict:
            require_embedded_id(d, "message_artifact_id",
                                art.message_artifact_id(),
                                "logical messages v2")
            recomputed = art.identity_dict()
            for key in ("schedules", "messages"):
                if d.get(key) != recomputed[key]:
                    raise EvidenceInvalid(
                        f"persisted logical messages v2 {key} do not equal "
                        f"the recomputed canonical content: content forged")
        elif d.get("message_artifact_id") not in (
                None, art.message_artifact_id()):
            raise InvalidInput(
                "message_artifact_id does not match content")
        return art


__all__ = [
    "CollectiveScheduleRecord", "DEFAULT_TRAFFIC_CLASS", "LogicalMessage",
    "LogicalMessageArtifactV2", "LOGICAL_MESSAGE_SCHEMA_VERSION_V2",
    "REPLICATION_SOURCE", "SCHEDULES",
]
