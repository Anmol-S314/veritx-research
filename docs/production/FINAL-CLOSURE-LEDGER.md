# VERITX Final Closure Ledger

Single ledger for the production-closure program. Status values:
`OPEN`, `IN_PROGRESS`, `CLOSED`, `UNSUPPORTED`, `DEFERRED_NONBLOCKING`.

Authority is source + tests + runtime output, never this document. Where a
row says CLOSED, the commit and the gate are named. `docs/production/CLOSURE-PLAN.md`
remains the earlier narrative; this file is the program ledger.

Release candidate under audit: baseline `2521d713`, inherited branch point
`bd6be628`, qualified code SHA `c759b84b` (this ledger and seal commits
follow it). Verdict: **NOT READY** (see `PRODUCTION-SEAL.md`).

---

## C0 — baseline + reproducibility snapshot

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C0 | high | CLOSED | `docs/production/FINAL-BASELINE.md` | no frozen reproducibility snapshot | recorded SHA, toolchain, backend hashes, test totals, skip classes | — | fast/validation/harness run and logged | doc commit | supersedes stale `BASELINE.md` counts | live-backend tier re-run owed in C10 |

## C1 — scientific core closure

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C1.1 executed route realization | critical | CLOSED | `backend/route_observation.py`, `backend/booksim_projection.py`, `backend/booksim_execution.py`, `backend/evidence.py` | executed route was only statically qualified | prepared schema v4 binds `expected_route_rows` + renders dump path; supervised run parses/compares the fork dump dest-by-dest and binds `route_dump_sha256` (evidence v3) | `test_route_observation.py` (10) incl. non-adjacent, unknown class, transplanted; `test_backend_booksim_execution.py` real mesh/anynet | real BookSim gates observe `EXECUTED_ROUTE_OBSERVED` | `c2748f9a`, `bd973e6c`, `aea2064b`, mutation tests `2521d713` | P0.10 claim now observed, first-hop only | beyond first hop not observable from the fork dump |
| C1.1b convergence window (F-0007) | critical | CLOSED | `backend/booksim_projection.py` | window sized from packet count, not per-source flit serialization; concentrated traces truncated | `trace_injection_horizon`; schema v5 / schedule v2 | `test_backend_booksim_projection.py` (horizon) + harness V13 | V13 conservation PASS, completion 2939 == authority | `e9abab38` | F-0007 fixed; old V13 numbers invalid | 1000-cycle drain margin is a heuristic |
| C1.2 error laundering | critical | CLOSED | `core/errors.py`, certificate/compiler boundaries | `ValueError`-rooted catch laundered programmer faults into verdicts | `SemanticError`/`Refusal` taxonomy; boundaries catch only typed refusals | `test_certificate_failclosed.py`, `test_11_arbitrary_programmer_error_escapes` | fast tier green | `ff141c68` | B7 closed | — |
| C1.3 producer certification at optimizer boundary | critical | CLOSED | `optimization/result.py`, `backend/producer.py`, `backend/evidence.py` | unpinned producer could reach CERTIFIED_PRODUCT | single admission rule + manifest binding; `optimize_certified` is the only certified entry | `test_certified_admission.py` incl. new `Optimizer.optimize_certified` boundary test | fast tier green | `a274d4b0`, boundary test `2521d713` | certified admission theorem | — |
| C1.4 exact recipe admission | high | CLOSED | `backend/evidence.py` (`required_build_recipe`) | evidence bound "some" recipe, not the profile's expected recipe | profile→exact-recipe map; admission refuses mismatch | `test_certified_profile_requires_the_exact_build_recipe`, `test_admission_uses_the_recipe_constant_by_profile` | fast tier green | `aea2064b` | — | — |
| C1.5 toolchain provenance reality | high | CLOSED | top-level `Makefile` | manifest hardcoded `g++` while build honoured ambient `CXX` | `RELEASE_CXX` drives every backend build and both manifest writes | `test_release_build_records_the_toolchain_it_actually_uses` | `make -n release-build RELEASE_CXX=clang++` threads clang++ | `839cd3a9` | P0.6 strengthened | compile flags still declared, not observed |
| C1.6 conservation closure | critical | CLOSED | `backend/booksim_execution.py` | packet/flit counters unenforced | required loaded/injected/delivered + injected/accepted flit equality | `test_booksim_conservation.py`, harness conservation checks | V01–V14 conservation PASS | `03e50675`, `a274d4b0` | — | flit totals depend on the window (C1.1b) |
| C1.7 evidence admissibility | high | CLOSED | `backend/evidence.py` | content-hash validation accepted impossible documents | closed vocabularies + cross-field invariants; rehashed impossible docs refuse | `test_evidence_admissibility.py` | fast tier green | `facf645b`, `aea2064b` | — | — |
| C1.8 VC contract | high | CLOSED | `model/vc_assignment.py` | malformed/duplicate authoring collapsed to valid artifacts | strict authoring/persistence contract | `test_vc_assignment.py` + adversarial suite | fast tier green | `a0b934b6` | — | — |

## C2 — authority collapse

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C2.1 v3 compiler authority | high | CLOSED | `compiler/orchestration.py`, `compiler/canonical.py`, `compiler/candidate_policy.py`, `docs/production/COMPILER-AUTHORITY.md` | v3 re-sequenced the derivation and carried its own 8/8/1 literals | `compose_deterministic_candidate` is the one engine; both paths call it; orchestration sequencer + literals deleted | `test_both_compile_paths_funnel_through_one_composer`, `test_v3_orchestration_uses_the_single_baseline_settings`; 543 compile tests | fast tier 3533 passed | this commit | A8 closed | V2↔V3 request-equivalence not defined (non-blocking) |
| C2.2 workload authority | high | CLOSED | `workload/{graph,operations,canonical,messages,traffic,collectives}.py`, `docs/production/WORKLOAD-AUTHORITY.md` | collective-kind vocabulary and algorithm map had 2–4 independent definitions (F-0004/F-0006 precondition) | single authority in `workload/collectives.py`; graph/operations/messages/migration import by identity | `test_collective_vocabulary_has_exactly_one_authority`, workload suite (276 passed) | fast tier green | this commit | COALESCES the four copies | `workload/canonical.py` op-kind vocabulary still inline (distinct fact, no schedule) |
| C2.3 collective audit | high | CLOSED | `workload/collectives.py`, `workload/messages.py`, `verification/reference_semantics.py`, `validation/harness/*` | ring ALLGATHER over-transmitted (F-0006); no non-ALLREDUCE oracle | closed-form law per pinned kind; direct/broadcast graph law; explicit broadcast root | V11–V14; `test_collective_allgather.py`, `test_workload_collectives.py` | V01–V14 PASS | `921eb270`, `620f15b9` | F-0006 fixed; network-level semantics only | chunk ownership/rotation not modeled (no full data-semantic claim) |

## C3 — durable run authority

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C3 | critical | CLOSED | `core/run_bundle.py`, `backend/reproduce.py`, `backend/booksim_execution.py`, `cli/cli.py` | three run notions; timestamped dirs; no verify/reproduce | checksummed `RunBundle` (atomic fsynced finalize, path-independent `bundle_id`); `veritx verify-run` (no rerun); `veritx reproduce` (rerun + science compare); every supervised execution finalizes | `test_run_bundle.py` (unit + real finalize/reproduce/tamper) | real reproduce matched; tamper refused | `0e915554` | A6 closed | legacy `core.runs`/`new_run_dir` still coexist; no single lifecycle wiring for evaluator/serving dirs |

## C4 — failure / concurrency safety

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C4 | critical | CLOSED | `tests/production/` | no fault/concurrency suite | fault matrix + concurrency/idempotency tests | `test_failure_injection.py` (10), `test_concurrency.py` (4, real gated) | typed failures; no evidence on fault; concurrent identical runs share identity | `dbbcf17c` | — | SIGKILL/process-restart of the parent service not exercised |

## C5 — production workload trust

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C5 | high | CLOSED | `validation/corpus.py`, `validation/experiments/V01–V14` | no production-scale corpus | W0 experiments run; W1/W2/W3 representative entries built through the canonical pipeline with content-addressed manifests | `validation/tests/test_production_corpus.py`; harness V01–V14 | manifest_id stable; conservation holds | `a7784bde` | workload matrix populated | representative, not exhaustive; no serving `.et` workloads |

## C6 — ASTRA numerical qualification

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C6 | high | IN_PROGRESS | `backend/astra_machine.py`, `third_party/astra-sim/.../Booksim2Fabric.hh`, `validation/harness/engines.py` | ~30M-cycle dominant timing | root cause fixed: `run_cycles` quantized draining billed 1,000,010c per ring step; chunked stepping restored (F-ASTRA-0001); aggregate now 40310 = declared 10000+30310, verified independently | engine gate `astra_runtime` | gate PASS, aggregate closes; gate wording corrected | `a4f7da62`, wording fix | F-ASTRA-0001 | no independent per-domain oracle yet; absolute timing still unqualified |

## C7 — serving qualification

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C7 | high | IN_PROGRESS | `serving/*`, `backend/serving_round.py`, `tests/test_serving_loop.py`, `tests/test_serving_liveness.py` | integration fixtures not vendored; qualification not complete | network-execution-evidence and multi-instance liveness gates exist and refuse missing/contradictory ledgers; flaky protocol tests deterministic; release gate fails on skips | `test_a_dispatched_instance_without_execution_evidence_refuses`, `test_a_missing_ledger_refuses`, serving liveness suite | fast tier green; gate fails on `.et` skips | `503c53a8` + prior serving work | — | serving `.et` fixtures unvendored → integration domain UNSUPPORTED; no independent TTFT/latency oracle |

## C8 — reproducible release build

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C8 | high | IN_PROGRESS | `Dockerfile`, `Makefile`, `scripts/write_release_manifest.py`, `.github/workflows/release.yml`, `validation/harness/engines.py` | container tag moving; several Docker deps clone HEADs; no release manifest; ASTRA build invoked with `sh` | `release-manifest.json` (`make release-manifest-json`); tag releases assert digest pin; F-0008 (bash) fixed; ASTRA engine timeout 300→900 | `test_release_manifest_binds_the_release_to_its_facts`; T6 clean clone (fast 3562 + harness green) | T6 build + science green | `a7784bde`, `64944077`, `c759b84b` | F-0008 | Dockerfile external clones unpinned; bit-reproducible binaries not established |

## C9 — live Studio product

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C9 | high | IN_PROGRESS | `veritx_dse/gateway/`, `apps/studio` | fixture-only operation | FastAPI gateway built over canonical services (compile/evaluate/optimize/runs/evidence/qualification/workloads) | `test_gateway.py` | gateway contract green | `d789c4da` | — | React app not yet wired to the gateway |

## C10 — final release battery

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C10 | high | IN_PROGRESS | `.github/workflows/release.yml`, `validation/harness/engines.py` | battery run at one frozen SHA | T0–T4 run green (fast 3562, validation 24, harness V01–V14, real 154); T6 clean clone green at `c759b84b`; T7 gateway-level smoke (uvicorn+curl); ASTRA timeout false-FAIL fixed | — | full battery + T6 | `c759b84b` | — | C10.2 certified run is covered by `test_real_grid_end_to_end`; C10.3 broader matrix and T7 browser smoke owed |

## C11 — final adversarial audit

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C11 | high | IN_PROGRESS | this program | stop-condition questions re-asked at seal | F-0007 (window), C1.5 (toolchain), F-0006 (ALLGATHER) found and fixed; route/producer/evidence/VC/admissibility/run-integrity/concurrency audits done | regression per fix | fast tier green | `e9abab38`, `839cd3a9`, `dbbcf17c` | — | ASTRA dominant-timing question unresolved (C6); clean-clone identity not yet re-proven |

## C12 — production seal

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C12 | high | IN_PROGRESS | `docs/production/PRODUCTION-SEAL.md` + all C13 outputs | seal only at full closure | all required C13 docs exist; seal refreshed with battery + T6 facts; verdict NOT READY | — | — | this program | — | C6/C7/C8/C9 blockers remain; verdict stays NOT READY |

---

## Stop conditions currently active

The release is **NOT READY** because these C15 conditions remain open:

- run corruption / concurrency not yet proven (C3, C4);
- clean clone not qualified (C8);
- release-critical tests skip (`test_full_pipeline.py`, ASTRA reference) (C7, C10.1);
- ASTRA timing contains an unexplained dominant component and is honestly
  labelled NOT_ESTABLISHED (C6) — it is excluded from scientific claims;
- two canonical authorities (v2/v3 compiler) not yet collapsed (C2.1);
- workload authority not yet audited (C2.2).

No stop condition is currently *violated* by a passing false result: the
conservation, route, producer and admissibility gates are all fail-closed
and green.
