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

---

## F-0003 — collective completion is injection-schedule-bound

**Status:** SUPPORTED BY INTERVENTION (low-pressure regime only);
network claim quarantined by F-0004
**Severity:** medium — limits what `completion_cycles` can rank
**Found:** 2026-09-24, during experiments V09/V10; intervention added
in the adversarial-hardening pass

### What it is

The canonical trace projection assigns timestamps `0, 1, 2, ...` — one
packet per cycle in emission order (`backend/booksim_projection.py`
`trace_schedule`, documented as projection-defined emission order, not
application wall-clock).

**Claim, stated precisely:** under the tested low-pressure injection
schedules, the completion follows the injection horizon with a small
drain term. This is NOT a claim that "ALLREDUCE is injection-bound":
(a) the current ALLREDUCE traffic graph is not a ring (F-0004), (b) the
intervention can only make injection slower, never exceed one packet per
cycle, and (c) the `max(50, 5%)` support threshold is a chosen
heuristic, not an independently justified physical boundary. Rerun after
F-0004 is resolved.

### Intervention (not correlation)

Same packets, topology, routing and packet sizes; only the injection
schedule changes (`validation/harness/intervention.py`, run on the
authority engine — the same BookSim the canonical path uses):

```text
schedule       spacing   horizon   completion   drain
per_cycle            1       959          990      31
half_rate            2      1918         1942      24
quarter_rate         4      3836         3855      19
eighth_rate          8      7672         7687      15
```

Over an 8x horizon range the completion tracks the horizon: the drain
beyond injection is 15–31 cycles (0.2–3.2% of the horizon) and does not
grow with load. That supports the injection-bound hypothesis: completion
is the injection horizon plus a small, load-independent drain.

### Scope and limit

All measured schedules are at or below the projection's maximum injection
rate (1 packet/cycle). The departure regime — where completion stops
tracking the horizon because the network saturates — is not expressible
in the current trace model, which cannot inject faster than one packet
per cycle. Demonstrating departure needs a sub-cycle / burst injection
model. Until then F-0003 is supported only for the low-pressure regime.

### Consequence

For workloads below the injection rate, `Optimizer`'s
`completion_cycles` objective ranks candidates largely by packet count
(which depends on packetisation) rather than by network contention.
`workload_lowering_conservation` independently validates the packet
count via the ring oracle, so at least that part is a checked quantity.

---

## F-0004 — the collective labelled `RING` is a complete directed exchange, not a ring

**Status:** OPEN — HIGH (network-performance claims quarantined)
**Severity:** high — invalidates the topology traffic of every ALLREDUCE
network claim until resolved
**Found:** 2026-09-24, by external audit of `1a6e4761`

### What is wrong

Production declares the ALLREDUCE algorithm as `RING`
(`workload/messages.py` `SCHEDULES`, `workload/operations.py`), but
`_collective_triples()` builds a complete directed exchange:

```python
for step in range(ref["steps"]):        # 2(k-1) steps
    off = step % (k - 1) + 1            # offsets 1..k-1, cycling
    for i in range(k):
        triples.append((step, i, (i + off) % k))
```

A ring reduce-scatter/all-gather moves data only between logical
neighbours `i -> (i+1) mod k`, with the chunk ownership rotating. The
offset scheme above sends every rank to every other rank, so the
communication graph is not a ring.

### Measured

```text
V09 k=4 : 12 distinct directed pairs (all pairs), only 4 are ring
          neighbours; 8 non-neighbour pairs; each pair used twice
V02 k=16: 240 distinct directed pairs, only 16 are ring neighbours;
          224 non-neighbour pairs
```

The counts are identical to a ring (`2(k-1)` steps, `2k(k-1)` messages,
`2(k-1)B` bytes) — which is exactly why the count oracle agreed. On a
4x4 row-major mesh the two graphs have very different hop distributions
(ring: neighbour links only; this: all-pairs, ~2.667 mean Manhattan vs
~1.875 for a logical ring), hence different link utilisation, hotspots,
contention and completion.

### Why B4 missed it

`validation/harness/oracle.py` validated message count, total bytes,
packet count and flit count, but never `(step, src, dst)`. Worse, the
existing `verification/reference_semantics.py::ref_collective_messages()`
uses the same offset scheme, so calling either "independent" would have
been circular. The corpus now adds `collective_graph_conformance`
(ring-neighbour pair multiset, no `veritx_dse` import), which fails on
the current lowering.

### Consequence

Network-performance claims are **withdrawn/quarantined** for V02, V04,
V09, V10 and F-0003. Their conservation/count/oracle checks remain
valid and useful.

### Resolution (product decision, not a harness change)

- **A. RING means ring.** Change the schedule so each rank communicates
  with its fixed logical neighbour per step and track the rotating chunk
  separately.
- **B. The exchange schedule is intentional.** Stop calling it `RING`;
  give it an accurate identity (e.g. a direct permutation exchange) so
  its topology sensitivity is not read as ring ALLREDUCE.

Rerun V02/V04/V09/V10 and the F-0003 intervention after either choice.
