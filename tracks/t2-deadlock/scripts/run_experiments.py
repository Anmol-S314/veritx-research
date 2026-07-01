#!/usr/bin/env python3
"""T2 Deadlock — experiment suite: sweep injection rate, detect deadlock."""
import subprocess, json, sys, os, time
from pathlib import Path

CONFIGS_DIR = Path(__file__).parent.parent / "configs"
RESULTS_DIR = Path(__file__).parent.parent / "results"

# CI sweep (coarse); add more points for local: [0.01, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3]
INJECTION_RATES = [0.05, 0.1, 0.2, 0.3]
CONFIGS = sorted(CONFIGS_DIR.glob("*.cfg"))

def run_booksim(cfg_path: Path, injection_rate: float) -> dict:
    """Run Booksim with modified injection rate and parse output."""
    booksim = os.environ.get("BOOKSIM_BIN") or "booksim"
    # Override injection rate via command-line arg
    cmd = [booksim, str(cfg_path),
           f"injection_rate={injection_rate}"]
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    elapsed = time.time() - start

    stdout = result.stdout
    data = {
        "config": cfg_path.name,
        "injection_rate": injection_rate,
        "returncode": result.returncode,
        "elapsed_s": round(elapsed, 2),
        "latency": None,
        "deadlock": False,
    }

    for line in stdout.splitlines():
        if "Packet latency average" in line:
            try:
                latency = float(line.split()[-3])
            except (ValueError, IndexError):
                pass
        if "deadlock" in line.lower():
            data["deadlock"] = True

    # If sim hangs (timeout or no output), flag as deadlock
    if result.returncode != 0 and data["latency"] is None:
        data["deadlock"] = True
        data["returncode"] = result.returncode
        data["stderr"] = result.stderr[:500]

    return data

def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    all_results = []

    for cfg in CONFIGS:
        for rate in INJECTION_RATES:
            print(f"  {cfg.name} @ rate={rate} ...", end=" ")
            try:
                res = run_booksim(cfg, rate)
                tag = "DEADLOCK" if res["deadlock"] else f"lat={res['latency']}"
                print(tag)
                all_results.append(res)
            except subprocess.TimeoutExpired:
                print("TIMEOUT → deadlock")
                all_results.append({
                    "config": cfg.name,
                    "injection_rate": rate,
                    "deadlock": True,
                    "latency": None,
                    "elapsed_s": 300.0,
                })
            except Exception as e:
                print(f"ERROR: {e}")
                all_results.append({
                    "config": cfg.name,
                    "injection_rate": rate,
                    "error": str(e),
                })

    report = RESULTS_DIR / "experiments.json"
    with open(report, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n  {len(all_results)} experiments → {report}")

    # Summary
    deadlocks = [r for r in all_results if r.get("deadlock")]
    if deadlocks:
        print(f"  ⚠  {len(deadlocks)} deadlock(s) detected")
        for d in deadlocks[:5]:
            print(f"     {d['config']} @ rate={d['injection_rate']}")
    else:
        print("  ✓  No deadlocks detected")

if __name__ == "__main__":
    main()
