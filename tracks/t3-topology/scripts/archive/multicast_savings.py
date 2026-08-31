#!/usr/bin/env python3
"""How much DRAM traffic does K/V multicast remove in GQA decode? (T3 — the useful lever)

The roofline (decode_roofline.py) showed decode is DRAM-bandwidth-bound and the NoC has
4x headroom. So the NoC's value is NOT its topology -- it is that it can carry on-chip
traffic that REMOVES load from DRAM, the actual bottleneck. Tenstorrent named the
specific opportunity and has not shipped it:

    "cores parallelized on Q heads need to read the same K and V heads. We could
     reduce total DRAM traffic by using multicasting to share K and V heads between
     groups of cores."  -- tt-metal FlashAttention report

This quantifies it. It is arithmetic, not simulation -- it cannot get stuck.

THE MECHANISM. In GQA there are n_q query heads but only n_kv < n_q key/value heads;
each KV head is shared by a group of  g = n_q / n_kv  query heads. To use many cores on
few KV heads (low-batch decode), a group's query heads land on DIFFERENT cores. If each
such core independently reads its KV head's cache from DRAM, that head is read g times.
Multicast reads it ONCE from DRAM and shares it over the NoC. So:

    KV DRAM traffic without multicast  = 2 * layers * n_q  * d_head * seq * dtype
    KV DRAM traffic WITH    multicast  = 2 * layers * n_kv * d_head * seq * dtype
    reduction on the KV cache          = g = n_q / n_kv

Weights are read once per token regardless (a decode GEMV) and are unaffected. So the
NET saving depends on how much of total DRAM traffic is KV -- which GROWS with context.

    python3 scripts/multicast_savings.py [--selfcheck]
"""
import sys

GiB = 2 ** 30


class Model:
    def __init__(self, name, layers, n_q, n_kv, d_head, n_params):
        self.name, self.layers = name, layers
        self.n_q, self.n_kv, self.d_head = n_q, n_kv, d_head
        self.n_params = n_params

    @property
    def group(self):
        return self.n_q // self.n_kv

    def kv_multicast(self, seq, dtype):
        """Distinct KV cache = DRAM traffic per token WITH multicast."""
        return 2 * self.layers * self.n_kv * self.d_head * seq * dtype

    def kv_redundant(self, seq, dtype):
        """Every group member re-fetches = DRAM traffic per token WITHOUT multicast."""
        return 2 * self.layers * self.n_q * self.d_head * seq * dtype

    def weights(self, dtype):
        return self.n_params * dtype


MODELS = [
    Model("Llama-3-8B", layers=32, n_q=32, n_kv=8, d_head=128, n_params=8.03e9),
    Model("Llama-3-70B", layers=80, n_q=64, n_kv=8, d_head=128, n_params=70.6e9),
    Model("Llama-3.1-405B", layers=126, n_q=128, n_kv=8, d_head=128, n_params=405e9),
]
CONTEXTS = [8192, 32768, 131072]           # 8K, 32K, 128K
W_DTYPE = 2                                # weights BF16
KV_DTYPE = 2                               # KV cache BF16


def row(m, seq, w_dtype=W_DTYPE, kv_dtype=KV_DTYPE):
    w = m.weights(w_dtype)
    kv_b = m.kv_redundant(seq, kv_dtype)
    kv_a = m.kv_multicast(seq, kv_dtype)
    tot_b, tot_a = w + kv_b, w + kv_a
    return {
        "weights": w, "kv_before": kv_b, "kv_after": kv_a,
        "total_before": tot_b, "total_after": tot_a,
        "kv_frac_before": kv_b / tot_b,
        "saved_frac": (kv_b - kv_a) / tot_b,
        # decode is DRAM-BOUND (roofline), so time ~ DRAM bytes: speedup ~ traffic ratio
        "decode_speedup": tot_b / tot_a,
    }


def _selfcheck():
    m8 = MODELS[0]
    # KV cache formula must reproduce the known Llama-3-8B figure: ~16 GiB at 128K, BF16.
    kv = m8.kv_multicast(131072, 2)
    assert abs(kv / GiB - 16.0) < 0.5, f"KV cache {kv / GiB:.1f} GiB != known ~16"

    # reduction factor must equal the GQA group size, exactly
    for m in MODELS:
        r = m.kv_redundant(1000, 2) / m.kv_multicast(1000, 2)
        assert abs(r - m.group) < 1e-9, (m.name, r, m.group)

    # the saving must GROW with context (KV grows, weights fixed) and be bounded by
    # the per-KV asymptote (g-1)/g as seq -> infinity
    s = [row(m8, c)["saved_frac"] for c in (8192, 32768, 131072)]
    assert s[0] < s[1] < s[2], f"saving not monotonic in context: {s}"
    asymptote = (m8.group - 1) / m8.group
    assert all(x < asymptote for x in s), f"saving exceeds (g-1)/g={asymptote}"

    # speedup must be >= 1 and tie out with saved_frac: speedup = 1/(1-saved)
    r = row(m8, 131072)
    assert abs(r["decode_speedup"] - 1 / (1 - r["saved_frac"])) < 1e-9
    assert r["decode_speedup"] > 1.0
    print(f"selfcheck OK — KV formula matches silicon (16 GiB @128K); "
          f"reduction = GQA group size; saving grows with context")


def main():
    print(f"\n  DRAM traffic removed by K/V multicast in GQA decode (BF16 weights + KV)")
    print(f"  decode is DRAM-bound (see decode_roofline.py), so % DRAM saved ~ % faster\n")
    for m in MODELS:
        print(f"  {m.name}  —  GQA group size g = {m.n_q}/{m.n_kv} = {m.group}"
              f"  (KV read {m.group}x without multicast)")
        print(f"    {'context':>8} {'weights':>9} {'KV before':>10} {'KV after':>9} "
              f"{'DRAM/tok':>9} {'KV share':>9} {'DRAM saved':>11} {'decode':>8}")
        for seq in CONTEXTS:
            r = row(m, seq)
            print(f"    {seq:>7}  {r['weights'] / GiB:>7.1f}GB {r['kv_before'] / GiB:>8.1f}GB "
                  f"{r['kv_after'] / GiB:>7.1f}GB {r['total_before'] / GiB:>7.1f}GB "
                  f"{100 * r['kv_frac_before']:>7.0f}% {100 * r['saved_frac']:>9.0f}% "
                  f"{r['decode_speedup']:>6.2f}x")
        print()

    print(f"  Reading: at short context weights dominate and multicast barely helps; as")
    print(f"  context grows the KV cache takes over and the saving climbs toward its")
    print(f"  ceiling (g-1)/g. Long-context, large-group models are where it pays:\n")
    big = row(MODELS[2], 131072)
    print(f"    Llama-3.1-405B @128K: {100 * big['saved_frac']:.0f}% less DRAM traffic per"
          f" token -> {big['decode_speedup']:.1f}x decode, purely by moving")
    print(f"    shared K/V onto the NoC that the roofline proved is sitting idle.")

    print(f"\n  Two things sharpen this further (not modelled above, stated honestly):")
    print(f"   * Quantizing WEIGHTS to BFP8 (1B) while keeping KV at BF16 shifts more of")
    print(f"     the traffic to KV -> multicast helps MORE, not less.")
    print(f"   * The NoC cost is real but bounded: one multicast tree replaces g DRAM")
    print(f"     fetches that each already crossed the array, so NoC hop-traffic FALLS")
    print(f"     too. And the roofline showed 4x NoC headroom to absorb it.")

    print(f"\n  CONCLUSION: the NoC's payoff for our workload is not its shape — it is")
    print(f"  using its idle capacity to cut DRAM traffic, the actual bottleneck. That")
    print(f"  is a mapping/dataflow lever, and it is worth real speedup at long context.")


if __name__ == "__main__":
    _selfcheck() if "--selfcheck" in sys.argv else main()
