# KV-Cache Multicast at the Chip-to-Chip Boundary: A Bridge-Fork Mechanism and a Bridge-Port Placement Law for Chiplet LLM Accelerators

> Status: **paper skeleton** — purposes, claims, evidence, open items. Not prose.
> Evidence tags used throughout:
> `[MEASURED]` = BookSim or RTL-gate number (the only place "measured" is earned);
> `[MODELED]` = analytic/energy/hop estimates;
> `[UNSAFE]` = explicitly forbidden claim (docs mark it unverified — do not publish).
> Source trail: `UCIE-ARC.md`, `RTL-ARC.md §10a`, `docs/research/cross-node-kv-distribution-2026.md`,
> `FINDINGS.md`, `NETWORK-HIERARCHY.md`, `docs/research/simulator-landscape-2026.md §6`,
> `results/bridge_fork_saturation.json`, `results/placement_law_scaling.json`.

---

## Title (candidates)

1. Fork After the Cut: Replication Placement for Multicast KV Traffic Across Chiplet NoC Boundaries
2. Bridge-Fork: Sending KV State Once Across the Die Boundary in Chiplet LLM Inference
3. KV-Cache Multicast at the Chip-to-Chip Boundary: A Bridge-Fork Mechanism and a Bridge-Port Placement Law

## Abstract (draft, one paragraph)

Chiplet LLM accelerators join per-die NoCs through a single, capacity-constrained
die-to-die cut. When replicated state (KV cache, MoE dispatch, embeddings) must
reach multiple dies, the placement of the replication point relative to that cut
determines how much of the scarce cut bandwidth a multicast consumes. For a KV
row-multicast whose chain spans a NoC-to-NoC (UCIe-class) die boundary, we compare
two mechanisms: **source-fork**, where the sender replicates and the bridge carries
g copies, and **bridge-fork**, where the bridge carries one copy and the remote
die's own NoC forks to its g cores. In cycle-accurate simulation of a two-die
8×8+8×8 system joined by a single bridge link [MEASURED, BookSim], bridge-fork
holds ~78-cycle latency flat to rate 0.064 while source-fork knees at 0.016 and
saturates at 0.032 — a g-fold cut-demand reduction that matches the analytic
model λ_sat,bridge/λ_sat,source ≈ g. We further measure a bridge-port **placement
penalty**: an off-axis bridge port costs the remote die's height in cycles per
crossing, ΔL = (S−1)·L_hop — 35 on 8×8, 75 on 16×16, 155 on 32×32 [MEASURED].
Both the mechanism and the penalty are verified in RTL-gated simulation
(`rtl_r1.py`): the 2-die RTL reproduces the 35-cycle penalty to the cycle
(on-axis first copy T52, off-axis T87) with zero per-flit mismatches at tol=0.
Peak cut bandwidth alone does not determine multicast performance; where
replication occurs determines how much of that scarce bandwidth is consumed.
Design rule: the bridge port must sit on the multicast row's axis of the remote
die, or every KV crossing pays the die-height hop count.

---

## 1. Introduction & Motivation

**Purpose.** Establish (a) KV cache as a first-class distribution object, (b) the
hierarchy rung this paper occupies (chip-to-chip, NOT on-chip — the on-chip verdict is a
prior result at a different rung), (c) what the closest deployed system (Google TPU 8i)
discloses — and precisely what it does not.

**Key claims.**

1. **KV distribution is multicast-shaped *when the parallelization requires it*.** GQA/MLA
   alone does not force cross-die KV movement: with TP ≤ KV-heads, ranks shard KV
   locally (TensorRT-LLM attention-head sharding; vLLM TP > num_kv_heads discussion),
   and replicated ranks can recompute K/V locally. The multicast-shaped regime is
   precisely the cases where a KV object is **already materialized on one die and must
   reach multiple dies/ranks**: (a) TP > KV-heads (replication by construction), and
   (b) prefill/decode disaggregation, where prefill-die KV streams to decode dies
   (3DLS, arXiv 2607.01617, documents exactly this regime: KV transfers over D2D
   fabric contending with TP collectives). The relevant parameter is the
   TP/KV-heads ratio and the disaggregation boundary — not GQA per se. [safe claim
   language, per cross-node-kv doc §3]
2. **The rung.** On-chip, topology is second-order (prior verdict: mesh not beaten by
   enough — fat-tree 1.80×/1.33× for 1.65× energy, EDP 0.92× prefill inside error,
   1.24× decode loss; crossbar dead at 6.97×). At the chip-to-chip rung the properties
   that made topology inert on-chip invert: links become scarce and costly (UCIe-class
   bridges, die-to-die package fabric), and the network is on the critical path for
   tensor-parallel decode. This paper is **at the chip-to-chip rung only** — the on-chip
   mesh verdict is context, not this paper's subject [prior result, cite FINDINGS.md +
   NETWORK-HIERARCHY.md ladder].
3. **What Google ships (safe claims only, all quoted-verbatim-disclosed):**
   - TPU 8i keeps the KV working set on silicon: 384 MB on-chip SRAM, "KV entirely on
     silicon". Google's public material describes the KV strategy primarily in terms of
     on-chip *capacity*; it does not specify a cross-die KV multicast mechanism.
     [safe — disclosed; "capacity, not distribution" is our interpretation, not a
     Google claim]
   - The CAE accelerates **collectives** (reduction/sync for sampling and chain-of-thought),
     not KV distribution. [safe — disclosed; the collective-vs-read-distribution
     distinction is our framing, not a Google claim]
   - Boardfly: serving-optimized ICI topology, ≤7 hops via OCS, up to 50% latency
     improvement for communication-intensive workloads — evidence that **traffic-driven
     topology at the scale-up rung is a live design axis**, the same rung this paper
     occupies. [safe — disclosed]
   - `[UNSAFE]` "Google reloads KV independently per chip" — **do not claim**; Google
     discloses nothing about cross-chip KV movement. The motivation is the footprint that
     *does not fit* on-chip (long context, agentic loops, multi-tenant concurrency) —
     Google's own agentic-era framing invites it, and their disclosed design does not
     cover it.
4. **Why multicast and not just bandwidth.** The scarce resource at this rung is the
   bridge/die-to-die link. Bridge-fork cuts its demand g-fold (carry 1 copy, fork on the
   remote die) — the same fetch-once-multicast-many primitive Phase 1 proved on-die,
   continued across the die edge.

**Evidence to include.**
- GQA g = n_q / n_kv framing (from prior on-chip work; keep brief — motivation only).
- Google verified-disclosure table (8i: 384 MB SRAM, 288 GB HBM, 19.2 Tb/s ICI, CAE 5×;
  8t: 3D torus 9,600 chips/pod) — cite the four primary URLs from the source index.
- Hierarchy ladder table (on-chip: no → chip-to-chip: "beginning to" → pod: yes →
  pod-to-pod: decisive), compressed to one line each, with the inversion argument
  (links free→scarce, network headroom→bottleneck, traffic local→collective-heavy).

**Open items.**
- Decide the failure case the paper leads with: long-context decode where KV exceeds
  on-chip SRAM, or disaggregated prefill/decode KV streaming. Both are unsupported by
  Google's disclosure; pick one and cite the serving architecture (trace-derived, per
  PITFALLS §4 — LLMServingSim/Chakra path, not hand-invented).
- Whether to cite the MoE-topology paper (arXiv 2605.00254) and NetKV (2606.03910) as
  scale-out-rung occupants to differentiate (they target MoE expert-parallel and
  network-aware routing, not KV multicast) — required for the related-work defense.

---

## 2. Background & Related Work

**Purpose.** Map who owns what at adjacent rungs; state the unclaimed slice precisely.
Every occupant must be cited **and** distinguished — "they own X, not our slice."

**The slice (one sentence, to state verbatim).** The fetch-once-multicast-many primitive
for replicated KV state at the chip-to-chip NoC/UCIe rung — i.e., *where* on the remote
die the bridge lands, and *whether the multicast fork survives the bridge* — has no
direct occupant (zero arXiv hits for KV+NoC, UCIe+NoC+multicast, cross-chip+KV cache,
LLM-serving+multicast+topology; all searched 2026-08-12, metadata+abstract, conservative).

**Ownership table (what they own → the gap vs our slice).**

| Work | Owns | Gap vs our slice |
|---|---|---|
| MONET (Liu et al., DATE 2026) | Two-tier multicast-optimized NoC for MoE: "Mel" multicast vs "Bel" aggregation routers; control/token routing segregated from bulk weight/KV; 8.5× latency / 6× energy vs flat topologies | On-die MoE dispatch; no die-boundary bridge, no port-placement law; segregation is a plane design, not a fork placement |
| PAC-NoC (Ouyang et al., 2026, IEEE CSDL/JSS, on NoCDAS) | Bandwidth-tapered fat-tree NoC with native multicast + aggregation for multi-head attention | On-chip attention multicast topology; no chip-to-chip rung, no placement law; our fork gates on a *mesh* remote die (prior verdict: trees don't pay on-chip) |
| 3DLS (arXiv 2607.01617) | 3D logic-stacked disaggregated LLM serving; **names** the shared lateral D2D KV-transfer/TP-collective problem | Names it, solves it with 3D stacking — no multicast-fork mechanism, no 2.5D/package-fabric rung |
| TPLA (arXiv 2508.15881) | Disaggregated prefill/decode + MLA; **states** "each device must load the full cache"; solves algorithmically (latent attention) | The redundant-load problem stated; solution is software/algorithmic — precisely the line-item our mechanism attacks |
| PTStore (arXiv 2607.22648) | Distributed prefix KV caching + replication, CDN-style, rack/node level | Software replication; no chip-to-chip fabric mechanism |
| WaferLLM (OSDI 2025), ELK (MICRO 2025), WaferAI-SIM | KV *placement* over the mesh / contention modeling / serving-level KV-NoC contention | Placement and contention, not multicast sharing; no bridge |
| FlooNoC (Fischer et al., NOCS 2023) | Four physically separate networks (Control/Streaming/Optional/Chiplet) — plane separation as a shipped chiplet NoC | The on-chip isolation lever; no fork, no placement law (our plane-separation result is its validation) |
| FlatAttention (cited in prior-art gate) | On-chip NoC multicast for shared K/V | **Taken** at the on-chip rung — which is why our novelty is the bridge-level form, not multicast itself |
| MoE topology (arXiv 2605.00254), NetKV (2606.03910) | Scale-out topology for MoE serving; network-aware routing on fixed fat-tree | MoE expert-parallel / routing, not KV multicast at the package rung |

**What we own (novelty statement, honest version).** The multicast fork mechanism itself
is vendor-shipped (PR #40733) and on-chip multicast is published (FlatAttention). Our
contribution is the **bridge-level form** (fork on the remote die, not at the source),
the **bridge-port placement law** (off-axis = die height in cycles, load-independent),
and the **RTL gate** of both at zero per-flit mismatch. The Gate-0 prior-art pass
(2026-08-05) and the primary-source refresh (2026-08-12) found no work analyzing
multicast fork placement across a NoC-to-NoC bridge for serving traffic.

**Open items.**
- Re-verify the ⚠️-flagged items before publication (per simulator-landscape-2026 §6
  confidence note): PAC-NoC venue/DOI, 2605.00254 and NetKV read-in-full to confirm the
  MoE-vs-KV-multicast delta holds (scoop risk is real; field moves monthly).
- Decide MONET's standing: it is simultaneously the closest architectural relative
  (multicast planes) and the cleanest differentiation (no bridge rung) — write the
  comparison table explicitly, per the existing monet-vs-plane-separation analysis.

---

## 3. Method

**Purpose.** Give the reviewer the exact reproducibility path: simulator stack, 2-die
topology construction, multicast knobs, the RTL gate pipeline, and the known-answer
discipline that governs every number. Method must make "measured" vs "modeled" auditable.

**3.1 Stack.**
- Exploration core: **BookSim2 fork with veritx extensions** (flit-fork multicast,
  per-flit timing). The on-chip prior verdict was produced via PyTorchSim (MICRO 2025) →
  BookSim2 + Ramulator2 + Accelergy (FlooCNoC-calibrated, 1.37× vs 12 nm silicon); this
  paper's measurements are at the BookSim2 + RTL level. State plainly: PyTorchSim models
  only core↔DRAM bipartite traffic, hence this rung is studied at the network level, not
  end-to-end. [Measured claim boundary]
- Fidelity gate: the repo's own RTL NoC (Verilator) with per-flit Gate R1 harness —
  no off-the-shelf equivalent publishes a per-flit RTL↔sim gate.

**3.2 2-die topology (the bridge).**
- `bridged_2die.{cfg,anynet}`: two 8×8 meshes (128 routers) joined by **one bridge link**
  (row 7 ↔ row 0 at column 3) — a bridge is modeled as a router hop with per-hop cost;
  the bridge column/entry row are parameters (BRIDGE_COL, BRIDGE_ROW).
- Required fork fix in `iq_router.cpp`: the eject port was hardcoded to `_outputs−1`
  (correct on uniform mesh, wrong on anynet where node channels come first); now found
  by scanning for the sink-less output channel. Mesh regression clean.
- Die-B uses Y-first DOR so an off-axis entry climbs to the multicast row before routing
  east — matching BookSim's Dijkstra path exactly (and the RTL matches this routing).

**3.3 Multicast knobs.**
- `mcast_offset`: die-A source → g die-B cores.
- `mcast_single=1`: gate to **one stream** — the clean cell. (Earlier multi-source runs
  were confounded: each die-A row multicast to a different die-B row, so placement helped
  some rows and hurt others; the clean cell must be the one reported, confound noted.)
- Flit-fork semantics: one injection → exactly g−1 copies (contiguous copy range,
  copy pid = stream_pid + (n − copy_lo) + 1; copies have vc<0 / no credit return —
  matching the BookSim dump contract).

**3.4 RTL gate pipeline (`rtl_r1.py`).**
- BookSim `trace_out` emits mcast lines (`cycle src cl far_end size mcast lo hi`);
  `gen_trace` writes a range word (`{cycle=0, cl=lo, dst=hi}`) after each mcast entry;
  the NIC detects it (zero cycle field), injects the stream with mcast/copy_lo/copy_hi.
- Drain check: `ejected == injected + Σ(hi−lo+1)` (fork delta read from the trace).
- pid correlation: RTL stream pid = (tptr<<4) = 32·ordinal; copies = stream_pid | offset
  (4-bit, up to 15); BookSim stream pid = cumulative 1+copies count.
- RTL implementation: `noc_pkg.sv` (flit_t gains mcast + copy_lo/hi), `router.sv` fork
  in the XT stage (mcast head granted SA to its next hop ALSO ejects a copy to the local
  port in the same cycle — eject-while-forwarding, no second SA grant), `noc_2die.sv`
  (bridge = 2-stage channel, like every other link).
- Gate discipline: per-flit comparison of (atime, cl, src, dst, itime). **tol=0 is the
  reported criterion** (strict, zero-tolerance is the development target); the ±3-cycle
  tolerance policy exists only for saturated runs where 99.96% of flits are bit-exact
  (mean Δatime −0.003) — counts, order, and ids are never tolerated.

**3.5 Known-answer gate discipline (PITFALLS §16).**
- One multicast injection must deliver to exactly g−1 cores — a number known in advance.
  This gate has caught two flattering errors before (torus row-skip delivering 1 not 7;
  throughput read one sample early, 10× vs true 7.1× ≈ g−1).
- At the bridge, the gate is: **bridge-fork must keep the bridge unsaturated ~g× longer
  than source-fork** (demand ratio source/bridge = g, from `ucie_bridge_multicast.py`).
- Read saturation numbers off the plateau, never off the last pre-saturation sample.
- Every number is selfcheck-pinned or trace-identical; the RTL cannot invent stimulus.

**Open items.**
- Whether to re-run the placement cells on a second engine (NoCDAS or CHIPSIM) for
  cross-simulator agreement — a reviewer-recognized credibility mechanism, days of work.
- State explicitly what is NOT modeled: no UCIe PHY energy (pJ/bit to be sourced, not
  assumed), no power at the bridge, no DRAM behind the remote-die NoC.
- The 2-die RTL suppresses the bridge column's mesh channel to avoid a duplicate path —
  same "no parallel path at the bridge" rule as the anynet; mention as a modeling choice.

---

## 4. Results

**Purpose.** Three measured tables, each with its gate. Nothing here is modeled.

### 4a. Mechanism saturation crossover (bridge-fork vs source-fork)

**Setup.** g=8 remote die-B cores; KV row-multicast die A → die B; `mcast_offset=64`;
`packet_size=1`; one bridge link; `mcast_single=1`. [MEASURED, BookSim —
`results/bridge_fork_saturation.json`]

| rate | bridge-fork lat (cyc) | source-fork lat (cyc) |
|---|---|---|
| 0.0005 | 82.0 | 76.4 |
| 0.001 | 79.1 | 76.2 |
| 0.002 | 77.7 | 76.8 |
| 0.004 | 77.5 | 77.7 |
| 0.008 | 78.0 | 80.5 |
| 0.016 | 77.9 | **119.7 (knee)** |
| 0.032 | 78.6 | **497.7 (saturated)** |
| 0.064 | 80.7 | 376.2 |
| 0.128 | 119.4 | 366.6 |

**Key claims.**
- Bridge-fork holds ~78-cycle latency flat to rate 0.064; source-fork knees at ~0.016
  and saturates at ~0.032 — **6.3× worse at the knee (498 vs 79 cyc)**.
- Bridge demand: 1 copy vs g copies — the g-fold known-answer gate passes at the die
  boundary: the bridge (scarce resource) stays unsaturated when it carries 1 copy and
  the remote die forks, "exactly as the analytic model predicted."
- Acceptance columns (raw JSON `acc`): bridge-fork acceptance rises monotonically
  (1.6e−05 → 1.07e−02) across the sweep; source-fork acceptance peaks at 0.032
  (7.7e−03) then *falls* — the saturation signature. Include as evidence of plateau
  reading (PITFALLS §16).

**Open items.**
- Pin the exact crossover definition: source-fork knee at 0.008–0.016 (first divergence
  at 0.008: 80.5 vs 78.0), saturation at 0.032. The JSON verdict's "2× the source-fork
  knee" phrasing is loose; the g-fold gate reads 8× (0.064/0.008) — decide the sentence
  the paper commits to.
- Why source-fork latencies *fall* post-saturation (497.7 → 376.2 → 366.6): injection
  throttling at the TM (accepted/injected < 1) — state this mechanism explicitly so a
  reviewer does not read it as a bug.

### 4b. Placement law scaling

**Setup.** Single KV multicast stream, node 0 → g cores on die-B row 0, bridge-fork
(1 copy crosses). On-axis = bridge lands on die-B row 0; off-axis = lands on row 7,
stream climbs col 0 then sweeps. [MEASURED, BookSim — `results/placement_law_scaling.json`]

| die (S×S) | g | on-axis lat (cyc) | off-axis lat (cyc) | penalty (cyc) |
|---|---|---|---|---|
| 8×8 | 8 | 67.0 | 102.0 | **35 = (8−1)×5** |
| 16×16 | 16 | 127.0 | 202.0 | **75 = (16−1)×5** |
| 32×32 | 32 | 247.0 | 402.0 | **155 = (32−1)×5** |

**Load-independence.** At fixed S=8, g=8: penalty is a constant 35 cyc at rates 0.002,
0.008, 0.032, 0.064, with **identical acceptance at every load** [MEASURED, UCIE-ARC
placement table]. The penalty is pure distance — 7 hops × 5 cyc/hop — no contention
component. (On-axis 15 hops vs off-axis 22 hops.)

**Key claims.**
- Law: `penalty = (S−1) × 5.0` cycles per crossing, load-independent, per-hop cost 5.0
  cyc (the RTL-ARC §3 measured per-hop budget: 4 router stages + 1 channel).
- Design rule: **the bridge port must sit on the multicast row's axis of the remote
  die**, or every KV crossing pays the die-height hop count.

**Open items.**
- `g` co-varies with `S` in the scaling table (g=8/16/32 at S=8/16/32) — "g-independent"
  is asserted in the JSON but not isolated at fixed S. Either run g at fixed S or soften
  the claim to "S-dependent, load-independent" and mark g-independence as a modeling
  consequence of the distance-only mechanism.
- On-axis/off-axis latency rises by ~20 cyc per step (67→127→247) — 2·S hops + bridge
  crossing; derive the closed-form path-length model and selfcheck it against the table.

### 4c. RTL gate

**Setup.** Fork wired into the `rtl_r1.py` pipeline; Verilator, VCS=1, one stream,
packet_size=1. [MEASURED, RTL — RTL-ARC.md §10a, caveat CLOSED]

| g | mesh | deliveries | mismatches at tol=0 (atime, cl, src, dst, itime) |
|---|---|---|---|
| 4 | 8×8 | 66 | **0** |
| 8 | 8×8 | 154 | **0** |
| 16 | 16×8 | 330 | **0** |

Plus the 2-die placement cell (RTL `noc_2die.sv`, fork_2die TB):

| cell | first copy fork | stream at far end | verdict |
|---|---|---|---|
| on-axis (bridge → die-B row 0) | T52 | T82 (p500 at R71) | PASS: 6 copies + stream, pids 501–506 + 500 |
| off-axis (bridge → die-B row 7) | T87 | T117 | PASS: same deliveries |

**Key claims.**
- Placement penalty in RTL: **35 cycles (T87 − T52) = 7 hops × 5 cyc/hop = the die
  height — matches BookSim `placement_law.json` to the cycle**.
- g-fold known-answer gate passes at RTL level: one injection → g deliveries, copies on
  the remote die, stream terminating at the far end, nothing leaking back to die A.
- Zero per-flit mismatches at tol=0 across g ∈ {4, 8, 16} — the strictest criterion
  (counts, order, ids never tolerated).

**Open items.**
- The g∈{4,8,16} gate and the T52/T87 placement cell were measured by different harness
  stages (diff pipeline vs 2-die TB). State which harness produced which table; confirm
  the 2-die placement cell is (or is not) inside `rtl_r1.py diff` before the results
  section finalizes.
- Delivery counts (66/154/330) do not cleanly decompose into injections × (1+g) from the
  docs alone (e.g., 330/17 is not integer) — either the injection count or the raw dump
  must be pinned before publication; report counts as-is otherwise.
- Formal leg (P6: exactly g−1 deliveries as an SMT property, Yosys-SMT) is planned, not
  done — do not claim proof.

---

## 5. Analysis

**Purpose.** Explain *why* the numbers are what they are, and convert the law into
design guidance. Keep measured-vs-derived separation explicit.

**5.1 Why the placement penalty is load-independent (and g-independent-by-construction).**
- The off-axis penalty is a **distance** term, not a queueing term: the stream climbs
  (S−1) rows at the head of the multicast before it can begin the row sweep; the climb is
  serialized once per crossing, ahead of the fork. No contention enters because the cells
  are run below saturation and acceptance is identical at every load.
- Per-hop cost 5.0 cyc is the *measured* pipeline budget (receive-to-receive 5 cycles:
  routing/VA/SA/XT + 1 channel — RTL-ARC §3), so the law is mechanical: hops × 5.
- Implication: the law transfers to any single-sender row-multicast; it is a statement
  about where the scarce resource (bridge) meets the multicast axis.

**5.2 The 35-cycle law as design guidance.**
- On a UCIe-class die boundary, the bridge port is a floorplanning decision made once;
  the law prices the error: every off-axis crossing pays the full die climb, in the
  decode-critical path, per token. On 8×8 that is 35 cyc; on 32×32, 155 cyc.
- Contrast with the on-chip rung (mesh shape second-order): at the die boundary the
  *port placement* is the topology. This is the rung-specific meaning of "topology
  matters at chip-to-chip" (NETWORK-HIERARCHY ladder).
- Interaction with the mechanism: bridge-fork makes placement a *first-order* design
  parameter — with source-fork the remote fork does not exist, but the bridge saturates
  first anyway; bridge-fork + on-axis placement is the only cell where both the g-fold
  win and the minimum crossing latency hold.

**5.3 Why the crossover table is a bandwidth-vs-multicast statement.**
- Both mechanisms move the same number of payload bits end-to-end; the difference is
  *where the replication happens*. Bridge-fork pushes replication to the free resource
  (remote-die NoC headroom) and keeps the scarce resource (bridge) at 1× — the same
  economics as the on-chip mechanism, one rung up.

**Open items.**
- An energy reading of the law (extra hops cost ~5 cyc each; with the FlooNoC 1.37×-
  calibrated router model, the off-axis cell's extra 7 hops × router energy is quantifiable
  on-die) — [MODELED] only, and bridge pJ/bit is NOT sourced: keep out of the paper until
  cited (honesty gate: "no UCIe pJ/bit until cited").

---

## 6. Threats to Validity

**Purpose.** State every limit up front; each item names what would have to be true for
the result to flip. Mark [MEASURED]/[MODELED]/[UNSAFE] as relevant.

1. **Single-stream workload.** The clean cell is one KV multicast stream (`mcast_single=1`).
   Multi-stream and mixed traffic-class interference at the bridge are unmeasured; the
   plane-separation result (burstiness starves control on a shared fabric) suggests the
   bridge as a new single-point contention site. The confounded multi-source runs that
   motivated `mcast_single` show the multi-stream regime is not trivially additive.
   **[UPDATE 2026-08-13: multi-stream trace-derived replay in progress (seed
   veritx-research-176e); the RTL was found to have a fork-copy XT collision under
   contention (F1, fixed edec5c1) and a missing B→A reverse path (fix in progress) —
   this threat item is being closed by the trace pipeline, not retired.]**
2. **Single-flit multicast scope (F3).** The RTL fork replicates the head flit only
   (router.sv:306 fires on `mcast && head`); body flits of a multi-flit mcast packet are
   not replicated, while BookSim's fork delivers every flit to every copy destination.
   All measured cells use `packet_size=1` (KV rows modeled as single-flit), so the
   mechanism claims are scoped to single-flit multicast. Multi-flit KV row-multicast
   (e.g., a 128-byte KV row as one flit vs several) is either a future extension or must
   be declared out of scope. [MEASURED limitation, not a bug in the tested regime]
3. **First-pass workload narrowness.** The motivating serving regime (long-context decode /
   footprint-miss / disaggregated prefill-decode) has not been traced end-to-end through
   the 2-die network. Traffic is synthetic KV row-multicast, not a Chakra-derived trace
   (PITFALLS §4: traffic must be derived, not invented, before the paper claims
   serving-level relevance).
3. **Uniform mesh remote die.** Die-B is an 8×8 mesh. The on-chip verdict says richer
   shapes don't pay on-die (mesh is wire-optimal by construction; fat-tree loses in
   decode); no crossbar/fat-tree remote die is tested — but a different remote shape
   changes the fork's hop cost structure, not the 1-copy-vs-g-copies bridge demand.
4. **No power model at the bridge.** UCIe pJ/bit is explicitly unsourced ("to be sourced,
   not assumed"); the paper makes no energy claims at the die boundary. Any energy
   discussion is [MODELED] on the FlooNoC-calibrated router model and must be labeled.
5. **Google could still disclose a mechanism.** The slice is open *today*; the primary-
   source pass is a point-in-time statement. `[UNSAFE]` never claim Google reloads KV per
   chip — the capacity solution is disclosed, a distribution mechanism is neither
   disclosed nor disproven.
6. **Placement-law g-independence is under-tested** (g co-varies with S in the scaling
   table; see §4b open item).
7. **BookSim is a model; the RTL gate covers the fork, not the whole system.** The
   RTL reproduces the fork and the placement cell to the cycle; the co-sim does not
   include DRAM, real workloads, or FPGA silicon (Gates R2/R3 pending). "Verified" =
   BookSim + RTL agreement, nothing more.
8. **Per-hop cost of 5 cyc is fork-specific.** The law's 5.0 cyc/hop factor is the
   measured pipeline budget of this iSLIP router; a different microarchitecture changes
   the constant, not the (S−1)-hop structure.

**Open items.**
- None new — the table above is the complete list; keep it synchronized with any result
  section change (every new claim must add its threat).

---

## 7. Next Steps

**Purpose.** The shortest path to a publishable paper; ordered by leverage.

1. **Off-axis in the full pipeline.** Run the KV multicast matrix (die-to-die matrix
   from `die_to_die_matrix.py`) with off-axis placement end-to-end; quantify the
   penalty in a serving-level trace (LLMServingSim 2.0 → Chakra → BookSim/RTL injection,
   PITFALLS §4 compliance).
2. **Multi-stream interference at the bridge.** Sweep number of concurrent KV streams
   (the confound `mcast_single` was built to avoid) at the bridge; check whether the
   g-fold win survives contention, and whether the placement law's load-independence
   survives multi-stream.
3. **Decode regime.** Wire the GQA decode workload (decode_e2e) to the 2-die topology:
   per-token KV multicast across the boundary at seq-128 first pass; latency budget per
   token. (Note: "seq-128 first pass" has no documented numbers in the repo — the
   experiment must be run or the threat deleted.)
4. **Area/energy of the fork in routers.** Fork cost in the XT stage: extra crossbar
   ports / copy muxes; Accelergy area+energy of the fork itself on the remote die
   (FlooNoC 1.37× anchor); bridge energy ONLY once UCIe pJ/bit is cited.
5. **Formal leg.** P6 (exactly g−1 copies, none duplicated/lost) as a Yosys-SMT BMC +
   k-induction property on the fork RTL — turns "zero mismatches on g∈{4,8,16}" into a
   proof for all g within the bound; state method per property.
6. **FPGA replay (Gates R2/R3).** Curve identity + functional identity on silicon for
   the 2-die fork; never cycle-for-cycle vs sim.
7. **Cross-simulator agreement (optional credibility add).** Re-run the saturation and
   placement cells on NoCDAS (or CHIPSIM if it verifies) — ordinal agreement buys a
   reviewer-proof claim for days of work.
8. **g-at-fixed-S sweep** to close the placement-law open item (§4b) and pin the
   crossover sentence (§4a).

**Gaps / open decisions to resolve before submission.** (i) the serving regime the paper
leads with (footprint-miss vs disaggregated P/D); (ii) the exact crossover wording;
(iii) delivery-count decomposition for the RTL gate table; (iv) whether the 2-die
placement cell is inside `rtl_r1.py diff`; (v) sourcing UCIe pJ/bit or dropping all
bridge energy claims.
