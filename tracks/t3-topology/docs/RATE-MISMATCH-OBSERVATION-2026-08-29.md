# Rate-Mismatch Observation — 9ce5 Cross-Check Note

**Date:** 2026-08-29  
**Issue:** veritx-research-9ce5 — BookSim DOR saturates at IR≈0.16 (352c) vs RTL at IR≈0.32 (65c), 4× blind spot  
**Loop:** `/tmp/rate_mismatch_loop.py` — mesh 8×8 uniform DOR vcs2 pkt4

## Observation (cross-check seed)

**IR sweep (BookSim mesh 8×8 DOR vcs2 pkt4 vs RTL expected from CALIBRATION-RESULTS-R10R11):**

| IR   | BookSim | RTL | ratio | status |
|------|---------|-----|-------|--------|
| 0.02 | 37.32c  | 17.76c | 2.10 | linear |
| 0.04 | 39.33c  | 23.08c | 1.70 | linear, ρ=1.0 pre-knee |
| 0.08 | 48.82c  | 61.77c | 0.79 | BookSim still linear |
| 0.16 | 201.39c | 64.41c | 3.13 | **BookSim knee** |
| 0.32 | 352.20c | 65.50c | 5.38 | BookSim saturated, RTL flat |

- Doc said knee 0.08, now 0.16 (binary/config drift) — still **2× early vs RTL 0.32**
- At IR 0.32, BookSim 352c vs RTL 65c = **5.38× over-estimate**, ranking across plateau is noise (ρ=0.486 misleading)
- At IR 0.04, both linear: BookSim 39c vs RTL 23c = **1.70× stable offset**, pre-knee ρ=1.0 (mesh_b4/b8/b16 all @0.06)

**Hypotheses tested (no code, BookSim cfg sweeps):**

- **H1 routing:** dor 201c@0.16 vs min_adapt 168c@0.16, 352c vs 320c@0.32 — **NO**, both saturate
- **H2 VCs:** vcs2 352c vs vcs4 327c vs vcs8 325c@0.32 — **NO**, VCs not binding (wormhole pkt4 caps at 4 flits, buf8 non-binding)
- **H3 pkt_size:** pkt4 48c@0.08 vs pkt8 209c vs pkt16 369c — **NO**, larger worsens
- **H4 escape-class (classes=2):** vcs4 dor 327c → classes2 425c@0.32 — **NO**, worse (up_down adds hops)
- **H5 metric wrong:** **YES** — pre-knee IR 0.04 ranking `torus 37c < mesh 39c < adapt 41c` stable, post-knee `all ~350c` noise. Fix: rank at light load or knee IR, not high-IR latency.

## Cross-Check Plan

1. **Fix DSE to IR 0.04** (pre-knee) in `evaluator.py`, `calibration_runner.py`, `multi_workload_pareto.py`, `bo_synthesizer.py` — 1-line per cfg
2. **Re-run** IR 0.04 sweep on 5 topos × 3 traces (legit Qwen 95K, llama, wrf) — expect ρ=1.0 vs RTL
3. **Paper:** show regime-split: low-load ρ=1.0 + knee IR (0.06 both) + throughput@latency, not absolute high-IR latency

**Artifacts to keep:**
- `/tmp/rate_mismatch_loop.py` output: `/tmp/rate_loop2.out`
- `/tmp/rate_h3.py` pkt sweep
- `/tmp/test_h4.sh` H4/H5 BookSim runs
- This note: `outputs/rate-mismatch-observation-2026-08-29.md`

**Next:** implement H5 IR 0.04 fix, verify ranking, close 9ce5 with evidence.
