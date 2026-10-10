# Standalone topology-bound reference network models

These are **new bounded reference modelling contracts**, not canonical RCU or
hardware multicast support. Canonical `rcu_enabled=True` and hardware
replication still refuse; existing source replication is unchanged. No BookSim,
ASTRA, RTL/UVM, physical, performance or qualification equivalence is claimed.
All executions in the current dirty tree are **diagnostic only**.

## Executable JSON examples and strict replay

From repository root:

```sh
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tracks/t3-topology/dse
python -m veritx_dse.verification.reference_network \
  --input tracks/t3-topology/dse/examples/rcu_reference_v1.json \
  --output /tmp/rcu-reference.json
python -m veritx_dse.verification.reference_network \
  --input tracks/t3-topology/dse/examples/multicast_tree_v1.json \
  --output /tmp/multicast-reference.json
python -m veritx_dse.verification.reference_network \
  --input tracks/t3-topology/dse/examples/multicast_tree_v1.json \
  --verify-evidence /tmp/multicast-reference.json --output /tmp/multicast-replay.json
python -m pytest -q -p no:cacheprovider \
  tracks/t3-topology/dse/tests/test_rcu_reference.py \
  tracks/t3-topology/dse/tests/test_multicast_reference.py \
  --basetemp=/tmp/reference-network-tests
```

JSON contains actual existing `TopologyArtifact` / `AgentAttachmentArtifact`
parents, not an invented topology schema. Every contract reload reconstructs
and validates actual endpoint seats, parent identities and all paths/edges.
Multicast also carries actual VC and canonical packet-format parents. Input,
contract, full execution trace and result hashes are bound; evidence verification
reruns the complete deterministic consumer against supplied authoritative
parents/inputs and compares exact serialization (including boolean types).
Unknown fields, missing hashes, duplicate JSON keys and nonfinite JSON constants
are refused. Artifact hashes identify content, not trusted provenance or signing.

Both v1 models support a **single Plane D, CHANNEL-only topology**; shared links,
MECS taps and multidrop transactions are refused, never flattened to edges.

## ABSTRACT_RCU_REFERENCE_V1

- Explicit `SUM`, `UINT32`, `WRAP_MOD_2_32`: equal nonempty vectors, exact integer
  lanes in `[0,2^32-1]`, modulo `2^32` sum. No floats, bools, signed lanes, MAX,
  saturation, allreduce or wire encoding inference.
- Explicit sorted unique contributors, group, root, lane count, reducer router,
  per-contributor directed unicast CHANNEL path, and reducer-to-root path. Local
  paths are empty only when bound routers coincide. Root contributes only if
  listed. The reducer is a **reference sidecar**, not a canonical router port.
- One open epoch at a time. New epochs strictly increase after delivery or abort.
  Arbitrary contributor arrival order; each contributes once. Identical and
  conflicting duplicates both reject. Unknown contributor, wrong group/epoch,
  shape/range, busy/overlap and early result emission reject with reasons and
  leave reducer state unchanged. No retry/dedup/input queue or implicit timeout.
- The consumer orders explicit events by `(cycle,event_id)`; event IDs are unique.
  Each accepted vector occupies `[admission, admission+service_cycles)`; another
  may enter exactly at finish. Abort cancels remaining occupancy, releases epoch,
  records missing contributors and never produces a result. Trace busy intervals
  describe reserved service; an abort truncates any unfinished reservation.
- Arithmetic is reserved at admission but result visibility waits for the final
  service finish. Result readiness is distinct from an explicit once-only `emit`,
  which is distinct from explicit once-only `deliver` to the root. Completion
  does not imply delivery. A new epoch waits for delivery or abort.
- Arrival, emission and delivery cycles are **exogenous inputs**. Path bytes and
  hop-byte demand are counted, not network-timed. Declared service cycles are
  abstract costs, not router latency calibration or congestion predictions.
- Evidence records accepted/rejected events, missing set, result state, bytes,
  hop demand, accumulator words and contributor bitmap bits. This is not physical
  area, power, bandwidth savings or native performance evidence.

The example has three contributors on a trunk/branch topology, UINT32 overflow,
permuted arrival, one busy rejection/retry and one early-emission rejection.
Expected final result `[4294967295,5]`, emission at 6, root delivery at 9;
accepted inbound 24 bytes/24 hop-bytes and emitted outbound 8 bytes/8 hop-bytes.

## ABSTRACT_MULTICAST_TREE_V1

- Explicit single operation/source, sorted unique destination endpoints, class,
  positive payload bytes, source injection VC and sorted directed CHANNEL/VC
  tree edges. No routing synthesis, adaptive branch selection, reconvergence,
  cycles, disconnected edges, missing destinations or dead/extra branches.
  Local endpoint ejections are derived from explicit destinations and attachment;
  multiple destinations on the same router remain separate obligations.
- VC/class eligibility and **every concrete ingress-to-child VC transition**
  are validated against the actual VC artifact, including injection transitions.
  One incoming CHANNEL/VC per nonroot and one source input VC instantiate FIFOs;
  `input_vc_capacity` explicitly assigns the same capacity to every such FIFO.
- Packetization happens once: canonical payload capacity and max packet flits
  partition original payload into ordered operation/packet/flit/range tokens.
  Every branch keeps token identity and payload range. Canonical unicast header
  fields are **not a multicast wire encoding**; this model uses reference tokens.
  Zero-payload messages are explicitly excluded in v1.
- Each tick uses start-of-tick occupancy/credits; ready FIFO heads advance to ALL
  child FIFOs and ALL local endpoints together, or none advance. Movements commit
  simultaneously. Even a receiver departing this tick must have free space at
  start. One flit/channel/tick; ascending-router deterministic arbitration. One
  source token is injected at end of tick if its explicit ready cycle has passed
  and root space existed at start; it cannot advance in that tick. Pending source
  tokens are reported explicitly, not hidden in a fabric queue.
- A single arborescence has no competing independent trees/flows. The serialized
  arbitration rule is deterministic but this envelope does not claim contention
  modelling for arbitrary traffic. Shared trunk carries each original flit once.
- Explicit per-destination sink capacity, sorted ready ticks and credit return
  delay. Sinks start full, delivery spends one credit, positive delays return at
  the named future tick start; zero delay returns at commit, **never same-tick
  reuse**. Credits + scheduled returns equal capacity at every tick. Delivery
  can finish with credit returns pending; final trace records that ledger.
- Channel hops take one **reference** tick, independent of canonical latency/
  route weight and clocks. FIFO/sink costs are explicit envelope inputs, not
  inferred native buffer/allocator parameters. No wormhole fidelity asserted.
- Destination obligation sets partition at each fork. For every destination and
  original payload flit: pending-source + inflight + delivered = exactly one.
  Global token count is deliberately NOT conserved under network replication.
- `COMPLETE` means exact ordered delivery to every endpoint and all input FIFOs
  drained. `BOUNDED_INCOMPLETE` records outstanding obligations, occupancy,
  credit returns and blocked resources; it is not successful delivery or proof
  of deadlock. No group/setup lifecycle, hardware budget or native readiness.

The example blocks a selected local sink until tick 6, preventing BOTH onward
branches until then. It delivers 43 bytes per endpoint at four endpoints from
one 43-byte source injection. Seven original flits traverse three tree edges:
21 completed edge-flits, `21*65=1365` modeled link wire bits (not rounded bytes).
The non-byte-aligned width and final partial payload range separate payload,
headers and padding without interpreting header/padding as delivered payload.
