# T4 Research Brief — AI-Accelerator / LLM-Serving Interconnect Simulation (2025–2026)

**File:** `outputs/.drafts/noc-deadlock-sim-credibility-2026-research-t4.md`
**Date compiled:** 2026-08-14 (all URLs checked this date unless noted)
**Plan:** `outputs/.plans/noc-deadlock-sim-credibility-2026-T4.md`
**Rule compliance:** No PDF bodies fetched or parsed (no `alpha_get_paper`, no raw `.pdf` fetch). All claims below rest on arXiv metadata/abstracts, arXiv HTML renderings, official docs pages, ACM/IEEE/CSDL HTML metadata pages, GitHub/Zenodo/HF pages, and web snippets. Where only a PDF exists, the PDF URL is cited from search metadata and full-text parsing is marked **blocked**. `alpha search` was attempted but the alphaXiv API returned "fetch failed" (see Search log); searches were completed via `web_search`.
**Conventions:** ⚠️ = claim rests on a secondary page, snippet, or earlier repo research pass rather than a directly-read primary source in this session. "reported" = number as stated by the source; "interpretation" = my inference, labeled as such.

---

## Executive summary (per question)

1. **Q1 — Simulators behind 2025–2026 wafer-scale / mesh KV-cache LLM serving papers:** The ASTRA-sim lineage dominates (WSC-LLM ISCA 2025 extended ASTRA-sim [21]; TEMP HPCA 2026 = ASTRA-Sim + Ramulator [17]; MOCAP 2026 = custom event-driven sim built on ASTRA-sim 2.0 [18]). Custom analytic/cycle frameworks appear alongside: BusyBarn (ISCA 2026, simulated-annealing mapping + BALD routing, custom Python, no named NoC sim) [14][15]; FACE (HPCA 2026, simulator unnamed, "will be open-sourced") [16]; Ouroboros (2026, simulation-based, engine unnamed) [19]. Pure NoC-level: the ETH DAC 2026 wafer-on-wafer network-design paper uses **BookSim2 + Orion3.0** and replays ATLAHS-collected Llama-7B training traces through an extended BookSim2 [20]. C2C-Explorer (Aug 2026) is the only 2026 C2C/LLM interconnect work with **hardware (FPGA) validation**: 2.46–8.23% end-to-end timing error [1]. **None of the wafer-scale serving papers reports flit-level or cycle-level validation against hardware.** [13][14][16][17][18][19]

2. **Q2 — ASTRA-sim validation claims and new comparative studies:** ASTRA-sim 3.0 (arXiv 2606.10440, Jun 2026) makes **no aggregate-% validation claim in its abstract** (load-store granularity, GPU model, InfraGraph) [2]; the official ASTRA-sim 2.2 docs still carry the primary validation numbers — geomean errors of 11.4/7.9/2.8% (NCCL All-Reduce on HPE ProLiant Gen10) [4] and 20.63/12.01/9.69% (HGX-H100) [3]; and a GitHub issue (open at check time) notes no public 3.0 branch/tag/release in `astra-sim/astra-sim` [5]. New 2026 serving/training simulators each report their own hardware-calibrated numbers: LLMServingSim 2.0 avg error 0.95% (paper) [6] and means within ~2.5% of real vLLM on RTXPRO6000 (official docs) [7]; Frontier <4% throughput error on 16×H800 and latency error cut from 44.9%→6.4% (co-location) / 51.7%→2.6% (disaggregation) [8]; Charon (MLSys 2026) <5.35% overall / <3.74% on large GPU cluster [9]; PrismLLM 0.58% iteration-time error, <0.01% memory error [10]; KernelSight-LM 12.1% (cross-generation) / 3.8% (target-measured) per-kernel error, E2E p50 throughput error 3.0%/2.7% [11].

3. **Q3 — Accelerator-internal NoC simulation (NoCDAS, SCALE-Sim, PAC-NoC):** NoCDAS (ACM TOMACS 35(4), Oct 2025) is the new open cycle-accurate NoC-DNN simulator; its validation is **functional (inference-output correctness vs PyTorch)**, timing not RTL/hardware-validated [24]. SCALE-Sim v3 (ISPASS 2025) adds multi-core/sparse/Ramulator/Accelergy but has no hardware-% validation in its abstract; the **SCALE-Sim TPU** follow-up (arXiv 2603.22535, Mar 2026) validates against measured Google TPU v4 cycles (strong linear correlation; learned elementwise models <3% median error) [25][26]. PAC-NoC (TVLSI 2026 preprint; built on NoCDAS) reports only simulator results (≤52% latency/energy vs baselines), no validation [27]. A collective-capable NoC for large-scale ML accelerators appears at MLSys 2026 [44].

4. **Q4 — Chiplet / die-to-die simulation 2025–2026:** LEGOSim (MICRO 2025) is a parallel multi-chiplet integration framework (gem5/GPGPU-Sim-style sub-sims via IPC) — validation depth not stated in abstract [28]. OpenURMA (May 2026) ships **three matched tiers** (synthesisable RTL on Alveo U50, cycle-level SystemC sim, gem5 scaffold) — cross-tier RTL↔sim agreement is the implied validation; ~500 ns 64B remote fetch, 4.37× under OpenRoCE baseline [29]. CLIPGen (May 2026) generates PPA for UCIe/2.5D link IP from configs (SPICE/Liberate pipeline); no end-to-end validation claim in abstract [30]. CHIPSIM (arXiv 2510.25958) claims "up to 340% accuracy improvement" over conventional co-sims [31]. **DICE (ISCA 2026)** is the strongest 2026 chiplet-validation case: gem5+Garnet PHY-level inter-chiplet model validated against real AMD EPYC 9454P C2C latencies (RMSE 29.4% vs HeteroGarnet's 46.4%; 17.0% fidelity improvement) [32]. **Omelet** (ISCA 2026, Georgia Tech) is a new packaging-aware hierarchical 2.5D/3D interconnect simulator — full text not publicly available; abstract blocked [33]. Cohet (HPCA 2026) is a hardware-calibrated CXL full-system sim [34]. **Gap:** no 2025–2026 chiplet paper validates a NoC/C2C simulator against UCIe silicon with per-packet timing; DICE's RMSE-level hardware check is the deepest found.

5. **Q5 — What counts as sufficient validation in 2025–2026:** (i) **Request/token-level % error vs real serving engines** is the emerging gold standard (LLMServingSim ~0.95–2.5% [6][7]; Frontier <4% [8]; KernelSight-LM 2.7–15.4% [11]); (ii) **collective-level % error vs real GPU clusters** (ASTRA-sim 2.2 official numbers 2.8–20.6% [3][4]); (iii) **simulator↔simulator / RTL tier agreement** (OpenURMA tiers [29]; DICE vs HeteroGarnet + real chip [32]); (iv) **linear correlation instead of % error** (SCALE-Sim TPU vs TPUv4 [26]); (v) **no validation at all** — common even at top venues (BusyBarn [14], FACE [16], MOCAP [18], TEMP [17], PAC-NoC [27], ETH wafer paper [20]). Curve-shape/trend arguments and named-simulator lineage (ASTRA-sim) remain accepted (see repo's `simulator-credibility-noc-literature.md` for the reviewer-side precedent).

6. **Q6 — KV-cache traffic characterization vs real inference workloads:** Real-traffic characterization is now available and replayable: production provider KV$ patterns (KV Cache in the Wild, Jun 2025) [39]; per-request KV-block-hash agentic traces (cc-traces-weka-042026, Apache-2.0, 96.57% prefix-hit-rate figure) [40]; GitHub Copilot-scale coding traces (Jun 2026) [46]; measured inter-GPU bandwidth heterogeneity for KV transfers (72× spread; 1.3 GB/request for 70B) [37]. **Direct simulator-vs-real-inference-trace validation on the interconnect side is still rare**: C2C-Explorer's FPGA-validated LLM-workload-driven C2C traffic generator is the closest 2026 example [1]; ETH replays real Llama-7B training traces into BookSim2 but validates nothing against hardware [20]; KernelSight-LM validates serving metrics (not NoC traffic) against real GPUs [11].

---

## Findings by question

### Q1 — Wafer-scale / mesh KV-cache & LLM serving papers: simulators and validation evidence

**ASTRA-sim-lineage (serving/wafer papers):**
- **WSC-LLM** (ISCA 2025, ACM DOI 10.1145/3695053.3731101): wafer-scale LLM service + architecture co-exploration on a 2D-mesh/D2D model; per the repo's earlier verified pass (2026-08-12, `simulator-credibility-noc-literature.md` §4), the paper states "an evaluation methodology based on an extended version of the ASTRA-sim simulator"; ACM DL page bot-blocked this session, so the quote is re-cited from the earlier verified read. No hardware-validation % is reported. ⚠️ quote re-verified via prior pass; abstract page blocked. [21]
- **TEMP** (HPCA 2026 session; arXiv 2512.14256): "We build upon ASTRA-Sim ... an open-source simulator validated against real hardware, to integrate our proposed TATP and TCME ... leveraging Ramulator to simulate memory occupancy." (arXiv HTML) — i.e., wafer-scale tensor-partition paper leans on ASTRA-sim's validation reputation; reports no new hardware numbers. [17]
- **MOCAP** (arXiv 2606.22968, Jun 2026): "we develop a custom event-driven simulator built upon ASTRA-sim 2.0"; metrics E2E latency + throughput (req/s); results vs GPipe/Terapipe (76.4% lower latency, 3.24× throughput, 1.31× seq-len) with **no hardware validation**. [18]

**Custom/analytic frameworks:**
- **BusyBarn** (ISCA 2026, "Mapping and Communication Optimizations with Fault Tolerance for Wafer-Scale LLM Inference", HKUST-GZ): artifact (Zenodo 19686855 + github.com/redbird-arch/isca2026-busybarn-artifact) shows a Python framework: simulated-annealing hierarchical mapping + load-balanced distance-aware fault-tolerant (BALD) routing; evaluation = synthetic AllGather/AllToAll + end-to-end analytic timing (compute/overlap/comm cycles) for 6 LLM architectures (GPT-NeoX-20B … Qwen3-MoE-30B). **No hardware validation disclosed; no named NoC simulator** (custom cost model). [14][15]
- **FACE** (HPCA 2026 main conf.): wafer-scale multi-level architecture + fully overlapped PD scheduling + KV cache management; abstract: 3.68× avg improvement vs SOTA serving on wafer-scale chips; "will be open-sourced"; **simulator unnamed in abstract, no validation numbers**. [16]
- **Ouroboros** (arXiv 2603.02737, Mar 2026): wafer-scale SRAM-CIM LLM inference (token-grained pipelining, distributed dynamic KV management, communication-aware mapping); 4.1× throughput / 4.2× energy results; **evaluation engine and validation not stated in abstract**. [19]
- **STAGE** (arXiv 2511.10480, Nov 2025; ISCA 2026 "Scalable Synthesis of Distributed LLM Workloads Through Symbolic Tensor Graphs", Georgia Tech/NVIDIA): symbolic-tensor-graph generator of Chakra execution traces for ASTRA-sim-based DSE — the trace-synthesis side of the ASTRA-sim ecosystem; no hardware validation (it generates synthetic traces by design). [23]

**NoC-level wafer studies:**
- **ETH "Network Design for Wafer-Scale Systems with Wafer-on-Wafer Hybrid Bonding"** (arXiv 2603.05266, DAC 2026; Iff/Bonato/Besta/Benini/Hoefler): "We use the cycle-accurate BookSim2 ... NoC simulator to perform flit-level simulations ... Area and power estimates are obtained using Orion3.0"; also "extend BookSim2 to replay" ATLAHS-collected Llama-7B training traces (GOAL format); 48 architecture–placement combos, ~1.17M packets/sim; results up to 250% throughput / 36% latency / 38% energy-per-byte; LLM-trace latency down to 37–60% of baseline. **No hardware validation.** Interpretation: BookSim2 remains the de-facto NoC engine for 2026 wafer-scale network design. [20]

**C2C for LLM serving:**
- **C2C-Explorer** (arXiv 2608.08611, Aug 2026): "Validated against FPGA-based C2C prototypes, the C2C simulator achieves 2.46-8.23% end-to-end timing error across diverse traffic patterns. Its hybrid cycle and event model further accelerates large-scale simulation by up to 7.8× over a pure cycle-accurate baseline." 32-XPU DeepSeek-R1-671B case: +44.1% goodput, −98.4% memory. Open-source (github.com/Selinaee/C2C-Explorer). **The only 2026 LLM-interconnect work with hardware-grounded timing validation found.** [1]

**gem5-lineage (on-device/edge):**
- **SMOOTH** (ISCA 2026, DGIST): AE artifact states "Simulation Framework: An extended version of the open-source cycle-accurate simulator (LLMCompass)"; LLMCompass = Princeton ISCA 2024 framework (repo github.com/PrincetonUniversity/LLMCompass). No hardware validation claim in artifact pages. [35]

### Q2 — ASTRA-sim / ASTRA-sim 3.0 validation claims and comparative studies

- **ASTRA-sim 3.0** (arXiv 2606.10440, v1 Jun 2026; AMD+Georgia Tech): abstract describes cache-line/load-store-granularity simulation, a GPU execution model, and InfraGraph, but contains **no aggregate-% validation claim**. Body not parsed (HTML available; not needed for abstract-level claim). ⚠️ Any % claims in the paper body are unverified in this pass. [2]
- **Release status caveat:** GitHub issue #380 (open at check) asks when 3.0 will be public: "the README still appears to describe ASTRA-sim 2.x, and I could not find a 3.0 branch, tag, or release." No maintainer reply captured on the fetched page. [5]
- **Official ASTRA-sim 2.2 validation docs (primary, HTML):** NCCL All-Reduce, analytical backend:
  - HPE ProLiant Gen10 (V100-class, NVLink 25 GB/s): geomean error **11.4%** (2-GPU ring), **7.9%** (4-GPU), **2.8%** (8-GPU hybrid cube mesh) [4]
  - HGX-H100 (NVSwitch, 900 GB/s bidir): geomean error **20.63%** (2-GPU), **12.01%** (4-GPU), **9.69%** (8-GPU) [3]
  - Docs also disclose recommended practices (empirical warm-up/link latency extraction; max achieved BW 741.34 GB/s) — i.e., calibration-dependent accuracy. [3]
- **Comparative serving simulators, 2026 (all hardware-calibrated):**
  - **LLMServingSim 2.0** (arXiv 2602.23036, ISPASS 2026): "reproduces key performance, memory, and power metrics with an average error of 0.95%" (paper abstract) [6]; official docs: 300-request ShareGPT replay vs real vLLM v0.19.0 on RTXPRO6000 — TTFT/TPOT/latency means within ~2.5% across Llama-3.1-8B (TP1), Qwen3-32B (TP2), Qwen3-30B-A3B (DP2×EP2 MoE) [7]. Note the two numbers measure different things (aggregate vs per-metric); report both, don't conflate. Interpretation: docs page is the stronger, reproducible claim.
  - **Frontier** (arXiv 2605.21312, May 2026): "On 16-H800 GPU testbed, Frontier achieves an average throughput error below 4%. Compared with state-of-the-art simulators, it reduces end-to-end latency error from 44.9% to 6.4% under co-location and from 51.7% to 2.6% under disaggregation." Repo github.com/NetX-lab/Frontier. [8]
  - **Charon** (MLSys 2026 oral; arXiv 2605.17164): "overall prediction error consistently under 5.35%, and even under 3.74% for training with a large-scale GPU cluster." (Validation details/venue of the numbers in the PDF body — not parsed.) [9]
  - **PrismLLM** (arXiv 2605.15617, May 2026): emulation (not simulation) "achiev[ing] only 0.58% average error in iteration time and less than 0.01% error in peak GPU memory usage"; emulates up to 8192 GPUs with <1% of physical GPUs. [10]
  - **KernelSight-LM** (arXiv 2606.28565, Jun 2026): kernel-level serving simulator; cross-generation tier per-kernel error 12.1% (vs 22.0% roofline baseline); target-measured tier 3.8% (vs 27.7%); E2E p50 errors 15.4%/12.8%/3.0% and 14.3%/6.2%/2.7% (TTFT/TPOT/throughput). [11]
  - **HeteroSim** (WWW 2026, ACM DOI 10.1145/3774904.3792254): heterogeneous-LLM-training simulator; abstract (partial, from ACM page snippet): "Existing simulators ... either trade fidelity for speed or require heavyweight workflows..." — **validation numbers not obtainable this pass** (ACM DL bot-blocked; author PDF not parsed). ⚠️ blocked. [12]

### Q3 — NoCs inside AI accelerators (NoCDAS, SCALE-Sim, PAC-NoC, others)

- **NoCDAS** (ACM TOMACS 35(4), Oct 2025; Zhu/Chen/Lu, KTH): open cycle-accurate NoC-based DNN accelerator simulator (github.com/CRDloghorizon/NoCDAS; dblp ZhuCL25). Validation: per the repo's earlier verified pass (2026-08-12), "the correctness of inference output is validated" vs PyTorch, and RE-mode vs FE-mode self-consistency; **timing not validated against RTL/hardware**. ACM DL abstract page itself bot-blocked this session. ⚠️ validation quote from prior verified pass. [24]
- **SCALE-Sim v3** (arXiv 2504.15377, Apr 2025; ISPASS 2025, IEEE 11096402): multi-core spatio-temporal partitioning, SpMM, Ramulator integration, Accelergy; abstract reports case-study deltas (6.53×, 2.86×, 21%, 30.1%) but **no validation against hardware** in abstract. [25]
- **SCALE-Sim TPU** (arXiv 2603.22535, Mar 2026): "We validate SCALE-Sim's systolic GEMM model against measurements on Google TPU v4 and show that simulated cycle counts exhibit a strong linear correlation with hardware latency, enabling a simple cycle-to-latency mapping"; learned elementwise models "achieving median relative errors below 3 percent"; StableHLO frontend. **Correlation-based validation (no % error given for the GEMM path).** [26]
- **PAC-NoC** (IEEE TVLSI PrePrint, DOI 10.1109/TVLSI.2026.3717165; Ouyang/Chen/Wang/Li, HFUT): bandwidth-tapered fat-tree NoC with aggregated multicast (SSOA/DAC/HS) for transformer accelerators; "reduces latency by up to 52% and energy by up to 52% over traditional baselines ... latency by up to 49% and energy by up to 57%" vs bandwidth-equivalent optimized baselines. Simulation-only (built on NoCDAS per repo's earlier pass); **no validation numbers**. [27]
- **Collective-capable NoC for large-scale ML accelerators** (MLSys 2026, paper hash 48fecef47b19fe501d27d338b6d52582): lightweight NoC supporting efficient collectives for large ML accelerators — abstract snippet only; validation not stated in snippet. ⚠️ partial. [44]

### Q4 — Chiplet / die-to-die interconnect simulation 2025–2026

- **LEGOSim** (MICRO 2025, ACM DOI 10.1145/3725843.3756068; repo FCAS-LAB/LEGOSIM_MICRO): "a unified parallel simulation framework capable of flexibly integrating various [sub-simulators]" for multi-chiplet heterogeneous integration; challenges addressed = modular heterogeneous-chiplet integration, parallel-sim sync overhead, inter-chiplet communication overhead. Abstract contains **no validation numbers**; full text (ACM DL HTML available) not parsed this pass. ⚠️ validation depth unverified. [28]
- **OpenURMA** (arXiv 2605.28717, May 2026; Bojie Li et al.): clean-room Unified Bus (UALink-family) implementation "realised at three tiers — synthesisable RTL on Alveo U50, a cycle-level two-node SystemC simulator, and a gem5 full-system scaffold — each with a matched OpenRoCE (RoCEv2 RC) baseline"; 64B remote fetch ~500 ns E2E, 4.37× below baseline, 2.80× throughput, ~14% of U50 LUTs. Interpretation: the RTL+SystemC+gem5 three-tier structure *is* the validation apparatus (cross-tier consistency); abstract does not state a % agreement between tiers. [29]
- **CLIPGen** (arXiv 2605.27757, May 2026; repo realise-lab/CLIPGen): "End-to-end characterization framework for 2.5D chiplet die-to-die (D2D) links" — channel RC → termination/equalization → SPICE netlists → Cadence Liberate → `.lib` timing/power; per-bit energy/delay/area metrics. PPA-generation tool; **no end-to-end validation claim in abstract** (it generates models, doesn't validate sim timing). [30]
- **CHIPSIM** (arXiv 2510.25958, Oct 2025; IEEE OJ-SSCS 2025 DOI 10.1109/OJSSCS.2025.3626314 per earlier pass): co-simulation of DNN execution on chiplet systems incl. NoI contention/pipelining + microsecond-granularity power/thermal; "up to 340% accuracy improvement" vs conventional simulators. Interpretation: "340% accuracy improvement" is the authors' phrasing; I did not parse the body to see the underlying error metric. ⚠️ [31]
- **DICE** (ISCA 2026; arXiv 2607.24221): gem5+Garnet in-simulation runtime PHY modeling (QC-LDPC FEC, PAM4, AWGN channel, LLR demod, flit-level retransmission, PHY flow control); component latencies calibrated via Yosys/OpenSTA synthesis (TSMC 40nm) and public datasheets; validated against **real AMD EPYC 9454P** C2C latency: "HG gives an RMSE of 141.2 cycles (46.4% of the average maximum latency, 304.6 cycles ...), whereas DICE achieves 89.5 cycles (29.4%)" — "improving the fidelity of the modeled tail latency by 17.0% over HG"; avg-latency RMSEs: ThreadRipper 3960X 8.9% (HG 19.1%), EPYC 7R13 11.8% (HG 18.9%), EPYC 9454P 29.8% (HG 40.5%); FEC corrects 97.8% of errors at baseline SNR; IPC shifts avg 6.8%, up to 27.6% vs fixed-latency links. Repo: github.com/RashidAGP/DICE-Simulator. **Deepest hardware-validated chiplet-sim evidence found in 2026.** [32]
- **Omelet** (ISCA 2026, Georgia Tech): "A Packaging-Aware Hierarchical Interconnect Simulator for 2.5D/3D Chiplet Architectures" (Kim, Baig, Waqar, Victor, Yu, Bakir, Hao); earlier incarnations at TECHCON 2025 / MODSIM 2025 workshop ("Network-on-X"). **Full text/abstract not publicly available this pass — blocked.** [33]
- **Cohet** (HPCA 2026 main conf.; arXiv 2511.23011 per earlier pass): CXL-driven coherent heterogeneous computing with "hardware-calibrated full-system simulation" — calibration-based validation; abstract details not re-fetched this session. ⚠️ [34]
- Electrical/UCIe SI-level simulation (IMAPS/IEEE papers on UCIe channel compliance) exists but is signal-integrity analysis, not architecture simulation; excluded from detail. (URLs: imapsource.org articles 147216/147217.) [45]

### Q5 — What 2025–2026 papers treat as sufficient validation (quantified)

Ranked by depth found this pass (with reported numbers):

| Validation posture | Examples (2025–2026) | Reported numbers |
|---|---|---|
| Request/token-level % vs real serving engine | LLMServingSim 2.0 [6][7]; Frontier [8]; KernelSight-LM [11] | 0.95% avg; means ≤~2.5%; <4% throughput; p50 2.7–15.4% |
| Collective-level % vs real GPU cluster | ASTRA-sim 2.2 official docs [3][4] | geomean 2.8–20.6% |
| C2C/NoC timing vs FPGA/hardware prototype | C2C-Explorer [1]; DICE [32] | 2.46–8.23% E2E timing; RMSE 8.9–29.8% (vs 19.1–46.4% baseline) |
| Emulation fidelity vs real cluster | PrismLLM [10] | 0.58% iteration time; <0.01% memory |
| Linear correlation instead of % | SCALE-Sim TPU vs TPUv4 [26] | "strong linear correlation"; <3% median for elementwise |
| Cross-tier RTL↔sim consistency | OpenURMA [29] | three matched tiers; no % stated |
| Simulator-vs-simulator accuracy deltas | CHIPSIM [31]; Frontier vs SOTA [8] | "up to 340% accuracy improvement"; 44.9%→6.4% |
| No validation; bare sim results | BusyBarn [14], FACE [16], MOCAP [18], TEMP [17], PAC-NoC [27], ETH wafer paper [20], Ouroboros [19], NoCDAS (functional-only) [24] | — |

Qualitative takeaways (interpretation):
- The **serving-simulator tier in 2026 publishes %-against-real-vLLM numbers as a matter of course**; single-digit (0.5–8%) is now the expected bar for request-level metrics [6][7][8][11].
- The **NoC/chiplet tier mostly does not validate against hardware**; when it does, it's aggregate % (2.5–30% RMSE) or correlation, never per-flit/cycle exactness [1][20][24][32]. This supports the repo's thesis (see `simulator-credibility-noc-literature.md`) that a documented per-flit RTL↔sim gate would exceed the 2026 community norm.
- **Named-simulator lineage (ASTRA-sim/BookSim2/gem5) is itself treated as validation** by many wafer-scale papers [17][18][20][21][23].
- "340% accuracy improvement" [31] shows percentage-inflation rhetoric exists; quote verbatim, do not normalize.

### Q6 — KV-cache traffic characterization validated against real inference workloads

- **KV Cache in the Wild** (arXiv 2506.02634, Jun 2025, v5 Feb 2026): "the first systematic characterization of the KV$ workload patterns from one of the leading LLM service providers"; observations "not covered by previous studies focusing on synthetic workloads" — skewed reuses; single-turn reuses as important as multi-turn; per-category predictability; moderate ideal-cache size; workload-aware eviction improves serving under real traces. Real traces + simulated cache policies. [39]
- **cc-traces-weka-042026** (Hugging Face, semianalysisai, Apr 2026): 739 multi-turn agentic traces, 59,274 requests (claude-opus-4-5-20251101), per-request **KV block hash IDs** + api_time/think_time — "replayed against an inference engine or used to simulate prefix-cache behavior offline"; aggregate prefix-KV hit rate 96.57% of 129,409,824 blocks; Apache-2.0. Interpretation: a ready-made real-traffic source for validating simulated KV distribution/prefetch without re-tokenization. [40]
- **Agentic coding at production scale (GitHub Copilot traces)** (Microsoft Research, Aug 2026, PDF): 3.2M users, 13M sessions, 761M LLM calls, 95T tokens — real KV-relevant workload stats; PDF body not parsed (metadata only). [46]
- **Topology-Aware Data Movement for Disaggregated GPU Inference** (arXiv 2607.28633, Jul 2026): measured/argued interconnect reality for KV payloads: 70B ≈ 1.3 GB KV per request; "bandwidth between two GPUs varies by 72× depending on their physical relationship: 900 GB/s via NVLink 4.0 within a [node]..." — motivates network-aware (not just cache-aware) KV placement. Abstract-level only this pass. [37]
- **NetKV** (arXiv 2606.03910, Jun 2026): "Disaggregated LLM inference forces the KV cache to traverse the datacenter network before decoding begins, so transfer time enters directly into the Time to First Token (TTFT) budget"; proves cache-aware-only scheduling arbitrarily suboptimal as context grows; network-cost oracle + greedy decode-instance selection. Simulator/validation methodology not extracted this pass (HTML available, not skimmed). ⚠️ [36]
- **KVServe** (arXiv 2605.13734, SIGCOMM 2026 per earlier pass): service-aware KV compression for disaggregated serving; evaluation approach per earlier pass = "analytical latency model with a lightweight bandit" + deployment in vLLM. [38]
- **C2C-Explorer traffic generator** (Aug 2026): "LLM-workload-driven traffic generator" whose simulated C2C traffic is validated 2.46–8.23% vs FPGA prototypes — **the only 2026 example found of simulated-LLM-traffic-vs-hardware validation**. [1]
- **Real LLM traces into a NoC simulator:** ETH DAC 2026 paper replays ATLAHS-collected Llama-7B **training** traces in extended BookSim2 (no serving KV traffic; no hardware validation) [20]. **No 2025–2026 paper was found that validates simulated KV-cache serving traffic at the NoC/flit level against real inference traces** — gap statement (interpretation; negative result within searched sources). [20][39][40]

---

## Evidence table

| # | Source | URL | Key claim | Type | Confidence |
|---|--------|-----|-----------|------|------------|
| 1 | C2C-Explorer (Li et al., 2026) | https://arxiv.org/abs/2608.08611 | FPGA-validated C2C interconnect sim for LLM workloads: 2.46–8.23% E2E timing error; 7.8× hybrid-sim speedup; +44.1% goodput on 32-XPU DeepSeek-R1-671B | primary (abstract) | high |
| 2 | ASTRA-sim 3.0 (Won et al., Jun 2026) | https://arxiv.org/abs/2606.10440 | Load-store granularity, GPU exec model, InfraGraph; **no % validation claim in abstract** | primary (abstract) | high |
| 3 | ASTRA-sim 2.2 docs — NCCL over HGX-H100 | https://astra-sim.github.io/astra-sim-docs/validation/hardware/gpu-validation-hgx-h100.html | Geomean error 20.63% / 12.01% / 9.69% (2/4/8 GPUs); max achieved BW 741.34 GB/s | primary (official docs) | high |
| 4 | ASTRA-sim 2.2 docs — NCCL over HPE Gen10 | https://astra-sim.github.io/astra-sim-docs/validation/hardware/gpu-validation.html | Geomean error 11.4% / 7.9% / 2.8% (2/4/8 GPUs) | primary (official docs) | high |
| 5 | ASTRA-sim GitHub issue #380 | https://github.com/astra-sim/astra-sim/issues/380 | No public 3.0 branch/tag/release as of issue date; README still 2.x | primary (issue page) | high |
| 6 | LLMServingSim 2.0 (Cho et al., Feb 2026) | https://arxiv.org/abs/2602.23036 | Avg error 0.95% vs real deployments; ~10 min sims | primary (abstract) | high |
| 7 | LLMServingSim validation docs | https://llmservingsim.ai/docs/validation | 300-req ShareGPT replay vs vLLM v0.19.0 on RTXPRO6000: TTFT/TPOT/latency means within ~2.5% (3 configs incl. DP2×EP2 MoE) | primary (official docs) | high |
| 8 | Frontier (Feng et al., May 2026) | https://arxiv.org/abs/2605.21312 | <4% avg throughput error on 16×H800; latency error 44.9%→6.4% / 51.7%→2.6% | primary (abstract) | high |
| 9 | Charon (MLSys 2026; arXiv 2605.17164) | https://arxiv.org/abs/2605.17164 | Prediction error <5.35% overall, <3.74% large-cluster training | primary (abstract) | high |
| 10 | PrismLLM (Xi et al., May 2026) | https://arxiv.org/abs/2605.15617 | 0.58% avg iteration-time error; <0.01% peak-memory error; 8192-GPU emulation with <1% GPUs | primary (abstract) | high |
| 11 | KernelSight-LM (Yao et al., Jun 2026) | https://arxiv.org/abs/2606.28565 | Per-kernel 12.1%/3.8% error (cross-gen/target-measured); E2E p50 throughput 3.0%/2.7% | primary (abstract) | high |
| 12 | HeteroSim (WWW 2026) | https://dl.acm.org/doi/10.1145/3774904.3792254 | Heterogeneous LLM-training simulator; abstract partial; **numbers blocked** (bot-walled) | primary (metadata/partial) | low (blocked) |
| 13 | ISCA 2026 program | https://iscaconf.org/isca2026/program/ | Sessions incl. wafer-scale (BusyBarn, DICE, Omelet, ConBin, WaferBRAIN) and LLM sessions (SMOOTH, STAGE); 850 subs / 161 accepted per trip report | primary (program page) | high |
| 14 | BusyBarn artifact (Zenodo) | https://zenodo.org/records/19686855 | ISCA 2026 artifact: SA mapping + BALD routing; 12 figures; 6 LLM architectures; no hardware validation disclosed | primary (artifact page) | high |
| 15 | BusyBarn GitHub | https://github.com/redbird-arch/isca2026-busybarn-artifact | Custom Python cost-model framework (cfg→experiment→timing "SA time cost: (compute, overlap, comm) cycles"); no NoC simulator named | primary (repo README) | high |
| 16 | FACE (HPCA 2026) | https://2026.hpca-conf.org/details/hpca-2026-main-conference/14/FACE-Fully-PD-Overlapped-Scheduling-and-Multi-Level-Architecture-Co-Exploration-on-W | 3.68× avg improvement vs SOTA on wafer-scale; simulator unnamed; "will be open-sourced" | primary (abstract) | high |
| 17 | TEMP (HPCA 2026; arXiv 2512.14256) | https://arxiv.org/html/2512.14256v1 | "We build upon ASTRA-Sim ... validated against real hardware ... leveraging Ramulator"; no new validation | primary (arXiv HTML) | medium |
| 18 | MOCAP (Wang et al., Jun 2026) | https://arxiv.org/abs/2606.22968 | Custom event-driven simulator on ASTRA-sim 2.0; 76.4% lower latency vs GPipe; no validation | primary (abstract + HTML) | high |
| 19 | Ouroboros (Mar 2026) | https://arxiv.org/abs/2603.02737 | Wafer-scale SRAM-CIM; 4.1× throughput/4.2× energy; engine & validation unstated in abstract | primary (abstract) | medium |
| 20 | ETH wafer-on-wafer network design (DAC 2026; arXiv 2603.05266) | https://arxiv.org/abs/2603.05266 | BookSim2 flit-level + Orion3.0 + ATLAHS Llama-7B traces; up to 250% throughput/36% latency/38% energy; no HW validation | primary (abstract + HTML) | high |
| 21 | WSC-LLM (ISCA 2025) | https://dl.acm.org/doi/10.1145/3695053.3731101 | Wafer-scale LLM service/arch co-exploration on 2D-mesh D2D; extended-ASTRA-sim methodology (quote re-verified via repo pass 2026-08-12) | primary (DOI) + prior-pass quote | medium (page bot-blocked) |
| 22 | WaferLLM (OSDI 2025) | https://arxiv.org/abs/2502.04563 | Shift-based on-chip KV management over mesh NoC; 360× KV capacity (per repo pass 2026-08-12) | primary (abstract) | medium (methodology not re-checked) |
| 23 | STAGE (Nov 2025; ISCA 2026) | https://arxiv.org/abs/2511.10480 | Symbolic tensor graph → Chakra ET generator for ASTRA-sim DSE | primary (abstract) | high |
| 24 | NoCDAS (ACM TOMACS 35(4) 2025) | https://dl.acm.org/doi/10.1145/3729169 · https://github.com/CRDloghorizon/NoCDAS | Cycle-accurate NoC DNN sim; functional validation vs PyTorch; timing not HW/RTL-validated (per repo pass 2026-08-12) | primary (DOI) + prior pass | medium (page bot-blocked) |
| 25 | SCALE-Sim v3 (Apr 2025) | https://arxiv.org/abs/2504.15377 | Multi-core/sparse/Ramulator/Accelergy; no HW-% validation in abstract | primary (abstract) | high |
| 26 | SCALE-Sim TPU (Mar 2026) | https://arxiv.org/abs/2603.22535 | Validated vs Google TPU v4: strong linear correlation; elementwise models <3% median error | primary (abstract) | high |
| 27 | PAC-NoC (TVLSI 2026 preprint) | https://www.computer.org/csdl/journal/si/5555/01/11641269/2iGhoU40Ir6 | Aggregated-multicast fat-tree NoC; ≤52%/49% latency, ≤52%/57% energy vs baselines; no validation | primary (abstract) | high |
| 28 | LEGOSim (MICRO 2025) | https://dl.acm.org/doi/10.1145/3725843.3756068 | Parallel multi-chiplet integration framework; no validation numbers in abstract | primary (abstract) | medium |
| 29 | OpenURMA (May 2026) | https://arxiv.org/abs/2605.28717 | RTL (Alveo U50) + cycle-level SystemC + gem5 tiers, matched OpenRoCE baseline; ~500 ns 64B fetch, 4.37× | primary (abstract) | high |
| 30 | CLIPGen (May 2026) | https://arxiv.org/abs/2605.27757 · https://github.com/realise-lab/CLIPGen | UCIe/2.5D link PPA generation (channel RC→SPICE→Liberate); no E2E validation claim in abstract | primary (abstract) | high |
| 31 | CHIPSIM (Oct 2025) | https://arxiv.org/abs/2510.25958 | Chiplet/NoI co-sim; "up to 340% accuracy improvement"; power/thermal at µs granularity | primary (abstract) | medium (metric undefined in abstract) |
| 32 | DICE (ISCA 2026; arXiv 2607.24221) | https://arxiv.org/abs/2607.24221 · https://github.com/RashidAGP/DICE-Simulator | gem5+Garnet PHY model; vs real EPYC 9454P C2C: RMSE 29.4% vs HG 46.4%; 8.9–29.8% across 3 chips; FEC corrects 97.8% | primary (abstract + HTML) | high |
| 33 | Omelet (ISCA 2026) | https://iscaconf.org/isca2026/program/ · https://jihoray.github.io/publications/ | Packaging-aware hierarchical 2.5D/3D interconnect simulator; abstract/full text blocked | primary (program/author pages) | low (blocked) |
| 34 | Cohet (HPCA 2026) | https://2026.hpca-conf.org/details/hpca-2026-main-conference/43/Cohet-A-CXL-Driven-Coherent-Heterogeneous-Computing-Framework-with-Hardware-Calibrat | CXL-driven coherent computing with hardware-calibrated full-system simulation | primary (abstract) | medium |
| 35 | SMOOTH (ISCA 2026) + LLMCompass | https://zenodo.org/records/19448463 · https://github.com/PrincetonUniversity/LLMCompass | SMOOTH extends LLMCompass cycle-accurate sim; no HW validation in artifact pages | primary (artifact) | high |
| 36 | NetKV (Jun 2026) | https://arxiv.org/abs/2606.03910 | KV transfer time enters TTFT; cache-aware-only scheduling arbitrarily suboptimal; methodology not extracted | primary (abstract) | medium |
| 37 | Topology-Aware Data Movement (Jul 2026) | https://arxiv.org/abs/2607.28633 | 70B ≈1.3 GB KV/request; inter-GPU BW varies 72× (900 GB/s NVLink 4.0 …) | primary (abstract) | medium |
| 38 | KVServe (SIGCOMM 2026; arXiv 2605.13734) | https://arxiv.org/abs/2605.13734 | KV compression for disaggregated serving; analytical latency model + bandit (per repo pass) | primary (abstract) | medium |
| 39 | KV Cache in the Wild (Jun 2025) | https://arxiv.org/abs/2506.02634 | First production-provider KV$ characterization; skewed reuses; workload-aware eviction | primary (abstract) | high |
| 40 | cc-traces-weka-042026 (HF, Apr 2026) | https://huggingface.co/datasets/semianalysisai/cc-traces-weka-042026 | 739 traces / 59,274 requests with per-request KV block hashes; 96.57% prefix-hit rate; Apache-2.0 | primary (dataset card) | high |
| 41 | GORGO (Feb 2026) | https://arxiv.org/abs/2602.11688 | Cross-region network-aware LLM serving proxy (KV locality + replica load + network latency) | primary (abstract) | medium |
| 42 | ASPLOS 2026 program | https://www.asplos-conference.org/asplos2026/program/index.html | Dedicated "LLM Attention & KV Cache" session exists | primary (program) | high |
| 43 | CacheWise (Jun 2026) | https://arxiv.org/abs/2606.16824 | Real coding-agent traces; sustained KVCache pressure | primary (abstract) | medium |
| 44 | Collective-capable NoC (MLSys 2026) | https://proceedings.mlsys.org/paper_files/paper/2026/hash/48fecef47b19fe501d27d338b6d52582-Abstract-Conference.html | Lightweight collective NoC for large ML accelerators | primary (abstract, partial) | low (partial) |
| 45 | UCIe SI-level simulation (IMAPS) | https://imapsource.org/article/147216-using-ucie-channel-compliance-simulation-for-understanding-substrate-interposer-design-tradeoffs.pdf | UCIe channel compliance simulation (electrical SI, not architecture sim) | primary (metadata) | low (PDF blocked) |
| 46 | Agentic Coding in the Wild (MSR, Aug 2026) | https://www.microsoft.com/en-us/research/wp-content/uploads/2026/08/ghcp_traces-6.pdf | GitHub Copilot: 3.2M users, 13M sessions, 761M calls, 95T tokens | primary (metadata; PDF blocked) | medium |

---

## Sources

1. Jiayi Li et al., "C2C-Explorer: An Exploration Framework for Chip-to-Chip Interconnect Architectures in LLM Cloud Computing Systems" (arXiv:2608.08611, Aug 2026) — https://arxiv.org/abs/2608.08611
2. William Won et al., "ASTRA-sim 3.0: Next-Level Distributed Machine Learning Simulations via High-Fidelity GPU and Infrastructure Modeling" (arXiv:2606.10440, Jun 2026) — https://arxiv.org/abs/2606.10440
3. ASTRA-sim 2.2 documentation, "Validation on GPU Systems — NCCL over HGX-H100" — https://astra-sim.github.io/astra-sim-docs/validation/hardware/gpu-validation-hgx-h100.html
4. ASTRA-sim 2.2 documentation, "Validation on GPU Systems — NCCL over HPE ProLiant Gen10" — https://astra-sim.github.io/astra-sim-docs/validation/hardware/gpu-validation.html
5. ASTRA-sim GitHub issue #380, "Question about the release timeline for ASTRA-sim 3.0" — https://github.com/astra-sim/astra-sim/issues/380
6. Jaehong Cho et al., "LLMServingSim 2.0: A Unified Simulator for Heterogeneous and Disaggregated LLM Serving Infrastructure" (arXiv:2602.23036, Feb 2026) — https://arxiv.org/abs/2602.23036
7. LLMServingSim official documentation, "Validation" — https://llmservingsim.ai/docs/validation
8. Yicheng Feng et al., "Frontier: Towards Comprehensive and Accurate LLM Inference Simulation" (arXiv:2605.21312, May 2026) — https://arxiv.org/abs/2605.21312
9. Mengtian Yang et al., "Charon: A Unified and Fine-Grained Simulator for Large-Scale LLM Training and Inference" (MLSys 2026; arXiv:2605.17164) — https://arxiv.org/abs/2605.17164
10. Shaoke Xi et al., "A Few GPUs, A Whole Lotta Scale: Faithful LLM Training Emulation with PrismLLM" (arXiv:2605.15617, May 2026) — https://arxiv.org/abs/2605.15617
11. Xiteng Yao et al., "KernelSight-LM: A Kernel-Level LLM Inference Simulator" (arXiv:2606.28565, Jun 2026) — https://arxiv.org/abs/2606.28565
12. Xiaofei Yue et al., "HeteroSim: Towards High-Fidelity Heterogeneous LLM Training Simulation on GPUs" (WWW 2026, pp. 5189–5197) — https://dl.acm.org/doi/10.1145/3774904.3792254
13. ISCA 2026 Conference Program — https://iscaconf.org/isca2026/program/
14. Cui, Qin, Cai, Huang, "Mapping and Communication Optimizations with Fault Tolerance for Wafer-Scale LLM Inference" — artifact (Zenodo 19686855, Apr 2026) — https://zenodo.org/records/19686855
15. redbird-arch/isca2026-busybarn-artifact (ISCA 2026 BusyBarn artifact repo) — https://github.com/redbird-arch/isca2026-busybarn-artifact
16. "FACE: Fully PD Overlapped Scheduling and Multi-Level Architecture Co-Exploration on Wafer" (HPCA 2026) — https://2026.hpca-conf.org/details/hpca-2026-main-conference/14/FACE-Fully-PD-Overlapped-Scheduling-and-Multi-Level-Architecture-Co-Exploration-on-W
17. "TEMP: A Memory Efficient Physical-aware Tensor Partition-Mapping Framework on Wafer-scale Chips" (arXiv:2512.14256, Dec 2025; HPCA 2026 session) — https://arxiv.org/html/2512.14256v1
18. Zichuan Wang et al., "MOCAP: Wafer-Scale-Chip-Oriented Memory-Orchestrated Chunked Pipelining Framework for Prefill-Only LLM Inference" (arXiv:2606.22968, Jun 2026) — https://arxiv.org/abs/2606.22968
19. Yiqi Liu et al., "Ouroboros: Wafer-Scale SRAM CIM with Token-Grained Pipelining for Large Language Model Inference" (arXiv:2603.02737, Mar 2026) — https://arxiv.org/abs/2603.02737
20. Patrick Iff, Tommaso Bonato, Maciej Besta, Luca Benini, Torsten Hoefler, "Network Design for Wafer-Scale Systems with Wafer-on-Wafer Hybrid Bonding" (DAC 2026; arXiv:2603.05266) — https://arxiv.org/abs/2603.05266
21. Zheng Xu et al., "WSC-LLM: Efficient LLM Service and Architecture Co-exploration for Wafer-scale Chips" (ISCA 2025) — https://dl.acm.org/doi/10.1145/3695053.3731101
22. Yubei He et al., "WaferLLM: Large Language Model Inference at Wafer Scale" (OSDI 2025; arXiv:2502.04563) — https://arxiv.org/abs/2502.04563
23. Changhai Man, Joongun Park, Hanjiang Wu, Huan Xu, Srinivas Sridharan, Tushar Krishna, "Scalable Synthesis of Distributed LLM Workloads through Symbolic Tensor Graphs / STAGE" (arXiv:2511.10480, Nov 2025; ISCA 2026) — https://arxiv.org/abs/2511.10480
24. Wenyao Zhu, Yizhi Chen, Zhonghai Lu, "NoCDAS: A Cycle-Accurate NoC-Based Deep Neural Network Accelerator Simulator" (ACM TOMACS 35(4), 2025) — https://dl.acm.org/doi/10.1145/3729169 · https://github.com/CRDloghorizon/NoCDAS
25. Ritik Raj et al., "SCALE-Sim v3: A modular cycle-accurate systolic accelerator simulator for end-to-end system analysis" (ISPASS 2025; arXiv:2504.15377) — https://arxiv.org/abs/2504.15377
26. Jingtian Dang et al., "SCALE-Sim TPU: Validating and Extending SCALE-Sim for TPUs" (arXiv:2603.22535, Mar 2026) — https://arxiv.org/abs/2603.22535
27. Yiming Ouyang et al., "PAC-NoC: A Hierarchical Network-on-Chip for Efficient Parallel Aggregated Communication in Transformer Accelerators" (IEEE TVLSI PrePrints, DOI 10.1109/TVLSI.2026.3717165) — https://www.computer.org/csdl/journal/si/5555/01/11641269/2iGhoU40Ir6
28. Tiantian Lin et al., "LEGOSim: A Unified Parallel Simulation Framework for Multi-chiplet Heterogeneous Integration" (MICRO 2025) — https://dl.acm.org/doi/10.1145/3725843.3756068 · https://github.com/FCAS-LAB/LEGOSIM_MICRO
29. Bojie Li et al., "OpenURMA: A Clean-Room Open Implementation of the Unified Bus Protocol" (arXiv:2605.28717, May 2026) — https://arxiv.org/abs/2605.28717
30. "CLIPGen: A Chiplet Link IP Modeling and Generation Framework for 2.5D Architecture Exploration" (arXiv:2605.27757, May 2026) — https://arxiv.org/abs/2605.27757 · https://github.com/realise-lab/CLIPGen
31. Lukas Pfromm et al., "CHIPSIM: A Co-Simulation Framework for Deep Learning on Chiplet-Based Systems" (arXiv:2510.25958, Oct 2025; IEEE OJ-SSCS 2025 DOI 10.1109/OJSSCS.2025.3626314) — https://arxiv.org/abs/2510.25958
32. Rashid Aligholipour, Stefanos Kaxiras, Yuan Yao, "DICE: Detailed Inter-Chiplet End-to-End PHY Modeling for Accurate Chiplet Simulation" (ISCA 2026; arXiv:2607.24221) — https://arxiv.org/abs/2607.24221 · https://github.com/RashidAGP/DICE-Simulator
33. Jiho Kim et al., "Omelet: A Packaging-Aware Hierarchical Interconnect Simulator for 2.5D/3D Chiplet Architectures" (ISCA 2026) — https://iscaconf.org/isca2026/program/ · https://jihoray.github.io/publications/
34. "Cohet: A CXL-Driven Coherent Heterogeneous Computing Framework with Hardware-Calibrated Full-System Simulation" (HPCA 2026; arXiv:2511.23011) — https://2026.hpca-conf.org/details/hpca-2026-main-conference/43/Cohet-A-CXL-Driven-Coherent-Heterogeneous-Computing-Framework-with-Hardware-Calibrat
35. skkim-caslab/SMOOTH ISCA 2026 AE release (Zenodo 19448463) + PrincetonUniversity/LLMCompass — https://zenodo.org/records/19448463 · https://github.com/PrincetonUniversity/LLMCompass
36. "NetKV: Network-Aware Decode Instance Selection for Disaggregated LLM Inference" (arXiv:2606.03910, Jun 2026) — https://arxiv.org/abs/2606.03910
37. "Topology-Aware Data Movement for Disaggregated GPU Inference" (arXiv:2607.28633, Jul 2026) — https://arxiv.org/abs/2607.28633
38. "KVServe: Service-Aware KV Cache Compression for Communication-Efficient Disaggregated LLM Serving" (SIGCOMM 2026; arXiv:2605.13734) — https://arxiv.org/abs/2605.13734
39. Jiahao Wang et al., "KV Cache in the Wild: Characterizing and Optimizing KVCache Cache at a Large Cloud Provider" (arXiv:2506.02634, Jun 2025) — https://arxiv.org/abs/2506.02634
40. semianalysisai/cc-traces-weka-042026 (Hugging Face dataset, Apr 2026) — https://huggingface.co/datasets/semianalysisai/cc-traces-weka-042026
41. "GORGO: Online Tuning for Cross-Region Network-Aware LLM Serving" (arXiv:2602.11688, Feb 2026) — https://arxiv.org/abs/2602.11688
42. ASPLOS 2026 Program — https://www.asplos-conference.org/asplos2026/program/index.html
43. "CacheWise: Understanding Workloads and Optimizing KVCache Management for Efficiently Serving LLM Coding Agents" (arXiv:2606.16824, Jun 2026) — https://arxiv.org/abs/2606.16824
44. "A Lightweight High-Throughput Collective-Capable NoC for Large-Scale ML Accelerators" (MLSys 2026) — https://proceedings.mlsys.org/paper_files/paper/2026/hash/48fecef47b19fe501d27d338b6d52582-Abstract-Conference.html
45. "Using UCIe Channel Compliance Simulation for Understanding Substrate/Interposer Design Tradeoffs" (IMAPS) — https://imapsource.org/article/147216-using-ucie-channel-compliance-simulation-for-understanding-substrate-interposer-design-tradeoffs.pdf
46. "Agentic Coding in the Wild: Characterizing GitHub Copilot at Production Scale" (Microsoft Research, Aug 2026) — https://www.microsoft.com/en-us/research/wp-content/uploads/2026/08/ghcp_traces-6.pdf

**Repo background docs read (extend, do not redo):** `docs/research/2026-moe-serving-landscape.md`, `docs/research/cross-node-kv-distribution-2026.md`, `docs/research/llm-serving-trace-pipeline.md`, `docs/research/simulator-landscape-2026.md`, `docs/research/simulator-credibility-noc-literature.md`.

---

## Search log (exact queries, in order)

`web_search` (provider auto; workflow=none; includeContent as noted):

1. `wafer scale LLM serving mesh NoC KV cache ISCA 2026 simulation validation` (content on)
2. `KV cache serving on mesh network-on-chip 2026 simulator validation ASTRA-sim` (content on)
3. `wafer-scale LLM inference interconnect paper 2026 cycle-accurate simulator` (content on)
4. `LLM serving systems ISCA 2026 HPCA 2026 network simulator validation` (content on)
5. `ASTRA-sim 3.0 validation claims 2026 error hardware` (content on)
6. `ASTRA-sim validation percentage error GPU cluster training 2025 2026` (content on)
7. `distributed training simulation accuracy real cluster comparison 2026 paper` (content on)
8. `NoCDAS cycle-accurate NoC DNN accelerator simulator validation ACM TOMACS 2025` (content on)
9. `SCALE-Sim v3 validation TPUv4 ISPASS 2025 spatio-temporal sparse` (content on)
10. `PAC-NoC bandwidth tapered fat tree NoC multicast attention validation` (content on)
11. `LEGOSim MICRO 2025 chiplet heterogeneous simulation validation` (content on)
12. `OpenURMA Unified Bus UALink clean-room implementation cycle-accurate` (content on)
13. `CLIPGen chiplet UCIe link IP modeling power performance area` (content on)
14. `chiplet die-to-die interconnect simulation validation 2026 UCIe` (content on)
15. `KV cache traffic characterization LLM inference network measurement simulation validation 2026` (content on)
16. `LLMCompass cycle-accurate simulator LLM inference on-chip memory`
17. `network design wafer scale systems wafer-on-wafer hybrid bonding arXiv ETH`
18. `ASPLOS 2026 KV cache serving disaggregated prefill decode paper`
19. `ELK MICRO 2025 compiler NoC co-design LLM validation`
20. `SMOOTH ISCA 2026 LLMCompass simulation framework validation hardware`
21. `WSC-LLM wafer scale LLM serving architecture ISCA 2025 arXiv abstract` (content on)
22. `Charon fine-grained simulator LLM training inference MLSys 2026 validation error` (content on)
23. `PrismLLM faithful LLM training emulation validation accuracy 2026` (content on)
24. `HeteroSim heterogeneous LLM training simulation GPUs validation WWW 2026` (content on)
25. `ISCA 2026 accepted papers KV cache serving network-on-chip wafer` (content on)
26. `KV cache traffic real inference measurement trace network characterization 2026` (content on)
27. `Omelet packaging-aware hierarchical interconnect simulator 2.5D 3D chiplet ISCA 2026` (content on)
28. `Scalable Synthesis of Distributed LLM Workloads Symbolic Tensor Graphs Georgia Tech` (content on)
29. `WSC-LLM arXiv wafer scale chips ASTRA-sim extended simulator` (content on)
30. `PAC-NoC NoCDAS multicast bandwidth tapered network 2026` (content on)
31. `HeteroSim LLM training simulation validation error percentage 2026`
32. `Echo simulating distributed training at scale NSDI 2025 validation error`
33. `ASPLOS 2026 KV cache serving disaggregated inference paper network`

`fetch_content` (HTML pages only; no .pdf): arXiv abs pages (2608.08611, 2606.10440, 2602.23036, 2605.21312, 2606.22968, 2603.02737, 2603.22535, 2607.24221, 2606.28565, 2605.28717, 2510.25958, 2504.15377, 2603.05266, 2605.17164, 2605.15617, 2506.02634); arXiv HTML full-text renderings (2607.24221v2, 2603.05266v2 — used only for methodology/validation sentences); official docs (llmservingsim.ai/docs/validation; astra-sim.github.io GPU-validation pages ×2); GitHub (astra-sim issue #380; redbird-arch/isca2026-busybarn-artifact; jihoray.github.io/publications); Zenodo record 19686855; HF dataset card; iscaconf.org/isca2026/program/; hpca-conf.org FACE/Cohet pages; dl.acm.org (WSC-LLM, HeteroSim — bot-blocked, noted); computer.org CSDL PAC-NoC page.

`alpha` CLI: `alpha status` → logged in; `alpha search "wafer scale KV cache serving simulator validation"` and `alpha search "KV cache serving wafer scale simulation validation" --json` → both returned `Error: fetch failed` (alphaXiv API unreachable 2026-08-14). **`alpha get`/`alpha ask` (paper-body parsing) were not used**, per plan rule.

---

## Coverage status

**Done (directly checked this session):** Q1 simulators/validation for WSC-LLM*, TEMP, MOCAP, BusyBarn, FACE, Ouroboros, STAGE, ETH wafer paper, C2C-Explorer, SMOOTH/LLMCompass, DICE, Omelet*; Q2 ASTRA-sim 3.0 abstract + release status + official 2.2 validation docs, LLMServingSim 2.0 (paper + docs), Frontier, Charon, PrismLLM, KernelSight-LM, HeteroSim (partial); Q3 NoCDAS*, SCALE-Sim v3/TPU, PAC-NoC, MLSys collective NoC; Q4 LEGOSim (abstract), OpenURMA, CLIPGen, CHIPSIM, DICE, Omelet, Cohet; Q5 validation-norm quantification; Q6 KV Cache in the Wild, cc-traces dataset, Copilot traces (metadata), Topology-Aware, NetKV (abstract), GORGO (abstract), CacheWise (abstract). (* = ACM DL bot-blocked; claims carried from previously-verified repo passes, marked ⚠️.)

**Blocked / not done:**
- PDF bodies never parsed (per plan): Charon/PrismLLM/HeteroSim validation internals beyond abstracts, WSC-LLM full text, LLMCompass paper, WaferLLM methodology, Copilot-traces paper, UCIe SI papers, MONET (DOI-only, from background).
- **Omelet abstract/full text**: no public preprint found; blocked.
- **ASTRA-sim 3.0 validation %**: not in abstract; body not parsed — needs follow-up if the paper's numbers matter to T1.
- **HeteroSim validation numbers**: ACM DL bot-blocked; author PDF not parsed — needs follow-up (⚠️).
- **alphaXiv API**: search failed (`fetch failed`) — all searches via web_search; noted above.
- **KV-traffic-validated NoC simulation**: negative result (no paper found validating simulated KV serving traffic at flit level against real inference traces); stated as a gap, not a fact about any source.
- Q1 venue coverage: ASPLOS 2025–2026 checked only via program page (KV session exists) and one search; a dedicated ASPLOS 2026 paper-level sweep was not completed.

**Uncertainty markers recap:** ⚠️ items = WSC-LLM quote (via prior pass), NoCDAS validation (via prior pass), CHIPSIM "340%" metric semantics, HeteroSim numbers (blocked), Omelet (blocked), ASTRA-sim 3.0 numbers (blocked), NetKV methodology (not extracted), Cohet details (not re-fetched), KVServe evaluation detail (via prior pass), WaferLLM methodology (not re-checked), LLMCompass (out-of-window base, via artifacts).
