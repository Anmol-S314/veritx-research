#!/usr/bin/env python3
"""Does the NoC return to the critical path for BF16/BFP8 decode? (T3, Phase 0b door)

Phase 0b found that arXiv 2603.23343's measured "the NoC doesn't matter" kernels were
ALL run in FP32 on the SFPU. The paper's own spec table (Table 2) shows why that might
not generalise:

    Wormhole n150d      FP8/BFP8  262 TFLOPS
                        FP16/BF16  74 TFLOPS
                        FP32        2.3 TFLOPS      <- what their kernels used
                        DRAM       288 GB/s

FP32 compute is 32x slower than BF16. If the compute unit is 32x slower, everything
waits on compute, and of course the NoC looks idle. Real transformer inference runs
BF16/BFP8, where compute is 32x faster -- so the balance shifts hard toward memory and
the network. The open question: does it shift far enough that the NoC becomes the wall?

This is a roofline, not a simulation. It cannot be "stuck" and it takes microseconds.

THE MODEL. Decode reads weights (and the KV cache) from DRAM and uses each datum
essentially once -- a matrix-VECTOR product. Arithmetic intensity:

    GEMV y=Wx : 2*d_out*d_in FLOP over 2*d_out*d_in bytes (BF16) = 1.0 FLOP/byte

That is the lowest AI in the whole transformer workload -- the most memory-bound,
most NoC-stressing case. If the NoC is not the bottleneck HERE, it is not anywhere.

Three resources in series on the decode data path  DRAM -> NoC -> L1 -> compute:
  1. DRAM      288 GB/s  (hard cap on bytes/sec entering the chip)
  2. NoC       every byte from DRAM crosses it; capacity = bisection/injection
  3. compute   FLOP/s at the datatype

Whichever is slowest binds. The NoC binds only if its sustainable delivery bandwidth
is BELOW the DRAM bandwidth -- because in steady state the NoC only ever has to carry
what DRAM can supply (288 GB/s), and multicast (alpha>0) REDUCES both DRAM and NoC
traffic (one tree replaces N independent fetches), so alpha=0 is the NoC's worst case.

    python3 scripts/decode_roofline.py [--selfcheck]
"""
import sys

# --- Wormhole n150d, from arXiv 2603.23343 Table 2 (measured) ----------------
DRAM_GBS = 288.0
TFLOPS = {"BF16": 74.0, "BFP8": 262.0, "FP32": 2.3}

# --- NoC capacity ------------------------------------------------------------
# The paper does not print a NoC bandwidth, so this is the one uncertain input and
# it is SWEPT below. Documented Wormhole NoC: each link 32 B/cycle at ~1 GHz AICLK
# ~= 32 GB/s per link per direction, and there are TWO planes (NOC0, NOC1). The
# capacity that matters for DRAM-fed traffic is how fast the 18 DRAM endpoints can
# inject: 18 nodes x 32 GB/s x 2 planes. Bisection (a 12-row torus cut, x2 planes,
# x2 for wraparound) is larger still, so injection is the tighter bound -- use it.
NOC_LINK_GBS = 32.0
N_DRAM_ENDPOINTS = 18
N_PLANES = 2


def noc_inject_gbs(link_gbs=NOC_LINK_GBS):
    """Aggregate rate the DRAM endpoints can push into the fabric."""
    return N_DRAM_ENDPOINTS * link_gbs * N_PLANES


def decode_ai(dtype_bytes=2):
    """FLOP per byte for a decode GEMV: 2 FLOP per MAC, one weight read per MAC."""
    return 2.0 / (2 * dtype_bytes)          # BF16 -> 0.5? no: see below


# NOTE on AI: a weight is `dtype_bytes` bytes and drives one MAC = 2 FLOP. So
# AI = 2 FLOP / dtype_bytes bytes. BF16 (2 B) -> 1.0 FLOP/B. BFP8 (~1 B) -> 2.0.
def ai_flop_per_byte(dtype_bytes):
    return 2.0 / dtype_bytes


def bind(dtype, link_gbs=NOC_LINK_GBS):
    """Which resource is slowest for decode at this datatype? Returns (name, detail)."""
    dbytes = {"BF16": 2, "BFP8": 1, "FP32": 4}[dtype]
    ai = ai_flop_per_byte(dbytes)
    peak_flops = TFLOPS[dtype] * 1e12

    # time to move 1 "unit" = the bytes for 1 FLOP's worth of work, through each stage
    # express each stage as an effective delivered-bytes/sec, take the min
    dram_bps = DRAM_GBS * 1e9
    noc_bps = noc_inject_gbs(link_gbs) * 1e9
    # compute expressed as bytes/sec it can consume at this AI:
    compute_bps = peak_flops / ai

    stages = {"DRAM": dram_bps, "NoC": noc_bps, "compute": compute_bps}
    binder = min(stages, key=stages.get)
    return binder, ai, stages


def _selfcheck():
    # THE finding: decode binds on DRAM at EVERY datatype -- and never on the NoC.
    # Its AI is so low that even FP32's slow 2.3 TFLOPS out-runs DRAM. So the door
    # does not open in any decode regime. If this regresses we must know.
    for dt in ("FP32", "BF16", "BFP8"):
        binder, ai, stages = bind(dt)
        assert binder == "DRAM", f"{dt} decode binds on {binder}, not DRAM: {stages}"
        assert stages["NoC"] > stages["DRAM"], f"{dt}: NoC below DRAM — it would bind"
    assert ai_flop_per_byte(2) == 1.0

    # the door only opens if the NoC link is implausibly slow. The break-even is well
    # below the documented ~32 GB/s, i.e. the conclusion is robust to the one unknown.
    lo = DRAM_GBS / (N_DRAM_ENDPOINTS * N_PLANES)
    assert lo < NOC_LINK_GBS / 3, f"NoC break-even {lo:.1f} too close to real {NOC_LINK_GBS}"

    # sanity: the paper's compute-bound result needs a HIGHER-AI kernel at FP32, not
    # decode. A dot-product-like AI (~a few FLOP/byte) at FP32 flips to compute-bound,
    # which is exactly the regime they measured "NoC idle" in -- a DIFFERENT reason
    # than decode's, but still not the NoC.
    hi_ai_fp32 = TFLOPS["FP32"] * 1e12 / (DRAM_GBS * 1e9)   # AI where FP32 compute=DRAM
    assert 5 < hi_ai_fp32 < 12, hi_ai_fp32
    print(f"selfcheck OK — decode binds on DRAM at FP32/BF16/BFP8; NoC never binds; "
          f"break-even {lo:.1f} GB/s/link vs real ~{NOC_LINK_GBS:.0f}")


def main():
    print(f"\n  Wormhole n150d roofline for DECODE (GEMV, AI = FLOP/byte)")
    print(f"  DRAM {DRAM_GBS:.0f} GB/s | NoC inject {noc_inject_gbs():.0f} GB/s "
          f"({N_DRAM_ENDPOINTS} DRAM nodes x {NOC_LINK_GBS:.0f} x {N_PLANES} planes)\n")

    print(f"  {'datatype':<8} {'TFLOPS':>7} {'AI':>5} {'DRAM':>8} {'NoC':>8} {'compute':>9}   BINDS ON")
    for dt in ("FP32", "BF16", "BFP8"):
        binder, ai, s = bind(dt)
        g = {k: v / 1e9 for k, v in s.items()}
        mark = {"DRAM": "", "NoC": "  <-- !!", "compute": ""}[binder]
        print(f"  {dt:<8} {TFLOPS[dt]:>7.1f} {ai:>5.1f} {g['DRAM']:>7.0f} {g['NoC']:>7.0f} "
              f"{g['compute']:>8.0f}   {binder}{mark}")

    hi = TFLOPS["FP32"] * 1e12 / (DRAM_GBS * 1e9)
    print(f"\n  Reading: each column is the bytes/sec that stage can sustain at this AI;")
    print(f"  the SMALLEST binds. DECODE BINDS ON DRAM AT EVERY DATATYPE — its AI is so")
    print(f"  low ({ai_flop_per_byte(2):.1f}-{ai_flop_per_byte(1):.1f} FLOP/B) that even FP32's slow 2.3 TFLOPS out-runs DRAM.")
    print(f"  (The paper's FP32 kernels found the NoC idle for a DIFFERENT reason: they")
    print(f"  are higher-AI — above ~{hi:.0f} FLOP/B — so at FP32 they hit the COMPUTE wall.")
    print(f"  Decode never gets near it. Either way the NoC is not the bottleneck.)\n")

    lo = DRAM_GBS / (N_DRAM_ENDPOINTS * N_PLANES)
    print(f"  NoC break-even: the NoC would bind only if each link were below "
          f"{lo:.1f} GB/s.")
    print(f"  The documented Wormhole link is ~{NOC_LINK_GBS:.0f} GB/s — a "
          f"{NOC_LINK_GBS / lo:.0f}x margin. Sweep it:\n")
    print(f"    {'link GB/s':>10} {'NoC inject':>11} {'BF16 binds on':>15}")
    for lk in (2, 4, 8, 16, 32, 64):
        b, _, _ = bind("BF16", lk)
        print(f"    {lk:>10.0f} {noc_inject_gbs(lk):>10.0f}  {b:>14}")

    print(f"\n  VERDICT: even in BF16/BFP8 decode — the lowest-AI, most memory-bound,")
    print(f"  most NoC-stressing regime in the whole transformer workload — the wall is")
    print(f"  DRAM, and the NoC has a {NOC_LINK_GBS / lo:.0f}x headroom over it. Multicast")
    print(f"  (alpha>0) only WIDENS that margin: one tree replaces N independent fetches,")
    print(f"  cutting DRAM and NoC traffic together. The door is CLOSED.")


if __name__ == "__main__":
    _selfcheck() if "--selfcheck" in sys.argv else main()
