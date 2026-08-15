# Handoff 003 — FULL STATE DUMP (2026-08-15 ~22:00, pre-compaction)

Series: handoff-001.md, handoff-002.md, handoff-003.md (this). Read 001/002 for the
earlier eras; this file is the canonical CURRENT state + ALL best practices.

---

## 0. TL;DR — where everything stands

The 15-cell corpus DELIVERY tier is fully verified on the committed tree
(injected==ejected==BookSim targets, all SIM COMPLETE). The only remaining
gate item is TIER-2 TIMING: Laura's leak-free eject queue (4d3b) — committed
(bd5b89c, f794d89) but the tree was BROKEN by her FIFO placement (stray end
in router.sv) — I fixed + committed it (c771686). Next: build + verify her
tier-2 verdict (b5_vc1 exact% ~98%), then rebuild all 3 binaries, regen 15
cells, full gate, team sign-off.

## 1. THE FIXES (all committed, artifact-backed)

| Fix | Commit | What |
|---|---|---|
| F15 delivery (eject FIFO removed — it stalled unicast corpus) | b2bbc35 | Laura's bisect: FIFO's blocking-assign side effects killed single-die burst cells |
| F13 pid OR (real fix) | 0b0d332 | `16'h8000 | (tptr+idx)` — the concat `{1'b1,4'h0,tptr+idx}` is 37-bit (idx is int) and truncated the 0x8000 bit; bd32694 was a silent no-op |
| VCS>=8 wall ROOT CAUSE | 8ca1308 | dbg_router_t hardcoded VC dim [3:0]; at VCS=8 the debug assigns index v=0..7 OOB → verilator 5.032 "lvalue required" codegen. Widened to [7:0]. (My earlier "stale RTL" conclusion was WRONG — it was our struct all along.) |
| DBG4 print port-index bug | (committed ~19:0x) | DBG4 read credit_free/in_use at INPUT index — arrays are OUTPUT-indexed; showed EAST's state for a LOCAL input (misled the 113b evidence read) |
| F9 debug wiring (2-die) | (committed) | noc_2die.sv dangling .dbg() ports → DBG2/3/5 dead in TWO_DIE; wired through (mirrors mesh.sv) |
| router.sv stray end | c771686 | Laura's FIFO placement (f794d89) left an extra `end` — ALL builds broke; removed |
| Gate report ratio rtl/bs | (committed) | Overall md column was bs/rtl (Laura review); per-class was already right |
| sweep --gate mode, manifest fixes, O2 N/A | (committed) | Spec §8.2 compliance; manifest always written w/ per-cell mtimes; git-root resolution fix |

F13 VERIFIED CLOSED (ee61): b5_vc2 43860/43860 (was 20503), b10_vc2 38750/38750
(was 578), b20_vc2 45401/45401 (was 668) — all exact BS targets, 0x8000+ pids.

## 2. THE 15-CELL MATRIX (verified delivery, targets locked)

| Cell | BS target | Status |
|---|---|---|
| b5_vc1 | 44,274 | ✓ exact |
| b10_vc1 | 71,832 | ✓ |
| b20_vc1 | 61,748 | ✓ |
| b40_vc1 | 78,947 | ✓ |
| b80_vc1 | 111,291 | ✓ |
| b5_vc2 | 43,860 | ✓ (F13) |
| b10_vc2 | 38,750 | ✓ (F13) |
| b20_vc2 | 45,401 | ✓ (F13) |
| b5_vc4 | 43,799 | ✓ (wall broken) |
| b10_vc4 | 44,442 | ✓ |
| b20_vc4 | 43,950 | ✓ |
| b40_vc4 | 58,725 | ✓ |
| b80_vc4 | 71,579 | ✓ |

Binaries (my builds, in /var/tmp/r1work/fork_gate/builds/):
b_1die_f13 (VCS=2), b_vc2_f13 (VCS=4), b_vc4_v2 (VCS=8, 93MB). ALL STALE after
Laura's tier-2 fix lands (router.sv changed) — rebuild from git archive HEAD.

## 3. TIER-2 (the only remaining gate item)

- 4d3b: eject queue (leak-free FIFO re-add) — Laura's. Committed bd5b89c +
  f794d89 (placement) — tree was broken; I fixed (c771686). Her targets:
  b5_vc1 exact% ~98% (vs 13% broken), delta flattened from −14..−91.
- Gold regression targets (from the 10:17 unicorn-era dumps — locked in 4d3b):
  b5_vc1 cl0 ratio 1.0 (56.62/56.61), cl1 1.0 (44.08/44.10), exact 98.12%,
  mean Δ −0.0049, p95 0, max 72. Post-fix b5 must land within mean Δ ±1.
- After her verdict: rebuild ALL 3 binaries from git archive HEAD → regen 15
  cells (cwd=cell!) → full gate → team sign-off (laura/steve/dave).

## 4. BEST PRACTICES / TRAPS (READ — these cost real hours)

1. **Build from `git archive HEAD` sources, NEVER the working tree** — the
   working tree held Laura's uncommitted shims twice; my "clean" builds
   silently used them (empty-SHA-style contamination).
2. **`--skip-identical` + fresh Mdir**: verilator's incremental Mdir reuse
   MIXED old elaboration objects (h7ddd480a hash family) — the binary had
   old pid code. Always rm -rf the Mdir for a clean build.
3. **SV concat width trap**: `{1'b1, 4'h0, tptr+idx}` with `int idx` = 37
   bits → truncated to 16 — the 0x8000 bit died silently. NO error, NO
   warning. Use explicit-width ops (`16'h8000 | (tptr+idx)`).
4. **DBG print index trap**: credit_free/in_use are OUTPUT-indexed; the old
   DBG4 read them at the input index — wrong port's state. Fixed.
5. **Empty-trace self-certification**: with no trace hexes in cwd, $readmemh
   fails silently → all-'1 traces → 0 injects → drain check 0==0 PASSES →
   "R1 SIM COMPLETE" with 0 flits. ALWAYS verify injected>0 + totals match.
   (Steve's sentinel seed + d604 lint are the mitigations.)
6. **cwd matters**: the TB reads trace_n*.hex and writes rtl_flits.txt
   relative to CWD — always `(cd <cell> && binary +run_cycles=...)`.
7. **ONE build at a time — ABSOLUTE** (even -j1 vs -j1 OOMs: 4 deaths today).
   Check ps BEFORE launching. Steve's scripts/build_lock.sh (f2329fc) exists.
   -j2 builds died 100% of the time at the g++ stage.
8. **VCS=8 elab peaks ~9.4GB** — the make stage after it needs the elab
   freed; watch RAM (free -g), be ready to retry with --skip-identical
   (elab done = retry is make-only).
9. **pgrep -f self-match** trap — use binary checks, not pgrep -f.
10. **Rule 3 (commit-first)** — RTL edits commit before verification; a
    dirty tree voids results (manifest says so loudly).
11. **The mcast pid space is (word<<4)|offset** (code at nic.sv, NOT the
    stale <<3 comment); unicast now at 0x8000+ — disjoint by construction.
12. **git archive is SLOW (~10-30s)** — don't combine with a 30s shell
    timeout (it truncated the extraction twice and I built garbage).

## 5. TEAM + COMMS (mandatory ritual every session)

- comm/ in the repo: `bash comm/check.sh junior` (inbox), `read.sh
  status|alerts|decisions|questions`, `send.sh -f junior <to> "subj" <<EOF`,
  `publish.sh -f junior <topic> "subj" <<EOF`. Commit comm/ after.
- Roster: laura=RTL/deadlocks/tier-2 (senior on R1), dave=bridge/2-die +
  paper framing, jane=ASTRA-sim serving leg + col-0, steve=hygiene/lit/
  tooling, junior=T3-002 gate+15-cell corpus+scripts.
- Roles: I'm the junior (gemini). The programme lead = the user.
- Update board/status on material changes. Mark messages READ when done.

## 6. OPEN ITEMS (lanes)

- 4d3b tier-2 eject queue (laura) — THE blocker for the gate. Tree fixed
  (c771686) — needs her build + verdict.
- 113b col-0 corner (dave/jane): B→A funnel — my turn-map correction
  (E→S not E→N) + audit signature sent; dave_d3_64 build in flight.
- c4d3 driver dedup (scripts) — deferred (live scripts, mid-crisis).
- 77e6 dead script cluster — contested (author call needed).
- 319e backup: pushed (Steve); merge plan for 291 commits = policy item.
- T3-004 contention / T3-005 seq-512 / T3-006 g-sweep — queued behind the gate.
- The t4-formal snapshots (a893) — stale, jane verified.

## 7. ENV FACTS

- 14GB box, opencode sessions eat ~2.3GB. avail RAM varies 0-10GB.
- Cells: /var/tmp/r1work/cells/b{5,10,20,40,80}_vc{1,2,4} (inputs intact).
- Fork cells: /var/tmp/r1work/fork_gate/cells/{gf_8,gf_2cls,gf_bridge_*}.
- Pipeline: /var/tmp/r1work/postfix_pipeline.sh (regen+gate w/ guards).
- Locks: /var/tmp/r1work/locks/build (mkdir=acquire, rmdir=release).
- Seeds: .seeds/issues.jsonl (sd create/update/close/dep; sd doctor clean).
- Mulch: .mulch/ domains veritx-rtl-gate / veritx-workflow / veritx-corpus.

## 8. NEXT ACTIONS (in order)

1. Watch for Laura's tier-2 verdict (her build of c771686 tree) — she may
   need to re-verify b5_vc1 (exact% ~98% expected).
2. Rebuild b_1die_f13, b_vc2_f13, b_vc4_v2 from git archive HEAD (one at a
   time, lock, --skip-identical NOT needed for fresh Mdirs — but the Mdirs
   are fresh: rm -rf each first).
3. Regen all 15 cells (postfix_pipeline.sh), verify against the locked
   targets (Section 2), then the full two-tier gate.
4. Send the acceptance to laura/steve/dave for sign-off; T3-002 closes on
   all-three agreement.
5. Then: F8/T3-003 closure (leak fixed by the queue), T3-004 contention,
   T3-005/006, and the 291-commit merge plan.

## 9. JANE'S EXAMPLE (do the same at session end)

Jane committed her state handoff (afb9649) before compaction — I'm doing the
same here. On any further crash: git log + comm/ + handoffs/ hold the truth.
