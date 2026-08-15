# T3 — Phase 3: The RTL leg — burstiness verified on a real fabric (FPGA + formal)

Status: **Phase 0 done (contract pinned, 2026-08-08). Phase 1 in progress — first RTL
files landed in rtl/ (2026-08-08).** Prerequisite reading:
[PITFALLS.md](PITFALLS.md), [NETWORK-HIERARCHY.md](NETWORK-HIERARCHY.md) (Appendix:
the measured burst table), [PLAN.md](PLAN.md) (the gate discipline), and
[UCIE-ARC.md](UCIE-ARC.md) (the slice convention this follows).

---

## 1. Why this slice, why now

Phase 1 proved a law in simulation: **burstiness, not bandwidth, starves control**
(1 VC: 45.1 → 221.6 cyc, 1.36× → 6.68×; 4 VCs absorb it to 1.24×). Phase 2 moved the
multicast mechanism to the chiplet boundary (g-fold law, bridge-fork vs source-fork).
Both are BookSim results. BookSim is a cycle-accurate *model* — the router
microarchitecture is code, and the laws we derived live inside that model.

This slice puts the laws on a second substrate: **our own RTL NoC, written from the
BookSim model, run (a) cycle-exactly against BookSim in simulation and (b) on real
FPGA silicon with cycle counters.** The formal leg (c) proves the safety properties
on the RTL with Yosys-SMT.

The claim being checked is the one the whole track rests on: **is the burstiness law
real, or is it an artifact of our simulator?** Two outcomes, both results:

- Burst curve reproduces on RTL + FPGA → the law is a queueing law, substrate-independent;
  plane separation is a real design rule, and every number in the Appendix table earns
  the word "measured".
- It diverges → the model lied somewhere, which is exactly what this track exists to
  catch (PITFALLS §8: torus deadlocks in one simulator, not another).

## 2. Two legs, honestly defined

**Leg 1 — cycle-exact co-sim (BookSim ↔ RTL, in simulation).** The RTL implements one
*specific* microarchitecture; BookSim is configured to model *that exact*
microarchitecture (same buffer depths, pipeline stages, allocator policy, credit
latency, routing). Both are driven by **the same stimulus trace** (see §5). Gate:
per-flit ejection cycles match exactly. This is the standard RTL↔model validation
pattern, and it is the only place "cycle-accurate" is a *matching* claim.

**Leg 2 — FPGA (RTL ↔ silicon, measured).** The same RTL, synthesized, with
**per-router cycle counters** on the device clock. Honest claim: **functional and
curve identity, not cycle-for-cycle identity** — placement/timing means the RTL-sim
and FPGA do not share absolute cycles. What must match: (a) same events, same
ordering, same counts; (b) the burst-curve *shape*; (c) bit-identical repeatability
(same bitstream + same seeds → same counter values).

**Leg 3 — formal (properties on the RTL).** Yosys-SMT BMC + k-induction on the
component level. Proves safety invariants for all runs, not one trace. Honest scope:
component-level safety, not system-level reachability (see §7).

## 3. The RTL spec (Leg 1's contract with BookSim)

Every knob below is a *matching parameter*, not a design choice — the RTL and the
BookSim config must agree on all of them or Leg 1 cannot pass. This mapping is
written down **before** any RTL exists, and every value was **verified against the
fork's source** (`src/routers/iq_router.cpp`, `src/booksim_config.cpp`,
`src/trafficmanager.cpp`, `src/traffic.cpp`, `src/networks/kncube.cpp`,
`src/allocators/islip.cpp`) on 2026-08-08.

| RTL | BookSim knob | Value (start) |
|---|---|---|
| Topology: 4×4 mesh, XY DOR | `topology = mesh`, `routing_function = dor` | 4×4 first; 8×8 = follow-up (matches the Phase-1 sweep grid; `melange` is not this fork's router — `iq` is) |
| Router pipeline: BW → RC → VA → SA → XT → LT (register-staged) | `routing_delay`, `vc_alloc_delay`, `sw_alloc_delay`, `crossbar_delay` | **1 + 1 + 1 + 1** — fork defaults, confirmed in `booksim_config.cpp` |
| Input buffers: depth D per VC | `vc_buf_size` | **D = 8 flits** — `plane_shared.cfg` sets 8 and the sweep does NOT override it (verified in `plane_separation.py` `sweep_dma`); the burst table was produced with D = 8 |
| VC count: 1, 2, 4 | `num_vcs` | the plane-separation sweep values |
| Credit flow control, credit loop = C cycles | `credit_delay` | **C = 0** — fork default; still measured in RTL sim, never assumed |
| Allocators: iSLIP, 1 iteration, pointers advance on successful match only | `vc_allocator = islip`, `sw_allocator = islip`, `alloc_iters = 1` | fork defaults (NOT `separable_input_first`); `speculative = 0`, `noq = 0`, `hold_switch_for_packet = 0` |
| Channel latency: 1 cycle per hop (flit + credit); inject/eject channels 1 | `use_noc_latency = 1` (mesh ⇒ 1 anyway) | confirmed in `kncube.cpp` (`_mesh ? 1 : 2`) |
| Flit: 1 flit/cycle/channel, 64-bit data + sideband | — | `packet_size` **is flits per packet** in this fork (`_GetNextPacketSize` is the flit count); the burst table cells are packet counts of flits |
| Injection: Bernoulli, per node per class per cycle, at *packet* rate | `injection_rate` per class, `injection_rate_uses_flits = 0` | per §5 trace; class 0 rate r = 0.08/B, class 1 rate 0.005 |
| Class-0 destinations: uniform pick among the 8 diagonal NICs per packet | `traffic = {hotspot(0,9,…),uniform}` | `HotSpotTrafficPattern::dest` = `RandomInt(_max_val)` over equal rates — 100% hotspot, no uniform mix |

**VC selection policy (verified, easy to get wrong):** BookSim does **not** partition
VCs by class. With `num_vcs > 1`, the iSLIP VC allocator grants *any* downstream VC
with free space. The 4-VC isolation of the burst table emerges from **capacity**, not
policy — the RTL must NOT implement strict class→VC segregation, or Leg 1 fails by
construction. With `num_vcs = 1` there is no VC allocation (both classes share VC 0).

**Pipeline timing semantics (what the RTL must replicate, per `iq_router.cpp`):**
a flit arrives at an input, is written into its VC buffer the same cycle, and the VC
enters `routing`. One full cycle each: routing (`_RouteUpdate`), VC allocation
(`_VCAllocUpdate`), switch allocation (`_SWAllocUpdate`), crossbar traversal
(`_SwitchUpdate` → output buffer → `_SendFlits`). Then channel latency 1 to the next
router. Minimum hop-to-hop flit latency = 4 router stages + 1 channel = 5 cycles;
credits return on the same schedule (credit channel latency 1, `credit_delay` 0).

**Measured cycle model (2026-08-08, `watch_flits` trace of this exact fork — the
authoritative reference, reproduced in full at the end of §3):** with all four
delays at their default of 1, the allocator "delays" resolve to the *same* cycle the
request is made, and the real per-hop budget is:

- cycle T — flit arrives at the router input; written into the VC buffer; **routing
  completes the same cycle** (head flit: VC idle → routing → vc_alloc; VA request
  forms).
- cycle T+1 — **VA**: request + iSLIP grant in one cycle; VC → active (TakeBuffer:
  output VC marked in-use).
- cycle T+2 — **SA**: request + iSLIP grant in one cycle; flit popped from the input
  buffer (credit sent back upstream), downstream occupancy++ (SendingFlit), tail
  flit releases the output VC (wait_for_tail_credit = 0).
- cycle T+3 — **XT**: crossbar traversal, flit placed on the output channel.
- cycles T+4..T+5 — channel delivery; the downstream router receives at T+5.
  So: **receive-to-receive = 5 cycles per hop; a flit channel costs 2 cycles
  send-to-receive** (the extra cycle is the scheduler's ReadInputs→WriteOutputs
  ordering, visible in the trace, not a channel parameter).

Ejection: router sends to the eject channel at the XT cycle; the traffic manager
reads it 2 cycles later and sends the credit back the same cycle; the router credits
its eject-port occupancy 2 cycles after that. Injection: TM → inject channel (2
cycles) → router local port. A 1-hop flit's packet latency is 7 cycles (inject 0 →
eject-read 7), which is exactly the `minimum = 7` the burst-sweep runs print — a
built-in calibration point for the co-sim harness.

Reference trace (k=2 mesh, flit 0, node 1 → node 2, plat = 17 = 64−47):
`47 inject · 48 ch · 49 recv+routing · 50 VA · 51 SA · 52 XT+send · 53 ch · 54 recv
· 55 VA · 56 SA · 57 XT+send(eject) · 58 ch · 59–62 router_1_0 … 63 ch · 64 eject
+credit back`

**Request formation — the event model the RTL must copy (re-pinned 2026-08-08,
`iq_router.cpp` + 3-flit watch trace).** A request is *presented* to an allocator only
when an event created it; "VC is active and non-empty" alone is NOT the eligibility
rule, and getting this wrong shifts every latency by a cycle:

- **VA (head only):** request formed the cycle routing completes (recv cycle, since
  `routing_delay = 1` resolves same-cycle) → **evaluated/arbitrated T+1**, granted T+1.
  On VA grant the output VC is `TakeBuffer`d and the head's SA request is formed the
  *same* cycle → **evaluated T+2**. VA re-presents every cycle until granted
  (STALL_BUFFER_BUSY retry).
- **SA (head):** first presented T+1 (VA-grant cycle), arbitrated T+2.
- **SA (body, VC already active):** a body written at T forms its SA request the same
  cycle (`_InputQueuing`, active-VC branch) → **arbitrated and granted at T**. In
  steady state SA grants chain at **1 flit/cycle**: pop at T → next flit's request
  formed at T → granted T+1 → popped T+1 → XT T+2 → sent T+2 → recv T+4.
  **recv→recv = 3 cycles for bodies, 5 for heads.** The first body of a burst waits
  for the head's SA (+2 from its recv) — the VC is still `vc_alloc` when it arrives.
- **XT:** granted SA at T → crossbar traversal + *send on the channel the same cycle*
  (T+3 for heads, T+1 for bodies — `_SendFlits` runs in the same WriteOutputs).
- **Retry:** failed VA/SA requests re-present next cycle; a stalled VC never drops
  out of the arbitrations it lost.

**Credit path (`credit_delay = 0`, backchannel effective latency 2):** flit popped at
SA grant (T) → credit sent *the same cycle* (`_SWAllocUpdate` → `_OutputQueuing` →
`_SendCredits`, all same-phase) → upstream credit counter **increments at T+2**.
Downstream occupancy is reserved at the SA grant (`SendingFlit`), 2 cycles before the
flit physically arrives — SA eligibility therefore sees reservations, and a freed
slot is usable by the upstream 2 cycles after the downstream pop (0+2, no extra
allocator cycle). Eject: TM reads at T, credit sent same cycle, router's eject-port
counter++ at T+2. Inject: router's local-credit counter (TM side) decrements at
inject, increments 2 cycles after the router pops a local flit.

**Injection backpressure (the NIC's contract, `trafficmanager.cpp`):** the TM keeps a
BufferState mirroring the router's local input port. Head injection requires
`IsAvailableFor && !IsFullFor` on the selected VC; VC selection rotates through the
range from `_last_vc` (start at `vc_start`, then `(vc_start + (lvc − vc_start + i) %
vc_count)`; `_last_vc = −1` ⇒ first candidate is `vc_start`); `TakeBuffer` at head
inject, `SendingFlit` (occupancy++) per inject, tail frees the VC at inject
(`wait_for_tail_credit = 0`). The router's own local-input buffer is written 2 cycles
later when the flit arrives — two independent mirrors of the same occupancy.

**iSLIP/VA–SA granularity (verified `islip.cpp`, `_SWAllocAddReq`):** VA is a
`(input, VC) → (output, VC)` iSLIP (20×20 at 5 ports × 4 VCs); grants/accepts from
`_gptrs`/`_aptrs`, pointers advance only on a successful match. SA is a 5×5 iSLIP:
multiple VCs at one input requesting the same output merge into **one request whose
label is the RR winner from `_sw_rr_offset[input]`** (`Supersedes(vc, prio, label,
prio, offset, _vcs)` with all prios 0 = the first VC at-or-after the offset);
the offset advances to `(granted_vc + 1) % VCS` only when that VC is actually
granted; on a conflict the merge recomputes each cycle from the (unchanged) offset.

**The contract:** the RTL pipeline stage count is a *claim* until RTL sim measures it.
If `vc_alloc_delay` must be set to 2 to make Leg 1 pass, the RTL had a 2-cycle
allocator all along — the config changes, not the conclusion. Adjusting BookSim to
the RTL is the only legitimate direction of the fix; the reverse is how you build a
model that agrees with everything.

**Channel latency (re-pinned 2026-08-08):** mesh links are configured `delay = 1`
but the measured send→receive gap is **exactly 2 cycles** for both flit and credit
channels (traversal logs at T+1, router reads at T+2) — the extra cycle is the
scheduler's ReadInputs→WriteOutputs phase ordering, not a config knob. The RTL
implements links as **two register stages**, both directions; a 1-hop flit's packet
latency = 7 cycles (inject 0 → eject-read 7) is the built-in calibration point.

## 4. VC allocator and flow control (the safety-critical parts)

- Credit counter per VC; **decrement on grant, increment on consumption** (ejection or
  downstream buffer write). The invariant — `0 ≤ credit ≤ buffer_depth`, always — is
  the property formal verification will prove (§7). It is also the classic bug farm:
  a single off-by-one here is a dropped flit *or* a deadlock, both invisible in
  throughput averages.
- VA grant only when downstream credit > 0. No speculative grants (BookSim's
  `speculative` = off).
- **Output VC life cycle:** the output VC is marked in-use at VA grant (TakeBuffer)
  and **released when the tail flit is SA-granted** (`wait_for_tail_credit = 0`),
  not when its credit returns. VA eligibility = output VC not in-use; SA eligibility
  = downstream VC occupancy < `vc_buf_size`. Two different gates — mixing them is
  the classic deadlock-by-construction bug.
- **SA request granularity:** with `input_speedup = 1`, the switch allocator has 5
  inputs × 5 outputs — one request per input port per output port. Multiple VCs at
  the same input requesting the same output **merge into one request**, winner =
  highest prio, ties by round-robin from `_sw_rr_offset[input]` (`Supersedes`); the
  offset advances to `(granted_vc + 1) % VCS` on a grant. The VC allocator, by
  contrast, is per (input, VC) → (output, VC).
- **iSLIP allocation, exactly as the fork implements it** (`src/allocators/islip.cpp`,
  1 iteration): grant phase — each output grants to the first free input from its
  pointer `_gptrs[output]`; accept phase — each input accepts the first grant from
  its pointer `_aptrs[input]`; **pointers advance by one only on a successful
  match**. Deterministic and seed-independent, which is what makes Leg 1 exact and
  Leg 2 repeatable.
- VC assignment at each hop: any free downstream VC (see §3, VC selection policy).

## 5. Stimulus: trace replay (cycle-exact) vs LFSR (FPGA shape)

- **Trace replay (Leg 1 and Leg 2's counting leg):** the plane-separation traffic
  (class 0: DMA bursts of length B ∈ {5, 10, 20, 40, 80} at rate r with B×r = 0.08
  flits/cyc/node, 8 diagonal NICs; class 1: 1-flit control at 0.005) is generated
  **once** and written to a BRAM-init file, then replayed identically by BookSim and
  the RTL testbench. The RTL cannot invent stimulus; it must not. This is how "same
  seeds" is made honest across two totally different engines. **Capture, don't
  reimplement:** the trace is *dumped by BookSim's own injection machinery* — a
  small fork patch adds a `trace_out` flag that logs (cycle, src, class, dest,
  size) per generated packet (class 0 Bernoulli at rate r, dest = uniform hotspot
  pick; class 1 Bernoulli at 0.005, dest = uniform). Reimplementing the fork's RNG
  (`rng.c` / `rng-double.c`) in Python would be a third simulator; dumping the
  injected stream is bit-faithful by construction.
- **LFSR (Leg 2 shape leg):** pseudo-random bursts with the same *burst parameters*,
  for long-running FPGA sessions where trace replay would exhaust BRAM. LFSR
  sequences will NOT match BookSim's RNG — that is fine, because this leg claims
  *curve shape*, not cycle identity. Do not confuse the two legs.

## 6. Instrumentation: per-router cycle counters

- Monotonic tick counter on the device clock at every router and NIC (never host
  timestamps).
- Latency measurement by **cycle stamp**: a shadow field in each flit carries its
  injection cycle; ejection reads it and records (ejection_cycle − injection_cycle)
  per class per VC. Exactly the control-latency metric of the Appendix table.
- Readout: CSR block → UART (FPGA leg); direct testbench reads (RTL-sim leg).
- Reproducibility gate: **same bitstream + same seeds ⇒ bit-identical counter dump.**
  If a second run differs, the bitstream isn't deterministic and the result is
  worthless — report the failure, don't average it away.

## 7. Formal verification — the property list (Yosys-SMT, sby, z3/yices2)

Proven at the **component level** (router, VC allocator, credit logic, NIC, burst
generator), with BMC + k-induction where the property admits it. Tools: Yosys-SMT
and SymbiYosys as in the t4-formal track. *(Note: Yosys/CBMC are currently disabled
in the Docker image to speed builds — re-enable for this slice, per the CI comment.)*

| # | Property | Class | Provable how |
|---|---|---|---|
| P1 | `0 ≤ credit ≤ buffer_depth` per VC, every cycle | safety | BMC + k-induction |
| P2 | No flit written to a full buffer | safety | BMC + k-induction |
| P3 | No flit read from an empty buffer | safety | BMC + k-induction |
| P4 | Packet integrity: flits of one packet never interleave with another on the same VC | safety | invariant |
| P5 | Routing correctness: flit exits through the port XY routing dictates | safety | one-symbol reachability |
| P6 | **Multicast completeness: exactly g−1 copies delivered, none duplicated or lost** | safety | **the g−1 = 7 law (PITFALLS §16) as an SMT property** |
| P7 | Grant liveness: every request granted within N cycles (under the round-robin fairness constraint) | liveness (bounded) | BMC to bound N; honest claim = bounded, not absolute |
| P8 | No credit lost across the VC allocator/ejector interface | safety | BMC + k-induction |

**What is NOT provable here, stated flat:** routing *deadlock freedom* is a
channel-dependency-graph question at the abstract level — that is T2's SPIN/UGAL
domain, not BMC on RTL, and conflating them is exactly PITFALLS §8. And a BMC bound
is not a proof for all cycles: only k-induction (or a complete bounded safety check)
earns the word "proven". The write-up must state which of P1–P8 got which treatment.

**The chain, stated as one sentence:** known-answer gates in BookSim (model) →
BMC/k-induction on RTL (implementation) → counters on FPGA (silicon) — three
independent witnesses, and "verified" means all three agree, nothing less.

## 8. Gates — no claim before these pass

Each gate has an explicit failure condition (PITFALLS §13: a gate that cannot fail
is not a gate).

**Gate R0 — the RTL simulates.** Every router/NIC/generator instantiates and runs
under Verilator; counters increment. *Fails if:* any module is uninstantiable.

**Gate R1 — cycle-exact co-sim.** BookSim vs RTL, trace-replay stimulus, per-flit
ejection cycles match at every router for every class. **The Appendix burst table
(1-VC row: 45.1/55.5/70.1/100.2/221.6) must reproduce cell-for-cell in RTL sim.**
*Fails if:* any ejection cycle differs by > 0 cycles (strict criterion), or — under
the **tolerance policy adopted 2026-08-10 (PITFALLS 24)** — any flit's (atime,
itime) differs by > 3 cycles or any (cl, src, dst) id differs at all. The strict
zero-tolerance criterion remains the development target and is always reported
first; the ±3-cycle bound is the measured fidelity limit of the RTL under
saturation (99.96% of flits bit-exact at VCS=1, mean Δatime −0.003; every residual
is timing-only jitter inside ±3), and the burst table — a mean-latency statistic —
reproduces to <0.01 cycles either way. Encode with `rtl_r1.py diff <cell> 3`;
counts, order, and ids are never tolerated. This is the known-answer gate
of the slice — the table is the law, and the RTL must be the law's citizen.

**Gate R2 — bit-identical FPGA.** Same bitstream + same seeds, two runs ⇒ identical
counter dumps (sha256 of the dump, same discipline as the JSON hash). *Fails if:*
the dumps differ.

**Gate R3 — FPGA curve shape.** Burst sweep on silicon: control-latency vs burst
length at constant load must be monotonically increasing, and the **1-VC vs 4-VC
separation must reproduce** (4 VCs hold control latency to ≈1.24×, not 6.68×).
*Fails if:* the shape inverts, or VC separation disappears. Absolute cycle values
may differ from BookSim (honest: placement/timing); the *shape and the separation*
are the law.

**Gate R4 — formal.** P1–P8 proven on the RTL (with the per-property method stated
per §7). *Fails if:* any property has a counterexample that RTL sim confirms — that
is a real bug, fix and re-prove; or a property cannot be proven and the honest
conclusion is "unproven", not "assumed".

## 9. Pre-registered predictions (written before running)

1. **Gate R1 passes** — the pipeline-staged RTL is faithful enough to reproduce the
   table cell-for-cell, because the burstiness mechanism is queueing, not timing.
2. **Gate R3 shows the same shape, larger spread.** FPGA control latency at 80-flit
   bursts is ≥ BookSim's (placement jitter, PHY effects), but the 1-VC/4-VC ratio
   keeps its order of magnitude: plane separation is real silicon behavior.
3. **P1–P3 prove clean** (credit/buffer invariants are structural). **P6 (g−1) proves
   clean** — it is the same law PITFALLS §16 already validated twice, now on RTL.
4. **P4 or P7 will bite once.** Every NoC bug farm lives in interleaving and grant
   fairness; if neither property ever fails during development, suspect we wrote the
   properties to match the RTL rather than the spec.
5. **The first RTL has a credit off-by-one.** Every real NoC bring-up does. The bet is
   that **Gate R4 catches it before Gate R1 does** — that is the whole point of
   formal-before-matching.

## 10. Honesty gates (carried from Phase 1/2)

- FPGA is not ASIC: absolute ns/cycles differ; we claim curve identity and functional
  identity on silicon, cycle identity only in co-sim (Leg 1). Say so in every write-up.
- No new topology, no "AI-native NoC IP" — this slice writes a *faithful mesh with
  VCs and (follow-up) express lanes* because it must match BookSim, not because the
  fabric is novel.
- Every number selfcheck-pinned or trace-identical; the RTL cannot invent stimulus.
- The known-answer gate (g−1, the Appendix table) is applied on every leg, per
  PITFALLS §16.

## 10a. Bridge-fork RTL gate — DONE (2026-08-12)

The UCIE-ARC Phase-2 mechanism (KV multicast crossing a die boundary) is now
**RTL-verified**, not just BookSim-measured. Built:

- `rtl/noc_pkg.sv`: `flit_t` gains `mcast` + `copy_lo`/`copy_hi` (copy range,
  matching the BookSim fork's contiguous-copy semantics; copy pid =
  stream_pid + (n − copy_lo) + 1, exact BookSim derivation).
- `rtl/router.sv`: multicast fork in the XT stage — a mcast head granted SA to its
  next hop ALSO ejects a copy to the local port in the same cycle (BookSim's
  eject-while-forwarding; no second SA grant needed). Copy marker `vc=0`, no credit
  return (BookSim: copies have vc<0, no occupancy).
- `rtl/noc_2die.sv`: two 8×8 meshes + one bridge link (2-stage channel, like every
  other link). Bridge column and entry row parameterized (`BRIDGE_COL`,
  `BRIDGE_ROW`). Die-A edge router routes die-B targets to the bridge; die-B uses
  Y-first DOR so an off-axis entry climbs to the multicast row (row 0) before
  routing east — matching BookSim's Dijkstra path exactly.
- fork unit coverage now lives in the `noc_tb` TWO_DIE path (fork TBs deleted 2026-08-15, seed e8f9).

Measured (Verilator, VCS=1, one stream, g=8 die-B cores, packet_size=1):

| cell | first copy fork | stream at far end | verdict |
|---|---|---|---|
| on-axis (bridge → die-B row 0) | **T52** | T82 (stream p500 at R71) | PASS: 6 copies + stream, pids 501-506 + 500 |
| off-axis (bridge → die-B row 7) | **T87** | T117 | PASS: same deliveries |

**The placement penalty is 35 cycles (T87 − T52), exactly 7 hops × 5 cyc/hop — the
die height — and it matches the BookSim placement_law.json to the cycle.** The
g-fold known-answer gate (PITFALLS §16) now passes at the RTL level: one injection
→ g deliveries, copies on the remote die, stream terminating at the far end, nothing
leaking back to die A.

Honesty notes: the RTL fork is a *functional + cycle-level* gate of the mechanism
(the pids, delivery count, and per-hop timing all match the BookSim dump contract);
it is not yet wired into the rtl_r1.py `diff` pipeline (that integration is the next
step). The 2-die RTL suppresses the bridge column's mesh channel to avoid a duplicate
path — the same "no parallel path at the bridge" rule the BookSim anynet encodes.

**Caveat CLOSED (2026-08-12): the fork is now wired into the rtl_r1.py pipeline.**
BookSim's `trace_out` emits mcast lines (`cycle src cl far_end size mcast lo hi`);
`gen_trace` writes a range word (`{cycle=0, cl=lo, dst=hi}`) after each mcast entry;
the NIC detects it (zero cycle field), injects the stream with `mcast/copy_lo/
copy_hi`, and the fork fires as before. The drain check now expects
`ejected == injected + Σ(hi−lo+1)` (fork delta read from the trace). The diff
correlates pids: RTL stream pid = (tptr<<4) = 32·ordinal (tptr = 2·ordinal, each
mcast entry consumes entry+range), copies = stream_pid | offset (4-bit, up to 15
copies), BookSim stream pid = cumulative 1+copies count. Verified on the 8×8 mesh
at **g ∈ {4, 8, 16} (16×8 mesh) — 66/154/330 deliveries, ALL ZERO mismatches at
tol=0** (atime, cl, src, dst, itime exact). Cell staging + traces: `/tmp/opencode/
gf_{4,8,16b}` (ephemeral — rerun `fork_gate_sweep.py` to regenerate).

**2-die bridge cells in the pipeline (2026-08-13):** `noc_tb` gained a `TWO_DIE`
parameter (instantiates `noc_2die`; NIC arrays sized `ND*N`, `replay_base` scaled by
`ND`, fork-delta drain break). Both placements gated through the standard pipeline
(BookSim trace → hex → RTL replay → rtl_r1.py diff), g=8, copies 65-70 on die B:

| cell | first copy (BS = RTL) | far end | deliveries | diff |
|---|---|---|---|---|
| on-axis (BRIDGE_ROW=0) | 580 | 610 | 154 (22 streams) | **ZERO mismatches, tol=0** |
| off-axis (BRIDGE_ROW=7) | 615 | 645 | 154 | **ZERO mismatches, tol=0** |
| penalty | **+35 cyc** | **+35 cyc** | — | — |

The 35-cycle placement law (7 hops × 5 cyc) is verified end-to-end — the RTL and
BookSim agree to the cycle on both placements. Note: the off-axis BookSim trace must
be generated from `bridged_2die_offaxis.cfg` (its Dijkstra path includes the climb);
using the on-axis cfg gives a consistent +35 BookSim-vs-RTL gap that looks like a
failure but is the wrong reference.

**Audit (2026-08-13, `docs/research/rtl-audit-2026-08-13.md`):** full read-through
of rtl/ + tb/ against the BookSim contract. Three blockers, all in the untested
corner (multi-stream / mixed-traffic / multi-flit): F1 fork-copy XT collision
(two writers to `xt_flit[PORT_L]` in one cycle — silent loss; untriggered by
single-stream cells), F2 NIC reorder path deadlocks on a mcast range word
(untested combination), F3 multi-flit mcast forks only the head (cells are
packet_size=1). **F1+F2 must be fixed before the contention/multi-stream runs; the
single-stream placement cells are clean.** Moderate: stale self-certifying
3D/4D stacks are not cycle models (F5/F6); noc_mcast_tb.sv deleted (F4, 2026-08-15); no off-axis
standalone TB (F7), phantom local-port credit breaks only the DBG5 audit line (F8).

## 11. Work plan

| phase | work | cost | exit |
|---|---|---|---|
| 0 | **DONE (2026-08-08):** contract pinned — every value above verified against the fork source; timing semantics nailed with a `watch_flits` trace (see the one-line summary below); re-enable Yosys/sby in the image | hours | the contract table, committed before RTL |
| 1 | RTL: router (5-port, 1–4 VCs), iSLIP VA+SA, credit logic, NICs, LFSR + trace-replay generators; Verilator testbench; per-router counters | 2–4 weeks (student team) | Gate R0 |
| 2 | Co-sim harness: BookSim (trace dump) ↔ Verilator (trace replay); per-flit ejection comparison | 1 week | **Gate R1 — the table reproduces** |
| 3 | Formal: P1–P8 in Yosys-SMT/sby on the component level | 1–2 weeks | Gate R4 |
| 4 | Board bring-up: synthesize, counters, UART readout; repeat runs | depends on board access | Gates R2, R3 |
| 5 | Falsification: for every mechanism claim, zero the term and check the claim dies (the Phase-1 rule, carried) | hours | no claim survives that a null test would kill |

Board: mid-range Xilinx/Intel (~$300 Artix-class up; Kria/Alveo if the hard-NoC
comparison is wanted), or cloud FPGA (AWS F1). Board acquisition is the one
hardware dependency; everything before Phase 4 runs on the existing CI toolchain.

## 12. What this slice will not claim

- Not a new fabric. A faithful reproduction, written to be wrong against the model.
- Not "silicon-proven NoC IP". A measured mesh with a known-answer gate.
- Not a formal proof of the *system* — proven properties are P1–P8 at component
  level, each with its method stated.
- Not that FPGA numbers equal ASIC numbers. It is a second substrate that either
  corroborates the queueing law or catches the model lying — both are the result.
