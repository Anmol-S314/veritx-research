# HANDOFF — Phase 15b-fix: drain-aware ReadWriteTrace (supersedes the 15b standing verdict)

**Date:** 2026-09-18 · **Branch:** `epic/booksim-forward-port`
**Prior:** Phase-15 handoff (same day), whose standing verdict (real runs
terminate INCONCLUSIVE) is retracted by this fix.

## Change

Vendored `readwrite_trace.cpp` (`VeritX:`-marked): request completion
callbacks drive `accepted/completed` counters; `is_finished()` = EOF **and**
drained; empty traces finish immediately; frontend stats
(`trace/accepted/completed/outstanding_requests`) registered. Independent
monotonic counters (a coalesced write can callback inside `send()`).

Coalesced writes count as completed via the independent
`num_write_reqs_coalesced` counter (T4 case: 125 served + 3971 coalesced
= 4096 accepted). Veritx `_reconcile` enforces
`served + coalesced == accepted`.

## Evidence

- Drain matrix on HBM3: empty/1-read/192R+32W/4096×3/4096W/mixed — all
  `outstanding == 0`; locality preserved (1-row: 4095 hits; 64-row: 4095
  conflicts, 17.7× gap).
- Live veritx test asserts PASS with conservation (was INCONCLUSIVE).
- Full suite: **1318 passed, 3 skipped, 0 failures** (2 skips = live
  backend, .so absent from clean tree by design); lint rc=0.

## Residuals

- Machine channel stays `stats.json` on disk (stdout capture truncates).
- External frontend still later, now for timing/coupling only — not drain.
- Interpreter binding caveat stands (build in target interpreter).
