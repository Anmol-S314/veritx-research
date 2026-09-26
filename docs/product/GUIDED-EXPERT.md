# GUIDED-EXPERT — Gate 6 (authoring architecture)

Authority: `PRODUCT-FLOWS.md`, `CAPABILITY-MATRIX.md`, `CROSS-DOMAIN-LAWS.md`,
the eleven `INTENT-*.md` domain documents, `intent-ontology.yaml`,
`capability-registry.yaml`. Current Studio audited **only after** the contracts.
Status: **PLANNED — COHERENT.** See §133.

---

## 1. The chosen architecture (§117, §118) — **one editor, progressive disclosure**

```text
ONE canonical Design editor
├── GUIDED DISCLOSURE      (default)  the coherent subset
└── EXPERT DISCLOSURE      (expansion) every accepted editable field
```

**There is no hard Guided/Expert toggle and no second editor.**

**Why not option A (hard modes):** a hard toggle implies two editors over one
contract, which invites two normalizations, two validation paths and eventually
two sciences. It also creates a **lossy-switch problem** that progressive
disclosure simply does not have — and Gate 6's own §4/§5 forbid lossy conversion
and mode-dependent identity. A mode that must be *proved* not to change science is
weaker than an architecture where **no such state exists**.

**Why progressive disclosure wins:** the governing principle is *"how much
accepted intent is directly exposed"* (§1). That is **disclosure depth**, not a
mode. Disclosure depth is a presentation property; a mode is a product concept
that must then be constrained (§5) and reconciled (§50–§52).

**Naming (§116):** the two disclosure levels are **Guided** and **Expert**.
Terminology is technically respectful: *Guided* describes the workflow, not the
user's competence.

**Optimization keeps a stronger distinction (§119)** — §19 explains why that is
consistent, not a special case.

## 2. Central distinction (§1)

```text
GUIDED vs EXPERT  =  how much accepted intent is directly exposed
```

**Not:** different fields with different semantics · a different compiler ·
invisible different defaults · different capability truth.

## 3. Mode invariants (§2) — proved

| Invariant | Proof |
|---|---|
| same canonical Intent Draft schema | both edit the **same draft**, whose canonical serialization is `CompileRequestV3` (Gate 5 D1) |
| same canonical normalization | normalization is backend-owned (§80); there is one canonicalizer per field |
| same validation | one validator set; only the **message level** differs (§55, §109) |
| same design identity for identical content | `design_hash` derives from `CompileRequestV3` only — disclosure state is not in the schema (§5) |
| same compile result | one `FabricCompiler` entry point |
| same certificate | one verifier |
| same backend qualification | one qualification path over the same revision |

**These hold structurally, not by discipline**, because there is exactly one
editor writing exactly one draft schema.

## 4. Guided is lossless (§3)

Every scientific value Guided materializes is an **ordinary field in the draft**
(§6). Expanding to Expert shows **the same fields with the same values**.

**No field may appear in Expert as "automatic".** There is no `automatic` state —
a materialized value is a value.

## 5. Expert round-trips (§4)

```text
Expert design expressible by Guided  → Guided shows it faithfully
Expert design NOT expressible        → "GUIDED VIEW CANNOT REPRESENT THIS DESIGN"
                                       read-only summary + stay in Expert
```

**Guided never silently alters or collapses Expert intent** (§99).

## 6. Mode is presentation metadata (§5)

Disclosure state does **not** enter `intent_id`, `design_hash`, artifact identity
or evidence identity. **Two scientifically identical designs authored at different
disclosure depths are the same design science.**

## 7. No hidden scientific defaults (§6)

```text
REQUIRED:  Guided choosing mesh / side_length=8 / concentration=1 / link_width=256
           writes those values EXPLICITLY into the draft.
FORBIDDEN: storing preset="balanced" and deriving the values only at compile.
```

**Presets are authoring shortcuts** (§8).

## 8. Preset expansion law (§7) and identity (§8)

```text
preset selection → expands into ordinary canonical intent fields
after expansion  → the preset is PROVENANCE only
```

**Already implemented correctly** in the repository: `CompileIntent` carries
`fabric_preset` **and** `preset_design_hash`, documented as *"the `design_hash()`
of the un-overridden base preset under that compiler [semantics] … preset
fingerprint"* (`application/compile_intent.py:51-54`). **A changed preset
implementation cannot reinterpret an old saved design** — the pin moves, the old
draft's materialized values do not.

**Preset provenance belongs to draft/revision metadata, not `design_hash`.**

## 9. Guided must not invent capability (§9)

Guided may **simplify existing** capability; it may **not** expose future
contracts. Therefore no Guided control for:

manual placement · VC count · routing-function override · turn restrictions ·
**RCU** · hardware multicast · multiplane · adaptive routing · valiant ·
memory timing · Ramulator profile as Design Intent.

## 10. Expert is not "show everything" (§10)

Expert exposes **accepted canonical user intent** and still excludes
compiler-derived fields. Expert also does **not** expose editable: Mapping ·
exact routes · VC IDs · VC count · endpoint IDs · turn restrictions · certificate
verdict · backend node IDs.

**Expert ≠ internal debugger.**

## 11. Exposure taxonomy (§11)

```text
G1  GUIDED PRIMARY        frequent, scientifically meaningful
G2  GUIDED ADVANCED       real intent, uncommon — behind the expansion
E1  EXPERT PRIMARY        accepted intent, expected in the Expert expansion
E2  EXPERT ADVANCED       accepted intent, specialist use
DERIVED_INSPECT           never editable; inspector only
EVALUATION_ONLY           configured outside Design (EvaluationPolicy)
OPTIMIZATION_ONLY         owned by Study / DesignSpace
METADATA                  never identity
NOT_RENDERED              no accepted target contract
LEGACY_ONLY               compatibility / migration only
```

## 12. The complete field exposure matrix (§12) — **69 declared fields, none omitted**

Machine form: `docs/product/exposure-registry.yaml` (62 leaf fields + 7 containers,
validated against the live dataclasses — see §116).

`RequirementV3`'s real shape was re-read for this gate: **`qos_class`,
`traffic_class`, `latency_ceiling_cycles`, `bandwidth_floor_gbps`, `binding`**
— **not** a generic `metric`/`op`/`threshold` triple. That corrects Gate 5 §17
(see §24).

| Field | Owner | Source | Guided | Expert | Default? | Preset? | Capability | Notes |
|---|---|---|---|---|---|---|---|---|
| `CompileRequestV3.workload` | WORKLOAD | UI | container | container | — | — | — | container |
| `CompileRequestV3.requirements` | REQUIREMENTS | UI | container | container | — | — | — | container |
| `CompileRequestV3.agents` | SYSTEM | UI | container | container | — | — | — | container |
| `CompileRequestV3.dependencies` | WORKLOAD | UI | container | container | — | yes | — | container |
| `CompileRequestV3.noc_config` | FABRIC | UI | container | container | — | — | — | container |
| `CompileRequestV3.address_map` | MEMORY | UI | container | container | — | yes | `MEM-001` NOT_AVAILABLE | container (§38) |
| `CompileRequestV3.physical` | PHYSICAL | UI | container | container | — | — | — | container |
| `CompileRequestV3.schema_version` | — | METADATA | — | — | pin | — | — | identity pin |
| `CompileRequestV3.compiler_semantics_version` | — | METADATA | — | — | pin | — | — | identity pin |
| `WorkloadV3.model_family` | WORKLOAD | UI | **G1** | **E1** | rec `dense_transformer` | yes | `WORK-001` | drives lowering |
| `WorkloadV3.model_name` | WORKLOAD | METADATA | G1 | E1 | none | yes | — | never identity |
| `WorkloadV3.tp` | PARALLELISM | UI | **G1** | **E1** | none | yes | `PAR-001` | |
| `WorkloadV3.pp` | PARALLELISM | UI | **G1** | **E1** | rec `1` | yes | `PAR-004` (stage lowering incomplete) | §27 |
| `WorkloadV3.ep` | PARALLELISM | UI | **G1** | **E1** | rec `1` | yes | `PAR-003` | §26 |
| `WorkloadV3.dp` | PARALLELISM | UI | **G1** | **E1** | rec `1` | yes | `PAR-002` | §26 |
| `WorkloadV3.serving_mode` | WORKLOAD | UI | G1 | E1 | rec `mixed` | yes | — | **must not imply a serving workflow** (§24) |
| `WorkloadV3.collectives` | COMMUNICATION | UI | **G2** | **E1** | materialized | yes | `COMM-002/003/004` | §28 |
| `WorkloadV3.source_ref` | WORKLOAD | METADATA | — | E2 | none | yes | — | digest/format/size |
| `RequirementV3.qos_class` | REQUIREMENTS | UI | G1 | E1 | none | yes | `REQ-001/002` | |
| `RequirementV3.traffic_class` | REQUIREMENTS | UI | **G2** | **E1** | materialized `None` (fabric-wide) | yes | `COMM-006` | |
| `RequirementV3.latency_ceiling_cycles` | REQUIREMENTS | UI | **G1** | **E1** | none | yes | `REQ-001` | the real cycle ceiling |
| `RequirementV3.bandwidth_floor_gbps` | REQUIREMENTS | **REMOVED from v4** | **NOT_RENDERED** | **NOT_RENDERED** | — | — | `REQ-003` DECL NO | **§24 — control must be removed** |
| `RequirementV3.binding` | REQUIREMENTS | UI | **G1** | **E1** | rec `false` (advisory) | yes | — | |
| `Agent.kind` | SYSTEM | UI | **G1** | **E1** | preset | yes | `SYS-001` | |
| `Agent.count` | SYSTEM | UI | **G1** | **E1** | preset | yes | `SYS-001` | |
| `Agent.data_width` | SYSTEM | UI | **G2** | **E1** | rec | yes | `SYS-001` | Domain A: R1 |
| `Agent.addr_width` | SYSTEM | UI | **G2** | **E1** | rec | yes | `MEM-001` | bounds address decode |
| `Agent.protocol` | SYSTEM | UI | **G2** | **E1** | rec | yes | `SYS-001` | |
| `Agent.clock_domain` | SYSTEM | UI | **G2** | **E1** | rec | yes | `SYS-003/004` (`PROJ NO`) | §20 |
| `Agent.power_domain` | SYSTEM | UI | **G2** | **E1** | rec | yes | `SYS-001` | §20 |
| `NocConfig.topology_family` | FABRIC | UI | **G1** | **E1** | rec `MESH` | yes | `FAB-001/002/003` | §35 |
| `NocConfig.radix` | FABRIC | UI | **G1** | **E1** | rec `8` | yes | `FAB-001` | **scientific name: Side length** (§33) |
| `NocConfig.concentration` | FABRIC | UI | **G1** | **E1** | rec `1` | yes | `FAB-002` (QUAL NO under mesh-DOR) | §36 |
| `NocConfig.link_width` | FABRIC | UI | **G1** | **E1** | rec `256` | yes | `FAB-006` | |
| `NocConfig.arbitration` | ROUTER RESOURCE | UI | **G2** | **E1** | semantic `null` | yes | `ROUTE-007` | §37 |
| `NocConfig.rcu_enabled` | — | **REMOVED from v4** | **NOT_RENDERED** | **NOT_RENDERED** | — | — | `ROUTE-011` FUTURE_CONTRACT | **§24 / Gate-5 correction** |
| `NocConfig.mcast_groups` | — | **REMOVED from v4** | **NOT_RENDERED** | **NOT_RENDERED** | — | — | `COMM-005` FUTURE_CONTRACT | §24 |
| `NocConfig.mcast_setup_cycles` | — | **REMOVED from v4** | **NOT_RENDERED** | **NOT_RENDERED** | — | — | `COMM-005` | §24 |
| `NocConfig.output_formats` | FABRIC | UI | **E2** | **E2** | semantic `SYSTEMVERILOG` | yes | — | collateral only |
| `NocConfig.obfuscation_level` | FABRIC | UI | **E2** | **E2** | semantic `0` | yes | — | collateral only |
| `AddressMap.ranges` | MEMORY | UI | **NOT_RENDERED** | **E2 (target)** | — | yes | `MEM-001` NOT_AVAILABLE | §38, §39 |
| `AddressRange.name` | MEMORY | METADATA | — | E2 | none | — | — | never identity |
| `AddressRange.base` | MEMORY | UI | NOT_RENDERED | E2 (target) | — | yes | `MEM-001` | half-open |
| `AddressRange.size` | MEMORY | UI | NOT_RENDERED | E2 (target) | — | yes | `MEM-001` | |
| `AddressRange.target_agent_idx` | MEMORY | UI | NOT_RENDERED | E2 (target) | — | yes | `MEM-001` | → stable `AgentInstanceId` (MEM-D1) |
| `PhysicalContext.default_clock_freq_mhz` | PHYSICAL | UI | **G2** | **E1** | rec | yes | — | **design clock** — not the network clock (§32) |
| `PhysicalContext.default_data_width` | PHYSICAL | UI | **G2** | **E1** | rec | yes | — | |
| `PhysicalContext.num_power_domains` | PHYSICAL | UI | **E2** | **E1** | rec `1` | yes | — | §32 |
| `PhysicalContext.process_node_nm` | PHYSICAL | **METADATA** | **E2** | **E2** | none | yes | — | no downstream effect |
| `DependencyGraph.dependencies` | WORKLOAD | UI | **G2** | **E1** | materialized | yes | — | §21 |
| `Dependency.source` | WORKLOAD | UI | G2 | E1 | — | yes | — | |
| `Dependency.target` | WORKLOAD | UI | G2 | E1 | — | yes | — | |
| `Dependency.kind` | WORKLOAD | UI | G2 | E1 | — | yes | — | |
| `CollectiveIntent.kind` | COMMUNICATION | UI | G2 | E1 | materialized | yes | `COMM-002/003/004` | |
| `CollectiveIntent.dimension` | COMMUNICATION | UI | G2 | E1 | materialized | yes | `PAR-001..004` | |
| `CollectiveIntent.payload_bytes` | COMMUNICATION | UI | G2 | E1 | materialized | yes | — | |
| `CollectiveIntent.traffic_class` | COMMUNICATION | UI | G2 | E1 | materialized | yes | `COMM-006` | |
| `CollectiveIntent.source_rank` | COMMUNICATION | UI | E2 | E1 | materialized | yes | — | |
| `WorkloadSourceRef.content_digest` | WORKLOAD | METADATA | — | E2 | — | yes | — | |
| `WorkloadSourceRef.format` | WORKLOAD | METADATA | — | E2 | — | yes | — | |
| `WorkloadSourceRef.size_bytes` | WORKLOAD | METADATA | — | E2 | — | yes | — | |
| `WorkloadSourceRef.artifact_identity` | WORKLOAD | METADATA | — | E2 | — | yes | — | |
| `CompileIntent.name` | — | METADATA | G1 | E1 | none | — | — | preset provenance |
| `CompileIntent.fabric_preset` | — | METADATA | G1 | E1 | none | — | — | preset provenance |
| `CompileIntent.fabric_overrides` | — | **LEGACY_ONLY** | NOT_RENDERED | **E2** | none | — | — | superseded (ledger W3) |
| `CompileIntent.candidate_policy` | — | METADATA | — | E2 | pin | — | — | |
| `CompileIntent.preset_design_hash` | — | METADATA | — | E2 | pin | — | — | preset fingerprint |

**Counts (from the registry, not by hand):** G1 = 18 · G2 = 18 · E2 = 7 ·
METADATA = 10 · NOT_RENDERED = 8 · LEGACY_ONLY = 1 · containers = 7 — **69 rows,
no field unclassified, no field editable at two authorities.**

## 13. User-controlled vs system-materialized vs canonical default (§13)

```text
USER SELECTED          the user chose the value
GUIDED MATERIALIZED    the product wrote an explicit value (from a preset or a
                       recommendation the user accepted)
CANONICAL DEFAULT      a default the CONTRACT itself defines (e.g.
                       NocConfig.output_formats = (SYSTEMVERILOG,),
                       NocConfig.obfuscation_level = 0)
```

**Proved from contract:** `output_formats` and `obfuscation_level` carry dataclass
defaults; `AddressRange.target_agent_idx` defaults to `0`; `RequirementV3.binding`
defaults to `False`. **No UI default is invented without a domain semantic
default or an explicit recommendation.**

## 14. Default law (§14)

| Class | Meaning | Example |
|---|---|---|
| **SEMANTIC DEFAULT** | part of the canonical contract | `output_formats = (SYSTEMVERILOG,)` |
| **AUTHORING RECOMMENDATION** | product convenience that materializes a value | `radix = 8`, `concentration = 1` |
| **NO DEFAULT** | the user must decide | `tp`, `latency_ceiling_cycles` |

**A recommended value is not a semantic default.**

## 15. Recommendations (§15)

Recommendations are labelled internally as **recommendations** and become
**explicit values when accepted**. They must **not silently change with software
version for an existing draft** (G29): the draft holds the materialized value, not
a pointer to a recommendation table.

## 16. Guided workflow objective (§16)

**Minimize the number of scientific decisions required before a coherent
compile** — not clicks. `tp` is **necessary** and stays Guided-primary even though
it is inconvenient to decide.

## 17. Expert workflow objective (§17)

Expose every accepted design-intent degree of freedom **without** derived
internals. The user must be able to answer: what assumption am I setting · what
changes if I change it · what will be derived · what capability limit applies.

## 18. SYSTEM exposure (§18)

Guided primary: agent kind + count. Guided advanced: `data_width`, `addr_width`,
`protocol`, `clock_domain`, `power_domain`. Expert: all accepted fields.

**Guided templates materialize a common physical inventory**; Expert exposes the
explicit inventory. Hierarchy is **Guided-advanced / Expert-primary** (§20).

## 19. SYSTEM presets (§19)

A Guided statement like *"64 compute tiles + 8 HBM controllers"* must expand
**deterministically and visibly** into `Agent` rows. **Generated
`AgentInstance` identities are not hidden** — they are inspectable in the Compile
Result (FLOW-B), and declaration order never changes science (X1).

## 20. Hierarchy exposure (§20)

Hierarchy is **Guided-advanced / Expert-primary**. It has a **present role**
(parent/context for context-bound artifacts and endpoint attachment), so it is
**not** hidden — but it is not required for a common compile. The product states
its present role rather than implying downstream effects it does not have.

## 21. WORKLOAD exposure (§21)

Guided prefers **supported workload templates / `ModelSpec`**; Expert exposes
operation-graph semantics (`collectives`, `dependencies`, `source_ref`). **Both
resolve to the same `WorkloadV3`.**

## 22. Template vs graph authoring (§22)

Template expansion **may not bypass** operation validation, collective semantics
or dependency laws (§72). A template is an **authoring shortcut over the same
contract**.

## 23. Static MoE handling (§23)

```text
WORK-002 static MoE: DECLARABLE YES · DERIVABLE NO (IMPLEMENTATION_GAP)
```

**Guided does not recommend the static MoE path.** Expert may declare the valid
semantics where accepted intent exists, with a staged capability warning. **Follow
the registry.**

## 24. Serving workloads are not Guided Workload fields (§24)

Request traces and schedulers belong **Serve** (FLOW-F). **`serving_mode` is
workload intent** (it selects a workload regime) and must **not** imply that a
serving workflow has been configured.

## 25. PARALLELISM exposure (§25)

TP/DP/EP/PP are **Guided primary** (explicit extents). **No hidden
participant/rank derivation.** Expert shows explicit extents **and** the derived
world size as a read-only preview.

## 26. Dimension relevance (§26)

If the workload has no EP semantics, Guided **hides EP** and **materializes
`ep = 1`** — a value the user can discover (§93). **An unset required field is
never hidden.**

## 27. PP limitation feedback (§27)

PP is a **real** intent (`PAR-004`) with an incomplete downstream stage. Guided
**exposes PP with a staged capability warning** — *not* Expert-only, because
disabling a real intent for a downstream gap is exactly what Gate 5 §19 forbids.

## 28. COMMUNICATION exposure (§28)

```text
Guided : single canonical communication class, MATERIALIZED and discoverable
Expert : class definitions + operation bindings
```

**Only if a canonical one-class recommendation exists** — it does: `COMM-006`
shows single-class is the executable state. **No invisible class IDs.**

## 29. Multi-class handling (§29)

Multi-class intent is **real** (`COMM-006` DECLARABLE YES) with downstream limits.
**Expert exposes it with a capability-stage explanation. Guided does not create
multi-class designs unless explicitly requested.**

## 30. REQUIREMENTS exposure (§30)

**Requirements are user-facing science, not Expert-only.** Guided exposes
`qos_class` · `latency_ceiling_cycles` · `binding` (+ `traffic_class` at G2).
Expert exposes the full accepted set. **Unsupported targets are not exposed**
(`REQ-003` bandwidth, `REQ-004` class-target, `REQ-005` memory, `REQ-006`
serving/operation/group).

## 31. Requirement language (§31)

Guided may label *"Network completion ≤ X cycles"*. **The label must map exactly
to the canonical object** — comparator, target and unit unchanged. **No semantic
paraphrase.**

## 32. PHYSICAL exposure (§32)

Guided advanced / Expert primary: `default_clock_freq_mhz` (the **design clock**),
`default_data_width`, `num_power_domains`. `process_node_nm` is **metadata** (no
downstream effect). **`network_clock_hz` is NOT Design Physical intent — it is
`EvaluationPolicy` (§68) and must never appear here.**

## 33. FABRIC exposure (§33)

Guided primary: `topology_family` · **Side length** · `concentration` ·
`link_width`. All four are needed for a coherent compile, so all four are primary.

**Expert uses the scientific name `side_length`; never "Radix."** The
implementation adapter may still write `NocConfig.radix` (Gate 3 §7).

## 34. Fabric presets (§34)

Guided may offer preset network sizes. They **expand to actual** `side_length`,
`concentration`, `link_width`. **No hidden "Small / Medium / Large" science** —
the expansion is inspectable.

## 35. Torus handling (§35) — **Guided exposes it, with the stage limit**

```text
Torus: DECLARABLE YES · topology DERIVABLE YES · routing DERIVABLE NO
       wiring INSPECT_ONLY
```

**Chosen: Guided exposes Torus with an explicit stage warning.**

**Why not "Guided recommendations only include fully evaluable paths":** that would
make Guided a **capability filter**, which contradicts §1 (the distinction is
disclosure depth, not capability truth) and §9 (Guided may simplify existing
capability, not hide it). The user reaches compile + topology inspection + a clear
statement that routed evaluation is unavailable — the Gate-5 §20
valid-but-not-executable state.

## 36. Concentration > 1 handling (§36)

**Guided does not block the field.** `concentration = 2` is a valid canonical
fabric (`FAB-002`); the native mesh-DOR envelope is not qualified for it. The
**Evaluate** workflow handles qualification (§69). Guided may communicate that
another compatible profile may be required — **without putting evaluation policy
into Design identity.**

## 37. Router arbitration exposure (§37)

**One field: `arbitration`** (`RouterResourceIntentV4.arbitration_policy`).
Guided advanced (G2) · Expert primary (E1). **Do not expose VC allocator and switch
allocator as two independent fields** — the canonical intent is **one arbitration
policy**.

## 38. MEMORY exposure (§38)

```text
MemoryIntent = AddressMap only          (Domain I §3)
MEM-001 capability: NOT_AVAILABLE, reason PRODUCT_NOT_WIRED   (Gate 5 correction)
```

**Resolved: target architecture includes an Expert-advanced AddressMap editor
(E2); current implementation exposes nothing (PF-D1).**

**The two are kept separate:** the target field is **classified** (E2, presets may
materialize) but the **current product renders no control**, because the surface is
not wired. Gate 5's `NOT_AVAILABLE` state governs today's behaviour; the exposure
class governs the target.

## 39. AddressMap complexity (§39)

**Expert advanced.** Guided presets may materialize address maps internally —
**and the resulting map must be inspectable** (Compile Result → Address decode).
**No hidden ownership.**

## 40. Placement remains absent (§40)

**Neither disclosure level gets placement controls, pinning, affinity or
anti-affinity.** Mapping remains derived. **Non-negotiable until a real
`PlacementIntent` contract exists** (`MAP-002`/`MAP-003` DECL NO).

## 41. Derived inspection within authoring (§41)

Guided may show read-only previews: world size · router count · endpoint capacity ·
required endpoint count. Expert may show more. **Previews are derived views and
never become alternate editable authorities.**

## 42. Preview freshness (§42)

A derived preview from an incomplete draft is labelled **PREVIEW**, never
"compiled artifact". **If canonical derivation requires compile, the frontend does
not simulate it approximately.**

## 43. Capability-aware field exposure (§43)

```text
RENDER             real accepted intent, appropriate for the depth
RENDER_WITH_LIMIT  real accepted intent, downstream limitation exists
DO_NOT_RENDER      no accepted target intent
```

**Aligned with Gate 5:** Torus → `RENDER_WITH_LIMIT`; RCU / `mcast_*` /
multiplane / manual placement / VC count → `DO_NOT_RENDER`; concentration > 1 →
`RENDER_WITH_LIMIT`.

## 44. Capability warning timing (§44)

**Show capability information only when the selected value materially changes
reachable stages.** Torus → *routed execution unavailable*. Concentration 2 →
*native profile not qualified; another projection may exist*. **No generic warning
wall.**

## 45. Guided safe path (§45) — an AUTHORING RECOMMENDATION

```text
model_family        dense_transformer
tp / pp / ep / dp   chosen by the user (no recommendation)
agents              preset physical inventory (e.g. 64 compute + 1 HBM)
topology_family     MESH
side_length         8          (NocConfig.radix = 8)
concentration       1
link_width          256
arbitration         null (semantic default)
single communication class (materialized)
requirements        advisory latency ceiling (user)
```

**This is an AUTHORING RECOMMENDATION, not a semantic default.**

## 46. Safe-path envelope (§46)

It corresponds to the named envelope **`CAP-ENV-BOOKSIM-MESH-DOR-XY-V1`**
(`CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`), whose required conditions are:

```text
COND-TOPOLOGY-MESH · COND-ROUTING-DOR-XY · COND-SINGLE-COMM-CLASS ·
COND-IDENTITY-VC-TRANSITIONS · COND-SINGLE-CLOCK-FABRIC ·
COND-DENSE-STATIC-WORKLOAD · COND-CONFIG-AUDIT-CLOSED
```

**Every required condition is satisfied by the safe path.** The configuration is
not merely plausible — it maps to a real, tested envelope (§90).

## 47. Guided ≠ native BookSim (§47)

**Guided Design does not hard-code native backend restrictions into the scientific
schema.** Users may leave the safe envelope intentionally; the UI then
communicates the downstream consequence.

## 48. Guided progressive disclosure (§48)

Advanced real fields appear when the user **expands** the Expert disclosure,
**selects a capability requiring them**, or **imports an Expert-created design**.
**No hidden value remains scientifically mysterious** (§93).

## 49. Expert completeness (§49)

Every accepted editable field appears in the Expert disclosure (§12). Fields
absent from Expert carry an explicit reason: **evaluation-only** (`network_clock_hz`,
profile) · **optimization-only** (search method/budget/seed, candidate-owned
buffers) · **metadata** · **derived** · **not wired** (`AddressMap` surface) ·
**removed from v4** (`rcu_enabled`, `mcast_*`, `bandwidth_floor_gbps`).

## 50. Disclosure switch state machine (§50) — no hard modes, so no lossy switch

```text
GUIDED DISCLOSURE ──expand──► EXPERT DISCLOSURE      (always possible)
EXPERT DISCLOSURE ──collapse─► GUIDED DISCLOSURE
     ├── design fully representable at Guided depth → collapse normally
     └── design NOT representable                    → collapse to a READ-ONLY
                                                        GUIDED SUMMARY with
                                                        "expand for full control"
```

**No conversion is ever lossy** because there is **one draft**; collapsing changes
only what is *shown*, never what is *stored*.

## 51. Disclosure-switch identity law (§51)

```text
changing disclosure depth        → NO intent identity change
changing authoring-only metadata → NO design scientific identity change
```

**Contract tests:** G1, G2, G6 (§126).

## 52. Import behavior (§52)

```text
open a design:
  fully representable at Guided depth → open at Guided depth
  otherwise                          → open at Expert depth (or read-only Guided
                                       summary) — NEVER silently downgraded
```

**Presentation metadata never affects science.**

## 53. Legacy import (§53)

Legacy fields — **RCU, `routing_function`, VC count** — **must not appear as
Expert controls merely because import parsed them.** Migration diagnostics are
shown **separately**. **Accepted v4 science remains authoritative.**

## 54. Unsupported imported values (§54)

A legacy value with no target contract enters a **migration/refusal** state. **It
is not placed into an "Expert extras" section.**

## 55. Validation architecture (§55)

Both depths use the **same validators**. Presentation may show a **simplified
message** versus **technical detail**. **The verdict and the owning field are
identical.**

## 56. Validation layers (§56)

Preserved from Gate 5: local syntax/type · preflight cross-domain joins · compile
authority · report/evaluation authority. **No cross-domain scientific logic is
implemented independently in React.**

## 57. Guided error explanation (§57)

```text
problem   128 physical agents need endpoints; current fabric provides 64 seats
why       the join between System inventory and Fabric seats is infeasible
remedies  increase side length or concentration · reduce physical inventory
```

**No auto-fix.**

## 58. Expert diagnostics (§58)

Additionally: reason codes · artifact/domain owners · exact contract references.
**Same underlying error.**

## 59. Auto-fix policy (§59)

```text
ALLOWED silently            format normalization, alias normalization
REQUIRES explicit confirm   changing topology, reducing parallelism, changing
                            concentration, changing a Requirement threshold
```

**Automatically fixing scientific intent is dangerous.**

## 60. Canonicalization vs auto-fix (§60)

```text
" iSLIP " → iSLIP      normalization of equivalent syntax — NOT an auto-fix
Torus    → Mesh        scientific mutation — NEVER silent
```

## 61. Guided explanation requirements (§61)

Every Guided control must be able to answer: **what is this · why must I decide it
· what does changing it affect.** *(No microcopy written here.)*

## 62. Expert explanation requirements (§62)

Additionally: **canonical field · unit · identity effect · downstream
invalidation · capability implications.**

## 63. Units (§63)

Guided may format readably (*"256 bits"*); **the canonical value stays exact**.
Expert may show the exact canonical unit. **No unit ambiguity; no lossy
conversion.**

## 64. IDs in authoring (§64)

**No raw internal hashes/IDs as primary controls.** Users select meaningful
entities; stable IDs operate underneath. Expert may inspect IDs in
provenance/debug context.

## 65. Adding agents (§65)

Guided creates **groups/templates**; Expert creates exact groups/instances per the
System contract. **Generated group order never determines science** — stable IDs
and canonical ordering apply (X1).

## 66. Workload graph editing (§66)

**Target: Expert-primary. Current: no product wiring for a full graph editor.**
Marked as a **target-vs-current gap**; the product does not promise a graph editor
merely because `WorkloadV3` can represent one.

## 67. Requirements presets (§67)

Guided shorthand *"limit network completion"* must materialize the exact
**target · metric · comparator · threshold · binding**. **No invisible requirement
semantics.**

## 68. Evaluate exposure (§68)

```text
GUIDED  recommend the most directly qualified profile, based on the registry
EXPERT  explicit profile · network clock · execution options
```

**Both create the same `EvaluationPolicy` contract.** **No silent fallback.**

## 69. Backend recommendations (§69)

Guided recommends the **most directly qualified** profile from the registry. The
user **confirms** when the choice would change the scientific producer (Gate 5
§32). **No silent switch.**

## 70. Qualification visibility (§70)

```text
GUIDED  plain-language qualification outcome
EXPERT  profile ID · failed predicates · evidence scope
```

**Same result object.**

## 71. Serving exposure (§71)

Guided may use **supported request/scheduler presets**; Expert may expose the full
serving configuration. **Serving scientific boundaries are identical**, and there
is **no static/serving conflation.**

## 72. Optimization exposure (§72) — **keeps a stronger distinction, consistently**

```text
GUIDED  goal → variation scope → MATERIALIZED typed DesignSpace → review → run
EXPERT  explicitly construct the typed DesignSpace
```

**Both produce the same `StudyDefinition`.** Optimization's stronger distinction
is legitimate because the **DesignSpace itself is a typed contract** — the
"guided" path materializes a `DesignSpace`, it does not merely hide fields. That
is the same law as §6/§8 (materialize, never hide), applied to a different object.

**The current implementation must not remain a special-case philosophy:** it must
be described as *materialize-then-review*, matching §73.

## 73. Optimization transparency (§73)

**Before running Guided optimization, the exact generated dimensions, objectives,
constraints and evaluation policy are shown.** **No hidden search space.** This is
mandatory.

## 74. SearchExecutionPolicy exposure (§74)

Guided **recommends** method/budget/seed; Expert **edits** them. They remain
**execution policy, not StudyDefinition science** (Gate 3 §9). The distinction is
visible conceptually.

## 75. Candidate-owned resources (§75)

Router buffers are **candidate-owned**, not Design Intent. **They are not surfaced
in Expert Design** merely because optimization can vary them. Expert **Optimize**
may expose them as typed dimensions — **when such a dimension exists**
(`ROUTE-012`: none exists today).

## 76. Capability registry integration (§76)

**Every field/value exposure decision references capability row(s).** No second
hand-written list of unsupported features. Guided/Expert consume capability truth.

## 77. Registry version mismatch (§77)

If authoring rules target an older `capability_semantics_version`, **fail safely**
— do not render stale "supported" controls. Consistent with Gate 5 P26.

## 78. `DesignView` v2 (§78)

Backend-owned projection of: **draft intent · field ownership · derived previews ·
capability status · validation state.** **The frontend does not reconstruct
canonical semantics.**

## 79. Projection authority (§79)

For each authoring field the frontend receives: **value · editable status ·
exposure class · validation · capability implications** from the backend/product
schema. **Avoid hard-coded duplicated enums.**

## 80. Frontend vs backend responsibility (§80) — **locked**

```text
FRONTEND owns  presentation · interaction · local ephemeral form state ·
               disclosure state
BACKEND owns   canonical values · canonicalization · scientific validation ·
               capability truth · derived previews · identity
```

## 81. Draft form model (§81)

The frontend edits a **draft projection** and sends **field-level patches**; the
backend holds the canonical `CompileRequestV3`. **Full snapshots are not the
editing primitive**, because a snapshot would let a stale client overwrite fields
it never saw.

## 82. Patch semantics (§82)

Patches target **canonical editable paths** only. **No arbitrary JSON pointers to
derived internals. Unknown path → fail closed.**

## 83. Dirty tracking (§83)

```text
editing a canonical value        → DIRTY
expanding the Expert disclosure  → NOT dirty
changing disclosure depth        → NOT dirty
changing a preset that materializes different values → DIRTY (science changed)
```

## 84. Advanced-section law (§84)

"Advanced" means **real accepted but less-common intent.** It is **not** a dumping
ground for legacy fields, derived fields, future capabilities or backend
internals.

**Current-UI audit:** the current Design page has no advanced grouping, and it
places **`rcu_enabled`** (a removed-from-v4 field) beside real intent — a direct
violation of this law (§85).

## 85. Current-control audit (§85, §86) — every control classified

| Current control | Verdict |
|---|---|
| `workload.model_family` | **GUIDED** |
| `workload.model_name` | **GUIDED** (metadata) |
| `workload.serving_mode` | **GUIDED** — but must not imply a serving workflow |
| `workload.tp/pp/ep/dp` | **GUIDED** |
| `requirements[].traffic_class` | **ADVANCED** |
| `requirements[].qos_class` | **GUIDED** |
| `requirements[].latency_ceiling_cycles` | **GUIDED** |
| **`requirements[].bandwidth_floor_gbps`** | **REMOVE** — `bandwidth` is *"REMOVE from v4"* (`INTENT-REQUIREMENTS.md:143`); `REQ-003` DECL NO |
| `requirements[].binding` | **GUIDED** |
| `agents[].count` | **GUIDED** |
| `noc_config.topology_family` | **GUIDED** + `RENDER_WITH_LIMIT` (torus) |
| **`noc_config.radix` labelled "Radix"** | **GUIDED** + **RENAME → "Side length"** |
| `noc_config.concentration` | **GUIDED** + `RENDER_WITH_LIMIT` |
| `noc_config.link_width` | **GUIDED** |
| `noc_config.arbitration` | **ADVANCED** |
| **`noc_config.rcu_enabled` + `.rcu-refusal` banner** | **REMOVE** — `ROUTE-011` FUTURE_CONTRACT (Gate-5 correction) |
| network clock | **absent — correct** (Evaluation-only) |
| power-domain controls | **absent** — target `PhysicalContext.num_power_domains` is **ADVANCED** |
| placement controls | **absent — correct** (no contract) |
| memory controls | **absent** — target is Expert-advanced, current `NOT_AVAILABLE` |
| VC count / turn restrictions / routing override | **absent — correct** |

## 86. Current template audit (§87) — shipped presets

**CORRECTED by implementation audit (§87 enforcement).** The table below
asserted Guided eligibility; §87's requirement 4 — *reach its advertised
capability envelope* — was never mechanically checked, and two rows were
false. The audit found the `mesh4` family failing
`COND-SINGLE-COMM-CLASS`: it ships a **multi-class** fabric (dependency
classes A and B, two VCs), and every static envelope requires a single
class, with `COMM-006` recording multi-class execution as unavailable. The
parenthetical *"(if single class)"* was the tell — the condition was known
and the verdict ignored it.

The family also declared `model_family=mixture_of_experts` while the
envelope's `COND-DENSE-STATIC-WORKLOAD` requires `dense_transformer`; that
metadata was wrong (a 1-NPU synthetic-trace fabric carrier is not a MoE
workload) and is corrected at the canonical preset source.

| Template | Materializes | Valid under target contracts? | Envelope | Verdict |
|---|---|---|---|---|
| `mesh4` | 4-tile mesh, **multi-class** (A/B) | **valid** | none — no static envelope admits multi-class (`COMM-006`) | **Expert-only** (declarable, compilable, inspectable; not evaluation-safe) |
| `mesh4_hbm` | 4-tile mesh + HBM + address map, multi-class | **valid** | none — same | **Expert-only** (map materialized, inspectable read-only) |
| `mesh4_wide128` | 4-tile mesh, 128-bit links, multi-class | **valid** | none — same | **Expert-only** |
| `dense-1b-16tiles` | dense, TP4 allreduce, 16 tiles | **valid** | `CAP-ENV-BOOKSIM-MESH-DOR-XY-V1` | **Guided-eligible — PROVEN** (every required condition holds) |
| `dense-4b-32tiles-conc4` | dense, **DP allgather**, concentrated mesh (4 tiles/router) | **needs preset certification (§87)** | mesh-DOR **not qualified** at concentration 4 | **Expert-only until certified** |
| `moe-8x7b-64tiles` | MoE serving, TP allreduce + EP alltoall | **serving path** | serving envelope | **Expert-only** (static MoE `DERIVABLE NO`) |

**`dense-1b-16tiles` is the one proven Guided safe path.** Every required
condition of its advertised envelope holds from real artifacts. The Guided
safe path is therefore real rather than asserted.

**The known `conc4` + DP allgather defect** is exactly the case §87 names. It
**must not survive as a Guided preset** without passing preset certification
(§88) — including the DP-allgather dimension check.

## 87. Preset certification (§88)

A shipped Guided preset must:

```text
1. canonicalize
2. pass intrinsic validation
3. pass preflight joins
4. reach its advertised capability envelope
5. declare which envelope it advertises
```

**A preset is not trusted because it is bundled.** Recorded as **GX-D5**.

**ENFORCED.** Requirements 1–3 and 5 are checked by
tests/test_preset_certification.py; requirement 4 is checked by
evaluating every required condition of the advertised envelope against the
canonical compilation (`application/preset_certification.py`), gated by
`scripts/check_preset_certification.py`. The certification states are
`GUIDED_SAFE` · `EXPERT_ONLY` · `INVALID` · `UNCERTIFIED`, and the gate
fails closed: a claim its own envelope refutes is `INVALID`, and a claim
resting on a condition only an execution can decide is `UNCERTIFIED`,
never assumed.

## 88. Guided preset tiers (§89)

```text
COMPILE-SAFE · EVALUATE-SAFE · SERVING-SAFE · OPTIMIZATION-BASELINE-SAFE
```

Used **only where useful**; **not everything is labelled "recommended."**

## 89. Safe-path fixtures (§90)

The Guided recommended configuration has **regression fixtures** asserting it
reaches `CAP-ENV-BOOKSIM-MESH-DOR-XY-V1`. If the product says *"Start here,"* that
path stays tested. **GX-D5.**

## 90. Field dependency disclosure (§91)

Dependencies are declared, not implied: `topology_family` determines which
topologies are derivable; the communication-class count determines whether
bindings are relevant; `concentration` changes qualification reachability. **No
dead inputs.**

## 91. Conditional fields (§92)

A conditionally hidden field **retains** its value. **Canonical schema always
retains it** — the draft is the canonical serialization, so a hidden field is
still a stored field. **Clearing requires an explicit action.**

## 92. Hidden-value problem (§93) — critical

```text
For every hidden accepted field, either
  (a) the materialized canonical value is SUMMARIZED and discoverable, or
  (b) the design is NOT representable at Guided depth (read-only summary).
```

**No ghost configuration.**

## 93. Guided summary (§94)

Before compile, Guided must be able to summarize **all** scientific values,
**including hidden advanced ones**. *(This leads into Gate 7 Review — not designed
here.)*

## 94. Expert summary (§95)

**The same canonical science**, possibly with more technical detail. **No separate
summary object.**

## 95. Mode-specific copy is not science (§96)

```text
Guided  "Grid size"
Expert  "Mesh side length"
```

Equivalent and not misleading. **Never "Radix."**

## 96. Terminology law (§97)

| Concept | Guided | Expert |
|---|---|---|
| logical participant | "participant" | "logical participant" |
| physical compute agent | "compute tile" | "agent (COMPUTE_TILE)" |
| attachment point | "port" | "endpoint seat / endpoint" |
| network switch | "router" | "router" |
| virtual channel | *(hidden)* | "virtual channel (VC)" |
| backend profile | "evaluation profile" | "certified profile (profile ID)" |
| side length | "grid size" | "mesh side length" |
| arbitration | "switch arbitration" | "router arbitration policy" |

## 97. Simplification boundary (§98)

Guided wording may omit implementation detail. It **may not collapse
scientifically distinct objects** when the distinction affects a user action.
*"Device"* must not ambiguously mean participant / agent / endpoint.

## 98. Destructive-switch case (§99) — and why progressive disclosure removes it

Expert design with **multiple communication classes**: collapsing to Guided depth
**must not collapse the classes**. Guided shows a **read-only high-level summary**
with *"expand for full control."*

**Because there is one draft, the classes are never at risk** — collapsing changes
only what is shown (§50).

## 99. Expert-only real intent (§100)

Accepted fields **not editable at Guided depth**: `collectives` (G2 = Guided
advanced, so *reachable* but not primary) · `source_ref` · `output_formats` ·
`obfuscation_level` · `num_power_domains` · `process_node_nm` ·
`AddressMap.ranges` (target) · `fabric_overrides` · `candidate_policy`.

**Guided users can still open and read designs containing them** (§92).

## 100. Guided-authored design at Expert depth (§101)

**Every Guided design is fully editable at Expert depth. No preset lock-in. No
opaque generated object.**

## 101. Expert-authored design at Guided depth (§102)

```text
FULLY REPRESENTABLE          all values at Guided depth
REPRESENTABLE WITH ADVANCED  values exist that Guided shows only when expanded
READ-ONLY AT GUIDED DEPTH    values exist that Guided does not show at all
```

**Deterministic test:** the design is `FULLY REPRESENTABLE` iff every non-default
value it carries has an exposure class of `G1` or `G2`; `REPRESENTABLE WITH
ADVANCED` iff every such value is `G1`, `G2` or `E1`; otherwise `READ-ONLY AT
GUIDED DEPTH`.

## 102. User choice preservation (§103)

If a user explicitly changes a recommended value, it is **not reset** when another
unrelated field changes — **unless a formal dependency requires it.**

## 103. Smart defaults (§104)

Materialized **only when the field is unset**. Once the user changes a value
explicitly, it is **never overwritten automatically.**

## 104. Reset to recommendation (§105)

**An explicit action.** **No silent reset.**

## 105. Capability changes after edit (§106)

If an edit moves the design outside the safe path, Guided **updates the capability
consequence and does not undo the edit.** Example: concentration 1 → 2 shows the
qualification consequence.

## 106. Compile readiness (§107) — one model for both depths

```text
INCOMPLETE          a mandatory field has no value
INVALID             a field violates its own contract
PREFLIGHT_BLOCKED   a cross-domain join is infeasible
READY_TO_COMPILE    all of the above clear
COMPILED / STALE    handled by the revision model (Gate 5 §7)
```

**Guided is never "ready" with hidden invalid fields.**

## 107. Incomplete fields (§108)

**The backend schema remains authority** for what is mandatory. **No
frontend-only mandatory list.** A field is mandatory when the canonical contract
requires it (e.g. `qos_class`, `Agent.kind`, `Agent.count`).

## 108. Validation presentation levels (§109)

```text
GUIDED  actionable
EXPERT  actionable + reason code / technical evidence
```

**Same underlying verdict.**

## 109. Capability presentation levels (§110)

```text
GUIDED  "Can compile, but current routed evaluation is unavailable."
EXPERT  stage table + limiting reason + envelope
```

**No contradictory wording.**

## 110. Provenance presentation levels (§111)

Guided keeps provenance secondary; Expert surfaces semantics versions, profile
IDs and artifact identities more directly. **Provenance remains accessible from
both depths** through FLOW-J.

## 111. Accessibility of advanced science (§112)

**Guided must not block users from understanding what was generated.** Every
auto-materialized scientific choice is discoverable. **No "magic" behind a
disclosure depth.**

## 112. Disclosure recommendation (§113)

```text
new project                    → Guided depth
opened simple design           → Guided depth
opened complex design          → Expert depth
optimization-promoted design   → depth per the candidate's content (§101 test)
```

**Based on representability and complexity — never persona guessing.**

## 113. Persistence (§114)

Disclosure depth may persist as a **user/product preference**. **It does not
belong to scientific object identity.** If absent, the product chooses by the
deterministic rule in §112.

## 114. Guided as default? (§115)

**Yes — Guided depth is the default**, because it minimizes the number of
scientific decisions before a coherent compile (§16). **Expert is not "necessary
for current capabilities"**: every accepted field is reachable from Guided depth
through the expansion, so the default does not restrict capability.

## 115. Checker invariants (§125)

A future `scripts/check_exposure.py` must enforce:

```text
1. every rendered field is declared intent
2. no DERIVED field is editable at any depth
3. no FUTURE_CONTRACT / LEGACY_ONLY field is rendered
4. every Guided-hidden active value is summarizable
5. every Expert-omitted declared field has a reason
6. presets expand to known fields only
7. every field has exactly one exposure class
8. no field is editable at two authorities
```

## 116. Exposure registry decision (§123, §124)

**Chosen: a separate `docs/product/exposure-registry.yaml`.**

**Why not `intent-ontology.yaml`:** the ontology answers *"what may the Design page
render?"* and is validated against `DesignEditor.tsx` field paths. Exposure
answers *"at which disclosure depth, and with what default/preset policy?"* — a
product concern with a different checker. Overloading the ontology would force
exposure rows through the ten-answer node schema, which they cannot satisfy, and
would duplicate capability truth.

**Ownership:** the exposure registry is owned by the product authoring model,
versioned alongside `capability_semantics_version`, and it **references capability
rows by ID** rather than restating capability truth.

## 117. Current Studio mapping (§120)

| Surface | Action |
|---|---|
| `components/DesignEditor.tsx` | **REBUILD** — add disclosure depths; remove RCU; remove bandwidth; rename Radix → Side length; add advanced grouping |
| `components/VerifyView.tsx` | **REBUILD** (Gate 5) |
| `components/EvaluateView.tsx` | **REBUILD** — EvaluationPolicy + recommendation/confirm |
| `components/FabricView.tsx` / `FabricInspector.tsx` | **KEEP** (moved under Compile Result per Gate 5) |
| `components/OptimizeView.tsx` / `OptimizationAnalysis.tsx` | **KEEP** — authority discipline correct |
| `pages/optimize.tsx` | **REBUILD** — materialize-then-review framing (§72/§73) |
| `pages/serving.tsx` | **KEEP** + label rebuild |
| `pages/index.tsx` | **REBUILD** (Gate 5) |
| `pages/design.tsx` | **REBUILD** |
| templates (`FABRIC_PRESETS`, workload catalog) | **AUDIT** (§86) — certify before Guided eligibility |
| legacy CLI / `POST /optimize` | **REMOVE** (Gate 5) |

## 118. API / view implications (§121)

```text
DesignView v2            + collectives, dependencies, address_map, physical,
                           product layer            (Gate 5 D5 / PF-D4)
                         + per-field exposure class
                         + per-field editable status
                         + per-field validation state
                         + per-field capability implications (row references)
                         + derived previews (labelled PREVIEW)
field patch endpoint     canonical editable paths only; unknown path fails closed
canonicalization         backend-owned; no optimizer- or frontend-specific aliasing
preset expansion         returns the materialized fields + preset provenance
capability endpoint      already exists (GET /api/v1/capabilities) — add version
```

**No gratuitous APIs.**

## 119. Avoid UI-only scientific rules (§122)

Any rule like *"field X is only valid when Y"* belongs to the **backend/domain
contract**. The frontend may mirror it for immediate feedback. **The backend
remains authority.**

## 120. Mode-switch and authoring tests (§126) — G1–G20

| # | Case | Verdict |
|---|---|---|
| G1 | Guided mesh design → Expert | **no scientific change** |
| G2 | Expert equivalent mesh design → Guided | **lossless** |
| G3 | Expert multi-class design → Guided | **no collapse**; read-only summary |
| G4 | Guided preset → Expert | all materialized values visible |
| G5 | preset implementation changes later | existing revision **unchanged** (`preset_design_hash` pin) |
| G6 | disclosure depth switch only | **design identity unchanged** |
| G7 | expand advanced | **not dirty** |
| G8 | canonical alias change (`" iSLIP "` → `iSLIP`) | normalized; **scientific identity unchanged** |
| G9 | legacy RCU import | **never appears as a control** |
| G10 | legacy placement concept import | **no target control** |
| G11 | Torus chosen at Expert depth | intent preserved; capability limit visible |
| G12 | Torus chosen at Guided depth | same science, same limit |
| G13 | concentration 2 | **not auto-reset to 1** |
| G14 | Guided safe path, native mesh | reaches the advertised envelope |
| G15 | Guided hides the communication class | materialized single-class value **discoverable** |
| G16 | Expert changes to multi-class | Guided representability state changes (§101) |
| G17 | Guided user changes arbitration advanced value | canonical `RouterResourceIntent` changes |
| G18 | network clock edited in Design | **impossible** — Evaluation-only |
| G19 | VC count edited at Expert depth | **impossible** — derived |
| G20 | AddressMap target editing while not wired | **no false control** |

## 121. Additional adversarial cases (§127) — G21–G40

| # | Case | Verdict |
|---|---|---|
| G21 | a hidden value becomes invalid after another edit | readiness blocks compile and **exposes the cause** |
| G22 | user sets a custom value then changes preset | product **asks / explicitly overwrites** per preset-action semantics |
| G23 | user re-selects the same preset | **no scientific change** |
| G24 | display label change | no science change |
| G25 | disclosure state missing in an old project | **deterministic** selection (§112) |
| G26 | unknown capability-registry version | **fail-safe rendering** |
| G27 | backend adds an accepted field unknown to the frontend | **fail closed / schema mismatch**, never silently omitted science |
| G28 | frontend knows a field the backend removed | **cannot submit the stale field** |
| G29 | recommendation changes in a new software version | existing draft/revision **retains the materialized value** |
| G30 | new-project recommendation changes | new project **may** receive the new recommendation |
| G31 | Expert design uses all accepted fields | summary remains complete |
| G32 | same design created at Guided and at Expert depth | **same canonical identity** |
| G33 | same design created by preset vs manual input | **same canonical identity** |
| G34 | preset name differs, expansion identical | **same science** |
| G35 | unsupported/future field injected through the API | backend **refuses**; no control revealed |
| G36 | candidate-owned buffer attempted in Design | **not available there** (§75) |
| G37 | Expert Evaluate profile differs from the Guided recommendation | **same `EvaluationPolicy` science** when values are equal |
| G38 | Guided recommends a profile, qualification fails after a design change | recommendation **updates**; **no silent backend substitution** |
| G39 | Serving Experiment opened in Design | **wrong workflow**; no serving fields in Design Intent |
| G40 | an advanced field is metadata-only | changing it follows the **metadata identity law** (no identity change) |

## 122. Preset adversarial cases (§128) — G41–G45

| # | Case | Verdict |
|---|---|---|
| G41 | preset contains DP allgather over DP with `dp = 1` | **preset validation fails**; cannot ship as a safe preset (§86) |
| G42 | preset contains unsupported RCU | **invalid for v4** |
| G43 | preset uses torus but advertises evaluable | **invalid advertised envelope** |
| G44 | preset uses concentration 2 but claims native BookSim qualification | **invalid** |
| G45 | preset expands to hidden multi-class intent Guided cannot explain | **invalid Guided preset** |

## 123. Research questions U1–U30

| # | Answer |
|---|---|
| U1 | **one editor with progressive disclosure** (§1) |
| U2 | Guided primary = G1, 14 fields (§12) |
| U3 | Guided advanced = G2, 13 fields (§12) |
| U4 | Expert-only = E1 (22) + E2 (16) (§12) |
| U5 | evaluation-only = `network_clock_hz`, backend profile (§32, §68) |
| U6 | optimization-only = search method/budget/seed, candidate-owned buffers (§74, §75) |
| U7 | metadata-only = `process_node_nm`, `WorkloadSourceRef.*`, `AddressRange.name`, `CompileIntent.name/fabric_preset/candidate_policy/preset_design_hash`, schema pins (§12) |
| U8 | **remove**: `rcu_enabled` + refusal banner, `bandwidth_floor_gbps` (§85) |
| U9 | **move**: none out of Design; network clock stays Evaluation (§32) |
| U10 | canonical semantic defaults: `output_formats`, `obfuscation_level`, `binding`, `target_agent_idx` (§13) |
| U11 | recommendations: `radix=8`, `concentration=1`, `link_width=256`, `MESH`, `pp=1`, `ep=1`, `dp=1`, `serving_mode=mixed`, safe-path envelope (§45) |
| U12 | `mesh4`, `mesh4_hbm`, `mesh4_wide128` + 3 workload templates (§86) |
| U13 | 4 valid as-is; `conc4` Expert-only until certified; `moe-8x7b-64tiles` Expert-only (§86) |
| U14 | `CAP-ENV-BOOKSIM-MESH-DOR-XY-V1` with all 7 conditions (§46) |
| U15 | **no** — Guided materializes single-class; multi-class is Expert (§29) |
| U16 | **no currently** — target is Expert-advanced; `MEM-001` `NOT_AVAILABLE` (§38) |
| U17 | **yes, at Guided-advanced depth** (§20) |
| U18 | **yes, with a staged limit** (§35) |
| U19 | read-only Guided summary + expand for full control (§50, §101) |
| U20 | separate `docs/product/exposure-registry.yaml` (§116) |
| U21 | per-field value, exposure class, editable status, validation, capability implications, previews (§118) |
| U22 | a backend canonicalization path; no frontend or optimizer aliasing (§118) |
| U23 | Guided = materialize-then-review; Expert = explicit; **same `StudyDefinition`** (§72) |
| U24 | a product preference, never scientific identity (§113) |
| U25 | exposure class + capability row references + `capability_semantics_version` (§118) |
| U26 | `fabric_preset` + `preset_design_hash` (already present) (§8) |
| U27 | `dense-4b-32tiles-conc4` (DP allgather, concentration 4) and `moe-8x7b-64tiles` (static MoE) (§86) |
| U28 | INCOMPLETE · INVALID · PREFLIGHT_BLOCKED · READY_TO_COMPILE (§106) |
| U29 | the safe path itself encodes a mesh-DOR assumption — labelled a **recommendation**, never a schema default (§47) |
| U30 | the safe path (§45) plus mandatory user decisions (`tp`, requirements) (§16) |

**All 30 answered.**

## 124. Gate-6 implementation debt (§130)

```text
GX-D1  DesignView v2 exposure metadata (per-field class, editable status,
       validation state, capability row references)
GX-D2  backend canonical field normalization before any frontend/candidate identity
GX-D3  preset expansion + provenance contract, with preset certification gate
GX-D4  Guided-depth representability classifier (§101 deterministic test)
GX-D5  safe-path + preset regression fixtures against CAP-ENV-BOOKSIM-MESH-DOR-XY-V1
GX-D6  remove invalid current controls (rcu_enabled + banner; bandwidth_floor_gbps)
GX-D7  machine-readable exposure registry + scripts/check_exposure.py
GX-D8  "Side length" rename; one arbitration field (no VC/switch allocator split)
```

**Referenced, not duplicated:** PF-D1…D16 · CAP-D1…D5 · XDOM-D1…D8 · OPT-D2…D8 ·
MEM-D1…D5 · FAB-D1/D4/D6 · VC-D1 · COMM-D1 · ROUTER-D2.

## 125. Coherence check against §132

| # | Criterion | Status |
|---|---|---|
| 1 | Guided and Expert use identical canonical science | **MET** (§1, §3) |
| 2 | mode itself never changes identity | **MET** (§6, §51) |
| 3 | Guided has no hidden scientific state | **MET** (§7, §92) |
| 4 | Expert does not expose derived internals | **MET** (§10, §12) |
| 5 | every declared field has an exposure class | **MET** (§12, 62 fields) |
| 6 | every hidden field has a discoverability law | **MET** (§92) |
| 7 | semantic defaults and recommendations are distinct | **MET** (§13, §14) |
| 8 | presets materialize ordinary canonical values | **MET** (§7, §8) |
| 9 | existing designs cannot be reinterpreted by changed presets | **MET** (§8 — `preset_design_hash`) |
| 10 | Guided safe path corresponds to a real tested envelope | **MET** (§46) |
| 11 | leaving the safe path causes no silent reset | **MET** (§105) |
| 12 | Torus behaviour follows capability truth | **MET** (§35) |
| 13 | concentration > 1 remains valid intent | **MET** (§36) |
| 14 | RCU / hardware multicast / multiplane / manual placement / VC count remain absent | **MET** (§9, §85) |
| 15 | network clock remains Evaluation-only | **MET** (§32, G18) |
| 16 | candidate-owned buffers remain Optimization-only | **MET** (§75) |
| 17 | switching is lossless or explicitly refused/read-only | **MET** (§50) |
| 18 | Guided-generated designs are fully inspectable at Expert depth | **MET** (§100) |
| 19 | Expert-only science is never silently collapsed | **MET** (§99) |
| 20 | validation authority remains backend/canonical | **MET** (§55, §56, §119) |
| 21 | capability registry remains one capability authority | **MET** (§76) |
| 22 | current invalid controls are classified for removal | **MET** (§85) |
| 23 | shipped presets are audited | **MET** (§86) |
| 24 | the chosen architecture is singular | **MET** (§1) |
| 25 | Gate 7 Review has not been designed | **MET** |
| 26 | wireframes not begun | **MET** |
| 27 | HTML not begun | **MET** |

## 126. Domain verdict

The gate's own premise was the first thing worth challenging. **A hard
Guided/Expert toggle is the weaker architecture**, because it creates a lossy
switch that must then be *proved* not to change science — and Gate 6's own §4/§5
demand exactly that proof. **One canonical editor with progressive disclosure has
no such state to prove.** There is one draft, one schema, one normalization, one
identity; collapsing or expanding changes only what is *shown*.

The audit found **two controls that render fields removed from v4**, both the same
defect class as the Gate-5 RCU correction. `noc_config.rcu_enabled` is still
rendered with a refusal banner even though `ROUTE-011` is `FUTURE_CONTRACT` and
`INTENT-ROUTER-RESOURCES.md:320` says *"**No `rcu=true` checkbox.**"* And
`requirements[].bandwidth_floor_gbps` is still rendered even though
`INTENT-REQUIREMENTS.md:143` reads **"Bandwidth decision — REMOVE from v4"** and
`REQ-003` is `DECLARABLE: NO`. Both are **REMOVE** (GX-D6). Re-reading
`RequirementV3` for this gate also corrected Gate 5 §17: its real fields are
`qos_class`, `traffic_class`, `latency_ceiling_cycles`, `bandwidth_floor_gbps` and
`binding` — **not** a generic `metric`/`op`/`threshold` triple.

The load-bearing decisions are small and specific. **Preset expansion is already
correct in the repository** — `CompileIntent.preset_design_hash` pins the preset
fingerprint, so a changed preset cannot reinterpret an old design (§8). **Guided
exposes Torus with a staged limit rather than filtering it out**, because making
Guided a capability filter would contradict §1 and §9. **Concentration > 1 is
never blocked in Design** — the qualification consequence belongs to Evaluate.
**`network_clock_hz` stays Evaluation-only.** And **`arbitration` is one field**,
never a VC-allocator/switch-allocator pair.

Optimization keeps a **stronger** distinction (§72), and that is consistent rather
than special-cased: its Guided path **materializes a typed `DesignSpace`** and then
shows it, which is the same materialize-never-hide law applied to a different
object. Both paths produce one `StudyDefinition`.

The field matrix is the deliverable that makes the rest checkable: **62 declared
fields, every one classified**, with no field editable at two authorities. The
remaining work is named and narrow: **GX-D1…GX-D8**.

**GATE 6 — GUIDED / EXPERT: PLANNED — COHERENT**

Gate 7 not begun. No Review screen. No wireframes. No HTML.
