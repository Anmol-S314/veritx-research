# Competitive Analysis: NoC DSE for AI Accelerators

*Generated 2026-08-21 — Literature survey + product analysis*

---

## 1. Landscape Map

The field splits into **four layers**, each with different tools:

| Layer | What it does | Our position |
|-------|-------------|-------------|
| **L1: Workload mapping** | "Given DNN model → schedule tiles on PE array" | Not our scope (MAESTRO, Timeloop, ZigZag) |
| **L2: Compute/memory DSE** | "Given workload → optimal PE count, SRAM size, dataflow" | **Weakest area** — need to integrate |
| **L3: NoC fabric DSE** | "Given traffic → optimal topology, VCs, buffers, routing" | **Our core strength** — nobody else does this well |
| **L4: RTL proof** | "Given config → cycle-accurate validation" | **Unique** — Verilator diff, no competitor has this |

---

## 2. Competitor Deep-Dive

### 2.1 MOSAIC (2026, arXiv) — Closest Competitor

**What it does:** Workload-driven analytical simulator + DSE for heterogeneous NPUs. Treats structural tile-level heterogeneity (different tile types) as the design variable.

**Key insights:**
- Uses roofline model for compute/memory bottleneck classification
- Explores tile-level heterogeneity (not just identical tiles)
- NoC is modeled as a black box (latency/bandwidth abstraction), not as fabric parameters
- Supports multi-workload evaluation

**What we can learn:**
- **Roofline integration**: Classify workloads as compute-bound vs memory-bound BEFORE fabric DSE. This tells you whether NoC sizing matters (memory-bound) or is irrelevant (compute-bound).
- **Multi-workload evaluation**: Test configs across dispatch, allgather, KV cache phases separately AND combined
- **Tile heterogeneity**: Their NPU has different tile types — our MoE dispatch has different expert types. Could model expert-to-expert vs expert-to-route traffic separately.

**What they can't do:**
- No fabric-level DSE (VCs, buffers, routing)
- No RTL validation
- No cycle-accurate proof

### 2.2 HT-NoC (2026, ACM TRETS) — NoC Architecture Paper

**What it does:** Dynamically reconfigurable NoC that adapts throughput to DNN layer type. Multi-dataflow support (different communication patterns for CONV vs FC vs PW layers).

**Key insights:**
- Adapts NoC configuration per DNN layer type
- 2.3x speedup for FC layers, 1.4x for CONV layers vs static mesh
- Minimal area/latency overhead from reconfiguration

**What we can learn:**
- **Per-layer NoC adaptation**: Our phase_sequencer already does this (dispatch → allgather → KV). HT-NoC validates that per-phase optimization matters.
- **Dataflow-aware routing**: They route differently for different layer types. We could route differently for different MoE phases.

**What they can't do:**
- Not a DSE tool — it's a NoC architecture
- No workload-driven recommendation
- No RTL proof

### 2.3 AgentDSE (2026, arXiv) — LLM-Agent DSE

**What it does:** Simulator-in-the-loop methodology driven by a general-purpose LLM coding agent. Domain-agnostic — works with any simulator (MAESTRO, Timeloop, gem5).

**Key insights:**
- LLM generates simulator code, runs it, reads results, iterates
- Beats DOSA (domain-specific optimizer) on some benchmarks
- Can discover non-obvious design optimizations

**What we can learn:**
- **LLM-in-the-loop**: Our recommend.py could use an LLM agent to suggest promising design points instead of grid/BO search
- **Simulator abstraction**: They wrap any simulator in a common interface. We could expose BookSim/RTL as a common API.
- **Cross-domain transfer**: They optimize across compute+memory+NoC. We should too.

**What they can't do:**
- No cycle-accurate RTL proof
- Relies on existing simulators (doesn't build new ones)
- Slow (LLM iteration is expensive)

### 2.4 Timeloop/Accelergy (MIT, 2014-2026) — The Standard

**What it does:** Analytical performance/energy model for DNN accelerators. Timeloop maps workload to architecture, Accelergy estimates energy/area.

**Key insights:**
- Roofline-based latency estimation
- Loop nest optimization for dataflow mapping
- Widely adopted (200+ papers cite it)
- Supports arbitrary memory hierarchies

**What we can learn:**
- **Roofline integration**: Use Timeloop's roofline to classify our workloads before fabric DSE
- **Memory hierarchy modeling**: Timeloop models SRAM/DRAM hierarchy well — we could use this for the memory axis (398b)
- **Energy estimation**: Accelergy's energy model is more sophisticated than our hops × 0.15 pJ/B/hop

**What they can't do:**
- No fabric-level DSE (topology, VCs, buffers)
- No RTL validation
- Analytical only — no cycle-accurate proof

### 2.5 ZigZag/DeFiNES (KU Leuven, 2023-2026) — Dataflow Exploration

**What it does:** Rapid DSE for dataflow accelerators. ZigZag does single-layer mapping, DeFiNES extends to multi-layer.

**Key insights:**
- Very fast (analytical, not simulation)
- Explores dataflow options (weight stationary, output stationary, etc.)
- SunPar extends to sparse accelerators
- FlexiGen (2026) generates RTL from explored configs

**What we can learn:**
- **Dataflow as DSE axis**: We could add dataflow type (WS/OS/IS) as a DSE axis alongside fabric params
- **RTL generation**: FlexiGen generates RTL from DSE results — we already do this (noc_frontend), but they do it for compute, not NoC

**What they can't do:**
- No NoC fabric DSE
- No cycle-accurate RTL proof

### 2.6 MLDSE (2025, arXiv) — Multi-Level DSE

**What it does:** Infrastructure for domain-specific DSE of multi-level hardware. Supports user-defined multi-level design spaces.

**Key insights:**
- Roofline model with mapping captures non-linear interactions
- Extends rules for general computation beyond DNN
- Supports compute + memory + NoC as coupled axes

**What we can learn:**
- **Multi-level coupling**: They model how compute, memory, and NoC interact. Our current DSE treats them separately (fabric DSE in one pass, memory in another).
- **Coupled optimization**: jointly optimize compute+memory+NoC instead of sequentially

**What they can't do:**
- No RTL proof
- Analytical only

### 2.7 Voyager (2025, arXiv) — End-to-End Accelerator Generation

**What it does:** HLS-based framework for rapid DSE and generation of DNN accelerators. Generates RTL from explored configs.

**Key insights:**
- End-to-end: workload → DSE → RTL generation
- Uses existing compilers for scheduling
- Generates matched baselines for fair comparison

**What we can learn:**
- **End-to-end flow**: They go workload → RTL in one pipeline. We should too (trace → config → RTL proof in one command).
- **Baseline generation**: Generate matched baselines for comparison (important for paper)

**What they can't do:**
- No NoC fabric DSE
- No cycle-accurate proof (HLS-generated, not hand-verified)

### 2.8 LLMulator (2025, DAC) — LLM as Cost Model

**What it does:** Uses pre-trained LLMs for generalized, interpretable performance modeling of dataflow accelerators.

**Key insights:**
- LLM can predict latency/energy from architecture description
- Input-adaptive control flow
- Interpretable (explains why a config is good/bad)

**What we can learn:**
- **LLM cost model**: Instead of running BookSim for every config, use an LLM to predict latency/energy. Only run BookSim for top candidates.
- **Interpretability**: LLM can explain why fattree beats mesh for MoE traffic (hops, contention pattern)

**What they can't do:**
- No cycle-accurate proof
- LLM predictions are approximate

### 2.9 OneDSE (2025, arXiv) — Unified CPU DSE

**What it does:** Unified microprocessor metric prediction + DSE framework. Uses LLM-based workload-aware CPU estimation (TrACE).

**Key insights:**
- Dual-objective: metric prediction + exploration
- Multi-agent DSE (multiple LLM agents exploring different axes)
- Works at CPU subsystem level

**What we can learn:**
- **Multi-agent DSE**: Multiple agents exploring different design axes simultaneously
- **Subsystem-level abstraction**: Model NoC as a subsystem with its own DSE, then compose with compute/memory DSE

**What they can't do:**
- CPU-focused, not AI accelerator
- No RTL proof

### 2.10 Arteris FlexGen/FlexNoC (Commercial)

**What it does:** Commercial NoC IP configurator. Generate RTL from configuration.

**Key insights:**
- "10x productivity boost, 30% wirelength reduction"
- Physically aware (timing closure)
- Protocol agnostic (AXI, AHB, etc.)
- Mesh topology editor with XL options

**What we can learn:**
- **Physical awareness**: They consider wire length and timing closure. We could add wire delay as a DSE axis.
- **Protocol support**: They support multiple protocols. We could support AXI/ACE-Lite for real SoC integration.

**What they can't do:**
- No workload-driven optimization
- No cycle-accurate proof
- You pick the config, they generate — no recommendation

---

## 3. Gap Analysis: What We're Missing

### 3.1 Compute/Memory DSE (Critical Gap)

**Current state:** Our DSE only optimizes NoC fabric (topology, VCs, buffers, routing). We don't consider:
- PE count and array size
- SRAM/DRAM hierarchy
- Dataflow type (weight stationary, output stationary, etc.)
- Compute precision (INT8, BF16, FP32)

**Why this matters:** For MoE models, the NoC is only useful if the compute and memory are also well-sized. A perfect fabric with too few PEs is still slow.

**What competitors do:**
- MOSAIC: Roofline-based compute/memory classification
- Timeloop/Accelergy: Full compute+memory+dataflow DSE
- ZigZag: Dataflow mapping optimization
- MLDSE: Multi-level coupled DSE

**Recommended fix:**
1. Add roofline classifier to classify workload as compute-bound vs memory-bound
2. If memory-bound → NoC fabric DSE matters (our sweet spot)
3. If compute-bound → PE count matters more (need Timeloop/ZigZag integration)
4. If balanced → coupled optimization (MLDSE approach)

### 3.2 Energy Model (Weak)

**Current state:** `energy ≈ hops × 64B × 0.15 pJ/B/hop` — single number, no breakdown.

**What competitors do:**
- Accelergy: Per-component energy (router, link, SRAM, DRAM, MAC)
- HT-NoC: Dynamic energy with reconfiguration overhead
- MOSAIC: Roofline-based energy (compute + memory + NoC)

**Recommended fix:**
1. Break down energy into router energy + link energy + memory energy
2. Use Accelergy-style per-component modeling
3. Add dynamic vs static energy separation

### 3.3 Multi-Workload Evaluation (Missing)

**Current state:** We evaluate one trace at a time. Real workloads have multiple phases (dispatch → allgather → reducescatter → KV cache).

**What competitors do:**
- MOSAIC: Multi-workload portfolio evaluation
- HT-NoC: Per-layer NoC adaptation
- AgentDSE: Cross-workload optimization

**Recommended fix:**
1. Our phase_sequencer already handles this — but the DSE should optimize for the WORST phase, not the average
2. Add per-phase metrics to the recommendation report
3. Weight phases by their duration (dispatch dominates)

### 3.4 Surrogate/Accelerated Search (Missing)

**Current state:** Grid/BO search runs BookSim for every config. Slow for large design spaces.

**What competitors do:**
- AgentDSE: LLM-guided search
- LLMulator: LLM as cost model
- OneDSE: Multi-agent search
- MLDSE: Analytical surrogate models

**Recommended fix:**
1. Train surrogate model (MLP) on BookSim data → predict latency without running sim
2. Use BO with surrogate (already have 1239 planned)
3. Add LLM cost model as alternative (LLMulator approach)

### 3.5 RTL Validation Confidence (Unknown)

**Current state:** Our GATE-R1 pass criteria is ≥60% exact timing match, mean Δ ≤5 cycles. Is this good enough?

**What competitors do:**
- No competitor has RTL proof at all
- Arteris uses physical simulation (synopsys DC)
- Academic tools use analytical models only

**Recommended fix:**
1. Validate our pass criteria against known-good configs
2. Document what "77% exact" means for design confidence
3. Add statistical analysis (confidence intervals, p-values)

---

## 4. Methodology Improvements (Prioritized)

### P0: Roofline Workload Classifier (1-2 days)

Add a roofline classifier that reads the traffic trace and classifies:
- **Compute-bound**: MAC operations dominate, NoC is idle
- **Memory-bound**: Memory accesses dominate, NoC is bottleneck
- **NoC-bound**: Communication dominates, fabric sizing matters

This tells the DSE which axes to optimize. If NoC-bound, our fabric DSE is the right tool. If compute-bound, we need Timeloop integration.

**Implementation:**
- Parse trace to count compute ops vs memory ops vs NoC ops
- Compare against roofline ridge point
- Classify and route to appropriate DSE

### P1: Coupled Compute-Memory-NoC DSE (1 week)

Instead of optimizing fabric separately, optimize compute+memory+NoC jointly:
- Add PE count, SRAM size, dataflow type as DSE axes
- Use Timeloop for compute/memory, BookSim for NoC
- Joint objective: minimize latency subject to energy/area constraints

**Implementation:**
- Extend space.py with compute/memory axes
- Add Timeloop wrapper for compute estimation
- Combine BookSim + Timeloop results in objective.py

### P2: Per-Phase Metrics (2-3 days)

Add per-phase breakdown to recommendation report:
- Dispatch latency, allgather latency, KV cache latency
- Per-phase energy, per-phase throughput
- Worst-phase identification
- Phase-weighted composite score

**Implementation:**
- Extend evaluator.py to track per-phase metrics
- Add phase boundaries to trace parsing
- Update recommend.py to report per-phase results

### P3: Surrogate Model (3-5 days)

Train MLP surrogate on BookSim data to predict latency without running sim:
- Use existing BookSim cache as training data
- Train MLP to predict (topology, VCs, buffers, routing, traffic) → (latency, hops, throughput)
- Use surrogate for initial screening, BookSim for top candidates

**Implementation:**
- Extract training data from evaluator_cache.json
- Train MLP in surrogate.py
- Wire into recommend.py as fast path

### P4: Energy Model Upgrade (2-3 days)

Replace single-number energy with per-component breakdown:
- Router energy: per-flit, per-hop
- Link energy: per-flit, per-hop
- Memory energy: per-access, per-bank
- Total = Σ(router) + Σ(link) + Σ(memory)

**Implementation:**
- Add energy constants to noc_pkg.sv or config
- Compute per-component in evaluator.py
- Update recommend.py energy reporting

---

## 5. Paper Positioning

### Our Unique Contribution

**No other tool combines:**
1. Workload-driven NoC fabric DSE (topology, VCs, buffers, routing)
2. Cycle-accurate RTL proof via Verilator diff
3. Unified trace format driving both simulation and RTL replay
4. Memory-aware co-design (joint fabric+memory)

### Comparison Table (for paper)

| Tool | Compute DSE | Memory DSE | NoC Fabric DSE | RTL Proof | Workload-Driven |
|------|:-----------:|:----------:|:--------------:|:---------:|:---------------:|
| Timeloop/Accelergy | ✅ | ✅ | ❌ | ❌ | ✅ |
| MOSAIC | ✅ | ✅ | ❌ (black box) | ❌ | ✅ |
| ZigZag/DeFiNES | ✅ | ❌ | ❌ | ❌ | ✅ |
| MLDSE | ✅ | ✅ | ⚠️ (analytical) | ❌ | ✅ |
| Voyager | ✅ | ❌ | ❌ | ⚠️ (HLS) | ✅ |
| AgentDSE | ✅ | ✅ | ❌ | ❌ | ✅ |
| HT-NoC | ❌ | ❌ | ✅ (architecture) | ❌ | ⚠️ (per-layer) |
| Arteris FlexGen | ❌ | ❌ | ✅ (configurator) | ❌ | ❌ |
| **Ours** | ❌ (P1) | ⚠️ (398b) | **✅** | **✅** | **✅** |

### Key Differentiator

> "We are the first tool to provide workload-driven NoC fabric DSE with cycle-accurate RTL validation. Existing tools either optimize compute/memory (Timeloop, MOSAIC) or configure NoC IP (Arteris), but none jointly optimize fabric parameters and prove correctness via RTL diff."

---

## 6. Action Items

| Priority | Item | Effort | Impact |
|----------|------|--------|--------|
| P0 | Roofline workload classifier | 1-2 days | Routes DSE to right axes |
| P1 | Coupled compute-memory-NoC DSE | 1 week | Fills critical gap |
| P2 | Per-phase metrics | 2-3 days | Better paper results |
| P3 | Surrogate model | 3-5 days | 10x faster search |
| P4 | Energy model upgrade | 2-3 days | Better paper results |
| P5 | Validate GATE-R1 pass criteria | 1 day | Confidence in RTL proof |

---

*Next steps: Implement P0 (roofline classifier) to enable coupled DSE, then P1 (joint optimization) to close the compute/memory gap.*
