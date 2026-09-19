# SROTA_FABRIC_SEMANTICS_V1

**Wave:** B3.0 (audit + specification; no implementation)
**Repository:** `Anmol-S314/veritx-research`
**Branch:** `audit/wave-b-intent-identity`
**Base SHA:** `c69e4ca78691a71ded094f67419b64cb0454c260`
**Status:** For architecture review
**Supersedes:** nothing (first fabric semantics specification)
**Depends on:** B1 (`design_hash`), B2 (`NodeInventory`, `MappingArtifact`)

This document defines what a resolved Srota fabric *is* before any B3 code is
written. It starts from hardware semantics and maps existing code onto them —
not the reverse. Where current code is narrower than the product contract, the
narrowness is recorded as *implementation support*, not used to redefine the
product.

---

## 1. Purpose

Srota is an intent-to-fabric compiler: the customer supplies intent; the engine
returns a synthesizable, simulatable fabric shipped with its proofs. B1 made
*design intent* trustworthy. B2 made *nodes, ranks and placement* trustworthy.
B3.0 defines the missing middle: **the exact resolved fabric**.

Today fabric semantics are distributed across TopologyIR, `presets.Topology`,
BookSim config construction, AnyNet, `RouteArtifact`, the abstract dependency/VC
logic, LLMServingSim's serving lowering, the RTL generator, three RTL families,
the flow/deadlock certifiers, reports and simulation defaults. These
representations are not guaranteed to mean the same thing. This document:

1. inventories every first-party fabric-semantic implementation;
2. names the contradictions between them;
3. defines one authoritative semantic model (artifacts + invariants);
4. defines the lowering contract from that model to each backend;
5. scopes the B3 implementation waves that will make the model real.

## 2. Scope and non-goals

**In scope:** routers/ports/links, endpoints/attachments, topology, routing,
virtual channels, deadlock certification, packet/flit format, flow control,
arbitration, pipeline semantics, multicast, multi-plane, clock/power/protocol
boundaries, artifact identity, backend lowering contracts, support matrix,
migration.

**Non-goals (explicitly deferred):** a universal NoC language; arbitrary routing
DSLs; full CHI/AMBA protocol semantics; physical floorplanning; CDC insertion;
SystemC implementation; changing B1/B2 semantics; changing any production code
in this wave.

**Product-facing non-negotiable invariants (inherited, verified doc §4):**
- 4.1 No false PASS.
- 4.2 Certified means executed — a routing/deadlock claim is valid only if the
  verifier reasons about the exact route/VC realization the target executes.
- 4.9 Compiler-owned does not mean hidden.
- 4.10 No silent scientific fallback.

## 3. Current implementation inventory

Counts are first-party, in-tree.

| Category | Count | Notes |
|---|---|---|
| Python modules audited | ~20 | DSE package fabric-surface + tools |
| SystemVerilog files | 15 | 3 RTL families + support |
| Test modules pinning fabric claims | 24 | see §29 |
| Third-party seams | 4 | BookSim2 (standalone + embedded), ASTRA-sim, LLMServingSim, Ramulator |
| Docs | 4 | Studio PRD, verified architecture, checklists, gap analysis |

Key files (Python):
`model/topology_ir.py`, `model/presets.py`, `model/compile_model.py`,
`model/placement.py`, `model/mapping.py`, `core/fabric.py`,
`core/route_artifact.py`, `core/anynet.py`, `core/constants.py`,
`simulation/booksim.py`, `simulation/astrasim_adapter.py`,
`core/experiment.py`, `core/experiment_serving.py`, `core/serving.py`,
`tools/deadlock_routing.py`, `tools/flow_certifier.py`, `synthesis/*.py`,
`reports/reports.py`, `verification/uvm_gen.py`.

Key files (SystemVerilog): `scripts/rtlgen/{noc_pkg,router,router_template,
router_template_v2,axi4_noc,axi4_flit,ecc_codec}.sv`,
`rtl/mot_htree/{noc_pkg,router_htree,router_template,router_template_v2,islip}.sv`,
`rtl/cdc/cdc_fifo.sv`.

Third-party seams actually invoked: BookSim AnyNet routing
(`third_party/booksim2/src/networks/anynet.cpp`), BookSim config parser
(`booksim_config.cpp`), ASTRA analytical network yml, LLMServingSim
`serving/__main__.py` and `serving/core/config_builder.py`.

## 4. Existing authority graph (how it works today)

```text
CompileRequest (Design intent, B1)
  │
  ├── Workload(tp,pp,ep,dp) ──► Workload.world_size / NodeInventory  (B2)
  │                                  │
  │                                  └── MappingArtifact (rank→AgentInstance)  (B2)
  │
  ├── derive_topology_spec ──► hardcoded per-family params (mesh k=8,n=2) ──► presets.Topology
  │                                   │
  │                                   └── booksim.build_config ──► config.cfg ──► BookSim (min_anynet / dor)
  │
  ├── derive_vc_count / derive_vc_assignment ──► abstract cycle count ──► num_vcs = vc_count + 1
  │
  ├── reports.generate_report ──► n_routers = Σ agents ; hand-rolled link formula ; flat area/power
  │
  ├── verification.uvm_gen ──► n_nodes = cr.total_nodes ; k = sqrt(total_nodes) ; placeholder SVA
  │
  └── cli.cmd_compile ──► topology_adjacency (2nd mesh/torus builder) ; verify_design

TopologyIR ──► to_booksim_cfg / to_analytical_yml / to_anynet / to_preset ──► some simulator lowering

RouteArtifact ──► route_artifact.py replica (anynet_dijkstra_hops) ──► F6 ; NOT consumed by BookSim or RTL

deadlock_routing.py ──► CDG over materialized paths (physical channel only)   ─┐
flow_certifier.py   ──► CDG over first gen_rtl table that is acyclic          ─┼──► CLI parses stdout
                                                                              ─┘

scripts/rtlgen/gen_rtl.py ──► independently derives route tables / VC classes / flit layout ──► RTL

rtl/mot_htree/* + rtl/cdc/* ──► a second RTL family with a different flit layout and no harness

core/fabric.py FabricArtifact ──► parsed executed cfg fragment (node count, routing, VC/buffer) ──► serving check
```

The duplication is visible: the same concept (topology size, route set, VC
count, deadlock status, fabric identity) is produced independently by multiple
subsystems, and only the AnyNet parser was actually consolidated.

## 5. Semantic contradictions

Severity: **P0** = wrong hardware / false certification / identity collision;
**P1** = major inconsistency or missing refusal; **P2** = maintainability.

| ID | Sev | Concept | Implementation A | Implementation B | Consequence | Authoritative ruling | Wave |
|---|---|---|---|---|---|---|---|
| C-01 | P0 | Route realization | certifier CDG from `deadlock_routing` routes | BookSim `min_anynet`; RTL generator tables (`gen_rtl.py:936-967`) | "certified" route set may differ from simulated and RTL sets (`route_artifact.py:2-8`; verified doc §3.3) | TopologyIR→RouteArtifact is the sole route truth; every consumer ingests or is mechanically proven equivalent | B3.2 |
| C-02 | P0 | Route equivalence evidence | `booksim_first_hop_table` → `_anynet_replica_first_hops` (same fn that builds the artifact) | no BookSim/RTL dump producer exists | F6 compares the replica to itself; production F6 is always `NOT_RUN` (`compile_model.py:1963-2012`) | Equivalence must compare against backend-emitted tables; replica-vs-replica is not evidence | B3.2 |
| C-03 | P0 | Deadlock certificate | `derive_vc_assignment` abstract cycles → routing label; F1 `PASS` on abstract graph (`compile_model.py:1809-1843`) | `deadlock_routing.build_cdg_and_check` physical-channel CDG, `escape_vcs` parameter unused (`:263-294`); `flow_certifier` passes on whichever table is acyclic (`:171-200,313`) | dependency DAG ≠ channel DAG ≠ (channel,VC) CDG; PASS may not bind the executed route/VC | Deadlock PASS requires a proof over the exact `(channel,VC)` realization, bound by topology+route+VC hashes | B3.3 |
| C-04 | P0 | Topology sizing | `derive_topology_spec` hardcodes `k=8,n=2` (`compile_model.py:1541-1549`) | reports size `n_routers=Σ agents` (`reports.py:351-353`); UVM `k=sqrt(total_nodes)` (`cli.py:2989`); `topology_adjacency` a second builder (`:1700-1750`) | 4-universe count mismatch (rank/agent/router/BookSim node); a 16-NPU intent compiles to 64 routers; reports disagree with the simulated fabric | TopologyArtifact is materialized from NodeInventory + MappingArtifact + GUIDED family/radix; no count is inferred from a name | B3.1 |
| C-05 | P0 | VC count | `derive_vc_count` clamps `min(vc, PLANE_C_MAX_VC)` (`:560`); `validate`'s overflow error is dead (`:1435-1440`) | `derive_vc_assignment` clamps again (`:922`) but writes `per_class_vc[victim]=i+1` over all cycles (`:944`) and `collective_vc_map` may exceed count | required VCs > supported are silently truncated; assignments can reference VCs ≥ declared count | Required > supported ⇒ `UNSUPPORTED`/`INFEASIBLE`; assignments are validated against `vc_count` | B3.3 |
| C-06 | P0 | Verification status | `verify_design` F1 named `deadlock_freedom` returns `PASS` on abstract graph | generated SVA F1/F4/F5/F6/F7 are `1'b1` placeholders (`uvm_gen.py:328-420`); F3 conservation invalid for pipelined fabric | a customer report can show deadlock "PASS" with no executed proof | PASS only with evidence bound to the exact artifact set (verified doc §12) | B3.8 / V-wave |
| C-07 | P0 | CLI certification | `cli.py:2680-2682` sets `cert=PASS` if any stdout line contains "PASS" | `flow_certifier` overall verdict may be FAIL; exit codes ignored | false PASS in manifest | Certification is parsed from a structured verdict, never by substring; exit code is authoritative | B3.8 |
| C-08 | P0 | Serving fabric check | `check_serving_fabric` compares only `npus_count` dims, `network.yml` topology string, and executed `node_count` (`fabric.py:128-156`) | executed config `topology=mesh` passes while expected/YML is `FullyConnected` (`test_fabric.py:105-107`) | a serving run is declared fabric-consistent without comparing executed topology/routing/VC | Executed BackendConfigArtifact must match the ResolvedFabric on all identity-bearing dimensions | B3.5/B3.7 |
| C-09 | P0 | Packet/flit format | `gen_rtl` flit: class bits top, type `[62:61]`, dst `[53:48]` (`gen_rtl.py:126-146`, `router_template.sv:112-126`) | `axi4_flit.sv` dst `[51:48]`, src `[47:44]`, no class; `mot_htree/noc_pkg.sv` 136-bit struct (src/dst 8b, vc 3b); UVM `DATA_WIDTH` via nonexistent `noc_mesh` | four incompatible layouts; no single packet-format authority; addressability envelope unenforced | One PacketFormatArtifact per fabric; all backends derive their encoding from it | B3.4 |
| C-10 | P0 | Addressability | dst width derived from node count at RTL gen (`dst_w=ceil(log2(n))`) | PRD open question k≤16 vs k=32; no feasibility check anywhere | endpoint count can exceed destination encoding capacity silently | PacketFormatArtifact declares max endpoint/source/VC/class/sequence; compiler checks `endpoints ≤ capacity` | B3.4 |
| C-11 | P1 | Concentration | `CONCENTRATED_MESH` maps to `mesh` and `c` is ignored by mesh math (`compile_model.py:1544,1554-1555`) | `c` only honoured for flatfly/cmesh/gec/dragonflynew (`presets.py:46-109`) | "concentrated mesh" knob is inert | Concentration is a GUIDED topology input; TopologyArtifact materializes tiles-per-router | B3.1 |
| C-12 | P1 | Fat-tree sizing | `FAT_TREE → ("fattree", {})` (`:1546`) | `presets.topo_size` defaults k=8,n=2 → 64 | arbitrary fat-tree size, name claims `_8x8` | Family params are derived from inventory; missing params are an error, not a default | B3.1 |
| C-13 | P1 | Cycle determinism | `find_cycles` iterates a Python `set` (`:495,517`), no `PYTHONHASHSEED` pin | dependency edge order pinned as semantic (`test_design_intent_identity.py:584`) | cross-process nondeterministic cycle count/victim | graph processing deterministic; dependency order becomes non-semantic; semantics version bump | B3.0-pre / B3.3 |
| C-14 | P1 | BookSim defaults | `constants.BOOKSIM_DEFAULTS` `num_vcs=2, vc_buf_size=4` (`constants.py:31-39`) | `BASE_PARAMS`/`BOOKSIM_DEFAULTS` `num_vcs=4, vc_buf_size=8` (`booksim.py:50-66`, `topology_ir.py:68-83`) | two "canonical" default tables | one canonical backend-default table; the other is deleted or derived | B3.7 |
| C-15 | P1 | Lowering honesty | anynet `_build_anynet_config` drops 11 BASE_PARAMS keys, seed, overrides (`booksim.py:192-214`) | standard path emits them; `overrides` topology/routing clobbered (`:172-181`) | hidden BookSim built-ins decide architecture; `hold_switch_for_packet` never emitted anywhere | Backend lowering must emit or explicitly declare every architecture-affecting value | B3.7 |
| C-16 | P1 | Reports fabric binding | reports use flat per-router area/power and their own link formula (`reports.py:351-370,363-370`) | canonical `presets.topo_size`/`_default_edge_count`; torus formula differs (112 vs 128) | report describes a different fabric than simulated | reports render `FabricArtifact`; no independent topology math | B3.5+ |
| C-17 | P1 | AnyNet parser | `core/anynet.py` is the one parser | `core/fabric.py:82-84` inline router scan; `multi_workload_pareto.py:159-167` legacy fallback | counts can diverge; unsupported grammar paths | one parser; fabric evidence uses it | B3.2 |
| C-18 | P1 | Width conversion | agent `data_width=256`, `NocConfig.link_width` are intent-only | RTL `FLIT_W=64` hardcoded, no converter; ASTRA/BookSim ignore width | width mismatch unresolved in hardware | width conversion is an NI responsibility declared in AgentAttachmentArtifact; unsupported ⇒ fail closed | B3.4 |
| C-19 | P1 | Protocol/clock/power | `Agent.protocol/clock_domain/power_domain`, `PhysicalContext` serialized and hashed | never consumed by topology/routing/VC/reports/verification | fabric claims protocol-independence it does not model; CDC undefined | protocol/clock/power ownership defined at attachment/link level; unsupported protocol semantics fail closed | B3.1/B3.4 |
| C-20 | P1 | Multi-plane | RTL emits N independent `noc_top`, no plane field/select; per-plane `"acyclic": True` hardcoded (`gen_rtl.py:1064-1066`) | Planes described as physical option; `flow_certifier` checks physical CDG only | plane independence is a literal, not evidence | Planes are fabric composition; plane identity and per-plane proof are explicit artifacts | B3.3/B3.5 |
| C-21 | P1 | Multicast | `NocConfig.mcast_groups/setup_cycles` + report message-count model | no RTL multicast; no BookSim primitive; PRD treats BROADCAST as lowering | "multicast support" is ambiguous across layers | v1: multicast is workload lowering only, labelled; fabric primitive is `UNSUPPORTED` until implemented | B3.4 |
| C-22 | P1 | Demotion | `router_template.sv:611` disables demotion (`if (0 && ...)`) | docs/TB/`certify.sh` advertise demotion; stale `router.sv:496` enables it | claimed RTL behavior does not exist in generator output | RTL support matrix records demotion `UNSUPPORTED`; claims removed from evidence | B3.6 |
| C-23 | P1 | Formal | `SIM_FORMAL` never defined; `.sby` blocked by Yosys SV syntax (`router_formal.sby:5-8`) | UI/report mention formal | no router ever formally proven | formal is `UNSUPPORTED`/`NOT_RUN`, never PASS | V-wave |
| C-24 | P1 | Ordering gate | `certify.sh:44` greps `P4-ORDER-VIOLATION` | TB never prints it (`gen_rtl.py:560`) | ordering gate can never fail | ordering is `NOT_RUN` until a real check exists | B3.6 |
| C-25 | P1 | Report validation | `report["validation"]["ok"]=True` hardcoded (`reports.py:514-518`) | `validate()` exists | report claims validity it did not compute | reports consume validate/verify results, never hardcode | B3.5 |
| C-26 | P1 | UVM elaboration | UVM instantiates `noc_mesh`/`noc_if`/`noc_tx` | no such modules exist | generated collateral cannot elaborate | UVM is generated from the actual RTL top-module contract | B3.6 |
| C-27 | P2 | Duplicate arithmetic | many per-backend node/edge copies (`evaluator.py:803-833`, `milp_topology_v2.py:91`, `multi_workload_pareto.py:388-397`) | canonical `presets.topo_size` | maintenance/drift | single canonical size helper; others delegate | B3.1 |
| C-28 | P2 | `guardrail_hash` name | `CompileRequest.guardrail_hash()` = design intent | RTL `guardrail_hash` = route-table+template hash (`gen_rtl.py:981-1005`) | same name, disjoint domains | rename RTL field to `rtl_build_hash` | B3.6 |
| C-29 | P2 | Identity artifacts | 5 independent hash authorities (design, mapping, route, fabric, manifest) | RTL template hash | no single resolved-fabric envelope | CandidateFabric/ResolvedFabric binds all child hashes | B3.5 |

## 6. Target fabric semantic architecture

Semantic artifacts, not mandatory Python class names. Layer order is a
dependency order: each artifact may reference only artifacts above it.

```text
DesignRevision  (B1 design_hash)
    │
    ├── NodeInventory        (B2; derived, not persisted)
    └── MappingArtifact      (B2; rank → AgentInstance)
            │
            ▼
     Candidate Synthesis  (GUIDED choices, search)
            │
            ▼
     TopologyArtifact              routers, ports, directed channels, links
            │
            ▼
     AgentAttachmentArtifact       AgentInstance → Endpoint/NI → RouterPort
            │
            ▼
     RouteArtifact                 (router,dest[,class]) → next hop
            │
            ▼
     VCAssignmentArtifact          class → VC set, transitions, escape
            │
            ▼
     PacketFormatArtifact          flit width + field layout
            │
            ▼
     FlowControlArtifact           buffering/credit/reservation semantics
            │
            ▼
     FabricArtifact                content-addressed composite of the above
            │
   ┌────────┼──────────────┬────────────────┬───────────────┐
   ▼        ▼              ▼                ▼               ▼
 BookSim   RTL         Analytical        SystemC         (future)
 Lowering  Lowering    Projection        Lowering
   │        │              │                │
BackendConfig RTLArtifact ModelArtifact   SCArtifact
```

`CandidateFabric` / `ResolvedFabric` is the parent envelope that binds
`design_hash` + `mapping_hash` + every child hash and performs cross-artifact
validation (§20). This discharges the deferred B2 parent-binding obligation.

## 7. Node / router / link semantics

### 7.1 Router

- **Identity:** stable dense integer `router_id` in `[0, router_count)`,
  independent of backend formatting. Coordinate labels (e.g. `(x,y)`) are
  optional attributes, not identity.
- **Attributes:** `router_id`, optional `coordinates`, `ports`, `concentration`
  (agent seats), clock domain (structural, §17).
- **Owner:** TopologyArtifact.
- **Invariant:** `router_id` set is exactly `[0, router_count)`; every port
  appears in at most one channel per direction.

### 7.2 RouterPort

- `(router_id, port_index, role)` where role ∈ {`local`, `link`}.
- `local` ports carry attached agents; `link` ports carry a channel.
- Irregular topologies must be representable; no assumption of cardinal N/E/S/W.

### 7.3 Link and channel

- **PhysicalLink:** unordered pair of ports with width and latency.
- **DirectedChannel:** `(src_router, dst_router, src_port, dst_port,
  logical_channel_index)`; a bidirectional PhysicalLink yields exactly two
  DirectedChannels.
- Routing and deadlock reasoning use **DirectedChannel**; area/timing may use
  PhysicalLink.
- Fields: width (bits), latency (cycles and/or ns with explicit unit), weight
  (for route cost; unit weights in v1), clock crossing (§17).

### 7.4 Materialized topology is the authority

A topology family name is *intent metadata*. The authoritative topology is the
materialized `{routers, ports, channels, links}`. Family/regular metadata may be
retained for explanation, generation and physical layout, but certification and
RTL/simulator equivalence compare materialized structures — never names.

## 8. Agent attachment semantics

```text
AgentInstance  (B2 identity: group_index, instance_index, kind)
      │
      ▼
Endpoint        (logical fabric-addressable attachment; 1:1 with AgentInstance in v1)
      │
      ▼
NetworkInterface (protocol/packetization/width conversion; see §8.2)
      │
      ▼
RouterPort
      │
      ▼
Router
```

- **Owner:** AgentAttachmentArtifact. Inputs: `NodeInventory`, `MappingArtifact`,
  TopologyArtifact, GUIDED concentration.
- **Every hardware AgentInstance gets an attachment**, compute or not: compute
  tiles, HBM controllers, NICs, peripherals, UCIe ports, and *idle compute
  instances*. An active `LogicalRank` is **not** required to attach an agent.
- **Concentration:** `endpoints_per_router` is explicit; a router may host zero,
  one, or many endpoints. Concentration is not inferred separately by simulator
  and RTL.
- **v1 decision:** `Endpoint` and `NetworkInterface` are modelled as one
  semantic attachment object. The distinction is documented for future
  protocol bridges but not instantiated: no fake complexity.
- **Width conversion** (§C-18) is an NI responsibility: `agent_data_width →
  flit_width`. Unsupported conversion fails closed; it may not be silently
  ignored by one backend.
- **Addressability:** `endpoint_id` is the routing destination. An agent may have
  a memory range (`AddressRange.target_agent_idx`) but address decode tables are
  not part of the v1 attachment artifact (§19, C-10).

## 9. Topology semantics

- **Authority:** TopologyArtifact, derived from NodeInventory + MappingArtifact +
  GUIDED `topology_family`/`radix`/`concentration` + physical constraints (§C-04,
  §C-11, §C-12).
- **Sizing rule (v1):** router count is a *derived consequence* of endpoint
  count and concentration under the chosen family — never a hardcoded constant,
  and never equal to model rank count by default.
- **Families and support truth** (§27): mesh, torus, concentrated mesh,
  flatfly, GEC/express, fat-tree, anynet/custom, H-tree. Presence of an enum
  member is not support.
- **AnyNet/custom:** explicit materialized channels; sequential router ids
  required by BookSim; weights are unit in v1 and non-unit weights are refused
  on any path that uses the Python certification representation (verified doc
  §6.4).
- Family metadata (`k`, `n`, `c`, `d`, …) is interpreted only by the family's
  materializer; the materialized graph is what every downstream artifact sees.

## 10. Routing semantics

### 10.1 Policy vs realization

- **RoutingPolicy:** `dimension_order | minimal | minimal_adaptive | up_down |
  valiant | custom`. A label.
- **Materialized realization:** the actual legal movement.
  - deterministic: `(router, destination) → next_hop`
  - adaptive: `(router, destination, routing_class/state) → allowed_next_hop_set`
- A policy label is never certification evidence; the realization is.

### 10.2 RouteArtifact (authority candidate — reuse what is strong)

The existing `core/route_artifact.py` is the strongest artifact in the tree and
is the intended basis. Reuse unchanged: all-pairs `(src,dst)→next_hop`
coverage, canonical `topology_hash`, `route_table_hash`/`artifact_hash` domain
separation, tie-break policy pinning, unit-weight enforcement, connectivity
refusal, sequential-id requirement. Must evolve: (a) add per-class next-hop sets
for adaptive routing instead of forcing one table for all classes; (b) bind
`topology_hash` to the materialized TopologyArtifact (verifiable on load);
(c) refuse a partial table from the public extraction helper as hard as the
constructor does; (d) permit VC/class-dependent entries where the fabric
requires them (verified doc §6.5).

### 10.3 Exact route certification rule (hard invariant)

> No deadlock or routing PASS may be produced unless the proof reasons about the
> exact route realization used by the target backend/RTL, or mechanically proves
> equivalence to it. No exceptions.

This is the direct encoding of verified-doc §4.2 and §7.3.

### 10.4 Turn restrictions

Compiler-owned LOCKED semantics, derived from the route realization. They are
either (a) derived from the RouteArtifact, or (b) proof evidence — never an
independent table that can disagree with routes. They are not a `NocConfig`
field (already true: `test_compile_model.py:626`).

## 11. VC semantics

- A **VirtualChannel** is a resource: `(channel, vc_id)` with its own buffer,
  credits, and allocation state.
- Fields: `vc_id`, `input_buffer_owner`, eligibility (which (channel, class)
  may use it), transition legality (when a packet may move between VCs),
  hold/release semantics.
- **v1 supported behavior class:** the RTL implements a two-class scheme,
  FREE (minimal) and ESCAPE (up/down). `NUM_VCS=N` must **not** be presented as
  N symmetric routing classes when the implementation supports two behavior
  classes. `VCAssignmentArtifact` records `vc_count`, per-class allowed VC sets,
  escape designation, transition restrictions, and buffer model.
- **BookSim reality:** `num_vcs` exposes VCs as buffering resources;
  `min_anynet` does not instantiate RTL escape-routing semantics (verified doc
  §3.4). Any claim of escape-based deadlock freedom must be bound to a backend
  that actually implements escape routing.
- **Extensibility:** the artifact must accommodate multiple traffic classes,
  adaptive+escape, QoS partitions, and (later) multicast without replacement.

### 11.1 VC limits

| Limit | Value | Source |
|---|---|---|
| `PLANE_C_MAX_VC` | 8 (env `VERITX_MAX_VC`) | `constants.py:89-92` |
| BookSim `num_vcs` default | 16 built-in / 4 in BASE_PARAMS / 2 in constants | `booksim_config.cpp:110`; `booksim.py:52`; `constants.py:31-39` |
| RTL class field | `ceil(log2(vcs))`; 1 bit at 2 VCs | `gen_rtl.py:110-116` |
| RTL `BUF_DEPTH` | 8 default | `gen_rtl.py:909` |

Disagreement between these is a **blocking contradiction** (C-05, C-14):
required > supported must be `UNSUPPORTED`/`INFEASIBLE`, never a silent min().

## 12. Deadlock-proof semantics

Supported proof methods are distinct evidence types — no single universal
theorem:

```text
DETERMINISTIC_DOR_THEOREM
CHANNEL_DEPENDENCY_ACYCLIC
CHANNEL_VC_DEPENDENCY_ACYCLIC
ESCAPE_SUBNETWORK_THEOREM          (escape class must be a real, separate VC class)
FORMAL_BOUNDED_CHECK
```

Every certificate binds: `topology_hash`, `route_hash`, `vc_hash`, relevant
`flow_control_hash`, `proof_method`, `evidence`, `tool`, `scope`.

Ruling: the abstract workload dependency graph and `derive_vc_*` are
**candidate-generation heuristics only**. They are never the deadlock proof.
`dependency graph cycles → vc_count` is deleted from certification semantics
(verified doc §3.4). It may remain as a heuristic until B3.3 replaces it.

## 13. Packet / flit semantics

Current state (§C-09): at least four incompatible layouts exist. A single
**PacketFormatArtifact** becomes authoritative; every backend derives its
encoding from it.

Fields: `flit_width_bits`; ordered `field_layout` entries
(`name`, `lsb`, `width`, `signed?`, `semantic_role`); packet types and
HEAD/BODY/TAIL/SINGLE encoding; `max_endpoint_ids`, `max_source_ids`,
`max_vc_ids`, `max_classes`, `max_sequence`; multicast metadata (absent in v1).

Observed layouts to reconcile:
- `gen_rtl.py:126-146` / `router_template.sv:112-126`: class bits at `[63:64-CLASS_W]`, type `[62:61]`, dst `[53:48]`, payload below. `src` is placed only by the TB at `[60:54]` and is not in the package — AMBIGUOUS.
- `axi4_flit.sv:1-20,94-105`: dst `[51:48]`, src `[47:44]`, AXI meta `[43:32]`, payload `[31:0]`, no class/sequence; dst width hardcoded 4b.
- `rtl/mot_htree/noc_pkg.sv:23-33`: 136-bit packed struct, data 64b + head/tail/vc3/cl3/src8/dst8/pid16/itime32.
- `gen_rtl_2die.py:237-247`: dst `[55:48]`, src `[47:40]`, payload `[39:0]`.
- UVM references `noc_mesh` with `DATA_WIDTH=256`, which does not exist.

## 14. Flow-control semantics

Architecture-relevant: credit flow control, buffer depth, credit return
timing/ownership, route reservation, tail release, `wait_for_tail_credit`,
head/body/tail semantics, input/output buffering, VC allocation, switch
allocation, arbitration, pipeline, speedup. These are not "simulator tuning".

RTL reality: per-(output,VC) credit, init to `BUF_DEPTH`, decrement on load,
increment on downstream acceptance (`router_template.sv:397-477`); the v2
template and H-tree router use per-output and per-(output,VC) variants. BookSim
default `vc_buf_size=8` matches the RTL default; VC count does not (2 vs 4).

Classification table (FABRIC SEMANTIC vs BACKEND IMPLEMENTATION DETAIL) is
mandatory in the FlowControlArtifact schema (§18) — see §15.3.

## 15. Arbitration / pipeline semantics

### 15.1 Arbitration inventory

| Mechanism | RTL (`router_template.sv`) | H-tree (`router_htree.sv`) | BookSim |
|---|---|---|---|
| VC allocation | escape-first + RR free | iSLIP (`islip.sv`) | islip |
| Switch allocation | single registered output stage (no separate SA) | iSLIP | islip |
| Escape priority | yes, with `ESC_YIELD_K=4` anti-starvation | n/a | none |
| QoS priority | none | none | none (classes=1) |

`NocConfig.arbitration` is a GUIDED label that does **not** currently select any
of these; it is recorded, not enforced. Recorded as a contradiction
(C-15 family / arbitration gap).

### 15.2 Pipeline inventory

`routing_delay`, `vc_alloc_delay`, `sw_alloc_delay`, `credit_delay`,
crossbar/channel latency. Classification:
- **Fabric semantic:** channel latency, GEC deferred routing (`routing_delay=1`
  is architectural there), internal/output/input speedup, buffer depth.
- **Backend execution detail:** BookSim staging values where they do not change
  observable semantics, `sample_period`, `max_samples`, `seed`, `sim_type`.

### 15.3 Required classification table

Every field in `BASE_PARAMS`/`BOOKSIM_DEFAULTS`/`NocConfig`/RTL parameters is
classified `FABRIC_SEMANTIC` or `BACKEND_IMPLEMENTATION_DETAIL`. No field may be
left implicit; `hold_switch_for_packet` (never emitted anywhere; BookSim default
0) is the first example of a field that must be explicitly classified.

## 16. Multicast / multi-plane semantics

- **Multicast (v1):** workload-lowering only. `NocConfig.mcast_groups` /
  `mcast_setup_cycles` are a message-count model. Fabric primitive is
  `UNSUPPORTED` until an RTL/BookSim primitive exists. Any fabric claim of
  multicast acceleration is prohibited.
- **Multi-plane:** fabric composition. A plane is a complete fabric instance;
  plane membership, per-plane route/VC artifacts, and per-plane certificates
  are explicit. `"cross_plane_independence": True` and per-plane
  `"acyclic": True` currently hardcoded (`gen_rtl.py:1064-1066`) must become
  computed evidence or `NOT_RUN`.

## 17. Clock / power / protocol boundaries

- **Clock:** an endpoint attachment carries a clock domain; a DirectedChannel
  may cross domains. Crossing implies an explicit CDC mechanism (§8), not a
  silent merge. v1 does not implement CDC insertion; crossings are recorded and
  unsupported crossings fail closed.
- **Power:** a router/link may belong to a power domain; domain crossing that
  needs isolation is declared. `PhysicalContext.num_power_domains` is currently
  inert; it becomes structural only when the fabric model consumes it.
- **Protocol:** `Agent.protocol` (AXI/CHI/custom/UCIe) currently does not change
  packet classes, ordering, response dependencies, VC requirements or NI
  structure. B3 need not implement CHI, but the fabric model must not claim
  protocol-independent verification where protocol semantics matter. Unsupported
  protocol semantics fail closed.

## 18. Artifact definitions

All artifacts: frozen, schema-versioned, canonical-JSON hashed with a
domain-separated tag (`srota/<Artifact>/v<schema>`), and fail-closed on unknown
fields (B1 discipline).

### TopologyArtifact
Routers, RouterPorts, DirectedChannels, PhysicalLinks, link width/latency,
concentration. Derived from inventory + attachment + GUIDED knobs. Identity:
materialized graph (router ids, channel set, attachment seats), not the family
name.

### AgentAttachmentArtifact
`endpoint_id → (AgentInstance, RouterPort)`, `agent_data_width`, `flit_width`,
NI declaration, clock domain. Derived from NodeInventory + MappingArtifact +
TopologyArtifact.

### RouteArtifact
Evolve `core/route_artifact.py`: `schema_version`, `topology_hash`,
`routing_algorithm` (exact version), entries (deterministic next-hop;
adaptive next-hop sets by class), `tie_break_policy`, `endpoint_assumptions`,
per-class VC eligibility where routing depends on VC, `route_table_hash`,
`artifact_hash`.

### VCAssignmentArtifact
`route_hash`, `vc_count`, VC definitions, `class → allowed_vc_set`, escape VC
designation, transitions, buffer model, derivation method, `artifact_hash`.

### PacketFormatArtifact
§13 fields + `artifact_hash`.

### FlowControlArtifact
Credit protocol, buffer depth per VC, reservation/tail-release semantics,
`wait_for_tail_credit`, speedups, field classification table, `artifact_hash`.

### FabricArtifact
Content-addressed composite: `{topology_hash, attachment_hash, route_hash,
vc_assignment_hash, packet_format_hash, flow_control_hash, arbitration_semantics,
structural clock/power semantics, schema_version, artifact_hash}`. **Excludes**
BookSim config path, run id, git SHA, timestamp, seed, sample period.

### BackendConfigArtifact
`{backend, backend_binary_sha256, fabric_hash, rendered_config_sha256,
auxiliary_files[{name,sha256}], lowering_version, semantic_loss[], artifact_hash}`.

### CandidateFabric / ResolvedFabric
Parent envelope: `{design_hash, mapping_hash, topology_hash, attachment_hash,
route_hash, vc_assignment_hash, packet_format_hash, flow_control_hash,
fabric_hash, generation_provenance, guided_choices, candidate_id}`. No
simulation results in identity.

## 19. Identity and hash rules

- **Semantic fields:** any change to a value that changes the hardware or its
  execution changes identity.
- **Non-semantic fields:** file path, JSON whitespace/key order, run id,
  timestamp, seed, git SHA, sample count. These never enter a semantic hash.
- **Domain separation:** every artifact hashes `srota/<Artifact>/v<schema>\0`
  plus canonical JSON (B1 pattern).
- **Parent binding:** a child artifact never embeds the entire parent; the
  parent envelope binds child hashes and validates relationships at the seam.

Identity table:

| Artifact | Parent hashes | Canonicalization | Hash domain | Producer | Consumer |
|---|---|---|---|---|---|
| TopologyArtifact | none (inputs: inventory/mapping hashes recorded in envelope) | sorted routers/channels | `srota/TopologyArtifact/v1` | synthesis | attachment, route, reports, lowerers |
| AgentAttachmentArtifact | topology_hash | sorted by endpoint_id | `srota/AgentAttachment/v1` | synthesis | route, packet, lowerers |
| RouteArtifact | topology_hash | sorted entries | `srota/RouteArtifact/v1` | routing | VC, certifiers, lowerers |
| VCAssignmentArtifact | route_hash | sorted class→VC | `srota/VCAssignment/v1` | VC derivation | certifiers, lowerers |
| PacketFormatArtifact | none | field order | `srota/PacketFormat/v1` | format derivation | RTL/BookSim lowerers |
| FlowControlArtifact | none | field order | `srota/FlowControl/v1` | flow derivation | lowerers, certifiers |
| FabricArtifact | the five above | child hashes sorted | `srota/Fabric/v1` | synthesis | lowerers, provenance |
| BackendConfigArtifact | fabric_hash | file list sorted | `srota/BackendConfig/v1` | lowerer | execution, comparison |
| ResolvedFabric | design_hash, mapping_hash, all above | key order | `srota/ResolvedFabric/v1` | synthesis | compiler, UI, export |

## 20. Cross-artifact invariants

Enforced at the ResolvedFabric seam (discharges B2's deferred parent binding):

- every mapping agent exists in NodeInventory; kind agrees; group/instance exist;
- every attachment agent exists; every attachment router/port exists;
- every router port used at most legally; every channel references real ports;
- every route hop corresponds to a materialized DirectedChannel;
- every destination reachable; no partial route tables;
- every VC id `< vc_count`; every class has legal VC eligibility; assignments
  never reference a VC ≥ count;
- packet fields can encode every endpoint/source/VC/class/sequence value;
- buffers exist for every implemented VC where the architecture requires;
- deadlock certificate hashes the exact topology+route+VC semantics;
- no fabric/mapping parent check is skipped because a hash is absent.

## 21. CandidateFabric semantics

Candidate generation (synthesis) is separate from candidate evaluation
(measurement). A candidate binds the child artifacts plus generation provenance
and the GUIDED knob choices, and its identity excludes simulation results.
Any architecture-affecting decision must be resolved *before*
BackendConfigArtifact generation; a backend may not finish architecture
decisions during evaluation.

## 22. Backend lowering contracts

General contract:

```text
FabricArtifact → (backend lowerer, lowering_version) → BackendConfigArtifact
```

The lowerer must emit or explicitly declare every architecture-affecting value;
`semantic_loss[]` lists anything the backend cannot represent. No backend invents
fabric semantics.

### BookSim (23)

Table of Srota semantic → BookSim field/file, exact mapping, losslessness:

| Srota semantic | BookSim | Lossless? |
|---|---|---|
| materialized topology | `topology`/`k`/`n`/`network_file` | mesh/torus/anynet yes; others partial |
| route realization | `routing_function` or route table | **NO** — BookSim computes `min_anynet`; must ingest or dump (C-01/C-02) |
| vc_count | `num_vcs` | yes, but semantics differ (buffering only) |
| vc buffer depth | `vc_buf_size` | yes |
| packetization | `packet_size` | yes (8 vs ASTRA 64 divergence) |
| flow control | `wait_for_tail_credit`, `hold_switch_for_packet` | partial; latter never emitted |
| arbitration | `vc_allocator`/`sw_allocator`/`arb_type` | partial |
| pipeline | `routing_delay`/`vc_alloc_delay`/`sw_alloc_delay`/`credit_delay` | execution detail |
| link width/latency | none | **loss** — declared in `semantic_loss[]` |

### RTL (24)

Must consume TopologyArtifact adjacency, RouteArtifact tables, VC assignment,
PacketFormatArtifact layout, FlowControlArtifact parameters, plane composition —
rather than re-deriving any of them. Current generator re-derives (C-01/C-04).

### Analytical (25)

Must declare topology classes representable, congestion model, units, and
`semantic_loss[]` (e.g. drops routing/VC detail, models bandwidth/latency only).

### SystemC (26)

`NOT IMPLEMENTED`. Intended high-level contract: consume FabricArtifact +
WorkloadIR, implement packet/flit format and flow-control semantics from the
artifacts, declare fidelity.

## 23. SystemC status

No first-party SystemC model exists. The PRD promises behavioral models; B3.0
records this as unimplemented and specifies only the contract above. No support
may be claimed.

## 24. Support matrix

Values: `SUPPORTED`, `PARTIAL`, `UNSUPPORTED`, `UNKNOWN`. Never inferred from a
name.

| Capability | Intent model | TopologyIR | BookSim | Analytical | RTL | Route cert. | Deadlock cert. | Certified today? |
|---|---|---|---|---|---|---|---|---|
| mesh | yes | yes | yes | yes | yes | yes | PARTIAL (physical CDG) | **No** (route mismatch) |
| torus | yes | yes | yes | yes (Ring) | partial | partial | partial | **No** |
| ring | via torus | yes | 1-D torus | Ring | partial | yes | yes | **No** |
| star/switch | no enum | yes | via anynet | Switch | no | yes | partial | **No** |
| anynet/custom | via GEC families only | yes | yes | needs dims | yes | yes | PARTIAL | **No** |
| GEC/express | GEC | no | partial | no | no | no | no | **No** |
| concentrated mesh | GUIDED | no | no (c ignored) | no | no | no | no | **No** |
| fat-tree | GUIDED | no | via sizes | no | no | no | no | **No** |
| H-tree | no | no | no | no | yes (`mot_htree`) | no | no | **No** |
| deterministic routing | yes | `effective_routing` | yes | partial | yes | yes | yes | **No** (realization) |
| adaptive routing | label only | no | partial (`min_adapt`) | no | escape only | no | no | **No** |
| escape routing | derived | no | no | no | yes | no | partial | **No** |
| N VCs | derived | no | buffering only | no | 2 classes | no | no | **No** |
| multicast | message model | no | no | no | no | no | no | **No** |
| multi-plane | flag only | no | no | no | duplication | no | hardcoded | **No** |
| credit flow control | implicit | no | yes | no | yes | n/a | no | **No** |
| width conversion | no | no | no | no | no | n/a | n/a | **No** |
| QoS arbitration | GUIDED label | no | no | no | no | no | no | **No** |
| CDC | fields only | no | no | no | `cdc_fifo.sv` | n/a | n/a | **No** |

## 25. LOCKED / GUIDED / FREE matrix

| Decision | Tier | Rationale |
|---|---|---|
| topology_family | GUIDED | user proposes, engine may adjust |
| radix / concentration | GUIDED | user proposes; sizing derived |
| arbitration preference | GUIDED | high-level preference; implementation derived |
| RCU | GUIDED | scope knob |
| link width | GUIDED | physical |
| buffer depth | GUIDED | expert; derived floor |
| output models | FREE | collateral choice |
| obfuscation | FREE | IP protection |
| router/link graph (materialized) | DERIVED CONSEQUENCE | from inventory + GUIDED |
| endpoint attachment | DERIVED CONSEQUENCE | from MappingArtifact + GUIDED concentration |
| routing algorithm | LOCKED | derived; inspectable |
| materialized routes | LOCKED | authority; inspectable, evidence-linked |
| turn restrictions | LOCKED | derived from route realization |
| VC count / assignment | LOCKED | derived; over-limit ⇒ UNSUPPORTED |
| escape policy | LOCKED | derived |
| packet format | LOCKED | derived from endpoint count + classes |
| flow-control protocol | LOCKED | credit-based in v1 |
| pipeline stages | BACKEND + partial LOCKED | channel latency semantic; staging detail |

**Controversial decisions for review:** (a) buffer depth GUIDED vs LOCKED;
(b) pipeline staging as backend detail (acceptable only if an observable-
equivalence contract is defined, §27); (c) concentration as GUIDED despite being
inert today.

## 26. Verification obligations

- Every routing/deadlock PASS binds topology+route+VC hashes (§12).
- F1–F8 must be evidence-backed or `NOT_RUN`/`ASSUMPTION`/`UNSUPPORTED`
  (verified doc §12.1).
- Formal is PASS only when a tool elaborates the exact RTL/property set.
- Reports render evidence; they never invent status; `validation.ok` is
  computed, never hardcoded.
- CLI certification parses a structured verdict and honors exit codes.

## 27. Simulator vs RTL equivalence contract

| Dimension | Requirement |
|---|---|
| router/link graph | MUST MATCH EXACTLY |
| endpoint attachment | MUST MATCH EXACTLY |
| route realization | MUST MATCH EXACTLY (or mechanically proven equivalent) |
| VC eligibility | MUST MATCH EXACTLY |
| packet/flit width and field semantics | MUST MATCH EXACTLY |
| buffer capacity | MUST MATCH EXACTLY |
| flow-control semantics | MUST MATCH EXACTLY |
| arbitration class behavior | MAY DIFFER WITH DECLARED MODEL |
| pipeline staging | MAY DIFFER WITH DECLARED MODEL (observable equivalence) |
| link latency/bw model | MAY DIFFER WITH DECLARED MODEL |

### 27.1 "Same fabric" (formal definition)

Two resolved fabrics are the **same** iff the identity-bearing fabric-semantic
artifacts are equal:

```text
topology_hash
attachment_hash
route_hash
vc_assignment_hash
packet_format_hash
flow_control_hash
```

It must not depend on file path, JSON whitespace, run id, timestamp, simulation
seed, git SHA, or sample count.

### 27.2 "Same backend execution"

Execution equivalence additionally requires: same fabric, same workload, same
mapping, same backend, same backend binary, same rendered config, same seed
policy, same fidelity. Fabric identity is not experiment identity.

## 28. CandidateFabric, requirements, certification boundary

- Requirement-driven optimization may vary GUIDED knobs only; LOCKED
  correctness fields are derived per candidate. Hard constraints are never
  silently relaxed; best feasible is not a proof of non-existence under
  heuristic search.
- **Certification boundary:** a CandidateFabric is *well-formed* ≠ *certified*.
  Certification requires later, separately tracked evidence (structural, route,
  deadlock, simulation, RTL functional, formal, physical).

## 29. Mutation-test obligations (B3 implementation)

- Topology: change one channel → `topology_hash` changes.
- Attachment: move one agent to another router/port → `attachment_hash` changes.
- Route: change one next hop → `route_table_hash`/`route_hash` change.
- VC: change one allowed VC → `vc_assignment_hash` changes.
- Packet: move one header field bit → `packet_format_hash` changes.
- Flow: change buffer depth → `flow_control_hash` changes.
- Fabric: change any child → `fabric_hash` changes.
- Non-semantic formatting must not change semantic identity.

## 30. B3 implementation plan (proposed; boundaries may move with evidence)

- **B3.0-pre** — graph determinism + dependency order non-semantic +
  `COMPILER_SEMANTICS_VERSION` bump (C-13). Exit: deterministic cycles; golden
  hash updated with rationale; zero regression.
- **B3.1** — TopologyArtifact + AgentAttachmentArtifact; materialized sizing from
  NodeInventory/MappingArtifact; remove hardcoded `k=8,n=2`; concentration/
  fat-tree honestly derived or refused (C-04/C-11/C-12/C-27). Exit: one
  materialized topology; reports consume it.
- **B3.2** — RouteArtifact convergence; Port Artifact; BookSim route
  ingestion/dump or explicit `UNSUPPORTED`; kill replica-vs-replica F6
  (C-01/C-02/C-17). Exit: exactly one route realization per fabric, hashed;
  RTL/BookSim equivalence is `NOT_RUN` or proven.
- **B3.3** — VCAssignmentArtifact + `(channel,VC)` CDG + proof-method registry;
  delete clamp semantics; over-limit ⇒ UNSUPPORTED (C-03/C-05/C-20). Exit:
  deadlock PASS only with bound evidence.
- **B3.4** — PacketFormatArtifact + FlowControlArtifact + addressability check
  (C-09/C-10/C-18/C-21). Exit: one authoritative layout; RTL/UVM derive from it.
- **B3.5** — FabricArtifact v2 + ResolvedFabric envelope + cross-artifact
  validation; reports become renderers (C-08/C-16/C-25). Exit: parent binding
  discharges B2 obligation.
- **B3.6** — RTL lowering convergence: consume artifacts, remove independent
  route/VC derivation, fix demotion/P4/formal claims (C-22/C-23/C-24/C-26/C-28).
- **B3.7** — Backend lowerer migration + BackendConfigArtifact + serving lowering
  honesty (C-14/C-15). Exit: every architecture-affecting value emitted or
  declared.
- **B3.8** — Adversarial/cross-backend qualification: mutation tests, exact-route
  equivalence, golden end-to-end 4/8-endpoint fabric.

Dependencies: B3.0-pre → B3.1 → B3.2 → B3.3 → B3.4 → B3.5; B3.6/B3.7 depend on
B3.5; B3.8 last.

## 31. Migration / deprecation plan

| API/class | Verdict | Note |
|---|---|---|
| `model/topology_ir.py` | EVOLVE | becomes TopologyArtifact source; materialization authority |
| `presets.Topology` | KEEP (narrow) | backend preset bridge; not fabric authority |
| `core/fabric.py FabricArtifact` | EVOLVE→RENAME | executed evidence → `ExecutedFabric` at B3.7 |
| `core/route_artifact.py` | KEEP + EVOLVE | strongest artifact; reuse hashing/coverage |
| `VCAssignment` (compile_model) | EVOLVE | becomes VCAssignmentArtifact; counts become evidence-bound |
| `derive_vc_count` | DEPRECATE | heuristic only; delete from certification |
| `derive_vc_assignment` | EVOLVE | feeds candidate generation, not proof |
| `derive_topology_spec` | EVOLVE | size from inventory, not `k=8,n=2` |
| `booksim.build_config` | EVOLVE | lowerer emitting declared semantics |
| `flow_certifier` route logic | EVOLVE | consume RouteArtifact; drop table-guessing |
| RTL local route generation | DEPRECATE | consume RouteArtifact |
| report topology arithmetic | DELETE | render FabricArtifact |
| `constants.BOOKSIM_DEFAULTS` | DELETE or DERIVE | one canonical table |

## 32. Open questions

- **OQ-1** BookSim↔RTL timing correlation scope: exact staging need not match if
  observable equivalence is defined; the observable-equivalence definition is
  unresolved.
- **OQ-2** Weighted-link semantics: v1 refuses non-unit weights on the
  certification path; when weighted routing lands, tie-break/relaxation must be
  pinned exactly for every backend.
- **OQ-3** Multicast execution model: workload-lowering-only in v1; whether a
  fabric primitive is on the roadmap is unresolved.
- **OQ-4** Formal certification target: Bitwuzla/Yosys SV frontend blocker
  (`router_formal.sby:5-8`) must be resolved before any router proof claim.
- **OQ-5** SystemC fidelity target: unimplemented; intended contract only.
- **OQ-6** Address map → fabric: whether `target_agent_idx` drives endpoint ids /
  NI decode in the v1 fabric model or remains a later seam.
- **OQ-7** Buffer depth tier: GUIDED vs LOCKED.
- **OQ-8** Plane composition identity: whether planes are topology, routing, or
  fabric composition (working assumption: fabric composition).

## 33. Definition of Done (B3.0)

A future engineer can answer, without reading simulator/RTL source:

- what a Srota fabric is, and what makes two fabrics the same;
- what a router, endpoint, NI, port, link and channel are;
- the topology authority and the route authority;
- what a VC means and when a VC-count is evidence;
- how deadlock freedom is certified (and what it binds);
- the packet/flit format the hardware implements;
- which flow-control semantics are architectural;
- which parameters are LOCKED/GUIDED/FREE;
- how a FabricArtifact becomes BookSim and RTL;
- which semantic losses analytical may declare;
- what SystemC must implement;
- what is supported and unsupported today;
- what evidence is required before calling a fabric verified.

If any answer is "it depends which file you look at", B3.0 is not done.

---

### Appendix A — Required authority diagram (target)

See §6. Layering: DesignRevision → NodeInventory/MappingArtifact → synthesis →
TopologyArtifact → AgentAttachmentArtifact → RouteArtifact →
VCAssignmentArtifact → PacketFormatArtifact → FlowControlArtifact →
FabricArtifact → {BookSim|RTL|Analytical|SystemC} lowerers → BackendConfig /
RTLArtifact / ModelArtifact / SCArtifact.

### Appendix B — Required current-authority diagram

See §4.

### Appendix C — Contradiction register

See §5 (C-01 … C-29).
