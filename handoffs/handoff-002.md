# Handoff 002 — F15 era (2026-08-14 evening; follows handoff-001.md)

Numbered handoff series. Next: handoff-003.md. This session changed the
project's understanding of its own evidence — read §2 carefully.

---

## 1. Where the work stands (one paragraph)

The two-tier gate (T3-002) is implemented, committed, spec-verified
(sweep --gate mode, negative tests, manifest provenance). The 15-cell
acceptance is **VOID** — its vc1 dumps came from a lost WIP binary.
The committed F2-era RTL (edec5c1+4f951e1+HEAD) has ONE delivery-bug
family (F15, veritx-research-69a0): the corpus deadlocks (2327/346) and
gf_2cls loses 1 flit (2823/2824). Laura owns the fix (F2 reorder corner,
handed to her with the exact delta + repro). F13 fix (bd32694, pid
0x8000+ base) stands — proven innocent via revert build. Everything
after Laura's fix must be regenerated from committed sources.

## 2. THE PATTERN (read before trusting ANY old evidence)

**Every "gold" datum on this project came from binaries matching NO
committed tree**: (a) the 0/0 fluke (GATE-R1-COORD §7.1), (b) the 99.85%
trust test, (c) gf_2cls "928/2824 exact" (13/8), (d) the 10:17 vc1 dumps
(44,274 timing-exact). Verification binaries were built from WIP states
(Laura edited RTL continuously; the 13/8 16:05 b_1die was 20 min before
4f951e1 committed). Rule going forward: **regen + gate ONLY from committed
trees; record the binary git SHA + mtime in the acceptance manifest.**

## 3. F15 — the bug family (reproducible, deterministic)

- **Symptoms**: post-edec5c1 binaries on corpus cells: b5/b20/b40/b80_vc1
  injected=2327 ejected=346, ALL 64 nodes pend=1, tptr parked 5-16, ej
  flat from ~t=10k, drain check $fatal noc_tb.sv:324. gf_2cls: 928/2823.
  gf_8: 154/154 PASS (unaffected). b10_vc1 runs crash before any output
  (empty log, old dump intact) — possibly Steve's empty-trace/garbage-hex
  case, uninvestigated.
- **Bisect result**: edec5c1 == 4f951e1 == HEAD == HEAD-minus-pidfix, all
  2327/346. Pre-F2 ladder binaries (vbuild_vc1test 18:18, vbuild_restored
  08:23 13/8, in /var/tmp/r1work/) DELIVER 44274/44274 (wrong timing, but
  no deadlock). F13 pid fix (bd32694) proven innocent twice (revert build
  stalls identically).
- **Root-cause delta (nic.sv fire/reorder block)**: WORKING (src/nic.sv):
  ord={1,0} reorder requires tptr entry ALREADY pending + (tick_r+1) >=
  due(tptr+1) + due_1 <= due_0 (or exact +1 with tptr pending) —
  deferred-unblock, bounded. F2 (HEAD): reorder requires BOTH not-pending,
  both due at tick_r, fires tptr+1 first; deferred tptr retries via the
  claimed-VC exclusion (pick_vc exclude=claimed) — anticipatory swap,
  unbounded retry. The corpus two-class UNICAST cells (dense same-cycle
  pairs, no range words) expose it; gf_2cls (mcast-heavy) nearly misses it.
- **Fix direction (Laura's lane)**: restore tptr-pending precondition or
  bound the claimed-exclusion retry. Do NOT touch RTL yourself (rule 3 +
  her lane); she has the repro (b5_vc1 + b_1die HEAD, cwd=cell dir).

## 4. Verified state — CURRENT TREE (committed, reproducible)

| Test | Result |
|---|---|
| gf_8 (fork, g=8) | 154/154 flits, SIM COMPLETE on HEAD (b_1die 11:51) |
| gf_2cls | 2823/2824 — F15 (1 flit lost) |
| corpus vc1 (b5/b20/b40/b80) | DEADLOCK 2327/346 — F15 |
| corpus b10_vc1 | runs crash pre-output (hex/garbage suspicion) |
| F13 fix lint | verilator --lint-only --timing: 0 errors |

**VOID evidence** (do not re-cite): docs/research/gate-acceptance/vc1-pass/
(5/5 PASS at 11:30 — stale-binary dumps), the "0.79 override obsolete"
claim (same dumps), gf_2cls "2824 exact" (13/8), any ratio numbers sent
11:29 (bs/rtl inversion fixed 21:21 — recheck any report you reuse).

## 5. Tooling state (all committed)

- rtl_r1.py: gate + sweep --gate (spec §8.2), UNICAST_PID_BASE=0x8000
  pairing (F13 lockstep), ratio rtl/bs (laura review), O2 = N/A not False
  when vc4 absent, always-writes manifest w/ per-cell input mtimes, git
  root resolved from script (was empty-SHA bug). Negative tests verified:
  corrupt flits -> FAIL (t1.2), short reason -> rejected.
- gate_policy.json: b5_vc1 override LEGACY (superseded by F15-era; do NOT
  re-apply the old 0.79 story).
- spec two-tier-gate-spec.md §8.4: known numbers updated to vc1 acceptance
  — NOW ALSO SUPERSEDED by F15 (vc1 acceptance void). Update again post-fix.
- Seeds: F15 = veritx-research-69a0; F13 = ee61; deadlock = 0344; T3-002
  updated. sd doctor clean. Tracker fixed (T3-era schema migration).
- Mulch: domains veritx-rtl-gate / veritx-workflow / veritx-corpus with
  F13, F14, F15, build-box rules, corpus map, comms protocol records.

## 6. Comm channel (MANDATORY ritual every session)

comm/ in the repo (canonical — my earlier /var/tmp/r1work/agent-comms is
deleted). `bash comm/check.sh junior` (inbox), `read.sh status|alerts`,
`send.sh -f junior <to> "subj" <<EOF`, `publish.sh -f junior <topic> ...`.
Commit comm/ after sending. Roster: laura=RTL/deadlocks, dave=trace+paper
framing, steve=hygiene/lit, junior=T3-002 gate+corpus.

## 7. Environment rules (still enforced)

14GB box, ONE build at a time — ABSOLUTE, even -j1 vs -j1 (I OOM-killed
the b_vc4 VCS=8 build at make/pch 12:32 with a concurrent -j1 elab).
All artifacts under /var/tmp/r1work (never /tmp). setsid/tmux for long
runs. pgrep -f self-match trap. RTL edits commit-first. Sims: cwd MUST
be the cell dir (the TB reads trace_n*.hex + writes rtl_flits.txt
relative to cwd — my wrong-cwd regen "passed" with 0 flits: the
0==0 drain check self-certifies empty loads! Steve's empty-trace seed
is the fix; verify R1 totals injected > 0 on every run).

## 8. Next actions (in order)

1. Wait for Laura's F2 reorder fix (she has the delta + repro).
2. Rebuild b_1die from HER committed fix; regen gf_8 + gf_2cls + 5 vc1
   cells (cwd=cell! verify totals injected==ejected+fdelta, SIM COMPLETE).
3. Regate gf_8/gf_2cls/vc1-5. Then vc2 (needs F13-verified binary — b_vc2
   exists 23:12 13/8, rebuild after fix) + vc4 (VCS=8 build: retry ALONE,
   elab succeeded 12:32 — the wall is OOM-at-make, not codegen; Aug-11
   lvalue error was a stale log).
4. Re-run the full 15-cell gate from committed sources; update spec §8.4,
   retract/refresh the void acceptance dir, send the fresh numbers to
   laura/steve/dave for sign-off. T3-002 closes only on all-three sign-off.
5. Track F13 verification (vc2 cells) + the VCS=8 retry in seeds.
