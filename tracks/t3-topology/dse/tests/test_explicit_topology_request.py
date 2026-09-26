"""Explicit topology as a first-class CompileRequest input (CFAB-1..CFAB-24).

TRANCHE 4. FAB-007 was: "CompileRequest cannot carry an explicit graph".
It is now resolved at the contract boundary, not by catching the exception.

The topology-selection law: a request expresses EXACTLY ONE topology source.

  NAMED     noc_config.topology_family names a family
  EXPLICIT  explicit_topology carries the graph as a TopologyIR (kind=custom)

Both materialize to the SAME TopologyArtifact, and nothing downstream may
care which produced it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.model.compile_model import (
    CompileRequestV3,
    CompileRequestV3SchemaError,
    NocConfig,
    TopologyFamily,
    fabric_intent_view,
)
from veritx_dse.model import topology_ir as tir
from veritx_dse.compiler.orchestration import derive_stages_v3

REPO = Path(__file__).resolve().parents[4]
V3_EXAMPLE = REPO / "tracks/t3-topology/examples/dense_1b_16tiles-v3.json"


def _doc(**kw) -> dict:
    d = json.loads(V3_EXAMPLE.read_text())
    d.pop("design_hash", None)
    d.pop("guardrail_hash", None)
    d.update(kw)
    return d


def _mesh_links(k: int):
    out = []
    for y in range(k):
        for x in range(k):
            n = y * k + x
            if x + 1 < k:
                out.append([n, n + 1])
            if y + 1 < k:
                out.append([n, n + k])
    return out


def _ir(k: int = 5, name: str = "explicit-mesh"):
    return tir.from_dict({
        "name": name, "kind": "custom", "nodes": k * k,
        "links": _mesh_links(k),
        "link_attrs": {"bandwidth_GBs": 50.0, "latency_ns": 500.0},
    })


def _explicit_doc(k: int = 5, name: str = "explicit-mesh") -> dict:
    d = _doc()
    d["explicit_topology"] = _ir(k, name).to_dict()
    d["noc_config"] = dict(d["noc_config"])
    d["noc_config"]["topology_family"] = None
    return d


# ══ CFAB-1 / CFAB-2: named identities unchanged ════════════════════════

def test_cfab_1_named_request_identity_unchanged():
    """The new field must not perturb the named path. Pinned against the
    value measured BEFORE the field existed."""
    r = CompileRequestV3.from_dict(_doc())
    assert r.explicit_topology is None
    assert r.design_hash().startswith("b1a2d760358da5c723df988bc88640b7")


def test_cfab_2_named_and_explicit_are_different_designs():
    named = CompileRequestV3.from_dict(_doc())
    explicit = CompileRequestV3.from_dict(_explicit_doc())
    assert named.design_hash() != explicit.design_hash(), \
        "a different topology SOURCE is a different design intent"


def test_cfab_2b_named_path_has_no_explicit_key():
    d = _doc()
    assert "explicit_topology" not in d
    assert "explicit_topology" not in CompileRequestV3.from_dict(d).to_dict()


# ══ CFAB-3: strict round trip ══════════════════════════════════════════

def test_cfab_3_explicit_round_trip_is_lossless():
    r = CompileRequestV3.from_dict(_explicit_doc())
    back = CompileRequestV3.from_dict(r.to_dict())
    assert back.design_hash() == r.design_hash()
    assert back.explicit_topology.links == r.explicit_topology.links
    assert back.explicit_topology.nodes == r.explicit_topology.nodes
    assert back.explicit_topology.link_attrs == r.explicit_topology.link_attrs


def test_cfab_3b_persistence_keeps_the_label_identity_drops_it():
    """to_dict is LOSSLESS (label kept); design identity EXCLUDES it."""
    d = _explicit_doc(name="authored-by-hand")
    r = CompileRequestV3.from_dict(d)
    assert r.to_dict()["explicit_topology"]["name"] == "authored-by-hand"
    assert "name" not in r.canonical_dict()["explicit_topology"]


# ══ CFAB-4 / CFAB-5: exactly one topology source ═══════════════════════

def test_cfab_4_named_plus_explicit_refuses():
    d = _explicit_doc()
    d["noc_config"] = dict(d["noc_config"])
    d["noc_config"]["topology_family"] = "mesh"     # both declared
    with pytest.raises(CompileRequestV3SchemaError) as e:
        CompileRequestV3.from_dict(d)
    assert "EXACTLY ONE topology source" in str(e.value)


def test_cfab_5_template_kind_refuses_as_explicit():
    """A named family must not sneak in through the explicit door."""
    d = _doc()
    template = tir.from_dict({
        "name": "m", "kind": "mesh", "nodes": 16, "params": {"k": 4, "n": 2},
        "link_attrs": {"bandwidth_GBs": 50.0, "latency_ns": 500.0}})
    d["explicit_topology"] = template.to_dict()
    with pytest.raises(CompileRequestV3SchemaError) as e:
        CompileRequestV3.from_dict(d)
    assert "TEMPLATE" in str(e.value)


# ══ CFAB-6: unknown fields refuse ══════════════════════════════════════

def test_cfab_6_unknown_explicit_fields_refuse():
    d = _explicit_doc()
    d["explicit_topology"] = dict(d["explicit_topology"])
    d["explicit_topology"]["surprise"] = 1
    with pytest.raises(CompileRequestV3SchemaError):
        CompileRequestV3.from_dict(d)


def test_cfab_6b_explicit_must_be_an_object():
    d = _explicit_doc()
    d["explicit_topology"] = "nope"
    with pytest.raises(CompileRequestV3SchemaError):
        CompileRequestV3.from_dict(d)


# ══ CFAB-7 / CFAB-8: graph science vs presentation ═════════════════════

def test_cfab_7_scientific_graph_change_changes_design_hash():
    base = CompileRequestV3.from_dict(_explicit_doc()).design_hash()
    # add one link
    d = _explicit_doc()
    d["explicit_topology"] = dict(d["explicit_topology"])
    d["explicit_topology"]["links"] = d["explicit_topology"]["links"] + [[0, 24]]
    assert CompileRequestV3.from_dict(d).design_hash() != base
    # change a scientific link attribute
    d2 = _explicit_doc()
    d2["explicit_topology"] = dict(d2["explicit_topology"])
    d2["explicit_topology"]["link_attrs"] = {"bandwidth_GBs": 64.0,
                                             "latency_ns": 500.0}
    assert CompileRequestV3.from_dict(d2).design_hash() != base


def test_cfab_8_presentation_layout_does_not_change_design_hash():
    """`name` is a LABEL. Two graphs differing only by name are one design."""
    a = CompileRequestV3.from_dict(_explicit_doc(name="authored-by-hand"))
    b = CompileRequestV3.from_dict(_explicit_doc(name="synthesized-abc123"))
    assert a.design_hash() == b.design_hash(), (
        "origin/label must not enter design identity — a synthesized "
        "candidate and the identical hand-authored graph are the same "
        "design science")


def test_cfab_8b_manual_and_synthesized_style_names_agree():
    """The exact §6 rule, stated as the two real producers."""
    manual = CompileRequestV3.from_dict(_explicit_doc(name="my-custom-graph"))
    synth = CompileRequestV3.from_dict(
        _explicit_doc(name="synthesized-0acbdc1acbe4"))
    assert manual.design_hash() == synth.design_hash()


# ══ CFAB-14..CFAB-19: compiler convergence ═════════════════════════════

def test_cfab_14_manual_custom_graph_enters_the_ordinary_compiler():
    _b, staged, refusal = derive_stages_v3(
        CompileRequestV3.from_dict(_explicit_doc(k=5)))
    if staged is not None:
        assert "TOPOLOGY" in staged.produced_stages
        assert staged.topology is not None
        assert staged.topology.family.value == "custom"


def test_cfab_15_16_manual_and_synthesized_produce_the_same_artifact():
    """The strongest convergence proof: same graph, different label, same
    TopologyArtifact."""
    from veritx_dse.model.topology_artifact import materialize_ir
    a = materialize_ir(_ir(5, "authored"), width_bits=64, latency_cycles=1)
    b = materialize_ir(_ir(5, "synthesized-xyz"), width_bits=64,
                       latency_cycles=1)
    assert a.topology_hash() == b.topology_hash()
    assert a.family == b.family


def test_cfab_17_18_both_origins_stop_at_the_same_stage():
    """Origin must not change capability. Both stop at ROUTING."""
    _b, staged, _r = derive_stages_v3(
        CompileRequestV3.from_dict(_explicit_doc(k=5)))
    assert staged is not None
    assert staged.stopped_at_stage == "ROUTING", (
        "the honest boundary after FAB-007 is ROUTING; if this moves the "
        "tranche conclusion must be re-derived")
    assert list(staged.produced_stages) == [
        "INPUT", "INPUT_MAPPING", "TOPOLOGY", "ATTACHMENT"]


def test_cfab_18b_route_refusal_is_typed():
    _b, staged, refusal = derive_stages_v3(
        CompileRequestV3.from_dict(_explicit_doc(k=5)))
    assert refusal is not None
    assert "no certified routing derivation" in str(refusal)
    assert "custom" in str(refusal)


def test_cfab_19_no_origin_specific_downstream_branch():
    """The artifact a custom graph produces is the SAME type a named family
    produces — no synthesis/custom subclass."""
    _b, staged, _r = derive_stages_v3(
        CompileRequestV3.from_dict(_explicit_doc(k=5)))
    art = staged.topology
    assert type(art).__name__ == "TopologyArtifact"
    keys = set(art.to_dict())
    from veritx_dse.model.topology_artifact import (
        MaterializedFamily, materialize_family,
    )
    mesh = materialize_family(MaterializedFamily.MESH, endpoint_count=16)
    assert keys == set(mesh.to_dict()), \
        "one artifact shape must serve every topology origin"


# ══ CFAB-20..CFAB-24: attachment and capacity ══════════════════════════

def test_cfab_21_excess_agents_refuse():
    """16 routers x 1 seat = 16 seats, but the design has 20 agents."""
    _b, staged, refusal = derive_stages_v3(
        CompileRequestV3.from_dict(_explicit_doc(k=4)))
    assert staged.stopped_at_stage == "ATTACHMENT"
    assert "seats" in str(refusal) and "agents must attach" in str(refusal)


def test_cfab_22_unused_seats_are_legal():
    """25 routers x 1 seat = 25 seats for 20 agents: 5 unused, and the
    pipeline proceeds past ATTACHMENT."""
    _b, staged, _r = derive_stages_v3(
        CompileRequestV3.from_dict(_explicit_doc(k=5)))
    assert "ATTACHMENT" in staged.produced_stages
    assert staged.attachment is not None


def test_cfab_24_no_fake_endpoints_for_unused_seats():
    _b, staged, _r = derive_stages_v3(
        CompileRequestV3.from_dict(_explicit_doc(k=5)))
    att = staged.attachment
    # Endpoints exist only for real agents.
    assert len(att.endpoints) == 20
    assert len(att.endpoints) < 25, "unused seats must not become endpoints"


# ══ CFAB-39 / CFAB-40: schema and parser discipline ════════════════════

def test_cfab_39_stale_design_hash_refuses():
    d = _explicit_doc()
    d["design_hash"] = "deadbeef"
    with pytest.raises(CompileRequestV3SchemaError):
        CompileRequestV3.from_dict(d)


def test_cfab_40_parser_does_not_assume_named_topology():
    """A request with topology_family=None and an explicit graph is valid;
    the parser must not require a family."""
    d = _explicit_doc()
    assert d["noc_config"]["topology_family"] is None
    r = CompileRequestV3.from_dict(d)
    assert r.noc_config.topology_family is None
    assert r.explicit_topology is not None
    assert fabric_intent_view(r).explicit_topology is not None


def test_cfab_40b_view_carries_the_explicit_source():
    r = CompileRequestV3.from_dict(_explicit_doc())
    assert fabric_intent_view(r).explicit_topology.links == \
        r.explicit_topology.links
