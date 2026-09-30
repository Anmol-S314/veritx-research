"""Typed topology intent — the v4 topology authority (PHASE B.1 §5, §6, §7, §26).

The load-bearing properties:

  * each family owns exactly the parameters its science needs, under
    scientific names (no BookSim `k`/`n`/`c`/`o`/`d`);
  * AUTHORABILITY AND MATERIALIZABILITY ARE DIFFERENT STAGES. A multidrop
    GEC design and a fat-tree are legal DECLARATIONS even though nothing can
    materialize them yet. Refusing MECS materialization is correct; refusing
    MECS design intent is not;
  * one topology authority per request (the explicit graph lives INSIDE the
    intent, so two authorities cannot even be expressed);
  * the scientific projection is the identity, so an explicit graph's
    presentation name cannot change which design this is.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.model.compile_model import TopologyFamily  # noqa: E402
from veritx_dse.model.topology_intent import (  # noqa: E402
    AUTHORABLE_INTENT_KINDS, ConcentratedMeshIntent, ExplicitTopologyIntent,
    FatTreeIntent, FlatFlyIntent, GecMode, GecTopologyIntent, MeshIntent,
    TopologyIntentError, TorusIntent, capability_family_label,
    topology_intent_from_dict, topology_intent_from_noc_config,
)

def test_every_required_kind_is_registered():
    required = {"mesh", "concentrated_mesh", "torus", "flatfly", "fattree",
                "gec", "explicit"}
    assert required <= set(AUTHORABLE_INTENT_KINDS)

def test_every_registered_kind_round_trips():
    for kind in AUTHORABLE_INTENT_KINDS:
        assert kind in topology_intent_from_dict.__globals__["_FIELDS"]

def test_every_variant_is_strictly_keyed():
    from veritx_dse.model import topology_intent as ti
    for kind, cls in ti._KIND_TO_CLASS.items():
        assert kind in ti._FIELDS, kind
        declared = {f.name for f in dataclasses.fields(cls)}
        assert declared <= ti._FIELDS[kind] | {"kind"}, kind

def test_gec_modes_are_the_four_physical_constructions():
    assert {m.value for m in GecMode} == {"mesh", "express", "multidrop",
                                          "hybrid"}

def test_gec_mesh_mode_forbids_express_partitioning():
    """Source gec.cpp refuses mesh=1 with o/d other than 1/1: the
    partitioning model does not apply to the nearest-neighbour graph."""
    ok = GecTopologyIntent(mode=GecMode.MESH, grid_side_length=8,
                           concentration=1)
    assert ok.express_channel_groups_per_dimension is None
    with pytest.raises(TopologyIntentError, match="NEAREST-NEIGHBOUR"):
        GecTopologyIntent(mode=GecMode.MESH, grid_side_length=8,
                          concentration=1,
                          express_channel_groups_per_dimension=7,
                          destinations_per_express_channel=1)

def test_gec_express_channel_grouping_law_is_the_source_law():
    """groups x destinations == grid_side_length - 1 (source o*d == k-1)."""
    GecTopologyIntent(mode=GecMode.EXPRESS, grid_side_length=8,
                      concentration=1,
                      express_channel_groups_per_dimension=7,
                      destinations_per_express_channel=1)
    GecTopologyIntent(mode=GecMode.MULTIDROP, grid_side_length=8,
                      concentration=1,
                      express_channel_groups_per_dimension=1,
                      destinations_per_express_channel=7)
    GecTopologyIntent(mode=GecMode.HYBRID, grid_side_length=8,
                      concentration=1,
                      express_channel_groups_per_dimension=7,
                      destinations_per_express_channel=1)
    with pytest.raises(TopologyIntentError, match="span the grid exactly once"):
        GecTopologyIntent(mode=GecMode.EXPRESS, grid_side_length=8,
                          concentration=1,
                          express_channel_groups_per_dimension=3,
                          destinations_per_express_channel=1)

def test_gec_express_and_multidrop_are_distinguished_by_tap_count():
    with pytest.raises(TopologyIntentError, match="POINT-TO-POINT"):
        GecTopologyIntent(mode=GecMode.EXPRESS, grid_side_length=8,
                          concentration=1,
                          express_channel_groups_per_dimension=1,
                          destinations_per_express_channel=7)
    with pytest.raises(TopologyIntentError, match="MECS"):
        GecTopologyIntent(mode=GecMode.MULTIDROP, grid_side_length=8,
                          concentration=1,
                          express_channel_groups_per_dimension=7,
                          destinations_per_express_channel=1)

def test_gec_mecs_is_a_valid_declaration():
    """THE CENTRAL LAW: the intent must express the physical design even
    though no materializer exists. MECS is shared, tapped science."""
    mecs = GecTopologyIntent(mode=GecMode.MULTIDROP, grid_side_length=8,
                             concentration=1,
                             express_channel_groups_per_dimension=1,
                             destinations_per_express_channel=7)
    assert mecs.shares_express_channels is True
    assert mecs.to_dict()["mode"] == "multidrop"
    assert topology_intent_from_dict(mecs.to_dict()) == mecs

def test_gec_express_parameters_cannot_be_defaulted():
    """Neither express parameter can be invented: the grid is spanned
    exactly once, so a missing value would silently mean a different
    physical design (source falls back to o=k-1, d=1 — we refuse)."""
    for mode in (GecMode.EXPRESS, GecMode.MULTIDROP, GecMode.HYBRID):
        with pytest.raises(TopologyIntentError, match="needs BOTH"):
            GecTopologyIntent(mode=mode, grid_side_length=8, concentration=1)

def test_gec_subfamilies_are_reported_separately():
    """GEC is one registered kind but four physical modes that progress
    differently, so capability truth must not collapse them."""
    def _params(mode):
        if mode is GecMode.MESH:
            return {}
        if mode is GecMode.MULTIDROP:
            return {"express_channel_groups_per_dimension": 1,
                    "destinations_per_express_channel": 7}
        return {"express_channel_groups_per_dimension": 7,
                "destinations_per_express_channel": 1}
    labels = {capability_family_label(GecTopologyIntent(
        mode=m, grid_side_length=8, concentration=1, **_params(m)))
        for m in GecMode}
    assert labels == {"gec_mesh", "gec_express", "gec_multidrop",
                      "gec_hybrid"}

def test_fattree_carries_only_the_source_structural_facts():
    """Source law (third_party/booksim2/src/networks/fattree.cpp):
    nodes = k ** n, switches = n * k ** (n - 1), and each BOTTOM switch
    terminates exactly k endpoints. There is NO independent concentration
    input, so the intent must not have one."""
    ft = FatTreeIntent(switch_radix=4, level_count=2)
    assert ft.to_dict() == {"kind": "fattree", "switch_radix": 4,
                            "level_count": 2}
    assert ft.endpoint_capacity == 4 ** 2 == 16
    assert ft.switch_count == 2 * 4 ** 1 == 8
    with pytest.raises(TopologyIntentError):
        FatTreeIntent(switch_radix=1, level_count=2)

def test_fattree_has_no_concentration_knob():
    """A concentrated fat-tree is a DIFFERENT topology semantic. Inserting a
    concentration knob into the BookSim-compatible intent would describe a
    topology the cited source does not implement."""
    import dataclasses
    names = {f.name for f in dataclasses.fields(FatTreeIntent)}
    assert names == {"switch_radix", "level_count"}
    with pytest.raises(TypeError):
        FatTreeIntent(switch_radix=4, level_count=2, concentration=2)
    with pytest.raises(TopologyIntentError, match="unknown fields"):
        topology_intent_from_dict({"kind": "fattree", "switch_radix": 4,
                                   "level_count": 2, "concentration": 2})

def test_fattree_is_authorable_and_round_trips():
    ft = FatTreeIntent(switch_radix=8, level_count=3)
    assert topology_intent_from_dict(ft.to_dict()) == ft
    assert ft.endpoint_capacity == 8 ** 3
    assert ft.switch_count == 3 * 8 ** 2

def test_mesh_and_concentrated_mesh_are_distinct_declarations():
    assert MeshIntent(side_length=4).kind == "mesh"
    assert ConcentratedMeshIntent(side_length=4, concentration=4).kind == \
        "concentrated_mesh"
    with pytest.raises(TopologyIntentError):
        ConcentratedMeshIntent(side_length=4, concentration=1)

def test_flatfly_owns_radix_per_dimension_and_dimension_count():
    ff = FlatFlyIntent(radix_per_dimension=4, dimension_count=2,
                       concentration=4)
    assert ff.to_dict() == {"kind": "flatfly", "radix_per_dimension": 4,
                            "dimension_count": 2, "concentration": 4}
    with pytest.raises(TopologyIntentError):
        FlatFlyIntent(radix_per_dimension=1, dimension_count=2,
                      concentration=4)

def test_torus_wraparound_is_the_family_not_a_knob():
    t = TorusIntent(side_length=8)
    assert set(t.to_dict()) == {"kind", "side_length", "concentration"}

def _graph(name="g16"):
    from veritx_dse.model import topology_ir as tir
    return tir.from_dict({
        "name": name, "kind": "custom", "nodes": 16,
        "links": [[i, i + 1] for i in range(15)],
        "link_attrs": {"bandwidth_GBs": 50.0, "latency_ns": 500.0},
    })

def test_explicit_intent_carries_the_graph_so_there_is_one_field():
    e = ExplicitTopologyIntent(graph=_graph())
    assert e.graph.nodes == 16
    assert topology_intent_from_dict(e.to_dict()).graph.nodes == 16

def test_explicit_intent_refuses_a_template_kind():
    from veritx_dse.model.topology_ir import TopologyIR
    tmpl = TopologyIR(name="m", kind="mesh", nodes=16,
                      link_attrs={"bandwidth_GBs": 50.0,
                                  "latency_ns": 500.0})
    with pytest.raises(TopologyIntentError, match="TEMPLATE"):
        ExplicitTopologyIntent(graph=tmpl)

def test_explicit_graph_name_is_excluded_from_identity():
    """A synthesized candidate and the identical hand-authored graph must be
    the same design science."""
    a = ExplicitTopologyIntent(graph=_graph("candidate_0007"))
    b = ExplicitTopologyIntent(graph=_graph("hand_authored"))
    assert a.intent_id() == b.intent_id()
    assert a.scientific_dict() == b.scientific_dict()

def test_no_backend_spelling_is_expressible():
    for bad in ({"kind": "mesh", "k": 4},
                {"kind": "mesh", "n": 2},
                {"kind": "flatfly", "radix_per_dimension": 4,
                 "dimension_count": 2, "concentration": 4, "c": 4},
                {"kind": "gec", "mode": "express", "k": 8, "c": 1, "o": 7,
                 "d": 1},
                {"kind": "fattree", "k": 4, "n": 2}):
        with pytest.raises(TopologyIntentError, match="unknown fields"):
            topology_intent_from_dict(bad)

def test_unknown_kind_is_refused():
    with pytest.raises(TopologyIntentError, match="unknown topology intent"):
        topology_intent_from_dict({"kind": "dragonfly"})

def test_bool_is_not_an_int():
    with pytest.raises(TopologyIntentError, match="must be an int"):
        MeshIntent(side_length=True)

def test_intent_id_is_stable_and_distinguishing():
    assert MeshIntent(side_length=4).intent_id() == \
        MeshIntent(side_length=4).intent_id()
    assert MeshIntent(side_length=4).intent_id() != \
        MeshIntent(side_length=8).intent_id()
    assert MeshIntent(side_length=4).intent_id() != \
        ConcentratedMeshIntent(side_length=4, concentration=4).intent_id()

def test_intent_carries_no_routing_or_backend_field():
    """Topology defines PHYSICAL STRUCTURE. Checked against the real
    dataclass FIELDS (prose may name them to say what the type is NOT)."""
    from veritx_dse.model import topology_intent as ti
    forbidden = ("routing", "booksim", "vc", "backend", "profile", "seed",
                 "buffer", "latency", "bandwidth", "clock")
    for name in ("MeshIntent", "ConcentratedMeshIntent", "TorusIntent",
                 "FlatFlyIntent", "FatTreeIntent", "GecTopologyIntent",
                 "ExplicitTopologyIntent"):
        for f in dataclasses.fields(getattr(ti, name)):
            low = f.name.lower()
            assert not any(bad in low for bad in forbidden), (
                f"{name}.{f.name} leaks a downstream concern")

def test_legacy_spelling_derives_for_families_v3_could_express():
    assert isinstance(topology_intent_from_noc_config(
        TopologyFamily.MESH, radix=8, concentration=1), MeshIntent)
    assert isinstance(topology_intent_from_noc_config(
        TopologyFamily.TORUS, radix=8, concentration=1), TorusIntent)
    assert isinstance(topology_intent_from_noc_config(
        TopologyFamily.CONCENTRATED_MESH, radix=4, concentration=None),
        ConcentratedMeshIntent)

def test_legacy_concentrated_mesh_default_is_a_frozen_literal():
    from veritx_dse.model.topology_intent import (
        V3_CONCENTRATED_MESH_DEFAULT_CONCENTRATION,
    )
    assert V3_CONCENTRATED_MESH_DEFAULT_CONCENTRATION == 4
    assert topology_intent_from_noc_config(
        TopologyFamily.CONCENTRATED_MESH, radix=4,
        concentration=None).concentration == 4

def test_legacy_gec_and_fattree_spellings_REFUSE():
    """v3 could not distinguish GEC's four modes, and the source's internal
    o=k-1/d=1 fallback is NOT a design decision we may make for the user."""
    with pytest.raises(TopologyIntentError, match="does not determine"):
        topology_intent_from_noc_config(TopologyFamily.GEC, radix=8,
                                        concentration=1)
    with pytest.raises(TopologyIntentError, match="does not determine"):
        topology_intent_from_noc_config(TopologyFamily.FAT_TREE, radix=4,
                                        concentration=None)

def test_legacy_custom_spelling_refuses_because_a_graph_is_not_derivable():
    with pytest.raises(TopologyIntentError, match="explicit GRAPH"):
        topology_intent_from_noc_config(TopologyFamily.CUSTOM, radix=None,
                                        concentration=None)

def test_legacy_flatfly_spelling_refuses_rather_than_picking_a_meaning():
    """The legacy shape carries ONE number for three FlatFly parameters."""
    with pytest.raises(TopologyIntentError, match="does not determine"):
        topology_intent_from_noc_config("flatfly", radix=4, concentration=4)
