"""Typed topology intent — the v3 topology authority (PHASE B).

The load-bearing properties:
  * each family owns exactly the parameters its science needs, under
    scientific names (no BookSim `k`/`n`/`c`/`o`/`d`);
  * the intent actually DRIVES materialization — it is not decorative;
  * one topology source per request (family XOR intent XOR explicit graph);
  * the intent is design science, so it enters design_hash, and a
    to_dict/from_dict round trip preserves identity;
  * the v2-shaped spelling still works and is derived INTO the typed intent,
    so there are never two disagreeing authorities.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).parent.parent
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

from veritx_dse.model.compile_model import (  # noqa: E402
    CompileRequestV3, CompileRequestV3SchemaError, TopologyFamily,
)
from veritx_dse.model.topology_intent import (  # noqa: E402
    ConcentratedMeshIntent, ExplicitTopologyIntent, FlatFlyIntent,
    GecExpressIntent, MeshIntent, TopologyIntentError, TorusIntent,
    migrate_topology_intent, topology_intent_from_dict,
    topology_intent_from_noc_config,
)


# ══ each family owns its own science ═══════════════════════════════════

def test_mesh_and_concentrated_mesh_are_distinct_declarations():
    assert MeshIntent(side_length=4).kind == "mesh"
    assert ConcentratedMeshIntent(side_length=4, concentration=4).kind == \
        "concentrated_mesh"
    # Concentration 1 is a mesh, not a concentrated mesh.
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


def test_no_backend_spelling_is_expressible():
    """`k`/`n`/`c`/`o`/`d` are BookSim letters. They must not be accepted as
    canonical intent fields."""
    for bad in ({"kind": "mesh", "k": 4},
                {"kind": "mesh", "n": 2},
                {"kind": "flatfly", "radix_per_dimension": 4,
                 "dimension_count": 2, "concentration": 4, "c": 4},
                {"kind": "gec_express", "grid_side_length": 8,
                 "concentration": 1, "express_channel_count": 7, "d": 1}):
        with pytest.raises(TopologyIntentError, match="unknown fields"):
            topology_intent_from_dict(bad)


def test_unknown_kind_is_refused():
    with pytest.raises(TopologyIntentError, match="unknown topology intent"):
        topology_intent_from_dict({"kind": "dragonfly"})


def test_mecs_is_refused_rather_than_flattened():
    """destinations_per_express_channel > 1 is one shared, tapped wire. It is
    NOT representable as independent point-to-point channels."""
    with pytest.raises(TopologyIntentError, match="MULTI-DROP"):
        GecExpressIntent(grid_side_length=8, concentration=1,
                         express_channel_count=1,
                         destinations_per_express_channel=7)
    # The point-to-point case is fine.
    ok = GecExpressIntent(grid_side_length=8, concentration=1,
                          express_channel_count=7,
                          destinations_per_express_channel=1)
    assert ok.kind == "gec_express"


# ══ content identity ═══════════════════════════════════════════════════

def test_intent_id_is_stable_and_distinguishing():
    a = MeshIntent(side_length=4)
    assert a.intent_id() == MeshIntent(side_length=4).intent_id()
    assert a.intent_id() != MeshIntent(side_length=8).intent_id()
    assert a.intent_id() != ConcentratedMeshIntent(side_length=4,
                                                   concentration=4).intent_id()
    assert a.intent_id().startswith("sha256:")


def test_intent_round_trips_through_dict():
    for i in (MeshIntent(side_length=4, concentration=2),
              ConcentratedMeshIntent(side_length=2, concentration=4),
              TorusIntent(side_length=8),
              FlatFlyIntent(radix_per_dimension=4, dimension_count=2,
                            concentration=4),
              GecExpressIntent(grid_side_length=8, concentration=1,
                               express_channel_count=7),
              ExplicitTopologyIntent()):
        assert topology_intent_from_dict(i.to_dict()) == i


# ══ the v2 compatibility layer derives INTO the intent ═════════════════

def test_v2_spelling_derives_into_the_typed_intent():
    intent = topology_intent_from_noc_config(
        TopologyFamily.CONCENTRATED_MESH, radix=4, concentration=4)
    assert isinstance(intent, ConcentratedMeshIntent)
    assert intent.side_length == 4 and intent.concentration == 4
    assert isinstance(topology_intent_from_noc_config(
        TopologyFamily.MESH, radix=8, concentration=1), MeshIntent)
    assert isinstance(topology_intent_from_noc_config(
        TopologyFamily.CUSTOM, radix=None, concentration=None),
        ExplicitTopologyIntent)


def test_migration_provenance_is_non_semantic():
    intent, prov = migrate_topology_intent(TopologyFamily.MESH, radix=4,
                                           concentration=1)
    assert prov["migrated_from"] == "noc_config.topology_family"
    assert prov["intent_id"] == intent.intent_id()
    # The provenance is linkage: it must not appear in the intent's identity.
    assert "migrated_from" not in intent.to_dict()


def test_family_with_no_intent_variant_is_refused():
    with pytest.raises(TopologyIntentError, match="no typed intent"):
        topology_intent_from_noc_config(TopologyFamily.FAT_TREE, radix=None,
                                        concentration=None)


# ══ the intent DRIVES materialization ═════════════════════════════════

def _v3_doc():
    doc = json.loads((REPO / "tracks/t3-topology/examples/"
                      "dense_1b_16tiles-v3.json").read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    doc["agents"] = [{"kind": "compute_tile", "count": 16,
                      "data_width": 256, "addr_width": 64, "protocol": "AXI"}]
    doc["noc_config"] = dict(doc["noc_config"])
    doc["noc_config"]["topology_family"] = None
    return doc


def test_intent_materializes_the_declared_family():
    from veritx_dse.application.fabric_compiler import FabricCompiler
    doc = _v3_doc()
    doc["topology_intent"] = MeshIntent(side_length=4).to_dict()
    c = FabricCompiler().compile(CompileRequestV3.from_dict(doc))
    assert c.status == "COMPILED"
    assert c.bundle.topology.family.value == "mesh"
    assert c.bundle.topology.router_count == 16


def test_intent_kind_changes_the_design_identity():
    a = _v3_doc()
    a["topology_intent"] = MeshIntent(side_length=4).to_dict()
    b = _v3_doc()
    b["topology_intent"] = ConcentratedMeshIntent(side_length=2,
                                                  concentration=4).to_dict()
    assert (CompileRequestV3.from_dict(a).design_hash()
            != CompileRequestV3.from_dict(b).design_hash())


def test_intent_survives_persistence_round_trip():
    doc = _v3_doc()
    doc["topology_intent"] = MeshIntent(side_length=4).to_dict()
    r = CompileRequestV3.from_dict(doc)
    back = CompileRequestV3.from_dict(r.to_dict())
    assert back.design_hash() == r.design_hash()
    assert back.topology_intent == r.topology_intent


def test_gec_express_intent_is_authorable_but_not_materializable_yet():
    """The typed refusal is the point: no silent fallback to another family."""
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.core.errors import TopologyError
    doc = _v3_doc()
    doc["topology_intent"] = GecExpressIntent(
        grid_side_length=4, concentration=1,
        express_channel_count=3).to_dict()
    c = FabricCompiler().compile(CompileRequestV3.from_dict(doc))
    assert c.status == "UNSUPPORTED"
    assert "no canonical materializer" in str(c.error)
    assert "PHASE D" in str(c.error)


# ══ one topology source per request ═══════════════════════════════════

def test_family_and_intent_together_are_refused():
    doc = _v3_doc()
    doc["topology_intent"] = MeshIntent(side_length=4).to_dict()
    doc["noc_config"] = dict(doc["noc_config"])
    doc["noc_config"]["topology_family"] = "mesh"
    with pytest.raises(CompileRequestV3SchemaError,
                       match="EXACTLY ONE topology source"):
        CompileRequestV3.from_dict(doc)


def test_intent_and_explicit_graph_together_are_refused():
    from veritx_dse.model import topology_ir as tir
    doc = _v3_doc()
    doc["topology_intent"] = MeshIntent(side_length=4).to_dict()
    doc["explicit_topology"] = tir.from_dict({
        "name": "g", "kind": "custom", "nodes": 4,
        "links": [[0, 1], [1, 2], [2, 3]],
        "link_attrs": {"bandwidth_GBs": 50.0, "latency_ns": 500.0},
    }).to_dict()
    with pytest.raises(CompileRequestV3SchemaError,
                       match="EXACTLY ONE topology source"):
        CompileRequestV3.from_dict(doc)


def test_explicit_marker_intent_is_refused():
    doc = _v3_doc()
    doc["topology_intent"] = ExplicitTopologyIntent().to_dict()
    with pytest.raises(CompileRequestV3SchemaError, match="MARKER"):
        CompileRequestV3.from_dict(doc)


def test_intent_carries_no_routing_or_backend_field():
    """Topology defines PHYSICAL STRUCTURE. Routing and backend projection are
    downstream, so no intent may declare a field for them. Checked against the
    real dataclass FIELDS (prose may name them to say what the type is not)."""
    import dataclasses
    from veritx_dse.model import topology_intent as ti
    forbidden = ("routing", "booksim", "vc", "backend", "profile", "seed",
                 "buffer", "latency", "bandwidth", "clock")
    for name in ("MeshIntent", "ConcentratedMeshIntent", "TorusIntent",
                 "FlatFlyIntent", "GecExpressIntent",
                 "ExplicitTopologyIntent"):
        cls = getattr(ti, name)
        for f in dataclasses.fields(cls):
            low = f.name.lower()
            assert not any(bad in low for bad in forbidden), (
                f"{name}.{f.name} leaks a downstream concern into topology "
                "intent")
        assert set(f.name for f in dataclasses.fields(cls)) <= \
            ti._FIELDS[cls.kind] | {"kind"}


def test_every_variant_is_registered_and_strictly_keyed():
    """A variant that is not in _KIND_TO_CLASS, or has no _FIELDS entry, could
    be persisted but not loaded — or loaded without key checking."""
    from veritx_dse.model import topology_intent as ti
    import dataclasses
    for kind, cls in ti._KIND_TO_CLASS.items():
        assert kind in ti._FIELDS, kind
        declared = {f.name for f in dataclasses.fields(cls)}
        assert declared <= ti._FIELDS[kind] | {"kind"}, kind
