# VERITX NoC Design-Space Exploration: Audit, Research, and Recommended Architecture

**Date:** 2026-10-31  
**Repository:** `veritx-research`  
**Audit snapshot:** `393206e4` + working tree (dirty; 361 modified/untracked paths)  
**Scope:** T3 topology DSE, BookSim integration, optimization/search, cost models, Studio/cockpit  
**Status:** Investigation only. No implementation was performed for this report.

## Evidence labels

Every major conclusion is labeled:

- **VERIFIED IN CODE** — observed in the repository at the audit snapshot, with file/function/line references.
- **VERIFIED EXTERNALLY** — observed in a primary external source (paper, official repository, official documentation).
- **REASONED PROPOSAL** — an engineering recommendation derived from the verified facts; not yet implemented or measured.
- **UNVERIFIED** — claimed or plausible, but not verified in code, in a primary source, or by execution.

Line numbers are current at the audit snapshot. The working tree is dirty, so they are not guaranteed to survive a later commit.

---

## 0. Executive summary

VERITX is not starting from zero. It already has a strong certified NoC evaluation backbone:

- A typed V4/V5 design IR with explicit topology intents, endpoint attachment, routing, and physical context. **VERIFIED IN CODE**
- A compiler certificate with connectivity, attachment, route completeness, route legality, VC assignment, and channel-VC deadlock obligations. **VERIFIED IN CODE**
- A BookSim fork with per-packet p50/p95/p99, completion time, per-class conservation, and per-channel time-series instrumentation. **VERIFIED IN CODE**
- 14 registered BookSim execution profiles, all declared `QUALIFIED` at audit time, each with an explicit scope. **VERIFIED IN CODE**
- A certified optimizer that runs real BookSim evaluations through authenticated evidence, with Pareto ranking, hard-constraint verdicts, content-addressed candidate IDs, and search-completeness accounting. **VERIFIED IN CODE**
- A Studio Optimize page that renders measured objectives, constraints, Pareto membership, and explicit “unmeasurable” states. **VERIFIED IN CODE**

The actual gap is narrower and more specific than “VERITX has no search”:

1. **The certified optimizer does not search VC count, buffer depth, routing, or turn restrictions.** Those are deliberately `LOCKED` and recompiled by `FabricCompiler`. It searches guided parameters such as topology family, link width, concentration, radix, and workload parallelism. **VERIFIED IN CODE**
2. **The design cockpit uses a separate diagnostic BookSim path** that does not call the certified conservation gate, sets `sim_power = 0`, does not parse p99 or native power, and is not aligned with the qualified profile scopes (notably the torus profile requires `use_noc_latency = 0`; the cockpit sets `use_noc_latency = 1`). **VERIFIED IN CODE**
3. **The current “AI topology search” is a bounded proposal loop**, not a NoC DSE engine: at most 4 proposals, 64 routers, 256 channels, 64 seats. A 9×9 fabric has 81 routers and 81 seats, so it is outside that pilot’s limits. **VERIFIED IN CODE**
4. **The cost numbers are not credible absolute physical costs.** The Accelergy bridge is explicitly a `PLACEHOLDER` ERT at 5.4 pJ/hop; Timeloop/Accelergy are accelerator-level tools, not NoC topology DSE; the cockpit’s energy/wire values are hand-set. **VERIFIED IN CODE**
5. **The only per-candidate cost model already integrated with BookSim is the BookSim native power/area model**, a 32 nm ITRS activity model valid for point-to-point mesh/torus, not a silicon calibration. **VERIFIED IN CODE**

### Final recommendation

For the current declared 9×9/10×10 mesh/torus space, use **exhaustive enumeration with structural pruning**, evaluated by BookSim, with a search ledger and explicit completeness accounting. Do **not** use a surrogate/ML optimizer until a validated surrogate exists and the space is large enough to justify it. Do **not** optimize energy, wire, or area until a credible cost model is integrated. Use **network performance only** as the objective: completion cycles and, once certified, packet latency/queue metrics. Treat cost as a separately labeled screen.

The scaling path is **hierarchical/two-stage search**: structural and analytical pruning first, BookSim on the survivors, then a more expensive cost model only for finalists. Use **pymoo/NSGA-II** only when the candidate space outgrows exhaustive evaluation and multiple objectives are genuinely needed. Use **RapidChiplet** only for chiplet-level inter-die DSE, not for the intra-die 9×9 mesh/torus question.

---

## 1. Method and audit boundary

### 1.1 What was inspected

- `tracks/t3-topology/dse/veritx_dse/` — model, compiler, verification, backend, optimization, gateway, reports.
- `tracks/t3-topology/scripts/` — supported sweeps, native power, energy bridge, Timeloop bridge, Pareto scripts.
- `tracks/t3-topology/configs/` and `tracks/t3-topology/timeloop/`.
- `third_party/booksim2/` and its `METADATA.json`.
- `apps/studio/src/` — Optimize, AI search, Pareto, constraints.
- The cockpit page and its static candidate JSON live in the worktree `/home/datavex/bruh/veritx-assistant-review/apps/studio/prototype/`; the `design_sim.py` backend is untracked in this main tree. Both are included in the audit because the cockpit is the prototype under discussion.
- Relevant tests, especially `test_design_sim.py`, `test_search_completeness.py`, `test_bo_adapter.py`, `test_bo_evaluation_honesty.py`, and the BookSim qualification tests.

### 1.2 What was not done

- No code changes.
- No new simulation campaign.
- No claim that a paper’s tool is reusable without checking its source and license.
- No claim that a metric exists because BookSim generally supports it; only metrics parsed by the current integration are treated as available.

### 1.3 External research boundary

External sources were used for tool capabilities, licenses, maintenance status, and published methods. Paper claims are marked **VERIFIED EXTERNALLY** only for what the paper/repository explicitly states; integration compatibility is **REASONED PROPOSAL** or **UNVERIFIED** unless demonstrated in this repository.

---

## 2. A. Current-state audit

### 2.1 Design IR and topology materialization

The current design root is `CompileRequestV4`, with `CompileRequestV5` adding clock, power, sideband, and access-policy intent:

- `CompileRequestV4` requires an explicit `TopologyIntent`; there is no implicit “None means mesh.” **VERIFIED IN CODE** — `model/compile_request_v4.py:79-130`.
- `CompileRequestV5` preserves a V4 base and adds explicit V5 extensions; unsupported extensions refuse rather than being silently dropped. **VERIFIED IN CODE** — `model/compile_request_v5.py:1-40, 130-180`.
- Topology intents include `MeshIntent`, `ConcentratedMeshIntent`, `TorusIntent`, `RingIntent`, `Tree4Intent`, `FlyIntent`, `QTreeIntent`, `FlatFlyIntent`, `FatTreeIntent`, `StructuredTopologyIntent`, and explicit graphs. **VERIFIED IN CODE** — `model/topology_intent.py`.
- The family registry is the single topology-count authority. It transcribes BookSim constructor formulas and distinguishes “network smaller than attached endpoints” as a contradiction. **VERIFIED IN CODE** — `model/family_registry.py:1-140`.
- Topology materialization builds the router graph, channels, and attachment; `FabricCompiler` turns a request into a resolved bundle and certificate. **VERIFIED IN CODE** — `application/fabric_compiler.py:136-384`.

**What this means:** VERITX already has a real design IR and a real materialization path. A search should consume this IR, not introduce a second one.

### 2.2 Attachment, routing, VC, and deadlock

- Attachment is validated against the materialized topology; the certificate includes `ATTACHMENT_COMPLETE`. **VERIFIED IN CODE** — `verification/certificate.py:24-30, 111-118`.
- Routing materialization has explicit families: `DOR_XY`, `DOR_TORUS_XY`, `FLATFLY_MIN`, `ANYNET_MIN_HOPS`, `WEIGHTED_SHORTEST_PATH`, and custom static routes. **VERIFIED IN CODE** — `model/routing_materialize.py:95-140`.
- The certificate obligations include `TOPOLOGY_CONNECTED`, `ATTACHMENT_COMPLETE`, `ROUTE_COMPLETE`, `ROUTE_LEGAL`, `VC_ASSIGNMENT_VALID`, `DEADLOCK_FREE`, plus technical checks such as address decode, mapping, packet format, and fabric DAG. **VERIFIED IN CODE** — `verification/certificate.py:24-40`, `application/certificate_projection.py:17-60`.
- Deadlock is proven, not assumed: the channel-VC dependency graph is checked for acyclicity; shared-resource fabrics use a separate CDG. **VERIFIED IN CODE** — `verification/certificate.py:270-393`, `verification/channel_vc_cdg.py`, `verification/shared_resource_cdg.py`.
- `verify_compiled_fabric` is the certificate entry point. **VERIFIED IN CODE** — `verification/certificate.py:541`.

**What this means:** A candidate that fails connectivity, attachment, route legality, VC assignment, or deadlock cannot honestly enter a performance search. The certificate is the correct structural validator.

### 2.3 BookSim integration: two different paths

There are two BookSim paths in the repository, and they do not have the same assurance level.

#### Path A — certified `FabricEvaluator` / BookSim adapter

- `BookSimAdapter` prepares, executes, and normalizes BookSim runs through the backend registry. **VERIFIED IN CODE** — `backend/booksim_adapter.py:105-626`.
- `booksim_execution.py` parses packet latency, flit latency, p50, p95, p99, packet count, hops, delivered packets, injected/accepted flits, per-class flits, instability tokens, and abort tokens. **VERIFIED IN CODE** — `backend/booksim_execution.py:338-421`.
- `assert_execution_gate` requires the trace-loaded packet count, injected count, delivered count, injected/accepted flit totals, per-class conservation (when requested), a valid completion cycle, and no unstable/abort token. **VERIFIED IN CODE** — `backend/booksim_execution.py:423-505`.
- `FabricEvaluator` binds the authenticated network window and refuses to construct wall-time claims without a declared clock. **VERIFIED IN CODE** — `application/fabric_evaluator.py:337-700`.
- The certified metric registry exposes `completion_cycles`, `completion_time`, and `completion_ns` as measured authorities; Wave-E model metrics are registered with `measured=False`. **VERIFIED IN CODE** — `optimization/metric_registry.py:335-360`.
- The certified optimizer uses `Optimizer.optimize_certified` → `RealCandidateEvaluator` → `FabricCompiler` + `FabricEvaluator` + authenticated evidence. **VERIFIED IN CODE** — `optimization/result.py:1005-1029`, `optimization/real_evaluator.py:119-240`.

#### Path B — design-cockpit diagnostic `design_sim.py`

- The cockpit endpoint is `POST /api/v1/loom/design/simulate`. **VERIFIED IN CODE** — `gateway/app.py:821-829`.
- It accepts 1–8 candidates, side 3–12, VCs 1–8, link width 64–512, family mesh/torus. **VERIFIED IN CODE** — `gateway/design_sim.py:43-57`.
- It writes a BookSim config with `use_noc_latency = 1`, `num_vcs = candidate.vcs`, `classes = trace_classes`, `max_samples = 1`, `injection_rate = 0.0`, and **`sim_power = 0`**. **VERIFIED IN CODE** — `gateway/design_sim.py:268-305`.
- It parses class packet/network/flit latency, hops, runtime, injected/accepted totals, but **not p50/p95/p99 and not native power/area**. **VERIFIED IN CODE** — `gateway/design_sim.py:238-263`.
- It reads the custom `channel_timeseries.json` and computes per-channel flits, queue cycles, and peak occupancy. **VERIFIED IN CODE** — `gateway/design_sim.py:204-237`.
- **It does not call `assert_execution_gate`.** A grep for `assert_execution_gate`, `loaded_trace_packets`, `delivered_packets`, `flits_injected`, and conservation in `design_sim.py` returns nothing. **VERIFIED IN CODE**
- Its tests cover geometry, projection, trace-path resolution, and torus VC refusal; they do not cover conservation or execution qualification. **VERIFIED IN CODE** — `tests/test_design_sim.py:1-180`.

**Consequence:** The cockpit’s 235/235 “accounting match” is a projection-vs-counter consistency check. It is useful, but it is **not** the certified BookSim execution gate. The cockpit’s queue/latency numbers are diagnostic BookSim output, not certified product evidence.

#### Qualification mismatch

The BookSim qualification registry is scope-specific:

- Mesh: seat capacity 1, square k×k, DOR_XY. **VERIFIED IN CODE** — `application/booksim_qualification_registry.py:150-162`.
- Concentrated mesh: seat 2 or 4, single class and VC, DOR_XY, `use_noc_latency 0`. **VERIFIED IN CODE** — `application/booksim_qualification_registry.py:164-180`.
- Torus: **odd square k×k only**, exact 2-VC dateline halves, DOR_TORUS_XY, **`use_noc_latency 0`**. **VERIFIED IN CODE** — `application/booksim_qualification_registry.py:231-250`.
- Mesh class-VC: seat 1, square k×k, DOR_XY, **two or more canonical traffic classes with one disjoint VC per class**, exact per-class input-VC membership, `use_noc_latency 1`. **VERIFIED IN CODE** — `application/booksim_qualification_registry.py:212-230`.

The cockpit’s `design_sim.py` sets `use_noc_latency = 1` for every candidate and does not verify per-class VC membership or dateline halves. **VERIFIED IN CODE** — `gateway/design_sim.py:276-295`.

**Therefore:** the 9×9 torus diagnostic run is **not** the qualified torus execution. The 2-VC/4-VC mesh runs are **not automatically** the qualified class-VC execution. They may still be valid BookSim configurations, but they must be labeled diagnostic unless they are lowered through the qualified path and the certificate/conservation gates.

### 2.4 Optimization infrastructure

The repository contains substantially more optimization machinery than the cockpit uses.

- `OptimizationDefinition` supports domain parameters, objectives, constraints, grid/enumeration/random search, a budget, a seed, and a selection policy. **VERIFIED IN CODE** — `optimization/definition.py:203-345`.
- Search methods are deliberately limited to `grid`, `enumeration`, and `random`; Bayes/MILP/SA/GRPO are refused with an explicit “only after deterministic correctness is established” message. **VERIFIED IN CODE** — `optimization/definition.py:17, 260-270`.
- Guided parameters include `link_width`, `concentration`, `radix`, `rcu_enabled`, `topology_family`, `arbitration`, multicast knobs, and workload parallelism. **VERIFIED IN CODE** — `optimization/definition.py:20-29`.
- Routing, VC count/structure, turn restrictions, and escape VC are **LOCKED** and cannot be patched; every candidate recompiles them through `FabricCompiler`. **VERIFIED IN CODE** — `optimization/definition.py:31-61`, `optimization/candidate.py:24-40`.
- The study path additionally refuses `rcu_enabled`, `mcast_groups`, and `mcast_setup_cycles` as dead knobs. **VERIFIED IN CODE** — `optimization/definition.py:346-395`.
- Candidate identity is content-addressed as `H(base design hash, canonical patch)`. **VERIFIED IN CODE** — `optimization/candidate.py:44-95`.
- `search_candidates` implements canonical grid enumeration and seeded random sampling. **VERIFIED IN CODE** — `optimization/search.py:20-90`.
- `SearchCompleteness` distinguishes `EXHAUSTIVE`, `BUDGETED`, and `UNBOUNDED`; only exhaustive search may claim optimality over the declared space. **VERIFIED IN CODE** — `optimization/completeness.py:25-135`.
- `pareto_ids` computes a non-dominated set; `pareto_with_sealed_gate` refuses mixed or unstamped fidelity. **VERIFIED IN CODE** — `optimization/pareto.py:9-76`.
- `StudyRunner` executes multi-scenario studies, records `VALID`/`ALIAS`/`INVALID`/`NOT_EVALUATED`, and enforces tail agreement and evaluation accounting. **VERIFIED IN CODE** — `optimization/study_runner.py:134-260`, `optimization/space_multiscenario.py:256-416`.
- `Optimizer.optimize_certified` is the only certified entry point; `optimize_with_port` is analytic/test only. **VERIFIED IN CODE** — `optimization/result.py:983-1029`.
- The Studio exposes a Pareto view, constraint rollups, and explicit `UNMEASURABLE` objective states. **VERIFIED IN CODE** — `apps/studio/src/components/OptimizeView.tsx:94, 250, 445, 594`.

#### The AI topology search is not a DSE engine

- `topology_search.py` is a bounded proposal/evidence loop: `max_proposals=4`, `max_routers=64`, `max_channels=256`, `max_seats=64`, `max_network_degree=8`, `backend_timeout_s=30`. **VERIFIED IN CODE** — `optimization/topology_search.py:24-25`.
- It refuses a topology that exceeds those limits, including a 9×9 fabric (81 routers, 81 seats). **VERIFIED IN CODE** — `optimization/topology_search.py:61-97`.
- The Studio UI advertises those exact limits and says “Network completion only, not model runtime, area or power.” **VERIFIED IN CODE** — `apps/studio/src/components/AITopologySearch.tsx:98-103`.
- The `bo_adapter` test suite confirms that the current “BO” path uses a `seeded-random` surrogate; a Gaussian-process surrogate is refused until vendored. **VERIFIED IN CODE** — `tests/test_bo_adapter.py:1-45`.

**Consequence:** The repository has a real deterministic optimizer, but it cannot search the cockpit’s VC/buffer question. The cockpit has a diagnostic evaluator that can vary VCs, but it bypasses the certificate/conservation discipline. This is the central architectural split that must be resolved.

### 2.5 Cost model

#### What exists

| Estimator | What it produces | Fidelity | Use as objective? | Evidence |
|---|---|---|---|---|
| `reports/reports.py` | Analytical router/link/NIC area, dynamic + leakage power, Fmax, pJ/bit | `ANALYTICAL_ESTIMATE`; accuracy notes say ±30% and order-of-magnitude | No | **VERIFIED IN CODE** — `reports/reports.py:38-210, 266-360` |
| `scripts/native_power.py` | BookSim `Total Power` / `Total Area`; pJ/cycle | `BOOKSIM_NATIVE_MODEL`, 2007 ITRS 32 nm, point-to-point families only | Screening only | **VERIFIED IN CODE** — `scripts/native_power.py:1-80` |
| `scripts/sweep_supported.py --native-power` | Runs BookSim with `sim_power=1`, `channel_width=128`; writes native model provenance | Backend activity model | Screening only | **VERIFIED IN CODE** — `scripts/sweep_supported.py:207, 424` |
| `scripts/noc_energy_bridge.py` | Accelergy 1-hop calibration → `pj_per_hop` | `TOOL_CALIBRATED_PROXY`; ERT is a `PLACEHOLDER` | No | **VERIFIED IN CODE** — `scripts/noc_energy_bridge.py:131-260`, `reports/energy_fidelity.py:10-35` |
| `scripts/energy_score.py` | `hops_avg × pj_per_hop` | Proxy; default 20.5 pJ/hop | No | **VERIFIED IN CODE** — `scripts/energy_score.py:1-90` |
| `scripts/area_model.py` | Port-count area estimate, `UNIT_AREA_PER_PORT = 0.0165 mm² @45 nm` | Analytical proxy, calibrated to mesh4x4 | No | **VERIFIED IN CODE** — `scripts/area_model.py:45-55` |
| `tracks/t3-topology/timeloop/` | Timeloop accelerator mapping + Accelergy energy | `TOOL_DERIVED` accelerator energy; not NoC signoff | No | **VERIFIED IN CODE** — `tracks/t3-topology/timeloop/arch.yaml`, `noc_arch.yaml`, `noc_ERT.yaml` |
| Cockpit `baseEnergy` / `baseWire` | Hand-set multipliers (1.00, 1.04, 1.18, etc.) | None | No | **VERIFIED IN CODE** — worktree `apps/studio/prototype/design-cockpit.html`; `design_sim.py` sets `sim_power=0` |

#### Key cost-model facts

- `energy_fidelity.py` states `BRIDGE_PJ_PER_HOP = 5.4` and `BRIDGE_ERT_STATUS = "PLACEHOLDER"`, and `combine_estimates` raises rather than merging fidelities. **VERIFIED IN CODE** — `reports/energy_fidelity.py:10-85`.
- The Timeloop `arch.yaml` is a 16-tile 4×4 accelerator, not the 64-endpoint Mixtral fabric. **VERIFIED IN CODE** — `tracks/t3-topology/timeloop/arch.yaml:1-30`.
- The Accelergy NoC `noc_ERT.yaml` is a fixed generic table: router traversal 2.5, buffer read 0.8, buffer write 0.9, link transfer 1.2 pJ. It is not parameterized by VC count, buffer depth, radix, or link width. **VERIFIED IN CODE** — `tracks/t3-topology/timeloop/noc_ERT.yaml`.
- `noc_energy_bridge.py` explicitly treats Accelergy as a **pJ-per-hop coefficient generator**, not a topology simulator. **VERIFIED IN CODE** — `scripts/noc_energy_bridge.py:1-32`.
- `timeloop_to_matrix.py` calls its spatial model a “deliberately simple placeholder.” **VERIFIED IN CODE** — `scripts/timeloop_to_matrix.py:1-80`.
- `ip_catalog.py` refuses numeric area/power without a PDK, Liberty, or P&R artifact; it says an area/power estimate would be an invented figure. **VERIFIED IN CODE** — `model/ip_catalog.py:136-165`.
- `Result` has `area_mm2=0.0`, `power_w=0.0`, `fmax_mhz=0.0`, `energy_pj_per_bit=0.0` defaults; these must not be read as measured zeros. **VERIFIED IN CODE** — `model/compile_model.py:1369-1408`.
- The Dockerfile installs Timeloop and Accelergy and the T3 Makefile has `timeloop`/`energy` targets, but the certified optimizer and the cockpit do not call them. **VERIFIED IN CODE** — `Dockerfile:78-102`, `tracks/t3-topology/Makefile:61-151`.
- There is no OpenROAD, ORION, DSENT, or PDK integration in the current tree. **VERIFIED IN CODE** — no such vendored tool in `third_party/`; `third_party/README.md` lists Booksim/astra-sim/llmservingsim/Timeloop only.

#### Provenance inconsistency

The DSE docs claim Timeloop + Accelergy integration “exists in `runs/mot_htree/` — 14.284 pJ per hop,” but that directory is absent in the current tree, while `energy_fidelity.py` says 5.4 pJ/hop and `PLACEHOLDER`. **VERIFIED IN CODE** — `tracks/t3-topology/dse/docs/PRD-GAP-ANALYSIS-DETAILED.md:230-235`; directory search returns no `runs/mot_htree`; `reports/energy_fidelity.py:10`.

**Consequence:** There is no canonical, reproducible NoC energy authority today. Any optimizer that treats the current energy or wire numbers as an objective is optimizing a placeholder.

### 2.6 Studio and cockpit

- Studio `OptimizeView` renders Pareto, objectives, constraints, objective availability, and “unmeasurable” states. **VERIFIED IN CODE** — `apps/studio/src/components/OptimizeView.tsx:94-250, 445-594`.
- Studio `AITopologySearch` is a bounded proposal loop with explicit limits and “Network completion only” language. **VERIFIED IN CODE** — `apps/studio/src/components/AITopologySearch.tsx:58-110`.
- The design cockpit is a separate prototype page in the worktree `/home/datavex/bruh/veritx-assistant-review`, with a five-candidate curated set (mesh 1 VC, mesh 2 VC, torus 2 VC, mesh 4 VC, 8×8 ablation). **VERIFIED IN CODE** — worktree `apps/studio/prototype/design-cockpit.html`.
- The cockpit’s candidate evidence is a static JSON plus the live `design_sim.py` endpoint; it is not wired to the Studio optimizer or the certified evaluator. **VERIFIED IN CODE** — worktree `apps/studio/prototype/public/data/candidate_evidence_9x9.json`; `gateway/app.py:821-829`.

### 2.7 Capability matrix

| Capability | Status | Evidence |
|---|---|---|
| Typed V4/V5 design IR | **IMPLEMENTED** | `model/compile_request_v4.py`, `compile_request_v5.py` |
| Mesh/torus/cmesh/ring/tree4/fly/qtree/flatfly/fattree intents | **IMPLEMENTED** | `model/topology_intent.py` |
| Endpoint attachment and placement | **IMPLEMENTED** | `model/attachment.py`, `model/placement.py`, certificate |
| DOR-XY / DOR-torus / AnyNet-min / flatfly-min routing | **IMPLEMENTED** | `model/routing_materialize.py` |
| Certificate: connectivity, attachment, route, VC, deadlock | **IMPLEMENTED** | `verification/certificate.py` |
| BookSim certified execution + conservation | **IMPLEMENTED** | `backend/booksim_execution.py` |
| Per-channel time-series / queue counters | **IMPLEMENTED** (diagnostic fork) | `backend/channel_series.py`, `channel_measurements.py` |
| p50/p95/p99 packet latency | **IMPLEMENTED** in certified parser | `backend/booksim_execution.py:407-409` |
| p50/p95/p99 in cockpit path | **UNSUPPORTED** | `gateway/design_sim.py:238-263` |
| Native BookSim power/area | **IMPLEMENTED** for point-to-point families | `scripts/native_power.py` |
| Cockpit native power | **UNSUPPORTED** (`sim_power=0`) | `gateway/design_sim.py:295` |
| Certified optimizer (grid/random) | **IMPLEMENTED** | `optimization/result.py:1005` |
| VC/buffer/routing search in certified optimizer | **UNSUPPORTED** (locked) | `optimization/definition.py:31-61` |
| Exhaustive/random search with completeness ledger | **IMPLEMENTED** | `optimization/completeness.py`, `search.py` |
| Pareto ranking | **IMPLEMENTED** | `optimization/pareto.py` |
| Multi-scenario studies | **IMPLEMENTED** | `optimization/study_runner.py` |
| AI proposal loop | **PARTIAL** (bounded, 4 proposals/64 routers) | `optimization/topology_search.py` |
| BO / Gaussian-process surrogate | **UNSUPPORTED** (seeded-random surrogate only) | `tests/test_bo_adapter.py:1-45` |
| Accelergy NoC energy | **PARTIAL** (placeholder ERT) | `scripts/noc_energy_bridge.py`, `reports/energy_fidelity.py` |
| Timeloop accelerator energy | **PARTIAL** (16-tile accelerator only) | `tracks/t3-topology/timeloop/` |
| Credible absolute area/power | **UNSUPPORTED** | `ip_catalog.py:136-165`, `reports.py` accuracy notes |
| OpenROAD / PDK / post-layout | **UNSUPPORTED** | no vendored tool/PDK |
| Cockpit conservation gate | **UNSUPPORTED** | `gateway/design_sim.py` no `assert_execution_gate` |
| Cockpit search | **UNSUPPORTED** (curated static set) | `design-cockpit.html` |

---

## 3. B. Research comparison

### 3.1 Timeloop and Accelergy

**What they solve:** Timeloop maps DNN loop nests onto accelerator architectures and reports data movement; Accelergy estimates accelerator component energy from action counts and an energy reference table (ERT). **VERIFIED EXTERNALLY** — [Timeloop/Accelergy tutorial](https://accelergy.mit.edu/tutorial.html).

**NoC limits:**

- Timeloop does not model NoC topology, VC arbitration, or packet latency. In [Timeloop issue #177](https://github.com/NVlabs/timeloop/issues/177), maintainers state there is no NoC latency modeling; a hop is the distance between neighboring mesh nodes; peer-to-peer traffic needs additional network definitions. **VERIFIED EXTERNALLY**
- Accelergy does not analyze how data moves; it needs a component model and action counts. For a custom NoC, you define a compound component or wire model. **VERIFIED EXTERNALLY** — issue #177; [Accelergy tutorial](https://accelergy.mit.edu/tutorial.html).
- The current `noc_ERT.yaml` is a generic placeholder and cannot distinguish 1 VC from 4 VC. **VERIFIED IN CODE**

**Fit for VERITX:** Use as a cross-check for a pJ/hop coefficient with a parameterized ERT, or as an accelerator-side energy model. Do not use as the NoC DSE engine or as the topology cost authority.

### 3.2 DSENT

**What it solves:** Analytical, parameterized power/area models for electrical and opto-electrical NoCs; supports 45/32/22/11 nm, a 3-stage input-buffered VC router, DFF buffers, mux-based crossbar, two-stage allocator, H-tree clock. **VERIFIED EXTERNALLY** — [DSENT README](https://github.com/beneslami/dsent), [DSENT paper](https://projects.csail.mit.edu/wiki/pub/LSPgroup/PublicationList/dsent_nocs12.pdf).

**Code/license/maintenance:**

- Unofficial GitHub mirror: `https://github.com/beneslami/dsent`, MIT, 0 stars, 1 commit, created 2026-05-01. **VERIFIED EXTERNALLY** — GitHub API.
- Upstream release 0.91 (26 June 2012); gem5 carries `ext/dsent`. **VERIFIED EXTERNALLY** — DSENT README; gem5 README.
- Maintenance: effectively unmaintained; technology nodes stop at 11 nm. **REASONED PROPOSAL**

**Inputs/outputs:** router radix, VCs, buffers, flit width, frequency, technology; outputs energy per event, non-data-dependent power, area. **VERIFIED EXTERNALLY**

**BookSim integration:** none out of the box. A VERITX adapter would need to map candidate parameters to DSENT configs and combine DSENT per-hop/per-event costs with BookSim hop/flit counts. **REASONED PROPOSAL**

**Assumptions/limits:** deep-sub-100 nm accuracy claims; known bugs for timing-not-met and unmodeled VC/credit buffers; local interconnect not modeled. **VERIFIED EXTERNALLY** — DSENT README "Known Bugs and Issues."

**Fit:** Strong candidate for router/link power and area on finalists; not a drop-in search evaluator.

### 3.3 ORION 3.0 and PAT-Noxim

**ORION 3.0:** post-place-and-route calibrated parametric/nonparametric router power/area models; 22–90 nm support. **VERIFIED EXTERNALLY** — [ORION 3.0 paper](https://vlsicad.ucsd.edu/Publications/Journals/j113.pdf). Code availability: the paper says web download; no maintained GitHub repository was located; GitHub search returns 0 repositories. **UNVERIFIED** for a canonical source.

**PAT-Noxim:** cycle-accurate SystemC NoC simulator with ORION 3.0 power/area, McPAT PE power/area, and HotSpot thermal; GPL-3.0; 38 stars; 21 commits; active as of 2026-07-11. **VERIFIED EXTERNALLY** — [PAT-Noxim](https://github.com/amin-norollah/PAT-Noxim), GitHub API.

**Fit:** PAT-Noxim is a separate simulator, not a BookSim drop-in. It could be a cross-check for router power/area/thermal, but it would duplicate the performance path. Use only if thermal/power is a first-class requirement.

### 3.4 pymoo

**What it solves:** Multi-objective optimization (NSGA-II, NSGA-III, MOEA/D, CMA-ES, etc.) with constraints. **VERIFIED EXTERNALLY** — [pymoo](https://github.com/the-dual-space/pymoo).

**Code/license/maintenance:** Apache-2.0, 2,986 stars, active (pushed 2026-07-07). **VERIFIED EXTERNALLY** — GitHub API.

**Fit:** The best-established choice if the search space grows beyond exhaustive and multiple objectives are required. It is not needed for a 10–20 candidate space; it would add stochasticity and a new dependency without improving coverage. **REASONED PROPOSAL**

### 3.5 Optuna

**What it solves:** Hyperparameter optimization with TPE, pruning, distributed trials. **VERIFIED EXTERNALLY** — [Optuna](https://github.com/optuna/optuna).

**Code/license/maintenance:** MIT, 14,997 stars, active (pushed 2026-10-30). **VERIFIED EXTERNALLY** — GitHub API.

**Fit:** Strong for single-objective black-box optimization; less natural than pymoo for constrained multi-objective Pareto search. Not needed for the current small space. **REASONED PROPOSAL**

### 3.6 OpenROAD

**What it solves:** RTL-to-GDS implementation, timing, area, power after synthesis/place-and-route. **VERIFIED EXTERNALLY** — [OpenROAD](https://github.com/The-OpenROAD-Project/OpenROAD).

**Code/license/maintenance:** BSD-3-Clause, 3,242 stars, active (pushed 2026-10-31). **VERIFIED EXTERNALLY** — GitHub API.

**Fit:** Finalist validation only. It requires a PDK, synthesis/P&R flow, and substantial runtime; it cannot evaluate every candidate. No PDK/vendor library is present in the current tree. **VERIFIED IN CODE** / **REASONED PROPOSAL**

### 3.7 NOCTOPUS

**What it is:** A 2026 framework that predicts optimal NoC configurations from SoC parameters and performance targets; uses a cycle-accurate NoC simulator to generate a dataset via Latin Hypercube Sampling. **VERIFIED EXTERNALLY** — [Springer article](https://link.springer.com/article/10.1007/s00521-026-12049-4), [ACM DOI](https://dl.acm.org/doi/10.1007/s00521-026-12049-4).

**Code availability:** No public repository was located in GitHub search; code availability is **UNVERIFIED**. Do not treat the paper as reusable software. **VERIFIED EXTERNALLY** (absence of a located repo) / **UNVERIFIED** (definitive unavailability).

**Fit:** Research reference for a simulation-data predictor, not a directly reusable tool.

### 3.8 BookSim-based ML DSE

**What it is:** A 2025 framework using 150,000 BookSim simulations and reverse neural-network models (MLP, conditional diffusion, CVAE) to predict NoC parameters from latency/throughput targets; reports MSE 0.463 for the diffusion model. **VERIFIED EXTERNALLY** — [arXiv 2512.07877](https://arxiv.org/abs/2512.07877).

**Fit:** Demonstrates the surrogate-first pattern, but 150k simulations are far beyond the current 10–20 candidate budget. It is not needed for the current space and would create a new training/provenance problem. **REASONED PROPOSAL**

### 3.9 MOOS and classical multi-objective DSE

**MOOS:** adaptive data-driven multi-objective search for NoC-enabled manycore systems, reporting up to 13× speedup over state-of-the-art and up to 20% better NoC designs on 3D manycore benchmarks. **VERIFIED EXTERNALLY** — [MOOS, ACM TECS 2019](https://dl.acm.org/doi/10.1145/3358206).

**Classical genetic DSE:** Palesi/Givargis, "Multi-Objective Design Space Exploration Using Genetic Algorithms" (CODES 2002), establishes the long-standing NSGA/SPEA-style approach. **VERIFIED EXTERNALLY** — [paper PDF](https://www.cecs.uci.edu/conference_proceedings/codes_2002/palesi_multi.pdf).

**Fit:** Good references for a future multi-objective search; not required for the current small exhaustive space.

### 3.10 RapidChiplet

**What it solves:** Fast inter-chiplet interconnect latency/throughput plus high-level area, power, manufacturing cost, and thermal stability; supports BookSim2 and Netrace; includes automated DSE experiment files. **VERIFIED EXTERNALLY** — [RapidChiplet](https://github.com/spcl/rapidchiplet), [paper](https://arxiv.org/abs/2311.06081).

**Code/license/maintenance:** 93 stars, 20 forks, 9 commits, last push 2025-07-25; GitHub API reports **no license**. **VERIFIED EXTERNALLY** — GitHub API.

**Fit:** Chiplet-level inter-die DSE. It is not a drop-in for the intra-die 9×9 mesh/torus BookSim trace replay. License must be resolved before reuse. **REASONED PROPOSAL**

### 3.11 Research comparison summary

| Tool / method | Solves | Code / license | Maintenance | BookSim integration | Fit for VERITX |
|---|---|---|---|---|---|
| Timeloop / Accelergy | Accelerator mapping + component energy | Docker/T3 vendored; MIT-style upstream | Active-ish; ERT placeholder here | Via pJ/hop bridge only | Cross-check, not NoC DSE |
| DSENT | NoC router/link power/area | MIT mirror; upstream 2012 | Unmaintained | Adapter needed | Finalist cost model |
| ORION 3.0 | Post-P&R router power/area | Web download; no canonical repo found | Unknown | Adapter needed | Finalist cost model |
| PAT-Noxim | Cycle-accurate power/thermal NoC | GPL-3.0; active 2026 | Active | Separate simulator | Cross-check, not drop-in |
| pymoo | Multi-objective optimization | Apache-2.0; active | Active | Objective-agnostic | Later, if space grows |
| Optuna | Single-objective BO/TPE | MIT; active | Active | Objective-agnostic | Later, if space grows |
| OpenROAD | RTL-to-GDS PPA | BSD-3; active | Active | None | Finalist validation |
| NOCTOPUS | Simulation-data predictor | No repo found | Unknown | Unknown | Research only |
| BookSim ML DSE | Surrogate NoC DSE | Paper only; 150k points | Research | BookSim | Not for 10–20 candidates |
| MOOS | Adaptive multi-objective DSE | Paper; code unverified | Research | Custom | Research reference |
| RapidChiplet | Chiplet-level DSE | No license declared | Last push 2025 | BookSim2/Netrace | Inter-die only |

---

## 4. C. Integration feasibility matrix

### 4.1 Directly reusable

- `CompileRequestV4` / `CompileRequestV5` as the only design IR.
- `FabricCompiler` + `verify_compiled_fabric` as the structural validator.
- `BookSimAdapter`, `booksim_execution.py`, `assert_execution_gate` as the certified evaluator.
- `OptimizationDefinition`, `search.py`, `completeness.py`, `pareto.py`, `constraints.py`.
- `Optimizer.optimize_certified` and `RealCandidateEvaluator`.
- `EvidenceCache` and run-bundle provenance.
- Studio `OptimizeView` for Pareto/constraint rendering.
- `native_power.py` for a labeled per-candidate backend activity screen.

### 4.2 Adaptable with bounded work

- `design_sim.py`: add conservation gate, p99 parsing, native power, and qualification alignment. Keep it labeled diagnostic.
- `metric_registry.py`: add p99/queue metrics only with a declared producer and measured/certified status.
- `topology_search.py`: raise the 9×9 limit only if the 81-router fabric fits the pilot’s structural budgets and the certificate/evidence path; otherwise keep it as a 64-router pilot.
- `native_power.py`: enable `sim_power=1` for the cockpit candidates; parse `Total Power`/`Total Area`; store model provenance.
- `sweep_supported.py`: reuse its thread-pool, run-directory, and native-model provenance patterns.

### 4.3 Research-only or substantial

- VC/buffer intent + deadlock proof extension in the compiler.
- A VC/buffer search in the certified optimizer.
- DSENT adapter for candidate router/link cost.
- pymoo/NSGA-II integration for larger spaces.
- A validated surrogate/ML model.
- OpenROAD finalist flow.

### 4.4 Unsuitable

- Timeloop/Accelergy as the NoC topology DSE engine.
- Accelergy placeholder ERT as an optimization objective.
- The cockpit’s hand-set `baseEnergy`/`baseWire` as a cost model.
- NOCTOPUS as reusable software without source.
- RapidChiplet for intra-die 9×9 mesh/torus.
- ML surrogate for a 10–20 candidate space.

---

## 5. D. Search formulation

### 5.1 Variables and valid domains

Do not assume a full Cartesian product. The following table distinguishes what the certified path supports, what the diagnostic path supports, and what is not supported.

| Variable | Valid values (current) | Path | Evidence / constraint |
|---|---|---|---|
| Topology family | `mesh`, `torus`, `concentrated_mesh` | Certified for supported intents; diagnostic for mesh/torus | `TopologyIntent`; qualification scopes |
| Side length | 9, 10 (8 is ablation; 11/12 possible but costlier) | Both | 9×9 = 81 seats; 10×10 = 100; 8×8 = 64 < 74 system endpoints |
| Concentration | 1 for mesh/torus; 2 or 4 for cmesh | Certified cmesh; diagnostic mesh/torus ignores concentration in projection | `design_sim._project` maps endpoint i→router i; concentration is not implemented there |
| VC count | 2 for torus; 1/2/4 diagnostic for mesh | Torus certified; mesh diagnostic unless class-VC qualification | `design_sim.py` allows 1–8; qualified mesh class-VC requires one VC per class |
| Buffer depth | Not exposed | None | `CandidateSpec` has no `vc_buf_size`; BookSim configs do |
| Link width | 64–512 bits; 128/256 as initial values | Diagnostic; certified via v4 controls for supported lowering | `CandidateSpec`; `NocControls.link_width` |
| Routing | DOR_XY mesh; DOR_TORUS_XY torus | Certified scopes | Torus requires odd square, exact 2-VC dateline |
| Placement | `rank_order` only | Study path | `PLACEMENT_POLICIES = ("rank_order",)` |
| Workload parallelism | tp/pp/ep/dp | Study path | `PARALLELISM_DIMS` |
| Trace | Fixed Mixtral 64-endpoint trace | Both | Same trace hash required for comparison |

**Critical finding:** The certified optimizer’s `OptimizationDefinition` does not expose VC count, buffer depth, routing, or turn restrictions; those are locked and recompiled. **VERIFIED IN CODE** — `optimization/definition.py:31-61`. A search that varies those dimensions must either extend the compiler with a proven VC/buffer intent or use a separate diagnostic path with explicit non-certified labels.

### 5.2 Structural and semantic constraints

A candidate is valid only if all of the following hold:

1. **Seat capacity:** `routers × concentration ≥ 74` system endpoints (64 compute + 8 HBM + 2 NIC). This rejects 8×8 (64 seats) for the real revision. **REASONED PROPOSAL**, grounded in the 74-endpoint requirement.
2. **Trace capacity:** the fabric must host the 64 trace endpoints. **VERIFIED IN CODE** — `design_sim.py:151-166`.
3. **Topology support:** the family must be in `TopologyIntent` / `EXPRESSIBLE_FAMILIES` / qualification scope. **VERIFIED IN CODE**
4. **Torus constraints:** odd square, at least 2 VCs, exact dateline halves, `use_noc_latency 0` for the qualified profile. **VERIFIED IN CODE** — qualification record.
5. **Routing legality:** route complete/legal and VC assignment valid. **VERIFIED IN CODE** — certificate.
6. **Deadlock:** channel-VC CDG acyclic (or shared-resource CDG for MECS). **VERIFIED IN CODE** — certificate.
7. **BookSim qualification:** the candidate must lower to a qualified profile if it is to be certified. **VERIFIED IN CODE** — qualification registry.
8. **Conservation:** loaded/injected/delivered packets and flits must conserve. **VERIFIED IN CODE** — `assert_execution_gate`; not yet in `design_sim`.
9. **Cost screen:** energy/wire/area may be reported only with a fidelity label; they are not hard constraints until a credible model exists. **REASONED PROPOSAL**

### 5.3 Objectives

**Primary (recommended):**

- `completion_cycles` — certified network completion. **VERIFIED IN CODE** — `metric_registry.py:335`.
- `completion_ns` only with an exact network clock. **VERIFIED IN CODE**
- Throughput / accepted packet rate — available from BookSim; needs a certified metric authority before it can be a certified objective. **REASONED PROPOSAL**

**Secondary / diagnostic:**

- Packet latency mean, p50/p95/p99 — parsed by the certified path but not registered as certified metrics. **VERIFIED IN CODE**
- Worst queue occupancy / queue cycles per flit — measured by the fork’s channel time series, but only in the diagnostic path. **VERIFIED IN CODE**
- Area, power, wire — analytical/proxy; **not objectives**. **REASONED PROPOSAL**

**Do not optimize:**

- The hand-set cockpit energy/wire multipliers.
- The Accelergy placeholder pJ/hop.
- A composite score that mixes measured network behavior with estimated cost.
- Area/power from `reports.py` without a fidelity label and sensitivity analysis.

### 5.4 Pruning rules

Pruning is allowed only when it is justified by a structural proof or a declared capability/qualification. Record the exact reason in the ledger.

**Safe pruning:**

- `seats < 74` → invalid for the system.
- `side < 3` or unsupported family → invalid.
- Torus even side, <2 VCs, or missing dateline proof → invalid/unsupported.
- CMesh concentration not 2 or 4, or multi-class/multi-VC mismatch → unsupported.
- Certificate obligation fail → invalid.
- Missing trace/BookSim binary/config → infrastructure failure, not a design verdict.
- Duplicate candidate ID → alias, not a second evaluation.
- Budget tail → `NOT_EVALUATED`, not “invalid.”

**Unsafe pruning (must not be used without a proof):**

- “Mesh is probably better than torus” — the current 2-VC diagnostic comparison is evidence, not a global proof.
- “4 VCs will always beat 2 VCs” — depends on trace and router cost.
- “A topology with more channels is too expensive” — cost model is not credible.
- “Random sample is enough” — only if the sample size and confidence are stated; it is not exhaustive.

### 5.5 Candidate deduplication and caching

- Candidate identity: `cand_<hash(base design hash, canonical patch)>`. **VERIFIED IN CODE** — `optimization/candidate.py:44-95`.
- Duplicate patches → alias; never double-evaluated. **VERIFIED IN CODE** — `space_multiscenario.build_study_candidates:256-305`.
- Evidence cache key includes prepared config, trace hash, binary hash, profile, parser version, build manifest, producer revision, seed, topology/fabric/traffic IDs, route observation, question, and network clock. **VERIFIED IN CODE** — `backend/evidence_cache.py:14-115`.
- Cache transplant is refused when any key field differs. **VERIFIED IN CODE** — `evidence_cache.py:70-115`.

### 5.6 Evaluation protocol

For every candidate:

1. Compile with `FabricCompiler`; require `status == "COMPILED"` and certificate `overall == "PASS"`. **VERIFIED IN CODE**
2. Lower to the qualified BookSim profile; record profile ID, binary SHA, config SHA, trace SHA, seed, sample period, network clock. **VERIFIED IN CODE**
3. Run BookSim with a bounded timeout; require exit 0 and the completion evidence. **VERIFIED IN CODE**
4. Call `assert_execution_gate` with expected packets/flits and per-class counts. **VERIFIED IN CODE**
5. Extract only registered metrics; unavailable metrics stay `UNMEASURABLE`, never zero. **VERIFIED IN CODE**
6. Record the run directory, evidence refs, parser version, and producer identity. **VERIFIED IN CODE**
7. On any failure, record `FAILED`/`TIMED_OUT` with the real reason; never substitute a plausible number. **VERIFIED IN CODE** — `real_evaluator.py` and `booksim_execution.py`.

For the diagnostic cockpit path, add the same gate before using its numbers. Until then, label it `DIAGNOSTIC_BOOKSIM_TRACE_REPLAY`, not `CERTIFIED_PRODUCT`.

### 5.7 Termination and reproducibility

- Exhaustive: evaluate all valid candidates; `SearchCompleteness.EXHAUSTIVE`; may claim optimality over the declared finite space. **VERIFIED IN CODE** — `completeness.py:25-90`.
- Budgeted: evaluate a prefix or sample; `BUDGETED`; may claim only “best observed among evaluated candidates.” **VERIFIED IN CODE**
- Unbounded/random: `UNBOUNDED`; no universe size, no optimality claim. **VERIFIED IN CODE**
- Record the definition ID, search method, seed, budget, generated/valid/alias/invalid/not-evaluated counts, evaluated IDs, failures, Pareto IDs, and selected ID. **VERIFIED IN CODE** — `space_multiscenario.py:388-416`, `result.py` study view.

### 5.8 Search-formulation decision

| Approach | When it wins | Why not now / caveat |
|---|---|---|
| A. Exhaustive + structural pruning | Small declared space (10–50), deterministic, auditable | Best fit for 9×9/10×10 mesh/torus/VC/link-width |
| B. Constrained multi-objective (pymoo NSGA-II/III) | Large space, many objectives, simulation budget | Overkill for 20 candidates; adds stochasticity/dependency |
| C. Bayesian/surrogate | Expensive evaluator, high-dimensional continuous space | No validated surrogate; current “BO” is seeded random |
| D. Hierarchical/multi-fidelity | Large space; cheap screen then BookSim finalists | Good scaling path; the cheap screen must be validated |
| E. End-to-end framework (RapidChiplet) | Chiplet-level ICI/placement/cost | Not intra-die 9×9; license unverified |

**Recommendation:** **A now, D as the scale path, B later, C deferred, E only for chiplet-level.** **REASONED PROPOSAL**

---

## 6. E. Cost-model assessment

### 6.1 What can be estimated credibly today

**Relative network performance** — yes, from BookSim, with the certified path and conservation gate. **VERIFIED IN CODE**

**Relative backend activity power/area** — conditionally, from BookSim native `Total Power`/`Total Area` for point-to-point mesh/torus. It is a 32 nm ITRS model, not silicon, and has no NIC/DRAM/compute. It is valid for relative comparison within the same technology/model. **VERIFIED IN CODE** — `native_power.py:1-80`.

**Screening area** — `reports.py` analytical estimates with ±30% claims, and `area_model.py` port-count estimates; both are screening values, not signoff. **VERIFIED IN CODE**

**Wire length** — not measured. The current cockpit wire values are hand-set; the repo has no routed wirelength or physical placement. **VERIFIED IN CODE**

### 6.2 What cannot be estimated credibly today

- Absolute router/link energy for a specific PDK.
- Absolute area or Fmax for a specific standard-cell library.
- Leakage/thermal/clock-tree power.
- Wire capacitance/resistance for a real metal stack.
- Inter-die/UCIe cost.
- Any cost number derived from the 5.4 pJ/hop placeholder.
- Any cost number from the cockpit’s hand-set multipliers.

### 6.3 Cost-model recommendation

1. **Do not optimize cost.** Use network performance as the objective.
2. **Report cost as a screen**, with estimator ID, inputs, fidelity, and confidence.
3. **Use BookSim native power first** for per-candidate activity; label it `BOOKSIM_NATIVE_MODEL · 32 nm ITRS · not silicon`.
4. **Use DSENT or ORION for finalists** to generate router/link power/area; keep the fidelity separate.
5. **Use OpenROAD only for a single selected design**, with a PDK and a declared flow; never for the search loop.
6. **Keep Accelergy as a cross-check**, with a parameterized ERT; do not use the current placeholder ERT as an objective.
7. **Never merge fidelities**; `combine_estimates` already refuses this. **VERIFIED IN CODE**

### 6.4 Cost-model identity table

| Quantity | Current method | Fidelity | Objective? |
|---|---|---|---|
| Network completion | BookSim certified | `SIMULATED` | **Yes** |
| Packet latency / p99 | BookSim certified parser | `SIMULATED` | Only after metric registration |
| Queue occupancy | Fork channel time series | `MEASURED_BACKEND_COUNTER` (diagnostic) | After registration |
| Router/link power | BookSim native power | `BACKEND_ACTIVITY_MODEL` | Screen only |
| Router/link area | BookSim native area or analytical | `BACKEND_ACTIVITY_MODEL` / `ANALYTICAL_ESTIMATE` | Screen only |
| NoC energy | Accelergy bridge | `TOOL_CALIBRATED_PROXY`; ERT `PLACEHOLDER` | No |
| Accelerator energy | Timeloop/Accelergy | `TOOL_DERIVED` | No (NoC question) |
| Wire length | Hand-set / geometric proxy | Unverified | No |
| Absolute PPA | None | — | No |

---

## 7. F. Recommended architecture

### 7.1 Component graph

```
Design IR (CompileRequestV4/V5)
        │
        ▼
Candidate Generator (supported guided params; research VC/buffer extension)
        │
        ▼
Structural Validator (FabricCompiler + certificate + qualification registry)
        │
        ▼
Search Controller (grid/enumeration/random; pymoo later)
        │
        ▼
BookSim Evaluator (certified path; diagnostic path with conservation gate)
        │
        ▼
Metrics / Cost Models (certified registry; native power; DSENT later)
        │
        ▼
Pareto / Constraints / Completeness
        │
        ▼
Search Ledger (generated, rejected, evaluated, tail, provenance)
        │
        ▼
Studio / Cockpit UI (curated control + search mode)
```

### 7.2 Interfaces and data contracts

**SearchDefinition**

- References `base_design_hash`, `definition_id`, domain, objectives, constraints, method, budget, seed.
- Reuses `OptimizationDefinition` / `MultiScenarioStudy`; do not create a parallel definition type. **REASONED PROPOSAL**

**CandidateEnvelope**

- `candidate_id` (content hash), `base_design_hash`, `patch`, `request_hash`, `status` (`VALID`/`ALIAS`/`INVALID`/`NOT_EVALUATED`), `reasons`.
- Reuses `Candidate` / `StudyCandidate`. **VERIFIED IN CODE**

**EvaluationRecord**

- `candidate_id`, `run_hash`, `binary_sha256`, `trace_sha256`, `config_sha256`, `profile_id`, `seed`, `network_clock_hz`, `question`, `metrics`, `metric_fidelities`, `conservation`, `p50/p95/p99_available`, `queue_available`, `status`, `reason`, `evidence_ref`.
- Reuses `EvidenceCache` and `assert_execution_gate`. **REASONED PROPOSAL**, grounded in existing fields.

**CostRecord**

- `estimator_id`, `estimator_version`, `inputs`, `fidelity`, `confidence`, `value`, `unit`, `provenance`.
- One record per estimator; never a merged “energy.” **REASONED PROPOSAL**, consistent with `energy_fidelity.py`.

**SearchLedger**

- Definition, universe size, generated candidates, aliases, invalid candidates with reasons, evaluated candidates, failures/timeouts, tail/not-evaluated identities, Pareto IDs, selection rationale, simulator/binary revisions, cost-model identities, completeness.
- Reuses `SearchCompleteness`, `BuildLedger`, `accounting_summary`. **VERIFIED IN CODE** / **REASONED PROPOSAL**

### 7.3 Minimal changes

1. **Fix the diagnostic path before calling it evidence.** Add `assert_execution_gate` to `design_sim.py`; parse p99 and native power; align torus `use_noc_latency` with its qualification or label it diagnostic. **REASONED PROPOSAL**
2. **Add a search endpoint or extend the existing optimizer.** Use `OptimizationDefinition` + `search_candidates` + `Optimizer.optimize_certified` for supported dimensions; add a ledger. **REASONED PROPOSAL**
3. **Extend the metric registry only when the metric is real.** Add p99/queue as registered authorities only after the parser and conservation evidence are wired. **REASONED PROPOSAL**
4. **Add VC/buffer support only with a proof.** A VC/buffer intent must carry the deadlock/VC-assignment obligation and a qualification scope; otherwise keep it diagnostic. **REASONED PROPOSAL**
5. **Add a cost screen, not a cost objective.** Use BookSim native power; keep DSENT/ORION for finalists. **REASONED PROPOSAL**

### 7.4 What not to do

- Do not create a second design IR.
- Do not duplicate `family_registry`, `TopologyIntent`, or the certificate.
- Do not bypass `FabricCompiler`.
- Do not call the diagnostic `design_sim` output “certified.”
- Do not call a seeded-random surrogate “Bayesian optimization.”
- Do not claim 9×9 support in the 64-router AI pilot without changing its limits and proving the evidence path.
- Do not create a new Git branch for this work.

---

## 8. G. Experimental protocol

### 8.1 Baselines

1. **Curated control set** — the current five cockpit candidates: mesh 1 VC, mesh 2 VC, torus 2 VC, mesh 4 VC, 8×8 ablation. These are the explanatory control, not the search.
2. **Exhaustive search** — all valid candidates in the declared finite space.
3. **Random search** — seeded sample of the same valid universe, same evaluation budget, 5 seeds.
4. **NSGA-II/pymoo** — only if the universe exceeds the exhaustive budget; same evaluation budget; same objectives/constraints.

### 8.2 Initial search space (bounded)

| Axis | Values | Notes |
|---|---|---|
| Family | mesh, torus | cmesh if concentration 2/4 is qualified |
| Side | 9, 10 | 8×8 fails 74 system endpoints; 11/12 optional |
| VCs | 1, 2, 4 | Torus ≥2; mesh 1/2/4 diagnostic unless class-VC qualified |
| Link width | 128, 256 | 64–512 allowed by `CandidateSpec` |
| Buffer depth | 2, 4, 8 | **Not yet exposed**; add only with qualification |
| Routing | DOR_XY, DOR_TORUS_XY | Torus requires exact 2-VC dateline |

Without buffer depth: `2 families × 2 sides × 3 VCs × 2 widths = 24`, minus torus 1 VC (4) = **20 candidates**. This is small enough for exhaustive BookSim. **REASONED PROPOSAL**

### 8.3 Identical conditions

- Same trace file and SHA-256.
- Same BookSim binary and SHA-256.
- Same config generation except the candidate variable.
- Same seed(s), sample period, timeout, and network clock.
- Same qualification path (or explicit diagnostic label).
- Same conservation gate and failure taxonomy.

### 8.4 Metrics

**Must report:**

- Valid candidate coverage (valid / universe).
- Simulation completion rate (completed / attempted).
- Completion cycles (certified).
- Packet latency mean, p50/p95/p99 if emitted; otherwise `UNMEASURED`.
- Throughput / accepted packet rate if registered.
- Queue occupancy if the diagnostic path is used; label diagnostic.
- Pareto membership and frontier, only over measured objectives.
- Number of BookSim calls.
- Wall-clock time.
- Reproducibility (same seed → same hashes/results).
- Sensitivity to seeds and traffic patterns.

**Must not report:**

- A single composite score mixing network and cost.
- A cost objective from placeholder values.
- A p99/queue value when the metric was not emitted.
- A “best” claim from a budgeted or unbounded search.
- An optimizer win without a like-for-like baseline.

### 8.5 Acceptance criteria

- **Exhaustive:** `SearchCompleteness.EXHAUSTIVE`; all valid candidates evaluated; no tail.
- **Random:** `BUDGETED` or `UNBOUNDED`; reported as “best observed,” not optimal.
- **Conservation:** every evaluated candidate passes `assert_execution_gate`; failures are recorded, not scored.
- **Fidelity:** every metric has a declared authority; cost has a declared estimator and confidence.
- **Reproducibility:** rerunning the same definition/seed produces the same candidate IDs and run hashes.
- **Honesty:** the UI shows the search space, rejected reasons, tail, and metric availability.

### 8.6 Expected outcome (not a claim)

The current curated diagnostic comparison found 2-VC mesh at 182 cyc / 13.9 queue cyc/flit vs 2-VC torus at 271 / 23.3. A certified/exhaustive search should either reproduce that ordering under the qualified path or explain the difference. Do not assume the curated result survives certification. **REASONED PROPOSAL**

---

## 9. H. Implementation roadmap

Each stage is independently verifiable and can stop without breaking the certified path.

### Stage 0 — Freeze the audit (this report)

- **Deliverable:** this document.
- **Acceptance:** every major claim labeled; no code changes.

### Stage 1 — Make the diagnostic cockpit path honest

- Add `assert_execution_gate` to `design_sim.py` (loaded/injected/delivered/flits; per-class when available).
- Parse p50/p95/p99 and `Total Power`/`Total Area`.
- Enable `sim_power=1` for a native-power screen.
- Align torus `use_noc_latency` with the qualified profile or label the run `DIAGNOSTIC`.
- Add tests for conservation, missing completion, unstable/abort, timeout, and p99 absence.
- **Acceptance:** every cockpit run proves conservation; no numeric fallback; torus label is explicit; `sim_power` output has model provenance.

### Stage 2 — Bounded search on supported dimensions

- Use `OptimizationDefinition` + `search_candidates` + `Optimizer.optimize_certified`.
- Search topology family, link width, concentration, radix, workload parallelism; **not** VC/routing.
- Add a search ledger with `SearchCompleteness`, valid/alias/invalid/not-evaluated, failures, Pareto.
- Expose it in Studio; keep the curated set as a control.
- **Acceptance:** exhaustive or budgeted as declared; no VC/routing; reproducible; no cost objective.

### Stage 3 — Research VC/buffer search

- Add a V4/V5 intent for VC count/buffer depth with a certificate obligation and qualification scope.
- Prove deadlock/VC assignment; do not bypass `FabricCompiler`.
- Keep the 9×9 1/2/4 VC diagnostic path labeled until the proof lands.
- **Acceptance:** certificate PASS; qualification entry; no unqualified “certified” result.

### Stage 4 — Cost screen

- Use BookSim native power for every point-to-point candidate.
- Add a DSENT adapter for finalists; keep fidelities separate.
- Add sensitivity when the cost model changes.
- **Acceptance:** cost is a screen, not an objective; estimator identity and confidence in the ledger.

### Stage 5 — Multi-objective scaling

- Add pymoo/NSGA-II only if the universe exceeds the exhaustive budget.
- Compare against random/exhaustive at the same evaluation budget.
- Report hypervolume/Pareto coverage and seed sensitivity.
- **Acceptance:** no optimizer-superiority claim without a like-for-like comparison.

### Stage 6 — Finalist physical validation

- Use OpenROAD/DSENT for one selected design with a PDK.
- Keep it out of the search loop.
- **Acceptance:** post-synthesis/post-layout provenance; no extrapolation to other candidates.

### Stage 7 — UI integration

- Studio: search mode + ledger + Pareto + fidelity labels.
- Cockpit: curated control + search mode; no auto-adopt.
- **Acceptance:** generated/pruned/evaluated/tail visible; no “best” without completeness; cost labeled.

---

## 10. I. Final recommendation

### 10.1 Selected approach

**A. Exhaustive enumeration with structural pruning**, using the existing certified optimizer for supported dimensions and a guarded diagnostic path for the 9×9 VC/buffer research question. Add **D. two-stage hierarchical search** as the scaling path. Add **B. pymoo/NSGA-II** only when the universe outgrows exhaustive. Defer **C. Bayesian/surrogate** until a validated surrogate exists. Use **E. RapidChiplet** only for chiplet-level inter-die DSE.

### 10.2 Why the alternatives lose

- **B (pymoo/NSGA-II) now:** the current space is ~20 candidates; exhaustive is cheaper, deterministic, and auditable. NSGA-II adds stochasticity and a dependency without improving coverage.
- **C (Bayesian/surrogate) now:** no validated surrogate; the current “BO” path is seeded random; the 150k-simulation ML paper is far beyond the budget. A surrogate would predict simulations, not replace them, and must be validated.
- **D (multi-fidelity) without a validated screen:** a cheap analytical screen that is not calibrated can prune the true optimum. It is a scaling path, not a substitute for the first exhaustive run.
- **E (RapidChiplet) for the 9×9 fabric:** it solves inter-chiplet ICI/placement/cost, not intra-die mesh/torus trace replay; its license is unverified.
- **Timeloop/Accelergy as the NoC DSE engine:** they are accelerator-level; Timeloop has no NoC latency model; Accelergy needs action counts and a component ERT. Using them would be a category error.
- **Optimizing the current cost numbers:** they are placeholders; the optimizer would rank the placeholder, not the design.

### 10.3 What this means for the product

- The curated cockpit set remains the **control**; the search is a separate mode.
- The first real search should be **network-performance-only**.
- The first real search should report **generated → pruned → evaluated → not evaluated → Pareto**.
- The first real search should not claim absolute optimality unless it is exhaustive.
- The first real search should not call p99/queue “certified” until those metrics have authorities and conservation evidence.
- The first real search should not call energy/wire a constraint until a credible cost model exists.

### 10.4 The one-sentence answer

> The technically defensible path is a guarded, exhaustive network-performance search over a declared finite 9×9/10×10 topology/VC/link-width space, using the existing V4/V5 IR, FabricCompiler certificate, BookSim conservation gate, and search-completeness ledger — with cost kept as a separately labeled screen and no optimizer claim stronger than the evidence.

---

## Appendix A — Key repository references

| Topic | File / function | Lines |
|---|---|---|
| V4 design root | `model/compile_request_v4.py` `CompileRequestV4` | 79-130 |
| V5 extensions | `model/compile_request_v5.py` `CompileRequestV5` | 130-180 |
| Topology intents | `model/topology_intent.py` | 1-220 |
| Family registry | `model/family_registry.py` `BOOKSIM_TOPOLOGIES` | 70-140 |
| Compiler | `application/fabric_compiler.py` `FabricCompiler.compile` | 136-384 |
| Certificate | `verification/certificate.py` `verify_compiled_fabric` | 541 |
| Certificate obligations | `verification/certificate.py` | 24-40 |
| Deadlock CDG | `verification/certificate.py` | 270-393 |
| BookSim parser | `backend/booksim_execution.py` `parse_booksim_stats` | 338-421 |
| Conservation gate | `backend/booksim_execution.py` `assert_execution_gate` | 423-505 |
| Channel series | `backend/channel_series.py` | 1-60 |
| Channel measurements | `backend/channel_measurements.py` `parse_channel_activity` | 74-140 |
| Qualification registry | `application/booksim_qualification_registry.py` | 90-330 |
| Optimization definition | `optimization/definition.py` `OptimizationDefinition` | 203-345 |
| Locked knobs | `optimization/definition.py` `_LOCKED_TOKENS` | 31-61 |
| Search methods | `optimization/definition.py` `SEARCH_METHODS` | 17 |
| Search | `optimization/search.py` `search_candidates` | 20-90 |
| Completeness | `optimization/completeness.py` `SearchCompleteness` | 25-135 |
| Pareto | `optimization/pareto.py` | 9-76 |
| Optimizer | `optimization/result.py` `optimize_certified` | 1005-1029 |
| Real evaluator | `optimization/real_evaluator.py` | 119-240 |
| AI proposal limits | `optimization/topology_search.py` `LIMITS` | 24-25 |
| AI UI | `apps/studio/src/components/AITopologySearch.tsx` | 98-103 |
| Studio Pareto | `apps/studio/src/components/OptimizeView.tsx` | 94-250 |
| Cockpit endpoint | `gateway/app.py` `/api/v1/loom/design/simulate` | 821-829 |
| Cockpit config | `gateway/design_sim.py` `_config_text` | 268-305 |
| Cockpit `sim_power` | `gateway/design_sim.py` | 295 |
| Native power | `scripts/native_power.py` | 1-80 |
| Energy bridge | `scripts/noc_energy_bridge.py` | 131-260 |
| Energy fidelity | `reports/energy_fidelity.py` | 10-85 |
| Analytical reports | `reports/reports.py` | 38-360 |
| IP catalog refusal | `model/ip_catalog.py` | 136-165 |
| BookSim metadata | `third_party/booksim2/METADATA.json` | — |

## Appendix B — External sources

- Timeloop/Accelergy tutorial: <https://accelergy.mit.edu/tutorial.html>
- Timeloop issue #177 (NoC latency/energy limits): <https://github.com/NVlabs/timeloop/issues/177>
- DSENT README: <https://github.com/beneslami/dsent>
- DSENT paper: <https://projects.csail.mit.edu/wiki/pub/LSPgroup/PublicationList/dsent_nocs12.pdf>
- ORION 3.0 paper: <https://vlsicad.ucsd.edu/Publications/Journals/j113.pdf>
- PAT-Noxim: <https://github.com/amin-norollah/PAT-Noxim>
- pymoo: <https://github.com/the-dual-space/pymoo>
- Optuna: <https://github.com/optuna/optuna>
- OpenROAD: <https://github.com/The-OpenROAD-Project/OpenROAD>
- NOCTOPUS: <https://link.springer.com/article/10.1007/s00521-026-12049-4>
- BookSim ML DSE: <https://arxiv.org/abs/2512.07877>
- MOOS: <https://dl.acm.org/doi/10.1145/3358206>
- Palesi/Givargis genetic DSE: <https://www.cecs.uci.edu/conference_proceedings/codes_2002/palesi_multi.pdf>
- RapidChiplet: <https://github.com/spcl/rapidchiplet>, <https://arxiv.org/abs/2311.06081>
- Berkeley NoC power model: <https://www2.eecs.berkeley.edu/Pubs/TechRpts/2023/Archive/EECS-2023-168.pdf>
- Chiplet assembly DSE: <https://passat.crhc.illinois.edu/tvlsi20.pdf>
- BookSim: <https://github.com/booksim/booksim2>

## Appendix C — Open questions / unknowns

1. **VC/buffer intent:** Can the V4/V5 IR carry VC count and buffer depth without breaking the existing certificate? This requires a design decision and a proof, not a patch.
2. **Qualified mesh VC scope:** Does any qualified mesh profile cover arbitrary 2/4 VC counts, or only one-VC-per-class? The current cockpit assumes the former; the registry suggests the latter.
3. **Torus latency mode:** The qualified torus profile requires `use_noc_latency=0`; the cockpit uses 1. Which is the intended diagnostic comparison?
4. **p99/queue certification:** What producer/authority would make p99 and queue occupancy certified metrics? The parser exists; the registry does not.
5. **Cost model:** Is BookSim native power acceptable as a relative screen, or is DSENT/ORION required for the first search? The native model is already integrated; DSENT/ORION require adapters.
6. **System endpoints:** The trace has 64 compute endpoints; the revision has 74 system endpoints. The 9×9 candidates satisfy seats, but the trace does not include HBM/NIC traffic. This is a scope limitation of the workload, not a topology check.
7. **RapidChiplet license:** No license is declared on GitHub; reuse requires clarification.
8. **BookSim license:** GitHub reports `NOASSERTION`; the vendored tree has no `LICENSE` file. Legal review is required before redistribution.

## Appendix D — Glossary

- **CDG:** channel dependency graph; here, channel-VC dependency graph.
- **Certificate:** the PASS/FAIL obligations proving attachment, routing, VC assignment, and deadlock.
- **DP:** design point / candidate.
- **ERT:** energy reference table used by Accelergy.
- **pJ/hop:** energy per flit per hop.
- **Qualified profile:** a BookSim profile with a declared scope and evidence, not merely a config that runs.
- **Search completeness:** whether the evaluated set covers the declared universe (`EXHAUSTIVE`), a budgeted prefix (`BUDGETED`), or an unbounded sample (`UNBOUNDED`).

---

*End of report.*
