# Loom finish-branch reconciliation — plan and decisions

Status: **landed on `integration/studio-reconciliation`** as merge commit
`c13f7ca2`. The reconciled branch was verified on scratch
`reconcile/loom-finish-20261015` (`cb0cf6e0`), then the user's in-flight M1 work
was committed (`1599aebe`) and the branch merged in, resolving three overlapping
files. See "Outcome" at the end. Not pushed.

This records the decision taken before any merge is landed, so the merge is
reviewable and reversible. Nothing is committed to the live branch until the
reconciled tree builds and its tests are green.

## What is being reconciled

Two lines descend from the same base `bf26286e`:

| Line | Ref | Time | Size | Role |
|---|---|---|---|---|
| Live mainline | `601a71bd` on `integration/studio-reconciliation` | 13:37 | 87 files / ~7.4k lines | **Authoritative for behavior and validation contracts** |
| Finish branch | `work/loom-finish-luna-20261015` (`4d68b526`) | 12:08 | 214 files / ~26k lines | **Authoritative for schema breadth and additive modules** |

The finish branch was produced by the prior "finish the tracker" attempt
(`docs/reports/LOOM-FINISH-BASELINE.md` on that branch). It explicitly does not
claim completion. Its own record: build passed, 572 tests passed.

`601a71bd` is the newer commit; it is the checked-out branch, the working tree's
uncommitted M1 work builds on it, and `docs/reports/LOOM-PRODUCTION-TRACKER-AUDIT.md`
scores its conventions (canonical `ProjectIssue` model, `objectRef` as a string,
`graph.disconnected` as policy-aware severity) as the tracker-aligned ones
(M0-16, M1-29, truthfulness gates G08/G11).

## Conflict surface

Only 12 of 214 files overlap; 8 conflict. ~202 files (all the schema modules,
contract tests, reports, SBOM, notices, sample projects) merge cleanly:

```
apps/studio/package.json, package-lock.json                  (auto)
apps/studio/src/graph/routing.ts                             (auto)
apps/studio/src/pages/loom/SimulationLoom.tsx                (auto)
apps/studio/src/pages/loom/authoring.tsx                     (CONFLICT)
apps/studio/src/pages/loom/GraphLoom.tsx                     (CONFLICT)
apps/studio/src/graph/adapter.ts                             (CONFLICT)
apps/studio/src/graph/history.ts                             (CONFLICT)
apps/studio/src/graph/project.ts                             (CONFLICT)
apps/studio/src/graph/store.ts                               (CONFLICT)
apps/studio/src/graph/workload.ts                            (CONFLICT)
apps/studio/src/contract/graph-project.contract.test.ts      (CONFLICT)
```

## The one hard decision

The two lines use **incompatible validation-result models**:

| | Live mainline (`601a71bd`) | Finish branch |
|---|---|---|
| result type | `ProjectIssue` | `ValidationIssue` |
| `objectRef` | `string` (`$.nodes[id=n1]`) | object (`{ path: '$.nodes' }`) |
| `validateWorkload` returns | `ProjectIssue[]` | `string[]` |
| disconnected node | warning while editing, error under `requireConnected` | hard refusal |
| `graphToDraft` | refuses without a canonical V4/V5 draft | synthesizes a V4 draft with fabricated defaults |

**Resolution: HEAD's model wins** (newer, tracker-aligned, and the model the
audit and the uncommitted M1 work depend on). The finish branch's richer
validation *logic* is kept, but re-expressed through `makeIssue`/`ProjectIssue`.
The finish branch's contradictory test assertions are updated to HEAD's policy;
they are not deleted and are not weakened to hide real breakage.

## Safety

- `tag backup/pre-reconcile-20261015 -> 601a71bd` (current live HEAD).
- Working-tree patch + the 5 untracked M1 files saved to
  `/tmp/opencode/wip-unstaged-20261015.patch` and `/tmp/opencode/wip-new-files/`.
- The merge runs in a throwaway worktree `/tmp/opencode/loom-reconcile`
  (branch `reconcile/loom-finish-20261015`). The live working tree is untouched.

## Definition of done for this step

1. All merge markers resolved on the 8 files; ~202 additive files retained.
2. `cd apps/studio && npx tsc --noEmit` passes.
3. `npx vitest run` passes (or every remaining failure is listed with cause).
4. A precise report: per-file resolution, test totals, remaining gaps.
5. Only then: a merge commit proposed to the user (not pushed, not applied to
   the live branch without sign-off).

## Outcome (verified)

Landed on `integration/studio-reconciliation`:

| Commit | Contents |
|---|---|
| `1599aebe` | in-flight M1 work (stable graph-id rules, interface direction, selection ops) |
| `8bcf9949` | tracker audit verdicts + this reconciliation record |
| `c13f7ca2` | merge of `reconcile/loom-finish-20261015` (the recovered finish work) |

The standalone merge commit `cb0cf6e0` on `reconcile/loom-finish-20261015`
changed **141 files, +25,538 / −308**.

Independently verified on the landed tree (not just self-reported):

| Check | Result |
|---|---|
| Conflict markers remaining | 0 |
| Unmerged paths | 0 |
| `npx tsc --noEmit` | clean (exit 0) |
| `npx vitest run` | **70 files / 671 tests passed** |
| `npm run build` | exit 0 (main chunk ~1.26 MB — advisory only) |

Recovered additive modules confirmed present: `catalog`, `firewall`, `floorplan`,
`provenance`, `runManifest`, `runState`, `semanticDiff`, `summary`,
`engineProtocol`, `migration`, `validation`; 11 `*-EXECUTION.md` reports;
`STUDIO_UI_SBOM.cdx.json` + `THIRD_PARTY_NOTICES.md`; section types for
M0-06…M0-12 in `graph/project.ts`.

Foundational change so both lines share one model: `graph/validation.ts`
`ValidationIssue.objectRef` is now a **string**.

Branch tests updated to the mainline policy (not deleted, not weakened):
disconnected-node warning vs refusal; eager-autosave store semantics and unique
scopes; `fingerprintProject` sync hash vs async SHA-256; `validateWorkload`
returns issues; string `objectRef` in the validation-issue contract + schema;
deterministic `nextNodeId`/`nextEdgeId` instead of the branch's `Date.now()`
id scheme (M0-02).

## Explicit non-goals

- This does not complete the 367-task tracker. It recovers the already-written
  finish work onto one coherent tree. Tracker statuses remain as audited.
- Desktop/Tauri, licensing, signed installers, real-backend provenance and
  physical/OpenROAD handoff are still open (audit M10, M4, M6 physical).
