# Battery baseline — the differential set M1 must not grow

Status: **recorded, not green.** This is the honest pre-M1 state of the DSE
battery in the active consolidation worktree, plus the reason it cannot yet be
treated as a reproducible gate.

## Run

| | |
|---|---|
| worktree | `/home/datavex/veritx-audit` (sole active consolidation worktree) |
| commit | `64a4e736` (North Star freeze + ledger status) |
| command | `cd tracks/t3-topology/dse && python3 -m pytest tests -q --tb=no -p no:cacheprovider` |
| result | **23 failed, 3495 passed, 42 skipped, 9 xfailed** in 158s |

## The 23 known-failed nodes, by cause

### A. Trace library / shipped trace assets (8)

```
tests/test_where_interact.py::TestResolveAsset::test_finds_library_trace_by_bare_name
tests/test_where_interact.py::TestResolveAsset::test_finds_trace_with_extension
tests/test_where_interact.py::TestWhere::test_where_trace_prints_copy_pasteable_path
tests/test_where_interact.py::TestWhere::test_where_lists_candidates_on_ambiguity_or_miss
tests/test_where_interact.py::TestWhere::test_where_json_mode
tests/test_trace_commands.py::TestHpc::test_installs_library_trace
tests/test_trace_commands.py::TestHpc::test_unknown_library_entry_lists_available
tests/test_trace_commands.py::TestHpc::test_appends_dot_trace_extension
```

Cause: the trace library the CLI resolves against is not present in this
worktree (`No trace matching 'test_dynamic'`).

### B. Astrasim cfg size directories (2)

```
tests/test_unified_contracts.py::TestSizesRouting::test_explicit_wins
tests/test_unified_contracts.py::TestSizesRouting::test_auto_sniffs_suffix
```

Cause: `select_cfgdir("baseline", "n64")` falls back to the `configs`
directory because no `configs/<size>` directory exists; the contract expects
the size directory.

### C. Slice-A trace asset (3)

```
tests/test_slice_a_booksim.py::TestSliceA::test_e2e_succeeded
tests/test_slice_a_booksim.py::TestSliceA::test_deterministic_replay
tests/test_slice_a_booksim.py::TestSliceA::test_result_frozen_spec_matches_hash
```

Cause: `run_experiment` cancels the run (state `CANCELLED`, not a crash) —
`core/experiment.py` cancels with `trace invalid` / `trace has no parseable
packets` when `dse/archive/inputs/traces/qwen3_20k.trace` is absent. The
binary is present; the trace input is not.

### D. Real-binary / toolchain legs, not yet individually root-caused (10)

```
tests/test_commands_batch_e.py::TestSweep::test_sweep_all_topos_real_latencies
tests/test_commands_batch_e.py::TestReport::test_report_stdout_table
tests/test_commands_batch_e.py::TestReport::test_report_latex_file
tests/test_commands_batch_e.py::TestReport::test_report_pdf_compiles
tests/test_commands_batch_e.py::TestReport::test_report_html_file
tests/test_doctor.py::test_real_quick_battery_runs_offline_and_fast
tests/test_pipeline_preflight.py::TestTimeloopBinPreference::test_real_repo_vendored_binary_exists
tests/test_serve_contract.py::test_serve_end_to_end_analytical
tests/test_serve_fidelity.py::test_serve_emits_structured_result
tests/test_astrasim_spine_contract.py::test_dangling_astrasim_bin_warns_and_falls_back
```

All exercise real
binaries, vendored trees or the CLI report toolchain; each needs individual
triage before it can be called environmental with confidence.

## Pre-existing, not introduced by the freeze

The same files were run in a throwaway worktree at `fbc71d74` (the commit
before the North Star freeze): **13 failed, 56 passed, 7 skipped** — the same
13 nodes from groups A–C, identically. The freeze commits added a reference
tree, a doc and an architecture-law test; they added no runtime code.

## The real finding: this battery is not reproducible

A fresh detached worktree at the *same commit* (`fbc71d74`), with no local
untracked assets, produced:

```
61 failed, 3255 passed, 230 skipped, 10 errors
```

Versus **23 failed, 3495 passed, 42 skipped** in the working worktree. Whole
clusters invert — `test_wave_e_product.py`, `test_wave_d_seal.py`,
`test_regression.py` and `test_unified_contracts.py::TestLiveHappyPaths` pass
here and fail in a fresh checkout. Test outcome is dominated by untracked,
environment-local state (populated `runs/`, built `third_party` binaries, trace
assets, cfg directories), not by the committed code.

Additionally, the suite cannot even be collected without
`tracks/t3-topology/scripts/lib/` (`t3log.py`, `t3load.py`, `t3models.py`, with
`__init__.py`), which is **untracked in every worktree** while being imported
by 11 tracked files (`Makefile`, `run_astrasim.py`, `aggregate.py`,
`analysis.py`, `generate_dashboard.py`, `plot_curves.py`,
`run_experiments.py`, `test_unified_contracts.py`, ...). It was copied into
this worktree from the stale one to make the run possible; it is still
untracked.

## Consequence for M1

`no new failed nodes` cannot be measured until the asset environment is
pinned. Until then:

1. Treat the 23 nodes above as the differential set, and require M1 to add
   none — not to reach green.
2. Record, in the M1 commit, the command and worktree used, so the next
   differential is comparable.
3. Fix the two asset classes that are cheapest and highest-leverage:
   - track `scripts/lib/` (it is source, imported by tracked files);
   - provide or skip-on-absence the trace/cfg fixtures (groups A–C), so a
     fresh checkout does not report 61 failures for missing test data.
4. Only then can a "battery green" exit condition be written without lying.
