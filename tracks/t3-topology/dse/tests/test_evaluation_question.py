"""Federation Commit 04 — the question vocabulary is closed capability
truth: only questions a registered backend can answer today."""
from __future__ import annotations

import sys
from pathlib import Path

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.evaluation_question import EvaluationQuestion


def test_evaluation_questions_are_exactly_the_answerable_set():
    assert {q.value for q in EvaluationQuestion} == {
        "NETWORK_COMPLETION", "SYSTEM_MAKESPAN",
        "COMMUNICATION_EXPOSURE", "PER_RANK_COMPLETION",
        "DRAM_TIMING", "SERVING_TTFT", "SERVING_COMPLETION",
    }
