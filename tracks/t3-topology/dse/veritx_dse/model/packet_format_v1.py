"""veritx_dse.model.packet_format — PacketFormatArtifact (Wave B3.4a).

PacketFormatArtifact is the sole authority for **what bits cross a NoC
link** and **how a network packet is delimited**. It does not route, does
not assign VCs, and does not carry protocol metadata.

Ownership:

    TopologyArtifact.DirectedChannel.width_bits = physical channel beat width
    PacketFormatArtifact.flit_width_bits         = logical flit width

For Srota v1 one logical flit is transferred in one channel beat, so the
two must be equal. That is a v1 equality constraint, not a permanent
conceptual equivalence: the ASTRA coarse-packetization knob
(ASTRASIM_FLIT_BYTES) is an execution-fidelity override and is explicitly
NOT fabric width authority.

v1 wire fields, and only these:

    payload               opaque to the router
    source_endpoint       endpoint namespace, packet-immutable
    destination_endpoint  endpoint namespace, packet-immutable
    flit_type             SINGLE / HEAD / BODY / TAIL, structural
    vc_id                 hop-local resource metadata

Not on the wire in v1:

    TrafficClass   injection-time intent (traffic_class_to_vcs)
    RoutingClass   derived from vc_out via VCAssignmentArtifact
    sequence       NI / protocol / testbench responsibility
    protocol meta  NI / protocol payload
    multicast      workload lowering only in v1

Header metadata is repeated in EVERY flit: BODY/TAIL remain independently
interpretable, and a legal VC transition rewrites only ``vc_id``.

Packetization v1 is BOUNDED_WORMHOLE with ``max_packet_flits`` (default
8). A larger message is fragmented by the NI/lowerer into multiple
bounded network packets; one message must never become one unbounded
wormhole packet.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .attachment import AgentAttachmentArtifact
from .topology_artifact import TopologyArtifact
from .vc_assignment import VCAssignmentArtifact

PACKET_FORMAT_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/PacketFormatArtifact"

PACKETIZATION_BOUNDED_WORMHOLE = "BOUNDED_WORMHOLE"
HEADER_REPLICATION_EVERY_FLIT = "EVERY_FLIT"

FLIT_TYPE_HEAD = "HEAD"
FLIT_TYPE_BODY = "BODY"
FLIT_TYPE_TAIL = "TAIL"
FLIT_TYPE_SINGLE = "SINGLE"

# Identity-bearing: pinned encodings for v1.
FLIT_TYPE_ENCODING = (
    (FLIT_TYPE_HEAD, 0),
    (FLIT_TYPE_BODY, 1),
    (FLIT_TYPE_TAIL, 2),
    (FLIT_TYPE_SINGLE, 3),
)
FLIT_TYPES = tuple(name for name, _ in FLIT_TYPE_ENCODING)

DEFAULT_FLIT_WIDTH_BITS = 64
DEFAULT_MAX_PACKET_FLITS = 8


class PacketFormatError(ValueError):
    """The packet/flit format is invalid or unsupported — fail closed."""


def _as_int(name: str, value: Any) -> int:
    if type(value) is not int:
        raise PacketFormatError(
            f"{name} must be an int, got {type(value).__name__}")
    return value


def _as_positive_int(name: str, value: Any) -> int:
    value = _as_int(name, value)
    if value < 1:
        raise PacketFormatError(f"{name} must be >= 1, got {value}")
    return value


def _as_non_negative_int(name: str, value: Any) -> int:
    value = _as_int(name, value)
    if value < 0:
        raise PacketFormatError(f"{name} must be >= 0, got {value}")
    return value


def _as_str(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise PacketFormatError(f"{name} must be a non-empty string")
    return value


def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise PacketFormatError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise PacketFormatError(
            f"{where} has unknown fields: {sorted(unknown)}")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise PacketFormatError(f"{where} is missing required field {key!r}")
    return d[key]


def encoding_width(count: int) -> int:
    """Bits needed to encode ids ``0..count-1``; at least 1.

    Equivalent to ``max(1, ceil(log2(count)))`` without float rounding.
    """
    count = _as_positive_int("encoding_width count", count)
    return max(1, (count - 1).bit_length())


# ── field schema ─────────────────────────────────────────────────────────

class FieldRole(Enum):
    PAYLOAD = "payload"
    SOURCE_ENDPOINT = "source_endpoint"
    DESTINATION_ENDPOINT = "destination_endpoint"
    FLIT_TYPE = "flit_type"
    VC_ID = "vc_id"


class FieldMutability(Enum):
    PAYLOAD = "payload"
    PACKET_IMMUTABLE = "packet_immutable"
    FLIT_STRUCTURAL = "flit_structural"
    HOP_LOCAL = "hop_local"


# The canonical role -> mutability mapping is fixed for v1.
_ROLE_MUTABILITY = {
    FieldRole.PAYLOAD: FieldMutability.PAYLOAD,
    FieldRole.SOURCE_ENDPOINT: FieldMutability.PACKET_IMMUTABLE,
    FieldRole.DESTINATION_ENDPOINT: FieldMutability.PACKET_IMMUTABLE,
    FieldRole.FLIT_TYPE: FieldMutability.FLIT_STRUCTURAL,
    FieldRole.VC_ID: FieldMutability.HOP_LOCAL,
}

_CANONICAL_NAMES = {
    FieldRole.PAYLOAD: "payload",
    FieldRole.SOURCE_ENDPOINT: "source_endpoint",
    FieldRole.DESTINATION_ENDPOINT: "destination_endpoint",
    FieldRole.FLIT_TYPE: "flit_type",
    FieldRole.VC_ID: "vc_id",
}


@dataclass(frozen=True)
class PacketField:
    """One contiguous bit field in the flit."""

    name: str
    lsb: int
    width: int
    role: FieldRole
    mutability: FieldMutability

    def __post_init__(self):
        _as_str("field name", self.name)
        _as_non_negative_int("field lsb", self.lsb)
        _as_positive_int("field width", self.width)
        if not isinstance(self.role, FieldRole):
            raise PacketFormatError(
                f"field role must be a FieldRole, got {self.role!r}")
        if not isinstance(self.mutability, FieldMutability):
            raise PacketFormatError(
                f"field mutability must be a FieldMutability, got "
                f"{self.mutability!r}")
        if self.name != _CANONICAL_NAMES[self.role]:
            raise PacketFormatError(
                f"field for role {self.role.value!r} must be named "
                f"{_CANONICAL_NAMES[self.role]!r}, got {self.name!r}")
        if self.mutability is not _ROLE_MUTABILITY[self.role]:
            raise PacketFormatError(
                f"field {self.name!r} role {self.role.value!r} requires "
                f"mutability {_ROLE_MUTABILITY[self.role].value!r}, got "
                f"{self.mutability.value!r}")

    @property
    def msb(self) -> int:
        return self.lsb + self.width - 1

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "lsb": self.lsb, "width": self.width,
                "role": self.role.value,
                "mutability": self.mutability.value}

    @classmethod
    def from_dict(cls, d: Any) -> "PacketField":
        _strict_keys(d, frozenset({"name", "lsb", "width", "role",
                                   "mutability"}), "packet field")
        try:
            role = FieldRole(_need(d, "role", "packet field"))
        except ValueError:
            raise PacketFormatError(
                f"unknown packet field role {d.get('role')!r}") from None
        try:
            mutability = FieldMutability(_need(d, "mutability", "packet field"))
        except ValueError:
            raise PacketFormatError(
                f"unknown packet field mutability "
                f"{d.get('mutability')!r}") from None
        return cls(
            name=_need(d, "name", "packet field"),
            lsb=_need(d, "lsb", "packet field"),
            width=_need(d, "width", "packet field"),
            role=role,
            mutability=mutability,
        )


def canonical_field_layout(*, endpoint_width: int, vc_width: int,
                           payload_width: int) -> tuple[PacketField, ...]:
    """The pinned B3.4 layout, LSB -> MSB:

        payload | source_endpoint | destination_endpoint | flit_type | vc_id
    """
    endpoint_width = _as_positive_int("endpoint_width", endpoint_width)
    vc_width = _as_positive_int("vc_width", vc_width)
    payload_width = _as_positive_int("payload_width", payload_width)
    return (
        PacketField("payload", 0, payload_width,
                    FieldRole.PAYLOAD, FieldMutability.PAYLOAD),
        PacketField("source_endpoint", payload_width, endpoint_width,
                    FieldRole.SOURCE_ENDPOINT,
                    FieldMutability.PACKET_IMMUTABLE),
        PacketField("destination_endpoint", payload_width + endpoint_width,
                    endpoint_width, FieldRole.DESTINATION_ENDPOINT,
                    FieldMutability.PACKET_IMMUTABLE),
        PacketField("flit_type", payload_width + 2 * endpoint_width, 2,
                    FieldRole.FLIT_TYPE, FieldMutability.FLIT_STRUCTURAL),
        PacketField("vc_id", payload_width + 2 * endpoint_width + 2,
                    vc_width, FieldRole.VC_ID, FieldMutability.HOP_LOCAL),
    )


def _validate_layout(layout: Any, flit_width_bits: int) -> None:
    if not isinstance(layout, tuple) or not layout:
        raise PacketFormatError("field_layout must be a non-empty tuple")
    for field in layout:
        if not isinstance(field, PacketField):
            raise PacketFormatError(
                f"field_layout must contain PacketField, got "
                f"{type(field).__name__}")
    roles = [f.role for f in layout]
    if len(set(roles)) != len(roles):
        raise PacketFormatError("field_layout has duplicate roles")
    missing = set(FieldRole) - set(roles)
    if missing:
        raise PacketFormatError(
            f"field_layout is missing roles: "
            f"{sorted(r.value for r in missing)}")
    names = [f.name for f in layout]
    if len(set(names)) != len(names):
        raise PacketFormatError("field_layout has duplicate field names")
    width_by_role = {f.role: f.width for f in layout}
    if width_by_role[FieldRole.SOURCE_ENDPOINT] \
            != width_by_role[FieldRole.DESTINATION_ENDPOINT]:
        raise PacketFormatError(
            "source_endpoint and destination_endpoint must share the same "
            "endpoint-namespace width")
    # Full coverage, no gaps, no overlaps.
    cursor = 0
    for field in sorted(layout, key=lambda f: f.lsb):
        if field.lsb != cursor:
            raise PacketFormatError(
                f"field_layout is not contiguous at bit {cursor}: field "
                f"{field.name!r} starts at {field.lsb}")
        cursor = field.lsb + field.width
    if cursor != flit_width_bits:
        raise PacketFormatError(
            f"field_layout covers {cursor} bits but the flit is "
            f"{flit_width_bits} bits")


def _validate_flit_encoding(encoding: Any) -> None:
    if encoding != FLIT_TYPE_ENCODING:
        raise PacketFormatError(
            f"flit_type_encoding must be exactly {FLIT_TYPE_ENCODING!r}, "
            f"got {encoding!r}")


# ── the artifact ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PacketFormatArtifact:
    """Authoritative logical flit layout and packet delimitation."""

    topology_hash: str
    attachment_hash: str
    vc_assignment_hash: str

    flit_width_bits: int

    packetization: str
    max_packet_flits: int
    header_replication: str

    field_layout: tuple[PacketField, ...]

    flit_type_encoding: tuple[tuple[str, int], ...] = FLIT_TYPE_ENCODING

    schema_version: int = PACKET_FORMAT_SCHEMA_VERSION
    artifact_hash: str = ""

    def __post_init__(self):
        _as_str("topology_hash", self.topology_hash)
        _as_str("attachment_hash", self.attachment_hash)
        _as_str("vc_assignment_hash", self.vc_assignment_hash)
        _as_positive_int("flit_width_bits", self.flit_width_bits)
        if self.packetization != PACKETIZATION_BOUNDED_WORMHOLE:
            raise PacketFormatError(
                f"unsupported packetization {self.packetization!r} "
                f"(v1 supports only {PACKETIZATION_BOUNDED_WORMHOLE!r})")
        _as_positive_int("max_packet_flits", self.max_packet_flits)
        if self.header_replication != HEADER_REPLICATION_EVERY_FLIT:
            raise PacketFormatError(
                f"unsupported header_replication {self.header_replication!r} "
                f"(v1 supports only {HEADER_REPLICATION_EVERY_FLIT!r})")
        _validate_flit_encoding(self.flit_type_encoding)
        if type(self.schema_version) is not int or \
                self.schema_version != PACKET_FORMAT_SCHEMA_VERSION:
            raise PacketFormatError(
                f"unsupported packet-format schema_version "
                f"{self.schema_version!r} (expected "
                f"{PACKET_FORMAT_SCHEMA_VERSION})")
        _validate_layout(self.field_layout, self.flit_width_bits)
        expected = self._compute_hash()
        if self.artifact_hash and self.artifact_hash != expected:
            raise PacketFormatError(
                "artifact_hash does not match content")
        if not self.artifact_hash:
            object.__setattr__(self, "artifact_hash", expected)

    # ── derived capacities (never persisted independently) ─────────────
    def _field(self, role: FieldRole) -> PacketField:
        for field in self.field_layout:
            if field.role is role:
                return field
        raise PacketFormatError(f"field_layout has no {role.value!r} field")

    @property
    def payload_width_bits(self) -> int:
        return self._field(FieldRole.PAYLOAD).width

    @property
    def endpoint_width_bits(self) -> int:
        return self._field(FieldRole.SOURCE_ENDPOINT).width

    @property
    def vc_width_bits(self) -> int:
        return self._field(FieldRole.VC_ID).width

    @property
    def endpoint_capacity(self) -> int:
        return 2 ** self.endpoint_width_bits

    @property
    def vc_capacity(self) -> int:
        return 2 ** self.vc_width_bits

    @property
    def max_network_packet_payload_bits(self) -> int:
        return self.payload_width_bits * self.max_packet_flits

    # ── identity ───────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "topology_hash": self.topology_hash,
            "attachment_hash": self.attachment_hash,
            "vc_assignment_hash": self.vc_assignment_hash,
            "flit_width_bits": self.flit_width_bits,
            "packetization": self.packetization,
            "max_packet_flits": self.max_packet_flits,
            "header_replication": self.header_replication,
            "field_layout": [f.to_dict()
                             for f in sorted(self.field_layout,
                                             key=lambda f: f.lsb)],
            "flit_type_encoding": [[name, value]
                                   for name, value in self.flit_type_encoding],
        }

    def _compute_hash(self) -> str:
        from veritx_dse.core.spec import canonical_json
        body = (f"{_HASH_TYPE_TAG}/v{self.schema_version}\0"
                + canonical_json(self.identity_dict()))
        return hashlib.sha256(body.encode()).hexdigest()

    def packet_format_hash(self) -> str:
        return self._compute_hash()

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["artifact_hash"] = self.packet_format_hash()
        return d

    # ── persisted parsing (validate, never repair) ─────────────────────
    @classmethod
    def from_dict(cls, d: Any) -> "PacketFormatArtifact":
        allowed = frozenset({
            "type", "schema_version", "topology_hash", "attachment_hash",
            "vc_assignment_hash", "flit_width_bits", "packetization",
            "max_packet_flits", "header_replication", "field_layout",
            "flit_type_encoding", "artifact_hash",
        })
        _strict_keys(d, allowed, "packet_format")
        if _need(d, "type", "packet_format") != _HASH_TYPE_TAG:
            raise PacketFormatError(
                f"unexpected artifact type {d.get('type')!r}")
        _as_str("topology_hash", _need(d, "topology_hash", "packet_format"))
        _as_str("attachment_hash",
                _need(d, "attachment_hash", "packet_format"))
        _as_str("vc_assignment_hash",
                _need(d, "vc_assignment_hash", "packet_format"))
        raw_layout = _need(d, "field_layout", "packet_format")
        if not isinstance(raw_layout, list) or not raw_layout:
            raise PacketFormatError("field_layout must be a non-empty list")
        layout = tuple(PacketField.from_dict(f) for f in raw_layout)
        raw_encoding = _need(d, "flit_type_encoding", "packet_format")
        if not isinstance(raw_encoding, list):
            raise PacketFormatError("flit_type_encoding must be a list")
        encoding = tuple(
            (_as_str("flit type name", pair[0]),
             _as_non_negative_int("flit type code", pair[1]))
            for pair in raw_encoding
            if isinstance(pair, (list, tuple)) and len(pair) == 2
        )
        if len(encoding) != len(raw_encoding):
            raise PacketFormatError(
                "flit_type_encoding entries must be [name, code] pairs")
        return cls(
            topology_hash=d["topology_hash"],
            attachment_hash=d["attachment_hash"],
            vc_assignment_hash=d["vc_assignment_hash"],
            flit_width_bits=_need(d, "flit_width_bits", "packet_format"),
            packetization=_need(d, "packetization", "packet_format"),
            max_packet_flits=_need(d, "max_packet_flits", "packet_format"),
            header_replication=_need(d, "header_replication",
                                     "packet_format"),
            field_layout=layout,
            flit_type_encoding=encoding,
            schema_version=_need(d, "schema_version", "packet_format"),
            artifact_hash=_need(d, "artifact_hash", "packet_format"),
        )

    # ── parent validation ──────────────────────────────────────────────
    def validate_against(self, topology: TopologyArtifact,
                         attachment: AgentAttachmentArtifact,
                         vc_assignment: VCAssignmentArtifact) -> None:
        """Prove the packet format is legal for its direct parents."""
        if self.topology_hash != topology.topology_hash():
            raise PacketFormatError(
                "topology_hash does not match the materialized topology")
        if self.attachment_hash != attachment.attachment_hash():
            raise PacketFormatError(
                "attachment_hash does not match the attachment artifact")
        if self.vc_assignment_hash != vc_assignment.vc_assignment_hash():
            raise PacketFormatError(
                "vc_assignment_hash does not match the VC assignment")
        eids = [e.endpoint_id for e in attachment.endpoints]
        if eids != list(range(len(eids))):
            raise PacketFormatError(
                "attachment endpoint ids must be contiguous from 0")
        if len(eids) > self.endpoint_capacity:
            raise PacketFormatError(
                f"{len(eids)} endpoints exceed the {self.endpoint_capacity} "
                f"encodable by {self.endpoint_width_bits} bits")
        if vc_assignment.vc_count > self.vc_capacity:
            raise PacketFormatError(
                f"vc_count {vc_assignment.vc_count} exceeds the "
                f"{self.vc_capacity} encodable by {self.vc_width_bits} bits")
        widths = {c.width_bits for c in topology.channels}
        if widths:
            if len(widths) != 1:
                raise PacketFormatError(
                    f"heterogeneous channel widths {sorted(widths)} are not "
                    "supported by PacketFormat v1")
            channel_width = next(iter(widths))
            if self.flit_width_bits != channel_width:
                raise PacketFormatError(
                    f"flit_width_bits {self.flit_width_bits} != physical "
                    f"channel width {channel_width} (v1 requires exactly one "
                    "flit per channel beat)")
        _validate_layout(self.field_layout, self.flit_width_bits)
        _validate_flit_encoding(self.flit_type_encoding)


def derive_packet_format(
        *,
        topology: TopologyArtifact,
        attachment: AgentAttachmentArtifact,
        vc_assignment: VCAssignmentArtifact,
        requested_flit_width_bits: int | None = None,
        max_packet_flits: int = DEFAULT_MAX_PACKET_FLITS,
) -> PacketFormatArtifact:
    """Canonical builder: parents -> pinned v1 wire layout.

    Width rule:
      * requested width wins if supplied;
      * else all channels must share one width and that width is used;
      * else (zero-channel topology) the v1 default 64 bits is used.
    In every case, if the topology has channels they must all equal the
    chosen flit width.
    """
    if not isinstance(topology, TopologyArtifact):
        raise PacketFormatError(
            f"topology must be a TopologyArtifact, got "
            f"{type(topology).__name__}")
    if not isinstance(attachment, AgentAttachmentArtifact):
        raise PacketFormatError(
            f"attachment must be an AgentAttachmentArtifact, got "
            f"{type(attachment).__name__}")
    if not isinstance(vc_assignment, VCAssignmentArtifact):
        raise PacketFormatError(
            f"vc_assignment must be a VCAssignmentArtifact, got "
            f"{type(vc_assignment).__name__}")
    max_packet_flits = _as_positive_int(
        "max_packet_flits", max_packet_flits)
    widths = {c.width_bits for c in topology.channels}
    if requested_flit_width_bits is not None:
        flit_width = _as_positive_int(
            "requested_flit_width_bits", requested_flit_width_bits)
    elif widths:
        if len(widths) != 1:
            raise PacketFormatError(
                f"heterogeneous channel widths {sorted(widths)} are not "
                "supported by PacketFormat v1")
        flit_width = next(iter(widths))
    else:
        flit_width = DEFAULT_FLIT_WIDTH_BITS
    if widths and flit_width not in widths:
        raise PacketFormatError(
            f"requested flit width {flit_width} does not match the "
            f"materialized channel widths {sorted(widths)}")
    endpoint_count = len(attachment.endpoints)
    if endpoint_count < 1:
        raise PacketFormatError("attachment has no endpoints")
    endpoint_width = encoding_width(endpoint_count)
    vc_width = encoding_width(vc_assignment.vc_count)
    header_width = 2 * endpoint_width + 2 + vc_width
    payload_width = flit_width - header_width
    if payload_width < 1:
        raise PacketFormatError(
            f"UNSUPPORTED: header ({header_width} bits: "
            f"{endpoint_width}-bit endpoints x2 + 2-bit flit type + "
            f"{vc_width}-bit VC) consumes the whole {flit_width}-bit flit; "
            "the physical link width is not grown automatically")
    layout = canonical_field_layout(
        endpoint_width=endpoint_width, vc_width=vc_width,
        payload_width=payload_width)
    artifact = PacketFormatArtifact(
        topology_hash=topology.topology_hash(),
        attachment_hash=attachment.attachment_hash(),
        vc_assignment_hash=vc_assignment.vc_assignment_hash(),
        flit_width_bits=flit_width,
        packetization=PACKETIZATION_BOUNDED_WORMHOLE,
        max_packet_flits=max_packet_flits,
        header_replication=HEADER_REPLICATION_EVERY_FLIT,
        field_layout=layout,
    )
    artifact.validate_against(topology, attachment, vc_assignment)
    return artifact


def network_packet_count(message_bits: int,
                         artifact: PacketFormatArtifact) -> int:
    """Network packets needed to carry ``message_bits`` under v1.

    Semantic packet counting only: protocol framing/reassembly overhead
    is the NI's responsibility and is deliberately not modeled here.
    """
    message_bits = _as_non_negative_int("message_bits", message_bits)
    capacity = artifact.max_network_packet_payload_bits
    if message_bits == 0:
        return 0
    return (message_bits + capacity - 1) // capacity
