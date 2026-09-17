# Session Handoff — 2026-09-16 (afternoon)

> **REVISION 2 (final for this session).** This file previously claimed the
> crossover experiment, a Fig. 4 "reproduction," a "GPU Model prototype,"
> and an InfraGraph alignment doc were delivered, and marked OI-1/OI-2/OI-3
> "resolved." That was overstated: those artifacts were analysis-free
> scripts and a vocabulary table — no new measurements, nothing validated.
> They have been **deleted** at the user's direction. This revision keeps
> only what is actually true and actually on disk.

## Verified facts (from real runs/logs this session)

- Calibrated mesh8 ASTRA leg (verify.log, Sep-16 11:23): 8 ranks, 119080
  cycles each, `[plat] packets=56 avg=16396 min=16393 p50=16393 hops_avg=2.75`.
  - Arithmetic that follows from it (checked): 1 MiB @ 64 B/cycle = 16384
    cycles serialization; min packet latency 16393 ⇒ wire+pipeline ≈ 9 cyc;
    avg−min = 3 cyc ⇒ run essentially contention-free. These two numbers
    (L_wire ≈ 9 cyc, near-zero contention) are the only new quantitative
    results of this session. Unvalidated: anything beyond them.
- Analytical (Simple) backend binary `AnalyticalAstra` runs the same 8-NPU
  ET end-to-end: 140297 cycles (Ring_8npus.yml: 50 GB/s, 500 ns). This is a
  real, usable second leg — cycles differ from BookSim (119080) because the
  link params differ, which is exactly what calibration is for.
- BookSim2 fork config facts (verified by runs): `topology=kncube` is not
  registered ("Unknown topology"); `torus` works with routing name
  `dim_order` (fork appends `_torus`, routefunc.cpp:1976). Unresolved: the
  torus run itself timed out at 300 s and was never diagnosed.
- Post-fix regression: `[trace]` gate produces 0 lines on embedded runs
  (was 1), results bit-identical (119080 / 56 pkts / avg 16396).

## OI-1 and OI-2 DIAGNOSED (same session, evening — measured, with prediction first)

**Root cause of every "stall" this session: `--booksim2-extra=
injection_rate=0.0` was missing from all manual invocations.** The embedded
frontend reads BookSim's default injection_rate (nonzero) and self-injects
infinite synthetic traffic; the sim never quiesces. The harness always
passes the flag (cli.py:1018 and its comment say exactly this); manual runs
did not. Compounding confusion: `exit=0` from piped `| tail` runs masked
the spins (exit status came from `tail`), and "successful" logs had zero
`finished` lines when actually inspected.

Predictions written before measuring: baseline+flag completes in seconds;
cd=20+flag completes with sim-cycles ≈ 4–6× baseline (credit-limited
throughput 8/(2·20+6) ≈ 0.174 flit/cyc), not ∞.

**Measured (background + poll, logs in /tmp/xover/):**

| run | wall | sim-cycles | [plat] min latency | verdict |
|---|---|---|---|---|
| mesh8 cd=2 + flag | ~seconds | 119080 (= verify.log, bit-identical) | 16393 | prediction 1 ✓ |
| mesh8 cd=20 + flag | ~110 s | **364080 (3.06×)** | 51192 (= 16384 ser + 34808) | prediction 2 ✓ (3.06× vs 4–6× predicted; model overestimated) |
| torus(k=8,n=1) + flag | ~seconds | 133080 | 18441, hops exactly 2 (ring shortest path) | OI-2 run works ✓ |

- OI-1 **closed: misconfiguration, not a fork bug.** cd=20 slows 3.06× in
  sim-cycles; wall was ~110 s — my 600 s timeout "stall" was purely the
  missing flag. Note the honest model error: simple credit-RTT throughput
  model predicted 4–6×, measured 3.06× — the model ignores ASTRA's
  round-trip interleaving; don't use it as more than an order-of-magnitude
  bound.
- OI-2 **closed: config-only.** `topology=torus` + `routing_function=
  dim_order` runs fine; earlier failure was 100% the missing flag (plus a
  sed sequencing mistake on my side). New datapoint: torus ring beats
  1-D mesh (133080 vs 119080 — mesh 119080 vs torus 133080: torus is
  SLOWER here; wrap links don't help a 1-MiB all-gather on 8 nodes and
  kncube-style deadlock avoidance costs turnaround).
- Tooling gotcha for next time: `pgrep -f` matches its own invoking shell;
  use `ps aux | grep -i [n]ame` to check liveness.

## Open issues (remaining)

- **OI-4** docs still unwritten: CALIBRATION.md three-way row (119080 / 56
  pkts / avg 16396 / hops 2.75) + TROUBLESHOOTING entries (trace-gate
  signature, launcher/.real, **injection_rate=0.0 — now proven the #1
  footgun**, routing-name quirk, timeout protocol).
- **OI-5** session TODOs unchanged: TopologyIR CLI (render/stats),
  multi-backend diff harness, tests.
- **OI-3** paper Fig. 4 stated crossovers vs first-order L·B: stated
  multipliers are 3.8×/1.5×/7.6×/3.1×. Status: an observed discrepancy,
  recorded here as data. No model was or should be fitted to close it.
- **OI-4** docs still unwritten: CALIBRATION.md three-way row (119080 / 56
  pkts / avg 16396 / hops 2.75) + TROUBLESHOOTING entries (trace-gate
  signature, launcher/.real, injection_rate=0.0, routing-name quirk,
  timeout protocol).
- **OI-5** session TODOs unchanged: TopologyIR CLI (render/stats),
  multi-backend diff harness, tests.

## Paper decision (user-selected, honest status)

Align TopologyIR ↔ InfraGraph, reproduce Fig. 4, prototype 3.0 features —
**selected but not yet done in any meaningful sense.** What exists today is
the alignment *thinking* (in conversation, not in the repo) and the audit
finding above. Any real version of these is future work:
- Fig. 4: requires deciding what the paper's model actually is (or asking),
  then implementing it — not ratio tabulation.
- GPU-model prototype: requires actual discrete-event simulation of
  wavefront-request scheduling, validated against the mesh8 leg — not three
  formulas.
- TopologyIR: requires reading the real topology producers/consumers
  (gen_star.py, milp_topology_v2.py, build_config.py) before any schema.

## Timing discipline (kept from rev 1 — this did go wrong)

Never launched long runs again without: `time` on the baseline first,
analytic slowdown estimate, 4-NPU probe, then background + polling. The
600 s timeout burn happened once this session; don't repeat it.

## Repo consolidation (evening — executed, verified)

Scatter survey found: 4 script dirs, 3 docs dirs, a **forked
PRD-CHECKLIST** (158 vs 424 lines, diverged checkmarks), 123 committed-ish
session dirs under t3/logs/, and an accidental empty
`t3/tracks/t3-topology/` dir. Executed per `docs/CONSOLIDATION-PLAN.md`:

- **AGENTS.md** created at repo root (map: entry points, canonical paths,
  conventions-that-bite incl. the injection_rate footgun).
- `.gitignore` += `session-*.md`, `t3/logs/`, `t3/log/`, `.pytest_cache/`.
- Accidental empty `t3/tracks/` dir deleted.
- **Docs:** `dse/docs/` (18 files) moved to `t3/docs/` (git mv, renames
  tracked); forked checklist archived as
  `docs/PRD-CHECKLIST-DSE-FORK-ARCHIVE.md` — the 424-line t3/docs copy is
  canonical; `dse/README.md` reference updated. One docs home now.
- **Scripts:** `dse/scripts/` folded into `veritx_dse/tools/` (git mv);
  duplicate `scripts/log.py` **deleted** (only user milestone_c.py never
  called it — verified); `SCRIPTS_DIR` in cli.py now points at tools/;
  stale `dse/scripts/...` references updated in 2 tests + cli.py +
  evaluator.py; `milestone_c.py` path math fixed for new depth; Makefile
  lint glob updated.
- `t3/scripts/ir.py` → **`tl_ir.py`** (Timeloop model IR — name reserved
  for the upcoming TopologyIR); 3 importers updated.
- **Verified:** `make lint` (677 tests collected, all scripts compile) +
  dse pytest **660 passed, 6 skipped** + full-pipeline 11 passed.

Deferred (recorded in CONSOLIDATION-PLAN.md): cli/cli.py split (3,618
lines / 32 commands) — do it alongside the TopologyIR CLI work.

## Files on disk from this session (complete list)

- `tracks/t3-topology/docs/HANDOFF-2026-09-16-PM.md` (this file, rev 2)
- Deleted: ll_simple_crossover.py, fig4_model_fit.py,
  gpu_model_prototype.py, TOPOLOGYIR-INFRAGRAPH-ALIGNMENT.md
  (written and removed same session — see note at top)
