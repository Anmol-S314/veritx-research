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

## Fix status (2026-09-03 update — eab2dfb7)

- ✅ Protocol landed: `load <path>`×N + `run` in both backends (per-rank file existence; legacy bare-path rounds unchanged).
- ✅ Statistics throw (CPU/REMOTE_MEM types in overlap extraction → std::terminate on instance-switch rounds) fixed.
- ✅ Independent multi-instance (`4_instance_2TP`) now serves instances 0..3 via round-robin: 2/3 reqs complete in 240s wall (3rd is rate-limited by serialized rounds, not stuck); per-instance TTFTs real (6/19/142 ms).
- ⚠️ Remaining: (a) round serialization cost — each Waiting round simulates one instance's batch; large-N configs are wall-clock heavy (DP-adjacent slowdown); (b) DP-group (`moe_dp_ep_instance`) NEW livelock post-rr: `schedule()` re-creates batch #0..N every round (wall frozen at arrival alarm 46927000, requests never consumed by dp_pending quorum); (c) PD (`single_node_pd_instance`) starts fine (prefill NPU[0] batch done, wall advances) but dies "No valid output" partway — 3-NPU/2-instance rank-doubling interaction untested.

## Old fix sketch (protocol part done; loop parts remain)
1. **Both `main.cc`s:** per round accept `load <path>` lines then `run`; reload system *i* only from the path where `<path>.<i>.et` exists; fire all unfinished workloads; emit per-sys lines + `Waiting`.
2. **`controller.py`:** return the full list of completed (sys, cycle) lines, not just sys 0.
3. **`__main__.py` loop:** on each Waiting round, schedule ALL instances whose in-flight batch completed (parse_all_booksim already sees them), collect their workload paths, send as loads + run.
4. Also re-run profiler with `TP_DEGREES` incl. 8 to unblock a single-instance 8-NPU config (`tp8` profile data missing today).

## Validated working (no protocol change needed)
Single-instance configs only, all 7 workloads, booksim backend, post unit-fix:
- 1N `single_node_single_instance`: 3/3 reqs, TTFT 16.09ms, TPOT 11.24ms
- 2N `single_node_moe_single_instance`: example 3/3 19.88ms/4.73ms; full sweep 6/7 workloads complete (swe-bench agentic = slow wall-clock, not a failure)
