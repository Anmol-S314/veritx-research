"""The closed evaluation-question vocabulary.

A question enters this vocabulary only when a REGISTERED backend can
answer it with authentic evidence — the enum is capability truth, not
aspirational documentation. Extend with DRAM_TIMING, CXL_TRANSACTION_
TIMING, SERVING_TTFT/SERVING_TPOT, SCALE_OUT_CONGESTION, RTL_BEHAVIOR,
PPA_ESTIMATE only when the matching adapter exists.
"""
from __future__ import annotations

from enum import Enum


class EvaluationQuestion(Enum):
    """WHAT is being asked of the federation, semantics first.

    Backend choice belongs to the planner (Federation 07), never to the
    question: asking NETWORK_COMPLETION does not name a simulator.
    """

    NETWORK_COMPLETION = "NETWORK_COMPLETION"
    SYSTEM_MAKESPAN = "SYSTEM_MAKESPAN"
    COMMUNICATION_EXPOSURE = "COMMUNICATION_EXPOSURE"
    PER_RANK_COMPLETION = "PER_RANK_COMPLETION"


__all__ = ["EvaluationQuestion"]
