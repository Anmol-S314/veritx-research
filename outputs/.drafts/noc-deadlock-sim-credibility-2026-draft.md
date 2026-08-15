# Literature Survey 2026: NoC Deadlock Analysis & Simulator Credibility (arXiv / Google Scholar check, 2025–2026)

- **Date:** 2026-08-14
- **Scope:** calendar 2026 primary, 2025 for context; older work only as grounding. Sources: arXiv (metadata/abstracts/HTML), Google Scholar (via web search), official tool docs, venue program pages. **No PDF bodies were parsed** (workflow rule); PDF-only sources are cited from search metadata with full-text parsing marked blocked.
- **Extends (does not duplicate):** `docs/research/simulator-credibility-noc-literature.md`, `docs/research/simulator-landscape-2026.md` (both 2026-08-12).
- **Feeds:** 0344/F14 deadlock forensics (BookSim-vs-RTL routing divergence on a 2-die mesh + bridge, single VC), the sim↔RTL credibility gate, paper framing (exact% 83–98 vs 99.85).

---

## 0. Executive summary

1. **Deadlock, 2025–2026: DOR is still the reference "guaranteed deadlock-free" scheme, and single-VC / low-VC deadlock freedom is an active, solved-in-principle problem.** The 2026 literature explicitly names DOR's deadlock freedom as the property you give up when deviating (Q-StaR [S2]); the closest analog to the project's multi-die bridge, HPCA 2026's Deadlock-Free Bridge Module, treats inter-chiplet deadlock with a single-VC-safe mechanism (injection control at the bridge, ~2.5% area) [S3]; TERA (HOTI 2025) achieves deadlock freedom with *zero* VCs via an embedded acyclic subnetwork [S7]. The Dally–Seitz channel-dependency-graph (CDG) acyclicity standard remains the operative criterion [S15].
2. **No 2025–2026 automated routing-table/CDG deadlock checker or DOR-vs-table-routing comparison was found** — the exact gap the project's routing-divergence analysis sits in. Closest anchors: a formal torus-routing construction (ACM TECS 2025) [S6] and industrial formal flows arguing simulation cannot reliably expose deadlock (DVCon US 2025/2026) [S8][S9].
3. **Sim↔RTL credibility, 2025–2026: the per-flit/per-cycle RTL gate remains unpublished.** No 2025–2026 paper gates a software NoC simulator against RTL at flit/cycle granularity [T2 brief, Q1]. The best in-window comparators are benchmark-level calibration (Microarchitecture Cliffs: XS-GEM5 error 59.2% → 1.4% vs RTL [S17]) and request-level validation (LLMServingSim 2.0, ISPASS 2026 Best Paper: 0.95% average error vs real vLLM [S31][S32]). Artifact-evaluation criteria (ACM policy, MICRO 2026/ISCA 2026) still require no RTL-agreement [S26].
4. **The 2026 toolchain landscape:** ASTRA-sim 3.0 is announced (arXiv + ISCA 2026 tutorial) but **code is not yet public** (README still v2.0; issue #380 open) [S40][S41][S42]; gem5 v25.x shipped no NoC/Garnet changes (Garnet3+vnets are pre-existing) [S44][S45]; **BookSim upstream has had no commits since 2024-06-24 and no 3.x exists** — the project's maintained fork is the de-facto continuation [S48][S49]; licensing flags on CHIPSIM/LEGOSim/PLENA (no LICENSE files) [S52][S55][S58].
5. **AI-accelerator/LLM interconnect, 2025–2026: validation norms are aggregate-% (request-level or RMSE), not per-flit.** Serving simulators now routinely publish single-digit % error vs real engines (0.95%–5.35%) [S31][S33][S34][S35][S36]; the deepest chiplet/hardware validation found is DICE (ISCA 2026) at 29.4% RMSE vs real AMD EPYC C2C latency (vs 46.4% for the prior baseline) [S37], and C2C-Explorer (Aug 2026) at 2.46–8.23% end-to-end timing error vs FPGA prototypes [S38]. No 2025–2026 work validates simulated KV-cache serving traffic at the NoC/flit level against real inference traces (gap) [T4 brief, Q6].
6. **Project implication (inference):** a documented per-flit RTL↔BookSim gate at 83–98% exactness with characterized residual families would exceed every published 2025–2026 validation norm found in this survey — stronger than the year's Best-Paper example (request-level), the year's RTL-calibration example (benchmark-level), and the year's deepest hardware validation (RMSE-level). No reviewer-facing standard found in the window requires per-flit cycle exactness.

---

## 1. Q1 — NoC deadlock analysis & deadlock-freedom verification (2025–2026)

### 1.1 DOR remains the reference deadlock-free baseline; deviations remove the structural guarantee
- **Q-StaR** (arXiv:2603.10637, Mar 2026) opens from the premise that DOR is "widely adopted for its favorable properties like low hardware cost, in-order transmission, and **guaranteed deadlock freedom**", and proposes BiDOR (bidirectional DOR) + an N-Rank load-trend metric to rebalance load while "retaining simplicity and predictability" (+42.9% throughput vs DOR per abstract) [S2]. *Inference (labeled):* the project's Dijkstra/table-based route set that diverges from DOR removed exactly this by-construction guarantee; no 2025–2026 paper states this about any specific project setup — it follows from [S2][S15].

### 1.2 Multi-die / chiplet-bridge deadlock is a named, active 2026 problem — solved by isolation, not extra VCs
- **Deadlock-Free Bridge Module (DFBM), HPCA 2026** (Chen, Fu, Wang, Zhou; NUDT; Feb 2 2026 session "Cache Coherence and Chiplet Interconnects"): inter-chiplet deadlock arises when integrating chiplets onto an interposer; prior fixes (turn restrictions, VC isolation, injection control, escape channels, bubble flow control) require knowledge of each chiplet's internal NoC; DFBM infers inter-chiplet packet-transmission behavior from coherence-protocol flow dependencies and uses **packet-injection control** to isolate inter- vs intra-chiplet traffic, at ~2.5% area overhead [S3]. *Direct relevance (inference):* this is the closest 2026 published analog to the project's "multi-die bridge, single VC" hang, and its premise is that even deadlock-free intra-die routing does not make the bridge safe.
- Context lines: **ReD** (IEEE TCAD, Dec 2024) and **DeFT** (arXiv:2112.09234, 2021) are the prior 2.5-D interposer deadlock-free routing work DFBM builds on/competes with (out of window, context only) [S21][S22].

### 1.3 The literature is moving away from VCs as the default deadlock mechanism
- **TERA** (HOTI 2025; arXiv:2510.14730): deadlock-free non-minimal routing for full-mesh **without VCs**, via an embedded physical acyclic subnetwork; 80% improvement over link-ordering on adversarial traffic; ~50% less buffering vs VC approaches [S7].
- **Physically-Aware Preemptive VCs** (Leone, Colagrande, Benini — PULP; arXiv:2607.01430, Jul 2026): four deadlock-free AXI4 traffic-class separation schemes; Preemptive VCs "save up to 76% of link resources with comparable frequency and only 3% router area overhead" vs multiplane baseline. Key premise: "In AXI4 systems, protocol-level dependencies between read and write traffic can create circular waits at the network endpoints, **even when the routing algorithm itself is deadlock-free**" [S1]. *Implication (inference):* protocol-level (endpoint) dependency cycles are a distinct second deadlock class in 2025–2026 discourse — relevant when diagnosing a hang that persists after routing fixes.
- **TONS** (Green et al.; arXiv:2605.27963, May 2026; Google TPU v4/5p): "a deadlock-free routing scheme compatible with **limited virtual channels** and optical switch faults", enabling 2.1×/1.6× geomean speedups over best TPU torus variants [S10].
- **Efficient Deadlock Avoidance** (Srivastava et al.; IEEE CAL 24(2), 2025): stall-based deadlock avoidance has a shortcoming that can itself deadlock; combining stall, message-dependency and topology analyses avoids it (PDF body blocked; abstract-level) [S5].

### 1.4 Formal/automated deadlock verification: industrial property-based flows; no new SAT/SMT/model-checking tooling found
- **DVCon US 2026** — "Scaling Formal Verification of Network On Chip Using Path Decomposition" (10xEngineers/LUMS): simulation "struggle[s] to handle the distributed, parallel, and reactive behavior of modern NoC architectures… limiting coverage and confidence in detecting critical behaviors such as deadlock, livelock, and starvation"; proposes scalable path decomposition (PDF blocked; session listing + abstract) [S8].
- **DVCon US 2025** — "Hierarchical Formal Verification and Progress Checking of Network-On-Chip Design": formal testbenches with guaranteed data delivery + forward-progress checks; end-to-end deadlock checks noted as hard due to tool capacity (PDF blocked) [S9].
- **Negative finding:** no 2025–2026 paper was found applying Z3/SMT or nuSMV/Spin-style model checking specifically to NoC deadlock/CDG cycle detection. Prior art is older (ILP-based deadlock-free routing construction, IEEE 2023 [S24]; EbDa ISCA 2017 [S23]; GeNoC TODAES 2012). Stated per the brief's "no work found" rule.
- **Theory side:** Mendlovic (arXiv:2503.04583, 2025, math) proves a necessary-and-sufficient graph condition for existence of any deadlock-free routing (two edge-disjoint directed trees rooted at one node) — insight for design/verification tools, not directly constructive [S4]. Bentert et al. (arXiv:2601.03934, Jan 2026) show checking static re-route rule sets for resilience is coNP-complete (adjacent domain: datacenter fast re-routing) [S16].

### 1.5 Bufferless/deflection routing: latency work, no new deadlock-freedom results
- Deflection protocol reducing worst-case latency (York/Indrusiak group; arXiv:2510.11361, Oct 2025): header-not-payload deflection cuts traffic and worst-case latency — a timing result, no deadlock claim confirmed [S13].
- Predictable deflection routing in routerless NoCs (Sayuti & Indrusiak; IEEE MCSoC 2025): per-flow deflection bounding via evolutionary optimization — predictability, not deadlock [S14].
- No 2025–2026 deadlock-freedom result specific to bufferless NoCs found; prior art is pre-2025 (BLESS/CHIPPER/MinBD line) [T1 brief Q3].

### 1.6 Deadlock in AI-accelerator/wafer-scale networks (2025–2026)
- TONS (above) is the clearest statement that AI-accelerator networks need limited-VC deadlock-free co-design [S10].
- HPCA 2026 DFBM (above) covers chiplet-interconnect deadlock [S3].
- Adjacent (no deadlock claim in abstract): wafer-on-wafer network design (Iff et al., arXiv:2603.05266) [S19]; Shiftfly optical-tier interconnect (Krause et al., arXiv:2608.00897) [S20].

### 1.7 Gap note (Q1-specific)
No 2025–2026 paper found that (a) compares DOR vs table/Dijkstra routing deadlock-freedom in a mesh, or (b) ships an automated tool that analyzes a NoC routing table for CDG cycles. Nearest analogs: InfiniBand Dragonfly deadlock-free routing configuration (arXiv:2502.01214, off-chip domain) [S18]; the TECS 2025 formal torus construction [S6]; EbDa theory [S23]. **A routing-table CDG checker would be novel relative to the 2025–2026 window searched.**

---

## 2. Q2 — Simulator↔RTL validation & credibility (2025–2026)

### 2.1 Headline: no per-flit/per-cycle sim↔RTL gate published through mid-2026
RTL appears in 2025–2026 work as in-the-loop *infrastructure* or as ground truth for *model calibration*, never as a per-flit agreement target:
- **Microarchitecture Cliffs** (arXiv:2602.11580, Feb 2026): closest analog — benchmark-generation methodology calibrating the XS-GEM5 CPU model against XiangShan RTL: "We reduce the performance error of XS-GEM5 from 59.2% to just 1.4% on the Cliff benchmarks." Granularity: benchmark/performance-error, not per-flit [S17].
- **UniCNet** (IEEE CAL 25(1):37–40, 2026; DOI 10.1109/LCA.2026.3653809): chiplet NoC simulator whose README claims the UCIe interface model is "verified against RTL model" — granularity (per-flit vs aggregate) not stated; needs full-text check (PDF blocked). Same accuracy as BookSim 2.0, 4× parallel speedup (simulator-vs-simulator) [S23].
- **HyNoC** (arXiv:2607.02729, Jul 2026): open-source RTL NoC; "Verilator co-simulation measures the deterministic per-hop latency" of *its own* RTL — RTL-as-ground-truth for self-measurement, not an independent gate [S19 in T2 numbering → S24]. *(Numbering: see Sources; T2-S13.)*
- **Rhea** (arXiv:2508.03837, 2025; v2 2026): gem5 + Verilator co-sim for RTL cache-coherent memory subsystems; "higher fidelity by simulating real RTL hardware" at up to 2.7× overhead — memory subsystem, no timing-agreement gate [S20 in T2 → S25].
- **UVM-TLM co-sim for RISC-V** (arXiv:2505.10145, 2025): methodology "prioritizes integration, simulation efficiency, and acceptable fidelity for architectural exploration **over cycle-level precision**" — explicit 2025 statement that non-cycle-precise co-sim is accepted practice [S26].
- **NoCFuzzer** (IEEE TCAD 2025): UVM-based functional NoC verification (fuzzing); argues Verilator open-source flows "offer limited support for SystemVerilog and UVM" — functional verification, not timing agreement [S27].
- Closest *cycle-level* RTL-validation precedent anywhere: **ONNXim** (IEEE CAL 2024, out of window): "average absolute error of 0.23%" vs Gemmini RTL for an NPU core model [S28].

### 2.2 What 2025–2026 papers report as validation (quantified)
- **System-level (the validated tier):** LLMServingSim 2.0 (ISPASS 2026 Best Paper): avg error 0.95% vs real deployments [S31]; official docs: 300-request ShareGPT replay vs vLLM v0.19.0 on RTXPRO6000, TTFT/TPOT/latency means within ~2.5% (3 configs incl. DP2×EP2 MoE) [S32]. SCALE-Sim TPU: vs Google TPU v4, strong linear correlation; learned elementwise models <3% median relative error [S29]. ATLAHS: "<5% error" — validation reference target (hardware vs traces) not stated in abstract (uncertain) [S30].
- **Memory-system validation is being actively litigated:** "Cleaning up the Mess: Re-Evaluating the Real-System Modeling Accuracy of Ramulator 2.0" (ISPASS 2026) attributes the prior "poor accuracy" claims to "demonstrable technical misconfigurations" [S15 in T2 → S33]. "Different Perspectives of Memory System Simulation" (2026) argues the application view is the ultimate correctness measure; documents residuals up to 214 ns at saturation and warns "internal simulator statistics are not only insufficient, but could be misleading" [S34].
- **NoC-specific 2025–2026:** mostly simulator-vs-simulator or nothing. UniCNet vs BookSim (same accuracy, 4× speedup) [S23]; CAMINOS (JPDC 2025) abstract contains no validation claims (PDF blocked) [S35]; scNoCSim (2026) says "case studies with validation" (nature unclear) [S36]; FlexNoC (ISPASS 2026) metadata only (PDF/paywall blocked) [S37 in T2 → S38].
- **Industry:** AMD UG1388 (2026.1): "The SystemC model simulates much faster but is cycle approximate and less accurate compared to the SystemVerilog model" — the RTL-vs-TLM fidelity gap is documented in current industry docs [S39].

### 2.3 Credibility methodology & venues
- **CAMS 2025** (workshop with MICRO 2025) explicitly solicited "Hardware-in-the-loop Simulation" and "Validation Techniques" papers + tool-release talks [S40 in T2 → S41].
- **gem5 reproducibility work** (ISPASS 2026): standardized resources (2000+ artifacts, disk images, Suites/MultiSim) [S42].
- **Noxim** added a deterministic regression suite with pinned YAML configs and golden outputs in April 2026 (`./regression.sh`) — reproducibility-as-validation in a mainstream NoC simulator [S43].
- **Artifact evaluation criteria unchanged:** MICRO 2026 and ISCA 2026 AE run the current ACM Artifact Review and Badging policy; no 2025–2026 revision adds an RTL/second-model agreement requirement [S44].
- **rtl2booksim** (the only named "connect RTL to BookSim" tool): last code push 2015-11-02, 25 stars, no 2025–2026 activity or usage found [S45].

### 2.4 BookSim's RTL-validation baseline: cited, not re-run
BookSim 2.0 (ISPASS 2013; ≤5% latency / ≤3% throughput vs RTL router on 3×3 mesh, 1 VC, 100K cycles) has **814 citations** (Semantic Scholar, checked 2026-08-14) with dozens of 2025–2026 citing works (DICE ISCA'26, C2C-Explorer, CAMINOS, UniCNet, CHIPSIM, scNoCSim, ReNoC-ML, …) [S46]. 2025–2026 NoC papers benchmark *against* BookSim, not against RTL [S23][S47]. No 2025–2026 source found (snippet level) quoting BookSim's 5%/3% numbers — **caveat:** absence-of-evidence at snippet level; full-text citation mining across ~800 citations was not performed.

---

## 3. Q3 — NoC simulator landscape 2026 (tools & releases)

### 3.1 ASTRA-sim 3.0 — announced, not yet obtainable
Paper (arXiv:2606.10440, Jun 2026) + ISCA 2026 tutorial (AMD + Georgia Tech): adds cache-line/load-store granularity, a detailed GPU execution model, MSCCL++ collectives, InfraGraph, Chakra `.et` input, HTSim/ns-3 backends [S40][S41]. **Code not public:** README still says "currently at version 2.0"; issue #380 asking for the 3.0 timeline is open with zero comments (checked 2026-08-14) [S42]. No aggregate-% validation claim in the 3.0 abstract. The 2.x repo ships a calibrated example (`HGX-H100-validated.yml`) [S47 in T3 → S48]. Official 2.2 validation docs carry the standing numbers: NCCL All-Reduce geomean errors 11.4/7.9/2.8% (HPE Gen10) and 20.63/12.01/9.69% (HGX-H100) [S49][S50].

### 3.2 gem5 v25.x — no NoC changes
Releases v25.0.0.0, v25.0.0.1, v25.1.0.0, v25.1.0.1; no v25.2/v26.0 as of 2026-08-14. v25.x highlights are CPU/ISA (Neoverse V2, SVE2, …); no NoC/Garnet items in release notes. Garnet3/HeteroGarnet (clock-domain islands) and vnets are baseline features since the gem5 20.2 era [S51 in T3 → S52][S53 in T3 → S54].

### 3.3 New open-source tools (2025–2026) — scannable

| Tool | What it models | Validation as stated | License | Activity (2026-08-14) |
|---|---|---|---|---|
| ASTRA-sim 3.0 [S40] | scale-out ML, load-store GPU model, MSCCL++, InfraGraph | none in abstract; 2.x ships HGX-H100-validated.yml | MIT | code not released; issue #380 open |
| NoCDAS [S55] | NoC-based DNN accelerator (cycle-accurate) | functional only ("correctness of inference output is validated") | MIT | low (code 2025-03) |
| CHIPSIM [S52] | chiplet DNN co-sim (NoI) — uses **Garnet, not BookSim** | "up to 340% accuracy improvement" (abstract; metric undefined) | **none (no LICENSE)** | mirror sync 2026-02-16 |
| LEGOSim (MICRO 2025) [S58] | multi-chiplet parallel-sim integration | correctness-preserving sync (abstract) | **none (no LICENSE)** | commits to 2026-07-28 |
| SCALE-Sim v3 [S59] / main SCALE-Sim [S60] | systolic arrays (multi-core, sparse, Ramulator, Accelergy) | v3 abstract: none; TPU variant: vs TPU v4 (paper), v4+v6e R²≤0.99 (tutorial) [S29][S61] | MIT | v3 legacy; main active |
| BookSim 2 [S62] | reference NoC simulator | ISPASS 2013 (historical) | Stanford-style | **no commits since 2024-06-24; no 3.x** |
| DICE (ISCA 2026) [S63] | gem5 chiplet sim w/ PHY modeling | vs real AMD EPYC C2C latency (see Q4) | BSD-3-Clause | new, active |
| CAMINOS [S64] | phit-level NoC sim in Rust | JPDC 2025 (abstract-level) | MIT/Apache-2.0 | crates.io 0.6 |
| Noxim [S43] | SystemC NoC sim | 2026 deterministic regression suite (self-test) | GPL | active |
| tt-npe / ttsim / polaris [S65][S66] | Tenstorrent NoC estimator / full-system | none stated in README (tt-npe); ttsim v1.10.0 weekly cadence | Apache-2.0 | very active |
| PLENA_Simulator [S67] | long-context LLM accelerator | none stated in README | **none (no LICENSE)** | active |

### 3.4 Corrections to `docs/research/simulator-landscape-2026.md` (from direct re-checks, 2026-08-14)
- **CHIPSIM does NOT use BookSim** — README: `comm_simulator: "Garnet"`, "Booksim not implemented". Background doc said BookSim. [S52]
- **PAC-NoC venue is IEEE TVLSI preprint** (DOI 10.1109/TVLSI.2026.3717165), not CSDL/JSS; the abstract does **not** mention NoCDAS (the "built on NoCDAS" claim is unverified — T4 brief carried it from an earlier repo pass; T3 direct check contradicts/does not confirm) [S68].
- **gem5 v25.1 did not introduce Garnet3/vnets** — pre-existing (background doc misattributed) [S54].
- **ttsim is now v1.10.0 (2026-08-07)**, not v1.8.1 [S66].
- **scale-sim-v3 repo declares itself legacy**; main repo is `scalesim-project/SCALE-Sim` [S59][S60].
- ASTRA-sim 3.0 arXiv ID confirmed but **code availability caveat added** [S40][S42].

---

## 4. Q4 — AI-accelerator / LLM-serving interconnect simulation (2025–2026)

### 4.1 Which simulators sit behind the wafer-scale serving papers
- **ASTRA-sim lineage dominates:** WSC-LLM (ISCA 2025; "extended version of the ASTRA-sim simulator" — quote re-verified via the repo's 2026-08-12 pass; ACM DL bot-blocked this session) [S69]; TEMP (HPCA 2026; arXiv:2512.14256: "We build upon ASTRA-Sim … leveraging Ramulator") [S70]; MOCAP (Jun 2026; "custom event-driven simulator built upon ASTRA-sim 2.0", no hardware validation) [S71].
- **Custom/analytic:** BusyBarn (ISCA 2026; Python cost-model framework, simulated-annealing mapping + BALD routing; no named NoC simulator; no hardware validation disclosed) [S72][S73]; FACE (HPCA 2026; 3.68× avg vs SOTA; simulator unnamed, "will be open-sourced") [S74]; Ouroboros (Mar 2026; engine + validation unstated in abstract) [S75].
- **Pure NoC-level:** ETH wafer-on-wafer network-design paper (DAC 2026; arXiv:2603.05266) uses **BookSim2 flit-level + Orion3.0** and replays ATLAHS-collected Llama-7B training traces; no hardware validation [S76]. *Interpretation:* BookSim2 remains the de-facto NoC engine for 2026 wafer-scale network studies.
- **Hardware-grounded exceptions:** **C2C-Explorer** (arXiv:2608.08611, Aug 2026): "Validated against FPGA-based C2C prototypes, the C2C simulator achieves **2.46–8.23% end-to-end timing error** across diverse traffic patterns"; hybrid cycle/event model accelerates large-scale sim up to 7.8×; 32-XPU DeepSeek-R1-671B case (+44.1% goodput, −98.4% memory). The only 2026 LLM-interconnect work found with hardware-grounded timing validation [S38]. **DICE** (ISCA 2026; arXiv:2607.24221): gem5+Garnet runtime PHY modeling (QC-LDPC FEC, PAM4, AWGN, flit-level retransmission); validated against real AMD EPYC 9454P C2C latency: RMSE 89.5 cycles (29.4% of avg max latency) vs HeteroGarnet 141.2 cycles (46.4%); avg-latency RMSE 8.9% (ThreadRipper 3960X) / 11.8% (EPYC 7R13) / 29.8% (EPYC 9454P); FEC corrects 97.8% of errors at baseline SNR [S37].

### 4.2 Validation norms, quantified (the 2026 ladder)
| Posture | Examples | Reported numbers |
|---|---|---|
| Request/token-level % vs real serving engine | LLMServingSim 2.0 [S31][S32]; Frontier [S33]; KernelSight-LM [S36 in T4 → S77]; Charon [S34] | 0.95% avg; ≤~2.5% per-metric means; <4% throughput error; per-kernel 3.8–12.1%, E2E p50 2.7–15.4%; <5.35% overall |
| Collective-level % vs real GPU cluster | ASTRA-sim 2.2 official docs [S49][S50] | geomean 2.8–20.6% |
| C2C/NoC timing vs FPGA/hardware | C2C-Explorer [S38]; DICE [S37] | 2.46–8.23% E2E; RMSE 8.9–29.8% (baseline 19.1–46.4%) |
| Emulation fidelity | PrismLLM (May 2026) [S78] | 0.58% iteration-time; <0.01% memory |
| Correlation instead of % | SCALE-Sim TPU vs TPU v4 [S29] | "strong linear correlation"; <3% median (elementwise) |
| Cross-tier RTL↔sim consistency | OpenURMA (May 2026) [S79] | three matched tiers (RTL/SystemC/gem5); no % stated |
| Sim-vs-sim deltas | CHIPSIM [S52]; Frontier vs SOTA [S33] | "up to 340% accuracy improvement"; latency error 44.9%→6.4% / 51.7%→2.6% |
| No validation; bare sim results | BusyBarn [S72], FACE [S74], MOCAP [S71], TEMP [S70], PAC-NoC [S68], ETH wafer paper [S76], Ouroboros [S75] | — |

### 4.3 Chiplet / die-to-die (2025–2026)
- **DICE** (above) is the deepest hardware-validated chiplet-sim evidence found [S37].
- **OpenURMA** (May 2026): clean-room Unified Bus implementation at three matched tiers — synthesisable RTL (Alveo U50), cycle-level SystemC sim, gem5 scaffold; ~500 ns 64B remote fetch, 4.37× under OpenRoCE baseline; cross-tier consistency is the implied validation [S79].
- **CLIPGen** (May 2026): UCIe/2.5D link PPA generation (channel RC → SPICE → Liberate `.lib`); model-generation tool, no end-to-end validation claim in abstract [S80].
- **CHIPSIM** (Oct 2025): chiplet/NoI co-sim with µs-granularity power/thermal; "up to 340% accuracy improvement" (metric undefined in abstract) [S52].
- **LEGOSim** (MICRO 2025): parallel multi-chiplet integration framework; no validation numbers in abstract [S58].
- **Omelet** (ISCA 2026, Georgia Tech): packaging-aware hierarchical 2.5D/3D interconnect simulator — abstract/full text not publicly available (**blocked**) [S81].
- **Cohet** (HPCA 2026): CXL-driven coherent computing with "hardware-calibrated full-system simulation" [S82].
- **Gap (inference):** no 2025–2026 chiplet paper validates a NoC/C2C simulator against UCIe silicon at per-packet timing; DICE's RMSE-level hardware check is the deepest found.

### 4.4 KV-cache traffic characterization vs real inference workloads
- **KV Cache in the Wild** (arXiv:2506.02634, Jun 2025; v5 Feb 2026): first systematic characterization of production-provider KV-cache workloads; skewed reuses; single-turn reuses as important as multi-turn [S83].
- **cc-traces-weka-042026** (Hugging Face, Apr 2026; Apache-2.0): 739 agentic traces / 59,274 requests with per-request KV block hashes — replayable for offline prefix-cache simulation; 96.57% aggregate prefix-hit rate [S84].
- **GitHub Copilot traces** (Microsoft Research, Aug 2026; PDF, metadata only): 3.2M users, 13M sessions, 761M LLM calls, 95T tokens [S85].
- **Topology-Aware Data Movement** (arXiv:2607.28633, Jul 2026): 70B ≈ 1.3 GB KV/request; inter-GPU bandwidth varies 72× by physical relationship (900 GB/s NVLink 4.0 in-node) [S86].
- **Gap (negative result within searched sources):** no 2025–2026 paper found validating simulated KV-cache serving traffic at the NoC/flit level against real inference traces. C2C-Explorer's LLM-workload-driven generator (FPGA-validated) is the closest [S38]; the ETH paper replays real Llama-7B *training* traces into BookSim2 but validates nothing against hardware [S76].

---

## 5. Caveats, disagreements, and confidence notes

1. **Negative findings are bounded.** Every "no 2025–2026 work found" statement is a negative result within the searched sources (see search logs in the research briefs), not proof of non-existence. In particular: no SAT/SMT NoC-deadlock paper (T1), no per-flit sim↔RTL gate (T2), no KV-flit-level trace validation (T4), and no 2025–2026 source quoting BookSim's 5%/3% numbers (T2 — citation mining not performed at full-text scale).
2. **Cross-brief disagreement (PAC-NoC ↔ NoCDAS):** T4 (carrying an earlier repo pass) says PAC-NoC is built on NoCDAS; T3's direct check found the TVLSI abstract does not mention NoCDAS. **Marked unverified** — do not assert the link without the full text.
3. **Blocked sources (cited from metadata only):** DVCon 2025/2026 PDFs [S8][S9]; IEEE CAL 2025 stall-avoidance PDF [S5]; CAMINOS [S35]; FlexNoC [S38 in T2]; UniCNet paper (README/dblp only) [S23]; HeteroSim (ACM DL bot-blocked) [T4-S12]; Omelet (no preprint) [S81]; MSR Copilot traces (PDF) [S85]; PAC-NoC/CHIPSIM/LEGOSim/SCALE-Sim full texts.
4. **Uncertain numbers:** ATLAHS "<5% error" reference target unstated [S30]; UniCNet "verified against RTL" granularity unknown [S23]; SCALE-Sim TPU v6e + R²≤0.99 claims are tutorial-only, not in the arXiv abstract [S61]; scNoCSim "case studies with validation" nature unclear [S36]; CHIPSIM "340% accuracy improvement" metric undefined [S52].
5. **Tool-access blockers recorded:** the alphaXiv API (`alpha search`) failed with network errors in all 4 researchers (2026-08-14); arXiv coverage was substituted via web search + arXiv abs pages + APIs (Semantic Scholar, GitHub, arXiv Atom). NOCS 2025/2026 program pages were not reachable; NOCS-specific coverage is thinner than venue pages for ISCA/HPCA/ISPASS/MICRO.
6. **Secondary/weak sources:** LUBIS EDA blog (no author/date) used only as prose corroboration for "deadlock escapes simulation" [S87]; alphaXiv AI-generated overview used only for ASTRA-sim 3.0 secondary detail [S88]; NVIDIA/AMD vendor docs are self-reported [S39][S89].
7. **Out-of-window context (cited but not surveyed):** Dally & Seitz 1987 [S15], EbDa ISCA 2017 [S23], ReD TCAD 2024 [S21], DeFT 2021 [S22], ILP construction 2023 [S24], ONNXim CAL 2024 [S28], WSC-LLM ISCA 2025 methodology [S69].

---

## 6. Implications for the VeritX project (inference, labeled)

1. **Deadlock work (0344/F14):** The literature supports the team's direction: a single-VC bridge is a recognized deadlock configuration; published remedies are structural (embedded acyclic subnetwork — TERA [S7]) or isolation/injection control at the bridge (DFBM [S3]), not necessarily more VCs. The Dijkstra-vs-DOR divergence that produced the hang is a CDG-cycle class problem [S15]; protocol-level endpoint cycles are a documented second cause [S1]. No published tool auto-checks routing tables for CDG cycles in 2025–2026 [T1 §1.7] — the project's route-table forensics could be positioned as a novel contribution.
2. **Credibility gate & paper framing:** Every quantified validation norm found in 2025–2026 is coarser than the project's per-flit gate: benchmark-level (59.2%→1.4% [S17]), request-level (0.95% [S31][S32]), RMSE-level vs hardware (29.4% [S37]), FPGA-level aggregate (2.46–8.23% [S38]). A documented 83–98% per-flit agreement with characterized residuals exceeds all of them. The "exact% 83–98 vs 99.85" framing question should be resolved as *fidelity characterization*, matching how 2026 papers that do validate present their numbers (LLMServingSim: separate paper number vs docs-page numbers for different metrics — report both, don't conflate [S31][S32]).
3. **Toolchain:** BookSim upstream is dormant (no commits since 2024-06-24) [S62] — the project's fork with multicast/per-flit extensions is the effective continuation. ASTRA-sim 3.0 is not yet usable; track issue #380 [S42]. Do not vendor CHIPSIM/LEGOSim/PLENA without license clarification [S52][S58][S67]. Garnet3+vnets in gem5 v25.x are available as baseline features if VC-plane studies are needed [S54].

---

## 7. Open questions

1. Does the HPCA 2026 DFBM injection-control mechanism transfer to the project's 2-die bridge with a single VC? (Compare DFBM's coherence-flow inference [S3] with the project's anynet/route-table setup.)
2. Is a routing-table CDG cycle checker (RTL route tables → channel dependency graph → cycle detection) publishable as a tool/artifact? No 2025–2026 equivalent found [T1 §1.7].
3. Which 2026 validation posture should the paper adopt for the exact% question — per-metric docs-style reporting (like LLMServingSim [S32]) or aggregate (like the 0.95% abstract claim [S31])? (Owner: laura, per comm status.)
4. ASTRA-sim 3.0: when does code land, and does its load-store granularity change the T1/T3 toolchain plan?
5. Would validating simulated KV-serving traffic against cc-traces-weka-042026 (KV block hashes) [S84] fill a demonstrated 2026 gap (no flit-level KV trace validation found)?
6. Unresolved project-internal question (not a literature finding): has any VCS≥2 binary ever delivered cross-die traffic (dave's open question in comm status)? The literature says 1-VC deadlock freedom is achievable structurally [S7], which is consistent with the hang being routing-structure, not VC-count — but the project's own binary evidence is still pending.

---

## 8. Blocked / unverified (capability status)

- `alpha` CLI paper search (alphaXiv API): **blocked** — network error "fetch failed" in all 4 researcher runs (2026-08-14). Substituted with web search + arXiv abs pages + Semantic Scholar/GitHub/arXiv APIs.
- PDF full-text parsing: **not performed by design** (workflow rule). All PDF-only sources cited from metadata/abstracts/snippets.
- NOCS 2025/2026 program coverage: **blocked** (pages unreachable).
- Omelet (ISCA 2026) abstract/full text: **blocked** (no public preprint).
- PAC-NoC–NoCDAS relationship: **unverified** (conflicting source levels).
- HeteroSim validation numbers: **blocked** (ACM DL bot-wall).

---

## Sources

Primary survey sources (all URLs checked 2026-08-14 by the four research briefs; T2/T3/T4 brief numbering kept where noted):

1. Leone, Colagrande, Benini — Physically-Aware Preemptive Virtual Channels for Deadlock-Free AXI Networks-on-Chip — https://arxiv.org/abs/2607.01430
2. Zhang, Zhao, Wang, Ren — Q-StaR: A Quasi-Static Routing Scheme for NoCs — https://arxiv.org/abs/2603.10637
3. Chen, Fu, Wang, Zhou (NUDT) — Deadlock-Free Bridge Module for Inter-Chiplet Communication in Open Chiplet Ecosystem (HPCA 2026) — https://2026.hpca-conf.org/details/hpca-2026-main-conference/76/Deadlock-Free-Bridge-Module-for-Inter-Chiplet-Communication-in-Open-Chiplet-Ecosystem
4. Mendlovic — Existence of Deadlock-Free Routing for Arbitrary Networks — https://arxiv.org/abs/2503.04583
5. Srivastava, Rydell, Goens, Nagarajan, Sorin — Efficient Deadlock Avoidance by Considering Stalling, Message Dependencies, and Topology (IEEE CAL 24(2), 2025) — https://scholars.duke.edu/publication/1692103 (PDF: https://www.goens.org/publications/cal25.pdf)
6. Das, Das, Karfa — Developing Deadlock-Free Routing Algorithms in Torus NoC: A Formal Approach (ACM TECS 24(5s), 2025) — https://dl.acm.org/doi/10.1145/3762650
7. Cano et al. — TERA: Deadlock-free routing for Full-mesh networks without using Virtual Channels (HOTI 2025) — https://arxiv.org/abs/2510.14730 (DOI: https://doi.org/10.1109/hoti66940.2025.00020)
8. Ahmed, Yaqoob, Zafar, Din — Scaling Formal Verification of Network On Chip Using Path Decomposition (DVCon US 2026) — https://dvcon.org/program/2026/2026-technical-sessions (PDF: https://10xengineers.ai/wp-content/uploads/DVcon_submission_final-1.pdf)
9. Roy et al. — Hierarchical Formal Verification and Progress Checking of Network-On-Chip Design (DVCon US 2025) — https://dvcon-proceedings.org/document/hierarchical-formal-verification-and-progress-checking-of-network-on-chip-design/
10. Green et al. — Throughput-Optimized Networks at Scale / TONS — https://arxiv.org/abs/2605.27963
11. Liao et al. — UB-Mesh (datacenter AI network; table-lookup + deadlock-free flow control) — https://arxiv.org/abs/2503.20377
12. Ji & Yang — A Deadlock-Free Deterministic–Adaptive Hybrid Routing Algorithm (Electronics 14(5):845, 2025) — https://www.mdpi.com/2079-9292/14/5/845
13. Indrusiak group — A protocol to reduce worst-case latency in deflection-based on-chip networks — https://arxiv.org/abs/2510.11361
14. Sayuti & Indrusiak — Toward Predictable Deflection Routing in Routerless NoCs (IEEE MCSoC 2025) — https://eprints.whiterose.ac.uk/id/eprint/234673/
15. Dally & Seitz — Deadlock-Free Message Routing in Multiprocessor Interconnection Networks (IEEE TC C-36(5):547–553, 1987) — https://ieeexplore.ieee.org/document/1676939
16. Bentert et al. — Complexity of Perfect and Ideal Resilience Verification in Fast Re-Route Networks — https://arxiv.org/abs/2601.03934
17. Carlson et al. — Benchmarking for Single Feature Attribution with Microarchitecture Cliffs — https://arxiv.org/abs/2602.11580
18. Leveraging InfiniBand Controller to Configure Deadlock-Free Routing Engines for Dragonflies — https://arxiv.org/abs/2502.01214
19. Iff et al. — Network Design for Wafer-Scale Systems with Wafer-on-Wafer Hybrid Bonding — https://arxiv.org/abs/2603.05266
20. Krause et al. — Shiftfly: Scaling the Accelerator Interconnect Past the Pod — https://arxiv.org/abs/2608.00897
21. Taheri, Pasricha, Nikdast — ReD (IEEE TCAD 43(12), Dec 2024) — https://ieeexplore.ieee.org/document/10529122
22. DeFT — Deadlock-Free and Fault-Tolerant Routing for 2.5D Chiplet Networks — https://arxiv.org/abs/2112.09234
23. Ebrahimi & Daneshtalab — EbDa (ISCA 2017) — https://dl.acm.org/doi/10.1145/3079856.3080253
24. Systematic Construction of Deadlock-Free Routing for NoC Using Integer Linear Programming (IEEE 2023) — https://ieeexplore.ieee.org/document/10387838
25. Esmaili-Dokht et al. — Different Perspectives of Memory System Simulation — https://arxiv.org/html/2604.16965v1
26. Bostanci, Luo, Olgun, Mutlu et al. — Cleaning up the Mess: Re-Evaluating the Real-System Modeling Accuracy of Ramulator 2.0 — https://arxiv.org/abs/2510.15744
27. Huang et al. — NoCFuzzer: Automating NoC Verification in UVM (IEEE TCAD 2025) — https://jyhuang91.github.io/papers/tcad2025-nocfuzzer.pdf
28. Kim et al. — ONNXim: A Fast, Cycle-level Multi-core NPU Simulator (IEEE CAL 2024) — https://arxiv.org/html/2406.08051v1
29. Dang et al. — SCALE-Sim TPU: Validating and Extending SCALE-Sim for TPUs — https://arxiv.org/abs/2603.22535
30. Shen et al. — ATLAHS: An Application-centric Network Simulator Toolchain — https://arxiv.org/abs/2505.08936
31. Cho et al. — LLMServingSim 2.0 (ISPASS 2026 Best Paper) — https://arxiv.org/abs/2602.23036
32. LLMServingSim validation docs — https://llmservingsim.ai/docs/validation
33. Feng et al. — Frontier: Towards Comprehensive and Accurate LLM Inference Simulation — https://arxiv.org/abs/2605.21312
34. Yang et al. — Charon (MLSys 2026) — https://arxiv.org/abs/2605.17164
35. Camarero, Postigo, Fuentes — The CAMINOS interconnection networks simulator (JPDC 204, 2025) — https://www.sciencedirect.com/science/article/pii/S0743731525001030
36. Stea et al. — scNoCSim (Univ. Pisa, 2026) — https://arpi.unipi.it/handle/11568/1347650
37. Aligholipour, Kaxiras, Yao — DICE: Detailed Inter-Chiplet End-to-End PHY Modeling (ISCA 2026) — https://arxiv.org/abs/2607.24221
38. Li et al. — C2C-Explorer: An Exploration Framework for Chip-to-Chip Interconnect Architectures in LLM Cloud Computing Systems — https://arxiv.org/abs/2608.08611
39. AMD UG1388 (2026.1) — NoC Simulation — https://docs.amd.com/r/en-US/ug1388-acap-system-integration-validation-methodology/NoC-Simulation
40. Won et al. — ASTRA-sim 3.0: Next-Level Distributed Machine Learning Simulations — https://arxiv.org/abs/2606.10440
41. ASTRA-sim ISCA 2026 tutorial — https://astra-sim.github.io/tutorials/isca-2026
42. ASTRA-sim issue #380 — https://github.com/astra-sim/astra-sim/issues/380
43. Noxim repo (regression suite 2026-04-22) — https://github.com/davidepatti/noxim
44. MICRO 2026 AE / ISCA 2026 AE / ACM Artifact Review and Badging — https://www.microarch.org/micro59/submit/artifacts.php ; https://iscaconf.org/isca2026/submit/artifactevaluation.php ; https://www.acm.org/publications/policies/artifact-review-and-badging-current
45. rtl2booksim repo — https://github.com/mohsaied/rtl2booksim
46. Jiang et al. — A Detailed and Flexible Cycle-Accurate Network-on-Chip Simulator (BookSim, ISPASS 2013); citations via Semantic Scholar — https://ieeexplore.ieee.org/document/6557149/ ; https://api.semanticscholar.org/graph/v1/paper/DOI:10.1109/ISPASS.2013.6557149
47. Pfromm et al. — CHIPSIM — https://arxiv.org/abs/2510.25958
48. ASTRA-sim HGX-H100-validated.yml — https://github.com/astra-sim/astra-sim/blob/master/examples/network/analytical/HGX-H100-validated.yml
49. ASTRA-sim docs — NCCL over HGX-H100 validation — https://astra-sim.github.io/astra-sim-docs/validation/hardware/gpu-validation-hgx-h100.html
50. ASTRA-sim docs — NCCL over HPE Gen10 validation — https://astra-sim.github.io/astra-sim-docs/validation/hardware/gpu-validation.html
51. Pai et al. — Toward Reproducible and Standardized Computer Architecture Simulation with gem5 (ISPASS 2026) — https://arxiv.org/abs/2512.13479
52. CHIPSIM repo (Garnet, not BookSim; no LICENSE) — https://github.com/LukasPfromm/CHIPSIM
53. gem5 releases — https://github.com/gem5/gem5/releases
54. gem5 RELEASE-NOTES.md + HeteroGarnet docs — https://github.com/gem5/gem5/blob/stable/RELEASE-NOTES.md ; https://www.gem5.org/documentation/general_docs/ruby/heterogarnet/
55. NoCDAS repo — https://github.com/CRDloghorizon/NoCDAS ; paper https://dl.acm.org/doi/10.1145/3729169
56. Galimberti et al. — Rhea — https://arxiv.org/abs/2508.03837v2
57. Qiu et al. — An Integrated UVM-TLM Co-Simulation Framework for RISC-V — https://arxiv.org/abs/2505.10145
58. LEGOSim repo + MICRO 2025 paper — https://github.com/FCAS-LAB/LEGOSIM_MICRO ; https://dl.acm.org/doi/10.1145/3725843.3756068
59. scale-sim-v3 repo (legacy) — https://github.com/scalesim-project/scale-sim-v3
60. SCALE-Sim main repo — https://github.com/scalesim-project/SCALE-Sim
61. SCALE-Sim ISCA 2026 tutorial (TPU v4/v6e, R²≤0.99) — https://scalesim-project.github.io/tutorial-isca2026.html
62. booksim/booksim2 — https://github.com/booksim/booksim2
63. DICE-Simulator repo — https://github.com/RashidAGP/DICE-Simulator
64. CAMINOS project page — https://www.atc.unican.es/sw_caminos.html
65. tt-npe repo — https://github.com/tenstorrent/tt-npe
66. ttsim releases — https://github.com/tenstorrent/ttsim/releases
67. PLENA_Simulator repo — https://github.com/AICrossSim/PLENA_Simulator
68. PAC-NoC (IEEE TVLSI PrePrints, DOI 10.1109/TVLSI.2026.3717165) — https://www.computer.org/csdl/journal/si/5555/01/11641269/2iGhoU40Ir6
69. Xu et al. — WSC-LLM (ISCA 2025) — https://dl.acm.org/doi/10.1145/3695053.3731101
70. TEMP (HPCA 2026) — https://arxiv.org/html/2512.14256v1
71. Wang et al. — MOCAP — https://arxiv.org/abs/2606.22968
72. BusyBarn artifact (Zenodo) — https://zenodo.org/records/19686855 ; repo https://github.com/redbird-arch/isca2026-busybarn-artifact
73. BusyBarn ISCA 2026 — (venue program: https://iscaconf.org/isca2026/program/)
74. FACE (HPCA 2026) — https://2026.hpca-conf.org/details/hpca-2026-main-conference/14/FACE-Fully-PD-Overlapped-Scheduling-and-Multi-Level-Architecture-Co-Exploration-on-W
75. Liu et al. — Ouroboros — https://arxiv.org/abs/2603.02737
76. Iff et al. — ETH wafer-on-wafer network design (DAC 2026) — https://arxiv.org/abs/2603.05266
77. Yao et al. — KernelSight-LM: A Kernel-Level LLM Inference Simulator — https://arxiv.org/abs/2606.28565
78. Xi et al. — PrismLLM — https://arxiv.org/abs/2605.15617
79. Li et al. — OpenURMA — https://arxiv.org/abs/2605.28717
80. CLIPGen — https://arxiv.org/abs/2605.27757 ; https://github.com/realise-lab/CLIPGen
81. Kim et al. — Omelet (ISCA 2026) — https://iscaconf.org/isca2026/program/ ; https://jihoray.github.io/publications/
82. Cohet (HPCA 2026) — https://2026.hpca-conf.org/details/hpca-2026-main-conference/43/Cohet-A-CXL-Driven-Coherent-Heterogeneous-Computing-Framework-with-Hardware-Calibrat
83. Wang et al. — KV Cache in the Wild — https://arxiv.org/abs/2506.02634
84. cc-traces-weka-042026 (Hugging Face) — https://huggingface.co/datasets/semianalysisai/cc-traces-weka-042026
85. Agentic Coding in the Wild: GitHub Copilot at Production Scale (MSR, Aug 2026; PDF) — https://www.microsoft.com/en-us/research/wp-content/uploads/2026/08/ghcp_traces-6.pdf
86. Topology-Aware Data Movement for Disaggregated GPU Inference — https://arxiv.org/abs/2607.28633
87. LUBIS EDA — Deadlocks in SoC: Why Simulation Falls Short (blog, 2026) — https://lubis-eda.com/deadlocks-in-socs-why-livelock-and-starvation-escape/
88. alphaXiv overview of ASTRA-sim 3.0 — https://www.alphaxiv.org/overview/2606.10440
89. NVIDIA DSX Air blog — https://developer.nvidia.com/blog/design-simulate-and-scale-ai-factory-infrastructure-with-nvidia-dsx-air/

Research brief files (source of every claim above):
- `outputs/.drafts/noc-deadlock-sim-credibility-2026-research-t1.md` (deadlock)
- `outputs/.drafts/noc-deadlock-sim-credibility-2026-research-t2.md` (sim↔RTL credibility)
- `outputs/.drafts/noc-deadlock-sim-credibility-2026-research-t3.md` (landscape)
- `outputs/.drafts/noc-deadlock-sim-credibility-2026-research-t4.md` (AI/LLM interconnect)
