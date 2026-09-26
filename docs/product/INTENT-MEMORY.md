# INTENT-MEMORY — Domain I specification (Gate 2, closure)

Domain row: `intent-ontology.yaml :: domains.MEMORY_INTENT`
Enforced by: `scripts/check_intent_ontology.py`
Status: **PLANNED — COHERENT.** See §49.

---

## 0. Reality header — two pipelines, **no edge between them**

```text
MEMORY INTENT (canonical, in the compile path)
  MemoryIntentV4 { address_map }
    → AddressDecodeArtifact
    → FabricArtifact

MEMORY EVALUATION (real engine, NOT product-wired)
  Phase-9 memory semantics (operand bytes + location grammar)
    → MemoryLowering
    → Ramulator-compatible request artifact
    → MemoryEvaluationProfile
    → Ramulator execution
    → MemoryEvidence
```

**No implicit edge connects these two pipelines today, and none is invented.**
Proven both ways: `build_artifact` is invoked only from
`workload/memory_lowering.py:331`; `RamulatorBackend` has no service, gateway,
CLI or evaluation caller; the only `veritx_dse.simulation` imports in the product
are `run_booksim` and `serving_loop`.

| Concept | Reality | Evidence |
|---|---|---|
| `AddressMap`/`AddressRange` | **R2 canonical input** | `model/compile_model.py:676,660` |
| `addr_width` | **R2 consumed** — the design-level address bound | `model/address_decode.py:405` |
| address decode | **R3 derived, version-bound** | `model/address_decode.py:464,72` |
| Phase-9 operand bytes + location grammar | **R1 legacy, memory-evaluation input authority** | `workload/canonical.py:102,118` |
| `MemoryArtifact` | **R3 derived, unwired** | `core/memory.py:431` |
| `MemoryLoweringManifest` | **R3 derived, hash-linked, version-bound** | `workload/memory_lowering.py:535` |
| `RamulatorGeometry` / profile envelope | **R4 backend** | `workload/memory_lowering.py:389`, `simulation/ramulator.py:56` |
| Ramulator execution + evidence | **R4 backend, unwired** | `simulation/ramulator.py:80,136` |
| compute→memory binding | **R0** | — |
| data→memory binding | **R0** | — |
| channels / capacity / technology | **R4 backend-only** | `RamulatorGeometry` |
| network+memory coupling | **R0** | standalone trace execution |
| memory metrics in the registry | **R0** | `optimization/metric_registry.py:272` |

## 1. Domain boundary

SYSTEM owns memory agents, `AgentInstance`/`AgentGroup` identity and the agent
interface `addr_width`. PLACEMENT maps participant→compute agent and does **not**
map data to memory. FABRIC connects endpoints. EVALUATION owns the network clock.
**MEMORY owns address-space ownership. Exactly one authority.**

## 2. Current authorities

| Concept | Symbol | Path | Authority | Consumer | Target owner |
|---|---|---|---|---|---|
| address ranges | `AddressMap`/`AddressRange` | `model/compile_model.py:676,660` | **canonical intent** | decode derivation | **MEMORY** |
| design address bound | `Agent.interface.address_width_bits` | `model/address_decode.py:405` | **canonical** | decode | SYSTEM |
| decode table | `AddressDecodeArtifact` | `model/address_decode.py:256` | compiler | `FabricArtifact` | compiler |
| decode policy | `ADDRESS_DECODE_SCHEMA_VERSION = 3` | `model/address_decode.py:72` | compiler | artifact identity | compiler |
| operand bytes + location | `WorkloadOp.*_bytes`/`*_loc` | `workload/canonical.py:102` | **Phase-9 legacy** | `_resolve_location` | legacy adapter |
| memory regions/accesses | `MemoryArtifact` | `core/memory.py:431` | unwired derived | trace lowering | evaluation |
| region allocation | `AddressMappingPolicy` | `core/memory.py:133` | unwired derived | region allocation | evaluation |
| geometry | `RamulatorGeometry` | `workload/memory_lowering.py:389` | backend profile | trace lowering | evaluation |
| lowering manifest | `MemoryLoweringManifest` | `workload/memory_lowering.py:535` | derived, version-bound | execution | evaluation |
| execution | `RamulatorBackend` | `simulation/ramulator.py:80` | backend | nothing | evaluation |
| evidence | `MemoryEvidence` | `simulation/ramulator.py:136` | backend | nothing | evaluation |

## 3. `MemoryIntentV4` is `AddressMap` only

```text
MemoryIntentV4 { address_map: AddressMap }
```

**Locked out** (none is design-level canonical intent): memory technology, HBM
generation, channel count, bank count, DRAM timing, memory clock, capacity, queue
policy, scheduler, Ramulator config, memory latency target, locality policy.

Each is either backend configuration (`RamulatorGeometry`, the `SUPPORTED`
envelope) or absent (capacity, technology, channels — R0/R4, §12–14).

## 4. Ownership decision — **MEMORY**

SYSTEM keeps: memory agents, `AgentInstance`/`AgentGroup` identity, the agent
interface `addr_width`.
MEMORY owns: **address-space ownership**.

**SYSTEM retains no second independently editable `AddressMap`.**

## 5. Target identity — **`AgentInstanceId`** (decisive)

**Resolution of instance-vs-group: the semantic owner is the unique
`AgentInstance`.**

Evidence, from the decoder itself:

- `AddressDecodeEntry` carries **both** `target_agent_group` **and**
  `target_endpoint_id`; the hardware identity key is
  `(base, size, target_agent_group, target_endpoint_id)` —
  `model/address_decode.py:171`.
- A range targets a **group only as input convenience**; derivation resolves it to
  **exactly one attached endpoint** and requires `count == 1`
  — `model/address_decode.py:440-460`.
- The restriction's stated reason is an **absence of semantics**, not a design
  choice: *"the design model defines no selection/interleave policy for
  distributing a range across instances"* — `model/address_decode.py:402,452,496`.

So a group target is only usable when it happens to contain one instance — **an
accidental legacy abstraction**. v4 therefore:

```text
AddressRange.target : AgentInstanceId      # stable SYSTEM identity
```

This removes the `count == 1` restriction **by construction** rather than by
adding a selection policy nobody asked for.

**MEM-D1** records the migration from `target_agent_idx`.

## 6. Memory-capable target eligibility

v4 law — an `AddressRange` target **MUST** be a `HBM_CONTROLLER` instance.

```text
COMPUTE_TILE  → INVALID
NIC           → INVALID
PERIPHERAL    → INVALID
UCIE_PORT     → INVALID
```

`HBM_CONTROLLER` is the **only** canonical memory-owning `AgentKind`; no second
kind is proven by code. **No generic `memory_capable=true` property is created** —
there is no consumer for one.

**MEM-D4** records that `derive_address_decode` today applies **no kind
restriction at all** — any singleton agent group is addressable.

## 7. Legacy compute-target maps

A legacy `AddressMap` whose target is not a memory agent is **not silently
migrated into valid v4 science.** Options are: preserve through the legacy
compatibility adapter, or **migration refusal**. The target is never
reinterpreted. The semantic incompatibility is recorded explicitly (§39, I59).

## 8. Address-range representation — exact

```text
base : int >= 0        # inclusive start
size : int >= 1        # byte count
[base, base + size)    # half-open
```

Half-open is **the existing convention**, not a change:

- `AddressRange.base` is documented `# start address (inclusive)`
  — `model/compile_model.py:661`;
- `AddressDecodeEntry` validates `base + size > ADDRESS_DOMAIN_SIZE` and renders
  ranges as `[base, base+size)` — `model/address_decode.py:197,249`.

## 9. Non-empty range law

`size >= 1` is enforced at declaration (`_as_int(..., minimum=1)`,
`model/compile_model.py:668`) and at decode (`_as_positive_int`, `:195`).

```text
size == 0        → INVALID
base < 0         → INVALID
reverse interval → INVALID (unrepresentable in this form)
```

## 10. Address-width bound — two nested bounds

```text
ADDRESS_DOMAIN_BITS = 64                    # model/address_decode.py:73
ADDRESS_DOMAIN_SIZE = 1 << 64               # :74

bound 1 (declaration)  base + size <= ADDRESS_DOMAIN_SIZE
bound 2 (design)       base + size <= (1 << endpoint.interface.address_width_bits)
```

Bound 2 is the **real design-level law**: exceeding it refuses `UNSUPPORTED`
because *"no translation/truncation adapter exists"* under
`AddressTransform.IDENTITY` — `model/address_decode.py:405-412`.

**Checked integer arithmetic is required** when constructing `end`, `size` or the
maximum address; overflow must refuse, never wrap (I43).

## 11. Non-overlap law — forbidden

```text
two ranges MUST NOT overlap
```

Two ranges assigning one address to two owners is ambiguous. **No first-match,
last-match or declaration-order authority is permitted.**

The law **is already implemented**, in the derived artifact:
`_validate_entries` sorts by the semantic key and refuses
`prev.base + prev.size > cur.base` — `model/address_decode.py:246-250`.

**But it is not intrinsic validation.** `AddressMap.validate_no_overlaps()`
exists (`model/compile_model.py:794`) and **has zero callers** — it is dead code.
So an overlapping `AddressMap` can be *declared* and only fails later, at decode
derivation.

**MEM-D3** records promoting the overlap law to `MemoryIntent` intrinsic
validation. The law itself is settled; only its enforcement stage moves.

## 12. Gap law — gaps are legal

Total address-space coverage is **not** required. No consumer scientifically
requires it: the decoder is `AddressTransform.IDENTITY` with
`UnmatchedAddressPolicy.ERROR`, so an unmapped address is a **typed refusal**, not
a silent fallback.

```text
address in no region → UNMAPPED_ADDRESS at decode/use time
```

This permits intentionally partial memory maps.

## 13. Adjacent ranges

Adjacent non-overlapping ranges are **valid**:

```text
[A, B) [B, C)     # legal; the overlap test is `prev.end > cur.base`
```

Canonicalization **must not merge** them automatically when targets differ — and
`_expected_entries` never merges (`model/address_decode.py:461`).

## 14. Canonical range ordering

Deterministic and already enforced:

```text
(base, size, target_agent_group, target_endpoint_id)      # _semantic_key
```

`_validate_entries` **requires** entries in this order — `:238`. Input row order
does not affect identity; reordering ranges in Studio is not a scientific change.

## 15. `AddressMap` identity

Scientific identity includes: address ranges · stable target identities ·
address semantics version.
It **excludes**: display labels · row order · hex/decimal presentation · UI
grouping.

Confirmed by code: `name` is deliberately absent from `semantic_dict()` and
`validate_against` states *"Range names are presentation and do not participate:
two design revisions differing only in range labels reuse the same hardware decode
artifact"* — `model/address_decode.py:203,420`.

## 16. Address decoding stays derived

```text
MemoryIntent
+ System agent / address-interface context
+ AddressDecodeSemanticsIdentity
  → AddressDecodeArtifact
```

The decode table is **never editable**.

## 17. `AddressDecode` semantics identity — **exists**

`ADDRESS_DECODE_SCHEMA_VERSION = 3` (`:72`) participates in the artifact's
content identity (`content_id(f"{_HASH_TYPE_TAG}/v{schema_version}", ...)`, `:313`).
Changing range-search semantics, the boundary convention or target resolution
**cannot silently preserve artifact identity**.

This matches the discipline established for Mapping, Attachment and VC assignment.
**No debt.**

## 18. `AddressDecode` target integrity

Derived entries carry **stable identity**: `target_endpoint_id` is the canonical
hardware owner, and the artifact already refuses to downgrade to a bare ordinal.
Where compiler internals need ordinals (`group_index`), that is an **explicit
projection**; stable identity stays authoritative.

## 19. No compute→memory placement contract

```text
COMPUTE_TO_MEMORY_BINDING: CONTRACT NOT AVAILABLE
```

There is no canonical `compute agent → memory controller` relation. **No "nearest
HBM", "local HBM" or "paired HBM" is invented** from hierarchy or array order.
MemoryIntent coherence does **not** require this contract.

## 20. No semantic data→memory placement contract

```text
DATA_PLACEMENT: CONTRACT NOT AVAILABLE
```

Address *ownership* exists; there is no canonical relation
`tensor / parameter / KV cache / activation / operand → memory resource` for the
v4 canonical workload. **`AddressMap` is not a tensor-placement model.**

## 21. Locality cannot be claimed

Because §19 and §20 are unavailable, the product **cannot** truthfully claim
local memory placement, remote placement quality, HBM affinity or a memory
locality score for canonical v4. Locality is **never** inferred from SYSTEM
hierarchy.

## 22. Legacy Phase-9 memory semantics — correctly scoped

```text
LEGACY / MEMORY-EVALUATION INPUT AUTHORITY
```

Operand bytes and the location grammar are **real and consumed** by
`memory_lowering` and tested — but they are **not** `WorkloadIntentV4`. The
adapter stays scientifically meaningful for standalone Ramulator analysis.

## 23. No injection back into `WorkloadIntentV4`

Domain B rejected blind union of workload generations. **Preserved.** `location`,
`duration_ns` and memory operand metadata are **not** added to `WorkloadIntentV4`
to make wiring easier. Future canonical memory operations require a deliberate
new Workload contract.

## 24. Ramulator chain — locked product state

```text
ENGINE:                    AVAILABLE
TESTED:                    YES
PRODUCT ENTRY POINT:       NOT AVAILABLE
CANONICAL DESIGN INTEGRATION: NO
NETWORK COUPLING:          NO
SERVING COUPLING:          NO
```

Better than deleting the work or pretending it is integrated.

## 25. Future product location

```text
Evaluate → Memory          # profile, qualification, run, result, evidence
Design   → AddressMap only # no timing knobs
```

## 26. Product-wiring debt

```text
MEM-EVAL-D1: wire a canonical product entry point for standalone qualified
             Ramulator evaluation (gateway method / CLI / service endpoint —
             chosen when the application architecture is settled).
```

**Not wired during this planning pass.**

## 27. Product-facing terminology

Until MEM-EVAL-D1 lands:

```text
"RAMULATOR ENGINE AVAILABLE"
"MEMORY EVALUATION NOT PRODUCT-WIRED"
```

**Never** `"Ramulator integrated"` in Studio capability UI. Internal engineering
docs may say the backend implementation exists.

## 28. `MemoryEvaluationProfile` v1 — versioned envelope

The fixed v1 envelope is now exact:

```text
SUPPORTED = {dram_class: "HBM3", controller: "HBM34",
             mapping_algorithm: "sequential_bankstriped_v1"}     # ramulator.py:56
driver constants: scheduler FRFCFS · row_policy Open ·
                  refresh_manager NoRefresh · clock_ratio 4/1   # ramulator.py:203-214
```

Formalized as a **versioned `MemoryEvaluationProfile`**. Individual fields are
**not** exposed as arbitrary user controls while only one qualified combination
exists.

## 29. Profile identity

A profile has stable identity + semantics version. Changing technology,
scheduler, row policy, refresh policy, clock ratio or geometry **must change
profile identity**. Unsupported combinations → `UNSUPPORTED`; the nearest
supported profile is **never** substituted.

**MEM-EVAL-D2**: `backend_config_payload` hashes only
`{geometry, mapping, transaction_bytes}` (`memory_lowering.py:578`). Scheduler,
row policy, refresh and clock ratio are **fixed by construction in the generated
driver but absent from the hash**. Today only one driver exists, so nothing is
ambiguous — but the identity is incomplete and must be closed before a second
profile can exist.

## 30. Qualification is two-dimensional

```text
request_generation : recorded stream (the artifact's assumptions)
dram_timing        : MEMORY_CYCLE_SIMULATION
```

Both are stated. **Never** collapsed into `HIGH`/`MEDIUM`/`LOW` or
`"high fidelity"`. Code: *"the request-generation fidelity rides in the artifact's
assumptions, never collapsed into one 'high fidelity' label"* —
`simulation/ramulator.py:137,497`.

## 31. Qualification claim scope — explicit limits

**Qualified:** given this request stream, under this pinned Ramulator profile, the
backend simulates DRAM-cycle service behaviour with a reconciled drain.

**NOT proven:** hardware latency · real HBM performance · NoC-inclusive memory
latency · end-to-end model execution time · calibrated accuracy.

## 32. Drain contract — four typed verdicts

```text
issued == accepted == served          → PASS
accepted < issued                     → INCONCLUSIVE (backend loss)
served + coalesced < accepted          → INCONCLUSIVE (drain shortfall)
crash / timeout                       → EVALUATION_FAILED (evidence + debris, never INFEASIBLE)
unsupported geometry                  → UNSUPPORTED (no execution)
```

Coalesced writes count as completed and are independently reported. **Never
reduced to boolean success**; a PASS must be independently checkable from
evidence (`simulation/ramulator.py:19-24,467`).

## 33. Standalone memory timing

```text
current Ramulator evaluation = standalone trace execution
```

Request arrival/service timing is **not causally coupled** to BookSim, ASTRA or
the serving scheduler. No coupled-system claims.

## 34. Latency addition is forbidden

```text
BookSim latency + Ramulator latency  →  MUST NOT be summed into "end-to-end latency"
```

The simulations do not share a coupled timing model. This prohibition belongs to
the Memory domain, the Analysis layer and Studio's metric-composition policy.

## 35. Network+memory coupling — future contract

```text
NETWORK_MEMORY_COUPLING: FUTURE CAPABILITY CONTRACT
```

Not v4 implementation debt. It would require explicit semantics for request
arrival coupling, network transport to the controller, memory service delay,
response transport, backpressure/stall propagation and a shared time domain.
**Not solved here.**

## 36. LOCAL / REMOTE — **corrected: only LOCAL resolves**

The first-pass audit said REMOTE "resolves against a memory design". **That was
wrong.** Re-reading `_resolve_location` (`workload/memory_lowering.py:119-150`):

| Token | Actual behaviour |
|---|---|
| `LOCAL` | **resolves** → `design.placement_for_local()` |
| `LOCAL:<dev>` | resolves **only if** the device **is** the HBM pool; otherwise `UnsupportedSemantic` (*"a LOCAL claim on another device is a remote access mislabeled"*) |
| `REMOTE` / `REMOTE:<dev>` / `REMOTE:<dev>.<chan>` | **REFUSED** — *"REMOTE implies a fabric traversal to another device's memory — a different system path, not pool HBM. Refused (never silently remapped)."* |
| `CXL` | **REFUSED** — *"CXL-attached memory is not the HBM pool."* |
| `STORAGE` | **REFUSED** — *"off-package storage is never HBM."* |
| anything else | **REFUSED** — *"unresolvable against the v1 memory design"* |

So the grammar's referent is **the v1 HBM pool**, and everything outside it fails
closed. These tokens remain inside the **legacy evaluation adapter** and are
**never** introduced into `MemoryIntentV4`.

## 37. CXL / STORAGE — accepted grammar, no execution semantics

Verdict for both: **LEGACY-ONLY / FUTURE.** Accepted by the parser, **explicitly
refused at lowering**, never displayed as a supported product capability.

## 38. PIM

`KIND_PIM_CHANNEL` / `KIND_PIM_END` are legacy graph markers. **No canonical or
backend capability exists.** `LEGACY VOCABULARY / FUTURE CAPABILITY`. **Not in
`MemoryIntent`.**

## 39. KV cache

Serving does not call Ramulator (`serve_canonical` imports `serving_loop`).
**KV memory evaluation is NOT AVAILABLE**, and it is **not** inferred from
LLMServingSim's KV behaviour. Serving memory semantics and standalone Ramulator
are disconnected.

## 40. Static memory evaluation — exact input source

```text
STATIC LEGACY MEMORY ANALYSIS
```

Static memory evaluation requires the **Phase-9 `WorkloadArtifact`**
(`resolve_memory(art: WorkloadArtifact, ...)`). It is **not** canonical
`WorkloadIntentV4` memory analysis, and the product must **not** imply that all
static v4 workloads can use Ramulator.

## 41. Memory request representation — reuse, do not reinvent

The existing artifact is **sufficient** as the standalone evaluation input:

```text
MemoryArtifact { regions, accesses, mapping_policy, source_workload_hash, artifact_hash }
```

`build_access(access_id, source_op_id, region_id, …)` carries **parent
provenance**, and `execute()` refuses a trace that does not match the manifest's
artifact hash. **`MemoryRequestArtifactV4` is NOT invented.** Smallest truthful
change wins.

## 42. Memory lowering semantics identity — **exists** (MEM-D2 withdrawn)

`MemoryLoweringManifest` binds `schema_version`, `source_memory_artifact_hash`,
`access_stream_hash`, `backend`, `lowerer`, `mapping_algorithm`,
`backend_config_hash`, `trace_sha256`, `coverage`, `semantic_losses`,
`unsupported` — `workload/memory_lowering.py:535`.

And substitution is refused outright:

> `mapping != MAPPING_ALGORITHM` → *"a new order is a new version, not a
> [parameter]"* — `:601`

`backend_config_payload` is recomputed by `execute()` to verify the declared hash
(**tamper-closed chain**, `:578`). **Request generation cannot change silently
under the same scientific identity.** The first-pass MEM-D2 is **withdrawn as
already satisfied**; only the profile-scope gap of §29 remains.

## 43. Backend trace is a projection

The Ramulator `ReadWriteTrace` is a **projection**, never identity authority. If
the same semantic requests serialize differently under another projection version,
**canonical request identity is unchanged** and only projection semantics identity
changes.

## 44. Ramulator executable identity

```text
producer = {name: "ramulator", version: RAMULATOR_VERSION,
            commit_sha: VENDOR_PIN, binary_sha256: <content hash>}
```

— `simulation/ramulator.py:102`. Identity binds **binary content**, the **vendor
pin**, and the profile/config hash. **Pathname alone is never identity**; a
different Ramulator build is not automatically the same producer.

## 45. Memory clock

DRAM timing clock stays independent. It is **not** equated with `design_clock_hz`,
`network_clock_hz` or the serving clock. Any conversion must come from the
`MemoryEvaluationProfile`. **No global clock abstraction.**

## 46. Metric inventory and decision

The registry holds **three metrics, all network**
(`optimization/metric_registry.py:272`): `completion_cycles`, `completion_time`
(producer `authenticated-network-window-cycles`) and `completion_ns`
(`authenticated-network-window-wall-time-ns`). **Zero memory metrics.**

Ramulator's real outputs:

```text
typed stats : completion_cycles(cycles) · average_read_latency_cycles(cycles)
              average_write_latency_cycles(cycles) · row_hits(requests)
              row_misses(requests) · row_conflicts(requests)
              read_queue_len_avg(requests) · write_queue_len_avg(requests)
counters    : issued_read_transactions · issued_write_transactions
              coalesced_write_requests · completed_read_bytes
              completed_write_bytes · generated_requests · accepted_requests
              completed_requests · outstanding_requests
```

**Decision: no memory metric is registered, and none is fabricated to close the
domain.** The single strongest candidate is **`completion_cycles`** (DRAM-clock
cycles to drain this exact stream). It satisfies *meaning · unit (cycles) · time
domain (DRAM clock) · qualified producer (binary_sha256 + profile) · semantics
version (`schema_version=1`)* — but it fails **target/population**: it describes
**one execution attempt over a legacy-sourced request stream**, not a
design-level population.

**MEM-METRIC-D1 (conditional)** records registering `dram_completion_cycles` once
a `RequirementV4` population/target contract exists. **No speculative metric
family is created.**

## 47. Requirements integration — explicitly deferred

Domain E is **unchanged**. `MEMORY REQUIREMENT TARGETS: DEFERRED`.

**This does not block Memory coherence.** The absence of a registered memory
metric is an explicitly unavailable integration, not an unresolved ambiguity.

## 48. `AddressMap` vs Ramulator — the domain's most important boundary

```text
AddressMap world  ≠  Ramulator world
```

Canonical `MemoryIntent` `AddressMap` does **not** configure standalone Ramulator
— **no bridge exists**. They stay disconnected in target v4 until a formal adapter
is designed.

**Initially surprising non-dependencies, documented honestly:**

- a Ramulator profile change does **not** alter `MemoryIntent`,
  `AddressDecodeArtifact` or `FabricArtifact` (evaluation configuration);
- an `AddressMap` change does **not** mutate Ramulator evidence, because the
  standalone legacy evaluation **does not consume `AddressMap`**.

I62 proves the disconnection from the other direction.

## 49. Future bridge classification

```text
CANONICAL_MEMORY_TO_RAMULATOR_BRIDGE: FUTURE CAPABILITY CONTRACT
```

A bridge would connect *canonical memory operation/data semantics + `AddressMap`
→ memory-controller-targeted request stream → Ramulator*. It requires four
missing contracts: semantic memory operation · data placement · memory-agent
binding · request timing. **Not v4 debt.**

---

## 50. Validation taxonomy

```text
MemoryIntent intrinsic (declaration)
  INVALID_RANGE          base < 0, size < 1, reverse interval
  OVERLAP                two ranges claim one address            [MEM-D3: stage]
  INVALID_TARGET_KIND    target is not HBM_CONTROLLER            [MEM-D4]
  AMBIGUOUS_OWNERSHIP    duplicate semantic range
  OUT_OF_WIDTH           base + size exceeds the domain bound
  UNKNOWN_SCHEMA         fail closed

Cross-domain binding
  MISSING_TARGET_INSTANCE
  TARGET_IDENTITY_MISMATCH

Decode / use time
  UNMAPPED_ADDRESS       identity transform + ERROR policy
```

**These are never collapsed into one error.**

## 51. Memory evaluation failure taxonomy

Separate from `MemoryIntent` validation:

```text
UNSUPPORTED_PROFILE · UNSUPPORTED (geometry) · EVALUATION_FAILED ·
PARSE_FAILED · INCONCLUSIVE (drain) · UNMEASURABLE
```

**An unsupported Ramulator profile is never reported as an invalid
`MemoryIntent`.**

## 52. Change / invalidation laws

| Change | MemoryIntent | AddressDecode | Fabric | Ramulator evidence | Mapping | Topology |
|---|---|---|---|---|---|---|
| AddressMap change | **changes** | changes | changes as the parent graph dictates | **unchanged** (no bridge) | unchanged | unchanged |
| range display reorder | **no change** | no change | no change | no change | unchanged | unchanged |
| range name change | **no change** | no change | no change | no change | unchanged | unchanged |
| target `AgentInstanceId` change | **changes / breaks** | changes | changes | unchanged | unchanged | unchanged |
| SYSTEM memory-agent identity change | **binding stale/invalid** | changes | changes | unchanged | unchanged | unchanged |
| Ramulator profile change | no change | no change | no change | **changes** | unchanged | unchanged |
| DRAM clock change | no change | no change | no change | **changes** | unchanged | unchanged |
| network clock change | no change | no change | no change | **unchanged** | unchanged | unchanged |
| router arbitration change | no change | no change | no change | **unchanged** | unchanged | unchanged |
| requirement threshold change | no change | no change | no change | **reusable** | unchanged | unchanged |
| mesh → torus | no change | no change | changes | **unchanged** | unchanged | changes |

## 53. Reuse law

Memory evidence is reusable when **request identity · backend producer/profile ·
semantics version · time-domain config** are unchanged. Requirement thresholds,
fabric routing and arbitration do **not** affect it (no coupling).

## 54. Migration

| Legacy | Target owner | Lossless? |
|---|---|---|
| `AddressRange.target_agent_idx` → `AgentInstanceId` | MEMORY, via **SYSTEM's one stable identity map** | **yes if the group has exactly one instance; otherwise REFUSE** |
| range `base`/`size` (already half-open) | unchanged | yes, mathematically identical |
| `addr_width` | SYSTEM | unchanged |
| Phase-9 operand bytes | legacy evaluation adapter | preserved, not promoted |
| location grammar | legacy evaluation adapter | preserved, not formalized |
| `RamulatorGeometry` / config | `MemoryEvaluationProfile` | n/a |
| unknown memory schema | **fail closed** | n/a |

**No guessing.** If a legacy group holds two memory instances and the old
semantics cannot select one, migration **refuses**.

## 55. Canonical contracts

`AddressMap`/`AddressRange` `compile_model.py:676,660` · `AddressDecodeArtifact` +
`AddressDecodeEntry` + `_semantic_key` + `_validate_entries` +
`derive_address_decode` `address_decode.py:256,182,171,230,464` ·
`ADDRESS_DECODE_SCHEMA_VERSION`/`ADDRESS_DOMAIN_BITS` `:72,73` · `MemoryArtifact`/
`MemoryRegion`/`MemoryAccess`/`AddressMappingPolicy` `core/memory.py:431,191,279,133` ·
`MemorySystemDesign`/`resolve_memory`/`RamulatorGeometry`/
`lower_to_ramulator_trace`/`MemoryLoweringManifest`/`MAPPING_ALGORITHM`/
`backend_config_payload` `memory_lowering.py:68,203,389,590,535,381,578` ·
`SUPPORTED`/`RamulatorBackend`/`MemoryEvidence`/`_TYPED_STATS`
`simulation/ramulator.py:56,80,136,62` · `WorkloadOp` operand fields
`workload/canonical.py:102`.

## 56. Capability matrix

| Capability | Declared | Lowered | Executed | Qualified | Evidence |
|---|---|---|---|---|---|
| `AddressMap` | **yes** | yes (decode) | n/a | n/a | in `FabricArtifact` |
| canonical compile decode | — | **yes** | n/a | schema v3 | `AddressDecodeArtifact` |
| multiple memory agents | via SYSTEM | yes, stable targets | n/a | — | — |
| compute→memory affinity | **unavailable** | no | no | — | — |
| data / tensor placement | **unavailable** | no | no | — | — |
| static legacy Ramulator | backend | **yes** | **engine only** | v1 envelope | `MemoryEvidence` |
| canonical `WorkloadV4`→Ramulator | **unavailable** | no | no | — | — |
| serving → Ramulator | **unavailable** | no | no | — | — |
| network+memory coupled | **unavailable** | no | no | — | — |
| CXL | grammar only | **refused** | no | — | — |
| STORAGE | grammar only | **refused** | no | — | — |
| PIM | legacy markers | **no** | no | — | — |
| KV serving memory | **unavailable** | no | no | — | — |
| memory Requirements | — | — | **deferred** | — | — |

## 57. Advanced capabilities (real)

Canonical half-open address decoding with a **64-bit domain bound and a
per-endpoint width bound** · a group-singleton law with identity forwarding ·
**overlap refusal** and duplicate-semantic-range refusal · **canonical ordering
enforced at construction** · name-independent identity · version-bound decode
semantics (schema v3) · a hash-linked, version-bound memory lowering manifest ·
tamper-closed execution that re-verifies the manifest against its source · a
**pinned binary-content producer identity** · a **four-verdict drain contract** ·
**two-dimensional honest fidelity labelling** · fail-closed refusal of
`REMOTE`/`CXL`/`STORAGE`.

## 58. Unsupported / deferred

compute→memory binding · data→memory binding · locality · canonical channels ·
capacity · canonical technology · CXL · STORAGE · PIM · KV memory · serving
memory · network+memory coupling · the canonical→Ramulator bridge · memory metrics
in the registry · memory `RequirementV4` targets · Ramulator product wiring.

## 59. Required user flows

```text
System → Memory  (advanced)
  Address width   48-bit        (read-only, from the agent interface)
  Regions
    0x0000_0000 – 0x3FFF_FFFF → HBM controller 0
    0x4000_0000 – 0x7FFF_FFFF → HBM controller 1
  Validation: no overlaps · 2 mapped regions
```

**No Ramulator timing on the Design side.**

```text
Evaluate → Memory   (when MEM-EVAL-D1 lands)
  Backend        Ramulator
  Profile        Qualified HBM3 profile v1
  Input          legacy memory request artifact (exact source)
  Coupling       STANDALONE MEMORY ONLY
  Qualification  request-generation: recorded stream
                 dram-timing:        MEMORY_CYCLE_SIMULATION
  Result / Evidence
  NETWORK DELAY NOT INCLUDED
```

## 60. Adversarial cases I1–I50 (revised verdicts)

I1 single HBM controller → VALID · I2 multiple controllers → VALID with stable
instance targets · I3 one region → VALID · I4 two disjoint regions → VALID ·
**I5 overlap → INVALID v4** (law §11; enforcement stage MEM-D3) ·
**I6 unmapped address → `UNMAPPED_ADDRESS`** · **I7 exceeds width → refuse
(`OUT_OF_WIDTH` / UNSUPPORTED at decode)** · I8 zero-length → `INVALID_RANGE` ·
I9 nonexistent memory agent → invalid bound intent (`MISSING_TARGET_INSTANCE`) ·
**I10 compute target → INVALID in v4** (MEM-D4) · I11 agent reorder → stable id
prevents semantic change · I12 legacy target index → migrate through SYSTEM's map ·
I13 unresolvable legacy index → **refuse** · **I14 LOCAL → resolves to the v1 HBM
pool** · **I15 REMOTE device → REFUSED** · **I16 REMOTE device.channel →
REFUSED** · **I17 CXL → refused, legacy-only** · **I18 STORAGE → refused,
legacy-only** · I19 PIM → legacy only · I20 KV_READ/WRITE → no canonical static
equivalent; serving-memory integration unavailable · I21 same requests, different
profile → request identity same, **evidence/producer context differs** ·
I22 request reorder → canonical semantics stable · I23 execution succeeds → PASS
only if `issued == accepted == served` · I24 process fails → `EVALUATION_FAILED`,
never zero · I25 missing metric → typed failure, never zero · I26 DRAM clock change
→ evidence identity changes · **I27 network clock change → standalone Ramulator
evidence unchanged** · **I28 mesh→torus → standalone memory evidence unchanged** ·
I29 requirement threshold → reusable · I30 compute mapping change → no effect
(no data placement exists) · **I31 HBM endpoint attachment change → standalone
Ramulator unchanged today** (NoC not coupled) · I32 display-order change → same
identity · I33 range reorder → same canonical identity · I34 target display-name
change → same semantics if `AgentInstanceId` unchanged · I35 agent moved hierarchy
→ parent/context effect per SYSTEM law · I36 two controllers with no binding law →
honest ambiguity classification · **I37 remote memory without coupling → never
claim NoC-inclusive latency** · **I38 UI summation → FORBIDDEN** · **I39 serving
Ramulator request → NOT AVAILABLE** · I40 unknown schema → fail closed ·
I41 many ranges → deterministic canonicalization · I42 boundary at max address →
refuse on overflow · I43 overflow constructing `end` → refuse · **I44 adjacent
ranges → legal** · I45 same bytes different target → lowering identity effect ·
I46 same target different bytes → request/evidence change · I47 profile alias
spelling → canonical identity law · I48 different executable same config →
**producer identity changes** · I49 same executable different timing config →
**profile identity changes** · I50 raw stdout differs while the semantic result is
the same → `ExecutionAttempt` changes; the stable scientific evidence law is
audited, not assumed.

## 61. Adversarial cases I51–I70

| # | Case | Verdict |
|---|---|---|
| I51 | two ranges overlap by one address | **INVALID** |
| I52 | adjacent ranges | **VALID** |
| I53 | gap between ranges | MemoryIntent **valid**; decode in gap → `UNMAPPED_ADDRESS` |
| I54 | same ranges reordered | **same identity** |
| I55 | target display name changes | same semantics if `AgentInstanceId` unchanged |
| I56 | memory agent id changes | AddressMap binding **changes / breaks** |
| I57 | legacy group target has exactly one memory instance | **lossless** migration to `AgentInstanceId` |
| I58 | legacy group target has two memory instances | **migration REFUSES** — cannot infer owner |
| I59 | legacy map targets a compute agent | legacy compatibility only / **v4 migration refusal** |
| I60 | Ramulator engine exists, no product caller | state = **ENGINE_ONLY** |
| I61 | future gateway wired without changing backend semantics | product capability state changes; scientific producer semantics may stay the same |
| I62 | AddressMap changes while standalone Phase-9 input is unchanged | Ramulator result **unchanged** — proves the disconnection |
| I63 | Ramulator profile changes, AddressMap unchanged | compile artifacts **unchanged** |
| I64 | memory evidence displayed alongside BookSim evidence | **allowed** as separate analyses |
| I65 | UI adds both latency values | **forbidden composition** |
| I66 | memory metric lacks a target/population contract | **not registered** |
| I67 | a valid registered memory metric appears later | Requirements integration needs a **separate Domain-E extension/version** |
| I68 | unknown memory-agent kind marked addressable | **fail closed** |
| I69 | unknown Ramulator profile version | **UNSUPPORTED / fail closed** |
| I70 | unknown `MemoryIntent` schema | **fail closed** |

## 62. Research questions M1–M40

| # | Answer |
|---|---|
| M1 | **`AddressMap` only** |
| M2 | `AddressDecodeArtifact` (canonical, wired); `MemoryArtifact` + `MemoryLoweringManifest` + `MemoryEvidence` (real, unwired) |
| M3 | `{ranges: [{name, base, size, target_agent_idx}]}`, half-open `[base, base+size)` |
| M4 | declared in `CompileRequest`; **target owner MEMORY** |
| M5 | `derive_address_decode` — it bounds the design address domain |
| M6 | **today: none — no kind restriction**; **v4: `HBM_CONTROLLER` only** |
| M7 | **no** |
| M8 | **no** |
| M9 | **backend-only** (`RamulatorGeometry`) |
| M10 | **no** |
| M11 | **no** — backend profile inside the fixed v1 envelope |
| M12 | the **Phase-9** `WorkloadArtifact` |
| M13 | **no** — `KIND_PIM_*` are markers |
| M14 | the Phase-9 artifact + a `MemorySystemDesign` |
| M15 | `MemoryArtifact` → `MemoryLoweringManifest` + `ReadWriteTrace` |
| M16 | yes — content-addressed, parent-linked, tamper-refused at execute |
| M17 | the v1 HBM pool |
| M18 | a named remote device — **and it is REFUSED** |
| M19 | **no** |
| M20 | **refused at lowering**; grammar only |
| M21 | **no** |
| M22 | **no** |
| M23 | **no** |
| M24 | the chain exists; **no product caller** |
| M25 | `SUPPORTED` envelope + fixed driver constants (HBM3/HBM34/FRFCFS/Open/NoRefresh/clock_ratio 4/1) |
| M26 | **yes** — `binary_sha256` + `VENDOR_PIN` + version |
| M27 | the pinned envelope + drain reconciliation; `MemoryLoweringManifest` binds the chain |
| M28 | `MemoryEvidence` |
| M29 | 8 typed stats + 9 counters (enumerated §46) |
| M30 | `cycles` (DRAM clock) and `requests`/`bytes` |
| M31 | **yes** — Ramulator's own, `clock_ratio 4/1` |
| M32 | **no** |
| M33 | **no** |
| M34 | **no** |
| M35 | v1-envelope execution with drain reconciliation over a recorded stream — **not hardware accuracy** |
| M36 | **no** — no registered `MetricId` (deferred, §47) |
| M37 | geometry, channels, timing, technology |
| M38 | preserve in the legacy evaluation adapter; **not promoted** |
| M39 | the drain contract makes PASS independently checkable; calibrated determinism is **not** claimed |
| M40 | *"a qualified DRAM-timing simulation over a recorded request stream, on a fixed v1 geometry, standalone from the network — engine available, product not wired"* |

**All 40 answered.**

## 63. Implementation debt — normalized

```text
MEM-D1        replace positional AddressRange.target_agent_idx with a stable
              AgentInstanceId (removes the count==1 restriction by construction)
MEM-D3        promote the overlap law to MemoryIntent intrinsic validation
              (validate_no_overlaps exists at compile_model.py:794 with zero callers)
MEM-D4        restrict AddressRange targets to memory-capable agents
              (derive_address_decode applies no kind restriction today)
MEM-EVAL-D1   wire a canonical product entry point for standalone qualified
              Ramulator evaluation
MEM-EVAL-D2   bind scheduler / row policy / refresh / clock ratio into
              MemoryEvaluationProfile identity
              (backend_config_payload hashes geometry+mapping+transaction_bytes only)
MEM-METRIC-D1 register dram_completion_cycles once a RequirementV4
              population/target contract exists  [CONDITIONAL]
```

**Withdrawn as already satisfied:** the first-pass `MEM-D2` (memory-lowering
semantics identity) — `MAPPING_ALGORITHM` refuses substitution and the manifest is
hash-linked and tamper-closed.

**Not v4 debt:** compute→memory placement · data/tensor placement ·
network+memory coupling · canonical `WorkloadV4`→Ramulator bridge ·
serving→Ramulator · PIM · CXL · STORAGE · KV-memory analysis.

## 64. Remaining blockers

**None for MEMORY coherence.** The two open items are external and explicitly
scoped, not unresolved ambiguity:

1. **`MEM-EVAL-D1`** — a product decision plus wiring work; the engine is real and
   the current state is stated honestly as `ENGINE AVAILABLE / NOT PRODUCT-WIRED`.
2. **Global decisions D1–D8** — the ontology checker reports
   `GATE CLOSED pending decisions: D1, D2, D3, D4, D5, D6, D7, D8`; these are
   cross-domain and outside Domain I.

## 65. Domain verdict

The domain closes coherently **because the two pipelines are kept apart** rather
than fused.

**`MemoryIntentV4` is `AddressMap` and nothing else**: which memory agent owns
which address range. It is canonical, in the compile path, and identity-bearing
through `FabricArtifact`. Ownership is **exclusively MEMORY**; SYSTEM keeps the
agents, their identity and their address interface width.

The target-identity question is **decided, not deferred**: an address range names a
concrete memory owner, so v4 targets a stable **`AgentInstanceId`**. The evidence
is decisive rather than convenient — the decode entry already carries
`target_endpoint_id`, the group is an input convenience usable only at
`count == 1`, and the code itself attributes that restriction to a *missing*
selection policy. The positional target was an accidental legacy abstraction, and
the group-singleton restriction disappears with it. Targets are restricted to
`HBM_CONTROLLER`; a compute agent is `INVALID`.

Range semantics are exact: **half-open `[base, base+size)`, `size >= 1`, a 64-bit
domain bound and a per-endpoint width bound**, deterministic ordering by
`(base, size, group, endpoint)`, **overlap forbidden**, **gaps legal** with
`UNMAPPED_ADDRESS` at use time, and name/order/presentation excluded from
identity. The overlap law already exists in the decoder; only its *enforcement
stage* moves to intrinsic validation.

Three corrections came out of the closure pass and are recorded rather than
smoothed over. **`REMOTE` is refused, not resolved** — the first-pass reading was
wrong, and `REMOTE`, `CXL` and `STORAGE` all fail closed with typed refusals
against the v1 HBM pool. **The memory-lowering semantics identity already
exists**, so the first-pass `MEM-D2` is withdrawn. **The design-level overlap check
is dead code**, which converts a presumed invariant into a precise validation-stage
debt.

The evaluation half is classified for exactly what it is: **a real, tested,
hash-linked, pinned engine that is not product-wired.** Its fidelity labelling is
honest and two-dimensional; its drain contract is four-typed; its producer identity
binds binary content; and it is **standalone**, so network latency is never added
to memory latency and no coupled-system claim is made. There is **no bridge**
between the `AddressMap` world and the Ramulator world, and I62 proves the
disconnection from both directions.

Compute→memory binding, data→memory binding and therefore **locality** are declared
**CONTRACT NOT AVAILABLE** rather than approximated. Requirements stay **deferred**,
with one named candidate metric and its exact missing element recorded — no metric
is fabricated to make the domain look finished.

**MEMORY INTENT: PLANNED — COHERENT**

Per Gate 2's rule, DESIGN-SPACE / OPTIMIZATION is not begun.
