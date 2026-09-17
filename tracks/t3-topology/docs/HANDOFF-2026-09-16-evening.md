# HANDOFF — 2026-09-16 evening (t3 stabilization pass)

## Addendum — control-plane redesign kickoff (same session)

The control-plane redesign handoff was received and its immediate
instruction executed: **Phase 0 + Phase 2 only, no Python scaffolding.**

- **Phase 0 (corrected Bash baseline): DONE this session.** Every defect
  on its Phase 0 list is fixed and verified — see "Fixed and verified"
  below (ASTRA arg forwarding, ONE execution path, `_veritx_sub`, trace
  builders, T3_RESULTS semantics, lint/check gates, paging/pager,
  unreachable branches).
- **Phase 2 (golden corpus + semantics): DELIVERED.**
  - `../CONTEXT.md` — domain vocabulary, every term code-cited
    (BookSim/ASTRA/LLMServingSim, interactive protocol, backend word
    collision, run/result/anchor, deterministic vs stochastic).
  - `docs/SEMANTIC_QUESTIONS.md` — all handoff §34 questions answered from
    source where the code settles them: the full multi-instance protocol
    framing table (`load`/`run`/`pass [t]`/`done`/`exit`, the
    one-`Waiting`-per-command rule, load's reply-less exception), `Waiting`
    semantics, backend owns the clock, per-integration sync vs session
    (Q5), success definition (Q6), preset locations (Q7), units (Q10),
    two-comparison-families (Q11). Six open questions listed (livelock
    diagnostics needed before Slice B, serving RNG, analytical seed,
    result schema unification, `Checking Non-Exited` legality, container
    digest home).
  - `dse/tests/test_golden_booksim.py` — 5 tests: pinned-seed determinism,
    recorded golden value (**35.0573** = mesh4x4 ir=0.1 seed=42 FINAL
    measurement period), the stochastic-without-seed hazard (documented
    spread 32.6–35.3), and two failure cases (bad cfg, missing cfg). Live
    binary, real process boundary, skipped when binary absent.

**Load-bearing discovery for the redesign:** BookSim prints one latency
line per sampling period — the golden metric is the *last* line with
"(1 samples)"; matching the first line silently compares warmup values.
Also: unseeded BookSim at ir=0.1 varies run-to-run — any parity harness
must pin `seed = 42;` first.

**Next session's first moves (per redesign §30):** Phase 1 ADRs (immutable
runs, run identity, fingerprint resume, trusted-config boundary, no-shell
for agents — short, invariants only), then PR 2 (spec → resolved spec →
hash → run dir → manifest skeleton, no execution). Do NOT start from a
package skeleton; Slice A (standalone BookSim) comes after the skeleton
exists, reusing the golden corpus as its acceptance test.

---

## Original handoff (stabilization pass)

Read this first. Newest handoff wins over older ones
(`HANDOFF-2026-09-16-PM.md`, `HANDOFF-2026-09-08-*` predate this one).

**State at handoff:** dse suite **793 passed, 1 skipped** (5 new golden-corpus tests) · `bash -n t3` clean ·
`t3 lint` rc=0 (and rc=1 with a deliberately broken probe file) · `t3 check`
rc=0 with required-tools gate · `t3 selfcheck` registry OK · native
`CONFIG=smoke_test ./t3 astrasim --selfcheck` → "selfcheck OK" (flags survive).

## What this session did

An external audit of `t3` (2,708 lines) was verified claim-by-claim against
the real file before anything was touched — several claims were confirmed,
one was misread, and two more bugs were found *by our own fixes* and caught
by smoke runs. All fixes follow semantic compression (2nd-instance rule,
one implementation per concept, dead code deleted not patched).

### Fixed and verified

1. **`_veritx_sub` rewritten** — old 4-arg `_pre` design consumed `sub1` as a
   phantom "typed sub", crashed `generate` under `set -u` (unbound `$1`), and
   hid the default sub from its own picker. Now: `_veritx_sub <verb>
   <default-sub> <other-subs...>`; picker gets the full choice set in
   declared order. The `_pre` mechanism was deleted (no caller ever passed a
   typed sub — dead code).
2. **Malformed trace builders fixed** — the tail now prepends
   `("$_v" "$_sub")` exactly once; every branch stores post-sub args only.
   Killed the `veritx trace slice slice …` class of commands and the
   unreachable duplicate `trace extract` branch (its good "extract mode"
   picker content was already in the live first arm).
3. **ASTRA-sim: ONE execution path** — the host fast-path no longer rebuilds
   a partial command line (which dropped every user flag, e.g.
   `t3 astrasim --tp 8 --seq-len 4096`). It re-execs itself with
   `T3_ASTRASIM_NATIVE=1`, which (a) skips the container hop — the frontend
   was just proven host-runnable via ldd, and the container's old glibc
   can't load it — and (b) lands in `cmd_astrasim`, the single owner of the
   flag contract (env defaults + MODEL_* overrides + forwarded "$@").
   Also fixed native mode's import: `cmd_astrasim` sets
   `PYTHONPATH=$T3_DIR/dse` (previously only the container's env.sh did).
   CLI/TUI/web now behave identically.
4. **`t3 lint` is a failing gate** — py_compile failures set rc=1 (previously
   `_warn` masked them), plus `bash -n` on `t3` itself, plus shellcheck
   when installed (skipped with a warning when not).
5. **`t3 check` is a real preflight** — required (python3, booksim) vs
   optional tools are distinguished; a missing required tool fails rc=1.
   Previously always exited 0.
6. **`report` help reachable** — split out of the `analysis|aggregate|plot)`
   case arm that swallowed it.
7. **Menu ←/→ paging** — `←` now goes to the previous page (both arrows
   previously advanced).
8. **TUI pager (scrolling window)** — `_ui_pick` (10 rows) and `_ui_multi`
   (12 rows) shared `_ui_page_start`/`_ui_page_ensure`: cursor walks the full
   filtered list, the render window follows it, `(i/N · ↑↓ scrolls)` footer,
   and filtering-shrank lists reset the window. Previously the cursor could
   select invisible items past the fixed slice.
9. **T3_RESULTS clobber fixed** — `_forward_path` now sets
   `T3_RESULTS_EXPLICIT=1` when the user forwarded a custom dir, and
   `_dispatch` re-derives T3_RESULTS only when that marker is absent.
   Custom results dirs survive the container round-trip.
10. **timeloop-workload forwarding** — each stage gets only the flags it
    actually parses (`gen_workload`: `--model/--config`;
    `run_experiments`: `--configs`); blind `"$@"` to both crashed one stage
    whenever the other's flag was passed.
11. **Verb-fallback single source** — `_veritx_verbs_fallback()` is the one
    literal; `_veritx_verbs()` prints it as fallback, `_t3_registry_selfcheck()`
    diffs against it (there were two divergent copies; selfcheck caught it).

### Bugs found by our own fixes (both caught by smoke runs)

- `_forward_path`'s `[ "$_var" = "T3_RESULTS" ] && …` tail made the function
  return 1 for every other var → `… || exit 1` killed every host dispatch.
  Fixed with an explicit `if`.
- The astrasim sentinel initially still hopped into the container (native
  re-entry went through the top-of-file container exec). Fixed by treating
  the sentinel as native (`IN_CONTAINER=1` reuse) *after* the binary was
  ldd-proven.

### Audit claims checked and deliberately NOT acted on

- **`_run_line` `set -- $1` word-splitting** — real, but the input is a
  filtered typed line from `_ui_runner` (see comment at `_run_line`); fixing
  quoting here needs the runner's line handling redesigned first. Deferred
  with the TUI polish batch.
- **`t3 results/<CONFIG>/topology_sweep.json` shared-mutable-state** — real
  design issue (see Open problems #2).
- **Comparability gate / multi-seed defaults / image digest pinning** — real
  research-validity issues; they live in `run_experiments.py`/configs, not
  the Bash layer. Tracked as Open problems #3–#5.
- **"Any directory" claim in help text** — cosmetic; not touched.

## Open problems (next session's queue, priority order)

1. **Provenance manifests (biggest research-validity gap).** Every simulation
   run should write a `manifest.json` next to its results:
   run_id, git_commit + dirty flag, container image **digest** (not
   `:latest` — that's the current default in `t3` line ~42), booksim /
   astrasim versions, full argv, config hash, trace sha256, seed,
   started/finished, status. `run_astrasim.py` and `run_experiments.py` both
   need it; `veritx doctor` deep battery should then verify a fresh run's
   manifest matches its results (self-checking provenance).
2. **Immutable run dirs + comparability gate.** Replace
   `results/<CONFIG>/topology_sweep.json` (shared mutable) with
   `results/<CONFIG>/runs/<ts>_<hash>/{manifest.json, sweep.json}` + a
   `latest` symlink; compare/report consume explicit run IDs. Then add a
   comparability gate before ranking: refuse to rank across differing node
   count, trace, packet size, bandwidth, routing, VC/buffer, simulator
   version — with an explicit `--allow-incomparable` escape. (The external
   audit's `mesh_4x4` vs `dragonfly_72` in one table complaint.)
3. **Multi-seed statistics.** Default seeds=1 in compare/quick-compare is
   indefensible for stochastic configs. Default ≥3 seeds, report
   mean/stddev/95% CI/N; the Pareto scoreboard should consume the same.
4. **CLI split (deferred twice, now overdue).** `veritx_dse/cli/cli.py` is
   ~4,000 lines / 32 commands. Split into `cli/commands/<family>.py` with
   `COMMANDS` aggregation staying the single registry. Do it *before*
   adding commands, not after.
5. **`tools/multi_workload_pareto.py` (841 lines)** — decision logic still
   inline in `main()` outside `aggregate()`; same extraction as the earlier
   tool seams (pure decision core, thin IO shell).
6. **`dse/README.md` (3,185 lines) vs AGENTS.md disagreement** — two wiki
   claims conflict about file locations; compress README into a pointer +
   what only it knows, keep AGENTS.md as the single index.
7. **`_state_set` concurrency** — temp-file+mv is atomic but two concurrent
   sessions still last-writer-wins silently; acceptable for now, revisit if
   parallel sessions become common (flock or per-session state).
8. **Shellcheck adoption** — lint supports it; the file is not yet
   shellcheck-clean. Run it, fix findings or add targeted disables; then
   add a builder smoke test (drive `_veritx_sub` branches non-interactively
   and assert the assembled argv) so builder regressions are caught in CI
   instead of by hand.
9. **Session-10 salvage integration** — `archive/session10-salvage/` holds
   the parallel implementations (zero_load.py analytic latency floors is the
   strongest candidate); integrate or delete deliberately. Also: the 5.2 GB
   `.treehouse` worktree farm can be deleted once salvage is settled —
   awaiting user's word.
10. **Paper-facing work (parked, do not let it block stabilization):**
    protocol crossover experiment (LL vs Simple, paper §3.2) needs the
    session-10 `protocol_crossover.py` reconciled against our links/anchors
    before any crossover claims; everything else in the ASTRA-sim 3.0
    feature list (Load-Store repr, GPU model, InfraGraph) remains
    not-implemented-here by explicit decision.

## ADDENDUM — 2026-09-17: Phase 1 ADRs + PR 2 skeleton landed

Redesign plan (control-plane migration) progress after this session:

- **Phase 0 (Bash baseline)**: was already done 2026-09-16 evening — every
  item on the redesign's Phase 0 list is fixed and verified here.
- **Phase 1 (ADRs)**: `docs/adr/0001..0006` — immutable runs, run_id vs
  experiment_hash, filesystem-authoritative, fingerprint resume, trusted
  config vs scientific intent, automatic provenance + no-shell boundary.
- **Phase 2 (golden corpus)**: `dse/tests/test_golden_booksim.py`
  (5 tests, seed-pinned; golden latency **35.0573**) + `CONTEXT.md` +
  `docs/SEMANTIC_QUESTIONS.md` (§34 answered from source).
- **PR 2 (spec -> resolve -> hash -> run dir -> manifest)**: shipped.
    - `dse/veritx_dse/core/spec.py` — strict boundary (pydantic
      `extra=forbid, strict=True`; "64"->64 coercion rejected), resolution,
      canonical hash (notes/name excluded), plan() with bound hash.
    - `dse/veritx_dse/core/runs.py` — Run dirs under `runs/veritx-runs/<uuid7>/`
      (git-ignored), state machine (CREATED..INTERRUPTED, legal transitions
      only), atomic writes via `core.recovery.atomic_write`, automatic
      provenance (git, binary, argv, allowlisted env), results frozen after
      terminal state, SUCCEEDED requires ≥1 recorded result.
    - `dse/tests/test_run_core.py` — 23 seam tests (no mocks).
- **Newly fixed this session** (found via the user's baseline paste):
    - `float('-')` crash: BookSim prints `= -` for sample-less stats
      (zero delivered packets); regexes in `simulation/booksim.py::parse_output`
      now use a number-shaped `NUM` fragment (`synthesis/evaluator.py`
      `_PLAT_RE`/`_HONEST_RE` aligned). Regression-tested.
    - Topology/trace mismatch is now a **pre-checked, diagnosable skip**:
      `TraceStats.max_node` (src/dst max) vs anynet router count in
      `run_compare` — the 4-node `topo.anynet` vs 33-node
      `chakra_converted.trace` case now reports "trace addresses nodes
      0..48 but this anynet has only 4 — remap the trace or use a larger
      net" instead of crashing the batch. NOTE: `topo.anynet` currently in
      `runs/booksim/` is a 4-node net and cannot carry that trace.
    - t3 anynet picker label now names the homes it actually scans.

Suite: **819 passed, 1 skipped**. Next: Slice A (PR 3) — standalone BookSim
through `spec.resolve()` + `Run` (the golden corpus is its acceptance test);
then PR 4 fake-process fixtures, PR 5 protocol fixture.

## ADDENDUM 2 — 2026-09-17 (later): Slice A / PR 3 landed

- **`veritx_dse/core/experiment.py` — `run_experiment(spec_dict) -> Run`**:
  the redesign's first vertical slice as ONE deep function (codebase-design
  vocabulary: small interface, all of validate→plan→run→result behind it).
  Rejects unknown fields/coercion before creating anything; resolves
  topology by registered ID (ADR 0005 join point); CANCELLED runs carry
  the rejection reason in manifest.results (evidence, not silence);
  Ctrl-C → INTERRUPTED + re-raise (process ownership stays with the loop).
- `run_topology_eval` gained the `runner` passthrough
  (`run_booksim` already documented that seam for tests).
- **`dse/tests/test_slice_a_booksim.py`** (6 tests, real binary, no mocks):
  e2e SUCCEEDED with automatic trace-sha256 provenance; two executions of
  one experiment → same experiment_hash, new run_id, identical latency;
  frozen spec/plan hash consistency; bad intent (unknown field, unknown
  topology id) raises with ZERO debris on disk; missing trace → CANCELLED
  run with evidence. Determinism cross-checked against the golden corpus.
- AGENTS.md now points agents at CONTEXT.md / docs/adr / SEMANTIC_QUESTIONS
  / the new seam (redesign §23, kept short).

Suite: **825 passed, 1 skipped** (~9s of that is Slice A e2e on the real
BookSim). Next per plan: PR 4 fake-process supervision fixtures, PR 5
LLMServingSim protocol fixture (livelock diagnostics first — see
SEMANTIC_QUESTIONS Q1), then Slices B/C.

## ADDENDUM 3 — 2026-09-17 (pipeline run 20260916_213026 triage)

Three-leg failure diagnosed — three DIFFERENT root causes, only one a bug:

1. **Timeloop leg (code bug, FIXED)**: the leg hardcoded the vendored
   `third_party/timeloop/bin/timeloop-mapper` — host-built against 24.04
   sonames (`libconfig++.so.11`), unloadable in the 22.04 container. The
   Dockerfile already builds a compatible timeloop into `/usr/local/bin`.
   Now `_pick_timeloop_mapper()` prefers container-built, falls back to
   vendored, and records `timeloop_binary` provenance in the manifest.
2. **BookSim leg (not a bug — impossible budget, now GUARDED)**: 56.1M-pkt
   trace (hpc_real model, 4,032 pkts/allreduce-invocation × 870 inv × 8
   inst × 2 classes) at measured ~13k pkt/s ≈ 70 min vs 600 s budget. AND
   the model's own stats print IR 0.486 — saturated. Step 4 now runs
   `predict_booksim_budget()` (header read, cheap) and refuses with the
   number + options BEFORE burning the budget; `eval_budget` in manifest.
3. **ASTRA leg (stall — instrumented, NOT closed)**: logs show init
   completed (64 ranks, ring built) then silence for 600 s. The leg now
   runs under a liveness loop (30 s samples of ASTRA's own log growth;
   kills at budget with diagnostics: log bytes at kill, quiet-for-s,
   stdout/stderr tails). stdout/stderr go to files (pipe-deadlock proof).
   Root cause still OPEN — see docs/RATE-MISMATCH-OBSERVATION and the
   credit_delay thread; next session should rerun the leg alone with
   T3_TIMEOUT high and the new diagnostics capturing the stall point.

User-lever for hpc_real-scale runs: lower `invocations_per_batch`, or
raise the step budget deliberately (the guard now makes the cost visible
up front). Suite: **835 passed, 1 skipped**.

## ADDENDUM 4 — 2026-09-17: ASTRA stall ROOT-CAUSED (was never a stall)

The "init-then-stall" was a **legitimately huge simulation killed at
budget**. Evidence chain (all reproducible natively in /tmp/astra_repro):

1. Native repro of the exact failing run: spins at 99.5% CPU in the sim
   drain loop, no `sys[i] finished` lines, killed at timeout (RC 124).
2. `--method shortest` CDG check on the winner: acyclic, 232 channels —
   `min_anynet` (anynet.cpp:214-244) does expose the full VC range with
   no escape class, but on THIS topology even BookSim's own Dijkstra
   routes yield an acyclic CDG, so the deadlock hypothesis DIED here.
3. 4-NPU leg (fresh pytest artifact) completes: the leg is fine.
4. **Plain 64-ring also "hangs"** with the default workload — so the
   winner's irregularity is NOT the trigger either.
5. Arithmetic: 16 MiB ring all-reduce at k=64 ≈ 37M packets ≈ 12-40+ min
   of sim wall time at this BookSim's pace vs the 600 s budget.
6. **Decisive A/B**: 64 KiB payload → 64-ring finishes in 3 s (147,270
   cycles, all 64 ranks); the irregular winner finishes in 4 s, 64/64
   ranks. Topology, VCs, routing, init: all exonerated.

The 4× "ring of node 0" stderr lines are the RankTopology construction
for ONE Sys (ring id 0 of 1 dim); log flushing, not a partial init.

Also fixed while bisecting: `min_anynet`/`route()` use `cout` (stdout)
— when stdout is block-buffered to a file and the process is SIGKILLed,
the buffered tail (including the `Routing table` banner) is lost, which
is what made the earlier logs look truncated mid-init.

**Pipeline changes:**
- `--astra-msg-mb` flag (default auto: ~nodes KiB, capped 16 MiB — the
  16 MiB default was sized for 8-NPU smoke tests and scales as k²).
- ASTRA timeout hint now states the measured extrapolation and the
  override flags. Auto-scaling is logged when it kicks in (n>=32).
- Manifest records `msg_size_bytes`; provenance for cross-run compare.
- Certifier note (H1 was RIGHT about the mechanism, WRONG about the
  trigger): `min_anynet` genuinely has no deadlock-avoidance; our CDG
  cert happened to pass for this topology, but `winner_astra.cfg` runs
  BookSim's internal Dijkstra table, NOT a certified exported table.
  The cert↔sim coupling gap is real and stays OPEN (export the cert
  table to BookSim or ship a table routing function) — just not what
  bit us this time.

Suite: **835 passed, 1 skipped**. Debug artifacts:
/tmp/astra_repro (repro scripts + A/B logs).

## ADDENDUM 5 — 2026-09-17: one routing truth (smart-model review landed)

The external review (H1/H5 bisection plan) was executed; H5 won (see
ADDENDUM 4). Two of its recommendations are now permanent, plus the
packetization fact it flagged as unknowable from upstream:

1. **Packetization pinned from source**: the vendored Booksim2NetworkApi
   converts sim_send bytes -> flits at 8 B/flit (`booksim2-flit-bytes`,
   main.cc:127 default) via its OWN EmbedTM packet builder — the
   standalone BookSim `packet_size=64` knob is NEVER read on this path.
   16 MiB all-reduce at k=64 => ~4.1M flits/rank, ~265M flits injected
   total. H5's arithmetic confirmed at the flit level.
2. **AnyNet integrity (review §6)**: winner.anynet verified clean —
   64/64 routers, fully bidirectional (0 asymmetric edges), strongly
   connected both directions, no self-links. The guard logic already
   lives in core/anynet.py (BookSim-style symmetrization, single-attach,
   sequential IDs) and gates compare/baseline runs.
3. **`--method booksim` in deadlock_routing (review §5, Design A's
   concrete first step)**: a Python replica of AnyNet::route()'s exact
   tie-breaking, transcribed from the C++ (std::set ascending candidate
   scan -> first strict min; strict-< relaxation -> first predecessor
   sticks; std::map ascending neighbors). The certificate now evaluates
   the SAME routes the simulator executes, all pairs, all traffic
   patterns — closing the cert↔sim route-set mismatch without touching
   the simulator. Winner re-certified under its own simulated routes:
   acyclic. `--export-table` writes <out>.routes.csv for permanent
   cert<->sim diffing.
4. **Test-discovered hazard, textbook-consistent**: on ANY wraparound
   ring, min_anynet's tie-breaks produce a CYCLIC CDG (the dateline
   argument — ring topologies need an escape VC under minimal routing,
   regardless of parity). The lexical `shortest` method misses some of
   these; the booksim-exact method catches them. Ring parity does NOT
   matter (both 5-ring and 6-ring certify cyclic; grids certify acyclic).
   Reminder that `min_anynet` itself has no deadlock-avoidance — the
   full C++ table-routing function (Design A complete) remains OPEN.

Suite: **853 passed, 1 skipped**.

## ADDENDUM 6 — 2026-09-17: timeloop exit 127 root-caused AND reproduced

Run 20260917_032223 (automotive_adas, 64 nodes) failed the energy leg
with `libconfig++.so.11: cannot open shared object file` on
/usr/local/bin/timeloop-mapper — i.e. ADDENDUM 3's fix (prefer the
container binary) exposed a SECOND bug: the leg set LD_LIBRARY_PATH to
the vendored build dir UNCONDITIONALLY, whatever binary was picked.

Mechanism (reproduced exactly inside container `funny_black`):
1. Inside a t3 container, /workspace IS the host repo mount.
2. The vendored build dir (host-built, 24.04-era: libconfig++.so.11,
   GLIBC_2.36/2.38, boost 1.90) sits at /workspace/third_party/timeloop/build.
3. The leg injects that dir into LD_LIBRARY_PATH; the container's own
   HEALTHY mapper resolves libtimeloop-model.so from it (shadowing the
   image's /usr/local/lib copy), and the host lib drags in .so.11 ->
   exit 127 naming the healthy binary. Poisoned-ldd output captured;
   `env -u LD_LIBRARY_PATH` the same mapper runs fine.

Rule now enforced by `_timeloop_env(provenance)`: the loader env must
match the picked binary's provenance — vendored binary gets the
in-tree build dir; container binary gets it STRIPPED (even if
inherited). Regression tests pin the contract (preflight tests).
Execution context is part of program semantics — redesign §4.2.

Audit trail of eliminated theories (all verified, none true): every
podman container on this host pins image 0a28794eb426 whose mapper
links .so.9 and runs; no container /usr/local/bin mutations (podman
diff clean); no stale :latest tag switch between Sep 15-17. The bug
was environment injection, not any binary.

Suite: **856 passed, 1 skipped**.

## Verification recipe (run all after touching `t3`)

```bash
bash -n t3                                   # syntax
script -qec "./t3 lint" /dev/null; echo $?   # gate: expect 0
script -qec "./t3 check" /dev/null; echo $?  # gate: expect 0
script -qec "./t3 selfcheck" /dev/null; echo $?  # registry: expect 0
CONFIG=smoke_test timeout 120 ./t3 astrasim --selfcheck  # native path + flag forwarding
cd dse && python3 -m pytest tests/ -q        # 819 passed, 1 skipped
```

Note: `script -qec … /dev/null` is needed because `t3`'s container dispatch
behaves differently under a pipe (no TTY). On the host, `t3` tries podman/
docker; inside this sandbox there is no container runtime, which is exactly
why the astrasim native sentinel path is now the one true path for that
frontend.

## ADDENDUM 7 — 2026-09-17: PR 4 landed (process supervision) + repo cleanup

**PR 4 — process failure/cancellation fixtures (§21/§26 Level 2):**
- `veritx_dse/core/process.py`: `supervised_run()` — the deep one-shot
  process primitive the handoff §5/§7 authorize. Owns the child in a NEW
  SESSION (signals hit the whole tree, never our ancestors); timeout =
  SIGTERM -> grace (5s) -> SIGKILL; bounded head+tail capture (§27 stderr
  floods cannot balloon memory or deadlock the pipes); Ctrl-C kills the
  group then propagates (UI cancellation == process cancellation).
  `SupervisedResult` IS-A CompletedProcess (+wall_time_s, timed_out), so
  run_booksim's `runner` seam contract is unchanged; injected runners
  take the legacy path (type-checked, not getattr — a MagicMock would
  auto-vivify any probed attribute).
- `run_booksim` default runner = supervised_run; timeout now classified
  BEFORE zero-delivered/partial-stats, raises TimeoutError carrying
  partial output.
- `tests/fake_sim.py` + `tests/test_process_supervision.py`: REAL
  processes, no subprocess mocks — group-kill (grandchild does not
  survive), TERM-ignoring child reaped via SIGKILL, flood bounded,
  signal deaths as negative returncodes, real-SIGINT cancellation.
- Slice-B boundary documented IN the module: interactive
  LLMServingSim sessions must NOT go through supervised_run (§4.2).

**Cleanup (user-requested), with the rules made explicit:**
- DELETED: `runs/experiments/*` without manifest.json (never became
  runs: 033413, 101916/53MB); `log/` at repo root AND `tracks/t3-topology/
  log|logs/` (simulator spew — root cause FIXED: `chakra_to_et` now runs
  with cwd=tempdir because astra's CmdLineParser defaults
  --logging-folder to relative `log/`, so it was writing log/log.log
  into REPO/ whenever cwd=REPO); .playwright-mcp, .pytest_cache,
  product/__pycache__, t3 product/ pycache.
- ARCHIVED to `archive/` (gitignored): 108 unreferenced experiment runs
  -> archive/abandoned-experiments/; session-ses_f714.md ->
  archive/session-transcripts/; .scratch/MERGE-HANDOFF.md ->
  archive/handoffs/. KEPT in runs/experiments/: the 3 doc-referenced
  runs (20260916_213026 ASTRA-stall evidence, 20260917_032223 timeloop
  root-cause, 20260917_102744 green baseline). runs/veritx-runs/ (new
  immutable home) untouched.
- `product/` is LIVE (example-spec home for `veritx run --spec`, path
  resolution pinned by batch-E tests) — documented via
  product/README.md instead of renamed.

Suite: **869 passed, 1 skipped**. Next per plan: PR 5 LLMServingSim
protocol fixture (needs §34 protocol facts answered from source first).
