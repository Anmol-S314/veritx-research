# T1: KVCache QoS — gem5/Garnet sanity config
# NOTE: gem5 is not in the base Docker image (4-6hr compile).
# This stub validates the infrastructure is ready.
import os
import json
from pathlib import Path

RESULTS = Path(__file__).parent.parent / "results"

def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    gem5_path = os.environ.get("GEM5_BIN") or "/usr/local/bin/gem5.opt"
    gem5_available = os.path.isfile(gem5_path) and os.access(gem5_path, os.X_OK)

    data = {
        "track": "t1-kvcache",
        "gem5_binary": gem5_path,
        "gem5_available": gem5_available,
        "status": "skip" if not gem5_available else "ready",
        "note": "gem5 build deferred (4-6 hrs). Rebuild Docker with gem5 layer to enable."
    }
    report = RESULTS / "sanity_result.json"
    with open(report, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  gem5 available: {gem5_available}")
    print(f"  Status: {data['status']}")
    print(f"  → {report}")

if __name__ == "__main__":
    main()
