#!/usr/bin/env python3
"""T3 Topology — sweep injection rate across topologies, collect latency data."""
import subprocess, json, os
from pathlib import Path

CONFIGS_DIR = Path(__file__).parent.parent / "configs"
RESULTS_DIR = Path(__file__).parent.parent / "results"
CONFIGS = sorted(CONFIGS_DIR.glob("*.cfg"))
# CI sweep (coarse); add more points for local: [0.01, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4]
INJECTION_RATES = [0.05, 0.1, 0.2, 0.3, 0.4]

def run_one(cfg: Path, rate: float) -> dict:
    booksim = os.environ.get("BOOKSIM_BIN") or "booksim"
    cmd = [booksim, str(cfg), f"injection_rate={rate}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    latency = None
    for line in result.stdout.splitlines():
        if "Packet latency average" in line:
            try:
                latency = float(line.split()[-3])
            except (ValueError, IndexError):
                pass
    return {
        "topology": cfg.stem,
        "injection_rate": rate,
        "latency_cycles": latency,
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
