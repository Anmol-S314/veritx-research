# VeritX T3 — Dynamic (Time-Varying) Traffic for Fabric DSE: Research Brief (2026-08-20)

**Author:** Feynman (research agent)
**Status:** primary-source survey + evidence synthesis. Where a claim is my assessment (costs, recommendations, "opinion"), it is flagged **[opinion]**; everything else cites a primary source.
**Companion to:** `outputs/t3-fabric-product-notes-2026-08-19.md` (D1–D10, F6 thesis). This brief answers the open question from that session: *is static-per-phase traffic analysis sufficient, or do we need dynamic (time-varying) simulation for credible fabric recommendations?*

---

## 0. TL;DR (the answer up front)

1. **Yes, published work shows phase-averaged / fixed-matrix analysis can miss material effects** — transient congestion, burst-driven queue buildup, and buffer provisioning under self-similar/bursty traffic are real and are precisely what *constant-rate* injection hides (QuaLe, SynFull, ICCD'08, AMD "Multiphase NoC").
2. **But at our 64-node single-die shared-L2 scope, the effect is most likely on *sizing* (buffers/VCs/saturation headroom), not on *topology ranking*** — consistent with our own measured F6 verdict (session notes, 6b) and with MoX's argument that static routing can suffice for MoE.
3. **Every tool you asked about already accepts trace input or time-varying injection except BookSim2's default steady-state mode.** The cheapest path to *dynamic* validation is (a) extending BookSim2 to replay a time-stamped per-phase trace; the highest-fidelity path is (c) gem5-Garnet replay; (b) FlooNoC RTL is the ground-truth baseline only.

---

## 1. Published methods for dynamic / time-varying NoC traffic (survey, primary sources)

Three traffic-modeling families are standard in the NoC literature (Nonaka/CRISTAL, *Application driven traffic modeling for NoCs*, ACM 2006 — three categories: constant-rate, stochastic/probabilistic, real-trace): 

- **Real-trace replay.** Feed an application's recorded injection stream (time-stamped packets/flits) through a cycle-accurate sim. The strongest community artifacts:
  - **Netrace** — standardized, dependency-annotated network packet trace format + reader library designed for network simulators (used with BookSim). https://github.com/booksim/netrace
  - **MCSL Traffic Suite** (HKUST-GZ) — benchmark suite of 8 real application traces across mesh/torus/fattree topologies, providing both Statistical Traffic Patterns (STP; distribution-based generators, e.g. exponential/mean-variance packet/execution time distributions) and Recorded Traffic Patterns (RTP; real trace replay), packaged for mainstream sims. https://personal.hkust-gz.edu.cn/jiangxu/release/MCSL_Traffic_Suite_User_Manual.pdf
- **Phase-based synthetic traffic.** Compress a long real execution into a *few plateaus* and replay them as synthetic bursts, preserving phase structure cheaply:
  - **SynFull** (ISCA'14, Toronto) — hierarchical macro/micro-phase clustering of a real cache-coherent trace → synthetic per-phase replay. Explicitly argues plain synthetic patterns are "unlikely to be representative of real workloads" and "produce a properly provisioned network." https://www.eecg.utoronto.ca/~enright/ISCA2014-SynFull.pdf
  - **Efficient Synthetic Traffic Models for Large, Complex SoCs** (HPCA'16) — extends SynFull to heterogeneous SoCs (CPU+GPU, full coherence): Markov-model-based generators (like SynFull) with new techniques to extrapolate to larger node counts + a novel synthetic memory reference model replacing SynFull's fixed-latency model. NOTE: no self-similar or on/off generators despite the brief's earlier draft claim. https://jiemingyin.github.io/docs/HPCA2016.pdf
  - **Automatic Phase Detection for Stochastic On-Chip Traffic** (CODES+ISSS'06) — decomposes highly non-regular processor traffic into phases by **analyzing simulation traces** (inspired by processor-arch performance-evaluation techniques; mixture-of-Gaussians style clustering), enabling automatic stochastic traffic-generator construction. NOTE: not Markov-based despite the brief's earlier draft claim. https://www.cs.york.ac.uk/rts/docs/CODES-EMSOFT-CASES-2006/codes/p88.pdf
  - **A Generic Multi-Phase On-Chip Traffic Generation Environment** (Sciweavers) — multi-phase generation + *trace replay* + stochastic traffic in one framework. https://sciweavers.org/publications/generic-multi-phase-chip-traffic-generation-environment
- **Non-stationary / transient modeling.** Explicitly model time-variation rather than equilibrium:
  - **QuaLe** (NoCS'10, Mutlu group ETH) — "Quantum-Leap inspired model for non-stationary analysis of NoC traffic": steady-state/equilibrium analysis is the wrong tool for transient congestion. https://people.inf.ethz.ch/omutlu/pub/quale_nocs10.pdf
  - **NoCLabs / NoCPoint** (Toronto, NOCS'14) — statistical *sampling* of traffic phases to speed up sim while preserving phase-accurate estimates. https://www.eecg.utoronto.ca/~enright/DaiNOCS14.pdf
  - **VNOC 2.0** (Marquette, SOCC'14) — trace-driven cycle-accurate homogeneous-NoC simulator with Orion 2 power model, per-router DVFS, and a **self-similar traffic generator** (Glen Kramer's generator). ⚠️ **License: NON-COMMERCIAL USE ONLY** (author grants use/copy/modify only for non-commercial purposes) — **not product-safe for our pitch**; fine as a research reference/benchmark source. https://github.com/eigenpi/vnoc20

**What they model, cycle-accuracy, cost (my synthesis of the above):**

| Family | Models | Cycle-accuracy | Cost |
|---|---|---|---|
| Real-trace replay (Netrace/MCSL) | exact injection stream, bursts, dependencies | full (cycle-accurate engine) | high (must have a real trace) |
| Phase-based synth (SynFull/HPCA'16) | phase plateaus + on/off bursts | cycle-level (synthetic) | low-moderate, fast |
| Non-stationary (QuaLe) | time-varying arrival statistics | analytical-ish / fast | low |
| Steady-state fixed matrix (our current) | single mean rate, no time axis | cycle-level | lowest |

**Fact:** bursty/self-similar inter-arrivals break Poisson-based analysis — "exponentially distributed packet inter-arrivals" assumptions "may be inappropriate in the presence of self-similar traffic," inflating needed buffer sizes (Tavakkol/ICCD'08). https://tavakkol.ch/downloads/papers/A.Tavakkol-ICCD2008.pdf

---

## 2. Does static-per-phase miss material effects (our MoE case)?

**Our current setup:** one matrix per phase (dispatch / ALLGATHER / REDUCESCATTER), each simulated as a separate steady-state BookSim2 run at a constant injection rate. This is exactly the "constant-rate" family (Sec 1).

**What that hides (sourced):**
1. **Intra-phase burstiness & correlation.** A phase's *mean* matrix discards the burst envelope. Self-similar/bursty traffic demands different buffer sizing than Poisson at the same mean (ICCD'08, above). Dispatch is a concentrated all-to-all-style burst, not a smooth Poisson mean.
2. **Inter-phase coupling / drain transient.** Running phases independently discards the boundary: flits queued at the end of Dispatch that should drain into the next phase, and congestion backpressure feeding back into injection. Multiphase behavior is explicitly an industry concern — AMD's "Multiphase NoC" doc states paths active in one phase can be idle in another, and designing all paths at max bandwidth over- or under-provisions the compiler's solution. https://docs.amd.com/r/en-US/pg406-network-on-chip/Multiphase-NoC
3. **Config must survive ALL phases, not each in isolation.** A config picked on phase-averaged traffic may be great on average yet saturate under the Dispatch burst (itself the highest-traffic phase). This is a *joint design* question a per-phase split cannot answer.

**Counter-evidence that static may be acceptable at our scope (sourced + ours):**
- **MoX** (arXiv 2607.20220): argues offline-optimized **static** routing with precomputed link weights handles MoE traffic on direct-connect topologies "without the need for... dynamic topology reconfiguration." https://arxiv.org/html/2607.20220
- **Our own measured F6 result (session notes 6b, honest)**: at 64-node single-die with real Qwen MoE traffic, memory-class traffic changed **sizing/saturation headroom** (~40% of load over-rates mesh/torus) but did NOT flip the topology winner. So at 64 nodes, the dynamic-vs-static material difference concentrates in *provisioning* (buffers/VCs/saturation point), not the topology pick.

**Bottom line [opinion]:** static-per-phase is *sufficient to rank topologies at 64 nodes* but *not sufficient to size the fabric* (VC/buffer/saturation). The dynamic question matters exactly where the F6 margin lives — provisioning, not ranking. To make provisioning claims credible we need at least a phase-sequenced / trace-replayed run.

---

## 3. Tool capability matrix (traffic input formats, trace replay, cycle-accuracy)

All links are primary (source code or official docs).

| Tool | Traffic input formats | Time-varying injection? | Real time-stamped trace replay? | Cycle-accuracy / cost |
|---|---|---|---|---|
| **BookSim2** | synthetic patterns + **per-class rates** (`classes=N; traffic=...; injection_rate=...`), `netrace` dependency-trace reader | per-class (simultaneous, fixed means) only; no native phase sequencing | **Yes via `netrace`**; otherwise static-mean Poisson | cycle-level, very fast. Manual: https://github.com/booksim/booksim2/blob/master/doc/manual.tex ; trafficmanager.hpp (class support) https://github.com/kingpoem/booksim2/blob/2b351556/src/trafficmanager.hpp ; netrace https://github.com/booksim/netrace ; ISPASS'13 https://icn.kaist.ac.kr/~jjk12/papers/2013ISPASS.pdf |
| **Noxim** | probability table **and** traffic-table / trace mode (per-cycle injection rates, cycle-indexed), YAML config | Yes (cycle-indexed table) | Yes (trace mode) | cycle-level SystemC, fast-moderate. https://github.com/davidepatti/noxim |
| **FlooNoC** (RTL) | **DMA job files** (time-stamped AXI DMA transaction lists), generated from **YAML traffic configs** (`traffic_flows: initiator/endpoint/rw/narrow_burst/wide_burst`) or built-in patterns (random/hbm/onehop/bit_complement/bit_reverse/bit_rotation/neighbor/shuffle/transpose/tornado/single_dest_*) | Yes (time-stamped bursts via DMA jobs) | Yes (job files = real transaction traces) | RTL/bit-true, slow (ground truth). Traffic gen lives in floogen (in-repo source) but is NOT in the PyPI floogen 0.8.4 build and NOT merged to main — it's PR #182 (`gen_jobs.py` + `traffic_cfg`, closed 2025). Requires building floogen from repo source. https://github.com/pulp-platform/FlooNoC/blob/main/floogen/model/traffic.py ; traffic example config https://github.com/pulp-platform/FlooNoC/blob/main/floogen/examples/traffic/nw_mesh_xy.yml ; PR#182 https://github.com/pulp-platform/FlooNoC/pull/182 |
| **gem5-Garnet** | Ruby `ruby_random_test` synthetic; **TrafficGen** (state-graph generator incl. *replay of captured traces*, Markov transitions); **TraceGen** (replay time-stamped transaction trace); **TraceCPU** (elastic annotated-trace replay) | Yes (TraceGen/TrafficGen graphs) | **Yes (TraceGen, TraceCPU)** | cycle-accurate Garnet2.0 NoC, moderate speed. TraceGen https://doxygen.gem5.org/release/current/classgem5_1_1TraceGen.html ; TraceCPU https://www.gem5.org/documentation/general_docs/cpu_models/TraceCPU ; TrafficGen explained https://cnlelema.github.io/memo/en/arch/basics/gem5/traffic-gen/ (secondary) |
| **SST** (memHierarchy + Merlin) | `StandardMemory` endpoints; pattern/trace generators: Miranda (patterns), **Prospero** (trace), ZoDiaC (trace), Ariel (PIN); Merlin NoC | Yes (multiple generators) | Yes (Prospero/Zodiac trace replay) | cycle-level, MPI-scalable, moderate-slow. memHierarchy https://sstsimulator.github.io/sst-docs/docs/elements/memHierarchy/intro ; Scratchpad https://github.com/sstsimulator/sst-elements/blob/master/src/sst/elements/memHierarchy/scratchpad.h |
| **ASTRA-sim** | workload layer via **Chakra Execution Trace** (real or synthetic) or native collectives/**STAGE** synthetic; network backends = **Analytical, ns-3, Garnet** | Yes (trace / ns-3 events) | Yes (Chakra ET replay) | network-fidelity varies: analytical fast, ns-3 packet-level, Garnet cycle-accurate. https://astra-sim.github.io/astra-sim-docs/getting-started/argument-workload-config.html ; backends https://astra-sim.github.io/astra-sim-docs/network-backend/network-backend.html ; ns-3 https://astra-sim.github.io/astra-sim-docs/network-backend/ns3-network-backend.html ; STAGE https://github.com/astra-sim/stage |
| **CHI** (protocol) | CHI REQ/SNP **access-sequence files**: `coh_noc` (SV RTL 2D-mesh CHI, CMN-600/700-style), `coroutine_sim` (C++20 discrete-event, cycle-driven transactions), `CHI-Test` (SV testbench, access/snoop sequences) | Yes (cycle-driven sequences) | Yes (access sequences) | RTL / discrete-event; focuses on coherency, not general fabric DSE. coh_noc https://github.com/tangyangchao578-art/coh_noc ; coroutine_sim https://github.com/eanorige/coroutine_sim ; CHI-Test https://github.com/XiaBin520/CHI-Test |

**Key takeaway [fact]:** every candidate *except* BookSim2's default mode already natively takes time-stamped traces or time-varying injection. BookSim2's *static* behavior is a modeling **choice**, not a capability limit — it links `netrace` for trace replay, so a time-stamped per-phase trace can drive it with modest effort.

---

## 4. Cost / fidelity of giving the DSE dynamic traffic — recommendation

Costs are **my estimates [opinion]**, scaled to one engineer on our box (14G RAM, 4GB GPU, no big-GPU elsewhere). Fidelity vs. a cycle-accurate RTL baseline is qualitative.

| Option | Build cost | Run cost | Fidelity vs RTL baseline | Strengths / limits |
|---|---|---|---|---|
| **(a) Phase series sequenced through BookSim2** (extend TrafficManager to time-slice injection across a per-phase matrix+burst schedule, or feed a netrace per-phase trace) | **Low–Med (~0.5–2 wk)** | **Very low** (fast; drives DSE sweep) | **Med.** cycle-accurate engine but phase-averaged injection — captures config-sharing across phases + drain if state carried; misses intra-phase burstiness unless burst envelope added | Smallest delta on existing engine; directly answers "does phase-aware config rank differently?" |
| **(b) FlooNoC RTL with job files** (real time-stamped DMA traffic) | **High (2–6 wk**: RTL sim env, Verilator/cocotb, 64-node job-file gen) | **High** (minutes–hours per config) | **Gold / ground truth** (actual RTL, bit-true timing) | Not a DSE sweep tool; the *calibration/reference* baseline for a handful of final configs |
| **(c) gem5-Garnet with real trace replay** (TraceGen over per-phase time-stamped memory+collective trace) | **Med (1–3 wk**: trace-gen from dispatcher + Garnet topo/routing/VC config) | **Med** (Ruby/Garnet; sample/truncate the 131M-cycle window) | **High.** real trace, transient + drain + backpressure, cycle-accurate NoC | Best dynamic *proof* engine short of RTL; aligns with D9 (SST/gem5 = validator only) |
| **(d) Custom synthetic dynamic generator** (SynFull-style phase + on/off Markov + burst multiplier) | **Med (2–4 wk)** | **Low–Med** | Depends on generator fidelity — good for *sensitivity* (how much does burstiness matter) not absolute proof | Best for stressing "which dynamics matter" before committing to full trace infra |

**Recommendation [opinion]:**
- **v1 (now, cheap): (a).** Extend BookSim2 to replay a per-phase time-stamped trace (netrace) or time-slice injection with inter-phase drain and retained buffer state. This is the smallest change that removes the *static-per-phase* assumption from the existing engine, keeps DSE sweep speed, and lets us test whether dynamic-aware config ranking differs at 64 nodes. Cross-check a half-dozen configs with (c).
- **2–3-yr product: (c) gem5-Garnet trace replay as the dynamic validation engine**, with occasional **(b) FlooNoC RTL** as the bit-true ground truth for a handful of final configs. Use **(d)** as a lightweight sensitivity generator to inform the analytical model's error bars. This matches D9 (never build a cycle-accurate engine; SST/gem5/RTL validate the fast model).

---

## 5. Prior work on co-designing the fabric for a *dynamically changing* workload (F6 analogues)

These are the closest published analogues to the F6 thesis — fabric decisions (topology/VC/buffer/arbitration/frequency) made *because* the workload's traffic changes over time:

- **mFabric** (arXiv 2501.03905) — **MoE training** fabric with millisecond-scale OCS topology reconfiguration; regionally reconfigurable high-bandwidth domain over electrical interconnects. Directly MoE + dynamic topology. (Note: arXiv title was "mFabric" v1/v2; camera-ready at SIGCOMM'25 renamed to **MixNet**.) https://arxiv.org/html/2501.03905v1
- **MoX** (arXiv 2607.20220) — **counterpoint**: argues efficient MoE routing on direct-connect topologies needs **no** dynamic reconfiguration if link weights are precomputed well. https://arxiv.org/html/2607.20220
- **Dynamic In-Switch Computing for MoE** (arXiv 2605.05607) — dispatch/combine inefficiency (redundant cross-GPU data movement) as first-order MoE fabric concern. https://arxiv.org/html/2605.05607
- **ReNoC** (ACM TACO'11) — *reconfigurable NoC*: synthesize an application-specific logical topology, reconfigure per application; routing made deadlock-free per config. https://dl.acm.org/doi/10.1145/2043662.2043669
- **Application-Aware Topology Reconfiguration** (TVLSI'10) — runtime topology tailoring driven by a light control network that monitors heavy flows and reconfigures to cut hop count. https://dl.acm.org/doi/10.1109/TVLSI.2010.2066586
- **PhaseNoC** (DATE'15) — **TDM scheduling at the virtual-channel** allocated per phase, for flow isolation under phase-varying active sets. https://gdimitrak.github.io/papers/date15-phasenoc.pdf
- **RACE** (arXiv 2205.13130) — RL that adjusts **NoC channel-buffer directions** as buffer demand changes with application phases. https://arxiv.org/pdf/2205.13130
- **Agile** (HPCA-track/GWU) — RL predicting NoC traffic to select **power-gating / DVFS / architecture configuration** at runtime. https://hpcat.seas.gwu.edu/assets/files/Agile_A_Learning-Enabled_Power_and_Performance-Efficient_Network-on-Chip_Design.pdf
- **A case for dynamic frequency tuning in on-chip networks** (MICRO'09) — network load varies over time; fixed-frequency routers waste or underperform. https://dl.acm.org/doi/10.1145/1669112.1669151
- **Multiphase NoC** (AMD Xilinx PG406, industry) — NoC compiler that accepts *per-phase* bandwidth requirements rather than all-max. https://docs.amd.com/r/en-US/pg406-network-on-chip/Multiphase-NoC
- **Collective-capable NoC for large-scale ML** (MLSys'26) — on-chip AllGather/ReduceScatter enablement in an ML NoC (our dispatch/ALLGATHER/REDUCESCATTER regimes). https://proceedings.mlsys.org/paper_files/paper/2026/file/48fecef47b19fe501d27d338b6d52582-Paper-Conference.pdf

**Gap vs. F6 [opinion]:** prior work reconfigures topology/routing/VF/buffers *at runtime in hardware* — none offers a *design-time DSE tool* that, given a phase-sequenced real workload trace, *recommends* the fabric+router config and proves it cycle-accurately. That white space (existing session finding) is where F6 sits; the dynamic-traffic engine is the missing undercarriage.

---

## 6. Open questions

- Does a phase-sequenced BookSim2 run flip any config ranking at 64 nodes, or only saturation/VC headroom (as our 6b result suggests)? → cheap to test with (a).
- Is the 131M-cycle window representable in gem5-Garnet by sampling (which phases/bursts) without losing the drain transient?
- Should the burst envelope (not just per-phase mean) be part of the *objective*, since provisioning is where dynamics bite?
- MoX argues static suffices for MoE routing; does that extend to *sizing*, and at what die count does dynamic traffic change the topology pick (our 6b: not at 64)?

---

## 7. Sources (primary)

Surveys/methods: MCSL https://personal.hkust-gz.edu.cn/jiangxu/release/MCSL_Traffic_Suite_User_Manual.pdf · SynFull https://www.eecg.utoronto.ca/~enright/ISCA2014-SynFull.pdf · HPCA'16 https://jiemingyin.github.io/docs/HPCA2016.pdf · QuaLe https://people.inf.ethz.ch/omutlu/pub/quale_nocs10.pdf · CODES+ISSS'06 phases https://www.cs.york.ac.uk/rts/docs/CODES-EMSOFT-CASES-2006/codes/p88.pdf · multi-phase gen https://sciweavers.org/publications/generic-multi-phase-chip-traffic-generation-environment · application-driven modeling https://dl.acm.org/doi/10.1145/1150343.1150364 · NoCLabs/NoCPoint https://www.eecg.utoronto.ca/~enright/DaiNOCS14.pdf · buffer-sizing self-similar ICCD'08 https://tavakkol.ch/downloads/papers/A.Tavakkol-ICCD2008.pdf

Effects: AMD Multiphase NoC https://docs.amd.com/r/en-US/pg406-network-on-chip/Multiphase-NoC · MICRO'09 dynamic freq https://dl.acm.org/doi/10.1145/1669112.1669151 · RACE https://arxiv.org/pdf/2205.13130

Tools: BookSim2 manual https://github.com/booksim/booksim2/blob/master/doc/manual.tex · trafficmanager.hpp https://github.com/kingpoem/booksim2/blob/2b351556/src/trafficmanager.hpp · netrace https://github.com/booksim/netrace · BookSim2 ISPASS'13 https://icn.kaist.ac.kr/~jjk12/papers/2013ISPASS.pdf · Noxim https://github.com/davidepatti/noxim · FlooNoC getting-started https://pulp-platform.github.io/FlooNoC/floonoc/getting_started/ · FlooNoC traffic model (in-repo floogen) https://github.com/pulp-platform/FlooNoC/blob/main/floogen/model/traffic.py · FlooDMA PR182 https://github.com/pulp-platform/FlooNoC/pull/182 · gem5 TraceGen https://doxygen.gem5.org/release/current/classgem5_1_1TraceGen.html · TraceCPU https://www.gem5.org/documentation/general_docs/cpu_models/TraceCPU · SST memHierarchy https://sstsimulator.github.io/sst-docs/docs/elements/memHierarchy/intro · Scratchpad https://github.com/sstsimulator/sst-elements/blob/master/src/sst/elements/memHierarchy/scratchpad.h · ASTRA-sim workload https://astra-sim.github.io/astra-sim-docs/getting-started/argument-workload-config.html · ASTRA-sim backends https://astra-sim.github.io/astra-sim-docs/network-backend/network-backend.html · ASTRA-sim ns3 https://astra-sim.github.io/astra-sim-docs/network-backend/ns3-network-backend.html · STAGE https://github.com/astra-sim/stage · CHI: coh_noc https://github.com/tangyangchao578-art/coh_noc · coroutine_sim https://github.com/eanorige/coroutine_sim · CHI-Test https://github.com/XiaBin520/CHI-Test

F6 analogues: mFabric (a.k.a. MixNet SIGCOMM'25) https://arxiv.org/html/2501.03905v1 · MoX https://arxiv.org/html/2607.20220 · MoE in-switch https://arxiv.org/html/2605.05607 · ReNoC https://dl.acm.org/doi/10.1145/2043662.2043669 · App-aware topology reconfig https://dl.acm.org/doi/10.1109/TVLSI.2010.2066586 · PhaseNoC https://gdimitrak.github.io/papers/date15-phasenoc.pdf · Agile https://hpcat.seas.gwu.edu/assets/files/Agile_A_Learning-Enabled_Power_and_Performance-Efficient_Network-on-Chip_Design.pdf · collective NoC MLSys'26 https://proceedings.mlsys.org/paper_files/paper/2026/file/48fecef47b19fe501d27d338b6d52582-Paper-Conference.pdf

---

## 8. Primary-source verification pass (2026-08-20, Dave)

Cross-checked the key claims above against the actual papers/sources (PDFs downloaded to `research-vendor/dyn-traffic/pdfs/`, extracted with pdftotext). Results:

**Verified accurate:**
- SynFull quotes — "unlikely to be representative of real workloads", "properly provisioned network" — both verbatim in ISCA'14 PDF.
- QuaLe title — "Quantum-Leap Inspired Model for Non-Stationary Analysis of NoC Traffic in Chip Multi-Processors" — verbatim.
- ICCD'08 — "assumptions such as exponentially-distributed packet inter-arrivals... may be inappropriate in the presence of self-similar traffic" — verbatim; paper's whole point is optimal buffer sizing under self-similar (PPBP) traffic.
- ACM'06 taxonomy — "three methods: constant injection rate, probability functions, trace based" — confirmed via abstract excerpt (ACM page itself is Cloudflare-blocked).
- MoX (arXiv 2607.20220) — abstract verbatim: "efficient offline-optimized routing... without the need for... dynamic topology reconfiguration" — confirmed; it's a Jul-2026 paper (real, not hallucinated).
- mFabric — arXiv 2501.03905 v1/v2 titled "mFabric"; SIGCOMM'25 camera-ready renamed **MixNet** — both confirmed (same DOI 10.1145/3718958.3750465).
- MCSL — 8 real applications, STP (statistical/distribution-based) + RTP (recorded/replayed), mesh/torus/fattree — confirmed from User Manual.
- VNOC 2.0 — trace-driven cycle-accurate, Orion 2 power, per-router DVFS, self-similar generator — confirmed from repo README. **License is NON-COMMERCIAL USE ONLY** (author's copyright notice) — flagged for product risk; NOT added to the tool matrix above because it's not a viable product dependency.

**CORRECTED in this pass (draft errors):**
- HPCA'16 does NOT use "on/off (Markov) and self-similar generators" — it's SynFull-style **Markov models** extended to heterogeneous SoCs + scaling techniques + a synthetic memory-reference model; no self-similar/on-off generators (0 occurrences in the PDF). Fixed above.
- CODES+ISSS'06 phase detection is **not Markov-based** — it detects phases by analyzing simulation traces (mixture-of-Gaussians-style clustering of trace statistics); "Markov" appears 0 times. Fixed above.
- FlooNoC traffic generation — the brief originally cited `floogen traffic` subcommand + `util/gen_jobs.py`; **neither exists in the released floogen 0.8.4 (PyPI) or on FlooNoC main**. Traffic generation is real but lives in the in-repo floogen source (floogen/model/traffic.py, `traffic_flows` YAML configs → DMA job files) as unmerged PR #182. Requires building floogen from repo source. Corrected in the tool matrix.
- mFabric → MixNet rename noted (arXiv title vs SIGCOMM'25 title).
- MCSL described more precisely (STP/RTP; it is a trace suite, not a generic tunable generator).

**Not yet verified (blocked):** AMD Multiphase NoC doc (JS-gated, couldn't fetch) and the ACM'06 full text (Cloudflare) — both corroborated via secondary excerpts; CHI repos (coh_noc/coroutine_sim/CHI-Test) not fetched (low risk — existence verifiable via GitHub URLs in sources section).

**Bottom line after verification:** the brief's TL;DR and recommendations (options (a)/(b)/(c)/(d), §4) stand unchanged; the corrections are all in supporting detail (mechanisms, licenses, precise claims), not in the strategic conclusion.
