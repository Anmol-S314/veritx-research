# HANDOFF 2026-09-17 — PR 5: LLMServingSim backend protocol fixture (complete)

**Branch:** `epic/booksim-forward-port` · working tree (uncommitted, per review decision)
**Suite:** `941 passed, 1 skipped` (`python3 -m pytest dse/tests -q`, 2:14) — up from 911/1 (A–E) and 869/1 (session start).
**Scope discipline:** PR 5 ONLY. No PR 6, no Session/Backend/Provider hierarchy, no routing/RTL/Studio/DSE changes. One pre-PR5 item from your review (BROADCAST → PROVISIONAL) is included and listed separately below.

---

## 1. Files changed

| File | What |
|---|---|
| `dse/veritx_dse/simulation/llmserving_protocol.py` (**new**) | The concrete protocol client: `ServingBackendSession` (start / `read_startup` / `command` / `close`), `BackendReply`, `ProtocolError`. LLMServingSim-specific by design — the module docstring records that no generic session abstraction may be extracted until a second real interactive system exists (§4.2, §7). |
| `dse/tests/fake_serving_backend.py` (**new**) | Real subprocess fixture: one script, 17 deterministic modes, speaks the traced wire format over real pipes; observable state via `FAKE_BACKEND_STATE` JSON file (atomic writes) so tests assert multi-command state without parsing protocol lines. |
| `dse/tests/test_serving_protocol.py` (**new, 30 tests**) | Sequencing pins, protocol violations, livelock shape, no-orphan guarantee, session discipline. Zero subprocess mocks (§26 Level 3). |
| `docs/protocols/llmservingsim-backend.md` (**new**) | The source-traced protocol facts (every claim cites file:line). |
| `dse/veritx_dse/simulation/model_to_trace.py` (pre-PR5 review item) | BROADCAST lowering marked **PROVISIONAL**: docstring note, decomposer docstring, and `lowering_manifest["provisional_semantics"]` when a BROADCAST class lowers. Tests unchanged and green (50/50). |

## 2. Protocol facts verified from source (highlights; full list in the protocol doc)

1. **Framing**: text, line-based. Command = `<payload>\n` + flush (`controller.py:63-66`). Reply = zero+ lines, then a terminator line **containing** `Waiting` as a substring — or the exact legacy `Checking Non-Exited Systems ...` (`controller.py:39`).
2. **Startup is unsolicited**: the backend runs the argv event-handler round and emits one completion burst + first `Waiting` with no command sent (`booksim2/main.cc:225-262`; same in both analytical frontends).
3. **One command outstanding, always**: the serving loop runs `read_wait` at the top of each round before any write (`serving/__main__.py:1074`).
4. **Commands**: bare `<workload path>` (legacy round — what the frontend ACTUALLY sends, `utils.py:35-48` + `__main__.py:1559`), `pass`, `pass <t>`, `pass -1`, `done`, `exit`. `load`/`run` exist **backend-side only** (queued loads applied on `run`, `main.cc:345-365`); `load` gets a silent ack (no reply).
5. **`Waiting` meaning**: round quiescence + clock report; idle-await-next-command. NOT "done". A backend may reply with **no** time advance (`done` → Waiting-only, `main.cc:336-343`) — the exact no-progress shape behind the livelock class.
6. **Simulated time**: backend owns the clock; the frontend jumps it only via `pass <t>` when next arrival > current (`__main__.py:1747-1751`). Clock reaches the frontend through the trailing `finished, <c> cycles` field.
7. **Completion grammar** (both accepted, `controller.py:13-27`): `sys[i] iteration n finished, c cycles, exposed communication e cycles.` and `[workload]( [info])? sys[i] finished, c cycles, exposed communication e cycles.` — one line per NPU per round, plus an optional `[plat]` summary line (BookSim only).
8. **EOF**: with work remaining → fail-loud, stderr tail dump, non-zero exit (`__main__.py:1076-1093`); post-completion EOF → clean shutdown. `check_end`'s `All Request Has Been Exited` / `ERROR: Some Requests Remain` strings exist in **no vendored binary** (exhaustive grep over both `third_party/astra-sim` trees) — on our binaries `check_end` always ends at EOF. Same for the `Checking Non-Exited Systems ...` terminator: legacy-accepted, never produced.
9. **Flush**: both ends flush per message; the forward-port added a stderr drain thread because an undrained stderr pipe stalled runs at ~round 1500 (`__main__.py:968-977`) — the client reproduces this drain.
10. **Binary selection** (`serving/__main__.py:689-733`): `booksim` → `AstraSim_BookSim2`; `analytical` 1-dim → congestion-**aware** `AnalyticalAstra`; `analytical` multi-dim → **silently swapped** to congestion-**unaware** `AnalyticalAstraUnaware`.

## 3. Protocol differences between backends (your warning was correct)

| | BookSim2 | analytical congestion-aware | analytical congestion-unaware |
|---|---|---|---|
| `pass [t]` / `exit` / `done` | yes | yes | yes |
| `load`/`run` queuing | yes | yes | **NO — any non-pass line is treated as a literal workload path** (`congestion_unaware/main.cc:140-147`); a `load X` line would attempt to load a file literally named `X` after a `load ` prefix check that doesn't exist |
| `[plat]` line | yes | no | no |
| reply grammar | `[workload]` per NPU | identical | identical (exposed always 0) |
| reached via | `--network-backend booksim` | `--network-backend analytical` (1-dim) | `--network-backend analytical` (multi-dim, silent swap) |

Consequence recorded in the protocol doc (§10.1): if serving ever switches
from legacy bare-path rounds to `load`/`run`, the unaware path breaks
**silently**. The client's `expect_reply=False` encoding of `load` is valid
only against the two queuing frontends; the unaware frontend requires the
legacy bare-path form. PR 7 must select the command form per binary.

## 4. The fixture: 17 modes

`normal`, `startup_hang`, `startup_eof`, `startup_exit_nonzero`,
`stderr_flood` (background thread — main loop stays protocol-responsive),
`waiting_without_progress` (THE livelock shape: Waiting forever, clock
frozen, zero completions), `delayed_waiting`, `multi_line_bursts`,
`missing_waiting`, `partial_line` (`Waiting` without newline — not a
terminator), `protocol_garbage`, `legacy_checking`, `eof_before_waiting`,
`crash_after_cmd` (exit 7), `ignore_exit` (answers normally, never exits —
must be TERM→KILLed).

## 5. What the client enforces (deliberately stricter than the frontend, per your review)

- EOF with a reply expected → `ProtocolError` (never a silent empty reply).
- Missing terminator within timeout → `ProtocolError` **and the child's
  process group is TERM→KILLed** — no stall can leak.
- Malformed framing never silently continues with a stale clock (the
  frontend's real robustness gap, documented, not reproduced).
- stderr drained by a bounded daemon thread; error objects carry
  `burst_tail` + `stderr_tail` (§28: diagnose, don't just time out).
- `select()`-based deadline line reading on a **binary** stdout — a blocking
  `readline()` cannot enforce a timeout, and text-mode buffering breaks
  fd readiness (this was a real design iteration during the session).
- Substring terminator rule reproduced exactly, with a test pinning it.

## 6. Test results

- Protocol suite: **30 passed** (~18 s, real processes throughout).
- Full suite: **941 passed, 1 skipped** — no prior seam broken.
- No-orphan verification: every teardown path asserted from outside via
  `kill(pid, 0)` (5 s deadline) — clean close, protocol-error path,
  `ignore_exit` escalation, `force` kill. No `fake_serving_backend`
  processes survive the suite (checked post-run).
- No new repo litter: the fixture writes only under `tmp_path`
  (`FAKE_BACKEND_STATE`); post-suite check found no new `log/` spew.
  (`dse/log/err.log`, `dse/log/log.log` are the known pre-existing legacy
  residue, untouched by PR 5.)

## 7. Unresolved semantics (for §34 / your review)

1. **Unaware-frontend command form** (§3 above): bare-path-only confirmed
   from source, but the *intended* multi-instance contract on that binary
   is a product question, not a source question.
2. **`run` with an empty load queue** is legal backend-side (re-report
   round, `main.cc:350` comment "empty set = re-report only"); no serving
   caller found — accidental surface?
3. **The `[workload] [info]` regex variant** (`controller.py:19`) implies
   some build prefixes logging markers on the completion line; which build
   does that is untraced (regex accepts both; fixture covers both).
4. **`parse_output`'s "pick sys 0" rule** (BookSim forward-port, 
   `controller.py:122-131`) is single-instance-shaped; multi-instance
   rebinding lives in the serving loop, not the controller — the client
   exposes `BackendReply.lines` raw so PR 6/7 don't inherit that bias.

## 8. Next dependency (your step 4 — liveness observability)

The fixture's `waiting_without_progress` mode now reproduces the multi-
instance livelock class deterministically in ~milliseconds with no
BookSim/ASTRA binaries. The instrumentation target is the serving loop's
round body (`serving/__main__.py:1099-1204` parse block + `1740-1801`
pass block), where the existing `_vprog_*` counters
(`__main__.py:1044-1050`) already track clock-advance/retire/dispatch —
the next change computes your progress fingerprint
`(sim_time, retired, pending, inflight_batches, backend_completions)` per
round and surfaces `NO_USEFUL_PROGRESS` with the component values, per
your spec. The client-side evidence needed for it (per-reply cycle,
completion count, identical-reply detection) is now asserted machinery
(`TestWaitingWithoutProgress`), not guesswork.

**Stopping here as instructed.** PR 6 (serving → BookSim) not started.
