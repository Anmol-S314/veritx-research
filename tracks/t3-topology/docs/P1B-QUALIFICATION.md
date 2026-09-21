# P1B qualification matrix (Q tranche)

Command: `cd tracks/t3-topology/dse && python3 -m pytest tests -q --tb=no -p no:cacheprovider`
Baseline: `tracks/t3-topology/docs/P1A-BATTERY-BASELINE.json`
(P0 seal `2c7a7061`: 52 failed + 10 errors, all missing-binary/capability
cascades on a binary-less fresh worktree; 3469 passed, 227 skipped.)

## Result at `fd428b34` (P1B.Q3a, clean tree)

`5 failed, 3814 passed, 40 skipped, 9 xfailed`, 0 errors, ~194 s.
The BookSim binary is built (`third_party/booksim2/src/booksim`), so
live tests execute instead of skipping (skipped 227 -> 40).

## Staying failures (5, all ⊆ baseline — still missing-binary cascades)

- `tests/test_astrasim_spine_contract.py::test_dangling_astrasim_bin_warns_and_falls_back`
- `tests/test_doctor.py::test_real_quick_battery_runs_offline_and_fast`
- `tests/test_pipeline_preflight.py::TestTimeloopBinPreference::test_real_repo_vendored_binary_exists`
- `tests/test_serve_contract.py::test_serve_end_to_end_analytical`
- `tests/test_serve_fidelity.py::test_serve_emits_structured_result`

## New failures: none. New errors: none.

`new_failed_nodes ⊆ baseline_failed_nodes` holds; error nodes are empty
(baseline had 10). Two transient non-baseline failures appeared mid-tranche
and were fixed forward in Q3a, zero outstanding:

- `test_backend_cross_qualification.py::TestUnsupportedDomains::test_non_anynet_route_class_refused`
  asserted the pre-Q rule; P1B-Q1 certifies DOR_XY on exact native meshes,
  so it is rewritten as `test_dor_xy_exact_mesh_selects_mesh_profile`.
- `test_domain_corpus_identity_is_stable`: the move happened at P1B.3
  (DEFAULT base VC class moves `traffic/id` + `traffic/to_dict_sha` only;
  render/projection/prepare entries identical to P1A; Q moves zero
  entries — bisected via `/tmp` worktrees). Argued re-pin
  `8d8f2fa7` -> `cdfc6a00`, note in `ARCHITECTURE-CONSOLIDATION.md`.

Discipline coupling the battery enforces: uncommitted TRACKED edits trip
`assert_pinned_producer` (dirt digest over `git diff HEAD`), which refuses
evidence-grade reuse and fails `test_reuse_keeps_wave_e_block`. The clean
tree restores it. Untracked `tracks/t3-topology/workloads/` debris is
excluded from dirt by policy and stays uncommitted.

## Resolved baseline nodes (57 = 47 failed + 10 errors)

All resolved by the provisioned binary (missing-binary cascades draining),
not by weakening assertions. Notable: both `test_wave_d_seal.py`
`TestReuseIdentity` nodes now pass (predicted to stay; they needed the
binary), and the whole `test_wave_e_product.py` block (32) plus the
`test_commands_batch_e.py` block (14, incl. all 10 errors) is green.

- `test_commands_batch_e.py` (14): TestBaseline::test_baseline_runs_literature_set,
  TestCompare::test_compare_two_topos, TestPareto::test_pareto_output_shape,
  TestSweep::test_sweep_all_topos_real_latencies,
  TestCertify::test_flow_missing_model_fails,
  TestCertify::test_flow_passes_on_real_synthesized_topo,
  TestEvaluateAnynet::test_anynet_eval_end_to_end,
  TestReport::test_report_html_file, TestReport::test_report_latex_file,
  TestReport::test_report_pdf_compiles, TestReport::test_report_stdout_table,
  TestRun::test_run_full_pipeline_artifacts,
  TestRunHistory::test_diff_needs_two_runs,
  TestRunHistory::test_runs_lists_experiments
- `test_control_plane_lifecycle.py` (2):
  TestStudyCli::test_study_cli_mixed_invalid_candidate,
  TestStudyCli::test_study_cli_rerun_and_inspect
- `test_regression.py` (4): TestRunBanner::test_success_says_complete,
  TestTraceReplayInvariants::test_delivers_every_packet_no_unstable,
  TestTraceReplayInvariants::test_honest_latency_present_and_sane,
  TestTraceReplayInvariants::test_torus_healthy_too
- `test_unified_contracts.py` (2):
  TestLiveHappyPaths::test_compare_mesh4x4_ok,
  TestLiveHappyPaths::test_pareto_eval_once_ok
- `test_v1_v2_differential.py` (1):
  TestCrossGenerationAttacks::test_v1_result_block_refuses_under_a_v2_plan
- `test_wave_d_seal.py` (2):
  TestReuseIdentity::test_result_provenance_block_matches_the_chain,
  TestReuseIdentity::test_transplanted_result_link_never_reuses
- `test_wave_e_product.py` (32): TestAggregateNetworkWindow (3),
  TestPerformanceKindMigration (1), TestPlanSideWaveEParentBehavioural (5),
  TestProductEvaluation (4), TestWaveEComparisonCompatibility (4),
  TestWaveENavigation (3), TestWaveEProvenanceBinding (9),
  TestWaveETamperMatrix (3) — full IDs per the baseline JSON diff.

## Live Q-tranche evidence pinned in this matrix

`test_backend_mesh_dor_profile.py` (27 tests): the P1A 9x9 DOR mesh
evaluates exit 0, `route_equivalence == EXACT` over 6561 pairs,
delivered 19600/19600, flits 156240/156240.
