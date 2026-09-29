# `simulation` — extracted module rationale

Extracted from the module docstrings of `veritx_dse/{name}` by the 2026-09-29 debloat. Code keeps a one-line pointer; this is the original long-form text.

## `tracks/t3-topology/dse/veritx_dse/simulation/booksim.py`

```text
veritx_dse.booksim — BookSim2 config generation, execution, and result parsing.

Single source of truth for:
  - Building BookSim config strings (never duplicated)
  - Running BookSim subprocess with proper timeout/error handling
  - Parsing latency/hops/throughput from BookSim stdout
  - Trace stats detection

All functions receive Ctx for logging. All errors are raised as
BookSimError (never sys.exit) so callers can handle failures.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/llmserving_protocol.py`

```text
LLMServingSim backend-session protocol (redesign PR 5).

A first-class, LLMServingSim-specific session over the exact stdin/stdout
protocol traced from vendored source — see
docs/protocols/llmservingsim-backend.md for every fact and citation.
NOT a generic interactive-runner: the handoff (§4.2) forbids forcing a
request/response session through a one-shot API, and no second interactive
system exists yet to justify a seam. When the analytical path (Slice C)
reuses this, only then compress.

Protocol contract (one command outstanding, always — the traced frontend
runs read_wait before every write, __main__.py:1074):

    spawn (argv array; backend runs the initial event-handler round)
        ↓ unsolicited burst + first Waiting-terminated reply
    write line: <workload path> | pass | pass <t> | pass -1 | done | exit
                (load <p> is backend-side only: silent ack, NO reply)
        ↓ zero+ event lines, then a terminator line:
        ↓   - contains "Waiting" (substring — traced rule), or
        ↓   - equals the legacy "Checking Non-Exited Systems ..." (accepted,
        ↓     never produced by any vendored binary)
    repeat; "exit" → EOF within a bounded time (backend breaks its loop).

Where this client is deliberately stricter than the traced frontend:
  * EOF while a reply is expected is a ProtocolError, never a silent empty
    reply (the frontend also fails loud here — __main__.py:1076-1093).
  * A missing terminator within the timeout is ProtocolError and the child
    process group is killed — a stall cannot leak (§21: cancellation must
    reach the real OS process).
  * stderr is drained by a bounded daemon thread (the undrained-pipe stall
    at ~round 1500 in the forward-port history is what this prevents), with
    evidence lines (ledger / Comm time / injection counter) kept in a
    separate non-evictable buffer from the diagnostic tail.
  * The substring terminator rule is reproduced EXACTLY (a line merely
    containing "Waiting" terminates) — see protocol doc §7; tests pin it.

Timeout enforcement note: stdout is read in binary via select() with a
deadline and lines are assembled by hand — a blocking readline() on a
stalled backend would hang past any timeout, and text-mode buffering
breaks fd-level readiness.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/model_to_trace.py`

```text
model_to_trace.py — Convert unified TrafficModel to BookSim trace format.

Generates a {cyc src cl dst sz} trace file from traffic_model.json flow classes.
Each collective operation is decomposed into point-to-point packets scheduled
at realistic injection cycles based on the traffic model's constraints.

Usage:
    python3 model_to_trace.py \\
        --traffic-model models/traffic_model.json \\
        --nodes 64 \\
        --out inputs/traffic_model.trace \\
        [--ipc 0.5]  # injections per cycle per node (controls timing)
```

## `tracks/t3-topology/dse/veritx_dse/simulation/ramulator.py`

```text
ramulator.py — Ramulator 2.1 standalone execution backend (Phase 15b).

Runs a lowered ReadWriteTrace through the vendored Ramulator
(third_party/ramulator2, see VERITX_VENDOR.md) as a subprocess and returns
typed MemoryEvidence. Responsibilities ONLY: backend discovery/identity,
driver generation, process execution, drain-aware verdicts, typed parsing.
No workload inference, no ranking policy.

Fidelity note: this is standalone trace execution
(MEMORY_CYCLE_SIMULATION for DRAM timing over an ASSUMPTION/recorded
request stream — the request-generation fidelity rides in the artifact's
assumptions, never collapsed into one "high fidelity" label).

Drain contract: the vendored ReadWriteTrace counts accepted/completed via
request callbacks and finishes only on EOF + full drain (VeritX patch —
upstream treated EOF as completion). Verdicts reconcile issued (manifest)
against accepted, served, and coalesced-write counters.

  issued (manifest) == accepted == served  → PASS
  accepted < issued                         → INCONCLUSIVE (backend loss —
                                             must never happen silently)
  served + coalesced < accepted              → INCONCLUSIVE (drain shortfall)
  backend crash / timeout                   → EVALUATION_FAILED (evidence,
                                             with debris — never INFEASIBLE)
  unsupported geometry                      → UNSUPPORTED (no execution)
  backend not built / trace tampered        → raise (VeriTX-side misuse)

Coalesced writes count as completed (absorbed into a buffered write, independently
reported under num_write_reqs_coalesced — reconciled, not assumed).

v1 driver configuration is FIXED (HBM3/HBM34/FRFCFS/open-row/
pass-through/NoRefresh, clock_ratio 4/1): the only geometry the audit
covers. Anything else refuses as UNSUPPORTED, never silently substituted.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serve_canonical.py`

```text
veritx_dse.simulation.serve_canonical — the canonical ``veritx serve`` path.

    cluster/service config (vendored LLMServingSim semantics)
           ↓
    canonical CompileRequest / fabric (canonical compiler ONLY)
           ↓
    canonical serving loop (real Router/Scheduler/MemoryModel)
           ↓
    ASTRA / BookSim (real binaries, qualified evidence)
           ↓
    real request metrics

LLMServingSim remains the service-semantics authority (instances,
parallelism, model, requests); VeritX remains the physical-fabric
authority (the fabric is compiled from a canonical CompileRequest and is
NEVER derived from the cluster config's network section). The legacy
``python -m serving`` path (which lets LLMServingSim own the network)
survives only behind ``veritx serve --legacy`` and its output must never
be mistaken for canonical evidence.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serving_dp.py`

```text
Slice 39 — dense data-parallel quorum semantics.

**DP synchronization is not a network operation.**  For dense DP there is no
cross-instance collective: a synchronized round still contains exactly the
per-instance TP collectives Slice 38 creates.  What DP adds is *when* a batch
may be dispatched:

    every group member resolves (real batch OR explicit dummy)
        -> pad every member to the group's max_total_len
        -> mark the whole quorum sent together
        -> each member runs its OWN TP group

This module owns DP *synchronization state* and nothing else.  It never owns
topology, routing, endpoint mapping or network configuration, and it never
adds ranks.  The padding semantics are the historical
``_pad_batch_to_max`` from the hardened LLMServingSim loop: only the
high-level dense-forward counters move, so attention keeps seeing the real
sequences while the dense/CUDA-graph shape reflects the padded one.

Two rules are load-bearing and are enforced here rather than trusted:

``sum_total_len = max_total_len``
    NOT ``max_total_len * group_size``.  It is bound into the quorum record
    even though this slice does not consume it: it is the seam a later EP
    slice reads.

``a pending real batch stays unsent``
    until the entire quorum is ready, which is what keeps the historical
    anti-pass-echo invariant intact.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serving_liveness.py`

```text
Serving-loop liveness observation (VeriTX review-directed, post-PR5).

PURE observation — this module never mutates simulator state, never
aborts, never converts a stall into success/failure, and adds no
round-count threshold. The serving loop calls ``observe()`` once per
round with values it has ALREADY computed (plus cheap counters); the
probe:

  * classifies the round into the review-mandated state vocabulary
    (BACKEND_NOT_RESPONDING, BACKEND_RESPONSIVE_NO_TIME_ADVANCE,
    SIM_TIME_ADVANCING_NO_REQUEST_PROGRESS, SCHEDULER_NO_DISPATCH,
    INFLIGHT_NO_COMPLETION, USEFUL_PROGRESS);
  * counts consecutive rounds whose progress fingerprint
    ``(sim_time, retired, pending, deferred, inflight, backend_completions)``
    is unchanged;
  * renders the NO_USEFUL_PROGRESS report (human block + machine JSON)
    on demand — on an explicit request (VERITX_LIVENESS_DUMP=n) or when
    the caller reports a failure (the existing EOF / spin-abort paths
    attach the latest observation).

NO_USEFUL_PROGRESS is an OBSERVATION, never a diagnosis: it does not
claim deadlock and does not change control flow. The report exists so
the question "which state stopped changing first?" has a
deterministic, evidence-backed answer for the historical multi-instance
livelock.

Field sources (serving/__main__.py round body):
  sim_time           — ``current`` (frontend clock; last backend-reported
                       cycle, optionally jumped by pass <t>)
  backend_cycle      — reply burst's trailing completion cycle
  backend_completions— completion lines in the current reply burst
  retired_requests   — ``req_cnt`` (cumulative)
  pending_requests   — router._pending_idx / len(router._pending_requests)
  deferred_requests  — len(router._deferred_sessions)
  inflight_batches   — sum(len(schedulers[i].inflight))
  dispatched_this_round — a new batch/workload was handed to the backend
  per-instance       — waiting/running/inflight (+dp-queued) per instance
  last_command       — the command (logical) issued for the next round
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serving_loop.py`

```text
Slice 37 — request-driven certified serving orchestration loop (§11).

This is the loop Slice 36 deliberately stopped short of.  It drives a real
request trace through the *real* historical service components and the
*qualified* canonical network boundary, in this order::

    JSONL  ->  Router.route_arrived_requests  ->  Scheduler.schedule
           ->  real Batch  ->  ServingBatchPlan  ->  canonical round
           ->  Scheduler.add_done (retirement)  ->  real TTFT / latency

Nothing here authors a metric.  TTFT, end time, latency and ITL come out of
the vendored ``Request`` object, which is the only thing that may set them.
The service clock is the fabric's own reported cycle count
(``RoundOutcome.backend_cycles``) accumulated round by round; the canonical
machine declares ``ns_per_cycle == 1.0``, so cycles and the trace's
nanosecond arrival times share one domain.

Three namespaces stay distinct, as everywhere else in this track::

    serving instance  !=  virtual NPU  !=  canonical rank  !=  endpoint

The vendored ``Scheduler`` needs a **contiguous** NPU span per instance
(``start_npu .. start_npu + num_npus - 1``) and ``add_done`` will not retire
a batch until both ends of that span report.  Canonical ranks are permuted
onto endpoints and an instance's endpoint set is not contiguous, so this
module introduces an explicit *virtual* NPU namespace and translates it to
canonical ranks/endpoints at round-lowering time — never by numeric
coincidence.

Certified service feature profile (declared, narrow)
----------------------------------------------------
Supported: flat JSONL request traces, real arrival times, RR/LOAD routing,
normal prefill/decode progression, independent instances, collectives
expressed as intent with ``expansion_authority = ASTRA``, the
``ASTRA_OWNED_COLLECTIVE_EXECUTION`` tier.

Deliberately **not** supported here (unchanged from Slice 36): PIM, active
remote-memory timing, CXL semantics, memory-offload timing, canonical-message
ASTRA execution, PD disaggregation, and **partial-membership collectives**.
That last one is the reason a round in this loop spans the *full* participant
set: one certified round carries one communicator group, so every instance's
endpoints execute the round's collective together.  A round therefore serves
a whole service step, and ``dispatched_instances`` is the full instance set;
retirement is gated separately by whether an instance actually had a batch in
flight.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serving_runtime.py`

```text
Slice 35 — canonical serving round driver.

Drives one serving round across the qualified boundary using the reclaimed
``ServingBackendSession`` wire protocol (never ad-hoc subprocess code), then
attributes completions through the canonical endpoint namespace.

The serving layer decides *when* a round happens and *which* instances
participate; the canonical adapter decides *how* the fabric runs it.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/trace_to_binary.py`

```text
Convert text traces to binary format for faster BookSim parsing.

Binary format:
  - 4 bytes: magic number (0x54524143 = "TRAC")
  - 4 bytes: count of packets
  - N × 16 bytes: packed records
      cycle:uint64, src:uint16, cl:uint16, dst:uint16, size:uint16
      (struct '<QHHHH' = 8+2+2+2+2 = 16 bytes; this header previously said
       12, which contradicted the pack format — corrected)

Usage:
  python3 trace_to_binary.py input.trace output.trace.bin
```

## `tracks/t3-topology/dse/veritx_dse/simulation/traces.py`

```text
veritx_dse.traces — Trace validation, analysis, extraction, and conversion.

All functions are pure (no side effects beyond file I/O).
Every function receives Ctx for logging and returns structured results.
```


# `simulation` — extracted inline comments

## `tracks/t3-topology/dse/veritx_dse/simulation/booksim.py`

line 21:

```text
# ── Errors ──────────────────────────────────────────────────────────────────
# RECLAIMED (one authority). This module used to DEFINE its own
# BookSimError(Exception)/TimeoutError, while core.errors defined a second
# BookSimError(VeritXError) that the certified backend
# (backend/booksim.py, backend/meshdor.py) actually raises. The CLI caught
# the LOCAL class, so a backend BookSim failure fell through to the generic
# handler. The core classes are shape-identical (returncode/stdout/stderr)
# and additionally subclass VeritXError, so they are re-exported here.
# Callers importing `from ..simulation.booksim import BookSimError` are
# unaffected; `except BookSimError` now also catches backend failures.
```

line 98:

```text
        # detect_trace_stats raises TraceError on unreadable/malformed traces
        # (no silent zero-fallback). Handle it explicitly here so a missing
        # trace still yields a runnable config with a conservative default
        # span — loudly, not silently. RECLAIMED alongside the fail-loud
        # parser change; without it build_config would raise for a trace that
        # only the config text is being inspected for.
```

line 114:

```text
        # For trace-driven mode, use max_samples = 1
        # The sample_period is set to trace_span + 10000, which forces
        # BookSim to run until all events are consumed in one pass
```

line 138:

```text
    # BookSim automatically appends topology suffix to routing function
    # e.g., routing_function=min_adapt + topology=torus -> min_adapt_torus
    # So we just pass the base routing name without the suffix
```

line 256:

```text
# Number-shaped field value. `[0-9.eE+\-]+` would match a bare "-" —
# BookSim's stats module prints "= -" for a stat with no samples (e.g. zero
# packets delivered) — and float("-") then crashes the whole batch.
# RECLAIMED from the stronger lineage (p1b/verified-evaluation ==
# integration/p1-product == epic/booksim-forward-port).
```

line 305:

```text
            # F8 evidence candidate: the \tmaximum within THIS block
            # (grammar: average, minimum, maximum — before "Network
            # latency average"). Guarded: NaN blocks (packet-less
            # phase/class) never produce the key.
```

line 338:

```text
        # THE P0 RECLAMATION: honest request-time latency. Same semantics as
        # p50/p95/p99 (all request-time based), so the distribution and the
        # mean come from one measurement convention.
```

line 346:

```text
        # VeritX (RT reclaim + F3 evidence): the qualified fork prints a drain
        # verdict, delivered count, and flit TOTALS at the trace-drain point
        # (the only point where the counters provably hold full-run values;
        # summed over classes by the fork itself). Stock BookSim prints none of
        # these — keys stay absent, never fabricated, so F3 reports NOT_RUN
        # instead of reading a fabricated zero.
```

line 375:

```text
    #: Highest ADDRESSED node id (src or dst). Feeds the anynet size
    #: pre-check: a graph smaller than the trace's node universe delivers
    #: zero packets and measures nothing. RECLAIMED from the stronger
    #: lineage, which had it; the current tree had dropped the field, so
    #: `presets.anynet_usability(..., trace_max_node)` could never fire.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/llmserving_protocol.py`

line 22:

```text
#: Evidence lines are kept in their own buffer and are NOT evictable by
#: binary chatter: a real canonical round emits ~300 stderr lines of which
#: the collective ledger is a small, early, load-bearing subset.  A single
#: shared tail silently drops it (measured: a 16-rank AllReduce round emits
#: 16 [LEDGER][COLL_SUBMIT] lines and 310 lines total).
```

line 245:

```text
                # the child is gone, so the pipe is at EOF and the drain thread
                # finishes on its own: join it instead of spinning on a
                # readable-forever fd
```

line 364:

```text
                # The exit code is part of the diagnosis, so make it
                # deterministically available: EOF on stdout can be observed
                # a scheduling quantum before the child is reaped, and a
                # bare poll() would then report None and lose the code under
                # load. Wait (bounded) for the reap first.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/ramulator.py`

line 241:

```text
    # Backend config: the driver is generated FROM manifest.geometry, so
    # the declared hash must equal the hash of that same geometry —
    # otherwise the executed config has no declared identity.
```

line 437:

```text
    # Drain counters EXPOSED, not just reconciled: a PASS verdict must be
    # independently checkable from evidence (accepted==completed==generated,
    # outstanding==0 — the reviewer's non-negotiable).
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serve_canonical.py`

line 271:

```text
    # The serving machine is qualified over a trivial ALLREDUCE, but
    # live rounds inject whatever the cluster parallelism can emit
    # (TP allreduce, EP dispatch/allgather + combine/reducescatter).
    # The embedded class envelope must cover those kinds, derived from
    # the serving configuration — never a hardcoded default, never
    # inferred per round. An unattributable kind refuses qualification.
```

line 296:

```text
    # machine qualification over a trivial all-rank collective (the live
    # loop re-projects every round over real batches; the machine itself
    # is workload-independent)
```

line 390:

```text
    # Persist the canonical serving evidence beside the run inputs: the
    # product layer reads serving-evidence.json as the served experiment's
    # evidence document and must not reconstruct it.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serving_liveness.py`

line 99:

```text
        # "no time advance" = this reply reported the same (or no) clock
        # as the previous round, via the probe's memory of the previous
        # observation — never by mutating the obs.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serving_loop.py`

line 75:

```text
    # ── expert-parallel (MoE) extension ──────────────────────────────
    # ep_size == 1 is dense (default; all dense identities byte-identical).
    # ep_size > 1 preserves the executable EP semantics: dispatch
    # ALLGATHER + per-rank expert compute + combine REDUCESCATTER over
    # the SAME ranks (ep_size <= instance ranks; no rank multiplication).
```

line 384:

```text
    #: instances that participated in the round but had no batch in flight;
    #: they must not report execution work.  A DP dummy member is NOT idle:
    #: it is dispatched and appears in ``dispatched_instances``.
```

line 535:

```text
            # close every already-open quorum with an explicit dummy for each
            # member that is genuinely idle (no batch this round, nothing in
            # flight).  A group with no real batch is never opened.
```


# `simulation` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/simulation/booksim.py` :: `detect_trace_stats`

```text

    This is the SINGLE function for trace analysis. All callers use this.
    Never passes "classes" to BookSim — only counts for display.

    Raises TraceError on unreadable/malformed traces instead of silently
    returning zeros — a zeroed span would size sample_period wrong and
    synthesize/evaluate against missing data. An existing-but-empty trace
    (comments only) still returns zeros so callers can report
    "no parseable packets" via ``num_packets == 0``.

    RECLAIMED from the stronger lineage (p1b/verified-evaluation): the
    current tree swallowed every exception and dropped ``max_node``.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/booksim.py` :: `parse_output`

```text

    TWO latency keys, deliberately NOT collapsed (RECLAIMED):

      latency         stock BookSim "Packet latency average" — the qtime-based
                      plat mean, which inflates on sparse traces because qtime
                      slots go stale across idle gaps
      honest_latency  the VeritX fork's ``honest_avg`` = arrival time minus the
                      ORIGINAL trace request timestamp

    These are TWO POPULATIONS, not one. `p50/p95/p99/honest_avg/pkt_count`
    all come from the fork's `_all_latencies` vector (request time);
    `latency`/`max_packet_latency` come from `_plat_stats` (qtime). The
    metric schema splits them into `sim.latency.*` (qtime) and
    `sim.trace_request_latency.*` (request) so a consumer cannot read them as
    one distribution.

    WHO READS WHAT (stated precisely, not "the evidence path prefers
    honest"): `backend/booksim.py::_execute_prepared` parses BOTH, requires
    the stock ``latency`` key, and stores the full stats dict; the certified
    profile, requirements and report consumers therefore read the stock key.
    The comparison CLI prefers ``honest_latency`` when the fork emits it.
    Both are parsed; neither is silently substituted for the other.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/llmserving_protocol.py` :: `BackendReply`

```text

    lines   — every line before the terminator (protocol data: per-NPU
              completion lines, [plat] summaries)
    cycle   — the backend's cumulative clock parsed from the LAST
              completion line in the burst (both traced grammar
              variants), else None
    terminated_by — "Waiting" | "legacy-checking" | "eof"
```

## `tracks/t3-topology/dse/veritx_dse/simulation/llmserving_protocol.py` :: `ProtocolError`

```text

    Carries the bounded tail of the reply burst and of stderr so the
    failure is diagnosable without re-running (handoff §28: preserve
    root-cause information; never reduce it to "timeout").
```

## `tracks/t3-topology/dse/veritx_dse/simulation/llmserving_protocol.py` :: `ServingBackendSession`

```text

    Usage shape (mirrors the serving loop, not an abstraction):

        with ServingBackendSession(argv) as session:
            first = session.read_startup()          # unsolicited burst
            reply = session.command("<workload>")   # legacy round
            reply = session.command("pass")
            reply = session.command("done")
        # exit+escalation happens on close; nothing survives the block.

    Cancellation safety: if the body raises, __exit__ still closes —
    'exit' is written, and a backend that ignores stdin is TERM→KILLed
    with its process group. No orphan survives the with-block.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/llmserving_protocol.py` :: `await_stderr_quiescence`

```text

        stdout (the reply) and stderr are independent pipes, so the backend can
        answer a round while its stderr ledger/statistics are still in flight.
        The drain is a Python readline loop and is slower than the C++
        producer, so with ``VERITX_LEDGER=1`` it can be thousands of lines
        behind when a reply lands; reading the evidence buffer immediately then
        silently loses measured statistics.

        BOUNDED: the loop is driven by an absolute deadline, so a stderr stream
        that never falls silent (e.g. a permanent flood) cannot make this wait
        forever.  Returns True if the pipe went quiet within the budget, False
        if the budget expired with stderr still busy.  A closed pipe or an
        exited child is quiescent by definition.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serving_dp.py` :: `DpQuorumCoordinator`

```text

    States a member's batch moves through::

        scheduled but UNSENT real batch   (batch.sent is False)
        DP dummy                          (explicit, unsent)
        quorum-ready                      (every member resolved)
        dispatched                        (padded and marked sent)
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serving_dp.py` :: `pad_batch_to_max`

```text

    Mirrors vLLM's CUDA-graph DP padding, exactly as the hardened
    LLMServingSim ``_pad_batch_to_max`` does:

        batch.total_len = max_len
        batch.kv_len    += pad
        batch.num_decode += pad

    and deliberately NOT ``decode_k_list`` / the prefill token lists / the
    request list: padding changes the dense forward shape without inventing
    real attention sequences.  Completion accounting reads ``batch.requests``
    and ``batch.end``, so it is unaffected by these mutations.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serving_liveness.py` :: `classify`

```text

        1. backend process dead                          -> BACKEND_NOT_RESPONDING
        2. backend answered, zero completions, no clock
           move, NOTHING inflight (pure idle ping-pong)  -> BACKEND_RESPONSIVE_NO_TIME_ADVANCE
        3. work inflight but zero completions in this
           reply (and nothing dispatched this round)     -> INFLIGHT_NO_COMPLETION
        4. clock advancing but retired count frozen      -> SIM_TIME_ADVANCING_NO_REQUEST_PROGRESS
        5. nothing inflight, nothing dispatched, work
           pending/deferred                              -> SCHEDULER_NO_DISPATCH
        6. otherwise                                     -> USEFUL_PROGRESS

        Precedence note: INFLIGHT_NO_COMPLETION outranks
        SIM_TIME_ADVANCING_NO_REQUEST_PROGRESS because "work is stuck in
        the network" is the operationally sharper label; a pass <t> jump
        while a batch is inflight still reports inflight-no-completion —
        exactly what the historical livelock needs to show.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serving_loop.py` :: `CertifiedServiceProfile`

```text

    ``compute_ns`` and ``collective_bytes`` are *declared* profile inputs, not
    reclaimed upstream measurements: the vendored ``trace_generator`` is
    perf-DB driven (``_load_perf_db(hardware, model, variant, tp_needed,
    model_type)``), and no hardware variant with perf CSVs is qualified here.
    Inventing a substitute would be the dishonest option; declaring a linear
    model and binding it into the profile identity is the honest one.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serving_loop.py` :: `VirtualNpuNamespace`

```text

    The vendored scheduler's NPU ids are a *fourth* namespace, not a synonym
    for canonical rank or endpoint.  Instances are laid out contiguously so
    ``start_npu .. start_npu + num_npus - 1`` is well defined, and every
    translation back to a canonical rank is explicit.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serving_loop.py` :: `run_request_driven_service`

```text

    One iteration of the loop is one certified round: route arrivals, ask
    every instance's real scheduler for a real ``Batch``, lower the round to
    the canonical boundary as collective *intent*, execute it, retire what
    the runtime actually finished, and advance the service clock by the
    fabric's own cycle count.

    ``dp_groups`` declares dense-DP synchronization groups.  Without it the
    behaviour and identities are exactly Slice 38: independent replicas are
    never turned into an implicit DP group.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serving_runtime.py` :: `collective_ledger_lines`

```text

    ``VERITX_LEDGER=1`` makes the frontend emit ``[LEDGER][COLL_SUBMIT]``
    with the collective type, size, members and whether a communicator group
    was used.  That is the runtime's own statement of expansion authority --
    evidence, not inference.

    The match is on the full ``[LEDGER][COLL_SUBMIT]`` tag, not a
    ``[LEDGER][COLL]`` prefix: every ledger tag the runtime emits
    (``COLL_SUBMIT``/``COLL_CONSTRUCTED``/``COLL_COMPLETE``) carries a suffix,
    so a prefix match silently yields no lines and makes the ledger
    validation unreachable.
```


# `simulation` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/simulation/booksim.py` :: `build_config`

```text

    This is the SINGLE function that generates BookSim configs.
    All other code delegates here.

    CRITICAL ordering: BookSim parses top-to-bottom. k/n must come BEFORE
    topology= so the network is built with correct dimensions.
    Also: NEVER pass "classes" — it creates separate traffic classes with
    split VCs, inflating latency 75x for multi-class traces.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/llmserving_protocol.py` :: `stderr_text`

```text

        This is the filtered evidence buffer (ledger submissions, per-endpoint
        ``Comm time`` and the injection counter), not the diagnostic tail:
        evidence must not be evictable by how chatty the binary happens to be.
        ``ProtocolError`` still carries the bounded raw tail separately.

        Call ``await_stderr_quiescence`` first: stdout and stderr are separate
        pipes and the drain thread can still be behind when a reply lands.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/model_to_trace.py` :: `ring_allreduce_packets`

```text

    Ring allreduce: 2(k-1) steps.
    Each step: every participant sends ONE message to next in ring.
    One packet per (step, sender) — matches real trace patterns.

    If accurate=True, scale pkt_flits by total_bytes to match real volumes
    (1 packet per step, packet size = bytes_per_step / 64B_per_flit).
```

## `tracks/t3-topology/dse/veritx_dse/simulation/ramulator.py` :: `_verify_chain`

```text

    The reviewer's blocker: execute() trusted the manifest's declared
    hashes/counts without recomputation, so the middle link of
    intent → artifact → execution → evidence could be substituted.
    After this function, evidence cannot claim a different artifact,
    access stream, backend config, or input than what is executed.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/ramulator.py` :: `execute`

```text

    Tamper-closed chain (2026-09-18): the manifest is not trusted — every
    link is re-verified against its SOURCE before spawn (see
    _verify_chain): artifact, access stream, backend config, trace hash,
    and recounted trace lines must all match the manifest's declared
    identity. Refuses (raising) on VeriTX-side misuse: backend not
    built, missing/tampered inputs. Returns UNSUPPORTED evidence (no
    execution) for geometries outside the v1 envelope.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serve_canonical.py` :: `_persist_serving_normalized_view`

```text

    The file always records whether normalization applied: a replay-only
    or partial run yields an explicit absence record (analyses null with
    the refusal reason), never a silent gap and never zero-filled
    metrics. Only the typed guard refusal is captured here — a
    programming error escapes and fails the run.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serve_canonical.py` :: `load_cluster_service_semantics`

```text

    Returns instances (model/hardware/tp/ep/pp ranks), dp groups and the
    model name. Only service-semantics fields are read: no topology, no
    link bandwidth, no BookSim config — those belong to the fabric
    authority and reading them here would leak the legacy network
    authority into the canonical path.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serve_canonical.py` :: `serving_class_envelope`

```text

    The serving machine is qualified over a trivial ALLREDUCE, but live
    rounds inject whatever the cluster parallelism can emit: TP traffic
    is ALLREDUCE, EP dispatch is ALLGATHER and EP combine is
    REDUCESCATTER. An unattributable kind refuses here (machine never
    qualifies) instead of aborting mid-run in the C++ guard.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serving_dp.py` :: `make_dp_dummy`

```text

    Not ``None``: the dummy must live in the real ``Scheduler`` lifecycle so
    ``Scheduler.add_done()`` can clear it.  It is appended to the scheduler's
    inflight list exactly as ``Scheduler.schedule()`` would, is unsent until
    the quorum dispatches, carries no user requests, and therefore retires
    nothing.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serving_liveness.py` :: `LivenessProbe`

```text

    The fast path is one dataclass construction + one tuple compare per
    round. No I/O, no formatting, unless a report is requested.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serving_loop.py` :: `quorum_sys`

```text

        Source: ``Scheduler.add_done`` — for a non-PD instance the batch is
        done once ``start_npu`` and ``start_npu + num_npus - 1`` are both in
        ``batch.end``.  A PD *prefill* instance would need
        ``start_npu + 2*num_npus - 1``; PD disaggregation is outside this
        certified profile, so that case is refused rather than guessed.
```

## `tracks/t3-topology/dse/veritx_dse/simulation/serving_runtime.py` :: `run_live_round`

```text

    The frontend runs its argv workload during startup, so that one is left
    deliberately idle and the round is delivered through the real
    ``load``/``run`` protocol instead of being executed twice in one process.

    ``staged`` lets a caller that already staged this round (to qualify it)
    reuse the staging instead of translating the same workload twice; the
    staging is deterministic, so this is an optimisation, not a second
    authority.
```
