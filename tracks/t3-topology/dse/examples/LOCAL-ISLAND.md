# Abstract local-island regulator experiment (v1)

This is a **new explicit abstract modelling contract**, not recovered native
SROTA semantics. Canonical SROTA intent still supplies placement/routing only.
No compiler intent fields, hardware capabilities, BookSim qualification, RTL,
UVM, shared side-buffer, telemetry, full-fabric or physical timing are added.

From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tracks/t3-topology/dse python -m veritx_dse.application.local_island tracks/t3-topology/dse/examples/local_island_positive.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tracks/t3-topology/dse python -m veritx_dse.application.local_island tracks/t3-topology/dse/examples/local_island_negative.json
```

The positive example explicitly binds the compiled `srota32_islands` design's
router 1 / endpoint 2 / `tp_collective` class. Four single-flit offers are
admitted at model cycles 0, 2, 4, 6 and served at 1, 3, 5, 7; all credits return
by the end of the nine-cycle horizon. The negative example uses an undeclared
class and must refuse. Exit codes: 0 complete, 1 refusal, 2 incomplete horizon.
Dirty-tree results are diagnostic only, not qualification evidence.

## Contract and accounting

All rate, burst, initial tokens, attach capacity, periodic service slots and
credit-return latency are explicitly supplied; no simulator tuning or placement
field supplies defaults. Fractions use reduced nonnegative integer numerator /
positive integer denominator records, never floats. Rates are flits per abstract
model cycle, **not a real clock, native rate or physical service latency**.
Contract identity includes parent topology/attachment identities, declared class
names, local endpoints and the complete named v1 edge/arbitration semantics.
Evidence additionally binds the revalidated compiled system and offer trace;
loading evidence recomputes the execution from those parents.

Each declared endpoint starts with an empty bounded attach FIFO and capacity
credits. Buckets are per declared traffic class shared across these local
endpoints on one island router. Each finite offer is one externally held flit;
upstream offers are not another modeled bounded fabric queue. No drops or
implicit arrivals are invented. Queues need not cover every local endpoint;
undeclared endpoints/classes refuse rather than projecting into a queue.

Cycle edges run in this order:

1. Return credits due on this edge; refill buckets (except cycle 0), capped at
   burst. Explicit initial tokens apply at cycle 0.
2. Serve existing endpoint FIFO heads up to that endpoint's periodic service
   slots. Zero slots permit explicit service starvation. Each departure returns
   exactly one credit at `service_cycle + credit_latency_cycles`; zero latency
   returns before admission on this edge, never granting extra same-edge service.
3. Admit due offers in ascending endpoint-ID order. Each endpoint's external
   FIFO is ordered by arrival cycle, then unique offer ID. Failed credit/token
   admission retains its head, spends no token and blocks later offers on that
   endpoint (even a different class). Successful admission debits one token and
   one credit. No speculative reservation, native allocator or refund is modeled.
4. Snapshot state and check flit, capacity, credit and token-envelope invariants.

Zero rate means **no refill**, not the native simulator's unregulated bypass.
Burst must hold at least one flit; initial tokens may be zero. Service and FIFO
arbitration may starve offers deliberately; no fairness/progress theorem is
claimed. Horizon is `[0, horizon_cycles)`, bounded to one million work units.
Future offers remain pending; no hidden drain or extra cycle is run.

`COMPLETE` requires every declared offer delivered **and every credit returned**.
Pending/backpressured offers or credit-in-flight mean `INCOMPLETE`, never a PASS
completion. `payload_completed` separately distinguishes delivered flits from
reusable credit capacity. Per-edge snapshots expose blocked heads, occupancy,
credits, in-flight credits and exact tokens. These demonstrate this abstract
model's conservation, not physical timing or native SROTA correctness.
