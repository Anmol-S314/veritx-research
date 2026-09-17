#!/usr/bin/env python3
"""End-to-end HF config.json -> Timeloop -> Booksim traffic-matrix pipeline.

Canonical Timeloop pipeline (Phase 3b: the legacy YAML-schedule
run_timeloop_pipeline.py is retired — a stub pointing here). Op shapes are
DERIVED from an HF config.json + tile count via MegatronTPStrategy, not read
from a fixed experiment_configs/*.yaml.

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
import os
import re
from pathlib import Path

from model_spec import load_model_spec
from mapping_strategy import MegatronTPStrategy
from timeloop_runner import TimeloopRunner, shape_tag
from traffic_matrix import build_stage_traffic_matrices, write_matrix, STAGES
from noc_energy_bridge import get_pj_per_hop

ROOT = Path(__file__).resolve().parent.parent  # tracks/t3-topology
TIMELOOP_DIR = ROOT / "timeloop"
RESULTS_ROOT = ROOT / "results"


def _results_root() -> Path:
    """Output root, honoring T3_RESULTS (claim-3 fix).

    T3_RESULTS points at a config dir (results/<CONFIG>); spatial outputs
    live BESIDE configs as <root>/<base>_N<n>, so the parent is the root.
    Unset → the default above. Pure path math, no I/O (testable).
    """
    t3r = os.environ.get("T3_RESULTS")
    if t3r:
        return Path(t3r).parent
    return RESULTS_ROOT


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


def apply_noc_join(spatial_rows, est, bytes_per_flit, accelergy_dir):
    """Attach the NoC-energy join to each spatial summary row (additive).

    est: {"total": pj/hop, "components": {...}} from get_pj_per_hop(), or
    None when Accelergy was unavailable — rows then carry status "skipped"
    with the reason instead of fabricated numbers. Pure function over the
    rows (no I/O) so the join math is unit-testable without running
    Timeloop or Accelergy. Returns (ok: bool).
    """
    if est is None or est.get("total") is None:
        reason = est.get("reason", "unknown") if isinstance(est, dict) else "unknown"
        for r in spatial_rows:
            r["noc"] = {"status": "skipped", "reason": reason,
                        "traffic_bytes_total": r["traffic_bytes_total"]}
        return False
    pj_per_hop = est["total"]
    for r in spatial_rows:
        # flits = bytes / bytes_per_flit: unit conversion with a STATED
        # flit-size assumption (--bytes-per-flit, default 128-bit links).
        total_flits = r["traffic_bytes_total"] / bytes_per_flit
        r["noc"] = {
            "status": "ok",
            "traffic_bytes_total": r["traffic_bytes_total"],
            "bytes_per_flit": bytes_per_flit,
            "total_flits": total_flits,
            "pj_per_hop": pj_per_hop,
            "pj_per_hop_components": est["components"],
            "noc_energy_pj_per_hop": round(total_flits * pj_per_hop, 4),
            "method": "total_flits * pj_per_hop; multiply by topology "
                      "hops_avg for system NoC energy (this pipeline is "
                      "topology-agnostic)",
            "accelergy_source": str(Path(accelergy_dir) / "energy_estimation.yaml"),
        }
    return True


def normalize_base_name(name: str) -> str:
    """Strip chained tile suffixes so re-picking an output dir can't grow
    `baseline_N16_N16_N32`-style chains: every run writes
    results/<base>_N<n>, where <base> never ends in _N<n> itself.

    Strips ALL trailing _N<digits> groups (`baseline_N16_N16` -> `baseline`);
    empty result falls back to "run". Pure function, unit-tested below in
    spirit (see selfcheck-less scripts: covered by contract test).
    """
    base = re.sub(r"(_N\d+)+$", "", str(name).strip())
    return base or "run"


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
    ap.add_argument("--bytes-per-flit", type=int, default=16,
                     help="Bytes per NoC flit for the NoC-energy join (default 16 = "
                          "128-bit links; stated assumption, not measured — see "
                          "the noc.* method note in the summary)")
    args = ap.parse_args()

    config_name = normalize_base_name(args.config_name or Path(args.model_config).stem)
    if config_name != (args.config_name or Path(args.model_config).stem):
        print(f"  note: config base normalized to {config_name!r} "
              f"(tile suffixes belong to output dirs, not the base name)")
    results_root = _results_root()
    if results_root != RESULTS_ROOT:
        print(f"  note: output root {results_root} (from T3_RESULTS)")

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

    spatial_rows = []
    for n in args.tiles:
        print(f"\n=== {config_name} N={n} ===")
        results_dir = results_root / f"{config_name}_N{n}"
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
        energy_pj = sum(inst * val for _, inst, val in runner.op_energy_pj()
                        if val is not None)
        # Raw whole-model byte volume, summed IN MEMORY before write_matrix:
        # immune to --no-normalize (row-normalized files would make sums
        # meaningless). Includes softmax_dram_bytes ESTIMATES (Pass 1 has no
        # Timeloop stats for softmax) — counted, flagged below, never silent.
        raw_full_layer_bytes = float((matrices["full_layer"] * model_spec.num_layers).sum())
        softmax_ops = [op for op in program.ops if op.op_template == "softmax"]
        spatial_rows.append({"tiles": n, "op_instances": len(program.ops),
                             "real_ops": len(real_ops),
                             "unique_runs": runner.num_unique_runs,
                             "total_energy_pj": energy_pj,
                             "compute_energy_pj": energy_pj,
                             "traffic_bytes_total": raw_full_layer_bytes,
                             "softmax_ops_estimated": len(softmax_ops),
                             "dir": str(results_dir)})
        print(
            f"  total op instances={len(program.ops)} (real Timeloop ops={len(real_ops)})  "
            f"unique Timeloop runs={runner.num_unique_runs}  "
            f"-> {results_dir}"
        )

    print("\n=== Spatial summary (best-mapping energy per tile count) ===")
    print(f"  {'tiles':>6} {'ops':>5} {'unique':>7} {'energy_pJ':>14}")
    print("  " + "─" * 36)
    for r in spatial_rows:
        print(f"  {r['tiles']:>6} {r['real_ops']:>5} {r['unique_runs']:>7} "
              f"{r['total_energy_pj']:>14.3g}")

    # ---- NoC energy join (Phase 3c) -------------------------------------
    # The spatial pipeline is topology-agnostic: it measures traffic VOLUME
    # (bytes) but never hop counts, so a topology-specific NoC energy is
    # uncomputable here — and never fabricated. What IS joined honestly:
    #   noc_energy_pj_per_hop = total_flits * pj_per_hop
    # (Accelergy-calibrated per-flit-per-hop coefficient, one run for the
    # whole sweep since it depends on tech, not tile count). Consumers
    # multiply by their topology's hops_avg (e.g. from topology_sweep.json)
    # for system NoC energy. total_energy_pj/compute_energy_pj stay
    # compute-only; the two must never be summed naively (byte vs flit-hop
    # units, and per-hop vs topology-specific).
    accelergy_dir = results_root / f"{config_name}_spatial_accelergy"
    try:
        est = get_pj_per_hop(out_dir=accelergy_dir)
        est_reason = None
    except RuntimeError as e:
        est, est_reason = {"total": None, "components": {}, "reason": str(e)}, str(e)
        print(f"  WARNING: NoC energy join skipped: {e}")
        print("  (compute energy above is unaffected; noc.* rows carry the reason)")
    noc_ok = apply_noc_join(spatial_rows, est, args.bytes_per_flit, accelergy_dir)
    for r in spatial_rows:
        if r["softmax_ops_estimated"]:
            print(f"  WARNING: N={r['tiles']}: {r['softmax_ops_estimated']} softmax ops use "
                  f"softmax_dram_bytes ESTIMATES (no Timeloop stats) — included in "
                  f"traffic_bytes_total, excluded from compute energy")
    if noc_ok:
        print(f"  NoC: pj/hop = {est['total']} "
              f"({', '.join(f'{k}={v}' for k, v in est['components'].items())}) "
              f"— per-hop; x hops_avg for system NoC energy")

    summary_path = results_root / f"{config_name}_spatial_summary.json"
    summary_path.write_text(json.dumps(spatial_rows, indent=2))
    print(f"  saved {summary_path.name}")
    print("\nDone.")


if __name__ == "__main__":
    main()
