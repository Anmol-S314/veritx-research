# Explicit tensor demand V1

This is an opt-in immutable-layout workload beside the V5 design, **not** a
replacement for canonical collective workloads, legacy op-scoped memory
artifacts, addressed DataMovementWorkload V1, or the Studio experiment API.
Missing catalog memory intent never becomes demand. Compilation continues to
import only model/core semantics, not runtime or simulator modules.

## Authorities and terms

See [domain language](../../../../CONTEXT.md). `model/tensor_demand.py` owns the
strict explicit input. `workload/tensor_demand.py` owns checked lowering;
`application/tensor_demand.py` is its real remote consumer.

- The workload binds the exact bare V5 design digest **and** compiled system
  digest. A successful compilation is revalidated before lowering.
- A tensor has persistent `tensor_id`, `element_bytes`, `element_count`, and
  `size_bytes == element_bytes * element_count`. Shape/dtype/kernel time are
  not inferred. Its immutable shards exactly cover its logical byte extent.
- Each shard declares `shard_id`, logical `offset_bytes/size_bytes`, owner
  `target` (an attached endpoint ID, **not** an HBM device ID or workload rank),
  `address_space`, physical `base_address`, and `transaction_bytes`.
  Logical boundaries are element aligned; physical bases may be unaligned.
  Replicas and physical aliases are refused, including between tensors within
  one `(target, address_space)` scope. Lifecycle/layout changes are not modeled.
- Full storage spans, including unused shards, must fit 64-bit arithmetic and
  the actual target interface width, and be covered by the actual compiled
  GLOBAL IDENTITY decode to the declared target. Adjacent decode entries may
  cover a shard; gaps, foreign targets, and last-byte overruns refuse. There is
  no compiled LOCAL decode: LOCAL placement explicitly refuses.
- An access names `access_id`, tensor, independent `issuer` endpoint,
  READ/WRITE, logical `offset_bytes`, `block_bytes`, positive `count`, positive
  `stride_bytes >= block_bytes`, explicit `deps`, and `cache_policy`.
  Generic demand consumers support `BYPASS`; `OWNER_CACHE` is executable only
  through the coupled owner-cache reference profile and is refused by
  demand-only lowering. Element alignment and final block bounds are mandatory. Blocks in one
  access do not overlap; repeated/overlapping accesses in different access
  records are allowed and remain real demand, not deduplicated cache hits.
- Dependencies name stable access IDs in an arbitrary acyclic DAG, not
  necessarily earlier authored records. Completion of an access means **all
  its generated requests have returned**. Declaration order is identity and
  serialization order only, never an issue schedule or implied ordering edge.
  Empty tensors/access lists are valid and produce no invented requests.
- BYPASS is an explicit uncached demand envelope, **not a cache model**.
  The bounded coupled owner-cache profile is a separate abstract reference and
  is not native/calibrated cache behavior. Authored hits, coherent caches,
  replicas, cache capacity approximations, working-set guesses and cache
  policies other than `BYPASS`/the separate coupled `OWNER_CACHE` profile
  refuse. Demand-only schema has no
  coherence/retry/reset/power/sideband execution or memory values.

Limits: 64 tensors, 256 total shards, 256 accesses, 4096 total blocks,
16 MiB accessed payload, and 65536 generated requests. Transaction granularity
is any explicitly declared positive integer from 1 through 65536 bytes, not a
backend/device-derived default. Backend-specific granularity/alignment limits
belong to a real adapter, which must refuse incompatibility rather than silently
round/reshape this demand. All integers are exact; bool/float do not pass.
Readers reject unknown/missing fields and wrong schema/type tags.

## Generator and conservation

```
lower_tensor_demand(compilation: Compilation,
                    workload: TensorDemandWorkload) -> LoweredTensorDemand
```

The generator emits access authored order, block index, logical shard offset,
then touched transaction address. It uses the shared
`core.memory.byte_transaction_span(start, size_bytes, transaction_bytes)`
authority also used by legacy `memory_lowering.access_tx_range`.

`LoweredTensorDemand.requests` is a tuple of `DemandRequest` with:

- `request_id`, `access_id`, `tensor_id`, `shard_id`, `block_index`,
  `tensor_offset_bytes`, `issuer`, `target`, `address_space`, READ/WRITE `kind`;
- `transaction_address/transaction_bytes`, exact
  `payload_address/payload_bytes`, `front_padding_bytes/back_padding_bytes`;
- access-level `deps` and explicit `cache_policy`.

A request ID is stable **within its parent demand artifact**. Consumers must
correlate `(demand.artifact_id(), request.request_id)`, not trust a request ID
alone as workload identity. Each payload is a contiguous byte slice; front/back
padding defines its implicit contiguous byte-enable mask within the rounded
transaction. Padding is accounting only, never a read/write/authorization of
adjacent storage. A backend lacking partial-byte representation must refuse or
explicitly identify its timing-only abstraction, not claim padded data access.
Repeated accesses may touch the same transaction: they are separate requests.

Per access: declared block payload = shard-fragment payload = request payload.
Globally: rounded transaction bytes = request payload + padding. Storage bytes
are reported separately and are **not** accessed bytes after reuse. Network
control/header/flit bytes belong to the remote consumer, not this audit.

`LoweredTensorDemand.to_dict()` includes parent digests, workload ID, audit,
scope and content ID. Its `from_dict(doc, *, compilation, workload)` and
`revalidate(*, compilation, workload)` rerun lowering and compare full content;
re-hashing a forged ledger does not authenticate it. No timing is simulated:
`timing_modeled=False`, `elapsed_clock_units=null` (not a fabricated zero-time
memory model).

## Actual remote consumer

```
RemoteDemandPolicy(network_clock, control_bytes, service_cycles,
                   traffic_class, response_traffic_class)
project_remote_tensor_demand(compilation, workload, policy) -> RemoteTensorDemand
```

Every transport/service input is explicit and included in projection identity.
`RemoteTensorDemand.workload` is a real existing DataMovementWorkload.
`completion_groups[access_id]` contains its generated operation IDs. Projection
uses stable-ID topological access order to satisfy that consumer's earlier-ID
reader, retaining all block/shard/transaction slices in each access. Every
successor operation depends on **all** predecessor operation IDs; the existing
runner further completes each operation only after all split children return.
Only exact payload addresses/bytes transfer; padding is never on this network.
The existing endpoint policies still own additional ordering, credits,
splitting and authorization. Ragged payload splitting remains refused by the
existing policy rather than weakened here. Remote projection is bounded to
10000 operations (the existing runner cap). Empty demand has no remote
workload; the generator still returns its valid empty result.

The generator can represent `issuer == target`; this remote-only consumer
explicitly refuses local requests. No implicit remote reassignment occurs.
`RemoteTensorDemand.from_dict(doc, *, compilation, workload, policy)` recomputes
the projection, including parent demand identity, service/control inputs and
completion groups. Execution evidence remains existing DataMovementEvidence
bound to the projection workload and checked physical placement.

## Running the connected example

From `tracks/t3-topology/dse`:

```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m veritx_dse.application.tensor_demand examples/tensor_demand_v5.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q -p no:cacheprovider tests/test_tensor_demand.py
```

The example recompiles the supplied V5 root, binds two distinct attached HBM
endpoints, performs a cross-shard strided READ then dependent cross-shard WRITE,
and executes the projection through the existing abstract clock/FIFO/credit/
authorization runner. Its tensor has 64B storage, accesses 52B payload in eight
requests, accounts 128B transactions/76B padding, and transfers 52B network
payload. The authored-service abstract runner completes at exactly
17/40000000 seconds (425 ns). This is **not** BookSim/Ramulator coupling, DRAM
latency inference, memory-value correctness or AXI equivalence. AXI labels on
authored interfaces do not upgrade the abstract evidence. The example explicitly
uses no endpoint splitting so byte-sized remainders do not trip the retained
ragged-splitting refusal.

## Handoff to later execution writers

Use the typed workload and `lower_tensor_demand` as the single demand authority;
do not duplicate addresses or guess demand from collectives. Runtime scheduling
must honor the access-completion DAG, not inject the authored-order stream in
advance. Local consumers need their own supported execution semantics. Compute
nodes, durations, resources/occupancy, time/phase policy, native admission and
completion correlation remain separately authored runtime contracts, not fields
invented by this generator. The current running abstract consumer uses exact
Fraction seconds and completion-before-issue phases; this is not yet an approved
universal native-clock ordering policy. Native granularity/configuration must
be bound and checked by a real adapter against the declared layout. No native
backend or scheduler API is created speculatively here.

Solved: strict persistent explicit tensor/address/shard demand and connected
remote projection with byte conservation and parent-validated replay. Partial:
workload-to-memory semantics as a whole; cache state, values/coherence, changing
ownership/lifecycle and local execution are not modeled. Native feedback,
compute/resource overlap, protocol retries/sideband/reset/power, RTL/UVM and
physical signoff are outside this slice. Dirty-tree runs are diagnostics, not
qualified source/build evidence.
