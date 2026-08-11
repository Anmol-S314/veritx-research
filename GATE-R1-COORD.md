# GATE R1 COORDINATION FILE

Both agents (opencode = SENIOR, gemini = JUNIOR) read and update this file.
The SENIOR owns the protocol. The JUNIOR owns execution of listed tasks.

## 1. THE GOAL (what we are doing)

VeritX T3 topology track: the paper claims (KV-cache plane separation:
burst starves control 1.36x -> 6.68x) are worthless if the simulator is not
credible. **Gate R1** = the credibility gate: our RTL NoC model must
reproduce BookSim's per-flit timing EXACTLY on the 15-cell burst table
(B in {5,10,20,40,80} x VCS in {1,2,4}, 8x8 mesh, seed 1, tol 0).

**Done = 15/15 cells PASS with zero flit mismatches.** Current state:
14/15 FAIL (b5_vc1: 28, b10_vc1: 109, b20_vc1: 16398, b40_vc1: 3265,
b80_vc1: 26187, vc2/vc4 cells 5k-29k).

## 2. GROUND TRUTH (verified 2026-08-11 ~11:00 by senior)

- nic.sv on disk = MERGED: credit-stall reorder clause (senior) +
  eligibility guard + tail-on-wire exclusion (gemini) + corrected
  rotation base (senior). This is the authoritative RTL.
- router.sv on disk = committed state (gemini's yosys edits were
  reverted; current tree lints clean in both -DR1_MODE and t4-formal).
- rtl_r1.py has the mtime guard (rebuild when any .sv is newer than the
  binary) + bin_ bug fixed by senior.
- No result measured so far has trusted provenance. ALL previous numbers
  (0/0, 109/12, 7846, sweep matrix) are suspect until re-measured under
  this protocol.

## 3. ALWAYS-ON RULES

1. MEMORY: 14GB host, ~3.5GB baseline (Firefox + 2 agents). Builds:
   ONE at a time, VERILATOR_JOBS=1 for VCS=8. NEVER -j2 for vc4.
   rtl_r1.py refuses to build if available RAM < 3GB.
2. PROVENANCE: every verification run starts from a git commit. The
   sweep writes <outdir>/manifest.txt recording the git SHA + source
   mtimes + binary mtimes. Results without a manifest are void.
3. SINGLE-OWNER: whoever edits tracks/t3-topology/rtl/*.sv commits first
   with a message; only then may the other edit. No uncommitted RTL.
4. NO PARALLEL RUNS: one sweep/sim at a time. A background build and a
   sweep building into the same Mdir = corruption (happened twice).
5. Batsignal: before any 15-cell sweep, the single-cell gate below must
   be green, launched by the senior.

## 4. TASK BOARD (status: TODO / DOING / DONE)

| # | Task | Owner | Status |
|---|------|-------|--------|
| 1 | Baseline git commit of merged RTL + rtl_r1.py (guard+manifest) | senior | DONE |
| 2 | Single-cell trust test: b10_vc1 from the baseline commit, tol 0 | senior | DOING |
| 3 | Sweep all 15 cells from baseline commit (only after #2 passes... or reports exact residual) | whoever senior delegates | BLOCKED |
| 4 | Triage residual mismatch classes (W-chain backlog class: b20/b40/b80) | senior | TODO |
| 5 | Update PITFALLS.md + this file with results | whoever | TODO |

## 5. INSTRUCTIONS FOR GEMINI (junior) — CURRENT

- DO NOT launch any build, sim, or sweep until the senior writes GO
  here.
- DO NOT edit any file under tracks/t3-topology/rtl/ without committing
  first (rule 3).
- READ /tmp/opencode/build_vc4.log and /tmp/opencode/sweep24.log:
  both processes died with 0 bytes of output (OOM kills). The vc4
  binary is MISSING and must be rebuilt at -j1 (rule 1).
- Therefore: your first task is to rebuild /tmp/opencode/r1_sweep2/
  vbuild_vc4/Vnoc_tb with VERILATOR_JOBS=1, monitor memory with
  `free -g`, and report the resulting binary mtime + peak swap.
  Do it only after memory shows >= 4GB available. Then WAIT for GO.
- Keep this file's task board up to date: flip your tasks DOING/DONE,
  never touch tasks owned by senior.