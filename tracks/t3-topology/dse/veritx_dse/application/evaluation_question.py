"""The closed evaluation-question vocabulary.

Rationale: docs/decisions/modules/application.md
"""
from __future__ import annotations

from enum import Enum


class EvaluationQuestion(Enum):
    """WHAT is being asked of the federation, semantics first.

Rationale: docs/decisions/modules/application.md
    """

    NETWORK_COMPLETION = "NETWORK_COMPLETION"
    SYSTEM_MAKESPAN = "SYSTEM_MAKESPAN"
    COMMUNICATION_EXPOSURE = "COMMUNICATION_EXPOSURE"
    PER_RANK_COMPLETION = "PER_RANK_COMPLETION"
    DRAM_TIMING = "DRAM_TIMING"
    SERVING_TTFT = "SERVING_TTFT"
    SERVING_COMPLETION = "SERVING_COMPLETION"


__all__ = ["EvaluationQuestion"]
