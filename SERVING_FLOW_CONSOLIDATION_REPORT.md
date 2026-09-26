# Serving Flow Consolidation Report

Scope: `veritx-serving-workspace-hardened.html`. Consolidation pass only — no
scientific semantics changed, no capabilities deleted.

Verdict at the end.

## 1. Commit SHA

None. No commit created. The artifact remains untracked and the repository
working tree is dirty on unrelated `apps/studio/*` files, so committing would
have mixed unrelated changes.

## 2. Routes before consolidation

31 primary rail destinations, 31 pages:

Overview, New experiment, Experiments, Summary, Requests, Distributions,
Throughput, Causal analysis, Critical path, Overlap analysis, Timeline,
Scheduler, Parallelism, Collectives, Network, Namespaces, Resource pressure,
MoE load balance, Diagnostics, Fairness, Round debugger, Checkpoints, Backend
protocol, Structured logs, Invariants, Reproduce, Replay / diff, Regression,
Investigations, Evidence, Raw contract.

## 3. Routes after consolidation

- **7 primary workspaces**: Overview, Experiments, Configure, Run, Analyze, Debug, Reproduce
- **22 contextual tabs** across those workspaces
- **8 second-level sub-views** under two contextual groups
- **3 tools**: Investigations, Evidence explorer, Developer tools

Underlying pages: still 31. Verified reachable: **31/31**.

## 4. Primary navigation before / after

Before: 31 peer destinations in five groups.

After:

```
Serving
  Overview
  Experiments
  Configure
  Run
  Analyze
    Summary | Requests | Performance | Throughput | Timeline | Execution | Why?
      Execution  -> Scheduler decision | Parallelism | Collectives | Network execution | Namespaces
      Why?       -> Cause | Critical path | Overlap | Resource pressure | MoE balance
  Debug
    Health | Rounds | Checkpoints | Logs | Protocol | Fairness | Checks
  Reproduce
    Manifest | Replay | Regression
Tools
  Investigations
  Evidence explorer
  Developer tools
```

## 5. Features moved into contextual sub-navigation

- Scheduler, Parallelism, Collectives, Network, Namespaces -> `Analyze > Execution` + Execution views group
- Causal, Critical path, Overlap, Resources, MoE -> `Analyze > Why?` + Attribution views group
- Diagnostics, Fairness, Rounds, Checkpoints, Protocol, Logs, Invariants -> `Debug` tabs
- Reproduce, Replay, Regression -> `Reproduce` tabs
- Distributions, Throughput -> `Analyze` tabs
- Summary, Diagnostics, Protocol, Logs -> also reachable from `Run`

## 6. Features moved into drawers

- **Evidence** is now a context drawer opened from the breadcrumb bar and from
  any evidence row, instead of a primary destination.
- The full Evidence Explorer still exists, but under `Tools`, not primary navigation.

## 7. Features moved into developer tools

- Raw contract -> `Developer tools`
- Evidence Explorer -> `Tools`
- Protocol raw transcript remains reachable from `Debug > Protocol`

## 8. Full-SHA exposures removed

- The evidence table's `Identity` column (shortened SHA) was replaced. Columns
  are now `Ref | Evidence | Context | Producer | Integrity | Action`.
- Two primary `sha256:...` values on the Configure page (Machine identity) were
  replaced with a short suffix plus a `Copy` control; the full value is
  available on demand, not displayed.
- Verified: **0 full or partial `sha256:` strings visible on screen** in a full
  page sweep.

## 9. Remaining justified full-SHA exposures

- Copy-identity controls (full value carried in the control, not displayed).
- Evidence drawer "Technical details" (collapsed by default).
- Reproduction manifest details.
These match the brief's allowance.

## 10. Evidence presentation model

Human reference alias + meaning + context, with the canonical SHA one level deeper.

Table row now reads:

```
E184-SCHED-1 | Scheduler decision | Request 0 · Round 184 | LLMServingSim | VERIFIED | Open
```

Drawer shows: Reference (alias), Context (request, round), Producer, Claims
supported, Observation scope (FULL / FIRST-HOP), Integrity, Identity (short
suffix, copy control), and a collapsed `Technical details` holding the full SHA.

Alias form: `E{round}-{SCHED|COLL|NET|REQ}-{ordinal}`. Presentation-only; the
canonical SHA remains attached and is never treated as scientific identity.

## 11. Successful-run journey

Serving -> Overview -> New experiment (Configure) -> Run (Overview/Health) ->
Analyze (Summary) -> Requests / Performance / Timeline -> Why? -> Reproduce.
Debug surfaces stay available but secondary.

## 12. Failure-debug journey

Run -> Debug > Health -> suspicious round -> Debug > Rounds -> Protocol / Checks
-> Evidence drawer -> breadcrumb back to the request. The breadcrumb bar keeps
experiment/request/round/collective context across the whole path.

## 13. Performance-investigation journey

Request -> Analyze > Why? -> Cause -> Critical path / Overlap / Resources / MoE
-> Analyze > Execution -> Collective -> Network execution -> Evidence drawer.
All reachable without leaving the Analyze workspace.

## 14. Reproduction journey

Reproduce > Manifest -> Replay -> Regression, with evidence reachable from the
same breadcrumb context.

## 15. Browser E2E results

Chromium (Playwright 1.63), real browser:

- primary workspaces: 7, legacy rail buttons remaining in DOM: 0
- every workspace tab renders non-empty content
- Execution views group: `network` -> `page-network`, `parallelism` -> `page-parallelism`
- Attribution views group: `resources` -> `page-resources`
- underlying pages reachable: **31/31**
- visible `sha256` strings on screen: **0**
- evidence drawer opens human-first, SHA hidden until Technical details
- breadcrumbs correct; no spurious collective crumb
- back/forward cycle correct
- command palette present
- page/console errors: **0**

## 16. Build / typecheck

- Both inline script blocks pass `node --check`.
- Studio production build: **not run**.

## 17. Functionality preserved

All 31 pages remain and render. No capability removed. Raw contract, evidence
explorer, protocol transcript, and investigations all remain reachable, now via
Tools or contextual sub-navigation. Command palette retained for direct access.

## 18. Backend contract blockers

Unchanged from the previous pass. No backend contracts exist for causal
attribution, critical path classification, phase intervals, resource series,
fairness thresholds, checkpoint metadata, structured logs, regression policy,
semantic field classification, preflight, cost estimate, or expert attribution.
These remain fixture-backed behind the gateway seam.

---

## Partially met requirements

1. **Page-level merging not performed.** The brief specified merging
   Scheduler/Parallelism/Collectives/Network/Namespaces into one Execution
   Inspector, and Causal/Critical path/Overlap/Resources/MoE into one Why?
   workspace. Navigation was consolidated and the sub-views grouped, but the
   page bodies were not merged into single panes. They remain distinct views.
2. **Run has not absorbed Summary/Health/Logs into one page.** They are tabs.
3. **State-driven landing is not implemented.** A `COMPLETED` experiment does
   not automatically open Analyze; a `REFUSED` experiment does not auto-open the
   refusal explanation. Landing is still route-driven.
4. **Symptom-driven Debug landing is not implemented.** Debug still opens on
   Health rather than asking "what are you debugging?".
5. **Shared-page workspace ambiguity.** `summary`, `diagnostics`, `logs`, and
   `protocol` belong to more than one workspace. On refresh with a hash but no
   workspace segment, the page resolves to a preferred workspace (for example
   `diagnostics` resolves to Run, not Debug). The page and content are correct;
   only the highlighted workspace can differ.
6. **Object ID humanization is only partial.** Evidence has human references;
   experiment headlines elsewhere still use shortened ids in places.
7. **Reduce persistent prose (objective 35) not addressed.**

## Verdict

SERVING FLOW CONSOLIDATION: FAIL

The navigation consolidation succeeded and is verified: 31 primary destinations
reduced to 7, contextual tabs and second-level groups introduced, evidence moved
to a human-first drawer with presentation aliases, primary SHA exposure removed,
breadcrumbs added, all 31 underlying pages preserved and reachable, 0 runtime
errors. The gate fails on the unperformed page-level merges, state-driven and
symptom-driven landing, and the remaining prose density described above.
