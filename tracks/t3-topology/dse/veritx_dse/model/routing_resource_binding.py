"""veritx_dse.model.routing_resource_binding — abstract roles to concrete VCs.

``RoutingResourceBindingArtifact`` binds the abstract routing resource roles
declared by a :class:`RoutingPolicyDefinition` to the concrete virtual
channels declared by a :class:`VCResourceArtifact`:

    adaptive -> (1, 2, 3)
    escape   -> (0,)

The parents are the POLICY and the VC RESOURCES, never a
``RoutingRelationArtifact``: the relation materializes roles for one
topology, while this binding is topology-independent and must be reusable by
every topology-specific relation produced from the same policy.

V1 requires a total, disjoint partition of the VC universe:

  * every policy role is bound exactly once, with at least one VC;
  * every concrete VC belongs to exactly one role;
  * unbound/dangling VCs are refused (reserved VCs would need explicit
    semantics, not an implicit omission).

Transition consistency is exact AND per-source:

  * projecting every concrete ``src_vc -> dst_vc`` through the binding must
    yield exactly ``policy.allowed_role_transitions``;
  * for every allowed ``role_A -> role_B`` and every ``src_vc`` bound to
    ``role_A``, there must be at least one concrete transition into some
    ``dst_vc`` bound to ``role_B``.

The second rule is what prevents a VC inside a role from losing access to a
required next role. Traffic-class eligibility is not touched here: injection
eligibility and in-network role transitions are separate semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.model.routing_policy import RoutingPolicyDefinition
from veritx_dse.model.vc_resource import VCResourceArtifact

ROUTING_RESOURCE_BINDING_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/RoutingResourceBindingArtifact"


class RoutingResourceBindingError(ValueError):
    """The role-to-VC binding is malformed or inconsistent — fail closed."""


def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise RoutingResourceBindingError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise RoutingResourceBindingError(
            f"{where} has unknown fields: {sorted(unknown)}")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise RoutingResourceBindingError(
            f"{where} is missing required field {key!r}")
    return d[key]


def _as_int(name: str, value: Any, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise RoutingResourceBindingError(
            f"{name} must be an exact int, got {type(value).__name__}")
    if minimum is not None and value < minimum:
        raise RoutingResourceBindingError(f"{name} must be >= {minimum}")
    return value


def _as_str(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise RoutingResourceBindingError(
            f"{name} must be a non-empty string, got {value!r}")
    return value


def _json_list(name: str, value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise RoutingResourceBindingError(
            f"{name} must be a JSON list, got {type(value).__name__}")
    return value


@dataclass(frozen=True)
class RoutingResourceBindingArtifact:
    """Topology-independent partition of concrete VCs over routing roles."""

    policy_hash: str
    vc_resource_hash: str
    role_to_vcs: tuple[tuple[str, tuple[int, ...]], ...]
    schema_version: int = ROUTING_RESOURCE_BINDING_SCHEMA_VERSION
    binding_hash: str = ""

    def __post_init__(self):
        for name in ("policy_hash", "vc_resource_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise RoutingResourceBindingError(
                    f"{name} must be a non-empty string")
        if not isinstance(self.role_to_vcs, tuple):
            raise RoutingResourceBindingError(
                "role_to_vcs must be a tuple of (role_id, vcs) rows")
        rows: list[tuple[str, tuple[int, ...]]] = []
        for item in self.role_to_vcs:
            if not isinstance(item, tuple) or len(item) != 2:
                raise RoutingResourceBindingError(
                    "role_to_vcs rows must be (role_id, vcs) pairs")
            role_id, vcs = item
            _as_str("role id", role_id)
            if not isinstance(vcs, tuple):
                raise RoutingResourceBindingError(
                    f"role {role_id!r} VC set must be a tuple")
            if not vcs:
                raise RoutingResourceBindingError(
                    f"role {role_id!r} must bind at least one concrete VC")
            values = tuple(_as_int("bound VC", vc, minimum=0) for vc in vcs)
            if len(set(values)) != len(values):
                raise RoutingResourceBindingError(
                    f"role {role_id!r} binds a duplicate VC")
            rows.append((role_id, tuple(sorted(values))))
        if len({role for role, _vcs in rows}) != len(rows):
            raise RoutingResourceBindingError("role ids must be unique")
        rows.sort(key=lambda row: row[0])
        if type(self.schema_version) is not int or \
                self.schema_version != ROUTING_RESOURCE_BINDING_SCHEMA_VERSION:
            raise RoutingResourceBindingError(
                f"unsupported routing-resource-binding schema_version "
                f"{self.schema_version!r} (expected "
                f"{ROUTING_RESOURCE_BINDING_SCHEMA_VERSION})")
        object.__setattr__(self, "role_to_vcs", tuple(rows))
        expected = self._compute_hash()
        if self.binding_hash:
            if not isinstance(self.binding_hash, str) \
                    or self.binding_hash != expected:
                raise RoutingResourceBindingError(
                    "binding_hash does not match the role binding")
        else:
            object.__setattr__(self, "binding_hash", expected)

    # ── identity ─────────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "policy_hash": self.policy_hash,
            "vc_resource_hash": self.vc_resource_hash,
            "role_to_vcs": [[role_id, list(vcs)]
                            for role_id, vcs in self.role_to_vcs],
        }

    def _compute_hash(self) -> str:
        return content_id(f"{_HASH_TYPE_TAG}/v{self.schema_version}",
                          self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["binding_hash"] = self._compute_hash()
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "RoutingResourceBindingArtifact":
        allowed = frozenset({
            "type", "schema_version", "policy_hash", "vc_resource_hash",
            "role_to_vcs", "binding_hash",
        })
        _strict_keys(d, allowed, "routing_resource_binding")
        if _need(d, "type", "routing_resource_binding") != _HASH_TYPE_TAG:
            raise RoutingResourceBindingError(
                f"binding type must be {_HASH_TYPE_TAG!r}, got "
                f"{d.get('type')!r}")
        raw_rows = _json_list(
            "role_to_vcs", _need(d, "role_to_vcs", "routing_resource_binding"))
        rows: list[tuple[str, tuple[int, ...]]] = []
        for index, row in enumerate(raw_rows):
            if type(row) is not list or len(row) != 2:
                raise RoutingResourceBindingError(
                    f"role_to_vcs[{index}] must be a two-element JSON list")
            role_id = _as_str(f"role_to_vcs[{index}] role id", row[0])
            raw_vcs = _json_list(f"role_to_vcs[{index}] vcs", row[1])
            vcs = tuple(_as_int(f"role_to_vcs[{index}] VC", vc,
                                minimum=0) for vc in raw_vcs)
            if list(vcs) != list(sorted(set(vcs))):
                raise RoutingResourceBindingError(
                    f"role_to_vcs[{index}] VC set must be sorted and unique")
            rows.append((role_id, vcs))
        if rows != sorted(rows, key=lambda row: row[0]) or \
                len({role for role, _vcs in rows}) != len(rows):
            raise RoutingResourceBindingError(
                "role_to_vcs must be sorted by role id and unique")
        binding_hash = _need(d, "binding_hash", "routing_resource_binding")
        if not isinstance(binding_hash, str) or not binding_hash:
            raise RoutingResourceBindingError(
                "binding_hash must be a non-empty string")
        artifact = cls(
            policy_hash=_need(d, "policy_hash", "routing_resource_binding"),
            vc_resource_hash=_need(d, "vc_resource_hash",
                                   "routing_resource_binding"),
            role_to_vcs=tuple(rows),
            schema_version=_need(d, "schema_version",
                                 "routing_resource_binding"),
        )
        if binding_hash != artifact._compute_hash():
            raise RoutingResourceBindingError(
                "binding_hash does not match the role binding")
        return artifact

    # ── parent validation ────────────────────────────────────────────────
    def validate_against(self, policy: RoutingPolicyDefinition,
                         vc_resource: VCResourceArtifact) -> None:
        if not isinstance(policy, RoutingPolicyDefinition):
            raise RoutingResourceBindingError(
                "policy must be a RoutingPolicyDefinition")
        if not isinstance(vc_resource, VCResourceArtifact):
            raise RoutingResourceBindingError(
                "vc_resource must be a VCResourceArtifact")
        if self.policy_hash != policy.policy_hash:
            raise RoutingResourceBindingError(
                "policy_hash does not match the routing policy definition")
        if self.vc_resource_hash != vc_resource.artifact_hash:
            raise RoutingResourceBindingError(
                "vc_resource_hash does not match the VC resource artifact")

        declared_roles = {role.id for role in policy.resource_roles}
        bound_roles = {role_id for role_id, _vcs in self.role_to_vcs}
        missing_roles = sorted(declared_roles - bound_roles)
        undeclared_roles = sorted(bound_roles - declared_roles)
        if missing_roles or undeclared_roles:
            raise RoutingResourceBindingError(
                f"role coverage does not match the policy (missing "
                f"{missing_roles}, undeclared {undeclared_roles})")

        universe = set(vc_resource.vc_ids)
        owner: dict[int, str] = {}
        for role_id, vcs in self.role_to_vcs:
            for vc in vcs:
                if vc not in universe:
                    raise RoutingResourceBindingError(
                        f"role {role_id!r} binds VC {vc}, which is not in "
                        "the VC resource universe")
                if vc in owner:
                    raise RoutingResourceBindingError(
                        f"VC {vc} is bound to both {owner[vc]!r} and "
                        f"{role_id!r}; v1 requires disjoint role sets")
                owner[vc] = role_id
        unbound = sorted(universe - set(owner))
        if unbound:
            raise RoutingResourceBindingError(
                f"v1 requires a total partition of the VC universe; unbound "
                f"VCs {unbound}")

        concrete = set(vc_resource.allowed_transitions)
        projected = {(owner[src], owner[dst])
                     for src, dst in concrete}
        expected = set(policy.allowed_role_transitions)
        if projected != expected:
            raise RoutingResourceBindingError(
                "concrete VC transitions do not realize the policy role "
                f"transitions (missing {sorted(expected - projected)}, "
                f"forbidden {sorted(projected - expected)})")

        role_vcs = dict(self.role_to_vcs)
        for src_role, dst_role in policy.allowed_role_transitions:
            targets = role_vcs[dst_role]
            for src_vc in role_vcs[src_role]:
                if not any((src_vc, dst_vc) in concrete
                           for dst_vc in targets):
                    raise RoutingResourceBindingError(
                        f"VC {src_vc} of role {src_role!r} has no concrete "
                        f"transition into role {dst_role!r}")

        if self.binding_hash != self._compute_hash():
            raise RoutingResourceBindingError(
                "binding_hash does not match the role binding")
