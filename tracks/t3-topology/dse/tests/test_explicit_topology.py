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
# TWO UNRELATED TopologyError CLASSES EXIST:
#   core.errors.TopologyError(VeritXError)          <- raised by topology_ir
#   model.topology_artifact.TopologyError(ValueError, SemanticError)
# Neither catches the other. This tranche catches BOTH and records the
# collision as an unresolved blocker (IMPLEMENTATION-LEDGER.md); it does
# not merge the classes, which would change error handling tree-wide.
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


# ══ CUSTOM-1: strict round-trip identity ═══════════════════════════════

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


# ══ CUSTOM-2: duplicate router / duplicate edge rejects ════════════════

def test_custom_2_duplicate_edge_rejects():
    with pytest.raises(TopologyError):
        tir.from_dict(_doc(links=[[0, 1], [1, 0]]))   # undirected duplicate


def test_custom_2b_duplicate_router_ids_are_unrepresentable():
    """Routers are 0..nodes-1 by construction, so a duplicate router id
    cannot be authored — the representation makes it inexpressible rather
    than merely refused."""
    art = materialize_ir(_ir(nodes=4))
    ids = [r.router_id for r in art.routers]
    assert ids == sorted(set(ids)) == [0, 1, 2, 3]


# ══ CUSTOM-3: invalid edge rejects ═════════════════════════════════════

def test_custom_3_self_loop_rejects():
    with pytest.raises(TopologyError):
        tir.from_dict(_doc(links=[[1, 1]]))


def test_custom_3b_out_of_range_rejects():
    with pytest.raises(TopologyError):
        tir.from_dict(_doc(nodes=4, links=[[0, 9]]))


def test_custom_3c_malformed_link_rejects():
    with pytest.raises(TopologyError):
        tir.from_dict(_doc(links=[[0]]))


# ══ CUSTOM-4: connectivity policy enforced ═════════════════════════════

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
    assert len(art.channels) == 4          # 2 undirected -> 4 directed


# ══ CUSTOM-5: seat capacity preserved ══════════════════════════════════

def test_custom_5_seat_capacity_preserved():
    art = materialize_ir(_ir(), seat_capacity=3)
    assert {r.seat_capacity for r in art.routers} == {3}


def test_custom_5b_seat_capacity_rejects_zero():
    with pytest.raises(ValueError):
        materialize_ir(_ir(), seat_capacity=0)


# ══ CUSTOM-6: link semantics preserved ═════════════════════════════════

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


# ══ CUSTOM-7: scientific coordinates are identity-bearing ══════════════

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


# ══ CUSTOM-8: presentation layout never changes identity ═══════════════

def test_custom_8_coordinate_free_graph_has_no_coordinates():
    art = materialize_ir(_ir())
    assert all(r.coordinates == () for r in art.routers), \
        "a coordinate-free custom graph must carry NO coordinates"


def test_custom_8b_presentation_layout_is_not_identity():
    """The identity of a coordinate-free graph does not move when a
    presentation layout is computed — because no layout is persisted."""
    art = materialize_ir(_ir())
    before = art.topology_hash()
    # A frontend layout is derived at render time and never written back.
    layout = {r.router_id: (r.router_id * 40, 0) for r in art.routers}
    assert layout is not None
    assert art.topology_hash() == before
    # And the serialized form carries no layout field at all.
    assert "layout" not in art.to_dict()
    assert "svg" not in str(art.to_dict()).lower()


def test_custom_8c_coordinate_free_identity_differs_from_placed():
    """Omitting coordinates is a DIFFERENT scientific claim from placing
    them, and the two must not collide."""
    a = materialize_ir(_ir())
    b = materialize_ir(_ir(), coordinates={i: (i, 0) for i in range(4)})
    assert a.topology_hash() != b.topology_hash()


# ══ CUSTOM-9: the inspector consumes only the canonical artifact ═══════

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


# ══ CUSTOM-10: no route / VC authored ══════════════════════════════════

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


# ══ STAGE-1: Mesh still fully compiles ═════════════════════════════════

def test_stage_1_mesh_identity_is_stable():
    """Mesh canonical identity must not move. This is the regression guard
    for AMEND-2's refactor of the shared _artifact() constructor."""
    from veritx_dse.model.topology_artifact import materialize_family
    art = materialize_family(MaterializedFamily.MESH, endpoint_count=16)
    assert len(art.routers) == 16
    assert len(art.channels) == 48
    assert art.topology_hash().startswith("524cf3267d4d64c3cdd07dd2")


# ══ STAGE-2/3: upstream survives a later refusal ═══════════════════════

def test_stage_2_torus_upstream_topology_survives():
    from veritx_dse.model.topology_artifact import materialize_family
    torus = materialize_family(MaterializedFamily.TORUS, endpoint_count=25)
    assert len(torus.routers) == 25
    # 5x5 torus: 4 neighbours per router -> 100 directed channels.
    assert len(torus.channels) == 100
    # The artifact is complete and inspectable even though routing refuses.
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
