"""veritx_dse.model.system_intent — SYSTEM intent v4 (Domain A closure).

The long-lived SYSTEM ontology: physical containment, stable agent-group
identity, typed clock/power domains, and the derived physical-inventory
artifact.

    SystemIntentV4
      containers[]     SystemContainer   physical containment only
      agent_groups[]   AgentGroup        stable group_id, never array position
      clock_domains[]  ClockDomain       typed; free text is gone
      power_domains[]  PowerDomain       typed; free text is gone
            │
            ▼ derive_physical_inventory
      PhysicalInventoryArtifact          immutable expanded supply

This module owns exactly that. It deliberately does NOT own:

  * logical ranks or the model rank space — PARALLELISM owns demand;
  * placement / mapping — PLACEMENT owns the join;
  * router seats, endpoints, attachments — FABRIC / attachment own those;
  * affinity or anti-affinity policy — PLACEMENT owns policy;
  * elastic ranges — DESIGN-SPACE owns search domains;
  * replication policy — count is the only multiplicity;
  * memory / failure / coherence / security domains — not SYSTEM concepts.

HIERARCHY DOES NOT IMPLY TOPOLOGY. Containment creates no link, no route,
no plane and no placement decision. A fabric policy that uses hierarchy
must consume it explicitly, downstream.

IDENTITY. ``system_intent_hash`` covers ids, kinds, counts, containment,
interfaces and domain membership. ``name`` on any entity is presentation
and is excluded — renaming never moves the scientific identity. Canonical
order is by id, so reordering a form is a no-op.

COMPATIBILITY. This is a NEW identity domain, exactly as v3 was against
v2. v3 requests are not reinterpreted; ``migrate_v3_agents_to_v4`` emits
explicit v4 facts and invents deterministic ids for positional groups
(``legacy-agent-group-NNN``). Migrated positional identity was never
named identity, and the migration does not pretend otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import SemanticError

from .compile_model import AgentKind

SYSTEM_INTENT_SCHEMA_VERSION = 4
PHYSICAL_INVENTORY_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/SystemIntent"
_INVENTORY_HASH_TYPE_TAG = "srota/PhysicalInventoryArtifact"
LEGACY_GROUP_ID_PREFIX = "legacy-agent-group-"


class SystemIntentError(ValueError, SemanticError):
    """Malformed SYSTEM intent — fail closed, never guess."""


# ── validators ────────────────────────────────────────────────────────────

def _as_int(name: str, value: Any, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise SystemIntentError(
            f"{name} must be an exact int, got {type(value).__name__}")
    if minimum is not None and value < minimum:
        raise SystemIntentError(f"{name} must be >= {minimum}, got {value}")
    return value


def _as_str(name: str, value: Any, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise SystemIntentError(
            f"{name} must be a string, got {type(value).__name__}")
    if not value and not allow_empty:
        raise SystemIntentError(f"{name} must be a non-empty string")
    return value


def _as_enum(name: str, value: Any, enum_cls: type[Enum]) -> Any:
    if not isinstance(value, enum_cls):
        raise SystemIntentError(
            f"{name} must be a {enum_cls.__name__}, got {type(value).__name__}")
    return value


def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise SystemIntentError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise SystemIntentError(
            f"{where} has unknown fields: {sorted(unknown)} — the schema is "
            "closed; extension dictionaries are refused")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise SystemIntentError(f"{where} is missing required field {key!r}")
    return d[key]


def _as_tuple(name: str, value: Any, cls: type) -> tuple:
    if isinstance(value, list):
        value = tuple(value)
    if not isinstance(value, tuple):
        raise SystemIntentError(f"{name} must be a tuple of {cls.__name__}")
    for item in value:
        if not isinstance(item, cls):
            raise SystemIntentError(
                f"{name} must contain {cls.__name__}, got {type(item).__name__}")
    return value


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    dup: set[str] = set()
    for v in values:
        if v in seen:
            dup.add(v)
        seen.add(v)
    return sorted(dup)


# ── vocabulary ────────────────────────────────────────────────────────────

class ContainerKind(Enum):
    """Physical containment kinds. Finite on purpose.

    ``BOARD`` is added only when a concrete use exists; ``CUSTOM`` is
    refused rather than used to dodge deciding semantics.
    """
    MACHINE = "machine"
    NODE = "node"
    PACKAGE = "package"
    ACCELERATOR = "accelerator"
    CHIPLET = "chiplet"


# ── entities ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SystemContainer:
    """One physical containment scope. Locality only — never topology."""

    container_id: str
    kind: ContainerKind
    parent_id: str | None = None
    name: str = ""  # presentation; excluded from identity

    def __post_init__(self):
        _as_str("container_id", self.container_id)
        _as_enum("kind", self.kind, ContainerKind)
        if self.parent_id is not None:
            _as_str("parent_id", self.parent_id)
            if self.parent_id == self.container_id:
                raise SystemIntentError(
                    f"container {self.container_id!r} is its own parent")
        _as_str("name", self.name, allow_empty=True)

    def identity_dict(self) -> dict[str, Any]:
        return {"container_id": self.container_id, "kind": self.kind.value,
                "parent_id": self.parent_id}

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["name"] = self.name
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "SystemContainer":
        _strict_keys(d, frozenset(
            {"container_id", "kind", "parent_id", "name"}), "container")
        try:
            kind = ContainerKind(_need(d, "kind", "container"))
        except ValueError as exc:
            raise SystemIntentError(
                f"unknown container kind {d.get('kind')!r}; known: "
                f"{[k.value for k in ContainerKind]}") from exc
        return cls(container_id=_need(d, "container_id", "container"),
                   kind=kind, parent_id=_need(d, "parent_id", "container"),
                   name=d.get("name", ""))


@dataclass(frozen=True)
class AgentInterface:
    """The interface shared by every instance of an agent group.

    ``addr_width`` is SEMANTIC_AND_CONSUMED: it bounds the address domain
    (``address_decode.py``). ``data_width`` and ``protocol`` are
    DECLARED / NOT INTERPRETED today — they enter attachment identity and
    therefore the certificate, but no consumer reads them. They are kept
    identity-bearing deliberately, pending a real interface contract.
    """

    data_width: int = 256
    addr_width: int = 64
    protocol: str = "AXI"

    def __post_init__(self):
        _as_int("data_width", self.data_width, minimum=8)
        _as_int("addr_width", self.addr_width, minimum=8)
        _as_str("protocol", self.protocol)

    def to_dict(self) -> dict[str, Any]:
        return {"data_width": self.data_width, "addr_width": self.addr_width,
                "protocol": self.protocol}

    @classmethod
    def from_dict(cls, d: Any) -> "AgentInterface":
        _strict_keys(d, frozenset({"data_width", "addr_width", "protocol"}),
                     "interface")
        return cls(data_width=_need(d, "data_width", "interface"),
                   addr_width=_need(d, "addr_width", "interface"),
                   protocol=_need(d, "protocol", "interface"))


@dataclass(frozen=True)
class ClockDomain:
    domain_id: str
    name: str = ""

    def __post_init__(self):
        _as_str("domain_id", self.domain_id)
        _as_str("name", self.name, allow_empty=True)

    def to_dict(self) -> dict[str, Any]:
        return {"domain_id": self.domain_id, "name": self.name}

    @classmethod
    def from_dict(cls, d: Any) -> "ClockDomain":
        _strict_keys(d, frozenset({"domain_id", "name"}), "clock_domain")
        return cls(domain_id=_need(d, "domain_id", "clock_domain"),
                   name=d.get("name", ""))


@dataclass(frozen=True)
class PowerDomain:
    domain_id: str
    name: str = ""

    def __post_init__(self):
        _as_str("domain_id", self.domain_id)
        _as_str("name", self.name, allow_empty=True)

    def to_dict(self) -> dict[str, Any]:
        return {"domain_id": self.domain_id, "name": self.name}

    @classmethod
    def from_dict(cls, d: Any) -> "PowerDomain":
        _strict_keys(d, frozenset({"domain_id", "name"}), "power_domain")
        return cls(domain_id=_need(d, "domain_id", "power_domain"),
                   name=d.get("name", ""))


@dataclass(frozen=True)
class AgentGroup:
    """A typed group of identical agents inside one container.

    ``group_id`` is the primary semantic reference. Array position is
    never identity, so reordering a form cannot change meaning.

    Heterogeneity is expressed by declaring a second group — the interface
    belongs to the group, not the instance.
    """

    group_id: str
    kind: AgentKind
    count: int
    container_id: str
    interface: AgentInterface = field(default_factory=AgentInterface)
    clock_domain_id: str | None = None
    power_domain_id: str | None = None
    name: str = ""

    def __post_init__(self):
        _as_str("group_id", self.group_id)
        _as_enum("kind", self.kind, AgentKind)
        _as_int("count", self.count, minimum=1)
        _as_str("container_id", self.container_id)
        if not isinstance(self.interface, AgentInterface):
            raise SystemIntentError(
                "interface must be an AgentInterface, got "
                f"{type(self.interface).__name__}")
        for fname in ("clock_domain_id", "power_domain_id"):
            value = getattr(self, fname)
            if value is not None:
                _as_str(fname, value)
        _as_str("name", self.name, allow_empty=True)

    @property
    def instance_ids(self) -> tuple[str, ...]:
        """Deterministic, position-independent instance identity."""
        return tuple(f"{self.group_id}/{i}" for i in range(self.count))

    def identity_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "kind": self.kind.value,
            "count": self.count,
            "container_id": self.container_id,
            "interface": self.interface.to_dict(),
            "clock_domain_id": self.clock_domain_id,
            "power_domain_id": self.power_domain_id,
        }

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["name"] = self.name
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "AgentGroup":
        _strict_keys(d, frozenset({
            "group_id", "kind", "count", "container_id", "interface",
            "clock_domain_id", "power_domain_id", "name"}), "agent_group")
        try:
            kind = AgentKind(_need(d, "kind", "agent_group"))
        except ValueError as exc:
            raise SystemIntentError(
                f"unknown agent kind {d.get('kind')!r}; known: "
                f"{[k.value for k in AgentKind]}") from exc
        return cls(
            group_id=_need(d, "group_id", "agent_group"),
            kind=kind,
            count=_need(d, "count", "agent_group"),
            container_id=_need(d, "container_id", "agent_group"),
            interface=AgentInterface.from_dict(
                _need(d, "interface", "agent_group")),
            clock_domain_id=d.get("clock_domain_id"),
            power_domain_id=d.get("power_domain_id"),
            name=d.get("name", ""),
        )


# ── the intent ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SystemIntentV4:
    """SYSTEM intent: containment, agent groups, typed domains.

    Intrinsic validation only. ``compute_instances >= world_size`` is a
    cross-domain placement feasibility check and is deliberately absent —
    SYSTEM must be valid independently of any workload.
    """

    containers: tuple[SystemContainer, ...]
    agent_groups: tuple[AgentGroup, ...]
    clock_domains: tuple[ClockDomain, ...] = ()
    power_domains: tuple[PowerDomain, ...] = ()
    schema_version: int = SYSTEM_INTENT_SCHEMA_VERSION

    def __post_init__(self):
        object.__setattr__(self, "containers",
                           _as_tuple("containers", self.containers,
                                     SystemContainer))
        object.__setattr__(self, "agent_groups",
                           _as_tuple("agent_groups", self.agent_groups,
                                     AgentGroup))
        object.__setattr__(self, "clock_domains",
                           _as_tuple("clock_domains", self.clock_domains,
                                     ClockDomain))
        object.__setattr__(self, "power_domains",
                           _as_tuple("power_domains", self.power_domains,
                                     PowerDomain))
        if _as_int("schema_version", self.schema_version) \
                != SYSTEM_INTENT_SCHEMA_VERSION:
            raise SystemIntentError(
                f"unsupported SystemIntent schema_version "
                f"{self.schema_version!r} (expected "
                f"{SYSTEM_INTENT_SCHEMA_VERSION})")

        # canonical order by id: reordering a form is a no-op
        object.__setattr__(self, "containers", tuple(sorted(
            self.containers, key=lambda c: c.container_id)))
        object.__setattr__(self, "agent_groups", tuple(sorted(
            self.agent_groups, key=lambda g: g.group_id)))
        object.__setattr__(self, "clock_domains", tuple(sorted(
            self.clock_domains, key=lambda d: d.domain_id)))
        object.__setattr__(self, "power_domains", tuple(sorted(
            self.power_domains, key=lambda d: d.domain_id)))

        self._validate_intrinsic()

    # ── intrinsic validation ───────────────────────────────────────────

    def _validate_intrinsic(self) -> None:
        if not self.agent_groups:
            raise SystemIntentError(
                "agent_groups cannot be empty — need at least one group")
        if not self.containers:
            raise SystemIntentError(
                "containers cannot be empty — a machine root must exist")

        for label, ids in (
            ("container_id", [c.container_id for c in self.containers]),
            ("group_id", [g.group_id for g in self.agent_groups]),
            ("clock domain_id", [d.domain_id for d in self.clock_domains]),
            ("power domain_id", [d.domain_id for d in self.power_domains]),
        ):
            dup = _duplicates(ids)
            if dup:
                raise SystemIntentError(f"duplicate {label}: {dup}")

        by_id = {c.container_id: c for c in self.containers}

        # exactly one root; every non-root has exactly one existing parent
        roots = [c for c in self.containers if c.parent_id is None]
        if len(roots) != 1:
            raise SystemIntentError(
                f"exactly one root container is required, found "
                f"{[c.container_id for c in roots]}")
        for c in self.containers:
            if c.parent_id is not None and c.parent_id not in by_id:
                raise SystemIntentError(
                    f"container {c.container_id!r} references missing parent "
                    f"{c.parent_id!r}")

        # acyclic: walk every chain to the root
        for c in self.containers:
            seen: set[str] = set()
            cur: str | None = c.container_id
            while cur is not None:
                if cur in seen:
                    raise SystemIntentError(
                        f"container parent cycle involving {cur!r}")
                seen.add(cur)
                cur = by_id[cur].parent_id

        clock_ids = {d.domain_id for d in self.clock_domains}
        power_ids = {d.domain_id for d in self.power_domains}
        for g in self.agent_groups:
            if g.container_id not in by_id:
                raise SystemIntentError(
                    f"agent group {g.group_id!r} references missing container "
                    f"{g.container_id!r}")
            if g.clock_domain_id is not None \
                    and g.clock_domain_id not in clock_ids:
                raise SystemIntentError(
                    f"agent group {g.group_id!r} references undeclared clock "
                    f"domain {g.clock_domain_id!r}")
            if g.power_domain_id is not None \
                    and g.power_domain_id not in power_ids:
                raise SystemIntentError(
                    f"agent group {g.group_id!r} references undeclared power "
                    f"domain {g.power_domain_id!r}")

    # ── structural queries (SYSTEM owns facts; PLACEMENT owns policy) ──

    def container_of(self, group_id: str) -> SystemContainer:
        by_id = {c.container_id: c for c in self.containers}
        for g in self.agent_groups:
            if g.group_id == group_id:
                return by_id[g.container_id]
        raise SystemIntentError(f"no such agent group: {group_id!r}")

    def ancestors(self, container_id: str) -> tuple[SystemContainer, ...]:
        """Containers from the given one up to the root (inclusive)."""
        by_id = {c.container_id: c for c in self.containers}
        if container_id not in by_id:
            raise SystemIntentError(f"no such container: {container_id!r}")
        chain: list[SystemContainer] = []
        cur: str | None = container_id
        while cur is not None:
            node = by_id[cur]
            chain.append(node)
            cur = node.parent_id
        return tuple(chain)

    def ancestor_of_kind(self, container_id: str,
                         kind: ContainerKind) -> SystemContainer | None:
        for c in self.ancestors(container_id):
            if c.kind == kind:
                return c
        return None

    def same_container(self, a_group_id: str, b_group_id: str,
                       kind: ContainerKind) -> bool:
        """Whether two groups share an ancestor container of ``kind``.

        This is the structural fact PLACEMENT consumes. It is NOT a policy.
        """
        a = self.ancestor_of_kind(self.container_of(a_group_id).container_id,
                                  kind)
        b = self.ancestor_of_kind(self.container_of(b_group_id).container_id,
                                  kind)
        return a is not None and b is not None \
            and a.container_id == b.container_id

    # ── identity ───────────────────────────────────────────────────────

    def identity_dict(self) -> dict[str, Any]:
        """Identity-bearing content only: ``name`` is presentation."""
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "containers": [c.identity_dict() for c in self.containers],
            "agent_groups": [g.identity_dict() for g in self.agent_groups],
            "clock_domains": [d.to_dict() for d in self.clock_domains],
            "power_domains": [d.to_dict() for d in self.power_domains],
        }

    def system_intent_hash(self) -> str:
        return content_id(f"{_HASH_TYPE_TAG}/v{self.schema_version}",
                          self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["containers"] = [c.to_dict() for c in self.containers]
        d["agent_groups"] = [g.to_dict() for g in self.agent_groups]
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "SystemIntentV4":
        _strict_keys(d, frozenset({
            "type", "schema_version", "containers", "agent_groups",
            "clock_domains", "power_domains"}), "system_intent")
        if d.get("type") != _HASH_TYPE_TAG:
            raise SystemIntentError(
                f"system intent type tag {d.get('type')!r} is not "
                f"{_HASH_TYPE_TAG!r}")
        return cls(
            containers=tuple(SystemContainer.from_dict(c)
                             for c in _need(d, "containers", "system_intent")),
            agent_groups=tuple(AgentGroup.from_dict(g)
                               for g in _need(d, "agent_groups",
                                              "system_intent")),
            clock_domains=tuple(ClockDomain.from_dict(x)
                                for x in d.get("clock_domains", ())),
            power_domains=tuple(PowerDomain.from_dict(x)
                                for x in d.get("power_domains", ())),
            schema_version=_need(d, "schema_version", "system_intent"),
        )


# ── derived: physical inventory ───────────────────────────────────────────

@dataclass(frozen=True)
class PhysicalInventoryArtifact:
    """The compiler-expanded physical supply side, with its own identity.

    Contains physical supply only. It deliberately excludes logical ranks,
    placement, router seats and endpoint attachments — those belong
    downstream. ``endpoint_demand`` is derived, never declared (S3).
    """

    system_intent_hash: str
    agent_count: int
    compute_instance_count: int
    endpoint_demand: int
    instances: tuple[tuple[str, str], ...]  # (instance_id, kind value)
    inventory_hash: str = ""
    schema_version: int = PHYSICAL_INVENTORY_SCHEMA_VERSION

    def __post_init__(self):
        _as_str("system_intent_hash", self.system_intent_hash)
        _as_int("agent_count", self.agent_count, minimum=0)
        _as_int("compute_instance_count", self.compute_instance_count,
                minimum=0)
        _as_int("endpoint_demand", self.endpoint_demand, minimum=0)
        if _as_int("schema_version", self.schema_version) \
                != PHYSICAL_INVENTORY_SCHEMA_VERSION:
            raise SystemIntentError(
                f"unsupported inventory schema_version "
                f"{self.schema_version!r}")
        if not isinstance(self.instances, tuple):
            raise SystemIntentError("instances must be a tuple of pairs")
        ids = []
        for pair in self.instances:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise SystemIntentError(
                    "instances entries must be (instance_id, kind) pairs")
            ids.append(_as_str("instance_id", pair[0]))
        dup = _duplicates(ids)
        if dup:
            raise SystemIntentError(f"duplicate instance_id: {dup}")
        expected = self._compute_hash()
        if self.inventory_hash:
            if self.inventory_hash != expected:
                raise SystemIntentError(
                    "inventory_hash does not match content")
        else:
            object.__setattr__(self, "inventory_hash", expected)

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _INVENTORY_HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "system_intent_hash": self.system_intent_hash,
            "agent_count": self.agent_count,
            "compute_instance_count": self.compute_instance_count,
            "endpoint_demand": self.endpoint_demand,
            "instances": [[i, k] for i, k in self.instances],
        }

    def _compute_hash(self) -> str:
        return content_id(
            f"{_INVENTORY_HASH_TYPE_TAG}/v{self.schema_version}",
            self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["inventory_hash"] = self._compute_hash()
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "PhysicalInventoryArtifact":
        _strict_keys(d, frozenset({
            "type", "schema_version", "system_intent_hash", "agent_count",
            "compute_instance_count", "endpoint_demand", "instances",
            "inventory_hash"}), "physical_inventory")
        if d.get("type") != _INVENTORY_HASH_TYPE_TAG:
            raise SystemIntentError(
                f"inventory type tag {d.get('type')!r} is not "
                f"{_INVENTORY_HASH_TYPE_TAG!r}")
        raw = _need(d, "instances", "physical_inventory")
        if not isinstance(raw, list):
            raise SystemIntentError("instances must be a JSON list")
        return cls(
            system_intent_hash=_need(d, "system_intent_hash",
                                     "physical_inventory"),
            agent_count=_need(d, "agent_count", "physical_inventory"),
            compute_instance_count=_need(d, "compute_instance_count",
                                         "physical_inventory"),
            endpoint_demand=_need(d, "endpoint_demand", "physical_inventory"),
            instances=tuple((pair[0], pair[1]) for pair in raw),
            inventory_hash=d.get("inventory_hash", ""),
            schema_version=_need(d, "schema_version", "physical_inventory"),
        )


def derive_physical_inventory(
        intent: SystemIntentV4) -> PhysicalInventoryArtifact:
    """Expand SYSTEM intent into immutable physical supply.

    Derivation only: no placement, no seats, no attachments, no ranks.
    """
    if not isinstance(intent, SystemIntentV4):
        raise SystemIntentError(
            "derive_physical_inventory takes a SystemIntentV4, got "
            f"{type(intent).__name__}")
    instances: list[tuple[str, str]] = []
    for group in intent.agent_groups:
        for instance_id in group.instance_ids:
            instances.append((instance_id, group.kind.value))
    agent_count = len(instances)
    compute_count = sum(1 for _, kind in instances
                        if kind == AgentKind.COMPUTE_TILE.value)
    return PhysicalInventoryArtifact(
        system_intent_hash=intent.system_intent_hash(),
        agent_count=agent_count,
        compute_instance_count=compute_count,
        # one agent instance -> one required attachment seat (S3)
        endpoint_demand=agent_count,
        instances=tuple(instances),
    )


# ── v3 -> v4 migration ────────────────────────────────────────────────────

def legacy_group_id(index: int) -> str:
    """Deterministic migration id for a positional v3 agent group.

    Migration only. Positional identity was never named identity; this
    invents a name, it does not recover one.
    """
    _as_int("index", index, minimum=0)
    return f"{LEGACY_GROUP_ID_PREFIX}{index:03d}"


def migrate_v3_agents_to_v4(
        agents: Any, *,
        clock_domain_names: tuple[str, ...] = (),
        power_domain_names: tuple[str, ...] = (),
        root_container_id: str = "machine",
) -> SystemIntentV4:
    """Re-emit v3 agent groups as an explicit v4 SYSTEM intent.

    Lossless for the fields v3 actually carries. The flat v3 model has no
    hierarchy, so every group lands in one MACHINE root — the migration
    does not invent structure it cannot know.
    """
    if not isinstance(agents, tuple):
        raise SystemIntentError("agents must be a tuple of v3 Agent groups")
    if not agents:
        raise SystemIntentError("agents cannot be empty")
    containers = [SystemContainer(container_id=root_container_id,
                                  kind=ContainerKind.MACHINE)]
    clock_domains = tuple(ClockDomain(domain_id=n)
                          for n in clock_domain_names)
    power_domains = tuple(PowerDomain(domain_id=n)
                          for n in power_domain_names)
    groups = []
    for index, agent in enumerate(agents):
        kind = getattr(agent, "kind", None)
        if not isinstance(kind, AgentKind):
            raise SystemIntentError(
                f"agents[{index}] is not a v3 Agent group")
        groups.append(AgentGroup(
            group_id=legacy_group_id(index),
            kind=kind,
            count=agent.count,
            container_id=root_container_id,
            interface=AgentInterface(
                data_width=agent.data_width,
                addr_width=agent.addr_width,
                protocol=agent.protocol),
            clock_domain_id=agent.clock_domain,
            power_domain_id=agent.power_domain,
        ))
    return SystemIntentV4(
        containers=tuple(containers),
        agent_groups=tuple(groups),
        clock_domains=clock_domains,
        power_domains=power_domains,
    )


def migrate_v3_address_targets(agents: Any) -> dict[int, str]:
    """Positional -> stable address-map target mapping.

    ``target_agent_idx = i`` -> ``legacy-agent-group-<i>``. A bijection, so
    the migration is lossless and preserves current decode semantics.
    """
    if not isinstance(agents, tuple):
        raise SystemIntentError("agents must be a tuple of v3 Agent groups")
    return {index: legacy_group_id(index) for index in range(len(agents))}


__all__ = [
    "SYSTEM_INTENT_SCHEMA_VERSION",
    "PHYSICAL_INVENTORY_SCHEMA_VERSION",
    "LEGACY_GROUP_ID_PREFIX",
    "SystemIntentError",
    "ContainerKind",
    "SystemContainer",
    "AgentInterface",
    "ClockDomain",
    "PowerDomain",
    "AgentGroup",
    "SystemIntentV4",
    "PhysicalInventoryArtifact",
    "derive_physical_inventory",
    "legacy_group_id",
    "migrate_v3_agents_to_v4",
    "migrate_v3_address_targets",
]
