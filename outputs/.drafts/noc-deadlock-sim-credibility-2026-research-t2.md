# T2 Research Brief — Simulator↔RTL Validation & NoC Simulator Credibility (2025–2026)

**Researcher:** Feynman evidence-gathering subagent (T2)
**Compiled:** 2026-08-14
**Window:** calendar 2026 primary, 2025 for context. Historical baseline (BookSim ISPASS 2013, GARNET ISPASS 2009) only as one-line context.
**Extends:** `docs/research/simulator-credibility-noc-literature.md` (T1 survey). This brief adds 2025–2026 sources only; it does not re-derive the T1 findings.
**Constraint honored:** No PDF bodies were fetched or parsed. All content below comes from metadata, abstracts, HTML pages, repo READMEs, program pages, and web snippets. PDF-only sources are cited with full-text parsing marked **blocked**.

---

## Q1 — 2025–2026 work gating a software NoC simulator against RTL at per-flit/per-cycle granularity

**Headline finding: no 2025–2026 paper was found that gates a software NoC simulator against an RTL model at per-flit/per-cycle (bit-exact or near-bit-exact) granularity.** The T1 conclusion (no published per-flit cycle-exact sim↔RTL gate exists) still holds through mid-2026. The 2025–2026 works that touch RTL do so as (a) RTL-in-the-loop *infrastructure* (no agreement gate claimed), (b) benchmark/instruction-level calibration, or (c) functional (not timing) verification. Evidence, 2026 items first:

- **[1] Microarchitecture Cliffs** (arXiv:2602.11580, 2026-02-12) is the closest 2026 analog: a *benchmark-generation methodology* to calibrate a simulator against RTL as "the ground-truth microarchitecture". Result: "We reduce the performance error of XS-GEM5 from 59.2% to just 1.4% on the Cliff benchmarks" (calibrating the XiangShan gem5 model against the XiangShan RTL). Granularity is benchmark/performance-error, **not per-flit or per-cycle stream agreement** — it is a calibration harness, not a bit-exact gate. URL: https://arxiv.org/abs/2602.11580
- **[6] UniCNet** (IEEE Computer Architecture Letters 25(1):37–40, Jan–Jun 2026; DOI 10.1109/LCA.2026.3653809): README states "Cycle-level chiplet protocol interface model, supporting UCIe protocol and **verified it against RTL model**". This is a claim of RTL verification of the *UCIe interface model* within a BookSim-derived simulator. Detail level (per-flit vs aggregate) not stated in the README; **uncertain — needs full-text check** (PDF blocked). URLs: https://github.com/wangplin/CAL-UniCNet ; https://dblp.uni-trier.de/rec/journals/cal/WangWYLY26.html
- **[13] HyNoC** (arXiv:2607.02729, 2026-07-02): an open-source RTL NoC (FPGA/VLIW) where "Verilator co-simulation measures the deterministic per-hop latency" of *its own RTL*. This is RTL-as-ground-truth (Verilator co-sim of the design itself), **not** an independent software-sim↔RTL agreement gate. URL: https://arxiv.org/abs/2607.02729
- **[5] Rhea** (arXiv:2508.03837, 2025-08-05; v2 2026-03-09): gem5 + Verilator co-simulation for *RTL cache-coherent memory subsystems*; "higher fidelity by simulating real RTL hardware" at "up to 2.7×" simulation overhead vs gem5 MI. RTL-in-the-loop infrastructure; no simulator-vs-RTL timing-agreement gate; memory subsystem, not NoC. URL: https://arxiv.org/abs/2508.03837v2
- **[14] FireBridge** (arXiv:2603.25969, 2026-03-26): "fast, cycle-accurate co-verification framework that bridges production firmware and RTL/gate-level hardware"; claims functional equivalence and 50× debug-iteration speedup — co-verification, not a performance-parity gate. URL: https://arxiv.org/abs/2603.25969
- **[15] UVM-TLM co-simulation for RISC-V** (arXiv:2505.10145, 2025-05-15): an integrated UVM/TLM co-sim framework whose methodology "prioritizes integration, simulation efficiency, and acceptable fidelity for architectural exploration **over cycle-level precision**" — an explicit 2025 statement that non-cycle-precise co-simulation is the accepted norm. URL: https://arxiv.org/abs/2505.10145
- **[16] NoCFuzzer** (IEEE TCAD 2025): "Automating NoC Verification in UVM" — functional verification of NoCs via fuzzing in UVM; it argues Verilator-based open-source flows "offer limited support for SystemVerilog and UVM". Timing agreement with simulators is not its target. Full text blocked (PDF); cited from search snippet + HKUST IR metadata. URLs: https://jyhuang91.github.io/papers/tcad2025-nocfuzzer.pdf (metadata only) ; https://repository.hkust.edu.hk/ir/Record/1783.1-140967 (record page, captcha-blocked on fetch)
- **[8] CHIPSIM** (IEEE Open Journal of the Solid-State Circuits Society, 2025; DOI 10.1109/ojsscs.2025.3626314; arXiv:2510.25958): a chiplet compute+communication *co-simulation framework* ("up to 340% accuracy improvement" over decoupled baselines; Section V-F titled "Hardware Validation" where CiMLoop is replaced by an analytical compute model). Co-simulation *between* simulators/models — not RTL-gated. URL: https://arxiv.org/html/2510.25958
- **[30] XiangShan difftest / co-simulation** (DeepWiki page, accessed 2026-08-14): in the CPU domain, cycle-accurate RTL-vs-reference lockstep ("difftest") is established practice — context showing that the per-cycle RTL gate exists *in CPU verification*, not in NoC performance simulation. URL: https://deepwiki.com/OpenXiangShan/XiangShan/9.1-difftest-and-co-simulation
- **[28] rtl2booksim**: still the only named "connect RTL to BookSim" tool; GitHub API (checked 2026-08-14) shows last code push 2015-11-02, 25 stars, no 2025–2026 development; no 2025–2026 paper found that uses it for a per-flit gate. URL: https://github.com/mohsaied/rtl2booksim

**Q1 bottom line (inference, labeled):** the 2025–2026 literature continues the T1 pattern — aggregate-curve/calibration validation at best; RTL appears as infrastructure (Verilator-in-the-loop) or as ground truth for *model calibration* (Microarchitecture Cliffs), never as a per-flit bit-exact agreement target for a NoC simulator.

---

## Q2 — Validation depth reported in 2025–2026 papers (quantified where possible)

**System-level simulators (2026 items first):**

- **[9] LLMServingSim 2.0** — ISPASS 2026 **Best Paper** (program: https://ispass.org/ispass2026/main.php; paper: https://arxiv.org/html/2602.23036v2). Validation: "LLMServingSim is validated end-to-end against real vLLM on the bundled `(hardware, model)` combos. The numbers below come from running a 300-request ShareGPT replay through both vLLM v0.19.0 and the simulator on RTXPRO6000, then comparing the per-request and per-tick metrics with `python -m bench validate`." (https://llmservingsim.ai/docs/validation). Zenodo artifact: https://zenodo.org/records/18879965. **Note:** "per-tick" = per simulator-clock-tick request metrics, not per-flit.
- **[4] SCALE-Sim TPU** (arXiv:2603.22535, 2026-03-23): "We validate SCALE-Sim's systolic GEMM model against measurements on Google TPU v4 and show that simulated cycle counts exhibit a strong linear correlation with hardware latency"; learned latency models for elementwise ops achieve "median relative errors below 3 percent". Hardware-validated with explicit numbers. URL: https://arxiv.org/abs/2603.22535
- **[12] ATLAHS** (arXiv:2505.08936, 2025-05-13): "Through extensive validation, we demonstrate that ATLAHS achieves high accuracy in simulating realistic workloads (**consistently less than 5% error**), while significantly outperforming AstraSim". **Uncertainty:** the abstract does not state exactly what the <5% error is measured against (real hardware runs vs traces); marked **unverified reference target**. URL: https://arxiv.org/abs/2505.08936
- **[21] MindPalace** (ISPASS 2025): "We calibrate the underlying ChampSim [core]... comparing simulated performance... against real hardware" (snippet). Full text blocked (PDF): https://parallel.princeton.edu/papers/ISPASS2025_MindPalace.pdf
- **[3] Ramulator 2.0 re-evaluation** ("Cleaning up the Mess", arXiv:2510.15744, 2025-10-17; v4 2026-05-08; ISPASS 2026): argues the Mess paper's "poorly resemble the actual system" claims were caused by "demonstrable technical misconfigurations" and that "by correctly configuring Ramulator 2.0, Ramulator 2.0's simulated memory system performance actually resembles real system characteristics well". Shows the field actively disputes what counts as hardware validation. URL: https://arxiv.org/abs/2510.15744
- **[2] Different Perspectives of Memory System Simulation** (arXiv:2604.16965v1, 2026): validation against a real Intel Skylake server; after all corrections "the memory latency of all simulators under study is still below the actual-system measurements. In the saturated memory system, the difference is large, up to 214 ns"; also finds "internal simulator statistics are not only insufficient, but could be misleading". URL: https://arxiv.org/html/2604.16965v1

**NoC-specific 2025–2026 papers (validation depth is thin):**

- **[6] UniCNet** (CAL 2026): validates against **BookSim 2.0 itself** — "Enable multi-thread parallel simulation, achieving up to 4X speedup while maintaining the same accuracy with Booksim2.0" (simulator-vs-simulator; the UCIe interface claim vs RTL is separate, see Q1). URL: https://github.com/wangplin/CAL-UniCNet
- **[7] CAMINOS** (JPDC 204:105136, Oct 2025): new phit-level Rust simulator; abstract mentions no validation section (validation content not checkable without PDF — **blocked**; abstract read via ScienceDirect page). URL: https://www.sciencedirect.com/science/article/pii/S0743731525001030
- **[11] scNoCSim** (Univ. Pisa IRIS record dated 2026-01-01): OMNeT++ wormhole NoC simulator; abstract says "present case studies with validation" — apparently Network Calculus delay/backlog bounds validation; granularity/numbers unknown (**uncertain**). URL: https://arpi.unipi.it/handle/11568/1347650
- **[10] FlexNoC** (ISPASS 2026, pp. 90–103; DOI 10.1109/ISPASS69572.2026.00019): "Fast and Flexible Analysis for NoCs with Arbitrary Topologies and Hybrid Arbitration" — abstract not retrievable without PDF/DOI paywall (**blocked**); cited from program + researchr metadata. URLs: https://ispass.org/ispass2026/program.php ; https://researchr.org/publication/GangulyTLIM26
- **[1] Microarchitecture Cliffs** (2026): the only 2026 work with a *number* for sim↔RTL error reduction in the NoC-adjacent space: 59.2% → 1.4% (CPU/NoC-adjacent, benchmark-level). URL: https://arxiv.org/abs/2602.11580

**Q2 bottom line (inference):** quantified validation (single-digit to low-10s % error vs hardware) is a *norm in system-level (LLM-serving, memory, accelerator) simulation*; NoC-specific 2025–2026 papers overwhelmingly rely on simulator lineage (BookSim/GARNET/Noxim) or simulator-vs-simulator comparison, and none report a per-flit agreement number against RTL.

---

## Q3 — New validation/credibility methodology papers and venues (2025–2026)

- **[2] "Different Perspectives of Memory System Simulation"** (2026, arXiv:2604.16965v1) — a *validation methodology* paper: evaluate simulation from three perspectives (memory-simulator view, CPU–memory-interface view, application view); argues "the application view is the ultimate measure of the memory simulation correctness that should be compared to the actual hardware"; ships an artifact with per-stage results (Zenodo DOI 10.5281/zenodo.19629351; repo https://github.com/bsc-mem/ZSim-mem-Interface). URL: https://arxiv.org/html/2604.16965v1
- **[3] The Ramulator 2.0 / Mess dispute** (2025–2026) — the community's live argument about hardware-validation methodology: misconfiguration vs inherent inaccuracy, wrong-statistics interpretation, artifact completeness ("the Mess paper's artifact repository lacks the necessary sources to fully reproduce"). ISPASS 2026 talk + repo https://github.com/CMU-SAFARI/Cleaning-up-the-Mess. URL: https://arxiv.org/abs/2510.15744
- **[1] Microarchitecture Cliffs** (2026) — calibration methodology with RTL as ground truth + automated tooling ("Cliff workflow"). URL: https://arxiv.org/abs/2602.11580
- **[4] SCALE-Sim TPU** (2026) — validation against real hardware presented as a first-class contribution ("weak validation against real hardware" named as a limitation of prior simulators). URL: https://arxiv.org/abs/2603.22535
- **[20] "Toward Reproducible and Standardized Computer Architecture Simulation with gem5"** (arXiv:2512.13479; ISPASS 2026, DOI 10.1109/ISPASS69572.2026.00027): reproducibility/standardization of simulation artifacts (disk images, kernels, 200+ workloads, Suites/MultiSim); blog: https://arch.cs.ucdavis.edu/simulation/2026/05/26/gem5-resources.html
- **[18] CAMS 2025** (3rd Workshop on Computer Architecture Modeling and Simulation, held with MICRO 2025, 2025-10-18, Seoul) explicitly solicited "**Hardware-in-the-loop Simulation**: Performance modeling and simulator validation with hardware" and "**Validation Techniques**: Approaches for validating the accuracy of simulation models" as workshop topics, plus a "Tool Release Talks" session (e.g., Mess Simulator release). Evidence of 2025 community focus on validation. URL: https://sarchlab.org/cams25
- **[19] ISPASS 2026 Session 2A "Simulation and Simulators"** — includes Ramulator 2.0 real-system re-evaluation, gem5 reproducibility, gem5 call-stack profiling, and Best Paper LLMServingSim 2.0 (with Zenodo artifact). URL: https://ispass.org/ispass2026/program.php
- **[26] Artifact evaluation criteria are unchanged in 2025–2026**: MICRO 2026 AE ("assessed based on the ACM Artifact Review and Badging policy"; "ASPLOS conducting AE in the last six years, and MICRO doing so as well in 2021") and ISCA 2026 AE both run on the current ACM Artifact Review and Badging policy — no 2025–2026 revision found that adds a "agreement with a second model/RTL" requirement. URLs: https://www.microarch.org/micro59/submit/artifacts.php ; https://iscaconf.org/isca2026/submit/artifactevaluation.php ; https://www.acm.org/publications/policies/artifact-review-and-badging-current
- **[27] Noxim** (SystemC NoC simulator, Univ. Catania): added (2026-04-22) "a deterministic regression test suite with pinned YAML configurations and golden outputs" + `./regression.sh` "for reproducible simulator verification across mesh and delta topologies" — reproducibility-as-validation in a mainstream NoC simulator (verified in README via GitHub raw fetch, 2026-08-14). URL: https://github.com/davidepatti/noxim

**Q3 bottom line:** 2025–2026 methodology work concentrates on (a) hardware-facing validation with quantified residuals, (b) artifact completeness as evidence, (c) reproducibility tooling, and (d) explicit "validation as a contribution" framing. No 2025–2026 methodology source was found that demands per-flit cycle-exact agreement.

---

## Q4 — Cycle-accurate NoC simulation tooling 2025–2026 (with validation sections, RTL↔sim comparisons, or reproducibility)

2026 items first:

- **[6] UniCNet** — IEEE CAL 2026 (DOI 10.1109/LCA.2026.3653809): cycle-accurate, BookSim-derived chiplet-network simulator; UCIe interface "verified against RTL model" (README claim); parallel simulation "up to 4X speedup while maintaining the same accuracy with Booksim2.0". URLs: https://github.com/wangplin/CAL-UniCNet ; https://dblp.uni-trier.de/rec/journals/cal/WangWYLY26.html
- **[10] FlexNoC** — ISPASS 2026 (pp. 90–103): "Fast and Flexible Analysis for NoCs with Arbitrary Topologies and Hybrid Arbitration" (IISc + Intel). Abstract blocked; no validation detail available. URL: https://researchr.org/publication/GangulyTLIM26
- **[29] DICE** — ISCA 2026 (arXiv:2607.24221; DOI 10.1109/ISCA66397.2026.00118): runtime PHY modeling in gem5; argues fixed-latency link abstractions "distort inter-chiplet packet-level timing and high-level performance metrics such as IPC, leading to off-trend simulation results" — a 2026 ISCA paper explicitly pushing for finer-grained timing fidelity in interconnect simulation. URL: https://arxiv.org/abs/2607.24221
- **[11] scNoCSim** — 2026 (Univ. Pisa IRIS): OMNeT++-based wormhole NoC simulator with Service-Curve/Network Calculus bounds; "case studies with validation" (nature of validation uncertain). URL: https://arpi.unipi.it/handle/11568/1347650
- **[9] LLMServingSim 2.0** — ISPASS 2026 Best Paper: cycle-level LLM-serving simulator; validation vs real vLLM (see Q2); public validation/artifact pages. URL: https://llmservingsim.ai/docs/validation
- **[27] Noxim** — active 2026 development; deterministic regression suite added 2026-04-22 (see Q3). URL: https://github.com/davidepatti/noxim
- **[13] HyNoC** — arXiv:2607.02729 (2026-07-02): open-source RTL NoC (CERN-OHL-P v2) with Verilator co-simulation for deterministic per-hop latency measurements; 5× throughput claim for quadrant partitioning (RTL-level, not a software-sim gate). URL: https://arxiv.org/abs/2607.02729
- **[24] AMD UG1388 2026.1 (Versal NoC simulation docs)**: "The SystemC model simulates much faster but is cycle approximate and less accurate compared to the SystemVerilog model" — industry documents the RTL-vs-TLM fidelity gap in current (2026.1) releases. URL: https://docs.amd.com/r/en-US/ug1388-acap-system-integration-validation-methodology/NoC-Simulation
- **[25] AMD UG1399 2026.1 (Vitis HLS C/RTL co-simulation)**: industry-standard C/RTL co-simulation flow ("automatically verify the RTL design... using the RTL created by C synthesis") — the industrial pattern for RTL-vs-model checks remains functional equivalence, not cycle-parity publication. URL: https://docs.amd.com/r/en-US/ug1399-vitis-hls/Automatically-Verifying-the-RTL

2025 items:

- **[7] CAMINOS** — JPDC, Oct 2025: phit-level Rust simulator; component-composition design; validation section not checkable (PDF blocked). URL: https://www.sciencedirect.com/science/article/pii/S0743731525001030
- **[17] NetTLMSim** — CAMS 2025 (MICRO 2025): "A Virtual Prototype Simulator for Large-Scale Accelerator Networks" (Konkuk Univ.); metadata only (PDF blocked). URL: https://sarchlab.org/cams25
- **[8] CHIPSIM** — IEEE OJ-SSCS 2025: chiplet co-simulation framework (CiMLoop + HeteroGarnet/BookSim backends); "up to 340% accuracy improvement" vs decoupled baselines; includes a "Hardware Validation" section (read partially via HTML; exact numbers in Section V not fully extracted). URL: https://arxiv.org/html/2510.25958
- **[12] ATLAHS** — arXiv:2505.08936 (May 2025): application-centric network-simulation toolchain (GOAL format), <5% error claim. URL: https://arxiv.org/abs/2505.08936
- **[5] Rhea** — arXiv:2508.03837 (Aug 2025): RTL cache-coherent subsystem design+validation framework with gem5+Verilator co-sim (see Q1). URL: https://arxiv.org/abs/2508.03837v2

**Q4 bottom line:** the 2025–2026 tooling landscape is dominated by chiplet/wafer-scale NoC simulation and LLM-serving simulation; validation sections, where present, are simulator-vs-simulator (UniCNet vs BookSim) or hardware-calibration (LLMServingSim vs vLLM, SCALE-Sim vs TPU v4), not RTL-per-flit gates.

---

## Q5 — Do 2025–2026 papers cite or exceed the BookSim (≤5% latency / ≤3% throughput vs RTL) and GARNET (sim-vs-sim) baselines?

- **[23] BookSim ISPASS 2013 remains the field's citation backbone**: Semantic Scholar (checked 2026-08-14) lists **814 citations** of the 2013 ISPASS paper (DOI 10.1109/ISPASS.2013.6557149), with many 2025–2026 citing works, including: DICE (ISCA 2026), C2C-Explorer (2026), ALCAR (Microelectronics Journal 2026), MAX-SM (IEEE TPDS 2026), ThAME (2026), UpDown (ICS 2026), NeuroMTA (IEEE CAL 2026), HeMu (IEEE TCAD 2026), 3D-TANoC (ISCAS 2026), CAMINOS (JPDC 2025), UniCNet (CAL 2026), scNoCSim (2026), CHIPSIM (2025), ReNoC-ML (APCCAS 2025), and others. URLs: https://ieeexplore.ieee.org/document/6557149/ ; citation data via https://api.semanticscholar.org/graph/v1/paper/DOI:10.1109/ISPASS.2013.6557149
- **[6][7] 2025–2026 NoC papers treat BookSim as the reference to compare against** (UniCNet "same accuracy with Booksim2.0"; CAMINOS cites it; CHIPSIM uses BookSim/HeteroGarnet as a communication backend) — i.e., simulator-vs-simulator benchmarking against BookSim continues; no 2025–2026 paper was found that *re-runs* BookSim's RTL validation or reports exceeding its ≤5%/≤3% aggregate bar at per-flit granularity. URLs: https://github.com/wangplin/CAL-UniCNet ; https://arxiv.org/html/2510.25958
- **No 2025–2026 source found quoting BookSim's specific 5%/3% RTL-validation numbers** in the snippet-level material gathered (**uncertainty marker**: full-text citation mining across ~800 citations was not performed; this is absence-of-evidence-in-searched-sources, not proof of non-citation).
- **GARNET-style simulator-vs-simulator validation persists as the norm**: UniCNet-vs-BookSim (2026) is the clearest 2025–2026 example; no 2025–2026 NoC paper found that validates against measured hardware (the hardware-validated 2025–2026 simulators are system-level: LLMServingSim 2.0, SCALE-Sim TPU, ATLAHS, MindPalace).
- **Historical baseline (one line, per brief rules):** BookSim 2.0 (ISPASS 2013) validated against an RTL NoC router on a 3×3 mesh, 1 VC, 100K cycles with ≤5% latency / ≤3% throughput aggregate agreement; GARNET (ISPASS 2009) validated against other simulators' published curves. Nothing in the 2025–2026 literature was found that exceeds this baseline in granularity.

---

## Evidence table

| # | Source | URL | Key claim | Type | Confidence |
|---|--------|-----|-----------|------|------------|
| 1 | "Benchmarking for Single Feature Attribution with Microarchitecture Cliffs" (arXiv:2602.11580, 2026-02-12) | https://arxiv.org/abs/2602.11580 | Calibrates XS-GEM5 vs XS-RTL: error 59.2% → 1.4%; RTL as ground truth; benchmark-level, not per-flit | primary (abstract, read) | high |
| 2 | "Different Perspectives of Memory System Simulation" (arXiv:2604.16965v1, 2026) | https://arxiv.org/html/2604.16965v1 | 3-perspective validation methodology; interface errors dominate; residual up to 214 ns at saturation; artifact Zenodo 10.5281/zenodo.19629351 | primary (HTML, read) | high |
| 3 | "Cleaning up the Mess: Re-Evaluating the Real-System Modeling Accuracy of Ramulator 2.0" (arXiv:2510.15744; ISPASS 2026) | https://arxiv.org/abs/2510.15744 | Mess paper's "poor accuracy" claims traced to misconfigurations; correct config "resembles real system characteristics well" | primary (abstract, read) | high |
| 4 | "SCALE-Sim TPU: Validating and Extending SCALE-Sim for TPUs" (arXiv:2603.22535, 2026-03-23) | https://arxiv.org/abs/2603.22535 | Validated vs Google TPU v4: strong linear correlation; elementwise latency models median rel. error <3% | primary (abstract, read) | high |
| 5 | "Rhea: Framework for Fast Design and Validation of RTL Cache-Coherent Memory Subsystems" (arXiv:2508.03837, 2025; v2 2026) | https://arxiv.org/abs/2508.03837v2 | gem5+Verilator RTL-in-the-loop; up to 2.7× overhead; higher fidelity via real RTL | primary (abstract, read) | high |
| 6 | "UniCNet" (IEEE CAL 25(1):37–40, 2026, DOI 10.1109/LCA.2026.3653809) | https://github.com/wangplin/CAL-UniCNet ; https://dblp.uni-trier.de/rec/journals/cal/WangWYLY26.html | Cycle-accurate chiplet NoC sim; UCIe interface "verified against RTL model"; "same accuracy with Booksim2.0", 4× parallel speedup | primary (README + dblp metadata, read) | medium (README-level claims; paper PDF blocked) |
| 7 | "The CAMINOS interconnection networks simulator" (JPDC 204:105136, Oct 2025) | https://www.sciencedirect.com/science/article/pii/S0743731525001030 | New phit-level Rust network simulator; no validation claims in abstract; full text blocked | primary (abstract only) | medium |
| 8 | "CHIPSIM: A Co-Simulation Framework for Deep Learning on Chiplet-Based Systems" (IEEE OJ-SSCS 2025; arXiv:2510.25958) | https://arxiv.org/html/2510.25958 | Compute+communication co-sim; "up to 340% accuracy improvement"; Hardware Validation section | primary (HTML, partially read) | medium |
| 9 | "LLMServingSim 2.0" (ISPASS 2026 Best Paper; arXiv:2602.23036) | https://arxiv.org/html/2602.23036v2 ; https://llmservingsim.ai/docs/validation ; https://zenodo.org/records/18879965 | Validated end-to-end vs real vLLM: 300-request ShareGPT replay, per-request/per-tick metric comparison | primary (abstract + docs, read) | high |
| 10 | "FlexNoC" (ISPASS 2026, pp. 90–103, DOI 10.1109/ISPASS69572.2026.00019) | https://researchr.org/publication/GangulyTLIM26 ; https://ispass.org/ispass2026/program.php | "Fast and Flexible Analysis for NoCs with Arbitrary Topologies and Hybrid Arbitration"; abstract/validation not retrievable without PDF | primary (metadata only) | low (blocked) |
| 11 | "A novel simulator for performance analysis in heterogeneous wormhole Network-on-Chips" (scNoCSim, Univ. Pisa IRIS, 2026-01-01) | https://arpi.unipi.it/handle/11568/1347650 | OMNeT++ wormhole NoC simulator with Network Calculus bounds; "case studies with validation" | primary (abstract, read) | medium |
| 12 | "ATLAHS" (arXiv:2505.08936, 2025-05-13) | https://arxiv.org/abs/2505.08936 | App-centric network-sim toolchain; "consistently less than 5% error" (validation reference target not stated in abstract) | primary (abstract, read) | medium |
| 13 | "HyNoC" (arXiv:2607.02729, 2026-07-02) | https://arxiv.org/abs/2607.02729 | Open-source RTL NoC; "Verilator co-simulation measures the deterministic per-hop latency"; 5× quadrant throughput claim | primary (abstract, read) | high |
| 14 | "FireBridge: Cycle-Accurate Hardware + Firmware Co-Verification" (arXiv:2603.25969, 2026-03-26) | https://arxiv.org/abs/2603.25969 | Cycle-accurate firmware+RTL co-verification; functional equivalence; 50× debug speedup | primary (abstract, read) | high |
| 15 | "An Integrated UVM-TLM Co-Simulation Framework for RISC-V" (arXiv:2505.10145, 2025-05-15) | https://arxiv.org/abs/2505.10145 | Co-sim "prioritizes... acceptable fidelity... over cycle-level precision" | primary (abstract, read) | high |
| 16 | "NoCFuzzer: Automating NoC Verification in UVM" (IEEE TCAD 2025) | https://jyhuang91.github.io/papers/tcad2025-nocfuzzer.pdf ; https://repository.hkust.edu.hk/ir/Record/1783.1-140967 | UVM-based functional NoC verification; Verilator flows called limited for UVM | primary (metadata/snippet only; PDF blocked) | medium |
| 17 | "NetTLMSim: A Virtual Prototype Simulator for Large-Scale Accelerator Networks" (CAMS 2025) | https://sarchlab.org/cams25 | New virtual-prototype accelerator-network simulator (Konkuk Univ.); metadata only | primary (metadata only; PDF blocked) | low |
| 18 | CAMS 2025 workshop (3rd Workshop on Computer Architecture Modeling and Simulation, w/ MICRO 2025, 2025-10-18, Seoul) | https://sarchlab.org/cams25 | Topics explicitly include "Hardware-in-the-loop Simulation" and "Validation Techniques"; tool-release session | primary (workshop page, read) | high |
| 19 | ISPASS 2026 program (2026-04-26/28, Seoul) | https://ispass.org/ispass2026/program.php ; https://ispass.org/ispass2026/main.php | Session 2A Simulation & Simulators; Best Paper LLMServingSim 2.0; Ramulator 2.0 re-eval; gem5 reproducibility | primary (program page, read) | high |
| 20 | "Toward Reproducible and Standardized Computer Architecture Simulation with gem5" (ISPASS 2026; arXiv:2512.13479) | https://arch.cs.ucdavis.edu/simulation/2026/05/26/gem5-resources.html ; https://arxiv.org/abs/2512.13479 | gem5 Resources: 2000+ artifacts, 12 disk images, Suites/MultiSim for reproducibility | primary (blog + abstract, read) | high |
| 21 | "Evaluation of MindPalace for Chip Design Tradeoffs on Function-as-a-Service" (ISPASS 2025) | https://parallel.princeton.edu/papers/ISPASS2025_MindPalace.pdf | Calibrates ChampSim against real hardware via performance counters | primary (snippet only; PDF blocked) | medium |
| 22 | "ONNXim: A Fast, Cycle-level Multi-core NPU Simulator" (arXiv:2406.08051; IEEE CAL 2024) — context, out of window | https://arxiv.org/html/2406.08051v1 | NPU core model vs Gemmini RTL: "average absolute error of 0.23%" — closest published cycle-level sim↔RTL validation precedent (2024) | primary (abstract, read) | high |
| 23 | BookSim 2.0 ISPASS 2013 + Semantic Scholar citation data (checked 2026-08-14) | https://ieeexplore.ieee.org/document/6557149/ ; https://api.semanticscholar.org/graph/v1/paper/DOI:10.1109/ISPASS.2013.6557149 | 814 citations; dozens of 2025–2026 citing works (DICE ISCA'26, C2C-Explorer, CAMINOS, UniCNet, CHIPSIM, scNoCSim, ReNoC-ML, ...) | secondary (citation DB) | high |
| 24 | AMD UG1388 — "NoC Simulation", 2026.1 English | https://docs.amd.com/r/en-US/ug1388-acap-system-integration-validation-methodology/NoC-Simulation | "The SystemC model... is cycle approximate and less accurate compared to the SystemVerilog model" (2026.1 revision) | secondary (official docs, snippet) | high |
| 25 | AMD UG1399 — "Automatically Verifying the RTL", 2026.1 English | https://docs.amd.com/r/en-US/ug1399-vitis-hls/Automatically-Verifying-the-RTL | Industry C/RTL co-simulation validates RTL against C testbench (functional equivalence) | secondary (official docs, snippet) | high |
| 26 | MICRO 2026 AE / ISCA 2026 AE pages | https://www.microarch.org/micro59/submit/artifacts.php ; https://iscaconf.org/isca2026/submit/artifactevaluation.php ; https://www.acm.org/publications/policies/artifact-review-and-badging-current | AE criteria = ACM Artifact Review and Badging; no RTL-agreement requirement; unchanged in 2025–2026 | primary (official pages, read) | high |
| 27 | Noxim (Univ. Catania) repo — README, 2026-04-22 entry | https://github.com/davidepatti/noxim | Deterministic regression suite + `./regression.sh` for reproducible simulator verification (verified via raw README fetch) | primary (README, read) | high |
| 28 | rtl2booksim repo (GitHub API, checked 2026-08-14) | https://github.com/mohsaied/rtl2booksim | Last code push 2015-11-02; 25 stars; no 2025–2026 activity; no 2025–2026 papers found using it | primary (repo metadata) | high |
| 29 | "DICE: Detailed Inter-Chiplet End-to-End PHY Modeling" (arXiv:2607.24221; ISCA 2026) | https://arxiv.org/abs/2607.24221 | Fixed-latency link abstractions "distort inter-chiplet packet-level timing... leading to off-trend simulation results"; runtime PHY modeling in gem5 | primary (abstract, read) | high |
| 30 | XiangShan difftest / co-simulation (DeepWiki) | https://deepwiki.com/OpenXiangShan/XiangShan/9.1-difftest-and-co-simulation | CPU-domain cycle-accurate RTL-vs-reference lockstep (context) | secondary (docs, snippet) | medium |
| 31 | ESWEEK 2025 guidebook (PDF) | http://esweek.org/wp-content/uploads/2025/09/esweek25-guidebook.pdf | Confirms NOCS co-located with ESWEEK 2025; full text blocked | primary (PDF, blocked) | low |
| 32 | "Probabilistic Verification for Modular Network-on-Chip Systems" (arXiv:2511.13890, 2025-11-17) | https://doi.org/10.48550/arxiv.2511.13890 | Quantitative/formal NoC verification (power-supply-noise focus); verification ≠ timing-sim validation | primary (abstract, read) | medium |
---

## Findings (synthesis, with inline references)

1. **The per-flit/per-cycle RTL gate remains unpublished through mid-2026.** No 2025–2026 NoC paper gates a software NoC simulator against RTL at per-flit/cycle granularity [1][6][13][15]. The nearest 2026 work (Microarchitecture Cliffs) calibrates a *CPU* simulator against RTL at benchmark granularity (59.2% → 1.4% error) [1]; the nearest *cycle-level* RTL-validation number in the broader accelerator space is ONNXim's 0.23% average absolute error vs Gemmini RTL — from 2024, outside the window [22]. RTL appears in 2025–2026 work as in-the-loop infrastructure (Rhea, HyNoC, FireBridge) [5][13][14], not as an agreement target for a separate software simulator.
2. **Quantified validation in 2025–2026 is a system-level phenomenon.** LLMServingSim 2.0 (ISPASS 2026 Best Paper) validates end-to-end against real vLLM with per-request/per-tick comparison [9]; SCALE-Sim TPU reports a strong linear correlation with TPU v4 hardware and <3% median relative error on learned latency models [4]; ATLAHS claims <5% error [12]; the memory-sim community reports multi-perspective validation with documented residuals up to 214 ns at saturation [2], and is simultaneously litigating whether prior "poor accuracy" results were misconfiguration artifacts (Ramulator 2.0 re-evaluation) [3][19]. NoC-specific 2025–2026 papers mostly skip hardware/RTL validation entirely or validate simulator-vs-simulator (UniCNet vs BookSim) [6][7][11].
3. **Credibility methodology in 2025–2026 = calibration to hardware/RTL + artifact completeness + reproducibility; no RTL-agreement requirement added.** The ACM Artifact Review and Badging policy is unchanged and is what MICRO 2026 / ISCA 2026 / ASPLOS run [26]; CAMS 2025 explicitly solicited hardware-in-the-loop and validation-technique papers [18]; Noxim added a deterministic regression suite in April 2026 [27]; LLMServingSim 2.0 and the memory-sim paper ship Zenodo artifacts with validation scripts [2][9].
4. **New tooling 2025–2026 is chiplet/LLM-oriented; validation sections are thin.** UniCNet (CAL 2026) [6], CAMINOS (JPDC 2025) [7], FlexNoC (ISPASS 2026) [10], scNoCSim (2026) [11], NetTLMSim (CAMS 2025) [17], CHIPSIM (2025) [8], DICE (ISCA 2026) [29], HyNoC (2026) [13], LLMServingSim 2.0 [9], ATLAHS [12]. DICE is notable: an ISCA 2026 paper arguing that simplified fixed-latency link models distort packet-level timing [29] — a 2026 signal that reviewers accept (indeed reward) finer-grained timing fidelity arguments.
5. **BookSim remains the citation backbone; its RTL-validation claim is recited but not re-run or exceeded.** 814 citations as of 2026-08-14, with dozens of 2025–2026 citing works [23]; 2025–2026 NoC papers benchmark *against* BookSim rather than against RTL [6][8]; no 2025–2026 source found (at snippet level) that reproduces BookSim's ≤5%/≤3% RTL validation or pushes to per-flit agreement. GARNET-style simulator-vs-simulator validation persists [6].
6. **Implication for the project (inference, labeled):** an 8×8-mesh RTL NoC co-simulated against BookSim at ~83–98% per-flit agreement, with characterized residual families, is stronger validation evidence than anything published in the 2025–2026 window — the window's best-paper example (LLMServingSim 2.0) validates at request/tick granularity against *software* (vLLM), and the window's RTL-calibration example (Microarchitecture Cliffs) reports 1.4% residual at benchmark granularity. No reviewer-facing standard found in 2025–2026 requires per-flit cycle-exactness.

---

## Sources (numbered, matching evidence table)

1. Trevor E. Carlson et al., "Benchmarking for Single Feature Attribution with Microarchitecture Cliffs" (arXiv:2602.11580, 2026-02-12) — https://arxiv.org/abs/2602.11580
2. P. Esmaili-Dokht et al. (BSC/UPC), "Different Perspectives of Memory System Simulation" (arXiv:2604.16965v1, 2026) — https://arxiv.org/html/2604.16965v1
3. N. Bostanci, H. Luo, A. Olgun, O. Mutlu et al., "Cleaning up the Mess: Re-Evaluating the Real-System Modeling Accuracy of Ramulator 2.0" (arXiv:2510.15744; ISPASS 2026) — https://arxiv.org/abs/2510.15744
4. J. Dang et al., "SCALE-Sim TPU: Validating and Extending SCALE-Sim for TPUs" (arXiv:2603.22535, 2026-03-23) — https://arxiv.org/abs/2603.22535
5. A. Galimberti et al., "Rhea: a Framework for Fast Design and Validation of RTL Cache-Coherent Memory Subsystems" (arXiv:2508.03837; v2 2026-03-09) — https://arxiv.org/abs/2508.03837v2
6. P. Wang, M. Wang, Z. Ye, T. Lu, Z. Yu, "UniCNet: Unified Cycle-Accurate Simulation for Composable Chiplet Network With Modular Design-Integration Workflow", IEEE CAL 25(1):37–40, 2026 (DOI 10.1109/LCA.2026.3653809) — https://github.com/wangplin/CAL-UniCNet ; https://dblp.uni-trier.de/rec/journals/cal/WangWYLY26.html
7. C. Camarero, D. Postigo, P. Fuentes, "The CAMINOS interconnection networks simulator", JPDC 204:105136, Oct 2025 — https://www.sciencedirect.com/science/article/pii/S0743731525001030
8. L. Pfromm et al., "CHIPSIM: A Co-Simulation Framework for Deep Learning on Chiplet-Based Systems", IEEE OJ-SSCS 2025 (DOI 10.1109/ojsscs.2025.3626314) — https://arxiv.org/html/2510.25958
9. J. Cho et al., "LLMServingSim 2.0: A Unified Simulator for Heterogeneous and Disaggregated LLM Serving Infrastructure", ISPASS 2026 (Best Paper) — https://arxiv.org/html/2602.23036v2 ; https://llmservingsim.ai/docs/validation ; https://zenodo.org/records/18879965
10. A. Ganguly et al., "FlexNoC: Fast and Flexible Analysis for NoCs with Arbitrary Topologies and Hybrid Arbitration", ISPASS 2026, pp. 90–103 (DOI 10.1109/ISPASS69572.2026.00019) — https://researchr.org/publication/GangulyTLIM26
11. G. Stea et al., "A novel simulator for performance analysis in heterogeneous wormhole Network-on-Chips" (scNoCSim, 2026-01-01) — https://arpi.unipi.it/handle/11568/1347650
12. S. Shen et al., "ATLAHS: An Application-centric Network Simulator Toolchain for AI, HPC, and Distributed Storage" (arXiv:2505.08936, 2025-05-13) — https://arxiv.org/abs/2505.08936
13. C. Clienti et al., "HyNoC: A Hybrid Circuit-Switch/Wormhole Network-on-Chip for Distributed VLIW Computing on FPGA" (arXiv:2607.02729, 2026-07-02) — https://arxiv.org/abs/2607.02729
14. G. Abarajithan et al., "FireBridge: Cycle-Accurate Hardware + Firmware Co-Verification for Modern Accelerators" (arXiv:2603.25969, 2026-03-26) — https://arxiv.org/abs/2603.25969
15. R. Qiu et al., "An Integrated UVM-TLM Co-Simulation Framework for RISC-V Functional Verification and Performance Evaluation" (arXiv:2505.10145, 2025-05-15) — https://arxiv.org/abs/2505.10145
16. J. Huang et al., "NoCFuzzer: Automating NoC Verification in UVM", IEEE TCAD 2025 — https://jyhuang91.github.io/papers/tcad2025-nocfuzzer.pdf (metadata only); https://repository.hkust.edu.hk/ir/Record/1783.1-140967
17. J. Heo et al., "NetTLMSim: A Virtual Prototype Simulator for Large-Scale Accelerator Networks", CAMS 2025 — https://sarchlab.org/cams25
18. CAMS 2025 — The 3rd Workshop on Computer Architecture Modeling and Simulation (w/ MICRO 2025, 2025-10-18, Seoul) — https://sarchlab.org/cams25
19. ISPASS 2026 Program and main page — https://ispass.org/ispass2026/program.php ; https://ispass.org/ispass2026/main.php
20. K. Pai et al., "Toward Reproducible and Standardized Computer Architecture Simulation with gem5", ISPASS 2026 (DOI 10.1109/ISPASS69572.2026.00027; arXiv:2512.13479) — https://arch.cs.ucdavis.edu/simulation/2026/05/26/gem5-resources.html
21. "Evaluation of MindPalace for Chip Design Tradeoffs on Function-as-a-Service", ISPASS 2025 — https://parallel.princeton.edu/papers/ISPASS2025_MindPalace.pdf (metadata only)
22. J. Kim et al., "ONNXim: A Fast, Cycle-level Multi-core NPU Simulator", IEEE CAL 2024 (arXiv:2406.08051) — https://arxiv.org/html/2406.08051v1 (context, out of window)
23. N. Jiang et al., "A Detailed and Flexible Cycle-Accurate Network-on-Chip Simulator", ISPASS 2013 — https://ieeexplore.ieee.org/document/6557149/ ; citation data: https://api.semanticscholar.org/graph/v1/paper/DOI:10.1109/ISPASS.2013.6557149
24. AMD, "NoC Simulation", UG1388 Versal ACAP System Integration & Validation Methodology Guide, 2026.1 — https://docs.amd.com/r/en-US/ug1388-acap-system-integration-validation-methodology/NoC-Simulation
25. AMD, "Automatically Verifying the RTL", UG1399 Vitis HLS User Guide, 2026.1 — https://docs.amd.com/r/en-US/ug1399-vitis-hls/Automatically-Verifying-the-RTL
26. MICRO 2026 Artifact Evaluation; ISCA 2026 Artifact Evaluation; ACM Artifact Review and Badging policy (current) — https://www.microarch.org/micro59/submit/artifacts.php ; https://iscaconf.org/isca2026/submit/artifactevaluation.php ; https://www.acm.org/publications/policies/artifact-review-and-badging-current
27. Noxim NoC simulator repository (Univ. Catania; regression suite added 2026-04-22) — https://github.com/davidepatti/noxim
28. rtl2booksim (mohsaied) — https://github.com/mohsaied/rtl2booksim
29. R. Aligholipour et al., "DICE: Detailed Inter-Chiplet End-to-End PHY Modeling for Accurate Chiplet Simulation", ISCA 2026 (arXiv:2607.24221) — https://arxiv.org/abs/2607.24221
30. OpenXiangShan, "Difftest and Co-Simulation" (DeepWiki) — https://deepwiki.com/OpenXiangShan/XiangShan/9.1-difftest-and-co-simulation
31. ESWEEK 2025 Guidebook (PDF; blocked) — http://esweek.org/wp-content/uploads/2025/09/esweek25-guidebook.pdf
32. "Probabilistic Verification for Modular Network-on-Chip Systems" (extended version, arXiv:2511.13890, 2025-11-17) — https://doi.org/10.48550/arxiv.2511.13890

---

## Search log (exact queries run)

Web searches (web_search tool; providers auto; all queries verbatim):
1. `NoC simulator validation against RTL 2026`
2. `cycle-accurate network-on-chip simulator RTL co-simulation 2025 2026`
3. `network simulator validation hardware computer architecture 2025 2026`
4. `simulator credibility validation computer architecture 2026 paper`
5. `BookSim RTL co-simulation 2025 2026 per-flit validation`
6. `UVM co-simulation network-on-chip RTL 2025`
7. `FPGA in the loop NoC simulation validation 2025 2026`
8. `cycle-exact simulator RTL agreement per-flit network-on-chip`
9. `NOCS 2025 network-on-chip symposium papers validation`
10. `NOCS 2026 papers network-on-chip simulator`
11. `CAMINOS interconnection networks simulator validation 2025`
12. `UniCNet chiplet network simulator paper 2025 2026`
13. `BookSim validation RTL 5% latency 3% throughput cited 2025 2026 paper`
14. `"BookSim" "validated against RTL" 2025 2026`
15. `ISPASS 2025 2026 simulator validation papers architecture`
16. `ONNXim multi-core NPU simulator Gemmini RTL validation accuracy`
17. `NOCS 2025 accepted papers network-on-chip symposium`
18. `scNoCSim OMNeT++ network-on-chip simulator year validation`
19. `NOCS 2025 symposium program papers ESWEEK`
20. `NOCS 2026 20th International Symposium Networks-on-Chip`
21. `OPENEDGES OAD network description language evaluation framework NoC IP`
22. `"An End-to-End Evaluation Framework for NoC IP" CAMS 2025`
23. `RTL in the loop network simulation Verilator co-simulation 2025 2026 chip`
24. `ISPASS 2026 program simulator validation hardware accuracy`
25. `rtl2booksim used 2025 2026 papers BookSim Verilog co-simulation`
26. `19th IEEE ACM International Symposium Networks-on-Chip NOCS 2025`
27. `OpenNoC RTL network-on-chip simulator validation 2025 2026`
28. `FlexNoC fast flexible NoC arbitrary topologies hybrid arbitration ISPASS 2026`
29. `artifact evaluation criteria 2026 ASPLOS ISCA MICRO ACM badges reproducibility`
30. `LLMServingSim 2.0 validation real hardware accuracy simulator`
31. `LLMServingSim 2.0 unified simulator heterogeneous disaggregated LLM serving ISPASS 2026`
32. `NOCS 2025 IEEE proceedings 19th networks-on-chip`
33. `ReNoC-ML reliability-aware network-on-chip machine learning 2025`
34. `Hybrid simulator infrastructure large-scale distributed training architectures 2025 paper`
35. `IEEE Xplore NOCS 2025 proceedings networks-on-chip 2025`
36. `simulator equivalence checking RTL co-simulation 2026 per cycle agreement`

API / tool queries:
- Semantic Scholar Graph API: `DOI:10.1109/ISPASS.2013.6557149` (citations, fields=title,year,externalIds; offsets 0 and 20); `paper/search?query=BookSim RTL validation network-on-chip`; `paper/search?query=cycle-exact co-simulation RTL network`; `paper/search?query=per-flit RTL simulator validation`; `paper/search?query=network-on-chip simulator validation RTL` (last three returned empty/rate-limited — see Coverage Status).
- GitHub API: `repos/mohsaied/rtl2booksim` (pushed_at, stars); `repos/davidepatti/noxim` (pushed_at, recent commits).
- Raw fetch: `raw.githubusercontent.com/davidepatti/noxim/master/README.md` (verified 2026-04-22 regression-suite entry).
- `alpha search` (alphaXiv CLI): attempted `NoC simulator validation RTL`, `network-on-chip simulator validation hardware`, `network-on-chip simulator RTL validation`, `cycle-accurate NoC simulation 2025` — **all failed with network error "fetch failed"** (see Coverage Status).

---

## Coverage Status

**Checked directly (read full content, not just metadata):** arXiv abstracts/HTML for sources 1, 2, 3, 4, 5, 8, 9, 12, 13, 14, 15, 29, 32; repo READMEs 6, 27 (raw), 28 (GitHub API); workshop/program pages 18, 19, 26; blog 20; citation DB 23.

**Metadata/snippet-only (full-text parsing blocked per brief rules):** 7 (CAMINOS — PDF), 10 (FlexNoC — paywalled/PDF), 16 (NoCFuzzer — PDF), 17 (NetTLMSim — PDF), 21 (MindPalace — PDF), 24/25 (AMD docs — snippet-level from search), 30 (DeepWiki — snippet), 31 (ESWEEK guidebook — PDF), 11 (scNoCSim — abstract only, no numbers).

**Uncertain / needs follow-up:**
- NOCS 2025 and NOCS 2026 program-level metadata could not be retrieved (dblp NOCS index lists proceedings through 2023; no IEEE Xplore NOCS 2025 proceedings page surfaced; ESWEEK 2025 guidebook is PDF-blocked). Any claims about "what NOCS 2025/2026 papers did for validation" are therefore **not covered** in this brief.
- Whether any 2025–2026 paper quotes BookSim's specific 5%/3% RTL-validation numbers: only snippet-level checking was possible; full-text citation mining across 800+ citations was not performed. Marked as absence-of-evidence.
- UniCNet's "verified against RTL model" claim detail level (per-flit vs aggregate): README-only; paper PDF blocked.
- ATLAHS's "<5% error" validation reference target (real hardware vs traces): not stated in abstract.
- scNoCSim's "case studies with validation" nature (Network Calculus bounds vs RTL): abstract-only.

**Blocked tasks:**
- `alpha search` (alphaXiv CLI) failed with network errors on all 4 attempts (2026-08-14) — no alphaXiv-based searches were completed; web_search used instead.
- Semantic Scholar search API rate-limited (HTTP 429) on 3 of 5 queries; citation data for BookSim (2013) retrieved successfully before rate-limiting.

**Question status:** Q1 `done` (no per-flit gates found in 2025–2026); Q2 `done` (quantified where available; several items marked uncertain); Q3 `done`; Q4 `done`; Q5 `done` with the citation-mining caveat above.
