# Work packages: production RTL through twelve-family qualification

Read the [master plan](../RTL-12-OF-12-EXECUTION-PLAN.md) and the acceptance section relevant to your package. These are implementation assignments, not permission to replace missing production behavior with another model.

## Common workspace and handoff

Proposed new integration root:

```bash
LAB=/home/datavex/.cache/veritx-noc-lab/vla-native-execution/experiments/constellation_topology_rtl
WORK=$LAB/rtl-12of12-release-v1  # choose a new unique suffix if already owned
```

Preserve the existing workspace layout when copying reusable tools: `$WORK/src` is the private Constellation source root, with code at `$WORK/src/src/main/scala`; `$WORK/tools` contains adapted existing tools. This keeps relative-path assumptions visible. Reference/baseline snapshots live separately from mutable current-candidate files. Do not accidentally compare a new source tree to a historical M2 baseline and either reject all legitimate edits or overwrite the baseline to make it pass.

Each owner receives one private source/work scope. It returns:

- baseline/source manifest and bounded patch or changed-file list;
- production module/test entrypoints;
- actual commands, exit status and raw log paths;
- selected profile and immutable artifact hashes;
- exact still-open work and next runnable command;
- scientific status: component_checked / generated / simulated / row_qualified, separately.

Prototype commands and filenames below are **proposed interfaces** unless identified as existing. Implement the smallest adapter to existing tools; do not claim they already work.

## WP00 — Establish one coherent intake and integration baseline

**Owner:** integrator. **Dependencies:** none. **Scope:** new `$WORK`, ownership table and snapshot manifests; external sources/outputs read-only.

### Actions

1. Read the previous handoff and [external update](EXTERNAL-ARTIFACT-INTAKE.md). Consume the terminal prior workflow rather than relaunching its completed tasks.
2. Record original twelve required IDs, optional13 separately and three separate Track B profiles. Record active external source/build owners and the heavy queue owner.
3. Freeze the actual current source/config/reference inputs coherently. Hash before/after copy and reject changes during capture. Capture dirty-source diff, untracked required source files, compiler/library versions, source/config hashes and origin paths. A Git HEAD alone is insufficient for this dirty workspace.
4. Intake existing external Verilog/partitioned artifacts: named top, every helper/blackbox/module, inventories, command/log/receipts, effective profile and known source lineage. Missing lineage stays unknown; do not derive it from current mutable source hashes.
5. Import the useful previous edits as private candidates, not accepted production: tag widening, InputBuffer regression, decoder helper, replay/fresh validators and generic shared scheduler.
6. Create the eleven-column twelve-row matrix from the master plan; keep all rows visible from the beginning.

### Acceptance

A second process can validate snapshot files and hashes, identify the exact required family/profile, locate every intake artifact and distinguish unknown historical source lineage from reproduced source. No original file was overwritten. Every subsequent package has a unique owner/write scope.

### Not done if

Only a status spreadsheet exists; required untracked sources were omitted; source changed while being copied; repeated filenames/variants were counted as additional family implementations.

## WP01 — Make one private execution path actually work

**Owner:** build/execution. **Dependencies:** WP00. **Scope:** runner and fresh private build/run directories. One heavy owner.

### Existing inputs

- `full-connectivity-v1/tools/run_chipyard.sh`, `run_mesh_rtl_elaborate.sh`, `export_candidate.sh`.
- `verification-isolated-v1/build-isolation/prepare_build.py` and tests.
- Existing solved JDK17, sbt launcher, Chipyard1.12 and Espresso.

### Actions

1. Audit the isolation helper before reuse: generated project definitions, selected source/resource directories, default source directories, duplicate symbols, dependency projects, symlinks and build/meta-build target paths.
2. Privatize build definitions/targets **before sbt loads**, including `project/target`, `project/project/target`, test directories and writable caches. Preserve needed integrated Chipyard dependencies. Do not use `++=` to accidentally compile both original and private candidate sources.
3. Add a small execution wrapper around existing commands. It owns the shared lock, process-tree preflight, finite cgroup/timeout, argv/env/cwd capture, tool hashes, raw stdout/stderr, exit/signal and atomic terminal receipt.
4. Distinguish `started`, `failed`, `blocked` and `complete`. A completed build phase is not a completed simulation. Scan complete logs for JVM/OOM/exception failures even when exit=0; also require all expected products.
5. Run a real private sbt load/selected-source check and the narrow existing production Chisel regression, then a small real emitted-RTL smoke through the correct pinned Verilator interface. This package is not complete at `prepared_not_loaded`.
6. Preserve a working immutable command/run before abstracting it. Add failure tests for bad argv, stale binary, missing helper, source drift, incomplete output, interrupted/failed compiler and exit0 with explicit OOM.

### Acceptance

Actual private load/compile or RTL execution produces raw logs and verified outputs; before/after containment checks show no shared build/source writes. An intentional missing helper/bad executable cannot yield complete. First invocation records the actual executed command, not a future recipe.

### Scheduling

If an external owner is active, finish useful lightweight runner work and publish the exact ready job. The orchestrator coordinates the slot. Do not inspect only an old PID or launch during gaps between queued JVMs. Do not block a safe ready ring run on every other implementation lane.

## WP02 — Freeze the native truth and record real choices

**Owner:** native-contract. **Dependencies:** WP00; actual native build/probe via WP01. **Scope:** private native probe source/configs and reference evidence.

### Existing inputs

`contracts/reference_contracts.json`, `tools/check_contracts.py`, `run_native_probe_matrix.py`, native `networks/network.cpp`, route functions, router/buffer-state implementations and existing probe fixtures.

### Actions

1. Revalidate effective values and required identity mapping for the master table. Preserve native constructed/routed distinctions and native/dense/terminal/drop mappings.
2. For dynamic/randomized choices, record actual controlled invocations: query context, forced selector/order, input link/VC/phase/control state, output port/drop/VC set, source/config/binary/run identity. Keep native diagnostic controls isolated from historical source.
3. Extend the native oracle beyond injection/first-hop samples to reachable transit cases. Use exhaustive small occupancy domains and exact boundary cases for cost functions; do not enumerate irrelevant huge counters if the comparison can be checked exhaustively over derived bounds.
4. Extract native `GetUsedCredit(port)` and `(port, drop)` aggregation, SROTA FIU/telemetry/epoch/plane behavior, native ties/random alternatives and VC subsets. Distinguish actual state from proof annotations.
5. Pin approved single-sensor and sequential two-sensor capture manifests. Latest timestamp alone does not mean accepted; one previously observed newest sequential capture had `reported_gate_pass=false`.
6. Retain existing historical reference hashes and intentional Track A differences. Never modify old native results to agree with a new implementation.

### Acceptance

Every expected native choice can be traced to an actual invocation and exact source/config. Removed branch, bad VC/drop, swapped configuration, rejected capture and missing probe receipt fail. Controlled outcomes are not inferred solely from a deduplicated outcome union.

## WP03 — Correct state semantics and progress before encoding hardware

**Owner:** shared-core/proof co-design, one writer for shared state/export types. **Dependencies:** WP02.

### Exact inspected seams

`CatalogRouting.scala`, `CatalogExporter.scala`, `CatalogGecHybridRouting.scala`, `routing/Types.scala`, generic/factored RouteComputers; `tools/proof_core.py`.

### Actions

1. Write a per-family state map: native/query state → actual packet/VC/control registers → exported transition state. Record what can be inferred from geometry, incoming link/VC and what must be stored.
2. Replace `CatalogExporter`'s exact-one decrement condition with a checked natural-number strict-decrease interface. Require nonnegative measure, zero only at valid arrival, nonterminal successor progress and nonempty outcomes. Verify successor measure from successor state, not an untrusted transition field.
3. Rebuild hybrid legal states without a future-hop B commitment that native routing does not have. Manhattan distance is a valid strict progress measure for monotone mesh and direct express hops; some steps decrease it by more than one. Include every native legal mesh/express decision at the same current physical state.
4. Update independent family/native comparison and negative tests. Changing the proof representation is a new source/export identity; regenerate only affected evidence and preserve historical exports.
5. Resolve actual route metadata width. Keep three-bit transport if a real enabled feature needs it; otherwise do not make an obsolete proof-only B field a hardware requirement. Do not claim a two-bit field carries values4–6.
6. Make injection commitment explicit for FlatFly/SROTA. If incoming VC encodes order/rank, prove the mapping and include injection restrictions. A union mask must not choose a different shape from the latched/control-selected one.
7. Add explicit next-packet-state behavior where state genuinely changes per hop. The code cannot simultaneously require all beats carry an unchanged tag and silently use that tag as a decremented per-hop counter.

### Required regressions

Hybrid path with express distance3 must decrease measure by3 and remain legal; equal/increasing/negative progress must fail. Native decisions cannot disappear because of an invented budget. Unsupported metadata bits must fail or be explicitly reserved. Distinct source/order states must not silently alias if they produce different legal masks.

### Acceptance

Compiled actual Scala exporter and independent checker agree on the revised complete reachable system; native-legal outcomes remain complete; all unsafe mutation fixtures still fail. No fixed exact path length is mistaken for general termination.

## WP04 — Production transport and runtime-selection seam

**Owner:** shared-core. **Dependencies:** WP03. **Scope:** actual shared channel/flow/IngressUnit/InputUnit/Router interfaces and tests. Family owners consume this stable seam.

### Actions

1. Apply necessary tag/state changes coherently across `channel/Flit.scala`, `routing/Types.scala`, `IngressUnit`, `InputUnit`, width adaptation, egress, route requests and any generated/retained active router variants. Retain legacy defaults/source compatibility.
2. Add the narrow real router construction/configuration seam described in the master plan. Existing active family arithmetic computers must be the modules actually constructed, not shadow classes unused by a generic `NoC`.
3. Integrate the legal-mask-to-runtime-selection path in both ingress and transit. Respect `combineRCVA` and `combineSAST` modes actually used by profiles. Separate legal mask from committed selection so proof instrumentation can see both.
4. Store per-head/per-input-VC committed decisions before asserting a request that can stall. Preserve requested physical link/VC subset until allocation accepts. After allocation, body/tail follow that reservation; the next packet must not inherit old state.
5. Keep local ejection correct and metadata/payload distinct. Changes to route choice must not overwrite application payload.
6. Add production tests: real IngressUnit→buffering/width path→real transit InputUnit→egress where needed, not just a locally defined three-bit Queue.
7. Reuse `ParallelLinkNoCSpec`, `LinkIdentitySpec`, `WidthWidgetSpec` and corrected `RouteTagTransportSpec`. Extend to actual selector and stage combinations.

### Acceptance

Actual Chisel tests pass for required metadata, multibeat packets, backpressure, reset, local ejection, two independently credited parallel links and legacy profile. Mutation truncating a required tag bit or switching a stalled decision fails on the production path. Updated docs/manifest widths match actual compiled ports.

## WP05 — Verify a real reachable physical-resource proof

**Owner:** proof. **Dependencies:** WP02/WP03 and per-family actual legal rules. **Scope:** existing checker/certificate, family adapters and meaningful negatives.

### Actions

1. Repair the known `m3/decoder_binding.py` acceptance of `b"proof"`. Parse a recognized certificate schema and independently recompute/recheck its relation to exact source/export/profile/inventory digests. A status string is not certification.
2. Explore all terminal-pair starts, injection commitments and reachable transit incoming-link/VC/state contexts. Preserve native flow identities when they affect legality. Different incoming VCs are not freely interchangeable successor states.
3. Construct A→B dependencies only for realizable hold-A/request-B steps; union these dependencies across all flows/choices on the **same physical resource identities**. A cycle can involve different packets—never require one packet to traverse the whole cycle.
4. Include injection/egress buffers, allocatable VC ownership and other real holdable resources where they can participate. For Track B add shared locks/queues via WP15 rather than reusing a P2P graph silently.
5. Independently validate each resource rank edge, absence of dead ends, correct ejection and strict progress. Distinguish logical reachability from an arbitrary Cartesian product or a silently underexplored subset.
6. Compare complete expected link/router/terminal/query sets against the independent native contract. Include branch witnesses, not only total counts.
7. Reuse existing wrong-dateline, shared XY/YX VC, SROTA-rank, down→up NCA, hybrid regression, parallel collapse, missing-link and wrong-butterfly negatives. Add malformed/unrelated certificate, truncated query domain and altered transition-with-old-certificate negatives.

### Acceptance

A verifier rejects arbitrary proof bytes, wrong source/export, omitted physical resources and unsafe cycles. A positive certificate is independently reproducible from actual transitions and inventory. Every correction to previous alias/reachability false cycles retains the old witness with an explicit explanation; no edge is removed merely to obtain acyclicity.

## WP06 — Bind proof to emitted decoder and actual wiring

**Owner:** correspondence. **Dependencies:** WP01/WP03; target-specific generated RTL and WP05 certificate. **Scope:** existing decoder backend/binder, machine-readable compiler capture and inventory verifier.

### Existing inputs

`verification-isolated-v1/{decoder-execution,rtl-binding,rtl-binding-ast}/`, `tools/check_rtl_inventory.py`, `compare_rtl_masks_m5.py`, actual emitted RouteComputer modules. Existing alias tracing is partial; preserve reusable work rather than writing another regex-only inventory.

### Actions

1. Execute actual emitted decoder instances through the existing pinned Verilator backend or equivalent existing compiled test path. Match the real query bit encoding, incoming instance, VC, source/destination seats and state inputs.
2. Enumerate reachable native/certified queries and observe output/VC masks. Check forbidden outputs as well as expected ones. Extract expected legal masks independently of the candidate decoder implementation.
3. Trace selected outputs through Router/NoC hierarchy to physical linkId, destination input, VC queues and terminal map. Use typed/compiler/net connectivity evidence rather than counts of module names. Include clocks/resets and helper/blackbox definitions.
4. Validate reference required-resource set against complete post-pruning hierarchy, not the emitter's pre-pruning graph metadata. Reject unresolved aliases, default maps, collapsed parallels or missing terminal direction mappings.
5. For per-router compilation, verify every required partition exists from the same elaborated snapshot and that the top reconnects all exact flit/credit/reset signals. No duplicate blackboxes, unconnected stubs or stale router files.
6. Bind exact native, proof, source, tool, emitted top/helper/inventory and observation file digests in the verifier input. Expected coverage comes from the independent contract.

### Acceptance

Actual decoder-bit mutation with unchanged exported transition data fails; physical parallel-link swap, terminal seat swap, missing helper/partition, VC remap and stale RTL fail. Real complete binding—not `partial_unresolved`—is required for row PASS. Unit fixtures remain useful but cannot stand in for these emitted-net checks.

## WP07 — One real RTL packet harness for the catalog

**Owner:** packet execution. **Dependencies:** WP01, profile inventory and production interfaces; WP04 for changed sources.

### Existing inputs

`tools/verilator/{run_ring_verilator.py,gen_verilator_harness.py,gen_capture_replay_harness.py}`, historical real ring path, frozen reviewed packet fixes, and `verification-isolated-v1/packets/packet_tools.py`.

### Actions

1. Recover one actual ring lint/build/run with the correct pinned executable/argv/helper. Keep old and new harness behavior distinct; select one maintainable path after the real cell works.
2. Replace ring-only dimensions/allowlists with an explicit qualified inventory adapter: terminal direction/seat, widths, tags, VC/buffer budgets, maximum route progress and instrumentation IDs. Do not infer topology from output-directory basename.
3. Implement the full [packet matrix](ACCEPTANCE.md#7-packet-and-credit-campaign). Drive/snapshot ready/valid at the same defined edge; compare accepted flits exactly once. Prevent post-edge sampling from missing/duplicating a handshake.
4. Check all128payload bits, head/body/tail framing, all destinations, sequence/packet identity, stalled valid/bits, independent blocked sinks, finite reset epochs, exact conservation and justified drain bounds.
5. Observe actual per-link/VC forward, credit-return, allocation and release events. Egress-only traces do not establish internal resource coverage or credit correctness.
6. Compile with assertions active. Classify warnings; do not blanket-suppress errors or alter assertions to make the campaign pass.
7. Make a common actual packet schedule input usable by both synthetic tests and WP13 capture replay; preserve traffic bytes and timing semantics.

### Acceptance

A compiled RTL cell passes the configured matrix and mutations catch high-half payload corruption, duplicate/drop/wrong egress, stall changes, credit under/overflow, stale state and bad reset accounting. Receipts identify the exact binary/top/helper/profile used. Generalization is demonstrated on a second structurally different family, not only mocked inventories.

## WP08 — Close Mesh, CMesh, QTree and Fly64

**Owner:** baseline-family implementer(s), isolated family scopes. **Dependencies:** common foundation, target-native contract, proof/decoder/harness available incrementally.

### Per-family work

- **Mesh:** preserve64routers/224nonwraplinks/4VC/depth15. Reuse factored arithmetic DOR. Prove removed source-query dimensions do not affect legality. Check edges/corners, XY turn and both signs. A diagnostic2VC mesh cannot qualify this row.
- **CMesh:**16routers/64terminalseats/48links/16VC/depth8. Test same-router different-seat delivery, all injection/ejection seats under simultaneous traffic and fair contention. `terminal_id != router_id` must hold throughout harness and decoder mapping. Inspect accepted unrouted native-wrap differences.
- **QTree:**21physicalrouters/40links/64leafterminals. Preserve actual sparse native/dense mapping and correct NCA subtree. Test same-leaf/local seats, same-subtree, cross-root traversal, all leaves and all required link witnesses. Do not use the unrelated structured one-terminal-per-router prototype as acceptance.
- **Fly64:**48routers/128directedinterstagelinks/64terminals, distinct injection/ejection attachments. Test native destination-digit/permutation mapping, every stage/link and all4096pairs. No returning to an earlier stage; no FlatFly substitution.

### Acceptance per row

All columns in ACCEPTANCE.md pass from reproduced source at configured size. Tests use actual family production modules. A candidate graph checker alone cannot close this package.

## WP09 — Close Ring and Torus dateline behavior

**Owner:** cyclic-family implementer. **Dependencies:** WP02–WP07.

### Actions

1. Reuse current ring/torus arithmetic/native work and retained unsafe fixtures.
2. Validate minimal direction, native half-distance tie alternatives and packet-stable direction. Ring distance32 and torus per-dimension distance4 need explicit tests.
3. Correct injection onto a seam and reachable transit incoming-VC mapping. Dateline state advances at the declared crossing; cannot revert within that dimension.
4. At torus X→Y transition, initialize Y's local dateline state correctly. Lower numeric VC at a dimension transition is not automatically invalid: rank includes dimension. Do not impose the wrong global-monotonic-VC rule.
5. Build the complete merged CDG over real link/VCs and actual decoder outputs; preserve predecessor-VC/flow compatibility. Force both signs, seams, zero-length dimensions and local ejection.
6. Run long packets, cyclic hotspots and delayed sinks, then release all sinks and drain. Packet success is additional evidence, not the deadlock theorem.

### Acceptance

Ring64/128links and torus8×8/256links keep exactly2VC/link. Exhaustive native/decoder/reachable-resource checks pass; wrong seam reset/input VC mutation fails. No extra VC or route-pruning workaround.

## WP10 — Close Fat-tree, Tree4 and FlatFly

**Owner:** multipath/order-family implementer. **Dependencies:** common foundation, controlled branch harness.

### Actions

- **Fat-tree:**48routers/256links/depth16. Retain all native NCA ancestors; force each allowed uplink/root path. Physical internal routers cannot be omitted because they host no terminals. Confirm downward destination coverage and no down→up turn in reachable contexts.
- **Tree4:**28routers/128links, sparse native0..3/16..23/32..47. Verify dense/native round trips and every source/destination port mapping. Force all legal parent/root alternatives, not one selected spanning tree. Check declaration ranges do not instantiate fake routers.
- **FlatFly:**16routers/96links/8VC/depth4. Enforce selected XY/YX at injection, then retain it through the actual incoming-VC half or other proven packet-state map. Force both orders, same-row/column cases and cross-dimension cases. XY uses0..3, YX4..7; shared-resource union must not create a hidden mixed-order cycle.

### Acceptance

Full configured production packet/branch/link tests and native/decoder/CDG/progress correspondence pass. An injection mask allowing both halves without enforcing the requested injection commitment is not sufficient. Tree4 and FlatFly names cannot be substituted with superficially similar research prototypes.

## WP11 — Pure GEC-MECS and live GEC-hybrid selector

**Owner:** GEC production integration. **Dependencies:** WP02/WP03/WP04. **Scope:** actual instantiated legal decoder/selector, mapping and tests, not an isolated cost model.

### Actions

1. Freeze native group/drop/port ordering and VC-range behavior. Pure MECS is16routers/96independentTrackAtaplinks/6VC/depth32. Test all tap identities, same-row/column and two-leg cases.
2. Hybrid is16routers/144links/8VC/depth32:48mesh plus96express. Preserve linkId in every input/output/channel lookup; `(src,dst)` is not identity.
3. Implement the live selector at the real ingress/transit allocation seam. Inputs are actual legal candidates and native-equivalent used occupancy derived from free-credit state, not static topology costs.
4. Native behavior: X before Y, mesh one step toward target vs express directly to target coordinate; meshH=remaining dimension distance, expressH=1, `mesh_cost < express_cost` selects mesh, ties express. Reevaluate at each router, never mid-stalled request or mid-packet reservation.
5. Extract and implement exact occupancy aggregation: native mesh-port occupancy vs native express-port/drop occupancy. Derive bit widths from capacity and maximum distance; test maximum aggregate and product. Do not simply feed existing six-bit scalar counters if native occupancy covers multiple VCs.
6. Wire filtered committed mask into actual VC allocation and retain all legal VCs within selected native candidate. Handle local ejection and no-legal/invalid states explicitly; assert selection subset of legal mask.
7. Implement production tests that manipulate real queue/credit state to force mesh, express and tie, including adjacent peers with two distinct physical resources. Interleave different input VCs and consecutive packets; stall the selected head while occupancy changes elsewhere.
8. Prove all runtime outcomes are in the corrected native-legal relation. The old future-B budget model cannot forbid a native occupancy-driven choice.

### Acceptance

Actual constructed Chisel datapath/compiled RTL demonstrably changes selected physical resource under controlled live occupancy and never changes a committed stalled choice. Separate parallel credits survive emitted wiring checks; every144link has a witness. Cost/model unit tests without instantiation leave this package unfinished.

## WP12 — SROTA configured behavior and capped full-size emission

**Owner:** SROTA production. **Dependencies:** WP02–WP07; private collaboration with existing factoring owner.

### Inputs

Actual `CatalogSrota8x8Routing`, `CatalogRtlSrotaExport`, prior private factoring, native `networks/srota.cpp`, `routers/srota_router_d.cpp`, allocator/control logic, accepted `srota64_rowcol.cfg` and effective contract.

### Actions

1. Freeze the actual enabled plane/path/router settings. Current effective contract records planes5, row/column path mask3, rank VC policy, threshold8, epoch1024, telemetry period4/latency8. Interpret these through the native implementation; inherited defaults for irrelevant other families do not activate features.
2. Implement the native injection FIU choice and control/telemetry state actually enabled by this profile. Define reset, epoch transition, stale/missing telemetry, measured-credit and ties from source; do not invent fallback thresholds or static forced shape as production behavior.
3. Commit selected shape for the packet. Preserve distinction between XY/YX shape and first/second-leg rank. First leg uses rank partition0..1, second/turn2..3 as accepted; aligned endpoints need the correct normalized initial rank.
4. Bind choice to actual ingress decoder/allocator and carry enough state for transit. A base mask containing both orders is safe-set evidence, not FIU implementation.
5. Preserve64routers/64terminals/896independentTrackAlinks/4VC/depth8/128payload. Verify grouping metadata for224directional segments without giving TrackA shared-driver bandwidth claims.
6. Reuse arithmetic decode/monitor factoring to lower memory. Prove all reachable query/state masks against native/certified relations. If using per-router lowering, verify complete connected assembly and same-snapshot partitions.
7. Test actual FIU telemetry/epoch cases, force both legal shapes through a recorded test control, verify state stable under stalls and side effects do not corrupt data/credits. Run rank-cycle mutation, long packets, hotspots and all required links.

### Acceptance

Actual configured FIU/control→selection→flit/VC→delivery behavior passes production tests and proof/decoder correspondence. Full-size source-bound generation completes under approved caps. Base-relation-only emission, disabling enabled telemetry or an unverified live long JVM are not completion.

If a reference contract is genuinely underspecified/inconsistent, preserve a concrete counterexample and the minimum decision needed. The orchestrator resolves it with the operator; it cannot declare SROTA passed by silently choosing a smaller static profile.

## WP13 — Execute the accepted captures through RTL

**Owner:** replay. **Dependencies:** WP02 capture acceptance, WP01 runner, WP07 executable packet schedule interface, each runnable family.

### Actions

1. Implement the missing actual invocation between `replay_holoscan_rtl.py` and the compiled RTL harness. Existing prewritten `holoscan_result.jsonl` is not proof a simulator ran.
2. Use pinned approved capture manifests, exact raw input bytes and one documented packetization/terminal/byte-order contract shared across families. Preserve raw payload; packet IDs/observability must not overwrite application bytes.
3. Keep single/sequential capture runs separate or use collision-safe composite identities. Current topology-level shared JSONL with restarted packet IDs can alias two captures.
4. Have the execution runner produce raw invocation/build/binary/top/helper/source/inputs/outputs/exit evidence. The verifier independently validates it; merely adding more successful JSON fields is insufficient.
5. Parse outputs against a defined schema; independently compare every delivered packet/flit byte and sequence with the packetized expected stream. Validate endpoints, causal predecessor relationships and logical capture sequencing. Only assert time-order constraints actually present in the accepted trace.
6. Validate real internal hop/VC/link traces against the certified relation and physical binding. Missing required refinement is a failed gate, not an optional flag producing an apparent row PASS.
7. Negative tests: unapproved capture, swapped two capture contents, wrong executable/helper, stale binary, forged-success receipt, hash-equal-but-semantic-invalid schema, wrong byte, reordered causal packet and missing internal trace.

### Acceptance

Both approved captures genuinely execute through each family's RTL, with exact bytes/packet lineage, causal checks, drain, internal refinement and coherent runner evidence. Sparse sequential captures do not establish congestion benefits; synthetic stress remains mandatory.

## WP14 — Same-snapshot full release and fresh reproduction

**Owner:** integrator plus fresh independent verifier. **Dependencies:** all Track A packages, not necessarily completed Track B.

### Actions

1. Merge required reviewed production changes and freeze one complete release source/config/reference/tool snapshot. Run shared production regressions first.
2. Adapt existing `run_rtl_matrix.py`, `check_rtl_inventory.py`, `check_routes.py`, `replay_holoscan_rtl.py`, `audit_m8.py` to consume actual runner evidence and explicit workspace/profile inputs. Remove false acceptance of authored records, not scientific checks.
3. Use a thin proposed `tools/qualify_rtl.py` only if needed to sequence those existing gates. Per-target diagnostic mode may run subsets; final `--all` must require exactly the twelve required IDs and every mandatory column.
4. Generate/build/prove/refine/simulate/replay all twelve from the final snapshot, with immutable per-phase runs. Reuse unchanged products only when their exact dependency identity is established; for final conservative release, a full fresh pass is preferred.
5. Repeat emission in a separate fresh root and compare transitions, full inventory, named top and every helper. No copying original outputs into the fresh root. Investigate deterministic normalization of metadata only; never normalize functional differences away.
6. Independently verify proof contents, actual physical maps, raw runner commands/exit, hashes, coverage, bytes, reset accounting and snapshot identity. Fix and rerun affected dependents on a new freeze when source changes.
7. Publish a bounded archive/manifest with source diff, required untracked files, tools, logs, receipts, native evidence, certificates, inventories, traffic/capture identities and exact reproduce command. Report TrackB/optional13 separately.

### Acceptance

Fresh final command exits0 with twelve complete rows and independently verified evidence. Missing/failed/blocked/not_run rows make it nonzero; optional13 and TrackB cannot alter the denominator. A user can reproduce the release without relying on private session prose or a mutable external `/tmp` directory.

## WP15 — Complete shared-resource Track B separately

**Owner:** shared-channel implementer, proof owner and serial execution owner. **Dependencies:** shared transport/contract foundation; no need to wait for every Track A row.

### Actions

1. Compile and simulate the existing generic `m7/rtl/shared_channel_scheduler.sv` with its real testbench as a bounded component test. Repair actual logic failures before integrating. Treat its Python model as an independent oracle, not hardware.
2. Extract and implement executable group/tap/link/VC maps: SROTA224groups/896taps; GEC-MECS32groups/96taps; hybrid those32groups plus48independentmeshlinks. SROTA group tap counts are not uniformly four: a native recorded group has seven taps, and directional segment lengths vary. Use each actual extracted group/tap list, never average-count reconstruction. Verify ordering and route/drop maps against native extraction.
3. Instantiate actual driver, ordered taps, per-tap VC credit ownership, serialization and destination selection in the family fabrics. TrackA independent links remain separate profiles.
4. Define packet/flit arbitration granularity from native enabled profile. Implement fair eligible service, stable stalled beat, packet-lock release and independent credit consumption/return. Count accepted beats, not one opaque Python Request per multi-flit packet.
5. Inventory all holdable shared locks, queues, buffers and allocation domains. Rebuild actual shared-resource CDG/progress proof. Per-tap slices must match allocator resource keys; no disguised alias.
6. Implement any enabled sidebuffer with exact capacity/ownership and reserved progress or a valid shared-pool theorem. `not_modeled` is honest incomplete status, not a safe disablement or proof.
7. Run shared contention/isolation/fair-service/credit-exhaustion/reset/drain tests and accepted byte-exact replay on all three profiles. Include a bandwidth test showing one driver cannot issue independent tap beats simultaneously.

### Acceptance

Three real instantiated shared-resource profiles pass their own complete proof, actual RTL and replay gates. Physical electrical behavior and PPA remain separate. Count/name profile records plus a generic scheduler do not finish M7.

## Package failures and re-planning

- A known source bug is an implementation task; assign the narrow production edit and regression.
- A missing build helper/runner is a WP01 task; do not repeat a proposal that ends before execution.
- An external active heavy owner is a scheduling blocker; preserve ready jobs and request ownership, without polling or killing it.
- A native-policy contradiction is a scientific decision: preserve counterexample, propose smallest same-resource corrected policy with an explicit new identity, and seek acceptance. Never rewrite history or silently relabel equivalence.
- A reviewer can approve a bounded component while the overall family remains incomplete. Keep both facts.
- A bounded round limit or quota checkpoint preserves all actual work and names the next task; it does not finish the original program.

## Command and test dispatch map

### Existing family emitter entrypoints

The following class names correspond to inspected existing source files. Run them only through WP01's private integrated Chipyard context, selected production sources/resources and capped execution wrapper. Do not run bare `sbt` inside a partial copied tree or write into the external `/tmp/opencode` tree.

| Required ID | Existing Scala entrypoint to inspect/reuse |
|---|---|
| mesh8x8 | `constellation.veritx.CatalogRtlMeshExport` |
| torus8x8 | `constellation.veritx.CatalogRtlTorusExport` |
| cmesh | `constellation.veritx.CatalogRtlCmeshExport` |
| fattree | `constellation.veritx.CatalogRtlFattreeExport` |
| flatfly | `constellation.veritx.CatalogRtlFlatFlyExport` |
| srota8x8 | `constellation.veritx.CatalogRtlSrotaExport` |
| gec_mecs | `constellation.veritx.CatalogRtlGecMecsExport` |
| gec_hybrid | `constellation.veritx.CatalogRtlHybridExport` |
| qtree | `constellation.veritx.CatalogRtlQTreeExport` |
| tree4 | `constellation.veritx.CatalogRtlTree4Export` |
| ring | `constellation.veritx.CatalogRtlRingExport` |
| fly64 | `constellation.veritx.CatalogRtlFly64Export` |

Conceptual job submitted to the runner:

```text
project constellation
<private candidate Compile/Test sources and resources already selected>
Compile / compile
runMain <the selected actual emitter class> <new private output directory> [supported topology ID]
```

The runner verifies each entrypoint's actual argument interface before invoking it. Existing factored/per-router emitters may be selected instead when they preserve the same profile and have proven decoder/hierarchy correspondence; record the actual class, do not pretend the generic entrypoint produced different bytes.

### Focused checks by package

| Package | Check to execute, not merely prepare |
|---|---|
| WP00 | Snapshot manifest validator: all listed files/hash identities, required ID set, coherent pre/post copy and ownership assertions |
| WP01 | Existing isolation helper tests, then actual private sbt load/source-list/compile and actual small RTL smoke; containment and malformed-argv/helper negatives |
| WP02 | Existing `tests.test_reference_contracts` plus newly recorded controlled native outcomes; actual private native probe run as needed |
| WP03 | New strict-progress/ghost-budget regression plus existing `tests.test_proof_mutations`; actual Scala revised exporter and independent family comparison |
| WP04 | Existing `LinkIdentitySpec`, `ParallelLinkNoCSpec`, `WidthWidgetSpec`, corrected `RouteTagTransportSpec` and real selector/transport production tests through the private runner |
| WP05 | Existing proof mutation suite plus malformed/unrelated/transition-mutated certificate and missing-query/resource negatives |
| WP06 | Existing decoder/binder tests, then actual emitted decoder query execution and complete typed/net physical-binding checks |
| WP07 | Harness event/scoreboard/receipt regression, then real ring and second-family RTL campaigns with assertions/internal observations |
| WP08–WP12 | Per-family native/proof gate plus actual configured-size emission, inventory/decoder correspondence and complete packet/branch matrix |
| WP13 | Approved-capture/lineage/schema negatives, then both actual RTL capture runs and independent output/refinement checks per family |
| WP14 | All corrected existing gate entrypoints plus actual fresh-source emission comparison and independent twelve-row release verification |
| WP15 | Real `iverilog`/`vvp` or pinned Verilator scheduler test, then instantiated three-profile shared-resource proof/RTL/replay campaigns |

New named checks must be implemented in the owning package. This table is not a claim they exist or pass. Each owner puts the exact executable command/argv, cwd, immutable inputs and expected outputs into its ready job after implementation; the execution owner runs it and records the actual result. Tests that simply check test-source presence or use only synthetic local substitutes are not substitutes for the production tests above.
