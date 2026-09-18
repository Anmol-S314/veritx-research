# HANDOFF — Phase 14: Canonical Memory Semantics (14a schema + 14b resolver)

**Date:** 2026-09-18 · **Branch:** `epic/booksim-forward-port`
**Prior gate:** Phase 13 fabric compiler handoff (`069d6eeb`, same day) —
the MEMORY-ROADMAP gating condition (no memory program before Phase-13
gate) is satisfied; Phase 13 landed before 14a started.
**Spec:** `tracks/t3-topology/docs/MEMORY-ROADMAP.md` (§2 quarantine landed
earlier; Appendix D backend spike retired the Ramulator risk).

## What landed

### 14a — `veritx_dse/core/memory.py` (MemoryArtifact v1)

Content-addressed, backend-independent resolved memory semantics, following
the Phase-9/10 artifact pattern (frozen dataclasses, eager builders,
`_sha256_of` canonical JSON, tamper-evident `from_dict`):

- `MemoryRegion` (id/type/size/base/placement/alignment/source-op),
  `MemoryAccess` (logical offset+size, READ/WRITE, source node, dependency
  order — **no ready cycles, no channel/bank/row/col fields**),
  `MemoryPlacement` (tier ∈ {HBM, SCRATCHPAD}, device, stack|None),
  `AddressMappingPolicy` (registry: `contiguous_aligned_v1` only).
- Triple hash: `region_table_hash` (sorted) + `access_stream_hash`
  (**artifact order preserved** — stream order is execution semantics) +
  `artifact_hash`; display `name` roundtrips, never hashes.
- Fail-closed: positive sizes, PoT alignment + base alignment, 64-bit
  overflow, overlap refused within a placement scope (allowed across
  scopes — different physical memories), access bounds/node/dangling-dep/
  dep-cycle checks, `source_workload_hash` must be `sha256:`-linked.
- `allocate_regions`: deterministic per-scope allocation (sort by
  region_id, align cursor); any input order → identical bases.

### 14b — `veritx_dse/workload/memory_lowering.py` (resolver)

`resolve_memory(workload, design) → ResolvedMemory` (+ conservation audit):

- Fixed operand mapping (input→ACTIVATION, weight→WEIGHT, output→OUTPUT —
  no inference); one region per (op, operand) — **op-scoped, cross-op
  tensor persistence explicitly not modeled** (assumption-recorded).
- Strict locations: only LOCAL resolves to the single-HBM pool;
  REMOTE/CXL/STORAGE → `UnsupportedSemantic` (reuses lowering.py's error
  family); multi-HBM designs refuse (sharding policy is future work).
- Explicit execution attribution (`issue_node`: int / per-op map / None
  only when unambiguous); ambiguous → `LoweringError`.
- Positional chaining (ET-lowering precedent): reads → write deps per op,
  each op chained after the previous tail. Conservation asserted in code
  (operands == regions == accesses) plus returned audit.
- Zero/None operands skipped; comm ops and markers ignored (fabric, not
  memory demand).

## Tests (75 new, all green)

- `tests/test_memory_artifact.py` (51): schema/link/placement/policy/
  allocation/region/access validation, all hash behaviors + 4 tamper
  cases, workload-conservation fixture (14,592B via real workload hash).
- `tests/test_memory_lowering.py` (24): happy path, order+deps, strict
  locations (incl. atomic refusal), attribution matrix, design refusals,
  determinism + order-is-identity, roundtrip, **real Path-B serving-row
  workload resolving conserved** (10,240B, collective correctly excluded).

## Live evidence

- Full suite: **1291 passed, 1 skipped, 0 failures** (1292 collected =
  1292 executed); `make -C tracks/t3-topology lint` rc=0.
- One honest footnote: an earlier full run this session showed 1261 items
  with no failures; the rerun shows the full 1268 with no failures and
  counts reconcile exactly. Transient collection artifact, no failures in
  any run — recorded rather than smoothed over.

## Known residuals / deferred (NOT in 14)

- Resolver versions itself into `assumptions[0]` (`resolver:.../1`); no
  separate resolver-version identity field (sufficient for v1).
- `SCRATCHPAD` tier exists in schema but the resolver never emits it
  (residency claims need reuse semantics — future hierarchy work).
- `LOCAL:<dev>` with dev ≠ pool refuses (cross-device local is remote
  access mislabeled).
- No CLI surface, no Ramulator lowering, no MemoryLoweringManifest (Phase
  15a per the agreed sequence: 15a addr_vec lowering → 15b standalone
  execution/drain contract → thin CLI last).

## Decisions locked (do not relitigate without new evidence)

1. Canonical artifact carries logical byte addresses only; Ramulator
   addr_vec mapping is the Phase-15 lowerer's job (spike-proven).
2. No ready-cycle timing anywhere in v1 (sources don't supply it).
3. REMOTE/CXL/STORAGE never silently remap to HBM.
4. Overlap refusal is per placement scope, not global.

## Next permitted phase

Phase 15a: `MemoryArtifact → Ramulator addr_vec` lowering + manifest
(bytes→addr_vec mapping, transaction expansion, conservation), reusing the
spike's proven boundary (ReadWriteTrace, HBM3_16Gb_8hi, drain-aware
counting per Appendix D caveats). Then 15b, then thin CLI. Pinned
Ramulator vendoring happens at 15a start (spike clone was `/tmp`, not
vendored).
