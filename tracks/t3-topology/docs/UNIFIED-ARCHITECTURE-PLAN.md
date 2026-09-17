# Unified Architecture Plan — t3-topology

Date: 2026-09-13. Status: Phases 1–4 + hardcoded follow-up complete
(suite 661 passed / 6 skipped / 0 failed).

## Hardcoded follow-up (DONE, same session)- #2 RATES (was already fixed): run_experiments default now matches t3's grid.
- #3 path literals → canonical/absolute: cmd_init `--out` (TRACK_RUNS_DIR),
  trace chakra/model/hpc `--out` ×3, astra system/network/memory defaults,
  bo `--traffic`, t3 guided-builder out-files ($T3_DIR-anchored). Left
  deliberately: `generate_artifacts(output_dir="runs/artifacts")` (library
  default; relative URIs are more portable in manifests, no production caller
  uses the default).
- #4 seeds → `BOOKSIM_SEED=42` in core.constants (distinct from
  `DEFAULT_SEED=0` auto); wired through evaluator/iterative/bo/pareto.
- #5 timeouts → `None` + `VERITX_TIMEOUT` env resolve (default 60, milp 120)
  across evaluate_adj/evaluate_spec/eval_bs/run_rho/run_grpo/
  evaluate_topology/solve_tmcf. Deleted the stale pre-convergence inline
  fallbacks in bo/iterative (they encoded sample-200/max-3/plat-last and
  would silently diverge again); missing evaluator now raises ImportError.
- #1 machine paths: orphaned proof_*.json (no consumers) deleted;
  floonoc plugin → $HOME + env override; router_formal.sby → relative
  (workdir output is gitignored, regenerates); verify.sh root derived.
- #6 interface defaults + #7 sentinels/guards: intentionally unchanged
  (documented in review).

## Astrasim stall-watchdog fix (DONE 2026-09-14)
- Symptom: all 8 64-node microbench topos died at 5m01s with
  "backend stall: injected 0 packets" — no proper results.
- Root cause: the trip keyed on BookSim's uniform-traffic injection counter,
  which is structurally 0 in embedded mode (API injection bypasses it), and a
  10 us comp node means zero-injected-at-drain-start is NORMAL. A healthy
  64-rank 16 MB allreduce needs ~9 min (proven: cmesh64 ok, 12463530 cycles);
  16-node completes in 1m48s (11738610 cycles, bit-identical to Sep-11).
  Binary, ET bytes, and generated configs all proven unchanged — no regresssion.
- Fix (`scripts/run_astrasim.py`): VERITX_LEDGER=1 always in the frontend env;
  two-tier trip — no-issue hang (nothing submitted, 300s via ASTRASIM_STALL_S)
  vs stuck collective (submitted, nothing completes, 900s via ASTRASIM_SLOW_S);
  COLL_COMPLETE resets the slow clock; 60 s progress notes while armed.
  Live proof: previously-doomed cmesh64 → ok in 8m55s.
- Related: `--sizes {auto,n16,n64,legacy}` flag decouples topology-size
  selection from CONFIG-suffix sniffing (a chain-suffixed CONFIG only landed
  in n64 by accident). Spatial `--config-name` strips chained `_N<n>`
  suffixes (normalize_base_name, contract-tested).
- Honesty-gate order: missing binary now refuses BEFORE the PP guard (a
  missing binary was misreportable as a model problem); fixed 2 red
  spine-contract tests (pre-existing guard/test mismatch, predates this
  session). Fake-binary half mirrors main()'s --pp 1 acceptance.

## Audit findings (8 parallel auditors, all triaged)

1. No single source of truth for topologies (presets vs compile_model vs t3models vs chakra vs model_spec; llama70b defined 3 ways).
2. Two CLIs bridged by string (bash `t3` + `cli.py`, 5 dispatch tables, lossy `$@` forwarding, divergent error/logging contracts).
3. Three BookSim harnesses / three topo-size functions / three anynet writers; failure codes incompatible (1e9 vs 1000.0 vs 1e15 vs None).
4. Four result schemas, two results homes (`runs/` vs `results/` vs `runs/booksim/` vs `logs/`).
5. Shadow `BookSimError` hierarchy; dead error taxa; swallowed exceptions.
6. Compare/viz fork (loaders, palettes, `--json` labels, dead `--k` flag).
7. Legacy vs spatial timeloop pipelines (two stats parsers, schema fork, orphaned `noc_energy_bridge`).
8. Constants triple-sourced (NIC/LINK/VC values disagree 2–4x).
9. Tests pinned happy path only (synthesize, timeloop leg, live compare/pareto untested).

## Phase 1 — foundations (DONE)

- 1a `model/presets.py`: canonical `topo_size()` + fixed `edges()` dead branch and mesh overcount
  (mesh_8x8 128 → true 112; torus keeps 128). Adapter + all synthesizers + pareto delegate.
- 1b `core/errors.py`: promoted `TimeoutError`; deleted shadow hierarchy in `simulation/booksim.py`
  (re-exported); `detect_trace_stats` raises `TraceError` instead of zero-fallback; 6 swallowed
  `except` sites now log.
- 1c `core/constants.py` ← `reports/reports.py`: single import; NIC/LINK divergences resolved as
  distinct abstractions (bare NIC vs NIC+DMA, per-mm vs per-link), named + commented.
- 1d `core/paths.py`: new `SYNTH_DIR` (track `runs/booksim`); BO/iterative winners + results anchored
  there; `cmd_run` winner-pickup list fixed (was silently dropping synthesized winners);
  cli/pipeline error imports moved to `core.errors`.
- Stale tests updated (old message strings, mesh-128 counts, cwd-relative BO output expectations,
  abort-pinned anynet tests → warn-and-continue contract).

## Phase 2 — interfaces (DONE)

- 2a `synthesis/evaluator.py` (NEW): one BookSim code path with named presets
  (BO/ITERATIVE/PARETO_PRESET, numerics bit-identical per caller). `synthesis/results.py` (NEW):
  `SynthResult` merged additively into all four producers' JSON.
- 2b `scripts/lib/t3load.py` (NEW): `compare_json`, `load_sweep(strict_ok/keep_all)`,
  `find_sweep`, `saturation_point`, shared palette. All 7 compare/viz consumers rewired with
  semantics-preserving parameters. One behavior fix: `compare_curves --k` was dead, now works.
- Deliberately left divergent (documented in `evaluator.py`): per-caller sample_period /
  max_samples / sim_type / vc_buf / match policy / float sentinels. Converging those changes
  *results* — needs sim-owner decision.

## Phase 3 — entry point (DONE)

- 3a Registry + logging (verified pre-existing, completed by an earlier session):
  canonical `COMMANDS` table in `cli.py` (DISPATCH/_SUB_DESTS/parser derived, no second
  list), hidden `veritx --list-commands`, generic registry-driven t3 `_dispatch` (one
  native list, one blocklist — `evaluate astra` blocked: host-built frontend can't load
  in-container), lossless `$@` forwarding everywhere, bare `print()` eliminated in
  cli/pipeline (Ctx helpers, routing + texts preserved), t3 helpers to stderr,
  `t3 selfcheck` fails loudly on registry drift (verified: "t3 tables agree").
- 3b Legacy `run_timeloop_pipeline.py` retired → stub (rc=2 + migration pointer, no silent
  forward). `t3 timeloop` repointed at the spatial pipeline (same defaults);
  `t3 timeloop-spatial` kept as alias. Only referrers were t3 + a docstring; YAML-schedule
  demo dropped without migration (spatial covers real models).
- 3c `noc_energy_bridge.get_pj_per_hop(out_dir=None)` parameterized (standalone behavior
  identical); spatial summary gains additive `compute_energy_pj` (= total, documented),
  `traffic_bytes_total` (in-memory raw sum, normalize-immune), per-row `noc.*` join:
  per-HOP energy (topology-agnostic pipeline can't know hops — never fabricated; consumer
  multiplies by hops_avg), `--bytes-per-flit` stated assumption (default 16), stderr
  warnings for softmax estimates + Accelergy-skip. Join helper unit-tested both paths.
  Note: host Accelergy currently crashes (AladdinTable plugin API mismatch) — skip path
  exercised live, OK path proven by unit test.

## Phase 4+ — subsequent phases (PROPOSED)

### Phase 4a numeric convergence (DONE, sim-owner sign-off 2026-09-13: converge to PARETO)
- `evaluator.py` builders now driven by preset fields (were hardcoded per-caller branches).
- ITERATIVE ≡ PARETO protocol (max_samples 5, warmup 1, no wait_for_tail, honest-first).
- BO adopts the measurement protocol (span-derived sample_period, max_samples 5, warmup 1,
  honest-first first-match) but keeps throughput identity (sim_type, matrix branch,
  vc_buf_matrix 16, injection 0.04, no latency_thres line, seed 42, sentinels).
- Cost note: converged evals run longer (250k+ vs hundreds of cycles); analytical BO path
  unaffected; `--timeout` raisable on huge traces. Suite time unchanged (26s synthesis leg).

### Phase 4b contract tests (DONE — `dse/tests/test_unified_contracts.py`, 23 tests)
- 4a convergence lock, full timeloop-leg contract (7 branches incl. artifact copy),
  live compare + pareto happy paths (real binary, honest_latency>0 asserted),
  evaluate/certify/where validation, 4d registry contracts, 4e label rule.

### Phase 4c single results home (DONE)
- Remaining writers routed canonical: iterative `--out`/standalone defaults → SYNTH_DIR,
  `cmd_synthesize_iterative --out` default → SYNTH_DIR, `cmd_compile` default report →
  `results/compile/` (`--output` user copy via Ctx unchanged). Readers keep legacy
  fallbacks (old artifacts must resolve). Left deliberately: serving logs (runs/astra),
  UVM collateral (runs/uvm), traces stash, experiments DB — not result JSONs.

### Phase 4d model registry (DONE, structural)
- `presets.py`: `normalize_collective()` (canonical = CollectiveKind values) +
  `parallel_world_size()` (documents the MoE convention question; compile sizing keeps
  its own rule deliberately). Unknown chakra model → ValueError (was silent llama7b
  fabrication — typo'd MODEL= now fails rc=2 with known list, in chakra/gen/astrasim).
  t3models typo-guard uses world size (identical today, future-proof). gen_workload
  known-list now dynamic.
- Deferred (needs owners): llama70b seq 4096-vs-2048 + tp 64-vs-8 numeric divergence;
  compile `total_npus` ignoring pp/dp; microbench ET always encodes ALL_REDUCE=0
  (now warns loudly instead of silently).
  RESOLVED 2026-09-14:
  - ET encoding FIXED: build_collective_trace writes the real proto code per
    collective (0/2/5/6/7); dead 1-based constants removed; `(as ALL_REDUCE)`
    tag suffix dropped; new `et_coll_type` row field stops resume from
    trusting pre-fix mislabeled rows. Historical non-allreduce microbench
    rows (compare/ ALL_GATHER ok) contain allreduce numbers — re-measure.
  - llama70b / total_npus / WORKLOAD_PRESETS: DORMANT, zero live consumers
    (presets read only by tests; live path is t3models→chakra and
    CompileRequest.total_nodes). Nothing to converge; no change.

### Phase 4e flags (DONE, scripts-side)
- `t3load.input_label()`: one LABEL:PATH rule (explicit wins, else stem — never
  parent.name/split slices); bars/curves/heatmap rewired (fixes curves abs-path
  mislabels + heatmap bare-`--json` silent skip; bars legend loses [:14] truncation).
- `--sweep` alias for dashboard `--topology_sweep` (byte-identical output proven).
- `synthesize bo` accepts `--trace` (= `--traffic`). `--traces` (multi-file
  list) and `--matrix` (matrix file) are genuinely different, intentionally
  NOT aliased. (Prior note about parser pinning was overcautious: additive
  aliases don't disturb pinned flags.)

## Review-03 follow-up (DONE 2026-09-14, suite 668 passed)
Independent review (firstmate t3-review-03, against a clean worktree) confirmed
item-by-item against the live branch; several findings were worktree-stale
(milp/event_objective dupes gone, verify.sh/CI/product all live-healthy).
Fixed live:
- HIGH-2 (downgraded by evidence): BookSim itself rejects mismatched matrices
  (`expected 16x16 = 256`, honest no_output rows) — no silent corruption.
  Added pre-run skip+warn anyway (saves burning runs).
- HIGH-1: `t3 energy` reads the spatial manifest first (fresh by
  construction); legacy stats path carries an explicit staleness warning.
- MED-3: spatial honors T3_RESULTS (parent dir as root).
- MED-4: container mount-forward (repo paths translated to /workspace twin;
  outside-repo data dirs bind-mounted; system dirs warn) + root-caused the
  walkthrough Step-1 failure: t3 sources run/env.sh on HOST (BOOKSIM_BIN=
  host path), old code forwarded it verbatim into the container where it is
  invisible — while veritx's own /workspace resolution kept working.
- LOW-5 analog: empty cfg set → rc 2 (run_experiments + sanity_test).
- Packet conservation (prior-audit P0): converter trimmed last packets to
  conserve bytes exactly (was: full-size every packet, up to 60% inflation);
  --pkt-flits forwarded through `veritx trace chakra`; contract tests added.
- F3/F4/F6: sanity_test clean rc=2 without binary; compare test skipif;
  dragonfly duplicate num_vcs removed. F1/F5 verified already-fixed live.
- `make lint` is now a real gate (py_compile both trees + 674 collect +
  8 binary-free selfchecks). booksim-ext annotated (landed, do-not-reapply).
- F7: dashboard badge shows traffic provenance. F9: empty-legend warning fixed.
- Left deliberately: milestone_c/spec_translate subprocess boundaries
  (load-bearing isolation, both used); legacy mixed sweep dir (warned,
  back-compat); system-dir mounts (warn, never auto-mount).
- Owner calls still open: RTL liveness arch (mux+guard verified current);
  preserving the uncommitted stack (awaiting your commit decision).
