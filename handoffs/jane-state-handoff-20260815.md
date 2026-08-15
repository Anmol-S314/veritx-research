# JANE STATE HANDOFF — 2026-08-15 ~21:40 (pre-compaction)

Author: Jane (opencode, team agent). Read this FIRST when resuming. Complete
live state, my findings, evidence locations, and best practices. Laura's
handoff (`laura-state-handoff-20260815.md`) is the sibling doc — read both.

---

## 0. THE URGENT THING (what I was doing when this was written)

No builds in flight from me — I hold the NO-BUILD lane while the box works
dave's/laura's items (ONE build at a time; box RAM is chronically tight).
My last actions:
1. Posted the **pending-state audit** (comm, 21:18): two uncommitted 113b
   fixes need committing (proposal up, laura = reviewer):
   - `noc_tb.sv:252` gmode fix (NICs idle before drain — kills the wrap-refire flood; VERIFIED by run: injected 196,552 -> 6,726)
   - `router.sv` head-guard on the S_ROUTE tail-pop path (laura's op=N fix; in the working tree, +19/-10)
2. **Verified the fixed col-0 anynet at the fabric level** (comm 21:30):
   cross-die multicast 800/800, row mcasts 700/700 — the F14 fix direction
   (bridge 56<->64) now delivers end-to-end at the model level.
3. Sent dave the **B->A turn-map analysis** (comm 21:34): opposite turns at
   the bridge node (A->B S->E vs B->A E->N) — awaiting his small-cell
   discriminator answer (which 4 B->A delivered?).

---

## 1. VERIFICATION STATE (all lanes)

### Delivery tier: GREEN (15/15) — junior's milestone 21:00
Committed tree delivers EXACTLY the BookSim targets:
- vc1 5/5 (b5 44274, b10 71832, b20 61748, b40 78947, b80 111291)
- vc2 3/3 F13-verified (b5 43860, b10 38750, b20 45401)
- vc4 5/5 (b5 43799, b10 44442, b20 43950, b40 58725, b80 71579)
All injected==ejected, SIM COMPLETE.
Three commits: b2bbc35 (F15 eject FIFO removed), 0b0d332 (F13 pid OR),
8ca1308 (VCS>=8 wall: dbg_router_t VC dim [3:0]->[7:0]).

### Open (NOT done):
- **Tier-2 TIMING (4d3b)** — laura's lane; eject FIFO removal shifted
  latency earlier (mean -14..-91). Laura's b_t2 build launched 21:19
  (tmux t2); her fix (bd5b89c) should restore exact% toward ~98%.
- **B->A (dave's lane)**: 1/4 in the small cell. My turn-map hypothesis
  sent; discriminator question pending his answer.
- **113b corner (the SA funnel wedge)**: delivery-tier cells pass; the
  general-traffic corner (501 A->B flits, 14.3%) characterized —
  fix candidates: head-guard (in tree) + dave's preemptive-VC plan
  (docs/research/preemptive-vc-bridge-fix.md).

---

## 2. MY FINDINGS & FIXES (this session)

### 113b family (my lane, all evidence-captured):
1. **NIC BRAM wrap re-fire** (the 28x flood): short traces walk the '1
   padding, wrap tptr, re-fire entry 0 forever during the drain loop.
   DBG2 proof: n73 inj=23,810 vs tptr=3. FIX: tb gmode=0 at drain start
   (noc_tb.sv:252, uncommitted). VERIFIED: injected 196,552 -> 6,726.
2. **Back-to-back xy_dor -> route2d** (router.sv:546,557): the two
   tail-pop paths routed a die-A cross-die head with die-B LOCAL coords
   (garbage route). COMMITTED (part of the 15/15 push). VERIFIED:
   A->B delivery 67% -> 85.7% (2,328 -> 2,992/3,493).
3. **Head-guard on S_ROUTE tail-pop** (laura's op=N source): body flit in
   the post-tail slot -> route2d(garbage dst) -> impossible out_port (op=N
   at row 0/2) -> SA wedge. Fix in the working tree (uncommitted).
4. **B->A turn-map**: opposite turns at (7,0) (S->E vs E->N) — the
   deadlock-family signature; sent to dave.

### F14 / anynet col-0 (my root-cause finding):
- The anynet bridge was at COL 3 (59<->67); the RTL protocol is COL 0
  (56<->64). Route tables followed the anynet -> die-B packets rolled
  east on row 7 and bounced. Steve confirmed + reverted his c1ed874;
  dave's resolution: it was a BRIDGE_COL config mismatch, NOT an RTL bug
  (fork gate 154/154 at col 0).
- MY STAGED FIX (uncommitted, team-accepted direction):
  /var/tmp/r1work/fixed_anynet/bridged_2die.anynet (bridge 56<->64,
  mesh restored 59-60/66-67, phantoms removed 56-57/64-65) +
  128 regenerated Dijkstra-exact tables in /var/tmp/r1work/fixed_anynet/tables.
- VERIFIED at the fabric level (smoke_b2die): row mcast 700/700, CROSS-DIE
  800/800 (the old anynet HUNG on cross-die).
- NOTE: the RTL currently runs DOR-with-bridge-rule (no tables) per dave's
  resolution; the tables are staged for the table path if revived.

### Area-share claim correction (done, uncommitted):
- The "routers are 95% of the die" was a documented PITFALL (hardcoded
  CSV constant + toy denominator). The current 87-90% shares are also
  vs a TOY compute base. Added noc_share_caveat to area_16/64.json +
  area_report.py + generate_dashboard.py + energy_report.py.
  Real-world anchor: FlooNoC 12nm ~3.5% of a compute tile.

### a893 — formal-proof gap (verified, escalated):
- t4-formal router_g1 snapshots are STALE: 646-line router diff, 33-line
  noc_pkg diff — proofs cover a pre-multicast, pre-bridge router. Must
  re-prove on the current RTL before any "formal" paper claim.

---

## 3. THE ASTRA-SIM SERVING LEG (my completed epic, pl-ac00 / 1ab3)

FULLY COMPLETE and committed:
- Built the booksim2 network backend for ASTRA-sim (doesn't exist
  upstream): EmbedTM API (RunCycles/InjectUnicast/InjectMcast/retire
  queues), AstraNetworkAPI wrapper, single shared fabric, event loop.
- Native BROADCAST collective implemented (upstream had "TODO: replay").
- Multicast fold: same-count fanout sends -> one stream per flit (k=3
  verified end-to-end); k=1 -> unicast fallback; snake-order far-end
  (mid-snake sources can't reach behind them — routing constraint).
- Qwen3-30B-A3B slice (12 ops, 63.7MB): analytical 10,495,246 cyc vs
  unicast 15,295,386 vs fold 13,885,374 (-9.2%). Claim-scoped per 5de1.
- Report + results: docs/research/astra-sim-serving-leg{.md,-results.json}
- Env: /var/tmp/r1work/astra-sim (master 518bd51) + protobuf 3.21.12 at
  /var/tmp/r1work/protobuf-install; build: build/astra_booksim2/build.sh.
- Follow-ups (seeds): bridged_2die fold geometry in ASTRA-sim, full-batch
  slice with flit-granularity scaling, paper framing.

---

## 4. EVIDENCE LOCATIONS (logs/dirs that prove everything)

- /var/tmp/opencode/ab_only_fix.log        — gmode fix verification (196k->6,726)
- /var/tmp/opencode/ab_only_fix2.log       — route2d fix + corner DBG4 evidence
- /var/tmp/opencode/ab_only_run.log        — the original 28x flood run
- /var/tmp/opencode/ab_only/              — the cell (trace.txt, rtl_flits.txt, hexes)
- /var/tmp/opencode/trace_evid/           — the relabeled A->B/B->A cell (5718 pkts)
- /var/tmp/opencode/bidi_cell/            — the 4-pkt bidi cell (tb-incompatible)
- /var/tmp/r1work/fixed_anynet/           — the col-0 anynet fix + tables + fixed cfg
- /var/tmp/r1work/booksim2-embed/         — fork with embed API + smoke tests
- /var/tmp/opencode/qwen_nofold.log, qwen_fold4.log — serving-leg run logs
- Builds: /var/tmp/opencode/trace_rtl_cell/vbuild_abfix (VCS=2 + fixes),
  vbuild_col0_rt (2-die table build — the 0/3663 finding)

---

## 5. BEST PRACTICES & LESSONS (compaction-proof)

### Builds / box (hard-won):
- ONE build at a time. Box = 14GB; verilator holds 8.8GB for the WHOLE
  compile phase. Free RAM below ~2GB = swap thrash; -j2 under pressure is
  SLOWER than -j1 and OOM-kills builds (today's pattern: every -j2 died).
- NEVER pkill/rm a build dir you didn't create. Each agent uses
  /var/tmp/r1work/builds/<agent>_<name>. T_DEPTH<=64 for light builds;
  T_DEPTH=2048 is the OOM class. Builds die if the launching shell is
  killed (orphans wedge with no progress).
- Build cmd (2-die, DOR): verilator -O3 -j1 --skip-identical -Wall
  -Wno-fatal -DR1_MODE --binary --top-module noc_tb -GVCS=2 -GX_DIM=8
  -GY_DIM=8 -GTWO_DIE=1 -GBRIDGE_COL=0 -GBRIDGE_ROW=0 -GT_DEPTH=64
  --Mdir <dir> noc_pkg.sv islip.sv router.sv mesh.sv nic.sv noc_2die.sv
  noc_tb.sv   (noc_2die.sv REQUIRED for 2-die builds — the standard
  rtl_r1.py file list omits it!)
- ETA rule: measure, don't guess — count .o files over 60s, extrapolate.

### Reading the RTL evidence (traps):
- DBG4 "R{x},{y}" prints (x, y) — I misread cols/rows twice. "i0" = EAST
  input, "i4" = LOCAL (0=E 1=W 2=N 3=S 4=L). cf/iu are OUTPUT-indexed
  but printed at the input index (misleading — F9 fix landed).
- The relabel script (user's) DROPS mcast range words — cells made from
  it are unicast-only; fork_delta=0.
- T_DEPTH=16 hand-made cells trip the tb's two-class trace machinery
  (phantom cl1 fires) — use real gen-trace cells or T_DEPTH>=64.

### Comms / workflow:
- comm/ is canonical; check inbox + status + alerts before building.
- Post state changes to status/decisions/alerts; commit comm/ after.
- sd: use FULL ids (veritx-research-XXXX) for show/plan; sd doctor after
  dep changes (12/12 clean now).
- Seeds: close with evidence; plan pl-ac00 closed as success.

---

## 6. OPEN WORK & OWNERS (at write time)

| item | owner | state |
|---|---|---|
| Tier-2 timing (4d3b) | laura | build in flight (tmux t2) |
| B->A small-cell | dave | 1/4; my turn-map analysis sent |
| 113b corner (SA wedge) | dave/laura | head-guard in tree; preemptive-VC plan |
| Commit 113b fixes (gmode + head-guard) | jane proposal, laura review | pending thumbs-up |
| anynet col-0 fix commit + c091 cells | dave/steve | staged + fabric-verified |
| a893 formal re-proof | TBD (tools disabled in Dockerfile) | escalated |
| ASTRA-sim follow-ups | jane | seeds filed; box-free work |
| Merge to main | steve | plan drafted |

---

## 7. NEXT SESSION CHECKLIST

1. Read laura's handoff + check tmux t2 / b_t2 build outcome (tier-2).
2. Check inbox (dave's B->A discriminator answer, laura's review of the
   commit proposal).
3. If the 113b commit proposal is approved: commit gmode + head-guard.
4. Re-run sd doctor (should be 12/12) + sd sync before pushing.

---

## 8. POST-COMPACTION SESSION (2026-08-16 00:31-01:10)

### 8.1 THE BIG FINDING: c1ed874 anynet is INVERTED from the RTL
- RTL (noc_2die.sv:116-119, BRIDGE_COL=0): bridge 56<->64; mesh 56-57 & 64-65
  REMOVED; 59-60 & 66-67 PRESENT.
- Repo anynet after c1ed874: bridge 59<->67 (col-3); mesh 56-57 & 64-65
  PRESENT; 59-60 & 66-67 REMOVED. ALL SIX LINKS INVERTED.
- My staged anynet (/var/tmp/r1work/fixed_anynet/bridged_2die.anynet) matches
  the RTL on all six — and passed the fabric verification (cross-die 800/800,
  rows 700/700+700/700).
- Consequence: die-A 60-63 unreachable from the bridge side with repo tables;
  ab55 (1-pkt A0->B64 hang at VCS=2 WITH tables) = wrong-geometry tables.
- Answered dave's question: YES VCS>=2 cross-die delivery exists —
  vbuild_abfix (VCS=2, DOR): A->B 2,992/3,493 (85.7%). The 0/3663 col-0-TABLE
  run predates b2bbc35/0b0d332/8ca1308 — NOT a valid table-path verdict.
- DECISIVE EXPERIMENT (queued for the free slot): current 15/15 tree +
  -DTWO_DIE_ROUTE_TABLE + MY staged tables + onecell (expect A0->B64 deliver).

### 8.2 Team state at resume (all read from comms, verified)
- 15/15 delivery GREEN (junior 21:00). b5_vc1 44,274/44,274 with tier-2 eject
  FIFO, 0 DBG5 violations (steve 22:07, t2b_fg). Tier-2 TIMING verdict =
  laura's gate run (exact% ~98% expected).
- junior 00:33: tree unblocked (stash-pop conflict, router.sv took HEAD;
  lint clean VCS=2; c771686 = my stray-end fix unblocked the tier-2 tree).
  Junior running b_vc2_t2 (VCS=4) rebuild NOW (box busy — no builds).
- dave 23:09: big-cell — starvation FIXED (depth-3, no isolation);
  in_use LEAK at bridge input under load OPEN (F15/4d3b family, team-level).
  Evidence: results/trace_pipeline/bigcell_d3_findings.json.
- head-guard + gmode COMMITTED (bd5b89c + noc_tb.sv:253) — my 21:18 audit
  was stale. bd5b89c eyeballed: copy-bit credit gate correct
  (eject_credit.valid = eject.valid && !eject.flit.copy).
- gate_policy.json EXISTS (configs/, legacy override documented).
- ce40 (F3) CLOSED by team 16:08 with the same declare-scope decision I
  independently posted (paper_draft.md:411). 30bd (F5) open; t4 caveat added.
- F9 (889f): 409f1f7 debug wiring eyeballed OK (noc_mesh-pattern consistent).

### 8.3 This session's deliverables (all committed)
- comm/topics/alerts/2026-08-16-0108: c1ed874 inversion + dave's answer
- comm/topics/decisions/2026-08-16-0109: F3 single-flit scope (confirms)
- tracks/t4-formal/README.md: contract caveat (F5/30bd, a893 re-proof note)
- comm committed; seeds synced.

### 8.4 Next-session checklist
1. Box: junior b_vc2_t2 (VCS=4) then vc4 (VCS=8) — vc1 regens via t2b_fg.
2. When a slot frees: the DECISIVE ab55 EXPERIMENT (8.1) — my top priority.
3. dave's B->A discriminator answer + laura's tier-2 verdict pending.
4. in_use leak (F15/4d3b family): laura's stale in_use race (09bb908) +
   dave's cfW0 iuW1 occ=0 = the bridge-funnel wedge (f3839c2).
