# File inventory — veritx-research (2026-10-26)

Scope: hand-authored source only (~1,902 files). Excluded: `runs/` (~90k outputs),
build trees (`target/`, `.venv`, `__pycache__`, `.hypothesis`), `node_modules`, `third_party/`.
Policy agreed with owner: **report only — nothing deleted without per-item approval.**

## Method

Six parallel investigators, one per area. Every DEAD/ORPHAN flag is grep-verified
(import/citation census), not guessed. Two agent claims were overturned by verification:

- **Canonical flip (owner correction): `apps/studio/prototype/` is the CURRENT frontend under
  development; `apps/studio/src/` is the OLDER full-featured frontend (kept as legacy reference).
  The studio agent's "prototype = legacy" verdict is reversed; its *internal* dead/orphan
  findings within the old tree still stand.
- **`tracks/t3-topology/scripts/pareto_report.py` is LIVE** (dispatched by the `t3` dispatcher,
  PA-04), not dead as the D agent claimed — it grepped Makefile/CI/docs but not `t3`.
  Conversely the E agent's "OK" on `energy_score`/`robustness`/`pareto*.py` was wrong:
  zero code importers (only CSV-key/prose mentions); only live inbound is dead files
  importing dead files. Verdict: dead (except `pareto_report.py`).

## Counts

| Area | Files | OK | Dead | Dup | Stale | Other |
|---|---|---|---|---|---|---|
| A prototype/src+tests+desktop+tauri | 157 | 150 | 0 | 0 | 7 (2 scratch + 5 gitignored regen) | — |
| B studio/src (legacy) + scripts/tests/e2e/fixtures | 324 | 308 | 1 | 5 | 1 (partial) | 8 orphan, 1 trivial |
| C veritx_dse package (309) | 309 | 289 | 6 | 4 | 1 | 9 empty-convention |
| D dse/tests + scripts (487) | 487 | 441 | 45 | 1 | 1 | — |
| E tracks top-level/configs/rtl/scripts | 210 | 152 | 18 | 5 | 35 | — |
| F scripts/contracts/docs/validation/archive/root | 415 | 318 | 4 | 0 | 8 | 14 trivial, 71 archive-fodder |

## Removal candidates (awaiting owner approval)

### S1 — safe deletes (zero references, grep-verified)

- R1 `apps/studio/prototype/.mix.mjs`, `.mix2.mjs` — scratch Playwright probes, superseded by `tests/*.spec.ts`
- R2 root `explore-clean-top.png`, `link-viz-before.png`, `router-viz-before.png` — unreferenced
- R3 12× `docs/design/stitch_veritx_studio_eda_frontend/*/screen.png` — literal `<FIFE Image failed to fetch>` text; replacements exist in `design-explore/contact-*.png`
- R4 `apps/studio/src/components/GraphFineKnobs.tsx` — zero refs tree-wide (legacy tree)
- R5 `apps/studio/src/pages/agents.tsx` — unimported; `/agents` renders `AgentsLoom` (legacy tree)
- R6 5× bare `apps/studio/fixtures/projects/*.json` — unreferenced twins of `*.project.json` (legacy tree)
- R7 `apps/studio/tests/e2e_walk.cjs` — no in-tree runner; superseded by `e2e/*.spec.ts` + pytest suites
- R8 veritx_dse dead: `backend/qualification.py` (273L), `application/execution_closure.py` (515L), `application/inventory.py`, `application/surfaces.py`, `tools/generate_studio_fixtures.py`, `tools/memory_miss_model.py`, `cli/commands_trace.py` (dup of cli.py inline cmds), `gateway/qualification.py` (16L dup), `workload/canonical_graph.py` (retired shim)
- R9 veritx_dse dups: `tools/chakra_to_dse.py` (wired copy is `scripts/`), `tools/multi_workload_pareto.py` (761L diverged fork; wired copy is `scripts/`)
- R10 `tracks/t3-topology/dse/tests/test_astra_trace.py` — collects 0 tests, imports 3 deleted modules
- R11 14 orphaned PA scripts: `area_model`, `area_ranking`, `bisection_bw`, `buffer_sweep`, `energy_score`, `energy_validate`, `paper_figures`, `pareto`, `pareto_3d`, `pareto_compare`, `pareto_plot`, `regression_export`, `robustness`, `stability` (all under `tracks/t3-topology/scripts/`)
- R12 `tracks/t3-topology/scripts/srota_deflect.py` — unreferenced; subject rejected by `native_srota_regulator`
- R13 config dups: `configs/ftree.cfg` (=fattree16), `configs/qtree16.cfg` (=qtree64), `configs/tree4.cfg` (=tree4_64) — double-counted by sweep globs
- R14 `configs/noc_specs/proof_1_topology-mesh_vcs-8_vc_buf-8.json`, `proof_2_*`, `proof_3_*` — zero refs
- R15 `examples/ska_low_fx_correlator-v4.json` (zero refs), `examples/llama_dense_64tiles.json` (superseded by -v3), `examples/qwen3_moe_tp2_ep4_16tiles-v3.json` (superseded by -v4)
- R16 `hardware/noc_multicast_bw.cpp` (unreferenced), `scripts/npu_scaling/qwen3_4npu_single.json` (unreferenced), `timeloop/experiment_configs/baseline.yaml` (superseded by HF configs)
- R17 `scripts/archive/multicast_savings.py` — byte-identical to `research/` copy
- R18 `docs/reports/LOOM-PRODUCTION-TRACKER-STATUS.md` (superseded by RESCORE), `docs/reports/LOOM-M9-M11-performance-budgets.md` (15-line non-result proposal)
- R19 `archive/booksim-ext/mesh-class-vc.patch` — undocumented vs documented `multicast.patch`

### S2 — move to archive/ (not delete)

- R20 `scripts/spend.sh` — personal cost tracker, not repo workflow
- R21 ~70 reviewed Stitch mockups under `docs/design/stitch_veritx_studio_eda_frontend/` — KEEP 4 still cited by the live ladder (`design_fabric_topology/code.html`, `optional_agents_workload_translation/code.html`, corrected missing-artifact pair); batch is reviewed/graded/correction-applied
- R22 `tracks/t3-topology/scripts/archive/` remainder (~30 files) — self-declared superseded; git preserves history
- R23 `configs/anynet16.cfg` (crashes rc=255), `configs/dragonfly16.cfg` (72-node in 16-node sweep) — poison `sanity_test`/`run_experiments` globs; delete or exclude from glob
- R24 `tracks/t3-topology/docs/wave-d-contract.*` — misfiled; belongs under `dse/`
- R25 `scripts/setup-github-runner.sh`, `setup-gitlab-runner.sh` — one-time provisioners, zero refs; wire into docs or archive

### S3 — needs a decision (rewrite / rewire / keep)

- R26 `CHANGELOG.md` (21-line stub, predates program), `CONTRIBUTING.md` (references absent `serving/` tree — actively misleading): rewrite, not delete
- R27 `docs/design/reviews/backend-completion-plan.md`, `backend-copy-test.md`: one-shot notes superseded by Oct-24 completion — archive
- R28 `scripts/check_topology_family_registry.py`: real validator nobody runs — one-line add to `product-gates` loop or admit informational
- R29 `tracks/t3-topology/scripts/research/*.py` (3 spikes): runnable, documented CLIs, zero repo refs — confirm hand-run before touching
- R30 `apps/studio/README.md` layout section: refresh (fixture-switcher → mode offline; DesignEditor → DesignViewV2Editor)
- R31 `docs/decisions/modules/veritx_dse.md`: 3-line pointer stub — delete or expand
- R32 KEEP (do not delete): 15 test-only-imported modules (`model/system_intent`, `backend/meshdor.py`, `backend/native_*`, `verification/*`, `workload/migration`, etc.) — tests are their consumers; `backend/meshdor.py` goes de-facto-dead only if R8 `backend/qualification.py` is removed (verify `preset_certification` uses `meshdor_profile` only — confirmed)
- R33 consolidation watch, NO action: 4 parallel selection models, 3 fabric renderers, `simulation/booksim.py` vs `backend/booksim_execution.py`, `workload/canonical.py` vs `workload/graph.py` — distinct scopes, overlapping names only

No action: gitignored regenerables (`src-tauri/binaries/`, `src-tauri/gen/`, `__pycache__`), `docs/decisions/modules/*` rationale extracts (live), historical reports/ledgers, `contracts/srota/v1` (frozen compat), review evidence PNGs/JSONs.
