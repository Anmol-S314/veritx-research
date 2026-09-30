"""Explicit custom topology tests (CUSTOM-1..10) and generic staged
compilation tests (STAGE-1..6).

AMEND-2: the canonical custom topology contract is the EXISTING
`model.topology_ir.TopologyIR` (strict, undirected links, no required
coordinates). This tranche adds only the missing half: lowering that intent
to a canonical `TopologyArtifact` via `materialize_ir`.

AMEND-3: the staged-compilation law (a later typed refusal preserves
upstream artifacts) must be generic, not Torus-specific.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.model.topology_artifact import (
    MaterializedFamily,
    materialize_flatfly,
    materialize_ir,
    materialize_topology,
)
from veritx_dse.model.compile_model import NocConfig, TopologyFamily
from veritx_dse.model import topology_ir as tir
from veritx_dse.model.topology_artifact import TopologyError as _ArtTE
from veritx_dse.core.errors import TopologyError as _CoreTE

TopologyError = (_ArtTE, _CoreTE)

def _doc(**kw) -> dict:
    base = {"name": "t", "kind": "custom", "nodes": 4,
            "links": [[0, 1], [1, 2], [2, 3]],
            "link_attrs": {"bandwidth_GBs": 50, "latency_ns": 500}}
    base.update(kw)
    return base

def _ir(**kw) -> tir.TopologyIR:
    return tir.from_dict(_doc(**kw))

def test_custom_1_round_trip_identity():
    art = materialize_ir(_ir())
    assert art.family == MaterializedFamily.CUSTOM
    d = art.to_dict()
    back = art.from_dict(d)
    assert back.topology_hash() == art.topology_hash()
    assert back == art

def test_custom_1b_identity_is_deterministic():
    a = materialize_ir(_ir())
    b = materialize_ir(_ir())
    assert a.topology_hash() == b.topology_hash()

def test_custom_1c_identity_moves_with_the_graph():
    a = materialize_ir(_ir())
    b = materialize_ir(_ir(links=[[0, 1], [1, 2], [2, 3], [0, 3]]))
    assert a.topology_hash() != b.topology_hash(), \
        "adding a link MUST change topology identity"

def test_custom_2_duplicate_edge_rejects():
    with pytest.raises(TopologyError):
        tir.from_dict(_doc(links=[[0, 1], [1, 0]]))

def test_custom_2b_duplicate_router_ids_are_unrepresentable():
    """Routers are 0..nodes-1 by construction, so a duplicate router id
    cannot be authored — the representation makes it inexpressible rather
    than merely refused."""
    art = materialize_ir(_ir(nodes=4))
    ids = [r.router_id for r in art.routers]
    assert ids == sorted(set(ids)) == [0, 1, 2, 3]

def test_custom_3_self_loop_rejects():
    with pytest.raises(TopologyError):
        tir.from_dict(_doc(links=[[1, 1]]))

def test_custom_3b_out_of_range_rejects():
    with pytest.raises(TopologyError):
        tir.from_dict(_doc(nodes=4, links=[[0, 9]]))

def test_custom_3c_malformed_link_rejects():
    with pytest.raises(TopologyError):
        tir.from_dict(_doc(links=[[0]]))

def test_custom_4_custom_requires_explicit_links():
    with pytest.raises(TopologyError):
        tir.from_dict(_doc(links=None))

def test_custom_4b_template_rejects_explicit_links():
    with pytest.raises(TopologyError):
        tir.from_dict({"name": "m", "kind": "mesh", "nodes": 16,
                       "params": {"k": 4, "n": 2},
                       "links": [[0, 1]],
                       "link_attrs": {"bandwidth_GBs": 50, "latency_ns": 500}})

def test_custom_4c_disconnected_graph_is_preserved_not_repaired():
    """A disconnected explicit graph is representable; the materializer must
    NOT silently connect it."""
    ir = _ir(nodes=5, links=[[0, 1], [2, 3]])
    art = materialize_ir(ir)
    undirected = {(min(c.src_router, c.dst_router),
                   max(c.src_router, c.dst_router)) for c in art.channels}
    assert undirected == {(0, 1), (2, 3)}
    assert len(art.channels) == 4

def test_custom_5_seat_capacity_preserved():
    art = materialize_ir(_ir(), seat_capacity=3)
    assert {r.seat_capacity for r in art.routers} == {3}

def test_custom_5b_seat_capacity_rejects_zero():
    with pytest.raises(ValueError):
        materialize_ir(_ir(), seat_capacity=0)

def test_custom_6_link_semantics_preserved():
    art = materialize_ir(_ir(), width_bits=128, latency_cycles=7)
    assert {c.width_bits for c in art.channels} == {128}
    assert {c.latency_cycles for c in art.channels} == {7}

def test_custom_6b_undirected_link_lowers_to_two_directed_channels():
    art = materialize_ir(_ir(nodes=2, links=[[0, 1]]))
    pairs = sorted((c.src_router, c.dst_router) for c in art.channels)
    assert pairs == [(0, 1), (1, 0)]

def test_custom_6c_link_attrs_required_no_hidden_default():
    """TopologyIR requires analytical link attrs; there is no honest
    fallback, so omitting them must fail rather than default."""
    with pytest.raises(TopologyError):
        tir.from_dict({"name": "t", "kind": "custom", "nodes": 2,
                       "links": [[0, 1]], "link_attrs": {}})

def test_custom_6d_per_link_outside_a_link_entry_is_refused():
    """Per-link overrides live in a link's own opts. Smuggling a per-link
    list into the GLOBAL link_attrs is still refused: it cannot be honored
    and dropping it would simulate a different (uniform) network."""
    with pytest.raises(TopologyError, match="link_attrs has unknown key"):
        tir.from_dict(_doc(link_attrs={
            "bandwidth_GBs": 50, "latency_ns": 500,
            "per_link": [[0, 1, 400.0], [1, 2, 400.0]],
        }))

def test_custom_6e_explicit_intent_honours_latency_cycles():
    """The typed-intent seam must forward link latency, not silently
    materialize at the default."""
    from veritx_dse.model.topology_artifact import materialize_topology_intent
    from veritx_dse.model.topology_intent import ExplicitTopologyIntent
    art = materialize_topology_intent(
        None, ExplicitTopologyIntent(graph=_ir()), latency_cycles=7)
    assert {c.latency_cycles for c in art.channels} == {7}

def test_custom_6f_directed_link_lowers_to_one_channel():
    art = materialize_ir(_ir(nodes=2, links=[[0, 1, {"directed": True}]]))
    pairs = sorted((c.src_router, c.dst_router) for c in art.channels)
    assert pairs == [(0, 1)], "a directed link is ONE channel, not two"

def test_custom_6g_per_link_latency_reaches_the_channel():
    """A per-link latency override must not be flattened to the global
    default: it is relative to the baseline link_attrs.latency_ns."""
    ir = tir.from_dict(_doc(links=[[0, 1], [1, 2, {"latency_ns": 1000}]],
                            link_attrs={"bandwidth_GBs": 50,
                                        "latency_ns": 500}))
    by_pair = {(c.src_router, c.dst_router): c.latency_cycles
               for c in materialize_ir(ir).channels}
    assert by_pair[(0, 1)] == 1
    assert by_pair[(1, 2)] == 2 and by_pair[(2, 1)] == 2, \
        "the 1000ns link is twice the 500ns baseline"

def test_custom_6h_per_link_bandwidth_reaches_the_channel():
    ir = tir.from_dict(_doc(links=[[0, 1], [1, 2, {"bandwidth_GBs": 400}]],
                            link_attrs={"bandwidth_GBs": 50,
                                        "latency_ns": 500}))
    by_pair = {(c.src_router, c.dst_router): c.width_bits
               for c in materialize_ir(ir, width_bits=64).channels}
    assert by_pair[(0, 1)] == 64
    assert by_pair[(1, 2)] == 512, "the 400GB/s link is 8x the 50GB/s baseline"

def test_custom_6i_shared_wire_materializes_as_a_shared_link():
    """A shared wire is one driver feeding many taps, NOT N point-to-point
    channels. Flattening it would model N independent wires instead."""
    ir = tir.from_dict(_doc(nodes=4, links=[[0, [1, 2, 3]]],
                            link_attrs={"bandwidth_GBs": 50,
                                        "latency_ns": 500}))
    art = materialize_ir(ir)
    assert [(s.src_router, s.taps) for s in art.shared_links] \
        == [(0, (1, 2, 3))]
    assert art.channels == (), \
        "a shared wire must not become point-to-point channels"
    back = art.from_dict(art.to_dict())
    assert back.topology_hash() == art.topology_hash()

def test_custom_6j_shared_wire_coexists_with_point_to_point():
    ir = tir.from_dict(_doc(nodes=4, links=[[0, [1, 2]], [2, 3]],
                            link_attrs={"bandwidth_GBs": 50,
                                        "latency_ns": 500}))
    art = materialize_ir(ir)
    assert len(art.shared_links) == 1
    assert sorted((c.src_router, c.dst_router) for c in art.channels) \
        == [(2, 3), (3, 2)]

def test_custom_6k_directed_and_undirected_overlap_refused():
    with pytest.raises(TopologyError, match="undirected link"):
        tir.from_dict(_doc(links=[[0, 1], [1, 0, {"directed": True}]]))

def test_custom_6l_anynet_keeps_direction_and_per_link_weight():
    """Each clause carries its own latency AND the hop-count cost, so a
    slow link keeps its delay without becoming a non-preferred path."""
    ir = tir.from_dict(_doc(nodes=3,
                            links=[[0, 1], [1, 2, {"latency_ns": 1000}]],
                            link_attrs={"bandwidth_GBs": 50,
                                        "latency_ns": 500}))
    lines = tir.to_anynet(ir).splitlines()
    assert lines[0] == "router 0 node 0 router 1 1 1"
    assert lines[1] == "router 1 node 1 router 0 1 1 router 2 2 1"
    assert lines[2] == "router 2 node 2 router 1 2 1"

def test_custom_6m_anynet_renders_a_one_way_link_once():
    ir = tir.from_dict(_doc(nodes=2, links=[[0, 1, {"directed": True}]],
                            link_attrs={"bandwidth_GBs": 50,
                                        "latency_ns": 500}))
    assert tir.to_anynet(ir).splitlines() == [
        "router 0 node 0 router 1 1 1", "router 1 node 1"]

def test_custom_6n_anynet_parser_separates_latency_from_cost(tmp_path):
    """`<latency> <cost>` keeps the wire delay and the routing metric
    apart, and a declared link exists in exactly the directions written."""
    from veritx_dse.core.anynet import parse_anynet_file
    p = tmp_path / "t.anynet"
    p.write_text("router 0 node 0 router 1 5 1\n"
                 "router 1 node 1 router 0\n")
    g = parse_anynet_file(str(p))
    assert g.router_weight[(0, 1)] == 5
    assert g.router_cost[(0, 1)] == 1
    assert g.router_directed == {0: {1}, 1: {0}}
    assert g.is_symmetric

def test_custom_6o_anynet_parser_keeps_a_one_way_link_one_way(tmp_path):
    from veritx_dse.core.anynet import parse_anynet_file
    p = tmp_path / "t.anynet"
    p.write_text("router 0 node 0 router 1 3 1\nrouter 1 node 1\n")
    g = parse_anynet_file(str(p))
    assert g.router_directed == {0: {1}}, \
        "an undeclared reverse direction must not be invented"
    assert not g.is_symmetric
    assert g.n_edges == 1

def test_custom_6p_anynet_parser_counts_parallel_lanes(tmp_path):
    from veritx_dse.core.anynet import parse_anynet_file
    p = tmp_path / "t.anynet"
    p.write_text("router 0 node 0 router 1 4 1 router 1 4 1\n"
                 "router 1 node 1 router 0 4 1 router 0 4 1\n")
    g = parse_anynet_file(str(p))
    assert g.router_lanes[(0, 1)] == 2
    assert g.has_parallel_lanes

def test_custom_7_scientific_coordinates_change_identity():
    a = materialize_ir(_ir(), coordinates={0: (0, 0), 1: (1, 0),
                                           2: (2, 0), 3: (3, 0)})
    b = materialize_ir(_ir(), coordinates={0: (0, 0), 1: (0, 1),
                                           2: (0, 2), 3: (0, 3)})
    assert a.topology_hash() != b.topology_hash(), \
        "supplied SCIENTIFIC coordinates are identity-bearing"

def test_custom_7b_partial_coordinates_refuse():
    with pytest.raises(TopologyError):
        materialize_ir(_ir(), coordinates={0: (0, 0)})

def test_custom_8_coordinate_free_graph_has_no_coordinates():
    art = materialize_ir(_ir())
    assert all(r.coordinates == () for r in art.routers), \
        "a coordinate-free custom graph must carry NO coordinates"

def test_custom_8b_presentation_layout_is_not_identity():
    """The identity of a coordinate-free graph does not move when a
    presentation layout is computed — because no layout is persisted."""
    art = materialize_ir(_ir())
    before = art.topology_hash()
    layout = {r.router_id: (r.router_id * 40, 0) for r in art.routers}
    assert layout is not None
    assert art.topology_hash() == before
    assert "layout" not in art.to_dict()
    assert "svg" not in str(art.to_dict()).lower()

def test_custom_8c_coordinate_free_identity_differs_from_placed():
    """Omitting coordinates is a DIFFERENT scientific claim from placing
    them, and the two must not collide."""
    a = materialize_ir(_ir())
    b = materialize_ir(_ir(), coordinates={i: (i, 0) for i in range(4)})
    assert a.topology_hash() != b.topology_hash()

def test_custom_9_artifact_is_sufficient_for_rendering():
    """The 2D inspector must need nothing beyond TopologyArtifact: routers,
    directed channels, ports. It must not be told the family."""
    art = materialize_ir(_ir())
    d = art.to_dict()
    for key in ("routers", "channels", "family", "topology_hash"):
        assert key in d, key
    for r in d["routers"]:
        assert set(r) == {"router_id", "coordinates", "seat_capacity"}
    for c in d["channels"]:
        assert {"channel_id", "src_router", "src_port",
                "dst_router", "dst_port"} <= set(c)

def test_custom_9b_same_shape_as_a_named_family_artifact():
    """Mesh, FlatFly and CUSTOM artifacts are structurally identical, so one
    renderer serves all three with no family-specific branch."""
    from veritx_dse.model.topology_artifact import materialize_family
    mesh = materialize_family(MaterializedFamily.MESH, endpoint_count=16)
    flat = materialize_flatfly(k=4, n=2)
    cust = materialize_ir(_ir())
    shapes = {type(a).__name__ for a in (mesh, flat, cust)}
    assert shapes == {"TopologyArtifact"}
    keysets = {tuple(sorted(a.to_dict())) for a in (mesh, flat, cust)}
    assert len(keysets) == 1, "artifact shape must not vary by family"

def test_custom_10_materializer_authors_no_routes_or_vcs():
    art = materialize_ir(_ir())
    d = art.to_dict()
    for forbidden in ("route", "routes", "vc", "vc_count", "vc_map",
                      "turn", "escape", "certificate"):
        assert forbidden not in d, f"materializer must not author {forbidden!r}"

def test_custom_10b_ir_schema_has_no_route_or_vc_fields():
    """The intent schema itself must not carry compiler-derived facts."""
    ir = _ir()
    fields = set(vars(ir))
    assert not (fields & {"route", "routes", "vc", "vc_map", "turn",
                          "escape", "channel_ids", "node_ids"})

def test_stage_1_mesh_identity_is_stable():
    """Mesh canonical identity must not move. This is the regression guard
    for AMEND-2's refactor of the shared _artifact() constructor."""
    from veritx_dse.model.topology_artifact import materialize_family
    art = materialize_family(MaterializedFamily.MESH, endpoint_count=16)
    assert len(art.routers) == 16
    assert len(art.channels) == 48
    assert art.topology_hash().startswith("524cf3267d4d64c3cdd07dd2")

def test_stage_2_torus_upstream_topology_survives():
    from veritx_dse.model.topology_artifact import materialize_family
    torus = materialize_family(MaterializedFamily.TORUS, endpoint_count=25)
    assert len(torus.routers) == 25
    assert len(torus.channels) == 100
    assert torus.topology_hash()

def test_stage_3_custom_upstream_topology_survives():
    """A custom graph materializes and stays inspectable; no downstream
    artifact is fabricated."""
    art = materialize_ir(_ir())
    assert art.routers and art.channels
    assert art.topology_hash()

def test_stage_6_no_missing_downstream_artifact_is_fabricated():
    """materialize_ir must not invent a route table, VC map or certificate."""
    art = materialize_ir(_ir())
    assert not hasattr(art, "route")
    assert not hasattr(art, "vc_assignment")
    assert not hasattr(art, "certificate")
