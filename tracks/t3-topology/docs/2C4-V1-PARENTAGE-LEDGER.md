# 2c.4 semantic-parent cutover — v1-parentage ledger

Status: **parentage class CLOSED** — chain generation aware in 2c.4a
(`db0a17f6`), `NetworkWindowBinding` generation-aware in `06e37487` (§3),
network-window path generation-aware at all four sites. Originally written
as the pre-flight for 2c.4b, after a systematic audit rather
than discovered one site at a time. Every site below reads or persists a
v1-only ancestry key (`operation_graph_id`, `waved_workload_id`,
`wave_d_semantics_id`, or an equivalent). Sections 1–4 record where each
site landed; §5 is the interlock now constraining the writer switch.

The reason this file exists: during seam 0.1 the *plan-side* hard-coded
`operation_graph_id` read was found by the architect, and it was fixed as
a single instance. A systematic grep for the same class then found two
more sites — one of which is not a read at all but a **persisted schema**.
Fixing instances one at a time is how a cutover acquires a long tail of
latent bugs; this ledger is the class.

## 1. Already generation-aware

| site | what |
|---|---|
| `application/results.py:341` | plan-side Wave-E parent: `validate_plan_chain_shape` → v1 opgraph / v2 workloadgraph |
| `application/results.py:622` | result-vs-plan generation check, exact result field set per generation |
| `application/results.py:643` | re-derivation dispatches through `chain_ids_from_traffic` |
| `application/wave_e_resources.py:245` | `wave_e.wave_d_chain` must cite the plan's **same** generation |
| `application/waved_resources.py:233` | `load_verified_workload_graph` strict + id recomputation |

## 2. Live v1 writer — correct today, switches in 4b §27

| site | what |
|---|---|
| `application/service.py:197` | the real chain builder: `waved_chain_ids(workload_decl, graph, logical, traffic, bundle)` |
| `application/service.py:176,178,181` | persists `wavedsemantics` / `wavedworkload` / `opgraph` — must stop (§29) |
| `application/service.py:645` | `_evaluate_waved` reads `chain["physical_traffic_id"]` — generation-neutral, no change |

### Correction

An earlier revision of this ledger listed `service.py:1000` as a writer
site. It is not: line 1000 is inside **`_derive_wave_e_block`**, i.e. the
execution/result path, and it is therefore reclassified below as 3.4. The
misclassification came from reading the line number without checking the
enclosing function — the same shortcut that produced the original
one-site-at-a-time fix.

## 3. CLOSED in 06e37487 — NetworkWindowBinding gained a generation

Found by this audit as four sites that would break the first v2 plan.
Closed by `2c.4b interlock: NetworkWindowBinding gains a generation`:
the dataclass field is `workload_parent_id` (not a v1 name holding a v2
value), the binding declares `schema_version` with absence meaning v1,
v1 serialization is byte-identical, and all four sites dispatch on the
plan chain's generation. Pins flipped from "gap" to "closed contract" in
`tests/test_v2_cutover_gaps.py` (13 tests, mutation tested: 6 mutations,
all bite).

Sites as found:

### 3.1 `wave_e_resources.py:332` — Wave-E result verification

```python
("operation_graph_id", plan_wave_d["operation_graph_id"]),
```

Compares the rebuilt `NetworkWindowBinding.operation_graph_id` against the
plan chain. On a v2 chain this is a `KeyError`, not a refusal. Needs a
generation-aware parent comparison (the binding is *about* a traffic
artifact and a chain; which key names its parent is a schema question,
see 3.3).

### 3.4 `service.py:1000` — `_derive_wave_e_block` builds the binder's chain

```python
chain={
    "operation_graph_id": chain["operation_graph_id"],
    "physical_traffic_id": chain["physical_traffic_id"],
    "backend_config_hash": run_evidence.backend_config_hash,
    "backend_input_hash": ...,
}
```

This is the CALLER of `bind_network_window`, and it reads
`chain["operation_graph_id"]` from the plan chain before the binder is
reached. On a v2 plan it is a `KeyError` during Wave-E result derivation,
upstream of 3.2. It also documents that the binder's `chain` argument is
NOT the raw plan chain: backend hashes are merged in by the caller, which
is what the pins for 3.2 must supply to be discriminating.

### 3.2 `wavee/network.py:171` — `bind_network_window` construction

```python
operation_graph_id=str(chain["operation_graph_id"]),
```

The function's own docstring types `chain` as "the Wave-D plan chain block
(physical_traffic_id, operation_graph_id, backend hashes)". A v2 chain has
no `operation_graph_id`, so binding a network window for a v2 plan raises
`KeyError`. Pinned by `test_v2_cutover_gaps.py`.

### 3.3 `wavee/network.py:49,61,83,98` — `NetworkWindowBinding` SCHEMA

This is the one that is not a read. `NetworkWindowBinding` is a persisted,
strictly-parsed structure whose **first field is `operation_graph_id`**:

- dataclass field (`:49`)
- `to_dict()` (`:61`)
- `from_dict()` `allowed` set (`:83`) — refuses any other field set
- `from_dict()` construction (`:98`)

It participates in `stats_sha256` and result identity. Consequences for 4b:

1. A v2 plan cannot express its ancestry in this binding at all — the
   schema refuses it before any value is compared.
2. The obvious "rename the field" fix is **rejected**: that is the
   mirror image of the cosmetic-v1 trap. The binding authenticates a
   *chain generation*; its schema must say which generation it is, not
   carry a v1 field name that happens to hold a v2 value.
3. Therefore this subsystem needs its own explicit binding generation
   (`NETWORK_BINDING_SCHEMA_VERSION_V1/V2`, absence → v1) exactly as the
   chain, message and traffic artifacts do.
4. The architect's plan covers plan chain (§34–37) and
   `waved_execution_block` (§36) but does not name this structure; it was
   found by this audit.

## 4. Historical readers — correct, do not change

| site | what | owner |
|---|---|---|
| `workload/messages.py:356-386` | v1 message strict reader | 2c.9 extraction |
| `workload/graph.py:258`, `workload/operations.py:376` | v1 opgraph/semantics strict readers | 2c.9 |
| `application/waved_resources.py:229` | `load_verified_operation_graph` | 2c.9 |
| `application/waved_resources.py:515-535` | `waved_chain_ids_from_traffic` → `_workload_from_graph` | 2c.9 |
| `application/waved_resources.py:420` | `waved_chain_ids` (v1 chain builder) | 2c.9 |

`_workload_from_graph` reconstructs a `WaveDWorkload` from side lists. It
is correct **only** for v1 and must never be reached from a v2 artifact;
after 4b it is reachable only through the historical v1 loader.

## 5. Interlock that constrains the writer switch

4b may not flip writers until the network-window path is
generation-aware, because a v2 plan produces a v2 chain and that path
consumes it in four places before any of the new science is compared.

```
chain generation aware            done (2c.4a, db0a17f6)
NETWORK BINDING generation        done (06e37487)   <-- this audit
  → messages v2 + traffic v2 + dual loaders        <-- remaining
  → MappingArtifact as a persisted authority       <-- target-model review
  → evidence-authentication decision               <-- target-model review
  → writer switch (§27)
  → 4c differential proof
```

## 6. Evidence-quality findings (mutation tested)

Every pin in `tests/test_v2_cutover_gaps.py` was mutation tested: the
production site was broken, the pin had to fail, and each mutation was
verified to actually apply (an earlier pass silently applied none, and a
`git checkout` restore used a wrong path and left the mutation in place).

Three consequences for earlier evidence:

1. **The 2c.4a tamper/transplant tests do not pin the loader.** They pass
   with BOTH `WorkloadGraph.from_dict(doc, strict=True)` relaxed to
   `from_dict(doc)` AND `load_verified_workload_graph`'s own
   `_require_equal("workload_id", ...)` deleted. The forgery is caught one
   layer down, inside `WorkloadGraph.from_dict`, which recomputes identity
   from content itself; `_parse` surfaces it. So:
   - `_require_equal` is redundant belt-and-braces (harmless, kept);
   - `strict=True` guards **extra-key tolerance**, not identity;
   - the earlier report that "the loader recomputes the embedded id so a
     forged document cannot pass" described a line that no test can
     distinguish.
2. **`chain_ids_from_traffic` was never mutation tested.** The 4a
   dispatcher is exercised only through v1 traffic, so its v2 branch is
   unproven — the same gap that seam 0.1 turned out to have.
3. Pins 3.1 and 3.4 are structural (source inspection) rather than
   behavioural, because driving them needs a persisted v2 plan. They do
   bite on verified mutations, but they are weaker evidence than the
   3.2/3.3 pins, which drive real objects.
