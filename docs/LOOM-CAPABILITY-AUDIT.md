# Loom capability audit

**Status:** evidence-based ledger, Slice 0 of the Loom implementation plan
**Date:** 2026-10-06
**Branch:** `integration/studio-reconciliation`
**HEAD at audit:** `5e38fdfb` ("docs(open-problems): point the seal entry at the commit that actually closed it")
**Subject:** what the Srota Fabric Compiler and VERITX evidence system can *actually* do today, versus what the reference "Srota Loom" screenshots depict.

Every row below was established by running code at this HEAD. No row is inherited
from a prior audit, README, or screenshot. Where a claim is "READY" it names the
test or probe that proves it; where it is not, it names what is missing.

Status vocabulary:

| Status | Meaning |
|---|---|
| `READY` | Implemented, wired to the product, and proven by a passing test or a live probe at this HEAD. |
| `PARTIAL` | Implemented and wired, but the artifact carries strictly less than the feature needs. |
| `BLOCKED` | Implemented; refuses on this input, with a typed reason. Correct behaviour, not a defect. |
| `UNSUPPORTED` | Declared out of scope by a sealed decision. |
| `BROKEN` | Implemented and wired, and currently fails. |
| `NOT_IMPLEMENTED` | Does not exist. No code, no artifact, no endpoint. |

---

## 0. Baseline: what actually runs at this HEAD

Commands run from the repository root.

### 0.1 Python engine suite

```
PYTHONPATH=tracks/t3-topology/dse:tracks/t3-topology/dse/tests \
  python3 -m pytest tracks/t3-topology/dse/tests -q -p no:randomly
```

**Result: `3 failed, 5627 passed, 25 skipped` in 817.66s.** The baseline is
**red**. It was verified red at HEAD with the working tree stashed, so all three
failures are pre-existing and none are caused by Loom work.

| # | Test | Root cause | Class |
|---|---|---|---|
| B1 | `test_workload_collectives.py::test_collective_vocabulary_has_exactly_one_authority` | `AttributeError: module 'veritx_dse.workload.migration' has no attribute '_WAVED_COLLECTIVE_KINDS'`. Commit `9175f6de` ("debloat sweep") deleted the re-export the test asserts on (`-    COLLECTIVE_KINDS as _WAVED_COLLECTIVE_KINDS,`) but left the test behind. | `BROKEN` (stale test, dead import) |
| B2 | `test_serving_federation_adapter.py::test_bound_valid_experiment_assesses_ready_or_unavailable` | `AttributeError: 'types.SimpleNamespace' object has no attribute 'workload'`. `serving_adapter.py:271` reads `context.workload.participant_count`; the test's `_context()` stub has no `workload` attribute. | `BROKEN` (test stub drifted from the adapter) |
| B3 | `test_closure_phase3_serveproduct.py::test_run_summary_carries_per_analysis_backends` | `503 EXECUTION_FAILED: no qualified backend configured (set VERITX_BOOKSIM_BIN)`. **Environmental** — passes when `VERITX_BOOKSIM_BIN` is exported. Verified. | `BLOCKED` (environment, not code) |

Three further serving tests (`test_planner_selects_serving_for_serving_questions`,
`test_explicit_pin_is_authoritative`) also fail, but only when pytest is invoked
from a CWD other than the repository root; the serving adapter resolves
`third_party/…` paths against `veritx_dse.core.paths.REPO`. CI invokes pytest
from the repo root, so these are a **CWD dependency**, not code defects. Worth
recording because it means the suite is not CWD-independent.

The canonical invocation (from `.github/workflows/release.yml`) is the
repo-root form above. Release CI additionally runs the fast tier with
`-k "not real"`.

### 0.2 Studio frontend

```
cd apps/studio && npx tsc --noEmit     → clean
cd apps/studio && npx vitest run      → 3 files, 46 passed
```

Green, including the 25 Loom derivation contract tests added by this work.

### 0.3 Studio python suite

```
PYTHONPATH=tracks/t3-topology/dse:tracks/t3-topology/dse/tests \
  python3 -m pytest apps/studio/tests -q -p no:randomly
```

**Result: `3 failed, 7 passed, 8 skipped`.** Also verified red at HEAD with the
tree stashed. All three are fixture-drift failures in
`test_studio_contract_v2.py`, all the same assertion: the checked-in fixture
`compiled-mesh.json` carries `design_hash sha256:28ffc…` while
`llama_dense_64tiles-v3.json` now hashes to `sha256:6f015…`. The fixture was not
regenerated after the design document changed. Class: `BROKEN` (stale golden).

### 0.4 Live gateway and browser

Gateway `127.0.0.1:8123` healthy; all three execution backends report `PRESENT`
(`BOOKSIM_STANDALONE`, `ASTRA2_EMBEDDED_BOOKSIM`, `RAMULATOR2_HBM3_V1`).
Vite dev server on `:5173`. Four projects exist; three have compiled revisions
and 16 evaluated runs between them. Loom's 8 tabs verified in Chrome at 1440×900
and iPhone-class widths, dark and light: Lighthouse accessibility 100 on every
tab in both themes, console clean.

### 0.5 Baseline verdict

The engine is **substantially green with three known-red tests, all pre-existing
and all diagnosed**. Loom must not be built on an assumption that the suite is
green, and none of B1–B3 block the Loom vertical slices: B1/B2 are test-fixture
drift in areas Loom does not touch, B3 is an environment variable.

---

## 1. The Srota fabric capability (recently added, and the most important row)

The user reports substantial Srota capability landed recently. **Verified: it is
present at this HEAD, it executes, and it emits real measurements.** Commits
`6711e4c5` (srota_hybrid), `1cce5189` (per-class shape/plane/VC), `f47f2b6d`
(deflection budget + esc_vcs failure), `9815c763` (mixed workload config),
`10349c9e` (per-node injection rates), `d4af98ca` (sweep runner).

`third_party/booksim2/src/networks/srota.cpp` (89 KB) implements a `srota`
topology with MECS express channels, hybrid mesh+express planes, per-class path
shape / plane / VC policy, an O1TURN-XY routing function with an injection-time
congestion overlay, and its own static channel-dependency-graph check.

**Live probe (run at this HEAD, binary `sha256:52150c62…`, then discarded):**

`srota_reference.config` (k=16, c=4 → 1024 tiles, MECS on both dimensions,
two QoS island columns, `srota_vc_policy=rank`):

```
Srota: k=16 c=4 routers=256 tiles=1024 | MECS row=on col=on drop_latency=1 | interior ports out=8 in=34
Srota: max network hops = 2  (TOPO-003 section 3.2 reach guarantee: <=2)
Srota: planes=0x5 (D+T)  plane-D router=iq  islands=0x102 isl_route=any
Srota: ROUTE_PATH_EN=0x7 (row+ col+ valiant+)  vc_policy=rank vc_sets=4/8
Srota F1 CDG check: PASS on the 4x4 abstraction (ROUTE-001 section 4.4).
  256 nodes, 496 edges, no cycle. Shapes enabled: row column valiant | vc_sets=4.
```

`srota_rtr7.config` (the deliberate RT-R7 reproducer, `srota_vc_policy=none`):

```
Srota F1 CDG check: *** CYCLE FOUND *** on the 4x4 abstraction.
  This is ROUTE-001 section 4.5's path-shape mixing hazard (RT-R7),
  reproduced statically.
```

Both exit 0 and emit a full statistics block (`Packet latency average`,
`Hops average`, per-node injection/acceptance minima and maxima, etc.).

**The gap that matters: none of this is reachable from the product.**

| Fact | Evidence |
|---|---|
| `srota` is a BookSim topology | `third_party/booksim2/src/booksim_config.cpp` accepts it; 152 `srota` strings in the binary |
| `srota` is **not** in the compiler's topology enum | `TopologyFamily` at `model/compile_model.py:478` = `MESH, TORUS, CONCENTRATED_MESH, GEC, FAT_TREE, CUSTOM` |
| `srota` is **not** in the authorable intent kinds | `model/topology_intent.py` `AUTHORABLE_INTENT_KINDS`; `capability_truth.GATED_KINDS` has 15 families, none of them `srota` |
| `srota` has **no** BookSim projection profile | `backend/booksim_projection.py` defines 7 profiles (`MESH_DOR_XY`, `CMESH_DOR_XY`, `FLATFLY_MIN`, `TORUS_DOR_XY`, `MESH_DOR_XY_MC`, `MIN_ADAPT_MESH`, `ANYNET_V1`); none renders `topology = srota` |
| `srota` has **no** product route | no gateway endpoint, no preset, no `CompileRequestV4` kind |

**Verdict: `srota` fabric = `READY` in the simulator, `NOT_IMPLEMENTED` in the
product.** A user cannot author it, compile it, verify it, or evaluate it
through Studio. The single highest-value Slice-2+ item is therefore a
`srota` intent kind plus a projection profile, reusing the existing
mesh-DoR profile pattern. This must **not** be faked in the UI: until the
compiler owns the family, Loom must report `srota` as not authorable.

---

## 2. Capability ledger

`Authority` names where the truth lives. "Product" means reachable through
`apps/studio` against the live gateway.

### 2.1 Design intent and revisions

| Capability | Status | Authority | Notes |
|---|---|---|---|
| CompileRequest v3 | `READY` | `model/compile_model.py` `CompileRequestV3` | Legacy shape, still accepted |
| CompileRequest v4 (fabric authority) | `READY` | `model/compile_model.py` `CompileRequestV4`, commit `fdc98e51` | Current authoring seam; `topology_intent` kinds accepted |
| Explicit topology as first-class input | `READY` | `model/topology_intent.py` `ExplicitTopologyIntent`, commit `64c3564c` (FAB-007) | Custom graph + `link_attrs`, strict key rejection |
| Working draft | `READY` | `application/store.py`, gateway `PUT /projects/{id}/draft` | `dirty` flag observed live on `p-09328ea4f00d` |
| Design revision | `READY` | gateway `POST /projects/{id}/compile` → `RevisionView` | 4 revisions exist across 3 projects |
| Revision diff | `READY` | gateway `GET /revisions/{id}/diff` | DESIGN/DERIVED/CAPABILITY changes |
| Draft vs revision staleness | `PARTIAL` | `gateway/staleness.py` | `dirty` is exposed; a *run-vs-current-draft* STALE verdict is not modelled as a first-class object |

### 2.2 System, agents, attachment

| Capability | Status | Authority | Notes |
|---|---|---|---|
| Typed agent kinds | `READY` | `AgentKind` enum, `compile_model.py:191` — 5 members, closed | `compute_tile, hbm_controller, nic, peripheral, ucie_port` |
| Agent interface record | `PARTIAL` | `model/attachment.py` `AgentInterfaceDescriptor` | 5 fields: data width, address width, protocol, clock domain, power domain. **No** AIU type, ordering, splitting, max-outstanding |
| Endpoint attachment | `READY` | `AgentAttachmentArtifact` | Live: 72 endpoints on 81 seats, `attachment_hash` present |
| Per-instance endpoint rows | `READY` | `topology.endpoints[]` | This is the artifact that makes a real 72-row agent matrix possible; Loom now uses it |
| Clock / power domain assignment | `PARTIAL` | authored `clock_domain` / `power_domain` on the agent record | Fields exist and are editable; **every shipped example leaves them null**. Loom derives the census and the crossing list; there is no clock tree, no frequency per domain |
| Address map / decode | `PARTIAL` | `application/address_decode.py`, `compileResult.groups.address_decode` | `address_transform=IDENTITY`, `unmatched_address_policy=ERROR`, `rows: []` on the live design. The draft carries `address_map.ranges: []` |
| Clock-domain crossing derivation | `NOT_IMPLEMENTED` (engine) / `READY` (Loom, derived) | Loom `domainsOf()` | Loom derives crossings from certified seating × authored domain names. The engine does not model crossings at all |

### 2.3 Workload

| Capability | Status | Authority | Notes |
|---|---|---|---|
| Workload catalog | `READY` | gateway `GET /catalog/workloads` | 6 entries, real digests |
| Workload IR / lowering | `READY` | `application/presets.py` `lowering_view`, `workload/` package | Real phase/operation/flow/message counts |
| Collective vocabulary | `READY` | `workload/collectives.py` `COLLECTIVE_KINDS` | Single authority; test B1 is a stale *test*, not a vocabulary split |
| Parallelism (TP/PP/EP/DP) | `READY` | `compileResult.groups.mapping.parallelism` | Live: TP=8, others 1 |
| Rank → endpoint mapping | `PARTIAL` | `compileResult.groups.mapping.rows` | Live: **8 rows** for an 8-rank design, while 72 endpoints are attached. Only the mapped 8 carry TP coordinates |
| Idle-agent accounting | `READY` | `groups.mapping.idle_agents` | Live: 64 declared compute tiles, 8 mapped, 72 attached |
| Profile registry / interpolation | `READY` | `model/family_registry.py`, `performance/model_profile.py`, commit `9175f6de` | Exact-grid + interpolation laws; missing profiles refuse |
| Known-model immutability | `READY` | `application/workload_registry.py` | Named models own fixed architecture metadata |
| Compute-tile internal architecture | `NOT_IMPLEMENTED` | — | No compute-unit / local-memory / accelerator model. A seam is needed before any cycle-accurate accelerator claim |

### 2.4 Topology synthesis

Compiler-derived truth, obtained by running
`veritx_dse.application.capability_truth.derive_all_stages()` at this HEAD. This
is the authoritative, probe-derived table — **not** a hand-written list. Stages:
AUTHORABLE → MATERIALIZABLE → ROUTABLE → VERIFIABLE → PROJECTABLE → EXECUTABLE
→ QUALIFIED → PRODUCT_WIRED.

| Family | Authorable | Materializable | Routable | Verifiable | Projectable | Executable | Qualified | Product-wired | Blocked at |
|---|---|---|---|---|---|---|---|---|---|
| `mesh` | YES | YES | YES | YES | YES | YES | YES | YES | — |
| `concentrated_mesh` | YES | YES | YES | YES | YES | YES | YES | YES | — |
| `flatfly` | YES | YES | YES | YES | YES | YES | YES | YES | — |
| `explicit` | YES | YES | YES | YES | YES | YES | YES | YES | — |
| `gec_express` | YES | YES | YES | YES | YES | YES | YES | YES | — (AnyNet profile) |
| `fat_tree` | YES | YES | YES | YES | YES | YES | YES | **NO** | no shipped preset |
| `fattree` | YES | YES | YES | YES | YES | YES | YES | **NO** | no shipped preset |
| `dragonfly` | YES | YES | YES | YES | YES | YES | YES | **NO** | no shipped preset |
| `qtree` | YES | YES | YES | YES | YES | YES | YES | **NO** | no shipped preset |
| `tree4` | YES | YES | YES | YES | YES | YES | YES | **NO** | no shipped preset |
| `flattened_butterfly` | YES | YES | YES | YES | YES | YES | YES | **NO** | no shipped preset |
| `torus` | YES | YES | YES | **NO** | NO | NO | NO | NO | real preparation path unreached |
| `gec_mesh` | YES | **NO** | NO | NO | NO | NO | NO | NO | GEC-MESH has no canonical materializer |
| `gec_multidrop` | YES | **NO** | NO | NO | NO | NO | NO | NO | no canonical materializer |
| `gec_hybrid` | YES | **NO** | NO | NO | NO | NO | NO | NO | no canonical materializer |
| `srota` | **not a kind** | — | — | — | — | — | — | — | **absent from the compiler** |

Reading the two `NO` clusters precisely, because they are different failures:

- **Six families are complete except for shipping.** They compile, route,
  verify, project, execute and qualify. Only `PRODUCT_WIRED` is `NO`: no preset
  normalizes to them, so a user cannot select one. These are one small,
  low-risk, high-value slice away from full product capability.
- **`torus` is `BROKEN`-shaped.** It materializes and routes, then fails at
  `VERIFIABLE` with `no COMPILED bundle (INVALID): the real preparation path is
  unreached`. A dedicated profile (`CERTIFIED_BOOKSIM_TORUS_DOR_XY_V1`) and
  lowerer (`DORTORUS/1`) exist in `booksim_projection.py`, so the intent was
  carried; the end-to-end path does not currently close.
- **Three GEC modes are `NOT_IMPLEMENTED`** at materialization, by a sealed
  decision: `GEC-MESH degrades to a plain mesh graph`, and multidrop/hybrid have
  no canonical materializer. `gec_express` (AnyNet) is fully working, so GEC is
  partially delivered by design.

Custom/AnyNet topologies are genuinely first-class: `fat_tree`, `dragonfly`,
`qtree` and `tree4` all lower through `TopologyIR` and execute under
`CERTIFIED_BOOKSIM_ANYNET_V1`.

### 2.5 Routing, VC, deadlock

| Capability | Status | Authority | Notes |
|---|---|---|---|
| Routing artifact | `READY` | `core/route_artifact.py`; `GET /revisions/{id}/route` | Probed live: `DOR_XY`, 8 routers for `0→8`, 8 hops with channel ids |
| Route table withheld by design | `READY` | `groups.routing.entries_withheld=true`, `entry_count=6480` | The UI must query `/route`, never receive the table |
| VC assignment | `READY` | `model/compile_model.py` `derive_vc_assignment`, `RouterBehaviorArtifact` | Live: `vc_count=1`, `traffic_class_to_vcs=[["tp_collective",[0]]]`, `vc_to_routing_class=[[0,"DOR_XY"]]` |
| VC-to-traffic-class binding | `READY` | `groups.resources.traffic_class_to_vcs` | Present and populated |
| Router behavior (pipeline, buffers, allocators) | `READY` | `model/router_behavior.py` `RouterBehaviorArtifact` | Pipeline stage cycles, buffer depths, allocator policy, escape VCs all modelled |
| Channel-VC CDG deadlock proof | `READY` | `verification/channel_vc_cdg.py`, method `channel-vc-cdg/v2` | Live: `status PASS`, `acyclic true`, 288 nodes, 508 edges, `sccs_gt_1=0` |
| Escape-VC / adaptive escape | `READY` | `verification/adaptive_escape.py` | `escape_vcs: []` on this design |
| Route observation (first hop) | `READY` | `backend/route_observation.py` | `route_observation: EXECUTED_ROUTE_OBSERVED` on the live run |
| O1TURN-XY + congestion overlay | `READY` (simulator) / `NOT_IMPLEMENTED` (product) | `srota.cpp` `o1turn` | Verified live in the probe above; unreachable from the compiler |

### 2.6 Execution backends

| Backend | Question(s) | Status | Authority / blocker |
|---|---|---|---|
| BookSim standalone | `NETWORK_COMPLETION`, `COMMUNICATION_EXPOSURE`, `PER_RANK_COMPLETION` | `READY` | Live run `01a10cf2…` `EVALUATED`, `BOOKSIM_STANDALONE`, `QUALIFIED`. Real metrics: `completion_cycles=3259`, `packet_latency_avg=1397.7`, `flit_latency_avg=19.741`, conservation verified |
| Embedded BookSim (ASTRA frontend) | `SYSTEM_MAKESPAN` | `READY` | `ASTRA2_EMBEDDED_BOOKSIM` `PRESENT`; qualification profile `ASTRA_COLLECTIVE_V1` |
| ASTRA numerical timing oracle | `SYSTEM_MAKESPAN` timing | `NOT_ESTABLISHED` | `docs/production/ENGINE-QUALIFICATION.json`: ASTRA integration `QUALIFIED`, numerical timing `NOT_ESTABLISHED` until per-domain oracles close. Closed-form ring law added in `prod/production-readiness` |
| Ramulator | `DRAM_TIMING` | `BLOCKED` | `backend/ramulator_adapter.py`. Binary reports `PRESENT`, but `assess()` refuses unless a memory participant can be identified from compute placement. **The correct refusal must be surfaced verbatim** — `COMPUTE_OPERATION_PLACEMENT_REQUIRED`-class reason, never a silent analytical substitute |
| LLMServingSim / serving | `SERVING_TTFT`, `SERVING_COMPLETION` | `PARTIAL` + 2 red tests | `backend/serving_adapter.py` with a real `_runtime_probe`; ASTRA binary present. Test B2 is a drifted stub. Gate is: no bound experiment → `BLOCKED`, never READY |

The evaluation question vocabulary is a closed 7:
`NETWORK_COMPLETION, SYSTEM_MAKESPAN, COMMUNICATION_EXPOSURE,
PER_RANK_COMPLETION, DRAM_TIMING, SERVING_TTFT, SERVING_COMPLETION`
(`application/evaluation_question.py`).

The planner already does the right thing: `EvaluationPlanner.plan()` selects
over a `BackendRegistry` and each adapter returns `support` (`SUPPORTED` /
`CONDITIONAL` / `UNSUPPORTED`) separately from `readiness` (`READY` / `BLOCKED` /
`UNAVAILABLE`), with a reason. **`READINESS ≠ SUPPORT`, and the UI must show
both.** This distinction already exists server-side and is exactly the seam the
capability registry should expose.

### 2.7 Optimization, comparison, serving experiments

| Capability | Status | Authority | Notes |
|---|---|---|---|
| Candidate ledger | `READY` | `optimization/result.py`, `candidate.py` | Failed/infeasible candidates retained; `EVALUATION_FAILED` status exists |
| Pareto front | `READY` | `optimization/pareto.py` | |
| Study runner | `READY` | `optimization/study_runner.py` | |
| Run comparison | `READY` | gateway `GET /compare`, `application/comparison.py` | Probed live. **It refuses**: cross-workload pairs come back `compatible: false`, `NOT_COMPARABLE`, `MODEL DIFFERENCE`, with per-row reasons. Incompatible runs must never be ranked |
| Objective/capability preflight | `READY` | `optimization/capabilities.py`, `capability_probe.py` | Only wired knobs are exposed; `locked_parameters` enumerated |
| Candidate adoption | `READY` | `api.useCandidate` / `optimization/candidate_policy.py` | `PROMOTE TO DRAFT` semantics; does not mutate the source revision |
| Serving experiments | `READY` | gateway `/serving`, `canonical_serving.py` | Needs a bound experiment; `BLOCKED` without one |

### 2.8 Evidence, provenance, reproduction

| Capability | Status | Authority | Notes |
|---|---|---|---|
| Evidence chain | `READY` | `backend/evidence.py`, `groups.provenance.artifact_chain` | Live: design → inventory_mapping → topology → route, each with a hash and the obligation that proves it |
| Run provenance | `READY` | `backend/booksim_execution.py` `backend-evidence.json` | Live evidence carries `binary_sha256`, `build_manifest_sha256`, `config_sha256`, `trace_sha256`, `route_dump_sha256`, `seed`, `parser_version`, `profile_id`, `producer_source_revision`, `producer_dirty`, `resolved_fabric_hash` |
| Conservation | `READY` | `RunIntegrityView` | Packet and flit conservation, `CONSERVED` live |
| Route realization | `PARTIAL` | `route_realization` | **First-hop scope only**, `full_path_claimed: false`. The UI must not present a full observed path |
| Bundle verify | `READY` | gateway `POST /runs/{id}/verify` | |
| Reproduction | `READY` | `backend/reproduce.py`, `reproduce_astra.py` | Per-analysis outcomes; `DIVERGED` is a real verdict |
| Traffic matrix | `READY` | `application/traffic_matrix.py`, gateway `/runs/{id}/traffic-matrix` | Counted from the executed trace, conservation-checked. Live: 8 nodes, 2464 packets, 19600 flits |
| Implementation status | `READY` | gateway `/implementation-status` | RTL / simulation / oracle build strings |
| Validation campaigns | `READY` | gateway `/validation`, `scripts/check_*.py` | Mutations, metamorphic, intervention study |

### 2.9 Physical

| Capability | Status | Authority | Notes |
|---|---|---|---|
| Router coordinates | `READY` | `TopologyRouter.coordinates` | 9×9 live |
| Link adjacency + channel lengths | `PARTIAL` | `TopologyPhysicalLink` | 0 physical links on the live revision; `length_mm` absent |
| Abstract die / area / TDP / metal stack | `NOT_IMPLEMENTED` | — | No PDK, no LEF/DEF, no RC model |
| Congestion / WNS / thermal overlays | `NOT_IMPLEMENTED` | — | No STA or P&R artifact |
| Pipeline-stage retiming closure | `NOT_IMPLEMENTED` | — | `RouterBehaviorArtifact` models stage *counts*; no timing closure |

Loom's floorplan view therefore stays an honest abstract projection. It must not
show die area, TDP, WNS, metal stack, or "TSMC N3E validated".

### 2.10 Generation

| Artifact | Status | Authority | Notes |
|---|---|---|---|
| RTL (SystemVerilog) | `NOT_IMPLEMENTED` | `scripts/rtlgen/gen_rtl.py` **does not exist** | `OutputFormat.SYSTEMVERILOG` is declared in the model and `compile_model.py:1492` names an artifact id `-rtl`, but no emitter exists. `scripts/check_python_deps.py:49` documents the absent helper and the explicit fallback verdict. `flow_certifier.py` has a guarded import |
| UVM testbench | `PARTIAL` | `verification/uvm_gen.py` (486 lines) | A real generator — top, sequences, assertions, coverage — that imports `..model.compile_model` symbols that no longer exist after the v4 refactor, and it is **not wired to the product API** (`grep` finds no reference from `product/` or `gateway/`). Treat as research-grade until it is re-plumbed and product-wired |
| SVA | `PARTIAL` | `uvm_gen.py` `_gen_assertions` | Assertions are emitted as part of the UVM generator; no standalone SVA artifact |
| Routing / config tables | `READY` | `backend/booksim_projection.py` `render_config`, `render_topology_anynet`, route dump | Real, deterministic, product-wired (this is what BookSim executes) |
| Firewall SystemVerilog | `NOT_IMPLEMENTED` | — | Zero occurrences of `firewall` in the engine. The reference screenshot's generated firewall rules have no generator behind them |
| Reports | `READY` | `reports/reports.py` (439 lines), `reports/artifact.py` | |
| Evidence bundle | `READY` | bundle layout under `runs/…/bundle/` | |
| Formal certificate | `NOT_ESTABLISHED` | — | No formal tool in the loop |

---

## 3. Cross-screen inconsistencies found in the reference screenshots

These are properties of the *reference* product. They are recorded because Loom
must not reproduce them, and because several are now provable invariants.

| # | Reference claim | Loom's obligation |
|---|---|---|
| X1 | "64 agents" in one panel, "Showing 64 of 16 Agents" in another | One count source. Loom derives every count from `topology.endpoints` / `groups.mapping`; a contract test asserts table rows equal artifact rows |
| X2 | Agent matrix shows base addresses, `Max OT`, ordering, splitting, access | These are absent from the 5-field agent interface record. Loom lists them under "Not in the contract" rather than showing blanks as zeros |
| X3 | I–T matrix reports 624 paths in the header and 768 in the footer | Derive both or neither. Loom shows `nodes × nodes` from the traffic matrix and refuses to state a path count it cannot compute |
| X4 | Simulation footer says "8x8 Mesh (64 routers)" while Topology shows a pruned express fabric | Loom renders the certified `TopologyView` and labels the source artifact per panel |
| X5 | `Agent_7_6` base address `0x37000_0000` — malformed hex | Address decoding is `PARTIAL` with `rows: []`; Loom shows no address map rather than a malformed one |
| X6 | Topology inspector shows `clk_npu` at 1.4 GHz; agent table shows 1.6 GHz | Every domain is undeclared in all 19 shipped examples. Loom derives its census from the draft and shows `undeclared` |
| X7 | Bisection "6.8 Tbps (theoretical)" vs "2048 Gbps peak bisection" | No bisection artifact exists. Loom must not show either |
| X8 | "3 Planes Validated (Data 512b, Telemetry 32b, Config 32b)" | One topology artifact exists. Loom marks telemetry and config as extension points and never claims validation |
| X9 | `TSMC N3E`, `DRC / Metal Grid: 100% N3E Orthogonal`, per-tile `Area 6.2 mm² / TDP 45 W` | No PDK, no STA, no area model. Loom must show none of it |
| X10 | "Fabric validated (0 address/ID collisions)" and "Zero-Trust rules validated" | No firewall engine exists. Loom must show the access policy as `NOT IMPLEMENTED` |

---

## 4. What the reference has that we do not, classified

| Reference feature | Class | Can it be built from existing capability? |
|---|---|---|
| Per-instance agent matrix (real rows) | `READY` for us | Yes — already built this session from `topology.endpoints` |
| Agent search / sort / column chooser / CSV | `READY` for us | Yes — presentation only |
| IP catalog with 15 IP cards | `NOT_IMPLEMENTED` for us | Partly: a *kind* catalog is honest (5 members); vendor/part/area/power are not |
| Per-agent deep config (AIU, ordering, splitting, max OT) | `NOT_IMPLEMENTED` for us | No — requires an engine contract change |
| Multi-plane telemetry / config fabrics | `NOT_IMPLEMENTED` for us | No artifact exists |
| Clock/power domain manager | `PARTIAL` for us | Census and crossings yes; clock tree, frequencies, SDC/UPF no |
| I–T firewall matrix with permissions | `NOT_IMPLEMENTED` for us | No policy or firewall engine |
| Physical floorplan with area/TDP/timing | `NOT_IMPLEMENTED` for us | Only coordinates and adjacency are real |
| Per-link utilization heatmap | `PARTIAL` for us | BookSim emits **per-node** accepted/injected rates, not per-link. The honest substitute is the derived expected-load walk Loom now ships |
| Cycle scrubber / timeline | `NOT_IMPLEMENTED` for us | BookSim's stdout has no per-cycle series; `print_activity` prints monitor state, not a trace. Must not be faked |
| Wait / arbitration / active latency split | `NOT_IMPLEMENTED` for us | Requires `TRACK_STALLS`, which the build does not define |
| `Generate RTL` | `NOT_IMPLEMENTED` for us | No emitter exists |
| Srota 1024b clustered express fabric | `READY` (sim) / `NOT_IMPLEMENTED` (product) | Highest-value gap: needs an intent kind + a projection profile |
| Topology compare / Pareto | `READY` for us | Server-side compare and Pareto both exist |

---

## 5. Slice 1 conclusions (truth foundation)

1. **A canonical capability registry already exists and is compiler-derived.**
   `application/capability_truth.py` probes the real compiler, profile selector
   and execution handlers for 15 families across 8 stages, with an authority
   string per stage. `scripts/check_capability_truth.py` fails the build if the
   registry claims a capability the compiler does not have. **Loom must read
   this rather than decide capability in React.**
2. **The gateway does not currently serve it.** `/api/v1/capabilities` returns a
   static backend table (`capabilities.py`, 162 lines) with no per-family stage
   truth. Slice 1 must expose `capability_truth` through the product API.
3. **Provenance is mostly there, in pieces.** Evidence hashes, artifact chain,
   parser version, producer revision and qualification profile all exist
   server-side. What is missing is one *value-level* provenance type the UI can
   attach to any displayed number, carrying origin (`AUTHORED` / `DERIVED` /
   `MEASURED` / `DECLARED`), revision, artifact, backend, run, evidence and
   staleness.
4. **Staleness is partial.** `draft.dirty` exists and Loom already reports it.
   A run-vs-current-draft STALE verdict does not exist as a first-class object
   and must be added server-side.
5. **LIVE/DEMO isolation is a real hazard.** `apps/studio/src/fixtures/` holds
   five fixtures, and the offline demo path boots from them. There is no test
   proving a fixture value cannot leak into a live project. Slice 1 must add one.
6. **Three pre-existing red tests** are recorded above. Slice 1 must not make the
   baseline worse, and should report it as red rather than green.

---

## 6. Reproduction

```bash
# baseline python suite (repo root; note the CWD dependency)
PYTHONPATH=tracks/t3-topology/dse:tracks/t3-topology/dse/tests \
  python3 -m pytest tracks/t3-topology/dse/tests -q -p no:randomly
VERITX_BOOKSIM_BIN=$PWD/third_party/booksim2/src/booksim   # clears B3

# studio
cd apps/studio && npx tsc --noEmit && npx vitest run
PYTHONPATH=tracks/t3-topology/dse:tracks/t3-topology/dse/tests \
  python3 -m pytest apps/studio/tests -q

# the compiler-derived family table in §2.4
PYTHONPATH=tracks/t3-topology/dse python3 -c "
from veritx_dse.application.capability_truth import derive_all_stages, GATED_KINDS, STAGES
s = derive_all_stages()
for f in GATED_KINDS:
    print(f, {k: s[f].stages[k] for k in STAGES})"

# the live Srota probe in §1 (run from a scratch dir, then delete)
third_party/booksim2/src/booksim third_party/booksim2/src/examples/srota_reference.config
```