# Profile ingestion — bringing a customer's measured model

`veritx_dse.performance.profile_ingest` turns a **customer-supplied**
profile document into the same first-class `ModelProfile` the evaluators
already consume from the repo's own profiler CSVs.

That is the whole customer story for compute: a customer measures their
model on their silicon, writes the numbers down in the documented format,
and the product derives per-layer compute stages from them. No code change
and no hand-written `compute` block.

## Schema `veritx.model-profile/1`

```json
{
  "schema": "veritx.model-profile/1",
  "model": "astr-llm-70b",
  "hardware": "ASTRA-AC-1",
  "variant": "bf16",
  "tp": 4,
  "ep": 1,
  "source": "customer silicon run 2026-03-14, 512-token decode",
  "layers": [
    {"index": 0, "kind": "attention", "duration_ns": 61200,
     "input_bytes": 16384, "weight_bytes": 83886080, "output_bytes": 16384},
    {"index": 0, "kind": "dense_ffn", "duration_ns": 214400,
     "input_bytes": 16384, "weight_bytes": 352321536, "output_bytes": 16384},
    {"index": 1, "kind": "attention", "duration_ns": null,
     "missing": "not measurable at tp4 on this silicon revision"}
  ]
}
```

| field | meaning |
|---|---|
| `model` / `hardware` / `variant` | free-text identity, carried into the profile |
| `tp` / `ep` | the parallelism the numbers were measured at |
| `source` | provenance string, recorded as the profile's weight source |
| `layers[].index` | layer number; indexes must be `0..N-1` without gaps |
| `layers[].kind` | `attention` \| `dense_ffn` \| `moe` |
| `layers[].duration_ns` | measured duration, **or** an explicit `null` |
| `layers[].missing` | required when `duration_ns` is `null` |

## The contract

This is the same fail-closed law as the rest of the product.

- **Unknown keys refuse** at both the document and layer level. A typo is
  an error, never silently ignored.
- **`duration_ns` is required on every layer.** A layer that omits it
  refuses — absence must be *stated*, because a missing key silently
  defaulting to `0` would turn "we did not measure this" into "this is
  free".
- **`null` must carry a `missing` reason.** An absence is a statement.
- **A measured layer may not also claim to be missing.**
- **Byte fields must be non-negative integers**; `tp`/`ep` must be >= 1.
- Anything unavailable makes the profile `complete == False`, and
  `to_compute_intent()` **refuses** rather than emitting a stage with an
  invented duration.

`null` + `missing` survives all the way to the top: the profile is
incomplete, the compute intent refuses, and the caller must decide. A
partial customer measurement never becomes a partial-looking number.

## Shipping one

Profiles live under `tracks/t3-topology/examples/profiles/`. Reference one
from a workload-registry entry (see
[workload-registry.md](workload-registry.md)) and its `compute` block is
derived automatically:

```json
{
  "workload_id": "astr-llm-70b-tp4",
  "path": "tracks/t3-topology/examples/astr_llm_70b_tp4-v4.json",
  "profile": "tracks/t3-topology/examples/profiles/astr-llm-70b-profile.json",
  "owners": 4
}
```

`owners` is the participant count the stages are distributed over.

Shipped examples:

- `astr-llm-70b-profile.json` — complete; drives the live `astr-llm-70b-tp4`
  catalog workload.
- `astr-llm-70b-profile-partial.json` — carries an explicit absence;
  demonstrates the refusal path.

## What is still missing

- The profile supplies **compute** and per-layer operand **bytes**. It does
  not yet supply a memory-timing contract, so the DRAM leg's cost is driven
  by `weight_bytes` (see [memory-scaling.md](memory-scaling.md)).
- There is no upload endpoint: a customer document is committed to the tree
  or placed on disk. See workload-registry.md for the same caveat.
