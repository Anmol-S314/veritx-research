# Deployment builder (model → hardware → intent)

Status: v1 implementation contract.

## Purpose

Let a user choose a model, hardware, and serving policy, preview feasibility,
and generate a v4 workload intent that becomes a project draft. The builder is
a thin layer over `deployment_intent.map_deployment_document`; it does not
re-model serving.

## Scope

- aggregated deployments only (`pd_type = null`)
- `pp_size = 1`
- one homogeneous instance group; `dp_instances` replicas share `dp_group`
- dense or MoE with `ep_size` in `{1, tp_size}`
- one LLMServingSim request trace from the tracked trace catalog
- user-supplied fabric topology (mesh side length in v1)

## Backend

### `GET /api/v1/catalog/deployment-models`

Scans `third_party/llmservingsim/configs/model/**/*.json` (excluding READMEs),
returns deterministic sorted entries:

```json
{
  "contract_version": 1,
  "models": [{
    "model_name": "Qwen/Qwen3-30B-A3B-Instruct-2507",
    "source": "third_party/llmservingsim/configs/model/Qwen/....json",
    "digest": "sha256:...",
    "model_family": "mixture_of_experts",
    "geometry": {"layers": 48, "hidden": 2048, "heads": 32, "kv_heads": 4,
                 "head_dim": 128, "experts": 128, "top_k": 8,
                 "dtype_bytes": 2}
  }]
}
```

### `GET /api/v1/catalog/deployment-hardware`

Merges tracked serving hardware profiles with declared datasheet entries.
B200 is declared because no profiler bundle exists:

```json
{
  "contract_version": 1,
  "hardware": [{
    "hardware_id": "B200",
    "display_name": "NVIDIA B200",
    "memory_bytes": 192000000000,
    "memory_bandwidth_bytes_per_s": 8000000000000,
    "link_bandwidth_bytes_per_s": 1800000000000,
    "provenance": "NVIDIA DGX B200 datasheet",
    "timing": "DATASHEET",
    "serving_profile": false
  }]
}
```

`timing` is `MEASURED` only when a profiler bundle exists; B200 is
`DATASHEET`, so the UI must say intent-only, no measured serving timing.

### `POST /api/v1/deployment-intent/preview`

Request:

```json
{
  "name": "Qwen3-30B on B200",
  "model_name": "Qwen/Qwen3-30B-A3B-Instruct-2507",
  "hardware": "B200",
  "tp_size": 2,
  "pp_size": 1,
  "ep_size": 2,
  "dp_instances": 1,
  "max_num_seqs": 32,
  "max_num_batched_tokens": 2048,
  "trace": "third_party/llmservingsim/workloads/example_trace.jsonl",
  "num_reqs": 10,
  "topology": {"kind": "mesh", "side_length": 2, "concentration": 1},
  "link_width_bits": 128,
  "hbm_controllers_per_rank": 0
}
```

Behavior:

- model must exist in the deployment-model catalog;
- hardware must exist in the deployment-hardware catalog;
- trace must exist in the serving trace catalog (no arbitrary paths);
- the builder constructs the LLMServingSim cluster document in memory
  (`dp_instances` instances, shared `dp_group` when > 1);
- calls `map_deployment_document`;
- assembles the request with the supplied topology;
- validates with `parse_request_doc` and `FabricCompiler().compile`.

Response:

```json
{
  "contract_version": 1,
  "status": "OK",
  "issues": [],
  "report": { "...": "deployment mapping report" },
  "request": { "...": "schema-4 request" },
  "compile": {"status": "COMPILED", "error": null}
}
```

Refusals return `status: "REFUSED"`, `request: null`, `compile: null`, and
the mapping report issues.

### Project creation

The client uses the existing endpoints:

1. `POST /projects` with `{name}` (no workload id).
2. `PUT /projects/{id}/draft` with `{request}` from the preview.
3. Navigate to the project workload/design page.

No new persistence endpoint is needed.

## UI

Root route `/builder` (`kind: "builder"`), reachable from the project picker
and the Experiments navigation.

Form:

- Model select (catalog; geometry shown).
- Hardware select (catalog; measured/datasheet badge).
- TP, EP, DP instances; PP fixed at 1 with a note.
- `max_num_seqs`, `max_num_batched_tokens`, trace select, `num_reqs`.
- Fabric: mesh side length, link width, HBM controllers per rank.

Behavior:

- debounced preview on change;
- report panel: status, issues, ranks, model geometry, derived volumes,
  assumptions (collapsed);
- request JSON (collapsed `details`);
- **Create project** enabled only when `status = OK`; creates the project,
  writes the draft, and navigates;
- empty/loading/error states.

## Verification

Backend tests:

- catalog entries are deterministic and complete;
- B200 is datasheet-only, no measured timing claim;
- preview for Qwen3-30B-A3B TP2 EP2 on B200 compiles;
- PD is not offered; `pp_size != 1` refuses;
- arbitrary trace paths refuse;
- unknown model/hardware refuses.

Frontend contract tests:

- form state maps to the exact preview body;
- refusal report renders issues and disables creation;
- OK report renders derived volumes and enables creation;
- create calls `POST /projects` then `PUT /draft` in that order.
