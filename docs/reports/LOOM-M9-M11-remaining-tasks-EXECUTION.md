# Loom M9–M11 remaining-tasks execution report

**Tracker:** `/home/datavex/Downloads/loom_production_execution_tracker.xlsx` (cross-checked against supplied JSON extracts). **Audited worktree:** assigned isolated checkout; branch `pi-subagents/m9-m11-51f486e-8b95-s0-t0`, starting HEAD `41ca430f85f4b1fd99771b3050eb9f5644d1c5e4`. **Scope:** only M9–M11 task IDs.

**Source reconciliation:** 367 tasks total; 104 in scope. Flows: 24; release gates: 26. This report preserves tracker IDs and verbatim acceptance criteria; the tracker itself was not modified.

## Baseline and boundaries

- The product in this checkout is a web Studio. The tracker includes Tauri commands, local-engine spawn, licensed desktop launch, physical-tool execution, signed updates/installers, and cross-platform clean-machine requirements. Browser evidence cannot satisfy those acceptance criteria.
- Starting tree was clean (`git status --short --branch` showed only the branch line).
- No credentials or original dirty checkout were accessed.
- Report statuses are execution-time evidence labels, not tracker status changes. `Not verified` is not a claim that no related implementation exists. A partial implementation remains partial until the complete acceptance test is evidenced.

## Task ledger (tracker acceptance verbatim)

### M9-01 — Set measurable UI performance budgets
- **Priority / area:** P0 / Performance
- **Acceptance:** Budgets exist for project load, pan/zoom FPS, matrix interaction, trace seek and memory at target graph sizes.
- **Depends on:** M0-20
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-02 — Virtualize node/agent table
- **Priority / area:** P0 / Performance
- **Acceptance:** 256+ rows scroll/edit smoothly and offscreen rows do not dominate DOM cost.
- **Depends on:** M2-15
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-03 — Virtualize I×T matrix
- **Priority / area:** P0 / Performance
- **Acceptance:** Large matrices render only visible cells and retain keyboard navigation/selection.
- **Depends on:** M3-16
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-04 — Use canvas/WebGL path for simulation heat when needed
- **Priority / area:** P1 / Performance
- **Acceptance:** Heat rendering remains interactive near graph budget without changing data semantics.
- **Depends on:** M6-22
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-05 — Add graph spatial index
- **Priority / area:** P1 / Performance
- **Acceptance:** Hit testing and viewport culling avoid O(N) work on every pointer move.
- **Depends on:** M1-05
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-06 — Throttle/debounce expensive derived updates
- **Priority / area:** P0 / Performance
- **Acceptance:** Drag/resize/edit interactions do not trigger full validation/layout on every event.
- **Depends on:** M0-18,M1-06
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-07 — Window large trace playback
- **Priority / area:** P0 / Performance
- **Acceptance:** Only necessary time/object slices are materialized for current playback/inspection.
- **Depends on:** M6-16
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-08 — Add memory limits and eviction for trace cache
- **Priority / area:** P1 / Performance
- **Acceptance:** Long runs do not grow memory unbounded; cache behavior is observable in diagnostics.
- **Depends on:** M9-07
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-09 — Benchmark 256 nodes / 512 edges
- **Priority / area:** P0 / Performance
- **Acceptance:** Automated benchmark records load/edit/zoom/playback performance against budgets.
- **Depends on:** M9-01,M1-34,M6-42
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-10 — Benchmark 10k access cells
- **Priority / area:** P0 / Performance
- **Acceptance:** Matrix interaction and batch edit stay within defined budgets.
- **Depends on:** M9-01,M9-03
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-11 — Benchmark large trace fixture
- **Priority / area:** P0 / Performance
- **Acceptance:** Seek/playback/parser memory and throughput are measured reproducibly.
- **Depends on:** M9-01,M9-07
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-12 — Create consistent app shell/navigation
- **Priority / area:** P0 / UX
- **Acceptance:** All production views use one header/nav/status pattern with no duplicated project state controls.
- **Depends on:** M0-17
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-13 — Create consistent inspector pattern
- **Priority / area:** P1 / UX
- **Acceptance:** Node/edge/rule/phase/run inspectors share spacing, sections, controls and error presentation.
- **Depends on:** M2-22,M2-23
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-14 — Add command palette
- **Priority / area:** P2 / UX
- **Acceptance:** Navigation and major actions are searchable; disabled commands explain why.
- **Depends on:** M9-12
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-15 — Add global object search
- **Priority / area:** P1 / UX
- **Acceptance:** Search finds nodes, edges, agents, domains, phases and runs and navigates to them.
- **Depends on:** M1-31,M6-32
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-16 — Add empty states
- **Priority / area:** P0 / UX
- **Acceptance:** Every major view explains what input is missing and gives a direct next action.
- **Depends on:** M9-12
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-17 — Add loading/progress states
- **Priority / area:** P0 / UX
- **Acceptance:** Engine runs, trace indexing, imports and large saves show cancellable progress where possible.
- **Depends on:** M6-07,M8-04
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-18 — Add failure states with recovery actions
- **Priority / area:** P0 / UX
- **Acceptance:** Common failures show exact cause plus retry/open logs/fix setting actions.
- **Depends on:** M7-01,M7-06
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-19 — Add light theme polish
- **Priority / area:** P1 / UX
- **Acceptance:** Light theme uses low-saturation blue accents, readable neutral surfaces and consistent focus/selection states.
- **Depends on:** M9-12
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-20 — Add dark theme parity
- **Priority / area:** P2 / UX
- **Acceptance:** All views remain legible and semantically equivalent in dark mode.
- **Depends on:** M9-19
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-21 — Add first-run onboarding
- **Priority / area:** P1 / UX
- **Acceptance:** User can open sample project, understand graph→workload→run→inspect loop and dismiss onboarding permanently.
- **Depends on:** M9-12,M5-29,M6-42
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-22 — Ship sample projects
- **Priority / area:** P0 / UX
- **Acceptance:** Small topology, multi-domain, floorplan and workload simulation samples open without network access.
- **Depends on:** M0-20,M8-22
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-23 — Keyboard-navigate core views
- **Priority / area:** P1 / Accessibility
- **Acceptance:** Topology controls, tables, matrix and dialogs have functional keyboard paths and visible focus.
- **Depends on:** M9-12
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-24 — Audit color contrast and non-color cues
- **Priority / area:** P1 / Accessibility
- **Acceptance:** Status/heat/problem severity remains interpretable without relying on hue alone.
- **Depends on:** M9-19
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-25 — Add accessible labels/tooltips
- **Priority / area:** P1 / Accessibility
- **Acceptance:** Icons, controls and dense metrics expose readable labels and descriptions.
- **Depends on:** M9-12
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-26 — Validate 1366×768 layout
- **Priority / area:** P0 / Responsive
- **Acceptance:** No primary controls become unreachable; dense panes collapse or scroll intentionally.
- **Depends on:** M9-12
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-27 — Validate high-DPI/4K scaling
- **Priority / area:** P1 / Responsive
- **Acceptance:** Canvas, text and drag targets remain usable under common scaling factors.
- **Depends on:** M9-12
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-28 — Add glossary/help affordances
- **Priority / area:** P2 / Polish
- **Acceptance:** VC, CDC, traffic class, provenance and metric terms have concise in-context explanations.
- **Depends on:** M9-12
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M9-29 — Large-project interactive flow
- **Priority / area:** P0 / E2E
- **Acceptance:** Open target-size graph, edit nodes, access matrix, floorplan and trace playback without violating performance budgets.
- **Depends on:** M9-09,M9-10,M9-11
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-01 — Lock down Tauri command allowlist
- **Priority / area:** P0 / Security
- **Acceptance:** Only required commands are exposed; each has explicit argument validation and least-privilege filesystem scope.
- **Depends on:** M8-01
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-02 — Sanitize all filesystem paths
- **Priority / area:** P0 / Security
- **Acceptance:** Save/import/export/run paths cannot escape approved workspace/user-selected destinations via traversal.
- **Depends on:** M10-01
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-03 — Remove shell-string command construction
- **Priority / area:** P0 / Security
- **Acceptance:** External engine/tool invocation uses structured argv with no user-controlled shell interpolation.
- **Depends on:** M6-03,M10-01
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-04 — Validate imported JSON sizes/depth
- **Priority / area:** P0 / Security
- **Acceptance:** Oversized or pathological project/catalog/trace inputs fail safely before resource exhaustion.
- **Depends on:** M8-03,M2-12,M6-15
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-05 — Harden bundle extraction
- **Priority / area:** P0 / Security
- **Acceptance:** Bundle import rejects path traversal, symlink escapes and hash mismatch.
- **Depends on:** M8-19
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-06 — Verify engine binary identity
- **Priority / area:** P0 / Security
- **Acceptance:** Configured/shipped engine version and checksum are verified before run when distribution policy requires it.
- **Depends on:** M6-02
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-07 — Verify updater/package signatures
- **Priority / area:** P0 / Security
- **Acceptance:** Unsigned or mismatched update artifacts are rejected.
- **Depends on:** M10-01
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-08 — Default to no network dependency
- **Priority / area:** P0 / Privacy
- **Acceptance:** Core app does not send project/run data externally; any network feature is explicit and documented.
- **Depends on:** M8-22
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-09 — Add explicit network/telemetry setting
- **Priority / area:** P1 / Privacy
- **Acceptance:** Any optional diagnostics/telemetry is opt-in or clearly controlled with local visibility.
- **Depends on:** M8-20,M10-08
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-10 — Redact sensitive paths from support bundle
- **Priority / area:** P0 / Privacy
- **Acceptance:** Support export can remove local usernames/paths and clearly lists included files.
- **Depends on:** M7-17
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-11 — Implement signed node-lock license file
- **Priority / area:** P0 / Licensing
- **Acceptance:** Offline license verifies signature/product/expiry/machine binding and exposes stable state to UI.
- **Depends on:** M8-01
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-12 — Build license state UI
- **Priority / area:** P0 / Licensing
- **Acceptance:** Valid/expired/missing/mismatch states are clear and do not corrupt project access.
- **Depends on:** M10-11
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-13 — Gate engine spawn only, not project recovery
- **Priority / area:** P0 / Licensing
- **Acceptance:** User can always open/export/recover owned projects; restricted actions are explicit.
- **Depends on:** M10-11,M6-03
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-14 — Add offline grace policy hook
- **Priority / area:** P1 / Licensing
- **Acceptance:** Grace behavior is centralized, testable and does not depend on mutable UI time checks.
- **Depends on:** M10-11
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-15 — Define floating-license adapter interface
- **Priority / area:** P2 / Licensing
- **Acceptance:** Future relay/commercial provider can plug into a stable lease API without changing UI semantics.
- **Depends on:** M10-11
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-16 — Implement update check
- **Priority / area:** P1 / Updater
- **Acceptance:** App can check a configured release channel and show current/latest version without forcing update.
- **Depends on:** M10-07
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-17 — Implement signed update apply
- **Priority / area:** P1 / Updater
- **Acceptance:** Downloaded update verifies signature/hash and applies through Tauri updater path.
- **Depends on:** M10-16,M10-07
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-18 — Implement failed-update rollback path
- **Priority / area:** P1 / Updater
- **Acceptance:** Interrupted/failed update leaves a launchable prior version or clear recovery instructions.
- **Depends on:** M10-17
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-19 — Create release channel configuration
- **Priority / area:** P1 / Release
- **Acceptance:** Dev/beta/stable endpoints/keys are separated and cannot be mixed accidentally.
- **Depends on:** M10-16
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-20 — Build Linux installer/package
- **Priority / area:** P0 / Packaging
- **Acceptance:** Clean Ubuntu machine can install, launch, run health check and uninstall successfully.
- **Depends on:** M10-01,M10-11
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-21 — Build Windows installer
- **Priority / area:** P1 / Packaging
- **Acceptance:** Clean supported Windows VM can install, launch, run health check and uninstall successfully.
- **Depends on:** M10-01,M10-11
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-22 — Build macOS signed/notarized package
- **Priority / area:** P2 / Packaging
- **Acceptance:** Supported macOS machine can install/launch without bypassing platform security.
- **Depends on:** M10-01,M10-11
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-23 — Generate SBOM
- **Priority / area:** P1 / Release
- **Acceptance:** Release artifact includes machine-readable dependency inventory for UI, Tauri and bundled binaries.
- **Depends on:** M10-20
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-24 — Generate third-party license notices
- **Priority / area:** P0 / Release
- **Acceptance:** Distributed dependencies and embedded assets have attributable license notices.
- **Depends on:** M10-23
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-25 — Run dependency vulnerability audit
- **Priority / area:** P0 / Security
- **Acceptance:** Known high/critical findings are resolved, mitigated or explicitly accepted before release.
- **Depends on:** M10-23
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-26 — Harden crash/log data retention
- **Priority / area:** P1 / Security
- **Acceptance:** Logs and crash artifacts have bounded retention and do not contain project contents unless required.
- **Depends on:** M7-06,M10-10
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M10-27 — Offline licensed launch→run→update check flow
- **Priority / area:** P0 / E2E
- **Acceptance:** App launches offline, opens project, validates license, runs local engine and handles optional update check without blocking work.
- **Depends on:** M10-12,M10-13,M8-23,M10-16
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-01 — Contract schema tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance:** Valid/invalid project fixtures cover every top-level schema block and version behavior.
- **Depends on:** M0-01
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-02 — Migration tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance:** Each migration step has before/after golden files and idempotence coverage.
- **Depends on:** M0-04
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-03 — Project store/action tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance:** Mutations, derived selectors and dirty state have deterministic tests.
- **Depends on:** M0-17,M0-18
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-04 — Editor command/undo tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance:** Every core command restores exact prior state on revert.
- **Depends on:** M1-01,M1-02
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-05 — Graph validator tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance:** Dangling, duplicate, port, connectivity and topology validation have positive/negative cases.
- **Depends on:** M1-26,M1-30
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-06 — Catalog/agent validator tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance:** Catalog ranges, protocol compatibility and address overlap cases are covered.
- **Depends on:** M2-24,M2-25
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-07 — Routing/VC validator tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance:** Routing reachability and VC/QoS policy cases include unsupported graph shapes.
- **Depends on:** M3-25,M3-26
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-08 — Access/firewall tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance:** Matrix edits, precedence, default policy and conflict detection have deterministic tests.
- **Depends on:** M3-16,M3-22
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-09 — Floorplan geometry tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance:** Placement, overlap, Manhattan length and route calculations cover edge cases.
- **Depends on:** M4-15,M4-30
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-10 — Workload/mapping tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance:** Parallelism, phases, communication ops, seat checks and mapping constraints are covered.
- **Depends on:** M5-06,M5-20
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-11 — Trace parser/index tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance:** Valid, malformed, truncated and large traces have deterministic parser/index expectations.
- **Depends on:** M6-15,M6-18
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-12 — Run manager state-machine tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance:** Success, fail, cancel, timeout and crash paths cannot enter impossible states.
- **Depends on:** M6-07
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-13 — Save/load/autosave/recovery integration
- **Priority / area:** P0 / Integration Tests
- **Acceptance:** Golden projects survive normal save, crash restore, migration and external-change handling.
- **Depends on:** M8-03,M8-10
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-14 — Engine handshake/spawn integration
- **Priority / area:** P0 / Integration Tests
- **Acceptance:** Compatible, incompatible and missing engine cases are tested on packaged app path.
- **Depends on:** M6-02,M6-03
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-15 — Backend capability/refusal integration
- **Priority / area:** P0 / Integration Tests
- **Acceptance:** Supported cases run; unsupported cases refuse before execution with stable reason codes.
- **Depends on:** M6-11,M5-26
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-16 — Run artifact/provenance integration
- **Priority / area:** P0 / Integration Tests
- **Acceptance:** A completed run has consistent manifest, summary, trace/log hashes and project fingerprint.
- **Depends on:** M6-08,M7-08
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-17 — Automate create→edit→save→reopen flow
- **Priority / area:** P0 / E2E Tests
- **Acceptance:** UI E2E covers topology edit, inspector edit, validation and persistence.
- **Depends on:** M1-34,M2-26
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-18 — Automate catalog→agents→domains flow
- **Priority / area:** P0 / E2E Tests
- **Acceptance:** UI E2E stamps IP, edits agent ports/domains and resolves validation.
- **Depends on:** M2-26,M3-13
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-19 — Automate access/firewall flow
- **Priority / area:** P0 / E2E Tests
- **Acceptance:** UI E2E edits matrix, inspects path/rule and verifies save/reload.
- **Depends on:** M3-27
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-20 — Automate floorplan flow
- **Priority / area:** P0 / E2E Tests
- **Acceptance:** UI E2E places nodes, routes links, checks timing/congestion and exports image.
- **Depends on:** M4-34
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-21 — Automate workload/mapping flow
- **Priority / area:** P0 / E2E Tests
- **Acceptance:** UI E2E creates workload, phases, mapping and validated run input.
- **Depends on:** M5-29
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-22 — Automate real simulation playback flow
- **Priority / area:** P0 / E2E Tests
- **Acceptance:** Supported backend run completes and UI scrubs utilization/stalls with provenance.
- **Depends on:** M6-42
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-23 — Automate mock truthfulness flow
- **Priority / area:** P0 / E2E Tests
- **Acceptance:** Mock fallback cannot be mistaken for measured/simulated backend data.
- **Depends on:** M6-43
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-24 — Automate ProblemsPanel recovery flow
- **Priority / area:** P0 / E2E Tests
- **Acceptance:** Injected config fault is found, navigated, fixed, rerun and disappears.
- **Depends on:** M7-23
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-25 — Automate crash recovery flow
- **Priority / area:** P0 / E2E Tests
- **Acceptance:** Unsaved changes survive forced termination through autosave restore.
- **Depends on:** M8-25
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-26 — Automate large project performance flow
- **Priority / area:** P0 / E2E Tests
- **Acceptance:** Target-size graph/matrix/trace meets budgets under automated instrumentation.
- **Depends on:** M9-29
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-27 — Test engine missing/incompatible
- **Priority / area:** P0 / Failure Injection
- **Acceptance:** User receives actionable error and can continue editing/exporting project.
- **Depends on:** M7-19
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-28 — Test corrupt project/catalog input
- **Priority / area:** P0 / Failure Injection
- **Acceptance:** App refuses unsafe/invalid content without crash or partial overwrite.
- **Depends on:** M10-04,M2-12
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-29 — Test corrupt/truncated trace
- **Priority / area:** P0 / Failure Injection
- **Acceptance:** Run remains inspectable as failed with exact parse problem and logs.
- **Depends on:** M6-40
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-30 — Test permission denied/read-only project
- **Priority / area:** P0 / Failure Injection
- **Acceptance:** Save/export failures do not lose in-memory state and recovery path is clear.
- **Depends on:** M8-04
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-31 — Test disk-full/low-space behavior
- **Priority / area:** P1 / Failure Injection
- **Acceptance:** Run/save stops safely and never reports success after write failure.
- **Depends on:** M6-41,M8-06
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-32 — Test updater failure/rollback
- **Priority / area:** P1 / Failure Injection
- **Acceptance:** Failed update leaves an operable app and records failure reason.
- **Depends on:** M10-18
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-33 — Zero unlabeled mock/estimate outputs
- **Priority / area:** P0 / Release Gates
- **Acceptance:** Automated/manual audit finds no metric or physical result whose provenance state is hidden.
- **Depends on:** M0-22,M6-10,M4-16
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-34 — Zero P0 validation bypasses
- **Priority / area:** P0 / Release Gates
- **Acceptance:** Every save/run/export path uses canonical validation or has an explicit documented exception.
- **Depends on:** M7-05,M8-04,M6-03
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-35 — No critical/high security findings
- **Priority / area:** P0 / Release Gates
- **Acceptance:** Security audit/dependency audit has no unresolved critical/high issue accepted accidentally.
- **Depends on:** M10-25
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-36 — Performance budgets pass
- **Priority / area:** P0 / Release Gates
- **Acceptance:** Target graph/matrix/trace benchmarks meet agreed budgets on reference hardware.
- **Depends on:** M9-09,M9-10,M9-11
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-37 — Installer/clean-machine smoke passes
- **Priority / area:** P0 / Release Gates
- **Acceptance:** Production artifact installs, launches, opens sample, runs health check and uninstalls cleanly.
- **Depends on:** M10-20
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-38 — Write user quickstart
- **Priority / area:** P0 / Docs
- **Acceptance:** A new user can create/open project, edit graph, configure workload and run/inspect a supported simulation.
- **Depends on:** M9-21,M9-22
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-39 — Write topology/catalog/agent guide
- **Priority / area:** P1 / Docs
- **Acceptance:** Guide covers graph editing, IP catalog, agent/port configuration and validation semantics.
- **Depends on:** M2-26
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-40 — Write domains/access/firewall guide
- **Priority / area:** P1 / Docs
- **Acceptance:** Guide explains domains, matrix semantics, routing path and firewall precedence.
- **Depends on:** M3-27
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-41 — Write floorplan guide
- **Priority / area:** P1 / Docs
- **Acceptance:** Guide distinguishes estimate vs external physical analysis and documents import/export limitations.
- **Depends on:** M4-34
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-42 — Write workload/simulation guide
- **Priority / area:** P0 / Docs
- **Acceptance:** Guide covers phases, mapping, backend support/refusals, playback and provenance.
- **Depends on:** M6-42
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-43 — Write reproducibility/support guide
- **Priority / area:** P1 / Docs
- **Acceptance:** Guide explains run fingerprints, replay, diff, logs and support bundles.
- **Depends on:** M7-23
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-44 — Write schema and engine protocol reference
- **Priority / area:** P0 / Docs
- **Acceptance:** Project/trace/summary/run-manifest schemas and sidecar protocol are versioned and documented.
- **Depends on:** M0-15,M6-01
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-45 — Write troubleshooting guide
- **Priority / area:** P0 / Docs
- **Acceptance:** Missing engine, version mismatch, corrupt trace, permission, license and update failures have procedures.
- **Depends on:** M7-19,M10-12
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-46 — Create release checklist
- **Priority / area:** P0 / Release
- **Acceptance:** One checklist covers build, tests, provenance audit, security, installers, docs, update metadata and artifact hashes.
- **Depends on:** M11-33,M11-38
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-47 — Create release notes/changelog
- **Priority / area:** P1 / Release
- **Acceptance:** User-visible features, known limitations, supported backends and incompatible changes are explicit.
- **Depends on:** M11-46
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

### M11-48 — Create signed production candidate
- **Priority / area:** P0 / Release
- **Acceptance:** Signed artifact passes release checklist and all P0 gates with no hidden mock/estimated behavior.
- **Depends on:** M11-46,M11-47
- **Tracker status:** Not Started
- **Execution status:** Not verified at report creation; see evidence and updates below.

## E2E flows and gates relevant to M9–M11

The full tracker contains 24 E2E flows and 26 release gates. M9–M11 evidence cannot claim any flow/gate closed without its complete pass condition and environment-appropriate evidence. Desktop packaging/licensing/update gates remain blocked by the absence of a Tauri desktop/package in this product checkout.

## Execution log

### Baseline audit
- `git status --short --branch` → clean at `pi-subagents/m9-m11-51f486e-8b95-s0-t0` (starting HEAD `41ca430f85f4b1fd99771b3050eb9f5644d1c5e4`).
- Source inventory: `apps/studio/package.json` describes the application as fixture-backed with no engine connectivity; repository inventory shows a web app and no production Tauri configuration/artifacts.
- No measured target-size performance baselines, signed artifacts, physical-tool evidence, or clean-machine installer tests are inferred from browser fixtures.

### Validation commands

Commands will be recorded with exact results as work proceeds. No tracker status will be upgraded on assumption.

## Remaining blockers / closeout

- Desktop-specific M10 acceptance is not demonstrable in the present web-only checkout (Tauri allowlist, license-bound spawn, signed updater/package, cross-OS installers).
- M9 target-size performance acceptance needs a reproducible harness, approved budgets, named reference hardware, and measurements.
- E2E tasks that require supported real backend runs, physical results, autosave/crash through desktop, or signed packaging require those actual environments.

## Execution updates

### M10-04 — imported JSON size/depth admission (partial; not Done)

- The existing project parser already defines an 8 MiB JSON/byte boundary and 128-level nesting cap (`apps/studio/src/graph/project.ts`, `MAX_PROJECT_JSON_CHARS`, `MAX_PROJECT_JSON_BYTES`, `MAX_PROJECT_JSON_DEPTH`) and has contract tests for over-limit project JSON. This is browser/web project input evidence only; it does not establish catalog import coverage or all imported input paths.
- Added a trace JSONL per-record admission boundary before `JSON.parse`: `MAX_TRACE_RECORD_CHARS = 1 MiB`, `MAX_TRACE_RECORD_DEPTH = 64`, with quote/escape-aware nesting scan and source-line-specific errors in `apps/studio/src/graph/traceParser.ts`.
- Added contract tests for oversized/deep records to `apps/studio/src/graph/traceParser.contract.test.ts`. The tests are **written but not executed** (see environment blocker); therefore this task remains partial/unverified, not Done. Also note current stream decoder retains an unterminated line until newline; the record cap is checked when a line is delivered, so a chunked malicious no-newline source may still accumulate in decoder `pending`. Further hardening and catalog coverage are needed before M10-04 can pass.

### M9-01 — candidate budgets (proposal only; not Done)

- Added `docs/reports/LOOM-M9-M11-performance-budgets.md` with explicit target sizes/operations and measurable candidate limits. Every threshold is labeled provisional; no reference hardware has been named/approved and no performance measurements were run. This is deliberately not acceptance evidence or a claim that M9-01/M9-09/M9-10/M9-11/M11-36 pass.

### Test/dependency installation blocker

- `cd apps/studio && npm ci --ignore-scripts --no-audit --no-fund` attempted to provision the locked toolchain but exited `228` with `ENOSPC: no space left on device`. Node emitted `EBADENGINE` warnings (environment Node `v22.22.1`, package requirements include `^22.22.2`). At the subsequent check, filesystem `/dev/nvme0n1p2` was 100% full with 8.5 MiB available; `apps/studio/node_modules/.bin/vitest` and `tsc` were absent. No test result is claimed. Do not remove pre-existing workspace/cache files to work around this.
- `python3 apps/studio/scripts/validate_fixtures.py` → pass for 5/5 fixtures (schemas + linkage + engine vocabulary); script explicitly reports “FAST PATH ONLY: backend realizability not proven.” This is fixture validation, not the changed TypeScript test.
- `git diff --check` → pass (no whitespace errors).

### Existing release artifacts observed (not promoted to Done)

- `apps/studio/public/STUDIO_UI_SBOM.cdx.json` and `apps/studio/public/THIRD_PARTY_NOTICES.md` exist; generation scripts exist. No independently verified completeness against bundled desktop/binary dependencies was performed, so M10-23/M10-24 are not marked Done.
- `docs/reports/LOOM-M11-release-candidate-checklist.md` is an unchecked release checklist template; no release signoffs or candidate evidence were found. M11-46/M11-48 and release gates remain open.

## Current status summary

- Implemented narrow change: trace-record input limits and associated contract tests (M10-04 partial; tests blocked by disk capacity).
- Added candidate performance-budget proposal (M9-01 not accepted pending owner approval/reference machine; not measured).
- Ran fixture validator and whitespace check successfully as listed above.
- No E2E flow or release gate is claimed complete. Desktop, physical-tool, backend execution, signed artifact, and clean-machine installer acceptance is not evidenced in this web-only checkout.

### Tracker reconciliation detail

- Used `openpyxl` on the downloaded workbook's `Master Tracker` sheet and compared all task IDs plus Milestone, Area, Task, Acceptance / Done When, Depends On, Priority, and Status against `/home/datavex/.cache/loom-durable-runner/tasks.json`: 367 rows vs 367 entries, 0 mismatches. The 104 M9–M11 records in this report are rendered from those exact tracker fields.
- Added a streamed oversized unterminated-record test alongside the line-parser limits. It is also written but unexecuted because the pinned JS test toolchain could not be installed.

### M11-45 — troubleshooting guide (partial; not Done)

- Added `docs/product/LOOM-TROUBLESHOOTING.md` documenting current web-only project JSON/trace/browser-save behavior and explicitly identifying absent engine, licensing, updater, and desktop recovery paths. It gives no fictitious procedure for those unavailable systems.
- This is useful web support documentation but does not meet full acceptance for product-specific license/update/engine/permission recovery procedures on the eventual desktop release; M11-45 remains partial.

### Additional scoped evidence reviewed (not upgraded to Done)

- **M11-38 (quickstart):** `docs/product/LOOM-QUICKSTART.md` exists and clearly explains current graph/workload-preview interactions, but explicitly says Studio lacks engine connectivity and its playback is mock/geometry-only. Thus the acceptance step “run/inspect a supported simulation” is not evidenced; partial documentation only.
- **M11-44 (schema/protocol reference):** `contracts/loom/v1/README.md` documents the v1 project, trace-event, summary, run-manifest, provenance and validation-issue contracts; corresponding JSON schemas exist. `apps/studio/src/graph/engineProtocol.ts` defines protocol version 1 and request/response types while explicitly describing a future sidecar. No running/packaged sidecar interoperability evidence exists in this web checkout. Existing docs are relevant evidence, but full task acceptance was not independently tested here.
- **M11-11 (trace parser/index tests):** existing `apps/studio/src/graph/traceParser.contract.test.ts` already covers valid records, invalid records, malformed source lines, stable-ID validation, 4,096-record indexing, and 10,000-record streaming/progress behavior. The new admission-bound tests are additional coverage but remain unexecuted. This does not provide tests for every demanded large-trace memory/throughput requirement.

### Artifact inventory command

- `find . -type f \( -name tauri.conf.json -o -name Cargo.toml -o -name '*.msi' -o -name '*.dmg' -o -name '*.AppImage' -o -name '*.deb' \) -print` → no results. This is a scoped repository inventory, not proof about products outside this checkout.

- Second toolchain installation attempt: `cd apps/studio && npm ci --ignore-scripts --no-audit --no-fund --prefer-offline` → exit `228`, `ENOSPC`. No further npm installation attempt is warranted in this checkout.
- Targeted runtime smoke test with the environment's standalone Bun (no dependency install): from `apps/studio`, a `bun -` script imported `traceParser.ts` and asserted (1) a valid frame parses, (2) oversized and >64-deep records reject with the expected reasons, and (3) an oversized unterminated `ReadableStream` rejects at line 1. **PASS**: `valid trace line; oversized/deep line rejection; oversized unterminated stream rejection`. This exercises changed runtime code, but does not substitute for the authored Vitest contract suite or typecheck.

## Follow-up slice: M9-22 sample projects (partial; not Done)

Selected M9-22 as the next feasible P0 item after reviewing this audit. Existing portable project fixtures covered small topology, multi-domain, and workload input, but no floorplanned `.project.json` was in `apps/studio/fixtures/projects/`; floorplan data existed only as a separate graph fixture. Added:

- `apps/studio/fixtures/projects/floorplanned.project.json`, a schema-v1 3-node authored placement sample with a die outline and placements. Its metadata disclaims physical-tool output.
- `apps/studio/fixtures/projects/README.md` with local-file import steps and scope/truth limits for all sample categories.
- `apps/studio/src/contract/loom-sample-projects.contract.test.ts` checking static small-topology, multi-domain, floorplan, and workload project imports with no network/API access and explicit no-physical/no-real-simulation implications.

**Narrow proof:** from `apps/studio`, standalone `bun -` imported `parseProject` and parsed `small-custom.project.json`, `multi-domain.project.json`, `floorplanned.project.json`, `workload-bound.project.json`, and `mesh-8x8.project.json`: all passed (respectively 3/2, 4/3, 3/2, 2/1, and 64/112 nodes/edges). This establishes parser acceptance of the local files, not browser file-picker UX or offline app operation. The new Vitest test was not run (Vitest still unavailable after the recorded ENOSPC installs).

**Status remains partial:** the app is web-only and has no real engine; the workload sample is authored simulation input and the current preview remains mock. Do not describe it as a simulation result. Browser/offline end-to-end sample opening and a supported non-mock simulation workflow remain unproved. No M9-22 completion or release-gate pass is claimed.

## Follow-up slice: M10-24 third-party notices (web-only evidence; desktop scope unresolved)

Inspected the existing notices/SBOM and found they lacked a checked-in offline consistency validator. Added `apps/studio/scripts/validate_third_party_notices.py` and the `npm run validate-notices` script. The validator compares the checked-in SBOM and notice inventory (package, locked version, declared license) with the 12 non-dev packages in `package-lock.json`; checks each dependency has a license-text attribution; and checks the self-hosted Inter/JetBrains fonts and board artwork have existing license files/notices.

- `cd apps/studio && npm run validate-notices` → **PASS**: `12 locked production packages match both SBOM and notices; embedded fonts and board artwork have license attribution`.
- `find apps/studio/public -type f` listed only the two fonts, their two OFL texts, the board artwork, SBOM, and notices. No additional public third-party assets were found.
- `git diff --check` → pass.

**Status:** The checked-in web Studio inventory/notices are now reproducibly cross-checked. Do not claim coverage for a future desktop installer, Tauri runtime, or bundled engine: the validator and current artifacts explicitly exclude them, and none exist in this checkout. M10-24 remains **partial for overall production distribution** until applicable packaged-artifact dependencies/assets (if any) are enumerated and covered. The package SBOM is likewise not evidence for a signed desktop release.

### Next-priority blockers / selection notes

- P0 M9-02/M9-03 require table/matrix virtualization and large-target tests; M9-03 depends on M3-16 owned outside this scope. The 10k-cell acceptance has no available matrix fixture/harness in this checkout, so no claim or overlapping matrix implementation was made.
- P0 M9-06, M9-07, M9-17, M9-18 overlap derived-store/trace/run/progress/failure source areas owned by prerequisite milestones; no broad source changes were made without the owning acceptance context.
- P0 M10 desktop security/licensing/package tasks have no Tauri command surface/artifacts to test. The report's existing web-only finding remains the concrete blocker.
- P0 M11-46 has an existing checklist template, but its stated dependencies M11-33 and M11-38 (provenance/quickstart complete evidence) remain unresolved; checklist presence is not release sign-off.

### M9-22 sample-schema follow-up

The first local Draft 2020-12 audit revealed two material sample defects: the new floorplan sample used the runtime parser's legacy `unit/die` variant and failed the authoritative v1 JSON Schema; the pre-existing `multi-domain.project.json` contained no domain block despite its name. Corrected the floorplan sample to canonical v1 `units/dieOutline/placements/keepouts/hierarchies`, and replaced the multi-domain example with the actual multi-domain graph fixture plus explanatory metadata. Removed the documentation's inaccurate claim that the sample carried a delay model.

- `cd apps/studio && npm run validate-loom-samples` → **PASS** for small topology, multi-domain (8 nodes/8 edges), floorplan and workload projects; all pass local `contracts/loom/v1/project.schema.json`. Output notes authored workload/floorplan are not measured or physical results.
- Standalone Bun `parseProject` → PASS for all four category samples (3/2, 8/8, 3/2, 2/1 nodes/edges). `npm run validate-notices` also remains PASS.
- The automated Vitest sample test exists but remains unexecuted because Vitest is absent. Full UI import/Network-off browser E2E and a real backend simulation remain unproved; M9-22 stays partial.

## Follow-up slice: M11-01 contract schema test coverage (partial; not Done)

Reviewed existing M11 contract coverage: project-schema boundary/version tests, agent-v1 tests, routing/schema tests, and golden fixtures for access, domains, floorplan, workload and VC/QoS. Added `apps/studio/src/contract/loom-contract-coverage.contract.test.ts` to explicitly pin all 14 project top-level schema properties and v1 version constants, and reject eleven invalid top-level values (routing, firewall, workload, VC config, domains, agents, floorplan, metadata, access and both version fields).

- Standalone Bun import/assertion of the local project schema and `validateProject` → **PASS**: 14 top-level blocks found, both version constants pinned, 11 invalid cases rejected at expected paths.
- `npm run validate-loom-samples` separately validates valid sample projects against the Draft 2020-12 project schema.
- Vitest source tests and the added contract file are not run: the two `npm ci` attempts failed with ENOSPC and `node_modules/.bin/vitest` remains absent. This task is not Done until the locked unit/contract suite executes successfully and its full required invalid/valid coverage is reviewed.

## Follow-up slice: M11-02 migration tests (partial; not Done)

Reviewed `apps/studio/src/contract/loom-m0-migration.contract.test.ts` and existing golden pair `apps/studio/src/graph/migration-fixtures/v0-side-map.json` → `v0-side-map.v1.json`. Added `apps/studio/src/contract/loom-migration-idempotence.contract.test.ts` with exact composite golden output/step assertions and idempotence cases for the stored v0 fixture, unversioned v0, and early-v1 missing compiler-semantics version.

- Standalone Bun migration smoke: **PASS**. v0 fixture performed 4 recorded steps; unversioned v0 2; early v1 1. Each second pass returned byte-identical canonical output with `changed=false` and no steps. Stored v0 expected-output golden matched exactly.
- Vitest test remains unexecuted due the already recorded missing dependency/disk blocker.
- At this point the existing checked-in golden was composite rather than step-isolated. A later focused slice below adds before/after golden pairs for the individual supported migration branches; the suite remains unexecuted in Vitest.

### M11-02 step-level golden follow-up

Added four distinct before/after fixture pairs under `apps/studio/src/graph/migration-fixtures/steps/` for v0 version/semantics defaults, early-v1 semantics default, edge pipeline-side-map fold, and supported firewall-to-access conversion. `apps/studio/src/contract/loom-migration-steps.contract.test.ts` pins each exact step list, exact golden output, and a second no-op migration pass.

- Standalone Bun execution of those same four fixture cases → **PASS** for before bytes, expected ordered migration steps, after bytes, and idempotent second pass.
- Together with the existing refusal tests for unsupported versions/conflicts/unsafe firewall shapes and the prior v0 combined golden, this closes the identified per-step golden/idempotence implementation gap. The written Vitest suite itself remains unrun due environment dependency installation failure; official CI validation is still pending. No desktop/engine acceptance is involved.

## Follow-up slice: M11-05 graph validator tests (partial; not Done)

Reviewed `apps/studio/src/contract/graph-project.contract.test.ts`, which already contains positive/negative cases for dangling edges, duplicate IDs, port exhaustion, disconnection, and unsupported routing shapes. Added no overlapping graph-validator implementation.

- Standalone Bun runtime assertions against `validateProject` / `supportsXYRouting` → **PASS**: valid connected mesh accepted; dangling endpoint, duplicate node ID, incident-edge port overuse, disconnected graph rejected; ring not classified as supported XY mesh.
- First probe used `ports=0` while asserting the *overuse* diagnostic. That correctly triggered the separate invalid-port-value check, so the harness assertion (not the product) was wrong. Corrected the probe to `ports=1` on a 2+ degree mesh; it then passed the intended port-overuse assertion. No source adjustment was needed.
- The full Vitest contract file remains unexecuted due unavailable dependencies. The manual smoke is narrow and is not a substitute for complete graph-validator tests; M11-05 remains partial pending Vitest/CI.

## Dependency-space blocker revisited; JS toolchain now provisioned

After the prior two ENOSPC failures and several independent backlog slices, the shared filesystem had recovered from 17 MiB available to 102 GiB available (`df -h .`: 78% used). Revisited the dependency blocker rather than treating the old failure as permanent:

- `cd apps/studio && npm ci --ignore-scripts --no-audit --no-fund` → **success**, 155 packages added. npm still warns that Node `v22.22.1` is below several packages' declared `^22.22.2` minimum; tests/build ran despite the warning.
- Focused suite: `npx vitest run src/graph/traceParser.contract.test.ts src/contract/loom-sample-projects.contract.test.ts src/contract/loom-contract-coverage.contract.test.ts src/contract/loom-migration-idempotence.contract.test.ts src/contract/loom-migration-steps.contract.test.ts src/contract/graph-project.contract.test.ts src/contract/loom-project-schema-boundaries.contract.test.ts src/contract/loom-agents-v1.contract.test.ts src/contract/loom-catalog-reference.contract.test.ts` → **9 files passed, 113 tests passed**.
- Full suite: `npx vitest run` → **56 files passed, 550 tests passed**.
- Production build/typecheck: `npm run build` → **PASS**; Vite emitted a chunk-size warning for `main` (1,238.13 kB minified, 333.94 kB gzip; configured warning threshold 500 kB). This is a performance risk, not a build failure.
- `npm run validate-loom-samples` → PASS for all four required categories; `npm run validate-notices` → PASS for web package/assets inventory; `git diff --check` → PASS.

This supersedes earlier “Vitest unavailable / no further install attempt” notes and all “test not run” statements for tests included in the above full suite. It does not substitute for desktop, real-engine, physical-tool, or clean-installer testing.

## Acceptance closures supported by executed tests

- **M11-01 — DONE (contract schema tests):** schema-boundary/version test additions plus existing agent, routing, and golden-fixture contracts cover the v1 project top-level schema surface and invalid/version cases. Focused 9-file/113-test suite and full 56-file/550-test suite passed.
- **M11-02 — DONE (migration tests):** step-specific v0/early-v1/side-map/firewall before/after goldens and idempotence tests passed in Vitest as part of the full suite; stored combined v0 golden still matches. No claim extends to unsupported migration formats, which are explicitly refused/tested.
- **M11-05 — DONE (graph validator tests):** graph contract test file passed in the full suite; cases cover dangling/duplicate IDs, port exhaustion, connectivity and unsupported topology/routing shapes. Additional focused Bun probe passed the positive mesh and negative cases.
- **M11-11 — DONE (trace parser/index tests):** trace parser contract tests passed in the full suite, covering valid/malformed/unknown-reference input, 4,096-record indexing, 10,000-record streaming/progress, valid-prefix behavior on corrupt final line, and new size/depth admission boundaries. This is parser correctness evidence, not a 100k-frame performance/memory benchmark (M9-11 remains separate and open).

Other M9/M10/M11 status labels remain unchanged unless separately resolved below; no E2E flow/release gate is inferred from these unit/contract tests.

## Further scoped test closures after provisioning

Additional higher-priority test acceptance slices were checked and executed with the now-installed lockfile toolchain:

- **M11-03 — DONE (project store/action tests):** focused `npx vitest run src/contract/graph-store.contract.test.ts src/graph/store.offline.contract.test.tsx` → 2 files / 11 tests passed. Coverage verifies mutations, derived preset/custom selectors, dirty state, undo/redo, refused mutation invariance, and offline persistence/reload.
- **M11-04 — DONE (editor command/undo tests):** focused `npx vitest run src/contract/graph-history-undo.contract.test.ts` → 1 file / 16 tests passed. Every reversible command including `add_node` restores the exact serialized prior state and replays the exact after-state; refused add does not alter history.
- **M11-07 — DONE (routing/VC validator tests):** `npx vitest run src/contract/loom-vc-qos-v1.contract.test.ts src/contract/graph-project.contract.test.ts` → included in the following 4-file / 69-test run; tests cover route reachability, routing policies, unsupported topology shapes, VC references, and QoS mappings.
- **M11-08 — DONE (access/firewall tests):** the same 4-file run includes `loom-access-floorplan` and `graph-project`; default policy, precedence conflicts/dangling scope, firewall duplicate/conflict, and route authorization cases pass.
- **M11-10 — DONE (workload/mapping tests):** the same run includes `loom-workload-v1` and `graph-project`; phases/communication, parallelism/capacity, mapping identities/rank uniqueness, traffic classes and seat demand cases pass.
- Exact grouped command: `npx vitest run src/contract/loom-vc-qos-v1.contract.test.ts src/contract/loom-access-floorplan.contract.test.ts src/contract/graph-project.contract.test.ts src/contract/loom-workload-v1.contract.test.ts` → **4 files / 69 tests passed**.

**Not closed by that run:** M11-06 does not have evidence for address-window overlap/protocol-compatibility and catalog range validations (the available catalog reference test covers provenance/fallback metadata); M11-09 lacks verified overlap/route edge cases; M11-12's state-machine tests do not yet cover all cancel/timeout/crash paths. These remain open rather than expanding into other milestone owners' implementation.

### M9-22 component import proof update

The sample-project test now mounts `GraphLoom` and loads each small-topology, multi-domain, floorplan and workload JSON through the actual local file-input handler. `npx vitest run src/contract/loom-sample-projects.contract.test.tsx` → **1 file / 7 tests passed**. No API/network mock or backend is involved. This verifies local Graph editor import; it does **not** prove the workload draft is joined to the separate Simulation workspace or produce a real simulation. M9-22 remains partial on that cross-view/sample workflow requirement.
