# Design — Initiator–Target Mapping

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

Purpose: inspect and edit explicit system relationships without collapsing permissions, routes, and traffic into one matrix.

Use initiators on rows and targets on columns, with grouping, endpoint search, keyboard navigation, sticky labels, and a tabular alternative. Provide an explicit layer selector:
- Intended mapping.
- Configured access permission.
- Structural reachability.
- Routability under selected policy.
- Requested traffic, only as a read-only workload overlay.

A filled mapping cell does not prove access permission, a valid address map, or an observed communication. Define each symbol and its evidence source. Unknown checks remain unknown, not allowed.

Selecting a pair shows source/destination interfaces, declared mapping, access rule, address-region references, route-check scope, adapters, and unresolved obligations. Canonical routes are configuration, not observed paths.

Manual editing previews added/removed relationships and associated policy consequences. Changing access must be an explicit policy action, not an accidental side effect of drawing a connection.

Bulk mapping operations require reviewable scope and exceptions. Identify stale or missing endpoints, conflicting policy, unreachable mappings, and unsupported adapters. Do not auto-repair or relax protection to satisfy a workload.

Deliver: primary mapping matrix with one selected pair; permission-versus-reachability conflict; reviewed bulk edit. Show links to endpoint definitions, address regions, relevant requirements, and workload demand while preserving current selection.
