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

## 2. Architecture

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

## 3. Identity DAG (as implemented)

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

## 4. Time / resource contract

```
time          exact rational seconds (numerator/denominator), never floats
clocks        explicit hz, no default 1 GHz; cycles→seconds requires one
resources     EXCLUSIVE (capacity >= 1) | BANDWIDTH (bytes/s > 0)
arbitration   FIFO_SERIAL | EQUAL_SHARE_BANDWIDTH, declared + hashed
network       one BARRIER window per traffic window; links are NOT
              re-modeled (BookSim owns network contention)
```

## 5. Proof matrix

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

## 6. Attack matrix (all against the real product verifier)

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

## 7. Real product E2E

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

## 8. Calibration

`UNCALIBRATED`. The repository holds no measured per-operation timing
dataset; no synthetic data is manufactured. The fidelity warning inside
every result is re-derived from the verified model, so an accuracy claim
cannot be forged. A calibrated claim would require dataset hash, device
identity, fit parameters, held-out error metrics and a validity domain.

## 9. Comparison compatibility (§119/§120)

The Wave-C comparison gate gains a required `timing_model` dimension
(the verified `performance_model_id`, or `NO_TIMING_MODEL` for an untimed
result). A different clock, resource set, compute source or arbitration
refuses comparison; a different *duration* does not (that is the study).
The variation can be allowed only by declaring it in the contract.

## 10. Regression

```
Wave-E suites            111 passed / 1 skipped
Wave-D seal + semantics  (see battery below)
Wave-C control plane
frozen Wave-B chain
BookSim goldens
broad DSE suite          failed-node IDs compared to the baseline
```

## 11. Known limitations

```
per-operation network causality     UNSUPPORTED (BookSim exposes a window)
optimal makespan under contention   UNSUPPORTED (declared FIFO, recorded gap)
analytical compute (FLOPs roofline) UNSUPPORTED (no FLOPs model in repo)
memory capacity feasibility         DEFERRED (no residency declarations)
throughput                          UNSUPPORTED (no denominator contract)
continuous batching                 UNSUPPORTED
LLMServingSim / ASTRA / Ramulator   BLOCKED / UNSUPPORTED / NOT_RUN
predictive accuracy                 UNCALIBRATED
area / power / energy, RTL timing   Wave F / Wave G
```
