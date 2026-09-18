# HANDOFF — 2026-09-18: consolidation pass (review directive), Phase-15 CLOSE

**Branch:** `epic/booksim-forward-port`
**Directive:** reviewer's stop-all-new-work consolidation (6 items). Every
item executed; **no new-phase work was started.**

## 0. Scope discipline

The previous session had overrun into Phase 17/18 API surfaces while
Phase-16's units were still broken and the Phase-15 battery was owed. Per
the directive, this pass **only** consolidates: Phase-15 battery, Phase-16
units + stall semantics, API repairs, full suite, handoffs.

## 1. Phase 15 — CLOSED (acceptance battery PASS)

`veritx_dse.acceptance.phase15` — one machine-readable verdict, exit 0
only on PASS, backend mandatory (missing ext = FAIL, not skip):

```text
build        vendored-ext-present, ext-hash-recorded            PASS
drain        1R / 192R+32W / 4096R / 4096W / mixed / backpressure
             — generated == accepted == completed, outstanding == 0  PASS ×6
equiv        wrapper vs raw driver on the SAME trace: identical
             completion_cycles / avg_read_latency / row_hits/misses/
             conflicts                                          PASS
determinism  replay ×3 identical scientific metrics             PASS
behavior     row-locality sensitivity (friendly 2047 hits vs
             hostile ~0 hits, hostile slower)                   PASS
             bank-parallelism ISOLATED fixture: both arms
             conflict-heavy, 4 banks 75.0% faster               PASS
             clock probe: default-ratio deterministic;
             clock_ratio not exposed by v1 seam (documented)    PASS
integrity    capacity beyond preset refused (LoweringError,
             never wraparound); tampered trace refused before
             spawn (RamulatorError)                             PASS ×2
audit        canonical 640B == artifact == 8R+2W tx incl.
             declared padding                                   PASS

VERDICT: PASS (16/16, ~6s)
```

Fixture correctness matters (the bank test initially used wrong arithmetic
and "passed" vacuously): `ADDR_VEC_ORDER` is column-first, so row = i //
banks, bank = i % banks via the COLUMN level (i%4 × 64 tx × 64B). Both
arms conflict-heavy; the ONLY variable is bank count.

Evidence change demanded by review: `execute()` now EXPOSES
`generated_requests / accepted_requests / completed_requests /
outstanding_requests` in PASS metrics — a PASS verdict is independently
checkable, not a drain proof by assertion.

Also fixed en route: `simulation/ramulator.py` derived its own REPO with
an off-by-one (`tracks/` instead of repo root) — now imports the canonical
`core.paths.REPO` (one implementation per concept).

## 2. Phase 16 — units fixed (the blocker)

**The bug (review, confirmed):** legs mixed nanoseconds (compute), mem
cycles on the COMPUTE clock, raw network cycles, and raw seconds (rate
form) inside one `max()`.

**The contract now:** every leg is canonical **nanoseconds** before any
comparison — `cycles × its OWN dimension's clock` (compute/mem/net each
carry one; the mem clock is not the compute clock), rate form is SI
(bytes/s → ns ×1e9). A cycles-denominated leg with no binding for its
dimension raises (`cycles without a clock are not time`) — fail closed.
Test that pins it: `test_each_dimension_uses_its_own_clock` (mem 10c × 3.0
= 30ns while compute 100c × 2.0 = 200ns — the old code said 20ns).

## 3. Phase 16 — stall vs ownership separated (the semantics ruling)

Review: "critical-path owner can credit the full 20,000; but
**exposed_stall** should be 15,000." Implemented exactly:

```text
service_ns(d)          the declared leg
exposed(d)             OWNERSHIP: step span credited to longest leg(s)
exposed_stall_ns(d)    max(0, leg − max other leg) — counterfactual
                       savings if d were instantaneous
overlap_ns(d)          leg − stall (hidden part)
critical_path_owners   dimension(s) at the span
```

Reviewer's example pinned: 20,000ns compute + 5,000ns mem ⇒ ownership
20,000/0, **stall 15,000/0**. The old docstring contradiction (recorded
one formula, implemented another) is gone — both formulas are implemented
and each named for what it answers. Verdicts consume **stall** (the
savings question):

- `NETWORK_NOT_THE_BOTTLENECK`: net carried service but stall == 0
  (fully hidden) — the honest "don't spend on fabric" case
- tie in stall (or the all-stalls-0 ownership-tie fallback) incl. net →
  same verdict; sole stall leader → FABRIC_BOUND
- schema `veritx.timeline/2`; 38/38 tests updated to pin the corrected
  rulings (including the honest re-ruling of the old three-way
  "NOT_THE_BOTTLENECK" test: with a net-only step, eliminating the fabric
  alone saves 5,000ns → FABRIC_BOUND)

## 4. Phase 17/18 API — repaired before anything builds on it

All five review findings:

1. `compile_fabric` called the core without its required `evaluate`
   argument (guaranteed TypeError) → evaluate is now an explicit REQUIRED
   API parameter; without it: `INVALID` + reason (data, not crash). The
   API never invents a default evaluator.
2. `get_run` looked at `runs/<run_id>` but `Run.create` allocates
   `runs/veritx-runs/<run_id>` → corrected; verified against a REAL run.
3. `execute` reported a budget it never enforced → the declared budget is
   now written into the spec's `simulation.timeout_s` (parse-level
   enforcement) and the EFFECTIVE budget is echoed.
4. Host paths in outputs (`run_dir`, `bundle`, `manifest`) → stripped;
   the surface reports identity (ids/hashes/states) only.
5. `list_capabilities` advertised `SYNCHRONIZATION_BOUND`, which the v1
   timeline can never produce → removed (honest vocabulary only).

## 5. Full suite + lint (the owed gate)

```text
dse pytest   1388 passed, 1 skipped (known live-binary skip) — from repo
             root AND from dse/ (cwd-fragility eliminated, see below)
make lint    PASS (rc=0, 1389 collected)
```

Bonus root-cause fixed: two `test_serving_spec.py` registry tests passed
at repo root but failed from `dse/` — they re-derived registry paths
cwd-relatively (`Path(rel)`) while production (`serving_fixture`)
resolves REPO-anchored. Tests now go through the production seam; the
cwd-fragility class is gone, not patched around.

## 6. Handoffs un-gaslit

- `HANDOFF-2026-09-18-phase15-ramulator.md`: the stale "drain patch
  rejected / real runs INCONCLUSIVE / PASS awaits External frontend"
  standing verdict is now marked SUPERSEDED with the actual outcome
  (patch landed, certified live, battery PASS), original text preserved
  as history.
- This document is the consolidation record.

## Current phase ledger

```text
Phase 13  requirements-driven fabric compiler     LANDED (pre-existing)
Phase 14  canonical memory semantics              PASS (reviewer-closed)
Phase 15  Ramulator backend                       CLOSED — battery PASS
Phase 16  system timeline + bottleneck attribution CORRECTED (units +
          stall semantics), 38/38 pinned, full suite green
Phase 17/18 API + export surface                 REPAIRED (this pass);
          not declared "Phase 17 complete" — review first
Next:     reviewer verdict on 16/17 before any new phase
```

## Owed / residuals

- `clock_ratio` is not exposed by the v1 `execute()` seam — probed and
  documented in the battery (deterministic at default ratio). Exposing it
  is a small, honest follow-up when needed.
- The API/CLI surface (17/18) awaits review before being called complete.
- Studio v0 (19) deliberately skipped per user decision; MCP stdio server
  was scrapped (user directive) and removed.
