# T3 — Conclusion: on-chip NoC topology is not the lever

**Read this first.** It states the answer and points at the evidence. If you are about
to re-open the topology question, read §"Why this is settled" before spending a day —
we spent several, and the verdict flipped four times before it converged.

---

## The question we set out to answer

> For a transformer accelerator, is the 2D mesh the right on-chip network topology —
> and can a better one (torus, fat-tree, concentrated mesh, crossbar, parallel subnets)
> beat it?

## The answer

**No — because the topology is not the bottleneck.** On the machines that actually run
transformers, the on-chip NoC is off the critical path in every regime we can find:

- **Prefill** is compute-bound (systolic/matrix unit saturated).
- **Decode** is DRAM-bandwidth-bound (arithmetic intensity ~1–2 FLOP/byte).
- The NoC sits between them with **comfortable headroom** and never binds.

So "which topology" is the wrong question to be optimising. The real levers are **memory
bandwidth, memory capacity, and the mapping** (chiefly: multicasting shared K/V between
cores to cut DRAM traffic — an optimisation Tenstorrent has publicly identified and not
yet shipped).

## Why this is settled — three independent anchors, same answer

| # | evidence | fabric | what it shows | artifact |
|---|---|---|---|---|
| 1 | Our cycle-accurate simulation (PyTorchSim → BookSim2 + Ramulator2) | **memory** fabric, TPU-class | topology moves EDP **inside** the model's own 1.37× error bar; the "mesh wins" mechanism was a measurement bug, not physics | [FINDINGS.md](FINDINGS.md) |
| 2 | Tenstorrent's **measured silicon** (arXiv 2603.23343) | **tile-to-tile** fabric, Wormhole | distance-minimising routing beats naive by ~15% at tiny scale, **negligibly** at real scale: "the network is so low latency that the naive pattern is sufficient" | [hw/wormhole_study_arxiv_2603.23343.txt](hw/wormhole_study_arxiv_2603.23343.txt) |
| 3 | Decode roofline on real Wormhole specs | both | decode binds on **DRAM** at FP32/BF16/BFP8 alike; the NoC has a 4× headroom and would only bind at <8 GB/s/link vs the real ~32 | [scripts/decode_roofline.py](scripts/decode_roofline.py) |

Two different networks, a vendor's tapeout, and a first-principles bound — all pointing
the same way. The result does **not** depend on our uncalibrated wire-energy constant or
on any validation gate we could not pass.

## The constructive half: where the NoC IS the lever

The negative result has a positive complement, and it falls straight out of the same
roofline. Decode is DRAM-bound and the NoC sits idle with headroom — so the NoC's value
is not its *shape*, it is spending that idle capacity to **cut the DRAM traffic that is
the bottleneck.** GQA hands you the opportunity: `g = n_q/n_kv` query heads share each
KV head, and the shipped kernel re-reads it from DRAM once per head instead of
multicasting it once over the network.

Modelled on a real deployment — **Llama-3-70B, 32K context, Tenstorrent QuietBox (8×
n300d, 192 GB, 4608 GB/s)**, batch capacity-limited to 11:

| | tokens/sec (aggregate) | per user |
|---|---|---|
| shipped (KV read 8× redundantly) | 50 | 4.5 |
| **K/V multicast over the idle NoC** | **269** | **24.4** |

**A 5.4× decode throughput gain at zero extra silicon** — the win a topology sweep could
never have found, because it comes from *using* the network, not reshaping it. See
[scripts/serving_multicast.py](scripts/serving_multicast.py) and
[scripts/multicast_savings.py](scripts/multicast_savings.py). Honest bounds: `g` is the
ceiling of the head-parallel mapping the vendor ships (context-parallelism reaches it a
different way); the win is a bandwidth gain, not a capacity gain; and it grows with
context, marginal at 8K, dominant at 128K.

## What is genuinely worth keeping

1. **[PITFALLS.md](PITFALLS.md) is the most valuable artifact in the track.** Fifteen
   distinct ways a NoC model produced plausible, confident, wrong numbers — each with
   the symptom, the cause, and the catch. Every headline figure was an artifact before
   it was a result, and the topology verdict flipped four times. The through-line:

   > **A NoC result that has not been calibrated against silicon is decoration** — and a
   > large *share* of a total (wires were 72% of NoC energy) is not the same as a large
   > *effect* (they moved the verdict by 1%).

2. **The double-anchored negative result itself.** "Topology is second-order for
   transformer accelerators" is a real, checkable contribution — more defensible than
   the topology ranking we set out to produce, precisely because it survived our own
   attempts to overturn it.

3. **The tooling, calibrated and reusable:** a radix-scaled router model at 1.37× of
   FlooNoC silicon ([floonoc_calibrate.py](scripts/floonoc_calibrate.py)), a floorplan
   that measures wire length from coordinates instead of guessing it
   ([floorplan.py](scripts/floorplan.py)), and a parsed-from-vendor Wormhole node census
   ([wormhole.py](scripts/wormhole.py)).

## What we are NOT claiming

- Not that topology *never* matters — only that it is not the binding constraint for
  **transformers** on **these** accelerators, at the scales tested.
- Not a silicon result. Simulation plus one calibrated router model plus published specs.
- Not that the crossbar is viable — it is dead beyond argument (O(radix²) energy, 6.97×
  the mesh). That part is unambiguous.

## If you still want to re-open it

There is exactly one honest way in, and it is narrow: find a transformer regime whose
arithmetic intensity is low enough, on a chip whose DRAM is fast enough, that the NoC
re-enters contention. [decode_roofline.py](scripts/decode_roofline.py) is the tool —
change the DRAM/NoC/compute numbers to your target chip and see if the binding column
ever reads `NoC`. On Wormhole it does not, with 4× to spare. Show it does somewhere
before building a topology sweep on top of it.

Everything else on the topology axis is closed. The door was checked three times; it is
shut.

---

*Full narrative in [PLAN.md](PLAN.md) (the pivot and the stop), the memory-fabric study
in [FINDINGS.md](FINDINGS.md), and the failure catalogue in [PITFALLS.md](PITFALLS.md).*
