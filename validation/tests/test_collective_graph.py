"""F-0004 regression: the old offset exchange must fail the ring law.

Reproduces the pre-fix schedule independently (NOT by importing the
production function) and asserts the graph oracle detects exactly the
non-neighbour pairs, then asserts the fixed production lowering conforms.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _ROOT / "tracks" / "t3-topology" / "dse"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from validation.harness.fabric import build  # noqa: E402
from validation.harness.oracle import collective_graph_report  # noqa: E402
from validation.harness.spec import ExperimentSpec  # noqa: E402


@dataclass(frozen=True)
class _Msg:
    step: int
    src_rank: int
    dst_rank: int
    payload_bytes: int


def _old_offset_exchange(k: int) -> list[_Msg]:
    """The F-0004 schedule: offset = step % (k-1) + 1 (all pairs)."""
    chunk = 1
    return [_Msg(step=s, src_rank=i, dst_rank=(i + s % (k - 1) + 1) % k,
                 payload_bytes=chunk)
            for s in range(2 * (k - 1)) for i in range(k)]


def test_old_offset_exchange_is_not_a_ring():
    for k in (4, 16):
        report = collective_graph_report("ALLREDUCE", k, k,
                                         _old_offset_exchange(k))
        assert not report["conforms"]
        # distinct offset pairs = k(k-1); ring neighbour pairs = k
        expected_extra = k * (k - 1) - k
        assert len(report["extra_non_neighbour_pairs"]) == expected_extra, (
            k, report["extra_non_neighbour_pairs"])
        assert report["checks"]["no_non_neighbour_pairs"] is False
        assert report["checks"]["dst_is_next_ring_neighbour"] is False


def test_fixed_production_lowering_conforms():
    root = _ROOT / "validation" / "experiments"
    for name in ("V09-rtl-allreduce-2x2.json",
                 "V02-allreduce-4x4.json"):
        spec = ExperimentSpec.load(root / name)
        built = build(spec)
        report = collective_graph_report(
            "ALLREDUCE", spec.fabric.compute_tiles,
            spec.workload.payload_bytes, built.logical.messages)
        assert report["conforms"], (name, report["problems"],
                                    report["extra_non_neighbour_pairs"])
        assert report["checks"]["dst_is_next_ring_neighbour"]
        assert report["checks"]["every_rank_sends_once_per_step"]
        assert report["checks"]["every_rank_receives_once_per_step"]
        assert report["checks"]["steps_exact"]
        assert report["checks"]["phase_labels_exact"]
        assert report["checks"]["no_non_neighbour_pairs"]
