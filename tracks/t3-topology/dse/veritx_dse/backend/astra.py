"""veritx_dse.backend.astra — canonical ASTRA/Chakra projection + execution.

    LogicalMessageArtifactV2 + ResolvedFabric + Mapping + Attachment
            |
            v
    AstraWorkloadProjection          (this module: canonical projection)
            |
            v
    Chakra ET artifacts              (real protobuf, per rank)
            |
            v
    existing AstraSim_BookSim2 runtime
            |
            v
    AstraExecutionEvidence           (fail-closed execution result)

ABSTRACTION BOUNDARY (deliberate)

ASTRA is itself a system simulator that owns communication-event generation.
This adapter consumes **logical messages**, never ``PhysicalTrafficArtifactV2``:
the BookSim-oriented flit decomposition would double-packetize and duplicate
the transport semantics ASTRA already models. Wire-level data enters only if a
specific runtime genuinely requires it (it does not today).

SINGLE COLLECTIVE AUTHORITY

Slice 29 expanded collectives into canonical logical messages; this module
must not expand them again. Each logical message becomes one
``COMM_SEND_NODE`` / ``COMM_RECV_NODE`` pair (the runtime supports both and
reads ``comm_src``/``comm_dst``/``comm_size`` attributes), so the ring
schedule lives in exactly one place.

UNSUPPORTED vs ZERO

An operation with no canonical network lowering is REFUSED, never silently
reduced to zero traffic. ``audit_operations`` distinguishes
``ZERO_TRAFFIC`` (genuinely no network work) from ``LOWERED`` and from
``UNSUPPORTED``. MULTICAST logical messages are replicated-unicast traffic
and evidence is labelled as such — they are not physical multicast.
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
from veritx_dse.workload.messages import LogicalMessageArtifactV2

ASTRA_PROJECTION_SCHEMA_VERSION = 1
LOWERING_SEMANTICS_VERSION = 1
_PROJECTION_TYPE_TAG = "srota/AstraWorkloadProjection"
_CHAKRA_SCHEMA = "1.0.2-chakra.0.0.4"

#: canonical operation classification
ZERO_TRAFFIC = "ZERO_TRAFFIC"
LOWERED = "LOWERED"
UNSUPPORTED = "UNSUPPORTED"

#: Chakra comm-attribute scalar ABI.
#: The vendored feeder (extern/graph_frontend/chakra/src/feeder/et_feeder_node.cpp)
#: reads comm_src/comm_dst from int32_val and comm_size from int64_val, while
#: the previously qualified historical fixture stores them in uint32/uint64_val
#: and is consumed successfully by the archived runtime. The ABI is therefore an
#: EXPLICIT, identity-bound lowering parameter, never an assumption.
COMM_ATTR_ABI = ("uint", "int")
_DEFAULT_COMM_ATTR_ABI = "uint"
#: (src/dst scalar field, size scalar field) per ABI
_COMM_ATTR_FIELDS = {"uint": ("uint32_val", "uint64_val"),
                     "int": ("int32_val", "int64_val")}

#: Chakra ET granularity. WHICH AUTHORITY EXPANDS THE COLLECTIVE is recorded
#: in the projection identity, never left implicit:
#:   "messages"    - one COMM_SEND/COMM_RECV pair per canonical logical
#:                   message; the Slice-29 schedule owns expansion.
#:   "collectives" - one COMM_COLL_NODE per collective OPERATION, which
#:                   DELEGATES expansion to ASTRA. Only for runtimes that do
#:                   not simulate the send/recv path; evidence is labelled.
ET_GRANULARITY = ("messages", "collectives")
_DEFAULT_ET_GRANULARITY = "messages"
#: canonical collective kind -> Chakra CollectiveCommType number
_CHAKRA_COLLECTIVE_TYPE = {"ALLREDUCE": 0, "ALLGATHER": 2, "BROADCAST": 5,
                           "ALLTOALL": 6, "REDUCESCATTER": 7}

#: kinds that never produce network traffic (and are NOT unsupported)
_ZERO_TRAFFIC_KINDS = (KIND_COMPUTE, KIND_PIM_CHANNEL, KIND_PIM_END)
#: kinds whose messages are projected as unicast send/recv pairs
_LOWERED_KINDS = (KIND_COLLECTIVE, KIND_P2P, KIND_MULTICAST, KIND_EXPERT_BEGIN,
                  KIND_EXPERT_END)

_CYCLES_RE = re.compile(r"sys\[(\d+)\] finished, (\d+) cycles")
_EXPOSED_RE = re.compile(
    r"sys\[(\d+)\] finished, \d+ cycles, exposed communication (\d+) cycles")


class AstraError(ValueError):
    """Base for ASTRA adapter refusals and failures."""


class AstraUnavailable(AstraError):
    """The runtime binary or the Chakra protobuf bindings are not available."""


class AstraLoweringRefused(AstraError):
    """The canonical workload has no ASTRA lowering for some operation."""


class AstraExecutionError(AstraError):
    """Execution failed, partially executed, or produced malformed evidence."""


# ── semantic audit ─────────────────────────────────────────────────────────

def classify_operation(op: Any) -> str:
    """ZERO_TRAFFIC | LOWERED | UNSUPPORTED for one canonical operation."""
    if op.kind in _ZERO_TRAFFIC_KINDS:
        return ZERO_TRAFFIC
    if op.kind in _LOWERED_KINDS:
        # An EXPERT region without a declared collective is genuinely zero.
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


# ── MTU / fragmentation boundary ───────────────────────────────────────────

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


# ── the projection ─────────────────────────────────────────────────────────

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
    #: (operation_id, owner) parallel to ``compute_operations``; ``owner=None``
    #: keeps the historical global-compute semantics (the node appears in
    #: every rank's ET), ``owner=rank`` emits it only into that rank's ET.
    #: Kept separate from ``compute_operations`` so existing global-compute
    #: projections keep their identity byte for byte.
    compute_owners: tuple[tuple[str, int | None], ...] = ()
    #: (operation_id, collective_kind, declared payload_bytes, participants)
    collective_operations: tuple[tuple[str, str, int, tuple[int, ...]], ...] = ()
    mtu_bytes: int | None = None
    comm_attr_abi: str = _DEFAULT_COMM_ATTR_ABI
    et_granularity: str = _DEFAULT_ET_GRANULARITY
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

    # -- construction ----------------------------------------------------
    @classmethod
    def build(cls, *, logical: LogicalMessageArtifactV2,
              resolved_fabric: ResolvedFabric, mapping: MappingArtifact,
              attachment: AgentAttachmentArtifact,
              mtu_bytes: int | None = None,
              comm_attr_abi: str = _DEFAULT_COMM_ATTR_ABI,
              et_granularity: str = _DEFAULT_ET_GRANULARITY
              ) -> "AstraWorkloadProjection":
        """Project canonical messages; refuse unsupported semantics."""
        if not isinstance(logical, LogicalMessageArtifactV2):
            raise AstraError("logical must be a LogicalMessageArtifactV2")
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
        # Ownership is a projection fact, not a second participant model:
        # it reuses the canonical OperationNode.owner the graph already
        # validates against the participant namespace.
        owners = tuple(
            (op.operation_id, op.owner)
            for op in logical.graph.ordered_operations()
            if op.kind == KIND_COMPUTE)
        # The DECLARED per-operation collective payload is design intent; it
        # is what a delegating ET must carry. Ring chunk sizes are schedule
        # detail and must never be mistaken for the collective's payload.
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
            et_granularity=et_granularity)

    # -- accessors -------------------------------------------------------
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

        Rank-parallel owned compute must not be summed as if every rank ran
        every chain serially: a rank's chain is the global (unowned) compute
        plus the compute it owns, and the floor is the *maximum* chain.  With
        no owned compute this is exactly the historical
        ``sum(cycles) * 1000``.
        """
        global_micros = 0
        owned_micros: dict[int, int] = {}
        for op_id, duration_ns in self.compute_operations:
            micros = max(1, int(duration_ns) // 1000)
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

    # -- identity --------------------------------------------------------
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
            for op_id, kind, payload_bytes, participants in \
                    self.collective_operations:
                plan.append((next_id, "COLL", {
                    "operation_id": op_id, "collective_kind": kind,
                    "payload_bytes": payload_bytes,
                    "participants": participants}))
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

    # -- Chakra ET emission (real protobuf, never a JSON imitation) ------
    def write_chakra(self, *, directory: str | os.PathLike[str],
                     stem: str = "workload") -> tuple[Path, ...]:
        """Write per-rank Chakra ET files the real runtime consumes.

        Granularity is explicit (``et_granularity``):
          * ``messages``    - COMM_SEND/COMM_RECV per canonical logical
                              message; the Slice-29 schedule owns expansion.
          * ``collectives`` - COMM_COLL_NODE per collective operation,
                              delegating expansion to ASTRA.
        Either way this method never invents a second collective algorithm.
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

        # one canonical node plan, shared by every rank
        plan = self.node_plan()

        written: list[Path] = []
        for rank in self.ranks():
            # the runtime derives per-rank paths as
            # ``<workload-configuration>.<rank>.et`` (Workload.cc)
            path = target / f"{stem}.et.{rank}.et"
            nodes: list[Any] = []
            previous = 0
            for node_id, kind, payload in plan:
                node = None
                if kind == "COMP":
                    owner = payload.get("owner")
                    if owner is not None and owner != rank:
                        continue    # owned compute: this rank's ET only
                    node = pb.Node()
                    node.id = node_id
                    node.name = payload["operation_id"]
                    node.type = pb.COMP_NODE
                    node.duration_micros = max(
                        1, int(payload["duration_ns"]) // 1000)
                elif kind == "COLL":
                    participants = payload["participants"]
                    if rank not in participants:
                        continue        # no node on this rank
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
                if node is None:  # pragma: no cover - defensive
                    continue
                if previous:
                    node.data_deps.append(previous)
                nodes.append(node)
                previous = node_id
            if not nodes:
                # An EMPTY ET is not a valid workload: the runtime's
                # dependency solver refuses a layer with no dependency-free
                # node.  A MISSING rank file is how the runtime expresses an
                # idle NPU (Workload.cc + the interactive loader), so an
                # idle rank is expressed by writing nothing at all.
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

# ── runtime adapter ────────────────────────────────────────────────────────

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
    # Template cfgs self-inject; embedded mode owns the injection rate.
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
    # Fail closed on SILENT NON-SIMULATION: a build that ignores the
    # send/recv path still exits 0 with all ranks reported, but the total
    # never rises above the declared compute floor. Communication was
    # projected, so "no communication time" is a refusal, not a result.
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
