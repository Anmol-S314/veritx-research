# Srota Studio — stitched design prototype

A **separate React prototype** reconstructed from the HTML references in `docs/design/stitch_veritx_studio_eda_frontend`. It shares one shell, design system, route catalogue, illustrative dataset, and local editable state. The original exports and existing Studio application are not modified or embedded in iframes.

## Run

From the repository root, using the existing dependencies installed in `apps/studio/node_modules`:

```bash
npm --prefix apps/studio/prototype run dev
```

Open **http://127.0.0.1:5174/**. The prototype uses its own Vite root and browser-storage key, `srota-stitch-prototype:v1`. Port 5173 remains separate for the existing Studio.

One gateway seam exists: `/gw` is proxied to the repository gateway (`VERITX_GATEWAY`, default `http://127.0.0.1:8099`). Reads cover the project list, project detail, draft, revision topology, runs, evidence, integrity, artifacts and the evaluation plan. There is exactly one write: launching an evaluation (below). Everything not listed there still renders the authored fixture. Start the gateway with:

```bash
cd tracks/t3-topology/dse && python3 -m uvicorn veritx_dse.gateway.app:app --host 127.0.0.1 --port 8099
```

If it is not running, that panel shows the failure reason and the command, and the rest of the prototype is unaffected. If dependencies are missing, install the parent Studio's declared dependencies; this prototype does not require another dependency set.

```bash
npm --prefix apps/studio/prototype run build
npm --prefix apps/studio/prototype test
npm --prefix apps/studio/prototype run test:e2e
```

Browser tests use the locally installed `/usr/bin/google-chrome`. Change that explicit test executable path for a different host. Build output and browser-test artifacts are ignored within this directory. Only the two existing font files and their OFL notices are copied from the parent's `public` directory into this prototype's `public` directory. Other Studio assets and product manifests are not included. No Google Fonts, Tailwind CDN, icon CDN, or remote asset dependency is used.

## Scope

The **43 supplied exports plus one prompt-only surface** are represented by explicit routes (7 Design, 6 Workloads & Requirements, 8 Analysis, 5 Explore, 5 Verify, 5 Deliver, 3 shared desktop, 4 optional-agent):

### Design

- `#/design/system` — System / Block Diagram
- `#/design/catalog` — IP Catalog
- `#/design/endpoints` — Hardware Endpoints
- `#/design/mapping` — Initiator–Target Mapping
- `#/design/addresses` — Address Map
- `#/design/domains` — Clock & Power Domains
- `#/design/placement` — Placement Constraints

### Workloads & Requirements

- `#/workloads/library` — Workload Library
- `#/workloads/editor` — Structured Workload Editor
- `#/workloads/requirements` — Requirements Editor
- `#/workloads/bindings` — Endpoint Bindings
- `#/workloads/assumptions` — Assumptions & Model Inputs
- `#/workloads/lowering` — Validation / Lowering Preview

### Analysis

- `#/analysis/summary` — Analysis Summary
- `#/analysis/matrix` — Traffic Matrix
- `#/analysis/missing` — Explicit missing-artifact scenario
- `#/analysis/topology` — Logical Topology Overlay
- `#/analysis/metrics` — Supported Metrics
- `#/analysis/trace` — Trace availability and independent example viewer
- `#/analysis/comparison` — Run Comparison
- `#/analysis/logs-artifacts` — Logs & Artifacts (built from its prompt; no HTML export was supplied for this surface)

### Explore

- `#/explore/brief` — Versioned Exploration Brief
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

The route catalogue in `src/model.ts` records the source export directory for every view. All six workspaces plus the four optional-agent surfaces are represented — 44 routes: 43 exports plus one prompt-only surface, `analysis/logs-artifacts`, whose source is `docs/design/stitch-prompts/analysis-logs-artifacts.md` because no HTML export was ever supplied for it. `tests/prototype.spec.ts` asserts that every directory holding a `code.html` has exactly one route and that the only non-export source is that prompt. The Logs & Artifacts surface stays backend-shaped: it lists real local records and names the gateway endpoints (`/api/v1/runs/{run_id}/artifacts`, `/integrity`, `/evidence`, `/jobs/…`) that would fill the remaining panels, leaving them empty rather than inventing file lists, sizes, or sha256 digests. The Requirements-to-Editable-Workload export arrived after the first 42 and is held to the same rule: it shows the working inputs a translation would have to produce plus the review gate, while the export's agent claims (active job, DRC-clean, drafting AI, synthesized phase windows) are dropped because no parser, model, or backend exists. Optional AI is **not** connected: there is no transport, handshake, credential lookup, model call, or permission grant. New Evaluation is a reviewable Analysis drawer; an executable backend configuration is not fabricated. The missing-artifact route is explicitly an alternate fixture scenario, not a mutation of SIM-402’s recorded counts.

## Live project data (Design surfaces)

`#/shared/projects` lists the repository gateway's real projects. Loading one switches these Design surfaces from the authored fixture to live store data:

| surface | live source | explicit gaps shown |
|---|---|---|
| Fabric Topology | revision topology: routers, directed channels, endpoint attachments, hashes | utilization, queue occupancy, achieved timing |
| System / Block Diagram | request agents, workload, `noc_controls`, derived certificate | simulation results |
| Hardware Endpoints | declared agent counts + topology endpoint seats | address assignment, permission, protocol behaviour, CDC |
| Initiator–Target Mapping | router adjacency derived from channels | mapping intent, access permission, guaranteed reachability, observed traffic |
| Address Map | `request.address_map.ranges` | overlap/decode analysis; empty for every project in the current store |
| Clock & Power Domains | `request.physical` (clock MHz, data width, power-domain count, process node) | per-agent clock assignment, CDC, power intent, achieved timing |
| Placement Constraints | logical router coordinates | floorplan, die outline, physical constraints, area/congestion |

IP Catalog has no live equivalent and keeps the fixture with a banner naming the loaded project.

Geometry is not hardcoded: a 3×3 mesh (9 routers, 24 directed channels) and a 64-router `custom` family render from the same channel list. Families that supply no router coordinates get a derived layout that is labelled as derived in the caption, and endpoint-count labels are hidden above 40 routers.

## Live runs (Analysis and Verify surfaces)

Loading a project also selects its newest run that has a backend evaluation (a bundle-only compile record is skipped rather than opened as an empty page). The run picker switches runs without leaving the page.

| surface | live source | explicit gaps shown |
|---|---|---|
| Analysis Summary | `GET /runs/{id}`: status, qualification + basis, requirement entries with verdicts and metric authority, fidelity warning, analyses | nothing computed locally; empty when a run carries no evaluation block |
| Metrics | `evaluation.metrics` | no histogram, percentiles, or distribution; no power/area/timing |
| Traffic Matrix | `GET /runs/{id}/traffic-matrix` packets/flits grid, pairs, classes, source trace path | per-link counters, per-pair latency, observed routes |
| Traffic Topology Overlay | declared channels (widths, latency) from the revision document | per-directed-link busy cycles: the run does not report them, so no utilization color is drawn |
| Trace Viewer | trace paths and digests from the run bundle | decoding/rendering is not implemented; no synthetic trace is generated |
| Run Comparison | second run read on demand, per-metric differences | comparability warning when revision or workload differ; no confidence intervals or significance |
| Verify · Evidence | `GET /runs/{id}/artifacts` bundle id, file list, every recorded sha256 | file bodies are not fetched or re-hashed here |
| Verify · Checks | `GET /runs/{id}/integrity`: packet/flit conservation per stage with availability, route realization, per-analysis status | deadlock proof, functional correctness, physical checks |
| Logs & Artifacts | the run bundle panel above, next to the local activity log | backend job log streams (the gateway has none) |

Loaded projects now use live bounded optimization, revision-manifest delivery, capability/gap registries, and the server-mediated AI topology workflow. Sample mode remains separate when no project is selected. See `docs/design/reviews/backend-completion-plan.md` (repository root) for current proof and remaining API gaps; it supersedes the older integration notes below.

## Live workload declaration (Workloads & Requirements surfaces)

The same loaded project also drives every workload surface from `GET /projects/{id}/draft`:

| surface | live content | explicit gaps |
|---|---|---|
| Workload Library | model name/family/serving mode, TP×DP×EP×PP, collectives with traffic classes and payloads, full agent inventory | payload is not multiplied by rank count (the draft never says if it is per rank); a parallelism/agent-count mismatch is reported as a mismatch |
| Structured Editor | every declared compute stage (owner, duration, input/output/weight bytes and locality), owner distribution | no dependency edges are declared, so the duration sum is labelled a total, not a critical path or schedule |
| Requirements Editor | declared requirement entries with binding flag, latency ceiling, bandwidth floor, matched to the loaded run's verdicts | verdicts never estimated; a run for a different revision is labelled as such |
| Endpoint Bindings | agent kinds and counts beside topology endpoint seats, per-kind differences | **no participant→endpoint binding table exists in these drafts**; seat order is not a rank |
| Assumptions & Inputs | `physical` clock/width/power/process, `noc_controls` link width/arbitration/obfuscation, schema and compiler-semantics versions, backend fidelity warning | per-agent clock assignment is `null`; no voltage, corners, or achieved timing |
| Validation / Lowering | traffic-class inventory, coherence checks (classes without requirements, requirements without traffic, stages, address ranges, agents vs parallelism), input contract a lowering step would receive | **no lowering adapter is connected**; nothing executable is produced and backend acceptance is unknown |

Observed against the real store:

- `p-72d52e15419d` (Qwen3-30B-A3B): TP2·DP1·EP4·PP1 = 8 units but **16 compute tiles** are declared — surfaced as an unexplained mismatch, not smoothed over. 96 stages across 8 owner indices, so half the tiles are assigned no work. `ep_dispatch`/`ep_combine` traffic has no requirement, so no verdict is expected for it.
- `p-d037b1c85839` (MWA correlator): 8 tiles / 8 seats, 8 stages with 500 ms durations, and a 7.68 MB `tile_ingest` all-to-all.
- Some drafts declare **no** `compute` block at all (most projects); their editor page says execution timing is not derivable rather than inventing stages.

## Project CRUD, compile, and the backend loop

`#/shared/projects` now writes to the store as well as reading it:

| action | endpoint | notes |
|---|---|---|
| New project (preset) | `POST /projects/from-preset` | 21 shipped presets; name optional |
| New project (blank) | `POST /projects` | optional catalog workload |
| Rename | `PATCH /projects/{id}` | |
| Set workload | `POST /projects/{id}/workload` | preset drafts ship with an empty workload, so the evaluation plan stays empty until one is chosen |
| Compile draft | `POST /projects/{id}/compile` | returns the new revision + certificate; the panel reloads, so the revision and topology appear immediately |
| Delete | `DELETE /projects/{id}` | requires typing the exact project id; removes revisions and runs |

Full loop, verified in the browser against the real gateway: create from preset `mesh4` → set workload `llama-dense-8b-64tiles` → compile (`r02`, certificate PASS) → launch `NETWORK_COMPLETION` → run published and selected → delete → store back to 18 projects. Temporary projects used for that check were removed afterwards.

Preset drafts have **no workload**, which is why a freshly created project shows "Nothing on this revision is ready to run" until a workload is set and the draft is recompiled — the evaluation plan is derived per revision, not per project.

## Projects & revisions: one workflow, four steps

The loaded-project page is a single vertical flow. Each step carries exactly one primary action, and nothing else on the page offers writes:

| step | shows | action |
|---|---|---|
| 1 Project | project id, declared workload, `TP/DP/EP/PP` | **Set workload**, **Rename** (each opens one inline field) |
| 2 Draft intent | fabric kind, compute tiles, workload, `compiled` / `uncompiled` | **Edit draft** — the editor opens inside this step |
| 3 Revision | active revision, router/channel/endpoint counts, design hash | **Compile draft** (plus **Show layout** for the topology graph) |
| 4 Evaluation | run count, latest run status and requirement verdict | **Open analysis** |

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

The Advanced draft sections JSON editor now supports address maps, workload collectives, requirements, dependencies, compute stages, and explicit topology documents. Edits invalidate validation; only the gateway's canonical document is saved. A server-hash precheck detects intervening changes, but atomic compare-and-swap requires backend support.

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

Latest checks: production build passed; **20 unit tests and 29 browser tests passed**, with the live backend test explicitly enabled (`VERITX_LIVE_TEST=1`). The live loop validated/saved/compiled a disposable project, launched evaluations and a bounded study, downloaded evidence, recovered after reload, and cleaned up; all 18 existing projects remained. All 44 routes were captured at both 1440×900 and 1280×800 (88 route screenshots), with unexpected external requests blocked and no page overflow or observed JavaScript errors in that route check. A dedicated browser test also asserts that configuring a runtime endpoint produces zero outbound requests. Local component/state flows are exercised separately. The design detector reported only two Inter-font saturation warnings; Inter is explicitly pinned by the approved visual direction, so it was retained. These checks do not establish a full accessibility audit or backend/hardware qualification.

Agent surfaces convert the exported runtime/approval screens into honest local intent. The connection form validates URL scheme, forbids embedded credentials/query secrets, restricts local-only policy to loopback hosts, accepts only an environment-reference *name* for credentials, and can be saved without any network request. Approval revocation clears only the local scope preview, preserving drafts, fixtures, and prepared artifacts. Model explanations, hypotheses, handshakes, and audit trails are explicitly unavailable rather than simulated.

Verification is parent-performed source and browser testing, not an independent delegated review. Unit checks cover numerical invariants, fixture identity, frontier membership, address arithmetic, bindings, brief bounds, revision conflicts, branch preservation, state validation, and descriptive exports. Browser checks exercise all routes at 1440×900 and 1280×800, block unexpected external requests, and exercise manual creation, edits, approvals, branch/recovery, keyboard navigation, checks, and actual JSON download.
