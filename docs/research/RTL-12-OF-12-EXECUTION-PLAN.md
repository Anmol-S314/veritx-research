# Get the twelve RTL fabrics genuinely passing

 **Execution plan, not a completion claim.** Prepared 2026-11-08 from the approved lab plan, actual Constellation/native source, and the completed
 34-child Luna workflow. The implementation and validation described below have not been performed by writing this plan.

 ## Read this in the right order

 1. This document: goal, architecture decisions, priorities, dependencies and operating rules.
 2. [Work packages](rtl-12of12-plan/WORK-PACKAGES.md): executable assignments with code seams, deliverables, checks and stop conditions.
 3. [Acceptance specification](rtl-12of12-plan/ACCEPTANCE.md): the exact evidence needed for a family to turn green.
 4. [Agent briefs](rtl-12of12-plan/AGENT-BRIEFS.md): copy/paste instructions for the orchestrator, implementers, execution owner and reviewers.
 5. [External artifact update](rtl-12of12-plan/EXTERNAL-ARTIFACT-INTAKE.md): the other coding agent’s generation progress, observed candidate files/processes, and reuse-first intake strategy.
 6. [Previous-session handoff](RTL-M1-M8-HANDOFF-20261108.md): what was actually changed, where artifacts live and which reviews remain open. Use
 this as evidence, not as a new task list to repeat.

 The original requirements remain at:

 ```text
 /home/datavex/.cache/veritx-noc-lab/vla-native-execution/experiments/
   constellation_topology_rtl/ALL_TOPOLOGIES_IMPLEMENTATION_PLAN.md
 ```

 This plan replaces the previous execution sequence and checker-only task decomposition. It does **not** relax the original twelve-family finish
 line, resource caps, full connectivity, deadlock/progress, payload, replay or source-reproduction requirements. A genuine conflict with the
 original architecture must be resolved explicitly, not hidden in a new manifest.

 ## 1. The deliverable

 Deliver **twelve working Track A RTL fabrics** and a repeatable qualification command that freshly validates all twelve on one integrated,
 immutable source snapshot.

 Track A is a digital point-to-point realization of each declared connectivity/routing family. For SROTA/GEC, independent tap links are explicitly
 different from a shared physical channel. Those differences must remain visible.

 For each family, PASS requires all of:

 - Frozen independent native/configuration contract, including effective widths, buffers, VC ranges, identities and declared differences.
 - Correct production packet state, legal routing and runtime selection—not an unused Scala/Python model.
 - Complete reachable-state proof over actual physical buffer/VC resources, correct ejection and strictly decreasing route progress.
 - Full-size generated RTL, complete post-elaboration instance/wiring/terminal inventory and source/tool/config binding.
 - Actual emitted decoder behavior consistent with the independently checked routing relation.
 - Actual RTL packet/credit/stall/reset/drain tests, all 4,096 ordered terminal pairs, family-specific choices and required link witnesses.
 - Actual RTL replay of the two approved capture sets with exact byte/packet identity and causal checks.
 - Fresh reproduction and independent verification of that evidence from the same source snapshot.

 **Nothing less is called 12/12.** A generated file, a passing Python suite, a self-authored successful receipt, a top-level ejection trace, or a
 historical run cannot satisfy the complete conjunction.

 ### Scope that must stay separate

 - **Track B / M7:** three faithful shared-resource profiles for SROTA, GEC-MECS and GEC-hybrid. Required to finish the full M1–M8 program, but not
 a reason to mislabel or block unrelated Track A implementation/testing. Detailed package WP15 is separate.
 - **dragonflynew:** optional thirteenth family, with 72 terminals. Preserve its evidence, but never include it in the original denominator or let
 it substitute for an original family.
 - **Not claimed:** synthesis, timing closure, PPA, FPGA/ASIC qualification, physical electrical multidrop behavior, exact BookSim cycle timing, or
 performance superiority. Those need separate work/evidence.

 ## 2. Exact twelve-family target

 These values were read from `full-connectivity-v1/contracts/reference_contracts.json`; revalidate their hashes in WP00/WP02 before implementation.
 Directed links exclude terminal injection/ejection links. All twelve have 64 terminals, so all-pairs means 64×64, not router-count squared.

 | ID | Physical routers | Required directed Track A links | VCs/link | Buffer flits/VC | Payload bits | Main route contract |
 |---|---:|---:|---:|---:|---:|---|
 | mesh8x8 | 64 | 224 | 4 | 15 | 128 | Nonwrap X-then-Y DOR |
 | torus8x8 | 64 | 256 | 2 | 8 | 128 | Minimal DOR, directional datelines |
 | cmesh | 16 | 48 | 16 | 8 | 128 | Four terminal seats/router, no-express DOR |
 | fattree | 48 | 256 | 4 | 16 | 128 | Native NCA, all allowed upward alternatives |
 | flatfly | 16 | 96 | 8 | 4 | 128 | Injection XY/YX, disjoint four-VC halves |
 | srota8x8 | 64 | 896 | 4 | 8 | 128 | Configured O1TURN/FIU, rank VC discipline |
 | gec_mecs | 16 | 96 | 6 | 32 | 128 | Direct native tap-aware GEC DOR |
 | gec_hybrid | 16 | 144 | 8 | 32 | 128 | X-before-Y, live mesh/express occupancy choice |
 | qtree | 21 | 40 | 4 | 8 | 128 | Native QTree NCA and terminal attachments |
 | tree4 | 28 | 128 | 4 | 8 | 128 | Native multi-root NCA; sparse identities |
 | ring | 64 | 128 | 2 | 8 | 128 | Minimal direction, dateline VC split |
 | fly64 | 48 | 128 | 4 | 8 | 128 | Three-stage native destination-tag butterfly |

 Important identity rules:

 - Hybrid has **144 physical link instances but only 96 unique ordered router pairs**. Its 48 nearest-neighbor pairs each have separately credited
 mesh and express resources.
 - A native sparse address is not a physical instance count. Tree4 uses native IDs 0..3/16..23/32..47; QTree also has sparse native identifiers.
 Export both address mapping and actual instance count. Creating placeholder routing nodes to fill address holes changes the architecture.
 - Native builders contain some unrouted resources, e.g. the mesh/CMesh wrap discrepancy already recorded in the accepted contract. Preserve the
 extraction and explicit accepted mapping between native constructed resources and the required routed target. Do not treat that precedent as
 permission to prune any required link.
 - `mesh8x8-diag2vc`, `*-7g`, debug configurations and reduced-size outputs are not interchangeable with these rows. File existence and similar
 directory names prove nothing about profile identity or caps.

 ## 3. What is already available—and what is not

 ### Reuse

 The lab already has a solved JDK17/Chipyard1.12/sbt/Espresso integration, native probes, thirteen candidate full-state exports, family checkers
 and negative CDG fixtures. Real generated RTL exists for some families. Historical ring evidence includes a real Verilator packet run; use it to
 recover a working execution path, not to establish a fresh release automatically.

 The previous batch also produced:

 - Private three-bit tag transport edits and a production InputBuffer test source.
 - Decoder-binding, replay-provenance and fresh-comparison utilities with unit tests.
 - A generic synthesizable shared-channel scheduler and SV testbench.
 - Private source/build-isolation and emitted-decoder backend work from the earlier verification effort.

 Reuse only after inspecting actual files and current reviews. Several utilities have known false-accept paths.

 ### Still missing or unqualified

 - GEC-hybrid runtime selector is not instantiated in the actual datapath.
 - SROTA's configured dynamic FIU/telemetry behavior is not implemented by its base relation factoring.
 - Complete physical inventory and emitted-decoder correspondence are not established.
 - The latest workflow ran no hardware compilation/simulation: foreign heavy work occupied the execution slot.
 - Accepted-capture RTL replay and fresh final reproduction are not established for all twelve.
 - The shared scheduler is not compiled/simulated or bound into the three Track B profiles.

 Do not restart M1 or multigraph plumbing from scratch merely because final qualification is incomplete. Do not stop at an implementation note
 saying the actual code is too broad: split the missing production edit into smaller connected changes and continue.

 ## 4. Source discoveries that change the implementation plan

 These are reasons to inspect and correct the architecture before spending more compilation time.

 ### 4.1 Proof convenience must not become invented packet behavior

 Current `CatalogExporter.scala` requires each hop's `remaining` to decrease by **exactly one**. `CatalogGecHybridRouting.scala` introduces an
 exact future hop budget B specifically to satisfy that exporter constraint. Native `hybrid_gec` instead chooses mesh/express again at each hop
 using current occupancy; an express jump can reduce Manhattan distance by more than one.

 The generic Python proof already checks **strict decrease**, not exact decrement. The original approved design also requires strict progress, not
 predetermined route length. This corrects the previous handoff’s assumption that the proof-only B budget necessarily needs three-bit physical transport;
 that assumption must be revalidated rather than blindly implemented.

 **Default decision:** WP03 removes the unnecessary exact-decrement restriction, uses a natural well-founded measure and reconstructs the complete
 native-legal hybrid transition system. Do not enforce an invented future-hop budget in hardware merely to appease an exporter.

 This is a proof-model correction, not permission to weaken progress. Keep strict decrease, all outcomes, correct ejection, full resource union and
 native comparisons. Preserve the old budget model as historical evidence. Regenerate and recertify affected exports. If any real active
 packet/control feature independently requires a three-bit field, retain/test it and document that requirement; unused B alone is not one.

 ### 4.2 Credit semantics are now known at the router output

 In the inspected `router/OutputUnit.scala`, counter `s.c`:

 - resets to buffer capacity;
 - increases on downstream credit return;
 - decreases on credit allocation;
 - drives `credit_available` when nonzero.

 Therefore it is **free credit**, not used occupancy. The previous M4 report's contrary inference must not be propagated.

 Native hybrid queries `GetUsedCredit(mesh_port)` and `GetUsedCredit(mecs_port, drop)`. WP11 must extract the exact aggregation rules and map the
 free-credit counters to those occupancy domains. A candidate-specific cost is not necessarily one VC's count: native port/drop aggregation
 determines the sum. Derive arithmetic widths from summed capacity; the existing six-bit selector input may be too narrow for an aggregate.

 Regression: with more FREE credits and otherwise equal conditions, native used-occupancy must decrease. Test full/empty and maximum product
 without overflow.

 ### 4.3 Transporting a tag does not make the decoder use it

 The inspected generic `RouteComputer.scala` deliberately excludes `route_tag` from its truth-table address. `FlowRoutingInfo` does not represent
 per-packet route-tag variants; `asLiteral` inserts zero for the tag. Some specialized decoders encode commitment through incoming VC halves
 instead.

 WP03/WP04 must specify the actual state-to-hardware map per family. Either the metadata is a real decoder/selector input, or a proven equivalent
 state encoding lives in actual VC/packet state. A carried but ignored field does not enforce injection order.

 For FlatFly, choosing first-hop VC half can carry XY/YX, but a user/forced-injection shape input must actually restrict that choice and remain
 consistent thereafter. For SROTA, a union of both shapes at ingress is not the configured FIU decision.

 ## 5. Chosen implementation structure

 ### Option A: keep extending disconnected catalog copies

 Each exporter can carry its own Router/NoC/decoder clone. This can unblock an individual build, but common transport, credit, selector and
 instrumentation fixes then need repeated edits. It risks proving one implementation while another is instantiated.

 ### Option B: narrow production seams over the existing router — chosen

 Keep the real Constellation NoC, channel, InputUnit/IngressUnit, VC allocation, switch and OutputUnit. Reuse existing family arithmetic decoders.
 Introduce only the necessary profile-derived construction seam for:

 1. family legal-mask decoder;
 2. runtime selection of a subset of that mask;
 3. verification instrumentation tied to actual instances.

 The existing `UserRouterParams.vcAllocator` factory is a local pattern for such a construction seam. Match existing types rather than inventing a
 second router framework. Generic defaults preserve legacy behavior. The shared-core owner implements/reviews this seam once; family owners supply
 their actual decoder/selector implementations.

 Do not begin with wholesale deduplication. Existing clones may remain temporarily if a specific family cannot move safely yet; the actual selected
 factory, module class, source hash and connection map must be explicit, and shared correctness fixes must reach every retained active variant.
 Consolidation is accepted only after real production-path checks preserve behavior.

 ### Deep-module ownership and interface reduction

 The sixteen work packages are delivery slices, not sixteen required modules. Deepen existing modules instead of building a wrapper for every phase.
 These are conceptual owners, not mandatory new classes or files:

 | Owning module | Behavior hidden inside | Caller supplies only what cannot be derived |
 |---|---|---|
 | Resolved reference/profile | Native/config validation, topology identities, terminal maps, legal budgets, credit aggregation domains and derived widths | Target identity and frozen reference input |
 | Production packet routing | Legal masks, native runtime selection, packet-local commitment, phase/order/rank interpretation, stall/reset/tail lifecycle | Actual request and live hardware observations/control inputs |
 | Build/execution | Source/resource closure, private build containment, tool selection, ownership lock, approved caps, stage ordering, failure detection and artifact publication | A validated job purpose and immutable inputs |
 | Traffic execution | Synthetic/capture packetization, profile-derived cases, event sampling, scoreboards, credit/reset/drain accounting and trace correlation | Actual stimulus or accepted capture identity and runnable RTL |
 | Independent verification | Required coverage, native comparison, certificate checking, physical/decoder correspondence, replay semantics and release predicate | Immutable candidate/run evidence and independent frozen reference |
 | Release qualification | Per-target dependencies, ready-job sequencing, invalidation, final twelve-row aggregation and reporting | The frozen release snapshot; a target only for an explicitly scoped diagnostic |

 Each owner may have substantial private implementation across existing files. Do not create a god-object/context bag that merely renames a long parameter list.
 Keep mathematical/native verification independent of the production implementation: single ownership does not mean both compute expected and actual results using the same candidate formula.

 For each interface change:

 1. Inventory every real caller and the behavior/failure/ordering contract before editing.
 2. Apply the deletion test: if deleting the module only exposes trivial forwarding, merge it into its owner; if callers would inherit substantial rules, retain and deepen it.
 3. Move special cases, ordering rules, validation and derived values into that owner. Callers must not calculate hop budgets, occupancy costs, VC halves, buffer-dependent test lengths, runner caps or qualification status on its behalf.
 4. Remove parameters/flags that the owner can derive, all callers pass identically, or no implementation reads. Retain genuine runtime inputs and independently meaningful supported behavior.
 5. Migrate every in-scope caller and test to the new interface. Delete superseded overloads, wrappers, compatibility branches, duplicated derivations and unused exports; do not leave a permanent old/new path.
 6. Prove the same caller-visible behavior, failures and ordering through the new interface. Replace redundant shallow implementation-detail tests only after the meaningful public-behavior and scientific negative regressions remain covered.
 7. Verify old entrypoints have no remaining production callers and the actual instantiated hardware/runner uses the new path. Preserve immutable historical source/evidence snapshots; they are records, not deprecated production interfaces to delete.

 Temporary migration steps must stay buildable, have one owner and name the deletion step. Final acceptance requires the old production path removed—not merely marked deprecated. Legacy supported behavior moves to the new shape; it is not an excuse to keep the redundant interface or to delete required behavior.

 ### Internal behavioral obligations—not a public menu callers must orchestrate

 ```text
 legal_mask(query) -> set of physical (output_link_id, output_vc)

 select_head(query, legal_mask, measured_occupancy, control_snapshot)
     -> committed nonempty subset of legal_mask, or explicit wait/invalid

 on_allocation_accept -> freeze actual output/VC reservation for the packet
 on_tail_release/reset -> release packet-local state per declared contract
 ```

 `query` must retain every input that actually affects legality: physical incoming link/port, incoming VC, actual flow/terminal identities and
 packet state. An inject query is a distinct context, not an invented transit VC.

 The interface contract includes:

 - selection never creates a legal output;
 - ejection/local delivery bypasses network selection correctly;
 - a single selector register cannot leak decisions between distinct input VCs;
 - decisions and asserted request bits are stable while stalled;
 - simultaneous RC/VA and SA/ST pipeline combinations remain correct;
 - shape/rank/phase changes occur only at specified events;
 - test controls select allowed branches only and are recorded in the profile.

 These operations belong inside the owning packet-routing implementation; callers must not manually sequence them or reproduce its state machine.
 Agents must compile the real construction and production test, not merely write these function names in a helper file.

 ## 6. Work breakdown and ownership

 Each package's detailed instructions are in [WORK-PACKAGES.md](rtl-12of12-plan/WORK-PACKAGES.md).

 | Package | Owner role | Main output | Dependencies |
 |---|---|---|---|
 | WP00 | Integrator | Coherent baseline, required twelve IDs, ownership and change ledger | Existing artifacts |
 | WP01 | Execution/build | One private, capped runner that really loads/builds/executes | WP00 |
 | WP02 | Native-contract | Correct effective profiles and recorded controlled alternatives | WP00; heavy runs via WP01 |
 | WP03 | Shared core + proof | Correct state/progress model; no ghost hardware budget | WP00/WP02 |
 | WP04 | Shared core | Real tag/state/selection transport and production tests | WP03 |
 | WP05 | Proof | Independently verified reachable-resource certificate | WP02/WP03; family rules incrementally |
 | WP06 | RTL correspondence | Actual decoder queries and complete physical resource mapping | WP01/WP03; per-family emission |
 | WP07 | Packet execution | Reusable actual-RTL harness and observability | WP01; WP04 as needed |
 | WP08 | Baseline families | Mesh, CMesh, QTree and Fly production closure | WP03–WP07 per target |
 | WP09 | Cyclic families | Ring and Torus dateline production closure | WP03–WP07 per target |
 | WP10 | Multipath/order families | Fat-tree, Tree4 and FlatFly production closure | WP03–WP07 per target |
 | WP11 | GEC families | Pure MECS and live hybrid selector closure | WP02–WP07 |
 | WP12 | SROTA | Configured FIU/telemetry/rank implementation and capped emission | WP02–WP07 |
 | WP13 | Replay | Actual accepted-capture injection, byte/lineage/causal checks | WP01/WP07; each runnable family |
 | WP14 | Release/audit | Same-snapshot full twelve-family qualification and reproduction | All Track A packages |
 | WP15 | Shared-resource | Three separately qualified Track B profiles | Common core; independent Track B proofs |

 ### One writer rule

 - Shared transport/router/interface edits: one shared-core writer, merged by the integrator.
 - Family work: separate private candidate trees from a named baseline, with bounded patches and explicit dependencies. Concurrent writers never
 share a mutable source/build directory.
 - Execution: one global heavy owner. All family agents submit concrete ready jobs; they do not compile privately in parallel to bypass this limit.
 - Reviewers: fresh context, read-only, inspect actual production code and evidence.
 - Optional parallel preparation: at most six agents active while the six-agent limit remains in force. More useful independent ownership is
 valuable; more duplicate plans are not.

 Changing the common source invalidates dependent releases. Use conservative snapshot invalidation rather than inventing complicated
 dependency-cache logic. Final twelve-family qualification runs from one final integrated freeze.

 ## 7. Critical path: first meaningful win, then repeat

 ```text
 WP00 ──► WP01 actual private load/build/runner ──► frozen ring runtime recovery
   │                     │                                      │
   ├──► WP02 native      ├──► WP07 real harness ────────────────┤
   └──► WP03/WP04 core   └──► WP06 physical/decoder binding ────┤
               └────────────► WP05 real certificate ────────────┤
                                                              ▼
                                                 first genuinely qualified row
                                                              │
                ┌──────── WP08/WP09/WP10/WP11/WP12 ────────────┤
                │              per-target ready jobs            │
                └──────── WP13 actual replay per row ──────────┤
                                                              ▼
                                                 WP14 fresh same-snapshot 12/12

 WP15 Track B: parallel implementation, same serial heavy queue, separate result.
 ```

 ### Phase A — recover execution immediately

 Start WP00/WP01/WP07 and the narrow WP05 proof-content correction. Once the frozen ring bytes and harness pass a concrete preflight, execute a
 diagnostic ring cell under original caps. This can be useful even before unrelated new source implementations are ready; label it diagnostic and
 historical-source-lineage unknown if appropriate.

 Do not make every preparatory agent finish before starting this cell. Do not demand a prior simulation PASS as a prerequisite to performing its
 first controlled simulation. Do not call that first diagnostic run a final row until all acceptance columns pass on reproduced source.

 ### Phase B — complete the common state seam and first end-to-end row

 Merge WP03/WP04. Pick ring or mesh based on actual runnable source/build readiness, not convenience of a prewritten JSON receipt. Bring it through
 native policy, source emission, actual inventory/decoder correspondence, packet/credit tests and real capture replay. Obtain a fresh independent
 audit. This proves the reusable path instead of twelve disconnected partial paths.

 Meanwhile GEC/SROTA owners implement missing production behavior in private trees. They must not spend the whole phase adding Python models around
 the missing datapath.

 ### Phase C — fill every family row

 Run the baseline, cyclic, multipath/order, GEC and SROTA lanes. Reuse the same harness/contract format. At each execution barrier, choose the next
 ready target. Implementers keep working while the serial queue runs.

 Full required link witnesses and forced legal branch coverage often need extra tests beyond all-pairs delivery. Plan them explicitly rather than
 discovering at final audit that an allocator never selected half the resources.

 ### Phase D — freeze, reproduce and audit

 Merge all required production changes, freeze a release snapshot, re-run all twelve. Emit into a second fresh output root and compare
 deterministic artifacts. Handle truly nondeterministic metadata separately without removing functional differences. Run the release verifier,
 inspect failures and re-enter the owning package. Stop only on twelve genuine PASS rows, not when the last assigned agent returns.

 ## 8. Scheduling and build-memory rules

 - Heavy work is serial across this effort and cooperating external owners: generation, Scala/JVM builds, Verilator/C++ builds and full simulation.
 - Preserve systemd `MemoryMax=4G`, `MemorySwapMax=512M`, JVM `-Xmx3g`, one active processor/sbt task, native/Verilator `-j1`, finite1800s
 generation cap. Do not recreate historical 7G or reduced-VC diagnostics as final evidence.
 - The execution owner uses one shared lock for cooperating jobs **plus** a fresh process/ownership check for foreign jobs. A lock that foreign jobs ignore does not prove safety. Old PIDs are historical, not current authority.
 - Wait on native completion events; never poll/sleep to burn quota. If foreign ownership blocks work, return the exact owner/process/root and
 ready command. Do not kill it.
 - All sbt/meta-build/project targets, generated resources, test directories and writable caches are private before sbt loads. Setting `target`
 after load does not establish this.
 - Reuse solved tool binaries and immutable dependencies. Fix private containment/duplicate source selection; do not restart dependency/toolchain
 discovery.
 - An OOM/exception/timeout/missing artifact fails even if sbt prints success or exits zero.

 ### When full-size elaboration exceeds the cap

 First identify the failing stage with actual logs. Apply this ladder:

 1. Remove redundant query dimensions **only after proving the relation independent of them**.
 2. Use existing family arithmetic/factored decoder implementations with exhaustive emitted-mask equivalence checks.
 3. Factor repeated production monitors/assertions without removing assertions, flow correlations or resource cases.
 4. If necessary, partition lowering at real router modules, retaining one coherent elaborated hierarchy and all real connections, clocks, buffers
 and assertions. Hash every partition and verify reassembly.

 A collection of individually generated router files is not a connected fabric. Do not replace buffer implementations, disable monitors, reduce
 widths/VCs/topology, collapse links or shrink the test domain to fit.

 ## 9. Agent acceptance and review discipline

 Every package returns actual changed files, actual command/exit/log evidence, immutable run references, unresolved conditions and a patch/baseline
 identity. Task status and scientific status are separate.

 Use the acceptance specification for reviews. In particular:

 - Production integration tests instantiate production modules and test the caller-visible behavior. A local Queue with a locally invented bundle
 cannot prove the production transport.
 - A proof file must be parsed and independently verified, not merely hashed.
 - A replay must be executed against approved capture bytes; fabricated success JSON is only a negative test.
 - A reproducibility check must compare outputs from an actual fresh invocation, not a copied directory with a plausible run ID.
 - The verifier's expected IDs/inventory come from an independent frozen contract, not from the candidate being verified.
 - Unsupported or incomplete states remain visible as not_run/blocked/failed; they are not silently skipped.

 Review implementation before expensive execution for concrete defects, but not for the circular absence of that very execution. Review actual raw evidence afterward. A bounded review-round cap means stop with findings and re-plan that package; it never converts findings into approval.

 ## 10. Tracking real progress

 Use one twelve-row matrix with these independent columns:

 ```text
 native_contract | production_policy | source_reproduced | emitted_inventory
 reachable_proof | decoder_correspondence | packets_and_credits
 accepted_replay | fresh_reproduction | independent_review | overall
 ```

 Each cell records a status and an evidence path/run ID, not just a checkmark. Track B is another table. Optional13 is another row group.

 At session end, report:

 1. number of original twelve rows whose complete conjunction is PASS;
 2. exact newly executed hardware tests and failures;
 3. production changes merged since the prior freeze;
 4. critical-path blockers and the next ready job.

 Do not report child count, new checker count or total unit-test count as percentage of the RTL goal.

 ## 11. Checkpoints and sensible stopping conditions

 - **Checkpoint 1:** an actual private build and Verilator run with raw evidence, not another prepared runner.
 - **Checkpoint 2:** one reproduced full-size family passing every Track A column, including replay and physical/decoder/proof correspondence.
 - **Checkpoint 3:** the same path works for a structurally different family and a stateful family; no ring-only hardcoding.
 - **Checkpoint 4:** all twelve have passed on the final integrated source.
 - **Checkpoint 5:** fresh reproduction and an independent final audit accept all twelve; release command exits zero.

 An individual owner stops on a specific unresolved architecture decision, reproducible infrastructure failure or explicit bounded assignment
 completion. The orchestrator then resolves/reassigns it. Missing implementation is not an external blocker. Do not stop the overall program
 because a task batch ended.

 The plan does not promise a wall-clock date. Measure the first real build/test durations, then estimate the serial queue plus unresolved engineering work. Keep the user informed without inventing a completion percentage.
