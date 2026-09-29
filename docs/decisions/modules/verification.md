# `verification` — extracted module rationale

Extracted from the module docstrings of `veritx_dse/{name}` by the 2026-09-29 debloat. Code keeps a one-line pointer; this is the original long-form text.

## `tracks/t3-topology/dse/veritx_dse/verification/adaptive_escape.py`

```text
veritx_dse.verification.adaptive_escape — v1 escape-subfunction proof.

SROTA's first independent adaptive-routing deadlock certificate. It consumes
five canonical parents:

    TopologyArtifact
    RoutingPolicyDefinition
    RoutingRelationArtifact
    VCResourceArtifact
    RoutingResourceBindingArtifact

and proves the structural conditions of SROTA's v1 escape-subfunction model:

  1. every adaptive routing context has a legal action into the escape role;
  2. source/injection routing can enter the escape role;
  3. the escape subfunction is closed (deterministic, escape-only);
  4. every source reaches every destination through escape routing;
  5. the concrete ``(channel, escape-VC)`` dependency graph is acyclic.

It does NOT prove arbitrary adaptive routing. A PASS is scoped to this
structural model and explicitly does not certify allocator fairness, backend
implementation equivalence, traffic-class injection eligibility, protocol
blocking, packet/flit buffering, multicast, or arbitrary stateful adaptive
routing. Routing roles are identified by ``RoutingResourceRole.kind``, never
by literal role names, and no legacy ``escape_vcs`` field is consulted.

Malformed or tampered parents raise ``AdaptiveEscapeVerificationError``;
``UNSUPPORTED`` is reserved for valid inputs outside the v1 profile.
```

## `tracks/t3-topology/dse/veritx_dse/verification/certificate.py`

```text
veritx_dse.verification.certificate — resolved-fabric verification (P1.4).

Before a fabric is called "compiled", it is certified. A
VerificationCertificate binds the resolved fabric to one verdict per
LOCKED obligation, each with its method and evidence digests — never
a generic {"verified": true}.

Obligations (P1A slice):

    TOPOLOGY_CONNECTED   underlying router graph is one component
    ATTACHMENT_COMPLETE  every design agent is attached (seats proven)
    ADDRESS_DECODE_VALID decode realizes the design address map
    ROUTE_COMPLETE       route table covers every class×src×dst pair
    ROUTE_LEGAL          every route is channel-legal and terminates
    VC_ASSIGNMENT_VALID  VC structure binds the resolved route
    DEADLOCK_FREE        (channel,VC) CDG is acyclic (typed proof)
    MAPPING_VALID        every mapped rank lands on an attached agent
    PACKET_FORMAT_VALID  wire format fits topology/attachment/VC bounds
    FABRIC_DAG_VALID     full hardware + design/mapping seam revalidates

A LOCKED obligation that is not PASS means the fabric is not
presented as compile success: the FabricCompiler returns INVALID
with this certificate as evidence. No obligation may be skipped,
downgraded, or satisfied by assumption.

Method migration (P1B): the DEADLOCK_FREE obligation method moved from
``channel-vc-cdg/v1`` to ``channel-vc-cdg/v2``. v1 certified the
(channel, VC) CDG with ``router_behavior_hash=""`` (the deadlock proof
floated free of the router behavior it was proven about); v2 binds the
live ``bundle.router_behavior.router_behavior_hash()`` and preserves the
authenticated parent hashes in the obligation evidence. The proof itself
(``CHANNEL_VC_DEPENDENCY_ACYCLIC`` over the realized CDG) is unchanged —
only the binding moved — so a v1 certificate ID and a v2 certificate ID
for the same fabric DIFFER, by design: the v2 ID commits to strictly more
provenance. There is no v1→v2 migration of persisted IDs; re-certify.
```

## `tracks/t3-topology/dse/veritx_dse/verification/channel_vc_cdg.py`

```text
veritx_dse.verification.channel_vc_cdg — independent (channel, VC) CDG.

Dally–Seitz: a routing function is deadlock-free when the channel dependency
graph over the resources a packet can WAIT for is acyclic. With virtual
channels the resource is exactly ``(directed_channel_id, vc_id)``, so the
graph must be built over those resources and their VC transitions, never
over physical channels alone.

Nodes: every directed topology channel × every VC id in the VC artifact.
Edges: a packet holding ``(c_in, vc_in)`` that reaches router ``v`` en route
to destination ``d`` may request the exact outgoing channel its NEXT class
selects for ``(v, d)``, for every allowed transition ``vc_in -> vc_out``.

Routing-class convention (corrected):

    class_in  = routing_class(vc_in)    # the class that chose c_in
    class_out = routing_class(vc_out)   # the class that chooses the next hop

The HELD channel comes from ``class_in``'s route table; the REQUESTED channel
comes from ``class_out``'s route table. Deriving both sides from ``class_out``
is wrong: it invents dependencies for packets that never travelled the
``class_out`` path. This verifier consumes the candidate VCAssignmentArtifact
as given and judges it independently of whatever policy produced it.

Honest scope:

  * routing + VC dependency proof only — the attachment hash is carried
    transitively from the ResolvedRouteArtifact, but attachment completeness
    is NOT recertified here;
  * buffering/credits are not modeled; ``CHANNEL_VC_DEPENDENCY_ACYCLIC``
    needs no allocator semantics;
  * a VC bound to a routing class the router route did not materialize is
    UNSUPPORTED, never a guessed PASS;
  * a designated escape VC is evidence only: it is reported, and it NEVER
    bypasses graph analysis or produces PASS by itself.

Malformed or tampered parents raise ``CDGError``; they are never converted
into UNSUPPORTED or PASS. A cyclic graph FAILs with a deterministic witness.
```

## `tracks/t3-topology/dse/veritx_dse/verification/gates.py`

```text
veritx_dse.verification.gates — pre-spawn and post-drain gates.

A gate is a VERIFIER: it inspects a model/workload artifact (or sealed
backend evidence) and either passes or refuses. It is not part of the
artifact it checks, and it must not be.

Ownership (slice 2b): these gates used to live on the Wave-D artifact
module (``waved/backend.py``) and partly inside the artifacts
themselves. Moving an artifact must not move its checker.

Dependency law: this module imports ``core`` and ``verification`` only.
It must NOT import ``backend`` — the trace-projection differential needs
the renderer and therefore lives with the renderer in
``backend/projection.py``. A verification module importing a backend is
how the DAG gets a cycle.
```

## `tracks/t3-topology/dse/veritx_dse/verification/protocol_vc.py`

```text
veritx_dse.verification.protocol_vc — E4 BLOCKING dependency separation.

This is an independent verifier, not a routing verifier and not a VC
generator. It answers exactly one question:

    Given a CompileRequest E4 dependency graph and a candidate
    traffic-class → VC mapping, does VC isolation separate every
    BLOCKING dependency cycle?

Model (explicitly assumed, not proven here):

    for each BLOCKING edge  src -> dst:
        shared = VCs(src) ∩ VCs(dst)
        shared non-empty  ->  the dependency remains coupled
        shared empty      ->  the dependency is separated

The coupled BLOCKING subgraph must be acyclic for PASS. This assumes that
disjoint virtual channels isolate the protocol buffering dependency the E4
edge represents; it does NOT model allocator/buffer credit semantics, it
does NOT prove channel-routing deadlock (that is the channel×VC verifier's
job), and it does NOT certify collective concurrency. The two verifiers
must agree independently before a candidate is accepted.

Multi-VC classes are handled conservatively: any shared VC keeps the edge
coupled. No "convenient VC" is chosen to make a proof pass.

Malformed candidates fail closed: a traffic class that appears in a
BLOCKING edge but has no VC mapping raises ``ProtocolVCError`` — never
PASS, never UNSUPPORTED. Collectives are recorded as NOT_MODELED evidence
and never contribute VCs or alter the E4 verdict.
```

## `tracks/t3-topology/dse/veritx_dse/verification/reference_semantics.py`

```text
veritx_dse.verification.reference_semantics — independent pure reference models (§26).

These oracles are structurally independent of the production lowering:
they never import or call it. They exist so Wave-D tests can prove the
production implementations with ``production(x) == oracle(x)`` instead of
the forbidden ``production(x) == production(x)``.

Simplicity is a requirement (§26): each oracle is the closed-form
equation itself, not a second simulator.
```

## `tracks/t3-topology/dse/veritx_dse/verification/uvm_gen.py`

```text
veritx_dse.uvm_gen — PRD §9.3: UVM testbench generator.

Generates SystemVerilog UVM verification collateral for NoC fabrics:
  - tb_noc.sv: Top-level testbench with DUT instantiation
  - seq_lib.sv: Sequence library (injected, random, directed, VC-separation)
  - assertions.sv: F1-F8 formal properties as SVA assertions
  - cov.sv: Coverage model (cross-coverage: traffic class × latency bucket)

Design principles:
  - Generator takes CompileRequest + topology params → emits SV strings
  - No hardcoded node counts — derived from agents tuple
  - No hardcoded topology — derived from NocConfig
  - Every assertion references PRD § section for traceability
```


# `verification` — extracted inline comments

## `tracks/t3-topology/dse/veritx_dse/verification/adaptive_escape.py`

line 266:

```text
# ── MIN_ADAPT_MESH qualification envelope ──────────────────────────────
#
# The escape certificate proves deadlock-structure; this envelope binds it
# to the executable selection (backend routing function + VC partition +
# realization) with an explicit fidelity distinct from the deterministic
# static first-hop envelope. Runtime route selection stays allocator-
# observed: qualification covers the declared policy/profile, the escape
# semantics and the candidate-set scope — never a certified packet path.
```

## `tracks/t3-topology/dse/veritx_dse/verification/certificate.py`

line 22:

```text
#: The ONLY exception classes an obligation may turn into a design verdict.
#: Semantic artifact errors now inherit ``SemanticError`` (which is a
#: ``VeritXError``), so this catches the taxonomy — never Python's
#: built-in ``ValueError``. Anything else — AttributeError,
#: NameError, TypeError, RuntimeError, MemoryError — is a software fault in
#: a trusted internal function and MUST abort certification instead of being
#: laundered into FAIL. The set is deliberately an allow-list: a new error
#: type that is not semantic fails closed (aborts) rather than passing.
```

line 231:

```text
    # The diagnostic rebuild below shares this guard: a semantic failure
    # at any point (proof or post-PASS reconstruction) refuses the
    # obligation via _fail, while a programming fault propagates as an
    # internal error — never an uncontrolled post-PASS exception.
```

line 246:

```text
        # Preserve the authenticated parent identities in the obligation
        # evidence itself: the DeadlockCertificate object is dropped after
        # this function returns, so without these the certificate would name
        # a deadlock verdict it cannot tie to the exact artifacts proven.
```

line 261:

```text
        # Required diagnostic evidence: the SCC count is part of the
        # DEADLOCK_FREE PASS record. It shares the same validated inputs
        # the verdict just ran on. A semantic failure here refuses the
        # obligation (same vocabulary as the proof); only a programming
        # fault escapes, as an internal error.
```

## `tracks/t3-topology/dse/veritx_dse/verification/channel_vc_cdg.py`

line 23:

```text
#: Expansion marker recorded on the realized graph and the certificate
#: evidence. ``dateline_restricted`` is the ONLY non-generic expansion:
#: the DOR_TORUS_XY dateline-partition discipline (see below).
```

line 311:

```text
            # Tie mirrors are per-PHASE geometric runs spliced with the
            # canonical other phase: every included run stays minimal in
            # each phase (no long-way phantoms).
```

line 470:

```text
    # The held channel is chosen by class_in; the requested channel is
    # chosen by class_out. A transition between routing classes therefore
    # crosses the dependency exactly once.
    # Every VC the transition relation can wait on must name its routing
    # class: without it the graph cannot choose a route table, and a bare
    # KeyError would crash certification instead of refusing the proof.
```

line 482:

```text
    # The edges below are complete for the resources packets can WAIT
    # for: (channel, VC) pairs with transitions from the assignment.
    # Traffic classes SHARING one VC add no new wait resource — the
    # shared VC is one node regardless of how many classes use it — so
    # same-routing-class sharing (as the shipped MoE design does on one
    # VC) is analyzed exactly, not waved through: the acyclicity verdict
    # covers it. Cross-table inconsistency is refused above and by the
    # admission layer, never silently proved.
```

## `tracks/t3-topology/dse/veritx_dse/verification/reference_semantics.py`

line 202:

```text
# ── verifiers moved out of the artifacts (slice 2b) ─────────────────────
# An artifact must not carry its own differential check: the check would
# then live inside the thing it checks, and the artifact would depend on
# the reference module. These functions are the verifier side of that
# seam. Callers: the verified loaders, the service, the projection gates.
```

line 301:

```text
        # NB: message COUNT is confirmatory here — the production spec and
        # this reference are two implementations of the same pinned
        # equation, and expansion reads the spec. The BYTE total below is
        # the differential: production sums generated messages, this
        # reference computes the law independently.
```


# `verification` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/verification/channel_vc_cdg.py` :: `DeadlockCertificate`

```text

    ``evidence`` is frozen at construction into an immutable value tree, so
    caller-owned dictionaries/lists cannot mutate the result and callers
    cannot mutate it through the attribute. ``to_dict()`` returns a fresh
    thawed copy on every call.

    The certificate carries the attachment hash transitively from the
    ResolvedRouteArtifact; it does not certify attachment semantics.
```

## `tracks/t3-topology/dse/veritx_dse/verification/channel_vc_cdg.py` :: `_dateline_restricted_edges`

```text

    With vc_ids (0, 1) the fork's per-half VC ranges are singletons, so
    every packet's (channel, VC) trajectory is FORCED: X-run on VC
    ``P_X``, turn into VC ``P_Y``, Y-run on VC ``P_Y`` — each half the
    endpoint-derived :func:`dateline_partition` of its phase.
    Within-phase edges stay inside one half; turn edges go X -> Y only
    (possibly cross-VC). DOR never returns to X, so any cycle lies
    inside one (phase, half) layer, and each layer is acyclic.

    Turn VC-changes are the fork's movement between owned resources
    (``dim_order_torus`` re-narrows the offered range at every turn;
    offered singletons leave the allocator no choice). The identity
    transitions are the per-half VC-ownership statement — each VC serves
    exactly one partition, never pooled — not a prohibition the executed
    system obeys at turns. Modeling the executed dynamics is what makes
    the verdict sound; the generic expansion would model a system that
    does not exist.

    Midpoint ties (even k): the fork resolves them randomly, so BOTH
    directions' runs are included with the (direction-independent)
    endpoint halves. Every mirror channel must exist in the topology or
    the proof refuses (fail-closed).
```

## `tracks/t3-topology/dse/veritx_dse/verification/protocol_vc.py` :: `ProtocolVCCertificate`

```text

    ``evidence`` is frozen at construction, so caller-owned mappings and
    lists cannot mutate the certificate and callers cannot mutate it through
    the attribute. ``to_dict()`` returns a fresh thawed copy each call.
```

## `tracks/t3-topology/dse/veritx_dse/verification/reference_semantics.py` :: `ref_collective_messages`

```text

    Participant indices are 0..k-1 within the collective's participant
    tuple (canonical order = ring order).

    Ring law, implemented from first principles (NOT copied from the
    production spec): in a ring collective data moves ONLY between logical
    neighbours — every step, rank i sends one chunk to rank (i+1) mod k.
    The CHUNK ownership rotates around the ring; the network edge does not.
    The message-level accounting abstracts chunk identity away (all
    messages of a step carry the same byte count), matching the §10.1
    contract which pins counts and bytes, not per-message chunk ownership.

    ALLREDUCE has two logical phases over the same edge set:
      steps [0, k-2]       reduce-scatter
      steps [k-1, 2k-3]    all-gather
```


# `verification` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/verification/gates.py` :: `assert_workload_ready`

```text

    Order is deliberate: the logical/physical seam, then the intrinsic
    message conservation, then the independent reference differentials,
    then the physical conservation laws. A backend must never receive
    traffic from an artifact that failed any of these.

    This is artifact-only by design. The rendered-trace projection is a
    property of the RENDERER and is checked in backend/projection.py
    immediately after rendering, where the grammar lives.
```

## `tracks/t3-topology/dse/veritx_dse/verification/protocol_vc.py` :: `certify_protocol_vc_separation`

```text

    PASS: the coupled BLOCKING subgraph is acyclic.
    FAIL: a deterministic coupled cycle witness exists.
    Malformed candidates (missing traffic-class mapping, bad parent types)
    raise ProtocolVCError; collectives are recorded as NOT_MODELED and never
    change the E4 verdict.
```

## `tracks/t3-topology/dse/veritx_dse/verification/reference_semantics.py` :: `verify_logical_messages_reference`

```text

    Distinct from ``validate_conservation``: that one proves generated
    == declared schedule (an intrinsic invariant), this one compares
    against an independent implementation of the law.

    Generation-aware: v1 iterates the OperationGraph side lists; v2
    iterates the schedule records the canonical lowering selected.
```
