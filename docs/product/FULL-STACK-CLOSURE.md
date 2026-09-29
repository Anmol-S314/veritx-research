# VERITX FULL-STACK FUNCTIONAL CLOSURE

Branch: `integration/studio-reconciliation`
Baseline SHA: `ec0f8deef3309dfce82a09b400e108baebb9e0ae`
Worktree at start: clean except untracked `.playwright-mcp/` (pre-existing browser-test artifact, not ours).
Full suite log: `/tmp/veritx-closure/pytest-full.log` (PID 129412).

Deferred v1.1 (NOT in scope): SimCCL/NCCL, MSCCL/TACCL, ns-3/SimAI,
SimCXL, FlooNoC, m4, Perfetto, new InfrastructureGraph, new
ScenarioDefinition.

## Root-cause ledger (one row per root cause, not per failed test)

| ID | Category | Root cause | Failing tests | Fix commit | Status |
|----|----------|------------|---------------|------------|--------|
| RC-01 | product | `revision_preflight()` consumed `profile_id`/`profile_reason` before init; hand-rolled BookSim lowering duplicated planner truth; bare `except Exception` laundered bugs. FIXED Wave 1: planner-row support/readiness + adapter's own prepare() for profile, typed catches, pin-verifying producer gate. | tests/test_closure_phase1_preflight.py | — | FIXED |
| RC-02 | product | single boolean mixed support with readiness (`supported` reused as execution gate). FIXED Wave 1: support/readiness split, derived compat booleans for Studio, submit refuses only UNSUPPORTED (BLOCKED rows belong to the executor). NOTE: validation.py:113 was a recon false positive (verbatim ledger projection, correctly untouched). | tests/test_closure_phase1_support.py | — | FIXED |
| RC-03 | federation | BookSim normalize never compared evidence parents (booksim_adapter.py:503); ASTRA never verified ids (astra_adapter.py:494); reproduce_ramulator returned {matched:False}. FIXED Wave 2: binding checks at normalize + outcome, Ramulator raises RunBundleError, PARTIAL reason proven by test. Live-backend confirmation pending Wave-2b battery. | tests/test_closure_phase2_trust.py | — | FIXED (pending live confirm) |
| RC-13 | product | Product compare now returns COMPARABLE/NOT_COMPARABLE/MODEL_DIFFERENCE/MISSING_MEASUREMENT/QUALIFICATION_DIFFERENCE with differs axis + evidence ids, delta only when COMPARABLE. FIXED Wave 2. | tests/test_closure_phase2_compare.py | — | FIXED |
| RC-04 | BookSim | CORRECTION: standalone BookSim multi-class V3 support ALREADY EXISTS (LogicalMessageArtifactV3, PhysicalTrafficArtifactV3, class-aware trace rendering, class-aware VC admission, per-class expected flits, CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1). Remaining work is NOT implementation: live clean-producer confirmation (battery pending) + any genuinely unsupported topology/VC envelope. Legacy simulation/booksim.py superseded but still used by presets/meshdor (track separately). | test_multiclass_optimization_hard_gate + test_federation_booksim_baseline | — | OPEN (live confirm only) |
| RC-05 | ASTRA | rank==endpoint fallback exists but unreachable on qualified path (astra_execution.py:56,632-648); message-mode unqualified; multi-class/P2P/multicast refused by envelope; real-runtime tests need built AstraSim_BookSim2 binary | test_astra_* | — | OPEN (verify binary + execution) |
| RC-06 | Ramulator | no-memory-demand correctly refuses (no zero-latency path); multi-channel/CXL/REMOTE refused; normalize drops non-PASS (downstream must handle absence); AUDIT padding branch looks tautological (qualification/ramulator.py) | test_ramulator_* | — | OPEN (verify extension built) |
| RC-07 | serving | Path real; strictness defects FIXED Wave 2: RequestMetric typed validation, corrupt-metric refusal, truncation fail-fast, unknown-comm_type refusal. Fake-fidelity investigated: no false pass. Live-ASTRA serving tests pending Wave-2b battery. | tests/test_closure_phase2_serving.py | — | FIXED (pending live confirm) |
| RC-08 | optimization | `required_questions()` gives execute-once-per-question ✓; candidate adoption is draft→explicit-compile ✓; SUSPECT: Pareto eligibility may demand network `performance_result_id` even for non-network studies (result.py:1240-1290 — verify); requirement applicability vacuous-pass smell (requirements.py:673-690) | test_federated_optimizer, test_multi_fidelity_objectives, test_p2_* | — | OPEN |
| RC-09 | gateway | `ErrorCode.INTERNAL_ERROR` used but never imported (NameError); legacy raw HTTPException 400s; alias undocumented. FIXED Wave 1: import + typed INVALID_INPUT + alias comment. | tests/test_closure_phase1_gateway.py | — | FIXED |
| RC-14 | tests | refusal-wording drift: certified_admission/evidence_admissibility tests expect BACKEND_UNAVAILABLE where code now adjudicates UNSUPPORTED (v1-fixture vs v2 gate). Pre-existing (in baseline 60); resolve after Phase-2 rebuild shows true producer states. | test_certified_admission, test_evidence_admissibility | — | OPEN |
| RC-10 | Studio | no dead buttons found; fixture display confined to /offline and labelled; risk: presence-fallback shows install-presence as runtime state (index.tsx:909); Playwright e2e needs live gateway | test_studio_contract_v2 | — | OPEN |
| RC-11 | compiler | adaptive path has no bundle/certifier path (canonical.py:~430, fabric_compiler.py:119); DEADLOCK_FREE CDG diagnostic runs outside _SEMANTIC_ERRORS guard → crash instead of FAIL (certificate.py:296-300); _provenance swallows via bare except (compile_result_view.py:~607) | test_certificate_failclosed + adaptive tests | — | OPEN |
| RC-12 | optimization | Submit boundary fixed Wave 1 (BookSim binary demanded only for network studies). NOT YET FIXED end-to-end: RealCandidateEvaluator still requires binary (EvaluationError on None) and non-network Pareto is blocked by network proof assumptions (see review). Mark fixed only after ASTRA-only/Ramulator-only COMPLETE. | test_closure_phase1_support.py (strengthen: require COMPLETED) | — | OPEN (submit only) |
| RC-13-DUPLICATE-REMOVED | see row 19 (FIXED Wave 2). The application/comparison.py raises are retained deliberately as the forgery-verification layer. |

## Recon lanes (workflow 69517230)

compiler, booksim, astra, ramulator, serving, federation, product,
optimization, gateway, studio — all read-only scouts, reports pending.

## Phase log

- Phase 0 started 2026-09-28: state frozen, full suite launched, recon fanned out.
- Recon wave 1 done (8/10): compiler, booksim, astra, ramulator, federation, optimization, gateway, studio. serving + product lanes timed out → wave 2 retry (workflow 23b7d560) with narrowed scopes.
- Recon wave 2 done (2/2): serving + product. All 10 lanes closed.
- Baseline suite (no backend env): 60 failed / 4891 passed / 26 skipped. Root causes: (a) gateway called missing ProductService.revision_diff (5 tests) — FIXED + committed; (b) shipped BookSim binary manifest records source_dirty:true (built from dirty tree) so producer never pins -> all real-execution tests BLOCKED (fix = Phase 2 clean rebuild); (c) VERITX_BOOKSIM_BIN unset in ad-hoc runs (CI sets it).
- Committed + pushed 952b996f (Phase 1) to origin AND github. Tree clean.
- Wave 2 fanned out (workflow 079a2e93): rebuild worker (clean BookSim/ASTRA/Ramulator rebuild + re-pin + real-backend tests), federation-trust worker (transplant checks + reproduce parity + PARTIAL reason), serving worker (fail-closed strictness), compare worker (RC-13 verdicts).
- Wave-2b manifest worker produced planning text instead of results — delegation failed, executed directly instead. BookSim force-rebuilt from clean source (bit-identical bytes, toolchain parity proven); all 3 manifests rewritten dirty=false @ 6b336fc0; producer probe PINNED OK; Ramulator ext rebuilt for cpython-314 (was stale 312). Live battery running (/tmp/veritx-closure/pytest-live-battery.log).
- FOREIGN STASH (resolved): worker stash-pop applied a parked foreign stash → 11 conflicted files; kept-ours verified byte-identical to HEAD (zero worker work lost); application/compile.py re-removed (suite mandates absence). Workers steered off stash/checkout/clean.
- UNREVIEWED COMMITS (7, same identity): capability truth, synthesis adapters, evidence cache, energy fidelity, vocabulary widening, studio scientific-value — substance follows mission laws; adopted pending full-suite arbitration. Future specs forbid git commit/push.
- QUARANTINE (superseded by the above adoption path): /tmp/veritx-quarantine-20260928 retained as backup.
- SERVING CAMPAIGN 01: runner + first numbers (dense-4xTP2, moe-tp2ep2 COMPLETED 8/8; TP1 typed refusal; mixed-64 scheduler stall recorded). Campaign scope violation (astra/serve_canonical edits) adopted after review — the serving class envelope is necessary. OPEN: mixed-64 stall needs typed INFEASIBLE/INCOMPLETE with partials preserved.
- UI CLEANUP (6 lanes + 3 routed fixes): rail, overview hierarchy, evaluate collapse, optimize disclosures, synthesize list. Verified via screenshots + tsc + vitest + build.
- Wave 1 implementation fanned out (workflow 24df15e3): product-service worker (preflight + support/readiness + RC-12), exceptions worker (backend+application typed catches), gateway worker (ErrorCode import + typed 400s), recipe scout (rebuild commands).
