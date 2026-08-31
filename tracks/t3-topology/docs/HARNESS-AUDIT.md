# Harness Audit — Findings, Open Problems & Improvements (2026-08-22)

**Scope:** the DSE production harness: `tracks/t3-topology/{dse,scripts,rtl,rtlgen,tb}`
plus the `serving/` simulator chain (booksim2-embed, ASTRA-sim, LLMServingSim,
SCALE-Sim, Noxim, FlooNoC). Grounded in live inspection + tonight's verification runs.
**Verdict up front:** the pipeline is functionally strong and the correctness work
landed well, but it is a **multi-author, multi-fork, ad-hoc-verification harness** that
will silently regress without a single-source-of-truth and a regression gate. Findings
below are grouped; each item is evidence-backed.

---

## 1. Architecture & structure — the biggest risks

### F1. TWO ROUTER FAMILIES (critical divergence)
`rtl/router.sv` (`module noc_router` — serving-leg, what `noc_frontend.py` + Verilator
build/results) and `scripts/rtlgen/router_template.sv` (`module router` — DSE/anynet,
what `gen_rtl.py` generates) are **separate implementations of the same fabric**.
- Fix-marker audit done tonight: serving-leg has **0** occurrences of
  `deq_actual`/`rt_out==LOCAL`/`effective_esc`; rtlgen has 8/1/6.
- Both pass their own rigs, but via **different mechanisms** (dd91e23/446bb41's
  admission/esc-force set vs tonight's deq_actual/occupancy-gate set).
- **Consequence:** a fix to one family silently doesn't apply to the other. The
  class-split bug lived in both, independently, for the same session. Any future fix
  must be mirrored twice.
- **Fix:** a single shared parameterized router source, OR an automation that
  cross-checks the two (open → assert same kernel), OR migrate noc_frontend to build
  from the rtlgen family. Document the canonical source-of-truth.

### F2. S10 extraction is a broken split-brain (E8)
`dse/veritx_dse/` package exists (docstring references `recommend`) but
`recommend.py`, `search_bo.py`, `dse_to_frontend.py`, `run_smoke.py` are **missing**
from it — still live only at old `dse/` paths. `import veritx_dse.recommend` FAILS.
Meanwhile the old-path scripts are the working CLI. → Two copies of the harness logic
drifting. **Fix:** finish the move, fix `__init__`, smoke the package CLI, delete the
old path (or make old path a thin shim).

### F3. Hardcoded machine-local paths (reproducibility)
`dse_to_frontend.py:68` and `recommend.py:289,318` hardcode `outdir=/var/tmp/opencode/nocfe`
and the report path. Proof artifacts live OUTSIDE the repo at a scratch path.
**Consequence:** results aren't reproducible/auditable from the clone; a second machine
or container can't produce the same report; the Srota "design revision + guardrail hash"
provenance goal is defeated. **Fix:** derive from env (`DSE_ARTIFACT_DIR`) with a repo-
default fallback; treat /var/tmp/opencode as machine-local only for scratch.

### F4. Duplicated logic across old/new paths + orphaned modules
7 new modules (compile_request, chakra_to_dse, workload_generator, trace_slicer,
calibration_booksim_rtl, automotive_workloads, customer_workloads) all import cleanly
but are **orphaned** (nothing in the CLI path calls them). `recommend.py` exists twice.
**Fix:** decide wire-or-drop; a module that imports but is never invoked is untested
dead weight that still rots.

---

## 2. Correctness — what's solid vs what's open

### Solid (verified tonight):
- S1 trace_input: hand-verifiable 14-flit trace → exact per-dst delivery; normal mode bit-exact.
- S3 four-defect chain incl. residual: 3765/3765, 0 stuck, 0 wrong-dst (unique-seq rig).
- 2-router regression: 787/787. M2 math corrected (0.333 vs ASTRA 0.684). M3/M7 verified.

### Open / not proven:
- **No rank-agreement test yet** (E1): nothing asserts Spearman(BookSim, RTL) > threshold.
  The DSE's entire "Config Out predicts silicon" claim rests on an untested assumption.
- **`9ce5` 4x blind spot (E2):** evaluator config space can't see escape-class saturation
  benefit → recommendations over-provision. Not modeled, not fixed.
- **Formal run never executed (E3):** SVAs were added, but sby/BMC never ran on the
  current template.
- **Light-traces can't calibrate:** any gate threshold or ranking computed on near-tie
  data is noise (G1 threshold §E6). Must use stressed IR.

---

## 3. Reproducibility & determinism

- **Cache-hash bug (fixed tonight):** cross-process hash randomization broke grid cache
  (129 keys / 21 configs). Fixed via stable sha1 + values-dict. (Keep an ABC test.)
- **Stale-binary bug (fixed by G6):** `Vnoc_tb.meta` didn't fingerprint rtl sources →
  results produced against old RTL. G6 added SHA-256 source fingerprinting.
- **Seeds / RNG:** `srand(42)` in TBs; `seed=42` in cfg. But multi-agent runs and
  absolute-path artifacts make bit-exact rerun fragile.
- **Hardcoded paths** (F3) directly undermine reproducibility.

---

## 4. Reliability (this box)

- **RAM rule enforced only by discipline.** Tonight: `-j4 --threads 4` Verilator build
  OOM-crashed the box; high-IR BookSim sweeps can also unbounded-run (convergence
  termination near saturation). No `ulimit`/`nproc`/watchdog in the harness.
- **Fix:** default Verilator to `-j2 --threads 2`; add a memory guard to `run_booksim`
  (abort if free_RAM < threshold or runtime > cap); document one-build-at-a-time as a
  machine-enforced nproc cap, not a convention.
- **Python 3.14 + ProcessPool(forkserver):** scripts run from stdin crash workers; any
  script using `grid_search` needs `if __name__ == "__main__":`. Fragile footgun —
  add a helper or a linter note.
- **/tmp is tmpfs** (RAM-backed, ~7G): AGENTS.md warns never to install/venv/download
  there; but `/var/tmp/opencode` is used for large artifacts + builds. Confirm it's
  truly disk-backed; a tmpfs there would crash on the 92MB binaries.

---

## 5. Verification methodology — no gate

- **No CI, no pre-commit, no lint gate** (no `.github`, no Makefile test target, no
  pre-commit-config). `test_*.py` are ad-hoc scripts run by hand.
- **Fix:** a single `verify.sh` running: (1) S1 trace-input unit, (2) 2-router PASS,
  (3) 4-router/anynet 0-stuck, (4) M2 math sanity, (5) cache-hit ABC, (6) veritx_dse import.
  Wire into pre-commit + a CI job. A regression that no machine runs is not a regression test.
- **Two families** (F1) mean the gate must run BOTH builds, or the gate is misleading.

---

## 6. Three-simulator consistency
BookSim (ranking), Noxim/FlooNoC (cross-check), RTL (proof) use different traffic models
and different router semantics. The 4x saturation gap (`9ce5`) is a direct symptom:
rankers and RTL disagree on the fabric's capability. **Fix:** define a single harness
"traffic contract" (uniform trace → all three) and a documented calibration delta table
(partially exists: `results/dse_calibration/`). Treat cross-engine rank agreement as a
**CI-blocking gate**, not a nice-to-have.

---

## 7. Prioritized improvement roadmap

**P0 (trust; unblocks everything else):**
1. F1 — canonicalize the router (or add cross-family automirror + assert).
2. F2 — finish S10 extraction (delete split-brain).
3. F3 — de-hardcode `/var/tmp/opencode`/`/tmp` paths behind env.
4. §5 — `verify.sh` gate + pre-commit + CI.

**P1 (per-OUTCOME):**
5. E1 — rank-agreement test on ≥2 serving-leg configs.
6. E2 — `9ce5` escape-proxy ranking mode.
7. §4 — memory guard + `-j2` default.

**P2 (completeness):**
8. E3 — run sby/BMC to actually discharge the SVAs.
9. E4/M4 — surrogate retrain on dynamic slices.
10. E5/E6 — FlooNoC + percentile completion; G1 threshold from stress data.

---

## 8. What the harness does WELL (keep)
- Correctness effort this session was rigorous and cross-validated (two agents
  independently converged on the same class-split root cause).
- The e213 unified trace is a genuinely good single-source-of-truth design.
- The stress-rank method (light traces can't calibrate) is the right insight.
- M2 correction corroborates two independent IR derivations.

---
*Author: steve (opencode). Grounded in live `git status`/`git log`, fix-marker greps,
import checks, and tonight's verification runs. Companion: `PRODUCTION-TASKLIST.md`
(OPEN ITEMS MASTER LIST), `results/dse_calibration/*`.*
