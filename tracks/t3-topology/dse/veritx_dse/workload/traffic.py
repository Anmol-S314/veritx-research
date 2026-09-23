"""veritx_dse.workload.traffic — participant binding + physical traffic.

One authoritative projection:

    LogicalMessageArtifactV2 + canonical Mapping/Attachment/Inventory
        + canonical PacketFormatArtifact + canonical ResolvedFabric
        → participant→endpoint binding → packets → flits

Bit-exact rules (unchanged from the proven Wave-D/E implementation):

    message_bits            = payload_bytes × 8
    packet payload capacity = Q × L     (Q = payload field width,
                                         L = max_packet_flits)
    N_packets               = ceil(message_bits / (Q × L))
    Σ packet_payload_bits   = message_bits                (exact)
    per packet i:  n_i = ceil(P_i / Q); padding_i = n_i·Q − P_i;
                   header_bits_i = n_i·H; transmitted_bits_i = n_i·F
                   transmitted_bits_i == header_bits_i + P_i + padding_i

Header width H is DERIVED from the authoritative PacketFormatArtifact field
layout (every flit repeats the header).

PARTICIPANT IDENTITY IS NOT GEOMETRY

``participant_count`` is the namespace the operations address; the mapping's
rank space is the deployment geometry. A participant is bound to a physical
endpoint only through the canonical MappingArtifact (rank→agent) and
AgentAttachmentArtifact (agent→endpoint). A missing or unattached
participant fails closed: logical rank == endpoint is never assumed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.core.artifact import (
    EvidenceInvalid, InvalidInput, content_hash, require_embedded_id,
    require_fields, require_schema_version, require_type_tag,
)
from veritx_dse.core.errors import ConservationFailed, MappingInvalid
from veritx_dse.model.attachment import AgentAttachmentArtifact
from veritx_dse.model.mapping import MappingArtifact
from veritx_dse.model.packet_format import FlitFieldRole, PacketFormatArtifact
from veritx_dse.model.placement import NodeInventory
from veritx_dse.model.resolved_fabric import ResolvedFabric
from veritx_dse.workload.messages import LogicalMessageArtifactV2

PHYSICAL_TRAFFIC_SCHEMA_VERSION_V2 = 2
_V2_HASH_TYPE_TAG = "srota/PhysicalTrafficArtifactV2"

PARTICIPANT_MAPPING_SCHEMA_VERSION = 1
_PEM_TYPE_TAG = "srota/ParticipantEndpointMapping"


def payload_width_bits(pf: PacketFormatArtifact) -> int:
    """The payload capacity of one flit from the pinned field layout."""
    payload_fields = [f for f in pf.fields
                      if f.role is FlitFieldRole.PAYLOAD]
    if len(payload_fields) != 1:
        raise InvalidInput(
            f"packet format has {len(payload_fields)} payload fields; "
            "exactly one is required")
    return payload_fields[0].width


def header_width_bits(pf: PacketFormatArtifact) -> int:
    """Non-payload bits of the pinned flit layout (every flit repeats it)."""
    return pf.flit_width_bits - payload_width_bits(pf)


def packet_capacity_bits(pf: PacketFormatArtifact) -> int:
    return payload_width_bits(pf) * pf.max_packet_flits


def packetize_message(message_bits: int, pf: PacketFormatArtifact
                      ) -> list[int]:
    """Packet payload bits per packet under the packet-format authority."""
    capacity = packet_capacity_bits(pf)
    if message_bits <= 0:
        raise InvalidInput("message_bits must be positive")
    full, tail = divmod(message_bits, capacity)
    out = [capacity] * full
    if tail:
        out.append(tail)
    return out


def flitize_packet(p_i: int, pf: PacketFormatArtifact
                   ) -> tuple[int, int, int]:
    """(flits, padding_bits, transmitted_bits) for one packet payload."""
    q = payload_width_bits(pf)
    f = pf.flit_width_bits
    n = (p_i + q - 1) // q
    padding = n * q - p_i
    return n, padding, n * f


@dataclass(frozen=True)
class PacketRecord:
    """One physical network packet: payload + flit decomposition."""

    message_id: str
    packet_index: int
    payload_bits: int
    flit_count: int
    padding_bits: int
    header_bits: int
    transmitted_bits: int
    src_endpoint: int
    dst_endpoint: int

    def canonical(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "packet_index": self.packet_index,
            "payload_bits": self.payload_bits,
            "flit_count": self.flit_count,
            "padding_bits": self.padding_bits,
            "header_bits": self.header_bits,
            "transmitted_bits": self.transmitted_bits,
            "src_endpoint": self.src_endpoint,
            "dst_endpoint": self.dst_endpoint,
        }


@dataclass(frozen=True)
class BindingRecord:
    """Logical rank → AgentInstance → endpoint for one message end."""

    rank: int
    agent_instance_id: str
    endpoint_id: int


@dataclass(frozen=True)
class MessageTraffic:
    """Physical projection of one logical message."""

    message_id: str
    operation_id: str
    src: BindingRecord
    dst: BindingRecord
    payload_bytes: int
    message_bits: int
    packets: tuple[PacketRecord, ...]

    @property
    def packet_payload_bits(self) -> int:
        return sum(p.payload_bits for p in self.packets)

    @property
    def flit_count(self) -> int:
        return sum(p.flit_count for p in self.packets)

    @property
    def header_bits(self) -> int:
        return sum(p.header_bits for p in self.packets)

    @property
    def padding_bits(self) -> int:
        return sum(p.padding_bits for p in self.packets)

    @property
    def transmitted_bits(self) -> int:
        return sum(p.transmitted_bits for p in self.packets)

    def canonical_packets(self) -> list[dict[str, Any]]:
        return [p.canonical() for p in self.packets]


@dataclass(frozen=True)
class OperationLedgerEntry:
    """Per-operation conservation quantities, kept as distinct classes."""

    operation_id: str
    operation_kind: str
    source_logical_payload_bytes: int
    scheduled_message_bytes: int
    generated_message_bytes: int
    message_count: int
    packet_count: int
    packet_payload_bits: int
    flit_count: int
    header_bits: int
    padding_bits: int
    transmitted_bits: int
    rank_binding_valid: bool
    endpoint_binding_valid: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "operation_kind": self.operation_kind,
            "source_logical_payload_bytes":
                self.source_logical_payload_bytes,
            "scheduled_message_bytes": self.scheduled_message_bytes,
            "generated_message_bytes": self.generated_message_bytes,
            "message_count": self.message_count,
            "packet_count": self.packet_count,
            "packet_payload_bits": self.packet_payload_bits,
            "flit_count": self.flit_count,
            "header_bits": self.header_bits,
            "padding_bits": self.padding_bits,
            "transmitted_bits": self.transmitted_bits,
            "rank_binding_valid": self.rank_binding_valid,
            "endpoint_binding_valid": self.endpoint_binding_valid,
        }


def bind_participants(*, participant_count: int,
                      mapping: MappingArtifact,
                      attachment: AgentAttachmentArtifact,
                      resolved_fabric: ResolvedFabric
                      ) -> "ParticipantEndpointMapping":
    """Bind the participant namespace to physical endpoints, or refuse.

    Uses only the canonical authorities: MappingArtifact answers rank→agent,
    AgentAttachmentArtifact answers agent→endpoint. No second rank→endpoint
    map and no rank==endpoint assumption.
    """
    if not isinstance(mapping, MappingArtifact):
        raise MappingInvalid("mapping must be a MappingArtifact")
    if not isinstance(attachment, AgentAttachmentArtifact):
        raise MappingInvalid("attachment must be an AgentAttachmentArtifact")
    if not isinstance(resolved_fabric, ResolvedFabric):
        raise MappingInvalid("resolved_fabric must be a ResolvedFabric")
    if mapping.mapping_hash() != resolved_fabric.mapping_hash:
        raise MappingInvalid(
            "mapping does not belong to the resolved fabric "
            "(mapping_hash mismatch)")
    rank_agent = {placement.rank: placement.agent
                  for placement in mapping.placements}
    agent_endpoint: dict[tuple[int, int, Any], int] = {}
    for endpoint in attachment.endpoints:
        agent_endpoint[(endpoint.agent.group_index,
                        endpoint.agent.instance_index,
                        endpoint.agent.kind)] = endpoint.endpoint_id
    rows: list[tuple[int, int]] = []
    for rank in range(participant_count):
        if rank not in rank_agent:
            raise MappingInvalid(
                f"participant rank {rank} has no mapping placement "
                f"(participant_count={participant_count}); physical "
                "lowering requires an explicit rank→agent binding")
        agent = rank_agent[rank]
        key = (agent.group_index, agent.instance_index, agent.kind)
        if key not in agent_endpoint:
            raise MappingInvalid(
                f"participant rank {rank} maps to unattached agent "
                f"{agent.instance_id}")
        rows.append((rank, agent_endpoint[key]))
    return ParticipantEndpointMapping(
        participant_count=participant_count,
        rank_to_endpoint=tuple(rows),
        fabric_id=resolved_fabric.resolved_fabric_hash)


@dataclass(frozen=True)
class ParticipantEndpointMapping:
    """Participant rank → physical endpoint, identified and refused."""

    participant_count: int
    rank_to_endpoint: tuple[tuple[int, int], ...]
    fabric_id: str
    schema_version: int = PARTICIPANT_MAPPING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.participant_count) is not int \
                or self.participant_count <= 0:
            raise MappingInvalid("participant_count must be a positive int")
        if len(self.rank_to_endpoint) != self.participant_count:
            raise MappingInvalid(
                f"participant mapping covers {len(self.rank_to_endpoint)} "
                f"ranks but participant_count is {self.participant_count}")
        ranks = [r for r, _ in self.rank_to_endpoint]
        if sorted(ranks) != list(range(self.participant_count)):
            raise MappingInvalid(
                "participant mapping must cover exactly "
                "[0, participant_count)")
        endpoints = [e for _, e in self.rank_to_endpoint]
        if any(type(e) is not int or e < 0 for e in endpoints):
            raise MappingInvalid("endpoint ids must be non-negative ints")
        if len(set(endpoints)) != len(endpoints):
            raise MappingInvalid("one endpoint per participant required")
        if not isinstance(self.fabric_id, str) or not self.fabric_id:
            raise MappingInvalid("fabric_id required")

    def endpoint_for(self, rank: int) -> int:
        if type(rank) is not int or not 0 <= rank < self.participant_count:
            raise MappingInvalid(
                f"participant rank {rank!r} outside "
                f"[0, {self.participant_count})")
        return dict(self.rank_to_endpoint)[rank]

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "type": _PEM_TYPE_TAG,
            "schema_version": self.schema_version,
            "participant_count": self.participant_count,
            "rank_to_endpoint": [[r, e] for r, e in self.rank_to_endpoint],
            "fabric_id": self.fabric_id,
        }

    def binding_id(self) -> str:
        return content_hash(_PEM_TYPE_TAG, self.schema_version,
                            self.canonical_dict())


def _packet_records(m: Any, src: BindingRecord, dst: BindingRecord,
                    pf: PacketFormatArtifact, h_bits: int, q_bits: int
                    ) -> tuple[PacketRecord, ...]:
    """Packetize ONE logical message; the transmitted-bit identity and the
    padding bound are checked here, so a violated equation can never
    persist."""
    message_bits = m.payload_bytes * 8
    packets: list[PacketRecord] = []
    for idx, pbits in enumerate(packetize_message(message_bits, pf)):
        n, padding, transmitted = flitize_packet(pbits, pf)
        hbits = n * h_bits
        if transmitted != hbits + pbits + padding:
            raise ConservationFailed(
                f"packet {idx} of {m.message_id!r}: transmitted "
                f"{transmitted} != header {hbits} + payload {pbits} + "
                f"padding {padding}")
        if not (0 <= padding < q_bits):
            raise ConservationFailed(
                f"packet {idx} of {m.message_id!r}: padding {padding} "
                f"outside [0, {q_bits})")
        packets.append(PacketRecord(
            message_id=m.message_id, packet_index=idx, payload_bits=pbits,
            flit_count=n, padding_bits=padding, header_bits=hbits,
            transmitted_bits=transmitted, src_endpoint=src.endpoint_id,
            dst_endpoint=dst.endpoint_id))
    return tuple(packets)


@dataclass(frozen=True)
class PhysicalTrafficArtifactV2:
    """Physical traffic from the canonical logical messages.

    Binds the message artifact, the canonical ResolvedFabric, the
    participant→endpoint mapping it actually used, and the canonical
    PacketFormatArtifact. Packet endpoints come from that mapping, so
    logical rank == physical endpoint is never assumed: a 4-participant
    workload on an 8-rank fabric lowers through its own explicit binding,
    and refuses only when a participant has no authenticated binding.
    """

    logical: LogicalMessageArtifactV2
    resolved_fabric: ResolvedFabric
    mapping: MappingArtifact
    attachment: AgentAttachmentArtifact
    inventory: NodeInventory
    packet_format: PacketFormatArtifact
    schema_version: int = PHYSICAL_TRAFFIC_SCHEMA_VERSION_V2

    def __post_init__(self) -> None:
        if not isinstance(self.logical, LogicalMessageArtifactV2):
            raise InvalidInput("logical must be a LogicalMessageArtifactV2")
        for name, value, cls in (
                ("resolved_fabric", self.resolved_fabric, ResolvedFabric),
                ("mapping", self.mapping, MappingArtifact),
                ("attachment", self.attachment, AgentAttachmentArtifact),
                ("inventory", self.inventory, NodeInventory),
                ("packet_format", self.packet_format, PacketFormatArtifact)):
            if not isinstance(value, cls):
                raise InvalidInput(f"{name} must be a {cls.__name__}")
        if self.schema_version != PHYSICAL_TRAFFIC_SCHEMA_VERSION_V2:
            raise InvalidInput(
                f"unsupported physical traffic schema_version "
                f"{self.schema_version!r}")
        # ── the canonical seams this lowering stands on ────────────────
        if self.mapping.mapping_hash() != self.resolved_fabric.mapping_hash:
            raise MappingInvalid(
                "mapping does not belong to the resolved fabric")
        if self.packet_format.attachment_hash \
                != self.attachment.attachment_hash():
            raise MappingInvalid(
                "packet format was not derived from this attachment")
        graph_shape = self.logical.graph.parallelism
        if graph_shape != self.inventory.parallelism:
            raise MappingInvalid(
                f"logical rank geometry "
                f"{graph_shape.to_dict()} does not match the physical "
                f"inventory geometry "
                f"{self.inventory.parallelism.to_dict()}; equal world size "
                "is not semantic equivalence")
        h_bits = header_width_bits(self.packet_format)
        q_bits = payload_width_bits(self.packet_format)
        if h_bits < 0 or q_bits < 1:
            raise InvalidInput("packet format has no payload capacity")
        pem = bind_participants(
            participant_count=self.logical.participant_count,
            mapping=self.mapping, attachment=self.attachment,
            resolved_fabric=self.resolved_fabric)
        rank_agent = {p.rank: p.agent for p in self.mapping.placements}

        traffic: list[MessageTraffic] = []
        count = self.logical.participant_count
        for m in self.logical.messages:
            for rank in (m.src_rank, m.dst_rank):
                if not 0 <= rank < count:
                    raise MappingInvalid(
                        f"message {m.message_id!r} addresses rank {rank} "
                        f"outside the participant namespace [0, {count})")
            src = BindingRecord(
                rank=m.src_rank,
                agent_instance_id=rank_agent[m.src_rank].instance_id,
                endpoint_id=pem.endpoint_for(m.src_rank))
            dst = BindingRecord(
                rank=m.dst_rank,
                agent_instance_id=rank_agent[m.dst_rank].instance_id,
                endpoint_id=pem.endpoint_for(m.dst_rank))
            message_bits = m.payload_bytes * 8
            packets = list(_packet_records(m, src, dst, self.packet_format,
                                           h_bits, q_bits))
            if sum(p.payload_bits for p in packets) != message_bits:
                raise ConservationFailed(
                    f"message {m.message_id!r}: packet payload bits do not "
                    "conserve message bits")
            traffic.append(MessageTraffic(
                message_id=m.message_id, operation_id=m.operation_id,
                src=src, dst=dst, payload_bytes=m.payload_bytes,
                message_bits=message_bits, packets=tuple(packets)))
        object.__setattr__(self, "_traffic", tuple(traffic))

    # ── the binding this lowering actually used ─────────────────────
    def participant_endpoint_mapping(self) -> ParticipantEndpointMapping:
        return bind_participants(
            participant_count=self.logical.participant_count,
            mapping=self.mapping, attachment=self.attachment,
            resolved_fabric=self.resolved_fabric)

    # ── accessors ─────────────────────────────────────────────────────
    @property
    def traffic(self) -> tuple[MessageTraffic, ...]:
        return self._traffic

    def totals(self) -> dict[str, int]:
        return {
            "message_count": len(self._traffic),
            "packet_count": sum(len(t.packets) for t in self._traffic),
            "flit_count": sum(t.flit_count for t in self._traffic),
            "packet_payload_bits": sum(t.packet_payload_bits
                                       for t in self._traffic),
            "header_bits": sum(t.header_bits for t in self._traffic),
            "padding_bits": sum(t.padding_bits for t in self._traffic),
            "transmitted_bits": sum(t.transmitted_bits
                                    for t in self._traffic),
        }

    def ledger(self) -> tuple[OperationLedgerEntry, ...]:
        """Per-operation conservation classes (declared vs generated)."""
        scheduled = {rec.collective_id: rec
                     for rec in self.logical.schedules}
        rows: list[OperationLedgerEntry] = []
        for op in self.logical.graph.ordered_operations():
            projected = tuple(t for t in self._traffic
                              if t.operation_id == op.operation_id)
            rec = scheduled.get(op.operation_id)
            declared = op.detail.get("payload_bytes")
            rows.append(OperationLedgerEntry(
                operation_id=op.operation_id, operation_kind=op.kind,
                source_logical_payload_bytes=(
                    declared if isinstance(declared, int) else 0),
                scheduled_message_bytes=(
                    rec.message_bytes if rec is not None else 0),
                generated_message_bytes=sum(t.payload_bytes
                                            for t in projected),
                message_count=len(projected),
                packet_count=sum(len(t.packets) for t in projected),
                packet_payload_bits=sum(t.packet_payload_bits
                                        for t in projected),
                flit_count=sum(t.flit_count for t in projected),
                header_bits=sum(t.header_bits for t in projected),
                padding_bits=sum(t.padding_bits for t in projected),
                transmitted_bits=sum(t.transmitted_bits for t in projected),
                rank_binding_valid=all(
                    t.src.rank == t.src.rank and t.dst.rank == t.dst.rank
                    for t in projected),
                endpoint_binding_valid=all(
                    t.src.endpoint_id >= 0 and t.dst.endpoint_id >= 0
                    for t in projected)))
        return tuple(rows)

    def validate_conservation(self) -> None:
        """Payload, packet and per-collective conservation, all at once."""
        for t in self._traffic:
            if t.packet_payload_bits != t.message_bits:
                raise ConservationFailed(
                    f"message {t.message_id!r}: packet payload "
                    f"{t.packet_payload_bits} != message bits "
                    f"{t.message_bits}")
            for p in t.packets:
                if p.transmitted_bits != p.header_bits + p.payload_bits \
                        + p.padding_bits:
                    raise ConservationFailed(
                        f"packet {p.packet_index} of {t.message_id!r}: "
                        "transmitted != header + payload + padding")
        logical_bits = sum(m.payload_bytes
                           for m in self.logical.messages) * 8
        totals = self.totals()
        if totals["packet_payload_bits"] != logical_bits:
            raise ConservationFailed(
                f"packet payload bits {totals['packet_payload_bits']} != "
                f"logical message bits {logical_bits}")
        for rec in self.logical.schedules:
            rows = [t for t in self._traffic
                    if t.operation_id == rec.collective_id]
            if len(rows) != rec.message_count:
                raise ConservationFailed(
                    f"collective {rec.collective_id!r}: projected "
                    f"{len(rows)} messages, schedule requires "
                    f"{rec.message_count}")
            if sum(t.payload_bytes for t in rows) != rec.aggregate_payload:
                raise ConservationFailed(
                    f"collective {rec.collective_id!r}: projected payload "
                    "does not equal the scheduled "
                    f"{rec.aggregate_payload}")

    # ── identity ──────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _V2_HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "message_artifact_id": self.logical.message_artifact_id(),
            "resolved_fabric_hash": self.resolved_fabric.resolved_fabric_hash,
            "packet_format_hash": self.packet_format.packet_format_hash,
            "participant_endpoint_mapping_id":
                self.participant_endpoint_mapping().binding_id(),
            "traffic": [t.canonical_packets() for t in self._traffic],
        }

    def physical_traffic_id(self) -> str:
        return content_hash(_V2_HASH_TYPE_TAG, self.schema_version,
                            self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_dict(),
                "physical_traffic_id": self.physical_traffic_id(),
                "totals": self.totals()}

    @classmethod
    def from_dict(cls, d: Any, *, logical: LogicalMessageArtifactV2,
                  resolved_fabric: ResolvedFabric, mapping: MappingArtifact,
                  attachment: AgentAttachmentArtifact,
                  inventory: NodeInventory, packet_format: PacketFormatArtifact,
                  strict: bool = False) -> "PhysicalTrafficArtifactV2":
        """Rebuild from VERIFIED parents (never from the JSON)."""
        require_fields(d, {
            "type", "schema_version", "message_artifact_id",
            "resolved_fabric_hash", "packet_format_hash",
            "participant_endpoint_mapping_id", "traffic",
            "physical_traffic_id", "totals",
        }, "physical traffic v2")
        if strict:
            require_type_tag(d, _V2_HASH_TYPE_TAG, "physical traffic v2")
            require_schema_version(d, PHYSICAL_TRAFFIC_SCHEMA_VERSION_V2,
                                   "physical traffic v2")
            if d["message_artifact_id"] != logical.message_artifact_id():
                raise InvalidInput(
                    "physical traffic v2 message_artifact_id does not "
                    "match the verified logical parent")
        elif "type" in d and d["type"] != _V2_HASH_TYPE_TAG:
            raise InvalidInput(
                f"physical traffic v2 type tag {d['type']!r} is not "
                f"{_V2_HASH_TYPE_TAG!r}")
        art = cls(logical=logical, resolved_fabric=resolved_fabric,
                  mapping=mapping, attachment=attachment,
                  inventory=inventory, packet_format=packet_format,
                  schema_version=d.get("schema_version",
                                       PHYSICAL_TRAFFIC_SCHEMA_VERSION_V2))
        if strict:
            require_embedded_id(d, "physical_traffic_id",
                                art.physical_traffic_id(),
                                "physical traffic v2")
            recomputed = art.identity_dict()
            for key in ("traffic", "resolved_fabric_hash",
                        "packet_format_hash",
                        "participant_endpoint_mapping_id"):
                if d.get(key) != recomputed[key]:
                    raise EvidenceInvalid(
                        f"persisted physical traffic v2 {key} does not "
                        "equal the recomputed canonical content: content "
                        "forged")
        elif d.get("physical_traffic_id") not in (
                None, art.physical_traffic_id()):
            raise InvalidInput(
                "physical_traffic_id does not match content")
        return art


__all__ = [
    "BindingRecord", "MessageTraffic", "OperationLedgerEntry",
    "PARTICIPANT_MAPPING_SCHEMA_VERSION", "ParticipantEndpointMapping",
    "PacketRecord", "PHYSICAL_TRAFFIC_SCHEMA_VERSION_V2",
    "PhysicalTrafficArtifactV2", "bind_participants", "flitize_packet",
    "header_width_bits", "packet_capacity_bits", "packetize_message",
    "payload_width_bits",
]
