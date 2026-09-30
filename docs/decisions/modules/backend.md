# `backend` — extracted module rationale

Extracted from the module docstrings of `veritx_dse/{name}` by the 2026-09-29 debloat. Code keeps a one-line pointer; this is the original long-form text.

## `tracks/t3-topology/dse/veritx_dse/backend/adapter.py`

```text
Backend federation orchestration contracts.

An ORCHESTRATION layer over the existing scientific-identity authorities
(``contracts.BackendConfigArtifact``, ``contracts.BackendInputManifest``,
``producer.ProducerIdentity``, backend-native prepared structures) — not
a second identity system. These objects are in-memory declarations:
no schema_version, no hashing, no serialization; identity lives in the
underlying canonical artifacts.

One seam is deliberately temporary (Federation 05 replaces it):
``context`` is opaque (``object``) until adapters consume the canonical
evaluation context; no compatibility machinery is provided.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra.py`

```text
veritx_dse.backend.astra — canonical ASTRA/Chakra projection + execution.

    LogicalMessageArtifactV2 + ResolvedFabric + Mapping + Attachment
            |
            v
    AstraWorkloadProjection          (this module: canonical projection)
            |
            v
    Chakra ET artifacts              (real protobuf, per rank)
            |
            v
    existing AstraSim_BookSim2 runtime
            |
            v
    AstraExecutionEvidence           (fail-closed execution result)

ABSTRACTION BOUNDARY (deliberate)

ASTRA is itself a system simulator that owns communication-event generation.
This adapter consumes **logical messages**, never ``PhysicalTrafficArtifactV2``:
the BookSim-oriented flit decomposition would double-packetize and duplicate
the transport semantics ASTRA already models. Wire-level data enters only if a
specific runtime genuinely requires it (it does not today).

SINGLE COLLECTIVE AUTHORITY

Slice 29 expanded collectives into canonical logical messages; this module
must not expand them again. Each logical message becomes one
``COMM_SEND_NODE`` / ``COMM_RECV_NODE`` pair (the runtime supports both and
reads ``comm_src``/``comm_dst``/``comm_size`` attributes), so the ring
schedule lives in exactly one place.

UNSUPPORTED vs ZERO

An operation with no canonical network lowering is REFUSED, never silently
reduced to zero traffic. ``audit_operations`` distinguishes
``ZERO_TRAFFIC`` (genuinely no network work) from ``LOWERED`` and from
``UNSUPPORTED``. MULTICAST logical messages are replicated-unicast traffic
and evidence is labelled as such — they are not physical multicast.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_adapter.py`

```text
The ASTRA2 embedded-BookSim backend adapter.

Promotes the EXISTING ASTRA authorities
(``astra.AstraWorkloadProjection``, ``astra_machine.qualify_astra_machine``
over the certified BookSim fabric projection, ``astra_execution.
execute_astra_machine``) into a first-class federation path. The adapter
orchestrates; it never re-derives what those modules already derive.

Backend identity is ``ASTRA2_EMBEDDED_BOOKSIM`` because the embedded
BookSim network backend materially affects the model — "ASTRA" alone
would hide which network simulator produced the number.

Qualified communication path: the runtime qualification proves live
communication through collective-mode (``et_granularity="collectives"``)
and proves the current runtime does not correctly execute the canonical
SEND/RECV message path. The adapter therefore prepares collective-mode
only, and REFUSES workloads whose network-bearing operations would have
to execute through SEND/RECV — never silently dropping them.

Endpoint binding: rank == endpoint is never assumed. The binding comes
from the canonical ``bind_participants()`` authority and feeds
``build_namespace()`` unchanged.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_execution.py`

```text
Slice 33 — authenticated ASTRA + embedded-BookSim execution.

Four execution tiers exist and are NOT interchangeable:

``STANDALONE_BOOKSIM_EXECUTION``
    Slice 32.  BookSim's own ``TrafficManager`` injects a trace.
``EMBEDDED_BOOKSIM_FABRIC_EXECUTION``
    ASTRA drives the fabric; BookSim only transports host-injected packets.
``ASTRA_OWNED_COLLECTIVE_EXECUTION``
    as above, with ASTRA expanding collectives (``astra_comm_coll``).
``CANONICAL_MESSAGE_ASTRA_EXECUTION``
    ASTRA replays Slice-29 SEND/RECV messages (``srota_logical_messages``).

Only the first is BookSim-workload evidence; the first is never ASTRA
evidence, and the last two never claim each other's fidelity.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_machine.py`

```text
Slice 33 — canonical ASTRA machine projection.

The historical authority for an ASTRA run was five hand-authored files
(``system.json``, ``network.json``, ``logical_topology.json``,
``memory.json``, ``mesh4x4.cfg``).  This module replaces that authority:
every deterministic runtime byte is *derived* from canonical artifacts and
content-addressed.

Two things are deliberately kept apart:

``standalone BookSim execution``
    Slice 31/32.  BookSim's own ``TrafficManager`` owns packet injection, so
    the config carries ``traffic = trace(workload.trace)``.

``embedded BookSim fabric execution``
    here.  ASTRA injects every packet through ``EmbedTM::InjectUnicast``, so
    the workload-driving fields must be *disarmed* while every
    machine-semantic field stays byte-identical to the Slice-31 projection.

There is exactly one BookSim machine-semantics authority (Slice 31); this
module only re-derives the workload-driving surface.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_namespace.py`

```text
Slice 34 — canonical participant → ASTRA execution-namespace binding.

The canonical model keeps four namespaces apart::

    workload rank   --MappingArtifact-->      agent
    agent           --AgentAttachmentArtifact--> physical endpoint
    endpoint        -->  BookSim fabric node  ==  ASTRA ``Sys.id``

ASTRA operates in the **endpoint** namespace: ``Workload.cc`` resolves
``<base>.<Sys.id>.et``, ``CommunicatorGroup`` membership is endpoint ids, and
Chakra ``comm_src``/``comm_dst`` are endpoint ids.  Nothing may assume
``rank == endpoint``.

This module translates only that namespace.  It never re-lowers the fabric,
never renumbers canonical endpoints, and never regenerates the message
schedule: the canonical identities stay rank-based.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim.py`

```text
veritx_dse.backend.booksim — canonical standalone BookSim lowering (B3.7b).

One profile, one lowerer, one renderer, one certified execution seam:

    ResolvedFabricBundle
        └─ lower_booksim_standalone()  → BackendConfigArtifact
             └─ render_booksim_standalone() → exact input bytes (path-free)
                  └─ bind_booksim_inputs() → BackendInputManifest
                       └─ materialize_backend() → run-owned backend/ dir
                            └─ run_certified_booksim() → evidence

What makes this different from the legacy ``simulation/booksim.py`` path:

  * lowering starts from validated semantic artifacts and never from a
    legacy ``Topology`` preset;
  * the topology is the ACTUAL materialized router/channel/attachment
    graph, rendered as an AnyNet file and parsed back before spawn;
  * a closed ownership table classifies every rendered parameter;
  * the certified profile REQUIRES a route-realization proof: the BookSim
    fork's ``routing_dump_file`` seam (VeritX B3.7b patch) writes the
    built all-pairs first-hop table, which is compared mechanically
    against the authoritative RouteArtifact. A missing or divergent dump
    refuses the run. Configuration names are never route evidence;
  * the executed input bytes are hash-verified immediately before spawn,
    so a file modified after planning cannot execute.

Route cost is separate from latency: AnyNet's link clause is
``<latency> [cost]``, and Dijkstra minimises COST while the latency stays a
pure wire delay (anynet.cpp). When the cost token is omitted the cost
defaults to the latency (the historic single-number semantics). VeritX
renders an explicit ``cost = 1`` (``ANYNET_ROUTE_COST``), so the executed
routing is exactly hop-count and matches the ANYNET_MIN_HOPS authority
regardless of per-link latency. Certified v1 therefore requires a uniform
route cost of 1 (``route_weight == 1``); heterogeneous LATENCY is allowed
and is carried as each channel's own delay. A non-unit cost is refused
(UNSUPPORTED), never approximated.

Deliberately NOT emitted: BookSim's ``packet_size``. Trace-driven packet
length comes from each trace record (tracetrafficmanager.cpp), so a
config-level packet_size would be a false packetization authority. The
manifest/runner validates every trace packet against
``PacketFormatArtifact.max_packet_flits`` instead.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_adapter.py`

```text
The standalone-BookSim backend adapter.

Federation Commit 05: the BookSim-specific core of the certified
evaluator (canonical traffic artifacts → VC admission → projection →
prepared input → pinned producer → qualified execution), orchestrated
through the federation contracts. Every projection/execution/evidence
authority is REUSED, never copied. Refusal strings are byte-identical
to the pre-adapter evaluator: the characterization suite
(``test_federation_booksim_baseline.py``) freezes them.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_execution.py`

```text
veritx_dse.backend.booksim_execution — execute prepared bytes, once.

    PreparedBookSimInput
            |
            v
    exact materialized bytes (tamper-closed, re-hashed before spawn)
            |
            v
    identified producer (binary SHA-256 + git provenance)
            |
            v
    supervised real execution (one seam, stdin=DEVNULL, timeout)
            |
            v
    fail-closed parser
            |
            v
    ScientificBackendEvidence  +  separate ExecutionAttempt metadata

Execution consumes ONLY the Slice-31 prepared artifact. It never receives
(or derives) topology, CompileRequest, ResolvedFabric, WorkloadGraph,
logical messages, PhysicalTrafficArtifactV2, routing policy or packet
format: all of those already participated in ``prepared_id()``.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_profile.py`

```text
veritx_dse.backend.booksim_profile — closed-world BookSim config audit (B3.7g).

Every configuration field the certified BookSim execution path can read
must appear here exactly once, with:

    * the owner class of its value (ParameterOwner), and
    * the source location(s) that read it, and
    * for BACKEND_PROFILE-owned fields, the explicit pinned value.

The invariant this table exists to enforce:

    No result-affecting value consumed by the certified backend may come
    from an unnamed, unversioned compiled default.

INACTIVE_FOR_PROFILE entries are fields the code reads but which cannot
affect the certified profile's result because a gating field is pinned
(e.g. `speculative=0` gates the spec_* fields; `buffer_policy=private`
makes the shared-buffer knobs dead). Each inactive entry states that
gating argument; it is documented, not hidden.

Source locations were extracted from the vendored fork at
`third_party/booksim2/src` at the B3.7g commit. The audit is intentionally
explicit-data: adding a new read without registering it fails the
closed-world test in `tests/test_backend_contracts.py`.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py`

```text
veritx_dse.backend.booksim_projection — qualified BookSim projection.

    canonical machine artifacts
        (TopologyArtifact, AgentAttachmentArtifact, MappingArtifact,
         VCResourceArtifact, RouteArtifact, PacketFormatArtifact,
         ResolvedFabric)
        +  PhysicalTrafficArtifactV2
                |
                v
    qualified BookSim projection
                |
                v
    PreparedBookSimInput        (deterministic, content-addressed)

BookSim is a BACKEND PROJECTION. It is never a second topology, mapping,
routing, packet-format or VC authority: every value it consumes is either
CANONICAL (taken from a canonical artifact), DERIVED (computed from
canonical artifacts by this projector), or BACKEND_PROFILE (a pinned
simulator control). A canonical dimension BookSim cannot represent is
recorded as UNSUPPORTED and REFUSED — never silently substituted.

Two certified projections (mutually exclusive, chosen by proof):

    CERTIFIED_BOOKSIM_ANYNET_V1        explicit AnyNet graph from the
                                       materialized topology + attachment
    CERTIFIED_BOOKSIM_MESH_DOR_XY_V1   native mesh DOR, ONLY when the
                                       narrow domain below is proven

Native mesh-DOR domain (all must hold, else AnyNet projection or refusal):
  * TopologyArtifact.family == MESH, every router seat_capacity == 1,
    square k x k router grid;
  * attachment is identity-prefix: endpoint ids dense 0..E-1 and
    endpoint i attaches to router i (E <= N);
  * the route artifact realizes DOR_XY and EVERY VC binds DOR_XY;
  * uniform channel latency 1, route_weight 1, no parallel channels;
  * single traffic class over the full VC set, identity transitions.

The historical certified dumps established these facts against the
vendored fork (native mesh node n <-> router n 1:1, x = id % k; links
latency 1 under use_noc_latency=1; the dump hook calls the CONFIGURED
routing function, so the dumped table IS the executed realization).
```

## `tracks/t3-topology/dse/veritx_dse/backend/canonical_serving.py`

```text
Slice 35 — canonical serving network backend adapter.

LLMServingSim owns **service** behaviour: request arrival, routing between
serving instances, scheduler queues, batching, prefill/decode separation,
KV/cache state and per-request metrics.  It owns nothing physical.

All physical network execution crosses the already-qualified canonical
boundary established by Slices 31-34::

    canonical fabric -> PreparedBookSimInput -> AstraMachineProjection
      -> AstraExecutionNamespace -> endpoint-indexed Chakra
      -> communicator groups -> current-source ASTRA + canonical BookSim

This module is the only place the two meet.  It accepts *qualified objects*
and never reconstructs semantics: there is no topology generation, no
BookSim config authoring and no model-preset inspection here, because the
historical ``prepare_booksim_config`` path is explicitly not an authority.

Five namespaces stay distinct and are never assumed equal::

    serving instance  !=  canonical rank  !=  physical endpoint
                      !=  BookSim node    !=  router
```

## `tracks/t3-topology/dse/veritx_dse/backend/contracts.py`

```text
veritx_dse.backend.contracts — backend projection/input identity (B3.7a).

Two identity domains, deliberately separate:

    BackendConfigArtifact
        the PATH-INDEPENDENT backend projection of one semantic fabric:
        backend target/profile, lowerer version, normalized parameters,
        and one SemanticBinding per fabric dimension with its
        representation status and certification effect.

    BackendInputManifest
        the exact per-execution scientific inputs: workload content hash,
        seed/policy, rendered file hashes, normalized invocation. It binds
        to a BackendConfigArtifact but never contaminates fabric identity.

The binary/source-tree identity is NOT part of either hash; B4 composes
producer identity later.

Strictness rules (same discipline as the B3 semantic artifacts):
  * frozen dataclasses, tuple-valued collections;
  * canonical JSON + domain-separated SHA-256;
  * unknown fields, unknown enum values and wrong primitive types refused;
  * hashes recomputed on load; old schemas refused unless an explicit
    migration exists (v1 is the first schema, so nothing to migrate);
  * no absolute filesystem path may enter scientific identity — a
    path-only change must not change any hash;
  * `semantic_loss` is a DERIVED view of the bindings, never an
    independently editable list that could disagree with them.
```

## `tracks/t3-topology/dse/veritx_dse/backend/evidence.py`

```text
veritx_dse.backend.evidence — content-authenticated evidence discipline.

Reclaimed from the historical ``backend/evidence.py`` (p1-product /
p1b / p1x lineage), re-parented onto the current canonical artifacts and
the Slice-31 ``PreparedBookSimInput``.

Two identities, deliberately distinct:

  * ``EvidenceRef``           external identity of the PERSISTED BYTES
                              (path + sha256). A naked path is never
                              reusable.
  * ``ScientificBackendEvidence``  internal identity of what the bytes
                              MEAN: the prepared input, the exact
                              producer, the parser version and the parsed
                              measurements. Execution-attempt metadata
                              (wall time, paths, host) is NOT part of it.

Reuse requires the bytes digest, the prepared input digests, the producer
binary digest and the parser/schema version all to agree.
```

## `tracks/t3-topology/dse/veritx_dse/backend/evidence_cache.py`

```text
Evidence-reuse cache orchestration — explicit hits, typed transplant refusal.

Thin orchestration over backend/evidence.py verify_reusable_record +
read_reusable_record (the safe verification primitives). This module adds
the missing layer only: key→record lookup keyed SOLELY by the scientific
parents required for reuse. No trial/study-id-only keys, no TTL tricks,
no synthetic measurements.

- put(ref, parents): re-passes the full reuse gate, then indexes.
- lookup(key, parents): re-reads via the verified reader, checks every
  bound field, recomputes evidence_id (inside the reader). Unknown key →
  CacheMiss. Known key with divergent bytes/fields → BackendEvidenceError
  (transplant refusal, never a quiet miss). Hit returns stored evidence
  unchanged with CacheHit(reused_evidence_id, hits).
- Clock discipline is strict exact-match; cycles-vs-ns re-derivation
  stays with callers. Question is the EvaluationQuestion name string;
  callers must pass it (never inferred).

In-memory only in this slice (no persisted index/TTL); wiring into the
federated evaluator + Studio run UI (explicit 'cache hit · reused id')
is the parent-owned next step.
```

## `tracks/t3-topology/dse/veritx_dse/backend/meshdor.py`

```text
veritx_dse.backend.meshdor — certified native-mesh DOR_XY lowering (P1B).

CERTIFIED_BOOKSIM_ANYNET_V1 is sealed and untouched; this module is the
parallel certified path for native-mesh DOR_XY fabrics
(CERTIFIED_BOOKSIM_MESH_DOR_XY_V1). It reuses every topology-independent
authority and duplicates only what is genuinely profile-specific:

REUSED (never reimplemented): ResolvedFabricBundle revalidation,
TraceSummary/trace grammar (`_scan_trace`), config value formatting,
seed discipline, BackendConfigArtifact/BackendInputManifest identity,
materialization + pre-spawn hash verification, profile-gate mechanics,
quiescence gates, route-dump FORMAT, stats parsing, producer identity,
CertifiedBookSimEvidence, PreparedBackend/RenderedBackend carriers,
pre-spawn workload gates + trace projection (`assert_projection_ready`,
`render_waved_trace`).

PROFILE-SPECIFIC (new here): the narrow domain checks (square MESH,
seat 1, identity-prefix attachment, DOR_XY-only VCs, unit latency and
weights, no parallel channels), the native-mesh render (`topology=mesh,
k, n`, no AnyNet file), the mesh shape verification (replaces the
AnyNet parse-back), the native-mesh route-dump comparison (covers every
native node, attached or idle), and the canonical-identity asserts.

Narrow certified domain (mirrors meshdor_profile.py): family MESH,
square k x k, seat_capacity 1, identity-prefix attachment (endpoint i
-> router i, E <= N), DOR_XY route class with all VCs bound to it,
uniform channel latency 1, unit route weights, no parallel channels.
CONCENTRATED_MESH, TORUS, RING and non-DOR classes are UNSUPPORTED
(their own proofs, later) — never silently approximated.

Native-mesh facts (read from third_party/booksim2/src, proven by the
qualification tests in tests/test_p1b_meshdor_profile.py): mesh ==
KNCube native (`_nodes == _size`, node n <-> router n, x = id % k),
links latency 1 under the pinned `use_noc_latency=1`, trace-only
addressing with self-loop skip for idle nodes, and the P1B dump hook
(KNCube::DumpDorRoutes) calling the CONFIGURED `dim_order_mesh`
function per (router, node) pair.
```

## `tracks/t3-topology/dse/veritx_dse/backend/meshdor_profile.py`

```text
veritx_dse.backend.meshdor_profile — CERTIFIED_BOOKSIM_MESH_DOR_XY_V1 audit.

The second certified BookSim projection, for native-mesh DOR_XY fabrics.
CERTIFIED_BOOKSIM_ANYNET_V1 is sealed and untouched; this profile has its
own identity, backend semantics version, parameter ownership table and
site-gate table.

Why a separate profile (not a flag): the native mesh path reads a
different config surface than AnyNet (`k`, `n`, `use_noc_latency` become
live; `network_file` goes dead; the `pin:topology=anynet` disabling
argument inverts). Sharing one audit would let one profile's pins vouch
for the other's reads.

Narrow certified domain (deliberate; widened only with new proofs):
  * TopologyArtifact.family == MESH, square k x k, seat_capacity 1;
  * router route materializes DOR_XY; every VC maps to DOR_XY;
  * attachment is identity-prefix (endpoint i -> router i; E <= N);
  * uniform channel latency 1, unit route weights, no parallel channels.

Native-mesh facts the domain rests on (all read from the vendored fork
at third_party/booksim2/src, pinned by tests in
tests/test_p1b_meshdor_profile.py):
  * mesh == KNCube(native): k-ary 2-cube, `_nodes == _size`, node n <->
    router n 1:1, coordinates x = id % k (x fastest) — the same row-major
    numbering the Srota mesh materializes, and the same decomposition
    `dor_next_mesh` routes on;
  * native links are latency 1 under `use_noc_latency=1` (pinned; the =0
    branch also yields 1 for mesh, but no compiled default is consumed);
  * trace-only addressing: the trace event list drives injection and
    BookSim skips self-loop injections for non-participating nodes, so
    native nodes beyond the attached endpoint prefix inject nothing;
  * the P1B mesh dump hook (KNCube::DumpDorRoutes) calls the CONFIGURED
    routing function (same `routing_function + "_" + topology` key rule
    both consumers use) with a probe flit per (router, node) pair, so the
    dumped first-hop table IS the executed realization, not a second
    Python DOR implementation.

Config selector pinned by construction-rule evidence (not function names):
`routing_function=dim_order` + `topology=mesh` -> key `dim_order_mesh` ->
`&dim_order_mesh`. (`dor` would resolve to the same pointer; `dim_order`
is pinned because key, function and class name coincide.)
```

## `tracks/t3-topology/dse/veritx_dse/backend/normalized_evidence.py`

```text
The normalized evidence envelope — one shape, native authority.

The federation's common result carrier: every adapter normalizes its
backend-native evidence (ScientificBackendEvidence, AstraRuntimeEvidence,
serving/Ramulator evidence) into THIS envelope so planners, optimizers
and Studio read one shape. The native evidence stays authoritative and
is pointed at by ``native_evidence_id`` — the envelope is never a
conversion of, or replacement for, a foreign backend's evidence schema
(different backends express genuinely different things; flattening them
would be a semantic lie).

Like the other orchestration contracts this is in-memory: no
schema_version, no serialization. Content identity lives in the native
evidence and the canonical parents it names.
```

## `tracks/t3-topology/dse/veritx_dse/backend/producer.py`

```text
veritx_dse.backend.producer — identify exactly what executed.

Reclaimed from the historical ``backend/producer.py``. The binary digest is
the primary statement of what executed; a Git revision alone is NOT proof
of binary provenance. A dirty or unpinned producer may be executed for
diagnosis, but must never silently receive reusable evidence status.
```

## `tracks/t3-topology/dse/veritx_dse/backend/projection.py`

```text
veritx_dse.backend.projection — derived-traffic backend input.

(Formerly veritx_dse.waved.backend; slice 2b moved it here by ownership.)

Wave D contributes TRAFFIC semantics; Wave B/C remain the execution and
evidence authorities. This module renders the canonical Wave-D physical
traffic into the qualified standalone-BookSim workload input and hands
it to the sealed Wave-B chain:

    render_waved_trace(pt)  → trace bytes (lossless, see below)
    prepare_waved_booksim(pt) → PreparedBackend (Wave-B prepare path)
    run_waved_booksim(...)    → evidence + Wave-D conservation summary

The rendered trace is a DERIVED, lossy-for-provenance backend input: the
5-column BookSim trace grammar (timestamp, src, dst, type,
packet_size_flits) cannot carry operation ids or phase. Losslessness is
therefore claimed ONLY for the fields the grammar can carry — source
endpoint, destination endpoint, packet/flit counts, packet ordering —
and is proven mechanically by ``verify_trace_projection``. The persisted
higher-level artifact (``PhysicalTrafficArtifact``) retains full
provenance; the trace is never promoted to semantic authority (§21).

Injection order: packets are emitted in (message seq, packet index)
order — deterministic from the artifact, no wall-clock input.

Quiescence counters (§21): the qualified fork exposes ``delivered``
packets and ``flits_injected``/``flits_accepted`` flit totals at trace
drain — all sealed Wave-B evidence fields. Wave D therefore proves
``delivered_packets == expected_packets`` and
``flits_injected == flits_accepted == expected_flits`` and never needs a
backend-injected packet counter (the sealed Wave-B evidence schema is
not modified by Wave D). Counters the backend does not print are
recorded as ``None``, never fabricated as zero.
```

## `tracks/t3-topology/dse/veritx_dse/backend/qualification.py`

```text
veritx_dse.backend.qualification — cross-backend semantic qualification
(B3.8b, hardened in B3.8e).

Two DIFFERENT claims are computed and never conflated:

    AUTHORITY AGREEMENT
        Two targets claim EXACT/DERIVED_EXACT for a dimension and bind
        the SAME authoritative source identity, the same representation
        status and the same supported domain. This proves they consulted
        one authority; it does NOT by itself prove their encodings agree.

    PROJECTION EQUIVALENCE
        For targets that share one canonical lowerer
        (BOOKSIM_STANDALONE vs SERVING_BOOKSIM2), the fabric-derived
        backend parameters must be byte-equal after projecting out
        target-specific execution fields. This is the stronger claim and
        is checked mechanically.

The module deliberately does NOT compare raw backend config hashes across
targets (they should differ) and does NOT impose latency equality across
heterogeneous backend families.
```

## `tracks/t3-topology/dse/veritx_dse/backend/ramulator_adapter.py`

```text
The certified Ramulator2 HBM3 backend adapter.

Promotes the EXISTING memory authorities into a first-class federation
path:

    workload graph --resolve_memory_graph--> MemoryArtifact
        --lower_to_ramulator_trace--> ReadWriteTrace
        --simulation.ramulator.execute--> MemoryEvidence

The adapter orchestrates; it never re-derives what those modules already
derive and never invents memory demand: a workload with no resolvable
memory operands is UNSUPPORTED/BLOCKED, never zero memory cost.

Backend identity is ``RAMULATOR2_HBM3_V1`` because the audited HBM3
single-channel profile materially affects the model — bare "RAMULATOR"
would hide which memory standard produced the number. The fixed profile
is a MODEL ASSUMPTION, not a user-authored design: capability
limitations and normalized evidence state it explicitly.

Model fidelity is MEMORY_CYCLE_SIMULATION, never FULL_SYSTEM_SIMULATION:
this is standalone DRAM-timing trace execution over a recorded request
stream, not a composed system.

Native preparation holds the resolved MemoryArtifact, the certified
geometry, the memory-profile identity and the mapping policy. No run
paths, PIDs, timestamps or host names ever enter scientific identity.
```

## `tracks/t3-topology/dse/veritx_dse/backend/registry.py`

```text
The explicit backend registry.

Registration means only: VERITX knows an adapter implementation.
Availability and readiness are determined by assessment at plan/evaluate
time — never by installation. No plugin framework, no discovery: the
default registry is a literal tuple of adapters.
```

## `tracks/t3-topology/dse/veritx_dse/backend/reproduce.py`

```text
veritx_dse.backend.reproduce — re-execute and compare a BookSim bundle.

``reproduce`` does NOT trust the stored numbers: it verifies the bundle,
digest-admits the evidence document (a copied or diagnostic bundle
refuses before anything runs), pins the reproduction binary and inputs
to the exact identities the evidence names, re-runs the recorded backend
on the verified inputs in a fresh directory, and compares the
deterministic science (parsed statistics and the executed route-dump
digest). A divergence refuses.
```

## `tracks/t3-topology/dse/veritx_dse/backend/reproduce_astra.py`

```text
veritx_dse.backend.reproduce_astra — re-execute and compare an ASTRA run.

``reproduce`` does NOT trust the stored numbers and does NOT re-derive
the inputs: it rebuilds the exact stored machine/projection/namespace
from the archived JSONs (refusing on any identity mismatch), re-runs
the recorded runtime on the stored staged workload in a fresh
directory, and compares the deterministic science (native evidence
identity + per-rank cycles). A divergence refuses.
```

## `tracks/t3-topology/dse/veritx_dse/backend/reproduce_ramulator.py`

```text
veritx_dse.backend.reproduce_ramulator — re-execute and compare a run.

``reproduce`` does NOT trust the stored numbers and does NOT re-derive
the inputs: it rebuilds the exact stored memory artifact and manifest
from the archived JSONs (refusing on any identity mismatch), re-runs
the stored trace through the backend in a fresh directory, and compares
the deterministic science (native evidence identity + status). A
divergence refuses.

Wall time is excluded from the comparison by construction: the native
evidence identity (``ramulator_evidence_id``) never covers it, so two
executions of the same science agree even though the host clock moved.
```

## `tracks/t3-topology/dse/veritx_dse/backend/route_observation.py`

```text
veritx_dse.backend.route_observation — executed route realization (P0.10).

The canonical route is proven STATICALLY (RouteArtifact + ResolvedRoute).
This module proves the runtime routing realization: the vendored fork's
``routing_dump_file`` writes the routing function/table actually built at
network construction, and we compare it destination-by-destination against
the canonical route.

Precise claim:

    The runtime routing-function/table first-hop realization is exactly
    equivalent to the canonical route over the complete source x
    destination domain.

This is stronger than static configuration checking but narrower than
per-packet instrumentation: for mesh-DOR the dump calls the active
registered routing function for every router/destination pair after
network construction; for AnyNet it dumps the routing table AnyNet itself
uses. It does not record head flits as packets traverse the router, so it
proves deterministic first-hop routing equivalence, not observed packet
paths.

Id mapping (why this is exact, not assumed):
  * mesh-DOR: the profile qualification proves endpoint ids are dense
    0..E-1 and endpoint i attaches to router i, and the native mesh node n
    maps 1:1 to router n — so the dump's ``src_router``/``dst_node`` ARE
    the canonical router/endpoint ids;
  * AnyNet: ``render_anynet_topology`` emits ``router <id>`` / ``node <id>``
    with the canonical ids verbatim, so the same identity holds.

OWNERSHIP (Tranche 5 PHASE 2). This module is a SIMULATOR ADAPTER: it owns
(a) parsing the fork's dump format and (b) building the expected table from
the sealed canonical artifacts plus the execution node->router map. It does
NOT own route-set comparison semantics — ``core.route_artifact.
compare_first_hop_tables`` does, and this module delegates to it. Two
independent comparisons of the same science is exactly the drift this
reclamation exists to remove.
```

## `tracks/t3-topology/dse/veritx_dse/backend/serving_adapter.py`

```text
The canonical serving federation adapter.

Promotes the EXISTING serving authorities into a first-class federation
path:

    CanonicalEvaluationContext (+ bound serving experiment)
        --prepare--> ServingPreparation (spec + design doc, no execution)
        --execute--> run_canonical_serve (live, real binaries)
        --normalize--> per-question TTFT / completion envelopes

The adapter orchestrates; it never re-implements serving semantics, the
scheduler, or the network execution — those stay in
``simulation.serve_canonical`` / ``simulation.serving_loop`` /
``backend.canonical_serving``. Normalization is the shared projection in
``backend.serving_normalization`` (per-request metrics only, absent
never zero-filled, TPOT never invented).

Backend identity is ``CANONICAL_SERVING`` — the same authority string
the normalized envelopes already carry (see
``serving_normalization.SERVING_BACKEND_ID``), so planner rows,
envelopes and evidence agree on one spelling.

The experiment binding law: serving needs caller-bound inputs (cluster
service semantics, request trace, request count, service-profile
overrides) that ``CanonicalEvaluationContext`` deliberately does not
carry. The adapter is therefore constructed WITH its experiment; an
unbound adapter assesses SERVING_* as BLOCKED (representable, awaiting
inputs), never READY. ``evaluate_federated`` registers the adapter only
when serving options are supplied, so unrequested serving questions
stay honest UNSUPPORTED rows instead of fake coverage.

Model fidelity is FULL_SYSTEM_SIMULATION: a serving run genuinely
composes serving, scheduler and live network execution — never an
isolated network number relabeled.
```

## `tracks/t3-topology/dse/veritx_dse/backend/serving_normalization.py`

```text
Normalized serving evidence — a view over CanonicalServingEvidence.

Serving goes through the planner path via the registered serving
adapter (``backend.serving_adapter.ServingAdapter``): serving needs
extra semantic inputs — cluster config, request trace,
CertifiedServiceProfile, instance geometry — that
CanonicalEvaluationContext does not carry, so those inputs are
caller-bound on the adapter and the bound experiment is what the
planner adjudicates. This module projects the authoritative
``CanonicalServingEvidence`` into the common normalized envelope
instead, and the adapter consumes exactly this projection (no second
normalization).

Gates, in order: the evidence must be live
(``assert_live`` — replay-only protocol output never normalizes) and
every instance must have completed work
(``assert_all_instances_served`` — a total request count is not
sufficient evidence). Model fidelity is FULL_SYSTEM_SIMULATION: a
serving run genuinely composes serving, scheduler and the live network.

SERVING_TTFT projects ``RequestMetric.ttft_cycles`` per request;
SERVING_COMPLETION projects ``RequestMetric.completion_cycles`` per
request. Metric identity is ``(key, (("request_id", ...),))`` — never
invented key suffixes. A request with no metric for a question is
absent from that envelope, never zero-filled. TPOT is deliberately
absent: native evidence does not prove it.
```

## `tracks/t3-topology/dse/veritx_dse/backend/serving_round.py`

```text
Slice 36 — certified per-round serving qualification and round evidence.

The service loop decides *what* a round means (a real ``Batch`` of real
``Request`` objects).  This module turns that into a qualified canonical
round and authenticates what the runtime actually did.

Two separations matter here:

``stable machine  vs  round workload``
    ``AstraMachineProjection.machine_id`` folds in the projection that
    qualified it, which is correct for one-shot qualification and wrong for a
    live loop where every round has a different batch.  ``physical_id()`` is
    the stable, workload-independent machine identity; each round binds its
    own workload identity *plus* the machine and namespace identities, so the
    three are always authenticated together and a round can never be
    transplanted onto a machine qualified for something else.

``serving intent  vs  physical lowering``
    A ``ServingBatchPlan`` carries serving semantics only (which requests, how
    many tokens, which collective intent, which canonical participant ranks).
    Physical endpoints, ET filenames, communicator groups and BookSim config
    stay canonical (Slices 31-34).  Collectives are lowered as *intent*; the
    certified tier never expands a ring here, because
    ``expansion_authority = ASTRA``.
```

## `tracks/t3-topology/dse/veritx_dse/backend/source_audit.py`

```text
veritx_dse.backend.source_audit — vendored-BookSim config read audit.

BookSim's certified projection claims that specific configuration fields
affect execution. This module proves it against the ACTUAL vendored
source instead of trusting a hand-written table:

    scan_config_reads(source_root)  -> every field the fork reads
    audit_profile_reads(profile, source_root) -> drift report / refusal

The read pattern is the fork's accessor convention
(``cfg->GetInt("k")`` / ``.GetStr("topology")`` / ``GetFloat(...)``),
revalidated here against ``third_party/booksim2/src``. Stale
line-number tables are deliberately NOT copied: a field is revalidated by
name against the current tree, so a fork upgrade that drops a read fails
closed rather than silently passing.
```


# `backend` — extracted inline comments

## `tracks/t3-topology/dse/veritx_dse/backend/astra.py`

line 31:

```text
#: logical artifact variants this projection accepts. V2 stamps one
#: uniform class; V3 stamps each message with its operation's lowered
#: class. The variant is identity-bearing: a V3 projection id can never
#: collide with a V2 id over the same graph.
```

line 42:

```text
#: Chakra comm-attribute scalar ABI.
#: The vendored feeder (extern/graph_frontend/chakra/src/feeder/et_feeder_node.cpp)
#: reads comm_src/comm_dst from int32_val and comm_size from int64_val, while
#: the previously qualified historical fixture stores them in uint32/uint64_val
#: and is consumed successfully by the archived runtime. The ABI is therefore an
#: EXPLICIT, identity-bound lowering parameter, never an assumption.
```

line 54:

```text
#: Chakra ET granularity. WHICH AUTHORITY EXPANDS THE COLLECTIVE is recorded
#: in the projection identity, never left implicit:
#:   "messages"    - one COMM_SEND/COMM_RECV pair per canonical logical
#:                   message; the Slice-29 schedule owns expansion.
#:   "collectives" - one COMM_COLL_NODE per collective OPERATION, which
#:                   DELEGATES expansion to ASTRA. Only for runtimes that do
#:                   not simulate the send/recv path; evidence is labelled.
```

line 94:

```text
#: Canonical collective-kind to embedded class id. Mirrors
#: ``VeritXClassId`` in the vendored frontend
#: (``astra-sim/.../system/Common.hh``); the two tables must agree or
#: attribution lies. Kinds without an id are unattributable: the
#: runtime injects them as class 0, which no qualification may accept.
```

line 235:

```text
    #: (operation_id, owner) parallel to ``compute_operations``; ``owner=None``
    #: keeps the historical global-compute semantics (the node appears in
    #: every rank's ET), ``owner=rank`` emits it only into that rank's ET.
    #: Kept separate from ``compute_operations`` so existing global-compute
    #: projections keep their identity byte for byte.
```

line 246:

```text
    #: which canonical logical artifact variant was projected (V2 uniform
    #: class, V3 per-operation classes). Identity-bearing: class semantics
    #: are part of the projection id, never ambient.
```

line 340:

```text
            # Per-operation conservation is the class-faithfulness
            # proof: every network-bearing collective's messages must
            # account for its declared payload exactly.
```

line 359:

```text
        # Ownership is a projection fact, not a second participant model:
        # it reuses the canonical OperationNode.owner the graph already
        # validates against the participant namespace.
```

line 366:

```text
        # The DECLARED per-operation collective payload is design intent; it
        # is what a delegating ET must carry. Ring chunk sizes are schedule
        # detail and must never be mistaken for the collective's payload.
```

line 516:

```text
            # V2 identity is frozen byte-for-byte (existing fixtures
            # and golden ids keep verifying); the class-bearing fields
            # enter the identity only for V3, where they are the point.
```

line 559:

```text
        # Archived field form nests messages as {"sequence": ...} maps
        # already; the identity form uses to_dict payloads with one
        # derived extra ("bytes_presented_to_astra"), ignored below.
```

line 587:

```text
        # The identity dict names this "compute_ownership" and omits it
        # when no compute is rank-owned; the archived field form names it
        # "compute_owners". Absence means "all global".
```

line 679:

```text
            # Boundary: this block holds ONLY the optional third-party
            # Chakra imports, so any failure means the runtime is unusable
            # (UNAVAILABLE verdict). No first-party logic lives here that
            # could mask our own bugs.
```

line 733:

```text
                    # Sidecar class attribute: the runtime schedules the
                    # collective; the canonical class travels WITH the
                    # node so attribution never depends on heuristics.
                    # A COLL node without a bound class is a collapsed
                    # binding and must not execute.
```

line 775:

```text
                    # Message-mode nodes carry the class sidecar too;
                    # message-mode never normalizes, so this is
                    # attribution only, never an execution claim.
```

line 788:

```text
                # An EMPTY ET is not a valid workload: the runtime's
                # dependency solver refuses a layer with no dependency-free
                # node.  A MISSING rank file is how the runtime expresses an
                # idle NPU (Workload.cc + the interactive loader), so an
                # idle rank is expressed by writing nothing at all.
```

line 1029:

```text
    # Fail closed on SILENT NON-SIMULATION: a build that ignores the
    # send/recv path still exits 0 with all ranks reported, but the total
    # never rises above the declared compute floor. Communication was
    # projected, so "no communication time" is a refusal, not a result.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_adapter.py`

line 31:

```text
#: Normalized metric rows per question, mirroring ``normalize()`` below:
#: (metric key, unit, scalar_bindable). PER_RANK rows carry rank
#: dimensions, so a scalar optimization objective cannot bind them —
#: ``scalar_bindable`` is False there (no invented key suffixes).
#: Single source for the federation capability catalog; edit here when
#: ``normalize()`` gains a metric, never in a second matrix.
```

line 334:

```text
        # V3 multi-class lowering: every operation keeps its lowered
        # class; the projection (not a flattening) carries them.
        # A caller-supplied traffic_class cannot subset a multi-class
        # intent at eval time — that would silently drop classes.
```

line 359:

```text
        # The qualified communication envelope: every network-bearing
        # operation must be representable through the collective-mode
        # path. P2P / multicast / message-mode operations refuse — never
        # silently dropped, never executed unqualified. The check loops
        # per operation, so multi-class membership never affects it.
```

line 377:

```text
            # Single-class: the unified class selects the BookSim leg.
            # Multi-class (V3): no class filter — the canonical V3 path
            # admits every class against its VC set (a filter here would
            # silently drop classes from the embedded network).
```

line 399:

```text
        # the machine qualification consumes the SAME canonical parents
        # the BookSim fabric projection consumed (packet_format, mapping,
        # attachment) — the machine is derived from the certified fabric
```

line 422:

```text
        # Canonical rank→endpoint binding: the ONLY authority is
        # bind_participants() over the compiled mapping/attachment.
        # rank == endpoint is never assumed.
```

line 471:

```text
            # Static-MoE expert dispatch/combine (EXPERT_BEGIN/END with a
            # declared collective such as ALLTOALL) executes through the
            # same collective-mode path as an ordinary collective: the
            # operation keeps its identity (operation_id) and its class
            # rides the COLL-node sidecar + class binding, never inferred.
            # A bare EXPERT region (no declared collective) is
            # ZERO_TRAFFIC upstream and never reaches here.
```

line 524:

```text
        # Bind the pinned producer to this execution: resolved here for
        # the record (preparation stays binary-independent until now);
        # the spawn itself re-resolves and asserts the pin inside
        # execute_astra_machine. A pin failure refuses execution — an
        # unqualified producer never spawns for reusable evidence.
```

line 632:

```text
        # Autonomous injection == 0 when the counter is available; an
        # absent counter stays absent (never zero-filled), but any
        # non-zero count refuses — the fabric generated traffic the
        # workload did not ask for.
```

line 642:

```text
        # Producer binding: the spawn gate stamps full producer facts
        # into evidence. Normalization verifies they are pin-quality — a
        # manifest-bound recipe, a clean revision, a manifest digest —
        # reusing the existing producer authority's vocabulary. Evidence
        # that did not come through the pinned spawn gate never
        # normalizes, even with matching machine/projection ids.
```

line 678:

```text
        # Class binding: a multi-class projection without a matching
        # binding id is unattributable (swapped, collapsed or omitted
        # classes would normalize silently). Single-class evidence needs
        # no attribution binding — there is nothing to swap.
```

line 699:

```text
        # Per-class conservation, when a producer reports per-class
        # counts: every injected class unit must complete. Absent counts
        # stay absent (never zero-filled); present-but-unbalanced counts
        # refuse.
```

line 782:

```text
#: prepare() failures that are SEMANTIC (UNSUPPORTED/BLOCKED), never
#: runtime. Programming errors (TypeError, AttributeError,
#: AssertionError, KeyError) are deliberately absent: they escape.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_execution.py`

line 35:

```text
#: Build recipe the qualified ASTRA producer must be built from. Pinned
#: at resolve time (spawn gate) and stamped into evidence so
#: normalization can verify it. Mirrors the BookSim producer pattern;
#: a single authority, never re-derived per call site.
```

line 66:

```text
#: contract ledger stream lines (stderr, VERITX_LEDGER>=1):
#: ``[LEDGER][STREAM] rank=<r> stream_id=<s> comm_type=<t> ...`` where
#: <t> is the ASTRA ComType int (None=0, Reduce_Scatter=1, All_Gather=2,
#: All_Reduce=3, All_to_All=4, All_Reduce_All_to_All=5).
```

line 73:

```text
#: vendored ComType int -> VeritX canonical class id. Mirrors
#: ``veritx_class_of_comtype`` in third_party/.../system/Common.hh
#: (0/5 map to 0 = unattributable; v1 ABI cannot attribute them).
```

line 147:

```text
    #: Deterministic operation->class binding the executed projection
    #: declared (None = legacy single-class evidence, which needs no
    #: attribution binding). Multi-class evidence without a binding is
    #: unattributable and never normalizes.
```

line 155:

```text
    #: Producer facts stamped at execution from the pinned identity.
    #: A pinned execution always records them; their absence means the
    #: evidence did not come through the spawn gate.
```

line 160:

```text
    #: Per-class injection/completion counts. Empty until the embedded
    #: backend exposes them reliably — never synthesized, never zero-
    #: filled: absence is absence.
```

line 484:

```text
    # ``main.cc`` prints ONE global ``wall_time`` in BOTH fields of its
    # ``[workload] sys[i] finished, <w> cycles, exposed communication <w>``
    # line for every Sys -- including idle ones.  That line therefore carries
    # no per-endpoint information and must never be read as exposure.  It is
    # used only to enumerate the endpoint namespace and detect duplicates.
```

line 498:

```text
    # Per-endpoint numbers come ONLY from the statistics logger, which emits
    # an entry per *executing* endpoint.  An idle endpoint has no entry, so
    # its absence is the idle signal -- not a zero written by us.
```

line 611:

```text
    # Slice-33 correction: the runtime namespace is the fabric ENDPOINT
    # count (Workload.cc resolves <base>.<Sys.id>.et and main.cc builds one
    # Sys per fabric.node_count()), never the router count.
```

line 619:

```text
    # Participation is proven ONLY by the statistics logger's per-endpoint
    # entry.  The global [workload] line enumerates every Sys (idle included),
    # so it can never establish that an endpoint executed work.
```

line 748:

```text
        # The real spawn gate: only a pinned producer may execute for
        # reusable evidence. The injected-runner path is an explicit test
        # fixture transport whose evidence never normalizes (normalize
        # requires SUPERVISED), so it records facts without the gate.
```

line 786:

```text
                # Contract-ledger floor: VERITX_LEDGER=1 buys the
                # [LEDGER][STREAM] schedule attribution (one line per
                # stream) the class-coverage check reads. Logging only;
                # a preset higher level is respected, never lowered.
```

line 837:

```text
    # §11/§6: the canonical-message path is a KNOWN runtime capability gap.
    # A run in which the runtime produces no per-endpoint statistic at all
    # (not even a wall time) never executed the SEND/RECV workload, so it is
    # recorded as such -- explicitly, with zeroed results and no fabricated
    # participation -- instead of being reported as a measurement.
    # No per-endpoint statistic of any kind means the frontend never entered
    # the workload path for any endpoint (an idle Sys logs nothing at all).
```

line 867:

```text
    # rank-mapped view: canonical ranks over the executed endpoint results
    # a rank with no runtime statistic maps to 0; the absence is carried by
    # ``participant_statistics_present`` rather than by a fabricated number
```

line 880:

```text
        # The canonical-message path is preserved but NOT claimed as
        # executed: a runtime that reports zero communication did not
        # simulate SEND/RECV.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_machine.py`

line 24:

```text
#: Class-attribution injection ABI proven by the embedded runtime.
#: 1 = class-aware injection (vendored kBooksim2AbiVersion=1): every
#: collective algorithm stamps request->veritx_class_id from its ComType
#: (Ring/HalvingDoubling/DoubleBinaryTree/CustomAlgorithm), Sys.cc
#: backstops NATIVE/rendezvous distinctly and never guesses a kind,
#: sim_send threads class_id into InjectUnicast, retire aborts on
#: arrival/pending class mismatch, and [LEDGER][SEND]/[ABI] log the
#: attribution. A multi-class machine qualifies only at class ABI >= 1;
#: against a class-blind runtime (ABI 0) the classes would contend
#: unattributed. Bump if and only if the vendored runtime extends the
#: attribution contract again and re-qualifies.
```

line 48:

```text
#: The network-configuration ABI the *currently vendored* frontend source
#: accepts.  ``CreateEmbeddedTM`` feeds the argument straight to
#: ``ParseArgs`` -> ``BookSimConfig``'s yacc grammar, so it must be a real
#: BookSim ``.cfg``.  The historical ``network.json`` wrapper was a property
#: of the *archived binary* (its ``veritx_embed.cpp`` carried an
#: ``nlohmann::json`` unwrap of ``booksim-config-file``); the vendored source
#: has no such unwrap, so JSON is NOT part of this ABI.
```

line 63:

```text
#: The disarmed values.  ``uniform`` is a pattern with no injection mechanism
#: of its own (``TraceTrafficPattern`` is the only one that has one), and
#: ``bernoulli`` at rate 0 makes ``BernoulliInjectionProcess::test`` return
#: ``RandomFloat() < 0.0`` — false for every draw in [0,1).
```

line 71:

```text
#: Keys whose VALUE IS MACHINE SEMANTICS.  The embedded projection must carry
#: them byte-identically from the Slice-31 config; a mismatch is a refusal,
#: never a silent re-derivation.
```

line 163:

```text
#: Fields this projector renders.  Everything else in SYSTEM_FIELDS is
#: either UNSUPPORTED (refused if the workload needs it) or has an ASTRA
#: default we deliberately do not override.
```

line 194:

```text
#: Memory: canonical memory semantics are NOT reclaimed (later slice).  The
#: analytical remote-memory backend still requires a file, so we emit the
#: smallest explicit runtime-required profile and *prove* it is inert.
```

line 213:

```text
#: 1 fabric cycle == 1 ns.  The canonical workload's compute durations are
#: cycles-at-1ns (`declared_compute_cycles` divides ns by 1000), so this
#: keeps ASTRA's ns domain and the fabric's cycle domain aligned.
```

line 517:

```text
    #: Proven class-attribution injection ABI of the embedded runtime
    #: (0 = pre-extension). Identity-bearing: a machine qualified
    #: against a class-aware runtime never shares identity with one
    #: qualified against a class-blind runtime.
```

line 820:

```text
    # Class-attribution gate: a multi-class workload executes more than
    # one traffic class through the same embedded network. The runtime
    # proves class-aware injection only at class ABI >= 1; against a
    # class-blind runtime (ABI 0) the classes would contend unattributed
    # — a silent flattening. Refuse qualification, never widen the
    # meaning of the existing ABI.
```

line 883:

```text
    # Slice-33 correction: the ASTRA node namespace is the fabric ENDPOINT
    # (node) count -- ``fabric.node_count() -> NumNodes()`` -- never the
    # router count.  AnyNet legitimately has routers != nodes.
```

line 988:

```text
        # AnyNet render grammar (Slice 31): per line
        #   router <r> node <n> ... router <dst> <latency>
        # "--nodes" are the BookSim endpoints; "--routers" are not nodes.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_namespace.py`

line 244:

```text
    #: ASTRA's ``Sys.id`` namespace ``[0, endpoint_count)`` == the BookSim
    #: NODE count (``_tm->NumNodes()``), not the attached-endpoint count and
    #: not "routers" in the AnyNet sense
```

line 477:

```text
    # Two shapes: the to_dict projection ("communicator_groups" maps
    # group id to membership) and the archived field form ("groups" is
    # the CommunicatorGroups field dict with a "memberships" list).
```

line 576:

```text
        # Boundary: this block holds ONLY the optional third-party Chakra
        # imports, so any failure means the staging runtime is unusable.
        # No first-party logic lives here that could mask our own bugs.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim.py`

line 53:

```text
# Execution-transport identity. Only SUPERVISED_PROCESS evidence is
# reusable/certifiable; TEST_INJECTED products are unit-test fixtures
# that can never enter the reuse API (enforced in producer's binding
# check, not by caller discipline).
```

line 68:

```text
# Authoritative profile/version identity per BookSim target. A forged
# artifact can recompute its own hash; it cannot change what its target's
# certified lowering must be.
```

line 93:

```text
# ── closed parameter ownership (B3.7g) ──────────────────────────────────
# One source of truth: backend/booksim_profile.py audits every config
# field the active certified path reads, with owner class and source
# location. The lowerer and renderer emit active audited fields only;
# BACKEND_PROFILE fields carry explicit pinned values from the profile,
# so no result-affecting value comes from a compiled BookSim default.
```

line 306:

```text
    # VC-range globals are derived exactly as InitializeRoutingMap computes
    # them from num_vcs (they are not consulted for ANY_TYPE trace flits,
    # but they are emitted explicitly instead of inherited).
```

line 1442:

```text
    # Whole-chain proof: canonical config -> exact rendered bytes ->
    # exact canonical input manifest. Refuses before any filesystem
    # materialization or process spawn.
```

line 1449:

```text
    # B-FINAL: identify the exact producer BEFORE spawn (and before any
    # filesystem materialization) and bind it into the evidence. An
    # unreadable binary refuses here — certified evidence never carries
    # an unknown producer digest.
```

line 1465:

```text
    # B-FINAL.2: the executed-route output must be fresh output of THIS
    # attempt. A pre-existing routing.dump (e.g. from an earlier attempt
    # sharing the directory) is stale/ambiguous: it is refused, never
    # silently accepted as current evidence and never silently deleted.
    # Certified re-execution belongs in a new attempt directory.
```

line 1479:

```text
    # B-FINAL.1: close the hash-to-exec window. The producer was
    # identified before materialization for early refusal; rehash the
    # exact bytes about to spawn and require the identical producer. A
    # binary replaced in between invalidates the planned execution — it
    # must be restarted, never silently adopted.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_adapter.py`

line 180:

```text
            # assessment mirrors preparation: the certified profile must
            # represent this exact fabric, or SUPPORTED here would lie
            # about what prepare() will refuse.
```

line 194:

```text
        # ── runtime readiness: the producer that would execute ───────
        # A READY assessment proves a usable, qualified producer exists.
        # Projection success alone is semantics, never readiness.
```

line 419:

```text
        # gate ORDER is the pre-adapter law: construct artifacts (ids
        # exist), admit classes, THEN assert the intent class — so a
        # refused outcome always binds the traffic identities it refused.
```

line 519:

```text
        # The certified path never accepts an unpinned producer: a binary
        # whose build manifest does not verify against the canonical
        # recipe cannot produce certified evidence.
```

line 648:

```text
    # Digest-admitted read + canonical validation + certified admission +
    # preparation binding (the read_reusable_record discipline for
    # callers that hold a path rather than a ref): a copied evidence
    # file from another run refuses here instead of normalizing under
    # this outcome's identities. (The FabricEvaluator already
    # reload-verified these bytes; this re-proves rather than trusts.)
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_execution.py`

line 51:

```text
#: the physically meaningful completion: cycle of the last ejected flit.
#: The fork emits this exactly once per sim (trafficmanager.cpp:1926) and
#: it is invariant under the sampling window (F-0001).
```

line 62:

```text
#: booksim2-fork/v2 per-class counters (booksim_execution law: each trace
#: class must conserve independently — a total-only check cannot see a
#: collapsed or swapped class)
```

line 105:

```text
    # refuse to let a stale directory contribute anything. ``checksums.json``
    # is tolerated because a finalized run bundle carries it; it is
    # re-derived on finalize, never consumed as input.
```

line 351:

```text
        # booksim2-fork/v2 per-class law: every executed class must
        # conserve its own flits. A missing counter for a declared class
        # means the class never executed — refused, never assumed.
```

line 400:

```text
    # No unregistered profile executes: the prepared profile id must
    # resolve to a registered execution implementation. Selecting or
    # preparing a profile never implies executability.
```

line 412:

```text
    # Trace/profile class-domain agreement: a prepared input whose trace
    # class indices do not match its profile's domain is forged or
    # transplanted. Single-class profiles execute exactly class 0; the
    # multi-class profile executes exactly the dense indices of its bound
    # class map. This holds on every transport, including injected
    # diagnostic runners.
```

line 475:

```text
    # 1. the prepared object must be self-consistent AND, when the caller
    #    holds the external identity, must match it (catches an object
    #    mutated after preparation, which self-consistency cannot see).
```

line 541:

```text
    # ── executed route realization (P0.10) ─────────────────────────────
    # A supervised certified run must emit the fork's first-hop dump and
    # realize exactly the canonical route. The dump is compared against the
    # expectation bound into the prepared input, so no second authority is
    # consulted at execution time.
```

line 604:

```text
        # Durable run bundle (C3): publish a checksum manifest over the
        # complete run (inputs, route dump, evidence) so it can be verified
        # without re-running, and reproduced independently.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_profile.py`

line 51:

```text
# ── the audit ───────────────────────────────────────────────────────────
# Grouped by the file that reads the field; a field read by several files
# lists every location.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py`

line 22:

```text
#: v2: the prepared identity includes the executed run ``seed`` (reseal
#: audit). v1 omitted an executed input, so the generations are declared
#: incompatible rather than left to differ by hash only.
#: v3: the prepared identity also binds ``expected_flits``, so the
#: execution gate can enforce the fork's flit-injected == flit-accepted ==
#: expected conservation law instead of only packet count.
#: v4: the prepared identity binds the canonical first-hop route table
#: (``expected_route_rows``) and renders the route-dump path, so execution
#: can prove the EXECUTED route realization rather than only qualify it
#: statically (P0.10).
#: v5: the convergence window is derived from the per-source trace
#: injection horizon (flit-serialized at one flit/cycle per source port),
#: not from the packet count. A concentrated source (e.g. a broadcast
#: root fanning out multi-flit packets) needs far more than one injection
#: cycle per packet; the old window truncated such runs and the
#: conservation gate (correctly) refused them.
```

line 48:

```text
#: The fork composes its routing registry key as
#:   routing_function + "_" + topology
#: and cmesh registers "dor_no_express_cmesh" (networks/cmesh.cpp:66), so the
#: VALUE here is "dor_no_express". This is the PLAIN dimension-order
#: function (networks/cmesh.cpp: cmesh_next_no_express — x-then-y, no
#: express branch): exactly the canonical DOR_XY semantics over the
#: unfolded 2k x 2k node grid. The EXPRESS variant ("dor_cmesh" via
#: cmesh_next) adds bypass channels the canonical artifact does not
#: materialize and is deliberately not certified.
```

line 62:

```text
#: trace scheduling semantics (bound into the prepared identity)
#: v2: the convergence window is the per-source injection horizon (the
#: cycle the last flit enters the network), not the last timestamp.
```

line 69:

```text
#: AnyNet routing VALUE that composes the fork's registry key:
#:   routing_function + "_" + topology == "min_anynet"
#: (networks/anynet.cpp: gRoutingFunctionMap["min_anynet"] = &min_anynet)
```

line 114:

```text
    #: emitted only when the vendored fork actually reads the field
    #: (revalidated by the source audit); an optional field the fork does
    #: not read is reported as unavailable, never silently emitted
```

line 359:

```text
#: semantics version for the multi-class mesh profile: the injection-law
#: patch (per-class replay + one shared source port) is part of the
#: certified semantics, and the prepared-input schema gained the bound
#: class map.
```

line 425:

```text
#: The fork composes routing_function + "_" + topology; torus registers
#: "dim_order_torus" (routefunc.cpp), so the VALUE is "dim_order" — the
#: same value as mesh, disambiguated by topology="torus".
```

line 477:

```text
#: FlatFly registers "ran_min_flatfly" -> min_flatfly (the deterministic
#: minimal function despite the "ran" name). Following the fork's
#: value_topology composition, the certified VALUE is "ran_min".
```

line 631:

```text
    #: canonical traffic classes carried by the executed trace, mapped to
    #: the fork's dense class indices (sorted canonical names). One class
    #: means the trace renders index 0 — byte-identical to pre-v2 traces.
```

line 684:

```text
        # stub-parent contexts (qualification replays over a sealed
        # qualification object): the class gate is the preparer's law and
        # the preparer always carries the traffic artifact
```

line 905:

```text
    # Physical truth is shared verbatim with the deterministic envelope;
    # the class/transition law below is the adaptive envelope's own (the
    # deterministic identity-only law cannot cover escape entry).
```

line 932:

```text
    # The executed VC domain: every carried class over the full envelope
    # (the fork allocates from the route-set envelope starting at VC 0),
    # plus the escape-entry transitions of the qualified partition.
```

line 1605:

```text
            # the workload's class count IS a canonical value in this
            # profile (audit row is CANONICAL): one class index per
            # canonical traffic class
```

line 1611:

```text
        # Runtime-selected adaptive: mesh geometry, min_adapt_mesh fork
        # function, workload-derived class count, NO route-dump path
        # (candidate-set functions abort deterministic dumps — the
        # observation-scope guard, not a missing feature).
```

line 1715:

```text
    # The window must cover the per-source injection horizon, not merely the
    # last scheduled timestamp: a single source emitting back-to-back
    # multi-flit packets needs `sum(flits)` cycles to inject them, and a
    # window that stops earlier truncates the run (the conservation gate
    # then refuses it — F-0007).
```

line 1754:

```text
        # stub-parent contexts (qualification replays over a sealed
        # qualification object): the class gate is the preparer's law and
        # the preparer always carries the traffic artifact
```

line 1765:

```text
    # The fork executes one VC envelope for every class (route-set
    # envelope; injection starts at VC 0), so a class-to-VC-SUBSET
    # assignment is not executed on AnyNet either: every bound class
    # must carry the full envelope, exactly as the mesh/cmesh
    # qualifiers demand. Identity transitions only, for the same
    # reason: the qualifier cannot prove cross-VC routing it never
    # rendered.
```

line 1866:

```text
    #: canonical traffic-class names mapped to the fork's dense trace
    #: class indices (sorted). Bound so the executed class identity is
    #: part of the prepared identity — a remapping can never be invisible.
    #: Empty for single-class profiles (the trace renders index 0).
```

line 1871:

```text
    #: per-class flit counts keyed by canonical class name; execution
    #: must conserve each class independently (booksim2-fork/v2 emits
    #: per-class counters for exactly this check).
```

line 1875:

```text
    #: canonical first-hop expectation: (src_router, node, next_router)
    #: rows over the execution node universe. Bound so execution can prove
    #: the executed route realization (P0.10).
```

line 1908:

```text
            # class identity keys appear ONLY when a class map is bound
            # (multi-class profile): single-class science keeps the exact
            # identity it always had — a prepared id never moves because a
            # new field was added empty.
```

line 2019:

```text
    # include_optional renders the route-dump path: the executed first-hop
    # realization is required evidence (P0.10), so it is not optional for a
    # certified prepared input.
```

line 2024:

```text
    # Every REQUIRED rendered field must appear (a required pin silently
    # vanishing from the render is itself a projection defect — the old
    # `if name in values` guard could not see it), and every pin must be
    # rendered verbatim.
```

line 2048:

```text
    # Canonical executed-route expectation. mesh-DOR addresses every router
    # as a node (native mesh node n <-> router n); AnyNet addresses the
    # attached endpoint nodes; cmesh addresses the fork's 2k x 2k folded
    # node grid via the seat mapping.
```

## `tracks/t3-topology/dse/veritx_dse/backend/canonical_serving.py`

line 381:

```text
            # A caller-supplied digest is a CLAIM, never evidence: resolve the
            # real binary and refuse any disagreement, so a false digest or a
            # substituted binary cannot become scientific evidence.
```

line 537:

```text
        # Native-layer validation: a corrupt cycle count must refuse at
        # construction, never travel into evidence and normalize silently.
        # None stays allowed (absent metric, never zero-filled).
```

line 560:

```text
    #: Declared service-profile identity (CertifiedServiceProfile.profile_id()).
    #: A declared semantics input is part of the scientific identity: without
    #: it two runs with different declared profiles produce identical evidence
    #: and cannot be told apart or reproduced.
```

line 654:

```text
        # Identity version 2: the declared service-profile identity is bound
        # in. Version 1 evidence did not carry it, so a v1 and a v2 digest are
        # deliberately not comparable.
```

## `tracks/t3-topology/dse/veritx_dse/backend/evidence.py`

line 18:

```text
#: v2: the run-stable scientific payload also binds the BUILD provenance
#: that established producer qualification: ``build_manifest_sha256`` (the
#: exact build manifest the binary was verified against) and
#: ``build_recipe_version``. A v1 document cannot prove which manifest (or
#: recipe) qualified its binary, so the generations are declared
#: incompatible: v1 is refused, never silently reread as v2.
#: v3: binds ``route_dump_sha256`` — the exact executed first-hop dump the
#: route realization was compared against (P0.10). OBSERVED without it is
#: impossible.
```

line 40:

```text
#: The build recipe every certified BookSim profile must have been built by.
#: Admission checks it by profile, so a self-consistent document that names
#: an arbitrary valid-looking recipe cannot enter a certified product.
```

line 56:

```text
#: Closed vocabularies for the run-stable scientific fields. An unknown
#: token is not a known measurement: a reader must never treat an invented
#: fidelity or transport as qualified, and a self-consistent document with
#: an impossible combination must refuse even though its evidence_id
#: recomputes.
```

line 269:

```text
    #: exact build manifest the binary was verified against, and its recipe
    #: version. Required for a certified-product admission: without them the
    #: evidence cannot prove WHICH manifest established qualification.
```

line 311:

```text
        # Closed vocabularies + cross-field impossibility. Content
        # authenticity (the evidence_id) is necessary but not sufficient:
        # a self-consistent document can still describe a run that cannot
        # exist, and must refuse before it can be read as a measurement.
```

line 545:

```text
        # A certified BookSim profile must have OBSERVED its executed route:
        # a rehashed current-schema document that skipped observation must
        # not enter the certified chain.
```

line 704:

```text
# Fields every unversioned historical (v1) consumer needed. v1 predates
# the schema marker, so there is no closed field set to enforce; these
# are the minimum keys that make the document readable as certified
# evidence at all.
```

line 929:

```text
        # The label order preserves v1 artifact identity exactly: v1
        # documents carry host platform text and it remains the label.
        # v2 documents carry no platform text, so the authenticated
        # transport is the stable label.
```

## `tracks/t3-topology/dse/veritx_dse/backend/evidence_cache.py`

line 16:

```text
#: Every field bound into the reuse key. All must match exactly on lookup.
#: prepared/config/trace/binary pin the execution; profile/projection/
#: parser/build-manifest/recipe/schema pin the semantics; producer pins
#: the binary provenance; seed/topology/fabric/traffic/message/route pins
#: the design; question + network clock pin the asked quantity.
```

## `tracks/t3-topology/dse/veritx_dse/backend/meshdor.py`

line 769:

```text
        # rendered.file()'s documented missing-input error only: a
        # programming error propagates instead of reading as a lowering
        # refusal.
```

## `tracks/t3-topology/dse/veritx_dse/backend/normalized_evidence.py`

line 208:

```text
    # Binding identities are digests; named parents (design names,
    # workload ids) are not comparable here and are skipped — the
    # adapter's outcome-vs-context checks own those.
```

## `tracks/t3-topology/dse/veritx_dse/backend/producer.py`

line 17:

```text
# Canonical execution-transport values (reclaimed verbatim from the RT
# candidate 26e6f9dc, additive only): the production runner is the only
# transport whose evidence is reusable; anything else is a test fixture.
# The RT backend stack (backend/meshdor.py) imports these names.
```

line 35:

```text
    #: True only when a build-time manifest verified the binary against
    #: the source revision/dirty state observed AT BUILD. Ambient git HEAD
    #: is not build provenance and never sets this.
```

line 39:

```text
    #: identity of the manifest that established qualification, and the
    #: build recipe it was produced by. Bound into evidence so a certified
    #: product can name exactly which manifest qualified its binary.
```

## `tracks/t3-topology/dse/veritx_dse/backend/projection.py`

line 19:

```text
# Canonical adapter (veritx-integrate §4/§7): the RT candidate bound this
# seam to the v1 PhysicalTrafficArtifact; the v1 authority was deleted
# and the canonical PhysicalTrafficArtifactV2 carries the same
# traffic/bundle surface the renderer consumes, so the seam binds V2.
```

## `tracks/t3-topology/dse/veritx_dse/backend/qualification.py`

line 23:

```text
# Fields allowed to differ between the two BookSim targets, with the
# reason they are execution/workload-specific rather than realization
# semantics. Closed list: a new target override must be added here
# explicitly after review, or realization comparison will refuse it.
```

line 176:

```text
    # Target identity is authoritative from the artifact; caller labels are
    # display aliases and must agree. Duplicate target artifacts under
    # different aliases are refused.
```

line 194:

```text
            # Profile-aware canonical check: the mesh-DOR profile has
            # its own lowerer and identity; the AnyNet assert would
            # refuse it for the wrong reason (profile mismatch).
```

line 265:

```text
    # Shared realization for target pairs sharing the canonical BookSim
    # lowerer: every result-affecting parameter except the closed
    # target-specific exclusion list.
```

## `tracks/t3-topology/dse/veritx_dse/backend/ramulator_adapter.py`

line 295:

```text
        # Semantic preparation: the workload's COMPUTE memory operands
        # resolved against the certified profile. A workload with no
        # resolvable memory demand refuses here — never zero cost.
```

line 353:

```text
        # Tamper-closed: the lowered trace must reproduce the config
        # identity preparation bound — a substituted lowering refuses
        # before spawn.
```

line 470:

```text
#: native metric keys projected into the normalized envelope, in stable
#: order. wall_time_s is deliberately absent: elapsed host time is not a
#: scientific design objective. issued_* counters are covered by the
#: generated/accepted/completed drain counters.
```

line 491:

```text
#: Public alias for the federation capability catalog: the native
#: metric keys ``normalize()`` projects for DRAM_TIMING (single source;
#: edit here when ``normalize()`` gains a metric, never in a second
#: matrix). Units are evidence-declared per run (not statically known);
#: every row binds as a scalar.
```

line 509:

```text
#: prepare() failures that are SEMANTIC (UNSUPPORTED/BLOCKED), never
#: runtime. Programming errors (TypeError, AttributeError,
#: AssertionError, KeyError) are deliberately absent: they escape.
```

## `tracks/t3-topology/dse/veritx_dse/backend/registry.py`

line 95:

```text
        # Unbound: assesses SERVING_* as SUPPORTED + BLOCKED (never
        # READY, never fake coverage); a bound experiment comes from
        # explicit serving options, never by default.
```

## `tracks/t3-topology/dse/veritx_dse/backend/reproduce.py`

line 182:

```text
        # Input pinning: the rerun executes exactly the bytes the
        # evidence names. The run seed is baked into the config bytes,
        # so matching the config digest pins the seed with it. An
        # input the evidence names but the bundle cannot supply (or
        # vice versa) refuses instead of running approximate inputs.
```

## `tracks/t3-topology/dse/veritx_dse/backend/reproduce_astra.py`

line 89:

```text
    # The archived namespace's rank map must equal the stored evidence's
    # executed binding: a permuted map with a colliding namespace id
    # would otherwise re-execute a different placement as "matching".
```

line 98:

```text
    # Producer pin: the rerun binary must be the exact producer the
    # stored evidence attributes (same SHA under the qualified recipe).
    # A different binary — even a rebuild from the same source — is a
    # different producer and cannot "match" this evidence. Standalone
    # config and ABI generations are covered by the machine_id and
    # evidence_id equalities below (both bind those facts).
```

## `tracks/t3-topology/dse/veritx_dse/backend/route_observation.py`

line 146:

```text
# ── adaptive observation scope ─────────────────────────────────────────
#
# The fork REFUSES a deterministic first-hop dump for adaptive routing
# functions (networks/network.cpp: a multi-port candidate set aborts the
# dump instead of writing a table). The canonical side mirrors that
# refusal: a deterministic RouteArtifact table can never certify adaptive
# execution, and claiming route equivalence from it is a scope violation.
# Adaptive inspection renders the canonical candidate sets (not evidence).
```

## `tracks/t3-topology/dse/veritx_dse/backend/serving_adapter.py`

line 29:

```text
#: stable execution identity — the same authority string the serving
#: envelopes already carry. One spelling across planner, envelopes,
#: evidence.
```

line 47:

```text
#: native qualification word for a bound, runnable serving experiment.
#: The per-run qualification rides the normalized envelope as the
#: evidence execution mode (LIVE_CANONICAL_EXECUTION).
```

line 487:

```text
#: constructor fields of CanonicalServingEvidence, in order. A strict
#: allowlist: an upstream field addition fails loudly here (forcing
#: review of what the new field means) instead of dropping science
#: silently.
```

## `tracks/t3-topology/dse/veritx_dse/backend/serving_normalization.py`

line 19:

```text
#: names the canonical serving authority in normalized envelopes — and
#: the planner adapter id of backend.serving_adapter.ServingAdapter.
#: One spelling across planner rows, envelopes and evidence.
```

line 52:

```text
    # Gate order is the law: liveness first, then completeness. A
    # replay-only run and a partial run both refuse — never a silent
    # subset normalization.
```

line 74:

```text
        # Construction-time validation (RequestMetric.__post_init__) is
        # the primary gate; this refusal is the backstop for evidence
        # rebuilt outside it. A corrupt value refuses loudly — it is
        # never dropped silently, which would mask corrupt evidence.
```

## `tracks/t3-topology/dse/veritx_dse/backend/serving_round.py`

line 124:

```text
    #: expert-parallel (MoE) participation.  Defaults keep dense plan
    #: identities byte-identical; EP reuses the same participant ranks
    #: (ep_size <= instance ranks; TP/EP overlap, no rank multiplication).
    #: The executable semantics are dispatch ALLGATHER + per-rank expert
    #: compute + combine REDUCESCATTER, exactly as LLMServingSim emits.
```

line 495:

```text
                # Chain expert computes positionally: the canonical graph
                # requires a unique dependency-derived order, so parallel
                # expert ranks migrate to an explicit chain (structural,
                # not temporal — service time is still the max rank).
```

line 797:

```text
            # Pure runtime noise never carries the marker and stays
            # skipped. A line that STARTS a ledger record but does not
            # parse is a truncated/corrupt record: fail fast here and
            # name truncation, instead of failing late in validation
            # with a misleading "never submitted" error.
```

line 875:

```text
    # The NUMBER of submissions is part of the contract, not just their
    # content: every participant submits the collective, so a ledger holding
    # only some ranks' lines must not validate green.  A subset check alone
    # accepts a single submission for a 16-rank round -- which is exactly how
    # a truncated/partially-evicted ledger slipped through once.
```

## `tracks/t3-topology/dse/veritx_dse/backend/source_audit.py`

line 107:

```text
# ── site-gated read closure (reclaimed verbatim from the RT candidate
# 26e6f9dc, additive only): the RT backend stack (backend/booksim.py,
# backend/meshdor.py, backend/meshdor_profile.py) authenticates rendered
# configs against these declared read sites. The canonical simple audit
# API above is untouched; this block adds names only.
```


# `backend` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/backend/adapter.py` :: `BackendAdapter`

```text

    Exactly five operations: declare capabilities, assess one for a
    canonical context, prepare, execute, normalize. The adapter
    ORCHESTRATES existing backend authorities (projection, execution,
    evidence); it does not re-implement or force them into one
    lifecycle — no parse()/verify()/qualify() ceremonies. Native
    evidence stays authoritative; ``normalize()`` is an index/view over
    it, never a conversion of it.
```

## `tracks/t3-topology/dse/veritx_dse/backend/adapter.py` :: `BackendAssessment`

```text

    Cross-field laws: UNSUPPORTED can never be READY and always names
    its reason; BLOCKED and UNAVAILABLE always name theirs; READY
    requires the semantics be representable (support != UNSUPPORTED).
    No law requires a qualification_profile — future backends may
    qualify differently.
```

## `tracks/t3-topology/dse/veritx_dse/backend/adapter.py` :: `BackendCapability`

```text

    A declaration, not a persisted scientific artifact — no content
    identity in this commit. ``question`` is from the closed
    ``EvaluationQuestion`` vocabulary: capability truth, not aspiration.
```

## `tracks/t3-topology/dse/veritx_dse/backend/adapter.py` :: `BackendReadiness`

```text

    READY: semantics passed and the required producer/runtime exists.
    BLOCKED: the backend exists but semantic or qualification
    requirements prevent this execution.
    UNAVAILABLE: the required executable/runtime/producer is absent.

    UNSUPPORTED (semantics) and UNAVAILABLE (runtime) are different
    states: a backend can support a capability while its executable is
    missing.
```

## `tracks/t3-topology/dse/veritx_dse/backend/adapter.py` :: `ModelFidelity`

```text

    Deliberately orthogonal to execution/provenance qualification
    (``ScientificBackendEvidence.execution_fidelity`` QUALIFIED /
    DIAGNOSTIC_UNPINNED_PRODUCER / TEST_INJECTED). Model fidelity says a
    packet-level network simulation produced the number; qualification
    says whether that execution's producer was pinned. Never collapse
    the two dimensions.
```

## `tracks/t3-topology/dse/veritx_dse/backend/adapter.py` :: `PreparedExecution`

```text

    References the existing authorities; never flattens or supersedes
    them. ``backend_config``/``backend_input`` are optional because
    BookSim fits those contracts naturally while other backends (e.g.
    ASTRA) carry their own native projection identities — requiring the
    BookSim artifacts here would secretly make this a BookSim contract.
    ``native_prepared`` is the backend-specific prepared structure,
    referenced opaquely: no hashing, no serialization, no inspection.
```

## `tracks/t3-topology/dse/veritx_dse/backend/adapter.py` :: `SupportLevel`

```text

    SUPPORTED: representable inside a stated capability envelope.
    CONDITIONAL: representation depends on explicit conditions checked
    during assessment.
    UNSUPPORTED: the backend cannot faithfully represent the semantics.
    Never a boolean: the reason a backend cannot represent is evidence.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_adapter.py` :: `Astra2Adapter`

```text

    Assessment walks the real gate chain (collective-envelope audit,
    namespace-valid projection, machine qualification over the certified
    fabric projection, executable present, producer identifiable and
    pinned, Chakra staging available) — a READY assessment means those
    gates passed on this context. Assessment never spawns the runtime.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_adapter.py` :: `Astra2Preparation`

```text

    The real projections are retained (not only their ids) so
    ``execute()`` can stage the Chakra workload itself — preparation is
    semantic projection, executable by itself, with no runtime binary
    required.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_adapter.py` :: `Astra2SemanticRefusal`

```text

    Typed so assessment maps a PREPARE refusal to UNSUPPORTED without a
    bare ``except Exception`` — which would launder programming bugs
    into capability verdicts.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_adapter.py` :: `ProducerPin`

```text

    Preparation is deliberately binary-independent, so the pin is
    resolved in ``execute()`` (never in ``_prepare_native``) from the
    existing producer authority and stamped into evidence. Normalization
    verifies the evidence's producer facts against this pin's recipe
    and pin-quality rules.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_machine.py` :: `EmbeddedFabricConfig`

```text

    Derived mechanically from the qualified Slice-31 standalone config: the
    machine-semantic surface is carried byte-identically, the
    workload-driving surface is disarmed.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_namespace.py` :: `AstraCollectiveBinding`

```text

    ``AstraExecutionNamespace`` owns what does not change per round: the
    canonical ``rank -> endpoint`` mapping, the endpoint count and the router
    count.  A live serving workload changes every round, so its collective
    memberships cannot be frozen into the namespace.

    This binding owns only the round-varying part, keyed by *operation id*:

        operation_id -> exact endpoint membership
        operation_id -> runtime collective mechanism
        membership   -> deterministic communicator group number

    It never renumbers endpoints, never regenerates the fabric and never
    re-derives the rank mapping.  Group numbering is transport representation;
    membership is semantic.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_namespace.py` :: `CommunicatorGroups`

```text

    Membership is semantic; the numeric id is transport representation and is
    assigned deterministically from sorted canonical membership, never from
    Python object iteration order.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_namespace.py` :: `stage_endpoint_workload`

```text

    Canonical ETs are generated per **rank** by the Slice-30 writer.  This
    adapter translates only the runtime namespace:

      * the filename index becomes the endpoint id (``Sys.id``);
      * ``COMM_SEND_NODE``/``COMM_RECV_NODE`` ``comm_src``/``comm_dst`` are
        rewritten rank → endpoint;
      * every ``COMM_COLL_NODE`` gains ``pg_name = "<group id>"``.

    Non-participant endpoints receive **no** file, so the current source
    treats them as idle (``Workload.cc``: missing rank file ⇒ empty
    workload).  Returns the staged mapping so the caller can assert it.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim.py` :: `CertifiedBookSimEvidence`

```text

    ``to_dict()`` emits ONLY the run-stable scientific document
    (``ScientificBackendEvidence``, evidence-v2); the measured wall time,
    command/backend paths and host platform text are exposed through
    ``execution_attempt()`` / ``to_attempt_dict()`` as a separate attempt
    record that never enters a scientific digest.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim.py` :: `_execute_prepared`

```text

    Only ``run_qualified_booksim`` (authoritative supervised process
    runner) may emit reusable ``EXECUTED_*`` evidence; the test-only
    seam below passes an injected runner with the TEST transport whose
    products the reuse API mechanically refuses.

    Order: revalidate bundle → canonical config → canonical prepared
    inputs (exact render + manifest binding) → qualification guard →
    producer identity (canonical absolute path, pre-spawn digest, fail
    closed) → materialize → parse-back topology → verify hashes
    IMMEDIATELY BEFORE spawn → runtime profile gates → fresh route-output
    slot → final producer recheck → run → executed-route proof → parse
    stats. Any tamper/stale/forged/unidentified input refuses before
    materialization or spawn.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim.py` :: `assert_canonical_prepared_booksim`

```text

        bundle -> canonical config -> exact rendered bytes
               -> exact canonical BackendInputManifest

    A canonical config paired with forged rendered bytes and a freshly
    recomputed, internally valid manifest is refused here: the workload
    bytes are taken as the execution-input authority, the renderer is
    re-run for the manifest's seed intent, every file is compared by
    exact bytes, and the manifest is re-bound and compared by complete
    identity. Hash consistency alone is never accepted at any boundary.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_adapter.py` :: `BookSimAdapter`

```text

    Supports exactly NETWORK_COMPLETION at NETWORK_PACKET_SIMULATION
    fidelity. Assessment re-runs the same canonical gates the evaluator
    always applied (artifact construction, VC admission, projection)
    AND proves runtime readiness (binary exists, producer identity
    resolves, build recipe matches, producer pinned, manifest
    qualification passes) — a READY assessment means those gates all
    passed on this context, not merely that the backend exists.
    Assessment never spawns BookSim.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_adapter.py` :: `BookSimProjectionRefusal`

```text

    Typed so the evaluator can map a PREPARE refusal to UNSUPPORTED
    without a bare ``except Exception`` — which would swallow bugs into
    a semantic verdict. Carries the message/traffic artifact identities
    when those artifacts were constructed before the gate refused, so a
    refusal outcome can bind exactly which traffic was refused.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_execution.py` :: `parse_booksim_stats`

```text

    Contract (``PARSER_VERSION``):
      * ``Loaded text trace: N packets`` is REQUIRED trace evidence;
      * ``Completion time is N cycles`` is REQUIRED completion evidence:
        the cycle of the last ejected flit — the network-physical
        completion, invariant under the sampling window (F-0001);
      * ``Time taken is N cycles`` is RECORDED as ``sample_window_cycles``
        (diagnostic only): it is a function of ``sample_period *
        max_samples``, not of network behaviour, and must never be
        reported as latency or used as an objective;
      * ``sample_window_cycles`` must bound ``completion_cycles`` — a
        completion after the run window is a parse error, refused;
      * the trace drain line (stderr, ``[trace] All <c> cycles, injected=N``)
        is RECORDED when present and may be absent in other modes;
      * ordinary latencies/hops that are absent or printed as
        ``-``/``nan``/``inf`` become ``None`` — never 0, never a failure;
      * a non-finite value never enters evidence;
      * instability/abort tokens are recorded and refuse downstream.

```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `BookSimProjectionParents`

```text

    Replaces the historical ``ResolvedFabricBundle``: the canonical
    ``ResolvedFabric`` binds only hashes, so the actual child artifacts
    are passed explicitly and re-checked here before any rendering.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `CMeshDorQualification`

```text

    Every field is a canonical artifact fact that the profile's execution
    semantics were proven against; nothing here is derived from counts
    alone.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `PreparedBookSimInput`

```text

    Identity binds every simulation-relevant parent: canonical artifact
    hashes, the physical-traffic artifact, the certified profile and its
    semantics/lowerer versions. Temporary directories, absolute paths and
    run slots are absent from identity by construction.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `TorusDorQualification`

```text

    The dateline VC-partition theorem is stated here and discharged by
    the channel-VC CDG certificate downstream: ``vc_count == 2`` with
    identity transitions gives the fork's ``dim_order_torus`` halves
    exactly one VC each. ``tie_flows`` are the even-k midpoint flows the
    fork resolves randomly — carved out of COMPARABLE equivalence.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `prepare_min_adapt_input`

```text

    Selection-driven (never via select_booksim_profile, which stays
    deterministic-only): the qualifier proves the mesh base + VC
    partition + qualification binding, then this renders the min_adapt
    profile with NO route-dump path and NO expected route rows —
    candidate-set routing has no deterministic first-hop table, so
    execution evidence is conservation +
    DOMAIN_QUALIFIED_ROUTE_NOT_OBSERVED (the observation-scope guard).
    Per-class identity rides the fork-v2 replay law exactly as in the
    multi-class profile; nothing is flattened, inferred or re-timed.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `qualify_min_adapt_mesh`

```text

    The declared policy/profile, escape semantics and candidate-set scope
    are qualified by the canonical chain (MinAdaptQualification over the
    escape-subfunction proof); this projection consumes that verdict and
    proves the mesh base, the VC partition and the fork mapping:

      * mesh-DOR base gates reused verbatim (geometry, seat capacity,
        DOR_XY escape-source route class, VC envelope, unit
        latency/weights, no parallel channels, fork-v2 per-class law)
        via the single/multi-class qualifier selected by the workload's
        class count — EXCEPT the identity-VC gate, which the escape
        subfunction supersedes by proof;
      * esc_resource: same VC ids/count as the compiler resource, whose
        transitions are exactly identity + the binding's adaptive->escape
        hops, hash-bound through binding and qualification;
      * vc_count == selection.num_vcs >= 2 (escape VC0 + adaptive 1..N);
      * qualification verdict QUALIFIED with matching routing function,
        escape/adaptive partition and policy/realization hashes.

    UGAL/Valiant/Chaos/planar/ROMM/GEC-adaptive and the broken
    limited_adapt_mesh are refused by the canonical chain before this
    projection is reachable; routing_function stays LOCKED (no user
    knob — the selection record is the only authority).
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `qualify_native_cmesh_dor`

```text

    The envelope is the fork's own contract (networks/cmesh.cpp), each
    clause proven against the canonical artifacts:

    1. family CONCENTRATED_MESH, uniform seat_capacity == 4 (the fork
       asserts ``c == 4``);
    2. square k x k router grid in row-major coordinates matching the
       fork's ``y * k + x`` router ids;
    3. endpoints dense 0..E-1, one per seat, seat ports forming the
       2x2 block the fork's NodeToPort expects;
    4. the route artifact realizes DOR_XY and every VC binds DOR_XY
       (the fork executes one deterministic dimension-order function);
    5. uniform channel latency 1 and route_weight 1 — the profile pins
       ``use_noc_latency = 0``, which makes every link latency 1 in the
       fork, so a canonical channel that is not unit-latency would
       execute with WRONG latency and must refuse here;
    6. no parallel channels (the fork's channel grid is one channel per
       direction per adjacent pair);
    7. single traffic class over the full VC set, identity VC
       transitions (the same trace-class law as the mesh envelope).
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `render_trace`

```text

    The fork's trace dialect is ``cyc src cl dst sz`` with ``sz`` in
    FLITS, one line per physical packet, timestamps in emission order.
    Deterministic: (message order, packet index) only.

    Class-aware (booksim2-fork/v2): column 3 carries each message's
    canonical traffic-class index from ``trace_class_map``. The vendored
    fork's ``TraceInjectionProcess`` class filter replays each event in
    exactly the class the trace labels — never a cross-class copy — so
    the executed classes ARE the canonical classes.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `vc_exactness`

```text

    Source audit (booksim2-fork/v2): ``iq_router`` takes an output VC
    from the ROUTE SET's ``vc_start..vc_end`` (routers/iq_router.cpp,
    piggyback VC allocation), and the injection VC search starts at VC 0
    (trafficmanager.cpp ``Find first available VC``) — neither consults
    the packet's class. So a class-to-VC-SUBSET assignment is executed
    only when every class's canonical set equals the full envelope: that
    IS the VC-domain design the backend runs, not a collapse of it. A
    real class-split VC assignment refuses with this named reason until
    routing-level class binding exists (never silently narrowed).
```

## `tracks/t3-topology/dse/veritx_dse/backend/canonical_serving.py` :: `ServingDataParallelGroup`

```text

    DP grouping is a SERVICE fact: which replicas must synchronize their
    forwards.  It is not a parallelism axis of the fabric.  It never adds
    ranks, never renumbers endpoints, and never touches topology -- it only
    names serving instances that already exist in a
    ``ServingNamespaceBinding``.
```

## `tracks/t3-topology/dse/veritx_dse/backend/canonical_serving.py` :: `ServingDataParallelGroups`

```text

    Content-addressed, and deliberately *only* a grouping: it does not
    participate in the rank namespace, the endpoint mapping, the namespace id,
    the machine identity or the resolved fabric.
```

## `tracks/t3-topology/dse/veritx_dse/backend/canonical_serving.py` :: `ServingNamespaceBinding`

```text

    Slices 33/34 own rank -> endpoint; this only adds the serving-instance
    grouping, and every relation is validated against the qualified objects
    rather than derived from numeric coincidence.
```

## `tracks/t3-topology/dse/veritx_dse/backend/contracts.py` :: `BackendConfigArtifact`

```text

    Every SemanticDimension appears exactly once. Identity contains no
    design/mapping/workload/run/backend-binary bytes: the projection is a
    pure function of the fabric hash, the declared target/profile and the
    lowered parameters/bindings.
```

## `tracks/t3-topology/dse/veritx_dse/backend/contracts.py` :: `BackendInputManifest`

```text

    ``backend_input_hash`` changes when a true backend input changes
    (workload content, seed, rendered bytes, invocation) and does NOT
    change when only a filesystem path changes. The executable/source
    identity is deliberately absent; B4 composes that later.
```

## `tracks/t3-topology/dse/veritx_dse/backend/contracts.py` :: `ExecutionQualification`

```text

    A successful process exit must never be reported as generic
    "certified": the qualification is derived from the artifact's
    bindings, and UNSUPPORTED_EXECUTION bindings refuse before spawn.
```

## `tracks/t3-topology/dse/veritx_dse/backend/contracts.py` :: `ParameterOwner`

```text

    A rendered backend parameter with no owner is an error; a parameter
    relying on an undeclared backend default is an error too. Certificate
    paths never carry free-form overrides. INACTIVE_FOR_PROFILE is used by
    the closed-world audit for parameters that are read by backend code
    but cannot affect the certified profile's results (and are documented
    with a source location instead of silently defaulted).
```

## `tracks/t3-topology/dse/veritx_dse/backend/contracts.py` :: `SemanticBinding`

```text

    ``supported_domain`` states the exact subset of the artifact's domain
    the declaration covers (e.g. "escape_vcs must be empty"). Without it,
    an unconditional EXACT cell would over-claim arbitrary
    representability. Exact declarations must name their supported domain;
    non-exact declarations may leave it empty (nothing is representable).
```

## `tracks/t3-topology/dse/veritx_dse/backend/evidence.py` :: `EvidenceArtifact`

```text

    Where ``EvidenceRef`` is the external identity of the persisted bytes,
    this is the internal identity of what those bytes MEAN: the backend
    input they were executed from, the raw bytes themselves, the parser
    version that read them and the stats digest they carry. A result that
    cannot name its evidence_id has evidence it cannot authenticate.
```

## `tracks/t3-topology/dse/veritx_dse/backend/evidence.py` :: `admit_for_certified_product`

```text

    Content authenticity (a valid ``evidence_id``) is not admission: a
    document can hash correctly and still describe a diagnostic, dirty,
    unpinned or test-injected run. This function is the one place that
    decides qualification; call sites must not re-implement it.

    Requires: supervised production transport, QUALIFIED fidelity, a known
    producer source revision, a clean (not dirty) producer, exit 0, and a
    verified build manifest + recipe bound into the evidence.
    ``TEST_INJECTED``, diagnostic, dirty, unpinned, unknown-build and
    unmanifested runs are refused.
```

## `tracks/t3-topology/dse/veritx_dse/backend/evidence.py` :: `admit_normalize_bare_evidence`

```text

    The federated BookSim evaluator persists the bare scientific
    document (never the wrapper: wrapper bytes mix run-varying attempt
    metadata, so a wrapper digest can never be run-stable). The
    wrapper-based reusable-record discipline therefore cannot apply;
    instead the caller names the exact bytes digest the producing
    execution sealed (``outcome.raw_evidence_digest``). A copied file
    from another run carries bytes the outcome does not name and
    refuses here. The document then passes canonical validation
    (which recomputes ``evidence_id``), certified admission and the
    same preparation binding as reusable records.
```

## `tracks/t3-topology/dse/veritx_dse/backend/evidence.py` :: `validate_evidence_document`

```text

    Current-version documents are validated against the CLOSED
    scientific-evidence schema: exactly the scientific fields, no
    leaked-back attempt metadata, no extras; the canonical validated
    document is returned. Unversioned documents are historical v1 and
    keep their legacy acceptance semantics. Any other declared
    generation refuses — an unknown schema is never read as a known one.

    Every consumption path (reuse, authenticated proof, control-plane
    verification) must pass bytes through this before using any field.
```

## `tracks/t3-topology/dse/veritx_dse/backend/meshdor.py` :: `_mesh_link_semantics`

```text

    Native mesh links are latency 1 (no per-link control exists), DOR
    ignores route weights (a non-unit weight would leave a fabric
    semantic unexecuted), and parallel channels have no native
    representation (last-mention-wins ambiguity, as with AnyNet).

    The channel set must BE the native k x k mesh adjacency (row-major
    numbering, x = router_id % k, y = router_id // k), both directions.
    Anything else — an express (non-grid) edge, or a missing grid edge
    — has no native representation: BookSim derives its link topology
    from k alone, so the artifact's channels would not be the channels
    the backend executes. This is the positive proof behind the
    TOPOLOGY_GRAPH -> DERIVED_EXACT claim; without it that claim is
    unearned.
```

## `tracks/t3-topology/dse/veritx_dse/backend/meshdor.py` :: `compare_meshdor_route_realization`

```text

    Native node n <-> router n is proven by the lowering's
    identity-prefix check (re-asserted here before trusting it): an
    attached endpoint maps to its own id, and an idle native node IS its
    router. Proving the idle nodes' forwarding is what shows unused
    terminals neither inject (they cannot address the trace) nor alter
    routing. Same dump grammar as AnyNet, so the row parser is shared in
    shape (duplicated here so the sealed AnyNet compare stays untouched).
```

## `tracks/t3-topology/dse/veritx_dse/backend/meshdor_profile.py` :: `_mesh_sites`

```text

    Transformation of GATED_READ_SITES, stated explicitly:
    - every `pin:topology=anynet` disabling argument becomes
      `pin:topology=mesh` (other topologies' constructors never run);
    - `k`/`n`/`use_noc_latency` @ kncube become ACTIVE reads (dropped
      from the site table — active fields need no sites);
    - `fail_seed` @ kncube stays gated but on its true guard,
      `pin:link_failures=0` (read only inside `if (_size && num_fails)`);
    - `network_file` @ anynet gains a site (unregistered in this
      profile; unreachable under mesh).
```

## `tracks/t3-topology/dse/veritx_dse/backend/normalized_evidence.py` :: `MetricValue`

```text

    Every objective value that ever reaches an optimizer or the Studio
    rides in one of these: a number alone is not evidence.

    ``dimensions`` carries coordinates such as ``(("rank", "3"),)`` for
    per-rank ASTRA metrics or ``(("request_id", ...),)`` for serving —
    never invented key suffixes like ``rank_0_cycles``. Metric identity
    is ``(key, dimensions)``: the same key with different dimensions is
    a different measurement of the same quantity, not a duplicate.
```

## `tracks/t3-topology/dse/veritx_dse/backend/normalized_evidence.py` :: `NormalizedBackendEvidence`

```text

    ``qualification`` is the native execution/provenance verdict (e.g.
    ScientificBackendEvidence.execution_fidelity: QUALIFIED /
    DIAGNOSTIC_UNPINNED_PRODUCER / TEST_INJECTED, or an
    ExecutionQualification value) — deliberately orthogonal to
    ``model_fidelity``, which says what KIND of model produced the
    number. Never collapse the two dimensions.
```

## `tracks/t3-topology/dse/veritx_dse/backend/qualification.py` :: `SharedAuthorityClaim`

```text

    ``source_identity``, ``status`` and ``supported_domain`` must all
    agree across the claimant targets; the domain is what keeps an EXACT
    cell from over-claiming arbitrary semantics.
```

## `tracks/t3-topology/dse/veritx_dse/backend/ramulator_adapter.py` :: `RamulatorAdapter`

```text

    Supports exactly DRAM_TIMING at MEMORY_CYCLE_SIMULATION fidelity.
    Assessment re-runs the real semantic gate (``resolve_memory_graph``
    against the certified profile) AND proves runtime readiness (the
    compiled extension exists and certified producer facts establish) —
    a READY assessment means those gates all passed on this context, not
    merely that the backend exists. Assessment never spawns Ramulator.
```

## `tracks/t3-topology/dse/veritx_dse/backend/ramulator_adapter.py` :: `RamulatorPreparation`

```text

    The real MemoryArtifact is retained (not only its hash) so
    ``execute()`` generates the real trace itself — preparation is
    semantic resolution, executable by itself, with no runtime binary
    required. ``backend_config_hash`` is the recomputable config identity
    (``backend_config_payload`` over the certified geometry); execute()
    refuses when the trace it lowers does not reproduce it.
```

## `tracks/t3-topology/dse/veritx_dse/backend/ramulator_adapter.py` :: `RamulatorSemanticRefusal`

```text

    Typed so assessment maps a PREPARE refusal to UNSUPPORTED without a
    bare ``except Exception`` — which would launder programming bugs
    into capability verdicts.
```

## `tracks/t3-topology/dse/veritx_dse/backend/route_observation.py` :: `compare_route_realization`

```text

    Legal next-hop adjacency is already proven when ``expected_route_rows``
    is derived: every non-local expected hop is looked up as a real channel
    leaving that src router. Exact executed == expected therefore implies
    adjacency-legal hops; a divergent dump refuses.

    The VERDICT is delegated to
    ``core.route_artifact.compare_first_hop_tables`` — the one comparison
    authority. This function contributes the dump parsing, the id mapping
    and the evidence digests, and converts a DIVERGENT verdict into the
    typed refusal this adapter's callers expect.
```

## `tracks/t3-topology/dse/veritx_dse/backend/serving_adapter.py` :: `ServingAdapter`

```text

    Answers exactly SERVING_TTFT and SERVING_COMPLETION at
    FULL_SYSTEM_SIMULATION fidelity. Assessment re-runs the real gates
    (bound experiment, parseable cluster semantics, usable runtime) —
    a READY assessment means those gates passed on this context, not
    merely that serving exists. Assessment never spawns the runtime.
```

## `tracks/t3-topology/dse/veritx_dse/backend/serving_adapter.py` :: `ServingSemanticRefusal`

```text

    Typed so assessment maps a PREPARE refusal to UNSUPPORTED/BLOCKED
    without a bare ``except Exception`` — which would launder
    programming bugs into capability verdicts.
```

## `tracks/t3-topology/dse/veritx_dse/backend/serving_round.py` :: `DpMemberRecord`

```text

    ``original_total_len`` is the member's real batch shape; ``padded``
    is the shape it actually executes after quorum padding.  ``is_dummy``
    is explicit -- it is never inferred from an empty request list.
```

## `tracks/t3-topology/dse/veritx_dse/backend/serving_round.py` :: `DpQuorumRecord`

```text

    ``dp_sum_total_len`` is deliberately ``max_total_len`` and NOT
    ``max_total_len * group_size`` -- that is the historical rule and the
    seam a later EP slice will read.
```

## `tracks/t3-topology/dse/veritx_dse/backend/serving_round.py` :: `ServingBatchPlan`

```text

    Deliberately free of physical placement: no endpoint ids, no ET paths, no
    BookSim configuration.  ``participant_ranks`` are *canonical* workload
    ranks; the canonical namespace owns rank -> endpoint.
```

## `tracks/t3-topology/dse/veritx_dse/backend/serving_round.py` :: `ServingRoundPlan`

```text

    This is a *container*, not a workload model.  Each instance keeps its own
    ``ServingBatchPlan`` -- its own ranks, phase, tokens, collective size and
    compute -- so independent TP groups never collapse into one collective.
```


# `backend` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/backend/astra.py` :: `declared_compute_cycles`

```text

        Rank-parallel owned compute must not be summed as if every rank ran
        every chain serially: a rank's chain is the global (unowned) compute
        plus the compute it owns, and the floor is the *maximum* chain.  With
        no owned compute this is exactly the historical
        ``sum(cycles) * 1000``.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra.py` :: `write_chakra`

```text

        Granularity is explicit (``et_granularity``):
          * ``messages``    - COMM_SEND/COMM_RECV per canonical logical
                              message; the Slice-29 schedule owns expansion.
          * ``collectives`` - COMM_COLL_NODE per collective operation,
                              delegating expansion to ASTRA.
        Either way this method never invents a second collective algorithm.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_adapter.py` :: `_require_collective_envelope`

```text

        COMPUTE, qualified COLLECTIVEs and truly zero-network operations
        pass. P2P requiring SEND/RECV, physical multicast and any other
        unsupported operation refuse with a typed refusal — never
        silently dropped to make a test pass.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_adapter.py` :: `execute`

```text

        Stages the real Chakra workload files itself
        (``run_dir/astra/workload/workload.<rank>.et`` translated into
        the endpoint namespace) and calls the existing
        ``execute_astra_machine`` — no new subprocess implementation.
        Returns the backend-native ``AstraRuntimeEvidence`` unchanged.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_execution.py` :: `assert_astra_gate`

```text

    The frontend instantiates one NPU per *fabric node*, so the runtime
    reports the canonical fabric's node count, not the workload's rank
    count.  Non-participant fabric nodes are therefore admitted — but only
    when they are provably idle, and they are returned so the evidence can
    declare them instead of hiding them.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_execution.py` :: `execute_astra_machine`

```text

    ``class_binding_id`` is the executed projection's deterministic
    operation->class binding (None = legacy single-class path); it is
    stamped into evidence so normalization can verify class attribution.
    ``expected_collective_kinds`` is the projected canonical kind set;
    when the runtime emits contract-ledger STREAM lines, the executed
    schedule must cover exactly that set (None = skip the check, never
    assume it).
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_machine.py` :: `MachineFieldOwner`

```text

    ``MAGIC`` does not exist: a field is either derived, profile-owned,
    runtime-required, or it is not rendered at all.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_machine.py` :: `embedded_fabric_config`

```text

    ``embedded_classes`` declares the embedded ``classes=`` envelope
    covering every canonical class id the workload will inject (the
    caller derives it from the collective-kind table). The standalone
    config pins ``classes`` only for multi-class profiles; the embedded
    runtime needs the envelope for every collective kind it attributes,
    so the machine declares it explicitly and asserts it into the
    rendered text — never inherited from a default of 1.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_machine.py` :: `fabric_node_count`

```text

    ``BookSim2Fabric::node_count()`` returns ``_tm->NumNodes()`` and the
    frontend builds one ``Sys`` per node, so the runtime namespace is the
    fabric node count -- *not* the number of attached agent endpoints and
    *not* "routers" in the AnyNet sense (where routers != nodes).  Derived
    from the canonical rendered BookSim projection, so there is still one
    topology authority.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_machine.py` :: `memory_scope`

```text

    Canonical memory timing is not reclaimed, so a workload that would
    exercise the analytical memory model is refused outright rather than
    measured with invented constants.  ``logical`` is the canonical
    ``LogicalMessageArtifactV2``: its operation kinds are the authority for
    whether any memory/PIM semantics are in play.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_machine.py` :: `physical_id`

```text

        ``machine_id`` folds in the projection that *qualified* the machine
        (workload id, payload bytes, compute floor), which is right for a
        one-shot qualification but wrong for a live service loop where every
        round has a different batch.  ``physical_id`` hashes only the
        workload-independent machine surface, so a stable machine can be
        re-used across rounds while each round carries its own qualified
        workload identity (see AstraServingRoundQualification).
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_machine.py` :: `qualify_astra_machine`

```text

    ``embedded_classes`` overrides the declared embedded ``classes=``
    envelope (callers whose workload outgrows the projection used for
    qualification — e.g. the serving loop, whose machine is qualified
    over a trivial collective while live rounds inject EP kinds —
    derive it from the kinds they can emit). None derives it from the
    projection's own collective operations.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_machine.py` :: `stage_workload`

```text

    The frontend resolves a rank's workload as ``<base>.<rank>.et`` and
    falls back to ``<base>`` when that file is absent — which would silently
    replicate the trace onto *every* fabric node, including the driver
    endpoint.  So every projected rank must have its own file, and the
    staged rank set is returned so the caller can assert it.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_namespace.py` :: `_translate_et`

```text

    Collective membership is resolved from the Chakra node's ``name`` -- the
    canonical *operation id* -- through the round's collective binding when
    one is supplied.  With several independent TP groups in one workload,
    inferring membership from the node's collective type would be a guess;
    the operation id is the fact.
```

## `tracks/t3-topology/dse/veritx_dse/backend/astra_namespace.py` :: `write_communicator_group_document`

```text

    ``groups`` may be the stable namespace's groups or a round's collective
    binding groups; only the membership document changes, never the fabric.

    ``replace`` is for a sequential round driver: rounds share one run
    directory and each round legitimately has different memberships, so the
    document must be replaced.  Without it a differing existing document
    still refuses, which is what catches inconsistent staging within a round.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim.py` :: `_run_qualified_booksim_with_runner_for_test`

```text

    Unit tests use this to exercise validation ordering, refusal paths
    and semantic classification without spawning BookSim. Products carry
    ``execution_transport=TEST_INJECTED`` and can NEVER pass
    ``verify_reusable_evidence`` — a fake runner that never executes the
    binary cannot fabricate reusable ``EXECUTED_*`` evidence.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim.py` :: `assert_canonical_booksim_projection`

```text

    A BackendConfigArtifact can be internally hash-consistent, bind the
    right fabric/resolved identities, and still not be the authorized
    lowering of that fabric (recomputed hash + forged parameters). This
    re-derives the expected artifact for the config's target/profile
    identity and requires complete canonical identity equality. Hash
    consistency alone is never accepted.

    Returns the freshly derived canonical artifact.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim.py` :: `execution_qualification`

```text

    Derived strictly from the bindings:
      * UNSUPPORTED_EXECUTION present  -> EXECUTION_UNSUPPORTED (refuse)
      * BLOCKS_EXACT_FABRIC present    -> EXECUTED_BLOCKED_FROM_EXACT
      * all exact/irrelevant           -> EXECUTED_EXACT
      * otherwise                      -> EXECUTED_WITH_DECLARED_LOSS
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim.py` :: `run_qualified_booksim`

```text

    This is the ONLY entry point that can emit reusable ``EXECUTED_*``
    evidence: it always spawns the identified BookSim binary through the
    supervised process runner. There is no runner parameter — injected
    transports live behind the explicitly test-only seam below, whose
    products the reuse API mechanically refuses.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_adapter.py` :: `_canonical_traffic`

```text

        The asserted class is the EVAL-TIME CONTRACT: a single-class
        caller MUST pass the lowered class (assertion, never a label);
        omitting it is a caller bug, not something to silently repair
        with the lowered value.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_adapter.py` :: `_check_booksim_evidence_binding`

```text

    Parents are never stamped from context blindly — a mismatch is
    evidence corruption, and normalizing another run's evidence under
    this run's identities would attach science to the wrong design.
    An absent binding identity is itself a refusal: an EVALUATED
    outcome without one is corrupt, never normalizable.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_adapter.py` :: `normalize_booksim_outcome`

```text

    Re-reads the persisted evidence document through the canonical
    reader, validates it and admits it for certified product use, then
    projects the envelope over the outcome's native numeric stats. Only
    an EVALUATED outcome normalizes; anything else is a caller bug.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `_cmesh_audit`

```text

    CMesh reads (networks/cmesh.cpp::_ComputeSize): ``k`` (side), ``n``
    (dimensionality, asserted <= 2), ``c`` (concentration, asserted == 4),
    ``x``/``y`` (topology extent, asserted equal), ``xr``/``yr``
    (concentration split, asserted xr*yr == c and xr == yr), plus
    ``use_noc_latency``. It shares the router/VC/traffic-manager surface
    with the mesh profile, so every row except the CMesh-specific ones is
    carried over verbatim from ``_mesh_audit`` — sharing tables would let
    one profile's pins vouch for the other's reads.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `_cmesh_expected_route_rows`

```text

    Delegates to `route_observation.expected_route_rows` — the one
    derivation authority — with the cmesh node -> router mapping. Every
    non-local hop is looked up as a real channel of the materialized
    artifact, so a route proof that does not cover this fabric refuses
    here rather than becoming an uncheckable expectation.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `_cmesh_node_to_router`

```text

    networks/cmesh.cpp::CMesh::NodeToRouter composes the node address from
    a 2k x 2k grid folded 2 x 2 onto each router (``_cX = _cY = 2`` for
    every certifiable geometry, because the fork asserts ``c == xr*yr``
    and ``xr == yr`` and ``c == 4``). Router ids are row-major
    ``y * k + x`` — the same numbering our materializer emits
    (coordinates ``(x, y)``). The returned mapping is the composition of
    exactly those two functions; it is never re-invented from counts.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `_flatfly_audit`

```text

    flatfly_onchip.cpp reads ``k`` (per-dimension size), ``n``
    (dimension count), ``c`` (concentration), ``x``/``y`` (extent,
    asserted equal), ``xr``/``yr`` (concentration split, asserted
    ``c == xr*yr`` and ``xr == yr``), ``use_noc_latency``. The v1 domain
    pins n = 2, c = 1 (so xr = yr = 1, x = y = k) with uniform
    latency 1 (use_noc_latency 0).
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `_mc_audit`

```text

    Everything is identical to the single-class mesh surface — same fork
    code paths, same router/VC/routing reads — except the class count is
    now derived from the workload (classes = len(trace_classes)), not
    pinned to 1. The fork's per-class replay filter (booksim2-fork/v2)
    is what makes that count semantically load-bearing.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `_mesh_dor_physical_gates`

```text

    Geometry, seats, route class, VC-routing-class mapping, latency,
    weight and parallelism — everything EXCEPT the traffic-class count
    law, the VC-envelope exactness law and the identity-transition law,
    which differ per envelope (deterministic DOR executes identity
    transitions over the full envelope; MIN_ADAPT executes the escape
    partition). Extracted verbatim; qualify_native_mesh_dor behavior is
    byte-identical.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `_min_adapt_audit`

```text

    Identical to the multi-class mesh surface (CANONICAL class count via
    the fork-v2 replay law) EXCEPT the route-dump row is absent entirely:
    the fork aborts deterministic first-hop dumps for candidate-set
    routing functions, so no dump path is rendered and no dump-based
    route comparison is claimed (observation-scope guard). Execution
    evidence is conservation + DOMAIN_QUALIFIED_ROUTE_NOT_OBSERVED.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `_torus_audit`

```text

    KNCube reads ``k`` (side), ``n`` (dimensionality, certified domain
    pins 2), ``use_noc_latency``. The pin is 0: the noc-latency path
    makes wraparound links latency 2 while canonical torus channels are
    latency 1, so the pin disables that path (mirroring the cmesh
    rationale) and the qualifier enforces uniform latency 1.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `qualify_anynet_min_hops`

```text

    The vendored ``AnyNet::route`` minimises the edge's COST token
    (``anynet.cpp``: ``dist[min_cand] + i->second[0].cost``); the link's
    latency is a pure wire delay and never enters the distance. VeritX
    pins ``cost = 1`` on every rendered link, so the executed routing is
    exactly min-hop with the fork's strict-``<``, ascending-map tie
    behaviour. A non-unit cost makes the two algorithms differ, so
    ANYNET_MIN_HOPS is NOT representable and we refuse rather than
    silently reinterpreting it as weighted shortest path. Per-link
    LATENCY may vary freely; only sub-cycle latency is refused.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `qualify_native_mesh_dor_mc`

```text

    Reuses every single-class mesh gate (geometry, seat capacity, DOR-XY
    route class, VC envelope, channel latency/weights, no parallel
    channels, identity VC transitions) and additionally requires the
    v2 fork injection law: the vendored fork's per-class replay filter
    (``TraceInjectionProcess`` class filter) is what executes a class
    count > 1 faithfully. Refusals name the real gate — never a
    silent class collapse.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `qualify_native_torus_dor`

```text

    1. family TORUS, square k x k, seat_capacity 1;
    2. endpoints dense 0..E-1 identity-prefix (KNCube node n <-> router n);
    3. route artifact realizes DOR_TORUS_XY, VCs bind DOR_TORUS_XY;
    4. unit channel latency/weight (use_noc_latency 0 makes every fork
       link latency 1); 5. no parallel channels; 6. single traffic class
    7. vc_count == 2 EXACTLY with identity transitions (the fork halves
       the range by dateline partition; any other count overlaps or
       starves a partition and is refused, never approximated).
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `select_booksim_profile`

```text

    Multi-class traffic on a mesh fabric routes to the multi-class
    profile — it executes the canonical classes as declared (fork v2
    per-class replay law) where the single-class profile would refuse.
    When all refuse, the native mesh-DOR reason leads the message: it is
    the profile this fabric was built for (mesh + DOR_XY), so its refusal
    names the real gap; the other refusals are fallback notes, never the
    headline that hides the operative cause.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `trace_class_map`

```text

    The fork's trace dialect is ``cyc src cl dst sz``; its class column is
    a small integer. Canonical class NAMES are mapped to indices by
    sorted order — deterministic, artifact-derived, and bound into
    prepared-input identity (``trace_class_map``) so a mapping change is
    never invisible. Single-class traffic yields ``(class,)`` and renders
    index 0, byte-identical to the pre-multi-class renderer.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `trace_injection_horizon`

```text

    A source port injects at most one flit per cycle (BookSim's default
    injection bandwidth), so a packet scheduled at cycle ``t`` with ``f``
    flits cannot begin before the source has finished its earlier packets.
    Returns the cycle the last flit enters the network, i.e. an exclusive
    finish time ``>= max_timestamp + 1``.
```

## `tracks/t3-topology/dse/veritx_dse/backend/booksim_projection.py` :: `trace_schedule`

```text

    Timestamps are PROJECTION-DEFINED emission order (0, 1, 2, ...), not
    application wall-clock scheduling: BookSim completion time measured
    under this schedule is the completion time of the canonical network
    traffic projection, and must never be reported as end-to-end workload
    runtime. The convergence window is the per-source injection horizon
    plus a fixed drain margin (F-0007).
```

## `tracks/t3-topology/dse/veritx_dse/backend/canonical_serving.py` :: `attribute_completions`

```text

    Slice 34 showed backend output mixes global and endpoint-specific
    information with different semantics, so a single leading completion
    line must never be read as "sys 0 owns the work".  A completion retires
    work only for the instance that owns that endpoint, and only when that
    instance actually had a batch dispatched.
```

## `tracks/t3-topology/dse/veritx_dse/backend/canonical_serving.py` :: `startup_workload_path`

```text

        It deliberately has **no** per-rank ET files, so every ``Sys`` starts
        idle and the real round is delivered later by ``load``/``run``.  This
        matters: ``CollectiveImplLookup`` is stateful per process, so running
        the same ET twice in one backend (startup + re-load) is not the
        supported path.
```

## `tracks/t3-topology/dse/veritx_dse/backend/contracts.py` :: `RepresentationStatus`

```text

    Non-exact statuses must state the reason; the certification effect is
    stored explicitly (and consistency-checked), never silently inferred.
```

## `tracks/t3-topology/dse/veritx_dse/backend/contracts.py` :: `SemanticDimension`

```text

    Extend only when source inspection proves a new identity-bearing
    fabric semantic exists; never silently drop one.
```

## `tracks/t3-topology/dse/veritx_dse/backend/contracts.py` :: `_FrozenMap`

```text

    A distinct type keeps ``{"a": 1}`` unambiguous from ``[["a", 1]]``
    when converting back to JSON; plain tuples are lists.
```

## `tracks/t3-topology/dse/veritx_dse/backend/contracts.py` :: `exact_fabric_eligible`

```text

        COARSENED / ASSUMED_FIXED / UNREPRESENTABLE bindings make this
        False even when the run itself is permitted (FIDELITY_DOWNGRADE):
        a downgraded run must never present itself as an exact-fabric
        result.
```

## `tracks/t3-topology/dse/veritx_dse/backend/evidence.py` :: `ExecutionAttemptRef`

```text

    Deliberately NOT an ``EvidenceRef``: an attempt record authenticates
    nothing scientific and must never be passed to evidence-reuse APIs.
```

## `tracks/t3-topology/dse/veritx_dse/backend/evidence.py` :: `_validate_legacy_v1`

```text

    The old consumers checked only the binding keys they needed and
    treated every other field as informational, so this preserves that
    permissiveness: require the minimum evidence keys, accept and return
    the historical extras unchanged. The v1 producer acceptance
    semantics (including ``producer_tool_identity``) live in the reuse
    binding, not here.
```

## `tracks/t3-topology/dse/veritx_dse/backend/evidence.py` :: `admit_normalize_evidence`

```text

    A normalize step must never reuse a naked path: the file bytes are
    digested into an ``EvidenceRef`` first (a copy dropped into another
    run directory carries bytes the caller's binding does not name, and
    refuses at the preparation check), then the document passes the
    canonical validation, certified admission and preparation binding.
    This is the ``read_reusable_record`` discipline for callers that
    hold a path rather than a ref.
```

## `tracks/t3-topology/dse/veritx_dse/backend/evidence.py` :: `from_dict`

```text

        Closed field set (exactly what to_dict emits — no extras, no
        missing keys), type-tag and schema-version pinned, and the
        embedded evidence_id must equal the recomputed one: a forged or
        transplanted document cannot pass. This is the read half of the
        write/read contract validate_evidence_document enforces.
```

## `tracks/t3-topology/dse/veritx_dse/backend/evidence.py` :: `from_verified_evidence`

```text

        The document must already have passed ``read_verified_evidence``
        AND ``validate_evidence_document``: only then can the ref digest
        be trusted as the raw-bytes identity and the fields be read as
        the declared generation's contract. ``parser_version`` is stamped
        from the document when the producer wrote one; historical
        documents predate versioning and get the legacy tag, so a
        different reader is a different claim.
```

## `tracks/t3-topology/dse/veritx_dse/backend/evidence.py` :: `require_hex64`

```text

    Slice-31 prepared-input identities use ``content_hash`` (prefixed);
    evidence digests are bare. Both are the same digest.

    Returns the value UNCHANGED: evidence identity is computed over the
    stored forms, so admission must never rewrite them. Use
    ``canonical_hex64`` when comparing identities across documents.
```

## `tracks/t3-topology/dse/veritx_dse/backend/meshdor.py` :: `_execute_prepared_meshdor`

```text

    Same order and same fail-closed discipline as the sealed AnyNet
    core: revalidate -> canonical config -> canonical prepared inputs
    -> qualification guard -> producer identity (pre-spawn digest) ->
    materialize -> mesh shape verification -> pre-spawn hash
    re-verification -> mesh profile gates -> fresh route-output slot ->
    producer recheck -> run -> executed-route proof -> parse stats.
```

## `tracks/t3-topology/dse/veritx_dse/backend/meshdor.py` :: `_mesh_attachment`

```text

    derive_attachment fills router-id-ordered seats from the canonical
    inventory order, so endpoint i -> router i for every attached
    endpoint. A permuted (or sparse) attachment would silently relabel
    the native node universe, so anything else refuses here — the
    renderer never remaps endpoint ids to node ids.
```

## `tracks/t3-topology/dse/veritx_dse/backend/meshdor.py` :: `verify_mesh_projection`

```text

    k/n travel as config VALUES (not a parsed file), so the spawn-time
    proof re-derives them from the artifact and compares. Behavioral
    equivalence is proven per run by the executed route dump; this
    proves the shape claim the dump executes under.
```

## `tracks/t3-topology/dse/veritx_dse/backend/meshdor_profile.py` :: `_mesh_audit`

```text

    - `network_file` is dead under native mesh (no AnyNet file exists);
      it leaves the active set (its read site stays declared below).
    - `topology` pins `mesh`.
    - `k`, `n`, `use_noc_latency` become live reads with explicit owners
      (fabric-derived shape; pinned backend constant).
    Every other row is shared unchanged (same Router/VC/flow/traffic-
    manager code runs under both topologies).
```

## `tracks/t3-topology/dse/veritx_dse/backend/normalized_evidence.py` :: `assert_envelope_matches_native`

```text

    The envelope must name the native evidence id it was projected
    from; every metric carrying a ``source_metric_key`` must equal the
    native stat it claims to project (no swapped run-B numbers under a
    run-A id); the canonical parents must include the native binding
    identities; qualification and producer identity must be the native
    verdicts, not re-stated claims. Metrics without a source key are
    derived quantities and are not value-checked here.
```

## `tracks/t3-topology/dse/veritx_dse/backend/producer.py` :: `resolve_producer_identity`

```text

    A verified build-time manifest is authoritative: it names the source
    revision and dirty state observed when the binary was built, so a
    binary built at A stays attributed to A even after the tree is
    checked out at B. With no manifest, only ambient git state is
    available and ``manifest_verified`` stays False, so the producer can
    never be pinned for reusable evidence.
```

## `tracks/t3-topology/dse/veritx_dse/backend/projection.py` :: `render_waved_trace`

```text

    The fork's cycle-accurate injection path (veritx_ext.cpp
    TraceTrafficPattern) parses the WHITESPACE dialect
    ``cyc src cl dst sz`` — one line per physical packet, packet size in
    FLITS (trafficmanager.cpp: "trace size is in flits"). The class
    column is 0: single-class certified runs (§21). Deterministic
    timestamps in emission order keep packet ordering semantic.
```

## `tracks/t3-topology/dse/veritx_dse/backend/projection.py` :: `verify_trace_projection`

```text

    Parses back the rendered trace and compares it against the artifact:
    line count, endpoint pairs, per-line flit counts, and ordering.

    Owned by the renderer, not by verification: it needs the trace
    grammar and the scanner, both of which live in the backend. The
    reference differentials live in verification/reference_semantics.py.
```

## `tracks/t3-topology/dse/veritx_dse/backend/qualification.py` :: `booksim_shared_realization`

```text

    Starts from the artifact's full normalized projection (which includes
    the explicit BACKEND_PROFILE pins, not only fabric-derived values) and
    removes only the closed, reviewed target-specific executions:
    traffic source, sample window, seed, and the route-dump evidence path.
    Anything that can change routing, buffering, arbitration, flow
    control, pipeline timing, channel behavior or packet handling stays
    in the comparison.
```

## `tracks/t3-topology/dse/veritx_dse/backend/qualification.py` :: `qualify_cross_backend`

```text

    Canonical lowering is checked FIRST for every BookSim target: an
    artifact that recomputed its own hash but is not the canonical
    lowering of ``bundle`` is refused before authority or realization
    comparison, so two equally forged artifacts cannot agree their way
    to validity. Analytical canonical re-lowering is out of scope (no
    graph authority exists); their identity checks are structural only.
```

## `tracks/t3-topology/dse/veritx_dse/backend/ramulator_adapter.py` :: `execute`

```text

        Writes ``run_dir/ramulator/``: the trace, its manifest, the
        memory artifact and the native evidence document — then runs the
        one audited subprocess path (``simulation.ramulator.execute``).
        No alternative subprocess runner exists. Returns the
        backend-native ``MemoryEvidence`` unchanged.
```

## `tracks/t3-topology/dse/veritx_dse/backend/ramulator_adapter.py` :: `ramulator_evidence_id`

```text

    Hashes the scientific fields only: status, producer, fidelity, the
    four hash links, metrics EXCEPT wall_time_s (nondeterministic across
    repeat runs — a repeat execution must reproduce the same identity),
    assumptions, semantic losses and the failure reason. ``raw`` is
    excluded: it carries host run paths, never science.
```

## `tracks/t3-topology/dse/veritx_dse/backend/reproduce.py` :: `_admitted_evidence`

```text

    The file bytes are digested first: a document copied in from another
    run, or edited after finalization, carries bytes the bundle never
    sealed and refuses here (bundle verification already guards the
    sealed bytes; this guards the read). The admitted document must
    then pass generation validation and certified-product admission, so
    diagnostic, test-injected, dirty-producer or unmanifested bundles
    refuse before any reproduction runs.
```

## `tracks/t3-topology/dse/veritx_dse/backend/reproduce.py` :: `_canonical_stats`

```text

    Parsed stats use int keys (``flits_by_class: {0: ...}``) while the
    persisted JSON round-trip turns them into strings. Comparing raw
    would false-diverge on every reproduction with class counters.
    Canonicalizing both sides to string keys compares the science, not
    the serialization accident.
```

## `tracks/t3-topology/dse/veritx_dse/backend/reproduce.py` :: `_pinned_binary`

```text

    The attempt-recorded path is untrusted until proven: the candidate
    binary's bytes must hash to the evidence ``binary_sha256``, and its
    adjacent build manifest must verify and be the exact manifest the
    evidence was qualified against (``build_manifest_sha256`` over the
    manifest file bytes, plus matching binary digest and size). A
    swapped binary — or a binary whose manifest cannot be proven —
    refuses instead of producing a "matched" reproduction.
```

## `tracks/t3-topology/dse/veritx_dse/backend/route_observation.py` :: `expected_route_rows`

```text

    ``node_to_router`` is the execution node universe: mesh-DOR addresses
    every router as a node (node n -> router n); AnyNet addresses the
    attached endpoint nodes (node e -> its router). Derived only from the
    sealed canonical artifacts, never from a simulator. Refuses if the
    route artifact does not cover a required (class, src, dst) pair — a
    route proof that does not cover the fabric must not silently become an
    observation expectation.
```

## `tracks/t3-topology/dse/veritx_dse/backend/serving_round.py` :: `CollectiveContract`

```text

    Keyed by the ASTRA node id, so two collectives that share a kind and byte
    size but differ in membership stay distinguishable.
```

## `tracks/t3-topology/dse/veritx_dse/backend/serving_round.py` :: `plan_from_round`

```text

    A certified round carries one communicator group, so it spans the full
    participant set; ``batches`` maps serving instance -> real ``Batch``.
    Only fields a real batch owns are read.  The phase is prefill if *any*
    instance is prefilling, because the round's collective is one workload
    and a mixed round must not be labelled decode.

    ``instance_id = -1`` marks a round that belongs to no single instance;
    the plan identity still binds every contributing batch id and request id.
```

## `tracks/t3-topology/dse/veritx_dse/backend/serving_round.py` :: `plan_from_round`

```text

    Only fields a real batch owns are read from it (id, requests, total_len,
    prefill/decode).  The declared profile values are computed per batch --
    never over an aggregate token count -- and, for DP members, only AFTER
    quorum padding, so ``batch.total_len`` here is the *executed* shape.

    ``dummy_instances`` names the members whose batch is an explicit DP dummy:
    an empty request list is accepted for those and refused for everyone else,
    so an arbitrary empty batch can never masquerade as DP participation.
```

## `tracks/t3-topology/dse/veritx_dse/backend/serving_round.py` :: `to_workload_graph`

```text

        The collective is expressed as *intent* with its participant set -- it
        is never expanded into ring messages here.  In EP mode the batch
        lowers to dispatch ALLGATHER + per-rank expert compute + combine
        REDUCESCATTER, exactly as LLMServingSim emits (TP/EP overlap, no
        rank multiplication).
```

## `tracks/t3-topology/dse/veritx_dse/backend/serving_round.py` :: `to_workload_graph`

```text

        The graph's participant namespace is the whole serving namespace, so
        operation participant sets stay explicit: a TP group of two ranks in
        an eight-rank namespace is legal without inventing a DP axis.
        EP batches lower to dispatch + expert compute + combine over the
        same ranks (no rank multiplication).
```

## `tracks/t3-topology/dse/veritx_dse/backend/source_audit.py` :: `GatedReadSite`

```text

    ``gates`` is site-specific: a site must not inherit a gate that
    justifies a different site of the same field.
```

## `tracks/t3-topology/dse/veritx_dse/backend/source_audit.py` :: `audit_profile_reads`

```text

    ``strict`` refuses when a field the profile EMITS is not read by the
    fork at all: that is the drift that silently voids a certified
    projection. Fields the fork reads but the profile does not declare
    are reported (they are gated/inactive by construction) and are not
    fatal unless ``strict`` and the field is in the profile's rendered
    set.
```
