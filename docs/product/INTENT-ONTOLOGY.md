# INTENT-ONTOLOGY — Design/Intent Subsystem Model (Gate 1 of 8)

Status: **GATE 1 DRAFT — implementation frozen.**
Scope: the model only. No flow, no contracts, no interaction, no wireframes,
no HTML. Gate 2 may not start until §6 is satisfied.

This document is the single source of truth for what the Design/Intent page
may present as declarable. It is **extracted from the compiler**, never
written beside it. Every row cites the owning Python symbol; a row that
cannot be cited does not exist.

Related gates: this file is the Gate-1 input to the redesign program
(`USER DECLARES → COMPILER DERIVES → EXECUTION/LOWERING DERIVES`).
Sibling gate: `docs/product/STUDIO-BACKEND-COVERAGE.md` (feature
eligibility A/B/C/D). This file answers a different question — *what is
declarable* — and does not restate eligibility.

---

## §0 Boundary and its mechanism

The boundary `USER DECLARES / COMPILER DERIVES` is not a UI convention.
It is enforced in the type system, and the redesign must render *from*
that mechanism rather than re-implement the split in React.

| Mechanism | Location | Meaning |
|---|---|---|
| `Tier` (`LOCKED` / `GUIDED` / `FREE`) | `model/compile_model.py:192` | LOCKED = "Compiler derives. No override, no expert mode." |
| Absent field by construction | `NocConfig` `model/compile_model.py:602` | No `routing_function`, `turn_restrictions`, `vc_map` field exists. "An override isn't something the compiler refuses — it's something that cannot be expressed." |
| LOCKED output type | `VCAssignment` `model/compile_model.py:852` | "the LOCKED output that the user cannot override." |
| Required, non-defaultable policy | `CompileIntent.candidate_policy` `application/compile_intent.py:369` | "required and may not be defaulted." |

**Rule for the redesign:** a field with no tier annotation is never
rendered as editable. Tier is data, not art direction.

---

## §1 Two declared layers (the ontology has two roots)

The subsystem declares intent at **two** layers with **different
identities**. This is the first structural fact the page gets wrong.

```text
PRODUCT LAYER
  CompileIntent  (application/compile_intent.py:343)
    fabric_preset · fabric_overrides · candidate_policy
    identity: intent_id  (content_id of the declaration)
        │  derive_compile_request(intent)
        ▼
COMPILER LAYER
  CompileRequestV3  (model/compile_model.py:2166)
    workload · requirements · agents · dependencies
    noc_config · address_map · physical
    identity: design_hash
        │
        ▼
COMPILER-DERIVED (no user field exists for any of it)
```

| Layer | Type | Identity | Draft endpoint writes it? |
|---|---|---|---|
| Product | `CompileIntent` `application/compile_intent.py:343` | `intent_id` | **No** |
| Compiler | `CompileRequestV3` `model/compile_model.py:2166` | `design_hash` | Yes — `product.put_draft` → `canonical_request_doc` `product/service.py:634` |

The current page edits the **compiler layer only**. `fabric_preset`,
`fabric_overrides` and `candidate_policy` are declared product intent that
has no UI home, and `intent_id` is never shown. See Decision D1.

**Fabric-facing subset.** The compiler's fabric derivation consumes a
gated projection, `FabricIntentView` (`model/compile_model.py:2679`):
`agents`, `dependencies`, `noc_config`, `address_map`, `physical`, `tp/pp/ep/dp`,
declared `traffic_classes`, `design_hash`. Non-persisted, never hashed.
This is the authoritative answer to "which intent fields the fabric
actually needs" and should drive which domains the page groups as
fabric-scoped.

---

## §2 Complete intent ontology — three-state classification

Every concept in the Design/Intent ontology falls into exactly one of:

- **DECLARED** — a user may set it today; tier stated.
- **DERIVED** — the compiler computes it; display-only, never editable.
- **NOT-MODELLED** — named in the intended ontology but has no type today.
  Creating one is new scope (new contract), not a new form field.

### 2.1 SYSTEM

| Concept | State | Type / tier | Notes |
|---|---|---|---|
| Agent kinds | DECLARED | `AgentKind` `:222`, `Agent` `:232` (GUIDED) | `compute_tile`, `hbm_controller`, `nic`, `peripheral`, `ucie_port` |
| Agent count | DECLARED | `Agent.count` (GUIDED) | |
| Agent interface | DECLARED | `data_width`, `addr_width`, `protocol`, `clock_domain`, `power_domain` (GUIDED) | |
| Nodes / accelerators / chiplets | NOT-MODELLED | — | No such taxonomy. `NodeInventory` `model/placement.py:157` derives nodes from counts. |
| Machine hierarchy | DERIVED | `NodeInventory` | Derived from agent counts + parallelism. |
| Resource domains | NOT-MODELLED | — | Power/clock domains exist per `Agent` and in `PhysicalContext`; no general "domain" entity. |

### 2.2 WORKLOAD

| Concept | State | Type / tier | Notes |
|---|---|---|---|
| Model family | DECLARED | `ModelFamily` `:265` (GUIDED) | |
| Model name | DECLARED | `WorkloadV3.model_name` (GUIDED) | Presentation; does not enter identity alone |
| Parallelism TP/PP/EP/DP | DECLARED | `WorkloadV3.tp/pp/ep/dp` `:2073` (GUIDED) | |
| Serving mode | DECLARED | `ServingMode` `:274` (GUIDED) | **Characterization only** — never maps to a per-operation phase (see `workload/intent_lowering.py`). |
| Operation graph | NOT-MODELLED | — | Not declared; collectives + dependencies are the declared substitutes. |
| Phases | NOT-MODELLED | — | Explicitly refused as an inference from `serving_mode`. |
| Memory behaviour | NOT-MODELLED | — | No declared memory-behaviour entity. |
| Static/serving execution mode | DERIVED | backend selection | Execution mode belongs to lowering, not intent. |
| Workload source | DECLARED | `WorkloadSourceRef` `:1978` (GUIDED) | Identity over **bytes**: `content_digest` + `format` + `size_bytes`; paths never enter identity. |

### 2.3 PARALLELISM

| Concept | State | Type / tier | Notes |
|---|---|---|---|
| TP/PP/EP/DP geometry | DECLARED | `WorkloadV3` (GUIDED) | Single declaration; groups are derived |
| Participant groups | DERIVED | `CollectiveDimension` expansion `:1891` | TP/DP/EP expand deterministically; `world_size` via `presets.parallel_world_size` |
| Group constraints | NOT-MODELLED | — | No group-constraint entity. |

### 2.4 COMMUNICATION INTENT

| Concept | State | Type / tier | Notes |
|---|---|---|---|
| Collective semantics | DECLARED | `CollectiveIntent` `:1910`, `CollectiveKind` `:281` (GUIDED) | `allreduce`, `allgather`, `reducescatter`, `broadcast`, `alltoall` |
| Collective dimension | DECLARED | `CollectiveDimension` `:1891` (GUIDED) | `TP`/`DP`/`EP`/`PP`/`GLOBAL`; a PP-dimension COLLECTIVE is a typed refusal at lowering |
| Payload | DECLARED | `CollectiveIntent.payload_bytes` (GUIDED) | Per-kind schedule payload, consumed verbatim |
| Broadcast root | DECLARED | `CollectiveIntent.source_rank` (GUIDED) | Required for BROADCAST; refused for others (no fabricated root) |
| Traffic classes | DECLARED | unified namespace | Declared by `traffic_class` on collectives/requirements/dependencies; surfaced as `FabricIntentView.traffic_classes` (sorted, distinct) |
| Point-to-point classes | DECLARED | `DependencyGraph` `:446` (GUIDED) | Via `Dependency.source/target/kind` |
| Multicast / broadcast | DECLARED | `CollectiveKind.BROADCAST` + `NocConfig.mcast_*` (GUIDED) | |
| Reduction | DECLARED (partial) | `rcu_enabled`, `mcast_*` (GUIDED) | In-network reduction is a GUIDED knob; `rcu_enabled=true` is a current typed refusal (no RCU realization) |
| Dependencies | DECLARED | `Dependency` `:428`, `DepKind` `:420` (GUIDED) | |
| Logical messages | DERIVED | `workload/lowering.py` | Lowering output, not intent |

### 2.5 REQUIREMENTS

| Concept | State | Type / tier | Notes |
|---|---|---|---|
| Traffic identity | DECLARED | `RequirementV3.traffic_class` `:2117` (GUIDED) | Distinct from QoS policy; `None` = fabric-wide |
| QoS class | DECLARED | `QoSClass` `:391` (GUIDED) | `latency_critical`, `bandwidth`, `best_effort` |
| Latency ceiling | DECLARED | `latency_ceiling_cycles` (GUIDED) | |
| Bandwidth floor | DECLARED | `bandwidth_floor_gbps` (GUIDED) | |
| Binding / acceptance | DECLARED | `RequirementV3.binding` (GUIDED) | **The design's pass/fail criterion.** binding + UNMEASURABLE never passes. |
| Locality / isolation / reachability | NOT-MODELLED | — | No requirement type. |
| Reliability / qualification | NOT-MODELLED as intent | producer qualification is execution-side | |
| Measurement authority | DERIVED | `application/requirements.py`, `backend/evidence.py` | Authority is engine-owned |
| Requirement verdicts | DERIVED | requirement report | Never declared |

### 2.6 PLACEMENT INTENT

| Concept | State | Type / tier | Notes |
|---|---|---|---|
| Placement (rank → agent) | DERIVED | `MappingArtifact` `model/mapping.py:88` | Supplied as a **candidate dimension**, not a declared field |
| Placement policy | DERIVED | `MappingPolicy.RANK_ORDER_V1` `compiler/candidate_policy.py:141` | "owned by candidate generation" — compiler-owned |
| Affinity / anti-affinity / locality / co-location / fixed placement / reserved resources / mapping objective | NOT-MODELLED | — | None exist as declared intent. Decision D2. |

### 2.7 FABRIC INTENT

| Concept | State | Type / tier | Notes |
|---|---|---|---|
| Topology family | DECLARED | `TopologyFamily` `:583`, `NocConfig.topology_family` (GUIDED) | `torus`/`gec`/`fat_tree` are typed refusals on the current routing path — selectable, never silently downgraded |
| Radix | DECLARED | `NocConfig.radix` (GUIDED) | |
| Concentration | DECLARED | `NocConfig.concentration` (GUIDED) | |
| Link width | DECLARED | `NocConfig.link_width` (GUIDED) | |
| Arbitration | DECLARED | `NocConfig.arbitration` (GUIDED) | |
| Multicast limits | DECLARED | `mcast_groups`, `mcast_setup_cycles` (GUIDED) | `None` = unconstrained |
| RCU (reduction) | DECLARED | `rcu_enabled` (GUIDED) | Current typed refusal when true |
| Output format | DECLARED | `OutputFormat` `:592`, `NocConfig.output_formats` (FREE) | |
| Obfuscation | DECLARED | `NocConfig.obfuscation_level` (FREE) | |
| Dimensions / hierarchy / planes / links / traffic-plane binding / topology constraints | NOT-MODELLED | — | Only the six GUIDED knobs + two FREE knobs exist; concrete dimensions/links are derived. |
| TopologyArtifact, FabricArtifact | DERIVED | `model/fabric_artifact.py` | |

### 2.8 ROUTER / RESOURCE INTENT

| Concept | State | Type / tier | Notes |
|---|---|---|---|
| Arbitration preference | DECLARED | `NocConfig.arbitration` (GUIDED) | Aliases in `model/router_behavior.py` |
| Buffering / resource budget | DERIVED | `FabricCompileSettings` (candidate recipe) | `max_packet_flits`, buffer depths are compiler-owned baseline |
| Supported traffic classes | DERIVED | `candidate_policy._traffic_classes` | Must not invent a class absent from the declaration |
| Reduction capability | DECLARED (partial) | `rcu_enabled`/`mcast_*` | |
| Routing function, VC count, turn restrictions | DERIVED (LOCKED) | `VCAssignment` `:852` | Structurally absent from `NocConfig` |
| Implementation constraints | NOT-MODELLED | — | |

### 2.9 MEMORY INTENT

| Concept | State | Type / tier | Notes |
|---|---|---|---|
| Address ranges | DECLARED | `AddressRange` `:660`, `AddressMap` `:676` (GUIDED) | `name`, `base`, `size`, `target_agent_idx` |
| Address decode | DERIVED | `model/address_decode.py` | |
| Memory domains / address spaces / locality / controller relationships / memory traffic classes | NOT-MODELLED | — | Only ranges exist. |

### 2.10 PHYSICAL CONTEXT

| Concept | State | Type / tier | Notes |
|---|---|---|---|
| Clock / data width / power domains / node | DECLARED | `PhysicalContext` `:815` (FREE) | `default_clock_freq_mhz`, `default_data_width`, `num_power_domains`, `process_node_nm` |

### 2.11 DESIGN-SPACE INTENT

Lives in a **separate subsystem** (`optimization/definition.py`), operates
in **metric space**, and is not part of `CompileRequestV3`. Decision D3.

| Concept | State | Type / tier | Notes |
|---|---|---|---|
| Searchable parameters | DECLARED | `DomainParam` `optimization/definition.py:105` | Finite GUIDED design-variable domain; names gated by `_check_guided` |
| Hard constraints | DECLARED | `Constraint` `optimization/definition.py:150` | `metric`, `op ∈ {<=,>=}`, finite `threshold`; one per metric |
| Objectives | DECLARED | `Objective` `optimization/definition.py:130` | `metric`, `direction ∈ {MIN,MAX}`; ≥1 required; one per metric |
| Search definition | DECLARED | `OptimizationDefinition` `optimization/definition.py:167` | + `method`, `budget`, `seed`, `selection` |
| Fixed parameters | NOT-MODELLED | — | "Fixed" is implicit: everything absent from `domain`. No entity. |
| Candidate-generation policy | DECLARED (product layer) | `CandidatePolicy` `compiler/candidate_policy.py:135`, `CompileIntent.candidate_policy` | Required; one legal value today (`BASELINE_DETERMINISTIC_V2`) |

**Do not merge the two "hard constraint" concepts.** `RequirementV3.binding`
is declared acceptance evaluated post-run; `Constraint` is search
feasibility over measured metrics. §2.5 ≠ §2.11.

---

## §2.12 Per-node answer set

The ten questions, answered for every node. These columns ARE the visual
schema: Gates 2–6 compose from them and may not add an eleventh axis.

**Codes**

| Col | Values |
|---|---|
| **Real** | `R2` consumed · `R1` parsed/inert · `R3` refused · `R4` derived · `R0` absent |
| **Owner** | `PRD` product (`CompileIntent`) · `CI` compiler-intent · `CAND` candidate · `DER` derivation · `EXE` execution/evidence · `OPT` optimization |
| **Edit** | `TCU` type+contract+UI · `TC-` type+contract, no UI · `T--` type only · `---` none |
| **Kind** | `CMT` commitment · `PRF` preference (has default) · `META` authoring · `RED` redundant · `INERT` · `DERIVED` |
| **Inv** | `A` identity-only · `B` fabric · `C` judgement · `D` refusal · `E` global pin |
| **Val** | `L1n` node-local parse · `L1d` document parse · `L2` identity/pin · `L3d` doc-computable, compile-time · `L3x` derivation-only · `L4` verification · `L5` report |
| **Vis** | `1` declaration control · `2` derived value · `3` refusal · `4` absence · `5` identity · `6` change class |

### SYSTEM / agents

| Node | Real | Owner | Edit | Kind | Stored | Deps | Inv | Val | Unsup | Vis |
|---|---|---|---|---|---|---|---|---|---|---|
| `agents[].kind` | R2 | CI | TC- | CMT | request → `NodeInventory`, `TopologyArtifact`, `AgentAttachmentArtifact` | inventory, topology, attachment | B | L1n | — | 1 |
| `agents[].count` | R2 | CI | TCU | CMT | same | **entire DAG** | B | L1n + L3d (`rank_count ≤ compute`) | — | 1 |
| `agents[].data_width` | R2 | CI | TC- | CMT | attachment, packet format | fabric | B | L1n (≥8) | — | 1 |
| `agents[].addr_width` | R2 | CI | TC- | CMT | attachment, address decode | fabric | B | L1n (≥8) | — | 1 |
| `agents[].protocol` | **R1** (carried) | CI | TC- | **INERT** | attachment artifact content | — (no reader) | **B** (hash-bearing) | L1n | — | 1 + annotate |
| `agents[].clock_domain` | R2/R3 | CI | TC- | CMT | attachment, `FabricArtifact` | fabric | B/D | L1n | fabric (>1 distinct) | 3 |
| `agents[].power_domain` | R2/R3 | CI | TC- | CMT | attachment, `FabricArtifact` (derives domain set) | fabric | B/D | L1n | fabric (>1 distinct) | 3 |

### WORKLOAD

| Node | Real | Owner | Edit | Kind | Stored | Deps | Inv | Val | Unsup | Vis |
|---|---|---|---|---|---|---|---|---|---|---|
| `model_family` | **R3** (4 of 5) | CI | TCU | CMT | request | lowering | **D** | L1n | **lowering: MoE, diffusion, CNN, custom** | 3 |
| `model_name` | R1 | CI | TCU | INERT | request only | — | A | L1n | — | 1 + annotate |
| `serving_mode` | R1 | CI | TCU | INERT | request only | — | A | L1n | — | 1 + annotate |
| `tp/pp/ep/dp` | R2 | CI | TCU | CMT | request → `NodeInventory`, `MappingArtifact`, `WavedParallelism` | mapping, groups, VC scope, lowering | B | L1n + L3d | — | 1 |
| `collectives[].kind` | R2 | CI | TC- | CMT | request → registry, VC, lowering | VC classes, lowering | B | L1n | — | 1 |
| `collectives[].dimension` | R2 | CI | TC- | CMT | request → groups | `WavedParallelism`, lowering | B | L1n + L3x | PP-dim collective | 1 |
| `collectives[].payload_bytes` | R2 | CI | TC- | CMT | request → lowering | messages, traffic, timeline | B | L1n (≥1) | — | 1 |
| `collectives[].traffic_class` | R2 | CI | TC- | CMT | request → **derived registry** | VC classes | B | L1n | — | 1 |
| `collectives[].source_rank` | R2 | CI | TC- | CMT | request → lowering | messages | B | L1n (required iff BROADCAST) | — | 1 |
| `collectives` **order** | R2 | CI | TC- | CMT | request (order-semantic) | lowering operation chain | B | — (semantic) | — | 1 |
| `source_ref` | R1 | CI | TC- | INERT | request (`identity_dict` hashed) | — | A | L2 (digest format) | — | 1 + annotate |
| v2 `param_count_b`, `sequence_length`, `batch_size`, `precision`, `trace_path` | R0 | — | --- | — | — | — | — | — | — | 4 |

### DEPENDENCIES

| Node | Real | Owner | Edit | Kind | Stored | Deps | Inv | Val | Unsup | Vis |
|---|---|---|---|---|---|---|---|---|---|---|
| `dependencies[].source/target/kind` | R2 | CI | TC- | CMT | request → VC derivation, route | VC classes, routing | B | L1n | — | 1 |

### REQUIREMENTS

| Node | Real | Owner | Edit | Kind | Stored | Deps | Inv | Val | Unsup | Vis |
|---|---|---|---|---|---|---|---|---|---|---|
| `requirements[].traffic_class` | R2 | CI | TCU | CMT | request (scope) | requirement report only | **C** | **L5** (`∈` registry) | — | 1 (select over registry) |
| `requirements[].qos_class` | R2 | CI | TCU | CMT | request | report | C | L1n | — | 1 |
| `requirements[].latency_ceiling_cycles` | R2 | CI | TCU | CMT | request | report (via `physical` clock) | C | L1n (≥0) | — | 1 |
| `requirements[].bandwidth_floor_gbps` | R2 | CI | TCU | CMT | request | report | C | L1n (≥0) | — | 1 |
| `requirements[].binding` | R2 | CI | TCU | CMT | request | `report_passes()` | C | L1n + L5 (binding+UNMEASURABLE) | — | 1 (acceptance marker) |

### PLACEMENT / ROUTER / RESOURCE

| Node | Real | Owner | Edit | Kind | Stored | Deps | Inv | Val | Unsup | Vis |
|---|---|---|---|---|---|---|---|---|---|---|
| placement (rank → agent) | R4 | CAND | --- | DERIVED | `MappingArtifact` | attachment, topology | B | L3x | — | 2 |
| `mapping_policy` | R4 | CAND | --- | DERIVED | provenance only (not in Fabric identity) | — | — | L3x | — | 2 |
| routing function, VC count, turn restrictions, per-class VC | R4 | DER | --- | DERIVED (LOCKED) | `VCAssignmentArtifact`, `VCResourceArtifact` | packet format, fabric | B | L3x | `vc_count > PLANE_C_MAX_VC` | 2 |
| buffer depths, packet limits | R4 | CAND | --- | DERIVED | `FabricCompileSettings` → `FabricArtifact` | fabric | B | L3x | — | 2 |
| affinity / anti-affinity / locality / fixed placement / mapping objective | R0 | — | --- | — | — | — | — | — | — | 4 |

### FABRIC / NOC

| Node | Real | Owner | Edit | Kind | Stored | Deps | Inv | Val | Unsup | Vis |
|---|---|---|---|---|---|---|---|---|---|---|
| `noc.topology_family` | R2/R3 | CI | TCU | PRF (default mesh) | `TopologyArtifact` | attachment, route, VC, fabric | B/D | L1n + L3x | topology: `gec`, `fat_tree`; routing: `torus` | 1 + 3 |
| `noc.radix` | R2 | CI | TCU | PRF | `TopologyArtifact` | fabric DAG | B | L1n + L3x (seats) | — | 1 |
| `noc.concentration` | R2 | CI | TCU | PRF (per-family default) | `TopologyArtifact` | fabric DAG | B | L1n + L3x | — | 1 |
| `noc.link_width` | R2 | CI | TCU | PRF (default 64) | `TopologyArtifact`, `PacketFormatArtifact` | fabric DAG | B | L1n | — | 1 |
| `noc.arbitration` | R2 | CI | TCU | PRF (baseline allocator) | `RouterBehaviorArtifact` | fabric | B | L1n + L3x (alias) | — | 1 |
| `noc.output_formats` | R1 | CI | TC- | META | request only | — | A | L1n | — | 1 + annotate |
| `noc.obfuscation_level` | R1 | CI | TC- | META | request only | — | A | L1n | — | 1 + annotate |
| `noc.rcu_enabled` | R3 | CI | TCU | CMT | request only | — | D | L3x | fabric (no RCU artifact) | 3 |
| `noc.mcast_groups` | R3 | CI | TC- | CMT | request only | — | D | L3x | fabric (no multicast artifact) | 3 |
| `noc.mcast_setup_cycles` | R3 | CI | TC- | CMT | request only | — | D | L3x | fabric (no multicast artifact) | 3 |
| NocConfig field classification | — | DER | --- | sentinel | `NOC_FIELD_CLASSIFICATION` | compile admission | — | L3x | unclassified field | 3 |

### MEMORY / PHYSICAL

| Node | Real | Owner | Edit | Kind | Stored | Deps | Inv | Val | Unsup | Vis |
|---|---|---|---|---|---|---|---|---|---|---|
| `address_map.ranges.{name,base,size}` | R2 | CI | TC- | CMT | `AddressDecodeArtifact` | fabric | B | L1n | — | 1 |
| `address_map.ranges[].target_agent_idx` | R2 | CI | TC- | CMT | `AddressDecodeArtifact` | fabric | B | L1n + L3d (indexes agents) | — | 1 |
| `physical.default_clock_freq_mhz` | R2 | CI | TC- | CMT | request → report | verdicts only | C | L1n (>0) | — | 1 |
| `physical.default_data_width` | R2 | CI | TC- | META | request → reports, UVM | output artifacts | A | L1n (≥8) | — | 1 |
| `physical.process_node_nm` | R2 | CI | TC- | META | request → reports | output artifacts | A | L1n (≥1) | — | 1 |
| `physical.num_power_domains` | R3 | CI | TC- | **RED** (derivable from `agents[].power_domain`) | request → refusal, `FabricArtifact` | fabric | D/B | L1n + L3x | fabric (>1) | 3 |

### PRODUCT + DESIGN-SPACE

| Node | Real | Owner | Edit | Kind | Stored | Deps | Inv | Val | Unsup | Vis |
|---|---|---|---|---|---|---|---|---|---|---|
| `fabric_preset` | R2 | PRD | TC- (not in draft) | CMT | `CompileIntentRecord` | `derive_compile_request` | E (pin) | L2 | — | 1 |
| `fabric_overrides` | R2 | PRD | TC- | CMT | `CompileIntentRecord` | derived request | E | L2 (normalization) | — | 1 |
| `candidate_policy` | R2 | PRD | TC- | CMT | `CompileIntentRecord` | candidate dispatch | E | L2 (required) | — | 1 |
| `intent_id` | R4 | PRD | --- | DERIVED | `CompileIntentRecord` | — | — | L2 (tamper) | — | 5 |
| `DomainParam` (searchable) | R2 | OPT | TC- | CMT | `OptimizationDefinition` | search | — | L1n (GUIDED names, finite, unique) | — | 1 |
| `Objective` | R2 | OPT | TC- | CMT | `OptimizationDefinition` | search | — | L1n (≥1, one per metric) | — | 1 |
| `Constraint` | R2 | OPT | TC- | CMT | `OptimizationDefinition` | search | — | L1n (one per metric, finite) | — | 1 |
| `method`/`budget`/`seed`/`selection` | R2 | OPT | TC- | CMT | `OptimizationDefinition` | search | — | L1n | `bayes`/`milp`/`sa`/… | 3 |
| fixed parameters | R0 | — | --- | — | — | — | — | — | — | 4 |
| `compiler_semantics_version` | R2 | PRD | --- | pin | `CompileIntent`, record | **all** designs | E | L2 | stale pin | 3 |

## §2.13 Findings recorded by the ten questions

1. **Two declared layers; the page edits one.** `candidate_policy`,
   `fabric_preset`, `fabric_overrides`, `intent_id` are declared product
   intent with no Studio draft home (§2.12, D1).
2. **`dirty` is identity, not effect.** Four R1 nodes change
   `design_hash` and no artifact (§2.12 Inv `A`).
3. **Requirements are fabric-inert.** Every requirement is Inv `C`; the
   certificate binds to `resolved_fabric_hash`, not `design_hash`.
4. **Two coherence checks are doc-computable but fire late:**
   `rank_count ≤ compute_instances` (compile, `mapping.py:181`) and
   `traffic_class ∈ derive_v3_traffic_classes` (report,
   `requirements.py:564`).
5. **Derivability is unmarked.** Six NocConfig knobs are `PRF` (the
   compiler already has a default) but render as required inputs.
6. **One derivable duplicate:** `physical.num_power_domains` vs
   `agents[].power_domain` — two authorities for one concept.
7. **Unsupported is staged.** `torus` fails at routing, `gec`/`fat_tree`
   at topology, `rcu`/`mcast` at fabric, multi-rank collectives at
   candidate, `PP` at lowering. `DesignEditor` collapses all to "refused".
8. **`StatusBadge` collapses distinct states:** `UNSUPPORTED` and
   `NOT_RUN` both render `muted` (`badges.tsx:19`).
9. **Only one refusal is visualized.** `.rcu-refusal` is hand-written for
   one of ten refusal conditions.
10. **Fail-closed completeness exists for one type only**
    (`check_noc_field_classification`).
11. **The capability registry already exists and is served**
    (`GET /api/v1/capabilities`) — consumed by Studio at `index.tsx:861`,
    not on Design.
12. **The visual primitive set is six**, not the eight ad-hoc ones in use;
    no primitive may be hand-authored for a single node.

## §2.14 Corrections found while verifying

Verification of §2.12 against call sites (not consumer lists) corrected
the following. They are recorded because each is a class of error the
Gate-1 question set exists to catch.

| Correction | Evidence |
|---|---|
| `model_family` is **not** generally supported. `intent_lowering.py:224` raises `UnsupportedSemantics` unless `model_family == dense_transformer`: *"MoE dispatch/combine, diffusion, CNN, and custom intents have no proven intent→collective mapping here."* **4 of the 5 values the UI offers refuse at lowering.** | `workload/intent_lowering.py:224-228` |
| `agents[].protocol` is **R1, not R2**. The only reads are validation (`compile_model.py:254`) and storage into the attachment endpoint (`attachment.py:149`). No consumer reads `interface.protocol`. It is still serialized into the attachment artifact, so changing it moves `attachment_hash` → `resolved_fabric_hash` → certificate **while changing nothing functional**. | `grep -rn '\.protocol'` |
| `agents[].{clock_domain,power_domain}` can **refuse**: `fabric_artifact.py:305-323` derives the domain sets and refuses >1 distinct value. They are `B/D`, not plain `B`. | `model/fabric_artifact.py:305` |
| **Empty `collectives` is invalid.** `intent_lowering.py:229` raises `InvalidInput`: *"intent declares no collectives — a fabric workload with no communication is under-specified."* The page has no collectives control, so any project not seeded from a workload template cannot lower. | `workload/intent_lowering.py:229` |
| **`WorkloadV3.world_size` and `FabricIntentView.world_size` are dead, broken properties.** Both do `from .presets import parallel_world_size` (`compile_model.py:2112, 2734`), but **`parallel_world_size` is defined nowhere in the tree**. They are never called (all `.world_size` call sites are `ParallelismShape` / `WavedParallelism`), which is why the missing import has never failed. | `grep -rn parallel_world_size` |

**Method note.** Three of the five corrections came from rows I had
derived from a *consumer file list* rather than from reading the call
site. Every row in §2.12 must therefore carry an evidence class:
`V` = read at the call site, `I` = inferred from a consumer list.
§2.12 is currently a mix. **The gate does not open until every row is
`V`.**

## §2.15 Enforcement — the gate as a mechanism

The rule "nothing goes into the UI until the questions are answered" is
only real if it fails closed, like the rest of this codebase. It is now
implemented:

1. **`docs/product/intent-ontology.yaml`** — machine-readable, 58 rows,
   one entry per declared field, carrying all ten answers, an
   `evidence: V|I` class, a `refusal_stage` for every refusal, and a
   `cite: file:line`.
2. **`scripts/check_intent_ontology.py`** — fails closed on: a declared
   field with no row; a missing answer; a citation that does not resolve;
   any row that is not `evidence: V`; `R4` marked editable; `PRF` with no
   default; a refusal with no stage; and **a field path the Studio Design
   editor writes that has no row**.
3. **Exit codes** distinguish the two failures: `1` = ontology invalid,
   `2` = ontology valid but the gate is closed (pending decisions),
   `0` = gate open.

Current status: **valid, gate closed (exit 2)** — 58 rows, 59 declared
fields covered, all `evidence: V`, 9 UI field paths admitted.

## §3 Derived ledger (display-only, no field exists)

Compiler-owned, in dependency order. None may appear as an editable
control on the Design page.

```text
MappingArtifact · AgentAttachmentArtifact · TopologyArtifact
RouteArtifact / ResolvedRoute · VCSeparation / VCAssignment
PacketFormatArtifact · RouterBehavior · AddressDecodeArtifact
FabricArtifact · ResolvedFabric  (terminal identity)
VerificationCertificate / obligations
```

Then, execution/lowering-owned: logical messages, physical traffic,
backend configuration, measurements, evidence, requirement verdicts.

**Rule:** if a value is in this ledger, the Design page may show it as
*read-only evidence with a link to its owning gate*, and only when it is
actually materialized. LOCKED values that do not exist for an uncompiled
draft render as absence, never as defaults.

---

## §4 Why the current page is structurally wrong (evidence)

| Defect | Evidence |
|---|---|
| The consumed contract is lossy | `contracts/srota/v1/design.view.schema.json` omits `collectives`, `dependencies`, `address_map`, `physical` — all legal v3 intent. |
| The contract is hand-duplicated in the UI | `DesignEditor.tsx` re-declares enums with `// model/compile_model.py::ModelFamily` comments. |
| Intent and compiled-fabric inspection are mixed in the editor | `E5 · NoC configuration` card embeds the LOCKED derived grid (routing/VC/turn restrictions/certificate) and the RCU refusal; the page also renders `FabricView` in the side rail. |
| The product layer is invisible | No UI for `fabric_preset`, `fabric_overrides`, `candidate_policy`; `intent_id` never shown. |
| The acceptance surface is buried | `RequirementV3.binding` — the design's pass/fail criterion — is a plain checkbox in a table. |

---

## §5 Open decisions (block Gate 2/3)

- **D1 — Which declared layer is the page's subject?** *(blocking)*
  (a) edit `CompileIntent` (preset + overrides + policy), matching product
  identity and `intent_id`; or (b) edit explicit `CompileRequestV3` with
  `CompileIntent` as a named-preset shortcut, defining how `intent_id` is
  derived. The ontology has two roots; the page must have one.
  **Evidence (§2.13.1):** the draft path (`product/service.py:670`)
  bypasses `CompileIntent` entirely and hardcodes `BASELINE_FABRIC_SETTINGS`
  inline (`orchestration.py:123`), so authority #3 is duplicated rather
  than dispatched.
- **D2 — Placement intent:** keep placement entirely derived
  (`MappingArtifact` + `MappingPolicy`), or create a declared
  affinity/placement contract. Today it is derived; `MappingPolicy` is
  "owned by candidate generation".
- **D3 — Design-space intent:** pull `OptimizationDefinition` under
  Design/Intent, or keep the Optimize page as its sole owner.
- **D4 — NOT-MODELLED domains** (§2 items): explicitly out of scope for
  this redesign, or new contracts? Each "new" converts this from a UI
  redesign into a compiler + contract redesign.
- **D5 — Contract widening:** confirm `DesignView` v2 must carry
  `collectives`, `dependencies`, `address_map`, `physical`, and the product
  layer, so the UI stops hand-mirroring `compile_model.py`. The DECLARED
  rows of §2.12 are the required field list.
- **D6 — Early validation:** move the two doc-computable coherence checks
  into the form (`rank_count ≤ compute_instances`; `traffic_class ∈
  derive_v3_traffic_classes`)? Both need no compiler.
- **D7 — Per-type classification sentinel:** require every declared type
  (`WorkloadV3`, `RequirementV3`, `Agent`, `PhysicalContext`) to publish a
  reality/kind classification with a fail-closed sentinel, as `NocConfig`
  already does? This is a compiler change, out of UI scope.
- **D8 — Visual primitive set:** freeze the six primitives of §2.12 as the
  closed vocabulary for Gates 2–6, and forbid per-node hand-authored
  primitives (`.rcu-refusal`, `.locked-grid`)?

## §5.1 Evidence summary (per decision)

| Decision | Blocking evidence |
|---|---|
| D1 | two declared layers with different identities; draft bypasses the product layer |
| D6 | `mapping.py:181` and `requirements.py:564` enforce document-local rules at compile/report |
| D7 | `check_noc_field_classification()` is the only completeness guard |
| D8 | `.rcu-refusal` covers 1 of 10 refusals; `.locked-grid` covers 4 of ~12 derived objects |

---

## §6 Gate 1 exit criteria

Gate 1 is complete when:

1. every concept the page may show maps to exactly one of DECLARED /
   DERIVED / NOT-MODELLED, with a citation; — **MET** (§2.1–§2.11, §2.12)
2. **every §2.12 row carries `evidence: V`** (read at the call site, not
   inferred from a consumer list); — **MET** (`check_intent_ontology.py`)
3. D1–D8 are decided and recorded here; — **OPEN** (D1 blocking)
4. the widened `DesignView` field list is enumerated (Gate 3 consumes it);
   — **MET** (the DECLARED rows of §2.12)
5. no DECLARED row is missing a tier, and no DERIVED row is reachable as
   an editable control; — **MET** (§2.12, enforced by the checker)
6. the six-primitive visual vocabulary is frozen; — **PENDING D8**
7. `intent-ontology.yaml` + `check_intent_ontology.py` exist and pass, so
   the gate is mechanical rather than remembered. — **MET** (exit 2:
   valid, gate closed)

Only then does Gate 2 (flow) begin. **Nothing enters `apps/studio` before
criteria 2, 3, 6 and 7 are met.**
