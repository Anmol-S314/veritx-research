# Topology Recommendation Plan

**Status:** proposed; Phase 2/3 recommendation slice implemented in the prototype on 2026-10-26  
**Date:** 2026-10-26  
**Scope:** Srota Studio prototype (`apps/studio/prototype`) and the product gateway it reads  
**Related:** `apps/studio/prototype/README.md`, `apps/studio/prototype/DESIGN.md`, `docs/design/reviews/backend-completion-plan.md`

> **Implemented slice.** `#/explore/brief` now joins measured workload trace replay, the native-model family reference, and a measured buffer-depth slice. It exposes latency / throughput / modeled power / modeled area / buffer-storage bounds, recommends a topology plus measured depth and canonical VCs, shows the runner-up and tested threshold flips, and prefills the bounded project study with executable families and declared link widths. The recommendation uses repository evidence only; power and area remain modeled screening estimates, link width is not varied by the measured sweep, and the project revision is measured only by the bounded study. See `apps/studio/prototype/README.md` § *Fabric recommendation (Explore)* for the current evidence sources and limits.

## 1. Purpose

Define the next product step after the revision-history cleanup:

> Start from the workload, let the user refine its demand, declare goals and constraints, then recommend topology candidates with evidence and trade-offs.

This is a workload-first, requirements-driven design flow. Topology is a consequence of the workload and the declared goals, not the first object the user has to author.

## 2. Decisions already made

1. **Workload is the root intent.** The user identifies the workload first, then refines it for the use case.
2. **Topology is downstream.** The system proposes or ranks topology candidates after the workload demand and goals are declared.
3. **Recommendation is constrained selection, not a single score.** Hard constraints filter; objectives rank; multiple objectives produce a Pareto set.
4. **A revision is the design version.** A run is one evaluation attempt. Run labels are `rNN · run N`; runs are never called versions.
5. **The recommendation must be honest about authority.** Measured, derived, modeled, and unavailable metrics are labelled separately. No metric is invented to fill a card.
6. **PDP means power × delay.** It is a derived metric and is only valid when power and delay come from the same declared scope and authority.

## 3. Vocabulary

| Term | Meaning |
|---|---|
| Intent | Editable inputs that produce a revision: workload, fabric, requirements, constraints. |
| Workload identity | The model or application being studied: catalog workload, imported description, or custom. |
| Demand profile | The workload consequences the fabric must serve: parallelism, phases, collectives, compute stages, memory access, traffic classes, seat demand. |
| Revision | One immutable compile attempt. May be `COMPILED`, `UNSUPPORTED`, or `FAILED`. |
| Run | One evaluation attempt against a revision. Multiple runs per revision are normal. |
| Design constraint | A hard bound used to filter candidates before or during evaluation. |
| Design objective | The metric to minimize or maximize among feasible candidates. |
| Acceptance requirement | A criterion used to judge a measured run after evaluation. |
| Recommendation | A candidate or set of candidates that satisfies declared constraints and leads on the declared objective, with its basis shown. |
| PDP | Power × delay. A derived metric, not a directly measured backend quantity. |

## 4. Product thesis

The current Studio flow is organized around storage objects (draft, revision, run) and separate workspaces. The next flow should be organized around the engineering decision loop:

```text
What workload am I serving?
  → What demand does it create?
    → What must the fabric achieve?
      → Which topologies are feasible?
        → Which one wins under my objective?
          → Adopt it as a revision and evaluate it.
```

Every screen should answer one of those questions. A page boundary that does not correspond to one of them is friction.

## 5. Current state

### 5.1 What exists

- Workload catalog and editable workload page (`LiveWorkloadPage`).
- Requirements editor (`RequirementsStudio`).
- Validation and lowering checks (`ValidationStudio`).
- Fabric draft editor (`DraftEditor`).
- Compile → revision → run model with revision history.
- Bounded optimization studies (`LiveExplore`, `LiveStudyResults`).
- Candidate adoption (`StudyAdoption`).
- Revision diff endpoint (`GET /revisions/{id}/diff`).
- Optimization capabilities endpoint (`GET /optimization/capabilities`).
- Metric registry and capability gaps.

### 5.2 What is missing

- Workload, fabric, requirements, and validation are not one Intent stage.
- The optimization UI only exposes integer parameter sweeps; `topology_family` is supported by the backend but filtered out of the study parameter list.
- Constraints are not exposed in the study UI, even though the backend supports them.
- There is no single “recommended candidate” surface that explains why it won, what lost, and what would change the answer.
- There is no persisted design brief for goals and constraints before a study is launched.
- There is no power metric, so PDP cannot be measured today.

### 5.3 Evidence from the current store

- The Mixtral project has **12 revisions** and **8 runs**. Six revisions (`r03–r08`) are `UNSUPPORTED` compile attempts; `r09–r10` compiled with no runs. The old flat table hid all of them.
- `v1.1–v1.3` were three runs of `r01`; `v12.1` was `r12`, run 1. The labels caused a semantic error, not just visual noise.
- `r11 → r12` changed one collective’s traffic class. The old rows looked identical because the run subtitle only carried model/topology/width.
- The New Interconnect Study has active `r07` with no run and historical `r04` runs. The old page auto-selected a historical run; the new page leaves the active revision’s “no run” state visible.

## 6. Target flow

```text
Project
  Intent
    Workload identity
    Demand profile
    Goals & constraints
    Fabric (optional manual constraints)
    Validate
  Compile
  Topology candidates
  Recommendation
  Adopt
  Revision
  Evaluation
  Analysis
```

The user can still author a topology manually. The recommender is a starting point, not a replacement for engineering judgment.

## 7. Requirements model

### 7.1 Hard constraints

Hard constraints filter candidates. They are not weights.

Examples:

- Transaction P95 latency ≤ 25 ns.
- Aggregate delivered throughput ≥ 18 GB/s.
- Peak power ≤ 5 W.
- Energy per transaction ≤ X pJ.
- Area ≤ Y mm².
- Allowed topology families: mesh, torus, fattree.
- Maximum radix, package, or concentration limits.

A candidate that violates a hard constraint is **excluded**, not silently penalized.

### 7.2 Objectives

One primary objective per study, with optional tie-breakers:

- Minimize latency.
- Minimize energy.
- Minimize PDP.
- Maximize throughput.
- Minimize area.
- Minimize cost.

If more than one objective is declared, show a Pareto set rather than inventing weights.

### 7.3 Acceptance requirements

Acceptance requirements judge a measured run. They are separate from design constraints:

- Design constraints decide what to evaluate.
- Acceptance requirements decide whether the measured result passes.

They may share metric definitions, but the UI must label their role.

### 7.4 Workload scope

The brief must say whether the recommendation is for:

- one workload,
- a set of workloads,
- a weighted mix,
- worst-case across a set,
- expected value across a set.

A topology that wins on one MoE all-to-all phase may lose on dense TP8 or a different batch size. The recommendation must state its scope.

## 8. Metric contract

The recommender is only as credible as its metric definitions. Every objective or constraint must have:

- a metric key,
- a definition,
- a scope,
- a unit,
- an authority (measured, derived, modeled, unavailable),
- a backend or model source.

| Metric | Definition | Scope | Current authority | Recommendation use |
|---|---|---|---|---|
| Network completion | `completion_cycles` | Network simulation | Measured by BookSim | Objective or constraint |
| Packet latency | `packet_latency_avg` / `flit_latency_avg` | Network simulation | Measured by BookSim | Constraint |
| System makespan | `system_makespan_cycles` | System simulation | Measured by Astra/BookSim | Objective or constraint |
| DRAM latency | `average_read_latency_cycles` | Memory simulation | Measured by Ramulator | Objective or constraint |
| Aggregate throughput | Delivered bytes / declared window | Network | Run metric / derived | Constraint, with scope stated |
| Energy | `hops_avg × pJ_per_hop` | Modeled proxy | Script/static baseline only | Not live; proxy only if explicitly enabled |
| Power | Watts | Fabric / device | **Unavailable** | Blocked |
| PDP | Power × delay | Mixed | **Derived; needs power** | Blocked until power authority exists |
| Area | mm² | Fabric | Modeled/static | Later |
| Cost | Currency | Package | Unavailable | Later |

### 8.1 PDP definition

```text
PDP = power × delay
```

For a meaningful PDP, both terms must use the same scope and operating point:

- Which power? Dynamic, leakage, total, peak, or average?
- Which delay? Packet latency, transaction P95, completion cycles, or system makespan?
- Which clock and voltage?
- Which workload phase?
- Is the power measured, modeled, or estimated?

Until those are declared, PDP is a label, not a metric.

### 8.2 Current PDP status

The live gateway currently has no power metric. The optimization study candidate payload carries objective values such as `system_makespan_cycles` and `average_read_latency_cycles`, but no `power_w`.

Therefore:

- PDP must not be offered as a selectable measured objective yet.
- If a modeled PDP is shown, it must be labelled **modeled PDP proxy** and must show the formula, power source, delay source, and scope.
- A modeled PDP must never be presented as measured evidence or used to claim requirement compliance.

## 9. Candidate generation and ranking

### 9.1 Candidate generation

Start with the existing bounded study contract:

- domain: one or more declared parameters,
- at most four configurations per study in the current product,
- method: grid/enumeration,
- seed: explicit for determinism.

For the first topology recommendation slice:

- Sweep `topology_family` over the executable values reported by `/optimization/capabilities`.
- Optionally sweep one integer parameter (`link_width`, `concentration`, or `radix`) in a later slice.
- Do not expose locked parameters (routing, VC count/structure, turn restrictions, escape VC).

### 9.2 Feasibility prefilter

Before evaluation:

- Check seat demand: workload parallelism demand vs candidate seat capacity.
- Check endpoint attachments.
- Check that the family is materializable and backend-executable.
- Show excluded candidates and the reason.

The `r03–r08` failures in the Mixtral project were seat mismatches. The recommender should surface that class of failure before a compile attempt, not after.

### 9.3 Evaluation

Use the existing certified optimization path:

- `POST /revisions/{id}/optimize` with `domain`, `objectives`, `constraints`, `method`, `budget`, `seed`.
- Poll the job.
- Read the optimization study.
- Show candidate compilation status, evaluation status, objective values, constraints, and fidelity.

### 9.4 Ranking

1. Remove candidates that fail a hard constraint.
2. Remove candidates that are not measured or whose constraint verdict is `UNMEASURABLE`.
3. Rank survivors by the primary objective.
4. If multiple objectives are declared, compute and display the Pareto set.
5. Show the winner, runner-up, and what would change the answer.
6. Never call an unmeasured candidate “best.”

### 9.5 Recommendation copy

Preferred:

> Recommended under your declared goals and constraints: C3. It has the lowest measured PDP among feasible candidates. C5 is 8% faster but 12% higher PDP. If peak power is capped at 4 W, C3 is excluded and C5 wins.

Avoid:

> Best topology.

## 10. UI plan

### 10.1 Project header

Keep the current Slice 1 header:

- Active revision (`rNN`, status, timestamp).
- Open run selector grouped by revision.
- Historical badge when the selected run is not on the active revision.

No duplicate “Open analysis” button; the run selector opens the run.

### 10.2 Intent stage

Replace the current separate Workload/Fabric/Requirements/Validate destinations with one Intent stage containing tabs:

```text
[ Workload ] [ Demand ] [ Goals & constraints ] [ Fabric ] [ Validate ]
```

- **Workload**: identity, model family, parallelism, serving mode, catalog preset.
- **Demand**: collectives, phases, compute stages, memory operands, traffic classes, derived seat demand.
- **Goals & constraints**: objectives, hard constraints, workload scope, evidence policy.
- **Fabric**: manual topology and NoC controls.
- **Validate**: declaration checks and lowering preview.

One sticky status bar:

```text
Saved · matches r12     [Save draft] [Compile revision]
```

### 10.3 Goals & constraints panel

```text
Workload scope
  ( ) This workload   ( ) A set of workloads

Hard constraints
  [metric] [op] [threshold] [unit] [remove]
  + Add constraint

Objective
  [metric] [MIN/MAX]
  Tie-breakers: [metric] [metric]

Evidence policy
  ( ) Measured only
  ( ) Allow modeled values, labelled

[Find topology candidates]
```

Unavailable metrics are disabled with a reason:

```text
PDP — unavailable: no power model is attached.
Energy — unavailable: only a modeled proxy exists; enable it explicitly.
```

### 10.4 Topology candidates

```text
7 feasible · 3 excluded

Candidate | Family | Latency | Energy | PDP | Area | Constraints | Fidelity | Pareto
C3        | mesh   | ...     | ...    | ... | ...  | pass        | measured | yes
C5        | torus  | ...     | ...    | ... | ...  | pass        | measured | yes
C7        | fattree| ...     | ...    | ... | ...  | fails power | modeled  | excluded

[Adopt C3] [Compare C3 vs C5] [Download study]
```

Each row expands to show:

- declared parameter values,
- compilation status,
- evaluation status,
- constraint verdicts,
- objective provenance,
- exclusions and reasons.

### 10.5 Recommendation summary

```text
Recommended: C3
Why: lowest measured PDP among feasible candidates.
Runner-up: C5 — 8% faster, 12% higher PDP.
What would change the answer: peak power ≤ 4 W excludes C3.
Evidence: BookSim measured network completion; power is modeled (if enabled).
```

### 10.6 Adopt

Adoption creates a revision from the chosen candidate:

- Review the patch (topology family and parameters).
- Preserve the current draft.
- Compile the adopted draft.
- Open the new revision.
- Do not transfer old run evidence to the new revision.

## 11. Backend and API plan

### 11.1 Reuse

- `GET /optimization/capabilities`
- `POST /revisions/{id}/optimize`
- `GET /jobs/{id}`
- `GET /optimizations/{id}`
- `POST /optimizations/{id}/candidates/{candidate_id}/use`
- `GET /revisions/{id}/diff`

### 11.2 Frontend changes

- Allow `topology_family` (enum) in the study parameter selector when `executable === true`.
- Add constraint rows to the study definition.
- Add objective direction and tie-breaker selection.
- Render constraint verdicts and exclusion reasons.
- Add a recommendation summary and “what would change the answer.”
- Keep the four-configuration limit visible.

### 11.3 Backend changes

- No new optimizer algorithm is required for the first slice.
- Add a persisted recommendation brief if the goals/constraints must survive reload before a study is launched.
- Add a `power_w` metric authority and a `pdp` derived metric only when a real power model/backend is connected.
- If a modeled power source is added, register it as `MODELED` with a formula and source; never as `MEASURED`.

### 11.4 Persistence decision

Options:

1. Keep the brief in local/session state until a study is launched; the optimization definition is the persisted record.
2. Add a `RecommendationBrief` to the project draft or project record.
3. Extend the existing draft `requirements` schema with design-time constraints.

Recommendation for the first slice: **option 1**. It avoids a schema migration and keeps the study definition as the auditable record. Revisit option 2 if users need the brief across sessions before launching.

## 12. Phased delivery

### Phase 0 — Revision history (completed)

- `rNN · run N` labels.
- Revision-first history with failed compile attempts.
- Exact-run opening.
- Historical banner.
- No auto-selection of historical runs when the active revision has none.

### Phase 1 — Intent consolidation (completed 2026-10-26)

- One Intent stage with Workload, Fabric, Requirements, and Validate tabs.
- One save/compile status bar for the active tab.
- Catalog workload selection moved into the Workload tab.
- Removed the separate “Set workload” action from the project header.
- Active Intent tab is remembered per project.
- Old workload routes still resolve for deep links and fixture mode, but are hidden from the loaded-project sidebar.

### Phase 2 — Requirements and constraints capture

- Goals & constraints form.
- Metric catalog with authority and availability.
- Persist the brief for the study (option 1).
- Disable unavailable metrics with reasons.
- Define PDP as blocked until power authority exists.

### Phase 3 — Topology candidate study

- Enable `topology_family` in the study selector.
- Add constraints to the study definition.
- Feasibility prefilter and excluded-candidate list.
- Recommendation summary and “what would change the answer.”
- Adopt candidate → revision.

### Phase 4 — Inline evaluation

- Move the evaluation launcher into the project page.
- After a run completes, hand off to Analysis with the exact run selected.
- Keep the explicit “writes a real run” confirmation.

### Phase 5 — Power and PDP authority

- Connect a real power/energy model or backend.
- Register `power_w` and `pdp` with scope and authority.
- Enable energy/PDP objectives and constraints only after the authority exists.
- If only a model is available, label it `MODELED` and keep it out of compliance claims.

## 13. Acceptance criteria

- A user can define a workload, refine its demand, and declare goals/constraints without leaving the project.
- Every objective and constraint shows its metric definition, scope, unit, and authority.
- A topology study can sweep executable `topology_family` values.
- Infeasible candidates are excluded with a reason, not silently ranked.
- A candidate is recommended only if it is measured and satisfies all hard constraints.
- The recommendation shows the runner-up and what would change the answer.
- Energy and PDP are never presented as measured without a power authority.
- Adopting a candidate creates a new revision and does not reuse old run evidence.
- Changing the workload or constraints invalidates the previous recommendation.

## 14. Risks and non-goals

### Risks

- **PDP overclaim.** Power is unavailable today; a modeled PDP could be mistaken for measured evidence.
- **Overfitting.** A single-workload recommendation may not generalize to the user’s workload portfolio.
- **Candidate-space limits.** Four configurations per study may be too small for cross-family exploration.
- **Metric scope drift.** Latency and energy definitions can differ across backends.
- **Brief persistence.** A non-persisted brief may surprise users after reload.
- **UI density.** Goals, constraints, candidates, and evidence can become a wall of controls; use progressive disclosure.

### Non-goals

- No claim of global optimality.
- No claim of hardware qualification or physical signoff.
- No invented power, area, or energy values.
- No automatic adoption without human review.
- No replacement of manual topology authoring.

## 15. Open questions

1. Does PDP mean power × packet latency, power × transaction P95, or power × system makespan?
2. Which power scope is intended: dynamic, leakage, total, peak, or average?
3. Is power measured by a backend, or modeled from a declared source?
4. Is the first recommendation for one workload or a workload set?
5. Is the first release single-objective with constraints, or Pareto from day one?
6. Should the recommendation brief persist before a study is launched?
7. Should candidate generation include link width/concentration alongside topology family in the first release?

## 16. Code references

- `apps/studio/prototype/src/ProjectFlow.tsx` — project workflow, revision history, run context.
- `apps/studio/prototype/src/RevisionHistory.tsx` — revision-first history and run picker.
- `apps/studio/prototype/src/revisionHistory.ts` — grouping, previous compiled revision, diff helpers.
- `apps/studio/prototype/src/LiveOperations.tsx` — current bounded study UI.
- `apps/studio/prototype/src/LiveStudyResults.tsx` — candidate/Pareto results.
- `apps/studio/prototype/src/StudyAdoption.tsx` — candidate adoption.
- `apps/studio/prototype/src/gateway.ts` — optimization and revision-diff clients.
- `tracks/t3-topology/dse/veritx_dse/optimization/definition.py` — domain/objective/constraint contract.
- `tracks/t3-topology/dse/veritx_dse/optimization/capabilities.py` — executable topology families and parameters.
- `tracks/t3-topology/dse/veritx_dse/optimization/result.py` — constraint verdicts, Pareto, candidate evidence.
- `tracks/t3-topology/scripts/energy_score.py` — modeled energy proxy (hops × pJ/hop).
- `tracks/t3-topology/scripts/area_model.py` — modeled area table.

## 17. Immediate next step

Start with **Phase 1** if the goal is to remove the workload-to-analysis page hop. Start with **Phase 3** if the goal is to prove the recommendation loop with the existing measured metrics.

Recommended sequence:

1. Phase 1 — merge Workload into Intent.
2. Phase 2 — capture goals and constraints with the metric contract.
3. Phase 3 — topology candidates and recommendation.
4. Phase 5 — add power/PDP authority when the backend exists.

PDP is not a Phase 1 blocker. It is a Phase 5 gate.
