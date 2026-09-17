# HANDOFF — Phase 6: PR7 analytical slice (congestion-aware + unaware)

**Date:** 2026-09-17 · **Branch:** `epic/booksim-forward-port`
**Prior gate:** Phase 5 (1038 passed, 1 skipped)
**Next permitted:** Phase 7 (semantic-compression review — no new features)

## What landed

The analytical serving slice: `ExperimentSpec(mode=serving)` with
`serving.network_backend="analytical"` now runs end-to-end through the
PR6 slice runner, with the frontend/engine choice recorded as data and
a backend-aware fabric-activity gate. One runner, backend as data —
no second slice, no shared-loop fork (semantic compression: the
copy-paste of `run_serving_experiment` was the smell to avoid).

### 1. PR7a — frontend inspection (STOP-risk resolved)

- Both analytical frontends (`AnalyticalAstra` congestion-aware,
  `AnalyticalAstraUnaware` congestion-unaware) already carry the VeritX
  interactive protocol: `pass [ts]` / `done` (non-terminal) / `exit` /
  bare-path reload, `Waiting`-terminated replies, `[workload] sys[N]
  finished, X cycles, exposed communication Y cycles.` output lines —
  the exact wire format `controller._COMPLETION_RE` parses. Both share
  `CommonNetworkApi`; they differ only in transmission mechanics
  (chunk injection vs. computed-delay + `sim_schedule`).
- Residual delta (harmless on the live wire): the **aware** frontend
  supports `load <p>` + `run` with per-rank `.et` existence checks; the
  **unaware** one treats any non-command line as a bare path applied to
  all ranks. The serving loop only ever sends bare paths / pass /
  done / exit (`__main__.py` `_issue` sites), so both are served by the
  one loop. Empirically proven by the multi-instance unaware golden.
- §7 STOP condition ("analytical frontends require incompatible serving
  semantics") is **resolved empirically**, not waived.

### 2. PR7b — selection as data + backend-aware fabric gate

- `core/serving.py::engine_identity_from_binaries(serve_binaries)` —
  pure mapping from preflight-resolved binary paths to
  `{network_engine: congestion_aware|congestion_unaware,
  engine_selected_by: topology_dims}`. Identity follows the binary that
  executed (same principle as `binary_identity` sha256), never a
  re-derivation that could drift. First design (re-deriving dims from
  the fixture) was rejected: `_compute_network_dims` needs parallelism-
  resolved instances, and duplicating the resolve = copy-paste.
- `experiment_serving.py::check_fabric_activity(evidence, backend)` —
  booksim requires `max_retired_flits >= 1`; analytical requires
  `coll_completes >= 1` (flit/TOPO ledger lines are BookSim-frontend
  artifacts; `COLL_SUBMIT`/`COLL_COMPLETE` come from the shared ASTRA
  core `Workload.cc`, so analytical runs emit them). Replay masquerade
  stays impossible: the loop cannot see COLL_COMPLETE without the
  backend's workload engine running.
- Slice boundary (`run_serving_experiment`) now accepts
  `network_backend in (booksim, analytical)`; booksim still demands
  `cycle_accurate=true`. `mode_for_backend`/`fidelity_for_mode` already
  covered analytical (`REAL_SIMULATION` / `ANALYTICAL_ESTIMATE`) — used
  as-is. Verdict stamps `network_engine` + `cluster` into the result.
- `preflight_serve` needed **zero changes** (it already resolved
  analytical binaries by dims). `cmd_serve` needed zero changes.

### 3. Goldens (live, both green)

- **Golden-C** `TestGoldenAnalytical::test_single_instance_aware_golden`
  — `single_tp2_ep2` (dims `[2]`) → congestion-aware, 1 request, ~5 s.
  Asserts retirement, `REAL_SIMULATION`, `ANALYTICAL_ESTIMATE`, engine
  identity, COLL_COMPLETE evidence, binary sha256.
- **Golden-D** `...::test_multi_instance_unaware_golden` —
  `multi_dp_tp` (dims `[2,2]`) → congestion-unaware fallback, 2 reqs
  RR, ~13 s. Per-instance CSV ownership `{0,1}` asserted (rebinding
  bugs fail); proves the unaware bare-path reload reaches every rank.

## Rulings

- N-dim→unaware fallback: preflight's printed notice stays (human
  surface), machine-readable identity now travels in the result —
  "make it data" satisfied without touching the vendored frontend.
- `cycle_accurate` on analytical: refused by preflight
  (`UNSUPPORTED_EXECUTION_MODE`, existing behavior); specs pass
  `cycle_accurate=False` — meaningless for analytical, kept explicit
  so resolved specs stay honest.
- Fabric gate is backend-dispatched by evidence type, not strength-
  ordered: neither "flits" nor "collectives" is the stronger claim —
  they are the fabric-activity witness each backend can produce.

## Testing shape (TDD: red → green per cycle)

- Cycle 1: vocabulary + fabric dispatch + boundary (`TestAnalytical-
  Identity`, `TestAnalyticalFabric`, `test_analytical_reaches_preflight`)
  — 14 tests, pure/stubbed, <1 s.
- Cycle 2: live goldens per frontend (above).
- Cycle 3: ripple — spec/preflight/contract/unified subsets + full
  suite. Note: `test_serving_spec.py::TestServingRegistry` builds
  fixture paths CWD-relative; run the suite from repo root
  (`python3 -m pytest tracks/t3-topology/dse/tests -q`), not from `dse/`.

## Residuals (next phases, not bugs)

- Unaware frontend lacks `load`/`run` + per-rank `.et` gating; only
  matters if the serving loop ever grows `load`-shaped commands —
  recorded, not fixed (vendored-tree sync rules would apply).
- ns-3: still no binary; slice refuses it at the boundary (D1 remains).
- No exposed-communication honesty note on unaware results: the
  frontend emits `exposed 0` always (no congestion to expose). If
  comparisons later consume exposed cycles, unaware runs must be
  excluded by `network_engine` — now possible because it's data.
- F4/F5 assumption-class; F2/F3/F6/F7/F8 NOT_RUN — unchanged, their
  phases (10–13) are where the F-plumbing precursor lands.

## Gate

Full-suite result recorded in this session's final message; the PR7
subset (serving experiment/spec/metrics/preflight/contract/unified)
passed 93/95 with the 2 "failures" being the CWD artifact above
(10/10 from repo root).
