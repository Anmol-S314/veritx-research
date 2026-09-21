"""veritx_dse.workload.collectives — PRODUCTION collective algorithm spec.

This is the workload-owned definition of the pinned collective algorithms:
step counts, message counts and byte accounting. It is a SPECIFICATION, not
a reference implementation — ``workload/messages.py`` uses it to expand
collectives into logical messages, so it is the production authority for
"how many steps does ring allreduce take".

Independence note: ``verification/reference_semantics.py`` carries its own
``ref_collective`` equations on purpose. Production must never import the
reference module, and the reference must never import this one — otherwise
the differential test becomes "the spec agrees with itself", which is
exactly the defect found in the Wave-D group-law oracle (see
docs/ARCHITECTURE-CONSOLIDATION.md, F1).
"""
from __future__ import annotations

from veritx_dse.core.errors import UnsupportedSchedule

PADDED_HEADER_BYTES = 0  # reserved: payload accounting lives in the spec


def collective_schedule(kind: str, k: int, B: int) -> dict[str, int]:
    """The §10.1 exact schedule table as pure arithmetic.

    Returns steps, message_count, message_bytes, per_rank_sent,
    aggregate_payload. Divisibility refusals mirror the production law.
    """
    if k < 2:
        raise ValueError("a collective needs k >= 2")
    if B <= 0:
        raise ValueError("payload must be a positive integer")
    if kind == "ALLREDUCE":
        if B % k:
            raise UnsupportedSchedule(
            "ALLREDUCE requires B % k == 0")
        C = B // k
        return {"steps": 2 * (k - 1), "message_count": 2 * k * (k - 1),
                "message_bytes": C, "per_rank_sent": 2 * (k - 1) * C,
                "aggregate_payload": 2 * (k - 1) * B}
    if kind == "REDUCESCATTER":
        if B % k:
            raise UnsupportedSchedule(
            "REDUCESCATTER requires B % k == 0")
        C = B // k
        return {"steps": k - 1, "message_count": k * (k - 1),
                "message_bytes": C, "per_rank_sent": (k - 1) * C,
                "aggregate_payload": (k - 1) * B}
    if kind == "ALLGATHER":
        return {"steps": k - 1, "message_count": k * (k - 1),
                "message_bytes": B, "per_rank_sent": (k - 1) * B,
                "aggregate_payload": k * (k - 1) * B}
    if kind == "ALLTOALL":
        if B % k:
            raise UnsupportedSchedule(
            "ALLTOALL requires B % k == 0")
        C = B // k
        return {"steps": 1, "message_count": k * (k - 1),
                "message_bytes": C, "per_rank_sent": (k - 1) * C,
                "aggregate_payload": (k - 1) * B}
    if kind == "BROADCAST":
        return {"steps": 1, "message_count": k - 1, "message_bytes": B,
                "per_rank_sent": (k - 1) * B,
                "aggregate_payload": (k - 1) * B}
    raise ValueError(f"unsupported collective kind {kind!r}")


__all__ = ["collective_schedule"]
