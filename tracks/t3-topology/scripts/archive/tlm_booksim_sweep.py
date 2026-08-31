#!/usr/bin/env python3
"""tlm_booksim_sweep.py — Run TLM + BookSim at multiple IRs for all 3 topologies,
produce a TLM-vs-BookSim divergence curve plot.

Usage:
  python3 tracks/t3-topology/scripts/tlm_booksim_sweep.py \
      --outdir .noc_p0/sweep --plot .noc_p0/sweep/divergence.png
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ── paths ──
SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parent.parent.parent
TLM_GEN = SCRIPT_DIR / "tlm_gen.py"
HYBRID = SCRIPT_DIR / "hybrid_vcsim.py"
MATRIX = str(REPO / "tracks/t3-topology/dse/inputs/qwen_moe_64d.mat")
TOPOS = {
    "custom_v2": str(REPO / ".noc_p0/custom_v2.anynet"),
    "mesh_8x8":  str(REPO / ".noc_p0/mesh_8x8.anynet"),
    "torus_8x8": str(REPO / ".noc_p0/torus_8x8.anynet"),
}
IRs = [0.04, 0.08, 0.16, 0.24, 0.32, 0.40]


def run_tlm(anynet: str, ir: float, outdir: Path, refine: bool = False) -> dict:
    """Generate + compile + run TLM model, return parsed JSON result."""
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(TLM_GEN),
           "--anynet", anynet,
           "--matrix", MATRIX,
           "--outdir", str(outdir),
           "--ir", str(ir)]
    if refine:
        cmd.append("--refine")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=str(REPO))
    if r.returncode != 0:
        return {"error": r.stderr[:300]}

    # compile
    mk = subprocess.run(["make", "-C", str(outdir)],
                        capture_output=True, text=True, timeout=120)
    if mk.returncode != 0:
        return {"error": mk.stderr[:300]}

    # run
    binary = outdir / "noc_tlm"
    if not binary.exists():
        return {"error": "binary not found", "avg_latency": None}
    try:
        rn = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "avg_latency": None}
    if rn.returncode != 0:
        return {"error": rn.stderr[:300], "avg_latency": None}

    # parse text output — may contain literal \n inside lines, so also split on those
    import re
    raw = rn.stdout
    # Normalize: split on both real newlines and literal backslash-n
    tokens = re.split(r'\\n|\n', raw)
    result = {}
    for tok in tokens:
        tok = tok.strip()
        m = re.match(r'^avg:\s+([\d.]+)', tok)
        if m: result["avg_latency"] = float(m.group(1)); continue
        m = re.match(r'^median:\s+([\d.]+)', tok)
        if m: result["median"] = float(m.group(1)); continue
        m = re.match(r'^p99:\s+([\d.]+)', tok)
        if m: result["p99"] = float(m.group(1)); continue
        m = re.match(r'^max:\s+([\d.]+)', tok)
        if m: result["max"] = float(m.group(1)); continue
        m = re.match(r'^max_rho:\s+([\d.]+)', tok)
        if m: result["max_rho"] = float(m.group(1)); continue
        m = re.match(r'^saturated_links:\s+(\d+)', tok)
        if m: result["saturated_links"] = int(m.group(1)); continue
    if result:
        return result
    return {"error": "could not parse TLM output", "avg_latency": None, "stdout_tail": rn.stdout[-500:]}


def run_booksim(anynet: str, ir: float) -> dict:
    """Run hybrid_vcsim and parse result. Adaptive cycles: fewer for high IR."""
    # Reduce cycles to avoid timeout (saturation = slow drain)
    cycles = 40000 if ir <= 0.24 else 25000 if ir <= 0.32 else 15000
    timeout = 60 if ir <= 0.24 else 90
    cmd = [sys.executable, str(HYBRID),
           "--anynet", anynet,
           "--matrix", MATRIX,
           "--ir", str(ir),
           "--cycles", str(cycles),
           "--mode", "hybrid",
           "--routing", "min"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(REPO))
    except subprocess.TimeoutExpired:
        return {"error": f"timeout ({timeout}s)", "avg_latency": None}
    if r.returncode != 0:
        return {"error": r.stderr[:300], "avg_latency": None}
    # BookSim outputs JSON — try to parse the whole block
    import re
    # Try full JSON parse first
    stdout = r.stdout.strip()
    if stdout.startswith("{"):
        try:
            d = json.loads(stdout)
            return {"avg_latency": d.get("avg_latency"), "ok": True,
                    "avg_hops": d.get("avg_hops"), "demotions": d.get("demotions", 0),
                    "max_latency": d.get("max_latency")}
        except json.JSONDecodeError:
            pass
    # Fallback: regex on individual lines
    for line in r.stdout.split("\n"):
        m = re.search(r'"?avg_latency"?\s*[:=]\s*([\d.]+)', line)
        if m:
            return {"avg_latency": float(m.group(1)), "ok": True}
    return {"error": "could not parse avg_latency", "avg_latency": None, "stdout": r.stdout[-500:]}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--outdir", default=".noc_p0/sweep")
    ap.add_argument("--plot", default=None, help="output PNG path")
    ap.add_argument("--irange", type=float, nargs=2, default=None,
                    help="override IR range [start, end]")
    ap.add_argument("--no-refine", action="store_true",
                    help="skip contention refinement (faster)")
    args = ap.parse_args()

    if args.irange:
        irs = [ir for ir in IRs if args.irange[0] <= ir <= args.irange[1]]
    else:
        irs = IRs

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # ── collect results ──
    # data[topo][ir] = {tlm: {avg_latency, max_rho}, booksim: {avg_latency, ...}}
    data = {}
    total_runs = len(TOPOS) * len(irs) * 2  # TLM + BookSim each
    done = 0

    for topo_name, anynet in TOPOS.items():
        data[topo_name] = {}
        for ir in irs:
            print(f"[{done}/{total_runs}] {topo_name} IR={ir:.2f} ...", end=" ", flush=True)

            # TLM
            tlm_dir = outdir / f"tlm_{topo_name}_ir{ir:.2f}"
            tlm = run_tlm(anynet, ir, tlm_dir, refine=not args.no_refine)
            tlm_lat = tlm.get("avg_latency")

            # BookSim
            bs = run_booksim(anynet, ir)
            bs_lat = bs.get("avg_latency")

            data[topo_name][ir] = {
                "tlm": tlm,
                "booksim": bs,
                "tlm_lat": tlm_lat,
                "bs_lat": bs_lat,
            }

            ratio = f"{tlm_lat/bs_lat:.2f}" if tlm_lat and bs_lat and bs_lat > 0 else "N/A"
            print(f"TLM={tlm_lat}  BS={bs_lat}  ratio={ratio}")
            done += 1

    # ── save raw data ──
    raw = {}
    for topo in data:
        raw[topo] = {}
        for ir in data[topo]:
            raw[topo][str(ir)] = data[topo][ir]
    (outdir / "sweep_data.json").write_text(json.dumps(raw, indent=2, default=str))
    print(f"\nRaw data saved to {outdir}/sweep_data.json")

    # ── plot divergence curve ──
    colors = {"custom_v2": "#2196F3", "mesh_8x8": "#FF5722", "torus_8x8": "#4CAF50"}
    markers = {"custom_v2": "o", "mesh_8x8": "s", "torus_8x8": "^"}
    linestyles = {"custom_v2": "-", "mesh_8x8": "--", "torus_8x8": "-."}

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("TLM vs BookSim Divergence Curve — Qwen MoE 64-node",
                 fontsize=14, fontweight="bold")

    ax1, ax2, ax3, ax4 = axes[0, 0], axes[0, 1], axes[1, 0], axes[1, 1]

    # ── subplot 1: absolute latencies (clip saturation outliers) ──
    LAT_CLIP = 500  # cycles — above this is "saturated" territory
    for topo in TOPOS:
        ir_vals, tlm_vals, bs_vals = [], [], []
        for ir in irs:
            d = data[topo].get(ir, {})
            tl, bl = d.get("tlm_lat"), d.get("bs_lat")
            if tl is not None and bl is not None:
                ir_vals.append(ir)
                tlm_vals.append(min(tl, LAT_CLIP))
                bs_vals.append(min(bl, LAT_CLIP))
        if ir_vals:
            ax1.plot(ir_vals, tlm_vals, marker=markers[topo], color=colors[topo],
                     linestyle=linestyles[topo], label=f"{topo} TLM", linewidth=2)
            ax1.plot(ir_vals, bs_vals, marker=markers[topo], color=colors[topo],
                     linestyle=":", linewidth=1, alpha=0.5,
                     label=f"{topo} BookSim")
    ax1.set_xlabel("Injection Rate (flits/cycle/node)")
    ax1.set_ylabel("Avg Latency (cycles)")
    ax1.set_title("Absolute Latency (clipped at saturation)")
    ax1.legend(fontsize=8, loc="upper left")
    ax1.grid(True, alpha=0.3)
    ax1.set_yscale("log")
    ax1.axvline(x=0.28, color="red", linestyle=":", alpha=0.4)
    ax1.annotate("saturation\nzone", xy=(0.30, 15), fontsize=8, color="red", alpha=0.6)

    # ── subplot 2: TLM/BookSim ratio (pre-saturation only) ──
    for topo in TOPOS:
        ir_vals, ratios = [], []
        for ir in irs:
            d = data[topo].get(ir, {})
            tl, bl = d.get("tlm_lat"), d.get("bs_lat")
            # Only plot pre-saturation (ratio < 2.0)
            if tl is not None and bl is not None and bl > 0 and tl / bl < 2.0:
                ir_vals.append(ir)
                ratios.append(tl / bl)
        if ir_vals:
            ax2.plot(ir_vals, ratios, marker=markers[topo], color=colors[topo],
                     linestyle=linestyles[topo], label=topo, linewidth=2)
    ax2.axhline(y=1.0, color="gray", linestyle="--", linewidth=1, alpha=0.5,
                label="TLM = BookSim (ideal)")
    ax2.axhspan(0.5, 0.65, alpha=0.1, color="green", label="typical range")
    ax2.set_xlabel("Injection Rate (flits/cycle/node)")
    ax2.set_ylabel("TLM / BookSim Ratio")
    ax2.set_title("Divergence (pre-saturation, ratio < 1 = TLM underestimates)")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(0.4, 1.2)

    # ── subplot 3: max link utilization (rho) ──
    for topo in TOPOS:
        ir_vals, rho_vals = [], []
        for ir in irs:
            d = data[topo].get(ir, {})
            rho = d.get("tlm", {}).get("max_rho")
            if rho is not None:
                ir_vals.append(ir)
                rho_vals.append(min(rho, 1.5))
        if ir_vals:
            ax3.plot(ir_vals, rho_vals, marker=markers[topo], color=colors[topo],
                     linestyle=linestyles[topo], label=topo, linewidth=2)
    ax3.axhline(y=1.0, color="red", linestyle="--", linewidth=1, alpha=0.5,
                label="Saturation (rho=1)")
    ax3.set_xlabel("Injection Rate (flits/cycle/node)")
    ax3.set_ylabel("Max Link Utilization (ρ)")
    ax3.set_title("Peak Link Load (TLM)")
    ax3.legend(fontsize=8)
    ax3.grid(True, alpha=0.3)

    # ── subplot 4: absolute error (clip saturation outliers) ──
    ERR_CLIP = 200  # cycles
    bar_width = 0.25
    for idx, topo in enumerate(TOPOS):
        ir_vals, errs = [], []
        for ir in irs:
            d = data[topo].get(ir, {})
            tl, bl = d.get("tlm_lat"), d.get("bs_lat")
            if tl is not None and bl is not None:
                ir_vals.append(ir)
                errs.append(min(bl - tl, ERR_CLIP))  # clip saturation
        if ir_vals:
            offset = (idx - 1) * bar_width
            ax4.bar([i + offset for i in ir_vals], errs, width=bar_width,
                    color=colors[topo], alpha=0.7, label=topo)
    ax4.set_xlabel("Injection Rate (flits/cycle/node)")
    ax4.set_ylabel("BookSim − TLM (cycles, clipped)")
    ax4.set_title("Absolute Error (positive = TLM underestimates)")
    ax4.legend(fontsize=8)
    ax4.grid(True, alpha=0.3, axis="y")
    ax4.axhline(y=0, color="gray", linestyle="-", linewidth=0.5)

    plt.tight_layout()
    plot_path = args.plot or str(outdir / "divergence.png")
    fig.savefig(plot_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Plot saved to {plot_path}")

    # ── summary table ──
    print(f"\n{'='*80}")
    print(f"  TLM vs BOOKSIM DIVERGENCE — IR SWEEP")
    print(f"  matrix: {Path(MATRIX).name} | 64-node Qwen MoE dispatch")
    print(f"{'='*80}")
    header = f"{'IR':<6}"
    for topo in TOPOS:
        header += f"  {topo:>20s}"
    print(header)
    print("-" * 80)

    for ir in irs:
        row = f"{ir:<6.2f}"
        for topo in TOPOS:
            d = data[topo].get(ir, {})
            tl = d.get("tlm_lat")
            bl = d.get("bs_lat")
            if tl is not None and bl is not None and bl > 0:
                ratio = tl / bl
                row += f"  TLM={tl:5.1f} BS={bl:5.1f} r={ratio:.2f}"
            elif tl is not None:
                row += f"  TLM={tl:5.1f} BS=  ERR"
            else:
                row += f"  TLM=  ERR BS=  ERR"
        print(row)

    print(f"{'='*80}")
    print(f"\n  TLM/BookSim ratio at operating point (IR=0.08):")
    for topo in TOPOS:
        d = data[topo].get(0.08, {})
        tl = d.get("tlm_lat")
        bl = d.get("bs_lat")
        if tl and bl and bl > 0:
            print(f"    {topo:12s}: TLM={tl:.2f}  BookSim={bl:.2f}  ratio={tl/bl:.3f}")


if __name__ == "__main__":
    main()
