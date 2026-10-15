# Execution closure plan

## Scope and starting point

Requested order: plan first, then execute. Cover the unlanded kernel/address/
memory/IP/product integration and the remaining multiplane/CDC, coherence,
power/sideband/reset, and native RCU/multicast execution gaps.

Initial audit HEAD: `38ccbd15` on `integration/studio-reconciliation`; the
implementation was subsequently committed at `bf26286e` (W1-W6 reference
increments). The current checkout still has mixed dirty documentation/owner
changes and is not a clean qualified baseline. The existing architecture audit
is historical: its `0c78f27b` assertions do not describe all current behavior.
Native coupled tensor execution is bounded diagnostic timing; reference byte
images and controller acknowledgement are not hardware equivalence.

## Rules

- Preserve staged, unstaged, and untracked work. No reset/clean/stash, producer
  repinning, or mixed-session wholesale commit. Record before/after hashes.
- One scheduler, one resource authority, one address resolver, one transaction
  identity/epoch vocabulary. Extend the existing executor; no standalone
  demonstration engine masquerading as connected execution.
- Reuse model declarations. Missing runtime policies refuse explicitly; no
  inferred placement, routing, retention, or protocol semantics.
- Existing supported evidence remains byte-identical when a feature is absent.
  New semantics bind their configuration into evidence and replay validation.
- Each increment needs execution, conservation/invariant checks, negative
  controls, and deterministic replay. A status word or structural certificate
  is not completion.
- Native builds use `-j1` and disk-backed cache. Existing pins remain intact.
- Independent review is a separate required landing gate, not implied by a
  green test run. This plan does not authorize spawning additional agents.

## Dependency order

```text
W0: captured integration baseline + historical replay comparison
  -> W1: kernel/fault lifecycle + address/memory/IP/product reconciliation
    -> W2: concurrent planes and CDC on the shared timeline
      -> W3: requester caches and directory protocol
        -> W4: domain power, sideband and reset lifecycle
W1 -> W5a: native RCU representation and execution
W1 -> W5b: native multicast representation and execution
W2 + W3 + W4 + W5 acceptance -> W6: combined scenario and clean release gate
```

Implement sequentially in this checkout. No overlapping writers on
`data_movement.py`, `coupled_tensor.py`, `compile_model.py`, or product storage.
Native work can use isolated vendor copies, not concurrent source edits.

## W0 — capture and establish a real baseline

1. Record HEAD/branch, complete Git status, staged and unstaged patches,
   untracked files, and per-file hashes outside the checkout.
2. Run focused kernel, fault, data-movement, coupled, address-decode,
   memory-lowering/multichannel, tensor, IP, gateway, and qualification tests.
   Run native coverage with the explicit config; record all skips and failures.
3. Compare default data-movement and coupled artifacts with the pre-kernel
   committed implementation in an isolated source copy. Comparing an injected
   kernel with a newly constructed kernel is not historical preservation proof.
4. Run product registry gates. Attribute failures to concrete changes before
   editing; never weaken the gate merely to accommodate work in progress.

Exit: reproducible source/test manifest and an attributed blocker list. Dirty
or copied-source proof is diagnostic, not clean committed release evidence.

## W1 — reconcile and land existing work

### Shared kernel and bounded faults

- Keep exact Fraction time and response-before-timeout ties.
- Check resource occupancy/release and transaction epochs across retries,
  horizon stops, and drain resets. Every active attempt has bounded progress;
  stale events cannot commit or retire it twice.
- Arm response deadlines per response attempt, not once per logical child.
  A deadline shorter than every response must exhaust the budget, not succeed
  because the second attempt has no deadline. Memory commits once regardless.
- Bind fault configuration into replayable evidence. No-fault evidence retains
  its old bytes and scope; fault evidence must not claim no loss recovery.

### Address and memory integration

- Preserve legacy singleton identity and round trips.
- Prove FIXED_INSTANCE/STRIPED selection across range/stripe boundaries;
  gaps, overflow, unauthorized bytes, and invalid attachment bindings refuse.
- Use one canonical resolver for every concrete system-address-to-fabric-endpoint path, including tensor demand and any memory-lowering path that consumes authored system-address spans. The existing abstract `LOCAL` operand memory lowerer starts from byte counts and coarse locations and allocates memory regions; it has no concrete system addresses, so it must not be fed synthetic spans through the fabric decoder. If a concrete-address memory-lowering input is added, it must consume the same compiled decode artifact rather than duplicate endpoint selection.
- Native multichannel dispatch keeps device identity separate from channel
  ordinal, authenticates address mapping, respects access dependencies at
  callbacks, retries admission without duplicating requests, and conserves
  logical/generated/padding bytes. Verify live native mapping separately from
  mocked dispatcher tests.

### IP and gateway/product integration

- Preserve template/version/instance identity through stamp, compile, export,
  persistence, reload, and execution on the existing backend path.
- A stamped HBM controller abstraction is not vendor IP or HBM3E timing proof.
  Additional templates need actual materializers and execution consumers;
  unsupported rows stay refused instead of inheriting a generic READY flag.
- Test stale-draft rejection, concurrent update/publication behavior, failure
  atomicity, supported/unsupported schemas, and no mutation on refusal.
- Group commits by actual dependencies: shared model fields may be required by
  both address and IP work. Split shared model additions first where possible;
  do not mechanically stage whole files from another session.

Exit: dependency-coherent commits, focused gates/replay proof and independent
review; then a clean integration checkpoint. Until ownership is reconciled,
retain mixed edits uncommitted and name the blocker.

## W2 — connected multiplane and CDC scheduling

Consume `MultiPlaneVCAssignment`, control-plane routing authority, compiled
resource graphs, and explicit clocks/crossings. Plane selection comes from the
bound traffic class; request and response may select different planes.

- Plane-local resource keys prevent channel/VC ID collisions.
- Shared endpoint interfaces, FIFO bridges, and memory service are explicitly
  declared shared resources; do not duplicate capacity per plane.
- Each phase uses its owning clock with exact edges. CDC uses the existing
  GRAY FIFO semantics; width conversion or missing crossings remain refused.
- Keep deterministic bounded routing initially. Broaden adaptive/shared-wire
  routing only with its separate routing and resource proof.

Exit: one run executes both planes concurrently; independent channels overlap,
shared resources contend, request/response dependencies hold, each plane
conserves traffic, and FIFO/credit accounting drains. Mutating plane bindings,
missing crossings, or duplicate resource ownership must fail. Single-plane
artifacts remain unchanged. This is reference execution, not RTL CDC signoff.

## W3 — coherence protocol, not owner-cache relabeling

Start with an explicit bounded MSI directory profile: one home per cache line,
multiple requester caches, fixed line size, deterministic line arbitration,
and authored network/memory costs. Existing BYPASS/OWNER_CACHE keeps its scope.

- Implement invalid/shared/modified state, directory sharers and dirty owner,
  and transient states while acknowledgements/recalls are outstanding.
- READ miss, ownership acquisition, invalidate/ack, dirty recall/writeback,
  fill and eviction are real transactions on the shared scheduler.
- Do not grant exclusive ownership before required acknowledgements/dirty data
  return. Preserve partial-write bytes and one authoritative latest value.
- Reuse retry identity/epoch for duplicate suppression; losing an ACK cannot
  apply a write or grant ownership twice.
- Atomics, MMIO and more protocols are separate increments, not silently
  approximated by MSI.

Current status: PARTIAL. MSI issue now atomically reserves every full line in
the lowered request, all current requester-cache lines that can become LRU
victims, and the affected finite requester caches. Reservations remain held
through response retirement; disjoint requests with independent cache state can
progress together, while overlapping lines and same-cache LRU mutations are
serialized. Issue scheduling is reawakened after response retirement, and reset
checks include outstanding reservations. W3 remains unaccepted: hostile
concurrent interleavings, cache-capacity pressure, retries/lost ACKs, and
out-of-order disjoint commits have not been validated.

Exit: two requesters share/read, one writes after invalidation, the other reads
fresh data after dirty recall, and eviction writes back correctly. Hostile
interleavings, capacity pressure, lost ACK and illegal ownership mutations are
checked. No conflicting writers, leaked transients or unresolved credits.

## W4 — power, sideband, reset

Use declared power domains, reset channels and sideband connections. Define
explicit supported policies before execution: drain or refuse in-flight work,
isolation ordering, retained/cleared cache and memory state, wake latency,
reset scope and release dependencies. Do not invent policy from a domain name.

- Schedule drain -> isolate -> sleep; admission to sleeping endpoints stops.
- Execute interrupt/wake/reset on the declared control path with appropriate
  synchronization. Wake path requires an active clock/domain.
- Restore clock/state -> remove isolation -> resume admission in order.
- Coherence dirty state is retained or flushed according to policy, never lost
  silently. Reset uses epochs so old responses cannot complete new work.
- Distinguish the existing global DRAIN_RESET from domain-local reset. Unsafe
  mid-flight reset and unsupported retention/CDC policies refuse initially.

Exit: a live workload sleeps and resumes via an interrupt; blocked requests
resume once, retained/cleared state matches policy, reset ordering is observed,
and stale responses are rejected. Control trace and transaction evidence agree.
No energy/PPA, clock-drift, RTL reset or physical isolation claim.

## W5 — native advanced network execution

Two separate deliverables, not one generic advanced-routing switch:

### W5a RCU

Confirm the repository's RCU reduction semantics and actual producer support.
Bind compiler resources, opcode, participant IDs, operation identity and
payload format to the native implementation. Execute reductions consuming
buffers/links/RCU capacity; validate contributor counts, numeric results,
ordering, completion, and bounded backpressure. Unsupported operations and
producer fields refuse before launch. Host-side reduction is not native RCU.

### W5b multicast

Bind authored destination sets and replication points to native routing and
allocation. Validate every destination receives once, branches consume real
link/buffer resources, and credits/flits drain with fanout and congestion.
Duplicated unicast remains labeled replicated unicast. Qualification requires
observed native branching, negative controls for missing/duplicate branches,
and producer-bound repeatable evidence.

Exit per feature: compiled semantic binding, live native execution, correct
results/delivery, resource conservation, unsupported-envelope refusals,
replay, and independent review. Changes to vendor source require their own
provenance-preserving commit/build evidence; never re-pin to bypass guards.

## W6 — combined proof and release

Run one connected scenario with concurrent data/control planes, two rates,
coherent read/write traffic, a lost response/ACK, and sleep/wake/reset. Assert
final bytes, ownership, completion/dependency ordering, epochs, resource and
credit drain, and per-plane traffic conservation. Test native advanced
features in their own supported profiles; do not pretend all profiles compose
until a real combined adapter exists.

Run `scripts/ci_gate.sh` on a stable committed tree, explicit native tests,
registry/capability checks, replay/tamper tests, and fresh review. Record exact
source/producer/config hashes, commands, results and residual refusals. Skip
is not pass. The current pytest `timeout` warning means the configured timeout
is not enforced; use explicit command deadlines for focused verification.

Completion report separates REFERENCE_EXECUTED, NATIVE_DIAGNOSTIC_EXECUTED,
and QUALIFIED. Calibration/hardware/RTL/physical signoff are separate work;
these execution increments do not earn those claims.

## Current status (source implementation; acceptance remains open)

As of 2026-10-10, the mixed checkout has source changes for W1-W4, W5b, and
W6. The owner explicitly excluded W5a/RCU. Fresh source reviews cleared W3
reservation logic and W5b route/physical-link accounting. A W6 review's three
assertion gaps (per-plane conservation, final ownership, and DAG completion
ordering) are now fixed and reviewed. A suspected dirty-recall/reset loss was
traced through commit and withdrawn as a false positive. W1's multichannel
Ramulator aggregation now weights read/write latency and queue means by their
actual denominators; its regression fixture is updated but unrun. Source
reviews do not replace execution evidence.

- W0: mixed-tree snapshots were captured outside the checkout at
  `/tmp/execution-closure-w0-20261010T114212Z`,
  `/tmp/execution-closure-implementation-20261010T121854Z`,
  `/tmp/execution-closure-w2-20261010T124126Z`, and
  `/tmp/execution-closure-w2-w5-after-20261010T135336Z`. Each records HEAD,
  branch, status, working-file hashes, staged/unstaged patches, and untracked
  hashes where present. These are local ephemeral snapshots, not a durable
  release manifest. Historical replay and product/test gates were not run;
  baseline exit criteria remain open.
- W1-W2: implementation/reconciliation is present in the working tree. The
  W1 resolver boundary is now explicit: tensor demand and any concrete
  system-address path use the compiled fabric decode; abstract LOCAL operand
  lowering remains a distinct byte-count/region-allocation path. No current
  mismatch was found. FIXED_INSTANCE/STRIPED boundaries, refusals, native
  multichannel mapping, and the latest changes still lack current-tree gate and
  historical-replay evidence.
- W3: MSI uses atomic line/cache reservations, defers commit until protocol
  completion, and keeps reset/drain checks. Hostile interleavings, eviction
  pressure, lost-ACK retries, and disjoint out-of-order commits remain
  unvalidated; W3 is not accepted.
- W4: bounded authored power/wake/reset policies and epoch checks are present;
  runtime lifecycle acceptance remains unverified.
- W5b: source-level native multicast binding, route-path checks, and
  physical-link conservation (excluding destination ejects while retaining
  them in route traces) are present and source-reviewed. The historical experimental
  `tracks/t3-topology/booksim-ext/multicast.patch` is preserved as
  `archive/booksim-ext/multicast.patch`; it is useful precedent, but its
  TrafficManager-generated modes and direct-eject copies do not meet the
  authored-operation/real-branch-resource contract. The current native source
  has not been built or replayed, and the executable/source build relationship
  is explicitly unproven.
- W6: source assertions cross-check per-plane phase-ledger totals, replay
  committed MSI-directory snapshots against final ownership, and verify
  exact-once completion plus authored dependency order. These checks have fresh
  source review; the combined scenario has not been executed.
- Release: no tests, builds, replays, CI, or staging/commit were performed in
  this continuation. The working tree remains mixed and dirty; release gates
  and qualification are therefore open. Hardware equivalence is not claimed.

## Reconciliation execution record — 2026-10-11

This checkout remains a mixed, uncommitted working tree based on
`38ccbd1585bd5d5f1d8ba31a168ebc337d1ae93c`; the preserved index tree is
`5c3290ff33efe55f1ef7743e82d8f70aceca3195`. All commands below used explicit
shell timeouts and external disk-backed `TMPDIR`/pytest basetemp. Their proof
scope is limited to this source state.

- Focused runtime regression: 168 passed, 1 warning. It includes the new MSI
  first-read shared-directory repair plus coupled tensor, kernel, fault, and
  native-multicast serialization tests. This is reference runtime evidence;
  native serialization tests do not constitute native engine execution.
- Focused product/truth/diagnostic regressions: 292 passed, 1 skipped, 1
  warning. The skip depends on an archived ASTRA binary. The Verilator F3
  checker ran with `-j1`, proving its standalone assertions only; no DUT/UVM
  checker hookup or full UVM integration is claimed.
- Earlier repair batch also reported 105 focused tests including real standalone
  F3 `-j1`, 97 nearest tests (2 deselected), 135 selected Studio tests, and
  TypeScript success. These are prior-run results, not a claim that the full
  present-day Studio or Python suite is green.
- A reference MSI scenario exercised two readers, partial writes and
  invalidation ACKs, dirty recall, fresh read, and finite-capacity dirty LRU
  eviction/writeback. It checked returned bytes, untouched bytes, six
  issue/commit/response completions, no live children, and balanced FIFO
  reservations. It is not native/coherence-hardware evidence.
- Targeted document/capability edits withdraw concentrated-mesh runtime
  QUALIFIED status, update Loom's address-map/multiplane/V5/reference-runtime
  boundaries, mark the production seal historical, and distinguish live Studio
  gateway behavior from explicit fixture-only `/offline`. Tests now assert the
  supported/diagnostic/unsupported text distinction. These docs/tests must pass
  the current product gates before acceptance.

Validation update: `make -C tracks/t3-topology product-gates` passed after
concentrated-mesh registry stages were changed to QUALIFIED=NO and the topology
family evidence was corrected to match `capability_truth`; no checker was
weakened. Targeted capability/product tests passed (69 passed, one pytest
unknown-timeout warning). Earlier focused product/runtime run reported 292
passed, 1 skipped (archived-ASTRA-binary dependency), 1 warning; runtime-focused
suite reported 168 passed, 1 warning. Both had explicit shell deadlines and
external temp paths.

A full DSE pytest attempt terminated with **20 failed, 6,399 passed, 34
skipped, 1,068 errors in 442.26s**. Representative setup errors were
`FileNotFoundError` for the configured pytest basetemp path, which had not been
created before launch; this is infrastructure/setup evidence explaining many
collection/setup errors, not proof that all failures are infrastructure. A
subsequent retry was interrupted by the status-file quota crash and has no
terminal result. Do not call full pytest green. A Studio `npm` command attempted
from the repository root failed immediately because no root `package.json`
exists; a later `cd apps/studio` build/test attempt did not produce a preserved
terminal result. Thus current full Studio tsc/Vitest status is unproven. The
shared `scripts/ci_gate.sh` was not completed.

Still open: W2 connected multi-plane/two-rate contention and CDC, W4 lifecycle
acceptance, combined W6 execution/replay/tamper controls, native multicast
build/replay, clean release build, qualification, and hardware/physical signoff.
No mixed-tree result is promoted to those claims.
