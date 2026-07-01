#!/usr/bin/env python3
"""T3 Topology — sweep injection rate across topologies, collect latency data."""
import subprocess, json, os
from pathlib import Path

CONFIGS_DIR = Path(__file__).parent.parent / "configs"
RESULTS_DIR = Path(__file__).parent.parent / "results"
CONFIGS = sorted(CONFIGS_DIR.glob("*.cfg"))
# CI sweep (coarse). Override for local/matrix runs: RATES="0.002,0.005,0.01,0.02"
# (matrix patterns with a hotspot saturate at much lower rates than uniform).
_rates = os.environ.get("RATES")
INJECTION_RATES = [float(x) for x in _rates.split(",")] if _rates else [0.05, 0.1, 0.2, 0.3, 0.4]

# Optional Timeloop-derived traffic matrix (the Timeloop->Booksim bridge). When
# set, every topology is driven by this matrix instead of uniform random traffic.
MATRIX = os.environ.get("TRAFFIC_MATRIX")

def run_one(cfg: Path, rate: float) -> dict:
    booksim = os.environ.get("BOOKSIM_BIN") or "booksim"
    cmd = [booksim, str(cfg), f"injection_rate={rate}"]
    if MATRIX:
        cmd.append(f"traffic=matrix({MATRIX})")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    latency = hops = None
    for line in result.stdout.splitlines():
        parts = line.split()
        if "Packet latency average" in line:
            for p in parts:
                try:
                    latency = float(p)
                    break
                except ValueError:
                    pass
        elif "Hops average" in line:
            for p in parts:
                try:
                    hops = float(p)
                    break
                except ValueError:
                    pass
    return {
        "topology": cfg.stem,
        "injection_rate": rate,
        "traffic": f"matrix({Path(MATRIX).name})" if MATRIX else "uniform",
        "latency_cycles": latency,
        "hops_avg": hops,  # energy proxy = hops_avg * packet_size (Pareto step)
        "status": "ok" if latency is not None else "no_output",
        "returncode": result.returncode,
    }

def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for cfg in CONFIGS:
        for rate in INJECTION_RATES:
            print(f"  {cfg.stem} @ {rate} ...", end=" ")
            res = run_one(cfg, rate)
            print(res["latency_cycles"])
            results.append(res)

    report = RESULTS_DIR / "topology_sweep.json"
    with open(report, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  {len(results)} data points → {report}")

if __name__ == "__main__":
    main()
