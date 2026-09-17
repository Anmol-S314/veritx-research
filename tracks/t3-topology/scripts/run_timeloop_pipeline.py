#!/usr/bin/env python3
"""RETIRED (Phase 3b unification): use scripts/run_spatial_pipeline.py instead.

The legacy YAML-schedule pipeline (experiment_configs/*.yaml schedule[] +
problem_library templates, uncaptured mapper output, wiped operations/,
placeholder 60%-ring/40%-star matrix with hardcoded N=16) is superseded by
the spatial pipeline: argparse HF model configs, captured mapper.log,
memoized unique-shape runs, real DRAM+ring_allreduce traffic.

No silent forward: flags, env vars, and output schemas differ, so an
automatic redirect would mislead. Migrate explicitly:

    python3 scripts/run_spatial_pipeline.py \\
        --model-config timeloop/experiment_configs/llama_7b_hf_config.json \\
        --tiles 16 --seq-len 2048

or via the wrapper:  t3 timeloop   (same defaults + "$@" passthrough)
"""
import sys

sys.stderr.write(
    "retired: scripts/run_timeloop_pipeline.py was removed in the Phase 3b\n"
    "unification. Use the spatial pipeline instead:\n"
    "\n"
    "  python3 scripts/run_spatial_pipeline.py \\\n"
    "      --model-config timeloop/experiment_configs/llama_7b_hf_config.json \\\n"
    "      --tiles 16 --seq-len 2048\n"
    "\n"
    "or:  t3 timeloop [extra spatial flags]\n"
)
sys.exit(2)
