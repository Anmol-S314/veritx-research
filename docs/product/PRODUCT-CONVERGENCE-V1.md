# PRODUCT-CONVERGENCE-V1 — convergence ledger

Branch: `product/convergence-v1`
Base: `origin/rebuild/live-product-flow @ 2e51311d`
Worktree: `/home/datavex/veritx-product-convergence`

This ledger records what the original convergence brief asked for, what the
three predecessor commits **already satisfy**, and what is genuinely left.
Requirements are classified as:

| class | meaning |
|---|---|
| `ALREADY_PRESENT — VERIFY` | the behaviour exists; the work is to prove it, not to build it |
| `EXTEND` | a predecessor commit established the authority; acceptance criteria are still unmet |
| `FIX` | a confirmed defect |
| `NEW` | nothing exists yet |
| `DEFER` | out of scope for this slice, with a reason |

**Do not reimplement a predecessor commit because the brief was written
against the older GitHub head.** The brief's base (`b9e4de0d`) is the PARENT
of the three commits below; it does not contain them.

---

## Predecessor commits carried by this base

| SHA | Subject | Authority established |
|---|---|---|
| `c1f3d118` | `fix(product): split latest attempt from active revision` | `active_revision_id` vs `latest_attempt_revision_id`; `_revision_promotable()` — only a COMPILED revision with a PASS certificate may go active; a refused attempt is recorded but never displaces the last usable revision; `_ensure_revision_pointers()` backfills/repairs |
| `24f7813f` | `fix(product): refuse simulation honestly for unevaluable intents` | `_evaluation_support(revision) -> (bool, reason)` by attempting `lower_compile_workload`; `evaluation_supported` / `evaluation_note` on entries; `active_evaluation` on the project view; a submit gate raising `LOWERING_UNSUPPORTED`. Law: *"Compilation proves the fabric; only a successful intent lowering proves the workload can run on it."* |
| `2e51311d` | `feat(product): MoE declared-ops lowering, per-message classes, real capability reasons` | MoE declared-ops lowering; `LogicalMessageArtifactV3` per-message classes; real capability reasons; **the multi-class BookSim trace guard** in `render_trace` |

---

## Phase classification

| # | Brief requirement | Class | Evidence / notes |
|---|---|---|---|
| 1 | Every optimization option reaches `OptimizationDefinition` unchanged | **FIX** | `product/service.py:1039` `_parse_definition` returns `domain, objectives, constraints, method, selection, seed`. `product/service.py:1079` constructs `OptimizationDefinition(domain=…, objectives=…, constraints=…, method=…)` — **`selection`, `seed` and `budget` are dropped**. Backend has all three (`optimization/definition.py`: `budget`, `seed`, `selection`). |
| 1b | Expose `max_candidates` / `max_evaluations` | **NEW** | `_parse_definition` accepts no budget at all; `search.py:51` consumes `budget.get("max_candidates")` and `max_evaluations`. |
| 1c | Reject unsupported fields instead of dropping | **NEW** | no unknown-field check on the optimization body today. |
| 2 | Product capability API for Guided params | **NEW** | no such endpoint. Backend authority exists: `candidate.apply_patch` GUIDED keys, `definition.SEARCH_METHODS = ("grid","enumeration","random")`, `definition.SELECTION_POLICIES = ("min_first_objective","lexicographic","none")`. |
| 2b | Certified metrics derived from the real registry | **ALREADY_PRESENT — VERIFY** | `optimization/metric_registry.py`. Must be read, not restated. |
| 2c | LOCKED properties non-searchable | **ALREADY_PRESENT — VERIFY** | `candidate.apply_patch` accepts GUIDED keys only. |
| 3 | Rebuild the Optimize page as a decision workflow | **EXTEND** | `apps/studio/src/pages/optimize.tsx` + `components/OptimizeView.tsx` exist. |
| 4 | Result page leads with the decision, not hashes | **EXTEND** | depends on `24f7813f`'s `_evaluation_support` for "what VERITX did NOT measure". |
| 5 | Candidate comparison with human labels | **EXTEND** | candidate identity exists; human labelling does not. |
| 6 | LOCKED consequences rendered as consequences | **ALREADY_PRESENT — VERIFY** | canonical bundle views exist; must not be recomputed in React. |
| 7 | Selected candidate → Draft → explicit Compile → new revision | **EXTEND** | `c1f3d118` established revision immutability and promotability. What is missing is the Draft target and the `derived_from_optimization_id` / `derived_from_candidate_id` provenance. |
| 8 | Candidate evidence without pretending it is a Product Run | **ALREADY_PRESENT — VERIFY** | `product-run` vs `optimization-candidate` distinction is in the service model; the UX must not conflate them. |
| 9 | Study analysis incl. failed/unmeasurable counts | **EXTEND** | `24f7813f` supplies the unmeasurable axis; the study must surface the counts. |
| 10 | Single objective ⇒ "Measured ranking", never "Pareto" | **FIX** | UI rule; needs a pinned test. |
| 11 | CLI P0 defects A–G | **FIX** | see table below. |
| 12 | Documentation reset | **FIX** | path in the brief was wrong — see below. |
| — | **Hard gate:** optimisation/evaluation cannot collapse a multi-class workload to class 0 | **EXTEND** | The guard exists in `render_trace` and IS covered (`tests/test_workload_moe_lowering.py::test_v3_physical_projection_conserves_and_trace_refuses_classes`). Coverage does **not** yet reach the optimization/evaluation path. |

### Documentation path correction

The brief cited `docs/VERITX-CLI-AND-TUI-PLAN.md`. That path has never existed
in this repository. The file is at:

`tracks/t3-topology/dse/docs/VERITX-CLI-AND-TUI-PLAN.md`

### Phase 11 CLI defects — status to be confirmed per item

| item | defect | class |
|---|---|---|
| A | `veritx run` synthesizes `winner.anynet` but evaluates a freshly constructed mesh | FIX |
| B | `non-square nodes -> k=8` silent fallback | FIX |
| C | certification decided by `any("PASS" in stdout)` | FIX |
| D | `fail()` does not return non-zero | FIX |
| E | sweep reports `nodes=0` when the node count is known | FIX |
| F | failed/partial rows crash `results` | FIX |
| G | UVM requires an obsolete representation | FIX |

---

## Status board

| issue | evidence | fix | tests | status |
|---|---|---|---|---|
| P1 selection/seed/budget dropped | `product/service.py` `_run_optimization` constructed `OptimizationDefinition(domain, objectives, constraints, method)` only; `OptimizationStudyView._select` reads `definition.selection`, so `selection="none"` silently became `min_first_objective` | propagate `budget`, `seed`, `selection`; add `budget` to `OptimizeBodyV1` | `test_product_convergence_phase1.py` (12) | **DONE** |
| P1 budget not expressible | `_parse_definition` had no budget branch at all; backend `search.py` consumes `budget["max_candidates"]`/`["max_evaluations"]` | accept + validate `budget` object | same | **DONE** |
| P1 unknown options dropped | no unknown-key check; a misspelled option was ignored | `_OPTIMIZATION_KEYS` closed set; unknown ⇒ `INVALID_INTENT` naming the supported set | same | **DONE** |
| P1 requested definition not persisted | the optimization record stored only `study` + `candidate_runs`, so `method`/`selection`/`seed`/`budget` were unverifiable after the fact | persist `definition` (the normalized request) | same | **DONE** |
| P1 canonical domain order | `[32,64,128]` ⇒ `(128,32,64)` | **C**: added `capabilities.presentation_order()` — numeric display order, explicitly NOT part of the definition; identity/enumeration keep canonical order | `test_optimization_capabilities.py` (4 tests) | **DONE** |
| P2 capability API | no endpoint; Studio hard-codes `link_width ∈ {32,64,128}` | **B**: new `optimization/capabilities.py` + `GET /api/v1/optimization/capabilities`, derived from `GUIDED_PARAMS` / `SEARCH_METHODS` / `SELECTION_POLICIES` / `CERTIFIED_METRIC_REGISTRY` / the canonical materializer | `test_optimization_capabilities.py` (19 tests) | **DONE** |
| P2 per-value honesty (expressible ≠ executable) | — | `topology_family` values obtained by ASKING `_family_of` + `MaterializedFamily`: `[mesh, torus, concentrated_mesh]`; `gec`/`fat_tree` refused though they ARE enum members | same | **DONE** |
| P2 no invented PPA | — | certified metrics are exactly `completion_{cycles,time,ns}`; area/power/energy/cost/thermal appear only in the explicit `not_measured` list | same | **DONE** |
| P2 LOCKED non-searchable | — | `LOCKED_PARAMETERS` named; parametrized test proves the definition refuses each | same | **DONE** |

### Capability payload (current)

```
search_methods      ["grid", "enumeration", "random"]
selection_policies  ["min_first_objective", "lexicographic", "none"]
certified_metrics   completion_cycles, completion_time, completion_ns
                    (registry certified-builtin-v1,
                     316e403f447f90431f761f084539c934aaded9581f15d58d72aa121627a9e938)
topology_family     mesh, torus, concentrated_mesh      (gec, fat_tree refused)
linK_width/radix/concentration   accepted_values = None
                    (validated ranges, NOT finite enumerations — no invented list)
mcast_groups/mcast_setup_cycles  accepted, but change nothing without multicast
locked_parameters   routing_function, turn_restrictions, vc_map, vc_count, escape_vc
not_measured        area, power, energy, cost, thermal, timing closure, effort
```

---

## PHASE 2.1 — capability truth is PROBED, not defaulted

DEFECT: every non-`topology_family` GUIDED parameter was initialized
`qualified=True` on the strength of "NocConfig accepts this field". That
conflated EXPRESSIBLE with "the certified backend measures it".

NEW `optimization/capability_probe.py` answers it by MEASUREMENT.
`prepare_booksim_input` is a pure function of `BookSimProjectionParents`
(topology, attachment, mapping, vc_resource, packet_format, route,
physical_traffic, resolved_fabric), so if patching a parameter leaves every
one of those canonical identities unchanged, the backend bytes CANNOT differ —
the knob is IDENTITY-ONLY. No binary needs to be spawned to prove it.

| parameter | expressible | compilable | effective | qualified | why |
|---|---|---|---|---|---|
| `link_width` | ✓ | ✓ | ✓ | **YES** | changes topology/packet_format/route identities |
| `concentration` | ✓ | ✓ | ✓ | **YES** | changes the topology artifact |
| `radix` | ✓ | ✓ | ✓ | **YES** | changes the topology artifact |
| `topology_family` | ✓ | ✓ | ✓ | **YES** | materializable subset (exhaustively enumerable) |
| `rcu_enabled` | ✓ | **✗** | ✗ | **NO** | a `rcu_enabled` design fails to compile (RESOLVED_FABRIC) |
| `arbitration` | ✓ | ✓ | **✗** | **NO** | compiles, but leaves EVERY projection input identical |
| `mcast_groups` | ✓ | **✗** | ✗ | **NO** | fails to compile; no multicast parameter exists in the closed-world config audit |
| `mcast_setup_cycles` | ✓ | **✗** | ✗ | **NO** | same |

**4 of 8 advertised knobs were not usable certified dimensions.** The payload
now publishes `qualified_parameters`, `unqualified_parameters`,
`effectiveness_basis` and a `multicast_note`, and every unqualified
parameter carries a reason so Studio can explain why it is hidden.

`accepted_values=None` is no longer ambiguous: `accepted_values_is_exhaustive`
is False for the validated-range domains, so Studio cannot read "no list" as
"all values supported". Only `topology_family` is exhaustively enumerable.
`radix`/`concentration` carry the real seat constraint
(`k*k*concentration >= endpoints`) instead of an invented list.

---

## NOT DONE in this slice

| step | status |
|---|---|
| **D** — PHASE 11 CLI P0 defects (A–G) | **NOT STARTED** |
| **E** — multi-class optimization hard gate | **NOT STARTED** (the `render_trace` guard IS covered by `test_workload_moe_lowering.py`; the optimization/evaluation path is not) |
| **F** — PHASE 3 Optimize UI rebuild | **NOT STARTED** (blocked on D/E per the brief) |

### Step A — backend testability (RESOLVED)

The fresh worktree had no built BookSim binary, so `test_p2_optimization_truth`
and friends failed. Symlinking the binary from another worktree does NOT fix
it and must not be used: `assert_pinned_producer` refuses it, because a binary
whose build-time manifest does not verify is not attributable to a source
revision. That refusal is CORRECT and was not worked around.

Canonical build in this worktree:

```
cd third_party/booksim2/src && make -j"$(nproc)"
cd <repo root>
python3 scripts/write_build_manifest.py third_party/booksim2/src/booksim \
    --recipe-version booksim2-fork/v1 --compiler g++ \
    --build-config Release --flag=-O3 --flag=-g
```

The manifest must be written while the worktree is CLEAN: `assert_pinned_producer`
refuses a dirty producer for reusable evidence. The manifest is gitignored
(`*.build-manifest.json`), so writing it does not itself dirty the tree.

| field | value |
|---|---|
| `binary_size` | 20832456 |
| `binary_sha256` | `93e370afaabd11a5430d9e3031a081babfe204c03d7aae803191bc5ded16ada4` |
| `recipe_version` | `booksim2-fork/v1` |
| `source_revision` | `bbc5e1c38763c55c7c0854222e47af902ec2d1e9` |
| `source_dirty` | `false` |
| `compiler` | `g++ (Ubuntu 15.2.0-16ubuntu1) 15.2.0` |

Results after the canonical build:

| run | result |
|---|---|
| `test_product_convergence_phase1.py` | 12 passed |
| `test_product_workflow.py` | 18 passed, 1 skipped |
| `-k "optimization or optimize or product or moe"` | **193 passed, 8 skipped, 0 failed** |

Classification of the 7 earlier failures: **qualification/provenance refusal**
(not regression, not pre-existing defect, not merely environment). Resolved by
building with the canonical manifest.

---

## PENDING — lineage reconciliation (does not block this branch)

The worktree at `/home/datavex/bruh/veritx-research` (branch
`integration/studio-reconciliation`, HEAD `c45f1ea8`) carries a **staged,
uncommitted port of `2e51311d`** into that line: 10 files including
`application/fabric_evaluator.py`, `backend/booksim_projection.py`,
`product/service.py`, `workload/{messages,traffic,intent_lowering}.py`, plus
`tests/test_workload_moe_lowering.py` and an example change.

`booksim_projection.py` and `traffic.py` in that staged set are byte-identical
to `2e51311d`; **`service.py` differs** (`b1db1a8f` there vs `980af7c4` at
`2e51311d`), i.e. it is an adapted port, not a straight copy.

Consequence: `product/service.py` will exist in two divergent forms — this
branch's (based on `2e51311d`) and that line's adapted port. **This must be
reconciled before either becomes a canonical base.** It is recorded here and
deliberately NOT touched from this branch.

---

## Verification rules for this slice

- Do not mark a capability implemented because the UI exists.
- Do not mark a result certified because an evaluator returned a number.
- Do not preserve bad behaviour for backwards compatibility unless a pinned
  consumer is proven.
- Every "supported" claim must resolve to a canonical backend authority.
