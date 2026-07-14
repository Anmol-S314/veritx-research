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

## 2. The question, stated properly this time

> On a **tiled spatial accelerator** running a transformer — the Cerebras / Groq /
> Tenstorrent class of machine, where compute tiles talk to *each other* over a
> packet-switched NoC — **is the 2D mesh the right topology?**

Every current system either assumes a mesh or ships one, and the 2026 literature
(WaferLLM, WATOS, TileLoom, MOCAP) optimises *mappings onto a mesh* rather than
asking whether the mesh is right. Nobody runs a cycle-accurate topology sweep with a
calibrated energy model on this network for this workload.

## 3. Why the answer might genuinely differ from what we found

This is not the same experiment relabelled. The **traffic is a different shape**, and
topology preference follows traffic shape.

| | ❶ memory fabric (what we measured) | ❷ tile fabric (what we propose) |
|---|---|---|
| traffic | strictly **bipartite** compute↔DRAM | **broadcast + reduce** between tiles |
| governing metric | bisection bandwidth | reduction latency/energy, multicast cost |
| mesh's advantage | wire-optimal: DOR = exact Manhattan distance | *unclear — this is the question* |

A tensor-parallel GEMM on a P×P grid multicasts activations along rows, weights down
columns, and **reduces partial sums**. Decode is even more extreme: broadcast a tiny
query vector to every tile holding a KV-cache slice, then reduce the partial attention
outputs. Broadcast and reduction are exactly the patterns where trees and rings beat
meshes — a mesh does an all-reduce in O(√P) hops where a torus does a ring all-reduce
and a fat-tree reduces in O(log P). **The mesh's wire-optimality argument, which is
the one thing we proved, does not obviously survive contact with reduction traffic.**

So there is a real mechanism by which the answer could flip, and it is stateable in
advance. That is the bar a hypothesis has to clear.

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

⚠️ **To verify in Phase 0, not to assume:** the exact grid. Sources disagree between
"8×10 Tensix" and "10×12 grid containing 64 Tensix plus DRAM/Ethernet/ARC nodes". If
the latter, the NoC carries **both** tile-to-tile *and* tile-to-DRAM traffic on one
fabric — which would mean our ❶ work is not discarded but becomes the memory half of a
more complete model. Do not write a line of traffic code before this is pinned.

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
| **0** | Pin Wormhole geometry + routing from `tt-metal`. Gate 0. | hours | grid, node types, routing written down and cited |
| **1** | Traffic model for one tensor-parallel GEMM on a P×P grid. Gates 1–3. | 1 day | traffic matrix that survives all three gates |
| **2** | Drive BookSim2 standalone, mesh only. Gate 4. | 1 day | we can predict the published mesh number |
| **3** | The sweep: mesh / **torus** / fat-tree / cmesh / fly / **subnets 1,2,4**. Energy from Accelergy + `floorplan.py`. | 1–2 days | EDP table, with torus and subnets arms alive for the first time |
| **4** | Prefill (GEMM multicast) vs decode (broadcast+reduce). The interesting split. | 1 day | does topology preference invert between regimes? |
| **5** | Falsification: for every mechanism claim, zero out the term and check the claim dies. | hours | no claim survives that a null test would kill |

Phase 5 is not optional and not last-if-there's-time. It is the direct response to the
fact that our headline mechanism ("wires dominate") turned out to be **inert** — a 72%
share with a 1% effect.

## 10. Pre-registered predictions

Written down **before** running, so they can be wrong in public (PITFALLS: we are prone
to post-hoc storytelling that flatters whatever we just found).

1. **Torus beats mesh on decode.** Decode is broadcast+reduce; a torus does ring
   all-reduce in ~P hops with no long wires and wraparound links that are one pitch
   long in a folded layout. Predict **EDP < 1.0** vs mesh.
2. **Subnets ≈ 2 is close to optimal.** Tenstorrent shipped 2. Predict a knee at 2 with
   sharply diminishing returns at 4 — bisection doubles at constant wire length and
   constant radix, but injection bandwidth becomes the limit.
3. **Fat-tree wins prefill but loses decode**, as in ❶ — its reduction advantage is
   offset by long die-spanning links.
4. **The crossbar stays dead.** O(radix²) is not survivable at any traffic shape.
5. **Mesh does not win outright.** If it does, suspect the fixed-mapping bias (§7)
   before believing it.

Prediction 1 is the study. If it fails, the mesh really is the right default for both
networks and the topology axis is closed for good — which is a publishable negative
result *only because* Gate 4 gives us the right to assert it.

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
