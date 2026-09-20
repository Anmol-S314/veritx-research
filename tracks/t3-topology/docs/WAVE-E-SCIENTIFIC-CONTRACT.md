# Wave E — System-Performance Scientific Contract

Status: **SEALED v1 supported domain** (branch `wave-e/system-performance`, from Wave-D seal `d3f3bd63b952b54fb5cac688532caf83ca66c512`). Machine-readable mirror: `wave-e-contract.json` (schema_version 2). Seal report: `WAVE-E-SEAL-REPORT.md`.

Wave D answers **what** communication occurs. Wave E answers **when** it and all
explicitly declared local work occurs, under an explicit, versioned performance
model. Two questions stay separate everywhere in this document:

- **Internal correctness** — given durations + dependencies + capacities, is the
  schedule the mathematically correct one? This is provable (oracles, bounded
  exhaustive, property tests).
- **Predictive accuracy** — does a modeled duration match real hardware? This is
  not provable; it is MEASURED / CALIBRATED / ANALYTICAL / UNCALIBRATED, and
  Wave E never uses `EXACT` for it.

## 1. Trust chain

```
verified Wave-D semantics
→ explicit WaveEPerformanceModel
→ explicit WaveETemporalWorkload (events + deps + resource claims + requests)
→ WaveEEventGraph (validated, identity-bound)
→ deterministic discrete-event schedule
→ network timing ONLY from qualified BookSim evidence (when used)
→ re-derived metrics (makespan, critical path, utilization, request latencies)
→ counterfactual sensitivity / bottleneck evidence
→ persisted, schema-close, re-verified WaveEPerformanceResult
```

Every reported number must be mechanically explainable by this chain. No metric
may silently depend on a hard-coded clock, a mutable preset, a hidden bandwidth,
an overlap heuristic, or an unversioned constant.

## 2. Time and clocks

- Canonical time is **exact rational seconds** (`wavee/time.py`, `Fraction`-based;
  serialized as `{"numerator", "denominator"}`, denominator > 0). Floats exist
  only at reporting boundaries.
- Every cycles→seconds conversion requires an explicit `clock_hz > 0` bound into
  `performance_model_id`. There is **no default 1 GHz**. A network window without
  a clock keeps its **cycles** and refuses wall-time claims.
- Unit law: `cycles × (1/clock_hz) = seconds`; `bytes / (bytes/s) = seconds`.

## 3. Identity DAG (direct parents, mechanically hashed)

```
performance_model_id  ← H(schema_version, clocks (name + exact hz),
                           resources (name/kind/capacity|bandwidth),
                           compute_source, network_timing_model,
                           network_clock, arbitration_exclusive,
                           arbitration_bandwidth)
temporal_workload_id  ← H(performance_model_id, canonical events,
                          dependencies, resource claims, requests)
event_graph_id        ← H(temporal_workload_id, performance_model_id,
                          network window binding where present,
                          Wave-D chain block where present)
network window        ← operation_graph_id, physical_traffic_id,
   binding (fields)      backend_config_hash, backend_input_hash,
                          evidence sha256, evidence-stats sha256,
                          network_clock_hz, window_kind
performance_result_id ← H(event_graph_id, performance_model_id,
                          canonical schedule, makespan, critical path)
```

Two different timing models with identical Wave-D traffic produce different
identities. Same-output/different-model transplants refuse.

## 4. Resource model

Exactly two resource classes (no taxonomy zoo):

- **EXCLUSIVE** (`capacity ≥ 1`): GPU compute engine, DMA engine, … At every
  instant `active claims ≤ capacity`. Policy `FIFO_SERIAL`: admit by (earliest
  ready, semantic event id).
- **BANDWIDTH** (`bandwidth_bytes_per_s > 0`): HBM, local copy path. Policy
  `EQUAL_SHARE_BANDWIDTH` — fluid equal sharing; `Σ allocations ≤ B` at every
  event boundary. Event-driven, never fixed timesteps; a transfer joins and
  leaves the active set exactly at its own start/completion times and its
  rate is recomputed at every boundary (verified exact: 1200 B shared 600/600
  splits a 1 s transfer into exactly 3/2 s and 1.0005 s when a second 600 B
  transfer arrives at 0.5 ms).

  A schedule records, per transfer, the exact **`bytes_moved`** and the
  time-weighted **average** rate (`bytes / span`) — never the final
  instantaneous share, which does not integrate back to the traffic. The
  capacity integral of a fluid transfer IS the bytes it moved, so
  `utilization = bytes_moved / (B × window) ≤ 1`; a schedule whose integral
  exceeds the resource capacity refuses rather than reporting an impossible
  number.

**The policy is declared and identity-bearing.** Both policy names are fields
of `WaveEPerformanceModel`, so two evaluations under different arbitration are
different performance models; the scheduler refuses a policy it does not
implement rather than silently falling back to FIFO.

**Feasibility is proven; optimality is a property of the chosen policy.**
`FIFO_SERIAL` admits by identity order, so under capacity contention it is
**not** makespan-optimal: with three independent jobs of 1 µs, 1 µs and 2 µs on
capacity 2, FIFO produces 3 µs while the optimum is 2 µs. The bounded-exhaustive
oracle records that counterexample, proves the production schedule is never
*better* than the optimum (soundness), and proves optimality where the policy is
non-idling-optimal (capacity 1, and the hand corpus). This is a stated property
of a declared model, not a hidden scheduling assumption.

Network **links are not modeled here** when BookSim is the network timing
authority; modeling them twice would double-count contention.

## 5. Scheduler

Deterministic discrete-event. Boundaries: dependency completion, resource
release, bandwidth completion. Stable tie-break: semantic event id; no Python
set iteration; no host time in outputs. Invariants (all enforced + tested):
start ≥ every predecessor end; capacity never exceeded; start ≤ end; each event
runs exactly once; quiescence schedules everything. Unfinished events with no
runnable progress raise typed `SchedulerDeadlock` (§35: no spinning).

**Request arrivals are release times.** Work owned by an explicit request
(and any event it declares as a root) cannot start before that request's
`arrival`; later arrivals therefore queue behind earlier ones on shared
resources instead of all starting at time zero. This is what makes the
latency metric well defined: a request can never complete before it arrives.

Complexity is event-driven, not per-cycle: admission pops the ready heap
(batch), events blocked on a full exclusive resource wait in a per-resource
heap and are re-queued only as capacity frees, and the next arrival is the
ready heap's minimum. 50 000 independent events on capacity 4 schedule in
about a second; 50 000-deep chains and 50 000-way bandwidth sharing likewise.

## 6. Compute / memory timing

The two sources are SEPARATE identity-bearing fields, because a single
`compute_source` flag that only affected memory was false provenance:

- `compute_source`: **`EXPLICIT_DURATION` only.** The repository holds no
  FLOPs/kernel model, so an "analytical compute" mode would change the
  fidelity warning while changing nothing about the timing. Declaring one
  refuses. `MEASURED_DURATION` / `CALIBRATED_MODEL` need a real dataset;
  none exists → `UNCALIBRATED`.
- `memory_source`: `EXPLICIT_DURATION` (the event's declared duration) or
  `ANALYTICAL_BANDWIDTH` (`T = bytes / bandwidth` for a bandwidth
  resource). **The declared source must match what the scheduler does**, or
  the model would carry false provenance — the exact failure the compute
  split fixed:
  - `ANALYTICAL_BANDWIDTH` requires a memory event on a BANDWIDTH resource
    with bytes > 0 and a declared duration of 0 (two authorities cannot own
    one duration);
  - `EXPLICIT_DURATION` refuses a memory event on a BANDWIDTH resource that
    carries bytes, because the fluid scheduler would override the declared
    duration; explicit memory timing uses an EXCLUSIVE resource;
  - a zero-byte, zero-duration memory event is a no-op under either source.
  **There is no latency term**: the repository declares no base memory
  latency, and folding a silent zero into the law would be a hidden timing
  assumption. Memory latency is UNSUPPORTED in v1.
- Memory bytes are explicit; capacity is an exact constraint only where
  residency is explicitly declared (DEFERRED).

## 7. Network timing (the one seam)

BookSim evidence (§38 audit) exposes: `completion_time` (global cycles),
`delivered`, `pkt_count`, latency avg/max/p50/p95/p99, `flits_injected`,
`flits_accepted`, `drain_verdict`. It does **not** expose per-message
completion cycles. Therefore:

- A workload declares **exactly one `NETWORK_TRAFFIC_WINDOW` event**
  covering the WHOLE Wave-D traffic artifact, with
  `duration = completion_time / network_clock_hz` (§39: no invented per-op
  causality). It carries no Wave-D operation id and declares duration 0 —
  both are refused, because the window is not one operation's time and the
  declared duration would be inert.
- `NETWORK_OPERATION_REF` is **UNSUPPORTED and refuses at construction**:
  assigning the global window to N operations would multiply the network
  contribution N-fold or invent overlap, with no evidence behind it.
  Per-operation network timing arrives only when BookSim exposes
  per-message completion.
- The evidence binding is present **iff** the overlay declares a window
  event: a pure-compute overlay claims no network window, and a claimed
  window that no event consumes refuses.
- Communication overlap *within* the window is BookSim's business.
- `cycles → seconds` requires the explicit network clock; without it the
  window stays in cycles and cross-domain wall-time claims refuse.
- Wave E never re-derives Wave-D traffic and never applies an analytical NoC
  contention model on top of BookSim-simulated traffic (§40: one authority per
  network effect).
- The result binds the full evidence provenance: `physical_traffic_id`,
  `backend_config_hash`, `backend_input_hash`, evidence sha256, stats sha256,
  network clock, window kind.

## 8. Metrics

- `makespan = max(end) − min(start)` over the scheduled domain.
- **`dependency_critical_path`** = longest EXPLICIT dependency chain of the
  scheduled DAG (not "largest busy time", and not the realized schedule
  critical path either); ties broken by semantic id. Resource serialization
  is NOT a dependency edge, so two independent events sharing a capacity-1
  resource run back to back while this metric reports only the longer one.
  The name says which one it is; sensitivity analysis is the tool for
  realized bottleneck attribution. A realized critical path would require
  reconstructing resource-causality edges — deliberately not built in v1.
- **Schedule accounting** (persisted with the schedule and re-derived on
  load): each bandwidth transfer records the exact `bytes_moved` and the
  time-weighted average rate; the capacity integral equals the bytes moved;
  `utilization ≤ 1` is enforced and an over-capacity schedule refuses.
- **Utilization** = occupied capacity-time / (capacity × makespan) per exclusive
  resource; bandwidth resources report bytes and capacity integral.
- **Request latency** = completion − arrival, only for events bound to explicit
  requests; distributions carry `sample_count`; TTFT needs an explicit
  first-token completion; TPOT needs explicit decode-step identities. Otherwise
  the metric is **UNSUPPORTED**, never a fake zero.
- **Exposed network** = `T_baseline − T_{network→0}` counterfactual — distinct
  from network active time (§43/§98).
- Attribution is **non-additive** (§99): sensitivities are reported
  per-parameter and never summed into the makespan.

## 9. Sensitivity

Perturbations (`0.5×`, `2×`, and zero-cost counterfactuals) re-run the actual
schedule — no algebraic shortcuts. Report `speedup = T_base/T_pert` and
elasticity with documented sign convention. Each perturbation is a distinct
derived identity bound to base model + perturbation. Contradictory monotonicity
(§89) fails the analysis rather than being reported.

## 10. Result provenance binding

The persisted `wave_e` block is **re-derived, never trusted**:

```
schema close          set(result.wave_e) == RESULT_WAVE_E_KEYS
plan binding          result.wave_e.{temporal_workload_id,
                      performance_model_id} == plan.wave_e
parent verification   the temporal workload resource re-verifies; its
                      model id must match
Wave-D chain          result.wave_e.wave_d_chain == plan.wave_d on every
                      chain field (a DIFFERENT valid chain refuses)
evidence binding      network_binding.evidence_sha256 == THIS run's
                      authenticated evidence digest; stats_sha256 ==
                      canonical digest of THIS run's stats;
                      operation_graph_id / physical_traffic_id /
                      backend hashes == their authorities;
                      network_clock_hz == the model's declared clock
window                network_window == network_binding.duration
schedule              the schedule is RE-RUN from the verified workload
                      + binding and makespan must match
fidelity              metrics_warning == wave_e_metrics_warning(model)
```

At plan level the binding must also resolve: the temporal workload exists and
re-verifies, its model id matches, and every declared Wave-D operation id
exists in the plan's operation graph (an overlay may only schedule
communication this workload actually performs).

Why this is not redundant: two workloads with different semantic identities
(e.g. DECODE vs PREFILL) can render **byte-identical** BookSim traffic, so
"this chain is valid" and "this chain is this experiment's chain" are different
questions. Every check above is exercised by an attack in
`test_wave_e_product.py::TestWaveEProvenanceBinding`.

## 11. Comparison compatibility

Two latency values are not automatically comparable. The Wave-C
comparison gate gains a required `timing_model` dimension, valued as the
verified `performance_model_id` for a Wave-E result and `NO_TIMING_MODEL`
for an untimed one:

```
different performance model (clocks, resources, compute source,
  arbitration, calibration context)  -> COMPARISON_INCOMPATIBLE
timed result vs untimed result       -> COMPARISON_INCOMPATIBLE
same model, different durations      -> comparable (that is the study)
explicitly declared variation        -> allowed via the contract
```

Durations are workload semantics; the model is measurement semantics.
Only the latter must match for two numbers to mean the same thing.

## 12. Persistence and authenticity

Resource kinds `waveeperfmodel`, `waveetemporal`, `waveeresult` follow the
Wave-C/D rule: requested filename id == embedded resource_id == recomputed
canonical-content id; closed field sets; parents verified before use; **schema
close** — an unknown performance-looking field in a VERIFIED result refuses;
summaries (makespan, utilization, critical path) are **re-derived from the
verified schedule** on load, never trusted as copied text (§74).

## 13. Calibration status

`UNCALIBRATED` for all analytical compute/memory rates: the repository holds no
measured per-operation timing dataset (audited at Stage A). No CalibrationArtifact
is claimed, and the fidelity warning inside every result is **re-derived from the
verified model** so a forged "VALIDATED against H100" claim cannot survive a load.
If data appears later, it must bind dataset hash, device, fit parameters,
held-out error metrics and validity domain before any calibrated claim is made.

## 14. Capability matrix

Status vocabulary: `EXACT_MODEL_SEMANTICS` (the model is exact and the
implementation provably matches it) · `ANALYTICAL` (declared model, no
empirical claim) · `UNCALIBRATED` (no dataset) · `UNSUPPORTED` (refuses)
· `DEFERRED` · `BLOCKED` · `NOT_RUN`.

| Capability | Status | Evidence / reason |
|---|---|---|
| explicit fixed compute duration | EXACT_MODEL_SEMANTICS | declared duration used verbatim; scheduler proven vs oracle |
| analytical compute (FLOPs/rate roofline) | UNSUPPORTED | no FLOPs model in the repo; not invented |
| calibrated compute | UNCALIBRATED | no measured dataset |
| explicit memory duration | EXACT_MODEL_SEMANTICS | as above |
| analytical memory `T = latency + bytes/BW` | ANALYTICAL | `rate_duration`, bound into model identity |
| memory capacity constraint | DEFERRED | residency is not declared in v1 workloads |
| memory contention (equal share) | ANALYTICAL | event-driven fluid sharing, exact-rational |
| BookSim network cycles | EXACT_MODEL_SEMANTICS | evidence `completion_time` |
| BookSim cycles → wall time | EXACT_MODEL_SEMANTICS | requires an explicit `network_clock_hz`; no default |
| per-operation network completion | UNSUPPORTED | BookSim exposes only a global window (§7); the event kind refuses at construction |
| memory latency | UNSUPPORTED | no base latency exists; the law is T = bytes/BW with no hidden zero |
| realized (resource-aware) critical path | UNSUPPORTED | only the dependency critical path is computed; named accordingly |
| communication overlap (window vs local work) | EXACT_MODEL_SEMANTICS | causal scheduling; no overlap heuristic |
| single request latency | EXACT_MODEL_SEMANTICS | completion − arrival for explicit requests |
| multiple explicit arrivals | EXACT_MODEL_SEMANTICS | arrivals are release times; deterministic queueing on shared resources |
| TTFT | EXACT_MODEL_SEMANTICS | requires an explicit first-token event, else UNSUPPORTED |
| decode-step / inter-token latency | EXACT_MODEL_SEMANTICS | requires explicit `step` identities |
| throughput | UNSUPPORTED | no defined denominator interval in v1 |
| continuous batching | UNSUPPORTED | no exact request-state contract |
| LLMServingSim integration | BLOCKED | unchanged from the Wave-D seal |
| ASTRA as a wall-time authority | UNSUPPORTED | semantics/clock contract not established |
| Ramulator / memory-simulator timing | NOT_RUN | no interface contract |
| critical path | EXACT_MODEL_SEMANTICS | longest causal chain of the scheduled DAG |
| utilization (exclusive) | EXACT_MODEL_SEMANTICS | capacity-time integral / (capacity × makespan) |
| utilization (bandwidth) | ANALYTICAL | bytes + capacity integral under the declared policy |
| sensitivity / bottleneck evidence | EXACT_MODEL_SEMANTICS | re-run schedules, counterfactual + scaling |
| optimal makespan under contention | UNSUPPORTED | the declared FIFO policy is feasible but not optimal (recorded counterexample, §4) |
| RTL timing | NOT_RUN | Wave G scope |
| area / power / energy | NOT_RUN | Wave F scope |

## 15. What seals Wave E

The scheduler proofs hold (independent bounded-exhaustive oracle + property +
monotonicity + metamorphic overlap), unit conversions are clock-bound, the
contention policy is declared and identity-bearing, network windows bind real
evidence and THIS run's evidence digest, every result summary is re-derived from
the verified workload and binding on load, valid-parent transplants refuse,
sensitivity demonstrates compute-dominant / network-exposed / overlap cases from
schedules (not labels), and all Wave-D/Wave-C regression deltas are zero beyond
the recorded baseline. Uncalibrated analytical status is an honest limitation,
not a blocker.
