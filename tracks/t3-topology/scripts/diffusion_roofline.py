#!/usr/bin/env python3
"""Roofline SCOPING: where does DIFFUSION-LLM serving actually bind? (fresh-pond recon)

The whole T3 line found transformer AUTOREGRESSIVE (AR) decode is weight-DRAM-bound —
one token per forward, all weights re-read each token, ~2 FLOP/byte, memory-bound. Every
serving optimization (KV-cache mgmt, memory-bound batching, weight streaming) assumes that.

Diffusion LLMs (LLaDA-style) invert the compute pattern, and this script maps how:
  - The generation region is all-[MASK]; each DENOISING STEP runs a FULL bidirectional
    forward pass over ALL S positions in parallel, unmasks the most-confident ones, repeats
    for N_STEPS. No KV cache in the pure form (all positions can change -> attention recomputed).
  - So per forward, the weights are amortized across S parallel tokens -> arithmetic intensity
    ~S FLOP/byte instead of ~2. That flips the bottleneck OFF memory.

Question this answers (scoping, not a paper): which of {memory, compute, attention} binds
diffusion serving, and where are the crossovers vs S and N_steps? That map is what tells us
whether there's a reachable systems question here BEFORE any Gate-0.

    python3 scripts/diffusion_roofline.py [--selfcheck]

Roofline, not simulation. Anchored on a diffusion-LLM (LLaDA-8B class) on an H100-SXM class
accelerator; the verdict is read from the gaps.
"""
import sys

# --- Model: LLaDA-8B class diffusion LLM --------------------------------------
PARAMS, L, H, DTYPE_B = 8e9, 32, 4096, 2

# --- Accelerator: H100-SXM class (diffusion LLMs run on GPUs) ------------------
PEAK_FLOPS = 989e12          # BF16 dense
DRAM_BW = 3.35e12            # HBM3


def flops_weight(S):
    """GEMM FLOPs through the weights for a forward over S tokens (2 MACs/param/token)."""
    return 2 * PARAMS * S


def flops_attn(S):
    """Bidirectional self-attention FLOPs: QK^T + AV over all S positions, all layers."""
    return 4 * L * H * S * S      # 2*L*S*S*H (scores) + 2*L*S*S*H (values)


def bytes_weight():
    """A forward reads every weight once (amortized across the S parallel tokens)."""
    return PARAMS * DTYPE_B


def forward_time(S):
    """Wall-clock for one full-sequence forward (seconds)."""
    t_compute = (flops_weight(S) + flops_attn(S)) / PEAK_FLOPS
    t_memory = bytes_weight() / DRAM_BW
    return max(t_compute, t_memory)


def binds_on(S):
    """Which term is the tallest pole for a diffusion forward over S tokens."""
    tw = flops_weight(S) / PEAK_FLOPS
    ta = flops_attn(S) / PEAK_FLOPS
    tm = bytes_weight() / DRAM_BW
    return max((tw, "compute"), (ta, "attention"), (tm, "memory"), key=lambda x: x[0])[1]


def diffusion_gen_time(S, n_steps):
    return n_steps * forward_time(S)


def ar_gen_time(S):
    """AR baseline: S sequential tokens, each a memory-bound weight re-read.
    ponytail: ignores KV-attention (small, memory-side) — AR's wall IS the weight DRAM re-read."""
    return S * (bytes_weight() / DRAM_BW)


def _selfcheck():
    # (1) AR single-token decode is MEMORY-bound (the whole T3 premise): compute << memory.
    assert flops_weight(1) / PEAK_FLOPS < bytes_weight() / DRAM_BW, "AR token should be memory-bound"

    # (2) THE inversion: a diffusion forward at LLM seq len is NOT memory-bound — it's COMPUTE-
    #     bound, because weights amortize across S parallel tokens. Opposite regime from AR.
    assert binds_on(512) == "compute", f"diffusion@512 should be compute-bound, got {binds_on(512)}"
    assert binds_on(512) != "memory"

    # (3) At video / world-model token counts, the O(S^2) attention term overtakes weight GEMM
    #     -> a THIRD regime (attention-bound) that neither AR-serving nor LLM-diffusion assumes.
    assert binds_on(1024) == "compute", "still compute-bound at 1K"
    assert binds_on(65536) == "attention", f"should be attention-bound at 64K, got {binds_on(65536)}"

    # (4) diffusion trades memory-reads for compute: N_steps weight-reads vs S for AR. So it wins
    #     wall-clock ONLY when N_steps is well below S — there's a real break-even, not a free lunch.
    S = 512
    be = next(n for n in range(1, S + 1) if diffusion_gen_time(S, n) >= ar_gen_time(S))
    assert 1 < be < S, f"expected a break-even step count strictly inside (1,S), got {be}"

    print(f"selfcheck OK — AR decode is memory-bound; a diffusion forward INVERTS to compute-bound "
          f"(weights amortized over S parallel tokens); at video-scale S it becomes ATTENTION-bound. "
          f"Three distinct regimes; diffusion beats AR wall-clock only below ~{be} steps at S={S}.")


def main():
    ms = 1e3
    print(f"\n  Diffusion-LLM roofline scoping — LLaDA-8B class on H100-SXM class "
          f"({PEAK_FLOPS/1e12:.0f} TFLOP/s, {DRAM_BW/1e12:.2f} TB/s)\n")

    print(f"  (A) what binds a single diffusion forward, vs sequence length S:")
    print(f"      {'S':>7} {'weight ms':>10} {'attn ms':>9} {'mem ms':>8} {'binds on':>10}")
    for S in (128, 512, 2048, 8192, 32768, 131072):
        tw = flops_weight(S) / PEAK_FLOPS * ms
        ta = flops_attn(S) / PEAK_FLOPS * ms
        tm = bytes_weight() / DRAM_BW * ms
        print(f"      {S:>7} {tw:>10.2f} {ta:>9.2f} {tm:>8.2f} {binds_on(S):>10}")
    print(f"      => LLM-scale S: COMPUTE-bound (opposite of AR's memory wall).")
    print(f"         video/world-model-scale S: the O(S^2) ATTENTION term takes over. Third regime.\n")

    print(f"  (B) diffusion vs AR wall-clock to generate S tokens — is the compute trade worth it?")
    print(f"      {'S':>6} {'AR ms':>9} {'N*=break-even':>13} {'diff@N=S/4 ms':>14} {'diff@N=S/2 ms':>14}")
    for S in (256, 512, 1024, 4096):
        ar = ar_gen_time(S) * ms
        be = next((n for n in range(1, S + 1) if diffusion_gen_time(S, n) >= ar_gen_time(S)), S)
        print(f"      {S:>6} {ar:>9.1f} {be:>13} {diffusion_gen_time(S, S//4)*ms:>14.1f} "
              f"{diffusion_gen_time(S, S//2)*ms:>14.1f}")
    print(f"      => diffusion beats AR wall-clock only when N_steps < N* (break-even). Above it,")
    print(f"         you pay N_steps x the FLOPs for no latency win — quality/step is the knob.\n")

    print(f"  SCOPING VERDICT: diffusion serving lives in a DIFFERENT roofline regime than the")
    print(f"  entire AR-serving stack assumes — COMPUTE-bound at LLM scale, ATTENTION-bound at")
    print(f"  video/world-model scale, memory-bound essentially never. Every AR-serving reflex")
    print(f"  (KV-cache mgmt, memory-bound batching, weight streaming) is aimed at a wall that")
    print(f"  isn't the binding one here. THAT is the unmapped territory: the optimal batching /")
    print(f"  parallelism / step-schedule for a compute-and-attention-bound generative workload,")
    print(f"  and where block-diffusion (KV reuse) sits on the memory<->compute trade. Whether any")
    print(f"  slice is unclaimed is the NEXT step (Gate-0) — this pass only shows the pond is real.\n")


if __name__ == "__main__":
    _selfcheck() if "--selfcheck" in sys.argv else main()
