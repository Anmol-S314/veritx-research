# Battery baseline — the differential set M1 must not grow

Status: **M0.5 COMPLETE.** Hermetic repository, classified failures,
reproducible node sets, clean-checkout equivalence proven.

This is the honest state of the DSE battery in the active consolidation worktree
(`/home/datavex/veritx-audit`).

## Current run

| | |
|---|---|
| commit | `1bab6dba` (M0.5d) |
| command | `cd tracks/t3-topology/dse && python3 -m pytest tests -q --tb=no -p no:cacheprovider` |
| result | **5 failed, 3638 passed, 40 skipped, 9 xfailed** in 144s |

The five are exactly the `QUALIFIED_BACKEND_UNAVAILABLE` nodes below. The
journey: 23 failed (before M0.5a/b) → 10 (after fixtures) → 5 (after the
sweep/report path fix). Clean-checkout baseline: 51 failed / 3391 passed /
228 skipped, all of it missing untracked build artifacts — recorded with
capability flags in `docs/TEST-BASELINE.json`.

## M0.5c — classification of the remaining 10

Taxonomy: `REPOSITORY_DEFECT`, `MISSING_COMMITTED_ASSET`,
`OPTIONAL_TOOL_UNAVAILABLE`, `QUALIFIED_BACKEND_UNAVAILABLE`,
`KNOWN_SCIENTIFIC_FAILURE`, `ACTUAL_PRODUCT_BUG`. "Environmental" is not a
category.

| # | node | class | evidence |
|---|---|---|---|
| 1 | `test_doctor.py::test_real_quick_battery_runs_offline_and_fast` | `QUALIFIED_BACKEND_UNAVAILABLE` | doctor reports `bin.astra_booksim FAIL missing`; the test asserts the verdict is PASS/WARN |
| 2 | `test_serve_contract.py::test_serve_end_to_end_analytical` | `QUALIFIED_BACKEND_UNAVAILABLE` | `SERVING_PREFLIGHT_FAILED reason: BACKEND_BINARY_MISSING` — the preflight correctly refuses |
| 3 | `test_serve_fidelity.py::test_serve_emits_structured_result` | `QUALIFIED_BACKEND_UNAVAILABLE` | cascade of #2: parses output that was never produced |
| 4 | `test_pipeline_preflight.py::TestTimeloopBinPreference::test_real_repo_vendored_binary_exists` | `QUALIFIED_BACKEND_UNAVAILABLE` | vendored Timeloop binary not built in this worktree |
| 5 | `test_astrasim_spine_contract.py::test_dangling_astrasim_bin_warns_and_falls_back` | `QUALIFIED_BACKEND_UNAVAILABLE` | astrasim binary absent, lookup returns `None` |
| 6 | `test_commands_batch_e.py::TestSweep::test_sweep_all_topos_real_latencies` | `REPOSITORY_DEFECT` **FIXED** | asserted `REPO/runs/booksim/sweep_tiny.json`; the sweep writes immutable run dirs. Test now drives `cmd_sweep` into a temp run root |
| 7–10 | `test_commands_batch_e.py::TestReport::{stdout_table,latex_file,html_file,pdf_compiles}` | `REPOSITORY_DEFECT` **FIXED** | fixture handed `report` a path the sweep never wrote; same fix |

Notes on the two classes:

- **`QUALIFIED_BACKEND_UNAVAILABLE` (1–5)**: these are *correct refusals*, not
  product bugs. Two of them (1, 2) are test-vs-policy conflicts rather than
  missing binaries alone: the doctor and the serving preflight fail closed on a
  missing mandatory binary, while the tests assert success. The decision needed
  is whether qualification tests should skip on a missing backend or whether the
  backend must be built before the battery runs — not whether the refusal is
  wrong.
- **`REPOSITORY_DEFECT` (6–10)**: one root cause, two symptoms. The sweep's
  output location is not the location the test asserts, and the report tests
  cascade from the same fixture. This is the `RUNS_DIR` / `TRACK_RUNS_DIR`
  ambiguity AGENTS.md already flags, now with a failing test attached.

No node is classified `ACTUAL_PRODUCT_BUG` yet. #6–10 are the candidates if the
run-root drift turns out to be in production code rather than in the test.

## M0.5d — clean-checkout equivalence PROVEN

Two fresh detached worktrees at `2d72d99b`, the same command in both, node
sets compared exactly (not by count):

| outcome | eq1 | eq2 | identical |
|---|---|---|---|
| collected | 3689 | 3689 | YES |
| passed | 3391 | 3391 | YES |
| failed | 51 | 51 | YES |
| errors | 10 | 10 | YES |
| skipped | 228 | 228 | YES |
| xfailed | 9 | 9 | YES |
| collected sha256 | `b172182600c69344…` | same | YES |

Recorded in `docs/TEST-BASELINE.json` with capability flags. All 51
clean-checkout failures are missing untracked build artifacts — BookSim alone
accounts for ~48 — not code failures.

## Consequence for M1

M1's exit condition is **"adds no new failed node against this 5-node set"**
(and against the clean baseline's collected digest when run clean). Each M1
commit records the command and the worktree used, so the differential is
comparable.
