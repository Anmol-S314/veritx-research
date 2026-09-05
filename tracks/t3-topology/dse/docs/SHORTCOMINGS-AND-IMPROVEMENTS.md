# DSE Pipeline — Shortcomings & Improvement Opportunities

**Written:** 2026-08-22 by Buffy (code review pass)
**Scope:** Everything from the DSE search engine through the RTL proof leg.

---

## 1. RTL Verification Shortcomings

### 1a. BookSim exit 255 is silently accepted
**Severity: Medium**
`run_sim()` in `noc_frontend.py` extracts latency/hops from BookSim stdout regardless of exit code. BookSim exits 255 (latency threshold / possible deadlock) and the pipeline treats it as success. The `report.json` records `booksim_exit: 255` but `gate_pass: true`. A real deadlock would produce garbage stats that look plausible. **Fix:** check `r.returncode` before extracting stats; if non-zero, flag the result as `suspect` rather than `ok`.

### 1b. RTL sim speed: 0.5 cyc/sec with debug output
**Severity: High (usability)**
The RTL binary has ~57 `$display` statements in `router.sv` alone. Even gated by R1_MODE, several fire every cycle (R26/R36 at `(X==2,Y==6 || X==3,Y==6)`, NIC50 at `(X==2,Y==6)`). A 28,865-cycle sim takes ~16 hours wall time. The `timeout=900` in `run_sim` kills it before completion. **Fix:** gate ALL per-cycle debug behind a separate `DBG_VERBOSE` define (off by default), or add a `+debug` plusarg that enables them at runtime.

### 1c. No stale-binary detection
**Severity: Medium**
`_find_cached_binary()` matches on `(vcs, vc_buf, x_dim, y_dim)` but ignores RTL source freshness. A binary built from older RTL (e.g., pre-VC_BUF parameterization) gets reused, producing incorrect results. The code checks `bin_.stat().st_mtime > newest` AFTER the cache copy, but if the source dir binary is stale AND the cached binary is also stale, both fail the check and trigger a rebuild — which may not have enough RAM. **Fix:** store RTL source hash (sha1 of all .sv files) in the .meta sidecar and validate on cache hit.

### 1d. VC_BUF=4/16 not validated against RTL
**Severity: Low**
`noc_frontend.py` validates `vc_buf in (4, 8, 16)` but the RTL parameterization was only smoke-tested at 4/8/16. The `PT_W = $clog2(VC_BUF) + 1` calculation works for powers of 2 but there's no assertion that VC_BUF IS a power of 2. Non-power-of-2 values would silently produce wrong-width ring pointers.

### 1e. No per-flit timing in the RTL proof
**Severity: Medium (research quality)**
The GATE-R1 diff matches by `(src, dst, cl)` stream order, comparing retire timestamps. This is a TIMING diff, not a correctness diff. If the RTL delivers the right flits but at wrong times, it passes as long as mean Δ ≤ 5. For a paper claiming cycle-accurate proof, the gate threshold (exact ≥ 60%, mean ≤ 5) is lenient. The proof_1 result is 79.4% exact with max Δ = 7 — acceptable but not tight.

### 1f. No stress-test coverage
**Severity: Medium**
There's a single proof spec (`proof_1_topology-mesh_vcs-4_vc_buf-8`). No corner-case testing: high injection rate (IR 0.32+), vc_buf=4 (tight buffers), or vc8 (more VCs = more contention). The 15-cell gate from t3-rtl-noc validates single-die delivery but not the DSE trace-driven flow.

---

## 2. DSE Search Engine Shortcomings

### 2a. Grid search is brute-force O(n^k)
**Severity: Low (acceptable for 64-point grid)**
The grid enumerates the full Cartesian product. With microarch axes: 3 topologies × 3 vcs × 2 vc_buf × 2 routing × 3 arbiter = 108 points. Each runs BookSim (~1s). At 4 workers: ~27s. Acceptable now, but won't scale to 5+ axes or larger meshes. The BO path exists but needs more trials to outperform grid on small spaces.

### 2b. BO search has no warm-start
**Severity: Low**
`bo_search()` creates a fresh Optuna study each call. Previous results in the grid cache are not fed as initial suggestions. On repeat runs, BO re-explores known-good regions. **Fix:** seed the study with cached results as `study.enqueue_trial()`.

### 2c. Injection rate is not a DSE axis
**Severity: Medium (research gap)**
The DSE sweeps topology × vcs × vc_buf × routing × arbiter but treats injection rate as a fixed parameter (`--ir 0.08`). The saturation frontier (`--sweep`) runs at multiple IRs separately but doesn't co-optimize IR with topology. A real DSE should find the MAXIMUM sustainable IR per config, not just check one IR.

### 2d. Cost model is naive
**Severity: Low**
`config_cost = vcs × vc_buf × (banks/4)` is a rough silicon proxy. It doesn't account for:
- Topology cost (fattree has O(N log N) switches vs mesh O(N))
- Routing table storage (table-mode needs O(N²) storage)
- Wire count (fattree needs O(N log N) wires vs mesh O(N))
A proper cost model would use area estimates from synthesized RTL or analytical models.

### 2e. No multi-objective optimization
**Severity: Medium (research gap)**
The F2 objective is latency-first with throughput constraint. Energy is computed but only shown in output, not used for ranking. The `bottleneck_score` for per-phase evaluation exists but isn't wired into the main recommendation path. A Pareto-optimal front (latency vs energy vs cost) would be more informative for a paper.

---

## 3. Traffic Model Shortcomings

### 3a. Matrix derivation loses temporal structure
**Severity: High (fidelity gap)**
`_trace_to_matrix()` aggregates the entire trace into a single probability matrix. This collapses burst timing, phase sequencing, and per-packet injection patterns into a static distribution. BookSim then runs with uniform random injection at the matrix rate. The DSE ranking is based on this static approximation; the RTL proof replays the actual trace. The two can diverge significantly for bursty traffic.

### 3b. on_off injection is a crude burst model
**Severity: Medium**
The burst envelope (peak vs mean from 100-cycle window) is fed to BookSim's `on_off` pattern. This is a binary on/off approximation of what is actually a complex, correlated injection sequence. At high burstiness (10x+), the on_off model significantly underestimates queue buildup.

### 3c. llm_traffic patterns are synthetic, not real
**Severity: Medium (honesty)**
The `moe_dispatch`/`tp_allreduce`/`kv_cache` patterns are parameterized synthetic traffic, not real LLM serving traces. The handoff mentions Chakra ETs from ASTRA-sim, but those aren't wired into the DSE yet (seed 4f65). The DSE recommends configs based on synthetic traffic that may not match real serving behavior.

### 3d. No memory hierarchy modeling in the ranking path
**Severity: Medium**
`bank_contention()` exists in `evaluator.py` but is only used with `--mem`. The default DSE path ignores shared-L2 bank conflicts, which the F6 analysis showed HALVE saturation headroom. Configs recommended without memory modeling may saturate in practice.

---

## 4. Pipeline Architecture Shortcomings

### 4a. DSE and RTL proof use different BookSim invocations
**Severity: High (coherence risk)**
The DSE evaluator runs BookSim with `sample_period`/`max_samples` stats collection. The RTL proof runs BookSim with `trace_out`/`flit_dump` for per-packet trace generation. These are DIFFERENT BookSim modes with potentially different internal states. The matrix is the same, but the injection pattern differs (Bernoulli vs trace-derived on_off). This is the "fidelity gap" noted in the handoff.

### 4b. noc_frontend writes to `/var/tmp/opencode/nocfe` (hardcoded)
**Severity: Low (portability)**
The outdir is hardcoded. Multiple agents writing to the same directory causes cache collisions. The `_find_cached_binary` glob-searches ALL outdirs, which means a binary built by one agent for one config gets picked up by another agent for a different config (if params match). This is by design but fragile.

### 4c. No reproducibility guarantees
**Severity: Medium (research quality)**
The pipeline has no seed-reproducibility check. BookSim's RNG seed is in the config, but the RTL sim uses `$urandom` for some internal state. Two runs of the same config may produce slightly different timing. The calibration table doesn't report run-to-run variance.

### 4d. recommend.py subprocess timeout is fixed at 900s
**Severity: Medium**
The proof subprocess has a hard 900s timeout. For vc8 builds (GVCS=16), the Verilator build alone takes >900s on a constrained box. The timeout should scale with VCS or be configurable. Currently, vc8 proof is impossible on this box regardless of RAM.

### 4e. No structured output / machine-readable report
**Severity: Low**
The recommendation output is human-readable text. The `report.json` exists for proof results but there's no overall DSE run report (all configs ranked, with timing/proof status). A JSON summary would enable automated tracking and comparison across runs.

---

## 5. Research Methodology Shortcomings

### 5a. Single workload, single mesh size
**Severity: High (generalizability)**
All DSE runs use `qwen_moe_64d.mat` (64-node MoE dispatch). No validation on:
- Different model architectures (dense transformer, different MoE topologies)
- Different mesh sizes (4×4, 16×16)
- Different injection rates beyond the 0.08 default
The paper's claims would be stronger with multi-workload validation.

### 5b. No baselines comparison
**Severity: High (research rigor)**
The DSE recommends configs but doesn't compare against established baselines:
- AlphaFold/TPU-style 2D mesh (the default)
- Fat-tree (the DSE finds it better but doesn't quantify the gap)
- Ring/torus for collectives
- Hamiltonian or runaround topologies
A "Table 1" comparing our best config against published baselines on the same workload is missing.

### 5c. FlooNoC and gem5 anchors are unvalidated
**Severity: High (validation)**
The energy number (`hops × 64B × 0.15 pJ/B/hop`) is a pure calculation, not a measurement. The FlooNoC leg (§4 of HANDOFF) requires generating a fabric, driving the trace, and measuring latency. The gem5-Garnet leg (§5) is deferred. Without external validation, the DSE results are self-referential (BookSim ranking → RTL proof on the same BookSim-generated trace).

### 5d. No sensitivity analysis
**Severity: Medium**
The DSE doesn't report confidence intervals or sensitivity to parameters:
- What if the traffic matrix is wrong by 20%?
- What if the injection rate is misestimated?
- How does the recommendation change with mesh size?
Robustness to input assumptions is critical for a credible paper.

### 5e. The "F6 claim" (fattree wins with memory) lacks formal statement
**Severity: Medium**
The handoff mentions "F6: fattree wins all load regimes at 64 nodes" but this isn't a precise, testable thesis. A paper needs a specific, falsifiable claim with a clear experimental protocol. Currently the DSE tool finds configs; it doesn't formalize what question it's answering.

---

## 6. Quick Wins (high value, low effort)

| # | Fix | Impact | Effort |
|---|---|---|---|
| 1 | Gate RTL debug output behind `+verbose` plusarg | RTL sim 100x faster | 1hr |
| 2 | Check booksim exit code before accepting stats | Prevent false positives | 15min |
| 3 | Store RTL hash in .meta for stale-binary detection | Prevent wrong-binary reuse | 30min |
| 4 | Add `+vc_buf` validation (power-of-2 assertion) | Prevent silent width bugs | 15min |
| 5 | Wire `bottleneck_score` into recommend.py output | Per-phase visibility | 30min |
| 6 | Make proof timeout configurable (`--proof-timeout`) | Unblock vc8 on slow boxes | 15min |
| 7 | Add run-to-run variance check (run 2x, report std) | Reproducibility | 1hr |

---

## 7. Summary Assessment

**What works well:**
- The L1→L2→L3→L4 pipeline architecture is sound: Traffic In → DSE Search → Config Out → RTL Proof
- The F2 objective (latency-first + throughput constraint) is well-defined and implemented correctly
- The cache system (after the sha1 fix) works reliably
- The RTL proof gate (per-flit timing diff) is a genuine cycle-accurate validation
- The VC_BUF parameterization enables a real buffer-depth sweep

**What needs work before a paper:**
- The fidelity gap between DSE ranking (static matrix) and RTL proof (trace replay) must be acknowledged and quantified
- External validation (FlooNoC, gem5) is not just "nice to have" — without it, the results are self-referential
- The traffic model needs real LLM traces, not synthetic patterns
- Multi-workload, multi-size validation is needed for generalizability
- The RTL sim speed (0.5 cyc/sec) makes iteration painfully slow
- The proof gate threshold (60% exact, mean ≤ 5) is too lenient for a "cycle-accurate" claim

**What's honestly not done:**
- No comparison against published baselines
- No formal problem statement / testable thesis
- No sensitivity analysis
- No confidence intervals
- FlooNoC anchor is a calculation, not a measurement
- gem5-Garnet validation is deferred
- Real LLM serving traces not wired in
- Memory hierarchy not in the default ranking path
