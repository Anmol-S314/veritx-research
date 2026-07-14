# T3 — Every way this study lied to us, and how we caught it

Read this before trusting any NoC number, including ours.

Over one working session, **every single headline figure was an artifact before it was a
result**, and the topology verdict flipped **three times**. Not because the tools are bad
— because a NoC model has many places to hide a wrong constant, and all of them produce
plausible-looking output. What follows is each one, how it was caught, and what stops it
recurring.

The pattern is consistent enough to state as a rule:

> **A NoC result that has not been calibrated against silicon is decoration.** Every
> uncalibrated number we produced was wrong, and each was wrong in a way that looked
> completely reasonable.

---

## 1. "Routers are 95% of the die" — a hardcoded CSV constant

**Symptom.** `area_report.py` reported routers at 95% of die area. Alarming, and it
became the framing for the whole project.

**Cause.** Accelergy's `isaac_router` has exactly **one row**:

```
technology,global_cycle_seconds,width|datawidth,energy,area,action
32nm,1e-9,256,20.74,150000,read
```

150,000 µm², flat. It does **not vary with radix, flit width, or buffer depth**. Every
router in the report read `150000.00` because the estimator has no model — it is a lookup.
Worse, ISAAC itself *shares one router across four tiles* (`isaac_router_shared_by_four.csv`,
37,500 µm²), so we were paying 4× even on the plugin's own terms.

**Fix.** Build the router from primitives: `crossbar` (O(radix²)) + one `regfile` input
buffer per port. Area now responds to topology, which is the entire point of the study.

**Catch it next time.** If a component's area is identical across configurations that
should differ, you are reading a constant, not a model. Print per-component area and look
for suspiciously round numbers.

## 2. The denominator was a toy

The 95% was also a *denominator* problem: the arch had **16 MACs total**. Eyeriss has 168
PEs; a TPU has 65,536 MACs. With a realistic compute tile the NoC share collapses —
FlooNoC's 12nm silicon puts the NoC at **3.5% of a compute tile**.

**Catch it next time.** Sanity-check the compute against a real chip before believing any
"X% of die" ratio.

## 3. Mixed process nodes in one ratio

`TECH = {"regfile": 45, "intmac": 45, "SRAM": 45, "isaac_router": 32}` — routers priced at
32nm, everything else at 45nm, because the shipped backends do not overlap. **Any ratio
across them is apples-to-oranges.** It was documented in the script and still fed a
headline number.

## 4. Placeholder traffic presented as a result

`timeloop_to_matrix.build_traffic_matrix()` shipped a **ring pattern with a hotspot** and a
docstring saying so. 147 rows of `topology_sweep.json` were generated from it. Topology
comparisons under synthetic traffic are meaningless; the traffic *is* the experiment.

**Fix.** Replaced with an output-stationary spatial model derived from Timeloop's actual
per-tensor DRAM counts. Then abandoned the whole pipeline for PyTorchSim, which does it
properly with a memory model.

## 5. The mapper does not optimize what you think

The GlobalBuffer sweep showed 512 kB performing **worse** than 256 kB (16× re-fetch vs 8×).
Not noise — `mapper.yaml` says:

```yaml
optimization-metrics: [energy, delay]
```

**Timeloop was never minimizing DRAM traffic.** It found a mapping that wins on energy/delay
while doubling DRAM reads. Any traffic claim from that sweep is a *side effect* of an
energy search, not a result.

**Catch it next time.** Read the optimization target before interpreting any metric the
optimizer was not told to care about.

## 6. `flit_size` is in BYTES, not bits

We swept flit sizes 32 / 128 / 512 expecting a bandwidth effect. Got ±1.6% — flat. Built an
entire "link width is the untested lever" theory on it.

**Cause.** BookSim (`Interconnect.cpp:221`):

```c
int num_flits = (pkt_size / flit_size) + ((pkt_size % flit_size) ? 1 : 0);
```

`pkt_size` is **bytes** and TOGSim's DRAM requests are **32 bytes**. At `flit_size = 32`
every packet is already **one flit**. Widening further cannot reduce flit count. *The
variable was pinned.* The sweep tested nothing.

This also propagated into the energy model as `FLIT_BITS = 32` when the flit is 32 **bytes**
= 256 bits — all absolute pJ were **8× low**. (Ratios survived, since every run used the
same flit size.)

**Catch it next time.** Before sweeping a parameter, verify it *moves something*. One cheap
run at each extreme, checking an intermediate quantity (here: flits per packet).

## 7. Validate configs on a 30-second workload, not a 30-minute one

Two sweeps were burned discovering config bugs that a short run would have caught in
seconds:

- `routing_function = dor` is valid for a mesh (`dor_mesh`) but **does not exist for a
  torus** — BookSim composes `<routing>_<topology>`, and only `dim_order_torus` exists.
- An `anynet` torus **deadlocks**: wrap-around links create cyclic channel dependencies and
  plain `min` routing has no dateline/VC avoidance.

**Fix.** `validate.sh` runs every config against `test_matmul.py` (~30 s) before any
`test_transformer.py` (~30 min) is queued. This is the highest-leverage habit in the whole
project.

## 8. Torus deadlocks inside PyTorchSim — but not in BookSim

Even with **native** `topology = torus`, correct `dim_order` routing, and 4 VCs, the torus
wedges inside TOGSim. But `sanity_test.py` runs the *same topology* in bare BookSim fine
(`torus8x8 latency=55.39`).

**Conclusion:** TOGSim's BookSim wrapper does not honour the dateline VC partitioning that
`dim_order_torus` requires. **Upstream bug, not ours.** The torus arm of the comparison is
blocked by someone else's code. Worth filing.

## 9. One log interval is not a measurement

Systolic utilization read **0.00%** in the interval we happened to inspect, which looked
like the GEMMs were not using the matrix units at all — a finding that would have
invalidated everything.

It was a LayerNorm interval. Across **all** intervals: systolic peaks at **84%** on the
`addmm` kernels. The rig was healthy the entire time.

**Catch it next time.** Aggregate across the whole run before concluding anything from a
periodic stat.

## 10. Uniform-random traffic is the wrong distribution

The energy model assumed uniform-random destinations → 5.25 mean hops on an 8×8 mesh.

**The traffic is strictly bipartite.** From `Simulator.cc:237`, requests go to DRAM nodes
(32–63) and replies to compute nodes (0–31). **There is no compute-to-compute traffic.**
Every packet crosses between the halves — which on a row-major mesh means crossing the
midline too. True mesh hops: **6.625**. A 26% error.

And it *inverts* the fat-tree story: compute and DRAM sit in different level-2 subtrees, so
every packet climbs to the root — exactly 6 hops, always, which is **shorter** than the
mesh. We had confidently written "the fat-tree does not save hops." Wrong.

**This moved EDP from 1.01× to 0.88× — it flipped the verdict.**

## 11. ~~Router-only energy models flatter long-link topologies~~ — **RETRACTED**

**This entry was wrong, and it is kept because being wrong twice about the same number is
the most instructive thing in this file.**

It claimed: the energy model priced routers only; adding wires showed they are 71–86% of
NoC energy, showed the fat-tree travels **4.2× farther**, and moved EDP 0.88× → **1.84×**,
flipping the verdict back to the mesh. We wrote "hops are not distance" and called it the
single most important lesson here.

**What is actually true.** Wires *are* ~72% of NoC energy — that part survives. But they
are **inert**. Sweep the wire constant from its published maximum (0.4 pJ/bit/mm) down to
**zero** and the fat-tree's EDP moves 0.92× → 0.93×. A router-only model flatters the
fat-tree by **one percentage point**, not by a verdict.

The reason is arithmetic. The fat-tree's *router* energy is 1.67× the mesh's; its *wire*
energy is 1.64×. Two nearly equal ratios — so **any blend of them lands in the same
place.** There was never a wire-vs-router story to tell.

**What actually flipped the verdict was §11b: a wrong ruler.** Wires were the scapegoat. We
found a real 72% and told ourselves a causal story about it that a thirty-second
sensitivity sweep would have refuted — if we had swept the constant instead of the die
size (§14).

**Catch it next time.** A large *share* is not a large *effect*. Before attributing a
result to a term, set that term to zero. If the answer does not move, that term is not the
mechanism, however much of the total it accounts for.

## 11b. The path length was hand-waved, and it decided everything

**Symptom.** The mesh won on EDP by a comfortable 1.95×, with a beautiful mechanism: the
fat-tree takes fewer hops (6.00 vs 6.62) but travels **4.2× farther** (105.5 mm vs 25.0 mm),
because its compute↔DRAM path climbs to a root that spans the die.

**Cause.** Nobody ever measured that 105.5 mm. `hop_distance_pitches()` *guessed* it:

```python
if topo == "fattree":
    k, n = 4, 3
    # a level-L link reaches a switch serving k^L leaves, which occupy a
    # sqrt(k^L)-wide patch of floorplan, so the link spans ~sqrt(k^L) pitches
    return 2 * sum((k ** L) ** 0.5 for L in range(1, n + 1))   # = 28 pitches
```

28 pitches × 3.767 mm = 105.5 mm. Plausible-sounding, entirely invented.

Give all 64 nodes real (x, y) coordinates and **measure** the route — on the *identical*
8×8 grid, same pitch, nothing else changed:

| | formula claimed | measured | |
|---|---|---|---|
| mesh | 25.0 mm | 25.0 mm | ✅ exact |
| fat-tree | 105.5 mm | **41.4 mm** | **2.5× overcount** |
| fly | 15.1 mm | **30.1 mm** | **2× undercount** |

The `fly` error is the tell, and it is embarrassing: a packet goes source → central router
→ destination. That is **two** legs. The formula counted **one**.

**This single number carried the entire headline.** Fix it and the fat-tree's energy falls
3.50× → 1.65×, and prefill EDP goes 1.95× → 0.92× — from "the mesh wins decisively, and
here is the mechanism nobody stated" to "it is a wash."

**Fix.** `floorplan.py`: every node gets coordinates, every path is walked and its links
summed. No topology gets a bespoke formula.

**Catch it next time.** A quantity produced by a closed-form expression that no test pins
against an independent computation is a guess wearing a lab coat. The mesh's formula
happened to be right, which made the other two look trustworthy by association.

## 11c. The nodes are not tiles — the question that cracked it open

Asked *"why are we talking about bisection bandwidth in a tiled architecture like a TPU?"*,
the model had no good answer — because the premise was false.

The 64 NoC nodes are **not 64 compute tiles**. From the config: `num_cores: 2`,
`icnt_injection_ports_per_core: 16`, `dram_channels: 32`. So:

- nodes 0–15 are **sixteen injection ports of ONE core**
- nodes 16–31 are core 1's
- nodes 32–63 are **DRAM channels** — in silicon, PHYs at the die edge

The energy model priced all 64 as compute-sized tiles on an 8×8 grid at a 3.767 mm pitch.
The DRAM half alone was therefore charged **454 mm² of silicon** for what is really a
~60 mm² edge strip, doubling the die in y.

**The irony:** this error was *second-order* — it moved the mesh path 25.0 → 26.0 mm. But
chasing it is what forced us to stop hand-waving link lengths and measure them, which is
how §11b was found. The wrong question found the right bug.

**Catch it next time.** When someone asks why a metric applies and the answer is "because
the topology has 64 nodes", go and look at what the 64 nodes *are*.

## 12. The autotuner runs a simulation per candidate — and it starves on hard configs

The sub-32B flit sweep timed out at 4 B and 8 B and never reached 16 B. It looked like
network congestion: narrow flits, saturated mesh, simulation can't finish. A tidy story.

**It was the compiler.** `codegen_mapping_strategy: autotune` runs a *simulation per
candidate mapping*, with a 15-second per-trial cap. With multi-flit packets every trial is
2–8× slower, so they all blow the cap, retry, and the **compile phase grinds for 40 minutes
before the real run even starts.** Zero kernels, no deadlock warning, nothing in the log but
autotune spam.

**Fix.** `codegen_mapping_strategy: heuristic` picks a mapping with no trial simulations.
The sweep then completes in minutes.

**The trap inside the fix.** Heuristic changes the *mapping*, and a different mapping is a
different experiment. Heuristic-32B runs **861,964** cycles against autotune-32B's
**719,178** — ~20% slower. Splicing a heuristic 16 B run against the autotuned 32 B baseline
would have inflated the apparent width effect by 20% and it would have been reported as
physics. Every flit size had to be re-run under the same strategy.

**Catch it next time.** When a run stalls, check whether it has *started simulating*
(`[TOGSim] Running simulation:`) before blaming the thing you are studying. A compile-phase
stall and a congested network look identical from the outside — and the compile-phase story
was the one that flattered our hypothesis.

## 13. A sensitivity sweep of the wrong variable is worse than none

We reassured ourselves — in print, in FINDINGS — that the verdict "survives a 12×
tile-pitch sweep, which is the only reason we trust it."

That sweep was **vacuous**. Every path length in the model is linear in the tile pitch, so
every *ratio* is scale-invariant and the sweep is flat **by construction**. It could not
have failed. It was equally flat under the old, wrong model — and we read that flatness as
robustness.

The variable that actually needed sweeping was the one we never touched: the wire constant
(§11). One sweep of it would have exposed the whole story a day earlier.

**Catch it next time.** Before running a sensitivity sweep, ask what result would make it
*fail*. If you cannot describe one, the sweep proves nothing — and a flat line will be
misread as confirmation.

## 14. Our one silicon anchor did not anchor what we thought

`floonoc_calibrate.py` passes at **1.37× of FlooNoC's 12nm silicon**, and that was cited as
the reason to trust the energy model. But FlooNoC's paper, §VI-D:

> "the **routers only** consume 596 pJ during the transfer, resulting in an energy
> efficiency of 0.15 pJ/B/hop."

**Routers only.** So the calibration anchors the *router* — and says nothing about the
*wires*, which by then were carrying 72% of our energy. We had exactly one external check
in the entire pipeline and were quietly applying it to the wrong term.

We got away with it only because of §11 (wires are inert). That is luck, not method.

**Catch it next time.** When you calibrate against a published figure, read what it
*measures*, not what it is *named*. "pJ/B/hop" sounds like a whole-NoC number. It is not.

*(Useful by-product: applying our wire model to FlooNoC's own floorplan — their compute
tile is 1.5 × 0.75 mm — says wires would be 66–94% of their NoC's energy. Their headline
figure omits the majority of their own interconnect's power, and it is widely quoted as if
it were the whole thing.)*

---

## The verdict flipped four times

| model | fat-tree EDP | verdict |
|---|---|---|
| routers only, uniform-random hops | 1.01× | wash |
| routers only, **real bipartite** hops | 0.88× | fat-tree wins |
| routers + wires, **hand-waved** path lengths | 1.84× | mesh wins |
| routers + wires, **measured** path lengths (§11b) | **0.92× / 1.24×** | **wash — fat-tree takes prefill, loses decode** |

Each correction was a genuine bug. Each changed the sign. **Three of the four flips were
caused by the same quantity — how far a packet physically travels — and we never measured
it until the fourth.**

The current model is the first one whose verdict does *not* depend on an uncalibrated
constant: sweep wire energy from 0 to 0.4 pJ/bit/mm and EDP moves 0.01×. That, and not any
sensitivity sweep we ran earlier, is the reason to trust it.

And the margin is thin enough to say plainly: with the router model sitting 1.37× from
silicon, an 8% EDP gap is **inside our own error bar**. "The fat-tree wins prefill" is not a
claim this study supports. It is a wash.

## What actually saved us

1. **Calibration against silicon.** FlooNoC publishes 0.15 pJ/B/hop from a 12nm tapeout.
   Rebuilding *their* router in our model and scaling gives 0.206 — **1.37×**. It is a
   `--selfcheck` that fails if the model regresses past 2×. But see §14: it anchors the
   router *only*, and we spent a day believing it anchored more than that.

2. **The stale-image guard.** Accelergy's `dummy` estimator answers **1 µm² to every query**
   and Accelergy falls back to it **silently, exit 0**. `check_estimators()` refuses to run
   if `dummy_tables` is present. It caught a stale image mid-session that would otherwise
   have produced a plausible, entirely fabricated table.

3. **Selfchecks that pin claims, not code.** Not "does this function run" but "does the
   fat-tree still take fewer hops than the mesh", "is crossbar energy still quadratic in
   radix", "is the calibration still within 2× of silicon". These fail loudly when a
   *conclusion* breaks, which is what you actually want.

4. **Measuring instead of deriving.** `floorplan.py` gives every node coordinates and walks
   every route. It replaced three closed-form guesses, two of which were wrong — one by
   2.5×, and that one decided the headline. Where a quantity can be *computed from a model
   of the thing itself*, do that, and keep the closed form only as a test.

5. **A stranger's naive question.** "Why are we talking about bisection bandwidth in a tiled
   architecture like a TPU?" had no good answer, because the premise was false — the nodes
   are not tiles (§11c). Every other check in this list was one we designed to pass.

## And what did NOT save us

**Sensitivity sweeps.** We ran them, we published their flatness as evidence, and they were
worthless: the swept variable could not have changed the answer (§13). A sweep is only
evidence if you can say in advance what outcome would falsify the claim.

**The one external check we had.** It was measuring a different quantity than we thought
(§14).

Four sign flips, and not one of them was caught by the safeguards we had built. They were
caught by measuring something we had previously assumed, every single time.
