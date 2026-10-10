"""veritx_dse.model.ip_catalog — the server-owned EDA IP primitive catalog.

Why this module exists
----------------------
The reference product renders an "EDA IP CATALOG" of primitives with vendor,
version and purchasable status. VERITX cannot claim any of that, and it must
not claim physical numbers it has no artifact for. This module is therefore
the ONE authority the product reads for IP primitives: React only renders it.

Hard rules encoded here (program sections 27, 48, 80, 89):

- **No invented PPA.** ``area_mm2`` and ``power_w`` are ``None`` when we have
  nothing, and they serialize as the literal ``"NOT PROVIDED"``. A number is
  REFUSED on input: an estimate must never be laundered into a catalog row and
  then quoted by a UI as if it were evidence.
- **Closed agent-kind set.** ``agent_kind`` must be a member of
  :class:`veritx_dse.model.compile_model.AgentKind`, which has exactly five
  members today. Nothing here invents a sixth. A primitive with no matching
  kind maps to the nearest real one and says so in ``provenance``, so the
  substitution is a visible statement rather than a silent relabelling.
- **Unsupported semantics stay PRESENT.** A primitive whose semantics we cannot
  yet carry is listed with the ``capability_requirements`` ids that must be
  READY before it can be stamped. Omitting it would hide the gap; listing it
  without the requirement would let a Stamp action fire on unsupported
  semantics. Both are forbidden, so every row carries its own gate.
- **Server-owned.** The catalog is data in this module. A client may render it
  and must not define, extend or reinterpret it.

Scope: this is a *catalog of stampable templates*, not an inventory of
instantiated agents, and not a network design. It deliberately carries no
topology, routing, VC or clock-rate semantics — those live in their own
canonical modules (``topology_intent``, ``router_behavior``, ``domain_intent``).

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, NoReturn

from veritx_dse.core.errors import SemanticError, UnsupportedSemantics
from veritx_dse.model.compile_model import AgentKind
from veritx_dse.model.agent_interface import InterfaceRole

SCHEMA_VERSION = 1

_TYPE_TAG = "srota/IpTemplate"

#: The one and only spelling for "we have no artifact-backed number".
NOT_PROVIDED = "NOT PROVIDED"


class IpCatalogError(ValueError, SemanticError):
    """A catalog entry cannot be represented as authored."""


class IpCategory(Enum):
    """Catalog grouping. Rendering-only: no design meaning."""

    COMPUTE = "compute"
    MEMORY = "memory"
    NETWORK = "network"
    BRIDGE = "bridge"
    SUPPORT = "support"


# --------------------------------------------------------------------------
# local typed helpers
#
# compile_model's ``_as_int``/``_as_str`` raise a bare ValueError, which would
# escape this module's typed boundary. Every refusal here therefore raises
# IpCatalogError, the way address_decode.py and sideband.py do it.
# --------------------------------------------------------------------------

def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise IpCatalogError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = sorted(set(d) - allowed)
    if unknown:
        raise IpCatalogError(
            f"{where} has unknown fields: {unknown} "
            f"(allowed: {sorted(allowed)})")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise IpCatalogError(f"{where} is missing required field {key!r}")
    return d[key]


def _as_str(name: str, value: Any, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise IpCatalogError(
            f"{name} must be a string, got {type(value).__name__}")
    if not allow_empty and not value:
        raise IpCatalogError(f"{name} must not be empty")
    return value


def _as_int(name: str, value: Any, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IpCatalogError(
            f"{name} must be an int, got {type(value).__name__}")
    if minimum is not None and value < minimum:
        raise IpCatalogError(f"{name} must be >= {minimum}, got {value}")
    return value


def _as_bool(name: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise IpCatalogError(
            f"{name} must be a bool, got {type(value).__name__}")
    return value


def _enum(name: str, enum_cls: type[Enum], value: Any) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if not isinstance(value, str):
        raise IpCatalogError(
            f"{name} must be a {enum_cls.__name__} value, got "
            f"{type(value).__name__}")
    try:
        return enum_cls(value)
    except ValueError:
        raise IpCatalogError(
            f"{name} {value!r} is not one of "
            f"{[m.value for m in enum_cls]}") from None


def _absent_number(name: str, value: Any) -> str | None:
    """Validate a physical figure that we usually do not have.

    Only ``None`` and the literal ``"NOT PROVIDED"`` are accepted. A number is
    refused with the reason it is refused: this repo has no PDK, no Liberty
    and no P&R artifact, so a numeric area or power in this catalog would be a
    fabricated claim dressed as data (program sections 27, 35, 80).
    """
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, (int, float)):
        raise IpCatalogError(
            f"{name} must not carry a numeric value: got {value!r}. This "
            f"catalog has no PDK, Liberty or place-and-route artifact behind "
            f"it, so an area/power estimate would be an invented figure. "
            f"Author {NOT_PROVIDED!r} or omit the field.")
    if value == NOT_PROVIDED:
        # Serialized spelling of "we have nothing"; in memory this is None.
        return None
    raise IpCatalogError(
        f"{name} must be {NOT_PROVIDED!r} or absent, got {value!r}")


@dataclass(frozen=True)
class IpTemplate:
    """One stampable IP primitive and the gaps that gate stamping it."""

    id: str
    version: str
    category: IpCategory
    agent_kind: AgentKind
    interface_role: InterfaceRole
    protocol: str
    data_width_bits: int
    address_width_bits: int
    requires_clock_domain: bool
    requires_power_domain: bool
    port_count: int
    capability_requirements: tuple[str, ...]
    provenance: str
    area_mm2: str | None = None
    power_w: str | None = None

    def __post_init__(self) -> None:
        _as_str("IpTemplate.id", self.id)
        if any(ch.isspace() for ch in self.id):
            raise IpCatalogError(
                f"IpTemplate.id {self.id!r} must not contain whitespace: ids "
                "are stable deep-link identities")
        _as_str("IpTemplate.version", self.version)
        _enum("IpTemplate.category", IpCategory, self.category)
        _enum("IpTemplate.agent_kind", AgentKind, self.agent_kind)
        _enum("IpTemplate.interface_role", InterfaceRole, self.interface_role)
        _as_str("IpTemplate.protocol", self.protocol)
        _as_int("IpTemplate.data_width_bits", self.data_width_bits, minimum=8)
        _as_int("IpTemplate.address_width_bits", self.address_width_bits,
                minimum=8)
        _as_bool("IpTemplate.requires_clock_domain",
                 self.requires_clock_domain)
        _as_bool("IpTemplate.requires_power_domain",
                 self.requires_power_domain)
        _as_int("IpTemplate.port_count", self.port_count, minimum=1)
        _as_str("IpTemplate.provenance", self.provenance)

        # Capability order is not design science: canonicalise it so two
        # spellings of the same requirement set are the same template.
        if isinstance(self.capability_requirements, list):
            object.__setattr__(self, "capability_requirements",
                               tuple(self.capability_requirements))
        if not isinstance(self.capability_requirements, tuple):
            raise IpCatalogError(
                "IpTemplate.capability_requirements must be a tuple of "
                f"strings, got {type(self.capability_requirements).__name__}")
        reqs: list[str] = []
        for item in self.capability_requirements:
            reqs.append(_as_str("capability requirement", item))
        if len(set(reqs)) != len(reqs):
            raise IpCatalogError(
                f"IpTemplate.capability_requirements has duplicates: {reqs}")
        object.__setattr__(self, "capability_requirements", tuple(sorted(reqs)))

        object.__setattr__(self, "area_mm2",
                           _absent_number("IpTemplate.area_mm2",
                                          self.area_mm2))
        object.__setattr__(self, "power_w",
                           _absent_number("IpTemplate.power_w",
                                          self.power_w))

    @property
    def stampable_now(self) -> bool:
        """False when a named capability still gates this primitive.

        This is a *catalog* verdict about requirements the server must still
        make READY. It is deliberately not a capability status: the registry
        in :mod:`veritx_dse.application.loom_capability` owns status.
        """
        return not self.capability_requirements

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "category": self.category.value,
            "agent_kind": self.agent_kind.value,
            "interface_role": self.interface_role.value,
            "protocol": self.protocol,
            "data_width_bits": self.data_width_bits,
            "address_width_bits": self.address_width_bits,
            "requires_clock_domain": self.requires_clock_domain,
            "requires_power_domain": self.requires_power_domain,
            "port_count": self.port_count,
            "capability_requirements": list(self.capability_requirements),
            "provenance": self.provenance,
            "area_mm2": self.area_mm2 if self.area_mm2 is not None
                        else NOT_PROVIDED,
            "power_w": self.power_w if self.power_w is not None
                       else NOT_PROVIDED,
        }

    @classmethod
    def from_dict(cls, d: Any) -> "IpTemplate":
        where = "IpTemplate"
        _strict_keys(d, frozenset({
            "id", "version", "category", "agent_kind", "interface_role",
            "protocol", "data_width_bits", "address_width_bits",
            "requires_clock_domain", "requires_power_domain", "port_count",
            "capability_requirements", "provenance", "area_mm2", "power_w",
        }), where)
        reqs = _need(d, "capability_requirements", where)
        if not isinstance(reqs, list):
            raise IpCatalogError(
                f"{where}.capability_requirements must be a list")
        return cls(
            id=_need(d, "id", where),
            version=_need(d, "version", where),
            category=_enum("category", IpCategory, _need(d, "category", where)),
            agent_kind=_enum("agent_kind", AgentKind,
                             _need(d, "agent_kind", where)),
            interface_role=_enum("interface_role", InterfaceRole,
                                 _need(d, "interface_role", where)),
            protocol=_need(d, "protocol", where),
            data_width_bits=_need(d, "data_width_bits", where),
            address_width_bits=_need(d, "address_width_bits", where),
            requires_clock_domain=_need(d, "requires_clock_domain", where),
            requires_power_domain=_need(d, "requires_power_domain", where),
            port_count=_need(d, "port_count", where),
            capability_requirements=tuple(reqs),
            provenance=_need(d, "provenance", where),
            area_mm2=d.get("area_mm2"),
            power_w=d.get("power_w"),
        )


_WIDTH_DEFAULT = (
    "width/address are compile_model.Agent defaults (256/64), declared "
    "defaults and not a property measured from any IP"
)
_KIND_NOTE = "veritx_dse/model/compile_model.py:AgentKind"


def _prov(kind_note: str, extra: str = "") -> str:
    parts = [f"agent_kind {_KIND_NOTE}: {kind_note}", _WIDTH_DEFAULT]
    if extra:
        parts.append(extra)
    return ". ".join(parts) + "."


#: The catalog. Server-owned: a client renders it and never extends it.
IP_CATALOG: tuple[IpTemplate, ...] = (
    IpTemplate(
        id="npu-tensor-core",
        version="1.0",
        category=IpCategory.COMPUTE,
        agent_kind=AgentKind.COMPUTE_TILE,
        interface_role=InterfaceRole.INITIATOR,
        protocol="AXI",
        data_width_bits=256,
        address_width_bits=64,
        requires_clock_domain=True,
        requires_power_domain=True,
        port_count=1,
        capability_requirements=("workload.compute_architecture",),
        provenance=_prov(
            "no NPU kind exists; COMPUTE_TILE is the nearest closed-set "
            "member",
            "gated because no compute-tile internal model exists "
            "(compute units, local memory, throughput), so a stamped NPU "
            "carries no execution semantics"),
    ),
    IpTemplate(
        id="vector-coprocessor",
        version="1.0",
        category=IpCategory.COMPUTE,
        agent_kind=AgentKind.COMPUTE_TILE,
        interface_role=InterfaceRole.INITIATOR,
        protocol="AXI",
        data_width_bits=256,
        address_width_bits=64,
        requires_clock_domain=True,
        requires_power_domain=True,
        port_count=1,
        capability_requirements=("workload.compute_architecture",),
        provenance=_prov(
            "no vector kind exists; COMPUTE_TILE is the nearest closed-set "
            "member",
            "gated on the same absent compute-architecture profile as the "
            "tensor core"),
    ),
    IpTemplate(
        id="streaming-dma-engine",
        version="1.0",
        category=IpCategory.MEMORY,
        agent_kind=AgentKind.PERIPHERAL,
        interface_role=InterfaceRole.BIDIRECTIONAL,
        protocol="AXI",
        data_width_bits=256,
        address_width_bits=64,
        requires_clock_domain=True,
        requires_power_domain=False,
        port_count=1,
        capability_requirements=(
            "transaction.outstanding",
            "transaction.splitting",
        ),
        provenance=_prov(
            "no DMA kind exists; PERIPHERAL is the nearest closed-set member",
            "BIDIRECTIONAL because a DMA both reads and writes; gated on the "
            "transaction policy it must obey, since a DMA whose outstanding "
            "and split rules cannot be authored would issue unbounded"),
    ),
    IpTemplate(
        id="telemetry-atb-trace-hub",
        version="1.0",
        category=IpCategory.SUPPORT,
        agent_kind=AgentKind.PERIPHERAL,
        interface_role=InterfaceRole.STREAM_SINK,
        protocol="AXI",
        data_width_bits=256,
        address_width_bits=64,
        requires_clock_domain=True,
        requires_power_domain=False,
        port_count=1,
        capability_requirements=("sideband.interface",),
        provenance=_prov(
            "no trace kind exists; PERIPHERAL is the nearest closed-set "
            "member",
            "STREAM_SINK: a trace hub consumes a unidirectional stream and "
            "performs no completion tracking, so no outstanding limit "
            "applies to it; gated because the trace sideband is not yet "
            "authorable through the product"),
    ),
    IpTemplate(
        id="csr-config-controller",
        version="1.0",
        category=IpCategory.SUPPORT,
        agent_kind=AgentKind.PERIPHERAL,
        interface_role=InterfaceRole.TARGET,
        protocol="AXI",
        data_width_bits=256,
        address_width_bits=64,
        requires_clock_domain=True,
        requires_power_domain=True,
        port_count=1,
        capability_requirements=(
            "fabric.multiplane",
            "sideband.connectivity",
        ),
        provenance=_prov(
            "no controller kind exists; PERIPHERAL is the nearest closed-set "
            "member",
            "TARGET because a config endpoint only receives writes; gated on "
            "the config plane, which cannot be a renamed copy of the data "
            "plane, and on sideband connectivity"),
    ),
    IpTemplate(
        id="cdc-async-fifo-bridge",
        version="1.0",
        category=IpCategory.BRIDGE,
        agent_kind=AgentKind.PERIPHERAL,
        interface_role=InterfaceRole.BIDIRECTIONAL,
        protocol="AXI",
        data_width_bits=256,
        address_width_bits=64,
        requires_clock_domain=True,
        requires_power_domain=True,
        port_count=2,
        capability_requirements=(
            "cdc.async_fifo",
            "cdc.crossing",
        ),
        provenance=_prov(
            "no bridge kind exists; PERIPHERAL is the nearest closed-set "
            "member",
            "port_count 2 is the source and destination side of one crossing; "
            "protocol is protocol-agnostic in reality and AXI here is only "
            "the compile_model.Agent default, not a claim about the bridge"),
    ),
    IpTemplate(
        id="pipeline-retiming-stage",
        version="1.0",
        category=IpCategory.SUPPORT,
        agent_kind=AgentKind.PERIPHERAL,
        interface_role=InterfaceRole.BIDIRECTIONAL,
        protocol="AXI",
        data_width_bits=256,
        address_width_bits=64,
        requires_clock_domain=True,
        requires_power_domain=False,
        port_count=2,
        capability_requirements=("generate.rtl",),
        provenance=_prov(
            "no pipeline kind exists; PERIPHERAL is the nearest closed-set "
            "member",
            "a retiming stage is a structural link element, not an endpoint, "
            "and it is gated on RTL generation because a stage with no emitter "
            "produces nothing a backend can consume"),
    ),
    IpTemplate(
        id="rcu-collective",
        version="1.0",
        category=IpCategory.COMPUTE,
        agent_kind=AgentKind.COMPUTE_TILE,
        interface_role=InterfaceRole.BIDIRECTIONAL,
        protocol="AXI",
        data_width_bits=256,
        address_width_bits=64,
        requires_clock_domain=True,
        requires_power_domain=False,
        port_count=1,
        capability_requirements=("router.rcu",),
        provenance=_prov(
            "no RCU kind exists; COMPUTE_TILE is the nearest closed-set "
            "member",
            "gated on router.rcu, which maps to capability-registry.yaml "
            "ROUTE-011 (RCU / in-network reduction, DECLARABLE "
            "= FUTURE_CONTRACT): rcu_enabled was REMOVED from v4 with no "
            "canonical consumed artifact, so no RCU realization exists"),
    ),
    IpTemplate(
        id="ucie-d2d-chiplet",
        version="1.0",
        category=IpCategory.BRIDGE,
        agent_kind=AgentKind.UCIE_PORT,
        interface_role=InterfaceRole.BIDIRECTIONAL,
        protocol="AXI",
        data_width_bits=256,
        address_width_bits=64,
        requires_clock_domain=True,
        requires_power_domain=True,
        port_count=1,
        capability_requirements=(
            "agent.interface",
            "cdc.crossing",
        ),
        provenance=_prov(
            "UCIE_PORT exists and is the direct match",
            "gated because a chiplet link needs an interface role and a "
            "crossing, and a width-conversion or SerDes model is absent; a "
            "UCIe port is not itself a SerDes and this row claims no PHY"),
    ),
    IpTemplate(
        id="concentrated-router",
        version="1.0",
        category=IpCategory.NETWORK,
        agent_kind=AgentKind.NIC,
        interface_role=InterfaceRole.BIDIRECTIONAL,
        protocol="AXI",
        data_width_bits=256,
        address_width_bits=64,
        requires_clock_domain=True,
        requires_power_domain=False,
        port_count=4,
        capability_requirements=(
            "router.concentration",
            "router.vc_allocation",
        ),
        provenance=_prov(
            "no router kind exists — a router is fabric structure, not an "
            "agent, so NIC is a placement stand-in only",
            "port_count 4 is the seat requirement at the canonical "
            "concentrated-mesh default concentration "
            "(compile_model.V3_CONCENTRATED_MESH_DEFAULT_CONCENTRATION), not "
            "a measured port count"),
    ),
    IpTemplate(
        id="hbm3e-memory",
        version="1.0",
        category=IpCategory.MEMORY,
        agent_kind=AgentKind.HBM_CONTROLLER,
        interface_role=InterfaceRole.TARGET,
        protocol="AXI",
        data_width_bits=256,
        address_width_bits=64,
        requires_clock_domain=True,
        requires_power_domain=True,
        port_count=1,
        capability_requirements=("address.decode",),
        provenance=_prov(
            "HBM_CONTROLLER exists and is the direct match",
            "gated on address decode: a memory target with no address window "
            "has nothing to be reached through"),
    ),
    IpTemplate(
        id="pcie-cxl-root",
        version="1.0",
        category=IpCategory.NETWORK,
        agent_kind=AgentKind.NIC,
        interface_role=InterfaceRole.INITIATOR,
        protocol="AXI",
        data_width_bits=256,
        address_width_bits=64,
        requires_clock_domain=True,
        requires_power_domain=True,
        port_count=1,
        capability_requirements=(
            "address.decode",
            "sideband.interface",
        ),
        provenance=_prov(
            "no PCIe or CXL kind exists; NIC is the nearest closed-set member",
            "INITIATOR because a root complex issues requests toward "
            "endpoints; gated on address windows for its outbound range and "
            "on the interrupt/error sidebands a root complex requires"),
    ),
)

_BY_ID: dict[str, IpTemplate] = {t.id: t for t in IP_CATALOG}
if len(_BY_ID) != len(IP_CATALOG):          # pragma: no cover - authoring bug
    raise IpCatalogError("IP_CATALOG contains duplicate template ids")


def get_ip_template(template_id: str) -> IpTemplate:
    """Look up one template by id.

    A missing id is a typed refusal rather than a ``KeyError`` so a bad stamp
    request becomes a product-visible reason instead of a 500.
    """
    _as_str("template_id", template_id)
    try:
        return _BY_ID[template_id]
    except KeyError:
        raise IpCatalogError(
            f"unknown IP catalog template {template_id!r} (known: "
            f"{sorted(_BY_ID)})") from None


def list_ip_templates(
    category: IpCategory | str | None = None,
) -> tuple[IpTemplate, ...]:
    """Every template, optionally narrowed to one category."""
    if category is None:
        return IP_CATALOG
    wanted = _enum("category", IpCategory, category)
    return tuple(t for t in IP_CATALOG if t.category is wanted)


def _resolve_template(template: str | IpTemplate) -> IpTemplate:
    """Accept a template id or an already-constructed template."""
    if isinstance(template, IpTemplate):
        return template
    if isinstance(template, str):
        return get_ip_template(template)
    raise IpCatalogError(
        "stamp_ip_template needs an IpTemplate or a template id string, got "
        f"{type(template).__name__}")


def stamp_ip_template(template: str | IpTemplate) -> NoReturn:
    """Attempt to stamp one catalog template into a design instance.

    This entry point REFUSES unconditionally and never returns. The catalog is
    AUTHORABLE data: no Stamp command, compiler instance materializer or
    backend consumer exists, so a stamped primitive would carry no semantics
    anywhere downstream. A template whose ``capability_requirements`` are not
    READY is refused first, naming the unmet requirement, so the missing
    capability is the visible reason rather than the generic absent
    materializer. An unknown template id is refused by :func:`get_ip_template`
    before either branch.
    """
    resolved = _resolve_template(template)
    if not resolved.stampable_now:
        unmet = ", ".join(resolved.capability_requirements)
        raise UnsupportedSemantics(
            f"IP template {resolved.id!r} cannot be stamped: capability "
            f"requirement(s) {unmet} are unmet. Owner stage = IP "
            "stamp/instance materializer; no compiler hook exists.")
    raise UnsupportedSemantics(
        f"IP template {resolved.id!r} cannot be stamped: no Stamp command, "
        "compiler instance materializer or backend consumer exists. Owner "
        "stage = IP stamp/instance materializer; no compiler hook exists.")


__all__ = [
    "SCHEMA_VERSION", "NOT_PROVIDED", "IpCatalogError", "IpCategory",
    "InterfaceRole", "IpTemplate", "IP_CATALOG", "get_ip_template",
    "list_ip_templates", "stamp_ip_template",
]
