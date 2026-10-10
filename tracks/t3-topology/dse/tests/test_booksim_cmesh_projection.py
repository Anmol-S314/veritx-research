"""Exact native terminal binding and dirty-tree source diagnostics.

These runs do not qualify a simulator or replace the pinned binary.
"""
from __future__ import annotations

import json
import re
import sys
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

DSE = Path(__file__).parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.backend.booksim_projection import (  # noqa: E402
    CMESH_DOR_PROFILE,
    BookSimProjectionParents,
    SemanticLoss,
    prepare_booksim_input,
    qualify_native_cmesh_dor,
    select_booksim_profile,
    source_audit_report,
)
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.model.compile_model import CompileRequestV3  # noqa: E402
from veritx_dse.model.topology_artifact import (  # noqa: E402
    MaterializedFamily,
)
from veritx_dse.model.vc_resource import (  # noqa: E402
    vc_resources_from_assignment,
)
from veritx_dse.workload.intent_lowering import (  # noqa: E402
    lower_compile_workload,
)
from veritx_dse.workload.messages import LogicalMessageArtifactV2  # noqa: E402
from veritx_dse.workload.traffic import (  # noqa: E402
    PhysicalTrafficArtifactV2,
)

EXAMPLE = REPO / "tracks/t3-topology/examples/dense_4b_32tiles_conc4-v3.json"

def _cmesh_parents(tmp_path: Path, concentration=4) -> BookSimProjectionParents:
    doc = json.loads(EXAMPLE.read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    if concentration == 2:
        doc["noc_config"]["concentration"] = 2
        # Full occupancy: 32 agents, 4x4 routers with two local ports each.
        doc["agents"] = doc["agents"][:1]
    request = CompileRequestV3.from_dict(doc)
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    bundle = compilation.bundle
    lowered = lower_compile_workload(request)
    logical = LogicalMessageArtifactV2(
        graph=lowered.graph, traffic_class=lowered.unified_traffic_class)
    physical = PhysicalTrafficArtifactV2(
        logical=logical, resolved_fabric=bundle.resolved_fabric,
        mapping=bundle.mapping, attachment=bundle.attachment,
        inventory=bundle.inventory, packet_format=bundle.packet_format)
    return BookSimProjectionParents(
        resolved_fabric=bundle.resolved_fabric, topology=bundle.topology,
        attachment=bundle.attachment, mapping=bundle.mapping,
        vc_resource=vc_resources_from_assignment(bundle.vc_assignment),
        vc_assignment=bundle.vc_assignment,
        packet_format=bundle.packet_format, route=bundle.router_route,
        physical_traffic=physical)

@pytest.fixture(scope="module")
def parents(tmp_path_factory) -> BookSimProjectionParents:
    return _cmesh_parents(tmp_path_factory.mktemp("cmesh"))

def test_cmesh_profile_source_audit_is_clean():
    report = source_audit_report(
        CMESH_DOR_PROFILE, source_root=REPO / "third_party/booksim2/src")
    assert report["clean"], report["missing_from_source"]
    src = (REPO / "third_party/booksim2/src/networks/cmesh.cpp").read_text()
    assert '"dor_no_express_cmesh"' in src
    assert '"cmesh"' in (
        REPO / "third_party/booksim2/src/networks/network.cpp").read_text()

def test_concentrated_mesh_qualifies_and_reports_canonical_facts(parents):
    qual = qualify_native_cmesh_dor(parents)
    assert qual.k == 3
    assert qual.concentration == 4
    assert qual.router_count == 9
    assert qual.endpoint_count == 36
    assert parents.topology.family is MaterializedFamily.CONCENTRATED_MESH


def test_sparse_concentration_two_refuses_without_padding(tmp_path):
    doc = json.loads(EXAMPLE.read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    doc["noc_config"] = dict(doc["noc_config"])
    doc["noc_config"]["concentration"] = 2
    request = CompileRequestV3.from_dict(doc)
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    bundle = compilation.bundle
    assert bundle is not None
    assert bundle.topology.family is MaterializedFamily.CONCENTRATED_MESH
    assert {router.seat_capacity for router in bundle.topology.routers} == {2}

    lowered = lower_compile_workload(request)
    logical = LogicalMessageArtifactV2(
        graph=lowered.graph, traffic_class=lowered.unified_traffic_class)
    physical = PhysicalTrafficArtifactV2(
        logical=logical, resolved_fabric=bundle.resolved_fabric,
        mapping=bundle.mapping, attachment=bundle.attachment,
        inventory=bundle.inventory, packet_format=bundle.packet_format)
    parents = BookSimProjectionParents(
        resolved_fabric=bundle.resolved_fabric, topology=bundle.topology,
        attachment=bundle.attachment, mapping=bundle.mapping,
        vc_resource=vc_resources_from_assignment(bundle.vc_assignment),
        vc_assignment=bundle.vc_assignment,
        packet_format=bundle.packet_format, route=bundle.router_route,
        physical_traffic=physical)
    with pytest.raises(SemanticLoss, match="full immutable terminal bindings"):
        qualify_native_cmesh_dor(parents)

def test_selector_picks_cmesh_for_concentrated_mesh(parents):
    assert select_booksim_profile(parents) is CMESH_DOR_PROFILE

def test_mesh_profile_still_refuses_concentration_for_its_own_reason(
        parents):
    from veritx_dse.backend.booksim_projection import qualify_native_mesh_dor
    with pytest.raises(SemanticLoss, match="seat_capacity 1"):
        qualify_native_mesh_dor(parents)

def _family_parents(tmp_path: Path, family: str) -> BookSimProjectionParents:
    doc = json.loads(
        (REPO / "tracks/t3-topology/examples/dense_1b_16tiles-v3.json")
        .read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    doc["noc_config"] = dict(doc["noc_config"])
    doc["noc_config"].update(
        {"topology_family": family, "radix": None, "concentration": None})
    request = CompileRequestV3.from_dict(doc)
    compilation = FabricCompiler().compile(request)
    if compilation.status != "COMPILED" or compilation.bundle is None:
        pytest.skip(f"{family} does not compile: {compilation.error}")
    bundle = compilation.bundle
    lowered = lower_compile_workload(request)
    logical = LogicalMessageArtifactV2(
        graph=lowered.graph, traffic_class=lowered.unified_traffic_class)
    physical = PhysicalTrafficArtifactV2(
        logical=logical, resolved_fabric=bundle.resolved_fabric,
        mapping=bundle.mapping, attachment=bundle.attachment,
        inventory=bundle.inventory, packet_format=bundle.packet_format)
    return BookSimProjectionParents(
        resolved_fabric=bundle.resolved_fabric, topology=bundle.topology,
        attachment=bundle.attachment, mapping=bundle.mapping,
        vc_resource=vc_resources_from_assignment(bundle.vc_assignment),
        vc_assignment=bundle.vc_assignment,
        packet_format=bundle.packet_format, route=bundle.router_route,
        physical_traffic=physical)

def test_mesh_fabric_still_selects_the_mesh_profile(tmp_path):
    assert select_booksim_profile(
        _family_parents(tmp_path, "mesh")
    ).profile_id == "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1"

def test_prepared_input_binds_cmesh_semantics_and_route_rows(parents):
    prepared = prepare_booksim_input(parents, seed=0)
    assert prepared.profile_id == "CERTIFIED_BOOKSIM_CMESH_DOR_XY_V1"
    assert prepared.semantics_version == (
        "booksim2-fork+cmesh-terminal-bijection+prepared-v2")
    assert prepared.lowerer_version == "DORXY/1"
    assert len(prepared.expected_route_rows) == \
        parents.topology.router_count * parents.topology.router_count * 4
    config = prepared.config_text
    for needle in ("topology = cmesh;", "k = 3;", "c = 4;",
                   "xr = 2;", "yr = 2;", "use_noc_latency = 0;",
                   "routing_function = dor_no_express;",
                   "routing_dump_file = routing.dump;"):
        assert needle in config, needle
    rows = {(src, node): nxt
            for src, node, nxt in prepared.expected_route_rows}
    assert rows[(0, 0)] == 0
    assert rows[(8, 35)] == 8
    assert rows[(0, 35)] == 1
    again = prepare_booksim_input(parents, seed=0)
    assert again.prepared_id() == prepared.prepared_id()
    assert prepare_booksim_input(parents, seed=1).prepared_id() \
        != prepared.prepared_id()

def test_tampered_route_refuses_preparation(parents):
    """A route artifact that does not cover the fabric must refuse, never
    become an uncheckable expectation."""
    import copy
    from veritx_dse.backend.booksim_projection import (
        BookSimProjectionParents as P,
    )
    from veritx_dse.core.route_artifact import RouteArtifactError
    broken = copy.copy(parents.route)
    object.__setattr__(broken, "entries", dict(parents.route.entries))
    victim = next(iter(broken.entries))
    del broken.entries[victim]
    with pytest.raises(Exception) as excinfo:
        prepare_booksim_input(
            P(resolved_fabric=parents.resolved_fabric,
              topology=parents.topology, attachment=parents.attachment,
              mapping=parents.mapping, vc_resource=parents.vc_resource,
              vc_assignment=parents.vc_assignment,
              packet_format=parents.packet_format, route=broken,
              physical_traffic=parents.physical_traffic),
            seed=0)
    assert "RouteArtifact" in str(excinfo.value) or \
        "no entry" in str(excinfo.value).lower() or \
        RouteArtifactError.__name__ in type(excinfo.value).__name__

@pytest.fixture(scope="module")
def source_binary(tmp_path_factory):
    if shutil.which("make") is None or shutil.which("g++") is None:
        pytest.skip("source diagnostic requires make and g++")
    build = tmp_path_factory.mktemp("cmesh-build") / "src"
    shutil.copytree(REPO / "third_party/booksim2/src", build,
                    ignore=shutil.ignore_patterns("*.o", "*.d", "booksim",
                                                 "booksim.build-manifest.json", "libveritx_embed.a"))
    subprocess.run(["make", "-j2"], cwd=build, check=True,
                   capture_output=True, text=True, timeout=600)
    return build / "booksim"


@pytest.mark.parametrize("concentration", [2, 4])
def test_source_diagnostic_mapping_routes_and_conservation(concentration, source_binary, tmp_path):
    from veritx_dse.backend.booksim_execution import execute_prepared_booksim
    parents = _cmesh_parents(tmp_path, concentration)
    prepared = prepare_booksim_input(parents)
    from veritx_dse.backend.cmesh_terminal_map import cmesh_terminal_map
    mapping = cmesh_terminal_map(parents.attachment,
        k=qualify_native_cmesh_dor(parents).k, concentration=concentration)
    assert prepared.cmesh_terminal_mapping == mapping.bindings
    record = execute_prepared_booksim(
        prepared=prepared, binary=source_binary, run_dir=tmp_path / "run",
        timeout=300, repo_root=REPO, allow_unqualified_profile=True)
    assert record.evidence.execution_fidelity == "DIAGNOSTIC_UNQUALIFIED_PROFILE"
    assert record.evidence.stats["flits_injected"] == prepared.expected_flits
    assert record.evidence.stats["flits_accepted"] == prepared.expected_flits
    assert record.evidence.route_observation == "EXECUTED_ROUTE_OBSERVED"
    # First-hop equality alone misses wrong local seats. Check actual native
    # ejection ports over the complete terminal universe, including idle seats.
    ejections = {(int(r), int(n)): (int(next_router), int(port))
                 for r, n, next_router, port in re.findall(
                     r"src_router (\d+) dst_node (\d+) next_router (\d+) port (\d+)",
                     (tmp_path / "run" / "routing.dump").read_text())}
    for _, node, router, port in mapping.bindings:
        assert ejections[(router, node)] == (router, port)


@pytest.mark.parametrize("config_change,reason", [
    (("xr = 1;", "xr = 2;"), "source-derived"),
    (("c = 2;", "c = 3;"), "supports c"),
    (("n = 2;", "n = 3;"), "requires n = 2"),
    (("x = 4;", "x = 5;"), "requires x = y = k"),
    (("routing_function = dor_no_express;", "routing_function = dor;"), "dor_no_express only"),
])
def test_native_c2_refuses_unsupported_geometry_and_routing(config_change, reason, source_binary, tmp_path):
    prepared = prepare_booksim_input(_cmesh_parents(tmp_path, 2))
    run = tmp_path / "bad"
    replace(prepared, config_text=prepared.config_text.replace(*config_change)).prepare_directory(run)
    proc = subprocess.run([str(source_binary), "config.cfg"], cwd=run,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode != 0
    assert reason in proc.stdout + proc.stderr


def test_product_assessment_does_not_qualify_changed_cmesh_semantics(tmp_path):
    from veritx_dse.product.service import ProductConfig, ProductService
    from veritx_dse.application.booksim_qualification_registry import qualification_of
    assert not qualification_of(CMESH_DOR_PROFILE.profile_id).is_qualified
    from veritx_dse.backend.router_controls import CONTROLLED_SUFFIX
    from veritx_dse.application.booksim_qualification_registry import withdrawn_capability_reason
    controlled = CMESH_DOR_PROFILE.profile_id + CONTROLLED_SUFFIX
    assert not qualification_of(controlled).is_qualified
    assert "terminal bijection" in withdrawn_capability_reason(controlled)
    svc = ProductService(ProductConfig(projects_root=tmp_path))
    doc = json.loads(EXAMPLE.read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    request = CompileRequestV3.from_dict(doc)
    assessment = svc._assess_compilation(request, FabricCompiler().compile(request))
    assert assessment["readiness"] == "BLOCKED"


@pytest.mark.parametrize("concentration,k,expected", [(2, 4, (1, 4)), (4, 3, (2, 6))])
def test_exact_terminal_bijection_preserves_every_packet(concentration, k, expected, tmp_path):
    from veritx_dse.backend.cmesh_terminal_map import cmesh_terminal_map
    from veritx_dse.backend.booksim_projection import render_trace, verify_trace_conservation
    parents = _cmesh_parents(tmp_path, concentration)
    mapping = cmesh_terminal_map(parents.attachment, k=k, concentration=concentration)
    assert expected in tuple((e, n) for e, n, _, _ in mapping.bindings)
    assert all(mapping.node_to_seat(n) == (r, p) for _, n, r, p in mapping.bindings)
    prepared = prepare_booksim_input(parents)
    assert f"c = {concentration};" in prepared.config_text
    assert f"xr = {concentration // 2};" in prepared.config_text
    assert "yr = 2;" in prepared.config_text
    assert prepared.physical_traffic_id == parents.physical_traffic.physical_traffic_id()
    raw = render_trace(parents.physical_traffic)
    mapped = render_trace(parents.physical_traffic, mapping)
    assert raw != mapped
    assert prepared.trace_text.encode() == mapped
    nodes = mapping.endpoint_to_node()
    for canonical, native in zip(raw.decode().splitlines(), mapped.decode().splitlines()):
        t, src, cl, dst, size = map(int, canonical.split())
        assert list(map(int, native.split())) == [t, nodes[src], cl, nodes[dst], size]
    assert verify_trace_conservation(parents.physical_traffic, mapping)["flits_total"] == prepared.expected_flits
    assert replace(prepared, cmesh_terminal_mapping=()).prepared_id() != prepared.prepared_id()


@pytest.mark.parametrize("tamper", ["duplicate", "endpoint", "seat", "geometry", "missing", "range"])
def test_terminal_mapping_counterexamples_refuse(tamper, tmp_path):
    from veritx_dse.backend.cmesh_terminal_map import cmesh_terminal_map, CMeshTerminalMapError
    parents = _cmesh_parents(tmp_path, 2)
    mapping = cmesh_terminal_map(parents.attachment, k=4, concentration=2)
    rows = list(mapping.bindings)
    e, node, router, port = rows[0]
    if tamper == "duplicate":
        rows[0] = (e, rows[1][1], router, port)
    elif tamper == "endpoint":
        rows[0] = (rows[1][0], node, router, port)
    elif tamper == "seat":
        rows[0] = (e, node, router, 1)
    elif tamper == "missing":
        rows.pop()
    elif tamper == "range":
        rows[0] = (e, 32, router, port)
    with pytest.raises(CMeshTerminalMapError):
        replace(mapping, bindings=tuple(rows), k=3 if tamper == "geometry" else 4)


@pytest.mark.parametrize("column", [0, 1, 2, 3, 4])
def test_trace_row_tampering_refuses_even_with_same_aggregate(column, parents, monkeypatch):
    from veritx_dse.backend import booksim_projection as bp
    from veritx_dse.backend.cmesh_terminal_map import cmesh_terminal_map
    mapping = cmesh_terminal_map(parents.attachment, k=3, concentration=4)
    lines = bp.render_trace(parents.physical_traffic, mapping).decode().splitlines()
    first = lines[0].split()
    first[column] = str(int(first[column]) + 1)
    lines[0] = " ".join(first)
    bp._TRACE_CONSERVATION_CACHE.clear()
    monkeypatch.setattr(bp, "render_trace", lambda *_args: ("\n".join(lines) + "\n").encode())
    with pytest.raises(bp.BookSimProjectionError, match="timestamp|binding"):
        bp.verify_trace_conservation(parents.physical_traffic, mapping)
