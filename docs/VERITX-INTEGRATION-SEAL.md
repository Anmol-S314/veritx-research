# VERITX-INTEGRATE — Seal Report

## Canonical base

```text
branch: veritx-integrate
worktree: /home/datavex/veritx-integration
base commit: a5b806fe048c5657972a12be5e98a007a0ffc4b6 (veritx-integrate tip;
  built on integration/canonical 96603ae2, one commit ahead of the pinned
  2f727dd1503c00697b2afaeda75a7fa6947dd1c3)
final candidate commit: c20af547c1e6509e35eeb1208caa206c7e0a5d9d (seal commit)
```

## Canonical authorities

| domain | canonical module | superseded implementations |
|---|---|---|
| intent | `application/compile_intent.py` (+`resources.py` 4-kind store) | Wave-B ad-hoc intent dicts |
| workload graph | `workload/graph.py` (`WorkloadGraph`, `ParallelismShape`) | `workload/canonical_graph.py` (now a delegating shim), v1 `WaveDWorkload`/`WaveDOperation` (deleted), `OperationGraph` as authority (historical v1 schema only) |
| fabric specification | `model/fabric_artifact.py` via `compiler/canonical.py` + `application/compile.py` bundle seam | `packet_format_v1.py`, `router_behavior_v1.py` (deleted), anonymous adjacency mutation (never an authority) |
| routing | `model/routing.py` + `routing_realization.py` (DOR_XY / ANYNET_MIN_HOPS classes) | none retained |
| VC/resource assignment | `model/vc_assignment.py` + `model/vc_resource.py` | none retained |
| compile request | `model/compile_model.py` (`CompileRequest` v2 / `CompileRequestV3`) | v1 application intents (refused, never migrated silently) |
| compile result | `compiler/canonical.py::CompiledFabric` + `ResolvedFabricBundle` | `ResolvedFabric`-hash-only lowering (bundle carries objects) |
| prepared execution | `backend/booksim_projection.py::PreparedBookSimInput` | RT `PreparedBackend` (LEGACY-ONLY, `backend/booksim.py`) |
| backend execution | `backend/booksim_execution.py::execute_prepared_booksim` | RT `prepare/run_waved_*` seams (LEGACY-ONLY, not on certified path) |
| backend evidence | `backend/evidence.py::ScientificBackendEvidence` (+`EvidenceArtifact`, `EvidenceRef`) | RT `CertifiedBookSimEvidence` (LEGACY-ONLY; validator refusal proven by test) |
| performance metrics | `performance/*` (Wave-E, byte-identical to source) + `CERTIFIED_METRIC_REGISTRY` | no second scoring formula |
| memory model | `core/memory.py` + `workload/memory_lowering.py` + `simulation/ramulator.py` | none (never reimplemented) |
| serving model | vendored LLMServingSim service semantics + canonical `simulation/serving_loop.py` + `backend/serving_round.py` + `backend/canonical_serving.py` | legacy `python -m serving` network path (explicit `--legacy` only) |
| multicast | canonical replicated unicast (`model/resolved_fabric.py` refuses silent reinterpretation) | physical-multicast fork (RETAIN_RESEARCH, patch not applied) |
| planes | canonical Fabric schema (unchanged; no plane abstraction forced) | plane cfgs/sweep/note (RETAIN_RESEARCH) |
| optimization | `optimization/` (definition/search/Pareto/selection/result) + `RealCandidateEvaluator` + canonical backend | `CandidateEvaluationPort` is the interface OF this implementation (not a parallel one); BO/GRPO/MILP stay deferred in `synthesis/` |
| persistence (compile plane) | `application/store.py::ResourceStore` (4-kind) + `SrotaControlPlane.compile` | Wave-C 7-kind store (never ported wholesale) |
| persistence (evaluation plane) | `application/results.py` + `waved_resources.py` loaders (tested; currently no production writers — verification surface) | v1 readers fail closed |
| CLI | `veritx_dse/cli/cli.py` + `commands_{compile,optimize}` | retired RT CLI surface (`COMMANDS`, `Ctx.failed`, fake-default) |
| Studio/API | `apps/studio/` (fixture-backed, contract-validated) | live study feed (OUT-OF-SCOPE this slice) |

## Reclamation result

Aggregated from `docs/VERITX-INTEGRATE-RECLAMATION.md` (row-level detail
there; UNRESOLVED = 0 — no TODO/maybe/pending-review rows remain):

```text
RECLAIMED family (COPY_VERBATIM + COPY_AND_ADAPT + RECLAIMED + TEST_ONLY applied)
                                     : 34 rows
KEEP_CANONICAL                       : 39 rows
SUPERSEDED                           : 6 rows + retired test blocks
LEGACY-ONLY                          : 3 rows (RT backend evidence stack,
                                       meshdor backend, RT standalone lowering)
REJECTED                             : 3 rows (RT→canonical evidence coercion,
                                       test_14 distinct-bytes invariant,
                                       second workload/graph authorities)
OUT-OF-SCOPE (each with concrete reason): 10 rows (PP/PD/CXL/PIM adapters,
                                       prefix-cache enablement, profiler
                                       binding, Studio live feed,
                                       binary provenance, lifecycle-test port,
                                       selection_metric_order vocabulary,
                                       result persistence API)
UNRESOLVED                           : 0
```

## Test qualification

### Full suite (DSE) — authoritative final run

Seal-candidate state at run time: HEAD `a5b806fe`, `git diff --check`
clean, no production changes after this capture. Command:
`PYTHONPATH=tracks/t3-topology/dse:tracks/t3-topology/dse/tests
python3 -m pytest tracks/t3-topology/dse/tests -q`
(full output `/tmp/veritx-final-seal-pytest.txt`).

```text
15 failed, 3555 passed, 24 skipped in 926.24s (0:15:26)
```

Differential (exact node IDs, `comm` on sorted FAILED lists):

```text
vs a5b806fe baseline set: FINAL_ONLY 0 / BASELINE_ONLY 0 / COMMON 15
vs previous complete run: IDENTICAL (byte-identical failure lists)
```

Reconciliation of the earlier session's intermediate failures
(`memory_graph` 5, `timeline_graph` 3, `resolved_fabric` 1,
`wave_e_identity` 1): those appeared only in intermediate partial
snapshots and were fixed BEFORE the previous complete run — they are
in neither the previous nor the final failure set. Ground truth
re-verified post-run: `test_memory_graph` + `test_timeline_graph` +
`test_resolved_fabric` + `test_wave_e_identity` = 162 passed, 0 failed.
No test is both fixed and remaining.

### Optimizer focused battery (canonical gate)

```text
184 passed, 4 skipped, 0 failed in ~12s
```

Files: `test_optimization_definition_identity`,
`test_optimize_canonical_cli`, `test_p1_optimize_booksim`,
`test_evidence_authority`, `test_p2_guided_optimization`,
`test_p2_optimization_truth`, `test_p2_real_adapter`,
`test_backend_booksim_execution`, `test_backend_booksim_projection`.

### BookSim live (§26)

`test_p1_optimize_booksim`: real binary, 2 candidates EVALUATED
(1216 vs 1120 cycles), Pareto + selection, byte-identical evidence
across invocations. Manual CLI replication confirmed end to end.
`test_p2_real_adapter::test_real_grid_end_to_end`: live
`optimize_certified` grid, EVALUATED + Pareto.

### Evidence authority

`test_evidence_authority`: 10 passed (round-trip stability,
tamper/transplant/type refusal, RT-document refusal).

### Ramulator

`qualification/ramulator.py` (python3.12 vendored extension),
seal-fresh: `VERDICT: PASS (1.9s, 16/16 checks)`.

### Serving

Dense live gate (seal-fresh): 2/2 requests, 174 rounds, 174 evidence
ids through the canonical path. MoE live gate (seal-fresh): 1/1
request, 70 rounds, EP AG/expert/RS preserved. EP battery
(`test_serving_ep`): 6 passed. Serving loop/DP/TP-groups suites green
in the full run.

### Multicast / planes

Multicast: canonical replicated unicast covered by the full suite;
physical BookSim patch retained UNAPPLIED by design (no live gate —
applying it unqualified would contradict the retention terms).
Planes: configs + sweep + note retained as research; `plane_separation.py`
gates documented in-script, not executed this slice (no BookSim sweep
established during reclamation either).

### RTL

Retained T3 RTL (2D/two-die + 3D + 4D + testbench + binding audit) lints
with verilator `--lint-only`, exit 0 (warnings only, no errors).
Functional qualification follows the binding audit (F1–F3 multicast
corners limited, 3D functional-only, 4D unqualified stub) — no new RTL
claims made.

### CLI/Studio

`veritx --help` / `optimize --help` / `serve --help` / `compile --help`
verified coherent; `--legacy` explicitly labeled non-canonical.
Studio fixtures 5/5 validate; Studio contract 6 passed; 3
regeneration tests + 1 error fail closed on the canonical compiler
(UNSUPPORTED example) — fixture mode deterministic, live study feed
OUT-OF-SCOPE (known limitation below).

## Known failures (all 15 — each with evidence of non-regression)

12× `test_vc_assignment.py` — INHERITED. Demand builder-time refusals
the implementation performs elsewhere; fail identically at the
pre-change baseline (verified by exact node-ID diff, FINAL_ONLY 0).
Frozen area; fixing would change canonical model validation semantics.

1× `test_design_intent_identity.py::test_migrated_documents_are_byte_identical`
— INHERITED. Migration preserves declaration order by design; fails
identically at baseline.

1× `test_application_service.py::test_application_package_reaches_no_legacy_compiler`
— STALE HISTORICAL TEST. Encodes the pre-reclaim package shape; fails
identically at baseline; canonical `application/compile.py`
legitimately defines `compile_bundle`.

1× `test_cli_compile_surface.py::test_no_booksim_binary_needed_for_canonical_compile`
— ENVIRONMENT (ledger-documented). Asserts the BookSim binary is
ABSENT; the binary is deliberately built for the live gates.

## Known limitations (product, not history)

- Evidence fidelity at seal time is `DIAGNOSTIC_UNPINNED_PRODUCER`
  (dirty tree pre-commit; revision identified). Evidence is authentic;
  producers pin once the tree is clean. Post-seal runs from the clean
  commit are expected QUALIFIED.
- PP/PD disaggregation, CXL/PIM service semantics, prefix-cache
  enablement, and profiler-backed compute are fail-closed exclusions,
  not silent mappings.
- Studio live study feed not demonstrated end to end.
- Physical multicast backend unqualified (patch retained, not applied).
- No `OptimizationResult` persist/reload API and no
  `selection_metric_order` field exist in-tree (vocabulary gaps, not
  defects); lexicographic selection orders by declared objective
  sequence with smallest-id tiebreak (verified in code).
- `docs/CAPABILITY-LEDGER.md`-style historical parity notes name
  source-branch paths (`build_candidates`, `OptimizationRun`,
  `test_optimization_core/e2e`); those objects are not in this tree
  and were not reintroduced.

## Architecture divergences (intentional)

- `RealCandidateEvaluator` / `CandidateEvaluationPort` are canonical
  in the integrated implementation (sole certified evaluator /
  its interface). Older Wave-F vocabulary such as `OptimizationRun` /
  `SrotaControlPlane.optimize` is not part of this tree and was not
  reintroduced merely to match historical documentation.
- `workload/canonical_graph.py` is a delegating shim over
  `workload/graph.py`, not an authority.
- The optimizer evaluates exclusively through canonical
  `booksim_execution.py`; RT evidence modules remain importable but
  are not on the certified path (boundary test proves refusal).
- `test_p2_optimization_truth` tests 12–14 were removed (12/13
  superseded by the p1 repeatability test; 14 contradicts the
  canonical identical-bytes contract); `test_ap02` was ported to the
  canonical seam. The file's remainder tests live single-copy
  optimizer mechanics.
- The P2 `TestOptimizeCli` block was replaced by
  `test_optimize_canonical_cli.py`.

## Seal decision

```text
CAN VERITX-INTEGRATE BECOME THE CANONICAL REPOSITORY STATE?

YES

BASIS:
- Final full suite: 15 failed / 3555 passed / 24 skipped; FINAL_ONLY 0
  vs baseline (exact node IDs), identical to previous complete run.
- UNRESOLVED ledger rows: 0.
- Focused optimizer gate: 184 passed, 4 skipped, 0 failed.
- Live qualification recorded in this report remains valid (no
  production changes since the gates ran).
- diff --check clean; no accidental tracked artifacts.
```

## Third-party modifications (explicit reasons)

- `third_party/booksim2/src/{booksim_config,injection,networks/anynet,networks/network,trafficmanager}.*`
  — staged pre-session B3.7b work: route-dump seam (executed-route
  evidence) + trace/diagnostic ABI (drain verdict, delivered/flit
  counters). Required by the built binary the live gates executed;
  presence proven by updated audit tests.
- `third_party/astra-sim/astra-sim/workload/Workload.cc` — ledger-mutex
  around `[LEDGER][COLL_SUBMIT]` emission (multi-Sys threads
  interleaved mid-line, corrupting ledger evidence and failing round
  qualification deterministically). Dense + MoE live gates pass
  because of it. All built binaries are git-ignored; source and
  binary are consistent in this worktree.
