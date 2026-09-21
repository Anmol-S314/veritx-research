# Fabric Compiler Authority (P1.0 audit)

P1 starts with promotion and unification, not greenfield. This document
classifies every existing compiler-related type as AUTHORITATIVE / IR /
POLICY / BACKEND PROJECTION / RESEARCH / DUPLICATE / LEGACY /
BROKEN-INCOMPLETE, states the actual pipeline, and answers: **which
exact object owns each resolved fabric semantic — with no duplicate
answer.**

All claims below were verified by reading code (P1.0 audit, three
parallel surveys + direct reads of `model/compile_model.py`).

## 1. The actual pipeline (as built, not as diagrammed)

The live product compiler is `application/compile.py:compile_bundle`
— strict ordered orchestration, derives no semantics itself, returns
a `ResolvedFabricBundle` (in-memory proof carrier, never persisted):

```text
CompileRequest (E1–E5 intent)
      ↓ validate_request (fail-closed parsing)
build_inventory()            → NodeInventory
derive_mapping()             → MappingArtifact
materialize_topology()       → TopologyArtifact        (mesh/torus/cmesh)
derive_attachment()          → AgentAttachmentArtifact
RouteArtifact.from_topology  → RouteArtifact           (ANYNET_MIN_HOPS)
derive_resolved_route()      → ResolvedRouteArtifact
derive_vc_assignment_artifact() → VCAssignmentArtifact (via compile_model)
derive_packet_format()       → PacketFormatArtifact
derive_router_behavior()     → RouterBehaviorArtifact
derive_address_decode()      → AddressDecodeArtifact
make_fabric_artifact()       → FabricArtifact          (hardware root)
make_resolved_fabric()       → ResolvedFabric          (design+mapping seam)
make_resolved_fabric_bundle  → ResolvedFabricBundle    (revalidated carrier)
      ↓
P0 canonical path: WorkloadGraph → Messages → Mapping → Traffic
      → BookSim → Evidence → PerformanceResult
```

Product entry: `veritx service compile` / `veritx api compile`
(`cli/service_cli.py` thin adapter → `SrotaControlPlane.compile`).
Gates on this path: `assert_workload_ready` + `verify_packetization_reference`
pre-spawn, `verify_backend_quiescence` post-drain. There is **no**
`srota compile` command yet.

The legacy pipeline (`veritx legacy compile`, BLOCKED) runs
`verify_design` F1–F8 + `generate_artifacts` + UVM/RTL registration.
`veritx legacy synthesize-compile` runs the candidate evaluator
(§4). `veritx generate uvm` is the only live `generate` subcommand
(no RTL subcommand exists).

## 2. Ownership table (one semantic, one owner)

| Semantic | Owner | Identity |
|---|---|---|
| design intent (E1–E5) | `model/compile_model.py:CompileRequest` | `design_hash()` (Wave B1) |
| workload intent (Level A/B) | `compile_model.Workload` | inside design_hash |
| executable workload semantics | `workload/canonical_graph.py:WorkloadGraph` (P0) | `workload_id()` |
| binding/perf requirements | `compile_model.Requirement` | inside design_hash |
| protocol dependencies | `compile_model.DependencyGraph` | inside design_hash |
| rank geometry (sealed) | `model/placement.py:ParallelismShape` | none (algebra) |
| hardware+rank universes | `model/placement.py:NodeInventory` | none (derivation sources) |
| rank → agent | `model/mapping.py:MappingArtifact` | `mapping_hash()` |
| fabric graph (routers/channels/seats) | `model/topology_artifact.py:TopologyArtifact` | `topology_hash()` |
| agent → endpoint/router seat | `model/attachment.py:AgentAttachmentArtifact` | `attachment_hash()` (binds topology_hash) |
| router-level routes | `core/route_artifact.py:RouteArtifact` | binds topology_hash |
| endpoint×endpoint×class routes | `model/resolved_route.py:ResolvedRouteArtifact` | binds topology+attachment+router hashes |
| VC structure | `model/vc_assignment.py:VCAssignmentArtifact` | binds resolved_route_hash |
| wire bits / packetization | `model/packet_format.py:PacketFormatArtifact` | binds topology+attachment+VC hashes |
| router behavior | `model/router_behavior.py:RouterBehaviorArtifact` | binds VC hash |
| address → endpoint decode | `model/address_decode.py:AddressDecodeArtifact` | binds attachment_hash |
| hardware root | `model/fabric_artifact.py:FabricArtifact` | `fabric_hash()` (7 child hashes) |
| design-bound root | `model/resolved_fabric.py:ResolvedFabric` | design+mapping+fabric hashes |
| backend evidence | `backend` Evidence + `EvidenceArtifact` (P0/M1.4) | evidence_id |
| performance claims | `performance`: PerformanceModel/TemporalWorkload/Schedule/PerformanceResult (P0) | content ids |

## 3. Classification

### AUTHORITATIVE (belong in the final compiler)

`CompileRequest`, `Workload` (modulo §6), `Requirement`,
`DependencyGraph`, `Agent`, `AddressMap`, `NocConfig`,
`PhysicalContext` (modulo §6), `NodeInventory`,
`MappingArtifact`, `TopologyArtifact`, `AgentAttachmentArtifact`,
`RouteArtifact`, `ResolvedRouteArtifact`, `VCAssignmentArtifact`,
`PacketFormatArtifact`, `RouterBehaviorArtifact`,
`AddressDecodeArtifact`, `FabricArtifact`, `ResolvedFabric`,
`ResolvedFabricBundle` (in-memory carrier), the P0 chain
(WorkloadGraph → Evidence → PerformanceResult).

`NocConfig` is correctly shaped: GUIDED + FREE only, no fields for
routing/turns/VCs — correctness-critical parameters are
structurally inexpressible, not merely refused. Do not redesign.

### IR (legitimate intermediate representation)

- `model/topology_ir.py:TopologyIR` — backend-neutral interchange +
  translators. NO content hash, NOT used by `compile_bundle`. Keep as
  authoring/interchange; never let it become a second authority.
- `synthesis/results.py:SynthResult` — merge schema for optimizer outputs.
- `core/memory.py:MemoryArtifact` — adjacent domain, fine.

### POLICY (candidate-generation / selection logic)

- `NocConfig` GUIDED knobs (family/radix/concentration/link-width/…).
- `model/presets.py` — authoring registry + workload presets. Input-side only.
- `synthesis/compiler.py` request fields (search accounting, §4).

### BACKEND PROJECTION (BookSim/ASTRA/etc only)

- `compile_model.derive_topology_spec` — artifact → preset bridge
  (square-grid assumption; RING→torus wart; see §7).
- `TopologyIR` translators (`to_booksim_cfg`, …).
- `synthesis/evaluator.py` BookSim measurement leg (the ONE shared one).
- `verification/uvm_gen.py` — takes `CompileRequest`; should
  eventually take `ResolvedFabricBundle`.

### RESEARCH (useful algorithm, not production authority)

- `synthesis/bo_synthesizer.py`, `iterative_synthesizer.py`,
  `milp_topology_v2.py`, `event_objective.py` — standalone optimizers;
  reach product only via results files through the bridge.
- `tools/deadlock_routing.py` — capability mine (MCLB, escape,
  BookSim-exact replica; "not part of the supported CLI surface").
  Extract semantics into typed modules; keep the script a wrapper.
- `tools/flow_certifier.py` — same status (imports tables/CDG from
  `scripts/rtlgen/gen_rtl.py`, itself a fourth CDG copy).
- `scripts/rtlgen/gen_rtl.py` — mature 2-VC RTL generator, OUTSIDE
  the package. Audit before reuse; do not rewrite.

### DUPLICATE (competing representation — resolve in P1)

1. **Three topology owners:** `presets.Topology` (backend strings) vs
   `TopologyIR` (interchange) vs `TopologyArtifact` (hashed truth).
   Only mesh/torus/ring bridge all three.
2. **Two rank-geometry owners:** `placement.ParallelismShape`
   (sealed) vs `model/parallelism.py:ParallelismArtifact` (Wave-D
   groups wrapper) + three world-size spellings. P1: groups derive
   from Shape or the wrapper goes.
3. **Two classes named `FabricArtifact`:** `model/` (hashed hardware
   root) vs `core.fabric` (legacy executed-evidence object).
   Rename pending (B3.7 noted); P1 should do it.
4. **Two VC owners:** `compile_model.VCAssignment` (legacy derivation
   incl. routing-function strings) vs `VCAssignmentArtifact`
   (hashed truth; `derivation` string is the bridge).
5. **Two routing vocabularies:** hashed `RoutingClassDefinition`
   ids vs unhashed strings (`dim_order`/`dor`/`min_adapt`, preset
   `routing`, IR `DEFAULT_ROUTING`). Legacy strings play no role in
   identity — keep it that way; delete the strings where unreferenced.
6. **Two behavior-knob copies:** hashed `RouterBehaviorArtifact`
   vs `topology_ir.BOOKSIM_DEFAULTS` (same numbers, no code link).
7. **Bound copies:** `endpoint_to_router` pairs stored in both
   attachment and resolved-route; semantic entry tuples in both
   design map and decode. Drift surfaces only at `validate_against`
   — acceptable, but the copies must never be edited independently.
8. **Deadlock proved 4 ways:** `channel_vc_cdg` (strongest: typed,
   (channel,VC)-granular — UNWIRED, test-only) vs
   `deadlock_routing` physical-channel CDG (legacy subprocess,
   VC-blind) vs `flow_certifier` (third path via gen_rtl tables) vs
   F1 abstract-cycle (ASSUMPTION). P1.6 wires (8) and retires the rest.

### LEGACY (historical compatibility — read, never extend)

waved*/opgraph readers (frozen, M4), `waveeworkload` kind (readable,
M6), `core.fabric.FabricArtifact` (until renamed), legacy CLI
(`compile`, `certify-*`, `api-export`, `synthesize-compile` flow),
`api.compile_fabric` (Wave-C.1 legacy-internal), `Workload.total_npus`
alias, `DEFAULT_ROUTING_CLASS` compat alias.

### BROKEN / INCOMPLETE (concept valid, implementation insufficient)

- **`Workload.trace_path` enters `design_hash` as a PATH STRING**
  (`_workload_dict`). A reproducible request cannot mean "load
  whatever bytes live at this path". P1: ingest to a content-hashed
  source artifact; reference `trace_artifact_id` /
  `WorkloadSourceRef(content_sha256, format, size, provenance)`.
  CLI keeps `--trace foo.trace` (ingest at the boundary).
- **`derive_vc_count` yields a COUNT, not an assignment**, and
  documents the missing overlap analysis itself. P1.5 builds the
  CDG→SCC→allocation→reprove pipeline ending in
  `VCAssignmentArtifact` with per-VC rationale.
- **`verify_design` honesty gaps:** F1 is abstract-cycle with a VC
  ASSUMPTION (full claim needs the (channel,VC) certificate);
  F4/F5 are assumption/mechanism; F7 unimplemented; UVM F1/F4–F7
  assertions are `1'b1` tautologies. Keep the PASS/FAIL/NOT_RUN/
  ASSUMPTION vocabulary; wire real evidence per obligation (P1.6).
- **`derive_topology_spec` assumes square grids** (`k*k`, refuses
  otherwise) and maps RING→torus backend. Fine for the mesh MVP;
  must not generalize silently.
- **`TopologyFamily` breadth ≠ certification:** GEC/fat-tree refused
  by the materializer (correct scoping). P1 product slice: MESH +
  CONCENTRATED_MESH only. Parser support is not compiler certification.
- **Requirement gaps for MVP:** `Agent` lacks reset/sideband/clock-vs-
  domain/protocol-capability detail; `Requirement` has no per-class
  latency distribution, no measurable bandwidth (P1.9:
  `PerformanceResult` → accepted/offered throughput, saturation,
  per-class BW); `PhysicalContext` has no floorplan/aspect/edge
  constraints; `Workload` Level B is collectives-only (no MoE/EP/PIM
  lowering yet — P1.7). Document the supported subset; do not block
  the slice on the full PRD.
- **Found defect (incidental):**
  `model/parallelism.py:group_of`/`validate_group_laws` raise
  `ConservationLikeError`, which is in `__all__` but never defined
  or imported → `NameError` on those paths. One-line fix with a
  regression test (file under P1 cleanup, not P0).

## 4. The naming collision (fix first)

`model/compile_model.py:CompileRequest` is the E1–E5 product request.
`synthesis/compiler.py:CompilerRequest` is a candidate-evaluation
request (`requirements` + caller-supplied `candidates` +
`search_budget` + recorded `seed_policy`), and `compile_fabric()`
EVALUATES caller-supplied candidates via an `evaluate` callable —
it synthesizes nothing (verified: no adjacency construction, no
parameter search; loop is `for cand in request.candidates`).
Its verdicts (FEASIBLE / NO_FEASIBLE_DESIGN /
CONSTRAINT_UNMEASURABLE / INCONCLUSIVE) and fail-closed bandwidth
handling are good code with an inflated job title.

Rename (no sealed persistence involved — verdict JSONs are reports,
not content-addressed resources; call sites: `api.compile_fabric`,
`cli synthesize-compile`, `synthesis/bridge.py`):

```text
CompilerRequest   → CandidateEvaluationRequest
compile_fabric()  → evaluate_candidates()
```

The only product-level `CompileRequest` is E1–E5.

## 5. TopologyIR vs TopologyArtifact (settled)

- `TopologyIR`: frontend/backend-neutral AUTHORING + interchange.
  No hash, no identity. May describe families the compiler will
  never certify.
- `TopologyArtifact`: sealed resolved semantics. The ONLY topology
  truth the compiler emits and backends execute.
- Seam: `TopologyIR ↓ resolve/materialize ↓ TopologyArtifact`.
  `compile_bundle` never touches the IR. CLI anynet inputs stay on
  the interchange path until a materialize path exists for them.

## 6. P1 exit (the wall)

```bash
srota compile examples/llama_dense_64tiles.json
```

produces chosen topology, placement, derived routing/VC/link
widths, deadlock certificate, BookSim-backed metrics, and a
`FabricArtifact` — with no manual routing/VC configuration.
Everything between now and then must justify itself against that
command. P1.1–P1.10 (deterministic mesh slice → attachment →
routing → VC assignment → certificate → workload lowering →
fabric binding → measurable requirements → vertical slice) follow
the program order; optimization (Wave F replay over GUIDED intent)
and RTL/DV generation come only after one deterministic candidate
works end to end.
