"""CompileRequestV5 — explicit canonical composition for new Loom intent.

Rationale: docs/decisions/modules/model.md
Contract: docs/INTENT-V5-CONTRACT.md

V5 is an identity-bearing root. The compiler can structurally materialize
clock domains, sidebands and access-policy records while preserving this root.
That is not execution qualification: ``to_compile_request_v4`` still refuses
non-empty extensions instead of silently dropping them.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from veritx_dse.core.errors import SemanticError
from veritx_dse.core.spec import canonical_json
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.agent_interface import InterfaceRole
from veritx_dse.model.transaction_intent import TransactionPolicy
from veritx_dse.model.access_policy import AccessPolicyArtifact
from veritx_dse.model.sideband import (
    SidebandConnection, SidebandInterface, validate_sidebands,
)
from veritx_dse.model.domain_intent import (
    AsyncFIFOConfig, ClockDomain, ClockSource, Crossing, PowerDomain,
    ResetChannel, validate_clock_domains, validate_reset_channels,
)

COMPILE_REQUEST_SCHEMA_VERSION_V5 = 5
COMPILER_SEMANTICS_VERSION_V5 = 5
_HASH_TYPE_TAG_V5 = "srota/CompileRequest/v5"


class CompileRequestV5SchemaError(ValueError, SemanticError):
    """V5 strict parse or cross-reference refusal."""


class CompileRequestV5MigrationError(ValueError, SemanticError):
    """Explicit migration cannot preserve the source design's meaning."""


def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise CompileRequestV5SchemaError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise CompileRequestV5SchemaError(
            f"{where} has unknown fields: {sorted(unknown)}")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise CompileRequestV5SchemaError(
            f"{where} is missing required field {key!r}")
    return d[key]


def _sequence(name: str, value: Any, cls: type) -> tuple:
    if not isinstance(value, (list, tuple)):
        raise CompileRequestV5SchemaError(f"{name} must be a list")
    out = tuple(value)
    if any(not isinstance(item, cls) for item in out):
        raise CompileRequestV5SchemaError(
            f"{name} must contain {cls.__name__} values")
    return out


@dataclass(frozen=True)
class AgentIntentV5:
    """V5 interface and transaction extensions for one v4 Agent group.

    ``agent_group_index`` references the immutable position in the embedded v4
    design. V4 has no stable group-id field; V5 preserves this explicit binding
    rather than inventing one during migration.
    """

    agent_group_index: int
    interface_role: InterfaceRole | None = None
    transaction_policy: TransactionPolicy | None = None
    # Agent issue/service clock OUTSIDE the single-clock fabric attachment.
    # An execution adapter must bind an explicit bridge; never overwrite V4.
    transaction_clock_domain: str | None = None

    def __post_init__(self) -> None:
        if type(self.agent_group_index) is not int or self.agent_group_index < 0:
            raise CompileRequestV5SchemaError(
                "agent_group_index must be an exact non-negative int")
        if self.interface_role is not None and not isinstance(
                self.interface_role, InterfaceRole):
            raise CompileRequestV5SchemaError(
                "interface_role must be InterfaceRole or None (undeclared)")
        if self.transaction_policy is not None and not isinstance(
                self.transaction_policy, TransactionPolicy):
            raise CompileRequestV5SchemaError(
                "transaction_policy must be TransactionPolicy or None")
        if self.transaction_clock_domain is not None and (
                not isinstance(self.transaction_clock_domain, str) or not self.transaction_clock_domain):
            raise CompileRequestV5SchemaError("transaction_clock_domain must be a nonempty string or None")

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_group_index": self.agent_group_index,
            "interface_role": (self.interface_role.value
                               if self.interface_role else None),
            "transaction_policy": (self.transaction_policy.to_dict()
                                   if self.transaction_policy else None),
            **({"transaction_clock_domain": self.transaction_clock_domain}
               if self.transaction_clock_domain is not None else {}),
        }

    @classmethod
    def from_dict(cls, d: Any) -> "AgentIntentV5":
        _strict_keys(d, frozenset({"agent_group_index", "interface_role",
                                   "transaction_policy", "transaction_clock_domain"}), "agent_intent")
        role = d.get("interface_role")
        try:
            role = InterfaceRole(role) if role is not None else None
        except ValueError:
            raise CompileRequestV5SchemaError(
                f"unknown interface_role {role!r}") from None
        policy = d.get("transaction_policy")
        if policy is not None:
            policy = TransactionPolicy.from_dict(policy)
        return cls(_need(d, "agent_group_index", "agent_intent"), role,
                   policy, d.get("transaction_clock_domain"))


@dataclass(frozen=True)
class CompileRequestV5:
    """A V4 design plus explicit, identity-bearing V5 intent.

    FabricCompiler preserves this root and certifies supported declarative
    records against it. Unsupported extensions retain stage-owned refusals;
    backend execution remains unqualified. Empty extension collections are
    the sole lossless compatibility projection to V4.
    """

    base_v4: CompileRequestV4
    agent_intents: tuple[AgentIntentV5, ...] = ()
    sideband_interfaces: tuple[SidebandInterface, ...] = ()
    sideband_connections: tuple[SidebandConnection, ...] = ()
    access_policy: AccessPolicyArtifact | None = None
    clock_sources: tuple[ClockSource, ...] = ()
    clock_domains: tuple[ClockDomain, ...] = ()
    reset_channels: tuple[ResetChannel, ...] = ()
    power_domains: tuple[PowerDomain, ...] = ()
    crossings: tuple[Crossing, ...] = ()
    migration_provenance: dict[str, Any] | None = None
    schema_version: int = COMPILE_REQUEST_SCHEMA_VERSION_V5
    compiler_semantics_version: int = COMPILER_SEMANTICS_VERSION_V5

    def __post_init__(self) -> None:
        if not isinstance(self.base_v4, CompileRequestV4):
            raise CompileRequestV5SchemaError("base_v4 must be CompileRequestV4")
        if self.schema_version != COMPILE_REQUEST_SCHEMA_VERSION_V5:
            raise CompileRequestV5SchemaError(
                f"unsupported V5 schema_version {self.schema_version!r}")
        if self.compiler_semantics_version != COMPILER_SEMANTICS_VERSION_V5:
            raise CompileRequestV5SchemaError(
                "unsupported V5 compiler_semantics_version "
                f"{self.compiler_semantics_version!r}")
        typed = (
            ("agent_intents", self.agent_intents, AgentIntentV5),
            ("sideband_interfaces", self.sideband_interfaces,
             SidebandInterface),
            ("sideband_connections", self.sideband_connections,
             SidebandConnection),
            ("clock_sources", self.clock_sources, ClockSource),
            ("clock_domains", self.clock_domains, ClockDomain),
            ("reset_channels", self.reset_channels, ResetChannel),
            ("power_domains", self.power_domains, PowerDomain),
            ("crossings", self.crossings, Crossing),
        )
        sort_keys = {
            "agent_intents": lambda x: x.agent_group_index,
            "sideband_interfaces": lambda x: x.id,
            "sideband_connections": lambda x: x.connection_id,
            "clock_sources": lambda x: x.id,
            "clock_domains": lambda x: x.id,
            "reset_channels": lambda x: x.id,
            "power_domains": lambda x: x.id,
            "crossings": lambda x: x.id,
        }
        for name, values, cls in typed:
            parsed = _sequence(name, values, cls)
            object.__setattr__(self, name, tuple(sorted(parsed,
                                                       key=sort_keys[name])))
        if self.access_policy is not None and not isinstance(
                self.access_policy, AccessPolicyArtifact):
            raise CompileRequestV5SchemaError(
                "access_policy must be AccessPolicyArtifact or None")
        if self.migration_provenance is not None and not isinstance(
                self.migration_provenance, dict):
            raise CompileRequestV5SchemaError(
                "migration_provenance must be an object or None")

        group_count = len(self.base_v4.agents)
        group_indices = [x.agent_group_index for x in self.agent_intents]
        if len(set(group_indices)) != len(group_indices):
            raise CompileRequestV5SchemaError(
                "agent_intents has duplicate agent_group_index values")
        for i in group_indices:
            if i >= group_count:
                raise CompileRequestV5SchemaError(
                    f"agent_intents references group {i}, but base_v4 has "
                    f"{group_count} agent groups")

        try:
            validate_clock_domains(self.clock_sources, self.clock_domains)
            validate_reset_channels(
                self.reset_channels, self.clock_domains,
                check_domain_existence=True)
        except ValueError as exc:
            raise CompileRequestV5SchemaError(str(exc)) from exc

        reset_ids = [x.id for x in self.reset_channels]
        power_ids = [x.id for x in self.power_domains]
        crossing_ids = [x.id for x in self.crossings]
        for name, ids in (("reset", reset_ids), ("power", power_ids),
                          ("crossing", crossing_ids)):
            if len(ids) != len(set(ids)):
                raise CompileRequestV5SchemaError(
                    f"duplicate {name} intent ids: "
                    f"{sorted({x for x in ids if ids.count(x) > 1})}")

        known_clocks = {d.id for d in self.clock_domains}
        for intent in self.agent_intents:
            if intent.transaction_clock_domain is not None and intent.transaction_clock_domain not in known_clocks:
                raise CompileRequestV5SchemaError("transaction_clock_domain references an undeclared clock domain")
        for crossing in self.crossings:
            if crossing.src_clock not in known_clocks or \
                    crossing.dst_clock not in known_clocks:
                raise CompileRequestV5SchemaError(
                    f"crossing {crossing.id!r} references undeclared clock "
                    f"domains {crossing.src_clock!r}->{crossing.dst_clock!r}; "
                    f"declared: {sorted(known_clocks)}")

        agent_universe = tuple(f"group:{i}" for i in range(group_count))
        try:
            validate_sidebands(self.sideband_interfaces,
                               self.sideband_connections,
                               agent_universe=agent_universe)
        except ValueError as exc:
            raise CompileRequestV5SchemaError(str(exc)) from exc
        if self.access_policy is not None:
            known = set(agent_universe)
            for rule in self.access_policy.rules:
                if rule.initiator not in known or rule.target not in known:
                    raise CompileRequestV5SchemaError(
                        f"access rule {rule.rule_id!r} references agent groups "
                        f"{rule.initiator!r}->{rule.target!r}; expected refs "
                        f"from {sorted(known)}")

    def _extension_dict(self) -> dict[str, Any]:
        return {
            "agent_intents": [x.to_dict() for x in self.agent_intents],
            "sideband_interfaces": [x.to_dict()
                                    for x in self.sideband_interfaces],
            "sideband_connections": [x.to_dict()
                                     for x in self.sideband_connections],
            "access_policy": (self.access_policy.to_dict()
                              if self.access_policy else None),
            "clock_sources": [x.to_dict() for x in self.clock_sources],
            "clock_domains": [x.to_dict() for x in self.clock_domains],
            "reset_channels": [x.to_dict() for x in self.reset_channels],
            "power_domains": [x.to_dict() for x in self.power_domains],
            "crossings": [x.to_dict() for x in self.crossings],
        }

    def canonical_dict(self) -> dict[str, Any]:
        """Scientific identity; provenance and nested v4 hash envelopes excluded."""
        return {"base_v4": self.base_v4.canonical_dict(),
                **self._extension_dict()}

    def design_hash(self) -> str:
        body = (f"{_HASH_TYPE_TAG_V5}/v{self.schema_version}/"
                f"c{self.compiler_semantics_version}\0"
                + canonical_json(self.canonical_dict()))
        return hashlib.sha256(body.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        d = {
            "schema_version": self.schema_version,
            "compiler_semantics_version": self.compiler_semantics_version,
            "base_v4": self.base_v4.to_dict(),
            **self._extension_dict(),
        }
        if self.migration_provenance is not None:
            d["migration_provenance"] = dict(self.migration_provenance)
        d["design_hash"] = self.design_hash()
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "CompileRequestV5":
        if not isinstance(d, dict):
            raise CompileRequestV5SchemaError(
                f"CompileRequestV5 must be an object, got {type(d).__name__}")
        if d.get("schema_version") != COMPILE_REQUEST_SCHEMA_VERSION_V5:
            raise CompileRequestV5SchemaError(
                "V5 reader requires schema_version=5; use an explicit "
                "migration for older roots")
        _strict_keys(d, frozenset({
            "schema_version", "compiler_semantics_version", "base_v4",
            "agent_intents", "sideband_interfaces", "sideband_connections",
            "access_policy", "clock_sources", "clock_domains",
            "reset_channels", "power_domains", "crossings",
            "migration_provenance", "design_hash",
        }), "CompileRequestV5")
        base = CompileRequestV4.from_dict(_need(d, "base_v4", "CompileRequestV5"))
        def rows(key: str, parser) -> tuple:
            raw = d.get(key, [])
            if not isinstance(raw, list):
                raise CompileRequestV5SchemaError(f"{key} must be a list")
            return tuple(parser(x) for x in raw)
        obj = cls(
            base_v4=base,
            agent_intents=rows("agent_intents", AgentIntentV5.from_dict),
            sideband_interfaces=rows("sideband_interfaces",
                                     SidebandInterface.from_dict),
            sideband_connections=rows("sideband_connections",
                                      SidebandConnection.from_dict),
            access_policy=(AccessPolicyArtifact.from_dict(d["access_policy"])
                           if d.get("access_policy") is not None else None),
            clock_sources=rows("clock_sources", ClockSource.from_dict),
            clock_domains=rows("clock_domains", ClockDomain.from_dict),
            reset_channels=rows("reset_channels", ResetChannel.from_dict),
            power_domains=rows("power_domains", PowerDomain.from_dict),
            crossings=rows("crossings", Crossing.from_dict),
            migration_provenance=(dict(d["migration_provenance"])
                                  if d.get("migration_provenance") else None),
            schema_version=d["schema_version"],
            compiler_semantics_version=d["compiler_semantics_version"],
        )
        supplied = d.get("design_hash")
        if supplied is not None and supplied != obj.design_hash():
            raise CompileRequestV5SchemaError(
                f"design_hash mismatch: supplied {supplied!r}, computed "
                f"{obj.design_hash()!r}")
        return obj

    def to_compile_request_v4(self) -> CompileRequestV4:
        """Lossless compatibility projection only for neutral V5 extensions."""
        if any((self.agent_intents, self.sideband_interfaces,
                self.sideband_connections, self.access_policy,
                self.clock_sources, self.clock_domains, self.reset_channels,
                self.power_domains, self.crossings)):
            raise CompileRequestV5SchemaError(
                "V5-only intent is present; refusing to drop it when projecting "
                "to CompileRequestV4. Structural record materialization is "
                "not V5 backend execution qualification.")
        return self.base_v4


def migrate_v4_to_v5(request: CompileRequestV4) -> CompileRequestV5:
    """Explicit v4->v5 migration with only provably neutral empty extensions."""
    if not isinstance(request, CompileRequestV4):
        raise CompileRequestV5MigrationError(
            f"migrate_v4_to_v5 needs CompileRequestV4, got "
            f"{type(request).__name__}")
    return CompileRequestV5(
        base_v4=request,
        migration_provenance={
            "migrated_from": "CompileRequestV4",
            "source_design_hash": request.design_hash(),
            "neutral_extension_semantics": (
                "all V5 extension collections empty; this preserves v4 meaning; "
                "no interface role, transaction policy, permission, clock, "
                "reset, power, sideband, or crossing was guessed"),
        },
    )


__all__ = [
    "CompileRequestV5", "AgentIntentV5", "CompileRequestV5SchemaError",
    "CompileRequestV5MigrationError", "migrate_v4_to_v5",
    "COMPILE_REQUEST_SCHEMA_VERSION_V5", "COMPILER_SEMANTICS_VERSION_V5",
]
