# Slice 2c — Workload Authority Inventory (the union gate)

**Status:** inventory complete, **no workload code changed yet**.
**Base:** `dc0a704b`.
**Rule for the merge:** the canonical `WorkloadGraph` must be a semantic
**SUPERSET** of both authorities. Neither is deleted because the other lacks
a feature.

Two corpora are captured and pinned before any edit:

```
tests/test_domain_corpus_identity.py   69 entries   the new graph
tests/test_phase9_workload_corpus.py  173 entries   the old authority
                                      builder: tests/fixtures/phase9_workload_corpus.py
```

---

## 1. Field-by-field union matrix

`D` = Wave-D graph/operations (`workload/graph.py`, `operations.py`,
`semantics.py`, `messages.py`, `traffic.py`).
`O` = Phase-9/14/16 authority (`workload/canonical.py`, `lowering.py`,
`memory_lowering.py`, `serve.py`, `timeline.py`).

| semantic content | D | O | canonical target |
|---|---|---|---|
| explicit operation id | yes (`event_id`/`op_id`) | yes (`op_id`) | `OperationNode.operation_id` (required) |
| explicit DAG deps | yes | **no** (order is the carrier) | `deps` (required); legacy order → sequential deps |
| acyclicity | yes | n/a | validated on the graph |
| owner rank | yes | no | `owner: int \| None` — **optional** |
| phase | yes (workload-global) | no | `phase: str \| None` on op; optional envelope phase |
| step | yes | no | `step: int \| None` |
| label | no | yes (presentation) | `label: str` — NOT identity-bearing |
| TP/PP/EP/DP binding | yes (`ParallelismArtifact`) | yes (`Parallelism` tp,dp,ep,pp) | `ParallelismArtifact` only |
| `num_participants` | derived (`world_size`) | **independent field** | derived + consistency-checked |
| COMPUTE | kind exists, no payload | full | `COMPUTE` detail |
| `duration_ns` | no | yes | COMPUTE detail (required) |
| `input/weight/output_bytes` | no | yes | COMPUTE detail (optional each) |
| `input/weight/output_loc` | no | yes | COMPUTE detail, default `LOCAL` |
| `batch_tag` | no | yes (default `NONE`) | COMPUTE detail |
| COLLECTIVE (AR/RS/AG/A2A) | yes | yes | COLLECTIVE detail |
| payload bytes | yes | yes | `payload_bytes` |
| participants | yes | yes | `participants` |
| **dimensional scope** | **no** | yes (`"ALL"` or bool vector) | `scope` — **OPTIONAL, absent ≠ "ALL"** |
| BROADCAST | no separate kind | yes, explicit `src` | COLLECTIVE kind + `source` |
| P2P | yes | yes (`SEND`/`RECV` + src/dst) | P2P detail |
| MULTICAST | yes (+ replication) | no | MULTICAST detail |
| EXPERT_BEGIN/END | constants only | yes (`expert_num`, `comm_kind`, bytes) | EXPERT detail |
| KV_READ/KV_WRITE | constant only | no | **not implemented** — drop the constants |
| EXPERT_DISPATCH/COMBINE | constant only | no | **not implemented** — drop or record as future |
| collective schedule | yes (`workload/collectives.py`) | no | keep, from graph ops |
| logical messages | yes | no | keep |
| packetization/flitization | yes | no | keep unchanged |
| conservation + references | yes | ET/memory conservation | keep both |
| physical traffic + BookSim trace | yes | no | keep unchanged |
| memory lowering | no | yes | keep, consume the graph |
| ET/Chakra lowering | no | yes | keep, consume the graph |
| trace-row projection/regeneration | no | yes (byte-identical round trip) | keep, consume the graph |
| serving canonicalization | no | yes | keep, produce the graph |
| timeline/attribution | no (slice 3) | yes (Phase 16) | adapt minimally in 2c; replaced in slice 3 |

## 2. Findings from capturing the corpora

**F9 — the old authority never had the divisibility law.** A k=3 ALLREDUCE
with B=1000 constructs fine in the old path and refuses in Wave D
(`UnsupportedSchedule`, "B % k == 0"). The canonical graph must keep the
Wave-D law (it is the stronger, audited semantics) — which means **legacy
workloads that used to be accepted may now refuse**. That is a behaviour
change and is reported, not slipped in.

**F10 — the location law lives in the resolver, not the constructor.** The
old authority accepts `REMOTE`/`CXL`/`STORAGE` at construction, *serializes*
them (non-default fields appear in `to_dict`), and refuses them in
`resolve_memory` with `UnsupportedSemantic`. The canonical COMPUTE detail
must therefore keep locations as declared data and let the memory lowerer
refuse — dropping the field would destroy the refusal contract.

**F11 — `WorkloadOp.to_dict()` is a COMPRESSED canonical form.** Defaults
(`loc=LOCAL`, `batch_tag=NONE`) are omitted; non-defaults appear. Identity is
built from the same dict, so omission is consistent. The canonical schema
must not "fix" this by always emitting defaults: that would move every legacy
identity hash.

**F12 — EXPERT markers round-trip to rows but do not lower to ET.** The
corpus shows `trace/serving_expert_rows/rows_roundtrip_equal == True` while
ET lowering fails inside the third-party Chakra converter (`'Layer' object
has no attribute 'output_memory_loc'`). The existing suite only tests the
round trip, so this was previously untested. Recorded, not fixed here (it is
a converter-contract issue, not a workload-schema one).

**F13 — old-path refusals are part of the semantics.** Captured exactly:
compute with comm bytes, duplicate ids, empty ops, out-of-range participants,
negative duration, empty batch tag. The canonical graph must reproduce them
(or report a deliberate change).

**F14 — `unknown_kind` is refused by the ARTIFACT, not the operation.**
`WorkloadOp(kind="NOPE")` constructs; `WorkloadArtifact.__post_init__`
refuses. The canonical graph validates at construction — a tightening to be
reported, not assumed.

## 3. Canonical target schema (to implement)

```
WorkloadGraph
  parallelism: ParallelismArtifact          # the ONE parallelism authority
  semantics:   WorkloadSemantics            # renamed from WaveDWorkloadSemantics
  workload_id: str
  operations:  tuple[OperationNode, ...]    # ONE entry per operation
  schema_version: int
  identity = content_hash(...)              # core/artifact.py

OperationNode
  operation_id: str
  kind: COMPUTE | COLLECTIVE | P2P | MULTICAST | EXPERT_BEGIN | EXPERT_END
  deps: tuple[str, ...]
  owner: int | None                         # absent means undeclared
  phase: str | None                         # absent means undeclared
  step:  int | None
  label: str                                # presentation, NOT identity
  detail: FrozenMap                         # ONE closed per-kind payload
```

**No side lists.** The current `OperationGraph` carries `nodes` plus
`collectives` / `p2p_transfers` / `multicasts`, and `LogicalMessageArtifact`
reconstructs the relationship by ID. The canonical graph carries each
operation's semantic payload exactly once; messages derive from the nodes.

Per-kind detail schemas (closed):

```
COMPUTE       duration_ns (req), input_bytes?, weight_bytes?, output_bytes?,
              input_loc, weight_loc, output_loc, batch_tag
COLLECTIVE    kind (AR/RS/AG/A2A/BROADCAST), participants, payload_bytes,
              scope?, source? (BROADCAST only)
P2P           src_rank, dst_rank, payload_bytes
MULTICAST     source_rank, destinations, payload_bytes, replication
EXPERT_BEGIN  expert_num?, comm_kind?, bytes?, participants?, scope?
EXPERT_END    (marker; no payload)
```

## 4. Migration rules

1. **Ordered legacy → explicit deps.** `op0..opN` becomes a chain because the
   ET lowering chains positionally. No extra concurrency is inferred.
2. **Identity.** Old `workload_id`/`artifact_hash`/`source_kind` become
   provenance; the graph's scientific identity is content-derived via
   `core/artifact.py`. Migration validates the OLD document under the OLD hash
   rules first, then converts and computes the new identity.
3. **`num_participants` is derived** from `parallelism.world_size`, with an
   explicit consistency check for legacy documents that declare it.
4. **Field name order is a trap.** The old `Parallelism` declares
   `tp, dp, ep, pp`; `ParallelismArtifact` declares `tp, pp, ep, dp`.
   Conversions use **named** fields; a positional-swap regression test is
   required.
5. **Optional ≠ default.** `owner`/`phase`/`step`/`scope` must support
   genuine absence. Filling `owner=0, phase="PREFILL", step=0` would invent
   semantics the source never had (and the memory lowerer already refuses
   ambiguous attribution rather than assigning node zero).

## 5. What must NOT change (exactness contracts)

```
collective arithmetic + reference equations
logical-message sequencing, packetization, flitization
conservation equations, physical binding, bundle validation
BookSim rendering (trace bytes identical for an equivalent workload)
old-path trace-row round trip (byte-identical)
old-path ET lowering bytes for an equivalent workload
memory-lowering bytes and conservation
```

Graph identity WILL change (new canonical schema). Derived artifact ids may
follow. Packets and trace bytes may not.
