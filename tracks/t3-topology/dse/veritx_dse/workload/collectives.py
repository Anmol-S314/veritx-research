"""veritx_dse.workload.collectives — PRODUCTION collective algorithm spec.

Rationale: docs/decisions/modules/workload.md
"""
from __future__ import annotations

from veritx_dse.core.errors import UnsupportedSchedule

PADDED_HEADER_BYTES = 0  # reserved: payload accounting lives in the spec

COLLECTIVE_KINDS = ("ALLREDUCE", "REDUCESCATTER", "ALLGATHER", "ALLTOALL",
                    "BROADCAST")
SCHEDULES = {
    "ALLREDUCE": "RING",
    "REDUCESCATTER": "RING",
    "ALLGATHER": "RING",
    "ALLTOALL": "DIRECT",
    "BROADCAST": "ROOT_FANOUT",
}


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
        if B % k:
            raise UnsupportedSchedule(
            "ALLGATHER requires B % k == 0")
        C = B // k
        return {"steps": k - 1, "message_count": k * (k - 1),
                "message_bytes": C, "per_rank_sent": (k - 1) * C,
                "aggregate_payload": (k - 1) * B}
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


__all__ = ["COLLECTIVE_KINDS", "SCHEDULES", "collective_schedule"]
