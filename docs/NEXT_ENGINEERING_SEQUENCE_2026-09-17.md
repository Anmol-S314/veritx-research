# Next engineering sequence — from live repo state, 2026-09-17

Branch `epic/booksim-forward-port` @ `bd1b6b7c`. Full suite just run here:
**971 passed, 1 skipped** (159 s). Reported counts of 941/962 are stale —
do not gate on counts; gate on what the relevant tests assert (checked below).

**What should I do next, in order?**

1. Add serving preflight to `cmd_serve`: refuse before spawning when the
   backend binary is missing/not-executable, the model cannot fit the
   configured NPU memory, the converter cannot represent the workload
   (PP today), or the requested mode is unsupported.
2. Make the `convert_rows` PP shim fail closed (raise, nonzero exit) instead
   of warn-and-continue; update the vendored-tree `METADATA.json` gap note
   and reinstall chakra so the edit takes effect.
3. Integrate the (already drafted, uncommitted) `network_mode` provenance +
   `TRACE_REPLAY` fidelity into serve results so replay can never be mistaken
   for simulation; golden gate = real simulation AND zero semantic loss.
4. Close the liveness delta: record the full logical last command and pin the
   six-state classifier with synthetic-observation tests.
5. Re-run both historical livelock configs under the probe, capture progress
   fingerprints as baseline evidence (both are PP-free, so step 2 blocking
   PP does not affect them).
6. Prove the real LLMServingSim → BookSim network path: tiny single-instance
   `--cycle-accurate` run with fabric-activity evidence (not just exit 0).
   If this path does not exist or cannot be made to work — STOP (see §7).
7. Build the PR6 slice: `ExperimentSpec(mode=serving)` → immutable run →
   structured metrics + provenance → single- and multi-instance goldens.
8. Then, in order: serving metric semantics → analytical slice → compression
   review → ComparisonSpec → workload/route truth → RTL → formal → synthesis
   → migration → Studio (see §6; order defended from code evidence).
9. Never fix livelocks with timeouts/round guards; the existing spin-abort
   stays a backstop, never the fix.
10. Never weaken `MemoryModel`'s fit check; move an equivalent check earlier
    instead.

---

### 1. Verified current checkpoint

Method: read source, read what the tests assert, ran the suite. Handoffs and
PRD labels were treated as hypotheses only.

| Claim | Verdict | Evidence |
|---|---|---|
| Integrity PR A (env/package reproducibility) | VERIFIED | `dse/tests/test_environment_contract.py` passes (in the 115-test integrity subset re-run here) |
| Integrity PR B (verification honesty) | VERIFIED | `dse/tests/test_pareto_honesty.py` passes; silent-exclusion fix `83734c78` visible in `cli/pipeline.py` failed-candidate rendering |
| Integrity PR C (lowering fail-closed) | VERIFIED | `dse/tests/test_trace_commands.py:231` asserts "Lowering refused", CLI fails, no trace; passes |
| Integrity PR D (routing-cert stopgap) | VERIFIED | `dse/tests/test_routing_stopgap.py` passes (stopgap status is explicit, not hidden) |
| Integrity PR E (typed metrics/provenance) | VERIFIED | `dse/tests/test_metrics_provenance.py` (8 tests) passes; every assertion inspected — closed fidelity vocabulary, binary SHA256, no partial-results-on-timeout |
| PR5: real-pipe fixture, no Popen mocks | VERIFIED | `test_serving_protocol.py:1-30` launches `fake_serving_backend.py` via real `Popen`; `grep` for `unittest.mock`/`MagicMock` across protocol/liveness/full-pipeline tests: zero hits; session spawns for real in `veritx_dse/simulation/llmserving_protocol.py:201` |
| PR5: `Waiting` = round quiescence | VERIFIED | `controller.py:30-39` reads until substring `Waiting`; `main.cc:285-343` emits `Waiting` after every command kind including bare `pass`; `done` explicitly replies `Waiting`-only |
| PR5: one outstanding command | VERIFIED | `__main__.py:1088` `read_wait` precedes all per-round `write_flush` sites (:1341–:1603); `main.cc` comment confirms every command needs exactly one `Waiting`-terminated reply or serving deadlocks |
| PR5: bare-path is the live wire path; `load`/`run` exist backend-side | VERIFIED | Serving writes bare workload paths from `utils.py:35-45` `get_workload()`; `main.cc:264-276` documents bare path as legacy `load`+`run`, with `load` (:347) queued-but-not-normally-used |
| PR5: analytical frontends differ; N-dim picks unaware | PARTIALLY VERIFIED | Code path real: `__main__.py:694-732` selects `AnalyticalAstraUnaware` for N-dim and prints an explicit notice — **not** silent, contradicting the "silently" wording. No dedicated test pins the protocol difference; no test file references the unaware binary |
| `waiting_without_progress` reproduces livelock shape | VERIFIED | `fake_serving_backend.py:159-161` + `test_serving_protocol.py:297-310`: 5 identical `Waiting` replies, zero completions, clock frozen |
| PR5.1 liveness wired in | VERIFIED | `__main__.py:30-32,1062-1112,1808+`: probe constructed, observations recorded, attached on EOF/spin-abort paths; all 10 desired fields present in `liveness.py:30-80`; six states defined |
| PR5.2 livelock regressions | PARTIALLY VERIFIED | Both tests (`test_full_pipeline.py:581-635`) exist, assert per-instance service (not bare counts), and passed live in this tree (binary present, nothing skipped). Both run `--booksim-replay-only`, so they pin scheduler-side completion only. Pre-fix failure rests on the archived issue, not a re-verified reproduction here |
| Reported suite "941 passed" / "962 passed" | CONTRADICTED (stale, harmless) | Just ran: 971 passed, 1 skipped. Counts drift with every added test; gate on assertions, not counts |
| Uncommitted working-tree PR6 prep (§17 PRD rows, `core/serving.py`, `test_serving_provenance.py`, `TRACE_REPLAY` in `runs.py`, `CONTEXT.md` §) | NOT VERIFIED as integrated | Files exist and the 9 provenance tests pass, but `cmd_serve` neither emits nor consumes the provenance — implementation without a caller. Must be integrated, not assumed done |

### 2. Newly discovered defects

**D1 — NS-3 backend never built (Case 1). Backend-not-built, not a stale path.**
`__main__.py:735` expects `extern/network_backend/ns-3/build/scratch/ns3.42-AstraSimNetwork-default`.
The target is legitimately declared (`ns-3/scratch/CMakeLists.txt:15-16`, `EXECNAME AstraSimNetwork`;
`ns3.42-*-default` is ns-3's scratch naming). But `build/scratch/` holds only
cmake scaffolding (Makefile, CMakeFiles, no binary) and no `ns3.42-AstraSimNetwork*`
exists anywhere under `third_party/`. Impact: every `ns3` serve fails at spawn.
Severity: medium. Blocks PR6: no (PR6 is BookSim) — but the missing preflight
(no existence/executability check before `Popen` at `:969`) is shared with all backends.

**D2 — No VeritX-side feasibility check (Case 2). Valid rejection, wrong layer.**
`memory_model.py:64-66` raises `RuntimeError` when per-rank weight exceeds NPU
memory — correct, keep it. Ordering: `Scheduler`/`MemoryModel` build at
`__main__.py:817-846`, *before* backend spawn (`:969`), so the child dies with a
traceback and VeritX reports only "exit code" (`cli.py:3091-3096`). All inputs to
an equivalent check (cluster JSON, model JSON, `calculate_sizes`/`get_weight`
pure math) are available without spawning. Impact: wasted spawns, unstructured
failure. Severity: low-medium. Blocks PR6 preflight: yes, as a checklist item.

**D3 — Replay-only is the default and VeritX's default serve selects it (Case 3a).**
`__main__.py:633` defaults `--booksim-replay-only=True`; `cli.py:2995-2997`
forwards `--no-booksim-replay-only` only under `--cycle-accurate`; the serve
parser defaults to `--network-backend booksim`. So a default `veritx serve` is
trace-duration replay (`Workload::issue` → `issue_replay`, `Workload.cc:241`)
while CLI copy ("full-stack", "cycle-accurate") implies simulation.
Severity: critical (scientific mislabeling). Blocks PR6 goldens: yes.

**D4 — `pp_stage_boundaries` discarded with exit 0 (Case 3b).**
`llm_converter.py:940-945` logs "ignored (converter predates PP support)" and
continues; the vendored converter has no PP partitioning logic anywhere else.
Upstream semantics (`trace_generator.py:1558-1590`) require block-boundary
partitioning with agreeing SEND/RECV sizes — dropping the boundaries hands every
rank the full unpartitioned graph (wrong compute, missing PP collectives).
With DP/TP/PP configs this makes the "successful" run scientifically void.
Severity: critical. Blocks PR6 for any `pp_size>1`; `pp_size==1` unaffected.
Installation trap: `chakra` resolves from site-packages, not the vendored tree —
editing the tree alone changes nothing until reinstall/`PYTHONPATH` override.

**D5 — `cmd_serve` equates exit 0 with success.**
`cli.py:3091-3092` prints "Simulation completed" on returncode 0 with no metric,
terminal-state, or provenance validation. Severity: high. Blocks PR6 by definition.

**D6 — Cycle-accurate e2e test proves too little.**
`test_serve_contract.py:221-237` asserts completion + ITL presence, not actual
fabric activity (no LEDGER/exposed-communication/fabric-stat assertion).
Severity: medium (test gap). Required closure in PR6 DoD.

**D7 — Spin-abort guardrail exists; must stay a backstop.**
`__main__.py:1034-1035,1776-1827`: WARNING at 200 idle rounds, abort at
`VERITX_SPIN_ABORT` (default 100000) with liveness snapshot attached and
nonzero exit. Acceptable as-is. Any proposal to "fix" a livelock by lowering
this threshold is a process violation, not a fix.

### 3. Required next tasks

**T1 — Serving preflight seam. Objective:** refuse before spawning, with named
reasons, when: backend binary missing/not-executable (per backend id, including
the ns-3 filename), model weight cannot fit NPU memory (mirror of
`get_weight`, never a replacement), converter lacks a load-bearing semantic the
workload needs (PP today), requested mode unsupported. Why now: Cases 1–3 are
all preflight failures arriving as expensive/confusing runtime failures.
Files: `dse/veritx_dse/cli/cli.py:cmd_serve`, new small preflight helper beside
`core/serving.py` (concrete, not a framework). Tests: missing binary → fail
without spawn; oversized model → refuse quoting GB numbers; PP config → refuse;
each <2 s. Acceptance: the three observed cases fail fast with the exact reason.
Non-goals: no generic validation framework; no serving behavior change.
Depends on: nothing. Size: M (memory-fit mirror must match `get_weight` exactly).

**T2 — PP fail-closed. Objective:** shim raises (`UNSUPPORTED_WORKLOAD_SEMANTIC`
with field/value/reason) instead of warning; update `METADATA.json` gap note;
reinstall chakra so it takes effect. Why now: precedent set by PR C; every PP
run today is void-but-green. Files: vendored `llm_converter.py:916-957`,
`METADATA.json`. Tests: PP header → raises nonzero; `pp_size==1` converts
unchanged. Acceptance: DP/TP/PP config fails before simulation. Non-goals: no
real PP converter implementation; no `--allow-lossy` flag unless research
explicitly needs degraded PP replay (then it must mark `DEGRADED` and be
golden-ineligible). Depends on: nothing; parallel with T1. Size: S.
Note: T2 does not block the livelock regressions — both historical configs are
PP-free (no `pp_size` key; verified in JSON).

**T3 — Execution-mode identity integration. Objective:** serve results carry
`{engine, network_backend, network_mode, semantic_losses}` (working-tree
`core/serving.py` integrated, not just present); replay latencies typed
`TRACE_REPLAY`; gate `passes_serving_golden_gate` enforced wherever goldens
are decided. Why now: D3/D4 stay dangerous until replay is unmistakable in data,
not just a stdout tagline. Files: `core/serving.py`, `core/runs.py`,
`cmd_serve` result emission. Tests: existing 9 + emission test (replay run's
result JSON shows `TRACE_REPLAY` + losses). Acceptance: no consumer can read a
replay result as simulation without ignoring a machine-checked field.
Non-goals: full serving metric vocabulary (next tranche). Depends on: T1
(supplies losses). Size: S.

**T4 — Liveness delta. Objective:** record the full logical last command
(known gap: bare-`pass` shape only) and pin the six-state classifier with
synthetic-observation unit tests. Why now: the probe already has all 10 fields;
this is the smallest change that makes "which state stopped changing first"
deterministic in every future hang. Files: `serving/core/liveness.py`,
one wiring line in `__main__.py`, `dse/tests/test_serving_liveness.py`.
Tests: classifier unit tests per state. Acceptance: each of the six stall
classes constructible and distinguishable in a test. Non-goals: no behavioral
change; no abort-threshold tuning. Depends on: nothing. Size: S.

**T5 — Historical-livelock baseline under probe. Objective:** run both
historical configs with liveness dump on, archive progress fingerprints +
per-instance retirement as baseline evidence. Why now: converts "passes" into
"passes for the documented reason, with a fingerprint to compare against".
Files: existing regression tests + run artifacts. Tests: existing two, plus
fingerprint capture. Acceptance: both green with all instances served and
fingerprints showing `USEFUL_PROGRESS` to terminal retire. If either hangs:
stop feature work, follow instrument→earliest-frozen-invariant→root-cause→fix→regression.
Non-goals: no network-path claims (both run replay-only — correct for a
scheduler-side invariant). Depends on: T2 (ordering safe — configs are PP-free).
Size: M (wall-clock dominated).

**T6 — Real-BookSim path proof. Objective:** tiny single-instance
`--cycle-accurate` run proving packets traversed the fabric (BookSim completion
stats / exposed-communication cycles / LEDGER activity), saved as an artifact
with the exact command. Why now: PR6's entire premise; D6 shows no test proves
this today. Files: `__main__.py` backend selection, `main.cc` interactive loop.
Tests: none yet — artifact first, test in T7. Acceptance: fabric-activity
evidence + cycles that move correctly vs the replay baseline. Non-goals: no
multi-instance, no metrics vocabulary. Depends on: T1, T2. Size: M.
Stop risk: see §7.

**T7 — PR6 slice. Objective:** `ExperimentSpec(mode=serving)` → immutable run →
owned LLMServingSim session (PR5 client) → structured per-request metrics +
provenance → single- and multi-instance tiny goldens asserting retirement,
terminal state, network activity, zero losses, units, binary identity, clean
shutdown, loud malformed-output failure, and replay-exclusion.
Depends on: T1–T6. Size: M–L.

### 4. PR6 gate

`NOT READY FOR PR6` — until ALL of:

- [ ] T1 preflight refuses the three observed cases fast with named reasons
- [ ] T2 PP shim fails closed (PP config exits nonzero pre-simulation)
- [ ] T3 provenance integrated: replay results machine-distinguishable
- [ ] T6 fabric-activity artifact exists for `--cycle-accurate`
- [ ] T5 fingerprints archived for both historical configs

### 5. PR6 Definition of Done

- [ ] `ExperimentSpec(mode=serving)` strict-parses; unknown fields rejected
- [ ] Single-instance tiny golden: all requests retire, terminal state validated
- [ ] Multi-instance tiny golden: every instance serves (per-instance assertion)
- [ ] Actual BookSim network activity proven in-test (fabric stats, not ITL presence)
- [ ] Zero semantic-loss warnings in golden runs; any loss fails the run
- [ ] Metrics carry units + producer + fidelity (`TRACE_REPLAY` vs serving-simulation)
- [ ] Backend binary SHA256 in provenance; clean child shutdown asserted (no orphans)
- [ ] Malformed/partial backend output fails loudly (no partial-stats acceptance)
- [ ] Replay-only run provably fails the real-BookSim golden (negative test, green)

### 6. Tasks immediately after PR6

Evaluated against live code; the candidate order survives with two adjustments:
metric semantics must come first (goldens emit numbers needing meaning), and the
compression review must precede ComparisonSpec (nothing to enforce comparison
over until the review fixes what a "result" is).

1. **Serving metric semantics** — pin `sim_clock`/TTFT/TPOT/completion/latency/
   backend-time/wall-time vocabulary on the PR E typed seam; forbid
   clock↔cycle conversion without a proven equivalence.
2. **LLMServingSim → analytical slice** — separate concrete slice reusing
   serving semantics; encode 1-D vs N-dim backend selection explicitly (the
   unaware fallback already prints; make it data); one tiny golden per frontend.
3. **Semantic-compression review** — three real paths exist by now; extract
   only repeated mechanics (init/finalize, ownership, artifacts, metrics,
   diagnostics). No `BackendFactory`/registries; leave unshared parts concrete.
4. **ComparisonSpec enforcement** — turn the `pipeline.py` warning into a gate:
   nodes, workload hash, packetization, routing artifact, VC config,
   simulator/fidelity, seed policy; failures stay visible with stats.
5. **Canonical workload representation** — promote the lowering manifest to
   preserve phases/collectives/participants/sizes/deps; conservation-checked.
6. **RouteArtifact / routing truth** — content-addressed exact next-hop behavior;
   certifier, BookSim path, and (later) RTL all reference its hash.
7. **RTL regression + equivalence investigation** — automated 4×4/8×8 Verilator
   delivery/conservation/ordering/no-stall/route-table checks; BookSim↔RTL
   correlation as separate contracts (zero-load, pre-knee, saturation,
   post-knee) — no premature cycle-equality demand.
8. **Formal proof execution, then requirements-driven synthesis, then remaining
   migration, then Studio v0** — in that order; each is a separate milestone
   with its own gate, not part of this sequence.

### 7. Stop conditions

Stop the roadmap and re-review architecture if any of these is discovered:

- No working LLMServingSim → real-BookSim serving path exists (T6 fails) —
  PR6 becomes "implement the backend path", not "integration glue".
- PP semantics fundamentally conflict with the converter representation (i.e.
  T2's refusal cannot be lifted by a bounded converter fix).
- Multi-instance completions cannot be correctly rebound to owning instances
  (the sys-attribution invariant breaks under a real fabric).
- Analytical frontends require incompatible serving semantics (one serving
  loop cannot serve both without silent fallback).
- Routing semantics cannot be reconciled (executed routes ≠ certifiable routes
  beyond the current stopgap).
- A "fix" for any hang consists of lowering a timeout/round threshold.
- Any result with discarded semantics is proposed for goldens, certification,
  ranking, or comparison.

### 8. Evidence appendix

**Suite:** `python3 -m pytest tracks/t3-topology/dse/tests -q` → 971 passed,
1 skipped, 159 s. Integrity subset re-run (env, pareto, routing-stopgap,
metrics, protocol, liveness): 115 passed.

**Preflight/execution (A–C):**
`dse/veritx_dse/cli/cli.py:2931-3101` (`_locate_serve_path`, `_build_serve_cmd`,
`cmd_serve`); `serving/__main__.py:633-636` (replay default), `:694-743`
(backend/binary selection), `:944-960` (replay injection into system.json),
`:1906-1912` (taglines); `astra-sim/system/Sys.cc:424-431` (flag parse);
`astra-sim/workload/Workload.cc:225-270` (`issue_replay` branch);
`serving/core/memory_model.py:29-89,157-205` (fit check + weight math);
`serving/core/config_builder.py:56-130` (TP/PP/EP validation);
`extern/graph_frontend/chakra/src/converter/llm_converter.py:916-957` (shim);
`serving/core/trace_generator.py:1558-1590` (boundary semantics);
`serving/core/graph_generator.py:138-187` (conversion call chain);
`serving/core/utils.py:35-45` (workload path strings);
`network_frontend/booksim2/main.cc:224-349` (interactive loop, bare-path,
`load`, `done`, `Waiting` discipline); `serving/core/controller.py:1-130`
(terminator rule, completion regexes).

**Liveness (D):** `serving/core/liveness.py:1-200` (fields, states, report);
`__main__.py:1034-1086,1140-1142,1334,1748-1830` (`_vprog_*`, idle WARN/ERROR,
spin-abort with snapshot); `dse/tests/test_serving_liveness.py` (400 lines).

**Livelock (E):** `docs/ROOT-CAUSE-multi-instance-livelock.md` (read as
hypothesis); `dse/tests/test_full_pipeline.py:553-635` (assertions +
replay-only mode noted); cluster JSONs
`single_node_moe_dp_ep_instance.json` / `single_node_4_instance_2TP.json`
(both PP-free); `dse/tests/fake_serving_backend.py:23,150-175`.

**PR6 surface (F):** `dse/veritx_dse/core/spec.py:61-66` (mode field),
`core/experiment.py` (Slice A only), `core/runs.py:153-187` (+ uncommitted
`TRACE_REPLAY`), `dse/tests/test_serve_contract.py:179-237` (cycle-accurate
assertions gap), `dse/tests/test_serving_provenance.py` + `core/serving.py`
(uncommitted, unintegrated).

**NS-3 (Case 1):** `ns-3/scratch/CMakeLists.txt:15-16`; `build/scratch/`
listing (scaffolding only); filesystem-wide absence of `ns3.42-AstraSimNetwork*`.

**Runtime artifacts observed:** `AstraSim_BookSim2` + `.real` present and
executed by the live regression tests in this run; ns-3 binary absent as stated.
