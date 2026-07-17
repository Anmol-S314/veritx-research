#!/usr/bin/env python3
"""Gate 1 (v2): does topology-level KV-MULTICAST beat a BROADCAST collective? (T3 scale-out door)

Companion to decode_roofline.py, one rung up (inter-chip / scale-out fabric of a
disaggregated prefill/decode deployment). v1 of this script compared multicast to a
NAIVE per-consumer unicast baseline (F x the bytes) and found the fabric "binds above
fanout ~36." That was a strawman, flagged in PITFALLS spirit. v2 fixes it.

THE HONEST BASELINE. No competent system sends a shared prefix's KV to F consumers as
F independent unicasts. It uses a BANDWIDTH-OPTIMAL BROADCAST collective (pipelined
ring / tree, NCCL-style): the buffer crosses the bottleneck link ~ONCE, so broadcast
time is ~= data/BW, essentially FLAT in F — the same bottleneck-bandwidth cost as
in-network multicast. So the real question is not "unicast vs multicast" (multicast
wins trivially) but:

    Does hardware / topology-level MULTICAST beat a software BROADCAST collective?

Three schemes to deliver a prefix's KV (size kv) to F decode instances over per-chip BW B:
  - UNICAST (naive):   time = F * kv / B          source egress F x   (the strawman)
  - BROADCAST (ring):  time ~= kv / B + depth*a   source egress 1x, EACH RELAY egress 1x
  - MULTICAST (fork):  time ~= kv / B + a          source egress 1x, relay egress 0 (switch forks)

BROADCAST and MULTICAST have the SAME bottleneck-bandwidth term (kv/B). Multicast's only
edges: it frees the F-1 relay NICs of their forward (kv each), and saves (depth-1) store-
and-forward hops of latency. For LARGE kv both edges are tiny relative to kv/B. This
script quantifies exactly how tiny, and folds in PREFIX CACHING (a hit => transfer zero).

    python3 scripts/interchip_roofline.py [--selfcheck]

Roofline, not simulation: microseconds, cannot be stuck. Uncertain inputs (scale-out BW,
per-hop latency, cache-hit rate, fanout) are swept; the verdict is read from the gaps.
"""
import sys

# --- Model: Llama-3-70B (matches serving_multicast.py / CONCLUSION.md) --------
L, H, N_KV, D_HEAD, PARAMS = 80, 8192, 8, 128, 70e9

# --- Deployment: Tenstorrent QuietBox, 8x n300d (matches CONCLUSION.md) --------
N_CHIPS = 8
DRAM_AGG_GBS = 4608.0

# --- Inter-chip fabric (swept) + per-hop latency ------------------------------
FABRIC_GBS = 25.0            # per-chip scale-out BW, one direction (~20-90x below NoC)
HOP_LAT_US = 2.0            # inter-chip store-and-forward latency per hop (~us-scale)
DTYPE_B = 2


def kv_bytes(seq_len, dtype_b=DTYPE_B):
    return 2 * L * N_KV * D_HEAD * seq_len * dtype_b


def weight_time_per_token(dtype_b=DTYPE_B):
    """Decode's binding stage (decode_roofline.py): all weights once/token from DRAM."""
    return (PARAMS * dtype_b) / (DRAM_AGG_GBS * 1e9)


def deliver_time(scheme, seq_len, fanout, fabric_gbs=FABRIC_GBS, hop_us=HOP_LAT_US):
    """Wall-clock to deliver a prefix's KV to `fanout` instances (a BURST, seconds)."""
    kv = kv_bytes(seq_len)
    B = fabric_gbs * 1e9
    a = hop_us * 1e-6
    if scheme == "unicast":
        return fanout * kv / B                       # source serialises F copies
    if scheme == "broadcast":
        depth = max(1, fanout - 1)                    # pipelined ring: F-1 forward hops
        return kv / B + depth * a                     # bandwidth term flat in F
    if scheme == "multicast":
        return kv / B + a                             # one fork pass in-fabric
    raise ValueError(scheme)


def relay_egress_bytes(scheme, seq_len, fanout):
    """Total bytes the intermediate DECODE nodes must forward (steals their NIC)."""
    kv = kv_bytes(seq_len)
    if scheme == "broadcast":
        return (fanout - 1) * kv                      # each relay forwards ~kv
    return 0                                          # unicast: source-only; multicast: switch forks


def amortized_ms_per_token(scheme, seq_len, fanout, out_len=512, cache_hit=0.0,
                            fabric_gbs=FABRIC_GBS):
    """Distribution burst spread over the decode run, x (1 - cache_hit)."""
    t = deliver_time(scheme, seq_len, fanout, fabric_gbs) * (1.0 - cache_hit)
    return t / out_len * 1e3


def _selfcheck():
    kv32 = 32768
    # (1) BROADCAST already keeps the bottleneck-bandwidth term ~= the F=1 unicast cost,
    #     i.e. broadcast is ~FLAT in F while naive unicast grows F x. So the v1 "fabric
    #     binds above F~36" was an artifact of the strawman baseline.
    for F in (4, 16, 64):
        tb = deliver_time("broadcast", kv32, F)
        tu = deliver_time("unicast", kv32, F)
        t1 = deliver_time("unicast", kv32, 1)
        assert abs(tb - t1) / t1 < 0.01, f"broadcast should ~= 1x unicast, got {tb/t1:.3f}x at F={F}"
        assert tu > tb * (F - 1), f"naive unicast must be ~Fx broadcast at F={F}"

    # (2) THE significance test: MULTICAST vs BROADCAST. For large KV the two are within
    #     a hair on wall-clock (both dominated by kv/B); multicast's only wins are relay
    #     egress and a few hops of latency, both negligible here. => the multicast thesis
    #     does NOT clear significance against a proper baseline.
    for F in (4, 16, 64):
        tb = deliver_time("broadcast", kv32, F)
        tm = deliver_time("multicast", kv32, F)
        assert (tb - tm) / tb < 0.001, f"multicast should be ~= broadcast, gap {(tb-tm)/tb:.4f} at F={F}"

    # (3) and BOTH broadcast and multicast sit far under the weight wall (amortised),
    #     so the scale-out fabric does NOT bind under a competent collective — the
    #     on-chip verdict extends up a rung.
    wall = weight_time_per_token() * 1e3
    for F in (4, 16, 64):
        assert amortized_ms_per_token("broadcast", kv32, F) < wall, "broadcast must stay under the wall"
        assert amortized_ms_per_token("multicast", kv32, F) < wall, "multicast must stay under the wall"

    # (4) prefix caching only widens the margin (a hit => transfer zero).
    assert amortized_ms_per_token("broadcast", kv32, 16, cache_hit=0.8) < \
           amortized_ms_per_token("broadcast", kv32, 16, cache_hit=0.0)

    print("selfcheck OK — broadcast is ~flat in F (v1's unicast baseline was a strawman); "
          "multicast ~= broadcast within <0.1% for large KV; both sit under the weight wall. "
          "The 'topology shifts via multicast' thesis does NOT clear a proper baseline.")


def main():
    ms, us = 1e3, 1e6
    wall = weight_time_per_token() * ms
    kv32 = 32768
    kv_gb = kv_bytes(kv32) / 1e9
    print(f"\n  Inter-chip roofline v2 — Llama-3-70B, QuietBox 8x n300d, BF16")
    print(f"  weight DRAM wall = {wall:.1f} ms/token   |   32K-ctx KV = {kv_gb:.1f} GB   |   "
          f"scale-out link = {FABRIC_GBS:.0f} GB/s/chip\n")

    print(f"  (A) DELIVER a 32K prefix's KV to F instances — wall-clock BURST (seconds):")
    print(f"      {'F':>4} {'unicast s':>11} {'broadcast s':>12} {'multicast s':>12} {'mc vs bcast':>12}")
    for F in (1, 2, 4, 16, 64):
        tu = deliver_time("unicast", kv32, F)
        tb = deliver_time("broadcast", kv32, F)
        tmc = deliver_time("multicast", kv32, F)
        gain = f"{(1 - tmc/tb)*100:.3f}%" if tb else "-"
        print(f"      {F:>4} {tu:>11.3f} {tb:>12.3f} {tmc:>12.3f} {gain:>12}")
    print(f"      => naive unicast grows F x; BROADCAST is ~flat in F; MULTICAST beats broadcast")
    print(f"         by a fraction of a percent — the kv/B bandwidth term dominates both.\n")

    print(f"  (B) amortised per output token (/512) vs the {wall:.0f} ms wall, F=16:")
    for sch in ("unicast", "broadcast", "multicast"):
        a = amortized_ms_per_token(sch, kv32, 16)
        b = "FABRIC" if a > wall else "dram"
        print(f"      {sch:>10} {a:>8.2f} ms/tok   binds on: {b}")
    print(f"      => under a competent BROADCAST, the fabric never binds; multicast changes nothing.\n")

    print(f"  (C) multicast's ONLY real edges, quantified (F=16, 32K):")
    relay = relay_egress_bytes("broadcast", kv32, 16) / 1e9
    lat_saved = (deliver_time("broadcast", kv32, 16) - deliver_time("multicast", kv32, 16)) * us
    band = kv_bytes(kv32) / (FABRIC_GBS * 1e9)
    print(f"      relay-NIC egress freed : {relay:.0f} GB total across 15 relays (~{relay/15:.1f} GB each)")
    print(f"        — but decode nodes are DRAM-bound (weights), their NICs have slack, so this is cheap.")
    print(f"      latency saved vs bcast : {lat_saved:.0f} us, against a {band*1e3:.0f} ms bandwidth term")
    print(f"        — i.e. {lat_saved/us/band*100:.4f}% of the transfer time. Negligible for large KV.\n")

    print(f"  (D) sweep the uncertain inputs — does ANY realistic corner make multicast beat broadcast?")
    print(f"      {'link GB/s':>9} {'F':>4} {'bcast ms/tok':>13} {'mc ms/tok':>11} {'mc gain':>9} {'binds':>7}")
    for lk in (12.5, 25, 100):
        for F in (8, 64):
            ab = amortized_ms_per_token("broadcast", kv32, F, fabric_gbs=lk)
            am = amortized_ms_per_token("multicast", kv32, F, fabric_gbs=lk)
            binds = "FABRIC" if ab > wall else "dram"
            print(f"      {lk:>9.1f} {F:>4} {ab:>13.2f} {am:>11.2f} {(1-am/ab)*100:>8.3f}% {binds:>7}")

    print(f"\n  VERDICT (Gate 1, honest baseline): the 'optimal topology SHIFTS because KV-multicast")
    print(f"  relieves a scale-out bottleneck' thesis DOES NOT SURVIVE. Against a bandwidth-optimal")
    print(f"  broadcast collective — what real systems already use — in-network multicast wins a")
    print(f"  fraction of a percent, and the fabric never binds for weight-DRAM-bound decode anyway.")
    print(f"  The on-chip verdict extends one rung UP: scale-out topology is SECOND-ORDER for")
    print(f"  transformer inference too. What (narrowly) survives — small-message / NIC-contended /")
    print(f"  ultra-high-fanout latency corners — needs its OWN justification; it is not this paper.\n")
    print(f"  => The defensible result is the NEGATIVE one (fabric second-order, broadcast suffices),")
    print(f"     not 'topology shifts'. Same shape as the on-chip finding, now proven a rung higher.\n")


if __name__ == "__main__":
    _selfcheck() if "--selfcheck" in sys.argv else main()
