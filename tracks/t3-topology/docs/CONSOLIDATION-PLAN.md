# Consolidation Plan — T3 Topology track (2026-09-16)

**Principle (codebase-design):** consolidate into **deep modules at clean
seams**, not into fewer files. One 12.7k-line `veritx_dse.py` would be
*less* queryable, not more. Target state: one package, one obvious entry
point per concern, one docs home, no runtime artifacts in git, and a single
index (`AGENTS.md`) so an AI agent resolves any question in one hop.

**Guardrails:**
- `dse/veritx_dse/` package is sound (33 files, 12.7k lines, clear core/
  model/simulation/synthesis/cli split) — we do NOT flatten it.
- Nothing moves without checking references: Makefile (`lint` compiles
  `scripts/*.py scripts/lib/*.py dse/veritx_dse/**/*.py dse/scripts/*.py`),
  `paths.py` (REPO/DSE_DIR/SYNTH_DIR resolution), `run/env.sh`, `t3` CLI
  (2,705-line bash at track root — referenced by PATH via run/env.sh).
- Runtime output dirs (`logs/`, `runs/`, `results/`, `log/`, `.scratch/`,
  `.noc_p0/`) are mostly untracked already (2 tracked files under run/ are
  README+env.sh — keep). We add .gitignore rules, we don't delete data.

## Phase 1 — Zero-risk, immediate (this session)

1. **`AGENTS.md` at repo root** — the map: entry points, canonical paths
   (from core/paths.py), where things live, common tasks. This alone makes
   the repo "queryable by an AI agent."
2. **.gitignore additions:** `logs/`, `log/` at t3 level, `session-*.md`,
   `__pycache__/` globally (currently 8+ committed copies).
3. **Delete accidental `tracks/t3-topology/tracks/` empty dir** (created by
   a path bug on Sep 11; zero files).

## Phase 2 — Docs consolidation (one home, no forks)

Current: 64 .md files, 3 docs dirs, and a **forked PRD-CHECKLIST**
(dse/docs 158 lines vs t3/docs 424 lines — diverged checkmarks = silent
conflict).

1. `tracks/t3-topology/docs/` becomes the single docs home:
   - PRD + checklists + plans + handoffs stay here (4 existing + dse's 18
     move in, EXCEPT duplicates).
   - Resolve the PRD-CHECKLIST fork: t3/docs copy is newer/superset (424 >
     158 lines, 56 vs 75 DONE markers — needs a merge pass, not a blind
     pick). One file survives at `docs/PRD-CHECKLIST.md`.
   - `dse/docs/*` unique files move to `docs/`; `dse/docs/` removed.
   - Root `docs/adr/` stays (ADR convention is repo-wide).
2. Root-level strays: `session-ses_f714.md` → deleted (chat log, gitignored
   going forward); `HANDOFF-2026-09-08-astra-integration.md` → `docs/`.

## Phase 3 — Scripts consolidation (three seams → two)

Current: `dse/scripts/` (7 loose, own `log.py`), `t3/scripts/` (39 files,
Timeloop/analysis pipeline + lib/), root `scripts/` (4).

1. **`dse/scripts/` folds INTO the package** as `veritx_dse/tools/`:
   - `scripts/log.py` (duplicate logging seam) → deleted; callers use
     `veritx_dse.core.logging` (the deep module — one seam, not two).
   - One-shot milestone scripts (`milestone_c.py`, `multi_workload_pareto.py`,
     `memory_miss_model.py`, `deadlock_routing.py`) → `veritx_dse/tools/`
     with a README stating they are historical one-offs, not supported CLI.
   - `chakra_to_dse.py` stays importable at the same path via a shim OR
     moves with an updated reference (cli.py:488 references its path in an
     error message — update string).
   - `_cov_sitecustomize.py` → `tests/` helper (it's coverage plumbing).
2. **`t3/scripts/` stays** — it belongs to the Makefile/Timeloop pipeline
   (different lifecycle), but its `ir.py` renames to `tl_ir.py` (it's the
   Timeloop model IR; the name will collide with TopologyIR we're about to
   build).
3. Root `scripts/` stays (4 files, all referenced by CI/Make).

## Phase 4 — (later, after TopologyIR) — cli/cli.py split

`cli/cli.py` is 3,618 lines / 32 commands — a shallow mega-module. Split
into `cli/` submodules per command family (trace, evaluate, runs, report,
synth) with `cli/main.py` as the dispatcher. NOT in this pass (needs its own
test run); planned alongside the TopologyIR CLI work since we're touching
it anyway.

## Verification after each phase

- `make -C tracks/t3-topology lint` (py_compile of all script dirs +
  pytest collect-only)
- `python3 -m pytest tracks/t3-topology/dse/tests -q -x` (full suite;
  1241+ tests repo-wide, dse subset is the affected one)
- grep for stale path references (`dse/scripts/`, `dse/docs/`) after moves.
