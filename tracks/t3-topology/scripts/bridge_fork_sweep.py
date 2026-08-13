#!/usr/bin/env python3
"""Bridge-fork vs source-fork on the 2-die bridge topology (UCIE-ARC Phase 2).

Mechanism comparison on `bridged_2die.cfg` (two 8x8 meshes + one bridge link):

  source-fork : sender replicates; bridge carries g copies   (mcast_naive=1)
  bridge-fork : bridge carries 1 copy; die B forks to g      (mcast_naive=0)

What we measure per cell:
  - accepted packet rate (throughput at the bridge bottleneck)
  - packet latency (the KV fetch latency the decode cores see)

Known-answer gate (PITFALLS 16 / UCIE-ARC): bridge-fork must show >= g-fold
link-load advantage at the bridge; below saturation it is a latency win, at
saturation it is a throughput win.

Usage: python3 scripts/bridge_fork_sweep.py [--rate 0.001..] [--g 4..16]
"""
import os, re, subprocess, sys

BOOKSIM = os.environ.get("BOOKSIM_BIN",
                         "/home/datavex/veritx-research/third_party/booksim2/src/booksim")
CFG = "/home/datavex/veritx-research/tracks/t3-topology/configs/booksim2_configs/bridged_2die.cfg"

def run_cell(g, rate, naive, max_samples=60):
    """Run booksim; return (accepted_rate, avg_latency)."""
    cmd = [BOOKSIM, CFG,
           f"mcast_k={g}", f"mcast_naive={naive}",
           f"injection_rate={rate}",
           "traffic=uniform", "packet_size=1",
           "sim_type=latency", "sample_period=1000",
           "warmup_periods=3", f"max_samples={max_samples}"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    out = r.stdout + r.stderr
    acc = re.findall(r"Accepted packet rate average = ([\d.e+-]+)", out)
    lat = re.findall(r"Packet latency average = ([\d.e+-]+)", out)
    hops = re.findall(r"Hops average = ([\d.e+-]+)", out)
    return (float(acc[-1]) if acc else None,
            float(lat[-1]) if lat else None,
            float(hops[-1]) if hops else None)

def main():
    g = int(sys.argv[sys.argv.index("--g") + 1]) if "--g" in sys.argv else 8
    rates = [0.0005, 0.001, 0.002, 0.004, 0.008]
    print(f"=== bridge-fork vs source-fork, g={g} remote cores, 2-die bridge ===\n")
    print(f"  {'rate':>8} | {'bridge-fork':^22} | {'source-fork':^22} | {'fork ratio':>10}")
    print(f"  {'':>8} | {'accept':>9} {'lat':>9} | {'accept':>9} {'lat':>9} | {'(src/brg)':>10}")
    for rate in rates:
        ba, bl, _ = run_cell(g, rate, 0)
        sa, sl, _ = run_cell(g, rate, 1)
        bf = f"{ba:.4f}/{bl:8.1f}" if ba else "FAIL"
        sf = f"{sa:.4f}/{sl:8.1f}" if sa else "FAIL"
        ratio = (sa / ba) if (sa and ba and ba > 0) else float("nan")
        print(f"  {rate:>8.4f} | {bf:>22} | {sf:>22} | {ratio:>9.1f}x")

if __name__ == "__main__":
    main()
