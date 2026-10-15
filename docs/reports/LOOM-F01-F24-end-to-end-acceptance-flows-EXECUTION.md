# Loom F01–F24 end-to-end acceptance execution

**Scope:** tracker flows F01–F24 only, plus the 21 exact tracker tasks in the `E2E` and `E2E Tests` areas that implement/automate these flows. No implementation claims for other task IDs; no release gate status changes.

**Checkout:** isolated integration-base worktree at `/home/datavex/.cache/worktrees/veritx-loom-integration-20261015/pi-worktree-e0bd1179-4859-4abc-aee2-70e7711856e2-s0-0`; initial HEAD `41ca430f` (`Add Loom browser acceptance evidence`). At audit start `git status --short --branch` showed a clean worktree on the assigned isolated subagent branch. This is a web Studio checkout, not a Tauri desktop distribution.

**Tracker source:** `/home/datavex/Downloads/loom_production_execution_tracker.xlsx`, cross-checked with `/home/datavex/.cache/loom-durable-runner/{tasks,flows,gates}.json`. Workbook has 367 master tasks, 24 E2E flows, 26 release gates. Flow IDs and task IDs below are copied without renaming. No source tracker status was edited.

## Scope task ledger

The 21 in-scope exact task IDs and tracker acceptance conditions are listed below. Status is **Evidence partial** unless explicitly noted; a passing slice is not acceptance of the complete task. Dependencies are tracker-declared and have not been changed by this lane.

| ID | Exact task | Acceptance / Done When (tracker) | Dependency / disposition |
|---|---|---|---|
| M1-34 | Topology edit/save/reload flow | Start from 8x8 preset, add a node, wire it, change an edge, save/reload and verify semantic equality. | M1-15,M1-20,M0-21; F01 web graph path passes; dependencies remain open. |
| M2-26 | Catalog→stamp→configure→save flow | Stamp HBM and compute IP, edit ports/widths/domains, validate and save/reload with catalog provenance intact. | M2-09,M2-22,M2-24; API HBM partial only; no catalog UI or compute-IP provenance. |
| M3-27 | Access policy→path→firewall flow | Choose an initiator/target pair, set RW, inspect route/VC, save, reload and see identical rule/path semantics. | M3-20,M3-22,M3-25; route and local policy evidence do not join/evaluate. |
| M4-34 | Place→route→timing→pipeline flow | Place a custom graph, route all links, inspect congestion, apply one pipeline suggestion and save/reload identical physical state. | M4-19,M4-21,M4-30; no qualifying physical artifacts. |
| M5-29 | Workload→mapping→validated run-input flow | Create workload, edit phases, map ranks, resolve validation and produce deterministic run input without hidden cycles. | M5-09,M5-16,M5-26; phase capacity and MoE lowering partial, no rank mapping/run-input. |
| M6-42 | Project→engine→trace→playback flow | Validated project launches a real supported backend, produces trace/summary, plays back stalls/utilization and preserves provenance. | M6-12,M6-15,M6-22; no supported producer qualification or run evidence. |
| M6-43 | Mock fallback truthfulness flow | With engine unavailable, mock run works only after explicit user choice and every metric remains visibly Mocked. | M6-10,M6-02; labeled local mock playback is not a mock run/provenance loop. |
| M7-23 | Problem→fix→rerun→compare flow | Introduce an invalid rule, locate it in ProblemsPanel, fix it, rerun and compare to baseline with full provenance. | M7-02,M7-05,M6-34; issue/fix/compile partial, no simulation rerun/fingerprint comparison. |
| M8-25 | Crash→recover→save flow | Edit project, simulate abrupt shutdown, relaunch, recover autosave, validate and save without data loss. | M8-07,M8-08,M8-04; browser-profile persistence only; no abrupt desktop recovery. |
| M9-29 | Large-project interactive flow | Open target-size graph, edit nodes, access matrix, floorplan and trace playback without violating performance budgets. | M9-09,M9-10,M9-11; graph partial, budget/matrix/floorplan/trace qualification absent. |
| M10-27 | Offline licensed launch→run→update check flow | App launches offline, opens project, validates license, runs local engine and handles optional update check without blocking work. | M10-12,M10-13,M8-23,M10-16; requires licensed desktop/local engine. |
| M11-17 | Automate create→edit→save→reopen flow | UI E2E covers topology edit, inspector edit, validation and persistence. | M1-34,M2-26; F01 browser automation passes for web graph only; catalog dependency remains open. |
| M11-18 | Automate catalog→agents→domains flow | UI E2E stamps IP, edits agent ports/domains and resolves validation. | M2-26,M3-13; generic/API slices only; no UI stamp or crossing resolution proof. |
| M11-19 | Automate access/firewall flow | UI E2E edits matrix, inspects path/rule and verifies save/reload. | M3-27; route and authored rule evidence partial, no evaluation/conflict semantics. |
| M11-20 | Automate floorplan flow | UI E2E places nodes, routes links, checks timing/congestion and exports image. | M4-34; blocked by physical evidence and native file export requirements. |
| M11-21 | Automate workload/mapping flow | UI E2E creates workload, phases, mapping and validated run input. | M5-29; partial workload evidence only. |
| M11-22 | Automate real simulation playback flow | Supported backend run completes and UI scrubs utilization/stalls with provenance. | M6-42; no supported producer run evidence. |
| M11-23 | Automate mock truthfulness flow | Mock fallback cannot be mistaken for measured/simulated backend data. | M6-43; playback is visibly labeled MOCK, but no explicitly selected mock run/result. |
| M11-24 | Automate ProblemsPanel recovery flow | Injected config fault is found, navigated, fixed, rerun and disappears. | M7-23; compile-time issue/fix/recompile partial; no run/fingerprint. |
| M11-25 | Automate crash recovery flow | Unsaved changes survive forced termination through autosave restore. | M8-25; browser localStorage/profile restart is not forced process termination. |
| M11-26 | Automate large project performance flow | Target-size graph/matrix/trace meets budgets under automated instrumentation. | M9-29; 256/512 probe is not a budget assertion; other surfaces not qualified. |

**Task status policy:** tracker status for all remains as supplied (`Not Started` at downloaded tracker baseline). This report records evidence but does not treat E2E observations as task completion where criteria/dependencies remain unmet.

## F01–F24 acceptance matrix

| Flow | User goal / tracker pass-condition summary | Current disposition and evidence boundary |
|---|---|---|
| F01 | New project → 8×8 mesh → edit/connect/validate/save/reopen; semantic equality, Custom, no dangling refs. | **Web slice passes.** Latest exact command `VERITX_LOOM_E2E=1 python -m pytest -q apps/studio/tests/test_loom_p0_browser_acceptance.py::test_f01_mesh_edit_validate_export_reopen_is_semantically_stable` — **1 passed in 11.00s**. Real browser/gateway exercised mesh preset, node and edge edits, validation, JSON export/reimport and semantic equality. Does not prove Tauri persistence; M1-34 declared predecessors remain open. |
| F02 | IP catalog to configured agent; persisted provenance, valid ports/domains/addressing, inspector cross-probe. | **Partial.** Focused rerun of `test_f02_hbm3e_gateway_stamp_persists_provenance_and_address_intent` passed in 15.81s: gateway HBM3E stamp persists template/version/instance, dimensions, domain/address/access intent and inspector attachment; unknown/stale requests refuse without mutating. This is direct gateway API, not catalog UI. No catalog search/stamp UI, compute-IP stamp, full per-IP editing, or UI provenance/replacement. |

| F03 | Routing/VC configuration; valid hop/VC sequence, invalid combinations blocked. | **Partial.** Prior browser evidence reports a canonical terminating route and route-class↔VC resource cross-probe; hop records have no per-hop VC. Unsupported non-default VC is refused before writes in a separate probe. No policy combination matrix/full sequence. |
| F04 | Clock/power crossings visible before fix and clear only after valid policy/bridge. | **Partial.** Focused `test_f04_domain_assignments_persist_but_crossing_needs_attachment` passed in 20.65s after updating the test to current exact empty-state text; `test_f04_certified_attachment_derives_clock_domain_crossings` passed in 36.83s. The V5 crossing/census separation probe also passes in the final 23-test suite. Domain labels and attachment-derived channel boundaries render, but no mitigation is joined to channels or before/after clearing proof. |

| F05 | Deny-default + one RW path, matching rule/path, save/reopen, conflict/shadow report. | **Partial.** Focused test passed in 23.28s after correcting the expected UI cell name to `DENY`. It observes canonical route and local deny-default/RW intent persistence, explicitly not measured permission evaluation. No rule/path join or conflict/shadow evaluation. |

| F06 | Topology to physical floorplan; every edge physical route or unresolved; cross-probe. | **Blocked/partial.** Prior browser probe compiled logical graph and correctly showed no placement/certified physical layout. Current suite’s test was among browser crashes. No physical placement, complete routes, congestion, timing or cross-probe. |
| F07 | Timing suggestion accepted into canonical edge pipeline stages and feeds later run with provenance. | **Partial.** F01 exports/reimports pipeline stage field semantically. Compiler adapter refuses pipelineStages before server writes (truthful blocker); no timing model/provenance/run consumption. |
| F08 | External physical-tool handoff imports versioned external placement/congestion/timing and warns unsupported. | **Blocked.** Focused capability-registry probe passed in 9.95s and labels physical signoff NOT_IMPLEMENTED with missing physical inputs/tools. No adapter or external evidence. |

| F09 | Dense workload to stable-ID rank mapping; capacity checked; no hardcoded phase cycles. | **Partial.** Focused test passed in 12.05s after updating current `Load dense example` and validation copy selectors. It exercises 128-rank capacity warning against 64 nodes, persistence across reload and resolution to two valid phases. No completed stable-ID assignment or deterministic run-input. |

| F10 | MoE mapping with explicit dispatch/collective semantics and refusal for unsupported cases. | **Partial.** Focused browser/gateway lowering test passed in 18.38s; Qwen MoE evidence covers lowering/collectives but ranks are not mapped and traffic labels remain DEFAULT. |

| F11 | Supported real backend run → trace/summary → playback/provenance/real IDs. | **Blocked/not demonstrated.** No pinned/qualified supported simulation producer completion, trace and playback evidence established for this integration checkout. A browser page is not engine qualification. |
| F12 | Engine unavailable, explicit mock choice, editable project, every result visibly Mocked. | **Partial.** Existing test probes visibly labeled local MOCK playback and editable graph while preserving “No run”; explicit mock backend/run record/result provenance absent. |
| F13 | Two compatible runs compared, metric/config diffs separated, incompatible metrics excluded. | **Not demonstrated.** Current full test fails due browser crash before assertions; earlier no-run probe evidence is not available in this integration run. No compatible completed run pair or comparison output. |
| F14 | Problem navigation/fix/validation/rerun bound to new project fingerprint. | **Partial.** Existing browser case exercises unsupported RCU finding → Fabric remediation → finding gone → successful compile; no simulation rerun or fingerprint comparison. |
| F15 | Historical replay uses stored inputs; environment/version mismatch reported before run. | **Not demonstrated.** Current browser test failed due page crash. No historical run evidence. |
| F16 | Abrupt-termination recovery restores latest autosave without silent source overwrite. | **Partial.** Focused browser profile test passed in 16.47s and checks localStorage restore/source file immutability, not abrupt native termination. |

| F17 | Portable support bundle with declared hashed/redacted artifacts and workspace-bounded import. | **Not demonstrated.** Latest full suite passes the no-failed-run guard: no export is offered/requested absent a failed run. No failed-run bundle manifest, hashes/redaction or bounded re-import tested. |
| F18 | 256 nodes/512 edges, 10k access matrix, search/edit within performance budgets. | **Partial.** Focused test passed in 16.81s after fixing the fixture to the required `compilerSemanticsVersion: 1`: it loaded 256 nodes/512 edges, validated and edited a node. The test observes the I×T authoring cap at 24×24 (552 directional cells), not the required 10k; no budget assertion/trace/floorplan qualification. |

| F19 | Licensed core workflow offline including local engine. | **Blocked.** No offline licensed desktop/local-engine test evidence. |
| F20 | Clean-machine production install/run/export/uninstall with signed artifact. | **Blocked.** This checkout is a web Studio; no signed production installers or clean-machine test. |
| F21 | Deterministic old-project migration preview/diff/save-as-current without source mutation/data loss. | **Partial.** Earlier test shows canonical V4→V5 helper deterministic output, gateway save/reload preserving migration provenance and fixture immutability. Migration is not user-triggered in Studio; no preview/diff/save-as-current imported-project flow. |
| F22 | Truncated trace exact corruption location/recovery; never marked complete. | **Partial.** Replaced an obsolete “no trace import” probe (the current UI does expose a local JSONL importer) with a real corrupt-file test. Focused `test_f22_truncated_trace_reports_exact_line_and_keeps_valid_prefix` passed (initial 23.98s, final recheck 17.08s): two-line file has valid frame then malformed JSON; UI reports `trace line 2: invalid JSON`, retains the valid frame, offers mock fallback, keeps “No run on this project,” and makes no backend upload. No portable support-bundle export/recovery workflow, so F22 remains incomplete. |

| F23 | Missing/outdated catalog item inspectable, provenance preserved, explicit replacement. | **Partial.** Earlier API probe refused unknown template ID without mutating saved draft; no UI missing-item/provenance/replacement flow. |
| F24 | Failed signed update rolls back to launchable prior version with data preserved. | **Blocked.** No signed desktop update, failure injection, rollback, or prior-version launch evidence. |

No F01–F24 flow is claimed fully Done. F01 is a verified web acceptance slice only.

## Related release-gate crosswalk (evidence only; no gate changes)

The source tracker contains 26 gates; all are `Not Started` in the downloaded extract. This lane does not modify gate status. Scope-relevant gates and limitations:

| Gate | Tracker requirement | Evidence / remaining gap |
|---|---|---|
| G06 | Catalog truth | Gateway stamp API probe preserves HBM identity; no UI catalog stamping/provenance or compute item. Not passed. |
| G07 | Access correctness | F05 path + local firewall intent; no evaluated permission artifact/conflict report. Not passed. |
| G08 | Physical honesty | F06/F08 show placement/signoff unavailable rather than fabricating it; no physical results. Not passed. |
| G09 | Workload honesty | F09 checks capacity; F10 observes real lowering; no validated rank mapping/run input. Not passed. |
| G10 | Backend refusal | Pipeline/VC unsupported edits refuse before writes; complete unsupported combination matrix absent. Not passed. |
| G11 | Mock isolation | MOCK playback label and editable project observed; no explicit mock run result. Not passed. |
| G12/G13 | Run provenance / replay | No qualified real run or stored-input replay. Not passed. |
| G14 | Crash recovery | Browser profile persistence/source immutability only; no forced termination/native recovery. Not passed. |
| G16/G17/G18 | Graph / matrix / trace performance | 256/512 graph interaction observed but not budget-qualified; matrix capped at 24×24; no large-trace performance evidence. Not passed. |
| G19/G20/G21/G23 | Tauri boundary / licensing / update security / clean install | No Tauri native boundary, license, updater rollback or signed clean-machine evidence. Not passed. |
| G26 | E2E closure | 23 browser tests pass; multiple tracker acceptance conditions remain partial/blocked. Not passed. |

## Integration-base audit and execution evidence

- Initial `git status --short --branch`: clean (`## pi-subagents/e2e-e0bd117-efcb-s0-t0`). Initial HEAD `41ca430f Add Loom browser acceptance evidence`.
- Inspected `apps/studio/package.json`, `apps/studio/src/App.tsx`, fixture/browser tests and tracker JSON. Product is Vite/React web Studio; no Tauri desktop boundary or packaging artifacts were present in the inspected checkout. Avoided changes to product source or other runner reports.
- Blocker availability check: `command -v BookSim`, `booksim`, `openroad`, and `klayout` each returned unavailable; `VERITX_BOOKSIM_BIN`, `VERITX_LIVE_FEDERATION`, and `VERITX_E2E` were unset. This is environment evidence, not a claim that no supported engine exists elsewhere.
- `cd apps/studio && npm ci` — passed, 155 packages installed, 0 audit findings. Runtime is Node v22.22.1 while several dependencies request v22.22.2+ (EBADENGINE warnings).
- `cd apps/studio && npm run build` — passed (`tsc --noEmit`, Vite production build; 210 modules). Vite emitted existing >500kB main-chunk advisory.
- `python -m pytest -q apps/studio/tests/test_loom_p0_browser_acceptance.py` — **23 skipped** because the E2E suite is intentionally opt-in (`VERITX_LOOM_E2E=1`).
- Initial full browser audit: `VERITX_LOOM_E2E=1 python -m pytest -q apps/studio/tests/test_loom_p0_browser_acceptance.py` — **9 passed, 14 failed in 310.98s**. Failures included Chromium page crashes after cumulative launches and stale selectors/fixtures. Retained as the exact initial diagnostic result; later focused tests corrected some authoring defects and validated probes independently.
- Latest full integration-base reruns after test-only corrections: `VERITX_LOOM_E2E=1 python -m pytest -q apps/studio/tests/test_loom_p0_browser_acceptance.py` — **23 passed in 140.57s**, then after final F22 assertions **23 passed in 191.98s**. The entire current browser acceptance/blocker-probe file passes with the actual Studio and isolated gateway. This covers only the behavior asserted by these tests, not full tracker flow closure.
- Focused reruns after correcting tests (all opt-in commands ran against real Studio + isolated gateway): F01 **1 passed / 11.00s**; F02 HBM3E stamp/API cross-probe **1 / 15.81s**; F04 no-attachment domain intent **1 / 20.65s**, certified channel crossing census **1 / 36.83s**; F05 route/firewall intent **1 / 23.28s**; F06 no-placement blocker **1 / 15.54s**; F08 physical capability blocker **1 / 9.95s**; F09 phase capacity/fix **1 / 12.05s**; F10 MoE lowering partial **1 / 18.38s**; F12 mock labeling partial **1 / 15.98s**; F13 no-run compare guard **1 / 19.40s**; F14 issue/fix/recompile **1 / 21.23s**; F15 no-history replay guard **1 / 12.40s**; F16 browser-profile recovery partial **1 / 16.47s**; F17 no-failed-run bundle guard **1 / 14.19s**; F18 256/512 graph interaction partial **1 / 16.81s**; F22 corrupt trace exact line/valid-prefix partial **1 / 23.98s**. F22 was materially upgraded: current UI imports user-provided JSONL locally and correctly exposes parser failure/provenance; it has no support-bundle completion.
- Test-only corrections in this lane: F05 expected current `DENY` cell label; F04 expected current “No clock-domain crossings to derive” copy; F09 current “Load dense example” control and ✓ validation message; F13 scoped run comparison request capture to actual `/api/v1/compare?` (avoids matching bundled module URLs) and scoped the selects to their `.loom-field`; F18 generated project now supplies required compiler semantics version; F22 now exercises the trace parser instead of incorrectly asserting there is no import input. No product source changed.
- Focused F13 initial attempt failed due an ambiguous `get_by_label("run a")` and broad `"/compare"` request filter matching `/src/pages/loom/compareInputs.ts`; corrected selectors then passed. Focused F22 initial attempt failed because it incorrectly assumed no file input; code inspection found `Import trace JSONL` and we replaced the test with corruption recovery evidence as above.
- One initial build command was run from repository root and failed with npm `ENOENT package.json`; rerun from `apps/studio` passed. This was command cwd only, not a product failure.

## Blockers and remaining work

1. Keep E2E statuses partial until exact flow pass conditions hold; no tracker status mutation is made here. Latest 23/23 test success is reported as browser evidence, not all-flow completion.
2. E2E flows depending on physical placement, external physical-tool results, simulation producers, licensing, Tauri lifecycle and signed packaging cannot be closed by web-only browser evidence.
3. F01 is a verified web graph-file slice. F22 local corrupt-trace parsing is a verified partial; support-bundle recovery is still absent. The rest are partial, blocked, or unverified per the matrix.
4. No claims of desktop/physical/engine/signing acceptance, measured metrics, or release-gate passage.
