# PRD Gap Analysis — Section-by-Section Deep Dive

**Date:** 2026-08-30  
**PRD:** SSM-PRD-STUDIO-001 (Srota Studio v0.1)  
**Codebase:** veritx-research (tracks/t3-topology/dse/)

---

## §1 Purpose & Scope

> "A browser-based tool that lets a chip design team describe the system they are building and receive, in return, a complete Srota Network-on-Chip (NoC) fabric tailored to that system: its topology, its RTL, its models, its verification suite, and every report needed to sign it off."

> "The client states what they need; the Srota engine decides how the fabric meets it, applying the SrotaSemi methodology under the hood."

> "It is an intent-to-fabric compiler whose value is that it configures correctly the things a customer should not have to reason about."

**What we have:**
- CLI tool (`veritx`) that takes a trace file and produces topology recommendations
- BookSim2 cycle-accurate simulation
- RTL generation (`gen_rtl.py`, `gen_rtl_htree.py`)
- RTL certification (144/144 PASS on mesh)

**What's missing:**
- **No browser UI** — everything is CLI
- **No "CompileRequest"** — the user passes individual CLI flags, not a structured intent object
- **No "customer" concept** — single-user research tool, not multi-tenant product
- **The "intent-to-fabric compiler" framing is aspirational** — we're a DSE research tool that happens to produce some of these outputs

**Honest assessment:** §1 describes a product. We have a research prototype that covers ~30% of what the product needs. The engine core (simulation + synthesis + certification) is real. The product layer (UI + API + customer workflow) doesn't exist.

---

## §2 How the Tool Works — One Page

> "Three stages: the client expresses intent through the UI; the Srota engine ingests, synthesizes, simulates, verifies, and generates; the client receives a set of views, reports, and downloadable collateral."

**What we have:**
```
trace → synthesize → evaluate → certify → done
```
This maps to the PRD's three stages:
1. "Client expresses intent" → User provides a trace file (partial — no UI, no structured input)
2. "Engine ingests, synthesizes, simulates, verifies, generates" → `veritx run` does trace → BO → BookSim → cert (mostly there)
3. "Client receives views, reports, downloadable collateral" → JSON results + LaTeX table (partial — no views, no downloadable bundle)

**What's missing:**
- Stage 1 is a CLI flag, not a UI
- Stage 3 is a JSON file, not a view/report/bundle
- No "views" concept at all — we output tables

**Honest assessment:** The pipeline shape is right. The inputs and outputs are too low-level for the PRD's vision.

---

## §3 UI Design Principles

### "Clean by default — One primary object on screen at a time"

**Our state:** We have no screen. We have terminal output.

### "Derive, don't ask — The tool never requests a value it can compute"

**What we have:**
- `detect_trace_stats()` auto-detects IR, max_cycle, num_classes from trace
- `build_config()` auto-derives `sample_period` from trace span
- `build_config()` auto-derives `num_vcs` for GEC MECS (needs >= d+1)
- `_lookup_topo()` resolves topology by name or .anynet file

**What's missing:**
- No auto-derivation of routing from topology (we hardcode `min_adapt` for mesh)
- No auto-derivation of VC count from dependency graph
- No auto-derivation of link width from bandwidth requirements

**Honest assessment:** We do some derivation (trace stats, sample_period, VC count for GEC). But the PRD wants EVERY correctness parameter derived. We hardcode routing and VC mapping.

### "Live consequence — Every edit updates live estimates within seconds"

**Our state:** `veritx compare` takes 9-30 seconds per topology. Not live.

### "Editable everywhere"

**Our state:** N/A — CLI.

### "Guardrails, visible — Parameters shown with tier badge: LOCKED / GUIDED / FREE"

**What we have:**
- `Topology.needs_noc_latency_zero` is a boolean flag (like a crude LOCKED indicator)
- `build_config()` never passes `classes` to BookSim (implicit guardrail)
- `build_config()` enforces `k/n` before `topology=` (implicit guardrail)

**What's missing:**
- No formal tier system (LOCKED/GUIDED/FREE)
- No way for users to see which parameters are derived vs. their choice
- No type-system enforcement — guardrails are runtime checks, not compile-time

**Honest assessment:** We have implicit guardrails (hardcoded safety in `build_config()`). The PRD wants explicit, type-system-enforced tiers. This is a significant gap.

---

## §4 Inputs — Describing the System

### §4.1 Agents (nodes) and their counts

> "Compute tile: 64–1024+, HBM controller: 4–16, NIC: 1–8, Peripheral: as needed, UCIe port: 0–full edge"

**Our state:** We model `n_nodes` as an integer. There is no concept of agent types. A 64-node network is just "64 nodes" — we don't distinguish compute tiles from HBM controllers from NICs.

**What's missing:** The entire Agent concept. This is fundamental — the PRD's world model starts with "what agents exist and what do they need."

**Honest assessment:** **CRITICAL GAP.** Our abstraction is N nodes. The PRD's abstraction is typed agents with attributes. This changes the entire input model.

### §4.2 Per-agent attributes

> "data_width, addr_width, clock, power domain, reset, protocol, sideband"

**Our state:** Not modeled at all. BookSim config has `packet_size = 8` (hardcoded). No concept of agent-level attributes.

**Honest assessment:** **CRITICAL GAP.** These attributes determine the fabric's physical interface. We don't model them.

### §4.3 Address map & configuration

> "Interactive editor — add ranges, assign to targets, see overlaps flagged live. Import — CSV / IP-XACT / JSON upload."

**Our state:** Not modeled. We don't have address maps. BookSim uses `network_file` for .anynet topology — no address decode.

**Honest assessment:** **CRITICAL GAP.** The address map drives routing and decode configuration. We skip this entirely.

### §4.4 Srota NoC IP configuration inputs

> "topology_family (GUIDED), radix/concentration (GUIDED), arbitration (GUIDED), RCU (GUIDED), link_width (GUIDED), output_models (FREE), obfuscation (FREE), routing/turn restrictions/VC map (LOCKED)"

**Our state:**

| PRD Knob | Our Equivalent | Tier | Status |
|----------|---------------|------|--------|
| topology_family | `Topology.backend` (mesh/torus/flatfly/gec) | Hardcoded | **PARTIAL** — we have 4 families, PRD wants more |
| radix/concentration | `Topology.params["k"]` + `Topology.params["n"]` | Implicit | **PARTIAL** — not exposed as a knob |
| arbitration | `BASE_PARAMS["vc_allocator"]` = "islip" | Hardcoded | **MISSING** — not a DSE axis |
| RCU | Not modeled | N/A | **MISSING** — no in-network reduction |
| link_width | Not modeled | N/A | **MISSING** — BookSim has fixed flit width |
| output_models | N/A | N/A | **MISSING** — no output format selection |
| obfuscation | N/A | N/A | **MISSING** — no IP protection |
| routing | `Topology.routing` (min_adapt/dim_order/dor) | Hardcoded per topo | **LOCKED by convention** — user can't change it |
| turn restrictions | Not modeled | N/A | **MISSING** |
| VC map | Not modeled | N/A | **MISSING** — VC count is hardcoded |

**Honest assessment:** We have 2 of 8 knobs (topology family + radix). The PRD wants 8 knobs with formal tiers. The LOCKED tier (routing, turn restrictions, VC map) is partially enforced by convention but not by type system.

---

## §5 Workload Scenario Capture

### "Three descending levels of abstraction"

> "Level A — Model & serving: Model family, shape, parallelism, serving mode"

**Our state:** We have `DENSE_PRESETS` with 3 entries (llama70b_ring, llama70b_a2a, qwen3_moe). Each preset specifies `desc`, `topos`, `anynet`, `routing_default`. But there's no "model family" or "parallelism" concept — just trace files.

**What's missing:**
- No `ModelFamily` enum (dense_transformer, MoE, diffusion, CNN)
- No shape parameters (parameter_count, sequence_length, batch_size, precision)
- No parallelism model (TP, PP, EP, DP degrees)
- No serving mode (prefill-heavy, decode-heavy, mixed)

**Honest assessment:** **PARTIAL.** We have the output of Level A (the trace file) but not Level A itself. The user must already have a trace — they can't describe "Llama-70B TP=64 decode" and get a trace.

### "Level B — Phase & dataflow"

> "Phases, tensor→agent mapping, collective operations, skew traffic"

**Our state:**
- `traffic_model.py` Phase detection works — divides trace into phases by IR changes
- `Phase` dataclass has: name, entries, matrix, mean_rate, peak_rate, burstiness
- `PhaseList` has: phases, n_nodes, total_flits, total_cycles
- `bottleneck_objective()` optimizes for worst phase

**What's missing:**
- No "tensor→agent mapping" — we don't track which tensor lives where
- No "collective operations" as first-class objects (allreduce, allgather, etc.)
- No "skew traffic" model (MoE hot-expert skew)

**Honest assessment:** **PARTIAL.** We have phase detection and per-phase evaluation. But we don't model the dataflow (which tensor → which agent) or collectives explicitly.

### "Level C — Per-class traffic profile"

> "Spatial pattern, temporal shape, QoS class, requirement, dependencies"

**Our state:**
- `TraceInfo` has: ir, burst_ir, burst_mode, top_srcs, top_dsts, profile
- `validate_trace()` checks self-loops, class distribution, sizes
- `extract_uniform()` can redistribute traffic

**What's missing:**
- No "QoS class" concept (latency-critical / bandwidth / best-effort)
- No "requirement" (latency ceiling or BW floor per class)
- No "dependencies" (ordering/blocking relationships between classes)

**Honest assessment:** **PARTIAL.** We have spatial and temporal characterization. We're missing QoS classes, requirements, and dependency tracking.

---

## §6 Output Views

### "Three linked views of the same design"

> "Logical/topological view — The graph the user reasons about: agents, routers, links, MECS express channels, QoS islands and RCU placement."

**Our state:** `veritx compare` outputs a text table. `veritx results` shows cached JSON. No graph visualization.

**What's missing:** The entire visualization layer. No React-Flow canvas, no graph rendering, no interactive editing.

### "Structural (block) view"

> "The block-level composition: SR-D routers, NIUs, MECS drop cells, RCUs, QoS islands and UCIe bridges."

**Our state:** Not modeled. We don't have block-level composition. The RTL has router.sv + nic.sv + mesh.sv — but no MECS, RCU, or QoS blocks.

### "Physical view (floorplan)"

> "A placement-aware view for floor planning: cell footprints, HBM/UCIe edge strips, link lengths."

**Our state:** Not modeled. No physical awareness at all.

**Honest assessment for §6:** **CRITICAL GAP.** The entire output visualization layer is missing. This is expected — we're a CLI tool, not a web app. But the PRD makes this the primary user interface.

---

## §7 Reports & Estimates

> "Area — Per-block and total fabric area; Power — Dynamic + leakage by block; Timing — Fmax per path class"

**Our state:**
- **Area:** Timeloop + Accelergy integration exists in `runs/mot_htree/` — 14.284 pJ per hop. But not wired into CLI.
- **Power:** Energy model exists: `hops × 64B × 0.15 pJ/B/hop`. But it's a calculation, not a validated measurement.
- **Timing:** Not implemented. No Fmax estimation, no critical path analysis.

**What's missing:**
- No area report generation
- No power report generation (just a raw calculation)
- No timing report at all
- No "live estimates" — these would need to be computed in < 2 seconds for the PRD's "live consequence" principle

**Honest assessment:** **PARTIAL.** We have the raw ingredients (Timeloop energy, hop counts) but not the report generation or the live-estimate speed.

---

## §8 In-Tool Simulator

> "A cycle-approximate NoC model (Booksim-class) driven by the traffic matrix. Reports: packet latency distribution, throughput, energy, area context."

**Our state:**
- BookSim2 is cycle-**accurate** (better than "cycle-approximate" the PRD asks for)
- `compute_percentiles()` gives P50/P90/P95/P99/P99.9
- `--sensitivity` flag sweeps injection rates
- `run_booksim_windowed()` handles long traces
- `run_booksim_phases()` does per-phase evaluation

**What's missing:**
- Not interactive — runs take 9-30 seconds, not milliseconds
- No "tweak & replot" — no way to change parameters and see results update live
- No "traffic mix" adjustment — can't shift class balance interactively
- No Pareto visualization in the tool

**Honest assessment:** **STRONG on simulation, WEAK on interactivity.** We have the best simulation engine (BookSim2 cycle-accurate). But it's not interactive enough for the PRD's "tweak & replot" requirement. The PRD asks for cycle-approximate for speed — we have cycle-accurate for correctness but it's too slow for live interaction.

---

## §9 Export & Downloads

> "RTL (SystemVerilog), Behavioral models (C/SystemC), Verification suite (UVM), Reports, Estimates, Design manifest (JSON + signature)"

**Our state:**
- **RTL:** `gen_rtl.py` + `gen_rtl_htree.py` generate SystemVerilog. PASS.
- **Behavioral models:** Not generated. No C/SystemC output.
- **Verification suite:** Verilator testbenches exist (tb_minimal.sv, tb_formal.cpp). Not UVM.
- **Reports:** `veritx report` generates LaTeX. No PDF/HTML.
- **Estimates:** JSON output. No structured estimate bundle.
- **Design manifest:** `manifest.json` exists but no signature, no guardrail hash.

**What's missing:**
- No C/SystemC behavioral models
- No UVM verification suite (we have Verilator, not UVM)
- No PDF/HTML report export
- No artifact signing
- No guardrail hash in manifest
- No bundled export (everything is separate files)

**Honest assessment:** **PARTIAL.** We have RTL generation and basic certification. The PRD wants a signed, revision-stamped export bundle. We have loose files.

---

## §10 Stack Overview

> "React + TypeScript frontend, Python FastAPI backend, Postgres + S3 + Redis + Celery, Kubernetes"

**Our state:** Python CLI package (`veritx_dse`). No frontend. No API. No database. No job queue. No containerization.

**Honest assessment:** **CRITICAL GAP.** The entire product infrastructure doesn't exist. This is expected — we're a research prototype, not a product. But the PRD is a product spec.

---

## §11 The Srota Engine

### §11.1 Compile data model (E1–E5)

| Entity | PRD Description | Our Equivalent | Gap |
|--------|----------------|----------------|-----|
| E1 Workload | Models, phases, parallelism, traffic classes | `PhaseList` (phases + n_nodes) | **PARTIAL** — missing model_family, parallelism, serving_mode |
| E2 Requirements | Per-class latency/BW bounds, binding flag | Not modeled | **MISSING** |
| E3 Agents | Initiators and targets with 9 attributes | `n_nodes` (integer) | **MISSING** — no agent concept |
| E4 Dependencies | Blocking/ordering graph + VC derivation | Not modeled | **MISSING** — no dependency graph |
| E5 NocConfig | GUIDED + FREE knobs only | `Topology` dataclass (partial) | **PARTIAL** — no tier system |

### §11.2 Guardrail model — LOCKED / GUIDED / FREE

> "Enforce the guardrail in the type system, not at runtime. NocConfig simply has no field in which a LOCKED value could be placed."

**Our state:** Guardrails are runtime checks in `build_config()`:
- `classes` never passed (runtime check)
- `k/n` before `topology=` (ordering enforced)
- `use_noc_latency=0` for GEC (conditional)

**What's missing:**
- No `@dataclass(frozen=True)` with deliberately absent fields
- No compile-time enforcement — everything is runtime
- No tier badges visible to the user

**Honest assessment:** **PARTIAL.** We have safety checks but not type-system enforcement. The PRD's approach (no field = no override) is more robust than our approach (check at runtime).

### §11.3 Dependency-driven VC derivation

> "A hand VC assignment can satisfy every bandwidth and latency requirement and still deadlock in the field under a pattern nobody tested. The graph makes the risk visible and the resolution mechanical."

**Our state:** VC count is hardcoded (`num_vcs = 4`). No dependency graph. No cycle detection. No automatic VC derivation.

**What's missing:** The entire VC derivation algorithm. This is called out as "the key differentiator" in the PRD.

**Honest assessment:** **CRITICAL GAP.** This is the PRD's most technically distinctive feature — deriving VC structure from a dependency graph to guarantee deadlock-freedom. We don't have it.

### §11.4 Engine stages

> "1. Ingest & validate → 2. Synthesize → 3. Simulate → 4. Optimize → 5. Verify → 6. Generate"

**Our state:**
```
veritx run:
  Step 1: Generate trace from traffic model    (Ingest)
  Step 2: Synthesize topology via BO           (Synthesize)
  Step 3: Evaluate with BookSim                (Simulate + partial Optimize)
  Step 4: Certify flow/RTL                     (Verify + partial Generate)
```

**What's missing:**
- No separate "Optimize" stage (Pareto search is in `pareto` command, not in `run`)
- "Generate" is split between RTL gen and cert — not a single stage
- No formal stage boundaries — it's a single try/except chain
- No "Validate" stage — `veritx trace validate` exists but isn't wired into `run`

**Honest assessment:** **PARTIAL.** We have 4 of 6 stages. Missing: formal Validate (guardrails), separate Optimize (Pareto), unified Generate (RTL + reports + signing).

---

## §12 Backend Schema

> "Design (revision) — Immutable snapshot. The hash pins the guardrail version used."

**Our state:**
- `manifest.json` per run (not immutable — overwritten on re-run)
- No revision tracking
- No guardrail hash
- No "Design" entity — just a run directory

> "Agent, Workload, NocConfig, Job, Result, Artifact"

**Our state:**
- No Agent entity
- Workload is a trace file (not a structured entity)
- NocConfig is `Topology` + params (not persisted as a DB entity)
- Job is a synchronous CLI run (no async job model)
- Result is a JSON file (not a structured entity)
- Artifact is a file on disk (not a managed, signed entity)

**Honest assessment:** **CRITICAL GAP.** The entire persistence layer is file-based. The PRD wants a relational schema with immutability and audit trails.

---

## §13 The Generate Pipeline

> "Submit → Validate → Simulate → Optimize → Verify → Sign & store → Return"

**Our state:**
```python
# cmd_run in cli.py
Step 1: model_to_trace()          # Trace generation
Step 2: bo_synthesizer.py         # Synthesis
Step 3: run_topology_eval()       # Simulation
Step 4: milestone_c.py            # Certification
# Then: save manifest.json
```

**What's missing:**
- No "Validate" step (guardrail check before synthesis)
- No "Optimize" step (Pareto search during pipeline)
- No "Sign & store" step (no artifact signing)
- No WebSocket progress streaming
- No "Return" of views/reports/bundle

**Honest assessment:** **PARTIAL.** We have the core pipeline shape. Missing: Validate, Optimize, Sign, Return.

---

## §14 IP Protection & Trust

> "The engine runs server-side only. The client never receives the methodology — only its outputs."

**Our state:** CLI runs locally. Engine code is open (in the repo). No server-side protection.

> "Per-tenant isolation — a client's workload and address map are commercially sensitive."

**Our state:** Single-user. No tenant concept.

> "Artifact signing — every exported bundle is signed and checksummed."

**Our state:** No signing. No checksums on exported files.

> "Obfuscation levels — the FREE obfuscation knob controls how much of the RTL structure is protected."

**Our state:** RTL is generated unobfuscated. `gen_rtl.py` has a `guardrail_hash` comment but no actual obfuscation.

**Honest assessment:** **CRITICAL GAP.** IP protection is a product-level concern. We're a research tool — this isn't expected yet. But the PRD makes it a core requirement.

---

## §15 Suggested Build Order

> "P1 — Engine core: Fabric Compiler (E1–E5, guardrails), simulation core, one topology family."

**Our status:**
- Simulation core: ✅ BookSim2 integration works
- One topology family: ✅ mesh/torus/flatfly/GEC
- E1–E5 dataclasses: ❌ Not formalized
- Guardrails: ⚠️ Runtime checks only

**Verdict: P1 is ~60% done.** Need E1–E5 formalization + VC derivation.

> "P2 — Generate path: API + job queue + RTL/report generation + artifact store."

**Our status:** RTL generation works. No API, no job queue, no artifact store.

**Verdict: P2 is ~20% done.** RTL gen works, nothing else.

> "P3 — Views & reports: Logical/structural/physical views; area/power/timing dashboards."

**Our status:** No views. LaTeX report exists.

**Verdict: P3 is ~10% done.**

> "P4 — Interactive sim: In-tool simulator with tweak-and-replot."

**Our status:** `--sensitivity` flag. Not interactive.

**Verdict: P4 is ~15% done.**

> "P5 — Full editing: Live editing in every view with background re-validation."

**Our status:** Not started.

**Verdict: P5 is 0% done.**

---

## What We Have That the PRD Doesn't Mention

These are capabilities we've built that the PRD doesn't explicitly call for:

| Capability | Why It Matters | PRD Coverage |
|------------|---------------|--------------|
| BookSim2 GEC/MECS topology support | Express cube search — unique topology family | Not in PRD topology families |
| RHO/GRPO iterative synthesis | Novel search method, beats flat MCTS | Not in PRD search methods |
| Multi-workload Pareto evaluation | Same topology scored on Qwen3 + WRF + LLaMA | Not in PRD optimizer |
| ASTRA-sim BookSim2 backend | Real Chakra ET support, end-to-end | Not in PRD simulator stack |
| RTL certification 144/144 PASS | Formal verification of fabric correctness | PRD mentions F1–F8 but no implementation |
| Burst analysis + sensitivity | Honest traffic characterization | Not in PRD traffic model |
| Trace validation | Pre-flight safety checks | Not in PRD pipeline |
| Dense vs MoE crossover analysis | Research contribution (TP≥16 threshold) | Not in PRD workload model |
| Ring vs star collective comparison | 58× improvement from algorithm choice | Not in PRD optimization |

---

## Summary: Priority Gap List

### CRITICAL (blocks PRD product vision)
1. **Agent model (E3)** — no concept of typed agents with attributes
2. **Dependency graph (E4)** — no blocking/ordering model
3. **VC derivation from dependencies** — PRD's key differentiator (§11.3)
4. **CompileRequest dataclass** — formal E1–E5 input model
5. **NocConfig with LOCKED/GUIDED/FREE tiers** — type-system enforced guardrails
6. **Browser UI** — React canvas, inspector, live estimates
7. **API layer** — FastAPI + Celery for async generation

### HIGH (blocks paper-quality output)
8. **Guardrail hash** — reproducibility + audit trail
9. **UVM verification suite** — not just Verilator testbenches
10. **Artifact signing** — IP protection for exported RTL
11. **Area/power/timing reports** — wired from Timeloop + Accelergy
12. **Physical floorplan view** — placement-aware visualization

### MEDIUM (blocks full PRD coverage)
13. **Auto-lowering Level A → Level C** — model description to traffic matrix
14. **Built-in reference workloads** — more than 3 presets
15. **QoS classes** — latency-critical / bandwidth / best-effort
16. **Requirements dataclass** — per-class bounds + binding flags
17. **On-prem deployment model** — single-tenant engine

### LOW (nice-to-have)
18. **Behavioral models (C/SystemC)** — not just RTL
19. **PDF/HTML report export** — beyond LaTeX
20. **Interactive simulator in UI** — tweak-and-replot
21. **Obfuscation levels** — IP protection for delivered netlist
22. **Licensing model in-tool** — per-design/per-seat gating

---

## Recommended Approach

The PRD is aspirational. We should **not** try to build everything. Instead:

1. **Complete P1 (Engine core):** Formalize E1–E5, add VC derivation, add guardrail hash
2. **Build a thin API:** Wrap `veritx` CLI as FastAPI endpoints (2-3 days)
3. **Minimal UI:** React + React-Flow for topology visualization (1-2 weeks)
4. **Skip P5 (full editing) for now** — it's the hardest UI work and least critical for the paper
5. **Focus on what makes the paper strong:** Engine core + RTL cert + multi-workload Pareto
