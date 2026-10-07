# VERITX / SROTA Loom — Capability Closure Ledger

**Status:** implementation ledger, not a roadmap or a claim of overall readiness.
**Audit base:** `74474645c72324eec11d938b6e6767aec645df4e`; **current HEAD:** `e82268cf83c109021db5e5726d12f8dba44bd02b` on `integration/studio-reconciliation`.
**Updated:** 2026-10-07.
**Authority:** live `loom_capabilities(include_topology_probe=True)` at this checkout.
**Hard boundary:** `CompileRequestV5` composes the new intent modules into a V5 identity hash with explicit neutral V4 migration. It is **not yet materialized by the compiler or consumed by a backend/product UI**. V5-only intent refuses V4 projection rather than being silently discarded.

## 1. Live capability truth

Probe result: **60 rows** — 19 READY, 7 BLOCKED, 26 PARTIAL, 8 NOT_IMPLEMENTED (live gateway probe, 2026-10-07). `generate.uvm` remains PARTIAL: bundle-derived output is available, but it is not qualified against the repository DUT.
The server registry is `tracks/t3-topology/dse/veritx_dse/application/loom_capability.py`; its topology rows are probe-derived. This pass corrected two stale statements using source/runtime evidence: UVM imports resolve, and measured per-channel telemetry exists. A later Phase I update wired bundle-derived UVM template generation, but a lint probe against the repository RTL found a DUT parameter/port mismatch and no installed UVM library. `generate.uvm` is therefore PARTIAL, not runnable or qualified; per-link telemetry remains PARTIAL.

Topology probe at inspected HEAD:

| Family | Status / last stage | Notes |
|---|---|---|
| mesh | READY / PRODUCT_WIRED | qualified BookSim mesh-DOR profile |
| concentrated_mesh | READY / PRODUCT_WIRED | certified concentrated mesh; native projection is constrained |
| flatfly | READY / PRODUCT_WIRED | qualified profile |
| flattened_butterfly | READY / PRODUCT_WIRED | AnyNet profile |
| dragonfly | READY / PRODUCT_WIRED | AnyNet profile |
| qtree | READY / PRODUCT_WIRED | AnyNet profile |
| tree4 | READY / PRODUCT_WIRED | AnyNet profile |
| fat_tree | READY / PRODUCT_WIRED | structured family/preset |
| explicit | READY / PRODUCT_WIRED | AnyNet profile |
| gec_express | READY / PRODUCT_WIRED | shipped preset |
| fattree | READY / PRODUCT_WIRED | new `fattree16` preset normalizes the distinct `FatTreeIntent` spelling through the graph-backed AnyNet profile; live BookSim run conserves flits |
| torus | READY / PRODUCT_WIRED | shipped `torus25` preset declares X↔Y blocking dependencies and compiles with 2 dateline VCs; qualified execution is restricted to odd side lengths because BookSim randomizes midpoint ties; the one-VC default remains refused |
| gec_mesh | READY / PRODUCT_WIRED | exact nearest-neighbor/X-then-Y lowering to the canonical mesh artifact; shipped `gec_mesh64` preset uses the qualified mesh-DOR profile |
| gec_multidrop | READY / PRODUCT_WIRED | materializes as shared wires, routes with per-tap VC slices, certifies via `shared-resource-cdg/v1`, and executes live under `CERTIFIED_BOOKSIM_GEC_MECS_V1`; no shipped preset normalizes to it yet |
| gec_hybrid | BLOCKED / AUTHORABLE | `hybrid_gec` chooses mesh-vs-MECS at runtime from live credit, so it has no deterministic decision table and needs the escape-subnetwork proof method |
| srota | READY / PRODUCT_WIRED | canonical `SrotaIntent` parses and carries identity; Plane D materializes with MECS express channels as shared (multidrop) links; the row-first hop rule is differentially qualified against the fork and now yields a v3 route whose shared-resource CDG is proven acyclic; the design now compiles and certifies with `DEADLOCK_FREE` discharged by `shared-resource-cdg/v1`; a shared-wire profile (`CERTIFIED_BOOKSIM_SROTA_ROW_FIRST_V1`) renders the Plane D surface, and the shipped `srota32` preset executes live with flit conservation; shape mixing, Valiant, islands and Plane C remain typed refusals |

## 2. Phase A implementation outcomes

Five canonical intent modules plus `CompileRequestV5` were added with strict parsing, typed refusals, deterministic serialization, explicit neutral V4 migration, and dedicated tests. V5 identity changes when new intent changes; the old V4 hash remains unchanged. Exact semantics are in `tracks/t3-topology/dse/docs/INTENT-V5-CONTRACT.md`.

| Capability | Current state | Canonical owner / field | Compiler artifact | Backend consumer | UI surface | Reference / oracle | Tests / qualification | Remaining blocker |
|---|---|---|---|---|---|---|---|---|
| Agent interface role | PARTIAL / V5 root only | `agent_interface.InterfaceRole`; `AgentIntentV5.interface_role` keyed to V4 group index | no attachment/compiler artifact | none | no Loom authoring | no upstream adopted | V5 + catalog tests; Q1 | extend stable endpoint identity and compiler materialization; current binding uses V4 positional group identity |
| Transaction outstanding | PARTIAL / root identity; blocked MATERIALIZABLE | `AgentIntentV5.transaction_policy` → `TransactionPolicy.outstanding` | no transaction artifact | none; no issue scheduler | none | mathematical issue/completion micro-oracle only | 82 transaction + V5 tests; Q1 only | workload transactionization, completion-driven issue execution, backend and differential qualification |
| Transaction ordering | PARTIAL / root identity; blocked MATERIALIZABLE | `AgentIntentV5.transaction_policy` → `OrderingPolicy` | no transaction artifact | none | none | no protocol oracle yet | transaction + V5 tests; Q1 | define operation/dependency materialization, protocol adapters and ordering execution proof |
| Transaction splitting | PARTIAL / root identity; blocked MATERIALIZABLE | `AgentIntentV5.transaction_policy` → `SplittingPolicy` | child transactions exist only in standalone helper | none; not packetization | none | canonical conservation micro-oracle | transaction + V5 tests; Q1 | bind into workload pipeline; packetization, BookSim execution, parent/child completion accounting and independent AXI comparison |
| Access windows and permissions | PARTIAL / root identity; blocked MATERIALIZABLE | `CompileRequestV5.access_policy`; RW/RO/WO/DENY | standalone `AccessPolicyArtifact`; not emitted by compiler | none | existing Access Loom is not bound to this policy | reuses address-domain constants; no external code | 44 policy + V5 tests; Q1/Q2 contract only | endpoint/route integration, execution authorization observation, product UI; this is not a firewall |
| Sideband interfaces | PARTIAL / V5 root identity; blocked MATERIALIZABLE | `CompileRequestV5.sideband_interfaces` | no materialized artifact | none | none | no upstream code used | 45 sideband + V5 tests; Q1 | compiler materialization; validate protocol bindings before claiming compatibility |
| Sideband connectivity | PARTIAL / V5 root identity; blocked MATERIALIZABLE | `CompileRequestV5.sideband_connections`, `validate_sidebands()` | standalone sideband set | none; separate edge only | none | no upstream code used | sideband + V5 tests; Q1 | materialized connectivity artifact, clock-crossing resolution and UI |
| Clock sources/domains | PARTIAL / V5 root identity; blocked MATERIALIZABLE | `CompileRequestV5.clock_sources/clock_domains`; exact integer Hz, exact divider law | none | none | Domains Loom still projects names/census from existing artifacts | existing exact-Hz parser discipline | domain + V5 tests; Q1 | compiler artifact and multi-clock backend; no clock ratio is simulated |
| Reset intent | PARTIAL / V5 root identity; blocked MATERIALIZABLE | `CompileRequestV5.reset_channels`; async assert + sync deassert, stages/dependencies | none | none | Domains Loom not bound | no RTL differential yet | domain + V5 tests; Q1 | reset materialization, supported RTL oracle; no metastability/signoff claim |
| Power intent | PARTIAL / V5 root identity; blocked MATERIALIZABLE | `CompileRequestV5.power_domains`; ALWAYS_ON/COLLAPSIBLE | none | none | Domains Loom not bound | no UPF oracle | domain + V5 tests; architectural intent only | compiler artifact; isolation, retention and level shifters remain unspecified; not UPF signoff |
| CDC crossing intent | PARTIAL / V5 root identity; blocked MATERIALIZABLE | `CompileRequestV5.crossings`; `Crossing`, `AsyncFIFOConfig`; UNRESOLVED is explicit | none | none | Domains Loom has derived crossing census, not this contract | PULP common_cells audit pending; no upstream used | domain + V5 tests; Q1 | crossing artifact, RTL differential against a pinned/license-reviewed primitive; no signoff or MTBF |
| Async FIFO performance | PARTIAL / V5 FIFO intent identity, separate standalone model | `CompileRequestV5.crossings`; `AsyncFIFOModel` is not embedded in design | no compiler artifact | no BookSim bridge integration | no execution control | mathematical event model only | domain + V5 tests; Q1 | model currently uses one shared cycle counter; no clock ratio; no RTL differential |
| IP catalog | PARTIAL / AUTHORABLE blocked | server-owned `IP_CATALOG`, 12 templates | no catalog-instantiation compiler artifact | none | not yet connected to Loom Catalog/Stamp | catalog entries are VERITX mappings, no upstream IP copied | 44 tests; Q1 | capability ids and template status must be joined to the server registry; bind stamps to canonical draft mutations; no area/power numbers supplied |
| Multi-plane fabric | PARTIAL | existing `PlaneComposition` only accepts SINGLE_PLANE; Srota plane enum is unreachable | no independent plane bundle | none | Loom labels planes as extension points | none | existing model refusal | create plane intent + independent per-plane materialization/status; do not recolor one topology |
| Concentration | PARTIAL | topology intents + concentrated-mesh projection | certified 4:1 cmesh; ordinary mesh 1:1 | BookSim cmesh | no truthful 1:1/2:1/4:1 editor | `cmesh.cpp:77` asserts `c == 4`; local source | live topology probe and projection tests | 2:1 exact lowering/qualification absent; must refuse, not approximate |
| VC allocation | PARTIAL | derived VC assignment/resources; `VCAllocationScope.PACKET` only | VC/resource artifacts | BookSim native VC allocator for qualified profiles | capability view only | local BookSim source audit | existing VC/CDG tests | no static/dedicated/shared-pool/custom semantics mapped or qualified |
| Routing controls | PARTIAL | rich `RoutingPolicyDefinition` and materializers | route/policy artifacts | BookSim profile-specific rendering | policies are not an arbitrary Loom control | existing route/deadlock certificate | existing routing + CDG tests | user-authored routing override and per-policy product capability not wired |
| SROTA topology | NOT_IMPLEMENTED product-side | `model/srota_intent.py` exists but absent from root topology parser/registry path | no product topology/route bundle | BookSim has `networks/srota.cpp`, unreachable canonically | capability row refuses | vendored BookSim only; no upstream candidate incorporated | intent legality tests only | topology root registration, materializer, route/deadlock certification, projection/profile, execution, qualification, preset |
| Per-link/channel telemetry | PARTIAL, product-wired | measured channel counters and sampled series artifacts | `MeasuredChannelLoad`, `ChannelLoadSeriesArtifact` | BookSim sampled channel activity; gateway `/loom/simulation/{load,series,link}` | Simulation Loom can query measured data | fork counter artifacts; source classified MEASURED | measurement/series tests; existing API | `stalls_per_window=None`; no stall/backpressure counter, buffer occupancy or power metric. No cycle-by-cycle claim; sample period applies |
| UVM template generation | PARTIAL; output is unverified and not runnable against the repository DUT | `verification.uvm_gen.generate_uvm_for_bundle(bundle, revision_id=…, design_hash=…)` derives n_nodes/K/VC/routing from the compiled bundle; declared v2 radix must agree with the compiled router count; legacy v2 `generate_uvm(CompileRequest, n_nodes, k)` remains for direct v2 callers | four stamped SV template sources with revision/design/generator identity; no successful compile proof | `ProductService.generate_revision_uvm` + `POST /api/v1/revisions/{id}/uvm`; `veritx generate uvm` routes v3/v4 docs through the bundle | gateway route exists; no Loom Generate-UVM button | generated DUT binding has not passed RTL lint; no UVM library was found; no upstream code adopted | `tests/test_uvm_bundle_product.py`, `tests/test_cli_truthfulness.py`, legacy generator tests; Verilator probe against `rtl/t3/mesh.sv` fails | DUT parameter names and required ports mismatch; must compile and run against a supported real DUT before promotion |
| RTL generation | NOT_IMPLEMENTED | no emitter; SystemVerilog output name is not an emitter | no generated RTL artifact with content proof | none | no truthful Generate RTL action | none adopted | no generated-output compile gate | supported subset emitter, capability refusal, syntax/lint/simulation smoke first |
| Abstract physical placement | PARTIAL | topology coordinates/adjacency; current floorplan projection | no external P&R result | none | Floorplan Loom abstract view | mathematical geometry | existing topology tests | shipped physical-link data sparse; provenance labels and authored placement mutation absent |
| OpenROAD handoff | NOT_IMPLEMENTED | no handoff/runner | none | none | disabled/unavailable | reuse/license audit pending | none | selected open PDK, LEF/Liberty/SDC/DEF contracts, tool/digest provenance and external failure semantics |
| Workload lowering | PARTIAL (real logical lowering) | workload registry/intent lowering | phase/operation/collective/traffic artifacts | BookSim/ASTRA/serving paths depending on question | Workload Loom | existing canonical registry and lowering | DSE conservation and workload tests | compute internals/timing not modeled; no shape-only workload may be called a named-model execution without registry provenance |
| Desktop executable | NOT_IMPLEMENTED | React/Vite Studio remains web application | gateway/CLI remain existing product boundary | no packaged process manager | none | Tauri reuse audit pending | none | Tauri v2 shell, health handshake, process lifecycle, filesystem/export and package smoke |
| Undo/redo and draft commands | PARTIAL typed client seam (7 agent fields plus limited mesh topology controls) | typed `DraftCommand` + `useDraftStore` in `apps/studio/src/pages/loom/{draftCommands,draftStore}.ts`; server still accepts whole-document `PUT /api/v1/projects/{id}/draft`; V4 topology editing refuses rather than projecting into legacy fields | draft document only | ProductService validates the whole document on Save (strict unknown-key refusal); source-keyed refresh avoids replacing a just-saved draft with the stale pre-refresh query result | Agents Loom inspector: kind/count/widths/protocol/domain edits, limited v2/v3 mesh controls, Save/Undo/Redo with server refusal display | no upstream code used | `loom-draft-mutation.contract.test.ts` (18), existing gateway/product tests | command coverage beyond agent groups, server-side mutation log and partial-edit validation, immutable revision protection |

## 3. Catalog reality and capability gate

`model/ip_catalog.py` contains 12 templates requested by the brief. Entries use only the existing closed `AgentKind` set; several are explicit placement stand-ins (e.g. compute/memory/peripheral/NIC) and say so in provenance. Area and power are `NOT PROVIDED`; no PPA estimate is asserted. This catalog is **not yet safe to expose as an actionable Stamp menu**: most referenced ids are not a product-wired capability decision, no `CompileRequestV5` mutation binds an instance, and no compiler validates a stamp. `router.rcu` is explicitly NOT_IMPLEMENTED. Catalog metadata is not proof of backend support.

## 4. Qualification and test evidence

### Baseline at inspected HEAD, before edits

- DSE suite command: `PYTHONPATH="tracks/t3-topology/dse:tracks/t3-topology/dse/tests" python3 -m pytest tracks/t3-topology/dse/tests -q -p no:cacheprovider` → **5827 passed, 25 skipped, 1 warning in 805.68s**. Warning: pytest-timeout is not installed, so pyproject's `timeout` option is unknown.
- Studio Python command: `PYTHONPATH="tracks/t3-topology/dse:tracks/t3-topology/dse/tests" python3 -m pytest apps/studio/tests -q -p no:cacheprovider` → **3 failed, 7 passed, 8 skipped**. Pre-existing failures are three assertions in `test_studio_contract_v2.py` where checked-in fixture design/resolved hashes differ from the engine. Example: fixture `compiled-mesh.json` has `28ffce…`; current `CompileRequestV3` computes `6f015d…`. This pass did not retain generated fixtures or weaken the test.

### New and focused tests

| Exact command | Result | What it establishes |
|---|---|---|
| `cd tracks/t3-topology/dse && PYTHONPATH="$PWD" python3 -m pytest tests/test_transaction_intent.py -q -p no:cacheprovider` | 82 passed | Q1 transaction policies, materialized splitting, issue watermark micro-model |
| same command with `tests/test_access_policy.py` | 44 passed | Q1 permission/window ladder, overlap refusals |
| same command with `tests/test_domain_intent.py` | 92 passed | Q1 exact clocks, reset/crossing laws, abstract FIFO model |
| same command with `tests/test_sideband.py` | 45 passed | Q1 sideband endpoints/connectivity laws |
| same command with `tests/test_ip_catalog.py` | 44 passed | Q1 catalog roundtrip, closed AgentKind, no invented PPA |
| `cd tracks/t3-topology/dse && PYTHONPATH="$PWD" python3 -m pytest tests/test_compile_request_v5.py tests/test_ip_catalog.py -q -p no:cacheprovider` | 50 passed | explicit V4→V5 neutral migration, stable V4 identity, V5 hash change and refusal to drop extensions |
| combined model + registry command: `python3 -m pytest tests/test_compile_request_v5.py tests/test_transaction_intent.py tests/test_access_policy.py tests/test_domain_intent.py tests/test_sideband.py tests/test_ip_catalog.py tests/test_capability_registry_truth.py tests/test_capability_archaeology.py -q -p no:cacheprovider` | 361 passed, 1 warning | V5 root, all five new intent modules, catalog, capability registry/archaeology |
| `tests/test_capability_registry_truth.py tests/test_capability_archaeology.py` | 47 passed, 1 warning | registry structure and truth contracts |
| `PYTHONPATH=tracks/t3-topology/dse:tracks/t3-topology/dse/tests VERITX_BOOKSIM_BIN=$PWD/third_party/booksim2/src/booksim python3 -m pytest tracks/t3-topology/dse/tests/test_cli_truthfulness.py tracks/t3-topology/dse/tests/test_cli_compile_surface.py tracks/t3-topology/dse/tests/test_uvm_bundle_product.py tracks/t3-topology/dse/tests/test_compile_uvm.py tracks/t3-topology/dse/tests/test_uvm_gen.py -q -p no:randomly` | 87 passed | Phase I UVM: parameters derived from the bundle, identity stamping, typed refusals, CLI v3 routing, legacy v2 generator unchanged |
| same command with `tracks/t3-topology/dse/tests/test_integration.py::TestGenerateUVM` | 2 passed | real CLI subprocess still generates ≥3 `.sv` files |

Current follow-up verification: `cd apps/studio && npm run build` succeeds (`tsc --noEmit && vite build`, with the existing >500 kB chunk warning); `npx vitest run` passes **153 tests**. The five fixture fast checks previously passed, but do not prove backend realizability. `tests/test_uvm_bundle_product.py` passes **10 tests**, including declared-radix/compiled-router mismatch refusal. The plan-aware traffic-matrix regression passes; the broader ProductService workflow/run-bundle suite previously passed **42 tests, 1 skipped**. All nine Loom routes were browser-smoked (HTTP 200, no page errors) before the latest draft-source sync guard; current Studio and gateway HTTP checks return 200.

A stable isolated full DSE run used a temporary synthetic snapshot (`6dae2570`) with the required BookSim/AstraSim binaries symlinked from the primary checkout: **6153 passed, 24 skipped, 3 failed**. One failure (`test_entry_point.py::TestInstalledConsoleScript::test_installed_package_is_used_not_the_worktree`) was caused by that run's inherited `PYTHONPATH`; it passes when rerun with `PYTHONPATH` unset. The other two (`test_qwen_v4_declared_compute_reaches_ramulator` and `test_bound_valid_experiment_assesses_ready_or_unavailable`) also fail on unmodified base `e82268cf`, so are confirmed pre-existing baseline failures, not introduced by the Loom changes. The full gate has not yet been rerun with a corrected environment.

These are **Q1/Q2 model tests only**, not backend execution, independent external RTL differential, product E2E, CDC signoff, or PPA qualification. No upstream candidate code was vendored or adapted in this pass.

A separate post-change DSE run in the shared checkout used `VERITX_BOOKSIM_BIN=$PWD/third_party/booksim2/src/booksim` and reported **2 failed, 6135 passed, 22 skipped, 1 warning in 822.66s**. Failures were `test_env_gates.py::test_staleness_gate_reports_fresh_on_stable_tree` and `test_gateway_staleness.py::test_a_fresh_process_is_not_stale`; the checkout was concurrently dirty, so this is not recorded as a clean integration gate. It must be rerun on a stable tree.

### Test-harness hygiene incident

The baseline/full suites mutated tracked files as side effects: Studio tests rewrote five fixtures (including the fixture that had caused the pre-existing hash mismatch), and a DSE test changed an example's HBM-controller count. The example mutation was reverted after each observed run. Fixture regeneration was reverted once; a later parallel run regenerated those fixtures again. The current shared checkout still contains fixture and Loom UI/draft-editor changes in the uncommitted worktree; these have been snapshotted for isolated testing and the Loom refresh race was reviewed and fixed. **Do not interpret fixture regeneration as a baseline fix.** The fixture test side effects still require a separate harness fix or isolated temporary fixture directory.

## 5. Open-source reuse ledger

`docs/third-party/LOOM-REUSE-LEDGER.md` records locally verifiable vendored components and all requested upstream candidates as **AWAITING_VERIFICATION**. The current environment's research subagent had no web tools; exact remote SHAs, SPDX licenses, source files, maintenance and tests were not invented. No candidate code was vendored or adapted. License review remains a blocker before any reuse.

## 6. Required next dependency graph

1. **Compiler materialization:** compile `CompileRequestV5` into content-addressed artifacts for each composed field; unsupported execution must refuse with a typed reason. V5 root identity and explicit v4 migration exist, but materialization is the next blocker.
2. **Stable agent identity:** replace V4 positional `agent_group_index` bindings with a stable V5 agent-group identity before endpoint attachment/product UI uses these extensions.
3. **Backend adapters:** implement issue/completion execution for outstanding/ordering/splitting; permission checks at transaction execution; CDC/clock performance bridge remains a separate qualified profile. No metadata-only knob.
4. **Oracle qualification:** complete license audit; pin sources; compare transaction splitting/ordering to PULP AXI where semantics align; compare FIFO event behavior to a license-approved RTL oracle; extend BookSim↔RTL gates only within their qualified envelope.
5. **Product service/API:** typed draft mutation seam, catalog and per-object capability response, immutable revision compile path, generated-artifact provenance. Do not put semantics in React.
6. **Loom integration:** bind catalog/stamp/editors to canonical mutations; retain evidence/provenance; controls disabled with server reason when not supported.
7. **Desktop/physical/generation:** only after live web product path is stable; OpenROAD and Tauri remain explicitly absent.

## 7. Files changed in this pass

- `tracks/t3-topology/dse/docs/INTENT-V5-CONTRACT.md` — shared contract for the new submodels.
- `tracks/t3-topology/dse/veritx_dse/model/{transaction_intent,access_policy,domain_intent,sideband,ip_catalog,agent_interface,compile_request_v5}.py` and matching test files.
- `tracks/t3-topology/dse/veritx_dse/application/loom_capability.py` — live registry truth corrections and added rows.
- `tracks/t3-topology/dse/veritx_dse/product/service.py` — plan-aware measured traffic availability and UVM bundle product route.
- `apps/studio/src/pages/loom/{draftCommands,draftStore,index,AgentsLoom,TopologyLoom}.tsx` plus contract coverage — typed local agent edits, limited v2/v3 mesh topology edits, undo/redo, and stale-refresh protection. This remains a client-command seam over whole-document server validation, not an atomic server mutation log.
- `docs/third-party/LOOM-REUSE-LEDGER.md` — local audit plus explicitly pending upstream verification.

CompileRequestV5 is delivered as an identity-bearing model root with explicit migration, but it is not compiler-, gateway-, API-, or Loom-wired. The limited agent/topology draft editor is delivered; a truthful catalog Stamp workflow is not. OpenROAD integration, an RTL emitter, and a Tauri shell remain absent.

**Phase I update (UVM template product-wiring):** `veritx_dse/verification/uvm_gen.py` (canonical `generate_uvm_for_bundle` + typed `UvmGenerationError`), `veritx_dse/product/service.py` (`generate_revision_uvm`, including frozen artifact-hash comparison), `veritx_dse/gateway/app.py` (`POST /api/v1/revisions/{id}/uvm`), `veritx_dse/cli/cli.py` (v3/v4 documents route through the bundle with expected-error handling), and `tests/test_uvm_bundle_product.py`/`test_cli_truthfulness.py`. Review blocked READY: generated `noc_mesh` parameters/ports do not match `rtl/t3/mesh.sv`, and the real UVM library is absent. The live capability is PARTIAL until generated collateral compiles and runs against a supported DUT.
