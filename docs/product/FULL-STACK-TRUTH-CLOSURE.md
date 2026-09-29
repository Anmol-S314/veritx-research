# FULL-STACK TRUTH CLOSURE — Qwen3-30B-A3B TP2+EP4 Acceptance Program

Branch: `integration/studio-reconciliation` (work here; no new branch).
START SHA: `a05d7769c7998c64a1c3c05e989f5a9cad9a8ef3`
(`a05d7769 catalog: nine more static workloads with proven traffic diversity`)

Starting tree state (2026-09-29): DIRTY — 21 modified `apps/studio/src` files
+ untracked `ScenarioStack.tsx`, `pages/evaluate.tsx` (prior Studio UI
sessions, uncommitted, preserved as-is) + untracked `node_modules/`,
`release-manifest.json` (build artifacts, never to commit).

Host baseline: Python 3.14.4, g++ 15.2.0, cmake 4.2.3, protoc 3.21.12
(Ubuntu, `libprotoc 3.21.12`). Host pydantic 2.13.4.

Acceptance target: Qwen/Qwen3-30B-A3B-Instruct-2507, MoE (48L/128 experts/
top-8), RTX PRO 6000 profile, TP2+EP4 (8 ranks), multi-class TP+EP
traffic, mesh fabric, through DESIGN → COMPILE → VERIFY → LOWERING →
TRAFFIC → BOOKSIM → ASTRA → MEMORY → RAMULATOR → SERVING → RESULTS →
EVIDENCE → REPRODUCE. Compute is NOT MODELED until a real authority
exists; the UI must say so.

Rule log (violations found during this program go here with fix + test):

| # | Rule broken | Where | Fix | Test |
|---|-------------|-------|-----|------|
| RC-A | Gate 1 UI admission: dirty Studio editor writes 9 field paths with no `intent-ontology.yaml` row | `apps/studio/src/components/DesignViewV2Editor.tsx` (uncommitted prior work) vs `scripts/check_intent_ontology.py` check #6 | Add honest ontology rows (§16) | `make -C tracks/t3-topology product-gates` on dirty tree |
| RC-B | `requirements.lock`/pyproject claim "runtime dependencies: none" while `core/spec.py`, `gateway/app.py`, `gateway/vnext.py` import pydantic, gateway imports fastapi, `product_registry.py` imports yaml | `tracks/t3-topology/dse/pyproject.toml`, `requirements.lock` | Declare runtime deps; guard test | new dep-guard check (§2) |
| RC-C | Release container (Dockerfile runtime stage) lacks cmake + protoc + pytest + pydantic, but `release.yml` runs `make release-build` + pytest inside it | `Dockerfile:189-211` | Add declared toolchain to runtime stage; guard check (§2) | new toolchain check (§2) |
| RC-D | Producer dirtiness measured over the WHOLE repo: any unrelated edit (Studio UI, docs) marked every backend binary NOT_QUALIFIED → 24 DSE tests failed + every live backend BLOCKED | `core/build_manifest.py:163-168` (schema 1) | Scope `source_dirty` to the producer's own source subtrees; manifest schema 2 records `source_paths`; Makefile passes per-backend scopes | `test_build_manifest.py::test_dirty_scope_is_the_producer_subtree_not_the_repo` etc. | FIXED — BookSim/ASTRA/Ramulator manifests now dirty=False; `NETWORK_COMPLETION READY` on the Qwen design |
| RC-E | Frozen v3 identity golden never extended when 9 new v3 examples were added → `test_v3_identity_is_byte_for_byte_unchanged` failed | `dse/tests/fixtures/v3_identity_golden.json` | Regenerate entries (additions only; verified no existing entry moved), amendments preserved | `test_v3_semantics_frozen.py` | FIXED — 11 → 20 entries, 10 passed |
| RC-F | Ramulator refusal text was misleading: `_issue_nodes_for` raised "COMPUTE ops carry no placement" even with ZERO COMPUTE ops (a collectives-only v3 workload has no memory demand) | `workload/memory_lowering.py:135-142` | Vacuous attribution for no-COMPUTE; owner-derived attribution for COMPUTE ops; accurate "no memory demand" message | `test_memory_graph.py::TestExecutionAttribution` (3 tests) | FIXED — DRAM reason now "workload declares no COMPUTE memory-operand bytes" |

## Capability table

Columns: Capability | Current authority | Current status | Current failure |
Fix | Test | Qualification level | Final status.

| Capability | Authority | Status | Failure | Fix | Test | Qual | Final |
|------------|-----------|--------|---------|-----|------|------|-------|
| release-build (host) | root `Makefile:72-76` | PASS (binaries present, rebuilt this program — see log) | — | — | `make release-build` | build reproducibility | PASS |
| product-gates (clean HEAD) | `tracks/t3-topology/Makefile:31-35` | PASS | — | — | same | static gates | PASS |
| product-gates (dirty tree) | Gate 1 UI check #6 | FAIL (9 problems) | editor writes w/o ontology rows | §16 ontology rows | same on dirty tree | static | OPEN |
| BookSim build | `third_party/booksim2/src/Makefile` | PASS | — | — | release-build | recipe `booksim2-fork/v2` | PASS |
| ASTRA build | `third_party/astra-sim/build/astra_booksim2/build.sh` (protoc+cmake) | PASS on host; FAILS in release container (no protoc/cmake) | RC-C | Dockerfile fix | toolchain check | recipe `astra-sim+booksim2/v1` | OPEN |
| Ramulator build | `third_party/ramulator2/build.sh` (cmake) | PASS on host; FAILS in release container (no cmake) | RC-C | Dockerfile fix | toolchain check | recipe `ramulator2/v1` | OPEN |
| pydantic/fastapi/yaml availability | undeclared (workstation-global) | WORKS ON HOST ONLY | RC-B | declare + install | dep-guard check | — | OPEN |
| Qwen acceptance workload | scattered (§3) | NO canonical definition | — | `validation/workloads/qwen3-30b-a3b-tp2-ep4/` | acceptance test (§18) | — | OPEN |
| System authority | `CompileRequestV4.agents` vs unwired `SystemIntentV4` | SPLIT | §4 | next-gen system object + migration | migration tests | — | OPEN |
| v4 product wiring | product accepted v2/v3 only | **PASS** | §6 | `parse_request_doc` + `design_view_v2._canonicalize` accept v4; compute intent flows end to end | acceptance v4 test | — | DONE |
| Compute device typing | `compute_tile` generic | VAGUE | §5 | typed devices | tests | — | OPEN |
| HW profile contract | browser-local only | **DERIVED from tracked measured sources** | §6 | `application/hardware_profiles.py` (cluster config + profiler meta), DESCRIPTIVE/CONSUMED dispositions, gateway `/catalog/hardware-profiles`, Studio binding; profile never enters design hash | `test_hardware_profiles.py` | DESCRIPTIVE vs CONSUMED | DONE (descriptive) |
| ASTRA TP2+EP4 | `derive_logical_dimensions` refused unequal sets; adapter never passed the collective binding | **PASS** | §7 | multi-communicator dims + wire `derive_collective_binding` into `stage_endpoint_workload`; tests in `test_memory_graph`/astra suites | Qwen r01 executes: BookSim MC 2805 cyc, ASTRA 3050 cyc, run QUALIFIED | LIMITED (absolute latency NOT_ESTABLISHED; schedule window only) | EXECUTES |
| Op attribution | `_issue_nodes_for` refuses multi-rank w/o placement | BLOCKED | §8 | attribution artifact | attribution tests | — | OPEN |
| Ramulator on Qwen | blocked by attribution | **PASS on v4 declared compute; BLOCKED on v3** | §9 | v4 `compute` intent wired through the product; v4 acceptance workload `qwen3_moe_tp2_ep4_16tiles-v4.json` declares per-layer activation demand | `test_acceptance_qwen_fullstack::test_qwen_v4_declared_compute_reaches_ramulator` | single-ctrl HBM3 v1 envelope | DONE (declared compute) |
| Compute model | `COMPUTE_SOURCE_EXPLICIT` only | NOT MODELED (honest) | §10 | keep honest / profile authority | — | — | NOT MODELED |
| RTX PRO 6000 data | profiler CSVs consumed by serving code | **BOUND in product** | §11 | profile names the measured timing source (Qwen3-30B-A3B, bf16, TP1/2, vLLM 0.19/CUDA 13, 2026-04-24) consumed by CANONICAL_SERVING; Studio shows it. Design-time compute stays NOT MODELED | `test_hardware_profiles.py` | TP1/TP2 measured envelope | DONE (serving timing source) |
| Serving binding | catalog count shown as readiness | **PASS (binding) / BLOCKED (execution)** | §12 | explicit binding + compatibility gate (rank count, internal TP/EP consistency, model identity); run options wired; v3 designs now compile through FabricCompiler in `run_canonical_serve`. Execution is blocked: **zero compatible design×cluster pairs** exist in the tracked catalog, and the serving loop binds EP inside an instance's TP span — the TP2+EP4 design's independent-dimension model has no compatible config | `test_serving_binding.py` (5) | PARTIAL (absolute latency) | DONE (binding); execution classified out of scope |
| Readiness vs qualification | single QUALIFIED label | **PASS** | §13 | `application/qualification_envelopes.py`: independent numerical_qualification + calibration per backend, exposed in the plan view | `test_qualification_envelopes.py` | per-backend envelopes | DONE |
| SYSTEM_MAKESPAN name | generic, misleading | **PASS** | §14 | Studio label now "Distributed schedule"; END_TO_END_WORKLOAD_RUNTIME reserved (comment) | live plan | — | DONE |
| Evaluate page | rebuilt prior sessions (question-first) | closer; verify vs §15 | §15 deltas | UI | live run | — | OPEN |
| Design page | 3 layers; localStorage profile; count inconsistencies | NEEDS §16 fixes | §16 | UI + ontology | live Qwen design | — | OPEN |
| Capability truth | live `capability_truth.py` vs YAML prose | DUAL; UI labels at risk | §17 | single truth + UI contract tests | contract tests | per-capability envelopes | OPEN |

## Acceptance workload definition (§3)

Canonical definition: `validation/workloads/qwen3-30b-a3b-tp2-ep4/`
(reproducible from tracked data; provenance per input below).

| Input | Source (tracked) | Provenance |
|-------|------------------|------------|
| Model config | `third_party/llmservingsim/configs/model/Qwen3-30B-A3B-Instruct-2507.json` | vendored upstream HF-subset: 48L, 128 experts, top-8, bf16 |
| HW profile | `third_party/llmservingsim/profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/{meta.yaml,tp1/,tp2/}` | measured vLLM 0.19/CUDA 13.0, 2026-04-24; TP1/TP2 |
| Cluster slice | `third_party/llmservingsim/configs/cluster/single_node_moe_single_instance.json` pattern (TP2/EP4 adaptation) | 1 node `RTXPRO6000`, link 16 GB/s |
| Serving trace | `third_party/llmservingsim/workloads/*.jsonl` selection | ShareGPT-derived; exact file TBD §12 |
| Topology | mesh (canonical TP2+EP4 fabric; sizes TBD §3) | derived from parallelism law |
| Backends | BookSim (mesh DOR MC), ASTRA embedded, Ramulator HBM3 v1, canonical serving | pinned producers + manifests |

## Qwen full-stack result (updated at completion)

Design compile: PASS (Qwen3-30B-A3B TP2+EP4, 16 compute + 4 HBM + 2 NIC)
Certificate: PASS
TP multi-class traffic: PASS (class tp_collective present)
EP multi-class traffic: PASS (classes ep_dispatch + ep_combine present)
BookSim: PASS (CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1; loaded==injected==delivered,
        flits_injected==flits_accepted)
ASTRA TP2+EP4: PASS (mixed communicators; makespan/exposure/per-rank EVALUATED)
Ramulator: PASS on the v4 declared-compute workload (activation demand, 101,875 cycles); v3 has no declared compute (BLOCKED)
Compute: NOT MODELED (stated everywhere; no fabricated timing)
Serving: BLOCKED — no tracked cluster config is compatible (rank + model + TP/EP geometry) with any catalog design; binding is now explicit + compatibility-checked, and the run reports it, never fabricates
Reproduction: PENDING (§20)
