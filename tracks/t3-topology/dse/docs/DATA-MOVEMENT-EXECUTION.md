# Explicit V5 data movement

Run from `tracks/t3-topology/dse`:

```bash
veritx --json evaluate data-movement --experiment examples/addressed_memory_v5.json
# With explicit WO/RO permissions:
veritx --json evaluate data-movement --experiment examples/addressed_memory_access_v5.json
# Direct module entry, same evaluator:
python3 -m veritx_dse.application.data_movement examples/addressed_memory_v5.json
```

`ABSTRACT_DATA_MOVEMENT_V1` is an abstract experiment, **not** qualified
BookSim execution, RTL CDC signoff, DRAM timing, or PPA.

## Supported slice

- Explicit READ/WRITE endpoint IDs, addresses, payload/control sizes, target
  service cycles and dependencies. Request and response can name separate,
  already-declared traffic classes; omission uses the request class in both
  directions. The canonical route is selected independently per direction.
  No memory demand is inferred from collectives.
- Compiled access-policy enforcement over the entire parent byte range,
  including every crossed window and gap. Address space must be explicit when
  a policy is present; GLOBAL never grants LOCAL. Explicit targets are
  authoritative here, not inferred from an address decoder. Denial aborts
  before any child issues. Evidence separates route existence, permission and
  abstract execution observation; this is not a hardware firewall.
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
unsupported crossings, width conversion, reorder windows, sidebands,
adaptive/shared-wire/multi-plane routing refuse. A declared access policy with
missing address space or any denied byte refuses; no policy means no access
authorization claim. Generic
V5 evaluation remains refused. Power/reset execution, memory contents,
physical implementation and external qualification remain unimplemented.

Tests: `test_data_movement_execution.py`, `test_data_movement_access.py`,
`test_clocked_fifo_reference.py`.
The latter checks 784 rate/depth/stage/size combinations against an independent
sampled-pointer mathematical reference; it is not an RTL differential.

## Automatic bounded retries (fault recovery reference envelope)

`execute_data_movement(..., _faults=FaultProfile(...))` is opt-in and
off by default: without a profile, execution and evidence are unchanged.

`FaultProfile` declares deterministic loss, so no random source is involved:

- `dropped_requests` / `dropped_responses`: `"<operation_id>:<child sequence>"`
  keys mapped to the attempt numbers that lose their flight.
- `timeout_cycles`: response deadline measured in network-clock cycles from
  service completion.
- `max_attempts`: physical attempts per child, bounded at 16.

Semantics:

- A dropped request flight retries from phase zero; a dropped response flight
  retries **after** the service phase, so memory is never committed or mutated
  twice (one service reservation per child, always).
- A response deadline that expires while the child has no response retries the
  same way. A deadline belongs to the attempt that armed it: a superseded
  attempt's queued phases and its stale deadline are void, so a retry can never
  be triggered twice for one response.
- The first response that retires wins; the initiator credit is held across
  every attempt and released exactly once.
- Exhausting `max_attempts` seals the child and fails the experiment with
  `EvidenceInvalid`. There is no partial completion and no silent give-up.
- Each child records an `attempt_log` of drop/timeout/retry/retire events with
  the attempt number and exact time.

This models packet loss, an unacknowledged tail and a retry deadline inside the
existing whole-message reservations only. It is **not** native transport
reliability, not link hardware behaviour, not CRC/ARQ, not in-flight
cancellation, and not a claim about physical fabrics. The independently authored
`retry_of` retransmission in the coupled reference remains a separate mechanism.
