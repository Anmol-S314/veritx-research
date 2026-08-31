# DSE Harness Improvement Plan & Paper Readiness Assessment

**Date:** 2026-08-23  
**Scope:** Complete DSE pipeline audit — evaluator, search, recommend, calibration, RTL generation, and paper readiness  
**Goal:** Make the harness production-ready and paper-publishable

---

## THE PIPELINE TODAY (what works)

```
spec_translate → milp_topology → deadlock_routing → [BookSim eval] → gen_rtl → [RTL proof]
       ↑                                                                    ↑
  customer reqs                                                       certify.sh
```

**What works end-to-end:**
1. Frontdoor: plain-language requirements → typed spec → derived matrix → synthesized topology → BookSim proof (beats mesh -23.4%)
2. DSE search: grid/BO over (topology × vcs × buf × routing × arbiter) with F2 ranking
3. RTL generation: anynet → router + TB + Makefile → Verilator binary
4. Certification: cert harness 144/144 on mesh_4x4 (old template)
5. Calibration: BookSim vs RTL Spearman correlation (partial, 1 config)
6. Workload library: 5 reference workloads in workloads.json

---

## WHAT'S MISSING FOR A PAPER (ISCA/MICRO/MLSys bar)

### The Paper's Testable Thesis (from comms)

Jane's state doc says: "the paper's testable thesis is not yet specified — that's the thing we should align on next." This is the #1 gap. Without a clear thesis, there's no paper.

**Candidate thesis:** "A constraint-driven NoC synthesizer that derives topology, routing, and flow control from workload specifications produces fabrics that outperform hand-tuned meshes by X% on real LLM serving traffic, with formal deadlock guarantees."

**What the thesis needs:**
1. A claim (X% improvement over baseline)
2. A method (the DSE pipeline)
3. Evidence (calibration + certification + real workload results)
4. Honest scope (what the tool can and can't do)

### Paper Evidence Requirements

| Requirement | Status | Gap |
|-------------|--------|-----|
| Cycle-accurate simulation | ✅ BookSim2 | None |
| Real workload traffic | ✅ qwen3 trace | None |
| Topology synthesis | ✅ milp_topology_v2 | None |
| Deadlock certification | ✅ deadlock_routing CDG | None |
| RTL validation | ⚠️ Old template only | v2 template untested |
| Rank agreement (BookSim vs RTL) | ❌ Not done | Core deliverable (8055) |
| Cross-simulator validation | ❌ Not done | FlooNoC/gem5 comparison |
| Area/power/timing | ❌ Not wired | PPA column missing |
| Statistical significance | ⚠️ Single seed | Need multi-seed + confidence intervals |
| Ablation studies | ❌ Not done | Need to show each component matters |
| Comparison vs prior art | ❌ Not done | Need vs BookSim auto-topo, vs手工 design |

---

## DETAILED IMPROVEMENT PLAN

### 1. EVALUATOR (evaluator.py) — 12 issues

#### E1.1. Trace-to-matrix loses temporal information
- **What:** `_trace_to_matrix()` aggregates the entire trace into a single static matrix. Time-varying traffic patterns (prefill → decode → MoE dispatch) are averaged into one flat distribution.
- **Impact:** The DSE evaluates configs against a time-averaged traffic pattern, not the actual temporal sequence. A config that's optimal for the average may be terrible for any individual phase.
- **Fix:** Already partially addressed by `run_booksim_phases()` and `run_booksim_windowed()`. But these are not wired into the main `recommend.py` flow — they're standalone functions. Wire phase evaluation into the default path when `traffic_phases` is set.

#### E1.2. Burst envelope approximation is crude
- **What:** `_trace_burst_stats()` computes peak/mean injection rate in a 100-cycle window. The `on_off` traffic model with fixed `burst_alpha=0.3, burst_beta=0.3` is a generic approximation, not trace-fitted.
- **Impact:** Real workload bursts (5-56x measured) are poorly approximated. The DSE may recommend configs that work for the average burst but not the worst case.
- **Fit per-trace burst parameters** from the actual trace (alpha = fraction of time in burst state, beta = mean burst duration). Or use the `traffic_model.py` burst model (once implemented, T046).

#### E1.3. Bank contention model uses mean rates, not peak
- **What:** `bank_contention()` in `memory_miss_model.py` computes M/D/1 queueing delay from mean access rate. Real memory traffic is bursty — the queueing delay at peak is much higher than at mean.
- **Impact:** The DSE underestimates memory contention at high IR. The 4x saturation gap (9ce5) is partially caused by this.
- **Fix:** Pass peak rate to bank_contention, not just mean. Or compute contention at the peak injection rate and use that as the upper bound.

#### E1.4. Windowed evaluation loses cross-window dependencies
- **What:** `run_booksim_windowed()` slices the trace into 1M-cycle windows with 50% overlap. Each window is evaluated independently. But network state (credits, queue occupancy) carries over between windows in reality.
- **Impact:** The windowed evaluation may overestimate latency for configs that benefit from warm-up (credits pre-loaded) or underestimate for configs that suffer from cold-start.
- **Mitigation:** Document this as a known limitation. The overlap helps but doesn't eliminate the boundary effect.

#### E1.5. No confidence intervals on results
- **What:** Each config is evaluated with a single seed (default 42). No error bars, no statistical significance testing.
- **Impact:** Paper reviewers will ask "is this result statistically significant?" We can't answer. A config that's "better" by 0.5 cycles might just be noise.
- **Fix:** Run each config with 3-5 seeds, report mean ± std. Add a paired t-test or bootstrap confidence interval to the ranking.

#### E1.6. Cache invalidation is fragile
- **What:** `_config_hash()` uses a SHA-1 of (topology, vcs, ir, buf, routing, arbiter, workload_type, traffic, seed, traffic_file_hash). But if the BookSim binary changes (recompiled with different flags), the cache returns stale results.
- **Impact:** After a BookSim rebuild, cached results from the old binary are used. The G6 stale-binary fix addressed the RTL side but not the BookSim side.
- **Fix:** Include BookSim binary hash (or mtime) in the cache key.

#### E1.7. Fat-tree topology derivation is magic-number-heavy
- **What:** `k = int(round((v.get('x_dim', 8) ** 2) ** (1/3)))` — derives k from x_dim with a cube-root approximation. If x_dim is not a perfect cube, k is wrong.
- **Impact:** Non-power-of-3 node counts produce incorrect fat-tree configs.
- **Fix:** Validate that k^n = nodes. Raise error if not exact.

#### E1.8. No per-flow latency breakdown
- **What:** The evaluator returns average latency across all packets. It doesn't break down latency by flow class (MoE dispatch vs allreduce vs KV cache reads).
- **Impact:** The DSE can't optimize for latency-critical flows separately from best-effort flows. The paper can't show per-class improvements.
- **Fix:** Add per-(src,dst) or per-class latency extraction from BookSim's `flits.txt` output.

#### E1.9. Workload-type synthesis is unvalidated
- **What:** `llm_traffic.generate_llm_pattern()` synthesizes MoE dispatch, TP allreduce, and KV cache traffic patterns. But these are heuristic patterns, not derived from real model execution traces.
- **Impact:** The DSE may recommend configs optimized for synthetic patterns that don't match real workload behavior.
- **Fix:** Validate synthetic patterns against real qwen3 trace (compare spatial distribution, temporal shape, burstiness). Document the validation.

#### E1.10. Parallel search has no progress tracking
- **What:** `grid_search()` with `ProcessPoolExecutor` prints results as they complete (out of order). No progress bar, no ETA, no way to resume after interruption.
- **Impact:** Large sweeps (72+ configs) are opaque. If the process dies at config 50, there's no way to resume from 51.
- **Fix:** The cache already provides resume capability (cached configs are skipped). Add a progress bar (tqdm) and ETA estimate.

#### E1.11. No reproducibility guarantee
- **What:** Results depend on BookSim binary version, Python version, random seeds, and OS scheduling. There's no mechanism to reproduce a result exactly.
- **Impact:** Paper reviewers can't reproduce our numbers. The `run_manifest.py` exists but isn't wired into the evaluator.
- **Fix:** Wire `run_manifest.py` into `run_booksim()` — auto-create a manifest with (binary hash, config, seed, timestamp) for every simulation.

#### E1.12. Memory coupling model is first-order only
- **What:** `bank_contention()` uses M/D/1 queueing (Poisson arrivals, deterministic service). Real memory traffic is bursty and correlated, not Poisson.
- **Impact:** The memory coupling model is approximate. The F6 claim (memory halves mesh/torus saturation headroom) may be over/under-estimated.
- **Fix:** Document the M/D/1 assumption explicitly. Compare against SCALE-Sim validated cycle counts for calibration.

---

### 2. SEARCH (search.py, search_bo.py) — 6 issues

#### S2.1. Grid search doesn't exploit structure
- **What:** Grid search evaluates all points independently. But the design space has structure: topology is the dominant factor, then vcs, then buf. A smarter search could skip dominated configs early.
- **Fix:** Add early termination: if a config is saturated at IR=0.08, don't evaluate it at IR=0.16. Use multi-fidelity (successive halving) to allocate more budget to promising configs.

#### S2.2. BO objective is not smooth
- **What:** Optuna TPE assumes a smooth objective. But `objective_score()` has a discontinuity at the saturation boundary (1e9 + deficit). The TPE sampler may waste trials exploring the discontinuity.
- **Fix:** Use a smoother penalty (e.g., exponential ramp) instead of the hard 1e9 jump. Or use a categorical "saturated" flag and optimize only the feasible subset.

#### S2.3. No warm-start for BO
- **What:** Each BO run starts from scratch (random initial points). Previous runs' results are in the cache but not used to warm-start the TPE prior.
- **Fix:** Load previous results as initial observations for the TPE sampler. This reduces the number of trials needed to find the optimum.

#### S2.4. Design space is too coarse
- **What:** The current grid is: topology(3) × vcs(3) × buf(2) × routing(3) = 54 points. This is too coarse to find the true optimum. Buffer depth 4 and 32 are missing. Routing options like `min_adapt` vs `planar_adapt` may have sub-options.
- **Fix:** Add more buffer depth options (4, 12, 32). Consider adaptive mesh refinement around the best config.

#### S2.5. No sensitivity analysis
- **What:** The DSE doesn't tell you which axis matters most. Is topology or vcs more important? By how much?
- **Fix:** After the sweep, compute per-axis contribution to latency variance (ANOVA or SHAP values). This is valuable for the paper ("topology contributes X% of latency variance, vcs contributes Y%").

#### S2.6. No Pareto frontier visualization
- **What:** The DSE produces a ranked list but no visual Pareto frontier (latency vs cost, latency vs energy). Paper figures need these.
- **Fix:** Generate a Pareto plot (latency vs vcs×buf cost) with feasible/saturated/failed regions colored. Output as PDF for the paper.

---

### 3. RECOMMEND (recommend.py) — 5 issues

#### R3.1. No end-to-end validation of recommended config
- **What:** `recommend.py` ranks configs by BookSim latency but doesn't validate the top config through the full pipeline (RTL generation → Verilator build → certification). The recommended config might have a BookSim-latency-optimal topology that's deadlocking in RTL.
- **Fix:** Add a `--validate` flag that runs the full pipeline on the top-N configs: gen_rtl → make → certify.sh. Report pass/fail alongside latency.

#### R3.2. No comparison vs baseline
- **What:** The recommendation says "best config is X with latency Y" but doesn't say "compared to a standard 8×8 mesh with 4 VCs, this is Z% better."
- **Fix:** Always include a baseline config (mesh, vcs=4, buf=8) in the output. Show the relative improvement.

#### R3.3. Energy score is dead code
- **What:** `objective_score()` includes `result.energy_pj * 1e-6` in the score, but `energy_pj` is always None. The energy term is dead code.
- **Fix:** Either wire in an energy model (T034) or remove the dead code path to avoid confusion.

#### R3.4. No explanation of recommendation
- **What:** The tool prints a ranked table but doesn't explain WHY config A is better than config B. "What makes this topology special?"
- **Fix:** Add a brief explanation: "Config A beats baseline because: (1) 2 extra shortcut links reduce avg hops from 6.5 to 4.9, (2) 8 VCs prevent head-of-line blocking at IR=0.08, (3) min_adapt routing handles bursty traffic better than DOR."

#### R3.5. No uncertainty quantification
- **What:** The recommendation is a point estimate (best config). There's no confidence interval or robustness analysis. "Is config A really better than config B, or is this within noise?"
- **Fix:** Run the top-N configs with multiple seeds. Report the probability that config A beats config B (e.g., "A beats B in 4/5 seeds, p=0.06").

---

### 4. CALIBRATION — 8 issues

#### C4.1. Only 1 config has RTL calibration data
- **What:** The calibration table (`results/dse_calibration/`) has ONE data point: mesh vcs=8 buf=8 at IR=0.08. The S5 task calls for ≥5 configs.
- **Impact:** We can't claim rank agreement with n=1. The Spearman correlation needs ≥3 paired observations.
- **Fix:** Run RTL builds for 4 more configs (mesh vcs=2, vcs=4, vcs=8 buf=16, torus vcs=4). Each build takes ~25 min with -j2.

#### C4.2. Calibration uses uniform traffic, not real traces
- **What:** `calibration_booksim_rtl.py` uses uniform random traffic. Real workload traffic (qwen3) has spatial and temporal structure that may affect the BookSim-RTL gap differently.
- **Fix:** Run calibration on a qwen3 trace slice (10K cycles). Compare BookSim trace_input vs RTL trace_player on the same slice.

#### C4.3. BookSim config mismatch with RTL
- **What:** The calibration BookSim uses `num_vcs=4, vc_buf_size=8, routing=min_adapt`. The RTL uses `NUM_VCS=2, BUF_DEPTH=8, DOR+escape-tree`. These are different configs — the comparison is apples-to-oranges.
- **Fix:** Either (a) run BookSim with the same config as RTL (vcs=2, DOR), or (b) document that the comparison is "BookSim with adaptive routing vs RTL with escape-tree routing" and explain why these are comparable.

#### C4.4. No FlooNoC calibration column
- **What:** The architecture decision doc positions FlooNoC as the L4 reference. But there's no FlooNoC latency data in the calibration table.
- **Fix:** Run FlooNoC sim on the same configs (E5/S6 in PRODUCTION-TASKLIST).

#### C4.5. No cross-topology calibration
- **What:** All calibration is on mesh. No calibration for torus or fat-tree.
- **Fix:** Add at least 2 torus configs to the calibration matrix.

#### C4.6. RTL build uses wrong flags
- **What:** `calibration_booksim_rtl.py` uses `make -j4` which OOM-kills on this box. The PRODUCTION-TASKLIST explicitly says `-j2 --threads 2`.
- **Fix:** Change to `make -j2 --threads 2`.

#### C4.7. No calibration report format
- **What:** Results are saved as JSON but there's no formatted report (table + plot) suitable for the paper.
- **Fix:** Generate a LaTeX-ready table and a scatter plot (BookSim latency vs RTL latency, with y=x line).

#### C4.8. IR derivation (M2) is not wired into calibration sweep
- **What:** `ir_derivation.py` derives that the real IR for Qwen3 MoE is ~0.02, but the calibration sweep uses IR=0.04-0.32. The derived IR is 4-19x below the sweep range.
- **Fix:** Add IR=0.02 to the calibration sweep. Document that the DSE oversamples high-IR regimes.

---

### 5. RTL GENERATION (gen_rtl.py) — 7 issues

#### G5.1. TB is a 300-line C++ f-string
- **What:** The testbench is emitted as a Python f-string with 40+ double-brace escapes. Any C++ change requires understanding Python string interpolation.
- **Fix:** Extract TB to a separate `.cpp` template file with `{PLACEHOLDER}` markers. gen_rtl.py reads the template and substitutes values. This separates C++ from Python.

#### G5.2. No TB-level watchdog
- **What:** The TB runs for `INJ_CYCLES + DRAIN_CYCLES + SWEEP_CYCLES` cycles. If the RTL hangs (infinite loop), the TB hangs too. The cert harness has `timeout 180` but the TB itself has no internal watchdog.
- **Fix:** Add a TB-level watchdog: if no ejection for 100K consecutive cycles, print diagnostic and exit. This catches hangs faster than the external timeout.

#### G5.3. No VCD dump by default
- **What:** VCD tracing is only enabled when `VCD` env var is set. For debugging failures, VCD is essential but you have to know to set it.
- **Fix:** When the TB detects a failure (wrong_dst > 0 or stuck > 0), automatically dump the last 10K cycles to VCD. This makes debugging failures automatic.

#### G5.4. Conservation check is flit-count based, not credit-based
- **What:** P3 conservation checks `completed_pkts == free_inj + esc_inj` (packet count). It doesn't check credit conservation (credits returned = credits consumed).
- **Fix:** Add credit tracking: increment on credit return, decrement on credit consume. At the end, assert credits == BUF_DEPTH × NUM_PORTS.

#### G5.5. No per-router diagnostic output
- **What:** When packets are stuck, the TB prints the first 20 stuck packets but doesn't say WHICH router they're stuck at or WHY (which output port is blocked, which queue is full).
- **Fix:** Add per-router final-state dump: queue occupancy per port, credit state per output, lock state. This is essential for debugging 64n failures.

#### G5.6. Pattern generator doesn't support "mixed" traffic
- **What:** The cert harness tests 6 patterns (uniform, hotspot, transpose, tornado, neighbor, bitrev) but real workloads are a mix of all of these. There's no "mixed" pattern.
- **Fix:** Add a `mixed` pattern that combines uniform (50%) + hotspot (20%) + neighbor (20%) + transpose (10%). This better approximates real traffic.

#### G5.7. No topology-aware pattern generation
- **What:** All patterns are defined in terms of node IDs (0..N-1). For non-mesh topologies (fat-tree, irregular), the patterns may not make sense (e.g., "tornado" on a fat-tree).
- **Fix:** For non-grid topologies, fall back to uniform random. Document that synthetic patterns are mesh-specific.

---

### 6. CERTIFICATION (certify.sh) — 4 issues

#### C6.1. No P5 conservation check
- **What:** The harness checks P1 (liveness), P2 (routing), P4 (pair-order). It doesn't check P3 (conservation) even though the TB outputs it.
- **Fix:** Add `conservation` grep to the harness.

#### C6.2. No credit conservation check
- **What:** The harness doesn't verify that credits balance (returned == consumed). A credit leak passes all current checks.
- **Fix:** Add credit balance assertion to the TB and wire into harness.

#### C6.3. Timeout is fixed at 180s
- **What:** All runs get 180s regardless of topology size or IR. 64-node runs may need 600s+.
- **Fix:** Scale timeout: `timeout=$((180 + n_nodes * 5))` or make it configurable.

#### C6.4. No summary statistics
- **What:** The harness prints PASS/FAIL per run but doesn't aggregate statistics (total injected, total ejected, mean conservation ratio, etc.).
- **Fix:** Add a summary line at the end: total pkts injected, total ejected, mean conservation ratio, total wrong_dst, total stuck.

---

### 7. DSE TOOL INTEGRATION — 6 issues

#### I7.1. No CLI entrypoint
- **What:** There's no single command to run the full DSE: `dse --spec moe_serving.json --output /tmp/result`. Users must run spec_translate, then recommend, then gen_rtl, then certify separately.
- **Fix:** Create a `dse` CLI that chains: spec → translate → recommend → gen_rtl → certify. Output a single report.

#### I7.2. No incremental update
- **What:** If the customer changes one requirement (e.g., "add 16 more endpoints"), the entire DSE must re-run from scratch.
- **Fix:** Cache intermediate results (synthesized topology, BookSim evaluations). Only re-evaluate configs affected by the change.

#### I7.3. No rollback
- **What:** If the DSE recommends a config and the customer says "no, try something cheaper," there's no way to explore the Pareto frontier interactively.
- **Fix:** Add `--pareto` mode that shows the full Pareto frontier (latency vs cost) and lets the customer pick a point.

#### I7.4. No validation report
- **What:** The DSE produces a recommended config but no formal report proving it meets the requirements. The PRD calls for a "verification certificate."
- **Fix:** Generate a report: "Config X meets requirements: latency 26.86cyc < 40ns budget ✓, throughput 0.08 > 0.05 requirement ✓, deadlock-free (CDG acyclic) ✓."

#### I7.5. No versioning
- **What:** There's no way to compare results across DSE runs. "Was the config from last week better or worse than today's?"
- **Fix:** Version every DSE run with a timestamp + git SHA. Store results in a structured format (JSON with metadata).

#### I7.6. No sensitivity report
- **What:** The DSE doesn't tell you which requirements are the binding constraints. "Is the latency budget or the throughput requirement limiting the design?"
- **Fix:** After the sweep, identify the binding constraint for the top config. "The latency budget of 40ns is not binding (best config achieves 26.86ns). The throughput requirement of 0.05 flits/node/cyc is the binding constraint."

---

## PAPER READINESS ASSESSMENT

### What we have (strong)

1. **End-to-end pipeline:** Requirements → topology → routing → certification → RTL
2. **Real workload traffic:** Qwen3-30B-A3B serving trace (668K packets, 64 nodes)
3. **Formal guarantees:** CDG cycle detection → deadlock-free routing certificate
4. **Cycle-accurate proof:** BookSim2 trace_input + RTL trace_player
5. **Custom topology beats baselines:** -23.4% vs mesh, -13.2% vs torus on synthetic traffic
6. **Certification harness:** 144/144 on mesh_4x4 (old template)
7. **FlooNoC cross-reference:** AXI4 wide-channel fabric for comparison

### What we need (gaps)

1. **Clear thesis statement** — "What is the paper claiming?"
2. **Rank agreement** — BookSim ranking predicts RTL ranking (Spearman ρ > 0.8)
3. **Multi-seed results** — Confidence intervals on all numbers
4. **Ablation studies** — Show each component (synthesis, routing, VC allocation) contributes
5. **Comparison vs prior art** — vs BookSim auto-topo, vs手工 design, vs MONET
6. **PPA estimates** — Area, power, timing (even first-order)
7. **64-node RTL proof** — The v2 template must pass 64n
8. **Real workload DSE** — Run the full frontdoor on qwen3 trace, not just synthetic
9. **Per-class latency breakdown** — Show MoE dispatch vs allreduce vs KV cache
10. **Pareto frontier plot** — Latency vs cost, with feasible/saturated regions

### Estimated effort to paper-ready

| Item | Effort | Dependencies |
|------|--------|-------------|
| Rank agreement (5 RTL builds) | 1 week | Build slot |
| Multi-seed (3 seeds × 5 configs) | 3 days | Rank agreement |
| Ablation study | 3 days | Multi-seed |
| Prior art comparison | 1 week | BookSim + RTL |
| PPA first-order | 1 week | Yosys/Accelergy |
| 64-node v2 template | 1 week | v2 build + test |
| Real workload DSE | 3 days | Frontdoor on qwen3 |
| Per-class breakdown | 2 days | BookSim flits.txt |
| Pareto plot | 1 day | DSE sweep results |
| Paper writing | 2-3 weeks | All above |
| **Total** | **~6-8 weeks** | |

### Recommended paper target

**MLSys 2027** (deadline ~Sept 2026) — closest realistic target.  
**ISCA 2027** (deadline ~Feb 2027) — more time, higher prestige.  
**MICRO 2027** (deadline ~May 2027) — most time, good fit for microarch paper.

---

## TOP 10 IMPROVEMENTS (ranked by impact)

| Rank | Improvement | Impact | Effort |
|------|-------------|--------|--------|
| 1 | **Run v2 template at 64n** (T006) | Unblocks everything | 1 day |
| 2 | **Rank agreement** (T015) | Core paper claim | 1 week |
| 3 | **Multi-seed results** | Statistical rigor | 3 days |
| 4 | **Wire phase evaluation into recommend** | Real workload accuracy | 2 days |
| 5 | **Per-class latency breakdown** | Paper figure | 2 days |
| 6 | **Ablation study** | Paper contribution | 3 days |
| 7 | **Pareto frontier plot** | Paper figure | 1 day |
| 8 | **TB watchdog + auto-VCD** | Debugging speed | 1 day |
| 9 | **Guardrail hash** | Traceability | 1 day |
| 10 | **Single CLI entrypoint** | Product usability | 3 days |
