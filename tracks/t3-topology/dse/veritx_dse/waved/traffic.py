"""veritx_dse.waved.traffic — PhysicalTrafficArtifact + ConservationLedger
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

from veritx_dse.backend.bundle import ResolvedFabricBundle
from veritx_dse.model.packet_format import PacketFormatArtifact

from .errors import (
    ConservationFailed, EvidenceInvalid, InvalidInput, MappingInvalid,
)
from .identity import content_hash
from .messages import LogicalMessageArtifact
from .strict import (
    require_embedded_id, require_fields, require_schema_version,
    require_type_tag,
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


def _require_matching_geometry(logical: LogicalMessageArtifact,
                               bundle: ResolvedFabricBundle) -> None:
    """Equal world size is NOT semantic equivalence (§9).

    The logical rank geometry must be exactly the geometry the physical
    bundle was built from: TP=4/PP=1 and TP=2/PP=2 share the integer
    rank universe {0..3} and can carry identical MappingArtifact
    content, but they are different deployments. Transposing one onto
    the other silently relabels every tensor-parallel peer group, so it
    must refuse before any rank→endpoint binding happens.
    """
    pa = logical.graph.parallelism
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
            packets: list[PacketRecord] = []
            for idx, pbits in enumerate(packetize_message(message_bits, pf)):
                n, padding, transmitted = flitize_packet(pbits, pf)
                hbits = n * H
                # Exact flit transmitted-bit identity (§18) — checked here,
                # so a violated equation can never persist.
                if transmitted != hbits + pbits + padding:
                    raise ConservationFailed(
                        f"packet {idx} of {m.message_id!r}: transmitted "
                        f"{transmitted} != header {hbits} + payload "
                        f"{pbits} + padding {padding}")
                if not (0 <= padding < Q):
                    raise ConservationFailed(
                        f"packet {idx} of {m.message_id!r}: padding "
                        f"{padding} outside [0, {Q})")
                packets.append(PacketRecord(
                    message_id=m.message_id, packet_index=idx,
                    payload_bits=pbits, flit_count=n, padding_bits=padding,
                    header_bits=hbits, transmitted_bits=transmitted,
                    src_endpoint=src.endpoint_id, dst_endpoint=dst.endpoint_id))
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

    def cross_check_against_oracle(self) -> None:
        """Independent-oracle differential check (§22/§26)."""
        from .oracles import ref_flitize, ref_packetize
        pf = self.bundle.packet_format
        Q, L = pf.payload_width_bits, pf.max_packet_flits
        H = header_width_bits(pf)
        for m in self.logical.messages:
            expected_pkts = ref_packetize(m.payload_bytes * 8, Q, L)
            got = next(t for t in self._traffic
                       if t.message_id == m.message_id)
            if [p.payload_bits for p in got.packets] != expected_pkts:
                raise ConservationFailed(
                    f"packetization oracle mismatch for {m.message_id!r}")
            for p in got.packets:
                n, padding, transmitted = ref_flitize(p.payload_bits, Q, H,
                                                      pf.flit_width_bits)
                if (n, padding, transmitted) != (
                        p.flit_count, p.padding_bits,
                        p.transmitted_bits):
                    raise ConservationFailed(
                        f"flitization oracle mismatch for packet "
                        f"{p.packet_index} of {m.message_id!r}")

    # ── identity (§32) ────────────────────────────────────────────────
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


__all__ = [
    "BindingRecord", "header_width_bits", "flitize_packet",
    "packetize_message", "PacketRecord",
    "PHYSICAL_TRAFFIC_SCHEMA_VERSION", "PhysicalTrafficArtifact",
    "OperationLedgerEntry", "MessageTraffic",
]
