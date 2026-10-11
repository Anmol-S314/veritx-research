"""Producer-bound native BookSim multicast diagnostic.

This profile accepts an authored single-flit HARDWARE_REPLICATION operation
whose replication point is its source router. A bounded local build record
binds the executable and required source inventory; it is not a signed or
independent build attestation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile

from veritx_dse.backend.booksim_projection import (
    MESH_DOR_PROFILE, parse_config_values, qualify_native_mesh_dor, render_config,
)
from veritx_dse.backend.native_booksim import NativeBookSimProcess
from veritx_dse.backend.router_controls import has_router_controls
from veritx_dse.core.artifact import FrozenMap, content_id, thaw
from veritx_dse.core.errors import EvidenceInvalid, InvalidInput, UnsupportedSemantics
from veritx_dse.core.paths import REPO
from veritx_dse.model.native_coupled import verify_pin
from veritx_dse.model.native_multicast import NativeMulticastConfig
from veritx_dse.model.vc_resource import vc_resources_from_assignment
from veritx_dse.model.mapping import MappingArtifact
from veritx_dse.workload.graph import KIND_MULTICAST, WorkloadGraph


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _native_mesh_dor_output_port(current: int, destination: int, k: int) -> int:
    """Mirror the pinned BookSim dim_order port choice for a 2-D mesh."""
    if current == destination:
        return 4  # dimension_order_mesh uses 2*gN as the local eject port
    for dimension, stride in enumerate((1, k)):
        coordinate = (current // stride) % k
        target = (destination // stride) % k
        if coordinate != target:
            return 2 * dimension + (0 if coordinate < target else 1)
    raise EvidenceInvalid("mesh DOR has no output direction before its destination")


def _validate_multicast_branch_path(route_trace, source: int, destination: int,
                                    *, bundle, qualification) -> None:
    """Bind every observed output, including destination eject, to the mesh route."""
    k = qualification.k
    eject_port = 2 * 2
    channel_by_id = {channel.channel_id: channel
                     for channel in bundle.topology.channels}
    routing_class = bundle.vc_assignment.vc_to_routing_class[0][1]
    current = source
    if not route_trace:
        raise EvidenceInvalid("native multicast branch has no observed route steps")
    for index, link in enumerate(route_trace):
        if (not isinstance(link, tuple) or len(link) != 2
                or type(link[0]) is not int or type(link[1]) is not int):
            raise EvidenceInvalid("native multicast route-trace output is malformed")
        router, output_port = link
        if router != current:
            raise EvidenceInvalid("native multicast route trace is not a continuous router path")
        expected_port = _native_mesh_dor_output_port(current, destination, k)
        if output_port != expected_port:
            raise EvidenceInvalid("native multicast output differs from the pinned mesh DOR route")
        if current == destination:
            if index != len(route_trace) - 1 or output_port != eject_port:
                raise EvidenceInvalid("native multicast branch has an illegal destination eject output")
            continue
        if output_port == eject_port:
            raise EvidenceInvalid("native multicast branch ejected before its destination")
        dimension, direction = divmod(output_port, 2)
        next_router = current + (1 if direction == 0 else -1) * (k ** dimension)
        if not 0 <= next_router < qualification.router_count:
            raise EvidenceInvalid("native multicast output leaves the qualified mesh bounds")
        channel_id = bundle.router_route.entries.get(
            (routing_class, current, destination))
        channel = channel_by_id.get(channel_id)
        if (channel is None or channel.src_router != current
                or channel.dst_router != next_router):
            raise EvidenceInvalid(
                "native multicast output disagrees with the compiled route channel")
        current = channel.dst_router
    if current != destination or route_trace[-1][1] != eject_port:
        raise EvidenceInvalid("native multicast branch does not end at its legal destination eject")


@dataclass(frozen=True)
class NativeMulticastRequest:
    """Exact MULTICAST semantic and compiled rank-to-router binding."""

    operation_id: str
    workload_id: str
    source_rank: int
    destination_ranks: tuple[int, ...]
    payload_bytes: int
    replication_point_rank: int
    traffic_class: str
    traffic_class_id: int
    source_router: int
    destination_routers: tuple[int, ...]
    topology_hash: str
    mapping_hash: str
    attachment_hash: str
    class_binding_hash: str

    def __post_init__(self):
        if (not isinstance(self.operation_id, str) or not self.operation_id
                or len(self.operation_id.encode("utf-8")) > 128):
            raise InvalidInput("native multicast operation identity must be bounded to 128 UTF-8 bytes")
        for name in ("workload_id", "traffic_class", "topology_hash", "mapping_hash",
                     "attachment_hash", "class_binding_hash"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise InvalidInput(f"native multicast {name} is required")
        if type(self.payload_bytes) is not int or self.payload_bytes < 1:
            raise InvalidInput("native multicast payload_bytes must be positive")
        for name in ("source_rank", "replication_point_rank", "traffic_class_id",
                     "source_router"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise InvalidInput(f"native multicast {name} must be a nonnegative int")
        if (not isinstance(self.destination_ranks, tuple)
                or not isinstance(self.destination_routers, tuple)
                or len(self.destination_ranks) < 2
                or len(self.destination_ranks) != len(self.destination_routers)
                or len(set(self.destination_ranks)) != len(self.destination_ranks)
                or len(set(self.destination_routers)) != len(self.destination_routers)):
            raise InvalidInput("native multicast destinations must be a paired unique fanout >= 2")
        if any(type(v) is not int or v < 0 for v in (*self.destination_ranks,
                                                       *self.destination_routers)):
            raise InvalidInput("native multicast destinations must be nonnegative ints")
        if self.source_rank in self.destination_ranks or self.source_router in self.destination_routers:
            raise InvalidInput("native multicast source cannot be a destination")
        if self.replication_point_rank != self.source_rank:
            raise UnsupportedSemantics(
                "native V1 supports only the explicitly authored source-router replication point")

    @classmethod
    def from_compiled(cls, compilation, graph: WorkloadGraph,
                      mapping: MappingArtifact, operation_id: str
                      ) -> "NativeMulticastRequest":
        """Bind graph intent to compiled ranks, traffic class and endpoints."""
        if not isinstance(graph, WorkloadGraph) or not isinstance(mapping, MappingArtifact):
            raise InvalidInput("explicit canonical workload and MappingArtifact are required")
        if mapping.rank_count != graph.participant_count:
            raise EvidenceInvalid("multicast workload/mapping participant cardinality differs")
        operations = [op for op in graph.operations if op.operation_id == operation_id]
        if len(operations) != 1 or operations[0].kind != KIND_MULTICAST:
            raise InvalidInput("native multicast operation id must name one compiled MULTICAST")
        op = operations[0]
        detail = op.detail
        if detail.get("replication") != "HARDWARE_REPLICATION":
            raise UnsupportedSemantics(
                "SOURCE_REPLICATION remains replicated unicast, not native multicast")
        if "replication_point" not in detail:
            raise InvalidInput("hardware multicast is missing its authored replication point")
        endpoint_by_instance = {
            endpoint.agent.instance_id: endpoint
            for endpoint in compilation.bundle.attachment.endpoints
        }
        placements = {placement.rank: placement.agent.instance_id
                      for placement in mapping.placements}
        ranks = (detail["source_rank"], *detail["destinations"],
                 detail["replication_point"])
        if any(rank not in placements for rank in ranks):
            raise InvalidInput("multicast rank lacks a compiled MappingArtifact placement")
        instances = [placements[rank] for rank in ranks]
        if any(instance not in endpoint_by_instance for instance in instances):
            raise UnsupportedSemantics("multicast rank maps to an unattached compute endpoint")
        class_rows = compilation.bundle.vc_assignment.traffic_class_to_vcs
        if len(class_rows) != 1:
            raise UnsupportedSemantics(
                "native multicast V1 supports one compiled traffic class mapped to BookSim class 0")
        traffic_class = class_rows[0][0]
        source, *destination_endpoints, replication = [
            endpoint_by_instance[instance] for instance in instances]
        if replication.router_id != source.router_id:
            raise UnsupportedSemantics(
                "native multicast V1 replication point must be the source endpoint router")
        return cls(
            operation_id=operation_id, workload_id=graph.workload_id(),
            source_rank=detail["source_rank"],
            destination_ranks=tuple(detail["destinations"]),
            payload_bytes=detail["payload_bytes"],
            replication_point_rank=detail["replication_point"],
            traffic_class=traffic_class, traffic_class_id=0,
            source_router=source.router_id,
            destination_routers=tuple(e.router_id for e in destination_endpoints),
            topology_hash=compilation.bundle.topology.topology_hash(),
            mapping_hash=mapping.mapping_hash(),
            attachment_hash=compilation.bundle.attachment.attachment_hash(),
            class_binding_hash=content_id(
                "veritx/NativeMulticastClassBinding/v1", {
                    "workload_id": graph.workload_id(),
                    "operation_id": operation_id,
                    "traffic_class": traffic_class, "traffic_class_id": 0,
                    "vc_assignment_hash": compilation.bundle.vc_assignment.vc_assignment_hash(),
                }))

    def to_dict(self) -> dict:
        return {field: (list(value) if isinstance(value, tuple) else value)
                for field in self.__dataclass_fields__
                for value in (getattr(self, field),)}


@dataclass(frozen=True)
class NativeMulticastEvidence:
    data: FrozenMap

    def artifact_id(self) -> str:
        return content_id("veritx/NativeMulticastEvidence/v1", self.data)

    def to_dict(self) -> dict:
        return {**thaw(self.data), "artifact_id": self.artifact_id()}

    @classmethod
    def from_dict(cls, doc: dict) -> "NativeMulticastEvidence":
        expected = {"type", "schema_version", "profile", "operation_id", "request",
                    "native", "branches", "conservation", "cycles", "scope",
                    "artifact_id"}
        if (not isinstance(doc, dict) or set(doc) != expected
                or doc.get("type") != "veritx/NativeMulticastEvidence"
                or doc.get("schema_version") != 1
                or not isinstance(doc.get("artifact_id"), str)):
            raise InvalidInput("malformed native multicast evidence envelope")
        data = {key: value for key, value in doc.items() if key != "artifact_id"}
        evidence = cls(FrozenMap(data))
        if evidence.artifact_id() != doc["artifact_id"]:
            raise EvidenceInvalid("native multicast evidence content hash mismatch")
        return evidence

    def revalidate(self, *, compilation, graph, mapping,
                   native_config, max_cycles=None):
        expected = execute_native_multicast(
            compilation, graph, mapping, self.data["operation_id"],
            native_config, max_cycles=max_cycles)
        if self != expected:
            raise EvidenceInvalid("native multicast evidence differs from fresh-engine replay")


_REQUIRED_BOOKSIM_SOURCE_INVENTORY = frozenset({
    "third_party/booksim2/src/flit.cpp",
    "third_party/booksim2/src/flit.hpp",
    "third_party/booksim2/src/routers/iq_router.cpp",
    "third_party/booksim2/src/routers/iq_router.hpp",
    "third_party/booksim2/src/veritx_embed.cpp",
    "third_party/booksim2/src/veritx_embed.hpp",
    "tracks/t3-topology/dse/backend/native_booksim_driver.cpp",
})


def _verify_booksim_inputs(config: NativeMulticastConfig) -> tuple[str, str, str]:
    """Verify the executable, source inventory and local build record."""
    executable_pin = config.files["booksim_executable"]
    source_manifest_pin = config.files["booksim_source_manifest"]
    build_pin = config.files["booksim_build_provenance"]
    for pin in (executable_pin, source_manifest_pin, build_pin):
        verify_pin(pin)
    executable = Path(executable_pin["path"])
    if executable.read_bytes()[:4] != b"\x7fELF":
        raise UnsupportedSemantics("native multicast requires the pinned ELF BookSim driver")
    manifest_path = Path(source_manifest_pin["path"])
    if manifest_path.stat().st_size > 2 * 1024 * 1024:
        raise InvalidInput("BookSim source manifest exceeds bound")
    manifest = json.loads(manifest_path.read_text())
    if (not isinstance(manifest, dict) or set(manifest) != {"files"}
            or not isinstance(manifest["files"], list)
            or not 1 <= len(manifest["files"]) <= 4096):
        raise InvalidInput("BookSim source manifest must pin a bounded file list")
    inventory = set()
    for pin in manifest["files"]:
        verify_pin(pin)
        path = Path(pin["path"]).as_posix()
        matches = set()
        for required in _REQUIRED_BOOKSIM_SOURCE_INVENTORY:
            if required.startswith("third_party/booksim2/"):
                relative = required.removeprefix("third_party/booksim2/")
                suffixes = ("/" + required, "/booksim2/" + relative)
            else:
                suffixes = ("/" + required, "/native_booksim_driver.cpp")
            if any(path.endswith(suffix) for suffix in suffixes):
                matches.add(required)
        if len(matches) > 1:
            raise InvalidInput("BookSim source manifest path ambiguously matches the canonical inventory")
        inventory.update(matches)
    missing = _REQUIRED_BOOKSIM_SOURCE_INVENTORY - inventory
    if missing:
        raise InvalidInput(
            "BookSim source manifest omits required multicast producer inputs: "
            + ", ".join(sorted(missing)))
    build_path = Path(build_pin["path"])
    if build_path.stat().st_size > 256 * 1024:
        raise InvalidInput("BookSim build provenance exceeds bound")
    build = json.loads(build_path.read_text())
    required_build_fields = {
        "schema_version", "scope", "booksim_executable_sha256",
        "booksim_source_manifest_sha256", "driver_sha256", "builder_sha256",
        "compiler", "make", "commands",
    }
    if (not isinstance(build, dict) or set(build) != required_build_fields
            or build["schema_version"] != 1
            or build["scope"] != "LOCAL_BUILD_RECORD_NOT_ATTESTATION"
            or build["booksim_executable_sha256"] != executable_pin["sha256"]
            or build["booksim_source_manifest_sha256"] != source_manifest_pin["sha256"]
            or not isinstance(build["driver_sha256"], str)
            or not isinstance(build["builder_sha256"], str)
            or not isinstance(build["commands"], list)
            or len(build["commands"]) != 2):
        raise EvidenceInvalid("BookSim binary/source pins do not match the build provenance")
    for tool_name in ("compiler", "make"):
        tool = build[tool_name]
        if (not isinstance(tool, dict)
                or set(tool) != {"path", "sha256", "version"}):
            raise InvalidInput(f"BookSim build record has malformed {tool_name} identity")
        verify_pin({"path": tool["path"], "sha256": tool["sha256"]})
        if not isinstance(tool.get("version"), str):
            raise InvalidInput(f"BookSim build record has no {tool_name} version")
    builder_pin = {"path": str(REPO / "scripts/build_native_coupled_diagnostic.py"),
                   "sha256": build["builder_sha256"]}
    verify_pin(builder_pin)
    commands = build["commands"]
    make_argv = commands[0].get("argv") if isinstance(commands[0], dict) else None
    compile_argv = commands[1].get("argv") if isinstance(commands[1], dict) else None
    if (make_argv != [build["make"]["path"], "-j1", "lib"]
            or not isinstance(compile_argv, list)
            or not compile_argv
            or compile_argv[0] != build["compiler"]["path"]
            or not any(str(arg).endswith("/native_booksim_driver.cpp")
                       for arg in compile_argv)
            or not any(str(arg).endswith("/veritx_embed.cpp")
                       for arg in compile_argv)
            or "-o" not in compile_argv
            or compile_argv[compile_argv.index("-o") + 1] != str(executable)):
        raise EvidenceInvalid("BookSim build commands do not describe the pinned producer")
    if build["driver_sha256"] not in {
            pin["sha256"] for pin in manifest["files"]
            if Path(pin["path"]).name == "native_booksim_driver.cpp"}:
        raise EvidenceInvalid("BookSim build driver is not present in the pinned source inventory")
    return (executable_pin["sha256"], source_manifest_pin["sha256"],
            build_pin["sha256"])


def execute_native_multicast(compilation, graph: WorkloadGraph,
                             mapping: MappingArtifact, operation_id: str,
                             native_config: NativeMulticastConfig, *,
                             max_cycles: int | None = None
                             ) -> NativeMulticastEvidence:
    """Execute and replay-check one actual BookSim source-router multicast."""
    from veritx_dse.application.fabric_compiler import Compilation
    if not isinstance(compilation, Compilation) or compilation.status != "COMPILED":
        raise InvalidInput("native multicast requires an explicitly compiled design")
    if not isinstance(native_config, NativeMulticastConfig):
        raise InvalidInput("native multicast requires explicit immutable producer pins")
    request = NativeMulticastRequest.from_compiled(
        compilation, graph, mapping, operation_id)
    root, bundle = compilation.compiled_system, compilation.bundle
    controls = bundle.design.noc_controls
    if (root.adaptive is not None or root.control_plane is not None
            or getattr(root.request, "sideband_interfaces", ())
            or getattr(root.request, "sideband_connections", ())
            or getattr(root.request, "power_domains", ())
            or getattr(root.request, "reset_channels", ())
            or has_router_controls(controls)
            or getattr(controls, "arbitration", None) is not None
            or getattr(controls, "rcu_enabled", None) is True
            or getattr(controls, "mcast_groups", None) is not None
            or getattr(controls, "mcast_setup_cycles", None) is not None):
        raise UnsupportedSemantics("native multicast V1 requires a plain single-plane default mesh")
    if request.traffic_class_id != 0 or bundle.vc_assignment.vc_count != 1:
        raise UnsupportedSemantics("native multicast requires one class and one identity-transition VC")
    packet_bytes = bundle.packet_format.flit_width_bits
    if packet_bytes % 8 or not 1 <= request.payload_bytes <= packet_bytes // 8:
        raise UnsupportedSemantics("native multicast V1 supports one flit of authored payload per destination")
    if len(request.destination_routers) > native_config.host_flit_limit:
        raise InvalidInput("multicast fanout exceeds the pinned native host-flit bound")
    exe_hash, source_manifest_hash, build_provenance_hash = \
        _verify_booksim_inputs(native_config)
    parents = type("NativeMulticastParents", (), {
        "topology": bundle.topology, "attachment": bundle.attachment,
        "vc_assignment": bundle.vc_assignment,
        "vc_resource": vc_resources_from_assignment(bundle.vc_assignment),
        "route": bundle.router_route, "physical_traffic": None,
        "source_bundle": bundle})()
    qualification = qualify_native_mesh_dor(parents)
    if any(router.coordinates != (router.router_id % qualification.k,
                                 router.router_id // qualification.k)
           for router in bundle.topology.routers):
        raise UnsupportedSemantics(
            "native mesh output ports require the compiled row-major BookSim router coordinates")
    if qualification.router_count > 64:
        raise UnsupportedSemantics("native multicast supports at most 64 routers")
    if any(router >= qualification.router_count for router in
           (request.source_router, *request.destination_routers)):
        raise InvalidInput("compiled multicast endpoint is outside the native mesh node set")
    config_bytes = render_config(
        parents, MESH_DOR_PROFILE,
        external_schedule={"sample_period": 1,
                          "max_samples": native_config.max_engine_steps,
                          "max_timestamp": native_config.max_engine_steps - 1})
    rendered = parse_config_values(config_bytes.decode("utf-8"))
    if (rendered.get("topology") != "mesh" or rendered.get("num_vcs") != "1"
            or rendered.get("classes") != "1" or rendered.get("n") != "2"
            or rendered.get("k") != str(qualification.k)
            or rendered.get("routing_function") != "dim_order"):
        raise UnsupportedSemantics("rendered BookSim multicast config differs from the one-class mesh envelope")
    config_hash = _sha(config_bytes)
    limit = max_cycles if max_cycles is not None else min(native_config.max_engine_steps, 100_000)
    if type(limit) is not int or not 1 <= limit <= native_config.max_engine_steps:
        raise InvalidInput("native multicast max_cycles exceeds the pinned engine-step bound")
    created = []
    retired = []
    cycles = 0
    with tempfile.TemporaryDirectory(prefix="veritx-native-mcast-") as directory:
        directory = Path(directory)
        config_path = directory / "network.config"
        config_path.write_bytes(config_bytes)
        # EmbedTM owns every injected event; BookSim's legacy config parser
        # still requires an inert trace file to initialize its TrafficManager.
        (directory / "workload.trace").write_text("")
        process = NativeBookSimProcess(
            native_config.files["booksim_executable"]["path"], config_path,
            native_config.host_flit_limit, directory)
        try:
            if process.num_nodes != qualification.router_count:
                raise EvidenceInvalid("native BookSim node count differs from compiled mesh")
            before = process.counts()
            pid = process.inject_multicast(
                request.operation_id, request.source_router,
                request.source_router, request.traffic_class_id,
                request.destination_routers)
            while pid is None:
                if cycles >= limit:
                    raise EvidenceInvalid("native multicast admission did not make bounded progress")
                cycles += 1
                process.step()
                for node in range(process.num_nodes):
                    created.extend(process.drain(node))
                pid = process.inject_multicast(
                    request.operation_id, request.source_router,
                    request.source_router, request.traffic_class_id,
                    request.destination_routers)
            while len(retired) < len(request.destination_routers):
                if cycles >= limit:
                    raise EvidenceInvalid("native multicast branches did not retire before the horizon")
                cycles += 1
                process.step()
                for node in range(process.num_nodes):
                    retired.extend(process.drain(node))
            after = process.counts()
            process.close()
        except BaseException:
            process.close(force=True)
            raise
    expected = set(request.destination_routers)
    seen: set[int] = set()
    branches = []
    for row in (*created, *retired):
        if row.operation_id != request.operation_id or row.pid != pid:
            raise EvidenceInvalid("native multicast retirement lost operation identity")
    for row in retired:
        if (not getattr(row, "multicast", False) or row.src != request.source_router
                or row.cl != request.traffic_class_id or row.dst not in expected
                or row.dst in seen or row.operation_id != request.operation_id):
            raise EvidenceInvalid("native multicast destination branch is missing, duplicate or misbound")
        if row.branch_id < 0 or row.branch_id >= len(request.destination_routers):
            raise EvidenceInvalid("native multicast branch ordinal is outside its authored set")
        if request.destination_routers[row.branch_id] != row.dst:
            raise EvidenceInvalid("native multicast branch ordinal differs from its authored destination")
        if row.route_steps != len(row.route_trace):
            raise EvidenceInvalid(
                "native multicast route-step count differs from the complete output trace")
        _validate_multicast_branch_path(
            row.route_trace, request.source_router, row.dst,
            bundle=bundle, qualification=qualification)
        if row.route_trace[-1][0] != row.dst:
            raise EvidenceInvalid("native multicast route trace does not terminate at its destination")
        physical_link_flits = len(row.route_trace) - 1
        if row.physical_link_flits != physical_link_flits:
            raise EvidenceInvalid(
                "native multicast physical-link count differs from the validated route trace")
        seen.add(row.dst)
        branches.append({"branch_id": row.branch_id, "destination_rank":
                         request.destination_ranks[row.branch_id], "destination_router": row.dst,
                         "retired_cycle": row.atime, "flits": 1,
                         "route_steps": row.route_steps,
                         "physical_link_flits": physical_link_flits,
                         "route_trace": [list(step) for step in row.route_trace]})
    if seen != expected or len(retired) != len(expected):
        raise EvidenceInvalid("native multicast did not deliver exactly once to every authored destination")
    branch_flits = len(request.destination_routers)
    physical_link_flits = sum(branch["physical_link_flits"] for branch in branches)
    if (after["packets"] - before["packets"] != 1
            or after["flits_retired"] - before["flits_retired"] != branch_flits
            or after["tails"] - before["tails"] != branch_flits
            or after["mcast_branch_flits_constructed"] - before["mcast_branch_flits_constructed"] != branch_flits
            or after["mcast_branch_flits_retired"] - before["mcast_branch_flits_retired"] != branch_flits
            or after["mcast_branch_physical_link_flits"]
            - before["mcast_branch_physical_link_flits"] != physical_link_flits
            or after["flits_live"] or after["flits_source_queued"]):
        raise EvidenceInvalid("native multicast branch/flit/link conservation failed to drain")
    return NativeMulticastEvidence(FrozenMap({
        "type": "veritx/NativeMulticastEvidence", "schema_version": 1,
        "profile": "NATIVE_MULTICAST_SOURCE_ROUTER_DIAGNOSTIC_V1",
        "operation_id": request.operation_id,
        "request": request.to_dict(),
        "native": {"booksim_executable_sha256": exe_hash,
                   "booksim_source_manifest_sha256": source_manifest_hash,
                   "booksim_build_provenance_sha256": build_provenance_hash,
                   "executable_source_relationship": "LOCAL_BUILD_RECORD_VERIFIED_NOT_ATTESTATION",
                   "booksim_config_sha256": config_hash,
                   "native_config_id": native_config.config_id()},
        "branches": sorted(branches, key=lambda row: row["branch_id"]),
        "conservation": {"authored_destinations": len(expected),
                         "branch_flits_constructed": branch_flits,
                         "branch_flits_retired": len(retired),
                         "all_flits_retired_delta": after["flits_retired"] - before["flits_retired"],
                         "tail_deliveries_delta": after["tails"] - before["tails"],
                         "physical_link_flits": physical_link_flits,
                         "observed_physical_link_flits": (
                             after["mcast_branch_physical_link_flits"]
                             - before["mcast_branch_physical_link_flits"]),
                         "drained": True},
        "cycles": cycles,
        "scope": {"execution": "NATIVE_DIAGNOSTIC_EXECUTED",
                  "replication_point": "AUTHORED_SOURCE_ROUTER",
                  "qualified": False, "calibrated": False,
                  "hardware_equivalence": False,
                  "executable_source_relationship": "LOCAL_BUILD_RECORD_VERIFIED_NOT_ATTESTATION",
                  "rcu": "NOT_REQUESTED"},
    }))


__all__ = ["NativeMulticastRequest", "NativeMulticastEvidence",
           "execute_native_multicast"]
