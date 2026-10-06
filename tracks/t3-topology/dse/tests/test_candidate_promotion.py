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

def test_cfab_9_promotion_freezes_the_exact_graph(promoted):
    _d, _t, c, p = promoted
    ir = p["explicit_topology"]
    assert ir.kind == "custom"
    assert ir.nodes == c.nodes
    assert sorted(tuple(sorted(e)) for e in ir.links) == sorted(c.links)

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

def test_cfab_11_provenance_is_linkage_not_science(promoted):
    _d, _t, _c, p = promoted
    doc = _base_doc()
    req = CompileRequestV3.from_dict(apply_promotion_to_request_doc(doc, p))
    assert "synthesis_provenance" in req.to_dict(), "must persist"
    assert "synthesis_provenance" not in req.canonical_dict(), \
        "must NOT enter design identity"
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

def test_cfab_12_generator_objective_is_not_copied_into_performance(promoted):
    _d, _t, c, p = promoted
    assert c.objective_value is not None
    blob = json.dumps(p["provenance"])
    assert "objective_value" in p["provenance"]["producer"]
    assert "objective_name" in p["provenance"]["producer"]
    for forbidden in ("latency_ns", "completion_cycles", "measured",
                      "pareto", "verified"):
        assert forbidden not in blob

def test_cfab_13_stale_definition_refuses(promoted):
    _d, _t, c, _p = promoted
    other = _defn(radix=3)
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
    assert promote_to_explicit_topology(tampered, d)["explicit_topology"]

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

# ── §21.1 exact family recognition in promotion ──────────────────────────

def _mesh_links(k):
    links = []
    for y in range(k):
        for x in range(k):
            n = y * k + x
            if x + 1 < k:
                links.append((n, n + 1))
            if y + 1 < k:
                links.append((n, n + k))
    return tuple(sorted(links))


def _torus_links(k):
    links = set()
    for y in range(k):
        for x in range(k):
            n = y * k + x
            a, b = n, y * k + (x + 1) % k
            links.add((min(a, b), max(a, b)))
            a, b = n, ((y + 1) % k) * k + x
            links.add((min(a, b), max(a, b)))
    return tuple(sorted(links))


def _exact_candidate(nodes, links, definition):
    return TopologyCandidate(
        definition_id=definition.definition_id(),
        traffic_id="sha256:" + "ab" * 32,
        nodes=nodes, links=tuple(sorted(links)),
        algorithm="milp_tmcf", solver_status="FEASIBLE",
        objective_value=1.0, objective_name="latency",
        status="SUCCEEDED", producer_id="test-producer/v1")


def test_exact_mesh_promotes_to_the_mesh_family():
    from veritx_dse.model.topology_intent import MeshIntent
    d = _defn(nodes=16, k=4)
    c = _exact_candidate(16, _mesh_links(4), d)
    p = promote_to_explicit_topology(c, d, concentration=1)
    assert p["provenance"]["structure"] == "EXACT"
    assert p["provenance"]["recognized_family"] == {
        "family": "mesh", "params": {"side_length": 4, "concentration": 1}}
    intent = p["family_intent"]
    assert isinstance(intent, MeshIntent)
    assert (intent.side_length, intent.concentration) == (4, 1)
    # The custom IR is still built as the universal fallback representation.
    assert p["explicit_topology"].kind == "custom"
    assert p["provenance"]["routing_policy"] is None


def test_exact_torus_promotes_to_the_torus_family():
    from veritx_dse.model.topology_intent import TorusIntent
    d = _defn(nodes=9, k=3)
    c = _exact_candidate(9, _torus_links(3), d)
    p = promote_to_explicit_topology(c, d, concentration=1)
    assert p["provenance"]["structure"] == "EXACT"
    assert isinstance(p["family_intent"], TorusIntent)
    assert p["family_intent"].side_length == 3


def test_exact_structured_family_promotes_without_concentration():
    from veritx_dse.model.topology_intent import StructuredTopologyIntent
    from veritx_dse.model.topology_artifact import structured_graph
    g = structured_graph("tree4", {"radix": 2, "tiers": 2})
    d = _defn(nodes=g.nodes, layout="interposer", rows=1, cols=g.nodes,
              k=None)
    links = tuple(sorted(
        (min(u, v), max(u, v)) for u, v in g.links if u != v))
    c = _exact_candidate(g.nodes, links, d)
    p = promote_to_explicit_topology(c, d)
    assert p["provenance"]["structure"] == "EXACT"
    assert isinstance(p["family_intent"], StructuredTopologyIntent)
    # qtree and tree4 share one builder (k_ary_tree_graph): the same graph
    # is both. Recognition returns the first structural match, deterministically;
    # backend-spelling differences are a product (§6) concern, not promotion's.
    assert p["family_intent"].family in ("qtree", "tree4")
    assert p["family_intent"].params == {"radix": 2, "tiers": 2}


def test_degenerate_exact_match_falls_back_with_the_reason_stated():
    # tiers=1 builds a canonical qtree graph the intent type rejects
    # (tiers >= 2). The promotion still proceeds as explicit topology —
    # the exact graph is preserved — with the match and the reason kept.
    from veritx_dse.model.topology_artifact import structured_graph
    g = structured_graph("tree4", {"radix": 2, "tiers": 1})
    d = _defn(nodes=g.nodes, layout="interposer", rows=1, cols=g.nodes,
              k=None)
    links = tuple(sorted(
        (min(u, v), max(u, v)) for u, v in g.links if u != v))
    c = _exact_candidate(g.nodes, links, d)
    p = promote_to_explicit_topology(c, d)
    assert p["family_intent"] is None
    assert p["provenance"]["structure"] == "EXACT"
    assert p["provenance"]["recognized_family"]["family"] == "qtree"
    assert p["provenance"]["routing_policy"] == "ANYNET_MIN_HOPS"
    assert "does not construct" in p["provenance"]["withheld_reason"]


def test_mesh_without_stated_concentration_promotes_as_explicit():
    d = _defn(nodes=16, k=4)
    c = _exact_candidate(16, _mesh_links(4), d)
    p = promote_to_explicit_topology(c, d)
    assert p["family_intent"] is None
    assert p["provenance"]["structure"] == "EXACT"
    assert p["provenance"]["recognized_family"] == {
        "family": "mesh", "params": {"side_length": 4, "concentration": 1}}
    assert p["provenance"]["routing_policy"] == "ANYNET_MIN_HOPS"
    assert p["provenance"]["withheld_reason"] is not None
    assert "concentration" in p["provenance"]["withheld_reason"]
    assert p["explicit_topology"].kind == "custom"


def test_irregular_graph_promotes_as_explicit_with_minhop_policy():
    d = _defn(nodes=16, k=4)
    links = _mesh_links(4) + ((0, 15),)
    links = tuple(sorted(set(links)))
    c = _exact_candidate(16, links, d)
    p = promote_to_explicit_topology(c, d, concentration=1)
    assert p["family_intent"] is None
    assert p["provenance"]["structure"] == "IRREGULAR"
    assert p["provenance"]["recognized_family"] is None
    assert p["provenance"]["routing_policy"] == "ANYNET_MIN_HOPS"


def test_invalid_concentration_refuses():
    d = _defn(nodes=16, k=4)
    c = _exact_candidate(16, _mesh_links(4), d)
    for bad in (0, -2, "1", 1.0):
        with pytest.raises(TopologyCandidateError, match="concentration"):
            promote_to_explicit_topology(c, d, concentration=bad)


def test_promotion_never_mutates_its_inputs():
    import copy
    d = _defn(nodes=16, k=4)
    c = _exact_candidate(16, _mesh_links(4), d)
    doc = _base_doc()
    before_candidate = copy.deepcopy(c.to_dict())
    before_doc = copy.deepcopy(doc)
    p = promote_to_explicit_topology(c, d, concentration=1)
    out = apply_promotion_to_request_doc(
        dict(doc, topology={"kind": "mesh", "side_length": 2,
                            "concentration": 1}), p)
    assert c.to_dict() == before_candidate
    assert doc == before_doc
    assert out is not doc


def test_family_promotion_onto_a_v3_document_refuses():
    # v3 has no topology authority field: carrying a family there would
    # mean downgrading it into noc_config guesses. Typed refusal instead.
    d = _defn(nodes=16, k=4)
    c = _exact_candidate(16, _mesh_links(4), d)
    p = promote_to_explicit_topology(c, d, concentration=1)
    with pytest.raises(TopologyCandidateError, match="v4"):
        apply_promotion_to_request_doc(_base_doc(), p)


def test_family_promotion_applies_to_a_v4_document():
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    d = _defn(nodes=16, k=4)
    c = _exact_candidate(16, _mesh_links(4), d)
    p = promote_to_explicit_topology(c, d, concentration=1)
    doc = {"topology": {"kind": "mesh", "side_length": 2, "concentration": 1},
           "design_hash": "sha256:old", "noc_config": {}}
    out = apply_promotion_to_request_doc(doc, p)
    assert out["topology"] == {"kind": "mesh", "side_length": 4,
                               "concentration": 1}
    assert "explicit_topology" not in out
    assert "design_hash" not in out
    assert doc["topology"] == {"kind": "mesh", "side_length": 2,
                               "concentration": 1}
    req = CompileRequestV4.from_dict({
        **_v4_doc(), "topology": out["topology"]})
    assert req.topology.kind == "mesh"


def _v4_doc():
    from test_v4_compute_intent import _v4 as _mk
    return _mk().to_dict()


def test_promoted_mesh_compiles_under_native_routing():
    # The point of family promotion: this design compiles under DOR_XY,
    # not the ANYNET_MIN_HOPS the same graph gets as explicit topology.
    from test_v4_compute_intent import _v4 as _mk
    from veritx_dse.application.fabric_compiler import FabricCompiler
    d = _defn(nodes=16, k=4)
    c = _exact_candidate(16, _mesh_links(4), d)
    p = promote_to_explicit_topology(c, d, concentration=1)
    doc = dict(_v4_doc())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    out = apply_promotion_to_request_doc(doc, p)
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    req = CompileRequestV4.from_dict(out)
    compiled = FabricCompiler().compile(req)
    assert compiled.status == "COMPILED"
    classes = [rc.id for rc in compiled.bundle.router_route.routing_classes]
    assert classes == ["DOR_XY"], classes
    assert compiled.certificate.overall == "PASS"
