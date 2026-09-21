# Architecture Consolidation Ledger

**Goal:** one product pipeline (Intent → Resolved design/FabricArtifact →
WorkloadGraph → LogicalTraffic → PhysicalTraffic → backend input →
EvidenceBundle → SystemTimeline → Result/Comparison), with directories that
describe what the code does rather than what month it was written in.

**Rule for every slice:** strictly behaviour-preserving. Where an identity
must move, compare semantic outputs, traffic, evidence and schedules — never
old hashes.

**Base:** `577feeb2` (capability reclamation pass). Wave E was sealed at
`d878cf5e`; nothing here reopens it.

---

## Slice ledger

| # | Slice | Status | Commit | Evidence |
|---|---|---|---|---|
| 1 | One artifact primitive (canonical serialization, content identity, immutability, strict parsing) | **DONE** | `62ff9959` | 32 primitive tests; sealed artifact identity pinned |
| 1b | One dimension law (ParallelismArtifact delegates to the sealed rank algebra) | **DONE** | `62ff9959` | parametrized agreement test |
| 2a | Restore oracle independence for group derivation | **DONE** | `684b856b` | reverse probe + 2 guard tests |
| 2b | Dissolve `waved/` into `model/`, `workload/`, `verification/`, `backend/` | **BLOCKED** (see below) | — | — |
| 2c | Make the Wave-D graph the ONE canonical workload (fold `workload/canonical.py`) | pending | — | — |
| 3 | Promote Wave E into `performance/`, retire `workload/timeline.py` | pending | — | — |
| 4 | Collapse application glue (`waved_resources` + `wave_e_resources` → one codec table; `_wave_e_*` dict transport → typed outcome) | pending | — | — |
| 5 | Reclaim TopologyIR/deadlock, Ramulator, model-shape lowering, Timeloop/energy | pending | — | — |
| 6 | Serving fidelity (LLMServingSim semantics → WorkloadGraph) | pending | — | — |

### Why 2b is blocked (a real dependency, not a preference)

`waved/parallelism.py` calls `ref_coords` inside
`cross_check_against_oracle()`, which is called at runtime by the verified
loader, the service and the backend projection. Moving the artifact to
`model/parallelism.py` would create a `model → verification` import.

The fix is a design decision, not a move: the cross-check is a *verifier*, so
it belongs in `verification/` (the user's target tree already has
`verification/reference_semantics.py` for exactly this). Move
`cross_check_against_oracle` out of the artifact, and `model/parallelism.py`
becomes dependency-clean. Do it in the same slice as the oracle relocation,
so the file moves once.

---

## Findings (found while consolidating)

### F1 — the group-law "independent oracle" test could not fail (FIXED)

`ParallelismArtifact.groups()` derived members by calling the oracle's
`ref_rank`; `group_of()` called `ref_group_members`; the test compared
`group_of().members` against `ref_group_members(...)`. Same function, same
arguments, both sides.

Proven by probe: with the oracle patched to return a constant on both sides,
the test still passed. It verified nothing.

Fixed in `684b856b`: derivation is production-side (`self.rank_of` via the
sealed Wave-B algebra), `group_of` looks the rank up in the one derivation,
and the oracle import is confined to the verifier. Outputs unchanged (0
mismatches across shapes).

This is the "trusted relationship that is never re-derived" class, one layer
down — there the relationship was `oracle == oracle`.

### F2 — `messages.validate_against_oracle()` is a MIXED case (NOT fixed, by design)

`_expand_collective()` reads `ref_collective(...)["steps"]` to build the ring
schedule, so the step/message count is *defined by* the oracle and the
count check is confirmatory. The BYTE check is a genuine differential (it
sums generated message bytes against the oracle's aggregate).

That is defensible — the oracle is the pinned algorithm spec (`§10.2`), and
one authority for "ring allreduce takes k−1 steps" is better than two. What
is not accurate is the *test name*: it is a spec conformance check, not an
independent second implementation. Recorded rather than renamed, because
renaming Wave-D evidence vocabulary is a Wave-D decision and this slice must
not touch conservation/oracle machinery.

### F3 — genuine verifiers, confirmed (not tautological)

```
traffic.cross_check_against_oracle()   re-derives packetization/flitization
                                       from the oracle and compares against
                                       separately generated traffic   GENUINE
parallelism.cross_check_against_oracle compares placement's coords_of with
                                       the oracle's ref_coords — two
                                       implementations of the inverse GENUINE
```

### F4 — the rank oracle guards drift, not misreading (scope statement)

`ref_rank` and `model.placement.rank_of` are the same closed form
(`((p·dp+d)·ep+e)·tp+t`), verified on 73 rank-space points over 6 shapes.
Comparing them catches implementation drift (a typo in one), not a
misunderstanding of rank order. That is the honest scope of a closed-form
reference, and the oracle docstring says as much.

### Deliberately NOT unified

`core/route_artifact.py::_freeze` (sorted tuple-of-pairs) and
`backend/contracts.py::_freeze_json` (path-aware frozen map with
absolute-path refusal) are two more immutability implementations. Both are
sealed Wave-B code, both feed content hashes, and both enforce different
validation policies — merging them would move sealed hashes for a naming
preference. Recorded for a later, deliberate Wave-B change.

---

## What the target tree needs that does not exist yet

```
core/artifact.py      EXISTS (slice 1)
core/time.py          wavee/time.py must move here      (slice 3)
model/parallelism.py  blocked on 2b
workload/graph.py     wavee? no: waved/workload.py + workload/canonical.py  (2c)
workload/traffic.py   waved/traffic.py                  (2b)
performance/*         wavee/*                           (3)
verification/reference_semantics.py  waved/oracles.py    (2b)
backend/ramulator.py  simulation/ramulator.py            (5)
backend/timeloop.py   scripts/timeloop_*                 (5)
backend/astra.py      simulation/astrasim_adapter.py     (5)
```

No compatibility layers: old persisted resources get migration readers, but
new writes use the canonical schemas immediately.

---

## Battery after slices 1 + 2a

```
artifact primitives                     32 passed
wave-D                                  249 passed
wave-D + wave-E + control-plane         670 passed  (1 known dirty-tree reuse test)
frozen wave-B chain                     747 passed
goldens                                   6 passed
broad DSE suite    27 failed / 3184 passed / 41 skipped
                   failed-node set IDENTICAL to the pre-Wave-D baseline
```
