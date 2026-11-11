# STAGE 3 — Parameterized RTL generation scope (family-agnostic, mesh8x8 as worked example)

Status: scoping doc only — no production code is changed by this document.
Audience: RTL-generator implementers + operator sign-off.
Goal: turn a compiled `CompileRequestV4` design (STAGE 1 schema + compiler) into
real, parameterized Verilog whose knobs come from the compiled bundle — without
forking the emission pipeline per topology family.

mesh8x8 is the *worked example and acceptance fixture*, not the design's home.
Every module proposed below is family-agnostic; the only per-family input is a
routing-law object plus partition parameters (Stage 1 §6). A new family costs
**one new routing-law implementation, not a new pipeline**.

Read for this doc (all paths repo-relative unless noted):

- Brief inventory: `/tmp/opencode/m5-rtl/mesh8x8-perrouter/` (`PERROUTER_REPORT.md`,
  `inventory.json`, `partition_manifest.json`, `run_perrouter_*.sh`,
  `partition_firrtl*.py`) — see §0.1: absent in this environment.
- `tracks/t3-topology/dse/veritx_dse/product/rtl_export.py` — product preview
  emitter (64-bit / 2-VC), §1.2.
- `tracks/t3-topology/dse/veritx_dse/product/catalog_evaluation.py` —
  `rtl_support` (`:246`), `RTL_EMITTER_VC_COUNT = 2` (`:119`).
- `tracks/t3-topology/dse/veritx_dse/product/rtl_prototypes.py` — 12 research
  rows (`:19-34`), `CandidateNoCTop.v` artifacts.
- `tracks/t3-topology/dse/veritx_dse/model/{compile_request_v4.py,noc_controls.py,
  compile_model.py}`; `tracks/t3-topology/scripts/rtlgen/gen_rtl.py`.
- `docs/design/mesh-stage1-schema-compiler-scope.md` (STAGE 1) — field
  definitions this stage consumes; `docs/research/RTL-M1-M8-HANDOFF-20261108.md`
  and `docs/research/rtl-12of12-plan/EXTERNAL-ARTIFACT-INTAKE.md` for
  caps/evidence constraints.

---

## 0. Design thesis: deep modules, simple interfaces

STAGE 3 is **one deep module** — `PerProjectElaborator` — behind a narrow
interface. Everything else (partitioner, `RouterWrapper`, concat, manifest,
lint ladder) is *internal implementation detail*, not public API:

```text
PerProjectElaborator.elaborate(request: CompileRequestV4,
                               bundle: CompiledFabric,
                               family: RoutingLaw) -> EmissionResult
    EmissionResult = { verilog: bytes, manifest: EmissionManifest,
                       verdicts: (lint, cdc, checker, parity, formal) }
```

- Caller passes **one frozen struct** (request + compiled bundle) and gets back
  **one verified artifact** (Verilog + manifest + checker verdicts). No
  partition flags, no JVM flags, no concat ordering leak to the caller.
- Internal steps (Chisel elaboration per-router → partition → concat) are
  hidden; they may change without breaking the interface.
- Each STAGE 1 field maps to a knob *behind* a module interface (§3): caller
  passes a simple param struct, gets back a verified module + checker verdict.
  The caller never hand-wires a Gray FIFO or a credit loop by hand.

Non-goals restated from STAGE 1 §7: no physical STA/timing closure, no hybrid
credit-contract redesign, no regeneration/re-qualification of the 12 fixed M5
`CandidateNoCTop.v` artifacts (their `proof_status` stays `UNVERIFIED`,
`rtl_prototypes.py`), no Studio UI beyond pass-through of new manifest fields.

### 0.1 Inventory caveat (read first)

`/tmp/opencode/m5-rtl/mesh8x8-perrouter/` was **empty in this environment**
(verified 2026-11-09; same note as STAGE 1 §1). All per-router numbers below
(205 MB ChirRTL, 65 partitions, 1,602 modules, caps, masks, widths) are taken
from the task brief and cross-checked against repo sources where possible.
**Re-verify against `inventory.json` / `partition_manifest.json` before
implementation.** §0.2 records the re-search verdict per number:
artifact-derived values are UNVERIFIABLE; geometry, caps, and the
constraint shape are VERIFIED. Values flagged `[brief]` elsewhere in this
doc follow §0.2.

### 0.2 Evidence verdicts (re-verified 2026-11-09)

A full re-search for the brief inventory found **no surviving artifact**:
`find /tmp -xdev` for `PERROUTER_REPORT.md`, `inventory.json`,
`partition_manifest.json`, `run_perrouter_*.sh`, `partition_firrtl*`,
`CandidateNoCTop.v` returned nothing (only unrelated pytest temp
`inventory` dirs); the same names are absent from the git index and the
working tree (excl. `.desktop-build`, `node_modules`, `__pycache__`). The
artifacts cited by `EXTERNAL-ARTIFACT-INTAKE.md:18` *did* exist at
2026-11-08T15:25:31Z under `/tmp/opencode/m5-rtl/…`; today that tree is
gone (all three cited roots verified absent). `find -size +50M` shows no
~205 MB ChirRTL document anywhere. Every artifact-derived number below is
therefore **UNVERIFIABLE**, not merely unchecked. Two universes must not be
conflated: the *compiler's* mesh8x8 facts (verified, right column) are not
the *research RTL artifact's* claimed facts (unverifiable).

| Claim (stage3 place) | Verdict | Search / source |
|---|---|---|
| 205 MB ChirRTL, 65 partitions, 1,602 modules (§1.2, §4.3, §7 golden) | **UNVERIFIABLE** | No `inventory.json`/`partition_manifest.json`/`CandidateNoCTop.v` in `/tmp`, git index, or working tree; `1602` hits in `runs/` are sha256 substrings, not module counts |
| Masks `4096/0` (§1.2, §3.12) | **UNVERIFIABLE** | Only repeat of stage1 §1, itself brief-sourced; no artifact to read them from |
| 128-bit payload (§1.1, §1.2, §3.8, §7) | **UNVERIFIABLE**, and internally inconsistent | Stage1 §1 says the brief did *not* state a payload width; stage3's 128-bit cannot be brief-sourced. Compiler fixture says `flit_width_bits: 256` (`fixtures/compiled/mesh8x8.json`) — a different fact about the compiler case, not the RTL artifact |
| 4 VCs (§1.1, §1.2, §7) | **UNVERIFIABLE** as an artifact claim | Compiler fixture for mesh8x8 carries `vc_count: 2` (`DOR_XY`/`DOR_XY`); the research-4-VC claim exists only in the brief. Stage1 §1.1 already records this as the conflict the stage exists to surface |
| Buffer depth 15 (§1.1, §3.7, §7) | **UNVERIFIABLE** | No artifact. Verified adjacent facts only: product passes through `input_buffer_depth` with default 8 (`rtl_export.py:54`) |
| `CandidateNoCTop.v` sha prefix `b1558c43…` (stage1 §1) | **UNVERIFIABLE** | No file to hash; no copy in `.desktop-build` staging |
| 64 routers, 224 directed channels = 112 undirected (56+56) (stage1 §1) | **VERIFIED** | `fixtures/compiled/mesh8x8.json`: `routers: 64`, `directed_channels: 224`, 1 component, 0 shared wires; derivation 8×7+8×7=112 undirected matches |
| Caps `MemoryMax=4G`/`Xmx3g`/1,800 s/`-j1` (§1.1) | **VERIFIED** | `RTL-M1-M8-HANDOFF-20261108.md:166` ("Original caps remain… Do not increase caps…") |
| "Serial-lock lanes bottleneck" constraint shape (§1.1) | **VERIFIED** | `EXTERNAL-ARTIFACT-INTAKE.md:10` (operator-relayed report, `:12` marks it reported progress, not a receipt); `-Xmx6g` deviation `:22` |

Rule: nothing above marked UNVERIFIABLE may be encoded as a literal,
default, or acceptance gate until the inventory (or a fresh capped
re-generation) is present to re-derive it.

---

## 1. How mesh8x8 Verilog was actually emitted today

### 1.1 Monolithic elaboration does not fit — the OOM fact

The research path (not the product preview, §1.2) elaborates a full
Chisel/Chipyard `CandidateNoC` for mesh8x8 — 64 routers, 4 VCs, 15-deep
buffers, 128-bit payload `[brief]` — as one Firrtl/ChirRTL document. The
monolithic build **OOMs**, which is why the per-router workaround exists at
all. `EXTERNAL-ARTIFACT-INTAKE.md:10` records the constraint shape: *“Memory
is tight … the serial-lock lanes are the bottleneck now, not heap
exhaustion”* — i.e. the system is throughput-bound on serialized JVMs even
when heap is not the binding constraint.

Caps observed for the per-router runs (hard constraints, not tuning knobs):

| Cap | Value | Source |
|---|---|---|
| systemd scope | `MemoryMax=4G`, `MemorySwapMax=512M` | brief + `RTL-M1-M8-HANDOFF-20261108.md:166` |
| JVM heap | `-Xmx3g` (one active sbt/JVM task) | same, `:166`; deviation to `-Xmx6g` observed once in foreign runs — `EXTERNAL-ARTIFACT-INTAKE.md:22` — do not copy |
| Generation wall | 1,800 s finite cap | `RTL-M1-M8-HANDOFF-20261108.md:166` |
| Verilator / native | `-j1` | same |

> Rule: caps are **not** increased to get a pass, and topology/config is not
> weakened to fit (`RTL-M1-M8-HANDOFF-20261108.md:166`). Partitioning is how
> the design fits — not a bigger heap.

### 1.2 The per-router pipeline as run (worked example)

Brief numbers `[brief]` (re-verify per §0.1):

1. **ChirRTL emission:** single elaboration of `CandidateNoC` → ChirRTL
   document of **205 MB**. This intermediate is the thing that does not fit
   comfortably in one JVM at `-Xmx3g` for downstream passes, so it is kept on
   disk and partitioned rather than held in memory.
2. **Partition:** `partition_firrtl*.py` splits the ChirRTL by router into
   **65 partitions** — 64 router partitions (one per router) + 1 top/link
   partition. Each partition carries exactly one `RouterWrapper` instance
   plus its closure. Partitioning granularity is *per router* because
   routers are the largest near-identical repeated unit; anything coarser
   re-introduces the OOM, anything finer multiplies JVM launches.
3. **Per-partition elaboration:** `run_perrouter_*.sh` drives one
   `systemd-run --scope` JVM per partition (`MemoryMax=4G`, `-Xmx3g`, serial —
   one active JVM). Each emits one Verilog module file.
4. **Concat:** the 65 Verilog files are concatenated (link/top last, or
   order recorded in `partition_manifest.json` — exact order is a concat-
   correctness item, §5) into the single `CandidateNoCTop.v`.
5. **Final count:** **1,602 modules** in the concatenated result, masks
   **`4096/0`** (address/controller mask pair — semantics unverified; STAGE 1
   §1 flags this as *do not build on it*), payload **128-bit**, **4 VCs**,
   buffer depth **15** `[brief]`.

What `inventory.json` / `partition_manifest.json` are for (semantics
inferred from the brief + STAGE 1 §1): `inventory.json` = full file/module
inventory of the concatenated top; `partition_manifest.json` = per-partition
hash + router id + partition order. **Neither file's existence proves
connected Verilog** (`EXTERNAL-ARTIFACT-INTAKE.md:19`) — a partition
collection is 64 unconnected routers until concat + lint (§4, rung L1)
proves otherwise. `WP01/WP06 validate actual profile/source/build/hierarchy
completeness; reject a partial router partition collection as a finished
fabric` (`EXTERNAL-ARTIFACT-INTAKE.md:31`).

### 1.3 Product preview: a different, deliberately smaller emitter

`product/rtl_export.py` is **not** the research emitter and must never be
presented as a realization of the compiled design (its own docstring,
`rtl_export.py:1-5`, and `LIMITATIONS`, `:22-28`):

| Fact | Research mesh8x8 `[brief]` | Product preview (`rtl_export.py`) |
|---|---|---|
| Flit width | 128-bit | **64-bit** (`:132`, `emitted_packet_width_bits: 64`) |
| VCs | **4** | **2** (free/escape; `:132`, `emitted_vcs: 2`; caller passes `--num-vc 2`, `:54`) |
| Router policy | family routing law (DOR) | generic free/escape route table; *“the selected family native routing law … is not generally realized”* (`:24`) |
| Shape guard | none (per-router) | 2–64 contiguously numbered routers, reciprocal point-to-point only (`:44-48`); shared wires refused (`:42`) |
| Address decode | full map in bundle | `addr_decode.sv` — decode only; *“does not implement permissions, protocol adaptation or packet routing”* (`:26`) |
| Verdict | — | `scope: TOPOLOGY_ONLY_PREVIEW`, `final_implementation: False` (`:119-120`) |

Why they differ: the product emitter is a *certified fixed point* (64-bit,
2-VC free/escape, `catalog_evaluation.py:113-119`) used to preview topology
shape, while the research emitter is parameterized (4-VC, 128-bit, native
routing law). STAGE 3's job is to make the *research* emitter parameterized
and honest about which controls it realizes — not to force 4→2 down-conversion.
That refusal already exists as `rtl_support` → `UNSUPPORTED_VC_SCHEME`
(`catalog_evaluation.py:301-309`, STAGE 1 §1.1). STAGE 3 must preserve it.

### 1.4 What this means for STAGE 3 sizing

- 205 MB ChirRTL / 65 JVMs is the *cost baseline* any parameterization must
  beat or match (§4.3). Elaboration memory is dominated by ChirRTL document
  handling, not by Verilog text (1,602 modules is small once emitted).
- Per-router partitioning is a **memory workaround with correctness debt**:
  concat order, duplicate module definitions across partitions, and
  cross-partition wires are all unchecked by construction. §4's ladder exists
  to retire that debt.

---

## 2. Architecture

```text
CompileRequestV4 ─┐
                  ├─▶ FabricCompiler (STAGE 1, existing) ─▶ CompiledFabric (bundle)
                  │         ▲ stages + M1–M4 verdicts
                  ▼         │
           PerProjectElaborator  ◀── RoutingLaw (family object, §6)
           ┌─────────────────────────────────────────────┐
           │ 1. plan: derive knobs from bundle (§3)      │
           │ 2. per-router partition elaboration (Chisel)│  ← internal
           │ 3. concat + dedup + top wiring              │  ← internal
           │ 4. manifest (hashes, masks, lint)           │
           │ 5. verification ladder L1–L5 (§5)           │
           └─────────────────────────────────────────────┘
                  ▼
        EmissionResult { verilog, manifest, verdicts }
```

Interfaces (all frozen dataclasses in, plain verdict out; no callbacks, no
registry lookups in the hot path — the STAGE 1 §4 pattern, reused):

1. `PerProjectElaborator.elaborate(request, bundle, law) → EmissionResult`.
   The *only* public entry for RTL generation. Replaces any direct call to
   `gen_rtl.py` or the per-router scripts.
2. `AdapterFactory.build(ProtocolParams) → (adapter_module, verdict)` —
   behind it: AXI5/CHI/TileLink/custom shims (§3).
3. `AddressDecoder.build(AddressParams) → (decoder_module, verdict)` —
   behind it: range decode + permission firewall (§3).
4. `OrderingFSM.build(OrderingParams) → (fsm_module, verdict)` — behind
   it: ordering/reorder + credit state machine (§3).
5. `CdcCell.build(CdcParams) → (cell_module, verdict)` — behind it: async
   FIFO (Gray) + synchronizer + clock gate (§3).
6. `RouteTable.build(RoutingLaw, TopologyView) → (table, verdict)` — the
   *only* family-specific module besides partition params (§6).

Each `build` is a deep module: caller passes one param struct, gets back a
module + `Verdict(ok, reason, findings)` (same `Verdict` shape as STAGE 1
§4.1). A module that cannot name its owner stage refuses via that `Verdict`.

---

## 3. Parameterization table: each STAGE 1 field → knob behind a module

STAGE 1 field names are from `docs/design/mesh-stage1-schema-compiler-scope.md`
§3–§4 (`AgentIntentV4`, `TrafficPolicyV4`, `NocControls`, `AddressMap`).
“Research status” = what the 4-VC/128-bit mesh8x8 artifact already does
`[brief]`; “Product status” = product preview (§1.3). “New module” =
does not exist today and must be written; “Existing” = a real knob on the
Chisel `NoCParams`/`RouterWrapper` path or product emitter.

| # | STAGE 1 field (source) | Chisel knob (`NoCParams` / `RouterWrapper` / adapter) | Behind module | Research 4-VC | Product 2-VC | Action |
|---|---|---|---|---|---|---|
| 3.1 | `AgentIntentV4.protocol` (AXI5/CHI/TileLink/custom) | Adapter `burst-split` / credit-id remap / packet framing params on the agent shim | `AdapterFactory` | hardcoded shim, one protocol | none (decode only) | **New module.** Caller passes `ProtocolParams{family, data_width, addr_width, max_outstanding, split_at}`; gets adapter + verdict. |
| 3.2 | `AgentIntentV4.max_outstanding`, `split_at` | outstanding-credit table depth; burst-split threshold | `AdapterFactory` (same verdict) | hardcoded | ignored | **New module.** `split_at` on a family with no burst-split → `INVALID` (STAGE 1 §5.9), never ignored. |
| 3.3 | `AddressMap.ranges` + `PermissionWindow` | base/size comparators; read/write gate per range | `AddressDecoder` | map baked into decode | `addr_decode.sv` emitted, no permission | **Extend existing.** Product `addr_decode.sv` (`rtl_export.py:58-61`) covers decode; permission firewall is **new** inside the same module. |
| 3.4 | `TrafficPolicyV4.traffic_class_vcs` + derived `vc_assignment` | `numVCs`, VC class→subset map, escape-VC id | `RouteTable` + router VC alloc | 4 VCs, fixed map | 2 VCs fixed free/escape | **Existing knob, new plumbing.** `numVCs` is already a Chisel param; the class→subset map must come from `derive_vc_assignment_v3` (STAGE 1 §4.2), not a hardcoded 4/2. |
| 3.5 | `AgentIntentV4.ordering` (STRONG/RELAXED/RAW) | reorder buffer enable/bypass; ordering FSM state count | `OrderingFSM` | hardcoded FSM | hardcoded FSM | **New module.** RAW = bypass (no FSM); STRONG = full FSM; RELAXED = partial. Caller passes `OrderingParams{mode, max_outstanding}`. |
| 3.6 | `AgentIntentV4.clock_domain` / crossings (M3) | async FIFO depth, Gray width, sync stages, clock-gate enable | `CdcCell` | single domain (no crossing) | single domain | **New module.** Multi-domain fabrics stay `UNSUPPORTED` until this lands (STAGE 1 §5.7); then `CdcCell` is the only place Gray/sync logic lives. |
| 3.7 | `NocControls.input_buffer_depth_flits_per_vc` (max 64) | per-VC buffer depth (research 15; product passes through at `rtl_export.py:54`) | router `InputBuffer` param, via `PerProjectElaborator` plan | 15 | passthrough, default 8 | **Existing knob.** Already plumbed in product; STAGE 3 must plumb the *derived* value, not a literal. |
| 3.8 | `NocControls.link_width` | flit/link width (research 128-bit vs product 64-bit) | `NoCParams` flit width + adapter | 128-bit | 64-bit | **Existing knob, different defaults.** Must come from `Agent.data_width`, not a literal. |
| 3.9 | `NocControls.arbitration`, `allocator_iterations`, cycle latencies | arbiter type; allocator iterations; route/VC/switch cycle counts | router pipeline params, via plan | hardcoded | hardcoded | **Existing knobs.** STAGE 3 exposes them as typed plan fields; unknown arbiter string → `INVALID`, not a default. |
| 3.10 | `NocControls.mcast_groups`, `mcast_setup_cycles` | multicast group count; setup cycles | multicast unit | none (unicast mesh) | none | **New module** only for families that need it; mesh path passes `0` and the module is not emitted (see §6). |
| 3.11 | `MeshIntent` shape (side, concentration, terminals/router) | `NoCParams` geometry; `RouterWrapper` degree; partition params | partitioner (internal to elaborator) | 8×8, c=1, 65 partitions | 2–64 contiguous only | **Existing, now internal.** Partition params become elaborator-internal config, not caller flags. |
| 3.12 | Masks `4096/0` `[brief]` | address/controller mask pair on top | `AddressDecoder` + manifest | baked in ChirRTL | n/a | **Keep as manifest field, not a knob** until semantics are established (STAGE 1 §1: *do not build on it*). Recorded, hashed, not synthesized from. |

Worked example (mesh8x8 row): `protocol=axi5, ordering=strong,
max_outstanding=16, split_at=64` (STAGE 1 §3.2) → `AdapterFactory` emits the
AXI5 shim with burst-split at 64; `traffic_class_vcs=[data→VC0, control→VC1]`
vs derived 4 VCs → `RouteTable` binds DOR + VC subset; `clock_domain` single
→ `CdcCell` emits nothing (no crossing); `input_buffer_depth=15`,
`link_width=128` → Chisel params. The mesh8x8 `CandidateNoCTop.v` is the
golden output this plan must reproduce bit-for-bit when given the same bundle
(see §7 acceptance).

---

## 4. Per-project emission pipeline

`PerProjectElaborator` owns the whole pipeline; internal ordering below is
**not** a public contract — but the idempotence and invalidation rules
(§4.2) **are**.

### 4.1 Steps (internal, in order)

| Step | What happens | Who owns it |
|---|---|---|
| S0 | `FabricCompiler.compile(request)` → `CompiledFabric` (STAGE 1 gates M1–M4 already passed) | existing |
| S1 | **Plan:** project bundle → per-field knob struct (§3). Any knob the bundle names but no module can realize → `UNSUPPORTED` + owner stage (never silent down-project). | elaborator |
| S2 | **Per-router partition elaboration:** split ChirRTL by router (65 partitions for mesh8x8 `[brief]`); one `systemd-run` JVM per partition, `MemoryMax=4G`, `-Xmx3g`, serial (§1.1 caps). | partitioner (internal) |
| S3 | **Concat:** concatenate partition Verilog in `partition_manifest.json` order; dedup identical module definitions (hash-equal → keep one; hash-different same-name → hard fail). Top module last. | concat (internal) |
| S4 | **Manifest:** write `inventory.json`-compatible manifest: per-file sha256, partition hashes, masks `4096/0` recorded, module count (1,602 `[brief]`), design hash. | elaborator |
| S5 | **Lint ladder:** run §5 rungs L1–L5; attach verdicts to `EmissionResult`. | elaborator |

### 4.2 Idempotence + content-hash invalidation

- **Design identity** = `CompileRequestV4.design_hash()` (`compile_request_v4.py:181-206`,
  `canonical_dict`). Same hash + same bundle hash + same routing-law version
  ⇒ byte-identical Verilog expected; the plan step re-runs and the
  `EmissionResult` hash must match the previous run's or the run FAILS
  (determinism gate, §7).
- **Partition invalidation:** a partition file is reusable iff
  `sha256(partition_source) + routing_law_hash + knob_struct_hash` matches
  the previous run's `partition_manifest.json`. Router *i* changes ⇒ only
  partitions whose knob struct covers router *i* (its adapter, decoder slice,
  FSM, CDC cell, route table) are re-elaborated; the other 63 are reused by
  hash. Top partition invalidates when any router partition invalidates.
- **No invalidation by timestamp.** File mtime is not identity. Content hash
  only — the `rtl_prototypes.py:_version` (dev/ino/size/mtime) is a *cache
  key for file serving*, not a correctness identity, and must not be reused
  as one.
- **Bundle → knob hash chain:** `knob_struct_hash = H(bundle_hash,
  law_hash, module_versions)`; recorded in the manifest so any reviewer can
  re-derive why a partition changed.

### 4.3 Cost / time / memory per step (from the report, `[brief]` + caps)

| Step | Cost basis | Time | Memory |
|---|---|---|---|
| S1 plan | pure Python projection over bundle | seconds | MBs |
| S2 partition elaboration | 65 JVMs × `-Xmx3g` serial (mesh8x8); 1,800 s total cap | ~65 × per-JVM (minutes each); serial lock is the wall, not heap (`INTAKE:10`) | per-JVM peak ≤ 3 GB heap + scope overhead ≤ `MemoryMax=4G` |
| S3 concat | 205 MB ChirRTL-derived text I/O; 1,602 modules | seconds–minutes (I/O-bound) | must stream, not hold all in RAM |
| S4 manifest | hashing 205 MB + Verilog | seconds | streaming hashes |
| S5 L1 lint | Verilator on concatenated top | minutes (`-j1`) | ≤ `MemoryMax=4G` |

Recovery cost on failure: re-run from the first invalid partition (hash
chain, §4.2) — not from zero. Concat/manifest steps are re-run freely; they
are cheap and deterministic.

---

## 5. Verification ladder

Each rung has a crisp “established” criterion. A rung that has not run is
`NOT_RUN`, never `PASS` (the `rtl_export.py:98` pattern — lint reports
`NOT_RUN` when Verilator is absent, and raises on failure).

| Rung | What runs | “Established” means |
|---|---|---|
| **L1 Verilator lint** | `verilator --lint-only -sv -Wall -Wno-fatal --top-module CandidateNoCTop` on the concatenated file (product already does this shape at `rtl_export.py:101`) | exit 0 **and** `%Warning` count recorded; `clean` only if 0 warnings (`rtl_export.py:103-107`). Warning-bearing PASS is reported as such, never as clean. |
| **L2 CDC check** | structural check: every `CdcCell` crossing has Gray FIFO + ≥2-flop sync; no combinational cross-domain path. Today: single-domain mesh ⇒ vacuous PASS with 0 cells. | 0 un-synced crossings in the netlist; each crossing names its `CdcCell` instance. |
| **L3 Protocol checker** | adapter assertions: burst-split at `split_at`, outstanding ≤ `max_outstanding`, AXI5/CHI/TileLink handshake rules per family | 0 assertion violations in directed + random traffic for the emitted adapter family. |
| **L4 BookSim ↔ RTL sim parity** | BookSim (reference model) vs Verilator RTL on the same traffic: route decisions, packet counts, flit counts, drain | exact packet/flit conservation match (accepted == delivered, drain exact — the standard the historical ring run is held to, `RTL-M1-M8-HANDOFF-20261108.md:103`: *16,385 packets, 69,637 flits, exact drain*). Eject-only traces do **not** count. |
| **L5 Formal (deadlock / address)** | ① deadlock: CDG acyclic per VC (reuses STAGE 1 `find_cycles`, `compile_model.py:451`) + credit-conservation invariant; ② address: decode table ≡ bundle `address_decode` entries, no overlap, permission windows respected | ① no CDG cycle reachable under emitted VC assignment; ② decode equivalence proven or exhaustively linted per entry. |

Rules: L1 is required for any `EmissionResult`; L2–L3 required when the
corresponding module was emitted; L4 required before any *qualification*
claim; L5 required before any *deadlock-free* claim. No rung may be skipped
by weakening the topology or caps (`RTL-M1-M8-HANDOFF-20261108.md:166`).

---

## 6. Generalization risk: what transfers vs what is mesh-specific

### 6.1 What transfers unchanged (family-agnostic core)

| Item | Transfers to all 12 families? | Notes |
|---|---|---|
| `PerProjectElaborator` interface (`request+bundle+law → verilog+manifest`) | **Yes** | Caller never sees Chisel/partition/concat (§2). |
| Partitioner + concat + dedup + top wiring | **Yes** | Per-router granularity for mesh; per-*switch* for fattree/tree; per-*group* for GEC/SROTA — granularity is a partition-param, not code. |
| Manifest (hashes, masks recorded, module count, design hash) | **Yes** | Masks recorded as data (§3.12) until semantics established. |
| Lint ladder L1–L5 | **Yes** | Criteria above are family-independent. |
| `AdapterFactory` / `AddressDecoder` / `OrderingFSM` / `CdcCell` | **Yes** | Param structs carry family-specific *values*, not family-specific code. |
| Idempotence / hash-invalidation (§4.2) | **Yes** | Content-hash chain is pipeline-level. |

### 6.2 What is routing-law specific (one new impl per family)

| Family (`rtl_prototypes.py:19-34`) | Law | Extra risk |
|---|---|---|
| `mesh` (mesh8x8, cmesh) | DOR, `dim_order` | none — baseline. CMesh adds concentration terminals/router. |
| `torus8x8`, `ring` | dateline | VC floor (`dateline_vc_floor`, `compile_model.py:2882`); dateline cut must be in the emitted route table, not just TC. |
| `gec_mecs` | MECS taps | multi-drop taps share VCs (`multidrop_degree`, `:2843`); shared-wire semantics — product emitter **cannot** serve these (`UNSUPPORTED_SHARED_WIRE`, `catalog_evaluation.py:317-324`). |
| `gec_hybrid` | hybrid phase + tap | full-envelope rewrite (`compile_model.py:3067`); mesh/express parallel links must preserve `(output, VC)` identity (M4 seam, `RTL-M1-M8-HANDOFF-20261108.md:87-94`). |
| `srota8x8` | shape/rank | shape/rank floors (`:2899`, `:2921`); dynamic D+T/FIU/telemetry still incomplete (M4). |
| `fattree` | native NCA | **NCA is not in the current tree** as a named function (STAGE 1 §6) — the law object may be new code, not just new params. |
| `flatfly`, `fly64`, `qtree`, `tree4` | native (fixed) | fixed radix/levels (`topology_intent.py:144, 163`); partition shape differs (no mesh grid). |

**Recovery-cost statement:** adding a family = one `RoutingLaw` impl +
partition params + (if needed) one adapter family in `AdapterFactory`.
No new pipeline, no new manifest schema, no new ladder. If a family needs
any of those, that is an elaborator bug (STAGE 1 §6 acceptance rule, reused).

### 6.3 Per-router partition reuse assessment (mesh8x8 → others)

- **Reuse across runs of the same design:** high — most partitions are
  identical routers; hash invalidation (§4.2) means a one-router knob change
  re-elaborates ~1–2 partitions of 65.
- **Reuse across families:** low at the *module* level (different router
  degree/VC/route table ⇒ different `router_edges.tsv`/`terminal_map.tsv`),
  **high at the *pipeline* level** (same partitioner/concat/manifest/lint
  code). Expect to reuse the pipeline and rewrite the law — not the reverse.
- **Shared-resource families** (GEC-MECS 32 groups/96 taps, SROTA 224
  groups/896 taps, `RTL-M1-M8-HANDOFF-20261108.md:135`) cannot use naive
  per-router partitioning: shared-channel scheduling state spans routers.
  Those need group-granular partitions + the `shared_channel_scheduler.sv`
  binding (M7). This is the largest generalization risk after §6.2's NCA.

---

## 7. Test plan (acceptance for STAGE 3)

All tests in `tracks/t3-topology/dse/tests/`; names are the contract.

- `test_stage3_elaborator_interface.py` — `PerProjectElaborator` imported
  standalone; no `partition_firrtl`, no `RouterWrapper`, no JVM flags in its
  transitive imports (import-lint, mirroring STAGE 1 §8.3). Same
  request+bundle+law twice → identical `EmissionResult` hash (determinism).
- `test_stage3_mesh8x8_golden.py` — mesh8x8 bundle → emitted Verilog
  reproduces the golden `CandidateNoCTop.v` module count (1,602 `[brief]`),
  masks `4096/0`, 4 VCs, 128-bit, depth 15. Any knob change that alters the
  golden output is a spec change, not a silent drift.
- `test_stage3_knob_mapping.py` — parametrized over §3 rows: each STAGE 1
  field change produces exactly the predicted knob change (and no other).
  `split_at` with `protocol=chi` → `INVALID`; write to read-only
  `PermissionWindow` → `INVALID` at `ADDRESS_DECODE`.
- `test_stage3_invalidation.py` — change one router's knob in the bundle →
  exactly its partition(s) re-elaborate (hash chain §4.2); change nothing →
  zero partitions re-elaborate (byte-identical `EmissionResult`).
- `test_stage3_ladder.py` — L1 lint on golden output (exit 0, warning count
  recorded, `clean` iff 0 warnings); L2 vacuous PASS for single-domain mesh;
  L4 conservation on the frozen ring packet checkpoint (16,385 packets /
  69,637 flits / exact drain) when a sim harness is present, `NOT_RUN`
  otherwise (never fabricated PASS).
- `test_stage3_family_swap.py` — same elaborator, torus law swapped in:
  dateline partition emitted, no pipeline code changed (the §6.2 acceptance
  rule, mechanically).

---

## 8. Top risks (operator attention)

1. **OOM / memory budget.** 205 MB ChirRTL + 1,602 modules under
   `MemoryMax=4G` / `-Xmx3g` serial JVMs. The 65-JVM serial lock is the
   throughput wall; any parameterization that holds the full ChirRTL in one
   JVM heap regresses to the monolithic OOM. Mitigation: streaming partition
   + streaming concat (§4.3); never raise caps (`Handoff:166`).
2. **Concat correctness.** 65 partition files → 1 top: order, duplicate
   module definitions, cross-partition wires, and the 1,602 vs 1,602+1
   module-count check are all silent-failure surfaces. An inventory file is
   not proof of connected Verilog (`INTAKE:19`). Mitigation: hash-equal
   dedup rule + hard-fail on hash-different same-name (§4.1 S3), L1 lint on
   the concatenated top (§5).
3. **Sim parity (BookSim ↔ RTL).** Packet/flit conservation + exact drain is
   the only honest parity bar; eject-only traces and lint-only PASS do not
   establish it (`Handoff:103-114`, `rtl_export.py:27`). The protocol checker
   (L3) and formal deadlock/address rungs (L5) must not be claimed from
   Python-model tests alone — several M1–M8 lanes already shipped Python-only
   “passes” for uncompiled Chisel (`Handoff:54, 133`). Mitigation: L4/L5
   criteria written as *established* means (§5), `NOT_RUN` never `PASS`.

## Appendix — module inventory (implementation checklist)

| Module | Status | File (proposed) |
|---|---|---|
| `PerProjectElaborator` | **new** (deep module, the public API) | `application/per_project_elaborator.py` |
| `AdapterFactory` | **new** | `application/adapter_factory.py` |
| `AddressDecoder` (+ permission firewall) | extend `product/addr_decode_rtl.py` | `product/addr_decode_rtl.py` |
| `OrderingFSM` | **new** | `application/ordering_fsm.py` |
| `CdcCell` | **new** | `application/cdc_cell.py` |
| `RouteTable` | **new** (family laws plug in here) | `application/route_table.py` |
| Partitioner + concat (internal) | extract from `run_perrouter_*.sh` / `partition_firrtl*.py` | `application/per_router_partition.py` |
| `FabricCompiler` + STAGE 1 M1–M4 | existing, unchanged by STAGE 3 | `application/fabric_compiler.py` |
| Product `rtl_export.py` preview | existing, unchanged; STAGE 3 does not call it | `product/rtl_export.py` |
