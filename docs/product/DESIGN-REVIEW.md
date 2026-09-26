# DESIGN-REVIEW — Gate 7 (canonical design review)

Authority: `PRODUCT-FLOWS.md`, `GUIDED-EXPERT.md`, `CAPABILITY-MATRIX.md`,
`CROSS-DOMAIN-LAWS.md`, the eleven `INTENT-*.md` documents, `intent-ontology.yaml`,
`exposure-registry.yaml`, `capability-registry.yaml`. Current Studio audited
**only after** the contracts.
Status: **PLANNED — COHERENT.** See §91.

---

## 1. What Review is (§1)

```text
Review = a read-only, canonical projection of the exact current Intent Draft,
         immediately before compile.
```

**It is not:** a second editor · a compile result · a certificate · a capability
dashboard · an evaluation setup · a backend configuration page · a marketing
summary.

**It answers one question:** *"What exactly am I asking SROTA to compile?"*

**It is the boundary between mutable authoring intent and immutable compiled
science.**

## 2. Review object decision (§2, §74) — **`DesignViewV2`, no new object**

```text
DesignViewV2 { …, presentation: "review" }
```

**Decision: Review is a projection mode of `DesignViewV2`. No `DesignReviewView`
is created.**

**Why:** Review needs exactly what `DesignViewV2` must already carry — canonical
draft values, field ownership/exposure class, readiness, validation findings,
capability consequences and derived previews (Gate 5 D5, Gate 6 GX-D1). A
separate object would **duplicate the schema definition**, creating two
authorities for the same projection. **One object, one authority.**

## 3. Snapshot identity (§3) — **it already exists**

Audit result: the draft **already carries a content hash**.

```text
DraftView.design_hash        stored by put_draft as _view_hash(request.design_hash())
DraftView.dirty              active is None or draft.design_hash != active.design_hash
```

`product/service.py:609-636`. `design_hash()` is a **pure function of the
canonical request**, so **the draft's hash predicts the revision's hash**. The
snapshot identifier therefore needs **no new identity**:

```text
REVIEWED DRAFT   identified by  (project_id, draft.design_hash)
COMPILE PRODUCES identified by  design_hash  — the same value, now bound to a revision
```

**§5 preserved:** `intent_id` (the `CompileIntent` preset record) ≠ `design_hash`.
Review operates over the **draft's** content identity, and the future revision
hash is never displayed as if it already existed.

## 4. TOCTOU protection (§4) — **the gap, and the exact fix**

**Audit result: there is no TOCTOU protection today.**

```text
POST /projects/{id}/compile     — takes NO body, no precondition
PUT  /projects/{id}/draft       — full-document write, no version/ETag
```

So the current flow permits exactly the failure Gate 7 exists to prevent:

```text
review X → another tab (or the same user) changes the draft → compile Y
```

**Chosen law — an explicit precondition, not a new locking system:**

```text
CompileRequest { expected_draft_design_hash: str }
  current draft hash == expected  → compile
  current draft hash != expected  → REFUSE (STALE_REVIEW), never compile unseen content
```

**Why this and not ETags/version numbers:** the content hash **already exists**
and is **already computed**. An `ETag` would be a second, weaker identity for the
same content; a monotonic version number would be metadata that can disagree with
the content. **The content hash is the authoritative snapshot identity.**

**§52 concurrent editing:** two tabs editing the same draft → the second write
wins the *draft*, but a compile carrying the first tab's
`expected_draft_design_hash` **refuses**. Conflict behaviour is therefore
**fail-closed**, and no collaboration UI is designed here.

## 5. Review completeness invariant (§7, §87)

```text
canonical active draft fields
  − metadata-only fields
  = scientific fields represented by Review
```

**Mechanically testable**, and the reason Review is *"where hidden science becomes
impossible."*

**Enforcement:** for every field in `exposure-registry.yaml` with a class other
than `METADATA`, Review must either **represent it** or prove it **non-active** in
this draft. No active canonical field may be omitted because the current
**disclosure state** hides it (§6, §60).

## 6. No hidden values (§6, §60) — Gate 7's strongest law

```text
AUTHORING may hide advanced values (progressive disclosure).
REVIEW may not.
```

**Review is canonical completeness, not another disclosure mode.** The Guided/
Expert disclosure depth is **not an input** to Review's content.

## 7. Review source of values (§8, §9)

Values come from the **backend canonical draft projection**. The frontend does
**not** reconstruct them from form defaults, presets, local component state or
stale caches. **Canonicalization happens before Review.**

```text
authoring input   " iSLIP "
Review shows      iSLIP
implementation    NocConfig.radix
Review shows      Mesh side length
```

**No legacy aliases in primary Review language.**

## 8. Preset transparency (§10, §20)

```text
FORBIDDEN  "Preset: mesh4"
REQUIRED   every materialized field, plus optional metadata
           "Created from mesh4 preset"
```

The preset name may appear as **provenance metadata**; it **never substitutes**
for the expanded content.

## 9. Section grouping (§11, §12)

Derived from **accepted editable science and product comprehension** — not
mechanically mirrored from ontology domains.

```text
1  System              agents, counts, hierarchy, interface, clock/power domains
2  Memory Addressing   AddressMap (read-only until PF-D1)
3  Workload            model identity, collectives, dependencies, source ref
4  Parallelism         TP/DP/EP/PP + derived world size
5  Communication       classes and operation bindings
6  Fabric              topology family, side length, concentration, link width
7  Router Behavior     arbitration (one policy)
8  Physical Context    design clock, data width, power domains
9  Requirements        the RequirementSet
```

**Minimal coherent grouping — nine sections.** No section exists for one field
merely for symmetry.

**Documented deviations from ontology ownership:**

| Review section | Ontology domain(s) |
|---|---|
| Router Behavior | ROUTER_RESOURCE — **split out of Fabric for comprehension** |
| Memory Addressing | MEMORY — **nested under System in authoring (Gate 6 §12), but its own Review section** because an active `AddressMap` is real science |
| Physical Context | PHYSICAL — own section, small but distinct |

## 10. System Review (§13)

Summarizes: physical inventory · group/agent quantities · hierarchy **where
active** · clock-domain membership · power-domain membership · address/interface
properties.

**Both levels are available** (§61): a compact semantic summary, and access to the
exact detail. **Every generated `AgentInstance` row is not dumped** — the summary
is semantic, the detail is reachable.

## 11. Workload Review (§14)

Summarizes: workload/model identity · operation semantics · important `ModelSpec`
values · network-producing operations · collectives · dependencies.

**Does not claim** compute timing · memory timing · serving request semantics —
none of which is `WorkloadV3` intent.

## 12. Template-expanded workloads (§15)

Review makes template expansion **scientifically visible**: the user can verify
**which operations and collectives were actually declared** — without reading
internal hashes.

## 13. Static MoE Review (§16)

```text
declared workload semantics        SHOWN
capability consequence             SHOWN SEPARATELY (WORK-002 DERIVABLE NO)
```

**Valid intent is never rejected because a later stage is unavailable.**

## 14. Parallelism Review (§17, §18)

Shows TP · DP · EP · PP, plus **derived** world size and group-count summaries
**labelled as derived**.

**Derived rank IDs are never presented as user declarations.**

Where PP or sharding semantics carry capability limits, Review shows the
**capability consequence** — never implying the declared shape is invalid.

## 15. Communication Review (§19, §64)

```text
single-class   the one materialized class and its operation binding, concisely
multi-class    EVERY class definition and binding
```

**A materialized single class is still disclosed** — *"Communication — Default
class: <semantic name>"*. It is **not hidden because the user did not type it.**

**Review never hides classes merely because authoring used progressive
disclosure.**

## 16. Requirements Review (§20) — **the field set is corrected**

Re-reading `RequirementV3` for Gate 6 established its real fields:

```text
qos_class · traffic_class · latency_ceiling_cycles · bandwidth_floor_gbps · binding
```

**Review shows only accepted v4 requirement science:**

| Field | Review |
|---|---|
| `qos_class` | **shown** |
| `traffic_class` | **shown** (advanced) |
| `latency_ceiling_cycles` | **shown** |
| `binding` | **shown** (binding / advisory) |
| **`bandwidth_floor_gbps`** | **NOT shown** — *"Bandwidth decision — REMOVE from v4"* (`INTENT-REQUIREMENTS.md:143`); `REQ-003` `DECLARABLE: NO` |

**Note for Gate 5 consistency:** Gate 5 §17 described requirements as
`metric`/`op`/`threshold`. That is the **optimization constraint** shape and the
**report entry** shape, **not** the declared `RequirementV3` shape. Corrected
here; the Review contract follows the declared object.

## 17. Requirement executability (§21)

Review **may** indicate whether a metric can be evaluated under known capability
envelopes, or that the evaluation path may be unavailable. **This is capability
information, not a verdict.**

**Review never shows `SATISFIED` / `VIOLATED`** — no measurement exists yet
(§47, R37).

## 18. Fabric and Router Review (§22, §26)

**Shown:** topology family · side length · concentration · link width · **one**
canonical arbitration policy.

**Not shown as editable/reviewed intent:** VC count · routing function · turn
restrictions · RCU · hardware multicast · multiplane.

**Arbitration is never split** into VC allocator and switch allocator — those are
**derived projection fields from one canonical intent**.

## 19. Fabric derived preview (§23) — exact precompile facts only

```text
PRE-COMPILE DERIVED SUMMARY   (exact, backend-computed)
  router count · endpoint capacity · required endpoints · unused seats
```

**These are not called compiled artifacts.** Anything requiring derivation is
**not** shown here (§47).

## 20. Torus Review (§24)

**Review allows compile.** The capability consequence is:

```text
topology derivation and inspection available
routed execution currently unavailable
```

**A staged limitation, not a validation error.** Torus is **not** a blocker.

## 21. Concentration > 1 Review (§25)

**Review remains valid.** If a native profile may later fail qualification, that
consequence **may** be shown.

**Review never implies "change to 1 to continue"** unless the user has already
chosen an evaluation profile that requires it — and Review is design-focused.

## 22. Memory Review (§27, §72) — **the contradiction resolved**

```text
Gate 5: AddressMap is canonical but the product surface is not wired (PF-D1).
Gate 6: no false edit control.
Gate 7: an ACTIVE canonical value cannot remain invisible.
```

**Resolution: Review shows a read-only Memory Addressing section whenever the
draft carries a non-empty `AddressMap`.** Presets materialize address maps today
(`mesh4_hbm`), so this science **is active** and must be reviewable.

**Why read-only and not an editor:** authoring remains `NOT_RENDERED` (Gate 6),
so Review exposes **no control** — it exposes the **value**. This satisfies both
constraints without inventing an authoring surface.

**Recorded as REV-D6** — `DesignView` v1 does not carry `address_map` (Gate 5 D5),
so this requires the v2 widening.

## 23. AddressMap Review content (§28)

Shows exact **address ranges** and **memory agent targets** using **meaningful
stable agent names/labels**, with IDs available in technical detail.

**Positional indices are never exposed** — `target_agent_idx` is the legacy
positional form pending **MEM-D1**; Review presents the resolved stable identity.

## 24. Physical Review (§29)

Shows accepted Design Physical intent only: `default_clock_freq_mhz` (the **design
clock**) · `default_data_width` · `num_power_domains`.

**Does not show `network_clock_hz`** — that is `EvaluationPolicy` (Gate 6 §32).
Review **does not imply** the design clock is network-timing authority.

## 25. Metadata (§30)

May appear: project name · revision label · preset provenance.

**Clearly separated from scientific intent.** Metadata **never masquerades** as
compiler input when it does not enter identity.

## 26. Compile readiness (§31) — one backend-owned result, not a Boolean

```text
READY
INCOMPLETE
INVALID
PREFLIGHT_BLOCKED
CAPABILITY_LIMITED_BUT_COMPILABLE
```

**Audit finding:** the current `PreflightView.ready` is a **single boolean** *and*
is **evaluation-scoped** — it carries `backend`, `backend_profile`,
`network_clock_hz` and `expected_evidence_tier` (`api/types.ts:253-265`).

**Two defects, both recorded:**
1. one boolean cannot express the five states;
2. **design preflight is conflated with evaluation setup** — a backend field on a
   design-readiness object.

**Target:** design readiness is its own result; `PreflightView`'s
backend/clock/tier fields **move to Evaluation** (REV-D5).

## 27. Validation classes (§32)

```text
FIELD/SYNTAX VALIDATION      local
CROSS-DOMAIN PREFLIGHT       canonical joins, provable before compile
CAPABILITY LIMITATION        downstream stage unavailable
COMPILE-TIME UNKNOWN         only the compiler can decide
```

**These are not equivalent**, and Review must not present them as one class.

## 28. Blocking vs non-blocking (§33)

```text
BLOCKING      malformed intent · missing required value ·
              cross-domain infeasibility provable before compile
NON-BLOCKING  downstream evaluation limitation for an otherwise valid design
```

**Torus routing unavailability must not prevent topology compilation.**

## 29. Finding taxonomy (§34, §78)

```text
BLOCKING_ERROR · DOWNSTREAM_LIMITATION · INFORMATION · LEGACY_MIGRATION_NOTICE
```

**A red banner is not semantic authority.** Every finding carries:

```text
class · owner domain · code · message · affected field/object ·
blocking (explicit) · remediation owners
```

**The frontend does not infer blocking from message text.**

## 30. Capability consequences (§35, §36)

Review summarizes **only the consequences materially caused by the current
choices**:

| Draft choice | Consequence shown |
|---|---|
| Torus | inspect-only after topology derivation |
| multi-class | accepted intent with downstream implementation/qualification limits |
| multiple clock domains | declared System intent; fabric crossing unsupported |
| static MoE | declared; current static lowering limitation |
| concentration > 1 | mesh-DOR envelope not qualified |

**Not the 73-row matrix.** These come from the **capability registry**, never from
hand-coded Review conditionals.

## 31. Registry mismatch (§37, R31, R32)

If Review's `capability_semantics_version` is stale or incompatible:

```text
do not generate potentially false claims
fail safely / require regeneration
```

**If a capability row changes after Review was generated, and the claim is part of
the Review snapshot, Review must regenerate before compile** (R32). If only the
consequence changed and the draft did not, the design science is unchanged —
**only the consequence text is refreshed** (R33).

## 32. Review does not choose a backend (§38)

**No BookSim profile · no network clock · no ASTRA mode.**

```text
Compile Design first. Evaluate later.
```

## 33. Backend-independent capability language (§39)

```text
SAY   "Routed execution unavailable in the current canonical pipeline."
NOT   "BookSim doesn't support this"
```

**The correct layer matters** — the blocker is route derivation, not the backend.

## 34. Review and changes from baseline (§40, §41, §42)

Review shows **what scientific values changed from its parent** compiled revision
or draft.

**Diff authority: canonicalized intent.** It does **not** diff raw JSON
formatting, field order, aliases or display labels.

```text
"islip" → " iSLIP "     NO scientific diff
Mesh    → Torus         scientific diff
```

Review knows the draft's parent/base revision **if one exists** — not all drafts
have parents.

## 35. New and promoted designs (§43, §44)

```text
brand-new design          no diff section required; complete science still shown
optimization-promoted     diff shows CHANGES FROM BASELINE;
                          trial number is NOT primary science;
                          candidate/study provenance appears as metadata
```

## 36. Invalidation summary (§45, §46)

Review may explain what existing results will **not** carry over after this
compile. **If included, it is derived from the Gate-3 invalidation graph — no
frontend heuristics.**

## 37. Derived previews are not certificates (§47)

```text
MAY show precompile      endpoint capacity PASS · world size · router count
MUST NOT show            DEADLOCK_FREE · ROUTE_LEGAL · QUALIFIED
```

**No certificate is pre-empted.**

## 38. No predicted backend metrics (§48)

**Review shows no estimated latency, bandwidth or expected performance.** No
accepted prediction model exists with `PREDICTED` evidence semantics, so **Design
Review stays away from fake performance promises.**

## 39. Review action set (§49, §50)

```text
Back to edit
Compile Design
```

**No `Approve`, `Certify` or `Accept`** — user confirmation does not
scientifically certify anything.

**No checkbox theatre.** Clicking **Compile** is sufficient intent to compile the
reviewed snapshot.

## 40. Compile action contract (§51)

```text
CompileRequest { expected_draft_design_hash }
```

The server compares it to the stored draft's `design_hash`:

```text
match     → compile
mismatch  → refuse STALE_REVIEW
```

**This is the minimal API change** — the identity already exists (§3); only the
**precondition** is added.

## 41. Review regeneration and freshness (§53, §54)

```text
change a canonical field        → Review STALE
expand/collapse a section       → Review remains valid
change Guided/Expert disclosure → Review remains valid
metadata-only change            → freshness follows the metadata identity law (R24)
```

```text
Review freshness:  CURRENT | STALE
```

**A stale Review is never shown as compile-ready.**

## 42. Compile handoff (§55, §56, §57)

```text
success   → an immutable Compiled Revision with a new revision identity.
            Review remains a historical snapshot/projection.
            Review is NOT mutated into the compile result.
refusal   → Review snapshot PRESERVED with the typed refusal attached.
            User returns to the owning editable field/domain.
            Review context is not erased.
```

**Locked distinction:**

```text
REVIEW          what the user declared + exact preflight facts
COMPILE RESULT  what the compiler derived and verified
```

**Only in Compile Result:** Mapping · Attachments · exact topology artifact ·
routes · VC assignment · certificate. **No cross-contamination.**

## 43. Review vs Capability page (§58)

Review shows **only draft-relevant consequences**. The Capability workflow shows
the full registry. **Review does not reproduce the 73-row matrix.**

## 44. Review vs Provenance (§59)

Review may show preset source · parent revision · draft identity. **Deep
compiler/backend evidence does not yet exist**, so **no empty provenance sections
are created** for future artifacts.

## 45. Two detail levels (§61)

Review offers a **summary representation** and **exact details**. Both must be
available. **Gate 8 decides the interaction** (accordion, table, etc.).

## 46. Terminology (§62, §63)

```text
NEVER  "Radix"        when it means side length
NEVER  "Node"         when participant / agent / router / endpoint must be distinguished
NEVER  "Supported" · "Verified" · "Optimal" · "Full route" as unqualified claims
```

**Primary Review uses meaningful labels; stable IDs appear in technical detail;
raw hashes are not primary UX.**

## 47. Defaults and recommendations (§65)

```text
explicit user choice
authoring recommendation accepted/materialized
semantic default
```

**Per-field provenance is not always displayed**, but **Review must not imply a
recommendation was compiler-derived when it is actual intent.** All three are
**declared intent** once materialized — the distinction is provenance, not
authority.

## 48. Legacy fields (§66) and metadata (§67)

```text
legacy imported state not migrated → MIGRATION DIAGNOSTICS, not Review
if migration unresolved            → compile readiness BLOCKED
metadata-only fields               → summarized but semantically distinct
changing metadata alone            → no recompile required
```

## 49. Binding vs advisory (§68) and Pareto (§69)

Review explains whether a requirement is **binding** or **advisory** — **without
implying it constrains compilation**. Requirements are evaluated **after
measurement**.

**Review does not mention Pareto.** Optimization semantics are not introduced into
Design Review.

## 50. Envelope preview (§70, §71) — exact prerequisite language

```text
COND-TOPOLOGY-MESH · COND-SINGLE-COMM-CLASS · COND-SINGLE-CLOCK-FABRIC ·
COND-DENSE-STATIC-WORKLOAD · COND-CONFIG-AUDIT-CLOSED
```

are **design-side** and provable precompile.

```text
COND-ROUTING-DOR-XY · COND-IDENTITY-VC-TRANSITIONS
```

depend on **derived** Route/VC state and therefore **cannot be known precompile**.

**Law:**

```text
Review MAY say  "Compatible with the design-side prerequisites of
                 CAP-ENV-BOOKSIM-MESH-DOR-XY-V1"
Review MUST NOT  claim QUALIFIED
```

**No `POTENTIALLY_ELIGIBLE` vocabulary is added** — the exact prerequisite
statement is sufficient, and adding a near-qualification term invites
overclaiming. **Qualification happens later.**

## 51. Backend ownership (§75, §76)

```text
BACKEND owns  canonical field values · readiness · validation ·
              capability consequences · scientific diff · snapshot identity ·
              grouping semantics
FRONTEND owns rendering and interaction
```

**Grouping lives in the backend/product schema**, not hard-coded in React —
otherwise a section could silently omit an active field.

### 51.1 Smallest target schema (§76)

```text
DesignViewV2 {
    contract_version: 2
    presentation: "edit" | "review"
    draft_identity: { project_id, draft_design_hash }
    parent_revision_ref?
    readiness: READY | INCOMPLETE | INVALID | PREFLIGHT_BLOCKED |
               CAPABILITY_LIMITED_BUT_COMPILABLE
    sections: [ { id, title, entries: [ { field, value, semantic_class,
                                         exposure_class, capability_ref? } ] } ]
    derived_summaries: [ { id, value, label: "PRE-COMPILE DERIVED SUMMARY" } ]
    validation_findings: [ { class, owner_domain, code, message,
                             affected, blocking, remediation_owners } ]
    capability_consequences: [ { capability_id, consequence, registry_version } ]
    scientific_diff?: [ { field, before, after } ]
    capability_semantics_version: "cap-v1"
}
```

## 52. Section entry semantics (§77)

Every entry is one of:

```text
DECLARED · DERIVED_PREVIEW · METADATA · CAPABILITY_CONSEQUENCE
```

**No naked values without a semantic class.**

## 53. Review identity (§79, §80)

**Decision: Review needs no separate stable hash.**

The snapshot is **fully bound** by `(project_id, draft_design_hash,
capability_semantics_version)`. A `content_id` over those would be **derivable
from what is already bound** and would add a second identity for the same
snapshot.

**Review is a product projection**: its interpretation version belongs to the
**product view schema**, **not** to scientific identity. Changing the Review
projection does **not** change any compiled science.

## 54. Current Studio audit (§81)

**Audit result: there is no Review surface.** `pages/design.tsx` exports
`Design`, `Compile`, `Verify`, `Simulate`; the `WorkflowBar` runs
design → compile → verify → simulate. **The `Compile` page shows the RESULT**
(identity, `resolved_fabric_hash`, `certificate_id`, derived routing/VC count) —
**not a pre-compile review of the draft.**

| Surface | Finding | Action |
|---|---|---|
| **no Review surface** | the pre-compile boundary does not exist | **BUILD** (REV-D1) |
| `pages/design.tsx :: Compile` | correctly shows the **result** with derived fields labelled *"compiler-owned"* / *"derived"* | **KEEP** — but it must not be mistaken for Review |
| `pages/design.tsx :: Verify` | certificate view | **KEEP** (Gate 5 REBUILD pending) |
| `pages/design.tsx :: PreflightPanel` | `PreflightView` mixes backend/profile/network-clock into design readiness | **REBUILD** — split design readiness from evaluation preflight (REV-D5) |
| `pages/design.tsx :: Design` | authoring; shows `active.design_hash` in the Compile result, not pre-compile | **KEEP** |
| `components/ArtifactChain.tsx` / `ArtifactStrip.tsx` | provenance over a compiled revision | **KEEP** |
| `DraftView` | already carries `design_hash` + `dirty` — the snapshot identity exists | **KEEP** |
| `POST /compile` | no precondition | **REBUILD** — add `expected_draft_design_hash` (REV-D2) |
| `PUT /draft` | full-document write, no version | **KEEP** — the hash precondition is sufficient |
| `DesignView` v1 | omits `address_map`, `physical`, `collectives`, `dependencies` | **REBUILD** → v2 (PF-D4 / REV-D1) |

## 55. Terminology audit (§82)

| Term found in current frontend | Verdict |
|---|---|
| `Radix` (`DesignEditor.tsx:387`) | **WRONG** — must be **Side length** (PF-D12) |
| `intervention.supported ? 'SUPPORTED' : 'NOT SUPPORTED'` (`index.tsx:747`, `:455`) | **WRONG** — single boolean over 8 stages (CAP-D2 / CC-1) |
| *"execute supported communication"* (`index.tsx:327`) | **WRONG** — undefined capability claim (CC-2) |
| `RCU (in-network reduction)` + `.rcu-refusal` (`DesignEditor.tsx:423-438`) | **WRONG** — removed from v4; control must go (GX-D6) |
| `bandwidth_floor_gbps` control | **WRONG** — *"REMOVE from v4"* (GX-D6) |
| `"· compiler-owned"` / `"· derived"` labels on routing / VC count (`design.tsx`) | **CORRECT** — keep |
| `Hash` component on `design_hash`, `resolved_fabric_hash`, `certificate_id` | **CORRECT** — hashes in technical detail |
| `Full route` / `Verified` / `Optimal` / `Multicast` | **not found** — no violation |

**Copy is not rewritten here.**

## 56. R1–R30 verdicts (§83)

| # | Case | Verdict |
|---|---|---|
| R1 | Guided safe-path design | Review contains **every materialized field** (§5) |
| R2 | same design authored at Expert depth | **scientifically identical Review** |
| R3 | preset-created design | preset name **does not substitute** for fields (§8) |
| R4 | preset implementation changes after a saved draft | Review of the old draft **unchanged** (`preset_design_hash` pin) |
| R5 | advanced section collapsed | Review **still shows advanced active fields** (§6) |
| R6 | Torus selected | **compile-ready**; downstream routed-execution limitation shown (§20) |
| R7 | concentration = 2 | **valid**; no false native qualification claim (§21) |
| R8 | multi-class communication | **every class and binding shown** (§15) |
| R9 | static MoE | declared semantics + downstream implementation limitation (§13) |
| R10 | PP > 1 | exact declared shape + current stage limitation (§14) |
| R11 | multiple clock domains | System intent valid; fabric-crossing limitation shown (§30) |
| R12 | RCU legacy field | **not in normal Review**; migration diagnostic handles it (§48) |
| R13 | bandwidth requirement legacy field | **not accepted Review science** (§16) |
| R14 | manual placement injected via stale frontend | backend **rejects**; not a Review field |
| R15 | VC count injected | **rejected/ignored** per schema; never reviewed as intent |
| R16 | `network_clock_hz` | **not Design Review** (§24) |
| R17 | AddressMap supplied by preset, not editable | **appears read-only in Review** (§22) |
| R18 | AddressMap targets an HBM controller | **stable instance identity shown meaningfully** (§23) |
| R19 | invalid AddressMap overlap | **blocking preflight finding** |
| R20 | endpoint capacity shortfall | **blocking cross-domain finding** |
| R21 | requirement threshold only | **not a compile validity issue** (§49) |
| R22 | draft changes after Review opens | **compile rejects the stale snapshot** (§4) |
| R23 | presentation expansion after Review | **does not stale Review** (§41) |
| R24 | metadata rename after Review | freshness follows the metadata identity law — **no stale** |
| R25 | two tabs modify the draft | **optimistic conflict prevents unseen compile** (§4) |
| R26 | compile refuses something not caught preflight | **Review retained with the refusal** (§42) |
| R27 | successful compile | new revision identity; **Review remains a historical snapshot** (§42) |
| R28 | optimization candidate promotion | **diff shows candidate changes from baseline** (§35) |
| R29 | same arbitration via an alias | **canonicalized; no scientific diff** (§34) |
| R30 | raw field order changed | **scientific content unchanged** (§34) |

## 57. R31–R45 verdicts (§84)

| # | Case | Verdict |
|---|---|---|
| R31 | unknown capability-registry version | **Review refuses claims** (§31) |
| R32 | capability row changes after Review generated | **regenerate before compile** if the claim is in the snapshot (§31) |
| R33 | new backend capability becomes available | design science unchanged; **consequence text refreshes** under the new registry version |
| R34 | active field omitted from the Review schema | **checker failure** (§5, §86) |
| R35 | derived preview accidentally editable | **architectural violation** |
| R36 | frontend shows a locally estimated router count differing from backend preflight | **backend wins; frontend estimator forbidden** (§37) |
| R37 | user sees a requirement as `PASS` before evaluation | **forbidden** (§17) |
| R38 | Review claims "qualified BookSim" | **forbidden before qualification** (§50) |
| R39 | Review claims "deadlock free" | **forbidden before certificate** (§37) |
| R40 | Review claims "full route verified" | **forbidden** (§37) |
| R41 | same design values, different preset provenance | **same scientific Review values** |
| R42 | expert-only value active | **Review shows it even under default authoring disclosure** (§6) |
| R43 | hidden active value has no human-readable representation | **Gate-7 blocker** — must be resolved before the field ships |
| R44 | review section ordering changes | **no scientific identity effect** |
| R45 | compile API receives a stale `expected_draft_design_hash` | **refuse** (§40) |

## 58. Research questions V1–V30 (§85)

| # | Answer |
|---|---|
| V1 | **No Review surface exists today** (§54) |
| V2 | **No** — `DesignView` v1 omits `address_map`, `physical`, `collectives`, `dependencies` |
| V3 | **No dedicated object needed** — `DesignViewV2` with `presentation: "review"` (§2) |
| V4 | `(project_id, draft.design_hash)` — **already exists** (`DraftView`) |
| V5 | `PUT /projects/{id}/draft` sends the full request document |
| V6 | **No** — `POST /compile` takes no body; this is the gap (§4) |
| V7 | `parse_request_doc` → `canonical_request_doc` → `design_hash()` |
| V8 | `GET /revisions/{id}/preflight` — **evaluation-scoped** (`gates[]`, `ready`) |
| V9 | derivation of Mapping/Topology/Attachment/Routes/VC/certificate |
| V10 | router count · endpoint capacity · required endpoints · unused seats · world size (§19) |
| V11 | `address_map`, `physical`, `collectives`, `dependencies`, and the product layer |
| V12 | expanded into the stored `request` document; the draft carries the materialized values |
| V13 | `CompileIntent.fabric_preset` + `preset_design_hash` (§8) |
| V14 | **Not surfaced at all** — no control, no view (§22) |
| V15 | `default_clock_freq_mhz`, `default_data_width`, `num_power_domains`, `process_node_nm` |
| V16 | design-side envelope prerequisites; multi-class / multi-clock / MoE / torus limits (§30, §50) |
| V17 | **Yes** — a stale `capability_semantics_version` makes Review refuse claims (§31) |
| V18 | the draft's `design_hash` compared with the active revision's (§3) |
| V19 | **Yes** — `PUT /draft` is last-write-wins with no precondition (§4) |
| V20 | `PreflightView.gates[]` + `reason`; compile refusals carry typed status |
| V21 | `ProjectView` pointers + `DraftView`; **no unified summary object** |
| V22 | **Yes** — `canonical_request_doc` gives a canonical serialization to diff (§34) |
| V23 | `active_revision_id` / `latest_attempt_revision_id` on the project |
| V24 | via the optimization study; promotion is **not wired** (`OPT-008`) |
| V25 | project name · revision label · preset provenance · `process_node_nm` · `WorkloadSourceRef.*` · `AddressRange.name` · schema pins (§25) |
| V26 | **No** — bound by `(project_id, draft_design_hash, capability_semantics_version)` (§53) |
| V27 | **Backend/product schema**, not React (§51) |
| V28 | `expected_draft_design_hash` on compile; `DesignView` v2; design readiness split from evaluation preflight |
| V29 | `Radix` · `SUPPORTED` boolean · *"execute supported communication"* · RCU control · bandwidth control (§55) |
| V30 | the completeness invariant (§5) + the snapshot precondition (§4) |

**All 30 answered.**

## 59. Review checker (§86)

A future `scripts/check_review_coverage.py` must prove:

```text
1. every exposure-registry field with a class other than METADATA has Review coverage
2. every active field type has a schema representation
3. no NOT_RENDERED / FUTURE_CONTRACT / LEGACY_ONLY field appears in Review
4. no EVALUATION_ONLY field appears as Design intent
5. all capability consequences reference a capability-registry id
6. all blocking findings carry a structured code and an owner domain
7. every Review entry carries a semantic class
8. the completeness invariant holds: active − metadata = represented
```

**Not implemented in this gate** (REV-D3).

## 60. Implementation debt (§88)

```text
REV-D1  DesignView v2 review projection (presentation: "review") with sections,
        entries, semantic classes, derived summaries, findings, consequences
REV-D2  compile precondition: expected_draft_design_hash + STALE_REVIEW refusal
REV-D3  scripts/check_review_coverage.py enforcing the completeness invariant
REV-D4  canonical scientific diff over canonical_request_doc
REV-D5  split DESIGN readiness from EVALUATION preflight (remove backend /
        backend_profile / network_clock_hz / expected_evidence_tier from design readiness)
REV-D6  read-only Memory Addressing (+ Physical Context) Review exposure, which
        requires the DesignView v2 widening
REV-D7  structured capability-consequence projection keyed by registry id +
        capability_semantics_version freshness check
```

**Referenced, not duplicated:** PF-D1…D16 · GX-D1…D8 · CAP-D1…D5 · XDOM-D1…D8 ·
MEM-D1…D5 · OPT-D2…D8 · FAB-D1/D4/D6 · VC-D1 · COMM-D1 · ROUTER-D2.

## 61. Coherence check against §90

| # | Criterion | Status |
|---|---|---|
| 1 | Review represents the exact draft compile will consume | **MET** (§3, §4) |
| 2 | unseen draft changes cannot be compiled | **MET** (§4) |
| 3 | Review has no hidden active scientific fields | **MET** (§5, §6) |
| 4 | disclosure state cannot change Review science | **MET** (§6, §41) |
| 5 | preset names never substitute for materialized values | **MET** (§8) |
| 6 | canonical aliases normalized before Review | **MET** (§7, §34) |
| 7 | scientific terminology correct | **MET** (§46, §55) |
| 8 | intent vs derived preview explicit | **MET** (§19, §52) |
| 9 | no fabricated certificate/qualification/evaluation claim | **MET** (§37, §50) |
| 10 | Torus remains valid-but-downstream-limited | **MET** (§20) |
| 11 | concentration > 1 remains valid | **MET** (§21) |
| 12 | RCU / hardware multicast / multiplane / manual placement / VC count absent | **MET** (§18, §48) |
| 13 | network clock outside Design Review | **MET** (§24) |
| 14 | all Requirements are exact accepted v4 objects | **MET** (§16) |
| 15 | AddressMap active science cannot remain invisible | **MET** (§22) |
| 16 | readiness distinguishes blocking errors from downstream limits | **MET** (§26, §28) |
| 17 | capability consequences come from the registry | **MET** (§30) |
| 18 | capability semantics version respected | **MET** (§31) |
| 19 | scientific diff is canonical, not textual | **MET** (§34) |
| 20 | compile binds the reviewed draft identity | **MET** (§40) |
| 21 | Review and Compile Result are different objects | **MET** (§42) |
| 22 | current Studio surfaces classified | **MET** (§54) |
| 23 | R1–R45 have verdicts | **MET** (§56, §57) |
| 24 | V1–V30 answered | **MET** (§58) |
| 25 | wireframes not begun | **MET** |
| 26 | HTML not begun | **MET** |

## 62. Domain verdict

Gate 7's two hardest requirements turned out to have very different answers.

**Snapshot binding already half-exists.** `DraftView` carries `design_hash` and
`dirty` (`product/service.py:609-636`), and because `design_hash()` is a pure
function of the canonical request, **the draft's hash predicts the revision's
hash**. No new identity is needed. What is missing is the **precondition**: today
`POST /projects/{id}/compile` takes no body and `PUT /draft` is last-write-wins,
so `review X → change draft → compile Y` is currently possible. The fix is one
field — `expected_draft_design_hash` — and a typed `STALE_REVIEW` refusal. **The
content hash is the authoritative snapshot identity; an ETag would be a second,
weaker identity for the same content.**

**Review has no home yet.** There is no Review surface at all; the `Compile` page
shows the *result*, correctly labelling routing and VC count as *"compiler-owned"*
and *"derived"*. The chosen architecture is **`DesignViewV2` with
`presentation: "review"`** — no new object, because Review needs exactly what
`DesignViewV2` must carry anyway (Gate 5 D5, Gate 6 GX-D1). A separate
`DesignReviewView` would duplicate the schema and create a second authority.

Two audit findings became corrections. The current `PreflightView` carries
`backend`, `backend_profile`, `network_clock_hz` and `expected_evidence_tier` —
**design readiness is conflated with evaluation setup** — and collapses to a
single `ready` boolean, which cannot express five readiness states (REV-D5). And
**Review forced a Requirements correction**: `RequirementV3`'s real fields are
`qos_class`, `traffic_class`, `latency_ceiling_cycles`, `bandwidth_floor_gbps`,
`binding` — Gate 5 §17 described the *optimization-constraint* shape instead. Only
the accepted v4 subset is reviewed; **`bandwidth_floor_gbps` is not**.

The **AddressMap contradiction is resolved without inventing an authoring
surface**: Review shows a **read-only Memory Addressing section** whenever the
draft carries a non-empty map. Presets materialize address maps today
(`mesh4_hbm`), so that science **is active** — and an active canonical value
cannot remain invisible merely because the authoring UI is not wired.

The strongest law this gate adds is that **authoring may hide advanced values but
Review may not**. Review is canonical completeness, not another disclosure mode,
and the completeness invariant — *active fields minus metadata equals represented
fields* — makes that mechanically testable rather than remembered.

Finally, envelope language is deliberately weak: Review may say *"compatible with
the design-side prerequisites of `CAP-ENV-BOOKSIM-MESH-DOR-XY-V1`"* and **must
not** claim `QUALIFIED`, because `COND-ROUTING-DOR-XY` and
`COND-IDENTITY-VC-TRANSITIONS` depend on derived state that does not exist yet.
**No `POTENTIALLY_ELIGIBLE` vocabulary is added** — a near-qualification term
invites overclaiming.

**GATE 7 — DESIGN REVIEW: PLANNED — COHERENT**

Gate 8 not begun. No wireframes. No HTML.
