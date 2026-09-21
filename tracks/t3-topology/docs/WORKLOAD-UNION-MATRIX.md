# Slice 2c — Workload Authority Inventory (Gate V2)

**Status:** inventory **corrected** after audit. No workload code changed yet.
**Base:** `31d1558c`. **Gate:** V2 — see §6 for what is green and what is not.

Two corpora are captured and pinned before any edit:

```
tests/test_domain_corpus_identity.py                          69 entries
tests/test_phase9_workload_corpus.py + fixtures/...py        173 entries
```

Gate V2 evidence: `tests/test_gate_v2_union_evidence.py` (20 passed,
2 strict xfail — the two defects below that are still unfixed).

---

## 1. Field-by-field union matrix

`D` = Wave-D graph/operations · `O` = Phase-9/14/16 authority.

| semantic content | D | O | canonical target |
|---|---|---|---|
| explicit operation id | yes | yes | `OperationNode.operation_id` (required) |
| explicit DAG deps | yes | **no** (order is the carrier) | `deps`; legacy order → sequential deps |
| acyclicity | yes | n/a | validated on the graph |
| owner rank | yes | no | `owner: int \| None` — **optional** |
| phase | yes (global) | no | `phase: str \| None` per op; envelope phase optional |
| step | yes | no | `step: int \| None` |
| label | no | yes (presentation) | `label` — NOT identity-bearing |
| **participant/rank space** | = world_size | **separate field** | `participant_count: int` — identity-bearing |
| TP/PP/EP/DP geometry | `ParallelismArtifact` | `Parallelism` (tp,dp,ep,pp) | `ParallelismArtifact` only |
| COMPUTE | kind only | full | COMPUTE detail |
| `duration_ns` | no | yes | required |
| `input/weight/output_bytes` | no | yes | optional each |
| `input/weight/output_loc` | no | yes (default LOCAL) | **explicit in v2**, default `LOCAL` |
| `batch_tag` | no | yes (default NONE) | **explicit in v2**, default `NONE` |
| COLLECTIVE (AR/RS/AG/A2A) | yes | yes | COLLECTIVE detail |
| payload bytes / participants | yes | yes | required |
| **dimensional scope** | **no** | yes (`"ALL"` or bool mask) | `scope: str \| None` + mask — three distinct states |
| BROADCAST | kind only, root = `participants[0]` | yes, **explicit `source`** | COLLECTIVE + `source` (required) |
| P2P | one transfer | `SEND` / `RECV` | P2P + `role: TRANSFER \| SEND \| RECV` |
| MULTICAST | yes (+ replication) | no | MULTICAST detail |
| EXPERT_BEGIN | constant only | yes (`expert_num`, optional collective) | EXPERT detail |
| **EXPERT_END** | constant only | **yes — carries the combine collective** | EXPERT_END detail with the same optional collective fields |
| **PIM_BEGIN / PIM_END** | no | **markers emitted, currently DROPPED** | PIM detail (`channel`) |
| KV_READ/KV_WRITE, EXPERT_DISPATCH/COMBINE | constants only | no | **not implemented** — no producer, no consumer |
| collective schedule | `workload/collectives.py` | no | keep |
| logical messages, packetization, flitization | yes | no | keep unchanged |
| conservation + reference differentials | yes | ET/memory conservation | keep both |
| physical traffic + BookSim rendering | yes | no | keep unchanged |
| memory lowering | no | yes | keep, consume the graph |
| ET/Chakra lowering | no | yes | keep, consume the graph |
| trace-row projection/regeneration | no | yes (byte-identical) | keep, consume the graph |
| serving canonicalization | no | yes | keep, produce the graph |
| timeline/attribution | no (slice 3) | yes | minimal adaptation in 2c |

## 2. Findings (corrected)

**F9 (CORRECTED) — divisibility belongs to the schedule, not the
declaration.** `ALLREDUCE(k=3, B=1000)` is a **valid canonical
declaration**. The pinned exact RING expansion refuses with
`UnsupportedSchedule` because equal chunks cannot be produced. No
padding, rounding, uneven chunking or algorithm substitution, and no
legacy permissive mode. The canonical graph must not inherit BookSim's
schedule restriction as a declaration-time law.

**F9b (NEW) — the old path never had the law at all.** The Phase-9
builder accepts k=3/B=1000 (corpus: `refusal/non_divisible_allreduce ==
"NO REFUSAL"`). So the merge makes the *declaration* permissive like the
old path and keeps the *lowering* strict like Wave D. Both halves are
tested.

**F10 — the location law lives in the resolver.** `REMOTE`/`CXL`/
`STORAGE` construct and serialize; `resolve_memory` refuses with
`UnsupportedSemantic`. The canonical COMPUTE detail keeps locations as
declared data or the refusal contract dies with the field.

**F11 (CORRECTED) — a legacy-reader rule, not a v2 serialization rule.**
Legacy compressed-hash validation must reproduce `to_dict()` omission
exactly. That does NOT constrain the new schema: v2 normalizes *values*
(`input_loc="LOCAL"`, `batch_tag="NONE"`) explicitly, and keeps *absences*
(`scope`, `owner`, `phase`, `routing_policy`) genuinely absent.

**F12 (CORRECTED) — a repairable implementation defect, not an
unsupported feature.** Chakra contains explicit `expert_start` /
`expert_end` collective emission (llm_converter.py:471, :482), so EXPERT
is an intended capability. Root cause of the crash: when the last row of
a layer group is a marker, the **last-NPU-group branch**
(llm_converter.py:547-553) reads `layers[layer_end-1].output_memory_loc`,
and marker rows (parsed at :24-43) never set memory attributes. The
*other* branch explicitly guards markers. The fix is a guard at that one
site; it belongs in an isolated commit **before** the merge.

**F12b (NEW, blocking) — Chakra is a pip dependency (0.0.4), not
vendored, and the repo has no patch mechanism.** A converter repair
therefore requires a **vendoring-or-fork decision** (as with BookSim2) or
an upstream fix. Reported, not worked around: patching site-packages is
not a repo change, and a `lowering.py` workaround would alter the trace
dialect that the byte-identical round-trip contract depends on.

**F13 — old refusals are semantics too** (compute with comm bytes,
duplicate ids, empty ops, out-of-range participants, negative duration,
empty batch tag). Captured exactly.

**F14 (CORRECTED) — not a compatibility requirement.** Constructing
`WorkloadOp(kind="NOPE")` and failing only at artifact construction is
not valuable. The canonical node refuses an unknown kind immediately.
What must survive is *no invalid workload becomes valid*, not the
historical exception site. Documented as an intentional API tightening.

**F15 (NEW) — the participant namespace is not the parallelism geometry.**
`serve._parallelism_from_cluster` sets `dp = number of INSTANCES` and
takes tp/ep/pp from the FIRST instance, while `num_participants` is the
per-instance rank space the trace's collectives address. For a
two-instance cluster, `world_size = 8` and `participant_count = 4`.
Deriving one from the other would silently break multi-instance serving.
Canonical `WorkloadGraph` therefore carries `participant_count` as an
identity-bearing field. Migration: Wave D → `world_size`; Phase 9 →
`num_participants`. A lowering needing global ranks must refuse unless
`participant_count == world_size` or an explicit binding exists.

**F16 (NEW) — PIM semantics are silently dropped.** `artifact_from_trace_
rows` does `if marker == "PIM": continue`, while LLMServingSim emits
`PIM <channel>` / `PIM END` and Chakra consumes PIM flags
(llm_converter.py:31-45, 261-262, 341-430). The 173-entry corpus missed it
because no PIM case existed. Gate V2 adds one and pins the loss.

**F17 (NEW) — the Chakra PIM path contains a genuine crash.**
`pim_parent_nodes.append()` with **no argument** (llm_converter.py:513) on
the `npu_group == 0` path — a `TypeError` wherever that branch runs.
**FIXED at Gate V2.1** (the first PIM block in group 0 has no
predecessor, so nothing is appended).

**F17b (CORRECTED) — PIM is SUPPORTED upstream; OUR STACK IS
VERSION-SKEWED.** The earlier "PIM is unsupported because Chakra has no
PIM node type" conclusion was wrong. Verified in-tree:

```
present (producer half)   LLMServingSim PIMModel, PIM configs,
                          PIM trace markers, converter
                          get_pim_compute_node() -> PIM_COMP_NODE
                          + tensor_channel
missing (consumer half)   et_def.proto has NO PIM_COMP_NODE and still
                          numbers COMP_NODE = 4
                          Chakra feeder has no tensor_channel/tensor_device
                          astra-sim/workload/Workload.cc: 0 PIM references
                          WorkloadLayerHandlerData: no pim_enabled /
                          pim_channel_id / pim_runtime
```

There is exactly ONE ASTRA source tree:
`third_party/llmservingsim/astra-sim/astra-sim` is a **symlink** to
`third_party/astra-sim/astra-sim`, so the LLMServingSim frontend is bound
to the vanilla tree rather than to its matching fork. The matching
`casys-kaist` forks are **not vendored**; both are fetchable (verified):
`chakra` HEAD `30221ab8…`, `astra-sim` HEAD `d3469945…`.

The danger this creates: encoding "PIM unsupported" into `WorkloadGraph`
would fossilise an integration regression as permanent architecture.

**F18 (NEW) — `scope=None` and `scope="ALL"` collapse to the same trace
form.** `_comm_field` emits the bare kind unless scope is a list, so both
states render `ALLREDUCE`. After the merge, "all dimensions" and "nobody
declared" would be indistinguishable at the backend. Canonical lowering
must refuse `None` unless the target has an independently proven meaning.

**F19 (NEW) — BROADCAST root is a Wave-D assumption.** `messages.py`
hard-codes `root_idx = 0`; the old authority stores an explicit `source`
and refuses its absence. Migration sets `source = participants[0]` for
Wave D (keeping packets identical) and preserves the declared source
otherwise; message generation and the reference differential must use it.

**F20 (NEW) — SEND/RECV and TRANSFER are different abstractions.** Old
`SEND`/`RECV` are identity-bearing kinds; a Wave-D P2P is a whole
transfer. One canonical P2P operation with `role = TRANSFER | SEND | RECV`
preserves both. Only `TRANSFER` is proven to lower into one logical
message; standalone legacy SEND/RECV stay representable and their
lowering refuses rather than fabricating a pairing.

**F21 (NEW) — identity ownership.** A canonical `WorkloadGraph` must not
carry an externally supplied `workload_id` while claiming content-derived
identity. `workload_id()` is the content hash of the canonical semantic
payload; legacy `workload_id`/`source_kind` become provenance.

**F22 (NEW) — `routing_policy` has the same fabrication trap as `phase`.**
Phase-9 declared neither. Migration must not insert `EXPLICIT_TRACE` or
`"PREFILL"`. `WorkloadSemantics` fields one authority lacked are optional;
consumers that require them refuse.

## 3. Canonical target schema

```
WorkloadGraph
├── parallelism: ParallelismArtifact      # system geometry authority
├── participant_count: int                # rank space the ops address
├── semantics: WorkloadSemantics          # optional fields, no fabrication
├── operations: tuple[OperationNode, ...] # ONE entry per operation
├── provenance: source metadata (non-identity, minimal)
└── schema_version

workload_id() = content_hash(canonical semantic payload)   # core/artifact.py

OperationNode
├── operation_id, kind, deps
├── owner: int | None, phase: str | None, step: int | None
├── label                                # presentation, non-identity
└── detail: FrozenMap                    # ONE closed per-kind payload
```

Kind union (eight, not six):

```
COMPUTE COLLECTIVE P2P MULTICAST EXPERT_BEGIN EXPERT_END PIM_BEGIN PIM_END
```

```
COMPUTE       duration_ns(req), input/weight/output_bytes?, locs, batch_tag
COLLECTIVE    kind(AR/RS/AG/A2A/BROADCAST), participants, payload_bytes,
              scope(3-state, optional), source(BROADCAST, required)
P2P           role(TRANSFER|SEND|RECV), src_rank, dst_rank, payload_bytes
MULTICAST     source_rank, destinations, payload_bytes, replication
EXPERT_BEGIN  expert_num?, comm_kind?, payload_bytes?, participants?, scope?
EXPERT_END    same optional collective fields as EXPERT_BEGIN
PIM_BEGIN     channel
PIM_END       (region close)
```

**No side lists**: the graph carries each operation's payload exactly once;
`messages.py` derives messages from the nodes instead of joining IDs.

## 4. Migration rules

1. **Ordered legacy → explicit deps** (chain). No inferred concurrency.
2. **Participant count**: Wave D → `world_size`; Phase 9 →
   `num_participants`. Never synthesise a local→global rank map.
3. **Field order trap**: `tp,dp,ep,pp` (old) vs `tp,pp,ep,dp`
   (canonical) — conversions use named fields; positional-swap test.
4. **Legacy hash first**: validate the old compressed document under the
   OLD rules, then convert, then compute the new identity.
5. **No fabricated defaults** for `owner`, `phase`, `step`, `scope`,
   `routing_policy`. Optional means absent.
6. **Broadcast**: Wave D `source = participants[0]`; legacy keeps its
   declared source even when it is not first.
7. **PIM/EXPERT** markers become first-class operations; they are never
   skipped.

## 5. Exactness contracts (must not change)

```
collective arithmetic + reference equations
logical-message sequencing, packetization, flitization
conservation, physical binding, bundle validation
BookSim rendering (trace bytes identical for an equivalent workload)
old trace-row round trip (byte-identical)
old ET lowering bytes for an equivalent workload
memory-lowering bytes and conservation
```

Graph identity changes (new schema); packets and trace bytes do not.

## 6. Gate V2 status

Green:

```
multi-instance participant_count != world_size          test_gate_v2 ...ParticipantNamespace
EXPERT_END with combine collective survives roundtrip   ...ExpertEndIsNotPayloadFree
PIM marker loss pinned (strict xfail)                   ...PimSemantics
PIM converter no-argument append pinned                 ...PimSemantics
scope=None vs scope=ALL collapse pinned (strict xfail)  ...ScopeAbsenceIsNotAll
BROADCAST explicit source preserved; Wave-D root pinned  ...BroadcastSource
SEND/RECV role distinction preserved                     ...P2PRoles
declaration vs schedule divisibility split                ...DivisibilityIsAScheduleLaw
legacy compressed-default hash validates as-is            ...LegacyCompressedDefaults
oracle-independence AST guard (top-level only)            test_architecture_law
```

Not yet green for the merge — but NOT blocked by Gate V2.2:

```
0. 2c PRELUDE (see below): acceptance decoupling + multi-instance case
1. (resolved) F12b: Chakra IS vendored; runtime is fingerprint-gated
3. scope=None lowering REFUSAL implemented (currently only pinned as xfail)
4. PIM_BEGIN/PIM_END added to the vocabulary (flips the PIM xfail)
5. multi-instance corpus case captured through serve.canonicalize_run_workload
   (currently captured at the _parallelism_from_cluster level)
```

Items 1 and 2 are decisions/repairs outside the workload authority and are
therefore sequenced **before** it, as required.

---

## Gate V2.2 — restore the matching PIM backend (NOT STARTED, NOT BLOCKING 2c)

**Sequencing correction (accepted).** Gate V2.2 does **not** block Slice
2c. PIM is a real WORKLOAD semantic, proven by the producer half that
already exists (PIMModel, PIM configs, the `PIM <channel>` / `PIM END`
grammar, the PIM latency model, `REMOTE:<device>.<channel>` placement, and
the converter intent). The defect is a BACKEND CAPABILITY defect: a newer
producer paired with an older Chakra schema/feeder/ASTRA consumer.

Coupling the canonical IR to whatever simulator build happens to work
today is the exact failure this consolidation exists to stop. So:

```
WorkloadGraph            PIM_BEGIN / PIM_END are REAL semantics (2c)
astra_chakra_et          REFUSES PIM with a typed backend-capability
                         refusal until Gate V2.2 lands
Gate V2.2 later          flips ONLY the backend box; WorkloadGraph
                         semantics and identity do not change
```

That invariance is the acid test that the abstraction is right.

Ruling: do not formalise PIM as unsupported. Port the matching upstream
deltas mechanically; do not design anything.

```
1. fetch casys-kaist/chakra (30221ab8…) and casys-kaist/astra-sim (d3469945…)
   into a scratch tree — NOT as a second vendored copy
2. diff our vendored Chakra against the fork; isolate the PIM deltas
   (et_def.proto enum, feeder tensor_device/tensor_channel)
3. diff our ASTRA against the fork; isolate the PIM deltas
   (Workload.cc issue_mem path + metadata propagation,
    WorkloadLayerHandlerData fields)
4. port ONLY those deltas into the existing vendored trees, VeriTX-marked
5. regenerate the protobuf bindings (PIM_COMP_NODE = 4 SHIFTS COMP_NODE to 5
   and every later enum; generated code and all components must be rebuilt
   together, and old .et files are not assumed compatible)
6. rebuild ASTRA + Chakra
7. run the real PIM trace
8. verify ET contains PIM_COMP_NODE with tensor channel/device
9. verify ASTRA consumes it (issue_mem + pim_runtime propagation)
10. dense non-PIM regression: ET hashes unchanged before/after
```

### PIM test policy (changed)

Do NOT leave "the PIM converter crashes" as a strict xfail once 2c
lands. The normal passing test becomes an intentional refusal that fires
BEFORE the version-skewed converter executes:

```python
with pytest.raises(UnsupportedSemantic):      # existing typed refusal
    lower_to_et(pim_workload)
```

`UnsupportedSemantic` (lowering.LoweringError) is the most appropriate
existing refusal — the lowering refuses because the qualified backend
cannot represent the semantic. No new exception family, and no
`BackendCapabilityUnavailable` invented for one case.

Gate V2.2 then REPLACES that refusal test with the positive end-to-end
execution test, so no xfail has to be re-interpreted later.

### The killer regression (Gate V2.2)

```
PIM 0
attention ... REMOTE:0.0
PIM 1
attention ... REMOTE:0.1
PIM END
```

proving trace -> converter -> ET(PIM_COMP_NODE) -> feeder(tensor_channel)
-> Workload::issue_mem -> pim_runtime propagated -> simulation completes.
The xfail is removed only when that chain is real, not when it is
re-labelled.

Note: steps 1–4 must not create a second source of truth. The forks are a
REFERENCE for the deltas, not a new vendoring.

---

## Slice 2c prelude — the work immediately before the WorkloadGraph merge

Sequenced by the ruling. Gate V2.2 and Slice 3 are explicitly NOT here.

| # | task | state |
|---|---|---|
| 1 | decouple `acceptance/phase15.py` from `workload/canonical.py` | **PARTIAL** — moved out of the production package (below); its legacy import is now a MIGRATION-CONSUMER boundary that 2c deletes |
| 2 | preserve its Ramulator qualification evidence exactly | **DONE** — same nine conceptual checks (BUILD DRAIN EQUIV DETERM LOCALITY BANK CLOCK INTEGRITY AUDIT) recorded as the same 13 `report()` calls in 7 groups (`audit behavior build determinism drain equiv integrity`); identical `--help`/`--json` interface |
| 3 | move its workload→memory conservation contract into an integration regression | TODO (the target boundary is recorded below) |
| 4 | real multi-instance `canonicalize_run_workload` regression (`participant_count != world_size`) | **DONE** |
| 5 | keep F18 (`scope=None != ALL`) explicitly open in this ledger | **DONE** (see below) |
| 6 | implement the canonical `WorkloadGraph` | TODO |

### Why item 1 needs care

`acceptance/phase15.py:48-49` imports `Parallelism`, `WorkloadArtifact`
and `build_compute_op`, and it feeds them to
`memory_lowering.resolve_memory(art, ...)`, which takes the legacy
artifact. So the decoupling is NOT a local import swap:

```
phase15 builds WorkloadArtifact -> resolve_memory(WorkloadArtifact)
```

Migrating `resolve_memory` to the canonical graph is 2c consumer work. The
pragmatic order is therefore:

```
a. move the battery out of veritx_dse (qualification/ramulator.py),
   keeping its Ramulator evidence byte-identical
b. keep the legacy import visible there as a MIGRATION CONSUMER, with the
   contract test (item 3) holding the conservation semantics
c. migrate resolve_memory to WorkloadGraph during 2c
d. delete workload/canonical.py; item (b)'s consumer migrates with it
```

A qualification battery is allowed to be a legacy consumer for one slice.
A production package module is not, which is why (a) comes first.

### Item 4 — DONE, with the mutation probe

`tests/test_multi_instance_canonicalization.py` (6 tests) drives the real
entry point with a two-instance cluster (tp=4, 4 NPUs per instance):

```
parallelism.dp == 2,  world_size == 8,  num_participants == 4
```

Mutation-proven: monkeypatching the participant rule to return
`world_size` makes `num_participants == 8`, and the regression fails. The
test is therefore the thing that would have caught the original silent
design error, not a decorative assertion.

### Item 5 — F18 stays open

`scope=None != scope="ALL"` is recorded as an OPEN 2c item: the canonical
lowering must REFUSE an undeclared scope unless the target proves a
meaning, because the trace projection currently renders both as the bare
collective form. Pinned as a strict xfail in
`tests/test_gate_v2_union_evidence.py`; the xfail is removed when the
canonical lowering owns the refusal.

### Item 1/2 — the qualification battery left the production package

```
before  veritx_dse/acceptance/phase15.py   (production package, 454 lines)
after   qualification/ramulator.py         (beside veritx_dse/)
        veritx_dse/acceptance/ deleted entirely (no compat module, no shim)
```

Scientific checks untouched: the same nine conceptual checks (BUILD /
DRAIN / EQUIV / DETERM / LOCALITY / BANK / CLOCK / INTEGRITY / AUDIT)
recorded as the same 13 `report(...)` calls in the same 7 groups (`audit
behavior build determinism drain equiv integrity`) — the nine are the
checks, the seven are the report groups; both are unchanged. The
`--help`/`--json` interface is identical, verified by diffing `--help`
before and after. The
only code change is the path assumption (`DSE_DIR` was
`parents[2]` inside `veritx_dse/acceptance/`, now `parents[1]`). Nothing
imports the battery from production, so the move is inert for the product
path.

Its legacy import is deliberate and temporary:

```
qualification/ramulator.py
    from veritx_dse.workload.canonical import Parallelism, WorkloadArtifact
    from veritx_dse.workload.memory_lowering import resolve_memory
```

That is a MIGRATION CONSUMER, not a second production authority. It is
acceptable for exactly one slice because 2c deletes the dependency.

### Item 3 — the boundary to land during 2c

Agreed target, and no cleanup theatre before the new graph exists:

```
before 2c   qualification -> old workload -> memory
after 2c    qualification -> MemoryArtifact
            integration test -> WorkloadGraph -> memory
```

Concretely, during 2c:

1. convert the battery's fixture construction from
   `build_compute_op -> WorkloadArtifact -> resolve_memory` to direct
   `MemoryArtifact` fixtures wherever that preserves the exact memory
   accesses being tested;
2. extract the workload→memory conservation claim as its own integration
   regression, pinned against the CURRENT legacy behaviour first;
3. migrate `resolve_memory()` itself to `WorkloadGraph` and move that
   integration test with it.

Do NOT duplicate `resolve_memory()` logic in the qualification battery to
make it look independent — the dependency disappears when the authority
does.

### Item 2 documentation correction — the invocation DID change

The argument/JSON interface is unchanged, but the **module invocation
changed** because the battery left the production package:

```
was   python3 -m veritx_dse.acceptance.phase15 [--json]   (no longer exists)
now   cd tracks/t3-topology/dse
      python3 qualification/ramulator.py [--json]
```

`veritx_dse/acceptance/` is deleted with no compatibility shim, and none
will be added to preserve an obsolete module name. The docstring states
this explicitly rather than implying the command still works.

### Item 3 — the seam already existed; strengthened, not duplicated

The integration seam was already `tests/test_memory_lowering.py::
TestRealWorkloadPath` (real serving rows -> canonical workload ->
`resolve_memory` -> MemoryArtifact, proving 10 240 operand bytes, six
regions/accesses, source-node attribution and conservation). No new test
framework was created. A new class `TestMemorySeamMigrationFixture` in the
same file pins it for 2c:

```
MUST NOT MOVE                      MAY MOVE (documented, not hidden)
region_table_hash  2091447e…       source_workload_hash
access_stream_hash a2037d77…       MemoryArtifact.artifact_hash
regions + placements + sizes       manifest source_memory_artifact_hash
access order + READ/WRITE
access dependencies
source_node attribution
logical bytes 10240 / 7680R+2560W
Ramulator trace_sha256 001e5970…
```

The identity test asserts the RELATION (`source_workload_hash ==
workload.artifact_hash`) rather than a frozen value, so 2c may move both
together while any silent ancestry break still fails. This is the "hash
cosplay" guard: the required outcome is semantic continuity with honest
new ancestry.

### Item D — the participant namespace at the memory seam

`resolve_memory()` binds `num_nodes = art.num_participants`; after
migration this must be `graph.participant_count`, never
`parallelism.world_size`. Pinned:

```
two instances, tp=4 -> world_size = 8, participant_count = 4
assert res.artifact.num_nodes == wl.num_participants == 4 != world_size
```

That assertion is the memory-side twin of the
`test_multi_instance_canonicalization.py` gate: the same design error
would resurrect here as an 8-node memory artifact for a 4-rank trace.
