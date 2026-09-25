# Serving Qualification (C7 / R1)

Status: **QUALIFIED for the certified serving domains** listed below, each
independently graded. There is no global serving PASS, and no absolute
hardware-latency claim. Authority is source + tests + runtime output.

The certified serving path is `simulation/serving_loop.run_request_driven_service`:
JSONL arrivals -> real vendored `Router`/`Scheduler`/`Batch` -> canonical round
intent -> qualified ASTRA-BookSim round -> real `Scheduler.add_done`
retirement, with the service clock equal to the fabric's own reported cycle
count (`ns_per_cycle == 1.0`).

## Domain grades

| domain | status | evidence |
|--------|--------|----------|
| `SERVING_SCHEDULING` | QUALIFIED | independent first-principles oracle + 3 literal hand tables; loop agrees field-for-field on 4 traces (`test_serving_scheduling_oracle.py`) |
| `SERVING_TP` | QUALIFIED | runtime 4xTP2 over one fixed canonical fabric; TP4 vs 4xTP2 share the machine but differ in workload/evidence; live gate `test_real_4xtp2_canonical_gate` |
| `SERVING_DP` | QUALIFIED | runtime DP quorum (pad-to-max, explicit dummy, held-unsent batch, no cross-instance collective); live gates A (all-real) and B (real+real) |
| `SERVING_EP` | QUALIFIED | runtime dispatch ALLGATHER + combine REDUCESCATTER over the same rank set, distinct ASTRA nodes, no rank multiplication (`test_serving_ep.py` runtime gates) |
| `SERVING_MULTI_INSTANCE` | QUALIFIED | every active instance progresses; clock advances strictly; all requests retire once; idle instances named; no instance-0 bias (`test_serving_multiinstance_liveness.py`) |
| `SERVING_TTFT` | QUALIFIED | TTFT is the vendored `Request`'s own value, measured from the request's arrival; the oracle reproduces it exactly under the declared profile |
| `SERVING_ABSOLUTE_LATENCY` | PARTIAL | exact under the declared linear service profile (`compute_base_ns + per_token*tokens`, declared collective bytes); **not** calibrated to real hardware latency |
| `SERVING_INTEGRATION_FIXTURES` | QUALIFIED | six `test_full_pipeline.py` tests run against deterministic tracked Chakra `.et` fixtures (`R1.1`), not a developer-local trace directory |

`SERVING_ABSOLUTE_LATENCY` is deliberately not QUALIFIED: the certified
profile declares a linear compute/collective model instead of reclaiming a
perf-DB measurement, and live rounds use `--booksim-replay-only`. A model-
internal latency is exact; a hardware latency claim is not made.

## Scheduling oracle (R1.2)

The loop was previously covered only by invariants (TTFT > 0, arrival gating,
`clock == sum(cycle counts)`), which cannot falsify a wrong schedule.
`tests/test_serving_scheduling_oracle.py` adds a reference model written from
the declared semantics that never imports the loop, the vendored scheduler or
any code under test. Three literal hand-derived tables validate the model;
the model is then compared field-for-field with the real loop. Fields:
instance, arrival, prefill start/end, first token, decode rounds, completion,
TTFT, latency.

## Parallelism (R1.3/R1.5)

TP, DP and EP are each proven from the **runtime ledger**, not only lowering:

- **TP**: a batch's `participant_ranks` produce exactly one communicator group
  and one collective; independent instances are not folded into a DP group;
  TP geometry is never inferred from endpoint numbering.
- **DP**: `ServingDataParallelGroup` + `DpQuorumRecord`; a member's real batch
  is held unsent until its whole quorum is ready; a dummy member is network-
  dispatched and retires zero user requests; `dp_sum_total_len == max_total_len`
  (pad-to-max, never max x group size).
- **EP**: dispatch ALLGATHER + per-rank expert compute + combine
  REDUCESCATTER over the *same* participant ranks (ep_size <= instance ranks);
  expert-compute ops are owned by those ranks; the rank namespace is never
  multiplied.

## Network-execution evidence (R1.6)

Every round's runtime collective ledger is parsed and validated against the
round's declared collective contract, keyed by ASTRA node id
(`validate_collective_ledger_contract`): kind, payload size, communicator
membership and submitter completeness must match. A dispatched instance with
no endpoint execution evidence fails; a completion from an undispatched
instance (pass echo) fails; an unsent batch can never be retired. See
`test_serving_round.py`, `test_serving_canonical.py`, `test_serving_loop.py`.

## Multi-instance liveness (R1.7)

`test_serving_multiinstance_liveness.py` drives 8 requests across 4 instances
and proves per-instance progress from the round records (queued, dispatched
rounds, completed, last progress time); it also proves late/idle instances do
not block progress and that no request retires twice or before its arrival.

## Integration fixtures (R1.1)

The six `test_full_pipeline.py` integration tests depended on a git-ignored
LLMServingSim run directory and skipped on a clean clone (a release-gate
failure). They now run against deterministic Chakra `.et` fixtures generated
by `veritx_dse.tools.gen_serving_chakra_fixtures` from canonical text traces,
committed with a sha256 manifest and reproduced byte-identically by
`test_serving_fixture_provenance.py`. Cases: `event_handler`, `dense_single`,
`dense_tp2`, `dense_tp4`, `moe_ep`.

## What remains outside this qualification

- Absolute hardware latency and throughput calibration.
- PD (prefill/decode) disaggregation: outside the certified profile, refused.
- PIM, CXL, active remote-memory timing: not supported by the certified loop.
- Partial-membership collectives: a certified round carries one communicator
  group, so a round spans the full participant set.

## Test reliability (C7.1)

- `test_crash_mid_session`, stderr-flood quiescence, per-test timeouts
  (`pytest-timeout`, 900 s default, 30 s protocol).
- Release gate fails on release-critical skips; the serving `.et` skips are
  resolved by R1.1. The `VERITX_ASTRA_REF_BIN` reference-binary differential
  is tracked under R2 (ASTRA) and is a shared-engine differential, not an
  independent numerical oracle.
