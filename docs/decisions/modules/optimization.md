# `optimization` — extracted module rationale

Extracted from the module docstrings of `veritx_dse/{name}` by the 2026-09-29 debloat. Code keeps a one-line pointer; this is the original long-form text.

## `tracks/t3-topology/dse/veritx_dse/optimization/__init__.py`

```text
veritx_dse.optimization — P2 guided optimization (above the compiler).

Deterministic search + Pareto over GUIDED CompileRequest knobs with a
fake deterministic evaluator (the real P1B/P1C adapter arrives at
integration — see evaluators.py for its contract).

    OptimizationDefinition  what to search (definition.py)
    Candidate               base request + GUIDED patch (candidate.py)
    search_candidates       grid/enumeration/seeded-random (search.py)
    evaluate_all            constraint verdicts (constraints.py)
    pareto_ids              frontier (pareto.py)
    Optimizer.optimize      search -> evaluate -> Pareto (result.py)
    FakeDeterministicEvaluator  in-dev port (evaluators.py)

Every candidate recompiles LOCKED properties (routing, VC
count/structure, turn restrictions, escape VC) via FabricCompiler.
The optimizer never sets them: they are structurally inexpressible in
the definition domain and the patch keys.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/candidate.py`

```text
veritx_dse.optimization.candidate — Candidate = base + GUIDED patch.

A candidate is NEVER an anonymous hardware dict: it is a base
CompileRequest identity plus a GUIDED patch that re-emits a full
candidate CompileRequest. LOCKED properties have no patch key (see
definition.GUIDED_PARAMS); they recompile via FabricCompiler.

Identity: candidate_id = H(base_design_hash, canonical patch), so
execution order never changes candidate identity. Patch key order and
domain declaration order are non-semantic.

Provenance: the base+patch authority shape REPLAYS synthesis/compiler.py
(candidates arrive from the caller, never synthesized inside the
evaluator) and wave-f space.py candidate_identity
(H(design_space_id, assignment, intent ids)); the patching seam is the
product CompileRequest dataclasses.replace on NocConfig (NOT Wave-F's
fabric_overrides intent patching — SUPERSEDED, see CAPABILITY-LEDGER.md).
```

## `tracks/t3-topology/dse/veritx_dse/optimization/capabilities.py`

```text
capabilities — the product-facing optimization capability description.

WHY THIS EXISTS (PRODUCT-CONVERGENCE-V1 PHASE 2)
================================================

The Studio must not hard-code what VERITX can optimize. Every control it
renders must come from a canonical backend authority, or the UI becomes a
second, silently-diverging registry.

THE CENTRAL DISTINCTION
=======================

    A field existing in GUIDED_PARAMS does NOT mean every value is usable.

So each parameter reports FOUR independent facts, and they are not collapsed:

  expressible        the definition schema accepts the parameter at all
  accepted_values    values the canonical compiler will accept (or None when
                     the domain is a validated range/type rather than a
                     finite enumeration)
  executable_values  the subset the CERTIFIED BACKEND can actually execute
                     (or None when not separately narrowed)
  qualified          whether the value is currently usable for product
                     optimization at all

FAIL CLOSED. A value that will deterministically fail downstream is not
advertised as available. Where an authority cannot be established, the field
reports `None` with a REASON — never an invented list.

WHY SOME VALUES ARE PROBED AND NOT DECLARED
===========================================

`topology_family` is the one parameter with a real finite enumeration
(`TopologyFamily`), and membership there means "authorable", NOT
"materializable", and materializable does NOT mean the certified backend
executes it. So the domain is obtained by ASKING twice: the canonical
materializer bounds `accepted_values`, and the full certified chain
(compile → workload lowering → `select_booksim_profile`) bounds
`executable_values` — the same gate `ProductService` applies before any
evaluation. A value that is deterministically refused at evaluation is
never advertised as an optimization choice.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/capability_probe.py`

```text
capability_probe — ASK the compiler+projector what a knob actually does.

WHY THIS EXISTS (PRODUCT-CONVERGENCE-V1 PHASE 2.1)
==================================================

`NocConfig` accepting a field means the SCHEMA accepts it. It does not mean
the certified backend measures its effect. Advertising "accepts this field"
as "certified optimization can search this field" is how a UI ends up
offering knobs that silently do nothing.

THE DECISIVE TEST — byte identity of the projection's INPUTS
===========================================================

`prepare_booksim_input` is a PURE FUNCTION of `BookSimProjectionParents`:
topology, attachment, mapping, vc_resource, packet_format, route,
physical_traffic, resolved_fabric.

So if patching a parameter leaves every one of those artifact identities
unchanged, the backend bytes CANNOT differ. The parameter is IDENTITY-ONLY:
it changes `design_hash` while execution stays byte-identical. That is the
same defect class as the `priced_geodesic` false contract, and it is
detectable without spawning the binary.

Where the projection's own closed-world audit (`_AUDIT`) has no row for a
concept at all — no `channel_width`, no `arbiter_type`, no multicast
parameter, no RCU parameter — a field that can only reach the backend through
such a row is ineffective by construction. The probe does not need to know
that: comparing artifact identity already answers it.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/completeness.py`

```text
veritx_dse.optimization.completeness — search completeness accounting.

THE DEFECT THIS REPAIRS
-----------------------

``search.py::search_candidates`` applies the budget as a silent prefix
truncation::

    cands = enumerate_candidates(base, defn)
    limit = _budget_limit(defn)
    if limit is not None:
        cands = cands[:limit]        # <- no completeness fact survives
    return cands

A consumer therefore cannot distinguish an exhaustive search from a
truncated one. The historical vocabulary existed and was removed
(``EXHAUSTIVE_GRID`` in 2 commits, ``BUDGETED_GRID`` in 3,
``NOT_EVALUATED`` in 4); ``optimization/CAPABILITY-LEDGER.md`` row W11
records the loss as ``HISTORICAL`` with the reason *"no
ALIAS/INVALID/NOT_EVALUATED states in P2"*.

Silent truncation is the exact failure mode that vocabulary existed to
prevent: a budgeted search that looks exhaustive will be read as an
optimality claim.

THE LAW
-------

Seven mechanical invariants (each is a test, not prose):

1. Truncation is identity/evidence-visible.
2. ``EXHAUSTIVE`` is never inferred — only claimed when
   ``universe_known`` and ``evaluated_count == universe_size``.
3. Non-evaluated candidates remain represented; absence must not look
   like nonexistence.
4. Pareto uses only eligible, evaluated candidates (unchanged).
5. Requirement violation stays separate from Pareto eligibility
   (unchanged).
6. Generated objective != evaluated metric (unchanged).
7. A synthesis engine cannot manufacture a certificate or evidence
   (unchanged; synthesis is a candidate producer, not an authority).

PRODUCT LANGUAGE
----------------

* exhaustive finite enumeration, all resolved:
  "complete over this declared finite design space"
* budgeted / synthesized:
  "best observed among evaluated candidates"
* otherwise: no optimality claim at all.

Never "optimal NoC" without a fully qualified scope.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/constraints.py`

```text
veritx_dse.optimization.constraints — hard-constraint verdicts (P2).

Truth table over exact comparisons (floats compared directly; the fake
evaluator emits short decimals, so no Fraction machinery is needed):

    measured value, op satisfied  -> SATISFIED (with margin)
    measured value, op violated   -> VIOLATED  (with excess)
    missing/None value            -> UNMEASURABLE (NEVER a pass)

Feasibility: every declared constraint SATISFIED. One VIOLATED rejects;
one UNMEASURABLE leaves feasibility unproven (fail-closed, never a
silent pass).

Provenance: REPLAYS the North-Star reference constraints module
(Constraint.evaluate for <=/>=) extended with the
UNMEASURABLE fail-closed arm from synthesis/compiler.py
(_UNMEASURABLE bandwidth floors) and wave-f constraints.py §47
(unmeasurable never passes). No expression parsing: operators are
exactly <= / >= (wave-f §45 rule, REPLAYED). Duplicate metric
constraints refuse (one metric, one verdict slot) instead of
last-write-wins.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/definition.py`

```text
veritx_dse.optimization.definition — OptimizationDefinition (P2).

Search semantics ABOVE the compiler: objectives, constraints, search
budget, seed policy, search method, and the GUIDED design domain.
Identity is per-metric: duplicate objective metrics and duplicate
constraint metrics refuse at construction (one metric, one verdict;
no silent last-write-wins).

Allowed domain dimensions are NocConfig GUIDED knobs only
(link_width, concentration, radix, rcu_enabled, topology_family,
arbitration, mcast_groups, mcast_setup_cycles). LOCKED properties
(routing algorithm/function, VC count/map, turn restrictions, escape
VC) are structurally inexpressible here: naming one raises
OptimizationDefinitionError. Every candidate recompiles LOCKED
properties via FabricCompiler; this module never sets them.

Provenance: domain-canonicalization and content-identity shape REPLAY
the North-Star reference optimization definition module
(Parameter/Objective/definition_id) and wave-f/design-optimization
space.py canonical ordering (§83/§84: declaration/value order never
changes identity); the GUIDED registry replaces Wave-F's
fabric_overrides PARAM_REGISTRY (which patched intents outside the
product CompileRequest authority — SUPERSEDED, see CAPABILITY-LEDGER.md).
```

## `tracks/t3-topology/dse/veritx_dse/optimization/evaluators.py`

```text
veritx_dse.optimization.evaluators — evaluation ports (P2).

CandidateEvaluationPort protocol + deterministic fake evaluator for
development and tests. No dependency on P1B/P1C branches.

FUTURE REAL ADAPTER (at integration, no optimizer rewrites unless the
interface mismatches — P1 contract §7 step 3):

    candidate CompileRequest
      -> FabricCompiler().compile(request)          # LOCKED consequences
      -> P1C lower_compile_workload(request)        # WorkloadGraph (v3)
      -> P1B FabricEvaluator.evaluate(              # authenticated perf
             compilation, workload, options)
      -> P1C RequirementEvaluator.evaluate(         # RequirementReport
             request, workload, performance)
      -> CandidateEvaluation{objective_values from PerformanceResult,
                             constraint verdicts from RequirementReport}

The real adapter must supply, per candidate: the compilation status +
certificate, workload/message/traffic IDs, backend producer identity +
config/input hashes, raw evidence + stats digests, performance_result_id,
and per-requirement {verdict, required, measured} bindings. UNMEASURABLE
never passes. BACKEND_UNAVAILABLE/UNSUPPORTED/FAILED stay visible and
never enter the Pareto set.

The fake below compiles every candidate through the REAL FabricCompiler
(LOCKED routing/VC consequences proven, never set) and then scores
deterministic analytic objectives as a pure function of the candidate
request — the stand-in for (lower -> evaluate -> requirements) until
the real adapter lands.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/metric_registry.py`

```text
veritx_dse.optimization.metric_registry — certified metric authorities.

Law (RT-final R2/C2): the certified metric authority is a FROZEN,
VERSIONED, identity-bearing product artifact. There is no public mutation
API on a frozen registry, and the certified entry point does not accept a
caller-supplied registry at all — certified optimization uses the
product-controlled ``CERTIFIED_METRIC_REGISTRY`` only. Extensibility goes
through an approved registry catalog (qualification -> registered producer
semantics -> approved registry ID -> certified execution), never runtime
selection. Plugins live in a separate
:class:`ExperimentalMetricRegistry` that can never yield
CERTIFIED_PRODUCT Pareto.

``registry_id()`` binds a declared semantic identity per metric —
``metric + producer_id + producer_semantics_version`` — not merely the
metric name, so ``{latency: ->1.0}`` and ``{latency: ->999999.0}`` can
never share an ID. (The callable itself need not be hashed; its declared
identity is the audit handle.) The resulting
``OptimizationResult`` binds ``metric_registry_id`` and
``metric_registry_version``.

One authority per metric: the cycle-recovery rule lives in
``requirements.authenticated_network_cycles`` and is not mirrored here.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/pareto.py`

```text
veritx_dse.optimization.pareto — Pareto frontier (P2).

MOVED from the North-Star reference optimization pareto module
(pareto_front: exact dominance, MIN/MAX directions, sorted-id
order — reused verbatim, no style rewrites) plus a thin objective-space
adapter and a sealed-gate cross-check against
core.comparison.pareto_with_scope (the Phase-8 authority REPLAYED from
synthesis/compiler.py's Pareto stage).

Ties stay ties: equal objective vectors neither dominate nor eliminate
each other.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/real_evaluator.py`

```text
veritx_dse.optimization.real_evaluator — real CandidateEvaluationPort.

The production route (fake stays unit-only):

    candidate CompileRequest (v3)
      -> FabricCompiler.compile()              (LOCKED consequences)
      -> lower_compile_workload()              (P1C WorkloadGraph)
      -> assert_traffic_classes_bound()        (pre-spawn gate)
      -> evaluate_federated()                  (plan once, one execution
                                               per question, objectives read)
      -> authenticate_backend_evaluation()     (A4 evidence-chain proof,
                                               network leg only)
      -> CandidateEvaluation (proof + evidenced objectives only)

Feasibility law: `evaluation_status` preserves the REAL taxonomy and
is never collapsed. EVALUATED means compiled AND every requested
question backend-evaluated (binding product requirements may still
fail — those candidates keep their measurements and a typed reason,
and the Optimizer makes them ineligible). Compile-phase refusals
(INVALID or UNSUPPORTED compiler verdicts) are COMPILE_FAILED;
lowering refusals are INVALID or UNSUPPORTED; backend-phase outcomes
stay BACKEND_UNAVAILABLE / FAILED / UNSUPPORTED, plus INCONCLUSIVE
when a native verdict drained without deciding (Ramulator). Whatever
provenance exists is still bound (locked consequences,
performance_result_id, per-objective federation provenance) —
visible, auditable, never Pareto-eligible. `compilation_status`
separately keeps the FabricCompiler verdict.

Federation law: the candidate compiles ONCE, the canonical context is
built ONCE, the planner adjudicates ONCE, and each required question
executes ONCE — objectives only read the analyses their question
produced (three objectives over NETWORK_COMPLETION + DRAM_TIMING is
one BookSim run plus one Ramulator run, not three). A
``requested_backend`` is never invented here: when the definition
constrains an objective to a backend the planner did not select, the
objective is unmeasured with an exact reason — never silently
substituted.

Objectives are evidenced measurements only: network-question metrics
come from the FROZEN certified metric authority over the VERIFIED
network performance result (unchanged sealed path); every other
question's metrics come from that analysis's normalized envelope
(scalar objectives bind dimension-free metrics only). There is
deliberately no area/latency-analytic key: unmeasured is absent,
never faked. Widening the metric set means binding a new qualified
producer (metric_registry.py), not adding a key here.

A4 proof: every network-EVALUATED outcome (including a
requirement-violating one) carries the `AuthenticatedBackendEvaluation`
built by Worker B's evidence-chain authority, so the Optimizer can
verify the proof and extract authoritative metrics from the derived
claims instead of trusting the `certified-backend` label or the
evaluator's own objective values. A non-EVALUATED outcome carries no
network measurements and therefore no proof. Non-network analyses
carry their own native evidence (native_evidence_id in the
provenance); the normalized envelope is a view, never the authority.

Legacy parity: with no ``objectives``/``questions`` (the gateway
single-evaluation path), this port evaluates NETWORK_COMPLETION only
through the certified BookSim leg with the same effective parameters
as before (binary, repo root, network clock, timeout, seed 0,
quiescent default) — the only difference is transport (evidence lives
under analyses/network_completion/ of the slot). Objective values are
bit-identical to the pre-federation path.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/result.py`

```text
veritx_dse.optimization.result — OptimizationResult + Optimizer (P2).

OptimizationResult binds: base request identity, definition,
candidate/evaluation IDs, objective values, constraint verdicts, Pareto
membership, selection rationale. Execution order never changes
candidate identity (re-derived and refused on mismatch, never an
assert).

TWO AUTHORITIES, NEVER MERGED:

* the PRODUCT RequirementReport answers "did the design satisfy the
  customer's requirements?" — carried as requirement_report_id,
  product_requirements_satisfied and product_requirement_details;
* the optimizer's own hard constraints answer "did the candidate
  satisfy the study's constraints?" — carried as constraint_verdicts
  (SATISFIED/VIOLATED/UNMEASURABLE), constraint_details and
  constraints_satisfied.

Objectives are a third, measured-only namespace (objective_values).
A candidate is Pareto-eligible only when its evaluation succeeded AND
Worker B's verifier authority re-proved the carried authenticated proof
for this request (A4: the verifier's derived claims are the authority;
the `certified-backend` label alone admits nothing) AND every requested
objective/constraint metric has a registered producer over those claims
AND its study-answerable binding product requirements pass (a binding
requirement answers exactly one federation question's evidence; a study
that asks no such question leaves it visibly unevaluated instead of
poisoning measured objectives) AND every requested objective
is measured and finite AND every hard constraint is SATISFIED. For a
certified candidate the evaluator's `objective_values` never score —
registered metrics are extracted from the proof and an unregistered
requested metric is UNMEASURABLE/ineligible. Ineligible candidates stay
visible with typed reasons and never reach pareto.py's indexing (never
a KeyError).

Emits OptimizationStudyView per the authoritative
contracts/srota/v2/optimization.study.view.schema.json
(contract_version 2 by default; contract_version=1 keeps the frozen
boolean-only v1 shape at contracts/srota/v1/ for pinned callers — that
projector is explicitly LOSSY and never claims to preserve three-state
semantics).

Provenance: result-identity and re-derivation discipline REPLAY
synthesis/compiler.py (request/budget/scope accounting, Pareto only over
the feasible set, relaxation as information) and the reference
result.py (content_id over definition + candidate rows + frontier);
Wave-F result.py's verified-loader machinery is SUPERSEDED (no control
plane / store in P2 — the fake evaluator carries no persisted evidence;
see CAPABILITY-LEDGER.md).
```

## `tracks/t3-topology/dse/veritx_dse/optimization/search.py`

```text
veritx_dse.optimization.search — deterministic search first (P2).

Enumeration, grid, and bounded seeded random as the correctness oracle.
Bayes/MILP refuse until deterministic correctness is established.

Canonical order (REPLAYED from reference search.canonical_assignments
and wave-f space.iter_raw_assignments §24/§83/§84): parameters sorted
by name, domain values sorted by canonical JSON; the first parameter
in canonical order varies slowest (lexicographic product). Declaration
order never changes the searched set; budget truncation keeps the
canonical prefix, never a sample (wave-f §23 rule, REPLAYED).

No blind Wave-F merge: BO/RHO/GRPO/SA/MILP loops are NOT imported here
(REJECTED/HISTORICAL per CAPABILITY-LEDGER.md).
```

## `tracks/t3-topology/dse/veritx_dse/optimization/space_multiscenario.py`

```text
veritx_dse.optimization.space_multiscenario — multi-scenario studies.

Wave-F re-expression on CompileRequest authority (NO fabric_overrides):
a study binds one base design, N scenario workloads, scenario-scoped
objectives/constraints, and a searchable domain. Candidates are built
once per study; each candidate is evaluated against exactly the scenario
intents in its identity.

Accounting (INVALID vs FAILED vs NOT_EVALUATED):
- INVALID  build-time refusal (bad patch value, LOCKED/dead dimension,
  mapping infeasible by canonical constructor). Terminal, never evaluated.
- ALIAS    duplicate patch: first occurrence is VALID, later ones are
  aliases evaluated once under the canonical first identity.
- NOT_EVALUATED  valid but budget-unreached (canonical-prefix tail).
  Non-terminal; tail agreement is verified, never assumed.
- FAILED / SUCCEEDED  per-(candidate, scenario) evaluation outcomes,
  recorded by the evaluator, never invented here.

Hardware consistency: scenario requests for one candidate must differ
ONLY in workload. check_hardware_consistent proves it pairwise
(dataclasses.replace equality); anything else refuses as transplant.

Search order replays search.py canonical semantics (sorted names, JSON
sorted values, canonical prefix truncation, seeded shuffle for random).
```

## `tracks/t3-topology/dse/veritx_dse/optimization/study_runner.py`

```text
Wave-F study runner — executes a MultiScenarioStudy beside the optimizer.

AUTHORITY (supervisor decision, final): space_multiscenario stays OUT of
Optimizer/result.py/real_evaluator.py. This module is the NEW execution
authority for multi-scenario studies: build/accounting from
space_multiscenario, one federated execution per (candidate, scenario,
question) at most, evidence rows bound per scenario+candidate.

What this module NEVER does:
- certified Pareto/selection (result_class is STUDY_GRADE, never
  CERTIFIED_PRODUCT; ``certified=True`` refuses — the Optimizer stays the
  only certified path);
- backend pinning (planner AUTO only; a ScenarioObjective with
  ``backend_id`` set refuses — pinning is expert execution policy);
- metric extraction (per-question outcomes + native evidence ids ride the
  rows; metric names live in the metric authority, never re-derived
  here);
- double evaluation (ALIAS known_ids + canonical-prefix tail are never
  attempted; verify_tail_agreement re-checks at the end);
- scenario transplant (scenario_request_for + check_hardware_consistent
  gate every execution).
```


# `optimization` — extracted inline comments

## `tracks/t3-topology/dse/veritx_dse/optimization/candidate.py`

line 69:

```text
    # Integration: v3 bases patch through the identical replace path
    # (same NocConfig class, same frozen-replace mechanics); v2 flow
    # is byte-identical — only the gate widens, nothing else branches.
```

line 133:

```text
# ── study patches: fabric + workload parallelism + placement (additive) ──
#
# GUIDED apply_patch is untouched. Study patches extend the same
# base+patch authority to workload parallelism sizes (patched onto
# base.workload) and placement policy (resolved through canonical
# mapping constructors, never JSON). Dead knobs and LOCKED properties
# refuse with reasons at normalization.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/capabilities.py`

line 24:

```text
#: LOCKED properties. These are compiler-derived correctness properties: the
#: UI may show them as CONSEQUENCES of a candidate, never as things to search.
#: Kept explicit and named, mirroring the definition's own refusal tokens.
```

line 74:

```text
    #: The certified backend profile accepts the probed result. Independent
    #: of `effective`: a knob can change executed semantics and STILL be
    #: refused by `select_booksim_profile` (concentration>1 does exactly
    #: that). Qualification requires all of compilable ∧ effective ∧
    #: backend_executable.
```

line 109:

```text
#: Per-parameter type/constraint authority. The TYPES come from
#: `NocConfig.__post_init__` and `NocConfig`'s annotations — the same code
#: that validates a patch — so a type change there cannot silently diverge.
```

line 142:

```text
    # `CUSTOM` is not universally present: where it exists it is a
    # CLASSIFICATION marker for an explicit graph, not a materializable named
    # family, so it is refused either way. Read it by name so a membership
    # change cannot raise here.
```

line 161:

```text
            # A family the canonical materializer does not cover is a
            # refused value, never a crash. Anything else — a
            # programming error in the resolver — propagates instead of
            # reading as "not materializable".
```

line 228:

```text
    # ASK the compiler+projector. `qualified` is NEVER defaulted true: a knob
    # that the schema accepts but the certified backend cannot measure is not
    # a certified optimization dimension.
```

line 294:

```text
    # Federated optimization truth (Prompt 4, Step 8): every metric an
    # objective may name, with the question it is read from, the
    # registered backend(s) answering that question, the model
    # fidelity, the unit and whether it is eligible as a scalar
    # optimizer objective. Derived from the federation registry and
    # the producers' own normalization catalogs — never a second
    # handwritten matrix. A backend listed here may still assess
    # UNAVAILABLE/BLOCKED for a given study: listing is installation,
    # execution is adjudicated per study.
```

line 328:

```text
        # §1: units are not dimensions. A study is multi-objective only when
        # the certified registry offers more than one INDEPENDENT semantic
        # family; today it offers exactly one.
```

line 373:

```text
#: Certified metric -> SEMANTIC OBJECTIVE FAMILY.
#:
#: The registry names three metrics, but they are NOT three independent
#: optimization dimensions:
#:
#:   completion_cycles  the authenticated network completion window, in cycles
#:   completion_time    the SAME window (same producer id)
#:   completion_ns      the SAME window, as wall time
#:
#: All three read the same canonical artifact (`verified["network_binding"]`),
#: so a study over "cycles vs ns" would be a study of ONE quantity expressed
#: twice — a frontier with a single underlying dimension. Treating that as
#: multi-objective would manufacture a trade-off that does not exist.
#:
#: The mapping is declared here and PROVEN against the producers by test
#: (`test_objective_semantic_families.py`), so a genuinely new metric cannot
#: be silently folded into `completion`.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/capability_probe.py`

line 38:

```text
    #: The FULL certified chain (compile → lower → physical traffic →
    #: `select_booksim_profile`) accepts a design patched with the
    #: alternative value. False means every candidate carrying that value
    #: would compile and then be REFUSED at evaluation — never a valid
    #: optimization dimension, no matter how effective it looks.
```

line 123:

```text
    # The lowering error vocabulary lives in ONE place: core.errors.
    # A fragile try/except-import chain here used to degrade all four
    # names to bare Exception whenever one name was missing, which made
    # every typed catch below a bare catch in production. Import the
    # canonical classes directly so the catches below mean what they say.
```

line 179:

```text
        # Artifact-construction validation (VC resources, logical/physical
        # message and traffic artifacts) refuses this parameter value.
        # Anything else — AttributeError, TypeError, KeyError, assertion
        # failures — is a programming error and propagates instead of
        # reading as "not executable".
```

line 188:

```text
#: (parameter, baseline value, alternative value). The alternative is a value a
#: user would plausibly pick; effectiveness is judged by whether the CERTIFIED
#: pipeline produces different projection inputs for it.
```

line 194:

```text
    # radix=2 is a VALUE constraint (2x2=4 seats < 16 endpoints), not an
    # effectiveness failure. The probe uses a value that seats the base, so it
    # measures whether the knob reaches execution — the constraint is reported
    # separately.
```

line 265:

```text
        # Effectiveness alone is not qualification: a knob can change the
        # artifacts and still be refused by the certified profile (e.g.
        # concentration>1 changes the attachment; mesh-DOR refuses it).
        # Ask the same gate the product evaluation path applies.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/definition.py`

line 20:

```text
#: GUIDED patch keys accepted in the domain. Short names map to the
#: NocConfig field patched on the base CompileRequest (see
#: candidate.apply_patch). Dotted "noc_config.*" aliases are accepted
#: and normalized to short names.
```

line 282:

```text
        # Duplicate identity refuses. Two objectives over the same metric
        # are one destination declared twice (declaration order is
        # non-semantic), and two constraints over the same metric would
        # silently overwrite each other in the metric-indexed verdict map
        # (latency<=100 + latency>=50 is deliberately NOT expressible by
        # accident: fail-closed refusal beats last-write-wins).
```

line 390:

```text
# ── Wave-F re-expression: study dimensions (additive; GUIDED path untouched) ──
#
# Wave-F's PARAM_REGISTRY patched fabric_overrides intent paths outside the
# product CompileRequest authority (SUPERSEDED). Study dimensions re-express
# the useful variables ON canonical authority: searchable NocConfig fabric
# knobs, workload parallelism sizes, and placement policy resolved through
# canonical placement/mapping artifacts. Dead knobs and LOCKED properties
# are refused with reasons, never silently dropped.
```

line 399:

```text
#: Fabric knobs searchable in a study. GUIDED_PARAMS additionally lists
#: rcu_enabled / mcast_groups / mcast_setup_cycles / output_formats /
#: obfuscation_level; those are NOT searchable (see DEAD_KNOBS).
```

line 410:

```text
#: GUIDED-listed knobs that must never be study dimensions, with reasons.
#: rcu/mcast are removed/future-contract router resources; output_formats
#: and obfuscation_level are not physical-performance dimensions.
```

line 427:

```text
#: Placement dimension name. Values are placement POLICY names resolved
#: through canonical mapping constructors (see candidate
#: .resolve_study_mapping); only qualified policies are expressible.
```

line 567:

```text
# ── dimension effectiveness (canonical ownership + probes, §18) ──────────
#
# An objective knows which design dimensions can causally affect it. A
# proven no-effect combination is refused for certified studies (it can
# never distinguish candidates); anything else unknown only warns.
# Rationales cite the canonical authority, never intuition.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/evaluators.py`

line 18:

```text
#: Evaluation-authority markers. An optimization result is only eligible
#: when its evaluation was produced by the certified backend pipeline;
#: analytic/fake evaluations are development doubles and are NEVER
#: authoritative (they carry no RequirementReport and no authenticated
#: performance_result_id).
#:
#: ``evaluation_authority`` is DESCRIPTIVE, never proof: the Optimizer
#: does not admit a candidate to authoritative Pareto because a port
#: says "certified-backend". The proof is the carried
#: ``VerifiedPerformanceResult`` (B's boundary) plus the independently
#: re-derived RequirementReport — see Optimizer.optimize.
```

line 155:

```text
    # Per-metric federation provenance for every bound objective value
    # (Step 2: metric key, question, backend id, model fidelity,
    # qualification, native evidence id, unit, value). Empty for legacy
    # and analytic evaluations.
```

line 160:

```text
    # Exact per-objective miss reasons (backend-constraint mismatch,
    # dimensioned-only metric, absent key) so UNMEASURABLE is auditable.
    # Empty means "no recorded reason" — the optimizer falls back to its
    # generic unmeasured reason.
```

line 166:

```text
    # The federated analyses (AnalysisOutcome records) this evaluation
    # executed — the in-memory carriers the optimizer re-derives
    # non-network objective values from (never trusts objective_values
    # for those). Empty for legacy single-backend evaluations.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/metric_registry.py`

line 50:

```text
    #: False = analytical/model-derived output, never a backend
    #: measurement. Analytical metrics extract honestly from the
    #: verified result, but they can never make an objective MEASURED
    #: for certified Pareto nor satisfy a hard constraint — a
    #: makespan-only study with zero backend measurement stays
    #: ineligible (wave_e_honesty_metadata keeps the distinction
    #: visible wherever these are shown).
```

line 272:

```text
# ── Wave-E model metrics (AMEND-5) ──────────────────────────────────────
#
# These are ANALYTICAL/MODEL-DERIVED facts from the verified Wave-E
# performance result — NOT backend measurements. Registering them does NOT
# make them measured; wave_e_honesty_metadata() is what keeps that
# distinction visible, and predictive_validation = NOT_ESTABLISHED must
# remain visible wherever these are shown.
#
# Each producer returns None when the fact is absent. A metric with no
# value is ABSENT, never zero — zero is a measurement.
```

line 392:

```text
#: The product-controlled certified registry (frozen at import). Only this
#: registry is used by ``Optimizer.optimize_certified``.
#:
#: v1 = the authenticated network-window metrics only.
#: v2 = v1 + the Wave-E ANALYTICAL model metrics (AMEND-5). A NEW VERSION,
#:      not a replacement: MetricRegistryBuilder refuses duplicate metric
#:      names, and one authority per metric is the rule. Adding a version
#:      is the documented path; silently replacing a producer is not.
```

line 424:

```text
# ── federated optimization catalog (Prompt 4, Step 8) ─────────────────
#
# WHAT an optimization objective may measure, FROM WHICH question, WITH
# WHICH backend(s), at WHAT fidelity, in WHAT unit — and whether it is
# eligible as a scalar optimizer objective at all.
#
# DERIVED, never hand-written (no second matrix):
#   * question -> backend(s) + fidelity: read from the federation
#     registry's own adapters (their ``capabilities()`` declarations,
#     SUPPORTED rows only). Registration is installation, not
#     readiness: a listed backend may still assess UNAVAILABLE/BLOCKED
#     at plan time — availability is adjudicated per study, never here.
#   * metric keys + units + scalar bindability: read from each
#     producer's single-source normalization catalog
#     (ASTRA_NORMALIZED_METRICS, RAMULATOR_NORMALIZED_METRICS, the
#     serving envelope keys; the certified registry names for the
#     network question, which the optimizer reads from the
#     authenticated proof rather than the envelope).
# A metric with no row here has no optimization meaning: it is absent,
# never zero, and an objective naming it stays UNMEASURABLE.
```

line 512:

```text
    # Declared truth per question: which registered backends claim it
    # (SUPPORTED) and at what fidelity. Readiness is NOT consulted:
    # UNAVAILABLE/BLOCKED backends stay listed (they refuse per study,
    # they are never silently substituted or hidden).
```

line 556:

```text
    # NETWORK_COMPLETION: the optimizer reads these from the
    # authenticated proof through the frozen certified registry (the
    # envelope contributes transport facts only). BookSim native stats
    # honestly carry no unit, so the unit is None — never invented.
```

line 596:

```text
    # DRAM_TIMING: the adapter's single-source key list
    # (RAMULATOR_NORMALIZED_METRICS mirrors normalize(); units are
    # evidence-declared per run, never statically known, so the unit
    # is None here — the envelope row carries the run's own unit).
```

line 614:

```text
    # SERVING_* questions: per-request dimensioned envelopes from the
    # canonical serving authority (NOT a planner path — deliberately
    # never registered, so _backends() is empty by construction and
    # these rows are honestly ineligible as scalar objectives: a
    # scalar objective can never bind a per-request row set, and no
    # invented key suffix may collapse it).
```

## `tracks/t3-topology/dse/veritx_dse/optimization/real_evaluator.py`

line 56:

```text
#: Optimizer-vocabulary status for a native verdict that drained without
#: deciding (Ramulator INCONCLUSIVE). The federated 4-status vocabulary
#: carries it inside the analysis reason (status FAILED + "native memory
#: evidence INCONCLUSIVE: ..."); this port promotes it to an explicit
#: candidate status so UNAVAILABLE memory backends never collapse into
#: infeasible and inconclusive drains never read as crashes.
```

line 166:

```text
        # The BookSim binary is backend-optional: required only when the
        # study asks a network question. An ASTRA-only or Ramulator-only
        # study runs with binary=None; the planner adjudicates every
        # requested question, and evaluate() re-asserts the network
        # requirement before any BookSim-bound options are built, so a
        # None binary can never flow into a network leg. The legacy
        # default (no questions/objectives) still resolves to
        # NETWORK_COMPLETION and therefore still requires BookSim.
```

line 241:

```text
            # Compile-phase refusal: ALL compiler verdicts (INVALID or
            # UNSUPPORTED) map to COMPILE_FAILED, kept distinct from the
            # backend-phase BACKEND_UNAVAILABLE/FAILED/UNSUPPORTED below;
            # the compiler's own verdict stays in compilation_status.
```

line 266:

```text
        # Collision-free per-evaluation evidence slot. The candidate
        # directory is stable transport; mkdtemp() is the OS-atomic
        # uniqueness mechanism (the path is transport, not science), so
        # re-evaluating the same candidate with the same evaluator both
        # completes and never overwrites a prior slot.
```

line 276:

```text
        # Defense in depth for the backend-optional binary: a None
        # binary must never reach the BookSim-bound execution options.
        # Unreachable through __init__ (which refuses this combination),
        # but re-asserted here so post-construction mutation cannot
        # smuggle a network leg past the constructor gate.
```

line 304:

```text
        # No measured network leg. Two honest cases, never collapsed:
        # (a) NETWORK_COMPLETION was not requested and every requested
        #     analysis EVALUATED: the study measured exactly what it
        #     asked — EVALUATED with the bound federated values and
        #     their provenance (no authenticated network proof and no
        #     product RequirementReport exist here; the Optimizer keeps
        #     such candidates visible but product-ineligible with a
        #     typed reason — never Pareto-eligible without a binding
        #     report, never refused as a forgery either);
        # (b) otherwise the exact backend-phase refusal taxonomy per
        #     question (an unavailable memory backend stays unavailable,
        #     never infeasible; an inconclusive native drain stays
        #     INCONCLUSIVE, never a crash).
```

line 363:

```text
        # A4: the authoritative proof is Worker B's evidence-chain
        # authentication, built from the live outcome's persisted
        # evidence; the canonical report comes from the proof.
```

line 396:

```text
            # Simulated successfully, product requirements failed: the
            # evaluation stays EVALUATED with its measurements and a
            # typed reason; the Optimizer makes it Pareto-ineligible.
            # Never relabel a measured run as UNSUPPORTED.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/result.py`

line 125:

```text
#: Result classes. Only ``CERTIFIED_PRODUCT`` comes from the optimizer-
#: owned certified entry point; ``ANALYTIC_RESEARCH`` can never contain
#: certified Pareto.
```

line 669:

```text
            # Unit/fidelity/qualification must be IDENTICAL across the
            # eligible set (a cycles-only None unit matches a None
            # unit — BookSim native stats honestly carry no unit — but
            # never a "cycles" unit, and never a different fidelity).
```

line 740:

```text
            # The proof does not evidence a finite value for this
            # registered metric: it is UNMEASURABLE and the evaluator's
            # number is ignored, never used.
```

line 790:

```text
    #: Per-measured-objective federation provenance (Step 2): one row
    #: per bound metric {metric_key, question, backend_id,
    #: model_fidelity, qualification, native_evidence_id, unit, value},
    #: in metric order. Part of result_id: equal floats from different
    #: models hash differently.
```

line 812:

```text
    #: Search completeness accounting. Identity-bearing: a budgeted search
    #: and an exhaustive one over the same space MUST hash differently, so
    #: a truncated result can never be presented as complete.
```

line 818:

```text
        # Binds evaluation provenance, not just rounded objectives: two
        # authenticated evaluations with equal objective floats but
        # different performance_result_id, status, requirement bindings
        # or locked consequences hash differently. It must move when the
        # evaluation provenance moves.
```

line 1169:

```text
        # C4: THE single production assignment site of CERTIFIED_PRODUCT.
        # Core mechanics never classify and never stamp registry identity;
        # only this wrapper may, and only from the product-controlled
        # registry (never a caller-supplied one).
```

line 1205:

```text
            # Identity stability: order never changes candidate identity.
            # Explicit conditionals (not assert) so production gates do not
            # vanish under python -O.
```

line 1228:

```text
            # Product-requirement authority (separate from the optimizer's
            # constraint authority): a report is accepted only when it is
            # THIS candidate's report, and a binding failure makes the
            # candidate optimization-ineligible even though the backend
            # returned EVALUATED.
```

line 1235:

```text
            # A federated EVALUATED without a network leg carries no
            # authenticated proof and no performance_result_id (there is
            # no network PerformanceResult to authenticate) — it is a
            # measured non-network evaluation, not a certified claim.
            # It flows through the report-binding path below (report
            # None → visible, product-ineligible, typed reason — never
            # Pareto-eligible without a binding report, never refused
            # as a forgery). A network-measured EVALUATED (a
            # performance_result_id exists) without its proof still
            # refuses: an unverified network number is a forgery smell,
            # never an analytic reading.
```

line 1254:

```text
                    # R1: the analytic entry point structurally refuses
                    # certified claims — an arbitrary port can never
                    # reach certified eligibility here.
```

line 1265:

```text
                # A4: import and call Worker B's verifier authority; the
                # derived claims (and the report they derive) are the only
                # authoritative facts. Never duck-type the proof.
```

line 1288:

```text
            # Measured values are real finite numbers only; a declared
            # objective without one is UNMEASURABLE (never 0, never
            # infinity, never a backend failure masquerading as a score).
```

line 1300:

```text
                # A4/R2: certified metrics come ONLY from the frozen
                # certified registry over the verified claims; the
                # evaluator's objective_values never score (a
                # registered-metric misreport refuses).
```

line 1308:

```text
                # Federation: non-network questions re-derive from the
                # carried analyses (same misreport discipline). Two
                # models evidencing one key is a collision, never a
                # merge — the evaluator already refuses it; this is
                # the second gate for ports that bypass it.
```

line 1332:

```text
                    # Legacy single-model path (analytic ports carry no
                    # proof and no analyses): the port's own values bind
                    # exactly as before — one model, no cross-model
                    # ambiguity to adjudicate.
```

line 1339:

```text
                    # Certified (or real federated) path: every hard
                    # constraint resolves to exactly one semantic
                    # source — verified proof or one evidencing
                    # analysis — never a guess across models.
```

line 1351:

```text
                # No measured values: every declared binding is
                # UNMEASURABLE (never a pass), with its required bound
                # still recorded so the refusal is auditable.
```

line 1371:

```text
            # Optimization-constraint authority (a DIFFERENT namespace
            # from the product RequirementReport above): pure tri-state
            # verdicts over this candidate's measured values.
```

line 1379:

```text
            # Every REQUESTED objective gets an explicit state. A missing,
            # non-finite or non-real value is UNMEASURABLE with its typed
            # reason; only MEASURED objectives may score or reach Pareto.
```

line 1438:

```text
            # Pareto input (authoritative): a CERTIFIED-BACKEND evaluation
            # succeeded AND the product-requirement leg is satisfied under
            # the question-aware applicability law (study-answerable
            # binding APPLICABLE or NOT_EVALUATED requirements demand a
            # bound, passing report; out-of-scope binding requirements
            # stay visibly unevaluated without poisoning measured
            # objectives; with no answerable requirements the leg is
            # vacuously satisfied — absence of a network leg never
            # invalidates a study on its own) AND the network-leg identity
            # holds where a network leg
            # executed (performance_result_id required there, never
            # fabricated elsewhere) AND every objective is measured from
            # authentic evidence (non-network objectives bind a carried
            # EVALUATED analysis with envelope, qualification and native
            # evidence id) AND every hard constraint is SATISFIED under
            # single-source resolution. Anything else is visible and
            # ineligible with a typed reason, never a fabricated score —
            # analytic/fake doubles can never masquerade as authority.
```

line 1532:

```text
                # A4: every network-question objective AND every
                # constraint metric must have a registered producer
                # over the derived claims — unless the federation
                # derived it (non-network objectives re-derive from
                # carried analyses above; constraint metrics under the
                # unambiguous-union rule). Registry silence plus
                # federation silence is UNMEASURABLE authority.
```

line 1591:

```text
        # Step 4: Pareto comparability over model fidelity. Candidates
        # whose provenance diverges (different unit/fidelity/
        # qualification for one objective axis, or a different question
        # than the definition) are demoted to ineligible with the exact
        # difference — never compared across models.
```

line 1635:

```text
            # C4: core mechanics NEVER mint certification. Classification
            # and registry identity are stamped by optimize_certified()
            # alone; every path through this core is ANALYTIC_RESEARCH.
```


# `optimization` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/optimization/candidate.py` :: `Candidate`

```text

    candidate_id is fixed at construction from (base hash, patch);
    execution order never changes it (the optimizer re-derives and
    asserts this).
```

## `tracks/t3-topology/dse/veritx_dse/optimization/candidate.py` :: `StudyCandidate`

```text

    candidate_id is fixed at construction from (base hash, patch);
    mapping_hash is a derived fact (deterministic of the request), not
    identity. A candidate carries no certificate, measurement, or Pareto
    status.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/capabilities.py` :: `ParamCapability`

```text

    FIVE SEPARATE FACTS, never collapsed (PHASE 2.1):

      expressible   the optimization schema accepts the parameter
      compilable    a patched design actually compiles
      effective     the parameter reaches the semantics being MEASURED —
                    changing it is not an identity-only change
      backend_executable  the certified profile accepts the probed result
                    (compile → lower → select_booksim_profile)
      qualified     VERITX may use it as a certified optimization dimension

    `accepted_values is None` means "the domain is a validated range, and the
    capability payload does NOT enumerate it". It must never be read as "all
    values are supported": `accepted_values_is_exhaustive` is False in that
    case so the Studio cannot make that mistake.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/capabilities.py` :: `_topology_family_truth`

```text

    Two separate stages, never collapsed:

      accepted_values    the canonical compiler ACCEPTS the family (a
                         concrete compile of a mesh-shaped request succeeds)
      executable_values  the full certified chain (compile → workload
                         lowering → `select_booksim_profile`) runs it —
                         what the product can actually evaluate

    gec and fat_tree are authorable enum members whose concrete compile is
    refused (the legacy spelling carries no mode/structure), so they are
    not accepted values. concentrated_mesh compiles but the certified
    profiles refuse it (mesh-DOR pins seat_capacity 1; AnyNet requires
    ANYNET_MIN_HOPS), and torus is refused at compile (no certified
    routing policy). Offering a value the evaluation path deterministically
    refuses manufactures doomed candidates.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/capabilities.py` :: `presentation_order`

```text

    `DomainParam` puts values in CANONICAL order — sorted by canonical JSON
    rendering — so declaration order never changes identity or enumeration.
    For numbers that is lexicographic on the string form, so

        [32, 64, 128]   ->   (128, 32, 64)

    which is correct and deterministic but reads badly.

    This function gives the UI a NUMERIC/logical display order instead, and
    it is deliberately NOT part of the definition: it must never be used to
    build a `DomainParam`, and importing it into the engine would be the bug
    it exists to prevent. A test pins that both orders yield the same
    definition identity and the same candidate enumeration.

    Sort key: numeric when every value is a real number; otherwise the
    canonical JSON key, so mixed/str domains keep a stable order.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/capability_probe.py` :: `_topology_family_backend_executability`

```text

    `_family_of` proves MATERIALIZATION. It does not prove that
    `select_booksim_profile` accepts the materialized fabric: concentrated
    mesh materializes and routes DOR_XY, and the certified profiles still
    refuse it (mesh-DOR pins seat_capacity 1; AnyNet requires
    ANYNET_MIN_HOPS).    Torus is refused even earlier — the certified mapping
    has no routing policy for it. This asks the real gate, once per family,
    so the capability payload cannot claim an execution that the product
    path refuses.

    Returns (truth, note) where truth maps family value →
    {"compiled": bool, "executable": bool}. `compiled` bounds
    accepted_values; `executable` bounds executable_values.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/completeness.py` :: `SearchCompleteness`

```text

    ``universe_known`` is the honesty switch: when the search method cannot
    bound its own space (a seeded random subsample), the universe size is
    NOT knowable and must not be fabricated.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/constraints.py` :: `evaluate_all`

```text

    Returns {"verdicts": {metric: doc}, "feasible": True/False/None}.
    None = not proven (some UNMEASURABLE, none VIOLATED).

    ``unresolved`` optionally forces UNMEASURABLE with a caller-supplied
    reason per metric (e.g. the optimizer's cross-model sourcing rule:
    a metric evidenced by zero — or several — semantic sources binds
    nothing, and the verdict must name the ambiguity rather than the
    generic missing-value text). Forced entries still record the
    required bound so the refusal stays auditable.

    Refuses duplicate metric constraints instead of silently letting the
    last verdict win: a verdict map keyed by metric has exactly one slot
    per metric, so a second constraint over the same metric is an
    ambiguity, not a second opinion.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/definition.py` :: `Objective`

```text

    ``question``/``backend_id`` are the objective's
    :class:`ObjectiveSource`: which federation question the metric is
    read from and which backend (if any) is required. The default
    (NETWORK_COMPLETION, None) is the legacy BookSim-only objective —
    bare ``Objective("completion_cycles", "MIN")`` constructions keep
    their meaning.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/definition.py` :: `ObjectiveSource`

```text

    An objective is never a bare metric name: it names the metric key,
    the closed-vocabulary :class:`EvaluationQuestion` it is read from,
    and an optional backend constraint (None = the federation planner
    adjudicates; a backend_id = the planned backend must be exactly
    that, else the objective is unmeasured — never silently
    substituted).

    ``question`` accepts an EvaluationQuestion or its canonical name
    (product transport arrives as a string); anything else refuses.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/definition.py` :: `OptimizationDefinition`

```text

    method: "grid"/"enumeration" (exhaustive Cartesian, canonical order)
        or "random" (bounded seeded subsample). "bayes"/"milp" refuse
        until deterministic correctness is established (see search.py).
    budget: {"max_candidates": int|None, "max_evaluations": int|None}.
        None = exhaustive. Truncation keeps the canonical prefix, never
        a sample (grid); random subsamples without replacement.
    seed: int|None. None = non-random methods only; "random" requires
        an explicit seed for determinism.
    selection: "min_first_objective" (default), "lexicographic", "none".
```

## `tracks/t3-topology/dse/veritx_dse/optimization/evaluators.py` :: `CandidateEvaluation`

```text

    Hash boundary: engine values are bare digests (design_hash is the
    bare CompileRequest identity); product views add any ``sha256:``
    prefix at the view boundary only (see result.to_study_view).

    ``requirement_report`` carries the real RequirementReport dict when
    the port produced one (compiled + backend-evaluated requests), so
    the optimizer can bind the report's identity instead of discarding
    it; None means no report exists (never an empty stand-in).
    ``requirement_report_id`` is that report's canonical
    ``report_identity`` (bare digest); the optimizer re-derives it from
    the carried report and refuses a mismatch, so a transplanted report
    can never masquerade as this candidate's provenance.

    ``evaluation_authority`` is the structural fidelity marker: a port
    must declare ``AUTHORITY_CERTIFIED_BACKEND`` for evaluations that
    went through the certified backend pipeline. Omitted/None means the
    evaluation is not authoritative and can never be Pareto-eligible.

    AUTHORITATIVE PROOF (A3/A4). For an EVALUATED, certified-backend
    evaluation the label is not enough: the evaluation must carry the
    authenticated backend proof object built by
    ``application.authenticated_evaluation.authenticate_backend_evaluation``
    and verified by ``verify_authenticated_backend_evaluation``.

    ``authenticated_proof`` is that proof (an
    ``AuthenticatedBackendEvaluation``): the dereferenced evidence
    reference/artifact, the network binding they authenticate, the
    producer identity, B's verified result and the canonical
    RequirementReport. The Optimizer imports Worker B's verifier
    authority and calls it — it never duck-types the proof — and
    authoritative metrics are extracted from the returned derived
    claims, never from ``objective_values``. ``workload`` and
    ``verified_performance_result`` are the legacy A3 carriers (kept
    for display/refusal context); the proof is the authority.

    ``objective_values`` remain the evaluation's own report of what it
    measured for ANALYTIC/TEST/RESEARCH ports; for certified Pareto
    they are ignored (except that a registered metric misreport
    refuses). A fake/development evaluator may still return analytic
    CandidateEvaluations, but it cannot produce certified Pareto
    science without the authenticated proof.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/evaluators.py` :: `FakeDeterministicEvaluator`

```text

    Deterministic: same candidate request -> bit-identical evaluation
    (recompiles LOCKED consequences every call; analytic objectives are
    a pure function of the request plus content-hash jitter).
    Non-COMPILED candidates yield status COMPILE_FAILED/UNSUPPORTED
    with no objective values (excluded from Pareto, never silent).

    Every outcome is marked ``AUTHORITY_ANALYTIC_FAKE``: the fake has no
    RequirementReport and no authenticated performance_result_id, so its
    candidates are structurally ineligible in authoritative studies.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/evaluators.py` :: `ObjectiveProvenance`

```text

    A float without provenance is not an optimizer objective: every
    value records the metric key, the question it was read from, the
    backend that produced it, the model fidelity, the qualification,
    the native evidence id, the unit and the value. Scalar objectives
    bind dimension-free envelope metrics only (per-rank / per-request
    rows never collapse into a scalar — no invented key suffixes).
```

## `tracks/t3-topology/dse/veritx_dse/optimization/metric_registry.py` :: `CertifiedMetricRegistry`

```text

    ``authorities`` is wrapped in a read-only mapping at construction; the
    dataclass is frozen and exposes no register/unregister method. The
    registry identity (``registry_id``) binds the version and the exact
    ``{metric, producer_id, semantics_version}`` set.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/metric_registry.py` :: `ExperimentalMetricRegistry`

```text

    Plugin experiments register/replace producers here; this object is
    structurally distinct from :class:`CertifiedMetricRegistry` and the
    certified extraction path refuses it, so it can never yield
    CERTIFIED_PRODUCT Pareto.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/metric_registry.py` :: `MetricAuthority`

```text

    ``producer_id`` names the qualified producer (what the value means);
    ``semantics_version`` versions that meaning. Both are bound into the
    registry identity, so a semantics change is a new registry version
    even when the metric name and version string are unchanged.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/metric_registry.py` :: `MetricRegistryBuilder`

```text

    Starts from ``base`` authorities when supplied (a qualified registry),
    refuses duplicate metric names within one build, and ``freeze()``
    returns an immutable :class:`CertifiedMetricRegistry`. The builder
    itself is never used while a study runs.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/real_evaluator.py` :: `RealCandidateEvaluator`

```text

    Storage layout: run_root/<candidate_id>/<eval-slot>/ holds one
    evaluation's federated evidence (plan.json,
    analyses/<question>/...). The candidate directory derives from
    candidate identity (stable transport, never scientific identity)
    and each evaluation gets a fresh OS-atomic slot via
    ``tempfile.mkdtemp()``, so the SAME evaluator instance can evaluate
    the SAME candidate repeatedly without overwriting a previous
    evaluation's evidence. No timestamp, PID or random token ever feeds
    a scientific identity: digests remain content-based.

    ``objectives`` (tuple of Objective) declares which questions must
    execute: the union of objective questions, each once. None means
    the legacy BookSim-only evaluation (NETWORK_COMPLETION through the
    certified leg). ``questions`` overrides explicitly. ``registry``
    injects the federation registry (tests script it; production builds
    the default registry from this port's binary/repo_root — the ASTRA
    binary resolves through the canonical resolver, Ramulator through
    its discovery authority).
```

## `tracks/t3-topology/dse/veritx_dse/optimization/result.py` :: `CandidateRecord`

```text

    Binds the reason the candidate won or lost: compilation and
    evaluation status, performance_result_id, the product
    RequirementReport identity and pass state (product_* fields), the
    optimizer's own constraint verdicts/details (constraint_* fields),
    the measured objectives (objective_* fields) and the locked
    consequences. Engine hashes stay bare; views prefix at the boundary.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/result.py` :: `CertifiedBackendConfig`

```text

    ``Optimizer.optimize_certified`` constructs ``RealCandidateEvaluator``
    from this config itself; no caller-supplied evaluator can enter the
    certified path. Quiescence is a certification obligation and is NOT a
    config knob: certified execution is always quiescent.

    ``binary`` is the BookSim binary (the network leg). ``astra_binary``
    and the Ramulator discovery options are None by default, in which
    case each backend resolves through its own canonical authority
    (ASTRA resolver / Ramulator discovery) — never a second matrix.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/result.py` :: `Optimizer`

```text

    TWO EXPLICIT MODES (R1). ``optimize_with_port`` is the
    ANALYTIC/TEST/RESEARCH entry point: an arbitrary
    ``CandidateEvaluationPort`` is structurally unable to reach certified
    eligibility there — any certified claim or authenticated proof is a
    typed refusal. ``optimize_certified`` is the ONLY certified entry
    point: it internally constructs and owns ``RealCandidateEvaluator``
    (compile -> qualified BookSim -> authenticated evidence), so the call
    path proves how the evidence was created. The persistence/replay/
    tamper verifier stays as-is for the certified path.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/result.py` :: `_enforce_federated_comparability`

```text

    Eligible only when, per objective: the question matches the
    definition, the backend satisfies the definition constraint, the
    native evidence exists, the qualification passes (present and
    identical across the eligible set — comparing a QUALIFIED number
    against a DIAGNOSTIC one silently would be a lie), the unit matches
    and the model fidelity matches. A divergent candidate is demoted
    to ineligible with the exact difference — never compared, never
    dropped silently. In particular a BookSim network completion and an
    ASTRA system makespan can never be one objective merely because
    both use cycles: different questions are different semantic
    families, structurally (each objective axis carries its question).
```

## `tracks/t3-topology/dse/veritx_dse/optimization/result.py` :: `_federated_objective_metrics`

```text

    Returns (measured, federated_keys). The certified discipline,
    extended to the federation: the evaluator's ``objective_values``
    never score. Network-question objectives come ONLY from the frozen
    certified registry over the verified claims
    (``_authoritative_metrics``); every other objective re-derives here
    from the carried federated analyses' normalized envelopes. A
    misreport refuses; a value the envelopes do not evidence is simply
    absent (the optimizer marks it UNMEASURABLE with the evaluator's
    exact miss reason when present).

    Constraint metrics (which carry no question) resolve under the
    unambiguous-union rule: exactly one EVALUATED analysis evidencing a
    scalar row binds it; zero — or several models evidencing the same
    key — leaves it unmeasured, never guessed across models.

    Per-value law: the analysis must be EVALUATED with an envelope, a
    backend, a qualification, a native evidence id and a
    dimension-free metric row; a definition backend constraint the plan
    did not satisfy is unmeasured, never substituted.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/result.py` :: `_study_answerable_binding_requirements`

```text

    Generalized objective-evidence binding (never performance_result_id
    == optimization authority): a binding requirement answers exactly
    one federation question's evidence. A study that asks no such
    question cannot satisfy the requirement — but the requirement must
    not poison objectives the study DID measure with authentic
    evidence. So the Pareto gate applies only to study-answerable
    binding requirements; out-of-scope ones stay visible as unevaluated
    (product_requirements_satisfied None, never True) without adding
    ineligibility reasons. Explicitly NOT_EVALUATED requirements poison
    every study until evaluated — an explicit mark wins over scoping.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/space_multiscenario.py` :: `BuildLedger`

```text

    valid holds EVERY valid candidate (canonical order); not_evaluated
    holds the canonical-prefix tail beyond budget (a subset of valid
    ids). Evaluation scheduling may only attempt eligible_ids();
    attempting a tail identity without re-budgeting refuses.
```


# `optimization` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/optimization/candidate.py` :: `apply_study_patch`

```text

    Fabric keys replace NocConfig fields, tp/pp/ep/dp replace workload
    fields (both via dataclasses.replace: the base is never mutated).
    The placement key carries a policy name only — mapping resolves
    through resolve_study_mapping. Empty patches and unknown/LOCKED/dead
    keys raise.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/capabilities.py` :: `_ProbeNoc`

```text

    `_family_of` reads only `topology_family`; constructing a real NocConfig
    is unnecessary and would drag in unrelated validation.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/capability_probe.py` :: `_ProbeNoc`

```text

    `_family_of` reads only `topology_family`; constructing a real NocConfig
    is unnecessary and would drag in unrelated validation.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/capability_probe.py` :: `_backend_executable`

```text

    This is the EXACT gate `ProductService._assess_compilation` applies
    before any evaluation: compile → lower the workload → build the
    logical/physical traffic artifacts → `select_booksim_profile`.
    `compiled` is the compile stage alone; `executable` requires every
    stage including profile selection. A parameter whose patched designs
    are refused here can compile in a study and then fail at evaluation;
    qualification must not advertise it.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/evaluators.py` :: `fake_objectives`

```text

    latency (cycles, MIN): falls with link_width and rcu, rises with
        concentration (contention proxy).
    area (cost units, MIN): rises with link_width, concentration, radix
        and rcu. The two trade off over link_width, so the grid Pareto
        is non-trivial.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/metric_registry.py` :: `federated_metric_catalog`

```text

    ``registry`` injects the federation registry (tests script it);
    None builds the default registry (registration only — no binary
    or readiness needed to enumerate declarations). Every row names
    the single source it was derived from; nothing here is restated
    by hand.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/metric_registry.py` :: `federated_semantic_family`

```text

    The network question reuses the certified family mapping (so
    completion_cycles/completion_time/completion_ns stay ONE semantic
    objective, never a manufactured trade-off). Every other question
    scopes the family to itself: a BookSim network completion and an
    ASTRA system makespan can never share an objective axis merely
    because both use cycles — different questions are different
    semantic families, structurally.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/real_evaluator.py` :: `_native_inconclusive`

```text

    Two shapes (explicit coupling): the first-class
    ``ANALYSIS_INCONCLUSIVE`` status the federated evaluator emits for
    a non-PASS/non-FAILED native verdict, and the legacy FAILED row
    whose reason carries the ``"native memory evidence {STATUS}"``
    shape. The INCONCLUSIVE token names the native verdict — never a
    crash, never a refusal.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/result.py` :: `_applicable_binding_requirements`

```text

    Applicable-binding requirements (binding=True and applicability
    APPLICABLE or NOT_EVALUATED) demand a bound, passing report —
    NOT_EVALUATED never passes until evaluated. Explicitly waived
    requirements (NOT_APPLICABLE) are ignored by the gate and
    returned for audit. A missing requirements field binds nothing.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/result.py` :: `_authoritative_metrics`

```text

    The verifier returns authenticated PRIMITIVES; optimization runs the
    FROZEN certified registry's producers over ``claims.verified_result``
    afterwards (evidence truth never depends upward on optimization).
    There is NO fallback to the evaluator's ``objective_values``: a
    registered metric the evaluator carried with a different (or
    non-finite) value refuses; a registered metric the claims do not
    evidence is UNMEASURABLE and the evaluator's number is ignored.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/result.py` :: `_check_report_binding`

```text

    The report is the PRODUCT-requirement authority: its design_hash and
    every entry's performance_result_id must name this candidate's
    evaluation, and its carried identity must equal the re-derived
    canonical identity. A transplanted report can never be bound to
    another candidate's measurements (the only alternatives would be
    silently changing result identity or accepting foreign provenance —
    both forbidden).
```

## `tracks/t3-topology/dse/veritx_dse/optimization/result.py` :: `_definition_view_v2`

```text

        Identity (`definition_id`), objective direction (MIN/MAX),
        objective evaluation policy (question + backend constraint),
        constraint operator and threshold, search method and selection
        policy are all explicit — a consumer never has to infer
        semantics from bare metric strings.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/result.py` :: `_federated_metric_sources`

```text

    {metric: [(question, value)]} over EVALUATED analyses carrying an
    envelope, a qualification and a native evidence id, dimension-free
    scalar rows only (first match per row, mirroring the objective
    re-derivation). Network-question rows are excluded: the network
    source is the verified proof (registry extraction), and merging it
    into this map would hide which model evidenced what.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/result.py` :: `_make_real_certified_evaluator`

```text

    ``optimize_certified`` calls THIS function, not a method, so ordinary
    subclass polymorphism cannot substitute a synthetic evaluator into
    the certified path. Quiescence is hard-coded True (C3): a certified
    result cannot be produced by a non-quiescent execution. The
    definition's objectives ride along so the port executes exactly the
    questions the study reads (plan once, one run per question); None
    means the legacy network-only evaluation.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/result.py` :: `_requirement_evidence_question`

```text

    RequirementV3 bounds (latency_ceiling_cycles, bandwidth_floor_gbps)
    are network-completion evidence: only an authenticated network
    PerformanceResult can satisfy them. A requirement declaring no bound
    answers no question (binding-without-bound is refused at
    construction, so this is unreachable for binding requirements —
    None here means unknown and therefore scoped to every study).
```

## `tracks/t3-topology/dse/veritx_dse/optimization/result.py` :: `_resolve_constraint_values`

```text

    Returns (resolved, unresolved_reasons). Candidates per metric: the
    verified-proof source (NETWORK_COMPLETION question, backend-measured
    registry values only — analytical model outputs never source a
    constraint) plus one candidate per evidencing non-network analysis.
    Exactly one candidate binds the metric; zero or several leave it
    unresolved with a typed reason — a constraint never guesses across
    models (the certified extension of the unambiguous-union rule).
```

## `tracks/t3-topology/dse/veritx_dse/optimization/result.py` :: `_to_study_view_v1`

```text

        Frozen boolean-only shape for pinned callers. UNMEASURABLE
        collapses to false (fail-closed: unmeasurable is never
        satisfied) and the v2 availability/product provenance fields are
        absent — these booleans do NOT preserve three-state semantics;
        callers that need the distinction must consume v2.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/result.py` :: `_to_study_view_v2`

```text

        Keeps the three authorities separate and lossless: product
        requirement identity/pass state, optimization constraint
        tri-state verdicts, and objective availability. ONE hash
        boundary (P1B rule): engine values are bare digests, product
        views are sha256:-prefixed, converted HERE only.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/result.py` :: `_verified_certified_claims`

```text

    The ``evaluation_authority`` label is descriptive, never proof. The
    optimizer imports and calls
    ``verify_authenticated_backend_evaluation(request, proof)`` — it does
    NOT duck-type the proof — and uses the returned derived claims as the
    authoritative facts. The port's carried RequirementReport must be the
    one the proof derives, and its performance_result_id must be the
    verified result's resource_id; anything else is a forgery and
    refuses hard.
```

## `tracks/t3-topology/dse/veritx_dse/optimization/result.py` :: `optimize_certified`

```text

        The optimizer constructs and owns ``RealCandidateEvaluator`` via
        the module-private factory; no caller-supplied evaluator is
        accepted, and the certified metric registry is NOT caller-
        selectable (product-controlled ``CERTIFIED_METRIC_REGISTRY``
        only). Only this path can produce ``CERTIFIED_PRODUCT`` results.
```
