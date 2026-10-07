"""The single topology authority — and the conformance it must guarantee.

The bug: every consumer switched on the family name independently, so mesh
worked (it was first) while cmesh/flatfly compiled, certified and then
REFUSED at the system leg. These tests pin the fix — one registry, one
derivation, two independent witnesses — and pin the two specific defects
that made 4 of 5 families unusable:

  * `fabric_node_count` derived a node count for mesh/torus/anynet only;
  * the AstraSim input referenced `topology.anynet` without shipping it.
"""
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.model.family_registry import (
    BOOKSIM_TOPOLOGIES,
    EXPRESSIBLE_FAMILIES,
    FamilyRegistryError,
    resolve_node_count,
    terminal_node_count,
)

def test_mesh_and_torus_are_k_to_the_n():
    assert terminal_node_count("mesh", {"k": 4, "n": 2}) == 16
    assert terminal_node_count("torus", {"k": 3, "n": 3}) == 27

def test_cmesh_and_flatfly_are_c_times_k_to_the_n():
    assert terminal_node_count("cmesh", {"k": 2, "n": 2, "c": 4}) == 16
    assert terminal_node_count("flatfly", {"k": 4, "n": 2, "c": 1}) == 16

def test_gec_is_size_times_c():
    assert terminal_node_count("gec", {"size": 32, "c": 4}) == 128

def test_config_values_are_strings_so_the_reader_coerces():
    """parse_config_values returns raw text; a formula must not need ints."""
    assert terminal_node_count("cmesh", {"k": "2", "n": "2", "c": "4"}) == 16
    assert terminal_node_count("cmesh", {"k": " 2 ", "n": "2", "c": "4"}) == 16
    assert terminal_node_count("cmesh", {"k": "x", "n": "2", "c": "4"}) is None

def test_a_missing_value_yields_no_count_never_a_guess():
    assert terminal_node_count("cmesh", {"k": 2, "n": 2}) is None
    assert terminal_node_count("flatfly", {}) is None
    assert terminal_node_count("gec", {"c": 4}) is None

def test_anynet_has_no_formula_because_it_declares_its_nodes():
    assert terminal_node_count("anynet", {"k": 4, "n": 2}) is None

def test_every_registered_backend_name_is_a_real_booksim_topology():
    """A name BookSim's Network::New does not compare against builds nothing."""
    booksim_names = {
        "mesh", "torus", "cmesh", "fly", "qtree", "tree4", "fattree",
        "flatfly", "anynet", "dragonflynew", "gec", "srota",
    }
    assert set(BOOKSIM_TOPOLOGIES) == booksim_names
    for name, entry in BOOKSIM_TOPOLOGIES.items():
        assert entry.backend == name
        assert entry.source

@pytest.mark.parametrize("family", ["fly", "qtree", "tree4", "fattree"])
def test_the_fly_and_tree_families_share_meshs_formula(family):
    """fly.cpp:52, qtree.cpp:67, tree4.cpp:74, fattree.cpp:77 — every one
    is `_nodes = powi(_k, _n)`, the formula mesh already had. Registering
    them was free; leaving them out was an oversight, not a limit."""
    assert terminal_node_count(family, {"k": 4, "n": 2}) == 16
    assert terminal_node_count(family, {"k": 2, "n": 3}) == 8

def test_dragonfly_uses_its_own_group_formula():
    """dragonfly.cpp:199 `_nodes = _a * _p * _g` with
    `_a = 2p if n == 1 else p^n` and `_g = _a * _p + 1`."""
    assert terminal_node_count("dragonflynew", {"k": 2, "n": 1}) == 72
    assert terminal_node_count("dragonflynew", {"k": 3, "n": 1}) == 342
    assert terminal_node_count("dragonflynew", {"k": 1, "n": 1}) == 6
    assert terminal_node_count("dragonflynew", {"k": 2}) is None

def test_the_internal_gap_is_recorded_as_data_not_left_implicit():
    """Counting a family BookSim can build is necessary, not sufficient:
    VeritX has no TopologyIntent for four of the eleven, so they are
    registered and still unreachable. Keeping that as data means the gap is
    visible rather than implied by an absent entry."""
    assert EXPRESSIBLE_FAMILIES <= set(BOOKSIM_TOPOLOGIES)
    assert set(BOOKSIM_TOPOLOGIES) - EXPRESSIBLE_FAMILIES == {
        "fly", "qtree", "tree4", "dragonflynew", "srota"}

def test_agreement_returns_the_count_and_names_its_witness():
    count, witness = resolve_node_count(
        topology="cmesh", values={"k": 2, "n": 2, "c": 4}, endpoint_count=16)
    assert count == 16
    assert "cmesh.cpp" in witness

def test_a_partially_filled_network_is_normal_not_a_contradiction():
    """A 5x5 mesh offers 25 seats; a 17-agent design uses 17 of them.
    Equality would refuse every such design — which is exactly what broke
    134 tests when this check was first written."""
    count, witness = resolve_node_count(
        topology="mesh", values={"k": 5, "n": 2}, endpoint_count=17)
    assert count == 25
    assert "kncube.cpp" in witness

def test_a_network_smaller_than_what_is_attached_refuses():
    with pytest.raises(FamilyRegistryError, match="smaller than what is"):
        resolve_node_count(topology="cmesh",
                           values={"k": 2, "n": 2, "c": 4},
                           endpoint_count=17)

def test_an_unregistered_topology_refuses_and_names_the_file_to_extend():
    with pytest.raises(FamilyRegistryError, match="family_registry.py"):
        resolve_node_count(topology="made_up_topo", values={},
                           endpoint_count=16)

def test_an_unregistered_topology_falls_back_when_the_config_is_silent():
    """A registered topology whose config lacks the values still resolves —
    from the attachment plan, which is what BookSim will build."""
    count, witness = resolve_node_count(
        topology="gec", values={}, endpoint_count=128)
    assert count == 128
    assert "attachment plan" in witness

def test_a_zero_endpoint_plan_refuses():
    with pytest.raises(FamilyRegistryError, match="cannot be that small"):
        resolve_node_count(topology="mesh", values={"k": 4, "n": 2},
                           endpoint_count=0)

@pytest.mark.parametrize("topology,values,expected", [
    ("mesh", {"k": 4, "n": 2}, 16),
    ("torus", {"k": 4, "n": 2}, 16),
    ("cmesh", {"k": 2, "n": 2, "c": 4}, 16),
    ("flatfly", {"k": 4, "n": 2, "c": 1}, 16),
    ("gec", {"size": 16, "c": 8}, 128),
])
def test_every_shipped_family_resolves_a_sys_namespace(topology, values,
                                                       expected):
    """Before this, only mesh/torus/anynet could; cmesh and flatfly raised
    'cannot derive the ASTRA Sys namespace' AFTER compiling and certifying."""
    count, _ = resolve_node_count(topology=topology, values=values,
                                  endpoint_count=expected)
    assert count == expected


# ── one table, three vocabularies ─────────────────────────────────────────

from veritx_dse.model.family_registry import (
    MATERIALIZED_FAMILIES,
    TOPOLOGY_FAMILIES,
    declared_family_names,
    families_for_backend,
    family_for_backend,
    family_for_ir_kind,
    migration_gaps,
)


def test_the_three_vocabularies_are_now_mapped():
    """`topology_ir.KINDS`, `MaterializedFamily` and BookSim's dispatch table
    were three unsynchronized name lists. Every name must now resolve."""
    gaps = migration_gaps()
    assert gaps["ir_kinds_without_a_family"] == [], gaps
    assert gaps["booksim_backends_without_a_family"] == [], gaps


def test_every_canonical_family_has_a_real_booksim_backend():
    from veritx_dse.model.family_registry import BOOKSIM_TOPOLOGIES
    for name, spec in TOPOLOGY_FAMILIES.items():
        assert spec["backend"] in BOOKSIM_TOPOLOGIES, name
        assert spec["routing"], name


def test_the_renames_are_now_recorded():
    """These pairs were the same topology under two names, with nothing
    anywhere saying so."""
    assert family_for_backend("cmesh") == "concentrated_mesh"
    assert family_for_backend("fly") == "flattened_butterfly"
    assert family_for_backend("dragonflynew") == "dragonfly"
    # many-to-one: the registry names these apart, BookSim does not
    assert families_for_backend("gec") == ("gec", "gec_mecs", "gec_express")
    assert families_for_backend("torus") == ("torus", "ring")


def test_ir_kinds_resolve_to_their_family():
    assert family_for_ir_kind("mesh") == "mesh"
    assert family_for_ir_kind("ring") == "ring"   # renders as a 1-D torus
    assert family_for_ir_kind("custom") == "custom"


def test_materialized_families_match_the_enum():
    from veritx_dse.model.topology_artifact import MaterializedFamily
    assert MATERIALIZED_FAMILIES == {m.value for m in MaterializedFamily}


def test_the_table_preserves_the_edge_counts_it_replaces():
    """Migration safety: the descriptor must reproduce
    `presets._default_edge_count` exactly for every family it covers."""
    from veritx_dse.model.presets import _default_edge_count
    cases = [
        ("mesh", {"k": 4, "n": 2}), ("torus", {"k": 4, "n": 2}),
        ("flatfly", {"k": 4, "n": 2, "c": 4}),
        ("gec", {"k": 8, "o": 7, "d": 1}), ("gec", {"k": 8, "o": 1, "d": 7}),
        ("gec", {"k": 8, "mesh": True}),
        ("fly", {"k": 4, "n": 3}), ("cmesh", {"k": 4, "n": 2}),
        ("fattree", {"k": 4, "n": 3}), ("qtree", {"k": 4, "n": 3}),
        ("tree4", {"k": 4, "n": 3}), ("dragonflynew", {"k": 2}),
    ]
    for backend, params in cases:
        name = family_for_backend(backend)
        assert name is not None, backend
        mine = TOPOLOGY_FAMILIES[name]["edges"](params)
        assert mine == _default_edge_count(backend, params), (backend, params)


def test_the_table_agrees_with_the_declared_registry():
    """The YAML is the naming authority. This module must not invent names."""
    declared = set(declared_family_names())
    mine = set(TOPOLOGY_FAMILIES)
    assert declared <= mine, sorted(declared - mine)
    # tree4 was claimed by the registry (§3.2); star/switch remain the
    # known-unclaimed backend spellings.
    assert mine - declared == {"star", "switch"}, sorted(
        mine - declared)


def test_the_one_backend_the_registry_does_not_claim_is_recorded():
    """Every BookSim backend spelling is claimed by the declared registry.
    tree4 was the single remaining gap and is now claimed (§3.2); an empty
    list is the assertion, not an absence of checking."""
    gaps = migration_gaps()
    assert gaps["ir_kinds_without_a_family"] == []
    assert gaps["booksim_backends_without_a_family"] == []
    assert gaps["booksim_backends_not_claimed_by_the_registry"] == []


# ── the migrated consumers ────────────────────────────────────────────────

def test_gec_modes_match_the_enum_they_were_copied_from():
    """`modes` is a copy of GecMode's values, made for a layer that cannot
    import the enum. A copy needs a drift guard."""
    from veritx_dse.model.topology_intent import GecMode
    from veritx_dse.model.family_registry import spec_for
    assert set(spec_for("gec")["modes"]) == {m.value for m in GecMode}


def test_spec_for_fills_defaults_for_unknown_names():
    from veritx_dse.model.family_registry import spec_for
    spec = spec_for("not_a_topology")
    assert spec["family"] is None
    assert spec["noc_latency_zero"] is False
    assert spec["rendered_graph"] is False
    assert spec["vcs_from_multidrop"] is False


def test_anynet_backed_families_are_marked_as_rendered_graphs():
    from veritx_dse.model.family_registry import spec_for
    assert spec_for("anynet")["rendered_graph"] is True
    assert spec_for("mesh")["rendered_graph"] is False


def test_only_gec_derives_vcs_from_multidrop():
    from veritx_dse.model.family_registry import spec_for
    assert spec_for("gec")["vcs_from_multidrop"] is True
    assert spec_for("mesh")["vcs_from_multidrop"] is False


def test_edge_and_node_counts_accept_both_spellings():
    from veritx_dse.model.family_registry import edge_count, node_count
    for canonical, backend in (("concentrated_mesh", "cmesh"),
                               ("flattened_butterfly", "fly"),
                               ("fat_tree", "fattree")):
        assert edge_count(canonical, {}) == edge_count(backend, {}), canonical
        assert node_count(canonical, {}) == node_count(backend, {}), canonical


def test_the_consumer_tables_are_derived_not_hand_kept():
    """These were three separate hand-written tables. They must agree."""
    from veritx_dse.model.topology_ir import ANALYTICAL_TOPO, DEFAULT_ROUTING
    from veritx_dse.model.family_registry import TOPOLOGY_FAMILIES
    for family, spec in TOPOLOGY_FAMILIES.items():
        for kind in spec["ir_kinds"]:
            assert DEFAULT_ROUTING[kind] == spec["routing"], kind
            assert ANALYTICAL_TOPO[kind] == spec["analytical"], kind
