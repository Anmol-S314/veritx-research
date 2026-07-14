#!/usr/bin/env python3
"""T3 Topology — sanity test: run Booksim on all configs, check output."""
import shutil, subprocess, json, sys, os
from pathlib import Path

CONFIGS_DIR = Path(__file__).parent.parent / "configs"
RESULTS = Path(__file__).parent.parent / "results"

def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    booksim = os.environ.get("BOOKSIM_BIN") or "booksim"
    # Every other script in this track says this rather than dumping a traceback.
    if not shutil.which(booksim):
        sys.exit(f"✗ '{booksim}' not on PATH — run inside the tools image:\n"
                 f"    make run TRACK=t3-topology CMD=test\n"
                 f"  (or set BOOKSIM_BIN to a booksim binary)")
    configs = sorted(CONFIGS_DIR.glob("*.cfg"))
    all_latencies = {}

    for cfg in configs:
        print(f"  Booksim {cfg.name} ...", end=" ")
        result = subprocess.run(
            [booksim, str(cfg)],
            capture_output=True, text=True, timeout=60
        )
        latency = None
        for line in result.stdout.splitlines():
            if "Packet latency average" in line:
                for p in line.split():
                    try:
                        latency = float(p)
                        break
                    except ValueError:
                        pass
        all_latencies[cfg.stem] = latency
        print(f"latency={latency}")

    data = {
        "track": "t3-topology",
        "status": "pass",
        "topologies": all_latencies
    }
    report = RESULTS / "sanity_result.json"
    with open(report, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\n  Results → {report}")
    print("  T3 sanity OK")

if __name__ == "__main__":
    main()
