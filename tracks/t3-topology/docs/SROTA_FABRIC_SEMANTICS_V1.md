# SROTA_FABRIC_SEMANTICS_V1

**Wave:** B3.0 audit + B3.0.1 architecture correction (documentation only; no production code)
**Repository:** `Anmol-S314/veritx-research`
**Branch:** `audit/wave-b-intent-identity`
**Base SHA (B3.0):** `c69e4ca78691a71ded094f67419b64cb0454c260`
**Status:** For architecture review (B3.0.1)
**Depends on:** B1 (`design_hash`), B2 (`NodeInventory`, `MappingArtifact`)

## Revision history

| Rev | Wave | Change |
|---|---|---|
| 1.0 | B3.0 | Audit + first specification. |
| 1.1 | B3.0.1 | Close fabric semantic ownership and identity gaps: RouteArtifact binds attachment; remove Topology/Attachment circularity; replace the linear chain with an artifact DAG; split RoutingClass (Route) from VC resources (VCAssignment); rename FlowControlArtifact → RouterBehaviorArtifact; single owner for flit width; `fabric_hash` is the same-fabric definition; separate `resolved_fabric_hash`; candidate provenance non-semantic; canonical numbering rules; `channel_id` and DirectedChannel-first link properties; derived packet capacities; structured SemanticLoss; consistent support vocabulary; closed buffer-depth/plane/address rulings; compiler-semantics-v1 migration rule. |
| 1.2 | B3.2 | Two-tier routing: the router-level RouteArtifact (parent: topology only) is split from ResolvedRouteArtifact (parents: topology + attachment + router route), which owns endpoint→router, LOCAL_EJECTION and the expanded endpoint route-table hash. FabricArtifact binds `resolved_route_hash`. F6 can never PASS from two replicas of the same algorithm; it requires independent backend-emitted executed-route evidence. |
| 1.3 | B3.4 | PacketFormatArtifact is the wire-format authority: physical beat width stays Topology-owned, logical flit width is PacketFormat-owned, v1 requires one flit per beat. v1 wire fields are payload/source_endpoint/destination_endpoint/flit_type/vc_id; TrafficClass, RoutingClass, sequence and protocol metadata are explicitly absent. RouterBehaviorArtifact v1 pins per-input-port/per-VC buffering, credit flow control, wait-for-tail-credit, iSLIP, pipeline timing and speedups, with no implicit demotion or escape priority. |
| 1.4 | B3.4c | RouterBehaviorArtifact schema v2: the ambiguous `packet_hold_policy=FLIT_INTERLEAVED` is replaced by `input_vc_packet_policy=ONE_PACKET_AT_A_TIME` (no two packets share one input VC's packet context) and `vc_allocation_scope=PACKET` (HEAD/SINGLE selects `vc_out`; BODY/TAIL reuse it for the packet at that hop). `hold_switch_for_packet` remains the independent switch-arbitration granularity. v1 is explicitly refused, not silently migrated. |
| 1.5 | B3.1c | AgentAttachmentArtifact completes the interface authority: each Endpoint carries an immutable `AgentInterfaceDescriptor` (data_width_bits, address_width_bits, protocol, clock_domain, power_domain) derived from the parent Agent group, and the artifact binds `design_hash` as a parent. Validation proves group/instance bounds, kind agreement, interface equality with the parent group, real router seats, and one-to-one mapping placement identity. Schema v2; v1 attachments refused. |
| 1.6 | B3.1d | Attachment identity correction: schema v3 makes `topology_hash` the ONLY semantic parent. DesignRevision and NodeInventory are derivation/validation sources and MappingArtifact meets the hardware again only at ResolvedFabric (`resolved_fabric_hash = design_hash + mapping_hash + fabric_hash`), so the same hardware under a different mapping or an unrelated design change keeps the same `attachment_hash`/`fabric_hash`. Validation now proves the complete design agent universe (no missing idle agents, no fabricated extras) and total seat legality. v1 and v2 attachments are refused. |
| 1.7 | B3.5a | FabricArtifact is implemented as the root hardware identity: exactly the six child semantic hashes + `PlaneComposition.SINGLE_PLANE`, domain `srota/Fabric/v1`. `validate_against` revalidates the complete child DAG, so individually valid children that cannot form one DAG are refused. No design/mapping/backend/provenance/evidence enters `fabric_hash`. Legacy `core.fabric.FabricArtifact` remains untouched backend evidence (rename in B3.7). |
| 1.8 | B3.5b | ResolvedFabric is implemented: `resolved_fabric_hash = H(design_hash, mapping_hash, fabric_hash)`, domain `srota/ResolvedFabric/v1`. Its seam proves the design/mapping/fabric roots, the attachment↔design/inventory universe, the mapping↔attachment placement identity (exact coordinates+kind; idle agents legal), the rank-space equality, and then the complete FabricArtifact DAG. Same hardware under a different mapping keeps `fabric_hash` and changes `resolved_fabric_hash`. |
| 1.9 | B3.5c | Sealing validation only; no schema/hash change. FabricArtifact now calls `attachment.validate_against_topology(topology)` and `router_route.validate_against(topology)` (parent-hash equality is not legality: channels, all-pairs termination, loops). Attachment gains the design-free `validate_against_topology` helper; `validate_against(design, inventory, topology)` composes it. ResolvedFabric proves `inventory.parallelism == workload (tp,pp,ep,dp)` and that `inventory.ranks` is the canonical rank namespace for that shape (equal world size with different geometry is refused), plus tampered coordinates are refused. |
| 1.10 | B3.5d | AddressDecodeArtifact materializes `CompileRequest.address_map` + attachment into canonical `(name, base, size, target_agent_group, target_endpoint_id)` entries (domain `srota/AddressDecode/v1`), with singleton-target-group enforcement and UNSUPPORTED for multi-instance groups. FabricArtifact becomes schema v2 (`srota/Fabric/v2`) binding `address_decode_hash`; v1 is refused. ResolvedFabric proves the decode artifact corresponds exactly to `design.address_map`. Addresses remain protocol payload and do not enter flit headers. |
| 1.11 | B3.5e | AddressDecodeArtifact schema v2: range `name` is non-semantic transport (excluded from `address_decode_hash` and canonical order), `address_transform=IDENTITY` pins forwarding, and entries must fit the target endpoint's address interface width. `validate_against_attachment` proves hardware legality without DesignRevision; `validate_against` proves design-map equivalence. FabricArtifact schema v3 (`srota/Fabric/v3`) validates hardware-only and refuses multi-clock/multi-power attachments; ResolvedFabric owns address-map equivalence and refuses `rcu_enabled=True`. Fabric v1/v2 and AddressDecode v1 are refused. |

This document defines what a resolved Srota fabric *is* before B3 code is
written. It starts from hardware semantics and maps existing code onto them —
not the reverse. Where current code is narrower than the product contract, the
narrowness is recorded as *implementation support*, not used to redefine the
product.

---

## 1. Purpose

Srota is an intent-to-fabric compiler. B1 made *design intent* trustworthy. B2
made *nodes, ranks and placement* trustworthy. B3.0/B3.0.1 define the missing
middle: **the exact resolved fabric and one owner for every fabric semantic**.

## 2. Scope and non-goals

**In scope:** routers/ports/channels/links, endpoints/attachments, topology,
routing classes, virtual channels, deadlock certification, packet/flit format,
router behavior (buffering/credit/arbitration/pipeline), multicast, multi-plane,
clock/power/protocol boundaries, artifact identity and parent binding, backend
lowering contracts, support matrix, migration.

**Non-goals:** a universal NoC language; routing DSLs; full CHI/AMBA semantics;
physical floorplanning; CDC insertion; SystemC implementation; changing B1/B2
semantics; changing production code in this wave.

**Inherited non-negotiable invariants (verified doc §4):** no false PASS;
certified means executed; compiler-owned ≠ hidden; no silent scientific
fallback.

## 3. Current implementation inventory

| Category | Count | Notes |
|---|---|---|
| Python modules audited | ~27 | DSE package fabric-surface + tools |
| SystemVerilog files | 13 | 3 RTL families + support |
| C++ testbenches | 5 | rtlgen harnesses |
| Test modules pinning fabric claims | 24 | §28 |
| Third-party seams actually invoked | 4 | BookSim2 (standalone + embedded), ASTRA-sim, LLMServingSim, Ramulator |
| Docs | 4 | Studio PRD, verified architecture, checklists, gap analysis |

Key Python: `model/{topology_ir,presets,compile_model,placement,mapping}.py`,
`core/{fabric,route_artifact,anynet,constants,experiment,experiment_serving,serving}.py`,
`simulation/{booksim,astrasim_adapter}.py`,
`tools/{deadlock_routing,flow_certifier}.py`, `reports/{reports,artifact}.py`,
`verification/uvm_gen.py`, `synthesis/*.py`.

Key SystemVerilog: `scripts/rtlgen/{noc_pkg,router,router_template,router_template_v2,axi4_noc,axi4_flit,ecc_codec}.sv`,
`rtl/mot_htree/{noc_pkg,router_htree,router_template,router_template_v2,islip}.sv`,
`rtl/cdc/cdc_fifo.sv`.

## 4. Existing authority graph (how it works today)

```text
CompileRequest (B1)
  ├── Workload(tp,pp,ep,dp) ──► NodeInventory (B2) ──► MappingArtifact (B2)
  ├── derive_topology_spec ──► per-family params (mesh k=8,n=2) ──► presets.Topology
  │                                   └── booksim.build_config ──► config.cfg ──► BookSim (min_anynet / dor)
  ├── derive_vc_count / derive_vc_assignment ──► abstract cycles ──► num_vcs = vc_count + 1
  ├── reports.generate_report ──► n_routers = Σ agents ; hand-rolled link formula ; flat area/power
  ├── verification.uvm_gen ──► n_nodes = cr.total_nodes ; k = sqrt(total_nodes) ; placeholder SVA
  └── cli.cmd_compile ──► topology_adjacency (2nd builder) ; verify_design

TopologyIR ──► to_booksim_cfg / to_analytical_yml / to_anynet / to_preset
ResolvedRouteArtifact ──► F6 requires independent backend-emitted executed evidence; replicas are INCONCLUSIVE
deadlock_routing.py / flow_certifier.py ──► CDGs ──► CLI parses stdout
scripts/rtlgen/gen_rtl.py ──► independently derives routes/VC/flit ──► RTL
rtl/mot_htree + rtl/cdc ──► second RTL family, different layout, no harness
core/fabric.py FabricArtifact ──► parsed executed cfg fragment ──► serving check
```

Duplication is visible: topology size, route set, VC count, deadlock status and
fabric identity each have multiple independent producers; only the AnyNet parser
was consolidated.

## 5. Semantic contradictions

Severity: **P0** wrong hardware / false certification / identity collision;
**P1** major inconsistency or missing refusal; **P2** maintainability.

| ID | Sev | Concept | A | B | Consequence | Ruling | Wave |
|---|---|---|---|---|---|---|---|
| C-01 | P0 | Route realization | certifier CDG (`deadlock_routing`) | BookSim `min_anynet`; RTL tables (`gen_rtl.py:936-967`) | certified ≠ simulated ≠ RTL routes | RouteArtifact sole route truth; consumers ingest or prove equivalence | B3.2 |
| C-02 | P0 | Route evidence | `booksim_first_hop_table` → replica (same fn that builds artifact) | no BookSim/RTL dump producer | F6 self-comparison; production F6 `NOT_RUN` (`compile_model.py:1963-2012`) | compare against backend-emitted tables | B3.2 |
| C-03 | P0 | Deadlock certificate | `derive_vc_assignment` abstract cycles; F1 `PASS` abstract (`compile_model.py:1809-1843`) | physical-channel CDG, `escape_vcs` unused (`deadlock_routing.py:263-294`); table-guessing PASS (`flow_certifier.py:171-200,313`) | PASS may not bind executed route/VC | PASS requires `(channel,VC)` proof bound by hashes | B3.3 |
| C-04 | P0 | Topology sizing | `derive_topology_spec` `k=8,n=2` (`compile_model.py:1541-1549`) | reports `Σ agents` (`reports.py:351-353`); UVM `sqrt(total_nodes)` (`cli.py:2989`); 2nd builder (`:1700-1750`) | 4-universe mismatch; 16-NPU intent → 64 routers | materialized from inventory+mapping+GUIDED | B3.1 |
| C-05 | P0 | VC count | clamp `min(vc,MAX)` (`:560`); dead error (`:1435-1440`) | 2nd clamp (`:922`) vs assignments over all cycles (`:944`) | silent truncation; assignments ≥ count | over-limit ⇒ UNSUPPORTED; validate assignments | B3.3 |
| C-06 | P0 | Verification status | F1 `PASS` abstract graph | SVA F1/F4/F5/F6/F7 `1'b1` (`uvm_gen.py:328-420`) | report shows deadlock PASS w/o proof | PASS only with bound evidence | B3.8/V |
| C-07 | P0 | CLI certification | `cert=PASS` on any "PASS" line (`cli.py:2680-2682`) | verdict may be FAIL; exit ignored | false PASS | structured verdict; exit code authoritative | B3.8 |
| C-08 | P0 | Serving check | `check_serving_fabric` dims+yaml+node_count only (`fabric.py:128-156`) | mesh passes as `FullyConnected` (`test_fabric.py:105-107`) | declared consistent w/o comparing executed topology/routing/VC | executed config must match `resolved_fabric_hash` | B3.5/7 |
| C-09 | P0 | Packet format | `gen_rtl` layout | `axi4_flit.sv`; `mot_htree/noc_pkg.sv`; `gen_rtl_2die`; UVM `noc_mesh` | 4 incompatible layouts | one PacketFormatArtifact | B3.4 |
| C-10 | P0 | Addressability | dst width from node count (`gen_rtl.py:110-116`) | PRD k≤16/k=32 open | endpoint count can exceed capacity | compiler checks endpoints ≤ capacity | B3.4 |
| C-11 | P1 | Concentration | `CONCENTRATED_MESH→mesh`, `c` ignored (`compile_model.py:1544,1554-1555`) | `c` honoured only elsewhere (`presets.py:46-109`) | knob inert | GUIDED input; materialized tiles-per-router | B3.1 |
| C-12 | P1 | Fat-tree sizing | `FAT_TREE→{}` (`:1546`) | defaults → 64 | arbitrary size, name claims `_8x8` | missing params = error | B3.1 |
| C-13 | P1 | Cycle determinism | `find_cycles` set iteration (`:495,517`) | dep order pinned semantic (`test_design_intent_identity.py:584`) | nondeterministic cycles | deterministic processing; order non-semantic; bump semantics | B3.0-pre |
| C-14 | P1 | BookSim defaults | `constants.BOOKSIM_DEFAULTS` (`num_vcs=2,vc_buf=4`) | `BASE_PARAMS` (`4,8`) | two canonical tables | one table | B3.7 |
| C-15 | P1 | Lowering honesty | anynet drops 11 keys/overrides (`booksim.py:192-214`); clobber (`:172-181`) | standard path emits | built-ins decide architecture; `hold_switch_for_packet` never emitted | emit or declare every architecture value | B3.7 |
| C-16 | P1 | Reports binding | flat area/power + own link formula (`reports.py:351-370`) | canonical `presets`; torus 112 vs 128 | report ≠ simulated fabric | render FabricArtifact | B3.5 |
| C-17 | P1 | AnyNet parser | `core/anynet.py` | inline reader `fabric.py:82-84`; legacy fallback | counts diverge | one parser | B3.2 |
| C-18 | P1 | Width conversion | `data_width=256`, `link_width` intent-only | RTL `FLIT_W=64`, no converter | unresolved in hardware | NI responsibility declared; unsupported ⇒ fail closed | B3.4 |
| C-19 | P1 | Protocol/clock/power | serialized/hashed | never consumed | false protocol-independence; CDC undefined | ownership at attachment/link; fail closed | B3.1/4 |
| C-20 | P1 | Multi-plane | N independent `noc_top`; `"acyclic":True` hardcoded (`gen_rtl.py:1064-1066`) | planes = physical option | independence is a literal | planes are fabric composition; per-plane proof | B3.3/5 |
| C-21 | P1 | Multicast | message-count model | no RTL/BookSim primitive; PRD = lowering | "support" ambiguous | v1 lowering-only, labelled | B3.4 |
| C-22 | P1 | Demotion | disabled (`router_template.sv:611`) | docs/TB advertise; stale `router.sv:496` | claimed RTL behavior absent | record UNSUPPORTED | B3.6 |
| C-23 | P1 | Formal | `SIM_FORMAL` never defined; `.sby` blocked (`router_formal.sby:5-8`) | UI mentions formal | no router proven | formal NOT_RUN/UNSUPPORTED | V |
| C-24 | P1 | Ordering gate | `certify.sh:44` greps string TB never prints (`gen_rtl.py:560`) | — | gate never fails | ordering NOT_RUN | B3.6 |
| C-25 | P1 | Report validation | `validation.ok=True` hardcoded (`reports.py:514-518`) | `validate()` exists | claims validity not computed | consume validate/verify | B3.5 |
| C-26 | P1 | UVM elaboration | instantiates `noc_mesh`/`noc_if`/`noc_tx` | modules absent | collateral cannot elaborate | generate from real top contract | B3.6 |
| C-27 | P2 | Duplicate arithmetic | many per-backend copies | canonical `presets.topo_size` | drift | single helper | B3.1 |
| C-28 | P2 | `guardrail_hash` name | design intent | RTL route/template hash (`gen_rtl.py:981-1005`) | same name, disjoint | rename RTL field | B3.6 |
| C-29 | P2 | Identity artifacts | 5 hash authorities | RTL template hash | no resolved envelope | ResolvedFabric binds all | B3.5 |

## 6. Target fabric semantic architecture

Artifacts are a **DAG**, not a linear chain. Edges are actual semantic
dependencies; a child's parent hashes name only the artifacts it semantically
depends on.

```text
                     DesignRevision  (design_hash)
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
        NodeInventory             MappingArtifact
              │                         │
              └──────────┬──────────────┘
                         │
                         ▼
                  Candidate Synthesis        (GUIDED choices, search)
                         │
                         ▼
                 TopologyArtifact
                 (NodeInventory + GUIDED topology + physical constraints)
                         │
                         ▼
              AgentAttachmentArtifact
              (topology-bound; agent universe + interface semantics from
               DesignRevision/NodeInventory; Mapping does not flow in)
                    │           │
          ┌─────────┘           └──────────┐
          ▼                                ▼
   RouteArtifact                   PacketFormatArtifact
   (topology only;                 (topology + attachment + vc assignment)
    router-level)                           ▲
          │                                 │
          ▼                                 │
 ResolvedRouteArtifact
 (topology + attachment + router_route)
          │                                 │
          ▼                                 │
 VCAssignmentArtifact ──────────────────────┘
 (resolved_route + design TrafficClass namespace)
          │
          ▼
 RouterBehaviorArtifact
 (vc structure + GUIDED buffer/arbitration choices + fixed architecture)
          │
          └──────────────┐
                         ▼
                   FabricArtifact          (all + address decode + plane, v2)
                         │
                         ▼
                   fabric_hash
                         │
                         ▼
                   ResolvedFabric          (design_hash + mapping_hash + fabric_hash)
                         │
                         ▼
                 resolved_fabric_hash
```

`ResolvedFabric` (design_hash + mapping_hash + fabric_hash) is the parent
envelope; `CandidateRecord` is the non-semantic provenance record (§20).

### 6.1 Semantic ownership index (exactly one owner per concept)

| Semantic | Sole owner |
|---|---|
| router/link graph, ports, channels, seats | TopologyArtifact |
| which AgentInstance occupies which seat | AgentAttachmentArtifact |
| endpoint_id namespace | AgentAttachmentArtifact |
| router routing behavior (`RoutingClass`, next-hop sets) | RouteArtifact (router-level) |
| endpoint→router binding, LOCAL_EJECTION, endpoint route table | ResolvedRouteArtifact |
| VC IDs, VC↔RoutingClass binding, transitions, escape designation | VCAssignmentArtifact |
| TrafficClass vocabulary | Design revision (B1) |
| physical channel beat width | TopologyArtifact (`DirectedChannel.width_bits`) |
| logical flit width + header field layout + encodings | PacketFormatArtifact |
| buffer capacity/credit/allocator/arbitration/pipeline | RouterBehaviorArtifact |
| plane composition | FabricArtifact |
| composite fabric identity | FabricArtifact (`fabric_hash`) |
| design+mapping+fabric binding | ResolvedFabric (`resolved_fabric_hash`) |
| generation provenance, GUIDED choices, candidate id | CandidateRecord (non-semantic) |

**Circularity rule:** TopologyArtifact does **not** depend on
AgentAttachmentArtifact. It exposes local attachment *seats*; the attachment
artifact assigns agents to them. No artifact depends on a descendant.

## 7. Node / router / link semantics

### 7.1 Router
- **Identity:** stable dense integer `router_id ∈ [0, router_count)`, independent
  of backend formatting; optional coordinate labels are attributes, not identity.
- Attributes: `router_id`, optional `coordinates`, `ports`, local seat capacity.
- **Owner:** TopologyArtifact.

### 7.2 RouterPort
- `(router_id, port_id, role)`, role ∈ {`local`, `link`}.
- `local` ports are attachment seats; `link` ports carry channels.
- Irregular topologies must be representable; no N/E/S/W assumption.

### 7.3 DirectedChannel and PhysicalLink
- **DirectedChannel** is the primary routing/deadlock resource:
  ```
  channel_id
  src_router, src_port, dst_router, dst_port
  width_bits
  latency
  route_weight
  optional physical_link_id
  ```
- `channel_id` replaces any notion of "logical channel index"; it is a stable
  identity, not a positional index.
- **PhysicalLink** is an *optional physical grouping* of one or more
  DirectedChannels. It may own implementation metadata: physical grouping,
  length, layer, die boundary. It is not necessarily a symmetric pair.
- Behavioral network properties (width, latency, weight) live on the
  DirectedChannel first. If v1 requires symmetric bidirectional channels,
  validate `A→B.width == B→A.width` and `A→B.latency == B→A.latency`; symmetry is
  a checked constraint, not a base-model assumption.

### 7.4 Materialized topology is the authority
A family name is intent metadata. The authoritative topology is the materialized
`{routers, ports, channels, links}`. Certification and backend equivalence compare
materialized structures, never names.

### 7.5 Canonical numbering (pinned here; implemented in B3.1)
Hash stability requires a versioned canonical ordering:
- **Regular families:** routers numbered by canonical coordinate order
  (row-major over declared dimensions); coordinates are the identity.
- **Imported/custom graphs:** input router IDs are semantic and preserved.
  (An alternative versioned canonical remapping may replace this only with a
  schema-version bump.) This is the pinned v1 choice.
- **Ports:** allocated by role, then ascending connected `router_id`, then local
  seat index.
- **Channels:** `channel_id` assigned densely in sorted
  `(src_router, src_port, dst_router, dst_port)` order.
- **Endpoints:** `endpoint_id` assigned densely in canonical attachment order
  `(router_id, port_id)`.
All four rules are part of the artifact schema version; changing them changes
identity. This prevents reintroducing graph-order hash drift after B1 removed
JSON-order drift.

## 8. Agent attachment semantics

```text
AgentInstance (B2: group_index, instance_index, kind)
      │
      ▼
Endpoint (logical fabric-addressable attachment; 1:1 with AgentInstance in v1)
      │
      ▼
NetworkInterface (protocol label, clock/power domain, future width adaptation)
      │
      ▼
RouterPort (local seat)
      │
      ▼
Router
```

- **Owner:** AgentAttachmentArtifact. Inputs: TopologyArtifact (seats) and the
  DesignRevision/NodeInventory agent universe (interface semantics). It selects
  seats; it does not create them. MappingArtifact does NOT participate in
  attachment derivation — rank placement is a ResolvedFabric seam concern.
- **Every hardware AgentInstance attaches**, compute or not: compute tiles, HBM
  controllers, NICs, peripherals, UCIe ports, and idle compute instances. An
  active `LogicalRank` is not required to attach an agent.
- **Concentration:** `endpoints_per_router` is explicit and bounded by the
  topology's local seat capacity; never inferred independently by simulator and
  RTL.
- **Endpoint IDs** are canonical fabric attachment IDs (§7.5). `AddressRange.
  target_agent_idx` identifies an Agent *group*; it does **not** assign endpoint
  IDs. Address→endpoint decode tables are a later NI concern.
- **Owns:** `endpoint_id`, `AgentInstance`, `RouterPort`, and an immutable
  `AgentInterfaceDescriptor` (`data_width_bits`, `address_width_bits`,
  `protocol`, `clock_domain`, `power_domain`) derived from the parent Agent
  group in the design revision.
- **B3.1d identity boundary:** the attachment's only semantic parent is
  `topology_hash`. DesignRevision and NodeInventory are derivation/validation
  SOURCES, not identity parents; the copied `AgentInterfaceDescriptor` is how
  design-derived hardware semantics propagate. Validation proves the
  attachment contains exactly the AgentInstance universe implied by the design
  (no missing idle agents, no fabricated extras), `group_index` exists,
  `instance_index < group.count`, kind agrees, each interface equals the parent
  group's width/address/protocol/clock/power semantics, every router/port is a
  real topology seat, and every seat is occupied at most once. Mapping
  placement legality is checked at the ResolvedFabric seam and never changes
  attachment identity.
- **Does not own flit width.** Flit width belongs to PacketFormatArtifact (§6.1).
- **v1 decision:** `Endpoint` and `NetworkInterface` are one semantic attachment
  object. The distinction is documented for future protocol bridges, not
  instantiated.
- **Width conversion** is an NI responsibility. For B3 v1, an
  `agent_interface_width` incompatible with the supported packetizer is
  `UNSUPPORTED`; it may not be silently ignored by one backend. A dedicated
  interface-adaptation artifact is introduced only if real conversion lands.

## 9. Topology semantics

- **Authority:** TopologyArtifact, derived from NodeInventory + GUIDED
  `topology_family`/`radix`/`concentration` + physical constraints. It does not
  depend on the attachment artifact (no circularity).
- **Sizing rule (v1):** router count is a derived consequence of endpoint count
  and concentration under the chosen family — never a hardcoded constant and
  never equal to model rank count by default.
- **Families:** mesh, torus, concentrated mesh, flatfly, GEC/express, fat-tree,
  anynet/custom, H-tree. Presence of an enum member is not support (§23).
- **Missing family params are an error**, not a default (§C-12).
- **AnyNet/custom:** explicit materialized channels; sequential router ids;
  unit weights in v1; non-unit weights refused on any path using the Python
  certification representation (verified doc §6.4).

## 10. Routing semantics

### 10.0 Two class namespaces (distinct)

- **TrafficClass** — *what the traffic is* (QoS/collective/required-behaviour
  identity). Owned by the design revision (B1/WorkloadIR later). B3 does not
  define the full taxonomy.
- **RoutingClass** — *which routing behavior a packet follows* (e.g. `FREE`,
  `ESCAPE`, `LATENCY_ROUTE`, `CUSTOM_CLASS_3`). Owned by RouteArtifact
  (router-level); carried into the endpoint realization by ResolvedRouteArtifact.

The mapping is `TrafficClass → VC (VCAssignmentArtifact) → RoutingClass
(ResolvedRouteArtifact over RouteArtifact)`. The bare word "class" is never
used for three things.

### 10.1 Policy vs realization
- **RoutingPolicy** label: `dimension_order | minimal | minimal_adaptive |
  up_down | valiant | custom`.
- **Materialized realization:**
  - deterministic: `(router, destination, RoutingClass) → next_hop`
  - adaptive: `(router, destination, RoutingClass, state) → allowed_next_hop_set`
- A policy label is never certification evidence; the realization is.

### 10.2 RouteArtifact (router-level)
Basis: existing `core/route_artifact.py` (strongest artifact). Reuse unchanged:
all-pairs coverage, `route_table_hash`/`artifact_hash` domain separation,
tie-break pinning, unit-weight enforcement, connectivity refusal,
sequential-id requirement. Evolve:
- **Parent hash: `topology_hash` only** — and for production it is
  `TopologyArtifact.topology_hash()` EXACTLY (one topology identity after
  B3.1). Standalone AnyNet graphs carry a routing-graph digest, exposed as
  `routing_graph_hash_from_adj`; they make no fabric claims and pass no
  endpoint identities.
- Entries are router/routing-class → directed-channel realization; next-hop
  router is derived from `channel_id` (parallel/express links are different
  resources even at the same neighbor). The channel-level column lands with
  the schema v2 route artifact (B3.2d); the current authoritative realization
  is the all-pairs first-hop table, validated against materialized channels.
- Add RoutingClass to entries; **no numeric VC assignment here** (that is
  VCAssignmentArtifact).

### 10.2.1 ResolvedRouteArtifact (fabric-level)
Parents: `topology_hash`, `attachment_hash`, `router_route_hash`. Owns the
endpoint interpretation: `endpoint_id → router_id`, `LOCAL_EJECTION` for
traffic whose endpoints share a router (never a fabricated hop), the
RoutingClass namespace, and an `endpoint_route_table_hash` computed from the
expanded semantic realization — without duplicating the full expanded table.
`from_dict` verifies SELF-integrity; `validate_against(topology, attachment,
router_route)` proves reference legality at the seam. `FabricArtifact` binds
`resolved_route_hash`, never the router-only `route_hash` — same router
network with different endpoint placement must be a different fabric.
- Bind and verify `topology_hash` against the materialized TopologyArtifact.
- Refuse partial tables from the public extraction helper as hard as the
  constructor does.
- `from_dict` must re-validate entry legality, not only hashes.

### 10.3 Exact route certification rule (hard invariant)
> No deadlock or routing PASS may be produced unless the proof reasons about the
> exact route realization used by the target backend/RTL, or mechanically proves
> equivalence to it. No exceptions.

**F6 invariant (B3.2):** F6 can never PASS from two independently generated
replicas of the same algorithm. Python agreeing with Python is not evidence.
PASS requires a `ResolvedRouteArtifact` plus independently backend-emitted
executed-route evidence (`booksim_dumped_table`, `booksim_ingested_artifact`,
`rtl_emitted_table`). Replica provenance is `INCONCLUSIVE`; unknown provenance
is `UNSUPPORTED`; no resolved artifact is `NOT_RUN`. Until backend route
evidence exists, F6 is honestly `NOT_RUN`/`UNSUPPORTED`.

### 10.4 Turn restrictions
Compiler-owned LOCKED, derived from the route realization; either derived from
RouteArtifact or proof evidence — never an independent table. Not a `NocConfig`
field (already true).

## 11. VC semantics

- A **VirtualChannel** is a resource `(channel, vc_id)` with its own buffer and
  credits.
- **VCAssignmentArtifact owns** (and only these):
  ```
  resolved_route_hash (parent)
  vc_count
  VC IDs
  traffic_class → allowed_vc_set
  vc → routing_class
  allowed VC transitions
  escape VC designation
  derivation method
  artifact_hash
  ```
- **It does not own buffering** (RouterBehaviorArtifact) and does not own
  routing behavior (RouteArtifact). Deadlock reasoning composes the three.
- **BookSim reality:** `num_vcs` exposes VCs as buffering resources;
  `min_anynet` does not instantiate RTL escape-routing semantics (verified doc
  §3.4). Escape-based deadlock claims must bind a backend that implements escape
  routing.
- **Extensibility:** accommodates multiple traffic classes, adaptive+escape, QoS
  partitions, and (later) multicast without replacement.

### 11.1 VC limits
| Limit | Value | Source |
|---|---|---|
| `PLANE_C_MAX_VC` | 8 (env `VERITX_MAX_VC`) | `constants.py:89-92` |
| BookSim `num_vcs` | 16 built-in / 4 BASE_PARAMS / 2 constants | `booksim_config.cpp:110`; `booksim.py:52`; `constants.py:31-39` |
| RTL class field | `ceil(log2(vcs))`; 1 bit at 2 VCs | `gen_rtl.py:110-116` |
| RTL `BUF_DEPTH` | 8 default | `gen_rtl.py:909` |

Required > supported ⇒ `UNSUPPORTED`/`INFEASIBLE`, never a silent `min()`
(C-05, C-14). Assignments are validated against `vc_count`.

## 12. Deadlock-proof semantics

Distinct proof methods (no universal theorem):
```text
DETERMINISTIC_DOR_THEOREM
CHANNEL_DEPENDENCY_ACYCLIC
CHANNEL_VC_DEPENDENCY_ACYCLIC
ESCAPE_SUBNETWORK_THEOREM   (escape class must be a real, separate VC class)
FORMAL_BOUNDED_CHECK
```
Every certificate binds `topology_hash`, `attachment_hash`,
`resolved_route_hash`, `vc_hash`, `router_behavior_hash`, `proof_method`,
`evidence`, `tool`, `scope`.

Ruling: the abstract workload dependency graph and `derive_vc_*` are
candidate-generation heuristics only, never the deadlock proof (verified doc
§3.4). `dependency cycles → vc_count` is removed from certification.

## 13. Packet / flit semantics

Current state (C-09): four incompatible layouts. A single
**PacketFormatArtifact** is authoritative; every backend derives its encoding
from it. Current RTL is a migration target, not the definition (§14.5, §21).

**Width ownership (B3.4):**
```
TopologyArtifact.DirectedChannel.width_bits = physical channel beat width
PacketFormatArtifact.flit_width_bits         = logical flit width
```
Srota v1 transfers exactly one logical flit per channel beat, so the two must
be equal. That equality is a v1 constraint, not a permanent conceptual
equivalence. The ASTRA `ASTRASIM_FLIT_BYTES` coarse-packetization knob is an
execution-fidelity override and is explicitly NOT fabric width authority.

**v1 wire fields (exactly these, repeated in EVERY flit):**
```
payload               opaque to the router
source_endpoint       endpoint namespace, PACKET_IMMUTABLE
destination_endpoint  endpoint namespace, PACKET_IMMUTABLE
flit_type             SINGLE/HEAD/BODY/TAIL, FLIT_STRUCTURAL
vc_id                 HOP_LOCAL (rewritable only by a legal VC transition)
```

**Deliberately not on the wire in v1:**
```
TrafficClass   injection-time intent (traffic_class_to_vcs)
RoutingClass   derived from vc_out via VCAssignmentArtifact
sequence       NI / protocol / testbench responsibility
protocol meta  NI/protocol payload (AXI/CHI/UCIe/...)
multicast      workload lowering only in v1 (no fabric primitive)
```

Addresses are protocol payload too: address→endpoint decoding happens at
injection/NI (`AddressDecodeArtifact`) and selects the PacketFormat
`destination_endpoint_id`; no address field enters the flit, and no flit
header is interpreted as an address.

Packetization v1 is `BOUNDED_WORMHOLE` with identity-bearing
`max_packet_flits` (default 8). A larger message is fragmented by the
NI/lowerer into multiple bounded network packets; one message must never become
one unbounded wormhole packet.

Canonical bit layout, pinned LSB → MSB:
```
payload | source_endpoint | destination_endpoint | flit_type | vc_id
```
with `endpoint_width = encoding_width(E)`, `vc_width = encoding_width(V)`,
`encoding_width(n) = max(1, ceil(log2(n)))`, `type_width = 2`, and
`payload_width = flit_width_bits - header_width >= 1` (otherwise UNSUPPORTED;
the physical link is never widened automatically). Flit-type encoding is
identity-bearing: HEAD=0, BODY=1, TAIL=2, SINGLE=3.

**Capacities are derived, not duplicated.** `endpoint_capacity = 2**endpoint_width`
and `vc_capacity = 2**vc_width` are derived properties. Cross-artifact
validation checks actual counts ≤ capacity (endpoints ≤ endpoint capacity,
`vc_count` ≤ encoded VC capacity). There is no second way to represent a limit.

Observed layouts to reconcile (for migration, not authority):
`gen_rtl.py:126-146` / `router_template.sv:112-126`; `axi4_flit.sv:1-20,94-105`;
`rtl/mot_htree/noc_pkg.sv:23-33`; `gen_rtl_2die.py:237-247`; UVM `noc_mesh`
(absent). `src` placement in the rtlgen layout is AMBIGUOUS (package omits it;
TB places it at `[60:54]`).

## 14. Router behavior semantics

`RouterBehaviorArtifact` (renamed from the underspecified "FlowControlArtifact")
is the sole owner of router microarchitecture and flow control:
```
buffer capacity / organization
credit semantics
route reservation
tail-release semantics
VC allocator
switch allocator
arbitration
escape priority / anti-starvation
router speedups (input/output/internal)
semantic router pipeline latency
field classification table: FABRIC_SEMANTIC | BACKEND_IMPLEMENTATION_DETAIL
artifact_hash
```
Backend-only simulator sampling/staging (`sample_period`, `max_samples`, `seed`,
`sim_type`) stays outside and never enters `fabric_hash`.

### 14.1 Arbitration inventory
| Mechanism | rtlgen router | H-tree router | BookSim |
|---|---|---|---|
| VC allocation | escape-first + RR free | iSLIP (`islip.sv`) | islip |
| Switch allocation | single registered output stage | iSLIP | islip |
| Escape priority | yes, `ESC_YIELD_K=4` | n/a | none |
| QoS priority | none | none | none (classes=1) |

`NocConfig.arbitration` is a GUIDED label that currently selects none of these;
recorded, not enforced (C-family).

### 14.2 Pipeline classification
- **Fabric semantic:** channel latency, GEC deferred routing (`routing_delay=1`
  architectural there), speedups, buffer depth.
- **Backend implementation detail:** simulator staging where observable
  semantics are unchanged.

### 14.3 Buffer depth ruling (closed)
**GUIDED with compiler-derived LOCKED minimum.** The user may propose a buffer
depth; the optimizer may vary it; the compiler rejects or raises it when below
the architectural minimum for the resolved VC/flow-control semantics.

### 14.4 RouterBehaviorArtifact v1 baseline (B3.4, schema v2)
Parent: `vc_assignment_hash` only. It references the VC structure; it never
duplicates VC ids, transitions or routing classes.
```
buffer organization          PER_INPUT_PORT_PER_VC
input buffer depth           8 flits / VC
output stage depth           1 flit / VC
flow control                 CREDIT (one-flit granularity, per channel+VC)
credit return latency        1 cycle
VC reuse                     WAIT_FOR_TAIL_CREDIT
VC allocator                 ISLIP
switch allocator             ISLIP
allocator iterations         1
hold switch for packet       false (switch arbitrated per flit)
input VC packet policy       ONE_PACKET_AT_A_TIME
VC allocation scope          PACKET (HEAD selects vc_out; BODY/TAIL reuse it)
input/output/internal speedup 1 / 1 / 1
route compute                0 cycles
VC allocation                1 cycle
switch allocation            1 cycle
switch traversal             1 cycle
output delay                 0 cycles
implicit demotion            none
implicit VC / escape priority none
```
Channel traversal latency remains solely `DirectedChannel.latency_cycles`.

### 14.5 B3.4 authority vs current implementation (migration gaps)
This table records explicit B3.6/B3.7 obligations; it is not a conformance
claim for any existing backend.

| Semantic | B3.4 authority | Current implementation |
|---|---|---|
| destination | endpoint id | rtlgen router id |
| source | full endpoint id | rtlgen truncated/ambiguous |
| VC | hop-local `vc_id` | rtlgen calls it class/escape |
| TrafficClass | injection-only | no exact equivalent |
| RoutingClass | derived from VC | separate RT_MIN/RT_ESC assumptions |
| max packet | 8 flits default | ASTRA can currently inject message-sized packet |
| buffer | per-input-port/per-VC, 8 | similar but local quirks |
| allocator | iSLIP default | rtlgen custom RR/priority |
| demotion | none | stale/partial historical code |
| switch hold | false | implementation-specific |
| flit width | equals channel width v1 | RTL fixed 64; ASTRA coarse override may differ |
| address decode | AddressDecodeArtifact v2 (semantic ranges, IDENTITY forwarding, width-checked, singleton groups) | rtlgen `gen_rtl_2die.py::addr_to_router()` upper-bit decode | B3.6 removes |

## 15. Multicast / multi-plane semantics

- **Multicast (v1):** workload-lowering only. `NocConfig.mcast_groups` /
  `mcast_setup_cycles` are a message-count model; the fabric primitive is
  `UNSUPPORTED`. No fabric claim of multicast acceleration is permitted. These
  knobs therefore do not affect `fabric_hash`; changing them may change
  `design_hash` but not hardware identity. Any backend claiming multicast
  hardware acceleration stays `UNSUPPORTED` until a real fabric-semantic
  primitive exists.
- **Multi-plane (closed ruling):** plane count/membership is **FABRIC SEMANTIC**
  and therefore affects `fabric_hash`. A plane is a complete fabric instance;
  plane membership, per-plane route/VC artifacts, and per-plane certificates are
  explicit. The current hardcoded `"cross_plane_independence": True` /
  per-plane `"acyclic": True` (`gen_rtl.py:1064-1066`) must become computed
  evidence or `NOT_RUN`. Implementation may remain unsupported/partial.

## 16. Clock / power / protocol boundaries

- **Clock (v1 gate):** endpoint interface descriptors carry `clock_domain`
  (`None` = DEFAULT). Fabric v3 supports exactly one effective endpoint clock
  domain; multiple domains are `UNSUPPORTED` because no CDC mechanism is
  represented in fabric identity.
- **Power (v1 gate):** endpoint interface descriptors carry `power_domain`
  (`None` = DEFAULT). Fabric v3 supports exactly one effective endpoint power
  domain; multiple domains are `UNSUPPORTED` because isolation/level-shifter
  hardware is not represented. `PhysicalContext.num_power_domains` remains
  implementation context and creates no fabric semantics.
- **RCU (v1 gate):** `NocConfig.rcu_enabled` has no owning artifact/behavior in
  Fabric v3. `None`/`False` resolve to the ordinary non-RCU fabric;
  `rcu_enabled=True` is `UNSUPPORTED` at the ResolvedFabric seam, never silently
  resolved to the non-RCU fabric.
- **Protocol:** `Agent.protocol` changes nothing below the NI; the fabric model
  does not claim protocol adaptation semantics. Unsupported protocol semantics
  fail closed.
- **Collateral / implementation context:** `output_formats`,
  `obfuscation_level`, `process_node_nm`, `default_clock_freq_mhz` and physical
  estimation outputs are generation/implementation concerns. They may change
  DesignRevision or generated-implementation identity but never `fabric_hash`.

## 17. Artifact definitions

All artifacts: frozen, schema-versioned, canonical-JSON hashed with a
domain-separated tag `srota/<Artifact>/v<schema>`, fail-closed on unknown
fields (B1 discipline).

### TopologyArtifact
Routers, RouterPorts, DirectedChannels, optional PhysicalLinks, local seat
capacity. Parents: none (inputs NodeInventory + GUIDED recorded in envelope).

### AgentAttachmentArtifact
`endpoint_id → (AgentInstance, RouterPort, AgentInterfaceDescriptor)` where the
descriptor owns `data_width_bits`, `address_width_bits`, `protocol`,
`clock_domain`, `power_domain`. Parent: `topology_hash` only; DesignRevision and
NodeInventory are derivation/validation sources and MappingArtifact is a
ResolvedFabric seam concern. Validation proves the complete design agent
universe. v1 (no interface descriptor) and v2 (design/mapping over-binding)
attachments are refused on load.

### RouteArtifact (router-level)
Parent hash `topology_hash` (== `TopologyArtifact.topology_hash()` for
production; a routing-graph digest for standalone AnyNet); `routing_algorithm`
(exact version); RoutingClass namespace; entries (deterministic next-hop or
adaptive allowed set by class, ultimately `channel_id`); `tie_break_policy`;
`route_table_hash`; `artifact_hash`. No attachment, no endpoint ids, no
numeric VC assignment.

### ResolvedRouteArtifact (fabric-level)
Parents `topology_hash`, `attachment_hash`, `router_route_hash`; endpoint→router
map; routing classes; `endpoint_route_table_hash` (expanded realization,
`LOCAL_EJECTION` included); `resolved_route_hash`. `from_dict` = self-integrity;
`validate_against(topology, attachment, router_route)` = parent legality.

### VCAssignmentArtifact
Parent `resolved_route_hash` + design TrafficClass namespace; §11 fields;
`artifact_hash`. No buffering.

### PacketFormatArtifact
Parents `topology_hash`, `attachment_hash`, `vc_assignment_hash`; §13 fields;
derived capacities; `artifact_hash`.

### RouterBehaviorArtifact
Parent `vc_assignment_hash`; §14 fields; `artifact_hash`.

### AddressDecodeArtifact
Parent `attachment_hash`; entries transport `(name, base, size,
target_agent_group, target_endpoint_id)`. Hardware identity per entry is
`(base, size, target_agent_group, target_endpoint_id)` — `name` is
non-semantic presentation and is excluded from `address_decode_hash` and from
canonical order. `address_transform = IDENTITY` (the selected endpoint receives
the original address unchanged; no base subtraction/translation/aliasing),
`unmatched_address_policy = ERROR`; domain `srota/AddressDecode/v2` (v1 is
refused). Derived from `CompileRequest.address_map` + attachment without
binding `design_hash`. v2 requires singleton target Agent groups (multi-instance
-> UNSUPPORTED) and requires `base + size <= 2 ** target endpoint
address_width_bits` (no truncation/width adapter).
`validate_against_attachment(attachment)` proves hardware legality alone;
`validate_against(address_map, attachment)` proves design-map equivalence by
comparing semantic fields only. Addresses stay protocol payload; the decoder
selects the PacketFormat destination endpoint at injection. Legacy
`gen_rtl_2die.py::addr_to_router()` is non-authoritative and B3.6 must remove it.

### FabricArtifact
Parents: `topology_hash`, `attachment_hash`, `resolved_route_hash`,
`vc_assignment_hash`, `packet_format_hash`, `router_behavior_hash`,
`address_decode_hash`, plus `plane_composition` (`SINGLE_PLANE` only in v1).
Contains no design_hash, mapping_hash, backend bytes/paths/run ids/git/
timestamps/seeds, candidate provenance, metrics or verification evidence.
`validate_against(...)` is hardware-only (no DesignRevision/AddressMap/Node/
Mapping required): it revalidates topology seats, the router route, the address
decode against the attachment, clock/power single-domain gates, and the
ResolvedRoute/VC/PacketFormat/RouterBehavior DAG. Persisted hash key
`fabric_hash`; domain `srota/Fabric/v3` (v1 and v2 are refused). NOTE: the
legacy `core.fabric.FabricArtifact` is backend/executed evidence, not this
object; its rename is deferred to B3.7.

### BackendConfigArtifact
`{backend, backend_binary_sha256, fabric_hash, rendered_config_sha256,
auxiliary_files[{name,sha256}], lowering_version, semantic_loss[SemanticLoss],
artifact_hash}`.

### ResolvedFabric (semantic)
`design_hash + mapping_hash + fabric_hash`; domain `srota/ResolvedFabric/v1`;
persisted hash key `resolved_fabric_hash`. `validate_against(...)` proves the
three root hashes, the attachment↔design/inventory seam, the
mapping↔attachment placement seam (exact `(group_index, instance_index, kind)`
identity; idle agents legal), the rank-space seam (`mapping.rank_count ==
inventory.rank_count` and ranks equal), and then the full FabricArtifact DAG.
No backend execution or candidate provenance.

### CandidateRecord (non-semantic)
`candidate_id`, `resolved_fabric_hash`, `guided_choices`, generator name/version,
search iteration, parent candidate, derivation explanation, generation
provenance. Never enters `fabric_hash`.

### SemanticLoss (structured)
```
semantic_dimension
source_artifact_hash
source_path
loss_kind
reason
affected_metrics
certification_consequence
```
Hard rule: if a backend loses a semantic dimension required by the requested
certification/comparison target, that target is `UNSUPPORTED`. Losses are
expected for analytical projection; fatal for exact RTL↔BookSim equivalence.

## 18. Identity and hash rules

- **Semantic fields:** any change to hardware or its execution changes identity.
- **Non-semantic:** file path, JSON whitespace/key order, run id, timestamp,
  seed, git SHA, sample count, generation provenance, candidate id.
- **Domain separation:** `srota/<Artifact>/v<schema>\0` + canonical JSON.
- **Parent binding:** a child never embeds its parent; the parent envelope binds
  child hashes and validates relationships at the seam.

| Artifact | Parent hashes | Hash domain |
|---|---|---|
| TopologyArtifact | — | `srota/TopologyArtifact/v1` |
| AgentAttachmentArtifact | topology_hash | `srota/AgentAttachment/v3` |
| RouteArtifact | topology_hash | `srota/RouteArtifact/v1` |
| ResolvedRouteArtifact | topology_hash, attachment_hash, router_route_hash | `srota/ResolvedRouteArtifact/v1` |
| VCAssignmentArtifact | resolved_route_hash | `srota/VCAssignment/v1` |
| PacketFormatArtifact | topology_hash, attachment_hash, vc_assignment_hash | `srota/PacketFormat/v1` |
| RouterBehaviorArtifact | vc_assignment_hash | `srota/RouterBehavior/v2` |
| AddressDecodeArtifact | attachment_hash | `srota/AddressDecode/v2` |
| FabricArtifact | topology, attachment, resolved_route, vc, packet, router_behavior, address_decode, plane_composition | `srota/Fabric/v3` |
| BackendConfigArtifact | fabric_hash | `srota/BackendConfig/v1` |
| ResolvedFabric | design_hash, mapping_hash, fabric_hash | `srota/ResolvedFabric/v1` |

## 19. Cross-artifact invariants

Enforced at the ResolvedFabric seam (discharges B2's deferred parent binding):

- every mapping agent exists in NodeInventory; kind agrees; group/instance exist;
- every attachment endpoint's group_index/instance_index/kind exist in the design
  revision, its interface descriptor equals the parent Agent group's
  data_width/addr_width/protocol/clock/power semantics, and the attachment
  contains exactly the AgentInstance universe implied by the design (no missing
  idle agents, no fabricated extras);
- every mapping placement points at an attached AgentInstance — a ResolvedFabric
  seam invariant that does not alter attachment identity;
- mapping rank count equals the NodeInventory rank count and the mapping ranks
  are exactly the inventory logical rank ids;
- `resolved_fabric_hash = H(design_hash, mapping_hash, fabric_hash)` is the only
  identity in which design and mapping meet hardware; the same fabric under a
  different mapping keeps `fabric_hash` and changes `resolved_fabric_hash`;
- every attachment endpoint references a real topology seat (router exists, port
  < seat capacity); every agent attaches exactly once; seats not exceeded.
  `attachment.validate_against_topology(topology)` proves these hardware-only
  facts without design context; FabricArtifact calls it directly, and the
  design/inventory completeness check composes it;
- `router_route.validate_against(topology)` is part of the FabricArtifact seam:
  parent-hash equality alone does not prove channel legality or all-pairs
  route termination;
- For ResolvedFabric, `inventory.parallelism == ParallelismShape(workload.tp,
  workload.pp, workload.ep, workload.dp)` and `inventory.ranks` equals the
  canonical rank namespace recomputed for that shape; equal world size with a
  different TP/PP/EP/DP geometry is refused;
- **`resolved_route.topology_hash == topology.topology_hash()`** and
  **`resolved_route.attachment_hash == attachment.artifact_hash`** and
  **`resolved_route.router_route_hash == route.artifact_hash`** (refuse
  otherwise); `validate_against()` proves every endpoint and every needed
  router pair is covered;
- every route hop corresponds to a real `channel_id`; every destination
  reachable; no partial tables; entry legality re-validated on load;
- every VC id `< vc_count`; every TrafficClass has legal VC eligibility; every VC
  maps to a RoutingClass present in RouteArtifact; assignments never reference a
  VC ≥ count;
- packet encoded capacities ≥ actual endpoint and VC counts (v1 has no class/sequence wire fields);
- router behavior covers every implemented VC;
- address decode entries equal the materialized decode of `design.address_map`
  against the attachment by SEMANTIC fields only (range names are presentation);
  forwarding is IDENTITY; target Agent groups are singleton; ranges are
  non-overlapping, within the address domain, and fit the target endpoint's
  address interface; addresses never enter flit headers;
- FabricArtifact validate_against is hardware-only; ResolvedFabric separately
  proves decode/design-map equivalence and refuses `NocConfig.rcu_enabled=True`;
  attachments spanning multiple effective clock or power domains are
  `UNSUPPORTED` (no CDC/isolation semantics in Fabric v3);
- FabricArtifact binds exactly the six child semantic hashes plus
  plane_composition and revalidates the complete child DAG; a set of
  individually valid artifacts that cannot form one DAG is refused;
- FabricArtifact contains no design, mapping, backend or evidence fields;
  `resolved_fabric_hash = H(design_hash, mapping_hash, fabric_hash)` is the
  only place design and mapping meet hardware identity;
- `fabric_hash` recursively covers every identity-bearing dimension, including
  plane composition;
- deadlock certificate hashes the exact topology+attachment+route+VC+router
  behavior;
- every `semantic_loss` has a declared certification consequence.

## 20. Candidate semantics

- **Candidate synthesis** (architecture) is separate from **candidate
  evaluation** (measurement). Any architecture-affecting decision is resolved
  before BackendConfigArtifact generation; a backend may not finish architecture
  decisions during evaluation.
- **ResolvedFabric** is semantic: `resolved_fabric_hash = H(design_hash,
  mapping_hash, fabric_hash)`.
- **CandidateRecord** is non-semantic provenance. Two optimizer paths that
  converge on the same hardware share `resolved_fabric_hash`; they do not
  invent separate hardware identities.

## 21. Backend lowering contracts

General: `FabricArtifact → (lowerer, lowering_version) →
BackendConfigArtifact`. The lowerer emits or explicitly declares every
architecture-affecting value; `semantic_loss[]` lists anything unrepresentable.

### 21.1 BookSim
| Srota semantic | BookSim | Lossless? |
|---|---|---|
| materialized topology | `topology`/`k`/`n`/`network_file` | mesh/torus/anynet yes; others partial |
| route realization | `routing_function` or route table | **NO** — BookSim computes `min_anynet`; must ingest or dump (C-01/C-02) |
| vc_count | `num_vcs` | yes, but buffering-only semantics |
| vc buffer depth | `vc_buf_size` | yes |
| packetization | `packet_size` | yes (8 vs ASTRA 64 divergence) |
| flow control | `wait_for_tail_credit`, `hold_switch_for_packet` | partial; latter never emitted |
| arbitration | `vc_allocator`/`sw_allocator`/`arb_type` | partial |
| pipeline | delays | execution detail |
| link width/latency | none | **loss** — declared |

### 21.2 RTL
Consumes TopologyArtifact adjacency/channels, ResolvedRouteArtifact tables,
VCAssignmentArtifact bindings, PacketFormatArtifact layout,
RouterBehaviorArtifact parameters, plane composition — never re-deriving them.
Current generator violates this (C-01/C-04).

### 21.3 Analytical
Declares representable topology classes, congestion model, units, and
`semantic_loss[]` with consequences.

### 21.4 SystemC
`NOT IMPLEMENTED`. Intended contract: consume FabricArtifact + WorkloadIR,
implement packet/flit format and router behavior from artifacts, declare
fidelity.

## 22. SystemC status

No first-party SystemC model exists. Recorded unimplemented; contract only. No
support may be claimed.

## 23. Support matrix

Vocabulary used consistently everywhere: `SUPPORTED`, `PARTIAL`, `UNSUPPORTED`,
`UNKNOWN`. Where useful, a distinction is marked: `R` representable, `E`
executable, `C` certifiable. Never inferred from a name.

| Capability | Intent | TopologyIR | BookSim | Analytical | RTL | Route cert | Deadlock cert | Certifiable today |
|---|---|---|---|---|---|---|---|---|
| mesh | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | PARTIAL | PARTIAL | UNSUPPORTED (route mismatch) |
| torus | SUPPORTED | SUPPORTED | SUPPORTED | PARTIAL (Ring) | PARTIAL | PARTIAL | PARTIAL | UNSUPPORTED |
| ring | PARTIAL (via torus) | SUPPORTED | SUPPORTED (1-D torus) | SUPPORTED (Ring) | PARTIAL | PARTIAL | PARTIAL | UNSUPPORTED |
| star/switch | UNSUPPORTED (no enum) | SUPPORTED | SUPPORTED (anynet) | SUPPORTED (Switch) | UNSUPPORTED | PARTIAL | PARTIAL | UNSUPPORTED |
| anynet/custom | PARTIAL | SUPPORTED | SUPPORTED | UNKNOWN (needs dims) | SUPPORTED | PARTIAL | PARTIAL | UNSUPPORTED |
| GEC/express | PARTIAL | UNSUPPORTED | PARTIAL | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED |
| concentrated mesh | SUPPORTED (GUIDED) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED |
| fat-tree | SUPPORTED (GUIDED) | UNSUPPORTED | PARTIAL | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED |
| H-tree | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | PARTIAL (no harness) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED |
| deterministic routing | SUPPORTED | PARTIAL | SUPPORTED | PARTIAL | SUPPORTED | SUPPORTED | SUPPORTED | UNSUPPORTED (realization) |
| adaptive routing | PARTIAL (label) | UNSUPPORTED | PARTIAL | UNSUPPORTED | PARTIAL (escape) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED |
| escape routing | PARTIAL | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | SUPPORTED | UNSUPPORTED | PARTIAL | UNSUPPORTED |
| N VCs | PARTIAL (derived) | UNSUPPORTED | PARTIAL (buffering) | UNSUPPORTED | PARTIAL (2 classes) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED |
| multicast | PARTIAL (model) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED |
| multi-plane | PARTIAL (flag) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | PARTIAL (duplication) | UNSUPPORTED | PARTIAL (hardcoded) | UNSUPPORTED |
| credit flow control | PARTIAL | UNSUPPORTED | SUPPORTED | UNSUPPORTED | SUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED |
| width conversion | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED |
| QoS arbitration | PARTIAL (label) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED |
| CDC | PARTIAL (fields) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | PARTIAL (`cdc_fifo.sv`) | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED |

Note: a backend may be `SUPPORTED` for representation/execution while
`UNSUPPORTED` for certification of the complete Srota fabric semantics.

## 24. LOCKED / GUIDED / FREE matrix

| Decision | Tier | Rationale |
|---|---|---|
| topology_family | GUIDED | user proposes, engine may adjust |
| radix / concentration | GUIDED | user proposes; sizing derived |
| arbitration preference | GUIDED | high-level preference |
| RCU | GUIDED | scope knob |
| link width | GUIDED | physical |
| buffer depth | GUIDED + LOCKED minimum | user proposes; compiler enforces architectural floor (§14.3) |
| output models | FREE | collateral |
| obfuscation | FREE | IP protection |
| materialized graph / seats | DERIVED CONSEQUENCE | from inventory + GUIDED |
| endpoint attachment | DERIVED CONSEQUENCE | from DesignRevision agent/interface semantics + NodeInventory + TopologyArtifact; MappingArtifact is a ResolvedFabric seam concern |
| routing algorithm / RoutingClass | LOCKED | inspectable |
| materialized routes | LOCKED | authority; evidence-linked |
| turn restrictions | LOCKED | derived from route realization |
| VC count / assignment | LOCKED | over-limit ⇒ UNSUPPORTED |
| escape policy | LOCKED | derived |
| packet format | LOCKED | derived from endpoint count + classes |
| router behavior protocol | LOCKED | credit-based v1 |
| plane composition | LOCKED | fabric semantic (affects `fabric_hash`) |
| pipeline stages | BACKEND + partial LOCKED | channel latency LOCKED; staging detail |

## 25. Verification obligations

- Every routing/deadlock PASS binds topology+attachment+route+VC+router-behavior
  hashes (§12).
- F1–F8 evidence-backed or `NOT_RUN`/`ASSUMPTION`/`UNSUPPORTED`.
- Formal is PASS only when a tool elaborates the exact RTL/property set.
- Reports render evidence; `validation.ok` computed, never hardcoded.
- CLI certification parses a structured verdict and honors exit codes.

## 26. Equivalence and "same" definitions

### 26.1 Requirement classes

| Dimension | Requirement |
|---|---|
| router/channel graph | MUST MATCH EXACTLY |
| endpoint attachment | MUST MATCH EXACTLY |
| route realization | MUST MATCH EXACTLY (or mechanically proven equivalent) |
| VC eligibility / routing-class binding | MUST MATCH EXACTLY |
| packet format width/fields | MUST MATCH EXACTLY |
| buffer capacity | MUST MATCH EXACTLY |
| router behavior semantics | MUST MATCH EXACTLY |
| arbitration class behavior | MAY DIFFER WITH DECLARED MODEL |
| pipeline staging | MAY DIFFER WITH DECLARED MODEL (observable equivalence) |
| link latency/bw model | MAY DIFFER WITH DECLARED MODEL |

### 26.2 Same definitions (verbatim)

> **Same topology:** equal `topology_hash`.

> **Same fabric architecture:** equal `fabric_hash`. `fabric_hash` recursively
> binds every identity-bearing hardware semantic including topology, attachments,
> routes, VC semantics, packet format, router behavior, plane composition, and
> any other direct fabric-semantic field.

> **Same resolved design:** equal `resolved_fabric_hash`, which binds
> `design_hash`, `mapping_hash`, and `fabric_hash`.

> **Same backend execution:** same resolved design/workload plus identical
> BackendConfigArtifact, backend binary/environment identity, seed policy, and
> execution fidelity.

Consequence: same hardware fabric with a different workload mapping yields the
same `fabric_hash` and a different `resolved_fabric_hash`.

## 27. Requirements and certification boundary

- Optimization may vary GUIDED knobs only; LOCKED correctness fields are derived
  per candidate. Hard constraints are never silently relaxed; a heuristic
  negative result is not a proof of non-existence.
- **Certification boundary:** a well-formed CandidateFabric is not certified.
  Certification requires separately tracked evidence (structural, route,
  deadlock, simulation, RTL functional, formal, physical).

## 28. Mutation-test obligations (B3 implementation)

- Topology: change one channel → `topology_hash` changes.
- Attachment: move one agent to another seat → `attachment_hash` changes.
- Route: change one next hop → `route_table_hash`/`route_hash` change; move one
  agent to another router at fixed router routes → `resolved_route_hash` changes
  while `route_hash` does not.
- VC: change one allowed VC or VC→RoutingClass binding → `vc_assignment_hash` changes.
- Packet: move one field bit → `packet_format_hash` changes.
- Router behavior: change buffer depth/allocator → `router_behavior_hash` changes.
- Plane: change plane composition → `fabric_hash` changes.
- Fabric: change any child → `fabric_hash` changes.
- Non-semantic formatting/provenance must not change any semantic hash.

## 29. B3 implementation plan

- **B3.0-pre** — graph determinism; dependency edge order becomes non-semantic;
  `COMPILER_SEMANTICS_VERSION` 1→2. **Migration rule:** v1 CompileRequests remain
  loadable under v1 semantics; new writes emit v2; a `migrate-design
  --to-semantics 2` path re-canonicalizes dependency order (order-insensitive)
  and records migration provenance (non-semantic). v1 is never re-emitted as v1
  with reordered edges. Exit: deterministic cycles; golden hash updated with
  rationale; zero regression.
- **B3.1** — TopologyArtifact (materialized, canonical numbering) +
  AgentAttachmentArtifact; attachment derived from DesignRevision agent/
  interface semantics + NodeInventory + TopologyArtifact (Mapping is a
  ResolvedFabric seam concern); sizing from inventory; no `k=8,n=2`.
  Exit: one materialized topology; reports consume it.
- **B3.2** — Two-tier routing: router RouteArtifact bound to the materialized
  TopologyArtifact, plus ResolvedRouteArtifact binding topology + attachment +
  router route. F6 requires the resolved artifact and independent
  backend-emitted executed evidence; replica-vs-replica is rejected. BookSim
  dump/ingest remains `UNSUPPORTED` until it lands. Exit: exactly one
  authoritative router-route realization, exactly one endpoint-resolved
  binding per candidate fabric, and no verification path can turn two
  replicas into an F6 PASS.
- **B3.3** — VCAssignmentArtifact + `(channel,VC)` CDG + proof registry; delete
  clamp semantics. Exit: deadlock PASS only with bound evidence.
- **B3.4** — PacketFormatArtifact + RouterBehaviorArtifact + addressability.
  Exit: one layout; RTL/UVM derive from it.
- **B3.5** — FabricArtifact (`fabric_hash`) + ResolvedFabric + cross-artifact
  validation; reports become renderers. Exit: B2 parent binding discharged.
- **B3.6** — RTL lowering convergence (demotion/P4/formal/UVM claims).
- **B3.7** — Backend lowerer migration + BackendConfigArtifact + structured
  SemanticLoss + serving honesty.
- **B3.8** — Adversarial/cross-backend qualification.

Dependencies: B3.0-pre → B3.1 → B3.2 → B3.3 → B3.4 → B3.5; B3.6/B3.7 after B3.5;
B3.8 last.

## 30. Migration / deprecation plan

| API/class | Verdict | Note |
|---|---|---|
| `model/topology_ir.py` | EVOLVE | materialization authority |
| `presets.Topology` | KEEP (narrow) | backend preset bridge |
| `core/fabric.py FabricArtifact` | EVOLVE→RENAME | executed evidence → `ExecutedFabric` |
| `core/route_artifact.py` | KEEP + EVOLVE | reuse hashing/coverage |
| `VCAssignment` (compile_model) | EVOLVE | becomes VCAssignmentArtifact |
| `derive_vc_count` | DEPRECATE | heuristic only |
| `derive_vc_assignment` | EVOLVE | candidate generation, not proof |
| `derive_topology_spec` | EVOLVE | size from inventory |
| `booksim.build_config` | EVOLVE | declared-semantics lowerer |
| `flow_certifier` route logic | EVOLVE | consume ResolvedRouteArtifact |
| RTL local route generation | DEPRECATE | consume ResolvedRouteArtifact |
| report topology arithmetic | DELETE | render FabricArtifact |
| `constants.BOOKSIM_DEFAULTS` | DELETE or DERIVE | one canonical table |
| `FlowControlArtifact` (name) | RENAME | → RouterBehaviorArtifact |

## 31. Open questions

- **OQ-1** BookSim↔RTL observable-equivalence definition (staging may differ
  only if equivalence is defined).
- **OQ-2** Weighted-link semantics end-to-end; tie-break/relaxation pinning per
  backend.
- **OQ-3** Multicast execution model (v1 lowering-only; fabric primitive roadmap).
- **OQ-4** Formal certification target: resolve the Yosys SV frontend blocker.
- **OQ-5** SystemC fidelity target (unimplemented).

Closed by B3.0.1: buffer depth tier (§14.3); plane composition semantics (§15);
address→endpoint relationship (§8).

## 32. Definition of Done (B3.0/B3.0.1)

A future engineer can answer, without reading simulator/RTL source: what a
fabric is and what makes two fabrics the same (`fabric_hash` vs
`resolved_fabric_hash`); router/endpoint/NI/port/channel/link semantics; the
topology and route authorities and their parents; what a VC means and when a
VC-count is evidence; how deadlock freedom is certified and what it binds; the
packet/flit format; which router-behavior semantics are architectural; the
LOCKED/GUIDED/FREE tiers; how a FabricArtifact becomes BookSim/RTL/analytical/
SystemC; which semantic losses are allowed; current support truth; and the
evidence required before a fabric is verified.

If any answer is "it depends which file you look at", B3.0 is not done.

### B3.0.1 acceptance checklist

1. no circular artifact derivation — §6, §6.1, §9;
2. one owner per semantic — §6.1;
3. two-tier routing: RouteArtifact parent is topology only; ResolvedRouteArtifact
   binds topology + attachment + router route — §10.2, §17, §19;
4. RoutingClass separates Route from VC resources — §10.0, §11;
5. VC and buffer ownership do not overlap — §11, §14;
6. flit width has one owner — §8, §13;
7. same fabric = `fabric_hash` — §26.2;
8. same resolved design distinct — §26.2;
9. candidate provenance non-semantic — §17, §20;
10. canonical numbering specified — §7.5;
11. DirectedChannel primary resource — §7.3;
12. structured SemanticLoss with consequences — §17, §21;
13. TrafficClass vs RoutingClass distinct — §10.0;
14. buffer/plane/address rulings closed — §14.3, §15, §8;
15. semantics-v1 migration stated — §29.

---

### Appendix A — Required authority diagram (target)
See §6.

### Appendix B — Required current-authority diagram
See §4.

### Appendix C — Contradiction register
See §5 (C-01 … C-29).
