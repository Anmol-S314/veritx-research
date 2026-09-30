# Workload registry — workloads as data

The product catalog used to be a hardcoded 4-tuple in `product/service.py`,
so onboarding a workload meant editing source. It is now a registry:
`veritx_dse.product.workload_registry`.

- `BUILTIN_WORKLOADS` — the shipped real-model workloads. Their identity is
  frozen; the registry only **adds**. (Re-exported as `_WORKLOAD_TEMPLATES`
  for existing importers.)
- `tracks/t3-topology/workloads/registry.json` — schema
  `veritx.workload-registry/1`, loaded on top of the builtins.

## Registry document

```json
{
  "schema": "veritx.workload-registry/1",
  "workloads": [
    {
      "workload_id": "astr-llm-70b-tp4",
      "path": "tracks/t3-topology/examples/astr_llm_70b_tp4-v4.json",
      "display_name": "Astr-LLM-70B · TP4 · 9-tile mesh",
      "description": "customer workload (Astera Labs)",
      "profile": "tracks/t3-topology/examples/profiles/astr-llm-70b-profile.json",
      "owners": 4
    }
  ]
}
```

| field | required | meaning |
|---|---|---|
| `workload_id` | yes | catalog id |
| `path` | yes | request document, relative to the repo root |
| `display_name` / `description` | yes | catalog presentation |
| `profile` | no | measured profile document; its compute is DERIVED |
| `owners` | no | participant count for stage distribution (default 1) |

## Fail-closed rules

- **Unknown keys refuse** at the document and entry level.
- **A duplicate `workload_id` refuses.** A registry entry may never silently
  shadow a shipped workload — if you want to replace one, that is a
  deliberate change to `BUILTIN_WORKLOADS`, not a config override.
- **A profile may only attach to a v4 request.** `compute` is a v4 field;
  attaching a customer's numbers to a v2/v3 document would silently discard
  them, so it refuses instead.
- A missing workload document refuses at materialization time.

## The customer path, end to end

1. Customer measures their model → writes a profile document
   ([profile-ingestion.md](profile-ingestion.md)).
2. A registry entry points at a v4 request document **and** that profile.
3. The catalog materializes the request with `compute` derived from the
   measured profile — verified by
   `tests/test_workload_registry.py::test_customer_workload_is_compilable_and_certifies`,
   which compiles `astr-llm-70b-tp4` and asserts a PASS certificate.

## What is still missing

- No upload endpoint or per-tenant isolation: the registry is a file in the
  tree, so onboarding is "commit a file", not "call an API".
- `owners` is a declared placement, not scheduling science — stages are
  distributed round-robin over that many ranks.
