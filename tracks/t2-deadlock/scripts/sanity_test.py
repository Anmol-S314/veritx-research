#!/usr/bin/env python3
"""T2 Deadlock — sanity test: runs Booksim on a 4x4 mesh, checks output."""
import subprocess, json, sys, os
from pathlib import Path

CFG = Path(__file__).parent.parent / "configs" / "mesh4x4_uniform.cfg"
RESULTS = Path(__file__).parent.parent / "results"

def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    booksim = os.environ.get("BOOKSIM_BIN") or "booksim"
    print(f"  Running: {booksim} {CFG}")
    result = subprocess.run(
        [booksim, str(CFG)],
        capture_output=True, text=True, timeout=60
    )
    stdout = result.stdout
    stderr = result.stderr

    latency = None
    for line in stdout.splitlines():
        if "Packet latency average" in line:
            try:
                latency = float(line.split()[-3])
            except (ValueError, IndexError):
                pass
    if latency is None:
        if stderr:
            print(f"  Booksim error:\n{stderr[:500]}")
        else:
            print(f"  Could not parse latency (booksim rc={result.returncode})")
            print(f"  Last 5 lines:\n" + "\n".join(stdout.splitlines()[-5:]))
        sys.exit(1)

    data = {
        "track": "t2-deadlock",
        "config": CFG.name,
        "latency_cycles": latency,
        "status": "pass"
    }
    report = RESULTS / "sanity_result.json"
    with open(report, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Latency: {latency} cycles  →  {report}")
    print("  T2 sanity OK")

if __name__ == "__main__":
    main()
