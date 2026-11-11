# Acceptance specification: a green row means working RTL

This is the normative test/evidence checklist for the [execution plan](../RTL-12-OF-12-EXECUTION-PLAN.md). Names of new test suites or receipt fields below are proposed implementation interfaces, not evidence that they already exist.

## 1. The twelve-row release predicate

Required IDs, exactly:

```text
mesh8x8 torus8x8 cmesh fattree flatfly srota8x8
gec_mecs gec_hybrid qtree tree4 ring fly64
```

For each required ID, the same declared release profile/source snapshot must pass:

```text
contract ∧ production_policy ∧ reproduced_source ∧ emitted_inventory
∧ reachable_resource_proof ∧ actual_decoder_correspondence
∧ actual_packet_credit_campaign ∧ approved_capture_replay
∧ fresh_reproduction ∧ independent_review
```

No UNKNOWN, BLOCKED, NOT_RUN, skipped mandatory test, missing file, failed query, unresolved alias or open correctness finding can count as PASS. A final matrix must fail if a required ID is omitted, duplicated, replaced, or counted twice through variants. Optional `dragonflynew` and Track B have separate tables.

Individual diagnostic/component commands may legitimately run a subset and report their limited results. They must not publish the final twelve-row predicate as satisfied.

### Artifact hierarchy

Keep four different claims distinct:

1. **Component checked:** an isolated model/parser/scheduler/test passes its scoped checks.
2. **Generated:** named connected RTL and all dependencies exist from a recorded completed emission.
3. **Simulated:** actual generated RTL executed the specified stimulus through the recorded simulator binary.
4. **Qualified row:** every conjunct above is independently supported on the declared source/profile.

Synthesis, timing, PPA and hardware qualification are separate false/not_run claims unless independently established.

## 2. One source/profile identity, not a bundle of unrelated successes

Each phase records:

```text
required topology ID / realization / profile ID
source snapshot and configuration identity
native reference/probe identity
phase and immutable run ID
actual command argv / cwd / environment / tool hashes
actual start/completion or failure / exit/signal
input artifacts and hashes
output artifacts and hashes
raw stdout/stderr and runtime evidence reference
explicit status / limits / predecessor run identities
```

Reuse and extend current receipt formats; do not build a general evidence platform. Existing schema names may remain where semantics are correct. A small root manifest can link phase receipts without duplicating all records.

### Required behavior

- Hash source **contents**, dirty edits, required untracked files, configs, tool binaries and selected dependencies. HEAD alone is not a source snapshot.
- Freeze input coherently; compare hashes before/after capture. Reject mutation during capture/run.
- Keep native/M2 historical accepted evidence separate from current-candidate source identity.
- A `complete` phase needs successful actual execution and every required artifact parsed/verified. Publish terminal receipts atomically; partial files remain partial.
- An emission completion marker does not complete lint/build/simulation/replay.
- Exit0 plus OOM/uncaught exception/missing modules is failure. Timeout, cancellation and signal death remain failures/not-complete.
- Actual top, helper and compiled-binary hashes must match the ones that executed. File basename or directory name is not identity.
- Do not consume stale output merely because a preferred file already exists.
- Final release uses one frozen integrated source; branch-specific historical successes cannot be assembled into a fictional same-source release.

### Trust model

The execution owner/orchestrator and pinned runner are trusted to execute commands honestly; independent verification protects against implementation mistakes, stale/forged-by-helper records, mismatched files and unsupported claims. A malicious host able to fabricate every log is outside this local process model.

A JSON field saying `status=success` is not execution authority. The orchestrator must possess the actual execution tool/run result plus raw command/log/exit artifacts and independently verify outputs. Do not replace actual execution with signatures around invented receipts, or claim local receipts are tamper-proof hardware attestation.

## 3. Independent native contract acceptance

For every family:

- Exact configured physical router/link/terminal identities and mappings match the frozen accepted target.
- Width, VC counts, per-VC buffer capacities, route law and enabled controls are resolved from real config/defaults.
- Link multiplicity, shared grouping/drop order and terminal concentration are preserved.
- Any native constructed-but-unrouted resource discrepancy has an explicit approved target mapping. Required resources are never pruned to make proof pass.
- Native nondeterministic/controlled alternatives have actual invocation records, not solely a deduplicated output union.
- Queries cover injection and reachable transit incoming-link/VC/state contexts. An arbitrary Cartesian product is neither a valid completeness argument nor permission to discard inconvenient states.
- Keep the proof compositional where justified: the resource safety graph covers every legal selector outcome, while a separate production control invariant/test proves FIU/occupancy logic selects only such outcomes. Do not enumerate every global telemetry/clock/counter combination if a sound local contract discharges that obligation; do not omit real packet state that changes legality.
- Timing/allocator/realization differences from native are declared. The target is the accepted functional resource/routing contract, not an unproved exact timing-equivalence claim.

Negative checks: wrong config hash, unresolved default, missing alternative, wrong VC/drop, parallel resource collapse, wrong native/dense mapping, terminal permutation and unaccepted capture cannot pass.

## 4. Production state and selection acceptance

The verifier records a per-family relation between native policy state, exported state and physical RTL state. Test it end-to-end.

### Invariants

- A selected output/VC is a subset of the independently certified legal mask.
- Injection order/shape is committed by the actual enabled policy/test control, not independently chosen again by the allocator.
- Transit respects actual incoming VC/link and stored state. An ignored carried route tag cannot prove a choice was enforced.
- Parallel mesh/express outputs retain separate IDs, queues and credit state.
- Each input VC/head owns independent committed state. An interleaved packet cannot overwrite another's selection.
- A stalled advertised request or beat retains valid and its required bits until accepted/reset under the declared interface contract.
- Body/tail follow the head's reservation. Release occurs at the actual protocol event; subsequent packets see clean state.
- Local ejection addresses the correct terminal seat without allocating an unnecessary network hop.
- Width conversion preserves all payload and metadata across odd beat ratios/partial final beats supported by the profile.
- Source/profile metadata widths agree with actual compiled ports; invalid/reserved values are asserted/rejected as specified.

Mutation checks must alter the production path: truncate a required bit, change a committed order, merge parallel credit counters, select outside mask, leak state between packets, bypass a true decoder input. A synthetic Queue that does not instantiate the changed production modules is supplemental only.

### Deep-interface migration gate

For each changed module, acceptance additionally requires:

- A caller inventory and one stated owning concept; special cases, validation, ordering and derived values live inside that owner, not duplicated at call sites.
- The deletion test justifies the module: trivial pass-throughs are merged away; real complexity does not leak back to callers.
- Derived, universally constant and unread parameters/flags are gone; no opaque parameter bag or global mutable configuration merely disguises them. Genuine runtime observations and supported variants remain represented.
- Every in-scope caller and test uses the new interface; superseded overloads, compatibility wrappers, duplicated computation and fallback paths are deleted, not left deprecated.
- Public-behavior regression checks preserve supported functionality, failure semantics and ordering through the same interface production callers use. Existing scientific negative regressions remain covered independently.
- Actual instantiated RTL/runner construction uses the new path; a cleaner unused helper is not a migration.
- Historical source snapshots and evidence are preserved. Removing an old production interface is not authority to delete the record of a previous run.

This is a scoped migration requirement, not permission for a repository-wide unverified rewrite. Refactor one ownership seam at a time, keep intermediate states buildable, and execute the final deletion step before package acceptance.

## 5. Proof and progress acceptance

### Reachable state domain

Cover every ordered terminal pair and every legal injection commitment, then explore all reachable native/candidate selector outcomes and incoming-resource states. Include internal routers with no attached terminals. Preserve complete physical mappings.

A query includes every relevant field: incoming link/port or injection context, incoming VC, actual source/flow/terminal context if relevant, destination and packet/control state. State compression is allowed only with a checked equivalence argument.

### Physical resource CDG

- Vertices are actual allocatable buffer/VC or other holdable resources, with true aliases/locks/pools represented.
- Flow IDs, packet tags and route shapes do **not** create additional physical buffers.
- Dependency A→B requires a realizable packet holding A while requesting B. Preserve predecessor-VC and packet-context compatibility.
- Union all such dependencies across flows and selector outcomes on their physical resource identities.
- A deadlock cycle may involve different flows/packets. Never demand a single flow traverse the entire cycle before accepting a counterexample.
- Verify the complete merged graph acyclic for the approved Track A construction. Rank certificate must include every relevant resource and satisfy rank(A)<rank(B) for every dependency.
- If the actual implementation introduces a shared pool, lock or staged resource, add it to the proof; do not keep an obsolete independent-buffer theorem.

### Delivery/progress

Every reachable nonterminal state has at least one legal successor, every legal branch ejects at the intended terminal eventually, and a well-founded nonnegative measure strictly decreases on every network hop. Terminal states have valid ejection and zero remaining measure.

Decrease need **not** equal one. Express jumps may decrease Manhattan distance by several units. A corrected strict-decrease exporter must still reject unchanged/increasing/negative measures and wrong terminal states.

### Actual certificate verification

Recompute or independently verify proof contents against exact source/export/native/inventory identity. Validate the recognized schema, all state/resource coverage, every edge/rank and progress/ejection conditions. A digest plus `certified=true` or literal `b"proof"` fails.

### Required negative suite

- torus wrong seam/turn reset;
- shared XY/YX VC resources;
- SROTA missing rank split;
- down→up NCA turn;
- hybrid dimension/distance regression;
- collapsed parallel resources;
- missing required link/router/terminal/query;
- wrong butterfly terminal/stage permutation;
- arbitrary/malformed/unrelated certificate;
- changed transition with old certificate;
- source/profile/decoder hash drift;
- underexplored reachable prefix or invented incompatible predecessor.

Unsafe mutations are expected-negative separate runs, not passing production tests. Preserve a concrete witness when rejecting them.

## 6. Actual RTL inventory and decoder correspondence

### Inventory

Validate real elaborated/compiled hierarchy and net connections, not just source graph JSON or module-name counts:

- exact physical router cardinality and native↔implementation identities;
- every required directed link instance and separate reverse credit connection;
- correct source/destination output/input ports and VC identity;
- terminal injection/ejection direction and seat map;
- actual payload/tag/VC/buffer dimensions, with payload bits distinguished from total link/flit width including routing/framing sidebands;
- correct clock/reset connection;
- no stubs, missing blackboxes/helpers, unintended fake routers or required pruned/untraversable channels;
- no collapsed nearest-neighbor mesh/express parallel links.

For partitioned generation, every included module must match the same source/config/elaboration snapshot. Check top-to-partition connectivity and unresolved/duplicate module definitions. Router files in a directory are not automatically an assembled fabric.

### Decoder/selector correspondence

Run actual emitted decoder instances for the complete reachable query set. Compare observed legal output/VC bits to the independent native/certified relation. Check absent bits as well as expected bits; first-hop union sampling is insufficient.

Then check actual runtime selector output/committed allocator masks are within that legal set, with policy-specific occupancy/control choices correct. Force native-permitted alternatives through test controls that cannot manufacture illegal outputs. Trace actual selected masks into the allocation path, not an unused debug duplicate.

Mutations: emitted decoder bit, link alias, VC number, seat mapping, missing partition/helper, stale top, unbound input state and incomplete expected resource domain all fail. No row PASS while the binder returns partial/unresolved.

## 7. Packet and credit campaign

All twelve have64terminals. Required results are accepted-event based; attempted sends are diagnostics only.

### Test groups

| Group | Required coverage | Acceptance |
|---|---|---|
| P0 startup/local | Reset cleanly; every terminal and same-router seat pair | Correct local egress, no phantom flit/credit/state |
| P1 exhaustive pairs | Every4096orderedpair, each distinct length in `{1,2,5,B+1,2B+3}` for actual VC depth B | Exactly once, correct destination, byte-exact payload/head/body/tail and full drain |
| P2 route choices | Every relevant legal injection order/selector branch/NCA alternative; all required physical link witnesses | Actual observed branch/link coverage, not scheduled-but-unaccepted intent |
| P3 contention | Seeded uniform, transpose, permutation, hotspot and same-output competition | Conservation, allocator legality and finite service under stated assumptions |
| P4 independent sinks | Every sink held then released; mixed stalls, random ready-low and injected valid gaps | Held beat stability and eventual drain after release |
| P5 capacity/credit | Long packets exceeding buffers, credit exhaustion, simultaneous return/consume, delayed tail/VC release | Correct per-resource bounds/token conservation; no cross-VC/tap credit alias |
| P6 reset epochs | Startup plus explicit mid-traffic flush/reset/restart scenario | Old-epoch accepted packets explicitly flushed or delivered, never silently lost/recounted; no stale output in new epoch |
| P7 consecutive/interleaved | Different routes/VCs/packets interleaved; single-flit head+tail and back-to-back packets | No head-state/tag/reservation leakage or duplicate release |
| P8 diagnostic refinement | Actual internal link/VC/allocation observations during representative traffic and forced witnesses | Every observed transition legal and mapped to certified physical state |

`B` is the real profile depth: mesh15, CMesh8, fat-tree16, FlatFly4, GEC32, etc. De-duplicate equal lengths; do not assume9flits exceeds every family's buffer. Use fixed published seeds, initially1,7,42, for stochastic stress; exhaustive/forced coverage does not depend on luck from these seeds.

### Payload/framing

- Exercise all128bits, including nonzero/high-bit patterns and independent upper/lower64-bit values.
- Maintain expected payload bytes independently of RTL decode/route code. Avoid comparison code that repeats the same packing bug as the driver.
- Check exact number/order of flits and head/body/tail per packet. Head+tail together is valid for length1.
- Synthetic IDs/patterns are test data. Real replay bytes must never be replaced with synthetic IDs; use sidecar trace correlation or declared framing metadata.
- A payload digest supplements, not replaces, comparison against independently expected bytes. Counts alone are insufficient.

### Common-edge event sampling

Specify when signals are driven, settled, snapshotted and clocked. Compute ingress and egress acceptance from the same edge's valid/ready values, then update scoreboards exactly once. Snapshot before sequential updates where required by the simulator model. Add directed regression where a beat enters/exits on the edge ready/valid changes; it must neither disappear nor be counted twice.

### Conservation

For each epoch and global run:

```text
accepted = delivered + explicitly_flushed + outstanding
```

Track packets and flits separately, with per-source/destination/packet identity as well as totals. At final drain, outstanding=0; no duplicated/unexpected delivery exists. Every expected-negative fault should demonstrate a verifier failure.

For each physical VC, verify token/credit accounting from actual update events. In the inspected OutputUnit free credits start at capacity, decrement on allocation and increment on credit return. Account for data/allocated tokens and returned credits in flight, staged transfers and receiver occupancy according to actual pipeline timing. The sum must equal configured capacity; valid bounds alone do not prove conservation. Keep VC ownership/tail release distinct from available credit.

### Fairness and drain

Packet simulation does not prove deadlock freedom. Likewise a CDG proof does not prove scheduler fairness or byte integrity.

State fair-arbitration and eventual-sink/credit assumptions. For a numerical drain limit, derive a conservative bound from finite accepted work, actual per-hop/credit pipeline delays, arbitration service guarantees and resource-DAG dependencies. An arbitrary fixed timeout is a watchdog, not a proof. If arbitration guarantees only eventual service without a cycle bound, report that honestly and supply the missing bounded-service argument before claiming the bound.

For contention fairness, monitor the number of **eligible competing grants**, not merely elapsed cycles when downstream is blocked. A packet lock must eventually release on its true tail under the stated assumptions and cannot strand an unrelated destination forever.

## 8. Family-specific mandatory observations

- **Mesh:** no wrap/diagonal/express substitution; XY direction and turn correct; exact4VC/depth15.
- **CMesh:** all four seats/router independently inject/eject, including local seat-to-seat and same-router contention;16VC.
- **Ring:** both signs, seam injection, seam transit, distance32 ties and stable direction;2VC.
- **Torus:** both dimensions/signs, distance4ties, seam cases and X→Y dateline initialization;2VC; no globally monotonic VC-number shortcut.
- **QTree:** all native leaf-seat mappings, same/cross-subtree paths and internal no-terminal routers;21physicalinstances.
- **Tree4:**28physicalinstances, sparse identities, multi-root parent alternatives, no spanning-tree reduction.
- **Fat-tree:**48physicalrouters,256links, every legal ancestor/uplink represented/forced, no down→up regression;depth16.
- **Fly64:** stage and digit/terminal permutation, distinct injection/ejection maps, no earlier-stage return.
- **FlatFly:** both injection orders actually enforced, VC-half commitment throughout transit, aligned cases and cross-half negative.
- **GEC-MECS:** correct native peer/drop ordering and tap-specific VC ranges; TrackA explicitly independent taplinks.
- **Hybrid:** every144link including both adjacent resources; live native-equivalent used occupancy, meshH/expressH, tie-to-express, arithmetic width, per-hop reevaluation but stalled-head commitment.
- **SROTA:** both configured O1TURN choices through actual FIU/control, rank split, aligned normalization, enabled telemetry/epoch/reset behavior, full896links; no invented static profile substituted for configured dynamic behavior.

## 9. Approved-capture RTL replay

For both approved captures, all twelve families must show:

1. Capture acceptance provenance and exact raw input hashes.
2. A common documented packetization, terminal attachment, byte order and padding contract.
3. Actual recorded compiled RTL execution on those packets, using the same source/profile/top/helper/binary as the row's other evidence.
4. Collision-safe IDs or separate files for single vs sequential capture runs.
5. Exact input→packet→acceptedflit→deliveredpacket→reconstructedoutput byte lineage.
6. Correct causal predecessor/sequence constraints from the approved capture semantics, plus complete drain.
7. Actual internal trace refinement against the certified relation and physical mappings.
8. No fabricated success receipt, no prewritten JSONL accepted as proof that a simulator ran, no latest-but-failed capture silently promoted to accepted.

Validate result schema and semantics, not just hashes of arbitrary files. Negative cases include unapproved capture, wrong executable/helper, stale binary, same capture presented as both kinds, wrong byte, invalid result schema, repeated packet ID and reordered causal output.

This validates replay fidelity, not application acceleration or congestion benefit. Sequential sparse captures cannot replace P3–P5 stress.

## 10. Fresh reproduction and final review

The final pinned source must be emitted in a **new output root through a real recorded invocation**. Compare named top, all helpers/blackboxes, transitions and full inventories. A copied old tree with a new JSON receipt fails.

If output includes nondeterministic metadata, first isolate the exact source. Normalize only explicitly nonfunctional metadata, preserve raw artifacts and validate the resulting functional comparison. Do not mask changed expressions/connections/widths or accept arbitrary hash differences.

Independent reviewer must inspect:

- full required-ID set, one final source/profile chain;
- actual production code, not only RESULT prose;
- native policy/reference identity and declared differences;
- certificate validity and physical resource/query completeness;
- actual emitted-module/net and decoder observations;
- raw commands/tool results/exit/logs/artifact hashes;
- packet/flit/credit/reset/coverage/drain evidence;
- actual capture bytes/lineage/refinement;
- fresh reproduction and all unresolved findings.

A reviewer may approve a bounded component with explicit nonclaims. That is not a family PASS. A final correctness finding remains blocking until fixed and reverified; a review-round cap cannot override it.

## 11. M7 / Track B acceptance is separate

For SROTA, GEC-MECS and Hybrid shared profiles, additionally require:

- executable native-derived group/tap/VC maps and actual instantiated shared driver;
- exact one-driver serialization/bandwidth and declared packet/flit granularity;
- per-tap/VC credit ownership, destination isolation and stable stalled beat;
- packet-lock/sidebuffer ownership and release modeled in actual proof resources;
- finite fair service under eligibility/sink assumptions;
- complete shared-resource CDG/progress, not the former expanded P2P proof;
- real component and full-fabric RTL contention/credit/reset/drain tests;
- approved byte-exact replay and source reproduction for each profile;
- hybrid's48meshP2Plinks remain independent.

A generic shared scheduler and profile count constants are useful beginnings, not these three passing implementations. Physical electrical modeling, synthesis/PPA and board/silicon results remain outside this logical shared-resource gate.

## 12. Release gate interfaces

Reuse the existing workspace tools, repairing their semantics before trusting their exit codes:

```bash
python3 tools/check_contracts.py --all
python3 tools/check_routes.py --all --require-acyclic --require-full-link-coverage
python3 tools/check_rtl_inventory.py --all
python3 tools/run_rtl_matrix.py --all --serial
python3 tools/replay_holoscan_rtl.py --all --captures accepted --serial
# Existing audit_m8.py: inspect its actual CLI and bind the final snapshot/run inputs.
```

These are existing/planned gate entrypoints from the approved program. Their present implementation may read old/prewritten records or resolve paths incorrectly; invocation alone is not proof. Execute from private inputs/outputs with explicit source/profile/run identities. Verify the actual `--all` required set and artifact semantics.

Optional thin new entrypoint:

```text
tools/qualify_rtl.py --all --snapshot <frozen-id> --out <fresh-run-root>
```

Implement only if a small orchestrating adapter is needed; it should call/reuse corrected existing gates, not create a parallel verifier stack. Final result exits0 only after the complete twelve-row predicate. Diagnostic `--topology`/subset modes must label their scope and cannot publish 12/12.
