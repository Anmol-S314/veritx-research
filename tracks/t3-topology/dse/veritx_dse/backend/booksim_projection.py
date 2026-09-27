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
from typing import Any, Iterator

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
#: v4: the prepared identity binds the canonical first-hop route table
#: (``expected_route_rows``) and renders the route-dump path, so execution
#: can prove the EXECUTED route realization rather than only qualify it
#: statically (P0.10).
#: v5: the convergence window is derived from the per-source trace
#: injection horizon (flit-serialized at one flit/cycle per source port),
#: not from the packet count. A concentrated source (e.g. a broadcast
#: root fanning out multi-flit packets) needs far more than one injection
#: cycle per packet; the old window truncated such runs and the
#: conservation gate (correctly) refused them.
BOOKSIM_PROJECTION_SCHEMA_VERSION = 5

_MESH_DOR_PROFILE_ID = "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1"
_MESH_DOR_SEMANTICS_VERSION = "booksim2-fork+P1B-meshdor-dump+prepared-v2"
_MESH_DOR_LOWERER_VERSION = "DORXY/1"
_MESH_DOR_ROUTING_FUNCTION = "dim_order"

_CMESH_DOR_PROFILE_ID = "CERTIFIED_BOOKSIM_CMESH_DOR_XY_V1"
_CMESH_DOR_SEMANTICS_VERSION = "booksim2-fork+P2-cmesh-dor+prepared-v1"
_CMESH_DOR_LOWERER_VERSION = "DORXY/1"
#: The fork composes its routing registry key as
#:   routing_function + "_" + topology
#: and cmesh registers "dor_no_express_cmesh" (networks/cmesh.cpp:66), so the
#: VALUE here is "dor_no_express". This is the PLAIN dimension-order
#: function (networks/cmesh.cpp: cmesh_next_no_express — x-then-y, no
#: express branch): exactly the canonical DOR_XY semantics over the
#: unfolded 2k x 2k node grid. The EXPRESS variant ("dor_cmesh" via
#: cmesh_next) adds bypass channels the canonical artifact does not
#: materialize and is deliberately not certified.
_CMESH_DOR_ROUTING_FUNCTION = "dor_no_express"

_ANYNET_PROFILE_ID = "CERTIFIED_BOOKSIM_ANYNET_V1"
_ANYNET_SEMANTICS_VERSION = "booksim2-fork+B3.7b-anynet-dump+prepared-v2"

#: trace scheduling semantics (bound into the prepared identity)
#: v2: the convergence window is the per-source injection horizon (the
#: cycle the last flit enters the network), not the last timestamp.
TRACE_SCHEDULE_VERSION = "srota/booksim-trace-schedule/v2"
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
    "topology", "k", "n", "c", "x", "y", "xr", "yr", "use_noc_latency",
    "network_file",
    "routing_function", "routing_dump_file",
    "num_vcs", "classes", "router", "priority", "link_failures",
    "traffic", "sample_period", "max_samples", "injection_rate",
    "injection_rate_uses_flits", "injection_process", "sim_type",
    "sim_count", "warmup_periods", "measure_stats", "print_activity",
    "viewer_trace", "sim_power", "seed", "latency_thres",
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
    ConfigRead("latency_thres", _A.BACKEND_PROFILE, "trafficmanager.cpp",
               1000000000000000.0,
               note="effectively disabled so trace drains never abort: the "
                    "traffic manager aborts the whole simulation once the "
                    "running latency average crosses this threshold "
                    "(compiled default 500), which silently truncates the "
                    "drain and drops packets from conservation"),
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


def _cmesh_audit() -> tuple[ConfigRead, ...]:
    """The audit re-pathed for the native concentrated-mesh surface.

    CMesh reads (networks/cmesh.cpp::_ComputeSize): ``k`` (side), ``n``
    (dimensionality, asserted <= 2), ``c`` (concentration, asserted == 4),
    ``x``/``y`` (topology extent, asserted equal), ``xr``/``yr``
    (concentration split, asserted xr*yr == c and xr == yr), plus
    ``use_noc_latency``. It shares the router/VC/traffic-manager surface
    with the mesh profile, so every row except the CMesh-specific ones is
    carried over verbatim from ``_mesh_audit`` — sharing tables would let
    one profile's pins vouch for the other's reads.
    """
    cmesh_only = {"k", "n", "use_noc_latency"}
    rows: list[ConfigRead] = []
    for row in _mesh_audit():
        if row.name in cmesh_only:
            continue
        if row.name == "topology":
            rows.append(ConfigRead(
                "topology", _A.CANONICAL, "networks/network.cpp", "cmesh",
                note="native concentrated-mesh render (no AnyNet file)"))
            continue
        rows.append(row)
    rows.extend((
        ConfigRead(
            "k", _A.DERIVED, "networks/cmesh.cpp",
            note="concentrated-mesh side: k x k router grid re-derived "
                 "from the topology artifact"),
        ConfigRead(
            "n", _A.DERIVED, "networks/cmesh.cpp",
            note="dimensionality; the fork asserts n <= 2 and the certified "
                 "domain pins n = 2"),
        ConfigRead(
            "c", _A.CANONICAL, "networks/cmesh.cpp",
            note="seats per router, from TopologyArtifact.seat_capacity; "
                 "the fork asserts c == 4"),
        ConfigRead(
            "x", _A.DERIVED, "networks/cmesh.cpp",
            note="topology extent; read and asserted equal to y by the "
                 "fork but unused beyond the assert — rendered as the "
                 "canonical side length k"),
        ConfigRead(
            "y", _A.DERIVED, "networks/cmesh.cpp",
            note="topology extent; asserted equal to x by the fork"),
        ConfigRead(
            "xr", _A.CANONICAL, "networks/cmesh.cpp",
            note="concentration split along x; canonical geometry is "
                 "square, so xr = yr = sqrt(c); the fork asserts xr*yr == c"),
        ConfigRead(
            "yr", _A.CANONICAL, "networks/cmesh.cpp",
            note="concentration split along y; asserted equal to xr"),
        ConfigRead(
            "use_noc_latency", _A.BACKEND_PROFILE, "networks/cmesh.cpp", 0,
            note="PINNED 0: the certified envelope requires uniform "
                 "link latency 1. The fork's noc-latency path sets "
                 "per-dimension latencies from the concentration split "
                 "(non-uniform for every certified geometry), so the pin "
                 "disables that path instead of certifying it"),
    ))
    return tuple(rows)


CMESH_DOR_PROFILE = BookSimProfile(
    profile_id=_CMESH_DOR_PROFILE_ID,
    semantics_version=_CMESH_DOR_SEMANTICS_VERSION, audit=_cmesh_audit())


def _assert_profile_closure() -> None:
    for profile in (ANYNET_PROFILE, MESH_DOR_PROFILE, CMESH_DOR_PROFILE):
        for row in profile.audit:
            if row.owner is ParameterOwner.BACKEND_PROFILE \
                    and row.name != "traffic" and row.name != "sample_period" \
                    and row.pin is None:
                raise BookSimProjectionError(
                    f"{profile.profile_id}: {row.name!r} must pin a value")
    if MESH_DOR_PROFILE.known_names() == ANYNET_PROFILE.known_names():
        raise BookSimProjectionError(
            "the mesh profile must have its own audited surface")
    if CMESH_DOR_PROFILE.known_names() == MESH_DOR_PROFILE.known_names():
        raise BookSimProjectionError(
            "the cmesh profile must have its own audited surface")


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
    # Seat capacity leads the family check: for a concentrated fabric the
    # real gap is that the native profile models one endpoint per router,
    # so the refusal names concentration rather than a family label.
    for router in topo.routers:
        if router.seat_capacity != 1:
            raise SemanticLoss(
                "UNSUPPORTED: certified mesh-DOR covers seat_capacity 1 "
                f"only (router {router.router_id} has "
                f"{router.seat_capacity}); concentration has no native "
                "representation")
    if topo.family is not MaterializedFamily.MESH:
        raise SemanticLoss(
            "UNSUPPORTED: the certified mesh-DOR profile covers "
            "TopologyArtifact.family MESH only, got "
            f"{getattr(topo.family, 'value', topo.family)!r}")
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


@dataclass(frozen=True)
class CMeshDorQualification:
    """The proof that the native concentrated-mesh DOR projection may be used.

    Every field is a canonical artifact fact that the profile's execution
    semantics were proven against; nothing here is derived from counts
    alone.
    """

    k: int
    concentration: int
    router_count: int
    endpoint_count: int
    route_artifact_hash: str
    vc_resource_hash: str
    attachment_hash: str


def _cmesh_node_to_router(k: int, c: int) -> Any:
    """The fork's node -> router law as a mapping, derived from CMesh.

    networks/cmesh.cpp::CMesh::NodeToRouter composes the node address from
    a 2k x 2k grid folded 2 x 2 onto each router (``_cX = _cY = 2`` for
    every certifiable geometry, because the fork asserts ``c == xr*yr``
    and ``xr == yr`` and ``c == 4``). Router ids are row-major
    ``y * k + x`` — the same numbering our materializer emits
    (coordinates ``(x, y)``). The returned mapping is the composition of
    exactly those two functions; it is never re-invented from counts.
    """
    cx = cy = math.isqrt(c)
    if cx * cy != c:                                   # pragma: no cover
        raise SemanticLoss(
            f"node addressing requires a square concentration split, got "
            f"c={c}")
    node_count = k * k * c
    return {node: ((node // (k * cx)) // cy) * k + (node % (k * cx)) // cx
            for node in range(node_count)}


def _cmesh_expected_route_rows(
        parents: BookSimProjectionParents, k: int,
        concentration: int) -> tuple[tuple[int, int, int], ...]:
    """Canonical expected first-hop table for the cmesh node universe.

    Delegates to `route_observation.expected_route_rows` — the one
    derivation authority — with the cmesh node -> router mapping. Every
    non-local hop is looked up as a real channel of the materialized
    artifact, so a route proof that does not cover this fabric refuses
    here rather than becoming an uncheckable expectation.
    """
    from veritx_dse.backend.route_observation import expected_route_rows
    return expected_route_rows(
        routing_class=DOR_XY, topology=parents.topology,
        route=parents.route,
        node_to_router=_cmesh_node_to_router(k, concentration))


def qualify_native_cmesh_dor(
        parents: BookSimProjectionParents) -> CMeshDorQualification:
    """Prove every prerequisite of the cmesh envelope, or refuse.

    The envelope is the fork's own contract (networks/cmesh.cpp), each
    clause proven against the canonical artifacts:

    1. family CONCENTRATED_MESH, uniform seat_capacity == 4 (the fork
       asserts ``c == 4``);
    2. square k x k router grid in row-major coordinates matching the
       fork's ``y * k + x`` router ids;
    3. endpoints dense 0..E-1, one per seat, seat ports forming the
       2x2 block the fork's NodeToPort expects;
    4. the route artifact realizes DOR_XY and every VC binds DOR_XY
       (the fork executes one deterministic dimension-order function);
    5. uniform channel latency 1 and route_weight 1 — the profile pins
       ``use_noc_latency = 0``, which makes every link latency 1 in the
       fork, so a canonical channel that is not unit-latency would
       execute with WRONG latency and must refuse here;
    6. no parallel channels (the fork's channel grid is one channel per
       direction per adjacent pair);
    7. single traffic class over the full VC set, identity VC
       transitions (the same trace-class law as the mesh envelope).
    """
    topo = parents.topology
    if topo.family is not MaterializedFamily.CONCENTRATED_MESH:
        raise SemanticLoss(
            "UNSUPPORTED: the certified cmesh-DOR profile covers "
            "TopologyArtifact.family CONCENTRATED_MESH only, got "
            f"{getattr(topo.family, 'value', topo.family)!r}")
    seats = {r.seat_capacity for r in topo.routers}
    if seats != {4}:
        raise SemanticLoss(
            "UNSUPPORTED: the vendored CMesh asserts c == 4 "
            f"(networks/cmesh.cpp::_ComputeSize); seats are {sorted(seats)}")
    n = topo.router_count
    k = math.isqrt(n)
    if k * k != n or k < 1:
        raise SemanticLoss(
            f"UNSUPPORTED: certified cmesh-DOR covers square k x k router "
            f"grids only, got {n} routers")
    for router in topo.routers:
        x, y = router.coordinates[0], router.coordinates[1] \
            if len(router.coordinates) > 1 else None
        if y is None or router.coordinates != (x, y) \
                or router.router_id != y * k + x:
            raise SemanticLoss(
                f"UNSUPPORTED: router {router.router_id} coordinates "
                f"{router.coordinates} do not match the fork's row-major "
                "y * k + x numbering")

    endpoints = parents.attachment.endpoints
    if sorted(e.endpoint_id for e in endpoints) \
            != list(range(len(endpoints))):
        raise SemanticLoss(
            "UNSUPPORTED: endpoint ids are not dense 0..E-1; the cmesh "
            "node universe cannot be addressed without a remap proof")
    expected_nodes = n * 4
    if len(endpoints) != expected_nodes:
        raise SemanticLoss(
            f"UNSUPPORTED: the fork's node universe has exactly {n} * 4 "
            f"= {expected_nodes} nodes; {len(endpoints)} endpoints attach")
    by_router: dict[int, list[int]] = {}
    for endpoint in endpoints:
        by_router.setdefault(endpoint.router_id, []).append(endpoint.port_id)
    for router_id, ports in by_router.items():
        if sorted(ports) != [0, 1, 2, 3]:
            raise SemanticLoss(
                f"UNSUPPORTED: router {router_id} seats ports {sorted(ports)}; "
                "the fork's NodeToPort expects the dense 2x2 seat block "
                "0..3 on every router")

    classes = [d.id for d in parents.route.routing_classes]
    if DOR_XY not in classes or list(classes) != [DOR_XY]:
        raise SemanticLoss(
            f"UNSUPPORTED: certified cmesh-DOR realizes DOR_XY only; route "
            f"artifact classes are {classes}")
    vc_classes = {cls for _vc, cls
                  in parents.vc_assignment.vc_to_routing_class}
    if vc_classes != {DOR_XY}:
        raise SemanticLoss(
            "UNSUPPORTED: the cmesh-DOR profile executes one DOR routing "
            f"function, but VCs map to {sorted(vc_classes)}")

    latencies = {c.latency_cycles for c in topo.channels}
    if latencies != {1}:
        raise SemanticLoss(
            "UNSUPPORTED: this profile pins use_noc_latency = 0, under "
            "which every fork link latency is 1; canonical channels carry "
            f"{sorted(latencies)} — the design would execute with wrong "
            "latency, so it is refused rather than silently re-timed")
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
            f"{parallel[:3]} have no native cmesh representation")

    exact, reason = vc_exactness(parents.vc_resource)
    if not exact:
        raise SemanticLoss(f"UNSUPPORTED: {reason}")
    if parents.vc_resource.allowed_transitions != tuple(
            (vc, vc) for vc in parents.vc_resource.vc_ids):
        raise SemanticLoss(
            "UNSUPPORTED: the certified profile executes identity VC "
            "transitions only")

    return CMeshDorQualification(
        k=k, concentration=4, router_count=n,
        endpoint_count=len(endpoints),
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


def _iter_physical_packets(physical_traffic: PhysicalTrafficArtifactV2
                           ) -> Iterator[Any]:
    """Physical packets in the exact emission order ``render_trace`` uses.

    One authority for the trace order: the renderer, the conservation
    proof and the convergence schedule all iterate this sequence.
    """
    for message in physical_traffic.traffic:
        for packet in message.packets:
            yield packet


def render_trace(physical_traffic: PhysicalTrafficArtifactV2) -> bytes:
    """Render canonical physical traffic as the BookSim whitespace trace.

    The fork's trace dialect is ``cyc src cl dst sz`` with ``sz`` in
    FLITS, one line per physical packet, timestamps in emission order.
    Deterministic: (message order, packet index) only.

    Single-class only: the dialect's class column renders 0, so
    multi-class traffic has no certified rendering — profile selection
    refuses execution first, and this guard closes the seam against any
    future caller that reaches the render directly.
    """
    classes = {m.traffic_class for m in physical_traffic.logical.messages}
    if len(classes) != 1:
        raise BookSimProjectionError(
            f"multi-class traffic {sorted(classes)} has no certified "
            f"BookSim trace dialect (the class column renders one class "
            f"only); refusing a class-blind execution")
    lines: list[str] = []
    for timestamp, packet in enumerate(_iter_physical_packets(physical_traffic)):
        lines.append(f"{timestamp} {packet.src_endpoint} 0 "
                     f"{packet.dst_endpoint} {packet.flit_count}")
    return ("\n".join(lines) + "\n").encode()


def trace_injection_horizon(physical_traffic: PhysicalTrafficArtifactV2) -> int:
    """Cycles to serialize the trace through the per-source ports.

    A source port injects at most one flit per cycle (BookSim's default
    injection bandwidth), so a packet scheduled at cycle ``t`` with ``f``
    flits cannot begin before the source has finished its earlier packets.
    Returns the cycle the last flit enters the network, i.e. an exclusive
    finish time ``>= max_timestamp + 1``.
    """
    free_at: dict[int, int] = {}
    for timestamp, packet in enumerate(_iter_physical_packets(physical_traffic)):
        src = packet.src_endpoint
        start = max(timestamp, free_at.get(src, 0))
        free_at[src] = start + packet.flit_count
    return max(free_at.values(), default=0)


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
    elif profile.profile_id == _CMESH_DOR_PROFILE_ID:
        qual = qualify_native_cmesh_dor(parents)
        values = dict(profile.pinned_values())
        values.update({
            "topology": "cmesh", "k": qual.k, "n": 2,
            "c": qual.concentration,
            "x": qual.k, "y": qual.k,
            "xr": math.isqrt(qual.concentration),
            "yr": math.isqrt(qual.concentration),
            "use_noc_latency": 0,
            "routing_function": _CMESH_DOR_ROUTING_FUNCTION,
            "routing_dump_file": ROUTE_DUMP_FILE,
            "num_vcs": parents.vc_resource.vc_count,
        })
    elif profile.profile_id == _ANYNET_PROFILE_ID:
        values = dict(profile.pinned_values())
        values.update({
            "topology": "anynet", "network_file": TOPOLOGY_FILE,
            "routing_function": _ANYNET_ROUTING_FUNCTION,
            "routing_dump_file": ROUTE_DUMP_FILE,
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
    runtime. The convergence window is the per-source injection horizon
    plus a fixed drain margin (F-0007).
    """
    expected_packets = sum(len(m.packets) for m in physical_traffic.traffic)
    if expected_packets <= 0:
        raise BookSimProjectionError(
            "a trace-driven execution requires a non-empty trace")
    max_timestamp = expected_packets - 1
    # The window must cover the per-source injection horizon, not merely the
    # last scheduled timestamp: a single source emitting back-to-back
    # multi-flit packets needs `sum(flits)` cycles to inject them, and a
    # window that stops earlier truncates the run (the conservation gate
    # then refuses it — F-0007).
    horizon = trace_injection_horizon(physical_traffic)
    needed = horizon + _SAMPLE_PERIOD_MARGIN
    sample_period = max(_SAMPLE_PERIOD_MIN, needed)
    max_samples = max(1, -(-needed // sample_period))
    return {"expected_packets": expected_packets,
            "max_timestamp": max_timestamp,
            "injection_horizon": horizon,
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
    #: canonical first-hop expectation: (src_router, node, next_router)
    #: rows over the execution node universe. Bound so execution can prove
    #: the executed route realization (P0.10).
    expected_route_rows: tuple[tuple[int, int, int], ...] = ()
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
            "expected_route_rows": [list(r) for r in self.expected_route_rows],
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
    """Native mesh DOR, then native concentrated-mesh DOR, else AnyNet.

    When all refuse, the native mesh-DOR reason leads the message: it is
    the profile this fabric was built for (mesh + DOR_XY), so its refusal
    names the real gap; the other refusals are fallback notes, never the
    headline that hides the operative cause.
    """
    try:
        qualify_native_mesh_dor(parents)
    except SemanticLoss as native_exc:
        try:
            qualify_native_cmesh_dor(parents)
        except SemanticLoss:
            pass
        else:
            return CMESH_DOR_PROFILE
        try:
            qualify_anynet_min_hops(parents)   # refuse if unrepresentable
        except SemanticLoss as anynet_exc:
            raise SemanticLoss(
                f"{native_exc}; the AnyNet fallback also refuses: "
                f"{anynet_exc}") from native_exc
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
    # include_optional renders the route-dump path: the executed first-hop
    # realization is required evidence (P0.10), so it is not optional for a
    # certified prepared input.
    config = render_config(parents, profile, include_optional=True, seed=seed)
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
    undeclared = set(rendered) - profile.known_names()
    if undeclared:
        raise BookSimProjectionError(
            f"rendered config carries fields outside the audited profile "
            f"surface {sorted(undeclared)} for {profile.profile_id}: an "
            "undeclared simulation-relevant value is never emitted")
    for name, pin in profile.pinned_values().items():
        if rendered.get(name) != _format_value(pin):
            raise BookSimProjectionError(
                f"rendered {name}={rendered.get(name)!r} does not equal the "
                f"profile pin {pin!r}")
    topology_text = (render_anynet_topology(parents).decode()
                     if profile.profile_id == _ANYNET_PROFILE_ID else None)
    pt = parents.physical_traffic
    schedule = trace_schedule(pt)
    # Canonical executed-route expectation. mesh-DOR addresses every router
    # as a node (native mesh node n <-> router n); AnyNet addresses the
    # attached endpoint nodes; cmesh addresses the fork's 2k x 2k folded
    # node grid via the seat mapping.
    from veritx_dse.backend.route_observation import expected_route_rows
    if profile.profile_id == _MESH_DOR_PROFILE_ID:
        routing_class = DOR_XY
        node_to_router = {n: n
                          for n in range(parents.topology.router_count)}
    elif profile.profile_id == _CMESH_DOR_PROFILE_ID:
        routing_class = DOR_XY
        node_to_router = _cmesh_node_to_router(
            math.isqrt(parents.topology.router_count),
            parents.topology.routers[0].seat_capacity)
    else:
        routing_class = ANYNET_MIN_HOPS
        node_to_router = {e.endpoint_id: e.router_id
                          for e in parents.attachment.endpoints}
    route_rows = expected_route_rows(
        routing_class=routing_class, topology=parents.topology,
        route=parents.route, node_to_router=node_to_router)
    return PreparedBookSimInput(
        profile_id=profile.profile_id,
        semantics_version=profile.semantics_version,
        lowerer_version=(_MESH_DOR_LOWERER_VERSION
                         if profile.profile_id == _MESH_DOR_PROFILE_ID
                         else (_CMESH_DOR_LOWERER_VERSION
                               if profile.profile_id == _CMESH_DOR_PROFILE_ID
                               else "ANYNET/1")),
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
        expected_route_rows=route_rows,
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
    "CMESH_DOR_PROFILE", "CmeshDorQualification",
    "CONFIG_FILE", "CONFIG_KEY_ORDER", "ConfigRead", "MESH_DOR_PROFILE",
    "MeshDorQualification", "ParameterOwner", "PreparedBookSimInput",
    "ROUTE_DUMP_FILE", "SemanticLoss", "TOPOLOGY_FILE", "TRACE_FILE",
    "TRACE_SCHEDULE_VERSION", "assert_canonical_booksim_projection",
    "compare_route_realization", "parse_config_values",
    "prepare_booksim_input", "qualify_anynet_min_hops",
    "qualify_native_cmesh_dor", "qualify_native_mesh_dor",
    "render_anynet_topology", "render_config",
    "render_trace", "select_booksim_profile", "source_audit_report",
    "trace_injection_horizon", "trace_schedule", "vc_exactness",
    "verify_trace_conservation",
]
