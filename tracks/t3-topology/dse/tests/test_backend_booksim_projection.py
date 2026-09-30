"""Canonical BookSim projection tests (Slice 31).

Proves: no legacy topology authority; deterministic, content-addressed
prepared input; per-parent identity binding; exact native mesh-DOR
qualification with refusal when a prerequisite fails; explicit AnyNet
projection; route-realization comparison; semantic-loss refusal; parent
tamper/transplant refusal; packet/flit conservation; and fail-closed
source drift.
"""
from __future__ import annotations

import dataclasses
import inspect
from pathlib import Path

import pytest

from test_canonical_compiler import (
    _anynet_policy, _det, _design, _vs,
)

from veritx_dse.backend import booksim_projection as bp
from veritx_dse.backend import source_audit
from veritx_dse.core.route_artifact import (
    ANYNET_MIN_HOPS, DOR_XY, RouteArtifactError,
)
from veritx_dse.model.compile_model import TopologyFamily
from veritx_dse.model.topology_artifact import MaterializedFamily, SharedLink
from veritx_dse.workload.graph import (
    KIND_COLLECTIVE, KIND_COMPUTE, KIND_MULTICAST, OperationNode,
    WorkloadGraph, collective_detail, compute_detail, multicast_detail,
)
from veritx_dse.workload.messages import LogicalMessageArtifactV2
from veritx_dse.workload.traffic import PhysicalTrafficArtifactV2

REPO = Path(__file__).resolve().parents[4]
BOOKSIM_SRC = REPO / "third_party" / "booksim2" / "src"

def _parents(*, compute=16, tp=16, family=TopologyFamily.MESH,
             ops=None, multicast=False, anynet=False):
    design = _design(compute=compute, tp=tp, family=family)
    compiled = (_det(design, policy=_anynet_policy(),
                     vc_spec=_vs(vc_to_routing_class=((0, ANYNET_MIN_HOPS),)))
                if anynet else _det(design))
    if ops is None:
        operations = [
            OperationNode(operation_id="pre", kind=KIND_COMPUTE,
                          detail=compute_detail(duration_ns=10000,
                                                participant_count=compute)),
            OperationNode(operation_id="ar", kind=KIND_COLLECTIVE,
                          deps=("pre",),
                          detail=collective_detail(
                              collective_kind="ALLREDUCE",
                              participants=tuple(range(compute)),
                              payload_bytes=1024,
                              participant_count=compute)),
        ]
        if multicast:
            operations.append(OperationNode(
                operation_id="m", kind=KIND_MULTICAST, deps=("ar",),
                detail=multicast_detail(
                    source_rank=0, destinations=(1, 2), payload_bytes=64,
                    replication="SOURCE_REPLICATION",
                    participant_count=compute)))
        ops = tuple(operations)
    graph = WorkloadGraph(parallelism=compiled.inventory.parallelism,
                          participant_count=compute, operations=ops)
    logical = LogicalMessageArtifactV2(graph=graph)
    traffic = PhysicalTrafficArtifactV2(
        logical=logical, resolved_fabric=compiled.resolved_fabric,
        mapping=compiled.mapping, attachment=compiled.attachment,
        inventory=compiled.inventory, packet_format=compiled.packet_format)
    parents = bp.BookSimProjectionParents(
        resolved_fabric=compiled.resolved_fabric, topology=compiled.topology,
        attachment=compiled.attachment, mapping=compiled.mapping,
        vc_resource=compiled.vc_resource,
        vc_assignment=compiled.routing.vc_assignment,
        packet_format=compiled.packet_format, route=compiled.routing.route,
        physical_traffic=traffic)
    return compiled, parents

def _stripped_source(module) -> str:
    import ast as _ast
    source = inspect.getsource(module)
    tree = _ast.parse(source)
    ranges = []
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Module, _ast.ClassDef, _ast.FunctionDef,
                             _ast.AsyncFunctionDef)) \
                and node.body \
                and isinstance(node.body[0], _ast.Expr) \
                and isinstance(node.body[0].value, _ast.Constant) \
                and isinstance(node.body[0].value.value, str):
            ranges.append((node.body[0].lineno, node.body[0].end_lineno))
    return "".join(
        line for number, line in enumerate(source.splitlines(keepends=True),
                                           start=1)
        if not any(low <= number <= high for low, high in ranges))

def test_projection_never_imports_legacy_topology_authority():
    source = _stripped_source(bp)
    for forbidden in ("model.presets", "presets import", "ResolvedFabricBundle",
                      "ParallelismArtifact", "OperationGraph",
                      "make_fabric_artifact", "simulation.booksim"):
        assert forbidden not in source, forbidden
    modules = {name for name in dir(bp) if not name.startswith("_")}
    assert "Topology" not in modules

def test_prepared_input_is_byte_identical_and_path_independent(tmp_path):
    _, parents = _parents()
    first = bp.prepare_booksim_input(parents, seed=0)
    second = bp.prepare_booksim_input(parents, seed=0)
    assert first.prepared_id() == second.prepared_id()
    a = first.prepare_directory(tmp_path / "a")
    b = second.prepare_directory(tmp_path / "b")
    for name in a:
        assert a[name].read_bytes() == b[name].read_bytes()
    assert "tmp" not in first.prepared_id()
    assert str(tmp_path) not in js_dump(first)

def js_dump(prepared) -> str:
    import json
    return json.dumps(prepared.identity_dict(), sort_keys=True)

def test_every_parent_moves_the_prepared_identity():
    _, base = _parents()
    reference = bp.prepare_booksim_input(base).prepared_id()
    other = _parents(compute=8, tp=8)[1]
    assert bp.prepare_booksim_input(other).prepared_id() != reference

    prepared = bp.prepare_booksim_input(base)
    doc = prepared.identity_dict()
    for key in ("topology_hash", "attachment_hash", "mapping_hash",
                "vc_resource_hash", "packet_format_hash",
                "route_artifact_hash", "resolved_fabric_hash",
                "physical_traffic_id", "message_artifact_id"):
        assert doc[key], key

def test_identity_binds_each_parent_field_individually():
    _, parents = _parents()
    base = bp.prepare_booksim_input(parents)
    replacements = {
        "topology_hash": "sha256:" + "1" * 64,
        "attachment_hash": "sha256:" + "2" * 64,
        "mapping_hash": "sha256:" + "3" * 64,
        "vc_resource_hash": "sha256:" + "4" * 64,
        "packet_format_hash": "sha256:" + "5" * 64,
        "route_artifact_hash": "sha256:" + "6" * 64,
        "resolved_fabric_hash": "sha256:" + "7" * 64,
        "physical_traffic_id": "sha256:" + "8" * 64,
    }
    for name, value in replacements.items():
        tampered = dataclasses.replace(base, **{name: value})
        assert tampered.prepared_id() != base.prepared_id(), name

def test_native_mesh_dor_is_qualified_and_selected():
    _, parents = _parents()
    qualification = bp.qualify_native_mesh_dor(parents)
    assert qualification.k * qualification.k == qualification.router_count
    assert bp.select_booksim_profile(parents).profile_id \
        == "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1"
    prepared = bp.prepare_booksim_input(parents)
    assert prepared.profile_id == "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1"
    assert prepared.topology_text is None
    values = bp.parse_config_values(prepared.config_text)
    assert values["topology"] == "mesh"
    assert values["routing_function"] == "dim_order"
    assert int(values["n"]) == 2
    assert int(values["k"]) ** 2 == qualification.router_count

def test_native_dor_refuses_when_seat_capacity_exceeds_one():
    compiled, parents = _parents()
    routers = list(compiled.topology.routers)
    object.__setattr__(routers[0], "seat_capacity", 2)
    object.__setattr__(parents.topology, "routers", tuple(routers))
    with pytest.raises(bp.SemanticLoss, match="seat_capacity 1"):
        bp.qualify_native_mesh_dor(parents)

def test_native_dor_refuses_a_non_identity_attachment():
    compiled, parents = _parents()
    endpoints = list(compiled.attachment.endpoints)
    object.__setattr__(endpoints[1], "router_id", 0)
    object.__setattr__(parents.attachment, "endpoints", tuple(endpoints))
    with pytest.raises(bp.SemanticLoss, match="identity-prefix"):
        bp.qualify_native_mesh_dor(parents)

def test_native_dor_refuses_a_non_dor_vc_binding():
    compiled, parents = _parents()
    vc = compiled.routing.vc_assignment
    swapped = dataclasses.replace(
        vc, vc_to_routing_class=tuple(
            (v, ANYNET_MIN_HOPS) for v, _ in vc.vc_to_routing_class))
    object.__setattr__(parents, "vc_assignment", swapped)
    with pytest.raises(bp.SemanticLoss, match="DOR routing function"):
        bp.qualify_native_mesh_dor(parents)

def test_native_dor_refuses_non_unit_link_latency():
    compiled, parents = _parents()
    channels = list(compiled.topology.channels)
    object.__setattr__(channels[0], "latency_cycles", 3)
    object.__setattr__(parents.topology, "channels", tuple(channels))
    with pytest.raises(bp.SemanticLoss, match="latency 1"):
        bp.qualify_native_mesh_dor(parents)

def test_non_mesh_family_falls_back_to_explicit_anynet():
    compiled, parents = _parents(family=TopologyFamily.CONCENTRATED_MESH,
                                 anynet=True)
    assert compiled.topology.family is MaterializedFamily.CONCENTRATED_MESH
    assert bp.select_booksim_profile(parents).profile_id \
        == "CERTIFIED_BOOKSIM_ANYNET_V1"
    prepared = bp.prepare_booksim_input(parents)
    assert prepared.topology_text is not None
    values = bp.parse_config_values(prepared.config_text)
    assert values["topology"] == "anynet"
    assert values["network_file"] == bp.TOPOLOGY_FILE
    text = prepared.topology_text
    assert text.count("router ") >= compiled.topology.router_count
    for endpoint in compiled.attachment.endpoints:
        assert f"node {endpoint.endpoint_id}" in text

def test_anynet_render_binds_routers_to_their_attached_nodes():
    compiled, parents = _parents(family=TopologyFamily.CONCENTRATED_MESH,
                                 anynet=True)
    text = bp.render_anynet_topology(parents).decode().splitlines()
    by_router = {}
    for endpoint in compiled.attachment.endpoints:
        by_router.setdefault(endpoint.router_id, []).append(endpoint.endpoint_id)
    for router_id, nodes in by_router.items():
        assert f"router {router_id}" in text[router_id]
        for node in nodes:
            assert f"node {node}" in text[router_id]

def test_route_realization_binding_and_dump_validation():
    _, parents = _parents()
    report = bp.compare_route_realization(parents, dumped_first_hops=None)
    assert report["routing_function"] == "dim_order"
    assert report["route_artifact_hash"] == parents.route.artifact_hash
    assert report["attachment_hash"] == parents.attachment.attachment_hash()
    assert report["dump_present"] is False
    assert report["dump_supported_by_fork"] is True

    k = report["k"]
    good = {0: 1, 1: 2}
    assert bp.compare_route_realization(
        parents, dumped_first_hops=good)["dump_entries"] == 2
    with pytest.raises(bp.BookSimProjectionError, match="outside the mesh"):
        bp.compare_route_realization(parents, dumped_first_hops={0: k * k})

def test_routing_class_must_be_dor_for_the_native_path():
    from veritx_dse.core.route_artifact import RouteArtifact
    _, parents = _parents()
    assert DOR_XY in [d.id for d in parents.route.routing_classes]
    non_dor = RouteArtifact.from_topology(
        parents.topology, name="anynet", routing_classes=(ANYNET_MIN_HOPS,))
    object.__setattr__(parents, "route", non_dor)
    with pytest.raises(bp.SemanticLoss, match="DOR_XY only"):
        bp.qualify_native_mesh_dor(parents)

def test_semantic_loss_is_a_refusal_not_a_substitution():
    assert issubclass(bp.SemanticLoss, bp.BookSimProjectionError)
    with pytest.raises(bp.SemanticLoss):
        bp.qualify_native_mesh_dor(_parents(family=TopologyFamily.CONCENTRATED_MESH)[1])
    from veritx_dse.model.vc_resource import VCResourceArtifact
    broken = VCResourceArtifact(
        vc_count=2, vc_ids=(0, 1),
        traffic_class_to_vcs=(("a", (0,)), ("b", (1,))))
    exact, reason = bp.vc_exactness(broken)
    assert exact is False
    assert "one VC envelope" in reason

def test_unsupported_owner_requires_a_documented_loss():
    with pytest.raises(bp.BookSimProjectionError, match="explain the loss"):
        bp.ConfigRead("x", bp.ParameterOwner.UNSUPPORTED, "somewhere.cpp")

def test_parent_tampering_and_transplant_are_refused():
    _, parents = _parents()
    prepared = bp.prepare_booksim_input(parents)
    assert bp.assert_canonical_booksim_projection(prepared, parents) is None

    tampered = dataclasses.replace(
        prepared, route_artifact_hash="sha256:" + "0" * 64)
    with pytest.raises(bp.BookSimProjectionError, match="tampered or transplanted"):
        bp.assert_canonical_booksim_projection(tampered, parents)

    other = bp.prepare_booksim_input(_parents(compute=8, tp=8)[1])
    with pytest.raises(bp.BookSimProjectionError, match="tampered or transplanted"):
        bp.assert_canonical_booksim_projection(other, parents)

def test_parent_set_rejects_mismatched_members():
    compiled, parents = _parents()
    other = _det(_design(compute=8, tp=8))
    with pytest.raises(bp.BookSimProjectionError, match="does not belong"):
        bp.BookSimProjectionParents(
            resolved_fabric=compiled.resolved_fabric,
            topology=compiled.topology, attachment=compiled.attachment,
            mapping=other.mapping, vc_resource=compiled.vc_resource,
            vc_assignment=compiled.routing.vc_assignment,
            packet_format=compiled.packet_format,
            route=compiled.routing.route,
            physical_traffic=parents.physical_traffic)

def test_packet_and_flit_conservation():
    _, parents = _parents()
    pt = parents.physical_traffic
    summary = bp.verify_trace_conservation(pt)
    assert summary["num_packets"] == sum(len(m.packets) for m in pt.traffic)
    assert summary["flits_total"] == pt.totals()["flit_count"]
    prepared = bp.prepare_booksim_input(parents)
    rows = [line.split() for line in prepared.trace_text.splitlines() if line]
    assert len(rows) == summary["num_packets"]
    assert sum(int(r[4]) for r in rows) == summary["flits_total"]
    assert pt.totals()["packet_payload_bits"] \
        == sum(m.payload_bytes for m in pt.logical.messages) * 8

def test_trace_renderer_is_endpoint_faithful():
    _, parents = _parents()
    pt = parents.physical_traffic
    rows = [line.split() for line in
            bp.render_trace(pt).decode().splitlines() if line]
    flat = [(p.src_endpoint, p.dst_endpoint, p.flit_count)
            for m in pt.traffic for p in m.packets]
    assert [(int(r[1]), int(r[3]), int(r[4])) for r in rows] == flat

def test_multicast_stays_replicated_unicast_evidence():
    compiled, parents = _parents(multicast=True)
    pt = parents.physical_traffic
    multicast_rows = pt.logical.messages_for_operation("m")
    assert len(multicast_rows) == 2
    assert all(m.src_rank == 0 for m in multicast_rows)
    assert {m.dst_rank for m in multicast_rows} == {1, 2}
    prepared = bp.prepare_booksim_input(parents)
    assert "multicast" not in prepared.config_text.lower()
    blob = js_dump(prepared).lower()
    for token in ("multicast", "flit_fork", "fork_tree"):
        assert token not in blob

def test_parameter_ownership_table_is_closed_and_four_valued():
    vocabulary = {owner.value for owner in bp.ParameterOwner}
    assert vocabulary == {"CANONICAL", "BACKEND_PROFILE", "DERIVED",
                          "UNSUPPORTED"}
    for profile in (bp.ANYNET_PROFILE, bp.MESH_DOR_PROFILE):
        ownership = profile.ownership()
        assert set(ownership.values()) <= set(bp.ParameterOwner)
        emitted = bp.parse_config_values(
            bp.render_config(_parents()[1], profile).decode())
        for key in emitted:
            assert key in profile.known_names(), key
        assert len(ownership) == len(profile.audit)

def test_native_profile_has_its_own_audited_surface():
    anynet = bp.ANYNET_PROFILE.known_names()
    mesh = bp.MESH_DOR_PROFILE.known_names()
    assert anynet != mesh
    assert "network_file" in anynet and "network_file" not in mesh
    assert {"k", "n", "use_noc_latency"} <= mesh
    assert bp.MESH_DOR_PROFILE.ownership()["topology"] \
        is bp.ParameterOwner.CANONICAL

def test_profile_pins_are_rendered_verbatim():
    _, parents = _parents()
    prepared = bp.prepare_booksim_input(parents)
    values = bp.parse_config_values(prepared.config_text)
    for name, pin in bp.MESH_DOR_PROFILE.pinned_values().items():
        if name in values:
            assert values[name] == bp._format_value(pin), name
    assert values["injection_rate"] == "0.0"

@pytest.mark.skipif(not BOOKSIM_SRC.is_dir(),
                    reason="vendored BookSim source not present")
def test_certified_profiles_are_clean_against_the_vendored_fork():
    for profile in (bp.ANYNET_PROFILE, bp.MESH_DOR_PROFILE):
        report = source_audit.audit_profile_reads(profile, BOOKSIM_SRC,
                                                  strict=True)
        assert report.clean
        assert report.declared

@pytest.mark.skipif(not BOOKSIM_SRC.is_dir(),
                    reason="vendored BookSim source not present")
def test_source_audit_observes_real_reads_and_rejects_drift(tmp_path):
    observed = source_audit.observed_fields(BOOKSIM_SRC)
    assert len(observed) > 50
    assert {"topology", "routing_function", "num_vcs", "k", "n"} <= observed
    assert "routing_dump_file" in observed

    (tmp_path / "empty.cpp").write_text("int main() { return 0; }\n")
    with pytest.raises(source_audit.SourceAuditError, match="source drift"):
        source_audit.audit_profile_reads(bp.MESH_DOR_PROFILE, tmp_path,
                                         strict=True)
    with pytest.raises(source_audit.SourceAuditError, match="not found"):
        source_audit.scan_config_reads(tmp_path / "absent")

def test_route_dump_field_is_rendered_for_executed_route_evidence():
    """P0.10: the certified prepared input renders the route-dump path so
    the executed first-hop realization can be compared (relative path, so
    identity stays path-independent)."""
    _, parents = _parents()
    prepared = bp.prepare_booksim_input(parents)
    assert bp.parse_config_values(prepared.config_text)["routing_dump_file"] \
        == bp.ROUTE_DUMP_FILE
    assert "/" not in bp.ROUTE_DUMP_FILE
    _, other = _parents(family=TopologyFamily.CONCENTRATED_MESH, anynet=True)
    assert bp.parse_config_values(
        bp.prepare_booksim_input(other).config_text)["routing_dump_file"] \
        == bp.ROUTE_DUMP_FILE

def test_traffic_is_a_derived_workload_binding_not_a_profile_constant():
    """traffic.cpp rejects a bare `trace` pattern and exits -1."""
    _, parents = _parents()
    prepared = bp.prepare_booksim_input(parents)
    values = bp.parse_config_values(prepared.config_text)
    assert values["traffic"] == "trace(workload.trace)"
    assert "/" not in values["traffic"]
    ownership = bp.MESH_DOR_PROFILE.ownership()
    assert ownership["traffic"] is bp.ParameterOwner.DERIVED
    assert ownership["sample_period"] is bp.ParameterOwner.DERIVED
    assert ownership["max_samples"] is bp.ParameterOwner.DERIVED
    assert "traffic" not in bp.MESH_DOR_PROFILE.pinned_values()

def test_convergence_controls_cover_the_injection_horizon():
    _, parents = _parents()
    schedule = bp.trace_schedule(parents.physical_traffic)
    assert schedule["expected_packets"] > 0
    horizon = bp.trace_injection_horizon(parents.physical_traffic)
    assert schedule["injection_horizon"] == horizon
    assert horizon >= schedule["max_timestamp"] + 1
    assert schedule["sample_period"] == max(200, horizon + 1000)
    assert schedule["sample_period"] * schedule["max_samples"] >= horizon
    prepared = bp.prepare_booksim_input(parents)
    values = bp.parse_config_values(prepared.config_text)
    assert int(values["sample_period"]) == schedule["sample_period"]
    assert int(values["max_samples"]) == schedule["max_samples"]
    doc = prepared.identity_dict()
    assert doc["trace_schedule_version"] == bp.TRACE_SCHEDULE_VERSION
    assert doc["expected_packets"] == schedule["expected_packets"]

def test_concentrated_multi_flit_source_widens_the_window():
    """F-0007: a single source emitting back-to-back multi-flit packets
    needs more injection cycles than the packet count, and the window must
    grow to the flit-serialized horizon (BROADCAST-style fanout)."""
    from veritx_dse.workload.graph import (
        KIND_COLLECTIVE, OperationNode, WorkloadGraph, collective_detail,
    )
    from veritx_dse.workload.messages import LogicalMessageArtifactV2
    from veritx_dse.workload.traffic import PhysicalTrafficArtifactV2
    compiled = _parents()[0]
    graph = WorkloadGraph(
        parallelism=compiled.inventory.parallelism, participant_count=16,
        operations=(OperationNode(
            operation_id="bc", kind=KIND_COLLECTIVE,
            detail=collective_detail(
                collective_kind="BROADCAST", participants=tuple(range(16)),
                payload_bytes=1024, participant_count=16, source=7)),))
    logical = LogicalMessageArtifactV2(graph=graph)
    traffic = PhysicalTrafficArtifactV2(
        logical=logical, resolved_fabric=compiled.resolved_fabric,
        mapping=compiled.mapping, attachment=compiled.attachment,
        inventory=compiled.inventory, packet_format=compiled.packet_format)
    schedule = bp.trace_schedule(traffic)
    assert schedule["injection_horizon"] > schedule["max_timestamp"] + 1
    assert schedule["sample_period"] == max(
        200, schedule["injection_horizon"] + 1000)
    assert schedule["sample_period"] * schedule["max_samples"] \
        >= schedule["injection_horizon"]

def test_a_late_event_still_fits_the_declared_schedule():
    """A deliberately late event must not be truncated."""
    _, parents = _parents()
    schedule = bp.trace_schedule(parents.physical_traffic)
    late = schedule["max_timestamp"]
    assert schedule["sample_period"] >= late + 1
    assert schedule["max_samples"] >= 1

def test_anynet_routing_value_composes_the_registry_key():
    _, parents = _parents(family=TopologyFamily.CONCENTRATED_MESH,
                          anynet=True)
    prepared = bp.prepare_booksim_input(parents)
    values = bp.parse_config_values(prepared.config_text)
    assert values["routing_function"] == "min"
    assert values["topology"] == "anynet"
    assert f"{values['routing_function']}_{values['topology']}" == "min_anynet"

@pytest.mark.skipif(not BOOKSIM_SRC.is_dir(),
                    reason="vendored BookSim source not present")
def test_fork_registers_min_anynet_and_rejects_bare_trace():
    """Source/fork compatibility: identities the projection depends on."""
    anynet = (BOOKSIM_SRC / "networks" / "anynet.cpp").read_text()
    assert 'gRoutingFunctionMap["min_anynet"]' in anynet
    traffic = (BOOKSIM_SRC / "traffic.cpp").read_text()
    assert 'pattern_name == "trace"' in traffic
    assert "requires a filename" in traffic
    # The fork's Dijkstra weights by the link COST token, not its latency.
    assert "dist[min_cand] + i->second[0].cost" in anynet

def test_anynet_allows_heterogeneous_link_latency(tmp_path):
    """An AnyNet link renders its OWN latency and pins route cost to 1, so
    wire latency may vary per link and stay hop-count-routed."""
    from veritx_dse.core.anynet import parse_anynet_file
    compiled, parents = _parents(family=TopologyFamily.CONCENTRATED_MESH,
                                 anynet=True)
    channels = list(compiled.topology.channels)
    object.__setattr__(channels[0], "latency_cycles", 4)
    object.__setattr__(parents.topology, "channels", tuple(channels))
    bp.qualify_anynet_min_hops(parents)
    prepared = bp.prepare_booksim_input(parents)
    rendered = tmp_path / "net.anynet"
    rendered.write_text(prepared.topology_text)
    g = parse_anynet_file(str(rendered))
    assert set(g.router_weight.values()) == {1, 4}, \
        "both the fast and the slow link keep their own wire latency"
    assert set(g.router_cost.values()) == {1}, \
        "route cost stays 1, so the slow link is not a non-preferred path"

def test_anynet_refuses_sub_cycle_and_weighted_routes():
    compiled, parents = _parents(family=TopologyFamily.CONCENTRATED_MESH,
                                 anynet=True)
    channels = list(compiled.topology.channels)
    object.__setattr__(channels[0], "latency_cycles", 0)
    object.__setattr__(parents.topology, "channels", tuple(channels))
    with pytest.raises(bp.SemanticLoss, match=">= 1"):
        bp.qualify_anynet_min_hops(parents)

    compiled_w, parents_w = _parents(
        family=TopologyFamily.CONCENTRATED_MESH, anynet=True)
    channels = list(compiled_w.topology.channels)
    object.__setattr__(channels[0], "route_weight", 3)
    object.__setattr__(parents_w.topology, "channels", tuple(channels))
    with pytest.raises(bp.SemanticLoss, match="unit route weights"):
        bp.qualify_anynet_min_hops(parents_w)

def _with_shared_wire(compiled):
    """The compiled artifact with one shared wire (a bus) spliced in."""
    ids = [r.router_id for r in compiled.topology.routers[:2]]
    shared = SharedLink(shared_link_id=0, src_router=ids[0], taps=(ids[1],),
                        width_bits=64, latency_cycles=1)
    return dataclasses.replace(compiled.topology, shared_links=(shared,))

def test_anynet_projection_refuses_a_shared_wire_topology():
    """A bus has no point-to-point representation; it must be refused, not
    silently rendered as a fabric with its buses missing."""
    compiled, parents = _parents(family=TopologyFamily.CONCENTRATED_MESH,
                                 anynet=True)
    object.__setattr__(parents, "topology", _with_shared_wire(compiled))
    with pytest.raises(bp.BookSimProjectionError, match="shared wire"):
        bp.prepare_booksim_input(parents)

def test_route_derivation_refuses_a_shared_wire_topology():
    from veritx_dse.model.routing import derive_route
    compiled, _ = _parents(family=TopologyFamily.CONCENTRATED_MESH,
                           anynet=True)
    with pytest.raises(RouteArtifactError, match="shared"):
        derive_route(request=compiled.design,
                     topology=_with_shared_wire(compiled))

def test_anynet_refuses_parallel_channels_and_non_sequential_routers():
    compiled, parents = _parents(family=TopologyFamily.CONCENTRATED_MESH,
                                 anynet=True)
    channels = list(compiled.topology.channels)
    object.__setattr__(channels[0], "dst_router",
                       channels[1].dst_router if len(channels) > 1 else 0)
    object.__setattr__(parents.topology, "channels", tuple(channels))
    with pytest.raises(bp.SemanticLoss):
        bp.qualify_anynet_min_hops(parents)

def test_anynet_refuses_a_dor_routed_fabric():
    """A DOR fabric is NOT silently reinterpreted as min-hop."""
    _, parents = _parents()
    with pytest.raises(bp.SemanticLoss, match="ANYNET_MIN_HOPS only"):
        bp.qualify_anynet_min_hops(parents)

def test_prepared_identity_binds_the_trace_schedule():
    _, parents = _parents()
    base = bp.prepare_booksim_input(parents)
    later = dataclasses.replace(base, max_samples=base.max_samples + 1)
    assert later.prepared_id() != base.prepared_id()
    renamed = dataclasses.replace(base, trace_schedule_version="other")
    assert renamed.prepared_id() != base.prepared_id()
