# VeritX Examples

Sample CompileRequest JSON files for common AI workloads.

## Usage

```bash
# Run any example through the full compile pipeline
veritx compile examples/qwen3_moe_16npu.json

# Run with custom output
veritx compile examples/llama70b_tp64.json -o my_report.json

# Run as JSON (machine-readable)
veritx --json compile examples/qwen3_moe_16npu.json
```

## Files

| File | Model | Nodes | Description |
|------|-------|-------|-------------|
| `qwen3_moe_16npu.json` | Qwen3-30B-A3B | 20 | MoE decode, TP=16 EP=8, 16 NPU |
| `llama70b_tp64.json` | LLaMA-70B | 72 | Dense TP=64 ring allreduce |
| `llama1b_tp64.json` | LLaMA-1B | 68 | Dense TP=64 attention |
| `dense_64npu.json` | Generic dense | 72 | 64-NPU mesh |
| `moe_8npu.json` | Generic MoE | 10 | 8-NPU concentrated mesh |
| `_template.json` | — | — | Full template with all fields documented |

## Modifying

1. Copy any example: `cp qwen3_moe_16npu.json my_config.json`
2. Edit the fields you want to change
3. Run: `veritx compile my_config.json`

Key fields to change:
- `workload.trace_path` — point to your trace file
- `workload.tp` / `workload.ep` — change parallelism
- `agents[].count` — change number of compute tiles
- `noc_config.topology_family` — change topology (mesh/torus/gec)
- `dependencies` — add blocking cycles to trigger VC derivation
