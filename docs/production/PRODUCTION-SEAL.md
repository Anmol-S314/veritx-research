# VERITX Production Seal

**Release decision: NOT READY**

This document is the release-seal report required by the production
program. It is written at each candidate; the verdict is `NOT READY`
until every seal condition is met.

## 1. Release candidate SHA

`prod/production-readiness`. The R1–R5 closure commits begin at `d3240814`;
the current (unfrozen) tip is `552a68d0`. The clean-clone qualification (T6)
was last run at code SHA `c759b84b` and has **not** been re-run at the R5
tip; R6 freezes one exact SHA and re-runs the battery (see
`FINAL-CLOSURE-LEDGER.md`). The branch is not tagged and `main` has not been
modified. A release tag must point at the exact audited SHA.

## 2. Base SHAs

| Ref | SHA |
|-----|-----|
| `origin/main` | `4be11e484aa81aa36799a9098f132f1eacfe2d2c` |
| `github/veritx-integrate` | `39a180ecc87c90241a674d59d1c4f14deda721bb` |
| `github/validation/b4-campaign` | `190d04f1` (F-0004 hardening + full campaign freeze) |

## 3. Authority map summary

See `AUTHORITY-MAP.md`. B1 (second compile authority) and B6 (shadow
`CompileRequest`/`migrate_design`) are CLOSED. Open blockers: B2
(`application/results.py` RT vocabulary), B3 (evidence admissibility is
now closed; the single producer admission rule remains), B4 (no build
manifest), B5 (timestamped run dirs), B7 (ValueError-rooted semantic
taxonomy).

## 4. Closed findings

| finding | severity | root cause | fix | regression test |
|---------|----------|------------|-----|-----------------|
| VC builder collapsed malformed/duplicate authoring into valid artifacts | high | `dict()`/set conversion before validation | `a0b934b6` | `test_vc_assignment.py` |
| Certificate converted any exception into a design verdict; `except Exception: pass` on PASS path | critical | broad exception handling | `8d61da35` | `test_certificate_failclosed.py` |
| Two `CompileRequest`/`migrate_design` definitions; older shadowed canonical | high | reclamation duplicate `a5b806fe` | `8c32ccc2` | `test_design_intent_identity.py` |
| Clock parse through binary float lost Hz above 2^53 | high | `float(str(text))` | `e7a85911` | `test_clock_parsing_exact.py` |
| `_validate_legacy_v1` called but undefined (NameError on legacy evidence) | high | reclamation dropped the function | `facf645b` | `test_evidence_admissibility.py` |
| Evidence accepted impossible documents (unknown/contradictory fidelity/transport) | high | content-only validation | `facf645b` | `test_evidence_admissibility.py` |
| Second compile authority `application/compile.py` reachable | high | unremoved legacy surface | `9eb7c2e6` | `test_application_service.py` |
| No single producer qualification rule; revision/cleanliness unchecked | high | split admission logic | `978a38ed` | `test_evidence_admissibility.py` |
| Build provenance was ambient git HEAD (binary built at A attributed to B) | critical | live `git rev-parse` | `43f55d94` | `test_build_manifest.py` |
| BookSim packet/flit counters unparsed and unenforced (`None`) | high | parser stubs | `03e50675` | `test_booksim_conservation.py` |
| Projection closure only checked missing fields, not undeclared ones | medium | partial closure check | `dc858a29` | `test_projection_closure.py` |
| Candidate identity was a truncated 16-hex hash | medium | `content_id(...)[:16]` | `85b7e5cf` | `test_optimization_identity_exact.py` |
| Empty optimizer domain created an illegal empty-patch candidate | medium | late failure | `85b7e5cf` | `test_optimization_identity_exact.py` |
| Authenticated evaluation read stale RT keys (`execution_transport`/`qualification`) | medium | stale vocabulary | `5d2a991b` | `test_p2_optimization_truth.py` |
| `application/results.py` mixed canonical and RT-vocabulary readers | medium | unmarked legacy | `c78e54af` | `test_results_legacy_boundary.py` |
| Certified path bypassed producer admission (unpinned → EVALUATED → CERTIFIED_PRODUCT) | critical | admission not enforced end-to-end | `a274d4b0` | `test_certified_admission.py` |
| Evidence did not bind which manifest/recipe qualified it; `reusable` was a second weak rule; reuse reader skipped `evidence_id` | high | provenance not persisted | `a274d4b0` | `test_evidence_admissibility.py` |
| Conservation accepted a missing trace-injected packet count | high | optional check | `a274d4b0` | `test_booksim_conservation.py` |
| Bare programmer `ValueError` could be laundered into a verdict (B7) | high | ValueError-rooted catch | `ff141c68` | `test_certificate_failclosed.py` |
| Legacy-reader reachability guard missed aliased imports | low | regex, not AST | `466c9fa8` | `test_results_legacy_boundary.py` |
| Two v2 compile orchestration implementations (drift risk) | high | duplicated derivation | `c70a1b9e` | `test_compiler_path_parity.py` |
| `core.runs` initial publication non-atomic; results RMW unlocked | high | `write_text`; no lock | `39f50578` | `test_run_core.py` |
| Environment contract contradiction (pyproject >=3.10 vs enforced 3.12) and missing `requirements.lock` | medium | inconsistent floor | `39f50578` | `test_run_core.py` |
| CI did not trigger on the production branch | high | missing branch glob + no release workflow | `1fea26ab` | `.github/workflows/release.yml` |
| Executed route realization was never observed (P0.10) | high | no dump render/compare | P0.10 commit | `test_route_observation.py`, real backend gates |
| Ring ALLGATHER over-transmitted by factor k (F-0006) | high | message_bytes used B, not B/k | `921eb270` | `test_collective_allgather.py`, V11 |
| Convergence window truncated concentrated multi-flit traces (F-0007) | high | window sized from packet count, not per-source flit horizon | `e9abab38` | `test_backend_booksim_projection.py`, V13 |
| Toolchain provenance recorded g++ while building with ambient CXX (C1.5) | high | manifest literal vs `$(CXX)` | `839cd3a9` | `test_build_manifest.py` |
| Collective vocabulary had 2–4 independent definitions (C2.2) | high | duplicated tuples/dicts | this program | `test_collective_vocabulary_has_exactly_one_authority` |
| ASTRA over-counted every collective step by 1,000,000 cycles (F-ASTRA-0001) | high | `run_cycles` quantized retired-packet draining | `a4f7da62` | engine gate `astra_runtime`; two-binary differential |
| ASTRA comm timing is quantized to a 1,000-cycle floor and payload-insensitive below ~64 KiB (F-ASTRA-0002) | medium | frontend `CHUNK=1000` stepping bills a full chunk per ring step | recorded + regression guard (not tuned) | `test_astra_timing_oracle.py` |
| `compilation_view` called `resolved_fabric.resolved_fabric_hash()` as a method, but it is a str field on the v3 `ResolvedFabric`; the whole `apps/studio` contract suite and fixture generation were broken and ran in no CI job | high | method-vs-field API drift | use `bundle.root_hashes()` (shim normalizes both); Studio tests added to the fast-gate | `apps/studio/tests/test_studio_contract_v2.py`, `test_gateway_revisions.py` |
| Four serving tests imported LLMServingSim from a developer-local path absent on a clean clone | high | hardcoded `/home/datavex/veritx-integration` | resolve the repo's own vendored package | serving suites |
| The real BookSim gates silently skipped in the release backend-gate (resolver only looked in `/tmp` scratch dirs); the ASTRA reference-binary differential was mis-classified as release-critical | high | developer-local resolver + wrong gate classification | resolve the built binary; a missing BookSim/ASTRA binary is now release-critical, the differential is not | `test_backend_booksim_execution.py`, `tests/conftest.py` |
| `generate_studio_fixtures` imports `application.product_evaluator`, which exists only on historical audit branches; committed compile fixture was stale | medium | cross-branch artifact | regenerate the compile fixture from the live path; offline-demo regeneration reported as unprovisioned | `apps/studio/tests/test_studio_contract_v2.py` |

Historical scientific findings F-0001 and F-0004 are FIXED in
`validation/FINDINGS.md`; F-0002 ACCEPTED.

## 5. Remaining limitations

- P0.10 claim is precise: runtime routing-function/table FIRST-HOP
  realization equivalence over the complete source x destination domain —
  stronger than static config checking, narrower than per-packet
  instrumentation. No flit path trace exists.
- The convergence window is the per-source injection horizon plus a
  fixed 1000-cycle drain margin (F-0007). The margin is a heuristic, not a
  physical bound; a workload needing more drain is refused by conservation.
- The v3 compile orchestration still re-sequences the derivation that the
  canonical compiler performs (hardware settings collapsed, sequencer not);
  there is no V2↔V3 identity parity test. Tracked as C2.1/A8.
- The collective vocabulary is now one authority (`workload/collectives.py`),
  imported by every workload layer; `workload/canonical.py` still spells its
  op-kind vocabulary inline (distinct fact, no schedule).
- Build manifests are local files, not a cryptographic trust root: a
  clean-clone CI must generate them and the release manifest must tie
  them to the tag. `release-manifest` covers BookSim and ASTRA; Ramulator
  is a vendored Python extension executed through `simulation/ramulator.py`
  (not the binary-manifest producer path), qualified by the engine gate
  (16/16) and its pinned vendored source.
- Run bundles are checksummed, atomic and path-independent, with
  `verify-run`/`reproduce` (C3). Legacy `core.runs.Run` and
  `core.paths.new_run_dir` still coexist and are not yet routed through the
  bundle lifecycle for evaluator/serving dirs.
- BookSim binaries built in two different directories are not bit-identical
  at the same source revision; classified
  `SCIENTIFICALLY_EQUIVALENT_NON_BIT_REPRODUCIBLE` (`.text` byte-identical,
  only DWARF paths/build-id differ; `scripts/classify_binary_reproducibility.py`).
  Each build's manifest binds its own binary sha.
- The Studio gateway is live for design→compile→evaluate with immutable
  revisions; Runs/Trust are live in React. Design/Verify/Evaluate/Optimize
  are still fixture-backed, there is no guided v3 design deriver, and there
  is no browser E2E. Offline-demo fixture regeneration needs
  `application.product_evaluator`, absent on this branch.
- Rebuilding a backend requires regenerating its build manifest
  (`make release-manifest`); the producer gate correctly refuses a binary
  whose manifest digest is stale (observed after the F-ASTRA-0001 rebuild).
- ASTRA timing is internally qualified under model M (compute exact, ring
  `comm = 1010*2(N-1)+10` exact for N=2/4/8/16 and additive over rounds).
  Absolute latency is NOT_ESTABLISHED (F-ASTRA-0002: comm is payload-
  insensitive below ~64 KiB), and P2P / multi-instance / MoE domains are not
  established, so ASTRA absolute timing must not enter a comparison.
- Serving integration now runs on deterministic tracked Chakra fixtures; the
  release gate no longer skips on their absence (R1.1). Absolute hardware
  serving latency remains PARTIAL (declared linear model only).
- The release base image is digest-pinned and Docker clones are pinned by
  commit; `apt`/`pip` are recorded but not snapshotted.
- The clean clone was last qualified at `c759b84b`; it has not been re-run at
  the R5 tip.
- Report files embed ephemeral scratch paths.
- `bash third_party/ramulator2/build.sh` fails silently (use `./build.sh`).
- Evidence schema v3 / prepared BookSim v5 / trace schedule v2 are
  incompatible with older fixtures by design; older persisted documents are
  refused, not migrated (see `SCHEMA-COMPATIBILITY.md`).

## 6. Schema / version matrix

See `SCHEMA-COMPATIBILITY.md` (owed). Version constants inventoried in
`AUTHORITY-MAP.md`; a formal matrix is not yet written.

## 7. Engine qualification matrix

| backend | role | independence | numerical validity |
|---------|------|--------------|--------------------|
| Embedded BookSim | canonical network execution engine | engine under test | qualified (F-0001 fixed) |
| Standalone BookSim | shared-engine differential | semi-independent | qualified |
| RTL / Verilator | independent execution engine | independent within RTL domain | established (R0 self-check) |
| Ramulator | memory engine / integration | independent | established (16/16) |
| ASTRA-Sim | runtime/integration | shares BookSim engine (not independent) | internally qualified under model M (compute + ring + multi-round); absolute latency **NOT_ESTABLISHED** |

The five categories are NOT "five independent engines".

## 8. B4 results by independence category

72/72 checks exact, 0 quarantined. Independent oracle checks
(`hand_calculated`, ring oracle), semi-independent shared-engine
(`standalone_booksim`), independent execution engines (RTL, Ramulator),
and ASTRA liveness (numerical validity excluded). Scope: network-level
ring semantics only; chunk ownership is not modeled.

## 9. Full regression results

- Fast DSE tier: `3607 passed, 7 skipped, 0 failed` (117 s) at `552a68d0`
  (up from 3563; the extra tests are the serving fixture/provenance,
  scheduling oracle, runtime EP, multi-instance liveness, ASTRA timing
  oracle and gateway taxonomy/revision suites).
- Studio contract suite: `7 passed, 3 skipped` (the skips are offline-demo
  fixture regeneration, unprovisioned on this branch).
- Validation pytest: `24 passed` (245 s).
- Validation harness: V01–V14 PASS, mutations CAUGHT, metamorphic PASS,
  engine gates PASS (ASTRA numerical internally qualified under model M),
  intervention SUPPORTED, 0 quarantined.
- Live-backend tier: green; the real BookSim/ASTRA gates now resolve the
  built binaries (previously the BookSim resolver only looked in developer
  scratch dirs and silently skipped).
- Certified optimization gate (C10.2): `test_real_grid_end_to_end` runs
  `Optimizer.optimize_certified` from the release build and asserts every
  selected/Pareto candidate is EVALUATED with an authenticated proof,
  satisfied constraints and a requirement report.
- Production fault/concurrency suite (`tests/production/`): green
  (real concurrency gates included in the live tier).

## 10. Failure-injection results

Implemented (`tests/production/test_failure_injection.py`): nonzero exit,
hang/timeout, malformed/partial output, post-preparation config/trace
tamper, foreign files in a reused run dir, post-finalize evidence tamper,
partial bundle, read-only destination. All end in a typed failure with no
evidence written. SIGKILL of the parent service is not exercised.

## 11. Concurrency results

Implemented (`tests/production/test_concurrency.py`): concurrent finalize is
idempotent; distinct bundles do not collide; concurrent identical real runs
share scientific identity with distinct run dirs; different runs differ.

## 12. Clean-clone results

RUN (C8/T6) at `c759b84b`, **not re-run at the R5 tip**. A `git clone` with no
prebuilt binaries builds BookSim, ASTRA and Ramulator from tracked source via
`make release-build`, writes both build manifests binding the release
revision with `source_dirty=false`, runs the fast tier, the real backend
gates, and the full validation harness. The clean clone's canonical compile
produces the same `resolved_fabric_hash` as the working tree. Findings:
F-0008 (ASTRA build invoked with `sh`) and a false astra_runtime FAIL from a
too-tight engine timeout (now 900 s). A build outside a git checkout records
no revision and `dirty=true`, so releases must build from a clone. R4
classifies cross-directory binary differences as
`scientifically-equivalent-non-bit-reproducible` (`.text` identical).

## 13. Performance / scale envelope

Not measured (`SUPPORTED-LIMITS.md` owed).

## 14. Security review

Not performed (`THREAT-MODEL.md` owed).

## 15. Reproducibility proof

Partial: source-only build of BookSim/ASTRA/Ramulator works and
`make release-build` writes build-time manifests for BookSim and ASTRA
(verified at resolve time). The release base image is digest-pinned and
Docker clones are pinned by commit. Missing: `apt`/`pip` snapshots (recorded,
not bit-reproducible) and a clean-clone re-run at the frozen RC SHA. See
`REPRODUCIBILITY.md`.

## 16. Known unsupported domains

- Certified-product admission theorem: profile CERTIFIED_BOOKSIM_* implies
  supervised transport, QUALIFIED fidelity, known/clean producer, exit 0,
  verified manifest, recipe == booksim2-fork/v1, observed route + dump
  digest.
- ASTRA absolute timing (NOT_ESTABLISHED, F-ASTRA-0002); ASTRA P2P /
  multi-instance / MoE timing domains not established.
- Serving absolute hardware latency (PARTIAL; declared linear model only).
- Reduce-scatter/all-gather chunk ownership/rotation (not modeled).
- Route realization beyond the first hop (the fork dumps first hops only).
- Injection faster than one flit per cycle per source (trace model limit);
  drain beyond the fixed 1000-cycle margin is refused.
- Studio Design/Verify/Evaluate/Optimize browser flow (gateway live;
  frontend wiring and a guided v3 design deriver owed).
- Offline-demo Studio fixture regeneration (`application.product_evaluator`
  absent on this branch).
- Durable run verification/reproduction (`verify-run`/`reproduce`) is
  implemented; legacy `core.runs` dirs are still outside the bundle
  lifecycle.

## 17. Dirty-tree status

The R1–R5 closure commits are committed on `prod/production-readiness`; the
only untracked paths are local agent tooling (`.agents/`, `.claude/`,
`skills-lock.json`) that are not part of the product.

## 18. Branch status

Historical branches untouched (no cleanup performed). `main` untouched.
`prod/production-readiness` was pushed to `github` at `b2600851`; the R1–R5
closure commits are local-only at the time of writing (tip `552a68d0`) and
are recorded in `FINAL-CLOSURE-LEDGER.md`. The exact RC SHA is frozen in R6.

## 19. Release decision

**NOT READY.** The scientific core (C1), authority collapse (C2.1–C2.3),
durable run bundles (C3), failure/concurrency safety (C4), the workload
corpus (C5), ASTRA internal timing qualification (C6), serving qualification
(C7), the release pinning/reproducibility classification (C8), and the live
gateway with revision continuity (C9) are in place and green. Remaining
blockers:

- The Studio React Design/Verify/Evaluate/Optimize flow is still
  fixture-backed; the gateway is live but the frontend wiring and a guided
  v3 design deriver are owed (C9).
- No browser end-to-end test exists (C9/C10).
- C10.3's broader production matrix (MoE / multi-instance serving) is not
  run end-to-end at one frozen SHA.
- ASTRA absolute latency is `NOT_ESTABLISHED` (F-ASTRA-0002), so ASTRA
  absolute timing must not enter a comparison.
- No exact RC SHA is frozen and the clean clone has not been re-run at the
  R5 tip (R6).

See `FINAL-CLOSURE-LEDGER.md` for the item-by-item state.
