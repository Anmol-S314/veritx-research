# VERITX Workload Authority (C2.2)

One semantic fact, one writer. This document names the single writer for
each workload fact and the one-way derivation that carries it into the
backend projection. It exists because F-0004 (a "ring" that was a full
exchange) and F-0006 (ALLGATHER over-transmitted by a factor k) were both
caused by two modules inventing the same collective law and agreeing with
each other.

Authority is source + tests, not this prose.

## Layers (one-way derivation)

```text
CompileRequest / CompileRequestV3        (intent; model/compile_model.py)
        |  application/compile_intent.py derive_compile_request
        v
WorkloadGraph                            (workload/graph.py)
        |  LogicalMessageArtifactV2
        v
Logical messages                         (workload/messages.py)
        |  PhysicalTrafficArtifactV2
        v
Physical traffic: packets + flits        (workload/traffic.py)
        |  booksim_projection.prepare_booksim_input
        v
PreparedBookSimInput + rendered trace    (backend/booksim_projection.py)
```

`workload/canonical.py` is the request-stage canonical *op* vocabulary
(COMPUTE, SEND/RECV, collective markers). It validates shape and explicit
broadcast roots; it computes no schedule and is not a schedule authority.

## Writers per semantic fact

| fact | single writer | notes |
|------|---------------|-------|
| request | `model/compile_model.CompileRequest(V3)` | intent only; no schedule |
| operation | `workload/graph.OperationNode` (`WorkloadGraph`) | immutable; ordered |
| dependency | `WorkloadGraph` edges (`deps`) | acyclic, checked here |
| collective kind vocabulary | `workload/collectives.COLLECTIVE_KINDS` | **imported by graph/operations/messages/migration; never redefined** |
| collective algorithm | `workload/collectives.SCHEDULES` | same single authority |
| participant set | `graph.collective_detail(participants=…)` | broadcast source is explicit, never `participants[0]` |
| payload meaning | `workload/collectives.collective_schedule` | per-kind: chunk for ring kinds, total for ALLTOALL, root payload for BROADCAST |
| step / phase | `workload/messages._collective_triples` (steps from `collective_schedule`; phase from `op.phase`) | step count is the schedule's, not a second formula |
| message | `messages.LogicalMessageArtifactV2` | one logical message per schedule triplet |
| packet | `workload/traffic.PhysicalTrafficArtifactV2` | packetisation of each logical message |
| flit | `workload/traffic` (`PacketRecord.flit_count`) | flits per packet |
| trace timestamp | `backend/booksim_projection.trace_schedule` / `render_trace` | projection emission order, one iterator |

## Independent (deliberately not shared)

`verification/reference_semantics.py` carries its **own** collective
equations. It must never import `workload/collectives.py`; the differential
is meaningful only while the two are derived separately. The test
`test_workload_collectives.py` re-derives the laws from the spec text for
the same reason.

## Conservation at each edge

| edge | proof | test |
|------|-------|------|
| schedule → messages | `_collective_triples` refuses `len(triples) != ref["message_count"]` | `test_workload_collectives.py` |
| messages → traffic | `PhysicalTrafficArtifactV2` checks aggregate bytes / logical parent | `test_workload_traffic.py` |
| traffic → trace | `verify_trace_conservation` proves packets and flits conserved | `test_backend_booksim_projection.py` |
| executed → declared | BookSim `loaded == injected == delivered` and flit injected == accepted | `test_booksim_conservation.py`, harness conservation |

## C2.2 collapse landed

`COLLECTIVE_KINDS` was defined in `graph.py` and `operations.py`;
`SCHEDULES` in `messages.py` and `operations.py`; a fourth copy lived in
`migration.py`. They agreed, but four authors of one law is the F-0006
precondition. They now import the single tuple/dict from
`workload/collectives.py`, and
`test_collective_vocabulary_has_exactly_one_authority` asserts identity
(`is`), so any future redefinition fails the suite.

## Remaining limitation

`workload/canonical.py` still spells its request-stage op-kind vocabulary
inline (a superset of the collective kinds, including SEND/RECV). It is a
distinct fact (op kind, not collective kind) and computes no schedule, but
is not yet derived from a single op-kind authority. Recorded as an open
C2.2 sub-item.
