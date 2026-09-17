# Root cause: multi-instance serving livelock ("only instance 0 ever scheduled")

**Status:** VERIFIED FIXED (fix pre-dates this document; this document is the PR5.2 verification + permanent record)
**Historical configs:** `single_node_4_instance_2TP.json` (4×TP2), `single_node_moe_dp_ep_instance.json` (DP/EP)
**Fix commit:** `db61a633` (2026-09-03) — *before* the PR5 protocol work; PR5.2's job was to verify the claim under real instrumentation and freeze it
**Issue archive:** `dse/archive/ISSUE-multi-instance-interactive-backend.md`
**Regression tests:** `dse/tests/test_full_pipeline.py::test_livelock_regression_dp_ep_both_instances_served`, `::test_livelock_regression_4_instance_2tp_all_served`

---

## 1. Symptom (historical, 2026-09-03)

- `single_node_4_instance_2TP`: only request #0 completed (on instance 0); requests
  routed to instances 1–3 never scheduled — stall at `0 reqs, Waiting: 1`. Matrix result 1/3.
- `single_node_moe_dp_ep_instance`: full livelock — `dp_pending` quorum never
  fills, 300 s without any output, wall clock frozen at the first arrival alarm
  (46927000; first arrival in `workloads/example_trace.jsonl` = 46926808).

## 2. Earliest violated invariant

The serving loop owns one scheduler per instance, and the loop's instance
attribution is derived from the backend reply:

```
out_dict = controller.parse_output(out)      # ← deliberately returns sys 0's line
instance_id = npu2inst_mapping[sys]          # __main__.py — derived from that line
schedulers[instance_id].schedule()
```

**Violated invariant (primary):** *completion evidence must retire work on the
instance that owns it, and every instance must eventually receive a scheduling
round.* `parse_output()`'s sys-0 bias broke the first half permanently
(`schedulers[k≥1].schedule()` was never called), and the round loop had no
fallback for the second half. Routing still placed requests on instances 1..N-1
(LOAD policy), so they queued forever — the exact `SCHEDULER_NO_DISPATCH`
liveness state (pending > 0, inflight = 0, dispatch = 0, backend responsive).

Two compounding violations followed (both fixed in the same commit):

| # | Defect | Mechanism |
|---|--------|-----------|
| 2 | Pass-echo retirement | Without a `Batch.sent` gate, each `pass`'s echoed finish lines "retired" DP-pending batches still awaiting quorum — the request re-queued every round and the wall clock froze at the arrival alarm |
| 3 | Round-robin starvation | Once the base instance emptied, no idle-not-done instance ever got a bookkeeping round, so `done_instance` could not fire; the loop spun bare-`pass` echoes forever |

State 2 is the sharper signature for DP configs (backend *responsive*, replies
*continue*, but `retired_requests` never moves — `BACKEND_RESPONSIVE_NO_TIME_ADVANCE`
in the PR5.1 vocabulary); state 1 dominates for plain multi-instance configs.

## 3. The fix (db61a633), mapped to the violations

1. **`Batch.sent` gate** — pass-echo finish lines can only retire batches
   actually flushed to the backend (`inflight[-1].sent`); DP-pending batches
   are immune to echo retirement. (violations 2)
2. **Round-robin fallback** — when the base instance cannot progress (empty
   queue *or* blocked on an unsent DP-pending batch), an idle-not-done instance
   gets a bookkeeping round so `done_instance` can fire for all. (violation 3)
3. **Protocol** — `load <path>`×N + `run` landed in both backends so per-rank
   ET files resolve under per-instance prefixes (retires the old
   `llm.2.et does not exist` failure mode). (violation 1's backend half)
4. Extras completions (`parse_all_booksim` non-leading finish lines) now count
   toward `req_cnt` + router notification; `done` no longer kills the backend
   at first instance completion.

## 4. Verification under PR5.1 instrumentation (2026-09-17)

PR5.1 added the pure `LivenessProbe` (`third_party/llmservingsim/serving/core/liveness.py`)
— per-round `ProgressObservation` (sim_time, pending/deferred/retired requests,
inflight batches, backend completions, per-instance scheduler state), the
6-state classification, and `NO_USEFUL_PROGRESS` reporting on failure paths.

Both historical configs re-run today (`--network-backend booksim
--booksim-replay-only`, `workloads/example_trace.jsonl`):

| Config | Before (2026-09-03) | After (this verification) |
|---|---|---|
| DP/EP 2-inst | livelock, 300 s no output, quorum never fills | exit 0; instance 0 TTFT 19.17 ms, instance 1 TTFT 25.77 ms |
| 4-inst TP2 | 1/3 requests (only instance 0) | exit 0 in ~3.7 s; TTFTs 6.09 / 8.09 / 130.91 / 876.99 ms — all four instances retire |

Before/after evidence basis: "before" numbers are the recorded symptoms in the
archived issue (written during the failure, pre-fix); "after" numbers are fresh
runs against the current tree at commit `83734c78` with the liveness probe
wired into the loop. The probe reported no `NO_USEFUL_PROGRESS` state in either
run (no failure path was hit, so no report fires — correct, since both runs
progressed).

## 5. Permanent regressions

`test_livelock_regression_dp_ep_both_instances_served` and
`test_livelock_regression_4_instance_2tp_all_served`
(`dse/tests/test_full_pipeline.py`) pin both configs. The anti-livelock
assertion is **not** a request-count: `_assert_every_instance_served()` reads
the `--output` per-request CSV and requires every expected instance id to
appear in its `instance id` column. `total requests >= N` passes vacuously
while instances 1..N-1 starve — that vacuous pass is precisely why the original
failure needed 300 s of wall-clock silence to notice.

Both tests skip cleanly when the vendored LLMServingSim tree or the
`AstraSim_BookSim2` binary is absent (same gating as the existing serve tests).
Local runtime: ~5.4 s for both.

## 6. Residuals / next

- The `_vprog_*` spin-abort guardrail still coexists with the `LivenessProbe`
  (two progress models by design). Unification is queued for the architecture
  checkpoint after PR7 — the probe is observational, the guardrail is
  behavioral; only the checkpoint decides which survives.
- `last_command` in the probe records only the bare-`pass` shape today; if a
  future regression needs command-sequence evidence, extend
  `ProgressObservation` first.
- Per the review directive, PR6 (serving → BookSim vertical slice) is now
  unblocked: the historical configurations terminate because the root cause
  was fixed and that fix is regression-pinned — not because a timeout absorbs it.
