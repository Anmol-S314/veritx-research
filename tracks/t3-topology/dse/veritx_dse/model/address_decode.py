"""veritx_dse.model.address_decode — AddressDecodeArtifact (B3.5d/B3.5e).

AddressDecodeArtifact is the exact authority mapping customer address
ranges to canonical fabric endpoint ids. It is derived from
``CompileRequest.address_map`` plus ``AgentAttachmentArtifact`` and copies
only the address semantics that affect generated NI hardware.

Schema v2 (B3.5e) makes the boundary explicit:

    AddressDecodeEntry (transported)
        name                    NON-SEMANTIC presentation/trace label
        base
        size
        target_agent_group
        target_endpoint_id

    AddressDecodeArtifact
        attachment_hash
        entries                 canonical semantic order
        address_transform = IDENTITY
        unmatched_address_policy = ERROR
        schema_version = 2

    domain: srota/AddressDecode/v2\\0

Hardware identity per entry is exactly
``(base, size, target_agent_group, target_endpoint_id)``; ``name`` travels
with the artifact for diagnostics but is excluded from the hash (the same
presentation/identity split RouteArtifact already uses). Renaming a range
therefore changes design/resolved identity but not hardware identity.

``address_transform = IDENTITY`` pins forwarding semantics: the decoder
selects the endpoint, and the original address value is forwarded
unchanged as protocol payload. There is no implicit base subtraction,
window remapping, aliasing, translation or hashing in v1/v2.

Because forwarding is IDENTITY, an entry must fit the target endpoint's
declared address interface:
``base + size <= 2 ** endpoint.interface.address_width_bits`` (and still
inside the global 64-bit system-address domain). No truncation, modulo,
base removal or implicit width adapter.

v1 restriction (fail closed, never invented): a range is executable only
when its target Agent group contains exactly one hardware instance.

Scope notes:
  * addresses do NOT go into network flit headers. AXI/CHI addresses stay
    protocol payload; the decoder runs at injection/NI and selects the
    PacketFormat ``destination_endpoint_id``.
  * ``validate_against_attachment`` proves hardware-local legality with no
    DesignRevision/AddressMap. ``validate_against`` additionally proves the
    table realizes a given address map, comparing semantic fields only.
  * the current rtlgen ``addr_to_router()`` behavior is legacy and
    non-authoritative; B3.6 must make RTL consume this materialized decoder.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .attachment import AgentAttachmentArtifact
from .compile_model import AddressMap

ADDRESS_DECODE_SCHEMA_VERSION = 2
_HASH_TYPE_TAG = "srota/AddressDecode"

ADDRESS_DOMAIN_BITS = 64
ADDRESS_DOMAIN_SIZE = 1 << ADDRESS_DOMAIN_BITS

ADDRESS_TRANSFORM_IDENTITY = "IDENTITY"
UNMATCHED_ADDRESS_POLICY_ERROR = "ERROR"


class AddressDecodeError(ValueError):
    """The address decode is invalid or unsupported — fail closed."""


def _as_int(name: str, value: Any) -> int:
    if type(value) is not int:
        raise AddressDecodeError(
            f"{name} must be an int, got {type(value).__name__}")
    return value


def _as_non_negative_int(name: str, value: Any) -> int:
    value = _as_int(name, value)
    if value < 0:
        raise AddressDecodeError(f"{name} must be >= 0, got {value}")
    return value


def _as_positive_int(name: str, value: Any) -> int:
    value = _as_int(name, value)
    if value < 1:
        raise AddressDecodeError(f"{name} must be >= 1, got {value}")
    return value


def _as_str(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise AddressDecodeError(f"{name} must be a non-empty string")
    return value


def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise AddressDecodeError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise AddressDecodeError(
            f"{where} has unknown fields: {sorted(unknown)}")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise AddressDecodeError(
            f"{where} is missing required field {key!r}")
    return d[key]


def _semantic_key(entry: "AddressDecodeEntry") -> tuple:
    """Hardware identity/order of one entry: ``name`` is excluded."""
    return (entry.base, entry.size, entry.target_agent_group,
            entry.target_endpoint_id)


def _semantic_tuple(entries: tuple["AddressDecodeEntry", ...]) -> tuple:
    return tuple(_semantic_key(e) for e in entries)


@dataclass(frozen=True)
class AddressDecodeEntry:
    """One decoded customer address range -> canonical endpoint id."""

    name: str
    base: int
    size: int
    target_agent_group: int
    target_endpoint_id: int

    def __post_init__(self):
        _as_str("entry name", self.name)
        _as_non_negative_int("entry base", self.base)
        _as_positive_int("entry size", self.size)
        _as_non_negative_int("target_agent_group", self.target_agent_group)
        _as_non_negative_int("target_endpoint_id", self.target_endpoint_id)
        if self.base + self.size > ADDRESS_DOMAIN_SIZE:
            raise AddressDecodeError(
                f"address range {self.name!r} overflows the "
                f"{ADDRESS_DOMAIN_BITS}-bit address domain: "
                f"base {self.base} + size {self.size}")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "base": self.base, "size": self.size,
                "target_agent_group": self.target_agent_group,
                "target_endpoint_id": self.target_endpoint_id}

    def semantic_dict(self) -> dict[str, Any]:
        return {"base": self.base, "size": self.size,
                "target_agent_group": self.target_agent_group,
                "target_endpoint_id": self.target_endpoint_id}

    @classmethod
    def from_dict(cls, d: Any) -> "AddressDecodeEntry":
        _strict_keys(d, frozenset({
            "name", "base", "size", "target_agent_group",
            "target_endpoint_id"}), "address decode entry")
        return cls(
            name=_need(d, "name", "address decode entry"),
            base=_need(d, "base", "address decode entry"),
            size=_need(d, "size", "address decode entry"),
            target_agent_group=_need(d, "target_agent_group",
                                     "address decode entry"),
            target_endpoint_id=_need(d, "target_endpoint_id",
                                     "address decode entry"),
        )


def _validate_entries(entries: Any) -> None:
    if not isinstance(entries, tuple):
        raise AddressDecodeError("entries must be a tuple")
    for entry in entries:
        if not isinstance(entry, AddressDecodeEntry):
            raise AddressDecodeError(
                f"entries must contain AddressDecodeEntry, got "
                f"{type(entry).__name__}")
    if tuple(sorted(entries, key=_semantic_key)) != entries:
        raise AddressDecodeError(
            "entries must be in canonical semantic order "
            "(base, size, target_agent_group, target_endpoint_id)")
    keys = [_semantic_key(e) for e in entries]
    if len(set(keys)) != len(keys):
        raise AddressDecodeError(
            "entries contain duplicate semantic ranges")
    for prev, cur in zip(entries, entries[1:]):
        if prev.base + prev.size > cur.base:
            raise AddressDecodeError(
                f"address ranges {prev.name!r} and {cur.name!r} overlap "
                f"({prev.base}+{prev.size} > {cur.base})")


@dataclass(frozen=True)
class AddressDecodeArtifact:
    """Materialized customer-address -> fabric-endpoint decode table.

    The dataclass field is ``artifact_hash`` for consistency with the other
    semantic artifacts; the canonical accessor is ``address_decode_hash()``
    and the persisted JSON key is ``address_decode_hash``.
    """

    attachment_hash: str
    entries: tuple[AddressDecodeEntry, ...]
    address_transform: str = ADDRESS_TRANSFORM_IDENTITY
    unmatched_address_policy: str = UNMATCHED_ADDRESS_POLICY_ERROR
    schema_version: int = ADDRESS_DECODE_SCHEMA_VERSION
    artifact_hash: str = ""

    def __post_init__(self):
        _as_str("attachment_hash", self.attachment_hash)
        if self.address_transform != ADDRESS_TRANSFORM_IDENTITY:
            raise AddressDecodeError(
                f"unsupported address_transform {self.address_transform!r} "
                f"in v2 (only {ADDRESS_TRANSFORM_IDENTITY!r}: the selected "
                "endpoint receives the original address unchanged)")
        if self.unmatched_address_policy != UNMATCHED_ADDRESS_POLICY_ERROR:
            raise AddressDecodeError(
                f"unsupported unmatched_address_policy "
                f"{self.unmatched_address_policy!r} in v2 "
                f"(only {UNMATCHED_ADDRESS_POLICY_ERROR!r})")
        if type(self.schema_version) is not int or \
                self.schema_version != ADDRESS_DECODE_SCHEMA_VERSION:
            raise AddressDecodeError(
                f"unsupported address-decode schema_version "
                f"{self.schema_version!r} (expected "
                f"{ADDRESS_DECODE_SCHEMA_VERSION})")
        _validate_entries(self.entries)
        expected = self._compute_hash()
        if self.artifact_hash and self.artifact_hash != expected:
            raise AddressDecodeError(
                "address_decode_hash does not match content")
        if not self.artifact_hash:
            object.__setattr__(self, "artifact_hash", expected)

    # ── identity (semantic; names excluded) ────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "attachment_hash": self.attachment_hash,
            "address_transform": self.address_transform,
            "unmatched_address_policy": self.unmatched_address_policy,
            "entries": [e.semantic_dict() for e in self.entries],
        }

    def _compute_hash(self) -> str:
        from veritx_dse.core.spec import canonical_json
        body = (f"{_HASH_TYPE_TAG}/v{self.schema_version}\0"
                + canonical_json(self.identity_dict()))
        return hashlib.sha256(body.encode()).hexdigest()

    def address_decode_hash(self) -> str:
        return self._compute_hash()

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "attachment_hash": self.attachment_hash,
            "address_transform": self.address_transform,
            "unmatched_address_policy": self.unmatched_address_policy,
            "entries": [e.to_dict() for e in self.entries],
            "address_decode_hash": self.address_decode_hash(),
        }

    @classmethod
    def from_dict(cls, d: Any) -> "AddressDecodeArtifact":
        if not isinstance(d, dict):
            raise AddressDecodeError(
                f"address_decode must be an object, got {type(d).__name__}")
        if d.get("schema_version") == 1:
            raise AddressDecodeError(
                "AddressDecodeArtifact schema v1 is refused: it hashed the "
                "non-semantic range name and left address forwarding "
                "implicit. Rebuild with v2 (IDENTITY transform) — no silent "
                "migration")
        _strict_keys(d, frozenset({
            "type", "schema_version", "attachment_hash", "address_transform",
            "unmatched_address_policy", "entries", "address_decode_hash",
        }), "address_decode")
        if _need(d, "type", "address_decode") != _HASH_TYPE_TAG:
            raise AddressDecodeError(
                f"unexpected artifact type {d.get('type')!r}")
        raw_entries = _need(d, "entries", "address_decode")
        if not isinstance(raw_entries, list):
            raise AddressDecodeError("address_decode.entries must be a list")
        return cls(
            attachment_hash=_need(d, "attachment_hash", "address_decode"),
            entries=tuple(AddressDecodeEntry.from_dict(e)
                          for e in raw_entries),
            address_transform=_need(d, "address_transform", "address_decode"),
            unmatched_address_policy=_need(
                d, "unmatched_address_policy", "address_decode"),
            schema_version=_need(d, "schema_version", "address_decode"),
            artifact_hash=_need(d, "address_decode_hash", "address_decode"),
        )

    # ── hardware-local legality (no design context) ────────────────────
    def validate_against_attachment(
            self, attachment: AgentAttachmentArtifact) -> None:
        """Prove hardware-local decode legality.

        No DesignRevision, NodeInventory or AddressMap is required: the
        fabric must be provable from its hardware children alone.
        """
        if not isinstance(attachment, AgentAttachmentArtifact):
            raise AddressDecodeError(
                f"attachment must be an AgentAttachmentArtifact, got "
                f"{type(attachment).__name__}")
        if self.attachment_hash != attachment.attachment_hash():
            raise AddressDecodeError(
                "attachment_hash does not match the attachment artifact")
        by_id = {e.endpoint_id: e for e in attachment.endpoints}
        for entry in self.entries:
            endpoint = by_id.get(entry.target_endpoint_id)
            if endpoint is None:
                raise AddressDecodeError(
                    f"address range {entry.name!r} targets endpoint "
                    f"{entry.target_endpoint_id}, which is not in the "
                    "attachment")
            if endpoint.agent.group_index != entry.target_agent_group:
                raise AddressDecodeError(
                    f"address range {entry.name!r} declares Agent group "
                    f"{entry.target_agent_group} but endpoint "
                    f"{entry.target_endpoint_id} belongs to group "
                    f"{endpoint.agent.group_index}")
            group_peers = [e for e in attachment.endpoints
                           if e.agent.group_index == entry.target_agent_group]
            if len(group_peers) != 1:
                raise AddressDecodeError(
                    f"UNSUPPORTED: address range {entry.name!r} targets "
                    f"Agent group {entry.target_agent_group} with "
                    f"{len(group_peers)} attached instances; AddressDecode "
                    "v2 requires singleton target groups (no selection/"
                    "interleave policy exists in the design model)")
            width = endpoint.interface.address_width_bits
            if entry.base + entry.size > (1 << width):
                raise AddressDecodeError(
                    f"UNSUPPORTED: address range {entry.name!r} "
                    f"(base {entry.base:#x} + size {entry.size:#x}) cannot "
                    f"be represented by target endpoint "
                    f"{entry.target_endpoint_id}'s {width}-bit address "
                    "interface under IDENTITY forwarding (no translation/"
                    "truncation adapter exists)")

    # ── design-value equivalence ───────────────────────────────────────
    def validate_against(self, address_map: AddressMap,
                         attachment: AgentAttachmentArtifact) -> None:
        """Prove the table realizes a given address map (semantic fields).

        ``name`` is presentation and does not participate: two design
        revisions differing only in range labels reuse the same hardware
        decode artifact.
        """
        if not isinstance(address_map, AddressMap):
            raise AddressDecodeError(
                f"address_map must be an AddressMap, got "
                f"{type(address_map).__name__}")
        self.validate_against_attachment(attachment)
        expected = _expected_entries(address_map, attachment)
        if _semantic_tuple(self.entries) != _semantic_tuple(expected):
            raise AddressDecodeError(
                "address decode entries do not match the design address "
                "map + attachment (missing/extra/changed range)")


def _expected_entries(address_map: AddressMap,
                      attachment: AgentAttachmentArtifact
                      ) -> tuple[AddressDecodeEntry, ...]:
    expected = []
    for r in address_map.ranges:
        group = r.target_agent_idx
        endpoints = [e for e in attachment.endpoints
                     if e.agent.group_index == group]
        if not endpoints:
            raise AddressDecodeError(
                f"address range {r.name!r} targets Agent group {group}, "
                f"which has no attached endpoint in the attachment")
        if len(endpoints) > 1:
            raise AddressDecodeError(
                f"UNSUPPORTED: address range {r.name!r} targets Agent group "
                f"{group} with {len(endpoints)} attached instances; "
                "AddressDecode v2 requires singleton target groups (no "
                "selection/interleave policy exists in the design model)")
        endpoint = endpoints[0]
        expected.append(AddressDecodeEntry(
            name=r.name, base=r.base, size=r.size,
            target_agent_group=group,
            target_endpoint_id=endpoint.endpoint_id))
    return tuple(sorted(expected, key=_semantic_key))


def derive_address_decode(*, design, attachment: AgentAttachmentArtifact
                          ) -> AddressDecodeArtifact:
    """Materialize the decode table from design address map + attachment.

    ``design`` must expose ``address_map`` and ``agents``. The design-level
    checks (group exists, singleton count) fail closed with UNSUPPORTED
    before any endpoint is selected.
    """
    if not isinstance(attachment, AgentAttachmentArtifact):
        raise AddressDecodeError(
            f"attachment must be an AgentAttachmentArtifact, got "
            f"{type(attachment).__name__}")
    address_map = getattr(design, "address_map", None)
    groups = getattr(design, "agents", None)
    if address_map is None or groups is None:
        raise AddressDecodeError("design must expose .address_map and .agents")
    for r in address_map.ranges:
        group = r.target_agent_idx
        if not 0 <= group < len(groups):
            raise AddressDecodeError(
                f"address range {r.name!r} targets Agent group {group}, "
                f"outside the design's {len(groups)} groups")
        if groups[group].count != 1:
            raise AddressDecodeError(
                f"UNSUPPORTED: address range {r.name!r} targets Agent group "
                f"{group} with count {groups[group].count}; AddressDecode "
                "v2 requires singleton target groups (no selection/"
                "interleave policy exists in the design model)")
    artifact = AddressDecodeArtifact(
        attachment_hash=attachment.attachment_hash(),
        entries=_expected_entries(address_map, attachment),
    )
    artifact.validate_against(address_map, attachment)
    return artifact
