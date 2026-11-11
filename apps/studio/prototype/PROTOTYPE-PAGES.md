# Prototype page guide

This guide covers every route registered in `src/model.ts` (55 routes). It describes the current prototype, including differences between the local illustrative preview and a loaded gateway project. Routes marked as aliases remain valid deep links even when navigation hides them or redirects them to a shared live surface.

## How to read the prototype

- **Local preview** means a page is showing the prototype's authored fixture or browser-persisted draft. It is not automatically a simulator result, hardware fact, or gateway mutation.
- **Live project** means a gateway project is loaded. Pages that support it read project, revision, run, or capability records from the gateway; only controls specifically described as writes mutate the gateway draft or launch work.
- Saving a draft, compiling a revision, evaluating that revision, and producing implementation artifacts are separate steps. One does not imply the next.
- A missing measurement is unavailable, not zero. A gateway/backend capability or a successful model simulation is not hardware qualification.
- The URLs below use the hash route, for example `#/flow/start`.

## Flow

The guided Flow workspace is a gateway-project workflow with five visible steps: `start`, `tune`, `search`, `optimize`, and `run`. Except for its start page, the steps require a loaded project. Its cards link to the full workspace that owns each editing or evidence surface. The hidden `flow/compare` compatibility alias remains registered, preserving all 55 route IDs.

### `flow/start` — Start from a workload template

Lists workload templates with their declared identity, traffic, requirements, compute stages, and backend readiness; existing projects are also available. Search or filter templates, inspect their full definitions, optionally name a project, then create a gateway project from a selected template or open an existing project. A separate reference-workload table reads the bundled measured trace set and marks which reference workloads have a matching project template; trace-only entries are study inputs, not project templates. Reads the gateway template catalog, project list, and bundled ablation document. A readiness label is a gateway assessment, not a measured result. This page does not select a fabric, compile, evaluate, or generate hardware.

### `flow/tune` — Workload intent

Embeds the workload and acceptance-criteria editors. Edit workload identity, parallelism, collectives, initiator profiles, compute stages, or criteria; switching tabs can prompt before discarding unsaved edits. A collective whose chosen dimension has fewer than two ranks (for example a TP collective while TP=1) is refused in the editor before save. Save writes workload intent to the gateway draft; compilation is a separate workflow step. Workload timing is declared input, not inferred from a model name or a calculated critical path. Some nested schema-v5 intent is read-only in these editors.

### `flow/search` — Evaluate & choose fabric

The canonical page for launching, evaluating, inspecting, and selecting a fabric. Select fabric candidates, review the frozen workload, explicitly approve traffic generation/evaluation, and launch or cancel the catalog job. Before results, setup states that no fabric is ranked; setup collapses when result rows arrive.

Results use a compact workbench. Four objective profile controls (Network, System, Balanced and Best evidenced) show a winner or its stated absence and open details, rather than presenting tall profile cards. The comparison starts as a full-width All fabrics table and switches to the Trade-off plot. Inspecting a fabric opens the adjacent inspector on Measurements, showing recorded aggregate and per-traffic-class metrics immediately, without opening disclosures, with BookSim network and ASTRA-SIM system scopes kept separate. Configuration and provenance are in the secondary Configuration tab; generated input downloads are in Files. Closing details collapses the comparison back to full width. Reviewing a table row, profile winner or plot point only inspects it; the inspected highlight is distinct from the Chosen badge. At content widths of 960px or less, details overlay the comparison; Close details dismisses the inspector and returns focus to the invoking control.

Choose a measured result only when it is eligible. Incomplete backend coverage requires explicit acknowledgement. Choosing a result writes the selection against the expected draft token, then navigates to `flow/optimize` for parameter refinement. Results and artifacts are gateway-backed; stale or incomplete measurements cannot become a valid recommendation. Network and system metrics are separate scopes, not a combined score; missing compute stages can make a system result incomplete. Results do not establish requirement compliance or hardware qualification.

### `flow/compare` — Evaluate & choose fabric (hidden compatibility alias)

Remains registered for existing deep links but is hidden from navigation and resolves to `flow/search`. It opens the same launch/evaluation/inspection/selection surface, not a separate results-only page or visible Flow step.

### `flow/optimize` — Refine fabric parameters

Shows the selected fabric's catalog-time network completion, system makespan, requirements and VC count before the editor. Manual parameters are grouped into Topology & sizing, Physical assumptions, Router & pipeline and, for Srota, typed fabric intent; the working group is selected in a section tablist. A pinned save bar reports compile state and keeps Save & compile and Final validation reachable. Manual changes are validated, saved to the draft, and compiled; AI proposals are scoped to the submitted design and require review and explicit adoption. This page reads the selected catalog plan/evaluation and gateway capability/job data. A successful compile is not a performance measurement; evaluate again to measure a changed revision. A catalog baseline is not the edited draft. AI suggestions are not evidence.

### `flow/run` — Finalize topology & RTL

Offers evaluation launch and run analysis, alongside RTL-generation readiness/preview. Select a run, review execution questions, explicitly confirm backend execution, and inspect run detail, traffic matrix, integrity, and artifacts. RTL preview has a separate confirmation and download path when supported. The selected fabric must be present and compiled before evaluation. Run completion does not establish qualification. The available emitter is a constrained topology-only preview, not final simulation-equivalent implementation RTL.

## Design

Without a gateway project, Design pages edit or inspect the local illustrative draft. With a project loaded, they generally render revision-backed declared topology and intent; only the fabric, catalog, and placement pages provide notable live writes. A live diagram is not a physical implementation view.

### `design/fabric-topology` — Fabric Topology

Shows the fabric graph, routers, channels, endpoint attachments, and (where available) declared overlays. The fixture uses a fixed 4×4 mesh and derived utilization proxy; the live view uses the project's declared topology and can expose router/wire selection, zoom, layers, and findings. In the fixture, router/overlay selection and queue-depth edits affect local draft state. Live users can edit explicit graph links or buffer depth when the schema supports it; writes go through draft save/compile. Fixture utilization is not measured traffic; live channel properties describe declared structure, not observed counters. Neither view establishes deadlock freedom, physical signoff, or hardware qualification.

### `design/system` — System / Block Diagram

Shows a system block diagram: the fixture displays sample endpoint blocks and mesh summary; the live view combines request agents/workload/NoC controls with topology counts and any derived certificate. Fixture users can zoom, fit, select endpoints, and navigate to the catalog. Live view is informational. It is a declared-composition diagram, not a floorplan, packet path, or evaluation of latency, throughput, power, or area.

### `design/catalog` — IP Catalog

The fixture lists a small set of architecture/interface descriptions; search or select an item and add an endpoint instance to the local draft. The live page shows request agent groups and topology-derived endpoint seats and can add an agent group to the gateway draft. Live additions require compilation before seats are materialized. Fixture entries are descriptions, not implementation IP; live agent intent does not itself supply RTL, an adapter, or a qualified endpoint.

### `design/endpoints` — Hardware Endpoints

Lists endpoint role, interface, domain, router, and source. Fixture users can filter/select endpoints and review an attachment change; attachment checks enforce the prototype's router/concentrator constraints. The live view compares declared agent groups with compiled endpoint seats and links to related views. Neither view proves protocol compatibility, CDC implementation, permissions, or hardware implementation.

### `design/mapping` — Initiator–Target Mapping

The fixture exposes separate intent, permission, logical reachability, and configured-route layers for source/target pairs. Pair intent/permission edits update the local draft; displayed routes use a deterministic mesh route. The live view shows a router incidence/adjacency matrix and explicitly treats initiator-target mapping as absent. Router adjacency does not prove access permission, endpoint mapping, route validity, or guaranteed reachability.

### `design/addresses` — Address Map

Shows declared memory regions and address bounds. The fixture calculates overlaps and mapped union and allows a proposed BAR relocation after validating the 48-bit address and overlap constraints. The live view lists the gateway draft's address ranges but does not run the fixture's interval validation. Neither view checks runtime decode, permissions, alignment requirements, or whether every external window is backed by materialized hardware.

### `design/domains` — Clock & Power Domains

Shows sample clock declarations and endpoint crossings in fixture mode; live mode displays physical parameters and agent clock-domain declarations. Fixture users can select an endpoint and review a local domain assignment. Live view is read-only. These declarations do not constitute CDC/reset analysis, timing closure, power intent, or process-specific power/area evidence; absent values remain unknown.

### `design/placement` — Placement Constraints

Fixture mode shows an illustrative die frame and router-anchor intent; users can switch display mode and review local anchor changes. Live mode shows topology coordinates and a gateway floorplan declaration; users can declare/update or remove that floorplan. The gateway stores authored geometry bound to a topology. It is not calibrated placement, extracted parasitics, PPA, congestion, DRC, LVS, or signoff evidence.

## Workloads & Requirements

This workspace has local editors and gateway-backed editors/validation. Three legacy routes are hidden from navigation but remain addressable. In live mode the library/editor routes share one workload editor; bindings, assumptions, and lowering resolve to the common validation/readiness page rather than separate live editors.

### `workloads/workflow` — Project & Revision Workflow

Guides the project through intent, compiled revision, evaluation, exploration, verification, and delivery. It shows project/revision/run history, draft state, and a next action; users can rename/delete a project, open editors, save/compile, inspect topology, open a run, or navigate to catalog/study/evidence/delivery. Gateway operations mutate the project or compile a revision. Draft changes are not published until saved and compiled. Missing evidence is not inferred; workflow completion does not establish hardware qualification or RTL generation.

### `workloads/library` — Workload

Local preview lists a captured reference and editable working workload; users can create a local workload, import/export workload-intent JSON, review/restore archived input sets, and open the editor. Changes stay in browser-backed prototype state. In live mode, this route is the same gateway-backed workload editor as `workloads/editor`; there is no separate live library.

### `workloads/editor` — Workload (legacy editor route)

Hidden from regular navigation and aliased to `workloads/library` for fixture navigation state. The local view edits structured transfer/compute-delay primitives in table or dependency-intent form and can export/preview lowering. In live mode it opens the shared workload editor on its Compute tab. Edits are intent until saved; they do not launch an evaluation. Declared dependencies are not execution ordering, compute-delay primitives are not a compute datapath, and transfer previews omit runtime scheduling/adapter effects.

### `workloads/requirements` — Requirements

Shows acceptance criteria and their current/working values. The fixture lets users propose and explicitly apply requirement changes while retaining historical outcomes. Live mode edits draft requirements by class/QoS/binding and threshold, saves via the gateway, and reads verdicts from a selected run. New verdicts require a subsequent compile/evaluation. Transaction-completion P95 and packet P99 are different measures; a missing matching measurement is not a pass.

### `workloads/bindings` — Validate (legacy binding route)

Hidden from regular navigation and aliased to `workloads/lowering` in fixture navigation. The fixture maps workload participants to hardware endpoints, allowing a user to review rebind/unbound choices and affected primitives. In live mode this URL renders the common validation page, which reports agent counts versus endpoint seats and says no binding table is connected. Explicitly unresolved endpoints remain unresolved; names are not auto-bound. Bindings do not cover address permissions or adapters.

### `workloads/assumptions` — Validate (legacy assumptions route)

Hidden from regular navigation and aliased to `workloads/lowering` in fixture navigation. The fixture reviews default compute delay and memory-service assumptions and applies them to local inputs; empty memory duration stays unspecified. Live mode renders the common validation page, not an assumptions editor. Fixture values are declared approximations, not calibrated hardware measurements.

### `workloads/lowering` — Validate

Fixture mode shows workload findings, source-to-preview correspondence, and an illustrative JSON payload; it permits export but not dispatch. Live mode shows read-only readiness/consistency checks such as workload presence, compute intent, traffic/requirement coverage, parallelism versus tiles, agent counts versus seats, and address-map presence. The live page reports that no lowering adapter is connected. It does not compile, simulate, or qualify a design.

## Analysis

Without a loaded gateway project, routes display authored fixture observations. With a loaded project, run-scoped pages use the selected gateway run; missing run data opens a selection/empty state. Several fixture-era URLs become tabs or aliases in the consolidated live analysis workspace.

### `analysis/summary` — Analysis Summary

Summarizes requirement assessment, run status, reported metrics, and evidence gaps; fixture mode allows switching among sample runs and opening evaluation-intent setup. Live mode reports selected-run data and gateway verdicts. Setup/export does not itself launch an evaluation. Packet P99 or averages are not transaction P95, and unavailable metrics are not zero or passes.

### `analysis/matrix` — Traffic Matrix

Displays traffic between source/destination endpoints. Fixture mode uses an authored pair-count matrix with selectable count/byte/rate views, cell inspection, and JSON export. Live mode reads the selected run's traffic-matrix artifact and supports packet/flit basis, class filtering, pair search, heatmap/pair selection, and traffic-pattern summaries. Absent artifacts mean unavailable counts, not zero; fixture conversions and windows are stated assumptions, not simulator output.

### `analysis/missing` — Traffic Matrix — Missing Artifact (legacy scenario)

In fixture mode, deliberately presents a missing-capture scenario using the matrix surface; it does not modify the selected sample run. In live mode, this is an alias for the regular matrix tab and does not force a missing artifact. The route is hidden from live navigation but direct links continue to resolve.

### `analysis/topology` — Topology & Simulation Overlay

Fixture mode renders a logical mesh, selectable directed links, and a derived link table based on authored endpoint-pair counts routed over declared paths. Live mode shows declared topology, run-linked simulation/playback, and sampled channel/router/load analyses when those artifacts exist; users can search channels and filter load ranges. Some route projections are unavailable for hybrid fabrics. Fixture link values are not measured link counters; live sampled series are optional and cannot be reconstructed if they were not recorded.

### `analysis/metrics` — Analysis Metrics (legacy route)

Fixture mode offers summary statistics, derived link-utilization data, and an explanation of latency-distribution availability. A scalar percentile cannot be used to invent a histogram or another percentile. In live mode this route canonicalizes to `analysis/summary`; it is not a separate page.

### `analysis/trace` — Trace Viewer

Fixture mode explains that selected sample runs have no packet trace and can open an independent demo trace for event filtering/inspection. Live mode reads observed playback and raw trace artifacts for the selected run, and can calculate packet percentiles only when a verified packet artifact is available. The fixture demo is unrelated to the selected run; live playback does not infer unlogged events or hardware telemetry.

### `analysis/curves` — Curves & Pareto

Uses repository workload/topology reference data to plot measured curves, Pareto views, and power/area/energy breakdowns; users can choose a workload, axes/preset, and topology and inspect/export results. For a loaded project it matches the reference workload when possible; project-owned revision studies are under Explore. Latency/hops/throughput are reference measurements, while power/area/energy come from a native BookSim model—not compute or DRAM measurements.

### `analysis/comparison` — Run Comparison

Fixture mode compares `SIM-402` against selected sample runs, showing packet-percentile and throughput deltas only when the runs are aligned. Live mode selects another project run, fetches its detail and gateway comparison, then displays server-provided rows/verdicts/deltas and configuration context. The fixture comparison is illustrative and not statistically significant; in live mode the comparison endpoint is the authority, not client-side qualification arithmetic.

## Explore

Explore contains repository reference studies plus project-specific fabric/study surfaces. Loading a project changes several fixture-era study routes to the same live revision-study workspace; reference catalog and ablation pages remain distinct.

### `explore/fabric` — Fabric for This Workload

With a live project, shows workload, traffic, agent/endpoint, requirement, and topology context. Mesh, concentrated mesh, and torus can be sized and applied; other families open the fabric editor for explicit configuration. Applying changes topology intent through gateway preview/draft APIs; it does not transfer the reference result as project evidence. A dirty draft blocks one-click application. Without a project, the page prompts the user to open a project or browse the reference catalog.

### `explore/fabric-search` — Reference Catalog

Loads a repository workload/fabric catalog and search controls for buffer values, audited knobs, budget, seed, and metric limits. Users run a fabric search, inspect measured results/recommendations, and may apply supported topology intent to a project draft. Failed/incomplete searches do not produce a winner. Catalog runs are reference measurements, not measurements of the loaded project; applying a topology does not apply its measured performance.

### `explore/ablations` — Workload Ablations

Compares measured workload × topology trace arms in a workbench. Select workload/fabrics, inspect measured cells, and use the supported tuning/analysis controls. Data comes from repository ablation documents and gateway runners. Missing or failed cells remain absent rather than being estimated. This is separate from a project's revision study.

### `explore/fabric-ablations` — Fabric Ablations

Shows a repository-wide fabric sweep over uniform injection rates. Reads a gateway topology sweep with a bundled JSON fallback and offers refresh. It is reference sweep evidence, not a loaded project's run or revision result.

### `explore/brief` — Revision Study (Advanced)

Without a loaded project, configures a local illustrative study brief: VC/depth/arbitration dimensions and run/time/concurrency/storage bounds. Save/approve records local scope and validates it; approval launches no jobs and grants no backend authority. With a project loaded, this route displays the live revision recommendation/study UI instead of the local brief.

### `explore/progress` — Study Execution & Budgets (legacy live alias)

Fixture mode shows a local execution ledger, approved-scope state, and candidate links; scope amendment updates preview state only, and launch is disabled. With a loaded project, this URL opens the shared live revision-study workspace and is hidden from navigation. The fixture does not report actual resource consumption or enforce backend budgets.

### `explore/results` — Candidate Results & Trade-offs (legacy live alias)

Fixture mode plots sample packet P99 against configured queue storage, filters/selects candidate rows, and shows a candidate inspector. Only complete comparable records meeting the local gates enter the frontier. Transaction P95 is not measured, and the plot is not a global optimum or compliance verdict. With a project loaded, this route opens the shared live revision-study workspace and is hidden from navigation.

### `explore/comparison` — Candidate Comparison (legacy live alias)

Fixture mode pins up to three sample candidates and compares queue settings, storage, run identity, and available packet metrics. It discloses unavailable transaction P95 and hardware qualification; cross-family comparison needs an explicit brief/comparability review. With a project loaded, this route opens the shared live revision-study workspace and is hidden from navigation.

### `explore/adoption` — Candidate Adoption / Branch (legacy live alias)

Fixture mode offers a confirmed isolated local branch or a supported local queue-parameter patch from a complete candidate. A branch preserves the prior draft; a patch changes only supported VC/depth fields and refuses conflicting queue edits. Neither creates a backend run or new evidence. With a project loaded, this route opens the shared live revision-study workspace and is hidden from navigation.

## Verify

Fixture Verify pages describe local checks and authored sample claims. Live pages read gateway-run evidence and backend reports; they do not broaden those records into claims the backend did not make.

### `verify/overview` — Evidence Overview

Fixture mode summarizes sample-candidate requirements/evidence domains and links to checks, evidence, obligations, and delivery. With a loaded project it aliases to `verify/evidence`, so the live page shows run/bundle evidence detail instead of a separate overview. Fixture metrics are authored illustrative data.

### `verify/support` — Configuration Support Checks

Fixture mode shows capability checks for a selected target context plus local arithmetic/check exports. Live mode shows registered backend support, capability gaps, and an export of capability registry data. Live data comes from the gateway capability endpoints. Backend support describes what the gateway can attempt; it does not qualify the current project, and fixture target selection does not inspect installed tools/licenses.

### `verify/checks` — Check Setup & Results

Fixture mode runs local declaration checks, records findings against a draft revision, and links each finding to its affected design page; changed drafts make prior findings stale. Live mode displays gateway-reported integrity/conservation, route-realization scope, and analysis status. Local checks are not solver/RTL/CDC/physical checks. Live conservation is backend-reported; unavailable is not zero, no deadlock proof is supplied, and functional correctness is not evaluated.

### `verify/obligations` — Outstanding Obligations

Fixture mode lists open engineering questions and allows selecting/acknowledging them; acknowledgement does not close an obligation. Live mode reads the project's obligation register and shows project/revision/run context, blocking/count summaries, evidence, next actions, and download. The live register is derived from draft, latest run, and product limits. A resolved item only meets its stated scope; it does not imply RTL or physical qualification.

### `verify/evidence` — Evidence Detail / Claim Scope

Fixture mode explains the captured sample design/workload/candidate, reported packet P99 and throughput, unavailable transaction P95, revision distinction, and integrity/signature status; it offers read-only sample JSON and limitations. Live mode shows run/revision/evidence/bundle identity, files, scope, evidence documents, raw artifacts, and bundle listing. It reads gateway records; raw artifact display verifies digests. The page does not recompute evidence or promote network simulation into hardware qualification.

## Deliver

The fixture delivery flow prepares a descriptive local architecture JSON. In a loaded gateway project, most old Deliver URLs intentionally canonicalize to one active-revision manifest page; there is no distinct live generation job or artifact-body browser.

### `deliver/readiness` — Output Readiness

Fixture mode lists available descriptive architecture JSON and marks RTL/SystemVerilog/ASIC/FPGA/protected RTL as unestablished, with links to configuration/support. In live mode it aliases to `deliver/package` and shows the revision artifact manifest. Local export readiness is not implementation eligibility or qualification.

### `deliver/configuration` — Output Configuration

Fixture mode lets the user select an output profile/name and prepare a local export for review; only architecture JSON is enabled. Preparing serializes the current draft and navigates to package review. In live mode this URL aliases to the package manifest, not a configuration form. No gateway job, RTL emitter, synthesis, or implementation tool is invoked in fixture mode.

### `deliver/job` — Generation Job

Fixture mode shows no backend generation job; after local export preparation it reports the serialization record, captured draft, file size, and local events. In live mode this URL aliases to `deliver/package`; it does not show a generator job. Local serialization is not background generation, execution, or hardware checking.

### `deliver/package` — Package Review & Manifest

Fixture mode reviews the prepared descriptive JSON file, captured draft, producer/classification, and download; without a prepared export it directs the user to configuration. Live mode reads the active revision artifact graph, inputs, named proofs/revalidation, scope coverage, freshness/origin, and generated reports; users can download manifest/evidence indexes or compare another revision. A certificate is a derivation graph, not a signature; named compiler proofs are not independent proof, and manifest comparison is not correctness evaluation. The manifest does not claim hardware/physical qualification.

### `deliver/artifacts` — Artifact Inspection & Export

Fixture mode previews/downloads the locally prepared JSON, or points to configuration if none exists. In live mode this URL aliases to `deliver/package`: it displays artifact references and proof metadata, not a distinct artifact-body browser. The API does not provide generated RTL or file-body downloads here; RTL and ASIC/FPGA implementation remain unavailable through this surface.

## Desktop

### `shared/projects` — Projects, Revisions & Recovery

Lists and loads gateway projects, creates projects, reloads project data, and permits deletion after explicit ID confirmation. Deletion removes the project and its associated revisions/runs and cannot be undone from this page. It also supports import/export and recovery of **local preview** project JSON, restoring a preserved local draft as a copy, and resetting local preview state after confirmation. Browser storage is best-effort; local recovery is separate from the gateway store. Desktop startup with no selected gateway project presents the project picker rather than treating the sample fixture as live.

### `shared/environment` — Environment & Local Settings

Reports the current environment boundary: browser-local persistence, gateway connection status, execution/agent runtime availability, and whether remote AI or local inference is connected. It is informational, not a settings editor. It does not inspect host tools, protect credentials, enforce runtime budgets, or establish certified air-gap isolation, encrypted storage, or firewall enforcement.

### `shared/jobs` — Jobs, Problems & Logs

Provides local Jobs, Problems, and Logs tabs: operation summaries, local declaration findings with links, and exportable prototype events. This is not a live gateway job monitor or backend log. Fixture entries are historical illustrations; the page has no simulation, formal-check, generation-worker, or cancellation controls.

## Optional agents

Agent pages have separate local-preview and gateway-project behavior. Local approval/connection intent is not server authorization. Live model requests require configured runtime/capabilities and explicit consent; suggestions are not evidence.

### `agents/assistant` — Contextual Assistant

Local preview lets a user select an authored observation and/or local draft context, inspect/download the context JSON, and navigate to manual equivalents; sending is disabled and no model response is produced. With a live project, the page offers a model-backed assistant when a runtime is configured. Context inclusion is reviewable; chat history is session-scoped, and a bounded recent message history is sent. Replies are suggestions, not evidence. The runtime is not an OS sandbox, though domain tools such as filesystem/terminal access are not exposed.

### `agents/runtime` — Runtime Connection & Permissions

Local preview edits a proposed endpoint, data policy, environment-variable name, and operation scope; it validates URL/scope shape and saves intent locally only. It sends no handshake, grants no permissions, and never stores the credential value. With a live project, the route uses the server-managed model endpoint/model/key configuration and bounded proposal flow; requests need explicit consent. The client does not grant file or terminal tools.

### `agents/approvals` — Approvals, Scope Changes & Activity

Shows local bounded-brief approval state, exportable activity, and a confirmed local revocation action. Those operations alter only preview state; they do not authorize a live agent or backend execution. In loaded-project mode, agent activity and proposal decisions are presented through the live agent surface. Approval of a proposal is a separate human-reviewed adoption step; connection status alone is not authority.

### `agents/workload-translation` — Requirements to Editable Workload

Local preview shows editable working-input assumptions, declared primitives, findings, and a lowering preview. It does not parse prompt text or invoke a model; export is explicitly illustrative/non-executable and adoption is disabled. With a live project, a configured assistant can submit requirements after explicit consent, schema-check a returned workload proposal, compare it with current workload/compute, and offer adoption only after review and while the base revision still matches. It leaves requirements and hardware unchanged.

## Route inventory and aliases

The canonical inventory is `PAGES` in `src/model.ts`. The following routes are registered but intentionally hidden from some navigation surfaces:

- `flow/compare` → `flow/search`, the canonical Evaluate & choose fabric page; not a separate results-only step.
- `workloads/editor` → fixture active-page alias of `workloads/library`; live route opens the shared editor on Compute.
- `workloads/bindings` and `workloads/assumptions` → fixture active-page aliases of `workloads/lowering`; live routes open common validation.
- `analysis/missing` → live matrix alias; `analysis/metrics` → live summary alias.
- `explore/progress`, `explore/results`, `explore/comparison`, and `explore/adoption` → one live revision-study surface.
- `verify/overview` → live evidence detail.
- `deliver/readiness`, `deliver/configuration`, `deliver/job`, and `deliver/artifacts` → live package manifest.

Bare workspace hashes resolve to landing pages, for example `#/analysis` to `analysis/summary`. These route mappings are implemented by `src/model.ts`, `src/App.tsx`, and the workspace view dispatchers; consult those files if a link's behavior changes.
