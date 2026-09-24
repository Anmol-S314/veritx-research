"""veritx_dse.model.address_decode — canonical NI address-decode semantics.

``AddressDecodeArtifact`` is the exact authority mapping customer/system
address ranges to canonical fabric endpoint ids:

    system address range -> canonical destination endpoint

The decoder runs before network injection. It selects the canonical
destination endpoint encoded by the Slice-17 ``PacketFormatArtifact``. The
original protocol address itself remains payload/protocol data and is
forwarded unchanged; addresses do NOT enter the NoC flit header.

Its only hardware parent is ``AgentAttachmentArtifact``: the attachment
already carries canonical endpoint identity and endpoint interface
semantics (address width). Topology, mapping, node inventory, design hash,
packet format, route/relation, VC resources and router behavior do not
participate.

Schema v3 is intentionally new. Historical schema v1 hashed the
non-semantic range name and left forwarding implicit; historical schema v2
used the pre-consolidation identity implementation and historical parent
identities. Canonical v3 uses Slice-1 ``content_id`` with domain
``srota/AddressDecodeArtifact/v3``; historical hashes are not reproduced.

    AddressDecodeEntry (transported)
        name                    NON-SEMANTIC presentation/trace label
        base
        size
        target_agent_group
        target_endpoint_id

Hardware identity per entry is exactly
``(base, size, target_agent_group, target_endpoint_id)``. ``name``
round-trips for diagnostics but is excluded from the hash, so renaming a
range does not move hardware identity.

``address_transform = IDENTITY`` pins forwarding semantics: the decoder
selects the endpoint and the original address value is forwarded
unchanged. There is no base subtraction, modulo, aliasing,
hash/interleave, translation, truncation or remapping.

``unmatched_address_policy = ERROR``: unmatched addresses are never
silently routed anywhere.

Because forwarding is IDENTITY, an entry must fit the target endpoint's
declared address interface:
``base + size <= 2 ** endpoint.interface.address_width_bits`` (and inside
the global 64-bit system-address domain). No truncation or hidden width
adapter exists.

A range is executable only when its target Agent group contains exactly one
hardware instance. The current design model has no semantics defining how a
range is distributed across multiple instances, so singleton target groups
are the only exact interpretation; multi-instance targets fail closed with
UNSUPPORTED rather than inventing striping, round-robin, channel selection,
hashing or address-bit interleave.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.model.attachment import AgentAttachmentArtifact
from veritx_dse.model.compile_model import (
    AddressMap, CompileRequest, CompileRequestV3,
)

ADDRESS_DECODE_SCHEMA_VERSION = 3
_HASH_TYPE_TAG = "srota/AddressDecodeArtifact"

ADDRESS_DOMAIN_BITS = 64
ADDRESS_DOMAIN_SIZE = 1 << ADDRESS_DOMAIN_BITS


class AddressDecodeError(ValueError):
    """The address decode is invalid or unsupported — fail closed."""


def _as_int(name: str, value: Any) -> int:
    if type(value) is not int:
        raise AddressDecodeError(
            f"{name} must be an exact int, got {type(value).__name__}")
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


def _as_hash(name: str, value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(c not in "0123456789abcdef" for c in value):
        raise AddressDecodeError(
            f"{name} must be a 64-character lowercase hex digest")
    return value


def _require_enum(name: str, enum_cls: type[Enum], value: Any) -> None:
    if not isinstance(value, enum_cls):
        raise AddressDecodeError(
            f"{name} must be a {enum_cls.__name__}, got "
            f"{type(value).__name__}")


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


def _enum(name: str, enum_cls: type[Enum], value: Any) -> Enum:
    if not isinstance(value, str):
        raise AddressDecodeError(
            f"{name} must be a string enum value, got "
            f"{type(value).__name__}")
    try:
        return enum_cls(value)
    except ValueError:
        raise AddressDecodeError(
            f"unknown {name} {value!r}; known: "
            f"{[member.value for member in enum_cls]}") from None


# ── vocabulary ────────────────────────────────────────────────────────────

class AddressTransform(Enum):
    """How the NI decoder treats the protocol address value."""

    IDENTITY = "IDENTITY"


class UnmatchedAddressPolicy(Enum):
    """What happens to an address that matches no decoded range."""

    ERROR = "ERROR"


# ── entries ───────────────────────────────────────────────────────────────

def _semantic_key(entry: "AddressDecodeEntry") -> tuple:
    """Hardware identity/order of one entry: ``name`` is excluded."""
    return (entry.base, entry.size, entry.target_agent_group,
            entry.target_endpoint_id)


def _semantic_tuple(entries: tuple["AddressDecodeEntry", ...]) -> tuple:
    return tuple(_semantic_key(entry) for entry in entries)


@dataclass(frozen=True)
class AddressDecodeEntry:
    """One decoded system address range -> canonical endpoint id."""

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

    def semantic_dict(self) -> dict[str, Any]:
        """Hardware identity payload: ``name`` deliberately absent."""
        return {"base": self.base, "size": self.size,
                "target_agent_group": self.target_agent_group,
                "target_endpoint_id": self.target_endpoint_id}

    def to_dict(self) -> dict[str, Any]:
        d = {"name": self.name}
        d.update(self.semantic_dict())
        return d

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
    keys = [_semantic_key(entry) for entry in entries]
    if len(set(keys)) != len(keys):
        raise AddressDecodeError(
            "entries contain duplicate semantic ranges")
    for prev, cur in zip(entries, entries[1:]):
        if prev.base + prev.size > cur.base:
            raise AddressDecodeError(
                f"address ranges {prev.name!r} and {cur.name!r} overlap "
                f"({prev.base}+{prev.size} > {cur.base})")


# ── the artifact ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AddressDecodeArtifact:
    """Materialized system-address -> fabric-endpoint decode table."""

    attachment_hash: str
    entries: tuple[AddressDecodeEntry, ...]
    address_transform: AddressTransform
    unmatched_address_policy: UnmatchedAddressPolicy
    schema_version: int = ADDRESS_DECODE_SCHEMA_VERSION
    address_decode_hash: str = ""

    def __post_init__(self):
        _as_hash("attachment_hash", self.attachment_hash)
        _require_enum("address_transform", AddressTransform,
                      self.address_transform)
        if self.address_transform is not AddressTransform.IDENTITY:
            raise AddressDecodeError(
                f"UNSUPPORTED address_transform "
                f"{self.address_transform.value!r} in v3 (only IDENTITY: "
                "the selected endpoint receives the original address "
                "unchanged; no translation/truncation exists)")
        _require_enum("unmatched_address_policy", UnmatchedAddressPolicy,
                      self.unmatched_address_policy)
        if self.unmatched_address_policy is not \
                UnmatchedAddressPolicy.ERROR:
            raise AddressDecodeError(
                f"UNSUPPORTED unmatched_address_policy "
                f"{self.unmatched_address_policy.value!r} in v3 "
                "(only ERROR; unmatched addresses are never silently "
                "routed)")
        if type(self.schema_version) is not int or \
                self.schema_version != ADDRESS_DECODE_SCHEMA_VERSION:
            raise AddressDecodeError(
                f"unsupported address-decode schema_version "
                f"{self.schema_version!r} (expected "
                f"{ADDRESS_DECODE_SCHEMA_VERSION})")
        _validate_entries(self.entries)
        expected = self._compute_hash()
        if self.address_decode_hash:
            _as_hash("address_decode_hash", self.address_decode_hash)
            if self.address_decode_hash != expected:
                raise AddressDecodeError(
                    "address_decode_hash does not match content")
        else:
            object.__setattr__(self, "address_decode_hash", expected)

    # ── identity (semantic; names excluded) ────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "attachment_hash": self.attachment_hash,
            "address_transform": self.address_transform.value,
            "unmatched_address_policy": self.unmatched_address_policy.value,
            "entries": [entry.semantic_dict() for entry in self.entries],
        }

    def _compute_hash(self) -> str:
        return content_id(f"{_HASH_TYPE_TAG}/v{self.schema_version}",
                          self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["entries"] = [entry.to_dict() for entry in self.entries]
        d["address_decode_hash"] = self._compute_hash()
        return d

    # ── persisted parsing (validate, never repair) ─────────────────────
    @classmethod
    def from_dict(cls, d: Any) -> "AddressDecodeArtifact":
        if isinstance(d, dict):
            version = d.get("schema_version")
            if type(version) is int and version == 1:
                raise AddressDecodeError(
                    "AddressDecodeArtifact schema v1 is refused: it hashed "
                    "the non-semantic range name and left address "
                    "forwarding implicit. Rebuild with canonical v3 "
                    "(IDENTITY transform, ERROR unmatched policy) — no "
                    "silent migration")
            if type(version) is int and version == 2:
                raise AddressDecodeError(
                    "AddressDecodeArtifact schema v2 is refused: it used "
                    "the pre-consolidation identity implementation and "
                    "historical parent identities. Rebuild with canonical "
                    "v3 — no silent migration")
        allowed = frozenset({
            "type", "schema_version", "attachment_hash", "address_transform",
            "unmatched_address_policy", "entries", "address_decode_hash",
        })
        _strict_keys(d, allowed, "address_decode")
        if _need(d, "type", "address_decode") != _HASH_TYPE_TAG:
            raise AddressDecodeError(
                f"address decode type must be {_HASH_TYPE_TAG!r}, got "
                f"{d.get('type')!r}")
        raw_entries = _need(d, "entries", "address_decode")
        if not isinstance(raw_entries, list):
            raise AddressDecodeError(
                "address_decode.entries must be a JSON list")
        return cls(
            attachment_hash=_need(d, "attachment_hash", "address_decode"),
            entries=tuple(AddressDecodeEntry.from_dict(entry)
                          for entry in raw_entries),
            address_transform=_enum(
                "address transform", AddressTransform,
                _need(d, "address_transform", "address_decode")),
            unmatched_address_policy=_enum(
                "unmatched address policy", UnmatchedAddressPolicy,
                _need(d, "unmatched_address_policy", "address_decode")),
            schema_version=_need(d, "schema_version", "address_decode"),
            address_decode_hash=_need(
                d, "address_decode_hash", "address_decode"),
        )

    # ── hardware-local legality (no design context) ────────────────────
    def validate_against_attachment(
            self, attachment: AgentAttachmentArtifact) -> None:
        """Prove hardware-local decode legality from the attachment alone."""
        if not isinstance(attachment, AgentAttachmentArtifact):
            raise AddressDecodeError(
                f"attachment must be an AgentAttachmentArtifact, got "
                f"{type(attachment).__name__}")
        if self.attachment_hash != attachment.attachment_hash():
            raise AddressDecodeError(
                "attachment_hash does not match the attachment artifact")
        by_id = {endpoint.endpoint_id: endpoint
                 for endpoint in attachment.endpoints}
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
            group_peers = [
                peer for peer in attachment.endpoints
                if peer.agent.group_index == entry.target_agent_group]
            if len(group_peers) != 1:
                raise AddressDecodeError(
                    f"UNSUPPORTED: address range {entry.name!r} targets "
                    f"Agent group {entry.target_agent_group} with "
                    f"{len(group_peers)} attached instances; address decode "
                    "v3 requires singleton target groups because the design "
                    "model defines no selection/interleave policy for "
                    "distributing a range across instances")
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
        """Prove the table realizes a given design address map.

        Range names are presentation and do not participate: two design
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
    expected: list[AddressDecodeEntry] = []
    for address_range in address_map.ranges:
        group = address_range.target_agent_idx
        endpoints = [endpoint for endpoint in attachment.endpoints
                     if endpoint.agent.group_index == group]
        if not endpoints:
            raise AddressDecodeError(
                f"address range {address_range.name!r} targets Agent group "
                f"{group}, which has no attached endpoint in the attachment")
        if len(endpoints) > 1:
            raise AddressDecodeError(
                f"UNSUPPORTED: address range {address_range.name!r} targets "
                f"Agent group {group} with {len(endpoints)} attached "
                "instances; address decode v3 requires singleton target "
                "groups because the design model defines no selection/"
                "interleave policy for distributing a range across "
                "instances")
        endpoint = endpoints[0]
        expected.append(AddressDecodeEntry(
            name=address_range.name, base=address_range.base,
            size=address_range.size, target_agent_group=group,
            target_endpoint_id=endpoint.endpoint_id))
    return tuple(sorted(expected, key=_semantic_key))


def derive_address_decode(*, design: CompileRequest | CompileRequestV3,
                          attachment: AgentAttachmentArtifact
                          ) -> AddressDecodeArtifact:
    """Materialize the decode table from a design address map + attachment.

    Group placement (mapping/rank) does not participate: rank placement has
    nothing to do with NI address decode. The design-level checks (group
    exists, singleton count) fail closed with UNSUPPORTED before any
    endpoint is selected.

    v3 requests are accepted for the fields they share with v2 (agents,
    address_map); the v3-only schema is never reinterpreted as v2.
    """
    if not isinstance(design, (CompileRequest, CompileRequestV3)):
        raise AddressDecodeError(
            f"design must be a CompileRequest, got "
            f"{type(design).__name__}")
    if not isinstance(attachment, AgentAttachmentArtifact):
        raise AddressDecodeError(
            f"attachment must be an AgentAttachmentArtifact, got "
            f"{type(attachment).__name__}")
    groups = design.agents
    for address_range in design.address_map.ranges:
        group = address_range.target_agent_idx
        if not 0 <= group < len(groups):
            raise AddressDecodeError(
                f"address range {address_range.name!r} targets Agent group "
                f"{group}, outside the design's {len(groups)} groups")
        if groups[group].count != 1:
            raise AddressDecodeError(
                f"UNSUPPORTED: address range {address_range.name!r} targets "
                f"Agent group {group} with count {groups[group].count}; "
                "address decode v3 requires singleton target groups because "
                "the design model defines no selection/interleave policy "
                "for distributing a range across instances")
    artifact = AddressDecodeArtifact(
        attachment_hash=attachment.attachment_hash(),
        entries=_expected_entries(design.address_map, attachment),
        address_transform=AddressTransform.IDENTITY,
        unmatched_address_policy=UnmatchedAddressPolicy.ERROR,
    )
    artifact.validate_against(design.address_map, attachment)
    return artifact
