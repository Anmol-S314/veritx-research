"""F-0005: ring ALLGATHER forwards B/k chunks, not the whole payload.

Production (and the reference that was copied from it) used message_bytes
= B for ALLGATHER, so aggregate was k(k-1)B instead of the ring law
(k-1)B — a factor-k over-transmission. This pins the corrected law and the
internal consistency of every pinned schedule.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.verification.reference_semantics import ref_collective  # noqa: E402
from veritx_dse.workload.collectives import collective_schedule  # noqa: E402


@pytest.mark.parametrize("k,B", [(16, 1024), (4, 1024), (2, 8)])
def test_allgather_ring_chunk_law(k, B):
    sched = collective_schedule("ALLGATHER", k, B)
    assert sched["message_count"] == k * (k - 1)
    assert sched["message_bytes"] == B // k
    assert sched["aggregate_payload"] == (k - 1) * B


def test_allgather_matches_independent_reference():
    assert collective_schedule("ALLGATHER", 16, 1024) \
        == ref_collective("ALLGATHER", 16, 1024)


def test_every_pinned_schedule_is_internally_consistent():
    for kind in ("ALLREDUCE", "REDUCESCATTER", "ALLGATHER", "ALLTOALL"):
        sched = collective_schedule(kind, 16, 1024)
        assert sched["message_count"] * sched["message_bytes"] \
            == sched["aggregate_payload"], (kind, sched)
        ref = ref_collective(kind, 16, 1024)
        for key in ("steps", "message_count", "message_bytes",
                    "per_rank_sent", "aggregate_payload"):
            assert sched[key] == ref[key], (kind, key)


def test_allgather_requires_divisible_payload():
    with pytest.raises(Exception):
        collective_schedule("ALLGATHER", 3, 1024)
