# HANDOFF — Phase 4 (PR6): serving → real-BookSim slice

**Date:** 2026-09-17 · **Branch:** `epic/booksim-forward-port`
**Suite:** 1031 passed, 1 skipped · **Gate: PASS**
**Next permitted: Phase 5 (serving metric semantics)**

## What PR6 is

`veritx_dse.core.experiment_serving.run_serving_experiment(spec)`:
strict `ExperimentSpec(mode=serving)` → immutable run → supervised
LLMServingSim child → terminal-validated typed result. Real-simulation
only; replay/analytical refused at the boundary (available via CLI/PR7).

## Corrections applied (review-binding, from Phase-3 addendum)

- **Ownership:** slice supervises the process via `supervised_run`
  (session, timeout, group-kill, captured logs). It never speaks the
  backend protocol; `ServingBackendSession` untouched.
- **Two goldens:** A = single TP2/EP2 (fabric); B = multi DP/TP with RR
  routing (ownership + retirement under real sim).
- **Tripwire now:** `check_involved_dim_tripwire` fails runs whose submit
  vectors don't match topology dims, or multi-dim runs with no scoped
  vector. Broader policy stays in Phase 9.
- **Terminal truth** = CSV retirement + artifacts + process state.
  Liveness unused by the slice.
- **Replay** enters neither the slice (refused) nor goldens (gate).

## Goldens (live, in-suite)

- **A** (`single_tp2_ep2`, 1 req, ~30 s): SUCCEEDED · 1/1 retired ·
  REAL_SIMULATION · losses [] · coll_completes ≥ 1 · flits > 0 ·
  TTFT/TPOT typed ns · binary/cluster/dataset SHAs.
- **B** (`multi_dp_tp`, 2 reqs RR, ~200 s): SUCCEEDED · 2/2 retired ·
  CSV instances exactly `{0, 1}` (rebinding bugs fail here) ·
  tripwire passed · fabric present · REAL_SIMULATION.

## Negatives (fast, faked supervision + boundary)

Replay/analytical/stochastic/unknown-fixture specs refused (SpecError);
preflight failure → CANCELLED evidence; nonzero/timeout/mismatch/
missing-CSV → FAILED with named reasons.

## Design points

- `ServingSpec` strict; `serving` block required iff mode=serving;
  latency resolution gains only a null key (relational hash tests green).
- Cluster/dataset by registered ID (`core.paths` trusted registry);
  `serving_fixture` raises SpecError on unknown IDs.
- `_build_serve_cmd`/`_locate_serve_path` relocated to `core.serving`
  (single implementation); CLI keeps names as delegating wrappers —
  all contract tests pass unchanged.
- Seeds: deterministic single-seed required; serving consumes no seed
  (recorded, no flag exists) — stated, not hidden.
- Sim clock omitted from metrics (would need stdout parsing);
  TTFT/TPOT means in ns + request counts are the typed result.
  Clock vocabulary belongs to Phase 5.

## Residuals

- `SYSTEM_SIMULATION` vs `SYSTEM_SERVING_SIMULATION` naming (Phase 5).
- Stochastic serving refused until a seed mechanism exists.
- Sim-clock / ITL-list metrics deferred to Phase 5.
- Suite now ~7 min (two live goldens); goldens gated on binary+tree
  presence like all live tests.
