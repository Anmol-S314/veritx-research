# Coupled tensor reference V1

Run from `tracks/t3-topology/dse`:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m veritx_dse.application.coupled_tensor examples/coupled_tensor_v5.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q -p no:cacheprovider tests/test_coupled_tensor.py
```

This **COUPLED_TENSOR_REFERENCE_V1** CLI/application profile consumes
[explicit tensor demand](TENSOR-DEMAND-CONTRACT.md), not workload names or
collective byte counts. It is available through the immutable V5 revision
`/api/v1/projects/{project_id}/revisions/{revision_id}/abstract-experiments`
endpoint using exactly `{profile, workload, transport, placement}`; the
revision's request/root is recompiled and demand must bind its design and system
identities. Synchronous API limits are 256 KiB body/root, 64 routers/endpoints,
256 DAG nodes, 64 accesses, 4096 lowered requests and 65536 request/response
flits. The response is diagnostic-only (`qualification: false`), explicitly
reports native execution as unsupported, and is not eligible for generic
promotion. CLI `python -m veritx_dse.application.coupled_tensor <document>`
remains the direct-root path. Existing ABSTRACT_DATA_MOVEMENT_V1 experiments
are unchanged. This is reference evidence, not qualified native or hardware
evidence.

## Input interface

The closed document is `{design, workload, transport, placement}`. Design is the
same complete immutable V5 root; placement is the existing PhysicalPlacement;
transport is RemoteDemandPolicy (explicit control bytes, per-child service
cycles, network clock, request/response classes). Workload is
`veritx/CoupledTensorWorkload` schema 1:

- `demand`: existing TensorDemandWorkload, exact design/system parent hashes,
  immutable exact-cover shards, explicit issuer/owner and BYPASS only.
- `engines`: `{engine_id, clock, capacity}`; compiled clock, capacity 1..256.
- `nodes`: unique `{node_id, kind, deps}` with completion dependencies. ACCESS
  additionally has `access_id`, optional `retry_of`; COMPUTE has `engine_id`,
  `cycles` (>=0), `occupancy` (>0); DRAIN_RESET has `reset_clock`, `cycles` (>=0).
  BARRIER has no other fields. Each demand access has exactly one ACCESS node.
- `initial_images`: tensor ID -> exact lowercase hex for every storage byte;
  no implicit zero-fill. `access_values`: access ID -> exact concatenation of
  block bytes in block order, WRITE payload or expected READ response.
- `horizon_clock`, positive `horizon_cycles`: inclusive compiled-clock bound.

Bounds: 64 engines, 512 nodes, each image/value collection <=16 MiB;
TensorDemandWorkload bounds remain in force, as do existing remote execution
bounds (10k operations/children, 1M flits and its no-ragged-split restriction).
The remote consumer still refuses empty demand and local requests. No engine
cycle count, bytes, cache hits or initial bytes are inferred. Reader refuses
unknown fields, bool/float integers, malformed identities and DAG cycles.

### Optional owner-cache reference

An optional `cache_profile` adds `line_bytes` (power of two), `capacity_bytes`
(positive multiple, <=16 MiB and <=65,536 lines), `lookup_cycles` (>=0) and
`line_fill_service_cycles` (>0). Integers are exact. Each `OWNER_CACHE` access
requires this profile; absent profile and explicit `BYPASS` preserve the prior
execution/evidence path. The unique authoritative tensor owner is the cache
endpoint; this is not a requester cache. Cached tensors must have one owner and
one address space. The modeled cache is fully associative exact LRU with
write-through/no-write-allocate. Its declared cycles use each owner's compiled
transaction clock.

At target-service reservation, the same serialized event loop projects ordered
metadata-only cache transitions to select duration for already queued service.
These projections do not expose bytes or count as completed. At each actual
service completion, a READ hit pays lookup cycles per touched line; a miss pays
lookup plus `line_fill_service_cycles` per missed line, fills the complete line
from initialized persistent bytes and snapshots only the requested response.
These values replace, rather than add to, authored READ `service_cycles` for an
OWNER_CACHE READ. Network requests/responses and requested payload bytes are
unchanged on hits. An entire aligned line must fit in the same authorized shard;
full-line READ permission is checked before any issue. Edge, cross-shard or
uninitialized fills refuse rather than overread or pad.

Writes retain authored write service plus lookup cycles per touched line when
OWNER_CACHE is selected; they are write-through/no-write-allocate and invalidate
overlapping resident lines at service completion. Any ordered write to a cached
owner line, including a BYPASS write, invalidates overlapping owner lines before
later service begins. No dirty/writeback state or requester replicas exist.
Cache fills read owner-local persistent bytes and are accounted separately as
`backing_read_bytes`; they are not network traffic or native Ramulator demand.
Evidence reports per-line ordinary hits/misses, committed lookup/fill service
cycles, invalidations/evictions, dedup lookups/costs, while requested payload
and network accounting remain separate.

Post-retirement retry still uses endpoint/epoch/original-child dedup. Cached READ
retry pays declared lookup cycles but performs no fill, cache mutation or LRU
touch and returns the original committed snapshot. Cached WRITE retry pays
lookup plus authored write service as explicit abstract dedup-lookup/ack cost,
without another mutation or invalidation. Dedup lookups are not ordinary cache
hits/misses. DRAIN_RESET conservatively clears cache and dedup state after drain,
retains bytes and advances epoch. A service beyond the inclusive horizon is only
reserved/in-progress: no fill, mutation, LRU update, snapshot or completed cache
counter is recorded until service completion. These authored effects are not
calibrated hardware timings, native cache equivalence, or a coherent protocol.

## One clock/event authority

`execute_coupled_tensor(compilation, workload, policy, placement)` validates
lowered demand and compiled authorization, then runs the existing addressed
request/FIFO/channel/service/response phases in **one** event queue. The runtime
hook does not execute independent precomputed timings and add their totals.
Requests are materialized for validation but not issued until ACCESS release;
response retirement of all requests/children releases dependents. Compute
completion can release later requests. Slower target service changes subsequent
compute readiness and injection, while independent engines remain unchanged.

Time is exact Fraction seconds, edges at phase zero. Phase completion/byte
visibility/response retirement and compute/reset completion have priority 0;
issue/DAG dispatch have priority 1; serial insertion order breaks remaining
simultaneous ties. Initial DAG/resource contenders use sorted node IDs;
request/child order is the existing canonical demand projection order. Newly
produced priority-zero events participate in bounded same-time closure.
COMPUTE is nonpreemptive; capacity is reserved from readiness through edge-rounded
start and completion (the evidence distinguishes reserved and start times).
Barriers have finite DAG-bounded zero-time closure. Source credit is charged per
child and remains live through response retirement. Compiled STRONG/hazard
edges are retained, lifted to access completion, and checked for new cycles;
compiled reordering remains refused. Unsequenced overlapping accesses containing
a write are refused unless authored/compiled completion order protects them.
Read-read overlap is permitted.

Target service is serial per endpoint; channels/interfaces/crossings are the
existing whole-message reservations. GRAY ASYNC_FIFO equal-flit-width crossings
use existing exact two-clock sampled-pointer execution. FIFO delivery and lane
reuse differ. This is source-credit/backpressure and resource reservation, NOT
native wormhole/receiver-ejection credit flow or DRAM timing. Partial FIFO
counters count **reserved whole bursts**, not words physically transferred before
the horizon. Phase windows can therefore extend beyond a partial horizon.

## Values, retry and reset

At child service completion, WRITE mutates only the exact byte slice, READ
captures an immutable snapshot. Split writes are not parent atomic. READ bytes
travel as the retained response and are checked against authored expected bytes
at response retirement; parent bytes are assembled in block order. Partial
results expose actual returned fragments and `hex=null` until complete: no
fabricated unread bytes. Compiled full-range policy authorization is required
and checked before any child issue/mutation (not hardware firewall proof).

An ACCESS `retry_of` names a unique original access, not another retry. It must
be a retirement predecessor, match issuer, tensor, kind, exact block coverage,
physical child addresses/split and WRITE data, and belong to the same epoch.
The retransmission incurs real reference request/service/response resource
costs and source credits. Endpoint dedup keys are target + epoch + original
access + issuer/kind/address-space/child interval/block identity. READ replays
the original snapshot even after an intervening WRITE; WRITE replays its ACK
without a second mutation. Useful and retransmitted payload/flit counters are
separate. `*_flits_planned` counts both request and future response flits for
issued children, not actual retired flits at a partial horizon. This supports
**authored post-retirement retransmission only**: there
is no automatic timeout, response-loss injection, link retry, retry window,
coherent cache or protocol-specific exactly-once guarantee.

DRAIN_RESET is a global endpoint/crossing barrier comparable to every ACCESS
and every other reset. It waits for predecessor response/credit drain and all
FIFO/channel/interface reusable reservations; then incurs authored reset-clock
cycles. Completion retains tensor images, clears retry snapshots and increments
endpoint epoch. Cross-epoch retries refuse before issue. Descendants remain
blocked during reset. Clocks keep running; independent compute may overlap
endpoint reset. No cancellation, compute reset, power state, reset synchronizer
waveforms, sideband transactions or physical V5 reset declaration is inferred.
Two ordered resets and zero-cycle reset are supported.

## Results and replay

CoupledTensorEvidence binds design/system/workload/demand/placement/policy and
is validated by full parent recomputation via `.from_dict`. Ledger records
request issue -> memory queue acceptance -> child visibility -> response
retirement -> access completion -> dependent compute/release. Evidence includes
engine reservation intervals/peaks, reset drain intervals/epoch, initial/final
image hashes and exact byte contents, response fragments, compiled authorization
and pending dependencies. Child states conserve declared = source-held +
request-inflight + memory-queued-or-servicing + response-inflight + retired;
accepted memory children = service-completed + queued-or-servicing; source live
credits = issued - retired. Retried service completion is counted separately
from bytes actually mutated.

COMPLETE means every node retired with no unresolved children/credits/engine
occupancy. INCOMPLETE stops after processing all events at or before the
inclusive horizon and reports future scheduled work. DEADLOCK is defensive
no-scheduled-progress classification with unfinished nodes/dependencies/source
children, not a claim of native deadlock proof. Valid finite DAGs with this
always-progressing service model normally complete or exhaust the horizon;
tests exercise DEADLOCK with a controlled internal gate fault, not a supported
user fault-mode setting. Invalid/unsupported intent refuses before execution;
wrong expected response bytes fail evidence rather than claiming completion.

## Concrete shared runtime handoff

The existing executor's private `_runtime` hook owns no compiler imports. It
receives `bind(deps, push, wake, trackers, lane_free)` after complete route,
policy, split and authorization validation. `ready(operation_id)` gates real
source issuance; `issued(op, child_record, now, phases)` records ownership;
`service_accepted(op, record, now, start, end)` records queue reservation;
`commit(op, record, now)` executes visibility; `responded(op, record, now,
parent_complete)` retires once; `handle(action, now)` releases DAG resources;
`finish(...)` checks states and emits evidence. Correlation is generated request
ID + child sequence + epoch, with immutable lowered-demand parent identity.

The separate [connected native diagnostic](NATIVE-COUPLED-TENSOR-DIAGNOSTIC.md)
now reuses the logical DAG/byte ownership contracts, supplying actual BookSim
steps/retirements and Ramulator admission/callbacks instead of reference network
or memory phases. Its closed initial envelope is a default single-class mesh
and one HBM2 owner, with no cache, retry/reset or declared crossing execution.
WRITE callback means controller ACK, not physical persistence. The hook remains
private, not a general native adapter ABI or qualified backend. This reference
profile itself remains non-native. No general AXI/CHI equivalence, cache coherence,
atomics/MMIO/speculation, power/sideband execution, metastability, RTL/UVM or
physical signoff is claimed. The optional owner cache is an abstract, single-owner
LRU/service profile only. Protocol names on V5 attachments remain structural
labels, not proof that their endpoint protocol is executed.
