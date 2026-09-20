"""veritx_dse.waved.oracles — independent pure reference models (§26, §68).

These oracles are structurally independent of the production lowering:
they never import or call it. They exist so Wave-D tests can prove the
production implementations with ``production(x) == oracle(x)`` instead of
the forbidden ``production(x) == production(x)``.

Simplicity is a requirement (§68): each oracle is the closed-form
equation itself, not a second simulator.
"""
from __future__ import annotations

from typing import Iterator


# ── rank space (§7) ──────────────────────────────────────────────────────

def ref_rank(t: int, p: int, e: int, d: int, *, tp: int, pp: int,
             ep: int, dp: int) -> int:
    """Closed-form rank: tp fastest, then ep, then dp, then pp slowest."""
    return ((p * dp + d) * ep + e) * tp + t


def ref_coords(r: int, *, tp: int, pp: int, ep: int, dp: int
               ) -> tuple[int, int, int, int]:
    """Closed-form inverse of ref_rank → (t, p, e, d)."""
    t = r % tp
    rest = r // tp
    e = rest % ep
    rest //= ep
    d = rest % dp
    p = rest // dp
    return t, p, e, d


# ── communication groups (§9) ────────────────────────────────────────────

def ref_group_members(family: str, sizes: tuple[int, int, int, int],
                      coords: tuple[int, int, int, int]) -> tuple[int, ...]:
    """Members of the family group containing ``coords``.

    family: "TP" varies t; "EP" varies e; "DP" varies d; "PP" is the
    stage (fixed p, all t/e/d). Returns ranks in canonical order.
    """
    tp, pp, ep, dp = sizes
    t, p, e, d = coords
    if family == "TP":
        return tuple(ref_rank(i, p, e, d, tp=tp, pp=pp, ep=ep, dp=dp)
                     for i in range(tp))
    if family == "EP":
        return tuple(ref_rank(t, p, i, d, tp=tp, pp=pp, ep=ep, dp=dp)
                     for i in range(ep))
    if family == "DP":
        return tuple(ref_rank(t, p, e, i, tp=tp, pp=pp, ep=ep, dp=dp)
                     for i in range(dp))
    if family == "PP":
        return tuple(ref_rank(i, p, j, k, tp=tp, pp=pp, ep=ep, dp=dp)
                     for i in range(tp) for j in range(ep)
                     for k in range(dp))
    raise ValueError(f"unknown family {family!r}")


# ── collectives (§10.1) ──────────────────────────────────────────────────

def ref_collective(kind: str, k: int, B: int) -> dict[str, int]:
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
            raise ValueError("ALLREDUCE requires B % k == 0")
        C = B // k
        return {"steps": 2 * (k - 1), "message_count": 2 * k * (k - 1),
                "message_bytes": C, "per_rank_sent": 2 * (k - 1) * C,
                "aggregate_payload": 2 * (k - 1) * B}
    if kind == "REDUCESCATTER":
        if B % k:
            raise ValueError("REDUCESCATTER requires B % k == 0")
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
            raise ValueError("ALLTOALL requires B % k == 0")
        C = B // k
        return {"steps": 1, "message_count": k * (k - 1),
                "message_bytes": C, "per_rank_sent": (k - 1) * C,
                "aggregate_payload": (k - 1) * B}
    if kind == "BROADCAST":
        return {"steps": 1, "message_count": k - 1, "message_bytes": B,
                "per_rank_sent": (k - 1) * B,
                "aggregate_payload": (k - 1) * B}
    raise ValueError(f"unsupported collective kind {kind!r}")


def ref_collective_messages(kind: str, k: int, B: int
                            ) -> list[tuple[int, int, int]]:
    """Exact (step, src, dst) message triples per pinned schedule.

    Participant indices are 0..k-1 within the collective's participant
    tuple (canonical order = ring order). Each ring step is a full
    permutation cycle (every participant sends and receives exactly one
    message of the step's size); the chunk CONTENT index is not part of
    the message-level accounting (all messages of a step carry the same
    byte count), matching the §10.1 contract which pins counts and
    bytes, not per-message chunk ownership.
    """
    if k < 2:
        raise ValueError("a collective needs k >= 2")
    if kind == "ALLREDUCE":
        if B % k:
            raise ValueError("ALLREDUCE requires B % k == 0")
        out: list[tuple[int, int, int]] = []
        for step in range(2 * (k - 1)):
            off = step % (k - 1) + 1
            for i in range(k):
                out.append((step, i, (i + off) % k))
        return out
    if kind == "REDUCESCATTER":
        if B % k:
            raise ValueError("REDUCESCATTER requires B % k == 0")
        return [(step, i, (i + step + 1) % k)
                for step in range(k - 1) for i in range(k)]
    if kind == "ALLGATHER":
        return [(step, i, (i + step + 1) % k)
                for step in range(k - 1) for i in range(k)]
    if kind == "ALLTOALL":
        if B % k:
            raise ValueError("ALLTOALL requires B % k == 0")
        return [(0, i, j) for i in range(k) for j in range(k) if i != j]
    if kind == "BROADCAST":
        return [(0, 0, j) for j in range(1, k)]
    raise ValueError(f"unsupported collective kind {kind!r}")


def ref_multicast(payload_bytes: int, n_destinations: int
                  ) -> dict[str, int]:
    """SOURCE_REPLICATION accounting (§17)."""
    if payload_bytes <= 0:
        raise ValueError("payload must be a positive integer")
    if n_destinations < 1:
        raise ValueError("multicast needs at least one destination")
    return {"source_payload": payload_bytes,
            "message_count": n_destinations,
            "message_bytes": payload_bytes,
            "aggregate_payload": payload_bytes * n_destinations,
            "delivered_payload": payload_bytes * n_destinations}


# ── packetization / flitization (§18) ────────────────────────────────────

def ref_packetize(message_bits: int, q: int, l_flits: int) -> list[int]:
    """Packet payload bits per packet: conserved split of ``message_bits``."""
    if message_bits < 0:
        raise ValueError("message_bits must be >= 0")
    if q < 1 or l_flits < 1:
        raise ValueError("capacity must be positive")
    capacity = q * l_flits
    if message_bits == 0:
        return []
    full, tail = divmod(message_bits, capacity)
    packets = [capacity] * full
    if tail:
        packets.append(tail)
    return packets


def ref_flitize(p_i: int, q: int, h: int, f: int
                ) -> tuple[int, int, int]:
    """(flit_count, padding_bits, transmitted_bits) for one packet."""
    if p_i <= 0:
        raise ValueError("packet payload must be positive")
    if q < 1 or h < 0 or f != q + h:
        raise ValueError("widths must satisfy F = payload + header")
    n = (p_i + q - 1) // q
    padding = n * q - p_i
    return n, padding, n * f


__all__ = [
    "ref_collective", "ref_collective_messages", "ref_coords",
    "ref_flitize", "ref_group_members", "ref_multicast", "ref_packetize",
    "ref_rank",
]
