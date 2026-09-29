# Compute/memory intent — decision and plan

Status: **v1 LANDED** (2026-09-29) — declared compute stages, lowered into the
canonical WorkloadGraph; `DRAM_TIMING` flips `BLOCKED → READY` when a workload
declares memory demand. Prototyped and verified in a temporary worktree, then
integrated. See `docs/decisions/modules/model.md` / `workload.md` for the
code-level rationale that was extracted.

## What landed

- `model/compute_intent.py`: `ComputeIntent` / `ComputeStage` — declared
  `duration_ns`, `input/weight/output_bytes`, `owner`, `LOCAL` locations.
- `model/compile_request_v4.py`: `CompileRequestV4.compute`, identity-bearing
  **only when non-empty** (a v4 document without compute keeps its hash).
- `workload/intent_lowering.py`: declared stages lower to chained COMPUTE
  operations (declared order = dependency order); a compute-only workload is
  now lowerable; an empty workload still refuses.
- `docs/product/exposure-registry.yaml`: the `CompileRequestV4.compute` row.
- Tests: `tests/test_v4_compute_intent.py` (11).

## What is still NOT done

- No Studio editor for compute stages yet (the intent is authorable only
  programmatically / by a future UI). The Operations tab already *displays*
  COMPUTE ops and the memory-demand rollup.
- v1 does not interleave compute with communication: the declared compute
  phase precedes the collective schedule (a stated assumption).
- Multi-HBM / sharding still refuses (memory lowering v1 is single-pool).

---

## The gap (original analysis)

Compute is **NOT MODELED** and Ramulator is **unreachable from the product**,
because the workload grammar (v3) can only declare communication:

```
workload: { model_family, model_name, tp/pp/ep/dp, serving_mode, collectives }
```

`lower_compile_workload` therefore emits only COLLECTIVE operations. The
`WorkloadGraph` supports COMPUTE ops with `input_bytes / weight_bytes /
output_bytes / *_loc`, but nothing authors them. Consequences:

- every catalog workload lowers to collectives-only → zero memory demand →
  `DRAM_TIMING` refuses ("no resolvable memory demand");
- compute time is explicitly absent, so **SYSTEM_MAKESPAN mixes communication
  with no card compute** — an honest caveat, but a large one;
- Ramulator, and any future compute authority, cannot be exercised.

The WorkloadGraph inspector (`lowering_view.operations` + `memory_demand`,
added 2026-09-29) now makes this visible in Studio: the Qwen workload shows
`compute_count: 0, has_memory_demand: false`.

## Why NOT do it now

1. **A second writer is already in this area.** `workload/memory_lowering.py`
   (`_issue_nodes_for` owner-derivation) and `tests/test_memory_graph.py`
   changed on 2026-09-29, and the working notes reference "the new v4
   compute/memory intent once it lands". Building it in parallel produces a
   second, half-wired path — the exact dual-truth disease this repo is trying
   to cure.
2. **The tree is red** (25 pre-existing failures). Adding a schema version on
   a red tree makes regressions indistinguishable from existing breakage.
3. It is a **schema migration**, not a feature flag: v4 identity, migration
   from v3, and every consumer of the lowered graph must agree.

## The slice (when a single writer owns it)

Ordered, each step verifiable on its own:

1. **Schema.** Add a compute/memory intent to `CompileRequestV4` (or a typed
   `SystemIntentV4` sub-object): a list of compute stages with
   `duration_ns`, `input_bytes`, `weight_bytes`, `output_bytes`, and locations
   (`LOCAL` only in v1). It must be *declared*, never inferred — the same law
   as `ep_combine`.
2. **Migration.** `migrate_v3_to_v4` maps a v3 request to a v4 request with an
   **empty** compute list (no invented bytes); v3 identity stays frozen.
3. **Lowering.** `lower_compile_workload` emits COMPUTE `OperationNode`s with
   a unique dependency chain (independent ops refuse — region order would be
   ambiguous) and an explicit `owner` per op when `participant_count > 1`.
   Communication ops keep their current lowering; ordering between compute and
   collectives must be declared, not guessed.
4. **Readiness.** `evaluation_plan` marks `DRAM_TIMING` READY only when
   memory demand exists; the reason stays typed.
5. **View.** `lowering_view.memory_demand` becomes non-zero; the Studio
   Operations tab and the Evaluate Memory card both reflect it with no new UI
   contract.
6. **Tests.** Identity/migration freeze tests, a real Ramulator drain on a
   declared compute workload, and a refusal test for a compute op with no
   owner among many.

## Law to preserve

- Compute is never *assumed*: absent intent means absent demand, and the
  evaluator must keep saying so. Do not default `duration_ns` or operand bytes
  to make a backend run.
- The v3 identity stays byte-for-byte frozen; v4 is a new generation with its
  own golden.
- One lowering authority: COMPUTE ops come from the declared intent via the
  canonical lowerer, never from a parallel path in the adapter.
