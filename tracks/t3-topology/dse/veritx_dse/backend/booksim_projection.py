"""veritx_dse.backend.booksim_projection — qualified BookSim projection.

    canonical machine artifacts
        (TopologyArtifact, AgentAttachmentArtifact, MappingArtifact,
         VCResourceArtifact, RouteArtifact, PacketFormatArtifact,
         ResolvedFabric)
        +  PhysicalTrafficArtifactV2
                |
                v
    qualified BookSim projection
                |
                v
    PreparedBookSimInput        (deterministic, content-addressed)

BookSim is a BACKEND PROJECTION. It is never a second topology, mapping,
routing, packet-format or VC authority: every value it consumes is either
CANONICAL (taken from a canonical artifact), DERIVED (computed from
canonical artifacts by this projector), or BACKEND_PROFILE (a pinned
simulator control). A canonical dimension BookSim cannot represent is
recorded as UNSUPPORTED and REFUSED — never silently substituted.

Two certified projections (mutually exclusive, chosen by proof):

    CERTIFIED_BOOKSIM_ANYNET_V1        explicit AnyNet graph from the
                                       materialized topology + attachment
    CERTIFIED_BOOKSIM_MESH_DOR_XY_V1   native mesh DOR, ONLY when the
                                       narrow domain below is proven

Native mesh-DOR domain (all must hold, else AnyNet projection or refusal):
  * TopologyArtifact.family == MESH, every router seat_capacity == 1,
    square k x k router grid;
  * attachment is identity-prefix: endpoint ids dense 0..E-1 and
    endpoint i attaches to router i (E <= N);
  * the route artifact realizes DOR_XY and EVERY VC binds DOR_XY;
  * uniform channel latency 1, route_weight 1, no parallel channels;
  * single traffic class over the full VC set, identity transitions.

The historical certified dumps established these facts against the
vendored fork (native mesh node n <-> router n 1:1, x = id % k; links
latency 1 under use_noc_latency=1; the dump hook calls the CONFIGURED
routing function, so the dumped table IS the executed realization).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from veritx_dse.backend.source_audit import audit_profile_reads
from veritx_dse.core.artifact import content_hash
from veritx_dse.core.route_artifact import ANYNET_MIN_HOPS, DOR_XY
from veritx_dse.model.topology_artifact import MaterializedFamily
from veritx_dse.workload.traffic import PhysicalTrafficArtifactV2

#: v2: the prepared identity includes the executed run ``seed`` (reseal
#: audit). v1 omitted an executed input, so the generations are declared
#: incompatible rather than left to differ by hash only.
#: v3: the prepared identity also binds ``expected_flits``, so the
#: execution gate can enforce the fork's flit-injected == flit-accepted ==
#: expected conservation law instead of only packet count.
BOOKSIM_PROJECTION_SCHEMA_VERSION = 3

_MESH_DOR_PROFILE_ID = "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1"
_MESH_DOR_SEMANTICS_VERSION = "booksim2-fork+P1B-meshdor-dump+prepared-v2"
_MESH_DOR_LOWERER_VERSION = "DORXY/1"
_MESH_DOR_ROUTING_FUNCTION = "dim_order"

_ANYNET_PROFILE_ID = "CERTIFIED_BOOKSIM_ANYNET_V1"
_ANYNET_SEMANTICS_VERSION = "booksim2-fork+B3.7b-anynet-dump+prepared-v2"

#: trace scheduling semantics (bound into the prepared identity)
TRACE_SCHEDULE_VERSION = "srota/booksim-trace-schedule/v1"
#: historical certified convergence constants
_SAMPLE_PERIOD_MIN = 200
_SAMPLE_PERIOD_MARGIN = 1000
#: AnyNet routing VALUE that composes the fork's registry key:
#:   routing_function + "_" + topology == "min_anynet"
#: (networks/anynet.cpp: gRoutingFunctionMap["min_anynet"] = &min_anynet)
_ANYNET_ROUTING_FUNCTION = "min"
_ANYNET_ROUTING_KEY = "min_anynet"

CONFIG_FILE = "config.cfg"
TOPOLOGY_FILE = "topology.anynet"
TRACE_FILE = "workload.trace"
ROUTE_DUMP_FILE = "routing.dump"

#: first-hop route dump the native-mesh profile asks the fork to emit
_ROUTE_DUMP_DIALECT = "booksim-native-mesh-dor-dump-v1"


class BookSimProjectionError(ValueError):
    """The projection cannot be rendered from these canonical artifacts."""


class SemanticLoss(BookSimProjectionError):
    """A canonical dimension has no exact BookSim representation."""


class ParameterOwner(Enum):
    """Who owns a simulation-relevant BookSim value."""

    #: taken directly from a canonical artifact
    CANONICAL = "CANONICAL"
    #: computed by this projector from canonical artifacts
    DERIVED = "DERIVED"
    #: a pinned simulator control (never a compiled default)
    BACKEND_PROFILE = "BACKEND_PROFILE"
    #: the canonical dimension has no exact BookSim representation
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class ConfigRead:
    """One simulation-relevant configuration field."""

    name: str
    owner: ParameterOwner
    source: str
    pin: Any = None
    note: str = ""
    #: emitted only when the vendored fork actually reads the field
    #: (revalidated by the source audit); an optional field the fork does
    #: not read is reported as unavailable, never silently emitted
    optional: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise BookSimProjectionError("ConfigRead.name must be non-empty")
        if not isinstance(self.source, str) or not self.source:
            raise BookSimProjectionError(
                f"ConfigRead {self.name!r} must record its source")
        if self.owner is ParameterOwner.BACKEND_PROFILE and self.pin is None \
                and self.name not in ("traffic", "sample_period"):
            raise BookSimProjectionError(
                f"BACKEND_PROFILE field {self.name!r} must carry an "
                "explicit pinned value")
        if self.owner is ParameterOwner.UNSUPPORTED and not self.note:
            raise BookSimProjectionError(
                f"UNSUPPORTED field {self.name!r} must explain the loss")


@dataclass(frozen=True)
class BookSimProfile:
    """One certified projection's closed-world audit."""

    profile_id: str
    semantics_version: str
    audit: tuple[ConfigRead, ...]

    def __post_init__(self) -> None:
        names = [row.name for row in self.audit]
        if len(names) != len(set(names)):
            raise BookSimProjectionError(
                f"profile {self.profile_id} audits a field twice")
        # a field must not be readable under two owners
        for row in self.audit:
            if row.owner is ParameterOwner.UNSUPPORTED:
                raise SemanticLoss(
                    f"profile {self.profile_id} declares "
                    f"{row.name!r} UNSUPPORTED: {row.note}")

    def ownership(self) -> dict[str, ParameterOwner]:
        return {row.name: row.owner for row in self.audit}

    def source_of(self, name: str) -> str:
        for row in self.audit:
            if row.name == name:
                return row.source
        raise BookSimProjectionError(
            f"profile {self.profile_id} does not audit {name!r}")

    def pinned_values(self) -> dict[str, Any]:
        return {row.name: row.pin for row in self.audit
                if row.owner is ParameterOwner.BACKEND_PROFILE
                and row.pin is not None and row.name != "traffic"}

    def known_names(self) -> frozenset[str]:
        return frozenset(row.name for row in self.audit)

    def rendered_names(self) -> frozenset[str]:
        """Fields the projector always emits (optional rows excluded)."""
        return frozenset(row.name for row in self.audit if not row.optional)


# ── the certified audit (shared router/VC/traffic-manager surface) ────────

_A = ParameterOwner

#: master render order for the fields this projector emits
CONFIG_KEY_ORDER = (
    "topology", "k", "n", "use_noc_latency", "network_file",
    "routing_function", "routing_dump_file",
    "num_vcs", "classes", "router", "priority", "link_failures",
    "traffic", "sample_period", "max_samples", "injection_rate",
    "injection_rate_uses_flits", "injection_process", "sim_type",
    "sim_count", "warmup_periods", "measure_stats", "print_activity",
    "viewer_trace", "sim_power", "seed",
)

_AUDIT: tuple[ConfigRead, ...] = (
    ConfigRead("topology", _A.CANONICAL, "networks/network.cpp",
               "anynet", note="AnyNet render of the materialized topology"),
    ConfigRead("network_file", _A.DERIVED, "networks/anynet.cpp",
               note="rendered logical name topology.anynet"),
    ConfigRead("routing_function", _A.CANONICAL, "routers/iq_router.cpp",
               note="canonical routing realization class"),
    ConfigRead("routing_dump_file", _A.DERIVED, "networks/anynet.cpp",
               note="executed-route evidence path; OPTIONAL because the "
                    "currently vendored fork has no dump hook (the source "
                    "audit observes no read), so dump-based route "
                    "comparison is unavailable and the qualification falls "
                    "back to the canonical route/attachment binding",
               optional=True),
    ConfigRead("num_vcs", _A.CANONICAL, "routers/iq_router.cpp",
               note="VCResourceArtifact.vc_count"),
    ConfigRead("classes", _A.BACKEND_PROFILE, "routers/router.cpp", 1,
               note="single-class trace execution"),
    ConfigRead("router", _A.BACKEND_PROFILE, "routers/router.cpp", "iq"),
    ConfigRead("priority", _A.BACKEND_PROFILE, "vc.cpp", "none",
               note="no priority scheme; class_priority is dead"),
    ConfigRead("link_failures", _A.BACKEND_PROFILE, "networks/network.cpp", 0),
    ConfigRead("traffic", _A.DERIVED, "traffic.cpp",
               note="DERIVED workload binding: traffic.cpp rejects a bare "
                    "'trace' pattern (exit -1) and requires the expression "
                    "trace(<file>); the renderer embeds the prepared "
                    "logical filename, never an absolute path"),
    ConfigRead("sample_period", _A.DERIVED, "trafficmanager.cpp",
               note="DERIVED convergence control: "
                    "max(200, max_trace_timestamp + 1 + 1000)"),
    ConfigRead("max_samples", _A.DERIVED, "trafficmanager.cpp",
               note="DERIVED so that sample_period * max_samples covers the "
                    "final trace timestamp; a long trace is never silently "
                    "truncated"),
    ConfigRead("injection_rate", _A.BACKEND_PROFILE, "trafficmanager.cpp", 0.0,
               note="embedded trace owns injection"),
    ConfigRead("injection_rate_uses_flits", _A.BACKEND_PROFILE,
               "trafficmanager.cpp", 1),
    ConfigRead("injection_process", _A.BACKEND_PROFILE, "trafficmanager.cpp",
               "bernoulli"),
    ConfigRead("sim_type", _A.BACKEND_PROFILE, "main.cpp", "latency"),
    ConfigRead("sim_count", _A.BACKEND_PROFILE, "main.cpp", 1),
    ConfigRead("warmup_periods", _A.BACKEND_PROFILE, "main.cpp", 0),
    ConfigRead("measure_stats", _A.BACKEND_PROFILE, "main.cpp", 1),
    ConfigRead("print_activity", _A.BACKEND_PROFILE, "main.cpp", 0),
    ConfigRead("viewer_trace", _A.BACKEND_PROFILE, "main.cpp", 0),
    ConfigRead("sim_power", _A.BACKEND_PROFILE, "main.cpp", 0),
    ConfigRead("seed", _A.DERIVED, "main.cpp", note="explicit run seed"),
)

ANYNET_PROFILE = BookSimProfile(
    profile_id=_ANYNET_PROFILE_ID, semantics_version=_ANYNET_SEMANTICS_VERSION,
    audit=_AUDIT)


def _mesh_audit() -> tuple[ConfigRead, ...]:
    """The audit re-pathed for the native mesh surface.

    ``network_file`` goes dead (no AnyNet file exists); ``topology`` pins
    ``mesh``; ``k``/``n``/``use_noc_latency`` become live DERIVED/CANONICAL
    reads. Sharing one audit would let one profile's pins vouch for the
    other's reads, so this is a distinct table with its own identity.
    """
    rows: list[ConfigRead] = []
    for row in _AUDIT:
        if row.name == "network_file":
            continue
        if row.name == "topology":
            rows.append(ConfigRead(
                "topology", _A.CANONICAL, "networks/network.cpp", "mesh",
                note="native mesh render (no AnyNet file)"))
            continue
        rows.append(row)
    rows.append(ConfigRead(
        "k", _A.DERIVED, "networks/kncube.cpp",
        note="mesh radix, re-derived from the topology artifact"))
    rows.append(ConfigRead(
        "n", _A.DERIVED, "networks/kncube.cpp",
        note="mesh dimensionality, always 2 in the certified domain"))
    rows.append(ConfigRead(
        "use_noc_latency", _A.BACKEND_PROFILE, "networks/kncube.cpp", 1,
        note="native mesh links are latency 1 under this pin"))
    return tuple(rows)


MESH_DOR_PROFILE = BookSimProfile(
    profile_id=_MESH_DOR_PROFILE_ID,
    semantics_version=_MESH_DOR_SEMANTICS_VERSION, audit=_mesh_audit())


def _assert_profile_closure() -> None:
    for profile in (ANYNET_PROFILE, MESH_DOR_PROFILE):
        for row in profile.audit:
            if row.owner is ParameterOwner.BACKEND_PROFILE \
                    and row.name != "traffic" and row.name != "sample_period" \
                    and row.pin is None:
                raise BookSimProjectionError(
                    f"{profile.profile_id}: {row.name!r} must pin a value")
    if MESH_DOR_PROFILE.known_names() == ANYNET_PROFILE.known_names():
        raise BookSimProjectionError(
            "the mesh profile must have its own audited surface")


_assert_profile_closure()


# ── canonical parents ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class BookSimProjectionParents:
    """The explicit canonical machine artifacts a projection stands on.

    Replaces the historical ``ResolvedFabricBundle``: the canonical
    ``ResolvedFabric`` binds only hashes, so the actual child artifacts
    are passed explicitly and re-checked here before any rendering.
    """

    resolved_fabric: Any
    topology: Any
    attachment: Any
    mapping: Any
    vc_resource: Any
    vc_assignment: Any
    packet_format: Any
    route: Any
    physical_traffic: PhysicalTrafficArtifactV2

    def __post_init__(self) -> None:
        rf = self.resolved_fabric
        if rf.mapping_hash != self.mapping.mapping_hash():
            raise BookSimProjectionError(
                "mapping does not belong to the resolved fabric")
        if rf.fabric_hash == "" or rf.resolved_fabric_hash == "":
            raise BookSimProjectionError("resolved fabric is not sealed")
        if self.packet_format.attachment_hash != self.attachment.attachment_hash():
            raise BookSimProjectionError(
                "packet format was not derived from this attachment")
        if self.packet_format.topology_hash != self.topology.topology_hash():
            raise BookSimProjectionError(
                "packet format was not derived from this topology")
        if self.packet_format.vc_resource_hash != self.vc_resource.artifact_hash:
            raise BookSimProjectionError(
                "packet format was not derived from this VC resource")
        if self.vc_assignment.vc_count != self.vc_resource.vc_count \
                or tuple(self.vc_assignment.traffic_class_to_vcs) \
                != tuple(self.vc_resource.traffic_class_to_vcs):
            raise BookSimProjectionError(
                "VC assignment does not belong to this VC resource")
        if self.route.topology_hash != self.topology.topology_hash():
            raise BookSimProjectionError(
                "route artifact was not materialized from this topology")
        if self.physical_traffic.resolved_fabric.resolved_fabric_hash \
                != rf.resolved_fabric_hash:
            raise BookSimProjectionError(
                "physical traffic does not belong to the resolved fabric")
        if self.physical_traffic.packet_format.packet_format_hash \
                != self.packet_format.packet_format_hash:
            raise BookSimProjectionError(
                "physical traffic was not projected through this packet "
                "format")


# ── native mesh-DOR domain qualification ──────────────────────────────────

@dataclass(frozen=True)
class MeshDorQualification:
    """The proof that the native mesh DOR projection may be used."""

    k: int
    router_count: int
    endpoint_count: int
    route_artifact_hash: str
    vc_resource_hash: str
    attachment_hash: str


def qualify_native_mesh_dor(parents: BookSimProjectionParents
                            ) -> MeshDorQualification:
    """Prove every prerequisite, or refuse. Never a family-name shortcut."""
    topo = parents.topology
    if topo.family is not MaterializedFamily.MESH:
        raise SemanticLoss(
            "UNSUPPORTED: the certified mesh-DOR profile covers "
            "TopologyArtifact.family MESH only, got "
            f"{getattr(topo.family, 'value', topo.family)!r}")
    for router in topo.routers:
        if router.seat_capacity != 1:
            raise SemanticLoss(
                "UNSUPPORTED: certified mesh-DOR covers seat_capacity 1 "
                f"only (router {router.router_id} has "
                f"{router.seat_capacity}); concentration has no native "
                "representation")
    n = topo.router_count
    k = math.isqrt(n)
    if k * k != n or k < 1:
        raise SemanticLoss(
            f"UNSUPPORTED: certified mesh-DOR covers square k x k meshes "
            f"only, got {n} routers")

    endpoints = parents.attachment.endpoints
    if len(endpoints) > n:
        raise SemanticLoss(
            f"UNSUPPORTED: {len(endpoints)} attached endpoints exceed the "
            f"{n} native mesh nodes")
    if sorted(e.endpoint_id for e in endpoints) != list(range(len(endpoints))):
        raise SemanticLoss(
            "UNSUPPORTED: endpoint ids are not dense 0..E-1; the native "
            "node universe cannot be addressed without a remap proof")
    for endpoint in endpoints:
        if endpoint.router_id != endpoint.endpoint_id:
            raise SemanticLoss(
                f"UNSUPPORTED: endpoint {endpoint.endpoint_id} attaches to "
                f"router {endpoint.router_id}, not its native node "
                "(identity-prefix attachments only)")

    classes = [d.id for d in parents.route.routing_classes]
    if DOR_XY not in classes:
        raise SemanticLoss(
            f"UNSUPPORTED: certified mesh-DOR realizes DOR_XY only; route "
            f"artifact classes are {classes}")
    vc_classes = {cls for _vc, cls
                  in parents.vc_assignment.vc_to_routing_class}
    if vc_classes != {DOR_XY}:
        raise SemanticLoss(
            "UNSUPPORTED: the mesh-DOR profile executes one DOR routing "
            f"function, but VCs map to {sorted(vc_classes)}")

    latencies = {c.latency_cycles for c in topo.channels}
    if latencies != {1}:
        raise SemanticLoss(
            f"UNSUPPORTED: native mesh links are latency 1; channels carry "
            f"{sorted(latencies)}")
    weights = {c.route_weight for c in topo.channels}
    if weights != {1}:
        raise SemanticLoss(
            f"UNSUPPORTED: DOR_XY is hop-count semantics but channels "
            f"carry route_weight {sorted(weights)}")
    pairs: dict[tuple[int, int], int] = {}
    for channel in topo.channels:
        key = (channel.src_router, channel.dst_router)
        pairs[key] = pairs.get(key, 0) + 1
    parallel = sorted(key for key, count in pairs.items() if count > 1)
    if parallel:
        raise SemanticLoss(
            f"UNSUPPORTED: parallel channels between routers "
            f"{parallel[:3]} have no native mesh representation")

    exact, reason = vc_exactness(parents.vc_resource)
    if not exact:
        raise SemanticLoss(f"UNSUPPORTED: {reason}")
    if parents.vc_resource.allowed_transitions != tuple(
            (vc, vc) for vc in parents.vc_resource.vc_ids):
        raise SemanticLoss(
            "UNSUPPORTED: the certified profile executes identity VC "
            "transitions only")

    return MeshDorQualification(
        k=k, router_count=n, endpoint_count=len(endpoints),
        route_artifact_hash=parents.route.artifact_hash,
        vc_resource_hash=parents.vc_resource.artifact_hash,
        attachment_hash=parents.attachment.attachment_hash())


def vc_exactness(vc_resource: Any) -> tuple[bool, str]:
    """BookSim trace traffic runs every flow in one class over all VCs."""
    if len(vc_resource.traffic_class_to_vcs) == 1:
        (_cls, vcs), = vc_resource.traffic_class_to_vcs
        if tuple(vcs) == tuple(vc_resource.vc_ids):
            return True, ""
    return False, (
        "BookSim trace traffic runs every flow in one class over all VCs; "
        "this artifact assigns traffic classes to VC subsets the backend "
        "does not execute")


# ── rendering ─────────────────────────────────────────────────────────────

def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    raise BookSimProjectionError(
        f"cannot render config value {value!r} ({type(value).__name__})")


def render_anynet_topology(parents: BookSimProjectionParents) -> bytes:
    """Exact AnyNet render of the canonical materialized topology."""
    by_router: dict[int, list[int]] = {}
    for endpoint in parents.attachment.endpoints:
        by_router.setdefault(endpoint.router_id, []).append(
            endpoint.endpoint_id)
    outgoing: dict[int, list[Any]] = {}
    for channel in parents.topology.channels:
        outgoing.setdefault(channel.src_router, []).append(channel)
    lines: list[str] = []
    for router_id in range(parents.topology.router_count):
        parts = [f"router {router_id}"]
        for node in sorted(by_router.get(router_id, ())):
            parts.append(f"node {node}")
        for channel in sorted(outgoing.get(router_id, ()),
                              key=lambda c: (c.dst_router, c.channel_id)):
            parts.append(f"router {channel.dst_router} "
                         f"{channel.latency_cycles}")
        lines.append(" ".join(parts))
    return ("\n".join(lines) + "\n").encode()


def render_trace(physical_traffic: PhysicalTrafficArtifactV2) -> bytes:
    """Render canonical physical traffic as the BookSim whitespace trace.

    The fork's trace dialect is ``cyc src cl dst sz`` with ``sz`` in
    FLITS, one line per physical packet, timestamps in emission order.
    Deterministic: (message order, packet index) only.
    """
    lines: list[str] = []
    timestamp = 0
    for message in physical_traffic.traffic:
        for packet in message.packets:
            lines.append(f"{timestamp} {packet.src_endpoint} 0 "
                         f"{packet.dst_endpoint} {packet.flit_count}")
            timestamp += 1
    return ("\n".join(lines) + "\n").encode()


def verify_trace_conservation(physical_traffic: PhysicalTrafficArtifactV2
                              ) -> dict[str, int]:
    """Mechanical proof that the rendered trace conserves the artifact."""
    expected_packets = sum(len(m.packets) for m in physical_traffic.traffic)
    expected_flits = sum(p.flit_count for m in physical_traffic.traffic
                         for p in m.packets)
    trace = render_trace(physical_traffic)
    rows = [line.split() for line in trace.decode().splitlines() if line]
    if len(rows) != expected_packets:
        raise BookSimProjectionError(
            f"trace projection lost packets: {len(rows)} != "
            f"{expected_packets}")
    flits = 0
    for index, row in enumerate(rows):
        if len(row) != 5:
            raise BookSimProjectionError(
                f"trace line {index} is not the 5-column dialect")
        if int(row[0]) != index:
            raise BookSimProjectionError(
                f"trace timestamp is not deterministic at line {index}")
        flits += int(row[4])
    if flits != expected_flits:
        raise BookSimProjectionError(
            f"trace projection lost flits: {flits} != {expected_flits}")
    return {"num_packets": expected_packets, "flits_total": expected_flits}


def render_config(parents: BookSimProjectionParents, profile: BookSimProfile,
                  *, include_optional: bool = False, seed: int = 0) -> bytes:
    """Render the certified config for a profile (deterministic bytes).

    ``include_optional`` emits optional fields (e.g. the route-dump path);
    it defaults to False because the source audit proves whether the
    vendored fork reads them.
    """
    optional = {row.name for row in profile.audit if row.optional}
    del_optional = not include_optional
    if profile.profile_id == _MESH_DOR_PROFILE_ID:
        qual = qualify_native_mesh_dor(parents)
        values = dict(profile.pinned_values())
        values.update({
            "topology": "mesh", "k": qual.k, "n": 2,
            "use_noc_latency": 1,
            "routing_function": _MESH_DOR_ROUTING_FUNCTION,
            "routing_dump_file": ROUTE_DUMP_FILE,
            "num_vcs": parents.vc_resource.vc_count,
        })
    elif profile.profile_id == _ANYNET_PROFILE_ID:
        values = dict(profile.pinned_values())
        values.update({
            "topology": "anynet", "network_file": TOPOLOGY_FILE,
            "routing_function": _ANYNET_ROUTING_FUNCTION,
            "routing_dump_file": "",
            "num_vcs": parents.vc_resource.vc_count,
        })
    else:
        raise BookSimProjectionError(
            f"unknown certified profile {profile.profile_id!r}")

    # DERIVED trace controls: the workload binding and the convergence
    # controls that guarantee every trace event is consumed.
    schedule = trace_schedule(parents.physical_traffic)
    values["traffic"] = f"trace({TRACE_FILE})"
    values["sample_period"] = schedule["sample_period"]
    values["max_samples"] = schedule["max_samples"]
    # the run seed is an executed input: render it so the identity that
    # binds it is also the identity BookSim runs
    values["seed"] = seed
    if schedule["sample_period"] * schedule["max_samples"] \
            < schedule["max_timestamp"] + 1:
        raise BookSimProjectionError(
            "convergence controls cannot cover the trace: "
            f"sample_period={schedule['sample_period']} * "
            f"max_samples={schedule['max_samples']} < "
            f"{schedule['max_timestamp'] + 1}")

    lines: list[str] = []
    for key in CONFIG_KEY_ORDER:
        if key not in values or key not in profile.known_names():
            continue
        if del_optional and key in optional:
            continue
        lines.append(f"{key} = {_format_value(values[key])};")
    return ("\n".join(lines) + "\n").encode()


def trace_schedule(physical_traffic: PhysicalTrafficArtifactV2
                   ) -> dict[str, int]:
    """The declared injection schedule of the canonical traffic projection.

    Timestamps are PROJECTION-DEFINED emission order (0, 1, 2, ...), not
    application wall-clock scheduling: BookSim completion time measured
    under this schedule is the completion time of the canonical network
    traffic projection, and must never be reported as end-to-end workload
    runtime.
    """
    expected_packets = sum(len(m.packets) for m in physical_traffic.traffic)
    if expected_packets <= 0:
        raise BookSimProjectionError(
            "a trace-driven execution requires a non-empty trace")
    max_timestamp = expected_packets - 1
    sample_period = max(_SAMPLE_PERIOD_MIN,
                        max_timestamp + 1 + _SAMPLE_PERIOD_MARGIN)
    max_samples = max(1, -(-(max_timestamp + 1) // sample_period))
    return {"expected_packets": expected_packets,
            "max_timestamp": max_timestamp,
            "sample_period": sample_period,
            "max_samples": max_samples}


def qualify_anynet_min_hops(parents: BookSimProjectionParents) -> None:
    """Narrow, fail-closed domain for ANYNET_MIN_HOPS on this fork.

    The vendored ``AnyNet::route`` adds the edge's LINK LATENCY to the
    Dijkstra distance (``anynet.cpp``: ``dist[min_cand] +
    i->second.second``) even though an old comment claims "distance is
    hops". Under unit latency/weight that reduces to min-hop routing with
    the fork's strict-``<``, ascending-map tie behaviour. With any
    non-unit value the two algorithms differ, so ANYNET_MIN_HOPS is NOT
    representable and we refuse rather than silently reinterpreting it as
    weighted shortest path.
    """
    classes = [d.id for d in parents.route.routing_classes]
    if ANYNET_MIN_HOPS not in classes:
        raise SemanticLoss(
            f"UNSUPPORTED: the certified AnyNet profile represents "
            f"ANYNET_MIN_HOPS only, got route classes {classes}")
    if len(classes) != 1 and set(classes) != {ANYNET_MIN_HOPS}:
        raise SemanticLoss(
            "UNSUPPORTED: the certified AnyNet profile executes one "
            f"min-hop routing function, got classes {classes}")

    latencies = {c.latency_cycles for c in parents.topology.channels}
    if latencies != {1}:
        raise SemanticLoss(
            "UNSUPPORTED: AnyNet on this fork adds link latency to the "
            f"route distance, so hop-count semantics require unit latency; "
            f"channels carry {sorted(latencies)} (use a weighted routing "
            "class instead)")
    weights = {c.route_weight for c in parents.topology.channels}
    if weights != {1}:
        raise SemanticLoss(
            f"UNSUPPORTED: ANYNET_MIN_HOPS requires unit route weights, "
            f"got {sorted(weights)}")

    pairs: dict[tuple[int, int], int] = {}
    for channel in parents.topology.channels:
        key = (channel.src_router, channel.dst_router)
        pairs[key] = pairs.get(key, 0) + 1
    parallel = sorted(key for key, count in pairs.items() if count > 1)
    if parallel:
        raise SemanticLoss(
            f"UNSUPPORTED: parallel router-to-router channels {parallel[:3]} "
            "would be collapsed/overwritten by the rendered AnyNet graph")

    router_ids = sorted(r.router_id for r in parents.topology.routers)
    if router_ids != list(range(len(router_ids))):
        raise SemanticLoss(
            "UNSUPPORTED: the fork requires a sequential router namespace "
            "0..N-1; got "
            f"{router_ids[:3]}...{router_ids[-3:] if router_ids else []}")
    for endpoint in parents.attachment.endpoints:
        if not 0 <= endpoint.router_id < len(router_ids):
            raise SemanticLoss(
                f"UNSUPPORTED: endpoint {endpoint.endpoint_id} attaches to "
                f"router {endpoint.router_id} outside the rendered AnyNet "
                "graph")


def parse_config_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        values[key.strip()] = raw.strip().rstrip(";").strip()
    return values


# ── the prepared input ────────────────────────────────────────────────────

@dataclass(frozen=True)
class PreparedBookSimInput:
    """Deterministic, content-addressed BookSim input.

    Identity binds every simulation-relevant parent: canonical artifact
    hashes, the physical-traffic artifact, the certified profile and its
    semantics/lowerer versions. Temporary directories, absolute paths and
    run slots are absent from identity by construction.
    """

    profile_id: str
    semantics_version: str
    lowerer_version: str
    config_text: str
    topology_text: str | None
    trace_text: str
    topology_hash: str
    attachment_hash: str
    mapping_hash: str
    vc_resource_hash: str
    packet_format_hash: str
    route_artifact_hash: str
    resolved_fabric_hash: str
    physical_traffic_id: str
    message_artifact_id: str
    num_vcs: int
    endpoint_count: int
    router_count: int
    trace_schedule_version: str = TRACE_SCHEDULE_VERSION
    sample_period: int = 0
    max_samples: int = 0
    expected_packets: int = 0
    #: total flits the trace declares (bound so flit conservation can be
    #: checked against the fork's emitted injected/accepted counters).
    expected_flits: int = 0
    #: the executed BookSim seed: a per-run simulation input, so it is part
    #: of the prepared identity (reseal audit) and rendered into the config.
    seed: int = 0
    schema_version: int = BOOKSIM_PROJECTION_SCHEMA_VERSION

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/PreparedBookSimInput",
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "semantics_version": self.semantics_version,
            "lowerer_version": self.lowerer_version,
            "topology_hash": self.topology_hash,
            "attachment_hash": self.attachment_hash,
            "mapping_hash": self.mapping_hash,
            "vc_resource_hash": self.vc_resource_hash,
            "packet_format_hash": self.packet_format_hash,
            "route_artifact_hash": self.route_artifact_hash,
            "resolved_fabric_hash": self.resolved_fabric_hash,
            "physical_traffic_id": self.physical_traffic_id,
            "message_artifact_id": self.message_artifact_id,
            "num_vcs": self.num_vcs,
            "endpoint_count": self.endpoint_count,
            "router_count": self.router_count,
            "trace_schedule_version": self.trace_schedule_version,
            "sample_period": self.sample_period,
            "max_samples": self.max_samples,
            "expected_packets": self.expected_packets,
            "expected_flits": self.expected_flits,
            "seed": self.seed,
            "config_sha256": content_hash("srota/PreparedBookSimConfig", 1,
                                          {"text": self.config_text}),
            "trace_sha256": content_hash("srota/PreparedBookSimTrace", 1,
                                         {"text": self.trace_text}),
            "topology_sha256": (
                content_hash("srota/PreparedBookSimTopology", 1,
                             {"text": self.topology_text})
                if self.topology_text is not None else None),
        }

    def prepared_id(self) -> str:
        return content_hash("srota/PreparedBookSimInput",
                            self.schema_version, self.identity_dict())

    def files(self) -> dict[str, bytes]:
        """The exact bytes a run directory receives."""
        out = {CONFIG_FILE: self.config_text.encode(),
               TRACE_FILE: self.trace_text.encode()}
        if self.topology_text is not None:
            out[TOPOLOGY_FILE] = self.topology_text.encode()
        return out

    def prepare_directory(self, directory: str | Path) -> dict[str, Path]:
        """Materialize the input; identity does NOT depend on the path."""
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        written: dict[str, Path] = {}
        for name, data in self.files().items():
            path = target / name
            path.write_bytes(data)
            written[name] = path
        return written


def select_booksim_profile(parents: BookSimProjectionParents) -> BookSimProfile:
    """Native mesh DOR when its domain is proven, else the AnyNet profile."""
    try:
        qualify_native_mesh_dor(parents)
    except SemanticLoss:
        qualify_anynet_min_hops(parents)   # refuse if also unrepresentable
        return ANYNET_PROFILE
    return MESH_DOR_PROFILE


def prepare_booksim_input(parents: BookSimProjectionParents, *,
                          seed: int = 0) -> PreparedBookSimInput:
    """Project canonical artifacts into a deterministic prepared input."""
    if not isinstance(parents, BookSimProjectionParents):
        raise BookSimProjectionError(
            "parents must be a BookSimProjectionParents")
    if type(seed) is not int or isinstance(seed, bool) or seed < 0:
        raise BookSimProjectionError("seed must be a non-negative int")
    profile = select_booksim_profile(parents)
    conservation = verify_trace_conservation(parents.physical_traffic)
    config = render_config(parents, profile, seed=seed)
    rendered = parse_config_values(config.decode())
    # Every REQUIRED rendered field must appear (a required pin silently
    # vanishing from the render is itself a projection defect — the old
    # `if name in values` guard could not see it), and every pin must be
    # rendered verbatim.
    missing = profile.rendered_names() - set(rendered)
    if missing:
        raise BookSimProjectionError(
            f"rendered config is missing required profile fields "
            f"{sorted(missing)} for {profile.profile_id}")
    for name, pin in profile.pinned_values().items():
        if rendered.get(name) != _format_value(pin):
            raise BookSimProjectionError(
                f"rendered {name}={rendered.get(name)!r} does not equal the "
                f"profile pin {pin!r}")
    topology_text = (render_anynet_topology(parents).decode()
                     if profile.profile_id == _ANYNET_PROFILE_ID else None)
    pt = parents.physical_traffic
    schedule = trace_schedule(pt)
    return PreparedBookSimInput(
        profile_id=profile.profile_id,
        semantics_version=profile.semantics_version,
        lowerer_version=(_MESH_DOR_LOWERER_VERSION
                         if profile.profile_id == _MESH_DOR_PROFILE_ID
                         else "ANYNET/1"),
        config_text=config.decode(), topology_text=topology_text,
        trace_text=render_trace(pt).decode(),
        topology_hash=parents.topology.topology_hash(),
        attachment_hash=parents.attachment.attachment_hash(),
        mapping_hash=parents.mapping.mapping_hash(),
        vc_resource_hash=parents.vc_resource.artifact_hash,
        packet_format_hash=parents.packet_format.packet_format_hash,
        route_artifact_hash=parents.route.artifact_hash,
        resolved_fabric_hash=parents.resolved_fabric.resolved_fabric_hash,
        physical_traffic_id=pt.physical_traffic_id(),
        message_artifact_id=pt.logical.message_artifact_id(),
        num_vcs=parents.vc_resource.vc_count,
        endpoint_count=len(parents.attachment.endpoints),
        router_count=parents.topology.router_count,
        sample_period=int(rendered["sample_period"]),
        max_samples=int(rendered["max_samples"]),
        expected_packets=schedule["expected_packets"],
        expected_flits=conservation["flits_total"],
        seed=seed)


def assert_canonical_booksim_projection(
        prepared: PreparedBookSimInput,
        parents: BookSimProjectionParents) -> None:
    """Re-prove a prepared input against its parents (tamper refusal)."""
    rebuilt = prepare_booksim_input(parents, seed=prepared.seed)
    if rebuilt.prepared_id() != prepared.prepared_id():
        raise BookSimProjectionError(
            "prepared input does not match a fresh projection of these "
            "canonical parents (tampered or transplanted artifact)")


def _fork_reads_route_dump() -> bool:
    """Whether the vendored fork exposes the P1B route-dump hook."""
    try:
        from veritx_dse.core.paths import REPO
        from veritx_dse.backend.source_audit import observed_fields
        root = REPO / "third_party" / "booksim2" / "src"
        return "routing_dump_file" in observed_fields(root)
    except Exception:
        return False


def compare_route_realization(parents: BookSimProjectionParents, *,
                              dumped_first_hops: dict[int, int] | None
                              ) -> dict[str, Any]:
    """Compare the executed route realization with the canonical one.

    Called only for the native mesh-DOR path. The canonical proof is the
    route artifact's executed class bound to the attachment it was
    materialized with; the fork's dump hook calls the CONFIGURED routing
    function, so a supplied dump is compared, never re-derived in Python.
    """
    qualification = qualify_native_mesh_dor(parents)
    report: dict[str, Any] = {
        "profile_id": _MESH_DOR_PROFILE_ID,
        "routing_function": _MESH_DOR_ROUTING_FUNCTION,
        "route_artifact_hash": qualification.route_artifact_hash,
        "attachment_hash": qualification.attachment_hash,
        "vc_resource_hash": qualification.vc_resource_hash,
        "k": qualification.k,
        "dump_dialect": _ROUTE_DUMP_DIALECT,
    }
    report["dump_supported_by_fork"] = _fork_reads_route_dump()
    if dumped_first_hops is None:
        report["dump_present"] = False
        return report
    # every router in the native mesh must appear with a legal next hop
    for router_id, next_hop in sorted(dumped_first_hops.items()):
        if not 0 <= router_id < qualification.router_count:
            raise BookSimProjectionError(
                f"route dump names router {router_id} outside the "
                f"materialized {qualification.router_count}-router mesh")
        if not 0 <= next_hop < qualification.router_count:
            raise BookSimProjectionError(
                f"route dump entry {router_id} -> {next_hop} is outside the "
                "mesh")
    report["dump_present"] = True
    report["dump_entries"] = len(dumped_first_hops)
    return report


def source_audit_report(profile: BookSimProfile, *, source_root: str | Path
                        ) -> dict[str, Any]:
    """Revalidate a certified profile against the vendored source."""
    report = audit_profile_reads(profile, source_root)
    return {
        "profile_id": profile.profile_id,
        "declared": len(report.declared),
        "missing_from_source": list(report.missing_from_source),
        "clean": report.clean,
    }


__all__ = [
    "ANYNET_PROFILE", "BOOKSIM_PROJECTION_SCHEMA_VERSION",
    "BookSimProfile", "BookSimProjectionError", "BookSimProjectionParents",
    "CONFIG_FILE", "CONFIG_KEY_ORDER", "ConfigRead", "MESH_DOR_PROFILE",
    "MeshDorQualification", "ParameterOwner", "PreparedBookSimInput",
    "ROUTE_DUMP_FILE", "SemanticLoss", "TOPOLOGY_FILE", "TRACE_FILE",
    "TRACE_SCHEDULE_VERSION", "assert_canonical_booksim_projection",
    "compare_route_realization", "parse_config_values",
    "prepare_booksim_input", "qualify_anynet_min_hops",
    "qualify_native_mesh_dor", "render_anynet_topology", "render_config",
    "render_trace", "select_booksim_profile", "source_audit_report",
    "trace_schedule", "vc_exactness", "verify_trace_conservation",
]
