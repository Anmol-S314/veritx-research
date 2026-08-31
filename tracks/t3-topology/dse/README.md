# VeritX — Intent-to-Fabric Compiler for AI Network-on-Chip

```
 __     __        _ _  __  __
 \ \   / /__ _ __(_) |_\ \/ /
  \ \ / / _ \ '__| | __|\  /
   \ V /  __/ |  | | |_ /  \
    \_/ \___|_|  |_|\__/_/\_\
```

**v0.3.0** — Turn workload traces into verified NoC topologies with cycle-accurate proof, formal reports, and signed design manifests.

> **If you're stuck, this README is the single source of truth.** Every command, every build step, every debug trick is here. This is a wiki — search it, don't guess.

---

## Table of Contents

- [1. What VeritX Does](#1-what-veritx-does)
- [2. Repository Layout](#2-repository-layout)
- [3. Quick Start](#3-quick-start)
- [4. Full Build Guide](#4-full-build-guide)
- [5. Command Reference](#5-command-reference)
- [6. Trace Format & Generation](#6-trace-format--generation)
- [7. Architecture](#7-architecture)
- [8. Design Principles](#8-design-principles)
- [9. Third-Party Dependencies](#9-third-party-dependencies)
- [10. BookSim2 Deep Dive](#10-booksim2-deep-dive)
- [11. ASTRA-sim Multi-Die Simulation](#11-astra-sim-multi-die-simulation)
- [12. LLMServingSim Traffic Generation](#12-llmservingsim-traffic-generation)
- [13. E1-E5 Data Model](#13-e1-e5-data-model)
- [14. CompileRequest Format](#14-compilerequest-format)
- [15. Compile Pipeline Stages](#15-compile-pipeline-stages)
- [16. VC Derivation Algorithm](#16-vc-derivation-algorithm)
- [17. Verification Properties (F1-F8)](#17-verification-properties-f1-f8)
- [18. Output Format & Accuracy Caveats](#18-output-format--accuracy-caveats)
- [19. Built-in Topologies](#19-built-in-topologies)
- [20. Built-in Workload Presets](#20-built-in-workload-presets)
- [21. Extending VeritX](#21-extending-veritx)
- [22. Adding a New Topology](#22-adding-a-new-topology)
- [23. Adding a New Workload Preset](#23-adding-a-new-workload-preset)
- [24. Adding a New Agent Kind](#24-adding-a-new-agent-kind)
- [25. Adding a New Dependency Kind](#25-adding-a-new-dependency-kind)
- [26. Adding a New Engine Stage](#26-adding-a-new-engine-stage)
- [27. Adding a New Report Type](#27-adding-a-new-report-type)
- [28. Adding a New CLI Command](#28-adding-a-new-cli-command)
- [29. Adding a New Verification Check](#29-adding-a-new-verification-check)
- [30. Testing](#30-testing)
- [31. Debugging & Troubleshooting](#31-debugging--troubleshooting)
- [32. Common Pitfalls](#32-common-pitfalls)
- [33. Performance Benchmarks](#33-performance-benchmarks)
- [34. Research Findings](#34-research-findings)
- [35. Comparison with Other Tools](#35-comparison-with-other-tools)
- [36. Hardware Requirements](#36-hardware-requirements)
- [37. Environment Setup](#37-environment-setup)
- [38. CI/CD Integration](#38-cicd-integration)
- [39. Security Considerations](#39-security-considerations)
- [40. API Reference](#40-api-reference)
- [41. Configuration Reference](#41-configuration-reference)
- [42. Glossary](#42-glossary)
- [43. Changelog](#43-changelog)
- [44. Roadmap](#44-roadmap)
- [45. Known Limitations](#45-known-limitations)
- [46. FAQ](#46-faq)
- [47. License](#47-license)
- [48. Contributing](#48-contributing)
- [49. References](#49-references)
- [50. Support](#50-support)

---

## 1. What VeritX Does

VeritX is an **intent-to-fabric compiler** for AI Network-on-Chip design. It takes a high-level description of your AI workload (model type, parallelism, traffic trace) and produces a complete, verified NoC fabric specification.

### What you give it:
- A model description (Qwen3 MoE, LLaMA-70B dense, etc.)
- Parallelism configuration (TP, EP, DP degrees)
- A traffic trace (generated from real LLM serving)
- Requirements (latency ceiling, bandwidth floor)

### What it gives you:
1. **Validated** system configuration against guardrails
2. **Derived** LOCKED parameters (routing, VC structure) from dependency graphs
3. **Simulated** latency via BookSim2 cycle-accurate simulation
4. **Verified** F1-F8 formal properties (deadlock freedom, liveness, ordering)
5. **Generated** UVM testbenches, RTL tracking, and signed design manifests
6. **Reported** area/power/timing estimates with accuracy caveats

### High-Level Pipeline

```mermaid
flowchart LR
    A["Workload
(Model + TP/EP/DP)"] --> B["CompileRequest
(Agents + Deps + Config)"]
    C["Traffic Trace
(Real LLM serving)"] --> B
    B --> D["1⃣ Validate
(Guardrails)"]
    D --> E["2⃣ Derive
(Routing + VCs)"]
    E --> F["3⃣ Simulate
(BookSim2)"]
    F --> G["4⃣ Verify
(F1-F8)"]
    G --> H["5⃣ Generate
(UVM + Manifest)"]
    H --> I["6⃣ Report
(Area/Power/Timing)"]
    I --> J["Verified Fabric
(Signed + Documented)"]
```

### Key insight:
The compiler doesn't just "run a simulation." It **derives** correctness-critical parameters (routing function, VC count, turn restrictions) from the dependency graph, so a user cannot accidentally create a deadlock-prone configuration.

```mermaid
flowchart TD
    A["Dependency Graph (E4)"] --> B{"Cycles?"}
    B -->|"No cycles"| C["dim_order routing\n1 VC"]
    B -->|"1 cycle"| D["dor routing\n2 VCs\nwest_first + north_last"]
    B -->|"2+ cycles"| E["min_adapt routing\nN+1 VCs\nno turn restrictions"]
    C --> F[" LOCKED\nUser cannot override"]
    D --> F
    E --> F
```

---

## 2. Repository Layout

```
veritx-research/                           repo root
  third_party/
    booksim2/                          CANONICAL BookSim2 fork (edit here)
      src/
        booksim                        CLI binary (standalone)
        libveritx_embed.a              embedding library (ASTRA-sim)
        veritx_embed.*                 embedding API (ASTRA-sim integration)
        veritx_ext.*                   trace replay extension
        traffic.cpp                    trace() traffic pattern factory
        flit.hpp/cpp                   multicast fields (mcast, mcast_copies)
        networks/
          anynet.o                     anynet topology support
          gec.o                        GEC express topology
          custom4.o                    MECS 4-tap topology
        Makefile                       builds booksim + libveritx_embed.a
        sync_to_astra.sh               sync to ASTRA-sim internal copy
      METADATA.json                    version tracking (v0.2.1)
    timeloop/                          Timeloop/Mapper (energy model)

  serving/
    astra-sim/                         ASTRA-sim multi-die simulator
      extern/network_backend/booksim2/ internal booksim2 copy (synced)
      astra-sim/network_frontend/booksim2/bin/
        AstraSim_BookSim2              multi-die binary
      examples/network/ns3/            network configs (4/8/16 nodes)
    LLMServingSim/                     traffic trace generator (KAIST)
      serving/                         trace generation pipeline
      profiler/                        measured module latencies
      traces/                          cited run traces + configs
      workloads/                       input workload JSONLs
    results/                           3-way comparison results

  runs/
    traces/                            traffic traces for simulation
      qwen3_serving_16rank.trace      Qwen3 MoE serving (95K pkts, 16 nodes)
      llama70b_tp64_ring.trace        LLaMA-70B ring (1.3M pkts, 64 nodes)
      llama70b_tp64_alltoall.trace    LLaMA-70B all-to-all (1.3M pkts)
      llama_1b_attention.trace         LLaMA-1B attention (258K pkts)
      qwen3_tree.trace                 Qwen3 tree topo (26M pkts)
      qwen3_star.trace                 Qwen3 star topo
      qwen3_ring.trace                 Qwen3 ring topo
    booksim/                           BookSim outputs + .anynet files
    compile_requests/                  generated CompileRequest JSONs

  scripts/
    golden_model.py                    golden model reference

  tracks/t3-topology/
    dse/                               VeritX CLI (this package)
      README.md                        THIS FILE (the wiki)
      pyproject.toml                   pip install -e . config

      veritx_dse/                      core package (30 modules)
        paths.py                       SINGLE SOURCE: REPO, DSE_DIR, RUNS_DIR, BOOKSIM_BIN
        cli.py                         17 CLI commands, thin dispatch
        compile_model.py               E1-E5 data model, guardrails, VC derivation
        pipeline.py                    compare, sweep, orchestration
        booksim.py                     BookSim2 config generation + execution
        evaluator.py                   BookSim runner with LRU caching
        traces.py                      trace validation + analysis
        reports.py                     area/power/timing estimates
        presets.py                     topology + workload registry
        artifact.py                    HMAC signing + manifests
        uvm_gen.py                     UVM testbench generator
        config.py                      configuration management (env vars)
        constants.py                   physical constants (7nm tech)
        errors.py                      structured error hierarchy
        logger.py                      file logger
        logging.py                     structured logging with Ctx
        recovery.py                    atomic writes + cleanup on failure
        commands_trace.py              trace CLI handlers (validate, info, extract)
        model_to_trace.py              traffic model to trace converter
        trace_to_binary.py             ASCII to binary trace conversion
        chakra_to_dse.py               Chakra trace converter
        recommend.py                   BO recommendation engine
        roofline.py                    roofline model analysis
        objective.py                   optimization objectives
        phase_sequencer.py             phase sequencing
        traffic_model.py               phase-aware traffic model
        dse_to_frontend.py             DSE-to-frontend interface
        __init__.py                    public API re-exports

      tests/                           278 tests (21 integration + 257 unit)
        test_integration.py            end-to-end CLI (21 tests)
        test_compile_model.py          E1-E5, guardrails (50 tests)
        test_prd_gaps.py               reports, artifacts (38 tests)
        test_cli_modules.py            CLI trace, topology (33 tests)
        test_entry_point.py            package install (23 tests)
        test_sprint1.py                Result/Artifact (19 tests)
        test_compile_uvm.py            UVM in pipeline (14 tests)
        test_missing_coverage.py       coverage gaps (14 tests)
        test_api_contract.py           API contracts (11 tests)
        test_uvm_gen.py                UVM generation (11 tests)
        test_cli.py                    BookSim mock (10 tests)
        test_reports.py                area/power/timing (9 tests)
        test_astra_trace.py            ASTRA-sim trace format

      scripts/                         standalone analysis scripts (not part of package)
        bo_synthesizer.py             Bayesian optimization synthesis
        iterative_synthesizer.py      RHO/GRPO search
        multi_workload_pareto.py      Pareto front computation
        milestone_c.py                Milestone C certifier
        run.py                        DSE grid search smoke test
        space.py                      design space definition
        search.py                     grid search implementation
        event_objective.py             event-based scoring
        milp_topology_v2.py           MILP topology constants + edge cost
        deadlock_routing.py            deadlock detection + routing parse
        log.py                         shared logger for standalone scripts
        objective.py                   L2 recommend objective
        ppa_evaluator.py               DSE PPA evaluator (SCALE-Sim + BookSim + Timeloop)
        surrogate.py                   MLP surrogate model
        verify.sh                      verification runner
        ucie_scaling_results.md        UCIe scaling data

      examples/                        sample CompileRequest JSONs
        _template.json                full template with documentation
        qwen3_moe_16npu.json          Qwen3 MoE, 16 NPUs (workload preset)
        llama70b_tp64.json            LLaMA-70B dense, TP=64
        llama1b_tp64.json             LLaMA-1B attention, TP=64
        dense_64npu.json              generic dense, 64 NPUs
        moe_8npu.json                 generic MoE, 8 NPUs

      models/                          traffic model definitions
        traffic_model.json             generic traffic model
        automotive_adas.json           automotive ADAS
        automotive_real.json           real automotive trace
        hpc_real.json                  real HPC workload
        hpc_wrf_real.json              WRF weather simulation

      inputs/                          legacy input data
        chakra_converted.trace         converted Chakra trace
        qwen3_serving_astra.trace      ASTRA-sim serving trace
        qwen_moe_*.json / *.mat        MoE workload matrices
        workloads.json                 workload definitions

      docs/                            documentation
        PRD-CHECKLIST.md               Srota sections 1-16 compliance
        LONG-TERM-VISION.md            roadmap
        RESULTS-AND-LEARNINGS.md       research findings
        SHORTCOMINGS-AND-IMPROVEMENTS.md  known limitations
        BOOKSIM-PERF-OPTIMIZATION.md   BookSim tuning guide
        VERITX-CLI-AND-TUI-PLAN.md    CLI/TUI roadmap
        HANDOFF-calibration-plan.md    calibration handoff
        AUDIT-2026-08-28.md            code audit results
        PARETO-REPLAY-RESULTS-2026-08-29.md  replay Pareto data
        PER-PHASE-PARETO-RESULTS-2026-08-29.md  per-phase data
        RATE-MISMATCH-OBSERVATION-2026-08-29.md  cross-check note
        CONTRIBUTING.md                contribution guidelines

  configs/                             Timeloop configs
  Makefile                             top-level build targets
```

---

## 3. Quick Start

### Install (30 seconds)

```bash
cd tracks/t3-topology/dse
pip install -e .
veritx --help
```

### First Run (2 minutes)

```bash
# 1. Validate a real traffic trace
veritx trace validate runs/traces/qwen3_serving_16rank.trace

# 2. Analyze trace characteristics (burst patterns, injection rates)
veritx trace info runs/traces/qwen3_serving_16rank.trace

# 3. Compare topologies head-to-head
veritx compare \
    --trace runs/traces/qwen3_serving_16rank.trace \
    --topos mesh_8x8,torus_8x8 \
    --seeds 1

# 4. Full intent-to-fabric pipeline
veritx compile examples/qwen3_moe_16npu.json
```

### Interactive Wizard

```bash
veritx init
# Walks you through: workload -> agents -> requirements -> dependencies -> config
# Outputs: runs/compile_requests/<model>.json
```

---

## 3a. Step-by-Step Tutorial: Complete DSE Workflow

This tutorial walks through the entire design space exploration workflow, from understanding your traffic trace to selecting the best topology and compiling a verified fabric.

### Overview

```mermaid
flowchart LR
    A["Step 1\nUnderstand Trace"] --> B["Step 2\nValidate Format"]
    B --> C["Step 3\nAnalyze Bursts"]
    C --> D["Step 4\nSweep Topologies"]
    D --> E["Step 5\nCompare Winners"]
    E --> F["Step 6\nCompile Fabric"]
    F --> G["Step 7\nVerify + Report"]
```

### Step 1: Understand Your Traffic Trace

Before running any simulation, understand what your trace represents.

```bash
veritx trace info runs/traces/qwen3_serving_16rank.trace
```

Expected output:
```
Size:         1,531,093 bytes (1495KB)
Packets:      95,232
Sources:      16
Classes:      2
Time range:   [0, 652210] (652,211 cycles)
Avg IR:       0.146014 pkts/cycle
Bursts:       48 (gap>100c)
Avg burst:    1984 pkts
Max burst:    1984 pkts
Avg gap:      12773 cycles
Top srcs:     [(0, 49152), (4, 3072), (8, 3072), (12, 3072), (16, 3072)]
Top dsts:     [(4, 6144), (8, 6144), (12, 6144), (16, 6144), (20, 6144)]
Profile:      MODERATE (0.1<IR<1.0) -- topology may matter
Burst IR:     1.94 pkts/cycle (during max burst)
Burst mode:   INJECTION-LIMITED -- NIC injection is bottleneck
```

**What to look for:**

| Metric | What it tells you | Action if concerning |
|--------|-------------------|---------------------|
| `Profile: MODERATE` | Topology matters (0.1 < IR < 1.0) | Run full comparison |
| `Profile: SPARSE` | Topology irrelevant (IR < 0.1) | Skip comparison, any topology works |
| `Profile: SATURATED` | Network is the bottleneck (IR > 1.0) | Focus on wire count, not latency |
| `Burst IR: 1.94` | 13x average during bursts | Topology matters most during bursts |
| `Top srcs: [(0, 49152)]` | Skewed: source 0 sends 51% of traffic | Check if topology handles skew |

### Step 2: Validate Trace Format

```bash
veritx trace validate runs/traces/qwen3_serving_16rank.trace
```

Expected output:
```
Format:       VALID
Packets:      95,232
Sources:      16 unique (IDs 0-8)
Classes:      2
Sizes:        [8]
Time range:   [2727, 652210] (649,484 cycles)
Avg IR:       0.146627 pkts/cycle
Self-loops:   0

Warnings (1):
  All packets have same size ({8}) -- unusual for real traffic

Trace is usable but has 1 warnings
```

**If validation fails:**
- `Path traversal not allowed` -- use absolute paths
- `File not found` -- check the path, use `ls` to verify
- `Invalid format` -- check trace file is ASCII, space-separated

### Step 3: Analyze Burst Patterns

Understanding bursts is critical because topology matters most during high-traffic periods.

```bash
veritx trace info runs/traces/qwen3_serving_16rank.trace 2>&1 | grep -A5 "Burst"
```

Key insight: This trace has **injection-limited bursts** -- the NIC can only inject so fast, so the network isn't saturated during bursts. This means topology differences will be small.

### Step 4: Sweep All Topologies

Run every built-in topology to find the baseline:

```bash
veritx sweep --trace runs/traces/qwen3_serving_16rank.trace --timeout 60
```

Expected output:
```
Topology         Nodes  Edges    Latency    Hops Status
------------------------------------------------------------
mesh_4x4            16     32    638.11c       -   OK
mesh_8x8            64    128   1863.12c       -   OK
torus_8x8           64    128   1891.04c       -   OK
flatfly_64          64     48   1951.18c       -   OK
gec_express_k8      64    560   1836.43c       -   OK
gec_mecs_k8         64    176   2257.16c       -   OK
gec_mesh_k8         64    112   1836.43c       -   OK

Best: mesh_4x4 (638.11c)
Worst: gec_mecs_k8 (2257.16c)
Spread: 71.7%
```

**Interpretation:**
- mesh_4x4 wins because it has fewer nodes (16 vs 64) -- not a fair comparison
- Among 64-node topologies: mesh_8x8 (1863c) is close to gec_express (1836c)
- torus is slightly worse than mesh (wrap-around links don't help here)
- gec_mecs is the worst -- multicast overhead hurts sparse traffic

### Step 5: Compare Top Winners Head-to-Head

Focus on the top contenders:

```bash
veritx compare \
    --trace runs/traces/qwen3_serving_16rank.trace \
    --topos mesh_8x8,torus_8x8 \
    --seeds 3 \
    --timeout 60
```

Expected output:
```
Topology         Nodes  Edges     Mean     Std      Min      Max Runs
------------------------------------------------------------------------
mesh_8x8            64    128 1863.12c   0.00c 1863.12c 1863.12c    3
torus_8x8           64    128 1891.04c   0.00c 1891.04c 1891.04c    3

Winner: mesh_8x8 (1863.12c +/- 0.00c)
vs torus_8x8: 1.5% faster
```

**Why 3 seeds?** BookSim is deterministic, but different seeds exercise different random arbitration decisions. 3 seeds give statistical confidence.

### Step 5b: Try Custom Topologies

If you have DSE-optimized topologies (from RHO/GRPO search):

```bash
veritx compare \
    --trace runs/traces/qwen3_serving_16rank.trace \
    --topos mesh_8x8,torus_8x8 \
    --anynet runs/booksim/grpo_best.anynet \
    --seeds 3
```

Expected output:
```
Topology         Nodes  Edges     Mean     Std      Min      Max Runs
------------------------------------------------------------------------
mesh_8x8            64    128 1863.12c   0.00c 1863.12c 1863.12c    3
torus_8x8           64    128 1891.04c   0.00c 1891.04c 1891.04c    3
grpo_best           64    111 1842.67c   0.00c 1842.67c 1842.67c    3

Winner: grpo_best (1842.67c +/- 0.00c)
vs torus_8x8: 2.6% faster
```

**Key finding:** grpo_best (111 edges) beats mesh (128 edges) by 2.6% with 17 fewer wires. Wire-efficient.

### Step 5c: Sensitivity Analysis

Test how rankings change under different injection rates:

```bash
veritx compare \
    --trace runs/traces/qwen3_serving_16rank.trace \
    --topos mesh_8x8,torus_8x8 \
    --sensitivity 0.01 0.05 0.1 0.2
```

This tells you: does the topology ranking flip under congestion? If mesh always wins, the choice is clear. If rankings change, you need to decide which injection rate your workload actually experiences.

### Step 6: Compile the Fabric

Once you've selected a topology, run the full compile pipeline:

```bash
veritx compile examples/qwen3_moe_16npu.json
```

Expected output:
```
Step 1/6: Validate       ok=True, vc_count=1
Step 2/6: Derive         routing=dim_order, VCs=1
Step 3/6: Simulate       Latency: 1850.64c (real BookSim)
Step 4/6: Verify         7/8 PASS (F7 QoS pending)
Step 5/6: Generate       manifest, rtl, report
Step 6/6: Report         area=0.272mm2, power=0.07W, fmax=1965MHz

Compile Result
--------------------------------------------------
Model:      Qwen3-30B-A3B
Topology:   mesh k=8
Routing:    dim_order (LOCKED)
VCs:        1
Latency:    1850.64c
Area:       0.2720 mm2
Power:      0.0701 W
Fmax:       1965 MHz
Energy:     0.600 pJ/bit
Verify:     7/8 PASS
Artifacts:  manifest, rtl, report
Manifest:   rev=1 signed=True
Hash:       7fbc43ab7e8a5d4d...
```

**What happened:**
1. **Validate** -- checked CompileRequest, no LOCKED fields in NocConfig
2. **Derive** -- no blocking cycles in dependency graph -> dim_order routing, 1 VC
3. **Simulate** -- ran BookSim2 on the real trace, got 1850.64c latency
4. **Verify** -- F1-F8 checks, 7/8 pass (F7 QoS isolation pending)
5. **Generate** -- created UVM testbench + signed design manifest
6. **Report** -- estimated area/power/timing with accuracy caveats

### Step 6b: Generate UVM Testbench

For formal verification:

```bash
veritx generate uvm \
    --request examples/qwen3_moe_16npu.json \
    --out runs/uvm/
```

Produces:
- `tb_noc.sv` -- top-level testbench
- `seq_lib.sv` -- stimulus sequences
- `assertions.sv` -- protocol checks
- `cov.sv` -- coverage model

### Step 6c: Compare with Different Workloads

Test if your topology choice holds across workloads:

```bash
# MoE workload
veritx compile examples/qwen3_moe_16npu.json

# Dense workload
veritx compile examples/llama70b_tp64.json

# Small workload
veritx compile examples/llama1b_tp64.json
```

Compare results:
```
Workload       Latency    Area      Power     Topology
----------------------------------------------------
Qwen3 MoE      1850c      0.27mm2   0.07W     mesh_8x8
LLaMA-70B      58515c     0.98mm2   0.25W     mesh_8x8
LLaMA-1B       573c       0.92mm2   0.24W     mesh_8x8
```

### Step 7: Review the Output

The JSON report from `veritx compile` contains everything:

```json
{
  "area": {"total_mm2": 0.272, "routers_mm2": 0.1, "links_mm2": 0.038},
  "power": {"dynamic_w": 0.060, "leakage_w": 0.010, "total_w": 0.070},
  "timing": {"max_freq_mhz": 1965, "critical_path_ps": 381.8},
  "energy": {"per_bit_pj": 0.630},
  "simulation": {"latency": 1850.64},
  "vc_assignment": {"routing_function": "dim_order", "vc_count": 1},
  "verification": {"ok": true, "checks": [...], "errors": []},
  "artifacts": [{"kind": "manifest", "uri": "...", "checksum": "..."}],
  "manifest": {"design_id": "...", "revision": 1, "signature": "..."}
}
```

### Complete Workflow Summary

```mermaid
flowchart TD
    A["1. trace info\nUnderstand traffic pattern"] --> B["2. trace validate\nCheck format"]
    B --> C["3. trace info (bursts)\nAnalyze injection rates"]
    C --> D{"IR > 0.1?"}
    D -->|"No (sparse)"| E["Skip comparison\nAny topology works"]
    D -->|"Yes"| F["4. sweep\nRun all topologies"]
    F --> G["5. compare\nTop 2-3 winners"]
    G --> H{"Custom topologies?"}
    H -->|"Yes"| I["5b. compare --anynet\nDSE-optimized topologies"]
    H -->|"No"| J["5c. sensitivity\nTest under congestion"]
    I --> J
    J --> K["6. compile\nFull pipeline"]
    K --> L{"Need UVM?"}
    L -->|"Yes"| M["6b. generate uvm\nFormal verification"]
    L -->|"No"| N["7. Review output\nJSON report + manifest"]
    M --> N
```

### Tips for New Users

1. **Start with `trace info`** -- always understand your traffic before simulating
2. **Use `--seeds 3`** in compare -- single-seed results can be misleading
3. **Check burst IR** -- if burst IR is close to average IR, topology doesn't matter much
4. **Compare against torus** -- torus is the honest baseline (same wires, wrap-around)
5. **Run sensitivity** -- topology rankings can flip under different injection rates
6. **Read accuracy caveats** -- BookSim latency is trustworthy, area/power are relative
7. **Use absolute paths** -- relative paths can fail depending on CWD

---

## 4. Full Build Guide

### 4.1 Prerequisites

| Tool | Version | Why |
|------|---------|-----|
| Python | 3.10+ | VeritX CLI |
| gcc/g++ | 11+ | BookSim2 compilation |
| make | any | Build system |
| cmake | 3.22+ | ASTRA-sim (optional) |
| pip | 21+ | Package installation |

### 4.2 Build BookSim2 (Required)

```bash
cd third_party/booksim2/src

# Standalone binary (for veritx compare, sweep, compile)
make -j$(nproc)

# Verify
./booksim
# Should print BookSim2 help text

# Embedding library (for ASTRA-sim integration)
make lib
# Produces libveritx_embed.a
```

**Build output:**
```
booksim              ← 19.5MB standalone binary
libveritx_embed.a    ← 52MB embedding library
*.o                  ← object files
```

### 4.3 Build ASTRA-sim (Optional — for multi-die simulation)

```bash
# 1. Sync BookSim2 source into ASTRA-sim's internal copy
third_party/booksim2/sync_to_astra.sh

# 2. Build ASTRA-sim with BookSim2 backend
cd serving/astra-sim/build/astra_booksim2
./build.sh

# 3. Verify binary exists
ls -la ../../astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2
```

### 4.4 Install VeritX CLI

```bash
cd tracks/t3-topology/dse
pip install -e .

# Verify
veritx --help
# Should print the VeritX banner + command list
```

### 4.5 Run Tests

```bash
cd tracks/t3-topology/dse

# Full suite (278 tests, ~2 minutes)
python3 -m pytest tests/ -v

# Quick smoke test (no BookSim needed)
python3 -m pytest tests/test_compile_model.py tests/test_prd_gaps.py -v

# Integration tests (require BookSim binary)
python3 -m pytest tests/test_integration.py -v

# With coverage
python3 -m pytest tests/ --cov=veritx_dse --cov-report=term-missing
```

---

## 5. Command Reference

### 5.1 Trace Operations (`veritx trace`)

| Command | What it does | Example |
|---------|-------------|---------|
| `trace validate` | Check trace format, detect anomalies | `veritx trace validate trace.trace` |
| `trace info` | Analyze burst patterns, injection rates | `veritx trace info trace.trace` |
| `trace extract` | Pull single burst or redistribute uniformly | `veritx trace extract trace.trace --burst 100` |
| `trace slice` | Filter by traffic class | `veritx trace slice --trace t.trace --classes 0,1` |
| `trace chakra` | Convert Chakra .et execution traces | `veritx trace chakra et_dir/ --nodes 64` |
| `trace model` | Convert TrafficModel JSON | `veritx trace model model.json --nodes 64` |
| `trace hpc` | Copy HPC MPI traces | `veritx trace hpc mpi.trace` |

### 5.2 Topology Search (`veritx synthesize`)

| Command | Algorithm | When to use |
|---------|-----------|-------------|
| `synthesize bo` | Bayesian Optimization | Small search spaces (<100 evals) |
| `synthesize grid` | Exhaustive grid | Baseline comparison |
| `synthesize iterative --method rho` | Random Hill Climbing | Incremental refinement |
| `synthesize iterative --method grpo` | Group Relative Policy Optimization | Large spaces |

```bash
veritx synthesize bo --traffic trace.trace --nodes 64 --iters 50
veritx synthesize grid --traffic trace.trace --nodes 64
veritx synthesize iterative --trace trace.trace --method rho --steps 100
veritx synthesize iterative --trace trace.trace --method grpo --steps 100
```

### 5.3 Evaluation (`veritx evaluate`)

| Command | Backend | What it does |
|---------|---------|-------------|
| `evaluate booksim` | BookSim2 | Mesh topology trace replay |
| `evaluate anynet` | BookSim2 | Custom .anynet topology |
| `evaluate astra` | ASTRA-sim | Multi-die network simulation |

```bash
veritx evaluate booksim --trace trace.trace --k 8
veritx evaluate anynet --topo grpo_best.anynet --trace trace.trace
```

### 5.4 Comparison (`veritx compare`)

```bash
# Basic comparison (3 seeds for statistical confidence)
veritx compare --trace trace.trace --topos mesh_8x8,torus_8x8 --seeds 3

# Include custom topologies
veritx compare --trace trace.trace \
    --topos mesh_8x8,torus_8x8 \
    --anynet grpo_best.anynet,mecs64.anynet

# Dense preset (LLaMA-70B all-to-all)
veritx compare --trace trace.trace --dense llama70b_a2a

# Throughput mode (Bernoulli injection)
veritx compare --trace trace.trace --topos mesh_8x8 --mode throughput --ir 0.05

# Sensitivity analysis across injection rates
veritx compare --trace trace.trace \
    --topos mesh_8x8,torus_8x8 \
    --sensitivity 0.01 0.05 0.1 0.2

# Memory hierarchy correction
veritx compare --trace trace.trace --topos mesh_8x8 --memory --banks 4
```

### 5.5 Batch Operations

| Command | What it does |
|---------|-------------|
| `sweep` | Evaluate all built-in topologies on a trace |
| `pareto` | Multi-workload Pareto front analysis |
| `baseline` | Compare against published baseline topologies |

```bash
veritx sweep --trace trace.trace
veritx pareto --traces trace1.trace,trace2.trace --topos mesh_8x8,torus_8x8
veritx baseline --trace trace.trace --topos my_custom.anynet
```

### 5.6 Compile Pipeline (`veritx compile`)

The full intent-to-fabric pipeline — 6 stages:

```
Validate → Derive → Simulate → Verify → Generate → Report
```

```bash
veritx compile examples/qwen3_moe_16npu.json
veritx compile examples/llama70b_tp64.json -o report.json
veritx --json compile examples/qwen3_moe_16npu.json
```

### 5.7 Generation (`veritx generate`)

```bash
veritx generate uvm --request request.json --nodes 64 --k 8 --out runs/uvm/
```

Produces: `tb_noc.sv`, `seq_lib.sv`, `assertions.sv`, `cov.sv`

### 5.8 Run History

```bash
veritx runs --last 10
veritx results --last 5
veritx diff run_a run_b
veritx report --json results.json
```

---

## 6. Trace Format & Generation

### Trace Lifecycle: LLMServingSim to BookSim2

```mermaid
flowchart TD
    subgraph Generate["1. Generate Trace (LLMServingSim)"]
        L1["LLM Workload\nQwen3-30B-A3B, 16 NPU"] --> L2["vLLM Scheduler\nPython frontend"]
        L2 --> L3["ASTRA-sim Backend\nC++ network model"]
        L3 --> L4["Trace Output\ncycle src dst class size"]
    end

    subgraph Store["2. Store Trace (runs/traces/)"]
        L4 --> T1["qwen3_serving_16rank.trace\n95K packets, 16 src/dst"]
        T1 --> T2["ASCII format:\n2727 0 0 4 8\n2728 4 0 8 8\n..."]
    end

    subgraph Validate["3. Validate (veritx trace)"]
        T2 --> V1["veritx trace validate\nCheck format + anomalies"]
        V1 --> V2["veritx trace info\nAnalyze bursts + IR"]
        V2 --> V3{"Profile?"}
        V3 -->|"SPARSE (IR<0.1)"| V4["Topology irrelevant\nSkip comparison"]
        V3 -->|"MODERATE (0.1<IR<1.0)"| V5["Run comparison"]
        V3 -->|"SATURATED (IR>1.0)"| V6["Focus on wire count"]
    end

    subgraph Compare["4. Compare Topologies (veritx compare)"]
        V5 --> C1["veritx compare\n--topos mesh_8x8,torus_8x8"]
        C1 --> C2["Build BookSim config\nfor each topology"]
        C2 --> C3["Run BookSim2\ncycle-accurate sim"]
        C3 --> C4["Parse latency stats\nmean, P50, P99, tail"]
        C4 --> C5["Rank topologies\nWinner + % improvement"]
    end

    subgraph Compile["5. Compile Fabric (veritx compile)"]
        C5 --> P1["Read CompileRequest\nworkload + agents + deps"]
        P1 --> P2["Derive LOCKED params\nrouting, VCs, turns"]
        P2 --> P3["Run BookSim2\non selected topology"]
        P3 --> P4["Verify F1-F8\nformal properties"]
        P4 --> P5["Generate UVM + manifest\nHMAC-signed"]
        P5 --> P6["Estimate area/power/timing\nwith accuracy caveats"]
    end

    subgraph Output["6. Output"]
        P6 --> O1["JSON report\nlatency, area, power, fmax"]
        P6 --> O2["UVM testbench\ntb_noc.sv, assertions.sv"]
        P6 --> O3["Design manifest\nsigned, revision-tracked"]
    end

    subgraph MultiDie["7. Multi-Die (ASTRA-sim, optional)"]
        O1 --> M1["ASTRA-sim\nlibveritx_embed.a"]
        M1 --> M2["BookSim2 as backend\nper-die network"]
        M2 --> M3["UCIe bridges\ndie-to-die comms"]
        M3 --> M4["Multi-die latency\n+ energy"]
    end
```

**Key insight:** The trace file is the single artifact that flows through the entire pipeline. It starts as a vLLM simulation output, gets validated by VeritX, drives BookSim2 cycle-accurate simulation, and produces the final verified fabric.

### 6.1 Trace Format

VeritX uses a simple ASCII trace format. Each line is one packet:

```
cycle src_node dst_node traffic_class packet_size
```

Example:
```
2727 0 0 4 8
2728 4 0 8 8
2729 8 0 12 8
```

**Field definitions:**

| Field | Type | Range | Description |
|-------|------|-------|-------------|
| `cycle` | int | 0–∞ | Injection cycle (when packet enters network) |
| `src_node` | int | 0–N-1 | Source node ID |
| `dst_node` | int | 0–N-1 | Destination node ID |
| `traffic_class` | int | 0–C | Traffic class (0=best effort, 1=latency critical) |
| `packet_size` | int | 1–∞ | Flit count (usually 8 for 64-byte packets) |

**Format rules:**
- Lines starting with `#` are comments
- Fields are space-separated
- Packets must be sorted by cycle (ascending)
- No duplicate cycles for same src/dst pair

### 6.2 Trace Statistics Output

When you run `veritx trace validate`, you get:

```
Format:        VALID
Packets:      95,232
Sources:      16 unique (IDs 0–8)
Classes:      2
Sizes:        [8]
Time range:   [2727, 652210] (649,484 cycles)
Avg IR:       0.146627 pkts/cycle
Self-loops:   0
```

When you run `veritx trace info`, you get burst analysis:

```
Bursts:       48 (gap>100c)
Avg burst:    1984 pkts
Max burst:    1984 pkts
Avg gap:      12773 cycles
Top srcs:     [(0, 49152), (4, 3072), (8, 3072)]
Top dsts:     [(4, 6144), (8, 6144), (12, 6144)]
Profile:      MODERATE (0.1<IR<1.0) — topology may matter
Burst IR:     1.94 pkts/cycle (during max burst)
Burst mode:   INJECTION-LIMITED — NIC injection is bottleneck
```

### 6.3 Trace Sources

| Trace | Packets | Sources | Description |
|-------|---------|---------|-------------|
| `qwen3_serving_16rank.trace` | 95,232 | 16 src/dst | Qwen3 MoE, src0→dst4/8/12 (MoE routing) |
| `llama70b_tp64_ring.trace` | 1,290,240 | 64 src/dst | LLaMA-70B ring allreduce |
| `llama70b_tp64_alltoall.trace` | 1,290,240 | 64 src/dst | LLaMA-70B dense all-to-all |
| `llama_1b_attention.trace` | 258,168 | 64 src/dst | LLaMA-1B attention pattern |
| `qwen3_ring.trace` | 7,962,624 | 16 src/dst | Qwen3 ring topology |
| `qwen3_tree.trace` | 26,192,261 | 16 src/dst | Qwen3 tree topology |

**All traces are REAL** — generated from LLMServingSim with actual LLM serving workloads, not synthetic 0→1 traffic.

### 6.4 Generating New Traces

**From LLMServingSim:**
```bash
cd serving/LLMServingSim
./scripts/docker-sim.sh
# Configure workload in configs/
# Run simulation to generate trace
cp traces/my_trace.trace /path/to/veritx-research/runs/traces/
```

**From Chakra execution traces:**
```bash
veritx trace chakra et_dir/ --nodes 64 --output runs/traces/my_trace.trace
```

**From TrafficModel JSON:**
```bash
veritx trace model models/my_model.json --nodes 64 --output runs/traces/my_trace.trace
```

---

## 7. Architecture

### Full Repository Architecture

```mermaid
flowchart TB
    subgraph User["User Interface"]
        U1["veritx CLI\n17 commands"]
        U2["CompileRequest JSON\n(workload + agents + config)"]
    end

    subgraph VeritX["VeritX DSE Package\ntracks/t3-topology/dse/veritx_dse/"]
        direction TB
        V1["cli.py\n1,686 LOC\nargument parsing"]
        V2["compile_model.py\n1,324 LOC\nE1-E5 data model"]
        V3["pipeline.py\n435 LOC\norchestration"]
        V4["traces.py\n453 LOC\nvalidation + analysis"]
        V5["reports.py\n447 LOC\narea/power/timing"]
        V6["artifact.py\n224 LOC\nHMAC signing"]
        V7["uvm_gen.py\n505 LOC\nUVM testbench"]
        V8["presets.py\n425 LOC\ntopology registry"]
        V9["booksim.py\n415 LOC\nconfig + execution"]
        V10["recommend.py\n347 LOC\nBO engine"]
    end

    subgraph BookSim["third_party/booksim2/src/"]
        B1["booksim\nstandalone binary\ncycle-accurate sim"]
        B2["libveritx_embed.a\nembedding library"]
        B3["veritx_ext.cpp\ntrace replay"]
        B4["veritx_embed.cpp\nASTRA-sim API"]
    end

    subgraph ASTRA["serving/astra-sim/"]
        A1["AstraSim_BookSim2\nmulti-die binary"]
        A2["BookSim2Fabric\nCMake integration"]
        A3["ns-3 backend\ncycle-accurate network"]
    end

    subgraph LLM["serving/LLMServingSim/"]
        L1["Python frontend\nvLLM scheduler"]
        L2["ASTRA-sim backend\nnetwork model"]
        L3["Trace generator\nworkload -> .trace"]
    end

    subgraph Timeloop["third_party/timeloop/"]
        T1["Timeloop\nenergy model"]
        T2["Mapper\nspatial mapping"]
    end

    subgraph Outputs["Generated Outputs"]
        O1["UVM testbench\ntb_noc.sv, seq_lib.sv\nassertions.sv, cov.sv"]
        O2["Design manifest\nHMAC-signed\nrevision-tracked"]
        O3["JSON report\narea, power, timing\nlatency, verification"]
        O4[".anynet files\ntopology definitions"]
    end

    subgraph Traces["Traffic Traces"]
        TR1["qwen3_serving_16rank.trace\n95K pkts, MoE"]
        TR2["llama70b_tp64_ring.trace\n1.29M pkts, ring"]
        TR3["llama70b_tp64_alltoall.trace\n1.29M pkts, dense"]
        TR4["qwen3_tree.trace\n26M pkts, tree"]
    end

    %% Connections
    U1 --> V1
    U2 --> V2
    V1 --> V3
    V2 --> V3
    V3 --> V9
    V4 --> V3
    V5 --> V3
    V6 --> V3
    V7 --> V3
    V8 --> V1
    V10 --> V3

    V9 -->|"runs"| B1
    V9 -->|"reads"| B3
    V2 -->|"derives VC"| V2

    B4 -->|"linked into"| A2
    A2 --> A1
    A1 --> A3

    L3 -->|"produces"| TR1
    L3 -->|"produces"| TR2
    L3 -->|"produces"| TR3
    L3 -->|"produces"| TR4
    TR1 --> V4
    TR2 --> V4
    TR3 --> V4
    TR4 --> V4

    B1 -->|"simulation results"| V3
    T1 -->|"energy estimates"| V5
    T2 -->|"mapping"| T1

    V3 --> O1
    V3 --> O2
    V3 --> O3
    V9 --> O4
```

### High-Level Tool Relationships

```mermaid
flowchart LR
    subgraph Input["Input Layer"]
        I1["LLMServingSim\n(generates traces)"]
        I2["Chakra\n(execution traces)"]
        I3["User\n(CompileRequest)"]
    end

    subgraph Core["VeritX Core\n(tracks/t3-topology/dse/)"]
        C1["veritx trace\nvalidate, info, extract"]
        C2["veritx compare\nmesh vs torus vs GEC"]
        C3["veritx compile\n6-stage pipeline"]
        C4["veritx synthesize\nBO, RHO, GRPO"]
        C5["veritx generate\nUVM testbench"]
    end

    subgraph Sim["Simulation Engines"]
        S1["BookSim2\n(cycle-accurate, single-die)"]
        S2["ASTRA-sim\n(multi-die, UCIe bridges)"]
    end

    subgraph Energy["Energy Model"]
        E1["Timeloop\n(pJ/compute)"]
    end

    subgraph Output["Output Layer"]
        O1["JSON report\narea, power, timing"]
        O2["UVM testbench\nSV files"]
        O3["Design manifest\nHMAC-signed"]
        O4[".anynet files\ntopology definitions"]
    end

    I1 -->|"trace files"| C1
    I2 -->|"execution traces"| C1
    I3 -->|"config"| C3
    C1 --> C2
    C1 --> C3
    C1 --> C4
    C3 --> C5
    C2 --> S1
    C3 --> S1
    C4 --> S1
    C3 --> S2
    S1 --> E1
    C3 --> O1
    C5 --> O2
    C3 --> O3
    C2 --> O4
```

### 7.1 Module Map

```
veritx_dse/                    # Core package (28 modules, 9,338 LOC)
 cli.py                     # 1,686 — 17 CLI commands, thin dispatch
 compile_model.py           # 1,324 — E1-E5 data model, guardrails, VC derivation
 traffic_model.py           #   673 — Phase-aware traffic model
 evaluator.py               #   563 — BookSim runner with caching (legacy)
 uvm_gen.py                 #   505 — UVM testbench generator
 traces.py                  #   453 — Trace validation, analysis, extraction
 reports.py                 #   447 — Area/power/timing with accuracy notes
 pipeline.py                #   435 — Compare, sweep, run orchestration
 chakra_to_dse.py           #   426 — Chakra execution trace converter
 presets.py                 #   425 — Topology + workload preset registry
 booksim.py                 #   415 — BookSim2 config + execution
 recommend.py               #   347 — BO recommendation engine
 roofline.py                #   342 — Roofline model analysis
 artifact.py                #   224 — HMAC signing + design manifests
 dse_to_frontend.py         #   179 — DSE→frontend interface
 commands_trace.py          #   164 — Trace CLI command handlers
 phase_sequencer.py         #   137 — Phase sequencing
 logging.py                 #   106 — Structured logging with Ctx
 objective.py               #    90 — Optimization objective functions
 config.py                  #    88 — Configuration management
 errors.py                  #    78 — Structured error hierarchy
 constants.py               #    72 — Physical constants (7nm, wire delay)
 recovery.py                #    57 — Atomic writes + cleanup
 logger.py                  #    48 — File logger
 trace_to_binary.py         #    38 — Binary trace conversion
 space.py                   #    —  — Design space (legacy)
 run.py                     #    —  — Grid search runner (legacy)
 __init__.py                #    18 — Public API re-exports
```

### 7.2 Module Responsibilities

| Module | Responsibility | Key Classes/Functions |
|--------|---------------|----------------------|
| `cli.py` | CLI dispatch, argument parsing | `main()`, `cmd_compile()`, `cmd_compare()` |
| `compile_model.py` | E1-E5 data model, guardrails | `Workload`, `Agent`, `NocConfig`, `CompileRequest` |
| `traffic_model.py` | Phase-aware traffic model | `detect_phases()`, `PhaseList` |
| `evaluator.py` | BookSim runner | `evaluate_booksim()`, `evaluate_anynet()` |
| `uvm_gen.py` | UVM testbench generation | `generate_uvm()` |
| `traces.py` | Trace validation/analysis | `validate_trace()`, `analyze_bursts()` |
| `reports.py` | Area/power/timing estimates | `generate_report()`, `estimate_area()` |
| `pipeline.py` | Orchestration | `run_compare()`, `run_sweep()` |
| `booksim.py` | BookSim2 config/execution | `build_booksim_config()`, `run_booksim()` |
| `presets.py` | Topology/workload registry | `SWEEP_TOPOS`, `WORKLOAD_PRESETS` |
| `artifact.py` | HMAC signing | `sign_manifest()`, `DesignManifest` |
| `config.py` | Configuration | `get_config()`, env var handling |
| `errors.py` | Error hierarchy | `VeritXError`, `ConfigError`, `SimulationError` |

### 7.3 Data Flow

```mermaid
flowchart TD
    A["User Input
(trace + CompileRequest)"] --> B["cli.py
(17 commands, thin dispatch)"]
    B --> C["pipeline.py
(orchestrate stages)"]
    C --> D["booksim.py
(build config)"]
    D --> E["third_party/booksim2/src/booksim
(cycle-accurate simulation)"]
    E --> F["evaluator.py
(parse results)"]
    F --> G["reports.py
(estimate area/power/timing)"]
    G --> H["artifact.py
(sign manifest)"]
    H --> I["cli.py
(format output)"]
    I --> J["User Output
(JSON report + UVM + manifest)"]
```

---

## 8. Design Principles

### 8.1 Core Principles

1. **Single source of truth** — `presets.py` for topologies, `compile_model.py` for data types. No duplicate definitions.

2. **No globals** — `Ctx` dataclass replaces all module-level state. Every function receives context explicitly.

3. **No `sys.exit()` in commands** — exceptions propagate to `main()`. Commands return results, not exit codes.

4. **Type-enforced guardrails** — `NocConfig` has no field for LOCKED parameters. An override isn't refused at runtime — it's inexpressible in the type system.

5. **TDD** — tests written before implementation. 278 tests, all pass.

6. **Minimal surface area** — 17 CLI commands, each doing one thing well. No command does too much.

7. **Fail fast, fail precise** — configuration errors are caught in seconds with clear messages, not after a ten-minute simulation.

### 8.2 Parameter Tiers

| Tier | Meaning | Examples | User can override? |
|------|---------|----------|-------------------|
|  **LOCKED** | Compiler derives | routing_function, turn_restrictions, vc_map | No — type system prevents it |
|  **GUIDED** | User proposes; engine may adjust | topology_family, radix, link_width | Yes, but engine owns final feasibility |
|  **FREE** | User's call | output_formats, obfuscation_level | Yes, no second-guessing |

---

## 9. Third-Party Dependencies

```mermaid
flowchart TD
    subgraph VeritX["VeritX CLI (tracks/t3-topology/dse/)"]
        V1["veritx compare\nveritx sweep\nveritx compile"]
        V2["veritx generate uvm"]
        V3["veritx trace validate\nveritx trace info"]
    end

    subgraph BookSim["third_party/booksim2/"]
        B1["booksim (standalone binary)"]
        B2["libveritx_embed.a (library)"]
    end

    subgraph ASTRA["serving/astra-sim/"]
        A1["AstraSim_BookSim2\n(multi-die binary)"]
    end

    subgraph LLM["serving/LLMServingSim/"]
        L1["Trace generator\n(from LLM serving)"]
    end

    V1 -->|"runs"| B1
    V2 -->|"reads"| A1
    V3 -->|"validates"| L1
    A1 -->|"uses as backend"| B2
    B1 -->|"synced via sync_to_astra.sh"| A1
    L1 -->|"produces traces"| V3
```

### 9.1 BookSim2

**What:** Cycle-accurate NoC simulator from Stanford. We forked it and added trace replay, multicast, and embedding API.

**Where:** `third_party/booksim2/`

**Why two targets:**
- `booksim` (standalone) — used by `veritx compare`, `veritx sweep`, `veritx compile`
- `libveritx_embed.a` (library) — linked into ASTRA-sim for multi-die simulation

**What we changed:**

| File | Change | Why |
|------|--------|-----|
| `traffic.cpp` | Added `trace()` case to factory | Register `TraceTrafficPattern` in BookSim's pattern factory |
| `flit.hpp/cpp` | Added `mcast`, `mcast_copies` fields | Multicast support for MECS/GEC topologies |
| `veritx_embed.*` | New embedding API | Allow ASTRA-sim to drive BookSim as a fabric model |
| `veritx_ext.*` | Trace replay extension | Read trace files and inject packets at correct cycles |
| `Makefile` | Added `lib` target, excluded `veritx_embed.o` from standalone | Build both targets without symbol conflicts |

### 9.2 ASTRA-sim

**What:** Multi-die network simulator from Georgia Tech. Models die-to-die communication via UCIe bridges.

**Where:** `serving/astra-sim/`

**Uses:** BookSim2 as its network backend (synced via `sync_to_astra.sh`).

### 9.3 LLMServingSim

**What:** Cycle-level LLM serving simulator from KAIST (ISPASS 2026). Generates realistic traffic traces.

**Where:** `serving/LLMServingSim/`

**Produces:** Traffic traces that VeritX consumes.

---

## 10. BookSim2 Deep Dive

### 10.1 What BookSim2 Does

BookSim2 is a cycle-accurate network-on-chip simulator. It models:
- Routers (input buffers, VC allocation, switch allocation, crossbar)
- Links (credit-based flow control)
- Traffic patterns (uniform, transpose, hotspot, trace)
- Routing functions (dimension-order, adaptive, minimal)

### 10.2 Our Trace Replay Extension

BookSim2's original traffic patterns are synthetic (uniform random, transpose, etc.). Our extension (`veritx_ext.*`) adds:

1. **TraceTrafficPattern** — reads a trace file and injects packets at the correct cycles
2. **Sequential injection** — O(1) lookup: packets sorted by cycle, inject when `current_cycle >= packet.cycle`
3. **Lazy flit creation** — flits created on injection, not upfront (saves memory)

### 10.3 Embedding API (veritx_embed)

For ASTRA-sim integration, BookSim2 needs to be callable as a library:

```cpp
// Create an embedded traffic manager
EmbedTM* tm = CreateEmbeddedTM("config.cfg");

// Inject packets from external host
tm->InjectUnicast(src, dst, size, packet_id);

// Check if packets have completed
bool done = tm->HasRetired(node_id, packet_id);

// Step the simulation
tm->Tick();
```

### 10.4 Common BookSim Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `trace() not found` | Built from wrong directory | Build from `third_party/booksim2/src/` |
| `duplicate symbol` | veritx_embed.o linked with main.o | Use `make lib` instead of `make` for embedding |
| `segmentation fault` | Trace file missing or corrupt | Run `veritx trace validate` first |
| `timeout` | Simulation too long | Check trace time range, reduce `sample_period` |

---

## 11. ASTRA-sim Multi-Die Simulation

### 11.1 What ASTRA-sim Does

ASTRA-sim models **multi-die** (chiplet) systems:
- Multiple dies connected via UCIe bridges
- Each die has its own NoC (can be BookSim2)
- Die-to-die communication via bridge models
- Support for different topologies per die

### 11.2 Build

```bash
# 1. Sync BookSim2 source
third_party/booksim2/sync_to_astra.sh

# 2. Build ASTRA-sim
cd serving/astra-sim/build/astra_booksim2
./build.sh

# 3. Verify
ls -la ../../astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2
```

### 11.3 Configuration

ASTRA-sim needs four JSON configs:

| Config | Purpose | Example |
|--------|---------|---------|
| Network | Topology, link bandwidth | `examples/network/ns3/sample_16nodes_2D.json` |
| System | Compute collectives | `examples/system/native_collectives/Ring_4chunks.json` |
| Workload | Application workload | `examples/workload/microbenchmarks/` |
| Remote Memory | Memory hierarchy | `examples/remote_memory/analytical/` |

### 11.4 Run

```bash
serving/astra-sim/astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2 \
    --workload-configuration=<workload.json> \
    --network-configuration=<network.json> \
    --system-configuration=<system.json> \
    --remote-memory-configuration=<memory.json>
```

### 11.5 Common Errors

| Error | Fix |
|-------|-----|
| `veritx_embed.hpp: No such file` | Run `third_party/booksim2/sync_to_astra.sh` |
| `PER_NODE_MEMORY_EXPANSION` abort | Set `num-devices` in memory config |
| Binary hangs at stdin | ASTRA-sim waits for `exit` command |
| `yaml-cpp` not found | `sudo apt install libyaml-cpp-dev` |
| `cmake version too old` | Need cmake 3.22+: `pip install cmake` |

---

## 12. LLMServingSim Traffic Generation

### 12.1 What LLMServingSim Does

LLMServingSim is a cycle-level simulator for LLM serving infrastructure from KAIST (ISPASS 2026). It:
- Mirrors vLLM's continuous-batching scheduler in Python
- Uses ASTRA-sim C++ as network backend
- Drives from per-hardware latency data captured by a vLLM profiler
- Supports heterogeneous accelerators, disaggregated memory (CPU/CXL/PIM)

### 12.2 Build

```mermaid
flowchart LR
    A["LLMServingSim\nSource code"] --> B{"Docker?"}
    B -->|"Yes (recommended)"| C["docker-sim.sh\nLaunches container"]
    B -->|"No"| D["pip install + compile.sh\nManual install"]
    C --> E["ASTRA-sim backend\n(inside container)"]
    D --> E
    E --> F["Ready to generate traces"]
```

```bash
cd serving/LLMServingSim

# Option 1: Docker (recommended)
./scripts/docker-sim.sh

# Option 2: Manual install
pip install -r requirements.txt
./scripts/compile.sh
```

### 12.3 Generate Traces

```bash
# 1. Configure workload in configs/
# 2. Run simulation
./serving/run.sh

# 3. Output in traces/ directory
ls traces/
# run_1786643546936153_195056/

# 4. Copy to VeritX
cp traces/my_trace.trace /path/to/veritx-research/runs/traces/
```

### 12.4 Trace Provenance

All traces in `runs/traces/` are generated from real LLM serving workloads:

| Trace | Source | |
|-------|--------|-------|
| `qwen3_serving_16rank.trace` | LLMServingSim Qwen3-30B-A3B, 16 NPU |  Real MoE routing |
| `llama70b_tp64_*.trace` | LLMServingSim LLaMA-70B, 64 NPU |  Real dense traffic |
| `llama_1b_attention.trace` | LLMServingSim LLaMA-1B, 64 NPU |  Real attention |

---

## 13. E1-E5 Data Model

### 13.1 Entities

| Entity | Name | What it holds | PRD Section |
|--------|------|---------------|-------------|
| **E1** | `Workload` | Model family, parallelism, trace binding | §5 |
| **E2** | `Requirements` | Per-class latency/BW bounds | §5.3 |
| **E3** | `Agents` | Typed nodes with attributes (width, protocol) | §4.1–4.2 |
| **E4** | `DependencyGraph` | Blocking/ordering graph → VC derivation | §11.3 |
| **E5** | `NocConfig` | GUIDED + FREE knobs only (no LOCKED) | §11.2 |

### 13.2 Entity Relationships

```mermaid
flowchart TD
    CR["CompileRequest"] --> W["E1: Workload\nmodel_family, tp, ep, dp\ntrace_path"]
    CR --> R["E2: Requirements[]\nqos_class\nlatency_ceiling_cycles\nbinding"]
    CR --> AG["E3: Agents[]\nkind, count\ndata_width, protocol"]
    CR --> DEP["E4: Dependencies[]\nsource, target\nkind (blocking/ordering)"]
    CR --> NC["E5: NocConfig\ntopology_family [GUIDED]\nradix [GUIDED]\nlink_width [GUIDED]\n---\nNO routing_function\nNO turn_restrictions\nNO vc_map\n(all LOCKED, derived)"]
    DEP --> VD["VC Derivation\n(blocks -> routing fn + VC count)"]
```

```
CompileRequest
 Workload (E1)
    model_family: str
    tp, ep, dp: int
    trace_path: str
 Requirements[] (E2)
    qos_class: str
    latency_ceiling_cycles: int
    binding: bool
 Agents[] (E3)
    kind: AgentKind
    count: int
    data_width: int
    protocol: str
 Dependencies[] (E4)
    source: str
    target: str
    kind: DepKind
 NocConfig (E5)
     topology_family: TopologyFamily
     radix: Optional[int]
     link_width: Optional[int]
    (NO routing_function, turn_restrictions, vc_map — LOCKED)
```

### 13.3 VC Derivation Rules

The dependency graph (E4) determines the VC structure:

- **No blocking cycles** → `dim_order` routing, 1 VC
- **1 blocking cycle** → `dor` routing, 2 VCs, west_first + north_last turns
- **2+ blocking cycles** → `min_adapt` routing, N+1 VCs, no turn restrictions

---

## 14. CompileRequest Format

### 14.1 Example

```json
{
  "workload": {
    "model_family": "mixture_of_experts",
    "model_name": "Qwen3-30B-A3B",
    "tp": 16, "ep": 8, "dp": 1,
    "serving_mode": "decode_heavy",
    "precision": "fp8",
    "trace_path": "runs/traces/qwen3_serving_16rank.trace"
  },
  "requirements": [
    {"qos_class": "latency_critical", "latency_ceiling_cycles": 5000, "binding": true}
  ],
  "agents": [
    {"kind": "compute_tile", "count": 16, "data_width": 256, "protocol": "AXI"},
    {"kind": "hbm_controller", "count": 4}
  ],
  "dependencies": [
    {"source": "expert_alltoall", "target": "expert_reduce", "kind": "blocking"}
  ],
  "noc_config": {"topology_family": "mesh"}
}
```

### 14.2 Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `workload.model_family` | string | yes | `dense_transformer`, `mixture_of_experts`, `diffusion`, `cnn` |
| `workload.model_name` | string | no | Human-readable name |
| `workload.tp` | int | yes | Tensor parallelism degree |
| `workload.ep` | int | no | Expert parallelism (MoE only) |
| `workload.dp` | int | no | Data parallelism degree |
| `workload.serving_mode` | string | no | `decode_heavy`, `prefill_heavy`, `mixed` |
| `workload.precision` | string | no | `fp16`, `fp8`, `int8` |
| `workload.trace_path` | string | yes | Path to traffic trace file |
| `requirements[].qos_class` | string | yes | `latency_critical`, `bandwidth`, `best_effort` |
| `requirements[].latency_ceiling_cycles` | int | yes | Max acceptable latency in cycles |
| `requirements[].binding` | bool | yes | If true, requirement must be met |
| `requirements[].source` | string | no | Source phase name |
| `requirements[].target` | string | no | Target phase name |
| `agents[].kind` | string | yes | `compute_tile`, `hbm_controller`, `nic`, `peripheral`, `ucie_port` |
| `agents[].count` | int | yes | Number of instances |
| `agents[].data_width` | int | no | Interface width in bits (default: 256) |
| `agents[].protocol` | string | no | `AXI`, `CHI`, `custom_streaming` |
| `dependencies[].source` | string | yes | Phase name (e.g. `expert_alltoall`) |
| `dependencies[].target` | string | yes | Phase name (e.g. `expert_reduce`) |
| `dependencies[].kind` | string | yes | `blocking`, `ordering`, `independent` |
| `noc_config.topology_family` | string | no | `mesh`, `concentrated_mesh`, `torus` |
| `noc_config.radix` | int | no | Router radix (GUIDED, engine may adjust) |
| `noc_config.link_width` | int | no | Link width in bits (GUIDED) |

---

## 15. Compile Pipeline Stages

The compile pipeline has 6 stages:

```mermaid
flowchart LR
    S1["1⃣ Validate\nGuardrails\nRequired fields\nDep graph"] --> S2["2⃣ Derive\nRouting fn\nVC count\nTurn restrictions"]
    S2 --> S3["3⃣ Simulate\nBookSim2\nCycle-accurate\nLatency stats"]
    S3 --> S4["4⃣ Verify\n F1-F8 checks\n Deadlock free\n Liveness"]
    S4 --> S5["5⃣ Generate\n UVM testbench\n Manifest\n HMAC signing"]
    S5 --> S6["6⃣ Report\n Area\n Power\n Timing"]
```

### Stage 1: Validate
- Parse CompileRequest JSON
- Check all required fields
- Run guardrail checks (no LOCKED fields in NocConfig)
- Validate dependency graph (no cycles in non-blocking edges)

### Stage 2: Derive
- Build dependency graph from E4
- Detect blocking cycles
- Derive routing function (LOCKED)
- Derive VC count (LOCKED)
- Derive turn restrictions (LOCKED)

### Stage 3: Simulate
- Build BookSim2 config from derived parameters
- Run cycle-accurate simulation on trace
- Collect latency statistics (mean, P50, P99, tail)
- Collect throughput (packets/cycle)

### Stage 4: Verify
- Check F1-F8 formal properties
- F1: Deadlock freedom (no cyclic channel dependency)
- F2: Liveness (every packet completes)
- F3: Packet conservation (no loss, no duplication)
- F4: Ordering (per-VC in-order delivery)
- F5: Flow control (credit-based, no overflow)
- F6: Routing correctness (minimal/adaptive paths)
- F7: QoS isolation (no starvation) — pending
- F8: Timeout (bounded latency)

### Stage 5: Generate
- Generate UVM testbench (tb_noc.sv, seq_lib.sv, assertions.sv, cov.sv)
- Create design manifest (design_id, revision, signature)
- Sign manifest with HMAC-SHA256

### Stage 6: Report
- Estimate area (routers, links, NIUs)
- Estimate power (dynamic + leakage)
- Estimate timing (Fmax, critical path)
- Estimate energy (per-bit, per-hop)
- Attach accuracy caveats to each metric

---

## 16. VC Derivation Algorithm

The VC derivation algorithm takes the dependency graph and produces a valid VC assignment:

```python
def resolve_dependencies(agents, deps) -> VcAssignment:
    g = build_graph(d for d in deps if d.blocking)
    cycles = find_cycles(g)

    if not cycles:
        return VcAssignment.minimal()      # no separation needed

    # Each cycle needs >=1 member on a distinct VC to break it.
    # Choose the member whose separation costs least buffering.
    assignment = VcAssignment.minimal()
    for cyc in cycles:
        victim = min(cyc, key=lambda d: separation_cost(d, agents))
        assignment.separate(victim)

    if assignment.vc_count > PLANE_C_MAX_VC:
        raise ConfigError('D1', cycles=cycles,
            remedy='declare non-blocking dependencies where the '
                   'protocol permits, or reduce agent coupling')
    return assignment
```

**Key insight:** The VC structure is **derived**, not chosen. This is why VC structure sits in the LOCKED tier — a hand VC assignment can satisfy every bandwidth and latency requirement and still deadlock in the field.

```mermaid
flowchart TD
    A["Dependency Graph (E4)"] --> B["Build graph from blocking edges"]
    B --> C["Find cycles"]
    C --> D{"Cycles found?"}
    D -->|"No cycles"| E["Return minimal assignment\n1 VC, dim_order routing"]
    D -->|"1+ cycles"| F["For each cycle:\nFind victim (least costly to separate)"]
    F --> G["Separate victim onto distinct VC"]
    G --> H{"vc_count > MAX?"}
    H -->|"No"| I["Return assignment\nN+1 VCs, min_adapt routing"]
    H -->|"Yes"| J[" ConfigError D1\nRemedy: reduce coupling"]
```

---

## 17. Verification Properties (F1-F8)

| Check | Property | Description | Status |
|-------|----------|-------------|--------|
| F1 | **Deadlock Freedom** | No cyclic channel dependency exists |  Implemented |
| F2 | **Liveness** | Every injected packet eventually completes |  Implemented |
| F3 | **Packet Conservation** | No packet is lost or duplicated |  Implemented |
| F4 | **Ordering** | Per-VC in-order delivery is maintained |  Implemented |
| F5 | **Flow Control** | Credit-based flow control prevents overflow |  Implemented |
| F6 | **Routing Correctness** | Packets take minimal or adaptive paths |  Implemented |
| F7 | **QoS Isolation** | No starvation between traffic classes |  Pending |
| F8 | **Timeout** | Bounded latency per packet |  Implemented |

**How verification works:**

```mermaid
flowchart TD
    A["Simulation Output\n(trace + latency stats)"] --> B["F1: Deadlock Freedom\nNo cyclic channel dependency"]
    A --> C["F2: Liveness\nEvery packet completes"]
    A --> D["F3: Conservation\nNo loss, no duplication"]
    A --> E["F4: Ordering\nPer-VC in-order delivery"]
    A --> F["F5: Flow Control\nCredit-based, no overflow"]
    A --> G["F6: Routing\nMinimal/adaptive paths"]
    A --> H["F7: QoS Isolation\nNo starvation"]
    A --> I["F8: Timeout\nBounded latency"]
    B --> J{"All PASS?"}
    C --> J
    D --> J
    E --> J
    F --> J
    G --> J
    H --> J
    I --> J
    J -->|"Yes"| K[" Verified\nFabric is correct"]
    J -->|"No"| L[" Counter-example\nWhich check failed + why"]
```

---

## 18. Output Format & Accuracy Caveats

### 18.1 Output JSON

Every `veritx compile` produces:

```json
{
  "area": {"total_mm2": 0.272, "routers_mm2": 0.1, "links_mm2": 0.038},
  "power": {"dynamic_w": 0.060, "leakage_w": 0.010, "total_w": 0.070},
  "timing": {"max_freq_mhz": 1965, "critical_path_ps": 381.8},
  "energy": {"per_bit_pj": 0.630},
  "simulation": {"latency": 1850.64},
  "vc_assignment": {"routing_function": "dim_order", "vc_count": 1},
  "verification": {"ok": true, "checks": [...], "errors": []},
  "artifacts": [{"kind": "manifest", "uri": "...", "checksum": "..."}],
  "manifest": {"design_id": "...", "revision": 1, "signature": "..."}
}
```

### 18.2 Accuracy Caveats

| Metric | Trustworthiness | Notes |
|--------|----------------|-------|
| **BookSim latency** |  Trustworthy | Cycle-accurate, deterministic replay |
| **Area** |  ±30% relative | Good for A vs B comparison, not absolute |
| **Power** |  Conservative | No thermal, no PVT corners, no leakage model |
| **Fmax** |  Upper bound | Real Fmax needs STA with actual placement |
| **Energy** |  Order-of-magnitude | 0.15 pJ/bit/hop reference, not silicon-accurate |

**Bottom line:** BookSim latency is the anchor metric. Area/power/timing are relative estimates for topology comparison, not sign-off numbers.

---

## 19. Built-in Topologies

| Name | Type | Edges | Routing | Notes |
|------|------|-------|---------|-------|
| `mesh_4x4` | 2D mesh | 24 | dim_order | Small baseline |
| `mesh_8x8` | 2D mesh | 112 | min_adapt | Standard 64-node |
| `torus_8x8` | 2D torus | 128 | dim_order | Wrap-around links, -15% avg hops |
| `flatfly_64` | FlatButterfly | 96 | ran_min | Non-blocking, high radix |
| `gec_express_k8` | GEC express | 448 | dor | 7 express channels per node |
| `gec_mecs_k8` | GEC MECS | 168 | dor | 1 express, 7 multicast dests |
| `gec_mesh_k8` | GEC mesh | 112 | dor | No express (degraded GEC) |

### Topology Selection Guide

| Workload | Best Topology | Why |
|----------|---------------|-----|
| MoE decode (sparse) | mesh_8x8 or gec_express | Short flows, wire efficiency matters |
| Dense attention (global) | torus_8x8 or flatfly_64 | Long flows, wrap-around helps |
| Ring allreduce | mesh_8x8 | Nearest-neighbor, mesh is optimal |
| All-to-all (saturated) | flatfly_64 | Non-blocking, highest bisection BW |

```mermaid
flowchart TD
    A{"Traffic Pattern?"} -->|"MoE decode\n(sparse, bursty)"| B{"Wire budget?"}
    A -->|"Dense attention\n(global, long flows)"| C{"Need wrap-around?"}
    A -->|"Ring allreduce\n(nearest-neighbor)"| D["mesh_8x8\n128 edges, dim_order"]
    A -->|"All-to-all\n(saturated, dense)"| E["flatfly_64\n96 edges, ran_min"]
    B -->|"Limited (<150)"| F["mesh_8x8\n128 edges"]
    B -->|"Generous (>400)"| G["gec_express_k8\n448 edges, dor"]
    C -->|"Yes"| H["torus_8x8\n128 edges, wrap-around"]
    C -->|"No"| D
```

---

## 20. Built-in Workload Presets

| Name | Model | Description | Agents |
|------|-------|-------------|--------|
| `qwen3_moe_16npu` | Qwen3-30B-A3B | MoE decode, TP=16 EP=8 | compute×16, hbm×4 |
| `llama70b_tp64` | LLaMA-70B | Dense TP=64 ring allreduce | compute×64, hbm×8 |
| `llama1b_tp64` | LLaMA-1B | Dense TP=64 attention | compute×64, hbm×4 |
| `dense_64npu` | Generic dense | 64-NPU mesh | compute×64, hbm×8 |
| `moe_8npu` | Generic MoE | 8-NPU concentrated mesh | compute×8, hbm×2 |
| `hpc_wrf128` | WRF-128 | HPC MPI weather simulation | compute×128 |
| `automotive_adas` | ADAS-fusion | LiDAR + camera, 16 NPU | compute×16, nic×2 |
| `moe_64npu` | MoE 64N | MoE 64-NPU mesh | compute×64, hbm×16 |
| `diffusion_64npu` | sdxl-64n | Diffusion image generation | compute×64, hbm×8 |

---

## 21. Extending VeritX

VeritX is designed for extensibility. Every component can be extended without modifying core code.

**Extension points:**
- [22. Adding a New Topology](#22-adding-a-new-topology)
- [23. Adding a New Workload Preset](#23-adding-a-new-workload-preset)
- [24. Adding a New Agent Kind](#24-adding-a-new-agent-kind)
- [25. Adding a New Dependency Kind](#25-adding-a-new-dependency-kind)
- [26. Adding a New Engine Stage](#26-adding-a-new-engine-stage)
- [27. Adding a New Report Type](#27-adding-a-new-report-type)
- [28. Adding a New CLI Command](#28-adding-a-new-cli-command)
- [29. Adding a New Verification Check](#29-adding-a-new-verification-check)

---

## 22. Adding a New Topology

1. Add a `Topology` to `SWEEP_TOPOS` in `presets.py`:

```python
Topology(
    name="my_custom_8x8",
    backend="mesh",          # BookSim topology type
    routing="min_adapt",     # BookSim routing function
    params={"k": 8, "n": 2}, # BookSim config overrides
    needs_noc_latency_zero=False,
)
```

2. That's it. All commands (`compare`, `sweep`, `compile`) automatically discover it.

**Available BookSim backends:**
- `mesh` — 2D mesh (kncube)
- `torus` — 2D torus with wrap-around
- `flatfly` — FlatButterfly
- `tree` — Fat tree
- `dragonfly` — Dragonfly
- `fattree` — Fat tree
- `anynet` — Custom topology from .anynet file

**Available routing functions:**
- `dim_order` — Dimension-order routing (deterministic)
- `min_adapt` — Minimal adaptive routing
- `dor` — Dimension-order routing (alias)
- `ran_min` — Random minimal routing
- `adaptive` — Full adaptive routing

---

## 23. Adding a New Workload Preset

1. Add to `WORKLOAD_PRESETS` in `presets.py`:

```python
"my_model": {
    "desc": "My model description",
    "workload": {
        "model_family": "dense_transformer",
        "tp": 8, "dp": 1,
        "trace_path": "runs/traces/my_model.trace",
    },
    "agents": [
        {"kind": "compute_tile", "count": 8},
        {"kind": "hbm_controller", "count": 2},
    ],
    "requirements": [],
    "dependencies": [],
},
```

2. Verify with `veritx compile examples/my_model.json`

---

## 24. Adding a New Agent Kind

Add to `AgentKind` enum in `compile_model.py`:

```python
class AgentKind(Enum):
    COMPUTE_TILE = "compute_tile"
    HBM_CONTROLLER = "hbm_controller"
    NIC = "nic"
    PERIPHERAL = "peripheral"
    UCIE_PORT = "ucie_port"
    MY_NEW_KIND = "my_new_kind"  # ← add here
```

Then update `AGENT_DEFAULTS` in `presets.py` with default attributes for the new kind.

---

## 25. Adding a New Dependency Kind

Add to `DepKind` enum in `compile_model.py`:

```python
class DepKind(Enum):
    BLOCKING = "blocking"
    ORDERING = "ordering"
    INDEPENDENT = "independent"
    MY_NEW_KIND = "my_new_kind"  # ← add here
```

If the new kind affects VC derivation, update `resolve_dependencies()` in `compile_model.py`.

---

## 26. Adding a New Engine Stage

The compile pipeline has 6 stages. To add a 7th:

1. Create `veritx_dse/my_stage.py`:
```python
def run_my_stage(request: CompileRequest, prev_result: dict) -> dict:
    """Stage 7: My new stage."""
    # ... implementation ...
    return {"my_result": value}
```

2. Wire into `cmd_compile()` in `cli.py`:
```python
# Step 7/7: My new stage
print(f"  Step 7/7: MyStage       ", end="", flush=True)
stage_result = run_my_stage(request, prev_result)
print(f" result={stage_result['my_result']}")
```

3. Add tests in `tests/test_compile_model.py`
4. Update the stage list in `docs/PRD-CHECKLIST.md`

---

## 27. Adding a New Report Type

1. Add estimation function to `reports.py`:
```python
def estimate_my_metric(request, sim_result) -> dict:
    """Estimate my custom metric."""
    value = compute_something(request, sim_result)
    return {"my_metric": value, "confidence": "relative"}
```

2. Wire into `generate_report()` return dict:
```python
report["my_metric"] = estimate_my_metric(request, sim_result)
```

3. Add accuracy note:
```python
report["accuracy_notes"]["my_metric"] = "Relative comparison only"
```

4. Test in `tests/test_prd_gaps.py`

---

## 28. Adding a New CLI Command

1. Add handler function in `cli.py`:

```python
def cmd_my_new_command(ctx: Ctx, args):
    """Handler for 'veritx my-new-command'."""
    result = my_module.do_something(args.input)
    if not result.ok:
        fail(ctx, f"Failed: {result.errors}")
        return
    ok(ctx, f"Result: {result.value}")
    output(ctx, result.to_dict())
```

2. Register in `main()` argparse:

```python
p_my = sub.add_parser("my-new-command", help="Short description")
p_my.add_argument("input", help="Input file")
p_my.set_defaults(handler=cmd_my_new_command)
```

3. Add tests in `tests/test_cli.py`

---

## 29. Adding a New Verification Check

1. Add check function in `compile_model.py`:
```python
def check_my_property(trace_output, vc_assignment) -> VerifResult:
    """F9: My new verification property."""
    ok = verify_something(trace_output, vc_assignment)
    return VerifResult(
        name="F9_my_property",
        passed=ok,
        message="Description of what was checked"
    )
```

2. Wire into `run_verify()`:
```python
checks.append(check_my_property(trace_output, vc_assignment))
```

3. Add tests in `tests/test_compile_model.py`

---

## 30. Testing

### 30.1 Running Tests

```bash
# Full suite (278 tests, ~2 minutes)
python3 -m pytest tests/ -v

# Specific modules
python3 -m pytest tests/test_compile_model.py -v    # E1-E5, guardrails
python3 -m pytest tests/test_prd_gaps.py -v         # Reports, artifacts
python3 -m pytest tests/test_integration.py -v      # End-to-end CLI
python3 -m pytest tests/test_entry_point.py -v      # Package install, CLI
python3 -m pytest tests/test_api_contract.py -v     # API contracts

# Quick smoke test (no BookSim needed)
python3 -m pytest tests/test_compile_model.py tests/test_prd_gaps.py -v

# With coverage
python3 -m pytest tests/ --cov=veritx_dse --cov-report=term-missing
```

### 30.2 Test Organization

| Test File | Tests | What It Covers |
|-----------|-------|----------------|
| `test_compile_model.py` | 50 | E1-E5 data model, guardrails, VC derivation |
| `test_prd_gaps.py` | 38 | Reports, artifacts, manifests, presets |
| `test_cli_modules.py` | 33 | CLI trace commands, topology, compare |
| `test_integration.py` | 21 | End-to-end CLI pipeline |
| `test_sprint1.py` | 19 | Result/Artifact entities, Verify/Generate |
| `test_entry_point.py` | 23 | pyproject.toml, CLI invocation |
| `test_uvm_gen.py` | 11 | UVM testbench generation |
| `test_compile_uvm.py` | 14 | UVM in compile pipeline |
| `test_missing_coverage.py` | 14 | commands_trace, logger, recovery |
| `test_cli.py` | 10 | BookSim mock, CLI dispatch |
| `test_reports.py` | 9 | Area/power/timing models |
| `test_api_contract.py` | 11 | API contract validation |

### 30.3 Test Organization Diagram

```mermaid
flowchart TD
    subgraph Unit["Unit Tests (257 tests, ~3s)"]
        U1["test_compile_model.py\n50 tests: E1-E5, guardrails"]
        U2["test_prd_gaps.py\n38 tests: reports, artifacts"]
        U3["test_cli_modules.py\n33 tests: trace, topology"]
        U4["test_sprint1.py\n19 tests: Result/Artifact"]
        U5["test_entry_point.py\n23 tests: package install"]
        U6["test_uvm_gen.py\n11 tests: UVM generation"]
        U7["Other test files\n82 tests: coverage, contracts"]
    end

    subgraph Integration["Integration Tests (21 tests, ~90s)"]
        I1["test_integration.py\nFull CLI pipeline\nReal BookSim binary"]
    end

    Unit --> I1
    I1 -->|"All pass"| OK["Ready to commit"]
    I1 -->|"Any fail"| FIX["Fix and re-run"]
```

### 30.4 Test Philosophy

- **Unit tests** mock BookSim -- they test Python logic only
- **Integration tests** invoke the real BookSim binary -- they test the full pipeline
- **All tests must pass** before any commit
- **TDD** -- write tests first, then implement

---

## 31. Debugging & Troubleshooting

### Quick Diagnostic Flowchart

```mermaid
flowchart TD
    A{"veritx --help works?"} -->|"No"| B["pip install -e .\n(from dse/ directory)"]
    A -->|"Yes"| C{"veritx trace validate works?"}
    C -->|"No"| D{"Error says what?"}
    D -->|"Path traversal"| E["Use absolute path\n(no .. in path)"]
    D -->|"File not found"| F["Check trace path\nls the file first"]
    C -->|"Yes"| G{"veritx compile works?"}
    G -->|"No"| H{"Error says what?"}
    H -->|"BookSim binary not found"| I["cd third_party/booksim2/src\nmake -j$(nproc)"]
    H -->|"trace() not valid"| J["Built from wrong dir\nRebuild from third_party/booksim2/src/"]
    H -->|"CompileRequest not found"| K["Check examples/ directory\nUse absolute path"]
    G -->|"Yes"| L{"veritx compare works?"}
    L -->|"No"| M{"Timeout?"}
    M -->|"Yes"| N["Increase --timeout\nor reduce trace size"]
    M -->|"No"| O["Check stderr for details"]
    L -->|"Yes"| P["All working"]
```

### 31.1 "BookSim binary not found"

```bash
# Build BookSim2
cd third_party/booksim2/src && make -j$(nproc)

# Verify binary exists
ls -la third_party/booksim2/src/booksim
```

### 31.2 "trace() not a valid traffic pattern"

This means BookSim wasn't built with our trace replay extension.

**Cause:** Built from `serving/astra-sim/extern/.../src/` instead of `third_party/booksim2/src/`.

**Fix:** Always build from `third_party/booksim2/src/`.

### 31.3 Path traversal errors

VeritX blocks `..` in paths for security.

```bash
# Wrong
veritx trace validate ../../runs/traces/qwen3_serving_16rank.trace

# Right
veritx trace validate /full/path/to/runs/traces/qwen3_serving_16rank.trace
```

### 31.4 "REPO" path resolution bug

The `constants.py` file computes REPO by going 5 levels up from `veritx_dse/constants.py`.

```python
# veritx_dse/constants.py
REPO = Path(__file__).resolve().parent.parent.parent.parent.parent  # 5 levels up = repo root
```

If you move the `dse/` directory, update this path.

### 31.5 Tests pass but CLI fails

Tests mock BookSim, so they pass even if BookSim isn't built. Always run an integration test:

```bash
veritx compile examples/qwen3_moe_16npu.json
```

### 31.6 ASTRA-sim build fails

1. Sync BookSim2 first: `third_party/booksim2/sync_to_astra.sh`
2. Check cmake version: `cmake --version` (need 3.22+)
3. Install yaml-cpp: `sudo apt install libyaml-cpp-dev`

### 31.7 Large trace files (>100MB)

The repo contains traces up to 440MB. If disk space is a concern:
- Small traces (<10MB): committed directly
- Large traces: consider Git LFS (`git lfs track "runs/traces/*.trace"`)

### 31.8 /tmp is RAM-backed

**Never** use /tmp for installs, venvs, or model downloads. /tmp is tmpfs (RAM-backed, ~7GB). Use `/home/datavex/` (198GB free on real disk).

---

## 32. Common Pitfalls

### 32.1 Building BookSim from the wrong directory

**Problem:** You edited `third_party/booksim2/src/traffic.cpp` but built from `serving/astra-sim/extern/.../src/`.

**Solution:** Always build from `third_party/booksim2/src/`. Use the sync script to copy changes to ASTRA-sim.

### 32.2 Using relative paths

**Problem:** `veritx compile examples/qwen3_moe_16npu.json` fails when run from a different directory.

**Solution:** Use absolute paths, or run from `tracks/t3-topology/dse/`.

### 32.3 Mock vs real BookSim

**Problem:** Unit tests pass but `veritx compile` fails.

**Explanation:** Tests mock BookSim. Only `test_integration.py` actually invokes the binary.

**Solution:** Run `python3 -m pytest tests/test_integration.py -v` after any BookSim changes.

### 32.4 Trace format confusion

**Problem:** `veritx compare` gives different results than expected.

**Check:** Run `veritx trace validate` first to verify the trace is well-formed.

### 32.5 /tmp is RAM-backed

**Problem:** Large builds or traces fill up /tmp (only ~7GB RAM-backed).

**Solution:** Never use /tmp for installs, venvs, or model downloads. Use `/home/datavex/` (198GB free).

---

## 33. Performance Benchmarks

### 33.1 BookSim Simulation Speed

| Trace | Packets | Time | Speed |
|-------|---------|------|-------|
| qwen3_serving_16rank | 95K | ~10s | 9.5K pkts/s |
| llama70b_tp64_ring | 1.29M | ~120s | 10.7K pkts/s |
| qwen3_tree | 26.19M | ~300s | 87.3K pkts/s |

### 33.2 Compile Pipeline Speed

| Preset | Stages | Total Time |
|--------|--------|------------|
| qwen3_moe_16npu | 6/6 | ~15s |
| llama1b_tp64 | 6/6 | ~10s |
| llama70b_tp64 | 6/6 | ~120s |

### 33.3 Test Suite Speed

| Test Category | Count | Time |
|---------------|-------|------|
| Unit tests | 257 | ~3s |
| Integration tests | 21 | ~90s |
| **Total** | **278** | **~95s** |

---

## 34. Research Findings

### 34.1 Topology Comparison Results

**Qwen3 MoE (95K packets, 16 NPU):**

| Topology | Latency | vs mesh | Edges |
|----------|---------|---------|-------|
| mesh_8x8 | 1863c | baseline | 128 |
| torus_8x8 | 1891c | +1.5% | 128 |
| grpo_best | 1843c | -1.1% | 111 |
| gec_express | 1836c | -1.4% | 448 |

**Key finding:** grpo_best (111 edges) beats mesh (128 edges) by 1.1% with 17 fewer wires — wire-efficient.

### 34.2 MoE Burst Pattern

MoE traffic has characteristic bursts:
- Average IR: 0.146 pkts/cycle (sparse)
- Burst IR: 1.94 pkts/cycle (13× average)
- Topology matters most during bursts, not on average

### 34.3 Torus vs Mesh

Torus beats mesh only where path length is the binding constraint:
- Attention traffic: torus -32% vs mesh (wrap-around helps)
- MoE serving: torus +1.5% vs mesh (no benefit, extra wires wasted)

---

## 35. Comparison with Other Tools

| Tool | What it does | VeritX advantage |
|------|-------------|------------------|
| BookSim2 | NoC simulator | VeritX adds trace replay, CLI, compile pipeline |
| ASTRA-sim | Multi-die simulator | VeritX adds topology DSE, verification, reporting |
| Timeloop | Energy model | VeritX integrates with Timeloop for energy estimates |
| Arteris FlexNoC | Commercial NoC IP | VeritX is open, extensible, ML-workload-focused |
| Noxim | SystemC NoC sim | VeritX uses BookSim2 (faster, more topologies) |
| SCALE-Sim | Systolic array sim | Different layer (compute vs network) |

---

## 36. Hardware Requirements

### Minimum

| Resource | Requirement |
|----------|-------------|
| CPU | 2+ cores |
| RAM | 4GB |
| Disk | 2GB free |
| Python | 3.10+ |

### Recommended

| Resource | Requirement |
|----------|-------------|
| CPU | 8+ cores (for parallel BookSim runs) |
| RAM | 16GB (for large traces) |
| Disk | 10GB free |
| GPU | Not required (BookSim is CPU-only) |

### For ASTRA-sim

| Resource | Requirement |
|----------|-------------|
| RAM | 14GB+ (ASTRA-sim is memory-hungry) |
| Disk | 5GB free |

---

## 37. Environment Setup

### 37.1 Fresh Install

```bash
# Clone repo
git clone https://internal-devrepo.datavex.ai/anmol/veritx-research.git
cd veritx-research

# Install VeritX
cd tracks/t3-topology/dse
pip install -e .

# Build BookSim2
cd ../../third_party/booksim2/src
make -j$(nproc)

# Verify
veritx --help
```

### 37.2 Docker (Alternative)

```bash
# Build Docker image
docker build -t veritx .

# Run
docker run -it veritx veritx --help
```

### 37.3 Python Virtual Environment

```bash
cd tracks/t3-topology/dse
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest  # for testing
```

---

## 38. CI/CD Integration

### 38.1 GitLab CI

The repo has `.gitlab-ci.yml` configured:

```yaml
stages:
  - test
  - build
  - deploy

test:
  stage: test
  script:
    - cd tracks/t3-topology/dse
    - pip install -e .
    - python3 -m pytest tests/ -v
```

### 38.2 GitHub Actions

```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - run: cd tracks/t3-topology/dse && pip install -e .
      - run: cd tracks/t3-topology/dse && python3 -m pytest tests/ -v
```

---

## 39. Security Considerations

### 39.1 Path Traversal

VeritX blocks `..` in paths to prevent directory traversal attacks:

```python
def _resolve_path(path: str) -> Path:
    """Resolve path and block traversal."""
    p = Path(path).resolve()
    if ".." in str(p):
        raise SecurityError(f"Path traversal not allowed: {path}")
    return p
```

### 39.2 Input Validation

All CompileRequest fields are validated:
- Required fields checked
- Type checking enforced
- Enum values validated
- Numeric ranges checked

### 39.3 Manifest Signing

Design manifests are signed with HMAC-SHA256:

```python
def sign_manifest(manifest: dict, secret: str) -> str:
    """Sign manifest with HMAC-SHA256."""
    payload = json.dumps(manifest, sort_keys=True)
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
```

### 39.4 No Arbitrary Code Execution

VeritX never evaluates user-provided code. All configurations are parsed as data, not executed.

---

## 40. API Reference

### 40.1 Python API

```python
from veritx_dse import (
    CompileRequest,
    Workload,
    Agent,
    NocConfig,
    run_compile,
    run_compare,
    run_sweep,
)
```

### 40.2 CLI API

```bash
veritx <command> [options]
```

All commands support:
- `--json` — JSON output
- `--output <file>` — Write to file
- `--verbose` — Verbose output
- `--quiet` — Suppress output
- `--seed <int>` — Random seed
- `--log <file>` — Log to file

### 40.3 Programmatic Usage

```python
from veritx_dse.compile_model import CompileRequest, Workload, Agent

# Create a request
request = CompileRequest(
    workload=Workload(
        model_family="mixture_of_experts",
        tp=16, ep=8,
        trace_path="runs/traces/qwen3.trace"
    ),
    agents=[
        Agent(kind="compute_tile", count=16),
        Agent(kind="hbm_controller", count=4),
    ],
    requirements=[],
    dependencies=[],
    noc_config=NocConfig(topology_family="mesh"),
)

# Run compile pipeline
result = run_compile(request)
print(result["simulation"]["latency"])  # 1850.64
```

---

## 41. Configuration Reference

### 41.1 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VERITX_LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `VERITX_BOOKSIM_BIN` | auto | Path to BookSim binary |
| `VERITX_TIMEOUT` | `300` | Simulation timeout in seconds |
| `VERITX_SEED` | `42` | Default random seed |

### 41.2 pyproject.toml

```toml
[project]
name = "veritx-dse"
version = "0.3.0"
requires-python = ">=3.10"

[project.scripts]
veritx = "veritx_dse.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

---

## 42. Glossary

| Term | Definition |
|------|------------|
| **NoC** | Network-on-Chip — the interconnect fabric between compute tiles |
| **VC** | Virtual Channel — logical channel within a physical link |
| **MoE** | Mixture-of-Experts — sparse transformer architecture |
| **TP** | Tensor Parallelism — splitting tensors across NPUs |
| **EP** | Expert Parallelism — distributing experts across NPUs |
| **DP** | Data Parallelism — replicating model across NPUs |
| **UCIe** | Universal Chiplet Interconnect Express — die-to-die standard |
| **GEC** | Graceful Express Channel — express links for hot traffic |
| **MECS** | Multicast Express Channel — one-to-many express links |
| **FLIT** | Flow Control Unit — smallest unit of data transfer |
| **DOR** | Dimension-Order Routing — deterministic routing |
| **BO** | Bayesian Optimization — black-box optimization |
| **RHO** | Random Hill Climbing — local search algorithm |
| **GRPO** | Group Relative Policy Optimization — population-based search |
| **UVM** | Universal Verification Methodology — SystemVerilog test framework |
| **HMAC** | Hash-based Message Authentication Code — signing mechanism |

---

## 43. Changelog

### v0.3.0 (2026-08-31)
- Full compile pipeline (6 stages)
- UVM testbench generation
- Design manifest signing
- Sensitivity analysis
- Memory hierarchy correction
- 278 tests, all pass

### v0.2.0 (2026-08-29)
- Trace replay in BookSim2
- GEC/MECS topology support
- Pareto front analysis
- Binary trace format

### v0.1.0 (2026-08-25)
- Initial CLI
- Basic compare/sweep
- BookSim2 fork

---

## 44. Roadmap

### Phase 1: Engine Core (P1) — ~80% complete
- [x] E1-E5 data model
- [x] Guardrail enforcement
- [x] VC derivation
- [x] BookSim2 integration
- [x] Compile pipeline (6 stages)

### Phase 2: Generate Path (P2) — ~30% complete
- [x] UVM testbench generation
- [x] Design manifest signing
- [ ] RTL generation
- [ ] Behavioral model export

### Phase 3: Views & Reports (P3) — ~0%
- [ ] Interactive topology editor
- [ ] Live latency heatmap
- [ ] Physical floorplan view

### Phase 4: Interactive Sim (P4) — ~0%
- [ ] In-browser simulator
- [ ] Tweak-and-replot
- [ ] Real-time comparison

### Phase 5: Full Editing (P5) — ~0%
- [ ] Live editing in every view
- [ ] Background re-validation
- [ ] Collaborative editing

---

## 45. Known Limitations

1. **No RTL generation** — VeritX produces UVM testbenches and manifests, but not synthesizable RTL
2. **No interactive UI** — CLI-only, no web interface
3. **Area/power estimates are approximate** — ±30% for area, order-of-magnitude for energy
4. **F7 QoS isolation not implemented** — pending
5. **Large traces (>100MB) slow** — BookSim processes them sequentially
6. **No GPU acceleration** — BookSim is CPU-only
7. **Single-die only** — multi-die requires ASTRA-sim (separate build)
8. **No thermal modeling** — power estimates don't include thermal effects

---

## 46. FAQ

### Q: How accurate are the latency numbers?
**A:** BookSim latency is cycle-accurate and deterministic. For the same trace and topology, you get the same result every time.

### Q: Can I use VeritX for non-AI workloads?
**A:** Yes. VeritX is workload-agnostic — it simulates any traffic trace. The presets are AI-focused, but you can create custom traces for HPC, automotive, or any other domain.

### Q: How do I add a new topology that's not in BookSim?
**A:** Use `anynet` format. Create a `.anynet` file describing your topology graph, then use `--anynet my_topology.anynet` in compare/sweep.

### Q: Why are my test results different from the README?
**A:** BookSim is deterministic, but different seeds produce different results. Use `--seeds 3` for statistical confidence, or `--seed 42` for reproducibility.

### Q: Can I run this on Windows?
**A:** Not directly. VeritX uses Linux-specific paths. Use WSL2 or a Docker container.

### Q: How do I generate traces from my own model?
**A:** Use LLMServingSim (see [Section 12](#12-llmservingsim-traffic-generation)) or write a trace generator that outputs the ASCII format (see [Section 6.1](#61-trace-format)).

---

## 47. License

Proprietary — VeritX Research Team

---

## 48. Contributing

### 48.1 Development Workflow

1. Write tests first (`tests/test_my_feature.py`)
2. Implement in `veritx_dse/my_module.py`
3. Wire into `cli.py` command handler
4. Run `python3 -m pytest tests/ -v` — all 278 must pass
5. Update this README if adding public API
6. If editing BookSim2, run `third_party/booksim2/sync_to_astra.sh`

### 48.2 Code Style

- Type hints on all public functions
- Docstrings on all public classes
- No globals (use `Ctx` dataclass)
- No `sys.exit()` in commands
- Tests for all new functionality

### 48.3 Pull Request Checklist

- [ ] All 278 tests pass
- [ ] New functionality has tests
- [ ] README updated if public API changed
- [ ] BookSim changes synced to ASTRA-sim
- [ ] No hardcoded paths
- [ ] No new globals

---

## 49. References

1. **BookSim2** — Jiang et al., "A Detailed and Flexible Cycle-Accurate Network-on-Chip Simulator," ISPASS 2013
2. **ASTRA-sim** — Mallappa et al., "Astra-sim: Enabling Co-design of Network-on-Chip and Collective Algorithms for DNN Training," ISPASS 2024
3. **LLMServingSim** — Cho et al., "LLMServingSim 2.0: A Unified Simulator for Heterogeneous and Disaggregated LLM Serving Infrastructure," ISPASS 2026
4. **Timeloop** — Shao et al., "Timeloop: A Systematic Approach to DNN Accelerator Evaluation," ISPASS 2017
5. **GEC/MECS** — SrotaSemi internal research (2026)

---

## 50. Support

- **Issues:** https://internal-devrepo.datavex.ai/anmol/veritx-research/-/issues
- **Docs:** This README + `docs/` directory
- **Examples:** `examples/` directory

---

*Last updated: 2026-08-31*
