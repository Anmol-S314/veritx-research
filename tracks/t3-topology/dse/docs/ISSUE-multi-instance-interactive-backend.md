# Bug: interactive backend only ever drives instance 0

**Found:** 2026-09-03, while validating "any LLM workload → cycle-accurate" (post `fb9e72ed` unit fix).

## Symptom
- `single_node_4_instance_2TP` (4 instances × TP2): only request #0 completes (on instance 0); requests routed to instances 1-3 are never scheduled (stall at `0 reqs, Waiting: 1`).
- `single_node_moe_dp_ep_instance` (DP group): full livelock — `dp_pending` quorum never fills, 300s without any output.

## Root cause
1. `serving/core/controller.py: parse_output()` deliberately returns **sys 0**'s completion (`if sys == 0: result = ...`).
2. `serving/__main__.py:849` derives `instance_id = npu2inst_mapping[sys]` → permanently instance 0.
3. So `schedulers[k].schedule()` for k ≥ 1 is never called; routing still places requests there (LOAD policy).
4. Compounding: the binary's interactive protocol (`booksim2/main.cc` and our `analytical/*/main.cc` patch) reloads **one** workload path for **all** systems. Instance-k batch dirs only contain `llm.<2k>.et`/`llm.<2k+1>.et`, so other ranks' files don't exist under that prefix (this is the real source of the old `llm.2.et does not exist` errors — NOT model mismatch).

## Fix status (2026-09-04 update — db61a633) — RESOLVED

- ✅ Protocol landed: `load <path>`×N + `run` in both backends (per-rank file existence; legacy bare-path rounds unchanged).
- ✅ Statistics throw (CPU/REMOTE_MEM types in overlap extraction → std::terminate on instance-switch rounds) fixed.
- ✅ Independent multi-instance (`4_instance_2TP`) 3/3 clean (was 1/3), `moe_multi_instance` 4/4 clean.
- ✅ DP-group (`moe_dp_ep_instance`) quorum livelock fixed: `Batch.sent` gate prevents pass-echo from retiring DP-pending batches; dummy self-overwrite guarded; shared quorum dir not re-enqueued (stale double-retire removed); extras retires now counted (req_cnt+router notify).
- ✅ PD (`single_node_pd_instance`) 2/2 clean (was flaky 1/2): same `sent` gate + extras count + `done`→`pass` fix; rr fallback for idle-not-done ensures done_instance fires for all instances.
- ✅ PD flake CLOSED loudly (6178d3e5): exit-time dropped-request guard (`req_cnt < router.req_num` → full state dump). Soak: 15× PD 3-req — 14 completed, all 3/3, guard never fired; 1 hit the 180s soak timeout, which a monitored rerun proved was SILENCE-NOT-PROGRESS (heartbeat only prints at sim-1s boundaries; PD 3-req needs 100-180s wall). Use ≥300s timeouts for PD 3-req soaks.
- ✅ Early-exit kill fixed: both backends treat `done` as `exit` (break), so old `write_flush(p,"done")` killed the binary at first instance completion — replaced with conditional `pass`; `done_inst_npus` echo-count gate (pinned sys=0 + TP>1 never reached 2) replaced with honest `not inflight` check.
- ✅ Matrix (booksim, WARNING): 1N 2/2, moe_single 3/3 (me2), 4-inst 3/3, moe_multi 4/4 (shared_prefix), DP 2/2, PD 2/2 — all `Exiting simulation`.
- Remaining: round serialization cost — each Waiting round simulates one instance's batch; large-N configs are wall-clock heavy but functionally correct.

## Old fix sketch (protocol part done; loop parts remain)
1. **Both `main.cc`s:** per round accept `load <path>` lines then `run`; reload system *i* only from the path where `<path>.<i>.et` exists; fire all unfinished workloads; emit per-sys lines + `Waiting`.
2. **`controller.py`:** return the full list of completed (sys, cycle) lines, not just sys 0.
3. **`__main__.py` loop:** on each Waiting round, schedule ALL instances whose in-flight batch completed (parse_all_booksim already sees them), collect their workload paths, send as loads + run.
4. Also re-run profiler with `TP_DEGREES` incl. 8 to unblock a single-instance 8-NPU config (`tp8` profile data missing today).

## Validated working (no protocol change needed)
Single-instance configs only, all 7 workloads, booksim backend, post unit-fix:
- 1N `single_node_single_instance`: 3/3 reqs, TTFT 16.09ms, TPOT 11.24ms
- 2N `single_node_moe_single_instance`: example 3/3 19.88ms/4.73ms; full sweep 6/7 workloads complete (swe-bench agentic = slow wall-clock, not a failure)
