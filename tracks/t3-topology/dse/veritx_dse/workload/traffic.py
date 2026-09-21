"""veritx_dse.workload.traffic — PhysicalTrafficArtifact + ConservationLedger
(D4/D5, §18–§24).

One authoritative projection from logical messages to physical traffic:

    LogicalMessageArtifact + ResolvedFabricBundle →
        per-message endpoint binding → packets → flits

Bit-exact rules (§18/§19):

    message_bits            = payload_bytes × 8
    packet payload capacity = Q × L        (Q = payload_width_bits,
                                            L = max_packet_flits)
    N_packets               = ceil(message_bits / (Q × L))
    Σ packet_payload_bits   = message_bits             (exact)
    per packet i:  n_i = ceil(P_i / Q); padding_i = n_i·Q − P_i;
                   header_bits_i = n_i·H; transmitted_bits_i = n_i·F
                   transmitted_bits_i == header_bits_i + P_i + padding_i

Header width H is DERIVED from the authoritative PacketFormatArtifact
field layout (every flit repeats the header; A6). Identity binds the
direct parents (§32): message_artifact_id, resolved_fabric_hash,
packet_format_hash, canonical packet/flit contents.

The ConservationLedger records the distinct quantity classes of §24.1 per
operation and fails closed (§24) on any violated law.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.model.resolved_bundle import ResolvedFabricBundle
from veritx_dse.model.packet_format import PacketFormatArtifact

from veritx_dse.core.errors import (
    ConservationFailed, EvidenceInvalid, InvalidInput, MappingInvalid,
)
from veritx_dse.core.artifact import content_hash
from veritx_dse.workload.messages import (
    LogicalMessageArtifact, LogicalMessageArtifactV2,
)
from veritx_dse.core.artifact import (
    require_embedded_id, require_fields, require_schema_version, require_type_tag,
)

PHYSICAL_TRAFFIC_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/WavedPhysicalTraffic"


def header_width_bits(pf: PacketFormatArtifact) -> int:
    """Non-payload bits of the pinned Wave-B flit layout (A6)."""
    return pf.flit_width_bits - pf.payload_width_bits


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
    """Per-operation conservation quantities (§24.1), distinct classes."""

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


def _rank_to_endpoint_maps(bundle: ResolvedFabricBundle) \
        -> tuple[dict[int, int], dict[int, str]]:
    """rank → endpoint id and rank → agent instance id, via the sealed
    Wave-B authorities only (no second rank→endpoint map is created)."""
    rank_agent: dict[int, Any] = {}
    for placement in bundle.mapping.placements:
        rank_agent[placement.rank] = placement.agent
    agent_endpoint: dict[tuple[int, int, int], int] = {}
    for e in bundle.attachment.endpoints:
        agent_endpoint[(e.agent.group_index, e.agent.instance_index,
                        e.agent.kind)] = e.endpoint_id
    r2e: dict[int, int] = {}
    r2a: dict[int, str] = {}
    for rank, agent in rank_agent.items():
        key = (agent.group_index, agent.instance_index, agent.kind)
        if key not in agent_endpoint:
            raise MappingInvalid(
                f"rank {rank} maps to unattached agent "
                f"{agent.instance_id}")
        r2e[rank] = agent_endpoint[key]
        r2a[rank] = agent.instance_id
    return r2e, r2a


def packetize_message(message_bits: int, pf: PacketFormatArtifact
                      ) -> list[int]:
    """Packet payload bits per packet under the Wave-B authority."""
    q = pf.payload_width_bits
    capacity = pf.max_network_packet_payload_bits  # Q × L
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
    q = pf.payload_width_bits
    h = header_width_bits(pf)
    f = pf.flit_width_bits
    n = (p_i + q - 1) // q
    padding = n * q - p_i
    return n, padding, n * f


def _require_geometry_shape(pa: Any, bundle: ResolvedFabricBundle) -> None:
    """Equal world size is NOT semantic equivalence (§9).

    The logical rank geometry must be exactly the geometry the physical
    bundle was built from: TP=4/PP=1 and TP=2/PP=2 share the integer
    rank universe {0..3} and can carry identical MappingArtifact
    content, but they are different deployments. Transposing one onto
    the other silently relabels every tensor-parallel peer group, so it
    must refuse before any rank→endpoint binding happens.
    """
    shape = (pa.tp, pa.pp, pa.ep, pa.dp)
    inventory = getattr(bundle, "inventory", None)
    inv_shape_obj = getattr(inventory, "parallelism", None)
    if inv_shape_obj is None:
        raise MappingInvalid(
            "physical bundle carries no inventory parallelism shape; "
            "cannot prove the logical geometry belongs to it")
    inv_shape = (inv_shape_obj.tp, inv_shape_obj.pp, inv_shape_obj.ep,
                 inv_shape_obj.dp)
    if shape != inv_shape:
        raise MappingInvalid(
            f"logical rank geometry TP={pa.tp} PP={pa.pp} EP={pa.ep} "
            f"DP={pa.dp} does not match the physical bundle geometry "
            f"TP={inv_shape[0]} PP={inv_shape[1]} EP={inv_shape[2]} "
            f"DP={inv_shape[3]}; equal world size is not semantic "
            f"equivalence")
    workload = getattr(getattr(bundle, "design", None), "workload", None)
    if workload is not None:
        design_shape = (workload.tp, workload.pp, workload.ep, workload.dp)
        if design_shape != shape:
            raise MappingInvalid(
                f"logical rank geometry {shape} does not match the "
                f"compiled design workload geometry {design_shape}")


def _require_matching_geometry(logical: LogicalMessageArtifact,
                               bundle: ResolvedFabricBundle) -> None:
    """v1 wrapper: the logical artifact's graph carries the geometry."""
    _require_geometry_shape(logical.graph.parallelism, bundle)


def _packet_records(m: Any, src: BindingRecord, dst: BindingRecord,
                    pf: PacketFormatArtifact, H: int, Q: int
                    ) -> tuple[PacketRecord, ...]:
    """Packetize ONE logical message under the Wave-B authority.

    Shared by both traffic generations: the transmitted-bit identity and
    the padding bound are checked here, so a violated equation can never
    persist in either schema.
    """
    message_bits = m.payload_bytes * 8
    packets: list[PacketRecord] = []
    for idx, pbits in enumerate(packetize_message(message_bits, pf)):
        n, padding, transmitted = flitize_packet(pbits, pf)
        hbits = n * H
        if transmitted != hbits + pbits + padding:
            raise ConservationFailed(
                f"packet {idx} of {m.message_id!r}: transmitted "
                f"{transmitted} != header {hbits} + payload {pbits} + "
                f"padding {padding}")
        if not (0 <= padding < Q):
            raise ConservationFailed(
                f"packet {idx} of {m.message_id!r}: padding {padding} "
                f"outside [0, {Q})")
        packets.append(PacketRecord(
            message_id=m.message_id, packet_index=idx, payload_bits=pbits,
            flit_count=n, padding_bits=padding, header_bits=hbits,
            transmitted_bits=transmitted, src_endpoint=src.endpoint_id,
            dst_endpoint=dst.endpoint_id))
    return tuple(packets)


PARTICIPANT_MAPPING_SCHEMA_VERSION = 1
_PEM_TYPE_TAG = "srota/ParticipantEndpointMapping"


@dataclass(frozen=True)
class ParticipantEndpointMapping:
    """Participant rank → physical endpoint, identified and refused.

    B2 MappingArtifact answers rank→agent and deliberately carries no
    fabric field; the attachment answers agent→endpoint. This is the
    participant-scoped projection of both — the binding physical
    lowering must prove before it sends, instead of assuming the
    participant namespace equals the world rank space (F15).
    """

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


PHYSICAL_TRAFFIC_SCHEMA_VERSION_V2 = 2
_V2_HASH_TYPE_TAG = "srota/PhysicalTrafficArtifactV2"


@dataclass(frozen=True)
class PhysicalTrafficArtifact:
    """The one authoritative logical→physical traffic projection (§31)."""

    logical: LogicalMessageArtifact
    bundle: ResolvedFabricBundle
    schema_version: int = PHYSICAL_TRAFFIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.logical, LogicalMessageArtifact):
            raise InvalidInput("logical must be a LogicalMessageArtifact")
        if not isinstance(self.bundle, ResolvedFabricBundle):
            raise InvalidInput("bundle must be a ResolvedFabricBundle")
        # Re-prove the complete Wave-B hardware DAG and the design/mapping
        # seam from the actual child objects immediately before lowering:
        # a bundle assembled around a stale/tampered child can never feed
        # physical traffic (Wave-B revalidation, not re-implemented here).
        try:
            self.bundle.revalidate()
        except Exception as exc:
            raise MappingInvalid(
                f"physical bundle fails revalidation: {exc}") from None
        _require_matching_geometry(self.logical, self.bundle)
        pf = self.bundle.packet_format
        H = header_width_bits(pf)
        Q = pf.payload_width_bits
        if H < 0 or Q < 1:
            raise InvalidInput("packet format has no payload capacity")
        r2e, r2a = _rank_to_endpoint_maps(self.bundle)

        traffic: list[MessageTraffic] = []
        R = self.logical.graph.parallelism.world_size
        for m in self.logical.messages:
            if m.src_rank >= R or m.dst_rank >= R:
                raise MappingInvalid(
                    f"message {m.message_id!r} addresses rank outside [0,"
                    f" {R})")
            src = BindingRecord(rank=m.src_rank,
                                agent_instance_id=r2a[m.src_rank],
                                endpoint_id=r2e[m.src_rank])
            dst = BindingRecord(rank=m.dst_rank,
                                agent_instance_id=r2a[m.dst_rank],
                                endpoint_id=r2e[m.dst_rank])
            message_bits = m.payload_bytes * 8
            packets = list(_packet_records(m, src, dst, pf, H, Q))
            if sum(p.payload_bits for p in packets) != message_bits:
                raise ConservationFailed(
                    f"message {m.message_id!r}: packet payload bits do not "
                    f"conserve message bits")
            traffic.append(MessageTraffic(
                message_id=m.message_id, operation_id=m.operation_id,
                src=src, dst=dst, payload_bytes=m.payload_bytes,
                message_bits=message_bits, packets=tuple(packets)))
        object.__setattr__(self, "_traffic", tuple(traffic))

    def validate_against_bundle(self) -> None:
        """Re-prove the logical↔physical seam on demand.

        The constructor already refuses a transposed geometry; this is
        the explicit seam check product code and tests call before
        treating an artifact as executable.
        """
        try:
            self.bundle.revalidate()
        except Exception as exc:
            raise MappingInvalid(
                f"physical bundle fails revalidation: {exc}") from None
        _require_matching_geometry(self.logical, self.bundle)

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

    # ── conservation ledger (§24) ─────────────────────────────────
    def conservation_ledger(self) -> tuple[OperationLedgerEntry, ...]:
        logical = self.logical
        entries: list[OperationLedgerEntry] = []
        seen_ops: set[str] = set()
        for t in self._traffic:
            if t.operation_id in seen_ops:
                continue
            seen_ops.add(t.operation_id)
            node = logical.graph.node(t.operation_id)
            ms = [m for m in logical.messages
                  if m.operation_id == t.operation_id]
            ts = [x for x in self._traffic
                  if x.operation_id == t.operation_id]
            d = node.detail
            if node.kind == "COLLECTIVE":
                cid = d["collective_id"]
                rec = next(s for s in logical.schedules
                           if s.collective_id == cid)
                scheduled = rec.aggregate_payload
                source = rec.payload_bytes
            elif node.kind == "P2P":
                scheduled = sum(m.payload_bytes for m in ms)
                source = scheduled
            elif node.kind == "MULTICAST":
                scheduled = sum(m.payload_bytes for m in ms)
                # Source payload comes from the multicast INTENT (the
                # authority), never from the node's link detail: the
                # link detail carries only the multicast id.
                mc = next(
                    m for m in logical.graph.multicasts
                    if m.multicast_id == d.get("multicast_id"))
                source = mc.payload_bytes
            else:
                scheduled = 0
                source = 0
            entries.append(OperationLedgerEntry(
                operation_id=t.operation_id, operation_kind=node.kind,
                source_logical_payload_bytes=source,
                scheduled_message_bytes=scheduled,
                generated_message_bytes=sum(m.payload_bytes for m in ms),
                message_count=len(ms),
                packet_count=sum(len(x.packets) for x in ts),
                packet_payload_bits=sum(x.packet_payload_bits for x in ts),
                flit_count=sum(x.flit_count for x in ts),
                header_bits=sum(x.header_bits for x in ts),
                padding_bits=sum(x.padding_bits for x in ts),
                transmitted_bits=sum(x.transmitted_bits for x in ts),
                rank_binding_valid=True, endpoint_binding_valid=True))
        return tuple(entries)

    def validate_conservation(self) -> None:
        """Every supported relevant law (§24). Mismatch = hard failure."""
        pf = self.bundle.packet_format
        Q = pf.payload_width_bits
        logical_bits = sum(m.payload_bytes for m in self.logical.messages) * 8
        totals = self.totals()
        if totals["packet_payload_bits"] != logical_bits:
            raise ConservationFailed(
                f"packet payload bits {totals['packet_payload_bits']} != "
                f"logical message bits {logical_bits}")
        for entry in self.conservation_ledger():
            if entry.generated_message_bytes != entry.scheduled_message_bytes:
                raise ConservationFailed(
                    f"operation {entry.operation_id!r}: generated "
                    f"{entry.generated_message_bytes} != scheduled "
                    f"{entry.scheduled_message_bytes}")
            if entry.packet_payload_bits != \
                    entry.generated_message_bytes * 8:
                raise ConservationFailed(
                    f"operation {entry.operation_id!r}: packet payload "
                    f"{entry.packet_payload_bits} != 8 × message bytes")
            if entry.transmitted_bits != entry.header_bits + \
                    entry.packet_payload_bits + entry.padding_bits:
                raise ConservationFailed(
                    f"operation {entry.operation_id!r}: transmitted-bit "
                    "identity violated")
            if entry.padding_bits >= entry.packet_count * Q:
                raise ConservationFailed(
                    f"operation {entry.operation_id!r}: padding outside "
                    "per-packet bound")
            if not (entry.rank_binding_valid and
                    entry.endpoint_binding_valid):
                raise ConservationFailed(
                    f"operation {entry.operation_id!r}: binding invalid")

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "message_artifact_id": self.logical.message_artifact_id(),
            "resolved_fabric_hash":
                self.bundle.resolved_fabric.resolved_fabric_hash(),
            "packet_format_hash":
                self.bundle.packet_format.packet_format_hash(),
            "traffic": [t.canonical_packets() for t in self._traffic],
        }

    def physical_traffic_id(self) -> str:
        return content_hash(_HASH_TYPE_TAG, self.schema_version,
                            self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_dict(),
                "physical_traffic_id": self.physical_traffic_id(),
                "totals": self.totals()}

    # ── strict parsing (persisted-resource contract) ──────────────────
    @classmethod
    def from_dict(cls, d: Any, *, logical: LogicalMessageArtifact,
                  bundle: ResolvedFabricBundle,
                  strict: bool = False) -> "PhysicalTrafficArtifact":
        """Rebuild physical traffic from VERIFIED parents.

        The bundle and the logical artifact are supplied by the caller
        (a verified loader) — never read out of the JSON. In strict
        mode the embedded parent hashes, the embedded traffic ID and
        every stored packet row must equal the recomputed content.
        """
        require_fields(d, {
            "type", "schema_version", "message_artifact_id",
            "resolved_fabric_hash", "packet_format_hash", "traffic",
            "physical_traffic_id", "totals", "design_id",
            "design_hash", "mapping_hash",
        }, "physical traffic")
        if strict:
            require_type_tag(d, _HASH_TYPE_TAG, "physical traffic")
            require_schema_version(d, PHYSICAL_TRAFFIC_SCHEMA_VERSION,
                                   "physical traffic")
            for key in ("message_artifact_id", "resolved_fabric_hash",
                        "packet_format_hash", "traffic",
                        "physical_traffic_id"):
                if key not in d:
                    raise InvalidInput(
                        f"persisted physical traffic is missing {key!r}")
            if d["message_artifact_id"] != \
                    logical.message_artifact_id():
                raise InvalidInput(
                    "physical traffic message_artifact_id does not match "
                    "the verified logical parent")
            if d["resolved_fabric_hash"] != \
                    bundle.resolved_fabric.resolved_fabric_hash():
                raise InvalidInput(
                    "physical traffic resolved_fabric_hash does not match "
                    "the verified bundle")
            if d["packet_format_hash"] != \
                    bundle.packet_format.packet_format_hash():
                raise InvalidInput(
                    "physical traffic packet_format_hash does not match "
                    "the verified bundle")
        elif "type" in d and d["type"] != _HASH_TYPE_TAG:
            raise InvalidInput(
                f"physical traffic type tag {d['type']!r} is not "
                f"{_HASH_TYPE_TAG!r}")
        art = cls(logical=logical, bundle=bundle,
                  schema_version=d.get("schema_version",
                                       PHYSICAL_TRAFFIC_SCHEMA_VERSION))
        if strict:
            require_embedded_id(d, "physical_traffic_id",
                                art.physical_traffic_id(),
                                "physical traffic")
            recomputed = art.identity_dict()
            if d.get("traffic") != recomputed["traffic"]:
                raise EvidenceInvalid(
                    "persisted physical traffic rows do not equal the "
                    "recomputed canonical packets: content forged")
        elif d.get("physical_traffic_id") not in (
                None, art.physical_traffic_id()):
            raise InvalidInput(
                "physical_traffic_id does not match content")
        return art


@dataclass(frozen=True)
class PhysicalTrafficArtifactV2:
    """Physical traffic from the canonical logical messages (M1.3).

    Binds message_artifact_id, the resolved fabric, the packet format AND
    the participant→endpoint mapping it actually used. Packet endpoints
    come from that mapping, so logical rank == physical endpoint is never
    assumed: a 4-participant workload on an 8-rank fabric lowers through
    its own explicit binding, and refuses only when a participant has no
    authenticated binding.
    """

    logical: LogicalMessageArtifactV2
    bundle: ResolvedFabricBundle
    schema_version: int = PHYSICAL_TRAFFIC_SCHEMA_VERSION_V2

    def __post_init__(self) -> None:
        if not isinstance(self.logical, LogicalMessageArtifactV2):
            raise InvalidInput(
                "logical must be a LogicalMessageArtifactV2")
        if not isinstance(self.bundle, ResolvedFabricBundle):
            raise InvalidInput("bundle must be a ResolvedFabricBundle")
        if self.schema_version != PHYSICAL_TRAFFIC_SCHEMA_VERSION_V2:
            raise InvalidInput(
                f"unsupported physical traffic schema_version "
                f"{self.schema_version!r}")
        try:
            self.bundle.revalidate()
        except Exception as exc:
            raise MappingInvalid(
                f"physical bundle fails revalidation: {exc}") from None
        _require_geometry_shape(self.logical.graph.parallelism, self.bundle)
        pf = self.bundle.packet_format
        H = header_width_bits(pf)
        Q = pf.payload_width_bits
        if H < 0 or Q < 1:
            raise InvalidInput("packet format has no payload capacity")
        _, r2a = _rank_to_endpoint_maps(self.bundle)
        pem = self.participant_endpoint_mapping()
        count = self.logical.participant_count

        traffic: list[MessageTraffic] = []
        for m in self.logical.messages:
            for rank in (m.src_rank, m.dst_rank):
                if not 0 <= rank < count:
                    raise MappingInvalid(
                        f"message {m.message_id!r} addresses rank {rank} "
                        f"outside the participant namespace [0, {count})")
            src = BindingRecord(rank=m.src_rank,
                                agent_instance_id=r2a[m.src_rank],
                                endpoint_id=pem.endpoint_for(m.src_rank))
            dst = BindingRecord(rank=m.dst_rank,
                                agent_instance_id=r2a[m.dst_rank],
                                endpoint_id=pem.endpoint_for(m.dst_rank))
            message_bits = m.payload_bytes * 8
            packets = list(_packet_records(m, src, dst, pf, H, Q))
            if sum(p.payload_bits for p in packets) != message_bits:
                raise ConservationFailed(
                    f"message {m.message_id!r}: packet payload bits do not "
                    f"conserve message bits")
            traffic.append(MessageTraffic(
                message_id=m.message_id, operation_id=m.operation_id,
                src=src, dst=dst, payload_bytes=m.payload_bytes,
                message_bits=message_bits, packets=tuple(packets)))
        object.__setattr__(self, "_traffic", tuple(traffic))

    # ── the binding this lowering actually used ─────────────────────
    def participant_endpoint_mapping(self) -> ParticipantEndpointMapping:
        r2e, _ = _rank_to_endpoint_maps(self.bundle)
        count = self.logical.participant_count
        rows: list[tuple[int, int]] = []
        for rank in range(count):
            if rank not in r2e:
                raise MappingInvalid(
                    f"participant rank {rank} has no authenticated "
                    f"rank→endpoint binding in the resolved fabric "
                    f"(participant_count={count}); physical lowering "
                    f"requires an explicit mapping")
            rows.append((rank, r2e[rank]))
        return ParticipantEndpointMapping(
            participant_count=count, rank_to_endpoint=tuple(rows),
            fabric_id=self.bundle.resolved_fabric.resolved_fabric_hash())

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

    def validate_against_bundle(self) -> None:
        """Re-prove the logical↔physical seam on demand (v2).

        Mirrors the v1 seam check: the bundle revalidates and the
        canonical graph's parallelism geometry must equal the bundle
        geometry. The constructor already refuses a transposed
        geometry; this is the explicit gate product code calls.
        """
        try:
            self.bundle.revalidate()
        except Exception as exc:
            raise MappingInvalid(
                f"physical bundle fails revalidation: {exc}") from None
        _require_geometry_shape(self.logical.graph.parallelism,
                                self.bundle)

    def validate_conservation(self) -> None:
        """Packet conservation + per-collective generated == scheduled."""
        logical_bits = sum(m.payload_bytes for m in self.logical.messages) * 8
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
                    f"does not equal the scheduled "
                    f"{rec.aggregate_payload}")

    # ── identity ──────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _V2_HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "message_artifact_id": self.logical.message_artifact_id(),
            "resolved_fabric_hash":
                self.bundle.resolved_fabric.resolved_fabric_hash(),
            "packet_format_hash":
                self.bundle.packet_format.packet_format_hash(),
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
                  bundle: ResolvedFabricBundle,
                  strict: bool = False) -> "PhysicalTrafficArtifactV2":
        """Rebuild v2 traffic from VERIFIED parents (never from the JSON)."""
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
        art = cls(logical=logical, bundle=bundle,
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
                        f"equal the recomputed canonical content: content "
                        f"forged")
        elif d.get("physical_traffic_id") not in (
                None, art.physical_traffic_id()):
            raise InvalidInput(
                "physical_traffic_id does not match content")
        return art


__all__ = [
    "BindingRecord", "header_width_bits", "flitize_packet",
    "packetize_message", "PacketRecord",
    "PHYSICAL_TRAFFIC_SCHEMA_VERSION", "PHYSICAL_TRAFFIC_SCHEMA_VERSION_V2",
    "PhysicalTrafficArtifact", "PhysicalTrafficArtifactV2",
    "ParticipantEndpointMapping", "PARTICIPANT_MAPPING_SCHEMA_VERSION",
    "OperationLedgerEntry", "MessageTraffic",
]
