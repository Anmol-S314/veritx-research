"""veritx_dse.backend.booksim_projection — qualified BookSim projection.

Rationale: docs/decisions/modules/backend.md
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
from veritx_dse.core.route_artifact import (
    ANYNET_MIN_HOPS, DOR_TORUS_XY, DOR_XY, FLATFLY_MIN,
)
from veritx_dse.model.topology_artifact import MaterializedFamily
from veritx_dse.model.topology_ir import ANYNET_ROUTE_COST
from veritx_dse.workload.traffic import PhysicalTrafficArtifactV2
from veritx_dse.model.family_registry import spec_for

BOOKSIM_PROJECTION_SCHEMA_VERSION = 5

_MESH_DOR_PROFILE_ID = "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1"
_MESH_DOR_SEMANTICS_VERSION = "booksim2-fork+P1B-meshdor-dump+prepared-v2"
_MESH_DOR_LOWERER_VERSION = "DORXY/1"
_MESH_DOR_ROUTING_FUNCTION = "dim_order"

_CMESH_DOR_PROFILE_ID = "CERTIFIED_BOOKSIM_CMESH_DOR_XY_V1"
_CMESH_DOR_SEMANTICS_VERSION = "booksim2-fork+P2-cmesh-dor+prepared-v1"
_CMESH_DOR_LOWERER_VERSION = "DORXY/1"
_CMESH_DOR_ROUTING_FUNCTION = "dor_no_express"

_ANYNET_PROFILE_ID = "CERTIFIED_BOOKSIM_ANYNET_V1"
_ANYNET_SEMANTICS_VERSION = "booksim2-fork+B3.7b-anynet-dump+prepared-v2"

TRACE_SCHEDULE_VERSION = "srota/booksim-trace-schedule/v2"
_SAMPLE_PERIOD_MIN = 200
_SAMPLE_PERIOD_MARGIN = 1000
_ANYNET_ROUTING_FUNCTION = "min"
_ANYNET_ROUTING_KEY = "min_anynet"

CONFIG_FILE = "config.cfg"
TOPOLOGY_FILE = "topology.anynet"
TRACE_FILE = "workload.trace"
ROUTE_DUMP_FILE = "routing.dump"

_ROUTE_DUMP_DIALECT = "booksim-native-mesh-dor-dump-v1"

class BookSimProjectionError(ValueError):
    """The projection cannot be rendered from these canonical artifacts."""

class SemanticLoss(BookSimProjectionError):
    """A canonical dimension has no exact BookSim representation."""

class ParameterOwner(Enum):
    """Who owns a simulation-relevant BookSim value."""

    CANONICAL = "CANONICAL"
    DERIVED = "DERIVED"
    BACKEND_PROFILE = "BACKEND_PROFILE"
    UNSUPPORTED = "UNSUPPORTED"

@dataclass(frozen=True)
class ConfigRead:
    """One simulation-relevant configuration field."""

    name: str
    owner: ParameterOwner
    source: str
    pin: Any = None
    note: str = ""
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

_A = ParameterOwner

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

Rationale: docs/decisions/modules/backend.md
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

_ML_DOR_PROFILE_ID = "CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1"
_ML_DOR_SEMANTICS_VERSION = "booksim2-fork+P3-meshdor-mc+prepared-v1"
_ML_DOR_LOWERER_VERSION = "DORXY-MC/1"

def _mc_audit() -> tuple[ConfigRead, ...]:
    """The mesh-DOR audit with ``classes`` promoted to CANONICAL.

Rationale: docs/decisions/modules/backend.md
    """
    rows: list[ConfigRead] = []
    for row in _mesh_audit():
        if row.name == "classes":
            rows.append(ConfigRead(
                "classes", _A.CANONICAL, "trafficmanager.cpp",
                note="number of canonical traffic classes in the executed "
                     "workload; the fork's per-class replay filter makes "
                     "the count execute as declared"))
            continue
        rows.append(row)
    return tuple(rows)

MESH_DOR_MC_PROFILE = BookSimProfile(
    profile_id=_ML_DOR_PROFILE_ID,
    semantics_version=_ML_DOR_SEMANTICS_VERSION, audit=_mc_audit())

_MIN_ADAPT_PROFILE_ID = "CERTIFIED_BOOKSIM_MIN_ADAPT_MESH_V1"
_MIN_ADAPT_SEMANTICS_VERSION = "booksim2-fork+A1-minadaptmesh+prepared-v1"
_MIN_ADAPT_LOWERER_VERSION = "MINADAPT/1"
_MIN_ADAPT_ROUTING_FUNCTION = "min_adapt_mesh"

def _min_adapt_audit() -> tuple[ConfigRead, ...]:
    """The mesh audit for runtime-selected adaptive routing.

Rationale: docs/decisions/modules/backend.md
    """
    return tuple(row for row in _mc_audit()
                  if row.name != "routing_dump_file")

MIN_ADAPT_MESH_PROFILE = BookSimProfile(
    profile_id=_MIN_ADAPT_PROFILE_ID,
    semantics_version=_MIN_ADAPT_SEMANTICS_VERSION,
    audit=_min_adapt_audit())

_TORUS_DOR_PROFILE_ID = "CERTIFIED_BOOKSIM_TORUS_DOR_XY_V1"
_TORUS_DOR_SEMANTICS_VERSION = "booksim2-fork+T1-torusdor-dump+prepared-v1"
_TORUS_DOR_LOWERER_VERSION = "DORTORUS/1"
_TORUS_DOR_ROUTING_FUNCTION = "dim_order"

def _torus_audit() -> tuple[ConfigRead, ...]:
    """The audit re-pathed for the native torus (KNCube) surface.

Rationale: docs/decisions/modules/backend.md
    """
    rows: list[ConfigRead] = []
    for row in _mesh_audit():
        if row.name in ("k", "n", "use_noc_latency"):
            continue
        if row.name == "topology":
            rows.append(ConfigRead(
                "topology", _A.CANONICAL, "networks/network.cpp",
                "torus",
                note="native torus render (KNCube, mesh=false)"))
            continue
        rows.append(row)
    rows.extend((
        ConfigRead(
            "k", _A.DERIVED, "networks/kncube.cpp",
            note="torus side: k x k router grid re-derived from the "
                 "topology artifact"),
        ConfigRead(
            "n", _A.DERIVED, "networks/kncube.cpp",
            note="dimensionality; the certified domain pins n = 2"),
        ConfigRead(
            "use_noc_latency", _A.BACKEND_PROFILE,
            "networks/kncube.cpp", 0,
            note="PINNED 0: the noc-latency path makes wrap links "
                 "latency 2; canonical torus channels are latency 1"),
    ))
    return tuple(rows)

TORUS_DOR_PROFILE = BookSimProfile(
    profile_id=_TORUS_DOR_PROFILE_ID,
    semantics_version=_TORUS_DOR_SEMANTICS_VERSION,
    audit=_torus_audit())

_FLATFLY_MIN_PROFILE_ID = "CERTIFIED_BOOKSIM_FLATFLY_MIN_V1"
_FLATFLY_MIN_SEMANTICS_VERSION = "booksim2-fork+F1-flatflymin-dump+prepared-v1"
_FLATFLY_MIN_LOWERER_VERSION = "FLATFLYMIN/1"
_FLATFLY_MIN_ROUTING_FUNCTION = "ran_min"

def _flatfly_audit() -> tuple[ConfigRead, ...]:
    """The audit re-pathed for the native FlatFly (on-chip) surface.

Rationale: docs/decisions/modules/backend.md
    """
    rows: list[ConfigRead] = []
    for row in _mesh_audit():
        if row.name in ("k", "n", "use_noc_latency"):
            continue
        if row.name == "topology":
            rows.append(ConfigRead(
                "topology", _A.CANONICAL, "networks/network.cpp",
                "flatfly",
                note="native flatfly render (no AnyNet file)"))
            continue
        rows.append(row)
    rows.extend((
        ConfigRead(
            "k", _A.DERIVED, "networks/flatfly_onchip.cpp",
            note="per-dimension size re-derived from the topology "
                 "artifact"),
        ConfigRead(
            "n", _A.DERIVED, "networks/flatfly_onchip.cpp",
            note="dimension count; the certified domain pins n = 2"),
        ConfigRead(
            "c", _A.CANONICAL, "networks/flatfly_onchip.cpp",
            note="seats per router; the certified domain pins c = 1"),
        ConfigRead(
            "x", _A.DERIVED, "networks/flatfly_onchip.cpp",
            note="topology extent; asserted equal to y, rendered as k"),
        ConfigRead(
            "y", _A.DERIVED, "networks/flatfly_onchip.cpp",
            note="topology extent; asserted equal to x"),
        ConfigRead(
            "xr", _A.CANONICAL, "networks/flatfly_onchip.cpp",
            note="concentration split; c = 1 gives xr = yr = 1"),
        ConfigRead(
            "yr", _A.CANONICAL, "networks/flatfly_onchip.cpp",
            note="concentration split; asserted equal to xr"),
        ConfigRead(
            "use_noc_latency", _A.BACKEND_PROFILE,
            "networks/flatfly_onchip.cpp", 0,
            note="PINNED 0: uniform link latency 1 like the canonical "
                 "channels"),
    ))
    return tuple(rows)

FLATFLY_MIN_PROFILE = BookSimProfile(
    profile_id=_FLATFLY_MIN_PROFILE_ID,
    semantics_version=_FLATFLY_MIN_SEMANTICS_VERSION,
    audit=_flatfly_audit())

def _assert_profile_closure() -> None:
    for profile in (ANYNET_PROFILE, MESH_DOR_PROFILE, CMESH_DOR_PROFILE,
                    MESH_DOR_MC_PROFILE, TORUS_DOR_PROFILE,
                    FLATFLY_MIN_PROFILE, MIN_ADAPT_MESH_PROFILE):
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

@dataclass(frozen=True)
class BookSimProjectionParents:
    """The explicit canonical machine artifacts a projection stands on.

Rationale: docs/decisions/modules/backend.md
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

@dataclass(frozen=True)
class MeshDorQualification:
    """The proof that the native mesh DOR projection may be used."""

    k: int
    router_count: int
    endpoint_count: int
    route_artifact_hash: str
    vc_resource_hash: str
    attachment_hash: str
    trace_classes: tuple[str, ...] = ()

def qualify_native_mesh_dor(parents: BookSimProjectionParents,
                            *, multi_class: bool = False
                            ) -> MeshDorQualification:
    """Prove every prerequisite, or refuse. Never a family-name shortcut.

    Physical gates live in _mesh_dor_physical_gates (shared verbatim
    with the MIN_ADAPT envelope); the class laws below are the
    deterministic-DOR envelope's own."""
    topo = parents.topology
    _mesh_dor_physical_gates(parents)
    _refuse_unbound_escape(parents, "mesh-DOR")
    n = topo.router_count
    k = math.isqrt(n)
    endpoints = parents.attachment.endpoints
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

    traffic = getattr(parents, "physical_traffic", None)
    if traffic is None:
        trace_classes: tuple[str, ...] = ()
    else:
        trace_classes = trace_class_map(traffic)
        if not multi_class and len(trace_classes) != 1:
            raise SemanticLoss(
                "UNSUPPORTED: the single-class mesh profile executes ONE "
                "traffic class (config pins classes = 1); this workload "
                f"declares {sorted(trace_classes)} — the multi-class "
                "profile owns this traffic")

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
        attachment_hash=parents.attachment.attachment_hash(),
        trace_classes=trace_classes)

def qualify_native_mesh_dor_mc(
        parents: BookSimProjectionParents) -> MeshDorQualification:
    """Qualify the multi-class mesh-DOR profile.

Rationale: docs/decisions/modules/backend.md
    """
    _mc_traffic = getattr(parents, "physical_traffic", None)
    if _mc_traffic is not None \
            and len(trace_class_map(_mc_traffic)) < 2:
        raise SemanticLoss(
            "UNSUPPORTED: the multi-class mesh profile requires two or "
            "more canonical traffic classes; single-class traffic is the "
            "single-class profile's domain")
    qual = qualify_native_mesh_dor(parents, multi_class=True)
    return MeshDorQualification(
        k=qual.k, router_count=qual.router_count,
        endpoint_count=qual.endpoint_count,
        route_artifact_hash=qual.route_artifact_hash,
        vc_resource_hash=qual.vc_resource_hash,
        attachment_hash=qual.attachment_hash,
        trace_classes=qual.trace_classes)

def _min_adapt_k(parents: BookSimProjectionParents) -> int:
    import math
    n = parents.topology.router_count
    k = math.isqrt(n)
    if k * k != n or k < 1:
        raise SemanticLoss(
            f"UNSUPPORTED: min_adapt mesh covers square k x k meshes "
            f"only, got {n} routers")
    return k

def _refuse_unbound_escape(parents: BookSimProjectionParents,
                           profile: str) -> None:
    """Refuse a design whose deadlock policy names escape VCs on a path
    that executes plain VCs with no escape semantics.

    The min_adapt envelope binds the escape partition exactly (see
    _check_escape_transitions); every other native profile below must
    refuse instead. A non-empty escape set reaching execution here would
    silently omit the declared deadlock policy."""
    escape = tuple(getattr(parents.vc_assignment, "escape_vcs", ()) or ())
    if escape:
        raise SemanticLoss(
            f"UNSUPPORTED: the certified deadlock policy names escape "
            f"VCs {list(escape)}, but the {profile} profile executes "
            "plain VCs with no escape semantics — refusing rather than "
            "executing a network that omits its deadlock policy")


def _check_escape_transitions(base_transitions, esc_transitions,
                              selection) -> None:
    have = set(base_transitions)
    esc = set(esc_transitions)
    if not have <= esc:
        raise SemanticLoss(
            "UNSUPPORTED: escape resource must extend (never rewrite) "
            "the compiler-derived transitions")
    roles = {"escape": tuple(selection.escape_vcs),
             "adaptive": tuple(selection.adaptive_vcs)}
    need = {(v, v) for vcs in roles.values() for v in vcs}
    need |= {(a, e) for a in roles.get("adaptive", ())
             for e in roles.get("escape", ())}
    if not need <= esc:
        raise SemanticLoss(
            "UNSUPPORTED: escape resource lacks required transitions "
            f"{sorted(need - esc)}")
    allowed_extra = {(a, e) for a in roles.get("adaptive", ())
                     for e in roles.get("escape", ())}
    if esc - have - allowed_extra:
        raise SemanticLoss(
            "UNSUPPORTED: escape resource adds non-escape transitions "
            f"{sorted(esc - have - allowed_extra)}")

def _mesh_dor_physical_gates(parents: BookSimProjectionParents) -> None:
    """Mesh-DOR physical truth shared by the DOR and MIN_ADAPT envelopes.

Rationale: docs/decisions/modules/backend.md
    """
    topo = parents.topology
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

def qualify_min_adapt_mesh(parents: BookSimProjectionParents, selection,
                           qualification, esc_resource
                           ) -> MeshDorQualification:
    """Qualify runtime-selected MIN_ADAPT_MESH execution.

Rationale: docs/decisions/modules/backend.md
    """
    from veritx_dse.model.routing_realization import (
        AdaptiveBackendSelection,
        MIN_ADAPT_BACKEND_ROUTING_FUNCTION,
    )
    if not isinstance(selection, AdaptiveBackendSelection):
        raise SemanticLoss(
            f"UNSUPPORTED: min_adapt projection consumes an "
            f"AdaptiveBackendSelection, got "
            f"{type(selection).__name__}")
    if getattr(qualification, "verdict", None) != "QUALIFIED":
        raise SemanticLoss(
            "UNSUPPORTED: min_adapt projection requires a QUALIFIED "
            "MinAdaptQualification (escape-subfunction proof); got "
            f"{getattr(qualification, 'verdict', None)!r}")
    if getattr(qualification, "routing_function", None) != \
            MIN_ADAPT_BACKEND_ROUTING_FUNCTION:
        raise SemanticLoss(
            "UNSUPPORTED: qualification routing function "
            f"{getattr(qualification, 'routing_function', None)!r} is "
            "not the min_adapt_mesh backend selection")
    for field in ("escape_vcs", "adaptive_vcs", "policy_hash",
                  "realization_hash"):
        if getattr(qualification, field, None) != \
                getattr(selection, field, None):
            raise SemanticLoss(
                f"UNSUPPORTED: qualification {field} does not match "
                "the backend selection")
    _mesh_dor_physical_gates(parents)
    classes = [d.id for d in parents.route.routing_classes]
    if DOR_XY not in classes:
        raise SemanticLoss(
            f"UNSUPPORTED: min_adapt runs on a DOR_XY escape route; route "
            f"artifact classes are {classes}")
    traffic = getattr(parents, "physical_traffic", None)
    trace_classes = trace_class_map(traffic) \
        if traffic is not None else ()
    if len(trace_classes) > 1:
        raise SemanticLoss(
            "UNSUPPORTED: min_adapt v1 covers single-class traffic only; "
            f"this workload declares {sorted(trace_classes)} (adaptive + "
            "multi-class interaction is unproven)")
    from veritx_dse.model.vc_resource import VCResourceArtifact
    if not isinstance(esc_resource, VCResourceArtifact):
        raise SemanticLoss(
            "UNSUPPORTED: min_adapt projection consumes an explicit "
            "escape-augmented VCResourceArtifact, got "
            f"{type(esc_resource).__name__}")
    if tuple(esc_resource.vc_ids) != tuple(parents.vc_resource.vc_ids):
        raise SemanticLoss(
            "UNSUPPORTED: escape resource VC ids diverge from the "
            "compiler-derived resource")
    exact, reason = vc_exactness(esc_resource)
    if not exact:
        raise SemanticLoss(
            f"UNSUPPORTED: min_adapt executed VC domain refused: {reason}")
    vc_count = esc_resource.vc_count
    if vc_count != selection.num_vcs or vc_count < 2:
        raise SemanticLoss(
            f"UNSUPPORTED: min_adapt escape partition needs vc_count "
            f"== selection.num_vcs >= 2, got vc_count={vc_count} vs "
            f"selection {selection.num_vcs}")
    _check_escape_transitions(
        parents.vc_resource.allowed_transitions,
        esc_resource.allowed_transitions, selection)
    topo = parents.topology
    endpoints = parents.attachment.endpoints
    return MeshDorQualification(
        k=math.isqrt(topo.router_count),
        router_count=topo.router_count,
        endpoint_count=len(endpoints),
        route_artifact_hash=parents.route.artifact_hash,
        vc_resource_hash=esc_resource.artifact_hash,
        attachment_hash=parents.attachment.attachment_hash(),
        trace_classes=tuple(trace_classes))

@dataclass(frozen=True)
class CMeshDorQualification:
    """The proof that the native concentrated-mesh DOR projection may be used.

Rationale: docs/decisions/modules/backend.md
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

Rationale: docs/decisions/modules/backend.md
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

Rationale: docs/decisions/modules/backend.md
    """
    from veritx_dse.backend.route_observation import expected_route_rows
    return expected_route_rows(
        routing_class=DOR_XY, topology=parents.topology,
        route=parents.route,
        node_to_router=_cmesh_node_to_router(k, concentration))

def qualify_native_cmesh_dor(
        parents: BookSimProjectionParents) -> CMeshDorQualification:
    """Prove every prerequisite of the cmesh envelope, or refuse.

Rationale: docs/decisions/modules/backend.md
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
    _refuse_unbound_escape(parents, "cmesh-DOR")
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

    if len(trace_class_map(parents.physical_traffic)) != 1:
        raise SemanticLoss(
            "UNSUPPORTED: the single-class cmesh profile executes ONE "
            "traffic class (config pins classes = 1); this workload "
            "declares "
            f"{sorted(trace_class_map(parents.physical_traffic))} — the "
            "multi-class profile owns this traffic")

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

@dataclass(frozen=True)
class TorusDorQualification:
    """The proof that the native torus DOR projection may be used.

Rationale: docs/decisions/modules/backend.md
    """

    k: int
    router_count: int
    endpoint_count: int
    route_artifact_hash: str
    vc_resource_hash: str
    attachment_hash: str
    tie_flows: tuple[tuple[int, int], ...] = ()

def qualify_native_torus_dor(
        parents: BookSimProjectionParents) -> TorusDorQualification:
    """Prove every prerequisite of the torus envelope, or refuse.

Rationale: docs/decisions/modules/backend.md
    """
    from veritx_dse.core.route_artifact import dor_torus_xy_tie_flows
    topo = parents.topology
    if topo.family is not MaterializedFamily.TORUS:
        raise SemanticLoss(
            "UNSUPPORTED: the certified torus-DOR profile covers "
            "TopologyArtifact.family TORUS only, got "
            f"{getattr(topo.family, 'value', topo.family)!r}")
    n = topo.router_count
    k = math.isqrt(n)
    if k * k != n or k < 2:
        raise SemanticLoss(
            f"UNSUPPORTED: certified torus-DOR covers square k x k "
            f"torus only, got {n} routers")
    seats = {r.seat_capacity for r in topo.routers}
    if seats != {1}:
        raise SemanticLoss(
            f"UNSUPPORTED: certified torus-DOR covers seat_capacity 1 "
            f"only, got {sorted(seats)}")
    _refuse_unbound_escape(parents, "torus-DOR")
    endpoints = parents.attachment.endpoints
    if len(endpoints) > n:
        raise SemanticLoss(
            f"UNSUPPORTED: {len(endpoints)} attached endpoints exceed "
            f"the {n} native torus nodes")
    if sorted(e.endpoint_id for e in endpoints) != list(range(len(endpoints))):
        raise SemanticLoss(
            "UNSUPPORTED: endpoint ids are not dense 0..E-1")
    for endpoint in endpoints:
        if endpoint.router_id != endpoint.endpoint_id:
            raise SemanticLoss(
                f"UNSUPPORTED: endpoint {endpoint.endpoint_id} attaches "
                f"to router {endpoint.router_id}, not its native node")
    classes = [d.id for d in parents.route.routing_classes]
    if DOR_TORUS_XY not in classes:
        raise SemanticLoss(
            f"UNSUPPORTED: certified torus-DOR realizes DOR_TORUS_XY "
            f"only; route artifact classes are {classes}")
    vc_classes = {cls for _vc, cls
                  in parents.vc_assignment.vc_to_routing_class}
    if vc_classes != {DOR_TORUS_XY}:
        raise SemanticLoss(
            "UNSUPPORTED: the torus-DOR profile executes one "
            "wraparound dimension-order function, but VCs map to "
            f"{sorted(vc_classes)}")
    latencies = {c.latency_cycles for c in topo.channels}
    if latencies != {1}:
        raise SemanticLoss(
            f"UNSUPPORTED: native torus links are latency 1; channels "
            f"carry {sorted(latencies)}")
    weights = {c.route_weight for c in topo.channels}
    if weights != {1}:
        raise SemanticLoss(
            f"UNSUPPORTED: DOR_TORUS_XY is hop-count semantics but "
            f"channels carry route_weight {sorted(weights)}")
    pairs: dict[tuple[int, int], int] = {}
    for channel in topo.channels:
        key = (channel.src_router, channel.dst_router)
        pairs[key] = pairs.get(key, 0) + 1
    parallel = sorted(key for key, count in pairs.items() if count > 1)
    if parallel:
        raise SemanticLoss(
            f"UNSUPPORTED: parallel channels between routers "
            f"{parallel[:3]} have no native torus representation")
    if len(trace_class_map(parents.physical_traffic)) != 1:
        raise SemanticLoss(
            "UNSUPPORTED: the torus-DOR v1 profile executes ONE "
            f"traffic class; this workload declares "
            f"{sorted(trace_class_map(parents.physical_traffic))}")
    if parents.vc_resource.vc_count != 2:
        raise SemanticLoss(
            f"UNSUPPORTED: the torus-DOR dateline partition requires "
            f"exactly 2 VCs (one per partition half), got "
            f"vc_count={parents.vc_resource.vc_count} — the fork "
            "integer-halves the range, so any other count overlaps or "
            "starves a partition")
    exact, reason = vc_exactness(parents.vc_resource)
    if not exact:
        raise SemanticLoss(f"UNSUPPORTED: {reason}")
    if parents.vc_resource.allowed_transitions != tuple(
            (vc, vc) for vc in parents.vc_resource.vc_ids):
        raise SemanticLoss(
            "UNSUPPORTED: the certified profile executes identity VC "
            "transitions only")
    return TorusDorQualification(
        k=k, router_count=n, endpoint_count=len(endpoints),
        route_artifact_hash=parents.route.artifact_hash,
        vc_resource_hash=parents.vc_resource.artifact_hash,
        attachment_hash=parents.attachment.attachment_hash(),
        tie_flows=tuple(sorted(dor_torus_xy_tie_flows(topo))))

@dataclass(frozen=True)
class FlatflyMinQualification:
    """The proof that the native FlatFly-minimal projection may be used."""

    k: int
    n: int
    concentration: int
    router_count: int
    endpoint_count: int
    route_artifact_hash: str
    vc_resource_hash: str
    attachment_hash: str

def qualify_native_flatfly_min(
        parents: BookSimProjectionParents) -> FlatflyMinQualification:
    """Prove every prerequisite of the flatfly envelope, or refuse.

    v1 domain: family FLATFLY, dimension count 2, concentration 1
    (identity node -> router), DOR-free minimal class FLATFLY_MIN,
    single traffic class over the full VC set, identity transitions,
    unit latency/weight, no parallel channels.
    """
    topo = parents.topology
    if topo.family is not MaterializedFamily.FLATFLY:
        raise SemanticLoss(
            "UNSUPPORTED: the certified flatfly-min profile covers "
            "TopologyArtifact.family FLATFLY only, got "
            f"{getattr(topo.family, 'value', topo.family)!r}")
    _refuse_unbound_escape(parents, "flatfly-min")
    n_routers = topo.router_count
    k = math.isqrt(n_routers)
    if k * k != n_routers or k < 2:
        raise SemanticLoss(
            f"UNSUPPORTED: certified flatfly-min v1 covers k-ary 2-fly "
            f"only, got {n_routers} routers")
    seats = {r.seat_capacity for r in topo.routers}
    if seats != {1}:
        raise SemanticLoss(
            f"UNSUPPORTED: certified flatfly-min v1 covers "
            f"concentration 1 only, got {sorted(seats)}")
    endpoints = parents.attachment.endpoints
    if len(endpoints) > n_routers:
        raise SemanticLoss(
            f"UNSUPPORTED: {len(endpoints)} attached endpoints exceed "
            f"the {n_routers} native flatfly nodes")
    if sorted(e.endpoint_id for e in endpoints) != list(range(len(endpoints))):
        raise SemanticLoss(
            "UNSUPPORTED: endpoint ids are not dense 0..E-1")
    for endpoint in endpoints:
        if endpoint.router_id != endpoint.endpoint_id:
            raise SemanticLoss(
                f"UNSUPPORTED: endpoint {endpoint.endpoint_id} attaches "
                f"to router {endpoint.router_id}, not its native node")
    classes = [d.id for d in parents.route.routing_classes]
    if FLATFLY_MIN not in classes:
        raise SemanticLoss(
            f"UNSUPPORTED: certified flatfly-min realizes FLATFLY_MIN "
            f"only; route artifact classes are {classes}")
    vc_classes = {cls for _vc, cls
                  in parents.vc_assignment.vc_to_routing_class}
    if vc_classes != {FLATFLY_MIN}:
        raise SemanticLoss(
            "UNSUPPORTED: the flatfly-min profile executes one minimal "
            f"function, but VCs map to {sorted(vc_classes)}")
    latencies = {c.latency_cycles for c in topo.channels}
    if latencies != {1}:
        raise SemanticLoss(
            f"UNSUPPORTED: native flatfly links are latency 1; "
            f"channels carry {sorted(latencies)}")
    weights = {c.route_weight for c in topo.channels}
    if weights != {1}:
        raise SemanticLoss(
            f"UNSUPPORTED: FLATFLY_MIN is hop-count semantics but "
            f"channels carry route_weight {sorted(weights)}")
    pairs = {}
    for channel in topo.channels:
        key = (channel.src_router, channel.dst_router)
        pairs[key] = pairs.get(key, 0) + 1
    parallel = sorted(key for key, count in pairs.items() if count > 1)
    if parallel:
        raise SemanticLoss(
            f"UNSUPPORTED: parallel channels between routers "
            f"{parallel[:3]} have no native flatfly representation")
    if len(trace_class_map(parents.physical_traffic)) != 1:
        raise SemanticLoss(
            "UNSUPPORTED: the flatfly-min v1 profile executes ONE "
            f"traffic class; this workload declares "
            f"{sorted(trace_class_map(parents.physical_traffic))}")
    exact, reason = vc_exactness(parents.vc_resource)
    if not exact:
        raise SemanticLoss(f"UNSUPPORTED: {reason}")
    if parents.vc_resource.allowed_transitions != tuple(
            (vc, vc) for vc in parents.vc_resource.vc_ids):
        raise SemanticLoss(
            "UNSUPPORTED: the certified profile executes identity VC "
            "transitions only")
    return FlatflyMinQualification(
        k=k, n=2, concentration=1, router_count=n_routers,
        endpoint_count=len(endpoints),
        route_artifact_hash=parents.route.artifact_hash,
        vc_resource_hash=parents.vc_resource.artifact_hash,
        attachment_hash=parents.attachment.attachment_hash())

def vc_exactness(vc_resource: Any) -> tuple[bool, str]:
    """The fork executes ONE VC envelope for every traffic class.

Rationale: docs/decisions/modules/backend.md
    """
    if not vc_resource.traffic_class_to_vcs:
        return False, "the VC assignment carries no traffic classes"
    if all(tuple(vcs) == tuple(vc_resource.vc_ids)
           for _cls, vcs in vc_resource.traffic_class_to_vcs):
        return True, ""
    return False, (
        "BookSim trace traffic runs every class over one VC envelope; "
        "this artifact assigns traffic classes to VC subsets the backend "
        "does not execute (route-set envelope; injection starts at VC 0)")

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
            # `<latency> <cost>`: cost pins hop-count routing so a link's
            # own wire latency does not become its route weight.
            parts.append(f"router {channel.dst_router} "
                         f"{channel.latency_cycles} {ANYNET_ROUTE_COST}")
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

def _message_class_of(logical: Any, message: Any) -> str:
    """The canonical traffic class of one physical message.

    V3 stamps each operation's class in ``traffic_class_by_operation``;
    V2 stamps one uniform class on every message. Packets stay
    class-blind by law — the LOGICAL artifact is the class authority.
    """
    by_op = getattr(logical, "traffic_class_by_operation", None)
    if by_op is not None:
        mapping = dict(by_op)
        try:
            return mapping[message.operation_id]
        except KeyError:
            raise BookSimProjectionError(
                f"operation {message.operation_id!r} has no canonical "
                "traffic class in the logical artifact") from None
    cls = getattr(logical, "traffic_class", None)
    if cls is None:
        raise BookSimProjectionError(
            "the logical message artifact carries no traffic-class "
            "authority (neither uniform nor per-operation)")
    return cls

def trace_class_map(physical_traffic: PhysicalTrafficArtifactV2
                    ) -> tuple[str, ...]:
    """Dense trace-class indices for the artifact's canonical classes.

Rationale: docs/decisions/modules/backend.md
    """
    return tuple(sorted({_message_class_of(physical_traffic.logical, m)
                         for m in physical_traffic.traffic}))

#: Rendering and horizon-scanning each walk every packet, and one evaluation
#: does both several times (conservation proof, then input preparation). The
#: physical traffic tuple is already shared by content (see
#: workload.traffic._TRAFFIC_MATERIALIZATION), so its identity is a sound,
#: O(1) memo key; the tuple is held in the entry so the id cannot be reused.
_TRACE_RENDER_CACHE: dict[int, tuple[Any, bytes]] = {}
_TRACE_HORIZON_CACHE: dict[int, tuple[Any, int]] = {}
_TRACE_CONSERVATION_CACHE: dict[int, tuple[Any, dict[str, int]]] = {}
_TRACE_CACHE_LIMIT = 1


def render_trace(physical_traffic: PhysicalTrafficArtifactV2) -> bytes:
    """Render canonical physical traffic as the BookSim whitespace trace.

Rationale: docs/decisions/modules/backend.md
    """
    traffic = physical_traffic.traffic
    key = id(traffic)
    hit = _TRACE_RENDER_CACHE.get(key)
    if hit is not None and hit[0] is traffic:
        return hit[1]
    class_index = {name: i for i, name
                   in enumerate(trace_class_map(physical_traffic))}
    lines: list[str] = []
    timestamp = 0
    for message in physical_traffic.traffic:
        cl = class_index[_message_class_of(physical_traffic.logical,
                                           message)]
        for packet in message.packets:
            lines.append(f"{timestamp} {packet.src_endpoint} {cl} "
                         f"{packet.dst_endpoint} {packet.flit_count}")
            timestamp += 1
    rendered = ("\n".join(lines) + "\n").encode()
    if len(_TRACE_RENDER_CACHE) >= _TRACE_CACHE_LIMIT:
        _TRACE_RENDER_CACHE.clear()
    _TRACE_RENDER_CACHE[key] = (traffic, rendered)
    return rendered

def trace_injection_horizon(physical_traffic: PhysicalTrafficArtifactV2) -> int:
    """Cycles to serialize the trace through the per-source ports.

Rationale: docs/decisions/modules/backend.md
    """
    traffic = physical_traffic.traffic
    key = id(traffic)
    hit = _TRACE_HORIZON_CACHE.get(key)
    if hit is not None and hit[0] is traffic:
        return hit[1]
    free_at: dict[int, int] = {}
    for timestamp, packet in enumerate(_iter_physical_packets(physical_traffic)):
        src = packet.src_endpoint
        start = max(timestamp, free_at.get(src, 0))
        free_at[src] = start + packet.flit_count
    horizon = max(free_at.values(), default=0)
    if len(_TRACE_HORIZON_CACHE) >= _TRACE_CACHE_LIMIT:
        _TRACE_HORIZON_CACHE.clear()
    _TRACE_HORIZON_CACHE[key] = (traffic, horizon)
    return horizon

def verify_trace_conservation(physical_traffic: PhysicalTrafficArtifactV2
                              ) -> dict[str, int]:
    """Mechanical proof that the rendered trace conserves the artifact."""
    # Re-parses the whole rendered trace, so it is O(packets) per call; the
    # memo key is the shared (content-keyed) traffic tuple identity.
    traffic = physical_traffic.traffic
    key = id(traffic)
    hit = _TRACE_CONSERVATION_CACHE.get(key)
    if hit is not None and hit[0] is traffic:
        return dict(hit[1])
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
    flits_by_class: dict[int, int] = {}
    for index, row in enumerate(rows):
        if len(row) != 5:
            raise BookSimProjectionError(
                f"trace line {index} is not the 5-column dialect")
        if int(row[0]) != index:
            raise BookSimProjectionError(
                f"trace timestamp is not deterministic at line {index}")
        flits += int(row[4])
        cl = int(row[2])
        flits_by_class[cl] = flits_by_class.get(cl, 0) + int(row[4])
    if flits != expected_flits:
        raise BookSimProjectionError(
            f"trace projection lost flits: {flits} != {expected_flits}")
    class_map = trace_class_map(physical_traffic)
    expected_by_class: dict[int, int] = {i: 0 for i in range(len(class_map))}
    for message in physical_traffic.traffic:
        i = class_map.index(_message_class_of(physical_traffic.logical,
                                              message))
        for packet in message.packets:
            expected_by_class[i] += packet.flit_count
    if flits_by_class != expected_by_class:
        raise BookSimProjectionError(
            f"trace projection lost class-bound flits: {flits_by_class} "
            f"!= {expected_by_class}")
    result = {"num_packets": expected_packets, "flits_total": expected_flits,
              "flits_by_class": {class_map[i]: n
                                 for i, n in sorted(flits_by_class.items())}}
    if len(_TRACE_CONSERVATION_CACHE) >= _TRACE_CACHE_LIMIT:
        _TRACE_CONSERVATION_CACHE.clear()
    _TRACE_CONSERVATION_CACHE[key] = (traffic, result)
    return dict(result)

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
    elif profile.profile_id == _ML_DOR_PROFILE_ID:
        qual = qualify_native_mesh_dor_mc(parents)
        values = dict(profile.pinned_values())
        values.update({
            "topology": "mesh", "k": qual.k, "n": 2,
            "use_noc_latency": 1,
            "routing_function": _MESH_DOR_ROUTING_FUNCTION,
            "routing_dump_file": ROUTE_DUMP_FILE,
            "num_vcs": parents.vc_resource.vc_count,
            "classes": len(qual.trace_classes),
        })
    elif profile.profile_id == _MIN_ADAPT_PROFILE_ID:
        values = dict(profile.pinned_values())
        values.update({
            "topology": "mesh", "k": _min_adapt_k(parents), "n": 2,
            "use_noc_latency": 1,
            "routing_function": _MIN_ADAPT_ROUTING_FUNCTION,
            "num_vcs": parents.vc_resource.vc_count,
            "classes": len(trace_class_map(
                parents.physical_traffic)),
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
    elif profile.profile_id == _TORUS_DOR_PROFILE_ID:
        qual = qualify_native_torus_dor(parents)
        values = dict(profile.pinned_values())
        values.update({
            "topology": "torus", "k": qual.k, "n": 2,
            "use_noc_latency": 0,
            "routing_function": _TORUS_DOR_ROUTING_FUNCTION,
            "routing_dump_file": ROUTE_DUMP_FILE,
            "num_vcs": parents.vc_resource.vc_count,
        })
    elif profile.profile_id == _FLATFLY_MIN_PROFILE_ID:
        qual = qualify_native_flatfly_min(parents)
        values = dict(profile.pinned_values())
        values.update({
            "topology": "flatfly", "k": qual.k, "n": 2,
            "c": qual.concentration,
            "x": qual.k, "y": qual.k, "xr": 1, "yr": 1,
            "use_noc_latency": 0,
            "routing_function": _FLATFLY_MIN_ROUTING_FUNCTION,
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

    schedule = trace_schedule(parents.physical_traffic)
    values["traffic"] = f"trace({TRACE_FILE})"
    values["sample_period"] = schedule["sample_period"]
    values["max_samples"] = schedule["max_samples"]
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

Rationale: docs/decisions/modules/backend.md
    """
    expected_packets = sum(len(m.packets) for m in physical_traffic.traffic)
    if expected_packets <= 0:
        raise BookSimProjectionError(
            "a trace-driven execution requires a non-empty trace")
    max_timestamp = expected_packets - 1
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

Rationale: docs/decisions/modules/backend.md
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
    traffic = getattr(parents, "physical_traffic", None)
    if traffic is not None:
        trace_classes = trace_class_map(traffic)
        if len(trace_classes) != 1:
            raise SemanticLoss(
                "UNSUPPORTED: the single-class AnyNet profile executes ONE "
                "traffic class (config pins classes = 1); this workload "
                "declares "
                f"{sorted(trace_classes)} — the multi-class profile owns "
                "this traffic")
    exact, reason = vc_exactness(parents.vc_resource)
    if not exact:
        raise SemanticLoss(f"UNSUPPORTED: {reason}")
    if parents.vc_resource.allowed_transitions != tuple(
            (vc, vc) for vc in parents.vc_resource.vc_ids):
        raise SemanticLoss(
            "UNSUPPORTED: the certified profile executes identity VC "
            "transitions only")
    _refuse_unbound_escape(parents, "anynet-min-hops")

    latencies = {c.latency_cycles for c in parents.topology.channels}
    if min(latencies, default=0) < 1:
        raise SemanticLoss(
            "UNSUPPORTED: certified BookSim requires channel latency >= 1 "
            f"cycle, got {sorted(latencies)}")
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
            "would render as AnyNet lanes that this profile cannot pin, so "
            "the extra lanes would idle unused")

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

@dataclass(frozen=True)
class PreparedBookSimInput:
    """Deterministic, content-addressed BookSim input.

Rationale: docs/decisions/modules/backend.md
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
    expected_flits: int = 0
    trace_class_map: tuple[str, ...] = ()
    expected_flits_by_class: tuple[tuple[str, int], ...] = ()
    expected_route_rows: tuple[tuple[int, int, int], ...] = ()
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
            **({"trace_class_map": list(self.trace_class_map),
                "expected_flits_by_class": [list(p) for p in
                                            self.expected_flits_by_class]}
               if self.trace_class_map else {}),
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
    """Multi-class mesh DOR, single-class mesh DOR, concentrated, AnyNet.

Rationale: docs/decisions/modules/backend.md
    """
    _sel_traffic = getattr(parents, "physical_traffic", None)
    _sel_classes = len(trace_class_map(_sel_traffic)) \
        if _sel_traffic is not None else 0
    if _sel_classes >= 2:
        try:
            qualify_native_mesh_dor_mc(parents)
        except SemanticLoss as mc_exc:
            raise SemanticLoss(
                "UNSUPPORTED: no certified multi-class profile accepts "
                "this design; the multi-class mesh profile refuses: "
                f"{mc_exc}; the concentrated-mesh and AnyNet profiles "
                "execute ONE traffic class only") from mc_exc
        return MESH_DOR_MC_PROFILE
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
            qualify_native_torus_dor(parents)
        except SemanticLoss:
            pass
        else:
            return TORUS_DOR_PROFILE
        try:
            qualify_native_flatfly_min(parents)
        except SemanticLoss:
            pass
        else:
            return FLATFLY_MIN_PROFILE
        # AnyNet renders the materialized graph. For a family whose
        # materialization is a real graph (explicit 4x4 -> 24 edges;
        # gec_express -> 48 edges, degree 6 = row+column express), this
        # simulates THAT topology correctly; the fidelity gap is the
        # ROUTING (generic min-hop vs the family's native function such as
        # dor_gec), which ANYNET_PROFILE's audit records. It is not a
        # different network, so it must not be refused here — refusing
        # would withdraw working capability to fix nothing.
        try:
            qualify_anynet_min_hops(parents)
        except SemanticLoss as anynet_exc:
            raise SemanticLoss(
                f"{native_exc}; the AnyNet fallback also refuses: "
                f"{anynet_exc}") from native_exc
        return ANYNET_PROFILE
    return MESH_DOR_PROFILE

def _require_representable_links(parents: BookSimProjectionParents,
                                 profile: BookSimProfile) -> None:
    """Refuse a fabric whose links this profile cannot honor.

    The profiles here build point-to-point links only, so a shared wire (a
    bus) has no representation and must not be silently dropped. The native
    profiles additionally assume a symmetric fabric, so a one-way channel
    graph on one of those would be flattened into a different network.
    """
    shared = getattr(parents.topology, "shared_links", ())
    if shared:
        raise BookSimProjectionError(
            f"UNSUPPORTED: the topology declares {len(shared)} shared "
            "wire(s) (a bus); the BookSim profiles build point-to-point "
            "links only, so the bus would be silently dropped. Refusing.")
    pairs = {(c.src_router, c.dst_router) for c in parents.topology.channels}
    if profile.profile_id != _ANYNET_PROFILE_ID and \
            any((b, a) not in pairs for (a, b) in pairs):
        raise BookSimProjectionError(
            f"UNSUPPORTED: profile {profile.profile_id} assumes a symmetric "
            "fabric, but the channel graph has one-way links; refusing "
            "rather than flattening direction")

def prepare_booksim_input(parents: BookSimProjectionParents, *,
                          seed: int = 0) -> PreparedBookSimInput:
    """Project canonical artifacts into a deterministic prepared input."""
    if not isinstance(parents, BookSimProjectionParents):
        raise BookSimProjectionError(
            "parents must be a BookSimProjectionParents")
    if type(seed) is not int or isinstance(seed, bool) or seed < 0:
        raise BookSimProjectionError("seed must be a non-negative int")
    profile = select_booksim_profile(parents)
    _require_representable_links(parents, profile)
    conservation = verify_trace_conservation(parents.physical_traffic)
    config = render_config(parents, profile, include_optional=True, seed=seed)
    rendered = parse_config_values(config.decode())
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
    from veritx_dse.backend.route_observation import expected_route_rows
    if profile.profile_id in (_MESH_DOR_PROFILE_ID, _ML_DOR_PROFILE_ID):
        routing_class = DOR_XY
        node_to_router = {n: n
                          for n in range(parents.topology.router_count)}
    elif profile.profile_id == _TORUS_DOR_PROFILE_ID:
        routing_class = DOR_TORUS_XY
        node_to_router = {n: n
                          for n in range(parents.topology.router_count)}
    elif profile.profile_id == _FLATFLY_MIN_PROFILE_ID:
        routing_class = FLATFLY_MIN
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
        lowerer_version=(_ML_DOR_LOWERER_VERSION
                         if profile.profile_id == _ML_DOR_PROFILE_ID
                         else (_MESH_DOR_LOWERER_VERSION
                               if profile.profile_id == _MESH_DOR_PROFILE_ID
                               else (_CMESH_DOR_LOWERER_VERSION
                                     if profile.profile_id \
                                     == _CMESH_DOR_PROFILE_ID
                                     else (_TORUS_DOR_LOWERER_VERSION
                                           if profile.profile_id \
                                           == _TORUS_DOR_PROFILE_ID
                                           else (_FLATFLY_MIN_LOWERER_VERSION
                                                 if profile.profile_id \
                                                 == _FLATFLY_MIN_PROFILE_ID
                                                 else "ANYNET/1"))))),
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
        trace_class_map=(trace_class_map(pt)
                         if profile.profile_id == _ML_DOR_PROFILE_ID
                         else ()),
        expected_flits_by_class=(tuple(
            sorted(conservation["flits_by_class"].items()))
            if profile.profile_id == _ML_DOR_PROFILE_ID else ()),
        expected_route_rows=route_rows,
        seed=seed)

def prepare_min_adapt_input(parents: BookSimProjectionParents, selection,
                            qualification, esc_resource, *, seed: int = 0
                            ) -> PreparedBookSimInput:
    """Project a qualified MIN_ADAPT_MESH selection into prepared input.

Rationale: docs/decisions/modules/backend.md
    """
    if not isinstance(parents, BookSimProjectionParents):
        raise BookSimProjectionError(
            "parents must be a BookSimProjectionParents")
    if type(seed) is not int or isinstance(seed, bool) or seed < 0:
        raise BookSimProjectionError("seed must be a non-negative int")
    profile = MIN_ADAPT_MESH_PROFILE
    qualify_min_adapt_mesh(parents, selection, qualification, esc_resource)
    conservation = verify_trace_conservation(parents.physical_traffic)
    config = render_config(parents, profile, include_optional=True,
                           seed=seed)
    rendered = parse_config_values(config.decode())
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
                f"rendered {name}={rendered.get(name)!r} does not equal "
                f"the profile pin {pin!r}")
    if "routing_dump_file" in rendered:
        raise BookSimProjectionError(
            "min_adapt prepared input must not render a route-dump path: "
            "candidate-set routing aborts deterministic dumps")
    pt = parents.physical_traffic
    schedule = trace_schedule(pt)
    multi = len(trace_class_map(pt)) >= 2
    return PreparedBookSimInput(
        profile_id=profile.profile_id,
        semantics_version=profile.semantics_version,
        lowerer_version=_MIN_ADAPT_LOWERER_VERSION,
        config_text=config.decode(), topology_text=None,
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
        trace_class_map=(trace_class_map(pt) if multi else ()),
        expected_flits_by_class=(tuple(
            sorted(conservation["flits_by_class"].items()))
            if multi else ()),
        expected_route_rows=(),
        seed=seed)

def assert_canonical_min_adapt_projection(
        prepared: PreparedBookSimInput,
        parents: BookSimProjectionParents, selection,
        qualification, esc_resource) -> None:
    """Re-prove a min_adapt prepared input (tamper refusal)."""
    rebuilt = prepare_min_adapt_input(
        parents, selection, qualification, esc_resource, seed=prepared.seed)
    if rebuilt.prepared_id() != prepared.prepared_id():
        raise BookSimProjectionError(
            "prepared input does not match a fresh min_adapt projection "
            "of these canonical parents (tampered or transplanted "
            "artifact)")

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
    "CONFIG_FILE", "CONFIG_KEY_ORDER", "ConfigRead",
    "FLATFLY_MIN_PROFILE", "FlatflyMinQualification",
    "MESH_DOR_PROFILE", "MIN_ADAPT_MESH_PROFILE",
    "MeshDorQualification", "ParameterOwner", "PreparedBookSimInput",
    "ROUTE_DUMP_FILE", "SemanticLoss", "TOPOLOGY_FILE", "TRACE_FILE",
    "TORUS_DOR_PROFILE", "TRACE_SCHEDULE_VERSION",
    "TorusDorQualification",
    "assert_canonical_booksim_projection",
    "assert_canonical_min_adapt_projection",
    "compare_route_realization", "parse_config_values",
    "prepare_booksim_input", "prepare_min_adapt_input",
    "qualify_anynet_min_hops", "qualify_min_adapt_mesh",
    "qualify_native_cmesh_dor", "qualify_native_flatfly_min",
    "qualify_native_mesh_dor", "qualify_native_torus_dor",
    "render_anynet_topology", "render_config",
    "render_trace", "select_booksim_profile", "source_audit_report",
    "trace_class_map",
    "trace_injection_horizon", "trace_schedule", "vc_exactness",
    "verify_trace_conservation",
]
