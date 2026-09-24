"""Independent closed-form oracles. NO veritx_dse imports.

These compute what a workload SHOULD produce from first principles, so
the corpus can check VERITX's *lowering* rather than only re-checking a
trace VERITX itself generated. The ring-ALLREDUCE model is textbook:

    steps    = 2 (k - 1)          reduce-scatter then all-gather
    messages = 2 k (k - 1)        one message per rank per step
    chunk    = B / k              bytes per message

Packetisation is then derived from the declared flit geometry (flit
width, header width, max packet flits), independently of VERITX.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

#: hardware parameter of the canonical compile path
#: (application/compile.py _MAX_PACKET_FLITS); declared, not imported.
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


def graph_conformance(ranks: int, observed: dict[tuple[int, int], int]
                      ) -> dict:
    """Compare an observed directed-pair multiset to the ring graph."""
    expected = ring_allreduce_graph(ranks)

    def _key(pair: tuple[int, int]) -> str:
        return f"{pair[0]}->{pair[1]}"

    extra = {_key(p): c for p, c in observed.items() if p not in expected}
    missing = {_key(p): c for p, c in expected.items() if p not in observed}
    wrong_count = {_key(p): [observed[p], expected[p]] for p in expected
                   if p in observed and observed[p] != expected[p]}
    return {
        "ring_pairs": {_key(p): c for p, c in sorted(expected.items())},
        "extra_non_neighbour_pairs": extra,
        "missing_neighbour_pairs": missing,
        "wrong_multiplicity": wrong_count,
        "conforms": not (extra or missing or wrong_count),
        "observed_distinct_pairs": len(observed),
        "ring_distinct_pairs": len(expected),
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
