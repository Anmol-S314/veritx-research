#!/usr/bin/env python3
"""T3 Topology — sanity test: run Booksim on all configs, check output."""
import subprocess, json, sys, os
from pathlib import Path

CONFIGS_DIR = Path(__file__).parent.parent / "configs"
RESULTS = Path(__file__).parent.parent / "results"

def _cfg_usable(cfg: Path) -> bool:
    """Preflight: anynet cfgs need their network_file to resolve (same guard
    as run_experiments._cfg_usable; copied here to keep this gate script
    dependency-free)."""
    import re
    try:
        text = cfg.read_text()
    except OSError:
        return True
    if "topology = anynet" not in text:
        return True
    m = re.search(r"network_file\s*=\s*([^;\s]+)", text)
    if not m:
        print(f"  ⚠ skipping {cfg.name}: anynet without network_file")
        return False
    if (cfg.parent / m.group(1)).exists() or Path(m.group(1)).exists():
        return True
    print(f"  ⚠ skipping {cfg.name}: network_file {m.group(1)} resolves nowhere")
    return False

def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    booksim = os.environ.get("BOOKSIM_BIN") or "booksim"
    import shutil
    _hit = Path(booksim) if "/" in booksim else shutil.which(booksim)
    if _hit is None or not os.access(_hit, os.X_OK):
        # Clean gate behavior (F3): missing binary is SKIP-worthy setup state,
        # not a traceback. Same message shape as run_experiments.run_one.
        print(f"  ✗ booksim binary not found or not executable: {booksim!r}",
              file=sys.stderr)
        print("    resolve it via run/env.sh (BOOKSIM_BIN), or build it:",
              file=sys.stderr)
        print("      cd third_party/booksim2/src && make -j$(nproc)", file=sys.stderr)
        sys.exit(2)
    configs = sorted(CONFIGS_DIR.glob("*.cfg"))
    configs = [c for c in configs if _cfg_usable(c)]
    if not configs:
        print("  ✗ no usable topology configs — nothing to check", file=sys.stderr)
        sys.exit(2)
    all_latencies = {}
    failed = []

    for cfg in configs:
        if not _cfg_usable(cfg):
            continue
        print(f"  Booksim {cfg.name} ...", end=" ")
        try:
            result = subprocess.run(
                [booksim, str(cfg)],
                capture_output=True, text=True, timeout=60
            )
        except subprocess.TimeoutExpired:
            print("timeout")
            failed.append((cfg.stem, "timeout"))
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
        import math
        # A gate must gate: a crashed run (nonzero rc) or a nonfinite latency
        # is a failure even if stats were partially printed. The old loop
        # recorded rc but judged only "did a float appear", so a die() mid-Run
        # still produced "status: pass".
        if result.returncode != 0:
            print(f"FAILED (rc={result.returncode})")
            failed.append((cfg.stem, f"rc={result.returncode}"))
        elif latency is None or not math.isfinite(latency):
            print(f"FAILED (latency={latency})")
            failed.append((cfg.stem, f"latency={latency}"))
        else:
            print(f"latency={latency}")

    if failed:
        data = {
            "track": "t3-topology",
            "status": "fail",
            "failed": [f"{t}: {why}" for t, why in failed],
            "topologies": all_latencies
        }
        report = RESULTS / "sanity_result.json"
        with open(report, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\n  Results → {report}")
        print(f"  T3 sanity FAILED: {len(failed)} of {len(all_latencies)} "
              f"topologies failed — see {report}")
        sys.exit(1)

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
