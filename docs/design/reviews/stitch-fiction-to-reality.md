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
