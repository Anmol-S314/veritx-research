# Loom finish baseline reconciliation

## Scope and source identity

This is a baseline/reconciliation record, not a claim that all tracker work is complete. Workbook and durable-runner extracts were read-only. `openpyxl` read-only comparison found exact equality for all columns: **367 tasks**, **24 flows**, **26 gates**. Workbook SHA-256: `e4cb6188531acd7f0362074eba2dcd98c2610b013548c3b8bbff1c4c35251fc6`. Extract SHA-256: tasks `3f1c7e51213e90e97bdfe4e70181c0487c8d4242f9d072de1c72013f136a3eba`; flows `732da0a4259beaa5aae9ef8e36f5ac367ee4065b4bf9f2312bc2260a7e39ac3a`; gates `da41f85674f4054f415bf576e49f51797551cb055a5c39b75b5f5ffe5ba20922`.

Integration source: `41ca430f85f4b1fd99771b3050eb9f5644d1c5e4`, branch `work/loom-finish-luna-20261015`. Source workbook status is unchanged (`Not Started` for all tasks/gates); execution evidence is separate and does not overwrite it.

## Complete task-ID ledger and ownership

Every task ID is accounted for below, in workbook order, with priority counts P0/P1/P2. Exact acceptance text, priority and dependencies remain in the source tracker/extract and scoped reports. This compact ledger avoids duplicating 367 criteria and does not convert partial evidence into completion.

| Milestone | Count | P0 / P1 / P2 | Exact task IDs |
|---|---:|---:|---|
| M0 | 22 | 22 / 0 / 0 | `M0-01, M0-02, M0-03, M0-04, M0-05, M0-06, M0-07, M0-08, M0-09, M0-10, M0-11, M0-12, M0-13, M0-14, M0-15, M0-16, M0-17, M0-18, M0-19, M0-20, M0-21, M0-22` | M0–M2 report |
| M1 | 34 | 18 / 15 / 1 | `M1-01, M1-02, M1-03, M1-04, M1-05, M1-06, M1-07, M1-08, M1-09, M1-10, M1-11, M1-12, M1-13, M1-14, M1-15, M1-16, M1-17, M1-18, M1-19, M1-20, M1-21, M1-22, M1-23, M1-24, M1-25, M1-26, M1-27, M1-28, M1-29, M1-30, M1-31, M1-32, M1-33, M1-34` |
| M2 | 26 | 18 / 7 / 1 | `M2-01, M2-02, M2-03, M2-04, M2-05, M2-06, M2-07, M2-08, M2-09, M2-10, M2-11, M2-12, M2-13, M2-14, M2-15, M2-16, M2-17, M2-18, M2-19, M2-20, M2-21, M2-22, M2-23, M2-24, M2-25, M2-26` |
| M3 | 27 | 16 / 11 / 0 | `M3-01, M3-02, M3-03, M3-04, M3-05, M3-06, M3-07, M3-08, M3-09, M3-10, M3-11, M3-12, M3-13, M3-14, M3-15, M3-16, M3-17, M3-18, M3-19, M3-20, M3-21, M3-22, M3-23, M3-24, M3-25, M3-26, M3-27` |
| M4 | 34 | 14 / 18 / 2 | `M4-01, M4-02, M4-03, M4-04, M4-05, M4-06, M4-07, M4-08, M4-09, M4-10, M4-11, M4-12, M4-13, M4-14, M4-15, M4-16, M4-17, M4-18, M4-19, M4-20, M4-21, M4-22, M4-23, M4-24, M4-25, M4-26, M4-27, M4-28, M4-29, M4-30, M4-31, M4-32, M4-33, M4-34` |
| M5 | 29 | 15 / 12 / 2 | `M5-01, M5-02, M5-03, M5-04, M5-05, M5-06, M5-07, M5-08, M5-09, M5-10, M5-11, M5-12, M5-13, M5-14, M5-15, M5-16, M5-17, M5-18, M5-19, M5-20, M5-21, M5-22, M5-23, M5-24, M5-25, M5-26, M5-27, M5-28, M5-29` |
| M6 | 43 | 29 / 14 / 0 | `M6-01, M6-02, M6-03, M6-04, M6-05, M6-06, M6-07, M6-08, M6-09, M6-10, M6-11, M6-12, M6-13, M6-14, M6-15, M6-16, M6-17, M6-18, M6-19, M6-20, M6-21, M6-22, M6-23, M6-24, M6-25, M6-26, M6-27, M6-28, M6-29, M6-30, M6-31, M6-32, M6-33, M6-34, M6-35, M6-36, M6-37, M6-38, M6-39, M6-40, M6-41, M6-42, M6-43` |
| M7 | 23 | 14 / 9 / 0 | `M7-01, M7-02, M7-03, M7-04, M7-05, M7-06, M7-07, M7-08, M7-09, M7-10, M7-11, M7-12, M7-13, M7-14, M7-15, M7-16, M7-17, M7-18, M7-19, M7-20, M7-21, M7-22, M7-23` |
| M8 | 25 | 12 / 10 / 3 | `M8-01, M8-02, M8-03, M8-04, M8-05, M8-06, M8-07, M8-08, M8-09, M8-10, M8-11, M8-12, M8-13, M8-14, M8-15, M8-16, M8-17, M8-18, M8-19, M8-20, M8-21, M8-22, M8-23, M8-24, M8-25` |
| M9 | 29 | 15 / 11 / 3 | `M9-01, M9-02, M9-03, M9-04, M9-05, M9-06, M9-07, M9-08, M9-09, M9-10, M9-11, M9-12, M9-13, M9-14, M9-15, M9-16, M9-17, M9-18, M9-19, M9-20, M9-21, M9-22, M9-23, M9-24, M9-25, M9-26, M9-27, M9-28, M9-29` |
| M10 | 27 | 16 / 9 / 2 | `M10-01, M10-02, M10-03, M10-04, M10-05, M10-06, M10-07, M10-08, M10-09, M10-10, M10-11, M10-12, M10-13, M10-14, M10-15, M10-16, M10-17, M10-18, M10-19, M10-20, M10-21, M10-22, M10-23, M10-24, M10-25, M10-26, M10-27` |
| M11 | 48 | 41 / 7 / 0 | `M11-01, M11-02, M11-03, M11-04, M11-05, M11-06, M11-07, M11-08, M11-09, M11-10, M11-11, M11-12, M11-13, M11-14, M11-15, M11-16, M11-17, M11-18, M11-19, M11-20, M11-21, M11-22, M11-23, M11-24, M11-25, M11-26, M11-27, M11-28, M11-29, M11-30, M11-31, M11-32, M11-33, M11-34, M11-35, M11-36, M11-37, M11-38, M11-39, M11-40, M11-41, M11-42, M11-43, M11-44, M11-45, M11-46, M11-47, M11-48` |

Owner map: M0–M2 → `LOOM-M0-M2-remaining-tasks-EXECUTION.md`; M3–M5 → `LOOM-M3-M5-remaining-tasks-EXECUTION.md`; M6–M8 → `LOOM-M6-M8-remaining-tasks-EXECUTION.md`; M9–M11 → `LOOM-M9-M11-remaining-tasks-EXECUTION.md`; F01–F24 → `LOOM-F01-F24-end-to-end-acceptance-flows-EXECUTION.md`; G01–G26 → `LOOM-G01-G26-release-gates-EXECUTION.md`. Those reports retain tracker criteria, dependencies and acceptance evidence/limitations. This integration lane reconciles patches; it does not independently certify every reported criterion.

### Evidence disposition

- **Existing bounded implementation evidence:** scoped reports describe schema/migration/serialization, graph editing/history, catalog contracts, access/domain/floorplan/workload support, trace parsing/playback and provenance helpers. The reports' ID-level Done/Partial labels retain their stated bounds; none changes workbook status.
- **Missing proof remains open:** all-view canonical store/selectors; full catalog stamping; supported real-backend run/provenance; complete access-to-routing; real physical implementation/signoff; desktop/Tauri/native recovery; licensed/offline behavior; signed packages/clean OS installs; hardware qualification; broad performance budgets.
- All 24 flows and 26 gates are separately accounted for in their reports. Passing a slice or a non-claim/blocker probe is not full acceptance. Web behavior is not desktop, real-engine, physical-tool or mock-equivalent acceptance.

## Snapshot reconciliation

All six sibling worktrees were inspected read-only at base `41ca430f85f4b1fd99771b3050eb9f5644d1c5e4`. Snapshot capture read each candidate file twice and verified identical SHA-256 before writing under `/tmp/loom-snapshots`; no concurrent-byte changes were detected. Snapshot manifest hashes:

- m0–m2 `pi-worktree-18784daf…`: `4a0f0e77ee7e19dd1f2da65fc69647be77b32cea36cdc8984c53985fa9c20b83` (10 files)
- m3–m5 `pi-worktree-192ae634…`: `4f809d1b723ca87219fae1e70ee8d190cc0c656bf0a16048a12b942976fbbec4` (6 files)
- m6–m8 `pi-worktree-f3136ef6…`: `7d7bf39dfe467b82943f87e30dd2443bbf8e13e76ee7fa4550b8122bd40e8d2d` (9 files)
- m9–m11 `pi-worktree-51f486e8…`: `4e1a9e8d7ab4f67b466ec767bd35183ef823ca6a6e9468b597878f161b2b8fd1` (23 files)
- gates `pi-worktree-80659710…`: `cfad50d689085482778c7135aca8582a10936c6693c88f5d45da43bd7f9f217a` (1 file)
- E2E `pi-worktree-e0bd1179…`: `f1f53782146e34885a80d36636ef3540225f802b7da1b2d58eba4454707340f7` (2 files)

Captured patches/tests/docs were applied into this workspace. Overlapping project/test/trace changes applied cleanly via three-way patch application and were validated below. Excluded sibling dependencies/build output, credentials, runtime databases/logs/state, runner code/config, durable database, and material outside `apps/studio`, `contracts/loom`, `docs`. No sibling worktree was modified. `/tmp` snapshot artifacts are not deliverables.

## Reconciled implementation and validation

Integrated changes include catalog v1 structure/search/serialization and validation; stricter graph/agent/address validation and fail-closed adapter checks; floorplan/authoring refinements; semantic project diff; trace parsing/playback regression fixes; run history panel; migration fixture/idempotence/sample checks; browser acceptance changes; scoped reports and docs. These do not imply unsupported execution-domain acceptance.

- `cd apps/studio && npm ci --ignore-scripts --no-audit --no-fund` — passed, 155 packages; Node 22.22.1 engine warnings for packages requiring 22.22.2+.
- `cd apps/studio && npm run build` — passed TypeScript/Vite; main JS ~1.25 MB triggers Vite's >500 kB advisory.
- `cd apps/studio && TMPDIR=/tmp npx vitest run --pool=threads --maxWorkers=1` — **58 files, 572 tests passed**, including MockPlayback contracts. Previously reported MockPlayback full-suite failure did not reproduce after reconciliation; no test was weakened or deleted.
- `python3 -m pytest apps/studio/tests/test_loom_p0_browser_acceptance.py -q --basetemp=/tmp/pytest-loom-finish-baseline` — **23 skipped** because browser acceptance is opt-in; no browser flow acceptance is claimed.
- `git diff --check` — passed after removing inherited trailing whitespace in gate report.

Residual risks: Node engine warning, bundle-size warning, opt-in browser suite skipped, and external acceptance dependencies listed above. No product task is marked Done by build/suite success alone.

## Clean baseline handoff

Reconciled source/tests/reports will be committed only to this workspace branch. Final commit/ref and clean-state check are recorded in `loom-finish-reconciliation.md`. This clean baseline is allocation-ready for subsequent scoped work, not release-ready and not completion of the 367 tasks.
