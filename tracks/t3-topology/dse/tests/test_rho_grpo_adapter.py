"""Adapter tests: RHO/GRPO deterministic candidate producers."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.synthesis import rho_grpo_adapter as A  # noqa: E402


def _demands(n: int):
    return [[0.0 if i == j else 1.0 for j in range(n)] for i in range(n)]


def test_rho_deterministic_under_seed():
    d = _demands(16)
    a = A.run_rho(definition_id="d", traffic_id="t", nodes=16, k=4,
                  demands=d, seed=7, steps=4)
    b = A.run_rho(definition_id="d", traffic_id="t", nodes=16, k=4,
                  demands=d, seed=7, steps=4)
    assert a.links == b.links and a.objective_value == b.objective_value


def test_grpo_deterministic_under_seed():
    d = _demands(16)
    a = A.run_grpo(definition_id="d", traffic_id="t", nodes=16, k=4,
                   demands=d, seed=11, steps=4)
    b = A.run_grpo(definition_id="d", traffic_id="t", nodes=16, k=4,
                   demands=d, seed=11, steps=4)
    assert a.links == b.links


def test_proposals_stay_connected_and_budgeted():
    d = _demands(16)
    for fn in (A.run_rho, A.run_grpo):
        p = fn(definition_id="d", traffic_id="t", nodes=16, k=4,
               demands=d, seed=3, steps=5, max_edges=40, radix=4)
        assert A.is_connected(16, p.links)
        assert len(p.links) <= 40
        deg = [0] * 16
        for u, v in p.links:
            deg[u] += 1
            deg[v] += 1
        assert max(deg) <= 4


def test_dimension_mismatch_refused_no_uniform_fallback():
    with pytest.raises(A.CandidateRejected):
        A.traffic_weighted_hops(16, frozenset({(0, 1)}), [[1.0]])
    with pytest.raises(A.CandidateRejected):
        A.run_rho(definition_id="d", traffic_id="t", nodes=16, k=4,
                  demands=[[1.0]], seed=1, steps=1)


def test_disconnected_never_penalized():
    with pytest.raises(A.CandidateRejected):
        A.traffic_weighted_hops(4, frozenset({(0, 1)}),
                                _demands(4))


def test_sentinels_refused():
    for bad in (1000.0, 1e9, float("inf"), float("nan")):
        with pytest.raises(A.CandidateRejected):
            A.check_objective_honest(bad)


def test_no_backend_authority():
    for mod in ("rho_grpo_adapter",):
        src = (DSE / "veritx_dse" / "synthesis" / f"{mod}.py").read_text()
        tree = ast.parse(src)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        assert not any("booksim" in m or "subprocess" in m for m in imported)
        assert "subprocess.run" not in src and "Popen" not in src
        assert "select_booksim_profile" not in src


def test_conversion_yields_feasible_typed_candidate():
    d = _demands(16)
    p = A.run_rho(definition_id="d", traffic_id="t", nodes=16, k=4,
                  demands=d, seed=1, steps=1)
    cand = A.to_topology_candidate(p)
    assert cand.algorithm == "rho_iterative"
    assert cand.solver_status == "FEASIBLE"  # never OPTIMAL for heuristics
    assert cand.status == "SUCCEEDED"
    assert cand.objective_value == p.objective_value
    assert tuple(sorted(p.links)) == cand.links


def test_vocabulary_gate_still_typed_for_unknown():
    import dataclasses

    d = _demands(16)
    p = A.run_rho(definition_id="d", traffic_id="t", nodes=16, k=4,
                  demands=d, seed=1, steps=1)
    bad = dataclasses.replace(p, algorithm="not_an_engine")
    with pytest.raises(A.AdapterVocabularyPending) as exc:
        A.to_topology_candidate(bad)
    assert "not_an_engine" in str(exc.value)


def test_grpo_is_relative_selection_not_policy():
    import inspect

    src = inspect.getsource(A.run_grpo)
    assert "baseline" in src
    for machinery in ("torch", ".backward", "optimizer.step",
                      "policy_net", "logits"):
        assert machinery not in src
