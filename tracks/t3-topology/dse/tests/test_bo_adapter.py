"""Adapter tests: BO parameterized-generator producer."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.synthesis import bo_adapter as B  # noqa: E402
from veritx_dse.synthesis.rho_grpo_adapter import (  # noqa: E402
    AdapterVocabularyPending,
    CandidateRejected,
    is_connected,
)


def _demands(n: int):
    return [[0.0 if i == j else 1.0 for j in range(n)] for i in range(n)]


def test_generator_params_validated():
    with pytest.raises(CandidateRejected):
        B.GeneratorParams(cluster_size=7)
    with pytest.raises(CandidateRejected):
        B.GeneratorParams(radix=9)
    with pytest.raises(CandidateRejected):
        B.GeneratorParams(intra_weight=0.1)


def test_generate_topology_deterministic_connected_radix():
    p = B.GeneratorParams(cluster_size=4, express_length=2, radix=4)
    a = B.generate_topology(16, p, seed=5)
    b = B.generate_topology(16, p, seed=5)
    assert a == b and is_connected(16, a)
    deg = [0] * 16
    for u, v in a:
        deg[u] += 1
        deg[v] += 1
    assert max(deg) <= 4


def test_run_bo_seeded_random_honest():
    d = _demands(16)
    a = B.run_bo(definition_id="d", traffic_id="t", nodes=16,
                 demands=d, seed=9, iters=4)
    b = B.run_bo(definition_id="d", traffic_id="t", nodes=16,
                 demands=d, seed=9, iters=4)
    assert a.links == b.links and a.surrogate == "seeded-random"


def test_gp_surrogate_refused_until_vendored():
    with pytest.raises(Exception, match="not vendored"):
        B.run_bo(definition_id="d", traffic_id="t", nodes=16,
                 demands=_demands(16), seed=1, iters=1,
                 surrogate="gaussian-process")


def test_no_uniform_fallback():
    with pytest.raises(CandidateRejected):
        B.run_bo(definition_id="d", traffic_id="t", nodes=16,
                 demands=[[1.0]], seed=1, iters=1)


def test_vocabulary_gate():
    d = _demands(16)
    p = B.run_bo(definition_id="d", traffic_id="t", nodes=16,
                 demands=d, seed=2, iters=2)
    with pytest.raises(AdapterVocabularyPending) as exc:
        B.to_topology_candidate(p)
    assert "bo_gp" in str(exc.value)
