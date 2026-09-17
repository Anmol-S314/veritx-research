# VeriTX Domain Vocabulary (CONTEXT.md)

Read before changing experiment semantics. Every term here is **already
established in this repository** — each entry cites where the code defines
it. Terms without code behind them are listed in
`docs/SEMANTIC_QUESTIONS.md` as open, not here.

The control-plane redesign handoff (§8) proposes vocabulary provisionally;
this file is the repo-truth check on it. Adjust when code reveals better
terms, but once decided, use one name per concept everywhere.

## Simulation stack (bottom-up)

**BookSim** — cycle-accurate NoC simulator, binary at
`third_party/booksim2/src/booksim`. One-shot invocation: `booksim <cfg>` →
stdout metrics → exit. Stochastic unless `seed` is pinned in the cfg
(verified: mesh4x4 at ir=0.1 varies run-to-run; with `seed = 42;` it is
exactly reproducible). Golden run: 0.2 s.

**ASTRA-Sim** (`AstraSim_BookSim2` frontend, host-built) — network sim
frontend; can run standalone (one-shot, `--workload-configuration …`) or as
**the interactive backend of LLMServingSim**.

**LLMServingSim** — serving-system simulator (`python -m serving` in
`third_party/llmservingsim`). Drives an ASTRA-Sim backend **as a long-lived
interactive subprocess** (`serving/core/controller.py`): writes commands,
reads until the backend's `Waiting` prompt, parses completion lines. This is
the only interactive process relationship in the repo today.

## Execution relationship (not "backend" — see below)

**Interactive protocol** — the stdin/stdout command-reply loop between
LLMServingSim (frontend) and AstraSim_BookSim2 (backend). Framing documented
from source in `docs/SEMANTIC_QUESTIONS.md` (Q1). The frontend is
`python -m serving`; the backend is the C++ binary. One owner per side.

**Backend** — in this repo this word means *the ASTRA-Sim binary when driven
by the serving loop* (protocol peer). It does **not** mean "network
simulator kind" (that word collides with the handoff's generic "network
backend" usage; keep them distinct until the redesign settles one term).
The network-simulator kind (BookSim vs analytical vs ns-3) is selected by
`--network-backend` in serving configs.

## Run identity (exists today in embryo)

**Run** — one realized execution. Today's runs are directories under
`tracks/t3-topology/results/<CONFIG>/` or `dse/results/<command>/<ts>_<seed>/`
(the doctor/evaluate layout). No run_id yet; the control-plane plan (§3.1)
introduces ULIDs. Recorded here because the *directory-per-run* convention
already exists.

**Result** — parsed structured output: BookSim metrics dict (`run_booksim`
returns at least `latency`), ASTRA artifact JSON
(`status/cycles/plat_stats`), serving clock totals (validate-baselines.txt
records them as exact-equality values).

**Golden corpus** — the tiny deterministic fixtures used by
`dse/tests/` (e.g. `dse/tests/fixtures/astra_tiny/`) and, after Phase 2 of
the redesign, the migration parity corpus. The simulator is deterministic
when seeds are pinned; the corpus exploits that.

## Seeds and determinism (verified, load-bearing for results)

**Deterministic run** — BookSim with `seed` pinned; LLMServingSim
(`serving/validate.sh`: "The simulator is deterministic, so validation is
exact equality against recorded results").
**Stochastic run** — BookSim without `seed` (rng in the injection process).
A result summary must always record which one it is; mixing them in one
comparison is invalid (see `docs/SEMANTIC_QUESTIONS.md` Q10).

## Comparison (the seams that already guard this)

**Comparability** — two results may be ranked only if node count, trace,
packetization, offered load, routing, VC/buffer, simulator identity, and
seed policy agree (differences here have already corrupted conclusions once:
64- vs 72-node mixing). The Pareto scoreboard's per-trace normalization and
the planned comparability gate both implement this.

**Anchor** — a pinned expected value for a canonical fixture, used to detect
drift: doctor deep verifies `booksim=119,080c` on the calibrated mesh8
anchor within 0.5%. "Anchor drift" = every other number in the repo becomes
suspect.

## Serving execution mode (PR6)

**Network mode** — *how* a serving result was produced:
`REAL_SIMULATION` (packets contended in a network backend) vs
`TRACE_REPLAY` (recorded durations replayed, fabric untouched —
downstream `--booksim-replay-only`, the default). Defined by
`dse/veritx_dse/core/serving.py:NETWORK_MODES`; every serving result
carries it via `serving_provenance()`.

**Trace replay** — the `TRACE_REPLAY` fidelity in
`dse/veritx_dse/core/runs.py:FIDELITY_CATEGORIES`. Replay TTFT/TPOT are
estimates, never comparable against `SYSTEM_SERVING_SIMULATION`.

**Golden gate** — `passes_serving_golden_gate()` in
`dse/veritx_dse/core/serving.py`: real simulation AND zero semantic
loss. A replay-only run fails it by construction, not by eyeballing.

## What this file deliberately does NOT define

No terms for the future Python control plane (spec/plan/run/manifest) —
those arrive with the code that implements them. No synonym sets
(backend/engine/runtime/provider); when the redesign needs a word, add it
here with its code citation, and delete the loser.
