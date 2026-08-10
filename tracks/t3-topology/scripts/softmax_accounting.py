"""Analytical softmax DRAM byte accounting.

plan.md Section 7 open decision: analytical add-on (this) vs. a dedicated
Timeloop problem template. v1 uses the analytical route -- softmax isn't a
GEMM and has no real mapper search space, so running Timeloop for it would
just add a 7th op template for no benefit.
"""


def softmax_dram_bytes(score_tensor_bytes: int) -> int:
    """Softmax reads the score tensor and writes a probability tensor of
    the same size: total DRAM traffic = 2 x score_tensor_bytes."""
    return 2 * score_tensor_bytes