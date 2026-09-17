# LLMServingSim ↔ backend protocol — source-traced facts (PR 5)

Every claim below cites a vendored source location; nothing is inferred from
handoffs or comments. Traced 2026-09-17 against HEAD `fa71db29` (PR 5).

## 1. Frontend (LLMServingSim serving loop)

Session owner / spawn: `third_party/llmservingsim/serving/__main__.py:963`
```
p = subprocess.Popen(astra_args, stdin=PIPE, stdout=PIPE,
                     stderr=PIPE-or-file, universal_newlines=True)
```
- text mode (universal_newlines), line-oriented.
- stderr is drained by a background thread (`__main__.py:979`, added by the
  VeriTX forward-port) so a chatty backend can never fill the pipe and
  deadlock the run; panic/error lines are forwarded.
- Backend selection (`__main__.py:689-733`):
  | `--network-backend` | binary |
  |---|---|
  | `analytical` (1-dim) | `<astra>/astra-sim/build/astra_analytical/build/AnalyticalAstra/bin/AnalyticalAstra` (congestion-**aware**) |
  | `analytical` (multi-dim) | silently swapped to `build/astra_analytical_unaware/build/bin/AnalyticalAstraUnaware` (congestion-**unaware**) |
  | `booksim` | `network_frontend/booksim2/bin/AstraSim_BookSim2` (forward-ported) |
  | `ns3` | `extern/network_backend/ns-3/build/scratch/ns3.42-AstraSimNetwork-default` |

- The initial event-handler round is **implicit**: before any command, the
  frontend pre-generates `event_handler` and passes its path as
  `--workload-configuration` (`__main__.py:919-941`); the backend runs it
  during startup and emits its burst + first `Waiting` unsolicited.

### Commands the frontend writes (one per round, `write_flush` = write + `\n` + flush, `controller.py:63-66`)

| Command | Meaning | Source |
|---|---|---|
| `<workload path>` | legacy round: load this path into ALL systems, fire, run to quiescence, reply | `__main__.py:1559,1586` via `get_workload()` (`core/utils.py:35-48` — returns a bare path, never `load ...`) |
| `pass` | idle poll; no-op round | `__main__.py:154,1580` |
| `pass <t>` | idle poll + advance backend clock to future arrival `t` (non-idempotent variant) | `__main__.py:155` |
| `pass -1` | state-changing pass (DP barrier join / claim hand-back); re-opens re-asks | `__main__.py:151,1442` |
| `done` | ONE instance finished (NOT global exit); backend must reply | `__main__.py:1736` |
| `exit` | shutdown; loop breaks, then `check_end` | `__main__.py:1731,1792` |

Ordering: no command is written until the previous reply was consumed —
`read_wait` runs at the top of the round loop (`__main__.py:1074`) before any
`write_flush`. **Exactly one command may be outstanding.** Multiple `load`
lines before a `run` are legal only on the backend side (queued); the
frontend itself never does this — it emits the legacy bare-path form.

### Reply consumption (`controller.py:30-48`)
```
read_wait: readline() until the LAST line contains "Waiting"
           (substring, not exact-match) OR equals
           "Checking Non-Exited Systems ..."; EOF => break (fail-loud upstream).
```
- Reply = zero or more arbitrary lines, then a terminator line containing
  `Waiting` (anywhere in the line) or the exact legacy `Checking` line.
- `parse_output` consumes the JOINED burst (`__main__.py:1101-1108` for
  booksim/analytical; `out[-2]` for ns3 — different path, not in scope).

### Completion grammar (controller.py:13-27)
Two accepted forms per NPU:
```
sys[<i>] iteration <n> finished, <c> cycles, exposed communication <e> cycles.
[workload](\s+\[info\])?\s+sys[<i>] finished, <c> cycles, exposed communication <e> cycles.
```
BookSim and both analytical frontends emit the `[workload]` form once per
NPU per round (`booksim2/main.cc:478-485`; `congestion_aware/main.cc:38-45`).
`cycle` is the cumulative event-queue wall clock — the frontend's monotonic
`current` comes from it; `exposed` is per-round non-overlapped comm.

### Simulated-time ownership
The BACKEND owns the clock. The frontend only jumps time via `pass <t>` with
`next_arrival > current` (`__main__.py:1747-1751`); every reply's cycle field
resets the frontend clock. A backend can reply without advancing time
(`pass` echo, `done`) — that is exactly the no-progress shape the spin
detector counts.

### Shutdown (`__main__.py:1812` + `controller.py:50-61`)
`check_end` reads until the previous-previous line is
`All Request Has Been Exited\n` or `ERROR: Some Requests Remain\n` — **or
EOF** (VeriXT break). Neither string exists in any vendored binary (verified
by exhaustive grep over both `third_party/astra-sim` trees), so on our
binaries `check_end` always ends at EOF after `exit`+process death.

## 2. BookSim2 frontend backend (`network_frontend/booksim2/main.cc:301-487`)

Interactive loop, per line (trimmed; empty = no-op round):
| Line | Behavior | Reply |
|---|---|---|
| `pass` / `pass <t>` | advance clock to `t` if > current (run_cycles or jump); pure time-advance, exposed=0 | one `[workload]` line per NPU (cumulative cycle, exposed 0) + `Waiting` |
| `exit` | break → process exits 0 | none (EOF follows) |
| `done` | no-op round; **must** echo `Waiting` (`main.cc:336-343` comment: serving read_waits BEFORE its next command) | `Waiting` only |
| `load <p>` (repeatable) | queue paths; applied on `run` to systems whose `<p>.<rank>.et` exists | none (silent ack) |
| `run` | apply queued loads, fire, run to quiescence | `[plat] ...` summary + one `[workload]` per NPU + `Waiting` |
| `<path>` (anything else) | legacy: clear queue, single load, fire | same as `run` |

Startup: runs the argv workload synchronously, then emits one `[workload]`
per NPU + first `Waiting` (`main.cc:225-262`) — unsolicited.

## 3. Analytical congestion-aware (`analytical/congestion_aware/main.cc:126-225`)

- Startup: same implicit event-handler round + burst + `Waiting`
  (`main.cc:139-147`), in BookSim's `[workload]` wire format.
- Interactive: identical command set to BookSim **including `load`/`run`
  queuing** (`main.cc:174-196`), except no `[plat]` line.
- `done` echoes `Waiting`; `exit` breaks.

## 4. Analytical congestion-unaware (`analytical/congestion_unaware/main.cc:106-149`)

**Protocol differs from the other two:**
- Interactive loop handles `pass [t]` / `exit` / `done` only. There is **no
  `load`/`run` branch**: any non-pass/exit/done line — including a literal
  `load <path>` — falls through to the legacy single-load round
  (`main.cc:140-147`). A path beginning with "load " would be treated as a
  filename.
- Reply grammar is the same `[workload] ... Waiting` wire format
  (`emit_workload_results`, `main.cc:31-42`), exposed always 0
  (no congestion accounting).
- This binary is reached silently whenever `--network-backend analytical`
  is combined with a multi-dim network (`serving/__main__.py:703-724`).

## 5. `Waiting` semantics

`Waiting` (as a bare line from all three frontends) means: **round complete,
backend idle, clock is at the reported cycle; awaiting the next command.**
It is NOT "done", NOT "no events before time t". It is emitted exactly once
per reply, always as the last line, always flushed
(`std::endl` / explicit flush). `pass -1`/`pass <t>` answers carry the same
meaning plus clock evidence.

## 6. Flush behavior

Frontend→backend: `stdin.write(s + '\n'); stdin.flush()` per command
(`controller.py:63-66`). Backend→frontend: every reply ends with
`std::endl` on `std::cout`. The frontend's stderr drain thread exists
because stdout alone was not the deadlock risk — an undrained stderr pipe
was (filling at ~round 1500, `__main__.py:968-977`).

## 7. EOF / crash / malformed (frontend behavior, for our client to match)

- EOF from backend stdout with work remaining → fail-loud: error print,
  stderr tail dump, non-zero exit, inputs kept (`__main__.py:1076-1093`).
- EOF after all requests retired → clean shutdown path.
- A malformed reply simply doesn't parse → `out_dict is None` → the round
  proceeds with stale clock; no framing error is raised today (a real
  robustness gap our client must NOT reproduce silently).

## 8. Legacy-terminator caveat

`read_wait` also accepts exactly `"Checking Non-Exited Systems ...\n"` and
`check_end` waits for `"All Request Has Been Exited\n"` /
`"ERROR: Some Requests Remain\n"` — but **no vendored binary emits any of
these strings** (exhaustive grep over `third_party/astra-sim` and
`third_party/llmservingsim/astra-sim` sources: zero matches). They are
compatibility relics of the original upstream AstraSim backend. The fake
fixture therefore treats them as legacy-accepted but never produces them,
and tests never rely on them.

## 9. Resolved handoff questions (§34 mapping)

| Q | Answer | Source |
|---|---|---|
| exact framing | line-based text; cmd = `<payload>\n` + flush | controller.py:63 |
| reply terminator | last line contains `Waiting` (substring) or legacy Checking line | controller.py:39 |
| `Waiting` meaning | round quiescence + clock report; idle-await-next-cmd | main.cc:336-343, 261 |
| multiple records per reply | yes — one `[workload]` line per NPU (+ optional `[plat]`) | main.cc:478-485 |
| stdout vs stderr | protocol+results on stdout; logs/ledger on stderr | main.cc:324, __main__.py:979 |
| outstanding commands | strictly one; read_wait precedes every write | __main__.py:1074 |
| time ownership | backend owns; frontend jumps via `pass <t>` | __main__.py:1747 |
| load/run ordering | load queues (backend-side only), run fires; frontend uses bare-path legacy form | main.cc:345-365 |
| reply without time advance | yes (pass echo, done) — the livelock shape | main.cc:336-343 |
| EOF semantics | fail-loud with work remaining; clean otherwise | __main__.py:1076 |
| flush | both ends flush per message | controller.py:66, std::endl |

## 10. Frozen contract decisions (post-PR5 review, 2026-09-17)

1. **The legacy bare-workload-path command IS the serving contract.** Do
   not migrate serving to `load`/`run`: the congestion-unaware analytical
   frontend would silently interpret a `load <path>` line as a literal
   filename (§4). Any future multi-instance redesign must either teach the
   unaware frontend the queuing protocol or keep bare-path rounds.
2. **Empty-queue `run` is NOT a supported semantic.** The backend accepts
   it (re-report round); no serving flow may rely on it. It remains
   fixture-only surface.
3. **PR6 must not inherit `parse_output`'s "pick sys 0" shortcut**
   (`controller.py:122-131`) — it is single-instance-shaped. Multi-instance
   completion→instance attribution must use the full per-NPU burst
   (`parse_all_completions`) or a new explicit rule.

## 11. Still unresolved (new questions raised by this trace)

1. **Unaware-frontend protocol gap**: since the unaware binary accepts no
   `load`, is the intended multi-instance serving contract "bare paths
   only"? If a future serving change ever emits `load`, the unaware path
   breaks silently — worth a guard or a protocol version.
2. The `[info]` variant in the completion regex suggests some binaries log
   through a formatter that prefixes `[workload] [info]` — which build
   does that? (Regex accepts both; fixture covers both.)
3. `run` with an empty load queue is legal (re-report round). Is any
   frontend flow relying on re-report semantics, or is it accidental
   surface? (Fixture supports it; no serving caller found.)
