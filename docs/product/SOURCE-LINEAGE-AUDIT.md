# SOURCE-LINEAGE AUDIT — TRANCHES 1–5

> Which historical implementation did each reclaimed file actually come
> from, and was a stronger one available?

**Why this exists.** A reclamation pass that "discovers" a missing behaviour
and re-implements it is only correct if no stronger implementation already
exists elsewhere. `integration/canonical` **sounds** authoritative but is a
migration *destination*, not a quality ranking. Two files were found to have
been taken from it while stronger descendants existed.

## AUTHORITY-SELECTION LAW

> **"canonical" means the current integration destination. It does NOT mean
> the strongest historical source implementation.**

Reclamation must inspect descendants and sibling branches before recreating
missing behaviour, and must record the chosen source.

## File-lineage table

Line counts across the branches that carry each file.

| File | current | canonical | p1-product / verified-eval | verdict |
|---|---|---|---|---|
| `core/route_artifact.py` | 706 → **972** | **704 (4 lines off)** | **971 (359 lines off)** | **RECLAIMED (PHASE 2)** |
| `synthesis/milp_topology_v2.py` | 454 → **521** | **454 (IDENTICAL)** | **582 (152 lines off)** | **RECLAIMED (PHASE 1)** |
| `model/presets.py` | 425 → **649** | **425 (IDENTICAL)** | **684 (259 lines off)** | **RECLAIMED (PHASE 1)** |
| `core/constants.py` | 51 | 51 | 92 | superset on strong (power/area model); `env_int` present in both |
| `model/topology_ir.py` | 595 | absent | 529 | extended locally |
| `model/topology_artifact.py` | 685 | 467 | 421 | extended locally |
| `model/routing.py` | 267 | absent | 68 | extended locally |
| `model/routing_materialize.py` | 326 | 324 | absent | from canonical |
| `backend/booksim_profile.py` | 414 | absent | SAME | from the strong line |
| `backend/booksim_projection.py` | 1049 | 939 | absent | from canonical |
| `backend/route_observation.py` | 167 | **absent everywhere** | absent | **locally invented** |

## Regressions from a weaker ancestor

### 1. `milp_topology_v2.py` — CONFIRMED, **RECLAIMED (PHASE 1)**

The current tree took this file **byte-identically** from
`integration/canonical`. The stronger version on
`p1b/verified-evaluation` / `integration/p1-product` / `epic/booksim-forward-port`
(blob `7487c3228036`, identical on all three) rejects empty, ragged,
non-square, non-numeric, NaN/Inf and negative matrices, resolves
`VERITX_TIMEOUT` through `env_int`, and takes `DEFAULT_K` from
`core.constants`.

**Consequence:** the Tranche-3 report said *"the historical `load_matrix`
validates nothing"*. True of the current tree's copy; **false about the
historical implementation.** `SynthesisTrafficMatrix` was built to add
validation that already existed.

**Behaviour matrix — every semantic delta, and its disposition:**

| Strong-lineage behaviour | Disposition | Reason |
|---|---|---|
| hardened `load_matrix` (empty/ragged/square/non-numeric/NaN/Inf/negative) | **RECLAIMED** | the confirmed regression; one validation authority |
| `solve_tmcf(timeout=None)` → `env_int("VERITX_TIMEOUT", 120)` | **RECLAIMED** | `timeout=120` was hardcoded; env override lost |
| `--k default=DEFAULT_K` (from `core.constants`) | **RECLAIMED** | constant must have one home |
| imports `DEFAULT_K`/`DEFAULT_TIMEOUT`/`env_int` from `core.constants` | **RECLAIMED** | `env_int` present in both trees; canonical home is `core.constants` |
| `mesh_size`/`grid_size`/`anynet_size` wrappers | **NOT RECLAIMED** | dead code: zero call sites in the strong file or anywhere else |
| `_shared_write_anynet` from `synthesis.evaluator` | **SUPERSEDED** | `synthesis/evaluator.py` no longer exists (889 lines → `application/product_evaluator.py`). The engine must not import the candidate layer (`candidate.anynet_projection`), which would invert the dependency. The inline writer is retained and **normalised to the canonical byte format** (`.rstrip()`, no trailing space) so it is indistinguishable from `model.topology_ir.to_anynet`. |
| `SynthResult.ok(...)` `synth_result` record block | **SUPERSEDED — deliberately not reclaimed** | `synthesis/results.py` no longer exists. The canonical candidate identity is `synthesis.candidate.TopologyCandidate` (solver status, `graph_id`, `candidate_id`), a **different identity** — emitting a `SynthResult`-shaped dict would create a second, competing candidate record. |
| docstring `--matrix dse/archive/...` | **NOT RECLAIMED** | a path in an example, not a contract |
| 6 extra `SWEEP_TOPOS` entries + `collectives` in `WORKLOAD_PRESETS` | **NOT RECLAIMED** | separate domains (see §3, §4) |

**Action taken:** the hardened `load_matrix`, the `timeout=None`/
`env_int` resolution and the `core.constants` imports are **reclaimed**
(with a provenance note in-file). `SynthesisTrafficMatrix` remains the
canonical authority — it additionally binds source provenance, which the
loader does not — and the file parser is developer tooling that must not
contradict it. **Validation ownership: one authority, no drifting
duplicate.**

### 1b. `model/presets.py` — CONFIRMED, **RECLAIMED (PHASE 1)**

Found while reconciling §1: the strong `milp_topology_v2` delegates its
topology sizes to `model.presets.topo_size`, and the current tree's
`model/presets.py` was **byte-identical to `integration/canonical`** while
the strong lineage carried 259 more lines. Unlike `milp_topology_v2.py`,
this was not latent — it was **live breakage**:

| Missing authority | Live caller (current tree) | Effect |
|---|---|---|
| `parallel_world_size` | `model/compile_model.py:2151`, `:2862` (`Workload.world_size`, v3 workload `.world_size`) | `ImportError` on any call |
| `resolve_fabric` | `core/spec.py:191` (standalone `network.topology` resolution) | `ImportError` on any call |
| `topo_size` | `veritx_dse/tools/multi_workload_pareto.py:447` | `ImportError` on any call |
| `normalize_collective` | (no current caller; canonical collective-spelling authority) | — |
| `check_anynet_connected` | (delegating wrapper; `core/anynet.py` is the authority) | — |

**And `core/anynet.py` already documents the delegation that was lost.**
Its module docstring names `presets` as a consumer of the one anynet
parser and states that `presets._parse_anynet_adj` *"required >=5 tokens
per line and peer-scanning from index 4 (two-line link files yielded EMPTY
adjacency)"* — yet the current `presets.py` still contained that exact
buggy parser. `core/anynet.py:147` says *"presets.count_anynet_edges
delegates here"*, which was false in the current tree.

Three further losses in the same file, each a **false-science** defect:

| Defect in the weaker copy | Corrected by the strong lineage |
|---|---|
| `_default_edge_count("mesh", k=8, n=2)` returned `n*k**n = 128` | `n*(k-1)*k**(n-1) = 112` (a mesh has no wrap links) |
| `_default_edge_count("gec", o=7, d=1)` returned `112 + 448 = 560` | `k*k*(k-1) = 448` — express mode builds **only** the p2p graph; the extra 112 counted links BookSim never builds |
| `gec_mesh_k8` params `{o: 0, d: 0}` — BookSim converts `o=0/d=0` to full-express defaults | `{o: 1, d: 1, mesh: 1}` — the real mesh graph; the old preset was a **silent duplicate of `gec_express_k8`** |

**Action taken:** `normalize_collective`, `parallel_world_size`,
`_parse_anynet_adj`, `check_anynet_connected`, `topo_size`, `resolve_fabric`,
the corrected `_default_edge_count`, the delegating `count_anynet_edges`
and the `gec_mesh_k8` fix are **reclaimed** verbatim from the strong
lineage. The two assertions in `tests/test_cli_modules.py` that **pinned
the wrong counts** (128 mesh, 560 gec) were corrected to 112 / 448 and the
mesh-vs-torus distinction restored.

**Deliberately NOT reclaimed from the same strong file** (separate
domains, see §3 and §4): the six extra `SWEEP_TOPOS` entries and the
`collectives` block added to four `WORKLOAD_PRESETS` entries.

### 2. `core/route_artifact.py` — CONFIRMED, **RECLAIMED (PHASE 2)**

Current was 4 lines from `integration/canonical`; the stronger version
(blob `8fdb3985…`, identical on `p1b/verified-evaluation` /
`integration/p1-product`; `epic/booksim-forward-port` carries a third
variant `ca52ae96…`) is **359 lines away** and contained functions
**entirely absent** from the current tree:

| Missing function | What it is |
|---|---|
| `equivalence_report` | per-flow expected-vs-executed comparison with `mismatched`, `missing_in_executed`, `extra_in_executed` all pinned |
| `artifact_from_anynet` | build a `RouteArtifact` from an AnyNet table |
| `upgrade_v1_to_v2` | **schema upgrade** (the audit's `upgrade_v`) |
| `topology_hash_from_adj` | topology identity from an adjacency |
| `standalone_channel_dst` | channel destination mapping |
| `first_hop_table` | public first-hop projection |
| `route_entries_from_adj` | public (ours was private `_route_entries_from_adj`) |
| `RouteArtifact.from_adjacency` | standalone-graph constructor — **live caller** `tools/deadlock_routing.py:426` already called it and would have raised `AttributeError` |
| `_validate_hop_entries` | all-pairs coverage + adjacency legality for a supplied hop table |

**Action taken — semantic three-way merge, not a wholesale replace.** The
current tree carried later hardening that the strong version lacks, and
all of it is preserved:

| Current-only hardening | Status |
|---|---|
| `RouteArtifactError(ValueError, SemanticError)` | **preserved** (strong is bare `ValueError`) |
| defensive freeze of `RoutingClassDefinition.parameters` | **preserved** |
| defensive copy + `MappingProxyType` for `RouteArtifact.entries` | **preserved** |
| `isinstance(self.entries, Mapping)` (not `dict`) | **preserved** — required so the read-only view re-validates |

`_route_entries_from_adj` is retained as a module-level **alias** of the new
public `route_entries_from_adj` (same object), so the earlier private name
keeps resolving to one implementation.

**Ownership reconciliation of the locally invented
`backend/route_observation.py`.** It was not deleted and is not garbage — it
is a **simulator adapter** owning two things the core module does not:
parsing the fork's `routing.dump` line format, and deriving the expected
table from a `TopologyArtifact` + execution `node->router` map (a node-level
domain, wider than router pairs). What it must NOT own is route-set
comparison semantics, which it previously re-implemented. A new core
primitive **`compare_first_hop_tables(expected, executed)`** is now the
single comparison authority; `equivalence_report` and
`route_observation.compare_route_realization` both delegate to it. The
adapter still converts a `DIVERGENT` verdict into its typed refusal with the
pinned per-flow diagnostics, so its callers and error contracts are
unchanged.

**Stale-diagnostic fix:** `model/routing.py` (×2),
`tests/test_custom_routing.py` and `tests/test_booksim_route_equivalence.py`
cited the private `_route_entries_from_adj`; they now cite the public
`route_entries_from_adj`.

### 3. `SWEEP_TOPOS` surface — NOT reclaimed (Gate-8)

The strong lineage's `SWEEP_TOPOS` carries 13 entries; the current tree
carries 7. The six extras (`fbfly_64`, `cmesh_64`, `fattree_k4n3`,
`qtree_64`, `tree4_64`, `dragonfly_72`) have **no evidence row** in
`docs/product/topology-family-registry.yaml` or
`docs/product/exposure-registry.yaml`. Gate-8 is remove-first: *expose less
rather than false science*. Advertising a topology with no certification
is exactly the failure Gate-8 forbids, so the pruned set is the correct
surface. **Recorded, not reclaimed.** If these families are wanted they
must be added through the family registry with evidence, as their own pass.

### 4. `WORKLOAD_PRESETS[*]["collectives"]` — NOT reclaimed

The strong lineage adds a `collectives` block to four workload presets and
a `CollectiveOp.from_dict` consumer in `preset_to_compile_request`. That
changes the `CompileRequest` content for those presets and therefore their
`design_hash` and certification outcome. It is a **workload-traffic
authority** change (the domain of Tranche 3's `SynthesisTrafficMatrix` and
PART D.12), not topology-synthesis lineage, and it must not ride a
reclamation commit. **Recorded as a separate candidate change.**

### 5. `core/constants.py` — PARTLY RECLAIMED (PHASE 3.1)

Current (51 lines) lacked the strong lineage's report area/power/timing
constants (`CAPACITANCE_PER_BIT_FF`, `ROUTER_DYNAMIC_MW_PER_MHZ`,
`LEAKAGE_PER_ROUTER_MW`, `ROUTER_STAGE_DELAY_PS`, `WIRE_DELAY_PS_PER_MM`,
`TOPO_WIRE_MM`, `FMAX_DERATING`, `LINK_AREA_MM2_256B_7NM`,
`NIC_AREA_MM2_7NM`, `RCU_AREA_MM2_7NM`, `MECS_AREA_MM2_7NM`) and
`BOOKSIM_SEED`. Current had `DEFAULT_ITERS` which the strong line lacks and
which has **0 references** in the tree.

**Corrected (PHASE 3.1).** The PHASE-1 note below called this "a separate
analytical domain, not a reclamation target". That was incomplete:
`reports/reports.py` — a LIVE, tested module — was already the consumer, and
was duplicating every one of those numbers locally. Two authorities for the
same constant is exactly the drift this audit exists to remove.

**Action taken:** all of the above are reclaimed into `core.constants`;
`reports/reports.py` aliases them; `DEFAULT_ITERS` is dropped;
`PLANE_C_MAX_VC` is now env-overridable (`env_int("VERITX_MAX_VC", 8)`)
and imported by `model/compile_model.py` instead of being re-declared as a
literal there. `BOOKSIM_SEED` closes a live gap —
`tools/multi_workload_pareto.py` was importing it through a fallback shim.

## PHASE 3 — first re-run of the source-lineage audit (after PHASE 1 + PHASE 2)

**Superseded by PHASE 3.1 below.** The candidate discovery below is sound;
the closure analysis in this section was not. It classified six files as
"NO STRONG-ONLY SYMBOL" and treated that as equivalent to "no regression",
which is false: a weaker ancestor can change a function BODY without adding
a symbol. Two of those six (`reports/artifact.py`, `cli/pipeline.py`) were
live defects. The counting was also wrong — the table has SIX
no-strong-only-symbol rows, not three. The section is kept, corrected, so
the error is auditable rather than erased.

**Method (discovery only).** Blob identity, not line count. A file is a
regression candidate only if its current blob is **identical to
`integration/canonical`** (i.e. the tree took it from the migration
destination) **and** the strong branch (`github/integration/p1-product` /
`github/p1b/verified-evaluation`) carries a different, larger blob. Files the
current tree evolved deliberately do not match canonical and are not
candidates.

**Candidates found: 15** (after PHASE 1 and PHASE 2 removed
`synthesis/milp_topology_v2.py`, `model/presets.py` and
`core/route_artifact.py` from the set).

| Candidate | cur / strong | PHASE-3 classification | Evidence |
|---|---|---|---|
| `application/service.py` | 252 / 1541 | **SUPERSEDED** | `SrotaControlPlane`'s 37 strong-only methods (`validate`, `capabilities`, `plan`, `evaluate`, `run_study`, `compare`, `inspect`, …) belong to the pre-product CLI-era control plane; the current authority is `product/service.py::ProductService` (2232 lines) plus `application/comparison.py` and the `product/*` seam. Strong-only leftovers `_binder_chain`/`_default_store_root` have 0 references. |
| `simulation/model_to_trace.py` | 219 / 444 | **SUPERSEDED** | Strong-only `broadcast_packets`, `p2p_packets`, `_validate_source`, `_flow_bytes_by_class`, `write_lowering_manifest`, `_lowering_manifest`: 0 references. `LoweringError` (48 references) lives at `workload/lowering.py:41` (`WorkloadError` base) with `LoweringManifest`, `UnsupportedSemantic`, `et_readback_conservation`. The typed lowering module is the current authority. |
| `simulation/traces.py` | 453 / 578 | **SUPERSEDED** | Strong-only `trace_num_nodes`, `aggregate_matrix`, `save_matrix`, `matrix_to_trace` (an untyped trace↔matrix round-trip): 0 references. Replaced by the typed traffic authority (`workload/traffic.py`, `SynthesisTrafficMatrix`, `workload/canonical.py`). The current `traces.py` carries the richer `validate_trace`/`analyze_trace`/`extract_burst`/`extract_uniform`/`slice_trace`. |
| `synthesis/iterative_synthesizer.py` | 336 / 508 | **SUPERSEDED** | Strong-only `mesh_size`/`grid_size`/`anynet_size` are the same dead wrappers rejected in §1; `mesh_seed_adj` has 0 references. Size math now has one authority, `presets.topo_size`. |
| `synthesis/bo_synthesizer.py` | 526 / 690 | **SUPERSEDED** | Same dead size wrappers; `_canonical_runs` has 0 references. |
| `core/logging.py` | 137 / 186 | **INTENTIONAL-REMOVAL** | Strong-only `emit()`, `diag()`, `Ctx.failed`. `tests/test_p2_guided_optimization.py:989` and `tests/test_p2_optimization_truth.py:1112` name `Ctx.failed` among features **removed on purpose**. |
| `__init__.py` | 44 / 98 | **COSMETIC** | The delta is only re-export surface (`derive_vc_assignment_artifact`, `migrate_design`, `PacketFormatArtifact`, `ResolvedRouteArtifact`, placement/mapping/attachment/address-decode names). Every symbol remains importable from its submodule; no caller imports it from the package root. |
| `cli/pipeline.py` | 466 / 683 | **NO STRONG-ONLY SYMBOL → was WRONG** | Body-level comparison found live defects. See PHASE 3.1. |
| `reports/reports.py` | 447 / 532 | **NO STRONG-ONLY SYMBOL → was INCOMPLETE** | Body-level comparison found duplicated magic numbers. See PHASE 3.1. |
| `backend/contracts.py` | 881 / 883 | **NO STRONG-ONLY SYMBOL → CURRENT-STRONGER** | See PHASE 3.1. |
| `reports/artifact.py` | 224 / 232 | **NO STRONG-ONLY SYMBOL → was WRONG** | The strong lineage HAS `MissingSigningKey` and `_require_key`; the current copy signed with a source-embedded default secret. Live integrity defect. See PHASE 3.1. |
| `synthesis/event_objective.py` | 159 / 166 | **NO STRONG-ONLY SYMBOL → RECLAIM** | Script-mode import fallback lost. See PHASE 3.1. |
| `simulation/trace_to_binary.py` | 53 / 54 | **NO STRONG-ONLY SYMBOL → COSMETIC** | 12 vs 16 byte record. See PHASE 3.1. |
| `application/resources.py` | 504 / 410 | **CURRENT LARGER** | No regression. |
| `application/store.py` | 432 / 105 | **CURRENT LARGER** | No regression. |

**CLI helper note.** The strong `cli/cli.py` (5177 lines) carries fail-fast
helpers the current tree does not have by those names
(`_eff_timeout`, `_expand_anynet_files`, `_sim_overrides`). The *contracts*
are present elsewhere: `VERITX_TIMEOUT` precedence is honoured at
`core/config.py:49`, and the current tree split the monolithic CLI into
`cli/commands_compile.py`, `cli/commands_trace.py`,
`cli/commands_optimize.py`. Reclaiming the strong CLI wholesale is **not**
justified — it would re-introduce `Ctx.failed`, which the tree removed on
purpose — so the individual helpers are recorded as a **PART I candidate**,
not reclaimed here.

### Verdict of the first re-run — RETRACTED

> ~~0 unresolved weaker-ancestor regressions with a live caller.~~
>
> ~~12 classified; 3 differ only inside function bodies and were not
> line-by-line diffed.~~

Both sentences were wrong. Six files were body-level residuals, not three,
and two of them (`reports/artifact.py`, `cli/pipeline.py`) contained live
defects that symbol-set equality could not see. **Superseded by PHASE 3.1.**

## PHASE 3.1 — semantic closure of the body-level residual

**Method.** Blob identity remains the *discovery* filter; it is NOT a
closure test. For every candidate the audit now compares, at body level:
top-level symbol additions/removals, function and class bodies, constants
and defaults, exception behaviour, serialization/hash behaviour, CLI/error
behaviour, and tests that existed on the strong lineage but disappeared.
Line count is never the decision rule, and supersession is never inferred
from the mere existence of a newer-looking module — a named successor and
its callers must be shown.

**Body-level disposition of the six residual files**

| File | Body-level finding | Disposition | Where it landed |
|---|---|---|---|
| `reports/artifact.py` | Strong lineage has `MissingSigningKey`, `_require_key`, `create_unsigned`, `_build`. Current had `_DEFAULT_SECRET = "srota-studio-default-key-change-in-production"` and signed with it whenever a caller omitted the key. A source-embedded key is public, so integrity was presented as authenticity. | **RECLAIM** | `MissingSigningKey(TypeError)`, one `_require_key` gate called by the primitives AND the classmethods (empty string refuses too), explicit `create_unsigned()` → `CHECKSUMMED_UNSIGNED` with an empty signature and a retained `manifest_hash` checksum. Callers reconciled: `test_prd_gaps.py`, `test_api_contract.py`, `__init__.py`. |
| `cli/pipeline.py` | `run_compare` gained an anynet connectivity + trace-size precheck, `topo_size` on failure records (current wrote `nodes: 0`), `honest_latency` preference, failed-candidate visibility in `summary`; `list_runs`/`show_results`/`diff_runs` hardened; `generate_latex` gained sweep-list support. It also gained a Phase-8 `core.comparison` verdict block gating the winner. | **RECLAIM (generic safety)** + **SUPERSEDED (verdict block)** | `anynet_usability` promoted to ONE reusable authority in `model.presets`; the other safety behaviours reclaimed into `cli/pipeline.py`. The verdict block is NOT reclaimed: `core/comparison.py` is `LEGACY_INTERNAL` per `application/inventory.py:88-96` and `application.comparison` is the canonical gate. The CLI winner claim is instead labelled **UNCERTIFIED LEGACY COMPARISON** so it cannot be confused with a qualified product comparison. |
| `reports/reports.py` | Strong centralizes area/power/timing knobs in `core.constants` and adds a collective sizing block. Current duplicated every magic number locally. | **RECLAIM** | `core.constants` reclaims the report knobs + `BOOKSIM_SEED`; `reports.py` aliases them. `PLANE_C_MAX_VC` now has one home (imported by `compile_model`, not re-declared). Collective block reclaimed with explicit *estimate, not sign-off* notes, plus `collective_vc_floor`. Dead `DEFAULT_ITERS` dropped. |
| `backend/contracts.py` | Strong built hashes by hand: `sha256((tag + "\0" + canonical_json(x)))`. Current delegates to `core.artifact.content_id`. | **CURRENT-STRONGER (proven)** | Proven byte-equivalent to the manual construction, and strictly stronger: `canonical_bytes` thaws frozen containers. Not restored. Pinned by test. |
| `synthesis/event_objective.py` | The module advertises `python event_objective.py …` and has a `__main__` entry point, but a bare package-relative import died before argparse. | **RECLAIM** | Script-safe import fallback. Verified by a subprocess `--help` smoke test. |
| `simulation/trace_to_binary.py` | `struct.pack("<QHHHH", …)` is 8+2+2+2+2 = 16 bytes; the docstring said 12. | **COSMETIC** | Corrected to 16, and the record size is now a named constant so writer, reader and documentation cannot disagree again. |

**Exact counts over the 15 audited weaker-ancestor candidates**

| Disposition | Count | Files |
|---|---|---|
| RECLAIM | **4** | `cli/pipeline.py`, `reports/reports.py`, `reports/artifact.py`, `synthesis/event_objective.py` |
| CURRENT-STRONGER | **3** | `backend/contracts.py`, `application/resources.py`, `application/store.py` |
| SUPERSEDED-BY-NAMED-AUTHORITY | **5** | `application/service.py`, `simulation/model_to_trace.py`, `simulation/traces.py`, `synthesis/iterative_synthesizer.py`, `synthesis/bo_synthesizer.py` |
| INTENTIONAL-REMOVAL | **1** | `core/logging.py` |
| COSMETIC / DOCUMENTATION | **2** | `__init__.py`, `simulation/trace_to_binary.py` |
| **OPEN-BLOCKER** | **0** | — |
| **TOTAL** | **15** | |

Across the whole audit (PHASE 1 + 2 + 3.1) the weaker-ancestor candidate set
is **18**: the 15 above plus the three already reclaimed —
`synthesis/milp_topology_v2.py`, `model/presets.py`, `core/route_artifact.py`
— for **7 RECLAIM** in total.

**Success condition met:** `OPEN-BLOCKER = 0`, every body-level residual
dispositioned, and no policy/diagnostic contradiction (see
`fix(routing): make diagnostics derive from certified policy`).

## Files whose provenance is correct

- `backend/booksim_profile.py` — taken from the **strong** line (identical
  to p1-product / verified-eval / system-performance / studio). Correct.
- `model/routing_materialize.py`, `backend/booksim_projection.py` — from
  canonical; no stronger version found on the audited branches.
- `model/topology_ir.py`, `model/topology_artifact.py`, `model/routing.py` —
  extended locally; no stronger version found.
