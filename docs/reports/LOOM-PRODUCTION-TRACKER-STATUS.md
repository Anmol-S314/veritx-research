# Loom production tracker — refreshed status

Generated 2026-10-15. Workbook `loom_production_execution_tracker.xlsx` Status column and
Release Gates refreshed from the post-merge re-score of this repository.

## Source and limits

- Source of task verdicts: `docs/reports/LOOM-PRODUCTION-TRACKER-RESCORE.md` — a task-by-task
  re-read of all 367 tracker rows against committed HEAD `c13f7ca2`, with the workbook's own
  acceptance text, a DONE/PARTIAL/NOT-DONE rubric and an independent symbol/test spot-check.
- Source of gate verdicts: `docs/reports/LOOM-G01-G26-release-gates-EXECUTION.md`.
- **Limits:** these are audit verdicts, not release sign-off. Desktop/Tauri, real-engine,
  licensing, updater and installer clauses remain capped because the shipped surface is a web
  Studio, not a desktop product. No physical-tool or signed-package result is claimed.

## Summary

| Milestone | Done | In Progress | Not Started | Total | Hours remaining |
|---|---:|---:|---:|---:|---:|
| M0 | 21 | 1 | 0 | 22 | 3 |
| M1 | 19 | 10 | 5 | 34 | 53 |
| M2 | 4 | 18 | 4 | 26 | 85 |
| M3 | 15 | 11 | 1 | 27 | 46 |
| M4 | 0 | 22 | 12 | 34 | 137 |
| M5 | 23 | 3 | 3 | 29 | 28 |
| M6 | 3 | 24 | 16 | 43 | 164 |
| M7 | 0 | 14 | 9 | 23 | 91 |
| M8 | 0 | 9 | 16 | 25 | 93 |
| M9 | 0 | 16 | 13 | 29 | 126 |
| M10 | 0 | 4 | 23 | 27 | 124 |
| M11 | 12 | 24 | 12 | 48 | 188 |
| **All** | **97** | **156** | **114** | **367** | **1138** |

## Release gates

| Gate | Requirement | Status |
|---|---|---|
| G01 | Contract integrity | In Progress |
| G02 | Migration safety | In Progress |
| G03 | Stable identity | In Progress |
| G04 | Single source of truth | Not Started |
| G05 | Editor safety | In Progress |
| G06 | Catalog truth | In Progress |
| G07 | Access correctness | In Progress |
| G08 | Physical honesty | In Progress |
| G09 | Workload honesty | In Progress |
| G10 | Backend refusal | In Progress |
| G11 | Mock isolation | In Progress |
| G12 | Run provenance | In Progress |
| G13 | Replay | Not Started |
| G14 | Crash recovery | In Progress |
| G15 | Offline core | In Progress |
| G16 | Target graph performance | In Progress |
| G17 | Matrix performance | Not Started |
| G18 | Trace performance | Not Started |
| G19 | Tauri boundary | Not Started |
| G20 | License behavior | Not Started |
| G21 | Update security | Not Started |
| G22 | Dependency security | In Progress |
| G23 | Clean install | Not Started |
| G24 | Documentation | In Progress |
| G25 | P0 closure | Not Started |
| G26 | E2E closure | In Progress |

## Pending — Not Started

### M1 — 5 tasks (0 × P0, 16 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M1-13 | P1 | 3 | Implement distribute tools |
| M1-14 | P2 | 3 | Add minimap and viewport indicator |
| M1-19 | P1 | 4 | Add edge crossing/overlap cleanup |
| M1-31 | P1 | 3 | Add topology search |
| M1-33 | P1 | 3 | Add context menus for node/edge/canvas |

### M2 — 4 tasks (2 × P0, 13 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M2-10 | P2 | 2 | Add favorites/recent IP |
| M2-18 | P0 | 4 | Implement protocol compatibility checks |
| M2-21 | P1 | 4 | Implement bulk-apply template |
| M2-24 | P0 | 3 | Validate catalog parameter ranges |

### M3 — 1 tasks (0 × P0, 4 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M3-23 | P1 | 4 | Build address map view |

### M4 — 12 tasks (1 × P0, 53 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M4-18 | P1 | 4 | Suggest pipeline stages from timing target |
| M4-19 | P0 | 3 | Apply suggested pipeline stages |
| M4-20 | P1 | 5 | Build simple routing-density congestion estimator |
| M4-21 | P1 | 3 | Add congestion heatmap overlay |
| M4-22 | P1 | 3 | Add pipeline-stage overlay |
| M4-23 | P1 | 3 | Add clock/power domain overlays |
| M4-25 | P1 | 6 | Import basic DEF placement |
| M4-26 | P1 | 5 | Export basic DEF placement |
| M4-27 | P1 | 5 | Create external physical-tool adapter interface |
| M4-28 | P1 | 9 | Add OpenROAD adapter prototype |
| M4-29 | P2 | 4 | Add KLayout inspection handoff |
| M4-33 | P2 | 3 | Export floorplan SVG |

### M5 — 3 tasks (0 × P0, 15 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M5-21 | P2 | 6 | Add simple topology-aware mapping heuristic |
| M5-22 | P1 | 4 | Add workload scenario variants |
| M5-23 | P2 | 5 | Add parameter sweep definition |

### M6 — 16 tasks (6 × P0, 65 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M6-03 | P0 | 5 | Implement sidecar spawn |
| M6-04 | P0 | 3 | Implement cancel/terminate |
| M6-06 | P0 | 4 | Capture structured stdout/stderr |
| M6-08 | P0 | 4 | Create run artifact directory |
| M6-13 | P1 | 8 | Add ASTRA/collective adapter path |
| M6-14 | P1 | 5 | Add generic external-engine adapter interface |
| M6-25 | P1 | 3 | Render buffer utilization metric |
| M6-26 | P1 | 4 | Render router power metric |
| M6-27 | P1 | 3 | Render hop-count distribution |
| M6-28 | P1 | 3 | Add traffic-class filter |
| M6-33 | P1 | 3 | Set baseline run |
| M6-35 | P1 | 5 | Add diff heatmap |
| M6-37 | P1 | 3 | Export selected metrics CSV |
| M6-41 | P1 | 3 | Handle disk/full write failure |
| M6-42 | P0 | 6 | Project→engine→trace→playback flow |
| M6-43 | P0 | 3 | Mock fallback truthfulness flow |

### M7 — 9 tasks (4 × P0, 38 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M7-04 | P1 | 5 | Add safe quick-fix framework |
| M7-07 | P1 | 3 | Link logs to run/object IDs |
| M7-12 | P0 | 5 | Implement replay run |
| M7-13 | P1 | 4 | Implement clone run as new scenario |
| M7-16 | P1 | 3 | Add deterministic mode indicator |
| M7-17 | P0 | 5 | Create support bundle exporter |
| M7-18 | P1 | 3 | Add copy diagnostics action |
| M7-22 | P0 | 5 | Create deterministic replay golden test |
| M7-23 | P0 | 5 | Problem→fix→rerun→compare flow |

### M8 — 16 tasks (4 × P0, 58 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M8-02 | P0 | 4 | Define project workspace layout |
| M8-05 | P1 | 3 | Implement Save As |
| M8-06 | P0 | 3 | Implement atomic write + temp rename |
| M8-08 | P0 | 4 | Implement crash-recovery prompt |
| M8-09 | P1 | 3 | Implement rolling backup retention |
| M8-10 | P1 | 5 | Detect external file changes |
| M8-11 | P1 | 3 | Add recent projects list |
| M8-12 | P2 | 2 | Support drag/drop project open |
| M8-15 | P1 | 3 | Implement PNG export command |
| M8-16 | P2 | 3 | Implement SVG export command |
| M8-17 | P1 | 5 | Implement SystemVerilog export hook |
| M8-18 | P1 | 5 | Create portable project bundle export |
| M8-19 | P1 | 5 | Create project bundle import |
| M8-20 | P1 | 3 | Build settings store |
| M8-21 | P1 | 3 | Add engine binary path override |
| M8-23 | P0 | 4 | Guarantee offline simulation when local engine exists |

### M9 — 13 tasks (5 × P0, 61 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M9-01 | P0 | 3 | Set measurable UI performance budgets |
| M9-03 | P0 | 6 | Virtualize I×T matrix |
| M9-04 | P1 | 8 | Use canvas/WebGL path for simulation heat when needed |
| M9-05 | P1 | 5 | Add graph spatial index |
| M9-07 | P0 | 6 | Window large trace playback |
| M9-08 | P1 | 4 | Add memory limits and eviction for trace cache |
| M9-10 | P0 | 4 | Benchmark 10k access cells |
| M9-11 | P0 | 5 | Benchmark large trace fixture |
| M9-14 | P2 | 4 | Add command palette |
| M9-15 | P1 | 5 | Add global object search |
| M9-21 | P1 | 5 | Add first-run onboarding |
| M9-27 | P1 | 3 | Validate high-DPI/4K scaling |
| M9-28 | P2 | 3 | Add glossary/help affordances |

### M10 — 23 tasks (13 × P0, 107 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M10-01 | P0 | 5 | Lock down Tauri command allowlist |
| M10-02 | P0 | 4 | Sanitize all filesystem paths |
| M10-03 | P0 | 4 | Remove shell-string command construction |
| M10-05 | P0 | 5 | Harden bundle extraction |
| M10-06 | P0 | 4 | Verify engine binary identity |
| M10-07 | P0 | 5 | Verify updater/package signatures |
| M10-08 | P0 | 3 | Default to no network dependency |
| M10-09 | P1 | 3 | Add explicit network/telemetry setting |
| M10-10 | P0 | 3 | Redact sensitive paths from support bundle |
| M10-11 | P0 | 6 | Implement signed node-lock license file |
| M10-12 | P0 | 4 | Build license state UI |
| M10-13 | P0 | 3 | Gate engine spawn only, not project recovery |
| M10-14 | P1 | 4 | Add offline grace policy hook |
| M10-15 | P2 | 4 | Define floating-license adapter interface |
| M10-16 | P1 | 4 | Implement update check |
| M10-17 | P1 | 6 | Implement signed update apply |
| M10-18 | P1 | 5 | Implement failed-update rollback path |
| M10-19 | P1 | 3 | Create release channel configuration |
| M10-20 | P0 | 6 | Build Linux installer/package |
| M10-21 | P1 | 8 | Build Windows installer |
| M10-22 | P2 | 9 | Build macOS signed/notarized package |
| M10-26 | P1 | 4 | Harden crash/log data retention |
| M10-27 | P0 | 5 | Offline licensed launch→run→update check flow |

### M11 — 12 tasks (5 × P0, 59 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M11-26 | P0 | 8 | Automate large project performance flow |
| M11-30 | P0 | 4 | Test permission denied/read-only project |
| M11-31 | P1 | 4 | Test disk-full/low-space behavior |
| M11-32 | P1 | 5 | Test updater failure/rollback |
| M11-36 | P0 | 5 | Performance budgets pass |
| M11-37 | P0 | 5 | Installer/clean-machine smoke passes |
| M11-39 | P1 | 5 | Write topology/catalog/agent guide |
| M11-40 | P1 | 5 | Write domains/access/firewall guide |
| M11-41 | P1 | 5 | Write floorplan guide |
| M11-43 | P1 | 4 | Write reproducibility/support guide |
| M11-47 | P1 | 3 | Create release notes/changelog |
| M11-48 | P0 | 6 | Create signed production candidate |


## Partial — In Progress

### M0 — 1 tasks (1 × P0, 3 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M0-22 | P0 | 3 | Define capability provenance states |

### M1 — 10 tasks (4 × P0, 37 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M1-12 | P1 | 3 | Implement alignment tools |
| M1-15 | P0 | 5 | Implement port-to-port link creation |
| M1-17 | P0 | 6 | Implement Manhattan edge routing |
| M1-18 | P1 | 5 | Implement editable waypoints |
| M1-21 | P1 | 3 | Implement Torus preset generator |
| M1-22 | P1 | 3 | Implement Ring preset generator |
| M1-24 | P1 | 3 | Implement Tree preset generator |
| M1-26 | P0 | 3 | Validator: dangling references |
| M1-30 | P0 | 3 | Validator: topology-specific constraints |
| M1-32 | P1 | 3 | Add keyboard shortcut layer |

### M2 — 18 tasks (13 × P0, 72 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M2-03 | P0 | 4 | Seed router/switch IP entries |
| M2-04 | P0 | 4 | Seed compute/NPU IP entries |
| M2-05 | P0 | 4 | Seed HBM/DDR memory-controller entries |
| M2-06 | P1 | 3 | Seed bridge/interconnect adapter entries |
| M2-07 | P1 | 3 | Seed generic peripheral/DMA entries |
| M2-08 | P0 | 4 | Implement catalog search/filter/tagging |
| M2-09 | P0 | 5 | Implement drag/stamp IP onto topology |
| M2-11 | P0 | 4 | Allow project-local catalog overrides |
| M2-12 | P1 | 4 | Import custom catalog JSON |
| M2-13 | P1 | 3 | Export custom catalog entries |
| M2-14 | P0 | 3 | Detect missing/outdated catalog references |
| M2-15 | P0 | 5 | Create agent inspector model |
| M2-16 | P0 | 5 | Implement per-port inspector |
| M2-19 | P0 | 4 | Implement address window editor |
| M2-20 | P1 | 3 | Implement clock/reset assignment |
| M2-22 | P0 | 5 | Build unified Node/Agent inspector UI |
| M2-23 | P0 | 5 | Build unified Edge inspector UI |
| M2-26 | P0 | 4 | Catalog→stamp→configure→save flow |

### M3 — 11 tasks (5 × P0, 42 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M3-06 | P0 | 4 | Edit per-VC depth and class |
| M3-07 | P1 | 3 | Add arbitration policy field |
| M3-09 | P1 | 3 | Add escape-VC configuration |
| M3-11 | P1 | 3 | Create reset-domain editor |
| M3-12 | P1 | 4 | Create power-domain editor |
| M3-13 | P0 | 4 | Detect CDC crossings |
| M3-14 | P1 | 4 | Detect power-domain crossings |
| M3-15 | P1 | 3 | Add domain overlay to topology |
| M3-16 | P0 | 6 | Build virtualized Initiator×Target matrix |
| M3-24 | P0 | 4 | Detect holes/overlaps and unmapped initiators |
| M3-27 | P0 | 4 | Access policy→path→firewall flow |

### M4 — 22 tasks (13 × P0, 84 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M4-01 | P0 | 4 | Create floorplan coordinate system and units |
| M4-02 | P0 | 3 | Create editable die outline |
| M4-03 | P0 | 5 | Render placed nodes as physical rectangles |
| M4-04 | P0 | 5 | Drag and resize physical instances |
| M4-05 | P1 | 3 | Add lock/fixed placement state |
| M4-06 | P1 | 3 | Add floorplan snap/grid controls |
| M4-07 | P1 | 3 | Add Anchor X/Y commands |
| M4-08 | P1 | 3 | Add alignment/distribution for physical instances |
| M4-09 | P0 | 4 | Add unplaced hierarchy/bin panel |
| M4-10 | P1 | 4 | Add keepout regions |
| M4-11 | P1 | 4 | Add placement groups/regions |
| M4-12 | P0 | 6 | Implement Route All Manhattan physical links |
| M4-13 | P1 | 5 | Allow manual physical edge waypoints |
| M4-14 | P1 | 3 | Add wire pitch/layer assumptions |
| M4-15 | P0 | 3 | Compute Manhattan wire length per edge |
| M4-16 | P0 | 5 | Add wire delay estimation model |
| M4-17 | P0 | 3 | Add per-edge timing constraint |
| M4-24 | P0 | 3 | Cross-probe topology↔floorplan selection |
| M4-30 | P0 | 4 | Validate floorplan overlaps/out-of-die placement |
| M4-31 | P0 | 3 | Validate physical routing completeness |
| M4-32 | P1 | 3 | Export floorplan PNG |
| M4-34 | P0 | 5 | Place→route→timing→pipeline flow |

### M5 — 3 tasks (2 × P0, 13 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M5-18 | P1 | 5 | Add automatic seat assignment |
| M5-26 | P0 | 3 | Mark unsupported workload/backend combinations |
| M5-29 | P0 | 5 | Workload→mapping→validated run-input flow |

### M6 — 24 tasks (20 × P0, 99 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M6-01 | P0 | 5 | Define loom-sim request/response protocol |
| M6-02 | P0 | 4 | Implement engine version/health handshake |
| M6-05 | P0 | 3 | Implement timeout handling |
| M6-07 | P0 | 5 | Create run state machine |
| M6-09 | P0 | 3 | Fingerprint run inputs |
| M6-10 | P0 | 5 | Implement explicit mock-trace mode |
| M6-11 | P0 | 5 | Create backend capability registry |
| M6-12 | P0 | 6 | Add BookSim adapter path |
| M6-15 | P0 | 6 | Implement streaming trace parser |
| M6-19 | P0 | 5 | Build timeline scrubber |
| M6-20 | P0 | 3 | Add play/pause/step controls |
| M6-21 | P0 | 3 | Show phase labels from workload.phases |
| M6-22 | P0 | 5 | Render edge utilization heat |
| M6-23 | P0 | 3 | Render stall metric |
| M6-24 | P1 | 3 | Render queue latency metric |
| M6-29 | P0 | 5 | Add node/edge metric inspector |
| M6-30 | P1 | 3 | Add Top-N congested list |
| M6-31 | P1 | 3 | Add metric legend and scale controls |
| M6-32 | P0 | 4 | Create run history list |
| M6-34 | P1 | 5 | Compare summary metrics |
| M6-36 | P0 | 4 | Compare workload/mapping/config inputs |
| M6-38 | P0 | 3 | Export raw trace/summary bundle |
| M6-39 | P0 | 4 | Handle engine crash |
| M6-40 | P0 | 4 | Handle truncated/corrupt trace |

### M7 — 14 tasks (10 × P0, 53 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M7-01 | P0 | 5 | Build global ProblemsPanel |
| M7-02 | P0 | 4 | Cross-probe issue to object/view |
| M7-03 | P1 | 3 | Add severity/code/source filters |
| M7-05 | P0 | 5 | Add validation run-all command |
| M7-06 | P0 | 4 | Build structured log viewer |
| M7-08 | P0 | 3 | Record UI and engine versions |
| M7-09 | P0 | 3 | Record project/workload fingerprints |
| M7-10 | P0 | 3 | Record backend command/config |
| M7-11 | P1 | 3 | Record random seed where applicable |
| M7-14 | P0 | 6 | Implement project semantic diff |
| M7-15 | P1 | 4 | Implement run manifest diff |
| M7-19 | P0 | 3 | Detect incompatible engine/UI versions |
| M7-20 | P0 | 3 | Detect stale run artifacts after project change |
| M7-21 | P1 | 4 | Add run artifact integrity check |

### M8 — 9 tasks (8 × P0, 35 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M8-01 | P0 | 5 | Create typed Tauri command surface |
| M8-03 | P0 | 4 | Implement Open Project |
| M8-04 | P0 | 4 | Implement Save |
| M8-07 | P0 | 4 | Implement autosave |
| M8-13 | P0 | 3 | Centralize export destination dialog |
| M8-14 | P0 | 3 | Implement CSV export command |
| M8-22 | P0 | 4 | Guarantee offline project editing |
| M8-24 | P2 | 3 | Persist selected project/view state safely |
| M8-25 | P0 | 5 | Crash→recover→save flow |

### M9 — 16 tasks (10 × P0, 65 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M9-02 | P0 | 5 | Virtualize node/agent table |
| M9-06 | P0 | 4 | Throttle/debounce expensive derived updates |
| M9-09 | P0 | 5 | Benchmark 256 nodes / 512 edges |
| M9-12 | P0 | 5 | Create consistent app shell/navigation |
| M9-13 | P1 | 4 | Create consistent inspector pattern |
| M9-16 | P0 | 3 | Add empty states |
| M9-17 | P0 | 4 | Add loading/progress states |
| M9-18 | P0 | 4 | Add failure states with recovery actions |
| M9-19 | P1 | 4 | Add light theme polish |
| M9-20 | P2 | 3 | Add dark theme parity |
| M9-22 | P0 | 4 | Ship sample projects |
| M9-23 | P1 | 5 | Keyboard-navigate core views |
| M9-24 | P1 | 4 | Audit color contrast and non-color cues |
| M9-25 | P1 | 3 | Add accessible labels/tooltips |
| M9-26 | P0 | 3 | Validate 1366×768 layout |
| M9-29 | P0 | 5 | Large-project interactive flow |

### M10 — 4 tasks (3 × P0, 17 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M10-04 | P0 | 4 | Validate imported JSON sizes/depth |
| M10-23 | P1 | 4 | Generate SBOM |
| M10-24 | P0 | 4 | Generate third-party license notices |
| M10-25 | P0 | 5 | Run dependency vulnerability audit |

### M11 — 24 tasks (24 × P0, 129 h)

| ID | P | hrs | Task |
|---|---|---:|---|
| M11-06 | P0 | 5 | Catalog/agent validator tests |
| M11-12 | P0 | 5 | Run manager state-machine tests |
| M11-13 | P0 | 6 | Save/load/autosave/recovery integration |
| M11-14 | P0 | 6 | Engine handshake/spawn integration |
| M11-15 | P0 | 6 | Backend capability/refusal integration |
| M11-16 | P0 | 6 | Run artifact/provenance integration |
| M11-18 | P0 | 6 | Automate catalog→agents→domains flow |
| M11-19 | P0 | 6 | Automate access/firewall flow |
| M11-20 | P0 | 6 | Automate floorplan flow |
| M11-21 | P0 | 6 | Automate workload/mapping flow |
| M11-22 | P0 | 8 | Automate real simulation playback flow |
| M11-23 | P0 | 5 | Automate mock truthfulness flow |
| M11-24 | P0 | 5 | Automate ProblemsPanel recovery flow |
| M11-25 | P0 | 5 | Automate crash recovery flow |
| M11-27 | P0 | 4 | Test engine missing/incompatible |
| M11-28 | P0 | 4 | Test corrupt project/catalog input |
| M11-29 | P0 | 4 | Test corrupt/truncated trace |
| M11-33 | P0 | 5 | Zero unlabeled mock/estimate outputs |
| M11-34 | P0 | 5 | Zero P0 validation bypasses |
| M11-35 | P0 | 5 | No critical/high security findings |
| M11-38 | P0 | 5 | Write user quickstart |
| M11-42 | P0 | 5 | Write workload/simulation guide |
| M11-44 | P0 | 6 | Write schema and engine protocol reference |
| M11-45 | P0 | 5 | Write troubleshooting guide |

