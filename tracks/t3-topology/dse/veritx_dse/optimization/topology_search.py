"""Bounded topology-only proposal/evidence bridge for an AI caller.

The caller supplies one proposal, reads feedback, then proposes again. This
module makes no model calls and never adopts a design. The existing certified
evaluator owns every measurement. Run with python -m ...topology_search.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import VeritXError
from veritx_dse.model.compile_model import fabric_intent_view
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.placement import build_inventory
from veritx_dse.model.topology_artifact import materialize_topology
from veritx_dse.model.topology_intent import topology_intent_from_dict

LIMITS = {"max_proposals": 4, "max_routers": 64, "max_channels": 256,
          "max_network_degree": 8, "max_seats": 64, "backend_timeout_s": 30}
KINDS = ("mesh", "concentrated_mesh", "torus", "flatfly", "explicit")


class ProposalRefused(ValueError):
    """A stale, unbounded or out-of-scope proposal; never a score."""


@dataclass(frozen=True)
class TopologyProposal:
    candidate_id: str
    base_design_hash: str
    request: CompileRequestV4
    rationale: str


def make_proposal(base: CompileRequestV4, proposal: dict[str, Any]) -> TopologyProposal:
    if not isinstance(base, CompileRequestV4):
        raise ProposalRefused("topology search requires a canonical v4 base")
    if not isinstance(proposal, dict) or set(proposal) != {
            "base_design_hash", "topology", "rationale"}:
        raise ProposalRefused("only base_design_hash, topology and rationale are allowed; workload, controls, constraints and scores are locked")
    if proposal["base_design_hash"] != base.design_hash():
        raise ProposalRefused("stale base_design_hash")
    if not isinstance(proposal["rationale"], str) or not proposal["rationale"].strip():
        raise ProposalRefused("proposal needs a rationale, not a predicted score")
    raw = proposal["topology"]
    if not isinstance(raw, dict) or raw.get("kind") not in KINDS:
        raise ProposalRefused(f"this bounded pilot accepts {KINDS}; other kinds are not searched")
    raw = dict(raw)
    required = sum(agent.count for agent in base.agents)
    if raw["kind"] == "explicit":
        graph = raw.get("graph")
        if not isinstance(graph, dict) or set(graph) != {"name", "kind", "nodes", "links"}:
            raise ProposalRefused("graph takes name, kind, nodes, links only; link timing/bandwidth are locked")
        nodes = graph["nodes"]
        links = graph["links"]
        if type(nodes) is not int or not 2 <= nodes <= LIMITS["max_routers"]:
            raise ProposalRefused("graph exceeds router budget")
        if not isinstance(links, list) or len(links) * 2 > LIMITS["max_channels"]:
            raise ProposalRefused("graph exceeds channel budget")
        if nodes < required:
            raise ProposalRefused("topology cannot seat the fixed agents")
        mhz = base.physical.default_clock_freq_mhz
        width = base.noc_controls.link_width
        if mhz is None or width is None:
            raise ProposalRefused("explicit graph needs declared clock and link width")
        raw["graph"] = {**graph, "link_attrs": {
            "bandwidth_GBs": width * mhz / 8000, "latency_ns": 1000 / mhz}}
    else:
        # Bound BEFORE expansion; a small parameter list can name a huge graph.
        keys = (["side_length", "concentration"] if raw["kind"] != "flatfly"
                else ["radix_per_dimension", "dimension_count", "concentration"])
        for key in keys:
            value = raw.get(key, 1 if key == "concentration" else None)
            if type(value) is not int or not 1 <= value <= LIMITS["max_routers"]:
                raise ProposalRefused(f"unbounded {key}")
        routers = (raw["radix_per_dimension"] ** raw["dimension_count"]
                   if raw["kind"] == "flatfly" else raw["side_length"] ** 2)
        if routers > LIMITS["max_routers"] or routers * raw.get("concentration", 1) > LIMITS["max_seats"]:
            raise ProposalRefused("topology exceeds router/seat budget")
        if routers * raw.get("concentration", 1) < required:
            raise ProposalRefused("topology cannot seat the fixed agents")
    intent = topology_intent_from_dict(raw)
    request = replace(base, topology=intent)
    topology = materialize_topology(build_inventory(request), fabric_intent_view(request))
    if len(topology.routers) > LIMITS["max_routers"] or len(topology.channels) > LIMITS["max_channels"]:
        raise ProposalRefused("materialized topology exceeds graph budget")
    degree = Counter(channel.src_router for channel in topology.channels)
    if max(degree.values(), default=0) > LIMITS["max_network_degree"]:
        raise ProposalRefused("materialized topology exceeds network-degree budget")
    seats = sum(router.seat_capacity for router in topology.routers)
    if not required <= seats <= LIMITS["max_seats"]:
        raise ProposalRefused("topology cannot seat the fixed agents within budget")
    cid = "tprop_" + content_id("veritx/topology-proposal/v1", {
        "base_design_hash": base.design_hash(), "design_hash": request.design_hash()})
    return TopologyProposal(cid, base.design_hash(), request, proposal["rationale"])


def evaluate_candidate(candidate, evaluator, *, proof_path: Path | None = None) -> dict[str, Any]:
    """Metrics enter only through consumption-time authenticated evidence."""
    from veritx_dse.application.authenticated_evaluation import verify_authenticated_backend_evaluation
    from veritx_dse.optimization.metric_registry import CERTIFIED_METRIC_REGISTRY
    outcome = evaluator.evaluate(candidate)
    record = {"status": outcome.status, "reason": outcome.error,
              "compilation_status": outcome.compilation_status,
              "performance_result_id": outcome.performance_result_id,
              "requirement_report": outcome.requirement_report,
              "objective_values": {}}
    if outcome.status == "EVALUATED":
        claims = verify_authenticated_backend_evaluation(candidate.request, outcome.authenticated_proof)
        measured = CERTIFIED_METRIC_REGISTRY.extract_all(claims.verified_result)
        record.update(objective_values={"completion_cycles": measured["completion_cycles"]},
                      evidence_path=str(claims.evidence_ref.path),
                      evidence_sha256=claims.evidence_ref.sha256,
                      backend_profile=claims.backend_profile,
                      execution_fidelity=claims.execution_fidelity)
        if proof_path is not None:
            proof = outcome.authenticated_proof
            document = {"design_hash": proof.design_hash, "workload_id": proof.workload_id,
                "physical_traffic_id": proof.physical_traffic_id,
                "backend_input_hash": proof.backend_input_hash,
                "evidence_ref": {"path": str(proof.evidence_ref.path), "sha256": proof.evidence_ref.sha256},
                "evidence_artifact": proof.evidence_artifact.to_dict(),
                "producer_identity": proof.producer_identity, "binding": proof.binding.to_dict(),
                "verified_result": dict(proof.verified_result),
                "temporal_workload": proof.verified_result.temporal_workload.to_dict(),
                "requirement_report": proof.requirement_report}
            temporary = proof_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(document))
            temporary.replace(proof_path)
    return record


def reverify_saved_candidate(request, proof_path: Path):
    """Rebuild branded objects and reprove the chain; never trust stored scores."""
    from veritx_dse.application.authenticated_evaluation import (
        AuthenticatedBackendEvaluation, verify_authenticated_backend_evaluation,
    )
    from veritx_dse.application.requirements import verify_performance_result
    from veritx_dse.backend.evidence import EvidenceArtifact, EvidenceRef
    from veritx_dse.core.errors import EvidenceInvalid
    from veritx_dse.performance.network import NetworkWindowBinding
    from veritx_dse.performance.workload import TemporalWorkload
    document = json.loads(proof_path.read_text())
    if not Path(document["evidence_ref"]["path"]).resolve().is_relative_to((proof_path.parent / "evidence").resolve()):
        raise EvidenceInvalid("evidence reference escaped its job workspace")
    temporal = TemporalWorkload.from_dict(document.pop("temporal_workload"))
    document["verified_result"] = verify_performance_result(document["verified_result"], workload=temporal)
    document["evidence_ref"] = EvidenceRef(**document["evidence_ref"])
    document["evidence_artifact"] = EvidenceArtifact.from_dict(document["evidence_artifact"])
    document["binding"] = NetworkWindowBinding.from_dict(document["binding"])
    return verify_authenticated_backend_evaluation(request, AuthenticatedBackendEvaluation(**document))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.base.read_text())
    base = CompileRequestV4.from_dict(source.get("request", source))
    raw = json.loads(args.proposal.read_text())
    args.run_root.mkdir(parents=True, exist_ok=True)
    lock = args.run_root / ".proposal.lock"
    with lock.open("x"):
        pass
    try:
        feedback_path = args.run_root / "feedback.json"
        feedback = (json.loads(feedback_path.read_text()) if feedback_path.exists() else {
            "base_design_hash": base.design_hash(), "limits": LIMITS,
            "base_request": base.to_dict(), "proposals": [],
            "scope": "assistant-guided pilot; network completion only; no adoption or hardware runtime/area/power claim"})
        if feedback["base_design_hash"] != base.design_hash() or feedback["limits"] != LIMITS:
            raise ProposalRefused("feedback belongs to a different base or policy")
        if len(feedback["proposals"]) >= LIMITS["max_proposals"]:
            raise ProposalRefused("proposal budget exhausted")
        record = {"proposal": raw, "status": "SUBMITTED", "objective_values": {}}
        feedback["proposals"].append(record)

        def persist() -> None:
            temporary = feedback_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(feedback, indent=2) + "\n")
            temporary.replace(feedback_path)

        persist()  # A failed/interrupted attempt still consumes its slot.
        try:
            candidate = make_proposal(base, raw)
            if any(row.get("candidate_id") == candidate.candidate_id for row in feedback["proposals"][:-1]):
                raise ProposalRefused("duplicate candidate; no repeat simulation")
        except (ValueError, VeritXError) as exc:
            record.update(status="REFUSED", reason=str(exc))
        else:
            from veritx_dse.optimization.real_evaluator import RealCandidateEvaluator
            repo = Path(__file__).resolve().parents[5]
            evaluator = RealCandidateEvaluator(
                binary=repo / "third_party/booksim2/src/booksim",
                repo_root=repo, run_root=args.run_root / "evidence",
                network_clock_hz=int(base.physical.default_clock_freq_mhz * 1_000_000),
                timeout_s=LIMITS["backend_timeout_s"])
            record.update(candidate_id=candidate.candidate_id,
                          request=candidate.request.to_dict())
            persist()
            record.update(evaluate_candidate(candidate, evaluator))
        persist()
        print(json.dumps(record, indent=2))
    finally:
        lock.unlink()


if __name__ == "__main__":
    main()
