# T3 — What the topology study actually found

**Status:** prefill + decode measured on a 64-node NoC. The topology verdict is a
**wash, not a win for either side** — and getting to that took correcting six
separate model bugs, four of which changed the sign of the answer. Read
[PITFALLS.md](PITFALLS.md) before trusting anything here, including this file.

**Headline:**

> On a TPUv3-class accelerator, **no topology beats the 2D mesh by enough to
> matter.** A fat-tree buys 1.80×/1.33× performance (prefill/decode) for 1.65× the
> NoC energy: EDP **0.92× in prefill** (inside our own model error) and **1.24× in
> decode** (a real loss, in the regime that dominates production inference). The
> crossbar is dead beyond argument at 6.97× energy.
>
> The mesh is not *optimal*. It is **not beatable by enough to justify the
> switch** — which is a weaker claim than we spent a day believing, and it is the
> one the numbers actually support.

We previously claimed the mesh wins outright on a wire-energy mechanism. **That
was wrong** — it rested on a hand-waved fat-tree path length that overcounted by
2.5×. See PITFALLS §11/§13.

---

## Setup

| | |
|---|---|
| Simulator | PyTorchSim (MICRO 2025) → BookSim2 + Ramulator2 |
| Hardware | TPUv3-class: 2 cores × 2 systolic 128×128, HBM2, 32 DRAM channels |
| NoC | 64 nodes = 2 cores × 16 injection ports + 32 DRAM channels |
| Prefill workload | BERT-base encoder block — 12 heads, d_model 768, seq 512, fp32 |
| Decode workload | LLAMA-4 TP8 GQA decode, 10,240-token KV cache |
| Area/energy | Accelergy (Aladdin crossbar + regfile), radix-scaled |
| Floorplan | `floorplan.py` — measured coordinates, not assumed tile pitches |

Only `booksim_config_path` changes between runs. Same TOG, same mapping, same memory.

**Why TPUv3 and not v4/v7:** it is the *only* config PyTorchSim ships with
`icnt_type: booksim2`. The TPUv4 configs use `simple_noc`, a fixed-latency model
with no topology, so a topology sweep cannot run on them at all. This is the
single biggest open threat to the result — see "What is still soft".

### What is calibrated, and what is not

| quantity | anchor | status |
|---|---|---|
| Router energy | FlooNoC 12nm silicon, 0.15 pJ/B/hop | **1.37×** — PASS |
| Hop length | FlooNoC compute tile 1.5 × 0.75 mm, scaled 12nm→45nm | **0.93×** — PASS |
| Speedups | measured by the simulator | not a model at all |
| Wire energy (0.1 pJ/mm/bit) | **nothing** | uncalibrated — **but inert, see §2** |

FlooNoC's 0.15 pJ/B/hop is explicitly *routers only* ("the routers only consume
596 pJ during the transfer", §VI-D). So it anchors our router and says nothing
about our wires — a distinction we missed for most of the study.

---

## 1. Performance tracks bisection bandwidth

Prefill (BERT encoder block), cycles:

| topology | routers | bisection | cycles | vs mesh |
|---|---|---|---|---|
| fly (64-way crossbar) | 1 | unbounded | 303,850 | **2.37× faster** |
| fat-tree (4-ary, 3-level) | 48 | 128 | 400,147 | **1.80× faster** |
| **mesh 8×8** | 64 | 16 | 719,178 | 1.00× |
| cmesh (c=4) | 16 | **8** | 1,388,109 | **1.93× slower** |

Monotonic in bisection. The DRAM column shows the mechanism — the mesh *starves
the memory system*: 19.2% utilization versus 38% on the fat-tree.

**Concentration is actively harmful.** cmesh halves the bisection (8 links vs 16)
and runs ~1.9× slower, DRAM collapsing to 10.2%. It cuts hop count, which does not
help.

These are the most trustworthy numbers in the file: they come out of the
simulator, not out of a model we wrote.

## 2. Energy — and the wire constant turns out not to matter

Energy per delivered flit (256-bit flits), routers **and** wires, with all path
lengths **measured from `floorplan.py` coordinates**:

| topology | radix | hops | path mm | router pJ | wire pJ | wire % | total | vs mesh |
|---|---|---|---|---|---|---|---|---|
| mesh | 5.0 | 6.62 | 26.0 | 255.9 | 664.5 | 72.2% | 920.4 | 1.00× |
| fat-tree | 6.7 | 6.00 | 42.7 | 427.7 | 1092.9 | 71.9% | 1520.6 | **1.65×** |
| fly | 64.0 | 1.00 | 32.8 | 5578.4 | 839.0 | 13.1% | 6417.4 | **6.97×** |

Wires are ~72% of NoC energy. **And it makes no difference whatsoever.** Sweeping
the (uncalibrated) wire constant across the entire published range for repeated
on-chip RC wires — 0.08–0.4 pJ/bit/mm — and beyond, down to *zero*:

| pJ/mm/bit | wire share | fat-tree energy | prefill EDP | decode EDP |
|---|---|---|---|---|
| **0.00** (routers only) | 0% | 1.67× | 0.93× | 1.26× |
| 0.05 | 57% | 1.66× | 0.92× | 1.25× |
| 0.10 (ours) | 72% | 1.65× | 0.92× | 1.24× |
| 0.20 | 84% | 1.65× | 0.92× | 1.24× |
| 0.40 | 91% | 1.65× | 0.92× | 1.24× |

The verdict is **invariant**. The arithmetic is why: the fat-tree's router energy
is 1.67× the mesh's and its wire energy is 1.64×. Two nearly equal ratios, so any
blend of them lands in the same place. This is pinned as a selfcheck — if it ever
fails, the wire constant has become load-bearing and must be calibrated before
anything is published.

**This retracts a claim we made loudly.** We previously reported that adding wires
flipped the verdict (EDP 0.88× → 1.84×) and that "router-only energy models
systematically flatter long-link topologies." They do not — a router-only model
gives 0.93× against the full model's 0.92×. It flatters the fat-tree by *one
percentage point*. What actually flipped the verdict was a wrong path length.

**Hops are still not distance** — just not by nearly as much as we said. The
fat-tree takes fewer hops (6.00 vs 6.62) and travels **1.64×** farther (42.7 mm vs
26.0 mm). We previously claimed 4.2×, from a formula that guessed a level-L link
spans √(4ᴸ) tile pitches. Measured on the identical grid, that overcounted 2.5×.

## 3. The one thing that is provable

**Dimension-order routing on a mesh traverses exactly the Manhattan distance
between source and destination.** That is the shortest path any wire can take.
Every other topology hauls the packet through an intermediate switch, so it can
only be longer.

**The mesh is wire-optimal by construction.** No rewiring beats it on distance —
only on hops and radix. The fat-tree does exactly that, and in prefill it is
almost worth it. This is asserted in `floorplan.py --selfcheck`.

## 4. The verdict splits by regime

Decode (LLAMA-4 TP8, 10,240-token context):

| topology | cycles | DRAM | systolic peak | **VPU peak** |
|---|---|---|---|---|
| mesh | 98,128 | 19.8% | 1.6% | **62%** |
| fat-tree | 73,725 | 26.1% | 1.6% | **100%** |
| fly | 59,050 | 33.1% | 1.6% | **100%** |

Systolic utilization is **1.6%** here (vs 84% in prefill) — genuinely memory-bound,
not a relabeled experiment.

**The mesh is NoC-bound; the fat-tree is VPU-bound.** On the mesh the vector unit
idles at 62%, starved by the network. The fat-tree saturates it at 100% — the
bottleneck moves from the fabric to the compute. That is a hard ceiling, which is
why the crossbar's unbounded bisection buys only 1.66× here versus 2.37× in
prefill.

So richer topologies buy **less** in decode while their energy penalty is unchanged:

| topology | NoC energy | prefill speed | EDP | decode speed | **EDP** |
|---|---|---|---|---|---|
| mesh | 1.00× | 1.00× | 1.00× | 1.00× | 1.00× |
| fat-tree | 1.65× | 1.80× | **0.92×** | 1.33× | **1.24×** |
| fly | 6.97× | 2.37× | 2.94× | 1.66× | **4.20×** |

**Do not over-read the 0.92×.** Our router model sits 1.37× from silicon. An 8%
EDP margin is well inside that error bar, so "the fat-tree wins prefill" is *not*
a claim this study can support. Prefill is a **wash**. The 24% decode loss is
larger than the error bar and is the more defensible half of the result.

## 5. Link width matters only until a packet fits in one flit

BookSim's `flit_size` is in **bytes**, and TOGSim's DRAM requests are 32 bytes. The
axis has a knee at exactly 32 B.

**Above the knee — nothing.** Every packet is already a single flit; widening
cannot reduce flit count. 719,178 / 713,695 / 729,691 cycles at 32/128/512 B —
±1.6%, noise. *This sweep moved a variable that was pinned* (PITFALLS §6).

**Below the knee — cycles scale with flits per packet:**

| flits/pkt | flit | cycles | vs 1-flit | DRAM util |
|---|---|---|---|---|
| 1 | 32 B | 861,964 | 1.00× | 16.8% |
| 2 | 16 B | 1,551,350 | **1.80×** | 9.5% |
| 4 | 8 B | 2,914,938 | **3.38×** | 5.0% |
| 8 | 4 B | ≥5,012,330 ‡ | **≥5.81×** | 2.7% |

One `heuristic`-mapping series throughout, so every row is comparable.
‡ the 4 B run reached 17 of 18 kernels inside the 1500 s cap — a **lower bound**.

Growth is consistently **sublinear** against the ideal 2×/4×/8×. The DRAM column is
the mechanism: each request occupies the network N× longer, so memory idles N× more.

**Independently reproduced:** a separate `autotune` series gives 3.42× at 4
flits/packet against 3.38× here — two mapping strategies, same scaling law.

**Runtime scales with flit count, not with bits.** The shipped 32-byte flit sits
exactly at the knee: no headroom above, real cost below. Width is not an available
lever for this traffic.

This also resolves the apparent contradiction with FlooNoC, whose whole thesis is
512-bit links. Wide links are better **when there is a packet big enough to fill
them.** FlooNoC moves large DMA bursts; a 32-byte DRAM request cannot use a
64-byte flit.

## 6. Memory capacity is a bigger lever than any of this

Timeloop sweep of GlobalBuffer size against DRAM traffic, 768×768 attention
projection:

| GB (kB) | DRAM reads (B) | B re-fetch |
|---|---|---|
| 32–256 | 4,718,592 | **8.00×** |
| 512 | 9,437,184 | 16.00× *(worse — see PITFALLS §5)* |
| 1024 | 589,824 | **1.00×** |

**A step function, not a curve.** Nothing helps until the 576 kB weight matrix
*fits*; then DRAM traffic collapses 7×. Buying 256 kB is pure waste. No topology
fixes this.

---

## What is still soft

- **TPUv3 is a 2018 chip, and it is the only one we can test.** PyTorchSim ships
  BookSim only on the v3 config; v4 uses `simple_noc` (no topology). TPUv7 does not
  exist in the tool at all. The whole result is one point in a design space whose
  most important axis — bytes/FLOP — has moved by an order of magnitude since v3.
  **A TPUv4-with-BookSim config is a ~5-line change and is the highest-value next
  experiment.** v4 doubles systolic arrays per core (2→4) and raises DRAM clock
  28%, i.e. *more* compute per byte, i.e. *more* NoC pressure — which should push
  the fat-tree further ahead. Untested.
- **The wire constant is uncalibrated.** Currently inert (§2), so this is not
  load-bearing — but it becomes load-bearing the moment the router/wire energy
  ratios stop coinciding, e.g. at a different radix or die size.
- **Torus is missing.** Deadlocks inside TOGSim's BookSim wrapper; runs fine in
  bare BookSim (`sanity_test.py`: `torus8x8 latency=55.39`). Upstream bug.
- **Subnets is untested, not refuted.** `Interconnect.cc` hardcodes `subnet = 0`,
  so BookSim builds N networks and TOGSim uses one. The one idea that could buy
  bisection at constant wire length has never actually run. ~20 lines of C++.
- **Hops are modeled, not BookSim-measured.** BookSim tracks `_hop_stats`
  internally; TOGSim never prints them.
- **Simulation only, no silicon.**

## What this is not

It is not a new topology, and it is no longer a clean negative result about
topology either. The defensible claims are narrow:

1. Performance tracks bisection bandwidth, monotonically, and that is measured.
2. The mesh is wire-optimal by construction (provable).
3. Nothing on the topology axis beats it by more than the error bars — in the
   regime that matters (decode), the fat-tree loses by 24%.
4. Crossbars are dead: O(radix²) is not survivable.

The most valuable output of this track is probably [PITFALLS.md](PITFALLS.md), not
this file.
