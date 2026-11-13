# HANDOFF — VeritX (intent → verified NoC RTL)

**Written:** 2026-11-13, for a strong incoming model with no prior context.
**Repo:** `/home/datavex/bruh/veritx-research`
**Branch / HEAD:** `integration/studio-reconciliation` @ `d5ce2f7a19557ce4a7ed8c60a7850525bc528556` (2026-11-12 12:26 +0530)
**Working tree:** *dirty by design* — 2,400 entries (2,285 untracked, 114 modified, 1 deleted). See §7.5. Do not "clean" it.

Read this document top to bottom once. Then read, in this order:
`docs/product/RTL-FINAL-CLOSEOUT-STATUS.md` → `docs/product/REMAINING-WORK.md` → `docs/OPEN-PROBLEMS.md` (only the "Current status" block at the top) → `docs/architecture/FLOW-AND-VERSION-MAP.md`.

---

## 0. How to read this repo (the thing that will bite you first)

This repository is not "a codebase with some docs". It is **an evidence system that happens to contain code**. Nearly every document you will open contains a mixture of:

- a **measurement** (a run, a hash, a log, a test) — trustworthy, dated, usually with a path under `runs/`;
- a **claim** (a status word) — only valid for the scope it explicitly names;
- a **stale claim** — superseded by a later section of the *same file*, or by another file.

Three rules that the previous sessions learned the hard way:

1. **The status words are scoped.** `PASS`, `QUALIFIED`, `final_implementation: true`, `READY` never mean "the project works". They mean "the named row, at the named design hash, at the named abstraction, passed". The tables in §7 and §8 always name the scope for this reason.
2. **A refusal is a first-class, correct outcome.** `UNSUPPORTED`, `UNMEASURABLE`, `NOT_RUN`, `BLOCKED`, `PASS_WITH_NOT_RUN`, `EVIDENCE_INVALID` are *designed* results. Inside this repo, a typed refusal is worth more than a green that was not earned. Do not "fix" a refusal by loosening it.
3. **The tree must be quiet to produce evidence.** Three of the repo's own gates (source-provenance, gateway staleness, renderer determinism) exist to refuse a verdict taken on a moving tree. Nearly every "failure" in the historical logs is the measurement reacting to a concurrent edit, not a defect. This is documented in detail in `docs/product/REMAINING-WORK.md` item 11.

If you take nothing else from §0: **when a doc and a run disagree, the run wins — but only if the run's log, hashes, and tree state are intact.**

---

## 1. One-page truth (as of 2026-11-13)

**What it is.** A compiler + verification + RTL-generation stack for AI-accelerator Networks-on-Chip. You describe a fabric as *intent* (JSON: agents, topology, VCs, addresses, clocks, AXI behaviour, workload, requirements). The stack compiles it into content-addressed artifacts, *proves* properties about it (deadlock-freedom, decode equivalence, credit conservation, arbitration bounds), *simulates* it (BookSim / ASTRA-sim / Ramulator), *generates synthesizable SystemVerilog* with real AXI5 adapters, and now *attempts place & route* (LibreLane / Sky130A). A React "Studio" drives all of it over an HTTP gateway.

**What it is trying to achieve.** A single honest pipeline: *declared intent → compiled + certified fabric → measured evaluation → emitted RTL → placed silicon*, where **every** stage either produces machine-checkable evidence or refuses with the exact missing thing named. The pinned representative target is a Mixtral-class inference NoC: **74 agent seats / 81 routers / 8 VCs / 162 shared wires / 128-bit flits**, revision `p-fd7e5e31be77-r02`, design hash `sha256:ab7bce8f…`.

**Where it actually is:**

| Axis | State |
|---|---|
| Compile + certify (14 topology families) | **Working.** 14/14 family rows PASS (lint + sim + scenarios), matrix re-ran on a clean tree 2026-11-12 |
| Composed-family RTL (`final_implementation`) | **12 of 14 true.** SROTA and GEC-hybrid stay false under their own Scope B claim lists |
| Selected 74-seat project (Scope C) | **C1–C5 CLOSED**, C6 (physical) open. Seats run as real endpoints: 5,476/5,476 flows conserved, credits restored |
| 81-router *Chisel* credit-preview emit | **OOMs structurally** (FIRRTL IR blowup, not a heap cap). Cause known, ~2× fixed, needs ~3–4× |
| Emission → synthesis | **Mechanism works; the area fix is in the tree and measured only on the pre-fix template.** 2×2 mesh post-ABC **109,148** cells (attribution inside the working note is unreliable — see §8.2 correction). 4×4 OOM-killed ABC at 14 GB. 8×8 unmeasured |
| Place & route / STA / signoff | **Not achieved.** Earlier Sky130A diagnostic: CTS PASS, post-CTS setup **WNS −4.424 ns / TNS −11.4 µs**, hold clean, stages ≥37 never ran. Containerized LibreLane 3.0.17 works; routing launched at 2026-11-13, no result yet |
| Evaluation (BookSim / ASTRA) | **Working and used.** Backends PRESENT, manifests verified, real spawns proven by `strace` |
| Evaluation (Ramulator / DRAM timing) | **UNSUPPORTED** — binary present, no prepare/execute path, correctly refused |
| Serving / MoE campaigns | **Partial.** Llama path works end-to-end; Mixtral serving semantics + trace input missing |
| Studio (production) | TypeScript clean, 217 Vitest, **115 passed / 4 failed / 13 skipped** Playwright |
| Studio (prototype) | 325/325 Vitest, 8/8 focused Playwright, 56 routes, Tauri desktop variant |
| Full DSE unit suite | 9,530 passed / 8 failed / 55 skipped / 3 errors in 2 h 14 m — **measured but stale**; all 11 failures pass in isolation at the committed head. No green-at-one-commit run exists |
| Product gates | **ALL PASS** on the committed tree (7 gates) |

**The five things actually blocking the goal** (detail in §8):
1. **Physical signoff** — no approved PDK/clock/die-bounds/pinout decision from the operator; no routed design; the one real STA attempt has a −4.4 ns setup violation.
2. **Selected-project Chisel emit** — structural OOM at 81 routers; needs an IR-complexity reduction, not a bigger heap.
3. **Scope B rows** — AXI/OrderingFSM/CDC composition + physical multidrop/STA/parity for SROTA & GEC-hybrid.
4. **Synthesis scaling** — the emitted router costs ~27k post-ABC cells per router; 16 routers OOM the ABC mapper.
5. **One green full-suite run at one commit** — a coordination problem (fence the tree for ~2 h 15 m), not a tooling problem.

---

## 2. What the project is

### 2.1 Origin (still visible in the tree, partly superseded)

VeritX began as a **6-month BTech research programme**: 15 students, 4 tracks, one shared containerized toolchain (`README.md`, `tracks/`).

| Track | Subject | State |
|---|---|---|
| `tracks/onboarding` | toolchain sanity | alive, used as a gate |
| `tracks/t1-kvcache` | KV-cache QoS, gem5/Garnet/ASTRA | **deferred** (gem5 build deferred) |
| `tracks/t2-deadlock` | routing deadlock, BookSim 2.0 | alive |
| `tracks/t3-topology` | topology × traffic, BookSim + Timeloop + Accelergy | **this is the real project** — contains the DSE engine |
| `tracks/t4-formal` | SymbiYosys / Yosys / CBMC | alive |

The research framing (traffic matrices, energy-delay, dashboards) is *not* where the work is. `tracks/t3-topology/dse/` is a ~300k-line Python product that outgrew its track.

### 2.2 What it actually became

Three layers, one pipeline:

```
 ┌──────────────────────────────────────────────────────────────────────┐
 │  Studio (React)  ── apps/studio (production, gateway-backed)         │
 │                  └─ apps/studio/prototype (56-route design surface)  │
 └───────────────────────────┬──────────────────────────────────────────┘
                             │ HTTP  (veritx_dse.gateway.app, FastAPI)
 ┌───────────────────────────▼──────────────────────────────────────────┐
 │  DSE engine   tracks/t3-topology/dse/veritx_dse                      │
 │   model → compiler → verification → backend → product(RTL)           │
 └───────────────────────────┬──────────────────────────────────────────┘
                             │ emits RTL + manifests
 ┌───────────────────────────▼──────────────────────────────────────────┐
 │  Hardware     emitted SystemVerilog → Verilator/Icarus → Yosys →     │
 │               LibreLane (OpenROAD/magic/netgen/klayout) → GDS+STA    │
 └──────────────────────────────────────────────────────────────────────┘
```

### 2.3 The end-to-end goal, stated the way the repo states it

From `docs/product/RTL-FINAL-CLOSEOUT-STATUS.md` (user clarification, 2026-11-11):

> the delivery target is the whole end-to-end product across every declared-supported workload/topology path **at bounded small configurations**. The 36-router / 5-VC / 32-endpoint GEC-MECS job is a first representative case, not the entire target; the 81-router / 74-endpoint stress case is **not** a prerequisite for this bounded scope. Keep `final_implementation` false until all in-scope paths and gates are actually proven; do not silently remove physical/signoff requirements.

And the exit rule (same file):

> Completion means every original P0–P11 acceptance row passes for the approved scope, the required fourteen-family rows are present, the exact selected project is transaction/packet/credit/reset qualified and legally placed on the approved target, the live browser flow reaches those artifacts, and a fresh run reproduces them. Otherwise report the precise remaining OPEN/BLOCKED rows and safe resume point; **never convert an unavailable external decision or unrun stage to PASS.**

---

## 3. Domain model and vocabulary

`CONTEXT.md` is the ubiquitous-language file. Read it (18 definitions). The load-bearing distinctions, because several bugs were caused by collapsing them:

| Term | Means | Do **not** mean |
|---|---|---|
| **Tensor** | identity-bearing element collection with declared byte extent, persists across accesses | "inferred working set" |
| **Tensor shard** | disjoint logical portion at an explicitly owned physical address range | replica |
| **Owner endpoint** | the target that owns a shard's address range | "HBM device number" |
| **Access demand** | explicit READ/WRITE payload including repeats | "collective bytes" / capacity |
| **Transaction padding** | bytes added by memory-transaction granularity | useful bytes |
| **Access completion** | all requests of an access returned | "injection" / durability |
| **Child visibility** | one request's write lands / read snapshot taken | parent atomic commit |
| **Retry snapshot** | retained response of an accepted request, returned on retransmission | cache hit |
| **Endpoint epoch** | lifetime of endpoint retry identities between drained resets | tensor lifetime |

Engineering vocabulary that recurs everywhere:

- **Intent** — the user's declared JSON (workload, fabric, physical, requirements). Declared values are *never* merged with derived values (`P1.2`).
- **Artifact** — content-addressed (`design_hash`) frozen structure: `TopologyArtifact`, `AgentAttachmentArtifact`, `VCResourceArtifact`, `RoutingRealizationArtifact`, `PacketFormatArtifact`, `RouterBehaviorArtifact`, `AddressDecodeArtifact`. Together: `FabricArtifact` (`model/fabric_artifact.py`).
- **Certificate** — the verification verdict object; `certificate.overall == "PASS"` is required to continue.
- **Claim list / scope** — e.g. `COMPOSED_FAMILY`, `RESEARCH_VERILOG`, `TOPOLOGY_ONLY_PREVIEW`, Scope B, Scope C. A claim is only valid inside its scope.
- **Qualification profile** — e.g. `CERTIFIED_BOOKSIM_GEC_HYBRID_V1`, `CERTIFIED_BOOKSIM_SROTA_ROW_FIRST_V1`. Authorises a scientific claim for a specific execution.
- **Refusal** — typed, named outcome with an owner stage.
- **Seat / instance / group** — `agent_group[g]/kind[i]`; seats are physical endpoint slots, instances are compiled agents.

---

## 4. Repository map (only the parts that matter)

```
.
├── HANDOFF.md                     ← this file
├── PROGRESS.md                    ← live chronological ledger (510 lines, newest first)
├── CONTEXT.md                     ← ubiquitous language
├── README.md                      ← still describes the student-toolchain era
├── Makefile                       ← container-driven track commands + release-build + production-gate
├── Dockerfile                     ← the tools image (BookSim, Timeloop, Yosys, CBMC, Verilator…)
│
├── tracks/t3-topology/
│   ├── dse/                       ★ THE ENGINE (881 .py, ~297k lines, 479 test files)
│   │   ├── veritx_dse/
│   │   │   ├── core/              errors, canonical JSON, hashes, locks, paths (no domain)
│   │   │   ├── model/  (74 files) artifacts + intent roots, content-addressed (no I/O)
│   │   │   ├── compiler/           staged derivation + certificates
│   │   │   ├── verification/       CDG proofs, decode equivalence, rank witnesses
│   │   │   ├── backend/ (45)       booksim, astra, ramulator, meshdor, projections
│   │   │   ├── application/ (56)   use-case services (fabric_compiler, capability_truth)
│   │   │   ├── product/ (39)      ★ RTL emission + product service + store + jobs
│   │   │   ├── gateway/ (11)       FastAPI app: the only I/O boundary, /api/v1/*
│   │   │   ├── optimization/, synthesis/, workload/, performance/, simulation/, analysis/
│   │   │   ├── cli/                console entry point
│   │   │   └── reports/
│   │   ├── tests/                 479 test modules — the executable spec
│   │   └── docs/                  DATA-MOVEMENT-EXECUTION.md etc.
│   └── rtl/                       hand-written/generated SV: axi5, cdc, tap_credit,
│                                  srota64_native, mot_htree, multi_seat, *_native families
│
├── apps/studio/                   production Studio (React 19 + Vite, gateway-backed)
│   ├── src/                       pages/, components/, api/, graph/, project/, contract/
│   ├── dist/                      committed build output + SBOM + third-party notices
│   ├── tests/ , e2e/              Playwright + Vitest
│   └── prototype/                 ★ 56-route design prototype (+ Tauri desktop shell)
│
├── contracts/                     frozen wire formats: loom/v1, srota/v1, srota/v2
├── docs/                          the real product surface (see §9)
│   ├── product/                   ★ registries + status ledgers + intents + proposals
│   │   └── evidence/              hashed evidence bundles (deadlock/, final-implementation/)
│   ├── architecture/              FLOW-AND-VERSION-MAP.md, EXECUTION-CLOSURE-*
│   ├── decisions/modules/         17 module ADRs + _root.md (backend.md 148k, model.md 122k…)
│   ├── research/                  per-line working notes (RTL-*, gr00t-*, PHYSICAL-RUNNER)
│   └── design/                    80 stitch prompts, reviews, screenshots
├── scripts/                       gates, runners, manifests, complete_design.py, ci_gate.sh
├── runs/                          ★ 85 run directories, 18 GB — the evidence corpus
└── third_party/                   vendored booksim2 (forked), astra-sim, ramulator2, timeloop…
```

**Files you will spend most of your time in:**

| File | Lines | Role |
|---|---|---|
| `veritx_dse/product/project_top_rtl.py` | **12,342** | The emitter. Routers, TBs, adapters, AXI/CDC/ordering, family templates, manifests. A god file. |
| `veritx_dse/product/service.py` | 5,812 | Product service: projects, drafts, revisions, jobs, evaluation, adoption |
| `veritx_dse/backend/booksim_projection.py` | 3,729 | Native qualifiers + projection to BookSim config |
| `veritx_dse/product/adapter_factory_rtl.py` | 3,552 | AXI5 initiator/target slices, outstanding queues |
| `veritx_dse/model/compile_model.py` | 3,210 | Frozen v1/v3 schema generations |
| `veritx_dse/gateway/app.py` | 1,714 | All `/api/v1/*` routes |
| `veritx_dse/product/gec_mecs_credited.py` | 1,002 | The shared-wire credited fabric transform |
| `veritx_dse/product/gec_mecs_scaled.py` | ~900 | Shape derivation + scaled emitter |
| `veritx_dse/product/physical_runner.py` | 484 | **New, untracked** — the LibreLane stage |
| `scripts/complete_design.py` | — | The 4-stage runner: freeze → compile → hardware → physical |

---

## 5. Architecture

### 5.1 Layering law (enforced, and it matters)

```
core/       error taxonomy, canonical JSON, external codec       (no domain knowledge)
  ↓
model/      artifacts + intent roots, each content-addressed     (semantics, no I/O)
  ↓
compiler/   orchestration: staged derivation, certificates
  ↓
application/ use-case services (fabric_compiler, capability_truth)
  ↓
backend/    execution adapters (booksim, astra, meshardor, ramulator)
  ↓
gateway/ product/   HTTP + product surface; the ONLY I/O boundary
```

Rule already obeyed: `model/` never imports a backend; `application/` owns no filesystem; `product/` is the only layer that composes both. From `docs/architecture/FLOW-AND-VERSION-MAP.md` §2.

### 5.2 The compile flow (verified call paths)

```
intent document (JSON)
   ↓  product/service.py:584  parse_request_doc()      emits V1..V5 object
   ↓  product/service.py:592  migrate_v3_to_v4()
   ↓  application/fabric_compiler.py:233  compile(request, routing_policy)
   │     schema_version 5 → _compile_v5() → V5.to_compile_request_v4()
   ↓  resolve 7 fabric children:
        FabricArtifact = Topology + Attachment + VCResource + RoutingRealization
                       + PacketFormat + RouterBehavior + AddressDecode
   ↓  verification certificate  (overall must == "PASS")
   ↓  backend execution → evaluation evidence
```

Two invariants stated in the map, worth keeping:
- **Refusal is a first-class outcome.** `UNSUPPORTED`/`INVALID` are returned, never raised past the boundary; `UNMEASURABLE` renders differently from `VIOLATED`; absence never becomes an assumed default.
- **Identity is separate from provenance.** The design hash covers science; `synthesis_provenance` and `migration_provenance` do not enter it.

### 5.3 Version lineage — frozen means frozen

```
CompileRequest   v1  test-only; no production caller
CompileRequestV3 v3  FROZEN  <-- still the execution currency
CompileRequestV4 v4  FROZEN  holds typed topology intent
CompileRequestV5 v5  current frontier (clock / sideband / access policy)

RouteArtifact v2  private-channel fabrics
RouteArtifact v3  shared-wire fabrics (opt-in, RouteDecision instead of an int channel)
```

Dependency direction is **downward** (V5→V4→V3). Nothing calls up. Quoting `docs/decisions/modules/model.md:155`:
> **V2 IS FROZEN. V3 IS FROZEN. NEW FABRIC SEMANTICS REQUIRE V4.**
> **NEW HASH DOMAIN** … a v3 and a v4 document can never share an identity by construction — including the migrated pair, which is the point.

**Consequence for you:** archiving a frozen version is not a refactor, it is a rewrite of recorded evidence. Do not do it. `RouteArtifact` v2's integer channel id *is* the identity — it is hashed and compared against simulator dumps.

### 5.4 Backends and exactly what each may claim

| Backend | Binary | State | Can claim |
|---|---|---|---|
| `BOOKSIM_STANDALONE` | `third_party/booksim2/src/booksim` (forked) | PRESENT + build manifest | network completion, conservation, latency, per-class replay, route observation |
| `ASTRA2_EMBEDDED_BOOKSIM` | `third_party/astra-sim/…/bin/AstraSim_BookSim2` | PRESENT + manifest | system makespan (per-dimension analytical legs); refuses unknown config fields by name |
| `ASTRA2_STANDALONE` | same tree | PRESENT | as above |
| `RAMULATOR2_HBM3_V1` | `third_party/ramulator2` | PRESENT | **nothing yet** — `DRAM_TIMING` evaluation returns `UNSUPPORTED` without a prepare/execute path |

The BookSim fork is *dirty by intent*: `matrix` traffic class, GEC topology, tap + VC-range route dumps, bare GEC routing-function fallback, per-channel activity counters (`veritx/channel-activity/v1`). It is synced downstream into ASTRA via `make tool-sync` — run that after any merge touching vendored sources, or the copies drift.

### 5.5 RTL generation path

```
application/fabric_compiler  →  product/project_top_rtl.py :: run_<family>/emit
    ├── NO_PKG / router.sv / noc_top.sv / project_top.sv / adapter_axi5_g*.sv
    ├── ordering_fsm.sv, cdc_bypass.sv / cdc_cell_rtl.py, addr_decode.sv
    ├── destination_adapter.sv (multi-flit reassembly)
    └── tb_*.sv (scenario testbench, 7–15 named scenarios)
        ↓ Verilator (lint + build) and Icarus (sim)
        ↓ product/final_implementation.py → verdict rows A1..A12 / C1..C6
        ↓ product/scope_evidence.py → hashed evidence bundle keyed to design_hash
        ↓ scripts/complete_design.py → freeze / compile / hardware / physical
        ↓ product/physical_runner.py → LibreLane → metrics → gates (STA/DRC/LVS/antenna)
```

Fourteen composed families are emitted: `mesh, torus, concentrated_mesh, ring, gec_mecs, fly, qtree, tree4, flatfly, srota, gec_hybrid, fattree, dragonflynew, kncube`.

### 5.6 Studio — two different applications, do not confuse them

| | `apps/studio` (production) | `apps/studio/prototype` |
|---|---|---|
| Purpose | real product UI, gateway-backed | 56-route design exploration surface + Tauri desktop |
| Stack | React 19, Vite 6, its own `src/api` client | React + its own Vite root (port 5174), Tauri 2.12 |
| Tests | Playwright (132), Vitest 217, python contract tests | Vitest 325, Playwright focused 8/8 |
| State | gateway project store | authored fixtures + browser-local draft; `/gw` proxied to gateway |
| Currently | 3 `app_repro` failures = absent gateway dependency on :8099 | **71 files modified, uncommitted, active lane** |

The prototype's rules are explicit and worth respecting: *"A missing measurement is unavailable, not zero. A gateway/backend capability or a successful model simulation is not hardware qualification."* (`PROTOTYPE-PAGES.md`)

---

## 6. The epistemic system (why this repo is unusual)

This is the part that a new, capable model is most likely to *improve away*. Don't. Each mechanism exists because the corresponding failure actually happened.

### 6.1 `final_implementation` is a computed function, not a flag

`veritx_dse/product/final_implementation.py`:
- rows: `A1..A12` (composed family), `C1..C6` (selected project);
- **a row is CLOSED only when it was supplied evidence that says so.** An absent row is OPEN; OPEN keeps the flag false. There is no way to pass a row by asserting it;
- a row may be closed by an **attributed, dated scope-out decision** — that is how the physical rows A11/A12 close without a PDK (`docs/product/evidence/physical-scope-out.json`);
- `PREVIEW_SCOPES = {TOPOLOGY_ONLY_PREVIEW, CHIPYARD_TOPOLOGY_PREVIEW, RESEARCH_VERILOG}` can *never* carry true.

`veritx_dse/product/scope_evidence.py` gathers evidence and records, for each row, **where it came from and the sha256 of the file**. Rows measured by proofs/gate tests live in per-family bundles `docs/product/evidence/final-implementation/<family>.json`, **keyed to `request.design_hash()`** — so evidence measured on one design can never carry the flag for another.

Bundle shape (real):
```json
{ "schema": "veritx/final-implementation-evidence/1", "family": "mesh",
  "design_hash": "8f00538e…",
  "rows": { "A2": {"status":"CLOSED","reason":"lint clean, simulation green, every scenario true",
                   "measured":{"lint":"PASS","sim":"PASS","scenarios":14},
                   "sha256":{"lint_log":"0539369f…","sim_log":"788b3aff…"}}, … } }
```

### 6.2 `PASS_WITH_NOT_RUN` and the exit-code convention

`scripts/complete_design.py` exits **1** on `PASS_WITH_NOT_RUN`. A matrix that passes every family but never ran the physical stage is *not* a failure of the families, and *not* a release. The runner records it and the exit code preserves the distinction for CI.

### 6.3 Product gates (fail-closed, run as one script)

`make -C tracks/t3-topology product-gates` runs 7 gates, each of which must independently fail closed:

```
check_intent_ontology        cite: anchors resolve (path::Symbol, never :line — line drift was silent)
check_capability_registry    registry ↔ code drift
check_capability_truth       no family may claim a stage it has no implementation for
check_exposure_registry      product surface ↔ capability
check_preset_certification   presets carry real certificates
check_python_deps            dependency pins
check_release_toolchain      runtime image has the tools the build needs
```

Known history: these used to be one recipe line with no `-` prefix, so gate #1 failing *hid* the other five (`OPEN-PROBLEMS.md` GATE-1). If you touch them, preserve independent reporting and non-zero exit.

### 6.4 Staleness and provenance

- `veritx_dse/gateway/staleness.py` flags a gateway whose source files are newer than the process. **Stale ≠ dead.** Fix by relaunching; never by ignoring.
- Every release backend binary has a `.build-manifest.json` (compiler, flags, source-subtree dirty state). Absent/mismatched manifest ⇒ reusable evidence refuses. `make release-build` + `make release-manifest` produce them; `booksim.build-manifest.json` is gitignored build output that **any rebuilder must regenerate**.
- `sequential-gates.sh` writes `toolchain.txt` (repo head, dirty counts, `--version` for python3/gcc/g++/make/verilator/yosys/iverilog) **before** any gate runs.

### 6.5 The "never convert X to PASS" rule

Repeated in three ledgers, verbatim. Practical form:
- an unavailable external decision ≠ PASS;
- an unrun stage ≠ PASS;
- another scope's evidence ≠ your evidence;
- a smaller shape's result ≠ the pinned shape's result;
- a clean lint ≠ a Scope B closure.

---

## 7. Current status (measured, with the evidence path)

### 7.1 The phase ledger (P0–P11)

Authority: `docs/product/INTENT-TO-PLACED-RTL-COMPLETION-PLAN.md` (615 lines) + `docs/product/RTL-FINAL-CLOSEOUT-STATUS.md` (the live ledger).

| Phase | Verdict | What that actually means | Where the evidence is |
|---|---|---|---|
| **P0** freeze target & truth | **BLOCKED overall** | Target + 27 focused contract tests exist; inventory captured; historical reports still need reconciliation; Constellation `KNCubeSourceSpec` absent; PDK/clock/bounds/block-scope approval is an operator gate | `runs/durability-revision-gate-current-tree-20261111/junit.xml` |
| **P1** complete/lossless intent | **PARTIAL** | high-u64 draft entry, legacy snapshot restore, exact 64-bit addresses all fixed; ownership/endpoint identity, protocol compliance, IP materialization, physical-placement fields still partial/open | prototype 325/325 Vitest; backend exact-int test |
| **P2** trustworthy workloads/evaluation | **OPEN** | Real paired run exists (128→256-bit link, completion 11,467→5,955 cycles, −48.07%), non-adopted; live Studio browser flow passes for Llama + selected r02; `DRAM_TIMING` correctly UNSUPPORTED; no hardware calibration (needs P9); no Mixtral serving experiment | `runs/p2-selected-r02-browser-e2e-20261110/`, `runs/p2-paired-gec-width-20261110T164450Z/` |
| **P3** 14 request→hardware bindings | **PARTIAL** | 14/14 family rows PASS with per-family log hashes (165 logs verified); shared fabric emits/lints/sims at the pinned 81/162/8/8 shape; the 74 seats are not that run's traffic endpoints | `runs/release-clean-20261112T020000Z/manifest.json` (sha256 `b375ffca…`) |
| **P4** packet router / native controls | **PARTIAL** | credit/router-policy tests pass; SBY/Z3 bounded credit proof; 9-router Chisel→Verilog→81-pair test passes; **36-router elaboration OOM-killed**; SROTA 64-cell lint 64/64 but 1,861 `UNUSEDSIGNAL` each | `runs/credit-gec-9router-2vc-9ep-v1-20261110T205649Z/` |
| **P5** endpoint transactions | **OPEN(→ largely closed for gec_mecs)** | gec_mecs family: A1–A10 CLOSED, lint 0 warnings, 15/15 scenarios, `final_implementation: true`, 4/4 multiple outstanding requests realized; cross-clock variant measures 2 concurrent acceptances (adapter `W` channel is the limiter, published honestly) | `runs/selected-r02-gec-mecs-seats-c4-20261112/` |
| **P6** one connected selected top | **OPEN** | fabric RTL exists at the selected shape; the *connected* 74-endpoint top with protocol adapters, ordering, CDC and the Chisel VC allocator does not | — |
| **P7** legality vs implementation | **OPEN** | model certificates ≠ emitted-decoder/resource proof for the 74-endpoint target | — |
| **P8** real traffic qualification | **PARTIAL** | 36-router baseline + limited contention; no 81-router transaction/credit/reset run, no full family/profile campaign | — |
| **P9** synthesize/place exact design | **BLOCKED** | see §8.2 — newest state is 2026-11-13 | `docs/research/RTL-PHYSICAL-RUNNER.md`, `runs/PHYSICAL-STATE-20261113.md` |
| **P10** real product flow | **PARTIAL** | production Studio builds; one live Llama compile→verify→evaluate→bundle path; browser→selected-RTL/placement and live cancel/stale not done | `runs/p2-live-browser-e2e-20261110/` |
| **P11** release/reproduce | **OPEN** | dirty tree is not a release snapshot; matrix is `PASS_WITH_NOT_RUN`; no clean independent rebuild of exact selected hardware + placement | — |

### 7.2 The fourteen families

Matrix `runs/release-clean-20261112T020000Z/manifest.json`, re-verified 2026-11-12 on the committed tree:

| Family | lint | scenarios | `final_implementation` | Notes |
|---|---|---|---|---|
| mesh | PASS | 13/13 | **true** | |
| torus | PASS | 13/13 | **true** | even side length is a typed refusal (fork randomises midpoint ties) |
| concentrated_mesh | PASS | 13/13 | **true** | memory endpoint shares a router with 2 initiator seats; demux by destination endpoint id |
| ring | PASS | 13/13 | **true** | **had a real deadlock**, fixed: VC is now the fork's dateline half, not a class; per-VC-class CDG proof |
| fly | PASS | 13/13 | **true** | the "unsupported topology-only preview" sidecar was mesh-derived once — fixed and re-pinned |
| qtree | PASS | 13/13 | **true** | 1,057-router cancel proof lives here |
| tree4 | PASS | 13/13 | **true** | |
| flatfly | PASS | 13/13 | **true** | was silently reshaped (`k=isqrt`, `n=2`); now solved from the artifact + proven by full adjacency equality |
| fattree | PASS | 13/13 | **true** | spellings normalise through one alias table |
| dragonflynew | PASS | 13/13 | **true** | |
| kncube | PASS | 13/13 | **true** | **with** blocker `KNCUBE_NATIVE_EQUIVALENCE_UNVERIFIED` (Constellation source absent, operator-owned) |
| gec_mecs | PASS | 13/13 (15/15 on the AXI path) | **true** | was false at the clean-tree pass (2 dead-declaration warnings); fixed `c3d360e9`, row re-run `aa66b4fe` |
| srota | PASS | 8 | **false** | Scope B: AXI/OrderingFSM/CDC + physical multidrop/STA/parity open |
| gec_hybrid | PASS | 10 | **false** | same |

**Read this table as: 14/14 rows PASS the *composed-family smoke* gate; 12/14 carry the full composed claim; 0/14 are placed silicon.**

### 7.3 The three scopes (do not blend them)

- **Scope A — `COMPOSED_FAMILY`**: "production-ready RTL for a topology at a declared configuration". Rows A1–A10 measured per family; A11/A12 physical, scoped out with a recorded decision.
- **Scope B — shared-wire families** (`gec_mecs` shared path, `gec_hybrid`, `srota`): own claim lists `GEC_MECS_SHARED_NOT_ESTABLISHED` / `SROTA_SHARED_NOT_ESTABLISHED`. **CLOSED:** multi-flit framing, multicast bitmap (80-bit flit, 16-bit router-id bitmap, 20 copies from 8 flits measured), per-(tap,VC) credits (MECS only). **OPEN:** AXI/OrderingFSM/CDC composition, physical multidrop, STA/parity.
- **Scope C — the pinned 74-agent project** `p-fd7e5e31be77-r02`: C1–C5 CLOSED (81 routers / 162 wires / 8 taps / 8 VCs / 128-bit; 74 seats as real endpoints; 5,476/5,476 flows; HEAD/BODY/TAIL + reset recovery). **C6 physical open.**

### 7.4 Test and gate counts (and what each number is worth)

| Suite | Result | Command | Caveat |
|---|---|---|---|
| DSE full unit suite | **9,530 passed / 8 failed / 55 skipped / 3 errors**, 8,055.89 s | `PYTHONPATH=tracks/t3-topology/dse:tracks/t3-topology/dse/tests python3 -m pytest tracks/t3-topology/dse/tests -q -p no:randomly` | measured on a **mid-rework** tree; all 11 failures pass in isolation at the committed head. **Not a green gate.** |
| `ci_gate.sh` (5 stages) | PASS except notes | `scripts/ci_gate.sh` | earlier run: DSE 6,701 passed / 25 skipped |
| Product gates | **ALL PASS** | `make -C tracks/t3-topology product-gates` | on the committed tree |
| Studio production TS | clean | `cd apps/studio && npx tsc --noEmit` | |
| Studio production Vitest | 217 passed | `cd apps/studio && npx vitest run` | |
| Studio production Playwright | **115 / 4 failed / 13 skipped** | `cd apps/studio && npx playwright test` | 3 failures = absent gateway on :8099 (operator-owned); 1 = test isolation, not reproducible |
| Prototype Vitest | 325/325 | `npm --prefix apps/studio/prototype test` | |
| Prototype Playwright (focused) | 8/8 | `npm --prefix apps/studio/prototype run test:e2e` | |
| physical_runner + complete_design | 63 passed | `pytest tests/test_physical_runner.py tests/test_complete_design.py` | |

`FLOW-AND-VERSION-MAP.md` §7 explicitly retracts collection-count matching: the collected count moved 7,783 → 7,784 → 7,786 in one session with no test authored. Use collection only as an import-health check.

### 7.5 Working-tree state right now (important)

```
branch:   integration/studio-reconciliation
HEAD:     d5ce2f7a  (2026-11-12)
status:   2,400 entries = 2,285 untracked + 114 modified + 1 deleted
diffstat: 115 files changed, 5,157 insertions(+), 3,278 deletions(-)
```

The **modified tracked** files are the newest work and are *not* in any commit:

| Area | Files |
|---|---|
| RTL/product engine | `product/project_top_rtl.py`, `adapter_factory_rtl.py`, `ordering_fsm_rtl.py`, `addr_decode_rtl.py`, `gec_mecs_credited.py`, `service.py`, `store.py`, `chipyard_sources.py` |
| Model/verification | `model/gec_hybrid_route.py`, `verification/gec_hybrid_instance.py` |
| Gateway | `gateway/app.py`, `gateway/errors.py`, `application/compile_result_view.py` |
| RTL sources | `rtl/mot_htree/router_template.sv`, `rtl/tap_credit/tap_credit_pool.sv`, `rtl/srota64_native/*`, `rtl/chipyard/CompiledGecCreditPreview.scala` |
| Evidence | 12 bundles under `docs/product/evidence/final-implementation/*.json` (re-pinned) |
| Studio prototype | 71 files + 9 screenshots + 1 deleted (`src/MModulesEditor.tsx`) |
| Docs | `RTL-FINAL-CLOSEOUT-STATUS.md`, `FINAL-IMPLEMENTATION-TRUE.md`, `OPEN-PROBLEMS.md`, 2 research notes |
| Runner | `scripts/complete_design.py` |

**Untracked but load-bearing:** `veritx_dse/product/physical_runner.py` (484 lines, the whole P9 stage) and `docs/research/RTL-PHYSICAL-RUNNER.md`. Both are essential to the newest state and exist only in the working tree.

Untracked scratch that must stay untracked: `.pi/` (142 MB of agent task data), `.playwright-mcp/` (126 MB), `audit/`, `test-results/`, root-level screenshots and `calculator.*`.

### 7.6 Live services (present right now)

```
:8099  python3 (pid 903565)   veritx_dse.gateway.app  — /api/v1/health → status ok, stale:false, source_age_s 0.0
                              BOOKSIM_STANDALONE / ASTRA2_EMBEDDED_BOOKSIM / RAMULATOR2_HBM3_V1 all PRESENT
:5174  node    (pid 641559)   app studio prototype dev server
```

Both are operator-owned in spirit (`docs/product/GATEWAY-RESTART.md`): restart only when needed, then re-check `/api/v1/health` for `stale:false`.

---

## 8. Open problems — the detailed list

Ordered by what actually blocks the goal, not by what is easiest.

### 8.1 Operator-blocked (no amount of code closes these)

1. **PDK decision.** ASAP7 is unobtainable via ciel/volare (only sky130 / gf180mcu / ihp-sg13g2 exist). sky130A is declared *diagnostic*. A 7-nm release needs ASAP7 or an approved equivalent. GF180MCU is the fallback for independent timing confirmation. → `docs/product/PDK-DECISION-REQUIRED.md`, `docs/product/physical-platform-decision.md`.
2. **Die bounds + pinout + CDC plane for the network block.** None exist. Required before any route/DRC claim.
3. **Constellation / KNCube native source.** The agent cannot fetch it; `KNCubeSourceSpec` equivalence stays open by design (`KNCUBE_NATIVE_EQUIVALENCE_UNVERIFIED`).
4. **Scope of the release claim.** "network block placed/routed on sky130A" vs "full-chip signoff" — neither is currently supportable as a signoff claim; the operator must pick.
5. **The pinned request is 7 nm / 1000 MHz** (`process_node_nm: 7`). On sky130A the only field-honest claim is *"implemented on sky130A"*, not 7 nm. Do not silently drop this.

### 8.2 Physical (P9 / C6 / A11 / A12) — the newest, least-documented state

**Authority:** `runs/PHYSICAL-STATE-20261113.md` (untracked, written 2026-11-13) + `docs/research/RTL-PHYSICAL-RUNNER.md`. Older docs saying "no `openroad`/`magic`/`netgen`/`klayout` binary present" are **superseded** — the container image now supplies them.

Working invocation:
```bash
export PATH=/home/datavex/.local/bin:$PATH
export LIBRELANE_BIN=/home/datavex/.local/bin/librelane
export PDK_ROOT=/home/datavex/librelane-spike/pdks
python3 scripts/complete_design.py --request <req>.json --out <fresh dir> \
    --platform sky130A --with-physical --physical-clock-ns 20.0
```
Image: `ghcr.io/librelane/librelane:3.0.17` (openroad, magic 8.3.623, netgen 1.5.316, klayout 0.30.7, sta, yosys-with-plugins 0.62, iverilog).

**Closed:** the stage is wired and gate-checked. `physical_runner.py` takes the RTL file list from the design's own `meta.json`, finds the top module *by name*, constrains **every** clock-like top port, records design/config hashes + tool paths + clock period, and fails a gate that is `NOT_MEASURED`. Gates: unmapped cells, worst-corner setup, worst-corner hold, pooled DRC, LVS, antenna. `--only` reports `PARTIAL`, never signoff.

**Open blockers, in the order you will hit them:**

> **CORRECTION 2026-11-13 (later the same day, after reading the code).** The
> "two router emitters" blocker that `runs/PHYSICAL-STATE-20261113.md` asserts —
> and that this table previously repeated — is **not real**. `project_top_rtl.py`
> has exactly one router template (`_UNIFIED_ROUTER_TEMPLATE`, selected
> unconditionally at `project_top_rtl.py:5369`), and
> `rtl/mot_htree/router_template.sv` is read only by
> `rtl/mot_htree/gen_rtl_htree.py:919-920`, which is reachable only through
> `scripts/rtlgen/gen_rtl.py` (the research/formal/catalog seam) and **never** from
> `complete_design.py` or `project_top_rtl.py` — verified by grep: neither file
> references `gen_rtl_htree` or `rtlgen`. So the divergent `router.sv` hashes are
> **different tree states of one emitter**, not two emitters, and the
> "active (18,546) vs unified (7,507)" cell counts in the working note compare the
> *research* emitter against the *product* emitter — they are not comparable.
> Do not spend time unifying them. The correct first step is row 5: re-emit and
> measure, because the transform is already in the tree and unmeasured.

| # | Blocker | Evidence | Notes |
|---|---|---|---|
| 1 | ~~Two router emitters produce different `router.sv`~~ **RETRACTED — see the correction above** | `68af7691` / `254a07dc` / `93b60a48` are three tree states of the same emitter | Product path = one template (`project_top_rtl.py:5369`). `rtl/mot_htree/*` belongs to the research emitter and cannot affect `complete_design.py`. |
| 2 | Yosys front-end rejected the RTL (`TOK_AUTOMATIC` at `router.sv:237/422`) | `runs/complete-design-mesh2x2-physical-100ns-20261113/physical/runs/design-physical/05-yosys-jsonheader/` | **The recorded artifact `93b60a48` is pre-fix on both counts:** it has **0** `gen_wq`/`gen_we`, still carries the indexed write `q[st_cc][q_cnt[st_cc]] <= in_flit_all[p]` (line 483), and 42 `automatic` occurrences. **At HEAD the emitter has 0 `gen_wq` and no `automatic`-stripping step**; the *working tree* adds both (the strip is a render-time regex in `_render_family_router`, `project_top_rtl.py` just after the token substitution). So this row is fixed **in source, unverified in an artifact**. The separate `return <expr>;` → assignment rewrite and the empty `final begin…end` removal were applied to `mot_htree/router_template.sv` (the research template), which is why that file changed today. |
| 3 | **Synthesis area is the real constraint** | 2×2 mesh, product template, post-ABC: **109,148** cells (21,447 mux2_1, 19,572 dfxtp_2, 11,927 a22o_2, 7,400 a221o_2) — ~27k cells/router | The 18,546 / 159,186 figures in the working note are research-emitter numbers; treat only the 109,148 as the product path's measurement. |
| 4 | **ABC mapper OOM on 4×4** | return code 137 after ~2.5 h, 14 GB exhausted, no cell count | 8×8 died before writing its log ("disk quota exceeded" on `/dev/stdout`) — mitigate with `YOSYS_LOG_LEVEL=WARNING` |
| 5 | **The fix is already in the tree and unmeasured** | Indexed queue write → per-entry enable flops (`gen_wq`/`gen_we`, one flop bank per (queue, entry), decode-into-enable so no wide write mux): pre-map **7,507 → 3,331 cells (−55.6%)**, 64-bit muxes **1,702 → 22 (−98.7%)** | Those percentages were measured on the **HEAD** template (indexed write), i.e. exactly what the working tree replaces. `gen_wq` is present only in the working tree (`git show HEAD:…project_top_rtl.py` → 0 occurrences). **Highest-value next action: re-emit 2×2, confirm `gen_wq` is in the output, re-run `proc; opt -full; wreduce; stat -width`, then ABC.** |
| 6 | Timing | Earlier sky130A diagnostic: CTS PASS, post-CTS **WNS −4.424 ns / TNS −11.4 µs**, hold clean, stages ≥37 never ran. Binding classes moved to 7,212 async-reset-fanout flops + 1,470 reg-reg/out (debug-tap adders in `project_top.sv`) | LibreLane `ResizerTimingPostCTS` was killed twice at iteration ~240 (23,570 violating endpoints, no metrics). Honest remaining paths: reset-tree constraint review + a pipeline stage on the debug-tap adders, then the PDK decision. **No clock tweak allowed.** |
| 7 | Routability | a routing attempt was launched with `PL_RESIZER_TIMING_OPTIMIZATIONS=false` | no result recorded yet |

Also open: `complete-design-p778826bde278-r04-20261113` is **refused by the emitter**, twice, for two different reasons — both real product bugs:
- `flit too narrow for data width`: `link_width 64 < data_width 256 + 6` (`UNSUPPORTED_COMPOSED_FAMILY`, owner stage = RTL generation, module = `ProjectTop`);
- `the memory group must seat exactly one endpoint, got 4`: `multi_instance_seats.py:64-73` requires exactly one `hbm_controller` group with exactly one endpoint, but the request declares 4 HBM controllers.

### 8.3 Selected-project Chisel emit (Scope C / P4) — root-caused, not fixed

**Symptom.** `runMain EmitCompiledGecCreditPreview` dies with `java.lang.OutOfMemoryError: Java heap space` after 1,634 s at `-Xmx6G`. Peaks >99 % in GC. No `CompiledGecCreditPreview.v` is produced.

**Root cause (established, this is not a heap problem).** The Chisel `CreditRouter` carries its route table as a one-hot legal mask over every slot plus a per-slot tag vector, per lane — `lanes × slots` per router:
- **2,966,784 bits** across the router boundary, **2,998,768 FIRRTL reduction nodes** at the 81-router shape (~8.5× the 36-router baseline);
- the cost driver is the **FIRRTL IR**, not the Verilog: at 36 routers the IR is 302.8 MB of text in 2,174,947 statements while the Verilog beside it is 25.6 MB, and **70.5 % of statements are primitive `node` ops**;
- measured thresholds at `-Xmx3G` on this host: **36 routers emits, 49 routers OOMs, 81 routers needs > 6 GiB**.

**Work done.** The route interface was compacted to slot index + valid + tag (24/24 ChiselTests pass, no elaboration warnings). The 36-router credit preview now emits at `-Xmx3G` (historically needed 6 GiB). Verilog 28,640,272 → 25,579,966 bytes — so the emitted artifact is **deliberately no longer byte-identical**.

**Still needed:** that is ~2×, the shape needs ~3–4×. Remaining terms: `CreditRouter`'s `lanes × slots` reductions (~39 % of that family's statements) and `CreditMatch` (33.6 % of the IR). Cost model + IR measurement: `veritx_dse/product/gec_rtl_cost.py` (7 tests). Evidence: `runs/gec-credit-router-compaction-20261111/`.

**Frozen contract facts** (for sizing any rewrite): 1,370 input ports (max 17/router), 10,960 input-VC FIFOs, 10,960 output-stage queues, ~13.3 Mbits of queue payload storage before control/IR overhead.

**Reproducibility caveat that matters:** the failed attempt-4 is **not reproducible from current source**. `CreditRouter.scala` is now `acb7d785…` while attempt 4 was `6ccd1a63…`; only the hash of the old file survives. `SelectedGec.scala`, the contract JSON, `GecContractData.scala` and `SynthAssert.scala` do match. The regenerated input snapshot + per-file hashes are at `inputs/credit-gec-selected-r02-recovery/manifest.json`; a fresh read-only candidate snapshot is pinned at `inputs/credit-gec-selected-r02-current-candidate-20261110T180308Z/`. Do not "reconstruct" the old file.

**Policy:** do not retry the 36-router case by raising the cap. 4-GiB cgroup is the runner policy; earlier 12-GiB approval does not override it. Revisit only after a *measured* elaboration-memory reduction.

### 8.4 Scope B remaining rows (SROTA + GEC-hybrid)

Closed and measured: multi-flit framing (HEAD/BODY/TAIL, packet lock, `WIRE_PIPE`-deep elastic wires), multicast (16-bit router-id bitmap in an 80-bit flit; 20 copies from 8 injected flits; SROTA refuses + counts island-class bitmaps; hybrid mesh carries no multicast flit).

Open, and each is a real engineering line:
1. **AXI/OrderingFSM/CDC composition** — this is exactly what the currently-modified `adapter_factory_rtl.py` / `ordering_fsm_rtl.py` / `cdc_cell_rtl.py` files are working on. `gec_mecs` already emits both CDC directions and passes 14/14 with a cross-clock variant; SROTA and hybrid do not.
2. **Physical multidrop / STA / parity.**
3. Their credit path stays **occupancy-based**, not per-(tap, VC) pools like MECS. Making credits the binding constraint needs a pipelined wire model; today the wire delivers one flit per wire per cycle, so credit is rarely the limiter (`docs/product/proposals/P4-4-3-credit-wiring-spec.md`).

### 8.5 Product / Studio gaps

- **Gateway dependency in Playwright.** 3 `app_repro` failures exist only because `:8099` was absent at run time (`/gw/api/v1/health`, `/projects` → 500, Find-fabrics button stays disabled). Gateway is **running now**; re-run before debugging UI code.
- **One context-dependent Playwright failure** (`native-sweep.spec.ts`): passes 3/3 under `--repeat-each=3`; the full run splits failing ids across two project-hash prefixes under a Playwright config declaring **no projects** → shared Vite/route-mock state, i.e. isolation, not product. Caveat recorded: the measurement was taken while another session was editing 11 files under `apps/studio/prototype/src/`. Settle on a quiet tree.
- **Multi-seat concentrator**: emitted, instantiated and linted, but the *tagless* concentrator answers into `owner_q` (most recently granted seat) and holds the router local port in `S_WAIT_RSP`, so it is correct only at **one outstanding request per router**. Endpoint-tagged families demux by destination endpoint field instead. Closing it means either carrying a tag in the flit for those families (packet-format + adapter + parity change) or proving strict single-outstanding is acceptable for the shape. → `docs/product/proposals/multi-seat-concentrator.md`
- **Multi-seat memory co-seating** is the last typed refusal: co-seating a memory endpoint with initiator seats needs an endpoint-addressed composed fabric.
- **V5 intent materialization** — `DECLARED_V5_EXTENSION_STRUCTURE_ONLY`. Per-item remainders: transactions (generic backend execution open), access policy (emitted but not enforced), sidebands/clocks (structural only; general domain execution open), reset/power (architectural identity + typed refusals), CDC+async-FIFO (no RTL differential), IP catalog (12 templates; 9 honestly refused, each naming its blocker id in `ip_catalog.py ROADMAP`), multi-plane (single plane only).
- **UVM** — generator emits `noc_dut_binding.sv` and it compiles/simulates, but there is no UVM library, no driver/environment, assertion templates unqualified.
- **RTL generation seam** — `scripts/rtlgen/gen_rtl.py` works for a 2-VC connected mesh slice and is **not wired into `compile_model.py`'s `-rtl` path**. Do not label it READY.
- **Concentrated mesh 2:1** — the stated blockers are stale: `CMeshTerminalMap` accepts concentration 2|4, `qualify_native_cmesh_dor` accepts `seat_capacity ∈ {2,4}`, the fork accepts `c==2` for `dor_no_express`, and `ConcentratedMeshIntent(4, 2)` **compiles** (16 routers, `seat_capacity {2}`). The remaining obligation is the **live route/conservation qualification at c=2** plus updating the product refusal text.
- **Optimization definition drops fields** — `_parse_definition` returns `domain, objectives, constraints, method, selection, seed` but the constructor omits `selection`, `seed`, `budget`; no unknown-field rejection. (`docs/product/PRODUCT-CONVERGENCE-V1.md` phase 1.)
- **No multi-objective frontier, no robustness/multi-seed study, no area/power/signoff, no autonomous multi-round search, no LLM-authored score anywhere** — deliberate, documented.

### 8.6 Evidence and process gaps

- **No green full-suite run at one commit.** Needs the real tree, one commit, no other writer for ~2 h 15 m. A worktree is *not* a substitute — it lacks `third_party/` binaries and the accumulated `runs/studio-store/` artifacts. That failure mode is diagnosed in `docs/product/REMAINING-WORK.md` (58 failures: BookSim/ASTRA absent, plus session-scoped fixtures).
- **Disk is a hard prerequisite.** One unbounded suite run peaked at 16 GB of `--basetemp`; three runs accumulated **34 GB**. A full run needs tens of GB free (currently 90 GB free). Shard into four sequential runs, deleting each `--basetemp`. Never free space by deleting `veritx-tmp/release-final*` or `veritx-tmp/selected-r02-*` — they are cited as the release matrix by name.
- **Full matrix has not been re-run at the reworked head.** The clean-tree pass is `020000Z` at `587d45b1` (11/14 true); the `gec_mecs` row was re-run at `aa66b4fe` and pinned. That is the current best state.
- **Release hermeticity** (from the 2026-09-30 audit, still live): GATE-5 (release workflow doesn't run on `integration/**`), GATE-6 (five non-equivalent build environments, digest enforced only on tags), GATE-7 (toolchain guard is a token scan; Ramulator needs `python3-dev` in the runtime stage), GATE-10 (`report` job pulls docker inside a container job that has no docker client; gh-pages action pinned by tag not SHA), GATE-11 (manifest validation doesn't require `container.pinned_by_digest`).
- **Provenance persistence** — INT-1 / NEW-PROV-1 still open.
- **Upstream reuse audit incomplete** (rate-limited, partial licence evidence): **nothing may be vendored** until exact commits, licences, sources and tests are recorded.
- **`runs/veritx-p2p7p11-evidence/`** is dated 2026-11-09 and explicitly stale.

### 8.7 Traps that will waste your first day (each one actually happened)

| Trap | Reality |
|---|---|
| **The installed package points at a different checkout** | `python3 -c "import veritx_dse"` resolves to `/home/datavex/veritx-research/tracks/t3-topology/dse/veritx_dse/__init__.py` — **not this repo**. An editable install shadows the tree and causes five collection errors. Always prepend and assert: `PYTHONPATH=$PWD/tracks/t3-topology/dse:$PWD/tracks/t3-topology/dse/tests` |
| **`pytest-timeout` is not installed in system Python** | The configured `timeout` option is unknown ⇒ the 900-second deadline **is not enforced**. Use `/home/datavex/.cache/veritx-test-tools/pytest-timeout-venv/bin/python` for deadline-enforced runs (verified: sleeping test killed at 0.1 s) |
| **Heavy builds are behind a single global lock** | The private runner's `heavy.lock` is held by whichever Verilator/Chisel build is running. Long-lived pytest suites (`test_gec_mecs_credited_fabric.py`, `test_gec_mecs_pinned_shape.py`) spawn successive compilers and will starve your launch. Wait event-driven for the **exact PID**, don't poll |
| **The runner pre-creates expected output directories** | It refuses paths that already contain files; it also refuses its own empty pre-created dirs in some paths. Use a fresh versioned output dir (`…-v2`, `-v3`) |
| **`TMPDIR` inside the repo breaks the BookSim provenance gate** | It refuses an output dir that is an ancestor of, or inside, the source tree. Use `/home/datavex/veritx-tmp` |
| **Piping a long run through `tail` loses everything** | A 90-minute run hit its limit, the pipe buffered, the log was empty. Redirect to a file |
| **`pkill -f pytest` kills your own shell** | The command string contains "pytest". Kill by PID |
| **`git status --porcelain \| wc -l` cannot tell source from scratch** | It is permanently non-zero here (`.pi/tasks` alone is 2,024 entries). Use `--untracked-files=no` for a real dirty-source signal; the completion runner does exactly this |
| **Verilator "exit 0" with `-Wno-fatal` and ABI stubs is not a lint pass** | That is how the SROTA top lint once reported green with 14,144 `UNDRIVEN`. The strict gate (`scripts/check_srota_hierarchy_lint.py`) denies blanket suppression |
| **Chisel elaboration is memory-fenced** | 4-GiB cgroup / 6-GiB JVM, one CPU, one job. Do not raise caps |
| **`booksim.build-manifest.json` is gitignored** | Any rebuild invalidates the binary↔manifest pair checkout-wide; regenerate with `scripts/write_build_manifest.py` using the Makefile's exact flags |
| **Prototype Playwright uses `/usr/bin/google-chrome`** | Hard-coded path in the config; change it for another host |

### 8.8 Historical audit items that are still live

`docs/OPEN-PROBLEMS.md` (827 lines) keeps the 2026-09-30 audit for lineage. The items that are still real, with the current state:

- **GATE-2** `cite: file:line` is a bounds proxy, not a semantic check → **partially fixed**: anchors became `path::Symbol`. Watch for new `:1` citations.
- **E / SEM-1 / SEM-3** route-dump parser ABI: fixed to one tolerant, versioned authority in `9786b2eb`, but the dump has no version field yet and adding a trailer field still fails the whole line.
- **SEM-2** bus refusal lived only at the `derive_route` call site → now also refused in `from_topology`/`from_adjacency`.
- **SEM-4** `escape_vcs` invisible to native projections → refused at 5 native seams.
- **F / G** `recognize_family` still has no caller; explicit graphs still scored on `ANYNET_MIN_HOPS`, so topology comparisons are exact on structure and approximate on routing. Do not present them as routing-exact.
- **H** the analytical (ASTRA) leg is per-dimension only; irregular graphs, one-way fabrics and buses have only the BookSim leg.
- **I** `_CERTIFIED_FAMILIES` is still only mesh + concentrated_mesh; other families are qualified differently. Capability truth must say *why*.
- **C** bandwidth is aggregate lanes, not per-channel width — this is a **decision**, document it, don't "fix" it.
- **B** the compiler cannot route a shared wire end-to-end in the *generic* sense; the GEC paths work but the `SharedLink`/bus lowering (`RouteArtifact` v3, option B1 with three invariants) is still the designed-but-unfinished path.

---

## 9. Where the truth lives (and which docs are stale)

**Authority order** (highest first):

1. **A run with intact logs + hashes** (`runs/*/manifest.json`) — the only real evidence.
2. **The test suite** — the executable spec (`tracks/t3-topology/dse/tests/`, 479 files).
3. **The registries** — `docs/product/{capability,topology-family,exposure,feature-reclamation}-registry.yaml`, `intent-ontology.yaml`. These are gate-checked against code.
4. **Contracts** — `contracts/loom/v1`, `contracts/srota/v{1,2}`. Frozen.
5. **Live ledgers** — `PROGRESS.md` (chronological), `docs/product/RTL-FINAL-CLOSEOUT-STATUS.md`, `docs/product/REMAINING-WORK.md`, `docs/OPEN-PROBLEMS.md` (top block only).
6. **Module ADRs** — `docs/decisions/modules/*.md` (17 module files + `_root.md`, some 120-150 KB). Authoritative on *why*.
7. Everything else.

**Known-stale documents — do not cite without checking:**

| Doc | Why |
|---|---|
| `README.md` | describes the 4-track student programme; the real product is `tracks/t3-topology/dse` |
| `docs/OPEN-PROBLEMS.md` Parts 1–3 | 2026-09-30 audit; several items closed. Only the "Current status" block is current |
| `docs/product/INTENT-TO-PLACED-RTL-P0-P1-STATUS.md` | 2026-11-09 board; the addenda at the bottom are newer than the tables |
| any doc saying "no `openroad`/`magic`/`netgen`/`klayout` binary" | superseded 2026-11-13 by the containerized LibreLane flow |
| `docs/product/REMAINING-WORK.md` rows about multi-seat "not yet placed" and cmesh 2:1 "producer asserts c==4" | both corrected in the file's own 2026-11-12 section |
| `runs/veritx-p2p7p11-evidence/` | explicitly stale until re-derived |
| the sharded suite run (58 failures) | **invalid as a measurement** — the worktree had no `third_party/` |

**Do not hand-maintain a HEAD in `OPEN-PROBLEMS.md`** — that file's own policy: it has gone `825b45c6` → `246fa118` → `9477c710` while agents worked the same branch. Record dated snapshots or tags only.

---

## 10. How to work — exact commands

### 10.1 Environment

```bash
cd /home/datavex/bruh/veritx-research

# EVERY python invocation needs this, or you import the other checkout
export PYTHONPATH="$PWD/tracks/t3-topology/dse:$PWD/tracks/t3-topology/dse/tests"
python3 -c "import veritx_dse; assert 'veritx-research/tracks' not in veritx_dse.__file__, veritx_dse.__file__"

export TMPDIR=/home/datavex/veritx-tmp     # never inside the repo
mkdir -p "$TMPDIR"
```

### 10.2 The gates

```bash
make -C tracks/t3-topology product-gates                 # 7 fail-closed gates, fast
scripts/ci_gate.sh                                       # product gates + DSE + studio tsc/vitest/pytest
scripts/sequential-gates.sh dse-pytest                   # one stage at a time, logs to runs/sequential-gates-<ts>/
scripts/sequential-gates.sh                              # every stage, stops at first failure
```

`sequential-gates.sh` refuses to start below 4 GiB free RAM or 1 GiB free swap, and writes `toolchain.txt` first.

### 10.3 The full DSE suite (2 h 15 m, needs tens of GB)

```bash
rm -rf "$TMPDIR"/basetemp*                      # reclaim from the previous run
python3 -m pytest tracks/t3-topology/dse/tests -q -p no:randomly \
  > "$TMPDIR/dse-full-suite.log" 2>&1           # redirect to a FILE, never a pipe
```

For deadline enforcement use the venv interpreter:
```bash
/home/datavex/.cache/veritx-test-tools/pytest-timeout-venv/bin/python -m pytest …
```
Shard it (four sequential shards, delete `--basetemp` between) to bound the peak.

### 10.4 RTL / hardware

```bash
# one family, small shape, lint + sim + scenarios
python3 scripts/complete_design.py --request runs/req-mesh4x4.json --out runs/<fresh>/

# the bounded physical candidate
python3 scripts/complete_design.py --request runs/physical-bounded-mesh2x2/input-request.json \
  --out runs/<fresh>/ --platform sky130A --with-physical --physical-clock-ns 20.0

# physical with the containerized toolchain (see §8.2)
export PATH=/home/datavex/.local/bin:$PATH
export LIBRELANE_BIN=/home/datavex/.local/bin/librelane
export PDK_ROOT=/home/datavex/librelane-spike/pdks
```

Result semantics: `result` ∈ `PASS` / `PASS_WITH_NOT_RUN` / `FAIL`, `final_implementation` computed, `blockers[]` typed. Exit 1 on `PASS_WITH_NOT_RUN` is expected, not a bug.

### 10.5 Studio

```bash
# production Studio (:5173) — needs the gateway
cd apps/studio && npm ci && npm run dev
npx tsc --noEmit
npx vitest run
npx playwright test

# prototype (:5174) — proxies /gw to the gateway
npm --prefix apps/studio/prototype run dev
npm --prefix apps/studio/prototype test
npm --prefix apps/studio/prototype run test:e2e
```

### 10.6 Gateway

```bash
PYTHONPATH=tracks/t3-topology/dse VERITX_BOOKSIM_BIN=third_party/booksim2/src/booksim \
  python3 -m uvicorn veritx_dse.gateway.app:app --host 127.0.0.1 --port 8099

curl -s http://127.0.0.1:8099/api/v1/health   # want: status ok, stale:false, backends PRESENT
```

It is **already running** (pid 903565, fresh). Restart only when the source moved.

### 10.7 Release binaries (only if you rebuild a backend)

```bash
make release-build            # builds BookSim fork + ASTRA + Ramulator, writes manifests
make release-manifest-json    # binds the candidate to its facts
```

---

## 11. What I would do next, in dependency order

1. **Freeze and interrogate the current dirty state (hours).** The newest work — `physical_runner.py`, the AXI/CDC/ordering RTL changes, the 12 re-pinned evidence bundles, 71 prototype files — exists only in the working tree. Split it into owned lane commits exactly as was done on 2026-11-12 (`574d5973` rtl, `00bfb780` compiler, `bb4e3ded` studio, `daca1562` gates, `841c3173` evidence/docs, `587d45b1` research). Until then no claim about the current code is reproducible.
2. **Verify the fix that is already in the tree, then measure (§8.2 #2 and #5).** Do **not** start by "unifying two emitters" — that blocker was retracted; the product path has one template. Instead: re-emit the 2×2 mesh from the current tree, assert the emitted `router.sv` now contains `gen_wq`/`gen_we` and **zero** block-local `automatic`, then run `proc; opt -full; wreduce; stat -width` and ABC. That single experiment answers whether the −55.6 % / −98.7 % transform actually reaches the product RTL, and whether 4×4 becomes mappable. Nothing downstream is interpretable until it is done.
3. **Scale the measurement: 2×2 → 4×4 → 8×8** with `YOSYS_LOG_LEVEL=WARNING` (8×8 died writing its log to `/dev/stdout`). If 4×4 still OOMs ABC at 14 GB after the transform, the next lever is the router's `NUM_PORTS × NUM_VCS × BUF_DEPTH` flop bank itself — 27k cells/router at DEG≈4 is a structural cost, not a mapping artefact.
4. **Finish the `p-778826bde278-r04` refusals (§8.2 tail).** Two real bugs: flit width (64 < 256+6) and the single-HBM-controller seat rule vs a 4-controller request. These block the *actual* pinned design, which matters more than the 2×2 proxy.
5. **Get one routed design through LibreLane.** Routing was launched with `PL_RESIZER_TIMING_OPTIMIZATIONS=false` and has no result. Either it routes (then measure DRC/antenna) or it doesn't (then the timing path matters). Report the metrics verbatim via the physical runner's gates.
6. **Take the operator decision set (§8.1) as a blocking input,** not a later step: PDK, die bounds, pinout, CDC plane, and the exact scope of the release claim. Nothing downstream of P9 is honest without it.
7. **Land one green full-suite run at one commit (coordination, not code).** Fence the tree for ~2 h 15 m, four shards, wipe `basetemp` between. That closes REMAINING-WORK item 11 and converts 9,530/8/55/3 from "measured but stale" into a gate.
8. **Scope B AXI/OrderingFSM/CDC for SROTA + hybrid** — the currently-modified files are already on this line. Finish `gec_mecs`'s pattern (both CDC directions, cross-clock variant, 14/14 with the burst + outstanding probes) for the two shared-wire families, keeping the "measured limit published honestly" discipline (the cross-clock `gec_mecs` variant publishes 2 concurrent acceptances although its queue holds 4, and records *why*: `w_busy=1`).
9. **Re-run the fourteen-family matrix at the reworked head.** The clean-tree pass is at `587d45b1`; the head is `d5ce2f7a` plus the working tree. Until the matrix re-runs, 12/14 is a pinned-rows claim, not a matrix claim.
10. **Only then** the Studio Playwright row and the remaining product gaps (§8.5).

**Do not** start with the 81-router Chisel emit unless you are prepared to rework the route representation: it is a structural IR problem with a known 2× improvement and a 3–4× requirement, and the current bounded scope explicitly does not require the 81-router stress case.

---

## 12. Rules of engagement for the next model

1. **Never convert an unavailable decision or an unrun stage to PASS.** This is the project's single most repeated instruction.
2. **Never close a `final_implementation` row by editing a manifest.** The flag is computed; a row closes with evidence or an attributed scope-out.
3. **A refusal is a deliverable.** If the honest answer is "this stage cannot run because X is absent", write that, name the owner stage, and stop.
4. **Do not reset, stash, clean, or `git checkout --` this tree.** 2,400 entries include the newest work and the entire evidence corpus.
5. **Do not touch `.pi/`, `.codex/`, `.impeccable/`, `audit/`, `test-results/`, `.playwright-mcp/`** — excluded non-goals, and the first two are live agent state.
6. **Do not archive a frozen schema version.** It rewrites recorded evidence.
7. **Do not raise a memory cap to make a structural problem go away** (Chisel OOM, ABC OOM). Reduce the structure.
8. **Do not present a family smoke matrix as qualification, a clean lint as a closure, a smaller shape as the pinned shape, or a model simulation as hardware.**
9. **Do not cite a run whose logs, hashes or tree state are broken.** The sharded worktree run exists as a documented example of what not to cite.
10. **Write down what you measured, where it lives, and what it does *not* prove** — in the same breath as doing it. That is the house style, and it is why this repo is navigable at all after months of concurrent agent sessions.

---

## 13. Appendix — index of the most load-bearing files

**Ledgers and status**
- `PROGRESS.md` — chronological, newest-first, 510 lines
- `docs/product/RTL-FINAL-CLOSEOUT-STATUS.md` — P0–P11 ledger + must-do-next
- `docs/product/REMAINING-WORK.md` — prioritized backlog with DoD per item
- `docs/OPEN-PROBLEMS.md` — durable gap list (read the top block)
- `docs/product/INTENT-TO-PLACED-RTL-COMPLETION-PLAN.md` — the authority for phases
- `docs/product/RTL-FINAL-CLOSEOUT-PLAN.md` — execution order, stop rules
- `docs/reports/FINAL-IMPLEMENTATION-HANDOFF-20261111.md` — the `final_implementation` closure chain

**Contract / claim machinery**
- `veritx_dse/product/final_implementation.py` — rows A1–A12, C1–C6, `PREVIEW_SCOPES`
- `veritx_dse/product/scope_evidence.py` — evidence collection + sha256
- `docs/product/FINAL-IMPLEMENTATION-TRUE.md` — the acceptance contract per scope
- `docs/product/evidence/physical-scope-out.json` — the attributed A11/A12 decision
- `docs/product/evidence/deadlock/shared-resource-rank-witness.json` — 144 nodes / 504 edges, O(V+E) rank witness
- `docs/product/evidence/deadlock/arbiter-starvation.json` — bounded-service proof of `ESC_YIELD_K`

**Registries / gates**
- `docs/product/{capability,topology-family,exposure,feature-reclamation}-registry.yaml`
- `docs/product/intent-ontology.yaml` (354 rows, 88 fields)
- `scripts/check_*.py` (7 gates), `scripts/ci_gate.sh`, `scripts/sequential-gates.sh`

**Engine internals**
- `docs/architecture/FLOW-AND-VERSION-MAP.md` — layers, versions, verified call paths, the "where the fat is" analysis
- `docs/decisions/modules/*.md` — 17 ADRs (backend, model, compiler, verification, product, …)
- `veritx_dse/product/project_top_rtl.py` — the emitter (12,342 lines)
- `veritx_dse/product/{adapter_factory,ordering_fsm,addr_decode,cdc_cell}_rtl.py` — the AXI/CDC stack
- `veritx_dse/product/{gec_mecs_credited,gec_mecs_scaled,gec_rtl_cost}.py` — shared fabric + cost model
- `veritx_dse/backend/booksim_projection.py` — native qualifiers
- `veritx_dse/gateway/app.py` — the HTTP surface

**Physical / hardware**
- `docs/research/RTL-PHYSICAL-RUNNER.md` — the P9 runner, its gates and its environment findings
- `runs/PHYSICAL-STATE-20261113.md` — **newest hardware state**, including the two-emitter blocker and the cell-count table
- `docs/product/PDK-DECISION-REQUIRED.md`, `docs/product/physical-platform-decision.md`

**Open proposals**
- `docs/product/proposals/{L3-WORKLOAD-QUALIFICATION, multi-seat-concentrator, kcube-intent, P4-4-3-credit-wiring-spec, runner-release-audit, group-name-attachment-binding}.md`

**Design surfaces**
- `apps/studio/prototype/{README.md, DESIGN.md, PROTOTYPE-PAGES.md}` — 56 routes, live-vs-fixture rules
- `docs/product/PRODUCT-FLOWS.md` — the 24 acceptance flows (F01–F24)
- `docs/design/stitch-prompts/` — 49 page-contract files (incl. `00-shared-contract.md`, `VALIDATION-CHECKLIST.md`)
