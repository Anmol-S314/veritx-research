# VERITX Final Closure Ledger

Single ledger for the production-closure program. Status values:
`OPEN`, `IN_PROGRESS`, `CLOSED`, `UNSUPPORTED`, `DEFERRED_NONBLOCKING`.

Authority is source + tests + runtime output, never this document. Where a
row says CLOSED, the commit and the gate are named. `docs/production/CLOSURE-PLAN.md`
remains the earlier narrative; this file is the program ledger.

Release candidate under audit: `2521d713`. Verdict: **NOT READY** (see
`PRODUCTION-SEAL.md`).

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
| C2.1 v3 compiler authority | high | IN_PROGRESS | `compiler/orchestration.py`, `compiler/canonical.py`, `compiler/candidate_policy.py`, `docs/production/COMPILER-AUTHORITY.md` | v2 collapsed; v3 still re-sequences the derivation and carried its own 8/8/1 hardware literals | baseline hardware settings collapsed to one `BASELINE_FABRIC_SETTINGS`; v3 consumes it | `test_v3_orchestration_uses_the_single_baseline_settings`; 577 compile tests pass | fast tier green | this commit | — | v3 sequencer + `_derive_canonical_fabric` duplication and no V2↔V3 parity test remain (A8) |
| C2.2 workload authority | high | CLOSED | `workload/{graph,operations,canonical,messages,traffic,collectives}.py`, `docs/production/WORKLOAD-AUTHORITY.md` | collective-kind vocabulary and algorithm map had 2–4 independent definitions (F-0004/F-0006 precondition) | single authority in `workload/collectives.py`; graph/operations/messages/migration import by identity | `test_collective_vocabulary_has_exactly_one_authority`, workload suite (276 passed) | fast tier green | this commit | COALESCES the four copies | `workload/canonical.py` op-kind vocabulary still inline (distinct fact, no schedule) |
| C2.3 collective audit | high | CLOSED | `workload/collectives.py`, `workload/messages.py`, `verification/reference_semantics.py`, `validation/harness/*` | ring ALLGATHER over-transmitted (F-0006); no non-ALLREDUCE oracle | closed-form law per pinned kind; direct/broadcast graph law; explicit broadcast root | V11–V14; `test_collective_allgather.py`, `test_workload_collectives.py` | V01–V14 PASS | `921eb270`, `620f15b9` | F-0006 fixed; network-level semantics only | chunk ownership/rotation not modeled (no full data-semantic claim) |

## C3 — durable run authority

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C3 | critical | OPEN | `core/runs.py`, `core/paths.py`, evaluator/serving temp dirs | three run notions; timestamped dirs; no verify/reproduce | `RunBundle` + `verify-run` + `reproduce` owed (P2, A6) | — | — | `39f50578` (atomic init/lock only) | — | no durable content-addressed run lifecycle |

## C4 — failure / concurrency safety

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C4 | critical | OPEN | — | no `tests/production/` fault/concurrency suite | P3/P4 owed | — | — | — | — | crash/concurrency not yet proven |

## C5 — production workload trust

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C5 | high | IN_PROGRESS | `docs/validation/PRODUCTION-WORKLOAD-MATRIX.md`, `validation/experiments/V01–V14` | no production-scale corpus | W0 micro-oracles exist (V01–V14); W1–W3 matrix drafted (PW1) | V01–V14 | harness green | `d21aed04`, `074a6db3` | workload matrix proposed | W1/W2/W3 model/serving/stress manifests not built |

## C6 — ASTRA numerical qualification

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C6 | high | OPEN | `backend/astra_machine.py`, `validation/harness` engines | ~30M-cycle dominant timing unexplained; numerical validity NOT_ESTABLISHED | micro-oracle derivation owed (F-ASTRA-0001) | engine gate reports EXECUTES + NOT_ESTABLISHED | `astra_runtime` gate | — | ASTRA timing must not enter scientific comparison | qualification domains not established |

## C7 — serving qualification

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C7 | high | IN_PROGRESS | `serving/*`, `tests/test_full_pipeline.py`, `tests/test_serving_protocol.py`, `tests/conftest.py` | integration fixtures not vendored; two timing-flaky protocol tests | flaky tests made deterministic (reap-on-EOF; bounded quiescence); pytest-timeout; release-gate fails on release-critical skips | `test_serving_protocol.py` (35 passed ×3) | fast tier 3531 passed; gate fails on `.et`/ASTRA skips | `503c53a8` | — | serving `.et` fixtures still unvendored → integration domain explicitly UNSUPPORTED at the gate |

## C8 — reproducible release build

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C8 | high | IN_PROGRESS | `Dockerfile`, `Makefile`, `.github/workflows/release.yml` | container tag moving; several Docker deps clone HEADs; no lockfile/release manifest | `release-build` + manifests exist; pinning + `release-manifest.json` owed | — | `make release-build` on host | `48152452`, `1fea26ab`, `839cd3a9` | — | clean clone not run |

## C9 — live Studio product

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C9 | high | OPEN | `apps/studio` | fixture-only operation | FastAPI gateway + live sections owed | — | — | — | `docs/validation/STUDIO-AUDIT-AND-GAP-REPORT.md` | no live gateway |

## C10 — final release battery

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C10 | high | OPEN | — | battery not run at the RC SHA | owed | — | — | — | — | includes T0–T7 |

## C11 — final adversarial audit

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C11 | high | IN_PROGRESS | this program | stop-condition questions re-asked at seal | F-0007 found and fixed; others owed | — | — | `e9abab38` | — | full checklist not yet closed |

## C12 — production seal

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C12 | high | OPEN | `docs/production/PRODUCTION-SEAL.md` | seal only at full closure | owed | — | — | — | — | verdict currently NOT READY |

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
