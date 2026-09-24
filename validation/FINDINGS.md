# VERITX Validation Findings

Durable ledger of defects and disagreements found by the independent
validation campaign. A finding here is a *measured* claim with
reproduction steps, not an opinion. Findings are append-only; a finding
is closed only by a fix that is itself re-validated by the corpus.

Status values: `OPEN`, `FIXED` (fix landed, corpus re-validates),
`ACCEPTED` (known, documented disagreement with reason).

---

## F-0001 — `completion_cycles` was a sampling-window artifact, not physics

**Status:** FIXED (validation/b4-corpus, pending full-corpus re-validation)
**Severity:** critical — invalidated the optimizer objective and every
trace-run timing claim
**Found:** 2026-09-24, while grounding experiment V01

### What was wrong

The canonical BookSim parser read the completion metric from the fork's
`Time taken is N cycles` line:

- `backend/booksim_execution.py` `_TIME_RE = r"Time taken is (\d+) cycles"`
  (pre-fix) → `stats["completion_cycles"]`.

But `Time taken is` prints the simulated *sampling window* `_time`, which
is set by `sample_period × max_samples` — a function of trace length, not
of network behaviour. The fork already prints the physically meaningful
metric on the very next line:

- `third_party/booksim2/src/trafficmanager.cpp:1924` → `Time taken is`
  (window)
- `third_party/booksim2/src/trafficmanager.cpp:1926` → `Completion time
  is _last_ejection_time` (cycle of the last ejected flit)
- `:1745` resets `_last_ejection_time` per sim; `:1344` advances it on
  ejection.

The canonical parser never read `Completion time is`; no regex in
`backend/` referenced it.

### Reproduction

Same fabric (native 4×4 mesh DOR), same trace (960 packets), only the
sampling window varied:

```text
sample_period=1960 max_samples=1  -> Time taken 1960  Completion 990
sample_period= 500 max_samples=10 -> Time taken 3001  Completion 990
sample_period= 100 max_samples=30 -> Time taken 2901  Completion 990
sample_period=5000 max_samples=1  -> Time taken 5000  Completion 990
```

`Time taken` moves with the window; `Completion time` is invariant.
Through the canonical path, `execute_prepared_booksim` reported
`completion_cycles = time taken` (e.g. 1960), i.e. the window.

### Impact

- `cli/commands_optimize.py:130` sets the optimizer objective to
  `Objective("completion_cycles", "MIN")`: candidates were ranked by trace
  length / formatting, not by network latency.
- `application/fabric_evaluator.py:705` and
  `performance/network.py:207` propagate the same value into
  `network_traffic_window.window_cycles` and any bound wall time.
- The seal report's §26 claim of a "real 1216 vs 1120 cycles
  differentiation" is **not** a network-performance result and is
  retracted by this finding.

### Fix

- New required parser evidence: `Completion time is N cycles` →
  `stats["completion_cycles"]` (last-ejected-flit cycle).
- `Time taken is N cycles` is retained as the diagnostic
  `stats["sample_window_cycles"]`; it is never latency.
- Fail closed if `completion_cycles > sample_window_cycles`.
- `PARSER_VERSION` bumped `v1 → v2`; v1 evidence is deliberately not
  reusable under v2 (it recorded a window-dependent value).

### Post-fix sanity (link-width monotonicity, 16-node ALLREDUCE)

```text
  lw  packets  window  completion  latency
  32     1920    2920        1962   53.38
  64      960    1960         990   32.63
 128      480    1480         507   26.22
 256      480    1480         505   22.84
```

Wider link is not slower; the metric now moves with physics rather than
with packet count.

### Regression coverage

`tests/test_backend_booksim_execution.py`: window-invariance,
completion-after-window refusal, window-only refusal, and the real
native-mesh / AnyNet execution gates.

---

## F-0002 — BookSim `Hops average` is router hops + 1 (ejection counted)

**Status:** ACCEPTED (known definitional difference, not a defect)
**Severity:** low — a reporting-basis difference, not a routing error
**Found:** 2026-09-24, during experiment V01

### What it is

BookSim increments `Flit::hops` once per router traversal, including the
traversal that ejects the flit at the destination
(`third_party/booksim2/src/routers/iq_router.cpp`, the
`f->hops++` in the input-to-output scheduling path). Its reported
`Hops average` is therefore the **router-to-router** hop count plus one.
VERITX's canonical route artifact counts router-to-router hops.

### Evidence (2x2 mesh, single 1-flit packet from router 0)

```text
0 -> 1 : Manhattan 1, BookSim Hops average 2
0 -> 2 : Manhattan 1, BookSim Hops average 2
0 -> 3 : Manhattan 2, BookSim Hops average 3
```

### Handling

The corpus `hand_route` check pins the exact relationship
`authority_hops == hand_router_hops + 1` and documents the cause, rather
than demanding equality (which would be wrong) or ignoring the statistic
(which would hide a real routing error). No VERITX product claim consumes
BookSim's `Hops average`, so no product value is affected.
