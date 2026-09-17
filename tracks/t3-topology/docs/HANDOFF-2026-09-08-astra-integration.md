# HANDOFF — ASTRA-sim × veritx-cli integration + DP-serving hang
Date: 2026-09-08 ~23:00 IST · Repo: `/home/datavex/veritx-research` (branch `epic/booksim-forward-port`)

## 0. Mission
Make Manal's ASTRA-sim BookSim2 work (`/home/datavex/veritx-manal`, branch `astrasim-manal`)
together with our veritx-cli on epic. His smoke went green on his tree; we ported the fixes to
epic, fixed `veritx evaluate astra`, and hit a NEW blocker: serving's dense-DP test hangs.
Read this file fully before touching anything.

## 1. Ownership split (avoid collisions)
**Buffy (me):** all C++ + build system + the DP-hang diagnosis.
- `third_party/booksim2/src/*`, `third_party/astra-sim/**`, both astra build dirs, main.cc,
  Booksim2Fabric.hh, veritx_embed*.cpp, /tmp log forensics, gdb.

**Agent 2:** everything Python-side + the manal tree (read-only diffs are fine for both).
- `tracks/t3-topology/dse/veritx_dse/cli/cli.py`, `tracks/t3-topology/dse/tests/**`,
  manal-tree comparisons (`git -C /home/datavex/veritx-manal ...`, diffs vs epic).
- If you need a C++ change, write it in this file under "Requests to Buffy", don't edit .hh/.cpp.

## 2. Completed on epic this session (ALL UNCOMMITTED)
1. **JSON unwrap** — `third_party/booksim2/src/veritx_embed.cpp`: `CreateEmbeddedTM` now
   detects a JSON config (BOM/`{` probe), reads `booksim-config-file` (resolves relative to the
   JSON's dir), feeds the real .cfg to ParseArgs. Added `#include "json/json.hpp"`.
   Why: ASTRA frontend passes network.json; the yacc grammar died with `Parse error on line 1`.
2. **Include path** — `third_party/astra-sim/extern/network_backend/booksim2/CMakeLists.txt`:
   added `${CMAKE_CURRENT_SOURCE_DIR}/../../helper` to BookSim2Fabric includes (nlohmann/json).
3. **Chunked run_cycles** — `Booksim2Fabric.hh`: 1K chunks + interleaved drains + early exit;
   `_drain_retired()` returns count. **FINAL STATE: applied (manal parity, copied from his tree).**
4. **`veritx evaluate astra` rewrite** — `tracks/t3-topology/dse/veritx_dse/cli/cli.py`:
   - `_parse_astra_cycles()` (regex `sys\[(\d+)\] finished, (\d+) cycles`)
   - `stdin=subprocess.DEVNULL` + `capture_output=True` (was: inherited terminal → binary sat at
     the interactive `Waiting` prompt forever → TimeoutExpired on every real invocation)
   - passes `--booksim2-extra=injection_rate=0.0` (template cfgs self-inject infinite traffic)
   - fail-fast canary: `--ets` must be an existing file AND `<base>.0.et` must exist
     (frontend idles ranks missing per-rank files → silent 0-cycle "success")
   - writes result JSON to `runs/astra/eval_<stem>.json` (cycles, per_rank_cycles, num_ranks)
   - fixed argparse help syntax error (`}` for `)`) + usage text `--ets <et_file>`
5. **Test fixture** — `tests/fixtures/astra_tiny/` (22 files): one-coll.et + `.0.et`..`.15.et`,
   system/logical_topology/memory.json + mesh4x4.cfg (copied from manal's green run),
   network.json (written: BookSim + booksim-config-file + num-nodes 16), README.provenance.
6. **New test file** — `tests/test_evaluate_astra.py`: 6 tests (parser units, convention gates,
   one LIVE binary single-shot test). **6/6 pass.**
7. **Ported from manal (both verified, trees now identical for these files):**
   - `third_party/astra-sim/astra-sim/workload/Statistics.cc`: comp_comm_overlap computed in
     signed math + clamped at 0 (was unsigned-wrap → ~1.8e19 garbage).
   - `third_party/booksim2/src/main.cpp`: standalone binary exit code (was inverted ternary →
     success exited 255).

## 3. Binary / build state (IMPORTANT, easy to break)
- Epic build: `cd third_party/astra-sim/build/astra_booksim2 && JOBS=$(nproc) ./build.sh`
  → canonical `third_party/booksim2`. Do NOT `cmake -D` from the wrong cwd (source dir is
  `third_party/astra-sim/build/astra_booksim2`, i.e. `..` from there).
- The pre-existing build cache pointed at the NESTED fork
  (`extern/network_backend/booksim2/booksim2`) — that's why the first live test failed with
  `Parse error on line 1` while my unwrap sat in canonical. build.sh fixed the cache (repro
  `bbe3` says canonical is the sanctioned default).
- **The two binary paths are HARDLINKS (inode 9321743)**: `third_party/astra-sim/astra-sim/
  network_frontend/booksim2/bin/AstraSim_BookSim2` == `third_party/llmservingsim/astra-sim/
  astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2`. md5 `13326f89d95c7b959db823a458328486`,
  mtime 22:51 = my epic_build3 (canonical + BLIND run_cycles). Serving resolves its binary from
  the llmservingsim copy (`serving/__main__.py:441` `astra_sim = os.path.join(cwd, "astra-sim")`,
  cwd=LLMSIM) — because of the hardlink both names always give the same file.
- llmservingsim has its OWN build tree: `third_party/llmservingsim/astra-sim/build/astra_booksim2`
  (cache: canonical). Which build dir last wrote the binary is unknown; treat the hardlink as
  shared state — rebuilding either tree may relink/unlink and desync the two names. After ANY
  rebuild, re-verify: `ls -i` both paths + md5.

## 4. What's verified green
- Manual tiny fixture through epic binary: rc=0, 0.1s, sys[0]=50310 cycles.
- **Differential proof:** all 16 per-rank cycles bit-identical between epic binary and manal's
  binary on the tiny fixture (`/tmp/epic_cycles.txt` vs `/tmp/manal_cycles.txt`).
- `test_evaluate_astra.py` 6/6 (0.18s when binary has chunked run_cycles; 68.5s with blind).
- Full dse suite: 228 passed, 4 skipped, **1 failed** = the DP hang below.

## 5. RESOLVED 2026-09-08 late — dense-DP serving hang (root cause: PYTHON, not C++)
Test: `tests/test_full_pipeline.py::TestLLMServingSimServe::test_serve_dense_dp_new_config`.
Diagnosis chain (all reproducible): (a) recursive diff canonical vs nested booksim core — only
stats/config divergences, nested fork exonerated, no A/B build needed; (b) gdb attach (sudo
sysctl kernel.yama.ptrace_scope=0 temporarily, restore to 1; pgrep with `AstraSim_BookSim[2]`
bracket trick — plain -f matches your own shell!) — backend was NOT spinning: main thread idle
in `std::getline`; the 1120 STATE heartbeats are the round-140 final drain (exec keeps pace with
sched, ~900 deferred events crawling 467M→470.7M) followed by clean `sys[*]` statistics;
(c) `python3 -X faulthandler` + SIGABRT → python blocked in `controller.read_wait:32`;
(d) `strace -p <python>` → **`write("done\n")` / `read("Waiting\n")` ~14K round-trips/sec**.
ROOT CAUSE: the shutdown gate required `len(done_inst_npus[i]) == 2` (two distinct NPU polls per
instance), but the BookSim backend reports per-round completion for ALL NPUs in one burst and the
instance-rebind pins `sys` to the instance's FIRST NPU — the second poll never arrives, so
`done_instance` never filled, `exit` was never sent, and each poll wrote `done` which the C++
side ("done" = sleep, the missing-requests fix) answered with a bare `Waiting` echo → livelock.
The old backend's `done == exit` behavior had masked this bug by killing the binary.
FIX (Python side — Agent 2 lane, applied in `serving/__main__.py` ~line 1590, uncommitted):
for `network_backend in ("booksim", "analytical")` one poll suffices
(`_done_npus_needed = 1`); non-reporting backends keep the old rule. Verified: repro rc=0 with
`Exiting simulation...`, targeted suites + FULL dse suite green (348 passed, 6 skipped, 80s).
Agent 2: please review that change, own it, and consider a regression test asserting the exit
handshake completes (or a bounded-rounds guard) for the DP cluster fixture.
Test: `tests/test_full_pipeline.py::TestLLMServingSimServe::test_serve_dense_dp_new_config`
(TimeoutExpired at 180s). Deterministic, reproduces manually:

```bash
cd third_party/llmservingsim && VERITX_BACKEND_STDERR=/tmp/dp_stderr.log VERITX_LEDGER=1 \
  timeout 90 python3 -m serving --cluster-config configs/cluster/single_node_dp_instance.json \
  --dataset workloads/example_trace.jsonl --num-reqs 1 --network-backend booksim \
  --booksim-replay-only --log-level WARNING --keep-inputs   # rc=124
```

### Evidence (from /tmp/dp_stderr.log, ledger-enabled)
- Rounds 1–139 complete normally (finished lines every ~6M cycles, ~10ms wall each).
- **Round 140 wedges in the quiescence drain loop.** Heartbeat `[LEDGER][STATE] where=drain`
  every ~4s: `heap=5 next_ev==now sys_pending=4(0,1,2,3) inflight=0 arrivals=0 req_packets=0
  fold_groups=0 api_pending=0 can_advance=0`; sched/exec tick ~+100/line (loop is ALIVE,
  ~10ms/iter) but exec lags sched by a constant 5 and wall creeps only ~400K cyc/4s
  (≈ 468.2M → 470.2M). No Waiting, zero packets injected (replay-only).
- sys[1] ends at 470,754,620 cycles with exposed=464M vs GPU time only 6M — the DP-group
  alltoall wave never synchronizes across the 4 members.
- Booksim2Fabric.hh's own comment (lines ~83-86) describes this exact class of failure
  ("fabric lagged behind the event queue so the next DP-group ALLTOALL wave could never
  synchronize") — but see below, the fabric-lag mechanism is NOT the culprit here.

### RESOLVED (final) — Python-side shutdown livelock, NOT a C++/fabric bug
Supersedes the "pre-existing wedge" framing below. gdb (ptrace_scope temporarily 0, restored
 to 1 — verified) + faulthandler + strace chain:
- Backend was never wedged: main thread idle in std::getline at its command loop; the 1120
  "heartbeat" STATE lines were round 140's final slow drain ending in clean statistics.
- Python blocked in controller.read_wait; strace: write("done\n") → read("Waiting\n") spinning
  ~14,000×/s.
- Root cause: shutdown gate required 2 distinct NPU polls per instance
  (len(done_inst_npus[i]) == num_npus), but booksim/analytical backends report all NPUs in one
  burst and serving rebinds `sys` to the instance's FIRST NPU — the second poll never arrives,
  exit is never sent, each poll writes "done", which the C++ done-echo answers with bare
  "Waiting". The old backend's done==exit bug had been accidentally masking this.
- Fix (Agent 2, serving/__main__.py ~L1590): one poll suffices for booksim/analytical
  per-round-reporting backends; non-reporting backends keep the old rule. Gate branch is
  already guarded by `instance_id not in done_instance` (no double-append).
- Buffy code-review of the hunk: SOUND. Note: `else 2` fallback differs from upstream's
  num_npus rule for hypothetical >2-NPU non-reporting backends — acceptable, commented.
- DONE-PROTOCOL CONTRACT (closes the open design question): binary echoes exactly one
  Waiting per command (incl. done) + keep-serving semantics; serving polls completion via
  scheduler state, once per instance. Both sides verified together.
- Verified independently by Buffy: DP repro rc=0 in 1.7s; FULL dse suite 348 passed /
  6 skipped in 80.6s (no exclusions).

### Historical record of the elimination chain (kept for provenance)
**The wedge is PRE-EXISTING and NOT caused by any of this session's changes.** Evidence:
- Full epic-vs-manal source diff enumerated; every behavioral candidate individually tested.
- Chunked→blind Fabric A/B: hang persists (early-exit exonerated).
- main.cc swapped to manal's: rc=0 — but decode shows the ONLY control-flow hunk is
  `done` → exit. **Manal's binary passes the DP test by DYING at the first `done` and riding
  serving's clean-EOF path** (`_work_remains` is false for --num-reqs 1). Not a real fix —
  in multi-request DP runs his variant strands other instances' queued work (the exact bug
  epic's keep-serving semantics were written to prevent — see main.cc comment).
- Silent-done experiment (done echoes nothing): serving DEADLOCKS in read_wait — its loop is
  `read_wait()` BEFORE send, so every command incl. done must echo exactly one Waiting reply.
- Core diffs (trafficmanager/veritx_ext/injection) are stats-only (honest-latency fix).
  Statistics.cc was a report-value wrap bug (ported). No scheduling/flow-control deltas.

### Hypotheses tested (historical)
- ~~Chunked run_cycles early-exit~~ **EXONERATED by A/B**: reverted to blind
  `_tm->RunCycles(cycles)` (epic_build3), DP serving STILL hangs. (Side observation: blind
  stepping makes the astra test suite 68.5s vs 0.18s — the quantization fix is worth keeping
  for `evaluate astra` regardless.)
- ~~"Wrong binary, A/B invalid"~~ resolved: hardlinks ⇒ every repro used the rebuilt binary.
- NOT yet excluded: serving passes `--network-configuration=<network.yml>` (YAML!) — check what
  `CreateEmbeddedTM` does with a .yml (JSON-probe should no-op → .yml straight to yacc?? yet
  rounds 1–139 ran fine — resolve this contradiction).

### Leading hypothesis
**Canonical-vs-nested booksim-core behavioral divergence.** Before my session the binary was
built from the nested fork (stale cache); serving tests presumably passed at some point with
that. `BOOKSIM2_SRC_DIR` swaps the booksim core only (trafficmanager.cpp, veritx_ext.cpp,
veritx_embed.cpp, routers); Fabric + main.cc come from the extern tree either way. Canonical
has the `_trace_reqtime` fix (veritx_ext.cpp ×1, trafficmanager.cpp ×6) — nested state unknown.
A completion callback the system waits on (sys_pending never decrements, heap self-refills)
differs between cores.

### Next steps (ordered) — Buffy's queue
ALL RESOLVED. gdb plan moot (backend was idle, not wedged); done-protocol contract settled
(see §5 RESOLVED). Remaining: commits — Buffy commits C++ + cli.py + astra tests;
Agent 2 commits serving/__main__.py + their dse/test files.

## 6. Requests to Buffy (Agent 2 writes here)
- (empty)

## 6d. REMOTE MAP + CONSOLIDATION PLAN (verified 2026-09-09, resolves "port from veritx-with-cli" claim)
Remote state (datavex = anmol/veritx-research):
- datavex/main @ 2719de3e: Timeloop work; ZERO astra content. epic is 123 ahead / 0 behind.
- origin/veritx-with-cli @ f892deef: OLD serving/ layout; divergent, never merged to main;
  superseded by epic's third_party/ layout. The "port from veritx-with-cli" advice is stale.
- origin/astrasim-manal @ be6fcb35: STILL BROKEN (submodule pointer 160000 @ 518bd513 = empty
  checkout; run_astrasim synthetic-fallback bug). Manal's 2 fix commits (038fa3b5, d7bf7bbb)
  are UNPUSHED on /home/datavex/veritx-manal (clone ahead 2).
- epic/booksim-forward-port: 0d7a5342/d27caaa0/1b7bf765 — NO upstream, NOTHING pushed.

Conclusion: Manal's problems are all fixed but the fixes live only on two local machines.
Consolidation: merge astrasim-manal (local) into epic → resolve main.cc conflict (KEEP epic's
done-echo; reject his done=exit — see §5) + veritx_embed.cpp unwrap variants → rebuild →
full suite + differential → push epic → Manal resets onto it. veritx-with-cli needs nothing.

## 6e. INTEGRATION COMPLETE (2026-09-09, Buffy) — consolidated onto epic
Merges: c6904808 (latest main = feat/veritx-cli MR11 merge ef044f6e; both parents were already
in epic — formality merge) and 74b3e8b2 (Manal's local astrasim-manal d7bf7bbb, fetched from
/home/datavex/veritx-manal). Conflict policy: OURS for all astra frontend/embed/example-cfg
files (his vendor predates this session's fixes); HAND-MERGED trafficmanager.cpp (our
honest-latency hunks + his TraceTrafficManager factory hook + _OnPacketGenerated call);
t3 = main's version + Manal's astrasim grafts (cmd_astrasim, dispatcher entry, check probe,
help line) — his committed copy contained stale conflict markers, do NOT copy it verbatim;
baseline.yaml = ours (his copy was stale timeloop content + a stray marker).
Commits after merge: 6c9df2fa (Agent 2's serving shutdown-gate fix, reviewed SOUND, committed
by Buffy for tree coherence), 25acc222 (Agent 2's dse modeling + 709 test lines; without it
2 suite tests fail). STILL UNCOMMITTED BY USER CHOICE: Dockerfile, .dockerignore.

FULL TEST BATTERY (all green, on the fully committed tree, binaries rebuilt from merged core):
1. Static: t3 help/check rc=0 (astrasim entry present); run_astrasim + chakra selfchecks OK;
   veritx evaluate astra --help OK (entrypoint: python3 -m veritx_dse.cli.cli, dse/ cwd).
2. Builds: standalone booksim rc=0; embedded astra rc=0 (TraceTrafficManager compiles in);
   hardlinks synced 6f7840bc707076a1c72bc9043199d241.
3. Behavioral: tiny-fixture 50310 cycles, differential vs manal binary IDENTICAL 16/16 ranks.
4. Manal's original complaint E2E: source env.sh -> ASTRASIM_BIN resolves + executable;
   run_astrasim.py --config baseline --model llama7b --topo mesh4x4 rc=0, 6 runs ok,
   astrasim_sweep.json: traffic="astrasim(llama-7b_chakra_et)", astrasim_cycles=1101240
   (chakra trace consumed, NO synthetic fallback). PP=4->1 warning expected (documented).
5. CLI: test_evaluate_astra 6/6; make -n astrasim dry-run OK.
6. Serving stack: dense-DP repro rc=0 (Exiting simulation); full dse suite 348 passed /
   6 skipped in 75-80s, twice (with and without stashing Agent 2's files — committed now).
KNOWN REMAINING (all documented): inj_rate axis is a no-op for chakra runs (Manal-side sweep
semantics); --msg-size knob missing (full-size sweep intractable); t3 check astrasim probe
looks for a PATH 'astrasim' binary (cosmetic; env.sh ASTRASIM_BIN is the real probe);
epic branch has no upstream — PUSH PENDING USER APPROVAL.

## 6c. COMMIT STATUS (end of session)
- Buffy committed: 1b7bf765 (build.sh recording, Agent 2), d27caaa0 (all C++ astra fixes),
  0d7a5342 (cli.py + test_evaluate_astra.py + fixtures). Nothing pushed.
- READY TO COMMIT by Agent 2: `third_party/llmservingsim/serving/__main__.py` — Buffy's review
  verdict: SOUND (shutdown-gate one-poll change guarded correctly; analytical binary-path
  fallback hunks reasonable; note: `else 2` fallback differs from upstream's num_npus rule for
  hypothetical >2-NPU non-reporting backends — acceptable). Left uncommitted to avoid
  double-staging if Agent 2's session is live.
- Left alone (not ours): Dockerfile, .dockerignore (infra, unverifiable without docker build
  — USER DECISION), comm/, scorpio-demo/, .playwright-mcp/, log/ dirs.
- Suite state at commit time: 348 passed / 6 skipped (full, no exclusions).

## 6b. Buffy → Agent 2: your queue, refined
- The DP test is OFF my critical path (proven pre-existing; don't adopt done=exit hacks).
- Useful now: (a) grep serving for any OTHER read_wait-before-send contract spots that a
  future protocol change could break; (b) confirm `runs/llm/qwen3_tp16/*` defaults in
  cmd_evaluate_astra still resolve (they were pre-existing defaults, I only kept them);
  (c) run the full dse suite once more EXCLUDING test_full_pipeline.py (known red) and
  report the count here; (d) when Manal syncs, his main.cc done=exit MUST NOT be merged
  without the multi-request DP discussion above.

## 7. Known non-issues / context
- FINAL VERIFICATION (all pass): astra tests 6/6 in 0.22s; differential vs manal bit-identical
  (32 lines, all 16 ranks × 2 formats, sys[0]=50310 cycles); hardlinks synced md5 6ea417110ecf….
- DP dense test: GREEN after Agent 2's shutdown-gate fix (see §5 RESOLVED). Full suite
  348 passed / 6 skipped. The done=exit "fix" remains rejected regardless.
- Manal's tree is GREEN on his side (his build used canonical booksim2 too:
  `BOOKSIM2_SRC_DIR=/home/datavex/veritx-manal/third_party/booksim2`).
- epic vs manal embedded-path sources now IDENTICAL except: main.cc (epic has keep-serving done
  + per-round exposed reporting; manal has done=exit + exposed=wall_time) and the Fabric comment
  block. Keep it that way unless Manal syncs.
- epic canonical veritx_embed.cpp vs nested: unwrap hunks only (verified by diff).
- manal-nested vs epic-nested veritx_embed.cpp: identical.
- Commit style: two prior commits today — 038fa3b5 (vendoring, append-only) and d7bf7bbb
  (the 8-file fix). Nothing pushed. Do NOT push.
- Full-size sweep (32L/32MB) is intractable (~hours/run) — reduced sizes until a --msg-size
  knob exists; inj_rate axis is a proven no-op for chakra runs (Manal to fix on his side).

## 8. RESOLVED 2026-09-09 — `t3 astrasim` TimeoutExpired (post-simulation stdin hang)
Symptom: `MODEL=all_reduce CONFIG=smoketest TOPO=mesh4x4 ./t3 astrasim` died at 1800s with
`error: TimeoutExpired`, `no latency | n/a total cycles` — yet the simulation itself was fine.
Diagnosis chain (all reproducible, LEDGER=1/2 + gdb + fd-level stdin A/B):
1. NOT a sim-level wedge: with stdin at /dev/null the 16MB allreduce on mesh4x4 completes all
   16 ranks at 3,980,310 cycles in ~2:45 wall and **exits normally** (gdb: inferior exited
   normally after `[system] warning: Exiting`). Diff vs the green astra_tiny fixture: workload
   scale only. Sim wall-rate on mesh4x4: ~30K sim-cycles/s (~2.5 min / 3.98M cycles).
2. Root cause: `scripts/run_astrasim.py` spawned AstraSim_BookSim2 with **inherited stdin**.
   The frontend's post-simulation command loop (`std::getline` in main.cc) blocks forever on an
   open-but-silent terminal → parent's 1800s timeout fires although `sys[*] finished` already
   printed. Identical class to the §2 `veritx evaluate astra` fix (stdin=DEVNULL there, missed
   here). FD-level repro (fast, deterministic): open-but-silent pipe as stdin → all 16 ranks
   finish → process stays alive; /dev/null → clean exit. Same binary, same workload.
3. Fix: one line — `subprocess.run(..., stdin=subprocess.DEVNULL)` in run_astrasim_topology.
   Regression test: `tests/test_astrasim_spine_contract.py::test_run_invocation_closes_stdin`
   (red before, green after; proven at fd level, not by mocking).
4. Verified: original user command now `3980310 total cycles | ok` in ~3 min; full dse suite
   591 passed / 6 skipped.
5. Operational note: two orphaned AstraSim_BookSim2 processes from pre-fix runs were found
   spinning at 100% CPU (llama7b mesh4x4 since 21:42, dragonfly16 all_reduce since 22:49) —
   `kill` them; every pre-fix hang leaves one behind. dragonfly16 all_reduce was ALSO mid-run
   pre-fix, so expect that topology to be slow-but-finite too (mesh scaling suggests minutes,
   not hours; if a genuinely intractable topology emerges, that is a capacity question for
   ASTRASIM_TIMEOUT, not this bug).

## 9. Result schema extension (2026-09-09) — real latency data wired
`no latency` in sweep rows was a hardwired placeholder (`latency = None`, "null beats
fabricated"), NOT a leftover of the stdin bug. The frontend already prints the real numbers:
`sys[i] finished, N cycles, exposed communication M cycles.` Now wired, both paths:
- `run_astrasim.py`: `astrasim_cycles` = max wall across ranks; `latency_cycles` = same
  (embedded mode: collective wall time IS the zero-load latency — that's what topology
  ranking compares); `exposed_comm_cycles` = exposed of the slowest rank;
  `comm_overhead_pct` = exposed/wall*100. `hops_avg` stays null — honest gap, see below.
- `veritx evaluate astra` (cli.py): new `_parse_astra_exposed`; result JSON gains
  `exposed_comm_cycles` (slowest rank's exposed). `cycles`/`per_rank_cycles` unchanged.
- Tests: `test_astrasim_spine_contract.py::test_row_wires_exposed_comm_from_finished_lines`,
  `test_evaluate_astra.py` live test now asserts exposed > 0 from the real fixture run.
- REMAINING GAP (needs a C++ change — DO NOT do unilaterally): per-packet latency and hop
  counts are never emitted in embedded mode (BookSim's DisplayStats never runs; frontend
  stdout carries only the ASTRA-level numbers above). Wiring real hops_avg / packet latency
  means adding a stats dump to the frontend + REBUILDING the shared hardlink binary
  (see §3 — coordinate with serving before touching it).

## 10. DONE 2026-09-10 — [plat] per-packet stats shipped (C++ rebuilt, hardlink verified)
Supersedes the §9 "REMAINING GAP" above — the C++ change is IN, verified, and serving-safe.
- C++ (canonical third_party/booksim2 + frontend main.cc): ctor now initializes
  `_sim_state(warming_up)` (embedded never enters _Run() — it was UNINITIALIZED memory);
  embed builders set `record=true` + insert into `_measured_in_flight_flits` (retire-path
  assert requires membership); new `EmbedTM::PlatStats()` (exact sorted-vector percentiles
  from `_all_latencies`, hop aggregates from Stats Sum/NumSamples — never the 20-bin
  histogram, it clamps); main.cc prints one `[plat] packets= avg= min= p50= p95= p99= max=
  hops_avg= hops_min= hops_max=` line at end of each report round + batch tail.
- BUILD FIX (root cause, not workaround): frontend CMakeLists hardcoded the NESTED fork's
  include dirs which SHADOWED canonical third_party/booksim2 headers (build broke:
  'PlatSummary is not a member'). BookSim2 include dirs now come from BOOKSIM2_SRC_DIR
  (same tree whose objects are linked). build.sh green; hardlink pair verified
  (inode 9321026, md5 82d164d6…).
- Verified: astra_tiny fixture `packets=480 avg=23.375 p50=19 p95=44 hops_avg=2.875
  hops_min=2 hops_max=7` — 480 = 2(k−1)k flits for a 16-rank ring allreduce; hops 2–7 = 4x4
  mesh DOR distances. Sanity checks, not eyeballed.
- Python: run_astrasim.py `_parse_plat_line` → sweep rows carry `plat_stats`;
  cli.py `_parse_astra_plat` → evaluate-astra JSON carries `plat_stats`. Both None when the
  binary predates [plat] (honest absence). Tests: 8 new (spine contract + evaluate live).
- Full dse suite: 613 passed / 6 skipped.
- IF MANAL SYNCS: his tree lacks [plat] + the CMake fix; merging his main.cc done=exit
  variant is still REJECTED (see §7). His frontend would need the same PlatStats hunks or
  the Python side degrades to plat_stats=null gracefully (verified path).

## 11. 2026-09-10 — Usability + full-stack foundation (Agent 2 lane, verified)
- `veritx where <name>` — resolves traces/examples/fixtures/anynet by short name
  (extension optional, substring fallback, all asset classes searched); miss exits 1 and
  LISTS available assets. Tests: tests/test_where_interact.py.
- `veritx interact` — guided entry point; EOF/piped stdin prints copy-pasteable next steps
  and exits 0 (every flow stays scriptable; prompts only on a TTY).
- `veritx history [--reindex] [--topo --workload --status --min-cycles --limit]` —
  cross-run queries over runs/index.db (veritx_dse/core/store.py): rebuildable sqlite
  index over result JSONs, files remain source of truth, ingest idempotent, 8 tests.
  This is the base for the future read-only API + dashboard frontend (same Store class).
- Slop sweep: bare `except:` in bo_synthesizer fixed (KeyboardInterrupt hazard); no other
  bare excepts, zero TODO/FIXME, no hardcoded /home/ paths in live code.
