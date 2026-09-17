# HANDOFF — Phase 5: serving metric semantics

**Date:** 2026-09-17 · **Branch:** `epic/booksim-forward-port`
**Suite:** 1038 passed, 1 skipped · **Gate: PASS**
**Next permitted: Phase 6 (PR7 serving → analytical)**

## Vocabulary (`core/serving_metrics.py`, schema v1)

Canonical names, all with unit/producer/fidelity/scope/derivation:
`sim_clock`, `request_arrival_time`, `request_completion_time`,
`request_latency`, `TTFT`, `TPOT`, `ITL` (ns, ticks @ FREQ=1GHz —
pinned at `request.py`/`__main__.py:902`, never converted),
`requests_submitted`/`requests_retired` (requests),
`wall_time` (s, producer veritx — wall seconds, never compared
against sim_clock). Bundle: `{schema, metrics}`; no ITL rows observed
→ no ITL metric (never fabricated 0); missing columns/retirement
mismatch → ValueError, never partial metrics.

## Rulings

- **Naming:** program's `SYSTEM_SIMULATION` denotes the code's
  `SYSTEM_SERVING_SIMULATION` (runs.py, arch §13.1). Source wins.
- **Exposed comm:** vocabulary-defined but UNSOURCED — parsed
  per-iteration, emitted nowhere (`grep exposed __main__.py` empty).
  Wiring an emitter is later serving-loop work, not backfill.
- Sim clock = max(end_time), proven equal to Total clocks in T6 data.

## Slice integration

`run_serving_experiment` verdicts now consume the canonical builder;
old TTFT/TPOT-only helper removed; goldens re-proven live against the
new path. Result carries `metric_schema: 1`.

## Incidents this phase (outside Phase 5 scope, fixed)

- **`t3` syntax error:** `{ printf '\n'; break }` — `break` swallowed
  `}` as its numeric argument (bash quirk), unterminated group,
  `done` unexpected at line 883. One-char fix (`break;`), from the
  Phase-0 baseline commit. `make lint` now runs `bash -n` on the
  wrapper + env.sh so the entry point can't break silently again.
- **Disk full (ENOSPC):** accumulated in-tree run artifacts (results,
  kept inputs, traces) filled the volume; 33 suite failures, all
  `OSError 28`. User cleaned; `.gitignore` now also covers
  `llmservingsim/traces/` and `astra-sim/inputs/runs/`. Lesson:
  `--keep-inputs` runs must stay out of the tree (or be removed
  after transcription — as T6 did).

## Residuals

- Stochastic serving refused (no seed mechanism).
- ITL-list / queuing means: queuing in vocabulary+builder? No —
  builder covers program-minimum + wall_time; queuing_delay mean
  omitted for now (column documented, Phase 7+ if needed).
- F4/F5 remain ASSUMPTION-class; F2/F3/F6/F7/F8 NOT_RUN without
  their evidence (verified honest in `compile_model.py`, Gate B).
