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

from veritx_dse.model.compile_model import TopologyFamily  # noqa: E402
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
