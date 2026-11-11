#!/usr/bin/env python3
"""Emit the deadlock-freedom and fairness evidence artifacts.

Two proofs, one file each, both regenerable so a reader never has to take a
verdict on trust:

  * ``deadlock/shared-resource-rank-witness.json`` -- the shared-wire fabric's
    dependency graph, its rank witness, the SMT encoding of the same question,
    and the solver's independent answer. Covers the two fabrics that carry
    shared wires and the point where A7's named residual was open.
  * ``deadlock/arbiter-starvation.json`` -- the output-wire starvation guard's
    bounded-service proof, bound to the router source by digest.

Both artifacts are content-addressed and deterministic: re-running this script
on unchanged source reproduces them byte for byte, which is why the regression
test can assert they are current instead of merely present.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DSE = REPO / "tracks" / "t3-topology" / "dse"
sys.path.insert(0, str(DSE))

OUT = REPO / "docs" / "product" / "evidence" / "deadlock"


def _write(name: str, payload: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def _rank_witness_artifact() -> dict:
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.presets import build_typed_preset_request
    from veritx_dse.verification.shared_resource_cdg_proof import certificate
    from veritx_dse.verification.shared_resource_deadlock import (
        verify_shared_resource_deadlock,
    )

    request = build_typed_preset_request("srota32_rank")
    compilation = FabricCompiler().compile(request)
    if compilation.status != "COMPILED":
        raise SystemExit(f"preset did not compile: {compilation.error}")
    route = compilation.bundle.router_route
    verdict = verify_shared_resource_deadlock(route)
    if verdict.verdict != "PASS":
        raise SystemExit(f"verdict is {verdict.verdict}: {verdict.reason}")
    graph = route.shared_resource_cdg()
    cert = certificate(graph)
    if not cert["acyclic"]:
        raise SystemExit("the certificate layer says the graph is cyclic")
    return {
        "schema": "veritx/deadlock-evidence/1",
        "subject": "SROTA rank policy fabric (shared wires, 4 rank VC sets)",
        "preset": "srota32_rank",
        "route_artifact_id": verdict.route_artifact_id,
        "routing_class": verdict.routing_class,
        "graph": {
            "cdg_id": graph.cdg_id(),
            "nodes": graph.node_count,
            "edges": graph.edge_count,
            "partitions": {str(k): list(v) for k, v in
                           sorted(graph.partition_to_vcs.items())},
        },
        "verdict": verdict.as_dict(),
        "certificate": {
            "acyclic": cert["acyclic"],
            "solver": cert["solver"],
            "reason": cert["reason"],
            "proof": cert["proof"],
            "smt_sha256": __import__("hashlib").sha256(
                cert["smtlib"].encode()).hexdigest(),
        },
        "readers": [
            "depth-first cycle search (verdicts FAIL and names the cycle)",
            "Kahn topological rank (produces the witness)",
            "z3 on the emitted SMT-LIB (re-decides without our traversal)",
        ],
        "how_to_audit": (
            "verify_rank_witness(graph, witness_ranks) checks every dependency "
            "edge strictly increases; it needs no solver and no trust in the "
            "producer. Then diff the ranks against the solver model."),
        "not_claimed": [
            "arbitration fairness",
            "credit or buffer availability",
            "traffic-class injection eligibility",
            "sufficiency for egress under an arbitrary arbitration policy",
        ],
    }


def _arbiter_artifact() -> dict:
    from veritx_dse.verification.arbiter_starvation import verify

    return {"schema": "veritx/deadlock-evidence/1",
            "subject": "output-wire escape/free starvation guard",
            **verify()}


def main() -> int:
    rank = _write("shared-resource-rank-witness.json", _rank_witness_artifact())
    fair = _write("arbiter-starvation.json", _arbiter_artifact())
    print(f"wrote {rank.relative_to(REPO)}")
    print(f"wrote {fair.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
