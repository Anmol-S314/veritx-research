# Capability Closure Audit — 2026-09

Durable evidence for `veritx_dse.application.booksim_qualification_registry`.
Every claim below was **derived from the implementation at HEAD** on
`integration/studio-reconciliation`, not carried over from older planning
documents. Regenerate this document whenever a profile, qualifier, or
execution gate changes. A stale optimistic row is a bug; a stale pessimistic
row is also a bug.

## 1. Certified BookSim execution envelope

| Profile | Scope | Qualifier | Evidence |
|---|---|---|---|
| `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1` | `MaterializedFamily.MESH`, seat_capacity 1, square k×k, `DOR_XY` | `qualify_native_mesh_dor` | `tests/test_booksim_route_equivalence.py` |
| `CERTIFIED_BOOKSIM_CMESH_DOR_XY_V1` | `MaterializedFamily.CONCENTRATED_MESH`, seat_capacity 4, square k×k, `DOR_XY`, plain grid (no express links routed) | `qualify_native_cmesh_dor` | `tests/test_booksim_cmesh_projection.py` (this audit) |
| `CERTIFIED_BOOKSIM_ANYNET_V1` | custom/explicit graphs, routing class `ANYNET_MIN_HOPS` | anynet qualifier | `tests/test_booksim_anynet_projection.py` |
| `CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1` | `MaterializedFamily.MESH`, seat_capacity 1, square k×k, `DOR_XY`, **≥2 canonical traffic classes** | `qualify_native_mesh_dor_mc` | `tests/test_multiclass_optimization_hard_gate.py` |

All profiles execute on the pinned fork binary under build recipe
`booksim2-fork/v2` (per-class trace replay; the manifest must be
regenerated after any rebuild).

### CMESH profile derivation (2026-09)

- **Endpoint→node law** (matches the vendored fork's `NodeToRouter` /
  `NodeToPort`): with row-major routers `router = y*gK + x` and seat port
  `p → (px, py) = (p % 2, p // 2)`, the trace node id is
  `node = 2k·(2·ry + py) + 2·rx + px`. The node universe is the 2k×2k grid
  folded 2×2 onto the k×k router grid.
- **Routing**: the fork's `dor_no_express_cmesh` is exact DOR-XY (x-then-y)
  over the plain concentrated grid; the express channels `_BuildNet` wires
  are dead under this routing function and the profile refuses designs that
  declare express links.
- **Fork envelope constraints** (audited in `third_party/booksim2/src/networks/cmesh.cpp`):
  `c == 4`, square k×k, `n ≤ 2`. The qualifier refuses anything else — no
  silent approximation.
- **Executed-route evidence**: live probe on the shipped
  `dense-4b-32tiles-conc4` geometry (k=3, c=4, 1 VC) produced a 324-row
  first-hop dump with **zero mismatches** against the canonical DOR-XY +
  seat-mapping expectation.
- **End-to-end acceptance**: `dense-4b-32tiles-conc4` → COMPILED →
  certificate PASS → cmesh profile selected → EVALUATED with 4704 packets
  conserved (loaded = injected = delivered; 37,520 flits accepted) and
  completion 6164 cycles, authenticated evidence.

### Multi-class profile derivation (2026-09, Phase 3)

- **Fork law (booksim2-fork/v2)**: `sim_type = latency` + `traffic =
  trace(file)` builds one `TraceInjectionProcess` per class from the FULL
  trace; unfiltered, `classes = 2` doubles every event (probed: 3 events
  → 6 injections). The patch adds a per-class event filter
  (`TraceInjectionProcess(..., class_filter)`) plus a source-busy
  coupling so a source replays its classes through one shared port
  without double-injection. The `sim_type = trace` path
  (`TraceTrafficManager`) carries the same guards as defense-in-depth.
- **Class indices**: the trace dialect `cyc src cl dst sz` maps canonical
  class NAMES to dense indices by sorted order (`trace_class_map`), bound
  into prepared-input identity only when multi-class — sealed single-class
  prepared IDs stay byte-stable.
- **Conservation**: `verify_trace_conservation` checks flits per class;
  `assert_execution_gate(expected_flits_by_class=…)` refuses the run if
  any per-class fork counter is missing or mismatched — no class
  collapsing, no cross-class contamination.
- **End-to-end acceptance**: `moe-8x7b-64tiles` → COMPILED → certificate
  PASS → MC profile selected (`classes = 2`) → executed live with
  per-class conservation (ep_dispatch 16,576 flits, tp_collective 66,304
  flits), 11,200 packets delivered, completion 11,720 cycles, all gates
  passed with `EXECUTED_ROUTE_OBSERVED`.

## 2. Static workload matrix (shipped templates)

| Workload | Compile/certify | Certified execution | Basis |
|---|---|---|---|
| `llama-dense-8b-64tiles` | PASS | EVALUATED (mesh-DOR) | mesh k×k, seat 1 |
| `dense-1b-16tiles` | PASS | EVALUATED (mesh-DOR) | mesh k×k, seat 1 |
| `dense-4b-32tiles-conc4` | PASS | **EVALUATED (cmesh-DOR, Phase 2)** | concentrated 3×3, seat 4 |
| `moe-8x7b-64tiles` | PASS | **EVALUATED (mesh-DOR multi-class, Phase 3)** | mesh k×k, seat 1, 2 canonical classes |

**Status: 4 of 4 shipped workloads execute.** Multi-class execution is
faithful, not flattened: `LogicalMessageArtifactV3` /
`PhysicalTrafficArtifactV3` preserve per-message classes, the MC profile
renders the fork's class column, and per-class flit counters are gated at
execution. Both classes share the single certified VC envelope (0,); the
VC envelope law is stated per run, never silently widened.

## 3. Optimization capability truth (Phase 1, repaired)

`optimization/capabilities.py` no longer derives `executable` from
`compilable && effective`. Each guided parameter now carries
`expressible`, `compilable`, `effective`, `backend_executable` (measured
through `select_booksim_profile` on a real compiled/lowered design),
`executable`, and `qualified_for_certified_optimization`.

- `topology_family.executable_values` is **derived from the full certified
  chain**, not from the materializer: `(mesh, concentrated_mesh)` execute;
  `torus` is refused at compile (no certified routing policy); legacy
  `gec`/`fat_tree` spellings refuse at compile (no mode/structure); `custom`
  is a classification marker, not a materializable family.
- `concentration` remains **unqualified** as a standalone knob: on a MESH
  base the profile gate refuses seat_capacity > 1; on a CONCENTRATED_MESH
  base the fork pins `c == 4`, so the knob does not traverse execution.
  Concentrated execution is reached via `topology_family=concentrated_mesh`,
  not via a concentration knob on mesh.
- Pins: `tests/test_optimization_capabilities.py`
  (`test_topology_family_execution_truth_is_derived`,
  `test_backend_executable_requires_the_certified_chain`).

## 4. Topology family stage truth

| Family | Materialize | Route (canonical) | Certified backend | Product evaluation |
|---|---|---|---|---|
| mesh | yes | DOR_XY | mesh-DOR profile | yes |
| concentrated_mesh | yes | DOR_XY | **cmesh-DOR profile** | **yes (Phase 2)** |
| torus | yes | no certified policy | — | refused at compile |
| flatfly | yes | no certified chain | — | refused |
| gec / fat_tree | intent-typed (v4), legacy spelling refuses | — | — | refused until intent supplied |
| custom | explicit graph | ANYNET_MIN_HOPS | anynet profile | yes |

## 5. Known gaps deliberately NOT claimed (fail-closed)

- Torus/FlatFly/GEC/fat-tree execution — no canonical route + backend
  equivalence yet; materialization alone is not support.
- Hardware multicast — `mcast_groups`/`mcast_setup_cycles` are knobs, not a
  replication-resource model; both knobs are unqualified for optimization.
- Memory (Ramulator) is a standalone qualified analysis, not coupled to the
  product NoC execution chain; latencies are never summed across domains.

## 6. Regression gates touched by this closure

- `tests/test_booksim_cmesh_projection.py` — new: qualification, config
  rendering, prepared-input binding, route equivalence, tamper refusal.
- `tests/test_product_workflow.py` — re-pinned: concentrated template now
  evaluates; MoE refusal pinned separately
  (`test_unevaluable_moe_revision_refuses_simulation_honestly`).
- `tests/test_optimization_capabilities.py` — re-pinned: executable_values
  include concentrated_mesh; concentration stays unqualified.

### Phase 3 gates

- `tests/test_multiclass_optimization_hard_gate.py` — rewritten to the
  Phase-3 law: MC profile selection, class-aware rendering, per-class
  conservation gate, prepared-identity binding of `trace_class_map`.
- `tests/test_workload_moe_lowering.py` — re-pinned: the V3 projection
  now renders and conserves per class (the old flattening refusal is
  gone by design).
- `tests/test_product_workflow.py` — MoE template now
  `evaluation_supported`; the unevaluable-concentrated refusal is pinned
  separately (c == 4 seat_capacity refusal, domain `backend_profile`).
- `tests/test_capability_truth.py` — fully-progressing families are now
  `{mesh, concentrated_mesh, explicit}`.
- `tests/test_sealed_prepared_input.py` — sealed single-class prepared
  IDs byte-stable across the class-aware schema change.
- `tests/test_custom_routing.py` — the custom AnyNet path survives the
  class gate via stub-parent tolerance.
