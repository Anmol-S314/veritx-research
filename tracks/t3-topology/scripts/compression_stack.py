#!/usr/bin/env python3
"""Does lossless KV compression (TurboQuant-class) eat the multicast gain? (T3)

The 2026 competitor to K/V multicast is lossless KV COMPRESSION: TurboQuant (Google,
ICLR 2026) packs the KV cache to 3 bits with zero measured accuracy loss (~5.3x from
BF16, they headline 6x); VeriCache gets 4x at identical outputs. Both shrink the exact
thing multicast operates on. So: if compression is standard, is multicast still worth
anything?

Compression factor c changes TWO things, and they pull opposite ways:
  (1) it shrinks KV READ traffic per sequence by c   -> less for multicast to save
  (2) it shrinks KV STORAGE by c, so c-fold MORE sequences fit -> bigger batch

The answer depends on the serving regime, and the split is the whole point:

  THROUGHPUT serving (batch grows to fill memory -- the datacenter default):
    At the capacity-limited batch, memory is full: W + B*K_c = capacity. Then
      multicast speedup = (W + g*(cap - W)) / cap
    which has NO c in it. Compression cancels: it lets you fit c-fold more sequences,
    and the multicast gain per the same full memory is identical. Compression and
    multicast STACK -- compression multiplies batch/throughput ~c, multicast multiplies
    on top by a c-INVARIANT factor.

  LATENCY serving (batch fixed small by an SLA):
    Weights dominate and compression makes KV negligible, so multicast erodes toward
    1x. Here compression DOES eat it -- unless context is long enough that KV still
    dominates even compressed.

    python3 scripts/compression_stack.py [--selfcheck]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from serving_multicast import Model, Box, QUIETBOX, MODELS, GB  # reuse, don't duplicate


def kv_read(m, seq, multicast, c):
    """Per-sequence KV bytes read per step, compressed by c, g-redundant if not mcast."""
    return (m.kv_distinct(seq) / c) * (1 if multicast else m.g)


def max_batch(m, box, seq, c):
    """Capacity-limited batch. Storage is compressed distinct KV, so it scales with c."""
    free = box.cap - m.weight_bytes()
    return int(free // (m.kv_distinct(seq) / c)) if free > 0 else 0


def tput(m, box, seq, B, multicast, c):
    if B <= 0:
        return 0.0
    return B * box.bw / (m.weight_bytes() + B * kv_read(m, seq, multicast, c))


def mcast_speedup(m, box, seq, B, c):
    b = tput(m, box, seq, B, False, c)
    return (tput(m, box, seq, B, True, c) / b) if b else 0.0


def _selfcheck():
    m, box = MODELS[1], QUIETBOX          # Llama-3-70B on a QuietBox
    W, cap, g = m.weight_bytes(), box.cap, m.g
    analytic = (W + g * (cap - W)) / cap  # multicast speedup at full memory, c-free

    # THE INVARIANCE: at the capacity-limited batch, the multicast speedup does NOT
    # depend on c or context -- EXACTLY in the continuous limit. With integer batch it
    # holds tightly once enough sequences fit to fill memory (B >= 10); at long context
    # where only 1-2 fit, rounding leaves memory underfull and the speedup dips (but
    # never collapses). That dip is real, so assert BOTH facts honestly.
    for c in (1, 5.3, 8, 16):
        for seq in (8192, 32768, 131072):
            B = max_batch(m, box, seq, c)
            if B == 0:
                continue
            s = mcast_speedup(m, box, seq, B, c)
            if B >= 10:                                   # memory fills tightly
                assert abs(s - analytic) / analytic < 0.05, (c, seq, s, analytic)
            else:                                         # underfull, dips but survives
                assert 4.0 < s <= analytic + 1e-9, (c, seq, s, analytic)

    # compression must multiply the fittable batch ~linearly
    b1 = max_batch(m, box, 32768, 1)
    b6 = max_batch(m, box, 32768, 6)
    assert abs(b6 / b1 - 6) < 0.15, (b1, b6)

    # LATENCY regime: at fixed small batch, more compression must ERODE multicast
    # toward 1x (weights come to dominate).
    s_c1 = mcast_speedup(m, box, 32768, 1, 1)
    s_c8 = mcast_speedup(m, box, 32768, 1, 8)
    assert s_c8 < s_c1, (s_c1, s_c8)
    assert s_c8 < 1.3, s_c8            # nearly gone at batch 1 with heavy compression

    print(f"selfcheck OK — throughput-regime multicast speedup is compression-INVARIANT "
          f"({analytic:.2f}x); latency-regime it erodes ({s_c1:.2f}x -> {s_c8:.2f}x)")


def _fmt(t):
    return f"{t:>6.0f}" if t >= 1 else f"{t:>6.2f}"


def main():
    m, box = MODELS[1], QUIETBOX
    W, cap, g = m.weight_bytes(), box.cap, m.g
    print(f"\n  Llama-3-70B on {box.name}  (weights {W / GB:.0f} GB, cap {cap / GB:.0f} GB, "
          f"BW {box.bw / GB:.0f} GB/s, GQA g={g})")
    print(f"  KV compression c: 1=BF16, 5.3=TurboQuant 3-bit, 8=2-bit-aggressive\n")

    print(f"  === THROUGHPUT serving: batch grows to fill memory (datacenter default) ===")
    print(f"  {'context':>8} {'c':>5} {'batch*':>7} {'tok/s base':>11} "
          f"{'tok/s +mcast':>13} {'mcast x':>8} {'vs c=1 base':>12}")
    for seq in (32768, 131072):
        base_c1 = None
        for c in (1, 5.3, 8):
            B = max_batch(m, box, seq, c)
            if B == 0:
                print(f"  {seq:>7} {c:>5} {'—':>7}  KV/seq too big to fit even 1")
                continue
            t_base = tput(m, box, seq, B, False, c)
            t_mc = tput(m, box, seq, B, True, c)
            if c == 1:
                base_c1 = t_base
            print(f"  {seq:>7} {c:>5} {B:>7} {_fmt(t_base)}      {_fmt(t_mc)}       "
                  f"{t_mc / t_base:>5.1f}x   {t_base / base_c1:>9.1f}x")
        print()

    print(f"  Read: the 'mcast x' column is FLAT down each block — multicast's gain does")
    print(f"  not depend on compression. Compression multiplies the BASE (more batch);")
    print(f"  multicast multiplies that again by the same ~{(W + g * (cap - W)) / cap:.1f}x. They STACK.\n")

    print(f"  === LATENCY serving: batch fixed at 1 by a tight SLA ===")
    print(f"  {'context':>8} {'c':>5} {'tok/s base':>11} {'tok/s +mcast':>13} {'mcast x':>8}")
    for seq in (32768, 131072):
        for c in (1, 5.3, 8):
            t_base = tput(m, box, seq, 1, False, c)
            t_mc = tput(m, box, seq, 1, True, c)
            print(f"  {seq:>7} {c:>5} {_fmt(t_base)}      {_fmt(t_mc)}       "
                  f"{t_mc / t_base:>5.1f}x")
        print()

    print(f"  Read: at batch 1 weights dominate; compression shrinks KV to near-nothing,")
    print(f"  so multicast erodes toward 1x — UNLESS context is long enough that KV still")
    print(f"  dominates even compressed (128K holds the gain better than 32K).\n")

    print(f"  VERDICT: compression does NOT eat multicast where it matters most —")
    print(f"  throughput serving, where they stack. It only erodes multicast in the")
    print(f"  small-batch latency regime, and even there long context preserves it.")
    print(f"  Betting on multicast is betting on the KV cache staying big relative to")
    print(f"  weights, which is exactly what long-context inference guarantees.")


if __name__ == "__main__":
    _selfcheck() if "--selfcheck" in sys.argv else main()
