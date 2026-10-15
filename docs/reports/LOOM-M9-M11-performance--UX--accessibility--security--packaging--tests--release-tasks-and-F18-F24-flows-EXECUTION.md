# Loom M9–M11 execution audit (scope-specific)

**Tracker source:** `/home/datavex/Downloads/loom_production_execution_tracker.xlsx` (Master Tracker, E2E Flows, Release Gates), cross-checked field-for-field against the provided JSON extracts (367/367 tasks, 24/24 flows, 26/26 gates; zero mismatches). **Audited checkout:** `bf26286ef9abbdaf4c433a245a7a284bba6fea25`; branch `work/loom-m9-m11-6h`.

**Execution status at start:** no implementation changes; audit/test first. The checkout is a web Studio, not the Tauri desktop described by several tracker acceptance criteria. Do not treat web-only substitutes as closing desktop, local-engine, physical-tool, or signed-installer requirements. Every status below starts as `Not verified` unless evidence is recorded later in this report.

## Baseline/environment findings

- Clean assigned worktree at audit: `git status --short --branch` reported only `## work/loom-m9-m11-6h`; HEAD matched the requested SHA. No dirty original worktree was used.
- `apps/studio/package.json` identifies a fixture-backed web UI and explicitly says “No engine connectivity; boots from contract-validated fixtures only.” An exhaustive repository search found no `tauri.conf.json`, `Cargo.toml`, `.msi`, `.dmg`, `.AppImage`, or `.deb` artifacts/configuration; no desktop packaging pipeline is present in this checkout.
- `cd apps/studio && npm run build` **blocked**: `sh: 1: tsc: not found` (dependencies are not installed).
- `cd apps/studio && npx vitest run` **blocked**: `vitest` and `@vitejs/plugin-react` cannot be resolved; no test execution occurred.
- No performance budgets, target graph/matrix/trace measurements, release artifacts, security audit, signed license/update infrastructure, or clean-machine installer evidence has been established by this audit.

## Task ledger (verbatim tracker IDs and acceptance criteria)

Status definitions: `Not verified` means acceptance is not evidenced; it is not a claim that no related code exists. Statuses will only be advanced with named test/evidence.

### M9-01 — Set measurable UI performance budgets
- **Priority / area:** P0 / Performance
- **Acceptance (verbatim):** Budgets exist for project load, pan/zoom FPS, matrix interaction, trace seek and memory at target graph sizes.
- **Depends on:** M0-20
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-02 — Virtualize node/agent table
- **Priority / area:** P0 / Performance
- **Acceptance (verbatim):** 256+ rows scroll/edit smoothly and offscreen rows do not dominate DOM cost.
- **Depends on:** M2-15
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-03 — Virtualize I×T matrix
- **Priority / area:** P0 / Performance
- **Acceptance (verbatim):** Large matrices render only visible cells and retain keyboard navigation/selection.
- **Depends on:** M3-16
- **Tracker status at source:** Not Started
- **Execution status:** Blocked/not verified. Existing authoring matrix caps display at 12/24 nodes and has no evidence at 10k cells. Dependency M3-16 is an out-of-scope access-matrix task/source owner; implementation was not retained to avoid overlapping another runner. No large-matrix benchmark or acceptance proof is claimed.

### M9-04 — Use canvas/WebGL path for simulation heat when needed
- **Priority / area:** P1 / Performance
- **Acceptance (verbatim):** Heat rendering remains interactive near graph budget without changing data semantics.
- **Depends on:** M6-22
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-05 — Add graph spatial index
- **Priority / area:** P1 / Performance
- **Acceptance (verbatim):** Hit testing and viewport culling avoid O(N) work on every pointer move.
- **Depends on:** M1-05
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-06 — Throttle/debounce expensive derived updates
- **Priority / area:** P0 / Performance
- **Acceptance (verbatim):** Drag/resize/edit interactions do not trigger full validation/layout on every event.
- **Depends on:** M0-18,M1-06
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-07 — Window large trace playback
- **Priority / area:** P0 / Performance
- **Acceptance (verbatim):** Only necessary time/object slices are materialized for current playback/inspection.
- **Depends on:** M6-16
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-08 — Add memory limits and eviction for trace cache
- **Priority / area:** P1 / Performance
- **Acceptance (verbatim):** Long runs do not grow memory unbounded; cache behavior is observable in diagnostics.
- **Depends on:** M9-07
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-09 — Benchmark 256 nodes / 512 edges
- **Priority / area:** P0 / Performance
- **Acceptance (verbatim):** Automated benchmark records load/edit/zoom/playback performance against budgets.
- **Depends on:** M9-01,M1-34,M6-42
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-10 — Benchmark 10k access cells
- **Priority / area:** P0 / Performance
- **Acceptance (verbatim):** Matrix interaction and batch edit stay within defined budgets.
- **Depends on:** M9-01,M9-03
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-11 — Benchmark large trace fixture
- **Priority / area:** P0 / Performance
- **Acceptance (verbatim):** Seek/playback/parser memory and throughput are measured reproducibly.
- **Depends on:** M9-01,M9-07
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-12 — Create consistent app shell/navigation
- **Priority / area:** P0 / UX
- **Acceptance (verbatim):** All production views use one header/nav/status pattern with no duplicated project state controls.
- **Depends on:** M0-17
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-13 — Create consistent inspector pattern
- **Priority / area:** P1 / UX
- **Acceptance (verbatim):** Node/edge/rule/phase/run inspectors share spacing, sections, controls and error presentation.
- **Depends on:** M2-22,M2-23
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-14 — Add command palette
- **Priority / area:** P2 / UX
- **Acceptance (verbatim):** Navigation and major actions are searchable; disabled commands explain why.
- **Depends on:** M9-12
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-15 — Add global object search
- **Priority / area:** P1 / UX
- **Acceptance (verbatim):** Search finds nodes, edges, agents, domains, phases and runs and navigates to them.
- **Depends on:** M1-31,M6-32
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-16 — Add empty states
- **Priority / area:** P0 / UX
- **Acceptance (verbatim):** Every major view explains what input is missing and gives a direct next action.
- **Depends on:** M9-12
- **Tracker status at source:** Not Started
- **Execution status:** Partial. The Loom Graph editor's empty Nodes panel now explains that the graph has no nodes and offers a direct “create first node” action; component test verifies it creates a valid first node. This does not audit every major view or establish the consistent app shell dependency, so M9-16 is not Done.

### M9-17 — Add loading/progress states
- **Priority / area:** P0 / UX
- **Acceptance (verbatim):** Engine runs, trace indexing, imports and large saves show cancellable progress where possible.
- **Depends on:** M6-07,M8-04
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-18 — Add failure states with recovery actions
- **Priority / area:** P0 / UX
- **Acceptance (verbatim):** Common failures show exact cause plus retry/open logs/fix setting actions.
- **Depends on:** M7-01,M7-06
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-19 — Add light theme polish
- **Priority / area:** P1 / UX
- **Acceptance (verbatim):** Light theme uses low-saturation blue accents, readable neutral surfaces and consistent focus/selection states.
- **Depends on:** M9-12
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-20 — Add dark theme parity
- **Priority / area:** P2 / UX
- **Acceptance (verbatim):** All views remain legible and semantically equivalent in dark mode.
- **Depends on:** M9-19
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-21 — Add first-run onboarding
- **Priority / area:** P1 / UX
- **Acceptance (verbatim):** User can open sample project, understand graph→workload→run→inspect loop and dismiss onboarding permanently.
- **Depends on:** M9-12,M5-29,M6-42
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-22 — Ship sample projects
- **Priority / area:** P0 / UX
- **Acceptance (verbatim):** Small topology, multi-domain, floorplan and workload simulation samples open without network access.
- **Depends on:** M0-20,M8-22
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-23 — Keyboard-navigate core views
- **Priority / area:** P1 / Accessibility
- **Acceptance (verbatim):** Topology controls, tables, matrix and dialogs have functional keyboard paths and visible focus.
- **Depends on:** M9-12
- **Tracker status at source:** Not Started
- **Execution status:** Partial evidence only: existing `graph-authoring-a11y.contract.test.tsx` verifies canvas node selection with Enter and Space. Tables, access matrix, dialogs, and visible-focus styling were not comprehensively keyboard-audited; not Done.

### M9-24 — Audit color contrast and non-color cues
- **Priority / area:** P1 / Accessibility
- **Acceptance (verbatim):** Status/heat/problem severity remains interpretable without relying on hue alone.
- **Depends on:** M9-19
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-25 — Add accessible labels/tooltips
- **Priority / area:** P1 / Accessibility
- **Acceptance (verbatim):** Icons, controls and dense metrics expose readable labels and descriptions.
- **Depends on:** M9-12
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-26 — Validate 1366×768 layout
- **Priority / area:** P0 / Responsive
- **Acceptance (verbatim):** No primary controls become unreachable; dense panes collapse or scroll intentionally.
- **Depends on:** M9-12
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-27 — Validate high-DPI/4K scaling
- **Priority / area:** P1 / Responsive
- **Acceptance (verbatim):** Canvas, text and drag targets remain usable under common scaling factors.
- **Depends on:** M9-12
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-28 — Add glossary/help affordances
- **Priority / area:** P2 / Polish
- **Acceptance (verbatim):** VC, CDC, traffic class, provenance and metric terms have concise in-context explanations.
- **Depends on:** M9-12
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M9-29 — Large-project interactive flow
- **Priority / area:** P0 / E2E
- **Acceptance (verbatim):** Open target-size graph, edit nodes, access matrix, floorplan and trace playback without violating performance budgets.
- **Depends on:** M9-09,M9-10,M9-11
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-01 — Lock down Tauri command allowlist
- **Priority / area:** P0 / Security
- **Acceptance (verbatim):** Only required commands are exposed; each has explicit argument validation and least-privilege filesystem scope.
- **Depends on:** M8-01
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-02 — Sanitize all filesystem paths
- **Priority / area:** P0 / Security
- **Acceptance (verbatim):** Save/import/export/run paths cannot escape approved workspace/user-selected destinations via traversal.
- **Depends on:** M10-01
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-03 — Remove shell-string command construction
- **Priority / area:** P0 / Security
- **Acceptance (verbatim):** External engine/tool invocation uses structured argv with no user-controlled shell interpolation.
- **Depends on:** M6-03,M10-01
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-04 — Validate imported JSON sizes/depth
- **Priority / area:** P0 / Security
- **Acceptance (verbatim):** Oversized or pathological project/catalog/trace inputs fail safely before resource exhaustion.
- **Depends on:** M8-03,M2-12,M6-15
- **Tracker status at source:** Not Started
- **Execution status:** Partial implementation, not Done. Loom project JSON import now rejects inputs over 8 Mi characters or nesting over 128 before `JSON.parse`; focused tests cover both bounds and escaped delimiters. Catalog and trace import paths were not comprehensively audited or bounded, so full acceptance is unmet.

### M10-05 — Harden bundle extraction
- **Priority / area:** P0 / Security
- **Acceptance (verbatim):** Bundle import rejects path traversal, symlink escapes and hash mismatch.
- **Depends on:** M8-19
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-06 — Verify engine binary identity
- **Priority / area:** P0 / Security
- **Acceptance (verbatim):** Configured/shipped engine version and checksum are verified before run when distribution policy requires it.
- **Depends on:** M6-02
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-07 — Verify updater/package signatures
- **Priority / area:** P0 / Security
- **Acceptance (verbatim):** Unsigned or mismatched update artifacts are rejected.
- **Depends on:** M10-01
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-08 — Default to no network dependency
- **Priority / area:** P0 / Privacy
- **Acceptance (verbatim):** Core app does not send project/run data externally; any network feature is explicit and documented.
- **Depends on:** M8-22
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-09 — Add explicit network/telemetry setting
- **Priority / area:** P1 / Privacy
- **Acceptance (verbatim):** Any optional diagnostics/telemetry is opt-in or clearly controlled with local visibility.
- **Depends on:** M8-20,M10-08
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-10 — Redact sensitive paths from support bundle
- **Priority / area:** P0 / Privacy
- **Acceptance (verbatim):** Support export can remove local usernames/paths and clearly lists included files.
- **Depends on:** M7-17
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-11 — Implement signed node-lock license file
- **Priority / area:** P0 / Licensing
- **Acceptance (verbatim):** Offline license verifies signature/product/expiry/machine binding and exposes stable state to UI.
- **Depends on:** M8-01
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-12 — Build license state UI
- **Priority / area:** P0 / Licensing
- **Acceptance (verbatim):** Valid/expired/missing/mismatch states are clear and do not corrupt project access.
- **Depends on:** M10-11
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-13 — Gate engine spawn only, not project recovery
- **Priority / area:** P0 / Licensing
- **Acceptance (verbatim):** User can always open/export/recover owned projects; restricted actions are explicit.
- **Depends on:** M10-11,M6-03
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-14 — Add offline grace policy hook
- **Priority / area:** P1 / Licensing
- **Acceptance (verbatim):** Grace behavior is centralized, testable and does not depend on mutable UI time checks.
- **Depends on:** M10-11
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-15 — Define floating-license adapter interface
- **Priority / area:** P2 / Licensing
- **Acceptance (verbatim):** Future relay/commercial provider can plug into a stable lease API without changing UI semantics.
- **Depends on:** M10-11
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-16 — Implement update check
- **Priority / area:** P1 / Updater
- **Acceptance (verbatim):** App can check a configured release channel and show current/latest version without forcing update.
- **Depends on:** M10-07
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-17 — Implement signed update apply
- **Priority / area:** P1 / Updater
- **Acceptance (verbatim):** Downloaded update verifies signature/hash and applies through Tauri updater path.
- **Depends on:** M10-16,M10-07
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-18 — Implement failed-update rollback path
- **Priority / area:** P1 / Updater
- **Acceptance (verbatim):** Interrupted/failed update leaves a launchable prior version or clear recovery instructions.
- **Depends on:** M10-17
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-19 — Create release channel configuration
- **Priority / area:** P1 / Release
- **Acceptance (verbatim):** Dev/beta/stable endpoints/keys are separated and cannot be mixed accidentally.
- **Depends on:** M10-16
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-20 — Build Linux installer/package
- **Priority / area:** P0 / Packaging
- **Acceptance (verbatim):** Clean Ubuntu machine can install, launch, run health check and uninstall successfully.
- **Depends on:** M10-01,M10-11
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-21 — Build Windows installer
- **Priority / area:** P1 / Packaging
- **Acceptance (verbatim):** Clean supported Windows VM can install, launch, run health check and uninstall successfully.
- **Depends on:** M10-01,M10-11
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-22 — Build macOS signed/notarized package
- **Priority / area:** P2 / Packaging
- **Acceptance (verbatim):** Supported macOS machine can install/launch without bypassing platform security.
- **Depends on:** M10-01,M10-11
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-23 — Generate SBOM
- **Priority / area:** P1 / Release
- **Acceptance (verbatim):** Release artifact includes machine-readable dependency inventory for UI, Tauri and bundled binaries.
- **Depends on:** M10-20
- **Tracker status at source:** Not Started
- **Execution status:** Partial: reproducible, schema-validated CycloneDX 1.6 SBOM covers 12 production npm runtime components for the web UI. No Tauri package or bundled engine binaries exist in this checkout, so the full acceptance is unmet and the UI BOM is not a release-wide SBOM.

### M10-24 — Generate third-party license notices
- **Priority / area:** P0 / Release
- **Acceptance (verbatim):** Distributed dependencies and embedded assets have attributable license notices.
- **Depends on:** M10-23
- **Tracker status at source:** Not Started
- **Execution status:** Partial: generated `apps/studio/public/THIRD_PARTY_NOTICES.md` inventories 12 locked production npm packages with license texts, Inter/JetBrains Mono OFL texts, and the repository MIT notice for Studio artwork. It is explicitly limited to the web UI and does not close notices for desktop/binary distributions.

### M10-25 — Run dependency vulnerability audit
- **Priority / area:** P0 / Security
- **Acceptance (verbatim):** Known high/critical findings are resolved, mitigated or explicitly accepted before release.
- **Depends on:** M10-23
- **Tracker status at source:** Not Started
- **Execution status:** Partial: npm audit of the Studio dependency graph found one high advisory, remediated by lockfile update; re-audit reports zero. Full release graph (desktop/Tauri/bundled tools/SBOM) unavailable, so not Done.

### M10-26 — Harden crash/log data retention
- **Priority / area:** P1 / Security
- **Acceptance (verbatim):** Logs and crash artifacts have bounded retention and do not contain project contents unless required.
- **Depends on:** M7-06,M10-10
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M10-27 — Offline licensed launch→run→update check flow
- **Priority / area:** P0 / E2E
- **Acceptance (verbatim):** App launches offline, opens project, validates license, runs local engine and handles optional update check without blocking work.
- **Depends on:** M10-12,M10-13,M8-23,M10-16
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-01 — Contract schema tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance (verbatim):** Valid/invalid project fixtures cover every top-level schema block and version behavior.
- **Depends on:** M0-01
- **Tracker status at source:** Not Started
- **Execution status:** Done for the committed Loom project v1 schema surface: new table-driven contract tests pin all six top-level properties, all four required blocks, valid firewall/workload optional blocks, invalid type/unknown fields, missing required blocks and schema version round-trip behavior. Broader non-Loom schemas are not implied by this task.

### M11-02 — Migration tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance (verbatim):** Each migration step has before/after golden files and idempotence coverage.
- **Depends on:** M0-04
- **Tracker status at source:** Not Started
- **Execution status:** Blocked. The Studio source exposes Loom project schema v1 parsing/version rejection but no migration steps to test; fabricating before/after migration fixtures would invent unsupported behavior. Dependency M0-04 is outside this runner's scope. `rg -n -i 'migrat(e|ion)|schemaVersion' apps/studio/src` found only schema-version validation/presets and unrelated legacy-migration UI markers, not a Loom project migration pipeline. No migration acceptance is claimed.

### M11-03 — Project store/action tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance (verbatim):** Mutations, derived selectors and dirty state have deterministic tests.
- **Depends on:** M0-17,M0-18
- **Tracker status at source:** Not Started
- **Execution status:** Partial: deterministic hook tests now cover valid mutation, custom/dirty/undo/redo selectors, refused mutations without history changes, and load-as-clean behavior; a GraphLoom UI-flow test also exercises paste/inspector mutations and dirty/validation UI. This is not exhaustive coverage of all store actions/selectors, and parent dependencies remain Not Started, so M11-03 is not Done.

### M11-04 — Editor command/undo tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance (verbatim):** Every core command restores exact prior state on revert.
- **Depends on:** M1-01,M1-02
- **Tracker status at source:** Not Started
- **Execution status:** Partial evidence: an exhaustive TypeScript record requires undo tests for the standard GraphCommand variants; `add_node` now has exact empty-document undo/redo coverage and isolated add refusal is tested in a nonempty graph. Parent dependencies M1-01/M1-02 are `Not Started` in the source tracker and their broader editor-command acceptance is not established, so M11-04 remains not Done.

### M11-05 — Graph validator tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance (verbatim):** Dangling, duplicate, port, connectivity and topology validation have positive/negative cases.
- **Depends on:** M1-26,M1-30
- **Tracker status at source:** Not Started
- **Execution status:** Done for Loom graph/project validation: existing `graph-project.contract.test.ts` includes positive valid preset/schema/adapter cases and negative dangling endpoint, duplicate ID, port overflow, disconnected graph, unsupported topology lowering, edge semantics and VC intent cases. Focused test passes all 20 assertions.

### M11-06 — Catalog/agent validator tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance (verbatim):** Catalog ranges, protocol compatibility and address overlap cases are covered.
- **Depends on:** M2-24,M2-25
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-07 — Routing/VC validator tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance (verbatim):** Routing reachability and VC/QoS policy cases include unsupported graph shapes.
- **Depends on:** M3-25,M3-26
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-08 — Access/firewall tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance (verbatim):** Matrix edits, precedence, default policy and conflict detection have deterministic tests.
- **Depends on:** M3-16,M3-22
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-09 — Floorplan geometry tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance (verbatim):** Placement, overlap, Manhattan length and route calculations cover edge cases.
- **Depends on:** M4-15,M4-30
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-10 — Workload/mapping tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance (verbatim):** Parallelism, phases, communication ops, seat checks and mapping constraints are covered.
- **Depends on:** M5-06,M5-20
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-11 — Trace parser/index tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance (verbatim):** Valid, malformed, truncated and large traces have deterministic parser/index expectations.
- **Depends on:** M6-15,M6-18
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-12 — Run manager state-machine tests
- **Priority / area:** P0 / Unit Tests
- **Acceptance (verbatim):** Success, fail, cancel, timeout and crash paths cannot enter impossible states.
- **Depends on:** M6-07
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-13 — Save/load/autosave/recovery integration
- **Priority / area:** P0 / Integration Tests
- **Acceptance (verbatim):** Golden projects survive normal save, crash restore, migration and external-change handling.
- **Depends on:** M8-03,M8-10
- **Tracker status at source:** Not Started
- **Execution status:** Partial: graph UI integration proves file export/re-import after deliberately clearing autosave, and hook integration proves browser autosave recovery after store remount. Golden fixtures, actual process-crash restore, migrations and external-change handling remain untested; not Done.

### M11-14 — Engine handshake/spawn integration
- **Priority / area:** P0 / Integration Tests
- **Acceptance (verbatim):** Compatible, incompatible and missing engine cases are tested on packaged app path.
- **Depends on:** M6-02,M6-03
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-15 — Backend capability/refusal integration
- **Priority / area:** P0 / Integration Tests
- **Acceptance (verbatim):** Supported cases run; unsupported cases refuse before execution with stable reason codes.
- **Depends on:** M6-11,M5-26
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-16 — Run artifact/provenance integration
- **Priority / area:** P0 / Integration Tests
- **Acceptance (verbatim):** A completed run has consistent manifest, summary, trace/log hashes and project fingerprint.
- **Depends on:** M6-08,M7-08
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-17 — Automate create→edit→save→reopen flow
- **Priority / area:** P0 / E2E Tests
- **Acceptance (verbatim):** UI E2E covers topology edit, inspector edit, validation and persistence.
- **Depends on:** M1-34,M2-26
- **Tracker status at source:** Not Started
- **Execution status:** Partial UI-flow test added: actual `GraphLoom` UI adds an auto-wired node, edits inspector role, checks validation/custom preset, exports project JSON, clears autosave, imports the saved project and verifies persistence. Test is RTL/jsdom rather than production-browser E2E; dependencies M1-34/M2-26 remain Not Started, so not Done.

### M11-18 — Automate catalog→agents→domains flow
- **Priority / area:** P0 / E2E Tests
- **Acceptance (verbatim):** UI E2E stamps IP, edits agent ports/domains and resolves validation.
- **Depends on:** M2-26,M3-13
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-19 — Automate access/firewall flow
- **Priority / area:** P0 / E2E Tests
- **Acceptance (verbatim):** UI E2E edits matrix, inspects path/rule and verifies save/reload.
- **Depends on:** M3-27
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-20 — Automate floorplan flow
- **Priority / area:** P0 / E2E Tests
- **Acceptance (verbatim):** UI E2E places nodes, routes links, checks timing/congestion and exports image.
- **Depends on:** M4-34
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-21 — Automate workload/mapping flow
- **Priority / area:** P0 / E2E Tests
- **Acceptance (verbatim):** UI E2E creates workload, phases, mapping and validated run input.
- **Depends on:** M5-29
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-22 — Automate real simulation playback flow
- **Priority / area:** P0 / E2E Tests
- **Acceptance (verbatim):** Supported backend run completes and UI scrubs utilization/stalls with provenance.
- **Depends on:** M6-42
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-23 — Automate mock truthfulness flow
- **Priority / area:** P0 / E2E Tests
- **Acceptance (verbatim):** Mock fallback cannot be mistaken for measured/simulated backend data.
- **Depends on:** M6-43
- **Tracker status at source:** Not Started
- **Execution status:** Partial UI-contract evidence: added a playback interaction test that checks the visible `MOCK trace — playback geometry only` disclosure, absence of measured/backend wording, and preservation of the disclosure while scrubbing/changing metrics. It does not exercise full application fallback/backend integration, so task/flow not Done.

### M11-24 — Automate ProblemsPanel recovery flow
- **Priority / area:** P0 / E2E Tests
- **Acceptance (verbatim):** Injected config fault is found, navigated, fixed, rerun and disappears.
- **Depends on:** M7-23
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-25 — Automate crash recovery flow
- **Priority / area:** P0 / E2E Tests
- **Acceptance (verbatim):** Unsaved changes survive forced termination through autosave restore.
- **Depends on:** M8-25
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-26 — Automate large project performance flow
- **Priority / area:** P0 / E2E Tests
- **Acceptance (verbatim):** Target-size graph/matrix/trace meets budgets under automated instrumentation.
- **Depends on:** M9-29
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-27 — Test engine missing/incompatible
- **Priority / area:** P0 / Failure Injection
- **Acceptance (verbatim):** User receives actionable error and can continue editing/exporting project.
- **Depends on:** M7-19
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-28 — Test corrupt project/catalog input
- **Priority / area:** P0 / Failure Injection
- **Acceptance (verbatim):** App refuses unsafe/invalid content without crash or partial overwrite.
- **Depends on:** M10-04,M2-12
- **Tracker status at source:** Not Started
- **Execution status:** Partial UI failure-injection evidence: GraphLoom rejects an oversized file before calling `File.text()`, and reports malformed JSON, unsupported schema version, or missing required fields without replacing the existing graph. Catalog import/corruption behavior is not implemented or covered here; task not Done.

### M11-29 — Test corrupt/truncated trace
- **Priority / area:** P0 / Failure Injection
- **Acceptance (verbatim):** Run remains inspectable as failed with exact parse problem and logs.
- **Depends on:** M6-40
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-30 — Test permission denied/read-only project
- **Priority / area:** P0 / Failure Injection
- **Acceptance (verbatim):** Save/export failures do not lose in-memory state and recovery path is clear.
- **Depends on:** M8-04
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-31 — Test disk-full/low-space behavior
- **Priority / area:** P1 / Failure Injection
- **Acceptance (verbatim):** Run/save stops safely and never reports success after write failure.
- **Depends on:** M6-41,M8-06
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-32 — Test updater failure/rollback
- **Priority / area:** P1 / Failure Injection
- **Acceptance (verbatim):** Failed update leaves an operable app and records failure reason.
- **Depends on:** M10-18
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-33 — Zero unlabeled mock/estimate outputs
- **Priority / area:** P0 / Release Gates
- **Acceptance (verbatim):** Automated/manual audit finds no metric or physical result whose provenance state is hidden.
- **Depends on:** M0-22,M6-10,M4-16
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-34 — Zero P0 validation bypasses
- **Priority / area:** P0 / Release Gates
- **Acceptance (verbatim):** Every save/run/export path uses canonical validation or has an explicit documented exception.
- **Depends on:** M7-05,M8-04,M6-03
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-35 — No critical/high security findings
- **Priority / area:** P0 / Release Gates
- **Acceptance (verbatim):** Security audit/dependency audit has no unresolved critical/high issue accepted accidentally.
- **Depends on:** M10-25
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-36 — Performance budgets pass
- **Priority / area:** P0 / Release Gates
- **Acceptance (verbatim):** Target graph/matrix/trace benchmarks meet agreed budgets on reference hardware.
- **Depends on:** M9-09,M9-10,M9-11
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-37 — Installer/clean-machine smoke passes
- **Priority / area:** P0 / Release Gates
- **Acceptance (verbatim):** Production artifact installs, launches, opens sample, runs health check and uninstalls cleanly.
- **Depends on:** M10-20
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-38 — Write user quickstart
- **Priority / area:** P0 / Docs
- **Acceptance (verbatim):** A new user can create/open project, edit graph, configure workload and run/inspect a supported simulation.
- **Depends on:** M9-21,M9-22
- **Tracker status at source:** Not Started
- **Execution status:** Partial: `docs/product/LOOM-QUICKSTART.md` documents graph JSON create/edit/export/import, workload authoring and playback using current control names, while explicitly marking playback as mock/geometry-only. `GraphLoom` uses the local autosave scope whereas workload/simulation editors use a project-ID scope, and there is no unified project export or real engine run path. The full new-user integrated workflow is therefore unmet; M11-38 is not Done.

### M11-39 — Write topology/catalog/agent guide
- **Priority / area:** P1 / Docs
- **Acceptance (verbatim):** Guide covers graph editing, IP catalog, agent/port configuration and validation semantics.
- **Depends on:** M2-26
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-40 — Write domains/access/firewall guide
- **Priority / area:** P1 / Docs
- **Acceptance (verbatim):** Guide explains domains, matrix semantics, routing path and firewall precedence.
- **Depends on:** M3-27
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-41 — Write floorplan guide
- **Priority / area:** P1 / Docs
- **Acceptance (verbatim):** Guide distinguishes estimate vs external physical analysis and documents import/export limitations.
- **Depends on:** M4-34
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-42 — Write workload/simulation guide
- **Priority / area:** P0 / Docs
- **Acceptance (verbatim):** Guide covers phases, mapping, backend support/refusals, playback and provenance.
- **Depends on:** M6-42
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-43 — Write reproducibility/support guide
- **Priority / area:** P1 / Docs
- **Acceptance (verbatim):** Guide explains run fingerprints, replay, diff, logs and support bundles.
- **Depends on:** M7-23
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-44 — Write schema and engine protocol reference
- **Priority / area:** P0 / Docs
- **Acceptance (verbatim):** Project/trace/summary/run-manifest schemas and sidecar protocol are versioned and documented.
- **Depends on:** M0-15,M6-01
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-45 — Write troubleshooting guide
- **Priority / area:** P0 / Docs
- **Acceptance (verbatim):** Missing engine, version mismatch, corrupt trace, permission, license and update failures have procedures.
- **Depends on:** M7-19,M10-12
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-46 — Create release checklist
- **Priority / area:** P0 / Release
- **Acceptance (verbatim):** One checklist covers build, tests, provenance audit, security, installers, docs, update metadata and artifact hashes.
- **Depends on:** M11-33,M11-38
- **Tracker status at source:** Not Started
- **Execution status:** Done for this task's checklist-artifact acceptance: `docs/reports/LOOM-M11-release-candidate-checklist.md` contains evidence checkboxes for build/tests, provenance, security, installers, docs, update metadata, artifact hashes and release sign-off. This does **not** assert any release criterion passed; dependencies M11-33/M11-38 and candidate/gates remain open blockers.

### M11-47 — Create release notes/changelog
- **Priority / area:** P1 / Release
- **Acceptance (verbatim):** User-visible features, known limitations, supported backends and incompatible changes are explicit.
- **Depends on:** M11-46
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

### M11-48 — Create signed production candidate
- **Priority / area:** P0 / Release
- **Acceptance (verbatim):** Signed artifact passes release checklist and all P0 gates with no hidden mock/estimated behavior.
- **Depends on:** M11-46,M11-47
- **Tracker status at source:** Not Started
- **Execution status:** Not verified; no acceptance evidence yet.

## E2E flows (verbatim tracker criteria)

### F18 — Large graph interaction
- **Steps:** Open 256-node/512-edge project → pan/zoom/search/edit → open 10k-cell access matrix
- **Pass condition:** Interaction remains within performance budgets and no core control becomes unusable.
- **Milestones:** M9
- **Execution status:** Not run / not passed; relevant desktop/backend infrastructure and/or dependencies are absent or unverified.

### F19 — Offline licensed workflow
- **Steps:** Disconnect network → launch → open project → validate license → edit → run local engine → export
- **Pass condition:** Core workflow succeeds without network; optional online features do not block project access.
- **Milestones:** M8,M10
- **Execution status:** Not run / not passed; relevant desktop/backend infrastructure and/or dependencies are absent or unverified.

### F20 — Clean-machine production smoke
- **Steps:** Install production artifact → open sample → health check → run supported sim → export → uninstall
- **Pass condition:** No manual developer setup is required; signed artifact passes release checklist.
- **Milestones:** M10,M11
- **Execution status:** Not run / not passed; relevant desktop/backend infrastructure and/or dependencies are absent or unverified.

### F21 — Version migration flow
- **Steps:** Open older project → preview migration → migrate → inspect diff → save as current schema
- **Pass condition:** Migration is deterministic, source can be preserved, and no data is silently discarded.
- **Milestones:** M0,M8,M7
- **Execution status:** Not run / not passed; relevant desktop/backend infrastructure and/or dependencies are absent or unverified.

### F22 — Corrupt trace recovery
- **Steps:** Open run with truncated trace → parser error → inspect valid logs/manifest → export support bundle
- **Pass condition:** App does not crash or mark run complete; exact corrupt location and recovery actions are visible.
- **Milestones:** M6,M7
- **Execution status:** Not run / not passed; relevant desktop/backend infrastructure and/or dependencies are absent or unverified.

### F23 — Catalog mismatch flow
- **Steps:** Open project referencing missing/outdated catalog item → inspect warning → resolve with embedded/custom item
- **Pass condition:** Graph remains inspectable; provenance is preserved; replacement requires explicit user action.
- **Milestones:** M2,M7
- **Execution status:** Not run / not passed; relevant desktop/backend infrastructure and/or dependencies are absent or unverified.

### F24 — Release update rollback
- **Steps:** Check signed update → install → inject update failure → restart prior version
- **Pass condition:** Prior version remains launchable and project data remains accessible.
- **Milestones:** M10,M11
- **Execution status:** Not run / not passed; relevant desktop/backend infrastructure and/or dependencies are absent or unverified.

## Release gates relevant to this scope

### G15 — Offline core
- **Pass condition:** Open/edit/validate/save and local-engine run work without network connectivity.
- **Evidence/status at audit:** No qualifying evidence recorded; not passed.

### G16 — Target graph performance
- **Pass condition:** 256 nodes / 512 edges meets load/edit/pan/zoom budgets.
- **Evidence/status at audit:** No qualifying evidence recorded; not passed.

### G17 — Matrix performance
- **Pass condition:** Large I×T matrix meets scrolling/editing budgets with virtualization.
- **Evidence/status at audit:** No qualifying evidence recorded; not passed.

### G18 — Trace performance
- **Pass condition:** Large trace indexing/seek/playback stays within memory and latency budgets.
- **Evidence/status at audit:** No qualifying evidence recorded; not passed.

### G19 — Tauri boundary
- **Pass condition:** Filesystem and external-command inputs are validated; no shell interpolation/path traversal remains.
- **Evidence/status at audit:** No qualifying evidence recorded; not passed.

### G20 — License behavior
- **Pass condition:** License failure may gate restricted execution but never blocks project recovery/export.
- **Evidence/status at audit:** No qualifying evidence recorded; not passed.

### G21 — Update security
- **Pass condition:** Updates are signed/verified and a failed update has a recovery/rollback path.
- **Evidence/status at audit:** No qualifying evidence recorded; not passed.

### G22 — Dependency security
- **Pass condition:** No unresolved critical/high dependency finding remains unintentionally.
- **Evidence/status at audit:** No qualifying evidence recorded; not passed.

### G23 — Clean install
- **Pass condition:** Production package installs, launches, runs health check/sample flow and uninstalls on target OS.
- **Evidence/status at audit:** No qualifying evidence recorded; not passed.

### G24 — Documentation
- **Pass condition:** Quickstart, workflow guides, schema/protocol docs and troubleshooting match shipped behavior.
- **Evidence/status at audit:** No qualifying evidence recorded; not passed.

### G25 — P0 closure
- **Pass condition:** All P0 tracker tasks are Done or explicitly removed from release scope; zero P0 defects remain.
- **Evidence/status at audit:** No qualifying evidence recorded; not passed.

### G26 — E2E closure
- **Pass condition:** All release-critical E2E flows pass on the production candidate.
- **Evidence/status at audit:** No qualifying evidence recorded; not passed.

## Work log and test evidence

Record exact command, result, and the acceptance criterion it supports. Do not infer full task completion from partial test coverage.

### P0 imported-project admission hardening (M10-04, partial)

- Changed `apps/studio/src/graph/project.ts`: `parseProject` rejects JSON larger than `MAX_PROJECT_JSON_CHARS` (8 Mi characters) and scans JSON structural nesting before invoking `JSON.parse`, rejecting depth greater than `MAX_PROJECT_JSON_DEPTH` (128). String escapes are handled so delimiters inside quoted text do not affect nesting. Both Loom graph file-input handlers also reject files larger than `MAX_PROJECT_JSON_BYTES` (8 MiB) before `File.text()` allocates the input string.
- Added tests in `apps/studio/src/contract/graph-project.contract.test.ts` for over-limit input, over-depth input, and escaped delimiters. Added `apps/studio/src/contract/project-import-safety.contract.test.tsx` against the actual GraphLoom file-import UI: rejects oversize before reading, and verifies malformed JSON leaves the rendered graph intact.
- `cd apps/studio && npx vitest run src/contract/graph-project.contract.test.ts src/contract/graph-authoring-a11y.contract.test.tsx` — PASS after file guards: 2 files, 22 tests. The independent graph parser test had also passed at 1 file / 20 tests before the file-input guards.
- `cd apps/studio && npm run build` — PASS after change (including latest graph file admission guards); existing Vite large-chunk warning remains.
- This only hardens the Loom `parseProject` import used by Loom graph UI/store. It does not establish bounds for all Studio project formats, IP catalogs, or trace parsing. M10-04 remains partial/not Done.

### Release checklist artifact (M11-46, acceptance complete; release remains blocked)

- Added `docs/reports/LOOM-M11-release-candidate-checklist.md` with build/test and E2E evidence, reference-hardware performance, truth/provenance, security/privacy/license, OS installer and rollback, documentation, SBOM/license notices, artifact hashes/signatures, and release-gate sign-off sections.
- Checklist starts fully unchecked and explicitly requires evidence; it is a template, not release approval or evidence that any gate passes. M11-46 checklist-artifact acceptance is Done.
- Its dependencies M11-33 and M11-38 remain unverified and no production candidate exists. All release gates remain open; no release readiness is claimed.

### Web UI SBOM and third-party notices (M10-23/M10-24, partial)

- Added `apps/studio/scripts/generate_ui_sbom.sh`; it invokes pinned `@cyclonedx/cyclonedx-npm@6.0.1` with production-only npm dependencies, CycloneDX 1.6, reproducible mode, license evidence and schema validation. Output: `apps/studio/public/STUDIO_UI_SBOM.cdx.json` (12 production npm components; SHA-256 `a66913cf2c37d6f37f2dd8794ff2d624e737661afa554b7fe6d102a4b4b3a863`). A second generation produced identical bytes.
- `cd apps/studio && npm sbom --sbom-format=cyclonedx` was tried but the installed npm 9.2.0 does not implement `npm sbom`; replaced with the pinned CycloneDX CLI generator.
- Added official SIL OFL 1.1 text for Inter and JetBrains Mono under `apps/studio/public/licenses/` (upstream copyright verified against font name metadata) and added `apps/studio/scripts/generate_third_party_notices.py`. The generated `apps/studio/public/THIRD_PARTY_NOTICES.md` covers 12 production npm packages, the embedded fonts, and repository-licensed Studio artwork.
- `cd apps/studio && python3 scripts/generate_third_party_notices.py` — PASS: 12 package entries, 11 distinct license texts/assets (deduplicated identical texts). Output rerun was byte-identical (SHA-256 `10334c2d51b5d2fdcfd0a09c8b6ce5eb7074ff0c886e0203ea544c4bdcf462ac`). A first generator run exposed a stale summary variable after writing; fixed it and reran successfully.
- `cd apps/studio && npm run build && test -s dist/STUDIO_UI_SBOM.cdx.json && test -s dist/THIRD_PARTY_NOTICES.md && test -s dist/licenses/inter-OFL-1.1.txt` — PASS; Vite copies BOM, notices and font license into web `dist`. Existing large-bundle warning is described under build evidence.
- These artifacts do not inventory absent Tauri, engine binaries, platform/system packages, or future installer payloads. M10-23/M10-24 remain Partial/not Done.

### Graph validator acceptance evidence (M11-05, acceptance passed)

- `cd apps/studio && npx vitest run src/contract/graph-project.contract.test.ts` — PASS: 1 file, 20 tests. Covers valid preset round-trip/validation plus invalid dangling refs, duplicate IDs, port overflow, disconnect, unsupported graph/edge semantics and graph VC refusal.
- This closes M11-05's stated Loom graph-validator test cases; it does not claim unrelated engine/backend validators.

### Contract schema boundary coverage (M11-01, acceptance passed)

- Added `apps/studio/src/contract/loom-project-schema-boundaries.contract.test.ts`. It imports the canonical Loom project schema and pins its top-level field inventory, required fields, valid optional firewall/workload round-trip, invalid top-level blocks, missing-required-field behavior and schemaVersion rejection/deterministic serialization.
- `cd apps/studio && npx vitest run src/contract/loom-project-schema-boundaries.contract.test.ts` — PASS: 1 file, 12 cases after adding missing-version rejection.
- This closes the stated Loom project v1 schema-test acceptance only; it does not claim tests for unrelated draft, trace, summary or engine schemas.

### Corrupt project import recovery proof (M11-28, partial)

- Added `apps/studio/src/contract/project-import-safety.contract.test.tsx`. Renders the actual `GraphLoom` component; dispatches oversized, malformed JSON, unsupported schema-version and missing-required-field project files; verifies admission rejects oversized content before `File.text()`, exposes an actionable error, and leaves the existing graph intact.
- `cd apps/studio && npx vitest run --pool=vmThreads src/contract/project-import-safety.contract.test.tsx` — PASS: 1 file, 4 tests. The oversized test initially used a Jest-DOM matcher not installed in this suite; replaced it with a native `textContent` assertion and reran successfully.
- Does not cover catalog imports or every corrupt-content variant; M11-28 remains partial/not Done.

### P0 empty graph recovery / empty-state slice (M9-16, partial)

- Updated `apps/studio/src/pages/loom/GraphLoom.tsx`: when the project has zero nodes, the Nodes panel displays the missing-input explanation and a direct create action. The generic auto-wired Add action is hidden until a first node exists, avoiding a duplicate/nonfunctional control.
- Added a UI regression case to `apps/studio/src/contract/graph-authoring-flow.contract.test.tsx`, seeding a valid empty Loom project in local autosave, checking the explanation, invoking the CTA and asserting a created node plus clean graph validation.
- `cd apps/studio && npx vitest run src/contract/graph-authoring-flow.contract.test.tsx` — PASS: 1 file, 2 tests.
- Scope is explicitly limited to the Loom graph view. Other production views and app-shell empty states remain unaudited; M9-16 stays partial/not Done.

### User quickstart artifact (M11-38, partial)

- Added `docs/product/LOOM-QUICKSTART.md` with current startup commands, route example, graph editing and validated JSON import/export, workload setup, and mock playback controls. It clearly distinguishes browser-local project state and mock geometry playback from server projects, real simulation, measured performance, and release qualification.
- Content was manually checked against `apps/studio/src/pages/loom/data.ts` view IDs, `GraphLoom.tsx` control labels/import-export behavior and its local `useGraphStore` scope, `useAuthoring(projectId)` plus `WorkloadEditor`/`SimPlayback` control text in `authoring.tsx`, and `router.ts` project route parsing. This source review revealed the graph/workload store-scope mismatch documented in the guide. It is not a new-user usability study.
- No true engine execution is available in this web checkout. The quickstart therefore remains partial against M11-38's supported-simulation acceptance; M9-21/M9-22 dependencies also remain open.

### M9 matrix dependency/ownership check

- Inspected `FirewallEditor`: current source caps the displayed matrix at 12 nodes, or 24 after expand; it does not prove the 10k-cell/virtualized acceptance.
- M9-03 depends on tracker task M3-16 (`Build virtualized Initiator×Target matrix`), which is outside assigned milestone scope. A transient local spike was tested then reverted to keep implementation ownership with the assigned M3 runner; no untested matrix changes remain in this worktree.
- Consequently M9-03 and F18 remain blocked; the spike is not cited as evidence.

### Project store and save/remount integration evidence (M11-03/M11-13, partial)

- Added `apps/studio/src/contract/graph-store.contract.test.ts`: deterministic hook-level coverage for valid mutation and derived `isCustom`/dirty/undo/redo selectors, refusal without state/history mutation, project load as a clean baseline, preset reset, exact serialization, and browser autosave recovery after store remount.
- `cd apps/studio && npx vitest run --pool=vmThreads src/contract/graph-store.contract.test.ts` — PASS: 1 file, 6 tests; covers valid/refused `run`, undo/redo selectors, `loadJson`, `loadPreset`, `serialize`, autosave restore, and clean/custom/dirty state.
- `apps/studio/src/contract/graph-authoring-flow.contract.test.tsx` also asserts the graph store exposes `unsaved` after mutations, derives `custom` preset and clean validation state, and persists the changed node through explicit project JSON export/re-import.
- Evidence is limited to this local authoring component/store path; it does not constitute exhaustive store action/selector or crash/migration/external-change integration. M11-03/M11-13 remain partial/not Done.

### Graph create/edit/save/reopen UI test (M11-17, partial)

- Added `apps/studio/src/contract/graph-authoring-flow.contract.test.tsx`: actual GraphLoom UI adds an auto-wired topology node, edits its inspector role, checks graph validation/custom shape/dirty indicator, downloads serialized `project.json`, clears local autosave, imports the downloaded JSON, and verifies the saved node and validation after reopen.
- `cd apps/studio && npx vitest run src/contract/graph-authoring-flow.contract.test.tsx` — PASS: 1 test. Initial selector collision was narrowed to `.loom-strip-key`; a later test extension added explicit export/import instead of relying only on remount.
- This is a jsdom component-flow proof, not production-browser E2E. M1-34/M2-26 dependencies remain Not Started; M11-17 partial/not Done.

### Mock playback provenance UI proof (M11-23, partial)

- Added `apps/studio/src/contract/mock-truthfulness.contract.test.tsx`; renders real `SimPlayback`, verifies explicit MOCK/geometry-only/no-per-cycle-artifact disclosure, scrubs to a later frame, changes the metric, and asserts the disclosure remains visible.
- `cd apps/studio && npx vitest run src/contract/mock-truthfulness.contract.test.tsx` — PASS: 1 test. Two initial test-query assumptions failed because Testing Library returned nested nodes/multiple `cycle` elements; corrected selectors, rerun passed. This is component UI proof, not the production E2E Mock fallback→backend-isolation flow.

### P0 command undo/redo coverage (M11-04, partial)

- Added `apps/studio/src/contract/graph-history-undo.contract.test.ts`: an exhaustive TypeScript `Record<Exclude<GraphCommand['type'], 'add_node'>, ...>` forces a test fixture for every other current mutating command; all test exact-JSON snapshots on undo and exact replay on redo. Added valid `add_node` empty-project undo/redo coverage and refusal/no-history coverage for adding an isolated node to a nonempty project.
- `cd apps/studio && npx vitest run src/contract/graph-history-undo.contract.test.ts` — PASS after `add_node` extension: 1 file, 11 tests. Earlier combined graph-history + graph-project run: 2 files, 30 tests; rerun needed for current combined count.
- `cd apps/studio && npx vitest run` after scoped changes — earlier PASS: 22 test files, 296 tests. Latest final-tree proof: `cd apps/studio && npx vitest run --pool=vmThreads` — PASS on the final test tree: 24 files, 317 tests. The default pool and `--maxWorkers=1` each failed during module loading with ENOENT for generated `/tmp/.../client/<hash>` files (the default invocation reported 21 failed suites / 83 tests reached); using Vitest's documented `vmThreads` pool completed all suites.
- This test coverage does not claim full product command inventory/boundary-case coverage. M11-04 remains partial/not Done.

### Baseline and dependency remediation

- Compared every populated tracker row with the JSON extract: `Master Tracker` 367 rows, `E2E Flows` 24 rows, `Release Gates` 26 rows; **zero field mismatches**.
- `cd apps/studio && npm ci` — PASS (155 packages installed); npm emitted engine warnings because Node is v22.22.1 while several transitive packages require v22.22.2+.
- `cd apps/studio && npm audit --json` — FOUND one high-severity transitive `source-map-js@1.2.1` advisory (GHSA-68fv-2mgg-jv7q), reachable through `jsdom`/`postcss`; fix available.
- `cd apps/studio && npm audit fix` — PASS; lockfile now resolves `source-map-js@1.2.2`. Narrow dependency remediation, no source behavior change. Preserved its `BSD-3-Clause` lock metadata, verified against the installed package manifest; this does not constitute a complete third-party notices deliverable.
- `cd apps/studio && npm audit --audit-level=high` — PASS on final tree, 0 reported vulnerabilities. A final clean `npm ci` confirmed the installed package is `source-map-js@1.2.2` (the first lockfile-only remediation had left the existing install at 1.2.1 until this reinstall). One audit invocation transiently returned npm registry HTTP 400; rerunning `npm audit --json` and `npm audit --audit-level=high` succeeded with zero findings. This is evidence for the Studio npm dependency graph only, **not** a full distribution/Tauri/bundled-binary audit; M10-25 and G22 therefore remain not fully verified.
- `cd apps/studio && npm run build` — PASS on final tree: TypeScript and Vite build pass; main JS chunk is 1,094.65 kB (295.87 kB gzip), above Vite's 500 kB advisory threshold. No tracker budget is defined, so this is recorded as a warning, not a claimed budget pass/fail.
- `cd apps/studio && npx vitest run` — PASS: 18 test files, 280 tests. Includes existing accessibility contract tests for Enter/Space selection of graph canvas nodes, but does not constitute the broad M11-17..30/E2E requirements.
- `cd apps/studio && npm run validate` — PASS on final tree: 5/5 fixture schema/linkage/vocabulary fast checks. Tool output explicitly says `FAST PATH ONLY: backend realizability not proven`; this is not proof of real simulation or production release readiness.
- `python -m pytest apps/studio/tests/test_studio_contract_v2.py -q` — PASS: 7 passed, 3 skipped. This is Studio contract coverage, not proof of any specific tracker test task's full acceptance.
- `git diff --check` — PASS.

### Scope interpretation after execution

The lockfile change removes the observed high-severity advisory from the audited npm dependency graph, but does not close M10-25 because that acceptance spans the complete release dependency/binary set and requires release finding disposition. Existing graph keyboard tests are useful partial evidence for M9-23, not proof of all core views/tables/matrix/dialog keyboard paths. Existing test-suite pass does not close any broad M11 task unless its individual acceptance is covered; no tracker M11 test task is marked Done here. F18 is not executable against the product as specified (256-node/512-edge + 10k-cell matrix/performance budgets); no such measured benchmark was run. F19/F20/F24 require native offline license/local-engine/signed-update/package infrastructure that is absent. F21–F23 are outside this runner's task-ID scope and are not claimed passed.

## Blockers / release truth

- Product architecture mismatch: this worktree contains a React/Vite fixture-backed web Studio, not a Tauri desktop. Tasks requiring Tauri command allowlists/filesystem scope, native updater/signatures, offline node-lock licensing, platform installers, signed candidate, and desktop clean-machine tests cannot be closed by web-only changes.
- Functional performance criteria need agreed budgets, reproducible target-size fixtures, and reference hardware; no numeric thresholds should be invented.
- E2E flows requiring real local engine, signed license/update, installation, or physical/external tools must remain unpassed without corresponding infrastructure and evidence.
- Task ownership remains limited to M9–M11 and F18–F24; unrelated task IDs are not implemented.
