# Srota Studio — stitched design prototype

A **separate React prototype** reconstructed from the HTML references in `docs/design/stitch_veritx_studio_eda_frontend`. It shares one shell, design system, route catalogue, illustrative dataset, and local editable state. The original exports and existing Studio application are not modified or embedded in iframes.

## Desktop

The Tauri application shares this prototype's source and live-reloads it during development. Its packaged build includes the Python gateway and simulator sidecar; no separately running backend is needed. See [desktop setup, build, tests, and current Linux limitations](desktop/README.md).

```bash
npm --prefix apps/studio/prototype run desktop:dev
npm --prefix apps/studio/prototype run desktop:build
```

## Run

From the repository root, using the existing dependencies installed in `apps/studio/node_modules`:

```bash
npm --prefix apps/studio/prototype run dev
```

Open **http://127.0.0.1:5174/**. The prototype uses its own Vite root and browser-storage key, `srota-stitch-prototype:v1`. Port 5173 remains separate for the existing Studio.

One gateway seam exists: `/gw` is proxied to the repository gateway (`VERITX_GATEWAY`, default `http://127.0.0.1:8099`). Reads cover the project list, project detail, draft, revision topology, runs, evidence, integrity, artifacts and the evaluation plan. Writes are explicit domain operations: saving the draft, project administration, and launching an evaluation (below). Everything not listed there still renders the authored fixture. Start the gateway with:

```bash
cd tracks/t3-topology/dse && python3 -m uvicorn veritx_dse.gateway.app:app --host 127.0.0.1 --port 8099
```

If it is not running, that panel shows the failure reason and the command, and the rest of the prototype is unaffected. If dependencies are missing, install the parent Studio's declared dependencies; this prototype does not require another dependency set.

```bash
npm --prefix apps/studio/prototype run build
npm --prefix apps/studio/prototype test
npm --prefix apps/studio/prototype run test:e2e
```

Browser tests use the locally installed `/usr/bin/google-chrome`. Change that explicit test executable path for a different host. Build output and browser-test artifacts are ignored within this directory. The `public/gr00t/staticpick-v1-observation/` directory is the byte-identical generated recorded bundle from `runs/gr00t-model/staticpick-v1-observation/`, including its manifest and raw RGB24 observation frame. No Google Fonts, Tailwind CDN, icon CDN, or remote asset dependency is used.

## GR00T architecture trace

Open **Analysis → GR00T trace** (`#/analysis/gr00t`) to inspect that actual generated, recorded bundle. The read-only page shows the pinned dataset and model revisions, the actual frame, graph interfaces and operation coverage, and separate Timeloop / BookSim result scopes. This checked-in run is architecture-derived static/meta shape tracing only: no numeric model inference, no Timeloop-mapped model operators, and no model tensor-transfer trace or paired simulation results. Missing results remain explicitly missing; the existing sensor and GEMM smoke runs are not represented as model simulations.

To inspect another exported bundle, select `comparison.json`, `manifest.json`, and `observation.rgb24` together from the same output directory using **Import recorded bundle**. The local-only import validates schema, model/dataset/frame binding, graph/operator reconciliation, RGB24 dimensions and SHA-256s. Invalid imports leave the current view unchanged. It only parses and displays files; it does not upload data, execute commands, create gateway runs, or mutate a project. The generated example source is `runs/gr00t-model/staticpick-v1-observation/`.

## Guided design flow

The landing surface is `#/flow/start`, the first step of a five-step path that puts the existing editors, search, optimization and analysis components in the order an engineering decision actually happens:

1. **Start from a workload template** (`#/flow/start`) — registry-defined workload templates are shown as cards with their definitions laid out before anything is created: model identity, parallelism, collectives, agents, NOC defaults and the canonical request. Choose a template, optionally name the project, and create it. This step does not ask the user to choose a fabric preset.
2. **Workload intent** (`#/flow/tune`) — edit and save parallelism, collectives, payload sizes, declared compute stages and requirements. Do not select a fabric or invent compute timing from a model name here.
3. **Evaluate & choose fabric** (`#/flow/search`) — launch, evaluate, inspect and select on this one canonical page. Before launching, four profile cards appear unranked ("Awaiting run"); freeze the saved workload and submit one process-isolated job over all 12 typed fabric families by default. Each candidate preserves workload, agents, controls, physical assumptions and requirements; the compiler maps it and the adapters generate BookSim packet traces and ASTRA-SIM execution graphs. Both backend verdicts remain visible, including refusal or missing execution support. A four-fact summary reports the chosen fabric, lowest measured network and system values and the selectable count; four compact objective controls (Network, System, Balanced, Best evidenced) then name a measured winner or its stated absence. The comparison table and the selected fabric's measurement inspector share one workbench, with an optional shared trade-off plot of network completion against system makespan. Only requirements-satisfying fabrics with both measurements are plotted; refusals, compile failures and unmet requirements stay in the measured table. Explicit selection re-verifies network evidence, requirements, the sealed result manifest and draft compatibility, then navigates to `#/flow/optimize`. Missing backend coverage requires acknowledgment; changing the workload/controls invalidates selection from the old campaign. No repository trace or model connection is required.
4. **Refine fabric parameters** (`#/flow/optimize`) — keeps the selected fabric's catalog-time network, system, requirement and VC facts in view, then edits the complete topology-specific, physical, arbitration, buffer, credit, allocator and pipeline controls in grouped sections. AI assistance proposes and evaluates changes to this selected family's existing knobs, never a new workload or family; model setup and outbound consent live here. The pinned save bar reports compile state, Save & compile pins the returned saved version, and unsaved changes and failed compilation block progression.
5. **Finalize topology & RTL** (`#/flow/run`) — evaluate the compiled final revision and inspect its actual evidence. General simulation-equivalent RTL export is not connected. The existing emitter can produce a clearly labeled, consented topology-only 64-bit/2-VC preview for supported point-to-point graphs, with actual SystemVerilog, a manifest and Verilator lint when available. The preview also emits `addr_decode.sv` from the resolved address map (a decoder, not a firewall); routing, VC policy, the side buffer and Plane T remain outside the preview. Shared-wire or otherwise unsupported graphs are refused rather than rewritten.

`#/flow/compare` remains registered as a hidden compatibility alias resolving to `#/flow/search`, not a separate results-only page. Flow has five visible steps; the registry retains all 55 route IDs.

Every step names the full workspace that already owns its evidence — Workloads & requirements, Reference catalog, Curves & Pareto, Revision study, Analysis, Run evidence, Delivery manifest — so the flow is the index into those surfaces rather than a second copy of them.

The flow is an orchestration surface, not a second data model. Project creation, draft saves, compiles and evaluations retain their existing gateway authorities. Catalog evaluation adds pinned `/projects/{id}/catalog-evaluations` jobs, sealed generated-input downloads and explicit candidate selection; AI parameter jobs reuse the existing isolated proposal/evidence lifecycle. The detailed Design, Workloads, Analysis, Explore, Verify and Deliver workspaces remain available for drill-down and reference work.

## Project study and reference comparisons

The workspaces are separated by scope. **Explore → Fabric Search** (`#/explore/fabric-search`) ranks catalog fabrics for a selected measured workload: the workload is the input, and topologies plus buffer configurations are the ranked objects. It shows a visual recommendation grid with relative bars, a measured latency/throughput trade-off chart and a selected-fabric strip; limits and audited knobs sit behind **Refine search**, and the full measured table sits behind **Measured configurations**. **Explore → Revision study** (`#/explore/brief`) owns the project's measured optimization study: the recommendation, the bounded study, the candidate analysis and adoption. **Analysis → Curves & Pareto** (`#/analysis/curves`) keeps the measured workload reference: packet latency, hops, VCs, modeled power/area, energy ratios, power–delay product and the buffer-depth sweep. **Explore → Fabric Ablations** (`#/explore/fabric-ablations`) is the repository reference workbench: it separates the uniform Repository sweep, including the power-versus-load view, from the measured Workload ablation and mounts the same one-plot / one-inspector / one-table workbench for both. **Explore → Workload Ablations** (`#/explore/ablations`) is the broad multi-workload × multi-topology matrix and tuning surface. The project study and the workload reference stay separate; a project study is never presented as the repository reference, and the reference is never presented as the project's candidates.

The Fabric Ablations load-matched explorer reads the latest `topology_sweep.json` from `tracks/t3-topology/runs/supported-sweep/` (the root or one named-run directory) through `GET /api/v1/analysis/topology-sweep`. Refresh is read-only; it never launches a tool. If the gateway/read fails, the bundled snapshot is explicitly labelled, with the failure reason.

**Fabric Ablations** owns one job: the repository injection-rate sweep, with plot presets that are axis recipes over the same observations rather than separate pages: latency versus offered load, the common-load trade-off, path length (hops) and the last-stable operating point. Changing a preset or an axis updates the same canvas, scale and inspector, and the pinned observation survives a preset change. The uniform sweep is generated only for `traffic = uniform`, so it has no workload axis; a trace workload is never folded into an injection-rate curve.

**Explore → Workload Ablations** (`#/explore/ablations`) is the measured workload × topology trace replay (`public/data/workload_ablation.json`, 11 workloads × 12 topologies). The workload is the independent axis and the fabric is the variable under comparison. Cross-arm comparison requires one trace hash, simulator binary and seed; unequal resources stay visible rather than being equalised. Scope, provenance and every non-claim sit in the single **Assumptions & scope** block at the bottom of the page, not between the controls and the data.

Every page follows the same anatomy: heading, one toolbar row, the working body, then one **Assumptions & scope** disclosure. A `Notice` is reserved for state the operator must act on now — error, unavailable data, a blocked action, or a selection outside coverage.

Charts are interactive SVG, not raster screenshots: hover/focus a point for exact values, click/Enter/Space to pin, and use the linked inspector to see metrics, qualification and dominance/exclusion reasons. **Fit data**, **Include zero** and **Front only** make dense scatter plots inspectable; overlapping points remain keyboard- and list-selectable. Selecting an arm in the picker isolates its latency curve; **Show all arms** restores the comparison. The pinned inspector carries the same identity across presets. Large data tables, constraints, extra objectives and the opt-in native estimates are progressively disclosed rather than always expanded. Technical provenance and script-coverage audits stay out of the user-facing page; the comparison export retains the source path, digest, objectives, constraints and observation records. These interactions never run a simulator, adopt a design or recompute an engine-owned study's membership.

Generate fresh observations from the repository root:

```bash
python3 tracks/t3-topology/scripts/sweep_supported.py --native-power --copy-to-prototype
# Keep a separately named run and its logs/configs/model inputs:
python3 tracks/t3-topology/scripts/sweep_supported.py --native-power --out tracks/t3-topology/runs/supported-sweep/my-run
```

Select a common workload, packet/flit size and offered load, then two plot axes: latency, hops, accepted throughput, router count, crosspoints or buffer capacity. Expand **Refine comparison** to add front objectives; front membership uses all selected objectives, not just the 2D projection. Exploratory constraints apply before Pareto dominance. Failed/missing observations, unavailable constrained metrics and points at or past first instability cannot enter the front; a row missing either plotted axis is marked **Not plotted**, never assigned a value. Equal points both survive. Export includes the source path, gateway SHA-256, objectives, constraints, candidate observations and exclusion reasons.

Structural counts are **not mm²**. **Include BookSim native estimates (research only)** enables separately labelled modeled power (W), area (mm²) and network energy/cycle (pJ/cycle) objectives and budget filters when the snapshot carries scoped native evidence. The bundled sweep has 143 attempted observations over 13 arms; 46 steady-state observations across 7 point-to-point arms carry native estimates. SROTA/GEC realizations remain unsupported/unaudited and are excluded from native comparisons, not assigned zero. Different native model identities are refused.

The technology input is BookSim's **2007 ITRS 32nm prediction**, with 128-bit flits and its own ~9.712 GHz model clock—not the project's clock or silicon calibration. Energy/cycle is `native power / model clock × 1e12`; under the common clock it ranks identically to native power. It is **not energy per packet**: power counters and steady-state packet statistics use different observation windows. Native model inputs, executable/technology digests and limitations are exported with candidate records; configs, logs and a technology snapshot remain under the run directory.

`public/data/workload_power.json` backs the workload reference on Analysis → Curves & Pareto. It joins each workload's depth-8 trace replay with `sim_power=1`, the BookSim power/area summary in the run log, and the same trace hash as `workload_ablation.json`. Regenerate it with `python3 apps/studio/prototype/scripts/build_workload_power.py`. Ten workloads use one binary and model id across all twelve arms; Qwen3-MoE is an older run in which only five arms report native power, so its other seven stay visible for latency, hops and throughput but are absent from power and energy axes. The workload power runs use the newer shared-wire model (`native-full-swing-tapped-grid/v1`) and therefore report SROTA/GEC arms that the older uniform sweep excludes; every arm still carries `qualification: NOT_ESTABLISHED` and the same “not silicon calibrated” limitation.

Timeloop/Accelergy accelerator energy is not substituted for NoC energy; the existing NoC ERT is placeholder-calibrated. The legacy `energy_score.py` accepts an explicit `noc_pj_per_hop` or environment override, never `total_pj_per_compute`; its constant-based score remains a proxy. Analytical report area estimates remain comparison-only; the opt-in axes above use the separate native backend model, not those estimates.

## Fabric recommendation (Explore)

`#/explore/brief` is a goal- and constraint-driven advisor, not only a study form. It joins three evidence sources:

| source | use |
|---|---|
| `public/data/workload_ablation.json` | measured trace replay for 11 workloads × 12 topologies at 64 endpoints |
| `public/data/topology_sweep.json` | native BookSim power/area family references at a common offered load |
| `public/data/design_sensitivity.json` | measured buffer-depth variants (4 / 8 / 16 flits per VC) for the five product arms |

Select a measured workload and a priority (latency, throughput, modeled power, modeled area, or balanced), then add optional hard bounds for P95 latency, delivered throughput, modeled power, modeled area, or buffer storage. The page recommends the leading measured topology plus virtual-channel count, measured depth/VC, routing and the reference flit width; it shows the runner-up and recomputes which tested constraint threshold would replace the winner. Unavailable power/area evidence excludes a candidate from a power/area bound instead of becoming zero.

When a live project is loaded, the **Only families the backend reports executable** filter is on by default. The unfiltered evidence leader is still named when it is not reported executable, so the page does not hide the difference between “best measured” and “the capability report permits it”. **Carry shortlist into measured study** prefills the bounded study with supported families and two declared link widths; buffer depth is not a study dimension, so it remains a recommendation for the next draft. The study still requires explicit approval. It is a narrow revision study, separate from the guided flow's full catalog evaluation.

Power and area are **modeled screening estimates**, not measured silicon: the native BookSim 32nm model reference is a 16-endpoint row, scaled linearly by endpoint count at the workload's nearest common offered load. Link/flit width is held at 128 bits by the measured slice; no width optimum is claimed. The page states these limits rather than filling them with an invented value.

## Scope

The supplied exports and prompt-only surfaces are represented by explicit routes (6 Flow route IDs in 5 visible steps, 9 Design, 7 Workloads & Requirements routes in 4 navigation views, 9 Analysis, 5 Explore, 5 Verify, 5 Deliver, 3 shared desktop, 4 optional-agent):

### Flow

- `#/flow/start` — Start from a workload template
- `#/flow/tune` — Workload intent
- `#/flow/search` — Evaluate & choose fabric
- `#/flow/compare` — hidden compatibility alias resolving to `#/flow/search`, not a separate results-only page
- `#/flow/optimize` — Refine fabric parameters
- `#/flow/run` — Finalize topology & RTL

### Design

- `#/design/fabric-topology` — Fabric Topology
- `#/design/system` — System / Block Diagram
- `#/design/catalog` — IP Catalog
- `#/design/endpoints` — Hardware Endpoints
- `#/design/mapping` — Initiator–Target Mapping
- `#/design/agent-map` — Agent Fabric Map (agent groups, address windows, resolved decode)
- `#/design/addresses` — Address Map
- `#/design/domains` — Clock & Power Domains
- `#/design/placement` — Placement Constraints

### Workloads & Requirements

- `#/workloads/workflow` — Project & Revision Workflow
- `#/workloads/library` — Workload (identity, traffic, compute stages)
- `#/workloads/requirements` — Requirements (criteria + measured verdicts)
- `#/workloads/lowering` — Validate (declaration checks + model inputs)
- `#/workloads/editor`, `#/workloads/bindings`, `#/workloads/assumptions` — legacy routes kept working; they open the consolidated view and are hidden from navigation

### Analysis

- `#/analysis/summary` — Analysis Summary
- `#/analysis/gr00t` — GR00T Architecture Trace (recorded static/meta bundle; no model simulations)
- `#/analysis/fabric` — Fabric Analysis (addresses, routing shapes, port budget, islands, RTL reach)
- `#/analysis/matrix` — Traffic Matrix
- `#/analysis/missing` — Explicit missing-artifact scenario
- `#/analysis/topology` — Logical Topology Overlay
- `#/analysis/metrics` — Supported Metrics
- `#/analysis/trace` — Requested injection timeline, source/activity summaries, and independent example viewer
- `#/analysis/curves` — Measured workload analysis (power, area, hops, energy, VCs); project study analysis is in Explore → Revision study
- `#/analysis/comparison` — Run Comparison

### Explore

- `#/explore/brief` — Fabric Recommendation & Study Brief
- `#/explore/progress` — Study Execution & Budgets
- `#/explore/results` — Candidate Results & Trade-offs
- `#/explore/comparison` — Candidate Comparison
- `#/explore/adoption` — Candidate Adoption / Branch

### Verify

- `#/verify/overview` — Evidence Overview
- `#/verify/support` — Configuration Support Checks
- `#/verify/checks` — Check Setup & Results
- `#/verify/obligations` — Outstanding Obligations
- `#/verify/evidence` — Evidence Detail / Claim Scope

### Deliver

- `#/deliver/readiness` — Output Readiness
- `#/deliver/configuration` — Output Configuration
- `#/deliver/job` — Generation Job / actual local export preparation
- `#/deliver/package` — Package Review & Manifest
- `#/deliver/artifacts` — Artifact Inspection & Export

### Shared desktop

- `#/shared/projects` — Projects, Revisions & Recovery
- `#/shared/environment` — Environment & Local Settings
- `#/shared/jobs` — Jobs, Problems & Logs

### Optional agents (disconnected)

- `#/agents/assistant` — Contextual Assistant
- `#/agents/runtime` — Runtime Connection & Permissions
- `#/agents/approvals` — Approvals, Scope Changes & Activity
- `#/agents/workload-translation` — Requirements to Editable Workload

The route catalogue in `src/model.ts` records the source export directory for every view. The catalogue covers the supplied design exports plus the prompt-only surfaces (`workloads_requirements_project_workflow`, `analysis_curves_pareto`, `analysis_workload_ablations`, `explore_fabric_ablations`, `explore_workload_search_recommendations`, `explore_revision_recommendation_study`, `design_agent_fabric_map`, `analysis_fabric_static_checks`). `tests/prototype.spec.ts` asserts that every directory holding a `code.html` has exactly one route and that the non-export sources match that list. Logs & Artifacts is no longer a route: the local activity list and the run-bundle manifest live in Jobs & activity and Verify → Evidence, and no gateway job-log stream exists to fill a separate panel. The Requirements-to-Editable-Workload export arrived after the first 42 and is held to the same rule: it shows the working inputs a translation would have to produce plus the review gate, while the export's agent claims (active job, DRC-clean, drafting AI, synthesized phase windows) are dropped because no parser, model, or backend exists. Optional AI is **not** connected: there is no transport, handshake, credential lookup, model call, or permission grant. New Evaluation is a reviewable Analysis drawer; an executable backend configuration is not fabricated. The missing-artifact route is explicitly an alternate fixture scenario, not a mutation of SIM-402’s recorded counts.

## Live project data (Design surfaces)

`#/shared/projects` lists the repository gateway's real projects. Loading one switches these Design surfaces from the authored fixture to live store data:

| surface | live source | explicit gaps shown |
|---|---|---|
| Fabric Topology | revision topology: routers, directed channels, MECS shared wires, declared planes, endpoint attachments; compile-result: derived router behavior, deadlock proof, Plane C subnet, rank→endpoint mapping; schema-v4 fabric-wide buffer-depth edit with save + recompile | utilization, queue occupancy, achieved timing; per-router independent configuration; Plane T is a declared overlay, not a separate topology |
| System / Block Diagram | system-composition diagram: workload, agent groups, attached endpoint seats, fabric, derived certificate; request agents, workload, `noc_controls` | simulation results; physical placement or traffic |
| Hardware Endpoints | declared agent counts + topology endpoint seats | address assignment, permission, protocol behaviour, CDC |
| Initiator–Target Mapping | connection-incidence matrix (directed channels or MECS driver→tap taps), router adjacency derived from channels, address-window summary | access permission, guaranteed reachability, observed traffic |
| Agent Fabric Map | editable agent groups (`data_width`, `addr_width`, `protocol`, clock/power domain) and `address_map.ranges` with FIXED_INSTANCE/STRIPED selection; `topology-preview` validation, draft save, compile; resolved rows from `compileResult.groups.address_decode` | per-initiator permission/firewall, protocol adaptation, CDC; the compile schema has no permission field |
| Address Map | `request.address_map.ranges` + `compileResult.groups.address_decode` | overlap, mapped union, target coverage and resolved decode are computed; permissions are not modelled |
| Clock & Power Domains | `request.physical` (clock MHz, data width, power-domain count, process node) | per-agent clock assignment, CDC, power intent, achieved timing |
| Placement Constraints | logical router coordinates | floorplan, die outline, physical constraints, area/congestion |

### Router inspection is fabric-wide

Selecting a router joins `GET /revisions/{id}/topology` with `GET /revisions/{id}/compile-result`. The inspector shows the one `RouterBehaviorArtifact` the revision carries (VCs, buffer depth, allocator, flow control) and the deadlock proof and its witness/evidence. Because the engine has one router behavior for the fabric, there is no per-router microarchitecture override: a selected router cannot have a different VC count or buffer depth without changing the design model. The editable control is schema-v4 `noc_controls.input_buffer_depth_flits_per_vc`, scoped in the review dialog to every router/port/VC; applying it writes the draft, compiles, and selects the new revision. Old runs remain attached to the revision that produced them. A schema-v3 draft is refused on this surface rather than silently migrated.

### SROTA planes are separate views

The data plane (D) draws the directed channels and, for SROTA, the MECS shared wires as dashed driver→taps lines. The control plane (C) is only selectable when the revision declares it and the compile result carries the canonical control-plane artifact; it is a separate `k×k` XY mesh with REQ/RSP/SNP VCs and a class→subnet binding, marked declared-structure-only. The telemetry plane (T) has no separate router/channel artifact in the engine; the view shows its declared period/latency and draws an explicitly illustrative ring overlay on Plane D rather than inventing a network or a per-router telemetry scope. Selecting a non-data plane clears the router selection; Plane C/T carry no per-router controls.

Shared wires are part of the canvas, not only a table below it. The tree’s **Wires** tab lists every multidrop wire; selecting one isolates and labels it on the graph, dims the others, and shows driver/taps/width/latency in the wire strip and inspector. The wire table remains linked to the same selection.

The **Parallelism overlay** joins `compile-result.groups.mapping` to endpoint seats. Selecting TP, DP, EP or PP paints one satellite per attached endpoint, coloured by that endpoint’s declared coordinate, and outlines groups when the degree is small enough to read. The **Parallelism mapping** card lists group→ranks→routers and the declared degrees; endpoints with no mapping row stay grey and are never assigned a rank. Axes with degree 1 are disabled rather than pretending to show partitioning.

The System/Block Diagram surface has a **system composition** diagram: workload on the left, declared agent groups, derived endpoint seats, and the fabric. Its arrows are composition/attachment only; the surface does not derive a floorplan or a traffic path. The Initiator–Target surface has a **connection-incidence matrix** over routers. It can show declared directed channels or MECS driver→tap incidences as separate layers; a filled cell is a declared resource between a router pair, not access permission, reachability, or observed traffic. Because the request carries no initiator/target rules, the surface shows that absence explicitly rather than drawing candidate edges.

IP Catalog has no live equivalent and keeps the fixture with a banner naming the loaded project.

Geometry is not hardcoded: a 3×3 mesh (9 routers, 24 directed channels) and a 64-router `custom` family render from the same channel list. SROTA renders from its `shared_links` as well: MECS wires are drawn as dashed driver→taps lines and are not flattened into point-to-point channels. Families that supply no router coordinates get a derived layout that is labelled as derived in the caption, and endpoint-count labels are hidden above 40 routers.

## Live runs (Analysis and Verify surfaces)

Loading a project also selects its newest run that has a backend evaluation (a bundle-only compile record is skipped rather than opened as an empty page). The run picker switches runs without leaving the page.

| surface | live source | explicit gaps shown |
|---|---|---|
| Analysis Summary | `GET /runs/{id}`: status, qualification + basis, requirement entries with verdicts and metric authority, fidelity warning, analyses | nothing computed locally; empty when a run carries no evaluation block |
| Metrics | `evaluation.metrics`: one compact window strip, one values table, reporters named once | caveats (no percentiles, histogram, transaction P95, power/area/timing, cross-run claim) are collapsed under “What these metrics do not claim” |
| Traffic Matrix | `GET /runs/{id}/traffic-matrix`: full packet/flit heatmap with source and destination marginals, active-pair and top-pair-share KPIs, top-flow and class-mix bars, per-class packet/flit matrices when the trace aggregation supplies them, flow-pattern grouping, and a searchable pair list | per-link counters, per-pair latency, observed routes; an absent per-class matrix is never inferred from aggregate class counts |
| Traffic Topology Overlay | declared channels (widths, latency) from the revision document in an independently scrolling, filterable list; measured link detail with an active-channel picker and stacked queue/arbitration/transmit split | per-directed-link busy cycles: the run does not report them, so no utilization color is drawn |
| Trace Viewer | trace paths from the run bundle: requested-injection KPIs, a timeline stacked by traffic class, busiest source/destination activity windows, packet-size distribution, and packet latency when `packets_out.csv` exists | no observed packet-hop trace and no synthetic trace; no per-flow latency from aggregation; the routing dump is a verification input, not a standalone first-hop view |
| Memory (DRAM timing) | a `DRAM_TIMING` analysis with `RAMULATOR2_HBM3_V1`: memory completion cycles, average read latency, row hit/conflict/miss counts, read/write bytes, queue occupancy, request completion, and stated limitations; row outcomes use counts and per-request rates instead of a shared linear bar when hits dominate | no NoC/memory composition and no additive network+memory runtime; no per-request histogram; no calibrated bandwidth claim |
| Run Comparison | second run read on demand, per-metric differences | comparability warning when revision or workload differ; no confidence intervals or significance |
| Curves & Pareto (Analysis) | a measured workload reference: packet latency, hops, VCs, native power/area, energy per packet/flit/bit/hop, power–delay product and buffer depths | project-study analysis lives in Explore → Revision study; the uniform power-versus-load reference is in Explore → Fabric Ablations; this reference is repository evidence, not the project's candidates; power/area are the native 32nm research model, not silicon; Vdd and temperature are fixed corner constants, so no P–V or P–T curve is drawn; unsupported arms stay absent rather than zero |
| Fabric Search (Explore) | catalog ablation search: workload trace + buffer depths, four ranked fabric profiles, measured latency/throughput trade-off chart, selected-fabric strip and review-only Design handoff | ranked fabric candidates are reference evidence, not the loaded revision; limits filter the recommendation cards, not the measured chart; missing/model-mismatched evidence is never zero-filled |
| Fabric Ablations (Explore) | the repository injection-rate sweep only: load curves, common-load trade-off, path length and operating point; one inspector and one data table | reference evidence, never the selected project's study or run; sources stay separate; failed/missing observations are not plotted |
| Workload Ablations (Explore) | measured workload × topology matrix, per-workload best candidate and ranking, candidate arms and the bounded tuner | unsuccessful cells are absent, not zero; arms differ in radix, VCs and buffering; no hardware-equalized claim |
| Verify · Evidence | `GET /runs/{id}/artifacts` file list, decoded evidence summaries | file bodies are not fetched or compared here |
| Verify · Checks | `GET /runs/{id}/integrity`: packet/flit conservation per stage with availability, route realization, per-analysis status | deadlock proof, functional correctness, physical checks |

### Performance evidence: measured, derived, absent

The run bundle supplies **measured** endpoint-pair packet/flit counts, aggregate packet/flit latency averages, completion/sample-window cycles, and per-channel sampled counters (flits, utilization, queue cycles, arbitration wait, transmit flits, occupancy, and peak queue/latency). The Topology analysis surface groups those channel counters by source router and attributes matched ingress by declared channel topology. This is a **source-port aggregate**, not router-internal queue occupancy or a per-initiator latency distribution.

Route attribution (trace or pair counts projected through declared routes) is **derived** and labelled as such. The trace carries timestamp, source, class, destination, and flit count per packet; the routing dump records the executed first hop, not a full observed packet path. No percentile, histogram, per-packet latency, per-class latency, power, area, energy, or wirelength result is present in the run, so none is drawn. Those require a backend artifact (for example `packets_out.csv` or calibrated energy/area output) before they can become a measured view.

Explore → Revision study shows the project's measured optimization study. A study preset plots either its declared parameter against a measured objective or two declared objectives when both exist; a single-objective study becomes a ranking, not a fabricated 2D frontier, and a study with fewer than two measured candidates is shown as a coverage statement rather than an empty chart. Analysis → Curves & Pareto keeps the measured workload reference: a trace replay per workload and topology, joined with BookSim's native 32nm power/area model. The reference exposes latency, hops, VCs, power, area, energy per packet/flit/bit/hop, power–delay product and the measured buffer-depth sweep. Its power/area numbers are research-model estimates, not silicon; Vdd and temperature are fixed technology constants, so no voltage or temperature curve is invented. The uniform power-versus-load reference is in Explore → Fabric Ablations, which keeps the repository sweep and workload ablation as separate reference sources inside the same workbench. Selected-run evidence stays on Analysis Summary, Metrics and Verify; a single aggregate run is never expanded into a synthetic sweep.

Loaded projects now use live bounded optimization, revision-manifest delivery, capability/gap registries, and the server-mediated AI topology workflow. Sample mode remains separate when no project is selected. See `docs/design/reviews/backend-completion-plan.md` (repository root) for current proof and remaining API gaps; it supersedes the older integration notes below.

## Live workload declaration (Intent stage)

The loaded project's **Intent** stage owns the draft inputs. It has four tabs and one save/compile bar:

| tab | what it is for | writes |
|---|---|---|
| Workload | Declare the model identity and parallelism, choose a catalog workload template, then move between traffic collectives and compute stages. The no-compute empty state offers “Add the first stage” instead of pointing at raw JSON. | `PUT /projects/{id}/draft` with the whole canonical request; compute stages require schema v4, so a v3 draft is validated and migrated through `POST /topology-preview` first |
| Fabric | Edit topology family, geometry, link width, buffers, agents, address ranges, and traffic-class dependencies. Validate the fabric before saving. | Same draft save after `POST /topology-preview` returns the canonical request |
| Requirements | Edit acceptance criteria (traffic class, QoS, binding, latency ceiling, bandwidth floor, applicability) and read the loaded run's verdicts beside them. | Same draft save; verdicts are read-only and stay bound to the run's revision |
| Validate | Read declaration checks (workload, compute, traffic↔requirements coverage, agent seats, address map, lowering) and the declared physical/NoC inputs. Details hold the endpoint-seat and traffic-class tables. | None; read-only |

Switching tabs with unsaved edits asks before discarding them. The active tab is remembered per project. The Intent bar shows whether the draft matches the revision, whether the current tab has unsaved changes, and whether the current tab is valid enough to save. **Compile draft** is available from the same bar, so workload, fabric, requirements, and compile no longer require a page hop.

Legacy routes `#/workloads/library`, `#/workloads/editor`, `#/workloads/requirements`, and `#/workloads/lowering` still resolve for deep links and fixture mode, but they are hidden from the loaded-project sidebar. Use the Intent tabs instead.

Observed against the real store:

- `p-72d52e15419d` (Qwen3-30B-A3B): TP2·DP1·EP4·PP1 = 8 units but **16 compute tiles** are declared — surfaced as an unexplained mismatch, not smoothed over. 96 stages across 8 owner indices, so half the tiles are assigned no work. `ep_dispatch`/`ep_combine` traffic has no requirement, so no verdict is expected for it.
- `p-d037b1c85839` (MWA correlator): 8 tiles / 8 seats, 8 stages with 500 ms durations, and a 7.68 MB `tile_ingest` all-to-all.
- Some drafts declare **no** `compute` block at all. Their Workload page states that network traffic is evaluable and execution timing is not, then accepts a structured stage instead of a JSON paste.

## Project CRUD, compile, and the backend loop

`#/shared/projects` now writes to the store as well as reading it:

| action | endpoint | notes |
|---|---|---|
| New project (workload template) | `POST /projects` | the UI requires a registry workload; name required |
| New project (fabric-first preset) | `POST /projects/from-preset` | advanced/API path; starts without a workload |
| New project (blank) | `POST /projects` | optional catalog workload |
| Rename | `PATCH /projects/{id}` | |
| Set workload | `POST /projects/{id}/workload` | preset drafts ship with an empty workload, so the evaluation plan stays empty until one is chosen |
| Compile draft | `POST /projects/{id}/compile` | returns the new revision + certificate; the panel reloads, so the revision and topology appear immediately |
| Delete | `DELETE /projects/{id}` | requires typing the exact project id; removes revisions and runs |

An earlier browser verification used the fabric-first API path: create from preset `mesh4` → set workload `llama-dense-8b-64tiles` → compile (`r02`, certificate PASS) → launch `NETWORK_COMPLETION` → run published and selected → delete → store back to the original count. Temporary projects used for that check were removed afterwards.

The guided flow now starts from the other direction: `POST /projects` with a registry workload template creates the draft from that template's canonical request. A fabric-first preset draft has **no workload**, which is why a freshly created preset project shows "Nothing on this revision is ready to run" until a workload is set and the draft is recompiled — the evaluation plan is derived per revision, not per project.

## Projects & revisions: one workflow, four steps

The loaded-project page is a single vertical flow. Writes stay inside the Intent stage or the project header; the later steps read the compiled result:

| step | shows | action |
|---|---|---|
| 1 Project | project id, declared workload, `TP/DP/EP/PP` | **Rename** |
| 2 Intent | workload, fabric, requirements, validation, `compiled` / `uncompiled` | Four tabs and one **Save draft** / **Compile draft** bar; **Edit draft** jumps to Fabric |
| 3 Revision | active revision, router/channel/endpoint counts | **Show layout** for the topology graph; compile from the Intent bar |
| 4 Evaluation | every revision (including `UNSUPPORTED` compile attempts), its runs, latest status and requirement verdict | **Open latest run** or **Open analysis** on any run |

The evaluation step is a revision-first history: runs are nested under the revision they evaluated, and a revision with no run stays visible instead of disappearing from the sequence. Run labels are `rNN · run N` — for example, the first run of `r12` is `r12 · run 1`. A revision is the design version; a run is one evaluation attempt, not a version. The project header keeps the active revision and the run being viewed visible, and the run picker groups options by revision. Selecting a historical run shows a banner in Analysis with a **Return to active run** action.

Project deletion sits alone at the bottom of the flow, behind a typed-id confirmation. The project list and **New project** come after the flow, so the page reads: work on this project → then pick another.

## Draft editing (validate → save → compile)

The loaded-project panel carries a **Draft editor**. It edits `topology` scalars (`side_length`, `concentration`, `grid_side_length`, …), `physical` (clock, data width), `noc` link width, and per-kind agent counts/widths, then:

1. **Validate topology** → `POST /projects/{id}/topology-preview`. The gateway canonicalizes the whole request and rejects impossible edits; refusals are shown verbatim. **Save stays disabled until a validation succeeds**, because the canonical request is what makes a v2 draft storable.
2. **Save draft** → `PUT /projects/{id}/draft` with the canonical request the preview returned, not the client's guess. Only fabric/NOC fields the user actually edited are overlaid, so a v2→v4 migration cannot silently drop or invent settings.
3. **Compile draft** → `POST /projects/{id}/compile`, which turns the saved draft into a revision.

Schema note: preset projects are **v2** drafts with no `topology` object (fabric implied by `noc_config.topology_family`). Validating a topology migrates them to **v4** with an explicit `topology` block — that is the gateway's own migration path, and the editor says so instead of pretending a v2 draft has explicit geometry.

Verified end to end: preset `mesh4_hbm` (3×3) → editor sets `side_length` 5 → validate → save (`dirty: true`, schema v4) → compile → revision topology reports **25 routers / 80 channels / 5 endpoints**, rendered live in Design. Temporary projects were deleted afterwards; the store is back to its original 18.

The editor also switches **topology family** (mesh, concentrated_mesh, torus, flatfly, fattree, gec — each with only the fields that intent kind accepts) and adds/removes **agents** (kind, count, width). Verified: `mesh4_hbm` → family `torus` + one added agent → validate → save → compile → revision reports `family: torus`, 9 routers, **36** directed channels (wraparound) and **6** endpoints.

Edits made after a preview are preserved: the saved document is the preview's canonical structure with the current form overlaid, so a v2→v4 migration cannot silently drop later changes.

The draft editor is intentionally narrow: it owns the fabric/NOC/physical fields, agents, address ranges, traffic-class dependencies, and explicit topology documents. Workload identity, traffic collectives, compute stages, and acceptance criteria have dedicated editors under Workloads & Requirements; the old “Advanced compute stages” JSON box is gone. Edits invalidate validation; only the gateway's canonical document is saved. A server revision-token precheck detects intervening changes, but atomic compare-and-swap requires backend support.

Adding a compute stage to a v3 draft is a deliberate two-step write inside the Workload page: the page asks `POST /topology-preview` for a canonical v4 request (fabric unchanged, workload/requirements preserved), overlays the declared stages, then saves that whole request with `PUT /draft`. The save bar says so before it happens, and the existing revision is not touched until a compile.

## Running an evaluation (the one write path)

`Analysis → Summary` carries a **Run a new evaluation on this revision** panel. Launching is an explicit store mutation; draft editing, project management, bounded studies, and reviewed AI proposals have separate mutation controls.

1. It first reads `GET /revisions/{id}/evaluation-plan` — the gateway's own adjudication of which questions this revision can answer, per backend, with `READY`/`BLOCKED` and the qualification basis. Blocked questions cannot be selected; the page shows the gateway's stated reason instead of overriding it.
2. The launch button stays disabled until the operator ticks "I understand this runs real backend binaries on this host and appends a new run".
3. `POST /revisions/{id}/evaluate` returns a job; the panel polls `GET /jobs/{job_id}` every 2 s and renders the gateway's states only — `QUEUED → PREPARING → RUNNING → FINALIZING → COMPLETED`, or `REFUSED`/`FAILED`/`CANCELLED` with `error_code` and `error_message` verbatim. No percentage or ETA is invented.
4. On `COMPLETED` the project is re-read and the newly published run becomes the selected run, so every analysis surface immediately shows genuine output. The job receipt survives the reload because it lives in the project context, not in the page.
5. `POST /jobs/{id}/cancel` is offered only when the gateway reports `cancellable`.

Status bar and the Jobs drawer report a live gateway job (`1 running`) instead of the old static `0 live`.

Verified end to end against the real store on 2026‑10‑24 (three runs written to `runs/studio-store/projects/projects/p-b2ed4e030a8a/runs/`):

| launch | job | result |
|---|---|---|
| NETWORK_COMPLETION (BookSim) | `job-a07f185b6ebd` | `01a16c33…`, 4,710 cycles, QUALIFIED |
| 5 READY questions (BookSim + Astra ×3 + Ramulator) | `job-7c375c49ff5b` | `01a16c39…`, completed in ~5 min |
| NETWORK_COMPLETION (BookSim, from the UI) | `job-138855a0215d` | `01a16c43…`, auto-selected as the new run |

Refusals are real too: the project's job history shows seven `REFUSED` evaluations on revision `r07` with the gateway's own semantic-refusal messages.

## Working local flow

1. Inspect System Diagram and select an endpoint.
2. Add an architecture-description instance from IP Catalog. Duplicate identifiers and occupied ports are blocked. The local draft changes, not a backend or hardware design.
3. Filter endpoints, inspect attachments, and review supported attachment edits. Shared concentrator membership cannot be silently split.
4. Inspect independent mapping, permission, logical reachability, and canonical-route layers. Route edges are actual adjacent links in the declared mesh.
5. Review and apply the sample PCIe address relocation. Address unions and conflicts update from the same data.
6. Review declared clock assignments and placement-intent edits. No CDC or physical-signoff claim follows from editing intent.
7. Edit and save/approve a bounded local exploration brief. Review amendments separately. No evaluations launch; enforcement remains unavailable without a runner.
8. Inspect consistent candidate fixtures, a numerically scaled objective frontier, and a comparison table. Missing metrics remain unavailable, not zero.
9. Review a branch or supported two-field queue patch. Branching preserves the complete prior draft. Conflicting queue patches and stale review revisions are blocked. Structural topology replacement is not offered as a generic partial merge.
10. Run actual in-browser interval/reference checks. Results capture the input edit and explicitly exclude hardware verification.
11. Prepare, inspect, and download a real JSON architecture description. File size is measured from actual UTF-8 content. RTL/bitstream/protected-output options stay unavailable.
12. Export/import local-project snapshots or activate a preserved draft copy. Jobs/Problems/Logs show actual local actions and declared findings, not fabricated running processes.

Workloads & Requirements additionally supports manual operation creation/editing/deletion, explicit dependency intent, reviewed binding changes, assumption editing, reviewed requirement revisions, local input-set preservation/import/export, and structural/reference validation. The lowering view exports generic intent correspondence, not executable BookSim flags. Declared data amounts calculate minimum 128-bit data flits without inventing header or adapter overhead.

Analysis provides separate requested/injected/delivered pair fixtures, scalar metrics without fabricated histograms, canonical-route-derived link counts, explicit missing evidence, an independent illustrative event viewer, and comparison warnings for mismatched workloads. Its 329,464 delivered flits reconcile with rounded 16.4 GB/s aggregate throughput in a 450,000-cycle/1.4 GHz window. Derived link values are labelled proxies, not recorded hardware observations. The real reviewable evaluation-intent JSON download has `executable: false` and cannot queue a backend job.

Working requirement and assumption edits never change the historical r5/w12 fixture. Existing saved v1 drafts migrate additively to include the new working-input editors without discarding architectural edits.

Selection and draft state survive route changes and normal reloads when browser storage is available. Use **Ctrl/Cmd+K** to find any imported view. Inspectors become on-demand panels at constrained widths; wide tables use visible scrolling.

## Corrected engineering semantics

- One consistent 4×4 mesh, eight sample endpoints, explicit concentrator membership, 128-bit links, and 1.4 GHz declared network clock.
- Raw one-flit/cycle link capacity: **22.4 GB/s per direction**. Whole-network throughput is labelled separately.
- `SIM-402` remains the same baseline fixture everywhere.
- `REQ-LAT-04` remains **P95 complete transaction latency ≤25 ns**. Authored packet-P99 observations do **not** assess it; it is Not evaluated.
- Queue storage is calculated from configured router/port/VC/depth values, not presented as fabricated foundry cell area.
- Pareto coordinates, axes, points, and frontier share the same scale transformation. Incomplete, invalid, and failed observations are not assigned invented coordinates. The frontier is scoped to complete comparable observations meeting the declared delivery/storage gates, not a global optimum or full-compliance recommendation.
- The sample address union is calculated with overlap counted once. A 4.8 mm square has **23.04 mm²** declared area, not 4.8 mm².
- Unsupported foundry qualifications, tool versions, licences, certifications, MTBF results, physical slack, and generated RTL are not carried over from the mockups.
- Historical input snapshots and sample observations are not silently retargeted to edited drafts.

## Deliberate limits

This is a local, fixture-backed design prototype, **not a production EDA system**. There is no simulation, solver, formal proof, synthesis, CDC analysis, hardware generation, physical qualification, tool discovery, execution-budget enforcement, agent connection, or filesystem-project service.

The selected generated-HTML layouts were rebuilt into components rather than treated as literal specifications. Unsupported production operations remain unavailable. Deliver can export a descriptive JSON file, not the invented RTL, bitstream, foundry package, or commercial IP shown in some exports. A browser download request does not prove the host filesystem save completed.

Browser storage is not encrypted or transactional and can be evicted. Use one editing tab and export important local work. Recovery is limited to preserved drafts and local-project JSON. A corrupt stored value is not overwritten until the user explicitly accepts a fresh preview. Import is capped at 2 MiB and validates the local schema. This does not certify an air gap or implement a confidential-data policy.

The prototype intentionally has its own fixture state rather than importing dirty Studio components/stores or querying live research APIs. This makes manual design review safe and keeps backend truth separate. Domain integration should be an explicit later task, not a side effect of combining HTML exports.

## Adding another batch

1. Keep the original export under `docs/design/stitch_veritx_studio_eda_frontend`.
2. Review its claims and reuse the shared state/definitions rather than copying contradictory sample data or scripts.
3. Add a route/source descriptor to `PAGES` and implement its content in the appropriate view module.
4. Reuse `ui.tsx` and `styles.css`; do not copy another header, navigation rail, CDN loader, or global reset.
5. Enable a previously absent workspace only after it has a real view.
6. Update coverage assertions and run build, unit tests, and the route/flow browser checks.

Do not automatically execute newly supplied HTML scripts or blindly import fabricated proof/generation outputs as evidence.

## Verification

Latest checks: production build passed; the unit suite passed; the all-routes, live-run and workload-analysis browser checks passed. The full browser suite still reports four failures in the current working tree that are unrelated to this page: a supplied export with no route, two surfaces whose test headings no longer match the renamed views, and a command-palette check that expects a hidden Deliver route.

Agent surfaces convert the exported runtime/approval screens into honest local intent. The connection form validates URL scheme, forbids embedded credentials/query secrets, restricts local-only policy to loopback hosts, accepts only an environment-reference *name* for credentials, and can be saved without any network request. Approval revocation clears only the local scope preview, preserving drafts, fixtures, and prepared artifacts. Model explanations, hypotheses, handshakes, and audit trails are explicitly unavailable rather than simulated.

Verification is parent-performed source and browser testing, not an independent delegated review. Unit checks cover numerical invariants, fixture identity, frontier membership, address arithmetic, bindings, brief bounds, revision conflicts, branch preservation, state validation, and descriptive exports. Browser checks exercise all routes at 1440×900 and 1280×800, block unexpected external requests, and exercise manual creation, edits, approvals, branch/recovery, keyboard navigation, checks, and actual JSON download.
