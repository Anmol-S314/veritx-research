# INTENT-PHYSICAL — Domain E.5 specification (Gate 2)

Domain row: `intent-ontology.yaml :: domains.PHYSICAL`
Enforced by: `scripts/check_intent_ontology.py`
Narrow domain. Supersedes the four-node stub marked `planned` by dependency.

---

## 0. Why PHYSICAL exists

Two discoveries forced it:

1. **REQUIREMENTS** — authoritative cycle recovery needs a clock definition;
2. **SYSTEM (S8)** — `physical.num_power_domains` duplicated the power-domain
   authority held by agent `power_domain` declarations.

PHYSICAL owns **shared physical operating parameters** that are neither SYSTEM
inventory, nor FABRIC topology/resources, nor backend runtime metadata.

**Result of this pass: it owns exactly one semantic field.**

---

## 1. The four existing nodes, audited

| Node | Reality | Symbol | Owner | In/derived | Identity | Consumers | Validation | UI |
|---|---|---|---|---|---|---|---|---|
| `default_clock_freq_mhz` | **R2** | `PhysicalContext.default_clock_freq_mhz` `compile_model.py:815` | PHYSICAL | input | **in `design_hash`**; **not** in `fabric_hash` | `_design_clock_hz` (makespan fallback), reports | `> 0` real | number (MHz) |
| `default_data_width` | **R2 metadata** | `PhysicalContext.default_data_width` `:816` | PHYSICAL | input | in `design_hash` | reports, UVM | `≥ 8` | annotated |
| `process_node_nm` | **R2 metadata** | `PhysicalContext.process_node_nm` `:817` | PHYSICAL | input | in `design_hash` | reports only | `≥ 1` | annotated |
| `num_power_domains` | **R3 duplicate** | `PhysicalContext.num_power_domains` `:823` | **must be derived** | input today | in `design_hash` | **only** `resolved_fabric.py:269` (a refusal) | `≥ 1`; `>1` refuses | refusal |

`_TOP_V3_KEYS` carries them as `clock_freq_mhz`, `data_width`,
`num_power_domains`, `process_node_nm` (`compile_model.py:93`).

---

## 2. Every physical authority

| Concept | Symbols | Current owners | Target owner |
|---|---|---|---|
| **design clock** | `PhysicalContext.default_clock_freq_mhz` (MHz, float) | PHYSICAL | **PHYSICAL** |
| **network clock** | `EvaluationOptions.network_clock_hz`; `network_binding.network_clock_hz` | **EVALUATION** | **EVALUATION** (not intent) |
| **serving model clock** | `model.clock_hz(model.network_clock)` `wave_e_resources.py:402` | **SERVING / Wave-E** | SERVING |
| clock **domain** membership | `Agent.clock_domain`; `EndpointInterface.clock_domain` | SYSTEM | SYSTEM |
| power **domain** membership | `Agent.power_domain` | SYSTEM | SYSTEM |
| power-domain **count** | `PhysicalContext.num_power_domains` | duplicate | **derived from SYSTEM** |
| `default_data_width`, `process_node_nm` | `PhysicalContext` | PHYSICAL | PHYSICAL (metadata) |
| router / link latency | `_DEFAULT_LINK_LATENCY_CYCLES` `topology_artifact.py` | FABRIC | FABRIC |
| backend timing | BookSim profile, ASTRA tick | BACKEND | BACKEND |
| memory timing | Ramulator geometry | MEMORY | MEMORY |

**No concept is absorbed into PHYSICAL merely because it has a time unit.**

---

## 3. Clock authority — **three clocks, three roles, zero duplicates**

This is the central finding, and it is *not* what the stub assumed.

### 3.1 Design clock — PHYSICAL

```text
PhysicalContext.default_clock_freq_mhz : float, MHz, default 1000.0
_design_clock_hz = Fraction(str(mhz)) * 10**6
```

Docstring: *"The design's own clock (exact Hz) — **the only legal converter for
the makespan fallback** (never a caller-supplied network clock)."*

**Role:** the wall-time → cycles conversion in the **fallback** path only, plus
reports. It **does not authenticate cycles.**

### 3.2 Network clock — EVALUATION

```text
EvaluationOptions.network_clock_hz : int | Fraction | None
```

- **caller-supplied at evaluation time**, not declared intent;
- recorded into `network_binding.network_clock_hz`, which becomes part of
  **evidence identity**;
- used by `authenticated_network_cycles` — the **primary** path;
- `None` → **typed refusal**: *"no valid network clock declared
  (EvaluationOptions.network_clock_hz): refusing wall-time claims; reporting
  the authenticated cycles-only completion window"* (`UNSUPPORTED`);
- CLI requires **exact** Hz: *"`float("9007199254740993")` silently becomes
  9007199254740992, so a frequency would move without anyone changing it"*
  (`commands_optimize.py:27`).

### 3.3 Serving model clock — SERVING

`wave_e_resources.py:402` validates
`rebuilt.network_clock_hz == model.clock_hz(model.network_clock)` — the Wave-E
performance model is the authority for its own network clock.

**Conclusion:** the three are **different quantities**, not duplicate
authorities. **The cycle-recovery clock is an execution parameter, so PHYSICAL
does not own it.** The stub's implicit assumption — that PHYSICAL owns "the
clock" — was wrong, and correcting it *shrinks* the domain.

---

## 4. Clock domain vs design clock

**They are unrelated concepts and must not be equated.**

| | SYSTEM `clock_domain` | PHYSICAL design clock |
|---|---|---|
| kind | a membership **label** on agents | a **frequency** |
| identity | string, per agent group | number, global |
| consumer | `fabric_artifact.py:305` — **a refusal** | fallback conversion, reports |
| multiplicity | many ids declarable | one frequency |

`fabric_artifact.py:304` is a **clock-domain gate**: endpoints spanning multiple
domains → `UNSUPPORTED` (*"FabricArtifact v1 has no clock-crossing artifact"*).
So `clock_domain` is a **refusal trigger**, not a frequency carrier. **A domain
id does not imply a frequency.**

## 5. Multi-clock boundary

```text
SCHEMA-VALID:      multiple SYSTEM ClockDomain ids
CURRENT PHYSICAL:  one design frequency; one active timing domain
UNSUPPORTED:       multiple active physical timing domains, CDC
```

**No per-domain frequency map is introduced** — no downstream semantics exist.

---

## 6. Cycle recovery law (exact, preserved)

```text
inputs:   network_binding.duration (exact seconds) × network_binding.network_clock_hz (exact Hz)
law:      the product must be an EXACT INTEGER
failure:  EvidenceInvalid — "BookSim completion_time is integral, so this pair
          cannot be the authenticated window — refusing to measure it"
null:     a null clock ⇒ cycles-only binding; wall-time claims refused
```

**Approximate frontend conversion is forbidden.** `_parse_clock_hz` refuses
non-integral and non-finite input at the CLI boundary, *"never inside the
science."*

## 7. Time-domain identity

| Domain | Owner | Convertible? |
|---|---|---|
| network cycles | EVALUATION (network clock) | **authoritative** |
| network wall duration | EVALUATION | bound to its clock |
| ASTRA time | BACKEND | only via a qualified binding |
| BookSim cycles | BACKEND | native |
| serving model time | SERVING | serving authority |
| wall-clock runtime | EXECUTION | **never** a scientific time |

**No universal converter.** The REQUIREMENTS law stands: *"time never
cross-compared without proof"* (`core/comparison.py:56`).

---

## 8. Power-domain duplicate authority — removed

| Authority | Role today |
|---|---|
| `Agent.power_domain` (SYSTEM) | membership; `fabric_artifact.py:317` **derives the set** and refuses `>1` |
| `PhysicalContext.num_power_domains` | declared count; `resolved_fabric.py:269` refuses `>1` |

**Two sources, one concept.** Target law:

```text
power_domain_count = derived from canonical SYSTEM power-domain declarations
legacy field: accepted, validated equal to the derived count, refused on mismatch
canonical v4: duplicate field REMOVED
```

The declared field's *only* consumer is a refusal that the derived check also
performs — so removal loses no capability.

## 9. Power semantics boundary

`PowerDomain` is an **id**. It does **not** imply voltage, DVFS, power gating,
energy or thermal modelling. **None of those exist in the repository** →
`CONTRACT NOT AVAILABLE`.

## 10. Process / technology

`process_node_nm` exists and is **metadata-only** (reports, `reports.py:351`).
**No voltage, no frequency corner, no PVT anywhere.** → `OUT OF SCOPE`.
PHYSICAL is **not** an ASIC PPA intent model.

## 11. Router / link latency boundary

`_DEFAULT_LINK_LATENCY_CYCLES` lives in `topology_artifact.py` — **FABRIC**.
Router behavior belongs ROUTER. **Not pulled into PHYSICAL** despite the time
unit.

## 12. Backend timing boundary

BookSim internal speedup, ASTRA tick, simulation timestep and wall process
runtime are **backend/execution configuration** unless bound to the physical
clock contract. Kept separate.

## 13. Serving timing boundary

`TTFT`, `ITL`, `TPOT`, `request_latency` are **serving authority**. PHYSICAL's
clock does **not** imply compute duration, scheduler duration or serving time.
**No hidden conversion.**

## 14. Memory timing boundary

Ramulator/DRAM timing belongs **MEMORY / memory backend**. The network design
clock is **not** the memory clock. **No coupling exists in code** — and none is
introduced.

---

## 15. Stable identity

**In `design_hash`:** the design clock, data width, process node, power-domain
count (today).
**In `fabric_hash`:** **nothing physical** — `FabricArtifact.identity_dict`
(`fabric_artifact.py:177`) carries topology/attachment/VC/routing/packet/
router-behavior/address-decode hashes and `plane_composition` only.

**Excluded from identity:** display labels, backend wall time, execution
timestamps.

## 16. PhysicalIntentV4 — the smallest justified schema

```text
PhysicalIntentV4 {
  design_clock_hz      # exact rational; canonical; > 0
  data_width           # metadata (reports)
  process_node_nm      # metadata (reports)
}
```

**One semantic field plus two metadata fields.** `num_power_domains` is
**removed**. The network clock is **not** here — it is an evaluation parameter.

**The domain is legitimately this small.** It is not inflated to look
important.

## 17. Derived PhysicalView (read-only)

```text
PhysicalView {
  design_clock_hz
  power_domain_count        # derived from SYSTEM
  supported_time_conversions
  network_clock_source      # EVALUATION (explanatory)
}
```

Not a canonical artifact. **Derived quantities are never editable.**

---

## 18. Relationship to SYSTEM

```text
SYSTEM    declares ClockDomain / PowerDomain membership identities
PHYSICAL  declares the design clock frequency (+ metadata)
DERIVED   power-domain count
UNSUPPORTED  multiple active physical timing domains
```

**No duplicate clock-domain authority:** SYSTEM owns *membership*, PHYSICAL owns
*one frequency*, and the two are never equated.

## 19. Relationship to REQUIREMENTS

A requirement references a `MetricId`; the **producer** may consume physical
timing. The requirement object **never copies a clock**.

| Path | Depends on the design clock? |
|---|---|
| `network_completion_cycles` (authenticated) | **no** — the binding records its own clock |
| makespan fallback | **yes** — `_design_clock_hz` |

So a design-clock change invalidates **fallback-derived** cycles only.

## 20. Relationship to FABRIC

**Audited: FABRIC does not consume the design clock.** `FabricArtifact`
identity has no physical field. There is **no** operating-point identity split
to invent — structural fabric identity simply does not include the clock.

## 21. Frequency-change invalidation (1 GHz → 1.2 GHz) — exact

| Artifact | Effect |
|---|---|
| `design_hash` | **changes** (physical is in `canonical_dict`) |
| `FabricArtifact` / `resolved_fabric_hash` | **unchanged** |
| Topology / attachment / route / VC / packet format | **unchanged** |
| `network_binding` (recorded `network_clock_hz`) | **unchanged** — self-contained |
| authenticated cycle evidence | **reusable** |
| makespan-fallback cycles | **change** (recomputed from the new design clock) |
| `RequirementReport` using the fallback | **stale** |
| `RequirementReport` using authenticated cycles | **reusable** |

## 22. Cycles vs nanoseconds reuse

**Native cycle evidence is reusable under a changed design clock**, because the
binding records `(duration, network_clock_hz)` as the exact image of the
backend's integer `completion_time` — *"the caller's clock cancels."*

**Derived nanosecond evidence is not**: it is a function of the clock used.

This is the scientifically important distinction, and the evidence contract
already implements it.

## 23. Physical changes and compiler identity

| Identity | Includes physical? |
|---|---|
| `CompileRequestV3.design_hash` | **yes** |
| `FabricArtifact.fabric_hash` | **no** |
| `ResolvedFabric.resolved_fabric_hash` | no (parents are design+mapping+fabric) — **design_hash is a parent**, so it changes |
| backend config identity | the *network clock* is an evaluation option, recorded in the binding |
| evidence identity | binds `network_clock_hz` |

**Note:** `resolved_fabric_hash` includes `design_hash` as a parent, so a design
clock change **does** move it — while the `fabric_hash` it points at does not.
That is a real, documented distinction, not a contradiction.

## 24. Migration

| Legacy field | Target |
|---|---|
| `clock_freq_mhz` (MHz float) | `design_clock_hz` — **exact rational**, lossless (`Fraction(str(mhz)) * 10⁶`) |
| `num_power_domains` | **removed**; validate equality against SYSTEM-derived count, refuse mismatch |
| `data_width` | unchanged (metadata) |
| `process_node_nm` | unchanged (metadata) |
| absent clock | **no invisible default**: the legacy `1000.0` default is recorded as *legacy loader semantics*, not v4 canonical state |

## 25. Failure taxonomy

| Case | Verdict |
|---|---|
| `frequency ≤ 0` | **INVALID** |
| non-integral where the metric requires integral | **INVALID** / typed refusal |
| float Hz at the CLI boundary | **INVALID** — exact parsing required |
| multiple active frequencies | **UNSUPPORTED** |
| legacy `num_power_domains` disagrees with SYSTEM | **migration/compile refusal** |
| time-domain conversion unavailable | **UNMEASURABLE / INCOMPARABLE at the consumer**, never malformed PHYSICAL intent |
| unknown physical field | **fail closed** |

## 26. Capability matrix

| Capability | Declarable | Consumed | Verifiable | Evidence-capable |
|---|---|---|---|---|
| single design clock | **yes** | yes (fallback + reports) | yes | n/a |
| multiple clock **domains** | **yes** (SYSTEM) | as a **refusal trigger** | yes | n/a |
| per-domain frequency | **no** | — | — | — |
| DVFS / voltage | **no** | — | — | — |
| multiple power domains | declarable | **refused** | — | — |
| power gating / energy / thermal | **no** | — | — | — |
| process node | declarable (metadata) | reports only | — | — |
| clock → network ns conversion | **no** (no qualified conversion) | — | — | — |
| network clock (evaluation) | yes | **yes** — authenticates cycles | yes | yes |

## 27. Adversarial cases

| # | Case | Verdict |
|---|---|---|
| **PH1** | 1 GHz | VALID (`1000.0` MHz) |
| **PH2** | non-integer GHz as exact Hz | VALID as exact rational |
| **PH3** | 0 Hz | INVALID |
| **PH4** | negative | INVALID |
| **PH5** | extreme frequency | exact rational arithmetic; no silent float overflow |
| **PH6** | `duration × clock_hz` integral | **authenticated** |
| **PH7** | non-integral product | **refused** (`EvidenceInvalid`) |
| **PH8** | same native cycle evidence, design clock changed | **reusable** |
| **PH9** | same ns evidence, clock changed | interpretation changes → **not silently reusable** |
| **PH10** | two clock-domain ids, one physical frequency | **schema-valid**; membership only; fabric refuses multi-domain endpoints |
| **PH11** | two distinct physical frequencies | **UNSUPPORTED** |
| **PH12** | legacy `num_power_domains` agrees with SYSTEM | migration succeeds, field removed |
| **PH13** | disagrees | **refuse** |
| **PH14** | power-domain label changes | label only; no scientific identity effect |
| **PH15** | network clock vs Ramulator clock | **must not be equated** — no coupling exists |
| **PH16** | network clock vs serving model time | **must not be equated** — serving authority |
| **PH17** | topology unchanged, clock changes | `fabric_hash` **unchanged**; `design_hash` changes |
| **PH18** | route unchanged, clock changes | route identity **unchanged** |
| **PH19** | `RequirementSet` unchanged, clock changes | authenticated-cycle reports **reusable**; fallback reports stale |
| **PH20** | unknown physical field | fail closed |

## 28. Research questions P1–P20

| # | Answer |
|---|---|
| P1 | `PhysicalContext.default_clock_freq_mhz` for the **design** clock; `EvaluationOptions.network_clock_hz` for the **network** clock |
| P2 | design clock in `CompileRequest.physical`; network clock in `EvaluationOptions` and `network_binding`; serving clock in the Wave-E model |
| P3 | each is an **authority in its own role**; none is a projection of another |
| P4 | design clock is a **float MHz**; the **network** clock is **exact int/Fraction Hz** |
| P5 | `duration × network_clock_hz` must be an **exact integer** |
| P6 | `completion_cycles`, `completion_ns`, and the fallback path |
| P7 | **yes** — `completion_time`/`completion_cycles` are integral backend stats |
| P8 | BookSim reports integer completion cycles; the binding adds `(duration, clock)` |
| P9 | **no** — `FabricArtifact.identity_dict` has no physical field |
| P10 | the network clock is an evaluation option, recorded in the binding |
| P11 | **yes** — topology does not depend on the clock |
| P12 | a **membership label** whose only functional use is a multi-domain **refusal** |
| P13 | **yes** — many ids declarable |
| P14 | **no** |
| P15 | declared on `PhysicalContext`, duplicating agent `power_domain` |
| P16 | **only** `resolved_fabric.py:269` (a refusal) |
| P17 | refusal + identity only; no behavioural semantics |
| P18 | **no** — memory timing is Ramulator's |
| P19 | **no** — serving time is serving authority |
| P20 | **no** — only `process_node_nm`, metadata-only |

**All 20 answered.**

---

## 29. UI implications

**No standalone Physical page.** If justified at all:

```text
Operating point
  Network clock    EVALUATION parameter (set at evaluation, not design)
  Design clock     1.00 GHz
  Timing domain    single clock supported
  Power domains    1 (derived from System)
```

**No** voltage, process-node or thermal-design-power controls. `process_node_nm`
and `data_width` remain **annotated metadata**, never presented as design knobs.

## 30. Product IA placement — **B: a supporting subdomain**

PHYSICAL is **not** a primary Design step. It surfaces under
**System → Operating point** (with the design clock) and the network clock is
shown at **Evaluate** where it is actually supplied.

**Ontology domain ≠ mandatory navigation destination.** This principle applies
to every remaining domain.

---

## 31. Coherence criteria

1. four nodes audited — **MET** (§1)
2. one **design** clock authority — **MET** (§3.1)
3. duplicate clock copies classified authority/projection — **MET**: three
   clocks, three roles, **no duplicates** (§3)
4. clock-domain vs clock-frequency boundary explicit — **MET** (§4)
5. power-domain duplicate authority removed — **MET** (§8)
6. time-domain conversion law exact — **MET** (§6, §7)
7. requirements dependency explicit — **MET** (§19)
8. native cycles vs derived wall-time reuse law explicit — **MET** (§22)
9. fabric/backend identity dependencies known — **MET** (§20, §23)
10. memory/serving clocks not conflated — **MET** (§14, §13)
11. target schema minimal — **MET** (§16)
12. PH1–PH20 verdicts — **MET** (§27)
13. P1–P20 resolved — **MET** (§28)
14. PLACEMENT not begun — **MET**

---

## 32. Domain verdict

The stub was accepted by dependency and has now earned its gate. The audit
**shrank** the domain rather than growing it: the assumption that PHYSICAL owns
"the clock" was wrong.

**Three clocks, three roles, no duplicates:** the **design** clock (PHYSICAL —
fallback conversion and reports), the **network** clock (EVALUATION — the
authority that authenticates cycles, exact Hz, recorded in evidence), and the
**serving model** clock (SERVING). Equating any two would have produced a
fabricated authority.

Also confirmed: `clock_domain` is a membership label whose only functional use
is a multi-domain **refusal**, not a frequency carrier; `num_power_domains` is a
**removable** duplicate whose sole consumer is a refusal the derived check also
performs; `FabricArtifact` identity contains **nothing physical**, so a clock
change does not invalidate the fabric while it does change `design_hash`; and
**native cycle evidence survives a clock change** because the binding records
its own clock.

PHYSICAL owns **one semantic field**, two metadata fields, and one refusal. It
does not become a PPA model.

**PHYSICAL INTENT: PLANNED — COHERENT**

Per Gate 2's rule, PLACEMENT is not begun.
