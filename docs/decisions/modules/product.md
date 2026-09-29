# `product` — extracted module rationale

Extracted from the module docstrings of `veritx_dse/{name}` by the 2026-09-29 debloat. Code keeps a one-line pointer; this is the original long-form text.

## `tracks/t3-topology/dse/veritx_dse/product/__init__.py`

```text
veritx_dse.product — the VERITX Studio product resource layer.

Filesystem-backed Project / Draft / DesignRevision / Run / Job /
OptimizationStudy resources that link the canonical scientific views
(DesignView, CompilationView, EvaluationView, RequirementReport,
OptimizationStudyView) into one coherent product state machine.

No science lives here: every scientific fact is projected from an
application service. See ``docs/product/STUDIO-FLOW-AUDIT.md``.
```

## `tracks/t3-topology/dse/veritx_dse/product/jobs.py`

```text
veritx_dse.product.jobs — the smallest reliable local job mechanism.

No Redis, no Celery, no broker. A persistent job record on disk plus an
in-process worker pool. The state machine is explicit:

    QUEUED -> PREPARING -> RUNNING -> FINALIZING -> COMPLETED
                                                   REFUSED
                                                   FAILED
                                                   CANCELLED

Typed control-plane refusals map to REFUSED; an unexpected programmer
failure maps to FAILED and is logged — it is never reported as an invalid
user input. Jobs left non-terminal by a gateway restart are explicitly
marked FAILED("interrupted by gateway restart") on startup; they are never
left permanently RUNNING.
```

## `tracks/t3-topology/dse/veritx_dse/product/qualification.py`

```text
veritx_dse.product.qualification — one machine-readable authority.

The Studio and the gateway both read ``docs/production/ENGINE-QUALIFICATION.json``.
Neither parses the prose markdown at runtime, and neither carries a
hand-copied duplicate (the drift the audit flagged in
``gateway/qualification.py``).
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py`

```text
veritx_dse.product.service — the product state machine over canonical views.

One owner per concept:

    ProjectView      linkage only (no scientific fields)
    RevisionView     envelope around DesignView + CompilationView
    RunView          envelope around EvaluationView + RequirementReport
    JobView          linkage only
    OptimizationView envelope around OptimizationStudyView

The service parses product input, loads resources, invokes the canonical
application services and projects their views. It derives no route, counts
no packet, decides no Pareto membership and invents no qualification.
```

## `tracks/t3-topology/dse/veritx_dse/product/store.py`

```text
veritx_dse.product.store — filesystem-backed product resources.

One directory per project. All writes are atomic AND crash-durable (temp
file + fsync + rename + parent-directory fsync) and serialized by a
process lock plus an advisory inter-process ``flock``, so a crash cannot
leave a half-written resource and two gateway processes cannot allocate
the same revision id. No database is introduced: the durable form is JSON
on disk.

Durability note: the inter-process lock is advisory ``flock`` on
``<root>/.store.lock``. It is correct for a single shared filesystem; it
does not make the store a distributed database. The gateway is expected
to run one worker (the default) — the lock makes two workers safe, not
many-host deployments.

Layout::

    <root>/projects/<project_id>/
        project.json
        draft.json
        revisions/<revision_id>.json
        runs/<run_id>/run.json
        runs/<run_id>/bundle/...        (the durable RunBundle)
        jobs/<job_id>.json
        optimizations/<optimization_id>.json

The store owns identity generation and persistence only. It never derives
a scientific value.
```

## `tracks/t3-topology/dse/veritx_dse/product/validation.py`

```text
veritx_dse.product.validation — machine-readable validation authority.

Projects ``validation/reports/V*.json`` (machine-readable experiment
reports) into a stable ValidationCampaignView for the Trust page. The
Markdown campaign reports (MUTATIONS / METAMORPHIC / INTERVENTION /
ENGINES) and FINDINGS.md are referenced by link, never parsed: prose is
unstable and the program forbids building UI on unstable prose (§34).
Where a finding is referenced by a machine-readable check, its id is
surfaced as data; the narrative lives in the linked document.

Projection rules (§48): select fields, group checks, attach presentation
labels. Verdicts, independence classes and quarantine state are copied
verbatim from the reports — never recomputed, never upgraded.
```

## `tracks/t3-topology/dse/veritx_dse/product/vnext.py`

```text
veritx_dse.product.vnext — Studio vNext product surface.

New product methods for the vNext workbench (BUILD/ANALYZE/EXPLORE/TRUST):
synthesis problems, the global candidate library, candidate promotion,
the capability explorer, Wave-E/energy metric authorities, reuse display
data and search-completeness panels.

Authority discipline (no backdoors):

* Synthesis engines are candidate producers only. They emit typed
  ``TopologyCandidate``s through the existing adapters; screening uses
  the explicitly labelled analytical generator objective, and final
  evaluation goes through the canonical compiler + backend adapters
  after promotion. A candidate is never verified because an engine
  likes it.
* Promotion reuses ``promote_to_explicit_topology`` +
  ``apply_promotion_to_request_doc`` — no second promoted-design type —
  and writes an ordinary draft. An explicit Compile is required for the
  next revision.
* The UI derives no scientific status: every maturity/status claim is
  computed here from registry + archaeology authorities.
* No backend becomes an alternative compiler and no synthesis engine
  becomes an evaluator.

All functions take the live ``ProductService`` (``svc``) for store/jobs
and canonical helpers. Errors are typed ``ControlPlaneError``s raised
via ``intent_error``/``ProductServiceError`` so the gateway maps them
to REFUSED/FAILED exactly like existing surfaces.
```


# `product` — extracted inline comments

## `tracks/t3-topology/dse/veritx_dse/product/jobs.py`

line 31:

```text
#: A job function returns ``(job_state, result)``. ``job_state`` is one of
#: COMPLETED / REFUSED; ``result`` is a small linkage object (run_id /
#: optimization_id), never a scientific payload.
```

line 93:

```text
            # A core Refusal (semantic refusal, never approximated silently)
            # is NOT a ControlPlaneError. Without this branch it fell through
            # to the generic handler and was reported as INTERNAL_ERROR/FALSE
            # FAILED, telling the operator something broke when in fact no
            # science was attempted.
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py`

line 144:

```text
#: Trust-read byte caps for serving bundle documents as science: a
#: single evidence document larger than this is refused rather than
#: parsed (giant raw exposure is never a trust read).
```

line 167:

```text
    #: Ramulator discovery overrides (vendor tree / interpreter). None
    #: means the canonical discovery: the vendored tree under the repo
    #: root with the running interpreter's extension tag.
```

line 179:

```text
#: Computed identity fields are engine-owned. A client may round-trip
#: them, but they are dropped before parsing so a user edit never has to
#: recompute a hash the engine owns (mirrors derive_compile_request).
```

line 224:

```text
        # One product process = one registry configuration, bound here
        # from the service settings. Adapters are never constructed ad
        # hoc in service methods. (Tests may inject a scripted registry;
        # production always builds exactly this one.)
```

line 240:

```text
        #: simulation-capability assessment, keyed by design_hash. The
        #: assessment compiles the request once; the verdict is
        #: deterministic for a given tree, so the process caches it.
```

line 370:

```text
            # Backward-compatible derived boolean: representability
            # only, never readiness. A SUPPORTED design with an absent
            # backend stays True here while `evaluation_readiness`
            # carries the execution truth.
```

line 422:

```text
    #: Directories the canonical serve path reads its inputs from. The
    #: product layer only lists them; the canonical loader still validates
    #: every file's contents.
```

line 428:

```text
    #: CertifiedServiceProfile constructor kwargs a caller may override.
    #: ``model`` and ``schema_version`` are engine-owned and excluded: the
    #: service model comes from the cluster config, never from a request.
```

line 619:

```text
    #: Filename markers that name an experiment facet. Derived from the
    #: asset name only — never from model semantics the catalog cannot
    #: see. A config without a marker simply lacks that facet label.
```

line 852:

```text
                # A missing/unreadable active revision steps back; a
                # programming error propagates instead of silently
                # stepping back over a corrupt store.
```

line 896:

```text
        # PF-D13: the ambiguous global "latest run" is replaced by three
        # distinct facts. Each is scoped to the active revision where that
        # scoping is meaningful, so an older revision's work is never shown
        # as the current design's.
```

line 903:

```text
        # Simulation-capability verdict for the active revision: states the
        # real reason (compile / intent_lowering / backend_profile) without
        # recompiling, so the UI never offers a run that would refuse.
        # `supported` is a backward-compatible DERIVED boolean
        # (representability only) for Studio's design gate, which still
        # reads it; new readers use support/readiness.
```

line 1028:

```text
            # Provenance of an adopted optimization candidate. The design
            # identity above is what pins the design; this records WHERE the
            # draft came from.
```

line 1145:

```text
        # A candidate that never compiled cannot become a design: adopting it
        # would produce a draft that cannot be compiled, which reads as a
        # broken compiler rather than a rejected candidate.
```

line 1161:

```text
        # The BASE revision, not the draft: the candidate was measured
        # relative to the revision the study ran on, and applying it to
        # anything else would silently mean a different design.
```

line 1255:

```text
        # PHASE 7 LINKAGE. The revision records where its design came from,
        # so a study -> draft -> revision chain is traceable. The design
        # HASH is the identity; this is provenance and is excluded from it.
```

line 1261:

```text
        # Materialized graph captured at certification time: the shape
        # Studio draws is frozen with the revision, never re-derived later
        # (re-derivation would let the drawn graph drift from the proof).
```

line 1268:

```text
            # Staged-compilation law: a later stage refusal must not
            # invalidate already-derived earlier artifacts. A Torus design
            # derives a real TopologyArtifact (with wraparound channels)
            # and refuses only at ROUTING; that topology is canonical
            # science and is frozen with the revision so it survives a
            # reload. It is NOT a TopologyView of a completed compile —
            # it carries `staged: true` and its stopping stage.
```

line 1279:

```text
        # Canonical artifact DAG captured at certification time (§12/§14):
        # like the topology, it is frozen with the revision and never
        # re-derived for display without an identity check.
```

line 1285:

```text
        # Compile Result inspectors, materialized at certification time and
        # frozen with the revision (Gate 5 §97, Gate 8 §50). Re-deriving
        # them at view time would let a drawn graph drift from the proof.
        # Only a bundle-bearing compile gets a Compile Result payload. A
        # staged refusal is projected by `_staged_compile_result` from the
        # frozen staged topology, so persisting an empty "no compile
        # result" payload here would mask it.
```

line 1295:

```text
        # Simulation capability is assessed ONCE, from the certified
        # bundle, and frozen with the revision: the UI states the real
        # reason (lowering / backend profile / compile) without
        # recompiling, and a run can never be offered where the profile
        # would refuse.
```

line 1302:

```text
        # Candidate status flips (synthesis candidates only): a compiled
        # draft flips compiled (+revision link); a PASS certificate flips
        # verified. Auxiliary bookkeeping — a flip failure is recorded on
        # the revision, never allowed to fail a valid compile.
```

line 1364:

```text
        # A FROZEN payload is served verbatim, so a payload whose certificate
        # claim shape predates the current contract must NOT be served: the
        # frontend type says those fields are required and rendering would
        # throw. Treat it as absent and fall through to the re-derivation
        # path below, which re-checks the recorded hashes and raises
        # EVIDENCE_INVALID on mismatch — never a silently redrawn fabric.
```

line 1552:

```text
            # PHASE 7 provenance, when this revision came from a study. A
            # whitelist otherwise silently drops it, so the study -> draft ->
            # revision chain would be unobservable from the product surface.
```

line 1871:

```text
            # Any other TYPED control-plane failure keeps its own code:
            # re-labeling it UNSUPPORTED_SEMANTICS would launder the
            # real verdict.
```

line 1910:

```text
        # A run must execute certified semantics: refused attempts
        # (INVALID/UNSUPPORTED) and FAIL certificates can never be
        # evaluated, so the UI cannot accidentally run the latest attempt
        # when it is not the usable revision.
```

line 1932:

```text
            # The historical network-only gate, unchanged in shape: a
            # design the federation cannot represent never becomes a
            # job, and a network run still requires its configured
            # producer. Only representability refuses here: a
            # representable design whose producer is not qualified
            # still becomes a job, and the federated executor records
            # the BLOCKED analysis row with its reason (that is what
            # PARTIAL runs are for). Refusing at submit would second-
            # guess the planner and break the executor's ownership of
            # non-ready rows; preflight already tells the user the run
            # cannot execute.
```

line 2082:

```text
            # A workload the lowering cannot prove (MoE, diffusion, …)
            # is a typed refusal, never an internal error: the design
            # certified, but no run can honestly execute it.
```

line 2099:

```text
            # Seal every successful analysis even when the overall run
            # FAILED: a crashed sibling must never discard another
            # backend's authenticated evidence. Inconclusive native
            # evidence is sealed too (it executed; the verdict is what
            # is unknown). Pure refusals (nothing executed anywhere)
            # seal nothing and stay bundle-less, exactly as before.
```

line 2123:

```text
            # Carried from the canonical evaluator. FabricEvaluator only
            # reaches EVALUATED after a pinned producer, admitted evidence
            # and a reloaded/verified chain, so EVALUATED *is* the
            # certified outcome; the basis is recorded for auditability.
```

line 2157:

```text
            # The federated record: the adjudicated plan plus one entry
            # per requested question, each with its own backend, status,
            # native evidence id and normalized metrics.
```

line 2163:

```text
            # Explicit reuse linkage (Studio §41 REUSED banner): the
            # network leg carries the reused evidence id plus the
            # matched parents when it did not execute. Never synthetic.
```

line 2189:

```text
        # Candidate evaluated flip: a synthesis candidate whose revision
        # produced an EVALUATED network measurement flips evaluated.
        # Auxiliary — recorded on the run, never failing it.
```

line 2305:

```text
            # Per-analysis backends: a federated run's top-level backend
            # is the network leg, so family visibility must come from
            # the analyses themselves. Empty when the run has none.
```

line 2450:

```text
            # No sealed bundle, no served evidence: partial working
            # files from a failed or refused job are never presented as
            # bundle artifacts. Hidden files and checksum-temp files
            # (.checksums-*) are never bundle content.
```

line 2464:

```text
                    # checksums.json at any depth is bundle metadata of
                    # its own scope (the sealer excludes it by name), never
                    # a servable science document.
```

line 2554:

```text
        # Producer qualification is an environment fact, checked here so
        # the gate names it instead of the binary's mere presence: a
        # configured binary whose manifest is dirty or missing is
        # NOT_QUALIFIED, never QUALIFIED.
```

line 2584:

```text
        # Profile state is initialized BEFORE the gates consume it (the
        # historical UnboundLocalError): the profile named here is the
        # one the REAL selector derives for this revision's canonical
        # bundle. Support/readiness come from the federation planner
        # row — Compilation → context → plan — never from a second
        # hand-built BookSim lowering. The profile id is read off the
        # BookSim adapter's own canonical preparation (the generic
        # PreparedExecution.qualification_identity), so preflight
        # projects the same gate the evaluation path applies. A refusal
        # keeps the reason; it is never silenced by a plausible name.
```

line 2742:

```text
        # The authenticated attempt record — a wrapped {attempt, evidence}
        # document — is written by the backend into the bundle's `run/`
        # working directory; the raw evidence copy lives under `evidence/`.
        # Read the wrapped record (the schema this projection parses), with
        # a bundle-root fallback for older layouts. Trust reads go
        # through the sealed checksums: bytes that changed after
        # verification are refused, never projected.
```

line 2922:

```text
            # The federated path persists the bare scientific document
            # (never the wrapper: wrapper bytes mix run-varying attempt
            # metadata). Accept it when it carries an evidence identity
            # and native stats; anything else is corruption.
```

line 3217:

```text
            # Canonical labels: the reproduce authority compares the
            # deterministic science (stats + route-dump digest). Host and
            # wall-time metadata are not compared and must not be implied
            # to match.
```

line 3230:

```text
    #: Vendored, tracked serving authorities: a cluster config carries
    #: service semantics only (instances/model/TP/EP); the dataset is a
    #: real JSONL request trace. Both may be overridden per submission
    #: with a repo-relative or absolute path.
```

line 3345:

```text
        # The evidence document lives in the run dir; the serve path
        # writes serving-evidence.json (the CanonicalServingEvidence
        # canonical bytes). Load it and carry it verbatim.
```

line 3354:

```text
        # The normalized TTFT/completion view the serve path persists
        # beside the native evidence (analyses, or an explicit absence
        # record). Native evidence is never removed or replaced.
```

line 3392:

```text
        # The BookSim producer is required only when the study asks a
        # network question: an ASTRA-only or Ramulator-only study must
        # not demand a BookSim binary. Every other question relies on
        # planner adjudication at execution time.
```

line 3406:

```text
    #: Fields the product API accepts for an optimization study. An unknown
    #: key is REFUSED, never dropped: a silently ignored option is a lie about
    #: what the study did.
```

line 3414:

```text
    #: Fields the product API accepts per optimization objective. An
    #: unknown key is REFUSED, never dropped. question names the
    #: federation question the metric is read from (default
    #: NETWORK_COMPLETION = the legacy BookSim-only objective);
    #: backend_id constrains the producing backend (None = the planner
    #: adjudicates; a mismatch is unmeasured, never substituted).
```

line 3554:

```text
                # PHASE 1: budget/seed/selection were accepted by the product
                # API and then dropped here, so a caller asking for a bounded
                # seeded random study silently got the default policy.
```

line 3599:

```text
                # A candidate execution is its own resource unless it was
                # independently registered as a Product Run. It is NOT a
                # verified RunBundle by default.
```

line 3613:

```text
            # THE REQUESTED DEFINITION, as normalized. Persisted so a study is
            # auditable against what was ASKED for, not only against what the
            # engine recorded. PHASE 1: this was previously not stored at all,
            # so `method`/`selection`/`seed`/`budget` were unverifiable after
            # the fact.
```

line 3675:

```text
            # Same closed vocabulary as the federated rows: scenario
            # mismatch is NOT_COMPARABLE, an unmeasured side is
            # MISSING_MEASUREMENT. Same key is not enough.
```

line 3771:

```text
                # Name the model difference explicitly when the same
                # metric key IS measured on the other side under a
                # different question: same key, different semantic
                # family — MODEL DIFFERENCE, never comparable.
```

line 3972:

```text
            # The draft still equals a refused attempt: recompiling would
            # reproduce the refusal, so the next action is fixing the
            # design, not compiling again.
```

## `tracks/t3-topology/dse/veritx_dse/product/store.py`

line 487:

```text
    # ── syntheses (vnext: topology-synthesis product records) ─────────
    #
    # One synthesis record per submitted synthesis problem. The record
    # carries the problem (definition + traffic), the generated
    # candidate, its generator objective (never a measurement) and the
    # search-completeness accounting. A candidate is never verified
    # because an engine likes it: verification happens after promotion
    # through the ordinary compile path.
```

line 539:

```text
    # ── candidates (vnext: global candidate library) ──────────────────
    #
    # The library is global (not per-project) so candidates from any
    # study or synthesis can be compared and adopted in one place.
    # Each record is linkage: the candidate graph, its origin
    # (synthesis or optimization study), generator provenance, and
    # adoption state. Scientific status (compiled / verified /
    # evaluated) is recorded from the ordinary pipeline, never derived
    # by the UI.
```

## `tracks/t3-topology/dse/veritx_dse/product/validation.py`

line 19:

```text
#: Machine-readable campaign ledgers beyond the V-experiments. Each is a
#: stable JSON document projected verbatim (selected fields); their
#: narrative context remains in the linked prose documents.
```

line 178:

```text
        # Machine-readable campaign ledgers, projected verbatim (selected
        # fields). Prose campaigns are listed so Trust can link them; their
        # contents are intentionally absent from this view.
```

## `tracks/t3-topology/dse/veritx_dse/product/vnext.py`

line 11:

```text
#: Synthesis engines the product may run, with the adapter authority and
#: the honesty facts Studio must render beside each method. Completeness
#: is method-level: heuristic graph search explores an unbounded/implicit
#: space (UNBOUNDED — "best observed among evaluated candidates"); BO
#: explores the declared 5-D generator space under a candidate budget
#: (BUDGETED). No engine may claim global topology optimality.
```

line 144:

```text
    # Adapter-level failure (disconnected search, no connected proposal)
    # is a feasible-design refusal, never a programmer FAILED: the
    # search ran honestly and found nothing worth recording.
```


# `product` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `_staged_compile_result`

```text

        The vocabulary distinguishes what happened:

          * upstream derivation valid, downstream contract unavailable
            -> the stages that DID derive are inspectable and the stopping
               stage is named with the capability reason;
          * the upstream artifact itself could not be built -> nothing is
               inspectable, because there is nothing valid to show.

        Empty downstream panels are never presented as successful.
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `run_integrity`

```text

        A pure projection over the authenticated evidence document inside
        the VERIFIED run bundle. Selects and groups existing counters;
        it computes no science. A counter the backend did not emit is
        reported as NOT AVAILABLE, never zero-filled (§18/§59).

        Federated runs report per-analysis integrity: the BookSim packet
        tables only for the NETWORK_COMPLETION analysis (never for
        ASTRA/Ramulator evidence), and each ASTRA analysis reports its
        own factual fields (tier, injection, namespace).
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `use_candidate`

```text

        The loop the whole product flow exists for:

            OptimizationStudy -> selected candidate -> "Use candidate"
              -> Draft updated -> user reviews -> explicit Compile
              -> NEW immutable DesignRevision

        What this does NOT do is turn r05 into r06 behind the user's back.
        The BASE revision is read-only here; only the draft is written. A
        later explicit `compile_draft` allocates the next revision from it,
        which is what makes the new revision immutable and the old one
        unchanged.

        The patch is re-applied to the BASE REVISION's request through the
        canonical `apply_patch`, and the resulting design hash is required to
        equal the candidate's. That equality is the proof that this draft is
        the SAME DESIGN the study measured — not a re-derivation that might
        have drifted.
```


# `product` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `_assess_compilation`

```text

        Representability and readiness are distinct verdicts, never one
        boolean: `support` names whether the federation can represent
        this exact fabric/workload (SUPPORTED / CONDITIONAL /
        UNSUPPORTED); `readiness` names whether it can execute right
        now (READY / BLOCKED / UNAVAILABLE). Derived from the
        federation planner, never from a second hand-built BookSim
        projection: the canonical context is built once and the
        NETWORK_COMPLETION plan row adjudicates representability.
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `_check_compilation_parity`

```text

        A Run must execute exactly the immutable compilation the revision
        records — not a re-derived one. Recompiling the stored request and
        demanding exact identity over every recorded artifact hash turns
        compiler drift (or a mutated request) into a refused job instead
        of a silently re-derived execution. Returns the recompiled
        Compilation the run executes (hash-matched to the stored one).
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `_check_run_report_binding`

```text

        The report is the product-requirement authority: its design_hash
        and every entry's performance_result_id must name this
        revision's network evaluation. A stale or transplanted report
        persisted beside the displayed revision is refused instead of
        stored. Reuses the optimizer's binding law; the failure is
        projected as a product EVIDENCE_INVALID.
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `_downgrade_unverified_trust`

```text

        A run record claiming evaluated trust (EVALUATED/PARTIAL status
        or any qualification) without a bundle_id serves UNVERIFIED
        verdicts instead: refused or legacy runs legitimately lack
        bundles, but no caller may read QUALIFIED science from a record
        with no sealed evidence. Pure refusals (no trust claimed) pass
        through untouched.
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `_ensure_revision_pointers`

```text

        Projects persisted before the split carry only
        ``active_revision_id``: the latest revision id becomes the latest
        attempt, and a non-promotable active revision steps back to the
        newest promotable one (or None) so a refused attempt can never
        masquerade as the certified fabric. Persists only when a pointer
        actually changes.
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `_parse_definition`

```text

        EVERY option accepted here reaches `OptimizationDefinition`. Nothing
        is accepted and then dropped: earlier, `selection`, `seed` and the
        whole budget were parsed and never propagated, so the study silently
        ran the default policy whatever the caller asked for.

        Normalization (not dropping): an ABSENT `selection` resolves to the
        backend default, and an absent `budget` resolves to `{}`. Both are
        the values `OptimizationDefinition` would have chosen itself.
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `_read_trust_file`

```text

        Every trust read (evidence documents consumed as science)
        goes through the bundle's sealed checksums: the file is
        re-hashed at read time and compared against the digest recorded
        at finalization, closing the verify-to-read gap where bytes could
        change between verification and consumption. A mismatch, an
        unsealed name, a symlink or a missing file raises
        EVIDENCE_INVALID — trust reads never fall back to raw bytes.
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `_require_evaluable_request`

```text

        A schema_version 2 request still compiles (frozen legacy
        interpretation, certified history preserved), but the lowering
        only speaks v3/v4 — so no evaluation, optimization or plan can
        honestly run against it. Refusing here with the remedy beats
        the raw lowering error the context builder would raise below.
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `_run_federated_evaluation`

```text

        Compatibility: the NETWORK_COMPLETION analysis keeps the exact
        historical record shape (evaluation, requirements, producer,
        evidence, qualification) so old readers and the requirement
        report keep working; per-analysis records ride alongside it.
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `_stored_compile_result`

```text

        Internal: the route walk needs the table the served response
        withholds. Read from the payload frozen at certification time. A
        revision persisted before this projection existed re-derives it
        from its own immutable request and is checked against the hashes
        the certificate already recorded — a mismatch is an
        EVIDENCE_INVALID, never a silently redrawn fabric. A revision that
        never compiled has no inspectors: a failed proof is not a fabric.
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `_verify_run_bundle`

```text

        A finalized bundle is the evidence authority: every read of a run,
        its evidence or its artifacts recomputes the content identity and
        refuses when the bundle is missing, tampered, or no longer matches
        the run record. Returns the verification summary, or None when the
        run has no bundle (e.g. a refused evaluation).
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `canonical_route`

```text

        Walks the route table frozen with the revision at certification
        time (Gate 8 §58). The routing class defaults to the first declared
        class — the canonical default — and src/dst default to the first
        attached router pair, so the inspector always has something real to
        show without the caller guessing.
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `compile_draft`

```text

        ``expected_draft_design_hash`` is the reviewed snapshot (Gate 7 §4,
        REV-D2). When supplied and it no longer matches the current canonical
        draft, compilation is refused as ``STALE_REVIEW`` — the reviewed
        content is never silently replaced by unseen content, and Review is
        never silently regenerated.
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `federation_backends`

```text

        Registration comes from the registry (each adapter's declared
        capabilities: question/support/fidelity/limitations). Runtime
        availability is an install fact per backend (binary/extension
        present), never a readiness verdict — readiness requires
        adjudicating a real canonical context, which this view never
        does. No simulation ever runs here.
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `get_revision_compile_result`

```text

        The routing group carries the routing classes, the entry count and
        the channel hops, but not the entry rows. A 16x16 mesh has 65,280
        entries (~4.8 MB); the frontend never needs them, because the
        canonical route is a query (`GET /revisions/{id}/route`) walked
        server-side over the frozen table. Shipping them would make the
        inspector unusable at exactly the sizes where it matters.
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `revision_diff`

```text

        Pure projection over stored payloads: the default basis is the
        predecessor in the project's revision order, and an explicit
        `against` must belong to the same project. Preflight readiness
        is deliberately excluded from the comparison — it depends on
        the live backend binary in this environment, so diffing it
        would report environment drift as a design change.
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `revision_preflight`

```text

        Pure projection: reads the stored revision, the active draft
        state and the configured backend and reports each gate with its
        exact reason. It decides nothing the evaluator would not decide
        again at spawn; it exists so the Run button is never the user's
        first indication of a missing gate (§15).
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `serving_experiment_catalog`

```text

        Every entry names on-disk assets only (config + trace sources
        with content digests). Facet labels are derived from geometry
        and asset names, never invented. Model configs without any
        cluster file (today Mixtral/Phi-mini) are reported as explicit
        gaps, never listed as runnable.
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `submit_reproduction`

```text

        Legacy runs reproduce through
        ``backend.reproduce.reproduce_booksim_run_bundle``. Federated runs
        dispatch per analysis backend (BookSim: the same authority over
        the analysis run subdir; ASTRA: rerun of the exact stored
        machine/projection/namespace inputs). A backend whose
        reproduction cannot run here reports REPRODUCTION_NOT_AVAILABLE
        for its analyses — never a generic Reproduce button that only
        reproduces BookSim.
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `submit_serving`

```text

        The job wraps ``serve_canonical.run_canonical_serve`` — the
        qualified live path (cluster service semantics -> canonical
        compiler -> ASTRA/BookSim -> CanonicalServingEvidence). No serving
        semantics live in the product layer; refusal reasons come from
        the canonical path's own typed errors.
```

## `tracks/t3-topology/dse/veritx_dse/product/service.py` :: `workload_lowering`

```text

        The workload template documents are immutable repo content, so the
        lowering is deterministic; the view carries the artifact's own
        content-hash identity so a consumer can verify it independently.
```

## `tracks/t3-topology/dse/veritx_dse/product/store.py` :: `create_revision`

```text

        Every attempt becomes ``latest_attempt_revision_id`` — including a
        refused one, which must stay visible. Only a caller-verified
        usable revision (COMPILED + certificate PASS) passes
        ``promote=True`` and displaces ``active_revision_id``. The store
        never decides promotability itself; it only persists the caller's
        verdict.
```

## `tracks/t3-topology/dse/veritx_dse/product/vnext.py` :: `_capability_status`

```text

    AVAILABLE: product-wired and qualified. EXPERIMENTAL: product-wired
    without full qualification. HISTORICAL: only historical execution/
    measurement exists. RESEARCH: a current implementation exists but
    the canonical/product bridge is incomplete. BLOCKED: every dynamic
    stage refuses. NOT APPLICABLE: the stages do not apply.
```

## `tracks/t3-topology/dse/veritx_dse/product/vnext.py` :: `mark_candidate_compiled`

```text

    Called by compile_draft when the promoted draft compiles. Only
    synthesis candidates carry these flags (optimization candidates live
    in studies); anything else is a typed refusal. Never synthesizes
    status: compiled requires a real COMPILED compilation, verified a
    real PASS certificate.
```
