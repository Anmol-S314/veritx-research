# How Simulator Credibility Is Established in Computer Architecture / NoC Research

Research report for the "Gate R1" decision (Verilator RTL 8x8 mesh NoC vs BookSim per-flit timing gate).
Compiled 2026-08-12 from primary sources (papers, official docs, repos). Every claim carries a quote and source URL so it can be re-verified.

---

## 0. Executive Summary

1. **Cycle-exact 0-mismatch RTL↔simulator agreement is the exception, not the norm.** The canonical counter-example is BookSim 2.0 itself (the exact simulator in question): its ISPASS 2013 paper validates against an RTL router and reports "a maximum difference of 5% in network latency measurements" and "a maximum difference of 3% in the accepted throughput" — on aggregate latency/throughput curves over a **3×3 mesh, single VC, 100K cycles**, not per-flit cycle counts.
2. **The community standard for NoC timing claims is aggregate-curve agreement within a few percent, or documented residuals.** GARNET (ISPASS 2009) validates against *other simulators' published numbers* (PoPNet/ViChaR) and openly states "GARNET saturates slightly earlier than ViChaR's baseline network." Acknowledged residuals are normal.
3. **Even RTL is provisionally "within 5% of hardware" in industry practice** (AMD UG1388 NoC docs).
4. **No published work gates a flit-by-flit, per-cycle match between a software NoC simulator and an RTL model.** The closest precedents (BookSim RTL validation; BST ISPASS 2020; rtl2booksim tooling; SynFull-RTL) compare distributions/curves, not bit-exact per-flit streams.
5. **In the KV-cache / LLM-serving domain specifically, request- or token-level discrete-event simulation validated to ~5–15% against real hardware is the state of the art** (ASTRA-sim2.0: 5%; VIDUR: ~9%; LLMServingSim: <14.7%; WSC-LLM at ISCA 2025 relies on ASTRA-sim). Many credible papers report bare simulator results with no timing validation at all.
6. **Reviewers do not demand exactness; they demand credibility**: a simulator with a published validation story, artifact availability, trend-robustness, and ablations. The ISCA 2025 reviews of WSC-LLM (wafer-scale KV-cache serving on a 2D mesh) show reviewers probing *whether network contention is modeled at all*, not exact cycle parity.
7. **"99.85% of flits bit-exact, with characterized residual families (bounded drift 0–9 cycles; const-early 23–32 cycles; VC-count-dependent rate)" is publishable methodology — if presented as characterized fidelity, not as a discrepancy to hide.** It is *stronger* evidence than what BookSim itself, GARNET, gem5, or ASTRA-sim ships.
8. **Pursuing 0/0 is likely not worth it**: no community precedent requires it, and the residual structure (deterministic, bounded, mechanistically explainable) is the kind of thing reviewers reward when documented. The productive target is: (a) explain the residual families mechanistically, (b) show they do not flip any reported ordinal claim (e.g., starvation exists at all VC counts / latency Qos rankings), (c) report both sim and RTL numbers side by side.
9. **Artifact evaluation criteria (ACM/ASPLOS/ISCA/MICRO) check availability, functionality, and result reproduction — not agreement with a second model.** "Reproduced" means a *person* re-obtains the *paper's* results; "Functional" requires "appropriate evidence of verification and validation."
10. **Recommended posture for the paper**: publish the co-simulation gate as a *validation section* with characterized error families + sensitivity analysis, and treat your RTL as the ground truth for the paper's quantitative claims (or report both). Reserve 0-mismatch chasing for the specific residual family (const-early) if a single mechanism (e.g., NI/credit-offset) explains it cheaply.

---

## 1. Q1 — How credible architecture/NoC papers establish simulator credibility

### Observed hierarchy of validation depth (from strongest to most common):

| Validation depth | Examples | Reported tolerance |
|---|---|---|
| Per-flit cycle-exact sim↔RTL agreement | **None found** in published NoC literature (see §3) | — |
| Aggregate curve agreement sim↔RTL (latency/throughput vs load) | BookSim 2.0 (ISPASS 2013) | ≤5% latency, ≤3% throughput |
| Simulator↔simulator agreement (incl. cross-tool) | GARNET vs PoPNet/ViChaR (ISPASS 2009); CODES vs BookSim (Mubarak et al.); BST vs Garnet2.0 (ISPASS 2020); AcENoCs vs Ocin tsim; dependency-aware Garnet vs full gem5 | curves "match"; ≤3.22% avg for trace method |
| Simulator↔measured hardware (aggregate runtime/throughput) | gem5 vs ARM TC2 (ISPASS 2014); ASTRA-sim2.0 vs NCCL on V100; Accel-Sim; VIDUR; DSD-Sim; MAccel-sim | 5%/13%; ~5%; ~20%; ~9%; 14.7%; MAPE 18.06% |
| No validation; bare reported numbers | majority of NoC evaluation sections | — |
| Validate against "known-good" phenomena/curve shapes | 3D NoC in gem5 thesis ("results agree with the accepted notion of 3D NoC performance") | qualitative |

### Concrete quotes with numbers:

**BookSim 2.0 (Jiang, Becker, Michelogiannakis, Balfour, Towles, Kim, Dally — ISPASS 2013):**
> "We have validated the accuracy of the simulator against RTL implementations of NoC routers."
> Validation config: "a 3×3 mesh network with a single VC and 16-flit input buffers... uniform random traffic patterns with a packet size of four flits... collected over a period of 100K cycles."
> "The results show a maximum difference of 5% in network latency measurements."
> "The result shows a maximum difference of 3% in the accepted throughput."
> "To the best of our knowledge, this is one of the first works that validate the results of a network simulator against an actual RTL implementation of a router."
> Note: they explicitly state the *limit* of the RTL comparison: "We are limited to simulating small NoCs due to the time and resource constraints of the RTL simulation; however, the results are applicable to larger network configurations as well."
Source: https://icn.kaist.ac.kr/~jjk12/papers/2013ISPASS.pdf (also IEEE Xplore 6557149)

**GARNET (Agarwal, Krishna, Peh, Jha — ISPASS 2009)** — the canonical gem5/Ruby NoC model validates against **other simulators' published curves**, not RTL:
> "We also simulated other synthetic traffic patterns and validated them against the PoPNet [1] network simulator, establishing that the latency-throughput curves match."
> "We obtained the actual latency numbers from the authors of [19] and plotted them against latency values observed in GARNET... the plots saturate at similar injection rates."
> "GARNET saturates slightly earlier than ViChaR's baseline network. This could be an artifact of different kinds of switch and VC allocators used..." (an acknowledged, published discrepancy)
Source: https://projects.csail.mit.edu/wiki/pub/LSPgroup/PublicationList/garnet.pdf

**gem5 vs real hardware (Gutierrez et al., "Sources of Error in Full-System Simulation", ISPASS 2014):**
> "we are able to achieve a mean percentage runtime error of 5% and a mean [absolute percentage error] of 13% for the SPEC CPU2006 benchmarks"
Source: http://cs.umich.edu/cse/awards/pdfs/ispass_2014-1.pdf

**ASTRA-sim 2.0 (Chang et al., 2023; the standard LLM/wafer-scale training simulator):**
> "The analytical network backend was validated against real NCCL-based All-Reduce operations on NVIDIA V100 GPUs... the analytical model demonstrated a mean error of only 5% compared to actual hardware measurements."
> "The 5% error margin against real systems provides sufficient accuracy for first-order design exploration..."
Source: https://alphaxiv.org/overview/2303.14006

**Accel-Sim (Khairy et al., ISCA 2020):** "preserving validation accuracy within 20% of real hardware measurements" — as quoted by the LLM-simulator survey https://arxiv.org/html/2511.21669v2

**MAccel-sim (multi-GPU extension of Accel-Sim, IISWC 2024 poster):** ReduceScatter validation: "Correlation Factor: 0.9532 / Mean Absolute Percentage Error: 18.06%" and the authors describe the residual cause honestly: "The errors in simulation mostly come from the memory accesses to the host... (not modeled)." Source: https://engineering.purdue.edu/tgrogers/publication/bose-iiswc-poster-2024/bose-iiswc-poster-2024.pdf

**Industry practice — AMD Versal NoC (UG1388):**
> "The tlm model is fast and efficient while the rtl model is near cycle-accurate (typically within 5% of hardware)."
Source: https://docs.amd.com/r/en-US/ug1388-acap-system-integration-validation-methodology/NoC-Simulation ; and https://docs.amd.com/r/1.0-English/pg313-network-on-chip/RTL-versus-SystemC-Models

### Takeaway for Q1
Credible NoC papers establish credibility by (1) using a community-known simulator (BookSim/GARNET/Noxim/SynFull), (2) reproducing prior published curves (cross-simulator), (3) *occasionally* validating against RTL or hardware with **percent-level aggregate agreement**, and (4) publishing artifacts. Direct RTL comparison exists for BookSim and is widely cited as the gold standard of that paper — yet its own numbers are 5%/3% aggregate, single-VC, tiny mesh.

---

## 2. Q2 — BookSim specifically: validation claims and subsequent practice

### What the authors claimed (and didn't claim)
- Claimed: "latency-throughput characteristics of BookSim2 closely match those of the RTL model" — aggregate curves (Fig. 5), ≤5% network latency, ≤3% accepted throughput, on a 3×3 mesh with 1 VC, uniform random, 4-flit packets, 100K cycles. They call it "one of the first works that validate the results of a network simulator against an actual RTL implementation of a router." Source: https://icn.kaist.ac.kr/~jjk12/papers/2013ISPASS.pdf
- NOT claimed: per-flit arrival-cycle parity, bit-exact flit streams, or generality of the RTL config (they explicitly scope RTL validation to "small NoCs").

### How subsequent users validate BookSim
- **Cross-simulator agreement is the norm**: CODES dragonfly model "has been validated by Mubarak et al. against BookSim, a serial cycle-accurate interconnection network simulator" (SC'16 bully paper: https://lanzhiling.github.io/assets/pdf/sc16_bully_final.pdf).
- **BookSim↔RTL is repeated as a claim about the tool, and occasionally re-done**: BST (ISPASS 2020) "validate BookSim SMART models with the RTL implementation" for **bypass routers** specifically, and separately "integrate BookSim in gem5... and compare it with gem5's Simple and Garnet 2.0 NoC models." Source: https://ieeexplore.ieee.org/document/9238620
- **BookSim↔RTL co-sim tooling exists in the community**: `rtl2booksim` (github.com/mohsaied/rtl2booksim) "allows connecting C/C++ simulators, or RTL (Verilog) designs to Booksim" — i.e., the plumbing for a gate like ours exists and is used in practice (mostly for SMART/multi-hop bypass features that BookSim added after the 2013 validation).
- **No GitHub issue or paper documents a per-flit, cycle-exact 0-mismatch gate for BookSim** (searched the booksim GitHub org, follow-on papers, and tooling; the standard language is "nearly identical performance", "closely match", "within X%", curve-level).
- The 3D-NoC extension paper (Simulation Modelling Practice and Theory, 2019) recites the community's understanding: "BookSim2.0 results are validated against the RTL implementation of the NoC router for accuracy." Source: https://www.sciencedirect.com/science/article/pii/S1569190X19300541

### Takeaway for Q2
BookSim's own authors validated it against RTL at **aggregate, percent-level** fidelity on a tiny config. Demanding 0/0 per-flit exactness from *our* RTL↔BookSim pair exceeds what the simulator's creators ever claimed or demonstrated, and no one in the literature has published such a gate.

---

## 3. Q3 — RTL-simulator co-simulation gates: community practice

### What exists
1. **BookSim itself** (see §2): aggregate curve agreement vs an RTL NoC router (2013). This is the canonical precedent for "gate a simulator against an RTL model" — and its acceptance bar was 95–97% aggregate match.
2. **SynFull-RTL** (Leyva, Monemi, Vallejo — NOCS 2022 / IEEE Design&Test): a *methodology paper* for driving RTL NoC routers (using Verilator! "Verilator: It converts the NoC RTL code to an equivalent cycle-accurate C++ model") with realistic traffic. Validation is statistical: "Using N=5 seeds and L=20 provides average results which differ less than 0.67% of SynFull-RTL-Ideal" and "SynFull-RTL average latency is within a 0.58% of the ideal value, whereas SynFull values with 400M cycles differ by up to 3.2%." They compare *averages with confidence*, not per-flit streams. Source: https://upcommons.upc.edu/bitstreams/745bce0c-21cb-40b6-a505-eaa1d421e690/download
3. **gem5+RTL co-simulation frameworks** (López-Paradís et al., ACM TACO/CF 2021, "gem5 + rtl: A Framework to Enable RTL Models Inside a Full-System Simulator"): infrastructure for embedding Verilator models in gem5 — used for *design evaluation*, not for validating gem5's own timing against RTL. Source: https://dl.acm.org/doi/abs/10.1145/3472456.3472461
4. **FireSim / FireAxe (Berkeley, ISCA 2018/2024)**: the "cycle-exact" claim lives here — but it's a different paradigm: the RTL *is* the timing model (FPGA-accelerated), so there is no separate software simulator to reconcile: "enables cycle-exact microarchitectural simulation of silicon-proven RTL designs"; FireAxe offers "an exact-mode which provides cycle-exact results with RTL-level fidelity". Source: https://par.nsf.gov/biblio/10087302 ; https://slice.eecs.berkeley.edu/papers/fireaxe-partitioned-fpga-accelerated-simulation-of-large-scale-rtl-designs-isca-2024-501-515
5. **Bypass-router RTL gates** (BST, ISPASS 2020) — see §2.
6. **FPGA-emulated NoC vs software simulator** (AcENoCs thesis, Texas A&M 2010): hardware (FPGA-implemented NoC) validated against the Ocin tsim software simulator on latency/throughput curves; discrepancies openly attributed to "throttling characteristics of the two simulators" at high load. Source: https://oaktrust.library.tamu.edu/server/api/core/bitstreams/3cd148ab-88f1-4192-8a96-eaa30d26d9c6/content

### What does NOT exist
- No published per-flit, cycle-exact (0-mismatch) co-simulation gate between a cycle-accurate C++ NoC simulator and an independent RTL model. The closest searched-and-found candidates (BookSim 2013, BST 2020, SynFull-RTL 2022, rtl2booksim) all compare distributions/curves/means; when residuals appear (GARNET vs ViChaR, MAccel-sim vs HW, AcENoCs vs Ocin tsim) they are disclosed in the paper.

### Tenstorrent ecosystem (relevant to the paper's setting)
- TT hardware has **two NoCs** (NoC-0, NoC-1) as 2D toruses; traffic and VC mechanisms are documented in official docs (https://deepwiki.com/tenstorrent/tt-isa-documentation/2-network-on-chip-%28noc%29). Multicast performance studies in the repo measure *measured* throughput/latency on hardware (e.g., docs.tt-metal multicast schemes performance study), not any simulation.
- TT-Fabric architecture spec explicitly separates **Data Plane (NoC-based)** from **Control Plane (PCIe)**, and its roadmap includes a "Data Plane Simulator" for functional/replay modeling — with no published cycle-fidelity gate against RTL. Source: https://github.com/tenstorrent/tt-metal/blob/main/tech_reports/TT-Fabric/TT-Fabric-Architecture.md

### Takeaway for Q3
Gating a simulator against RTL is a recognized, respected practice — but the community's accepted form is **curve/distribution agreement with characterized residuals**, and the highest-profile example (BookSim vs RTL) settled for ≤5% latency / ≤3% throughput. Our gate (99.85% flits bit-exact + characterized residual families) is *stronger* evidence than any published precedent.

---

## 4. Q4 — The KV-cache / transformer serving domain: simulation methodology

### What credible papers in this domain actually do
The KV-cache-serving literature divides into (a) real-system measured work, and (b) request/token-level discrete-event simulation. **None validate at NoC flit level; several don't validate timing against hardware at all.**

- **WSC-LLM (ISCA 2025)** — wafer-scale LLM serving on a 2D-mesh NoC with KV-cache management: "an evaluation methodology based on an extended version of the ASTRA-sim simulator." Published at ISCA. Reviewer (Synthesizer persona) probing methodology asked: "is this cross-instance network traffic and potential congestion fully modeled within the Evaluator? And how does the system arbitrate or manage this contention in practice?" — i.e., reviewers ask *whether contention is modeled*, not *how many cycles exact*. Source: https://pages.cs.wisc.edu/~karu/archprisms/dl/isca2025_reviews.html
- **LLMServingSim (Li et al., 2024)** — LLM serving hardware-software co-sim on ASTRA-sim: "providing up to 91.5× faster simulation... while maintaining an error below 14.7% compared to real GPU-based serving systems" (reported by the survey arXiv:2511.21669).
- **VIDUR (Agrawal et al., 2024)** — LLM inference simulator using "empirical profiling and predictive modeling, achieving an average latency estimation error of approximately 9%" (arXiv:2511.21669).
- **DSD-Sim (2026)** — distributed speculation DES: "we validate VIDUR's prefill and decode latency predictions against real hardware measurements and determine RTT values using real measurements"; the simulator's own timing is *inherited credibility* from VIDUR's ~9% error. Source: https://arxiv.org/html/2511.21669v2
- **ASTRA-sim 2.0** — 5% mean error vs NCCL on real GPUs (see §1); the docs' "Validation" page is literally "under construction" for parts of it. https://astra-sim.github.io/astra-sim-docs/validation/validation.html
- **HyMCache (2026, CXL-hybrid KV cache)** — evaluated as a real system (DRAM pools, Mooncake baseline): "Compared with 1 TB distributed-DRAM Mooncake, HyMCache trades a 30% performance gap for a 16× reduction in DRAM usage" — measured, not simulated. Source: https://arxiv.org/html/2607.18141v1
- **KVServe (SIGCOMM 2026, KV compression for disaggregated serving)** — deployed in vLLM; uses "an analytical latency model with a lightweight bandit"; evaluated on datasets/models, not a NoC sim. Source: https://arxiv.org/abs/2605.13734
- **Energy characterization of KV cache offloading (HotCarbon 2026)** — pure hardware measurement ("We present an empirical energy characterization using per-endpoint production agentic trace replay"); no simulation at all. Source: https://hotcarbon.org/assets/2026/paper-20.pdf
- **Queueing-theoretic KV-cache stability (ICML 2026)** — analytical closed-form stability conditions, "cross-scenario validation... gap ≤10% for high confidence." Source: https://github.com/zhaoyang97/Paper-Notes-en (ICML 2026 note)
- **Transformer NoC accelerator simulators (NoCDAS, ACM TOMACS 2025)** — "the correctness of inference output is validated" (functional correctness vs PyTorch), and RE-mode validated against FE-mode (self-consistency); timing is *not* validated against RTL or hardware. Source: https://dl.acm.org/doi/10.1145/3729169
- **GPGPU NoC for LLM apps (AsymFly, IEICE ELEX 2025)** — "request and reply networks" implementation for LLM traffic; validation is simulation-only. Source: https://www.jstage.jst.go.jp/article/elex/22/24/22_22.20250590/_pdf/-char/en

### The specific claim class ("bursty serving traffic starves control traffic on a NoC")
- In NoC literature the *starvation/QoS-separation* phenomenon class has canonical prior treatment via **Express Virtual Channels (Kumar et al., ISCA 2007)** and priority/VC-separation schemes — i.e., the qualitative claim is well-precedented and evaluated in mainstream simulators (BookSim/GARNET-class), where the accepted evidence is latency-throughput curves + per-class latency percentiles, not per-flit exactness.
- WSC-LLM (ISCA 2025) shows that a paper making KV-cache + 2D-mesh + contention claims on an extended ASTRA-sim passes review with aggregate metrics, provided the simulator lineage (ASTRA-sim) is named and contention is actually modeled.

### Takeaway for Q4
In this domain, the credibility bar for simulation is: (1) use a known simulator or one with a hardware-calibration story (~5–15% typical), (2) model contention, (3) report request/token-level metrics with quantiles, (4) optionally validate per-kernel timing against hardware. Flit-level timing exactness is *far above* the domain norm. Our paper's claims would be evaluated on whether contention/starvation is captured and whether trends hold — not on ±couple of cycles.

---

## 5. Q5 — What counts as "enough" credibility for publication

### Reviewers (what actually gets probed)
Evidence from the public ISCA 2025 review corpus (WSC-LLM and Ruche Networks reviews) shows reviewers ask:
- Is the simulator *named* and credible (ASTRA-sim), and are claims grounded in it? ("The evaluation methodology is grounded in RTL-level implementations of the router microarchitectures, which provides a more credible basis for area, timing, and power analysis than high-level simulation models" — written as praise *for* a paper that used RTL routers for area/timing but sim for performance).
- Is contention modeled? (Synthesizer review of WSC-LLM, above).
- Are micro-benchmarks + execution-driven benchmarks both present? (Ruche review: "combination of synthetic traffic patterns... and a comprehensive suite of execution-driven parallel benchmarks" praised).
- No reviewer verbiage anywhere in the scraped corpus demands cycle-exact agreement between a simulator and RTL or another simulator.
Source: https://pages.cs.wisc.edu/~karu/archprisms/dl/isca2025_reviews.html

### Artifact evaluation (the formal bar)
- **ACM badge definitions** (used by ASPLOS (since 2020), MICRO (since 2021), ISCA, MLSys, PADS, etc.):
  - Artifacts Available: "placed in a publicly accessible archival repository... DOI or link... license."
  - Artifacts Evaluated — Functional: "documented, consistent, complete, and exercisable and include **appropriate evidence of verification and validation**."
  - Artifacts Evaluated — Reusable: "(previously called 'reproduced' under ACM's 2020 terminology)... very carefully documented and well-structured to the extent that reuse and repurposing are facilitated."
  - Results Reproduced: "the paper's main results have been successfully obtained by a person or team other than the author" (using artifacts) — i.e., an *independent human re-run*, not a second model.
  Sources: https://sigsim.acm.org/conf/pads/2025/blog/artifact-evaluation/ ; https://github.com/acmsigsoft/artifact-evaluation/issues/7 (ACM definitions) ; https://www.acm.org/publications/artifacts ; https://www.microarch.org/micro59/submit/artifacts.php ("AE has become a common practice... ASPLOS conducting AE in the last six years, and MICRO doing so as well in 2021").
- **Key point**: none of the badges require, or even mention, agreement with a reference RTL. The formal credibility bar is *availability + runnability + independent re-execution of the paper's own results*.

### Is "99.85% match with characterized residual families" publishable?
- Yes. It exceeds every published precedent (BookSim 5%/3%; GARNET "slightly earlier saturation"; gem5 5%/13%; ASTRA-sim 5%; SynFull-RTL 0.58–3.2% bias) in *granularity* of the gate (per-flit vs aggregate) and would read as exceptional methodology if written as a validation section with:
  1. the exact gate definition (per-flit arrival cycle, class, src/dst),
  2. residual-family characterization (ramp drift 0–9; const-early 23–32; VC-scaling) each tied to a mechanism hypothesis,
  3. sensitivity analysis showing the paper's ordinal claims are invariant under the residual envelope,
  4. release of both models + the comparator harness as an artifact.
- Risk pattern to avoid: claiming "cycle-exact" or "reproduces exactly" and being caught at 0.15% — *that* is what reviewers punish. Claiming **documented bounded fidelity** is the safe, precedented framing.

---

## 6. Q6 — Alternative credibility mechanisms credible papers use

1. **Analytical models calibrated to measured hardware**: HopliteRT derives formal latency bounds and then shows "our router never violates the predicted bounds... Our observed latencies are within 20% of the computed bound" (FPT 2017). KVServe (SIGCOMM 2026) uses "an analytical latency model with a lightweight bandit to select profiles... correct[ing] offline-to-online mismatch" (§4). Source: https://nachiket.github.io/publications/hoplitert_fpt-2017.pdf
2. **Cross-simulator agreement**: GARNET↔PoPNet/ViChaR (ISPASS 2009); CODES↔BookSim (Mubarak; SC'16); BST↔Garnet2.0 (ISPASS 2020); AcENoCs↔Ocin tsim (thesis 2010); SynFull↔full-system gem5 ("errors as low as 0.x%", ISCA 2014); dependency-aware Garnet↔gem5 (≤3.22%, NoCArc 2016).
3. **Latency distributions / percentiles instead of point values**: BookSim-era papers plus KV-domain work report mean + percentile latency (P95 TTFT in Solidigm/Dynamo demo and in KVServe-style serving work; the surveys in §4 emphasize quantiles).
4. **Statistical validation with confidence intervals**: SynFull-RTL is the model example (seeds, macro-phase averaging, "differs less than 0.67%... within 0.58% of the ideal", honesty about original SynFull's up-to-15.8% short-run bias) — NOCS 2022.
5. **Validation against "known-true" behavior**: NoCDAS validates functional correctness of inference output vs PyTorch (ACM TOMACS 2025); the 3D gem5 thesis validates against "the accepted notion of 3D NoC performance"; Ruche Networks (ISCA 2025) earns reviewer praise for "a specific performance diagnosis... that lends credibility to the simulation framework" (a *mechanistic explanation* being treated as validation).
6. **Open-source artifact + re-runnable harness**: the single most-effective credibility lever in the current reviewer climate (ACM badges; ASPLOS/MICRO AE tracks; MAccel-sim: "We aim to open-source this work once it has undergone rigorous validation").
7. **Methodology-consistency and trend-robustness (industry view)**: NVArchSim (HPCA 2021, industry track; co-author Nan Jiang = BookSim author):
   > "We utilize only loose cycle accuracy wherever this lack of fidelity does not substantially harm overall system-level simulation accuracy."
   > "we have found that during simulator development we must be willing to accept and embrace that some degree of inaccuracy is inevitable. Focusing on achieving correct trends across hundreds of diverse workloads provides more predictive power for forward-looking studies."
   Source: https://d1qx31qr3h6wln.cloudfront.net/publications/HPCA_2021_NVArchSim.pdf
8. **Bounded-residual honesty**: GARNET's "saturates slightly earlier" note; MAccel-sim's MAPE 18.06% with root cause (PCIe unmodeled); AcENoCs's throttling explanation. Disclosed, mechanistically-attributed residuals are treated as *good methodology*.

---

## 7. Verdict / recommendation for the Gate R1 decision

1. **Is cycle-exact RTL↔simulator agreement a community norm?** No. The strongest precedent (BookSim's own ISPASS 2013 validation) demonstrates aggregated ≤5% latency / ≤3% throughput agreement on a tiny config. No published NoC work reports a per-flit 0-mismatch gate.
2. **Accepted credibility standard for timing claims**: aggregate latency/throughput curves within a few percent of another simulator or of RTL; or request-level simulation validated within ~5–15% of hardware; with named tools, mechanisms, and artifacts. Cycle-exactness is only claimed — and only meaningful — when the RTL itself *is* the simulator (FireSim-style) or in formal verification contexts (SymbiYosys-style equivalence), never as a software-sim emulation gate.
3. **Your situation (99.85% bit-exact + bounded structured residuals)**: this is already *above* the community bar. 0/0 is not worth pursuing as a general gate; the residual structure (deterministic, bounded drift 0–9, const-early 23–32, VC-scaling rate) is strong evidence the remaining differences are model-abstraction artifacts (e.g., credit/NI offsets, allocation tie-breaking order, VC-buffer management details) rather than errors.
4. **What to do instead**:
   - Reframe the gate as the paper's **validation section** ("RTL co-simulation fidelity"): state the gate definition, the 99.85% exactness, and characterize each residual family with a mechanism hypothesis and an explicit invariant check (no residual can flip any reported ordinal claim: which traffic class starves, at which VC counts, latency-rankings across configurations).
   - Report both RTL and BookSim numbers side by side in the paper figures where cycles are quoted.
   - Release RTL + BookSim configs + the comparator as an artifact (this alone meets the modern credibility bar).
   - Optional: chase 0-mismatch only for the single *const-early* family if a cheap mechanism (e.g., NI injection offset / credit round-trip) plausibly explains all 23–32-cycle earliness at once — a one-mechanism fix that would lift exactness further, but do not hold the paper hostage to it.
5. **Do not** write "cycle-exact" anywhere; write "demonstrated per-flit agreement for 99.85% of flits with characterized bounded residuals" — a claim no competing paper in the space can match and one reviewers can verify from your artifact.

---

## Appendix A — Source list (all verified during research)

| # | Source | Key claim | URL |
|---|---|---|---|
| 1 | Jiang et al., "A Detailed and Flexible Cycle-Accurate Network-on-Chip Simulator", ISPASS 2013 | BookSim vs RTL: ≤5% latency, ≤3% throughput, 3×3 mesh, 1VC, 100K cycles | https://icn.kaist.ac.kr/~jjk12/papers/2013ISPASS.pdf |
| 2 | Agarwal et al., GARNET, ISPASS 2009 | Validation vs PoPNet/ViChaR curves; "saturates slightly earlier" | https://projects.csail.mit.edu/wiki/pub/LSPgroup/PublicationList/garnet.pdf |
| 3 | Gutierrez et al., "Sources of Error in Full-System Simulation", ISPASS 2014 | gem5 vs ARM TC2: MPE 5%, MAPE 13% | http://cs.umich.edu/cse/awards/pdfs/ispass_2014-1.pdf |
| 4 | ASTRA-sim 2.0 (Chang et al., 2023) | Analytical network backend: mean 5% error vs NCCL on V100 | https://alphaxiv.org/overview/2303.14006 |
| 5 | Leyva, Monemi, Vallejo, SynFull-RTL, NOCS 2022 | Verilator-based RTL NoC eval; 0.58% vs ideal; SynFull ≤3.2% | https://upcommons.upc.edu/bitstreams/745bce0c-21cb-40b6-a505-eaa1d421e690/download |
| 6 | SynFull, ISCA 2014 | "errors as low as 0.x%" vs full-system/trace | https://www.eecg.utoronto.ca/~enright/ISCA2014-SynFull.pdf (and ACM DL 10.1145/2678373.2665691) |
| 7 | BST: BookSim SMART, ISPASS 2020 | RTL validation of BookSim bypass models; BookSim vs Garnet2.0 comparison | https://ieeexplore.ieee.org/document/9238620 |
| 8 | rtl2booksim (github.com/mohsaied) | Community tool connecting Verilog RTL to BookSim | https://github.com/mohsaied/rtl2booksim |
| 9 | CODES dragonfly vs BookSim (Mubarak et al.; SC'16 "bully" paper) | "validated by Mubarak et al. against BookSim" | https://lanzhiling.github.io/assets/pdf/sc16_bully_final.pdf |
| 10 | FireSim ISCA 2018 / FireAxe ISCA 2024 | Cycle-exact = RTL-as-timing-model paradigm | https://par.nsf.gov/biblio/10087302 ; https://slice.eecs.berkeley.edu/papers/fireaxe-... |
| 11 | López-Paradís et al., gem5+RTL, 2021 | RTL inside full-system sim (infrastructure, not gate) | https://dl.acm.org/doi/abs/10.1145/3472456.3472461 |
| 12 | AcENoCs thesis, Texas A&M 2010 | FPGA-emulated NoC vs Ocin tsim curves; throttling residuals disclosed | https://oaktrust.library.tamu.edu/... (thesis) |
| 13 | AMD UG1388 Versal NoC | "rtl model is near cycle-accurate (typically within 5% of hardware)" | https://docs.amd.com/r/en-US/ug1388-acap-system-integration-validation-methodology/NoC-Simulation |
| 14 | NVArchSim, Villa et al., HPCA 2021 | "loose cycle accuracy" philosophy; "inaccuracy is inevitable"; trends > point accuracy | https://d1qx31qr3h6wln.cloudfront.net/publications/HPCA_2021_NVArchSim.pdf |
| 15 | Accel-Sim, ISCA 2020 | validated "within 20% of real hardware" | via https://arxiv.org/html/2511.21669v2 |
| 16 | VIDUR / LLMServingSim / DSD-Sim (survey 2026) | ~9% / <14.7% / hardware-calibrated DES | https://arxiv.org/html/2511.21669v2 |
| 17 | MAccel-sim poster, IISWC 2024 | NCCL ReduceScatter: corr 0.9532, MAPE 18.06%, PCIe residual disclosed | https://engineering.purdue.edu/tgrogers/publication/bose-iiswc-poster-2024/... |
| 18 | WSC-LLM, ISCA 2025 (public review corpus) | ASTRA-sim-based wafer-scale KV-cache serving on 2D mesh; reviewers probe contention modeling | https://pages.cs.wisc.edu/~karu/archprisms/dl/isca2025_reviews.html |
| 19 | ACM artifact badging (PADS 2025 / acmsigsoft / acm.org) | Functional badge = "appropriate evidence of verification and validation"; Reproduced = human re-run | https://sigsim.acm.org/conf/pads/2025/blog/artifact-evaluation/ ; https://www.acm.org/publications/artifacts |
| 20 | HopliteRT, FPT 2017 | Analytical bounds validated within 20%; "never violates the predicted bounds" | https://nachiket.github.io/publications/hoplitert_fpt-2017.pdf |
| 21 | NoCDAS, ACM TOMACS 2025 | DNN NoC sim validated by inference-output correctness | https://dl.acm.org/doi/10.1145/3729169 |
| 22 | TT ISA docs (NoC-0/NoC-1); TT-Fabric spec | Two NoCs, 2D torus, VC mechanism; data vs control plane split; data-plane simulator on roadmap | https://deepwiki.com/tenstorrent/tt-isa-documentation/2-network-on-chip-%28noc%29 ; https://github.com/tenstorrent/tt-metal/blob/main/tech_reports/TT-Fabric/TT-Fabric-Architecture.md |
| 23 | KVServe, SIGCOMM 2026 | vLLM-embedded KV compression; analytical latency model + bandit | https://arxiv.org/abs/2605.13734 |
| 24 | HyMCache, 2026 | CXL-hybrid KV cache evaluated as real system | https://arxiv.org/html/2607.18141v1 |
| 25 | BookSim 2.0 README / User's Guide (2018) | Positioning: "cycle-accurate interconnection network simulator" (self-description; no per-flit-RTL claims) | https://github.com/booksim/booksim2 ; usermanual.wiki PDF |
| 26 | MVC-SPARC / 3D NoC + gem5 thesis (OSU 2020) | Garnet described as cycle-accurate; validation by "accepted notion" of performance | https://ir.library.oregonstate.edu/downloads/mc87px61x |
| 27 | Dependency-aware Garnet, NoCArc 2016 | trace-based Garnet ≤3.22% / ≤14.97% vs full-system | https://dl.acm.org/doi/10.1145/2994133.2994140 |

## Appendix B — Method notes
- All quotes above were taken verbatim from the fetched documents (PDF text extraction or page text).
- Searches targeted primary sources (paper PDFs, IEEE/ACM pages, official gem5/AMD/Tenstorrent docs, GitHub) plus review corpora; secondary aggregators (e.g., alphaXiv summaries) were only used to locate claims in the primary PDFs.
- The KV-cache "paper of record" for our own project (KV-cache plane separation in transformers, 8x8 mesh, bursty-serving-starves-control claim) was not located in the published literature — consistent with it being an in-preparation manuscript; the domain standards above (WSC-LLM, KVServe, HyMCache, LLMServingSim) define the comparison set reviewers will use.
## 28. Saranya & Rao (JETTA 2024) — async NoC router verification = feasibility, not fidelity

**Source:** Saranya, M.N., Rao, R., "Design and Verification of an Asynchronous NoC Router Architecture for GALS Systems," J. Electronic Testing 40:61–74, 2024. DOI 10.1007/s10836-024-06104-y (full text: eng.auburn.edu JETTA mirror).

**What it is:** functional verification of a baseline asynchronous NoC router (5-port, 4×4 mesh, XY, wormhole, PD-Hybrid domino pipeline, hybrid 1-DR-bit + SR encoding) via Cadence Spectre AMS mixed-level simulation (transistor domino stages + behavioral/structural Verilog router logic, UMC 65nm).

**Why it's in the corpus (the credibility lens):** a textbook "feasibility-not-fidelity" exhibit:
- All "results" are functional waveforms (packet routes, arbiter grants one port under contention, five ports communicate concurrently) — pass/fail only.
- "The verification approach has no timing information"; "preliminary simulation results conform to the objectives."
- **NO synchronous/clocked baseline anywhere in the paper** — the "async is naturally low power" claim is asserted in the intro, never measured against a clocked router. No power/latency/throughput/area/EDP numbers at all.
- The paper therefore cannot and does not answer "is async genuinely better than clocked" — citing it as evidence async wins would be the confident-wrong-number pattern (PITFALLS-class).

**What IS worth taking from it (evaluated 2026-08-14, Steve):**
- Test-case discipline: four minimal targeted scenarios (switch-level routing, no-load network traversal, all-inputs→one-output contention, five-port concurrent communication). Maps directly to our cell framework: TC2 ≡ the onecell/F14 clean-traversal test; TC3 ≡ an iSLIP arbitration-contention cell; TC4 ≡ a same-switch concurrency cell. See seed T3-004 (contention experiment) for the F14-era version.
- The "no critical timing constraints" property of their hybrid encoding is architecture-argued, not measured — treat as claim, not result.

**Not transferable:** async paradigm (domino logic, handshakes, completion detection), AMS toolchain, 65nm transistor-level modeling.
