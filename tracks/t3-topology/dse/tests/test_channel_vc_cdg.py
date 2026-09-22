"""Channel×VC dependency-graph tests — independent deadlock verification.

The verifier consumes candidate artifacts and judges them; it never trusts
the VC-selection policy that produced them. The regression that matters
here: for a transition between routing classes, the HELD channel comes from
the class of ``vc_in`` and the REQUESTED channel from the class of
``vc_out``.
"""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

import pytest

from veritx_dse.core.route_artifact import ANYNET_MIN_HOPS, DOR_XY, RouteArtifact
from veritx_dse.model.attachment import derive_attachment
from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, ModelFamily, NocConfig, TopologyFamily,
    Workload,
)
from veritx_dse.model.placement import build_inventory
from veritx_dse.model.resolved_route import (
    ResolvedRouteArtifact, derive_resolved_route,
)
from veritx_dse.model.topology_artifact import (
    DirectedChannel, MaterializedFamily, Router, TopologyArtifact,
    materialize_family, materialize_topology,
)
from veritx_dse.model.vc_assignment import make_vc_assignment_artifact
from veritx_dse.verification.channel_vc_cdg import (
    CDGError, CHANNEL_VC_DEPENDENCY_ACYCLIC, DEADLOCK_PROOF_METHODS,
    ChannelVCCDG, DeadlockCertificate, build_channel_vc_cdg,
    certify_channel_vc_deadlock,
)


def _real_fabric(n: int, classes=(ANYNET_MIN_HOPS,),
                 family=TopologyFamily.MESH):
    cr = CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1, dp=1),
        requirements=[], agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=n)],
        dependencies=[], noc_config=NocConfig(topology_family=family))
    inv = build_inventory(cr)
    topo = materialize_topology(inv, cr)
    att = derive_attachment(design=cr, inventory=inv, topology=topo)
    rr = RouteArtifact.from_topology(topo, name="t", routing_classes=classes)
    return topo, rr, derive_resolved_route(topo, att, rr)


def _fabricated(topo, classes=(ANYNET_MIN_HOPS,)):
    """Custom-topology fixture: route/parent hashes are real, attachment is
    carried transitively only (this verifier does not certify attachment)."""
    rr = RouteArtifact.from_topology(topo, name="t", routing_classes=classes)
    rra = ResolvedRouteArtifact(
        topology_hash=topo.topology_hash(), attachment_hash="a" * 64,
        router_route_hash=rr.artifact_hash,
        endpoint_to_router=tuple((i, i) for i in range(topo.router_count)),
        routing_classes=classes, endpoint_route_table_hash="b" * 64)
    return rr, rra


def _vc(rra, vc_count: int = 1, **kw):
    kw.setdefault("traffic_class_to_vcs",
                  {chr(65 + i): [i] for i in range(vc_count)})
    return make_vc_assignment_artifact(
        resolved_route=rra, vc_count=vc_count, derivation="cdg-test", **kw)


def _two_router() -> TopologyArtifact:
    return TopologyArtifact(
        family=MaterializedFamily.MESH,
        routers=(Router(0, (0,), 2), Router(1, (1,), 2)),
        channels=(DirectedChannel(0, 0, 0, 1, 0, 64, 1),
                  DirectedChannel(1, 1, 0, 0, 0, 64, 1)))


def _directed_ring() -> TopologyArtifact:
    return TopologyArtifact(
        family=MaterializedFamily.RING,
        routers=(Router(0, (0,), 1), Router(1, (1,), 1), Router(2, (2,), 1)),
        channels=(DirectedChannel(0, 0, 0, 1, 0, 64, 1),
                  DirectedChannel(1, 1, 0, 2, 0, 64, 1),
                  DirectedChannel(2, 2, 0, 0, 0, 64, 1)))


def _parallel_hop_ring() -> TopologyArtifact:
    return TopologyArtifact(
        family=MaterializedFamily.RING,
        routers=(Router(0, (0,), 1), Router(1, (1,), 1), Router(2, (2,), 1)),
        channels=(DirectedChannel(0, 0, 0, 1, 0, 64, 1),
                  DirectedChannel(1, 1, 0, 2, 0, 64, 1),
                  DirectedChannel(2, 1, 1, 2, 1, 64, 1),
                  DirectedChannel(3, 2, 0, 0, 0, 64, 1)))


def _mixed_class_mesh(transitions=((0, 1),)):
    topo = materialize_family(MaterializedFamily.MESH, endpoint_count=4)
    rr, rra = _fabricated(topo, (ANYNET_MIN_HOPS, DOR_XY))
    vc = _vc(rra, vc_count=2, vc_to_routing_class={
        0: ANYNET_MIN_HOPS, 1: DOR_XY}, allowed_transitions=list(transitions))
    return topo, rr, rra, vc


# ── positive verdicts ──────────────────────────────────────────────────────

@pytest.mark.parametrize("k", (2, 3))
def test_dor_mesh_real_chain_passes(k):
    topo, rr, rra = _real_fabric(k * k, (DOR_XY,))
    vc = _vc(rra, vc_count=1)
    cert = certify_channel_vc_deadlock(
        topology=topo, resolved_route=rra, router_route=rr, vc_assignment=vc)
    assert cert.verdict == "PASS"
    assert cert.proof_method == CHANNEL_VC_DEPENDENCY_ACYCLIC
    assert cert.evidence["acyclic"] is True
    assert cert.evidence["cdg_route_classes"] == (DOR_XY,)
    assert cert.evidence["route_realization"] == "v2_channel_id"


def test_two_router_ejection_has_no_edges():
    topo = _two_router()
    rr, rra = _fabricated(topo)
    vc = _vc(rra, vc_count=2)
    cdg = build_channel_vc_cdg(topo, rr, vc)
    assert cdg.edge_count == 0
    cert = certify_channel_vc_deadlock(
        topology=topo, resolved_route=rra, router_route=rr, vc_assignment=vc)
    assert cert.verdict == "PASS"


def test_nodes_are_channels_times_vcs():
    topo = _two_router()
    rr, rra = _fabricated(topo)
    vc = _vc(rra, vc_count=3)
    cdg = build_channel_vc_cdg(topo, rr, vc)
    assert cdg.node_count == topo.channel_count * vc.vc_count
    assert cdg.nodes == tuple((c.channel_id, v)
                              for c in topo.channels for v in vc.vc_ids)


# ── negative verdicts and witnesses ────────────────────────────────────────

def test_directed_ring_fails_with_deterministic_witness():
    topo = _directed_ring()
    rr, rra = _fabricated(topo)
    vc = _vc(rra, vc_count=1)
    cert = certify_channel_vc_deadlock(
        topology=topo, resolved_route=rra, router_route=rr, vc_assignment=vc)
    assert cert.verdict == "FAIL"
    assert cert.evidence["acyclic"] is False
    assert cert.evidence["cycle"] == ((0, 0), (1, 0), (2, 0), (0, 0))
    assert cert.evidence["cycle"][0] == cert.evidence["cycle"][-1]


def test_cycle_witness_is_deterministic():
    topo = _directed_ring()
    rr, rra = _fabricated(topo)
    vc = _vc(rra, vc_count=1)
    first = certify_channel_vc_deadlock(
        topology=topo, resolved_route=rra, router_route=rr, vc_assignment=vc)
    second = certify_channel_vc_deadlock(
        topology=topo, resolved_route=rra, router_route=rr, vc_assignment=vc)
    assert first.evidence == second.evidence
    assert first.to_dict() == second.to_dict()


def test_escape_vcs_never_bypass_analysis():
    topo = _directed_ring()
    rr, rra = _fabricated(topo)
    vc = _vc(rra, vc_count=1, escape_vcs=(0,))
    cert = certify_channel_vc_deadlock(
        topology=topo, resolved_route=rra, router_route=rr, vc_assignment=vc)
    assert cert.verdict == "FAIL"
    assert cert.evidence["escape_vcs"] == (0,)


# ── exact edge construction ────────────────────────────────────────────────

def test_dependency_targets_the_next_channel_not_a_far_exit():
    topo = _directed_ring()
    rr, _rra = _fabricated(topo)
    vc = _vc(_rra, vc_count=1)
    cdg = build_channel_vc_cdg(topo, rr, vc)
    assert cdg.edges == (((0, 0), (1, 0)), ((1, 0), (2, 0)), ((2, 0), (0, 0)))
    assert ((0, 0), (2, 0)) not in cdg.edges


def test_parallel_hop_uses_the_materialized_exact_channel():
    topo = _parallel_hop_ring()
    rr, rra = _fabricated(topo)
    vc = _vc(rra, vc_count=1)
    assert rr.entries[(ANYNET_MIN_HOPS, 1, 2)] == 1
    cdg = build_channel_vc_cdg(topo, rr, vc)
    assert ((0, 0), (1, 0)) in cdg.edges
    assert ((0, 0), (2, 0)) not in cdg.edges
    assert len(cdg.edges) == len(set(cdg.edges))


def test_duplicate_edges_canonicalize_and_order_is_deterministic():
    topo = _directed_ring()
    rr, _rra = _fabricated(topo)
    vc = _vc(_rra, vc_count=2,
             allowed_transitions=[(0, 0), (1, 1), (0, 1), (0, 1)])
    cdg = build_channel_vc_cdg(topo, rr, vc)
    assert cdg.edges == tuple(sorted(set(cdg.edges)))
    assert len(cdg.edges) == len(set(cdg.edges))


# ── cross-routing-class transition regression (STOP gate) ──────────────────

def test_cross_class_transition_uses_class_in_for_held_channel():
    """Held channel from class(vc_in); requested channel from class(vc_out).

    For 2 -> 1 on the 2x2 mesh the classes pick different first hops:
      ANYNET_MIN_HOPS: 2 --ch4--> 0 --ch0--> 1
      DOR_XY:          2 --ch5--> 3 --ch6--> 1
    so VC0(ANYNET) -> VC1(DOR) must depend on ((4,0),(0,1)) and must NOT
    invent the DOR-held edge ((5,0),(6,1))."""
    topo, rr, rra, vc = _mixed_class_mesh(transitions=((0, 1),))
    assert rr.entries[(ANYNET_MIN_HOPS, 2, 1)] == 4
    assert rr.entries[(DOR_XY, 2, 1)] == 5
    cdg = build_channel_vc_cdg(topo, rr, vc)
    assert cdg.edges == (((0, 0), (3, 1)), ((2, 0), (1, 1)),
                         ((4, 0), (0, 1)), ((6, 0), (2, 1)))
    assert ((4, 0), (0, 1)) in cdg.edges
    assert ((5, 0), (6, 1)) not in cdg.edges
    cert = certify_channel_vc_deadlock(
        topology=topo, resolved_route=rra, router_route=rr, vc_assignment=vc)
    assert cert.evidence["cdg_route_classes"] == (ANYNET_MIN_HOPS, DOR_XY)


def test_vc_preserving_transitions_keep_single_class_behaviour():
    topo, rr, _rra, vc = _mixed_class_mesh(transitions=((0, 0), (1, 1)))
    cdg = build_channel_vc_cdg(topo, rr, vc)
    assert all(src[1] == dst[1] for src, dst in cdg.edges)
    edges_for = {vc_id: tuple(e for e in cdg.edges if e[0][1] == vc_id)
                 for vc_id in (0, 1)}
    for vc_id, cls in ((0, ANYNET_MIN_HOPS), (1, DOR_XY)):
        rr_single, rra_single = _fabricated(topo, (cls,))
        vc_single = _vc(rra_single, vc_count=1)
        single = build_channel_vc_cdg(topo, rr_single, vc_single)
        mapped = tuple(((src[0], vc_id), (dst[0], vc_id))
                       for src, dst in single.edges)
        assert edges_for[vc_id] == mapped


# ── UNSUPPORTED semantics ──────────────────────────────────────────────────

def test_unknown_routing_class_is_unsupported():
    topo = _two_router()
    rr = RouteArtifact.from_topology(topo, name="t")
    rra = ResolvedRouteArtifact(
        topology_hash=topo.topology_hash(), attachment_hash="a" * 64,
        router_route_hash=rr.artifact_hash,
        endpoint_to_router=((0, 0), (1, 1)),
        routing_classes=("ESCAPE",), endpoint_route_table_hash="b" * 64)
    vc = _vc(rra, vc_count=1, vc_to_routing_class={0: "ESCAPE"})
    with pytest.raises(CDGError, match="ESCAPE"):
        build_channel_vc_cdg(topo, rr, vc)
    cert = certify_channel_vc_deadlock(
        topology=topo, resolved_route=rra, router_route=rr, vc_assignment=vc)
    assert cert.verdict == "UNSUPPORTED"
    assert "ESCAPE" in cert.evidence["unsupported_reason"]


# ── fail-closed parent handling ────────────────────────────────────────────

def test_non_artifact_parents_are_refused():
    topo = _two_router()
    rr, rra = _fabricated(topo)
    vc = _vc(rra, vc_count=1)
    for bad_kwargs in (
            dict(topology=object()),
            dict(resolved_route=object()),
            dict(router_route=object()),
            dict(vc_assignment=object())):
        kwargs = dict(topology=topo, resolved_route=rra, router_route=rr,
                      vc_assignment=vc)
        kwargs.update(bad_kwargs)
        with pytest.raises(CDGError):
            certify_channel_vc_deadlock(**kwargs)
    with pytest.raises(CDGError, match="TopologyArtifact"):
        build_channel_vc_cdg(object(), rr, vc)


def test_tampered_bindings_are_refused():
    topo = _two_router()
    rr, rra = _fabricated(topo)
    vc = _vc(rra, vc_count=1)
    tampered = _vc(rra, vc_count=1)
    object.__setattr__(tampered, "resolved_route_hash", "0" * 64)
    with pytest.raises(CDGError, match="VC assignment"):
        certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr,
            vc_assignment=tampered)
    tampered_route = _fabricated(topo)[1]
    object.__setattr__(tampered_route, "topology_hash", "0" * 64)
    with pytest.raises(CDGError, match="topology"):
        certify_channel_vc_deadlock(
            topology=topo, resolved_route=tampered_route, router_route=rr,
            vc_assignment=vc)
    wrong_route = RouteArtifact.from_topology(topo, name="t")
    other_rra = _fabricated(topo)[1]
    object.__setattr__(other_rra, "router_route_hash", "0" * 64)
    with pytest.raises(CDGError, match="router route"):
        certify_channel_vc_deadlock(
            topology=topo, resolved_route=other_rra, router_route=wrong_route,
            vc_assignment=vc)


def test_schema_v1_router_route_is_refused():
    topo = _two_router()
    rr, rra = _fabricated(topo)
    vc = _vc(rra, vc_count=1)
    object.__setattr__(rr, "schema_version", 1)
    with pytest.raises(CDGError, match="schema v2"):
        certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr,
            vc_assignment=vc)


def test_router_route_failing_parent_validation_is_cdg_error():
    topo = _two_router()
    rr, rra = _fabricated(topo)
    vc = _vc(rra, vc_count=1)
    entries = dict(rr.entries)
    entries[(ANYNET_MIN_HOPS, 0, 1)] = 999
    object.__setattr__(rr, "entries", MappingProxyType(entries))
    with pytest.raises(CDGError, match="router route fails parent validation"):
        certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr,
            vc_assignment=vc)


def test_vc_assignment_failing_parent_validation_is_cdg_error():
    topo = _two_router()
    rr, rra = _fabricated(topo)
    vc = _vc(rra, vc_count=1)
    object.__setattr__(vc, "vc_to_routing_class", ((0, "ESCAPE"),))
    with pytest.raises(CDGError, match="VC assignment fails parent validation"):
        certify_channel_vc_deadlock(
            topology=topo, resolved_route=rra, router_route=rr,
            vc_assignment=vc)


# ── certificate contract ───────────────────────────────────────────────────

def _certificate(**over) -> DeadlockCertificate:
    kw = dict(proof_method=CHANNEL_VC_DEPENDENCY_ACYCLIC, verdict="PASS",
              topology_hash="a" * 64, attachment_hash="b" * 64,
              router_route_hash="c" * 64, resolved_route_hash="d" * 64,
              vc_assignment_hash="e" * 64, router_behavior_hash="",
              evidence={"acyclic": True, "cycle": []})
    kw.update(over)
    return DeadlockCertificate(**kw)


def test_proof_vocabulary_is_closed():
    assert CHANNEL_VC_DEPENDENCY_ACYCLIC in DEADLOCK_PROOF_METHODS
    assert len(DEADLOCK_PROOF_METHODS) == 4
    with pytest.raises(CDGError, match="proof method"):
        _certificate(proof_method="TRUST_ME")
    _certificate(verdict="NOT_RUN", proof_method="FORMAL_BOUNDED_CHECK")


def test_certificate_rejects_unknown_verdict():
    with pytest.raises(CDGError, match="verdict"):
        _certificate(verdict="MAYBE")


def test_certificate_rejects_bad_hashes_and_schema():
    with pytest.raises(CDGError, match="topology_hash"):
        _certificate(topology_hash="")
    with pytest.raises(CDGError, match="resolved_route_hash"):
        _certificate(resolved_route_hash=7)
    with pytest.raises(CDGError, match="router_behavior_hash"):
        _certificate(router_behavior_hash=None)
    with pytest.raises(CDGError, match="schema_version"):
        _certificate(schema_version=2)


def test_certificate_binds_all_hashes():
    topo = _two_router()
    rr, rra = _fabricated(topo)
    vc = _vc(rra, vc_count=1)
    cert = certify_channel_vc_deadlock(
        topology=topo, resolved_route=rra, router_route=rr, vc_assignment=vc,
        router_behavior_hash="c" * 64)
    d = cert.to_dict()
    for key in ("type", "schema_version", "proof_method", "verdict",
                "topology_hash", "attachment_hash", "router_route_hash",
                "resolved_route_hash", "vc_assignment_hash",
                "router_behavior_hash", "evidence", "tool", "scope"):
        assert key in d
    assert d["topology_hash"] == topo.topology_hash()
    assert d["attachment_hash"] == rra.attachment_hash
    assert d["router_route_hash"] == rr.artifact_hash
    assert d["resolved_route_hash"] == rra.resolved_route_hash()
    assert d["vc_assignment_hash"] == vc.vc_assignment_hash()
    assert d["router_behavior_hash"] == "c" * 64
    assert d["type"] == "srota/DeadlockCertificate"


def test_certificate_scope_does_not_claim_attachment_proof():
    topo = _two_router()
    rr, rra = _fabricated(topo)
    vc = _vc(rra, vc_count=1)
    cert = certify_channel_vc_deadlock(
        topology=topo, resolved_route=rra, router_route=rr, vc_assignment=vc)
    assert "attachment completeness is not recertified" in cert.scope


# ── certificate immutability ───────────────────────────────────────────────

def test_caller_evidence_cannot_mutate_certificate():
    evidence = {"acyclic": True, "cycle": [], "cdg_route_classes": ["A"]}
    cert = _certificate(evidence=evidence)
    evidence["acyclic"] = False
    evidence["cycle"].append([0, 0])
    evidence["cdg_route_classes"].append("B")
    assert cert.evidence["acyclic"] is True
    assert cert.evidence["cycle"] == ()
    assert cert.evidence["cdg_route_classes"] == ("A",)
    assert isinstance(cert.evidence, Mapping)
    assert not isinstance(cert.evidence, dict)


def test_certificate_evidence_is_read_only():
    cert = _certificate()
    with pytest.raises(TypeError):
        cert.evidence["acyclic"] = False


def test_to_dict_returns_a_defensive_copy():
    cert = _certificate(evidence={"acyclic": False, "cycle": [[0, 0]]})
    first = cert.to_dict()
    assert first["evidence"] == {"acyclic": False, "cycle": [[0, 0]]}
    first["evidence"]["acyclic"] = True
    first["evidence"]["cycle"].append([9, 9])
    second = cert.to_dict()
    assert second["evidence"] == {"acyclic": False, "cycle": [[0, 0]]}
    assert cert.evidence["acyclic"] is False
    assert cert.evidence["cycle"] == ((0, 0),)
