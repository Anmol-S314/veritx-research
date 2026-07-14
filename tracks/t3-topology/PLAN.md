# T3 — Plan: move the study to the network that actually exists

**Status:** proposed. Nothing here is run yet.
**Prerequisite reading:** [PITFALLS.md](PITFALLS.md). This plan is shaped almost
entirely by the failures recorded there, and it should be read as a response to them.

---

## 1. What went wrong, in one paragraph

We spent two days sweeping NoC topologies on PyTorchSim/TOGSim. Its interconnect
carries **only memory traffic** — `Simulator.cc` pushes into the network in exactly
two places, core→DRAM (line 142) and DRAM→core (line 168), and a grep for
`core_to_core`, `peer`, `collective`, `allreduce` across all of TOGSim returns
nothing. There is no tile-to-tile path, and `num_cores: 64` would not create one.

So every result in [FINDINGS.md](FINDINGS.md) describes a **memory fabric** (compute
ports ↔ HBM channels) on a 2-core TPU. That is a real question and the numbers are
real. It is **not** the question the NoC-topology literature asks, and it is not the
question we thought we were asking. Worse, we were calibrating against FlooNoC — a
288-core **tile-to-tile** chip — as though the two networks were the same thing.

## 2. ❶ vs ❷ is a FALSE DICHOTOMY — Phase 0 killed it

*This section replaces the original framing. Phase 0 ran, and it refuted the premise
the rest of this plan was built on. Kept visible rather than rewritten away.*

The plan opened by splitting the world into ❶ a *memory fabric* (compute↔DRAM, what we
had measured) and ❷ a *tile fabric* (tile↔tile, what we proposed to measure), and
proposed abandoning ❶ for ❷. **On the real chip there is only one fabric, and it
carries both.** From tt-metal, describing the RISC cores inside every Tensix:

> "RISC0 and RISC1 are capable of issuing NoC transfers to move data from
> **L1 ↔ L1 and L1 ↔ DRAM**."

One NoC. Both traffic types. And the node census (`scripts/wormhole.py`, parsed from
the vendor's own SoC descriptor) shows why the split was never physical: the 18 DRAM
endpoints sit in **interior columns x=0 and x=5**, with column 5 running straight down
the middle of the Tensix array. Memory is not off to one side of the network — it is
*embedded in it*.

**Worse for the original plan: on a real transformer kernel, the DRAM traffic
dominates.** Tenstorrent's own SOTA FlashAttention implementation:

> "Our FlashAttention kernel **reads Q, K, and V from DRAM and writes the output to
> DRAM**. On each core, the reader kernel will read a chunk of Q and then iterate over
> the chunks of K and V. Intermediate results ... are stored in L1 until all KV chunks
> are processed, then the output is written to DRAM."

Every core works on its own Q chunk, independently. There is **essentially no
tile-to-tile traffic in the shipped kernel at all.** And they say so explicitly:

> "One Wormhole feature that **this work did not take advantage of is multicasting**.
> Tensix cores can issue multicasts over the NoC to efficiently ... transfer data to
> any other core. **Multi-query attention is a good use case** ... We could **reduce
> total DRAM traffic** by using multicasting to share K and V heads between groups of
> cores."

So the tile-to-tile path is not the main event — it is an **unexploited optimisation
that the vendor has publicly identified and not yet implemented.**

**This vindicates the ❶ work rather than discarding it.** Bipartite compute↔DRAM
traffic is not the wrong question; it is the *dominant* traffic pattern on a real
tiled accelerator running a real transformer kernel. What was wrong was the *machine*
(a 2-core TPU with edge DRAM), not the *traffic*.

## 3. The question, restated

> A transformer on a tiled accelerator generates a **mix** of DRAM↔L1 traffic and
> L1↔L1 traffic, and the mix is set by the mapping — most sharply by whether K/V are
> **multicast** between cores or re-fetched from DRAM per core.
>
> **How does the optimal NoC topology depend on that mix?** And is the mesh still the
> right default once the traffic stops being purely bipartite?

This is a better question than either version we had:

- It is **the vendor's own open problem**, stated in their tech report.
- The knob (multicast ratio) is a **real, single-parameter axis** that moves traffic
  continuously from ❶-like to ❷-like — so we sweep it rather than guessing where on it
  reality sits.
- It uses **both halves** of what we have built: the bipartite work is the α=0 endpoint.
- Nobody has run it. The 2026 literature (WaferLLM, WATOS, TileLoom, MOCAP) optimises
  mappings *onto a fixed mesh*; nobody asks how topology preference moves with the mix.

**Why the answer could genuinely differ from FINDINGS.md.** Topology preference follows
traffic shape:

| traffic | governing metric | mesh's advantage |
|---|---|---|
| pure DRAM↔L1 (α=0, today's kernel) | bisection bandwidth | **wire-optimal** — DOR traverses exact Manhattan distance |
| multicast K/V (α→1, the optimisation) | multicast + reduction cost | *unclear — this is the study* |

Multicast and reduction are exactly the patterns where trees and rings beat meshes: a
mesh all-reduces in O(√P) hops, a torus does a ring all-reduce, a fat-tree reduces in
O(log P). **The wire-optimality result — the one thing we actually proved — does not
obviously survive contact with multicast traffic.** That is a stateable mechanism for a
flip, which is the bar a hypothesis has to clear.

## 4. Target machine: Tenstorrent Wormhole

Not Cerebras (900k cores — unsimulable), not Groq (closed). **Wormhole**, because:

- It is a **production transformer accelerator** with public documentation
  (`tt-metal`, including a FlashAttention tech report).
- Its NoC is a **2D torus** with **two independent unidirectional NoC planes**
  (NOC0 / NOC1, opposite directions), row-first dimension-order routing.
- It is ~80 Tensix cores — **simulable in BookSim2** at full scale, unlike a wafer.
- There is a measured-hardware paper to validate against
  ([arXiv 2603.23343](https://arxiv.org/abs/2603.23343), *Numerical Kernels on a
  Spatial Accelerator: A Study of Tenstorrent Wormhole*).

**The two arms TOGSim blocked us on are exactly what this chip ships.** The torus
(which deadlocked in TOGSim's wrapper) and parallel NoC planes (which TOGSim silently
pinned to `subnet = 0`) are not speculative — they are Tenstorrent's shipped design.
And two *unidirectional* planes is precisely the standard way to avoid the cyclic
channel dependency that deadlocked our bidirectional torus. Our "bug" was the
literature telling us the answer.

**Built-in reality check.** Tenstorrent spent real money choosing torus + 2 planes over
a mesh. If our model concludes the plain mesh beats it, the most likely explanation is
that **our model is wrong**, not that Tenstorrent is. That gives this study something
the last one never had: an external result we can be *wrong against*.

### Phase 0 result — DONE, and it moved the plan (`scripts/wormhole.py --selfcheck`)

Parsed from the vendor's SoC descriptor, vendored at `hw/wormhole_b0_80_arch.yaml`.
**All 120 NoC nodes classified; the selfcheck asserts none are unaccounted for.**

| | count | where |
|---|---|---|
| NoC grid | **10 × 12 = 120 nodes** | *not* 8×10 — that is only the Tensix subset |
| Tensix workers | **80** | x ∈ {1,2,3,4,6,7,8,9}, y ∈ {1–5, 7–11} |
| **DRAM endpoints** | **18** | **columns x=0 and x=5 — INTERIOR** (6 banks × 3 endpoints, 12 GiB, 288 GB/s) |
| Ethernet | 16 | rows y=0 and y=6 |
| ARC / PCIe / router-only | 1 / 1 / 4 | column x=0 |

- **Topology:** 2D **torus** (wraparound), **two unidirectional NoC planes** (NOC0/NOC1,
  opposite directions) — tt-metal `METALIUM_GUIDE.md`.
- **Routing:** row-first dimension-order (X then Y).
- **L1:** 1,464 KiB × 80 = **114 MiB on-chip**.

**Two findings that cut against our own assumptions:**

1. **DRAM is in interior columns, not an edge strip.** Column 5 splits the Tensix array
   into two 4-wide halves. `floorplan.py` models TPU DRAM as an edge PHY strip — correct
   for a TPU, **wrong here**. It cannot be reused for Wormhole without re-derivation.
   (This is PITFALLS §11c catching itself *before* the study instead of after.)
2. **One fabric carries both traffic types** — see §2. The premise of this plan was wrong
   and Phase 0 is what caught it.

⚠️ **Gate 4 is now at risk.** The FlashAttention report's performance numbers are in a
*figure* (`image3.png`), not a table — there is nothing extractable to validate against.
Gate 4 must instead come from arXiv 2603.23343 (measured Wormhole kernels). **If that
paper has no extractable per-kernel numbers either, Gate 4 cannot be met and §11 says
stop.** Resolve this before Phase 1, not after.

### Phase 0b result — DONE, and it is a red light

I read arXiv 2603.23343 (*Numerical Kernels on a Spatial Accelerator: A Study of
Tenstorrent Wormhole*) end to end. It is the best-matched external anchor that exists,
and it says, repeatedly and from measurement, that **the NoC is not the bottleneck.**

Three independent statements, all measured on silicon:

1. **Reduction collective, communication granularity** (§5.1): sending full tiles vs
   pre-reduced scalars through the NoC differ by **1.8% at the largest scale.** Cutting
   network traffic barely moves the wall clock.
2. **Reduction collective, routing pattern** (§5.2, Fig. 6): the "center" pattern that
   *minimises distance travelled* beats the naive left-then-up pattern by ~15% at 1
   tile/core, and by a **negligible** margin at 128 tiles/core. Their own words: *"the
   network is so low latency that the naive pattern is sufficient for larger problem
   sizes."* **Routing/topology stops mattering as the problem grows.**
3. **Stencil (nearest-neighbour exchange)** (§6): *"The local compute is much more
   expensive than the communication, demonstrating the strength of the Wormhole NoC."*

For the study this is close to fatal, and I am not going to soften it:

- **Gate 2 is what actually failed, not Gate 4.** Gate 2 asks whether the NoC is even on
  the critical path. This paper is direct silicon evidence that for the collective and
  reduction kernels — *the exact multicast/reduce traffic the α-sweep is built to
  study* — **it is not.** The compute (SFPU FP32, high latency) dominates. A topology
  that changes NoC energy/latency by 2× would move end-to-end performance by single-digit
  percent, and that swamps our 1.37× model error.
- This is the **same shape of result as FINDINGS.md**, arrived at from the opposite
  direction and on the right machine: topology is a second-order knob for transformers.
  We found it for the memory fabric; Tenstorrent's own numbers show it for the tile
  fabric too.

**One caveat that keeps a door open.** Their FP32 compute is on the SFPU, which they say
is ~6× slower than the FPU and "high latency". Transformer inference runs in **BF16/BFP8
on the FPU**, which is ~6× faster — so compute shrinks and the NoC's *relative* share
grows. It is *possible* the NoC matters at low arithmetic intensity (decode: tiny GEMMs,
huge KV reads) even though it does not for these FP32 scientific kernels. But that is a
hope, not an anchor, and I will not build a study on it without a number.

**Verdict: Gate 4 as designed cannot be met** (a NoC-topology prediction cannot be
validated against a machine whose own authors show the NoC is off the critical path),
**and Gate 2 is in serious doubt.** Per §11, this is a stop-and-reassess point, not a
proceed. See "Decision" at the end.

## 5. What we already own

| piece | status |
|---|---|
| Cycle-accurate NoC, full topology sweep | **BookSim2 standalone works** — `sanity_test.py` runs `torus8x8 latency=55.39` |
| Router energy model | **calibrated 1.37× vs FlooNoC 12nm silicon** |
| Wire lengths | `floorplan.py` — measured from coordinates, no hand-waved rulers |
| Transformer workload knowledge | two days of it |

**Dropping TOGSim is a simplification, not a rebuild.** It deletes both blocking bugs
(torus deadlock, `subnet = 0`) because both live in TOGSim's BookSim *wrapper*, not in
BookSim. And FlooNoC — a tile-to-tile chip — finally becomes the *correct* calibration
anchor rather than a borrowed one.

The only missing piece is **the traffic**.

## 6. The traffic model — and the danger

**PITFALLS §4 is literally "placeholder traffic presented as a result."** We shipped a
ring-with-a-hotspot traffic matrix and reported topology comparisons from it. This plan
requires hand-building a traffic matrix **again**. That is the single largest risk here
and no amount of care makes it zero.

What is different — and it has to be substantive, not rhetorical:

1. **The traffic is derived, not invented.** Tile-to-tile traffic for a transformer on
   a 2D grid is *determined* by the parallelisation strategy. It is not a free
   parameter. A tensor-parallel GEMM's communication is a closed form.
2. **The mapping is published.** We take it from `tt-metal`'s FlashAttention tech
   report and TileLoom's `flashattn` / `mqa_decode` spatial mappings — and we **cite**
   them rather than inventing our own.
3. **It must pass the gates in §8 before it is allowed to produce a topology claim.**

We will **not** consume TileLoom as a library: it is an MLIR compiler, not a
simulator. Its `NetworkModule` "records affine placement" and it emits no traffic
matrix — grepping its tree for `traffic`/`packet`/`noc.*volume` returns zero files. It
also needs a full LLVM build. We use it as a *specification of the dataflow*, which is
what it is good for.

*(Note: `loom-dataflow`'s README claims it is a submodule of `github.com/anthropics/loom`,
which is implausible for an NUS project. Treat its provenance as unverified; rely on
the paper, not the repo.)*

## 7. The methodological trap that would sink this

**A fixed mapping run on every topology is a rigged comparison.**

If we derive one mapping (say, mesh-optimal: row multicast, column multicast, neighbour
reduce) and then run *that same traffic* on a torus and a fat-tree, we are measuring
"torus executing mesh-optimal code." That is not the torus's best. Real designs co-design
the mapping with the topology — a torus wants a **ring all-reduce**, a fat-tree wants a
**tree reduce**. TileLoom's entire thesis is that dataflow planning is topology-dependent.

This cuts in a specific direction, and we should exploit it rather than hide it:

> A fixed mesh-derived mapping **biases the result toward the mesh.**

Therefore the study can only produce a **strong** conclusion in one direction:

- **If a torus/fat-tree wins despite running mesh-optimal traffic** → strong result. The
  bias was against them and they won anyway.
- **If the mesh wins under mesh-optimal traffic** → **weak, near-circular.** We may not
  report it as "the mesh is best." We must either re-map per topology, or report the
  mesh's win as *conditional on the mapping* and say so in the headline.

This asymmetry gets written into the plan **now**, before we know the answer, so it
cannot be quietly forgotten if the numbers come out the convenient way. That is exactly
the failure mode of PITFALLS §11 — a real observation (72% wire energy) turned into a
causal story that a 30-second sweep would have refuted.

## 8. Validation gates — no topology claim before these pass

Each gate has an explicit failure condition. **A gate that cannot fail is not a gate**
(PITFALLS §13: we published a 12× sensitivity sweep that was flat *by construction*).

**Gate 0 — geometry.** Pin Wormhole's actual grid, node composition, and routing from
`tt-metal` docs. *Fails if:* we cannot say exactly what the 80-odd NoC nodes are.
(This is PITFALLS §11c — "the nodes are not tiles" — applied before, not after.)

**Gate 1 — volume.** Total bytes in the generated traffic matrix must match a
hand-derived closed form for the mapping, to the byte. *Fails if:* they differ. Catches
the entire ring-with-a-hotspot class of error.

**Gate 2 — the variable moves.** Mesh link utilisation under the traffic must be
non-trivial (target >10%). *Fails if:* the network is idle — then the experiment cannot
detect a topology effect at all and we would be sweeping a **pinned variable**
(PITFALLS §6, the `flit_size`-in-bytes disaster).

**Gate 3 — independent re-derivation.** Two implementations of the traffic model — one
closed-form analytical, one from an execution trace of the mapping — must agree.
*Fails if:* they disagree by >5%.

**Gate 4 — external anchor.** Reproduce a *published* Wormhole number (from
arXiv 2603.23343 or the `tt-metal` FlashAttention report) within a stated tolerance.
*Fails if:* we cannot predict the mesh/torus baseline that real silicon produced.

> **Gate 4 is the one that matters.** Every previous safeguard in this track — the
> calibration, the selfchecks, the sensitivity sweeps — was something we designed to
> pass. Not one of the four verdict flips was caught by them. They were all caught by
> measuring something we had assumed. Gate 4 is the first check with an owner who does
> not want us to succeed.

## 9. Phases

| phase | work | cost | exit |
|---|---|---|---|
| **0** | ✅ **DONE.** Wormhole geometry, node census, topology, routing. Gate 0 passes. | — | `scripts/wormhole.py --selfcheck` |
| **0b** | **Can Gate 4 be met at all?** Find extractable measured numbers (arXiv 2603.23343). | hours | a real number to be wrong against — **or stop** |
| **1** | Traffic model for FlashAttention on the 80-Tensix grid, with a **multicast ratio α**: α=0 is the shipped kernel (all K/V from DRAM), α=1 is full K/V multicast between cores. Gates 1–3. | 1–2 days | traffic matrix that survives all three gates, at both endpoints |
| **2** | Drive BookSim2 standalone. **Torus + 2 planes** (what the chip *is*) as baseline. Gate 4. | 1 day | we can predict a measured Wormhole number |
| **3** | **Sweep α × topology.** mesh / torus / fat-tree / cmesh / fly × subnets {1,2,4}. Energy: Accelergy routers + a **re-derived** Wormhole floorplan (§ Phase 0 finding 1). | 1–2 days | *does the optimal topology move as α moves?* |
| **4** | Prefill vs decode at the α that each regime implies (decode/GQA is where multicast pays — the vendor says so). | 1 day | does topology preference invert between regimes? |
| **5** | Falsification: for every mechanism claim, zero the term and check the claim dies. | hours | no claim survives that a null test would kill |

Phase 5 is not optional and not last-if-there's-time. It is the direct response to the
fact that our headline mechanism ("wires dominate") turned out to be **inert** — a 72%
share with a 1% effect.

## 10. Pre-registered predictions

Written down **before** running, so they can be wrong in public (PITFALLS: we are prone
to post-hoc storytelling that flatters whatever we just found).

1. **Topology preference moves with α.** At α=0 (pure DRAM↔L1, today's kernel) the
   traffic is bipartite and the mesh's wire-optimality should hold, reproducing
   FINDINGS.md. As α→1 (K/V multicast between cores) the traffic becomes multicast +
   reduce, and **the mesh should lose ground to the torus.** Predict a **crossover at
   some α\*** — and *finding that α\* exists and where it sits is the result.*
2. **Torus beats mesh at high α.** Ring all-reduce, wraparound links that are one pitch
   long in a folded layout, no die-spanning wires. Predict **EDP < 1.0** vs mesh once
   multicast dominates.
3. **Subnets ≈ 2 is close to optimal.** Tenstorrent shipped 2. Predict a knee at 2 with
   sharply diminishing returns at 4 — bisection doubles at constant wire length and
   constant radix, but injection bandwidth becomes the limit.
4. **Multicast reduces total NoC energy, not just DRAM traffic.** The vendor claims it
   cuts DRAM traffic; predict it also cuts NoC energy, because one multicast tree
   replaces N independent DRAM fetches that each cross the array.
5. **The crossbar stays dead.** O(radix²) is not survivable at any traffic shape.
6. **The mesh does not win outright at every α.** If it does, suspect the fixed-mapping
   bias (§7) before believing it.

**Prediction 1 is the study.** If α\* does not exist — if the mesh wins across the whole
range — then the mesh really is the right default under every traffic shape a transformer
produces, and the topology axis is closed for good. That is a *publishable negative
result*, but only because Gate 4 would give us the right to assert it.

And note what makes this falsifiable in a way the last study never was: **at α=0 we must
reproduce our own bipartite result, and at the torus+2-planes point we must reproduce a
chip Tenstorrent actually shipped.** Two independent anchors, neither of which we control.

## 11. What would kill this, and when to stop

- **Gate 4 fails and cannot be fixed.** If we cannot reproduce a real Wormhole number,
  we do not have a model of a tiled accelerator and nothing downstream is reportable.
  **Stop.** Do not "adjust constants until it matches" — that is how you build a model
  that agrees with everything and predicts nothing.
- **Gate 2 fails.** The NoC isn't the bottleneck for this workload/mapping, so topology
  cannot matter. That is itself a finding, and a much cheaper one than the sweep.
  Report it and stop.
- **The mesh wins under a mesh-optimal mapping (§7).** Weak result. Either invest in
  per-topology mapping or downgrade the claim honestly. Do not ship it as a verdict.
- **Time.** This is a ~1 week plan with five gates. If Gate 4 has not passed by the end
  of Phase 2, the remaining phases are not worth starting.

## 12. What this study will not claim

- Not a new topology. We are testing existing ones under a traffic shape nobody has
  tested them under.
- Not silicon. Simulation, with one calibrated router model and one measured floorplan.
- Not a general result about "AI accelerators". It is a result about **tiled spatial
  accelerators running transformers**, at Wormhole scale, under a published mapping.
- Not a claim about the memory fabric. That was the last study, it is in FINDINGS.md,
  and it stands on its own narrower terms.

---

## DECISION (after Phase 0 + 0b)

**Do not proceed to Phase 1 as written.** The gating logic that was pre-committed in §11
now fires:

- Phase 0 showed the ❶/❷ split is a false dichotomy — one fabric, both traffic types,
  DRAM interior — so the *reframing* to a multicast α-sweep was the right correction.
- Phase 0b then showed, from measured silicon (arXiv 2603.23343), that **on the very
  collective/reduction kernels the α-sweep targets, the NoC is off the critical path.**
  Their own conclusion: "the network is so low latency that the naive pattern is
  sufficient." That is Gate 2 failing, and Gate 4 has no extractable NoC-bound number to
  anchor to.

Pre-committing the stop condition was the point. The convenient move is to run the
sweep anyway — we have every piece — and report a topology ranking. But a ranking on a
fabric that measured silicon says is not the bottleneck is exactly the "decoration"
PITFALLS opens by warning against. **The discipline is to honour the gate we wrote when
we did not yet know it would hurt.**

### What survives, and is worth writing up

The **negative result is now double-anchored and genuinely interesting:**

> On-chip NoC topology is a second-order knob for transformer accelerators — shown
> independently for the **memory fabric** (our PyTorchSim study, FINDINGS.md) and the
> **tile-to-tile fabric** (Tenstorrent's own measured Wormhole kernels). Both point the
> same way: the mesh/torus is a fine default, and the interesting levers are elsewhere
> (memory capacity/bandwidth, mapping, multicast to cut DRAM traffic — not graph shape).

That is a real contribution and it is *more* defensible than the topology-sweep would
have been, precisely because it does not depend on our uncalibrated wire model or on a
Gate 4 we cannot pass.

### The one open door, stated as a testable condition, not a hope

Every measured "NoC doesn't matter" result in 2603.23343 is **FP32 on the SFPU**, which
the paper itself says is ~6× slower than FPU BF16. Real inference is BF16/BFP8 on the
FPU. **Decode** specifically has tiny GEMMs and huge KV reads — the lowest arithmetic
intensity in the whole workload. So the falsifiable question that remains is:

> Is there a transformer regime (BF16/BFP8 decode) whose arithmetic intensity is low
> enough that the NoC returns to the critical path?

That is answerable **without** a topology sweep — a single roofline calculation places
decode against Wormhole's NoC and compute bandwidths and tells us if the NoC is even in
contention. If it is not, the topology axis is closed for transformers, full stop, and
we have shown it twice. If it is, *that* regime — and only that one — earns the sweep.

**Recommended next step: the roofline, not Phase 1.** Hours, not a week. It either closes
the track with a strong two-anchor negative result or it identifies the single regime
that justifies the full study. Either outcome is worth more than a sweep we already have
reason to disbelieve.
