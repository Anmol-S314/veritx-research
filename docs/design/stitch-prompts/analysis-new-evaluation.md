# Stitch prompt: Analysis — New Evaluation

## Shared product and design contract

Create this surface for **Srota Studio**, a local desktop engineering application for NoC and hardware-system architecture. Use the attached approved screen as the visual reference. This contract and the specific brief below are the complete prompt; settled product decisions do not require another discovery interview.

### Product boundaries
- Preserve two journeys: workload-first architecture evaluation and existing-design improvement.
- Six contextual workspaces: Design; Workloads & Requirements; Analysis; Explore; Verify; Deliver. These are not mandatory wizard stages.
- Manual engineering remains fully usable offline without AI. AI is optional, closed by default, and never the database or primary navigation.
- Designs, workloads, requirements, studies, runs, snapshots, checks, and artifacts are explicit revisioned objects. Historical results remain applicable to their original immutable inputs.
- Support Srota, supported BookSim families, and custom graphs through configuration-specific capability checks. Modeling, simulation, verification, RTL generation, and target implementation are independent capabilities. Engine installation does not establish qualification.
- Distinguish connectivity, address mapping, access permission, routability, requested traffic, injection, delivery, and observed paths. Do not silently substitute one for another.
- Distinguish architectural intent, analytical estimates, simulation observations, generated RTL, verification evidence, and physical implementation. ASIC and FPGA qualification are separate.
- Complete accelerator generation is not an established capability. Declared compute/memory behavior does not generate compute datapaths. Mark supplied IP and model-only blocks explicitly.
- Planned interfaces may be designed, but document planned/unavailable status rather than claiming implementation. Unsupported descriptions may remain editable and exportable without becoming eligible for production RTL.
- Never invent simulator flags, generator versions, measurement artifacts, qualified configurations, proof results, overhead figures, process-specific power, or achieved timing. Do not include confidential internal specification contents in generated examples.
- Every repair is explicit and reviewable. Never silently modify architecture, relax requirements, remap endpoints, or replace the active design.

### Visual system
Retain the approved light-first industrial identity: Inter, JetBrains Mono for technical values, restrained blue accent, cool neutral surfaces, flat bordered panes, compact readable controls, and small radii. Inherit actual reference tokens rather than creating another palette.
Use essential text generally 12–14px. Support 1440×900, 1920×1080, and constrained 1280×800. Collapse/rescale pane structure rather than shrinking text. Use one contextual left pane, a dominant central workspace, a collapsible inspector, and one Jobs/Problems/Logs drawer when useful.
Do not reproduce known reference defects: duplicate Workbench Explorer rails, page-wide text-selection blocking, hidden scrollbars, decorative pulsing, unsupported thermal summaries, ambiguous global cycle counters, or duplicated status/navigation bars.
Use native-feeling selection, forms, tables, keyboard focus, copyable identifiers, visible scrolling, accessible icon labels, and non-color-only statuses. No marketing chrome, giant KPI walls, gradients as decoration, or chat-first layouts. Charts may use meaningful sequential/diverging scales.
Show empty, loading, unsupported, partial, failed, and revision-mismatch states where relevant. Explain each with a useful next action; distinguish zero from missing or not applicable. Do not turn every state into a modal.

### Evidence and numerical discipline
Always identify evaluated inputs, measurement definition, units, aggregation/window, source, and limitations where relevant. Execution success does not mean requirement compliance. Use Met, Violated, Not evaluated, and Inconclusive according to an explicit assessment policy.
A missing packet trace does not rule out measured percentiles when an appropriate histogram exists. Packet latency is not complete transaction latency. High utilization does not prove head-of-line blocking, starvation, deadlock, or a causal bottleneck.
Compare runs only with disclosed workload, measurement, backend, and assumption differences. Report scoped observations, not global optimality.
Keep sample arithmetic consistent. A 128-bit link transferring one flit/cycle at 1.4 GHz has 22.4 GB/s raw capacity per direction. Whole-network aggregates may exceed one-link capacity but need explicit scope. A 450,000-cycle window at that clock lasts about 321.4 microseconds.
Use shared illustrative identifiers where useful: project Falcon8_NoC_Gen2; evaluated design d7a4e9b; current draft changed afterward; workload ResNet50_Burst [w12]; requirements r5; completed run SIM-402; separate active job SIM-403. Keep these records consistent across surfaces. REQ-LAT-04's example threshold is 25 ns, not 20 ns; show 28.6 ns only with explicitly defined transaction-level measurement support. Otherwise show Not evaluated.
Keep “Illustrative sample data” visible. Do not invent evidence to preserve a successful-looking screen.

### Optional agents
Human and agent actions use the same validated operations, permissions, revision checks, and budgets. Approve one versioned exploration brief specifying workload, assumptions, requirements, allowed changes, search space, and execution limits. Included runs need no repetitive approvals; scope expansion requires new approval. Candidates remain isolated until human adoption.
ACP connects compatible agent runtimes; it is not a model provider or domain authorization system. Remote AI is optional and policy-controlled. Do not depict a connection as permission to execute arbitrary commands.

### Output discipline
Generate the specific requested surface and its meaningful variants inside this established system—not all workspaces at once. If producing HTML, distinguish local demonstration state from real integration. Do not fake queue acceptance, saved revisions, simulation completion, or repaired hardware with alerts/timers. Functional zoom must transform the view, not only its label. Use explicit demo states when integration is absent.

## Specific surface brief

Use the corrected Analysis screen as the visual reference. Design the New Evaluation flow inside the same Srota Studio application. Preserve the approved shell, palette, typography, borders, controls, and engineering density. Do not copy known defects such as duplicate sidebars, hidden scrollbars, or tiny text.

## Purpose and boundaries

Help an engineer configure a reproducible evaluation with explicit inputs, supported settings, requested evidence, and bounded execution. Manual operation is first-class; AI is optional and closed by default.

The engineer must understand which design, workload, requirements, assumptions, backend, measurements, and execution limits apply. Launching creates a new run. It never overwrites historical results or silently changes the active design.

This is an evaluation setup flow, not an architecture generator, broad design-space search, or mandatory wizard. Simulation does not establish RTL correctness or physical implementation qualification.

## Entry scenario

The engineer enters from the missing-artifact Traffic Matrix view:

- Project: Falcon8_NoC_Gen2.
- Historical run: SIM-402, completed.
- Evaluated design snapshot: d7a4e9b.
- Workload: ResNet50_Burst, revision w12.
- Requirements: revision r5.
- Current editable draft: contains changes after d7a4e9b.
- Investigation: endpoint-pair delivered traffic counts were not recorded.

Preserve SIM-402 and its existing evidence. Do not promise capture support until compatibility is established. Keep “Illustrative sample data” visible at every viewport size. Do not include confidential specification content.

## Layout

Open a large right-side setup drawer over Analysis, approximately 720–800px wide at 1440×900. At 1280×800, use a near-full-width panel rather than crushing the form. The background workspace remains recognizable. Avoid redundant inspectors behind the setup.

Use:

- Sticky header: “New Evaluation,” “Based on SIM-402,” close control.
- Scrollable body: Inputs; Backend & Compatibility; Simulation Settings; Evidence Capture; Execution Limits; Review.
- Sticky footer: validation summary, Cancel, Review Evaluation or Queue Evaluation.

Use sections and progressive disclosure, not a full-screen numbered wizard. Keep essential text generally 12–14px. No KPI-card wall or decorative animation.

## Inputs and immutable snapshots

Make the revision choice explicit:

1. **Re-evaluate original inputs:** uses SIM-402’s immutable design and workload snapshots; useful for reproducing the setup with additional capture.
2. **Evaluate current draft:** captures a new immutable design snapshot; workload and requirements revisions remain explicit choices.

For this entry scenario, original inputs may be visibly preselected. Never switch to the newer draft silently.

Show design, workload, and requirements identifiers and revisions, relevant assumptions, and links to inspect them. Snapshot identifiers are application objects; do not assume every revision is a Git commit.

If inputs change after validation, mark validation out of date and require updated review. A running evaluation never follows live draft edits. Final submission must bind exactly the reviewed immutable inputs.

## Workload and requirements

Support both workload-first exploration and existing-design improvement. Allow workload inspection without losing setup changes.

Expose endpoint references, operation/traffic scope, phases, assumptions, and relevant compute or memory-model inputs. Declared compute durations are model inputs, not compute RTL generation.

Validate workload references against the chosen design. Missing endpoints produce an object-linked blocker, not silent remapping. Offer inspection or navigation to the owning editor.

Requirements are selected acceptance criteria, not execution limits. Preview which criteria the selected measurements can assess. Never relax a requirement to make the configuration runnable.

## Backend and compatibility

Select from the application's established capability catalog. Distinguish:

- Installed/available.
- Compatible with the selected configuration.
- Supported evaluation scope.
- Qualification limitations.

Engine presence is not qualified support. Show versions only when metadata supplies them; do not invent versions or command-line flags.

Use bounded descriptions such as network performance simulation or architectural memory-system evaluation. Do not assume RTL correspondence or universal cycle accuracy.

Compatibility depends on topology, configuration, and backend. Support the catalog's Srota configurations, BookSim families, and custom graphs without implying every backend accepts every family.

Show each finding with the affected object/setting, reason, severity, consequence, and reviewable next action. Distinguish execution blockers from evidence limitations. Do not silently repair architecture.

ASIC and FPGA implementation qualification remain separate from architectural simulation and from each other.

## Simulation settings

Show only backend-supported controls, potentially including clock assumptions, warm-up policy, measurement window, phases, seed, repetitions, and model-specific settings.

Identify inherited design/workload values. Do not expose architecture-owned settings as unrelated evaluation edits. Architecture changes require a deliberate design revision workflow.

If model overrides are supported, label them as evaluation assumptions, record them, and explain comparison consequences.

Place units beside inputs. Distinguish simulation cycles, simulated time, and wall-clock limits. Define phase-boundary semantics where relevant. Show advanced settings progressively rather than inventing a wall of flags.

## Evidence capture

Use a compact table: Evidence; Purpose; Support; Capture choice; Known overhead.

Potential evidence, only when supported:

- Aggregate throughput summary.
- Endpoint-pair injection counts.
- Endpoint-pair delivery counts.
- Directed-link utilization.
- Buffer occupancy statistics.
- Supported latency measurements.
- Detailed event or packet trace.
- Execution logs.
- Resolved input manifest.

Highlight “Requested for this investigation: endpoint-pair delivered traffic counts.” Requested demand, observed injection, and observed delivery are different bases.

Do not invent simulator instrumentation flags, artifact sizes, or overhead percentages. Unknown overhead reads “Not estimated.” Unknown support reads “Support not established.” Unsupported options show a precise, accessible reason.

If the requested capture cannot be produced, require explicit resolution. Do not quietly launch without it. An execution-only run may remain possible only after the engineer explicitly accepts its reduced evidence scope.

Historical missing data cannot be recovered by changing a display setting.

## Coverage preview

Show a compact table: Criterion/investigation; Required measurement; Expected availability; Limitation.

Distinguish network packet latency from complete transaction latency. Packet statistics do not automatically assess transaction criteria. Aggregate percentiles can be supported by an appropriate histogram without detailed packet trace capture.

Separate estimates from observations. Do not promise deadlock-freedom proofs, functional correctness, RTL equivalence, achieved timing, or power signoff.

## Execution limits

Keep execution controls separate from design requirements. Expose only supported controls, such as wall-clock limit, memory limit, worker allocation, enforceable output-storage limit, and execution destination.

Distinguish enforced limits from advisory estimates. Default to local execution without a mandatory cloud account or AI provider. Show monetary controls only for an explicitly selected execution service that requires them.

Explain limit-reached behavior. Preserve logs and available partial artifacts; do not represent truncated measurements as complete results. A single evaluation does not include a topology search budget.

## Review and queue

Provide an inline review state summarizing:

- Immutable design, workload, and requirements inputs.
- Backend and supplied version.
- Scope, assumptions, and overrides.
- Measurement window and repetition policy.
- Requested artifacts.
- Execution limits.
- Unsupported assessments and remaining warnings.

When based on SIM-402, show a compact configuration diff. Highlight changed capture settings and any other intentional differences. Do not call evaluations identical when their conditions differ.

Separate blockers, warnings, and informational limitations. Use “Configuration checks passed for queue submission,” never “Hardware verified.”

Enable Queue Evaluation only when required inputs are resolved, blockers are addressed, capture choices are explicit, and review matches the bound input snapshot.

On real submission, prevent duplicates and show pending state. Create a run only after acceptance; then add it to Run History and offer View New Run. Do not invent its ID before acceptance. Submission failures preserve entered settings and support a deliberate retry without duplicate jobs.

For a static prototype, illustrate states without claiming backend operations occurred. Never use timers or alerts to fake successful runs or saved revisions.

## Optional AI

Keep AI closed. Secondary actions may explain settings or draft an editable configuration. Human and agent actions use the same validation, revision checks, and limits.

AI must not silently change architecture, relax requirements, replace the active design, launch an unbounded search, or expand approved scope. Broad exploration belongs in Explore with an approved bounded brief.

## Accessibility and dismissal

Provide visible focus and scrolling, copyable values, accessible labels, logical tab order, correct focus handling, inline validation, and an error summary linked to blockers. Essential explanations must not depend on hover.

Closing modified setup offers Continue Editing or Discard Setup. Discarding setup never changes the design or deletes historical evidence.

## Deliverables

Generate two variants in the same visual system:

1. Primary setup drawer: original SIM-402 inputs selected, explicit current-draft alternative, backend compatibility, requested pair-delivery capture, honest support/overhead states, execution limits, and access to review.
2. Review state: resolved immutable inputs, configuration differences, coverage, limitations, and Queue Evaluation. If capture support is unresolved, show a blocker rather than fabricating support.

Success: an engineer deliberately configures a reproducible, bounded evaluation and understands which evidence it can produce before committing execution resources.
