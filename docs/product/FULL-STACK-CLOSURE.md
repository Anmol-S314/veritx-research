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
| RC-03 | federation | BookSim normalize never compares evidence parents vs context (booksim_adapter.py:503); ASTRA normalize never verifies machine/workload-projection/namespace ids (astra_adapter.py:494); PARTIAL masks FAILED in _aggregate; network leg bypasses adapter prepare/execute; requirements blind to ASTRA/Ramulator; reproduce_ramulator returns {matched:False} vs RunBundleError elsewhere; serving has no registered adapter (plan UNSUPPORTED) | test_federation_kernel*, test_normalized_evidence, test_run_bundle | — | OPEN |
| RC-04 | BookSim | multi-class/split-VC refused (single-class trace replay only); legacy simulation/booksim.py superseded but still used by presets/meshdor; stale-dir/materialization + conservation gates OK | test_federation_booksim_baseline + lane tests | — | OPEN (verify binary built+pinned) |
| RC-05 | ASTRA | rank==endpoint fallback exists but unreachable on qualified path (astra_execution.py:56,632-648); message-mode unqualified; multi-class/P2P/multicast refused by envelope; real-runtime tests need built AstraSim_BookSim2 binary | test_astra_* | — | OPEN (verify binary + execution) |
| RC-06 | Ramulator | no-memory-demand correctly refuses (no zero-latency path); multi-channel/CXL/REMOTE refused; normalize drops non-PASS (downstream must handle absence); AUDIT padding branch looks tautological (qualification/ramulator.py) | test_ramulator_* | — | OPEN (verify extension built) |
| RC-07 | serving | path is real (Batch→plan→stage→qualify→spawn ASTRA→ledger→evidence→normalize); TTFT/completion pass-through, TPOT deliberately absent ✓. Defects are strictness-level: RequestMetric has no native validation (canonical_serving.py:550); non-numeric metric silently dropped (serving_normalization.py:92-93); ledger parser skips non-matching lines silently (serving_round.py:802); unknown comm_type → None kind (serving_round.py:786-788); fake backend hardcodes ledger values; REPLAY_ONLY fixture skips digest gate | test_serving_dp + serving tests | — | OPEN |
| RC-08 | optimization | `required_questions()` gives execute-once-per-question ✓; candidate adoption is draft→explicit-compile ✓; SUSPECT: Pareto eligibility may demand network `performance_result_id` even for non-network studies (result.py:1240-1290 — verify); requirement applicability vacuous-pass smell (requirements.py:673-690) | test_federated_optimizer, test_multi_fidelity_objectives, test_p2_* | — | OPEN |
| RC-09 | gateway | `ErrorCode.INTERNAL_ERROR` used but never imported (NameError); legacy raw HTTPException 400s; alias undocumented. FIXED Wave 1: import + typed INVALID_INPUT + alias comment. | tests/test_closure_phase1_gateway.py | — | FIXED |
| RC-14 | tests | refusal-wording drift: certified_admission/evidence_admissibility tests expect BACKEND_UNAVAILABLE where code now adjudicates UNSUPPORTED (v1-fixture vs v2 gate). Pre-existing (in baseline 60); resolve after Phase-2 rebuild shows true producer states. | test_certified_admission, test_evidence_admissibility | — | OPEN |
| RC-10 | Studio | no dead buttons found; fixture display confined to /offline and labelled; risk: presence-fallback shows install-presence as runtime state (index.tsx:909); Playwright e2e needs live gateway | test_studio_contract_v2 | — | OPEN |
| RC-11 | compiler | adaptive path has no bundle/certifier path (canonical.py:~430, fabric_compiler.py:119); DEADLOCK_FREE CDG diagnostic runs outside _SEMANTIC_ERRORS guard → crash instead of FAIL (certificate.py:296-300); _provenance swallows via bare except (compile_result_view.py:~607) | test_certificate_failclosed + adaptive tests | — | OPEN |
| RC-12 | optimization | `submit_optimization` calls `_require_backend()` unconditionally (service.py:2785, 1428-33) → BookSim binary demanded even for ASTRA-only/Ramulator-only studies | test_optimization_capabilities + new | — | OPEN |
| RC-13 | product | Compare raises COMPARISON_INCOMPATIBLE instead of returning NOT_COMPARABLE / MODEL_DIFFERENCE verdicts (application/comparison.py) | comparison tests + new | — | OPEN |

## Recon lanes (workflow 69517230)

compiler, booksim, astra, ramulator, serving, federation, product,
optimization, gateway, studio — all read-only scouts, reports pending.

## Phase log

- Phase 0 started 2026-09-28: state frozen, full suite launched, recon fanned out.
- Recon wave 1 done (8/10): compiler, booksim, astra, ramulator, federation, optimization, gateway, studio. serving + product lanes timed out → wave 2 retry (workflow 23b7d560) with narrowed scopes.
- Recon wave 2 done (2/2): serving + product. All 10 lanes closed.
- Baseline suite (no backend env): 60 failed / 4891 passed / 26 skipped. Root causes: (a) gateway called missing ProductService.revision_diff (5 tests) — FIXED + committed; (b) shipped BookSim binary manifest records source_dirty:true (built from dirty tree) so producer never pins -> all real-execution tests BLOCKED (fix = Phase 2 clean rebuild); (c) VERITX_BOOKSIM_BIN unset in ad-hoc runs (CI sets it).
- Committed 0ecce592 (revision_diff fix + closure ledger + .playwright-mcp ignore). Tree clean.
- Wave 1 implementation fanned out (workflow 24df15e3): product-service worker (preflight + support/readiness + RC-12), exceptions worker (backend+application typed catches), gateway worker (ErrorCode import + typed 400s), recipe scout (rebuild commands).
