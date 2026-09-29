# `application` — extracted module rationale

Extracted from the module docstrings of `veritx_dse/{name}` by the 2026-09-29 debloat. Code keeps a one-line pointer; this is the original long-form text.

## `tracks/t3-topology/dse/veritx_dse/application/authenticated_evaluation.py`

```text
veritx_dse.application.authenticated_evaluation — backend evidence proof.

`VerifiedPerformanceResult` (B's boundary) proves the persisted
PerformanceResult re-derives from a verified ``TemporalWorkload``: event
graph, deterministic schedule, every summary and the result identity.
It does NOT prove the network binding came from authenticated BookSim
execution — ``NetworkWindowBinding.from_dict`` validates digest *shape*
and ``reverify_result`` never reopens the evidence bytes. A synthetic
binding with invented digests can therefore satisfy B's boundary.

This module is the missing half: it dereferences the REAL persisted
evidence bytes and proves the whole chain end to end.

Creation (``authenticate_backend_evaluation``) binds a compilation +
workload + verified result to the evidence bytes at evaluation time and
returns an ``AuthenticatedBackendEvaluation`` proof object.

Consumption (``verify_authenticated_backend_evaluation``) re-checks the
ENTIRE chain from the proof's ``EvidenceRef`` at consumption time and
returns DERIVED ``VerifiedEvaluationClaims`` — never caller-supplied
claims. Worker A calls it directly (real import coupling, no duck
typing).

    exact evidence bytes -> sha256 == EvidenceRef.sha256
      -> read_verified_evidence (digest re-check + parse)
      -> validate_evidence_document (generation-aware closed schema)
      -> EvidenceArtifact (raw evidence digest, stats digest, backend
         input digest)
      -> NetworkWindowBinding: same evidence digest, same stats digest,
         same backend_input_hash, same physical_traffic_id
      -> VerifiedPerformanceResult (already verified by B's boundary)
      -> request/workload/design identity (re-derived lowering)
      -> RequirementEvaluator re-derivation -> canonical RequirementReport

Every mismatch or unreadable evidence refuses with ``EvidenceInvalid``
naming the mismatch; genuinely unexpected programming errors still
escape. ``evaluation_authority="certified-backend"`` is display metadata
only — the returned proof object IS the proof.
```

## `tracks/t3-topology/dse/veritx_dse/application/booksim_qualification_registry.py`

```text
booksim_qualification_registry — the ONE qualification authority.

WHY THIS EXISTS (PHASE B.1 §19, corrected in B.2 §2–§3)
=======================================================

`select_booksim_profile()` returning a profile is NOT a qualification result.
Before PHASE B.1 the capability-truth gate treated a successful selection as
PROJECTABLE = EXECUTABLE = QUALIFIED = YES, which is exactly the
false-positive shape the phase exists to remove: three DIFFERENT questions
answered by one observation.

  PROJECTABLE   can the canonical projector/preparer produce the backend
                input?  Authority: the REAL preparation path.
  EXECUTABLE    does a selected profile have an actual execution
                implementation registered AND resolvable?
  QUALIFIED     has the profile been SCIENTIFICALLY qualified?

WHAT QUALIFICATION IS BOUND TO — AND WHAT IT IS NOT
===================================================

PHASE B.1 invented `semantics_version = 1` and described it as "the compiler
semantics version under which the backend was qualified". Source inspection
shows that is the WRONG BOUNDARY:

  * the projection layer already owns the exact semantic identity of each
    profile (`BookSimProfile.semantics_version`, e.g.
    `booksim2-fork+P1B-meshdor-dump+prepared-v2`) plus its lowerer version
    (`DORXY/1`), and `PreparedBookSimInput.prepared_id()` BINDS those into the
    content identity of the prepared backend input;
  * the qualifier functions (`qualify_native_mesh_dor`,
    `qualify_anynet_min_hops`) operate over CANONICAL PARENT ARTIFACTS. They
    never inspect whether the root request began as v2, v3 or v4 — and they
    must not: the qualified interface is the canonical artifacts DOWNSTREAM of
    request generation.

Therefore qualification is bound to

    profile_id
    + projection semantics version   (EXACT match)
    + lowerer version                (EXACT match, where the profile binds one)
    + an executable qualifier over the canonical parents
    + resolvable durable evidence
    + record state

and NOT to CompileRequest schema generation. A v2 request, a v3 request and a
v4 request that lower to the SAME canonical parents produce the SAME prepared
bytes, so they are the same qualification question. Binding qualification to
`schema_version` would make the answer depend on how the design was typed
rather than on what it is.

Changing a profile's semantics string therefore INVALIDATES its qualification
automatically, because the exact-match check fails.
```

## `tracks/t3-topology/dse/veritx_dse/application/capabilities.py`

```text
veritx_dse.application.capabilities — authoritative capability registry.

Derived from ACTUAL registered backend support (Wave-B modules), never
from a parallel hand-written list. CLI/API/Studio surfaces read this
registry; no duplicate advertising lists.

Fidelity vocabulary is Wave-B's (RepresentationStatus /
CertificationEffect / ExecutionQualification), referenced by name.
```

## `tracks/t3-topology/dse/veritx_dse/application/capability_truth.py`

```text
capability_truth — live topology stage truth, derived from the compiler.

A descriptive registry may not claim a stage the implementation cannot
execute, so stages are derived by running the real compiler + profile
selector. See docs/decisions/capability-truth.md for why and for the
stage-source rules.
```

## `tracks/t3-topology/dse/veritx_dse/application/certificate_projection.py`

```text
veritx_dse.application.certificate_projection — CertificateProjectionV1.

The certificate has **two semantic layers** that must never be conflated
(the audit below is the authority; the code encodes it, it does not invent
it):

    certificate obligation status   PASS | FAIL
    CDG analysis verdict            PASS | FAIL | UNSUPPORTED | NOT_RUN

``VerificationCertificate.__post_init__`` enforces that an obligation
status is ``PASS`` or ``FAIL`` and that the certificate carries exactly the
ten canonical ``OBLIGATIONS``. The channel-VC CDG certifier underneath has
a richer vocabulary. ``_deadlock_free`` folds every non-PASS CDG verdict
into obligation ``FAIL`` — which is correct for the certificate, because
inability to *prove* deadlock freedom is not compile success — but the
underlying verdict survives in the obligation's evidence and MUST be
surfaced separately. Showing ``FAIL`` alone would tell a user a deadlock
was detected when the analysis in fact never produced a verdict.

The four product claims are derived here, deterministically, from the ten
obligations. The contribution table is the audit result:

    ATTACHMENT_COMPLETE <- ATTACHMENT_COMPLETE
    ROUTE_COMPLETE      <- ROUTE_COMPLETE
    ROUTE_LEGAL         <- ROUTE_LEGAL
    DEADLOCK_FREE       <- DEADLOCK_FREE

Each is 1:1 because the obligations validate different inputs:

    _attachment_complete  attachment.validate_against(design, inventory,
                                                      topology)
    _mapping_valid        the mapping<->attachment seam over
                          mapping.placements
    _route_complete       entry coverage over the router route table
    _route_legal          route.validate_against(topology)
    _deadlock_free        the (channel, VC) CDG over the realized route

``MAPPING_VALID`` is therefore NOT part of ``ATTACHMENT_COMPLETE`` despite
sharing an artifact-provenance parent in ``views.py``: it is the mapping
seam, a different artifact with a different failure mode, and it is
exposed as technical-only.

Fail-closed: every canonical obligation must be classified. A certificate
carrying an obligation this projection does not know is a projection
failure, never a silently dropped row.
```

## `tracks/t3-topology/dse/veritx_dse/application/comparison.py`

```text
veritx_dse.application.comparison — one comparison authority (Wave C).

No product path may compare naked result dictionaries. Comparison goes
through an explicit ``ComparisonContract`` (allowed variations +
metrics), a compatibility gate over typed ``EvaluationResult`` records,
and observed-language output (``lower observed latency`` — never
WINNER/BEST/OPTIMAL from single samples).

Conservative defaults for DESIGN_COMPARISON: the fabric may vary; the
experiment context (workload, mapping, backend profile/semantics,
execution mode, seed policy, metric schema) must match. Binary producer
identity must match unless the contract explicitly varies it. Semantic
loss digests must match unless the contract varies loss with an explicit
acknowledgement covering the differing dimensions.
```

## `tracks/t3-topology/dse/veritx_dse/application/compile_intent.py`

```text
veritx_dse.application.compile_intent — compile-only product boundary.

The smallest product-facing input boundary that can reach the canonical
architecture:

    CompileIntent
        ├── fabric_preset
        ├── strict overrides
        └── candidate_policy
                 |
                 v
           CompileRequest
                 |
                 v
       Slice-24 candidate policy
                 |
                 v
       Slice-23 canonical compiler
                 |
                 v
           ResolvedFabric

This module owns exactly:

1. named product ``CompileRequest`` presets (the authoritative canonical
   product preset registry: ``mesh4``, ``mesh4_hbm``, ``mesh4_wide128``);
2. strict, type-safe dotted-path preset overrides;
3. an immutable compile-only product intent with its own content id;
4. derivation of the exact canonical ``CompileRequest``;
5. explicit selection of the candidate-generation policy.

It does NOT own workload-trace transport, backend targets, seeds,
metrics, timeouts, execution, verification, persistence, or service
orchestration. ``CompileRequest.workload`` below is ordinary design
semantics, not a product trace-transport concern.

INTENT IDENTITY

    intent_id = content_id(
        "srota/CompileIntent/v2",
        {type, schema_version, compiler_semantics_version, fabric_preset,
         preset_design_hash, fabric_overrides, candidate_policy})

``name`` is presentation: it round-trips and never enters the id.
The id represents the DECLARED product request, not the resulting
hardware — a changed override changes intent identity even if a compiler
later produced equivalent hardware.

The intent is CLOSED over every semantics needed to reproduce its derived
design: it pins the compiler semantics version and the exact semantic
revision of the named preset (``preset_design_hash`` is the
``design_hash()`` of the un-overridden base preset under that compiler
semantics version — the existing canonical design hash, not an invented
preset fingerprint). A schema-v1 CompileIntent predates this pinning and
is refused explicitly; it is never silently reinterpreted.

OVERRIDE MODEL

``fabric_overrides`` is a canonical, sorted, duplicate-free tuple of
``(dotted_path, JSON scalar)`` pairs; transport form is a JSON object.
Paths address existing dictionary fields only (no array indices), may not
create fields, and may not touch the computed identity fields
(``design_hash``/``guardrail_hash``) or the envelope/version fields. When
the current leaf is non-null the override must preserve the exact JSON
semantic type — ``bool`` is not ``int`` — while a null leaf defers final
type authority to the canonical ``CompileRequest`` parser.

Nothing in the lower architecture imports this module.
```

## `tracks/t3-topology/dse/veritx_dse/application/compile_result_view.py`

```text
veritx_dse.application.compile_result_view — Compile Result inspectors.

One projection over a compiled revision, materialized **at certification
time** and frozen with the revision (Gate 5 §97, Gate 8 §50). The
inspectors are never re-derived from the request at view time: a drawn
graph that could drift from the proof it claims to show is worse than no
graph.

Seven groups under one Compile Result (Gate 8 §50) — not one page per
artifact:

    summary · mapping · fabric · routing · resources · address_decode ·
    provenance

Two rules shape what is projected:

* **Expected and observed are never merged** (Gate 8 §58/§59). The
  canonical route is a DERIVED EXPECTED state; runtime observation is a
  separate fact with its own scope. The observation is reported only when
  the certificate actually carries it, using the exact Gate-4 claim
  wording.
* **The certificate is four product claims over ten obligations** (Gate 7
  §9 PF-D9, Gate 8 §62). The verifier issues ten obligations; four of them
  are the named claims the product surfaces. Both are exposed — the four
  as the headline, all ten verbatim — so the projection cannot hide an
  obligation the proof relied on.

Everything here is read-only. No group carries an edit control.
```

## `tracks/t3-topology/dse/veritx_dse/application/design_view_v2.py`

```text
veritx_dse.application.design_view_v2 — DesignViewV2 (Gate 5 D1 / Gate 6 /
Gate 7 §51.1).

One projection serves authoring and Review. Review is
``presentation="review"`` on the same object — there is no
``DesignReviewView`` (Gate 7 §2).

The backend owns (Gate 7 §51):

    canonical field values · readiness · validation · capability
    consequences · scientific diff · snapshot identity · grouping semantics

The frontend owns rendering and interaction. It never reconstructs
canonical semantics, never infers blocking from message text, never
recomputes readiness, and never maintains its own field classification —
sections, exposure classes, labels and source-of-value all come from
``exposure-registry.yaml`` via :mod:`veritx_dse.application.product_registry`.

Two laws shape the output:

* **Completeness** (Gate 7 §5). Review must not hide active science:

      canonical active draft fields − metadata-only fields
        = scientific fields represented by Review

  Every registry field that is not metadata-only is either represented or
  proved non-active in this draft. ``completeness`` makes that mechanically
  checkable instead of a promise.

* **No later-stage claims** (Gate 7 §39/§40). Review describes the draft.
  It must never present DEADLOCK_FREE, ROUTE_LEGAL, QUALIFIED, SATISFIED,
  a measured latency or any backend evidence as a current fact — none of
  those exist before compile/evaluation.

Design readiness is its own result and is NOT evaluation preflight
(REV-D5): no backend, backend_profile, network_clock_hz or
expected_evidence_tier appears here.
```

## `tracks/t3-topology/dse/veritx_dse/application/errors.py`

```text
veritx_dse.application.errors — one control-plane error taxonomy.

Every product surface (CLI/API/T3/Python) reports failures as typed
``ControlPlaneError`` values, never as raw tracebacks and never as a
generic "evaluation failed". The critical invariant: a simulator crash,
a timeout, bad evidence and an unsupported semantic are NEVER reported
as NO_FEASIBLE_DESIGN — that code is reserved for a legitimate
design/search process that evaluated its space and found nothing
feasible (Wave C has no such search yet, so it is never emitted here).
```

## `tracks/t3-topology/dse/veritx_dse/application/evaluation_context.py`

```text
The canonical evaluation context — the fixed input boundary.

Every backend adapter receives ONE canonical context, never a raw
compilation: the request is lowered exactly once here, the workload
identity is bound back to the design by re-derivation, and the bundle
is the compilation's own. Adapters never call arbitrary lowerers
independently, so no backend can silently evaluate against a different
semantic graph than another.

    CompileRequest → FabricCompiler → Compilation
        → CanonicalEvaluationContext → planner / adapters
```

## `tracks/t3-topology/dse/veritx_dse/application/evaluation_plan.py`

```text
The evaluation plan — where backend choice belongs.

The planner asks every registered adapter one question per requested
analysis, applies a DETERMINISTIC selection law, and returns a plan.
It never executes anything and never silently downgrades semantics: an
analysis with no qualifying backend is a BLOCKED or UNSUPPORTED row
with a reason, not a substitution.
```

## `tracks/t3-topology/dse/veritx_dse/application/evaluation_plan_view.py`

```text
The evaluation-plan view — server truth for Studio, no derivation.

Projects an ``EvaluationPlan`` (plus its canonical identities) into the
language-neutral EvaluationPlanView
(contracts/srota/v1/evaluation-plan.view.schema.json). The frontend
renders support/readiness; it never derives them.
```

## `tracks/t3-topology/dse/veritx_dse/application/evaluation_question.py`

```text
The closed evaluation-question vocabulary.

A question enters this vocabulary only when a REGISTERED backend can
answer it with authentic evidence — the enum is capability truth, not
aspirational documentation. Extend with DRAM_TIMING, CXL_TRANSACTION_
TIMING, SERVING_TTFT/SERVING_TPOT, SCALE_OUT_CONGESTION, RTL_BEHAVIOR,
PPA_ESTIMATE only when the matching adapter exists.
```

## `tracks/t3-topology/dse/veritx_dse/application/fabric_compiler.py`

```text
veritx_dse.application.fabric_compiler — the product compiler (P1.4).

One entry point, three stages kept separate (later optimization
repeats compile → verify → evaluate per candidate without
duplicating logic):

    compile(request)  → Compilation (bundle + certificate + status)

A LOCKED obligation that is not PASS means no ResolvedFabric is
presented as success: the outcome is INVALID (failed proof) or
UNSUPPORTED (refused semantics) with the certificate or the error
as evidence. Compilation is a pure function of the request — no
hidden environment state, no spawn, no backend.
```

## `tracks/t3-topology/dse/veritx_dse/application/fabric_evaluator.py`

```text
veritx_dse.application.fabric_evaluator — P1B verified evaluation.

One entry point:

    FabricEvaluator.evaluate(compilation, workload, options)
        -> EvaluationOutcome (EVALUATED | BACKEND_UNAVAILABLE |
                              UNSUPPORTED | FAILED)

Preconditions are REFUSALS (typed ControlPlaneError, no backend work):
the input must be a COMPILED Compilation whose certificate is PASS, the
workload a canonical WorkloadGraph, the options an EvaluationOptions.
Anything downstream of satisfied preconditions is a TYPED OUTCOME —
never an exception, never fabricated performance.

Canonical chain (reuse, never reimplement):

    WorkloadGraph -> LogicalMessageArtifactV2 -> PhysicalTrafficArtifactV2
    -> traffic-class admission gate -> profile selection (derived from
    fabric semantics, never a user knob) -> pre-spawn gates
    (assert_projection_ready) -> certified BookSim projection
    (mesh-DOR native for MESH+DOR_XY fabrics, AnyNet for
    ANYNET_MIN_HOPS fabrics) -> producer availability (producer.py) ->
    qualified execution (quiescence inside) -> EvidenceArtifact
    (evidence.py only) -> NetworkWindowBinding v2 (ONE aggregate window)
    -> PerformanceModel + TemporalWorkload (window event only)
    -> schedule_workload -> build_performance_result -> reverify_result

Status law:
  * absent qualified BookSim producer -> BACKEND_UNAVAILABLE (the
    FileNotFoundError never escapes; no performance is fabricated);
  * execution failure (spawn, timeout, nonzero exit, quiescence,
    evidence authentication, timing bind) -> FAILED;
  * unprojectable semantics (unsupported workload semantics, unknown
    traffic class, BookSim lowering refusal, no valid network clock)
    -> UNSUPPORTED;
  * valid evidence + valid clock -> EVALUATED with a verified
    PerformanceResult.

Timing honesty: BookSim exposes one aggregate completion window, not
per-operation latency, so the temporal workload declares exactly ONE
NETWORK_TRAFFIC_WINDOW event. The network clock is an explicit caller
declaration (EvaluationOptions.network_clock_hz), recorded in the
PerformanceModel identity — never guessed. Without a valid clock the
evidence still authenticates but wall-time claims refuse: UNSUPPORTED
with a cycles-only window (window_cycles set, wall_time_ns None).
```

## `tracks/t3-topology/dse/veritx_dse/application/federated_evaluator.py`

```text
veritx_dse.application.federated_evaluator — the product-level resource.

Turns the sealed BookSim+ASTRA federation into one callable resource:

    evaluate_federated(compilation, questions, registry, ...)
        -> FederatedEvaluationOutcome

Laws (non-negotiable):
  * the canonical context is built ONCE; every analysis evaluates the
    same design/fabric/workload — no backend owns a private view;
  * the planner adjudicates every question; execution never second-
    guesses selection and never substitutes backends;
  * BOOKSIM_STANDALONE / NETWORK_COMPLETION executes through the
    existing certified FabricEvaluator — no second BookSim evidence or
    performance chain is ever constructed;
  * ASTRA analyses execute through their adapter seam
    (prepare -> execute -> normalize), staging their own workload;
  * ASTRA cycle counts never enter the network PerformanceResult: they
    answer different questions;
  * RequirementEvaluator stays bound to the verified PerformanceResult
    from NETWORK_COMPLETION until another requirement class explicitly
    names a different metric authority;
  * overall EVALUATED requires every requested question EVALUATED —
    never report EVALUATED when a requested question failed.
  * overall FAILED whenever a genuine execution FAILED — even beside
    successes (PARTIAL is incomplete coverage, never a crash mask).
    Successful analyses are preserved in the record, never discarded.
  * reproduction archival is explicit, never silent: every ASTRA /
    Ramulator analysis records an ArchivalResult (ARCHIVED or
    NOT_AVAILABLE naming the missing artifact). An EVALUATED analysis
    whose mandatory inputs never reached the layout keeps its
    EVALUATED status — the scripted-adapter product tests and the
    reproduce-time NOT_AVAILABLE verdict depend on it — but the run
    never claims reproducibility for it: the archival record rides in
    the analysis, and reproduction refuses without archived inputs.
    (Rationale: the strict variant — failing such analyses closed —
    would require redesigning the scripted-adapter test ecosystem,
    which stages no real inputs by construction; execute() already
    wrote evidence before persist runs, so a persist fault with
    successful execution is near-pathological and normalize-readback
    would usually fail it anyway.)
  * INCONCLUSIVE native verdicts are never FAILED and never PASS.
  * BOOKSIM_STANDALONE executes exactly once per NETWORK_COMPLETION
    question through the adapter seam (prepare -> execute); the
    certified FabricEvaluator is the single orchestration authority
    that drives that seam, and the federated path normalizes through
    exactly one normalization entry.
```

## `tracks/t3-topology/dse/veritx_dse/application/inventory.py`

```text
veritx_dse.application.inventory — Wave-C migration ledger (Phase 1/30).

One row per known execution surface: where it lives, what it does,
its classification, and its Wave-C replacement. AUTHORITATIVE rows are
the only product-certified paths. LEGACY_INTERNAL rows keep working
for historical research flows but are not reachable from certified
surfaces. TEST_ONLY rows never execute product intent.
```

## `tracks/t3-topology/dse/veritx_dse/application/preset_certification.py`

```text
veritx_dse.application.preset_certification — shipped-preset certification.

A preset may only advertise a capability envelope whose own conditions it
satisfies. Gate 6 asserted that for four presets; nothing verified it, and
one assertion was false: the ``mesh4`` family declared
``model_family=mixture_of_experts`` while advertising
``CAP-ENV-BOOKSIM-MESH-DOR-XY-V1``, whose ``COND-DENSE-STATIC-WORKLOAD``
requires ``dense_transformer``.

This module derives the certification state from **evidence** rather than
from the claim:

    registry claim  (exposure-registry.yaml: guided_eligible + envelope)
  + condition verdicts evaluated from the canonical compilation
  = certification state

States (Gate 6 already distinguishes the first two; the last two are the
fail-closed additions):

    GUIDED_SAFE    claimed Guided-eligible and every statically decidable
                   required condition of the advertised envelope holds
    EXPERT_ONLY    not claimed Guided-eligible
    INVALID        claimed Guided-eligible but a required condition FAILS —
                   the claim is false and must not ship
    UNCERTIFIED    no registry entry, or the claim rests on a condition
                   only an execution can decide

Fail-closed: an undecidable condition never yields GUIDED_SAFE, and an
unknown preset never yields any state but UNCERTIFIED.
```

## `tracks/t3-topology/dse/veritx_dse/application/presets.py`

```text
veritx_dse.application.presets — immutable named presets (Wave C).

Two registries, both immutable by construction:

* fabric presets: NAME -> CompileRequest builder. Builders construct
  FRESH sealed model objects on every call, so no caller can mutate a
  shared preset. ``derive_request(name, overrides)`` deep-copies through
  the canonical dict form and applies strict dotted-path overrides
  (unknown paths and type changes refuse).
* workload traces: NAME -> exact trace bytes.
* metric definitions: the smallest honest schema — only metrics the
  BookSim stdout parser genuinely produces, versioned with it.

Only presets reachable through the sealed CompileRequest derivation
live here. Artifact-level test variants that bypass CompileRequest
(single-class / escape VC overrides) are NOT presets; overriding them
would invent semantics Wave C does not own.
```

## `tracks/t3-topology/dse/veritx_dse/application/product_evaluator.py`

```text
veritx_dse.application.product_evaluator — ONE product evaluation.

Composes the canonical authorities without duplicating any science:

    FabricCompiler.compile            (application/fabric_compiler.py)
      -> Compilation (bundle + certificate)

    lower_compile_workload            (workload/intent_lowering.py)
      -> the request's exact WorkloadGraph

    FabricEvaluator.evaluate          (application/fabric_evaluator.py)
      -> EvaluationOutcome (authenticated, verified performance)

    RequirementEvaluator.evaluate     (application/requirements.py)
      -> RequirementReport (typed verdicts, no invented metrics)

This module owns *sequencing only*. It derives no route, counts no packet,
decides no verdict and invents no metric. It exists so the gateway, the
Studio fixture generator and any future product surface all call the same
four-step chain instead of re-implementing it.
```

## `tracks/t3-topology/dse/veritx_dse/application/product_registry.py`

```text
veritx_dse.application.product_registry — the backend owner of the
frozen product registries (Gate 4 / Gate 6).

Two planning authorities live as data, not as Python:

  * ``docs/product/capability-registry.yaml`` — what SROTA can represent,
    derive, verify, project, execute, qualify, evidence and wire, plus the
    certified envelopes and their conditions;
  * ``docs/product/exposure-registry.yaml`` — which Design intent fields
    the product may render, at which disclosure depth, with which
    source-of-value.

Nothing here re-states them. This module loads them, exposes the single
``capability_semantics_version`` every claim surface binds to, and
projects per-field and per-capability facts. The frontend may map exposure
classes to presentation; it never owns the classification (Gate 8 §12/§13).

Fail-closed (Gate 8 §137/§138): if the registries are absent, unreadable or
disagree about the semantics version, a typed error is raised and the
claim surface withholds claims rather than guessing.
```

## `tracks/t3-topology/dse/veritx_dse/application/requests.py`

```text
veritx_dse.application.requests — typed product intent (Wave C).

``Intent`` is the single typed boundary every surface (Python, CLI, API,
T3) constructs. Strict parsing (unknown fields refuse, no coercion),
explicit schema version, and canonical identity over SEMANTIC fields
only: display labels (``name``) and transport metadata (external trace
paths, output locations) never enter the identity.
```

## `tracks/t3-topology/dse/veritx_dse/application/requirements.py`

```text
veritx_dse.application.requirements — RequirementEvaluator (P1C).

Evaluates v3 requirements over an ALREADY-VERIFIED PerformanceResult
(performance/result.py authority — this module never builds, schedules,
or re-verifies results; it reads the verified document). No backend, no
spawn, no optimization: one pure function of (request, workload,
performance).

Measurement honesty (binding — every rule enforced below):

* **Aggregate evidence, attributed honestly.** BookSim yields ONE global
  traffic window, never per-operation or per-class completion. A global
  completion time is a SOUND UPPER BOUND on any class's completion
  (class traffic completes no later than window drain), so:
    - aggregate latency <= ceiling -> class SATISFIED (proven);
    - aggregate latency > ceiling with several classes in play ->
      UNMEASURABLE (the excess cannot be attributed — a class VIOLATED
      from aggregate data would be fabricated);
    - fabric-wide (or single-class, where aggregate == class evidence)
      requirements evaluate directly to SATISFIED / VIOLATED.
* **Bandwidth needs bytes.** A bandwidth floor measures iff attributable
  byte movement exists (BANDWIDTH utilization entries) over a known
  window: fabric-wide or single-class aggregates evaluate; class-scoped
  requirements over multi-class workloads are UNMEASURABLE (per-class
  bytes are not evidenced). Absent bytes are absent, never zero-filled.
* **Cycles are compared to cycles.** A latency ceiling is declared in
  fabric cycles, so it is compared against the fabric cycles the bound
  network window AUTHENTICATED: the binding records the exact pair
  (duration seconds, network_clock_hz) produced by
  completion_time / network_clock_hz, so multiplying them recovers the
  backend's completion_time exactly and the CALLER's clock cancels. A
  caller clock can rescale the wall duration but never the authenticated
  cycles. When no network window is bound, the makespan (compute+network
  wall-time superset) is converted with the DESIGN's own clock and the
  authority string says so — a documented conservative fallback, never a
  caller-clock rescale.
* **Wall-time stays wall-time.** Cycles-only evidence (no valid network
  clock) still refuses wall-time claims upstream (FabricEvaluator
  UNSUPPORTED, cycles-only window); requirement evaluation never
  invents the missing frequency.
* **Binding + UNMEASURABLE never passes.** report_passes() is False
  unless every BINDING entry is SATISFIED. Non-binding entries are
  advisory. A requirement with no thresholds at all is NOT_APPLICABLE,
  not satisfied.
* **Wrong workload refuses.** The workload geometry must equal the
  request geometry (same TP/PP/EP/DP law as the traffic seam: equal
  world size is not equivalence); a class-scoped requirement naming a
  class outside the request's intent registry refuses fail-closed.
* **The triple must belong to one design.** Geometry equality alone
  admits a same-shape transplant: two v3 requests with identical
  TP/PP/EP/DP but different payloads/semantics lower to same-geometry
  graphs. The workload must be EXACTLY this request's re-derived
  lowering (provenance is metadata, not authority — it is excluded from
  workload_id()), and the performance result must have passed the
  verified boundary (``verify_performance_result`` -> a
  ``VerifiedPerformanceResult``); its Wave-D chain must bind BOTH this
  workload's workload_id() AND this request's design_hash (traffic-class
  semantics live in the lowering sidecar, not in the canonical graph
  identity, so two designs differing only in traffic class share a
  workload_id). A naked result dict, a missing chain binding or a
  foreign graph refuses — an absent binding is not a pass.

Report shape follows contracts/srota/v1/requirement.report.schema.json
(contract_version 1): per-requirement {requirement_index,
traffic_class, qos_class, verdict, binding, required, measured,
metric_authority, performance_result_id, reason}.
```

## `tracks/t3-topology/dse/veritx_dse/application/resources.py`

```text
veritx_dse.application.resources — durable application resource envelopes.

The first durable persistence boundary for canonical compilation defines
exactly four resource kinds:

    CompileIntentRecord    key = intent_id              (this module)
    CompileRequest         key = design_hash            (model, verbatim)
    ResolvedFabric         key = resolved_fabric_hash   (model, verbatim)
    CompileResolution      key = intent_id              (this module)

Relationship:

    CompileIntent declaration
            |
            v
    CompileIntentRecord
     key = intent_id
            |
            v
    CompileResolution
     key = intent_id
     |-- design_hash ----------> CompileRequest
     `-- resolved_fabric_hash -> ResolvedFabric

There is NO CompiledDesign hash, NO resolution hash, NO store-generated
UUID, NO timestamp identity, and NO duplicate hash over
``{design_hash,mapping_hash,fabric_hash}``. ``ResolvedFabric`` already owns
precisely that semantic identity.

WHY CompileIntent IS NOT STORED VERBATIM

``intent_id`` deliberately excludes ``CompileIntent.name`` (presentation
metadata). Two intents named ``"alpha"`` and ``"beta"`` can therefore share
one ``intent_id`` while having different ``to_dict()`` bytes. An
identity-addressed store keyed by ``intent_id`` must not persist
``CompileIntent.to_dict()``; it persists :class:`CompileIntentRecord`, the
exact *semantic* declaration. Human labels belong to a future
project/UI metadata layer. ``CompileIntent`` identity is not redefined to
solve a storage problem.

These envelopes are persistence projections, NOT new semantic identities:
neither type has a hash method. ``CompileIntentRecord`` validation
recomputes the EXISTING CompileIntent identity equation and requires it to
equal the stored ``intent_id``; the projection is pinned structurally
against ``CompileIntent.identity_dict()`` so it cannot drift.

CURRENT-ONLY WRITE POLICY

The first persistent store begins after the v2 semantics migration, so
both parsers accept only current CompileIntent schema v2, current compiler
semantics v2, and a currently recognized candidate policy. Pre-25B v1
application intents are refused explicitly; no silent reinterpretation and
no migration is performed here.

This module imports neither candidate generation nor the canonical
compiler: it only validates and links already-produced resources.
```

## `tracks/t3-topology/dse/veritx_dse/application/results.py`

```text
veritx_dse.application.results — verified resource loading (Wave C.2).

Scientific consumers must NEVER use ``store.get()`` directly: every
content-identified resource proves, on load, that its current canonical
contents still produce its claimed ID:

    requested filename ID == embedded resource_id == recomputed ID

plus linkage and Wave-B evidence derivations. Anything else refuses
with EVIDENCE_INVALID (corrupt store links) or NOT_FOUND. Raw
``store.get()`` is inspection/internal storage access only.

LEGACY BOUNDARY (P0.11)
-----------------------
The result/attempt/comparison/study readers below
(``load_verified_result``, ``load_verified_attempt``,
``load_verified_experiment``, ``load_verified_comparison``,
``load_verified_study``, ``load_verified_studyrun`` and their helpers
``_read_attempt_record`` / ``_verify_waved_result`` / ``_verify_metrics``)
speak the HISTORICAL RT result-resource vocabulary
(``backend_config_hash``, ``qualification``, ``execution_transport``,
``booksim_binary_sha256``). They are **not production-reachable**: no CLI
or application service imports them, and the canonical production path
persists and verifies ``ScientificBackendEvidence`` / performance results
instead. They exist only for the legacy Wave-D/E seal tests and are
retained until those tests migrate to the canonical evidence schema.

Canonical usage is ``load_verified_design`` (used by
``waved_resources.rebuild_verified_bundle``). Do not add a new caller of
the legacy result readers; migrate the caller to canonical evidence.
```

## `tracks/t3-topology/dse/veritx_dse/application/revision_diff.py`

```text
veritx_dse.application.revision_diff — stable revision-diff projection.

Compares two FROZEN CompileResultView payloads field-by-field and reports
what changed between them. This is a presentation projection, not science:
it never recompiles, never re-derives a route, never re-runs the CDG
analysis. Every row names frozen values from payloads materialized at
certification time, so the diff cannot drift from the proofs it describes.

Three sections, in product order:

    DESIGN CHANGES      declared intent (what the user asked for)
    DERIVED CHANGES     compiler-derived structure (what was built)
    CAPABILITY CHANGES  executability / qualification (what it can do)

A missing predecessor is not an error: the first revision of a project has
nothing to diff against, and the view says so explicitly.
```

## `tracks/t3-topology/dse/veritx_dse/application/service.py`

```text
veritx_dse.application.service — canonical application compile orchestration.

The ONE product compile path:

    CompileIntent
          |
          v
    derive_compile_request
          |
          v
    generate candidate          (explicit candidate-policy dispatch)
          |
          v
    canonical candidate compiler
          |
          v
    ResolvedFabric
          |
          v
    ResourceStore.commit_resolution
          |
          v
    validated committed result

The service owns SEQUENCING ONLY. It owns no topology derivation, routing
semantics, VC semantics, packet format, router behavior, address decoding,
verification, backend lowering, requirements evaluation, or persistence
format — those authorities already exist below it.

SCOPE

``SrotaControlPlane`` receives an explicit :class:`ResourceStore` (no
implicit path, no environment variable, no repository-relative store, no
global singleton) and exposes exactly one public operation, ``compile``.
Backend lowering is a later slice; compilation here is structural.

RECOMPILATION

``compile()`` always runs candidate generation and canonical compilation;
it never short-circuits on an existing resolution. That keeps one compile
path, detects accidental policy/compiler drift, and lets the idempotent
``commit_resolution`` surface a genuine conflict instead of hiding it
behind a cache lookup. Caching is a later, explicit product policy.

PERSISTENCE

Only the resolution root is durable (see :mod:`veritx_dse.application.store`).
The live ``CompiledFabric`` is returned in :class:`CompileOutcome` for the
future backend-lowering path but is never persisted and never pickled.
```

## `tracks/t3-topology/dse/veritx_dse/application/store.py`

```text
veritx_dse.application.store — typed durable resource store.

The first durable application persistence boundary: four resource kinds,
content- or identity-addressed, written once, never overwritten with
conflicting content.

    <root>/
        intents/<intent_id>.json            CompileIntentRecord
        designs/<design_hash>.json          CompileRequest (canonical)
        resolved/<resolved_fabric_hash>.json  ResolvedFabric (canonical)
        resolutions/<intent_id>.json        CompileResolution
        .store.lock                         POSIX advisory write lock

A hidden lock file is the only extra artifact. No SQLite, no manifest
index, no aliases, no "latest".

WHAT THIS STORE IS NOT (YET)

It persists the durable COMPILE RESOLUTION ROOT only: the semantic intent
declaration, the exact canonical design, the exact ResolvedFabric, and the
resolution link between them. It deliberately does NOT persist the full
compiled DAG (topology, attachment, route, VC assignment/resource, packet
format, router behavior, address decode, FabricArtifact) and does NOT
persist a ``CompiledFabric`` object (no pickle, JSON only).

Those artifacts remain available from a live Slice-23 compile. A restart
recovers the resolution root, not a directly lowerable backend artifact
set; backend lowering is a later concern and may motivate typed
child-artifact persistence or deterministic reconstruction.

WRITE-ONCE SEMANTICS

Identities are immutable. A missing resource is written atomically; an
existing resource holding the SAME canonical content is an idempotent
success; an existing resource holding DIFFERENT content under the same key
fails closed (never "repaired"). Existing bytes are never overwritten with
conflicting content.

DURABILITY

Writes publish a unique same-directory temporary file with flush + fsync,
``os.replace``, then an fsync of the destination directory. The
check-existing -> publish sequence is serialized across processes by an
``fcntl.flock`` on ``<root>/.store.lock``. Readers are lock-free because
final-file publication is atomic.
```

## `tracks/t3-topology/dse/veritx_dse/application/studies.py`

```text
veritx_dse.application.studies — typed study/batch resources (Wave C).

A study is a typed GROUPING of related experiments, not a scheduler:
sequential evaluation, no dependency graph, no workers. Multi-seed
evaluation = multiple candidate intents (seed is result-affecting, so
each seed is a distinct experiment). Replicates stay visible as
observation sets — Wave C computes no means and names no winners.

Compiler-verdict vocabulary (FEASIBLE / NO_FEASIBLE_DESIGN /
CONSTRAINT_UNMEASURABLE / INCONCLUSIVE) is encoded here with strict
rules for future search orchestration; Wave C emits verdicts only by
summarizing completed study records, never by searching.
```

## `tracks/t3-topology/dse/veritx_dse/application/surfaces.py`

```text
veritx_dse.application.surfaces — one intent from every surface.

Python, CLI, API and T3 construct the SAME canonical intent document and
parse it through the SAME ``parse_intent``. Transport metadata (flag
order, JSON key order, routes, directories, labels) never enters
semantic identity — proven by cross-surface equivalence tests.
```

## `tracks/t3-topology/dse/veritx_dse/application/views.py`

```text
veritx_dse.application.views — product-view gateway (P1 integration).

The single Studio-facing boundary:

    engine artifacts
      -> this projector
      -> contracts/srota/v1 (JSON Schemas)
      -> Studio (never engine internals)

Rules, shared with every other view projector:
- Engine values are bare digests; this module adds exactly one
  ``sha256:`` prefix per hash at the view boundary.
- Absent engine facts stay absent (keys omitted), never zero-filled or
  guessed. In particular the resolved VC artifact carries no turn
  restriction list, so ``turn_restrictions`` is omitted rather than
  rendered as "none".
- No semantics here: pure projection of already-certified objects.
  Invalid inputs raise TypeError; never a view with half-truths.

Already covered elsewhere and NOT duplicated here: EvaluationView
(``EvaluationOutcome.to_view_dict``), RequirementReport (the evaluator's
report dict), OptimizationStudyView (``OptimizationResult.to_study_view``).
```

## `tracks/t3-topology/dse/veritx_dse/application/wave_e_resources.py`

```text
veritx_dse.application.wave_e_resources — persisted performance resources.

Temporal workloads are scientific resources under the SAME contract as
the workload ones (§56/§149):

    requested filename ID == embedded resource_id == recomputed ID

plus verified workload parents where cited, closed field sets, and
semantic revalidation. Raw ``store.get()`` is inspection-only.

M6 vocabulary: new temporal workloads persist under the ``performance``
kind; ``waveeworkload`` documents remain readable (historical). A
performance result is NOT a separate loose resource: it rides inside
the EvaluationResult ``wave_e`` block, verified against the plan
binding and the authenticated BookSim evidence (§71).
```

## `tracks/t3-topology/dse/veritx_dse/application/waved_resources.py`

```text
veritx_dse.application.waved_resources — persisted Wave-D resources.

Wave-D semantic artifacts are scientific resources: they must survive
persistence and be loadable under the SAME contract Wave C uses for
intents/designs/results:

    requested filename ID == embedded resource_id == recomputed ID

plus verified parents, closed field sets and semantic revalidation.
Raw ``store.get()`` is inspection-only and never scientific trust.

The chain is stored as five content-addressed resources:

    wavedworkload   WaveDWorkload            (declared semantics)
    parallelism     ParallelismArtifact      (rank geometry)
    wavedsemantics  WaveDWorkloadSemantics   (versioned envelope)
    opgraph         OperationGraph           (causal DAG)
    messages        LogicalMessageArtifact   (scheduled messages)
    traffic         PhysicalTrafficArtifact  (packets + flits)

A ``traffic`` record also carries its ``design_id`` so the physical
bundle can be recompiled and re-verified on load; the bundle itself is
never persisted (it is an in-memory proof carrier — same rule as Wave B).
The ConservationLedger is NOT persisted: it is derived from a verified
``PhysicalTrafficArtifact`` and recomputed on demand.
```


# `application` — extracted inline comments

## `tracks/t3-topology/dse/veritx_dse/application/authenticated_evaluation.py`

line 150:

```text
    # Canonical evidence seam (§26 Option 2): the evidence chain file
    # holds the bare scientific document (the evaluator persists the
    # validated scientific bytes deterministically; run-varying attempt
    # metadata lives only in the execution run directory, never in the
    # chain). Every digest below is read under its CANONICAL key, each
    # naming the same executed fact the canonical execution path proved:
    # - profile_id: which backend profile executed (its identity);
    # - trace_sha256: digest of the exact executed trace bytes
    #   (materialized and re-hashed before spawn by
    #   execute_prepared_booksim); the evaluator binds this same
    #   digest as backend_input_hash in binding and chain, so
    #   artifact↔binding agreement is by construction, not by
    #   cross-schema guessing;
    # - parser_version / stats / binary_sha256: pinned by the
    #   canonical document itself. No RT field is read here.
```

line 171:

```text
        # Certification admission: content authenticity is not
        # qualification. Every authenticated-evaluation open runs the one
        # admission rule, so an unpinned/diagnostic/dirty/legacy run can
        # never reach a certified claim.
```

line 218:

```text
    # Executed-config digest under its canonical key: config_sha256
    # is the digest of the exact executed config bytes (re-hashed
    # before spawn); the binding names the same executed bytes'
    # digest as backend_config_hash. Same bytes, each side's own key.
```

line 295:

```text
    # Canonical producer key: binary_sha256 is the digest of the exact
    # executed binary (resolved and re-checked before spawn by
    # execute_prepared_booksim).
```

line 552:

```text
    # Canonical evidence fields only. ``profile_id`` is the executed
    # backend profile, ``execution_fidelity`` the executed qualification
    # label. No RT vocabulary (execution_transport / qualification) is
    # read; those keys do not exist in the canonical document.
```

## `tracks/t3-topology/dse/veritx_dse/application/booksim_qualification_registry.py`

line 89:

```text
#: profile id -> qualification record. THE qualification authority.
#:
#: The exact semantics strings are read from the projection layer itself
#: (see `_profile_semantics()`), so a profile whose semantics string changes
#: cannot keep a stale qualification: the registry VALIDATES the binding at
#: import time and raises.
```

line 138:

```text
    # Multi-class mesh-DOR: the qualifier runs over the REAL canonical
    # parents on every evaluate_qualification call — registration grants
    # no bypass. The MC delta over single-class mesh (workload-derived
    # class count, fork-v2 per-class replay, per-class conservation) is
    # covered by durable tests: the multi-class hard gate (render, bind,
    # determinism, conservation-or-refuse, optimizer end-to-end), the
    # conservation fault matrix, and route equivalence (routing is shared
    # with the single-class mesh envelope). Scope states the envelope
    # exactly; a live MC bake-off remains ledger debt, not a silent gap.
```

line 165:

```text
    # Torus wraparound-DOR: the qualifier runs over the REAL canonical
    # parents on every evaluate_qualification call. Registration grants
    # no bypass: exact-2-VC dateline halves, tie carve-out, identity
    # transitions. End-to-end qualification is reachable only with a
    # COMPILED bundle, which requires the dateline-proof bridge (the
    # certificate currently fails DEADLOCK_FREE with a named X-ring
    # cycle) — unit-level qualification is proven by the profile tests.
```

line 191:

```text
    # FlatFly minimal: qualifier runs over the REAL canonical parents.
    # v1 domain (k-ary 2-fly, concentration 1, identity node->router)
    # is proven end to end by the capability-truth probe: 256/256
    # byte-identical dump equivalence on k=4/n=2.
```

line 217:

```text
#: profile id -> the execution implementation that runs a prepared input.
#: THE execution authority. An entry here means a real code path exists; it
#: does NOT mean a probe was executed during the capability gate.
```

line 310:

```text
    # The lowerer version is bound into PreparedBookSimInput rather than onto
    # the profile, so it is read from the module constant that prepares it —
    # the same value the prepared identity carries.
```

line 411:

```text
    # The lowerer version is not an attribute of BookSimProfile; it is the
    # projection module's constant for the profile, read through the same
    # table _profile_semantics uses so the two can never disagree.
```

line 432:

```text
        # Qualifier refusal vocabulary only: qualifier functions refuse
        # with SemanticLoss/BookSimProjectionError (or Refusal). A
        # programming error (AttributeError/TypeError/...) propagates as
        # an internal failure, never as a "not qualified" verdict.
```

## `tracks/t3-topology/dse/veritx_dse/application/capability_truth.py`

line 26:

```text
#: Capability-truth key -> the intent the probe declares. The probe SHAPE
#: lives with the probe (no second shape table); each is the smallest design
#: that exercises the family's real path.
```

line 89:

```text
    # A registered kind is satisfied when EVERY subfamily label it expands to
    # is probed: GEC is one registered kind but four physical modes, and all
    # four must be gated.
```

line 206:

```text
        # Probe refusal vocabulary only: schema/intent construction
        # refuses with ValueError-family schema errors (or Refusal). A
        # programming error propagates, never reading as "schema refused".
```

line 216:

```text
    # No family-name shortcut: `.kind == "gec"` for every GEC mode, so the
    # preset request is normalized through the real generation seam and its
    # capability label compared with the probed label.
```

line 283:

```text
    # Direct probes: a verification failure (e.g. torus DEADLOCK_FREE) drops
    # the staged record, which would mis-report these stages as NO even
    # though the canonical seams demonstrably produce them.
```

line 325:

```text
        # Distinct stage authorities even with no bundle: PROJECTABLE
        # asks the preparation path (unreached without a bundle),
        # EXECUTABLE asks handler availability (likewise unreached).
```

line 356:

```text
            # PROJECTABLE is separate from selection: it is answered by the
            # real preparation path, which is what produces backend input.
            # Selecting a profile is necessary but not sufficient.
```

line 372:

```text
                # Real preparation-path refusal only: prepare raises
                # BookSimProjectionError (or Refusal). A programming error
                # propagates, never reading as PROJECTABLE=NO.
```

line 392:

```text
            # QUALIFIED is scientific qualification from one registry, decided
            # by the real qualifier over the real canonical parents under an
            # exact projection-semantics match. Selection or preparation never
            # implies it.
```

## `tracks/t3-topology/dse/veritx_dse/application/certificate_projection.py`

line 14:

```text
#: The CDG certifier's analysis vocabulary. `NOT_RUN` is declared by the
#: certifier but never produced by `certify_channel_vc_deadlock`; it is
#: retained because a reserved slot is not the same as an impossible one.
```

## `tracks/t3-topology/dse/veritx_dse/application/comparison.py`

line 28:

```text
    # Wave E: two latency numbers are not automatically comparable. A
    # result produced under a different performance model (different
    # clocks, resources, compute source, arbitration or calibration
    # context) measures something else, so the model is a required
    # compatibility dimension. A contract may explicitly allow it, but
    # silence never may.
```

line 142:

```text
        # The performance model IS the timing semantics (clocks,
        # resources, compute source, arbitration); the fidelity warning
        # is a function of it. Wave-D-only results have no timing model.
```

## `tracks/t3-topology/dse/veritx_dse/application/compile_intent.py`

line 24:

```text
# Exactly the computed identity fields CompileRequest.to_dict() serializes.
# These are stripped before reparse so from_dict() recomputes them under the
# overridden semantics. Explicit set only — no "endswith _hash" catch-all.
```

line 117:

```text
# Structurally immutable module-level registries: no runtime caller can
# mutate preset descriptors or the preset->builder association. Builders
# always construct fresh CompileRequest objects (see test_preset_requests_are_fresh_and_frozen).
```

line 389:

```text
        # A schema-v1 document predates the compiler-semantics and
        # preset-revision pins; it is refused explicitly and never
        # silently reinterpreted or auto-migrated here.
```

## `tracks/t3-topology/dse/veritx_dse/application/compile_result_view.py`

line 13:

```text
#: Shape version of the CERTIFICATE CLAIM rows inside a CompileResultView.
#:
#: WHY THIS EXISTS. The claim row shape changed while CONTRACT_VERSION stayed
#: 1: legacy rows are ``{claim, scope, status, method}`` and current rows add
#: ``certificate_status``, ``established``, ``contributing_obligations``,
#: ``contributing_statuses`` and ``aggregation``. A CompileResultView is
#: FROZEN at certification time and served back verbatim, so a revision
#: persisted before the change hands the frontend a payload its own type
#: says is impossible — ``claim.contributing_obligations.map`` throws and the
#: Compile Result white-screens.
#:
#: The version marker alone is not enough (nothing reads it on a legacy
#: payload), so ``claims_are_current()`` is the enforcement: a frozen payload
#: whose claims are not current is treated as ABSENT and re-derived through
#: the existing hash-checked path, never served stale and never silently
#: redrawn.
```

line 79:

```text
    # Legacy payloads carry no marker; fall back to a structural check so a
    # pre-marker revision is still classified correctly rather than
    # re-derived on every read.
```

line 119:

```text
#: The DEADLOCK_FREE obligation records the route-realization *scheme*
#: (`v2_channel_id`), which is a property of the artifact encoding, not a
#: runtime observation. It must never be presented as one.
```

line 366:

```text
    # OCCUPANCY IS ENDPOINT COUNT, NOT DISTINCT-ROUTER COUNT. A router with
    # four seats hosting four agents occupies four seats; counting the
    # router once would under-report occupancy by a factor of the
    # concentration (dense-4b-32tiles-conc4 has 36 seats and 36 agents, so
    # zero unused — not 27).
```

line 413:

```text
    # The route table and the channel table are stored as pure data: the
    # revision is persisted as JSON, so the payload can hold no callable.
    # `canonical_route(payload, ...)` walks them on request.
```

line 430:

```text
    # Gate 8 §59: the observation is a separate fact with its own scope.
    #
    # A compiled revision has NO runtime execution, so there is no
    # observation to report. The DEADLOCK_FREE evidence carries
    # `route_realization: "v2_channel_id"`, which is the artifact's encoding
    # scheme — presenting it as an observation would claim a runtime fact
    # that does not exist. The observation belongs to an evaluation run,
    # where RunIntegrityView.route_realization reports
    # OBSERVED | NOT_OBSERVED with its own scope.
```

line 484:

```text
            # Gate 8 §61: the channel dependency graph is the witness. When
            # the verdict is FAIL the cycle is named; when PASS the graph
            # properties are the proof. Both are the same fields.
```

line 585:

```text
            # Documented domain faults (artifact errors) yield absent
            # provenance hashes; a programming error propagates instead of
            # hiding as empty hashes.
```

line 672:

```text
        # design_view's documented refusal (e.g. cross-design projection)
        # falls back to the rebuilt document below; a programming error
        # propagates instead of diverging from authority silently.
```

line 707:

```text
    # The compilation is required to see the LOWERED traffic classes: a
    # fabric can be multi-class through its dependency graph without
    # declaring a single collective (the mesh4 family is exactly that).
```

## `tracks/t3-topology/dse/veritx_dse/application/design_view_v2.py`

line 46:

```text
#: Gate 7 §9 — nine sections, in order. Router Behavior is split out of
#: Fabric and Memory Addressing out of System for comprehension; Physical
#: Context is its own small section. These are the only documented
#: deviations from ontology ownership.
```

line 107:

```text
#: Repeated groups: registry class -> (container path, candidate row-list
#: paths). A candidate list is tried in order because v2 nests dependencies
#: under ``dependencies.dependencies`` while v3 declares them directly.
```

line 121:

```text
#: Which capability a draft choice makes material (Gate 7 §30). These come
#: from the registry; the mapping from a *choice* to the capability it
#: exercises is product grouping, and it is deliberately explicit rather
#: than inferred.
```

line 251:

```text
    # Explicit absence checks instead of a broad catch: a missing bundle,
    # VC assignment or class map is absence (empty set); a programming
    # error inside a property propagates instead of under-reporting
    # multi-class traffic.
```

line 706:

```text
#: Field-level normalizers applied before a scientific comparison. A diff
#: is over *normalized* science (Gate 8 §24): field order, formatting and
#: aliases are not differences. Arbitration is the one field whose raw
#: spelling is not semantic identity, so it is normalized through the
#: domain owner before comparison.
```

line 791:

```text
    # Compile once. Every consumer below reads the same canonical
    # compilation, so the projection can never disagree with itself about
    # what the design derives.
```

## `tracks/t3-topology/dse/veritx_dse/application/evaluation_context.py`

line 74:

```text
    # Lower EXACTLY once, here. Binding back to the design: the lowering
    # carries the design_hash it was derived from, and it must be THIS
    # compilation's request identity — a transplanted lowering is refused.
```

## `tracks/t3-topology/dse/veritx_dse/application/evaluation_plan.py`

line 56:

```text
#: deterministic preference when several backends qualify for one
#: question. Order is the LAW, stated here once: earlier beats later.
#: Installation order in the registry can never alter selection.
```

line 113:

```text
        # the bundle's fabric identity is its resolved_fabric child's
        # hash (RT v1 accessor or canonical attribute — same shim the
        # bundle itself uses)
```

line 150:

```text
            # deterministic: report the PREFERRED backend's refusal for
            # this question (never registry-order-first, which blames an
            # unrelated backend — e.g. BookSim for a DRAM question). An
            # UNSUPPORTED row is unbound (no backend could represent), so
            # backend_id stays None while the refusal reason is named.
```

## `tracks/t3-topology/dse/veritx_dse/application/fabric_compiler.py`

line 15:

```text
#: The canonical derivation stages, in order. A refusal at stage N leaves
#: every artifact from stages < N authoritative and produces none from
#: stages >= N (the staged-compilation law).
```

line 72:

```text
    #: Adaptive overlay derived alongside the deterministic bundle when
    #: compile() was given an explicit RoutingPolicyDefinition (an
    #: AdaptiveCompileResult; None on the pure deterministic path). The
    #: deterministic bundle + certificate are unchanged either way.
```

line 152:

```text
            # The legacy v2 path is not decomposed into preserved stages,
            # but the canonical compiler still attributes its refusal to a
            # `CompileStage`. Report that stage rather than losing it: a
            # user must be able to see WHERE a derivation stopped even when
            # upstream artifacts are not recoverable on this path.
```

line 177:

```text
            # A typed stage refusal. The status vocabulary is unchanged:
            # UNSUPPORTED means a downstream contract is unavailable, and
            # that is a capability fact, not an invalid design. The staged
            # artifacts ride along so upstream science stays inspectable.
```

line 200:

```text
            # The T-series law extends past derivation: a verification
            # failure must not discard the derived artifacts (torus
            # topology + DOR_TORUS_XY route stay inspectable with a named
            # DEADLOCK_FREE failure). Preserve the full derivation record
            # with stopped_at_stage VERIFICATION; bundle stays None (no
            # fabric is certified) and nothing downstream is synthesized.
```

## `tracks/t3-topology/dse/veritx_dse/application/fabric_evaluator.py`

line 352:

```text
        # The canonical context lowers the request EXACTLY once; the
        # workload is validated against it by identity (provenance is
        # forgeable metadata). No second lowering anywhere downstream.
```

line 368:

```text
        # ── canonical projection via the BookSim adapter ───────────
        # Federated: the evaluator consumes the certified BookSim stack
        # through the BackendAdapter seam. The ADAPTER owns the canonical
        # traffic construction (V3/V2 by unified class), the VC admission
        # gate, the intent-class assertion, and the projection — exactly
        # once, no duplicate artifact construction here. The prepared
        # execution flows straight from prepare() to execute(); the
        # evaluator binds the native identities and keeps the
        # evidence/window/performance assembly.
```

line 392:

```text
            # Preserve the pre-adapter refusal taxonomy: lowering/traffic
            # construction failures are FAILED; admission and projection
            # refusals are UNSUPPORTED. When the canonical artifacts were
            # constructed before the gate refused, bind their identities.
```

line 470:

```text
        # execute_prepared_booksim fails closed on nonzero exit, so a
        # completed record always carries exit_status 0 and parsed stats.
        # Stats flow unmodified from here on: the proof re-derives the
        # stats digest from the persisted bytes, so any local key alias
        # would break artifact↔binding agreement. The canonical
        # ``completion_cycles`` key is consumed as-is downstream.
```

line 478:

```text
        # ── evidence authentication (evidence.py only) ─────────────
        # §26 reload gate: the persisted bytes must read back through
        # the canonical reader and validate — proving the write/read
        # contract, not just in-memory construction. execute wrote the
        # canonical {"evidence","attempt"} wrapper to the run
        # directory; the SCIENTIFIC document inside it is what validates
        # as evidence.
        #
        # The evidence CHAIN (binding, artifact, outcome, proof) then
        # names the pure scientific document only: the wrapper mixes
        # run-varying attempt metadata (run_dir, wall time) into its
        # bytes, so a wrapper digest can never be run-stable. The bare
        # scientific bytes are deterministic for identical science, and
        # write_evidence refuses to overwrite them with anything else.
```

line 589:

```text
            # Honest cycles-only refusal: the evidence is authenticated
            # and quiescence-proven, but with no valid network clock no
            # wall-time claim may be made.
```

line 698:

```text
        # ── verified boundary (the wrapper is the only input
        #    RequirementEvaluator accepts; a stale resource_id is not
        #    authentication) ─────────────────────────────────────────
```

line 785:

```text
        # network_clock_hz is deliberately NOT type-checked here: an
        # absent or invalid clock is a typed UNSUPPORTED outcome
        # (cycles-only refusal), never a call rejection.
```

## `tracks/t3-topology/dse/veritx_dse/application/federated_evaluator.py`

line 136:

```text
    #: explicit reuse linkage (Studio §41): when this analysis did not
    #: execute but returned byte-verified reused evidence, the reused
    #: evidence id rides here (never a synthetic measurement) plus the
    #: matched reuse parents. None on a direct execution.
```

line 145:

```text
    #: reproduction-archival verdict for this analysis (None when the
    #: backend defines no mandatory archival step, e.g. BookSim whose
    #: reproduction replays the sealed bundle). Set by the evaluator,
    #: enforced at aggregation: EVALUATED-but-unarchived fails closed.
```

line 230:

```text
    # The serving adapter is caller-bound: serving experiment inputs
    # ride ServingRunOptions (the context deliberately does not carry
    # them), so the adapter joins the registry only for runs that bind
    # an experiment. Without it, serving questions stay honest
    # UNSUPPORTED rows — never fake planner coverage.
```

line 341:

```text
# ── evidence-reuse orchestration (network leg) ────────────────────────
#
# The safe verification primitives (verify/read_reusable_record) prove
# that STORED bytes are intact, but they cannot skip an execution: the
# full EvidenceCache key contains execution outputs (evidence_id,
# route_dump_sha256, route_observation) unknowable before the backend
# runs. So this layer does lookup-before-execute on the maximal
# pre-execution projection of the parent key, and treats the excluded
# outputs as functionally determined by those inputs under the seeded
# deterministic backend. The determination is then CONFIRMED, not
# assumed: a hit re-reads stored bytes through the verified reader and
# copies them into the current layout with a post-copy digest check.
# Any mismatch executes fresh. A hit never creates a synthetic
# measurement. In-memory process-wide only; strict clock exact-match.
```

line 633:

```text
            # Bundle-relative evidence lives at
            # analyses/network_completion/evidence/backend-evidence.json;
            # no host path is ever recorded in the outcome.
```

line 773:

```text
        # INCONCLUSIVE (or any future non-PASS verdict) is never FAILED
        # and never PASS: the backend executed but decided nothing, so
        # the analysis carries the native verdict openly. (Sibling
        # contract: optimization.real_evaluator._native_inconclusive
        # keys on the "native memory evidence {STATUS}" reason shape —
        # it must also accept ANALYSIS_INCONCLUSIVE, not just FAILED.)
```

line 973:

```text
        # Full field archival (asdict), not the identity projection:
        # reproduction rebuilds the exact executed objects, including
        # the rendered config texts the identity dict omits.
```

## `tracks/t3-topology/dse/veritx_dse/application/preset_certification.py`

line 34:

```text
# ── condition evaluators ───────────────────────────────────────────────
#
# Each evaluator reads the canonical intent and/or the canonical
# compilation. It never guesses: a condition it cannot decide returns
# PENDING_EXECUTION, which blocks a GUIDED_SAFE verdict.
```

line 55:

```text
    # Absence is a verdict, not a crash — but only absence: explicit
    # getattr checks let a programming error propagate instead of
    # silently certifying a fabric with no routing classes.
```

## `tracks/t3-topology/dse/veritx_dse/application/presets.py`

line 185:

```text
# ── metric schema (booksim-parse/v2) ─────────────────────────────────
#
# TWO LATENCY POPULATIONS. BookSim's stats block emits both, and they are
# NOT statistics of one distribution — verified in the fork source
# (third_party/booksim2/src/trafficmanager.cpp):
#
#   Packet latency average / \tmaximum        <- _plat_stats[c]      (qtime)
#   p50 / p95 / p99 / honest_avg / pkt_count  <- _all_latencies[c]   (request)
#
#   _plat_stats[c]->AddSample(f->atime - head->ctime)     <- qtime slots,
#       which go STALE across idle gaps and inflate sparse-trace means 100x+
#   _all_latencies[c].push_back(f->atime - <original trace request ts>)
#       <- REQUEST time, the same vector the percentiles are sorted from
#
# v1 put the qtime mean and the request-time percentiles in one
# `sim.latency.*` family, so a consumer could read them as one distribution.
# v2 splits them. `sim.latency.avg_cycles` is RETAINED for backward
# compatibility but its definition now states exactly which population it is.
```

line 268:

```text
# Evidence stats key -> metric id (only genuinely produced metrics).
#
# The mapping is what ENFORCES the split: a qtime mean can never be filed
# under a request-time id, because each key has exactly one destination.
```

line 291:

```text
#: Latency metric ids grouped by the statistical population they belong to.
#: A consumer that wants "the latency" must choose a population; there is no
#: single ambiguous family to fall back on.
```

## `tracks/t3-topology/dse/veritx_dse/application/requests.py`

line 18:

```text
# Workload provenance vocabulary: a packet trace is NOT a semantic
# workload. Wave D workloads declare operations explicitly and derive
# their trace; legacy traces stay explicitly classified as such.
```

line 225:

```text
                    # Strict-parser refusal vocabulary only: malformed
                    # wave_e reads as INVALID input, while a programming
                    # error propagates instead of laundering into a parse
                    # verdict.
```

## `tracks/t3-topology/dse/veritx_dse/application/requirements.py`

line 81:

```text
# Every documented refusal of the persisted-result verification stack:
# reverify_result (ResultError), NetworkWindowBinding/QTime parsing
# (TimeError), deterministic scheduling (SchedulerError), canonical
# freezing (ImmutableError) and artifact validation (ArtifactError). A
# document that trips any of these is "not verifiable" — callers get one
# EvidenceInvalid taxonomy. Unexpected programming errors
# (KeyError/AttributeError/TypeError) still escape as bugs: this is not
# a broad catch.
```

line 449:

```text
        # ── the workload must be exactly this request's lowering ────
        # Provenance is metadata, not authority: it is excluded from
        # workload_id() by canonical law, so any caller can forge a
        # matching design_hash onto a foreign semantic graph. Re-derive
        # what the request must have produced and compare content
        # identity — never ask the workload who its parent is.
```

line 481:

```text
        # The workload graph identity deliberately excludes traffic-class
        # semantics (the lowering sidecar carries them), so two designs
        # differing ONLY in traffic class lower to the same workload_id.
        # The chain must therefore name the design it measured; a chain
        # without that binding is not a pass.
```

line 518:

```text
                    # No bound network window: the verified makespan
                    # (compute+network wall-time superset) converted by
                    # the DESIGN's own clock. Never the caller's clock.
```

## `tracks/t3-topology/dse/veritx_dse/application/resources.py`

line 156:

```text
        # Current-only: the declaration must still be accepted by the
        # running application semantics (preset revision, policy
        # vocabulary, compiler semantics).
```

## `tracks/t3-topology/dse/veritx_dse/application/results.py`

line 15:

```text
# Wave-C resource envelope (local — the canonical resources.py owns the
# 4-kind CompileIntent persistence and must not be overwritten with the
# old generic envelope; evaluation-plane records carry their own).
```

line 176:

```text
        # Strict-parser refusal vocabulary: CompileRequest.from_dict
        # refuses malformed input with ValueError-family schema errors. A
        # programming error propagates instead of reading as forged
        # evidence.
```

line 381:

```text
    # Parent verification is GENERATION-AWARE: a v1 plan authenticates its
    # Wave-D opgraph, a v2 plan authenticates the canonical WorkloadGraph.
    # The scientific gate below is identical either way — only which
    # authority supplies the operation ids changes. A hard-coded
    # operation_graph_id here would have broken the first v2 plan.
```

line 391:

```text
    # The SHAPE is validated before anything generation-specific is read.
    # A block carrying chain_schema_version=2, a workload_graph_id AND an
    # illegal operation_graph_id is not "a v2 block we can work with": it
    # is malformed, and it must be refused here rather than after a parent
    # load has already been attempted. This is why the version comes from
    # validate_plan_chain_shape() and not from chain_version() alone.
```

line 482:

```text
        # Evidence-IO refusal vocabulary only: the evidence seam raises
        # BackendEvidenceError for unreadable/forged evidence and OSError
        # for IO failure. A programming error propagates instead of
        # reading as failed verification.
```

line 702:

```text
    # 1. Schema closure: a VERIFIED block carries exactly the declared
    #    chain + execution fields, nothing else.
    # 1b. Chain GENERATION: the plan's generation is the contract, and the
    #     result must be the same one. A v1 result never verifies against a
    #     v2 plan, or the reverse: they are different contracts.
```

line 725:

```text
    # the generation-dispatched re-derivation: v1 rebuilds the Wave-D
    # ancestry from its historical resources, v2 reads the WorkloadGraph
    # parent directly (no reconstruction, no legacy IDs)
```

line 920:

```text
    # Unreachable under the ATTEMPT_STATUSES membership check above,
    # but explicit by design: no status may silently fall through
    # into another state's rule.
```

line 1210:

```text
        # Re-derive the refusal through the read-only gate (no writes,
        # no execution): the recorded error code must reproduce exactly.
        # Mirrors SrotaControlPlane.compare minus the store put: the
        # evidence policy runs before compatibility, and either source
        # of refusal is legitimate.
```

## `tracks/t3-topology/dse/veritx_dse/application/revision_diff.py`

line 78:

```text
    # Identity rows: a changed hash IS the derived-identity change. The
    # mapping identity is the rank→endpoint row set; comparing the full row
    # list would ship megabytes, so the row count plus the fabric hash
    # carries the signal and the inspector owns the detail.
```

## `tracks/t3-topology/dse/veritx_dse/application/service.py`

line 180:

```text
        # 6-7. commit the resolution root, then reload it and validate.
        # Only store-domain failures are classified PERSISTENCE: an
        # unexpected RuntimeError/TypeError from a broken internal call is a
        # programmer bug and must propagate unchanged.
```

## `tracks/t3-topology/dse/veritx_dse/application/store.py`

line 284:

```text
                    # Typed-parser refusal vocabulary only: the store's
                    # parsers refuse malformed documents with
                    # ResourceValidationError or ValueError-family schema
                    # errors. A programming error propagates instead of
                    # reading as a corrupt resource.
```

## `tracks/t3-topology/dse/veritx_dse/application/studies.py`

line 125:

```text
#: Error codes that mean "this derivation is not supported", as opposed
#: to an execution failure. The capability registry decides whether the
#: candidate's backend is BLOCKED (serving) or merely UNSUPPORTED.
```

## `tracks/t3-topology/dse/veritx_dse/application/views.py`

line 33:

```text
    # A staged refusal still says WHERE it stopped and what it produced:
    # "compilation failed" would be wrong when upstream derivation was
    # valid and only a downstream contract is unavailable.
```

line 270:

```text
# Canonical artifact chain: design intent -> materialized proof chain ->
# certificate. Order is the compiler's own dependency order (the same DAG
# FABRIC_DAG_VALID revalidates); each node names the parent artifacts it
# was derived from and the certificate obligation(s) that proved it.
```

## `tracks/t3-topology/dse/veritx_dse/application/wave_e_resources.py`

line 128:

```text
        # Strict-parser refusal vocabulary only: TemporalWorkload refuses
        # malformed artifacts with WorkloadError/ValueError. A programming
        # error propagates instead of reading as invalid evidence.
```

line 331:

```text
            # Strict-parser refusal vocabulary only: the binding parser
            # refuses malformed input with TimeError/ValueError. A
            # programming error propagates instead of reading as invalid
            # evidence.
```

line 368:

```text
        # The binding names a workload AUTHORITY, and which key names it
        # depends on the chain generation — the same dispatch as the plan
        # gate. A v1 binding proves a v1 parent; comparing a v2 binding
        # against a v1 key (or the reverse) is a transplant, not a match.
```

line 430:

```text
        # Scheduler refusal vocabulary only: an unschedulable verified
        # workload reads as invalid evidence, while a programming error
        # propagates as an internal failure.
```

## `tracks/t3-topology/dse/veritx_dse/application/waved_resources.py`

line 19:

```text
# Historical v1 authorities (WaveDWorkload, LogicalMessageArtifact v1,
# PhysicalTrafficArtifact v1) were intentionally deleted per §4/§7: the
# canonical WorkloadGraph + V2 artifacts are the sole execution authority.
# v1 persisted resources are therefore explicitly unsupported — the v1
# readers below fail closed rather than resurrecting a second authority.
```

line 45:

```text
# Wave-C resource envelope (local shim — the canonical resources.py now
# owns the 4-kind CompileIntent persistence and must not be overwritten
# with the old generic envelope; waved v1/v2 records carry their own).
```

line 80:

```text
# ── records (write side) ─────────────────────────────────────────────────
#
# M4: the v1 writers are DELETED (waved_semantics_record,
# waved_workload_record, operation_graph_record, messages_record,
# traffic_record had zero callers after the M1.6 cutover — new runs
# never emit wavedworkload/wavedsemantics/opgraph resources). The v1
# READERS below stay frozen for historical verification; the v2
# records are the only writers.
```

line 188:

```text
        # Verification refusal vocabulary only: the Wave-D artifact parsers
        # refuse malformed documents with core InvalidInput/MappingInvalid
        # (VeritXError) or ValueError-family schema errors, and reads fail
        # with OSError. A programming error propagates instead of reading
        # as failed verification.
```

line 316:

```text
        # Strict-parser refusal vocabulary: CompileRequest.from_dict
        # refuses malformed input with ValueError-family schema errors. A
        # programming error propagates instead of reading as forged
        # evidence.
```

line 380:

```text
# The ONE authoritative key sets. Plan identity binds the scientific
# chain; the result adds only execution-derived counters. Both
# constructors assert they emit exactly these keys, so a field can never
# be added to a VERIFIED block without this verifier knowing about it.
# ── chain generations ──────────────────────────────────────────────────
# v1 (historical) authenticates the Wave-D runtime ancestry:
# wavedworkload + wavedsemantics + opgraph. It is READ-ONLY science; new
# writers must not emit it.
# v2 (canonical) authenticates the semantic parent by workload_graph_id
# alone. Absence of chain_schema_version means v1, so the boundary is
# unambiguous without guessing from which keys happen to be present.
```


# `application` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/application/authenticated_evaluation.py` :: `AuthenticatedBackendEvaluation`

```text

    Carries the dereferenced ``EvidenceRef`` and ``EvidenceArtifact``,
    the binding they authenticate, the producer identity the evidence
    names, B's verified result and the canonical RequirementReport
    re-derived from the triple. A caller may use this object as proof;
    the ``certified-backend`` label alone is never proof.
```

## `tracks/t3-topology/dse/veritx_dse/application/authenticated_evaluation.py` :: `VerifiedEvaluationClaims`

```text

    Every field is derived by ``verify_authenticated_backend_evaluation``
    from the re-checked evidence chain — none is accepted from the
    caller's proof object. These are authenticated PRIMITIVES (the
    verified result, its binding, the evidence ref/artifact, backend and
    producer identities, the canonical RequirementReport); metric
    extraction is the optimization layer's job, applied afterwards over
    ``verified_result`` — evidence truth never depends upward on
    optimization.

    ``backend`` is the executed canonical backend profile id and
    ``backend_profile`` its ``execution_fidelity`` label; the exact
    executed configuration identity is ``backend_config_hash`` (the
    binding's key for the canonical evidence ``config_sha256`` bytes).
```

## `tracks/t3-topology/dse/veritx_dse/application/booksim_qualification_registry.py` :: `QualificationRecord`

```text

    `evidence` is no longer a bag of prose. It is:

      qualifier       an executable `module:function` authority over the
                      canonical parents. The qualification IS this function's
                      verdict; nothing else may stand in for it.
      evidence_paths  repository-relative durable documents or tests. Each one
                      must EXIST.

    A record whose evidence does not resolve is not a qualification, so the
    constructor refuses it. `"trust me"` cannot make a profile QUALIFIED.
```

## `tracks/t3-topology/dse/veritx_dse/application/compile_intent.py` :: `CompileIntent`

```text

    ``compiler_semantics_version`` and ``preset_design_hash`` are bound on
    construction (callers do not supply them): they pin the compiler
    semantics and the exact semantic revision of the named preset. If
    explicitly present (deserialization), they must equal the current
    expected values — a stale pin is refused, never accepted silently.
```

## `tracks/t3-topology/dse/veritx_dse/application/design_view_v2.py` :: `_incomplete`

```text

    Mandatory is decided by the canonical contract, never a frontend list.
    The compiler's own reader already enforces everything it requires — a
    document that fails it is INVALID, not INCOMPLETE. What remains is the
    scalar *user decision* the schema permits to be absent: a rendered,
    non-metadata field the registry marks ``default: NONE``.

    Repeated children (requirements, agents, collectives, dependencies,
    address ranges) are excluded: their per-row required fields are
    enforced by the reader, and an empty list is a legitimate design.
```

## `tracks/t3-topology/dse/veritx_dse/application/errors.py` :: `ControlPlaneError`

```text

    Deliberately NOT frozen: frozen dataclass exceptions cannot
    propagate through generator-based context managers (traceback
    assignment raises FrozenInstanceError). Value equality retained.
```

## `tracks/t3-topology/dse/veritx_dse/application/evaluation_context.py` :: `CanonicalEvaluationContext`

```text

    ``request``/``compilation`` bind provenance; ``lowered_workload`` is
    the one canonical lowering; ``workload`` is its graph (the identity
    adapters receive); ``bundle`` is the compiled fabric. Constructed
    ONLY through :func:`build_evaluation_context`, which enforces the
    PASS/identity laws.
```

## `tracks/t3-topology/dse/veritx_dse/application/evaluation_plan.py` :: `EvaluationPlanner`

```text

    Selection law, in order:
      1. query every registered adapter for the question;
      2. an explicitly requested backend is authoritative: unknown is a
         planning error; known returns exactly its row (refusal or
         selection) — never a silent substitution;
      3. drop UNSUPPORTED assessments (they cannot represent);
      4. among the rest, prefer READY over BLOCKED/UNAVAILABLE;
      5. otherwise apply the stated per-question preference order;
      6. ties beyond that are refused loudly, never broken silently
         by registry order;
      7. when nothing qualifies, emit an UNSUPPORTED/BLOCKED/UNAVAILABLE
         row carrying the best (deterministic) refusal reason;
      8. an empty registry is an UNAVAILABLE row, never a crash.
```

## `tracks/t3-topology/dse/veritx_dse/application/fabric_compiler.py` :: `Compilation`

```text

    status COMPILED carries the bundle + passing certificate.
    INVALID/UNSUPPORTED carry evidence (certificate or error) and
    never a bundle — a failed proof is not a fabric.

    A refusal that happened *after* upstream artifacts were derived also
    carries a :class:`StagedDerivation`, so those artifacts stay
    inspectable. `bundle` remains None: a staged result is not a fabric.
```

## `tracks/t3-topology/dse/veritx_dse/application/fabric_compiler.py` :: `StagedDerivation`

```text

    A later stage refusal must not invalidate already-derived earlier
    artifacts: for a Torus design the topology IS derived (with real
    wraparound channels) and only the routing contract is unavailable.
    Discarding the topology would throw away valid science and turn a
    staged refusal into a fake "invalid design".

    Only artifacts the source actually produced are present. Nothing here
    is ever synthesized: an absent stage stays absent.
```

## `tracks/t3-topology/dse/veritx_dse/application/fabric_compiler.py` :: `compile`

```text

        P1C phase-2: v3 requests compile through the v3 bundle builder
        (genuine v3 derivation — never a fake-v2 conversion); v2 flows
        exactly as before.

        routing_policy opts into the MIN_ADAPT_MESH chain: it must be an
        explicit RoutingPolicyDefinition (a raw routing_function string
        raises TypeError — routing stays LOCKED). The deterministic
        bundle + certificate are derived byte-identically first; the
        adaptive overlay (relation, escape partition, binding,
        realization, escape qualification, adaptive fabric) is derived
        alongside and gated by the escape-subfunction proof. v2 requests
        cannot carry a policy (UNSUPPORTED).
```

## `tracks/t3-topology/dse/veritx_dse/application/federated_evaluator.py` :: `ArchivalResult`

```text

    A typed result, never a swallowed exception: EVALUATED-but-
    unarchived cannot claim reproducibility, so the evaluator fails
    the analysis closed with the missing artifact named.
```

## `tracks/t3-topology/dse/veritx_dse/application/federated_evaluator.py` :: `RamulatorRunOptions`

```text

    Discovery configuration (which vendor tree / interpreter) lives on
    the registered adapter, bound once in the registry — never
    reconstructed per run. Only the wall-clock budget rides here.
```

## `tracks/t3-topology/dse/veritx_dse/application/federated_evaluator.py` :: `ServingRunOptions`

```text

    The serving experiment (cluster service semantics, request trace,
    request count, service-profile overrides) rides here because
    CanonicalEvaluationContext deliberately does not carry it — the
    planner never invents experiment inputs. Presence of these options
    is what registers the serving adapter for the run (see
    evaluate_federated); absence leaves serving questions as honest
    UNSUPPORTED rows.
```

## `tracks/t3-topology/dse/veritx_dse/application/federated_evaluator.py` :: `_evaluate_network`

```text

    Execution-authority note: FabricEvaluator.evaluate drives the
    BookSim adapter seam itself (adapter.prepare -> adapter.execute —
    the single spawn per NETWORK_COMPLETION question), then this leg
    normalizes through normalize_booksim_outcome, which enforces the
    identical admission + parent-binding law as adapter.normalize.
    Unifying the two normalization entries (deleting
    normalize_booksim_outcome in favor of adapter.normalize) requires
    threading the execution result through booksim_adapter — a
    booksim_adapter.py change owned by a later lane, not this one.
    The no-duplicate-execution test below pins the invariant that
    matters: exactly one backend spawn per network question.
```

## `tracks/t3-topology/dse/veritx_dse/application/presets.py` :: `_mesh4_request`

```text

    These are FABRIC presets: a 4-tile mesh carrying a minimal synthetic
    trace (``tiny2`` / ``tiny2x5``). The declared workload is the carrier
    that lets the canonical CompileRequest exist; it is not a model
    workload, and ``tp=ep=dp=1`` means it exercises no parallelism
    structure at all.

    ``model_family`` is therefore DENSE_TRANSFORMER, not MOE. It was MOE
    historically as a placeholder, which made the preset declare a
    workload family its advertised envelope excludes: GUIDED-EXPERT.md
    §preset audit certifies ``mesh4`` under
    ``CAP-ENV-BOOKSIM-MESH-DOR-XY-V1``, whose COND-DENSE-STATIC-WORKLOAD
    requires ``dense_transformer``. A preset must not advertise an
    envelope whose own conditions it fails.

    The correction is identity-only and proven inert for the fabric: for
    ``tp=1, ep=1`` ``Workload.total_npus`` is 1 either way, the traffic is
    trace-driven rather than collective-driven, and every derived artifact
    hash (topology, attachment, mapping, route, resolved route, VC
    assignment, fabric) is byte-identical. Only ``design_hash`` and its
    ``resolved_fabric_hash`` child move, exactly as they did for the
    semantics-v1 -> v2 identity move.
```

## `tracks/t3-topology/dse/veritx_dse/application/product_evaluator.py` :: `ProductEvaluation`

```text

    ``outcome`` is None only when the design never compiled. ``status``
    mirrors the canonical evaluator status (EVALUATED,
    BACKEND_UNAVAILABLE, UNSUPPORTED, FAILED) or the compilation status
    (INVALID, UNSUPPORTED) for a design that could not be compiled.
    ``requirement_report`` exists only for an EVALUATED outcome.
```

## `tracks/t3-topology/dse/veritx_dse/application/requests.py` :: `WorkloadRef`

```text

    Provenance kinds:

    * legacy packet trace (``trace``/``trace_file``): the bytes are the
      ground truth and ``trace_sha256`` is the content digest; no Wave-D
      semantics can be reconstructed from a trace, ever;
    * explicit Wave-D semantic workload (``wave_d``): the declared
      operations are the ground truth and ``wave_d.workload_id()`` is
      the content digest. The BookSim trace is DERIVED from it.
    * optional Wave-E temporal overlay (``wave_e``): an explicit
      TemporalWorkload layered OVER a Wave-D workload — it adds
      WHEN (events/resources/requests) but owns no communication
      semantics (§8: never retrofit compute into Wave D).

    The filesystem path (for ``trace_file``) is transport metadata and
    never enters identity; the bytes always do. An intent without a
    resolved digest has no identity (``intent_id`` refuses).
```

## `tracks/t3-topology/dse/veritx_dse/application/requests.py` :: `resolve_intent`

```text

    Returns (intent with workload identity filled, exact trace bytes or
    ``None`` for a Wave-D semantic workload, transport source metadata).
    Every downstream stage must use these bytes — never reread the file.
    A document digest that disagrees with the resolved bytes refuses (a
    file changed after intent resolution never executes under a stale
    identity). Registry traces resolve without I/O; external files are
    read here, once.

    A Wave-D semantic workload has no trace bytes yet: its trace is
    DERIVED from the verified Wave-D traffic inside the control plane,
    after the fabric is compiled. ``None`` here is therefore a kind
    signal, never an empty workload.
```

## `tracks/t3-topology/dse/veritx_dse/application/requirements.py` :: `VerifiedPerformanceResult`

```text

    The authoritative input to :meth:`RequirementEvaluator.evaluate`: a
    naked dict is NOT authentication — a nonempty ``resource_id`` proves
    nothing about the persisted content — so the evaluator refuses one
    and requires this wrapper. The evaluator re-runs ``reverify_result``
    on every call, so even a hand-constructed wrapper whose content was
    mutated after verification refuses. ``temporal_workload`` is the
    verified parent the result was re-derived against.
```

## `tracks/t3-topology/dse/veritx_dse/application/requirements.py` :: `authenticated_network_cycles`

```text

    The single cycle-recovery authority (RequirementEvaluator's latency
    adjudication and the optimization metric registry both call THIS
    function — the rule exists once, never mirrored).

    The binding is the only source of AUTHENTICATED fabric cycles: it
    records (duration, network_clock_hz) as the exact image of the
    backend's integer completion_time under that clock. Multiplying the
    pair recovers that integer exactly — the caller's clock cancels —
    and a pair that does not reconstruct an integer cycle count is
    refused rather than measured. Returns (None, "") when no window
    duration is bound (cycles-only or compute-only evidence).
```

## `tracks/t3-topology/dse/veritx_dse/application/requirements.py` :: `report_passes`

```text

    True iff the report carries at least one entry AND every BINDING
    entry is SATISFIED. Non-binding entries are advisory (a non-binding
    VIOLATED warns, never fails). A binding NOT_APPLICABLE entry fails
    the gate: construction refuses binding requirements that declare
    no bound, so a binding entry with nothing to measure is either a
    hand-crafted report or a waived bound smuggled past intent —
    fail-closed applies, and the old vacuous-spec pass is gone.

    An EMPTY entry set is NEVER a vacuous success: a report with no
    entries is evidence for nothing (it cannot be distinguished from a
    fabricated empty stand-in), so it returns False — "no entries =>
    not satisfied", the explicit form of the typed refusal.
```

## `tracks/t3-topology/dse/veritx_dse/application/resources.py` :: `CompileIntentRecord`

```text

    Exactly the identity-bearing declaration; no presentation name, no
    derived design/mapping/fabric/resolved hash, no timestamp, no user, no
    git SHA. The resource key is ``intent_id``.
```

## `tracks/t3-topology/dse/veritx_dse/application/resources.py` :: `CompileResolution`

```text

    No hash field, no name, no candidate-policy duplicate, no mapping hash,
    no fabric hash, no backend, no verification, no timestamp. The storage
    key is ``intent_id``, and there is deliberately no independent content
    hash: a second hash domain would give one compiled design two competing
    canonical ids, since ``ResolvedFabric`` already owns that identity.
```

## `tracks/t3-topology/dse/veritx_dse/application/results.py` :: `_verify_waved_result`

```text

    The verified plan is the authority for the scientific chain. Proving
    that the result's chain is internally valid is a DIFFERENT question
    from proving that it is THIS experiment's chain: two individually
    valid chains can describe byte-identical BookSim traffic (phase is
    not representable in a five-column trace), so a transplant would
    otherwise pass every local check. The verifier therefore:

      1. closes the result block's schema (no unknown fields),
      2. requires the result's chain to equal the plan's chain exactly,
      3. re-derives the chain from the PLAN's traffic parent,
      4. re-derives the execution counters from that traffic and from
         the authenticated evidence.
```

## `tracks/t3-topology/dse/veritx_dse/application/results.py` :: `load_verified_workload`

```text

    The content ID covers trace bytes, byte length and endpoint count
    (plus the verified Wave-D semantic chain for a Wave-D workload).
    ``packets`` and ``source`` are OBSERVATIONAL: they are deliberately
    outside the content hash and must never be read as authenticated
    scientific fields. ``workload_kind`` is the provenance label.

    A Wave-D workload is verified all the way down: the persisted
    semantic chain is re-loaded through its verified loaders, the chain
    block is recomputed, and the derived trace is re-rendered and
    re-hashed against the stored digest.
```

## `tracks/t3-topology/dse/veritx_dse/application/service.py` :: `CompileOutcome`

```text

    No hash, no schema, no persistence format, no timestamp, no backend.
    The convenience properties derive from the committed resolution rather
    than duplicating stored identity values.
```

## `tracks/t3-topology/dse/veritx_dse/application/views.py` :: `lowering_view`

```text

    This is the "workload -> operations -> collectives -> logical
    messages" authority, built ONLY from the real canonical lowering —
    the same construction the evaluator lowers to physical traffic before
    every run. Per-step messages stay inspectable (bounded), but this view
    is a projection of the artifact, never a reimplementation of it: the
    artifact identity hash is computed by the canonical class itself and
    carried verbatim.

    Raises TypeError for a non-request, and the lowering's own typed
    errors for a workload whose semantics cannot be projected — an
    unprojectable workload stays unprojectable (no empty view).
```

## `tracks/t3-topology/dse/veritx_dse/application/wave_e_resources.py` :: `verify_wave_e_result_block`

```text

    The verified plan is the authority for the performance semantics and
    for the Wave-D chain; the authenticated evidence is the authority
    for network timing. Nothing in the block is trusted as copied text:
    the schedule is re-run and every summary compared. Checks, in order:

      1. schema closure against RESULT_WAVE_E_KEYS,
      2. the block claims the PLAN's temporal-workload/model binding,
      3. the temporal workload resource re-verifies from the store,
      4. the Wave-D chain IS the plan's chain (transplant refusal),
      5. the network binding cites THIS run's authenticated evidence,
         backend hashes, Wave-D chain, clock and window kind,
      6. the schedule is re-run from the verified workload + binding and
         ``makespan``/``network_window`` must match,
      7. the fidelity warning is re-derived from the verified model.
```


# `application` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/application/authenticated_evaluation.py` :: `authenticate_backend_evaluation`

```text

    Refuses (``EvidenceInvalid`` naming the mismatch): a non-COMPILED
    compilation, a workload that is not the compilation request's
    re-derived lowering, a result whose chain/binding does not describe
    this triple, unreadable evidence, an evidence digest that does not
    match the binding, a stats/backend-input/config/fabric mismatch, a
    missing or mismatched producer identity, or a RequirementReport that
    cannot be re-derived. Wrong argument types raise ``InvalidInput``.
```

## `tracks/t3-topology/dse/veritx_dse/application/authenticated_evaluation.py` :: `verify_authenticated_backend_evaluation`

```text

    Consumption-time authority: re-opens the evidence bytes named by the
    proof's ``EvidenceRef``, rebuilds the ``EvidenceArtifact``, re-checks
    the binding digests, the verified result's chain, the candidate
    request's re-derived lowering and the RequirementReport identity. A
    fabricated proof object, a wrong ``EvidenceRef.sha256``, a mismatched
    artifact, or a transplanted request refuses with ``EvidenceInvalid``.
    No claim is ever accepted from the caller.
```

## `tracks/t3-topology/dse/veritx_dse/application/booksim_qualification_registry.py` :: `validate_registry`

```text

    Every QUALIFIED record must:
      * name a profile that exists in the projection layer;
      * match that profile's exact semantics version (and lowerer version,
        when the profile binds one);
      * resolve its qualifier to a callable;
      * have every evidence path exist.
```

## `tracks/t3-topology/dse/veritx_dse/application/capability_truth.py` :: `_probe_request`

```text

    Authored in v4 because v4 is where typed topology intent lives — and
    because the probe must exercise the SAME vocabulary a user declares.
    Built from the shipped v3 example's workload so the probe uses the same
    science the product does; the workload is migrated, the topology is
    declared.

    A kind whose probe cannot even be CONSTRUCTED is a gate failure: the
    intent registry and the probe registry must agree.
```

## `tracks/t3-topology/dse/veritx_dse/application/certificate_projection.py` :: `cdg_analysis_verdict`

```text

    Read from evidence keys, never from the failure message: the message is
    prose and prose is not an interface.

        acyclic is True                     -> PASS
        acyclic is False, cycle present     -> FAIL
        unsupported_reason, no acyclic      -> UNSUPPORTED
        no analysis evidence at all         -> NOT_RUN
```

## `tracks/t3-topology/dse/veritx_dse/application/compile_intent.py` :: `_mesh4_workload`

```text

    DENSE_TRANSFORMER, not MOE: these presets exist to certify a 4-tile
    mesh, they carry a minimal synthetic trace, and ``tp=ep=dp=1`` means
    they exercise no parallelism structure. Declaring MOE made the preset
    fail COND-DENSE-STATIC-WORKLOAD, a condition of the very envelope
    GUIDED-EXPERT.md certifies it under. See application/presets.py for
    the inertness proof.
```

## `tracks/t3-topology/dse/veritx_dse/application/compile_intent.py` :: `derive_compile_request`

```text

    Fresh preset -> canonical to_dict() -> strict overrides -> strip the
    computed identity fields -> canonical CompileRequest.from_dict().
    The preset object itself is never mutated; the canonical parser is the
    final type authority for null leaves. Every user/product declaration
    failure surfaces as CompileIntentError with the canonical underlying
    exception preserved through ``__cause__`` — canonical semantic
    authority is never flattened into this boundary.
```

## `tracks/t3-topology/dse/veritx_dse/application/compile_result_view.py` :: `_claim_table`

```text

    Delegates to CertificateProjectionV1: the claims are aggregated by an
    explicit contribution table, never by a same-name lookup, and the
    deadlock claim carries its underlying analysis verdict so a
    NOT-ESTABLISHED certificate state is never rendered as a detected
    deadlock.
```

## `tracks/t3-topology/dse/veritx_dse/application/compile_result_view.py` :: `canonical_route`

```text

    ``entries[(class, src, dst)]`` is a **channel id**; the next router is
    that channel's destination. The walk terminates in ``LOCAL_EJECTION``.

    This is a query over the frozen payload, never a re-derivation: the
    table it walks is the one captured at certification time.
```

## `tracks/t3-topology/dse/veritx_dse/application/design_view_v2.py` :: `_declares_moe_structure`

```text

    WORK-002's limitation is "no full static dispatch/combine lowering" — it
    is about expert routing, not about a model-family label. A design only
    reaches that limitation when it has expert parallelism or declares
    dispatch/combine traffic. Firing on the label alone would report a
    limitation for a single-NPU trace carrier that has no MoE structure to
    lower — a false capability claim in the opposite direction.
```

## `tracks/t3-topology/dse/veritx_dse/application/evaluation_context.py` :: `build_evaluation_context`

```text

    Laws (each a typed refusal, never a silent downgrade):
      * the compilation is COMPILED — a failed proof is not a fabric;
      * the certificate is PASS — an unverified fabric is not evaluable;
      * the request is lowered EXACTLY once, here;
      * the graph's identity is bound back to this design by
        re-derivation — a transplanted workload is refused.
```

## `tracks/t3-topology/dse/veritx_dse/application/evaluation_question.py` :: `EvaluationQuestion`

```text

    Backend choice belongs to the planner (Federation 07), never to the
    question: asking NETWORK_COMPLETION does not name a simulator.
```

## `tracks/t3-topology/dse/veritx_dse/application/fabric_evaluator.py` :: `_admit_traffic_classes`

```text

    Every LogicalMessage traffic class must exist in the
    VCAssignmentArtifact, map to >= 1 legal VC, and every such VC must
    exist and map to a routing class of the resolved route (which the
    router route must also materialize for execution). Unknown or
    missing classes are a typed refusal — never a silent VC0.
```

## `tracks/t3-topology/dse/veritx_dse/application/fabric_evaluator.py` :: `_require_context_for_workload`

```text

    The canonical context lowers the compilation request exactly once;
    the caller's workload is validated against it by content identity
    only — provenance is forgeable metadata, never authority. A
    transplanted workload is a typed refusal, never a second lowering.
    Returns the ``CanonicalEvaluationContext`` the adapters evaluate.
```

## `tracks/t3-topology/dse/veritx_dse/application/fabric_evaluator.py` :: `_view_hash`

```text

    Engine artifact hashes are bare 64-hex digests while the frozen
    EvaluationView schema requires self-describing ``sha256:<hex>`` for
    design_hash/resolved_fabric_hash. The outcome itself keeps the
    native identities (comparable with == against the artifacts); only
    the view projection prefixes. Strip one ``sha256:`` prefix to map
    a view hash back to its engine identity.
```

## `tracks/t3-topology/dse/veritx_dse/application/federated_evaluator.py` :: `_aggregate`

```text

    A genuine execution FAILED anywhere fails the run even beside
    successes (PARTIAL is incomplete coverage, never a crash mask).
    INCONCLUSIVE executed without deciding: a gap, never a crash.
    Any other non-success, non-failure status (UNSUPPORTED,
    UNAVAILABLE, BLOCKED, NOT_APPLICABLE, ...) is a coverage gap.
    Successful analyses are always preserved in the record.
```

## `tracks/t3-topology/dse/veritx_dse/application/federated_evaluator.py` :: `_evaluate_ramulator`

```text

    Status mapping preserves the native vocabulary: a backend crash
    (EVALUATION_FAILED) is FAILED; INCONCLUSIVE stays INCONCLUSIVE in
    the reason and is never EVALUATED; an unsupported geometry is
    UNSUPPORTED; only a drained PASS normalizes. Requirement binding is
    untouched — still the network PerformanceResult only.
```

## `tracks/t3-topology/dse/veritx_dse/application/federated_evaluator.py` :: `_persist_astra_inputs`

```text

    Fail-closed archival: any persistence fault returns NOT_AVAILABLE
    naming every artifact that did not reach the layout — the caller
    fails the analysis rather than claiming silent reproducibility.
    Only typed faults are converted; anything else escapes.
```

## `tracks/t3-topology/dse/veritx_dse/application/federated_evaluator.py` :: `_persist_ramulator_inputs`

```text

    Fail-closed archival: any persistence fault returns NOT_AVAILABLE
    naming every artifact that did not reach the layout — the caller
    fails the analysis rather than claiming silent reproducibility.
    Only typed faults are converted; anything else escapes.
```

## `tracks/t3-topology/dse/veritx_dse/application/product_registry.py` :: `ProductRegistryError`

```text

    A claim surface that raises this must withhold claims — it must never
    substitute a guess (Gate 8 §137/§138).
```

## `tracks/t3-topology/dse/veritx_dse/application/requirements.py` :: `_makespan_latency_seconds`

```text

    The bound network window is measured as AUTHENTICATED CYCLES
    (``authenticated_network_cycles``); this fallback is reached only
    when no window duration is bound. The verified makespan
    (compute+network superset) is wall time, converted by the DESIGN's
    clock at the call site — conservative: may false-violate, never
    false-pass, and never driven by a caller clock.
```

## `tracks/t3-topology/dse/veritx_dse/application/requirements.py` :: `evaluate`

```text

        Refuses (typed): non-v3 request, non-graph workload, geometry
        mismatch between request and workload, a workload that is not
        exactly this request's re-derived lowering, a naked performance
        result (the verified boundary is required), a performance result
        whose Wave-D chain binds another workload or another design (or
        that carries no chain binding), unknown class scope, or a result
        missing its identity/makespan spine. Per-metric gaps become
        UNMEASURABLE entries, never exceptions and never passes.
```

## `tracks/t3-topology/dse/veritx_dse/application/results.py` :: `_verify_attempt_structure`

```text

    These records are NOT authenticated scientific evidence — no
    successful EvidenceRef exists to bind. Structural validity still
    requires internal coherence: the terminal state and its error
    classification must agree, and no unsuccessful attempt may carry
    success evidence.
```

## `tracks/t3-topology/dse/veritx_dse/application/results.py` :: `_verify_plan_wave_e`

```text

    Plan identity hashes the block, but that only proves the plan is
    self-consistent: without resolving the parent, a plan could bind a
    temporal workload that does not exist, or whose model is not the
    one it names, or that schedules communication this workload's
    operation graph never performs.
```

## `tracks/t3-topology/dse/veritx_dse/application/results.py` :: `load_verified_attempt`

```text

    Successful attempts additionally bind producer provenance to the
    authenticated Wave-B evidence (binary/revision/dirt/tool). Failed,
    timed-out and interrupted attempts verify structurally only — their
    integrity is STRUCTURALLY_VALID with evidence NOT_AVAILABLE, never
    cryptographically authenticated success.
```

## `tracks/t3-topology/dse/veritx_dse/application/results.py` :: `load_verified_design`

```text

    Design identity is content-addressed by its semantic hashes; the
    intent that produced it is NOT part of the record (two intents
    compiling identical fabric share one design resource — only plans
    differ). The design-to-intent link lives on the plan, verified
    there.
```

## `tracks/t3-topology/dse/veritx_dse/application/revision_diff.py` :: `_capability_diff`

```text

    Compares the frozen ``capability_consequences`` (registry authority,
    stable across reads) and the certificate overall. Preflight readiness
    is deliberately EXCLUDED: it depends on the live backend binary in
    this environment, so diffing it would report environment drift as a
    design change.
```

## `tracks/t3-topology/dse/veritx_dse/application/store.py` :: `StoredCompileResolution`

```text

    Carries no independent hash; every member is validated before the
    bundle is returned.
```

## `tracks/t3-topology/dse/veritx_dse/application/studies.py` :: `summarize_study`

```text

    Each record: {status, measurable: bool, constraints_met: bool}.
    Rules: invalid input -> INVALID (never NO_FEASIBLE_DESIGN); backend
    unsupported -> UNSUPPORTED verdict family; nothing measurable ->
    CONSTRAINT_UNMEASURABLE; all crashed/timed out -> INCONCLUSIVE;
    every measured candidate violates -> NO_FEASIBLE_DESIGN; else
    FEASIBLE. Crashes and timeouts are NEVER feasibility evidence.
```

## `tracks/t3-topology/dse/veritx_dse/application/views.py` :: `artifact_chain_view`

```text

    Each node is a real bundle artifact: its identity hash (from
    ``bundle.root_hashes()`` — nothing re-derived), its parent artifacts,
    and the certificate obligations that proved it. Returns None for a
    non-COMPILED compilation: a refused design produced no artifacts and
    no chain may be drawn around that fact.
```

## `tracks/t3-topology/dse/veritx_dse/application/views.py` :: `design_view`

```text

    `compilation`, when given, must be a Compilation FOR THIS REQUEST
    (same design_hash); a COMPILED match fills the read-only
    `locked_derived` block, while an unmatched or non-Compilation
    object raises ValueError — never a cross-design projection.
    Nothing (None) leaves locked_derived null: Studio must never let
    users edit derived state, and this projector never invents it.
```

## `tracks/t3-topology/dse/veritx_dse/application/views.py` :: `staged_topology_view`

```text

    A later stage refusal must not invalidate already-derived earlier
    artifacts. When routing refuses, the TopologyArtifact and
    AgentAttachmentArtifact are still canonical science and stay
    inspectable — they are simply not a fabric, so this view is returned
    ONLY alongside an explicit `stopped_at_stage` and never as a
    TopologyView of a completed compile.

    Returns None when no upstream topology was produced.
```

## `tracks/t3-topology/dse/veritx_dse/application/views.py` :: `topology_view`

```text

    This is the ONLY shape Studio may draw. A topology family name in
    DesignView is intent metadata; the routers, channels and agent
    attachments below are the certified artifact the certificate proved.

    Returns None for a non-COMPILED compilation (a failed proof is not a
    fabric — no empty graph is ever invented in its place).
```

## `tracks/t3-topology/dse/veritx_dse/application/waved_resources.py` :: `load_verified_messages`

```text

    v1 (``srota/WavedLogicalMessages``) authenticates the historical
    OperationGraph parent; v2 (``srota/LogicalMessageArtifactV2``)
    authenticates the canonical WorkloadGraph parent. The dispatch is
    on the persisted type tag — never inferred from which keys happen
    to be present.
```
