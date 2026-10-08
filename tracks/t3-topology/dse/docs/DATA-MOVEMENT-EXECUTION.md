# Explicit V5 data movement

Run from `tracks/t3-topology/dse`:

```bash
veritx --json evaluate data-movement --experiment examples/addressed_memory_v5.json
# Direct module entry, same evaluator:
python3 -m veritx_dse.application.data_movement examples/addressed_memory_v5.json
```

`ABSTRACT_DATA_MOVEMENT_V1` is an abstract experiment, **not** qualified
BookSim execution, RTL CDC signoff, DRAM timing, or PPA.

## Supported slice

- Explicit READ/WRITE endpoint IDs, addresses, payload/control sizes, target
  service cycles and dependencies. No memory demand inferred from collectives.
- V5 endpoint-bound outstanding, splitting and STRONG/RELAXED/CUSTOM hazard
  policies. Each child spends one agent transaction credit; its modeled
  response releases it. Parents complete only when every child completes.
- Optional `AgentIntentV5.transaction_clock_domain` drives issue/service on
  the agent side of an explicit bridge. It never overwrites the V4 fabric
  attachment clock. Omission preserves old V5 intent bytes.
- Single-clock P2P fabric; explicitly declared GRAY, equal-flit-width FIFO
  bridges to agent clocks. Exact rational, phase-zero clock edges; both pointer
  directions synchronize. One shared FIFO lane per directed clock pair;
  whole bursts serialize until pointer release is visible. This is not a
  pipelined RTL FIFO or wormhole router model.
- Deterministic routing from the canonical root, canonical packetization,
  whole-message store-and-forward channel reservations and target-service
  serialization. One child issue per initiator clock edge.
- Authored, non-overlapping router footprints inside a die, exact micrometres,
  canonical resource binding and Manhattan centre-to-centre channel lengths.
  `routed_flit_um` is geometric traffic distance, not delay/energy/PPA.

The example is synthetic compute-to-HBM-controller addressed demand, not a
Qwen execution. Its embedded V4 workload supplies the hardware's traffic-class
vocabulary; the explicit workload supplies all executed transactions.

Evidence binds system, workload and placement identities, child/parent
completion, packet/flit accounting, FIFO conservation/backpressure, outstanding
peaks, exact timestamps and geometry. Reload recomputes the execution, not just
its hash. Geometry changes do not fabricate timing changes.

Limits: 10k children and 1M flits. Missing clock/policy/bridge, unresolved or
unsupported crossings, width conversion, reorder windows, sidebands, access
policy enforcement, adaptive/shared-wire/multi-plane routing refuse. Generic
V5 evaluation remains refused. Power/reset execution, memory contents,
physical implementation and external qualification remain unimplemented.

Tests: `test_data_movement_execution.py`, `test_clocked_fifo_reference.py`.
The latter checks 784 rate/depth/stage/size combinations against an independent
sampled-pointer mathematical reference; it is not an RTL differential.
