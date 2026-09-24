"""veritx_dse.verification.reference_semantics — independent pure reference models (§26).

These oracles are structurally independent of the production lowering:
they never import or call it. They exist so Wave-D tests can prove the
production implementations with ``production(x) == oracle(x)`` instead of
the forbidden ``production(x) == production(x)``.

Simplicity is a requirement (§26): each oracle is the closed-form
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
        # F-0005: re-derived ring law — each rank owns a B/k chunk, so each
        # of the k(k-1) ring messages carries B/k, aggregate (k-1)B.
        if B % k:
            raise ValueError("ALLGATHER requires B % k == 0")
        C = B // k
        return {"steps": k - 1, "message_count": k * (k - 1),
                "message_bytes": C, "per_rank_sent": (k - 1) * C,
                "aggregate_payload": (k - 1) * B}
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
    tuple (canonical order = ring order).

    Ring law, implemented from first principles (NOT copied from the
    production spec): in a ring collective data moves ONLY between logical
    neighbours — every step, rank i sends one chunk to rank (i+1) mod k.
    The CHUNK ownership rotates around the ring; the network edge does not.
    The message-level accounting abstracts chunk identity away (all
    messages of a step carry the same byte count), matching the §10.1
    contract which pins counts and bytes, not per-message chunk ownership.

    ALLREDUCE has two logical phases over the same edge set:
      steps [0, k-2]       reduce-scatter
      steps [k-1, 2k-3]    all-gather
    """
    if k < 2:
        raise ValueError("a collective needs k >= 2")

    def _ring(steps: int, base: int) -> list[tuple[int, int, int]]:
        return [(base + step, i, (i + 1) % k)
                for step in range(steps) for i in range(k)]

    if kind == "ALLREDUCE":
        if B % k:
            raise ValueError("ALLREDUCE requires B % k == 0")
        return _ring(k - 1, 0) + _ring(k - 1, k - 1)
    if kind == "REDUCESCATTER":
        if B % k:
            raise ValueError("REDUCESCATTER requires B % k == 0")
        return _ring(k - 1, 0)
    if kind == "ALLGATHER":
        return _ring(k - 1, 0)
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


# ── verifiers moved out of the artifacts (slice 2b) ─────────────────────
# An artifact must not carry its own differential check: the check would
# then live inside the thing it checks, and the artifact would depend on
# the reference module. These functions are the verifier side of that
# seam. Callers: the verified loaders, the service, the projection gates.

def verify_parallelism_reference(artifact) -> None:
    """Rank-bijection differential for a ParallelismArtifact.

    Compares the production coordinates (model.placement) against this
    module's closed-form inverse. Genuine differential: two independent
    implementations of the same bijection.
    """
    from veritx_dse.core.errors import ConservationFailed
    sizes = artifact.sizes()
    tp, pp, ep, dp = sizes
    for r in range(artifact.world_size):
        c = artifact.coords_of(r)
        got = artifact.rank_of(c["tp"], c["pp"], c["ep"], c["dp"])
        if got != r:
            raise ConservationFailed(
                f"rank bijection broken at {r}: got {got}")
        if ref_coords(r, tp=tp, pp=pp, ep=ep, dp=dp) != \
                (c["tp"], c["pp"], c["ep"], c["dp"]):
            raise ConservationFailed(
                f"coords disagree with the independent reference at "
                f"rank {r}")


def verify_packetization_reference(traffic) -> None:
    """Packetization/flitization differential for physical traffic.

    The production packetizer is an independent implementation; this
    re-derives both laws from the closed forms and compares.
    """
    from veritx_dse.core.errors import ConservationFailed
    from veritx_dse.workload.traffic import header_width_bits, payload_width_bits
    pf = getattr(traffic, "packet_format", None)
    if pf is None:  # historical v1 traffic nests children under .bundle
        pf = traffic.bundle.packet_format
    Q, L = payload_width_bits(pf), pf.max_packet_flits
    H = header_width_bits(pf)
    for m in traffic.logical.messages:
        expected_pkts = ref_packetize(m.payload_bytes * 8, Q, L)
        got = next(t for t in traffic._traffic
                   if t.message_id == m.message_id)
        if [p.payload_bits for p in got.packets] != expected_pkts:
            raise ConservationFailed(
                f"packetization reference mismatch for {m.message_id!r}")
        for p in got.packets:
            n, padding, transmitted = ref_flitize(
                p.payload_bits, Q, H, pf.flit_width_bits)
            if (n, padding, transmitted) != (
                    p.flit_count, p.padding_bits, p.transmitted_bits):
                raise ConservationFailed(
                    f"flitization reference mismatch for packet "
                    f"{p.packet_index} of {m.message_id!r}")


def verify_logical_messages_reference(messages) -> None:
    """Differential of generated logical messages vs the reference law.

    Distinct from ``validate_conservation``: that one proves generated
    == declared schedule (an intrinsic invariant), this one compares
    against an independent implementation of the law.

    Generation-aware: v1 iterates the OperationGraph side lists; v2
    iterates the schedule records the canonical lowering selected.
    """
    from veritx_dse.core.errors import ConservationFailed
    if hasattr(messages, "schedules") and not hasattr(
            getattr(messages, "graph", None), "collectives"):
        for rec in messages.schedules:
            ref = ref_collective(rec.kind, rec.k, rec.payload_bytes)
            mine = [m for m in messages.messages
                    if m.operation_id == rec.collective_id]
            sent = sum(m.payload_bytes for m in mine)
            if sent != ref["aggregate_payload"]:
                raise ConservationFailed(
                    f"collective {rec.collective_id!r}: generated {sent} "
                    f"payload bytes, reference requires "
                    f"{ref['aggregate_payload']}")
            if len(mine) != ref["message_count"]:
                raise ConservationFailed(
                    f"collective {rec.collective_id!r}: generated "
                    f"{len(mine)} messages, reference law requires "
                    f"{ref['message_count']}")
        return
    op_ids = messages._collective_op_ids()
    for ci in messages.graph.collectives:
        ref = ref_collective(ci.kind, ci.k, ci.payload_bytes)
        mine = [m for m in messages.messages
                if m.operation_id in op_ids[ci.collective_id]]
        sent = sum(m.payload_bytes for m in mine)
        if sent != ref["aggregate_payload"]:
            raise ConservationFailed(
                f"collective {ci.collective_id!r}: generated {sent} "
                f"payload bytes, reference requires "
                f"{ref['aggregate_payload']}")
        # NB: message COUNT is confirmatory here — the production spec and
        # this reference are two implementations of the same pinned
        # equation, and expansion reads the spec. The BYTE total below is
        # the differential: production sums generated messages, this
        # reference computes the law independently.
        if len(mine) != ref["message_count"]:
            raise ConservationFailed(
                f"collective {ci.collective_id!r}: generated "
                f"{len(mine)} messages, reference law requires "
                f"{ref['message_count']}")


__all__ = __all__ + [
    "verify_logical_messages_reference", "verify_packetization_reference",
    "verify_parallelism_reference",
]
