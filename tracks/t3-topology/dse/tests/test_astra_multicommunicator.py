"""Multi-communicator ASTRA projection (§7).

A real MoE workload carries SEVERAL communicator structures at once
(TP groups of 2 AND EP groups of 4 over the same ranks). The historical
`derive_logical_dimensions` refused any unequal participant sets, which
made every MoE workload unexecutable. These tests pin the supported
structures and the refusal of genuinely malformed ones.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.backend.astra_machine import (  # noqa: E402
    AstraMachineError, derive_logical_dimensions,
)

def _projection(participants: int, collectives):
    """Minimal projection stub: only the fields the derivation reads."""
    return SimpleNamespace(
        participant_count=participants,
        ranks=lambda: tuple(range(participants)),
        collective_operations=tuple(
            (f"op{i}", kind, 1024, tuple(sorted(parts)))
            for i, (kind, parts) in enumerate(collectives)),
    )

def _tp_groups(tp: int, ep: int):
    ranks = tp * ep
    tps = [tuple(range(t * ep, t * ep + ep)) for t in range(tp)]
    eps = [tuple(range(e, ranks, ep)) for e in range(ep)]
    return ranks, tps, eps

class TestMixedCommunicators:
    def test_tp2_ep4_is_accepted_and_records_both_sizes(self):
        ranks, tps, eps = _tp_groups(2, 4)
        ops = [(("ALLREDUCE"), g) for g in tps] + [(("ALLTOALL"), g) for g in eps]
        topo = derive_logical_dimensions(_projection(ranks, ops))
        assert topo.dimensions == (8,)
        assert topo.derivation == "communicator_group_structure(2,4)"
        assert topo.product() == ranks

    def test_tp4_ep2_is_accepted(self):
        ranks, tps, eps = _tp_groups(4, 2)
        ops = [(("ALLREDUCE"), g) for g in tps] + [(("ALLTOALL"), g) for g in eps]
        topo = derive_logical_dimensions(_projection(ranks, ops))
        assert topo.dimensions == (8,)
        assert "2,4" in topo.derivation

    def test_tp8_ep8_over_64_ranks_is_one_uniform_size(self):
        ranks = 64
        tps = [tuple(range(t * 8, t * 8 + 8)) for t in range(8)]
        eps = [tuple(range(e, ranks, 8)) for e in range(8)]
        ops = [(("ALLREDUCE"), g) for g in tps] + [(("ALLTOALL"), g) for g in eps]
        topo = derive_logical_dimensions(_projection(ranks, ops))
        assert topo.dimensions == (8, 8)
        assert topo.derivation == "collective_group_structure"

    def test_tp_only_subset_keeps_the_two_dimension_form(self):
        ranks = 4
        ops = [(("ALLREDUCE"), (0, 1)), (("ALLREDUCE"), (2, 3))]
        topo = derive_logical_dimensions(_projection(ranks, ops))
        assert topo.dimensions == (2, 2)
        assert topo.derivation == "collective_group_structure"

    def test_ep_only_subset_single_size(self):
        ranks = 8
        ops = [(("ALLTOALL"), (0, 2, 4, 6)), (("ALLTOALL"), (1, 3, 5, 7))]
        topo = derive_logical_dimensions(_projection(ranks, ops))
        assert topo.dimensions == (2, 4)
        assert topo.derivation == "collective_group_structure"

    def test_overlapping_communicators_are_allowed(self):
        ranks = 8
        ops = [(("ALLREDUCE"), (0, 1)), (("ALLTOALL"), (0, 2, 4, 6))]
        topo = derive_logical_dimensions(_projection(ranks, ops))
        assert topo.dimensions == (8,)
        assert "2,4" in topo.derivation

    def test_flat_all_participants_unchanged(self):
        topo = derive_logical_dimensions(
            _projection(4, [(("ALLREDUCE"), (0, 1, 2, 3))]))
        assert topo.dimensions == (4,)
        assert topo.derivation == "flat_all_participants"

    def test_size_that_does_not_divide_participants_refuses(self):
        with pytest.raises(AstraMachineError, match="does not divide"):
            derive_logical_dimensions(
                _projection(8, [(("ALLREDUCE"), (0, 1, 2)),
                                (("ALLTOALL"), (0, 2, 4, 6))]))

    def test_singleton_group_refuses(self):
        with pytest.raises(AstraMachineError, match="does not divide"):
            derive_logical_dimensions(
                _projection(8, [(("ALLREDUCE"), (0,)),
                                (("ALLTOALL"), (0, 2, 4, 6))]))

    def test_non_dense_namespace_refuses(self):
        proj = _projection(4, [(("ALLREDUCE"), (0, 1))])
        proj.ranks = lambda: (0, 1, 2)
        with pytest.raises(AstraMachineError, match="dense participant"):
            derive_logical_dimensions(proj)
