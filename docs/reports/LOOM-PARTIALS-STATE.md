# Loom partials workstream — state and handoff

Last updated 2026-10-15. Branch `work/loom-partials-20261015`, worktree
`/tmp/opencode/loom-reconcile`, based on `integration/studio-reconciliation`
@ `48508e64`.

This records what has landed, what is verified, what remains, and the exact
commands to merge and clean up. It is a work-state document, not a release claim.

## What this branch is

11 commits implementing tracker items that the post-merge re-score
(`docs/reports/LOOM-PRODUCTION-TRACKER-RESCORE.md`) scored PARTIAL or NOT DONE.
Base commits below it came from the finish-branch reconciliation (see
`LOOM-RECONCILIATION-PLAN.md`).

| Commit | Items |
|---|---|
| `2c231d20` | M5-18, M5-26, M5-29 |
| `039499b2` | M1-12, M1-13 |
| `b3f9d251` | M1-31, M1-32 |
| `3e7f9a16` | M1-21, M1-22, M1-24, M1-30 |
| `db898481` | M1-15, M1-17, M1-26 |
| `e665d68c` | M1-14, M1-33 |
| `d87559b2` | M1-18, M1-19 |
| `7b8000ba` | M2-08, M2-09, M2-26 |
| `a849a9a5` | M2-11, M2-14, M2-24 |
| `82e1e0e0` | M2-12, M2-13 |
| `835f6b9c` | M2-15, M2-16, M2-18, M2-19 |

## Verification (run on this branch)

```
cd apps/studio
npx tsc --noEmit                 # clean
npx vitest run                   # 80 files, 754 tests pass
npx playwright test              # 5/5 pass
```

Baseline before this branch: 67 files / 671 tests.

## Tracker items closed (28)

- **M5** (now 26 Done / 0 Partial / 3 Open): M5-18 seat-assignment policy,
  M5-26 workload×backend preflight, M5-29 run-input browser E2E.
- **M1** (now 34 / 0 / 0 — fully closed): M1-12, 13, 14, 15, 17, 18, 19, 21,
  22, 24, 26, 30, 31, 32, 33.
- **M2** (now ~16 Done / 7 Partial / 3 Open): M2-08, 09, 11, 12, 13, 14, 15,
  16, 18, 19, 24, 26 (M2-26's stamp→configure→save flow).

## What each slice added (code map)

- `graph/alignOps.ts` — align/distribute over a topology multi-selection (M1-12/13).
- `graph/selectionOps.ts`, `graph/interfaceRole.ts` — selection algebra, direction pairing (M1-08/28, earlier).
- `GraphLoom.tsx` — search box (M1-31), keyboard shortcut layer + documented list
  (M1-32), minimap (M1-14), context menus (M1-33), obstacle-avoiding lanes
  (M1-17/19), pick-time link refusal (M1-15), catalog browser + stamp (M2-08/09),
  agent/port/window inspector host (M2-15/16/19).
- `graph/linkOps.ts` — link compatibility at pick time, incl. protocol (M1-15, M2-18).
- `graph/routing.ts` — `nodeFootprintRect`, `laneIndex`, `withLane` (M1-17/19).
- `graph/presets.ts` — `buildRingPreset`/`buildTreePreset`/`buildTorusPreset`,
  `presetClaimStatus` (M1-21/22/24/30).
- `graph/project.ts` — `knownCatalogItems` option (M1-26), `metadata.localCatalog` (M2-12).
- `graph/workload.ts` — `RANK_ASSIGNMENT_POLICIES`/`autoRankMappings(policy)`,
  `nextPhaseId`/`nextCommunicationId` (M5-18, determinism).
- `graph/workloadBackend.ts` — workload × declared-backend preflight (M5-26).
- `graph/catalogStamp.ts` — catalog item → authored node with provenance (M2-09).
- `graph/catalogStore.ts` — effective catalog (embedded local, else built-in) (M2-12/13).
- `graph/protocolCompat.ts` — protocol compatibility + explicit-bridge rule (M2-18).
- `graph/catalog.ts` — `CATALOG_OVERRIDE_CONSTRAINTS`, `validateCatalogOverrides` (M2-11/24).
- `graph/store.ts` — added live `current()` accessor (fixes batched-edit staleness).
- `pages/loom/CatalogProvenance.tsx` — resolution + rebind + override editor (M2-11/14/24).
- `pages/loom/NodeAgentInspector.tsx` — agents/ports/address windows (M2-15/16/19).
- `e2e/workload-run-input.spec.ts` — M5-29 flow.
- Tests added: `align-ops`, `graph-search-shortcuts`, `graph-minimap-context`,
  `graph-link-routing`, `preset-claims`, `graph-catalog-stamp`,
  `catalog-provenance`, `catalog-import-export`, `node-agents`,
  `workload-backend`, plus updates to existing suites.

## Two guard fixes worth remembering

- `loom-truth` forbids bare count literals in `pages/loom` — geometry/limits must
  come from constants (e.g. `NODE_FOOTPRINT`, `CATALOG_OVERRIDE_CONSTRAINTS`).
- Adding a file input made `input[type="file"]` ambiguous and broke F01/F18/F21;
  the project-load input now has `data-testid="project-file-input"`.

## Future work

Still PARTIAL / open, in rough priority order. Everything below is Studio-local
unless stated.

**M2 (finish the catalog/IP experience)** — 7 partial + 3 open:
- M2-03/04/05/06/07 catalog entries: more router radix variants; configurable
  agent-port surfaces; DDR address window; port-compatibility metadata on bridges;
  stampable peripheral/DMA (they exist as templates but aren't instantiable).
- M2-10 favorites/recent catalog items (store + UI).
- M2-20 reset/power domain assignment UI with visual inherit/override.
- M2-21 one-undoable bulk agent/VC/clock template apply (NodeTable currently runs
  N sequential commands).
- M2-22/23 unify node/edge inspectors into stable sections (identity, catalog
  provenance, ports, clocks, domains, routing, physical/timing).

**M3 (policy, domains, matrix)** — 11 partial:
- M3-16 virtualized I×T matrix; M3-19 row/column/batch access edits.
- M3-06/07/09 per-VC depth/class edit against catalog limits; arbitration UI;
  escape-VC configuration.
- M3-11/12/14/15 reset/power domain editors, power-domain crossings, domain overlay.
- M3-24 addressing holes/overlaps/unmapped initiators; M3-27 access→path→firewall flow.

**M7 (diagnostics/repro)** — 14 partial; several need run artifacts that do not
exist yet (support bundle, replay, manifest diff). ProblemsPanel/logs cross-probe
and project semantic diff are the closable ones.

**M8 / M9 / M11** — M8 file-resilience and M9 performance need real desktop/measured
surfaces; M11 docs (M11-38…45) are closable as documentation.

**Not closable without surfaces that do not exist** (leave as-is):
M4 physical/OpenROAD, M6 real `loom-sim` engine, M8 real atomic file I/O,
M9 measured budgets, M10 desktop/licensing/installers.

## Merge and cleanup (runbook)

**Precondition: the other session editing `apps/studio/src/pages/loom/GraphLoom.tsx`
in the main working tree MUST be stopped.** On 2026-10-15 18:32 that tree had
uncommitted `GraphLoom.tsx` plus new `graph/layout.ts`, `graph/search.ts` and two
tests. Merging over an active writer loses its work.

Safety already in place:
- `backup/pre-reconcile-20261015` → `601a71bd` (the pre-reconciliation HEAD).
- `/tmp/opencode/wip-unstaged-20261015.patch` + `/tmp/opencode/wip-new-files/`.
- This branch and its worktree.

When the main tree is clean (or its work committed):

```bash
cd /home/datavex/bruh/veritx-research
git status --short                     # must be empty
git log --oneline -1 integration/studio-reconciliation
git merge --no-ff work/loom-partials-20261015
# resolve any conflicts (GraphLoom.tsx is the likely one), then:
cd apps/studio && npx tsc --noEmit && npx vitest run && npx playwright test
git push    # only when you decide to publish
```

Clean up only after the merge is verified:

```bash
cd /home/datavex/bruh/veritx-research
git worktree remove /tmp/opencode/loom-reconcile            # my scratch worktree
git branch -d work/loom-partials-20261015                   # merged
git branch -d reconcile/loom-finish-20261015                # merged via c13f7ca2
# keep backup/pre-reconcile-20261015 and work/loom-finish-luna-20261015
# until you no longer need the fallback history.
```

If the merge is deferred, the branch stands alone and is green; nothing is lost.
