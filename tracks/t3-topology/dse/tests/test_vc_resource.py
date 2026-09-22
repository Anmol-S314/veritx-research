"""VCResourceArtifact tests — routing-independent concrete VC resources.

The artifact owns only the VC universe, traffic-class eligibility and
concrete VC transitions. Routing classes, roles, escape designations,
topology and design identity are all outside its authority.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect

import pytest

from veritx_dse.core.route_artifact import ANYNET_MIN_HOPS, DOR_XY, RouteArtifact
from veritx_dse.model import vc_resource as vr
from veritx_dse.model.attachment import derive_attachment
from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, ModelFamily, NocConfig, TopologyFamily,
    Workload,
)
from veritx_dse.model.placement import build_inventory
from veritx_dse.model.resolved_route import derive_resolved_route
from veritx_dse.model.topology_artifact import materialize_topology
from veritx_dse.model.vc_assignment import make_vc_assignment_artifact
from veritx_dse.model.vc_resource import (
    VCResourceArtifact, VCResourceError, vc_resources_from_assignment,
)

GOLDEN_ONE_VC = (
    "39cdc47227d5bde77438b2da2599a84f2f7a6e17f85a7d2906a647818baeb387")
GOLDEN_MIN_ADAPT = (
    "3edd5a2067e4f25e7c51dbd109f2647b0c3717d2c4223d135523cd655e93916e")
GOLDEN_SEPARATED = (
    "15dd9421b26bf07c089b00f670e2e8b212f3265f455158fb8f711e558c14ef22")

EXPECTED_FIELDS = {
    "vc_count", "vc_ids", "traffic_class_to_vcs", "allowed_transitions",
    "derivation", "schema_version", "artifact_hash",
}

FORBIDDEN_TOKENS = (
    "resolved_route_hash", "route_hash", "policy_hash", "relation_hash",
    "topology_hash", "routing_class", "routing_role", "escape_vcs",
    "channel_id", "endpoint_id", "router_id", "booksim", "backend",
    "verdict", "certificate", "deadlock",
)

_MIN_ADAPT_TRANSITIONS = (
    (0, 0),
    (1, 0), (1, 1), (1, 2), (1, 3),
    (2, 0), (2, 1), (2, 2), (2, 3),
    (3, 0), (3, 1), (3, 2), (3, 3),
)


def _one_vc(**over) -> VCResourceArtifact:
    kw = dict(vc_count=1, vc_ids=(0,),
              traffic_class_to_vcs=(("default", (0,)),),
              allowed_transitions=((0, 0),), derivation="one-vc")
    kw.update(over)
    return VCResourceArtifact(**kw)


def _min_adapt_resources(**over) -> VCResourceArtifact:
    kw = dict(vc_count=4, vc_ids=(0, 1, 2, 3),
              traffic_class_to_vcs=(("default", (0, 1, 2, 3)),),
              allowed_transitions=_MIN_ADAPT_TRANSITIONS,
              derivation="min-adapt-like")
    kw.update(over)
    return VCResourceArtifact(**kw)


def _separated(**over) -> VCResourceArtifact:
    kw = dict(vc_count=2, vc_ids=(0, 1),
              traffic_class_to_vcs=(("A", (0,)), ("B", (1,))),
              allowed_transitions=((0, 0), (1, 1)), derivation="separated")
    kw.update(over)
    return VCResourceArtifact(**kw)


def _shared(**over) -> VCResourceArtifact:
    kw = dict(vc_count=3, vc_ids=(0, 1, 2),
              traffic_class_to_vcs=(("A", (0, 1)), ("B", (1, 2))),
              allowed_transitions=((0, 0), (1, 1), (2, 2)),
              derivation="shared")
    kw.update(over)
    return VCResourceArtifact(**kw)


# ── golden hashes ──────────────────────────────────────────────────────────

def test_one_vc_hash_is_pinned():
    assert _one_vc().artifact_hash == GOLDEN_ONE_VC


def test_min_adapt_like_hash_is_pinned():
    assert _min_adapt_resources().artifact_hash == GOLDEN_MIN_ADAPT


def test_protocol_separated_hash_is_pinned():
    assert _separated().artifact_hash == GOLDEN_SEPARATED


def test_hashes_are_bare_64_hex():
    for artifact in (_one_vc(), _min_adapt_resources(), _separated()):
        assert len(artifact.artifact_hash) == 64
        assert not artifact.artifact_hash.startswith("sha256:")


@pytest.mark.parametrize("factory", [_one_vc, _min_adapt_resources,
                                     _separated, _shared])
def test_round_trip_is_lossless(factory):
    artifact = factory()
    restored = VCResourceArtifact.from_dict(artifact.to_dict())
    assert restored.artifact_hash == artifact.artifact_hash
    assert restored.to_dict() == artifact.to_dict()
    assert restored == artifact


# ── MinAdapt-like concrete resource fixture ────────────────────────────────

def test_min_adapt_like_transition_structure():
    artifact = _min_adapt_resources()
    assert artifact.vc_ids == (0, 1, 2, 3)
    assert artifact.traffic_class_to_vcs == (("default", (0, 1, 2, 3)),)
    transitions = set(artifact.allowed_transitions)
    assert (0, 0) in transitions
    for source in (1, 2, 3):
        assert transitions >= {(source, 0), (source, 1), (source, 2),
                               (source, 3)}
    assert len(transitions) == 13
    # No escape/adaptive labels exist anywhere in the semantic payload.
    assert "escape" not in str(artifact.to_dict()).lower()
    assert "adaptive" not in str(artifact.to_dict()).lower()


def test_shared_multi_vc_traffic_keeps_eligibility_separate():
    artifact = _shared()
    by_class = dict(artifact.traffic_class_to_vcs)
    assert by_class["A"] == (0, 1)
    assert by_class["B"] == (1, 2)
    assert set(by_class["A"]) & set(by_class["B"]) == {1}


# ── invariants ─────────────────────────────────────────────────────────────

def test_sparse_or_short_vc_ids_are_refused():
    with pytest.raises(VCResourceError, match="0..vc_count-1"):
        _min_adapt_resources(vc_ids=(0, 1, 2, 4))
    with pytest.raises(VCResourceError, match="0..vc_count-1"):
        _min_adapt_resources(vc_ids=(0, 1, 2))


def test_vc_id_types_are_strict():
    with pytest.raises(VCResourceError, match="exact int"):
        _min_adapt_resources(vc_ids=(0, 1, 2, True))
    with pytest.raises(VCResourceError, match="exact int"):
        _min_adapt_resources(vc_ids=(0, 1, 2, "3"))


def test_vc_count_is_strict():
    with pytest.raises(VCResourceError, match=">= 1"):
        _one_vc(vc_count=0, vc_ids=())
    with pytest.raises(VCResourceError, match="exact int"):
        _one_vc(vc_count=True, vc_ids=(0,))


def test_traffic_class_name_rules():
    with pytest.raises(VCResourceError, match="non-empty string"):
        _one_vc(traffic_class_to_vcs=(("", (0,)),))
    with pytest.raises(VCResourceError, match="non-empty string"):
        _one_vc(traffic_class_to_vcs=((1, (0,)),))
    with pytest.raises(VCResourceError, match="unique"):
        _separated(traffic_class_to_vcs=(("A", (0,)), ("A", (1,))))


def test_traffic_vc_set_rules():
    with pytest.raises(VCResourceError, match="non-empty VC set"):
        _one_vc(traffic_class_to_vcs=(("default", ()),))
    with pytest.raises(VCResourceError, match="duplicate"):
        _min_adapt_resources(
            traffic_class_to_vcs=(("default", (0, 0, 1, 2, 3)),))
    with pytest.raises(VCResourceError, match="outside"):
        _min_adapt_resources(
            traffic_class_to_vcs=(("default", (0, 1, 2, 4)),))
    with pytest.raises(VCResourceError, match="exact int"):
        _min_adapt_resources(
            traffic_class_to_vcs=(("default", (0, 1, 2, "3")),))


def test_transition_rules():
    with pytest.raises(VCResourceError, match="outside"):
        _separated(allowed_transitions=((0, 0), (1, 2)))
    with pytest.raises(VCResourceError, match="unique"):
        _separated(allowed_transitions=((0, 0), (0, 0)))
    with pytest.raises(VCResourceError, match="pairs"):
        _separated(allowed_transitions=((0, 0, 1),))
    with pytest.raises(VCResourceError, match="exact int"):
        _separated(allowed_transitions=((True, 0),))


def test_identity_transitions_are_not_required():
    artifact = _separated(allowed_transitions=())
    assert artifact.allowed_transitions == ()
    assert artifact.artifact_hash != _separated().artifact_hash


def test_uninjectable_vc_is_allowed():
    artifact = VCResourceArtifact(
        vc_count=2, vc_ids=(0, 1),
        traffic_class_to_vcs=(("A", (0,)),),
        allowed_transitions=((0, 1), (1, 1)), derivation="escape-only")
    assert 1 not in dict(artifact.traffic_class_to_vcs)["A"]
    assert (0, 1) in artifact.allowed_transitions


def test_derivation_is_provenance_not_identity():
    left = _separated(derivation="compiler pass 1")
    right = _separated(derivation="handwritten for tests")
    assert left.artifact_hash == right.artifact_hash
    assert left.to_dict() != right.to_dict()
    assert left.to_dict()["derivation"] == "compiler pass 1"
    assert right.derivation == "handwritten for tests"
    loaded = VCResourceArtifact.from_dict(right.to_dict())
    assert loaded.derivation == "handwritten for tests"
    assert loaded.artifact_hash == left.artifact_hash


def test_semantic_mutations_change_hash():
    base = _separated()
    variants = [
        VCResourceArtifact(vc_count=3, vc_ids=(0, 1, 2),
                           traffic_class_to_vcs=(("A", (0,)), ("B", (1,))),
                           allowed_transitions=((0, 0), (1, 1))),
        _separated(traffic_class_to_vcs=(("A", (0,)), ("B", (0,)))),
        _separated(allowed_transitions=((0, 0),)),
        _separated(traffic_class_to_vcs=(("A", (0,)), ("C", (1,)))),
    ]
    assert len({base.artifact_hash} | {v.artifact_hash for v in variants}) == 5


def test_construction_order_does_not_move_hash():
    canonical = _shared()
    reordered = VCResourceArtifact(
        vc_count=3, vc_ids=(0, 1, 2),
        traffic_class_to_vcs=(("B", (2, 1)), ("A", (1, 0))),
        allowed_transitions=((2, 2), (0, 0), (1, 1)),
        derivation="shared")
    assert reordered.artifact_hash == canonical.artifact_hash
    assert reordered.to_dict() == canonical.to_dict()


# ── strict persisted parsing ───────────────────────────────────────────────

def _valid_dict() -> dict:
    return _separated().to_dict()


def test_unknown_fields_are_refused():
    d = _valid_dict()
    d["extra"] = 1
    with pytest.raises(VCResourceError, match="unknown fields"):
        VCResourceArtifact.from_dict(d)


@pytest.mark.parametrize("field", sorted(EXPECTED_FIELDS | {"type"}))
def test_missing_required_fields_are_refused(field):
    d = _valid_dict()
    d.pop(field)
    with pytest.raises(VCResourceError):
        VCResourceArtifact.from_dict(d)


@pytest.mark.parametrize("bad", [None, "srota/RouteArtifact", 3])
def test_type_tag_is_strict(bad):
    d = _valid_dict()
    if bad is None:
        d.pop("type")
    else:
        d["type"] = bad
    with pytest.raises(VCResourceError, match="type"):
        VCResourceArtifact.from_dict(d)


@pytest.mark.parametrize("bad", [2, True, "1", 1.0])
def test_schema_version_is_strict(bad):
    d = _valid_dict()
    d["schema_version"] = bad
    with pytest.raises(VCResourceError, match="schema_version"):
        VCResourceArtifact.from_dict(d)


@pytest.mark.parametrize("bad", ["01", (0, 1), {0: 1}, [0, True], [0, "1"]])
def test_persisted_vc_ids_are_strict(bad):
    d = _valid_dict()
    d["vc_ids"] = bad
    with pytest.raises(VCResourceError):
        VCResourceArtifact.from_dict(d)


@pytest.mark.parametrize("bad", [
    [["A"]],
    [["A", [0], 1]],
    [("A", [0]), ("B", [1])],
    [["A", 0]],
    [[1, [0]]],
    [["A", "0"]],
    [["B", [1]], ["A", [0]]],
    [["A", [0]], ["A", [1]]],
    [["A", [1, 0]], ["B", [1]]],
    [["A", [0, 0]], ["B", [1]]],
])
def test_persisted_traffic_rows_are_strict(bad):
    d = _valid_dict()
    d["traffic_class_to_vcs"] = bad
    with pytest.raises(VCResourceError):
        VCResourceArtifact.from_dict(d)


@pytest.mark.parametrize("bad", [
    [[0]],
    [[0, 1, 2]],
    [(0, 0), (1, 1)],
    [["0", 0]],
    [[True, 0]],
    [[0, 0], [0, 0]],
    [[1, 1], [0, 0]],
    {"0": 1},
])
def test_persisted_transition_rows_are_strict(bad):
    d = _valid_dict()
    d["allowed_transitions"] = bad
    with pytest.raises(VCResourceError):
        VCResourceArtifact.from_dict(d)


def test_persisted_hash_and_derivation_are_strict():
    d = _valid_dict()
    d.pop("artifact_hash")
    with pytest.raises(VCResourceError, match="missing required field"):
        VCResourceArtifact.from_dict(d)
    d = _valid_dict()
    d["artifact_hash"] = ""
    with pytest.raises(VCResourceError, match="artifact_hash"):
        VCResourceArtifact.from_dict(d)
    d = _valid_dict()
    d["artifact_hash"] = "0" * 64
    with pytest.raises(VCResourceError, match="artifact_hash"):
        VCResourceArtifact.from_dict(d)
    d = _valid_dict()
    d["derivation"] = 7
    with pytest.raises(VCResourceError, match="derivation"):
        VCResourceArtifact.from_dict(d)


def test_constructor_rejects_stored_hash_mismatch():
    with pytest.raises(VCResourceError, match="artifact_hash"):
        _separated(artifact_hash="deadbeef")


# ── immutability ───────────────────────────────────────────────────────────

def test_artifact_is_frozen_and_tuple_backed():
    artifact = _separated()
    with pytest.raises(dataclasses.FrozenInstanceError):
        artifact.vc_count = 3
    assert isinstance(artifact.vc_ids, tuple)
    assert isinstance(artifact.traffic_class_to_vcs, tuple)
    assert isinstance(artifact.allowed_transitions, tuple)
    with pytest.raises(TypeError):
        artifact.traffic_class_to_vcs[0] = ("C", (0,))


def test_mutable_inputs_are_refused_not_aliased():
    with pytest.raises(VCResourceError, match="tuple"):
        VCResourceArtifact(
            vc_count=1, vc_ids=[0],
            traffic_class_to_vcs=(("default", (0,)),))
    with pytest.raises(VCResourceError, match="pairs"):
        VCResourceArtifact(
            vc_count=1, vc_ids=(0,),
            traffic_class_to_vcs=[["default", [0]]])


def test_to_dict_returns_fresh_data():
    artifact = _min_adapt_resources()
    first = artifact.to_dict()
    first["vc_ids"].append(9)
    first["traffic_class_to_vcs"][0][1].append(3)
    first["allowed_transitions"].clear()
    second = artifact.to_dict()
    assert second["vc_ids"] == [0, 1, 2, 3]
    assert second["traffic_class_to_vcs"] == [["default", [0, 1, 2, 3]]]
    assert len(second["allowed_transitions"]) == 13
    assert artifact.artifact_hash == GOLDEN_MIN_ADAPT


# ── Slice-8 compatibility projection ───────────────────────────────────────

def _resolved_route(classes=(ANYNET_MIN_HOPS,)):
    cr = CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1, dp=1),
        requirements=[], agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=4)],
        dependencies=[], noc_config=NocConfig(
            topology_family=TopologyFamily.MESH))
    inv = build_inventory(cr)
    topo = materialize_topology(inv, cr)
    att = derive_attachment(design=cr, inventory=inv, topology=topo)
    rr = RouteArtifact.from_topology(topo, name="t", routing_classes=classes)
    return derive_resolved_route(topo, att, rr)


def _assignment(resolved_route, **over):
    kw = dict(
        resolved_route=resolved_route, vc_count=4,
        traffic_class_to_vcs={"default": [0, 1, 2, 3]},
        allowed_transitions=list(_MIN_ADAPT_TRANSITIONS),
        vc_to_routing_class={vc: ANYNET_MIN_HOPS for vc in range(4)},
        escape_vcs=(), derivation="projection-test")
    kw.update(over)
    return make_vc_assignment_artifact(**kw)


def test_projection_copies_only_generic_resources():
    assignment = _assignment(
        _resolved_route((ANYNET_MIN_HOPS, DOR_XY)),
        vc_to_routing_class={0: ANYNET_MIN_HOPS, 1: DOR_XY,
                             2: ANYNET_MIN_HOPS, 3: DOR_XY},
        escape_vcs=(3,), derivation="provenance text")
    projected = vc_resources_from_assignment(assignment)
    assert projected.vc_count == assignment.vc_count
    assert projected.vc_ids == assignment.vc_ids
    assert projected.traffic_class_to_vcs == assignment.traffic_class_to_vcs
    assert projected.allowed_transitions == assignment.allowed_transitions
    assert projected.derivation == "provenance text"
    assert projected.artifact_hash == GOLDEN_MIN_ADAPT
    assert VCResourceArtifact.from_dict(projected.to_dict()) == projected


def test_routing_class_and_escape_changes_do_not_move_projected_identity():
    resolved = _resolved_route((ANYNET_MIN_HOPS, DOR_XY))
    left = _assignment(resolved,
                       vc_to_routing_class={vc: ANYNET_MIN_HOPS
                                            for vc in range(4)},
                       escape_vcs=())
    right = _assignment(resolved,
                        vc_to_routing_class={0: DOR_XY, 1: DOR_XY,
                                             2: ANYNET_MIN_HOPS,
                                             3: ANYNET_MIN_HOPS},
                        escape_vcs=(0, 1))
    assert left.vc_assignment_hash() != right.vc_assignment_hash()
    projected_left = vc_resources_from_assignment(left)
    projected_right = vc_resources_from_assignment(right)
    assert projected_left.artifact_hash == projected_right.artifact_hash


def test_projection_is_independent_of_the_resolved_route_parent():
    both = _resolved_route((ANYNET_MIN_HOPS, DOR_XY))
    single = _resolved_route((ANYNET_MIN_HOPS,))
    left = _assignment(both)
    right = _assignment(single)
    assert left.resolved_route_hash != right.resolved_route_hash
    assert vc_resources_from_assignment(left).artifact_hash \
        == vc_resources_from_assignment(right).artifact_hash


def test_projection_refuses_non_assignment_values():
    with pytest.raises(VCResourceError, match="VCAssignmentArtifact"):
        vc_resources_from_assignment(object())
    with pytest.raises(VCResourceError, match="VCAssignmentArtifact"):
        vc_resources_from_assignment(_separated())


# ── scope sentinels ────────────────────────────────────────────────────────

def test_schema_has_no_routing_or_topology_fields():
    names = {f.name for f in dataclasses.fields(VCResourceArtifact)}
    assert names == EXPECTED_FIELDS
    for token in FORBIDDEN_TOKENS:
        assert token not in " ".join(names)
    for artifact in (_one_vc(), _min_adapt_resources(), _separated(), _shared()):
        d = artifact.to_dict()
        assert set(d) == EXPECTED_FIELDS | {"type"}
        blob = str(d).lower()
        for token in FORBIDDEN_TOKENS:
            assert token not in blob


def test_module_imports_only_core_and_vc_assignment():
    tree = ast.parse(inspect.getsource(vr))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    local = {name for name in imported
             if name.startswith("veritx_dse")}
    assert local == {"veritx_dse.core.artifact",
                     "veritx_dse.model.vc_assignment"}
    forbidden = ("routing_policy", "routing_relation", "route_artifact",
                 "topology_artifact", "verification", "backend", "booksim",
                 "astra")
    for name in imported:
        assert not any(token in name.lower() for token in forbidden), name
