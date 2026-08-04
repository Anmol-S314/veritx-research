#!/usr/bin/env python3
"""K/V multicast in a REAL batched-serving scenario, not per-token. (T3)

multicast_savings.py did per-token traffic and implicitly assumed batch=1. Real serving
batches many sequences per decode step, and batching changes the arithmetic in the way
that matters most:

  * WEIGHTS are read once per step and AMORTISED across the whole batch (this is why
    batching exists). Per token, weight traffic = W / B -> shrinks as batch grows.
  * KV CACHE is PER-SEQUENCE and is NOT amortised. Per step it scales with batch: B
    sequences each read their own full cache.

So as batch and context grow, KV comes to dominate DRAM traffic -- and KV is exactly
what multicast attacks. Batching does not dilute the multicast win; it CONCENTRATES it.

DEPLOYMENT (swap freely): Tenstorrent QuietBox = 8x Wormhole n300d.
  capacity  8 x 24 GB   = 192 GB      (holds weights + the batch's KV cache)
  DRAM BW   8 x 576 GB/s = 4608 GB/s   (decode is DRAM-bound -> this sets tokens/sec)
Both numbers from arXiv 2603.23343 Table 2 (n300d), x8.

THROUGHPUT MODEL (decode is DRAM-bound, per decode_roofline.py):
  bytes/step = W + B * K_read           K_read = per-sequence KV read this step
  time/step  = bytes/step / (BW_agg * eps)
  tokens/sec = B / time/step = B * BW_agg * eps / (W + B * K_read)
     small B: ~ B*BW*eps/W    (weight-amortisation regime, linear in batch)
     large B: ~ BW*eps/K_read (KV-bound ceiling -- where multicast changes the ceiling)

  eps = ACHIEVED / PEAK DRAM bandwidth. NOT 1.0 -- an earlier version implicitly assumed
  peak, which is exactly the uncalibrated assumption this track distrusts. Measured with
  Ramulator2 (scripts/dram_efficiency.py, GDDR6): ~0.91 for a per-head-CONTIGUOUS KV layout
  (the ~9% gap is refresh), collapsing to ~0.66 if the KV cache is stored vLLM-interleaved
  [block,heads,dim] so reading one head strides past the other g-1 and thrashes the row
  buffer. eps derates the ABSOLUTE tok/s; it CANCELS in the multicast/naive speedup (same
  layout both ways). Consequence: the schedule REQUIRES per-head-contiguous KV storage.

THE MULTICAST KNOB is K_read:
  naive head-parallel (what the vendor ships): each of a GQA group's g query heads sits
    on a different core and re-fetches the shared KV head -> K_read = g * K_distinct.
  multicast (or ideal co-location): fetch once, share over the NoC -> K_read = K_distinct.
  So multicast cuts the KV term by up to g = n_q / n_kv, and at the KV-bound ceiling that
  is a g-fold throughput gain.

HONESTY (these bound the claim, so they are stated up front, not buried):
  * The g-fold factor is the penalty of the HEAD-PARALLEL mapping specifically. A
    context-parallel mapping avoids the redundancy a different way (cross-core reduction
    instead of multicast). g is the CEILING of the multicast win, realised when the
    schedule would otherwise split a group across cores -- which is the norm when you
    spread one sequence over many cores for low-latency decode.
  * Capacity is set by DISTINCT KV (you only STORE n_kv heads; the redundancy is in
    reads). So multicast does NOT raise the max batch -- it speeds up the batch you can
    already fit. It is a bandwidth win, not a capacity win.
  * KV shared across CHIPS would ride the Ethernet scale-out fabric, not the on-chip
    NoC. This models the aggregate/intra-chip picture.
  * The NoC delivery side is SILICON-MEASURED, not assumed: the official Tenstorrent
    multicast-schemes study (tt-low-level-documentation, the closed #22519 deliverable;
    curves extracted into scripts/mcast_measured.py) shows a row-multicast on NOC0 with
    the sender excluded sustains 30.59 -> 29.79 B/cyc from 2x2 to 7x7 -- flat in fanout
    (<3% total). The schedule's per-row feed (14.6 GB/s) sits at >=1.8x headroom even at
    49 destinations, so the NoC never binds and the g-fold ratio stands -- PROVIDED the
    row multicast runs on NOC0 with a row-shared placement (the same study shows the
    col-shared-on-NOC0 / row-shared-on-NOC1 pairings collapse up to ~15%: that is a
    design constraint, not a free parameter).

    python3 scripts/serving_multicast.py [--selfcheck]
"""
import sys

GB = 1e9
GiB = 2 ** 30

# Achieved / peak DRAM bandwidth for the KV read. Measured, not assumed (the whole point):
# Ramulator2 GDDR6, per-head-CONTIGUOUS layout, saturated, refresh on -> 0.91 (the 9% is
# refresh). See scripts/dram_efficiency.py. A vLLM-interleaved KV layout would drop this to
# ~0.66; the schedule forbids that (SCHEDULE.md layout requirement). eps derates the ABSOLUTE
# tok/s but CANCELS in the multicast/naive ratio (same layout both ways), so the selfcheck's
# speedup bounds are unaffected.
DRAM_EFF = 0.91


class Model:
    def __init__(self, name, layers, n_q, n_kv, d_head, n_params):
        self.name, self.layers = name, layers
        self.n_q, self.n_kv, self.d_head, self.n_params = n_q, n_kv, d_head, n_params

    @property
    def g(self):
        return self.n_q // self.n_kv

    def kv_distinct(self, seq, dtype=2):
        """Bytes of KV a sequence actually STORES / ideally reads per step."""
        return 2 * self.layers * self.n_kv * self.d_head * seq * dtype

    def weight_bytes(self, dtype=1):        # BFP8 weights (Tenstorrent-native)
        return self.n_params * dtype


class Box:
    """A serving deployment: aggregate DRAM capacity and bandwidth."""
    def __init__(self, name, cap_bytes, bw_bytes_per_s):
        self.name, self.cap, self.bw = name, cap_bytes, bw_bytes_per_s


QUIETBOX = Box("QuietBox (8x n300d)", 8 * 24 * GB, 8 * 576 * GB)

MODELS = [
    Model("Llama-3-8B", 32, 32, 8, 128, 8.03e9),
    Model("Llama-3-70B", 80, 64, 8, 128, 70.6e9),
]


def max_batch(model, box, seq):
    """Capacity-limited batch: weights + B * distinct-KV must fit. Storage is distinct
    whether or not multicast is used, so this bounds BOTH cases identically."""
    free = box.cap - model.weight_bytes()
    if free <= 0:
        return 0
    return int(free // model.kv_distinct(seq))


def throughput(model, box, seq, B, multicast):
    """Tokens/sec for a decode step, DRAM-bound."""
    if B <= 0:
        return 0.0
    k_read = model.kv_distinct(seq) * (1 if multicast else model.g)
    bytes_per_step = model.weight_bytes() + B * k_read
    return B * box.bw * DRAM_EFF / bytes_per_step


def operating_point(model, box, seq, B=None):
    B = max_batch(model, box, seq) if B is None else B
    before = throughput(model, box, seq, B, multicast=False)
    after = throughput(model, box, seq, B, multicast=True)
    return {"batch": B, "before": before, "after": after,
            "speedup": (after / before) if before else 0.0,
            "kv_per_seq_GB": model.kv_distinct(seq) / GB}


def _selfcheck():
    m70 = MODELS[1]
    # KV cache per sequence must match the known Llama-3-70B figure: ~10.7 GB at 32K BF16
    assert abs(m70.kv_distinct(32768) / GB - 10.7) < 0.3, m70.kv_distinct(32768) / GB

    # multicast speedup must approach g as batch grows (weights amortise away) and be
    # >= 1 and <= g always
    for seq in (8192, 32768):
        big = throughput(m70, QUIETBOX, seq, 10_000_000, False)
        bigm = throughput(m70, QUIETBOX, seq, 10_000_000, True)
        assert abs(bigm / big - m70.g) < 0.05, (bigm / big, m70.g)
        op = operating_point(m70, QUIETBOX, seq)
        assert 1.0 <= op["speedup"] <= m70.g + 1e-9, op

    # multicast is a BANDWIDTH win, not capacity: max_batch identical with/without it
    # (baked in -- max_batch ignores the multicast flag; assert the storage basis)
    b = max_batch(m70, QUIETBOX, 32768)
    assert m70.weight_bytes() + b * m70.kv_distinct(32768) <= QUIETBOX.cap
    assert m70.weight_bytes() + (b + 1) * m70.kv_distinct(32768) > QUIETBOX.cap

    # weight amortisation: per-token weight traffic must fall as batch rises
    t1 = throughput(m70, QUIETBOX, 8192, 1, False)
    t8 = throughput(m70, QUIETBOX, 8192, 8, False)
    assert t8 > t1, "batching should raise throughput"
    print(f"selfcheck OK — KV matches silicon; speedup in [1, g={m70.g}], -> g at large "
          f"batch; multicast is bandwidth not capacity")


def _fmt(tok):
    return f"{tok:>6.0f}" if tok >= 1 else f"{tok:>6.2f}"


def main():
    box = QUIETBOX
    print(f"\n  Batched decode on {box.name}: {box.cap / GB:.0f} GB, "
          f"{box.bw / GB:.0f} GB/s aggregate x {DRAM_EFF:.2f} achieved (Ramulator2, GDDR6)")
    print(f"  decode is DRAM-bound -> tokens/sec = B * BW * {DRAM_EFF:.2f} / (weights + B * KV_read)\n")

    for m in MODELS:
        print(f"  {m.name}  (BFP8 weights {m.weight_bytes() / GB:.0f} GB, "
              f"GQA group g={m.g})")
        print(f"    {'context':>8} {'batch*':>6} {'KV/seq':>8} "
              f"{'tok/s base':>11} {'tok/s mcast':>12} {'speedup':>8} {'/seq base->mcast':>18}")
        for seq in (8192, 32768, 131072):
            op = operating_point(m, box, seq)
            B = op["batch"]
            if B == 0:
                print(f"    {seq:>7}   —     {op['kv_per_seq_GB']:>6.1f}GB   "
                      f"does not fit (KV/seq {op['kv_per_seq_GB']:.0f} GB > free capacity)")
                continue
            ps_b, ps_a = op["before"] / B, op["after"] / B
            print(f"    {seq:>7}  {B:>5}  {op['kv_per_seq_GB']:>6.1f}GB "
                  f"{_fmt(op['before'])}      {_fmt(op['after'])}      "
                  f"{op['speedup']:>5.1f}x   {ps_b:>6.1f} -> {ps_a:<6.1f}")
        print()

    print(f"  * batch is capacity-limited (weights + B*KV must fit in {box.cap / GB:.0f} GB).")
    print(f"    Multicast does NOT raise it (storage is unchanged) — it speeds up the")
    print(f"    batch you can already hold. tok/s are AGGREGATE; /seq is the per-user rate.\n")

    m70 = MODELS[1]
    op = operating_point(m70, box, 32768)
    print(f"  HEADLINE — Llama-3-70B, 32K context, {box.name}:")
    print(f"    batch {op['batch']} fills memory; without multicast the KV cache is read")
    print(f"    {m70.g}x redundantly and the box delivers {op['before']:.0f} tok/s "
          f"({op['before'] / op['batch']:.1f}/user).")
    print(f"    Multicast shares each KV head over the idle NoC -> {op['after']:.0f} tok/s "
          f"({op['after'] / op['batch']:.1f}/user), a {op['speedup']:.1f}x throughput gain")
    print(f"    at ZERO extra silicon — the win the topology sweep could never have found.")
    print(f"    (tok/s are at {DRAM_EFF:.2f} DRAM efficiency; the {op['speedup']:.1f}x ratio holds at any")
    print(f"    efficiency. REQUIRES per-head-contiguous KV storage — see dram_efficiency.py.)")

    print(f"\n  The two results are one story: on-chip topology is not the lever")
    print(f"  (it's not the bottleneck), and that is *precisely why* the NoC has the")
    print(f"  spare bandwidth to cut DRAM traffic — which is.")


if __name__ == "__main__":
    _selfcheck() if "--selfcheck" in sys.argv else main()
