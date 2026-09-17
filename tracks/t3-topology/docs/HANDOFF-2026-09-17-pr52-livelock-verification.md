# HANDOFF — PR5.2: multi-instance livelock verification + permanent regressions

**Date:** 2026-09-17 · **Branch:** `epic/booksim-forward-port` · **HEAD:** `f53c92bd` (local, unpushed)
**Suite:** 962 passed, 1 skipped (960 → 962)
**Primary deliverable:** `docs/ROOT-CAUSE-multi-instance-livelock.md` — read that first.

## What PR5.2 was directed to do

Reproduce the historical multi-instance serving livelock under the PR5.1
liveness instrumentation, produce a root-cause document (earliest violated
invariant), and freeze the exact configurations as permanent regressions.
Fix-first was explicitly forbidden; a timeout/round-guard was explicitly
disallowed as "the fix."

## Result: the root cause was already fixed — now it is *proven* fixed

`db61a633` (2026-09-03, pre-dating PR5) fixed the livelock. PR5.2 verified
that claim with fresh runs under the liveness probe and pinned it:

| Historical config | Historical symptom | Today (fresh run, `83734c78` tree) |
|---|---|---|
| `single_node_moe_dp_ep_instance` (DP/EP) | quorum never fills, 300 s silent | exit 0; **both** instances retire (TTFT 19.17 / 25.77 ms) |
| `single_node_4_instance_2TP` | 1/3 requests, only instance 0 | exit 0 ~3.7 s; **all four** instances retire |

**Earliest violated invariant** (full derivation in the root-cause doc):
*completion evidence must retire work on the instance that owns it, and every
instance must eventually receive a scheduling round.* `controller.parse_output()`'s
sys-0 bias broke the first half; the round loop had no fallback for the second.
Compounding: echo retirement of unsent DP-pending batches, and round-robin
starvation of idle-not-done instances.

## Tests added (the regressions)

`dse/tests/test_full_pipeline.py`:

- `test_livelock_regression_dp_ep_both_instances_served`
- `test_livelock_regression_4_instance_2tp_all_served`

Anti-livelock assertion: `_assert_every_instance_served(csv, {expected})`
requires every expected instance id to appear in the per-request CSV's
`instance id` column. **`total requests >= N` was deliberately NOT used** — it
passes vacuously while instances 1..N-1 starve, which is exactly why the
original failure needed 300 s of silence to notice. Gated on the vendored
LLMServingSim tree + `AstraSim_BookSim2` binary like the existing serve tests
(skip cleanly when absent). Runtime ~5.4 s both.

## PR5.1 evidence machinery used

The probe (`serving/core/liveness.py`) was wired into the loop before these
runs; both runs progressed, so no `NO_USEFUL_PROGRESS` report fired (correct
behavior — reports attach to failure paths or `VERITX_LIVENESS_DUMP` only).
The probe's field definitions/classification rules are unchanged from
`HANDOFF-2026-09-17-liveness-observability.md`; nothing new was discovered
in the serving loop this round beyond what the archived issue recorded.

## Gate verdict for PR6

Per the review's hard gate — *do not proceed to PR6 until the real historical
configuration terminates because the root cause was fixed* — **PR6 is
unblocked**: both configs terminate, the root cause is documented, and the fix
is regression-pinned. A regression failure now (not a timeout) is the signal
that the invariant regressed.

## Unresolved semantics (unchanged + one note)

1–4: carried from the PR5 handoff (`docs/HANDOFF-2026-09-17-pr5-protocol-fixture.md`).
5. **Soak-vs-wall-clock**: PD 3-req soaks need ≥300 s timeouts (issue note:
   heartbeat prints only at sim-1s boundaries — silence ≠ no-progress). PR6
   goldens must not size timeouts off wall-clock alone; the probe's
   scientific-state fingerprint is the right stall detector.

## Next (awaiting review authorization)

PR6 — serving → BookSim vertical slice: `ExperimentSpec(mode=serving)` →
immutable run → LLMServingSim session (PR5 client) → per-request results.
Goldens: single-instance trivial + multi-instance trivial. Success = all
requests retire + terminal state validated, not exit 0.
