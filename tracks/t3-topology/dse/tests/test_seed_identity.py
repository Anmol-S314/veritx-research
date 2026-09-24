"""Seed identity (P0.7): the executed simulation seed is fixed at prepare.

The simulation seed is rendered into the config, bound into the prepared
identity, propagated into evidence, and cannot be overridden at execution.
It is distinct from the optimizer's search seed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_backend_booksim_projection import _parents  # noqa: E402

from veritx_dse.backend import booksim_projection as bp  # noqa: E402
from veritx_dse.backend.booksim_execution import (  # noqa: E402
    BookSimExecutionError, execute_prepared_booksim,
)


def _prepared(seed: int):
    _compiled, parents = _parents()
    return bp.prepare_booksim_input(parents, seed=seed)


def test_different_sim_seed_changes_config_and_prepared_identity():
    a = _prepared(1)
    b = _prepared(2)
    assert a.seed != b.seed
    assert a.config_text != b.config_text
    assert a.prepared_id() != b.prepared_id()


def test_same_sim_seed_is_stable():
    assert _prepared(7).prepared_id() == _prepared(7).prepared_id()


def test_seed_is_part_of_the_identity_dict():
    assert _prepared(3).identity_dict()["seed"] == 3


def test_execution_may_not_override_the_prepared_seed(tmp_path):
    prepared = _prepared(5)
    with pytest.raises(BookSimExecutionError, match="does not match the "
                       "prepared identity seed"):
        execute_prepared_booksim(
            prepared=prepared, binary=tmp_path / "booksim",
            run_dir=tmp_path / "run", timeout=1, seed=6)
