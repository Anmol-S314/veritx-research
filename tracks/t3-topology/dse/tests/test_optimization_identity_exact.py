"""Optimizer construction edge cases (P0.14).

An empty guided domain is refused at definition construction (an empty
patch is illegal and would only fail later), and candidate scientific
identity is the FULL content hash, never a truncated alias.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.optimization.candidate import (  # noqa: E402
    Candidate, candidate_id_for,
)
from veritx_dse.optimization.definition import (  # noqa: E402
    DomainParam, Objective, OptimizationDefinition,
    OptimizationDefinitionError,
)


def test_empty_guided_domain_refused_at_construction():
    with pytest.raises(OptimizationDefinitionError, match="domain is empty"):
        OptimizationDefinition(
            domain=(), objectives=(Objective("latency", "MIN"),))


def test_random_with_empty_domain_still_refused():
    with pytest.raises(OptimizationDefinitionError, match="domain is empty"):
        OptimizationDefinition(
            domain=(), objectives=(Objective("latency", "MIN"),),
            method="random", seed=1)


def test_candidate_identity_is_the_full_digest():
    cid = candidate_id_for("a" * 64, {"link_width": 64})
    assert cid.startswith("cand_")
    assert len(cid) == len("cand_") + 64
    assert cid == candidate_id_for("a" * 64, {"link_width": 64})


def test_truncated_candidate_id_is_not_accepted():
    full = candidate_id_for("a" * 64, {"link_width": 64})
    with pytest.raises(ValueError):
        Candidate(candidate_id=full[:21], base_design_hash="a" * 64,
                  guided_patch={"link_width": 64}, request=None)
