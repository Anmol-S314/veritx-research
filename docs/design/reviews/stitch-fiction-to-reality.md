# Stitch fiction → reality: filed items and conversion ladder

Source mockups: `docs/design/stitch_veritx_studio_eda_frontend/`
(`optional_agents_workload_translation`, `design_fabric_topology`).
Element-by-element review revealed ~70% of the data panels are fiction.
This doc files the two closeable gaps and grades every fictional panel
by what it would actually take to make it real.

## Filed work items

### WT-01: Assumption status taxonomy in workload-translation proposals

**Problem.** `translate_workload` returns `assumptions: string[]` — a flat
list. An unresolved guess ("assumed cold-cache") is indistinguishable
from a decided fact, so the reviewer cannot tell what still needs a human.

**Change (backend).** In `product/service.py::translate_workload`, require
each assumption to carry `{text, status}` with
`status ∈ {bound, inferred, unresolved}`, and validate the enum alongside
the existing shape checks. Unresolvable prompt gaps must be returned as
`unresolved`, never silently defaulted. `candidate_request` hashing is
unaffected (assumptions are not design intent).

**Change (frontend).** `AgentConsole.tsx` proposal review: render the three
groups separately; block the reviewed-checkbox until every `unresolved`
item is explicitly acknowledged (separate checkbox per item or one
"accept open assumptions" box — reviewer UX choice, recorded in the
downloadable proposal JSON).

**Acceptance.** Backend test: a prompt with a gap yields at least one
`unresolved` assumption and adoption still pins the draft hash. Playwright:
stale/new proposal with unresolved items cannot be adopted without the
acknowledgement; the proposal JSON records it.

### WT-02: Adopt Stitch's honest sentences into prototype notices

**Problem.** The mockups phrase disclaimers better than we do
("declaring 'ResNet50' does NOT imply traffic", "modeled as synthetic
link injector"). Free improvement, frontend-only.

**Changes.**
- `AgentViews.tsx` fixture notice → add: "Declaring an application name
  does not imply its traffic pattern."
- `AgentConsole.tsx` translation notice → add: "Proposals are synthetic
  injection intent; no compute datapath is synthesized."
- `LiveAnalysis.tsx` trace notice → already close; add: "Direction is
  declared, not observed." (verify current text first).

**Acceptance.** Existing Playwright suite passes; no backend change.

## Conversion ladder: what each fiction costs

Rule of thumb used below: a panel becomes real only when a named backend
authority produces it. Declared data (render what the draft says) is free;
measured data needs an execution or proof authority; anything else is a new
product, not a UI task.

### Workload translation

| Mockup panel | Verdict | What makes it real |
|---|---|---|
| ONNX attach + Batch/FP16 parse | **Far — new importer** | An ONNX→WorkloadGraph importer with provenance and refusal on ambiguity. No ONNX code exists in the repo. The honest interim is what we have: text requirement + base request. Do not fake parsing with filename-derived parameters. |
| Assumption ledger (bound/inferred/unresolved) | **Near — WT-01** | Schema change only, no new authority. The model already returns assumptions; it just needs the taxonomy enforced. |
| NL phrase → primitive mapping | **Near — proposal metadata** | Store phrase→operation links inside the proposal record next to `sections`. Real once the model emits them and the backend validates the operation side against the workload schema. No execution needed — it is traceability, not measurement. |
| Per-primitive VALIDATED / REVIEW statuses | **Far — per-op execution authority** | Each primitive would need isolated lowering + BookSim execution (`backend/booksim_projection.py` already lowers whole workloads; per-op isolation is the new part). Until then, no status column — statuses without an authority are the exact fiction to avoid. |
| Phase-profile chart (0–700k cycles) | **Near — render declared windows** | If primitives ever carry declared cycle windows, charting them is free (declared data). Must be labelled "declared windows, not observed." |
| Lowering preview (BookSim config code) | **Near — read-only projection** | `booksim_projection` already derives configs; exposing the derived (not hand-written) config text for the *current draft only* is a display task. Never show it for a proposal that was not lowered. |
| REQ-CAND derived criteria | **Far — requirement-derivation authority** | Model-suggested candidate requirements are fine as proposal text; *binding* verdicts need evaluation against a run. The adoption gate must keep refusing to bind them (as it does today). |
| Sim #403 progress, SystemC model, DRC, daemon version | **Out of scope** | Different backends (SystemC, DRC) or pure chrome (daemon). BookSim standalone is the execution authority; a second backend is a product decision, not an iteration. |
| GGUF engine identity, register-map stripping | **Trivial but pointless** | Report `model` from capabilities (already shown). Stripping is moot — nothing sensitive is attached by design. Keep the design minimal instead. |

### Fabric topology

| Mockup panel | Verdict | What makes it real |
|---|---|---|
| Utilization / heatmap / skew / deadlock-probability layers | **Far — per-link measurement authority** | Needs per-directed-link counters out of BookSim execution, sealed into the run bundle, then rendered as overlays labelled by run and window. This is the single most valuable far item: it is the same backend we already run, just with link-granular evidence plumbed through. No overlay entry before the bundle carries it. |
| Saturation %, simulated-vs-expected latency | **Near — derived from existing runs** | Completion cycles, packet/flit latency averages, and windows already exist per run (`metric_contracts.py`). A per-run "expected vs observed" panel is honest arithmetic *if* the expectation is a declared requirement, not an invented baseline. Never compare across runs except through `/compare`. |
| Arbitration policy editing (WRR/strict/age-based) | **Near — expose existing control** | `arbitration` is already a canonical NoC control (`model/router_behavior.py`). The structured draft editor currently exposes only `link_width`; adding the arbitration selector is a frontend task plus a vitest/Playwright case. No backend change. |
| VC counts, buffer depth, protocol labels on attachments | **Near — schema extension** | Requires compiler support for the new fields (they enter `design_hash`). Small individually; each needs its own acceptance test. Until then: absent, not zero-filled. |
| Problems drawer, Z3 "deadlock-free proof signed off" | **Out of scope — new proof authority** | A formal backend is a separate wave (like Wave F power). The honest counterpart already exists: the obligations register (`OBL-*`, open/blocking, never certificates). Do not render proof-shaped UI without a prover. |
| RTL generator / export, TSMC target, power mW | **Out of scope** | No RTL emitter, no target qualification, power explicitly deferred. Manifest export stays descriptive. |
| Die footprint, cursor coordinates, auto-layout lock | **Free — declared geometry** | The topology document already carries coordinates and counts; presenting them (with hashes) is display work. Footprint *dimensions* in mm need a declared process assumption — label it or omit it. |

## Standing policy (unchanged)

No panel renders a number without a named authority. Missing metadata is
never equality, never zero-filled, never a default that looks measured.
Mockup language may be borrowed; mockup data may not.

## Spec-grounded corrections and deltas (SSM-UARCH-001/002/003 rev 0.3)

Read `~/Downloads/SSM-UARCH-{ROUTE-001,VC-002,TOPO-003}_rev0.3`. Only 3 of
9 hardware sub-documents; parent arch (NOC-001), telemetry (#4), RAS (#5),
packet header (#8), and config (#6/#9) are referenced but not provided.
Corrections to the mockup diff above are marked CORRECTION.

### What the specs actually say

- **ROUTE-001**: O1TURN-XY over MECS (row-first / column-first / Valiant,
  chosen once per flow-epoch at the FIU; in-network traversal is
  deterministic, `srota_route_compute` has no congestion inputs). Proof
  obligations F1 (deadlock freedom) / F3 (livelock) / F4 (starvation) /
  F6 (ordering), with SVA assertions (`a_single_turn`,
  `a_valiant_stable`, `a_stage_grants_disjoint`,
  `a_shape_mix_observable`) and a generator-built static CDG check plus a
  4x4 model check. Gains table carries a Status column
  (analytic / simulation-pending M1, M3 / qualitative) and a "does NOT
  claim credit for" section per target.
- **VC-002**: Plane D carries **no per-port VC arrays** — 2-flit staging
  latch per input plus one shared 8-flit side buffer per router
  (MinBD-cited ratio). Plane C is conventional 3-VC (REQ/RSP/SNP).
  Credit withholding is the backpressure mechanism; assertions
  (`a_no_grant_wo_credit`, `a_sb_no_overflow`, `a_no_bypass_reorder`,
  `a_loss_after_both_stages`) plus VC-C1/VC-C2 properties.
- **TOPO-003**: 16x16 concentrated mesh (c=4), MECS express layer, any
  router reaches any other in <=2 network hops, O(k) wiring vs O(k^2)
  flattened butterfly, multicast-for-free via multidrop broadcast, QoS
  islands in shared-resource columns, drop cell as the timing gate.
  Generated (shape depends on k/c/width/planes/islands) vs hand-written
  (config-independent leaf RTL) split is defined; register/counter maps
  (§13: discovery, control, status, performance/congestion counters).
- **Headline open items**: RT-R7 (F1 does not cover the
  `ROUTE_PATH_EN=0b111` default — two-node cycle
  row[0]->col[0]->row[0]; "nothing else in this document matters until it
  is resolved"); VC-R5 (port enumeration inconsistent: 8 vs <=6 vs P=12
  — blocks RTL); T-R1 (drop-interface area/timing at 512b/4GHz erodes the
  express advantage — dominant risk); T-R5 (interleaved tenant allocation
  breaks island confinement); VC-R1 (side-buffer capacity inherited from
  MinBD, not re-derived); RT-R8 (Valiant intermediate not cached —
  resolved in rev 0.3 text, needs implementation confirmation).

### Corrections to the earlier diff

- CORRECTION — "DOR-XY, deadlock safe": doubly wrong. The algorithm is
  O1TURN-XY, and safety is **open and blocking** (RT-R7). The mockup's
  I-ROUT-1049 "deadlock-free proof signed off by Z3" is contradicted by
  the spec itself. This stays an open obligation, never a badge.
- CORRECTION — "5-VC per port": no such number exists. Plane D has zero
  VC arrays; Plane C has three. Worse, the port enumeration the count
  would hang off is itself an open item (VC-R5). Keep VC data out of the
  topology view until VC-R5 is closed.
- CORRECTION — "no write path for microarchitecture": half wrong. The
  backend already models the real substrate as `SrotaIntent`
  (concentrated mesh + MECS row/col + islands + path_shapes
  row/column/valiant + vc_policy none/shape/rank/oneshape + sidebuf +
  telemetry periods), with presets and BookSim execution tests — but the
  prototype exposes **none** of it (zero `srota` references in
  `DraftEditor`/live views; family list lacks it, `path_shapes`
  uneditable). The gap is UI exposure, not backend modelling — except
  the injection-time adaptive overlay with Plane-T telemetry, which
  BookSim does not model (static traces only).
- CONFIRMED — Problems drawer: the specs define its future authority
  (register/counter maps TOPO-003 §13, `VC_CNT_SPURIOUS_FILL`,
  `a_shape_mix_observable` as a configuration-on-record backstop) while
  providing no data source today. The drawer stays empty; the concept to
  steal now is "record the configuration the claim depends on," which is
  exactly what the compare endpoint's `metadata_warnings` already do.

### Filed deltas

- **D-01 (near)**: expose the `srota` family in the structured draft
  editor with canonical `SrotaIntent` fields. Gateway parsing, presets,
  and execution tests already exist. Acceptance: validate/save/compile
  a srota draft through the UI plus a hardening case.
- **D-02 (near)**: track spec open items (RT-R7, VC-R5, T-R1, T-R5, …)
  as a static "specification obligations" section in the obligations
  endpoint, sourced from a checked-in list. Makes proof-shaped UI
  structurally unrenderable while items are open. Acceptance: visible
  on verify/obligations with blocking states.
- **D-03 (near)**: adopt the specs' gains-table format — Gain |
  Mechanism | Baseline | Status — for every displayed number; statuses
  analytic / simulation-pending / measured map onto the existing
  comparable / documented vocabulary. No backend change.
- **D-04 (near, needs spec-owner confirm)**: when a srota draft enables
  row+column path shapes (the `ROUTE_PATH_EN=0b111` equivalent), surface
  RT-R7 as a blocking draft warning. Display-only; the backend still
  evaluates. Confirm the `path_shapes`→`ROUTE_PATH_EN` mapping first.
- **D-05 (far, unchanged)**: per-directed-link counters sealed into run
  bundles. Now grounded: TOPO-003 §13.5 and VC-002 counters are the
  spec'd signals to plumb.
- **D-06 (recorded out of scope)**: injection-time adaptive overlay with
  Plane-T telemetry is not modelled by the BookSim path. No UI may imply
  congestion-aware routing until a backend models it.
