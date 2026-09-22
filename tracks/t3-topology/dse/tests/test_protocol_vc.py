"""Protocol/VC separation tests — independent E4 BLOCKING verifier.

The verifier judges a candidate traffic-class → VC mapping without calling
the routing/CDG verifier and without generating VC assignments. A shared VC
keeps a BLOCKING edge coupled; disjoint VC sets separate it under the
explicit VC-isolation assumption.
"""
from __future__ import annotations

from collections.abc import Mapping

import pytest

from veritx_dse.core.route_artifact import RouteArtifact
from veritx_dse.model.attachment import derive_attachment
from veritx_dse.model.compile_model import (
    Agent, AgentKind, CollectiveKind, CollectiveOp, CompileRequest, DepKind,
    Dependency, DependencyGraph, ModelFamily, NocConfig, TopologyFamily,
    Workload,
)
from veritx_dse.model.placement import build_inventory
from veritx_dse.model.resolved_route import derive_resolved_route
from veritx_dse.model.topology_artifact import materialize_topology
from veritx_dse.model.vc_assignment import make_vc_assignment_artifact
from veritx_dse.verification.protocol_vc import (
    COLLECTIVE_SEMANTICS_ABSENT, COLLECTIVE_SEMANTICS_NOT_MODELED,
    PROTOCOL_VC_DEPENDENCY_ACYCLIC, PROTOCOL_VC_PROOF_METHODS,
    ProtocolVCCertificate, ProtocolVCError, build_protocol_vc_graph,
    certify_protocol_vc_separation,
)


def _resolved_route():
    cr = CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1, dp=1),
        requirements=[], agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=4)],
        dependencies=[], noc_config=NocConfig(topology_family=TopologyFamily.MESH))
    inv = build_inventory(cr)
    topo = materialize_topology(inv, cr)
    att = derive_attachment(design=cr, inventory=inv, topology=topo)
    rr = RouteArtifact.from_topology(topo, name="t")
    return derive_resolved_route(topo, att, rr)


@pytest.fixture(scope="module")
def rra():
    return _resolved_route()


def _dep(source, target, kind=DepKind.BLOCKING):
    return Dependency(source, target, kind)


def _design(deps=(), collectives=()):
    return CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1, dp=1,
                          collectives=tuple(collectives)),
        requirements=[], agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=4)],
        dependencies=DependencyGraph(list(deps)),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH))


def _vc(rra, mapping, derivation="protocol-test"):
    vc_count = max(1, 1 + max(max(vcs) for vcs in mapping.values()))
    return make_vc_assignment_artifact(
        resolved_route=rra, vc_count=vc_count,
        traffic_class_to_vcs=mapping, derivation=derivation)


def _cert(design, vc):
    return certify_protocol_vc_separation(design=design, vc_assignment=vc)


AB_CYCLE = (_dep("A", "B"), _dep("B", "A"))
THREE_CYCLE = (_dep("A", "B"), _dep("B", "C"), _dep("C", "A"))


# ── verdicts ───────────────────────────────────────────────────────────────

def test_no_blocking_cycle_passes(rra):
    design = _design((_dep("A", "B"),))
    cert = _cert(design, _vc(rra, {"A": [0], "B": [0]}))
    assert cert.verdict == "PASS"
    assert cert.proof_method == PROTOCOL_VC_DEPENDENCY_ACYCLIC
    assert cert.evidence["acyclic"] is True
    assert cert.evidence["coupled_edge_count"] == 1
    assert cert.evidence["separated_edge_count"] == 0


def test_simple_ab_cycle_on_one_vc_fails(rra):
    cert = _cert(_design(AB_CYCLE), _vc(rra, {"A": [0], "B": [0]}))
    assert cert.verdict == "FAIL"
    assert cert.evidence["acyclic"] is False
    assert cert.evidence["cycle"] == ("A", "B", "A")


def test_simple_ab_cycle_split_across_disjoint_vcs_passes(rra):
    cert = _cert(_design(AB_CYCLE), _vc(rra, {"A": [0], "B": [1]}))
    assert cert.verdict == "PASS"
    assert cert.evidence["coupled_edges"] == ()
    assert cert.evidence["separated_edges"] == (("A", "B"), ("B", "A"))


def test_three_node_cycle_fails(rra):
    cert = _cert(_design(THREE_CYCLE),
                 _vc(rra, {"A": [0], "B": [0], "C": [0]}))
    assert cert.verdict == "FAIL"
    cycle = cert.evidence["cycle"]
    assert len(cycle) == 4
    assert cycle[0] == cycle[-1]


def test_one_separated_edge_breaks_three_node_cycle(rra):
    cert = _cert(_design(THREE_CYCLE),
                 _vc(rra, {"A": [0], "B": [0], "C": [1]}))
    assert cert.verdict == "PASS"
    assert cert.evidence["coupled_edges"] == (("A", "B"),)
    assert cert.evidence["separated_edges"] == (("B", "C"), ("C", "A"))


def test_multiple_independent_cycles_fail(rra):
    design = _design((_dep("A", "B"), _dep("B", "A"),
                      _dep("C", "D"), _dep("D", "C")))
    cert = _cert(design, _vc(rra, {"A": [0], "B": [0], "C": [0], "D": [0]}))
    assert cert.verdict == "FAIL"
    assert cert.evidence["cycle"] == ("A", "B", "A")


def test_overlapping_cycles_fail(rra):
    # A->B->A and A->B->C->A share the edge A->B.
    design = _design((_dep("A", "B"), _dep("B", "A"),
                      _dep("B", "C"), _dep("C", "A")))
    cert = _cert(design, _vc(rra, {"A": [0], "B": [0], "C": [0]}))
    assert cert.verdict == "FAIL"
    assert cert.evidence["coupled_edge_count"] == 4


def test_separating_the_shared_edge_breaks_overlapping_cycles(rra):
    design = _design((_dep("A", "B"), _dep("B", "A"),
                      _dep("B", "C"), _dep("C", "A")))
    cert = _cert(design, _vc(rra, {"A": [0], "B": [1], "C": [0]}))
    assert cert.verdict == "PASS"
    assert cert.evidence["coupled_edges"] == (("C", "A"),)
    assert cert.evidence["separated_edge_count"] == 3


# ── conservative multi-VC intersection ─────────────────────────────────────

def test_multi_vc_intersection_stays_coupled(rra):
    design = _design((_dep("A", "B"),))
    cert = _cert(design, _vc(rra, {"A": [0, 1], "B": [1, 2]}))
    assert cert.evidence["coupled_edges"] == (("A", "B"),)
    assert cert.evidence["separated_edges"] == ()


def test_multi_vc_disjoint_sets_are_separated(rra):
    design = _design((_dep("A", "B"),))
    cert = _cert(design, _vc(rra, {"A": [0, 1], "B": [2, 3]}))
    assert cert.evidence["coupled_edges"] == ()
    assert cert.evidence["separated_edges"] == (("A", "B"),)
    assert cert.verdict == "PASS"


# ── only BLOCKING creates dependencies ─────────────────────────────────────

def test_ordering_does_not_create_blocking_dependency(rra):
    design = _design((_dep("A", "B", DepKind.ORDERING),
                      _dep("B", "A", DepKind.ORDERING)))
    cert = _cert(design, _vc(rra, {"A": [0], "B": [0]}))
    assert cert.verdict == "PASS"
    assert cert.evidence["coupled_edge_count"] == 0
    assert cert.evidence["ordering_edge_count"] == 2


def test_independent_does_not_create_blocking_dependency(rra):
    design = _design((_dep("A", "B", DepKind.INDEPENDENT),
                      _dep("B", "A", DepKind.INDEPENDENT)))
    cert = _cert(design, _vc(rra, {"A": [0], "B": [0]}))
    assert cert.verdict == "PASS"
    assert cert.evidence["coupled_edge_count"] == 0
    assert cert.evidence["independent_edge_count"] == 2


def test_no_blocking_edges_at_all_passes(rra):
    cert = _cert(_design(()), _vc(rra, {"A": [0]}))
    assert cert.verdict == "PASS"
    assert cert.evidence["blocking_edge_count"] == 0
    assert cert.evidence["acyclic"] is True


# ── fail-closed malformed candidates ───────────────────────────────────────

def test_missing_traffic_class_mapping_raises(rra):
    design = _design((_dep("A", "B"),))
    with pytest.raises(ProtocolVCError, match="B"):
        _cert(design, _vc(rra, {"A": [0]}))
    with pytest.raises(ProtocolVCError, match="no VC mapping"):
        build_protocol_vc_graph(design, _vc(rra, {"A": [0]}))


def test_invalid_parent_types_raise(rra):
    design = _design(AB_CYCLE)
    vc = _vc(rra, {"A": [0], "B": [0]})
    with pytest.raises(ProtocolVCError, match="CompileRequest"):
        _cert(object(), vc)
    with pytest.raises(ProtocolVCError, match="VCAssignmentArtifact"):
        _cert(design, object())


# ── determinism and provenance independence ────────────────────────────────

def test_cycle_witness_is_deterministic(rra):
    design = _design(THREE_CYCLE)
    vc = _vc(rra, {"A": [0], "B": [0], "C": [0]})
    first = _cert(design, vc)
    second = _cert(design, vc)
    assert first.evidence == second.evidence
    assert first.to_dict() == second.to_dict()


def test_edge_order_permutation_does_not_change_proof(rra):
    edges = (_dep("A", "B"), _dep("B", "C"), _dep("C", "A"))
    forward = _design(edges)
    backward = _design(tuple(reversed(edges)))
    vc = _vc(rra, {"A": [0], "B": [0], "C": [1]})
    a = _cert(forward, vc)
    b = _cert(backward, vc)
    assert a.verdict == b.verdict == "PASS"
    assert a.evidence == b.evidence


def test_derivation_does_not_change_proof(rra):
    design = _design(AB_CYCLE)
    left = _vc(rra, {"A": [0], "B": [0]}, derivation="cycles=1")
    right = _vc(rra, {"A": [0], "B": [0]}, derivation="compiler pass 9")
    a = _cert(design, left)
    b = _cert(design, right)
    assert left.vc_assignment_hash() == right.vc_assignment_hash()
    assert a.verdict == b.verdict == "FAIL"
    assert a.evidence == b.evidence


def test_semantic_mapping_change_can_change_verdict(rra):
    design = _design(AB_CYCLE)
    failing = _cert(design, _vc(rra, {"A": [0], "B": [0]}))
    passing = _cert(design, _vc(rra, {"A": [0], "B": [1]}))
    assert failing.verdict == "FAIL"
    assert passing.verdict == "PASS"
    assert failing.vc_assignment_hash != passing.vc_assignment_hash


# ── collectives are explicitly not modeled ─────────────────────────────────

def test_multi_rank_collectives_are_recorded_not_modeled(rra):
    design = _design(
        AB_CYCLE,
        collectives=(CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=4),))
    cert = _cert(design, _vc(rra, {"A": [0], "B": [0]}))
    assert cert.evidence["collective_vc_semantics"] \
        == COLLECTIVE_SEMANTICS_NOT_MODELED
    assert cert.evidence["multi_rank_collective_count"] == 1
    assert cert.verdict == "FAIL"  # collectives never launder a cycle


def test_absent_collectives_are_recorded_as_absent(rra):
    cert = _cert(_design((_dep("A", "B"),)),
                 _vc(rra, {"A": [0], "B": [0]}))
    assert cert.evidence["collective_vc_semantics"] \
        == COLLECTIVE_SEMANTICS_ABSENT
    assert cert.evidence["multi_rank_collective_count"] == 0


def test_single_rank_collectives_do_not_claim_isolation(rra):
    design = _design(
        (_dep("A", "B"),),
        collectives=(CollectiveOp(kind=CollectiveKind.ALLGATHER, group_size=1),))
    cert = _cert(design, _vc(rra, {"A": [0], "B": [0]}))
    assert cert.evidence["collective_vc_semantics"] \
        == COLLECTIVE_SEMANTICS_ABSENT


# ── certificate contract and immutability ──────────────────────────────────

def _certificate(**over) -> ProtocolVCCertificate:
    kw = dict(proof_method=PROTOCOL_VC_DEPENDENCY_ACYCLIC, verdict="PASS",
              design_hash="a" * 64, vc_assignment_hash="b" * 64,
              evidence={"acyclic": True, "cycle": []})
    kw.update(over)
    return ProtocolVCCertificate(**kw)


def test_proof_vocabulary_is_closed():
    assert PROTOCOL_VC_DEPENDENCY_ACYCLIC in PROTOCOL_VC_PROOF_METHODS
    with pytest.raises(ProtocolVCError, match="proof method"):
        _certificate(proof_method="TRUST_ME")
    with pytest.raises(ProtocolVCError, match="verdict"):
        _certificate(verdict="UNSUPPORTED")


def test_certificate_rejects_bad_hashes_and_schema():
    with pytest.raises(ProtocolVCError, match="design_hash"):
        _certificate(design_hash="")
    with pytest.raises(ProtocolVCError, match="vc_assignment_hash"):
        _certificate(vc_assignment_hash=7)
    with pytest.raises(ProtocolVCError, match="schema_version"):
        _certificate(schema_version=2)


def test_certificate_binds_recomputed_hashes(rra):
    design = _design(THREE_CYCLE)
    vc = _vc(rra, {"A": [0], "B": [0], "C": [1]})
    cert = _cert(design, vc)
    assert cert.design_hash == design.design_hash()
    assert cert.vc_assignment_hash == vc.vc_assignment_hash()
    d = cert.to_dict()
    assert d["design_hash"] == design.design_hash()
    assert d["vc_assignment_hash"] == vc.vc_assignment_hash()
    assert d["type"] == "srota/ProtocolVCCertificate"


def test_certificate_scope_states_the_assumption(rra):
    cert = _cert(_design(AB_CYCLE), _vc(rra, {"A": [0], "B": [0]}))
    assert "assumes disjoint VCs isolate" in cert.scope
    assert "does not prove channel-routing deadlock" in cert.scope
    assert "collective concurrency" in cert.scope
    assert cert.evidence["proof_assumption"] \
        == "disjoint_vcs_isolate_protocol_buffering_dependency"


def test_evidence_reports_class_sets_and_counts(rra):
    mapping = {"A": [0, 1], "B": [1], "C": [2]}
    design = _design(THREE_CYCLE)
    cert = _cert(design, _vc(rra, mapping))
    frozen = cert.evidence["traffic_class_to_vcs"]
    assert dict(frozen) == {"A": (0, 1), "B": (1,), "C": (2,)}
    assert cert.evidence["blocking_edge_count"] == 3
    assert cert.evidence["coupled_edge_count"] == 1
    assert cert.evidence["separated_edge_count"] == 2
    assert cert.verdict == "PASS"


def test_caller_evidence_cannot_mutate_certificate():
    evidence = {"acyclic": False, "cycle": ["A", "B", "A"]}
    cert = _certificate(verdict="FAIL", evidence=evidence)
    evidence["acyclic"] = True
    evidence["cycle"].append("C")
    assert cert.evidence["acyclic"] is False
    assert cert.evidence["cycle"] == ("A", "B", "A")
    assert isinstance(cert.evidence, Mapping)
    assert not isinstance(cert.evidence, dict)


def test_certificate_evidence_is_read_only():
    cert = _certificate()
    with pytest.raises(TypeError):
        cert.evidence["acyclic"] = False


def test_to_dict_returns_a_defensive_copy():
    cert = _certificate(verdict="FAIL",
                        evidence={"acyclic": False, "cycle": ["A", "B", "A"]})
    first = cert.to_dict()
    assert first["evidence"] == {"acyclic": False, "cycle": ["A", "B", "A"]}
    first["evidence"]["acyclic"] = True
    first["evidence"]["cycle"].append("C")
    second = cert.to_dict()
    assert second["evidence"] == {"acyclic": False, "cycle": ["A", "B", "A"]}
    assert cert.evidence["cycle"] == ("A", "B", "A")
