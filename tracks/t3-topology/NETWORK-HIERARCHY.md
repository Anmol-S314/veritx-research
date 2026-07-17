# Where NoC topology matters — the network hierarchy

Companion to [CONCLUSION.md](CONCLUSION.md). That doc closed **one rung**: the
**on-chip** NoC. This doc places that result in the full hierarchy of networks in
an AI system, and marks where the topology question is *still open* — because the
"topology is second-order" verdict is **specific to the bottom rung and inverts as
you climb.**

---

## The ladder

| Level | Network | Medium | Topology matter? | Why |
|---|---|---|---|---|
| **On-chip** | NoC (cores ↔ cores, one die) | on-die wires | **No — second-order** | NoC has ~4× headroom; memory/compute bind first. Wires cheap + uniform. |
| **Chip-to-chip** | scale-up fabric (e.g. 8× n300 in a box) | short copper / Ethernet | **Beginning to** | Link costs stop being uniform; a real (small) hierarchy appears. |
| **Node / pod** | rack interconnect | copper / short optics | **Yes** | Links scarce; collectives cross the boundary. |
| **Pod-to-pod / datacenter** | the DC network | **long-haul optics** | **First-order — decisive** | Links expensive + scarce; network is the bottleneck; traffic is collective-heavy. |

## Why the on-chip verdict inverts as you climb

Every property that made topology *not* matter on-chip reverses at scale:

1. **Links go from free to expensive.** On-chip wires are cheap and uniform. Pod-to-pod,
   every link is an **optical transceiver** — costly, power-hungry, radix-limited.
   Hierarchical topologies (fat-tree, dragonfly) exist *specifically* to economize these
   expensive links; that premise is absent on-chip and dominant at scale.
2. **The network becomes the bottleneck.** On-chip the NoC had headroom (memory/compute
   bound first). At datacenter scale for **training**, gradient all-reduce across thousands
   of chips can be **30–50% of wall-clock** — communication-bound, so topology sets throughput.
3. **Traffic goes collective-heavy.** On-chip traffic is local/bipartite (mesh-optimal).
   Cross-pod it's **all-reduce / all-to-all** (data-parallel gradients, MoE routing) — the
   global-bandwidth pattern fat-tree/dragonfly were built for.

## What's actually used at each level

- **On-chip:** 2D mesh / torus. Tenstorrent Wormhole: 2D torus + two unidirectional NoC
  planes (deadlock-free, 2× bandwidth). Settled; richer shapes cost more for no gain
  ([CONCLUSION.md](CONCLUSION.md)).
- **Chip-to-chip (scale-up):** short-reach mesh/torus of chips over Ethernet-class links.
- **Pod / datacenter (scale-out):**
  - **Fat-tree / Clos** — dominant datacenter-AI-training fabric (Meta, Google, NVIDIA SuperPOD).
  - **Dragonfly** — HPC supercomputers (HPE/Cray Slingshot); minimizes long global cables.
  - **Rail-optimized** — GPU clusters wire each NIC to a dedicated rail, tuned for all-reduce.
  - The **collective algorithm co-designs with the shape**: ring all-reduce on a torus,
    tree / halving-doubling on a fat-tree, hierarchical across tiers.

## Training vs inference — a nuance that matters for us

"Topology is first-order at scale" is strongest for **training** (communication-bound).
For **inference** (our whole decode/KV discussion) it's more situational:

- A model usually fits within a **node/box**, so a single request rarely crosses pods.
- Cross-pod traffic is mostly **replica serving** (embarrassingly parallel — little
  inter-pod communication) **or** **disaggregated prefill/decode** (prefill and decode on
  separate pools, streaming KV between them — *this* does stress the inter-pod fabric).

So pod-to-pod topology is **decisive for training, situational for inference** — big only
if the serving architecture deliberately spreads a request across pods.

---

## The open problem — and an honesty gate before we chase it

The on-chip rung is **closed**. The **inter-chip / scale-out** rung is where the topology
question is live *and* where richer topologies earn their keep. That is the direction with
real headroom. **But "open for us" ≠ "unpublished," and this track's rule is to check that
before investing** (the on-chip study's entire value turned out to be its failure catalogue,
not a positive result).

**Prior-art reality check — do this first, it is the gate:**

- **Datacenter topology for training is saturated.** Fat-tree vs dragonfly vs rail-optimized
  for large-model training is extensively published by hyperscalers and HPC. A generic
  "which topology for scale-out training" study is **not novel** and will not clear a
  literature review. Do not start here.
- **The on-chip K/V-multicast angle is already taken.** NoC-multicast for shared K/V is
  published (FlatAttention). See [[t3-prior-art-landscape]]. Our on-chip multicast result is
  a *validation*, not a first.
- **The only defensible slice is narrow and must be verified novel:** *inference-serving*
  scale-out — specifically **disaggregated prefill/decode**, where KV streams between pools —
  and whether the optimal inter-pod topology shifts when you exploit **cross-chip K/V
  multicast / sharing**. That connects our one real asset (the multicast finding) to the one
  rung that isn't closed. It may still be occupied; **a prior-art pass is Gate 0.**

**Validation gates (same discipline as [PLAN.md](PLAN.md)):**

- **Gate 0 — novelty.** A prior-art pass finds no published study of *inference-serving,
  disaggregated, KV-multicast-aware* scale-out topology. *Fails if it's occupied — then stop.*
- **Gate 1 — the bottleneck is real.** A roofline (extend [decode_roofline.py](scripts/decode_roofline.py))
  shows the *inter-chip* fabric actually binds for the target serving setup. *Fails if the
  fabric has headroom too — then topology is second-order here as well, and that is the finding.*
- **Gate 2 — traffic is derived, not invented.** Cross-pod KV/activation traffic comes from a
  published serving architecture, not a hand-built matrix (PITFALLS §4).
- **Gate 3 — external anchor.** Reproduce a measured collective/serving number before
  predicting a topology ranking.

**Recommended first step: Gate 0 + Gate 1 — a day, not a project.** A prior-art pass plus one
inter-chip roofline either kills it cheaply or identifies the single narrow question worth a
full study. Either outcome beats building a sweep we have reason to disbelieve — which is
exactly the mistake this track already made once, on-chip.
