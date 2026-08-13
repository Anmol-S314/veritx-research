#!/usr/bin/env python3
"""Gate R1 extended: TPUv4-with-BookSim vs TPUv3-with-BookSim (prefill).

FINDINGS.md "What is still soft": TPUv3 is the only config that ships with
booksim2; v4 uses simple_noc. v4: 4 systolic arrays (vs 2), core 1050 MHz
(vs 940), DRAM 1200 MHz (vs 940) — more compute per byte => more NoC
pressure. Question: does the mesh-vs-fattree verdict move?

Method: BERT encoder block (12 heads, d_model 768, seq 512, fp32) lowered
with torch.compile onto npu:0, TOGSim with booksim2 config (same
booksim_config_path for both). TOGSim results land in togsim_results/
inside the container; this script copies the cycle counts out.

Usage (inside torchsim-ci image):
    python3 scripts/tpu_v3_v4.py            # run both, print cycle table
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import time

import torch

CONFIGS = {
    "v3": "/work/configs/systolic_ws_128x128_c1_booksim_tpuv3_timing_only.yml",
    "v4": "/work/configs/systolic_ws_128x128_c1_booksim_tpuv4_timing_only.yml",
    "bisect_a": "/work/configs/systolic_ws_128x128_c1_booksim_tpuv4_timing_only_bisect_a.yml",
    "bisect_c": "/work/configs/systolic_ws_128x128_c1_booksim_tpuv3_timing_only_bisect_c.yml",
    "bisect_d": "/work/configs/systolic_ws_128x128_c1_booksim_tpuv3_timing_only_bisect_d.yml",
    "bisect_e": "/work/configs/systolic_ws_128x128_c1_booksim_tpuv3_timing_only_bisect_e.yml",
    "bisect_f": "/work/configs/systolic_ws_128x128_c1_booksim_tpuv4_timing_only_bisect_f.yml",
    "c2v3mesh": "/work/configs/systolic_ws_128x128_c2_booksim_tpuv3_timing_only_mesh.yml",
    "c2v4mesh": "/work/configs/systolic_ws_128x128_c2_booksim_tpuv4_timing_only.yml",
    "c2v3ft": "/work/configs/systolic_ws_128x128_c2_booksim_tpuv3_timing_only_ft.yml",
    "c2v4ft": "/work/configs/systolic_ws_128x128_c2_booksim_tpuv4_timing_only_ft.yml",
    "c2v3ft4": "/work/configs/systolic_ws_128x128_c2_booksim_tpuv3_timing_only_ft_vc4.yml",
    "c2v3ftislip": "/work/configs/systolic_ws_128x128_c2_booksim_tpuv3_timing_only_ft_islip.yml",
    "c2v4ft4": "/work/configs/systolic_ws_128x128_c2_booksim_tpuv4_timing_only_ft_vc4.yml",
    "c2v3fly64": "/work/configs/systolic_ws_128x128_c2_booksim_tpuv3_timing_only_fly64.yml",
    "c2v4fly64": "/work/configs/systolic_ws_128x128_c2_booksim_tpuv4_timing_only_fly64.yml",
    "c2v3torus": "/work/configs/systolic_ws_128x128_c2_booksim_tpuv3_timing_only_torus.yml",
    "c2v4torus": "/work/configs/systolic_ws_128x128_c2_booksim_tpuv4_timing_only_torus.yml",
    "c2v3meshl2": "/work/configs/systolic_ws_128x128_c2_booksim_tpuv3_timing_only_mesh_l2.yml",
    "c2v3flyl2": "/work/configs/systolic_ws_128x128_c2_booksim_tpuv3_timing_only_fly64_l2.yml",
    "c2v3mesh2x": "/work/configs/systolic_ws_128x128_c2_booksim_tpuv3_timing_only_mesh_icnt2x.yml",
    "c2v3fly2x": "/work/configs/systolic_ws_128x128_c2_booksim_tpuv3_timing_only_fly64_icnt2x.yml",
}
OUT = "/work/tpu_v3_v4_out"


def total_cycles(results_dir: str) -> int | None:
    """Pull Total_cycles from the freshest TOGSim result file (*.log/*.txt)."""
    files = sorted(glob.glob(f"{results_dir}/**/*.log", recursive=True)
                   + glob.glob(f"{results_dir}/**/*.txt", recursive=True),
                   key=os.path.getmtime)
    if not files:
        return None
    total = None
    for f in files:
        for line in open(f, errors="ignore"):
            m = re.search(r"Total_cycles (\d+)", line)
            if m:
                total = int(m.group(1))
    return total


def run_prefill(config_path: str, tag: str) -> dict:
    import torch_openreg  # noqa: F401  (register npu backend before device use)
    from Simulator import simulator

    results_dir = "/work/persist/togsim_results"
    shutil.rmtree(results_dir, ignore_errors=True)
    os.makedirs(results_dir)
    os.environ["TOGSIM_CONFIG"] = config_path
    os.environ["TORCHSIM_LOG_PATH"] = results_dir
    os.environ["TORCHSIM_DUMP_PATH"] = "/work/persist/outputs"

    t0 = time.time()
    with simulator.TOGSimulator(config_path=config_path):
        torch.manual_seed(1)
        d_model, heads, seq = 768, 12, 128
        # one BERT-base encoder block, batch 1, prefill-style (FINDINGS setup;
        # seq 128 for the first pass — the v3/v4 comparison is what matters)
        block = torch.nn.TransformerEncoderLayer(
            d_model=d_model, nhead=heads, dim_feedforward=3072,
            dropout=0.0, batch_first=True, activation="gelu").to("npu:0")
        x = torch.randn(1, seq, d_model, device="npu:0")
        y = torch.compile(block)(x)
        torch.npu.synchronize()
    dt = time.time() - t0

    cycles = total_cycles(results_dir)
    # keep the evidence: copy out the trace for provenance
    shutil.copytree(results_dir, f"{OUT}/{tag}_togsim", dirs_exist_ok=True)
    return {"tag": tag, "wall_s": round(dt, 1), "total_cycles": cycles}


def main():
    tags = sys.argv[1:] or list(CONFIGS)
    os.makedirs(OUT, exist_ok=True)
    results = []
    for tag in tags:
        print(f"--- {tag}: {CONFIGS[tag]} ---", flush=True)
        try:
            r = run_prefill(CONFIGS[tag], tag)
        except Exception as e:
            r = {"tag": tag, "error": str(e)}
        results.append(r)
        print(f"    {r}", flush=True)
    print("\n=== RESULTS ===")
    for r in results:
        print(f"  {r['tag']}: total_cycles={r.get('total_cycles')} "
              f"wall={r.get('wall_s')}s error={r.get('error', '-')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
