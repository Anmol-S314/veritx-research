# Flow and version map

Purpose: make the compile/evidence flow and the artifact version lineage
readable in one place, so "why does v4 exist" and "can this be deleted" become
mechanical questions instead of archaeology.

Supersedes nothing. This is a map, not an authority — authorities remain
`contracts/`, `docs/product/*-registry.yaml`, and the test suite.

---

## 1. What "still achieves the goal" means (the acceptance gate)

Trimming is only safe against a checkable definition of the goal. For this
repository the goal is four things:

| Goal | Authority | How it is checked |
|---|---|---|
| Executable spec | `tracks/t3-topology/dse/tests/` | `pytest` — 7,784 tests collect |
| Frozen wire formats | `contracts/srota/v{1,2}`, `contracts/loom/v1` | fixture validators under `apps/studio/scripts/` |
| Fail-closed product gates | `docs/product/*-registry.yaml` | `scripts/check_*.py` (7 gates) |
| Identity lineage | `schema_version` folded into content hashes | golden/identity tests (`test_v3_identity_golden`, `gen_sealed_input_golden`) |

**A cut is legitimate only if all four still hold.** Removing a symbol that no
caller uses but that participates in a hash domain is *not* a safe cut, even
though it looks dead.

---

## 2. Layering

```
core/            error taxonomy, canonical JSON, external codec            (no domain knowledge)
  |
model/           artifacts + intent roots, each content-addressed          (semantics, no I/O)
  |
compiler/        orchestration: staged derivation, certificates
  |
application/     use-case services (fabric_compiler, capability_truth, ...)
  |
backend/         execution adapters (booksim, astra, meshdor, ramulator)
  |
gateway/ product/   HTTP + product surface; the only I/O boundary
```

Rule the layers already obey: `model/` never imports a backend; `application/`
owns no filesystem; `product/` is the only layer that composes both.

---

## 3. End-to-end flow (verified call paths)

```
                       intent document (JSON)
                              |
                              v
  product/service.py:584  parse_request_doc()          <- emits V1..V5 object
                              |
                 +------------+-------------+
                 |                          |
     gateway/app.py:357              product/service.py:592
     CompileRequestV3.from_dict      migrate_v3_to_v4()
                 |                          |
                 v                          v
     application/fabric_compiler.py:233  compile(request, routing_policy)
                 |
                 |-- schema_version == 5  ->  _compile_v5()          (fabric_compiler.py:239)
                 |                              `- V5.to_compile_request_v4()   (compile_request_v5.py:345)
                 |-- CompileRequestV3/   ->  staged orchestration    (compiler/orchestration)
                 |   V4
                 v
        resolution of the 7 fabric children, then:
            model/fabric_artifact.py:99   FabricArtifact
                = TopologyArtifact              (model/topology_artifact.py:252)
                + AgentAttachmentArtifact       (model/attachment.py:161)
                + VCResourceArtifact            (model/vc_resource.py:76)
                + RoutingRealizationArtifact    (model/routing_realization.py:304)
                + PacketFormatArtifact          (model/packet_format.py:272)
                + RouterBehaviorArtifact        (model/router_behavior.py:161)
                + AddressDecodeArtifact         (model/address_decode.py:227)
                 |
                 v
        verification certificate   (certificate.overall must == "PASS")
                 |
                 v
        backend execution  ->  evaluation evidence
```

Two invariants worth keeping visible:

- **Refusal is a first-class outcome.** `UNSUPPORTED` and `INVALID` are returned,
  never raised past the boundary, and `UNMEASURABLE` renders differently from
  `VIOLATED`. Absence of information never becomes an assumed default.
- **Identity is separate from provenance.** The design hash covers science;
  `synthesis_provenance` and `migration_provenance` do not enter it.

---

## 4. Version lineage (and why it is not sprawl)

```
CompileRequest   v1  test-only surface; no production caller
CompileRequestV3 v3  FROZEN  <-- still the execution currency
CompileRequestV4 v4  FROZEN  holds typed topology intent
CompileRequestV5 v5  current frontier (explicit clock/sideband/access policy)

RouteArtifact v2 (core/route_artifact.py)   private-channel fabrics
RouteArtifact v3 (model/route_artifact_v3.py) shared-wire fabrics (opt-in)
```

The dependency direction is **downward**: V5 projects into V4, V4 migrates from
V3, and the gateway still parses V3. Nothing calls "up".

Why the frozen generations cannot be merged, from
`docs/decisions/modules/model.md:155`:

> Schema 3 / compiler semantics 3 are RELEASED semantic authorities. PHASE B
> originally added typed topology intent to `CompileRequestV3` directly, which
> expanded schema 3 IN PLACE: schema-3 readers that used to refuse a typed
> intent would accept one. Two binaries reading the same "v3" document would
> then disagree about what v3 means.
>
> **V2 IS FROZEN. V3 IS FROZEN. NEW FABRIC SEMANTICS REQUIRE V4.**

And on identity separation:

> **NEW HASH DOMAIN.** `_HASH_TYPE_TAG_V4` plus `schema_version=4` /
> `compiler_semantics_version=4` domain-separate the envelope, so a v3 and a v4
> document can never share an identity by construction — including the migrated
> pair, which is the point: the same science expressed in two generations is
> deliberately NOT the same design identity.

`RouteArtifact` v2/v3 is a **capability** split, not a time split
(`model/route_artifact_v3.py:1`): v2 persists one integer channel id, and that
integer *is* the identity — it is hashed, recorded in qualification records and
compared against simulator dumps. v3 carries a `RouteDecision` for shared wires.

**Consequence:** archiving any frozen version is not a refactor, it is a
rewrite of recorded evidence. Do not do it.

---

## 5. Where the fat actually is

### 5.1 Dead code: almost none

`vulture` over all 313 modules / 120,867 lines returns **5 findings above 80%
confidence**, and all 5 are protocol or signature requirements, not fat:

| Finding | Why it is not fat |
|---|---|
| `astra_machine.py:753` `workload_directory` | required parameter of a public signature |
| `ai_search.py:61` `newurl` | `urllib` override must accept it |
| `llmserving_protocol.py:139` `exc_type, tb` | `__exit__` protocol |
| `chakra_to_dse.py:239` `npu_map_all` | public API parameter; removing changes a signature |

This is a tight codebase. **"Trim the fat" as dead-code deletion has almost no
yield here** — which is the single most useful thing the map can tell you.

### 5.2 The real fat is file delineation

| File | Lines | Top-level classes | Verdict |
|---|---|---|---|
| `product/service.py` | 5,039 | — | god object |
| `backend/booksim_projection.py` | 3,065 | 13 | mixed purpose |
| `model/compile_model.py` | 3,048 | **38** | v1 + v3 generations in one file |
| `cli/cli.py` | 1,824 | — | command surface + logic |
| `model/topology_artifact.py` | 1,551 | — | |
| `gateway/app.py` | 1,466 | 20 | routes + schemas + handlers |

Six of these eight are currently dirty in the working tree, so they are
**deliberately not touched** here.

### 5.3 Looks like duplication, is deliberate

`model/domain_intent/_parse.py` re-expresses `_strict_keys` / `_need` /
`_as_int` that `compile_model.py` also defines. This is intentional — the
module docstring records why: `compile_model`'s helpers raise bare
`ValueError`, while domain intent must raise `DomainIntentError` (contract §1).
**Do not deduplicate these.**

---

## 6. Delineation plan

### 6.1 `compile_model.py` — blocked on WIP

The highest-value remaining target. Its seams are already marked in the source.
Split by contiguous line range, with `compile_model.py` left behind as a
re-export shim so **no importer changes**:

| New module | Lines | Contents |
|---|---|---|
| `model/_schema.py` | 26-169 | `CompileRequestSchemaError` + coercion helpers |
| `model/workload.py` | 170-487 | `Tier`, `AgentKind`, `Agent`, `ModelFamily`, `ServingMode`, collectives, `Workload`, `Requirement*`, `Dep*`, `DependencyGraph` |
| `model/topology_spec.py` | 488-737 | `derive_vc_count`, `TopologyFamily`, `OutputFormat`, `NocConfig`, `AddressRange`, `AddressMap` |
| `model/physical.py` | 738-857 | `PhysicalContext`, `VCSeparation`, `VCAssignment`, `collective_vc_*`, `derive_vc_assignment` |
| `model/compile_request_v1.py` | 858-1629 | `CompileRequest` + `migrate_design`, `validate`, `derive_topology_spec` — **archive candidate** |
| `model/workload_v3.py` | 1630-2017 | `CompileRequestV3SchemaError`, `WorkloadSourceRef`, `WorkloadV3`, `RequirementV3` |
| `model/compile_request_v3.py` | 2018-3048 | `CompileRequestV3` (frozen authority — rename directory to communicate that) |

### 6.2 `domain_intent` — DONE

`model/domain_intent.py` (1,178 lines) was split into a package. The file's own
section banners were the seams, so no judgement was needed:

| Module | Lines | Purpose |
|---|---|---|
| `_core.py` | 16 | `SCHEMA_VERSION`, `DomainIntentError` |
| `_parse.py` | 119 | typed coercion helpers (raise `DomainIntentError`, not `ValueError`) |
| `enums.py` | 86 | the 10 domain enums + their law frozensets |
| `clock.py` | 245 | `ClockSource`, `ClockDomain`, validation, materialisation |
| `reset.py` | 189 | `ResetChannel`, `validate_reset_channels` |
| `power.py` | 63 | `PowerDomain` |
| `crossing.py` | 332 | `AsyncFIFOConfig`, `Crossing`, `assess_crossing` |
| `fifo.py` | 173 | `AsyncFIFOModel` (performance consequence) |
| `__init__.py` | 73 | original module docstring + all 26 re-exports |

Zero import churn: `__init__.py` re-exports the original `__all__` verbatim, so
all 9 test modules and every application importer were unchanged.

Dependency order is a DAG (`_core → _parse → enums → clock → reset → power →
crossing → fifo`). Two apparent cycles were **docstring-only**
(``:class:`AsyncFIFOModel``` in `crossing`, ``ResetChannel.from_dict`` in
`enums`) and were correctly excluded by deriving references from the AST rather
than from text search; the one real edge (`fifo → AsyncFIFOConfig`) is preserved.

**Follow-up that the split surfaced:** `application/loom_capability.py` cited the
old file path as evidence in six capability rows (`reset.intent`,
`reset.async_assert_sync_deassert`, `cdc.crossing`, `cdc.sync_2ff`,
`cdc.sync_3ff`, `cdc.async_fifo`). No test resolves evidence refs to real files
— it only checks that a ref *looks* like a path — so these would have rotted
silently. They now point at the specific submodule, which is strictly more
precise than the old monolith citation.

Verification: 345 tests passed across the 11 affected modules, 320/321 modules
import (the one failure, `backend/meshdor.py`, is pre-existing and unrelated —
clean file, no `domain_intent` import, fails on its own config assertion).

---

## 7. Verification gate

Run before and after any cut.

```bash
cd tracks/t3-topology/dse

# 1. behaviour on the surface you touched (the gate that actually holds)
python3 -m pytest $(grep -rln 'MODULE_NAME' tests/ --include=*.py) -q

# 2. product gates (fail-closed)
cd ../.. && for g in check_intent_ontology check_capability_registry \
  check_capability_truth check_exposure_registry check_preset_certification \
  check_python_deps check_release_toolchain; do python3 scripts/$g.py; done
```

### Do NOT use collection count as a tripwire here

This document originally recommended `pytest --collect-only` count matching as a
cheap global check. **That is wrong for this repository** and was retracted
after measurement: the count moved 7,783 -> 7,784 -> 7,786 across a single
session with no test authored, and stayed at 7,786 with a new doc file added or
removed. It is not a stable invariant — the working tree is edited concurrently
(dirty-file count moved 295 -> 301 mid-session, including test sources), and
generated fixtures under `tests/`, `examples/` and `runs/` feed parametrized
collection.

Use collection only as a **one-shot import health check** ("does anything fail
to import?"), never as a numeric equality assertion.

### Known-red baseline (not yours)

```
tests/test_serving_federation_adapter.py::test_bound_valid_experiment_assesses_ready_or_unavailable
```

`CANONICAL_SERVING` assesses `BLOCKED` where the test expects `READY` or
`UNAVAILABLE`. **Verified to fail identically on pristine `HEAD` (`713825c7`)**
with changes reverted, so it is pre-existing and environmental. Do not chase it
while cutting; do not "fix" it by loosening the assertion.

### Caution learned the hard way

1. `pytest --collect-only` is the cheapest tripwire for a deleted import that was
   actually a **re-export**. `vulture` cannot tell the difference —
   `MissingCapability` in `application/capability_gaps.py` was reported unused
   while `tests/test_capability_gaps.py` imported it from that module.
2. A full `pytest -q` run exceeds 20 minutes here; budget for it or scope to the
   touched surface. A timeout kill mid-run leaves a misleading partial log.
3. `pkill -f pytest` will match and kill the shell running the command, because
   the command string contains "pytest". Kill by PID.

---

## 8. Known dead / cuttable

| Item | Status |
|---|---|
| `migrate_v2_to_v4` (`model/compile_request_v4.py`) | **cut** — 0 callers; the live v2 path composes `migrate_v2_to_v3` + `migrate_v3_to_v4` explicitly in `product/service.py:583-592`. The `from_dict` refusal message now names that composition. |
| unused import in `application/fabric_compiler.py` | **cut** — `build_resolved_bundle_v3` removed from a local import |
| `MissingCapability` re-export in `application/capability_gaps.py` | **kept** — it is a public re-export; now written as an explicit `as` re-export so linters stop flagging it |
| `CompileRequest` v1 (`compile_model.py:858-1629`) | **blocked** on the `compile_model.py` split — v3 consumers still import `Agent` / `NocConfig` / `TopologyFamily` from the same module |

Net effect of this pass: 3 files touched, ~20 lines removed, no behaviour change.
