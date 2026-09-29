# `model` — extracted module rationale

Extracted from the module docstrings of `veritx_dse/{name}` by the 2026-09-29 debloat. Code keeps a one-line pointer; this is the original long-form text.

## `tracks/t3-topology/dse/veritx_dse/model/address_decode.py`

```text
veritx_dse.model.address_decode — canonical NI address-decode semantics.

``AddressDecodeArtifact`` is the exact authority mapping customer/system
address ranges to canonical fabric endpoint ids:

    system address range -> canonical destination endpoint

The decoder runs before network injection. It selects the canonical
destination endpoint encoded by the Slice-17 ``PacketFormatArtifact``. The
original protocol address itself remains payload/protocol data and is
forwarded unchanged; addresses do NOT enter the NoC flit header.

Its only hardware parent is ``AgentAttachmentArtifact``: the attachment
already carries canonical endpoint identity and endpoint interface
semantics (address width). Topology, mapping, node inventory, design hash,
packet format, route/relation, VC resources and router behavior do not
participate.

Schema v3 is intentionally new. Historical schema v1 hashed the
non-semantic range name and left forwarding implicit; historical schema v2
used the pre-consolidation identity implementation and historical parent
identities. Canonical v3 uses Slice-1 ``content_id`` with domain
``srota/AddressDecodeArtifact/v3``; historical hashes are not reproduced.

    AddressDecodeEntry (transported)
        name                    NON-SEMANTIC presentation/trace label
        base
        size
        target_agent_group
        target_endpoint_id

Hardware identity per entry is exactly
``(base, size, target_agent_group, target_endpoint_id)``. ``name``
round-trips for diagnostics but is excluded from the hash, so renaming a
range does not move hardware identity.

``address_transform = IDENTITY`` pins forwarding semantics: the decoder
selects the endpoint and the original address value is forwarded
unchanged. There is no base subtraction, modulo, aliasing,
hash/interleave, translation, truncation or remapping.

``unmatched_address_policy = ERROR``: unmatched addresses are never
silently routed anywhere.

Because forwarding is IDENTITY, an entry must fit the target endpoint's
declared address interface:
``base + size <= 2 ** endpoint.interface.address_width_bits`` (and inside
the global 64-bit system-address domain). No truncation or hidden width
adapter exists.

A range is executable only when its target Agent group contains exactly one
hardware instance. The current design model has no semantics defining how a
range is distributed across multiple instances, so singleton target groups
are the only exact interpretation; multi-instance targets fail closed with
UNSUPPORTED rather than inventing striping, round-robin, channel selection,
hashing or address-bit interleave.
```

## `tracks/t3-topology/dse/veritx_dse/model/attachment.py`

```text
veritx_dse.model.attachment — AgentAttachmentArtifact (B3.1, B3.1c, B3.1d).

B2 stops at LogicalRank -> AgentInstance. B3 owns the next relationship:

    AgentInstance -> Endpoint (fabric-addressable attachment) -> RouterPort

Every hardware AgentInstance attaches, compute or not, including idle
compute instances — an active LogicalRank is not required to attach an
agent. Endpoint ids are canonical fabric attachment ids assigned densely
in (router_id, port_id) order; AddressRange.target_agent_idx identifies
an Agent group and does NOT assign endpoint ids (§8).

Interface authority (B3.1c):

    AgentInterfaceDescriptor
        data_width_bits
        address_width_bits
        protocol
        clock_domain
        power_domain

endpoints carry the immutable interface semantics of the Agent group they
were derived from.

Identity boundary (B3.1d). The attachment's ONLY semantic parent is

    topology_hash

because the endpoints reference router/port seat identities from the
TopologyArtifact. DesignRevision and NodeInventory are the derivation and
validation SOURCES, and MappingArtifact is a downstream seam concern — none
of them enter attachment identity:

    fabric_hash       = identity of the resolved hardware fabric
    resolved_fabric   = design_hash + mapping_hash + fabric_hash

so the same hardware fabric under a different workload mapping must keep
the same attachment_hash (and later fabric_hash). Copying the interface
descriptor into the artifact is what lets design-derived hardware
semantics propagate WITHOUT hashing the entire design; an unrelated design
change (batch size, requirement, output format) must not change hardware
identity.

Validation (B3.1d) proves the complete agent universe:

    expected = {(group_index, instance_index, group.kind)
                for every group in design.agents
                for every instance in range(group.count)}

    inventory agents == expected      (no missing, no extra)
    attachment endpoints == expected  (no missing, no extra, no duplicates)

plus per-endpoint group bounds, kind agreement, interface equality with
the parent group, real router seats, and at-most-once seat occupancy.
Every hardware agent attaches — not only agents that currently host a
logical rank. Mapping placement legality is a ResolvedFabric seam check,
not an attachment identity rule.

Schema v1 and v2 attachments are refused on load: v1 has no interface
descriptor; v2 polluted identity with design/mapping hashes. Neither is
silently converted to v3.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py`

```text
veritx_dse.compile_model — Srota Engine compile data model (E1–E5).

Implements the PRD §11.1 data model with guardrails enforced by type
system (§11.2). LOCKED parameters have no field in NocConfig — the
override is inexpressible, not merely refused.

Design principles (from PRD §3):
  - Derive, don't ask: VC count derived from dependency graph
  - Guardrails visible: Tier enum with badge strings
  - Type-system enforcement: frozen dataclasses, absent LOCKED fields

Architecture:
  CompileRequest (E1–E5 unified)
  ├── Workload (E1): model family, parallelism, trace binding
  ├── Requirements (E2): per-class latency/BW bounds
  ├── Agents (E3): typed nodes with attributes
  ├── DependencyGraph (E4): blocking/ordering → VC derivation
  └── NocConfig (E5): GUIDED + FREE fields only (no LOCKED)
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_request_v4.py`

```text
compile_request_v4 — the v4 fabric intent root.

WHY A NEW GENERATION
====================

Schema 3 / compiler semantics 3 are RELEASED semantic authorities. PHASE B
originally added typed topology intent to `CompileRequestV3` directly, which
expanded schema 3 IN PLACE: schema-3 readers that used to refuse a typed
intent would accept one. Two binaries reading the same "v3" document would
then disagree about what v3 means.

So the new fabric semantics get a new generation:

    V2 IS FROZEN.  V3 IS FROZEN.  NEW FABRIC SEMANTICS REQUIRE V4.

WHAT CHANGES IN V4
==================

ONE topology authority. v3 had `noc_config.topology_family` XOR
`explicit_topology`, and `topology_family=None` IMPLICITLY meant mesh. v4 has
a single `topology: TopologyIntent` field that is REQUIRED and always
explicit:

  * there is no "None means mesh" in the v4 persisted schema — implicit mesh
    is a LEGACY meaning and is handled only in migration;
  * an explicit graph is an `ExplicitTopologyIntent(graph=TopologyIR)`, so
    two topology authorities cannot even be expressed;
  * `NocConfig` is replaced by `NocControls`, which may not describe topology
    shape at all.

NEW HASH DOMAIN. `_HASH_TYPE_TAG_V4` plus `schema_version=4` /
`compiler_semantics_version=4` domain-separate the envelope, so a v3 and a
v4 document can never share an identity by construction — including the
migrated pair, which is the point: the same science expressed in two
generations is deliberately NOT the same design identity.
```

## `tracks/t3-topology/dse/veritx_dse/model/fabric_artifact.py`

```text
veritx_dse.model.fabric_artifact — canonical hardware fabric identity.

``FabricArtifact`` is the single content-addressed root of one fully
resolved NoC/NI **hardware** fabric. It is composition only: it owns no
derivation algorithm and embeds no child artifact bodies. Its children are
already-resolved semantic authorities:

    TopologyArtifact
    AgentAttachmentArtifact
    VCResourceArtifact
    RoutingRealizationArtifact
    PacketFormatArtifact
    RouterBehaviorArtifact
    AddressDecodeArtifact
            |
            v
       FabricArtifact

It works identically for deterministic and adaptive routing: routing
internals are hidden behind ``routing_realization_hash`` and no
route-policy-specific field appears here.

Fabric identity answers only "is this the same hardware fabric?". It
deliberately excludes design intent, rank placement, node inventory,
verification certificates, backend configuration, runs, seeds and
provenance. Two designs that resolve to the same hardware share a fabric.

Schema v1 supports exactly one semantic plane (``PlaneComposition``).
Multi-plane hardware, clock-domain crossing and power-domain crossing are
explicitly unmodelled: they fail closed rather than being approximated.
```

## `tracks/t3-topology/dse/veritx_dse/model/generation.py`

```text
generation — which design-request generation an object is.

WHY THIS EXISTS
===============

The compiler has ONE derivation engine that serves every generation of design
request. Gates that used to ask `isinstance(design, CompileRequest)` or
`isinstance(design, (CompileRequest, CompileRequestV3))` therefore had to grow
a third disjunct every time a generation was added, and a missed one showed up
as a confusing downstream AttributeError rather than a clear refusal.

This module answers the question ONCE:

    v2  CompileRequest        schema 2, compiler semantics 1/2
    v3  CompileRequestV3      schema 3, compiler semantics 3
    v4  CompileRequestV4      schema 4, compiler semantics 4

The check is by SHAPE for v4 (schema_version + the v4-only `noc_controls`)
because importing `CompileRequestV4` into every consumer would create import
cycles for no benefit. The v2/v3 checks stay isinstance checks against the
frozen classes.

THIS IS NOT A SEMANTIC BRIDGE. It answers "can the shared engine consume
this?" — never "is this design equivalent to that one?".
```

## `tracks/t3-topology/dse/veritx_dse/model/mapping.py`

```text
veritx_dse.model.mapping — MappingArtifact (Wave B2).

A workload's tp/pp/ep/dp counts do not say WHICH hardware agent each
rank runs on. Two runs with swapped per-rank placement share a rank
multiset but execute different work on different agents; they are not
equivalent.

MappingArtifact answers exactly one question:

    which hardware AgentInstance hosts each logical workload rank?

It does NOT answer which endpoint or router that agent attaches to —
that is a B3 fabric relationship, and no fabric field is representable
here. The artifact is derived (never hand-authored for the baseline
path), content-addressed, schema-versioned, and fails closed.
```

## `tracks/t3-topology/dse/veritx_dse/model/noc_controls.py`

```text
noc_controls — the topology-INDEPENDENT NoC controls (v4).

WHY THIS EXISTS
===============

`NocConfig` mixed two different things:

  * TOPOLOGY SHAPE  — `topology_family`, `radix`, `concentration`. What the
    physical fabric IS.
  * NoC CONTROLS    — arbitration, RCU, link width, multicast engine limits,
    output formats, obfuscation. How the fabric is CONTROLLED, independent of
    its shape.

Keeping them in one bag is why a mesh-shaped vocabulary leaked into families
that are not meshes. v4 splits them:

    topology shape  ->  TopologyIntent   (model/topology_intent.py)
    NoC controls    ->  NocControls      (this module)

THE SPLIT IS A LAW, NOT A PREFERENCE
====================================

Nothing here may describe topology shape. `radix`, `concentration`,
dimensions and GEC channel structure belong exclusively to topology intent,
and a test pins that: if a field name here starts describing shape, the split
has regressed.

`NocConfig` is NOT mutated. It stays exactly as it is so that schema 2 and
schema 3 keep meaning what they meant; v4 reads it only through migration.

LOCKED CONTROLS STAY UNEXPRESSIBLE
==================================

`NocConfig` deliberately has no field for `routing_function`,
`turn_restrictions` or `vc_map`, because those are DERIVED from the
dependency graph and the topology. That discipline is preserved here: this
type has no field for them either. An override is not something the compiler
refuses — it is something that cannot be expressed.
```

## `tracks/t3-topology/dse/veritx_dse/model/packet_format.py`

```text
veritx_dse.model.packet_format — canonical routing-independent flit format.

``PacketFormatArtifact`` is the sole authority for what bits cross a NoC
link and how a bounded network packet is delimited. It does not route, does
not assign VCs, and carries no protocol metadata.

Parents are physical/semantic only:

    TopologyArtifact        -> physical channel beat width
    AgentAttachmentArtifact -> endpoint namespace
    VCResourceArtifact      -> concrete VC universe

The historical packet format was parented to ``VCAssignmentArtifact``. Schema
v2 deliberately replaces that routing-specific parent with
``VCResourceArtifact``: a flit must represent the concrete VC universe, not
whether those VCs belong to DOR classes, MinAdapt roles, Valiant phases or
anything else. The hash domain is therefore ``srota/PacketFormatArtifact/v2``
and historical packet-format hashes are intentionally not reproduced.

Canonical v2 wire fields, least-significant to most-significant:

    payload | source_endpoint | destination_endpoint | flit_type | vc_id

with ``endpoint_width = max(1, ceil(log2(endpoint_count)))``,
``vc_width = max(1, ceil(log2(vc_count)))`` and ``flit_type_width = 2``.
Schema v2 owns exactly one layout; user-defined field ordering is refused.
The layout is re-derived from the parents during ``validate_against``, so a
self-consistent but non-canonical layout cannot validate.

``vc_id`` is HOP_LOCAL: a legal VC transition rewrites only that field.
Traffic class, routing class, routing role, escape/phase semantics, QoS and
multicast are not wire fields.
```

## `tracks/t3-topology/dse/veritx_dse/model/parallelism.py`

```text
veritx_dse.model.parallelism — ParallelismArtifact (D1, §4/§5/§7/§8/§9).

One immutable, strict, versioned Wave-D authority for rank-space
geometry. Identity covers exactly (schema_version, tp, pp, ep, dp):

    parallelism_id = H("srota/WavedParallelism", v, TP, PP, EP, DP)

``world_size`` is DERIVED (R = TP·PP·EP·DP) and is never an independent
identity field: two artifacts with the same four dimensions are the same
geometry, whatever integer they were constructed from.

Group derivation is total and law-checked (§9): for every family every
rank appears in exactly one group, groups are disjoint, and
Σ group sizes = R. The "PP family" is stages, not collectives: a stage
holds all ranks with one pp index.
```

## `tracks/t3-topology/dse/veritx_dse/model/placement.py`

```text
veritx_dse.model.placement — node semantics (Wave B2).

"node" was overloaded: a Workload rank, a CompileRequest agent, a BookSim
node, and an RTL router are four different objects. Sizing a fabric off
the wrong one is exactly how a 4-active-rank workload came to share a
name with a 64-router fabric.

This module names the universes:

    AgentGroup (Agent: kind, count)
        ↓ expand
    AgentInstance            — one hardware agent, globally unambiguous
    LogicalRank              — one model rank, as 4D parallel coords
    NodeInventory            — the explicit counts, never one integer

A B2 MappingArtifact binds LogicalRank → AgentInstance only. Fabric
attachment (agent → endpoint → router) is a B3 relationship and is
deliberately absent here.

Canonical design-rank ordering: tp varies fastest, then ep, then dp,
then pp slowest. This defines the Srota DESIGN rank namespace only. It
does NOT yet prove that a trace rank, an ASTRA rank, or an LLMServingSim
rank uses the same assignment — that executed-rank equivalence belongs to
backend workload lowering.
```

## `tracks/t3-topology/dse/veritx_dse/model/presets.py`

```text
veritx_dse.presets — Topology definitions and presets.

Single source of truth for all topology configs. Adding a new topology
means adding one Topology instance here — no other file needs changes.
```

## `tracks/t3-topology/dse/veritx_dse/model/resolved_bundle.py`

```text
veritx_dse.model.resolved_bundle — ResolvedFabricBundle (B3.7a).

A lowerer must receive the ACTUAL semantic objects needed to revalidate
the DAG — never a root hash alone. Because ResolvedFabric stores only
(design_hash, mapping_hash, fabric_hash), proving its binding requires the
design revision, inventory and mapping objects too; the bundle carries
them all.

Constructing a bundle already validates; ``revalidate()`` re-runs the two
root seams immediately before lowering so a caller cannot lower from a
bundle assembled around a stale/tampered child.

    fabrication.validate_against(all children)          (hardware DAG)
    resolved_fabric.validate_against(design, inventory, mapping, ..., fabric)
                                                        (design/mapping seam)

There is deliberately no persisted "bundle artifact": the bundle is an
in-memory proof carrier, and every child is separately content-addressed.
```

## `tracks/t3-topology/dse/veritx_dse/model/resolved_fabric.py`

```text
veritx_dse.model.resolved_fabric — design/mapping -> hardware seam.

``ResolvedFabric`` answers exactly one question:

    Does this exact CompileRequest + NodeInventory + MappingArtifact
    resolve to this exact FabricArtifact?

It derives nothing. It binds already-resolved design intent, logical
rank/inventory geometry, rank->agent mapping, and canonical hardware
fabric, and it owns the design-level unsupported-intent policy.

Identity is:

    resolved_fabric_hash = content_id(
        "srota/ResolvedFabric/v1",
        {type, schema_version, design_hash, mapping_hash, fabric_hash})

NodeInventory participates in validation but is deliberately NOT
independently identity-bearing: it is a derivation/validation source whose
geometry is recomputed and checked against the design, exactly as it was
historically. Every hardware child (topology, attachment, VC resource,
routing realization, packet format, router behavior, address decode, plane
composition) is transitively bound through ``fabric_hash`` and is
deliberately not repeated here.

TERMINOLOGY (pinned):

    "resolved" means structurally and semantically bound.
    It does NOT mean verified, qualified, backend-executable, or
    meeting latency/bandwidth/area/power requirements.

High-level performance/area/power ``Requirement`` objects remain outside
resolved hardware identity; a structurally resolved fabric may still fail
them later. Verification certificates and backend qualification are
likewise outside this artifact.
```

## `tracks/t3-topology/dse/veritx_dse/model/resolved_route.py`

```text
veritx_dse.model.resolved_route — endpoint-resolved routing identity.

A router-level route table is not a fabric routing truth: it says how
traffic moves between ROUTERS, while a fabric is routed between ENDPOINTS
whose attachment to routers is a separate artifact.

    TopologyArtifact ──► RouteArtifact (class-aware, exact channels)
            │                     │
            ▼                     ▼
    AgentAttachmentArtifact ──► ResolvedRouteArtifact
                                      │
                                      ▼
                              VCAssignmentArtifact (later)

ResolvedRouteArtifact binds exactly those three parents and owns the
endpoint interpretation:

  * endpoint → router mapping, copied from the attachment;
  * the routing-class axis, in the parent route's exact order;
  * an expanded endpoint route-table digest covering every
    (endpoint_src, endpoint_dst, routing_class) row with the exact first
    network channel selected by the class-specific router table;
  * LOCAL_EJECTION for endpoint pairs sharing a router: local traffic
    takes no network hop and no channel is fabricated.

The expanded table itself is not stored. The compact digest plus
deterministic re-derivation from the three parents is sufficient, and
validate_against() recomputes the digest, so a fabricated endpoint-table
hash cannot pass.

Identity vs transport: ``resolved_route_hash()`` covers the semantic fields
including ``endpoint_route_table_hash``. ``validate_against()`` proves the
parents accept each other and that the digest really is the expansion of
their entries. Schema v1 (classless next-router expansion) is refused on
the authoritative path; there is no migration here.
```

## `tracks/t3-topology/dse/veritx_dse/model/router_behavior.py`

```text
veritx_dse.model.router_behavior — canonical router microarchitecture.

``RouterBehaviorArtifact`` is the sole authority for **how a router behaves**
independent of any routing algorithm, RTL or simulator implementation: what
it buffers, how credits are interpreted, how output VCs are selected and
reused, how the switch is arbitrated, and what pipeline latency the
architecture has.

Its sole semantic parent is ``VCResourceArtifact``: the concrete VC universe
with traffic eligibility and the legal ``vc_in -> vc_out`` transition
relation. Router behavior knows how to handle whatever VC structure it is
given, without knowing a topology, wire format, route table, routing class,
routing role or backend. The same behavior may therefore be reused by
deterministic and adaptive routing systems that share the same concrete VC
resources.

It does NOT own:

    route tables or routing classes      (RouteArtifact)
    resolved endpoints                   (ResolvedRouteArtifact)
    VC ids or legal transitions          (VCResourceArtifact)
    packet bit positions                 (PacketFormatArtifact)
    routing candidate/priority semantics (RoutingPolicyDefinition,
                                          RoutingRelationArtifact)
    routing role->resource binding       (RoutingResourceBindingArtifact)
    channel/link latency                 (TopologyArtifact)
    backend sampling/seed knobs          (backend layer)

Hash domain is ``srota/RouterBehaviorArtifact/v3``. The version is
intentionally new: historical schema v1 conflated switch arbitration with
input-VC packet context (``packet_hold_policy``), and historical schema v2
was parented to the routing-specific ``VCAssignmentArtifact``. Canonical v3
binds the routing-independent ``VCResourceArtifact``. Historical
router-behavior hashes are deliberately not reproduced.

Three independent packet/switch semantics:

    hold_switch_for_packet = False
        the physical switch/crossbar is arbitrated per flit; a packet does
        not reserve the crossbar path until TAIL. It does NOT say anything
        about whether two packets may share one input VC's packet context.

    input_vc_packet_policy = ONE_PACKET_AT_A_TIME
        WITHIN one input VC, HEAD/SINGLE opens a packet context and
        BODY/TAIL belong to it; no second HEAD/SINGLE may begin there until
        the first packet closes. Packets in DIFFERENT VCs may still make
        interleaved progress through the switch.

    vc_allocation_scope = PACKET
        HEAD/SINGLE selects the output VC at this hop; BODY/TAIL reuse that
        same output VC, and every outgoing flit of the packet at this hop
        carries it in its hop-local ``vc_id`` field. BODY/TAIL never
        re-arbitrate a different output VC (that would let one packet split
        across VCs or routing classes mid-hop). This complements the
        hop-local ``vc_id`` of the canonical packet format.

These three are separate semantics and must not be conflated.

``VCResourceArtifact.allowed_transitions`` is the sole concrete authority
for legal ``vc_in -> vc_out`` transitions. This artifact contains no second
transition table and invents no transitions through timers, congestion,
escape designation, role membership or automatic demotion.

Explicitly absent: escape/adaptive priority, routing-action priority,
congestion thresholds, MinAdapt/UGAL arbitration, hidden QoS priority, and
multicast. ``RoutingRelationArtifact`` / ``RoutingPolicyDefinition`` own
routing candidate semantics; future backend qualification proves how a
concrete router implementation consumes them. This artifact owns generic
router microarchitecture only.

Convenience baseline defaults live only in ``derive_router_behavior``.
The persisted artifact contains every resolved value explicitly, and no
consumer may assume omitted defaults from serialized data.
```

## `tracks/t3-topology/dse/veritx_dse/model/routing.py`

```text
veritx_dse.model.routing — compiler-owned route derivation (P1.2).

The routing-function problem, stated plainly: the legacy derivation
computed strings (``dim_order``/``dor``/``min_adapt``) while the
bundle independently built ``ANYNET_MIN_HOPS`` routes — derived text
that controlled no hardware semantics. This module is the single
place where the product compiler chooses routing:

    CompileRequest.dependencies + TopologyArtifact
        ↓ derive_route()
    RouteArtifact (LOCKED — no user field exists for it)

Policy (P1A slice + torus/flatfly reclamation): MESH and
CONCENTRATED_MESH route DOR_XY (dimension-order XY over the router
grid — deterministic, proven by construction-time termination walk
plus the P1.4 CDG certificate). TORUS routes DOR_TORUS_XY
(wraparound-minimal XY with deterministic midpoint ties; the dateline
VC-partition theorem is discharged per shape by the DEADLOCK_FREE CDG
obligation — never by construction). FLATFLY routes FLATFLY_MIN
(lowest-dimension-first minimal; DETERMINISTIC_CDG per (k, n) shape).
CUSTOM routes ANYNET_MIN_HOPS (the sealed executable contract — the
replica of the vendored fork's AnyNet routing, which the certified
AnyNet backend profile accepts and which executed-route comparison
verifies mechanically). Anything else (RING, …) is
UNSUPPORTED_SEMANTICS at the service boundary: representability is not
certification, and silent minimum-hop fallback would certify a route
set the deadlock theorem does not cover.

``request`` is a load-bearing parameter even though the MVP policy
keys off family alone: it is type-checked (fail-closed), and future
policy (dependency-driven class choice) consumes it.
```

## `tracks/t3-topology/dse/veritx_dse/model/routing_materialize.py`

```text
veritx_dse.model.routing_materialize — deterministic policy materialization.

Compile a ``RoutingPolicyDefinition`` into the existing sealed schema-v2
``RouteArtifact`` — but only when the policy has an exact deterministic
singleton realization:

    (current_router, destination) -> exactly one DirectedChannel

Representability profile (anything else is refused, never approximated):

    decision_scope       STATIC
    candidate_mode       SINGLETON
    selection_locus      ROUTE_COMPUTE
    randomness           NONE
    state_requirements   empty
    runtime_observations empty
    resource roles       exactly one, kind DEFAULT
    role transitions     empty or a single DEFAULT self-transition

Supported families (recognized from the validated semantic profile, never
from ``policy.id``):

  * DOR_XY               delegates to the certified RouteArtifact class;
  * ANYNET_MIN_HOPS      delegates to the certified RouteArtifact class;
  * WEIGHTED_SHORTEST_PATH  new producer over directed channels:
        primary key  minimum sum of DirectedChannel.route_weight
        tie-break    lexicographically smallest full channel-id sequence
  * CUSTOM_STATIC        explicit caller-supplied exact table.

``deadlock_proof_obligation`` is descriptive only: changing it must not
change the realized forwarding table, and this module never runs the CDG or
protocol verifiers. ``policy_hash`` never enters ``RouteArtifact`` identity —
intended semantics and exact realized tables are separate objects.
```

## `tracks/t3-topology/dse/veritx_dse/model/routing_policy.py`

```text
veritx_dse.model.routing_policy — backend-independent routing semantics.

``RoutingPolicyDefinition`` describes what a routing algorithm requires and
permits. It is deliberately none of the following:

  * not an executable route table (``RouteArtifact`` remains the
    authoritative deterministic singleton realization);
  * not a deadlock proof — ``deadlock_proof_obligation`` names the proof
    family a verifier must apply, never a verdict;
  * not a BookSim routing-function name or backend configuration record.

The definition is a reusable, content-addressed semantic object. Two
backends that implement the same routing behavior can reference the same
``policy_hash``; backend executables, seeds and simulator names never enter
the identity.

Later materialization splits by ``candidate_mode``:

    MINIMAL/STATIC/SINGLETON policies  -> existing RouteArtifact
    adaptive/stateful policies         -> a future relation artifact

The semantic dimensions:

  * path_mode, decision_scope, candidate_mode, selection_locus;
  * state_requirements (named packet-routing state, e.g. phase);
  * runtime_observations (what the policy may observe while deciding);
  * randomness;
  * resource_roles and allowed_role_transitions (semantic role ids only —
    concrete VC binding is a separate future artifact);
  * deadlock_proof_obligation (the proof family that must be discharged);
  * immutable semantic parameters.

Only universally safe structural implications are enforced: STATIC policies
may not require runtime observations or RNG. Nothing here assumes that
adaptive means minimal, that multiple roles mean multiple VCs, or that an
escape designation proves deadlock freedom.
```

## `tracks/t3-topology/dse/veritx_dse/model/routing_realization.py`

```text
veritx_dse.model.routing_realization — executable routing identity.

``RoutingRealizationArtifact`` is one canonical **hardware-execution
identity** for routing, regardless of whether routing is represented by:

1. the deterministic route chain
   (``RouteArtifact`` -> ``ResolvedRouteArtifact`` -> ``VCAssignmentArtifact``);
   or
2. the adaptive/stateful relation chain
   (``RoutingPolicyDefinition`` -> ``RoutingRelationArtifact`` ->
   ``RoutingResourceBindingArtifact``).

It exists to separate *source artifact identity* and *proof/presentation
metadata* from *routing behavior that changes executable fabric semantics*.
A future ``FabricArtifact`` binds only ``routing_realization_hash`` instead
of embedding deterministic/adaptive routing internals.

Why a normalization layer is required:

* ``RoutingRelationArtifact`` and ``RoutingResourceBindingArtifact`` each
  contain ``policy_hash``, and ``RoutingPolicyDefinition`` identity includes
  non-execution fields: the presentation ``id`` and the verification
  ``deadlock_proof_obligation``. Binding either source hash directly would
  let a proof-method or naming change masquerade as a hardware change.
* ``VCAssignmentArtifact`` identity includes proof-oriented ``escape_vcs``
  designation; only ``VC -> routing class`` is deterministic-only execution
  semantics not already owned by ``VCResourceArtifact``.

Source hashes are retained as immutable, strictly validated provenance for
``validate_against_*`` and traceability, and deliberately do **not**
participate in ``routing_realization_hash``.

Both kinds bind ``topology_hash`` and ``vc_resource_hash`` as semantic
identity, so a realization cannot be transplanted onto another topology or
concrete VC-resource universe.
```

## `tracks/t3-topology/dse/veritx_dse/model/routing_relation.py`

```text
veritx_dse.model.routing_relation — topology-bound legal routing actions.

``RoutingRelationArtifact`` is the second half of the routing-semantics split:

    RoutingPolicyDefinition
            │
            ├── deterministically representable  -> RouteArtifact (Slice 11)
            └── adaptive / stateful / stochastic -> RoutingRelationArtifact

It records the complete envelope of LEGAL routing actions for every declared
context. It deliberately does not:

  * select an action from congestion, faults or RNG;
  * bind abstract routing roles to concrete VC ids;
  * perform VC allocation or model a router allocator;
  * prove deadlock freedom (Slice 9A/9B own that);
  * contain backend names, BookSim VC ranges, endpoints or ranks.

Context is (current router, destination, current abstract role, routing
state). ``current_role_id is None`` is the injection/source context — a
packet that does not yet hold a routing resource role. It is not a declared
role. Actions are FORWARD (an exact topology channel plus next role and next
state) or EJECT (destination only). ``priority`` is semantic preference
metadata; this artifact never encodes how an allocator resolves ties.

The relation is total over its declared state space: every (router,
destination, {None + declared roles}, state-combination) context must have
exactly one decision. A policy that is already exactly representable by the
deterministic RouteArtifact profile is refused here
(``REDUNDANT_DETERMINISTIC_POLICY``) so there is only one deterministic
routing authority.
```

## `tracks/t3-topology/dse/veritx_dse/model/routing_relation_materialize.py`

```text
veritx_dse.model.routing_relation_materialize — MinAdapt source semantics.

Materialize the exact source-level SROTA semantic relation for the
``MIN_ADAPT_MESH`` routing policy:

    TopologyArtifact + RoutingPolicyDefinition
        -> RoutingRelationArtifact

Semantics (normalized, no backend VC numbers):

  * at the destination: exactly one EJECT;
  * ``current_role == "escape"``: the DOR_XY escape channel only,
    ``next_role = "escape"``, priority 0;
  * ``current_role == "adaptive"``: the DOR_XY escape channel
    (priority 0) plus one action per differing coordinate dimension that
    steps exactly one Manhattan unit toward the destination
    (``next_role = "adaptive"``, priority 1);
  * ``current_role is None`` (injection): the same normalized first-network
    envelope as the adaptive role.

The escape channel is taken from the already-certified schema-v2 DOR_XY
``RouteArtifact`` — this module never reimplements XY. Concrete VC ids,
BookSim ranges, allocator selection, and deadlock certification are out of
scope.

The same physical channel may legitimately appear twice in one decision
(e.g. ``(X, adaptive, 1)`` and ``(X, escape, 0)``): different routing
resource roles are different semantic actions.
```

## `tracks/t3-topology/dse/veritx_dse/model/routing_resource_binding.py`

```text
veritx_dse.model.routing_resource_binding — abstract roles to concrete VCs.

``RoutingResourceBindingArtifact`` binds the abstract routing resource roles
declared by a :class:`RoutingPolicyDefinition` to the concrete virtual
channels declared by a :class:`VCResourceArtifact`:

    adaptive -> (1, 2, 3)
    escape   -> (0,)

The parents are the POLICY and the VC RESOURCES, never a
``RoutingRelationArtifact``: the relation materializes roles for one
topology, while this binding is topology-independent and must be reusable by
every topology-specific relation produced from the same policy.

V1 requires a total, disjoint partition of the VC universe:

  * every policy role is bound exactly once, with at least one VC;
  * every concrete VC belongs to exactly one role;
  * unbound/dangling VCs are refused (reserved VCs would need explicit
    semantics, not an implicit omission).

Transition consistency is exact AND per-source:

  * projecting every concrete ``src_vc -> dst_vc`` through the binding must
    yield exactly ``policy.allowed_role_transitions``;
  * for every allowed ``role_A -> role_B`` and every ``src_vc`` bound to
    ``role_A``, there must be at least one concrete transition into some
    ``dst_vc`` bound to ``role_B``.

The second rule is what prevents a VC inside a role from losing access to a
required next role. Traffic-class eligibility is not touched here: injection
eligibility and in-network role transitions are separate semantics.
```

## `tracks/t3-topology/dse/veritx_dse/model/system_intent.py`

```text
veritx_dse.model.system_intent — SYSTEM intent v4 (Domain A closure).

The long-lived SYSTEM ontology: physical containment, stable agent-group
identity, typed clock/power domains, and the derived physical-inventory
artifact.

    SystemIntentV4
      containers[]     SystemContainer   physical containment only
      agent_groups[]   AgentGroup        stable group_id, never array position
      clock_domains[]  ClockDomain       typed; free text is gone
      power_domains[]  PowerDomain       typed; free text is gone
            │
            ▼ derive_physical_inventory
      PhysicalInventoryArtifact          immutable expanded supply

This module owns exactly that. It deliberately does NOT own:

  * logical ranks or the model rank space — PARALLELISM owns demand;
  * placement / mapping — PLACEMENT owns the join;
  * router seats, endpoints, attachments — FABRIC / attachment own those;
  * affinity or anti-affinity policy — PLACEMENT owns policy;
  * elastic ranges — DESIGN-SPACE owns search domains;
  * replication policy — count is the only multiplicity;
  * memory / failure / coherence / security domains — not SYSTEM concepts.

HIERARCHY DOES NOT IMPLY TOPOLOGY. Containment creates no link, no route,
no plane and no placement decision. A fabric policy that uses hierarchy
must consume it explicitly, downstream.

IDENTITY. ``system_intent_hash`` covers ids, kinds, counts, containment,
interfaces and domain membership. ``name`` on any entity is presentation
and is excluded — renaming never moves the scientific identity. Canonical
order is by id, so reordering a form is a no-op.

COMPATIBILITY. This is a NEW identity domain, exactly as v3 was against
v2. v3 requests are not reinterpreted; ``migrate_v3_agents_to_v4`` emits
explicit v4 facts and invents deterministic ids for positional groups
(``legacy-agent-group-NNN``). Migrated positional identity was never
named identity, and the migration does not pretend otherwise.
```

## `tracks/t3-topology/dse/veritx_dse/model/topology_artifact.py`

```text
veritx_dse.model.topology_artifact — materialized fabric truth (Wave B3.1).

A topology family name ("mesh 8x8") is intent METADATA. The authoritative
topology is the materialized graph:

    routers (with local attachment seats)
    directed channels (the routing/deadlock resource)
    optional physical-link grouping

Sizing rule (spec SROTA_FABRIC_SEMANTICS_V1 §9): router count is derived
from the hardware endpoint count and GUIDED concentration, never from a
hardcoded constant and never from the model rank count. Every AgentInstance
in NodeInventory needs a seat, so the endpoint count is
``NodeInventory.agent_count`` (compute tiles, HBM controllers, NICs,
peripherals, UCIe ports and idle compute instances alike).

TopologyArtifact does NOT depend on AgentAttachmentArtifact: it exposes
seats; the attachment artifact assigns agents to them. No circularity.

Canonical numbering (§7.5): regular families number routers by coordinate
order (row-major); ports are local seats then link ports in ascending
neighbor-id order; channel ids are assigned densely in sorted
(src_router, src_port, dst_router, dst_port) order. Changing these rules
changes identity and requires a schema bump.
```

## `tracks/t3-topology/dse/veritx_dse/model/topology_intent.py`

```text
topology_intent — the typed, family-specific topology authority (v4).

WHY THIS EXISTS
===============

`NocConfig` carried `topology_family` + `radix` + `concentration`. That is a
mesh-shaped vocabulary, and it is already insufficient:

  * GEC needs a grid side, concentration, express-channel grouping, a
    destinations-per-channel count AND a physical mode;
  * FlatFly needs a per-dimension radix, a dimension count and concentration;
  * Torus needs extents and wrap semantics;
  * fat-tree needs a switch radix and a level count.

The wrong fix is to let `NocConfig` accumulate every backend parameter. The
other wrong fix is to expose BookSim's `k`/`n`/`c`/`o`/`d` as the scientific
API because the backend happens to use those letters.

So topology intent is TYPED. Each variant owns exactly the parameters its
family's science needs, under scientific names, and a parameter that is
meaningless for a family is not expressible for it.

THE CENTRAL LAW (PHASE B.1 §5)
==============================

    THE INTENT MUST BE ABLE TO EXPRESS THE PHYSICAL DESIGN EVEN WHEN NO
    MATERIALIZER EXISTS YET.

Authorability and materializability are DIFFERENT stages. A multidrop GEC
design is real physical science (BookSim implements it over shared, tapped
`MultiDropChannel`s). Saying "this is a multidrop GEC design" must be legal
even though the canonical `TopologyArtifact` cannot represent a shared
resource yet. So the intent accepts it and MATERIALIZATION refuses it.

Refusing MECS *materialization* is correct. Refusing MECS *design intent* is
not.

WHAT THIS IS NOT
================

Topology intent describes PHYSICAL STRUCTURE only. It never carries a routing
function, a backend config, a backend profile or a VC policy — routing is
downstream of topology, and backend projection is downstream of both.

For an explicit graph the graph IS the input, so `ExplicitTopologyIntent`
carries the `TopologyIR` itself. That keeps v4 to ONE topology field: two
topology authorities cannot even be expressed, let alone disagree.
```

## `tracks/t3-topology/dse/veritx_dse/model/topology_ir.py`

```text
veritx_dse.model.topology_ir — TopologyIR v0: one topology, every backend.

A TopologyIR document is a single JSON file describing a fabric once;
translators lower it to each consumer's native format:

  - BookSim cfg (+ .anynet links file for anynet kinds)  -> to_booksim_cfg
  - ASTRA analytical network yml (Ring/Switch per-dim lists) -> to_analytical_yml
  - BookSim anynet links text (gen_star.py format)        -> to_anynet
  - presets.Topology bridge (mesh/torus/ring only)        -> to_preset

Schema vocabulary is InfraGraph-aligned: a fabric is NODES with optional
attrs joined by LINKS with attrs. Template kinds (mesh/torus/ring/star/
switch) expand to materialized nodes+edges; anynet/custom carry explicit
links. ``rtl`` is passthrough attrs for the RTL leg (carried, validated as
a mapping, unused by v0 translators).

Errors raise TopologyError (core.errors) with the file/field named — never
a silent default. In particular:

  - link_attrs.bandwidth_GBs / latency_ns are REQUIRED (the analytical leg
    has no honest fallback);
  - anynet/custom REQUIRE explicit ``dims`` for the yml leg (no honest
    topology-name guess for arbitrary graphs);
  - template kinds REJECT explicit ``links`` (one source of truth).
```

## `tracks/t3-topology/dse/veritx_dse/model/vc_assignment.py`

```text
veritx_dse.model.vc_assignment — VCAssignmentArtifact (Wave B3.3).

VC structure is a fabric semantic, not a buffering budget: which VC ids
exist, what each VC's routing class is, which traffic classes may use
which VC, which transitions are allowed, and (only when a routing class
implements one) which VC is an escape VC.

    TopologyArtifact ──► RouteArtifact (router-level)
            │                    │
            ▼                    ▼
    AgentAttachmentArtifact ──► ResolvedRouteArtifact
                                     │
                                     ▼
                              VCAssignmentArtifact

Parent hash: ``resolved_route_hash`` — VC semantics are routed semantics,
so the binding is to the endpoint-resolved route, never to a design label.

Hard rules (B3.3):
  * vc ids are exactly 0..vc_count-1 — no sparse or renamed VCs;
  * every VC maps to a RoutingClass present in the resolved route;
  * every declared traffic class has a non-empty, legal VC set;
  * transitions and escape designations reference existing VCs;
  * over-limit requirements are UNSUPPORTED, never silently clamped.

The derivation (which cycle needed which separation) lives in the
``derivation`` string and is provenance, not authority: it is transported
by ``to_dict()`` but deliberately excluded from ``vc_assignment_hash``.
```

## `tracks/t3-topology/dse/veritx_dse/model/vc_resource.py`

```text
veritx_dse.model.vc_resource — routing-independent concrete VC resources.

``VCResourceArtifact`` answers exactly one question:

    Which concrete virtual-channel ids exist, which traffic classes may use
    them, and which concrete VC->VC transitions are legal?

It deliberately knows nothing about:

  * routing classes or routing roles (``adaptive``, ``escape``, ...);
  * escape routing or escape designations;
  * RouteArtifact / RoutingRelationArtifact / ResolvedRouteArtifact;
  * topology, design identity, backends or deadlock proofs.

The same concrete VC structure can occur in different designs, so the
artifact carries no design hash and no parent hash. ``derivation`` is
provenance: it round-trips but is excluded from semantic identity.

The sealed Slice-8 deterministic ``VCAssignmentArtifact`` is projected into
this model one way by ``vc_resources_from_assignment``; the reverse
projection is intentionally not offered because a generic VC resource
structure carries no routing-class binding.
```


# `model` — extracted inline comments

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py`

line 20:

```text
# Product design-intent format. Versioned INDEPENDENTLY of the experiment
# spec (core.spec) and of every other persisted format — same user
# request under different compiler semantics is a different design.
```

line 24:

```text
# Compiler-semantics version — how design intent maps to identity.
#   v1 (legacy) — dependency declaration order is identity-bearing.
#   v2 (current) — graph processing is deterministic, so dependency
#                  declaration order is NON-semantic: the same dependency
#                  multiset always yields the same design_hash.
# v1 documents remain loadable under their own semantics and are never
# reinterpreted as v2; use migrate_design() to re-emit them explicitly.
```

line 123:

```text
# Strict primitive typing (Wave B1.1). `bool` is an `int` subclass in
# Python, so `type(x) is int` is the only reliable integer check; and an
# int/float distinction in the canonical JSON would otherwise let
# `1000` and `1000.0` hash differently for one semantic value.
```

line 471:

```text
# Maximum VC count the fabric supports (PRD §11.3 bound).
# NOTE: PLANE_C_MAX_VC lives in core.constants (env-overridable via
# VERITX_MAX_VC) and is imported, not re-declared — a second literal here
# would be a duplicated magic-number authority that could silently drift.
```

line 598:

```text
    # Count independent cycles (simplified: each cycle needs its own VC)
    # In production, this would use cycle overlap analysis to share VCs
    # between cycles that can be broken by separating the same node.
```

line 1084:

```text
        # The version fields describe the semantics THIS class implements;
        # they are not user-adjustable knobs. Unsupported versions are
        # unrepresentable in memory, exactly as they are refused on load.
```

line 1207:

```text
        # Arbitration spelling is not semantic identity (Gate 3 / §15):
        # "islip", "ISLIP" and " iSLIP " are one policy and must hash equal.
        # Normalization lives in the domain owner (router_behavior) and is
        # applied here only — `to_dict` stays lossless.
```

line 1769:

```text
    # F3: Packet conservation — checked by BookSim flit accounting
    # NOTE: This is a simulation check, not a formal proof. The claim is that
    # BookSim's internal accounting is correct (injected == completed + dropped).
    # For formal verification, we would need a model checker.
```

line 1815:

```text
    # F8: Timeout — bounded latency (BookSim simulation provides proof)
    # F8: Timeout — checked by BookSim latency threshold
    # NOTE: This is a simulation check, not a formal proof. The claim is that
    # BookSim's latency measurement is correct (within simulation accuracy).
    # For formal verification, we would need a model checker.
```

line 1917:

```text
# Product workload-intent envelope, versioned INDEPENDENTLY of v2: the
# same user fields under v3 semantics are a different design, and the
# distinct hash domain below makes v2/v3 identity collision structural.
```

line 1937:

```text
    # Synthesis provenance: LINKAGE, never design science. Accepted and
    # persisted, deliberately EXCLUDED from _semantic_dict() so it cannot
    # reach design_hash — a promoted candidate and the identical manual
    # graph must be the same design.
```

line 2241:

```text
        # Identity split: applicability rides the document only when it
        # differs from the default — every pre-existing document hashes
        # exactly as before, while an explicit waiver/evaluation mark is
        # identity-bearing (different semantics, different design).
```

line 2289:

```text
    #: THE TOPOLOGY-SELECTION LAW (FAB-007). A request expresses EXACTLY ONE
    #: topology source:
    #:
    #:   NAMED     noc_config.topology_family names a family the compiler
    #:             materializes (mesh / torus / concentrated_mesh)
    #:   EXPLICIT  explicit_topology carries the exact graph as a TopologyIR
    #:             document (kind=custom), which `materialize_ir` lowers
    #:
    #: Never both: declaring a family AND a graph is two authorities for one
    #: fact. An explicit graph is DESIGN INTENT, so its scientific content
    #: enters `design_hash`. Its `name` does NOT: a synthesized candidate and
    #: the identical hand-authored graph must be the same design science.
```

line 2302:

```text
    #: Optional linkage to the synthesis candidate this design came from.
    #: NOT design semantics: it is excluded from canonical_dict(), so
    #: origin cannot enter design identity. A manual design simply has None.
```

line 2352:

```text
        # ── topology-selection law (FAB-007) ────────────────────────────
        # A request expresses EXACTLY ONE topology source. `None` on both
        # keeps the historical NAMED default (mesh), so every pre-existing
        # request behaves identically.
```

line 2453:

```text
        # PERSISTENCE: the LOSSLESS document (label + backend policy kept),
        # so to_dict/from_dict round-trips exactly. canonical_dict() then
        # REPLACES this with scientific_dict() for identity.
```

line 2471:

```text
            # IDENTITY: replace the lossless document carried by
            # _semantic_dict with the SCIENTIFIC projection. `name` is
            # excluded so origin cannot enter design identity — a
            # synthesized candidate and the identical hand-authored graph
            # must hash the same.
```

line 2478:

```text
        # Identity/persistence split (P1C phase-2 fix): the persisted
        # workload_source_ref keeps provenance (artifact_identity), but
        # the canonical envelope hashes the identity representation
        # ONLY — same bytes from different producers, same design.
```

line 2490:

```text
        # Arbitration spelling is not semantic identity (Gate 3 / §15):
        # "islip", "ISLIP" and " iSLIP " are one policy and must hash equal.
        # Normalization lives in the domain owner (router_behavior) and is
        # applied here only — `to_dict` stays lossless.
```

line 2525:

```text
        # PERSISTENCE ONLY. `_semantic_dict()` feeds `canonical_dict()`, so a
        # provenance write there would put ORIGIN into design identity —
        # a promoted candidate and the identical manual graph would stop
        # being the same design. It is attached here, after identity is
        # settled, and is therefore linkage rather than science.
```

line 2751:

```text
    # A v4 request carries the SAME WorkloadV3, so the registry is the same
    # function of the workload. Checked by shape rather than by class so the
    # one definition cannot drift into two.
```

line 2898:

```text
    #: The EXPLICIT topology source, when the request declares one. Carried
    #: so the TOPOLOGY stage can dispatch without re-reading the request
    #: (the same discipline as noc_config). None = NAMED topology.
```

line 2902:

```text
    #: THE NORMALIZED TYPED TOPOLOGY AUTHORITY (PHASE B.1 §15).
    #:
    #: For a v4 request this is the declared intent itself. For v2/v3 it is
    #: derived TRANSIENTLY by this seam using FROZEN legacy semantics — a
    #: normalization, never a reinterpretation: it cannot change a persisted
    #: identity because the view has no to_dict/from_dict and its
    #: `design_hash` is copied from the source request verbatim.
    #:
    #: The TOPOLOGY stage consumes THIS, not legacy
    #: topology_family/radix/concentration.
```

line 3171:

```text
    # A v4 request carries the same WorkloadV3/DependencyGraph, so the VC
    # policy is the same function of the design. Checked by shape so the one
    # definition cannot drift into two.
```

line 3204:

```text
    # Dateline envelope: DOR_TORUS_XY over exactly 2 VCs executes every
    # class over the FULL envelope (the fork allocates from the route-set
    # envelope starting at VC 0 — vc_exactness), with deadlock-freedom
    # carried by the dateline VC partition (proven by the restricted CDG
    # expansion, not by class separation). A per-class singleton map
    # would describe narrowing the backend never performs, so the
    # canonical assignment states the executed domain. Gated strictly:
    # single DOR_TORUS_XY route class + exact 2 VCs (artifact transitions
    # default to identity, independently re-verified by the restricted
    # expansion before any certificate can pass); anything else keeps
    # the per-class derivation.
```

line 3286:

```text
# Max trace lines scanned during validate(). Full scans of 26M-line traces
# would break the "errors in seconds" promise; beyond the cap we report
# sampled results explicitly. Env-overridable (import-time read).
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_request_v4.py`

line 76:

```text
    #: Linkage to the synthesis candidate this design came from. NOT design
    #: semantics: excluded from canonical_dict(), so origin cannot enter
    #: design identity.
```

line 151:

```text
    # ── envelope rendering (delegates to the frozen v3 helpers) ─────────
    # These parts of the envelope are IDENTICAL to v3 by construction, so
    # they are rendered by the v3 code rather than re-implemented: a
    # duplicate would be free to drift.
```

line 187:

```text
        # PERSISTED IDENTITY (PHASE B.2 §6.1). v4 follows the same explicit
        # discipline as v3: the computed identity travels WITH the document,
        # so a reader can verify the document was not altered in transit.
        # `canonical_dict()` (the hash input) is unaffected — these are added
        # only to the persisted form, exactly as v3 does.
```

line 248:

```text
        # Reuse the frozen v3 readers for the UNCHANGED parts of the
        # envelope. They are invoked on a v3-shaped projection of this
        # document, so the shared sub-objects cannot drift between
        # generations.
```

line 256:

```text
            # CRITICAL: the v4 root hashes must NOT reach the frozen v3
            # reader. It would compare a V4 hash against a V3 design hash and
            # refuse a perfectly valid v4 document before the v4 parser ever
            # validates its own hashes. The v3 projection carries no root
            # identity; identity is validated once, below, by the v4 reader.
```

## `tracks/t3-topology/dse/veritx_dse/model/parallelism.py`

line 55:

```text
        # The dimension law has ONE definition: the sealed Wave-B rank
        # algebra (model.placement.ParallelismShape). This artifact adds
        # identity and group derivation; it must not restate the law. A
        # second copy is a second answer to "is tp=0 legal", which is how
        # two layers come to disagree.
```

## `tracks/t3-topology/dse/veritx_dse/model/placement.py`

line 170:

```text
        # Fundamental identity is the SOURCE coordinate (group, instance);
        # kind is descriptive information inherited from the parent group, so
        # it must not be able to mask a duplicate member claim.
```

## `tracks/t3-topology/dse/veritx_dse/model/presets.py`

line 50:

```text
        # 2D k×k mesh: 2*k*(k-1) undirected (112 for k=8; per-plane
        # logic consistent with reports.py). General n-dim:
        # n dims × k^(n-1) lines × (k-1) edges per line.
```

line 69:

```text
        # Physical graph per gec.cpp: mesh mode builds ONLY mesh channels
        # (2*k*(k-1) undirected); express (d==1) builds ONLY the full
        # row/column p2p graph (k*k*(k-1) undirected — the old formula added
        # unbuilt mesh edges on top, overcounting by 112 at k=8); MECS keeps
        # the mesh+express proxy (multidrop channels have no p2p equivalent).
```

line 93:

```text
        # k-ary n-tree: n levels × k^n links (undirected, approx).
        # NOTE: "fly" (flattened butterfly) is handled above and must NOT
        # appear here — the old ("fly", "fattree", ...) arm was dead for
        # "fly" (matched earlier).
```

line 111:

```text
# ── Collective spelling + parallelism math (Phase 4d single source) ────
# The same collective is spelled three ways across layers: "allreduce" /
# "alltoall" (DSE presets, compile CollectiveKind values), "all_reduce" /
# "all_to_all" (t3models registry, chakra CLI), "ALL_REDUCE" (chakra ET
# attr path). Normalize at every boundary; canonical = CollectiveKind value.
```

line 312:

```text
    # GEC mesh: mesh=1 builds the plain-mesh graph (o/d must be nonzero —
    # BookSim converts o=0/d=0 to full-express defaults, which once made
    # this preset a silent duplicate of gec_express_k8 at identical latency).
```

## `tracks/t3-topology/dse/veritx_dse/model/resolved_bundle.py`

line 63:

```text
        # Canonical revalidation: the two canonical children are pure
        # one-way projections of the sealed VC assignment, so the bundle
        # re-derives them instead of storing a second copy.
```

## `tracks/t3-topology/dse/veritx_dse/model/resolved_fabric.py`

line 50:

```text
# Classification of every current NocConfig semantic field. The set of keys
# must equal the exact dataclass field set; a new field breaks the sentinel
# until it is explicitly classified.
#
#   REPRESENTED     canonical hardware artifacts encode the semantics
#   NON_HARDWARE    output/authoring metadata, not executable network
#   UNSUPPORTED_V1  requires hardware semantics FabricArtifact v1 lacks
```

## `tracks/t3-topology/dse/veritx_dse/model/routing.py`

line 16:

```text
# NOTE (ownership debt): the WEIGHTED_SHORTEST_PATH class id is owned by
# `model.routing_materialize` (the producer) rather than by
# `core.route_artifact` (the sealed artifact owner), unlike DOR_XY and
# ANYNET_MIN_HOPS which live in the artifact module. Imported here rather
# than re-declared so there is one spelling. Moving it into route_artifact
# would be a rename of a sealed artifact and is deliberately not done here.
```

line 28:

```text
# Families the P1A compiler certifies routing for. Everything else
# refuses — including TORUS, whose wraparound needs a different
# deadlock theorem and gets its own class later.
```

line 36:

```text
#: THE DECLARED ROUTING-POLICY TABLE (compiler-owned).
#:
#: This is the canonical authority for "which routing semantic does this
#: topology use". It is DATA, not a branch: an implicit `if CUSTOM:` inside
#: the compiler would be an undocumented semantic, and the point of the
#: table is that the choice is inspectable and has exactly one owner.
#:
#:   DOR_XY                 deadlock-free BY CONSTRUCTION. Dimension-order
#:                          traversal terminates; the ordering IS the proof,
#:                          so no CDG check is needed to certify it.
#:   ANYNET_MIN_HOPS        the SEALED EXECUTABLE contract for CUSTOM. Its
#:                          first-hop table IS the vendored fork's
#:                          ``AnyNet::route()`` replica, so route
#:                          equivalence holds by construction rather than
#:                          by hope. Naming debt (the id spells a backend
#:                          concept) is recorded, not acted on.
#:   WEIGHTED_SHORTEST_PATH a SEPARATE, still-valid producer. It is NOT
#:                          selected by this table today: no family maps to
#:                          it. It remains reachable through
#:                          `routing_materialize` for callers that ask for
#:                          it explicitly, and its deadlock-freedom is a
#:                          PROPERTY TO BE CHECKED by the CDG obligation,
#:                          not a consequence of the algorithm.
#:
#: The mapping below is THE authority. Diagnostics DERIVE their wording
#: from it (see `_certified_mapping_text`): a hand-written sentence is what
#: once let this file's error message claim custom used
#: WEIGHTED_SHORTEST_PATH while the table said ANYNET_MIN_HOPS.
```

line 69:

```text
    # GEC-EXPRESS is pure point-to-point, so the sealed AnyNet minimum-hop
    # contract routes it exactly (first-hop equivalence by construction).
    # No GEC-specific routing class is invented: dor_gec parity is a
    # backend-execution question, not a canonical route semantic.
```

line 74:

```text
    # CUSTOM routes with ANYNET_MIN_HOPS — the SEALED, EXECUTABLE contract.
    #
    # CORRECTION (this supersedes an earlier choice in this file). An earlier
    # revision selected WEIGHTED_SHORTEST_PATH here, on the aesthetic ground
    # that ANYNET_MIN_HOPS' name is BookSim-coupled. That was wrong and it
    # cost us the backend:
    #
    #   * `core.route_artifact.route_entries_from_adj` is documented as
    #     "the one routing truth: AnyNet::route() first-hop table" — a REPLICA
    #     of the vendored fork's routing, i.e. the sealed contract that
    #     ALREADY matches BookSim;
    #   * `backend.booksim_projection.qualify_anynet_min_hops` is a
    #     pre-existing fail-closed profile that ACCEPTS a custom graph routed
    #     with ANYNET_MIN_HOPS (verified) and REFUSES one routed with
    #     WEIGHTED_SHORTEST_PATH purely on the class id;
    #   * so choosing WEIGHTED_SHORTEST_PATH created a canonical-vs-backend
    #     mismatch that did not previously exist, and then reported that
    #     mismatch as a backend limitation.
    #
    # The naming debt is real and is recorded rather than acted on: renaming
    # a sealed artifact to sound backend-neutral is exactly the gratuitous
    # rename the reclamation discipline forbids.
```

line 97:

```text
    # RING is deliberately ABSENT (test fixture, not user intent). TORUS
    # and FLATFLY were absent until the wraparound/minimal reclamation
    # proved them: torus minimum-hop without the dateline theorem routes
    # but the CDG reports acyclic=False with a cycle witness — a real and
    # useful verdict that the DOR_TORUS_XY VC-partition theorem answers.
```

line 218:

```text
    # P1C phase-2: the gate accepts the fabric view too. It reads
    # NOTHING from the request (routing is LOCKED off the topology),
    # so the v2 flow is provably identical — the view only lets v3
    # reach the same derivation without a fake-v2 conversion.
```

line 234:

```text
        # Wraparound is NOT deadlock-free by construction: the class
        # carries the dateline VC-partition theorem and the normal
        # DEADLOCK_FREE verification obligation must discharge the
        # channel-VC CDG per shape. Nothing here claims acyclicity.
```

line 258:

```text
        # The SEALED executable contract: a replica of the vendored fork's
        # AnyNet routing, which the certified AnyNet profile accepts and
        # which `routing_dump_file` comparison verifies mechanically.
```

line 273:

```text
        # Reachable only if a family is added to `_POLICY_BY_FAMILY` with
        # this policy (none is today). Kept because WEIGHTED_SHORTEST_PATH
        # remains a valid, separately-owned producer — deleting the branch
        # would make re-adding a family silently unsupported.
        # Deadlock-freedom is a property the CDG obligation must CHECK. The
        # producer lives in `routing_materialize`; this module only SELECTS
        # the policy and calls it. There is no synthesis/authoring branch
        # here — the topology's family alone decides.
```

## `tracks/t3-topology/dse/veritx_dse/model/routing_realization.py`

line 195:

```text
# Every RoutingPolicyDefinition identity field is classified as exactly one
# of: EXECUTION (hardware), PRESENTATION, VERIFICATION. The classification
# is a hard gate: policy_execution_semantics_dict() fails closed if the
# supplied policy has an identity field this module has not classified.
```

line 606:

```text
# ── adaptive backend selection (canonical projection record) ───────────
#
# This is a canonical SELECTION record, not a backend renderer: it states
# which fork routing function an ADAPTIVE realization executes under, the
# exact VC partition the fork requires, and the observation scope. The
# backend projection consumes it; routing stays compiler-LOCKED (no user
# knob). Only MIN_ADAPT_MESH is selectable; every other adaptive fork
# function is refused.
```

line 618:

```text
#: Fidelity label for adaptive execution. Distinct from the deterministic
#: static first-hop envelope: runtime route selection is allocator-
#: observed, never a certified table.
```

## `tracks/t3-topology/dse/veritx_dse/model/routing_relation_materialize.py`

line 35:

```text
#: Fork routing functions with NO canonical policy instance. They execute
#: in the backend only; any policy naming one is refused here.
#: ``limited_adapt_mesh`` is additionally broken upstream (its registration
#: is commented out in routefunc.cpp) and must never be reclaimed.
```

line 67:

```text
# The only runtime observation the MinAdapt profile may carry is the router
# allocator's credit visibility; it selects among legal candidates but does
# not change the legal-action envelope materialized here.
```

## `tracks/t3-topology/dse/veritx_dse/model/topology_artifact.py`

line 785:

```text
    # ── NORMALIZED TYPED INTENT (v4 / FabricIntentView) ──────────────
    # THE ONE SEAM. A FabricIntentView always carries a normalized
    # `topology` intent (derived transiently for v2/v3 by the dispatch
    # seam). When it is present it is the AUTHORITY: nothing downstream
    # reads legacy topology_family/radix/concentration.
```

line 804:

```text
    # ── EXPLICIT source (FAB-007) ────────────────────────────────────
    # Read by attribute so a FabricIntentView needs no import here and no
    # second topology authority exists (same discipline as noc_config).
```

line 820:

```text
        # The canonical attributes come from the request's link_width when
        # declared; TopologyIR's analytical attrs are NOT converted here
        # (ns -> cycles needs a clock TopologyIR does not carry).
```

## `tracks/t3-topology/dse/veritx_dse/model/topology_intent.py`

line 361:

```text
#: Every topology kind a v4 design may declare. Capability truth DERIVES its
#: probe coverage from this, so a newly registered kind cannot be silently
#: ungated (PHASE B.1 §18.1).
```

line 385:

```text
        # The persisted form carries the graph as a plain document; the
        # in-memory form carries a TopologyIR. Convert HERE and nowhere else,
        # so a persisted intent always reloads to the same object.
```

line 419:

```text
#: Frozen v3 default concentration for concentrated mesh, used ONLY by the
#: migration. It is a literal on purpose: reading a mutable current default
#: would make a migration's meaning depend on when it ran.
```

## `tracks/t3-topology/dse/veritx_dse/model/topology_ir.py`

line 50:

```text
# BookSim cfg defaults. Canonical source is simulation.booksim.BASE_PARAMS
# (model must not import simulation — layering); test_topology_ir asserts
# this dict stays equal to BASE_PARAMS so the two can never drift silently.
```

line 478:

```text
    # Explicit node count for parse_booksim_cfg (closed-form-free topologies
    # must not be guessed). The ASTRA path strips it via _write_sanitized_cfg
    # — BookSim's own parser rejects unknown fields.
```

line 530:

```text
    # House style matches ASTRA examples (50.0, 500.0, 936.25): always a
    # float rendering. Semantically identical either way (YAML ints parse
    # to the same double in yaml-cpp), this is purely cosmetic parity.
```

## `tracks/t3-topology/dse/veritx_dse/model/vc_assignment.py`

line 19:

```text
# Compatibility alias only: the authoritative default class is
# resolved_route.routing_classes[0] (RouteArtifact v2). "DEFAULT" no
# longer names hardware semantics — B3.2d materializes ANYNET_MIN_HOPS /
# DOR_XY explicitly. The name stays so older callers do not break.
```

line 337:

```text
            # No int()/str() repair: malformed persisted values must be
            # rejected by __post_init__, never canonicalized into valid
            # state (True / 1.0 / "1" are impostors, not integers).
```


# `model` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/model/attachment.py` :: `AgentAttachmentArtifact`

```text

    Identity parent is ``topology_hash`` ONLY. DesignRevision and
    NodeInventory are derivation/validation sources; MappingArtifact is a
    downstream ResolvedFabric seam concern.
```

## `tracks/t3-topology/dse/veritx_dse/model/attachment.py` :: `AgentInterfaceDescriptor`

```text

    This is NI-level hardware semantics, derived from the design revision
    and copied into the attachment artifact: design-derived semantics
    propagate through the descriptor, not through a design hash.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `AddressMap`

```text

    Accepts three forms per PRD:
      - Interactive: built programmatically
      - Import: parsed from CSV/IP-XACT/JSON
      - Inherit: cloned from previous revision

    This is the minimal representation. The full PRD address map
    includes initiator→target decode, which we derive from the
    agent positions in the topology.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `CollectiveDimension`

```text

    TP/DP/EP expand to the ParallelismArtifact groups of that family
    (deterministic: every rank in exactly one group — e.g. tp=8,dp=4
    yields four TP groups of eight). GLOBAL is the single all-ranks
    group. PP names pipeline stages, which are NOT collective peers
    (stages communicate point-to-point); a PP-dimension COLLECTIVE is a
    typed refusal at lowering, while pp>1 geometry still scopes TP/DP
    groups within stages.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `CollectiveIntent`

```text

    Unlike v2 CollectiveOp (whose bytes_per_element meaning is unproven —
    see B1 finding 1), every field here is load-bearing: kind names the
    pinned schedule, dimension derives the exact participant groups,
    payload_bytes is the per-kind schedule payload B consumed verbatim
    by workload/collectives.py::collective_schedule, traffic_class is
    the unified-namespace identity (B1 finding 2), and source_rank is
    the explicit BROADCAST root (no participants[0] invention — a
    BROADCAST without one is unrepresentable).
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `CompileRequest`

```text

    Combines all five entities (E1–E5) into one immutable revision.

    Identity (Wave B1): ``design_hash()`` is the AUTHORITATIVE product
    design-intent identity — SHA-256 over the canonical semantic envelope
    (domain-tagged and versioned by schema + compiler semantics).
    ``guardrail_hash()`` is a retained compatibility name for the same
    value; new code calls ``design_hash()``. Execution provenance (git
    commit, binaries, host, timestamps, seeds) is deliberately NOT part
    of either hash.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `CompileRequestV3`

```text

    Agents, dependencies, NoC knobs, address map, and physical context
    reuse the v2 types UNCHANGED (one authority per concept — no second
    Agent/NoC types). Only workload and requirements are v3 generations.
    Envelope (schema 3 / semantics 3, distinct hash domain) keeps v2 and
    v3 identities disjoint: the same user fields under v2 semantics are a
    different design and NEVER reinterpreted here (use migrate_v2_to_v3
    with explicit per-collective specs).
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `DependencyGraph`

```text

    The graph is a directed graph over traffic class names.
    Cycles in the BLOCKING subgraph indicate potential deadlock
    that requires VC separation to resolve.

    Frozen with a tuple: the graph is part of design identity, so it
    must not be mutable after construction.

    TRAVERSAL CONTRACT (compiler semantics v2): graph processing is
    deterministic. Adjacency neighbor lists are sorted and DFS roots are
    visited in sorted node-name order, so the observed cycle witnesses do
    not depend on Python set/hash iteration or on dependency declaration
    order. Under legacy semantics v1 dependency declaration order remains
    identity-bearing in design_hash(); that is a hashing ruling only — the
    traversal below is deterministic in both.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `FabricIntentView`

```text

    The compiler's fabric derivation consumes this where a gated type is
    required. Fields: the shared fabric inputs (agents, dependencies,
    noc_config, address_map, physical), the parallelism geometry as plain
    ints, the DECLARED traffic classes the fabric must serve, and the
    design identity string it binds. source_generation ("v2"/"v3") is
    dispatch metadata selecting the VC policy — never persisted, never
    hashed (the view itself has no to_dict/from_dict by design).
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `NocConfig`

```text

    CRITICAL DESIGN: This type deliberately has NO fields for:
      - routing_function (LOCKED — derived from dependency graph)
      - turn_restrictions (LOCKED — derived from topology + routing)
      - vc_map (LOCKED — derived from dependency graph via derive_vc_count)

    An override isn't something the compiler refuses — it's something
    that cannot be expressed. A type with no field for the value cannot
    be overridden.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `RequirementApplicability`

```text

    APPLICABLE: the requirement declares a bound and must be evaluated
        and PASS before a candidate is product-eligible.
    NOT_APPLICABLE: explicitly waived by the author; requires empty
        thresholds (a bound requirement cannot be waived — binding +
        no-threshold refuses at construction).
    NOT_EVALUATED: explicitly marked unevaluated; never passes — a
        candidate carrying it is product-ineligible until evaluated.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `RequirementV3`

```text

    traffic_class names the constrained traffic in the unified namespace
    (None = fabric-wide); qos_class names the policy applied to it.
    A binding requirement must be met or the design fails; binding +
    UNMEASURABLE never passes (requirements.py enforces at report read).
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `Tier`

```text

    LOCKED: Compiler derives. No override, no expert mode.
    GUIDED: User proposes; optimizer may adjust.
    FREE: User's call, no second-guessing.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `TopologyFamily`

```text

    Membership here means the family is RECOGNIZED and AUTHORABLE. It does
    NOT mean materializable, routable or executable. GEC and FAT_TREE are
    authorable with no materializer, and `_family_of` refuses them with a
    typed error rather than silently downgrading. The stage authority is
    docs/product/topology-family-registry.yaml.

    CUSTOM is a CLASSIFICATION marker, not a topology algorithm: it means
    "the graph comes from an explicit topology description (TopologyIR)".
    It carries no parameters and is not materializable through
    `_family_of` — the graph itself is the input.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `Workload`

```text

    Covers Level A (model & serving) and optionally Level B (phases via trace).
    
    SOURCE OF TRUTH RULES:
    - tp/pp/ep/dp describe the MODEL configuration (Level A)
    - trace_path describes the ACTUAL TRAFFIC (Level C)
    - If both are present, trace_path is the ground truth for simulation
    - tp/pp/ep/dp are used for topology sizing and VC derivation
    - The two are consistent: trace was generated from this model config
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `WorkloadSourceRef`

```text

    Names BYTES, never paths: content_digest is sha256 over the exact
    ingested bytes, format names the byte dialect (e.g. "packet_trace",
    "chakra_et", "synthetic"), size_bytes bounds the artifact, and
    artifact_identity names the producing artifact or producer (provenance,
    never authority). A filesystem path is transport metadata and MUST
    NOT enter v3 identity — ingest bytes first via
    ingest_workload_source_file. A synthetic intent (no external bytes)
    carries source_ref=None on WorkloadV3: the intent document is then
    its own source.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `WorkloadV3`

```text

    No trace_path (B1 finding 5): external bytes are bound via source_ref
    (or None for a synthetic intent, which is its own source). tp/pp/ep/dp
    are the model geometry the dimension expansion derives groups from.
    serving_mode is serving characterization ONLY — it never maps to a
    per-operation phase (no PREFILL_HEAVY -> pure-PREFILL invention; see
    intent_lowering).
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `_normalized_fabric_from_legacy`

```text

    This is the ONLY place allowed to read legacy
    `noc_config.topology_family` / `radix` / `concentration` for the purpose
    of choosing a topology: after this seam, topology materialization reads
    `view.topology` and nothing else.

    It is a NORMALIZATION, not a reinterpretation. The derived intent is
    transient (the view has no to_dict/from_dict) and `design_hash` is copied
    from the source request verbatim, so a legacy document's persisted
    identity cannot move because of it.

    It reuses the same frozen sizing law the migration uses, and it REFUSES
    families whose legacy spelling does not determine a physical design
    (flatfly / gec / fat_tree) rather than guessing.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `canonical_dict`

```text

        Ordering policy (authoritative table lives in
        tests/test_design_intent_identity.py):
          ORDERED   collectives (index to VC map), agents
                    (target_agent_idx indexes the tuple)
          UNORDERED dependencies (semantics v2; graph processing is
                    deterministic), requirements, address ranges,
                    output_formats

        Under legacy semantics v1, dependency declaration order is
        identity-bearing; v1 documents are hashed in declared order so
        their stored design_hash still validates. Under semantics v2,
        dependency rows are canonicalized (sorted) in the identity.
        Sorting changes order only: duplicate declared edges are kept.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `collective_vc_floor`

```text

    Assumption (documented, worst-case): declared collectives are
    potentially concurrent. Concurrent collectives sharing a VC can
    deadlock via cyclic buffer waits (rank A holds buffers for collective 1
    waiting on B; B holds buffers for collective 2 waiting on A) — the same
    reason MPI separates communicator contexts and IB maps classes to
    distinct service levels. Phase overlap is NOT modeled, so this is a
    floor, not a proof: VC0 covers the first context, each additional
    multi-rank collective needs one more VC.

    Single-rank (group_size == 1) collectives need no fabric VC.

    RECLAIMED from the stronger lineage (integration/p1-product), where it
    is the sibling of collective_vc_map; the current tree had only the map.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `derive_topology_spec`

```text

    Maps NocConfig.topology_family → Topology(backend=...) with
    appropriate defaults from the PRD's GUIDED knobs.

    The routing function is LOCKED — derived from the dependency graph
    via derive_vc_assignment(), not taken from the family map default.

```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `derive_vc_assignment`

```text

    Algorithm (from PRD listing 11.2):
      1. Build blocking dependency graph
      2. Find cycles in BLOCKING subgraph
      3. For each cycle, choose the victim (least separation cost)
      4. Assign victim to a distinct VC
      5. Derive routing function from topology + cycle structure

    The routing function and turn restrictions are LOCKED — derived,
    not chosen by the user.

```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `derive_vc_assignment_artifact`

```text

    The candidate VC structure (dependency-graph cycles + collective
    floor as policy input) is bound explicitly to the route the
    compiler derived: every VC names its routing class, and every
    routing class the route defines is served by at least one VC
    (coverage assertion — a class with no VC would be unroutable
    hardware). The derivation string names the route classes,
    victims and floor; it is provenance, never authority. Acyclicity
    is proven by the P1.4 certificate's CDG obligation over
    (topology, route, VC assignment), not by this string.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `derive_vc_assignment_v3`

```text

    Cycle law is shared (derive_vc_count over the same DependencyGraph
    type; over-limit is UNSUPPORTED, never clamped). The v2
    concurrent-collectives floor is DELIBERATELY absent: v2 assumes
    declared collectives are potentially concurrent, while v3 intents
    lower to an ordered sequential chain — copying the floor would
    over-provision VCs for concurrency v3 semantics never claim.
    Every DECLARED traffic class appears in per_class_vc even when
    plainly VC0 (fabric must serve what intent declares); dependency
    endpoint names ride along at VC0; cycle victims separate per the
    shared least-cost law.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `derive_vc_count`

```text

    LEGACY UTILITY (not a canonical candidate authority — see
    compiler/candidate_policy.py for the canonical VC proposal).

    Algorithm:
      1. Collect deterministic DFS cycle witnesses of the BLOCKING subgraph
         (see DependencyGraph.find_cycles: not an exhaustive cycle list).
      2. Each witness needs >= 1 member on a distinct VC to break it.
      3. Choose the member whose separation costs least buffering.
      4. VC count = 1 + number of witnesses needing separation.

    If vc_count > PLANE_C_MAX_VC, the design is infeasible.

```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `find_cycles`

```text

        SCOPE: this is NOT an exhaustive enumeration of every simple cycle
        in the mathematical graph. It returns the deterministic set/sequence
        of DFS back-edge witnesses produced by sorted-root, sorted-adjacency
        depth-first search — the exact witnesses the baseline candidate
        heuristic consumes. Independent VC/deadlock verification remains
        downstream.

        Returns a list of witnesses, where each witness is a list of node
        names closing back on its first node.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `from_ipxact`

```text

        IP-XACT (IEEE 1685) is the standard XML format for hardware component descriptions.
        This parser extracts memoryMap elements with addressBlock children.

        Expected structure:
            <component>
              <memoryMaps>
                <memoryMap>
                  <addressBlock>
                    <name>HBM0</name>
                    <baseAddress>0x00000000</baseAddress>
                    <range>0x10000000</range>
                  </addressBlock>
                </memoryMap>
              </memoryMaps>
            </component>
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `generate_artifacts`

```text

    Produces a manifest artifact for each CompileRequest.
    RTL/UVM generation is delegated to external tools but tracked here.

```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `migrate_design`

```text

    Input is a CompileRequest object or a persisted CompileRequest dict;
    a dict is parsed and validated under its own declared semantics first,
    so its stored design hash must validate exactly according to that
    semantics.

    CURRENT semantics v2: returned semantically unchanged with a no-op
    migration record. LEGACY semantics v1: every actual design semantic is
    preserved and a semantics-v2 CompileRequest is emitted whose
    DependencyGraph row order is canonicalized IN THE MIGRATED OBJECT
    ITSELF (not only in the hash projection), so two v1 documents that
    differ only by dependency declaration order migrate to byte-identical
    v2 ``to_dict()`` results.

    Returns ``(migrated, provenance)``. Provenance is NON-semantic — it
    never enters design identity; the caller records it out-of-band.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `migrate_v2_to_v3`

```text

    v2 CollectiveOp carries NO dimension, NO payload_bytes, and NO
    traffic_class (bytes_per_element meaning unproven — B1 finding 1),
    so migration CANNOT be mechanical: the caller supplies one spec per
    v2 collective, in order, each naming dimension/payload_bytes/
    traffic_class (+ source_rank for BROADCAST). Guessing is refused:
    spec count must equal collective count, and every spec is validated
    as a CollectiveIntent.

    A v2 trace_path is a mutable path, never v3 identity (B1 finding 5):
    if the v2 workload names one, the caller must supply an ingested
    source_ref (ingest_workload_source_file) or migration refuses.
    v2 requirements carry no traffic scope (B1 finding 3) and migrate
    as fabric-wide (traffic_class=None) — narrowing scope needs intent
    the v2 document never stated.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `validate`

```text

    Catches config errors in seconds, not minutes. Checks:
      - At least one agent with count > 0
      - Dependency graph cycle detection (warnings, not errors)
      - VC count derivation
      - Total node count

```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `verify_design`

```text

    Produces proof obligations for the selected configuration.
    Each check returns PASS/WARN/FAIL with explanation.

    F1: Deadlock freedom — no cyclic channel dependency
    F2: Liveness — every packet eventually delivered
    F3: Packet conservation — no lost/duplicated flits
    F4: Ordering — in-order delivery per VC
    F5: Flow control — credit-based, no overflow
    F6: Routing correctness — minimal/adaptive paths
    F7: QoS isolation — traffic classes don't starve
    F8: Timeout — bounded latency under load
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_request_v4.py` :: `migrate_v3_to_v4`

```text

    MIGRATION MATRIX
    ----------------
    mesh (+ radix=None)      -> MeshIntent, radix RESOLVED from the request's
                                endpoint count via the FROZEN v3 sizing law
    mesh (+ radix=k)         -> MeshIntent(side_length=k)
    concentrated_mesh        -> ConcentratedMeshIntent; a missing
                                concentration resolves to the FROZEN v3
                                default 4 (a literal, not a live default)
    torus                    -> TorusIntent (wrap topology only; no routing
                                is invented)
    explicit_topology        -> ExplicitTopologyIntent(graph=...) preserving
                                the graph's scientific identity
    topology_family=None     -> the legacy IMPLICIT mesh becomes an EXPLICIT
      (and no explicit graph)   MeshIntent
    flatfly / gec / fat_tree -> REFUSED unless `topology_intent` is supplied.
                                The v3 spelling does not determine a physical
                                design for these families.

    `topology_intent` may be supplied to resolve a family v3 could not
    express. It must AGREE with any family v3 DID express.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_request_v4.py` :: `noc_config`

```text

        It carries NO topology shape: `topology_family`, `radix` and
        `concentration` are all None, because in v4 topology shape belongs
        exclusively to `self.topology` and a second copy could disagree.

        This exists so control reads (`link_width`, `arbitration`, ...) do not
        have to be rewritten in one step. It is NOT a second authority for
        anything: the shape fields are structurally absent, so a consumer
        that reads shape here gets None and must fail loudly rather than
        silently use a stale copy.
```

## `tracks/t3-topology/dse/veritx_dse/model/noc_controls.py` :: `NocControls`

```text

    GUIDED (the engine may adjust):
      arbitration        switch arbitration policy name
      rcu_enabled        request-combining unit present
      link_width         link width in bits
      mcast_groups       hardware multicast groups the switch engine holds
      mcast_setup_cycles per-group reconfiguration cost

    FREE (the user's call, and not design physics):
      output_formats     which RTL artifacts to emit
      obfuscation_level  source obfuscation strength

    Every field keeps its `None`/default meaning from `NocConfig`: `None` on
    a GUIDED control means UNCONSTRAINED, and the compiler derives the value.
    That is preserved deliberately — a v3 document that left `arbitration`
    unset must not silently acquire a different meaning in v4.
```

## `tracks/t3-topology/dse/veritx_dse/model/placement.py` :: `AgentInstance`

```text

    ``group_index`` is the ordered position of the source Agent group in
    CompileRequest.agents; that order is semantic because
    AddressRange.target_agent_idx indexes it. Two Agent groups of the
    same kind therefore never collide, because the group index is part
    of the identity.
```

## `tracks/t3-topology/dse/veritx_dse/model/placement.py` :: `NodeInventory`

```text

    agent_count        — hardware agents the fabric carries
    rank_count         — model ranks the workload must place
    compute_instances  — agents a rank may occupy

    Self-checking: agent identities are unique, the rank namespace is
    exactly [0, world_size), and every rank's stored coordinates match
    the declared parallelism shape.
```

## `tracks/t3-topology/dse/veritx_dse/model/presets.py` :: `anynet_usability`

```text

    THE reusable gate for custom-graph simulation. BookSim HANGS on a
    disconnected anynet, and can dribble out a near-empty result (e.g. 13
    delivered packets) that would otherwise rank as a real measurement.

    Three distinct failures keep three distinct reasons — a missing file
    (bad glob/typo), a corrupt file (parses to zero routers) and a
    disconnected graph must never collapse into one shrug. A fourth case
    is a trace that addresses more nodes than the graph has: the run
    delivers zero packets and measures nothing.

    ``reason`` is "" when usable. RECLAIMED from the stronger CLI lineage
    (integration/p1-product) where it was inlined in ``run_compare``;
    promoted here so every caller shares ONE precheck instead of
    re-implementing it ad hoc.
```

## `tracks/t3-topology/dse/veritx_dse/model/presets.py` :: `topo_size`

```text

    All other modules must delegate here instead of hand-rolling
    ``k**n`` / edge math.

    Usable from a Topology object OR a backend+params dict::

        topo_size(topo)                      # Topology instance
        topo_size("mesh", {"k": 8, "n": 2})  # backend + params dict
        topo_size(backend="mesh", params={"k": 8, "n": 2})
        topo_size({"backend": "mesh", "k": 8, "n": 2})          # flat dict
        topo_size({"topology": "mesh", "k": 8, "n": 2})         # flat dict
        topo_size({"backend": "mesh", "params": {"k": 8}})      # nested dict

    Returns (num_nodes, num_edges). Unknown backends yield (0, 0);
    anynet with a missing/unreadable file yields (0, 0) via
    :func:`count_anynet_edges`.
```

## `tracks/t3-topology/dse/veritx_dse/model/router_behavior.py` :: `canonical_arbitration_token`

```text

    Two designs that name the same policy with different spellings must have
    the same design identity, so ``"islip"``, ``"ISLIP"`` and ``" iSLIP "``
    all collapse to the canonical policy value. This is the normalization the
    product identity is computed through; it is deliberately *not* applied to
    lossless serialization (``to_dict``), which preserves what the user
    wrote.

    A value outside the alias table is returned verbatim rather than folded
    into a known policy or refused: it is not a policy this compiler knows,
    so it must keep its own identity. ``canonical_allocator`` still refuses it
    at compile time — identity is not the place to decide validity.

    ``None`` is deliberately NOT folded into the iSLIP default, even though
    ``canonical_allocator`` resolves it that way. ``None`` is a *declaration
    state* (unset; ``SEMANTIC_DEFAULT`` in the exposure registry), not a
    spelling of a chosen policy: "the user did not decide" and "the user
    chose iSLIP" are different requests, and ``design_hash`` answers what was
    requested, not what the compiler resolved it to.
```

## `tracks/t3-topology/dse/veritx_dse/model/router_behavior.py` :: `derive_router_behavior`

```text

    The historical baseline is:

        per-input-port/per-VC buffering, 8 flits deep
        one output staging slot per VC
        credit flow control, one-cycle return latency
        WAIT_FOR_TAIL_CREDIT reuse
        iSLIP VC and switch allocators, one iteration
        flit-granularity switch (no packet hold)
        one packet context per input VC, packet-scoped VC allocation
        input/output/internal speedup 1
        route 0, VC-alloc 1, switch-alloc 1, traversal 1, output 0 cycles

    These defaults belong only to this convenience builder. The persisted
    artifact always carries every resolved value explicitly.

    ``arbitration`` is a guided label canonicalized to an AllocatorPolicy;
    the raw string is not part of artifact identity.
```

## `tracks/t3-topology/dse/veritx_dse/model/routing_relation.py` :: `RoutingAction`

```text

    ``priority`` is exact integer routing preference metadata (higher means
    preferred). Tuple order never carries priority: action order is
    canonicalized for identity and consumers must read this field.
```

## `tracks/t3-topology/dse/veritx_dse/model/system_intent.py` :: `AgentGroup`

```text

    ``group_id`` is the primary semantic reference. Array position is
    never identity, so reordering a form cannot change meaning.

    Heterogeneity is expressed by declaring a second group — the interface
    belongs to the group, not the instance.
```

## `tracks/t3-topology/dse/veritx_dse/model/system_intent.py` :: `AgentInterface`

```text

    ``addr_width`` is SEMANTIC_AND_CONSUMED: it bounds the address domain
    (``address_decode.py``). ``data_width`` and ``protocol`` are
    DECLARED / NOT INTERPRETED today — they enter attachment identity and
    therefore the certificate, but no consumer reads them. They are kept
    identity-bearing deliberately, pending a real interface contract.
```

## `tracks/t3-topology/dse/veritx_dse/model/system_intent.py` :: `PhysicalInventoryArtifact`

```text

    Contains physical supply only. It deliberately excludes logical ranks,
    placement, router seats and endpoint attachments — those belong
    downstream. ``endpoint_demand`` is derived, never declared (S3).
```

## `tracks/t3-topology/dse/veritx_dse/model/system_intent.py` :: `SystemIntentV4`

```text

    Intrinsic validation only. ``compute_instances >= world_size`` is a
    cross-domain placement feasibility check and is deliberately absent —
    SYSTEM must be valid independently of any workload.
```

## `tracks/t3-topology/dse/veritx_dse/model/topology_artifact.py` :: `MaterializedFamily`

```text

    This is a PROVENANCE/CLASSIFICATION marker, not a topology algorithm.
    CUSTOM means "the graph came from an explicit topology description
    (TopologyIR)", not "a custom algorithm ran". Membership here does NOT
    imply a family is authorable or routable: see
    docs/product/topology-family-registry.yaml, which is the stage
    authority (RING is materializable and deliberately not authorable).
```

## `tracks/t3-topology/dse/veritx_dse/model/topology_artifact.py` :: `materialize_flatfly`

```text

    Shape: ``k ** n`` routers, each with radix ``r = concentration +
    (k - 1) * n``. In each of the ``n`` dimensions a router connects to
    every other router that differs only in that dimension, giving
    ``(k - 1) * n`` router ports per router and ``k ** n * (k - 1) * n / 2``
    undirected links.

    Every link is an ordinary point-to-point channel. FlatFly needs NO new
    channel primitive, which is why it is the first non-mesh proof family
    rather than GEC (GEC-MECS is a single express channel *tapped* to many
    destinations — multidrop, not representable as DirectedChannels
    without semantic loss).

    Canonical numbering is row-major over dimensions, matching the grid
    families' convention: ``coord_i = (router_id // k**i) % k``.
```

## `tracks/t3-topology/dse/veritx_dse/model/topology_artifact.py` :: `materialize_ir`

```text

    The existing ``model.topology_ir`` module is the canonical custom
    topology contract: strict schema, undirected explicit links, self-loop
    and duplicate and range validation, and NO required coordinates. This
    function is the missing half — lowering that intent to the canonical
    artifact. It is the ONLY place an explicit graph becomes a
    TopologyArtifact.

    COORDINATE LAW (see FEATURE-RECLAMATION-AMENDMENT.md):
      * ``coordinates`` is OPTIONAL and SCIENTIFIC. Supply it only when
        physical placement is a real fact (it feeds link length, allowed
        links, latency and physical cost). When supplied, it is
        identity-bearing.
      * When omitted, routers carry ``coordinates=()`` and the artifact is
        coordinate-free. The 2D Fabric Inspector derives a
        presentation-only layout at render time; that layout is NEVER
        persisted into a design, topology or evidence hash.

    UNIT GAP (explicit, not hidden): TopologyIR carries ANALYTICAL link
    attributes (``bandwidth_GBs``, ``latency_ns``). DirectedChannel carries
    PHYSICAL units (``width_bits``, ``latency_cycles``). Converting ns to
    cycles requires a clock that TopologyIR does not carry, so this
    function does NOT guess: the caller supplies the canonical channel
    properties. Fabricating a conversion would silently invent a clock.

    No routing, VC, turn or escape semantics are produced here. Those stay
    compiler-derived (the whole point of the authority boundary).
```

## `tracks/t3-topology/dse/veritx_dse/model/topology_artifact.py` :: `materialize_topology`

```text

    TWO TOPOLOGY SOURCES, ONE ARTIFACT (FAB-007). The request expresses
    exactly one:

      NAMED     noc_config.topology_family -> the family materializers
                (mesh / torus / concentrated_mesh / ring / flatfly)
      EXPLICIT  an explicit TopologyIR graph (kind=custom) -> materialize_ir

    Both emit the SAME `TopologyArtifact`, and nothing downstream may care
    which path produced it. There is no `if synthesized` branch anywhere
    after this function.

    GEC and fat-tree are refused rather than silently downgraded to mesh.
```

## `tracks/t3-topology/dse/veritx_dse/model/topology_artifact.py` :: `materialize_topology_intent`

```text

    This is the ONLY place a typed intent becomes a canonical artifact, and
    therefore the only place that decides whether the canonical model can
    represent a physical design at all.

    THE LAW (PHASE B.1 §16): authorability and materializability are
    different stages. An intent that describes real physical science the
    canonical artifact cannot yet represent is refused HERE, by name, with a
    typed UNSUPPORTED — never silently mapped onto a different family's
    shape.

      mesh / concentrated_mesh / torus / flatfly  -> the family materializers
      explicit graph                              -> materialize_ir
      gec (all four modes)                        -> REFUSED (PHASE D owns
                                                     the equivalence ruling)
      fattree                                     -> REFUSED (no materializer)
```

## `tracks/t3-topology/dse/veritx_dse/model/topology_intent.py` :: `ConcentratedMeshIntent`

```text

    Distinct from MeshIntent because the concentration is the scientific
    point of the family, not a default: a concentrated mesh at concentration
    1 is a mesh, and saying so explicitly is a different declaration.
```

## `tracks/t3-topology/dse/veritx_dse/model/topology_intent.py` :: `ExplicitTopologyIntent`

```text

    Carrying the graph HERE (rather than in a sibling request field) is what
    keeps v4 to ONE topology field, so two topology authorities cannot even
    be expressed.

    The graph's scientific content is design identity. Its `name` is
    presentation and is excluded — a synthesized candidate and the identical
    hand-authored graph must be the same design science.
```

## `tracks/t3-topology/dse/veritx_dse/model/topology_intent.py` :: `FatTreeIntent`

```text

    Source: `third_party/booksim2/src/networks/fattree.cpp`. The physical
    structure is fixed by two facts:

      switch_radix (source `k`)  ports per DIRECTION at a switch. A switch
                                 therefore has 2*switch_radix total ports,
                                 except at the top level which has
                                 switch_radix.
      level_count  (source `n`)  hierarchy levels.

    From those, endpoint capacity = switch_radix ** level_count and switch
    count = level_count * switch_radix ** (level_count - 1). The intent
    carries the STRUCTURE; the derived counts are properties, not knobs.

    THERE IS NO CONCENTRATION PARAMETER, and adding one would be false
    science. The source gives each BOTTOM switch exactly `switch_radix`
    terminals and no independent endpoint-per-switch input; the endpoint count
    is fixed by `switch_radix ** level_count`. A concentrated fat-tree is a
    DIFFERENT topology semantic, not something to insert silently into the
    BookSim-compatible one.

    Authorable now, materializable later — no materializer is invented here.
```

## `tracks/t3-topology/dse/veritx_dse/model/topology_intent.py` :: `GecTopologyIntent`

```text

    Source: `third_party/booksim2/src/networks/gec.cpp`. Physical facts:

      * a `grid_side_length` x `grid_side_length` grid of routers, each
        seating `concentration` endpoints;
      * `express_channel_groups_per_dimension` express-channel groups leave
        each router per dimension, each group reaching
        `destinations_per_express_channel` destinations;
      * for every NON-mesh mode the source law is

            express_channel_groups_per_dimension
              x destinations_per_express_channel
              == grid_side_length - 1

        (this is `o * d == k - 1` in the source, and it is the reason the
        express channels span the grid exactly once);
      * `mesh` mode is the nearest-neighbour graph ONLY: the partitioning
        model does not apply, so express parameters are not expressible;
      * `multidrop` mode is MECS: one shared, tapped wire per express
        channel, with several destinations reading the same transmission.

    THE MODE IS PHYSICAL SCIENCE, NOT A BACKEND KNOB. `destinations_per_
    express_channel > 1` is a legal declaration here; whether the canonical
    artifact can represent a shared resource is a MATERIALIZATION question,
    answered downstream.
```

## `tracks/t3-topology/dse/veritx_dse/model/topology_ir.py` :: `scientific_dict`

```text

        INCLUDED: kind, nodes, links, link_attrs. These are the exact
        connectivity semantics; changing any of them changes the design.

        EXCLUDED, deliberately:

          * ``name`` — a LABEL. A synthesized candidate is named
            ``synthesized-<id>`` and the identical hand-authored graph is
            named whatever the user typed. Hashing the name would make
            origin part of design identity, so the same scientific graph
            authored and synthesized would hash differently. That is the
            ownership error this method exists to prevent.
          * ``routing`` / ``booksim_params`` / ``rtl`` — backend and
            collateral POLICY, not graph science.
          * ``dims`` — an analytical-leg projection, not canonical
            connectivity.
```

## `tracks/t3-topology/dse/veritx_dse/model/vc_resource.py` :: `adaptive_escape_vc_resource`

```text

    The compiler-derived resource carries identity transitions only, which
    cannot realize the policy's adaptive->escape role transition (escape
    entry is the deadlock-freedom mechanism). This constructor extends the
    transition relation with every adaptive->escape pair while keeping
    escape VCs closed under escape (escape->escape only, via identity):
    adaptive traffic may enter the escape subfunction, escape traffic
    never leaves it. Partition (disjoint, covering, non-empty) is
    enforced.

    The executed class law: the fork allocates every class from the
    route-set envelope starting at VC 0, so each carried class maps to
    the FULL envelope here. Pass the workload's carried classes
    explicitly (never inferred); omitting them copies the base map,
    which only qualifies when it is already full-envelope.
```

## `tracks/t3-topology/dse/veritx_dse/model/vc_resource.py` :: `require_disjoint_traffic_classes`

```text

    Raises VCResourceError naming every shared VC and its classes.
    This is the predicate for proofs that need per-class VC isolation.
    It is deliberately NOT a construction rule: full-envelope overlap
    (every class carrying every VC, as the shipped MoE design does on a
    single-VC mesh) is sound — the fork executes one VC envelope and
    per-class replay keeps the classes distinct. Subset overlap, where a
    class claims isolation it cannot have, is refused at admission (see
    workload.intent_lowering.assert_traffic_classes_bound) and at
    qualification (vc_exactness in the BookSim qualifiers).
```


# `model` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/model/address_decode.py` :: `derive_address_decode`

```text

    Group placement (mapping/rank) does not participate: rank placement has
    nothing to do with NI address decode. The design-level checks (group
    exists, singleton count) fail closed with UNSUPPORTED before any
    endpoint is selected.

    v3 requests are accepted for the fields they share with v2 (agents,
    address_map); the v3-only schema is never reinterpreted as v2.
```

## `tracks/t3-topology/dse/veritx_dse/model/attachment.py` :: `derive_attachment`

```text

    Baseline policy: routers in id order, seats 0..capacity-1 within each
    router, agents in canonical NodeInventory order. Deterministic, no
    optimizer.

    Inputs are the design revision (agent universe + interface
    semantics), the NodeInventory (canonical agent order), and the
    TopologyArtifact (seats). MappingArtifact deliberately does not
    participate: rank placement is not hardware attachment identity.
```

## `tracks/t3-topology/dse/veritx_dse/model/attachment.py` :: `validate_against`

```text

        DesignRevision and NodeInventory are validation sources, not
        identity parents: this proves the attachment corresponds to them
        without hashing them. Hardware-local seat legality is delegated
        to ``validate_against_topology`` so FabricArtifact can prove it
        without design context — no duplicated implementation.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `Artifact`

```text

    Each artifact (RTL file, UVM testbench, report, manifest) is
    tracked with its checksum and signature for provenance.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `PhysicalContext`

```text

    PRD §4.2 lists these as per-agent attributes, but they also
    have system-level defaults. This captures the system-level context.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `Result`

```text

    Captures the numeric outcomes from BookSim simulation and
    area/power/timing estimation. Frozen for immutability.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `VCAssignment`

```text

    This is the LOCKED output that the user cannot override.
    It determines the fabric's virtual channel structure.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `_routing_for_cycle_structure`

```text

    Restates the sealed v2 law (derive_vc_assignment: no cycles →
    dim_order; cycles → dor/min_adapt by count with matching turn
    restrictions). Restated — not shared — because the v2 function body
    is frozen; a cross-check test pins v2/v3 parity for identical
    dependency structures, so drift fails loudly instead of silently.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `canonical_dict`

```text

        Ordering mirrors v2 (requirements/address-ranges/output-formats/
        dependencies canonicalized) EXCEPT collectives, which stay in
        declared order: collective index feeds the lowering's operation
        chain, so declaration order is v3-semantic (reordering intents is
        a different design).
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `derive_v3_traffic_classes`

```text

    Sorted distinct CollectiveIntent.traffic_class values. Dependency
    endpoints, RequirementV3.traffic_class scopes, VC artifact classes,
    and LogicalMessage classes MUST be drawn from this set: the
    evaluator admission gate refuses any message class outside the VC
    artifact instead of silently mapping to VC0.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `derive_vc_assignment_artifact_v3`

```text

    Same binding law as derive_vc_assignment_artifact: every VC names a
    routing class of the resolved route, and every route class is served
    by at least one VC (an unserved class would be unroutable hardware).
    The derivation string is provenance naming v3 inputs (declared
    classes, victims, no concurrent-context floor).
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `fabric_intent_view`

```text

    v2 traffic classes are the dependency endpoint names (v2 declares no
    classes; the VC derivation serves exactly the dep-graph namespace —
    same set derive_vc_assignment covers). v3 classes come from
    derive_v3_traffic_classes (the declared intent registry). Anything
    else refuses: the compiler never guesses a generation.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `from_csv`

```text

        Expected columns: name, base (hex or int), size (hex or int), target_agent_idx (optional).
        Lines starting with '#' are comments. Empty lines are skipped.

        Example CSV:
            name,base,size,target_agent_idx
            HBM0,0x00000000,0x10000000,0
            SRAM0,0x20000000,0x00100000,1
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `from_dict`

```text

        Fails closed on: unknown fields at any level, missing or
        unsupported schema_version, unsupported compiler_semantics_version,
        and any value that cannot represent a design. A supplied
        design_hash/guardrail_hash must match the recomputed identity under
        the DECLARED compiler semantics (a legacy v1 document validates
        under v1 rules). Loading never migrates: see migrate_design().
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` :: `identity_dict`

```text

        artifact_identity is PROVENANCE (which producer handed us the
        bytes), never authority: two references to the same bytes from
        different producers MUST hash identically, so it is excluded
        here. CompileRequestV3.canonical_dict() consumes ONLY this
        representation.
```

## `tracks/t3-topology/dse/veritx_dse/model/compile_request_v4.py` :: `migrate_v2_to_v4`

```text

    Every explicit supplemental fact demanded by either step must be
    supplied; nothing is defaulted. v2 cannot express a topology shape at
    all, so in practice `topology_intent` is required for anything but the
    legacy implicit mesh.
```

## `tracks/t3-topology/dse/veritx_dse/model/mapping.py` :: `derive_mapping`

```text

    Baseline P1 policy: rank r takes the r-th compute instance in
    canonical NodeInventory order. This is not an optimizer and not
    physical placement. If the workload has more ranks than compute
    instances the placement is infeasible and refused — never
    oversubscribed or modulo-mapped.
```

## `tracks/t3-topology/dse/veritx_dse/model/placement.py` :: `LogicalRank`

```text

    ``rank`` is the global id; ``tp``/``pp``/``ep``/``dp`` are COORDINATES
    (indices into the shape), never the shape sizes.
```

## `tracks/t3-topology/dse/veritx_dse/model/presets.py` :: `_parse_anynet_adj`

```text

    Delegates to core.anynet — the ONE parser implementing BookSim's
    anynet.cpp grammar (both line dialects, auto-symmetrized edges).
    History: this parser required >=5 tokens and peer-scanning from
    index 4, so two-line link files (configs/anynet16.links style)
    yielded EMPTY adjacency → count 0 / "disconnected".
```

## `tracks/t3-topology/dse/veritx_dse/model/presets.py` :: `parallel_world_size`

```text

    NOTE on the MoE convention question: expert (ep) ranks each hold a
    shard of the MoE layer and collectively span the same device mesh as
    the tp×pp×dp grid in this codebase's accounting (cf. compile
    total_npus = tp×ep for MoE, which ignores pp/dp). This helper reports
    the full product — the conservative upper bound for typo-guard style
    checks. Do NOT substitute it into compile sizing without sim-owner
    review; the sizing path keeps its own rule deliberately.
```

## `tracks/t3-topology/dse/veritx_dse/model/resolved_fabric.py` :: `make_resolved_fabric`

```text

    Reclaimed adapter (veritx-integrate): the RT compile path composes the
    child artifacts itself and binds them through this one seam. Identity
    is the canonical triple (design_hash, mapping_hash, fabric_hash); the
    child artifacts are accepted as already-resolved authorities exactly
    as RT composed them — composition only, no child is rederived.
```

## `tracks/t3-topology/dse/veritx_dse/model/routing.py` :: `_anynet_min_hops_policy`

```text

    `weight_metric: hop_count` + `tie_break_policy: anynet_ascending_min`
    select the ANYNET_MIN_HOPS realization in routing_materialize, whose
    first-hop table is `route_entries_from_adj` — the documented replica of
    `AnyNet::route()`. Because it IS the fork's algorithm, the certified
    AnyNet profile accepts it and BookSim route equivalence holds by
    construction rather than by hope.
```

## `tracks/t3-topology/dse/veritx_dse/model/routing.py` :: `_weighted_shortest_path_policy`

```text

    Exactly the representability profile `routing_materialize` accepts:
    STATIC / SINGLETON / ROUTE_COMPUTE / randomness NONE, no state, no
    runtime observations, one DEFAULT resource role, no transitions.

    `deadlock_proof_obligation` is DETERMINISTIC_CDG: the OBLIGATION to run
    the channel-VC dependency-graph check is declared here and discharged
    downstream by the normal DEADLOCK_FREE obligation. Declaring it is not
    passing it, and this policy makes no deadlock claim of its own.
```

## `tracks/t3-topology/dse/veritx_dse/model/routing_policy.py` :: `DeadlockProofObligation`

```text

    Naming the obligation is not passing it: no member of this enum is a
    verdict, and this artifact carries no verdict field.
```

## `tracks/t3-topology/dse/veritx_dse/model/routing_realization.py` :: `deterministic_vc_routing_semantics_hash`

```text

    The generic VC universe, traffic-class eligibility and legal concrete
    transitions are owned by ``VCResourceArtifact``. ``resolved_route_hash``
    is already bound by the deterministic ``routing_semantics_hash``.
    ``escape_vcs`` is a proof/interpretation designation consumed only by
    verification modules, not by canonical execution semantics, so it is
    excluded.
```

## `tracks/t3-topology/dse/veritx_dse/model/routing_relation.py` :: `RoutingContext`

```text

    ``current_role_id is None`` is the injection/source context (no routing
    resource role is held yet); it is not a declared routing resource role.
```

## `tracks/t3-topology/dse/veritx_dse/model/system_intent.py` :: `ContainerKind`

```text

    ``BOARD`` is added only when a concrete use exists; ``CUSTOM`` is
    refused rather than used to dodge deciding semantics.
```

## `tracks/t3-topology/dse/veritx_dse/model/topology_artifact.py` :: `materialize_gec_express`

```text

    k x k routers in row-major coordinates; every router connects to
    every other router in its row and column (full express span, the
    o=k-1, d=1 corner). Every link is an ordinary DirectedChannel — no
    new primitive, which is why EXPRESS precedes MECS. Degree grows
    with k (paper port count ``pout = c + 2(k-1)``): callers enforce
    radix budgets, never this function silently.
```

## `tracks/t3-topology/dse/veritx_dse/model/topology_intent.py` :: `GecMode`

```text

    `mesh` and `hybrid` are mutually exclusive in the source; `mesh` forbids
    the express-channel partitioning entirely.
```

## `tracks/t3-topology/dse/veritx_dse/model/topology_intent.py` :: `topology_intent_from_noc_config`

```text

    This is the compatibility layer used by the internal normalization seam.
    It is NOT a second authority: the typed intent is derived from the legacy
    spelling, so the two can never disagree.

    It deliberately REFUSES families whose legacy spelling does not determine
    a physical design (GEC's four modes, fat-tree's structure) rather than
    defaulting to a plausible-looking guess.
```

## `tracks/t3-topology/dse/veritx_dse/model/topology_ir.py` :: `to_booksim_cfg`

```text

    anynet kinds (star/switch/anynet/custom) REQUIRE network_file — the
    caller writes to_anynet() output and passes its path (absolute at run
    time; astrasim_adapter absolutizes). No injection_rate is emitted:
    standalone runs set their own, and the ASTRA leg MUST pass
    --booksim2-extra=injection_rate=0.0 (embedded mode owns injection).
```

## `tracks/t3-topology/dse/veritx_dse/model/vc_assignment.py` :: `_authoring_rows`

```text

    Accepts a mapping or a sequence of pairs. A ``str`` is refused here:
    iterating it yields characters, which is never a row sequence, and
    silently repairing one is how malformed authoring becomes a fabric.
    Duplicate keys are deliberately NOT collapsed — the caller decides
    whether a repeated key is an authoring error.
```

## `tracks/t3-topology/dse/veritx_dse/model/vc_assignment.py` :: `make_vc_assignment_artifact`

```text

    Defaults encode the honest state of the world, not a desired proof:
      * every VC uses the resolved route's default routing class;
      * allowed transitions are VC-preserving only (a packet does not
        switch VCs unless a class says so — silent cross-VC hops are how
        deadlock proofs get falsified);
      * no escape VC is designated.
```
