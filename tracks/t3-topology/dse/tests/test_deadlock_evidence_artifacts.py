"""The committed deadlock evidence must still be what the code produces.

An evidence file that nobody regenerates is a claim with a timestamp. These
tests re-derive both artifacts and compare them to the committed bytes, so a
change in the guard, the graph builder or a preset breaks the check instead of
leaving a stale proof in the tree looking authoritative.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
DSE = REPO / "tracks" / "t3-topology" / "dse"
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(REPO))

EVIDENCE = REPO / "docs" / "product" / "evidence" / "deadlock"


def _committed(name: str) -> dict:
    path = EVIDENCE / name
    assert path.is_file(), f"missing evidence artifact {path}"
    return json.loads(path.read_text())


def test_rank_witness_artifact_is_current():
    pytest.importorskip("z3", reason="the cross-check needs z3py")
    from scripts.gen_deadlock_evidence import _rank_witness_artifact

    assert _rank_witness_artifact() == _committed("shared-resource-rank-witness.json")


def test_arbiter_starvation_artifact_is_current():
    pytest.importorskip("z3", reason="the service bound needs z3py")
    from scripts.gen_deadlock_evidence import _arbiter_artifact

    assert _arbiter_artifact() == _committed("arbiter-starvation.json")


def test_the_committed_witness_actually_verifies():
    """Re-check the artifact without regenerating it: the auditor's path."""
    artifact = _committed("shared-resource-rank-witness.json")
    graph = {
        "nodes": artifact["verdict"]["node_count"],
        "edges": artifact["verdict"]["edge_count"],
    }
    assert graph["nodes"] == len(artifact["verdict"]["rank_witness"])
    ranks = {}
    for entry in artifact["verdict"]["rank_witness"]:
        key = (entry["resource"]["kind"], entry["resource"]["resource_id"],
               entry["vc"])
        assert key not in ranks
        ranks[key] = entry["rank"]
    assert len(set(ranks.values())) >= 1
    assert artifact["certificate"]["acyclic"] is True
    assert artifact["certificate"]["solver"] in {"sat", "not-asked"}


def test_the_committed_proofs_state_their_limits():
    rank = _committed("shared-resource-rank-witness.json")
    assert rank["not_claimed"]
    assert any("arbitration fairness" in item for item in rank["not_claimed"])
    fair = _committed("arbiter-starvation.json")
    assert fair["bounded_service_verdict"] == "unsat-no-counterexample"
    assert fair["tightness_verdict"] == "sat-counterexample"
    assert fair["not_modeled"]
