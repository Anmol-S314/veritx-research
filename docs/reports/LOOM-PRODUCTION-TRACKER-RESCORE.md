# Loom production tracker — honest re-score (post-merge)

**HEAD:** `c13f7ca2` (merge `land reconciled finish-branch onto studio-reconciliation`).
**Working tree:** clean. **Verified on this tree:** `npx tsc --noEmit` → exit 0;
`npx vitest run` → 70 files / 671 tests passed.
**Prior audit** (`LOOM-PRODUCTION-TRACKER-AUDIT.md`) was scored *before* the merge, on a
dirty `601a71bd` tree, and reported DONE=0 / PARTIAL=84 / NOT-DONE=283. The merge
(`601a71bd → c13f7ca2`) landed ~26k lines (149 files), which is why the verdicts move.

## Method

Each of the 367 master-tracker rows was re-read against committed HEAD code and its
contract test, using the tracker's own "Acceptance / Done When" text. Rubric:

- **DONE** — every acceptance clause is satisfied on HEAD, on the surface the tracker
  names, and a committed test or artifact proves it.
- **PARTIAL** — related implementation exists but at least one clause is unmet/unproven.
- **NOT DONE / NOT PROVEN** — no substantive evidence, or the required surface is absent.

**Desktop rule enforced:** the workbook targets a desktop/Tauri product (local files,
`loom-sim` sidecar, signed updates, installers). HEAD is a **web** React/Vite Studio plus
a local graph-authoring slice. A web analog is **not** accepted as proof of a desktop
clause; such rows are capped at PARTIAL (analog exists) or NOT DONE (no analog). Engine,
physical-signoff, licensing, updater and installer rows are therefore still open.

**Independent spot-check:** every symbol and test file cited by the re-score was confirmed
present on HEAD (e.g. `VcConfigV1`, `DomainsConfigV1`, `ProjectAgent`, `FirewallConfig`,
`TraceEventV1`, `RunSummaryV1`, `RunManifestV1`, `TraceIndex`, `previewOddEvenPath`,
`validateAllowedRouteReachability`, plus all 17 cited contract tests). The one cited
Playwright run shows a **failed** test (F18), not F01 — treated accordingly.

## Verdict totals (this re-score)

| Verdict | Tasks | Share | Prior audit |
|---|---:|---:|---:|
| **DONE** | 97 | 26% | 0 |
| **PARTIAL** | 156 | 43% | 84 |
| **NOT DONE / NOT PROVEN** | 114 | 31% | 283 |
| **Total** | **367** | 100% | 367 |

## By milestone

| Milestone | Tasks | DONE | PARTIAL | NOT DONE | Done% |
|---|---:|---:|---:|---:|---:|
| M0 | 22 | 21 | 1 | 0 | 95% |
| M1 | 34 | 19 | 10 | 5 | 55% |
| M10 | 27 | 0 | 4 | 23 | 0% |
| M11 | 48 | 12 | 24 | 12 | 25% |
| M2 | 26 | 4 | 18 | 4 | 15% |
| M3 | 27 | 15 | 11 | 1 | 55% |
| M4 | 34 | 0 | 22 | 12 | 0% |
| M5 | 29 | 23 | 3 | 3 | 79% |
| M6 | 43 | 3 | 24 | 16 | 6% |
| M7 | 23 | 0 | 14 | 9 | 0% |
| M8 | 25 | 0 | 9 | 16 | 0% |
| M9 | 29 | 0 | 16 | 13 | 0% |

## What closed since the merge

- **M0 data-model freeze** is now effectively closed (21/22 DONE): the unified
  `project.json` v1 (M0-01…05) plus section contracts for VC/QoS (M0-06), clock/reset/power
  domains (M0-07), agents/ports (M0-08), catalog refs (M0-09), access/firewall (M0-10),
  floorplan (M0-11), workload phases (M0-12), trace (M0-13), summary (M0-14), run manifest
  (M0-15), canonical issues (M0-16), one store (M0-17), derived selectors (M0-18).
- **M1 graph editing** moved from ~0 to 19/34 DONE: command/revert layer, undo/redo,
  pan/zoom, node/port rendering, drag-snap, selection, delete-preview, copy/paste,
  duplicate, presets (mesh/star/srota), validation rows.
- **M3 routing/firewall/domains** 15/27 DONE: XY/West-First/Odd-Even + custom routing,
  firewall editor with deterministic JSON and reachability audit, path/VC inspection.
- **M5 workload** 23/29 DONE: phases, communication ops, tensor metadata, rank mapping
  (+overlay, constraints), deterministic JSON import/export. (Workload editing is pure
  local software, so it clears the desktop rule.)
- **M11** 12/48 DONE: schema/migration/store/command/validation contract suites, plus F01.

## Still genuinely open (no surface exists / capped)

- **M10 desktop/Tauri** 0/27 — no `src-tauri/`, no updater, no license, no installer.
  Only SBOM/notices/`npm audit` are PARTIAL.
- **M6 engine** — no `loom-sim` sidecar; trace/playback helpers are MOCK/user-provided, so
  only 3 self-contained parser rows are DONE. Backend run, replay, support bundle open.
- **M4 physical handoff** 0 DONE — web floorplan authoring is an abstract projection; no
  DEF/OpenROAD/KLayout, no congestion/signoff.
- **M8 file resilience** 0 DONE — localStorage analog only; no atomic real-file save,
  crash recovery, bundle, or centralized export.
- **M9 performance** 0 DONE — budgets are an unapproved proposal; no measured results.
- **M7 diagnostics/replay** — support bundle, logs, determinism, golden replay open.

## Caveats (do not over-read this)

1. **This does not close the tracker.** 114 rows remain unproven and every release gate
   (0/26) and most E2E flows (1 passed / 1 partial / 22 not started) are still open.
2. **Weakest DONE rows** (web-analog or template evidence): M11-17 (F01 run evidence shows
   a sibling failure), M11-46 (checklist exists; the release it describes is not passed),
   M1-04/M1-16 (web editor only). These are honest for the *task text* but are not desktop
   acceptance.
3. **Tracker status is a separate artifact.** The workbook's own Status column was set
   independently; this re-score updates the audit columns and the workbook copy, but the
   authoritative `/home/datavex/Downloads/loom_production_execution_tracker.xlsx` is
   untouched.

---

# Full per-row ledger (367 rows)

## M0–M1

# Re-score — Loom production tracker, milestones M0 and M1

Repo `/home/datavex/bruh/veritx-research` @ HEAD c13f7ca2 (merge landed; 8caed21d docs-only above). Baseline = `docs/reports/LOOM-PRODUCTION-TRACKER-AUDIT.md` as committed at 601a71bd (pre-merge). Every verdict below re-checked against HEAD code + contract tests, not the audit text.

## M0-M1
DONE=40 PARTIAL=11 NOTDONE=5 CHANGED_FROM_AUDIT=36

| ID | NEW VERDICT | changed/unchanged | evidence: path (+test) | gap if not DONE |
|---|---|---|---|---|
| M0-01 | DONE | unchanged | `contracts/loom/v1/project.document.schema.json` + `apps/studio/src/project/document.ts` (validate/canonicalize/parse/serialize/fingerprint); `src/contract/project-document.contract.test.ts` | |
| M0-02 | DONE | changed | `src/graph/ids.ts` `GRAPH_ID_RE`/`graphIdProblem`/`nextNodeId`/`nextEdgeId`/`pasteClipboard`; `validateProject` `node.id_format`/`edge.id_format`; `src/contract/graph-ids.contract.test.ts` | |
| M0-03 | DONE | unchanged | `src/project/document.ts` records `schema_version`+`compiler_semantics_version`, future-version refusal; `src/contract/project-document.contract.test.ts` | |
| M0-04 | DONE | unchanged | `src/project/migrate.ts` step registry (deep-clone, from->to+1, refuses future/no-path/malformed); `src/contract/project-document.contract.test.ts` | |
| M0-05 | DONE | unchanged | `GraphEdge.pipelineStages` canonical; `src/graph/migration.ts` folds `pipelineStagesByEdge`; `graph-serialization.contract.test.ts` + `graph-project.contract.test.ts` | |
| M0-06 | DONE | changed | `VcConfigV1` (VC depth/class/escape, trafficClassMap, arbitration) `src/graph/project.ts`; schema `$defs.vcConfig`; `src/contract/loom-vc-qos-v1.contract.test.ts` | |
| M0-07 | DONE | changed | `DomainsConfigV1` clocks/resets/powers/portAssignments + `EdgeDomainCrossingV1`; `src/graph/project.ts`; `src/contract/loom-domains-v1.contract.test.ts` | |
| M0-08 | DONE | changed | `ProjectAgent`/`AgentPort` roles/protocol/widths/capabilities/addressWindows; `src/graph/project.ts`; `src/contract/loom-agents-v1.contract.test.ts` | |
| M0-09 | DONE | changed | `Node.catalogRef` {catalogId,itemId,version,overrides,fallbackMetadata}; `src/graph/catalog.ts` `resolveCatalogReference`; `src/contract/loom-catalog-reference.contract.test.ts` | |
| M0-10 | DONE | changed | `FirewallConfig` access {defaultPolicy, rules{precedence,source,target,policy}}; `src/graph/project.ts`; `src/contract/loom-access-floorplan.contract.test.ts` | |
| M0-11 | DONE | changed | `Floorplan` {units,dieOutline,placements{locked,hierarchyId},keepouts,hierarchies} + `PhysicalEdge`; `src/contract/loom-access-floorplan.contract.test.ts` | |
| M0-12 | DONE | changed | `workload.phases` with communicationOps/tensorSizes/mappingRefs/timingHints; `src/graph/project.ts`; `src/contract/loom-workload-v1.contract.test.ts` | |
| M0-13 | DONE | changed | `TraceEventV1` cycle/metricFamily/trafficClass/node_id|edge_id/phaseId/runId; `src/graph/trace.ts`; `loom-trace-v1.contract.test.ts` | |
| M0-14 | DONE | changed | `RunSummaryV1` metrics{provenance,unsupported,estimated}+warnings; `src/graph/summary.ts`; `src/contract/loom-summary-v1.contract.test.ts` | |
| M0-15 | DONE | changed | `RunManifestV1` fingerprint/versions/engine/ui/backend/command/seed/inputs/artifact sha256; `src/graph/runManifest.ts`; `loom-run-manifest-v1.contract.test.ts` | |
| M0-16 | DONE | changed | `makeIssue` ProjectIssue + `ValidationIssue` same shape; all validators return it; `src/contract/loom-validation-issue-v1.contract.test.ts` | |
| M0-17 | DONE | changed | one `useGraphStore` doc holds graph/workload/firewall/access/floorplan/domains/agents; GraphLoom + authoring share it; `graph-store-ownership.contract.test.ts` | |
| M0-18 | DONE | changed | `src/pages/loom/data.ts` derived selectors (agentRows,domainsOf,expectedChannelLoad,loomPlan,…) consumed via `useMemo`; `loom-derivation.contract.test.ts` | |
| M0-19 | DONE | unchanged | `canonicalizeProject` fixed field order + `sortJsonKeys`; `fingerprintProject`; `src/contract/graph-serialization.contract.test.ts` | |
| M0-20 | DONE | changed | `apps/studio/fixtures/projects/{small-custom,mesh-8x8,multi-domain,floorplanned,workload-bound}.json` validated; `project-fixtures.contract.test.ts` | |
| M0-21 | DONE | changed | load→edit→save→reload semantic equality per fixture; `project-fixtures.contract.test.ts` + `loom-golden-projects.contract.test.ts` | |
| M0-22 | PARTIAL | changed | `PROVENANCE_STATES` `src/graph/provenance.ts` + `contracts/loom/v1/provenance.schema.json` `x-ui-rules`; `loom-provenance-v1.contract.test.ts` | vocabulary + documented UI rules exist; no proof every displayed result is tagged (summary/manifest carry it only). |
| M1-01 | DONE | changed | `src/graph/history.ts` `GraphCommand` apply/inverse; every command exercised in `graph-command-revert.contract.test.ts` + `graph-history-undo.contract.test.ts` | |
| M1-02 | DONE | changed | Ctrl+Z/Ctrl+Shift+Z via `src/graph/store.ts`; exact restore across node/edge/property; `graph-authoring-a11y.contract.test.tsx` + `graph-history-undo.contract.test.ts` | |
| M1-03 | DONE | unchanged | batch/paste/replace as one history step; `graph-command-revert.contract.test.ts` | |
| M1-04 | DONE | changed | `NodeEditor` pan/zoom-around-pointer/fit/reset (`src/pages/loom/authoring.tsx`); `graph-authoring-a11y.contract.test.tsx` | |
| M1-05 | DONE | changed | `NodeEditor` renders nodes+ports from `store.doc`, live update without reload; `graph-authoring-a11y.contract.test.tsx` | |
| M1-06 | DONE | changed | `NodeEditor` snap toggle + one `move_node` command; `graph-authoring-a11y.contract.test.tsx` | |
| M1-07 | DONE | changed | click/Shift/click/marquee select nodes+edges keeping inspector; `graph-authoring-a11y.contract.test.tsx` | |
| M1-08 | DONE | changed | `src/graph/selectionOps.ts` + GraphLoom rail/Ctrl+A/Escape; `src/contract/graph-selection-ops.contract.test.tsx` | |
| M1-09 | DONE | changed | delete confirm dialog lists affected edges then one `delete_nodes`; `graph-authoring-a11y.contract.test.tsx` | |
| M1-10 | DONE | unchanged | copy/paste remaps ids, offsets, one command; `graph-paste-component.contract.test.ts` + `graph-authoring-a11y.contract.test.tsx` | |
| M1-11 | DONE | unchanged | offset copy with fresh ids as one history entry (copy→paste); `graph-authoring-a11y.contract.test.tsx` + `graph-command-revert.contract.test.ts` | |
| M1-12 | PARTIAL | changed | `authoring.tsx` "Group alignment" aligns selected physical placements to anchor x/y; `workload-editor.contract.test.tsx` | topology multi-selection align left/right/top/bottom/center not implemented (physical-placement anchor align only). |
| M1-13 | NOT DONE | unchanged | no distribute tool found (`grep distribute` in `src/pages/loom` returns none) | no horizontal/vertical distribute action or test. |
| M1-14 | NOT DONE | unchanged | no minimap/viewport indicator in `GraphLoom.tsx`/`authoring.tsx` | minimap absent. |
| M1-15 | PARTIAL | unchanged | `GraphLoom` link mode + `NodeEditor` Wire link create edges; validator refuses oversubscribed/direction with reason | no true port-to-port drag/drop; compatibility not checked at pick time. |
| M1-16 | DONE | changed | `NodeEditor` edge select/inspect/delete with undo; `graph-authoring-a11y.contract.test.tsx` | |
| M1-17 | PARTIAL | unchanged | `src/graph/routing.ts` `manhattanAvoiding` used by `NodeEditor.routeEdge` | no test; obstacle avoidance not proven for normal/dense graph sizes. |
| M1-18 | PARTIAL | changed | `authoring.tsx` manual physical waypoints add + reset, persisted on `edge.physical.waypoints`; `workload-editor.contract.test.tsx` + `graph-project.contract.test.ts` | no per-waypoint move. |
| M1-19 | NOT DONE | unchanged | routing has only single-edge obstacle avoidance (`manhattanAvoiding`) | no stable-lane/crossing-cleanup pass. |
| M1-20 | DONE | changed | `buildMeshPreset(columns,rows,{endpointIndices,nodeRole,endpointRole})` valid+deterministic; `graph-project.contract.test.ts` "builds valid deterministic mesh presets" | |
| M1-21 | PARTIAL | changed | `buildPreset('torus-4x4')` adds explicit wrap links (`src/graph/presets.ts`) | no test proves the torus preset passes `validateProject`. |
| M1-22 | PARTIAL | changed | `buildPreset('ring-8')` generator exists (`src/graph/presets.ts`) | no ring size/direction options. |
| M1-23 | DONE | changed | `buildPreset('star-8')` hub(ports 7)/7 spokes valid; roles editable in `NodeEditor`; validated via `loadJson` in `graph-authoring-a11y.contract.test.tsx` | |
| M1-24 | PARTIAL | changed | `buildPreset('tree-15')` generator exists (`src/graph/presets.ts`) | no branch-factor/depth options. |
| M1-25 | DONE | changed | `buildPreset('srota-opt-16')` loads as normal graph; any edit clears `presetHint`→custom (`history.mutate`); `graph-edit-save-reload.contract.test.ts` | |
| M1-26 | PARTIAL | unchanged | `validateProject` reports unknown node/domain refs and port refs with `objectRef` | catalog-ref dangling refs not resolved (needs catalog context). |
| M1-27 | DONE | unchanged | duplicate node/edge ids + `edge.duplicate_directed_link`; `graph-serialization.contract.test.ts` | |
| M1-28 | DONE | changed | `src/graph/interfaceRole.ts` capability model; `node.ports_oversubscribed`/`node.interface_role`/`edge.direction_incompatible`; `graph-interface-direction.contract.test.ts` | |
| M1-29 | DONE | unchanged | `validateProject({requireConnected})` `graph.disconnected` with components+quickFix; adapter escalates; `graph-project.contract.test.ts` + `graph-paste-component.contract.test.ts` | |
| M1-30 | PARTIAL | unchanged | edit clears `presetHint`→custom; `supportsXYRouting` revalidates mesh for routing policy | no general revalidation of a Mesh/Torus claim after edits. |
| M1-31 | NOT DONE | unchanged | no topology search by id/label/role/catalog in the graph editor | search absent. |
| M1-32 | PARTIAL | changed | Ctrl+A/Escape (`GraphLoom`), Ctrl+Z/Ctrl+Shift+Z (`store.ts`), Enter/Space select (`NodeEditor`, `graph-authoring-a11y`) | delete/duplicate/copy/paste/fit/search shortcuts and discoverability absent. |
| M1-33 | NOT DONE | unchanged | no `onContextMenu`/context menus in `src/pages/loom` | context menus absent. |
| M1-34 | DONE | unchanged | `graph-edit-save-reload.contract.test.ts` (8x8 add→wire→edit→save/reload semantic equality) | |

## M2–M3

# Loom production-tracker re-score — M2 + M3

HEAD = c13f7ca2 (merge landed). Scored against committed code + contract tests. Desktop/Tauri clauses capped per rubric.

## M2-M3
DONE=19 PARTIAL=29 NOTDONE=5 CHANGED_FROM_AUDIT=39

| ID | NEW VERDICT | changed/unchanged | evidence: path[:symbol] (+test) | gap if not DONE |
| M2-01 | DONE | changed | apps/studio/src/graph/catalog.ts:BUILTIN_CATALOG_V1,validateLocalCatalog,parseLocalCatalog (+loom-catalog-store.contract.test.ts) | - |
| M2-02 | DONE | changed | catalog.ts:CatalogItemV1 vendor/family/version/class/clocks/resets/powers/ports(dataWidth,addressWidth,capabilities) (+loom-catalog-store) | - |
| M2-03 | PARTIAL | changed | catalog.ts router.generic-5p; tracks/t3-topology/dse/veritx_dse/model/ip_catalog.py concentrated-router | only one generic router; no radix/VC variants; stamp_ip_template refuses non-hbm3e |
| M2-04 | PARTIAL | changed | catalog.ts compute.generic; ip_catalog.py rcu-collective (gated router.rcu) | no configurable agent-port surface; templates are fixed |
| M2-05 | PARTIAL | changed | catalog.ts memory.hbm/ddr templates; ip_catalog.py hbm3e-memory (target port, address window at stamp) | DDR entry exposes no address window; no stamp/inspector for local templates |
| M2-06 | PARTIAL | changed | catalog.ts bridge.protocol-domain.generic (clk_a/clk_b, up/down ports); ip_catalog pcie-cxl-root/ucie-d2d (gated) | no port-compatibility metadata; conversion explicitly not implemented |
| M2-07 | PARTIAL | changed | catalog.ts peripheral.generic + dma.generic interface templates | no instantiation/stamp of these templates into a graph |
| M2-08 | PARTIAL | changed | catalog.ts:searchCatalog name/vendor/family/class/tags/protocol (+loom-catalog-store) | no IP-catalog UX; pages/loom/CatalogLoom.tsx searches engine agent kinds, not catalog items |
| M2-09 | PARTIAL | changed | gateway stamp /draft/ip-templates/stamp (apps/studio/tests/test_loom_p0_browser_acceptance.py F02, opt-in) appends agent group | no drag/stamp UI; test_f02_catalog_ui asserts 0 "stamp IP" buttons; not one undoable graph edit |
| M2-10 | NOT DONE | unchanged | - | no favorites/recent store or UI; CatalogLoom pin/compare is not recent/favorites |
| M2-11 | PARTIAL | changed | project.ts catalogRef.overrides+fallbackMetadata validated/serialized (+loom-catalog-reference) | no allowed-parameter override policy enforced at stamp/apply |
| M2-12 | PARTIAL | changed | catalog.ts parseLocalCatalog/validateLocalCatalog field-level messages (+loom-catalog-store) | validation only; no local add/store or import UI |
| M2-13 | PARTIAL | changed | catalog.ts serializeLocalCatalog deterministic + lossless re-import (+loom-catalog-store) | no user-entry creation/export UI or file path |
| M2-14 | PARTIAL | changed | catalog.ts resolveCatalogReference missing/outdated/resolved + warning + requiredAction (+loom-catalog-store) | not integrated into project load/UI; warning never displayed |
| M2-15 | PARTIAL | unchanged | project.ts ProjectAgent/AgentPort role/protocol/capabilities (+loom-agents-v1) | no unified agent inspector UI binding the model to a view |
| M2-16 | PARTIAL | unchanged | project.ts AgentPort protocol/dataWidth/addressWidth/capabilities/addressWindows validated (+loom-agents-v1) | no per-port editor UI for any of those fields |
| M2-17 | DONE | changed | project.ts:AgentCapability read/write/atomic/coherent/streaming + validCapabilities check (+loom-agents-v1 rejects unsupported/dup) | - |
| M2-18 | NOT DONE | unchanged | - | no protocol-compatibility validator or explicit-bridge requirement (CatalogLoom notes "no bridge registry exists") |
| M2-19 | PARTIAL | unchanged | project.ts addressWindows hex/range validation + overlap (+loom-agents-v1) | no hex-safe editor UI for base/size/permissions |
| M2-20 | PARTIAL | changed | project.ts node clock/resetDomain/powerDomain + domains.portAssignments; V5Declarations ClockDomainEditor (+v5-authoring) | reset assignment UI absent (V5 JSON only); no visual inherit/override indication |
| M2-21 | NOT DONE | unchanged | - | NodeTable batch VC runs N sequential store.run (not one undoable op); no agent/VC/clock template bulk-apply |
| M2-22 | PARTIAL | unchanged | authoring.tsx:NodeEditor (identity/ports/clock/vc); AgentsLoom group inspector | not one unified inspector with catalog-provenance/domains/routing/physical sections |
| M2-23 | PARTIAL | unchanged | authoring.tsx:NodeEditor edge panel width/stages/vcClass/src+dst ports + endpoints (+workload-editor) | timing/physical metadata edited in separate FloorplanPreview, not the edge inspector |
| M2-24 | NOT DONE | unchanged | - | no catalog parameter-range validator; catalogRef.overrides is opaque JSON, no catalog-backed messages |
| M2-25 | DONE | changed | project.ts target-window overlap at both windows, agent/port ids + hex ranges, severity=error (+loom-agents-v1) | - |
| M2-26 | PARTIAL | changed | gateway stamp + opt-in browser test test_f02_hbm3e_gateway_stamp... (HBM stamp→save→reload, provenance) | compute IP not stampable; no local-catalog stamp/validate flow; test is opt-in |
| M3-01 | DONE | changed | graph/routing.ts:previewXYPath; project.ts XY select/validate/serialize (+graph-project, workload-editor) | - |
| M3-02 | DONE | changed | routing.ts:previewWestFirstPath; project.ts refuses non-mesh (+graph-project, workload-editor) | - |
| M3-03 | DONE | changed | routing.ts:previewOddEvenPath; exhaustive 4x4 turn-model + refuses ring (+graph-project) | - |
| M3-04 | DONE | changed | project.ts:validateCustomRoutingRules (missing/invalid dst, adjacency, loops); authoring.tsx custom table (+graph-project, workload-editor) | - |
| M3-05 | DONE | changed | authoring.tsx FirewallEditor cell inspector: ordered hops, ports, VC class, provenance (+workload-editor XY/West/Even/custom) | - |
| M3-06 | PARTIAL | unchanged | authoring.tsx NodeEditor/NodeTable per-node vc depth + edge vcClass serialize (+graph-project) | "validate against catalog limits" unmet; test states catalog limits unspecified |
| M3-07 | PARTIAL | changed | project.ts vcConfig.arbitration policy enum validated/refused (round_robin/fixed_priority/weighted_round_robin) | no arbitration editor UI; no test for the unsupported-policy refusal |
| M3-08 | DONE | changed | authoring.tsx WorkloadEditor traffic-class→VC/QoS mapping + default; routing.ts:validateWorkloadRoutingCompatibility (+workload-editor, graph-project) | - |
| M3-09 | PARTIAL | changed | project.ts VirtualChannelV1.escape boolean validated; golden fixture carries escape:true | escape VC not visible in UI; not carried into run input/provenance |
| M3-10 | DONE | changed | components/V5Declarations.tsx:ClockDomainEditor sources/domains/freq/divider, assign agent groups, safe delete (+v5-authoring) | - |
| M3-11 | PARTIAL | changed | project.ts domains.resets polarity/asynchronous/clockDomainId validated + round-trip (+loom-domains-v1) | no structured reset editor; V5 reset_channels is a raw JSON field |
| M3-12 | PARTIAL | changed | project.ts domains.powers nominalVoltageV/canPowerOff validated + round-trip (+loom-domains-v1) | no power-domain editor UI; V5 power_domains raw JSON, refuses at COMPOSE |
| M3-13 | PARTIAL | unchanged | DomainsLoom clock-crossings derived from attachment×clock_domain; edges.domainCrossing policies validated (+loom-domains-v1) | no validator emits a result for an unpoliced clock crossing; UI label only |
| M3-14 | PARTIAL | changed | DomainsLoom power-crossings (+domains-authoring); edge.domainCrossing.power policies validated | no level-shift/isolation requirement enforcement; shown UNRESOLVED only |
| M3-15 | PARTIAL | unchanged | pages/loom/DomainsLoom census + crossing lists | no topology overlay: FabricCanvas OVERLAYS has no clock/power domain layer |
| M3-16 | PARTIAL | unchanged | authoring.tsx FirewallEditor matrix RW/RO/deny, keyed on node id | not virtualized; hard cap 12/24 per axis, so does not scale to large agent counts |
| M3-17 | DONE | changed | graph/firewall.ts:allowAllFirewallRules + FirewallEditor "Allow all" (+workload-editor one-command undo) | - |
| M3-18 | DONE | changed | firewall.ts:canonicalFirewall default deny + "Deny by default"; unconfigured cell shows DENY (+workload-editor) | - |
| M3-19 | DONE | changed | firewall.ts:setFirewallRow/setFirewallColumn + FirewallEditor bulk row/column, one command (+graph-project, workload-editor) | - |
| M3-20 | DONE | changed | FirewallEditor cell inspector: matched rule, src/dst, permission, precedence, routed path/hops/ports (+workload-editor) | - |
| M3-21 | DONE | changed | firewall.ts:inspectFirewallRules duplicate/conflict/invalid + unmatchable src/dst/self-pair (+graph-project, workload-editor) | - |
| M3-22 | DONE | changed | firewall.ts:canonicalFirewall deterministic sort; FirewallEditor view-state-free JSON (+graph-project, workload-editor) | - |
| M3-23 | NOT DONE | unchanged | - | AddressMapReadout (DesignViewV2Editor) is read-only; no sort/search/cross-probe to topology or access matrix |
| M3-24 | PARTIAL | changed | project.ts target-window overlap with agents/ranges/severity (+loom-agents-v1) | no address-hole or unmapped-initiator detection |
| M3-25 | DONE | changed | routing.ts:validateAllowedRouteReachability audits each allowed pair → route or precise error (+graph-project, workload-editor) | - |
| M3-26 | DONE | changed | routing.ts:validateWorkloadRoutingCompatibility traffic-class→VC vs route hops; blocks run intent (+graph-project, workload-editor) | - |
| M3-27 | PARTIAL | changed | constituents tested: cell→RW, route/VC inspect, deterministic firewall JSON, routing round-trip (+workload-editor) | no single save→reload→identical rule/path E2E test |

## M4–M5

## M4
DONE=0 PARTIAL=22 NOTDONE=12 CHANGED_FROM_AUDIT=22

## M5
DONE=23 PARTIAL=3 NOTDONE=3 CHANGED_FROM_AUDIT=25

Policy: HEAD's physical surface is a local web-authoring slice (`pages/loom/authoring.tsx:FloorplanPreview` + `graph/floorplan.ts`), which the code itself labels an abstract projection ("not the certified placement", heat "not congestion"). Tested web analogs are credited PARTIAL; rows needing DEF/OpenROAD/KLayout/Tauri/real engine have no analog and are NOT DONE. Workload editing is pure local software, so tested rows there reach DONE. Verified by running the 4 contract files (58/58 pass) and reading code.

| M4-01 | PARTIAL | changed | `graph/floorplan.ts:convertDieOutline`/`convertFloorplanIntent`; `authoring.tsx:FloorplanPreview` die unit select (test `workload-editor` "authors explicit die bounds with unit conversion...") | Web-only analog, not the desktop physical flow; conversion "between delay calculations" is code-only, untested. |
| M4-02 | PARTIAL | changed | `authoring.tsx:FloorplanPreview` die outline apply/clear with validation + undo via `set_floorplan` (test `workload-editor` die-bounds test) | Web analog; no Tauri/physical product surface. |
| M4-03 | PARTIAL | unchanged | `authoring.tsx:FloorplanPreview` rectangles from `floorplan.placements` (test `workload-editor` die-bounds test) | Authored local-graph rectangles, not certified placement; no topology cross-probe. |
| M4-04 | PARTIAL | changed | `authoring.tsx:FloorplanPreview` pointer move/resize, `snapPhysical`, one `set_floorplan` command (test `workload-editor` pointerDown/Up) | Web analog; no physical placement engine. |
| M4-05 | PARTIAL | changed | `authoring.tsx:FloorplanPreview` lock/unlock persisted; drag/resize blocked when locked (test `workload-editor` locked:true) | Web analog only. |
| M4-06 | PARTIAL | changed | `authoring.tsx` `gridStep` persisted per project, independent of canvas snap (test `workload-editor` "persists an independent physical snap grid...") | Web analog only. |
| M4-07 | PARTIAL | changed | `authoring.tsx:FloorplanPreview` Align X / Align Y to anchor with snap, one undo step (test `workload-editor` die-bounds anchor align) | Web analog only. |
| M4-08 | PARTIAL | changed | `authoring.tsx:FloorplanPreview` group Align X/Y skips locked, undo (test "aligns selected physical rectangles to shared anchors...") | Distribution not implemented; web analog only. |
| M4-09 | PARTIAL | changed | `authoring.tsx` unplaced-node bin + drag-into-die (test "drags unplaced graph nodes into the authored die...") | No hierarchy panel; web analog only. |
| M4-10 | PARTIAL | changed | `authoring.tsx` keepout add/remove; `graph/project.ts` validates intersection (test "authors, serializes, validates and removes physical keepout regions") | Authored intent, not a physical-tool blockage result. |
| M4-11 | PARTIAL | changed | `graph/project.ts` floorplan `hierarchies[]`+`hierarchyId` validation, cycle detect (test `loom-access-floorplan` "rejects cyclic floorplan hierarchy parent links") | No region-constraint authoring/UI or region-violation view; schema-level grouping only. |
| M4-12 | PARTIAL | changed | `graph/floorplan.ts:routeAllManhattanPhysicalEdges` deterministic (test "derives deterministic Manhattan physical link previews and unresolved...") | Centerline preview; no obstacle-avoiding physical router or signoff. |
| M4-13 | PARTIAL | changed | edge `physical.waypoints` add/reset, `authoring.tsx` (test "authors persisted manual physical waypoints and resets an edge...") | Preview routing only. |
| M4-14 | PARTIAL | changed | `graph/project.ts` `PhysicalEdge.layer`/`routeClass` validated + round-trip (test `loom-access-floorplan` physical round-trip) | No wire-pitch project parameter; no assumption labeling. |
| M4-15 | PARTIAL | changed | `graph/floorplan.ts` route `length`; recomputed after placement edit (test "renders physical routes... recomputes lengths after a placement edit") | Preview geometry, not a routed/parasitic wire length. |
| M4-16 | PARTIAL | changed | `graph/floorplan.ts:estimateManhattanRouteDelayPs` explicit inputs, tagged Estimated (test `workload-editor` "Estimated delay 23 ps") | Local linear estimate; not backed by an external physical engine. |
| M4-17 | PARTIAL | changed | `floorplan.timingConstraints` target delay + Estimated PASS/FAIL (test "Estimated FAIL against 22 ps target"; `graph-project.contract.test` timingConstraints) | Estimate-based; no static timing analysis. |
| M4-18 | NOT DONE | unchanged | no pipeline-suggestion function anywhere under `apps/studio/src` | No timing-model suggestion surface. |
| M4-19 | NOT DONE | unchanged | `edge.pipelineStages` editable in `authoring.tsx:NodeEditor` only; no suggestion to accept | No suggest→apply path. |
| M4-20 | NOT DONE | unchanged | no routed-occupancy estimator; `FloorplanLoom.tsx` OVERLAYS congestion=unavailable; authoring heat is canvas distance "not congestion" | Estimator absent. |
| M4-21 | NOT DONE | unchanged | no congestion heatmap overlay | Surface absent. |
| M4-22 | NOT DONE | unchanged | no pipeline-count edge overlay | Surface absent. |
| M4-23 | NOT DONE | changed | no physical-view clock/power domain grouping; `TopologyPlanes.tsx` has a domain table only | No analog in FloorplanPreview; prior PARTIAL unsupported on HEAD. |
| M4-24 | PARTIAL | changed | shared `useLoomSelection` + `?sel=` carry across views (`pages/loom/index.tsx`); `FloorplanLoom` link selection | FloorplanPreview explicitly does not cross-probe certified topology. |
| M4-25 | NOT DONE | unchanged | no DEF parser; capability registry reports physical.signoff NOT_IMPLEMENTED "No PDK, LEF/DEF, RC model" (python `test_f08_...`) | Surface absent. |
| M4-26 | NOT DONE | unchanged | no DEF writer | Surface absent. |
| M4-27 | NOT DONE | unchanged | no external physical-tool adapter interface | Surface absent. |
| M4-28 | NOT DONE | unchanged | no OpenROAD invocation | Surface absent. |
| M4-29 | NOT DONE | unchanged | no KLayout handoff | Surface absent. |
| M4-30 | PARTIAL | changed | `graph/project.ts` validates out-of-die bounds, placement overlap, keepout intersect, non-positive dims (test `loom-access-floorplan` bounds/overlap paths) | Authored-intent validation, not signoff DRC. |
| M4-31 | PARTIAL | changed | `graph/floorplan.ts` routed/unresolved + error per edge; FloorplanPreview counts (test deterministic preview "Missing physical placement for n2") | Preview completeness only. |
| M4-32 | PARTIAL | changed | `authoring.tsx` "Export PNG" → `graph/io.ts:exportSvgPng` browser download | Not Tauri-backed; exports abstract projection, not overlays/legend; untested. |
| M4-33 | NOT DONE | unchanged | no floorplan SVG export | Surface absent. |
| M4-34 | PARTIAL | changed | place/route/timing/save-reload pieces implemented + tested | Congestion inspect and pipeline suggestion absent; no executed end-to-end flow. |
| M5-01 | DONE | changed | `authoring.tsx:WorkloadEditor` → `set_workload`; `graph/workload.ts` validation (test `workload-editor` "writes edited workload fields through validated set_workload history actions") | |
| M5-02 | DONE | changed | `authoring.tsx` model family/name fields (test "records Dense/MoE/custom family and model name as descriptive metadata only") | |
| M5-03 | DONE | changed | `paramsB`/`hiddenSize`/`layerCount` optional + validated (test "keeps unknown model-shape metadata optional and validates supplied ranges") | |
| M5-04 | DONE | changed | `seqLen`/`batch` inputs; `graph/workload.ts` positive-int validation; phase `tokens`/`batch` (test import rejects "$.seqLen: must be a number"; `phases[1].batch` issue) | |
| M5-05 | DONE | changed | precision select fp16/fp8/int8/bf16 (test "records only supported normalized precision enums without changing other workload data") | |
| M5-06 | DONE | changed | per-phase `tp/ep/pp/dp`; `requiredRankCount` vs nodeCount (test "validates TP/EP product demand against graph and explicitly mapped node seats") | |
| M5-07 | DONE | changed | `validateWorkload` "parallelism needs N nodes but the graph has M" + mapped-seat check (tests `workload-editor` + `workload-fixtures` blocked-capacity, runIntent null) | |
| M5-08 | DONE | changed | `WorkloadEditor` phase rows add/reorder/remove/name/kind/start/duration (test "creates, edits, reorders, removes and serializes authored phases with cycle timing") | |
| M5-09 | DONE | changed | `authoring.tsx:SimPlayback` + `graph/trace.ts:buildMockTrace` consume workload phases, no phase literals (test "labels mock playback phases only from explicit project start/duration boundaries") | |
| M5-10 | DONE | changed | `WorkloadEditor` op kind/dimension/payload/customName (test "edits collective and custom communication kind, dimension, payload and name") | |
| M5-11 | DONE | changed | point-to-point source/target + payload (test "authors point-to-point source/target references and payload as a distinct operation") | |
| M5-12 | DONE | changed | op `trafficClass` + `trafficClassMappings`→vcClass/qosClass (tests "maps operation traffic classes to authored VC/QoS..."; p2p VC-conflict run-intent block) | |
| M5-13 | DONE | changed | STARTER dense example, assumptions labeled (test "loads editable dense example assumptions and labels the unstated inputs") | |
| M5-14 | DONE | changed | `graph/workload.ts:moeWorkloadSkeleton` TP/EP empty slots (test "inserts a TP/EP MoE skeleton without assuming collective or dispatch/combine semantics") | |
| M5-15 | DONE | changed | `emptyWorkload` (test "starts an empty custom workload without hidden phases, operations, model shape or mappings") | |
| M5-16 | DONE | changed | rank mapping table + filter (tests "edits rank role/node IDs and round-trips..."; "search-filters rank mappings by rank, role, or graph node") | |
| M5-17 | DONE | changed | rank overlay SVG on nodes + cross-probe (test "renders rank labels on authored nodes and cross-probes node selection to a mapping row") | |
| M5-18 | PARTIAL | changed | `autoRankMappings` + "Auto-map in graph order" (test "auto-maps ranks deterministically in graph order as one undoable operation") | No chosen policy: single fixed graph-order assignment, no policy selection. |
| M5-19 | DONE | changed | reassign rank via node select + revalidation (test "manually reassigns a rank to a graph node and immediately revalidates mapping") | |
| M5-20 | DONE | changed | `rankConstraints` pinned/allowedNodeIds/requiredRole (test "edits and validates pinned, allowed-node, and required-role rank constraints") | |
| M5-21 | NOT DONE | unchanged | `autoRankMappings` is graph order, not distance-aware; no objective before/after | No topology-aware heuristic. |
| M5-22 | NOT DONE | unchanged | no workload scenario/variant clone | Surface absent. |
| M5-23 | NOT DONE | unchanged | no parameter sweep definition | Surface absent. |
| M5-24 | DONE | changed | `parseWorkloadJson` localized errors, no coercion (test "imports valid workload JSON and rejects localized schema errors without coercion") | |
| M5-25 | DONE | changed | `serializeWorkloadJson` with `workloadSchemaVersion:1` (test "exports deterministic versioned workload JSON including rank mappings...") | |
| M5-26 | PARTIAL | unchanged | `WorkloadEditor` "Run status: BLOCKED" + routing preflight; `CapabilityLoom` UNSUPPORTED/BLOCKED registry; test "validates TP/EP..." shows BLOCKED | No explicit per workload×backend unsupported classification; only a local block status. |
| M5-27 | DONE | changed | `WorkloadEditor` "Workload summary" shape/parallelism/phases/declared bytes/mapped ranks (test "summarizes canonical workload shape, phases, declared bytes and mapping completeness") | |
| M5-28 | DONE | changed | `fixtures/workloads/{dense-supported,moe-blocked-capacity,custom-invalid}.json` (test `workload-fixtures.contract.test.ts`) | |
| M5-29 | PARTIAL | changed | `buildWorkloadRunIntent` + "Export validated run intent" (explicit cycles, schema v1; `workload-fixtures` determinism test) | Intent file only ("not a backend RunInput"); no executed create→map→run-input browser E2E. |

## M6–M7

## M6-M7
DONE=3 PARTIAL=38 NOTDONE=25 CHANGED_FROM_AUDIT=25

Rule applied: HEAD has no Tauri/loom-sim sidecar (repo-wide grep for tauri/child_process/spawn empty; `engineProtocol.ts` header: "future loom-sim sidecar ... this web-only build can spawn the engine"). Engine/desktop-dependent clauses are capped at PARTIAL. DONE is only granted where a self-contained clause is implemented and proven by a committed test on the surface the clause names.

| ID | NEW VERDICT | CHANGE | EVIDENCE | GAP |
| M6-01 | PARTIAL | changed | graph/engineProtocol.ts: versioned EngineRequest/EngineRunResponse(artifacts,exitCode,provenance); engineProtocol.contract.test.ts. | No engine executes the protocol; file calls itself "future loom-sim" types only. |
| M6-02 | PARTIAL | changed | engineProtocol.ts:assessEngineHealth → compatible/incompatible/unavailable; engineProtocol.contract.test.ts "distinguishes compatible, incompatible, and unavailable". | No UI shows health before a run; nothing to handshake. |
| M6-03 | NOT DONE / NOT PROVEN | unchanged | No Tauri/child_process/spawn in repo; engineProtocol.ts header states web build cannot spawn. | Needs desktop Tauri versioned-binary spawn capturing PID/state. |
| M6-04 | NOT DONE / NOT PROVEN | unchanged | engineProtocol.ts declares an EngineCancelRequest type only. | No run to cancel; no child-process/temp-state cleanup. |
| M6-05 | PARTIAL | changed | graph/runState.ts: 'timed-out' state + required error reason; runState.contract.test.ts "requires actionable failure reasons". | No hung-engine detection and no preserved logs; state unwired. |
| M6-06 | NOT DONE / NOT PROVEN | unchanged | No stdout/stderr capture or log stream in graph/ or pages/loom. | Needs streaming logs retained with the run bundle. |
| M6-07 | PARTIAL | unchanged | runState.ts TRANSITIONS queued→preparing→running→parsing→completed/failed/cancelled/timed-out + parseRunState; runState.contract.test.ts. | Not wired to engine or durable run store. |
| M6-08 | NOT DONE / NOT PROVEN | unchanged | runManifest.ts:describeRunArtifact hashes bytes but "performs no file I/O". | No per-run artifact directory (inputs/trace/summary/logs/manifest). |
| M6-09 | PARTIAL | changed | engineProtocol.ts:fingerprintInputs/canonicalJson + runManifest.createRunManifest projectFingerprint; engineProtocol.contract.test.ts. | Hashes not written to a real run manifest nor shown in provenance UI. |
| M6-10 | PARTIAL | changed | trace.ts:buildMockTrace origin 'MOCK'; authoring.tsx:SimPlayback labels MOCK; trace.contract.test.ts + MockPlayback.contract.test.tsx. | Produces no trace/summary files; not gated as engine-unavailable fallback. |
| M6-11 | PARTIAL | unchanged | Gateway qualification (api/types.ts EngineQualification/QualificationView; api.qualification/capabilities in Trust page). | No local backend registry declaring topology/workload/metric features + refusals. |
| M6-12 | PARTIAL | unchanged | Gateway backend path/fixtures (api/types.ts backend+qualification; fixtures BookSim labels). | No local BookSim adapter generating/parsing inputs with backend/version provenance. |
| M6-13 | NOT DONE / NOT PROVEN | unchanged | No ASTRA/collective adapter in apps/studio/src (only gateway types/fixture labels). | Needs external collective adapter with explicit unsupported cases. |
| M6-14 | NOT DONE / NOT PROVEN | unchanged | graph/adapter.ts is a compiler adapter (LOOM_COMPILER_ADAPTER_UNSUPPORTED), not an engine adapter. | Needs registrable capability-check/command-builder/result-parser interface. |
| M6-15 | PARTIAL | changed | traceParser.ts:parseTraceStream/decodeTraceStream incremental, line errors; traceParser.contract.test.ts 10k stream + corrupt line 10001. | Streams the mock/import frame shape, not the committed trace-event v1 JSONL; no engine trace. |
| M6-16 | DONE | changed | traceParser.ts:TraceIndex byCycle/byNode/byEdge/byMetric + onProgress; traceParser.contract.test.ts (4096-frame index, 10k progress); MockPlayback progress test. |  |
| M6-17 | DONE | changed | traceParser.ts:parseTraceLines unknownReferences error|warn deletes foreign ids; traceParser.contract.test.ts; MockPlayback.contract.test.tsx "refuses foreign object IDs". |  |
| M6-18 | DONE | changed | traceParser.ts strict cycle monotonicity + finite/non-negative metric checks with TraceParseError.line; traceParser.contract.test.ts asserts line 2. |  |
| M6-19 | PARTIAL | changed | authoring.tsx:SimPlayback range scrubber; MockPlayback.contract.test.tsx seek updates values. | Mock/user-provided trace only; no engine cycle/time artifact. |
| M6-20 | PARTIAL | changed | authoring.tsx:SimPlayback Play/Pause/Step + speed; MockPlayback.contract.test.tsx 2× timing, pause, inspector in sync. | Mock/user trace only; no engine-run playback. |
| M6-21 | PARTIAL | changed | trace.ts:buildMockTrace phase from workload.phases startCycle/durationCycles; authoring.tsx; MockPlayback.contract.test.tsx cycles 0/100/200. | Label derived for mock trace only; no engine-trace alignment. |
| M6-22 | PARTIAL | changed | authoring.tsx:SimPlayback edge bars + auto/fixed scale + '—' missing; MockPlayback.contract.test.tsx auto 0–40, missing bar. | Bars, not a topology heat overlay; MOCK/unit-unverified values only. |
| M6-23 | PARTIAL | changed | authoring.tsx:SimPlayback stalls metric selectable + edge/node inspector; MockPlayback.contract.test.tsx. | Mock/user values; no backend stall provenance. |
| M6-24 | PARTIAL | unchanged | SimulationLoom.tsx "Unavailable readouts"/"Latency breakdown" ExtensionPoint; authoring.tsx note queue latency has no per-cycle artifact. | Backend never provides it; no queue-latency display path. |
| M6-25 | NOT DONE / NOT PROVEN | unchanged | authoring.tsx:SimPlayback states buffer figures "not shown". | No buffer utilization selectable by router/VC. |
| M6-26 | NOT DONE / NOT PROVEN | unchanged | authoring.tsx:SimPlayback states router power "not shown". | No power metric with backend provenance/units/Estimated label. |
| M6-27 | NOT DONE / NOT PROVEN | unchanged | No hop-count histogram/table in graph/summary.ts or pages/loom. | Needs summary hop distribution with sample count + backend provenance. |
| M6-28 | NOT DONE / NOT PROVEN | unchanged | No traffic-class filter in authoring.tsx or graph/. | Needs metric filtering by traffic class without mutating the run. |
| M6-29 | PARTIAL | changed | authoring.tsx:SimPlayback Edge/Node metric inspector current/min/max/avg + source; MockPlayback.contract.test.tsx. | Provenance is MOCK or USER-PROVIDED (unverified); no backend run. |
| M6-30 | PARTIAL | changed | trace.ts:topCongested; authoring.tsx Top congested buttons select edge; MockPlayback.contract.test.tsx. | Fixed top-5, no topology centering, no backend provenance. |
| M6-31 | PARTIAL | changed | authoring.tsx:SimPlayback Auto/Fixed scale, fixed max, units, '—'; MockPlayback.contract.test.tsx auto→fixed. | Component-local, not preserved per view; MOCK/unverified units. |
| M6-32 | PARTIAL | unchanged | RunHistoryPanel.tsx + runHistory.ts search/freshness; runHistory.contract.test.ts + runHistoryPanel.contract.test.tsx; wired in SimulationLoom. | Composite project/workload fingerprint equivalence to gateway design_hash unverified. |
| M6-33 | NOT DONE / NOT PROVEN | unchanged | SimulationLoom.tsx:RunComparison defaults to two evaluated runs; no baseline pinning. | No pin-baseline action/state. |
| M6-34 | PARTIAL | changed | SimulationLoom.tsx:RunComparison calls api.compare, renders Δ + compatibility.reasons, inputs separate from outputs. | No percent deltas; gateway pair, not a pinned loom-sim baseline. |
| M6-35 | NOT DONE / NOT PROVEN | unchanged | No per-edge/node metric-delta topology overlay. | Needs diff heatmap between compatible runs. |
| M6-36 | PARTIAL | changed | compareInputs.ts:compareRecordedRunInputs + compareInputs.contract.test.ts; rendered in SimulationLoom RunComparison. | Only recorded gateway fields (revision/hash/backend/workload/NoC); no mapping/authored inputs. |
| M6-37 | NOT DONE / NOT PROVEN | unchanged | Only exportProjectJson (project.json) in graph/io.ts; no CSV export of metrics. | Needs CSV with run/object/metric/cycle/units/provenance. |
| M6-38 | PARTIAL | unchanged | RunArtifactVerify/verifyRun verifies; only project.json export exists (graph/io.ts). | No export of exact raw run trace/summary artifacts. |
| M6-39 | PARTIAL | unchanged | runState.ts failed state requires error reason; ProblemsPanel surfaces integrity failures. | No engine crash handling/logs; nothing produces a crash. |
| M6-40 | PARTIAL | changed | traceParser.ts stops with exact line; onFrame keeps valid prefix; traceParser.contract.test.ts; MockPlayback corrupt test; e2e F22 test_loom_p0_browser_acceptance.py. | Retains valid prefix frames, not durable prior run artifacts. |
| M6-41 | NOT DONE / NOT PROVEN | unchanged | No filesystem writes in graph/; describeRunArtifact does no I/O. | Needs disk-full handling with actionable error, no false completion. |
| M6-42 | NOT DONE / NOT PROVEN | unchanged | No engine; SimulationLoom reads gateway runs; playback is MOCK/user trace. | Needs real supported backend launch → trace/summary → playback. |
| M6-43 | NOT DONE / NOT PROVEN | unchanged | SimPlayback is always-available "Mock playback (beta)", not gated on engine health; e2e F12 not closed. | Needs engine-unavailable detection then explicit mock opt-in. |
| M7-01 | PARTIAL | unchanged | ProblemsPanel.tsx + data.ts:problemsOf aggregates preflight/integrity/requirements/conservation/deadlock/certificate/staleness; loom-derivation.contract.test.ts. | Not global; no runtime/compatibility/physical-issue sources. |
| M7-02 | PARTIAL | unchanged | ProblemsPanel.tsx renders a Link to /loom/<view> per problem.view. | No referenced-object selection/cross-probe (node/edge/rule/phase). |
| M7-03 | PARTIAL | changed | data.ts:filterProblems(severity + query over id/source/title/detail); ProblemsPanel.tsx severity select + search; loom-derivation.contract.test.ts. | No validator/backend code taxonomy; no selection-preservation component test. |
| M7-04 | NOT DONE / NOT PROVEN | unchanged | validation-issue.schema.json requires quickFix.safe=true, but no producer/executor sets quickFix (loom-validation-issue-v1 test asserts undefined). | No undoable quick-fix commands. |
| M7-05 | PARTIAL | unchanged | problemsOf aggregates several gateway verdicts into one panel (data.ts). | No single run-all over schema/graph/catalog/domains/access/physical/workload/backend. |
| M7-06 | PARTIAL | unchanged | Run history/integrity views exist; no log viewer in pages/loom. | No structured log viewer filterable by run/component/severity. |
| M7-07 | NOT DONE / NOT PROVEN | unchanged | No structured log records anywhere. | Needs logs referencing run/node/edge with cross-probe. |
| M7-08 | PARTIAL | unchanged | runManifest.ts: engine{name,version} + uiVersion; loom-run-manifest-v1.contract.test.ts. | No manifest created at runtime; no exported support bundle. |
| M7-09 | PARTIAL | unchanged | createRunManifest SHA-256 projectFingerprint; loom-run-manifest-v1.contract.test.ts; engineProtocol fingerprintInputs. | Not persisted to a real run; UI shows gateway design_hash, not this fingerprint. |
| M7-10 | PARTIAL | changed | runManifest.ts command:string[] + inputs; serializeRunManifest keeps argv separate (no shell interpolation); loom-run-manifest-v1.contract.test.ts. | No executed engine command/config recorded or sanitized at runtime. |
| M7-11 | PARTIAL | changed | runManifest.ts seed number|null validated/serialized; loom-run-manifest-v1.contract.test.ts. | Seed not persisted from a run and not replayable. |
| M7-12 | NOT DONE / NOT PROVEN | unchanged | e2e test_loom_p0_browser_acceptance.py::test_f15 asserts no replay offered/requested without a stored run. | No replay from stored inputs/backend/seed with version-mismatch warning. |
| M7-13 | NOT DONE / NOT PROVEN | unchanged | No clone-run-as-scenario path. | Needs stored run inputs seeding an editable scenario without mutating artifacts. |
| M7-14 | PARTIAL | unchanged | semanticDiff.ts:semanticProjectDiff node/edge + metadata (domains/access/floorplan/workload) by stable id; semanticDiff.contract.test.ts. | Helper has no UI; not wired to a comparison view. |
| M7-15 | PARTIAL | changed | compareInputs.ts + SimulationLoom.tsx RunComparison separate input differences from output metrics; compareInputs.contract.test.ts. | No manifest/environment/version/seed diff. |
| M7-16 | NOT DONE / NOT PROVEN | unchanged | No determinism indicator in manifest or run UI. | Needs UI stating determinism and why. |
| M7-17 | NOT DONE / NOT PROVEN | unchanged | No support-bundle exporter in repo. | Needs project snapshot + manifest + summary + logs (+trace) with redaction. |
| M7-18 | NOT DONE / NOT PROVEN | unchanged | No copy-diagnostics action. | Needs one action copying versions/health/fingerprint/latest run status. |
| M7-19 | PARTIAL | changed | engineProtocol.ts:assessEngineHealth incompatible branch with expected/actual; engineProtocol.contract.test.ts. | Nothing blocks a run before spawn (no engine/spawn path). |
| M7-20 | PARTIAL | unchanged | runHistory.ts:runFingerprintFreshness older/current/unknown; RunHistoryPanel.tsx shows; runHistory[Panel].contract.test.(ts|tsx). | Web gateway design_hash, not tracker composite fingerprint; no live API integration test. |
| M7-21 | PARTIAL | unchanged | RunArtifactVerify.tsx + api.verifyRun (gateway bundle); RunArtifactVerify.contract.test.tsx; engineProtocol.verifySha256. | Gateway bundle only; user/local trace/summary/manifest hashes not verified. |
| M7-22 | NOT DONE / NOT PROVEN | unchanged | No golden replay fixture/test. | Needs known fixture replay matching expected artifact fingerprints. |
| M7-23 | NOT DONE / NOT PROVEN | unchanged | e2e F15 blocks replay; no fix→rerun→compare flow. | Needs invalid rule → ProblemsPanel → fix → rerun → compare with provenance. |

## M8–M9

# Loom re-score — M8 (file-system resilience / autosave / crash recovery / offline / export) and M9 (performance / UX)

HEAD = c13f7ca2. Baseline = docs/reports/LOOM-PRODUCTION-TRACKER-AUDIT.md (scored before the merge).
Rubric applied strictly: the workbook targets a DESKTOP/Tauri product; the web Studio is an analog, so web-only rows cap at PARTIAL. Performance rows require measured budgets, not structural intent.

## M8
DONE=0 PARTIAL=9 NOTDONE=16 CHANGED_FROM_AUDIT=5

| ID | NEW VERDICT | changed/unchanged | evidence | gap |
|---|---|---|---|---|
| M8-01 | PARTIAL | changed | apps/studio/src/graph/io.ts (web-only export central); graph/history.ts GraphCommand union; store.ts typed API/error | No Tauri command surface; settings/license/updater commands and centralized cross-command error mapping absent |
| M8-02 | NOT DONE | unchanged | apps/studio/src/graph/store.ts KEY `loom-graph-autosave-v1` scoped per project only | No documented per-project workspace locations for project/autosaves/runs/caches/exports |
| M8-03 | PARTIAL | changed | GraphLoom.tsx `load project.json` + project/document.ts parseProjectDocument (migrate+validate); contract/project-import-safety.contract.test.tsx | Browser file input, not a Tauri picker; migration is applied silently (no migration report UI) |
| M8-04 | PARTIAL | changed | graph/io.ts exportProjectJson + project/document.ts serializeProjectDocument (canonical); graph-authoring-flow.contract.test.tsx downloads a Blob | No atomic real-file write; dirty state not gated on save success (store autosaves eagerly to localStorage) |
| M8-05 | NOT DONE | unchanged | none | No Save As; no artifact-ownership handling |
| M8-06 | NOT DONE | unchanged | none | No temp-file write + rename; browser download only |
| M8-07 | PARTIAL | unchanged | graph/store.ts changed()/persist() 500ms debounce; store.offline.contract.test.tsx "keeps one latest autosave snapshot" | Synchronous localStorage snapshot, not file autosave; non-blocking/crash durability unproven |
| M8-08 | NOT DONE | unchanged | graph/store.ts initialize() silently loads the localStorage snapshot | No newer/source comparison; no preview/restore/discard prompt |
| M8-09 | NOT DONE | unchanged | store.offline.contract.test.tsx asserts exactly one autosave key exists | Single latest snapshot; no bounded rolling save history or restore semantics |
| M8-10 | NOT DONE | unchanged | none | No disk-change detection with reload/keep-current/compare |
| M8-11 | NOT DONE | unchanged | studio.tsx ACTIVE_PROJECT_KEY only | No recent-projects list with path/name/last-opened or missing-file handling |
| M8-12 | NOT DONE | unchanged | none | No drag/drop project open |
| M8-13 | PARTIAL | unchanged | graph/io.ts download() central web save; exportProjectJson/exportSvgPng/nodesToCsv | Browser download, not shell-owned; no SV/support export; PNG path uses a data URL |
| M8-14 | PARTIAL | changed | graph/io.ts nodesToCsv; authoring.tsx NodeTable:744 download('nodes.csv','text/csv') | Browser download not Tauri; no cancellation/error reporting; no matrix/run CSVs |
| M8-15 | NOT DONE | unchanged | graph/io.ts exportSvgPng: `img.src = data:image/svg+xml…` then canvas.toBlob download | Acceptance forbids browser data-URL hacks; no Tauri byte save |
| M8-16 | NOT DONE | unchanged | none | No SVG export (exportSvgPng emits PNG) |
| M8-17 | NOT DONE | unchanged | graph/engineProtocol.ts v1 boundary types explicitly for a "future loom-sim sidecar" | No versioned SV generator hook; no unsupported-generator reporting |
| M8-18 | NOT DONE | unchanged | none | No portable bundle (project + catalog overrides + selected run artifacts + manifest) |
| M8-19 | NOT DONE | unchanged | none | No bundle import/isolated workspace/hash validation |
| M8-20 | NOT DONE | unchanged | App.tsx theme is useState (not persisted); studio.tsx persists only ACTIVE_PROJECT_KEY | No settings store for theme/recent paths/engine/perf-preferences/telemetry |
| M8-21 | NOT DONE | unchanged | none | No engine binary selection or immediate health/version validation |
| M8-22 | PARTIAL | unchanged | graph/store.offline.contract.test.tsx "validates, edits, serializes, and reloads a graph without fetch" | localStorage local-only; catalog/offline app startup and disconnected runtime untested |
| M8-23 | NOT DONE | unchanged | graph/provenance.ts is a vocabulary only; no local engine | No local-engine run; no local-mode provenance |
| M8-24 | PARTIAL | unchanged | studio.tsx ACTIVE_PROJECT_KEY; App.tsx staleProject guard; contract/app-navigation.contract.test.ts | Persists active project id only; canvas view/selection not persisted; no stale-ID crash test |
| M8-25 | PARTIAL | changed | tests/test_loom_p0_browser_acceptance.py::test_f16_browser_restart_restores_local_graph_autosave_only | Browser-restart localStorage recovery only; no abrupt process kill, recovery prompt or validate+save; source not writable |

## M9
DONE=0 PARTIAL=16 NOTDONE=13 CHANGED_FROM_AUDIT=7

| ID | NEW VERDICT | changed/unchanged | evidence | gap |
|---|---|---|---|---|
| M9-01 | NOT DONE | unchanged | docs/reports/LOOM-M9-M11-performance-budgets.md self-declares "proposal; not a test result" and does not close M9-01 | No approved budgets and no measurements collected |
| M9-02 | PARTIAL | changed | authoring.tsx NodeTable:744 (PAGE=40 paginated, maxHeight scroll) | Pagination, not virtualization; no 256+ row smooth-scroll/edit measurement |
| M9-03 | NOT DONE | unchanged | AccessLoom.tsx:272 renders one `<rect>` per matrix cell in SVG; FirewallEditor caps 24×24 | No visible-cell-only rendering; no virtualized matrix at 10k cells |
| M9-04 | NOT DONE | unchanged | none (all heat drawn via SVG fills) | No canvas/WebGL heat path |
| M9-05 | NOT DONE | unchanged | none | No spatial index; hit-testing/viewport scans all nodes per event |
| M9-06 | PARTIAL | changed | GraphLoom.tsx drag uses dragPreview ref, commits on mouseup; store.ts 500ms autosave debounce; validation is useMemo(doc) | No explicit throttle/debounce utility; not measured that edit/drag avoids full validation |
| M9-07 | NOT DONE | unchanged | graph/traceParser.ts indexes the full stream; no windowing in SimPlayback | No time/object slice materialization for playback/inspection |
| M9-08 | NOT DONE | unchanged | none | No trace-cache memory limit/eviction or diagnostic observability |
| M9-09 | PARTIAL | changed | e2e/graph-history.spec.ts F18; test_loom_p0_browser_acceptance.py::test_f18… records load/edit wall time | Probe asserts "no acceptance budget"; no zoom/playback; recorded times not against budgets |
| M9-10 | NOT DONE | unchanged | test_f18 comment: firewall caps 24×24 → 552 cells, "not the required 10k" | No 10k-cell matrix and no batch-edit benchmark |
| M9-11 | NOT DONE | unchanged | graph/traceParser.contract.test.ts 10k-frame correctness/progress only | No seek/playback/parser memory or throughput benchmark |
| M9-12 | PARTIAL | unchanged | App.tsx Shell/NAV_GROUPS + contract/app-navigation.contract.test.ts; pages/loom/index.tsx Panes/status | Web shell only; "all production views one pattern, no duplicated project state controls" unproven |
| M9-13 | PARTIAL | changed | authoring.tsx NodeEditor/FirewallEditor/WorkloadEditor inspectors built on parts.tsx RailSection/Kv | No shared inspector component/test proving consistent spacing, sections, errors |
| M9-14 | NOT DONE | unchanged | none | No command palette |
| M9-15 | NOT DONE | unchanged | authoring.tsx NodeTable filter; runHistory search (page-local) | No global object search across nodes/edges/agents/domains/phases/runs with navigation |
| M9-16 | PARTIAL | unchanged | GraphLoom.tsx empty-state + graph-authoring-flow.contract.test.tsx "actionable empty-node state"; parts.tsx ExtensionPoint | Not every major view; no exhaustive audit |
| M9-17 | PARTIAL | unchanged | studio.tsx JobProgress; AccessLoom "counting packets…" role=status; traceParser progress callbacks | Cancellable progress for engine runs/large saves not proven |
| M9-18 | PARTIAL | unchanged | GraphLoom ApplyPanel error role=alert; offline.tsx "Retry live gateway" | Retry / open-logs / fix-setting recovery actions not consistently present |
| M9-19 | PARTIAL | unchanged | src/styles.css :root / [data-theme='light'] tokens + :focus-visible outline; contrast comments | No test/concrete proof of consistent focus/selection states across views |
| M9-20 | PARTIAL | unchanged | src/styles.css [data-theme='dark'] token block parallel to light | No parity test; "all views legible" unproven |
| M9-21 | NOT DONE | unchanged | none | No first-run onboarding or permanently-dismissable state |
| M9-22 | PARTIAL | changed | fixtures/projects/*.project.json + contract/loom-sample-projects.contract.test.ts (parseProject, no network) | Web-only fixture parse; workload sample is authored input, not a real simulation; no onboarding entry |
| M9-23 | PARTIAL | unchanged | contract/graph-authoring-a11y.contract.test.tsx (Enter/Space select, Ctrl+Z/Y, marquee, dialog); styles.css :focus-visible | Matrix keyboard path absent; not all tables/dialogs proven |
| M9-24 | PARTIAL | changed | styles.css --ok/--bad tokens; Loom status uses ✓/●/✗ glyphs + text; AccessLoom "Colour says nothing about permission" | No audit; matrix heat encodes by fill shade only (no non-color cue) |
| M9-25 | PARTIAL | unchanged | pervasive aria-label/role/title (~309 refs) + cell `<title>`; graph-authoring-a11y.contract.test.tsx | Not audited across every icon/control/dense metric |
| M9-26 | PARTIAL | unchanged | src/styles.css @media max-width 1100/1000/820px; loom.css 1180px; e2e runs 1600×1000 | No 1366×768 validation run |
| M9-27 | NOT DONE | unchanged | graph/io.ts exportSvgPng doubles canvas only | No devicePixelRatio handling or high-DPI/4K validation |
| M9-28 | NOT DONE | unchanged | none; only scattered inline notes | No glossary/help affordance defining VC/CDC/traffic class/provenance/metric terms |
| M9-29 | PARTIAL | changed | e2e/graph-history.spec.ts F18 + test_f18… (256/512 open+edit interactive) | No budget verification; matrix caps 24×24; floorplan/trace not exercised at target size |

## M10–M11

# Re-score — M10 & M11 (HEAD c13f7ca2)

## M10
DONE=0 PARTIAL=4 NOTDONE=23 CHANGED_FROM_AUDIT=4

| ID | NEW VERDICT | changed? | evidence: path[:symbol] (+test) | gap if not DONE |
|---|---|---|---|---|
| M10-01 | NOT DONE | unchanged | No `src-tauri/`, `tauri.conf.json`, `Cargo.toml` anywhere (`find . -iname '*tauri*'`); Studio is Vite/React web (`apps/studio/package.json`). | No Tauri command surface or allowlist exists. |
| M10-02 | NOT DONE | unchanged | Web import has size/depth guards (`src/graph/project.ts` MAX_PROJECT_JSON_*), not filesystem path scope. | No Tauri save/import/export path boundary; traversal scope unproven. |
| M10-03 | NOT DONE | unchanged | No external engine invocation in `apps/studio/src` (no child_process/exec). Engine is not spawned. | No structured-argv engine/tool invocation surface exists. |
| M10-04 | PARTIAL | changed | `src/graph/project.ts` MAX_PROJECT_JSON_CHARS/DEPTH; `src/graph/traceParser.ts` MAX_TRACE_RECORD_CHARS/DEPTH; tests graph-project.contract.test.ts:434-441, traceParser.contract.test.ts:88-100. | Catalog import is not size/depth bounded; no desktop FS admission. |
| M10-05 | NOT DONE | unchanged | `src/graph/catalog.ts` has no archive/bundle extraction; no zip/tar bundle importer. | No bundle import/extraction path to reject traversal/symlink/hash. |
| M10-06 | NOT DONE | unchanged | `src/graph/engineProtocol.ts` verifies artifact bytes (SHA-256), not engine binary identity. | No shipped engine version/checksum verification before run. |
| M10-07 | NOT DONE | unchanged | No updater code/config on HEAD (no tauri updater, no signed manifest). | No updater/package signature verification. |
| M10-08 | NOT DONE | unchanged | Web Studio is gateway-backed; Loom slice is local but no network-dependency doc/control. | No proof core app avoids external data; no documented network feature. |
| M10-09 | NOT DONE | unchanged | grep finds no telemetry/opt-in privacy setting in `src`. | No diagnostics/telemetry opt-in control with local visibility. |
| M10-10 | NOT DONE | unchanged | No support-bundle export/redaction module; only a F17 "bundle not claimed" probe. | No support export that strips usernames/paths or lists files. |
| M10-11 | NOT DONE | unchanged | No license module (grep 'licen[cs]e' hits only `CatalogLoom.tsx` IP field). | No signed node-lock license verify (sig/product/expiry/machine). |
| M10-12 | NOT DONE | unchanged | No license state UI. | Valid/expired/missing/mismatch states absent. |
| M10-13 | NOT DONE | unchanged | No license gate; no engine spawn to gate. | Recovery-vs-restricted-action separation not implemented. |
| M10-14 | NOT DONE | unchanged | No grace-policy hook. | No centralized/testable offline grace behavior. |
| M10-15 | NOT DONE | unchanged | No floating-license adapter interface. | No stable lease API surface. |
| M10-16 | NOT DONE | unchanged | No update-check/channel code. | No configured release-channel check. |
| M10-17 | NOT DONE | unchanged | No downloaded-update verify/apply path. | Signed update apply absent (Tauri updater path absent). |
| M10-18 | NOT DONE | unchanged | No updater rollback logic. | No prior-version rollback/recovery instructions. |
| M10-19 | NOT DONE | unchanged | No release-channel config (dev/beta/stable keys/endpoints). | No separated channel configuration. |
| M10-20 | NOT DONE | unchanged | No `.deb`/`.AppImage`/packaging config; `npm run build` emits web assets only. | No Linux installer/clean-machine install+uninstall. |
| M10-21 | NOT DONE | unchanged | No `.msi`/Windows packaging config. | No Windows installer evidence. |
| M10-22 | NOT DONE | unchanged | No `.dmg`/notarization config. | No signed/notarized macOS package. |
| M10-23 | PARTIAL | changed | `apps/studio/public/STUDIO_UI_SBOM.cdx.json` (CycloneDX 1.6, 12 npm prod components); `scripts/generate_ui_sbom.sh`; copied into `dist/`. [G22 partial] | No Tauri/bundled-binary inventory; not a release-wide SBOM. |
| M10-24 | PARTIAL | changed | `apps/studio/public/THIRD_PARTY_NOTICES.md` + `public/licenses/*`; `scripts/validate_third_party_notices.py` PASS (12 pkgs + fonts + artwork). | Covers web UI lockfile/assets only; no desktop/engine distributions. |
| M10-25 | PARTIAL | changed | `npm audit` 0 advisories for Studio tree (LOOM-G01-G26-...EXECUTION.md:12,66); source-map-js fixed 1.2.2 (M9-M11 report:933-935). [G22 not passed] | Full release/Tauri/bundled-binary graph not audited. |
| M10-26 | NOT DONE | unchanged | No log/crash retention config. | No bounded retention or project-content exclusion. |
| M10-27 | NOT DONE | unchanged | No offline licensed launch→run→update flow; web Studio has no local engine/license/updater. [F19 not passed; G20/G21 open] | Requires licensed desktop + local engine — surface absent. |

## M11
DONE=12 PARTIAL=24 NOTDONE=12 CHANGED_FROM_AUDIT=30

| ID | NEW VERDICT | changed? | evidence: path[:symbol] (+test) | gap if not DONE |
|---|---|---|---|---|
| M11-01 | DONE | changed | `src/contract/loom-project-schema-boundaries.contract.test.ts` (pins 14 top-level props + 5 required + invalid/unknown/missing/version); `loom-project-schema-v1.contract.test.ts`. [G01 partial] | — |
| M11-02 | DONE | changed | `src/graph/migration-fixtures/steps/*.{before,after}.json` (4 steps) + `loom-migration-steps.contract.test.ts` (goldens+idempotent) + `loom-migration-idempotence.contract.test.ts`. [G02 partial] | — |
| M11-03 | DONE | changed | `src/contract/graph-store.contract.test.ts` (valid/refused mutation, custom/dirty/undo/redo selectors, load baseline, serialize, remount recovery). | — |
| M11-04 | DONE | changed | `src/contract/graph-command-revert.contract.test.ts` (byte-exact revert of node/edge/workload/firewall commands); `graph-history-undo.contract.test.ts` exhaustive `Record<Exclude<GraphCommand['type'],'add_node'>,…>`:37. | — |
| M11-05 | DONE | changed | `src/contract/graph-project.contract.test.ts` positive/negative dangling, duplicate id, port overflow, disconnect, unsupported topology/edge/VC (20 tests). [G05 partial] | — |
| M11-06 | PARTIAL | changed | `loom-agents-v1.contract.test.ts` (address-window overlap/adjacency, width bounds) + `loom-catalog-reference/store` provenance tests. | Catalog parameter-range and protocol-compatibility cases not shown. |
| M11-07 | DONE | changed | `loom-vc-qos-v1.contract.test.ts` + `graph-project.contract.test.ts` XY/West-First/Odd-Even routes, reachability audit, unsupported-shape refusal, next-hop loops. | — |
| M11-08 | DONE | changed | `graph-project.contract.test.ts` row/column matrix edits, duplicate/conflict detection, allow-all/deny-default; `loom-access-floorplan` precedence; `workload-editor` deny-default undo step. [G07 partial] | — |
| M11-09 | DONE | changed | `graph-project.contract.test.ts` placement/overlap/keepout/Manhattan-side-map/unresolved-route; `workload-editor` drag-place + physical route length; `loom-access-floorplan` geometry. [G08 partial] | — |
| M11-10 | DONE | changed | `loom-workload-v1.contract.test.ts` (phases/comm-ops/tensor/mapping/timing) + `workload-editor.contract.test.tsx` (rank constraints/seat checks/mapping completeness). [G09 partial] | — |
| M11-11 | DONE | changed | `src/graph/traceParser.contract.test.ts` valid index, exact malformed line, 10k stream, unterminated/oversized bounds; `loom-trace-v1.contract.test.ts`. [G18 open] | — |
| M11-12 | PARTIAL | unchanged | `src/graph/runState.ts` (queued→…→completed/failed/cancelled/timed-out) + `runState.contract.test.ts`. | Cancel/timeout transitions and crash path not directly tested. |
| M11-13 | PARTIAL | changed | `loom-golden-projects.contract.test.ts` round-trip; `graph-store.contract.test.ts` autosave remount; `loom-migration-*`. [G14 partial] | Forced-process crash restore and external-change handling untested. |
| M11-14 | PARTIAL | changed | `src/graph/engineProtocol.contract.test.ts` compatible/incompatible/unavailable + SHA-256 artifact verify; `engineProtocol.ts`. | Not tested on a packaged app path (no package exists). [G10 partial] |
| M11-15 | PARTIAL | unchanged | `execution-readiness.contract.test.tsx` + `compile-control-plane.contract.test.tsx` refusal/absence reasons. | No supported backend case actually runs. [G10 partial] |
| M11-16 | PARTIAL | changed | `loom-run-manifest-v1/-summary-v1/-provenance-v1` contracts; `RunArtifactVerify.contract.test.tsx` gateway verify counts. [G12 partial] | No real completed run with consistent manifest/summary/trace/log hashes. |
| M11-17 | DONE | changed | `apps/studio/e2e/graph-history.spec.ts:100` F01 (Playwright: add/wire node, inspector width edit, validation, export/import, reload persistence) passed in last run; `tests/test_loom_p0_browser_acceptance.py::test_f01` passed. [F01 web slice only] | — |
| M11-18 | PARTIAL | unchanged | `tests/...::test_f02_catalog_ui_explicitly_disclaims_stampable_ip_contract` passed; `loom-catalog-reference`/`loom-agents-v1` contracts. [F02 partial] | No UI IP-stamp/provenance/port-domain E2E. |
| M11-19 | PARTIAL | changed | `tests/...::test_f05_firewall_editor_states_intent_without_execution_evidence` passed; `workload-editor`/`graph-project` matrix+conflict tests. [F05 partial] | No path/rule evaluation and save/reload equivalence E2E. |
| M11-20 | PARTIAL | changed | `workload-editor.contract.test.tsx` physical authoring (place/route/Manhattan/keepout/lock); F06 no-placement probe passed. [F06 blocked/partial] | No E2E place→route→timing/congestion→export-image. |
| M11-21 | PARTIAL | changed | `tests/...::test_f09_...rank_capacity_overflow` and `test_f10_moe_...lowering` passed; `workload-editor` rank mapping/phases. [F09/F10 partial] | No complete stable-ID mapping + validated run-input E2E. |
| M11-22 | PARTIAL | unchanged | `RunArtifactVerify.contract.test.tsx`, `MockPlayback.contract.test.tsx`. [F11 blocked] | No supported backend run completes with playback provenance. |
| M11-23 | PARTIAL | changed | `mock-truthfulness.contract.test.tsx` MOCK/geometry-only disclosure; `MockPlayback.contract.test.tsx`; F12 fallback browser probe passed. [F12 partial; G11 partial] | Full app fallback/backend isolation not exercised. |
| M11-24 | PARTIAL | changed | `tests/...::test_f14_review_reports_unsupported_rcu_then_clears_after_fix` passed (find→fix→recompile). [F14 partial] | No injected-fault→rerun→new-fingerprint disappearance E2E. |
| M11-25 | PARTIAL | changed | `tests/...::test_f16_browser_restart_restores_local_graph_autosave_only` passed. [F16 partial; G14 partial] | Browser restart is not forced process termination. |
| M11-26 | NOT DONE | unchanged | `e2e/graph-history.spec.ts:179` F18 FAILED (`test-results/.last-run.json`; error-context pointer intercept); `LOOM-M9-M11-performance-budgets.md` = proposal only. [F18 not passed; G16-G18 open] | No budget assertion; no matrix/trace perf E2E. |
| M11-27 | PARTIAL | changed | `engineProtocol.contract.test.ts` (unavailable/incompatible), `execution-readiness.contract.test.tsx`, `compile-control-plane.contract.test.tsx`. [G10 partial] | No actionable-error + continue-editing/exporting test. |
| M11-28 | PARTIAL | unchanged | `project-import-safety.contract.test.tsx` (oversize before read, malformed/version/missing-field keeps graph). | Catalog corruption rejected-not-covered; no partial-overwrite audit. |
| M11-29 | PARTIAL | changed | `MockPlayback.contract.test.tsx:116` corrupt line + valid prefix; `tests/...::test_f22_truncated_trace...` passed. [F22 partial] | Run not inspectable as failed with logs/recovery actions. |
| M11-30 | NOT DONE | unchanged | No permission-denied/read-only project test. | — |
| M11-31 | NOT DONE | unchanged | No disk-full/low-space test. | — |
| M11-32 | NOT DONE | unchanged | No updater failure/rollback test. | — |
| M11-33 | PARTIAL | unchanged | `product-truth.contract.test.tsx`, `mock-truthfulness.contract.test.tsx`, `loom-provenance-v1.contract.test.ts`. [G08/G09/G11 partial] | No exhaustive audit that every metric/result is provenance-labeled. |
| M11-34 | PARTIAL | changed | `graph-apply-fail-closed.contract.test.tsx`, `project-import-safety`, `graph-store-ownership.contract.test.ts` (refusal/dirty preserved). [G25 open] | No path-by-path save/run/export audit or exception inventory. |
| M11-35 | PARTIAL | changed | Studio `npm audit` 0 high/critical (gate execution report:12,66). [G22 not passed] | No full-artifact/dependency security audit. |
| M11-36 | NOT DONE | unchanged | `LOOM-M9-M11-performance-budgets.md` explicitly "proposal; not a test result". [G16/G17/G18 open] | No measured benchmark on reference hardware. |
| M11-37 | NOT DONE | unchanged | No installer/health-check artifact. [F20 not passed; G23 open] | — |
| M11-38 | PARTIAL | changed | `docs/product/LOOM-QUICKSTART.md` (create/edit graph, workload config, mock playback). [G24 partial] | No run/inspect of a supported simulation. |
| M11-39 | NOT DONE | unchanged | No topology/catalog/agent guide (only QUICKSTART + TROUBLESHOOTING). | — |
| M11-40 | NOT DONE | unchanged | No domains/access/firewall guide. | — |
| M11-41 | NOT DONE | unchanged | No floorplan guide. | — |
| M11-42 | PARTIAL | changed | `docs/product/LOOM-QUICKSTART.md` §Configure a workload/§Inspect playback (phases, mock playback, no-engine disclaimer). [G09/G24 partial] | Mapping, backend refusals and provenance coverage thin; no engine. |
| M11-43 | NOT DONE | unchanged | No reproducibility/support-bundle guide. | — |
| M11-44 | PARTIAL | changed | `contracts/loom/v1/README.md` + `docs/contracts/loom-project-v1.md` document project/trace/summary/run-manifest+validation schemas; `engineProtocol.ts`. [G24 partial] | Sidecar/engine protocol not documented as a versioned contract. |
| M11-45 | PARTIAL | changed | `docs/product/LOOM-TROUBLESHOOTING.md` sections: project JSON, malformed trace, save/download, engine missing/incompatible, license/update; doc states it does not close M11-45. [G24 partial] | Desktop license/update/permission procedures explicitly absent. |
| M11-46 | DONE | changed | `docs/reports/LOOM-M11-release-candidate-checklist.md` (build/tests, provenance, security/license, installers+rollback, docs, SBOM/hashes, gate sign-off). [checklist is a template, not a pass] | — |
| M11-47 | NOT DONE | unchanged | No Loom release notes/changelog (root `CHANGELOG.md` covers VeritX tools, no Loom entries). | — |
| M11-48 | NOT DONE | unchanged | No signed artifact/candidate. [F24/G25/G26 open] | — |

