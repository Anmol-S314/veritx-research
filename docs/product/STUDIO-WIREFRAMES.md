# STUDIO-WIREFRAMES — Gate 8 (wireframes + interaction architecture)

Authority: `PRODUCT-FLOWS.md` (Gate 5), `GUIDED-EXPERT.md` (Gate 6),
`DESIGN-REVIEW.md` (Gate 7), `CAPABILITY-MATRIX.md` (Gate 4),
`CROSS-DOMAIN-LAWS.md` (Gate 3), the eleven `INTENT-*.md` documents,
`intent-ontology.yaml`, `capability-registry.yaml`, `exposure-registry.yaml`.
Current `apps/studio` audited as **implementation constraint evidence only**.
Status: **PLANNED — COHERENT.** Verdict §200.

---

## 1. D8 visual primitives — exact recovered definitions

Recovered from `intent-ontology.yaml` (answer-key header) and
`INTENT-ONTOLOGY.md:234`:

> `Vis` — `1` declaration control · `2` derived value · `3` refusal · `4` absence ·
> `5` identity · `6` change class

**Six categories. Mechanically frozen** — `check_intent_ontology.py` validates
`visual ∈ {1..6}` per ontology node (`VISUAL = {1,2,3,4,5,6}`). **No seventh
primitive exists and none may be added by Gate 8.**

| Primitive | Exact meaning | Allowed uses | Forbidden uses |
|---|---|---|---|
| **1 — declaration control** | an editable accepted intent field | any `G1`/`G2`/`E1`/`E2` field with an accepted contract; its label, input, unit, validation | any `DERIVED_INSPECT`, `NOT_RENDERED`, `LEGACY_ONLY`, `METADATA`-only or `EVALUATION_ONLY` field; any `FUTURE_CONTRACT` field |
| **2 — derived value** | a compiler-derived or backend-computed value | Mapping · Topology · Routes · VC · CDG · `locked_consequences` · world size · pre-compile derived summaries | as an input; as a certificate; as a qualification |
| **3 — refusal** | a typed staged limitation or refusal | capability consequences; `NOT_QUALIFIED`; `UNSUPPORTED`; `BLOCKING_ERROR` findings | implying design invalidity for a downstream stage; a generic red banner as authority |
| **4 — absence** | a concept with no accepted contract | `NOT_RENDERED`, `FUTURE_CONTRACT`, `LEGACY_ONLY` disclosures **in Capability only** | a disabled or "coming soon" control in authoring |
| **5 — identity** | a stable identity or provenance reference | `design_hash`, artifact hashes, `MetricId`, `AgentInstanceId`, `profile_id`, semantics versions — **in technical detail** | as a primary label; raw SHA as primary UX |
| **6 — change class** | the invalidation consequence of an edit | staleness, reuse/recompute notices, "requires recompile" | as a substitute for validation; as a pre-compile certificate claim |

**Compositional variants are permitted only as combinations of these six** (e.g.
primitive 2 rendered inside primitive 5's technical detail). **No new axis.**

## 2. Visual philosophy

**Target qualities:** precise · dense without cramped · quiet · technical ·
legible · traceable · fast to scan.

**Explicitly avoided:** generic SaaS dashboard aesthetics · purple AI gradients ·
glossy glass panels · oversized marketing cards · pill-badge proliferation ·
gratuitous rounded containers · large whitespace · decorative illustrations ·
"AI assistant" visual language · **Inter-as-default merely because it is common**.

**Reference class:** a serious scientific / EDA / systems-engineering tool. The
nearest mental models are a logic analyzer, a synthesis report, and a
place-and-route viewer — not an analytics dashboard.

**Audited existing direction** (`apps/studio/src/styles.css:1`):

> *"Srota Studio — semiconductor engineering-tool theme. Dense, flat, no gloss."*

**The existing direction already matches the target.** Preserve the philosophy;
change the default theme and the shell.

## 3. Light mode first

```text
current   :root, [data-theme='dark']  ← DARK is the default (styles.css:3)
          [data-theme='light']        ← exists but secondary
target    :root, [data-theme='light'] ← LIGHT is the default
          [data-theme='dark']         ← retained, secondary
```

**Gate 8 closes on light-first.** Dark-mode parity is **not** required for closure.
The existing light token block is the starting point:

```text
--bg #f2f4f6 · --bg-raise #e9edf1 · --bg-card #ffffff · --border #d3d9e0
--text #1d242c · --muted #5d6874 · --accent #0f6c9e
--ok #1d7a4c · --bad #b3372c · --warn #9a6b12
```

**Required change:** raise border contrast slightly (dense tables need structural
edges), and add a `--mono` and tabular-figure rule for numeric columns.

## 4. Persistent global context

The shell always shows **Project** and **Revision** context. No screen may
silently switch revision context.

```text
ALWAYS VISIBLE:  which Project · Draft or immutable Revision ·
                 which revision/evaluation/study an object belongs to ·
                 whether the current Design has uncompiled changes
```

## 5. Global shell

```text
┌────────────────────────────────────────────────────────────────────────────────┐
│ topbar                                                                         │
│ ┌──────────┐ ┌───────────────────────────┐ ┌──────────────────────────────────┐ │
│ │ SROTA    │ │ Project: dense-4b-32tiles │ │ ● Draft dirty · 2 findings       │ │
│ │ Studio   │ │ [switch ▾]                │ │ Jobs: 1 running        [theme]   │ │
│ └──────────┘ └───────────────────────────┘ └──────────────────────────────────┘ │
├──────────┬─────────────────────────────────────────────────────────────────────┤
│ sidebar  │  context bar                                                        │
│ (primary │  ┌─────────────────────────────────────────────────────────────────┐ │
│  nav)    │  │ ◉ Draft  ·  based on R7 · 0x3f9a…  ▸ Switch to R7 (compiled)   │ │
│          │  └─────────────────────────────────────────────────────────────────┘ │
│ Design   │                                                                     │
│ Evaluate │  ── primary content region ─────────────────────────────────────────  │
│ Serve    │                                                                     │
│ Optimize │                                                                     │
│ History  │                                                                     │
│ Capability│                                                                    │
│          │                                                                     │
│ ──────── │                                                                     │
│ ▸ R7     │                                                                     │
│ ▸ E2     │                                                                     │
│ ▸ S1     │                                                                     │
└──────────┴─────────────────────────────────────────────────────────────────────┘
```

**Shell regions:** topbar (identity, project switch, global freshness, jobs, theme)
· sidebar (primary nav + recent objects) · context bar (Draft vs Revision) ·
primary content region.

**Primary navigation (confirmed against Gate 5 §95/§136):**

```text
Design · Evaluate · Serve · Optimize · History · Capability
```

**No top-level page for Mapping, Topology, Attachments, Routes, VCs, Certificate
or Evidence.** Those live inside Compile Result (§50) and Provenance (§115).

## 6. Primary navigation states

```text
DEFAULT        label, muted glyph
ACTIVE         filled left rule + weight increase + aria-current="page"
UNAVAILABLE    muted + non-interactive + reason on focus  (e.g. Evaluate with no compiled revision)
STALE          a "stale" marker glyph + count, NOT a colour change alone
RUNNING JOB    a spinner glyph + count in the topbar jobs area (nav item gets a dot)
ATTENTION      a "!" glyph + count (a failure needing user action)
```

**Every state carries a non-colour channel** (glyph, weight, rule, count).
**No global `SUPPORTED` indicator exists anywhere in the shell.**

## 7. Draft vs revision affordance

```text
DRAFT      ◉ Draft        dirty marker · parent revision · no design_hash yet shown
REVISION   ▣ R7 compiled  design_hash in technical detail · parent · compile provenance
```

The context bar **always** answers: *what am I looking at?*

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ ◉ Draft  ·  based on R7  ·  ⚠ uncompiled changes        ▸ Open R7 (compiled) │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Raw hash is never the primary label** — it appears in technical detail (primitive 5).

## 8. Design page architecture

**One canonical editor with progressive disclosure** (Gate 6 §1). Not hard modes.

Sections, from the exposure registry:

```text
System · Memory Addressing* · Workload · Parallelism · Communication ·
Fabric · Router Behavior · Physical Context · Requirements

* Memory Addressing is read-only until PF-D1 lands (Gate 7 §22)
```

Advanced accepted intent nests **inside** its section, not as peer destinations:

```text
System           advanced: clock/power domains, address/data width, protocol
Workload         advanced: collectives, dependencies, source ref
Fabric           advanced: arbitration  ← Router Behavior rendered here
Physical Context advanced: power domains, process node (metadata)
```

## 9. Design page structural question — **chosen: left section navigator + central editor**

```text
┌──────────────┬───────────────────────────────────────────────────────────────┐
│ SECTIONS     │  SYSTEM                                                       │
│              │  Physical agent inventory                                     │
│ System     !2│  ┌──────────────────────────────────────────────────────────┐ │
│ Workload   ✓ │  │ kind          count   data   addr   proto   clock   pwr  │ │
│ Parallelism  │  │ COMPUTE_TILE     64    256     64    AXI      d0      0  │ │
│ Communication│  │ HBM_CONTROLLER    8      —     48    AXI      d0      0  │ │
│ Fabric     ⚠ │  │ [+ group]                                                │ │
│ Physical     │  └──────────────────────────────────────────────────────────┘ │
│ Requirements │                                                               │
│              │  ▸ Advanced — 3 settings active                               │
│              │                                                               │
│              │  ── findings ────────────────────────────────────────────────  │
│              │  ! BLOCKING  128 endpoints required, 64 seats available       │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

**Why this and not a single continuous document:** **69 exposure-registry rows**
cannot be scanned as one scroll without losing position; §10's per-section
readiness indicators need a persistent home; §39's cross-domain findings must
**navigate to a section**; and this matches the desktop engineering-console
workflow. **Within** a section the editor is a continuous document — **not a
wizard.**

## 10. Design section navigation

Each item shows: **section name · readiness glyph · blocking count · downstream
limitation count.**

```text
System         !2     2 blocking findings
Fabric         ⚠1     1 downstream limitation
Workload       ✓      no findings
```

**No green "supported".** **No certificate status** — nothing is certified before
compile.

## 11. Design header

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ DESIGN — Draft (based on R7)                                                 │
│ ⚠ 2 blocking · 1 downstream limitation     [ Review Design → ]  (disabled)   │
└──────────────────────────────────────────────────────────────────────────────┘
```

Answers: *what draft · is it dirty · is it compile-ready · what is it based on ·
what is the next action.* **No backend or evaluation state.**

## 12. Progressive disclosure interaction

```text
PRIMARY FIELDS      always rendered
ADVANCED FIELDS     behind a per-section "Advanced" disclosure
```

| Action | Science | Dirty | Review |
|---|---|---|---|
| Expand Advanced | unchanged | **not dirty** | **unchanged** |
| Collapse Advanced | unchanged | **not dirty** | **unchanged** |

**Collapsing must not make an active value undiscoverable** — a collapsed section
with active non-default advanced values shows a summary indicator (§13).

## 13. Hidden-active-value indicator

```text
▸ Advanced — 3 settings active      ← collapsed, 3 non-default advanced values
▾ Advanced — 3 settings active      ← expanded
▸ Advanced — defaults               ← collapsed, nothing non-default
```

**Purpose:** prevent hidden scientific configuration. **Clicking reveals the
fields.** Review is **not** the only discoverability mechanism during authoring
(Gate 7 §6 constrains Review, not authoring).

## 14. Field anatomy

```text
┌─────────────────────────────────────────────────────────────┐
│ Mesh side length                              [ 8        ]  │  label + input
│ routers per dimension · square grid                          │  concise note
│ ✓ valid                                    ⓘ canonical: radix│  state + owner
└─────────────────────────────────────────────────────────────┘
```

Order: **label · value/input · unit · one-line note · validation state ·
ownership marker**. Capability consequence appears **only when material** (§38).
**No large help text per field** — deeper detail is progressively exposed (§15).

## 15. Scientific ownership detail — **one pattern: the inline ⓘ disclosure**

```text
ⓘ → expands inline (not a tooltip, not a modal):
    canonical field   noc_config.radix
    domain owner      FABRIC
    source of value   user selected | recommendation | semantic default
    identity effect   design_hash · A
    capability        FAB-001
```

**One consistent pattern** for canonical name, domain owner, identity effect,
source-of-value and capability reference. **Chosen inline disclosure** over
tooltip/popover because the content is multi-line and must be selectable and
screen-reader reachable.

## 16. Canonical terminology

```text
"Mesh side length"        NOT "Radix"
"Arbitration policy"      NOT "VC allocator" + "switch allocator"
"Participant" / "compute tile" / "router" / "endpoint"  NOT "node"
```

**No removed-v4 terminology appears in any label:** no `RCU`, no
`bandwidth_floor_gbps`, no `routing_function`, no VC count as a field.

## 17. Safe-path recommendations

```text
Mesh side length  [ 8 ]   ◆ recommended
```

**◆ recommended means:** a starting value the product suggests. It does **not**
mean required, compiler-derived, or certified. **Changing away is permitted**
and produces no warning unless a formal dependency requires one.

## 18. Preset entry

**CORRECTED by implementation audit.** `mesh4`, `mesh4_hbm` and
`mesh4_wide128` were drawn as `✓ evaluate-safe`. They are not: they ship a
**multi-class** fabric (dependency classes A/B, two VCs), and every static
envelope requires `COND-SINGLE-COMM-CLASS`, with `COMM-006` recording
multi-class execution as unavailable. Only `dense-1b-16tiles` provably
reaches the advertised envelope (GUIDED-EXPERT.md §86/§87).

```text
┌─ Start from ──────────────────────────────────────────────────┐
│ ○ Empty draft                                                  │
│ ● dense-1b-16tiles  dense TP4 allreduce          ✓ evaluate-safe│
│ ▸ Other shipped presets (5)      ⚠ not Guided-eligible         │
│     mesh4 · mesh4_hbm · mesh4_wide128                          │
│       multi-class fabric — no static envelope admits it        │
│     dense-4b-32tiles-conc4                                     │
│       concentration 4 is not covered by the mesh-DOR envelope  │
│     moe-8x7b-64tiles                                           │
│       static MoE lowering unavailable; serving path only       │
└────────────────────────────────────────────────────────────────┘
```

**A preset is never labelled `✓ evaluate-safe` from its name or from the
fact that it is bundled.** The label is the certification state
`GUIDED_SAFE`, which is derived by evaluating every required condition of
the advertised envelope against the canonical compilation and fails closed
(`scripts/check_preset_certification.py`).

**Preset selection visibly results in materialized fields** (§19). After
applying, the product **shows what changed**. The user is **never trapped inside
a preset abstraction** — the draft holds ordinary canonical values.

## 19. Preset application interaction

**Applying a preset over an edited draft is scientifically destructive.**

```text
TRIGGER       apply preset over a dirty draft
PRECONDITION  preset is Guided-eligible OR user opened the expert group
UI RESPONSE   change-preview dialog (below) — NOT a silent apply
BACKEND       nothing until explicit Apply
SUCCESS       fields replaced per preset law; affected fields flash-marked
FAILURE       preset refused by certification → not offered (never applied)
IDENTITY      design_hash changes; a new draft hash; no revision created
```

```text
┌─ Apply mesh4? ───────────────────────────────────────────────────────┐
│ 12 fields will change · 3 will be preserved                          │
│   topology_family   MESH        (was MESH)      unchanged            │
│   radix             8           (was 16)        CHANGED              │
│   concentration     1           (was 4)         CHANGED              │
│   …                                                                  │
│   tp                4           (was 4)         preserved (not set)  │
│                                    [ Cancel ]  [ Apply preset ]      │
└──────────────────────────────────────────────────────────────────────┘
```

**No silent overwrite.**

## 20. Invalid preset

```text
✓ evaluate-safe            certification state GUIDED_SAFE: every required
                           condition of the advertised envelope holds
                           (derived, never declared)
▸ Expert / research presets
    mesh4                    ⚠ not Guided-eligible
      multi-class fabric — no static envelope admits multi-class execution
    mesh4_hbm                ⚠ not Guided-eligible
      same as mesh4; the HBM address map is materialized and reviewable
    mesh4_wide128            ⚠ not Guided-eligible
      same as mesh4, with 128-bit links
    dense-4b-32tiles-conc4   ⚠ not Guided-eligible
      DP allgather with dp=1; concentration 4 is not covered by the
      mesh-DOR envelope
    moe-8x7b-64tiles         ⚠ not Guided-eligible
      static MoE lowering is not available; serving path only
```

**A preset failing certification never appears as an ordinary Guided-safe
option.** Expert/research presets are visually separated with their reason.

## 21. System section

```text
SYSTEM
Physical agent inventory
┌──────────────────────────────────────────────────────────────────────────┐
│ kind              count  data_width  addr_width  protocol  clock  power  │
│ COMPUTE_TILE         64        256          64      AXI      d0      0   │
│ HBM_CONTROLLER        8          —          48      AXI      d0      0   │
│ [+ add group]                                                            │
└──────────────────────────────────────────────────────────────────────────┘

Hierarchy
┌──────────────────────────────────────────────────────────────────────────┐
│ ▸ node/accelerator grouping (active)                                     │
└──────────────────────────────────────────────────────────────────────────┘

▸ Advanced — 3 settings active
```

**Not every `AgentInstance` is a card** (§22).

## 22. Agent inventory interaction — **chosen: grouped table/editor**

| Approach | Verdict |
|---|---|
| **grouped table/editor** | **CHOSEN** — scales from 1 to 64+ agents; numeric columns align; sortable/filterable; dense |
| hierarchical outline | rejected as primary — hierarchy is a *property* of a group, not the primary axis |
| one card per instance | rejected — 64 cards is unusable |

Handles small systems, 64+ compute agents, memory controllers and stable
groups/instances.

## 23. Generated instances

```text
COMPUTE_TILE   count [ 64 ]  →  64 instances materialized
▸ inspect instances (64)
    instance_id            group    index   attached endpoint
    ct-0x3f9a…:0000        compute      0    ep-…:000
    ct-0x3f9a…:0001        compute      1    ep-…:001
```

**Compact group-level authoring plus exact instance inspection when needed.**
**Stable identity remains underneath** — the user never types 64 rows, and
generated group order never determines science (X1).

## 24. Workload section

```text
WORKLOAD
Model            [ dense_transformer ▾ ]      Model name [ dense-4b        ]
Serving mode     [ mixed ▾ ]                  ◆ recommended

▸ Advanced — collectives, dependencies, source reference

note  Serving requests and schedulers belong to Serve, not here.
```

Two authoring paths: **template/model-based** (common) and **explicit graph
semantics** (advanced, where product wiring allows — Gate 6 §66). **Serving
request controls never appear here.**

## 25. Workload summary visualization

```text
Network-producing operations
┌──────────────────────────────────────────────────────────────────────┐
│ op            kind        dimension  payload      class              │
│ allreduce-0   ALLREDUCE   TP         128 KiB      default            │
│ allgather-1   ALLGATHER   DP         64 KiB       default            │
└──────────────────────────────────────────────────────────────────────┘
```

**Table-first.** A DAG rendering is permitted **only** where it communicates
semantic structure (dependency edges that the table cannot express), and it must
be **static** — no animated nodes, no decorative motion. **No node-canvas
gimmick.**

## 26. Static MoE state

```text
WORKLOAD
Model  [ moe ]  ·  ep [ 8 ]

  ✓ intent is valid and declarable
  ⚠ downstream limitation  static MoE lowering is not available
     (capability WORK-002 · DERIVABLE = NO)
     Compile remains available. Static evaluation will not reach execution.
```

**No red invalid-state treatment.** The Design remains valid; the limitation is
visible at the capability layer.

## 27. Parallelism section

```text
PARALLELISM
TP [ 4 ]   DP [ 2 ]   EP [ 1 ]   PP [ 1 ]

  derived   world size 8 participants · 8 compute tiles required
  derived   groups     TP×2 · DP×4        (labelled derived — not editable)
```

**Derived world size is clearly marked non-editable.** Group structure preview is
labelled **derived**.

## 28. Parallelism geometry

**A compact partition visual is included only if it materially improves
comprehension.** For TP/DP/EP/PP a small labelled extent matrix is permitted:

```text
        d0     d1
  t0   p0     p4
  t1   p1     p5
  t2   p2     p6
  t3   p3     p7        (derived participant assignment preview)
```

**No decorative visualization.** If the matrix does not aid comprehension for the
current shape, it is omitted.

## 29. Communication section — two states

**Single-class (ordinary):** compact.

```text
COMMUNICATION
Default class   one class, fabric-wide
Bindings        all network-producing operations  (derived from collectives)
▸ Advanced — edit class definitions and bindings
```

**Multi-class:** expands to the exact editor.

```text
COMMUNICATION
┌──────────────────────────────────────────────────────────────────────┐
│ class        qos        bound operations              status         │
│ default      BEST_EFFORT allreduce-0, allgather-1      ✓ bound        │
│ latency      LATENCY    allreduce-0                    ✓ bound        │
│ bulk         BEST_EFFORT (none)                        ⚠ unbound      │
│ [+ class]                                                            │
└──────────────────────────────────────────────────────────────────────┘
  ⚠ downstream limitation  multi-class execution is not available
     (COMM-006 · PROJECTABLE = NO). Compile and verification remain available.
```

## 30. Communication class interaction

**Scalable class/binding editor — no repeated cards.** A two-pane binding editor:

```text
┌─ classes ──────────────┬─ bindings: latency ────────────────────────────┐
│ default      BEST_EFFORT│ ☑ allreduce-0                                  │
│ latency      LATENCY   ◀│ ☐ allgather-1                                  │
│ bulk         BEST_EFFORT│ ☐ reduce-scatter-2                             │
│ [+ class]              │                                                 │
└────────────────────────┴────────────────────────────────────────────────┘
  ⚠ unbound operations: bulk has no bindings
```

Makes **class definition · bound operations · unbound errors** easy to detect.

## 31. Requirements section

```text
REQUIREMENTS
┌────────────────────────────────────────────────────────────────────────────┐
│ target              metric                   cmp   threshold  binding      │
│ WholeNetworkEval…   completion_cycles        ≤        1200    ☑ binding    │
│ WholeNetworkEval…   completion_ns            ≤      900000    ☐ advisory   │
│ [+ requirement]                                                            │
└────────────────────────────────────────────────────────────────────────────┘
note  Requirements are evaluated after measurement. They do not block compile.
```

**Accepted v4 requirement science only.** The removed `bandwidth_floor_gbps`
control **does not exist**. `qos_class` and `traffic_class` are accepted fields
rendered in the advanced area, **not** as a "traffic-class target".

## 32. Requirement creation

```text
[+ requirement]
┌─ Add requirement ──────────────────────────────────────┐
│ target   [ WholeNetworkEvaluationTarget ▾ ]  (only valid target)
│ metric   [ completion_cycles ▾ ]             (registry-backed only)
│          [ completion_ns ]
│ op       [ ≤ ▾ ]  [ ≥ ▾ ]
│ threshold[ 1200 ]
│ [ ] binding
│                                    [ Cancel ]  [ Add ]
└────────────────────────────────────────────────────────┘
```

**Only registry-valid metric/target combinations appear.** Unknown combinations
are never offered, **and the backend still validates**.

## 33. Fabric section

```text
FABRIC
Topology family  [ MESH ▾ ]
Mesh side length [ 8 ]       ◆ recommended    routers 64 · seats 64
Concentration    [ 1 ]       ◆ recommended    endpoints per router
Link width       [ 256 ] bits ◆ recommended

▸ Advanced — arbitration
    Arbitration policy  [ ISLIP ▾ ]     (one canonical policy)
```

**Not rendered:** RCU · hardware multicast · VC count · manual route · turn
restrictions · multiplane.

## 34. Fabric visualization

```text
┌─ Topology preview ──────────────────────────── PRE-COMPILE PREVIEW ─────────┐
│                                                                             │
│     ▣───▣───▣───▣         ▣ router (64)                                     │
│     │   │   │   │         ─ link (144)                                      │
│     ▣───▣───▣───▣         ▪ attached agent (64/64 seats)                    │
│     │   │   │   │                                                           │
│     ▣───▣───▣───▣         derived from intent only —                         │
│     │   │   │   │         not the compiled TopologyArtifact                  │
│     ▣───▣───▣───▣                                                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

Communicates **routers · links · concentration/seats · attached agents/occupancy**.
**Explicitly labelled `PRE-COMPILE PREVIEW`** — it never pretends to be the
compiled artifact (§35).

## 35. Preview vs compiled visual treatment

| | Draft preview | Compiled artifact |
|---|---|---|
| Frame | dashed border | solid border |
| Corner label | `PRE-COMPILE PREVIEW` | `COMPILED · <revision>` |
| Identity | none | `topology_hash` in technical detail |
| Numbers | derived from intent, marked derived | exact artifact values |
| Provenance | none | link to Provenance |

**Applied consistently to** topology, participant counts and capacity summaries.
**No user can mistake approximate draft presentation for a certified result.**

## 36. Torus interaction

```text
Topology family [ TORUS ▾ ]

  ✓ topology derivation and inspection are available
  ⚠ routed execution is unavailable in the current canonical pipeline
     (FAB-004 · DERIVABLE = NO)
     Compile remains available if other readiness checks pass.
```

**Preview updates. Compile remains available.** The consequence is
non-blocking and uses **primitive 3 (refusal/limitation)**, not an error.

## 37. Concentration > 1 interaction

```text
Concentration [ 2 ]

  ⓘ downstream  the mesh DOR-XY evaluation profile is not qualified at
     concentration > 1. Other projections may apply. This is an evaluation
     consequence, not a design problem.
```

**Never "unsupported".** Fabric authoring is **not** tied to a backend that has
not been selected.

## 38. Design validation presentation

```text
!  BLOCKING ERROR          left rule + "!" glyph + bold label   → must be fixed
⚠  DOWNSTREAM LIMITATION   left rule + "⚠" glyph + normal text  → informational
ⓘ  INFORMATION             muted glyph + muted text
⚑  LEGACY / MIGRATION      "⚑" glyph + amber rule                → needs a decision
```

**Four visually distinct classes.** **No wall of red banners.** A red banner is
never semantic authority — the **class label** is.

## 39. Cross-domain finding interaction

```text
┌─ ! BLOCKING · MAPPING JOIN INFEASIBLE ──────────────────────────────────────┐
│ 128 endpoints required, 64 seats available                                  │
│                                                                             │
│ required   System agents   64 COMPUTE_TILE + 8 HBM_CONTROLLER = 72          │
│ available  Fabric          64 router seats (side length 8, concentration 1) │
│ owner      SYSTEM (agents) · FABRIC (seats)                                 │
│                                                                             │
│ remedies (user-owned — no auto-fix)                                         │
│   ▸ increase mesh side length            → Fabric                          │
│   ▸ increase concentration               → Fabric                          │
│   ▸ reduce physical agent inventory      → System                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Clicking a remedy navigates to the correct Design section.** **No auto-fix.**

## 40. Compile readiness

Design header and Review footer show **three distinct states**, never one boolean:

```text
✓ READY TO REVIEW
! BLOCKED — 2 blocking findings
⚠ VALID BUT DOWNSTREAM LIMITED — 1 limitation
```

## 41. Review transition

```text
Design  →  [ Review Design → ]  →  Review  →  [ Compile Design ]
```

**Compile is not triggered from a random Design position.** The flow guarantees a
review snapshot while adding **one** step, not a wizard.

## 42. Review wireframe

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ REVIEW — Draft (based on R7)                     snapshot 0x3f9a…   CURRENT  │
├──────────────────────────────────────────────────────────────────────────────┤
│ ✓ READY TO REVIEW                                                            │
├──────────────────────────────────────────────────────────────────────────────┤
│ SYSTEM                                                                       │
│   COMPUTE_TILE ×64 · HBM_CONTROLLER ×8 · data 256 · addr 64 · AXI            │
│   clock domain d0 · power domain 0                                           │
│                                                                              │
│ MEMORY ADDRESSING                                             read-only      │
│   0x0000_0000 – 0x3FFF_FFFF  →  HBM controller 0                             │
│                                                                              │
│ WORKLOAD                                                                     │
│   dense_transformer · dense-4b · mixed                                       │
│   collectives  allreduce-0 (TP) · allgather-1 (DP)                           │
│                                                                              │
│ PARALLELISM                                                                  │
│   TP 4 · DP 2 · EP 1 · PP 1        derived: world size 8                     │
│                                                                              │
│ COMMUNICATION                                                                │
│   default class · all network-producing operations bound                     │
│                                                                              │
│ FABRIC                                                                       │
│   MESH · side length 8 · concentration 1 · link width 256 bits               │
│   ROUTER BEHAVIOR  arbitration ISLIP                                         │
│                                                                              │
│ PHYSICAL CONTEXT                                                             │
│   design clock 1000 MHz · data width 256 · power domains 1                   │
│                                                                              │
│ REQUIREMENTS                                                                 │
│   R0  WholeNetworkEvaluationTarget · completion_cycles ≤ 1200 · binding      │
│   R1  WholeNetworkEvaluationTarget · completion_ns     ≤ 900000 · advisory   │
├──────────────────────────────────────────────────────────────────────────────┤
│ PRE-COMPILE DERIVED SUMMARY                                                  │
│   routers 64 · endpoint capacity 64 · required endpoints 72 · seats unused 0 │
├──────────────────────────────────────────────────────────────────────────────┤
│ CAPABILITY CONSEQUENCES                                                      │
│   ⓘ compatible with the design-side prerequisites of                         │
│     CAP-ENV-BOOKSIM-MESH-DOR-XY-V1                                           │
│     qualification is not claimed — route/VC predicates are derived later     │
├──────────────────────────────────────────────────────────────────────────────┤
│ CHANGES FROM R7                                                              │
│   concentration  1 → 2                                    changed            │
│   link width     128 → 256                                changed            │
├──────────────────────────────────────────────────────────────────────────────┤
│  [ ← Back to edit ]                                    [ Compile Design ]     │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Read-only · complete · canonical · scannable.**

## 43. Review section hierarchy

```text
1  declared scientific values      (primitive 1 — what you are asking to compile)
2  PRE-COMPILE DERIVED SUMMARY     (primitive 2 — exact precompile facts)
3  CAPABILITY CONSEQUENCES         (primitive 3 — staged limitations)
4  CHANGES FROM <parent>           (primitive 6 — canonical scientific diff)
```

**Never intermingled as if they have the same authority.**

## 44. Review change summary

```text
CHANGES FROM R7
  + tp              1 → 4                      added
  − ep              8 → 1                      removed
  ~ concentration   1 → 2                      changed
```

**Added / removed / changed.** **No raw JSON.** Derived from **canonicalized
intent** — an alias spelling change produces **no diff** (Gate 7 §34).

## 45. Review hidden-value guarantee

```text
ADVANCED VALUES INCLUDED
  the following active values are not primary fields but are part of this design
  · Agent.addr_width 64 · Agent.protocol AXI · PhysicalContext.num_power_domains 1
```

**Active values hidden under progressive disclosure are obvious in Review.**
**No omission.**

## 46. Review readiness panel

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ ! BLOCKING  2                                                                │
│   MAPPING JOIN INFEASIBLE — 128 endpoints required, 64 seats     → System    │
│   ADDRESS OVERLAP — ranges 0 and 2 overlap at 0x4000_0000        → Memory    │
│ ⚠ LIMITATION 1                                                               │
│   routed execution unavailable for TORUS                         → Fabric    │
│ ⓘ snapshot  draft 0x3f9a… · review schema v1 · capability cap-v1             │
├──────────────────────────────────────────────────────────────────────────────┤
│  [ ← Back to edit ]                            [ Compile Design ]  (disabled)│
└──────────────────────────────────────────────────────────────────────────────┘
```

**Primary action is `Compile Design`.** **No `Certify` or `Approve`.**

## 47. Stale Review interaction

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ REVIEW — Draft                                     snapshot 0x3f9a…  ⚠ STALE  │
├──────────────────────────────────────────────────────────────────────────────┤
│ ⚠ This review is stale. The draft changed after this review was generated.   │
│   Reviewed snapshot 0x3f9a… · current draft 0x71c4…                          │
│                                          [ Refresh review ]                  │
├──────────────────────────────────────────────────────────────────────────────┤
│  [ ← Back to edit ]                          [ Compile Design ]  (disabled)  │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Compile is disabled in the UI and refused by the backend** (`STALE_REVIEW`).
**Review is never silently refreshed while the user is reading**, and no unseen
content is ever compiled.

## 48. Compile-in-progress

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ COMPILING — Draft 0x3f9a…                                                    │
│   ✓ accepted snapshot                                                        │
│   ● deriving fabric …                                                        │
│                                                                              │
│   progress is shown only where the backend reports real stages.              │
│   No percentage is invented.                                                 │
└──────────────────────────────────────────────────────────────────────────────┘
```

The immutable revision **does not exist until compile succeeds**. **No fake
percentages.**

## 49. Compile refusal

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ ✗ COMPILE REFUSED — UNSUPPORTED                                              │
│   route derivation is unavailable for topology family TORUS                  │
│   owner      FABRIC                                                          │
│   stage      canonical compile                                               │
│                                                                              │
│ Your reviewed values are preserved.                                          │
│   [ ← Back to Fabric ]   [ ← Back to Review ]                                │
└──────────────────────────────────────────────────────────────────────────────┘
```

**The Review snapshot is preserved** with the typed refusal attached. **Review
context is not erased.**

## 50. Compile Result architecture

Gate 5 §97 fixed **seven inspector groups** under one Compile Result (six content
groups plus Provenance):

```text
Compile Result (a compiled revision)
├── Summary        identities · certificate · capability stages · freshness
├── Mapping        participant → compute agent
├── Fabric         routers · channels · seats · attachments · unused seats
├── Routing        canonical routes + observation scope
├── Resources      VC assignment · CDG · arbitration · router behavior
├── Address decode ranges → memory agent → endpoint
└── Provenance     compiler semantics · artifact hashes · pins
```

**Not one page per artifact.**

## 51. Compiled Revision header

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ ▣ R8  compiled from Draft 0x3f9a…        parent R7        2026-09-26 19:20   │
│ certificate  PASS (4/4 claims)   ·   capability  ⚠ 1 limitation              │
│ ⓘ design_hash 0x8d2c… · resolved_fabric 0x41af… · certificate 0x77b1…        │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Hashes are available on demand**, never primary.

## 52. Compile Summary

```text
SUMMARY
declared    MESH · side length 8 · concentration 1 · link width 256 ·
            TP4/DP2/EP1/PP1 · 64 compute + 8 HBM · 2 requirements
derived     routers 64 · channels 144 · endpoints 64 · VC 2 · routing DOR-XY
verified    ATTACHMENT_COMPLETE PASS · ROUTE_COMPLETE PASS ·
            ROUTE_LEGAL PASS · DEADLOCK_FREE PASS
evaluation  ready under CAP-ENV-BOOKSIM-MESH-DOR-XY-V1  (not yet run)
```

**Does not duplicate full Design Review.**

## 53. Mapping inspector

```text
MAPPING                                    [ search participant or agent… ]
┌──────────────────────────────────────────────────────────────────────────────┐
│ rank  participant      agent            group    instance      endpoint      │
│  0    p0 (tp0,dp0)     COMPUTE_TILE     compute  ct-…:0000     ep-…:000      │
│  1    p1 (tp1,dp0)     COMPUTE_TILE     compute  ct-…:0001     ep-…:001      │
│  …                                                                           │
│  7    p7 (tp3,dp1)     COMPUTE_TILE     compute  ct-…:0007     ep-…:007      │
└──────────────────────────────────────────────────────────────────────────────┘
  idle compute tiles: 56 of 64        ⓘ derived · no editing
```

**Search/filter · coordinate context · agent hierarchy · idle compute
visibility.** **No editing.**

## 54. Mapping scale

**Primary representation: a table/list.** A visual summary is secondary.

```text
4 participants      table of 4 rows
64 participants     table + virtualized rows + filter
hundreds            table + virtualization + aggregate summary
```

**Tiny node diagrams are never the sole representation.**

## 55. Fabric inspector

```text
FABRIC                                    [ zoom − + ] [ fit ] [ ▣ routers ▣ links ]
┌──────────────────────────────────────────────┬───────────────────────────────┐
│  ▣───▣───▣───▣───▣───▣───▣───▣               │ ROUTER 23                     │
│  │   │   │   │   │   │   │   │               │   seats        1              │
│  ▣───▣───▣───▣───▣───▣───▣───▣               │   attached     ct-…:0023      │
│  │   │   │   │   │   │   │   │               │   channels     4              │
│  ▣───▣───▣───▣───▣───▣───▣───▣               │   port width   256 bits        │
│  …                                           │                               │
│                                              │ ⓘ topology_hash 0x5b0e…       │
└──────────────────────────────────────────────┴───────────────────────────────┘
  routers 64 · channels 144 · seats 64 · attached 64 · unused 0   COMPILED · R8
```

**One of Studio's strongest technical views.** Uses the existing hand-rolled SVG
direction. **Not an ornamental network diagram.**

## 56. Topology interaction

```text
zoom / pan          wheel + drag; fit button
router selection    click → inspector panel shows canonical properties
agent selection     click → inspector shows agent + endpoint + rank
link selection      click → channel + physical link + VC mapping
cross-highlight     selecting a router highlights its channels and attached agent
```

**Selecting an object reveals exact canonical properties. No editing.**

## 57. Large topology strategy — semantic zoom

```text
≤ 64 routers     full detail: every router, every link, labels on selection only
65–256 routers   routers + links; labels on hover/selection; no per-router text
> 256 routers    aggregate view: router-count heat/occupancy summary +
                 drill-down to a region; per-router DOM is not created
```

**Labels are never drawn on every element simultaneously.** **No unreadable
spaghetti.**

## 58. Routing inspector

```text
ROUTING
class    [ default ▾ ]     source [ p0 ▾ ]     destination [ p7 ▾ ]

CANONICAL DERIVED ROUTE
  p0 → r0 → r1 → r2 → r7 → p7
  channel sequence   r0.E → r1.N → r2.N → r7.S → LOCAL_EJECTION

ⓘ this is a DERIVED EXPECTED state. It is not an observation.
```

**Clearly labelled `CANONICAL DERIVED ROUTE`.** `LOCAL_EJECTION` is shown
explicitly.

## 59. Runtime observation — visually separate

```text
ROUTE OBSERVATION                              COMPILED · R8
  ✓ runtime routing-function/table first-hop realization is exactly equivalent
    to the canonical route over the complete source × destination domain
  ⓘ this proves deterministic first-hop routing equivalence, not observed
    packet paths. Observation scope: FIRST_HOP.
```

**Expected and observed are never merged into one green line.** The wording is the
exact Gate-4 claim.

## 60. VC inspector

```text
RESOURCES — virtual channels
routing class   VC binding   transitions
default         0, 1         identity
latency         1            identity

derived VC count 2 · escape designation  (none — supported-but-unused)
                                                       ⓘ derived · no controls
```

**No controls.**

## 61. Deadlock inspector

```text
RESOURCES — channel dependency graph
DEADLOCK_FREE   PASS

(when FAIL)
DEADLOCK_FREE   FAIL
  cycle witness   ch(r2.E,vc1) → ch(r3.N,vc1) → ch(r7.S,vc1) → ch(r2.E,vc1)
  involved        classes  default, latency
                  VCs      1
                  channels r2.E → r3.N → r7.S → r2.E
  remedy          these are derived. Change editable upstream intent:
                  topology family · concentration · arbitration ·
                  communication classes.            → Fabric · Communication
```

`PASS` / `FAIL` / `UNSUPPORTED` per the actual verdict vocabulary. **No manual VC
patching action exists.**

## 62. Certificate inspector

```text
VERIFICATION
┌──────────────────────────────────────────────────────────────────────────────┐
│ claim                  status   scope                                        │
│ ATTACHMENT_COMPLETE    PASS     every declared agent is attached             │
│ ROUTE_COMPLETE         PASS     every required (class, src, dst) has a route │
│ ROUTE_LEGAL            PASS     every route's channel sequence is legal      │
│ DEADLOCK_FREE          PASS     the channel-VC CDG is acyclic                │
└──────────────────────────────────────────────────────────────────────────────┘
ⓘ certificate 0x77b1… · verified against resolved_fabric 0x41af…
```

**Never one giant `VERIFIED`.**

## 63. Certificate summary

A high-level summary may appear as a **count** — `certificate PASS (4/4 claims)` —
**and it never erases individual claim scope.**

## 64. Evaluate landing states

```text
no compiled revision   →  "Compile a design first." + [ Go to Design ]
compiled, no evaluation→  evaluation setup (§65)
evaluation exists      →  result (§71) + [ Run again ]
revision changed       →  result marked for its own revision;
                          a banner: "This evaluation belongs to R8."
```

**The page always binds an explicit compiled revision.**

## 65. Static Evaluation setup

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ EVALUATE — static                                                             │
├──────────────────────────────────────────────────────────────────────────────┤
│ compiled revision   ▣ R8    (read-only)                                       │
│ design (read-only)  MESH · side length 8 · concentration 1 · link 256 ·       │
│                     TP4/DP2/EP1/PP1 · single communication class              │
├──────────────────────────────────────────────────────────────────────────────┤
│ EVALUATION PROFILE                                                            │
│ ◉ CERTIFIED_BOOKSIM_MESH_DOR_XY_V1        ◆ recommended                       │
│   mesh DOR-XY · qualified network-cycle simulation of a dense static          │
│   workload under the pinned config audit                                      │
│ ○ CERTIFIED_BOOKSIM_ANYNET_V1                                                 │
│   canonical-route static evaluation · first-hop routing-function equivalence  │
├──────────────────────────────────────────────────────────────────────────────┤
│ network clock  [ 1000000000 ] Hz     timeout [ 600 ] s                        │
├──────────────────────────────────────────────────────────────────────────────┤
│  [ Check qualification ]                                                      │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Design values are read-only here.**

## 66. Backend / profile selection

```text
◉ CERTIFIED_BOOKSIM_MESH_DOR_XY_V1
  envelope    CAP-ENV-BOOKSIM-MESH-DOR-XY-V1
  claim scope qualified network-cycle simulation of a dense static workload
              over a square mesh with DOR-XY routing under the pinned config audit
  semantics   booksim2-fork+P1B-meshdor-dump
  status      ✓ design-side prerequisites satisfied

○ CERTIFIED_BOOKSIM_ANYNET_V1
  envelope    CAP-ENV-BOOKSIM-ANYNET-V1
  claim scope canonical-route static evaluation with first-hop routing-function
              equivalence
  status      ✓ compatible
```

**Three materially different profiles exist. One generic "BookSim" option is
never presented.**

## 67. Guided backend recommendation

```text
◆ recommended  this profile's design-side prerequisites are satisfied by the
               current revision, and it is the most directly qualified envelope.
```

**Recommended ≠ selected silently.** The recommendation is shown **with its
reason**, and the user confirms.

## 68. Qualification preflight

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ QUALIFICATION — CERTIFIED_BOOKSIM_MESH_DOR_XY_V1                              │
│                                                                              │
│ ✓ QUALIFIED                                                                   │
│                                                                              │
│ (or)                                                                          │
│ ✗ NOT_QUALIFIED                                                              │
│   COND-TOPOLOGY-MESH          pass                                           │
│   COND-SINGLE-COMM-CLASS      pass                                           │
│   COND-IDENTITY-VC-TRANSITIONS pass                                          │
│   concentration == 1          FAIL   observed 2                              │
│                                                                              │
│   ⓘ the design remains canonically valid. This is an envelope limitation,     │
│     not an invalid design.                                                   │
│   [ choose another profile ]  [ change design → Fabric ]  [ inspect ]        │
│                                                                              │
│ (or)                                                                          │
│ ⚠ BACKEND_UNAVAILABLE  the backend binary is not built for this interpreter   │
└──────────────────────────────────────────────────────────────────────────────┘
```

**`NOT_QUALIFIED` is never shown as an invalid design.**

## 69. Evaluation run action

```text
[ Run Evaluation ]    enabled only when an executable + qualified path exists
                      disabled with reason otherwise
```

**No silent backend fallback.**

## 70. Evaluation running state

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ RUNNING — static evaluation                                                   │
│   profile   CERTIFIED_BOOKSIM_MESH_DOR_XY_V1                                  │
│   stage     executing backend                                                 │
│   elapsed   00:42                                                             │
│   ⓘ stage and elapsed only. No percentage is invented.                        │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 71. Evaluation result

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ EVALUATION — R8 · CERTIFIED_BOOKSIM_MESH_DOR_XY_V1                            │
├──────────────────────────────────────────────────────────────────────────────┤
│ QUALIFICATION   ✓ QUALIFIED   envelope CAP-ENV-BOOKSIM-MESH-DOR-XY-V1         │
│ EXECUTION       ✓ EVALUATED   attempt 0x9c11… · 00:51                         │
├──────────────────────────────────────────────────────────────────────────────┤
│ METRICS                                                                       │
│   completion_cycles     1187 cycles   producer authenticated-network-window…  │
│   completion_ns         1187 ns       (from the same authenticated window)    │
│   completion_time       1187 cycles                                           │
│   row_hit_rate          UNMEASURABLE  not evidenced by this profile           │
├──────────────────────────────────────────────────────────────────────────────┤
│ REQUIREMENTS                                                                  │
│   R0  completion_cycles ≤ 1200   SATISFIED   binding                          │
│   R1  completion_ns     ≤ 900000 VIOLATED    advisory                         │
├──────────────────────────────────────────────────────────────────────────────┤
│ EVIDENCE        performance_result 0x… · authenticated proof chain            │
│ PROVENANCE      [ open provenance ]                                           │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Never reduced to a latency number.**

## 72. Metric presentation

```text
completion_cycles   1187  cycles
  ⓘ MetricId completion_cycles · producer authenticated-network-window-cycles ·
    semantics v1 · time domain network cycles
```

Each metric makes available: **MetricId/label · value · unit · producer/evidence ·
semantics version in technical detail.**

**`UNMEASURABLE` is never zero** and never blank — it is a labelled state.

## 73. Requirement Report

```text
REQUIREMENTS
┌──────────────────────────────────────────────────────────────────────────────┐
│ id  target                metric             cmp  threshold  verdict   binding│
│ R0  WholeNetworkEval…     completion_cycles  ≤       1200    SATISFIED binding│
│ R1  WholeNetworkEval…     completion_ns      ≤     900000    VIOLATED  advisory│
│ R2  WholeNetworkEval…     completion_cycles  ≤        500    UNMEASURABLE binding│
│ R3  WholeNetworkEval…     completion_ns      ≥          0    NOT_APPLICABLE    │
└──────────────────────────────────────────────────────────────────────────────┘
  binding/advisory is shown per row and does not change the individual verdict.
```

**Individual verdicts are never hidden by an overall status.**

## 74. Threshold-only edit

```text
REQUIREMENTS — R8 · evaluation 0x9c11…
│ R0  completion_cycles ≤ [ 1200 ] → [ 1400 ]     [ Recompute report ]
│
│ ⓘ measurement 0x9c11… is reused. No backend rerun is required.
│   Recomputing produces a new RequirementReport for the same evaluation.
```

**The UI makes reuse explicit and immediate.**

## 75. Evaluation provenance

```text
┌─ Provenance ─────────────────────────────────────────────────────────────────┐
│ metric observation   completion_cycles = 1187                                │
│   ↑ evidence         performance_result 0x…  (authenticated)                 │
│   ↑ execution        attempt 0x9c11… · EVALUATED · 00:51                     │
│   ↑ qualification    CAP-ENV-BOOKSIM-MESH-DOR-XY-V1 · profile               │
│                      CERTIFIED_BOOKSIM_MESH_DOR_XY_V1                        │
│   ↑ backend producer ramulator-style producer identity: name/version/commit/ │
│                      binary_sha256  →  booksim2-fork+P1B-meshdor-dump        │
│   ↑ certificate      PASS 4/4 claims · 0x77b1…                               │
│   ↑ compiled         R8 · design_hash 0x8d2c… · resolved_fabric 0x41af…      │
│   ↑ draft            snapshot 0x3f9a… (reviewed)                             │
└──────────────────────────────────────────────────────────────────────────────┘
```

**No vague "confidence" score.**

## 76. Comparison flow

```text
COMPARE
mode  ◉ Design revisions      ○ Evaluations

design mode      canonical intent changes · compiled differences · capability
evaluation mode  metric observations with comparability checking
```

**Separate modes.** Incompatible metrics are **never** ordinary deltas.

## 77. Design comparison

```text
DESIGN COMPARISON — R7 vs R8
intent changes
  ~ concentration   1 → 2
  ~ link width      128 → 256
compiled differences
  routers      64 → 64
  channels    128 → 144
capability consequences
  ⚠ R8 concentration 2 is not covered by the mesh DOR-XY envelope
(no backend numbers — select evaluations to compare measurements)
```

## 78. Evaluation comparison

```text
EVALUATION COMPARISON — E2 (R7) vs E5 (R8)
┌──────────────────────────────────────────────────────────────────────────────┐
│ metric              E2            E5            Δ          Δ%                 │
│ completion_cycles   1240          1187          −53        −4.3%   comparable │
│ completion_ns       1240          1187          −53        −4.3%   comparable │
└──────────────────────────────────────────────────────────────────────────────┘

(incompatible case)
│ completion_ns      1240 @1.0 GHz 1187 @2.0 GHz  —   INCOMPARABLE
│   reason  different network clock; ns observations are not comparable.
│           cycles remain comparable.
```

**Absolute · difference · percentage only where mathematically valid.**
**`INCOMPARABLE` with the exact reason otherwise.**

## 79. Serve landing / setup

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ SERVE                                                                         │
├──────────────────────────────────────────────────────────────────────────────┤
│ compiled revision  ▣ R8                                                       │
│ request trace      [ serving-trace-a ▾ ]                                      │
│ serving config     [ cluster-default ▾ ]                                      │
│ scheduler/batching options supported by the serving contract                  │
│ serving backend    [ CERTIFIED_SERVING_BOOKSIM2_V1 ▾ ]                        │
├──────────────────────────────────────────────────────────────────────────────┤
│  [ Run Serving Experiment ]                                                   │
└──────────────────────────────────────────────────────────────────────────────┘
```

**The static Evaluate form is not reused indiscriminately.**

## 80. Serving ownership

```text
ⓘ Serving semantics
    requests · queues · scheduling · batching · prefill/decode · instances ·
    request metrics        — owned by the serving model
  Fabric/network execution · round qualification · round evidence
                           — owned by SROTX fabric execution
```

**Distinguished without exposing implementation noise.**

## 81. Serving result

```text
SERVING EXPERIMENT — R8 · CERTIFIED_SERVING_BOOKSIM2_V1
┌──────────────────────────────────────────────────────────────────────────────┐
│ REQUEST METRICS          p50        p99                                       │
│   TTFT                   …          …                                         │
│   completion latency     …          …                                         │
│   throughput             …                                                     │
├──────────────────────────────────────────────────────────────────────────────┤
│ NETWORK EVIDENCE         round qualification · round evidence · attempt        │
│ QUALIFICATION            CAP-ENV-BOOKSIM-SERVING-V1                           │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Only metrics the code actually produces.** Request-level result, network
evidence and qualification/provenance are clearly separated.

## 82. Serving MoE

```text
SERVE
  ✓ dispatch/combine semantics are available in the serving path
    (WORK-004 · DERIVABLE = YES)

ⓘ static Product Evaluation MoE is a different capability
  (WORK-002 · DERIVABLE = NO). This does not imply static MoE support.
```

## 83. Optimize landing

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ OPTIMIZE                                                                      │
│ baseline revision  ▣ R8                                                       │
│ [ + New study ]                                                               │
├──────────────────────────────────────────────────────────────────────────────┤
│ study      baseline  status      candidates  pareto  selected                 │
│ S1         R7        completed          24       3   cand_4f2a…               │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Does not lead with trial numbers.**

## 84. Study setup architecture

```text
STUDY SETUP
1  Baseline              compiled revision
2  Design space          typed dimensions
3  Objectives            registry-backed metric + direction
4  Constraints           typed metric bounds
5  Requirements context  RequirementSet (annotation)
6  Evaluation policy     one backend/profile per study
7  Search execution      method · budget · seed
```

**These authorities are never merged.**

## 85. Guided optimization setup

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ NEW STUDY — guided                                                            │
├──────────────────────────────────────────────────────────────────────────────┤
│ goal            [ reduce network completion cycles ▾ ]                        │
│ variation scope [ fabric link width + concentration ▾ ]                       │
├──────────────────────────────────────────────────────────────────────────────┤
│ MATERIALIZED DESIGN SPACE                                                     │
│ ┌──────────────────────────────────────────────────────────────────────────┐ │
│ │ dimension        owner    values          baseline                       │ │
│ │ link_width       FABRIC   64, 128, 256    256                            │ │
│ │ concentration    FABRIC   1, 2            1                              │ │
│ └──────────────────────────────────────────────────────────────────────────┘ │
│ ⓘ 6 candidates (3 × 2). Every dimension is shown — nothing is hidden.        │
├──────────────────────────────────────────────────────────────────────────────┤
│ objectives   completion_cycles  MIN                                           │
│ constraints  (none)                                                           │
│ requirements R8 RequirementSet (annotation)                                   │
│ evaluation   CERTIFIED_BOOKSIM_MESH_DOR_XY_V1                                 │
│ search       grid · budget (none) · seed 7                                    │
├──────────────────────────────────────────────────────────────────────────────┤
│  [ Review study → ]                                                           │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 86. Expert optimization setup

```text
NEW STUDY — expert
  dimensions   [+ dimension]
    dimension  [ link_width ▾ ]   owner FABRIC   values [64,128,256]
  objectives   [+ objective]
  constraints  [+ constraint]
```

**Produces the same `StudyDefinition`. No arbitrary JSON path editor.**

## 87. DesignSpace dimension editor

```text
dimension        link_width
owner domain     FABRIC
allowed values   64 · 128 · 256          (finite set)
baseline value   256
```

**Cannot select:** routes · VC count · manual placement · any future-contract
field. The dimension picker offers **only** the closed GUIDED registry.

## 88. Candidate-owned resources

```text
dimensions
  link_width        FABRIC          64, 128, 256
  concentration     FABRIC          1, 2
  router_buffers    CANDIDATE-OWNED — not a Design field
                    ⓘ not available today: no candidate-owned dimension exists
                      (ROUTE-012). Shown here so ownership is explicit.
```

**Not made to look like an omitted Design control.**

## 89. Objectives

```text
objectives
  completion_cycles   MIN
  completion_ns       MAX        [+ objective]
ⓘ metric and direction only. No free-text objective, no composite score.
```

## 90. Optimization constraints

```text
constraints
  completion_cycles   ≤   1400        [+ constraint]
ⓘ one constraint per metric. No pre-compile field constraint mechanism exists.
```

## 91. Requirements context

```text
requirements context   R8 RequirementSet
  R0  completion_cycles ≤ 1200  binding
  R1  completion_ns     ≤ 900000 advisory

ⓘ requirement status is an ANNOTATION on each candidate. It does not remove an
  objectively Pareto-dominant candidate from the frontier.
```

## 92. Search execution policy

```text
SEARCH EXECUTION POLICY            (execution, not study science)
  method  [ grid ▾ ]
  budget  max_candidates [ ] max_evaluations [ ]
  seed    [ 7 ]
ⓘ changing method/budget/seed changes exploration, not the scientific question.
```

**Visually and semantically separate from the StudyDefinition.**

## 93. Study Review

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ REVIEW STUDY — S2                                                             │
├──────────────────────────────────────────────────────────────────────────────┤
│ baseline          ▣ R8 · design_hash 0x8d2c…                                  │
│ design space      link_width [64,128,256] · concentration [1,2]   (6 candidates)│
│ objectives        completion_cycles MIN                                       │
│ constraints       none                                                        │
│ requirements      R8 RequirementSet (annotation)                              │
│ evaluation policy CERTIFIED_BOOKSIM_MESH_DOR_XY_V1                            │
│ search policy     grid · no budget · seed 7                                   │
├──────────────────────────────────────────────────────────────────────────────┤
│  [ ← Back ]                                    [ Run Study ]                  │
└──────────────────────────────────────────────────────────────────────────────┘
```

**No hidden guided choices.**

## 94. Optimization running state

```text
RUNNING — study S2
  generated   6
  compiled    6
  evaluated   4
  failed      1
  remaining   1
ⓘ counts are real. No percentage is invented for adaptive search.
```

## 95. Candidate table

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ candidate    changes from R8        status      cycles  ns     req  pareto   │
│ cand_4f2a…   link_width 256→64      EVALUATED    1187  1187   PASS  member   │
│ cand_9b03…   link_width 256→128     EVALUATED    1104  1104   FAIL  member   │
│ cand_c117…   concentration 1→2      EVALUATED    1310  1310   PASS  —        │
│ cand_2e88…   link_width→64 conc→2   COMPILE_FAILED  —     —    —     —        │
│ cand_71d4…   link_width 256→128     NOT_QUALIFIED  —     —    —     —        │
└──────────────────────────────────────────────────────────────────────────────┘
  [ filter: status · pareto · requirements ]        ⓘ click a row to inspect
```

Columns emphasise **Candidate · Changes · Status · Objectives · Requirements ·
Pareto · Qualification.** **No trial number, no raw backend score.**

## 96. Candidate state rendering

```text
evaluation_status    EVALUATED · COMPILE_FAILED · INVALID · UNSUPPORTED ·
                     BACKEND_UNAVAILABLE · FAILED
orthogonal           objective availability  MEASURED | UNMEASURABLE
                     constraint verdicts     SATISFIED | VIOLATED | UNMEASURABLE
                     requirements            true | false | null
                     pareto                  eligible | member | ineligible
```

**Canonical statuses only.**

## 97. Failed candidate inspection

```text
┌─ cand_2e88… ─────────────────────────────────────────────────────────────────┐
│ changes from R8   link_width 256→64 · concentration 1→2                       │
│ design identity   ⓘ candidate 0x… · design_hash 0x…                           │
│ compile           COMPILE_FAILED                                              │
│   compilation_status  UNSUPPORTED                                             │
│   reason              endpoint demand 128 exceeds fabric capacity 64          │
│ certificate       not reached                                                 │
│ qualification     not reached                                                 │
│ objectives        —                                                           │
│ remediation       increase side length or concentration, or reduce agents     │
│                   → Fabric                                                    │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Failed candidates remain in study history.**

## 98. Pareto presentation

**The frontend consumes `pareto_member` and `pareto_eligible`. It never
recomputes.**

```text
pareto members  3 of 5 eligible
[ candidate table ]  +  [ Pareto plot (only when exactly 2 objectives) ]
```

**Only eligible candidates enter any Pareto visualization.**

## 99. Pareto plot

```text
objectives == 1   no scatter. Table + a single-axis strip is honest.
objectives == 2   scatter is permitted:
                  ┌──────────────────────────────┐
                  │ cycles ↓                      │
                  │   ●  cand_9b03 (req FAIL)     │
                  │      ●  cand_4f2a (req PASS)  │
                  │           ●  cand_c117        │
                  │  ──────────────────────→ ns   │
                  └──────────────────────────────┘
objectives > 2    table-first, or a parallel-coordinates view.
                  No radar chart.
```

**No decorative radar charts.**

## 100. Requirement violation on a Pareto member

```text
cand_9b03…   pareto  MEMBER      requirements  FAIL
  ⓘ a Pareto member may violate a requirement. Requirement status is an
    annotation and does not remove an objectively dominant candidate.
```

**Requirement status never visually erases frontier membership.**

## 101. Candidate comparison

```text
CANDIDATE COMPARISON — cand_4f2a… vs cand_9b03…
design values
  link_width    64          128
  concentration 1           1
objective observations
  completion_cycles  1187   1104      Δ −83   comparable
requirements
  R0             PASS       FAIL
qualification    QUALIFIED  QUALIFIED
```

**Focus on changed design values, objective observations, requirements,
qualification/evidence.**

## 102. Candidate selection

```text
ROW FOCUS        clicking a row — no scientific meaning, only inspection
STUDY SELECTION  explicit [ Select candidate ] → selected_candidate_id + rationale
PROMOTE          [ Use as new design ] → a new revision (see §103)
```

**Clicking a row is not scientific selection.**

## 103. Candidate promotion

```text
[ Use as new design ]     ← disabled, with reason
  ⓘ promotion is not wired in the current product (OPT-008 · PRODUCT_NOT_WIRED)
```

**Target behaviour (documented, not offered while unwired):**

```text
candidate → explicit "Use as new design" → successor draft from the candidate's
canonical intent → the optimization study remains immutable
```

## 104. History

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ HISTORY                                                                       │
│ ◉ Objects     ○ Timeline                                                      │
├──────────────────────────────────────────────────────────────────────────────┤
│ DRAFTS                                                                        │
│   draft 0x3f9a…   based on R8    dirty · 2 findings                           │
│ COMPILED REVISIONS                                                            │
│   ▣ R8   parent R7   certificate PASS   evaluation E5   study S2              │
│   ▣ R7   parent —    certificate PASS   evaluation E2                         │
│ EVALUATIONS                                                                   │
│   E5  R8  CERTIFIED_BOOKSIM_MESH_DOR_XY_V1  completion_cycles 1187            │
│   E2  R7  CERTIFIED_BOOKSIM_MESH_DOR_XY_V1  completion_cycles 1240            │
│ SERVING EXPERIMENTS                                                           │
│   V1  R8  CERTIFIED_SERVING_BOOKSIM2_V1                                       │
│ STUDIES                                                                       │
│   S2  baseline R8  completed  6 candidates  3 pareto                          │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Object history, not log spam.** Objects remain linked.

## 105. History timeline vs table — **chosen: table-first, with an optional timeline**

| Representation | Verdict |
|---|---|
| **object table** | **CHOSEN as primary** — precise, filterable, scales, preserves links |
| timeline | secondary mode; useful for ordering, poor for precise lookup |
| revision tree | **only when actual branching exists** — promotion creates a branch, so a tree is offered for revisions specifically |

## 106. Archive behaviour

```text
▣ R7   archived 2026-09-20
  ⓘ archived objects remain provenance-resolvable. They are not deleted.
    E2 and S2 still reference R7.
```

**Archive is visually distinct from delete.** **No dangling scientific
references.** Delete is not offered for objects referenced by an
evaluation/study.

## 107. Capability explorer

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ CAPABILITY                            registry cap-v1 · 73 rows              │
│ [ search… ]                                                                   │
│ filter:  domain ▾   wiring ▾   blocker ▾   gap/future ▾                       │
├──────────────────────────────────────────────────────────────────────────────┤
│ id         capability                DECL DERIV VERIF PROJ EXEC QUAL EVID WIRED│
│ FAB-003    torus topology            ✓    ✓     ✓     ✗    ✗    ✗    ✗   insp │
│ ROUTE-011  RCU / in-network reduction FUT  ✗     ✗     ✗    ✗    ✗    ✗   none│
│ MEM-002    Ramulator engine          ✗    ✓     ✗     ✓    ✓    ✓    ✓   eng  │
│ OPT-001    guided optimizer          ✓    ✓     ✓     ✓    ✓    ✓    ✓   wired│
└──────────────────────────────────────────────────────────────────────────────┘
```

## 108. Capability row

Human-readable stage labels, **not** a `Supported` boolean:

```text
declare · derive · verify · project · execute · qualify · evidence · wired

glyphs   ✓ yes · ✗ no · ⚠ conditional (with envelope) · —
         not applicable · FUT future contract · LEG legacy only · ENG engine only
```

## 109. Capability filtering

```text
domain          SYSTEM WORKLOAD PARALLELISM COMMUNICATION PLACEMENT FABRIC
                ROUTER_RESOURCE MEMORY EVALUATION REQUIREMENTS DESIGN_SPACE
wiring          WIRED · ENGINE_ONLY · INSPECT_ONLY · NOT_AVAILABLE
blocker         NO_CONTRACT · NO_DERIVATION · NO_BACKEND_PROJECTION ·
                NOT_QUALIFIED · NO_EVIDENCE_CONTRACT · PRODUCT_NOT_WIRED · …
gap/future      IMPLEMENTATION_GAP · FUTURE_CONTRACT · LEGACY_ONLY
```

**The capability page is expert-oriented.** Ordinary workflows are not
overwhelmed.

## 110. Capability detail

```text
┌─ FAB-003 · torus topology ───────────────────────────────────────────────────┐
│ owner       FABRIC                                                            │
│ stages      declare ✓ · derive ✓ · verify ✓ · project ✗ · execute ✗ ·        │
│             qualify ✗ · evidence ✗ · wired: inspect only                      │
│ blocker     NO_BACKEND_PROJECTION                                             │
│ claim scope topology construction available; routed execution not available   │
│ envelopes   (none)                                                            │
│ related     FAB-004 torus routed execution · ROUTE-004 torus routing          │
│ actions     ▸ Inspect a torus topology (open a compiled revision)             │
│             (no evaluation action — the route path is absent)                 │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 111. ENGINE_ONLY interaction

```text
┌─ MEM-002 · Ramulator engine ─────────────────────────────────────────────────┐
│ stages    declare ✗ · derive ✓ · verify ✗ · project ✓ · execute ✓ ·          │
│           qualify ⚠ (CAP-ENV-RAMULATOR-V1) · evidence ✓ · wired: ENGINE ONLY  │
│ claim     standalone DRAM-cycle timing simulation over a recorded             │
│           legacy-derived request stream                                       │
│           NOT NoC-inclusive memory latency                                    │
│ status    Memory simulation engine available; not connected to the current    │
│           product workflow.                                                   │
│ actions   (none — no Run action exists)                                       │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 112. INSPECT_ONLY interaction

```text
┌─ FAB-003 · torus topology ───────────────────────────────────────────────────┐
│ actions   ▸ Inspect a torus topology      → opens Compile Result → Fabric     │
│           ✗ no evaluation action          (routed execution unavailable)      │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 113. FUTURE_CONTRACT interaction

```text
┌─ ROUTE-011 · RCU / in-network reduction ─────────────────────────────────────┐
│ stages    declare FUTURE_CONTRACT · all later stages ✗ · wired: NOT_AVAILABLE │
│ reason    removed from v4; no structural router-reduction artifact            │
│ claim     not modeled. No target intent field exists.                         │
│ actions   (none)                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

**No configuration control. No "Coming soon" disabled controls anywhere.**

## 114. LEGACY_ONLY interaction

```text
┌─ MEM-006 · REMOTE / CXL / STORAGE memory ────────────────────────────────────┐
│ stages   declare LEGACY_ONLY · wired NOT_AVAILABLE                            │
│ claim    grammar tokens, refused at lowering against the v1 HBM pool          │
│ visible  migration diagnostics · technical capability detail only             │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Never in ordinary authoring.**

## 115. Provenance interaction pattern — **one universal right-hand drawer**

```text
┌──────────────────────────────────────┬───────────────────────────────────────┐
│ primary content                      │ PROVENANCE                  [ × ]     │
│                                      │ ─────────────────────────────────────  │
│                                      │ compiled   R8 · design_hash 0x8d2c…    │
│                                      │ certificate PASS 4/4 · 0x77b1…         │
│                                      │ qualification CAP-ENV-…                │
│                                      │ execution attempt 0x9c11…              │
│                                      │ evidence  performance_result 0x…       │
│                                      │ metric    completion_cycles            │
└──────────────────────────────────────┴───────────────────────────────────────┘
```

**One pattern, used consistently** across compiled artifacts, evaluations,
studies and candidates. **Chosen over a dedicated subview** because provenance is
consulted *while* looking at a value, and over a modal because it must not
interrupt.

## 116. Technical detail pattern — **inside the provenance drawer**

IDs, hashes, semantics versions, producer identities and condition IDs render in
the drawer (or the inline ⓘ from §15), **never in the primary visual hierarchy**.

## 117. Error interaction pattern

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ <class glyph + class label>                                                  │
│ stage     canonical compile | qualification | execution | report             │
│ reason    typed reason code + one sentence                                   │
│ owner     domain / artifact                                                  │
│ next      one or more concrete actions, each pointing at an owning surface    │
└──────────────────────────────────────────────────────────────────────────────┘
```

Applied to: blocking design error · compile refusal · verification failure ·
qualification failure · execution failure · unmeasurable metric.

## 118. No generic toast-only failures

**Critical scientific failures are never toast-only.** A toast may acknowledge an
action; the **persistent structured state** is required. Toasts are reserved for
non-scientific acknowledgements (draft saved, copied to clipboard).

## 119. Running jobs

```text
topbar:  Jobs: 1 running   ▸   ┌─ jobs ───────────────────────────────┐
                              │ study S2     running   4/6 evaluated │
                              │ evaluation E5 completed              │
                              └──────────────────────────────────────┘
```

**Job status survives navigation.** A running study is not lost by leaving the
page.

## 120. Cancellation interaction

```text
[ Cancel ]   cancels the EXECUTION ATTEMPT / JOB
             the scientific definition (revision · evaluation policy · study) remains
ⓘ a cancelled execution produces no measured result. Partial or incomplete
  evidence is never presented as a complete metric.
```

## 121. Retry interaction

```text
[ Retry ]    same scientific definition · NEW ExecutionAttempt
ⓘ no new Design revision is created.
```

## 122. Keyboard workflow

```text
section navigation      [ and ]  or  ⌥↑ / ⌥↓   move between Design sections
search                  ⌘K / Ctrl-K             command palette (§123)
review / compile        ⌘⏎                     advance Design → Review → Compile
table selection         ↑ / ↓                   move the row cursor
                        Enter                   open detail for the focused row
escape detail panel     Esc                     close drawer / clear selection
focus                   Tab / Shift-Tab         standard order; visible focus
```

**Browser conventions are not overridden** — no hijacking of ⌘W, ⌘R, ⌘L,
text-field arrow keys, or ⌘/Ctrl-C.

## 123. Command palette — **YES, navigation-only**

```text
DECISION: yes, with a deliberately narrow scope.

INCLUDED   jump to project · revision · evaluation · serving experiment ·
           study · candidate · capability row · Design section
EXCLUDED   Compile Design · Run Evaluation · Run Study
           — because these must flow through Review (§41), qualification
             preflight (§68) and study Review (§93). A palette command would
             bypass the review snapshot binding that Gate 7 exists to guarantee.
```

**Not built merely because developer tools have one** — it earns its place
because the object model is deep (project → revision → evaluation/study →
candidate) and the objects are already deep-linkable (§150).

## 124. Search — four separate searches

```text
project object search     command palette (§123) — revisions, evaluations, studies
candidate search/filter   local to the candidate table (§95)
mapping/agent lookup      local to the Mapping inspector (§53)
capability search         local to the Capability explorer (§107)
```

**No single overloaded global search.**

## 125. Tables

```text
sticky header              always
sorting                    click a header; numeric columns sort numerically
filtering                  per-table filter control
column visibility          only on wide scientific tables (candidate, mapping)
row selection              keyboard cursor + Enter; click sets the cursor
virtualization             > 200 rows
tabular numerals           all numeric columns
```

**Tables must remain scientifically readable** — no card-stacking transformation.

## 126. Dense information

**Compact hierarchy over giant cards.** A typical desktop engineering screen shows
meaningful data above the fold. **No mobile-dashboard spacing on desktop.**

## 127. Panel / container system

```text
canvas        the page background — no border
section       a heading + content, separated by a rule, NOT a bordered card
subsection    a labelled group inside a section
data table    a bordered block (tables need structure)
inspector     a right-hand drawer (provenance/detail) or a bordered panel (selection)
finding       a left-ruled block, class-coloured rule only
```

**Not every field sits inside a bordered card.** Current Studio overuses
`.card`; the target uses rules and headings.

## 128. Visual hierarchy (relative)

```text
1  page title            largest, semibold
2  object context        (revision label, draft/revision state) — medium, with glyph
3  section heading       medium-semibold, with readiness glyph
4  field label           small, medium weight
5  value                 same size as label, tabular figures
6  technical metadata    smallest, muted, monospace
7  status                glyph + short label, never colour-only
8  finding               left rule + class label + body
```

**Exact pixel and font sizes are deferred to implementation**; the relative order
is binding.

## 129. Typography requirements

```text
UI text     technical · neutral · compact · highly legible for numbers
            clear label/value distinction · NOT Inter-by-default
numbers     tabular figures REQUIRED in tables (cycles, ns, bytes, counts)
monospace   selective: IDs · addresses · hashes · cycles · canonical field names
            (reuse the existing --mono token)
NOT         monospace for everything
```

**Final font selection happens at implementation**, constrained by: true tabular
figures, a neutral grotesque without geometric/rounded styling, and a monospace
with unambiguous `0/O` and `1/l/I`.

## 130. Numeric alignment

```text
cycles · ns · bytes · counts · metrics   right-aligned, tabular figures
hex addresses                            monospace, left-aligned, grouped 0x0000_0000
percentages                              right-aligned, fixed decimals
```

**Specified: tabular numerals wherever available.**

## 131. Colour semantics

```text
blocking      --bad   (left rule + "!" glyph)
failure       --bad
success       --ok
limitation    --warn  (left rule + "⚠" glyph)
information   --muted / --info
selected      --accent (left rule + weight; never fill-only)
```

**Scientific state never depends on colour alone** — every colour has a glyph,
label, rule or count channel. **Saturated status colours are used sparingly** —
status appears as a glyph + short label first, colour second.

## 132. Capability-stage visual language

```text
DECL DERIV VERIF PROJ EXEC QUAL EVID WIRED
 ✓    ✓     ✓     ✗    ✗    ✗    ✗    insp
```

**A compact eight-cell glyph row.** **Not a maturity bar, not a gradient, not a
"score".** Absent stages are simply `✗`; a stage that is meaningless shows `—`.

## 133. Verification visual language

```text
CLAIM TABLE          claim name · status glyph+label · scope sentence
                     ATTACHMENT_COMPLETE  PASS  every declared agent is attached
```

**Distinct from the capability glyph row.** A certificate `PASS` is never rendered
with the capability glyph vocabulary, and **never conflated with product
availability**.

## 134. Empty states

```text
Design        new draft: section navigator with defaults + "Start from a preset"
Evaluate      "Compile a design first."          → Design
Serve         "Select a compiled revision."      → Design
Optimize      "Create an optimization study."    → study setup
History       "No compiled revisions, evaluations or studies yet."
Capability    always registry-backed — never empty; if the registry is
              unavailable, a version/refresh error (§137)
```

**No marketing filler.**

## 135. Loading states

```text
skeletons       for table/list regions with known shape
spinner         for actions and jobs
NEVER           display stale science as current while loading new revision data
```

**If old data remains visible during a load, it is explicitly marked** — e.g. a
muted `showing R7 · loading R8` banner.

## 136. Error states

```text
unknown enum from API          fail closed — render a typed "unknown value" state
                               with the raw value in technical detail
schema/contract mismatch       refuse the surface, do not degrade silently
```

**A scientifically incompatible frontend/backend never silently degrades.**

## 137. Capability registry mismatch

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ ⚠ CAPABILITY DATA OUT OF DATE                                                 │
│   this build understands cap-v1; the backend reports cap-v2                    │
│   capability claims are withheld until the data is refreshed.                 │
│                                          [ Refresh ]                          │
└──────────────────────────────────────────────────────────────────────────────┘
```

**No guessed capability state. Claims are withheld rather than shown falsely.**

## 138. Exposure registry mismatch

```text
If the frontend cannot account for an active field present in the draft:
  Design  → refuse authoritative editing; show "unknown active field" finding
  Review  → refuse to present a complete review; Compile disabled
```

**Unknown science is never hidden.**

## 139. Responsive target

```text
≥ 1440 px   full engineering console
1280–1439   compact but complete (sidebar collapses to icons; tables keep all columns)
1024–1279   inspect-first: authoring available for Design only; inspectors read-only
< 1024      read-only: object inspection, evidence, capability. No authoring.
mobile      read-only: revision/evaluation/study/capability inspection.
            No topology authoring, no Design editing, no study setup.
```

## 140. Minimum supported viewport

```text
1280 × 720    minimum for FULL authoring (Design, Review, Evaluate, Serve, Optimize)
below 1280    inspect-only; a persistent banner states the limitation
```

**Scientific tables are never contorted into card stacks** — below the minimum,
the product reduces *capability*, not *comprehension*.

## 141. Accessibility

```text
keyboard access      every interactive element reachable; logical focus order
visible focus        always visible, 2px, not colour-only
labels               every input has a programmatic label; no placeholder-only labels
status text          aria-live for job state, findings and compile results
non-colour state     every status carries a glyph/label/rule (§131)
reduced motion       honour prefers-reduced-motion — all motion becomes instant
SVG alternatives     every scientific SVG has (a) a text summary and (b) the
                     inspectable data table that produced it. The table is the
                     accessible equivalent, not a description.
tables               real <table> semantics; header scope; row/column association
```

## 142. Motion

```text
PERMITTED   state transition (fade/slide ≤ 120 ms)
            selection and context change
            topology flow demonstration ONLY if it corresponds to real data
FORBIDDEN   ambient motion · floating particles · glowing animated networks ·
            decorative animated DAGs
```

## 143. Topology animation

**If packet/path animation is ever used it must correspond to real data or be
explicitly labelled a demonstration.** **Decorative animation never implies
measured runtime traffic.** Today no measured per-packet data exists, so
**topology animation is not used**.

## 144. Current visual reference

**Preserve:**

```text
engineering-console philosophy ("dense, flat, no gloss")
hand-rolled scientific SVG (FabricCanvas, FabricInspector, fabricLayout.ts)
clean light surface (the existing [data-theme='light'] token block)
existing --mono token
existing StatusBadge / Hash / Empty / fmtNum primitives
```

**Visual debt identified:**

```text
dark theme is the default (styles.css:3) — must invert to light-first
.card used for nearly every region — replace with section rules (§127)
TierBadge (LOCKED/GUIDED/FREE) — superseded by exposure classes (Gate 6)
WorkflowBar linear PIPELINE (01…05) — superseded by object-lifecycle nav (Gate 5)
FabricCanvas3D — no scientific depth dimension exists (§186)
landing/motion.ts + landing/styles.css — ambient motion; not part of the console
```

## 145. Current Studio screen audit

| Screen | Gate-5 verdict | Gate-8 interaction verdict |
|---|---|---|
| `pages/index.tsx` (home) | REBUILD | **REBUILD** — Project entry + summary; remove `intervention.supported` |
| `pages/design.tsx :: Design` | REBUILD | **KEEP CONCEPT, REBUILD LAYOUT** — section navigator + progressive disclosure |
| `pages/design.tsx :: Compile` | KEEP | **KEEP STRUCTURE** — becomes Compile Result §50 |
| `pages/design.tsx :: Verify` | REBUILD | **REBUILD** — four individual claims (§62) |
| `pages/design.tsx :: Simulate` | — | **MERGE** into Evaluate |
| `components/DesignEditor.tsx` | REBUILD | **REBUILD** — remove RCU + bandwidth; rename Radix; add disclosure |
| `components/FabricView.tsx` | MOVE | **KEEP STRUCTURE, MOVE** under Compile Result |
| `components/FabricInspector.tsx` | KEEP | **KEEP STRUCTURE** + semantic zoom (§57) |
| `components/FabricCanvas.tsx` | KEEP | **REFINE** — preview vs compiled framing (§35) |
| `components/FabricCanvas3D.tsx` | — | **REMOVE** (§186) |
| `components/EvaluateView.tsx` | REBUILD | **REBUILD** — profiles, qualification preflight |
| `components/VerifyView.tsx` | REBUILD | **REBUILD** — claim table |
| `components/OptimizeView.tsx` | KEEP | **KEEP STRUCTURE** — authority discipline correct |
| `components/OptimizationAnalysis.tsx` | KEEP | **KEEP** |
| `pages/optimize.tsx` | REBUILD | **REBUILD** — setup authorities separated |
| `pages/serving.tsx` | KEEP | **KEEP STRUCTURE** + ownership disclosure |
| `pages/evidence.tsx` | KEEP | **KEEP** — becomes the provenance drawer's full view |
| `pages/offline.tsx` | MOVE | **MOVE** — developer/demo path |
| `components/ArtifactChain.tsx` / `ArtifactStrip.tsx` | KEEP | **KEEP** — provenance |
| `studio.tsx :: WorkflowBar` | — | **REMOVE** — superseded by object-lifecycle nav |
| `studio.tsx :: ContextHeader` | — | **REFINE** — becomes the Draft/Revision context bar (§7) |
| `studio.tsx` AsyncView / useAsync / useJobPoll / ErrorBox | KEEP | **KEEP** — sound primitives |
| `badges.tsx :: TierBadge` | — | **REMOVE** — superseded by exposure classes |
| `badges.tsx :: StatusBadge / Hash / Empty / fmtNum / shortHash / humanize` | KEEP | **KEEP** |
| `router.ts` | — | **REFINE** — add object deep links (§150) |
| `landing/*` | — | **REMOVE** from the console (ambient motion) |

## 146. Final screen inventory

```text
 1  Project landing / open            /
 2  Design editor                     /projects/:pid/design
 3  Design Review                     /projects/:pid/design/review
 4  Compile Result (7 groups)         /revisions/:rid/:group
 5  Static Evaluation setup           /revisions/:rid/evaluate
 6  Static Evaluation result          /evaluations/:eid
 7  Comparison                        /compare?design=a,b | ?eval=a,b
 8  Serve setup                       /revisions/:rid/serve
 9  Serving result                    /serving/:sid
10  Optimize landing / studies        /projects/:pid/optimize
11  Study setup                       /projects/:pid/optimize/new
12  Study Review                      /projects/:pid/optimize/new/review
13  Study results                     /studies/:sid
14  Candidate detail                  /studies/:sid/candidates/:cid
15  History                           /projects/:pid/history
16  Capability explorer               /capability
17  Provenance drawer                 (universal overlay, no route of its own)
```

**No screen without a workflow.**

## 147. Avoid wizard explosion

```text
Study setup      seven labelled sections on ONE page (§84), not seven steps
Design           section navigator + continuous section, not a wizard
Review           one page, not a wizard
```

**Complex setup uses staged sections while preserving context.**

## 148. Modal policy

```text
MODAL ALLOWED   small destructive confirmation (apply preset over a dirty draft)
                small selection task (add requirement)
MODAL FORBIDDEN full Design editor · full Study setup · large scientific
                inspection · anything with its own deep link
NO NESTED MODALS
```

## 149. Drawer / side-panel policy

```text
RIGHT DRAWER   provenance (§115) and technical detail (§116) — universal, one
               instance, opened from any value, closable with Esc
               ALSO: object selection detail in inspectors (router/agent/link)
NOT A DRAWER   Design sections · Review · study setup · results — these are pages
```

## 150. URL / deep-link behaviour

```text
/projects/:pid/design
/projects/:pid/design/review
/revisions/:rid/summary|mapping|fabric|routing|resources|address-decode|provenance
/revisions/:rid/evaluate
/evaluations/:eid
/serving/:sid
/projects/:pid/optimize
/studies/:sid
/studies/:sid/candidates/:cid
/projects/:pid/history
/capability
/capability/:capabilityId
```

**Selected derived artifact is encoded in the path** (`/revisions/:rid/fabric?router=23`).
**Back/forward works** — the existing `router.ts` is a history router and is
extended, not replaced.

## 151. Unsaved draft navigation

**Audit result:** drafts **autosave to the server** (`PUT /projects/:id/draft`
on change; `DraftView.updated_at`). **There is therefore no unsaved-draft
warning** — that would be a fake warning.

```text
leaving Design with a dirty draft  →  no modal
```

## 152. Autosave feedback

```text
topbar:  Draft  ● Saving…   →   ● Saved 19:20   →   ⚠ Save failed [ retry ]
```

**`Saved` is never confused with `compiled`.** The context bar continues to show
`◉ Draft` until a compile succeeds.

## 153. Review / compile interaction test — Level 3

```text
TRIGGER        user activates "Review Design" on a READY draft
PRECONDITION   readiness != BLOCKED
UI RESPONSE    navigate to Review; render from the draft projection;
               record the reviewed snapshot hash
BACKEND        GET the review projection (no compile)
SUCCESS        Review renders CURRENT with the snapshot hash
FAILURE        projection unavailable → typed error; Compile disabled
IDENTITY       no identity change — a draft hash is read, not created

TRIGGER        user activates "Compile Design"
PRECONDITION   Review is CURRENT (snapshot == current draft)
UI RESPONSE    Compile in progress (§48)
BACKEND        POST compile { expected_draft_design_hash: <reviewed> }
SUCCESS        new immutable revision; navigate to Compile Result → Summary
FAILURE        STALE_REVIEW → §47 (refresh required)
               UNSUPPORTED/INVALID → §49 (Review preserved, typed refusal)
IDENTITY       a new revision identity is created; the draft is unchanged

TRIGGER        draft edited while Review is open
UI RESPONSE    Review flips to STALE (§47); Compile disabled
BACKEND        nothing until refresh or compile
```

## 154. Torus interaction test — Level 3

```text
select TORUS in Fabric
  → topology preview updates
  → ⚠ routed execution is unavailable in the current canonical pipeline
     (FAB-004 · DERIVABLE = NO)      [non-blocking]
  → Review: torus declared; capability consequence listed under CAPABILITY
  → Compile: SUCCEEDS (topology derives; certificate over the topology)
  → Compile Result → Fabric: exact compiled topology inspectable
  → Evaluate: unavailable — the route path is absent; the reason names
    route derivation, not the backend
```

**The workflow feels intentional, not broken.**

## 155. Concentration-2 / native profile test — Level 3

```text
Design concentration 2      → valid; no warning tied to a backend
Compile                     → SUCCEEDS
Evaluate                    → choose CERTIFIED_BOOKSIM_MESH_DOR_XY_V1
Qualification preflight     → NOT_QUALIFIED
                              predicate: concentration == 1  FAIL (observed 2)
                              ⓘ the design remains canonically valid
actions                     → choose another compatible profile
                            → change design → Fabric
                            → inspect the qualification failure
```

**The design is valid throughout.**

## 156. Static MoE test — Level 3

```text
author moe intent (ep > 1)  → ✓ declarable
capability consequence      → ⚠ static MoE lowering is not available
                              (WORK-002 · DERIVABLE = NO)
Compile                     → according to registry: lowering does not reach
                              execution; the typed stage is reported
Evaluate                    → NO false evaluation action is offered
```

## 157. Serving MoE test — Level 3

```text
Serve → MoE workload → ✓ dispatch/combine available in the serving path
                    → run serving experiment → request metrics + round evidence
Design → moe intent  → ⚠ static MoE lowering is not available
```

**The difference is visible through workflow**, not through marketing copy.

## 158. Multi-class test — Level 3

```text
Communication → add a second class → bind operations
  → ⚠ multi-class execution is not available (COMM-006 · PROJECTABLE = NO)
Review → COMMUNICATION section lists BOTH classes and their bindings
Compile → valid through verification
Evaluate → no execution path under a single-class envelope
```

## 159. Requirement reuse test — Level 3

```text
Evaluation E5 complete → RequirementReport shown
edit threshold R0 1200 → 1400
  → ⓘ measurement 0x9c11… is reused; no backend rerun
  → [ Recompute report ]
  → new RequirementReport for the SAME evaluation
  → no new revision, no new attempt, no new evidence
```

## 160. Optimization Pareto test — Level 3

```text
Study results → cand_9b03 is a Pareto MEMBER with requirements FAIL
  → both states visible in the row and in the detail
  → [ Compare ] against cand_4f2a
  → [ Select candidate ] (explicit study selection)
  → [ Use as new design ] disabled (OPT-008 · PRODUCT_NOT_WIRED)
```

**No contradiction between frontier membership and requirement status.**

## 161. Failed verification test — Level 3

```text
certificate DEADLOCK_FREE FAIL
  → open the cycle witness (§61)
  → involved classes / VCs / channels listed
  → routes and VC assignment cross-highlight in their inspectors
  → remedy points to upstream editable owners: Fabric · Communication
  → [ Edit a successor draft ] → new draft based on the compiled revision
```

**No manual VC patching action exists.**

## 162. Stale history test — Level 3

```text
Revision A has evaluation E2
user edits new Draft B
  → History still lists A and E2, unchanged
  → Evaluate page for Draft B shows "no current evaluation" (§64)
  → E2 remains attached to A
```

**No result disappearance.**

## 163. Provenance test — Level 3

```text
any metric value → ⓘ or the Provenance drawer
  metric → evidence → execution attempt → qualification → backend producer →
  certificate → compiled revision → draft snapshot
```

**The user can trace the claim source.** No confidence score.

## 164. Capability test — Level 3

```text
from a Torus limitation → "why?" → Capability FAB-004
  stages  declare ✓ · derive ✗ · …
  blocker NO_DERIVATION
  related ROUTE-004 torus routing
```

**No binary Support label.**

## 165. Wireframe fidelity levels

```text
Level 1   site/screen map                    §146, §5
Level 2   ASCII structural wireframes        §8–§107 (per screen)
Level 3   interaction-state wireframes       §153–§164 + §167
```

**No visual mockups, no code.**

## 166. ASCII wireframe requirements

**Every screen wireframe includes:** global shell · context · major content
regions · primary actions · status areas · secondary inspection. **Monospaced
diagrams.** The Level-2 wireframes above (§8, §11, §21–§107) follow this.

## 167. Interaction specification format — mandatory

Every important interaction is documented as:

```text
TRIGGER · PRECONDITION · IMMEDIATE UI RESPONSE · BACKEND ACTION ·
SUCCESS STATE · FAILURE STATES · SCIENTIFIC IDENTITY/FRESHNESS EFFECT
```

Applied in §153–§164 and §19, §47, §74.

## 168. State coverage matrix

| Screen | EMPTY | READY | DIRTY/STALE | LOADING/RUNNING | SUCCESS | BLOCKED | FAILED | UNAVAILABLE |
|---|---|---|---|---|---|---|---|---|
| Project landing | ✓ no project | ✓ | — | ✓ | — | — | ✓ | — |
| Design | ✓ new draft | ✓ | ✓ dirty | — | — | ✓ findings | ✓ save failed | — |
| Design Review | — | ✓ READY | ✓ STALE | — | — | ✓ BLOCKED | — | — |
| Compile Result | — | ✓ | ✓ superseded | — | ✓ | — | ✓ refused | — |
| Evaluate setup | ✓ no revision | ✓ | ✓ revision changed | — | — | — | ✓ | ✓ backend unavailable |
| Evaluate result | — | — | ✓ stale revision | ✓ running | ✓ EVALUATED | ✓ NOT_QUALIFIED | ✓ FAILED | ✓ UNSUPPORTED |
| Comparison | — | ✓ | — | — | ✓ comparable | — | — | ✓ INCOMPARABLE |
| Serve setup | ✓ no revision | ✓ | — | — | — | — | ✓ | ✓ |
| Serving result | — | — | — | ✓ running | ✓ | — | ✓ FAILED | ✓ |
| Optimize landing | ✓ no studies | ✓ | ✓ baseline changed | ✓ running | ✓ completed | — | ✓ | — |
| Study setup | — | ✓ | — | — | — | ✓ invalid definition | — | — |
| Study results | ✓ no candidates | ✓ | — | ✓ running | ✓ completed | — | ✓ failed | — |
| Candidate detail | — | ✓ | — | — | ✓ EVALUATED | — | ✓ typed failures | — |
| History | ✓ no objects | ✓ | — | — | — | — | — | — |
| Capability | — | ✓ | — | ✓ | — | — | ✓ registry error | — |

**No missing terminal states.**

## 169. Object-action matrix

| Object | Allowed user actions | Forbidden actions | Created object |
|---|---|---|---|
| **Draft** | edit fields · apply preset · validate · review · compile · select workload · discard | set `design_hash` · edit derived values · edit evaluation policy · edit study dimensions | Design Revision (via compile) |
| **Compiled Revision** | inspect · evaluate · serve · optimize · compare · archive · fork to successor draft · promote candidate *into* it | edit any intent field · edit derived artifacts · edit the certificate · mutate `design_hash` | Evaluation · Serving Experiment · Study · successor Draft |
| **Evaluation** | run · retry · cancel · recompute report · compare · inspect provenance · archive | edit design values · change the compiled revision · edit the backend producer | RequirementReport · ExecutionAttempt |
| **Serving Experiment** | run · retry · cancel · inspect · compare · archive | edit design values · reuse static evaluation forms | Round evidence |
| **Study** | create · run · cancel · inspect candidates · select candidate · compare · archive | mutate the baseline revision · edit the study definition after completion · promote (not wired) | Candidate · OptimizationResult |
| **Candidate** | inspect · compare · focus · select (study selection) | edit the candidate · promote (not wired) · alter `candidate_id` | successor Draft (only via promotion, not wired) |
| **RequirementSet** | edit thresholds · add/remove · recompute report | block compile · remove a Pareto member · change measurements | RequirementReport |
| **Capability row** | inspect · filter · link to a related action | edit · claim availability · enable a `FUTURE_CONTRACT` control | — |

## 170. Screen-authority matrix

| Screen state | Scientific authority | Frontend may not |
|---|---|---|
| Design authoring | draft intent (backend canonical) | compute canonical values · infer readiness from field text |
| Design Review | draft projection + capability registry | recompute completeness · refresh silently · claim qualification |
| Compile Result | compiled artifacts + certificate | derive artifact values · edit derived objects |
| Routing inspector | `RouteArtifact` + `ResolvedRoute` | merge expected with observed |
| Certificate | verifier verdicts | collapse claims into one status |
| Evaluate setup | capability registry + qualification profile | substitute a backend · claim availability |
| Evaluate result | metric registry + authenticated evidence | compute metrics · coerce `UNMEASURABLE` to 0 |
| Comparison | metric registry comparability | compare incompatible producers · show percentages |
| Serve | serving runtime + round evidence | reuse static metrics · conflate ownership |
| Optimize setup | `StudyDefinition` + registry | hide a dimension · offer a future-contract dimension |
| Study results | `OptimizationResult` (backend Pareto) | recompute Pareto · infer `EVALUATED` from non-empty cells |
| Candidate detail | backend candidate record | relabel a status · hide a failure |
| History | object identities | fabricate ordering semantics |
| Capability | `capability-registry.yaml` + version | hardcode a support boolean |
| Provenance | evidence chain | invent a confidence score |

**The frontend is never scientific authority.**

## 171. Data loading strategy

```text
Design           GET draft + DesignViewV2 (values, exposure, validation,
                 previews, consequences, freshness)          ONE projection
Design Review    GET DesignViewV2 with presentation=review     SAME projection
Compile Result   GET CompileResultView (references artifacts)  ONE projection
Evaluate setup   GET capability + qualification data           targeted
Evaluate result  GET EvaluationView                            ONE projection
Serve            GET ServingView                                ONE projection
Study results    GET OptimizationStudyView v2 (existing)       ONE projection
Candidate        subset of the study view + candidate detail
History          GET project object index                      ONE projection
Capability       GET /api/v1/capabilities (exists)             ONE projection
```

**No one giant endpoint dumping the whole project. No dozens of chatty calls.**

## 172. `DesignViewV2` wire contract

```text
DesignViewV2 {
    contract_version: 2
    presentation: "edit" | "review"
    draft_identity: { project_id, draft_design_hash }
    parent_revision_ref?: { revision_id, label }
    readiness: READY | INCOMPLETE | INVALID | PREFLIGHT_BLOCKED |
               CAPABILITY_LIMITED_BUT_COMPILABLE
    sections: [{
        id, title, exposure: GUIDED | EXPERT,
        entries: [{
            field,                       canonical path
            label,                       product terminology
            value,                       canonical value (never reconstructed)
            unit?,
            semantic_class: DECLARED | DERIVED_PREVIEW | METADATA |
                            CAPABILITY_CONSEQUENCE,
            exposure_class: G1|G2|E1|E2|METADATA|NOT_RENDERED|LEGACY_ONLY,
            source: USER_SELECTED | RECOMMENDATION | SEMANTIC_DEFAULT,
            validation?: { state, code, message },
            capability_ref?: [capability_id],
            ownership?: { domain, canonical_field, identity_effect },
            hidden_active?: bool
        }],
        advanced_active_count: int,
        blocking_count: int,
        limitation_count: int
    }]
    derived_summaries: [{ id, label, value, kind: "PRE_COMPILE_DERIVED_SUMMARY" }]
    validation_findings: [{
        class: BLOCKING_ERROR | DOWNSTREAM_LIMITATION | INFORMATION |
               LEGACY_MIGRATION_NOTICE,
        owner_domain, code, message, affected, blocking,
        remediation_owners: [section_id]
    }]
    capability_consequences: [{ capability_id, consequence, registry_version }]
    scientific_diff?: [{ field, before, after, kind: added|removed|changed }]
    capability_semantics_version: "cap-v1"
}
```

**The frontend never reconstructs canonical semantics.**

## 173. Compile Result view contract

```text
CompileResultView {
    contract_version, revision_id, revision_label, design_hash, parent_revision_ref,
    compiled_at, compiler_semantics_version, resolved_fabric_hash, certificate_id,
    certificate: { claims: [{ name, status, scope }], overall },
    capability_consequences: [...],
    groups: {
        summary, mapping, fabric, routing, resources, address_decode, provenance
    }   — each a REFERENCE (artifact hash) plus the minimal presentation data
}
```

**References artifacts rather than letting the frontend reconstruct them.**

## 174. Evaluation view contract

```text
EvaluationView {
    contract_version, evaluation_id, revision_id,
    qualification: { profile_id, envelope, semantics_version, status, predicates[] },
    execution:     { attempt_id, status, elapsed_s, started_at },
    metrics:       [{ metric_id, label, value | "UNMEASURABLE", unit, producer_id,
                      semantics_version, reason? }],
    requirements:  [{ requirement_index, target, metric, op, threshold, verdict,
                      binding }],
    evidence:      { performance_result_id, proof_ref },
    provenance_ref
}
```

## 175. Optimization view contract

**Keep `OptimizationStudyView` v2 authority. No second frontend study model.**
The frontend consumes `definition`, `candidates[]`, `pareto_ids`,
`selected_candidate_id`, `selection_rationale` exactly as specified in Gate 4/J.
**It does not recompute Pareto.**

## 176. Capability view contract

```text
CapabilityView {
    contract_version, capability_semantics_version, registry_id,
    rows: [{
        id, name, owner, stages: {DECLARABLE…PRODUCT_WIRED},
        conditions[], wiring, reason?, limiting?, claim_scope?, future_contract?
    }],
    envelopes: [...], conditions: [...]
}
```

**No hardcoded support booleans in the frontend.**

## 177. Exposure view contract

**The frontend consumes exposure semantics from `DesignViewV2.sections[].entries[]`
(§172).** It **does not** maintain a parallel TypeScript list of fields without
validation. A build-time check asserts the frontend's known classes against
`exposure-registry.yaml`.

## 178. Implementation sequencing

```text
 1  REMOVE-FIRST: RCU control + .rcu-refusal · bandwidth control ·
    intervention.supported boolean · "Radix" label · FabricCanvas3D ·
    WorkflowBar PIPELINE · TierBadge · landing/* · legacy CLI surfaces
 2  Foundation: light-first theme · shell (topbar, sidebar, context bar) ·
    object-lifecycle nav · panel/rule system · typography + tabular figures
 3  Shared primitives: table · finding block · capability glyph row ·
    claim table · provenance drawer · ⓘ inline detail · status glyphs
 4  Backend-blocked: DesignViewV2 (§172) → Design authoring (§8–§39)
 5  Review + compile locking: DesignViewV2 presentation=review ·
    expected_draft_design_hash · STALE_REVIEW
 6  Compile Result: seven groups (§50–§63)
 7  Evaluate: setup · qualification · result · requirement reuse (§64–§75)
 8  Comparison (§76–§78)
 9  Serve (§79–§82)
10  Optimize reconciliation (§83–§103)
11  History + archive (§104–§106)
12  Capability explorer (§107–§114)
13  Accessibility pass (§141) · responsive pass (§139) ·
    visual regression lock (§182)
```

## 179. Backend-first blockers

```text
DesignViewV2 (sections, exposure classes, source-of-value, ownership,
              hidden_active, derived summaries, findings, consequences,
              scientific diff)                      ← blocks Design, Review
expected_draft_design_hash + STALE_REVIEW          ← blocks Review→Compile
readiness decomposition (design vs evaluation)      ← blocks Design header,
                                                      Evaluate setup
capability/exposure projection with versions        ← blocks Capability,
                                                      all claim surfaces
address_map + physical in DesignViewV2              ← blocks Memory/Physical
                                                      Review sections
CompileResultView aggregation                       ← blocks Compile Result
```

**No fake frontend substitutes are built for any of these.**

## 180. Parallelisable frontend work

```text
shell (topbar, sidebar, context bar, nav)
generic table (sticky, sort, filter, virtualization, tabular figures)
finding block + class vocabulary
capability glyph row + claim table
provenance drawer frame
ⓘ inline detail
status glyph + label system
theme tokens (light-first)
```

**These carry no science-specific fake data paths.** Any placeholder uses clearly
synthetic fixtures, never production authority.

## 181. Remove-first strategy

```text
REMOVE  rcu_enabled control + .rcu-refusal banner          (GX-D6)
REMOVE  bandwidth_floor_gbps control                       (GX-D6)
REMOVE  intervention.supported boolean                     (CAP-D2)
REMOVE  "Radix" label → "Mesh side length"                 (PF-D12)
REMOVE  FabricCanvas3D                                     (§186)
REMOVE  WorkflowBar linear PIPELINE                        (§145)
REMOVE  TierBadge                                          (§144)
REMOVE  landing/* ambient motion                           (§142)
REMOVE  legacy CLI surfaces (synthesize/sweep/baseline) + deprecated POST /optimize (PF-D15)
REMOVE  "Latest run" concept                               (PF-D13)
```

## 182. Visual regression targets

```text
1  Design → Fabric (preview, advanced disclosure, concentration consequence)
2  Design Review (nine sections + derived summary + consequences + diff)
3  Compile Result → Fabric inspector (compiled, semantic zoom)
4  Evaluation result (qualification + metrics + requirements + UNMEASURABLE)
5  Optimization results (candidate table + Pareto + requirement annotation)
6  Capability explorer row (eight-stage glyph row)
```

## 183. Interaction regression targets

```text
1  review stale rejection          (R22, §47, §153)
2  torus inspect-only              (R6, §154)
3  qualification refusal           (R7, §155)
4  requirement threshold reuse     (R21, §159)
5  Pareto member + requirement violation  (R16, §160)
6  candidate promotion unavailable (OPT-008, §103)
```

## 184. Performance considerations

```text
topologies       semantic zoom above 256 routers (§57)
candidate tables virtualization above 200 rows
mapping tables   virtualization above 200 rows
history          paginate object groups; lazy per-group detail
small forms      no premature optimization
```

## 185. SVG performance

**Audit:** `FabricCanvas.tsx` + `fabricLayout.ts` render hand-rolled SVG.

```text
≤ 64 routers     full SVG, all links, labels on selection
65–256 routers   full SVG; no per-router text nodes
> 256 routers    SVG is inappropriate — switch to an aggregate view
                 (occupancy/summary blocks) with drill-down to a region
```

**Threshold: 256 routers.** Above it, **semantic simplification, not a bigger
SVG.** **No 3D rendering is introduced as a performance workaround.**

## 186. No 3D requirement

**There is no scientific depth dimension.** Mesh, torus and concentrated mesh are
planar; concentration is a per-router property; there is no z-axis in the
canonical `TopologyArtifact`.

```text
FabricCanvas3D.tsx  →  REMOVE
```

**3D would be misleading**, not merely unnecessary.

## 187. Visual density modes

**One visual density system.** Progressive disclosure already handles complexity.
**No separate "simple" and "expert" themes.**

## 188. Copy tone

```text
technical · concise · precise
```

**Forbidden copy:** "Awesome!" · "Magic" · "AI-powered" · "Supercharge" ·
"Perfect" · exclamation marks in status text.

**Warnings state exact limitations** — *"routed execution is unavailable in the
current canonical pipeline"*, not *"something went wrong"*.

## 189. Status vocabulary enforcement

```text
USE      compile ready · certificate PASS · qualified · evidence available ·
         product wired · INSPECT_ONLY · ENGINE_ONLY
NOT      SUPPORTED · VERIFIED as umbrella states
```

## 190. Forbidden copy audit

Every wireframe text sample was checked. **None of the following appears:**

```text
"Torus supported"                        → "topology construction available;
                                            routed execution not available"
"Multicast supported"                    → "semantic multicast lowers to
                                            unicasts; hardware multicast is not
                                            modeled"
"Full route verified by BookSim"         → "canonical route verified; backend
                                            first hop observed"
"Ramulator integrated end-to-end"        → "engine available; not connected to
                                            the current product workflow"
"Hardware-accurate latency"              → not claimed anywhere
"Optimal NoC"                            → not claimed anywhere
```

## 191. Screen-specific claim audit

| Screen | Claim authority | Sample text |
|---|---|---|
| Design | draft projection + capability registry | capability consequences only |
| Review | design-side prerequisites only | *"compatible with the design-side prerequisites of …"* — **never** `QUALIFIED` |
| Compile Result | certificate + artifact hashes | four individual claims |
| Routing | `RouteArtifact` | `CANONICAL DERIVED ROUTE` |
| Route observation | `route_observation` evidence | exact Gate-4 first-hop wording |
| Evaluate result | metric registry + evidence | producer and semantics version shown |
| Study results | backend Pareto | `pareto_member` read, never computed |
| Capability | registry row | stage glyphs, never a boolean |

**Numerical illustrations in this document are synthetic placeholders** and are
labelled as such where they appear. **No benchmark claims are fabricated.**

## 192. Final visual-system specification

```text
layout grid        12-column; content max-width none (engineering console fills);
                   sidebar 200 px (icon-only 56 px below 1440)
spacing rhythm     4 px base; 4/8/12/16/24/32; sections separated by 24 px + a rule
border/radius      borders 1 px solid --border; radius 2 px on inputs/tables,
                   0 px on panels — flat, not rounded
typographic h.     §128 order; UI 13 px base, 12 px table, 11 px metadata
table density      row height 28 px (comfortable) / 24 px (dense toggle later);
                   sticky header 32 px
panel hierarchy    canvas → section (rule) → subsection (label) → table (border)
                   → inspector (drawer/panel) → finding (left rule)
status treatment   glyph + short label + optional count; colour secondary
icon usage         monochrome, 14 px, meaning-bearing only; no decorative icons
monospace usage    IDs · addresses · hashes · cycles · canonical field names
chart style        axes labelled with units; no gridlines-for-decoration;
                   no gradients; no radar; points selectable and cross-highlighting
SVG style          1 px strokes; --border for links; --accent for selection;
                   fill only for occupancy; no shadows, no glow, no gradients
motion rules       ≤120 ms, state/selection only; honours prefers-reduced-motion
```

## 193. Current-style reconciliation

```text
PRESERVE   the "dense, flat, no gloss" philosophy
           the token-variable system (--bg/--border/--text/--muted/--accent/--ok/…)
           the --mono token
           flat 1 px borders
           the light token block (promote it to :root)
REFINE     border contrast (+1 step for dense tables)
           panel system: replace .card with section rules
           table density and tabular figures
           status treatment: add glyphs so colour is never the only channel
REMOVE     dark-as-default
           .card as the universal container
           TierBadge, WorkflowBar, FabricCanvas3D, landing/*
```

**No full rewrite** — the existing structure and philosophy are strong.

## 194. Final information hierarchy

| Destination | Primary question answered |
|---|---|
| **Design** | *What am I asking SROTA to build?* |
| **Evaluate** | *How does this compiled design perform under a qualified static evaluation?* |
| **Serve** | *How does this compiled design behave under request-driven serving?* |
| **Optimize** | *What candidate designs trade off my measured objectives?* |
| **History** | *What immutable scientific work has this project produced?* |
| **Capability** | *What can the system actually represent, derive, execute and claim?* |

**One clear purpose per destination.**

## 195. W1–W30 verdicts

| # | Case | Verdict |
|---|---|---|
| W1 | user cannot tell Draft from Revision | **PASS** — context bar §7, always visible |
| W2 | Torus shown disabled entirely | **PASS** — `ALLOW + INSPECT`, §36 |
| W3 | RCU appears disabled in Advanced | **PASS** — removed, not rendered (§181) |
| W4 | VC count editable at Expert depth | **PASS** — `DERIVED_INSPECT`, §60 |
| W5 | Review omits a hidden Communication class | **PASS** — §42 lists both; §45 advanced-included |
| W6 | Review auto-refreshes after a draft edit and leaves Compile active | **PASS** — §47 stale, Compile disabled + refused |
| W7 | Evaluation profile changes Design dirty state | **PASS** — profiles live in Evaluate; Design untouched |
| W8 | `NOT_QUALIFIED` shown as invalid Design | **PASS** — §68 states the design remains valid |
| W9 | `UNMEASURABLE` displayed as 0 | **PASS** — §71, §72 labelled state |
| W10 | Pareto recomputed in the frontend | **PASS** — §98 consumes `pareto_member`/`pareto_eligible` |
| W11 | requirement-violating Pareto member disappears | **PASS** — §100 both states visible |
| W12 | serving MoE label implies static MoE support | **PASS** — §82 explicit distinction |
| W13 | Ramulator gets a Run button | **PASS** — §111 no action |
| W14 | Torus has Compile but no topology inspector | **PASS** — §50 Fabric group, §154 |
| W15 | capability page uses a Supported checkbox | **PASS** — §108 eight-stage glyph row |
| W16 | Mapping table editable | **PASS** — §53 read-only |
| W17 | deadlock witness offers a manual VC edit action | **PASS** — §61 remedy points upstream only |
| W18 | candidate row click changes scientific selection | **PASS** — §102 three distinct concepts |
| W19 | promotion mutates an existing revision | **PASS** — §103 creates a successor |
| W20 | old Evaluation disappears after a new Draft | **PASS** — §162 History retains it |
| W21 | network clock appears in Design | **PASS** — Evaluate only (§65) |
| W22 | `radix` appears as a user-facing field | **PASS** — "Mesh side length" (§16) |
| W23 | preset hides resulting scientific values | **PASS** — §19 change preview |
| W24 | topology preview identical to compiled exact topology without a label | **PASS** — §35 distinct framing |
| W25 | certificate collapsed into one generic Verified badge | **PASS** — §62 claim table |
| W26 | metric shown without a unit | **PASS** — §71, §72 |
| W27 | incompatible evaluations show percentage improvement | **PASS** — §78 `INCOMPARABLE` |
| W28 | capability registry mismatch silently ignored | **PASS** — §137 claims withheld |
| W29 | unknown API enum silently omitted | **PASS** — §136 fail closed |
| W30 | mobile layout hides scientific columns but still claims full authoring | **PASS** — §139/§140 read-only below 1280 |

**Additional cases exposed during wireframing:**

| # | Case | Verdict |
|---|---|---|
| W31 | Design header shows evaluation/backend state | **PASS** — §11 excludes it |
| W32 | collapapsed Advanced hides an active non-default value | **PASS** — §13 indicator |
| W33 | Review claims `QUALIFIED` precompile | **PASS** — §42/§50 prerequisite wording only |
| W34 | requirement appears as `PASS` before measurement | **PASS** — §31 note, §73 post-measurement |
| W35 | frontend estimates router count locally | **PASS** — §34/§42 backend `PRE-COMPILE DERIVED SUMMARY` |
| W36 | toast is the only failure signal | **PASS** — §118 persistent structured state |
| W37 | running study lost on navigation | **PASS** — §119 shell-level jobs |
| W38 | cancel deletes the scientific definition | **PASS** — §120 cancels the attempt only |
| W39 | retry creates a new Design revision | **PASS** — §121 same definition, new attempt |
| W40 | archive leaves a dangling reference | **PASS** — §106 archive preserves resolvability |
| W41 | a `FUTURE_CONTRACT` field appears as a disabled control | **PASS** — §113 no controls |
| W42 | capability page offered as ordinary workflow | **PASS** — §109 expert-oriented |
| W43 | 3D topology used because it looks impressive | **PASS** — §186 removed |
| W44 | mobile card-stacks a scientific table | **PASS** — §140 capability reduced, not comprehension |

## 196. I1–I20 answers

| # | Answer |
|---|---|
| **I1** | **Remove-first (§181)**, then the foundation shell (§178 step 2). No new screen ships before the false controls are gone. |
| **I2** | **`DesignViewV2`** (§172) — it blocks Design, Review and every claim surface. |
| **I3** | RCU control + banner · bandwidth control · `intervention.supported` · "Radix" label · `FabricCanvas3D` · `WorkflowBar` · `TierBadge` · `landing/*` · legacy CLI surfaces (§181) |
| **I4** | `FabricInspector` · `FabricCanvas` · `OptimizeView` · `OptimizationAnalysis` · `ArtifactChain`/`ArtifactStrip` · `AsyncView`/`useAsync`/`useJobPoll`/`ErrorBox` · `StatusBadge`/`Hash`/`Empty`/`fmtNum`/`shortHash`/`humanize` · the token system |
| **I5** | `DesignEditor` · `VerifyView` · `EvaluateView` · `pages/design.tsx` · `pages/index.tsx` · `pages/optimize.tsx` · `ContextHeader` (refine) |
| **I6** | table · finding block · capability glyph row · claim table · provenance drawer · ⓘ inline detail · status glyph+label · context bar · section navigator |
| **I7** | `DesignViewV2` · `CompileResultView` · `EvaluationView` · `OptimizationStudyView` v2 · `CapabilityView` · `ServingView` · `DraftView` |
| **I8** | presentation state only: disclosure expansion, drawer open, table sort/filter/cursor, form focus, theme. **Never** canonical values, readiness, capability truth or identity. |
| **I9** | from the URL (`/projects/:pid/...`, `/revisions/:rid/...`) plus the context bar; every page reads the active revision from the route, never from ambient state |
| **I10** | every claim surface checks `capability_semantics_version` (and the exposure registry's known classes) and **withholds claims** on mismatch (§137, §138) |
| **I11** | `GET DesignViewV2(presentation=review)` → user reads → `POST compile { expected_draft_design_hash }` → `STALE_REVIEW` or a new revision (§153) |
| **I12** | a job object (`queued/running/completed/failed/cancelled`) with a shell-level indicator; job state is never scientific state (§119, §120) |
| **I13** | one right-hand provenance drawer (§115), opened from any value via ⓘ or a value action |
| **I14** | > 200 rows (§184), with sticky headers and tabular figures |
| **I15** | hand-rolled SVG ≤ 256 routers; above that an aggregate view with drill-down (§185) |
| **I16** | **1280 × 720** for full authoring (§140) |
| **I17** | read-only inspection below 1280 and on mobile — no authoring, no study setup, no topology editing (§139) |
| **I18** | SVG textual alternatives + the underlying data table; focus visibility; `aria-live` for jobs/findings; non-colour state channels (§141) |
| **I19** | shell · tables · finding block · glyph rows · claim table · drawer frame · ⓘ · theme (§180) |
| **I20** | never mock: readiness · capability stages · certificate claims · qualification · metric values · Pareto membership · `design_hash`. Only **layout** may use synthetic fixtures, clearly marked (§191). |

## 197. Deliverable checklist

| # | Required content | § |
|---|---|---|
| 1 | exact visual primitive definitions | §1 |
| 2 | target visual philosophy | §2 |
| 3 | global shell | §5 |
| 4 | final screen inventory | §146 |
| 5 | site map | §146, §150 |
| 6 | Design wireframe | §8–§13 |
| 7 | each Design-section wireframe | §21–§33 |
| 8 | Review wireframe | §42–§46 |
| 9 | Compile Result wireframes | §50–§52 |
| 10 | Mapping inspector | §53, §54 |
| 11 | Fabric inspector | §55–§57 |
| 12 | Routing/VC/deadlock inspectors | §58–§61 |
| 13 | Certificate inspector | §62, §63 |
| 14 | Evaluate setup/result | §64–§72 |
| 15 | Requirement result/reuse flow | §73, §74, §159 |
| 16 | Comparison | §76–§78 |
| 17 | Serve setup/result | §79–§82 |
| 18 | Optimize setup/results | §83–§94 |
| 19 | candidate detail/compare | §95–§103 |
| 20 | History | §104–§106 |
| 21 | Capability explorer | §107–§114 |
| 22 | provenance/detail interaction | §115, §116 |
| 23 | error/finding system | §38, §39, §117, §118 |
| 24 | loading/running/stale states | §47, §48, §119, §135 |
| 25 | responsive policy | §139, §140 |
| 26 | accessibility policy | §141 |
| 27 | keyboard interactions | §122, §123 |
| 28 | Level-1 site map | §146, §150 |
| 29 | Level-2 ASCII screen wireframes | §8–§107 |
| 30 | Level-3 critical interaction-state diagrams | §153–§164 |
| 31 | state-coverage matrix | §168 |
| 32 | object-action matrix | §169 |
| 33 | screen-authority matrix | §170 |
| 34 | API/view-contract requirements | §171–§177 |
| 35 | current Studio preserve/rebuild/remove audit | §144, §145, §193 |
| 36 | implementation sequence | §178 |
| 37 | backend blockers | §179 |
| 38 | regression targets | §182, §183 |
| 39 | W1–W30+ verdicts | §195 |
| 40 | I1–I20 answers | §196 |
| 41 | Gate verdict | §200 |

## 198. No code deliverable

**No HTML · no CSS · no React · no production SVG · no Figma export · no image
assets were produced.** ASCII wireframes and interaction specifications only.

## 199. Coherence check against §199 criteria

| # | Criterion | Status |
|---|---|---|
| 1 | every primary workflow has a screen path | **MET** (§146, §150) |
| 2 | every WIRED capability has a usable interaction path | **MET** (§146, §133 in Gate 4) |
| 3 | every INSPECT_ONLY capability has an inspection path | **MET** (§50, §112) |
| 4 | ENGINE_ONLY does not gain fake execution | **MET** (§111) |
| 5 | FUTURE_CONTRACT fields never appear as controls | **MET** (§113, §181) |
| 6 | one canonical editor implements progressive disclosure | **MET** (§8–§13) |
| 7 | hidden active science remains discoverable | **MET** (§13, §45) |
| 8 | Review is complete and stale-safe | **MET** (§42, §47) |
| 9 | Draft vs Revision is always clear | **MET** (§7) |
| 10 | Compile Result separates declared/derived/verified | **MET** (§52, §62) |
| 11 | expected vs observed routing is visually separate | **MET** (§58, §59) |
| 12 | certificate claims are individually visible | **MET** (§62) |
| 13 | static Evaluate and Serve remain separate | **MET** (§65, §79) |
| 14 | qualification is not design validity | **MET** (§68, §155) |
| 15 | Requirement reuse requires no fake rerun | **MET** (§74, §159) |
| 16 | optimization authorities remain separated | **MET** (§84–§92) |
| 17 | Pareto remains backend-authoritative | **MET** (§98) |
| 18 | candidate promotion preserves revision immutability | **MET** (§103) |
| 19 | provenance is universally reachable | **MET** (§115) |
| 20 | capability stages replace Supported | **MET** (§108) |
| 21 | all important terminal/error states are wireframed | **MET** (§168, §49, §68) |
| 22 | responsive behavior preserves scientific comprehension | **MET** (§139, §140) |
| 23 | accessibility is specified | **MET** (§141) |
| 24 | current false controls/claims have a removal plan | **MET** (§181) |
| 25 | backend-first blockers are explicit | **MET** (§179) |
| 26 | implementation order is executable | **MET** (§178) |
| 27 | no scientific semantics remain for the frontend to invent | **MET** (§170, §172) |
| 28 | W1–W30+ have verdicts | **MET** (§195) |
| 29 | I1–I20 are answered | **MET** (§196) |
| 30 | no production code was written | **MET** (§198) |

## 200. Domain verdict

Gate 8 converted the closed planning architecture into a buildable interaction
specification. The two most consequential findings were both **subtractions**.

**`FabricCanvas3D.tsx` must be removed.** The canonical `TopologyArtifact` has no
depth dimension — mesh, torus and concentrated mesh are planar, and concentration
is a per-router property. **3D here would be misleading**, not merely
unnecessary, and Gate 8's job was to notice that rather than preserve an
impressive-looking component.

**The current Studio has dark as its default theme** (`styles.css:3` —
`:root, [data-theme='dark']`). The light token block already exists and matches
the target; the change is an inversion, not a redesign. And the existing
philosophy — *"dense, flat, no gloss"* — is already the right one, so the visual
system is a **refinement**: raise border contrast, replace `.card` with section
rules, add glyph channels so colour is never the sole carrier of state.

The structural choice was **left section navigator + central editor**, and it is
forced by the numbers: **69 exposure-registry rows** cannot be scanned as one
scroll, per-section readiness counts need a persistent home, and cross-domain
findings must be able to *navigate to a section*. Within a section the editor
stays a continuous document — **not a wizard**.

Two decisions were made against the tempting default. **The command palette is
navigation-only**, deliberately excluding Compile, Run Evaluation and Run Study,
because those must flow through Review and qualification preflight — a palette
command would bypass exactly the snapshot binding Gate 7 exists to guarantee.
And **the capability page is expert-oriented**, not an ordinary workflow surface.

The interaction specification carries the gates forward without diluting them:
`pareto_member` is read, never computed; `UNMEASURABLE` is a labelled state, never
zero; the certificate is four claims, never one badge; `NOT_QUALIFIED` never
becomes an invalid design; Torus compiles and is inspectable while evaluation is
unavailable at the route stage; and Review shows design-side prerequisites while
**never claiming `QUALIFIED`** before qualification runs.

**Forty-four adversarial cases pass.** Twenty implementation-readiness questions
are answered. The remove-first list is explicit, the backend blockers are named,
and the sequencing is executable.

**GATE 8 — STUDIO WIREFRAMES / INTERACTIONS: PLANNED — COHERENT**

**PLANNING PROGRAM COMPLETE — IMPLEMENTATION MAY BEGIN**
