"""VCAssignmentArtifact tests — the explicit class-aware VC structure.

The VC artifact is semantics, not policy: it says which VCs exist, which
routing class each executes, which traffic classes may use them, which
transitions are allowed, and which VCs are designated escape VCs.
Deadlock/escape-network proof belongs to the later (channel, VC)
certification layer, so nothing here certifies deadlock freedom.

``derivation`` is provenance: same VC structure, different compiler story,
same ``vc_assignment_hash``.
"""
from __future__ import annotations

import pytest

from veritx_dse.core.artifact import content_id
from veritx_dse.core.route_artifact import ANYNET_MIN_HOPS, DOR_XY, RouteArtifact
from veritx_dse.model.attachment import derive_attachment
from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, ModelFamily, NocConfig, TopologyFamily,
    Workload,
)
from veritx_dse.model.placement import build_inventory
from veritx_dse.model.resolved_route import derive_resolved_route
from veritx_dse.model.topology_artifact import materialize_topology
from veritx_dse.model.vc_assignment import (
    VCAssignmentArtifact, VCAssignmentError, make_vc_assignment_artifact,
)

GOLDEN_ANYNET_1VC = (
    "22c7353f056e04e16b1de6337a3cb2af95aed9e586380d6c8cb99fed1ce5c3e4")
GOLDEN_ANYNET_2VC = (
    "f1ab335cb45c48aa558f241f6bebd214ed720eb612597f24b99fc9998bd51eb0")
GOLDEN_ANYNET_3VC = (
    "fd87506ac2fe762a913981f1520019db7941cac31556b38d07dac72f4459c8be")
GOLDEN_DOR_1VC = (
    "ee597b71eb45bb05d41af614b327b21083901b4f01e5fa26b2107f5ad3e9363a")
GOLDEN_DOR_2VC = (
    "28f27213d46345aed9774a7b531d0fe83a2d583998be204d29b20b414d507a0d")
GOLDEN_MULTI_CLASS = (
    "e7714b24374eb7741dbbf1edb254b6f85be163c58df9a89a5a21c8a0d91a30b5")


def _resolved(classes=(ANYNET_MIN_HOPS,)):
    cr = CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1, dp=1),
        requirements=[], agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=4)],
        dependencies=[], noc_config=NocConfig(topology_family=TopologyFamily.MESH))
    inv = build_inventory(cr)
    topo = materialize_topology(inv, cr)
    att = derive_attachment(design=cr, inventory=inv, topology=topo)
    rr = RouteArtifact.from_topology(topo, name="t", routing_classes=classes)
    return derive_resolved_route(topo, att, rr)


def _make(rra, **kw) -> VCAssignmentArtifact:
    kw.setdefault("derivation", "unit")
    return make_vc_assignment_artifact(resolved_route=rra, **kw)


@pytest.fixture(scope="module")
def rra():
    return _resolved()


@pytest.fixture(scope="module")
def rra_dor():
    return _resolved((DOR_XY,))


@pytest.fixture(scope="module")
def rra_both():
    return _resolved((ANYNET_MIN_HOPS, DOR_XY))


# ── golden compatibility fixtures ──────────────────────────────────────────

def test_golden_anynet_1vc(rra):
    art = _make(rra, vc_count=1, traffic_class_to_vcs={"default": [0]})
    assert art.vc_assignment_hash() == GOLDEN_ANYNET_1VC


def test_golden_anynet_2vc(rra):
    art = _make(rra, vc_count=2,
                traffic_class_to_vcs={"A": [0], "B": [1]})
    assert art.vc_assignment_hash() == GOLDEN_ANYNET_2VC


def test_golden_anynet_3vc(rra):
    art = _make(rra, vc_count=3,
                traffic_class_to_vcs={"A": [0, 1], "B": [2]})
    assert art.vc_assignment_hash() == GOLDEN_ANYNET_3VC


def test_golden_dor_1vc(rra_dor):
    art = _make(rra_dor, vc_count=1, traffic_class_to_vcs={"default": [0]})
    assert art.vc_assignment_hash() == GOLDEN_DOR_1VC


def test_golden_dor_2vc(rra_dor):
    art = _make(rra_dor, vc_count=2,
                traffic_class_to_vcs={"A": [0], "B": [1]})
    assert art.vc_assignment_hash() == GOLDEN_DOR_2VC


def test_golden_multi_class(rra_both):
    art = _make(rra_both, vc_count=2,
                traffic_class_to_vcs={"A": [0], "B": [1]},
                vc_to_routing_class={0: ANYNET_MIN_HOPS, 1: DOR_XY})
    assert art.vc_assignment_hash() == GOLDEN_MULTI_CLASS


# ── honest builder defaults and canonicalization ───────────────────────────

def test_one_vc_defaults_are_honest(rra):
    art = _make(rra, vc_count=1, traffic_class_to_vcs={"default": [0]})
    assert art.vc_count == 1
    assert art.vc_ids == (0,)
    assert art.vc_to_routing_class == ((0, ANYNET_MIN_HOPS),)
    assert art.allowed_transitions == ((0, 0),)
    assert art.escape_vcs == ()
    assert art.resolved_route_hash == rra.resolved_route_hash()


def test_multi_vc_defaults_are_honest(rra):
    art = _make(rra, vc_count=3,
                traffic_class_to_vcs={"A": [0], "B": [1, 2]})
    assert art.vc_ids == (0, 1, 2)
    assert art.vc_to_routing_class == ((0, ANYNET_MIN_HOPS),
                                       (1, ANYNET_MIN_HOPS),
                                       (2, ANYNET_MIN_HOPS))
    # VC-preserving transitions only, no invented escape VC.
    assert art.allowed_transitions == ((0, 0), (1, 1), (2, 2))
    assert art.escape_vcs == ()


def test_multi_class_binding_validates_against_parent(rra_both):
    art = _make(rra_both, vc_count=2,
                traffic_class_to_vcs={"A": [0], "B": [1]},
                vc_to_routing_class={0: ANYNET_MIN_HOPS, 1: DOR_XY})
    assert art.vc_to_routing_class == ((0, ANYNET_MIN_HOPS), (1, DOR_XY))
    assert art.validate_against(rra_both) is None


def test_builder_canonicalizes_class_and_vc_ordering(rra):
    art = _make(rra, vc_count=3,
                traffic_class_to_vcs={"B": [2], "A": [1, 0, 0]})
    assert art.traffic_class_to_vcs == (("A", (0, 1)), ("B", (2,)))


def test_builder_dedupes_and_sorts_transitions(rra):
    art = _make(rra, vc_count=2, traffic_class_to_vcs={"A": [0], "B": [1]},
                allowed_transitions=[(1, 1), (0, 0), (0, 0)])
    assert art.allowed_transitions == ((0, 0), (1, 1))


def test_builder_canonicalizes_escape_designation(rra):
    art = _make(rra, vc_count=2, traffic_class_to_vcs={"A": [0], "B": [1]},
                escape_vcs=[1, 0, 1])
    assert art.escape_vcs == (0, 1)


def test_mapping_and_pair_sequence_agree(rra_both):
    a = _make(rra_both, vc_count=2,
              traffic_class_to_vcs={"A": [0], "B": [1]},
              vc_to_routing_class={0: ANYNET_MIN_HOPS, 1: DOR_XY})
    b = _make(rra_both, vc_count=2,
              traffic_class_to_vcs=[("B", [1]), ("A", [0])],
              vc_to_routing_class=[(1, DOR_XY), (0, ANYNET_MIN_HOPS)])
    assert a.vc_assignment_hash() == b.vc_assignment_hash()


def test_derivation_is_provenance_not_identity(rra):
    a = _make(rra, vc_count=2, traffic_class_to_vcs={"A": [0], "B": [1]},
              derivation="two blocking dependency cycles")
    b = _make(rra, vc_count=2, traffic_class_to_vcs={"A": [0], "B": [1]},
              derivation="compiler pass 7 determined 2 VCs")
    assert a.vc_assignment_hash() == b.vc_assignment_hash()
    assert a.to_dict() != b.to_dict()
    assert a.to_dict()["derivation"] == "two blocking dependency cycles"
    loaded = VCAssignmentArtifact.from_dict(b.to_dict())
    assert loaded.derivation == "compiler pass 7 determined 2 VCs"
    assert loaded.vc_assignment_hash() == a.vc_assignment_hash()
    assert "derivation" not in a.identity_dict()


def test_identity_domain_is_explicit_and_bare(rra):
    art = _make(rra, vc_count=1, traffic_class_to_vcs={"default": [0]})
    assert art.vc_assignment_hash() == content_id(
        "srota/VCAssignmentArtifact/v1", art.identity_dict())
    assert len(art.vc_assignment_hash()) == 64
    assert not art.vc_assignment_hash().startswith("sha256:")


def test_escape_vcs_is_a_designation_only(rra):
    art = _make(rra, vc_count=2, traffic_class_to_vcs={"A": [0], "B": [1]},
                escape_vcs=(1,))
    assert art.escape_vcs == (1,)
    assert art.validate_against(rra) is None
    assert not hasattr(art, "deadlock_free")
    assert "proof" not in art.identity_dict()


# ── parent binding ─────────────────────────────────────────────────────────

def test_parent_is_pinned_and_validated(rra):
    art = _make(rra, vc_count=1, traffic_class_to_vcs={"default": [0]})
    assert art.resolved_route_hash == rra.resolved_route_hash()
    assert art.validate_against(rra) is None


def test_parent_mismatch_is_refused(rra, rra_dor):
    art = _make(rra, vc_count=1, traffic_class_to_vcs={"default": [0]})
    with pytest.raises(VCAssignmentError, match="resolved_route_hash"):
        art.validate_against(rra_dor)


def test_parent_hash_tamper_is_refused(rra):
    art = _make(rra, vc_count=1, traffic_class_to_vcs={"default": [0]})
    object.__setattr__(art, "resolved_route_hash", "0" * 64)
    with pytest.raises(VCAssignmentError, match="resolved_route_hash"):
        art.validate_against(rra)


def test_non_artifact_parent_is_refused(rra):
    with pytest.raises(VCAssignmentError, match="ResolvedRouteArtifact"):
        make_vc_assignment_artifact(
            resolved_route=object(), vc_count=1,
            traffic_class_to_vcs={"A": [0]}, derivation="unit")
    art = _make(rra, vc_count=1, traffic_class_to_vcs={"A": [0]})
    with pytest.raises(VCAssignmentError, match="ResolvedRouteArtifact"):
        art.validate_against(object())


def test_unknown_routing_class_is_refused(rra):
    with pytest.raises(VCAssignmentError, match="not defined"):
        _make(rra, vc_count=1, traffic_class_to_vcs={"A": [0]},
              vc_to_routing_class={0: "ESCAPE"})


# ── structural invariants ──────────────────────────────────────────────────

def _artifact(rra, **over) -> VCAssignmentArtifact:
    kw = dict(resolved_route_hash=rra.resolved_route_hash(), vc_count=2,
              vc_ids=(0, 1),
              traffic_class_to_vcs=(("A", (0,)), ("B", (1,))),
              vc_to_routing_class=((0, ANYNET_MIN_HOPS),
                                   (1, ANYNET_MIN_HOPS)),
              allowed_transitions=((0, 0), (1, 1)), escape_vcs=(),
              derivation="unit")
    kw.update(over)
    return VCAssignmentArtifact(**kw)


def test_sparse_vc_ids_are_refused(rra):
    with pytest.raises(VCAssignmentError, match="0..vc_count-1"):
        _artifact(rra, vc_ids=(0, 2))


def test_missing_vc_routing_is_refused(rra):
    with pytest.raises(VCAssignmentError, match="every VC exactly once"):
        _artifact(rra, vc_to_routing_class=((0, ANYNET_MIN_HOPS),))


def test_escape_out_of_range_is_refused(rra):
    with pytest.raises(VCAssignmentError, match="escape VC"):
        _artifact(rra, escape_vcs=(2,))


def test_unsorted_traffic_classes_are_refused(rra):
    with pytest.raises(VCAssignmentError, match="sorted by class name"):
        _artifact(rra, traffic_class_to_vcs=(("B", (1,)), ("A", (0,))))


def test_duplicate_traffic_classes_are_refused(rra):
    with pytest.raises(VCAssignmentError, match="declared twice"):
        _artifact(rra, traffic_class_to_vcs=(("A", (0,)), ("A", (1,))))


def test_empty_traffic_class_name_is_refused(rra):
    with pytest.raises(VCAssignmentError, match="non-empty strings"):
        _artifact(rra, traffic_class_to_vcs=(("", (0,)),))


def test_traffic_vc_set_out_of_range_is_refused(rra):
    with pytest.raises(VCAssignmentError, match="outside"):
        _artifact(rra, traffic_class_to_vcs=(("A", (0, 2)),))


def test_unsorted_transitions_are_refused(rra):
    with pytest.raises(VCAssignmentError, match="sorted and unique"):
        _artifact(rra, allowed_transitions=((1, 1), (0, 0)))


def test_duplicate_transitions_are_refused(rra):
    with pytest.raises(VCAssignmentError, match="sorted and unique"):
        _artifact(rra, allowed_transitions=((0, 0), (0, 0)))


def test_transition_out_of_range_is_refused(rra):
    with pytest.raises(VCAssignmentError, match="outside"):
        _artifact(rra, allowed_transitions=((0, 0), (0, 2)))


def test_vc_count_zero_is_refused(rra):
    with pytest.raises(VCAssignmentError, match=">= 1"):
        _artifact(rra, vc_count=0, vc_ids=(),
                  vc_to_routing_class=(), allowed_transitions=())


def test_bool_and_float_impostors_are_refused(rra):
    with pytest.raises(VCAssignmentError, match="must be an int"):
        _artifact(rra, vc_ids=(0, True))
    with pytest.raises(VCAssignmentError, match="must be an int"):
        _artifact(rra, vc_count=2.0)
    with pytest.raises(VCAssignmentError, match="must be an int"):
        _artifact(rra, traffic_class_to_vcs=(("A", (False,)), ("B", (1,))))
    with pytest.raises(VCAssignmentError, match="must be an int"):
        _artifact(rra, escape_vcs=(True,))


def test_allowed_transitions_must_be_an_immutable_tuple(rra):
    with pytest.raises(VCAssignmentError, match="must be a tuple"):
        _artifact(rra, allowed_transitions=[(0, 0), (1, 1)])


# ── strict persisted parsing ───────────────────────────────────────────────

def _valid_dict(rra) -> dict:
    return _make(rra, vc_count=2,
                 traffic_class_to_vcs={"A": [0], "B": [1]}).to_dict()


def test_roundtrip_preserves_hash_and_provenance(rra):
    art = _make(rra, vc_count=2, traffic_class_to_vcs={"A": [0], "B": [1]},
                derivation="round-trip")
    loaded = VCAssignmentArtifact.from_dict(art.to_dict())
    assert loaded.vc_assignment_hash() == art.vc_assignment_hash()
    assert loaded.identity_dict() == art.identity_dict()
    assert loaded.derivation == "round-trip"
    assert loaded.validate_against(rra) is None


@pytest.mark.parametrize("bad_type", [None, "srota/ResolvedRouteArtifact", 1])
def test_type_tag_is_strict(rra, bad_type):
    d = _valid_dict(rra)
    if bad_type is None:
        d.pop("type")
    else:
        d["type"] = bad_type
    with pytest.raises(VCAssignmentError, match="type"):
        VCAssignmentArtifact.from_dict(d)


def test_unknown_fields_are_refused(rra):
    d = _valid_dict(rra)
    d["extra"] = 1
    with pytest.raises(VCAssignmentError, match="unknown fields"):
        VCAssignmentArtifact.from_dict(d)


@pytest.mark.parametrize("field", [
    "type", "schema_version", "resolved_route_hash", "vc_count", "vc_ids",
    "traffic_class_to_vcs", "vc_to_routing_class", "allowed_transitions",
    "escape_vcs", "derivation", "artifact_hash",
])
def test_missing_required_fields_are_refused(rra, field):
    d = _valid_dict(rra)
    d.pop(field)
    with pytest.raises(VCAssignmentError, match="missing required field"):
        VCAssignmentArtifact.from_dict(d)


@pytest.mark.parametrize("bad", [2, True, "1", 1.0])
def test_schema_version_must_be_the_exact_int(rra, bad):
    d = _valid_dict(rra)
    d["schema_version"] = bad
    with pytest.raises(VCAssignmentError, match="schema_version"):
        VCAssignmentArtifact.from_dict(d)


@pytest.mark.parametrize("field,bad", [
    ("vc_ids", "01"),
    ("vc_ids", (0, 1)),
    ("vc_ids", {0: 1}),
    ("vc_ids", None),
    ("traffic_class_to_vcs", "A"),
    ("traffic_class_to_vcs", (("A", [0]),)),
    ("traffic_class_to_vcs", {"A": [0]}),
    ("vc_to_routing_class", "x"),
    ("vc_to_routing_class", ((0, ANYNET_MIN_HOPS),)),
    ("vc_to_routing_class", {}),
    ("allowed_transitions", "[0,0]"),
    ("allowed_transitions", ((0, 0),)),
    ("allowed_transitions", {}),
    ("escape_vcs", "0"),
    ("escape_vcs", (0,)),
    ("escape_vcs", {0: 1}),
])
def test_persisted_fields_must_be_json_lists(rra, field, bad):
    d = _valid_dict(rra)
    d[field] = bad
    with pytest.raises(VCAssignmentError):
        VCAssignmentArtifact.from_dict(d)


@pytest.mark.parametrize("field,row", [
    ("traffic_class_to_vcs", [["A"]]),
    ("traffic_class_to_vcs", [["A", [0], 1]]),
    ("traffic_class_to_vcs", [("A", [0])]),
    ("traffic_class_to_vcs", [["A", 0]]),
    ("traffic_class_to_vcs", [[0, [0]]]),
    ("traffic_class_to_vcs", [["A", [0]], [""]]),
    ("vc_to_routing_class", [[0]]),
    ("vc_to_routing_class", [[0, ANYNET_MIN_HOPS, 1]]),
    ("vc_to_routing_class", [(0, ANYNET_MIN_HOPS)]),
    ("vc_to_routing_class", [[0, 1]]),
    ("vc_to_routing_class", [["0", ANYNET_MIN_HOPS]]),
    ("allowed_transitions", [[0]]),
    ("allowed_transitions", [[0, 0, 1]]),
    ("allowed_transitions", [(0, 0)]),
    ("allowed_transitions", [["0", 0]]),
])
def test_persisted_pair_rows_must_be_two_element_lists(rra, field, row):
    d = _valid_dict(rra)
    d[field] = row
    with pytest.raises(VCAssignmentError):
        VCAssignmentArtifact.from_dict(d)


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(vc_ids=[0, True]),
    lambda d: d.update(escape_vcs=[False]),
    lambda d: d.update(traffic_class_to_vcs=[["A", [0]], ["B", [True]]]),
    lambda d: d.update(vc_to_routing_class=[["0", ANYNET_MIN_HOPS],
                                            [1, ANYNET_MIN_HOPS]]),
    lambda d: d.update(traffic_class_to_vcs=[["A", "0"], ["B", [1]]]),
    lambda d: d.update(escape_vcs=[1.0]),
])
def test_persisted_impostors_are_rejected_not_repaired(rra, mutate):
    d = _valid_dict(rra)
    mutate(d)
    with pytest.raises(VCAssignmentError):
        VCAssignmentArtifact.from_dict(d)


def test_persisted_artifact_hash_is_required_and_verified(rra):
    d = _valid_dict(rra)
    d.pop("artifact_hash")
    with pytest.raises(VCAssignmentError, match="missing required field"):
        VCAssignmentArtifact.from_dict(d)
    d = _valid_dict(rra)
    d["artifact_hash"] = ""
    with pytest.raises(VCAssignmentError, match="artifact_hash"):
        VCAssignmentArtifact.from_dict(d)
    d = _valid_dict(rra)
    d["artifact_hash"] = "0" * 64
    with pytest.raises(VCAssignmentError, match="artifact_hash"):
        VCAssignmentArtifact.from_dict(d)


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(vc_count=3),
    lambda d: d.update(vc_ids=[0, 1, 2]),
    lambda d: d.update(traffic_class_to_vcs=[["A", [1]], ["B", [1]]]),
    lambda d: d.update(allowed_transitions=[[0, 0]]),
    lambda d: d.update(escape_vcs=[1]),
    lambda d: d.update(vc_to_routing_class=[[0, ANYNET_MIN_HOPS],
                                            [1, ANYNET_MIN_HOPS]][::-1]),
])
def test_persisted_semantic_tamper_is_detected(rra, mutate):
    d = _valid_dict(rra)
    mutate(d)
    with pytest.raises(VCAssignmentError):
        VCAssignmentArtifact.from_dict(d)


@pytest.mark.parametrize("derivation", ["", 1, None])
def test_persisted_derivation_is_type_checked(rra, derivation):
    d = _valid_dict(rra)
    d["derivation"] = derivation
    with pytest.raises(VCAssignmentError, match="derivation"):
        VCAssignmentArtifact.from_dict(d)


# ── duplicate builder keys fail instead of collapsing ─────────────────────

def test_builder_refuses_duplicate_traffic_class_keys(rra):
    with pytest.raises(VCAssignmentError, match="more than once"):
        _make(rra, vc_count=2,
              traffic_class_to_vcs=[("A", [0]), ("A", [1]), ("B", [0])])


def test_builder_refuses_duplicate_vc_routing_keys(rra):
    with pytest.raises(VCAssignmentError, match="more than once"):
        _make(rra, vc_count=2, traffic_class_to_vcs={"A": [0], "B": [1]},
              vc_to_routing_class=[(0, ANYNET_MIN_HOPS),
                                   (0, ANYNET_MIN_HOPS)])


@pytest.mark.parametrize("kwargs", [
    dict(traffic_class_to_vcs=[("A",)]),
    dict(traffic_class_to_vcs="AB"),
    dict(traffic_class_to_vcs={"A": [0]}, vc_to_routing_class=[(0,)]),
    dict(traffic_class_to_vcs={"A": [0]}, vc_to_routing_class="AB"),
    dict(traffic_class_to_vcs={"A": [0]}, allowed_transitions=[(0, 0, 1)]),
    dict(traffic_class_to_vcs={"A": [0]}, allowed_transitions="call"),
])
def test_builder_refuses_malformed_authoring_rows(rra, kwargs):
    with pytest.raises(VCAssignmentError):
        _make(rra, vc_count=1, **kwargs)


# ── semantic changes move identity ────────────────────────────────────────

def test_each_semantic_field_changes_hash(rra_both):
    base = _make(rra_both, vc_count=2,
                 traffic_class_to_vcs={"A": [0], "B": [1]})
    variants = [
        _make(rra_both, vc_count=3,
              traffic_class_to_vcs={"A": [0], "B": [1]}),
        _make(rra_both, vc_count=2,
              traffic_class_to_vcs={"A": [1], "B": [1]}),
        _make(rra_both, vc_count=2,
              traffic_class_to_vcs={"A": [0], "B": [1]},
              vc_to_routing_class={0: ANYNET_MIN_HOPS, 1: DOR_XY}),
        _make(rra_both, vc_count=2, traffic_class_to_vcs={"A": [0], "B": [1]},
              allowed_transitions=[(0, 1)]),
        _make(rra_both, vc_count=2, traffic_class_to_vcs={"A": [0], "B": [1]},
              escape_vcs=(1,)),
    ]
    hashes = {base.vc_assignment_hash()} \
        | {v.vc_assignment_hash() for v in variants}
    assert len(hashes) == 6
