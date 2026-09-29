# `workload` — extracted module rationale

Extracted from the module docstrings of `veritx_dse/{name}` by the 2026-09-29 debloat. Code keeps a one-line pointer; this is the original long-form text.

## `tracks/t3-topology/dse/veritx_dse/workload/__init__.py`

```text
veritx_dse.workload — canonical workload semantics.

The workload authority layer of the canonical SROTA spine:

    CompileRequest (design identity)
          |
          v
    WorkloadGraph            graph.py      operation semantics + namespace
          |
          v
    collective schedules     collectives.py  pinned step/byte arithmetic
          |
          v
    logical messages         messages.py   expansion + per-class conservation
          |
          v
    participant -> endpoint  traffic.py    canonical mapping/attachment binding
          |
          v
    packets / flits          traffic.py    bit-exact packetization

Nothing here owns design identity, topology, routing, VC resources or any
backend configuration: those remain the current canonical authorities.
```

## `tracks/t3-topology/dse/veritx_dse/workload/canonical.py`

```text
canonical.py — the canonical workload semantic artifact (Phase 9).

One authoritative workload-semantic representation that all supported
execution paths can lower from without silently changing the workload.

Derived from the audited semantics of the two live workload paths:

  Path B (serving):  LLMServingSim trace_generator rows → chakra → ET
  Path A (standalone BookSim): traffic_model.json flow classes

Represented semantic classes are exactly those the backends consume today
(no speculative collectives): COMPUTE, P2P send/recv, ALLREDUCE,
ALLGATHER, REDUCESCATTER, ALLTOALL, BROADCAST. Unknown kinds fail closed
(PR C lineage) — never warn-and-skip.

Rulings encoded here (Phase 9 handoff documents the evidence):

  BROADCAST (§6, Case B): the source format never guaranteed
  participants[0]=source, so source is an explicit validated field. The
  ASTRA backend already carries `bcast_root`; the positional convention
  does not survive canonicalization.

  Dimensional scope (§7): a comm op carries either an explicit boolean
  dim-participation vector or the ALL_DIMENSIONS sentinel. Scope absence
  on a comm op is a construction error — it is never read as "all dims",
  because the ASTRA fallback fabricates participation when the attribute
  is missing. Explicit [True, True] and ALL_DIMENSIONS are distinct
  values (they hash differently).

  Units (§10): every comm size is logical BYTES. Backend lowering may
  convert bytes→packets→flits but records the conversion parameters in
  its LoweringManifest — never silently.

  Identity (§16): the content hash covers schema version, participants,
  parallelism, and the ordered semantic ops. Presentation labels are
  excluded (a label rename must not change identity); operation order is
  semantic and therefore included.
```

## `tracks/t3-topology/dse/veritx_dse/workload/canonical_graph.py`

```text
veritx_dse.workload.canonical_graph — retired compatibility shim.

The Slice-2c migration is complete: the ONE canonical workload authority
is ``veritx_dse.workload.graph`` (ParallelismShape geometry). This module
re-exports it so historical imports keep resolving to the single
authority — it defines nothing itself and must never diverge.
```

## `tracks/t3-topology/dse/veritx_dse/workload/collectives.py`

```text
veritx_dse.workload.collectives — PRODUCTION collective algorithm spec.

This is the workload-owned definition of the pinned collective algorithms:
step counts, message counts and byte accounting. It is a SPECIFICATION, not
a reference implementation — ``workload/messages.py`` uses it to expand
collectives into logical messages, so it is the production authority for
"how many steps does ring allreduce take".

Independence note: ``verification/reference_semantics.py`` carries its own
``ref_collective`` equations on purpose. Production must never import the
reference module, and the reference must never import this one — otherwise
the differential test becomes "the spec agrees with itself", which is
exactly the defect found in the Wave-D group-law oracle (see
docs/ARCHITECTURE-CONSOLIDATION.md, F1).
```

## `tracks/t3-topology/dse/veritx_dse/workload/graph.py`

```text
veritx_dse.workload.canonical_graph — the ONE canonical workload authority.

Slice 2c, step 1: the authority itself. Nothing consumes it yet.

This module will become ``workload/graph.py`` when the competing
authorities are deleted (step 10): ``WaveDWorkload`` currently owns that
path. It is deliberately NOT named ``graph.py`` yet, because two workload
authorities in one module is worse than two modules for one migration
step, and a forwarding shim is forbidden.

Design laws (all enforced, none assumed):

* **One operation, one payload.** An ``OperationNode`` carries its closed
  per-kind ``detail`` mapping. There is no ``collectives=`` /
  ``p2p_transfers=`` / ``multicasts=`` side list to re-join by id.
* **The participant namespace is not the geometry.**
  ``participant_count`` is the rank space the operations address;
  ``parallelism`` is the system geometry. For a two-instance cluster they
  are 4 and 8. Ranks validate against ``participant_count``.
* **Absent stays absent.** ``owner``, ``phase``, ``step``, ``scope`` and
  ``routing_policy`` are optional because a legitimate source may not
  declare them. ``scope=None`` (undeclared) is NOT ``scope="ALL"``.
* **Declarations are permissive; schedules are strict.** A non-divisible
  ALLREDUCE is a valid declaration; the exact ring expansion refuses it.
  That law lives in ``workload/collectives.py``, not here.
* **Provenance never moves identity.** ``provenance`` is not hashed;
  labels and source spellings are not science (finding F23).
* **Structure is checked before any backend.** Stray/unclosed EXPERT and
  PIM regions refuse HERE, not as a Chakra IndexError.

Identity uses the shared ``core.artifact`` machinery — one implementation.
```

## `tracks/t3-topology/dse/veritx_dse/workload/intent_lowering.py`

```text
veritx_dse.workload.intent_lowering — v3 intent → canonical WorkloadGraph.

P1C: product workload intent lowers deterministically to the ONE canonical
WorkloadGraph authority (workload/graph.py — consumed, never forked). v2
requests are REFUSED here: v2 interpretation is frozen, and a
v2 CollectiveOp carries no dimension/payload/traffic-class facts to lower
from (compile_model B1 finding 1). Migrate explicitly first.

Lowering laws (all enforced, none assumed):

* **Dimensions derive groups, never guesses.** TP/DP/EP expand through
  ParallelismArtifact.groups (total, law-checked: every rank in exactly
  one group — tp=8,dp=4 yields four TP groups of eight). GLOBAL is the
  single all-ranks group. Group membership is derived, so participants
  are exact by construction; ranks are never guessed from group_size.
* **PP stages are not collective peers.** A PP-dimension COLLECTIVE is a
  typed refusal (stages communicate point-to-point; no proven peer
  semantics). pp>1 GEOMETRY is still supported: TP/DP groups scope
  within stages via the canonical rank algebra.
* **Dense transformer, and MoE by declared ops.** Any other model family
  is a typed refusal — diffusion, CNN, and custom topologies have no
  proven intent→collective mapping here. For mixture-of-experts the
  lowering maps exactly the declared collectives with their declared
  classes: a declared EP all-to-all is dispatch traffic, never an
  implied layer; expert compute has no duration semantics and combine
  traffic exists only when explicitly declared.
* **Ordered collectives.** Declared intent order becomes an explicit op
  chain (each op depends on its predecessor), so the graph has a unique
  dependency-derived total order. Declaration order is therefore v3
  identity (reordering intents is a different design).
* **No fabricated roots, scopes, or phases.** BROADCAST requires an
  explicit source_rank present in EVERY expanded group (multi-group
  broadcast with one root refuses rather than inventing per-group
  roots); scope is always None (undeclared is not ALL); phase is always
  None — serving_mode is serving characterization, never a per-operation
  phase declaration (no PREFILL_HEAVY -> pure-PREFILL mapping without
  evidence, and none is claimed).
* **Schedulability proven at lower time.** Every expanded group is
  checked against workload/collectives.py::collective_schedule (the
  pinned schedule authority) before the op is built: divisibility
  (B % k), minimums, and kind support refuse HERE, not at the backend.
* **Traffic classes ride alongside, not inside.** The canonical detail
  grammar carries no traffic-class field (by canonical law), so the
  lowering returns the graph PLUS a per-operation class sidecar
  (LoweredWorkload). One class per message is P1B evaluator wire-up
  (single-class fast path: build_single_class_messages); this module
  never forks messages.py.

B1 audit findings (for the record — see compile_model v3 section for
full evidence): the v2 per-element byte-count field meaning unproven (never
here); DependencyGraph names ad hoc in v2 (v3 unifies through
derive_v3_traffic_classes); v2 Requirement has no traffic_class;
LogicalMessageArtifactV2 is single-class (hence the sidecar);
trace_path is environment-sensitive (v3 has no path field).
```

## `tracks/t3-topology/dse/veritx_dse/workload/lowering.py`

```text
lowering.py — canonical artifact → backend representations (Phase 9).

Two targets, one rule: the artifact is the semantic parent, so every
lowering must be regenerable from the artifact ALONE (the reviewer's
sufficiency test) and must pass mechanical conservation against real
backend bytes — not against its own claims.

Targets:

  inspection        rows + header + broadcast roots. Pure projection of
                    the artifact; carries no ET claim. Exists so BROADCAST
                    workloads can be inspected without implying the ET
                    converter supports them yet.

  astra_chakra_et   the proven production lowering: the artifact →
                    LLMServingSim trace rows → the in-process chakra
                    LLMConverter (exactly what serving runs execute).
                    Verified against real ET bytes with a read-back
                    conservation check (op classes, per-rank comm bytes,
                    participants, per-rank dim scopes).

Refusals are hard: BROADCAST cannot produce an ET lowering until the
converter emits bcast_root (§18: no zero-loss manifest from an
unsupported semantic), and pp_stage_boundaries keep the Phase 1 T2
fail-closed ruling.
```

## `tracks/t3-topology/dse/veritx_dse/workload/memory_lowering.py`

```text
memory_lowering.py — CanonicalWorkload → MemoryArtifact resolver (Phase 14b).

Resolves per-op memory demand (COMPUTE input/weight/output bytes + locations)
against an explicit single-HBM-pool design into placed regions and an ordered
semantic access stream. Returns the artifact plus a conservation report; the
artifact itself carries everything Phase 15 needs.

Deliberate v1 boundaries (each documented where enforced):

* Op-scoped regions: one region per (op, operand). The workload carries no
  tensor identity across ops, so cross-op persistence (one weights region
  shared by many layers) would be invented semantics. Recorded as an
  assumption, not modeled.
* Fixed operand mapping: input→ACTIVATION, weight→WEIGHT, output→OUTPUT.
  No inference (a KV input is still ACTIVATION — the source does not
  distinguish it, so neither do we).
* Strict locations: only LOCAL resolves (to the design's HBM pool).
  REMOTE/CXL/STORAGE refuse as UnsupportedSemantic — "eh, use HBM" would
  silently reroute off-package traffic through the evaluated memory.
* Single-HBM designs only: multi-device placement needs an explicit
  sharding policy (future). Refuse, don't spread.
* Execution attribution is explicit: COMPUTE ops carry no placement, so
  the caller supplies per-op issue nodes (or one node for all, recorded
  as an assumption). Absent and ambiguous → refuse.
* Order, not timing: accesses chain positionally (workload op order is
  execution order — the ET lowering precedent); each op reads then
  writes, the write depending on the op's reads. No ready cycles invented.
* Zero/None operand bytes emit nothing (no empty regions, no zero accesses
  — both refuse at the schema, so the resolver skips them).
* Comm ops and structural markers carry no memory operands → ignored.
```

## `tracks/t3-topology/dse/veritx_dse/workload/messages.py`

```text
veritx_dse.workload.messages — logical messages over the canonical graph.

ONE lowering: the canonical :class:`WorkloadGraph` → canonical ordered
logical messages.

    COLLECTIVE        pinned schedule over declared participants
    BROADCAST         explicit declared source, never participants[0]
    P2P TRANSFER      one message
    P2P SEND/RECV     refused: not a complete transfer
    MULTICAST         one message per declared destination
    EXPERT_BEGIN/END  declared collective when it has >= 2 participants
    PIM_CHANNEL/END   no network message, ever
    COMPUTE           no network message

There are no communication side lists and no second graph authority: the
WorkloadGraph IS the authority, so the parent identity is ``workload_id``
and the rank namespace is the graph's ``participant_count`` (never the
world rank space).

Exactly one schedule per collective kind, pinned:

    ALLREDUCE ring · REDUCESCATTER ring · ALLGATHER ring
    ALLTOALL direct · BROADCAST root fanout

Conservation is per operation class — never a generic byte law. The
production schedule arithmetic lives in ``workload/collectives.py``; the
independent oracle lives in the test suite, deliberately not here, so a
differential test cannot degenerate into "the spec agrees with itself".
```

## `tracks/t3-topology/dse/veritx_dse/workload/migration.py`

```text
veritx_dse.workload.migration — historical formats -> WorkloadGraph.

Slice 2c.3. ONE narrow boundary. It is not a workload authority: it reads
an authenticated historical representation, validates it with its OWN
historical rules, extracts semantics, and produces a ``WorkloadGraph``.
Nothing here is a runtime model — production consumers use the graph.

The migration law (Rule 2), enforced by ordering rather than by comment:

    legacy bytes
      -> legacy parser            (its own schema)
      -> legacy identity recomputed and COMPARED   <- refuses before here
      -> semantic extraction
      -> WorkloadGraph
      -> canonical-v2 identity

Legacy bytes are NEVER reinterpreted under v2 hashing, and a legacy hash
is never smuggled forward as canonical ancestry: it is preserved as
NON-IDENTITY provenance so old artefacts stay auditable.

Also here: the direct trace-row reader, which must NOT route through the
legacy workload authority (that is what dropped PIM — finding F16).
```

## `tracks/t3-topology/dse/veritx_dse/workload/operations.py`

```text
veritx_dse.workload.operations — OperationGraph (D2, §15–§19, §27–§29).

One immutable deterministic operation graph per (workload, parallelism,
semantics). The graph contains EXACTLY the operations the workload
declares — nothing synthesized, nothing dropped.

Identity is the mechanical parent DAG of §23.2:

    operation_graph_id = H(workload_id, parallelism_id,
                           wave_d_semantics_id, canonical nodes,
                           canonical edges)

DAG laws (§17): every dependency references an existing node, no
self-dependency, acyclic. Repeated decode steps are explicit per-step
nodes (step index in the node), never graph cycles.
```

## `tracks/t3-topology/dse/veritx_dse/workload/semantics.py`

```text
veritx_dse.workload.semantics — WaveDWorkloadSemantics (D1/D2, §12/§14).

A separate immutable versioned Wave-D semantic envelope, orthogonal to
the frozen CompileRequest ``design_hash`` (§23.4): it carries ONLY the
fields the implemented Wave-D semantics actually consume.

Model shape metadata is admitted only as content: either the caller
passes the descriptor dict itself (hashed by value here) or a
descriptor content hash. A bare model name is never identity (§14) —
``model_descriptor_name`` may ride along as provenance but is excluded
from the identity payload unless a descriptor hash binds it.
```

## `tracks/t3-topology/dse/veritx_dse/workload/timeline.py`

```text
Phase 16 — System Execution / Bottleneck Attribution.

One dependency-aware timeline over declared per-op backend service legs,
answering the product question: *what actually delayed this workload —
and what would improving each subsystem actually save?*

Relationship to the plan: the CanonicalWorkloadArtifact is the semantic
parent (Phase 9); BookSim/analytical/memory evidence conventions come
from Phases 5/15. Phase 16 does NOT couple simulators (reviewer §Phase
16): it composes DECLARED per-op service legs through the workload's
dependency structure and attributes stalls.

Canonical time unit
-------------------
Every leg is normalized to NANOSECONDS before any comparison:
    compute_ns = compute_cycles × compute.ns_per_cycle
    memory_ns  = mem_cycles     × mem.ns_per_cycle      (the MEM clock)
    network_ns = net_cycles     × net.ns_per_cycle      (the NET clock)
    rate_ns    = bytes / bytes_per_second × 1e9        (SI: no clock)
Cycles without a clock are not time — a service leg in cycles with no
binding for its dimension raises (fail closed; the 2026-09-18 review
found compute-ns, mem-on-compute-clock, raw net cycles, and raw seconds
mixed inside one max()).

Op model (where overlap comes from)
-----------------------------------
- The artifact's op ORDER is the dependency carrier (the ET lowering
  chains nodes positionally): op *i* is released when op *i-1* finishes.
  No dependency edges are invented here.
- One op = one dependency step issuing its service legs CONCURRENTLY:
    finish = ready + max(legs_ns)
- Per op the attribution reports SEPARATE metrics (never overloaded):
    service_ns(d)          the declared leg
    exposed_stall_ns(d)    max(0, leg − max other leg)  — the COUNTER-
                           FACTUAL: runtime saved if dimension d were
                           instantaneous. A 20,000ns compute beside a
                           5,000ns mem fetch → compute stall 15,000
                           (removing compute saves exactly that), mem 0.
    overlap_ns(d)          leg − exposed_stall — the hidden part
    critical_path_owner    dimension(s) whose leg == step span; the
                           step's span is attributed fully to them
                           (ownership, NOT stall — a tie credits each)
- Legs by op kind (all values DECLARED, never defaulted):
    COMPUTE            compute leg (required) + optional memory leg
                       (mem_cycles — operand fetch service, e.g. from a
                       Ramulator evaluation of the operand stream)
    comm (net form)    single net leg (net_cycles, e.g. BookSim evidence)
    comm (rate form)   concurrent mem/comp legs: bytes/mem_bw and
                       bytes/comp_bw (transfer overlaps local work)
  A comm op declares EITHER net_cycles OR the rate pair — both is
  ambiguous, neither is unservable.
- SYNC: the v1 canonical op set has no barrier semantics, so there is no
  sync leg and SYNC_BOUND is unreachable in v1 — recorded as an explicit
  assumption on every attribution, never as a silent zero.

Verdicts (§ reviewer spec, on exposed STALL — the savings question)
-------------------------------------------------------------------
The one rule (2026-09-18 consolidation-2):
    net service > 0 AND net stall == 0  → NETWORK_NOT_THE_BOTTLENECK
    net stall > 0, tied with another dim → MIXED (co-bottlenecks:
        improving either independently still saves runtime)
    net stall unique max                → FABRIC_BOUND
  COMPUTE_BOUND / MEMORY_BOUND          — unique stall leader
  MIXED                                 — tie or leader margin ≤ 0.05
  INCONCLUSIVE                          — no dimension carries service
```

## `tracks/t3-topology/dse/veritx_dse/workload/traffic.py`

```text
veritx_dse.workload.traffic — participant binding + physical traffic.

One authoritative projection:

    LogicalMessageArtifactV2 + canonical Mapping/Attachment/Inventory
        + canonical PacketFormatArtifact + canonical ResolvedFabric
        → participant→endpoint binding → packets → flits

Bit-exact rules (unchanged from the proven Wave-D/E implementation):

    message_bits            = payload_bytes × 8
    packet payload capacity = Q × L     (Q = payload field width,
                                         L = max_packet_flits)
    N_packets               = ceil(message_bits / (Q × L))
    Σ packet_payload_bits   = message_bits                (exact)
    per packet i:  n_i = ceil(P_i / Q); padding_i = n_i·Q − P_i;
                   header_bits_i = n_i·H; transmitted_bits_i = n_i·F
                   transmitted_bits_i == header_bits_i + P_i + padding_i

Header width H is DERIVED from the authoritative PacketFormatArtifact field
layout (every flit repeats the header).

PARTICIPANT IDENTITY IS NOT GEOMETRY

``participant_count`` is the namespace the operations address; the mapping's
rank space is the deployment geometry. A participant is bound to a physical
endpoint only through the canonical MappingArtifact (rank→agent) and
AgentAttachmentArtifact (agent→endpoint). A missing or unattached
participant fails closed: logical rank == endpoint is never assumed.
```


# `workload` — extracted inline comments

## `tracks/t3-topology/dse/veritx_dse/workload/canonical.py`

line 36:

```text
# MoE structural markers (audit: the converter branches on EXPERT rows to
# build the per-EP-rank subgraph and attach the dispatch/combine
# collectives). They optionally carry a collective.
```

line 143:

```text
        # Presentation sidecar (§16): serialized so backend lowerings can
        # reproduce executed bytes (ET node names come from source layer
        # labels), but _identity_dict strips it — a label rename must not
        # change workload identity.
```

line 455:

```text
        # Presentation sidecar (§16): labels ride in the serialized
        # artifact so backend lowerings reproduce executed bytes (ET node
        # names are source layer labels); they were stripped from
        # _identity_dict, so the recorded artifact_hash never covers them.
```

line 595:

```text
        # Location columns are converter-consumed semantics (tensor_loc /
        # tensor_device in the ET; ASTRA dispatches issue_remote_mem on
        # them) — carried verbatim and validated, never dropped.
```

line 606:

```text
                # P/D KV send in the serving trace: point-to-point bytes
                # on a NONE comm row are the pp kv transfer in
                # decode-heavy placement; represent as an explicit P2P
                # only when a source path declares it — otherwise refuse,
                # because inferring endpoints here would fabricate
                # semantics (§5).
```

## `tracks/t3-topology/dse/veritx_dse/workload/collectives.py`

line 11:

```text
#: THE single production authority for the collective-kind vocabulary and
#: the pinned algorithm per kind (C2.2). ``graph``, ``operations``,
#: ``messages`` and ``migration`` import these; they must never redefine
#: them, so two layers cannot drift into accepting or scheduling different
#: collectives (the F-0004/F-0006 failure mode). The verification reference
#: keeps its own independent equations on purpose.
```

line 55:

```text
        # F-0006: ring ALLGATHER forwards CHUNKS of B/k, not the whole
        # payload. Using B per message made aggregate = k(k-1)B instead of
        # the ring law (k-1)B — a factor-k over-transmission.
```

## `tracks/t3-topology/dse/veritx_dse/workload/graph.py`

line 65:

```text
# collective kinds a COLLECTIVE / EXPERT payload may name.
# The vocabulary is owned by ``workload.collectives`` (C2.2); importing it
# (rather than redefining) makes drift between layers impossible.
```

line 493:

```text
        # ONE validator for builders and readers alike: exact key set plus
        # full semantic revalidation. A strict reader is adversarial and
        # may not trust that a builder produced this value.
```

line 497:

```text
            # STRUCTURE ONLY: a bare node does not know the participant
            # namespace, and it must not cache one (a frozen object that
            # changes depending on which graph touched it last is an
            # aliasing bug). The GRAPH validates bounds against its own
            # namespace, without writing anything back into the node.
```

line 652:

```text
        # Namespace law enforced HERE, read-only: the node is frozen and
        # stays byte-identical no matter which graphs reference it. The
        # same node may legally live in graphs with different participant
        # counts; passing validation is what makes that legal.
```

line 805:

```text
        # PIM is a STATE MACHINE, not nesting: inactive -> (PIM_CHANNEL ch)*
        # -> PIM_END -> inactive. Consecutive channel markers are legal
        # (the producer emits them even for empty channels).
```

## `tracks/t3-topology/dse/veritx_dse/workload/intent_lowering.py`

line 272:

```text
    # The chain construction guarantees a unique dependency order; prove
    # it (a positional source must satisfy this naturally, and any
    # future edit that breaks chaining refuses here, not downstream).
```

line 359:

```text
    # VC-domain soundness for the bound classes (beyond mere existence).
    # The (channel, VC) deadlock proof and the fork's single VC envelope
    # can only reason about VCs with exactly one routing class, so every
    # VC a bound class uses — and every VC in allowed_transitions — must
    # name its routing class. Overlap itself is legitimate when every
    # bound class carries the full VC envelope (the shipped MoE design
    # shares one VC across classes); overlap on a SUBSET is refused
    # because the backend executes the whole envelope, never the claimed
    # subset (vc_exactness re-checks this at qualification).
```

## `tracks/t3-topology/dse/veritx_dse/workload/lowering.py`

line 155:

```text
                # The generator emits bare markers as
                # "EXPERT <n> NONE 0" / "EXPERT END NONE 0" — the NONE/0
                # columns are part of the row shape the converter's
                # marker split expects, and the ET embeds the trace text
                # verbatim, so byte parity needs the exact spelling.
```

line 166:

```text
            # The text format has no src/dst columns; converter SEND/RECV
            # pairs are synthesized per-PP-rank from adjacent sizes at
            # conversion time. A standalone SEND cannot enter the row
            # format without fabricating endpoints (§5) — refuse.
```

line 180:

```text
            # Inspection-only projection: rows keep the semantic bytes;
            # the explicit root is machine-readable in root_by_row (the
            # bcast_root the backend already consumes via Workload.cc).
```

line 186:

```text
        # plain collectives co-locate on a layer row (one comm per
        # layer): attach backward to the just-emitted layer row when its
        # slot is free (the canonicalizer's order: compute, then its
        # collective from the same source row); otherwise pend for the
        # next layer row; if no layer row follows, the trailing flush
        # emits them standalone
```

line 359:

```text
        # P2P TRANSFER / MULTICAST: no row encoding (refused for the ET
        # target above); inspection carries them as explicit markers so
        # the projection is total without fabricating dialect rows.
```

line 649:

```text
        # Conserved transformations (each verified by conservation, not
        # assumed): ns durations ride the trace column unchanged; logical
        # BYTES become the ET comm_size attr unchanged; dim vectors ride
        # the :1,0 column encoding into the ET involved_dim attr; layer
        # order becomes per-rank node order.
```

## `tracks/t3-topology/dse/veritx_dse/workload/memory_lowering.py`

line 96:

```text
        # LOCAL:<dev> suffix (canonical grammar allows it): the owning
        # device must BE the pool — a LOCAL claim on another device is a
        # remote access mislabeled, not local memory.
```

line 266:

```text
    # Allocate per placement scope (separate physical memories must not
    # share one cursor — identical numeric addresses across scopes are
    # distinct locations, not collisions).
```

line 277:

```text
    # Access stream: workload order, reads before the op's write, the
    # write depending on the op's reads, each op chaining after the
    # previous op's last access (positional chaining — order, not timing).
```

line 331:

```text
# ── Phase 15a: MemoryArtifact → Ramulator trace lowering ───────────────────
#
# Boundary (spike-proven): the ReadWriteTrace frontend consumes text lines
#   R|W ch,pc,sid,bg,bank,row,col
# i.e. BACKEND address vectors, not byte addresses, issuing one request per
# frontend tick. This lowering is a pure function of (artifact + explicit
# backend geometry): it never imports Ramulator, so it runs on any VeriTX
# interpreter (the bindings are interpreter-tagged). Geometry mismatch with
# the executing backend is a Phase-15b execution-time check against this
# manifest's backend_config_hash — not something lowering can see.
```

line 345:

```text
# Bytes→addr_vec policy: sequential transactions fill column fastest, then
# bank, bankgroup, sid, pseudo-channel, channel, row slowest. Rationale:
# a sequential tensor stream stays row-local as long as possible (streaming
# behavior), spreading across banks/channels only as addresses grow — the
# locality-monotonic choice. Row slowest means crossing a row boundary is
# always visible as a deliberately large address step, never an accident
# of interleaving. Versioned: any order change is a new mapping version.
```

line 592:

```text
        # VeriX extended trace form: <op> <flat_byte_addr> <addr_vec> —
        # the flat address is the controller's coalescing/forwarding key
        # (the lowerer KNOWS the logical byte address; never invent a
        # hash of the addr_vec for it).
```

## `tracks/t3-topology/dse/veritx_dse/workload/messages.py`

line 30:

```text
#: the pinned algorithm label per collective kind (identity-bearing)
# Collective algorithms are owned by ``workload.collectives`` (C2.2) and
# imported above; the historical ``messages.SCHEDULES`` name still resolves.
#: the pinned multicast replication schedule
```

line 120:

```text
        # F-0004: a ring collective moves data ONLY between logical
        # neighbours. Every step, each rank sends one chunk to its next
        # ring neighbour; the CHUNK ownership rotates, the network edge
        # does not. (The previous offset exchange used all pairs.)
```

## `tracks/t3-topology/dse/veritx_dse/workload/migration.py`

line 75:

```text
        # NO fallback transformations. The historical reader already
        # applies the real historical defaults when a field is ABSENT;
        # a hash-valid document that explicitly carries null/"" is
        # MALFORMED and must refuse rather than be silently rewritten
        # into different, valid-looking semantics.
```

line 328:

```text
        # the dialect has two row shapes: an 11-field layer tuple, and a
        # MARKER row whose whole text arrives in a single field
        # ("PIM 0",) / ("EXPERT END REDUCESCATTER:1,0 4096",)
```

line 380:

```text
        # comm columns, parsed exactly as the converter's
        # _parse_comm_type does: a BARE collective means UNDECLARED scope
        # (the converter returns involved_dim=None), while KIND:1,0 is an
        # explicit mask. The historical parser turned bare syntax into
        # "ALL" — an over-claim the source never made.
```

## `tracks/t3-topology/dse/veritx_dse/workload/operations.py`

line 41:

```text
# Collective kinds and their pinned schedules are owned by
# ``workload.collectives`` (C2.2); re-exported here for the historical
# import surface without redefining them.
```

line 247:

```text
        # Read-only index over a dict no one else holds a reference to:
        # the node objects themselves are frozen, so the graph content
        # cannot be mutated after construction.
```

## `tracks/t3-topology/dse/veritx_dse/workload/semantics.py`

line 92:

```text
        # Deep immutability: the caller's container is copied into an
        # immutable canonical map, so later mutation of the original
        # cannot change this artifact or its identity.
```

## `tracks/t3-topology/dse/veritx_dse/workload/timeline.py`

line 354:

```text
        # Ownership: full span to the longest leg(s) — a tie credits each
        # tied leg, so ownership sums may exceed the span exactly when a
        # single-owner verdict must be refused.
```

line 458:

```text
    # A positive tie between net and another dimension is MIXED, never
    # NETWORK_NOT_THE_BOTTLENECK: making the fabric instantaneous saves
    # mx ns — the network clearly matters (consolidation-2 ruling; the
    # old net-tie special case contradicted the counterfactual).
```


# `workload` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/workload/canonical.py` :: `WorkloadArtifact`

```text

    Not a universal IR: exactly the semantic content the audited
    execution paths consume. Lowering proceeds from this artifact to
    backend representations; every lowering emits a LoweringManifest
    and must pass conservation checks (§13).
```

## `tracks/t3-topology/dse/veritx_dse/workload/canonical.py` :: `WorkloadError`

```text

    Raised on unknown operation kinds, invalid participants, missing
    required scope/units, or conservation failure — never a warning.
    (PR C fail-closed lineage; Phase 9 §4/§5/§13.)
```

## `tracks/t3-topology/dse/veritx_dse/workload/canonical.py` :: `WorkloadOp`

```text

    kind:     one of _KNOWN_KINDS (unknown → WorkloadError)
    op_id:    stable logical identity within the artifact
    bytes:    communication volume in logical BYTES (comm ops only);
              compute ops carry bytes=None — mixing the two is an error
    participants: tuple of ranks, all validated against the artifact
    scope:    explicit dim-participation vector or ALL_DIMENSIONS
              (comm ops); None (unused) on compute ops
    src/dst:  explicit endpoints for SEND/RECV/BROADCAST (§6: never
              inferred from participant order)
    duration_ns: compute duration in nanoseconds (compute ops only)
    input_bytes/weight_bytes/output_bytes: memory operand sizes in BYTES
              (compute ops; the converter emits memory load/store nodes
              from them — audit-backed semantics, part of identity)
    input_loc/weight_loc/output_loc: memory operand locations, the
              trace's verbatim location grammar ("LOCAL", "REMOTE:<dev>",
              "REMOTE:<dev>.<chan>", "CXL...", "STORAGE") — the converter
              derives tensor_loc/tensor_device from them and ASTRA
              dispatches issue_remote_mem on the result, so they are
              converter-consumed semantics and part of identity
    comm_kind: for EXPERT_BEGIN/EXPERT_END markers, the optional
              collective they carry (None = bare structural marker)
    expert_num: expert index for EXPERT markers
    label:    presentation-only; excluded from the content hash
```

## `tracks/t3-topology/dse/veritx_dse/workload/canonical.py` :: `artifact_from_trace_rows`

```text

    The rows ARE the semantic source for serving runs: the in-process
    chakra converter consumes exactly these field tuples (11 fields per
    layer row, 1 field for EXPERT/PIM markers), so canonicalizing from
    them loses nothing the backend ever saw.

    Fail-closed: an unknown comm_type is a WorkloadError naming the type
    — mirroring _parse_comm_type's supported set plus SEND/RECV pairs,
    which the converter synthesizes for PP from adjacent sizes.

    has_pp_stage_boundaries: the trace header declared pp_stage_boundaries
    (Phase 1 T2 ruling): the ET converter has no pipeline-parallel
    semantics and refuses them, so canonicalization refuses too — the
    semantics cannot survive the lowering, so they cannot enter the
    canonical artifact silently.
```

## `tracks/t3-topology/dse/veritx_dse/workload/graph.py` :: `WorkloadGraph`

```text

    ``provenance`` is deliberately NOT part of ``workload_id()``: it
    carries source metadata (origin run, trace file, source spelling) that
    must never move scientific identity.
```

## `tracks/t3-topology/dse/veritx_dse/workload/intent_lowering.py` :: `LoweredWorkload`

```text

    ``graph`` is the canonical authority (identity-bearing).
    ``traffic_class_by_operation`` maps every COLLECTIVE operation id to
    its unified-namespace class (sorted by operation id; complete: every
    graph COLLECTIVE op appears exactly once). ``design_hash`` binds the
    v3 request identity this was lowered from.
```

## `tracks/t3-topology/dse/veritx_dse/workload/intent_lowering.py` :: `bridge_to_evaluation_messages`

```text

    P1C phase-2 (Fix 3). The P1B evaluator takes one global traffic
    class while LoweredWorkload carries per-operation classes:

    * **Supported first case** — the lowering is single-class
      (``unified_traffic_class is not None``): route through
      build_single_class_messages() into the canonical
      LogicalMessage → PhysicalTraffic → gates → backend chain.
      Every message honestly carries the lowered class.
    * **Multi-class → typed refusal** (UnsupportedSemantics, code
      UNSUPPORTED_SEMANTICS — P1B maps it to EvaluationOutcome
      UNSUPPORTED): one V2 artifact cannot carry per-message classes,
      so representing it would be lossy. The per-operation artifact
      DOES exist (``LogicalMessageArtifactV3``, multi-class lowering);
      this bridge stays single-class V2 by contract, so multi-class
      traffic must go through the V3 builders, never through here.
      The collective schedule is NOT forked, v2 message identity is
      NOT mutated, and the sidecar (traffic_class_by_operation) is
      kept as the per-operation record.

    ``requested_traffic_class`` carries the P1B
    EvaluationOptions.traffic_class through as an ASSERTION, never a
    label: when given it must equal the lowered class, else refusal.
    Direction for P1B: that option is legacy/test-only — a user must
    never relabel traffic at eval time (e.g. best_effort evaluated as
    latency_critical would forge QoS evidence). The lowered intent
    owns class names; evaluation only checks them.
```

## `tracks/t3-topology/dse/veritx_dse/workload/intent_lowering.py` :: `lower_compile_workload`

```text

    Supported: dense transformer and mixture-of-experts intents with
    TP/DP/EP/GLOBAL ordered collectives. Everything else is a typed
    refusal (see module laws). Deterministic: same request ->
    byte-identical graph (workload_id stable across runs and processes).

    Declared-ops law (MoE): the lowering maps exactly the declared
    collective intents, each with its declared traffic class. A declared
    EP all-to-all is dispatch traffic — never an implied full MoE layer:
    expert compute has no duration semantics here and combine traffic
    exists only when a combine collective is explicitly declared. The
    run therefore measures declared communication, and per-operation
    classes ride the sidecar to the per-message artifact.

```

## `tracks/t3-topology/dse/veritx_dse/workload/lowering.py` :: `RowsProjection`

```text

    ``root_by_row`` records the explicit BROADCAST source per emitted
    row (§6 Case B); root 0 (the ASTRA default) is recorded explicitly
    too, so consumers never have to re-derive it positionally.

    ``comm_op_by_row`` maps a layer row index to the op_id of the
    collective co-located on it (the trace dialect's one-comm-per-layer
    rule — the converter emits that collective from that row).
```

## `tracks/t3-topology/dse/veritx_dse/workload/lowering.py` :: `rows_from_artifact`

```text

    For artifacts built from real trace rows this is a byte-identical
    round trip (proven by the equality goldens): the trace dialect
    co-locates each collective on a layer row's comm columns (one comm
    per layer — the converter's shape), so an attach-comm op merges into
    the next compute op's row instead of becoming its own row.
    Synthetic artifacts produce rows carrying the same semantic fields
    the proven path consumes — the sufficiency test lower_to_et then
    proves they feed the real converter without consulting the source
    rows again.

    target="astra_chakra_et" additionally refuses BROADCAST: the ET
    converter has no broadcast emission until bcast_root is threaded
    through it, so no ET claim may be made (fail-closed, §18).
```

## `tracks/t3-topology/dse/veritx_dse/workload/lowering.py` :: `rows_from_graph`

```text

    Same dialect as rows_from_artifact (11-field layer rows, 1-field
    marker rows, one comm per layer with pending/flush co-location), in
    the graph's total order. COMPUTE ops become layer rows; COLLECTIVE
    ops ride layer comm columns; EXPERT/PIM markers pass through in
    their source spelling so workload_graph_from_trace_rows recovers
    them byte-identically.

    Dialect limits (fail-closed, same culture as the artifact path):
    BROADCAST rows carry no root in this dialect for the ET target —
    inspection records the explicit source in root_by_row while the ET
    target refuses; P2P TRANSFER has no row encoding (the converter
    synthesizes pairs positionally — explicit endpoints would be
    fabricated); MULTICAST destinations are not representable either.
```

## `tracks/t3-topology/dse/veritx_dse/workload/memory_lowering.py` :: `MemoryLoweringManifest`

```text

    Mirrors workload/lowering.py:LoweringManifest culture: semantic_losses
    is [] ONLY because the conservation asserts in lower_to_ramulator_trace
    ran (never claimed from completion), and coverage is total-or-refuse.
```

## `tracks/t3-topology/dse/veritx_dse/workload/memory_lowering.py` :: `MemorySystemDesign`

```text

    hbm_devices: device ids exposing HBM. Exactly one in v1 — placement
                 below device granularity (stack/bank/row) belongs to the
                 Phase-15 lowerer, and spreading tensors across pools
                 without a sharding policy would invent placement.
```

## `tracks/t3-topology/dse/veritx_dse/workload/memory_lowering.py` :: `RamulatorGeometry`

```text

    Level counts (>0 ints) in ReadWriteTrace addr_vec order plus the
    transaction size the backend serves per request. All caller-supplied:
    transcribing them here (instead of importing Ramulator) keeps the
    lowering pure and interpreter-independent; the manifest hashes them so
    15b execution can prove it ran the same geometry. Use
    hbm3_16gb_8hi_geometry() for the audited preset transcription.
```

## `tracks/t3-topology/dse/veritx_dse/workload/memory_lowering.py` :: `expand_access`

```text

    The backend serves whole transactions (req.size_bytes = tx, set by the
    frontend — a partial tail still occupies a full request). Padding is
    explicit: front_pad bytes before the access inside the first tx,
    back_pad after it inside the last tx. The flat byte address of each
    transaction (tx_index * transaction_bytes) rides beside its addr_vec:
    it is the equality key for controller write coalescing / read
    forwarding (the req.addr == -1 aliasing bug, fixed 2026-09-18 —
    without it, unrelated requests shared one coalescing key). Pure: no I/O.
```

## `tracks/t3-topology/dse/veritx_dse/workload/memory_lowering.py` :: `hbm3_16gb_8hi_geometry`

```text

    Level sizes transcribed from the vendored tree
    (third_party/ramulator2/python/ramulator/dram/hbm3.py,
    HBM3.org_presets["HBM3_16Gb_8hi"]; test_transcription_pin pins them):
    pseudochannel=2, sid=2, bankgroup=4, bank=4, row=16384, column=256.
    transaction_bytes=64 from dram_spec.h
    (internal_prefetch_size 8 × channel_width 64 / 8; HBM3.cpp sets
    internal_prefetch_size=8 and the preset carries no payload override).
    Channel COUNT is configuration (stacks × channels/stack), not preset —
    caller-supplied, defaulting to 1 for single-channel experiments.
```

## `tracks/t3-topology/dse/veritx_dse/workload/messages.py` :: `LogicalMessageArtifactV3`

```text

    V2 stamps one uniform class on every message; a multi-class lowering
    cannot be represented that way without loss, so V3 stamps each
    message with its operation's lowered class from the sidecar
    (``traffic_class_by_operation``: every communicating graph op — every
    COLLECTIVE plus every EXPERT_BEGIN/END that declares >= 2 participants —
    exactly once, sorted). Construction, schedule records and conservation are
    the shared law (:func:`_build_messages`); only the class stamp is
    per-operation, and it is identity-bearing, so a V3 id can never
    collide with a V2 id over the same graph.
```

## `tracks/t3-topology/dse/veritx_dse/workload/messages.py` :: `_TrafficClassAuthority`

```text

    Traffic-class names are validated at physical-binding time against
    ``VCAssignmentArtifact.traffic_class_to_vcs``; here one class is
    assigned per message from the declaration or the pinned default.
```

## `tracks/t3-topology/dse/veritx_dse/workload/operations.py` :: `CollectiveIntent`

```text

    Payload meaning is per-kind (§10.1): input tensor bytes per rank for
    ALLREDUCE/REDUCESCATTER, local contribution per rank for ALLGATHER,
    total input per rank for ALLTOALL, root payload for BROADCAST.
```

## `tracks/t3-topology/dse/veritx_dse/workload/operations.py` :: `OperationNode`

```text

    ``detail`` is the canonical per-kind payload (dict of typed values)
    consumed by lowering; ``step`` distinguishes repeated decode
    instances (identity-bearing; cycles are forbidden).
```

## `tracks/t3-topology/dse/veritx_dse/workload/semantics.py` :: `WaveDWorkloadSemantics`

```text

    Identity payload: schema version, phase, routing policy, declared
    shape metadata (sorted canonical dict), model descriptor content
    hash. ``model_descriptor_name`` rides as provenance only.
```

## `tracks/t3-topology/dse/veritx_dse/workload/timeline.py` :: `BackendBinding`

```text

    ns_per_cycle: REQUIRED for any cycle-denominated service on this
    dimension (cycles without a clock are not time — a default of 1.0
    would silently double time when the real clock is 0.5 ns/c).
    None is legal ONLY for bindings used exclusively with rate-form
    service (bytes/second is SI and needs no clock). No silent default.
```

## `tracks/t3-topology/dse/veritx_dse/workload/timeline.py` :: `OpRecord`

```text

    legs          declared service per dimension
    exposed       critical-path OWNERSHIP: the step span credited to the
                  longest leg's dimension(s) (a tie credits each)
    exposed_stall COUNTERFACTUAL savings: max(0, leg − max other leg) —
                  what runtime drops if that dimension were instantaneous
    overlap       legs hidden under a concurrent longer leg
    owners        dimension(s) whose leg == the step span
```

## `tracks/t3-topology/dse/veritx_dse/workload/timeline.py` :: `OpService`

```text

    net_cycles OR (mem_bw, comp_bw) — never both (ambiguous authority).
    mem_cycles is the COMPUTE-op operand memory leg (explicit None = the
    op declares no memory service; absent is recorded, not zero-filled).
```

## `tracks/t3-topology/dse/veritx_dse/workload/traffic.py` :: `PhysicalTrafficArtifactV2`

```text

    Binds the message artifact, the canonical ResolvedFabric, the
    participant→endpoint mapping it actually used, and the canonical
    PacketFormatArtifact. Packet endpoints come from that mapping, so
    logical rank == physical endpoint is never assumed: a 4-participant
    workload on an 8-rank fabric lowers through its own explicit binding,
    and refuses only when a participant has no authenticated binding.
```

## `tracks/t3-topology/dse/veritx_dse/workload/traffic.py` :: `PhysicalTrafficArtifactV3`

```text

    Binding, packetization and conservation are the V2 law unchanged
    (rank→endpoint binding has no class semantics); only the accepted
    logical version and the identity tag differ, so a V3 physical id can
    never collide with a V2 id. Per-message classes ride on the logical
    messages — packets stay class-blind. The class-aware trace dialect
    (booksim2-fork/v2) renders each message's canonical class from the
    logical authority; the multi-class profile binds the executed class
    identity into the prepared input.
```


# `workload` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/workload/canonical.py` :: `_identity_dict`

```text

        Excluded on purpose: labels, timestamps, paths, run ids —
        presentation metadata must not alter scientific identity (labels
        DO ride in serialize() as a lowering sidecar; they are stripped
        here so the content hash never sees them).
        Included: operation ORDER (semantically meaningful; the ET
        lowering chains nodes positionally).
```

## `tracks/t3-topology/dse/veritx_dse/workload/canonical.py` :: `check_conservation`

```text

    lowered_ops: iterable of tuples. For comm ops:
        (op_id, kind, bytes, participants_tuple, scope)
    For compute ops:
        (op_id, "COMPUTE", None, None, None)

    Order-sensitive (the ET lowering chains nodes positionally), so a
    reordering is itself a conservation failure, matching §9.
```

## `tracks/t3-topology/dse/veritx_dse/workload/graph.py` :: `_canonical_detail`

```text

    Every canonical detail must have EXACTLY its canonical field set —
    optional semantic values are represented explicitly as ``None``, never
    by dropping canonical keys. This is the single implementation used by
    the builders AND by every reader (a strict reader is an adversarial
    boundary, so it may not trust that a builder validated the value).
```

## `tracks/t3-topology/dse/veritx_dse/workload/graph.py` :: `_parallelism_from_dict`

```text

    Re-parented onto the CURRENT canonical ``ParallelismShape`` (the
    geometry authority ``NodeInventory`` is built from). The historical
    Wave-D ``ParallelismArtifact`` carried a derived world size and an
    embedded ``parallelism_id``; neither is a second authority here — the
    shape is the four dimensions and nothing else.
```

## `tracks/t3-topology/dse/veritx_dse/workload/graph.py` :: `_unique_topological_order`

```text

        Raises when more than one operation is simultaneously ready: such
        a graph has no unique dependency order, so region membership
        (EXPERT/PIM) would have to come from construction order, which
        identity deliberately ignores. Refusing is the only honest answer;
        a legitimate positional source (LLMServingSim/ET rows, Phase-9
        ops) migrates to an explicit chain and satisfies this naturally.
```

## `tracks/t3-topology/dse/veritx_dse/workload/graph.py` :: `pim_detail`

```text

    NOT a region opener. The producer emits ``PIM 0``, rows, ``PIM 1``,
    rows, ..., then ONE ``PIM END``; the matching converter keeps
    ``pim_start`` true across markers and only switches which channel owns
    the following attention rows. Repeated markers are channel SELECTION,
    not nesting — modelling them as BEGIN/END nesting would reject a
    legitimate producer trace.
```

## `tracks/t3-topology/dse/veritx_dse/workload/intent_lowering.py` :: `assert_traffic_classes_bound`

```text

    Every lowered class must exist in the VC artifact's
    traffic_class_to_vcs with a non-empty legal VC set. Unknown class =
    typed refusal, never a silent VC0. P1B calls the same predicate
    before backend spawn; P1C calls it at lowering time so an unbound
    intent fails before any evaluation is attempted.
```

## `tracks/t3-topology/dse/veritx_dse/workload/intent_lowering.py` :: `build_multi_class_messages`

```text

    Each message carries its own operation's lowered class from the
    sidecar — no flattening to one class, no loss. Admission against
    the compiled VC assignment stays per-class downstream
    (:func:`fabric_evaluator._admit_traffic_classes` iterates messages,
    and :func:`assert_traffic_classes_bound` mirrors it here).
```

## `tracks/t3-topology/dse/veritx_dse/workload/intent_lowering.py` :: `build_single_class_messages`

```text

    Refuses multi-class lowerings: one V2 artifact assigns one class to
    every message, so a multi-class graph cannot be represented without
    loss. Per-message classes are P1B evaluator wire-up (integration
    note in the P1C report); this helper covers the mesh_dense_64 case
    where every intent shares one class.
```

## `tracks/t3-topology/dse/veritx_dse/workload/lowering.py` :: `et_readback_conservation`

```text

    Per rank r (group g = r // npus_per_group), each comm op must appear
    as a comm node with the op's byte count and scope — accounting for
    the converter's audited partitioning: ranks outside group g skip
    group-g collectives; ALLTOALL is N² membership so it appears on
    every in-scope rank. Byte volume is conserved per participant, and
    participants/dim scopes must match exactly.
```

## `tracks/t3-topology/dse/veritx_dse/workload/lowering.py` :: `lower_to_et`

```text

    ``rows`` should come from rows_from_artifact(art) — the sufficiency
    contract — but any row list equal to it produces identical bytes, so
    the test suite proves the artifact-alone regeneration equals the
    source-row path byte for byte.

    pp_stage_boundaries: Phase 1 T2 ruling — the converter has no PP
    semantics; refuse instead of handing every rank the unpartitioned
    graph.
```

## `tracks/t3-topology/dse/veritx_dse/workload/lowering.py` :: `lower_to_et_graph`

```text

    The runtime ET entry point: the graph projects to trace rows via
    rows_from_graph (same dialect the converter consumes), then runs
    the shared converter seam. Refusals (BROADCAST/P2P/MULTICAST for
    the ET target, PP boundaries) happen in the projection, before
    the converter is touched.
```

## `tracks/t3-topology/dse/veritx_dse/workload/memory_lowering.py` :: `resolve_memory_graph`

```text

    The ONLY runtime memory entry point going forward: COMPUTE operand
    bytes/locations come from the graph's closed COMPUTE detail, in the
    graph's total order (positional memory stream needs it — an
    unordered DAG refuses rather than invents an order). Comm ops and
    structural markers carry no memory operands and are ignored, exactly
    as in the artifact path. Allocation, access chaining and
    conservation are the shared core below — one implementation.
```

## `tracks/t3-topology/dse/veritx_dse/workload/messages.py` :: `_build_messages`

```text

    ``class_for`` names the traffic class of one operation id: V2 passes
    the uniform artifact class, V3 the lowering sidecar lookup. Message
    order, schedule records and conservation are identical either way —
    only the per-message class stamp differs, and it is identity-bearing
    (``LogicalMessage.canonical`` carries it).
```

## `tracks/t3-topology/dse/veritx_dse/workload/migration.py` :: `_chain`

```text

    Phase-9 operation ORDER was semantic: ET row reconstruction, the
    positional memory stream and timeline v1 all chained operations
    positionally. Migration makes that relation explicit so no lowerer has
    to rely on tuple construction order (which canonical identity
    deliberately ignores).
```

## `tracks/t3-topology/dse/veritx_dse/workload/migration.py` :: `migrate_phase9_document`

```text

    The historical reader already recomputes the legacy hash from content
    and refuses a forged or tampered document, so validation is NOT
    re-implemented here (one implementation per rule). Its historical
    refusal is translated into the migration boundary's typed refusal so
    callers see one vocabulary while the original message is preserved.
```

## `tracks/t3-topology/dse/veritx_dse/workload/migration.py` :: `migrate_waved_document`

```text

    A persisted Wave-D resource does not inline its parents: it carries
    ``parallelism_id``/``semantics_id``, and the historical strict reader
    requires the VERIFIED parent documents. Passing only the workload
    document would silently parse it in authoring shape, which is not the
    persisted shape. Provide the parent documents (or already-verified
    parent objects) explicitly.
```

## `tracks/t3-topology/dse/veritx_dse/workload/migration.py` :: `workload_graph_from_trace_rows`

```text

    Deliberately does NOT route through ``artifact_from_trace_rows`` /
    ``WorkloadArtifact``: that path DROPPED PIM markers (finding F16), so
    reusing it would reproduce the data loss this reader exists to fix.

    Source order is positional, so every operation is explicitly chained.
    PIM markers are CHANNEL SELECTION (see the authority's state machine).
```

## `tracks/t3-topology/dse/veritx_dse/workload/timeline.py` :: `_legs_for_op`

```text

    Fail-closed: a COMPUTE op without compute_cycles raises; a comm op
    with neither service form raises; a cycles-denominated leg without
    its dimension's clock raises; values violating OpService invariants
    raise (checked at construction). Memory legs that were not declared
    are ABSENT legs — recorded as assumptions, never zero-filled.
```

## `tracks/t3-topology/dse/veritx_dse/workload/timeline.py` :: `build_timeline_graph`

```text

    The ONLY runtime timeline entry point going forward. Op order is the
    graph's total order (positional chaining needs it — an unordered DAG
    refuses rather than invents an order). COMPUTE legs are identical;
    comm bytes come from each kind's closed detail (collective payload,
    transfer payload, multicast payload, expert payload or 0, PIM none).
    Composition, stall math and verdicts are the shared core below.
```

## `tracks/t3-topology/dse/veritx_dse/workload/traffic.py` :: `validate_against_bundle`

```text

        The constructor already refused a transposed geometry or a
        foreign mapping/packet-format; this re-runs exactly those seam
        checks (mapping↔fabric hash, packet-format↔attachment hash,
        geometry equality, binding re-derivation) so pre-spawn gates
        written against the historical bundle seam keep proving the
        same facts over the canonical children. Raises MappingInvalid
        on any drift since construction.
```
