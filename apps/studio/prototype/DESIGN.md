# Srota Studio prototype design contract

## Surface mode

**Operate.** A local desktop engineering workbench for inspecting explicit architecture objects, running scoped local declaration checks, and reviewing fixture-backed design workflows. The attached Stitch exports establish the visual direction; their unsupported engineering claims do not establish product truth.

## Visual authority

Preserve the light, restrained industrial identity of the supplied Design and Explore exports. Use one shared shell and consistent component vocabulary across Design, Explore, Verify, Deliver, and desktop settings. This is a reconstruction/refinement, not a new brand direction or pixel-for-pixel reproduction of contradictory exports.

## Tokens

- Ground: `#F2F4F6`.
- Surface: `#FFFFFF`.
- Toolbar: `#E9EDF1`.
- Border: `#C9D1DA`.
- Primary ink: `#1D242C`.
- Secondary ink: `#536170`.
- Accent: `#0F6C9E`.
- Selection: `#E3F0F8`.
- Error ink: `#A32928`.
- Warning ink: `#79540C`.
- Success ink: `#246847`.
- Single typeface: locally served IBM Plex Sans, used for interface copy, code, and measured data with tabular numerals. Its engineered grotesque character fits the instrument-panel surface; it is not a neutral UI default.
- Four sizes only: 12px metadata, 14px interface and body text, 16px section headings, 23px page titles. Emphasized measures use 20px.
- Sentence case everywhere. No uppercase text transform; acronyms and identifiers stay as authored.
- Borders: 1px; control radii: 3–4px; dialog radius: 6px.

`src/styles.css` is the implementation token source. IBM Plex Sans is bundled locally with its OFL notice; there are no runtime font or icon CDN dependencies.

## Composition

Shared top header, workspace slots, one horizontal section strip under the page heading, dominant work area, optional selection inspector, and one operational footer/drawer. A workspace with a single destination shows no strip. Missing workspaces are visibly unavailable rather than represented by fake pages.

Primary desktop: 1440×900. Constrained desktop: 1280×800. At constrained widths, the inspector becomes an on-demand panel instead of squeezing the central view. Large tables use visible horizontal scrolling. Main content and the inspector scroll independently. Do not hide scrollbars or block text copying.

The guided flow is the landing composition with five visible steps: workload template → high-level workload intent → evaluate & choose fabric → parameter refinement of the selected fabric → final validation and supported RTL export. Workload templates show their definitions before project creation; fabric selection happens only after results. The section strip is the single five-step navigator; evaluation and choice share `flow/search`, while `flow/compare` remains a hidden compatibility alias. Catalog evaluation freezes one workload and preserves its agents, compute, requirements and router/physical inputs across complete typed topology candidates; BookSim and ASTRA-SIM receive their own generated formats and retain distinct metric scopes.

Fabric choice is a compact catalog workbench, not four tall profile cards over a nested plot. The four objective profile controls (Network, System, Balanced and Best evidenced) name a winner or its stated absence and open that fabric for inspection. The left comparison pane defaults to the All fabrics table and switches to the shared `InteractiveScatter` trade-off plot through a `.segmented` control. The right inspector opens on Measurements with recorded aggregate and per-traffic-class metrics visible without expanding disclosures, separated by backend scope. Configuration, controls identities and provenance sit in the secondary Configuration tab; generated input downloads sit in Files. Inspecting a row, profile winner or plot point does not choose it: inspected highlights and the Chosen badge represent different states, and the explicit Choose action retains eligibility and acknowledgement gates. At content widths of 960px or less, the inspector overlays the comparison instead of squeezing it; Close details dismisses it and returns focus to the invoking control. Comparison and inspector content scroll independently.

A profile never invents a fused score, a refused or requirement-failing fabric never wins, and a fabric missing one scope is not drawn at an invented position. Before results, evaluation setup states that no fabric is ranked; result controls appear only when rows exist. The flow links or embeds the workspace that owns each editing or evidence surface rather than duplicating it. Every catalog/backend verdict remains visible, including refusal and failure. Repository reference traces and the four-configuration revision study are separate detailed workspaces, never substitutes for this catalog run. AI assistance belongs after measured fabric selection, keeps that family and workload fixed, and requires configured model access plus explicit outbound consent. Manual refinement keeps the selected fabric's catalog-time network, system, requirement and VC facts in a summary strip. A sectioned editor groups topology and sizing, physical assumptions, router and pipeline, and (for Srota) typed fabric intent, so only the working group is visible. Its save bar stays pinned with the compile state and both Save & compile and Final validation actions. Save & compile pins the returned saved version, and unsaved changes or failed compilation block progression. AI refinement is the same page-level method switch and contributes to the one page scope block, not a second one. The RTL surfaces are tiered. A selected revision can launch a clearly labeled topology-only preview; it is fixed packet/router RTL, not the selected design's final implementation. Separately, composed-family A1–A10 evidence is keyed to a design hash and never transfers to a different design; the gateway exposes it only as family-scoped evidence. Physical implementation and signoff remain a third, unrun tier. No tier upgrades another. The flow owns no duplicate project, draft, revision or run state, and missing project or selection is stated rather than substituted with the sample.

The Design workspace opens on one editor surface (`design/editor`) rather than five parallel pages: outline, canvas or draft settings, a selection inspector and a single Problems list. The inspector shows only the selection and what the compiler derived for it; fabric-wide settings are reached from it, never presented as per-object overrides. Problems has no status pills — counts are plain text — and keeps errors, warnings and "not evaluated" separate, so an unmeasured obligation is never shown as passing. The toolbar carries the Save & compile action and one plain sentence of state, not badges.

## Component and interaction language

Use native forms, semantic tables, named icon controls, consistent authored line icons, visible focus, and native dialog focus handling. Dense information is appropriate; decorative telemetry, pulsing status, giant KPI cards, duplicate rails, and chat-first navigation are not.

The Fabric topology view is the reference composition for a working page: `view-layout` with `view-main` and `Inspector`, one `.toolbar` row of `Field` controls with `Badge`s and a primary `Button`, a `Notice` for provenance, then `Section`s with `.table-scroll` tables and a `.legend`. Pages do not invent a parallel vocabulary for the same job. Mode switches and tab sets use `.segmented`; parameter grids use `.form-grid`; checkbox groups use `.actions` with `.check-chip`; property lists use `Properties`; optional configuration and data use `details`. Analysis charts add plot marks (`.curve-*`, `.plot-*`, `.hop-*`) and one candidate panel, not their own controls, panels or type scale.

Every page follows one anatomy: page heading, one toolbar row, the working body, and exactly one `Assumptions` block as the last element. `Assumptions` is the only place for scope, provenance, method and limitation text; it is a collapsed `details` titled "Assumptions & scope". A `Notice` is reserved for state the operator must act on now — error, unavailable data, a blocked or invalid action, a selection outside coverage — never for philosophy or blanket non-claims. Prose paragraphs that explain how a page works are removed rather than restyled. A page does not repeat a fact already shown by a table, a badge or another section, and does not add a second navigation rail beside the workspace section strip.

Meaningful signature interactions: selecting a graph point, endpoint, or comparison object carries its identity into related views; reviewing a change produces an actual local state update; branching preserves the complete previous draft. Route changes do not execute tools or adopt designs.

## Truthful visualizations

Chart coordinates, thresholds, axes, and frontier membership derive from the same numeric fixture. Missing metrics are not plotted at invented positions. Logical and placement-intent coordinates stay distinct. Physical area/power/qualification cannot be fabricated for visual completeness. Plane D draws directed channels and shared wires as separate resources. Plane C is drawn only from the canonical control-plane artifact. Plane T is an overlay with no invented router/channel graph. Parallelism satellites and group outlines come only from `compile-result.groups.mapping`; unmapped endpoints stay uncoloured and are never assigned a rank, and a degree-1 axis is not presented as partitioning. Selecting a shared wire isolates the declared wire; it does not imply observed traffic or point-to-point channels. The system-composition diagram shows declared agent groups, derived endpoint attachment, and fabric counts; its arrows are never floorplan or traffic claims. The mapping incidence matrix counts declared channels or MECS driver→tap incidences between router pairs; it is not an access rule, a reachability proof, or an observed flow. An absent initiator→target rule set is drawn as absent, not inferred from endpoint kinds. Explore → Revision study owns the project's measured optimization study, including its candidate analysis; a study with fewer than two measured candidates is shown as a coverage statement rather than an empty chart. Analysis → Curves & Pareto keeps the measured workload reference joined from the same trace replay and BookSim's native power/area model. The reference exposes latency, hops, VCs, power, area, energy ratios, power–delay product and the measured buffer-depth sweep; the uniform power-versus-load reference is in Explore → Fabric Ablations; its power and area are research estimates, Vdd and temperature are fixed technology constants, and no voltage or temperature curve is invented. Explore holds the multi-workload and multi-topology reference work: Fabric Search ranks catalog fabrics for a selected workload (the workload is the input, not the search target); Fabric Ablations keeps the uniform injection-rate sweep and the measured workload ablation as separate sources in one workbench, and Workload Ablations holds the broad workload × topology matrix. The sweep has no workload axis, so a trace workload is never folded into an injection-rate curve, and a cross-arm workload comparison is refused when trace hash, simulator binary or seed differ. A single-objective study is shown as a ranking, not a fabricated 2D frontier; selected-run evidence stays on Analysis Summary, Metrics and Verify, and a single aggregate run is never expanded into an injection-rate sweep. Per-router totals are a source-port aggregation of measured channel counters, never router-internal queue occupancy or per-initiator latency. The trace viewer separates time (requested injections stacked by class, source/destination activity windows) from the traffic matrix’s pair structure (full heatmap, source/destination marginals, top-pair share). Class-specific matrix views are counted from the same trace; when the response carries no per-class pair grid, the aggregate matrix remains visible and no class split is inferred. Ramulator HBM3 metrics are shown only for a recorded `DRAM_TIMING` analysis; network and memory cycles use separate models and are never added, and a missing memory analysis is stated rather than inferred from workload memory-access bytes. Derived route attribution stays labelled derived; missing packet percentiles, power, area, energy, and wirelength are shown as gaps, not synthesized numbers.

Keep execution, evidence availability, requirement outcomes, generation eligibility, and target qualification separate. All authored data remains visibly illustrative. Never upgrade a packet metric into a transaction requirement or a local declaration check into hardware verification.

## Implementation boundary

Local snapshots, browser state, JSON serialization/downloads, and in-browser declaration checks are real prototype operations. When a gateway project is loaded, draft saves, compiles, and evaluations are real gateway operations: they mutate only that project and are confirmed by the returned revision, certificate, or run. Fixture mode remains local and must not be described as compiled. Simulation, formal proof, RTL generation, implementation qualification, agent execution, tool discovery, and enforceable execution budgets are not connected. Labels and disabled actions must preserve this distinction. Do not fake backend success with alerts or timers.

## Design workbench amendment

The Design workspace is a working surface, not a report. Its page anatomy is a
one-line heading, one command bar, the working object (canvas, matrix, diagram
or editor), and a contextual inspector. The project and revision live in the
shared header. Workspace-purpose paragraphs, page-purpose paragraphs and the old sidebar
"working context" block are removed; they repeated the header and the first
table.

No workspace has a left view rail. Its surfaces are one horizontal section
strip under the heading, and the strip is the workspace's only navigator. Tabs
are real links, so deep links, history and open-in-new-tab still resolve. A
workspace with a single destination renders no strip. Section state (selected
router, run or draft) remains inside the surface, not in the strip.

The Design strip carries the six surfaces that can change the draft or declare
a design rule: Fabric topology, Agent catalog, Agent map, Address map, Domains
and Placement. Fabric topology is the landing surface. System, Endpoints and
Mapping remain hidden context routes because the gateway has no write path for
them; their content is reached from the page that owns the change, and they do
not occupy a tab that promises an edit. The old Workflow route is hidden for the
same reason; status and consequences live in the pages that own them. The page heading carries only the single Compile draft action. A compile
uses the saved draft; the page that owns an edit saves it to the draft first.
The six strip surfaces and the three context routes edit or read the same draft
and selected revision; the removed rail added a second navigator beside the
strip and took width the canvas needs.

The Fabric topology page is the reference: a full-height three-pane workbench
(object rail, canvas, inspector). Selecting a router or wire fills the
inspector; findings are a selectable list; shared wires are opt-in; zoom is a
real control. The previous below-the-canvas channel table, shared-wire table,
routing/VC summary, ordering verdict and physical-estimate dump are removed.
Detail appears only for the selected object, and only when it changes a
decision or an edit.

The agent/endpoint split is explicit. Agent Catalog owns the agent-group
inventory. Agent Fabric Map owns agent interface fields and the agent-scoped
window auto-map and coverage; Address Map owns the system-wide window editor,
resolved decode and blocking checks. Both window surfaces write the same
`address_map.ranges` field; the system view is the authoritative check surface.
Endpoints remains a hidden context route: it shows compiled seats and a
declared-versus-materialized count by agent kind, and does not pretend a seat is
an editable attachment when the gateway derives it. Protocol-ownership findings
sit beside the protocol field: an unowned literal is preserved for identity and
reports only and generates no adapter.

Other Design pages follow the same rule. A page that has no selection
inspector uses the full content width rather than reserving an empty rail.
Declared-physical parameters collapse to the values that exist plus one
"Not declared" line. Tables remain only where they are the object list, the
editor, or the selected object's data. The floorplan map labels its routers;
the address page shows its editor and empty state without a compiled-artifact
dump.
