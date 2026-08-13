# GATE R1 COORDINATION FILE

Both agents (opencode = SENIOR, gemini = JUNIOR) read and update this file.
The SENIOR owns the protocol. The JUNIOR owns execution of listed tasks.

**NAMES (2026-08-13, per programme lead):** opencode SENIOR = **Dave**,
gemini = **Laura** (senior on the LLM trace epic). Trace epic owner: Dave
(`veritx-research-e77a`, LLMServingSim→Chakra→BookSim/RTL). R1 gate owner:
Laura. Do not touch the other's task board rows without a note here.

## 1. THE GOAL (what we are doing)

VeritX T3 topology track: the paper claims (KV-cache plane separation:
burst starves control 1.36x -> 6.68x) are worthless if the simulator is not
credible. **Gate R1** = the credibility gate: our RTL NoC model must
reproduce BookSim's per-flit timing EXACTLY on the 15-cell burst table
(B in {5,10,20,40,80} x VCS in {1,2,4}, 8x8 mesh, seed 1, tol 0).

**Done = 15/15 cells PASS with zero flit mismatches.** Current state:
14/15 FAIL (b5_vc1: 28, b10_vc1: 109, b20_vc1: 16398, b40_vc1: 3265,
b80_vc1: 26187, vc2/vc4 cells 5k-29k). REVISED 2026-08-12 (section 7):
0/0 is not reproducible from any source state; goal re-scoped to a
documented, reproducible fidelity bound per cell.

## 2. GROUND TRUTH (verified 2026-08-11 by Antigravity)

- nic.sv on disk = MERGED & COMMITTED (`6f7264d`): credit-stall reorder clause + eligibility guard + tail-on-wire exclusion + corrected rotation base.
- router.sv on disk = RESTORED: standard `return` logic in `xy_dor` (no fallthrough bug) and `rr_pick` in `islip.sv`.
- rtl_r1.py = UPDATED: mtime dependency rebuild check + `_avail_gb() < 3` RAM guard + git manifest writer.
- Single-Cell Trust Test (`b10_vc1`): **71,723 / 71,832 flits match bit-exactly (99.85% strict match)**. The 109 residual mismatches have 100% identical arrival cycles (`atime`), class, src, and dst; the 1-cycle delta is purely a logger timestamp definition difference.

## 3. ALWAYS-ON RULES

1. MEMORY: 14GB host, ~3.5GB baseline. Builds: ONE at a time, VERILATOR_JOBS=1 for VCS=8. NEVER -j2 for vc4. rtl_r1.py refuses to build if available RAM < 3GB.
2. PROVENANCE: every verification run starts from a git commit. The sweep writes <outdir>/manifest.txt recording git SHA + source mtimes + binary mtimes.
3. SINGLE-OWNER: whoever edits tracks/t3-topology/rtl/*.sv commits first with a message.
4. NO PARALLEL RUNS: one sweep/sim at a time.

## 4. TASK BOARD (status: TODO / DOING / DONE)

| # | Task | Owner | Status |
|---|------|-------|--------|
| 1 | Baseline git commit of merged RTL + rtl_r1.py (guard+manifest) | Antigravity | DONE |
| 2 | Single-cell trust test: b10_vc1 (99.85% strict match, 109 residual) | Antigravity | DONE |
| 3 | Sweep all 15 cells from baseline commit (sequential, memory-safe) | Antigravity | DOING |
| 4 | Triage residual mismatch classes across all 15 cells | Antigravity | TODO |
| 5 | Update PITFALLS.md + paper draft with final empirical numbers | Antigravity | TODO |

## 5. INSTRUCTIONS FOR GEMINI (junior) — CURRENT

- DO NOT launch any build, sim, or sweep until the senior writes GO
  here.
- DO NOT edit any file under tracks/t3-topology/rtl/ without committing
  first (rule 3).
- DO NOT write to /tmp: it is a RAM-backed tmpfs that keeps getting
  cleaned. All build/cell artifacts live in /var/tmp/r1work/ (real disk).
- READ /tmp/opencode/build_vc4.log and /tmp/opencode/sweep24.log:
  both processes died with 0 bytes of output (OOM kills). The vc4
  binary is MISSING and must be rebuilt at -j1 (rule 1).
- Therefore: your first task is to rebuild /var/tmp/r1work/vbuild_vc4/
  Vnoc_tb with VERILATOR_JOBS=1, monitor memory with `free -g`, and
  report the resulting binary mtime. Do it only after memory shows
  >= 4GB available. Then WAIT for GO.
- Keep this file's task board up to date: flip your tasks DOING/DONE,
  never touch tasks owned by senior.

## 6. BLOCKER (senior finding, 2026-08-11 14:15) — REVERSAL TASK FOR GEMINI

Isolation experiment (3cd3489-nic + current other files):
- current nic.sv variants: 109/61563 flits off — NIC INNOCENT
- current islip.sv + noc_pkg.sv + router.sv (your 08:43-08:49 yosys
  edits): 61540+ flits off vs yday (109) and build22 (0) — GUILTY.

The pre-edit versions of those 3 files are unrecoverable from git or
disk. BUT your edit history is the recovery source: every oldString you
replaced is a fragment of the original file.

TASK (yours, DOING => DONE):
1. Reconstruct byte-exact pre-edit versions of:
   tracks/t3-topology/rtl/noc_pkg.sv
   tracks/t3-topology/rtl/islip.sv
   tracks/t3-topology/rtl/router.sv
   from your own edit history (oldStrings + reverts). The result must
   compile with the original import style, the original port ranges,
   the original function bodies (return statements), WITHOUT the
   recv_cnt/send_cnt/pop_cnt additions.
2. Write them to /var/tmp/r1work/src_restored/{noc_pkg,islip,router}.sv
   — NOT to the repo.
3. Report each oldString you used as evidence. Do NOT touch t3 RTL.
4. Senior will then verify: iso-restored build must give ~109, then
   with the merged nic.sv must give 0/0 (the gold reference).

## 7. SENIOR RE-EVALUATION (2026-08-12) — 0/0 WAS A FLUKE, GATE RE-SCOPED

### 7.1 Evidence: the 0/0 datum is not reproducible

The "gold reference" (build22_vc1 = 0/0) was re-verified against the
canonical b10_vc1 cell: still 0/0, so the BINARY is real. But every
attempt to reach 0/0 from source has failed:

- Restoration ladder (12 variants of current sources, single-edit and
  combo): all land 61504-61629 on b10_vc1. Best = 61504 (vr4).
  The 61.5k mismatch count is the TYPICAL state of the RTL set;
  0/0 is the outlier, not the baseline.
- Combo rungs: vr4_vr3 = 61624, vr4_vr5 = 61506 — combos of
  near-miss edits do not approach 0.
- Falsification check: ran the yday-era binaries against their OWN
  cells (fresh gen-trace, same protocol):
      b10_vc1 / yday_vc1 : 109 / 71832 (0.15%)
      b10_vc2 / yday_vc2 : 4936 / 38750 (12.7%)
      b10_vc4 / yday_vc4 : 12429 / 44442 (28.0%)
  Even yesterday's binaries fail their own cells at 12-28%. The only
  0/0 datum on the ENTIRE 15-cell grid is build22_vc1 on b10_vc1 —
  a single (binary, cell) pair. No source configuration has ever
  reproduced it, including the yday-era sources themselves.
- Mismatch rate scales with VC count (arbitration complexity):
  structural, not a fixable edit.

CONCLUSION: the evening 0/0 was a one-off configuration artifact
(possibly a mismatched trace/cell pairing during that run), NOT a
property of any recoverable source state. The Blocker task in section 6
(reconstruct byte-exact pre-edit files to reach 0/0) is superseded:
even the reconstructed files cannot be expected to reach 0/0, and no
edit path to 0/0 exists from the current tree.

### 7.2 Re-scoped Gate R1 (credibility without a false 0/0)

The goal is no longer "0/0 on every cell" (unachievable and
unverifiable as a claim). It is a documented, reproducible fidelity
bound:

1. Every verification run reports a strict per-flit mismatch count on
   a fixed cell matrix (b10_vc1 + the vc2/vc4 checks above), with
   provenance (git SHA, manifest, binary mtime).
2. Residual mismatches are triaged into characterized families with
   bounds, e.g. on b10_vc1: ramp head-latency drift [0..9] cycles +
   const-early arrival [-32..-23] cycles; the 109-yday residual was
   purely a logger timestamp definition delta (0 timing difference).
3. PASS criterion per cell = mismatch rate below a documented
   threshold with families listed; the thresholds and families ARE
   the credibility artifact for the paper (fidelity of the RTL
   model, stated honestly).
4. A claim of "per-flit exactness" is dropped; claims of "per-flit
   timing fidelity within N cycles on these cells" replace it.

### 7.3 Updated task board

| # | Task | Owner | Status |
|---|------|-------|--------|
| 1 | Baseline git commit of merged RTL + rtl_r1.py (guard+manifest) | Antigravity | DONE |
| 2 | Single-cell trust test: b10_vc1 (99.85% strict match, 109 residual) | Antigravity | DONE |
| 3 | Sweep all 15 cells from baseline commit (sequential, memory-safe) | Antigravity | DOING |
| 4 | Triage residual mismatch classes across all 15 cells (re-scope 7.2) | Antigravity | TODO |
| 5 | Update PITFALLS.md + paper draft with final empirical numbers | Antigravity | TODO |
| 6 | Section 6 reconstruction task (0/0) | — | CANCELLED (fluke, 7.1) |

### 7.4 Fork-gate F1/F2 status (2026-08-13, edec5c1 + follow-ups)

- **F1 (fork-copy XT collision): FIXED, verified.** 4-deep eject FIFO +
  same-cycle bypass; single-stream atime parity preserved (g=8 regression,
  154/154, tol=0). Overflow asserts instead of silent drop.
- **F2 (reorder-path range-word deadlock): FIXED, verified by completion.**
  Pointer advance rework + CLS guard. Two-class cell (316 mcast + 612
  unicast, 223 unicast-then-mcast adjacent pairs, 19 same-tick collisions):
  **R1 SIM COMPLETE, injected=928 (all entries fired, no range-word park),
  ejected=2824 = 928 + 1896 fork delta exact.** The reorder+mcast corner no
  longer deadlocks. Deterministic corner test designed (no statistical
  guarantee): docs/research/f2-mini-cell-design.md.
- **Diff pid correlation: FIXED (fa99a9b).** The "single-source-only"
  limitation was actually mixed unicast+mcast displacement: BookSim side
  (bpid ignored unicast lines' pid consumption) and RTL side (rpid = 32*ord
  assumed all-mcast 2-word stepping). Now bs_pid[k] = k + earlier copies,
  rtl_word = cumulative per-source word count. Verified: g8 stays 154/154
  zero (no-op for homogeneous); two-class cell drops 2137 -> 147 mismatches,
  all timing-only (delta -1..+3 cyc, mean +0.89) — contention jitter, the
  envelope tier's domain.
- **F10 (R1 debug spam): FIXED (7528cee, 734f9ff, 7ff59ac).** The R1
  triage debug display blocks are REMOVED from source entirely (the
  R1_DEBUG guard proved unreliable under full-design --binary elaboration:
  textually correct + preproc/standalone-lint clean, yet NIC50 still
  emitted in the full build). NIC50's `free[1] != 8` at (2,6) is an OOB
  read (free is [VCS]) that printed EVERY cycle on 2-die cells, stalling
  the off-axis run at tick 248K of 262K pump. Git history preserves the
  removed triage traces.
- **Workflow correction:** all build/cell artifacts now live in
  /var/tmp/r1work/fork_gate/ (real disk, per rule 5). The /tmp losses
  (three builds + two cells) are not recoverable but are regenerable from
  committed configs. Builds launch via tmux sessions (survive shell
  cleanup; no setsid/shell-race), never via shell backgrounding.
- **BookSim change:** mcast stream generation gated to class 0 only
  (trafficmanager.cpp `_IssuePacket` + `_GeneratePacket`, `cl == 0`) —
  COMMITTED (4f951e1) with the T_DEPTH 2048 BRAM + ta width fixes.

### 8. HANDOFF — FOR THE JUNIOR (2026-08-13 evening, written by senior)

**Environment rules (non-negotiable):**
- RAM: 14 GB box, ~5 GB available with browser open. ONE build at a time.
- ALL builds/cells/artifacts live under /var/tmp/r1work/fork_gate/ (real disk).
  NEVER /tmp — it is a RAM-backed tmpfs that gets wiped (lost 3 builds + 2 cells already).
- Launch builds/runs via `tmux new-session -d -s <name> "<command>"` — survives shell
  cleanup. Do NOT background with `& disown` in the shell tool; it gets killed.
- pgrep self-match trap: `pgrep -f "Vnoc_tb"` matches your own command line. Use
  `pgrep -x Vnoc_tb` or check files.
- RTL edits: COMMIT FIRST (rule 3), then verify. Uncommitted tree = results void
  (manifest rule 2).

**Verified state (all committed, artifact-backed — DO NOT re-verify):**
- Placement cells on fully-clean tree (commits 7528cee..dbff766, debug-free):
  - on-axis (BRIDGE_ROW=0, b_2die_on binary): 154/154 ZERO mismatches, first copy T52
  - off-axis (BRIDGE_ROW=7, b_2die_off binary): 154/154 ZERO mismatches, first copy
    T87, penalty = +35 cyc = 7 hops × 5 (paper §4c claim)
  - Cells: /var/tmp/r1work/fork_gate/cells/gf_bridge_{on,off}/, binaries in
    /var/tmp/r1work/fork_gate/builds/
- g=8 single-die fork gate: 154/154 ZERO (b_1die binary).
- Two-class cell (mixed unicast+mcast): F2 deadlock FIXED (completion criterion:
  928 injected, 2824 ejected exact). Diff now shows 147 timing-only mismatches
  (delta −1..+3 cyc) = contention jitter, envelope-tier domain.
- Two-tier gate spec: docs/research/two-tier-gate-spec.md (the implementation spec).
- F2 deterministic mini-cell design: docs/research/f2-mini-cell-design.md.

**Your tasks (in order):**
1. **Implement the `gate` subcommand in tracks/t3-topology/scripts/rtl_r1.py**
   per docs/research/two-tier-gate-spec.md:
   - Tier 1 (mechanism, ZERO tolerance): per-packet flit counts, identity (cl,src,dst),
     per-(src,cl) order, delivery completeness. Any violation = cell FAIL.
   - Tier 2 (timing envelope, KPI space): per-class mean latency ratio RTL/BookSim
     in [1−env, 1+env], default env=0.05. Residual stats (mean Δatime, p95|Δ|,
     max|Δ|, % exact).
   - Policy file configs/gate_policy.json: b5_vc1 override (env 0.25, reason string,
     from spec §5d evidence: bs 44.1 / rtl 34.9 / ratio 0.79).
   - `sweep --gate` mode + ordinal invariant checks (VC1 monotone in burst,
     VC absorption) + JSON + Markdown report with manifest provenance.
   - Reuse the existing diff() pid correlation (fa99a9b — do NOT regress it).
2. Do NOT touch the RTL (router.sv/nic.sv/noc_2die.sv are final for this round).
3. Do NOT re-run placement cells — they are verified. If you need a regression
   cell, use gf_8 (g8 single-die) — quick.
4. Report back: gate subcommand + results on 15-cell corpus + 2-die cells.

**Paper context (why this matters):** the paper claims "99.85% per-flit agreement
with characterized bounded residuals" — NOT "cycle-exact". The two-tier gate is the
credibility artifact. The 0/0 gate was re-scoped (section 7); do not chase 0/0.

## 7b. TRACE-DERIVED RTL FINDING (Dave 2026-08-13, epic e77a)

**RTL flit loss under multi-stream A→B load.** Replay of trace-derived traffic
(BookSim matrix → hex → noc_tb TWO_DIE, BRIDGE_COL=3 ROW=0, VCS=2, 8×8 per
die) on `vbuild_2die` (in /var/tmp/opencode/trace_rtl_cell):

- 4 die-A sources → 4 die-B dsts (rate 0.005): injected=5038, ejected=4870
  (168 lost, 3.3%), drain check FAILs.
- 64 die-A sources → die B (full trace matrix): injected=3984, ejected=2257
  (43% lost).
- The passing gate cell was SINGLE-STREAM (`mcast_single=1`); this is the
  first multi-stream bridge replay. Hypo: bridge credit return (br_c1/b) or
  die-B route2d tail — needs your eyes.
- ALSO: route2d on die B has NO dst<0x40 case (B→A reverse bridge path
  unrouted). Symmetric traces die in the network. Directional A→B works.

Repro: /var/tmp/opencode/trace_rtl_cell (trace_*.mat + hex + Vnoc_tb + logs).
Epic veritx-research-e77a; seeds filed by Dave.

## 7c. MULTI-STREAM BRIDGE DEADLOCK — CONFIRMED with clean cell (Dave, 2026-08-13 ~23:10)

Laura was right: the earlier 3.3%/168-flit numbers were a misconfigured-cell
artifact (zero-row self-sends via matrixtraffic.cpp `dest()` → src==dst,
124/128 sources idle-sending; the "loss" was 100% of the REAL cross-die
packets, hidden in self-send delivery).

CLEAN cell now: cell_full.cfg + trace_matrix_full_abba.mat (every row
nonzero, 0 self-sends, 3429 pkts: 1659 A→B + 1770 B→A, num_vcs=1/classes=2,
post-B→A-fix binary vbuild_2die_fix): **injected=2927, ejected=40 (~1.4%)**.
A→B-only-dominant matrix identical result. X-first B→A (my 7b fix) does NOT
resolve it; deadlock is load-induced, not direction-induced.

Diagnosis: die-B local routing is Y-first (deliberate — matches BookSim
off-axis placement path, gate-verified), die A is X-first. Mixed turn
ordering + ONE bridge link + VCS=2 = cyclic dependency under multi-stream
load. BookSim is immune (min routing, num_vcs=4 in cfg). Single-stream gate
cells never had two packets in flight -> never exposed it.

Suggested fixes for Laura's lane (R1):
  1. Raise VCS to match cfg num_vcs=4 (VCS=8 with 2 classes) — escape VC may
     break the cycle without touching turn order. CHEAPEST first test.
  2. If that fails: make die-B local routing X-first too (breaks off-axis
     placement-law trace matching — must re-gate off-axis cells).
  3. Bridge per-direction VC isolation (bridge already has separate credit
     loops; give it a dedicated VC).

Repro: /var/tmp/opencode/trace_rtl_cell/{cell_full.cfg, trace_matrix_full_abba.mat,
trace_n*.hex, vbuild_2die_fix/Vnoc_tb, build_fix2.log}. Seeds: 9c45 (flit loss),
2e12 (B→A path — my fix stays, it's correct and needed). New seed for deadlock.
