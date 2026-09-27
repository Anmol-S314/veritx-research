# EVIDENCE-FIRST CAPABILITY ARCHAEOLOGY

> **What has VERITX already implemented, executed, measured, verified or
> qualified — even when the current canonical product does not expose it?**

Companion (machine-readable, 26 records): `capability-archaeology.yaml`.

This is **not** a feature-development tranche. It exists because the
capability registry answered *"what is canonical?"* and nobody asked
*"what already exists?"* — which is how a real, measured, modified-BookSim
GEC/MECS implementation ended up described as unsupported.

## 0. EVIDENCE ORDER

Source beats prose. For every capability, in this order:

1. executable backend/source implementation
2. experiment scripts and committed result artifacts
3. tests and qualification/evidence code
4. historical branches and commits
5. canonical representation/lowering
6. capability/reclamation registries
7. product/API/Studio exposure

Where two sources disagree, the disagreement is **recorded**, not silently
resolved in favour of the registry.

Inspected historical refs (all present and resolvable):

| Ref | SHA |
|---|---|
| `p1b/verified-evaluation` | `3def89c3a146490a91288210ba6252af51cd8eba` |
| `integration/p1-product` | `b1b6ed5579210a48a4617bb36bb3d82148446f43` |
| `epic/booksim-forward-port` | `e7c66d7ea69d9dabb4a666db1db2165aabb368ae` |

**A note on method.** The PHASE-3.1 audit closed its selected 18-file
weaker-ancestor set correctly, but its *discovery* filter (current blob ==
`integration/canonical` AND strong blob differs) does not cover the whole
scientific execution surface. `simulation/booksim.py` proves it: it did not
satisfy the narrow weak-blob condition, yet its stats parser — consumed by
the **certified** path — had regressed. Discovery by blob identity is
necessary and insufficient; capability discovery must be organised by
capability, not by file.

## 1. THE P0 REGRESSION (FIXED — `f2f3340f`)

`reclaim(booksim): restore honest trace latency parsing`

`veritx_dse/simulation/booksim.py::parse_output` is not a legacy CLI helper:
```
backend/booksim.py::_execute_prepared  -> parse_output   (CERTIFIED path)
backend/meshdor.py                     -> parse_output
application/presets.py                 -> metric mapping ("mean")
```

The stronger lineage (`04d91435`, identical on all three refs) carried:

| Lost semantic | Consequence |
|---|---|
| `honest_avg -> honest_latency` | the comparison CLI and the evidence path prefer `honest_latency`; the parser never produced it, so every consumer silently fell back to the qtime-based plat mean, which inflates on sparse traces |
| `NUM` numeric grammar | `[0-9.eE+\-]+` matches a bare `-`; BookSim prints `= -` for a stat with no samples, and `float("-")` crashed the whole batch |
| `max_packet_latency` | F8 evidence (block-scoped `\tmaximum`, NaN/inf guarded) |
| `TraceStats.max_node` | the PHASE-3.1 `anynet_usability(..., trace_max_node)` precheck could **never** fire without it |
| fail-loud `detect_trace_stats` | it swallowed every exception and returned zeros; a zeroed span sized `sample_period` wrong and measured missing data |

Also reclaimed: **one `BookSimError` identity**. `simulation/booksim.py`
defined its own `BookSimError(Exception)` while `core.errors` defined a
second `BookSimError(VeritXError)` that the certified backend actually
raises — and the CLI caught the local one, so a backend failure fell through
to the generic handler.

Preserved (not replaced): the later current-side drain verdict, delivered
count and flit totals.

**Latency authority, stated once.** The certified evidence path, the mesh-DOR
backend, requirements and report consumers read `latency` (the stock key,
paired with BookSim's own accepted-packet-rate accounting). The comparison
CLI prefers `honest_latency` when the fork emits it. Both are now parsed;
neither is silently substituted for the other.

## 1b. LATENCY METRIC AUTHORITY (FIXED IN THE SEAL PASS)

The parser fix restored `honest_latency`, but the METRIC SCHEMA still filed a
qtime mean and request-time percentiles in one `sim.latency.*` family. The
fork source shows they are different populations:

```
trafficmanager.cpp
trafficmanager.cpp:  _plat_stats[c]->AddSample( f->atime - head->ctime )      <- qtime
trafficmanager.cpp:  _all_latencies[c].push_back( f->atime - <request ts> )   <- request
trafficmanager.cpp:  "Packet latency average = " << _plat_stats[c]->Average()  <- qtime
trafficmanager.cpp:  sorted_lat(_all_latencies[c]) -> p50/p95/p99/honest_avg  <- request
```

Both are emitted **in the same per-class stats block**, which is exactly why a
consumer could read them as one distribution. `booksim-parse/v2` splits them:

| Metric id | Population | Source key |
|---|---|---|
| `sim.latency.avg_cycles` | stock BookSim qtime/ctime (`_plat_stats`) | `latency` |
| `sim.latency.max_cycles` | stock BookSim qtime/ctime (`_plat_stats`) | `max_packet_latency` |
| `sim.trace_request_latency.avg_cycles` | VeritX request time (`_all_latencies`) | `honest_latency` |
| `sim.trace_request_latency.p50_cycles` | request | `p50` |
| `sim.trace_request_latency.p95_cycles` | request | `p95` |
| `sim.trace_request_latency.p99_cycles` | request | `p99` |
| `sim.trace_request_latency.samples` | request | `pkt_count` |

`sim.latency.avg_cycles` is RETAINED for backward compatibility, and its
definition text now states that it is **not the same population** as
`sim.trace_request_latency.*`. The old ambiguous ids
(`sim.latency.p50_cycles`, `.p95`, `.p99`, `sim.packets.count`) are gone —
nothing consumed them. `LATENCY_POPULATIONS` publishes the grouping so a
consumer must choose a population.

**Who reads what (corrected wording).** `backend/booksim.py::
_execute_prepared` parses BOTH keys, **requires** the stock `latency` key and
stores the full stats dict; the certified profile, requirements and report
consumers therefore read the stock key. The comparison CLI prefers
`honest_latency` when the fork emits it. Neither is silently substituted for
the other. (The earlier parser-commit prose said the certified path
"prefers honest latency"; that was inaccurate and is corrected in the
current comments — Git history is not rewritten.)


## 2. CAPABILITY RECORDS

Full structured records are in `capability-archaeology.yaml` (26 records, 13
independent fields each, no collapsed `SUPPORTED` flag). The table below is
the summary; `MISSING_BRIDGE` is the field that matters.

| Capability | Classifications | MISSING_BRIDGE |
|---|---|---|
| BookSim stats parser | CURRENT_CANONICAL, CURRENT_QUALIFIED | none after this tranche |
| GEC-MECS | CURRENT_BACKEND_ONLY, HISTORICAL_EXECUTABLE, HISTORICAL_MEASURED | canonical multidrop resource + route/VC semantics + backend-equivalence qualification |
| GEC-express | CURRENT_BACKEND_ONLY, HISTORICAL_MEASURED, DOC_STALE | canonical materializer + route/VC semantics |
| Torus | CURRENT_BACKEND_ONLY, HISTORICAL_MEASURED, DOC_STALE | canonical route generator + proof/profile for wraparound minimal routing |
| FlatFly | CURRENT_BACKEND_ONLY, HISTORICAL_MEASURED, DOC_STALE | authoring/control-plane bridge + route class + backend profile |
| Fat-tree | CURRENT_BACKEND_ONLY, HISTORICAL_MEASURED, DOC_STALE | canonical representation + qualification (NOT "cfg only") |
| Dragonfly | CURRENT_BACKEND_ONLY, HISTORICAL_MEASURED, DOC_STALE | canonical representation + qualification (NOT "cfg only") |
| QTree | CURRENT_BACKEND_ONLY, DOC_STALE | canonical representation + qualification; execution NOT PROVEN |
| Tree4 | CURRENT_BACKEND_ONLY, DOC_STALE | canonical representation + qualification; execution NOT PROVEN |
| Adaptive routing | CURRENT_BACKEND_ONLY, CURRENT_RESEARCH, HISTORICAL_EXECUTABLE | policy producer + BookSim projection + executed-route observation + qualification |
| Multi-class | CURRENT_BACKEND_ONLY, CURRENT_CANONICAL, HISTORICAL_MEASURED | sound canonical class→VC-subset mapping expressed exactly in a profile |
| Hardware multicast | HISTORICAL_EXECUTABLE, PROTOTYPE_ONLY | reclaim/modernize fork resource semantics + verification |
| Multiplane | CURRENT_RESEARCH, HISTORICAL_EXECUTABLE | first-class simultaneous multi-plane contract |
| P2P + logical multicast | CURRENT_CANONICAL, CURRENT_DOWNSTREAM_ONLY | WorkloadV3 / product intent origination |
| Static MoE | CURRENT_DOWNSTREAM_ONLY, CURRENT_CANONICAL | canonical static MoE dispatch/combine producer (SERVING MoE is separate and is not evidence here) |
| PIM | CURRENT_DOWNSTREAM_ONLY, CURRENT_RESEARCH | canonical intent → PIM execution bridge |
| Ramulator | CURRENT_CANONICAL, CURRENT_DOWNSTREAM_ONLY | NoC/memory coupling + product surface |
| Candidate promotion | CURRENT_CANONICAL, CURRENT_DOWNSTREAM_ONLY | product/API/Studio promotion action |
| Evidence reuse | CURRENT_CANONICAL, CURRENT_DOWNSTREAM_ONLY | cache lookup/orchestration |
| Search completeness | CURRENT_CANONICAL, DOC_STALE | registry/docs reconciliation only |
| Wave-E metrics | CURRENT_CANONICAL, DOC_STALE | registry/docs describe an older missing state |
| NoC energy | CURRENT_RESEARCH, DOC_STALE | canonical fidelity/metric ownership (six estimators must not merge) |
| BookSim native power | CURRENT_BACKEND_ONLY | MECS-aware power accounting |
| RTL validation | CURRENT_RESEARCH | product integration; remains simulation, not proof |
| UVM/SVA | PROTOTYPE_ONLY, CURRENT_RESEARCH | execution/formal authority |
| CDC | CURRENT_RESEARCH, PROTOTYPE_ONLY | canonical multi-clock NoC execution |

### GEC: what was actually added to BookSim

`Network::New` really instantiates `new GEC(config, name)` for
`topology = gec`. The fork adds:

- `MultiDropChannel` / `MultiDropCreditChannel` (`multidropchannel.{hpp,cpp}`)
  — a genuinely shared, tapped wire: one source drives it, N taps receive,
  **one flit in flight per cycle** (inherited from `Channel<T>`'s single
  `_input`/`_output` slot, which *is* the MECS contention model).
- `Flit::drop` (`flit.hpp:82`) — the tap index, set by the routing function
  before the flit reaches the channel; every other tap's `ReceiveAt()` sees
  `NULL` that cycle.
- Per-tap `BufferState`, per-tap credit return, body/tail inheritance of the
  selected drop (`routers/iq_router.cpp`, `routers/router.*`).
- VC sub-ranges partitioned by tap.
- Routing functions: `dor_gec`, `adaptive_xy_yx_gec`, `hybrid_gec`.

The multi-drop header is explicit that wiring one `FlitChannel` into several
routers would *silently broadcast* (double-consumption, pointer reuse) — so
flattening MECS into independent point-to-point edges is **not** an
equivalent model unless equivalence is proven.

**Layer-level answer, not "GEC unsupported":**

| Sub-family | Representable as ordinary directed channels? |
|---|---|
| `GEC_MESH` | YES — lowers directly through ordinary mesh channels |
| `GEC_EXPRESS` | YES — express links are ordinary p2p directed channels |
| `GEC_MECS` | **NO** — needs a new shared/multidrop physical resource |
| `GEC_HYBRID` | NO — selects between mesh and MECS per hop, so it inherits the MECS resource gap |

### Routing functions actually registered

`routefunc.cpp` / topology files register: `dim_order_{mesh,torus}`,
`dor_mesh`, `xy_yx_mesh`, `adaptive_xy_yx_mesh`, `min_adapt_{mesh,torus}`,
`limited_adapt_mesh`, `planar_adapt_mesh`, `romm_mesh`, `romm_ni_mesh`,
`valiant_{mesh,torus}`, `valiant_ni_torus`, `chaos_{mesh,torus}`,
`dim_order_bal_torus`, `dim_order_ni_*`, `dim_order_pni_mesh`,
`nca_{fattree,qtree,tree4}`, `anca_{fattree,tree4}`, `dest_tag_fly`,
`dor_{cmesh,no_express_cmesh}`, `xy_yx_{cmesh,no_express_cmesh}`,
`ran_min_flatfly`, `xyyx_flatfly`, `ugal_flatfly`, `ugal_pni_flatfly`,
`ugal_xyyx_flatfly`, `valiant_flatfly`, `adaptive_xyyx_flatfly`,
`min_dragonflynew`, `ugal_dragonflynew`, `min_anynet`, plus the VeritX
extensions `matrix`, `trace`, `snake_mesh`, `yx_mesh`.

The canonical side already models the *concepts*: `RoutingPolicyDefinition`
carries `DecisionScope.PER_HOP`, `CandidateMode.CANDIDATE_SET`,
`SelectionLocus.ROUTER_ALLOCATOR`, an RNG mode, output-credit observation,
and `RoutingResourceRoleKind.{ADAPTIVE,ESCAPE,PHASE,TAP}`, with
`verification/adaptive_escape.py` holding the escape-subfunction proof
obligation. Adaptive routing is therefore **not conceptually absent** — the
missing bridge is the producer/projection/qualification chain, not the model.

### Hardware multicast

Three separate concepts, never collapsed:

| Concept | Status |
|---|---|
| LOGICAL SOURCE REPLICATION | CURRENT_CANONICAL — typed workload ops, lowers to unicast |
| HISTORICAL HARDWARE FLIT-FORK | HISTORICAL_EXECUTABLE — `archive/booksim-ext/multicast.patch` (300 lines) adds `mcast_k`/`mcast_naive`/`reduce_col`/`bcast_all` and modifies Flit/IQRouter/TrafficManager; row-broadcast experiments ran |
| CURRENT HARDWARE MULTICAST PRODUCT CONTRACT | absent |

`tracks/t3-topology/product/examples/multicast.json` has **no consumer
anywhere in the tree** (grep across `.py`/`.ts`/`.tsx`). A JSON example is not an executable capability.

### Multiplane

`plane_*.cfg` + `scripts/research/plane_separation.py` exist, and per-plane
latency/VC/express studies ran. The separate-plane arm executes the planes as
**independent runs**. That is recorded as research, not promoted to a
canonical simultaneous multi-plane fabric — and not called absent either.

### PIM

`third_party/llmservingsim/serving/core/{pim_model,power_model}.py` contain
real PIM latency/power models that execute inside LLMServingSim. The
canonical side has PIM graph markers, and ASTRA treats those markers as
**zero network traffic**. A zero-traffic marker is not PIM simulation, and
no bridge currently connects canonical PIM intent to the LLMServingSim model.

### Energy: six quantities, never one

| Estimator | Fidelity class |
|---|---|
| early `hops × packet_size` proxy | proxy |
| Accelergy/Timeloop tool-derived energy | tool-calibrated (accelerator side) |
| `tracks/t3-topology/scripts/noc_energy_bridge.py` | Accelergy-calibrated pJ/hop |
| `reports/reports.py` analytical estimates | analytical, estimate-not-sign-off |
| BookSim native `Power_Module` | backend activity-based |
| LLMServingSim power model | downstream model |

**MECS check (mandatory):** `Power_Module` iterates
`Network::GetChannels()` / `_chan`. GEC MECS stores shared links in
`_md_chan` (`network.cpp` deletes `_md_chan_cred[c]` in its own loop, i.e.
they are a separate container). Therefore:

> `BOOKSIM_NATIVE_POWER_FOR_MECS = INVALID/INCOMPLETE` until multidrop-channel
> activity is included. It must never be silently used for GEC-MECS.

### Optimization / synthesis primitives that already exist

| Primitive | Where | Registry said |
|---|---|---|
| `SearchCompleteness` + `OptimizationResult.completeness` (EXHAUSTIVE/BUDGETED/UNBOUNDED, result-bound) | `optimization/completeness.py` | described as absent |
| `promote_to_explicit_topology` / `apply_promotion_to_request_doc` + `test_candidate_promotion.py` | `synthesis/candidate.py` | described as needing canonicalization |
| `verify_reusable_record` / `read_reusable_record` (digest/schema/binary/profile safe) | `backend/evidence.py` | described as unreclaimed |
| makespan / critical path / request-latency mean / resource-utilization max | `optimization/metric_registry.py` | described as older missing state |

In each case the **primitive** exists; what is missing is **orchestration**
and **product wiring**. For evidence reuse specifically: a safe
reuse-*verification* API is not a cache that discovers and reuses evidence.
For promotion: a correct promotion primitive is not a Studio/API action.

## 3. REGISTRY CLAIMS THAT DO NOT MATCH EXECUTABLE EVIDENCE

| Document | Exact current claim | Evidence contradicting/narrowing it | Correct replacement wording | Change |
|---|---|---|---|---|
| `topology-family-registry.yaml` (torus) | `PROJECTABLE: "NO", EXECUTABLE: "NO"` | `Network::New` instantiates `KNCube(config,name,false)` for `topology = torus`; `dim_order_torus`/`min_adapt_torus`/`valiant_torus` registered; `torus_8x8 (dim_order)` measured at 1872.47c/62451.80c/374.61c | `PROJECTABLE/EXECUTABLE: "NO (canonical path)"; BACKEND: "YES — BookSim KNCube, measured 2026-08-29"` | code+docs |
| `topology-family-registry.yaml` (gec) | `PROJECTABLE: "PARTIAL", EXECUTABLE: "NO"` | `gec_express` 1857.69c and `gec_mecs` 1906.87c rows are committed measurements | split into sub-family rows with `BACKEND_EXECUTABLE: YES` | code+docs |
| `topology-family-registry.yaml` (flatfly) | `MATERIALIZABLE: "YES", ROUTABLE: "NO", EXECUTABLE: "NO"` | an internal flatfly materializer exists **and** `flatfly_64 (ran_min)` measured 1922.73c | `BACKEND_EXECUTABLE: "YES"`; ROUTABLE stays NO (no canonical class) | docs |
| `topology-family-registry.yaml` (fat_tree, dragonfly, qtree, flattened_butterfly) | `MATERIALIZABLE: "NO", PROJECTABLE: "PARTIAL"` | concrete C++ networks instantiated by `Network::New`, with registered routing functions | add `BACKEND_IMPLEMENTATION: "YES — networks/*.cpp"` alongside `MATERIALIZABLE: NO` | docs |
| `capability-registry.yaml` / `CAPABILITY-MATRIX.md` (search completeness) | described as absent/unreclaimed | `optimization/completeness.py` + `test_search_completeness.py` | `CURRENT_CANONICAL; missing = orchestration/product wiring` | docs |
| `feature-reclamation-registry.yaml` (Wave-E metrics) | described as unreclaimed | `optimization/metric_registry.py` registers the four metrics | `CURRENT_CANONICAL; missing = registry/doc reconciliation` | docs |
| `feature-reclamation-registry.yaml` (candidate promotion) | needs canonicalization | primitive + `test_candidate_promotion.py` exist | `primitive CURRENT_CANONICAL; missing = product wiring` | docs |
| `FEATURE-RECLAMATION-AUDIT.md` / `-AMENDMENT.md` (evidence reuse) | unreclaimed | `verify_reusable_record`/`read_reusable_record` exist | `primitive CURRENT_CANONICAL; missing = cache orchestration` | docs |
| `FEATURE-RECLAMATION-AUDIT.md` (P2P / logical multicast) | "no contract" | typed ops in `workload/{operations,graph,messages}.py` | `CURRENT_CANONICAL downstream; missing = intent origination` | docs |
| `FEATURE-RECLAMATION-AMENDMENT.md` (hardware multicast) | historical-parity wording | `archive/booksim-ext/multicast.patch` is executable historical implementation, currently unapplied | `HISTORICAL_EXECUTABLE, not applied; not TRULY_ABSENT` | docs |
| `capability-registry.yaml` (BookSim stats parser) | (not modelled) | the certified path consumes it | add as a capability row | docs |

Per the work order, `capability-registry.yaml` is **not** edited in this
tranche. The audit comes first; every row above is unambiguous enough to
change later, and none of them redefines product semantics.

### Measurement claims corrected in the seal pass

An independent audit found `MEASURED_ANYWHERE = YES` claims that exceeded the
committed evidence. All four are corrected in the ledger, and a structural
test now enforces the law for **every** record (not only `HISTORICAL_MEASURED`):
a script or implementation file proves executable POTENTIAL, never MEASURED.

| Record | Was | Now | Why |
|---|---|---|---|
| Fat-tree/QTree/Tree4/Dragonfly | `MEASURED_ANYWHERE: YES — full_topology_comparison.xlsx` | `YES IN HISTORY`, commit-qualified | the workbook **was** found — at `6a335004:booksim2/full_topology_comparison.xlsx` (20,725 bytes), not at HEAD and not on the three audited refs (it lived under `booksim2/`, not `third_party/booksim2/src/`). The script alone would only prove executable potential. |
| Static MoE | `MEASURED_ANYWHERE: YES — serving MoE traces exercise dispatch/alltoall` | `NO CONFIRMED STATIC-MOE MEASUREMENT`; `EXECUTED_ANYWHERE: TESTED LOWERING` | serving MoE is a **different path**; its measurements are not evidence for the static-MoE producer. Only construction/lowering tests exist. |
| P2P + logical multicast | `MEASURED_ANYWHERE: YES — via lowered traffic in BookSim runs` | `NOT PROVEN` | no committed measurement tied to a canonically originating P2P/logical-multicast operation was located. The lowering is real; the measurement axis is not established. |
| Hardware multicast | `EXECUTED_ANYWHERE: YES`, `MEASURED_ANYWHERE: YES` | `YES IN HISTORY`, commit-qualified | a patch proves an implementation prototype, not execution. Execution/measurement evidence exists **in history** (`90da38ff` added `mcast_measured.py`; comm status/decision records at `c41087b1`/`973ee7bd`), and the scripts were removed and the patch unapplied at HEAD. |

Records now carry an optional `historical_evidence:` list, whose entries must
be commit-qualified (`<sha>:<path>`), so a claim that is true only in history
can be re-found rather than taken on trust.

### Execution claims corrected (seal pass 2)

The same discipline now applies to `EXECUTED_ANYWHERE`. A source file or a
runnable script proves **executable potential**, never **executed**. Every
`EXECUTED_ANYWHERE = YES` must cite durable run evidence: a committed result
artifact, evidence document, or a commit-qualified status/result record.

| Record | Was | Now |
|---|---|---|
| Adaptive routing | `YES IN HISTORY` (no artifact) | `EXECUTABLE POTENTIAL — NOT PROVEN EXECUTED` |
| PIM | `YES — inside LLMServingSim serving runs` | `IMPLEMENTED AND CALLABLE — EXECUTABLE POTENTIAL; NO PIM SERVING RUN PROVEN` |
| P2P + logical multicast | `YES — typed ops lower…` | `TESTED LOWERING — NO BACKEND RUN PROVEN` |
| Candidate promotion / evidence reuse / search completeness / Wave-E metrics | `YES` | `TESTED PRIMITIVE — exercised in-process by committed tests; no durable external run artifact` |
| NoC energy | `YES — runnable research script` | `EXECUTABLE POTENTIAL` |
| BookSim native power | `YES when sim_power=1` | `EXECUTABLE POTENTIAL` |
| RTL validation | `YES — the harness builds and runs RTL` | `EXECUTABLE POTENTIAL` (the committed RTL document is a read-through audit, not a run record) |
| CDC | `YES (component-level)` | `EXECUTABLE POTENTIAL` |
| BookSim stats parser | `YES` (no citation) | `YES` + cites `BAKE-OFF-REPRODUCIBILITY.md` (verified latencies: mesh_8x8 23.38c, custom_anynet 23.20c, flatfly_8x8 20.38c) |

### `6a335004` — disposition

The combined topology record cited `6a335004:booksim2/full_topology_comparison.xlsx`.
Independent verification could not resolve that commit on
`Anmol-S314/veritx-research`: the object is contained only by
`origin/updated-booksim` (the **internal** remote), not by any GitHub ref.

The workbook is genuine and detailed (Excel 2007+, 20,725 bytes, sheets
*Report* + *All Runs*, per-topology rows for Mesh/MECS/Hybrid/CMesh/Flatfly/
**Fat-tree**/**Dragonfly**/**Torus**). It was therefore made durable rather
than discarded:

```
refs/heads/archive/topology-comparison-2026-08
  -> 6a3350048c646b0ea9f738f0bff889fbfcf6a753
```

pushed to GitHub and verified remotely. All historical citations now use
**full 40-character SHAs**, and a structural test fails if any cited SHA is
unreachable from every ref (a dangling object is not repository evidence).

### Fat-tree / Dragonfly / QTree / Tree4 — split

The previous combined record cited `run_full_comparison.py` as execution
evidence for all four. That script runs CMesh, Flatfly, Fat-tree, Dragonfly
and Torus — **not QTree or Tree4** — and the comparison workbook has no QTree
or Tree4 rows. The record is split:

| Record | Implementation | Execution | Measurement |
|---|---|---|---|
| Fat-tree | YES | YES IN HISTORY | YES IN HISTORY (`6a335004…:booksim2/full_topology_comparison.xlsx`) |
| Dragonfly | YES | YES IN HISTORY | YES IN HISTORY (same workbook) |
| QTree | YES | EXECUTABLE POTENTIAL — NOT PROVEN | NOT PROVEN |
| Tree4 | YES | EXECUTABLE POTENTIAL — NOT PROVEN | NOT PROVEN |

Implementation remains YES for all four — they are concrete C++ networks
instantiated by `Network::New`. Only the evidence axis was overstated.

## 4. NEGATIVE EVIDENCE — search scope for TRULY_ABSENT

No capability in this ledger is classified `TRULY_ABSENT`. Where a
capability is missing, the missing layer is named. For any future
`TRULY_ABSENT` claim the search must cover: current canonical code, backend
source, legacy CLI, research scripts, `archive/`, historical branches,
tests, and committed results. Absence from one registry is not evidence of
absence.

Concrete negative findings recorded here (each with the scope searched):

- `product/examples/multicast.json` — searched all `.py`/`.ts`/`.tsx` for
  `multicast.json`; **no consumer**. Not executable capability.
- `noc_energy_bridge` — not in `veritx_dse/`; it is
  `tracks/t3-topology/scripts/noc_energy_bridge.py`. A path-based search of
  the package would have wrongly reported it absent.
- No canonical multidrop physical resource exists — searched
  `model/topology_artifact.py`, `core/route_artifact.py`,
  `model/topology_ir.py` for a shared/tapped channel concept.
- No simultaneous multi-plane fabric contract — searched `model/`,
  `compiler/`, `backend/` for a plane-set contract.

## 5. TOP 10 MISSING BRIDGES BY IMPACT

1. **Canonical multidrop physical resource (GEC-MECS)** — unblocks a
   measured, best-in-class attention result; requires a real shared-channel
   concept, not fake p2p edges.
2. **MECS-aware BookSim power accounting** — native power silently ignores
   `_md_chan`, so any MECS energy number today is invalid.
3. **Canonical route generator + proof/profile for torus wraparound** —
   `MaterializedFamily.TORUS` already materializes; only the route class and
   profile are missing.
4. **Adaptive-routing producer → BookSim projection → executed-equivalence
   qualification** — the canonical model exists; the chain does not.
5. **Canonical class→VC-subset mapping expressed exactly in a profile** —
   multi-class execution exists; exactness is only partially qualified.
6. **Product intent origination for P2P / logical multicast / static MoE** —
   representations exist downstream; users cannot originate them.
7. **Canonical intent → PIM execution bridge** — real PIM models exist in
   LLMServingSim; ASTRA currently sends zero traffic for PIM markers.
8. **Canonical fidelity ownership for NoC energy** — six estimators, no
   fidelity class on the metric; the risk is merging them.
9. **Product wiring for candidate promotion and evidence reuse** — both
   primitives are canonical and tested; neither is reachable from the
   product.
10. **UVM/SVA execution or formal authority** — a generator is not
    verification; generated SVA is not proven.

## 6. CLASSIFICATION COUNTS

Counted over **these 26 audited records** (a record may carry several
classifications). Counts are OUTPUTS of the records, not targets.

| Classification | Records |
|---|---|
| CURRENT_CANONICAL | 9 |
| CURRENT_QUALIFIED | 1 |
| CURRENT_BACKEND_ONLY | 11 |
| CURRENT_DOWNSTREAM_ONLY | 6 |
| CURRENT_RESEARCH | 7 |
| CURRENT_LEGACY_EXECUTABLE | 0 |
| HISTORICAL_EXECUTABLE | 4 |
| HISTORICAL_MEASURED | 7 |
| PROTOTYPE_ONLY | 3 |
| DOC_STALE | 10 |
| TRULY_ABSENT | 0 |

### Classification semantics

A classification must have mechanical meaning. The exact definitions live in
`capability-archaeology.yaml:classification_definitions` and are enforced by
test. The load-bearing one:

> **CURRENT_CANONICAL** — the capability has a current canonical VERITX
> representation or primitive that **participates in the canonical authority
> model** (an identity owner, a sealed artifact, a registered authority, a
> typed contract other canonical code derives from). It does **not** mean
> merely "the source file is currently in the repository".

Applied to the three records that previously contradicted themselves:

| Record | Was | Now | Why |
|---|---|---|---|
| NoC energy | CURRENT_CANONICAL (with `CANONICAL_REPRESENTATION: PARTIAL`) | CURRENT_RESEARCH, DOC_STALE | six estimators, no canonical metric authority, no fidelity class |
| RTL validation | CURRENT_CANONICAL (with `CANONICAL_REPRESENTATION: N/A`) | CURRENT_RESEARCH | current and executable, but a validation harness is not canonical product science |
| UVM/SVA | CURRENT_CANONICAL (with `CANONICAL_REPRESENTATION: N/A`) | PROTOTYPE_ONLY, CURRENT_RESEARCH | a generator is not a canonical verification authority |

A structural test now forbids `CURRENT_CANONICAL` with
`CANONICAL_REPRESENTATION` of `NO` or `N/A`, and requires `PARTIAL` to name
the canonical portion that exists.

### TRULY_ABSENT scope law

> `TRULY_ABSENT = 0` means **none of these 26 audited records satisfied the
> strict TRULY_ABSENT definition**. It does **not** mean "VERITX has no
> absent capabilities."

`CURRENT_LEGACY_EXECUTABLE` is 0 because the legacy CLI is *covered* by the
`CURRENT_BACKEND_ONLY` records it exercises (the old compare path is the
live route to GEC/Torus/FlatFly execution); it is not a separate capability.
"Unsupported" is not used as a sole classification anywhere in this audit.

## 7. WHAT WAS NOT DONE

Per the work order: no new topology materializers, no torus routing, no new
adaptive algorithms, no multidrop canonical resource, no hardware multicast,
no multiplane, no PIM/Ramulator product wiring, no new optimizer dimensions,
no new RTL. Only the confirmed BookSim stats-parser regression was fixed.
