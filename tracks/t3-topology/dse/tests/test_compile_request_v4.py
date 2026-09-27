"""CompileRequest v4 + NocControls + v3->v4 migration (PHASE B.1 §9–§13, §25).

The load-bearing properties:

  * v4 has ONE topology authority, REQUIRED, with no "None means mesh";
  * v4 is strict: unknown fields, unknown kinds, shape-in-controls, missing
    topology and bool-as-int all refuse;
  * the v4 hash domain is separate from v3, so the same science expressed in
    two generations is deliberately NOT the same identity;
  * migration REFUSES families whose legacy spelling does not determine a
    physical design, and never upgrades implicitly during parsing.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).parent.parent
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

from veritx_dse.model.compile_model import (  # noqa: E402
    CompileRequestV3, TopologyFamily,
)
from veritx_dse.model.compile_request_v4 import (  # noqa: E402
    COMPILE_REQUEST_SCHEMA_VERSION_V4, CompileRequestV4,
    CompileRequestV4MigrationError, CompileRequestV4SchemaError,
    migrate_v3_to_v4,
)
from veritx_dse.model.noc_controls import (  # noqa: E402
    NocControls, NocControlsError, TOPOLOGY_SHAPE_FIELD_NAMES,
    noc_controls_from_dict, noc_controls_from_noc_config,
)
from veritx_dse.model.topology_intent import (  # noqa: E402
    ExplicitTopologyIntent, FatTreeIntent, GecMode, GecTopologyIntent,
    MeshIntent,
)

EX = REPO / "tracks/t3-topology/examples"


def _v3_doc(**noc):
    d = json.loads((EX / "dense_1b_16tiles-v3.json").read_text())
    d.pop("design_hash", None)
    d.pop("guardrail_hash", None)
    d["agents"] = [{"kind": "compute_tile", "count": 16, "data_width": 256,
                    "addr_width": 64, "protocol": "AXI"}]
    d["noc_config"] = dict(d["noc_config"])
    d["noc_config"].update(noc)
    return d


def _v3(**noc):
    return CompileRequestV3.from_dict(_v3_doc(**noc))


def _v4():
    return migrate_v3_to_v4(_v3(topology_family=None, radix=None,
                                concentration=None))


# ══ §9 NocControls may not describe topology shape ════════════════════

def test_noc_controls_carries_exactly_the_topology_independent_controls():
    names = {f.name for f in dataclasses.fields(NocControls)}
    assert names == {"arbitration", "rcu_enabled", "link_width",
                     "mcast_groups", "mcast_setup_cycles", "output_formats",
                     "obfuscation_level"}
    assert not (names & TOPOLOGY_SHAPE_FIELD_NAMES)


def test_noc_controls_refuses_topology_shape_by_name():
    for shape in ({"radix": 4}, {"concentration": 4},
                  {"topology_family": "mesh"}, {"side_length": 4}):
        with pytest.raises(NocControlsError, match="topology SHAPE"):
            noc_controls_from_dict(shape)


def test_noc_controls_refuses_unknown_fields():
    with pytest.raises(NocControlsError, match="unknown noc_controls"):
        noc_controls_from_dict({"arbitration": "round_robin", "o": 7})


def test_noc_controls_has_no_locked_routing_field():
    """routing_function / turn_restrictions / vc_map are DERIVED, so they are
    not expressible — not refused, impossible."""
    names = {f.name for f in dataclasses.fields(NocControls)}
    for locked in ("routing_function", "turn_restrictions", "vc_map"):
        assert locked not in names


def test_noc_controls_preserves_legacy_none_means_unconstrained():
    controls = noc_controls_from_noc_config(_v3().noc_config)
    assert controls.arbitration is None
    assert controls.rcu_enabled is None
    assert controls.link_width == 64        # carried verbatim from v3
    assert controls.mcast_groups is None
    assert controls.mcast_setup_cycles is None


def test_output_format_order_is_not_design_science():
    from veritx_dse.model.compile_model import OutputFormat
    a = NocControls(output_formats=(OutputFormat.SYSTEMVERILOG,
                                    OutputFormat.JSON))
    b = NocControls(output_formats=(OutputFormat.JSON,
                                    OutputFormat.SYSTEMVERILOG))
    assert a.controls_id() == b.controls_id()


def test_bool_is_not_an_int_in_controls():
    with pytest.raises((NocControlsError, ValueError)):
        NocControls(link_width=True)


# ══ §10–§12 v4 root ═══════════════════════════════════════════════════

def test_v4_requires_an_explicit_topology():
    """No implicit 'None means mesh' in the persisted v4 schema."""
    with pytest.raises(ValueError, match="MUST declare its topology"):
        CompileRequestV4(workload=_v3().workload, topology=None,
                         dependencies=_v3().dependencies)


def test_v4_schema_and_semantics_versions_are_four():
    r = _v4()
    assert r.schema_version == 4
    assert r.compiler_semantics_version == 4
    assert COMPILE_REQUEST_SCHEMA_VERSION_V4 == 4
    assert r.to_dict()["schema_version"] == 4


def test_v4_has_a_separate_hash_domain_from_v3():
    """The migrated pair MUST differ: generation is part of the identity."""
    from veritx_dse.model.compile_model import _HASH_TYPE_TAG_V3
    from veritx_dse.model.compile_request_v4 import _HASH_TYPE_TAG_V4
    assert _HASH_TYPE_TAG_V3 != _HASH_TYPE_TAG_V4
    v3 = _v3(topology_family=None, radix=None, concentration=None)
    assert migrate_v3_to_v4(v3).design_hash() != v3.design_hash()


def test_v4_round_trips_and_preserves_identity():
    r = _v4()
    back = CompileRequestV4.from_dict(r.to_dict())
    assert back.design_hash() == r.design_hash()
    assert back.topology == r.topology


def test_v4_topology_science_enters_identity():
    a = _v4()
    b = dataclasses.replace(a, topology=MeshIntent(side_length=8))
    assert a.design_hash() != b.design_hash()
    # ...and the graph's presentation name does NOT.
    from veritx_dse.model.topology_intent import ExplicitTopologyIntent
    from veritx_dse.model.topology_ir import TopologyIR
    g1 = TopologyIR(name="aaa", kind="custom", nodes=4,
                    links=[[0, 1], [1, 2], [2, 3]],
                    link_attrs={"bandwidth_GBs": 50.0, "latency_ns": 500.0})
    g2 = TopologyIR(name="zzz", kind="custom", nodes=4,
                    links=[[0, 1], [1, 2], [2, 3]],
                    link_attrs={"bandwidth_GBs": 50.0, "latency_ns": 500.0})
    assert (dataclasses.replace(a, topology=ExplicitTopologyIntent(graph=g1))
            .design_hash()
            == dataclasses.replace(
                a, topology=ExplicitTopologyIntent(graph=g2)).design_hash())


def test_v4_migration_provenance_is_not_design_science():
    r = _v4()
    assert r.migration_provenance is not None
    assert "migrated_from" not in json.dumps(r.canonical_dict())
    assert "migrated_from" in json.dumps(r.to_dict())


def test_v4_never_upgrades_implicitly_during_parsing():
    with pytest.raises(CompileRequestV4SchemaError, match="MIGRATED"):
        CompileRequestV4.from_dict(_v3_doc(topology_family=None, radix=None,
                                           concentration=None))
    # ...and a document that merely OMITS topology is refused too.
    d = _v4().to_dict()
    del d["topology"]
    with pytest.raises(CompileRequestV4SchemaError, match="MUST carry"):
        CompileRequestV4.from_dict(d)


# ══ §11 v4 strictness ═════════════════════════════════════════════════

def test_v4_refuses_unknown_top_level_fields():
    d = _v4().to_dict()
    d["noc_config"] = {}
    with pytest.raises(CompileRequestV4SchemaError, match="noc_config"):
        CompileRequestV4.from_dict(d)


def test_v4_refuses_a_missing_topology():
    d = _v4().to_dict()
    del d["topology"]
    with pytest.raises(CompileRequestV4SchemaError, match="MUST carry"):
        CompileRequestV4.from_dict(d)


def test_v4_refuses_unknown_topology_kind():
    d = _v4().to_dict()
    d["topology"] = {"kind": "dragonfly", "k": 8}
    with pytest.raises(CompileRequestV4SchemaError, match="unknown topology"):
        CompileRequestV4.from_dict(d)


def test_v4_refuses_unknown_fields_inside_a_topology_variant():
    d = _v4().to_dict()
    d["topology"] = {"kind": "mesh", "side_length": 4, "k": 4}
    with pytest.raises(CompileRequestV4SchemaError, match="unknown fields"):
        CompileRequestV4.from_dict(d)


def test_v4_refuses_shape_inside_noc_controls():
    d = _v4().to_dict()
    d["noc_controls"] = {"radix": 4}
    with pytest.raises(CompileRequestV4SchemaError, match="topology SHAPE"):
        CompileRequestV4.from_dict(d)


def test_v4_refuses_a_malformed_explicit_graph():
    d = _v4().to_dict()
    d["topology"] = {"kind": "explicit",
                     "graph": {"kind": "custom", "nodes": 4}}
    with pytest.raises(CompileRequestV4SchemaError, match="explicit"):
        CompileRequestV4.from_dict(d)


def test_v4_refuses_a_tampered_design_hash():
    d = _v4().to_dict()
    d["design_hash"] = "0" * 64
    with pytest.raises(CompileRequestV4SchemaError, match="design_hash"):
        CompileRequestV4.from_dict(d)


# ══ §13 migration matrix ══════════════════════════════════════════════

def test_migration_resolves_implicit_mesh_with_the_frozen_v3_sizing_law():
    r = migrate_v3_to_v4(_v3(topology_family=None, radix=None,
                             concentration=None))
    assert r.topology == MeshIntent(side_length=4, concentration=1)
    assert "frozen_v3_autosize" in r.migration_provenance["radix_resolution"]


def test_migration_preserves_an_explicit_v3_radix():
    r = migrate_v3_to_v4(_v3(topology_family="mesh", radix=2,
                             concentration=None))
    assert r.topology == MeshIntent(side_length=2, concentration=1)
    assert r.migration_provenance["radix_resolution"] == "explicit"


def test_migration_uses_the_frozen_concentrated_mesh_default():
    """NOT a live default: reading one would make a migration's meaning
    depend on when it ran."""
    r = migrate_v3_to_v4(_v3(topology_family="concentrated_mesh", radix=2,
                             concentration=None))
    assert r.topology.concentration == 4
    assert r.migration_provenance["concentration_resolution"] == \
        "frozen_v3_default_4"


def test_migration_preserves_torus_wrap_without_inventing_routing():
    r = migrate_v3_to_v4(_v3(topology_family="torus", radix=4,
                             concentration=None))
    assert r.topology.kind == "torus"
    assert set(r.topology.to_dict()) == {"kind", "side_length",
                                         "concentration"}


def test_migration_moves_the_graph_into_the_intent():
    doc = _v3_doc(topology_family=None, radix=None, concentration=None)
    doc["explicit_topology"] = {
        "name": "g16", "kind": "custom", "nodes": 16,
        "links": [[i, i + 1] for i in range(15)],
        "link_attrs": {"bandwidth_GBs": 50.0, "latency_ns": 500.0}}
    r = migrate_v3_to_v4(CompileRequestV3.from_dict(doc))
    assert isinstance(r.topology, ExplicitTopologyIntent)
    assert r.topology.graph.nodes == 16
    assert r.topology.graph.name == "g16"
    assert "g16" not in r.topology.intent_id()


def test_migration_REFUSES_gec_without_supplemental_facts():
    with pytest.raises(CompileRequestV4MigrationError,
                       match="does not determine"):
        migrate_v3_to_v4(_v3(topology_family="gec", radix=8,
                             concentration=1))


def test_migration_REFUSES_fattree_without_supplemental_facts():
    with pytest.raises(CompileRequestV4MigrationError,
                       match="does not determine"):
        migrate_v3_to_v4(_v3(topology_family="fat_tree", radix=4,
                             concentration=None))


def test_migration_accepts_supplied_facts_for_a_family_v3_could_not_express():
    mecs = GecTopologyIntent(
        mode=GecMode.MULTIDROP, grid_side_length=8, concentration=1,
        express_channel_groups_per_dimension=1,
        destinations_per_express_channel=7)
    r = migrate_v3_to_v4(_v3(topology_family="gec", radix=8,
                             concentration=1), topology_intent=mecs)
    assert r.topology == mecs
    assert r.topology.shares_express_channels is True


def test_migration_refuses_a_supplied_intent_that_contradicts_v3():
    with pytest.raises(CompileRequestV4MigrationError, match="contradicts"):
        migrate_v3_to_v4(_v3(topology_family="torus", radix=4,
                             concentration=None),
                         topology_intent=FatTreeIntent(switch_radix=4,
                                                       level_count=2))


def test_migration_refuses_two_topology_authorities():
    doc = _v3_doc(topology_family=None, radix=None, concentration=None)
    doc["explicit_topology"] = {
        "name": "g4", "kind": "custom", "nodes": 4,
        "links": [[0, 1], [1, 2], [2, 3]],
        "link_attrs": {"bandwidth_GBs": 50.0, "latency_ns": 500.0}}
    with pytest.raises(CompileRequestV4MigrationError, match="two authorities"):
        migrate_v3_to_v4(CompileRequestV3.from_dict(doc),
                         topology_intent=MeshIntent(side_length=4))


def test_migration_is_deterministic():
    v3 = _v3(topology_family=None, radix=None, concentration=None)
    a, b = migrate_v3_to_v4(v3), migrate_v3_to_v4(v3)
    assert a.design_hash() == b.design_hash()
    assert a.migration_provenance == b.migration_provenance


def test_migration_records_the_source_design_hash():
    v3 = _v3(topology_family=None, radix=None, concentration=None)
    assert migrate_v3_to_v4(v3).migration_provenance["source_design_hash"] \
        == v3.design_hash()


def test_migration_rejects_a_non_v3_request():
    with pytest.raises(CompileRequestV4MigrationError):
        migrate_v3_to_v4({"not": "a request"})       # type: ignore[arg-type]
