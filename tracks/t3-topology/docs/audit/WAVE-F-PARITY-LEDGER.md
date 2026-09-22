# Wave-F parity ledger (QUEUED — post-seal task, do not start before the seal)

**Status:** queued, not started. This file is an evidence-only artifact; it
must not be merged into the seal candidate and no Wave-F code may be
ported until `p1-product-integration-seal-v2` exists.

**Why queued:** the RT-final closure campaign's binding law forbids
feature work that is not strictly required to repair a demonstrated P1
closure invariant. Wave-F parity is capability recovery, not closure.

**Branch:** `wave-f/design-optimization` @ `d178c90e` — 3 unique commits
vs the candidate (`f34a4361`, `a571a184`, `d178c90e`); everything else on
that branch is contained.

## Observed footprint of the 3 unique commits (facts, not claims)

| Commit | Subject | Substantive files |
|---|---|---|
| `f34a4361` | design optimization as an orchestration layer over the sealed control plane | `optimization/*` (new wave), `application/service.py` (+87), `application/store.py`, `tests/test_optimization_core.py` (663), `tests/test_optimization_e2e.py` (534), `tests/veritx_e_helpers.py`, `docs/WAVE-F-SCIENTIFIC-CONTRACT.md`, `docs/WAVE-F-SEAL-REPORT.md` |
| `a571a184` | post-commit audit gaps: reuse accounting, ALIAS/INVALID coverage, §89 differential | `optimization/orchestrator.py`, `optimization/result.py`, tests +214 |
| `d178c90e` | pre-seal verification and evidence gaps | `optimization/{__init__,definition,metrics}.py`, tests +~600, contract +144 |

Wave F was written against the pre-consolidation Wave-D/E packages and its
own seal report states it must be replayed onto `WorkloadGraph`,
`performance/*`, and the final application/persistence domains. **Do not
merge the branch.** Parity-port per capability.

## Parity checklist (each row needs: exists? where? equivalent semantics? tests?)

- [ ] multi-scenario optimization
- [ ] canonical candidate accounting (reuse accounting)
- [ ] ALIAS / INVALID / NOT_EVALUATED candidate semantics
- [ ] EXHAUSTIVE_GRID vs BUDGETED_GRID search modes
- [ ] search/frontier completeness accounting
- [ ] scenario-scoped metrics
- [ ] verified metric registry (`optimization/metrics.py`)
- [ ] evidence-bound failure statuses
- [ ] explicit selection policies
- [ ] tie preservation
- [ ] persisted optimization-definition / optimization-result artifacts
- [ ] `load_verified_optimization_result()` (full result re-derivation)
- [ ] Wave-C store integration (`application/store.py`, `service.py`)

## Method (per capability, no exceptions)

1. Read the Wave-F implementation and its tests; state the invariant.
2. Locate the candidate's current equivalent (expected homes:
   `optimization/definition.py`, `optimization/result.py`,
   `optimization/real_evaluator.py`, `contracts/srota/v2/`,
   `application/requirements.py`).
3. Classify: `PRESENT_EQUIVALENT` / `PRESENT_WEAKER` / `ABSENT` /
   `SUPERSEDED_BY_DESIGN` (with the design reason).
4. For `PRESENT_WEAKER`/`ABSENT`: port the capability onto the current
   authorities — never resurrect the old package layout, never bypass the
   verified-result boundary or the v2 contract.
5. Every ported capability needs a positive test and an adversarial
   negative test, and must not weaken any RT-closure invariant (no
   self-declared certification, no fabricated metrics, three-state
   verdicts preserved, requirement provenance bound).

## Start here when unblocked

`optimization/CAPABILITY-LEDGER.md` (written during P2) already contains a
first-pass classification of wave-F items (`REPLAY` / `REJECT`-deferred /
`HISTORICAL`) — reconcile this checklist against it before writing new
code, so the post-seal tranche starts from recorded evidence rather than a
fresh audit.

## Also queued with this ledger (non-code)

- Archive tags before any branch deletion: `serving-leg` `ffee3333`,
  `epic/booksim-forward-port` `e7c66d7e`, `t3-rtl-noc-backup-20260814`
  `eaa5b2c3`, `t3-rtl-noc-backup-20260815` `f8ab4a63`,
  `wave-f/design-optimization` `d178c90e`.
- Worktree collapse to two (`veritx-research` + one engineering tree)
  after: worktree audit clean, `veritx-p1`'s uncommitted
  `fabric_evaluator.py` + two untracked test files resolved, every
  candidate branch pushed.
