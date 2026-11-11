# Serving campaign 01 — first real numbers

Runner: `scripts/veritx_campaign.py` (one JSONL row per experiment,
refusals recorded with reasons, absent metrics stay null).
Store roots are throwaway per campaign run; rows below are measured,
not projected.

## Results

| experiment | status | completed | makespan_cyc | ttft_mean/p50/p95 | compl_mean/p50/p95 | tok/kcyc | reason |
|---|---|---|---|---|---|---|---|
| dense-tp1 | FAILED | None/None | None | absent | absent | None | INVALID_INPUT: COLLECTIVE participants: 1 participant(s); a collective needs ... |
| dense-4xTP2 | COMPLETED | 8/8 | 812055126.0 | 24155/25030/34030 | 508441631/571067136/812055126 | None | - |
| moe-tp2ep2 | COMPLETED | 8/8 | 812055216.0 | 24165/25040/34040 | 508442265/571067256/812055216 | None | - |
| mixed-608 | SUBMIT_REFUSED (not run) | None/None | None | absent | absent | None | TP1 cluster cannot form collectives (same boundary as dense-tp1); full 608 exceeds a single campaign budget — see mixed-64 |
| mixed-64 | FAILED | None/None | None | absent | absent | None | INTERNAL_ERROR: ServingLoopError: no instance can schedule at clock 7599159000 and no future arrival exists; the trace is stuck |

Units: cycles are ASTRA system cycles. `tok/kcyc` is absent because
serving request metrics do not carry per-request output token counts
(field absent in native evidence, not zero).

## Reading the numbers

- dense-4xTP2 vs moe-tp2ep2 on the same 8-request trace: TTFT means
  differ by 10 cycles in 24k (identical scheduling, +10 from EP
  dispatch setup); makespans differ by 90 cycles in 812M. The two
  configs are nearly indistinguishable on this tiny trace — expected:
  8 short requests never stress EP vs TP paths. Bigger traces first.
- TP1 (dense-tp1, mixed-608-as-specified) cannot run collectives:
  a single rank has no collective communication. This is a typed
  refusal at the lowering boundary, not a backend gap.
- mixed-64 (4xTP2, first 64 of the mixed trace, max 30k input tokens):
  the serving scheduler deadlocked at the last arrival (clock
  7599159000) with work unscheduled. Undetermined whether long-context
  KV infeasibility (genuine saturation) or a scheduler stall; either
  way it surfaces as INTERNAL_ERROR with zero partial evidence, which
  is the wrong product shape — a stuck trace should be a typed
  INFEASIBLE/INCOMPLETE with partial completions preserved. Lead
  follow-up, not runner scope.

## Follow-up 2026-10-27: stall paths are typed, doctrine kept

- The exact raise this row hit (``no instance can schedule ... the trace
  is stuck``) was converted by 0c78f27b into the typed ``_stalled_outcome``
  path (INFEASIBLE/INCOMPLETE + break with partials). The silent-evidence
  raise was deliberately KEPT as a raise (pinned by
  ``test_a_dispatched_instance_without_execution_evidence_refuses`` and
  ``test_a_real_contract_violation_still_raises_serving_loop_error``):
  a backend that executes nothing is a broken contract, not a slow run.
- Live re-run of mixed-64 through ``veritx_campaign.py`` (default profile):
  REFUSED / NO_FEASIBLE_DESIGN — typed INFEASIBLE naming request 0
  (27369 tokens > max_num_batched_tokens=1024). No INTERNAL_ERROR.
- The deeper stall branch the 30k-bound run would take
  (NO_SCHEDULABLE_EVENT, within-bound but KV-unschedulable) is pinned
  hermetically by
  ``test_memory_stall_is_typed_incomplete_not_internal_error``. The 30k-bound
  live mirror was not re-run (the runner exposes no profile overrides);
  reachable via a direct ``submit_serving`` with ``profile_overrides``.
- Open question narrowed: not "typed or raise" (settled) but which stall
  branch the 30k configuration lands on.

## Provenance

- Cluster configs: `third_party/llmservingsim/configs/cluster/`
  (single_node_single_instance, single_node_4_instance_2TP,
  single_node_moe_single_instance).
- Traces: `third_party/llmservingsim/workloads/` (example_trace ×8/10,
  workload_me2_01_mixed ×64 attempted).
- ASTRA producer: pinned release binary + fresh manifest; evidence
  carries native request metrics with request_id dimensions.
