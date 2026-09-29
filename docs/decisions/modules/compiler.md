# `compiler` — extracted module rationale

Extracted from the module docstrings of `veritx_dse/{name}` by the 2026-09-29 debloat. Code keeps a one-line pointer; this is the original long-form text.

## `tracks/t3-topology/dse/veritx_dse/compiler/candidate_policy.py`

```text
veritx_dse.compiler.candidate_policy — baseline candidate generation.

The first explicit CANDIDATE GENERATION policy above the Slice-23
canonical candidate compiler. It converts a ``CompileRequest`` into an
explicit candidate plan:

    CompileRequest
          |
          v
    CANDIDATE GENERATION POLICY   (this module)
          |
          v
    explicit mapping / routing / VC / settings
          |
          v
    Slice-23 canonical compiler
          |
          v
    ResolvedFabric

Division of authority:

    candidate_policy:  "Here is a candidate worth compiling."
    canonical compiler: "Given this exact candidate, here is the
                          exact hardware."
    verifier:          "Here is what we can prove about that
                          hardware."
    evaluator:         "Here is how it performs."

This module does NOT compile, claim correctness, prove deadlock freedom,
score performance, or check backend capability. It makes one versioned
statement: ``BASELINE_DETERMINISTIC_V2`` proposes this exact candidate
for this design.

POLICY VOCABULARY

``CandidatePolicy.BASELINE_DETERMINISTIC_V2``
    The only policy implemented. It is one versioned policy, not a
    "default" and not universally preferred. It proposes DOR_XY routing,
    dependency-cycle-derived VC separation, rank-order mapping and the
    historical-baseline compile settings.

    V1 HISTORY: ``BASELINE_DETERMINISTIC_V1`` was superseded before any
    durable application persistence existed because its dependency-cycle
    witnesses were not cross-process deterministic (Python set/hash
    iteration and dependency declaration order could change the proposed
    hardware). V2 consumes the deterministic semantics-v2 graph
    traversal and is current; the closed vocabulary carries V2 only.

``MappingPolicy.RANK_ORDER_V1``
    The only mapping policy. Rank r maps to the r-th canonical compute
    ``AgentInstance`` via the sealed ``derive_mapping(design)``. Candidate
    generation is precisely the layer that owns this choice; Slice 23
    still receives the resulting ``MappingArtifact`` explicitly.

BASELINE_DETERMINISTIC_V2 SEMANTICS (all PROPOSALS, never theorems)

    traffic classes : sorted unique {dependency.source, dependency.target};
                      FAIL CLOSED if none (no invented "default" class)
    blocking cycles : canonical ``DependencyGraph.find_cycles()``
                      (deterministic DFS back-edge witnesses of the
                      BLOCKING subgraph — not an exhaustive enumeration
                      of every mathematical simple cycle)
    cycle victims    : per cycle, member minimizing
                      (BLOCKING out-degree, class name) — deterministic,
                      lexically tie-broken, independent of traversal order
    vc_count         : 1 + len(UNIQUE victims)   [authoritative formula]
                      duplicate victims reuse their separated VC; no
                      unused VC is allocated for a duplicate cycle
    traffic class -> : every unique victim gets its own VC (VC1, VC2, ...)
    one VC           in sorted victim order; all other classes -> VC0;
                      every class maps to exactly one VC
    vc -> routing    : every VC maps to DOR_XY (no modulo, no fallback)
    transitions      : identity only  i -> i
    escape_vcs       : ()  (no escape designation)
    collectives      : FAIL CLOSED for any group_size > 1
                      (group_size == 1 consumes no fabric resource)

    No clamp exists here: a design proposing 9 VCs generates 9 VCs.
    Backend/resource capability checks belong downstream.

PROVENANCE IS NOT AUTHORITY

``DeterministicVCSpec.derivation`` records the policy version, chosen
victims and proposed count for diagnostics. Slice 8 excludes derivation
from VC identity; it never acts as semantic authority.

Dependency direction: ``semantic model <- candidate_policy <- future
application / search / DSE``. ``candidate_policy`` may construct inputs
consumed by ``canonical.py``; ``canonical.py`` must never import this
module.
```

## `tracks/t3-topology/dse/veritx_dse/compiler/canonical.py`

```text
veritx_dse.compiler.canonical — canonical candidate compiler.

One orchestration path that takes an exact ``CompileRequest``, an exact
placement (``NodeInventory`` + ``MappingArtifact``), and an **explicit
compiler-owned candidate recipe**, and mechanically derives the sealed
artifact DAG through ``ResolvedFabric``.

    CompileRequest + Inventory + Mapping + candidate recipe
            |
            v
    one orchestration path
            |
            v
    ResolvedFabric

This module compiles exactly ONE fully specified candidate. It does NOT:

    * choose a routing algorithm or deterministic vs adaptive;
    * choose VC count, VC partition, escape resources;
    * choose packet limits or router buffers;
    * derive the mapping (mapping is a candidate dimension and is supplied);
    * search, rank, score or evaluate requirements;
    * run verification or certificates;
    * lower to a backend or write any output.

Those choices are candidate semantics and must be supplied explicitly.
Candidate generation/search lives above this seam and funnels every
candidate through this exact compiler.

Terminal identity is ``ResolvedFabric.resolved_fabric_hash``. The
``CompiledFabric`` bundle returned here is orchestration transport only:
it carries no independent content hash and is not another semantic
artifact.
```

## `tracks/t3-topology/dse/veritx_dse/compiler/orchestration.py`

```text
veritx_dse.compiler.orchestration — bundle compiler (orchestration).

The compiler sequences the SEALED Wave-B derivation only:

    CompileRequest -> inventory -> mapping -> topology -> attachment
    -> route -> resolved route -> VC -> vc resource -> routing
    realization -> packet format -> router behavior -> address decode
    -> fabric -> resolved fabric -> validated bundle

It derives NOTHING semantic itself: no routes, no VC assignment, no
packetization, no profile values. New semantic logic here would be a
second authority and is forbidden.

Reclamation note (veritx-integrate): the historical RT-candidate seam
composed FabricArtifact v1 children (resolved_route_hash +
vc_assignment_hash). The canonical FabricArtifact is the single fabric
authority; this seam now derives the two canonical children
(``vc_resources_from_assignment`` and
``make_deterministic_routing_realization``) exactly as
``compiler.canonical.compile_deterministic_candidate`` does and composes
through canonical ``make_deterministic_fabric``. No second artifact
class exists.
```


# `compiler` — extracted inline comments

## `tracks/t3-topology/dse/veritx_dse/compiler/candidate_policy.py`

line 27:

```text
# Historical-baseline candidate settings (Slice-17/Slice-18 canonical
# baseline: input depth 8, output stage 1; Slice-17 deliberately has no
# default for max_packet_flits — the pinned baseline fixtures use 8).
```

line 34:

```text
#: THE single definition of the baseline hardware settings (C2.1). The v3
#: orchestration and this policy both consume it, so the values cannot
#: drift by independent literals.
```

line 163:

```text
    # Authoritative formula: one separated VC per UNIQUE victim. Duplicate
    # victims (two cycles separable by the same class) reuse that class's
    # VC; no unused VC is allocated from a duplicate cycle discovery.
```

## `tracks/t3-topology/dse/veritx_dse/compiler/orchestration.py`

line 15:

```text
# There is no derivation sequencer here. Both entry points build their
# candidate semantics (route / resolved route / VC assignment) and funnel
# through ``compiler.canonical.compose_deterministic_candidate`` (C2.1),
# the one deterministic derivation engine. The baseline hardware settings
# live in ``candidate_policy.BASELINE_FABRIC_SETTINGS``.
```

line 58:

```text
        # Typed semantic refusal -> product outcome. A programmer fault
        # (AttributeError/TypeError/RuntimeError/NameError) is NOT a
        # semantic result and must propagate, not be laundered into
        # UNSUPPORTED_SEMANTICS.
```

line 175:

```text
            # A typed semantic refusal is a stage refusal; a programmer
            # fault must propagate rather than be laundered into a staged
            # capability result.
```

line 230:

```text
        # v3 intent interpretation produces explicit candidate semantics
        # (inventory/mapping/topology/attachment/route/resolved_route/VC);
        # everything downstream is the ONE canonical derivation engine.
```

line 270:

```text
        # Typed semantic refusal -> product outcome. A programmer fault
        # (AttributeError/TypeError/RuntimeError/NameError) is NOT a
        # semantic result and must propagate, not be laundered into
        # UNSUPPORTED_SEMANTICS.
```


# `compiler` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/compiler/orchestration.py` :: `AdaptiveCompileResult`

```text

    The deterministic bundle + certificate are unchanged (byte-identical
    science); these artifacts are the MIN_ADAPT_MESH chain the request
    opted into via an explicit RoutingPolicyDefinition: relation,
    escape-partitioned VC resource, role binding, realization, escape
    qualification (QUALIFIED gate already passed), and the adaptive
    fabric + resolved fabric. No raw routing-function string can produce
    this: routing stays LOCKED, and only the exact min_adapt profile
    passes the relation gate (UGAL/Valiant/Chaos stay refused).
```

## `tracks/t3-topology/dse/veritx_dse/compiler/orchestration.py` :: `build_resolved_bundle_v3`

```text

    P1C phase-2 (Fix 2): makes CompileRequestV3 genuinely compilable
    WITHOUT converting it into a fake v2 request. The sequence is the
    same sealed derivation: every duck-typed stage (inventory, mapping,
    attachment, address decode, packet format, router behavior, fabric,
    resolved fabric/bundle) consumes the v3 request directly through the
    fields it shares with v2 (agents, address_map, workload geometry,
    design_hash, noc_config). The two v2-gated stages take the
    FabricIntentView (the one dispatch seam); VC structure comes from
    the v3 policy (derive_vc_assignment_artifact_v3 — declared classes,
    no concurrent-context floor). No v2 semantics are reinterpreted and
    the v2 path above is untouched.
```

## `tracks/t3-topology/dse/veritx_dse/compiler/orchestration.py` :: `derive_stages_v3`

```text

    Returns ``(bundle, staged, refusal)``:

      * full success      -> (bundle, None, None)
      * stage refusal     -> (None, StagedDerivation, the ControlPlaneError)

    A typed semantic refusal at stage N leaves every artifact from stages
    < N authoritative and produces none from stages >= N. Nothing is
    synthesized to fill a gap: an absent stage stays absent, so a staged
    result can never masquerade as a fabric.
```


# `compiler` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/compiler/candidate_policy.py` :: `CandidatePlan`

```text

    ``mapping_policy`` is proposal provenance (which mapping rule was
    chosen); it does NOT become Fabric or ResolvedFabric identity.
```

## `tracks/t3-topology/dse/veritx_dse/compiler/canonical.py` :: `compose_deterministic_candidate`

```text

    Given explicit candidate semantics — the route, resolved route and VC
    assignment (which V2 and V3 may obtain by different intent
    interpretation) — compose every downstream artifact and the terminal
    ``ResolvedFabric``. Both ``compile_deterministic_candidate`` and the v3
    orchestration entry call THIS function; no second sequencer exists.
```

## `tracks/t3-topology/dse/veritx_dse/compiler/orchestration.py` :: `build_resolved_bundle`

```text

    The reclaimed Wave-C entry point no longer performs a second v2
    derivation: it generates the declared BASELINE_DETERMINISTIC_V2
    candidate plan and compiles it with
    ``compiler.canonical.compile_deterministic_candidate`` — the same
    compiler the ``SrotaControlPlane`` service uses. Child identities are
    pinned equal by ``tests/test_compiler_path_parity.py``.
```

## `tracks/t3-topology/dse/veritx_dse/compiler/orchestration.py` :: `derive_adaptive_overlay`

```text

    Contract faults (non-policy input, including raw routing_function
    strings) raise TypeError and propagate — never mapped to a semantic
    outcome. Semantic refusals (wrong algorithm, wrong topology,
    vc_count < 2, proof failure) arrive as ControlPlaneError (typed
    outcomes) or VeritXError (mapped by the caller); programmer faults
    propagate untouched.
```
