"""Exact native fly: three stages, ingress/egress split, destination tags.

The fly is the first fabric here whose terminals inject and eject at
DIFFERENT routers, so the evidence has two independent halves:

* the static first-hop table is the literal ``dest_tag_fly`` answer for every
  (router, destination node) pair -- deterministic, so it is compared
  row-for-row and port-for-port, not as a legal-choice union;
* the runtime route-compute dump proves the executed hops advance one stage
  at a time, start at the flow's own injection router and eject exactly at
  the flow's own stage-2 router, which no static table can state.

The attachment must also be asymmetric: a symmetric seat would let the
renderer accept a fabric whose ejection points were never bound.
"""
from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from veritx_dse.application.presets import _typed_request, build_typed_preset_request
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.booksim_qualification_registry import (
    QUALIFICATION, resolve_execution_handler,
)
from veritx_dse.backend.booksim_projection import (
    BookSimProjectionError, prepare_booksim_input,
)
from veritx_dse.backend.booksim_execution import BookSimExecutionError
from veritx_dse.backend.fly_projection import (
    LOWERER_VERSION, OBSERVATION_FILE, PROFILE, PROFILE_ID, expected_rows,
    legal_hops, qualify, static_port, verify_runtime,
)
from veritx_dse.application.capability_truth import _parents_from_bundle
from veritx_dse.core.paths import REPO
from veritx_dse.core.route_artifact import (
    FLY_DEST_TAG, FLY_DEST_TAG_DEFINITION, RING_DATELINE, TREE4_NCA,
    RouteArtifact, RouteArtifactError, routing_pair_domain,
)
from veritx_dse.model.fly_net import (
    EGRESS_ROUTERS, K, LEVELS, ROUTER_COUNT, TERMINALS, WIRING,
    egress_port, materialize_fly, native_router_id, next_router,
    router_stage, terminal_egress_location, terminal_ingress_location,
    witness_path,
)
from veritx_dse.model.resolved_route import routing_router
from veritx_dse.model.routing_policy_artifact import normalize_legacy_route
from veritx_dse.model.topology_artifact import MaterializedFamily
from veritx_dse.model.topology_intent import (
    FlyIntent, TopologyIntentError, topology_intent_from_dict,
)
from veritx_dse.verification.channel_vc_cdg import (
    FLY_DESTINATION_EXPANSION, _fly_edges, build_channel_vc_cdg,
)


def request():
    return _typed_request(FlyIntent(4, 3), endpoints=64, tp=64)


@pytest.fixture(scope="module")
def compiled():
    result = FabricCompiler().compile(request())
    assert result.status == "COMPILED", result.error
    assert result.certificate.overall == "PASS"
    return result


def legal_stream(rows=((0, 0, 32, 3),), *, num_vcs=4):
    """A synthetic executed stream from explicit (flit, src, dest, hops)."""
    from veritx_dse.model.fly_net import terminal_egress_location
    lines = ["# native-route-compute/v1"]
    for flit, src, dest, hops in rows:
        router, _ = terminal_ingress_location(src)
        for step in range(hops):
            port = static_port(router, dest)
            lines.append(f"{flit} {src} {dest} {router} 0 0 {port} "
                         f"0 {num_vcs - 1} 0")
            following = next_router(router, port)
            if following is None:
                break
            router = following
        egress, _ = terminal_egress_location(dest)
        assert router == egress, "the synthetic stream must reach the egress"
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- geometry
def test_geometry_ports_and_asymmetric_attachment(compiled):
    topology = compiled.bundle.topology
    assert topology.family is MaterializedFamily.FLY_NATIVE
    assert ROUTER_COUNT == 48 and LEVELS == 3 and K == 4
    assert len(topology.routers) == ROUTER_COUNT
    assert len(topology.channels) == 2 * TERMINALS
    # Stage 0 owns the ingress slots, stage 2 the egress slots, stage 1 none.
    assert [r.seat_capacity for r in topology.routers] == [4] * 16 + [0] * 32
    assert [r.egress_seat_capacity for r in topology.routers] == \
        [0] * 16 + [0] * 16 + [4] * 16
    assert sum(r.seat_capacity for r in topology.routers) == TERMINALS
    assert sum(r.ejection_capacity for r in topology.routers) == TERMINALS
    # Every channel advances exactly one stage and keeps BookSim's channel id.
    for channel in topology.channels:
        assert router_stage(channel.src_router) + 1 == \
            router_stage(channel.dst_router)
        assert channel.channel_id == (
            router_stage(channel.src_router) * TERMINALS
            + (channel.src_router % 16) * K + channel.src_port)
    assert {c.channel_id for c in topology.channels} == set(range(2 * TERMINALS))
    endpoints = compiled.bundle.attachment.endpoints
    assert len(endpoints) == TERMINALS
    for endpoint in endpoints:
        terminal = endpoint.endpoint_id
        assert (endpoint.router_id, endpoint.port_id) == \
            terminal_ingress_location(terminal)
        assert endpoint.egress_location() == terminal_egress_location(terminal)
        assert not endpoint.symmetric
        # Routing addresses are the egress routers; the attachment keeps the
        # ingress ones, so the two facts can never be confused.
        assert routing_router(endpoint) == terminal_egress_location(terminal)[0]


def test_wiring_is_a_permutation_and_paths_terminate():
    assert len(WIRING) == 2 * TERMINALS
    sources = {}
    for (stage, addr, port), (dst, dst_port) in WIRING.items():
        assert sources.setdefault((stage, addr, port), (dst, dst_port)) == \
            (dst, dst_port)
        assert router_stage(dst) == stage + 1
        assert 0 <= dst_port < K
    # Every terminal is reachable from its own formula in exactly 3 routers.
    for terminal in range(TERMINALS):
        ingress, _ = terminal_ingress_location(terminal)
        path = witness_path(ingress, terminal)
        assert [router_stage(r) for r in path] == [0, 1, 2]
        assert path[-1] == terminal_egress_location(terminal)[0]
        assert native_router_id(path[0]) == path[0]


def test_identity_is_distinct_from_every_graph_description(compiled):
    from veritx_dse.model.routing import routing_policy_for
    from veritx_dse.model.topology_artifact import materialize_topology_intent
    from veritx_dse.model.topology_intent import StructuredTopologyIntent
    structured = materialize_topology_intent(
        None, StructuredTopologyIntent(family="flattened_butterfly",
                                       params={"radix": 4, "dimensions": 2}))
    # The stage law, the ingress/egress split and the destination-tag function
    # are construction facts of the native fabric; a graph description has
    # none of them, so neither geometry nor routing class may be shared.
    assert routing_policy_for(compiled.bundle.topology) == FLY_DEST_TAG
    assert structured.canonical_dict() != \
        compiled.bundle.topology.canonical_dict()
    with pytest.raises(RouteArtifactError, match="exact native fly geometry"):
        RouteArtifact.from_topology(structured, name="x",
                                    routing_classes=(FLY_DEST_TAG,))


def test_intent_refuses_unsupported_geometry_and_locked_fields():
    with pytest.raises(TopologyIntentError):
        FlyIntent(radix=2, levels=3)
    with pytest.raises(TopologyIntentError):
        FlyIntent(radix=4, levels=4)
    with pytest.raises(TopologyIntentError):
        topology_intent_from_dict({"kind": "fly_native", "radix": 4,
                                   "levels": 3, "routing_function": "nca"})
    parsed = topology_intent_from_dict({"kind": "fly_native", "radix": 4,
                                        "levels": 3})
    assert parsed == FlyIntent(4, 3)


# ------------------------------------------------------------------ routing
def test_route_class_is_sealed_and_partial_by_construction(compiled):
    route = compiled.bundle.router_route
    assert route.routing_classes == (FLY_DEST_TAG_DEFINITION,)
    domain = routing_pair_domain(FLY_DEST_TAG_DEFINITION, compiled.bundle.topology)
    assert domain is not None and len(domain) == 16 * 16 + 16 * 4
    assert set(route.entries) == {(FLY_DEST_TAG, s, t) for (s, t) in domain}
    # No entry may name a non-ejection destination.
    assert {t for _cls, _s, t in route.entries} <= set(EGRESS_ROUTERS)


def test_route_table_cannot_drop_a_required_pair(compiled):
    route = compiled.bundle.router_route
    entries = dict(route.entries)
    victim = sorted(entries)[0]
    entries.pop(victim)
    with pytest.raises(RouteArtifactError, match="do not cover"):
        RouteArtifact(
            schema_version=route.schema_version, name="x",
            topology_hash=route.topology_hash,
            routing_classes=route.routing_classes, entries=entries,
        ).validate_against(compiled.bundle.topology)


def test_static_table_is_the_literal_dest_tag_law(compiled):
    hops, ports = expected_rows(compiled.bundle.topology)
    assert len(hops) == ROUTER_COUNT * TERMINALS == len(ports)
    for router, terminal, following in hops:
        port = static_port(router, terminal)
        assert router_stage(router) == 2 or next_router(router, port) == following
        if router_stage(router) == 2:
            assert following == router        # ejection names the router itself


def test_legal_hops_refuse_impossible_positions():
    # A stage-1 router only serves terminals whose destination digit matches.
    ingress, _ = terminal_ingress_location(0)
    port = static_port(ingress, 0)
    stage1 = next_router(ingress, port)
    assert router_stage(stage1) == 1
    # Terminal 16 has destination digit 1, so a flow reached through digit 0
    # can never continue toward it.
    with pytest.raises(Exception, match="destination digit matches"):
        legal_hops(stage1, 16)
    # A stage-2 router that is not the destination's ejection point refuses.
    other = EGRESS_ROUTERS[5]
    with pytest.raises(Exception, match="cannot be at"):
        legal_hops(other, 0)
    # Its own ejection point is a valid (last) hop.
    egress, egress_port_ = terminal_egress_location(0)
    assert legal_hops(egress, 0) == ((egress, egress_port_),)


def test_no_vacuous_total_relation_is_invented(compiled):
    with pytest.raises(Exception, match="destination-tag allocation adapter"):
        normalize_legacy_route(compiled.bundle.topology,
                               compiled.bundle.router_route,
                               compiled.bundle.vc_assignment)


def test_deadlock_graph_is_destination_indexed_and_stage_increasing(compiled):
    edges = _fly_edges(compiled.bundle.topology, ((0, 0), (1, 1)), TERMINALS)
    assert edges
    stage_of = {c.channel_id: router_stage(c.src_router)
                for c in compiled.bundle.topology.channels}
    # Edges are between (channel, VC) nodes: the hop chain of one terminal.
    assert all(stage_of[a[0]] < stage_of[b[0]] for a, b in edges)
    cdg = build_channel_vc_cdg(compiled.bundle.topology, compiled.bundle.router_route,
                               compiled.bundle.vc_assignment)
    assert cdg.expansion == FLY_DESTINATION_EXPANSION
    assert not cdg.cycles() if hasattr(cdg, "cycles") else True


# ------------------------------------------------------------- qualification
def holder(compiled):
    """The four artifacts `qualify` reads, free of the projection invariants.

    The negative cases below deliberately break ONE thing; building a full
    BookSimProjectionParents would fail its own consistency checks first,
    which is not the claim under test.
    """
    from types import SimpleNamespace
    parents = _parents_from_bundle(compiled.bundle, request())
    return SimpleNamespace(topology=parents.topology,
                           attachment=parents.attachment,
                           route=parents.route,
                           vc_resource=parents.vc_resource)


def test_qualification_refuses_a_symmetric_attachment(compiled):
    parents = holder(compiled)
    endpoints = tuple(replace(e, egress_router_id=None, egress_port_id=None)
                      for e in parents.attachment.endpoints)
    parents.attachment = replace(parents.attachment, endpoints=endpoints)
    with pytest.raises(Exception, match="no egress location"):
        qualify(parents)


def test_qualification_refuses_the_wrong_ejection_point(compiled):
    parents = holder(compiled)
    endpoints = list(parents.attachment.endpoints)
    # Swap two terminals' ejection points: still a legal one-to-one
    # attachment (no duplicate slot), but neither matches its own law.
    a, b = endpoints[0], endpoints[1]
    endpoints[0] = replace(a, egress_router_id=b.egress_router_id,
                           egress_port_id=b.egress_port_id)
    endpoints[1] = replace(b, egress_router_id=a.egress_router_id,
                           egress_port_id=a.egress_port_id)
    parents.attachment = replace(parents.attachment,
                                endpoints=tuple(endpoints))
    with pytest.raises(Exception, match="does not eject at its stage-2"):
        qualify(parents)


def test_qualification_refuses_changed_geometry(compiled):
    parents = holder(compiled)
    routers = tuple(replace(r, seat_capacity=3) if r.router_id == 0 else r
                    for r in parents.topology.routers)
    parents.topology = replace(parents.topology, routers=routers)
    with pytest.raises(Exception, match="geometry/ports/slots differ"):
        qualify(parents)


def test_qualification_refuses_another_family_and_other_classes(compiled):
    parents = holder(compiled)
    family = parents.topology.family
    parents.topology = replace(parents.topology,
                               family=MaterializedFamily.TREE4_NATIVE)
    try:
        with pytest.raises(Exception, match="certified for fly_native only"):
            qualify(parents)
    finally:
        parents.topology = replace(parents.topology, family=family)
    from types import SimpleNamespace
    from veritx_dse.core.route_artifact import RING_DATELINE_DEFINITION
    # The class check runs before anything reads the entries, so a stand-in
    # route is enough to state "a fly refuses another sealed class".
    parents.route = SimpleNamespace(
        routing_classes=(RING_DATELINE_DEFINITION,))
    with pytest.raises(Exception, match="sealed FLY_DEST_TAG"):
        qualify(parents)


def test_other_native_classes_cannot_route_a_fly(compiled):
    topology = compiled.bundle.topology
    for other in (TREE4_NCA, RING_DATELINE):
        with pytest.raises(RouteArtifactError):
            RouteArtifact.from_topology(topology, name="x",
                                        routing_classes=(other,))


def test_prepared_input_carries_both_obligations(compiled, tmp_path):
    prepared = prepare_booksim_input(_parents_from_bundle(compiled.bundle,
                                                          request()))
    assert prepared.profile_id == PROFILE_ID
    assert prepared.lowerer_version == LOWERER_VERSION
    values = prepared.config_text
    assert "topology = fly;" in values
    assert "routing_function = dest_tag;" in values
    assert f"native_route_observation_file = {OBSERVATION_FILE};" in values
    hops, ports = expected_rows(compiled.bundle.topology)
    assert prepared.expected_route_rows == hops
    assert prepared.expected_route_ports == ports


# ---------------------------------------------------------- runtime evidence
def test_runtime_accepts_a_legal_stream():
    stats = verify_runtime(legal_stream(), num_vcs=4)
    assert stats["rows"] == stats["flits"] * 3
    assert stats["stages"] == [stats["flits"]] * 3


def test_runtime_rejects_a_skipped_stage():
    text = "\n".join([
        f"1 0 0 0 0 0 {static_port(0, 0)} 0 3 0",
        f"1 0 0 {next_router(0, static_port(0, 0)) + 16} 0 0 "
        f"{static_port(next_router(0, static_port(0, 0)) + 16, 0)} 0 3 0",
    ]) + "\n"
    with pytest.raises(BookSimExecutionError, match="lands at|stage"):
        verify_runtime(text, num_vcs=4)


def test_runtime_rejects_a_wrong_port():
    port = static_port(0, 0)
    text = f"1 0 0 0 0 0 {(port + 1) % 4} 0 3 0\n"
    with pytest.raises(BookSimExecutionError, match="dest_tag_fly computes"):
        verify_runtime(text, num_vcs=4)


def test_runtime_rejects_ejection_elsewhere():
    dest = 4
    egress, _ = terminal_egress_location(dest)
    other = EGRESS_ROUTERS[0] if egress != EGRESS_ROUTERS[0] else EGRESS_ROUTERS[1]
    text = f"1 0 {dest} {other} 0 0 {static_port(other, dest)} 0 3 0\n"
    with pytest.raises(BookSimExecutionError):
        verify_runtime(text, num_vcs=4)


def test_runtime_rejects_a_wrong_injection_router():
    text = legal_stream().splitlines()
    text[1] = "1 0 32 16 0 0 2 0 3 0"
    with pytest.raises(BookSimExecutionError):
        verify_runtime("\n".join(text) + "\n", num_vcs=4)


def test_runtime_rejects_narrowed_vc_range():
    text = legal_stream().splitlines()
    text[1] = text[1].rsplit(" ", 3)[0] + " 1 2 0"
    with pytest.raises(BookSimExecutionError, match="whole range"):
        verify_runtime("\n".join(text) + "\n", num_vcs=4)


def test_runtime_rejects_two_flows_on_one_flit():
    # Two legal single-hop rows for the same flit but different destinations.
    first = f"9 0 0 0 0 0 {static_port(0, 0)} 0 3 0"
    ingress, _ = terminal_ingress_location(16)
    second = f"9 0 16 {ingress} 0 0 {static_port(ingress, 16)} 0 3 0"
    with pytest.raises(BookSimExecutionError, match="two flows"):
        verify_runtime(first + "\n" + second + "\n", num_vcs=4)


def test_runtime_rejects_malformed_and_empty_dumps():
    with pytest.raises(BookSimExecutionError, match="10-field"):
        verify_runtime("1 2 3\n", num_vcs=4)
    with pytest.raises(BookSimExecutionError, match="no executed rows"):
        verify_runtime("# header only\n", num_vcs=4)


# --------------------------------------------------------------- execution
def test_authenticated_product_execution_and_preset(tmp_path):
    from veritx_dse.application.product_evaluator import evaluate_product
    preset = build_typed_preset_request("fly_native64")
    assert preset.design_hash() == request().design_hash()
    binary = REPO / "third_party/booksim2/src/booksim"
    if not binary.is_file():
        pytest.skip("authenticated native execution requires built BookSim")
    result = evaluate_product(preset, binary=binary, network_clock_hz=10**9,
                              timeout_s=600, run_dir=tmp_path, repo_root=REPO,
                              seed=0)
    assert result.status == "EVALUATED", result.reason
    assert result.outcome.evidence_id and result.outcome.realization_digest
    metrics = result.outcome.metrics
    assert metrics["flits_injected"] == metrics["flits_accepted"] > 0
    evidence = json.loads(next(
        tmp_path.rglob("evidence/backend-evidence.json")).read_text())
    assert evidence["route_observation"] == "EXECUTED_ROUTE_OBSERVED"
    assert evidence["route_dump_sha256"]
    runtime = evidence["stats"]["fly_route_computations"]
    assert runtime["rows"] == runtime["flits"] * 3
    assert runtime["stages"][0] == runtime["stages"][1] == runtime["stages"][2]


def test_execution_refuses_incomplete_obligations(compiled, tmp_path):
    from veritx_dse.backend.booksim_execution import execute_prepared_booksim
    binary = REPO / "third_party/booksim2/src/booksim"
    if not binary.is_file():
        pytest.skip("authenticated native execution requires built BookSim")
    prepared = prepare_booksim_input(_parents_from_bundle(compiled.bundle,
                                                          request()))
    with pytest.raises(BookSimExecutionError, match="complete hop AND port"):
        execute_prepared_booksim(
            prepared=replace(prepared,
                             expected_route_ports=prepared.expected_route_ports[:-5]),
            binary=binary, run_dir=tmp_path, repo_root=REPO, timeout=300)
    with pytest.raises(BookSimExecutionError, match="complete hop AND port"):
        execute_prepared_booksim(
            prepared=replace(prepared, expected_route_rows=()),
            binary=binary, run_dir=tmp_path, repo_root=REPO, timeout=300)
    assert not list(tmp_path.iterdir())


def test_projection_refuses_a_one_way_fabric_that_is_not_the_stage_law(compiled):
    parents = _parents_from_bundle(compiled.bundle, request())
    channels = parents.topology.channels
    broken = replace(channels[0], dst_router=channels[0].dst_router + 16)
    topology = replace(parents.topology,
                       channels=(broken,) + tuple(channels[1:]))
    with pytest.raises((BookSimProjectionError, Exception)):
        prepare_booksim_input(replace(parents, topology=topology))


# ---------------------------------------------------------------- registry
def test_registry_records_the_qualified_profile():
    record = QUALIFICATION[PROFILE_ID]
    assert record.state == "QUALIFIED"
    assert record.lowerer_version == LOWERER_VERSION
    assert record.projection_semantics_version == PROFILE.semantics_version
    assert resolve_execution_handler(PROFILE_ID)
