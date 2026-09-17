# HANDOFF 2026-09-17 — PR5.1: serving-loop liveness observability (complete)

**Branch:** `epic/booksim-forward-port` · **local commits:** `e1278f96` (A–E), `5326821f` (PR5)
**Suite:** `960 passed, 1 skipped` — up from 941/1 (PR5) and 869/1 (session start).
**Scope:** observability ONLY. No abort threshold added, no behavioral change, no PR6. The pre-existing `VERITX_SPIN_ABORT` guardrail is untouched (its failure path now *reports* liveness; the guardrail itself is unchanged).

## 1. Deliverables

| File | What |
|---|---|
| `third_party/llmservingsim/serving/core/liveness.py` (**new**) | Pure probe: `ProgressObservation`, `LivenessProbe` (observe / classify / report / render / answers), `attach_to_failure`. Never mutates simulator state, never aborts, no thresholds. |
| `third_party/llmservingsim/serving/__main__.py` (3 small edits) | (a) import block + probe construction before the loop; (b) one `observe()` call at the loop bottom (after all round state is final, before the flush) wrapped in try/except so instrumentation can never kill simulation; (c) `_liveness_attach` prints on the two existing failure paths (EOF-with-work, spin abort) + optional machine JSON via `VERITX_LIVENESS_JSON` on abort. |
| `dse/tests/test_serving_liveness.py` (**new, 19 tests**) | Pure-probe classification + all 8 mandated scenarios + fake-backend end-to-end drives + purity pins. |
| `docs/SEMANTIC_QUESTIONS.md` | Q5 RESOLVED (legacy terminators never produced); frozen serving-contract decisions recorded. |
| `docs/protocols/llmservingsim-backend.md` | §10 frozen contract decisions. |

## 2. Progress fields and sources (all pre-computed values, zero re-parsing)

| Field | Source (serving loop) |
|---|---|
| `sim_time` | `current` (frontend clock; last backend-reported cycle or `pass <t>` jump) |
| `backend_cycle` | trailing `cycle` in the round's completion burst (`round_completions[-1]['cycle']` — reuses PR5-traced `parse_all_completions`, no independent stdout parsing) |
| `backend_completions` | `len(round_completions)` |
| `retired_requests` | `req_cnt` (cumulative) |
| `pending_requests` | `len(router._pending_requests) - router._pending_idx` |
| `deferred_requests` | `len(router._deferred_sessions)` |
| `inflight_batches` | `sum(len(sch.inflight))` |
| `dispatched_this_round` | `bool(finished_reqs) or _routed_now > 0 or new_req is not None` |
| `per_instance` | per instance: `waiting/running/inflight` (+ `dp_queued` from `dp_pending`) |
| `last_command` | logical command for the round (bare-pass shape tracked; see limitation) |
| `backend_alive` | `p.poll() is None` |
| fingerprint | `(sim_time, retired, pending, deferred, inflight, backend_completions)` — scientific state, never wall-clock |

## 3. Classification rules (exclusive, ordered)

1. `BACKEND_NOT_RESPONDING` — process dead (`poll() is not None`).
2. `BACKEND_RESPONSIVE_NO_TIME_ADVANCE` — replied, zero completions, no clock move, **nothing inflight** (pure idle ping-pong).
3. `INFLIGHT_NO_COMPLETION` — work inflight, zero completions this reply, nothing dispatched this round. **Outranks #4** — "work stuck in the network" is the operationally sharper label; a `pass <t>` jump with inflight work still lands here.
4. `SIM_TIME_ADVANCING_NO_REQUEST_PROGRESS` — clock moving, retire count frozen.
5. `SCHEDULER_NO_DISPATCH` — nothing inflight/dispatched while pending/deferred > 0.
6. `USEFUL_PROGRESS`.

`NO_USEFUL_PROGRESS` is an observation, never a diagnosis — no code path claims deadlock.

## 4. Deterministic output — `waiting_without_progress` fixture (201 rounds, ~0.3 s, no simulator binaries)

```
NO_USEFUL_PROGRESS
state: BACKEND_RESPONSIVE_NO_TIME_ADVANCE
rounds_unchanged: 199
round: 201
sim_time: None
backend_cycle: None (prev None)
retired_requests: 0
pending_requests: 2
deferred_requests: 0
inflight_batches: 0
backend_completions: 0
dispatched_this_round: False
last_command: pass
backend_alive: True
per_instance:
  instance_0: {"dp_queued": 0, "inflight": 0, "running": 0, "waiting": 2}
  instance_1: {"dp_queued": 0, "inflight": 0, "running": 0, "waiting": 2}
```
(`sim_time/backend_cycle: None` is the pure Waiting-only shape — the fake's livelock mode emits bare `Waiting`, like the real `done` reply. A real backend stall shows cycle values; the classification is identical.)

The eight review questions are answerable from `probe.answers()`: backend alive ✓, replying ✓, sim_time changing ✗, requests retiring ✗, schedulers dispatching ✗, batches inflight 0, stuck instance (waiting>0 & inflight=0 & unchanged), repeating_same_action ✓.

## 5. Newly discovered conditions / honest limitations

1. **Two progress models now coexist by design**: the loop's `_vprog_*` counters (abort guardrail) and the probe (observation). Semantics differ — `_vprog_last` treats ANY clock advance as progress; the probe requires completion/retirement evidence. Documented; the probe does not feed the guardrail, so behavior is unchanged. Candidate for unification at the architecture checkpoint.
2. **`last_command` limitation**: this iteration records the bare-pass shape (`pass` / `pass <t>` / `pass -1`); workload-path dispatches are visible via `dispatched_this_round` but not stored verbatim. Cheap to extend when PR5.2 shows it matters.
3. **The `sys 0` retire path** (`controller.parse_output` BookSim branch picks sys 0, loop retires instance of sys 0 first, then sweeps extras) — per-instance `inflight` in the report makes any misattribution visible per round; this is exactly the evidence PR5.2 needs.
4. The observe block sits after `_sweep_completion` and done-checking, so a round that breaks out (`all instances done`, EOF) does not record a final observation — the failure paths attach the last recorded one, which is the pre-break state. Acceptable for diagnosis; noted for completeness.

## 6. Root-cause readiness verdict

**Yes — the historical multi-instance livelock now has its evidence machinery.** The four decision branches from your matrix are each observable in one report:
- `pending>0, inflight=0, dispatch=0, backend responsive` → `SCHEDULER_NO_DISPATCH`
- `inflight>0, completions=0, Waiting continues` → `INFLIGHT_NO_COMPLETION`
- `completions>0, retired unchanged` → `SIM_TIME_ADVANCING_NO_REQUEST_PROGRESS` (or USEFUL if retiring eventually)
- `one instance progresses, another never receives work` → per_instance + `stuck_instance`

**Next (PR5.2, starting now):** smallest real previously-spinning configuration; capture per-instance state/completions/commands/sim-time/ownership; deliver a root-cause document stating the earliest violated invariant + before/after trace; fix only that defect; add the exact config as a permanent regression. No timeout counts as the fix. PR6 remains blocked until the real config terminates because the root cause was fixed.
