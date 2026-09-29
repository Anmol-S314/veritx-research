# `performance` — extracted module rationale

Extracted from the module docstrings of `veritx_dse/{name}` by the 2026-09-29 debloat. Code keeps a one-line pointer; this is the original long-form text.

## `tracks/t3-topology/dse/veritx_dse/performance/__init__.py`

```text
veritx_dse.performance — system-performance semantics (§9/§111).

Small, boring modules over exact rational time (clocks live in
veritx_dse.core.time):

    model        PerformanceModel (immutable, content-addressed)
    workload     temporal overlay: events, requests, graph laws
    scheduler    deterministic discrete-event schedule (the ONE scheduler)
    network      BookSim evidence → BARRIER network window (§36–§42)
    metrics      critical path / utilization / request latencies
    sensitivity  counterfactual bottleneck evidence (§48–§51)
    result       PerformanceEventGraph + verified performance result (§65/§66)

Compute/memory calibration: UNCALIBRATED (no dataset in repo, §11 of
the contract). Analytical models stay labeled; no synthetic data.
```

## `tracks/t3-topology/dse/veritx_dse/performance/metrics.py`

```text
veritx_dse.performance.metrics — re-derived metrics from a schedule (§45/§46).

Every metric here is computed FROM a verified ``Schedule`` — never
trusted from a persisted summary (§74). Definitions:

- makespan: max(end) - min(start) (scheduler-owned).
- critical path: the longest causal chain of the scheduled DAG by
  duration; ties broken by semantic event id. NOT "largest busy time".
- utilization (exclusive): occupied capacity-time / (capacity x window),
  window = makespan (§46); bandwidth resources report bytes and the
  capacity integral (byte-seconds).
- request latency: completion - arrival for events bound to an explicit
  request (§53); distributions carry sample_count; unsupported metrics
  are absent, never zero (§97).
```

## `tracks/t3-topology/dse/veritx_dse/performance/model.py`

```text
veritx_dse.performance.model — PerformanceModel (§10/§13/§63).

One immutable, versioned, content-addressed artifact binding every
timing-affecting assumption of a Wave-E evaluation:

    performance_model_id = H(tag, schema_version, clocks,
                             compute_model, memory_model,
                             network_timing_model, resources,
                             arbitration policy)

Any change to a timing-affecting field changes the identity. Host data
(paths, wall time) never enters. The model carries no measured values
that lack provenance: rates are declared ANALYTICAL/UNCALIBRATED here
because the repository holds no calibration dataset.
```

## `tracks/t3-topology/dse/veritx_dse/performance/network.py`

```text
veritx_dse.performance.network — BookSim evidence → network timing (§36–§42).

Wave D owns WHAT traffic; Wave E owns WHEN — but only through explicit
backend timing evidence. This module is the single seam:

- The Stage-A audit (§38) established that BookSim evidence exposes a
  GLOBAL ``completion_time`` (network cycles) plus packet/latency
  statistics, and does NOT expose per-message completion cycles.
- Therefore (§39) the whole traffic window is ONE BARRIER network
  event with duration = completion_time / network_clock_hz. Inventing
  per-operation causality from aggregate stats is forbidden and this
  module refuses to do it.
- One timing authority per network effect (§40): BookSim already
  simulates contention inside the window; no analytical NoC model is
  applied on top.
- The binding carries the full evidence provenance (§42):
  physical_traffic_id, backend config/input hashes, evidence sha256,
  stats sha256, network clock, window kind.

Without a bound network clock the window keeps its CYCLES and refuses
cross-domain wall-time claims (§37: never guess a frequency).
```

## `tracks/t3-topology/dse/veritx_dse/performance/result.py`

```text
veritx_dse.performance.result — EventGraph + PerformanceResult (§65/§66/§74).

Identity DAG (direct parents, mechanically hashed):

    event_graph_id = H(temporal_workload_id, performance_model_id,
                       network window binding?, Wave-D chain?)

    performance_result_id = H(event_graph_id, performance_model_id,
                              canonical schedule, makespan, critical path)

Two rules from Waves C/D carry over verbatim:

- **Schema close**: a VERIFIED result refuses unknown fields — no
  ``{"estimated_speedup": "47%"}`` hitchhiking through verification (§75).
- **Summaries are re-derived**: makespan, utilization and the critical
  path are recomputed from the authenticated schedule on load; a
  persisted summary that disagrees with the schedule refuses (§74/§133).
```

## `tracks/t3-topology/dse/veritx_dse/performance/scheduler.py`

```text
veritx_dse.performance.scheduler — deterministic discrete-event scheduler (§33/§34).

One authoritative scheduler. Event boundaries are dependency
completions, resource releases, bandwidth completions, and future
ready times — never fixed timesteps (§32). Two resource classes from
the model:

- EXCLUSIVE capacity ``c``: at most ``c`` simultaneous claims. FIFO
  under contention ordered by earliest-ready time, then semantic event
  id (§20/§33; no set iteration, no host time).
- BANDWIDTH ``B`` bytes/s: fluid EQUAL_SHARE among active transfers.
  An arriving transfer joins the active set at its own ready time;
  every active transfer's rate is recomputed at each boundary
  (event-driven fluid equal sharing, §31).

Ready-time gate: an event is admitted only when every predecessor has
finished — a dependent entering the heap at admission time carries a
*future* ready time and acts as a future arrival, never as an
immediate start. This is what keeps fluid sharing causal: a transfer
cannot consume bandwidth before it begins.

Invariants enforced and tested (§34): start >= every predecessor end;
capacity never exceeded; start <= end; each event executes exactly
once; quiescence schedules everything. Unfinished events with no
runnable progress raise typed ``SchedulerDeadlock`` (§35: never spin).

All quantities are exact rational seconds (``QTime``/``Fraction``).
```

## `tracks/t3-topology/dse/veritx_dse/performance/sensitivity.py`

```text
veritx_dse.performance.sensitivity — counterfactual sensitivity (§48–§51).

Bottleneck evidence is counterfactual, never "component total larger"
(§47). For each parameter we RE-RUN the actual schedule under explicit
perturbations — no algebraic shortcut (§48) — and report:

    speedup_x   = T_baseline / T_x
    elasticity  = ((T_2x - T_0.5x) / T_1x) / (2 - 0.5)   [§49 sign
                  convention: positive elasticity means a FASTER/
                  BIGGER parameter shortens the makespan]

Zero-cost counterfactuals (duration → 0) measure the *exposed*
contribution of a source class to makespan (§50) — distinct from its
active/busy time (§43). Contributions are NOT additive (§99): each is
reported separately against the same baseline.

Each perturbed run is a distinct derived evaluation identity bound to
base model + perturbation (§51); the engine refuses a perturbation
that makes a supposedly faster resource slow the system down when the
model is monotone in that parameter (§89).
```

## `tracks/t3-topology/dse/veritx_dse/performance/workload.py`

```text
veritx_dse.performance.workload — temporal overlay + event graph (§14–§17).

Wave E does **not** add COMPUTE/KV timing to sealed Wave-D semantics
(§8). The overlay *references* Wave-D operations by id and declares
local compute/memory events with explicit provenance. The event graph
is the causal object the scheduler consumes:

    temporal_workload_id = H(performance_model_id, canonical events,
                             dependencies, resources, requests)

Event kinds (small vocabulary, §14): COMPUTE, MEMORY_READ, MEMORY_WRITE,
MEMORY_COPY, NETWORK_TRAFFIC_WINDOW, BARRIER.

DAG laws (§17): every dependency references an existing event; no self
edges; acyclic; referenced resources exist in the model; Wave-D
operation references resolve; durations are exact and non-negative.
Repeated steps use explicit ``step`` identities — never graph cycles.
```


# `performance` — extracted inline comments

## `tracks/t3-topology/dse/veritx_dse/performance/metrics.py`

line 55:

```text
    # longest_from(eid): (duration-sum, path) of the longest chain that
    # ENDS at eid (walking backward through deps). Process in topo order
    # so every event's deps are resolved before it.
```

line 111:

```text
            # For a fluid transfer the capacity integral is EXACTLY the
            # bytes it moved (rate x dt integrated == bytes). Using the
            # recorded average rate here would be equivalent; using the
            # final instantaneous rate would not — that was a real bug
            # (a shared transfer's share changes at every boundary).
```

## `tracks/t3-topology/dse/veritx_dse/performance/model.py`

line 20:

```text
# Compute timing has exactly ONE supported source in v1: the declared
# duration. The repository holds no FLOPs/kernel model, so advertising an
# "analytical compute" mode would be false provenance (the flag would
# change the fidelity warning while changing nothing about the timing).
```

line 27:

```text
# Memory timing has two declared sources: the event's own duration, or
# the declared bandwidth rate law T = bytes / bandwidth. There is no
# latency term: no identity-bearing base latency exists, and a hidden
# zero is still a hidden assumption.
```

line 196:

```text
        # §20: the contention policy is DECLARED and identity-bearing.
        # Two evaluations under different arbitration are different
        # performance models; an undeclared policy would be a hidden
        # timing assumption.
```

## `tracks/t3-topology/dse/veritx_dse/performance/network.py`

line 21:

```text
# The binding names the workload AUTHORITY it was bound to, and that
# authority changed generation in 2c.4. Rather than keep a v1 field name
# (operation_graph_id) holding a v2 value, the field is named for what it
# is and the binding declares which generation it belongs to. Absence of
# ``schema_version`` means v1, exactly as in the plan chain: the boundary
# is explicit, not inferred from which keys happen to be present.
```

line 70:

```text
        # v1 output is byte-identical to what it always was: no version
        # field, and the historical parent key. Only a v2 binding emits
        # the version and the canonical parent key.
```

line 98:

```text
        # An explicit version, never inferred from key presence: absence
        # means v1, and an unknown version refuses rather than being read
        # as whichever generation happens to match its keys.
```

line 183:

```text
    # Canonical-key acceptance (veritx-integrate §26): the canonical
    # BookSim parser records the backend's reported completion cycles
    # as ``completion_cycles``; historical stats used
    # ``completion_time``. One measured quantity — the backend's
    # reported completion cycles — two labels. The historical label
    # keeps precedence when both are present; a bool is never a count.
```

## `tracks/t3-topology/dse/veritx_dse/performance/result.py`

line 148:

```text
    # The fidelity classification is DERIVED from the model, never
    # supplied: a producer cannot leave it null (hiding the claim) or
    # forge it (the verifier re-derives the same function).
```

line 184:

```text
        # The name says exactly what it is: the longest EXPLICIT
        # dependency chain. Resource-serialization edges (two independent
        # events sharing a capacity-1 resource) are not part of it, so
        # this can be shorter than the makespan and must not be read as
        # the realized schedule critical path.
```

## `tracks/t3-topology/dse/veritx_dse/performance/scheduler.py`

line 155:

```text
    # §20: the contention policy is declared in the model, not assumed
    # here. An unknown policy refuses rather than silently scheduling
    # under FIFO.
```

line 169:

```text
    # §36/§42: the aggregate window event with no evidence-bound duration
    # would silently schedule at its declared placeholder (0) — i.e.
    # claim the network is free without any timing authority. Refuse:
    # network time enters ONLY through the evidence seam.
```

line 191:

```text
    # §52/§101: an explicit request arrival is a RELEASE TIME for the
    # work that request owns, and for any event it declares as a root.
    # Without this, arrivals are inert bookkeeping: work could start (and
    # finish) before the request exists, and the latency metric would
    # then have to refuse a workload the scheduler happily accepted.
    # This is what makes multiple explicit arrivals real queueing on
    # shared resources rather than a silently time-zero assumption.
```

line 212:

```text
    # bandwidth: name -> {"items": [...], "total": bytes/s}
    #   item = [eid, remaining_bytes, t_ref, start_q, work_bytes];
    #   remaining_bytes is measured at t_ref; start_q is the ORIGINAL
    #   start (reported in the schedule) — never advanced. The per-item
    #   rate is total/len(items), computed on demand: writing the same
    #   rate into every item at every admission is O(n) per admission,
    #   which is quadratic for a wide sharing set.
```

line 228:

```text
    # Events ready but blocked by a FULL exclusive resource wait here,
    # per resource, instead of being re-scanned at every instant: they
    # can only become admissible when that resource releases, and the
    # release path re-queues exactly that resource's waiters. Each list
    # is a heap keyed by (ready, event_id) so an event that bounces
    # (moved to the ready heap, then blocked again by a rival that took
    # the slot first) returns to its correct FIFO position in
    # O(log n) rather than at the tail.
```

line 303:

```text
            # Waiters are appended in (ready, id) order, so moving the
            # first `room` of them preserves FIFO. Moving ALL of them
            # (and re-blocking the surplus) would rescan the whole queue
            # at every instant — the O(n^2) this queue exists to avoid.
```

line 358:

```text
        # 0+1) fixed point: release capacity that is DUE (q <= t_now,
        #      zero-duration events complete immediately) and admit what
        #      fits, until neither can make progress
```

line 376:

```text
        # 2) advance to the next STRICTLY FUTURE boundary: a future
        #    arrival, an exclusive release, or a fluid completion
        # The ready heap is ordered, so its minimum IS the next arrival:
        # scanning it (and the blocked waiters, which are all ready at or
        # before t_now by construction) was the remaining O(n) per
        # instant — quadratic on wide graphs.
```

## `tracks/t3-topology/dse/veritx_dse/performance/sensitivity.py`

line 45:

```text
        # A perturbation must change EXACTLY ONE variable: dropping the
        # memory authority would silently reset it to the constructor
        # default, making the counterfactual a two-variable experiment.
```

## `tracks/t3-topology/dse/veritx_dse/performance/workload.py`

line 28:

```text
# ONE aggregate network event covering the WHOLE Wave-D traffic artifact.
# BookSim exposes a global completion window and no per-message completion
# cycles, so a per-operation network event would be a lie: assigning the
# global window to each of N operations multiplies the network
# contribution N-fold (or invents overlap) with no evidence behind it.
```

line 337:

```text
                    # The declared memory authority must MATCH what the
                    # scheduler will actually do, or the model would carry
                    # false provenance: a declared duration silently
                    # overridden by the shared rate law (or vice versa).
```

line 435:

```text
            # Full model CONTENT, not just the id: content-addressing
            # makes the parent binding mechanical (content determines
            # performance_model_id) and to_dict/from_dict an exact
            # roundtrip — a persisted workload re-verifies on load.
```


# `performance` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/performance/metrics.py` :: `dependency_critical_path`

```text

    Chain length = sum of scheduled durations along a dependency chain,
    maximized over the event DAG; ties broken by semantic event id
    ordering (deterministic). This is NOT "largest total busy time", and
    it is NOT the realized schedule critical path either: resource
    serialization is not a dependency edge, so two independent events
    sharing a capacity-1 resource run back to back while this metric
    reports only the longer of the two. The name says which one it is;
    sensitivity analysis is the tool for realized bottleneck attribution.
    Iterative memoized evaluation: safe for deep chains (§140).
```

## `tracks/t3-topology/dse/veritx_dse/performance/network.py` :: `NetworkWindowBinding`

```text

    ``workload_parent_id`` names the workload authority this window was
    bound to: the historical OperationGraph in generation 1, the canonical
    WorkloadGraph in generation 2. Values are never compared across
    generations — a v1 binding proves a v1 parent, a v2 binding proves a
    v2 parent.

    ``duration`` is the exact wall-time window (completion_time /
    network_clock_hz) when a clock is bound, else ``None``: cycles-only
    evidence is retained for provenance but can never be converted to
    time without a declared frequency (§37 — never guess one).
```

## `tracks/t3-topology/dse/veritx_dse/performance/network.py` :: `bind_network_window`

```text

    Returns ``(binding, duration)`` where duration is a QTime when a
    clock is bound, else the raw cycle count (cycles-only mode, §37:
    cross-domain wall-time claims refuse downstream).

    ``chain`` is the Wave-D plan chain block (physical_traffic_id,
    workload parent id, backend hashes) — passed through, never
    re-derived here. ``evidence_sha256`` is the digest of the exact
    authenticated evidence bytes (``EvidenceRef.sha256``), supplied by
    the caller that read the evidence; a binding that cannot name its
    evidence refuses.
```

## `tracks/t3-topology/dse/veritx_dse/performance/result.py` :: `PerformanceEventGraph`

```text

    Transitively immutable, like every other Wave-E/D artifact: the
    Wave-D chain block is copied into a frozen canonical map, so mutating
    the caller's dict (or any nested value) cannot change the graph after
    ``event_graph_id()`` has been observed. A cached identity over
    mutable content is the exact bug class Waves B and D exterminated.
```

## `tracks/t3-topology/dse/veritx_dse/performance/result.py` :: `reverify_result`

```text

    The verified workload + model + network binding are the authority:
    the deterministic scheduler is RE-RUN from them, the persisted
    schedule must equal that expected schedule exactly, and only then are
    the summaries re-derived (from the expected schedule). Proving that
    summaries follow *a* schedule is not the same as proving the schedule
    follows the verified parents — a self-consistent re-signed schedule
    must not verify. There is deliberately no caller-supplied schedule
    seam: one schedule for summaries and another for identity is exactly
    the confusion this closes.
```

## `tracks/t3-topology/dse/veritx_dse/performance/scheduler.py` :: `ScheduledEvent`

```text

    ``bytes_moved`` is the EXACT number of bytes the transfer moved, and
    ``bandwidth_allocated_bps`` is the time-weighted AVERAGE rate over
    the interval (bytes / duration), not the instantaneous rate at
    completion. A fluid transfer's share changes at every boundary, so
    recording only the final instantaneous rate loses the history: the
    average is what integrates back to the bytes actually moved.
```

## `tracks/t3-topology/dse/veritx_dse/performance/scheduler.py` :: `admit_ready_batch`

```text

        Exactly the previous one-event-at-a-time policy, without the
        O(n) rescan per admission: the ready heap is already keyed by
        (ready, event_id), so popping it admits in the same order, and
        events that become ready mid-batch (a zero-duration predecessor
        completing) enter the same heap and are therefore considered
        before any later candidate — which is what the rescan used to
        guarantee. An event blocked by exclusive capacity is set aside
        and pushed back for the next instant; it cannot become
        admissible without a release, and releases only happen when
        ``t_now`` advances.
```

## `tracks/t3-topology/dse/veritx_dse/performance/sensitivity.py` :: `perturb_workload_durations`

```text

    Each selector touches exactly one class, so the counterfactuals are
    distinguishable:

    * ``duration_factor`` scales declared COMPUTE/BARRIER durations;
    * ``memory_zero`` zeroes memory transfers (bytes AND duration);
    * ``network_zero`` zeroes the network window;
    * ``network_factor`` scales network event durations.

    ``network_factor``/``network_zero`` only affect the EVENT durations:
    a caller that supplies ``network_durations`` (the evidence-bound
    window) must perturb that mapping too — ``sensitivity_analysis``
    does exactly that, because otherwise the window would silently
    override the perturbation.

    Because events are immutable, a perturbed workload is a NEW object;
    its ``temporal_workload_id`` differs (identity rule, §51).
```

## `tracks/t3-topology/dse/veritx_dse/performance/workload.py` :: `PerformanceRequest`

```text

    ``request_id`` is the identity the scheduler keys release times by, so
    it must be unique within a workload. Root/completion/first-token
    events must be owned by this request or unowned — one ownership
    policy for all three.
```


# `performance` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/performance/model.py` :: `rate_duration`

```text

    Exact rational. This is a *declared analytical model*, not an HBM
    prediction; the caller binds it into model identity via the
    resource/bandwidth definitions. There is deliberately NO latency
    term: the repository declares no base memory latency, and folding a
    silent zero into the law would be a hidden timing assumption. Memory
    latency is UNSUPPORTED in v1.
```

## `tracks/t3-topology/dse/veritx_dse/performance/result.py` :: `network_durations`

```text

        BookSim exposes a global completion window, so the workload
        declares exactly one NETWORK_TRAFFIC_WINDOW event and it receives
        that window verbatim. Handing the same global duration to several
        network events would multiply or fake-overlap the network
        contribution with no evidence behind it. Without a bound clock the
        duration stays None and cross-domain wall-time mixing refuses.
```

## `tracks/t3-topology/dse/veritx_dse/performance/scheduler.py` :: `_duration_of`

```text

    Compute always uses the declared duration: v1 has no compute model, so
    ``compute_source`` admits EXPLICIT_DURATION only. Memory events use the
    declared duration unless ``memory_source`` is ANALYTICAL_BANDWIDTH, in
    which case the resource's rate law ``T = bytes / bandwidth`` applies
    (no latency term exists to fold in).
```
