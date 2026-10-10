# Execution closure baseline

**Branch:** `integration/studio-reconciliation`
**Reference commit:** `0c78f27b` (`feat(model): checkpoint scoped execution support`)
**Audit date:** 2026-10-10
**Purpose:** Establish exactly what is already implemented before any
execution-closure code changes (Phase 0 of the master execution prompt).

---

## 0. Repository state at audit time

- Branch and HEAD match the required reference (`0c78f27b`).
- The working tree is **NOT clean**. Concurrent sessions own uncommitted work in:
  - `veritx_dse/model/address_decode.py`, `model/compile_model.py`,
    `model/ip_catalog.py`, `gateway/app.py`, `product/service.py`,
    `backend/ramulator_adapter.py`, `workload/*` (address-selection session);
  - `veritx_dse/backend/native_coupled.py`, `native_booksim.py`,
    `model/native_coupled.py`, `tests/test_native_coupled.py`,
    `backend/` artifacts (native-coupled diagnostic session).
- **This audit does not claim those changes.** No Phase 0/1 work may modify,
  stage or revert those files. Two pre-existing gate failures are attributable
  to them (see §7).

### 0.1 Post-audit movement (same day)

The branch advanced during/after this audit; recorded so later phases do not
trust stale statements:

| Commit | What it changed for this audit |
|---|---|
| `f438f4aa` (native coupled) | Committed the native-coupled session's WIP (BookSim/Ramulator-coupled DAG execution). §7 attributions for `native_hbm2_config.json` tests refer to this session's files. |
| `4977f32d` (fault profile) | **Phase-4-territory work landed**: `FaultProfile` with authored request/response drops, a real response deadline and bounded in-flight retries inside `data_movement.py`, plus `tests/test_data_movement_faults.py`. §2.3's "no fault model exists" was true at `0c78f27b` and is now **partially superseded**: timeout + bounded retry + first-response-wins exist for the abstract data-movement envelope; link recovery, cancellation states, fault injection into other subsystems and per-type timeout policies do not. |
| `4467a8f8` (rank alignment) | The fault session bound its event ranks to the Phase-1 kernel contract before this kernel was wired in: `data_movement.TIMEOUT_PRIORITY = EventPriority.TIMEOUT (3)`, `RETRY_PRIORITY = EventPriority.RETRY (5)`, asserted by `tests/test_data_movement_faults.py::test_fault_event_ranks_match_the_reserved_kernel_contract` against `application/execution_kernel.py`. The concurrent sessions and this one are coordinating on the shared kernel rather than forking ordering rules. |
- Test environment: Python 3.14.4, pytest 9.0.3, run from
  `tracks/t3-topology/dse`.

---

## 1. The canonical execution path (what actually runs)

There is exactly **one reference execution engine**, and it is a strict
extension chain:

```text
FabricCompiler().compile(CompileRequestV5)
        -> Compilation (status COMPILED, compiled_system)
        -> execute_data_movement(compilation, workload, placement, _runtime=None)   # application/data_movement.py
              event heap: heapq of (Fraction time, priority, serial, payload)
              priorities: 0 = phase arrival / completion, 1 = issue / runtime dispatch
              resources: implicit `lane_free[key]` single-lane serialization
              keys: ("channel", cid) | ("interface", eid, dir) | ("crossing", id) | ("service", eid)
        -> execute_coupled_tensor(...) = execute_data_movement(..., _runtime=_ReferenceRuntime)   # application/coupled_tensor.py
              _runtime.bind(deps, push, wake, trackers, lane_free)
              adds: compute DAG, byte images, owner cache, epoch dedup, drain-reset
```

Key facts:

- **Time is exact** (`fractions.Fraction`), phase-zero clock edges via
  `edge_at_or_after`. Floating point is not the event authority.
- **Event ordering today:** tuple compare `(time, priority, serial)`; priority 0
  (completions/arrivals) precedes priority 1 (issue/dispatch) at equal time;
  `serial` (insertion order) breaks remaining ties. Documented in
  `data_movement.py` as "completions/phase arrivals before issue on
  simultaneous edges" and asserted by
  `test_coupled_tensor.py::test_all_same_time_completions_precede_canonical_resource_contenders`.
- **The runtime hook is private** (`_runtime` kwarg) and already provides:
  scheduled runtime events, horizon/cancellation of the loop, per-operation
  `ready()` gating, `service_cycles` override, commit/responded callbacks, and
  `finish()` evidence assembly. This is the extension point Phase 1 must
  formalize — not replace.
- **Refusals are the contract.** `data_movement.py` refuses (typed
  `UnsupportedSemantics`) multi-plane/adaptive/shared-wire routing, sideband
  execution, unresolved or non-GRAY crossings, FIFO width conversion, reorder
  windows, >10k children / >1M flits. Coupled evidence reports
  `power_sideband: NOT_EXECUTED`, `coherence: UNIQUE_OWNER_NO_PROTOCOL`,
  `retry: AUTHORED_POST_RETIREMENT_DEDUP_NO_TIMEOUT_LOSS_RECOVERY`.
- **Evidence is recomputed, not trusted:** `DataMovementEvidence.revalidate()`
  and `CoupledTensorEvidence.revalidate()` re-run the whole execution and
  compare bytes. Any timing/semantic change in Phase 1 invalidates stored
  evidence → behavior preservation is mandatory.

---

## 2. Capability-by-capability baseline

### 2.1 Multiplane and clock-domain crossing execution

| Item | Finding |
|---|---|
| Existing implementation | `model/multi_plane_vc.py` (structural class→subnet binding, Plane C/D independent VC spaces), `model/control_plane.py` (Plane C artifact, REQ/RSP/SNP VCs, `SROTA_PLANEC_XY`), `simulation/clocked_fifo.py` (exact two-clock FIFO with GRAY-pointer visibility), two-clock phases in `application/data_movement.py` |
| Real execution path | **BookSim multi-plane runs exist** (`backend/booksim_execution.py`, `tests/test_srota_plane_c.py::test_multi_plane_run_conserves_every_flit`). **Reference two-clock execution exists** but only single-plane: `test_data_movement_execution.py::test_two_clock_fifo_conserves_and_backpressures`. The two are NOT on one timeline. |
| Missing state/behavior | No runtime plane instances; no concurrent multi-plane reference execution; no shared-resource contention between planes; data_movement hard-refuses multi-plane routing (`deterministic single-plane P2P routing only`); no CDC mechanisms beyond GRAY async FIFO of equal flit width |
| Unsupported combinations (refused today) | multi-plane routing in reference execution; sideband; non-GRAY pointers; width-converting FIFO; endpoint clock ≠ network clock without a declared crossing |
| Reusable modules | `multi_plane_vc`, `control_plane`, `clocked_fifo`, `edge_at_or_after`, route-rule lookup in `data_movement.path()` |
| Required modifications | plane runtime instances + plane-aware resource keys on the shared timeline (Phase 2); keep `test_srota_plane_c` green |
| Test entry points | `tests/test_srota_plane_c.py` (11), `tests/test_clocked_fifo_reference.py` (7), `tests/test_data_movement_execution.py::test_two_clock_*`, `tests/test_domain_intent.py` (81) |
| Owner / completion definition | Phase 2 — passes when both planes execute concurrently on ONE run, shared contention measurable, FIFO accounting correct, per-plane flit conserved, missing CDC declared → refusal, single-plane results unchanged |

### 2.2 General memory and cache coherence

| Item | Finding |
|---|---|
| Existing implementation | `application/coupled_tensor.py` `_ReferenceRuntime`: byte images, per-target LRU owner cache with projection/commit cross-check, invalidation on foreign writes, snapshot reads, epoch dedup |
| Real execution path | Fully connected: `lower_tensor_demand` → `project_remote_tensor_demand` → `execute_data_movement(_runtime=...)`; commits mutate real byte images; READ results validated against expected bytes |
| Missing state/behavior | **Not a coherence protocol.** One owner per tensor (`owner cache requires one endpoint and address space per tensor`); no requester caches, no directory/sharer tracking, no MESI or transient states, no coherence messages on the network, no atomics, no MMIO. Evidence honestly labels `UNIQUE_OWNER_NO_PROTOCOL`. |
| Unsupported combinations | >1 owner per tensor; unsequenced overlapping writes (`unsequenced overlapping write requires completion ordering` refuses); non-OWNER_CACHE policies get BYPASS only |
| Reusable modules | `_ReferenceRuntime.commit/responded/service_cycles`, dedup key machinery, `OutstandingTracker`, `transaction_intent.py` policies |
| Required modifications | requester cache state, directory, protocol message transactions consuming shared resources, atomics, MMIO (Phase 3), all inside the existing scheduler |
| Test entry points | `tests/test_coupled_tensor.py` (39 tests, incl. retry/reset/owner-cache), `tests/test_transaction_intent.py` |
| Owner / completion definition | Phase 3 — a coherent workload executes on the connected system with validated byte values, no conflicting exclusive owners, correct dirty writeback, hostile interleavings |

### 2.3 Automatic fault recovery

| Item | Finding |
|---|---|
| Existing implementation | Authored `retry_of` ACCESS nodes with strict identity checks; runtime dedup keyed by `(target, epoch, original, initiator, kind, space, addr range, block)`; `DRAIN_RESET` advances epoch and clears dedup/cache; horizon stops the loop. **Post-audit (`4977f32d`/`4467a8f8`):** `FaultProfile` in `data_movement.py` — deterministic authored request/response drops, a response deadline armed at service completion, bounded physical attempts (<=16), superseded-attempt voiding, first-response-wins, seal-after-exhaustion; threaded through the coupled DAG via `execute_coupled_tensor(..., faults)`. |
| Real execution path | Retry executes as a real second issue through the same engine; `test_retry_write_does_not_mutate_twice`, `test_invalid_retry_refuses_before_issue` prove dedup and refusal; `tests/test_data_movement_faults.py` (16 tests) proves drop/timeout/exhaustion/supersession semantics including commit-exactly-once under response loss. |
| Missing state/behavior | **No automatic recovery.** No fault model (packet loss, link down/restored, timeout, response loss), no timeout policy, no fault controller injecting events, no cancellation lifecycle, no link recovery/reroute, retry must be authored in the workload DAG (`AUTHORED_POST_RETIREMENT_DEDUP_NO_TIMEOUT_LOSS_RECOVERY`) |
| Reusable modules | epoch/dedup, `push/wake` scheduling, `OutstandingTracker`, refusal taxonomy |
| Required modifications | fault-event injection into the heap, timeout scheduling per transaction type, destination duplicate suppression as a first-class subsystem, cancellation states (Phase 4) |
| Test entry points | retry/reset subset of `tests/test_coupled_tensor.py`; no dedicated fault test file exists yet |
| Owner / completion definition | Phase 4 — lost response after a committed write → timeout fires → automatic retry → no duplicate commit → credits balanced; exhausted retries produce terminal failure |

### 2.4 Dynamic placement and memory migration

| Item | Finding |
|---|---|
| Existing implementation | `model/physical_placement.py` (`PhysicalPlacement`: authored non-overlapping router footprints, Manhattan wires — geometry only, validated against resource graph); `model/placement.py` (parallelism shapes/agent instances); tensor demand shards carry `target` + `address_space`; address selection is being built concurrently in `model/address_decode.py` **by another session** |
| Real execution path | Placement affects only `routed_flit_um` geometry; `test_placement_changes_geometry_not_network_or_clock_timing` proves it does NOT affect execution |
| Missing state/behavior | No `placement_epoch`, no migration lifecycle (PREPARE→…→COMPLETE), no layout transforms, no multi-target selection policy, no data transfer between memory targets, no concurrent-access-during-migration rules |
| Unsupported combinations | everything: migration simply does not exist; nothing to refuse yet |
| Required modifications | placement/migration state artifact, migration as a scheduled transaction consuming network+memory resources, consistency policy (Phase 5). **Constraint: consume the other session's address resolver; do not fork an address authority.** |
| Test entry points | `tests/test_placement.py` (21), `tests/test_data_movement_execution.py` placement tests |
| Owner / completion definition | Phase 5 — tensor migrates between two memory targets while traffic is active; final bytes, new epoch, changed network utilization, failure-safe under injected fault |

### 2.5 Executable IP catalog

| Item | Finding |
|---|---|
| Existing implementation | `model/ip_catalog.py`: 12 templates, capability requirements per template, `stamp_ip_template()` |
| Real execution path | **Only `hbm3e-memory` materializes**: a stamped canonical HBM_CONTROLLER agent group + address range + access rule compiled into `CompileRequestV5.base_v4`, then executed by the normal compiler path. All 12 templates report `stampable_now=False` from the requirement table; the other 11 raise `UnsupportedSemantics` naming unmet requirements. |
| Missing state/behavior | Instance identity fields (`ip_instance_id`, template/version binding) are **not in HEAD** — they exist only in the concurrent session's uncommitted `compile_model.py`/`ip_catalog.py` work (the intent-ontology gate failures prove this). No executable primitives (async FIFO/router/SRAM/memory-controller as instances), no capability-state ladder (DECLARED→…→NATIVE_EXECUTABLE) beyond the registry's coarse capability rows, no instance→compiler resource wiring beyond the hbm3e agent |
| Required modules | `ip_catalog.py`, `compile_model.py` (Agent fields), `fabric_compiler.py` |
| Required modifications | Phase 6 — but **coordinate the `Agent.ip_template_id`/`ip_instance_id` contract with the address-selection/IP session first**; do not duplicate it |
| Test entry points | `tests/test_ip_catalog.py` (40 tests incl. stamp refusal tests) |
| Owner / completion definition | Phase 6 — catalog template → instance → compiler → verified resources → executed transactions → evidence for ≥4 primitives; remaining templates report truthful status |

### 2.6 Power management and sideband execution

| Item | Finding |
|---|---|
| Existing implementation | `model/domain_intent.py` (1178 lines): `PowerPolicy`, `PowerDomain` with `declared_states`, clocks/resets, `Crossing`/`CrossingMechanism`; `model/sideband.py` (499 lines): first-class sideband edges, CDC flagged-never-resolved; `model/control_plane.py` |
| Real execution path | **None.** `data_movement.py` refuses any declared sideband (`sideband execution is outside this experiment envelope`); coupled evidence hard-codes `power_sideband: NOT_EXECUTED`; `PowerDomain` is validated model data only; the only runtime reset is the global `DRAIN_RESET` node in the coupled runtime |
| Missing state/behavior | power state machine, quiescence policies, isolation, retention, per-reset-type effects, sideband signal execution (interrupt/wake/power-request/reset), wake latency, sleep-blocked transactions |
| Reusable modules | `domain_intent.py` declarations, `sideband.py` connection validation, coupled runtime reset/epoch machinery |
| Required modifications | Phase 7 — power/sideband events on the shared scheduler; explicit refusals for undeclared policies |
| Test entry points | `tests/test_sideband.py` (42), `tests/test_domain_intent.py` (81) — both model-level only |
| Owner / completion definition | Phase 7 — drain→isolate→sleep→interrupt-wake→restore→resume executes with a verifiable event trace |

---

## 3. Phase 1 foundation: what exists, what must be added

Existing substrate (must be built upon, not replaced):

| Requirement | Today |
|---|---|
| Deterministic event ordering | `(time, priority, serial)` — 2 hardcoded priorities, insertion-order ties. Needs a **named, documented priority scheme** with boundary semantics (response vs timeout vs cancellation at equal time). |
| Exact global time | Yes — `Fraction`, proven by `test_clock_parsing_exact.py` and FIFO oracle tests |
| Multiple clock domains | Data present (`clocks` map, per-endpoint `transaction_clock_domain`); scheduling per-endpoint issue edges — but only one network clock in a run |
| Resource ownership | Implicit `lane_free[key] = free_at` single-lane FIFO serialization; no capacity>1, no occupancy/queue introspection, no double-allocation guard object |
| Shared-resource arbitration | First-come-by-construction (heap order); no arbitration policy abstraction |
| Event dependencies | Operation deps + runtime DAG gates (coupled only) |
| Transaction state | `record["state"]` strings inside coupled runtime (`REQUEST_INFLIGHT` → `MEMORY_QUEUED_OR_SERVICING` → `RESPONSE_INFLIGHT` → `RETIRED`) |
| Cancellation / timeouts | Horizon-based loop stop only; `_runtime.finished` breaks the loop. No per-transaction timeout. |
| Scheduled state transitions | Runtime events (`dispatch`, `compute_complete`, `reset_complete`) only |
| Transaction identity | `ChildTransaction(parent_id, sequence)` + hand-built dedup tuples. **No** `logical_transaction_id` / `attempt_id` / `execution_epoch` abstraction (epoch exists as an int in coupled runtime only) |

**Phase 1 design constraint (from observed evidence):** evidence artifacts
recompute whole executions and compare bytes; 217 focused tests assert exact
timestamps. Therefore Phase 1 must be a *pure refactor + additive layer*:
extract `lane_free` into a resource registry with **identical semantics**,
introduce identity/ordering objects that the current paths adopt without
changing any emitted timestamp.

---

## 4. Baseline test evidence (Phase 0.3)

Focused run (as mandated by the master prompt), from `tracks/t3-topology/dse`:

```bash
python -m pytest -q tests/test_coupled_tensor.py tests/test_data_movement_execution.py \
  tests/test_clocked_fifo_reference.py tests/test_srota_plane_c.py \
  tests/test_ip_catalog.py tests/test_rcu_reference.py
# 217 passed, 1 warning in 11.46s
```

Full CI gate (`bash scripts/ci_gate.sh`, run from repo root on the dirty
tree, 33m41s for the DSE suite):

```text
CI GATE: PASS=3 FAIL=2 SKIP=0
  product-gates: FAIL   (check_intent_ontology, check_capability_truth,
                         check_exposure_registry, check_python_deps)
  dse-pytest:    FAIL   26 failed, 7345 passed, 35 skipped
  studio-tsc:    PASS
  studio-vitest: PASS
  studio-pytest: PASS   10 passed, 8 skipped
```

Every one of the 26 dse-pytest failures was attributed by re-running the
failing files in a pristine `git worktree` at `0c78f27b` (`/tmp/veritx-head`):
see §7.

---

## 5. Definitions of completion (per capability)

Each phase exit condition is taken verbatim from the master prompt and bound
to a concrete owner here:

1. **Phase 1 (foundation):** existing coupled/compute/network/memory tests pass
   through the shared substrate with byte-identical evidence; resource
   registry, transaction identity and named event-ordering rules exist with
   positive/negative/mutation tests.
2. **Phase 2:** §2.1 completion definition.
3. **Phase 3:** §2.2 completion definition.
4. **Phase 4:** §2.3 completion definition.
5. **Phase 5:** §2.4 completion definition (address contract shared with the
   concurrent session).
6. **Phase 6:** §2.5 completion definition.
7. **Phase 7:** §2.6 completion definition.
8. **Phase 8–9:** one combined scenario (A–G) + closure report
   `docs/architecture/SYSTEM-EXECUTION-CLOSURE.md` with honest
   REFERENCE_EXECUTED / NATIVE_EXECUTED / NOT_QUALIFIED labels.
9. **Phase 10:** Studio surfaces only after backend evidence exists.

---

## 6. Reusable-module map (implementation owners)

- Scheduler/kernel: `application/data_movement.py` (heap, priorities, lane
  serialization, clocks) — Phase 1 owner.
- Runtime hooks: `application/coupled_tensor.py` (`_ReferenceRuntime`) —
  Phase 1 formalization, Phases 3/4/7 extension point.
- Credits/ordering: `model/transaction_intent.py` (`OutstandingTracker`).
- Exact clocks/FIFO: `simulation/clocked_fifo.py`.
- Multiplane structure: `model/multi_plane_vc.py`, `model/control_plane.py`.
- Clock/crossing/power declarations: `model/domain_intent.py`.
- Sideband edges: `model/sideband.py`.
- IP catalog: `model/ip_catalog.py` (coordinate with concurrent session).
- Geometry: `model/physical_placement.py`.
- Certificates: `verification/certificate.py`, `verification/system_certificate.py`.

---

## 7. Baseline CI gate results and known-broken attribution

`bash scripts/ci_gate.sh` at `0c78f27b` + dirty worktree: **PASS=3 FAIL=2**.

### 7.1 product-gates (4 failing sub-gates)

| Sub-gate | Attribution |
|---|---|
| `check_intent_ontology` (6 problems: `Agent.ip_template_id/version/ip_instance_id`, `AddressRange.target_instance_index/selection_policy/interleave_bytes`) | **Concurrent-session WIP** — these fields do not exist at HEAD (`git show HEAD:...compile_model.py` has zero matches). |
| `check_exposure_registry` (same 6 fields) | **Concurrent-session WIP** — same cause; passes in a pristine HEAD worktree. |
| `check_python_deps` (`gateway/app.py` starlette import) | **Pre-existing at HEAD** — the import is committed at HEAD (line 721; worktree line 746). |
| `check_capability_truth` (`concentrated_mesh.QUALIFIED` vs WITHDRAWN producer) | **Pre-existing at HEAD** — reproduces in a pristine HEAD worktree; `capabilities.py` has no worktree diff. |

Passing sub-gates: `check_capability_registry` (82 capabilities),
`check_preset_certification` (18 presets), `check_release_toolchain`.

### 7.2 dse-pytest — 26 failures, three causes

Attribution method: `git worktree add --detach /tmp/veritx-head 0c78f27b`,
then re-running the failing files there (20 of 26 reproduce; the other 6 are
worktree-environment artifacts: `test_booksim_producer_present`,
`test_astra_producer_present` and two `test_gateway_staleness` producer tests
require locally built binaries that a fresh checkout lacks, and two staleness
tests pass there).

| Cause | Count | Tests |
|---|---|---|
| **Pre-existing at HEAD** (fail in pristine worktree) | 16 | `test_capability_truth` (3), `test_lineage_residuals::test_reports_constants_come_from_core_constants` (1), `test_design_intent_identity` example round-trips for `local_island_*`, `multicast_tree_v1`, `rcu_reference_v1` (12) |
| **Concurrent-session WIP** (pass at pristine HEAD) | 8 | `test_capability_gaps::test_untagged_backlog_is_bounded_and_reported` (a scanned source phrase disappeared from WIP edits: 18 vs 19), `test_design_intent_identity::field_coverage_sentinel[Agent|AddressRange]` (2, WIP fields), `test_design_intent_identity[*native_hbm2_config.json]` (3, native session's untracked example), `test_product_registry_gates::test_exposure_registry_is_valid` (1), `test_memory_lowering::TestDesign::test_multi_hbm_refused` (1) |
| **Tree flux during the 34-min run** (a source file was written mid-run; the tests say so themselves: "a failure here means tree flux, not product rot") | 2 | `test_env_gates::test_staleness_gate_reports_fresh_on_stable_tree`, `test_gateway_staleness::test_a_fresh_process_is_not_stale` — both pass in the pristine worktree |

None of the 26 failures is caused by Phase 0/1 work (Phase 0 added only this
document; the kernel module added later is imported by nothing until Phase 1
wiring lands, and is re-verified by §4's focused run plus the full suite).

**Implication for later phases:** the Phase 9 gate cannot reach exit status 0
until (a) the concurrent sessions land their registry/backlog rows, and (b)
owners address the pre-existing HEAD failures (capability truth, lineage
residuals, example round-trips, starlette dependency declaration). Phase 0/1
must not "fix" any of these by editing another session's registry, capability
claims or examples — the honest Phase 9 report must separate
pre-existing/concurrent failures from regressions introduced by closure work.

---

## 8. Explicit non-goals of this baseline

- No UI/Studio inspection (Phase 10 is out of scope until backends verify).
- No claims about native qualification: BookSim/Ramulator/RTL evidence is
  tracked separately and is not inferred from reference execution.
- No modification of pinned third-party code, existing certificates, or the
  concurrent sessions' uncommitted files.
