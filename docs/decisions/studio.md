

# Studio (TypeScript) — extracted file-header rationale

## `src/components/ImplementationLab/capabilityLedger.ts`

```text
/**
 * Capability ledger — the Studio-side mirror of
 * `docs/product/capability-archaeology.yaml` (evidence-archaeology-v1,
 * 28 audited records) plus the core product systems that are not
 * archaeology rows.
 *
 * This file is DOCUMENTATION STATE, not authority: every cell condenses
 * the yaml record (source paths, classifications, measured evidence with
 * source commits, missing bridges). When the ledger is re-audited, this
 * mirror must be re-mirrored — it never overrides the yaml, the
 * capability registry, or backend verdicts. Cells that the yaml marks
 * NOT PROVEN stay NOT PROVEN here.
 */
```

## `src/components/Synthesis/methods.ts`

```text
// Synthesis METHOD catalog (§22). Honest claims per method — what each
// method may claim about its own search, never about product truth.
// A generator score is a proposal input, not measured performance; a
// candidate is never verified because a generator likes it.
//
// Route paths (for the nav lane — this lane wires nothing outside its
// owned files):
//   /projects/:pid/synthesize
//   /projects/:pid/candidates
//   /projects/:pid/candidates/:candidateId
```

## `src/components/Synthesis/store.ts`

```text
// Local synthesis study drafts + imported candidate graphs.
// Explicitly LOCAL: these never touch backend truth. A study draft is an
// authoring aid (problem definition + CLI command + imported graphs); a
// candidate graph becomes science only after promotion → compile →
// qualified execution through the canonical pipeline. localStorage only.
```

## `src/fabricLayout.ts`

```text
// Fabric geometry for both canvases. Two sources are never mixed:
//
//   'topology' — the materialized TopologyArtifact + attachments the
//                revision was certified against. Drawn as it is.
//   'intent'   — declared DesignView counts only: a PREVIEW until a
//                compile materializes the graph (router count, agent
//                seats and attachment positions are then unknown).
//
// The canvases render whichever model they are handed and FabricView
// labels the source on screen, so a preview can never impersonate a
// materialized fabric.
```

## `src/landing/motion.ts`

```text
// Landing page motion. Anime.js drives three quiet things only: the hero
// entrance, a few pixels of pointer parallax on the board, and the
// caption/index reveal. Nothing here is decorative fiction — the board is
// a rendered photograph and stays a photograph; motion never implies
// traffic that is not in the image.
```

## `src/components/CandidateDetail.tsx`

```text
// Candidate detail page (§25). One page per parameter-search or
// topology-synthesis candidate: design delta, topology graph, routing /
// VC resources, compile result, verification, backend analyses,
// requirements, constraints, evidence, generator provenance — then the
// three actions: Evaluate candidate, Compare to base, Promote to draft.
//
// Promotion uses the existing safe candidate→explicit-topology path:
// for optimization-study candidates that is api.useCandidate, for gateway
// synthesis candidates POST /candidates/{id}/promote (draft only — Compile
// creates the immutable revision). Local imports carry no gateway record:
// the page states that explicitly and offers the submit/import path instead
// of inventing a promotion.
```

## `src/components/CompareView.tsx`

```text
/**
 * CompareView — §27 cross-comparison workbench.
 *
 * Modes: Run↔Run · Revision↔Revision · Candidate↔Candidate ·
 * Candidate↔Revision. Every mode resolves to a pair of evaluated runs and
 * calls the single backend contract `GET /compare` — React compares
 * nothing itself.
 *
 * Tabs: Design · Structure · Performance (compatible metrics only) ·
 * Requirements · Verification · Evidence. Incompatible pairs render an
 * explicit MODEL DIFFERENCE banner with the server's reasons; no fake
 * deltas are emitted.
 */
```

## `src/components/RunDetail.tsx`

```text
/**
 * RunDetailView — §29 run detail.
 *
 * WIRING NOTE (minimal export): `pages/index.tsx` currently owns the
 * `RunDetail` page (same name, different file). To adopt this view,
 * render `<RunDetailView runId={runId} />` from that page — or rename on
 * import. No route changes needed.
 *
 * Fixes the "producer revision = backend name" display mistake: the
 * producer block shows the executing backend, the verbatim producer
 * identity, and the config/input hashes as three separate facts.
 * Header names question → backend → revision; the headline value is an
 * explicit SIMULATED ScientificValue, never a naked number.
 */
```

## `src/components/RunsView.tsx`

```text
/**
 * RunsView — §28 run library.
 *
 * WIRING NOTE (minimal export): `pages/index.tsx` currently owns the
 * `Runs` page. To adopt this view, replace that page body with
 * `<RunsView />` (same route, no new page needed) — or keep both while
 * migrating. This file is intentionally self-contained apart from shared
 * `studio`/`badges`/`ScientificValue` primitives.
 *
 * Each line carries question-relevant identity: revision, workload,
 * backend, status, qualification, simulated value, fidelity-relevant
 * timestamps and reproduction-input availability. Two honest gaps are
 * marked in code, not papered over:
 * - `RunSummary` carries no per-run question tag, so there is no
 *   question filter (filtering by backend is not the same fact).
 * - `RunSummary` carries no reproduction outcome, so there is no
 *   reproduced/not-reproduced filter (bundle presence means archived
 *   inputs exist, not that reproduction succeeded).
 */
```

## `src/components/ScenarioStack.tsx`

```text
// Study-scenario composition for the Design page.
//
// Three explicit layers, never mixed:
//
//   01 DESIGN INTENT ......... EDITABLE — authored here, owned by the draft.
//   02 INTERPRETATION ........ What the intent means for analysis. PROFILE
//                              readings (descriptive, no compiler effect) and
//                              placement/count consequences. Gaps render as
//                              gaps, with the missing authority named.
//   03 DERIVED IMPLEMENTATION  DERIVED — compiler output from the active
//                              revision. Never authored here.
//
// Sources are ALREADY-WIRED product data only: the draft document, the
// workload catalog, the serving experiment catalog, the compile result,
// the evaluation plan, the capability explorer and the energy
// authorities. What this does NOT do: author SystemIntentV4 (no gateway
// path exists), bind hardware profiles server-side (no such endpoint —
// the profile below is browser-local descriptive metadata), or display
// profiler coverage (not exposed).
```

## `src/components/Synthesis/TopologyGraph.tsx`

```text
// Topology graph visualization: base vs generated candidate.
// Added links (candidate-only), removed links (base-only, dashed),
// kept links. Routers as grid-positioned nodes; degree shown beside
// high-degree routers. Pure rendering of explicit link lists — React
// infers no routing, no performance, no qualification here.
```

## `src/pages/candidates.tsx`

```text
// Candidates page (§26): the global candidate library. Filters by
// study, generation method, compiled, verified, evaluated, eligible,
// Pareto, adopted. Sources, in order of authority:
//   1. live gateway candidate library (api.candidates) where wired —
//      adopted/status flips read straight from these gateway records;
//   2. optimization-study candidates from the project record;
//   3. local synthesis imports (explicitly local, never backend truth).
// Cards show origin, design delta, network/system/memory results,
// verification and status. Selecting one opens CandidateDetail (§25).
```

## `src/pages/evaluate.tsx`

```text
// Evaluate — answer engineering questions about the current design.
//
// One dominant cognitive task at a time, in the Synthesize grammar:
//
//   choose engineering question → see what is runnable → execute →
//   understand the answer.
//
// The server adjudicates everything (plan readiness, backends,
// metrics, qualification). Studio projects that truth into
// question-first UI and derives nothing scientific: headlines are
// looked up by canonical metric key with a first-metric fallback,
// never synthesized.
```

## `src/pages/synthesize.tsx`

```text
// Synthesize page: topology synthesis as a decision workflow.
//
//   Workload → Constraints → Search → Measured candidates → Adopt
//
// The primary surface is one path: the current workload supplies the
// traffic, three constraints bound the search, one method runs through
// the gateway job route, and the resulting candidate lands in the
// candidate library for compile → verify → evaluate.
//
// What this page NEVER does: offer a control that does not affect the
// live synthesis request, invent a generator score, or call a candidate
// measured/verified. Solver vocabulary, CLI reproduction, raw matrices
// and hashes live behind Advanced / Technical details.
```

## `src/studio.tsx`

```text
// Studio shell primitives: mode detection, active-project state, async/job
// hooks and the persistent context header. React renders the gateway's
// explicit flow state; it never infers a stage from a missing field.
//
// The linear 01…05 WorkflowBar was removed (STUDIO-WIREFRAMES.md §144/§181):
// navigation follows the scientific object lifecycle (Design · Evaluate ·
// Serve · Optimize · History · Capability), not one global pipeline.
```
