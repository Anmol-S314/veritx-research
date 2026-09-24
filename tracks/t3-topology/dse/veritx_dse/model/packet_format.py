"""veritx_dse.model.packet_format — canonical routing-independent flit format.

``PacketFormatArtifact`` is the sole authority for what bits cross a NoC
link and how a bounded network packet is delimited. It does not route, does
not assign VCs, and carries no protocol metadata.

Parents are physical/semantic only:

    TopologyArtifact        -> physical channel beat width
    AgentAttachmentArtifact -> endpoint namespace
    VCResourceArtifact      -> concrete VC universe

The historical packet format was parented to ``VCAssignmentArtifact``. Schema
v2 deliberately replaces that routing-specific parent with
``VCResourceArtifact``: a flit must represent the concrete VC universe, not
whether those VCs belong to DOR classes, MinAdapt roles, Valiant phases or
anything else. The hash domain is therefore ``srota/PacketFormatArtifact/v2``
and historical packet-format hashes are intentionally not reproduced.

Canonical v2 wire fields, least-significant to most-significant:

    payload | source_endpoint | destination_endpoint | flit_type | vc_id

with ``endpoint_width = max(1, ceil(log2(endpoint_count)))``,
``vc_width = max(1, ceil(log2(vc_count)))`` and ``flit_type_width = 2``.
Schema v2 owns exactly one layout; user-defined field ordering is refused.
The layout is re-derived from the parents during ``validate_against``, so a
self-consistent but non-canonical layout cannot validate.

``vc_id`` is HOP_LOCAL: a legal VC transition rewrites only that field.
Traffic class, routing class, routing role, escape/phase semantics, QoS and
multicast are not wire fields.
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

from dataclasses import dataclass
from enum import Enum
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.model.attachment import AgentAttachmentArtifact, AttachmentError
from veritx_dse.model.topology_artifact import TopologyArtifact
from veritx_dse.model.vc_resource import VCResourceArtifact

PACKET_FORMAT_SCHEMA_VERSION = 2
_HASH_TYPE_TAG = "srota/PacketFormatArtifact"

FLIT_TYPE_HEAD = "HEAD"
FLIT_TYPE_BODY = "BODY"
FLIT_TYPE_TAIL = "TAIL"
FLIT_TYPE_SINGLE = "SINGLE"
FLIT_TYPE_WIDTH = 2

# The one canonical numeric encoding for schema v2 (historical pinned order).
FLIT_TYPE_ENCODING = (
    (FLIT_TYPE_HEAD, 0),
    (FLIT_TYPE_BODY, 1),
    (FLIT_TYPE_TAIL, 2),
    (FLIT_TYPE_SINGLE, 3),
)
FLIT_TYPES = tuple(name for name, _code in FLIT_TYPE_ENCODING)


class PacketFormatError(ValueError, SemanticError):
    """The packet/flit format is invalid or unsupported — fail closed."""


def _as_int(name: str, value: Any) -> int:
    if type(value) is not int:
        raise PacketFormatError(
            f"{name} must be an exact int, got {type(value).__name__}")
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
    """Bits needed to encode ids ``0..count-1``; at least 1."""
    count = _as_positive_int("encoding_width count", count)
    return max(1, (count - 1).bit_length())


# ── field schema ─────────────────────────────────────────────────────────

class FlitFieldRole(Enum):
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


_CANONICAL_NAMES = {
    FlitFieldRole.PAYLOAD: "payload",
    FlitFieldRole.SOURCE_ENDPOINT: "source_endpoint",
    FlitFieldRole.DESTINATION_ENDPOINT: "destination_endpoint",
    FlitFieldRole.FLIT_TYPE: "flit_type",
    FlitFieldRole.VC_ID: "vc_id",
}

_ROLE_MUTABILITY = {
    FlitFieldRole.PAYLOAD: FieldMutability.PAYLOAD,
    FlitFieldRole.SOURCE_ENDPOINT: FieldMutability.PACKET_IMMUTABLE,
    FlitFieldRole.DESTINATION_ENDPOINT: FieldMutability.PACKET_IMMUTABLE,
    FlitFieldRole.FLIT_TYPE: FieldMutability.FLIT_STRUCTURAL,
    FlitFieldRole.VC_ID: FieldMutability.HOP_LOCAL,
}

_CANONICAL_ROLE_ORDER = (
    FlitFieldRole.PAYLOAD,
    FlitFieldRole.SOURCE_ENDPOINT,
    FlitFieldRole.DESTINATION_ENDPOINT,
    FlitFieldRole.FLIT_TYPE,
    FlitFieldRole.VC_ID,
)


@dataclass(frozen=True)
class FlitField:
    """One contiguous bit field in the flit; ``msb`` is derived."""

    name: str
    lsb: int
    width: int
    role: FlitFieldRole
    mutability: FieldMutability

    def __post_init__(self):
        _as_str("field name", self.name)
        _as_non_negative_int("field lsb", self.lsb)
        _as_positive_int("field width", self.width)
        if not isinstance(self.role, FlitFieldRole):
            raise PacketFormatError(
                f"field role must be a FlitFieldRole, got {self.role!r}")
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
    def from_dict(cls, d: Any) -> "FlitField":
        _strict_keys(d, frozenset({"name", "lsb", "width", "role",
                                   "mutability"}), "flit field")
        role_value = _need(d, "role", "flit field")
        if not isinstance(role_value, str):
            raise PacketFormatError(f"unknown flit field role {role_value!r}")
        try:
            role = FlitFieldRole(role_value)
        except ValueError:
            raise PacketFormatError(
                f"unknown flit field role {role_value!r}") from None
        mutability_value = _need(d, "mutability", "flit field")
        if not isinstance(mutability_value, str):
            raise PacketFormatError(
                f"unknown flit field mutability {mutability_value!r}")
        try:
            mutability = FieldMutability(mutability_value)
        except ValueError:
            raise PacketFormatError(
                f"unknown flit field mutability {mutability_value!r}"
            ) from None
        return cls(
            name=_need(d, "name", "flit field"),
            lsb=_need(d, "lsb", "flit field"),
            width=_need(d, "width", "flit field"),
            role=role,
            mutability=mutability,
        )


def canonical_field_layout(*, endpoint_width: int, vc_width: int,
                           payload_width: int) -> tuple[FlitField, ...]:
    """The one canonical v2 layout, LSB -> MSB.

    ``payload | source_endpoint | destination_endpoint | flit_type | vc_id``
    """
    endpoint_width = _as_positive_int("endpoint_width", endpoint_width)
    vc_width = _as_positive_int("vc_width", vc_width)
    payload_width = _as_positive_int("payload_width", payload_width)
    return (
        FlitField("payload", 0, payload_width,
                  FlitFieldRole.PAYLOAD, FieldMutability.PAYLOAD),
        FlitField("source_endpoint", payload_width, endpoint_width,
                  FlitFieldRole.SOURCE_ENDPOINT,
                  FieldMutability.PACKET_IMMUTABLE),
        FlitField("destination_endpoint", payload_width + endpoint_width,
                  endpoint_width, FlitFieldRole.DESTINATION_ENDPOINT,
                  FieldMutability.PACKET_IMMUTABLE),
        FlitField("flit_type", payload_width + 2 * endpoint_width,
                  FLIT_TYPE_WIDTH, FlitFieldRole.FLIT_TYPE,
                  FieldMutability.FLIT_STRUCTURAL),
        FlitField("vc_id", payload_width + 2 * endpoint_width + FLIT_TYPE_WIDTH,
                  vc_width, FlitFieldRole.VC_ID, FieldMutability.HOP_LOCAL),
    )


def _validate_canonical_layout(fields: tuple[FlitField, ...],
                               flit_width_bits: int) -> None:
    if not isinstance(fields, tuple) or not fields:
        raise PacketFormatError("fields must be a non-empty tuple")
    for field in fields:
        if not isinstance(field, FlitField):
            raise PacketFormatError(
                f"fields must contain FlitField, got {type(field).__name__}")
    roles = [field.role for field in fields]
    if len(set(roles)) != len(roles):
        raise PacketFormatError("fields contain duplicate roles")
    missing = set(FlitFieldRole) - set(roles)
    if missing:
        raise PacketFormatError(
            f"fields are missing roles: "
            f"{sorted(role.value for role in missing)}")
    names = [field.name for field in fields]
    if len(set(names)) != len(names):
        raise PacketFormatError("fields contain duplicate names")
    ordered = tuple(sorted(fields, key=lambda field: field.lsb))
    if tuple(field.role for field in ordered) != _CANONICAL_ROLE_ORDER:
        raise PacketFormatError(
            "field order must be exactly the canonical v2 layout "
            "(payload, source_endpoint, destination_endpoint, flit_type, "
            "vc_id)")
    cursor = 0
    for field in ordered:
        if field.lsb != cursor:
            raise PacketFormatError(
                f"fields are not contiguous at bit {cursor}: field "
                f"{field.name!r} starts at {field.lsb}")
        cursor = field.lsb + field.width
    if cursor != flit_width_bits:
        raise PacketFormatError(
            f"fields cover {cursor} bits but the flit is {flit_width_bits} "
            "bits")
    by_role = {field.role: field for field in ordered}
    if by_role[FlitFieldRole.SOURCE_ENDPOINT].width \
            != by_role[FlitFieldRole.DESTINATION_ENDPOINT].width:
        raise PacketFormatError(
            "source_endpoint and destination_endpoint must share the same "
            "endpoint-namespace width")
    if by_role[FlitFieldRole.FLIT_TYPE].width != FLIT_TYPE_WIDTH:
        raise PacketFormatError(
            f"flit_type width must be exactly {FLIT_TYPE_WIDTH}")


# ── the artifact ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PacketFormatArtifact:
    """Canonical logical flit layout and bounded packet delimitation."""

    topology_hash: str
    attachment_hash: str
    vc_resource_hash: str
    flit_width_bits: int
    max_packet_flits: int
    fields: tuple[FlitField, ...]
    schema_version: int = PACKET_FORMAT_SCHEMA_VERSION
    packet_format_hash: str = ""

    def __post_init__(self):
        _as_str("topology_hash", self.topology_hash)
        _as_str("attachment_hash", self.attachment_hash)
        _as_str("vc_resource_hash", self.vc_resource_hash)
        _as_positive_int("flit_width_bits", self.flit_width_bits)
        _as_positive_int("max_packet_flits", self.max_packet_flits)
        if not isinstance(self.fields, tuple) or not self.fields:
            raise PacketFormatError("fields must be a non-empty tuple")
        for field in self.fields:
            if not isinstance(field, FlitField):
                raise PacketFormatError(
                    "fields must contain FlitField")
        fields = tuple(sorted(self.fields, key=lambda field: field.lsb))
        _validate_canonical_layout(fields, self.flit_width_bits)
        if type(self.schema_version) is not int or \
                self.schema_version != PACKET_FORMAT_SCHEMA_VERSION:
            raise PacketFormatError(
                f"unsupported packet-format schema_version "
                f"{self.schema_version!r} (expected "
                f"{PACKET_FORMAT_SCHEMA_VERSION})")
        object.__setattr__(self, "fields", fields)
        expected = self._compute_hash()
        if self.packet_format_hash:
            if not isinstance(self.packet_format_hash, str) \
                    or self.packet_format_hash != expected:
                raise PacketFormatError(
                    "packet_format_hash does not match content")
        else:
            object.__setattr__(self, "packet_format_hash", expected)

    # ── derived capacities (never persisted independently) ─────────────
    def _field(self, role: FlitFieldRole) -> FlitField:
        for field in self.fields:
            if field.role is role:
                return field
        raise PacketFormatError(f"fields have no {role.value!r} field")

    @property
    def payload_bits_per_flit(self) -> int:
        return self._field(FlitFieldRole.PAYLOAD).width

    @property
    def endpoint_width_bits(self) -> int:
        return self._field(FlitFieldRole.SOURCE_ENDPOINT).width

    @property
    def vc_width_bits(self) -> int:
        return self._field(FlitFieldRole.VC_ID).width

    @property
    def endpoint_capacity(self) -> int:
        return 2 ** self.endpoint_width_bits

    @property
    def vc_capacity(self) -> int:
        return 2 ** self.vc_width_bits

    @property
    def header_width_bits(self) -> int:
        return (2 * self.endpoint_width_bits + FLIT_TYPE_WIDTH
                + self.vc_width_bits)

    @property
    def max_network_payload_bits(self) -> int:
        return self.payload_bits_per_flit * self.max_packet_flits

    def network_packet_count_for_bits(self, message_bits: int) -> int:
        """Canonical network packetization count under the max payload.

        Semantic packet counting only: protocol framing/reassembly overhead
        is the NI's responsibility and is deliberately not modeled here.
        """
        message_bits = _as_positive_int("message_bits", message_bits)
        capacity = self.max_network_payload_bits
        return (message_bits + capacity - 1) // capacity

    # ── identity ───────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "topology_hash": self.topology_hash,
            "attachment_hash": self.attachment_hash,
            "vc_resource_hash": self.vc_resource_hash,
            "flit_width_bits": self.flit_width_bits,
            "max_packet_flits": self.max_packet_flits,
            "fields": [field.to_dict()
                       for field in sorted(self.fields,
                                           key=lambda field: field.lsb)],
        }

    def _compute_hash(self) -> str:
        return content_id(f"{_HASH_TYPE_TAG}/v{self.schema_version}",
                          self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["packet_format_hash"] = self._compute_hash()
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "PacketFormatArtifact":
        allowed = frozenset({
            "type", "schema_version", "topology_hash", "attachment_hash",
            "vc_resource_hash", "flit_width_bits", "max_packet_flits",
            "fields", "packet_format_hash",
        })
        _strict_keys(d, allowed, "packet_format")
        if _need(d, "type", "packet_format") != _HASH_TYPE_TAG:
            raise PacketFormatError(
                f"packet format type must be {_HASH_TYPE_TAG!r}, got "
                f"{d.get('type')!r}")
        raw_fields = _need(d, "fields", "packet_format")
        if not isinstance(raw_fields, list) or not raw_fields:
            raise PacketFormatError("fields must be a non-empty list")
        fields = tuple(FlitField.from_dict(field) for field in raw_fields)
        if list(fields) != list(sorted(fields, key=lambda f: f.lsb)):
            raise PacketFormatError(
                "persisted fields must be sorted by lsb")
        packet_format_hash = _need(d, "packet_format_hash", "packet_format")
        if not isinstance(packet_format_hash, str) or not packet_format_hash:
            raise PacketFormatError(
                "packet_format_hash must be a non-empty string")
        artifact = cls(
            topology_hash=_need(d, "topology_hash", "packet_format"),
            attachment_hash=_need(d, "attachment_hash", "packet_format"),
            vc_resource_hash=_need(d, "vc_resource_hash", "packet_format"),
            flit_width_bits=_need(d, "flit_width_bits", "packet_format"),
            max_packet_flits=_need(d, "max_packet_flits", "packet_format"),
            fields=fields,
            schema_version=_need(d, "schema_version", "packet_format"),
        )
        if packet_format_hash != artifact._compute_hash():
            raise PacketFormatError(
                "packet_format_hash does not match content")
        return artifact

    # ── parent validation ──────────────────────────────────────────────
    def validate_against(self, topology: TopologyArtifact,
                         attachment: AgentAttachmentArtifact,
                         vc_resource: VCResourceArtifact) -> None:
        """Prove the format is legal for its parents AND canonical.

        The expected layout is re-derived from the parents; a forged but
        self-consistent alternate layout is refused even when its own
        ``packet_format_hash`` matches.
        """
        if not isinstance(topology, TopologyArtifact):
            raise PacketFormatError("topology must be a TopologyArtifact")
        if not isinstance(attachment, AgentAttachmentArtifact):
            raise PacketFormatError(
                "attachment must be an AgentAttachmentArtifact")
        if not isinstance(vc_resource, VCResourceArtifact):
            raise PacketFormatError(
                "vc_resource must be a VCResourceArtifact")
        try:
            attachment.validate_against_topology(topology)
        except AttachmentError as exc:
            raise PacketFormatError(
                f"attachment is not legal for the topology: {exc}"
            ) from exc
        if self.topology_hash != topology.topology_hash():
            raise PacketFormatError(
                "topology_hash does not match the materialized topology")
        if self.attachment_hash != attachment.attachment_hash():
            raise PacketFormatError(
                "attachment_hash does not match the attachment artifact")
        if self.vc_resource_hash != vc_resource.artifact_hash:
            raise PacketFormatError(
                "vc_resource_hash does not match the VC resource artifact")

        widths = {channel.width_bits for channel in topology.channels}
        if not widths:
            raise PacketFormatError(
                "UNSUPPORTED: no inter-router channels exist from which to "
                "derive an unambiguous network flit width")
        if len(widths) != 1:
            raise PacketFormatError(
                f"heterogeneous channel widths {sorted(widths)} are not "
                "supported by PacketFormat v2")
        channel_width = next(iter(widths))
        if self.flit_width_bits != channel_width:
            raise PacketFormatError(
                f"flit_width_bits {self.flit_width_bits} != physical "
                f"channel width {channel_width}")

        endpoint_count = len(attachment.endpoints)
        if endpoint_count < 1:
            raise PacketFormatError("attachment has no endpoints")
        endpoint_width = encoding_width(endpoint_count)
        if self.endpoint_width_bits != endpoint_width:
            raise PacketFormatError(
                f"endpoint field width {self.endpoint_width_bits} is not the "
                f"canonical {endpoint_width} bits for {endpoint_count} "
                "endpoints")
        if self.endpoint_capacity < endpoint_count:
            raise PacketFormatError(
                f"{endpoint_count} endpoints exceed the "
                f"{self.endpoint_capacity} encodable by "
                f"{self.endpoint_width_bits} bits")
        vc_width = encoding_width(vc_resource.vc_count)
        if self.vc_width_bits != vc_width:
            raise PacketFormatError(
                f"VC field width {self.vc_width_bits} is not the canonical "
                f"{vc_width} bits for {vc_resource.vc_count} VCs")
        if self.vc_capacity < vc_resource.vc_count:
            raise PacketFormatError(
                f"vc_count {vc_resource.vc_count} exceeds the "
                f"{self.vc_capacity} encodable by {self.vc_width_bits} bits")

        header_width = 2 * endpoint_width + FLIT_TYPE_WIDTH + vc_width
        payload_width = self.flit_width_bits - header_width
        if payload_width < 1:
            raise PacketFormatError(
                f"UNSUPPORTED: header ({header_width} bits) consumes the "
                f"whole {self.flit_width_bits}-bit flit")
        expected = canonical_field_layout(
            endpoint_width=endpoint_width, vc_width=vc_width,
            payload_width=payload_width)
        if self.fields != expected:
            raise PacketFormatError(
                "fields are not the canonical layout derived from the "
                "parents")
        if self.packet_format_hash != self._compute_hash():
            raise PacketFormatError(
                "packet_format_hash does not match content")


def derive_packet_format(
        topology: TopologyArtifact,
        attachment: AgentAttachmentArtifact,
        vc_resource: VCResourceArtifact,
        *,
        max_packet_flits: int,
) -> PacketFormatArtifact:
    """Canonical builder: parents + explicit packet bound -> v2 layout.

    The flit width is derived from the materialized topology channels; there
    is no requested-width override and no default. Heterogeneous channel
    widths or a channel-less topology fail closed.
    """
    if not isinstance(topology, TopologyArtifact):
        raise PacketFormatError("topology must be a TopologyArtifact")
    if not isinstance(attachment, AgentAttachmentArtifact):
        raise PacketFormatError(
            "attachment must be an AgentAttachmentArtifact")
    if not isinstance(vc_resource, VCResourceArtifact):
        raise PacketFormatError("vc_resource must be a VCResourceArtifact")
    max_packet_flits = _as_positive_int("max_packet_flits", max_packet_flits)
    widths = {channel.width_bits for channel in topology.channels}
    if not widths:
        raise PacketFormatError(
            "UNSUPPORTED: no inter-router channels exist from which to "
            "derive an unambiguous network flit width")
    if len(widths) != 1:
        raise PacketFormatError(
            f"heterogeneous channel widths {sorted(widths)} are not "
            "supported by PacketFormat v2")
    flit_width = next(iter(widths))
    endpoint_count = len(attachment.endpoints)
    if endpoint_count < 1:
        raise PacketFormatError("attachment has no endpoints")
    endpoint_width = encoding_width(endpoint_count)
    vc_width = encoding_width(vc_resource.vc_count)
    header_width = 2 * endpoint_width + FLIT_TYPE_WIDTH + vc_width
    payload_width = flit_width - header_width
    if payload_width < 1:
        raise PacketFormatError(
            f"UNSUPPORTED: header ({header_width} bits: "
            f"{endpoint_width}-bit endpoints x2 + {FLIT_TYPE_WIDTH}-bit "
            f"flit type + {vc_width}-bit VC) consumes the whole "
            f"{flit_width}-bit flit")
    artifact = PacketFormatArtifact(
        topology_hash=topology.topology_hash(),
        attachment_hash=attachment.attachment_hash(),
        vc_resource_hash=vc_resource.artifact_hash,
        flit_width_bits=flit_width,
        max_packet_flits=max_packet_flits,
        fields=canonical_field_layout(
            endpoint_width=endpoint_width, vc_width=vc_width,
            payload_width=payload_width),
    )
    artifact.validate_against(topology, attachment, vc_resource)
    return artifact
