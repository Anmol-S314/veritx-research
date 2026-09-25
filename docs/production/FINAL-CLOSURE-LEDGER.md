# VERITX Final Closure Ledger

Single ledger for the production-closure program. Status values:
`OPEN`, `IN_PROGRESS`, `CLOSED`, `UNSUPPORTED`, `DEFERRED_NONBLOCKING`.

Authority is source + tests + runtime output, never this document. Where a
row says CLOSED, the commit and the gate are named. `docs/production/CLOSURE-PLAN.md`
remains the earlier narrative; this file is the program ledger.

Release candidate under audit: baseline `2521d713`, inherited branch point
`bd6be628`. The R1–R5 closure commits begin at `d3240814` (R1.1) and the
current tip is `552a68d0`; R6 freezes one exact SHA after this ledger and the
seal are refreshed. Verdict: **NOT READY** (see `PRODUCTION-SEAL.md`).

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
| C6 | high | CLOSED | `backend/astra_machine.py`, `third_party/astra-sim/extern/network_backend/booksim2/Booksim2Fabric.hh`, `tests/test_astra_timing_oracle.py` | ~30M-cycle dominant timing; then no independent per-domain oracle | F-ASTRA-0001 fixed the 1M-cycle quantization; R2 adds a closed-form model M oracle: compute exact, ring `comm = 1010*2(N-1)+10` exact for N=2/4/8(held-out)/16 and additive over rounds | `test_astra_timing_oracle.py` (13, real binary) | exact equality on the release binary | `a4f7da62`, `34a37b8b` | F-ASTRA-0001, F-ASTRA-0002 | absolute latency NOT_ESTABLISHED (F-ASTRA-0002: comm payload-insensitive below 64 KiB); P2P/INSTANCE/MOE not established |

## C7 — serving qualification

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C7 | high | CLOSED | `backend/canonical_serving.py`, `backend/serving_round.py`, `tests/test_serving_*.py`, `docs/validation/SERVING-QUALIFICATION.md` | integration fixtures not vendored; independent oracle and runtime parallelism qualification missing | deterministic Chakra fixtures (`gen_serving_chakra_fixtures`, R1.1); independent scheduling oracle (R1.2); runtime EP ledger gates (R1.3); multi-instance liveness (R1.4); domain statuses (R1.9) | `test_full_pipeline.py` (no skips), `test_serving_fixture_provenance.py`, `test_serving_scheduling_oracle.py`, `test_serving_ep.py`, `test_serving_multiinstance_liveness.py`, `test_serving_tp_groups.py`, `test_serving_dp.py` | fast tier green; live TP/DP gates gated by `VERITX_LIVE_SERVING` | `d3240814`, `7e14bfdc`, `6212e185`, `b8ad1b47`, `15f0d295` | release-critical `.et` skip resolved | absolute hardware latency PARTIAL (declared model only) |

## C8 — reproducible release build

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C8 | high | CLOSED | `Dockerfile`, `Makefile`, `scripts/check_dockerfile_pins.py`, `scripts/classify_binary_reproducibility.py`, `docs/production/REPRODUCIBILITY.md` | container tag moving; Docker deps cloned HEADs; base image unpinned; binary bit-reproducibility unknown | base image pinned by digest (`ARG UBUNTU_IMAGE`); clones pinned by commit; pin guard now covers `FROM`; binaries classified SCIENTIFICALLY_EQUIVALENT_NON_BIT_REPRODUCIBLE (`.text` byte-identical) | `test_release_manifest_binds_the_release_to_its_facts`, `test_release_dockerfile_clones_are_pinned` | T6 clean clone + guard green | `69bda89c`, `ce05c4bc` | F-0008 | apt/pip not snapshotted (recorded, not bit-reproducible OS); clean clone not re-run at the R5 tip |

## C9 — live Studio product

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C9 | high | IN_PROGRESS | `veritx_dse/gateway/`, `apps/studio` | fixture-only operation | gateway live for design→compile→evaluate: immutable revisions, DesignView/CompilationView, revision_id continuity, typed HTTP error taxonomy; Runs/Trust live in React | `test_gateway.py`, `test_gateway_errors.py`, `test_gateway_revisions.py`, `apps/studio/tests/test_studio_contract_v2.py` | gateway + Studio contract green | `d789c4da`, `dd46efcc`, `e6faad7c` | latent `compilation_view` regression fixed | React Design/Verify/Evaluate/Optimize still fixture-backed; no guided v3 design deriver; no browser E2E |

## C10 — final release battery

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C10 | high | IN_PROGRESS | `.github/workflows/release.yml`, `validation/harness/engines.py` | battery run at one frozen SHA | T0–T4 green; T6 clean clone green at `c759b84b` (not re-run at the R5 tip); Studio contract added to the fast-gate; R6 will freeze one SHA | — | fast tier 3607 passed / 7 skipped at `552a68d0`; harness V01–V14 | `c759b84b`, `e6faad7c` | — | C10.3 broader matrix (MoE/multi-instance serving) owed; no browser E2E; final SHA moves with each docs commit |

## C11 — final adversarial audit

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C11 | high | IN_PROGRESS | this program | stop-condition questions re-asked at seal | F-0007 (window), C1.5 (toolchain), F-0006 (ALLGATHER), F-ASTRA-0002 (quantized comm), the `compilation_view` method/field regression, and the silent BookSim-skip/developer-local-path hermeticity gaps found and fixed; route/producer/evidence/VC/admissibility/run-integrity/concurrency audits done | regression per fix | fast tier green | `e9abab38`, `839cd3a9`, `ce05c4bc` | — | independent adversarial audit of the R1–R5 changes not yet run by a second party; clean-clone identity not re-proven at the R5 tip |

## C12 — production seal

| id | severity | status | source | root cause | implementation | tests | runtime gate | commit | historical claims affected | remaining limitation |
|----|----------|--------|--------|-----------|----------------|-------|--------------|--------|---------------------------|----------------------|
| C12 | high | IN_PROGRESS | `docs/production/PRODUCTION-SEAL.md` + all C13 outputs | seal only at full closure | all required C13 docs exist; seal refreshed with the R1–R5 facts; verdict NOT READY | — | — | this program | — | C9 frontend flow, C10.3 matrix, R6 freeze remain; verdict stays NOT READY |

---

## Stop conditions currently active

The release is **NOT READY** because these conditions remain open:

- the React Design/Verify/Evaluate/Optimize flow is still fixture-backed
  (the gateway is live; the frontend wiring and a guided v3 design deriver
  are owed) (C9);
- no browser end-to-end test exists (C9/C10);
- the C10.3 broader production workload matrix (MoE / multi-instance
  serving) is not run end-to-end at one frozen SHA (C10);
- ASTRA absolute latency is honestly `NOT_ESTABLISHED` (F-ASTRA-0002) and is
  excluded from scientific claims (C6);
- the clean clone has not been re-run at the R5 tip, and no exact RC SHA is
  frozen yet (R6);
- `apt`/`pip` are recorded but not snapshotted (R4.3).

Closed since the previous ledger revision: C6 (independent ASTRA timing
oracle), C7 (serving fixtures, scheduling oracle, runtime TP/DP/EP,
multi-instance liveness), C8 (base-image digest pin, reproducibility
classification), and the release-critical serving `.et` skip. The stale
"two canonical authorities" and "clean clone not qualified" entries were
already closed in the C2/C8 tables and are removed here.

No stop condition is currently *violated* by a passing false result: the
conservation, route, producer and admissibility gates are all fail-closed
and green.
