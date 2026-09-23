# VeritX Examples

Editable, canonical **CompileRequest** JSON documents (PRD §11.1, E1–E5)
for common AI workloads.

These files are the low-level design-intent schema: workload, requirements,
agents, dependency graph, NocConfig, address map and physical context.
They are useful as model/schema examples, as fixtures for the canonical
`schema_version: 2` / `compiler_semantics_version: 2` identity model, and
as inputs to low-level tooling and research commands.

They deliberately carry **no** `design_hash` / `guardrail_hash`: those are
computed values, so embedding them would make a copied-and-edited file
fail to reparse.

## Canonical product compile

The canonical `veritx compile` command does **not** take a CompileRequest
path. It takes a declared **CompileIntent**: a named fabric preset plus
optional typed overrides, an explicit candidate policy, and an explicit
resource store.

```bash
# Resolve a named preset to a committed canonical design
veritx compile \
  --preset mesh4 \
  --policy baseline_deterministic_v2 \
  --store runs/canonical-store

# Preset with typed overrides (values are strict JSON scalars: quote strings)
veritx compile \
  --preset mesh4 \
  --policy baseline_deterministic_v2 \
  --store runs/canonical-store \
  --set noc_config.link_width=128 \
  --set 'noc_config.arbitration="rr"'

# Compile an exact persisted CompileIntent snapshot
veritx compile \
  --intent my-intent.json \
  --store runs/canonical-store

# Machine-readable summary
veritx --json compile --preset mesh4 \
  --policy baseline_deterministic_v2 --store runs/canonical-store
```

The command reports a structural state only (`Compile state: RESOLVED`).
Backend execution (BookSim) and verification are separate, later stages
and are **not** performed by `veritx compile`.

Preset names come from the application preset registry; policy values come
from the closed candidate-policy vocabulary. An arbitrary CompileRequest
JSON file is **not** an accepted `veritx compile` input — there is no
implicit conversion from a low-level request to a product declaration.

## Files

| File | Model | Nodes | Description |
|------|-------|-------|-------------|
| `qwen3_moe_16npu.json` | Qwen3-30B-A3B | 20 | MoE decode, TP=16 EP=8, 16 NPU |
| `llama70b_tp64.json` | LLaMA-70B | 72 | Dense TP=64 ring allreduce |
| `llama1b_tp64.json` | LLaMA-1B | 68 | Dense TP=64 attention |
| `dense_64npu.json` | Generic dense | 72 | 64-NPU mesh |
| `moe_8npu.json` | Generic MoE | 10 | 8-NPU concentrated mesh |
| `_template.json` | — | — | Full template with all fields documented |

## Using these documents

These documents are valid inputs to the canonical `CompileRequest` schema
(`CompileRequest.from_dict`), which is the authority for the E1–E5 model:

```python
import json
from veritx_dse.model.compile_model import CompileRequest

request = CompileRequest.from_dict(json.loads(open("moe_8npu.json").read()))
print(request.design_hash())
```

To modify one:

1. Copy any example: `cp qwen3_moe_16npu.json my_config.json`
2. Edit the fields you want to change
3. Parse it with `CompileRequest.from_dict()` (identity is recomputed, so
   there is no stale hash to update)

Key fields to change:
- `workload.trace_path` — point to your trace file
- `workload.tp` / `workload.ep` — change parallelism
- `agents[].count` — change number of compute tiles
- `noc_config.topology_family` — change topology (mesh/torus/gec)
- `dependencies` — add blocking cycles to trigger VC derivation
