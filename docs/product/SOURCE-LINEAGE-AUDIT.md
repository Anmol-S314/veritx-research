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
buggy parser. `core/anynet.py:177` says *"presets.count_anynet_edges
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

### 5. `core/constants.py` — NOT a regression

Current (51 lines) lacks the strong lineage's power/area constants
(`CAPACITANCE_PER_BIT_FF`, `ROUTER_DYNAMIC_MW_PER_MHZ`, `LEAKAGE_PER_ROUTER_MW`,
`ROUTER_STAGE_DELAY_PS`, `WIRE_DELAY_PS_PER_MM`, `TOPO_WIRE_MM`,
`FMAX_DERATING`, `BOOKSIM_SEED`). Current has `DEFAULT_ITERS` which the
strong line lacks. `env_int`, `DEFAULT_K`, `DEFAULT_TIMEOUT` and
`PLANE_C_MAX_VC` are present in **both**. The delta is an **analytical
power/area model**, a different domain from topology synthesis. **Not a
reclamation target for PHASE 1; recorded.**

## Files whose provenance is correct

- `backend/booksim_profile.py` — taken from the **strong** line (identical
  to p1-product / verified-eval / system-performance / studio). Correct.
- `model/routing_materialize.py`, `backend/booksim_projection.py` — from
  canonical; no stronger version found on the audited branches.
- `model/topology_ir.py`, `model/topology_artifact.py`, `model/routing.py` —
  extended locally; no stronger version found.
