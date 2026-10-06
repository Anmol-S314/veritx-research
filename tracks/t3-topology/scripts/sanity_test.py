#!/usr/bin/env python3
"""T3 Topology — sanity test: run Booksim on all configs, check output."""
import subprocess, json, sys, os
from pathlib import Path

CONFIGS_DIR = Path(__file__).parent.parent / "configs"
RESULTS = Path(__file__).parent.parent / "results"

def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    booksim = os.environ.get("BOOKSIM_BIN") or "booksim"
    configs = sorted(CONFIGS_DIR.glob("*.cfg"))
    all_latencies = {}

    failures: list[str] = []
    for cfg in configs:
        print(f"  Booksim {cfg.name} ...", end=" ")
        try:
            result = subprocess.run(
                [booksim, str(cfg)],
                capture_output=True, text=True, timeout=60
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"ERROR: {exc}")
            all_latencies[cfg.stem] = None
            failures.append(f"{cfg.name}: did not run ({exc})")
            continue
        if result.returncode != 0:
            print(f"ERROR: exit {result.returncode}")
            print(result.stderr[-2000:] if result.stderr else "(no stderr)")
            all_latencies[cfg.stem] = None
            failures.append(f"{cfg.name}: booksim exit {result.returncode}")
            continue
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
        if latency is None:
            failures.append(
                f"{cfg.name}: no 'Packet latency average' in output — "
                "a run without a latency figure is not a pass")
    if not configs:
        failures.append("no configs found: nothing ran")

    ok = not failures
    data = {
        "track": "t3-topology",
        "status": "pass" if ok else "fail",
        "topologies": all_latencies,
        "failures": failures,
    }
    report = RESULTS / "sanity_result.json"
    with open(report, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\n  Results → {report}")
    if not ok:
        print("  T3 sanity FAILED:")
        for failure in failures:
            print(f"    - {failure}")
        raise SystemExit(1)
    print("  T3 sanity OK")

if __name__ == "__main__":
    main()
