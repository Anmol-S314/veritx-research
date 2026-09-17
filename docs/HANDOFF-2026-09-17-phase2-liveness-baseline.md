# HANDOFF — Phase 2: liveness evidence (T4 + T5)

**Date:** 2026-09-17 · **Branch:** `epic/booksim-forward-port`
**Suite:** 1003 passed, 1 skipped · **Gate: PASS** · **Next permitted: Phase 3 (T6)**

No scheduling behavior changed in this phase. One defect found and fixed
in instrumentation (scope bug, below) — caught by a live smoke run, not
by unit tests, which is recorded as a lesson.

## Files changed

- `third_party/llmservingsim/serving/__main__.py`
  - `_issue(p, controller, cmd)` closure inside `main()`: the single
    backend-send seam. All 14 send sites routed through it; the only
    remaining `controller.write_flush(` is the seam body. Same strings,
    same order — recording only.
  - Removed the now-redundant `_lv_last_cmd = pass_msg` one-off (single
    writer invariant: init + seam).
  - Opt-in terminal `[LIVENESS] final:` render under
    `VERITX_LIVENESS_DUMP` (default off; pure observation print).
- `tracks/t3-topology/dse/tests/test_serving_liveness.py`
  - `TestCompleteLogicalCommand` (3 tests): verbatim workload-path
    preservation, repeat detection on full commands, seam-structure pin
    (exactly one raw send; exactly two `last_command` writers).

## Tests run

- New T4 tests + full DSE suite: **1003 passed, 1 skipped**.
- Live smoke (analytical 1-req): exit 0, metrics normal.
- Runtime seam proof: `last_command` captured a full workload path
  (`.../workload/RTXPRO6000/meta-llama/Llama-3.1-8B/instance0_batch69/llm`).

## T5 baselines (replay-only = scheduler-side evidence, not network proof)

Both historical configs, `--network-backend booksim --booksim-replay-only`,
`VERITX_LIVENESS_DUMP=1`, per-request CSV retirement check.

**DP/EP (`single_node_moe_dp_ep_instance`, 2 reqs):** exit 0 ·
344 rounds · terminal `USEFUL_PROGRESS`, `rounds_unchanged: 0` ·
`retired_requests: 2`, CSV instances `{0, 1}` · TTFT 15.57 / 25.77 ms ·
backend mode replay-only, fidelity TRACE_REPLAY.

**4-instance TP2 (`single_node_4_instance_2TP`, 4 reqs):** exit 0 ·
256 rounds · terminal snapshot `SIM_TIME_ADVANCING_NO_REQUEST_PROGRESS`
with `retired_requests: 3` (terminal transient — final CSV shows 4/4) ·
CSV instances `{0, 1, 2, 3}` · terminal `last_command` =
`.../workload/RTXPRO6000/meta-llama/Llama-3.1-8B/instance1_batch103/llm`
(dispatch command recorded, not bare pass).

Neither run fired a stall dump mid-run (correct: both progressed).
No timeout threshold was used as a fix; the spin-abort backstop is
untouched.

## Known residuals

- Healthy runs emit exactly one liveness block (the terminal render);
  mid-run dumps fire only on non-`USEFUL_PROGRESS` rounds, by design.
- Terminal snapshot of a completing run may show a transient
  non-`USEFUL_PROGRESS` state (4-inst case above) — the CSV retirement
  count is the terminal truth, the snapshot is one round's observation.

## Newly discovered contradiction (fixed)

`def main():` at `serving/__main__.py:521` — the serving loop is
function-local, so the first version of the seam (module-level `global`)
recorded into a different variable and the probe kept `<startup>`.
Caught by the live smoke run (unit tests cannot see loop scope).
Fixed by making the seam a closure; runtime proof re-taken.
Lesson: instrumentation refactors in the serving loop require a live
smoke, not just unit green.

## Gate result: PASS

- [x] Classifications deterministic (synthetic tests per state, green)
- [x] Historical configs terminate for understood reasons (baselines above)
- [x] Per-instance progress evidence archived (this doc + CSV counts)
- [x] No timeout threshold used as the fix
