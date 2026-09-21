# Battery baseline — the differential set M1 must not grow

Status: **M0.5a/b landed (23 → 10 failures). M0.5c classified. M0.5d open.**

This is the honest state of the DSE battery in the active consolidation worktree
(`/home/datavex/veritx-audit`), plus the reason it is not yet a reproducible
gate.

## Current run

| | |
|---|---|
| commit | `bff62a41` (M0.5b fixtures) |
| command | `cd tracks/t3-topology/dse && python3 -m pytest tests -q --tb=no -p no:cacheprovider` |
| result | **10 failed, 3633 passed, 40 skipped, 9 xfailed** in 138s |

Before M0.5a/b, at `208c890a`: 23 failed, 3495 passed, 42 skipped, 9 xfailed.
The 13 asset failures are gone; the 10 below are what remains.

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
| 6 | `test_commands_batch_e.py::TestSweep::test_sweep_all_topos_real_latencies` | `REPOSITORY_DEFECT` | asserts `REPO/runs/booksim/sweep_tiny.json`; the sweep writes no such file (run-root drift: `RUNS_DIR` vs `TRACK_RUNS_DIR`/`SYNTH_DIR`) |
| 7–10 | `test_commands_batch_e.py::TestReport::{stdout_table,latex_file,html_file,pdf_compiles}` | `REPOSITORY_DEFECT` | class fixture runs `legacy sweep` and asserts `rc == 0`, gets 1; standalone the same command exits 0, so the fixture's state/run-root differs |

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

## M0.5d — clean-checkout equivalence is still open

The battery remains non-reproducible across worktrees: a fresh detached
worktree at the same commit reported **61 failed / 3255 passed / 230 skipped /
10 errors** against 23/3495/42 in the working worktree, with whole clusters
inverting (`test_wave_e_product.py`, `test_wave_d_seal.py`,
`test_regression.py::TestTraceReplayInvariants`). M0.5a/b removed the two
largest causes (untracked `scripts/lib`, ignored trace/config inputs), but the
equivalence gate has not been re-run since.

M0.5d completes when two fresh worktrees at the same commit produce **equal
node sets** for collected/passed/failed/skipped/xfailed, and the result is
written to `docs/TEST-BASELINE.json` with the capability flags
(`booksim`, `astra`, `ramulator`, `timeloop`).

## Consequence for M1

Until M0.5d lands, M1's exit condition is **"adds no new failed node against
this 10-node set"**, not "green". Each M1 commit records the command and the
worktree used, so the next differential is comparable.
