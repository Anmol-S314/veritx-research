"""veritx_dse.backend.astra — canonical ASTRA/Chakra projection + execution.

Rationale: docs/decisions/modules/backend.md
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from veritx_dse.model.attachment import AgentAttachmentArtifact
from veritx_dse.model.mapping import MappingArtifact
from veritx_dse.model.resolved_fabric import ResolvedFabric
from veritx_dse.workload.graph import (
    KIND_COLLECTIVE, KIND_COMPUTE, KIND_EXPERT_BEGIN, KIND_EXPERT_END,
    KIND_MULTICAST, KIND_P2P, KIND_PIM_CHANNEL, KIND_PIM_END,
)
from veritx_dse.workload.messages import (
    LogicalMessageArtifactV2, LogicalMessageArtifactV3,
)

ASTRA_PROJECTION_SCHEMA_VERSION = 1
LOWERING_SEMANTICS_VERSION = 1
_PROJECTION_TYPE_TAG = "srota/AstraWorkloadProjection"
_CHAKRA_SCHEMA = "1.0.2-chakra.0.0.4"

LOGICAL_ARTIFACT_VARIANTS = ("V2", "V3")

ZERO_TRAFFIC = "ZERO_TRAFFIC"
LOWERED = "LOWERED"
UNSUPPORTED = "UNSUPPORTED"

COMM_ATTR_ABI = ("uint", "int")
_DEFAULT_COMM_ATTR_ABI = "uint"
_COMM_ATTR_FIELDS = {"uint": ("uint32_val", "uint64_val"),
                     "int": ("int32_val", "int64_val")}

ET_GRANULARITY = ("messages", "collectives")
_DEFAULT_ET_GRANULARITY = "messages"
_CHAKRA_COLLECTIVE_TYPE = {"ALLREDUCE": 0, "ALLGATHER": 2, "BROADCAST": 5,
                           "ALLTOALL": 6, "REDUCESCATTER": 7}

_ZERO_TRAFFIC_KINDS = (KIND_COMPUTE, KIND_PIM_CHANNEL, KIND_PIM_END)
_LOWERED_KINDS = (KIND_COLLECTIVE, KIND_P2P, KIND_MULTICAST, KIND_EXPERT_BEGIN,
                  KIND_EXPERT_END)

_CYCLES_RE = re.compile(r"sys\[(\d+)\] finished, (\d+) cycles")
_EXPOSED_RE = re.compile(
    r"sys\[(\d+)\] finished, \d+ cycles, exposed communication (\d+) cycles")

def compute_micros(duration_ns: Any, op_id: str) -> int:
    """Integer microseconds for one compute duration, or refusal.

    FIDELITY BOUNDARY (documented, not silent): Chakra ET carries whole
    microseconds, so a nanosecond duration reaches the backend only when
    it survives the conversion without inventing time.

    - None (profile gap) or negative: refused. A missing duration is not
      timing, and the old `max(1, ...)` turned it into a full microsecond.
    - 0 < ns < 1000: refused. Integer micros cannot represent a
      sub-microsecond duration; mapping 1ns (or 999ns) to 1us invents up
      to three orders of magnitude of compute time.
    - ns >= 1000: floor division. The sub-microsecond remainder is dropped
      and stated here — never silently, and never rounded up.
    - 0 ns is exactly representable as 0 and passes through.
    """
    if duration_ns is None:
        raise AstraError(
            f"compute operation {op_id!r} has no duration_ns: a profile "
            "gap is not timing, and defaulting it to 1us would invent "
            "compute time")
    if not isinstance(duration_ns, int) or duration_ns < 0:
        raise AstraError(
            f"compute operation {op_id!r} has invalid duration_ns "
            f"{duration_ns!r}: must be a non-negative int")
    if 0 < duration_ns < 1000:
        raise AstraError(
            f"compute operation {op_id!r} declares {duration_ns}ns, which "
            "integer microseconds cannot represent: mapping it to 1us "
            "would invent up to 1000x compute time")
    return duration_ns // 1000


class AstraError(ValueError):
    """Base for ASTRA adapter refusals and failures."""

class AstraUnavailable(AstraError):
    """The runtime binary or the Chakra protobuf bindings are not available."""

class AstraLoweringRefused(AstraError):
    """The canonical workload has no ASTRA lowering for some operation."""

class AstraExecutionError(AstraError):
    """Execution failed, partially executed, or produced malformed evidence."""

VERITX_CLASS_IDS = {
    "ALLREDUCE": 1,
    "REDUCESCATTER": 2,
    "ALLGATHER": 3,
    "ALLTOALL": 4,
}

def class_ids_for_kinds(kinds: Any) -> list[int]:
    """Embedded class ids for canonical collective kinds.

    A kind without a VeritXClassId (today BROADCAST) is a typed
    refusal: executing it unattributed would flatten it into class 0
    silently. Never derive class from endpoint, rank, size or arrival
    order — the authority is this table plus the runtime enum.
    """
    ids: list[int] = []
    for kind in kinds or ():
        class_id = VERITX_CLASS_IDS.get(kind)
        if class_id is None:
            raise AstraLoweringRefused(
                f"collective kind {kind!r} has no embedded class id "
                "under ABI v1: the runtime would inject it unattributed "
                "(class 0) — refusing instead of flattening")
        ids.append(class_id)
    return ids

def required_embedded_classes(collective_operations: Any) -> int:
    """Embedded ``classes=`` covering every attributable collective.

    Returns max(class id) + 1 over the projection's collective
    operations (empty projection needs no envelope: 1).
    """
    kinds = [entry[1] for entry in collective_operations or ()
             if len(entry) > 1]
    ids = class_ids_for_kinds(kinds)
    if not ids:
        return 1
    return max(ids) + 1

def classify_operation(op: Any) -> str:
    """ZERO_TRAFFIC | LOWERED | UNSUPPORTED for one canonical operation."""
    if op.kind in _ZERO_TRAFFIC_KINDS:
        return ZERO_TRAFFIC
    if op.kind in _LOWERED_KINDS:
        if op.kind in (KIND_EXPERT_BEGIN, KIND_EXPERT_END):
            declared = op.detail.get("participants")
            if not declared or len(declared) < 2:
                return ZERO_TRAFFIC
        return LOWERED
    return UNSUPPORTED

def audit_operations(graph: Any) -> tuple[dict[str, str], ...]:
    """Per-operation classification; UNSUPPORTED is reported, never hidden."""
    return tuple(
        {"operation_id": op.operation_id, "kind": op.kind,
         "classification": classify_operation(op)}
        for op in graph.ordered_operations())

def fragment_payload(payload_bytes: int, mtu_bytes: int | None
                     ) -> tuple[int, ...]:
    """Split a logical payload into transport fragments.

    ASTRA consumes LOGICAL messages; fragmentation is only applied when the
    caller declares an MTU. Conservation is exact: the fragments sum to the
    original payload, with no dropped or duplicated bytes.
    """
    if type(payload_bytes) is not int or payload_bytes <= 0:
        raise AstraError("payload_bytes must be a positive int")
    if mtu_bytes is None:
        return (payload_bytes,)
    if type(mtu_bytes) is not int or mtu_bytes <= 0:
        raise AstraError("mtu_bytes must be a positive int or None")
    if payload_bytes <= mtu_bytes:
        return (payload_bytes,)
    full, tail = divmod(payload_bytes, mtu_bytes)
    fragments = [mtu_bytes] * full
    if tail:
        fragments.append(tail)
    if sum(fragments) != payload_bytes:
        raise AstraError("fragmentation did not conserve payload bytes")
    return tuple(fragments)

@dataclass(frozen=True)
class AstraMessage:
    """One canonical logical message as ASTRA will execute it."""

    sequence: int
    operation_id: str
    kind: str
    collective_kind: str | None
    step: int
    phase: str | None
    src_rank: int
    dst_rank: int
    payload_bytes: int
    traffic_class: str
    fragments: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence, "operation_id": self.operation_id,
            "kind": self.kind, "collective_kind": self.collective_kind,
            "step": self.step, "phase": self.phase,
            "src_rank": self.src_rank, "dst_rank": self.dst_rank,
            "payload_bytes": self.payload_bytes,
            "traffic_class": self.traffic_class,
            "fragments": list(self.fragments),
            "bytes_presented_to_astra": sum(self.fragments),
        }

@dataclass(frozen=True)
class AstraWorkloadProjection:
    """Canonical projection of logical messages onto the ASTRA workload."""

    messages: tuple[AstraMessage, ...]
    participant_count: int
    message_artifact_id: str
    workload_id: str
    resolved_fabric_hash: str
    mapping_hash: str
    attachment_hash: str
    compute_operations: tuple[tuple[str, int], ...] = ()
    compute_owners: tuple[tuple[str, int | None], ...] = ()
    collective_operations: tuple[tuple[str, str, int, tuple[int, ...]], ...] = ()
    mtu_bytes: int | None = None
    comm_attr_abi: str = _DEFAULT_COMM_ATTR_ABI
    et_granularity: str = _DEFAULT_ET_GRANULARITY
    logical_artifact_variant: str = "V2"
    schema_version: int = ASTRA_PROJECTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ASTRA_PROJECTION_SCHEMA_VERSION:
            raise AstraError(
                f"unsupported projection schema_version "
                f"{self.schema_version!r}")
        if self.comm_attr_abi not in COMM_ATTR_ABI:
            raise AstraError(
                f"comm_attr_abi must be one of {COMM_ATTR_ABI}, got "
                f"{self.comm_attr_abi!r}")
        if self.et_granularity not in ET_GRANULARITY:
            raise AstraError(
                f"et_granularity must be one of {ET_GRANULARITY}, got "
                f"{self.et_granularity!r}")
        if self.logical_artifact_variant not in LOGICAL_ARTIFACT_VARIANTS:
            raise AstraError(
                f"logical_artifact_variant must be one of "
                f"{LOGICAL_ARTIFACT_VARIANTS}, got "
                f"{self.logical_artifact_variant!r}")
        if type(self.participant_count) is not int \
                or self.participant_count <= 0:
            raise AstraError("participant_count must be a positive int")
        for message in self.messages:
            if not 0 <= message.src_rank < self.participant_count \
                    or not 0 <= message.dst_rank < self.participant_count:
                raise AstraError(
                    f"message {message.sequence} addresses a rank outside "
                    f"the participant namespace [0, {self.participant_count})")
            if sum(message.fragments) != message.payload_bytes:
                raise AstraError(
                    f"message {message.sequence}: fragmentation does not "
                    "conserve payload bytes")
        if self.compute_owners:
            declared = tuple(op_id for op_id, _ in self.compute_operations)
            mirrored = tuple(op_id for op_id, _ in self.compute_owners)
            if mirrored != declared:
                raise AstraError(
                    "compute_owners must mirror compute_operations exactly "
                    f"({mirrored} != {declared})")
            for op_id, owner in self.compute_owners:
                if owner is None:
                    continue
                if not 0 <= owner < self.participant_count:
                    raise AstraError(
                        f"compute operation {op_id!r} is owned by rank "
                        f"{owner}, outside the participant namespace "
                        f"[0, {self.participant_count})")

    @classmethod
    def build(cls, *, logical: Any,
              resolved_fabric: ResolvedFabric, mapping: MappingArtifact,
              attachment: AgentAttachmentArtifact,
              mtu_bytes: int | None = None,
              comm_attr_abi: str = _DEFAULT_COMM_ATTR_ABI,
              et_granularity: str = _DEFAULT_ET_GRANULARITY
              ) -> "AstraWorkloadProjection":
        """Project canonical messages; refuse unsupported semantics.

        Accepts the V2 uniform-class artifact and the V3 per-operation
        artifact. V3 messages keep their operation's lowered class each;
        the variant is recorded in the projection identity so class
        semantics can never silently collapse to V2."""
        if isinstance(logical, LogicalMessageArtifactV3):
            variant = "V3"
        elif isinstance(logical, LogicalMessageArtifactV2):
            variant = "V2"
        else:
            raise AstraError(
                "logical must be a LogicalMessageArtifactV2 or "
                f"LogicalMessageArtifactV3, got "
                f"{type(logical).__name__}")
        if not isinstance(resolved_fabric, ResolvedFabric):
            raise AstraError("resolved_fabric must be a ResolvedFabric")
        if not isinstance(mapping, MappingArtifact):
            raise AstraError("mapping must be a MappingArtifact")
        if not isinstance(attachment, AgentAttachmentArtifact):
            raise AstraError("attachment must be an AgentAttachmentArtifact")
        if mapping.mapping_hash() != resolved_fabric.mapping_hash:
            raise AstraError(
                "mapping does not belong to the resolved fabric")
        unsupported = [row for row in audit_operations(logical.graph)
                       if row["classification"] == UNSUPPORTED]
        if unsupported:
            raise AstraLoweringRefused(
                "no canonical ASTRA lowering for operation(s) "
                f"{[row['operation_id'] for row in unsupported]}; refusing "
                "rather than reporting zero communication cost")
        if variant == "V3":
            logical.validate_conservation()
        messages = tuple(
            AstraMessage(
                sequence=index, operation_id=m.operation_id,
                kind=logical.graph.by_id(m.operation_id).kind,
                collective_kind=logical.graph.by_id(
                    m.operation_id).detail.get("collective_kind"),
                step=m.step, phase=m.phase, src_rank=m.src_rank,
                dst_rank=m.dst_rank, payload_bytes=m.payload_bytes,
                traffic_class=m.traffic_class,
                fragments=fragment_payload(m.payload_bytes, mtu_bytes))
            for index, m in enumerate(logical.messages))
        compute = tuple(
            (op.operation_id, int(op.detail.get("duration_ns") or 0))
            for op in logical.graph.ordered_operations()
            if op.kind == KIND_COMPUTE)
        owners = tuple(
            (op.operation_id, op.owner)
            for op in logical.graph.ordered_operations()
            if op.kind == KIND_COMPUTE)
        collectives = tuple(
            (op.operation_id, str(op.detail.get("collective_kind")),
             int(op.detail.get("payload_bytes") or 0),
             tuple(op.detail.get("participants") or ()))
            for op in logical.graph.ordered_operations()
            if op.detail.get("collective_kind") is not None)

        return cls(
            messages=messages, participant_count=logical.participant_count,
            message_artifact_id=logical.message_artifact_id(),
            workload_id=logical.graph.workload_id(),
            resolved_fabric_hash=resolved_fabric.resolved_fabric_hash,
            mapping_hash=mapping.mapping_hash(),
            attachment_hash=attachment.attachment_hash(),
            compute_operations=compute,
            compute_owners=owners,
            collective_operations=collectives,
            mtu_bytes=mtu_bytes,
            comm_attr_abi=comm_attr_abi,
            et_granularity=et_granularity,
            logical_artifact_variant=variant)

    def operation_traffic_classes(self) -> dict[str, str]:
        """One canonical traffic class per operation id.

        Every message of an operation must carry its operation's class:
        an intra-operation mismatch is a collapsed binding, refused here
        rather than projected."""
        classes: dict[str, str] = {}
        for message in self.messages:
            known = classes.get(message.operation_id)
            if known is None:
                classes[message.operation_id] = message.traffic_class
            elif known != message.traffic_class:
                raise AstraError(
                    f"operation {message.operation_id!r} carries two "
                    f"traffic classes ({known!r} vs "
                    f"{message.traffic_class!r}): refusing a collapsed "
                    "class binding")
        return classes

    def class_binding_id(self) -> str:
        """Deterministic identity of the operation->class binding.

        Binds every network-bearing collective operation to its traffic
        class. Evidence and machine qualification carry this id so a
        swapped, collapsed or omitted class binding refuses downstream.
        """
        from veritx_dse.core.artifact import content_hash
        binding = sorted(
            (op_id, cls) for op_id, cls in
            self.operation_traffic_classes().items())
        return content_hash("srota/AstraClassBinding", 1,
                            {"binding": [list(row) for row in binding]})

    def traffic_classes(self) -> tuple[str, ...]:
        """Sorted distinct traffic classes across messages."""
        return tuple(sorted({m.traffic_class for m in self.messages}))

    def ranks(self) -> tuple[int, ...]:
        return tuple(range(self.participant_count))

    def active_ranks(self) -> tuple[int, ...]:
        """Ranks that emit at least one Chakra node in this workload.

        An idle participant emits nothing: no ET file is written for it, which
        is exactly how the runtime expresses an idle NPU.  Global (unowned)
        compute touches every rank, so it keeps the historical full set.
        """
        ranks: set[int] = set()
        for op_id, _duration_ns in self.compute_operations:
            owner = self.compute_owner(op_id)
            if owner is None:
                return self.ranks()
            ranks.add(owner)
        for _op_id, _kind, _payload, participants in \
                self.collective_operations:
            ranks.update(participants)
        for message in self.messages:
            if self.et_granularity == "collectives" \
                    and message.collective_kind is not None:
                continue
            ranks.add(message.src_rank)
            ranks.add(message.dst_rank)
        return tuple(sorted(ranks))

    def total_payload_bytes(self) -> int:
        return sum(m.payload_bytes for m in self.messages)

    def presented_bytes(self) -> int:
        return sum(sum(m.fragments) for m in self.messages)

    def evidence_scope(self) -> str:
        """Replicated-unicast traffic is not physical multicast evidence."""
        if any(m.kind == KIND_MULTICAST for m in self.messages):
            return "replicated_unicast"
        return "canonical_logical_messages"

    def expansion_authority(self) -> str:
        """Who expands the collective schedule for this projection."""
        return ("srota_logical_messages"
                if self.et_granularity == "messages" else "astra_comm_coll")

    def declared_compute_cycles(self) -> int:
        """Compute-only cycle floor declared by the workload (1 cycle/ns).

Rationale: docs/decisions/modules/backend.md
        """
        global_micros = 0
        owned_micros: dict[int, int] = {}
        for op_id, duration_ns in self.compute_operations:
            micros = compute_micros(duration_ns, op_id)
            owner = self.compute_owner(op_id)
            if owner is None:
                global_micros += micros
            else:
                owned_micros[owner] = owned_micros.get(owner, 0) + micros
        if not owned_micros:
            return global_micros * 1000
        return (global_micros + max(owned_micros.values())) * 1000

    def compute_owner(self, operation_id: str) -> int | None:
        for op_id, owner in self.compute_owners:
            if op_id == operation_id:
                return owner
        return None

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _PROJECTION_TYPE_TAG,
            "schema_version": self.schema_version,
            "lowering_semantics_version": LOWERING_SEMANTICS_VERSION,
            "workload_id": self.workload_id,
            "message_artifact_id": self.message_artifact_id,
            "resolved_fabric_hash": self.resolved_fabric_hash,
            "mapping_hash": self.mapping_hash,
            "attachment_hash": self.attachment_hash,
            "participant_count": self.participant_count,
            "mtu_bytes": self.mtu_bytes,
            "comm_attr_abi": self.comm_attr_abi,
            "et_granularity": self.et_granularity,
            **({"logical_artifact_variant": self.logical_artifact_variant,
                "class_binding_id": self.class_binding_id(),
                "traffic_classes": list(self.traffic_classes())}
               if self.logical_artifact_variant != "V2" else {}),
            "expansion_authority": self.expansion_authority(),
            "evidence_scope": self.evidence_scope(),
            "compute_operations": [[op_id, duration_ns]
                                   for op_id, duration_ns
                                   in self.compute_operations],
            **({"compute_ownership": [[op_id, owner]
                                      for op_id, owner
                                      in self.compute_owners]}
               if any(owner is not None
                      for _, owner in self.compute_owners) else {}),
            "collective_operations": [[op_id, kind, payload, list(parts)]
                                      for op_id, kind, payload, parts
                                      in self.collective_operations],
            "messages": [m.to_dict() for m in self.messages],
        }

    def projection_id(self) -> str:
        from veritx_dse.core.artifact import content_hash
        return content_hash(_PROJECTION_TYPE_TAG, self.schema_version,
                            self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_dict(), "projection_id": self.projection_id()}

    @classmethod
    def from_dict(cls, doc: Any) -> "AstraWorkloadProjection":
        """Rebuild the exact projected workload from its persisted JSON.

        Accepts the identity dict or the full to_dict payload (derived
        keys are ignored, never trusted). The caller must verify
        ``projection_id()`` against the externally held identity.
        """
        if not isinstance(doc, dict):
            raise AstraError(
                f"workload document must be a JSON object, got "
                f"{type(doc).__name__}")
        try:
            raw_messages = doc["messages"]
            participant_count = doc["participant_count"]
            str_fields = {
                name: doc[name] for name in (
                    "message_artifact_id", "workload_id",
                    "resolved_fabric_hash", "mapping_hash",
                    "attachment_hash", "comm_attr_abi", "et_granularity")}
        except KeyError as exc:
            raise AstraError(
                f"workload document is missing {exc}") from exc
        if not isinstance(raw_messages, list):
            raise AstraError("workload document messages must be a list")
        messages = tuple(_message_from_dict(m) for m in raw_messages)
        if type(participant_count) is not int or participant_count <= 0:
            raise AstraError(
                "workload document participant_count must be a "
                "positive int")
        for name, value in str_fields.items():
            if not isinstance(value, str) or not value:
                raise AstraError(
                    f"workload document field {name!r} must be a "
                    f"non-empty string")
        compute = _op_pairs(doc.get("compute_operations", ()),
                            "compute_operations")
        if "compute_ownership" in doc:
            owners = _owner_pairs(doc.get("compute_ownership", ()))
        else:
            owners = _owner_pairs(doc.get("compute_owners", ()))
        collectives = _collective_rows(
            doc.get("collective_operations", ()))
        mtu = doc.get("mtu_bytes")
        if mtu is not None and (type(mtu) is not int or mtu <= 0):
            raise AstraError(
                "workload document mtu_bytes must be a positive int "
                "or null")
        schema = doc.get("schema_version",
                         ASTRA_PROJECTION_SCHEMA_VERSION)
        if schema != ASTRA_PROJECTION_SCHEMA_VERSION:
            raise AstraError(
                f"unsupported workload schema_version {schema!r}")
        variant = doc.get("logical_artifact_variant", "V2")
        if variant not in LOGICAL_ARTIFACT_VARIANTS:
            raise AstraError(
                f"workload document logical_artifact_variant must be "
                f"one of {LOGICAL_ARTIFACT_VARIANTS}, got {variant!r}")
        return cls(
            messages=messages, participant_count=participant_count,
            **str_fields, compute_operations=compute,
            compute_owners=owners, collective_operations=collectives,
            mtu_bytes=mtu, schema_version=schema,
            logical_artifact_variant=variant)

    def canonical_bytes(self) -> bytes:
        return json.dumps(self.to_dict(), sort_keys=True,
                          separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8") + b"\n"

    def node_plan(self) -> tuple[tuple[int, str, dict], ...]:
        """The deterministic Chakra node plan shared by every rank.

        Node ids are assigned here, once, in canonical order (compute, then
        collectives, then messages), so the runtime's ``astra_node`` ledger
        field is reproducible from the projection alone.
        """
        plan: list[tuple[int, str, dict]] = []
        next_id = 1
        for op_id, duration_ns in self.compute_operations:
            plan.append((next_id, "COMP", {
                "operation_id": op_id, "duration_ns": duration_ns,
                "owner": self.compute_owner(op_id)}))
            next_id += 1
        if self.et_granularity == "collectives":
            op_classes = self.operation_traffic_classes()
            for op_id, kind, payload_bytes, participants in \
                    self.collective_operations:
                plan.append((next_id, "COLL", {
                    "operation_id": op_id, "collective_kind": kind,
                    "payload_bytes": payload_bytes,
                    "participants": participants,
                    "traffic_class": op_classes.get(op_id)}))
                next_id += 1
        for message in self.messages:
            if self.et_granularity == "collectives" \
                    and message.collective_kind is not None:
                continue
            plan.append((next_id, "MSG", {"message": message}))
            next_id += 1
        return tuple(plan)

    def collective_node_ids(self) -> tuple[tuple[str, int], ...]:
        """(operation_id, Chakra node id) for every emitted collective."""
        return tuple((payload["operation_id"], node_id)
                     for node_id, kind, payload in self.node_plan()
                     if kind == "COLL")

    def write_chakra(self, *, directory: str | os.PathLike[str],
                     stem: str = "workload") -> tuple[Path, ...]:
        """Write per-rank Chakra ET files the real runtime consumes.

Rationale: docs/decisions/modules/backend.md
        """
        try:
            from chakra.schema.protobuf import et_def_pb2 as pb
            from chakra.src.third_party.utils import protolib
        except Exception as exc:  # pragma: no cover - environment dependent
            raise AstraUnavailable(
                "the Chakra protobuf bindings are required to emit ET "
                f"artifacts: {exc}") from exc
        if not isinstance(stem, str) or not stem:
            raise AstraError("stem must be a non-empty string")
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)

        plan = self.node_plan()

        written: list[Path] = []
        for rank in self.ranks():
            path = target / f"{stem}.et.{rank}.et"
            nodes: list[Any] = []
            previous = 0
            for node_id, kind, payload in plan:
                node = None
                if kind == "COMP":
                    owner = payload.get("owner")
                    if owner is not None and owner != rank:
                        continue
                    node = pb.Node()
                    node.id = node_id
                    node.name = payload["operation_id"]
                    node.type = pb.COMP_NODE
                    node.duration_micros = compute_micros(
                        payload.get("duration_ns"),
                        payload.get("operation_id", "?"))
                elif kind == "COLL":
                    participants = payload["participants"]
                    if rank not in participants:
                        continue
                    node = pb.Node()
                    node.id = node_id
                    node.name = payload["operation_id"]
                    node.type = pb.COMM_COLL_NODE
                    node.duration_micros = 1
                    type_attr = node.attr.add()
                    type_attr.name = "comm_type"
                    setattr(type_attr,
                            _COMM_ATTR_FIELDS[self.comm_attr_abi][1],
                            _CHAKRA_COLLECTIVE_TYPE[
                                payload["collective_kind"]])
                    size_attr = node.attr.add()
                    size_attr.name = "comm_size"
                    setattr(size_attr,
                            _COMM_ATTR_FIELDS[self.comm_attr_abi][1],
                            payload["payload_bytes"])
                    op_class = payload.get("traffic_class")
                    if not isinstance(op_class, str) or not op_class:
                        raise AstraError(
                            f"collective node {node_id} "
                            f"({payload.get('operation_id')!r}) has no "
                            "bound traffic class: refusing a collapsed "
                            "class binding")
                    class_attr = node.attr.add()
                    class_attr.name = "veritx_traffic_class"
                    class_attr.string_val = op_class
                    dim = node.attr.add()
                    dim.name = "involved_dim"
                    dim.bool_list.values.append(True)
                else:
                    message = payload["message"]
                    is_src = message.src_rank == rank
                    is_dst = message.dst_rank == rank
                    if not (is_src or is_dst):
                        continue
                    node = pb.Node()
                    node.id = node_id
                    node.type = (pb.COMM_SEND_NODE if is_src
                                 else pb.COMM_RECV_NODE)
                    node.name = (f"{message.operation_id}#"
                                 f"{message.sequence}")
                    src = node.attr.add()
                    src.name = "comm_src"
                    setattr(src, _COMM_ATTR_FIELDS[self.comm_attr_abi][0],
                            message.src_rank)
                    dst = node.attr.add()
                    dst.name = "comm_dst"
                    setattr(dst, _COMM_ATTR_FIELDS[self.comm_attr_abi][0],
                            message.dst_rank)
                    size = node.attr.add()
                    size.name = "comm_size"
                    setattr(size, _COMM_ATTR_FIELDS[self.comm_attr_abi][1],
                            message.payload_bytes)
                    msg_class = node.attr.add()
                    msg_class.name = "veritx_traffic_class"
                    msg_class.string_val = message.traffic_class
                if node is None:  # pragma: no cover - defensive
                    continue
                if previous:
                    node.data_deps.append(previous)
                nodes.append(node)
                previous = node_id
            if not nodes:
                continue
            with open(path, "wb") as handle:
                metadata = pb.GlobalMetadata()
                attribute = metadata.attr.add()
                attribute.name = "schema"
                attribute.string_val = _CHAKRA_SCHEMA
                protolib.encodeMessage(handle, metadata)
                for node in nodes:
                    protolib.encodeMessage(handle, node)
            written.append(path)
        if written:
            base = target / f"{stem}.et"
            base.write_bytes(written[0].read_bytes())
            written.append(base)
        return tuple(written)

def _message_from_dict(doc: Any) -> AstraMessage:
    if not isinstance(doc, dict):
        raise AstraError("workload message must be a JSON object")
    try:
        int_fields = {
            name: doc[name] for name in (
                "sequence", "step", "src_rank", "dst_rank",
                "payload_bytes")}
        str_fields = {
            name: doc[name] for name in (
                "operation_id", "kind", "traffic_class")}
    except KeyError as exc:
        raise AstraError(f"workload message is missing {exc}") from exc
    for name, value in int_fields.items():
        if type(value) is not int or isinstance(value, bool):
            raise AstraError(
                f"workload message field {name!r} must be an int")
    for name, value in str_fields.items():
        if not isinstance(value, str) or not value:
            raise AstraError(
                f"workload message field {name!r} must be a non-empty "
                f"string")
    collective_kind = doc.get("collective_kind")
    if collective_kind is not None and not isinstance(collective_kind, str):
        raise AstraError("workload message collective_kind must be a "
                         "string or null")
    phase = doc.get("phase")
    if phase is not None and not isinstance(phase, str):
        raise AstraError(
            "workload message phase must be a string or null")
    fragments = doc.get("fragments")
    if not isinstance(fragments, list) or not fragments \
            or any(type(f) is not int or f <= 0 for f in fragments):
        raise AstraError(
            "workload message fragments must be a non-empty list of "
            "positive ints")
    return AstraMessage(
        **int_fields, **str_fields, collective_kind=collective_kind,
        phase=phase, fragments=tuple(fragments))

def _op_pairs(rows: Any, where: str) -> tuple[tuple[str, int], ...]:
    if not isinstance(rows, (list, tuple)):
        raise AstraError(f"workload document {where} must be a list")
    out = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 2 \
                or not isinstance(row[0], str) or not row[0] \
                or type(row[1]) is not int:
            raise AstraError(
                f"workload document {where} rows must be "
                f"[operation_id, int]")
        out.append((row[0], row[1]))
    return tuple(out)

def _owner_pairs(rows: Any) -> tuple[tuple[str, int | None], ...]:
    if not isinstance(rows, (list, tuple)):
        raise AstraError(
            "workload document compute_owners must be a list")
    out = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 2 \
                or not isinstance(row[0], str) or not row[0]:
            raise AstraError(
                "workload document compute_owners rows must be "
                "[operation_id, rank-or-null]")
        owner = row[1]
        if owner is not None and type(owner) is not int:
            raise AstraError(
                "workload document compute_owners rows must be "
                "[operation_id, rank-or-null]")
        out.append((row[0], owner))
    return tuple(out)

def _collective_rows(rows: Any) -> tuple[
        tuple[str, str, int, tuple[int, ...]], ...]:
    if not isinstance(rows, (list, tuple)):
        raise AstraError(
            "workload document collective_operations must be a list")
    out = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 4 \
                or not isinstance(row[0], str) or not row[0] \
                or not isinstance(row[1], str) or not row[1] \
                or type(row[2]) is not int \
                or not isinstance(row[3], list):
            raise AstraError(
                "workload document collective_operations rows must be "
                "[operation_id, kind, payload_bytes, participants]")
        parts = tuple(row[3])
        if any(type(p) is not int for p in parts):
            raise AstraError(
                "workload document collective participants must be ints")
        out.append((row[0], row[1], row[2], parts))
    return tuple(out)

@dataclass(frozen=True)
class AstraExecutionEvidence:
    """Canonical execution evidence. Only produced for complete runs."""

    status: str
    projection_id: str
    resolved_fabric_hash: str
    backend: str
    binary: str
    per_rank_cycles: tuple[tuple[int, int], ...]
    exposed_comm_cycles: tuple[tuple[int, int], ...]
    aggregate_cycles: int
    evidence_scope: str

    def per_rank_map(self) -> dict[int, int]:
        return dict(self.per_rank_cycles)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "projection_id": self.projection_id,
            "resolved_fabric_hash": self.resolved_fabric_hash,
            "backend": self.backend,
            "binary": self.binary,
            "per_rank_cycles": {str(r): c for r, c in self.per_rank_cycles},
            "exposed_comm_cycles": {str(r): c
                                    for r, c in self.exposed_comm_cycles},
            "aggregate_cycles": self.aggregate_cycles,
            "evidence_scope": self.evidence_scope,
        }

def parse_astra_cycles(stdout: str) -> tuple[dict[int, int], dict[int, int]]:
    """(per-rank cycles, per-rank exposed comm) from runtime stdout."""
    cycles: dict[int, int] = {}
    exposed: dict[int, int] = {}
    duplicates: set[int] = set()
    for line in stdout.splitlines():
        match = _CYCLES_RE.search(line)
        if match:
            rank = int(match.group(1))
            if rank in cycles:
                duplicates.add(rank)
            cycles.setdefault(rank, int(match.group(2)))
        exp = _EXPOSED_RE.search(line)
        if exp:
            exposed.setdefault(int(exp.group(1)), int(exp.group(2)))
    if duplicates:
        raise AstraExecutionError(
            f"runtime reported duplicate rank results for {sorted(duplicates)}")
    return cycles, exposed

def run_astra(*, binary: str | os.PathLike[str], projection: AstraWorkloadProjection,
              workload_configuration: str | os.PathLike[str],
              system_configuration: str | os.PathLike[str],
              network_configuration: str | os.PathLike[str],
              memory_configuration: str | os.PathLike[str],
              logging_folder: str | os.PathLike[str] | None = None,
              backend: str = "booksim", timeout_s: int = 300,
              runner: Callable[..., Any] | None = None,
              extra_args: tuple[str, ...] = ()) -> AstraExecutionEvidence:
    """Execute the real ASTRA runtime; fail closed on any deviation."""
    if not isinstance(projection, AstraWorkloadProjection):
        raise AstraError("projection must be an AstraWorkloadProjection")
    binary_path = Path(binary)
    if not binary_path.exists():
        raise AstraUnavailable(
            f"ASTRA runtime binary not found: {binary_path}")
    for name, value in (("workload", workload_configuration),
                        ("system", system_configuration),
                        ("network", network_configuration),
                        ("memory", memory_configuration)):
        if not Path(value).exists():
            raise AstraExecutionError(
                f"{name} configuration not found: {value}")

    command = [
        str(binary_path),
        "--workload-configuration", str(workload_configuration),
        "--system-configuration", str(system_configuration),
        "--network-configuration", str(network_configuration),
        "--remote-memory-configuration", str(memory_configuration),
    ]
    if logging_folder is not None:
        command += ["--logging-configuration", "empty",
                    "--logging-folder", str(logging_folder)]
    command += ["--booksim2-extra=injection_rate=0.0", *extra_args]

    if runner is None:
        def runner(cmd, timeout):  # pragma: no cover - real process
            return subprocess.run(cmd, stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True,
                                  timeout=timeout)
    try:
        proc = runner(command, timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise AstraExecutionError(
            f"ASTRA runtime timed out after {timeout_s}s") from exc

    if proc.returncode != 0:
        tail = (proc.stderr or "")[-400:]
        raise AstraExecutionError(
            f"ASTRA runtime exited {proc.returncode}: {tail}")
    cycles, exposed = parse_astra_cycles(proc.stdout or "")
    expected = set(projection.ranks())
    if set(cycles) != expected:
        missing = sorted(expected - set(cycles))
        extra = sorted(set(cycles) - expected)
        raise AstraExecutionError(
            "runtime did not report exactly the participant ranks "
            f"(missing={missing}, unexpected={extra})")
    if any(value <= 0 for value in cycles.values()):
        raise AstraExecutionError(
            "runtime reported a non-positive cycle count; refusing to "
            "treat this as execution")
    ordered = tuple(sorted(cycles.items()))
    aggregate = max(value for _, value in ordered)
    if projection.total_payload_bytes() > 0 \
            and aggregate <= projection.declared_compute_cycles():
        raise AstraExecutionError(
            f"runtime simulated no communication for "
            f"{projection.total_payload_bytes()} projected bytes "
            f"(aggregate {aggregate} <= declared compute floor "
            f"{projection.declared_compute_cycles()}); this runtime does "
            "not simulate the projected comm nodes. Refusing to report "
            "execution")
    return AstraExecutionEvidence(
        status="EXECUTED", projection_id=projection.projection_id(),
        resolved_fabric_hash=projection.resolved_fabric_hash,
        backend=backend, binary=str(binary_path),
        per_rank_cycles=ordered,
        exposed_comm_cycles=tuple(sorted(exposed.items())),
        aggregate_cycles=aggregate,
        evidence_scope=projection.evidence_scope())

def compare_per_rank(a: AstraExecutionEvidence,
                     b: AstraExecutionEvidence) -> dict[str, Any]:
    """Bit-identical differential between two runs (requalification aid)."""
    left, right = a.per_rank_map(), b.per_rank_map()
    common = sorted(set(left) & set(right))
    identical = [r for r in common if left[r] == right[r]]
    return {
        "common_ranks": len(common),
        "bit_identical_ranks": len(identical),
        "differing_ranks": sorted(set(common) - set(identical)),
        "left_binary": a.binary, "right_binary": b.binary,
    }

def resolve_runtime_binary() -> Path | None:
    """The canonical runtime location, or an explicit override. No guessing."""
    override = os.environ.get("VERITX_ASTRA_BIN")
    if override:
        path = Path(override)
        return path if path.exists() else None
    from veritx_dse.core.paths import ASTRA_BS_BIN
    return ASTRA_BS_BIN if ASTRA_BS_BIN.exists() else None

__all__ = [
    "ASTRA_PROJECTION_SCHEMA_VERSION", "AstraError", "AstraExecutionError",
    "AstraExecutionEvidence", "AstraLoweringRefused", "AstraMessage",
    "AstraUnavailable", "AstraWorkloadProjection", "COMM_ATTR_ABI",
    "ET_GRANULARITY", "LOWERED",
    "LOWERING_SEMANTICS_VERSION", "UNSUPPORTED", "ZERO_TRAFFIC",
    "audit_operations", "classify_operation", "compare_per_rank",
    "fragment_payload", "parse_astra_cycles", "resolve_runtime_binary",
    "run_astra",
]
