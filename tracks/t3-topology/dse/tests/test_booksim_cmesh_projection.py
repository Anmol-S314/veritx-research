"""PHASE 2 — the certified concentrated-mesh BookSim profile.

`CERTIFIED_BOOKSIM_CMESH_DOR_XY_V1` closes the last shipped dense
workload: a canonical CONCENTRATED_MESH fabric with uniform seat
capacity 4 executes natively through the vendored fork's
``dor_no_express_cmesh`` function — no route-class substitution, no
seat flattening, no second topology construction.

Every test here derives its expectation from the canonical artifacts
and the fork's own addressing law (networks/cmesh.cpp:
``NodeToRouter`` / ``NodeToPort``); nothing is hardcoded from a run.
The live equivalence test executes the REAL binary and refuses if the
executed first-hop table diverges from the canonical route.
"""
from __future__ import annotations

import json
import sys
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


def _conc4_parents(tmp_path: Path) -> BookSimProjectionParents:
    doc = json.loads(EXAMPLE.read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
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
    return _conc4_parents(tmp_path_factory.mktemp("cmesh"))


# ══ source audit: the profile's surface exists in the vendored fork ══

def test_cmesh_profile_source_audit_is_clean():
    report = source_audit_report(
        CMESH_DOR_PROFILE, source_root=REPO / "third_party/booksim2/src")
    assert report["clean"], report["missing_from_source"]
    # the fork really registers the composed routing key
    src = (REPO / "third_party/booksim2/src/networks/cmesh.cpp").read_text()
    assert '"dor_no_express_cmesh"' in src
    assert '"cmesh"' in (
        REPO / "third_party/booksim2/src/networks/network.cpp").read_text()


# ══ qualification: every clause proven, refusals typed ════════════════

def test_concentrated_mesh_qualifies_and_reports_canonical_facts(parents):
    qual = qualify_native_cmesh_dor(parents)
    assert qual.k == 3
    assert qual.concentration == 4
    assert qual.router_count == 9
    assert qual.endpoint_count == 36
    assert parents.topology.family is MaterializedFamily.CONCENTRATED_MESH


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


# ══ prepared input: identity binds the profile, config, and routes ════

def test_prepared_input_binds_cmesh_semantics_and_route_rows(parents):
    prepared = prepare_booksim_input(parents, seed=0)
    assert prepared.profile_id == "CERTIFIED_BOOKSIM_CMESH_DOR_XY_V1"
    assert prepared.semantics_version == (
        "booksim2-fork+P2-cmesh-dor+prepared-v1")
    assert prepared.lowerer_version == "DORXY/1"
    # the fork's node universe: k*k*c = 9*4 = 36 nodes, each covered as
    # a (src_router, node) row from every router: 9 * 36 = 324 rows
    assert len(prepared.expected_route_rows) == \
        parents.topology.router_count * parents.topology.router_count * 4
    config = prepared.config_text
    for needle in ("topology = cmesh;", "k = 3;", "c = 4;",
                   "xr = 2;", "yr = 2;", "use_noc_latency = 0;",
                   "routing_function = dor_no_express;",
                   "routing_dump_file = routing.dump;"):
        assert needle in config, needle
    # the seated endpoint mapping: node 0 -> router 0, node 35 -> router 8
    rows = {(src, node): nxt
            for src, node, nxt in prepared.expected_route_rows}
    assert rows[(0, 0)] == 0
    assert rows[(8, 35)] == 8
    # a remote first hop crosses the real materialized channel set
    assert rows[(0, 35)] == 1  # router0 -> router1 (+x), then +y
    # prepared identity is deterministic and seed-sensitive
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
    # drop one entry: the route proof no longer covers the node universe
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


# ══ live executed-route equivalence (REAL binary, real run) ═══════════

def _booksim_binary() -> Path | None:
    try:
        from veritx_dse.simulation.booksim import find_booksim_bin
        return find_booksim_bin(REPO)
    except Exception:                                    # noqa: BLE001
        return None


def test_executed_first_hop_matches_canonical_route_end_to_end(
        parents, tmp_path):
    """THE acceptance proof: the vendored binary executes the certified
    prepared input and its dumped first-hop realization equals the
    canonical route expectation over the complete node universe."""
    binary = _booksim_binary()
    if binary is None:
        pytest.skip("no booksim binary built")
    prepared = prepare_booksim_input(parents, seed=0)
    run_dir = tmp_path / "cmesh-run"
    prepared.prepare_directory(run_dir)
    import subprocess
    proc = subprocess.run(
        [str(binary), "config.cfg"], cwd=run_dir, capture_output=True,
        text=True, timeout=300)
    assert proc.returncode == 0, (proc.stderr or "")[-400:]
    from veritx_dse.backend.booksim_execution import (
        assert_execution_gate, parse_booksim_stats,
    )
    stats = parse_booksim_stats(proc.stdout, proc.stderr)
    conservation = __import__(
        "veritx_dse.backend.booksim_projection",
        fromlist=["verify_trace_conservation"]
    ).verify_trace_conservation(parents.physical_traffic)
    assert_execution_gate(
        stats, expected_packets=prepared.expected_packets,
        expected_flits=prepared.expected_flits,
        require_conservation=True)
    dump_text = (run_dir / "routing.dump").read_text()
    from veritx_dse.backend.route_observation import (
        compare_route_realization,
    )
    result = compare_route_realization(
        expected_rows=prepared.expected_route_rows, dump_text=dump_text,
        routing_class="DOR_XY")
    assert result.pairs_compared == len(prepared.expected_route_rows)
    # and the conservation law the evaluator enforces held in this run too
    assert stats.get("packets_injected") == prepared.expected_packets or \
        stats.get("injected_trace_packets") == prepared.expected_packets


# ══ product-path closure: the shipped workload is simulatable again ═══

def test_product_assessment_reports_the_shipped_workload_simulatable(
        tmp_path):
    """`ProductService._assess_compilation` is the gate that previously
    refused this workload with a backend_profile reason; it must now
    report SUPPORTED through the cmesh profile."""
    import types

    from veritx_dse.application.product_evaluator import evaluate_product
    from veritx_dse.product.service import ProductConfig, ProductService
    svc = ProductService(ProductConfig(projects_root=tmp_path))
    doc = json.loads(EXAMPLE.read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    request = CompileRequestV3.from_dict(doc)
    compilation = FabricCompiler().compile(request)
    assessment = svc._assess_compilation(request, compilation)
    assert assessment["supported"] is True, assessment["reason"]
    assert assessment["domain"] is None
    binary = _booksim_binary()
    if binary is None:
        pytest.skip("no booksim binary built")
    product = evaluate_product(
        request, binary=binary, network_clock_hz=1_000_000, timeout_s=240,
        repo_root=REPO)
    assert product.status == "EVALUATED", product.reason
