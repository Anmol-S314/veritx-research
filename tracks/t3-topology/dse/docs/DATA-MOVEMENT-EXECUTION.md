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
- One authored network clock with independently authored endpoint transaction
  clocks and explicit GRAY, equal-flit-width FIFO bridges. Exact rational,
  phase-zero clock edges; both pointer
  directions synchronize. One shared FIFO lane per directed clock pair;
  whole bursts serialize until pointer release is visible. This is not a
  pipelined RTL FIFO or wormhole router model.
- Deterministic routing from the canonical root, canonical packetization,
  whole-message store-and-forward channel reservations and target-service
  serialization. One child issue per initiator clock edge. A compiled Plane-D /
  Plane-C binding may execute concurrently: traffic class chooses its bound
  subnet independently for request and response; Plane D uses the compiled
  route, Plane C uses its declared plain XY mesh route. Channel lanes are
  subnet-local, while endpoint interfaces, declared FIFO crossings and target
  service remain shared. Evidence binds the plane-assignment hash and reports
  per-plane routed/link flits. This does not model VC buffers, credits, adaptive
  routing or RTL CDC.
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
unsupported crossings, width conversion, reorder windows, unbound sidebands,
adaptive/shared-wire routing refuse. Multi-plane execution refuses unless the
compiled class-to-subnet binding and its Plane-C plain-XY control plane both
exist; only the two-subnet D/C profile is supported. A declared access policy with
missing address space or any denied byte refuses; no policy means no access
authorization claim. Generic V5 evaluation remains refused. Domain power is a
coupled-reference-only profile; native clock gating, physical isolation, energy,
RTL reset, and external qualification remain unimplemented.

## Bounded MSI directory reference profile

A coupled workload may opt into an explicit `msi_profile` with a fixed line
size, per-requester cache bound, and authored directory, memory-fill,
invalidation, acknowledgement, recall, and writeback cycle costs. The coupled
runtime tracks I/S/M state, sharers, a dirty owner and full-line dirty bytes;
reads after a dirty-owner recall observe the latest bytes, partial writes retain
the untouched bytes, and requester eviction writes dirty lines back. A single active MSI transaction provides deterministic conservative arbitration.
Directory,
invalidate/ACK, recall/writeback, fill and grant messages reserve the same
endpoint, FIFO and channel resources as ordinary traffic. Exclusive state commits
only after required ACKs and dirty data retire. An authored dropped ACK retries
the logical child before commit; epoch and dedup identity prevent a duplicate
write. Authored directory/home costs remain distinct from actual reference
channel timing. This is not native coherence timing or protocol signoff. `BYPASS`
and `OWNER_CACHE` workloads without `msi_profile` retain their existing semantics.

## Domain power lifecycle reference profile

A coupled workload can bind `power_policies` to every attached declared
`COLLAPSIBLE` power domain. Each `DomainPowerPolicy` explicitly selects the
active and declared sleep states, `DRAIN_DOMAIN`, `ISOLATE_AFTER_DRAIN`,
`SIGNAL_RESTORE_DEISOLATE`, `DOMAIN_LOCAL`, `RETAIN_ALL` or
`CLEAR_DOMAIN_MEMORY`, active control clock,
interrupt wake connection, and isolation/sleep/restore/wake costs. The runtime accepts one
`DOMAIN_SLEEP` / `DOMAIN_WAKE` pair per domain and optional `DOMAIN_RESET`
nodes. Sleep blocks new admissions to the domain, waits for its active children
to retire, asserts isolation, then enters sleep. Wake is scheduled on the
explicit same-clock INTERRUPT sideband path between declared `ALWAYS_ON`
control endpoints; the target state/clock is restored before isolation is
removed and admission resumes. Domain reset is dependency-ordered against all
accesses touching the domain, uses a declared reset channel with synchronous
release stages, and advances a domain-local epoch. Every child binds its
per-domain epoch; mismatched responses are rejected. `CLEAR_DOMAIN_MEMORY`
zeroes authored shards homed in the domain and invalidates the corresponding
owner-cache projection after drain. MSI clear is refused until dirty-state flush
is modeled. The selected retention policy and cleared-byte count are evidence-bound.

The initial profile refuses MSI clear/flush retention, power-domain CDC, multiple
transaction clocks in one domain, wake paths outside the explicit active
same-clock interrupt route, and mid-flight reset. Existing `DRAIN_RESET`
remains the distinct global drain/reset profile. These transitions and costs are
bounded reference scheduling only, not physical power switching, metastability,
clock-gating, isolation-cell, UPF, or reset signoff evidence.

`application.execution_closure.execute_w6_reference_scenario` composes the
compiled two-plane binding, two authored clock rates, MSI reference, domain
lifecycle, and response/ACK fault profiles through this same coupled scheduler.
It refuses unless both planes overlap on channel work, shared-resource waiting
is observed, losses are actually exercised, domain sleep/wake/reset retires,
and requests, FIFOs and MSI transients drain. Its evidence is
`REFERENCE_SCENARIO_COMPLETE`, never `QUALIFIED`; native multicast is a separate
unsupported producer profile and RCU is excluded.

Tests: `test_data_movement_execution.py`, `test_data_movement_access.py`,
`test_clocked_fifo_reference.py`.
The latter checks 784 rate/depth/stage/size combinations against an independent
sampled-pointer mathematical reference; it is not an RTL differential.

## Automatic bounded retries (fault recovery reference envelope)

`execute_data_movement(..., _faults=FaultProfile(...))` is opt-in and
off by default: without a profile, execution and evidence are unchanged.
`execute_coupled_tensor(..., faults=FaultProfile(...))` forwards the same
reference envelope through the tensor DAG; the native BookSim/Ramulator
profile does not expose it.

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
existing whole-message reservations only. Tests exercise it on both synthetic
operations and the coupled tensor reference, including single memory commit and
readback under response loss. It is **not** native transport reliability, not
link hardware behaviour, not CRC/ARQ, not in-flight cancellation, and not a
claim about physical fabrics. The independently authored `retry_of`
retransmission in the coupled reference remains a separate mechanism.
