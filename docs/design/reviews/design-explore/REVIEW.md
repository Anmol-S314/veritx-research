# Design and Explore export review

## Scope and method

Reviewed the **12 exported HTML views** under `docs/design/stitch_veritx_studio_eda_frontend`: **7 Design specialists and all 5 Explore views**. This review does not assume that the other planned surfaces were generated or exported.

Method: direct parent-led source inspection and local Chromium rendering, not a formal independent dual-review, backend capability audit, or complete accessibility/conformance test. No application or exported HTML was edited. No interaction was used to adopt a design, submit a job, or change project state.

All 12 supplied `screen.png` files contain the text `<FIFE Image failed to fetch>` rather than PNG images. The HTML is usable, so fresh screenshots were rendered locally at **1440×900 and 1280×800**: 24 captures, with Tailwind present and no observed page JavaScript errors during initial rendering. This does not establish working domain operations.

Evidence:
- [Design contact sheet, 1440](contact-design-1440.png)
- [Design contact sheet, 1280](contact-design-1280.png)
- [Explore contact sheet, 1440](contact-explore-1440.png)
- [Explore contact sheet, 1280](contact-explore-1280.png)
- [Browser measurements](render-metrics.json)
- [Selected source evidence](source-evidence.json)
- Full individual captures remain under `/tmp/veritx-stitch-review/` for this session.

## Verdict

**Keep the visual direction and most workspace structures. Do not use the current sample data, evidence badges, or chart geometry as engineering truth.** These are useful design references, not an implementation-ready functional specification.

The strongest parts are explicit model/supplied-IP boundaries, object-linked inspectors, separation of isolated candidates from the active design, and a bounded exploration approval concept. The highest-risk problems are semantic and numerical, not a need for another aesthetic redesign.

## Priority findings

### 1. P1 — The Pareto plot contradicts its data and invents positions for unavailable values

Source: [candidate results, lines 312–444](../../stitch_veritx_studio_eda_frontend/explore_candidate_results_trade_offs/code.html#L312).

The latency axis has larger values toward the top, but the candidates with *smaller* latency are drawn higher: C-09 is labelled 22.4 ns near the 34 ns region; the 28.6 ns baseline is drawn below it. The 25 ns threshold line does not align with its tick. Axis labels, fixed SVG points, and percentage-positioned HTML markers use unrelated coordinate systems.

Incomplete/failed candidates also receive plotted positions despite missing required coordinates. The caption claims a frontier among 32 comparable evaluated candidates while its population includes incomplete, invalid, and failed entries. C-22 is presented with the compliant/frontier encoding even though its listed 0.345 mm² exceeds the displayed 0.320 mm² hard area ceiling.

Fix: derive axes, thresholds, points, selection, and frontier from one dataset and scale mapping. Missing coordinates stay in an unplotted list. Define the comparison population and distinguish an unconstrained frontier from the compliant recommendation frontier.

### 2. P1 — The same requirement and run identities change meaning across screens

Sources: [brief, line 327](../../stitch_veritx_studio_eda_frontend/explore_versioned_exploration_brief_stu_088/code.html#L327), [progress, lines 204–205](../../stitch_veritx_studio_eda_frontend/explore_study_execution_budgets/code.html#L204), [comparison, line 380](../../stitch_veritx_studio_eda_frontend/explore_candidate_comparison/code.html#L380), [adoption, lines 297–304](../../stitch_veritx_studio_eda_frontend/explore_candidate_adoption_branch/code.html#L297).

REQ-LAT-04 changes from the agreed transaction P95 criterion to packet/flit P99, then an HBM **mean** criterion. These are not interchangeable. SIM-402 becomes a 22.4 ns compliant candidate in the progress ledger but remains a 28.6 ns violating baseline elsewhere. CAND-04 references SIM-404 in pinning and SIM-405 in the main comparison table. Study IDs and input configurations also drift without a clear intentional cross-study transition.

Fix: define one immutable illustrative fixture shared across views. Changing a requirement definition creates a distinct revision/identifier. Do not retain a transaction assessment without supporting transaction measurements. Distinct studies are allowed, but their identity and navigation must be explicit.

### 3. P1 — Unsupported qualification and certification claims overwhelm the caveats

Sources: [IP catalogue, lines 149–287 and 521](../../stitch_veritx_studio_eda_frontend/design_ip_catalog/code.html#L149), [endpoint MTBF, lines 851–852](../../stitch_veritx_studio_eda_frontend/design_hardware_endpoints/code.html#L851), [brief certification, line 420](../../stitch_veritx_studio_eda_frontend/explore_versioned_exploration_brief_stu_088/code.html#L420), [comparison, lines 151 and 584](../../stitch_veritx_studio_eda_frontend/explore_candidate_comparison/code.html#L151).

Examples include TSMC N5 signoff qualification, timing-clean wrappers, DRC/LVS clean, a >10^12-hour MTBF signoff, verified silicon constraints, qualified RTL adapters, and “ISO/EDA Deterministic Signoff Std 2024.” No supporting evidence for those claims was supplied. The latter must not be presented as an established certification standard. A sample-data label does not make a misleading product capability claim acceptable.

Fix: remove these claims or replace them with explicit not-evaluated/unknown/planned capability states. Scoped positive evidence needs a declared method, inputs, artifact, and limitations. Do not fabricate an artifact just to keep the badge.

### 4. P1 — Desktop layouts lose usable workspace even at the required sizes

Visual evidence: both Design and Explore contact sheets. Browser measurements show offscreen address-row actions and placement-toolbar controls at both sizes.

System Diagram has an outer Architecture Elements rail plus a second system hierarchy and a fixed inspector, crushing the actual block diagram. At 1280, labels collide and the generation boundary overlaps content. Comparison devotes substantial width to fixed side panes while columns and toolbar actions are obscured. The address table's row actions measure around x=1564 at a 1280-wide viewport. Placement zoom/filter controls measure around x=1759–2022 at that width.

The document itself measuring 1280 pixels wide does **not** prove the descendants fit. Some tables may intentionally scroll, but hidden scrollbars conceal that escape route. Every exported view hides WebKit scrollbars; 8 of 12 apply body-wide `select-none`.

Fix: one contextual left pane, collapsible inspectors, visible scrolling, separate toolbar rows, overflow menus, readable essential text, and explicit responsive pane behavior. Keep wide tables scrollable instead of shrinking the text.

### 5. P1 — Candidate adoption presents unsafe partial application as a clean merge

Source: [adoption, lines 135–158](../../stitch_veritx_studio_eda_frontend/explore_candidate_adoption_branch/code.html#L135).

The candidate changes a 16-router mesh into a four-router concentrated topology, but the UI offers “7/8 clean” patches while preserving an old router placement constraint. Structural references may no longer exist. Textual nonconflict is not semantic compatibility. The overwrite acknowledgement checkbox is not wired to disable/enable the action; the script only changes labels/styles. This is a prototype, not an enforced guard.

Fix: prefer branch/open-isolated. Disable partial application until a domain-level transformed proposal is generated and revalidated. Preserve unsaved work through an explicit snapshot/recovery step rather than casually erasing caches or “draft commits.” A new branch does not automatically mean a Git ref.

### 6. P1/P2 — Arithmetic and interface semantics need a coherent fixture

- **Address density:** the selected space is 48-bit/256 TiB, not a small plotted subset. The listed regions sum to 33.7363 GiB, or **33.4863 GiB after subtracting the 256 MiB overlap**, not 33.24 GiB. Their union covers about **0.012774%** of that space, not 68.4%. Source: [address map, lines 84 and 472](../../stitch_veritx_studio_eda_frontend/design_address_map/code.html#L84). If density refers to a different scope, explicitly define that scope.
- **Packetization:** 128 bytes require at least **8 × 128-bit data flits**, not two; headers/overhead may add more. Source: [IP catalogue, line 617](../../stitch_veritx_studio_eda_frontend/design_ip_catalog/code.html#L617).
- **Buffer ratio:** 2 VCs × 8 flits = 16 flits/port; 4 × 16 = 64 flits/port, a **4× total-buffer increase**, not the unqualified 2× label. Source: [comparison, lines 281–294](../../stitch_veritx_studio_eda_frontend/explore_candidate_comparison/code.html#L281).
- **Die area:** 4.8 mm × 4.8 mm is **23.04 mm²**, not 4.8 mm². Source: [placement, line 213](../../stitch_veritx_studio_eda_frontend/design_placement_constraints/code.html#L213).
- **Interface roles:** returning link credits does not itself make an AXI endpoint an initiator. Coherent roles need the actual interface profile and transaction behavior. Source: [endpoints, line 863](../../stitch_veritx_studio_eda_frontend/design_hardware_endpoints/code.html#L863).

## Per-view notes

| Export | Keep | Correct before using as a specification |
|---|---|---|
| System / Block Diagram | Model-only vs supplied-IP boundary; adapter inspector | Remove duplicate outer rail; reconcile torus/mesh, VCs, endpoint counts; qualify adapter-generation claims; make block/port connections legible. |
| IP Catalog | Technical listing and explicit instance staging | Remove vendor/library/licence/signoff inventions; correct packetization; make staging a labelled demo or validated operation, not timed fake success. |
| Hardware Endpoints | Dense table, explicit concentrator diagram, deletion impact | Reconcile HBM peer attachments with the inspector; remove MTBF signoff; correct roles; validate aggregate concentration capacity rather than one endpoint alone. |
| Initiator–Target Mapping | Separate layer breakdown and permission/reachability conflict | Replace broad Fully Qualified labels with scoped layer results; reconcile 8×10 heading and 48-pair totals; do not recommend permission revocation as a connectivity repair; fix alert-based fake apply. |
| Address Map | Useful overlap visualization and proposed base/end diff | Fix totals/density; avoid asserting a specific router dual-grant failure from overlapping ranges alone; show revalidation as pending instead of claiming zero collisions in advance. |
| Clock & Power Domains | Explicit intent-level warning and missing-bridge obligation | Remove global DRC clean and unsupported validated bridges; no automatic proof that a frequency reassignment clears CDC or adds zero violations; show a normal base state, not only a pre-opened modal. |
| Placement Constraints | Explicit logical/constraint/imported-evidence modes | Remove invented enforcement/PnR/RC claims; fix area and offscreen controls; preserve old run evidence instead of blanket stale marking; distinguish declared frame from imported/calibrated implementation evidence. |
| Exploration Brief | Versioned scope and one approval for included runs | Remove certification; preserve requirement semantics; define buffer-capacity proxy vs physical area; reconcile weighted three-objective prose with two-objective frontier policy; show exact active sweep values and eligibility. |
| Execution & Budgets | Child run ledger, explicit scope-expansion request, separate execution/outcome text | Fix SIM-402 identity and requirement definitions; do not infer host CPU frequency from NoC clock; qualify trace trimming and enforcement; avoid calling local execution literally free. |
| Candidate Results | Candidate categories, inspector, isolated adoption intent | Rebuild numeric chart and frontier population; no fabricated coordinates for missing metrics; mark area violations; distinguish aggregate/injected/delivered throughput; do not offer trace-only reconstruction without a supporting source. |
| Candidate Comparison | Configuration differences and incomparability warning | Reconcile candidate/run IDs, routing-policy descriptions, buffer ratio, metric definitions; remove unsupported physical/RTL proofs and timing slack; collapse side panes at smaller widths. |
| Candidate Adoption / Branch | Explicit isolation, model-only candidate, conflict awareness | Block unvalidated partial topology patch; preserve current draft; enforce any destructive review; remove generic Git assumptions; reconcile active-draft coordinates and footer width/clock/topology. |

## Shared design document

The exported [DESIGN.md](../../stitch_veritx_studio_eda_frontend/precision_silicon_workbench/DESIGN.md) is useful visual reference material, not product truth. Its YAML and prose palettes/radii differ. It also prescribes global convergence/cycle readouts and example port handles that are not universally appropriate. Consolidate one token source and remove capability assumptions before using it as implementation authority.

## Recommended next action

Do **not** regenerate all planned views to satisfy a screen count. This 12-view subset is enough to review the Design/Explore system. Keep the current exports intact. Use [the focused correction brief](corrections.stitch.md) on one screen at a time, or make the same corrections during implementation after the product fixtures and shared shell are agreed.

Correction order:
1. Shared immutable fixture and requirement definitions.
2. Numeric Pareto plot and candidate classification.
3. Adoption safety and unsupported qualification claims.
4. Shared shell and desktop layout.
5. Page-specific arithmetic/interface fixes.

Other workspaces can be exported in separate batches within the user's stated Stitch limit. Prompt coverage is not generated-screen coverage, and neither establishes implemented functionality.
