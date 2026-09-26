# SROTA Studio — implementation handoff

## Product rule

Studio is a **contract-first engineering console** over SROTA/VERITX. It must not reimplement compiler, verification, backend, optimizer, or serving semantics in React.

The frontend owns:
- navigation and user flow;
- local draft state before compilation;
- rendering frozen product views;
- choosing user-requested actions;
- presenting explicit engine states;
- visualization from authoritative payloads.

The backend owns:
- design identity and canonicalization;
- placement, mapping, topology materialization, attachment, routing, resolved routing, VC assignment, packet semantics;
- verification obligations and certificates;
- logical-message and physical-traffic lowering;
- backend qualification and producer identity;
- evidence integrity and conservation checks;
- requirement verdicts;
- optimization eligibility/Pareto/selection;
- serving scheduling semantics in LLMServingSim;
- rank-to-endpoint binding and network evidence;
- validation-backend scope.

## Current remote Studio surface reviewed

The visible `audit/rt-final-studio-contract-v2` branch already contains:

- `DesignEditor.tsx`
- `FabricCanvas.tsx`
- `VerifyView.tsx`
- `EvaluateView.tsx`
- `OptimizeView.tsx`
- contract-mirror `types.ts`
- v2 optimization contract with separate requirement, constraint and objective authorities.

Retain those semantics. The main restructuring is the product shell and workflow.

## Recommended information architecture

```
00 Overview
01 Intent
02 Compile
03 Verify
04 Evaluate
05 Optimize
06 Serving
07 Evidence
08 Compare
09 Validation Lab
```

Do not collapse these into generic tabs.

### 00 Overview
Answer: "What can I do with this revision?"

Primary jobs:
- Evaluate a product design
- Explore design space
- Run request-driven LLM serving
- Audit/reproduce a result

Show the canonical pipeline and current revision status.

### 01 Intent
Use the existing E1–E5 concepts.

Editable:
- workload/model family
- serving mode
- TP/PP/EP/DP
- requirements
- agent inventory
- topology family
- radix/concentration/link width
- supported arbitration knobs

Compiler-owned:
- routes
- route realization
- VC mapping
- escape VC semantics
- turn restrictions
- packet format
- certificates

If a user edits anything affecting compilation, mark the revision dirty and invalidate downstream UI until a new backend compile returns.

### 02 Compile
Show the linked artifact graph, not a BookSim config.

Minimum artifact identities to expose:
- CompileRequest
- placement/mapping
- TopologyArtifact
- AgentAttachmentArtifact
- RouteArtifact / ResolvedRoute
- VCAssignment
- FabricArtifact

Do not derive counts or hashes independently if the backend already supplies them.

### 03 Verify
Render each verification obligation from the certificate.

No generic green "verified" state without the obligation table.

At minimum support:
- topology connectivity
- attachment completeness
- address decode
- route completeness
- route legality
- VC assignment validity
- channel-VC CDG/deadlock verdict
- mapping
- packet format
- artifact-DAG/identity gate

A failed parent gate must visually block downstream actions that depend on it.

### 04 Evaluate
Flow:

```
declared workload
→ logical messages
→ physical traffic
→ qualified backend
→ scientific evidence
→ performance result
→ requirement report
```

Rules:
- absent metric != 0;
- BACKEND_UNAVAILABLE has no metrics;
- UNSUPPORTED has no fake fallback;
- requirement verdicts come only from RequirementReport;
- first-hop route realization must be labelled "first-hop", not "full route verified".

### 05 Optimize
Keep these as three independent authorities:

1. Product requirements
2. Optimization constraints
3. Measured objective availability/value

Use `OptimizationStudyView v2` directly.

A candidate is Pareto-eligible only if the backend says so. The UI must not recompute eligibility from displayed fields except for local explanatory presentation.

Plot only explicitly measured objectives. UNMEASURABLE candidates are excluded from measured-objective plots and remain visible in the candidate table.

### 06 Serving
This is a separate product workflow, not a toggle inside static evaluation.

Ownership:

```
LLMServingSim:
  arrivals
  queues
  scheduling
  batching
  prefill/decode
  instances
  request metrics

SROTA:
  physical fabric
  rank → endpoint binding
  topology/routing/VC
  network execution
  evidence
```

Keep these namespaces explicit:
`serving instance != rank != endpoint != BookSim node != router`.

Expose TP/DP/EP parameters and request traces.

For canonical MoE serving, show the implemented semantics as returned by the serving backend, e.g. dispatch → expert compute → combine. Do not translate a static Studio `EP ALLTOALL` declaration into serving semantics in the browser.

### 07 Evidence
Make `RunBundle` a first-class inspector.

Show:
- design hash
- revision identity
- fabric hash
- workload/traffic identities
- backend producer identity
- config/input hash
- raw evidence digest
- stats digest
- performance result ID
- requirement report ID
- route-observation scope
- reproducibility status
- tamper/identity failures

Known requirement: non-semantic runtime fields must not make scientific identities unstable.

### 08 Compare
Run a compatibility gate before rendering deltas.

Check backend-provided compatibility for:
- workload identity
- compiler semantics
- metric registry/version
- producer/authority class
- comparable measurement windows
- intended changed knobs

Do not compare incompatible results as if they were apples-to-apples.

### 09 Validation Lab
This page is for bounded independent evidence.

Represent scope honestly:

| Backend | Primary role | UI wording |
| --- | --- | --- |
| BookSim | canonical network execution | qualified backend |
| ASTRA-Sim | distributed-system projection | integrated execution path, not hardware truth |
| Ramulator | memory analysis | bounded memory authority |
| RTL | independent correspondence | qualified validation cases only |

Never turn "backend executes" into "accurate hardware latency prediction".

## Gateway adapter

Do not let components fetch arbitrary endpoints directly. Add one typed adapter, for example:

```ts
interface StudioGateway {
  loadRevision(projectId: string, revisionId: string): Promise<RevisionView>;
  compile(request: CompileIntent): Promise<CompilationView>;
  getCertificate(compilationId: string): Promise<CompilationView>;
  evaluate(req: EvaluationRequest): Promise<{
    evaluation: EvaluationView;
    requirements: RequirementReport | null;
  }>;
  optimize(req: OptimizationRequest): Promise<OptimizationStudyView>;
  runServing(req: ServingExperimentRequest): Promise<ServingRunView>;
  getRunBundle(runId: string): Promise<RunBundleView>;
  compare(runIds: string[]): Promise<ComparisonView>;
  getValidation(subjectId: string): Promise<ValidationView>;
}
```

The method names are frontend adapter names. They do **not** require the server to use matching HTTP paths.

## Suggested React structure

```
apps/studio/src/
  app/
    AppShell.tsx
    Router.tsx
    ProjectContext.tsx
  gateway/
    StudioGateway.ts
    HttpStudioGateway.ts
    FixtureStudioGateway.ts
  pages/
    OverviewPage.tsx
    IntentPage.tsx
    CompilePage.tsx
    VerifyPage.tsx
    EvaluatePage.tsx
    OptimizePage.tsx
    ServingPage.tsx
    EvidencePage.tsx
    ComparePage.tsx
    ValidationPage.tsx
  components/
    fabric/
      FabricCanvas.tsx
      StructureOverlay.tsx
      RouteOverlay.tsx
      VcOverlay.tsx
      TrafficOverlay.tsx
      UtilizationOverlay.tsx
    artifacts/
      ArtifactGraph.tsx
      IdentityCell.tsx
    evidence/
      RunBundleChain.tsx
      ProducerIdentity.tsx
    status/
      ExplicitStateBadge.tsx
      AuthorityBadge.tsx
  contracts/
    types.ts
    presentation.json
```

Do not create an oversized `App.tsx`. Pages should compose contract-rendering components. Keep comments for invariants and authority boundaries, not narration.

## State invalidation

This is critical.

```
edit intent
→ revision becomes DIRTY
→ existing compile/certificate/evaluation/optimization views are stale
→ user recompiles
→ new design_hash returned
→ downstream views may load only if bound to that design_hash
```

Never leave old performance metrics visible beside edited local intent.

## Visual rules

- Light mode primary; dark mode supported.
- Flat engineering aesthetic; no gradients or glossy cards.
- Serif display type is acceptable for page titles; dense UI text remains sans/mono.
- Hashes and producer IDs use monospace.
- Use restrained accent colors only for semantic state.
- Do not color a topology overlay unless the data authority for that overlay exists.
- Always render an explicit reason for UNSUPPORTED, BACKEND_UNAVAILABLE, FAILED, UNMEASURABLE, and INELIGIBLE.

## Worker acceptance criteria

A worker implementation is not complete until:

1. One revision can move through Intent → Compile → Verify → Evaluate without re-entering information.
2. Editing intent invalidates downstream views.
3. CompilationView drives compiler status; frontend never reimplements compilation.
4. Certificate obligations are individually inspectable.
5. Missing metrics are omitted or marked UNMEASURABLE, never zero-filled.
6. Optimization preserves three separate authorities and explicit candidate states.
7. Serving is a distinct workflow and preserves instance/rank/endpoint/router namespaces.
8. Evidence page can trace one metric to producer/input/evidence/result identities.
9. Compare refuses or labels incompatible authorities.
10. Validation Lab labels the scope of ASTRA/Ramulator/RTL results.
11. Every visual overlay has a named backend payload requirement.
12. No Python engine module is imported into the browser bundle.
13. No hard-coded "successful" metric survives when the fixture/gateway payload removes it.
14. Unknown enum/state renders as UNKNOWN, never as a passing/default style.
15. The app can still run through a `FixtureStudioGateway` for deterministic UI tests.

## Prototype

Use `srota-studio-product-flow.html` as the interaction/reference shell. It is deliberately a single-file prototype so product flow can be reviewed before the React implementation is decomposed.
