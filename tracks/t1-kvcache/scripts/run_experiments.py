#!/usr/bin/env python3
"""T1 KVCache — experiment stub (gem5 deferred)."""
import json
from pathlib import Path

RESULTS = Path(__file__).parent.parent / "results"

def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    data = {
        "track": "t1-kvcache",
        "status": "skipped",
        "note": "gem5 build deferred (4-6 hrs). Rebuild Docker with gem5 layer to enable."
    }
    report = RESULTS / "experiments.json"
    with open(report, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  T1 experiments skipped (gem5 deferred) → {report}")

if __name__ == "__main__":
    main()
