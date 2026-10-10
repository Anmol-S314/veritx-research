"""AI proposals are bounded topology changes, never workload or score edits."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from veritx_dse.application.authenticated_evaluation import verify_authenticated_backend_evaluation
from veritx_dse.application.presets import build_typed_preset_request
from veritx_dse.core.errors import EvidenceInvalid, InvalidInput
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.optimization.real_evaluator import RealCandidateEvaluator
from veritx_dse.optimization.topology_search import make_proposal, ProposalRefused


def _base():
    doc = build_typed_preset_request("srota32").to_dict()
    for key in ("design_hash", "guardrail_hash"):
        doc.pop(key)
    doc["noc_controls"]["link_width"] = 64
    doc["workload"] = {
        "model_family": "dense_transformer", "model_name": "fixed workload",
        "serving_mode": "mixed", "tp": 8, "dp": 1, "ep": 1, "pp": 1,
        "collectives": [{"kind": "allreduce", "dimension": "TP", "payload_bytes": 8192,
                         "source_rank": None, "traffic_class": "tp_collective"}],
        "workload_source_ref": None}
    doc["requirements"] = [{"traffic_class": "tp_collective", "qos_class": "latency_critical",
        "binding": True, "latency_ceiling_cycles": 100000, "bandwidth_floor_gbps": None}]
    return CompileRequestV4.from_dict(doc)


def _proposal(base, topology=None):
    return {"base_design_hash": base.design_hash(),
            "topology": topology or MeshIntent(6, 1).to_dict(),
            "rationale": "Reference mesh sized for the fixed agents."}


def test_only_topology_changes_and_rationale_is_not_scientific_identity():
    base = _base()
    candidate = make_proposal(base, _proposal(base))
    expected = base.to_dict()
    expected["topology"] = candidate.request.topology.to_dict()
    actual = candidate.request.to_dict()
    for derived in ("design_hash", "guardrail_hash"):
        expected.pop(derived)
        actual.pop(derived)
    assert actual == expected
    assert base.topology.kind == "srota"
    other = make_proposal(base, {**_proposal(base), "rationale": "Same topology, new explanation"})
    assert other.candidate_id == candidate.candidate_id


@pytest.mark.parametrize("field", ["workload", "requirements", "noc_config", "noc_controls", "objective_values", "qualified"])
def test_proposer_cannot_change_locked_context_or_supply_scores(field):
    base = _base()
    with pytest.raises(ProposalRefused, match="locked"):
        make_proposal(base, {**_proposal(base), field: {}})


def test_stale_base_is_refused():
    base = _base()
    with pytest.raises(ProposalRefused, match="stale"):
        make_proposal(base, {**_proposal(base), "base_design_hash": "old"})


@pytest.mark.parametrize("topology", [
    {"kind": "mesh", "side_length": 1000000, "concentration": 1},
    {"kind": "flatfly", "radix_per_dimension": 64, "dimension_count": 64, "concentration": 1},
    {"kind": "structured", "family": "qtree", "params": {"radix": 32, "tiers": 2}},
    {"kind": "mesh", "side_length": 4, "concentration": 1000},
])
def test_huge_expansion_is_refused_before_materialization(monkeypatch, topology):
    from veritx_dse.optimization import topology_search

    def forbidden(*args, **kwargs):
        raise AssertionError("unbounded proposal reached materialization")

    monkeypatch.setattr(topology_search, "materialize_topology", forbidden)
    base = _base()
    with pytest.raises(ProposalRefused):
        make_proposal(base, _proposal(base, topology))


def test_explicit_graph_attrs_are_pinned_and_degree_budget_is_enforced():
    base = _base()
    graph = {"name": "tree", "kind": "custom", "nodes": 32,
             "links": [[(i - 1) // 2, i] for i in range(1, 32)]}
    candidate = make_proposal(base, _proposal(base, {"kind": "explicit", "graph": graph}))
    assert candidate.request.topology.graph.link_attrs == {"bandwidth_GBs": 8.0, "latency_ns": 1.0}
    with pytest.raises(ProposalRefused, match="locked"):
        make_proposal(base, _proposal(base, {"kind": "explicit", "graph": {**graph, "link_attrs": {"latency_ns": 0.01}}}))
    graph["links"] = [[0, i] for i in range(1, 32)]
    with pytest.raises(ProposalRefused, match="degree"):
        make_proposal(base, _proposal(base, {"kind": "explicit", "graph": graph}))


def test_cannot_resize_agents_to_fit_candidate():
    base = _base()
    with pytest.raises(ProposalRefused, match="fixed agents"):
        make_proposal(base, _proposal(base, MeshIntent(2, 1).to_dict()))


def _cli(tmp_path, monkeypatch):
    from veritx_dse.optimization import topology_search
    base = _base()
    source = tmp_path / "base.json"
    proposal = tmp_path / "proposal.json"
    source.write_text(json.dumps(base.to_dict()))
    proposal.write_text(json.dumps(_proposal(base)))
    root = tmp_path / "study"
    monkeypatch.setattr("sys.argv", ["topology_search", "--base", str(source),
        "--proposal", str(proposal), "--run-root", str(root)])
    return topology_search, base, proposal, root


def test_feedback_consumes_refusals_and_duplicates_and_stops_at_budget(tmp_path, monkeypatch):
    module, base, proposal, root = _cli(tmp_path, monkeypatch)
    calls = []

    def refuse(self, candidate):
        calls.append(candidate)
        return SimpleNamespace(status="UNSUPPORTED", error="test refusal",
            compilation_status="COMPILED", performance_result_id=None, requirement_report=None)

    monkeypatch.setattr(RealCandidateEvaluator, "evaluate", refuse)
    module.main()  # A valid candidate whose execution is refused.
    module.main()  # The duplicate consumes a slot, but is not executed again.
    proposal.write_text(json.dumps({**_proposal(base), "qualified": True}))
    module.main()
    module.main()
    with pytest.raises(ProposalRefused, match="budget exhausted"):
        module.main()
    feedback = json.loads((root / "feedback.json").read_text())
    assert len(calls) == 1
    assert [r["status"] for r in feedback["proposals"]] == ["UNSUPPORTED", "REFUSED", "REFUSED", "REFUSED"]
    assert all(r["objective_values"] == {} for r in feedback["proposals"])
    assert not (root / ".proposal.lock").exists()


def test_unproved_evaluated_label_cannot_write_a_score(tmp_path, monkeypatch):
    module, _, _, root = _cli(tmp_path, monkeypatch)
    monkeypatch.setattr(RealCandidateEvaluator, "evaluate", lambda self, candidate:
        SimpleNamespace(status="EVALUATED", error=None, compilation_status="COMPILED",
            performance_result_id="invented", requirement_report={}, authenticated_proof=None,
            objective_values={"completion_cycles": 1}))
    with pytest.raises(InvalidInput, match="AuthenticatedBackendEvaluation"):
        module.main()
    record = json.loads((root / "feedback.json").read_text())["proposals"][0]
    assert record["status"] == "SUBMITTED"
    assert record["objective_values"] == {}
    assert not (root / ".proposal.lock").exists()


def test_real_typed_candidate_is_measured_and_proof_reverified(tmp_path):
    repo = Path(__file__).resolve().parents[4]
    binary = repo / "third_party/booksim2/src/booksim"
    if not binary.is_file():
        pytest.skip("qualified BookSim binary unavailable")
    base = _base()
    candidate = make_proposal(base, _proposal(base))
    outcome = RealCandidateEvaluator(binary=binary, repo_root=repo,
        run_root=tmp_path, network_clock_hz=1_000_000_000, timeout_s=30).evaluate(candidate)
    assert outcome.status == "EVALUATED", outcome.error
    assert outcome.error is None
    claims = verify_authenticated_backend_evaluation(candidate.request, outcome.authenticated_proof)
    assert claims.design_hash == candidate.request.design_hash()
    assert claims.evidence_ref.sha256
    assert outcome.objective_values["completion_cycles"] > 0
    tampered = replace(candidate.request, topology=MeshIntent(4, 2))
    with pytest.raises(EvidenceInvalid, match="proof.design_hash"):
        verify_authenticated_backend_evaluation(tampered, outcome.authenticated_proof)
