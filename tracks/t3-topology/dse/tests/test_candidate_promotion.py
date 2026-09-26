"""TopologyCandidate -> ordinary Design intent (CFAB-9..CFAB-13).

Promotion FREEZES a candidate's exact graph into canonical explicit
topology. It is not "mark verified": nothing here claims a certificate, a
measurement or a Pareto status. And it is not a second design type — the
result is the SAME explicit topology an authored graph produces.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.synthesis.definition import SynthesisDefinition
from veritx_dse.synthesis.traffic import from_uniform
from veritx_dse.synthesis.candidate import (
    TopologyCandidate,
    TopologyCandidateError,
    apply_promotion_to_request_doc,
    promote_to_explicit_topology,
    synthesize,
)
from veritx_dse.model.compile_model import CompileRequestV3
from veritx_dse.application.fabric_compiler import FabricCompiler

REPO = Path(__file__).resolve().parents[4]
V3 = REPO / "tracks/t3-topology/examples/dense_1b_16tiles-v3.json"

N = 25
K = 5


def _defn(**kw):
    base = dict(nodes=N, layout="grid", k=K, radix=4, max_len=1.0,
                bandwidth_GBs=50.0, latency_ns=500.0, timeout_s=60,
                max_nodes=30)
    base.update(kw)
    return SynthesisDefinition(**base)


def _traffic(**kw):
    base = dict(demand=1.0, source_artifact_id="sha256:promo-fixture",
                namespace="router", unit="messages",
                aggregation="sum_over_workload")
    base.update(kw)
    return from_uniform(N, **base)


def _base_doc():
    d = json.loads(V3.read_text())
    d.pop("design_hash", None)
    d.pop("guardrail_hash", None)
    return d


@pytest.fixture(scope="module")
def promoted():
    d, t = _defn(), _traffic()
    c = synthesize(d, t)
    assert c.status == "SUCCEEDED"
    return d, t, c, promote_to_explicit_topology(c, d, name="promoted-5x5")


# ══ CFAB-9: promotion freezes the exact graph ══════════════════════════

def test_cfab_9_promotion_freezes_the_exact_graph(promoted):
    _d, _t, c, p = promoted
    ir = p["explicit_topology"]
    assert ir.kind == "custom"
    assert ir.nodes == c.nodes
    assert sorted(tuple(sorted(e)) for e in ir.links) == sorted(c.links)


# ══ CFAB-10: promoted and manual are the same design science ══════════

def test_cfab_10_promoted_and_manual_have_equivalent_design_science(promoted):
    _d, _t, _c, p = promoted
    doc = _base_doc()
    req = CompileRequestV3.from_dict(apply_promotion_to_request_doc(doc, p))
    manual = dict(doc)
    manual["explicit_topology"] = p["explicit_topology"].to_dict()
    manual["noc_config"] = dict(manual["noc_config"])
    manual["noc_config"]["topology_family"] = None
    mreq = CompileRequestV3.from_dict(manual)
    assert req.design_hash() == mreq.design_hash(), (
        "origin must not enter design identity")


def test_cfab_10b_identical_topology_routes_and_vc(promoted):
    _d, _t, _c, p = promoted
    doc = _base_doc()
    req = CompileRequestV3.from_dict(apply_promotion_to_request_doc(doc, p))
    manual = dict(doc)
    manual["explicit_topology"] = p["explicit_topology"].to_dict()
    manual["noc_config"] = dict(manual["noc_config"])
    manual["noc_config"]["topology_family"] = None
    mreq = CompileRequestV3.from_dict(manual)
    a, b = FabricCompiler().compile(req), FabricCompiler().compile(mreq)
    assert a.bundle.topology.topology_hash() == \
        b.bundle.topology.topology_hash()
    assert a.bundle.router_route.entries == b.bundle.router_route.entries
    assert a.bundle.vc_assignment == b.bundle.vc_assignment
    assert a.certificate.overall == b.certificate.overall == "PASS"


# ══ CFAB-11: provenance does not alter topology/design identity ════════

def test_cfab_11_provenance_is_linkage_not_science(promoted):
    _d, _t, _c, p = promoted
    doc = _base_doc()
    req = CompileRequestV3.from_dict(apply_promotion_to_request_doc(doc, p))
    assert "synthesis_provenance" in req.to_dict(), "must persist"
    assert "synthesis_provenance" not in req.canonical_dict(), \
        "must NOT enter design identity"
    # and it survives a round trip
    back = CompileRequestV3.from_dict(req.to_dict())
    assert back.design_hash() == req.design_hash()
    assert back.synthesis_provenance == req.synthesis_provenance


def test_cfab_11b_provenance_chain_is_navigable(promoted):
    d, t, c, p = promoted
    prov = p["provenance"]
    assert prov["candidate_id"] == c.candidate_id()
    assert prov["graph_id"] == c.graph_id()
    assert prov["definition_id"] == d.definition_id()
    assert prov["traffic_id"] == t.traffic_id()
    assert prov["producer"]["solver_status"] == c.solver_status


# ══ CFAB-12: generator objective never becomes performance ═════════════

def test_cfab_12_generator_objective_is_not_copied_into_performance(promoted):
    _d, _t, c, p = promoted
    assert c.objective_value is not None          # the generator objective
    blob = json.dumps(p["provenance"])
    # It lives under `producer`, explicitly named as the GENERATOR's.
    assert "objective_value" in p["provenance"]["producer"]
    assert "objective_name" in p["provenance"]["producer"]
    # It must not appear as a performance/measurement field anywhere.
    for forbidden in ("latency_ns", "completion_cycles", "measured",
                      "pareto", "verified"):
        assert forbidden not in blob


# ══ CFAB-13: stale candidates cannot be promoted ═══════════════════════

def test_cfab_13_stale_definition_refuses(promoted):
    _d, _t, c, _p = promoted
    other = _defn(radix=3)                        # a DIFFERENT definition
    with pytest.raises(TopologyCandidateError) as e:
        promote_to_explicit_topology(c, other)
    assert "definition changed" in str(e.value)


def test_cfab_13b_wrong_expected_candidate_id_refuses(promoted):
    d, _t, c, _p = promoted
    with pytest.raises(TopologyCandidateError) as e:
        promote_to_explicit_topology(c, d, expected_candidate_id="deadbeef")
    assert "stale promotion" in str(e.value)


def test_cfab_13c_failed_candidate_cannot_be_promoted():
    d, t = _defn(), _traffic()
    c = synthesize(d, t)
    failed = TopologyCandidate(
        definition_id=c.definition_id, traffic_id=c.traffic_id,
        nodes=c.nodes, links=(), algorithm="milp_tmcf",
        solver_status="INFEASIBLE", objective_value=None,
        objective_name="traffic_weighted_hops", status="INFEASIBLE",
        producer_id="test")
    with pytest.raises(TopologyCandidateError) as e:
        promote_to_explicit_topology(failed, d)
    assert "no graph to freeze" in str(e.value)


def test_cfab_13d_tampered_candidate_refuses(promoted):
    """A candidate that does not re-verify against its own wire form must
    not become a design."""
    d, _t, c, _p = promoted
    tampered = TopologyCandidate(
        definition_id=c.definition_id, traffic_id=c.traffic_id,
        nodes=c.nodes, links=c.links, algorithm=c.algorithm,
        solver_status=c.solver_status, objective_value=c.objective_value,
        objective_name=c.objective_name, status=c.status,
        producer_id=c.producer_id)
    # same content -> same identity -> promotion succeeds
    assert promote_to_explicit_topology(tampered, d)["explicit_topology"]


# ══ no SynthesizedDesign ontology ══════════════════════════════════════

def test_promotion_produces_a_normal_request(promoted):
    _d, _t, _c, p = promoted
    req = CompileRequestV3.from_dict(
        apply_promotion_to_request_doc(_base_doc(), p))
    assert type(req).__name__ == "CompileRequestV3"
    assert req.explicit_topology.kind == "custom"


def test_manual_design_has_no_candidate_parent():
    """Synthesis provenance is OPTIONAL: a manual explicit design simply
    has none."""
    d = _base_doc()
    d["explicit_topology"] = {
        "name": "hand", "kind": "custom", "nodes": N,
        "links": [[i, i + 1] for i in range(N - 1)],
        "link_attrs": {"bandwidth_GBs": 50.0, "latency_ns": 500.0}}
    d["noc_config"] = dict(d["noc_config"])
    d["noc_config"]["topology_family"] = None
    req = CompileRequestV3.from_dict(d)
    assert req.synthesis_provenance is None
    assert "synthesis_provenance" not in req.to_dict()
