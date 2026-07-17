#!/usr/bin/env python3
"""Gate 1 (latency regime): does inter-chip TOPOLOGY SHAPE move decode token latency?

Companion to interchip_roofline.py. That script killed the BANDWIDTH thesis (multicast
vs broadcast = noise, because decode is weight-DRAM-bound, not fabric-bound). This one
asks the only regime left with a pulse: LATENCY.

In tensor-parallel (TP) decode, every layer does ~2 all-reduces across the TP group, on
the CRITICAL PATH, every token. The messages are TINY (batch x hidden), so bandwidth is
irrelevant — what matters is the all-reduce's LATENCY term:

    collective_latency ~= (collective steps) x (hops/step) x (per-hop latency)

and that term is set by TOPOLOGY SHAPE:
  - RING all-reduce:     2(N-1) sequential hops         -> grows LINEARLY in N (awful at scale)
  - SWITCH / tree:       2*log2(N) steps, ~1 hop each   -> grows LOG in N (fat-tree / NVSwitch)
  - FULL MESH (direct):  1 hop, every pair direct       -> flat (small N only; radix-limited)

Unlike bandwidth, this is NOT batch-amortizable into nothing: the latency term is fixed
per FORWARD PASS (independent of message size), and the weight-DRAM wall is ALSO per
forward — so their RATIO is batch-independent. If collective latency is a real fraction
of the wall, topology is first-order for latency-SLO serving. This script measures it.

    python3 scripts/tp_latency_roofline.py [--selfcheck]

Roofline, not simulation. The verdict is read from the gaps, not asserted.
"""
import sys
from math import log2, ceil

# --- Model: Llama-3-70B (matches the rest of T3) ------------------------------
L, H, N_KV, D_HEAD, PARAMS = 80, 8192, 8, 128, 70e9
DTYPE_B = 2
ALLREDUCE_PER_LAYER = 2                     # Megatron TP: after attn out-proj + after MLP

# --- Deployment: per-chip DRAM BW held ~constant as we scale the TP group ------
DRAM_GBS_PER_CHIP = 576.0                   # 4608 GB/s / 8 chips (QuietBox n300d)
HOP_LAT_US = 2.0                            # inter-chip store-and-forward latency / hop


def weight_time_per_forward(n_chips, dtype_b=DTYPE_B):
    """Weights read once per forward, sharded across the TP group (batch-independent)."""
    agg_gbs = DRAM_GBS_PER_CHIP * n_chips
    return (PARAMS * dtype_b) / (agg_gbs * 1e9)


def collective_hops(topology, n_chips):
    """Total per-hop latencies charged by ONE all-reduce over n_chips."""
    if topology == "ring":
        return 2 * (n_chips - 1)             # bandwidth-optimal ring: 2(N-1) sequential steps
    if topology == "switch":                # fat-tree / NVSwitch: recursive halving-doubling
        return 2 * ceil(log2(n_chips))      # 2*log2(N) steps, ~1 switch-hop each
    if topology == "mesh":                  # full direct mesh: every pair 1 hop (radix-limited)
        return 2                            # send + receive, no store-and-forward
    raise ValueError(topology)


def collective_latency_per_forward(topology, n_chips, hop_us=HOP_LAT_US):
    """All-reduce latency summed over the whole forward pass (seconds)."""
    hops = collective_hops(topology, n_chips)
    return L * ALLREDUCE_PER_LAYER * hops * (hop_us * 1e-6)


def forward_latency(topology, n_chips, hop_us=HOP_LAT_US):
    """Small-batch decode: weight wall + serial collective barriers (seconds)."""
    return weight_time_per_forward(n_chips) + collective_latency_per_forward(topology, n_chips, hop_us)


def collective_share(topology, n_chips, hop_us=HOP_LAT_US):
    """Fraction of forward latency spent waiting on the fabric (batch-independent)."""
    c = collective_latency_per_forward(topology, n_chips, hop_us)
    return c / (weight_time_per_forward(n_chips) + c)


def _selfcheck():
    # (1) Unlike multicast's 0.001%, the collective is a REAL fraction of the wall even
    #     at the modest N=8 box scale on a plain ring -> latency is NOT second-order.
    s8 = collective_share("ring", 8)
    assert s8 > 0.05, f"expected a non-trivial collective share at N=8 ring, got {s8:.3f}"

    # (2) TOPOLOGY genuinely moves it: switch/mesh cut the ring's collective materially.
    for N in (8, 16, 32):
        assert collective_latency_per_forward("switch", N) < collective_latency_per_forward("ring", N)
        assert collective_latency_per_forward("mesh", N) <= collective_latency_per_forward("switch", N)

    # (3) The catch that kills the PAPER: ring degrades LINEARLY in N (network-bound at
    #     scale), but a switch degrades only LOG in N -> at N=32 the ring is network-bound
    #     while the switch is not. That gap IS the known engineering answer (why NVSwitch/
    #     fat-tree exist), not an open question.
    assert collective_share("ring", 32) > 0.5, "ring should be network-bound at N=32"
    assert collective_share("switch", 32) < 0.3, "switch should rescue it at N=32"

    # (4) batch-independence of the ratio: both terms are per-forward, so nothing here is
    #     an artifact of a chosen batch size (the effect is real OR absent, not amortizable).
    print("selfcheck OK — collective latency is a REAL fraction of the decode wall "
          "(unlike bandwidth/multicast); topology moves it a lot; ring is network-bound "
          "at scale while a switch is not. The effect is first-order — but it is the "
          "textbook reason NVSwitch/fat-tree exist, i.e. an ANSWERED question.")


def main():
    ms = 1e3
    print(f"\n  TP-decode LATENCY roofline — Llama-3-70B, per-chip DRAM {DRAM_GBS_PER_CHIP:.0f} GB/s, "
          f"hop {HOP_LAT_US:.0f} us\n")

    print(f"  (A) collective latency's share of decode forward latency (batch-independent):")
    print(f"      {'N':>4} {'wall ms':>8} {'ring ms':>9} {'switch ms':>10} {'mesh ms':>9} "
          f"{'ring %':>7} {'switch %':>8}")
    for N in (2, 4, 8, 16, 32, 64):
        wall = weight_time_per_forward(N) * ms
        r = collective_latency_per_forward("ring", N) * ms
        s = collective_latency_per_forward("switch", N) * ms
        m = collective_latency_per_forward("mesh", N) * ms
        print(f"      {N:>4} {wall:>8.2f} {r:>9.2f} {s:>10.2f} {m:>9.2f} "
              f"{collective_share('ring',N)*100:>6.1f}% {collective_share('switch',N)*100:>7.1f}%")
    print(f"      => on a RING the fabric goes network-bound as N grows (linear in N);")
    print(f"         a SWITCH/tree keeps it log(N) -> topology shape is FIRST-ORDER here.\n")

    print(f"  (B) sweep per-hop latency (the number we're least sure of), N=8 ring:")
    print(f"      {'hop us':>7} {'collective ms':>14} {'share':>7}")
    for h in (0.5, 1.0, 2.0, 5.0):
        c = collective_latency_per_forward("ring", 8, hop_us=h) * ms
        print(f"      {h:>7.1f} {c:>14.2f} {collective_share('ring',8,hop_us=h)*100:>6.1f}%")
    print(f"      => even at a sub-us NVLink-class hop, the collective is a real few-%; at")
    print(f"         a 2-5us commodity hop it's 10-30% -> genuinely worth a topology, at N=8.\n")

    print(f"  VERDICT (Gate 1, latency regime): the network is a REAL first-order term here")
    print(f"  (10-70% of forward latency depending on N and hop) — UNLIKE bandwidth/multicast,")
    print(f"  which was 0.001%. So topology genuinely matters for latency-SLO TP decode.")
    print(f"  BUT the answer is already KNOWN and baked into silicon: ring degrades linearly,")
    print(f"  a switch/fat-tree/full-mesh degrades log(N) and wins — which is exactly WHY")
    print(f"  NVSwitch and fat-tree exist, and why nobody runs TP across a slow ring at scale")
    print(f"  (they cap TP at the switch domain and go pipeline-parallel beyond). A reviewer")
    print(f"  writes 'yes, that's what NVSwitch is for.' Real effect, SOLVED problem -> still")
    print(f"  no open paper. The honest T3 story is unchanged across all three rungs.\n")


if __name__ == "__main__":
    _selfcheck() if "--selfcheck" in sys.argv else main()
