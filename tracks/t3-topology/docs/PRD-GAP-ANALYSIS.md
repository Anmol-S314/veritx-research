# PRD Gap Analysis — Srota Studio vs VeritX Current State

**Date:** 2026-08-30  
**PRD:** SSM-PRD-STUDIO-001 (Srota Studio v0.1)  
**Codebase:** veritx-research (tracks/t3-topology/dse/)

---

## Executive Summary

The PRD describes a **browser-based NoC IP product** with a canvas UI, live simulator, and export bundle. Our codebase is a **CLI-based DSE research tool**. The gap is real but the core engine — which the PRD explicitly says is "the company" — maps well to what we've built. The UI, export, and verification layers are the main missing pieces.

**What we have that the PRD needs (engine core):**
- Topology synthesis (BO, RHO, GRPO, MCTS)
- Cycle-accurate simulation (BookSim2 integration)
- Trace-based traffic model (real LLM workloads)
- RTL generation + certification framework
- Pareto multi-objective search

**What the PRD needs that we don't have (product layer):**
- Browser UI (React canvas, inspector, live estimates)
- API/Job queue (FastAPI + Celery/Ray)
- Artifact store + signing
- VC derivation from dependency graph
- F1–F8 formal verification proofs
- Physical floorplan view

---

## Section-by-Section Analysis

### §1 Purpose & Scope

| PRD Requirement | Our Status | Gap |
|-----------------|------------|-----|
| Browser-based tool | CLI only | **CRITICAL** — no UI at all |
| "Intent-to-fabric compiler" | CLI pipeline (trace → synth → eval → cert) | **PARTIAL** — works but no structured CompileRequest |
| "Configures correctly the things a customer should not" | Guardrails in `build_config()` (no classes param, k/n ordering) | **PARTIAL** — hardcoded safety, not type-system enforced |

### §3 UI Design Principles

| Principle | Our Status | Gap |
|-----------|------------|-----|
| Clean by default | N/A (CLI) | **N/A** — needs UI first |
| Derive, don't ask | `detect_trace_stats()` auto-detects IR/span | ✅ Engine does this |
| Live consequence | `veritx results` shows cached results | **PARTIAL** — not live, not interactive |
| Editable everywhere | N/A (CLI) | **N/A** |
| Guardrails visible | `Topology.needs_noc_latency_zero` flag | **PARTIAL** — not user-facing |

### §4 Inputs — Describing the System

| PRD Requirement | Our Status | Gap |
|-----------------|------------|-----|
| Agent placement | Not modeled — we work with fixed N-node networks | **CRITICAL** — no agent concept |
| Per-agent attributes (data_width, addr_width, etc.) | Not in our model | **CRITICAL** — missing E3 |
| Address map | Not modeled | **CRITICAL** — missing |
| Srota IP knobs (topology_family, radix, etc.) | Partially in `Topology` dataclass + `_SWEEP_TOPOS` | **PARTIAL** — no GUIDED/LOCKED tiers |
| LOCKED params derived, not editable | `routing_function` hardcoded per topology | ✅ We do this (routing is LOCKED by convention) |

### §5 Workload Scenario Capture

| PRD Requirement | Our Status | Gap |
|-----------------|------------|-----|
| Level A: Model & serving | Partially — we have Qwen3 MoE, LLaMA70B dense | **PARTIAL** — hardcoded presets, not user-configurable |
| Level B: Phase & dataflow | `traffic_model.py` Phase detection works | ✅ We have this |
| Level C: Per-class traffic profile | `detect_trace_stats()` + `TraceInfo` | ✅ We have this |
| Auto-lowering between levels | Manual — user provides .trace files | **GAP** — need auto-generation from Level A |
| Built-in reference workloads | 3 presets in `DENSE_PRESETS` | **PARTIAL** — need more (MoE decode, dense prefill, etc.) |

### §6 Output Views

| PRD Requirement | Our Status | Gap |
|-----------------|------------|-----|
| Logical/topological view | `veritx compare` table output | **PARTIAL** — text table, not interactive graph |
| Structural (block) view | Not implemented | **CRITICAL** — no block-level visualization |
| Physical view (floorplan) | Not implemented | **CRITICAL** — no floorplan |
| Cross-linked views | N/A | **N/A** |

### §7 Reports & Estimates

| PRD Requirement | Our Status | Gap |
|-----------------|------------|-----|
| Area report | Timeloop + Accelergy integration exists (runs/mot_htree/) | **PARTIAL** — not wired into CLI |
| Power report | Energy model exists (hops × 64B × 0.15 pJ/B/hop) | **PARTIAL** — calculation only, not validated |
| Timing report | Not implemented | **GAP** |
| Report cross-linking | N/A | **N/A** |
| Design revision + guardrail hash | `manifest.json` in run dir | **PARTIAL** — no guardrail hash |

### §8 In-Tool Simulator

| PRD Requirement | Our Status | Gap |
|-----------------|------------|-----|
| Cycle-approximate NoC model | BookSim2 (cycle-accurate, not approximate) | ✅ We have BETTER than required |
| Packet latency (mean, P50, P99) | `compute_percentiles()` in evaluator.py | ✅ We have this |
| Throughput (accepted vs offered) | `sim_type=throughput` mode | ✅ We have this |
| Energy per-bit | Partially in evaluator.py | **PARTIAL** — not wired |
| Interactive tweak & replot | CLI only — no interactive mode | **CRITICAL** — no live UI |
| Injection rate sweep | `--sensitivity` flag on compare | ✅ We have this |

### §9 Export & Downloads

| PRD Requirement | Our Status | Gap |
|-----------------|------------|-----|
| RTL (SystemVerilog) | `gen_rtl.py` + `gen_rtl_htree.py` | ✅ We have this |
| Behavioral models (C/SystemC) | Not generated | **GAP** |
| Verification suite (UVM) | Verilator testbenches exist | **PARTIAL** — not UVM |
| Reports (PDF/HTML/CSV) | `veritx report` LaTeX + JSON | **PARTIAL** — no PDF/HTML |
| Design manifest (JSON + signature) | `manifest.json` without signature | **PARTIAL** — no signing |
| Artifact bundling | No bundling | **GAP** |

### §10 Stack Overview

| PRD Requirement | Our Status | Gap |
|-----------------|------------|-----|
| React + TypeScript frontend | Not started | **CRITICAL** |
| Python FastAPI backend | Not started | **CRITICAL** |
| Postgres + S3 + Redis | Not started | **CRITICAL** |
| Kubernetes infrastructure | Not started | **CRITICAL** |

### §11 The Srota Engine

| PRD Requirement | Our Status | Gap |
|-----------------|------------|-----|
| E1 Workload dataclass | `PhaseList` / `Phase` in traffic_model.py | ✅ We have this |
| E2 Requirements | Not formalized | **GAP** — no Requirement dataclass |
| E3 Agents | Not modeled | **CRITICAL** — no Agent dataclass |
| E4 Dependencies (blocking graph) | Not modeled | **CRITICAL** — no Dependency graph |
| E5 NocConfig (GUIDED/FREE only) | `Topology` dataclass (partial) | **PARTIAL** — no tier system |
| Guardrail in type system | `build_config()` hardcoded checks | **PARTIAL** — runtime, not compile-time |
| VC derivation from dependency graph | Not implemented | **CRITICAL** — §11.3 key differentiator |
| Engine stages (Ingest→Synth→Sim→Opt→Verify→Gen) | Pipeline exists but informal | **PARTIAL** — no formal stage boundaries |

### §12 Backend Schema

| PRD Requirement | Our Status | Gap |
|-----------------|------------|-----|
| Design revision (immutable) | `manifest.json` per run | **PARTIAL** — not immutable revisions |
| Agent entity | Not modeled | **CRITICAL** |
| Job entity | Not modeled — CLI runs synchronously | **CRITICAL** |
| Result entity | JSON files in runs/booksim/ | **PARTIAL** — not structured |
| Artifact entity | Not modeled | **CRITICAL** |
| Guardrail hash | Not implemented | **GAP** |

### §13 The Generate Pipeline

| PRD Requirement | Our Status | Gap |
|-----------------|------------|-----|
| Submit → Validate → Simulate → Optimize → Verify → Sign → Return | `veritx run` does trace→synth→eval→cert | **PARTIAL** — missing Validate, Optimize, Sign steps |
| WebSocket progress streaming | CLI progress logging (`_log()`) | **PARTIAL** — not WebSocket |
| Fail fast with precise errors | `BookSimError` exceptions | ✅ We have this |

### §14 IP Protection & Trust

| PRD Requirement | Our Status | Gap |
|-----------------|------------|-----|
| Engine server-side only | CLI runs locally | **GAP** — needs deployment model |
| Per-tenant isolation | Single-user CLI | **GAP** |
| Artifact signing | Not implemented | **GAP** |
| Obfuscation levels | Not implemented | **GAP** |

### §15 Build Order

| Phase | PRD Says | Our Status |
|-------|----------|------------|
| P1 Engine core | Fabric Compiler + simulation core | ✅ **DONE** — booksim.py + bo_synthesizer.py + traffic_model.py |
| P2 Generate path | API + job queue + RTL generation | ❌ **NOT STARTED** |
| P3 Views & reports | Logical/structural/physical views | ❌ **NOT STARTED** |
| P4 Interactive sim | In-tool simulator with tweak-and-replot | ❌ **NOT STARTED** |
| P5 Full editing | Live editing with background re-validation | ❌ **NOT STARTED** |

---

## What We Have That PRD Doesn't Explicitly Mention

| Capability | PRD Gap | Value |
|------------|---------|-------|
| BookSim2 GEC/MECS topology support | Not in PRD topology families | Unique — express cube search |
| RHO/GRPO iterative synthesis | Not in PRD search methods | Novel — better than flat MCTS |
| Multi-workload Pareto | Not in PRD optimizer | Strong paper contribution |
| ASTRA-sim BookSim2 backend | Not in PRD simulator stack | Real Chakra ET support |
| RTL certification (144/144 PASS) | PRD mentions F1–F8 but doesn't have implementation | We're ahead |
| Burst analysis + sensitivity | Not in PRD traffic model | Honest traffic characterization |
| Trace validation (veritx trace validate) | Not in PRD | Pre-flight safety |
| Dense vs MoE crossover analysis | Not in PRD | Research contribution |

---

## Priority Gap List (ordered by PRD impact)

### CRITICAL (blocks product vision)
1. **Agent model (E3)** — no concept of compute tiles, HBM controllers, NICs
2. **Dependency graph (E4)** — no blocking/ordering model for VC derivation
3. **VC derivation from dependencies** — PRD §11.3 key differentiator
4. **Browser UI** — React canvas, inspector, live estimates
5. **API/Job queue** — FastAPI + Celery for async generation

### HIGH (blocks paper-quality output)
6. **CompileRequest dataclass** — formal E1–E5 input model
7. **NocConfig with GUIDED/LOCKED/FREE tiers** — type-system enforced guardrails
8. **Guardrail hash** — reproducibility + audit trail
9. **UVM verification suite** — not just Verilator testbenches
10. **Artifact signing** — IP protection for exported RTL

### MEDIUM (blocks full PRD coverage)
11. **Physical floorplan view** — placement-aware visualization
12. **Area/power/timing reports** — wired from Timeloop + Accelergy
13. **On-prem deployment model** — single-tenant engine
14. **Built-in reference workloads** — more than 3 presets
15. **Auto-lowering Level A → Level C** — model description to traffic matrix

### LOW (nice-to-have)
16. **Behavioral models (C/SystemC)** — not just RTL
17. **PDF/HTML report export** — beyond LaTeX
18. **Interactive simulator in UI** — tweak-and-replot
19. **Obfuscation levels** — IP protection for delivered netlist
20. **Licensing model in-tool** — per-design/per-seat gating

---

## Recommended Next Steps

1. **Start with P1 completion:** Formalize E1–E5 dataclasses, add VC derivation, add guardrail hash
2. **Build the API layer:** FastAPI wrapping our CLI commands as async jobs
3. **Minimal UI:** React + React-Flow for topology visualization (P3)
4. **Don't try to build everything:** The PRD is aspirational — focus on what makes the paper strong first
