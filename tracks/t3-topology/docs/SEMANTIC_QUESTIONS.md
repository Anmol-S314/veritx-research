# Semantic questions (handoff §34) — answered from code, not guesses

Companion to `../CONTEXT.md`. Instruction was: "If the current repository
does not make the following semantics clear, inspect the code/tests and
document the answer before implementing behavior." Each question is either
**answered** (with file:line evidence) or **open** (with what would settle
it). The open ones must be settled before the corresponding control-plane
behavior is implemented.

## Q1. Exact LLMServingSim stdin/stdout protocol framing — ANSWERED

Source: `third_party/astra-sim/astra-sim/network_frontend/booksim2/main.cc`
(VeritX multi-instance protocol comment, lines ~270–360) and
`third_party/llmservingsim/serving/core/controller.py`.

Line-based protocol over the backend's stdin/stdout (text, `\n`-terminated;
frontend uses `universal_newlines=True`):

| Frontend sends        | Backend reply                                                                 |
|-----------------------|-------------------------------------------------------------------------------|
| `load <path>`         | *none* — queues a reload (applied only to systems whose `<path>.<rank>.et` exists) |
| `run`                 | applies queued loads, fires workloads, runs to quiescence, emits per-NPU completion lines, then `Waiting\n` |
| `<path>` (legacy)     | = `load <path>` + `run`                                                       |
| `pass [t]`            | advances event queue (optionally to target cycle `t`), emits `[workload] sys[N] finished, <wall> cycles, exposed communication 0 cycles.` for each NPU + `Waiting\n` |
| `done`                | `Waiting\n` only (one instance finished; binary keeps serving the rest)       |
| `exit`                | loop breaks, backend exits                                                    |

Reply framing: **every command — including `done` and `load`-less rounds —
must be terminated by exactly one `Waiting` line**, because the frontend
always does `read_wait()` before sending its next command
(`main.cc` ~336: "every command (done included) needs exactly one
Waiting-terminated reply or serving deadlocks in read_wait"). The `load`
command is the exception that produces no reply of its own: it is only
legal because the frontend never calls `read_wait` after it — it queues
loads then sends `run`.

Backend completion lines (what the frontend parses):
- ASTRA analytical format: `sys[N] iteration I finished, C cycles, exposed communication E cycles.`
- BookSim format: `[workload] [info] sys[N] finished, C cycles, exposed communication E cycles.`

Both are matched by `_COMPLETION_RE` in `controller.py`.

## Q2. Exact meaning of `Waiting` — ANSWERED

`Waiting` = the backend reached quiescence for the current round and is
ready for the next command. It is **not** "requests pending" and **not**
"simulation done": `done`/`pass` rounds also emit it, and a
`Checking Non-Exited Systems ...` line is an acceptable terminator for
`read_wait` (frontend treats it as end-of-round). EOF without `Waiting`
means the backend died (crash/arg error) — `read_wait` breaks and the
caller fails loudly.

## Q3. Which process owns simulated-time advancement — ANSWERED

The **backend** owns the clock (event queue + cycle counter). The frontend
advances it only by asking: `run` (simulate until quiescence) or
`pass <target>` (jump/advance to target cycle). Frontend keeps its own
`_sim_time` mirror fed by parsed completion cycles; `pass t` exists
precisely "to keep the binary's wall_time monotonic with Python's
`_sim_time`" (`main.cc` ~283).

## Q4. Ordering constraints for load/run/pass — ANSWERED

- `load <p>` may be repeated; loads accumulate until `run`.
- `run` consumes all queued loads (clears the queue; empty set = re-report only).
- `pass [t]` is standalone (no loads); it must not be interleaved with
  queued-but-unfired loads — the backend treats it as a no-load round.
- The frontend pattern is strictly: `read_wait()` → send command → (optional
  more commands without reads only for `load`) → next `read_wait()`.
- Startup: the backend emits its first `Waiting` before any command
  (`main.cc` 225: "This ensures the first Waiting contains valid completion
  data"), so the frontend's first action is a read.

## Q5. Synchronous or session-like per integration — ANSWERED

- Standalone BookSim (`evaluate booksim`, `run_booksim` seam): synchronous
  one-shot process; argv in, stdout metrics out, exit.
- Standalone ASTRA (`evaluate astra`): synchronous one-shot; writes a result
  JSON artifact (the doctor leg parses the artifact, not stdout).
- LLMServingSim → BookSim / → analytical: **session-like** (the §4.2
  interactive protocol above). One backend process per serving run,
  many rounds.

## Q6. What constitutes successful completion of a serving run — ANSWERED
(operational definition in code)

The serving loop terminates when the router has no pending/deferred
requests and all batches are retired; then it sends `exit`. Two explicit
end-of-stream markers exist: `All Request Has Been Exited` (success) and
`ERROR: Some Requests Remain` (failure) — `controller.check_end()` reads
until one of them. Post-completion backend EOF is treated as clean
shutdown; EOF with work remaining is the fail-loud path
("backend pipe exhausted with work remaining" — the exit-1 error in
`evaluate astra`'s sibling serving runs). Exit code 0 + the success marker
+ all requests retired = success. **Open wrinkle:** the success marker is
checked by line-matching; if the backend protocol ever adds output between
marker and exit, this is fragile (see Q12).

## Q7. Authoritative location of model/topology presets — ANSWERED

- Topologies: `tracks/t3-topology/configs/` (legacy mixed-size),
  `configs/n16/`, `configs/n64/` (generated — do not hand-edit; regenerate
  via `scripts/gen_sweep_configs.py`), anynet links in `configs/*.links`,
  canonical anynet parser `dse/veritx_dse/core/anynet.py`.
- Traffic traces (ONE home): `dse/archive/inputs/traces/`
  (symlinked from `dse/inputs/traces` and `runs/traces` for legacy
  consumers — the picker dedupe of 2026-09-16).
- Models: `models/` + `dse/models/traffic/` (traffic model JSONs);
  workload registry via `t3 model` / `veritx` compile requests in
  `runs/compile_requests/` (created by `veritx init`).
- Simulators: booksim binary `third_party/booksim2/src/booksim`;
  ASTRA frontend
  `third_party/astra-sim/astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2`
  (host-built; must pass ldd-clean check — container glibc can't load it).

## Q8. Which existing outputs are canonical for downstream scripts — PARTIALLY ANSWERED

- `results/<CONFIG>/topology_sweep.json` — consumed by `t3 analysis`,
  `aggregate`, `plot`, `plot_config` (the config picker requires exactly
  this file). Incrementally rewritten by `run_experiments.py`.
- ASTRA sweeps write `astrasim_sweep.json`-style artifacts consumed by
  `report`/compare flows.
- `veritx report` accepts only veritx-native result JSONs (have `name`
  keys); t3's own sweep JSONs use a different schema and make it die with
  KeyError('name') — known schema split, see Open #8.
- Open: the control-plane redesign replaces this with immutable run dirs;
  until then the list above is descriptive, not a contract.

## Q9. Precise random-number sources and seed propagation — PARTIALLY ANSWERED

- BookSim: `seed` cfg parameter pins the RNG (verified experimentally:
  mesh4x4 ir=0.1 without seed varies ±2 cycles run-to-run; with
  `seed = 42;` → exactly 35.0573 every run). Default is unpinned →
  stochastic. The golden corpus must pin it.
- LLMServingSim: deterministic (validate.sh's stated premise). Its own RNG
  usage (routing tie-breaks, if any) needs a source-level pass — see
  Open #2 in the handoff queue.
- ASTRA analytical backend: believed deterministic (same input → same
  cycles in doctor anchor), but no explicit seed parameter has been
  verified at source level. Open.

## Q10. Simulator-specific units — ANSWERED (what the code emits)

- BookSim: **cycles** (packet/network/flit latency averages are in cycles;
  flit/packet size in flits; injection rate in packets/cycle/node). Time
  inside a run is cycles; `Total run time` is wall-clock seconds of the
  *simulation process* (not a scientific metric).
- ASTRA: **cycles** (`sys[N] … C cycles`); exposed communication also
  cycles.
- LLMServingSim: **clocks** (total simulation clock count;
  validate-baselines.txt stores exact clock totals); TTFT/TPOT/IPWT in the
  results section are in simulated time units derived from clocks.
- Cross-simulator comparisons must convert or refuse; no unit field exists
  in current result JSONs (gap tracked by the provenance work).

## Q11. Two comparison modes with different semantics — ANSWERED (they do)

`t3 compare` (BookSim injection sweeps, uniform traffic, cycles) and
`veritx compare` (trace replay, latency/throughput modes) are different
experiments with different inputs, not two UIs over one thing. The
comparability gate (planned) must treat them as distinct families; the
current Pareto scoreboard already normalizes per-trace for this reason.

## Q12. Remaining OPEN questions (must be settled before implementing)

1. **Serving livelock root cause (multi-instance).** Known: extremely fast
   no-progress spinning with several instances. The plan (§28) requires
   diagnostics that distinguish wall-clock-slow vs clock-not-advancing vs
   clock-advancing-no-completions vs `Waiting`-with-unchanged-state. None
   exist yet as a first-class feature (`[VERITX_TIMING]` prints round
   splits but not per-instance progress). **Needed before Slice B.**
2. **Serving RNG usage** — does the router/scheduler consume randomness?
   Source pass required (Q9 wrinkle).
3. **ASTRA analytical seed** — explicit seed parameter? Source pass
   required (Q9 wrinkle).
4. **Schema unification for results** — t3 sweep JSONs vs veritx-native
   result JSONs vs the future manifest (Q8). Deciding the target schema is
   part of the provenance work, not this document.
5. **`Checking Non-Exited Systems ...` as a read_wait terminator** —
   **RESOLVED (PR 5, 2026-09-17):** exhaustively grep'd both vendored
   astra-sim trees — no binary emits it, `All Request Has Been Exited`, or
   `ERROR: Some Requests Remain`. They are legacy-AstraSim compatibility
   relics; `read_wait` accepts the Checking line, no current backend
   produces it, and `check_end` always ends at EOF on our binaries.
   See `docs/protocols/llmservingsim-backend.md` §8.
6. **Container identity for BookSim runs** — current container default tag
   is `:latest` (mutable). Digest pinning is handoff §15; needs a decision
   on where the digest lives (trusted config vs provenance capture point).
7. **Frozen serving-contract decisions (post-PR5 review, 2026-09-17)** —
   binding until explicitly revised: (a) legacy bare-workload-path is THE
   serving command contract — do not migrate serving to `load`/`run` (the
   congestion-unaware analytical frontend silently misreads it); (b)
   empty-queue `run` is not a supported semantic — fixture-only surface;
   (c) PR6 must not inherit `parse_output`'s "pick sys 0" shortcut —
   multi-instance attribution uses the full per-NPU burst. Recorded in
   `docs/protocols/llmservingsim-backend.md` §10.
