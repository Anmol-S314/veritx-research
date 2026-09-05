# VeritX — Long-Term Vision & Roadmap

> Last updated: 2026-08-28
> One-liner: **End-to-end NoC DSE harness that takes a real LLM workload trace and produces a certified, Pareto-optimal topology with cycle-accurate proof.**

---

## Where We Are (Current State)

### What works today
- **CLI** (`veritx`): trace → model → BO → BookSim → cert — all wired, tested
- **Traffic sources**: Qwen3-30B MoE (16 NPUs), LLaMA-70B (64 NPUs), WRF-128 (HPC), Frontier traces
- **BookSim 2.0 fork**: cycle-accurate fabric, multicast, matrix() traffic, veritx_embed API, GEC/MECS support
- **ASTRA-sim BookSim2 backend**: runs real Chakra ETs on mesh and GEC, progress logging, no crashes
- **RTL cert**: 144/144 PASS (Alice's harness), CDG acyclic, P3 conservation, P4 pair-order INFO
- **MCTS topology search**: finds MECS 64-node (111 edges, 21.11c) and flatfly (928 edges, 19.78c) on Qwen3
- **Sweep + compare**: `veritx sweep` batch-evaluates mesh/torus/flatfly, `veritx compare` runs multi-seed statistical head-to-head
- **Per-phase traffic model**: 6 flow classes (global vs TP-local), per-expert dispatch, WRF-128 real traces

### What's honest
| Result | Value | Source |
|--------|-------|--------|
| MECS vs mesh (Qwen3 per-phase) | 21.11c vs 23.60c = **1.12×** | BookSim S1 |
| Hierarchical vs mesh (contention) | 20.53c vs 23.37c = **+12%** | BookSim S1 trace |
| flatfly vs mesh (Qwen3) | 19.78c vs 23.60c = **16%** | BookSim S1, but 928 edges |
| RTL cert | 144/144 PASS | Verilator co-sim |
| Dense vs MoE crossover | NoC matters at TP≥16 for dense, never for MoE | ASTRA-sim analytical |
| Ring vs star collectives | 66.7c vs 63,912c = **58×** | BookSim S1, real Qwen3 |
| Mesh vs GEC express (Qwen3) | 129,649c vs 129,550c = **same** | BookSim, IR=0.015 |
| Flatfly vs mesh (uniform IR=0.1) | 14.7c vs 33.4c = **2.3×** | BookSim native |
| GEC express vs mesh (transpose IR=0.1) | 17.1c vs 38.4c = **2.2×** | BookSim native |
| UCIe 32 bridges vs 8 bridges | 1758c vs 2710c = **35% better** | BookSim anynet |

### What's not yet honest
- BO uses hop-count scoring, not cycle-accurate BookSim → 16× accuracy gap
- C/R sweep timed out (all entries fake in `fix3_cr2.json`)
- "6× paper claim" decomposes to real 1.12× topology + aspirational adder
- No single `veritx run` reproducibility — manual script invocations still needed
- BookSim2 ASTRA-sim integration runs too slow for full LLM workload (hours)

---

## The Vision

### North Star
A researcher/engineer runs:
```bash
veritx run --workload qwen3-30b --nodes 64 --search mcts --scorer booksim --cert rtl
```
And gets a **certified Pareto-optimal topology** with:
- Cycle-accurate latency/throughput numbers (not hop-count)
- RTL certification (Verilator co-sim PASS)
- Area/power estimates (Timeloop + Accelergy)
- Paper-ready comparison table against baselines

### What makes this publishable
1. **Only system** that goes from real LLM traffic → topology synthesis → cycle-accurate proof → RTL certification in one pipeline
2. **ASTRA-sim BookSim2 integration** with GEC/MECS — the only such integration
3. **RTL certification framework** (144/144 PASS, CDG, conservation) — novel contribution
4. **Dense vs MoE crossover analysis** — when does NoC matter? Answer: TP≥16 for dense, never for MoE
5. **Inter-die UCIe optimization** — 32 bridges = 35% latency reduction, Pareto-optimal area/performance
6. **Traffic-pattern-dependent topology ranking** — mesh wins LLM, flatfly wins random, GEC wins all-to-all

---

## Task Roadmap

### Phase 1: CLI Strength (CURRENT)
Make the CLI unbreakable. Every command works, every number is real.

- [x] `veritx trace model` — traffic model → trace
- [x] `veritx trace chakra` — Chakra ETs → trace
- [x] `veritx evaluate booksim` — BookSim evaluation
- [x] `veritx evaluate anynet` — custom .anynet evaluation
- [x] `veritx synthesize bo` — Bayesian optimization topology search
- [x] `veritx certify flow` — flow-level certification
- [x] `veritx certify rtl` — RTL certification
- [x] `veritx run` — full pipeline orchestrator
- [x] `veritx status` — run history
- [x] `veritx sweep` — batch evaluate mesh/torus/flatfly
- [x] `veritx compare` — multi-seed statistical head-to-head
- [x] BO booksim validation: relative path bug fixed, sample_period reduced, timeout extended
- [ ] **Custom topology compare** — wire `.anynet` files into `compare` loop
- [ ] **`veritx report`** — generate paper-ready LaTeX table from compare results
- [ ] **Error handling audit** — every subprocess timeout/exit-code handled gracefully
- [ ] **Reproducibility** — every run writes a `manifest.json` with exact commands, seeds, git hash

### Phase 2: Scorer Accuracy
Replace hop-count with cycle-accurate BookSim as the BO objective.

- [ ] **BookSim S1 as BO scorer** — `evaluate_topology` calls BookSim latency mode, not `size * hops`
- [ ] **Traffic model integration** — BO evaluates against real Qwen3 per-phase traffic, not synthetic uniform
- [ ] **Injection rate sweep** — BO tries multiple IRs per topology (0.01, 0.05, 0.1, 0.2)
- [ ] **Parallel BookSim eval** — run N BookSim instances concurrently during BO (multiprocessing)
- [ ] **Validation timeout fix** — BookSim timeout on 64-node traces (need sample_period auto-tuning)

### Phase 3: Search Quality
Move from flat MCTS to graph-rewrite search that finds genuinely better topologies.

- [ ] **MCTS graph-rewrite** — add/remove/replace edges (not just remove), per TUM 2020
- [ ] **MECS generator** — parameterized k/c generation (currently hardcoded 64-node)
- [ ] **GEC generator** — parameterized o/d tradeoff sweep
- [ ] **Constraint-aware search** — max edges, max degree, wire-length budget
- [ ] **Multi-objective Pareto** — latency × area × power (NSGA-II or MOBO)
- [ ] **Warm start** — load previous BO/MCTS results to continue search

### Phase 4: Traffic Model Fidelity
Replace averages with real workload timing for honest numbers.

- [x] Per-phase global vs TP-local (6 flow classes) — DONE
- [x] WRF-128 real HPC traces — DONE
- [ ] **Deadline-aware traffic** — SLO TTFT/TPOT hints, not just "per-phase average"
- [ ] **Burst characterization** — Poisson vs self-similar injection per flow class
- [ ] **Multi-workload evaluation** — same topology scored on Qwen3 + WRF + LLaMA simultaneously
- [ ] **Workload mix optimization** — find topologies that robustly handle diverse traffic

### Phase 5: ASTRA-sim Integration (Production)
Make ASTRA-sim BookSim2 backend run full LLM workloads end-to-end.

- [x] 4-NPU mesh + GEC run cleanly, no crashes — DONE
- [x] Progress logging at all three levels — DONE
- [ ] **Speed optimization** — current ~12 events in 300s is too slow for full trace
  - [ ] Skip long compute phases (inject flits directly at collective start)
  - [ ] Reduce BookSim cycle granularity for analytical pre-filter
  - [ ] Batch injection for identical-size collectives
- [ ] **Full Qwen3-30B run** — 16 NPUs, 1160 events, complete without timeout
- [ ] **Full LLaMA-70B run** — 64 NPUs, dense model, TP=64
- [ ] **Scaling analysis** — 4/8/16/32/64 NPUs, find communication bottleneck crossover
- [ ] **BookSim vs analytical comparison** — validate analytical backend against cycle-accurate

### Phase 6: RTL Certification (Paper-Quality)
Make the RTL cert framework rigorous enough for publication.

- [x] 144/144 PASS on mesh — DONE
- [x] P3 conservation check — DONE
- [x] P4 pair-order INFO (demoted, by design) — DONE
- [ ] **GEC RTL cert** — generate GEC router, run certify.sh on it
- [ ] **MECS RTL cert** — generate MECS router, run certify.sh
- [ ] **Stress harness expansion** — larger traces, more patterns, higher IR
- [ ] **Timing closure check** — post-synthesis timing (if synthesis available)
- [ ] **Area/power via Accelergy** — pJ/hop, total energy per workload

### Phase 7: Inter-Die Optimization (NEW)
Optimize multi-die NoC with UCIe bridges.

- [x] **2-die mesh + UCIe stress test** — intra/inter/mixed traffic patterns — DONE
- [x] **UCIe bridge scaling** — 1→64 bridges, found sweet spot at 32 — DONE
- [ ] **32-bridge validation** — test with real Qwen3 inter-die traffic
- [ ] **Bridge latency sweep** — 5/10/20/40 cycle UCIe latency
- [ ] **Multi-die topology comparison** — mesh+dies vs single large mesh vs hierarchical
- [ ] **Inter-die routing optimization** — dedicated bridges for TP vs EP traffic
- [ ] **noc_2die.sv integration** — generate RTL for 2-die config, run cert

### Phase 8: Paper & Publication
Package the contribution for submission.

- [ ] **Paper outline** — Motivation / Method / Results / Related Work
- [ ] **Figure generation** — Pareto frontier, scaling curves, RTL waveforms
- [ ] **Reproducibility package** — Docker + `veritx run` one-liner
- [ ] **Comparison table** — VeritX vs Timeloop-only vs ASTRA-sim-only vs manual DSE
- [ ] **Submission target** — ISCA/MICRO/HPCA workshop, or DATE/ICCAD

---

## Architecture: How Everything Connects

```
Real Workload          Our Tools              Proof
─────────────          ─────────              ─────
Qwen3-30B MoE     ──→ veritx trace     ──→ .trace file
LLaMA-70B Dense   ──→ veritx trace     ──→ .trace file
WRF-128 HPC       ──→ veritx trace     ──→ .trace file

.trace file       ──→ veritx synthesize ──→ topo.anynet (BO/MCTS)
.trace + topo     ──→ veritx evaluate   ──→ latency, throughput
.trace + topos    ──→ veritx compare    ──→ statistical head-to-head
.trace + topos    ──→ veritx sweep      ──→ batch ranking
topo + model      ──→ veritx certify    ──→ PASS/FAIL (flow + RTL)

Full pipeline:
  veritx run ──→ trace → model → BO → BookSim → cert ──→ manifest.json

Inter-die:
  2-die mesh ──→ UCIe bridges ──→ BookSim anynet ──→ scaling analysis
```

### The "One Fabric" Principle
Every tool that produces traffic (Timeloop, LLMServingSim) must eventually express it through **the one BookSim fork**. The RTL must reproduce that fork's behavior flit-for-flit. Nothing else defines the fabric.

### The Inter-Die Principle
Multi-die systems add UCIe bridges as a design knob. The bridge count (1-64) creates a Pareto frontier between latency and area. 32 bridges is the sweet spot for 2×64-node systems.

---

## Open Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| BO hop-count scorer → wrong topologies | Paper invalid | Phase 2: wire BookSim S1 as scorer |
| ASTRA-sim too slow for full traces | No end-to-end proof | Phase 5: speed optimization |
| GEC/MECS RTL never generated | No silicon proof | Phase 6: generate and cert |
| No area/power model | Weak paper contribution | Phase 6: Accelergy integration |
| Custom topology compare doesn't work | Can't validate BO results | Phase 1: wire .anynet into compare |

---

## Success Criteria

### Minimum viable paper
- [ ] BO finds topology with **measurable** improvement over mesh (not just 1.12×)
- [ ] Improvement validated with **cycle-accurate** BookSim (not hop-count)
- [ ] RTL cert PASS on the winning topology
- [ ] Comparison table with error bars (multi-seed)
- [ ] At least 2 workloads (Qwen3 + one other)

### Strong paper
- [ ] Pareto frontier (latency × area × power) with 3+ topologies
- [ ] Scaling analysis (4/8/16/32/64 NPUs) showing when NoC matters
- [ ] Dense vs MoE crossover (TP=16 threshold)
- [ ] Full ASTRA-sim end-to-end on real LLM workload
- [ ] Reproducibility package (Docker + one-liner)

### Dream paper
- [ ] MCTS graph-rewrite finds topology Timeloop can't
- [ ] RTL synthesis timing closure (not just Verilator co-sim)
- [ ] Comparison against commercial NoC IP (Arteris, NetSpeed)
- [ ] Industry partnership for silicon validation
