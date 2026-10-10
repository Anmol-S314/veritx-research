"""veritx_dse.model.access_policy — canonical initiator/target access policy.

What this layer is
------------------
``model/address_decode.py`` answers "which endpoint does this address reach?"
This layer answers a strictly different question: "is this operation *allowed*?"
The two are kept apart on purpose — a route existing does NOT mean access is
granted, so the ladder

    1. endpoint exists
    2. route exists
    3. address window matches
    4. permission allows the operation
    5. the transaction was observed/executed

is carried rung by rung on :class:`AccessDecision` and is never collapsed into a
single boolean. Each rung is ``bool | None`` where ``None`` means *not evaluated
here*, which is a fact about the caller's evidence, not a denial.

This is architectural access intent. It is not a firewall, not a crypto
trust boundary, and it makes no "zero trust" claim: see the
``access.firewall`` capability row for what would be needed to earn that.

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import SemanticError
from veritx_dse.model.address_decode import (
    ADDRESS_DOMAIN_BITS, ADDRESS_DOMAIN_SIZE,
)

ACCESS_POLICY_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/AccessPolicyArtifact"


class AccessPolicyError(ValueError, SemanticError):
    """The access policy is invalid or unsupported — fail closed."""


def _as_int(name: str, value: Any) -> int:
    if type(value) is not int:
        raise AccessPolicyError(
            f"{name} must be an exact int, got {type(value).__name__}")
    return value


def _as_non_negative_int(name: str, value: Any) -> int:
    value = _as_int(name, value)
    if value < 0:
        raise AccessPolicyError(f"{name} must be >= 0, got {value}")
    return value


def _as_positive_int(name: str, value: Any) -> int:
    value = _as_int(name, value)
    if value < 1:
        raise AccessPolicyError(f"{name} must be >= 1, got {value}")
    return value


def _as_str(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise AccessPolicyError(f"{name} must be a non-empty string")
    return value


def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise AccessPolicyError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise AccessPolicyError(
            f"{where} has unknown fields: {sorted(unknown)}")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise AccessPolicyError(f"{where} is missing required field {key!r}")
    return d[key]


def _enum(name: str, enum_cls: type[Enum], value: Any) -> Enum:
    if not isinstance(value, str):
        raise AccessPolicyError(
            f"{name} must be a string enum value, got "
            f"{type(value).__name__}")
    try:
        return enum_cls(value)
    except ValueError:
        raise AccessPolicyError(
            f"unknown {name} {value!r}; known: "
            f"{[member.value for member in enum_cls]}") from None


class AccessPermission(Enum):
    """What one initiator may do to a target's window.

    These four values are the whole vocabulary; there is no "DEFAULT" and no
    implicit grant. ``DENY`` is expressed by an explicit rule, never by the
    absence of one.
    """

    RW = "RW"
    RO = "RO"
    WO = "WO"
    DENY = "DENY"


class AddressSpace(Enum):
    """Which address space a window (and a query) lives in.

    The canonical design address map is a single system address space —
    ``model/address_decode.py`` models no local/global distinction — so
    ``GLOBAL`` is the value that reproduces today's behaviour exactly.
    ``LOCAL`` must be authored deliberately.
    """

    GLOBAL = "GLOBAL"
    LOCAL = "LOCAL"


class UnmatchedAccessPolicy(Enum):
    """What happens to an address that matches no rule.

    Defaults to ``DENY``: an unmapped access is denied unless the design
    *explicitly* opts into ``ALLOW``.
    """

    DENY = "DENY"
    ALLOW = "ALLOW"


def _rule_sort_key(rule: "AccessRule") -> tuple:
    """Canonical order: ``(initiator, target, address_base, address_size,
    rule_id)``. ``rule_id`` is required to be globally unique, so the key is
    unambiguous and declaration order can never enter identity."""
    return (rule.initiator, rule.target, rule.address_base,
            rule.address_size, rule.rule_id)


def _windows_overlap(a_base: int, a_size: int, b_base: int, b_size: int) -> bool:
    """Half-open ranges ``[base, base+size)`` intersect?"""
    return a_base < b_base + b_size and b_base < a_base + a_size


@dataclass(frozen=True)
class AccessRule:
    """One initiator's permission over one window of one target."""

    rule_id: str
    initiator: str
    target: str
    address_base: int
    address_size: int
    permission: AccessPermission
    address_space: AddressSpace = AddressSpace.GLOBAL

    def __post_init__(self):
        _as_str("rule_id", self.rule_id)
        _as_str("initiator", self.initiator)
        _as_str("target", self.target)
        _as_non_negative_int("address_base", self.address_base)
        _as_positive_int("address_size", self.address_size)
        if not isinstance(self.permission, AccessPermission):
            raise AccessPolicyError(
                "permission must be an AccessPermission, got "
                f"{type(self.permission).__name__}")
        if not isinstance(self.address_space, AddressSpace):
            raise AccessPolicyError(
                "address_space must be an AddressSpace, got "
                f"{type(self.address_space).__name__}")
        if self.initiator == self.target:
            raise AccessPolicyError(
                f"rule {self.rule_id!r} grants {self.initiator!r} permission "
                "over itself: an access rule needs distinct initiator and "
                "target")
        if self.address_base + self.address_size > ADDRESS_DOMAIN_SIZE:
            raise AccessPolicyError(
                f"rule {self.rule_id!r} overflows the "
                f"{ADDRESS_DOMAIN_BITS}-bit address domain: "
                f"address_base {self.address_base} + "
                f"address_size {self.address_size}")

    @property
    def address_end(self) -> int:
        """Exclusive end of the window."""
        return self.address_base + self.address_size

    def covers(self, address: int) -> bool:
        """Is ``address`` inside this rule's half-open window?"""
        return self.address_base <= address < self.address_end

    def allows(self, operation: str) -> bool:
        """Does this permission permit ``"read"`` or ``"write"``?"""
        if operation == "read":
            return self.permission in (AccessPermission.RW, AccessPermission.RO)
        if operation == "write":
            return self.permission in (AccessPermission.RW, AccessPermission.WO)
        raise AccessPolicyError(
            f"unknown operation {operation!r}; known: ['read', 'write']")

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "initiator": self.initiator,
            "target": self.target,
            "address_base": self.address_base,
            "address_size": self.address_size,
            "permission": self.permission.value,
            "address_space": self.address_space.value,
        }

    @classmethod
    def from_dict(cls, d: Any) -> "AccessRule":
        _strict_keys(d, frozenset({
            "rule_id", "initiator", "target", "address_base",
            "address_size", "permission", "address_space",
        }), "access rule")
        return cls(
            rule_id=_need(d, "rule_id", "access rule"),
            initiator=_need(d, "initiator", "access rule"),
            target=_need(d, "target", "access rule"),
            address_base=_need(d, "address_base", "access rule"),
            address_size=_need(d, "address_size", "access rule"),
            permission=_enum("permission", AccessPermission,
                             _need(d, "permission", "access rule")),
            address_space=_enum("address_space", AddressSpace,
                                d.get("address_space",
                                      AddressSpace.GLOBAL.value)),
        )


@dataclass(frozen=True)
class AccessDecision:
    """One access query, evaluated rung by rung.

    Every rung is ``bool | None``: ``None`` means *not evaluated here* and is
    NEVER coerced to ``False``. A caller that has no route evidence leaves
    ``route_exists`` as ``None`` rather than recording a denial it did not
    establish.
    """

    endpoint_exists: bool | None
    route_exists: bool | None
    window_matched: bool | None
    permission: AccessPermission | None
    observed: bool | None
    rule_id: str | None
    reason: str
    permitted: bool | None = None

    def __post_init__(self):
        for name in ("endpoint_exists", "route_exists", "window_matched",
                     "observed", "permitted"):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise AccessPolicyError(
                    f"{name} must be a bool or None (None means not "
                    f"evaluated), got {type(value).__name__}")
        if self.permission is not None and \
                not isinstance(self.permission, AccessPermission):
            raise AccessPolicyError(
                "permission must be an AccessPermission or None, got "
                f"{type(self.permission).__name__}")
        if self.rule_id is not None:
            _as_str("rule_id", self.rule_id)
        _as_str("reason", self.reason)

    @property
    def network_reachable(self) -> bool | None:
        """Window matched AND a route exists — independent of permission.

        This exists so the UI can render "network reachable" and "access
        forbidden" as two DIFFERENT facts (program scenario G). Evaluating
        either rung as unknown yields ``None``, never ``False``.
        """
        if self.window_matched is None or self.route_exists is None:
            return None
        return bool(self.window_matched and self.route_exists)

    @property
    def access_forbidden(self) -> bool | None:
        """Rung 4 verdict, or ``None`` when it was not evaluated.

        Server-owned so a client never has to re-derive policy semantics from
        the raw permission word (React must not decide capability).
        """
        if self.permitted is None:
            return None
        return not self.permitted

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoint_exists": self.endpoint_exists,
            "route_exists": self.route_exists,
            "window_matched": self.window_matched,
            "permission": (self.permission.value
                           if self.permission is not None else None),
            "observed": self.observed,
            "rule_id": self.rule_id,
            "reason": self.reason,
            "permitted": self.permitted,
        }

    @classmethod
    def from_dict(cls, d: Any) -> "AccessDecision":
        _strict_keys(d, frozenset({
            "endpoint_exists", "route_exists", "window_matched",
            "permission", "observed", "rule_id", "reason", "permitted",
        }), "access decision")
        raw_permission = _need(d, "permission", "access decision")
        return cls(
            endpoint_exists=d.get("endpoint_exists"),
            route_exists=d.get("route_exists"),
            window_matched=d.get("window_matched"),
            permission=(None if raw_permission is None
                        else _enum("permission", AccessPermission,
                                   raw_permission)),
            observed=d.get("observed"),
            rule_id=d.get("rule_id"),
            reason=_need(d, "reason", "access decision"),
            permitted=d.get("permitted"),
        )


def _validate_rules(rules: Any) -> None:
    """Type, canonical order, uniqueness and the address-overlap law.

    Overlap is checked within one ``(initiator, target, address_space)``
    triple: two rules covering the same bytes for the same pair is an
    ambiguous grant, so it refuses and names both colliding rule ids and
    their exact ranges.
    """
    if not isinstance(rules, tuple):
        raise AccessPolicyError("rules must be a tuple")
    for rule in rules:
        if not isinstance(rule, AccessRule):
            raise AccessPolicyError(
                f"rules must contain AccessRule, got {type(rule).__name__}")
    ids = [rule.rule_id for rule in rules]
    if len(set(ids)) != len(ids):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise AccessPolicyError(
            f"rule_id must be unique across the policy; duplicated: {dupes}")
    if tuple(sorted(rules, key=_rule_sort_key)) != rules:
        raise AccessPolicyError(
            "rules must be in canonical order "
            "(initiator, target, address_base, address_size, rule_id)")
    buckets: dict[tuple[str, str, AddressSpace], list[AccessRule]] = {}
    for rule in rules:
        buckets.setdefault(
            (rule.initiator, rule.target, rule.address_space), []).append(rule)
    for (initiator, target, space), group in sorted(
            buckets.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2].value)):
        for i, first in enumerate(group):
            for second in group[i + 1:]:
                if _windows_overlap(first.address_base, first.address_size,
                                    second.address_base, second.address_size):
                    raise AccessPolicyError(
                        f"address windows overlap for initiator "
                        f"{initiator!r} -> target {target!r} in "
                        f"{space.value}: rule {first.rule_id!r} "
                        f"[{first.address_base}, {first.address_end}) "
                        f"collides with rule {second.rule_id!r} "
                        f"[{second.address_base}, {second.address_end}). "
                        "Split the windows so each byte has exactly one "
                        "grant, or merge them into one rule.")


@dataclass(frozen=True)
class AccessPolicyArtifact:
    """The materialized I-T access policy for a design."""

    rules: tuple[AccessRule, ...]
    unmatched_policy: UnmatchedAccessPolicy = UnmatchedAccessPolicy.DENY
    schema_version: int = ACCESS_POLICY_SCHEMA_VERSION
    policy_hash: str = ""

    def __post_init__(self):
        if isinstance(self.rules, list):
            object.__setattr__(self, "rules", tuple(self.rules))
        if not isinstance(self.unmatched_policy, UnmatchedAccessPolicy):
            raise AccessPolicyError(
                "unmatched_policy must be an UnmatchedAccessPolicy, got "
                f"{type(self.unmatched_policy).__name__}")
        if type(self.schema_version) is not int or \
                self.schema_version != ACCESS_POLICY_SCHEMA_VERSION:
            raise AccessPolicyError(
                f"unsupported access-policy schema_version "
                f"{self.schema_version!r} (expected "
                f"{ACCESS_POLICY_SCHEMA_VERSION})")
        _validate_rules(self.rules)
        expected = self._compute_hash()
        if self.policy_hash:
            if not isinstance(self.policy_hash, str):
                raise AccessPolicyError("policy_hash must be a string")
            if self.policy_hash != expected:
                raise AccessPolicyError("policy_hash does not match content")
        else:
            object.__setattr__(self, "policy_hash", expected)

    def identity_dict(self) -> dict[str, Any]:
        """Identity payload. Declaration order is already canonical, and no
        presentation-only field exists on a rule, so nothing is stripped."""
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "unmatched_policy": self.unmatched_policy.value,
            "rules": [rule.to_dict() for rule in self.rules],
        }

    def _compute_hash(self) -> str:
        return content_id(f"{_HASH_TYPE_TAG}/v{self.schema_version}",
                          self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["policy_hash"] = self._compute_hash()
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "AccessPolicyArtifact":
        if not isinstance(d, dict):
            raise AccessPolicyError(
                f"access policy must be an object, got {type(d).__name__}")
        _strict_keys(d, frozenset({
            "type", "rules", "unmatched_policy", "schema_version",
            "policy_hash",
        }), "access policy")
        if _need(d, "type", "access policy") != _HASH_TYPE_TAG:
            raise AccessPolicyError(
                f"access policy type must be {_HASH_TYPE_TAG!r}, got "
                f"{d.get('type')!r}")
        raw_rules = _need(d, "rules", "access policy")
        if not isinstance(raw_rules, list):
            raise AccessPolicyError("access policy rules must be a list")
        supplied = d.get("policy_hash")
        return cls(
            rules=tuple(AccessRule.from_dict(r) for r in raw_rules),
            unmatched_policy=_enum(
                "unmatched_policy", UnmatchedAccessPolicy,
                d.get("unmatched_policy", UnmatchedAccessPolicy.DENY.value)),
            schema_version=d.get("schema_version",
                                 ACCESS_POLICY_SCHEMA_VERSION),
            policy_hash=supplied or "",
        )

    def _evaluate(
            self, *, operation: str, initiator: str, target: str,
            address: int, address_space: AddressSpace,
            endpoint_exists: bool | None, route_exists: bool | None,
            observed: bool | None) -> AccessDecision:
        if operation not in ("read", "write"):
            raise AccessPolicyError(
                f"unknown operation {operation!r}; known: ['read', 'write']")
        if not isinstance(address_space, AddressSpace):
            raise AccessPolicyError(
                "address_space must be an AddressSpace, got "
                f"{type(address_space).__name__}")
        _as_str("initiator", initiator)
        _as_str("target", target)
        _as_non_negative_int("address", address)

        for rule in self.rules:
            if rule.initiator != initiator or rule.target != target or \
                    rule.address_space is not address_space:
                continue
            if not rule.covers(address):
                continue
            allowed = rule.allows(operation)
            return AccessDecision(
                endpoint_exists=endpoint_exists,
                route_exists=route_exists,
                window_matched=True,
                permission=rule.permission,
                observed=observed,
                rule_id=rule.rule_id,
                permitted=allowed,
                reason=(
                    f"address {address:#x} matches rule {rule.rule_id!r}: "
                    f"{initiator} -> {target} is {rule.permission.value}; "
                    f"{operation} "
                    f"{'allowed by permission' if allowed else 'forbidden by permission'}"
                    f" (window [{rule.address_base}, {rule.address_end}) "
                    f"in {address_space.value} space)"),
            )

        allowed = self.unmatched_policy is UnmatchedAccessPolicy.ALLOW
        return AccessDecision(
            endpoint_exists=endpoint_exists,
            route_exists=route_exists,
            window_matched=False,
            permission=None,
            observed=observed,
            rule_id=None,
            permitted=allowed,
            reason=(
                f"no address window matches {address:#x} for "
                f"{initiator} -> {target} in {address_space.value} space: "
                f"unmatched_policy={self.unmatched_policy.value} so "
                f"{operation} is "
                f"{'allowed with NO governing permission (authored ALLOW)' if allowed else 'forbidden'}. "
                "No permission is invented for an unmapped address."),
        )

    def range_decisions(self, *, operation: str, initiator: str, target: str,
                        address: int, byte_length: int, address_space: AddressSpace,
                        endpoint_exists: bool | None = None, route_exists: bool | None = None,
                        observed: bool | None = None) -> tuple[tuple[int, int, AccessDecision], ...]:
        """Partition a half-open range at every policy boundary, including gaps."""
        _as_non_negative_int("address", address)
        _as_positive_int("byte_length", byte_length)
        end = address + byte_length
        if end > ADDRESS_DOMAIN_SIZE:
            raise AccessPolicyError("access range exceeds the canonical address domain")
        boundaries = {address, end}
        for rule in self.rules:
            if (rule.initiator == initiator and rule.target == target
                    and rule.address_space is address_space):
                boundaries.update(p for p in (rule.address_base, rule.address_end) if address < p < end)
        points = sorted(boundaries)
        return tuple((start, stop, self._evaluate(
            operation=operation, initiator=initiator, target=target, address=start,
            address_space=address_space, endpoint_exists=endpoint_exists,
            route_exists=route_exists, observed=observed))
            for start, stop in zip(points, points[1:]))

    def may_read(self, initiator: str, target: str, address: int,
                 *, address_space: AddressSpace = AddressSpace.GLOBAL,
                 endpoint_exists: bool | None = None,
                 route_exists: bool | None = None,
                 observed: bool | None = None) -> AccessDecision:
        """Evaluate a read. Unevaluated rungs stay ``None``."""
        return self._evaluate(
            operation="read", initiator=initiator, target=target,
            address=address, address_space=address_space,
            endpoint_exists=endpoint_exists, route_exists=route_exists,
            observed=observed)

    def may_write(self, initiator: str, target: str, address: int,
                  *, address_space: AddressSpace = AddressSpace.GLOBAL,
                  endpoint_exists: bool | None = None,
                  route_exists: bool | None = None,
                  observed: bool | None = None) -> AccessDecision:
        """Evaluate a write. Unevaluated rungs stay ``None``."""
        return self._evaluate(
            operation="write", initiator=initiator, target=target,
            address=address, address_space=address_space,
            endpoint_exists=endpoint_exists, route_exists=route_exists,
            observed=observed)


__all__ = [
    "ACCESS_POLICY_SCHEMA_VERSION",
    "AccessDecision",
    "AccessPermission",
    "AccessPolicyArtifact",
    "AccessPolicyError",
    "AccessRule",
    "AddressSpace",
    "UnmatchedAccessPolicy",
]
