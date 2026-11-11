# STAGE 1 — Schema + compiler enforcement scope (family-agnostic, mesh8x8 as worked example)

Status: scoping doc only — no production code is changed by this document.
Audience: compiler/schema implementers + operator sign-off.
Goal: turn a per-tile intent (agent protocol, ordering, permission, domain) into previously-implicit
research-RTL facts that the compiler can check, reject, or warn about — without forking the schema
per topology family.

mesh8x8 is the *worked example and acceptance fixture*, not the design's home. Every field proposed
below lives on the shared `CompileRequestV4` / agent-descriptor layer so the other 11 required
families (`product/rtl_prototypes.py:19-34`, `_REQUIRED` at `:35`) reuse it unchanged.

Read for this doc (all paths repo-relative unless noted):

- `tracks/t3-topology/dse/veritx_dse/model/compile_request_v4.py` — v4 root, strict keys, migration
- `tracks/t3-topology/dse/veritx_dse/model/topology_intent.py` — `MeshIntent` (`:18-41`), `_FIELDS` (`:403`)
- `tracks/t3-topology/dse/veritx_dse/model/compile_model.py` — `Agent` (`:202`), `AddressMap` (`:631`),
  `derive_vc_assignment` (`:804`), `derive_vc_assignment_v3` (`:2940`), `derive_vc_assignment_artifact_v3` (`:3002`),
  `FabricIntentView` / `fabric_intent_view` (`:2659` / `:2725`)
- `tracks/t3-topology/dse/veritx_dse/model/noc_controls.py` — `NocControls` (`:28`), strict load (`:120`)
- `tracks/t3-topology/dse/veritx_dse/model/address_decode.py` — `AddressDecodeEntry` (`:117`),
  `_validate_entries` (`:204`), `derive_address_decode` (`:535`)
- `tracks/t3-topology/dse/veritx_dse/application/fabric_compiler.py` — `STAGES` (`:16`), `FabricCompiler.compile` (`:233`),
  `_compile_v5` (`:164`)
- `tracks/t3-topology/dse/veritx_dse/compiler/canonical.py` — `CompileStage` (`:58`), `ADDRESS_DECODE` (`:380`), `VC` (`:399`)
- `tracks/t3-topology/dse/veritx_dse/product/catalog_evaluation.py` — RTL predicate (`:105-131`), `rtl_support` (`:246`), `compiled_facts` (`:388`)
- `tracks/t3-topology/dse/veritx_dse/product/rtl_prototypes.py` — 12-row inventory (`:19-34`), `prototype_for_family` (`:145`)
- `apps/studio/prototype/src/DraftEditor.tsx` — agent table (`:524-543`), agent kinds (`:43`), no protocol/ordering editors today

> Inventory note: `/tmp/opencode/m5-rtl/mesh8x8-perrouter/` was empty in the environment where this
> doc was written (verified 2026-11-09). §1 baseline numbers are taken from the task brief and must be
> re-verified against that inventory before implementation; they are flagged where unverified.

---

## 1. Current mesh8x8 baseline (worked example)

Derived from the brief inventory summary + `MeshIntent(side_length=8, concentration=1)`
(`topology_intent.py:18-41`) + `catalog_for` sizing (`catalog_evaluation.py:60-61`, mesh `concentration=1`).

| Fact | Value (brief) | How to re-verify |
|---|---|---|
| Routers | 64 (8×8, one seat/router) | `router_edges.tsv` / `terminal_map.tsv` under `mesh8x8/` (`rtl_prototypes.py:50-51`) |
| Links | 224 directed = 112 undirected (56 horizontal + 56 vertical, reciprocal, point-to-point) | same; count is derived, not stated in brief |
| VCs | 4 | `CandidateNoCTop.v` header/parameters; see §1.1 conflict |
| Buffers | 15 (per-router buffer depth units) | `CandidateNoCTop.v` parameters |
| Mask | `4096/0` (address/controller mask — semantics unverified; do not build on it) | top-level parameters of `CandidateNoCTop.v` |
| Payload | **not stated in brief** — payload width must be read from `CandidateNoCTop.v` and recorded before coding | `data_width` on the agent (`compile_model.py:214`, default 256) is a different fact |
| Top file | `CandidateNoCTop.v`, sha prefix `b1558c43…` | `sha256sum` of the artifact served by `rtl_prototypes.py:189 stream_artifact` |
| Partition | monolithic build OOMs; per-router partition = **65 partitions** (64 routers + 1 top) | the partition script/checkpoint log in `mesh8x8-perrouter/` |

### 1.1 The conflict STAGE 1 exists to surface (not hide)

- Research RTL (mesh8x8) is a **4-VC** design. Product RTL emitter is **2-VC free/escape**
  (`RTL_EMITTER_VC_COUNT = 2`, `catalog_evaluation.py:119`).
- The compiler's own derivation for mesh DOR is *not* 4: no BLOCKING cycles → `derive_vc_count = 1`,
  routing `dim_order` (`compile_model.py:488-507, 822-825`). `derive_vc_assignment_v3` adds fabric
  floors (dateline/MECS/hybrid/shape/rank, `:2958-2975`) — mesh DOR has none.
- `rtl_support` therefore: fabric VC 4 > 2 → `UNSUPPORTED_VC_SCHEME` (`catalog_evaluation.py:301-309`);
  router count 64 passes the 2–64 bound (`:337-342`, inclusive edge). The catalog's `compiled_facts`
  (`:388-423`) calls this *preview* support, not finalization.
- **Implication:** "per-router RTL for mesh8x8" today means *research* per-router emission
  (65 partitions), not product-emitter emission. STAGE 1 must make that distinction a compiler
  outcome (typed refusal + owner stage, per `rtl_support`'s pattern), never a silent 4→2 down-conversion.
  This is Decision D1 (§9).

### 1.2 What already exists and must be extended, not replaced

1. `CompileRequestV4` (`compile_request_v4.py:59-114`): frozen, `topology` REQUIRED (`:68, 84-89`),
   `_TOP_V4_KEYS` strict-allowlist (`:40-47`), `from_dict` fail-closed (`:212`), `DESIGN hash identity`
   via `canonical_dict` (`:181-206`). New fields must enter `_semantic_dict` (`:149-165`) or they do
   not exist as far as identity is concerned.
2. `Agent` (`compile_model.py:202-257`): `kind/count/data_width/addr_width/protocol/clock_domain/
   power_domain` + stamped-IP guard (`:232-257`). `protocol` is a free `str` (`:227`) — no closed
   vocabulary, no per-instance variation (one row = `count` uniform instances).
3. `AddressRange`/`AddressMap` (`:590-735`): `base/size/target_agent_idx` + FIXED_INSTANCE/STRIPED
   selection (`:604-628`); `validate_no_overlaps` (`:722-735`) is pairwise-sorted, name-bearing.
4. `DependencyGraph` (`:416-486`) + `derive_vc_assignment(_v3)` (`:804, :2940`) +
   `derive_vc_assignment_artifact_v3` (`:3002-3120`, incl. multi-class full-envelope rewrite
   `:3067-3075` and hybrid exact-envelope rule `:3076-3094`).
5. `FabricCompiler` stages `INVENTORY…BUNDLE` (`fabric_compiler.py:16-19`) over
   `derive_stages_v3` (`compiler/orchestration.py:136`) and `CompileStage` (`canonical.py:58-72`).
   `_compile_v5` (`fabric_compiler.py:164-231`) is the template for owning-stage refusal: unsupported
   extension → `UNSUPPORTED` + `stopped_at_stage`, never down-projected.
6. Studio: `DraftEditor.tsx` agents table has kind/count/width/clock/power, `protocol` is display-only
   (`:538`); no ordering/permission/domain editors; address ranges (`:546-556`) have no permission or
   window-policy column; dependencies (`:558-567`) are free-form `source/target/kind` strings.

---

## 2. Design principles (generalization)

P1. **One shared intent layer, zero family forks.** Per-tile agent facts (protocol, ordering,
    permission, clock/power domain refs, traffic-class VC) are fields on the *shared* request/agent
    layer. `MeshIntent` (`topology_intent.py:18`) gains **nothing** — the parser's strict allowlist
    (`:464-468`, `_FIELDS["mesh"]` at `:404`) must keep rejecting them if they land on topology.
P2. **Deep modules, simple interfaces** (§4): each concern is a small pure function
    `struct-in → (ok, reason)` with no callbacks/registry lookups in the hot path. Derivation, cycle
    search, and cross-checks are hidden inside; callers pass one frozen struct.
P3. **Topology variation is 2-dimensional only:** (a) a routing-law object (DOR / dateline / MECS
    slice / NCA / shape / rank / hybrid phase — see §6), (b) partition parameters (side, concentration,
    terminals/router, planes). Everything else is family-agnostic.
P4. **Fail-closed, additive, hash-honest.** Unknown keys refuse (`compile_request_v4.py:222`,
    `noc_controls.py:132-136`); absent new fields ≡ old design (byte-identical serialization, see
    the `traffic_profiles` precedent `compile_request_v4.py:139-143` and `NocControls.to_dict`
    `noc_controls.py:90-93`); present fields enter `canonical_dict` so identity names them.
P5. **Refusal names an owner stage.** Follow `_v5` (`fabric_compiler.py:218-231`): `UNSUPPORTED`/
    `INVALID` + `stopped_at_stage` from the `CompileStage` vocabulary. A check that cannot name a
    stage does not ship.

---

## 3. Proposed `CompileRequestV4` deltas (shared layer)

Two placement options; **recommended: (A)** — new top-level `agent_intents` + `traffic_policy`
blocks beside `agents`/`dependencies`, because `Agent` is frozen and shared by v2/v3/v4
(`compile_model.py:202`, `CompileRequestV3` `:2096`, `CompileRequestV4` `:66`). Mutating `Agent`
changes three schemas' hashes at once. Option (B) (extend `Agent`) is listed only for the operator
to reject.

### 3.1 New frozen dataclasses (sketch — all new fields `Optional` for backward compat)

```python
# model/agent_intent_v4.py  (new; NOT topology_intent.py)
from dataclasses import dataclass
from enum import Enum

class ProtocolFamily(Enum):           # closed vocabulary; Agent.protocol str is NOT this
    AXI5 = "axi5"; CHI = "chi"; TILELINK = "tilelink"; CUSTOM = "custom"

class OrderingMode(Enum):
    STRONG = "strong"; RELAXED = "relaxed"; RAW = "raw"  # RAW = no ordering promise

@dataclass(frozen=True)
class AgentIntentV4:                  # one row per Agent GROUP (index = agents[i])
    agent_idx: int                    # REQUIRED when row present
    protocol: ProtocolFamily | None = None      # None = inherit Agent.protocol literal
    ordering: OrderingMode | None = None
    max_outstanding: int | None = None          # >=1 when present
    split_at: int | None = None                 # burst split threshold, >=1
    clock_domain: str | None = None             # ref must exist / == Agent.clock_domain if set
    power_domain: str | None = None
    # permission is per (group -> address range), enforced by Address&Permission module:
    #   permission_windows: tuple[PermissionWindow, ...] = ()   # absent = no per-tile claim

@dataclass(frozen=True)
class PermissionWindow:
    address_range: str                # AddressRange.name it constrains
    readable: bool = True; writable: bool = True
    # False/False = declared no-access window (compiles; emitters must not route writes there)

@dataclass(frozen=True)
class TrafficClassVC:                 # per-traffic-class desired VC (validated, §5.3)
    traffic_class: str
    vc: int                           # 0 <= vc < derived vc_count (checked post-derivation)
    # NOTE: desired, not authority — derive_vc_assignment_v3 stays the authority;
    # mismatch = compile INVALID (§5.3), never silent override.

@dataclass(frozen=True)
class TrafficPolicyV4:
    agent_intents: tuple[AgentIntentV4, ...] = ()        # index-aligned to agents
    traffic_class_vcs: tuple[TrafficClassVC, ...] = ()    # absent = derived default (§5.3)
```

`CompileRequestV4` gains (both default-empty, both enter `_semantic_dict`/`from_dict` like
`traffic_profiles` does at `compile_request_v4.py:234-270`):

```python
    agent_intents: tuple[AgentIntentV4, ...] = ()
    traffic_policy: TrafficPolicyV4 = field(default_factory=TrafficPolicyV4)
    # _TOP_V4_KEYS += {"agent_intents", "traffic_policy"}
    # schema_version stays 4, compiler_semantics_version stays 4 (additive, absent≡empty)
```

Required-vs-optional rule: nothing in the new blocks is REQUIRED at the top level; *within* a
present row, `agent_idx` is required, `max_outstanding >= 1`, `split_at >= 1`,
`0 <= vc < 16` (`PLANE_C_MAX_VC`, `core/constants.py:71`); unknown keys refuse at the row level
(same `_strict_keys` pattern, `compile_model.py:81-87`). A present-but-otherwise-empty
`AgentIntentV4(agent_idx)` is legal (explicit "no per-tile intent").

### 3.2 JSON example (mesh8x8 worked example — 64 tiles as one group)

```json
{
  "schema_version": 4, "compiler_semantics_version": 4,
  "topology": {"kind": "mesh", "side_length": 8, "concentration": 1},
  "agents": [{"kind": "compute_tile", "count": 64, "data_width": 256,
              "addr_width": 64, "protocol": "AXI", "clock_domain": "noc_clk",
              "power_domain": "pd0"}],
  "address_map": {"ranges": [
    {"name": "dram", "base": 0, "size": 68719476736, "target_agent_idx": 0}]},
  "agent_intents": [
    {"agent_idx": 0, "protocol": "axi5", "ordering": "strong",
     "max_outstanding": 16, "split_at": 64,
     "clock_domain": "noc_clk", "power_domain": "pd0"}],
  "traffic_policy": {"traffic_class_vcs": [
    {"traffic_class": "data", "vc": 0}, {"traffic_class": "control", "vc": 1}]},
  "dependencies": [{"source": "data", "target": "control", "kind": "ordering"}],
  "design_hash": "…", "guardrail_hash": "…"
}
```

Note the deliberate gap this exposes: `protocol: "AXI"` (legacy literal) vs `protocol: "axi5"`
(closed enum). Coexistence rule — enum present wins; literal retained for round-trip. Flagged as D2.

`TrafficProfile` (`compile_model.py:1731-1774`, v4-only `workload.traffic_profiles` at
`compile_request_v4.py:234-254`) already carries `src_rank/dst_rank/traffic_class`; the new
`traffic_class_vcs` must key off `derive_v3_traffic_classes` (`compile_model.py:2559-2576`) so
collective/coherence/profile classes share one registry.

---

## 4. Deep modules — narrow interfaces (the whole STAGE 1 architecture)

Each module: frozen input struct, `(ok: bool, reason: str | None, findings: tuple)` out.
No module sees `CompileRequestV4` — callers project first (`fabric_intent_view`,
`compile_model.py:2725`, is the existing projection seam; extend its view struct, don't bypass it).

### 4.1 M1 — `address_permission` (Address & Permission)

```python
@dataclass(frozen=True)
class AddressPermissionInput:
    ranges: tuple[AddressRange, ...]          # compile_model.py:590
    windows: tuple[PermissionWindow, ...]     # §3.1
    attachment_hash: str                      # AgentAttachmentArtifact identity
    unmatched_policy: str                     # "ERROR" (UnmatchedAddressPolicy.ERROR, address_decode.py:576)

@dataclass(frozen=True)
class Verdict: ok: bool; reason: str | None; findings: tuple[str, ...] = ()

def check_address_permission(inp: AddressPermissionInput) -> Verdict: ...
def build_decode_entries(inp: AddressPermissionInput) -> tuple[AddressDecodeEntry, ...]: ...
    # Address&Permission owns overlap + window coverage; decode table stays a projection
    # (AddressDecodeEntry: address_decode.py:117; _validate_entries overlap rule: :220-224).
```

Owns: range overlap/exclusivity, singleton-vs-STRIPED selection legality
(`AddressRange.__post_init__`, `compile_model.py:615-628`; multi-instance-without-policy refusal,
`address_decode.py:563-566`), initiator→target permission coverage (every TrafficProfile
`(src,dst,class)` must be permitted by the window naming `dst`'s range; write to read-only
window = INVALID with `stopped_at_stage=ADDRESS_DECODE`).

### 4.2 M2 — `ordering_vc` (Ordering & VC assignment)

```python
@dataclass(frozen=True)
class OrderingVCInput:
    graph: DependencyGraph                    # compile_model.py:416
    desired: tuple[TrafficClassVC, ...]       # §3.1 (may be empty)
    routing_law: "RoutingLaw"                 # §6 — the ONLY family-specific input
    vc_max: int = 16                          # PLANE_C_MAX_VC

def check_ordering_vc(inp: OrderingVCInput) -> Verdict: ...   # legality gate (fail-fast)
def derive(inp: OrderingVCInput) -> "VCAssignment": ...       # single authority, see below
```

Single authority = `derive_vc_assignment_v3` (`compile_model.py:2940-3000`) *parameterized by law*:
floors from `multidrop_degree` (`:2843`), `dateline_vc_floor` (`:2882`), `shape_policy_vc_floor`
(`:2899`), `rank_policy_vc_floor` (`:2921`), `hybrid_policy_vc_floor` (`:2873`) become methods on the
routing-law object instead of `kind=="gec"/"srota"/"ring_native"` if-chains. `check_ordering_vc` runs
*before* derivation: desired VC ≥ derived count, desired VC isolates a STRONG class from a BLOCKING
cycle victim, 2 classes sharing a VC across a BLOCKING edge, etc. (§5.3). Cycle search
(`find_cycles`, `:451`) and artifact binding (`derive_vc_assignment_artifact_v3`, `:3002`) stay inside.

### 4.3 M3 — `clock_power_cdc` (Clock, Power & CDC)

```python
@dataclass(frozen=True)
class ClockPowerInput:
    endpoints: tuple[EndpointDomain, ...]     # (agent_idx, clock_domain, power_domain)
    crossings: tuple[Crossing, ...]           # declared (src_domain, dst_domain) edges
    # FabricArtifact today: >1 endpoint domain = hard UNSUPPORTED (fabric_artifact.py:256-262)

def check_clock_power_cdc(inp: ClockPowerInput) -> Verdict: ...
def cdc_insertion_points(inp: ClockPowerInput) -> tuple[str, ...]: ...  # endpoint/attachment names
```

Owns domain-ref integrity (agent intent domain must exist and match `Agent.clock_domain`), the
multi-domain gate (currently an unconditional refuse — STAGE 1 keeps refuse, adds *named* insertion
points so a later stage can materialize rather than re-derive), and power-domain count vs
`PhysicalContext.num_power_domains` (`compile_model.py:745`). Backends that refuse CDC today
(`backend/native_coupled.py:115-121`, `fabric_artifact.py:256`) keep refusing — the module only
makes the refusal structured and staged.

### 4.4 M4 — `protocol_adapter` (Protocol Adapter)

```python
@dataclass(frozen=True)
class ProtocolInput:
    intents: tuple[AgentIntentV4, ...]
    data_width: int; addr_width: int          # from Agent (compile_model.py:214-215)
    protocol_vocab: tuple[str, ...]           # closed: ("axi5","chi","tilelink","custom")

def check_protocol(inp: ProtocolInput) -> Verdict: ...   # vocabulary + width legality
def adapter_requirements(inp: ProtocolInput) -> tuple[str, ...]: ...  # e.g. ("burst-split",)
```

Owns the closed vocabulary (replacing free-string `Agent.protocol`, `:227`), compatibility of
`max_outstanding`/`split_at` with the family (AXI5 burst splitting yes; CHI/TileLink constrain
different knobs — unknown combination = INVALID, not ignored), and the `adapter_requirements`
tuple that a hypothetical emitter consumes. No adapter RTL in STAGE 1 (§7).

### 4.5 Wiring (only addition to the compiler)

- `FabricCompiler.compile` (`fabric_compiler.py:233`): after `derive_stages_v3` succeeds and before
  `verify_compiled_fabric` (`:310`), run M1→M2→M3→M4 on the `fabric_intent_view` projection.
  First `INVALID` verdict → `Compilation(status="INVALID", stopped_at_stage=<stage>, error=reason)`
  following `:294-309`; first `UNSUPPORTED` (multi-domain CDC, adapter family) → same channel with
  `UNSUPPORTED`, following `_compile_v5` (`:218-231`).
- Stage names: M1→`ADDRESS_DECODE`, M2→`VC`, M3→`ATTACHMENT` (endpoints are placed there,
  `canonical.py:447`), M4→`PACKET_FORMAT` (`:66`). No new stage names in STAGE 1.

---

## 5. Compiler checks — fail vs warn

`INVALID` = compilation produces no bundle; `UNSUPPORTED` = no materializer exists for a legal
intent; `WARN` = compiles, finding recorded on the Compilation (extend `Compilation`,
`fabric_compiler.py:54-82`, with a `findings` tuple or reuse certificate obligations).

| # | Check | Verdict | Owner stage | Existing code path to extend |
|---|---|---|---|---|
| 5.1 | Address overlap / duplicate semantic range | INVALID | `ADDRESS_DECODE` | `_validate_entries` (`address_decode.py:204-224`); note `AddressMap.validate_no_overlaps` (`compile_model.py:722`) is a *different*, name-bearing checker — reconcile, don't duplicate wording |
| 5.2 | Multi-instance target without FIXED_INSTANCE/STRIPED; STRIPED unaligned/non-power-of-2 | INVALID | `ADDRESS_DECODE` | `AddressRange.__post_init__` (`compile_model.py:615-628`); `derive_address_decode` (`address_decode.py:552-566`) |
| 5.3 | Initiator→target permission mismatch (write to read-only window; unpermitted TrafficProfile pair) | INVALID | `ADDRESS_DECODE` | **new** — needs `TrafficProfile` registry (`compile_model.py:1731`) joined to M1 windows |
| 5.4 | Desired `traffic_class_vc` ≥ derived count, or isolates STRONG class onto cycle-victim VC | INVALID | `VC` | **new gate** in M2 before `derive_vc_assignment_v3` (`compile_model.py:2940`); exact-envelope precedent: hybrid rule (`:3076-3094`) |
| 5.5 | BLOCKING cycle with VC count > 16 | INVALID | `VC` | `validate` (`compile_model.py:1304-1309`), `derive_vc_assignment_v3` raise (`:2976-2980`) — keep both, gate uses M2's derived count |
| 5.6 | VC-scheme vs product emitter (4-VC mesh vs 2-VC emitter) | UNSUPPORTED at *finalization*; WARN at catalog preview | `RTL generation` (non-compile stage, per `rtl_support`) | `rtl_support` (`catalog_evaluation.py:246-347`), `compiled_facts` (`:388`) — STAGE 1 adds no new emitter; it only stops `compile` from implying servability |
| 5.7 | Endpoint spans >1 clock domain without declared crossing | UNSUPPORTED | `ATTACHMENT` | `FabricArtifact` gate (`fabric_artifact.py:256-262`); M3 names insertion points |
| 5.8 | Agent intent domain ref unknown, or ≠ `Agent.clock/power_domain` | INVALID | `ATTACHMENT` | `Agent.__post_init__` domain checks (`compile_model.py:228-231`) extended to intents |
| 5.9 | Unknown protocol family; `split_at` on a family that has no burst split | INVALID | `PACKET_FORMAT` | **new** M4 gate over `Agent.protocol` (`compile_model.py:227`) |
| 5.10 | `max_outstanding` present but no STRONG/RAW ordering declared | WARN | `PACKET_FORMAT` | **new** — ordering default ambiguity; warn, don't invent a default (migration-refuses-not-guesses law, `compile_request_v4.py:36-38`) |
| 5.11 | `num_power_domains` < distinct power domains referenced | WARN (INVALID if a domain ref is unknown) | `ATTACHMENT` | `PhysicalContext` (`compile_model.py:737-758`), M3 |
| 5.12 | Cross-family: dateline/MECS/shape/rank floor > derived count | INVALID | `VC` | existing floors (`compile_model.py:2958-2975`) moved behind routing law (§4.2) — behavior identical for existing drafts |

---

## 6. The 11 other families reuse the modules unchanged

Only these two things vary per family: the **routing-law object** (implements §4.2's floors +
`_routing_for_cycle_structure`, `compile_model.py:2831-2841`) and **partition parameters**.

| Family (intent kind) | Routing law | VC floor source today | Partition variation |
|---|---|---|---|
| `mesh` (`topology_intent.py:18`) | DOR, `dim_order`/`dor` | none (graph only) | side_length, concentration=1 |
| `torus` (`:62`) | dateline | `dateline_vc_floor` (`compile_model.py:2893`) | odd side (`catalog_evaluation.py:63`) |
| `concentrated_mesh` (`:44`) | DOR | none | side, concentration=4 (`catalog_evaluation.py:62`) |
| `ring_native` (`:85`) | dateline 1-D | `dateline_vc_floor` | router_count = endpoints (`catalog_evaluation.py:75`) |
| `gec` MECS (`:275`) | tap-slice | `multidrop_degree` (`:2843`) + full-envelope rewrite (`:3067`) | `o*d == k-1` law (`topology_intent.py:329-336`) |
| `gec` hybrid (`:275`) | X/Y phase+tap | `hybrid_policy_vc_floor` (`:2873`), exact-envelope (`:3076`) | same `o*d` law |
| `srota` | shape / rank | `shape_policy_vc_floor` (`:2899`), `rank_policy_vc_floor` (`:2921`) | planes, `vc_policy` (already a typed knob) |
| `flatfly` (`:170`) | DOR-ish flat | none | per-dim radix × dims |
| `fattree` (`:240`) | (native nca — stays behind law interface; **NCA is not in the current tree** as a named function — verify before claiming) | none | switch_radix, level_count |
| `tree4_native` (`:103`), `qtree_native` (`:153`), `fly_native` (`:128`) | native-only fixed (4,3) | none | none — fixed `radix=4, levels=3` (`topology_intent.py:144, 163`) |

Acceptance rule for generalization: for each of the 12 rows, the *same* `CompileRequestV4` JSON
(with that family's `topology` block) must pass M1–M4 checks with only the law object swapped.
A family that needs an M1–M4 change is a STAGE 1 bug, not a family exception.

---

## 7. Non-goals (explicit)

1. **No physical STA / congestion / clock-tree work.** No timing closure, no placement, no
   `PhysicalContext` semantics change beyond §5.11. `default_clock_freq_mhz` stays an assumption.
2. **No hybrid credit contract.** No credit-cycle, allocator, or router-behavior redesign; the
   certified 2-VC free/escape emitter (`catalog_evaluation.py:118-119`) is a fixed fact, not a
   variable. STAGE 1 describes VCs; it does not re-derive the credit scheme.
3. **No change to the 12 fixed M5 instances.** The `rtl_prototypes.py:19-34` rows, their
   `CandidateNoCTop.v` artifacts, and their `manifest.tsv`/`verification.json` evidence are read-only
   references. STAGE 1 adds schema + checks; it does not regenerate, re-verify, or re-qualify any
   of the 12 (their `proof_status` stays `UNVERIFIED`, `:128`). In particular mesh8x8's 4-VC/65-partition
   artifact is *described*, not re-emitted.
4. **No adapter RTL, no CDC hardware, no permission hardware.** M3/M4 emit insertion-point/
   requirement *lists*; nothing synthesizes a synchronizer, level shifter, or protocol shim.
5. **No Studio UI beyond pass-through.** `DraftEditor.tsx` must round-trip the new blocks opaquely
   (preserve on save) but gets no new editors in STAGE 1; §8 only requires it not to strip them.
6. **No migration of existing drafts' meaning.** Anything that changes an existing design's
   `design_hash` is out; §8.4 gates this.

---

## 8. Test plan

All tests in `tracks/t3-topology/dse/tests/` (following existing placement); names are the contract.

### 8.1 Schema round-trip
- `test_stage1_schema_roundtrip.py::test_mesh8x8_example_roundtrip` — §3.2 JSON →
  `CompileRequestV4.from_dict` → `to_dict()` byte-identity incl. `design_hash` stability
  (`compile_request_v4.py:167-206`). Parametrized over the 12 family rows (§6): same body,
  family `topology` swapped, hash differs by topology only (`canonical_dict` uses
  `topology.scientific_dict()`, `compile_request_v4.py:189`).
- `test_stage1_schema_roundtrip.py::test_absent_is_empty` — omit `agent_intents`/`traffic_policy`
  entirely: loads, hash equals pre-STAGE-1 hash of the same body, `to_dict` emits no new keys
  (absent≡empty precedent `noc_controls.py:90-93`).
- `test_stage1_schema_roundtrip.py::test_strict_keys_refuse` — typo'd key in any new row
  (`agent_intenets`, `traffic_class_vcs[].Vc`) → `CompileRequestV4SchemaError`
  (`compile_request_v4.py:33-34`).

### 8.2 Refusal cases (each: `INVALID`/`UNSUPPORTED` + named `stopped_at_stage`, no bundle)
- `test_stage1_refusals.py` §5.3 permission mismatch: TrafficProfile write to read-only window.
- §5.2 multi-instance range without selection policy; STRIPED unaligned.
- §5.4 desired VC ≥ derived count; STRONG class isolated onto cycle-victim VC.
- §5.5 BLOCKING cycles needing >16 VCs (synthetic 17-cycle graph; `PLANE_C_MAX_VC`).
- §5.7 two clock domains, no declared crossing → `UNSUPPORTED/ATTACHMENT`.
- §5.9 `protocol: "axi99"`; `split_at` with `protocol: "chi"`.
- §5.1 overlap: dense 64-tile ranges with one duplicated window (mesh8x8-shaped fixture) → overlap
  names both ranges (mirror `address_decode.py:220-224` message format).

### 8.3 Module isolation (deep-module contract)
- `test_stage1_modules.py` — M1–M4 each imported standalone: no `CompileRequestV4`,
  no `topology_intent` symbols in their transitive imports (assert via `sys.modules` snapshot or
  an import-lint rule). Pure-function property: same input struct twice → identical `Verdict`.

### 8.4 Compatibility (backward compat for drafts without new fields)
- Golden hashes: re-run the existing v4 test corpus; any `design_hash` change for a document
  without the new blocks is a failure (P4).
- `migrate_v3_to_v4` (`compile_request_v4.py:328-439`) unchanged; a migrated v3 mesh draft with no
  intents must compile to the same bundle as today (`FabricCompiler.compile`,
  `fabric_compiler.py:233`).
- Catalog: `catalog_for` (`catalog_evaluation.py:48-87`) unchanged; `compiled_facts` (`:388`)
  on the 12 rows must produce identical `rtl_support` codes (incl. mesh `UNSUPPORTED_VC_SCHEME`).
- Studio: `DraftEditor` save round-trip preserves unknown-to-UI blocks verbatim
  (`merged()`, `DraftEditor.tsx:241-260`, spreads `...draft` — assert the new keys survive).

---

## 9. Decisions needing operator sign-off

- **D1 (blocks §1.1):** Is mesh8x8's per-router target the *research* 4-VC emitter (65 partitions)
  or must STAGE 1 force a 2-VC product-emitter-compatible variant? STAGE 1 as scoped refuses to
  silently down-convert (4→2) and surfaces `UNSUPPORTED_VC_SCHEME`. Sign-off required before any
  emitter work exists.
- **D2:** Coexistence of legacy `Agent.protocol` free string (`compile_model.py:216,227`) with the
  closed `ProtocolFamily` enum — enum-wins rule (§3.2) vs. requiring `from_dict` to reject documents
  that set both inconsistently? Affects whether existing `protocol: "AXI"` drafts keep loading unchanged.
- **D3:** Placement (A) new top-level blocks vs. (B) extending frozen `Agent`: (A) is recommended
  (§3.1) because `Agent` is shared by v2/v3/v4 — but it changes `_TOP_V4_KEYS` and every strict
  reader. Confirm (A) before implementation.
- **D4:** Desired-vs-authoritative VC semantics: is a `traffic_class_vcs` mismatch INVALID (§5.4)
  or a WARN-with-override? INVALID is recommended (fail-closed); override would reintroduce the
  silent-substitution failure `rtl_support` exists to prevent (`catalog_evaluation.py:282-300`).
- **D5:** CDC scope: STAGE 1 keeps multi-domain fabrics UNSUPPORTED (§5.7) with named insertion
  points, vs. accepting declared crossings as compiles-with-warnings. UNSUPPORTED is recommended —
  no synchronizer hardware exists to point at (§7.4).

## Appendix — file-change map (implementation checklist)

| File | Change |
|---|---|
| `model/agent_intent_v4.py` (new) | §3.1 dataclasses + strict `from_dict`/`to_dict` (model for `noc_controls.py:120-155`) |
| `model/compile_request_v4.py` | 2 new fields (`:59`), `_TOP_V4_KEYS` (`:40`), `_semantic_dict` (`:149`), `from_dict` parse (`:234-285` pattern), hash safety (§8.1) |
| `model/address_permission.py`, `model/ordering_vc.py`, `model/clock_power_cdc.py`, `model/protocol_adapter.py` (new) | M1–M4 (§4) |
| `model/compile_model.py` | extract VC floors behind routing-law object (`:2843-2937`, `:2958-2975`); extend `FabricIntentView` (`:2659`) |
| `application/fabric_compiler.py` | wire M1–M4 after `derive_stages_v3`, before `verify_compiled_fabric` (`:269, :310`); `Compilation` findings (`:54`) |
| `model/topology_intent.py` | **no change** — §2/P1; reject new fields on `MeshIntent` via existing strict allowlist (`:464-468`) |
| `apps/studio/prototype/src/DraftEditor.tsx` | pass-through only (§7.5) |
