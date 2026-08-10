#!/usr/bin/env python3
"""End-to-end HF config.json -> Timeloop -> Booksim traffic-matrix pipeline.

Lives in scripts/, alongside run_timeloop_pipeline.py -- named
run_spatial_pipeline.py to avoid overwriting the existing script (different
scheduling paradigm: op shapes DERIVED from an HF config.json + tile count
via MegatronTPStrategy, not read from a fixed experiment_configs/*.yaml).

Usage:
    python run_spatial_pipeline.py \\
        --model-config timeloop/experiment_configs/llama_7b_hf_config.json \\
        --tiles 16 32 64 72 \\
        --seq-len 2048

Per tile count N, writes results/<config_name>_N<N>/:
    execution.json
    operations/<shape_tag>/{stats.txt, map.txt, map+stats.xml, used_by.json}
        -- ONE folder per unique (op_template, M/N/K) shape, not per tile/
        head instance. used_by.json lists every op_id + tile_id this one
        Timeloop run stands in for.
    traffic_matrices/per_layer/{qkv_proj,attention,out_proj,gate_up_proj,down_proj,full_layer}.txt
    traffic_matrices/whole_model/{...same five + full_layer...}.txt
        -- per_layer * num_layers (steady-state single-layer replay
        assumption, plan.md Section 8)
    traffic_matrix.txt -- alias for traffic_matrices/whole_model/full_layer.txt,
        in case existing tooling (booksim-ext, configs/*.cfg) hardcodes this name.

See README.md "Traffic matrix formats" for what each stage matrix contains.
"""
import argparse
import json
from pathlib import Path

from model_spec import load_model_spec
from mapping_strategy import MegatronTPStrategy
from timeloop_runner import TimeloopRunner, shape_tag
from traffic_matrix import build_stage_traffic_matrices, write_matrix, STAGES

ROOT = Path(__file__).resolve().parent.parent  # tracks/t3-topology
TIMELOOP_DIR = ROOT / "timeloop"
RESULTS_ROOT = ROOT / "results"


def write_execution_json(program, results_dir):
    """Same operations[] schema run_timeloop_pipeline.py already writes,
    but stats_file now points at the shared shape folder (operations/
    <shape_tag>/stats.txt), since many op_ids can point at the same file."""
    execution_json = {"operations": []}
    for op in program.ops:
        if op.op_template == "softmax":
            stats_file = None
        else:
            stats_file = f"operations/{shape_tag(op.op_template, op.shape)}/stats.txt"
        execution_json["operations"].append({
            "name": op.op_id,
            "op_template": op.op_template,
            "tile_id": op.tile_id,
            "repeat": 1,
            "stats_file": stats_file,
        })
    with open(results_dir / "execution.json", "w") as f:
        json.dump(execution_json, f, indent=4)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-config", required=True, help="HF config.json path")
    ap.add_argument("--config-name", default=None,
                     help="Base name for results/<config-name>_N<N>/ (default: derived from --model-config filename)")
    ap.add_argument("--tiles", type=int, nargs="+", default=[16, 32, 64, 72])
    ap.add_argument("--seq-len", type=int, required=True)
    ap.add_argument("--dtype-bytes", type=int, default=2, help="bytes/element (2=bf16/fp16, 4=fp32)")
    ap.add_argument("--problem-template", default="gemm.yaml",
                     help="Filename under timeloop/problem_library/ used for every op")
    ap.add_argument("--no-normalize", action="store_true",
                     help="Write raw byte counts instead of row-normalized weights")
    args = ap.parse_args()

    config_name = args.config_name or Path(args.model_config).stem

    model_spec = load_model_spec(args.model_config, seq_len=args.seq_len, dtype_bytes=args.dtype_bytes)
    print(
        f"Loaded model spec: hidden={model_spec.hidden_size} heads={model_spec.num_heads} "
        f"kv_heads={model_spec.num_kv_heads} head_dim={model_spec.head_dim} "
        f"ffn={model_spec.ffn_intermediate_size} layers={model_spec.num_layers} "
        f"seq_len={model_spec.seq_len} dtype_bytes={model_spec.dtype_bytes}"
    )
    if model_spec.num_kv_heads != model_spec.num_heads:
        print(
            "WARNING: GQA detected (num_key_value_heads != num_attention_heads). "
            "v1's MegatronTPStrategy assumes plain MHA -- treat results as "
            "approximate until GQA-aware K/V sharing is added."
        )

    strategy = MegatronTPStrategy()

    for n in args.tiles:
        print(f"\n=== {config_name} N={n} ===")
        results_dir = RESULTS_ROOT / f"{config_name}_N{n}"
        results_dir.mkdir(parents=True, exist_ok=True)

        program = strategy.map(model_spec, n)
        write_execution_json(program, results_dir)

        runner = TimeloopRunner(TIMELOOP_DIR, results_dir, problem_template=args.problem_template)
        matrices = build_stage_traffic_matrices(program, runner, model_spec.dtype_bytes)
        runner.write_manifests()

        per_layer_dir = results_dir / "traffic_matrices" / "per_layer"
        whole_model_dir = results_dir / "traffic_matrices" / "whole_model"
        per_layer_dir.mkdir(parents=True, exist_ok=True)
        whole_model_dir.mkdir(parents=True, exist_ok=True)

        for name, mat in matrices.items():
            write_matrix(mat, per_layer_dir / f"{name}.txt", normalize=not args.no_normalize)
            write_matrix(mat * model_spec.num_layers, whole_model_dir / f"{name}.txt",
                         normalize=not args.no_normalize)

        # Legacy alias for anything hardcoding this filename.
        write_matrix(matrices["full_layer"] * model_spec.num_layers,
                     results_dir / "traffic_matrix.txt", normalize=not args.no_normalize)

        real_ops = [op for op in program.ops if op.op_template != "softmax"]
        print(
            f"  total op instances={len(program.ops)} (real Timeloop ops={len(real_ops)})  "
            f"unique Timeloop runs={runner.num_unique_runs}  "
            f"-> {results_dir}"
        )

    print("\nDone.")


if __name__ == "__main__":
    main()
