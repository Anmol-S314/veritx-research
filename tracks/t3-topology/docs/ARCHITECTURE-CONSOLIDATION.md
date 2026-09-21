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
| 2b | Dissolve `waved/` + **dependency inversion** (not a rename) | **DONE** | see §Slice 2b | corpus 69/69 identical; DAG guards |
| 2c | Make the Wave-D graph the ONE canonical workload (fold `workload/canonical.py`) | pending | — | — |
| 3 | Promote Wave E into `performance/`, retire `workload/timeline.py` | pending | — | — |
| 4 | Collapse application glue (`waved_resources` + `wave_e_resources` → one codec table; `_wave_e_*` dict transport → typed outcome) | pending | — | — |
| 5 | Reclaim TopologyIR/deadlock, Ramulator, model-shape lowering, Timeloop/energy | pending | — | — |
| 6 | Serving fidelity (LLMServingSim semantics → WorkloadGraph) | pending | — | — |

### Slice 2b: three seams, not one (superseded — kept for the record)

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

---

# Slice 2b — dependency inversion and package dissolution

**Commit(s):** `Error taxonomy` + `Slice 2b` (see §Commit map).
**Objective:** dissolve `veritx_dse/waved/` into semantic domains **and** fix the
dependency direction, not merely rename a directory.

## Before -> after file map

| before | after | change |
|---|---|---|
| `waved/oracles.py` | `verification/reference_semantics.py` | all `ref_*` stay; +3 verifiers moved OUT of the artifacts |
| `waved/parallelism.py` | `model/parallelism.py` | `cross_check_against_oracle()` removed from the artifact |
| `waved/semantics.py` | `workload/semantics.py` | import updates |
| `waved/operations.py` | `workload/operations.py` | import updates |
| `waved/messages.py` | `workload/messages.py` | uses `workload/collectives.py`; `validate_against_oracle` -> `validate_conservation` |
| `waved/traffic.py` | `workload/traffic.py` | `cross_check_against_oracle()` removed; imports `model.resolved_bundle` |
| `waved/workload.py` | `workload/graph.py` | ownership only (slice 2c does the canonical merge) |
| `waved/backend.py` | `backend/projection.py` + `verification/gates.py` | split BY RESPONSIBILITY |
| `backend/bundle.py` | `model/resolved_bundle.py` | `ResolvedFabricBundle` is model composition, not backend science |
| `waved/errors.py` | `core/errors.py` | domain refusals into the one hierarchy |
| `waved/__init__.py` | — | deleted with the package |
| — | `workload/collectives.py` | NEW: the production collective algorithm spec |
| — | `verification/gates.py` | NEW: pre-spawn + post-drain gates |

## Deleted rather than moved

```
waved/__init__.py    the package boundary itself; no compatibility layer kept
waved/errors.py      contents MERGED into core/errors.py (not a copy):
                     Refusal base, ArtifactError, InvalidInput, EvidenceInvalid,
                     UnsupportedSemantics, UnsupportedSchedule, MappingInvalid,
                     ConservationFailed, BackendFailure, BackendTimeout
                     (WavedTimeout renamed; WaveDError deleted: nothing caught it)
```

No function was deleted as dead: every function in `waved/backend.py` had a
real caller and was classified:

```
render_waved_trace          -> backend/projection.py   (renders the grammar)
verify_trace_projection     -> backend/projection.py   (needs the renderer +
                                                        scanner; verification
                                                        must not import backend)
assert_projection_ready     -> backend/projection.py   (pre-spawn chain)
prepare_waved_booksim       -> backend/projection.py
run_waved_booksim           -> backend/projection.py
assert_workload_ready       -> verification/gates.py   (artifact-only gates)
verify_backend_quiescence   -> verification/gates.py   (sealed counters only)
```

## Final dependency DAG (verified by AST guard)

```
core        imports nothing from model/workload/verification/backend/application
model       imports core only
workload    imports core + model only
verification imports core + model + workload only  (never backend/application)
backend     imports core + model + workload + verification gates
application orchestrates everything
```

Five **pre-existing** `core -> domain` edges remain (legacy research stack):
`comparison->workload.serve`, `doctor->model`, `experiment->model.presets`,
`experiment_serving->workload.serve`, `spec->model.presets`. They are encoded
as an exact-equality allowlist in `tests/test_architecture_law.py`, so a new
upward import fails AND a silently fixed one fails (the list must stay
truthful). Resolving them belongs to slice 5.

## Remaining wave vocabulary, classified

**(a) Persisted schema vocabulary — MUST NOT change without a migration
reader** (a JSON body on disk or in a resource id):

```
"wave_d", "wave_e"            intent/plan/result body keys
waved_resources, wavedworkload, waved_parallelism, wavedsemantics,
wavedoperationgraph, wavedmessages, wavedtraffic   resource kinds
WAVED_WORKLOAD_SCHEMA_VERSION, WAVED_RESOURCE_KINDS, WAVED_OPERATION_KINDS
WAVED_TRACE_DIALECT = "waved-derived-whitespace-v1"   in projection summaries
waved_workload_record, waved_workload_id, waved_semantics_record, waved_links,
waved_chain_ids, waved_execution_block                persisted record keys
```

**(b) Temporary Python symbols, pending slice 2c/3** (not persisted, but a
rename now would collide with the canonical-workload and performance slices):

```
classes   WaveDWorkload, WaveDOperation, WaveDWorkloadSemantics,
          WaveETemporalWorkload, WaveETemporalEvent, WaveEPerformanceModel,
          WaveEEventGraph, WaveERequest
functions render_waved_trace, prepare_waved_booksim, run_waved_booksim
modules   application/waved_resources.py, application/wave_e_resources.py,
          the wavee/ package (slice 3)
```

**(c) Defects (recorded, slice 4 owns them):** `service.py` transports LIVE
objects through `extra["_wave_e_evidence" | "_wave_e_traffic" |
"_wave_e_summary"]` — an in-memory private channel, not persisted, but the
exact "found at 2 AM" pattern. Slice 4 replaces it with a typed outcome.

## Behaviour equivalence (the point of the slice)

A 69-entry corpus was captured from the pre-move tree and recomputed after
the move with the same script (import-shimmed, so both runs are comparable):

```
parallelism ids, to_dict, groups, group_of    semantics, op graphs, graph ids
logical message + schedule ids                packetization, flitization
physical traffic id + to_dict digest          conservation ledgers, totals
rendered trace sha256 + bytes + first lines   projection summary digest
prepared BookSim config/input hashes

entries 69/69; differing values 0; symmetry 0
```

Now pinned as `tests/test_domain_corpus_identity.py`
(corpus sha256 `8d8f2fa7…a938eb`), so slices 2c/3/4 fail loudly if an identity
moves without an argued schema bump.

### The corpus earned its keep immediately

It caught two real mistakes that would otherwise have shipped:

1. Removing `cross_check_against_oracle` from `traffic.py` cut **87 extra
   lines** — `identity_dict`, `physical_traffic_id`, `to_dict`, `from_dict`.
   The persistence/identity surface of the artifact was gone; the corpus
   failed on the first entry that touched it.
2. The new `verify_logical_messages_reference` asserted `distinct (src,dst)
   pairs == message_count`, which is false for a k=2 ring (2 pairs, 4
   messages). Fixed to compare message COUNT (confirmatory) while the BYTE
   total stays the differential.

## New findings

**F5 — the artifact carried its own differential.** `ParallelismArtifact`
and `PhysicalTrafficArtifact` each owned a `cross_check_against_oracle()`
method that called the reference module. An artifact that verifies itself
against a reference is a layering inversion *and* a trust inversion: three
production call sites (verified loader, service, pre-spawn gate) ran the
check from inside the thing being checked. Both moved to
`verification/reference_semantics.py`.

**F6 — `waved/backend.py` had two owners in one file.** Rendering/preparation
(backend) and gates (verification) were interleaved. Split by responsibility;
`verification/gates.py` now imports **no backend module**, which is why the
trace-projection differential lives with the renderer that owns the grammar
instead of in `verification/`.

**F7 — `PhysicalTrafficArtifact` imported `backend.bundle`.** The hidden
`workload -> backend` edge. `ResolvedFabricBundle` is model composition
(topology, mapping, attachment, routes, VC, packet format, router behaviour,
address decode, fabric), so it moved to `model/resolved_bundle.py`.
Validation semantics and hashes unchanged (frozen Wave-B battery: 838 passed).

**F8 — `ref_collective` was serving two jobs.** It was the production ring
spec *and* the independent reference. Split: `workload/collectives.py` is the
production spec (`collective_schedule`), `verification/reference_semantics.py`
keeps its own equations. `messages.validate_against_oracle` is renamed
`validate_conservation` because it proves generated == declared schedule
(an intrinsic invariant); the independent differential is now
`verify_logical_messages_reference`. Per F2 the message COUNT remains
confirmatory — the BYTE total is the differential — and the docstrings say so.

## Battery (from the committed tree)

```
architecture law            9 passed
domain corpus identity      1 passed
artifact primitives        33 passed
wave-D                     249 passed
wave-E + control-plane      390 passed (1 known dirty-tree reuse test)
frozen wave-B              838 passed
goldens                      6 passed
broad DSE suite    27 failed / 3195 passed / 41 skipped
                   failed-node set IDENTICAL to the 0bfa5c88 baseline
```
