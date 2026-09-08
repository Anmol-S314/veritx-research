#!/usr/bin/env python3
"""LLaMA-7B Execution Runner via ASTRA-Sim 2.0 + BookSim 2.0.

Shortcut wrapper around run_astrasim.py for LLaMA-7B model workload execution across
T3 NoC topologies using Tensor Parallelism (TP=4) and Pipeline Parallelism (PP=4).

Outputs:
  - results/$(CONFIG)/llama7b_sweep.json
  - Updates results/$(CONFIG)/topology_sweep.json for Pareto analysis

Usage:
  python3 scripts/run_llama7b.py --config baseline
  python3 scripts/run_llama7b.py --selfcheck
"""

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
TRACK = HERE.parent
CONFIGS_DIR = TRACK / "configs"
RESULTS_DIR = TRACK / "results"

from generate_chakra_trace import ChakraTraceGenerator
from run_astrasim import run_astrasim_topology


def get_llama7b_workload_spec() -> dict:
    """Return LLaMA-7B architectural and communication workload specs via ChakraTraceGenerator."""
    gen = ChakraTraceGenerator()
    spec = gen.resolve_spec("llama7b")
    spec["model"] = "LLaMA-7B"
    return spec


def _selfcheck():
    spec = get_llama7b_workload_spec()
    assert spec["model"] == "LLaMA-7B"
    assert spec["msg_size_mb"] == 32.0, f"Expected 32MB, got {spec['msg_size_mb']}"
    assert spec["total_allreduce_calls"] == 64, f"Expected 64 calls, got {spec['total_allreduce_calls']}"
    print("selfcheck OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="baseline", help="configuration name (e.g. baseline)")
    ap.add_argument("--selfcheck", action="store_true", help="Run internal selfcheck")
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    gen = ChakraTraceGenerator()
    spec = gen.resolve_spec("llama7b")

    out_res_dir = RESULTS_DIR / args.config
    out_res_dir.mkdir(parents=True, exist_ok=True)

    configs = sorted(CONFIGS_DIR.glob("*.cfg"))
    results = []

    print(f"=== LLaMA-7B ASTRA-Sim + BookSim Runner ===")
    print(f"  Parallelism Strategy : Tensor Parallel (TP=4), Pipeline Parallel (PP=4)")
    print(f"  All-Reduce Call Size : {spec['msg_size_mb']:.1f} MB (64 calls total across 32 layers)\n")

    for cfg in configs:
        print(f"  Running LLaMA-7B on {cfg.stem:<12} ...", end=" ", flush=True)
        r = run_astrasim_topology(cfg, spec, args.config)
        print(f"{r['astrasim_cycles']:>7} cycles  |  Comm Overhead: {r['comm_overhead_pct']:>5.1f}%  ({r['status']})")
        results.append(r)

    out_json = out_res_dir / "llama7b_sweep.json"
    out_json.write_text(json.dumps(results, indent=2))

    out_sweep = out_res_dir / "topology_sweep.json"
    out_sweep.write_text(json.dumps(results, indent=2))

    print(f"\n  ✓ {len(results)} LLaMA-7B topology records → {out_json}")
    print(f"  ✓ Integrated sweep results → {out_sweep}")


if __name__ == "__main__":
    main()

