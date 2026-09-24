"""Independent closed-form oracles. NO veritx_dse imports.

These compute what a workload SHOULD produce from first principles, so
the corpus can check VERITX's *lowering* rather than only re-checking a
trace VERITX itself generated. The ring-ALLREDUCE model is textbook:

    steps    = 2 (k - 1)          reduce-scatter then all-gather
    messages = 2 k (k - 1)        one message per rank per step
    chunk    = B / k              bytes per message

Packetisation is then derived from the declared flit geometry (flit
width, header width, max packet flits), independently of VERITX.

PW2 extends the same discipline to the remaining pinned schedules. Every
law below is written from the ALGORITHM definition (who must learn what),
not from the implementation under test:

    ALLGATHER ring      every rank ends with all k chunks; each ring
                        edge carries k-1 messages, chunk = B/k
                        (k(k-1) messages of B/k -> aggregate (k-1)B)
    REDUCESCATTER ring  every rank ends owning one reduced chunk; each
                        ring edge carries k-1 messages, chunk = B/k
    ALLTOALL direct     every ordered pair (i, j), i != j, carries
                        exactly one message of B/k bytes; each rank
                        sends k-1 distinct chunks
    BROADCAST fanout    the declared root sends one B-byte message to
                        each of the k-1 other participants; nobody
                        else sends anything

Chunk-identity caveat (network-level semantics, see
PRODUCTION-CLAIMS.md C-16): these oracles validate the communication
SCHEDULE — who sends how many bytes to whom, in which step. They cannot
see which DATA VALUE a message carries; reduction-ownership semantics
are out of scope until a chunk-identity artifact exists.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

#: hardware parameter of the canonical compile path
#: (compiler/orchestration.py _MAX_PACKET_FLITS); declared, not imported.
DEFAULT_MAX_PACKET_FLITS = 8


@dataclass(frozen=True)
class RingAllReduceOracle:
    ranks: int
    payload_bytes: int
    flit_width_bits: int
    max_packet_flits: int

    messages: int
    total_bytes: int
    chunk_bytes: int
    header_bits: int
    usable_payload_bits: int
    flits_per_message: int
    packets_per_message: int
    total_flits: int
    total_packets: int

    def as_dict(self) -> dict:
        return {
            "ranks": self.ranks, "payload_bytes": self.payload_bytes,
            "messages": self.messages, "total_bytes": self.total_bytes,
            "chunk_bytes": self.chunk_bytes,
            "header_bits": self.header_bits,
            "usable_payload_bits": self.usable_payload_bits,
            "flits_per_message": self.flits_per_message,
            "packets_per_message": self.packets_per_message,
            "total_flits": self.total_flits,
            "total_packets": self.total_packets,
        }


def ring_allreduce_graph(ranks: int) -> dict[tuple[int, int], int]:
    """Expected directed-pair MULTISET of a ring ALLREDUCE.

    A ring reduce-scatter + all-gather moves data only between logical
    neighbours: rank i sends to rank (i+1) mod k. Each neighbour edge
    carries k-1 reduce-scatter messages and k-1 all-gather messages =
    2(k-1) messages. Every other pair carries ZERO.

    This is the check `ring_allreduce_oracle` cannot make: it validates
    counts, this validates the communication GRAPH.
    """
    if ranks < 2:
        raise ValueError(f"ring needs >= 2 ranks, got {ranks}")
    pairs: dict[tuple[int, int], int] = {}
    for i in range(ranks):
        pairs[(i, (i + 1) % ranks)] = 2 * (ranks - 1)
    return pairs


def collective_graph_report(kind: str, ranks: int, payload_bytes: int,
                            messages) -> dict:
    """The exact ring communication-graph law, as individual invariants.

    ``messages`` is any iterable of objects exposing ``step``, ``src_rank``,
    ``dst_rank`` and ``payload_bytes``. Every invariant is reported
    separately so a failure names exactly what broke.
    """
    from collections import Counter
    msgs = [(int(m.step), int(m.src_rank), int(m.dst_rank),
             int(m.payload_bytes)) for m in messages]
    steps = sorted({s for s, _, _, _ in msgs})
    n = len(msgs)
    if kind == "ALLREDUCE":
        expected_steps = 2 * (ranks - 1)
        chunk = payload_bytes // ranks
        expected_messages = 2 * ranks * (ranks - 1)
        expected_aggregate = 2 * (ranks - 1) * payload_bytes
        payload_ok_unit = chunk
    elif kind in ("REDUCESCATTER", "ALLGATHER"):
        expected_steps = ranks - 1
        # Ring law for BOTH: every message carries one B/k chunk; a full
        # ALLGATHER or REDUCESCATTER moves (k-1)B bytes in k(k-1) messages.
        # (The previous ALLGATHER branch used chunk = B, which is
        # inconsistent with its own aggregate (k-1)B.)
        chunk = payload_bytes // ranks
        expected_messages = ranks * (ranks - 1)
        expected_aggregate = (ranks - 1) * payload_bytes
        payload_ok_unit = chunk
    else:
        raise ValueError(f"no ring graph law for {kind!r}")

    per_step = Counter(s for s, _, _, _ in msgs)
    sends = {s: Counter() for s in steps}
    recvs = {s: Counter() for s in steps}
    for s, i, j, _ in msgs:
        sends[s][i] += 1
        recvs[s][j] += 1
    expected_rank_set = list(range(ranks))

    checks = {
        "steps_exact": steps == list(range(expected_steps)),
        "message_count_match": n == expected_messages,
        "every_step_has_k_messages": all(v == ranks
                                         for v in per_step.values()),
        "every_rank_sends_once_per_step": all(
            sorted(c) == expected_rank_set
            and all(v == 1 for v in c.values()) for c in sends.values()),
        "every_rank_receives_once_per_step": all(
            sorted(c) == expected_rank_set
            and all(v == 1 for v in c.values()) for c in recvs.values()),
        "dst_is_next_ring_neighbour": all(
            j == (i + 1) % ranks for _, i, j, _ in msgs),
        "no_self_messages": all(i != j for _, i, j, _ in msgs),
        "chunk_bytes_match": all(b == payload_ok_unit for _, _, _, b in msgs),
        "aggregate_bytes_match": sum(b for _, _, _, b in msgs)
        == expected_aggregate,
    }
    observed_pairs = Counter((i, j) for _, i, j, _ in msgs)
    expected_pairs = ring_allreduce_graph(ranks) if kind == "ALLREDUCE" else {
        (i, (i + 1) % ranks): 2 * (ranks - 1) for i in range(ranks)}
    if kind in ("REDUCESCATTER", "ALLGATHER"):
        expected_pairs = {(i, (i + 1) % ranks): ranks - 1
                          for i in range(ranks)}
    extra = {f"{i}->{j}": c for (i, j), c in observed_pairs.items()
             if (i, j) not in expected_pairs}
    checks["no_non_neighbour_pairs"] = not extra
    if kind == "ALLREDUCE":
        # exact phases, not just their sizes: reduce-scatter then all-gather
        rs = sorted(s for s in steps if s < ranks - 1)
        ag = sorted(s for s in steps if s >= ranks - 1)
        checks["phase_labels_exact"] = (
            rs == list(range(0, ranks - 1))
            and ag == list(range(ranks - 1, 2 * (ranks - 1))))

    problems = [name for name, ok in checks.items() if not ok]
    return {
        "kind": kind, "ranks": ranks, "payload_bytes": payload_bytes,
        "steps": expected_steps, "messages": expected_messages,
        "chunk_bytes": payload_ok_unit, "aggregate_bytes": expected_aggregate,
        "checks": checks, "conforms": not problems, "problems": problems,
        "extra_non_neighbour_pairs": extra,
        "observed_distinct_pairs": len(observed_pairs),
    }


def ring_allreduce_oracle(*, ranks: int, payload_bytes: int,
                          flit_width_bits: int,
                          max_packet_flits: int = DEFAULT_MAX_PACKET_FLITS
                          ) -> RingAllReduceOracle:
    """Textbook ring-ALLREDUCE message/byte/flit counts from (k, B)."""
    if ranks < 2:
        raise ValueError(f"ring allreduce needs >= 2 ranks, got {ranks}")
    if payload_bytes < 1:
        raise ValueError("payload_bytes must be positive")
    if payload_bytes % ranks != 0:
        raise ValueError(
            f"payload {payload_bytes} is not divisible by {ranks} ranks; "
            "the ring chunk model does not apply")
    # endpoint field widths scale with the rank count; header also carries
    # flit_type (2 bits) and vc_id (1 bit)
    endpoint_bits = max(1, (ranks - 1).bit_length())
    header_bits = 2 * endpoint_bits + 3
    usable_bits = flit_width_bits - header_bits
    if usable_bits <= 0:
        raise ValueError(
            f"flit width {flit_width_bits} cannot hold a {header_bits}-bit "
            "header")
    messages = 2 * ranks * (ranks - 1)
    chunk_bytes = payload_bytes // ranks
    chunk_bits = chunk_bytes * 8
    flits_per_message = max(1, math.ceil(chunk_bits / usable_bits))
    packets_per_message = max(1, math.ceil(flits_per_message
                                           / max_packet_flits))
    return RingAllReduceOracle(
        ranks=ranks, payload_bytes=payload_bytes,
        flit_width_bits=flit_width_bits, max_packet_flits=max_packet_flits,
        messages=messages, total_bytes=2 * (ranks - 1) * payload_bytes,
        chunk_bytes=chunk_bytes, header_bits=header_bits,
        usable_payload_bits=usable_bits, flits_per_message=flits_per_message,
        packets_per_message=packets_per_message,
        total_flits=messages * flits_per_message,
        total_packets=messages * packets_per_message)


# ── PW2: per-collective communication-graph laws ─────────────────────────

def collective_count_oracle(kind: str, ranks: int, payload_bytes: int,
                            flit_width_bits: int,
                            max_packet_flits: int = DEFAULT_MAX_PACKET_FLITS
                            ) -> RingAllReduceOracle:
    """Message/byte/flit/packet counts for the pinned schedule of `kind`.

    Same closed-form discipline as ring_allreduce_oracle: steps, message
    count and bytes from the algorithm definition, then packetisation from
    the declared flit geometry. Supported for every pinned kind.
    """
    if ranks < 2:
        raise ValueError(f"{kind} needs >= 2 ranks, got {ranks}")
    if payload_bytes < 1:
        raise ValueError("payload_bytes must be positive")
    if kind == "ALLGATHER":
        # F-0005: each of the k(k-1) ring messages carries one B/k chunk.
        if payload_bytes % ranks:
            raise ValueError(
                f"payload {payload_bytes} is not divisible by {ranks} "
                "ranks; the ring chunk model does not apply")
        messages = ranks * (ranks - 1)
        message_bytes = payload_bytes // ranks
        total_bytes = (ranks - 1) * payload_bytes
    elif kind == "REDUCESCATTER":
        if payload_bytes % ranks:
            raise ValueError(
                f"payload {payload_bytes} is not divisible by {ranks} "
                "ranks; the ring chunk model does not apply")
        messages = ranks * (ranks - 1)
        message_bytes = payload_bytes // ranks
        total_bytes = (ranks - 1) * payload_bytes
    elif kind == "ALLTOALL":
        if payload_bytes % ranks:
            raise ValueError(
                f"payload {payload_bytes} is not divisible by {ranks} "
                "ranks; the direct chunk model does not apply")
        messages = ranks * (ranks - 1)
        message_bytes = payload_bytes // ranks
        total_bytes = (ranks - 1) * payload_bytes
    elif kind == "BROADCAST":
        messages = ranks - 1
        message_bytes = payload_bytes
        total_bytes = (ranks - 1) * payload_bytes
    elif kind == "ALLREDUCE":
        return ring_allreduce_oracle(
            ranks=ranks, payload_bytes=payload_bytes,
            flit_width_bits=flit_width_bits,
            max_packet_flits=max_packet_flits)
    else:
        raise ValueError(f"no count oracle for {kind!r}")

    endpoint_bits = max(1, (ranks - 1).bit_length())
    header_bits = 2 * endpoint_bits + 3
    usable_bits = flit_width_bits - header_bits
    if usable_bits <= 0:
        raise ValueError(
            f"flit width {flit_width_bits} cannot hold a {header_bits}-bit "
            "header")
    chunk_bits = message_bytes * 8
    flits_per_message = max(1, math.ceil(chunk_bits / usable_bits))
    packets_per_message = max(1, math.ceil(flits_per_message
                                           / max_packet_flits))
    return RingAllReduceOracle(
        ranks=ranks, payload_bytes=payload_bytes,
        flit_width_bits=flit_width_bits, max_packet_flits=max_packet_flits,
        messages=messages, total_bytes=total_bytes,
        chunk_bytes=message_bytes, header_bits=header_bits,
        usable_payload_bits=usable_bits, flits_per_message=flits_per_message,
        packets_per_message=packets_per_message,
        total_flits=messages * flits_per_message,
        total_packets=messages * packets_per_message)


def direct_or_broadcast_graph_law(kind: str, ranks: int,
                                  payload_bytes: int, messages,
                                  source: int | None = None) -> dict:
    """Exact communication-graph laws for ALLTOALL and BROADCAST.

    ALLTOALL (direct): every ordered pair (i, j), i != j, carries exactly
    one message of B/k bytes; each rank sends exactly k-1 messages.

    BROADCAST (root fanout): only the declared root sends; it sends one
    B-byte message to each other participant; nobody else sends anything.

    Every invariant is reported individually so a failure names exactly
    what broke (F-0004 discipline).
    """
    from collections import Counter
    msgs = [(int(m.step), int(m.src_rank), int(m.dst_rank),
             int(m.payload_bytes)) for m in messages]
    n = len(msgs)
    checks: dict[str, bool] = {}

    if kind == "ALLTOALL":
        expected_count = ranks * (ranks - 1)
        chunk = payload_bytes // ranks
        checks["no_self_messages"] = all(i != j for _, i, j, _ in msgs)
        checks["message_count_match"] = n == expected_count
        observed_pairs = Counter((i, j) for _, i, j, _ in msgs)
        expected_pairs = {(i, j): 1 for i in range(ranks)
                          for j in range(ranks) if i != j}
        checks["pair_multiplicity_exact"] = observed_pairs == expected_pairs
        checks["chunk_bytes_match"] = all(b == chunk
                                          for _, _, _, b in msgs)
        checks["aggregate_bytes_match"] = (
            sum(b for _, _, _, b in msgs) == (ranks - 1) * payload_bytes)
        sends = Counter(i for _, i, _, _ in msgs)
        recvs = Counter(j for _, _, j, _ in msgs)
        checks["every_rank_sends_k_minus_1"] = all(
            sends.get(i, 0) == ranks - 1 for i in range(ranks))
        checks["every_rank_receives_k_minus_1"] = all(
            recvs.get(j, 0) == ranks - 1 for j in range(ranks))
        checks["steps_exact"] = all(s == 0 for s, _, _, _ in msgs)
    elif kind == "BROADCAST":
        if source is None:
            raise ValueError("BROADCAST law needs the declared source rank")
        if not 0 <= source < ranks:
            raise ValueError(f"source {source} is not a rank")
        expected_count = ranks - 1
        checks["message_count_match"] = n == expected_count
        checks["only_root_sends"] = all(i == source
                                        for _, i, _, _ in msgs)
        checks["root_sends_to_every_other_exactly_once"] = (
            Counter(j for _, _, j, _ in msgs)
            == {j: 1 for j in range(ranks) if j != source})
        checks["no_self_messages"] = all(i != j for _, i, j, _ in msgs)
        checks["chunk_bytes_match"] = all(b == payload_bytes
                                          for _, _, _, b in msgs)
        checks["aggregate_bytes_match"] = (
            sum(b for _, _, _, b in msgs)
            == (ranks - 1) * payload_bytes)
        checks["steps_exact"] = all(s == 0 for s, _, _, _ in msgs)
    else:
        raise ValueError(f"no direct/broadcast law for {kind!r}")

    problems = [name for name, ok in checks.items() if not ok]
    return {
        "kind": kind, "ranks": ranks, "payload_bytes": payload_bytes,
        "source": source, "messages": len(msgs),
        "checks": checks, "conforms": not problems, "problems": problems,
    }
