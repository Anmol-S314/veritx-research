# Merge Plan: t3-rtl-noc → main (291 commits)

**Status: draft v1 (2026-08-15, Steve). Policy item from seed 319e — the safety
net exists (t3-rtl-noc-backup-20260815 = f8ab4a6, verified); the merge is the
follow-on. Owner: dave (review) / steve (draft). Not urgent — backup is the
risk mitigation.**

## The situation

- `t3-rtl-noc` is **291 commits ahead of main / 29 behind** (measured 2026-08-15
  09:46, junior). The 29 behind = main-only commits (CI infra, registry points,
  timeloop work) that must be merged INTO the branch first (or the merge
  conflates unrelated histories).
- The branch carries the F13/F14/F15 work, the col-0 protocol, the gate
  implementation, the serving-leg results, and the coordination infra
  (comm/, .seeds/.mulch, build_lock, toolchain-provenance).
- GitHub origin is current (main + the backup branch); internal GitLab
  (datavex) is the real CI and was unreachable from the box earlier.

## Preconditions (gate criteria — the branch merges only when these hold)

1. **F15/tier-2 settles**: the unicast corpus is at 100% delivery (5/5 vc1) with
   Tier 1 CLEAN; Tier 2 (timing envelope) must pass after the leak-free eject
   queue lands (seed 4d3b) — the eject path is the timing model.
2. **Fork path restored**: gf_8/gf_2cls deliver after the F1 re-fix (copies
   currently dropped — b2bbc35).
3. **The table-path question closed**: either the col-0 protocol runs DOR (the
   working path) and the table machinery is documented as unused, or the table
   consumption bug (jane's 0/3663) is fixed. Do NOT merge with an unresolved
   "the tables never delivered" claim in the branch.
4. **col-0 1% corner**: resolved or explicitly scoped (wrap re-fire fix pending
   — the gmode line — plus the die-B Y-first corner check).
5. **vc2/vc4 cells**: at least one VCS≥4 cell gates (the vc4 build is in
   flight; df18 confirmed builds succeed alone — the OOM class was the wall).

## Merge mechanics

- **Direction:** first merge main → t3-rtl-noc (the 29 behind), resolve
  conflicts (likely: README, CI files, .gitignore — small), THEN merge
  t3-rtl-noc → main.
- **Strategy:** `--no-ff` feature merge (keep the branch history visible);
  do NOT squash — the per-commit evidence trail (fixes with artifact
  references) is the credibility record.
- **CI:** the internal GitLab pipeline gates the merge (5-cell matrix). The
  merge must not land before a green run on the merged tree.
- **Results:** results/ stays gitignored (reproduced, not committed); the
  committed artifacts (FINDINGS, serving-leg docs, seeds) carry the evidence.

## Sequencing

1. F15/tier-2 eject-queue lands + vc1 tier-2 passes → branch checkpoint A.
2. F1 re-fix (fork copies) + gf cells pass → checkpoint B.
3. col-0 1% resolved or scoped + vc4 cell gates → checkpoint C.
4. main → t3-rtl-noc (rebase the 29), CI green on the merged tree.
5. t3-rtl-noc → main, --no-ff, record the merge decision in comms + seeds.

## Risks / notes

- The 291-commit gap is large; review burden is real — the per-commit
  evidence discipline (every fix cites its artifact) is what makes this
  reviewable at all.
- The branch is the current source of truth for the RTL; merging it changes
  what CI runs on main — the 5-cell matrix on a green merged tree is the gate.
- If internal GitLab remains unreachable, GitHub Actions (stale since 07-01)
  needs a pipeline restore before the merge — flag for dave.

## Decision record

- 2026-08-15: backup refreshed + approved (junior 09:46); merge deferred to
  post-F15/tier-2 per the preconditions above.
