# Wave E seal report

Status: **SEALED v1 supported domain** (system-performance evaluation).

```
branch      wave-e/system-performance
base        Wave-D seal d3f3bd63b952b54fb5cac688532caf83ca66c512
contract    docs/WAVE-E-SCIENTIFIC-CONTRACT.md (14 sections)
machine     docs/wave-e-contract.json (schema_version 2)
```

Wave D answers WHAT communication occurs; Wave E answers WHEN it and the
explicitly declared local work occur, under a versioned performance
model. The two questions the whole wave keeps apart:

```
internal correctness   given durations + deps + capacities, is the
                       schedule mathematically correct?      PROVABLE
predictive accuracy    does a modeled duration match real
                       hardware?                            MEASURED or
                                                            UNCALIBRATED
```

Wave E never uses `EXACT` to mean "the simulator produced a number".

## 1. What the closure fixed

The implementation arrived with the architecture in place but with seven
product-level trust holes — the same class as Wave D-SEAL.1. All were
reproduced with real attacks before being fixed:

| # | Hole (reproduced) | Closure |
|---|---|---|
| 1 | `makespan` in a persisted result was trusted text; a tampered number survived `load_verified_result` | the schedule is **re-run** from the verified workload + binding and the makespan compared |
| 2 | `network_window` was not tied to the binding | required to equal `network_binding.duration` |
| 3 | `metrics_warning` was trusted, so `"VALIDATED against NVIDIA H100"` could ride along | re-derived by `wave_e_metrics_warning(verified model)` |
| 4 | `wave_e.wave_d_chain` was checked for key-set only — a DIFFERENT fully valid chain could be transplanted | every chain field must equal the plan's chain |
| 5 | `network_binding` was not tied to THIS run's evidence; another run's valid binding was accepted | `evidence_sha256` must equal the authenticated evidence digest of this run |
| 6 | the binding's `evidence_sha256` was actually the *stats* hash (the evidence object carries no digest), so it could not identify evidence at all | `bind_network_window` now takes the authenticated `EvidenceRef.sha256` explicitly and refuses without it; the stats digest is canonical-JSON based and stable across Python versions |
| 7 | a plan could bind a `temporal_workload_id` that does not exist, or whose model it does not name | `load_verified_plan` resolves and verifies the overlay, and requires every declared Wave-D operation id to exist in the plan's operation graph |

Two further correctness findings came out of writing the bounded-exhaustive
oracle:

| # | Finding | Resolution |
|---|---|---|
| 8 | the contention policy was hard-coded in the scheduler and **absent from `performance_model_id`** — a hidden timing assumption (contract §20) | `arbitration_exclusive` / `arbitration_bandwidth` are declared, identity-bearing model fields; the scheduler refuses a policy it does not implement |
| 9 | the declared `FIFO_SERIAL` policy is **not makespan-optimal** under contention | recorded, not hidden: three independent jobs 1 µs, 1 µs, 2 µs on capacity 2 → FIFO 3 µs, optimum 2 µs. The oracle asserts soundness (never better than optimum) and proves optimality where the policy is non-idling-optimal (capacity 1, hand corpus) |

## 1b. Adversarial audit (independent, after the seal)

The sealed tree was attacked layer by layer with real objects fed into
the real production validators. Twelve findings, all reproduced before
being fixed. Two of them were trust-relevant; the rest were silent
nonsense or dead fields.

| # | Finding (reproduced) | Fix |
|---|---|---|
| 1 | **Bandwidth accounting was wrong.** The scheduler recorded only the FINAL instantaneous share per transfer, so `bytes_moved` and `utilization` multiplied that rate by the whole interval: the staggered case reported 2400 bytes for 1800 bytes of traffic and `utilization = 1.33` — impossible. 72/300 randomized DAGs were affected. | `ScheduledEvent` now records the exact `bytes_moved` and the time-weighted AVERAGE rate (`bytes/span`); `resource_utilization` uses the exact bytes; a schedule that exceeds a resource's capacity integral refuses. |
| 2 | **`exposed_compute == exposed_memory`, always.** Both counterfactuals ran the SAME perturbation (zero all non-memory durations), so the "memory" number was compute's. | `perturb_workload_durations` gained a `memory_zero` selector; each counterfactual now zeroes exactly the class it names (verified: 1 ms vs 997 ms on the same workload). |
| 3 | **Request arrivals were inert.** `arrival` and `root_event_ids` were validated and then ignored: a request's work could start (and finish) before the request arrived. A two-request workload that the scheduler accepted then made `request_latencies` raise. Multi-request queueing did not exist. | The scheduler treats an arrival as a RELEASE TIME for the work that request owns (and its declared roots), so arrivals queue on shared resources and latency is non-negative by construction. |
| 4 | **Negative TTFT could be reported.** The overall latency was guarded; `first_token_latency` was not. | Refuses a first-token completion before arrival. |
| 5 | `perturb_model` silently dropped the declared arbitration policies (latent: only the defaults exist today). | Propagated through the perturbation. |
| 6 | `network_factor` was dead code: `network_durations` (the evidence-bound window) overrode the scaled event duration. | `sensitivity_analysis` scales the evidence-bound mapping and reports `network_window_0.5x/2x` rows. |
| 7 | `QTime(True)` meant one second (bool is an int subclass). | Bools refuse. |
| 8 | Negative `QTime` was constructible. | Time cannot be negative; a subtraction that goes backwards refuses. |
| 9 | An empty temporal overlay was accepted, reporting a makespan of 0 that means nothing. | At least one event is required. |
| 10 | `bytes_count` on a COMPUTE/BARRIER/NETWORK event was silently ignored. | Refused: only memory events carry bytes. |
| 11 | `inspect` could not see the persisted `waveeworkload` resource, and results never surfaced their chain links (the navigation block sat in the wrong branch). | The overlay is inspectable (with its users), and a result surfaces `wave_d.*` and `wave_e.temporal_workload_id`. |
| 12 | **The scheduler was O(n^2).** 50 000 independent events on capacity 4 took 139 s: every instant rescanned the ready heap, the blocked waiters and the whole future-arrival set. | Batch admission by heap pop, per-resource wait heaps, O(1) next-arrival. 50 000 events now schedule in 1.27 s — with **0/600 schedule differences** against the previous scheduler on randomized mixed DAGs (semantics preserved, verified differentially). |

The remaining invariants held under attack: across 300 randomized
mixed-resource DAGs there were **zero** dependency violations, zero
exclusive-capacity violations, zero fluid-law violations (bytes moved ≤
bandwidth × window), and after the fixes zero accounting errors. The
critical path matched an independent brute-force longest-chain
computation on 300 random DAGs (0 mismatches). Product-level transplant,
tamper and schema attacks all refuse.

### Boundary (not a defect, but stated)

A writer with full store access who re-signs the overlay, plan,
experiment, result and attempt consistently can present a different
*timing model*: the temporal overlay is a DECLARED input, not a
measurement. Only the network window is anchored in authenticated
evidence (its sha256 is bound into the result). The verified loaders
prove internal consistency plus evidence binding; they do not make the
store tamper-evident — the same boundary Wave C and Wave D declared.
The library-level `reverify_result` is likewise a self-consistency
checker; the product path never persists a schedule, so the product
verifier re-runs the scheduler from the verified overlay and binding.

## 1c. Second adversarial audit: the closure findings

An independent audit of the sealed tree found eight further issues. All
were reproduced, fixed, and locked with tests.

| # | Finding | Fix |
|---|---|---|
| 1 | **The global BookSim window was assigned to EVERY network event.** A workload with two network events got the whole global duration twice (or fake overlap), and the product bound the window to a single Wave-D operation id while it actually covered the whole traffic artifact. | One aggregate `NETWORK_TRAFFIC_WINDOW` event per workload, carrying no operation id and declaring duration 0; `NETWORK_OPERATION_REF` refuses at construction as UNSUPPORTED; the binding exists iff the overlay declares a window event; a window no event consumes refuses. |
| 2 | **`WaveEEventGraph` was mutable beneath a cached identity.** `wave_d_chain` was a caller-owned dict and no attribute was frozen, so mutating the caller's dict left `event_graph_id()` stale. | Transitively immutable: the chain is frozen into the canonical value tree (shared with Wave D), attribute assignment refuses, and mutation of the caller's dict cannot move the identity. |
| 3 | **`compute_source=ANALYTICAL_MODEL` was false provenance.** It changed the fidelity warning but nothing about compute timing — compute always used the declared duration. | `compute_source` admits `EXPLICIT_DURATION` only and refuses anything else; a separate `memory_source` (`EXPLICIT_DURATION` / `ANALYTICAL_BANDWIDTH`) carries the memory rate law. The warning reports both. |
| 4 | **Memory latency was advertised and silently zero.** The law was documented as `T = latency + bytes/BW` while the scheduler passed no latency and `ResourceDef` had none. | The law is `T = bytes / bandwidth` with no latency parameter at all; memory latency is UNSUPPORTED rather than a hidden zero. |
| 5 | **Nested schemas were not closed.** `ResourceDef.from_dict`, `WaveETemporalEvent.from_dict` and `WaveERequest.from_dict` ignored extra fields, so a persisted overlay could carry `claimed_h100_latency_ns: 17`, verify, and still expose the raw field through `inspect`. | All three parsers enforce exact key sets; an unknown field refuses. |
| 6 | **Request identity was ambiguous.** Request ids were not required unique (two `r1` entries shared release keys while metrics looped over both), and `first_token_event_id` was checked for existence but not ownership, so one request could claim another's event. | Unique request ids; one ownership policy for root, completion and first-token events (owned by this request or unowned). |
| 7 | **The library result verifier dropped `bytes_moved`** when rebuilding a persisted schedule, so re-derived bandwidth utilization was wrong again after the audit fix. | The row roundtrip restores `bytes_moved`; schedule rows have a closed key set and an unknown field refuses. |
| 8 | **The "critical path" was not the realized one.** Two independent events on a capacity-1 resource produce a 20 ms makespan while the metric reported 10 ms, because resource serialization is not a dependency edge. | Renamed to `dependency_critical_path` (and `_duration`) everywhere, with the limitation stated in the contract and pinned by a test. Building resource-causality edges was deliberately NOT done in v1; sensitivity is the bottleneck tool. |

## 1d. Third adversarial audit: the final three

A third independent audit found three remaining correctness problems. All
reproduced, fixed, locked.

| # | Finding | Fix |
|---|---|---|
| 1 | **`memory_source=EXPLICIT_DURATION` did not mean explicit duration.** For a memory event on a BANDWIDTH resource with bytes, the fluid scheduler overrode the declared duration with `bytes/rate` (declared 100 ms, scheduled 1 s). We had fixed false COMPUTE provenance and left false MEMORY provenance. | The declared memory authority must MATCH what the scheduler does: a memory event on a BANDWIDTH resource with bytes requires `memory_source=ANALYTICAL_BANDWIDTH` (and a declared duration of 0); `EXPLICIT_DURATION` refuses that combination and is honoured verbatim on an EXCLUSIVE resource. `ANALYTICAL_BANDWIDTH` with no bytes, or with a nonzero declared duration, refuses. A zero-byte zero-duration event is a no-op under either source. |
| 2 | **Bandwidth sensitivity silently changed `memory_source`.** `perturb_model` propagated compute_source, network model, clocks and arbitration but not the memory source, so a `bandwidth_2x` counterfactual also reset the memory authority to the constructor default — a two-variable experiment. | `perturb_model` propagates `memory_source`; a test asserts every other declared source is unchanged and that the model id differs only because bandwidth changed. |
| 3 | **`reverify_result()` accepted forged reported metrics.** It re-derived makespan, the dependency critical path and utilization, but not `request_latencies`, `latency_summary`, `metrics_warning`, `sensitivity`, `network_binding`, `wave_d_chain` or the parent ids — so a document could carry fabricated customer-visible metrics and still verify. | The verifier now re-derives EVERY exposed field: parent ids must be the workload's, the event graph is reconstructed from the workload + binding + chain and its id compared, binding presence must match the window event, and latencies, summary, fidelity warning and sensitivity are recomputed and compared. `build_performance_result` derives the warning itself (a producer can no longer null it). `wave_d_chain` is thawed to plain JSON at the serialization boundary. |

## 2. Repository audit (Stage A): what timing authority exists

Searched for compute cycles, kernel durations, FLOPs, HBM bandwidth/latency,
clock frequencies and historical timing constants across the production tree:

```
backend/booksim.py + simulation/booksim.py
    BookSim statistics: completion_time (global cycles), delivered,
    pkt_count, latency avg/max/p50/p95/p99, flits_injected/accepted,
    drain_verdict.  NO per-message completion cycles.
backend/analytical.py
    registered; execution UNSUPPORTED. Not a timing authority.
core/serving.py, experiment_serving.py
    serving stack; BLOCKED since Wave D. No request timing contract.
synthesis/compiler.py
    bandwidth_floor_gbps is a REQUIREMENT (a constraint to check), not a
    timing model. Not on the Wave-E path.
tools/memory_miss_model.py
    standalone research tool with a default per-bank bandwidth. Not on
    the product path and not promoted to authority.
model/compile_model.py
    Workload carries tp/pp/ep/dp and shape metadata; no timing fields.
```

Ruling: **the repository holds no trustworthy compute/memory timing
authority and no measured dataset.** Wave E therefore treats
`EXPLICIT_DURATION` as the trustworthy baseline, declares analytical rate
laws where they are exact (`T = latency + bytes/BW`), binds every rate
into model identity, and reports `UNCALIBRATED` rather than promoting an
existing constant to scientific authority. No hidden clock, bandwidth or
overlap heuristic influences a VERIFIED result: the only timing numbers
that reach a result are declared durations, declared rates, and BookSim
evidence divided by a declared clock.

## 3. Architecture

```
wavee/time.py         exact rational QTime + explicit clocks
wavee/model.py        WaveEPerformanceModel (clocks, resources,
                      compute source, network timing model,
                      arbitration policies)
wavee/workload.py     WaveETemporalWorkload: events, deps, resource
                      claims, explicit requests, Wave-D operation refs
wavee/scheduler.py    the ONE deterministic discrete-event scheduler
wavee/network.py      BookSim evidence -> BARRIER window binding
wavee/metrics.py      critical path, utilization, request latencies
wavee/sensitivity.py  counterfactual + scaling perturbations
wavee/result.py       WaveEEventGraph + performance result, re-derived
application/wave_e_resources.py   persisted resource + verified block
```

No second control plane: `SrotaControlPlane` remains the only product
authority. The temporal overlay is declared on the intent
(`workload.wave_e`), bound into the plan, executed through the sealed
Wave-B/D path, and verified on load.

## 4. Identity DAG (as implemented)

```
performance_model_id  ← H(clocks, resources, compute_source,
                          network_timing_model, network_clock,
                          arbitration_exclusive, arbitration_bandwidth)
temporal_workload_id  ← H(performance_model content, canonical events,
                          dependencies, resource claims, requests,
                          declared Wave-D operation ids)
event_graph_id        ← H(temporal_workload_id, performance_model_id,
                          network window binding?, Wave-D chain?)
performance_result_id ← H(event_graph_id, performance_model_id,
                          canonical schedule, makespan, critical path)
```

Plan identity binds `{temporal_workload_id, performance_model_id}`; the
result block binds the same pair **plus** the full Wave-D chain, the
network binding, the window, the makespan and the fidelity warning.

## 5. Time / resource contract

```
time          exact rational seconds (numerator/denominator), never floats
clocks        explicit hz, no default 1 GHz; cycles→seconds requires one
resources     EXCLUSIVE (capacity >= 1) | BANDWIDTH (bytes/s > 0)
arbitration   FIFO_SERIAL | EQUAL_SHARE_BANDWIDTH, declared + hashed
network       one BARRIER window per traffic window; links are NOT
              re-modeled (BookSim owns network contention)
```

## 6. Proof matrix

| Invariant | Production | Independent reference | Adversarial | Status |
|---|---|---|---|---|
| dependency scheduling | `scheduler.py` | brute-force oracle (§83) | cycle/self/missing dep refused | PROVED |
| exclusive capacity | `scheduler.py` | brute-force oracle | capacity mutation | PROVED |
| bandwidth sharing | `scheduler.py` | independent equal-share walk | staggered/unequal cases | PROVED |
| time-unit conversion | `time.py` | hand-computed exact values | zero/negative clock refused | PROVED |
| makespan | `metrics`/`Schedule` | brute-force optimum | tamper refuses | PROVED |
| critical path | `metrics.critical_path` | hand corpus | tamper refuses | PROVED |
| network-time binding | `network.py` | — | evidence transplant refuses | PROVED |
| compute/memory binding | `scheduler._duration_of` | hand corpus | duration mutation moves IDs | PROVED |
| overlap | scheduler causality | metamorphic tests | hidden-event laws | PROVED |
| request latency | `metrics.request_latencies` | hand corpus | arrival mutation | PROVED |
| sensitivity | `sensitivity.py` | re-run schedules | monotonicity contradiction fails | PROVED |
| identity propagation | every artifact | reconstruction roundtrip | mutation matrix | PROVED |
| result provenance | `wave_e_resources` | re-run schedule | transplant/tamper matrix | PROVED |
| predictive accuracy | — | — | — | **UNCALIBRATED** |

## 7. Attack matrix (all against the real product verifier)

```
makespan tamper                      refused (re-derived)
network_window tamper                refused
fidelity-warning forgery             refused (re-derived)
valid Wave-D chain transplant        refused (not the plan's chain)
valid network-binding transplant     refused (not this run's evidence)
evidence_sha256 tamper               refused
stats_sha256 tamper                  refused
network clock tamper                 refused
backend hash transplant              refused
orphaned timing block                refused
plan citing unknown overlay          refused
overlay citing foreign operation     refused (compile time)
unknown field in the block           refused (schema close)
workload-id transplant               refused
```

## 8. Real product E2E

```
intent(workload.wave_d + workload.wave_e)
  -> compile: persist temporal overlay; verify every declared Wave-D
     operation id exists in the compiled operation graph
  -> plan: bind {temporal_workload_id, performance_model_id}
  -> evaluate: load VERIFIED traffic, run BookSim, bind the network
     window to THIS run's authenticated evidence digest, schedule,
     derive the result block
  -> load_verified_result: re-run the schedule and re-derive every field
```

The demo corpus (`test_wave_e_demos.py`) contains a real certified BookSim
run whose evidence flows through `bind_network_window` into a verified
result, plus the three sensitivity demonstrations (compute-dominant,
network-exposed, overlap) whose conclusions are derived from schedules.

## 9. Calibration

`UNCALIBRATED`. The repository holds no measured per-operation timing
dataset; no synthetic data is manufactured. The fidelity warning inside
every result is re-derived from the verified model, so an accuracy claim
cannot be forged. A calibrated claim would require dataset hash, device
identity, fit parameters, held-out error metrics and a validity domain.

## 10. Comparison compatibility (§119/§120)

The Wave-C comparison gate gains a required `timing_model` dimension
(the verified `performance_model_id`, or `NO_TIMING_MODEL` for an untimed
result). A different clock, resource set, compute source or arbitration
refuses comparison; a different *duration* does not (that is the study).
The variation can be allowed only by declaring it in the contract.

## 11. Regression

From the committed tree (`934f122f`, clean):

```
Wave-E suites (scheduler/identity/demos/product)   165 passed / 1 skipped
Wave-D seal + semantics + physical + authenticity   (with Wave-C below)
Wave-C control plane                                467 passed together
frozen Wave-B focused chain                         747 passed
BookSim goldens                                       6 passed
broad DSE suite      26 failed / 3145 passed / 41 skipped
  failed node IDs vs the pre-Wave-D baseline        IDENTICAL (zero new)
git diff --check                                    clean
```

The 26 pre-existing failures are the environment-dependent ones recorded
before Wave D (gitignored `dse/archive/` + `dse/runs/` assets and unbuilt
vendored binaries); the node set is byte-identical.

Evidence-grade reuse and comparison require a clean tree (sealed Wave-B
producer policy); both were verified from this committed SHA:

```
evaluate twice, same overlay      reused=True, same result id
comparison, different clock       COMPARISON_INCOMPATIBLE (timing_model)
comparison, different duration    comparable (that is the study)
```

## 12. Known limitations

```
per-operation network causality     UNSUPPORTED (BookSim exposes one window;
                                    the event kind refuses at construction)
realized critical path              NOT COMPUTED (dependency chain only, and
                                    named accordingly)
memory latency                      UNSUPPORTED (T = bytes/BW, no hidden zero)
analytical compute                  UNSUPPORTED (declared durations only)
optimal makespan under contention   UNSUPPORTED (declared FIFO, recorded gap)
analytical compute (FLOPs roofline) UNSUPPORTED (no FLOPs model in repo)
memory capacity feasibility         DEFERRED (no residency declarations)
throughput                          UNSUPPORTED (no denominator contract)
continuous batching                 UNSUPPORTED
LLMServingSim / ASTRA / Ramulator   BLOCKED / UNSUPPORTED / NOT_RUN
predictive accuracy                 UNCALIBRATED
area / power / energy, RTL timing   Wave F / Wave G
```
