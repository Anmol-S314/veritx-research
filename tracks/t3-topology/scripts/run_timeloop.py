#!/usr/bin/env python3
"""Run Timeloop once per NoC size (T3).

`arch.yaml` describes an N-PE accelerator, and its PE count must equal the NoC's
node count -- one PE per tile. Sweeping a 16-node AND a 64-node topology against
a single 16-PE Timeloop run would spread a workload mapped onto 16 PEs across 64
tiles, so the traffic wouldn't describe the machine being simulated.

So: derive the node counts from configs/, emit a scaled arch per size, run the
mapper for each, and leave results/timeloop_<N>.stats.txt for the matrix bridge.
Nothing is hardcoded to 16 -- add a config of any size and it gets its own run.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).parent
TRACK = HERE.parent
TIMELOOP = TRACK / "timeloop"
RESULTS = TRACK / "results"

sys.path.insert(0, str(HERE))
from timeloop_to_matrix import parse_levels, sizes_from_configs  # noqa: E402


def scale_arch(arch: dict, nodes: int) -> dict:
    """Set the per-PE levels to `nodes` instances. Shared levels stay singular.

    Only the arithmetic units and their private RegisterFile are replicated per
    tile (they carry meshX). GlobalBuffer and DRAM are shared -- scaling those
    would model a different machine, not a bigger one.
    """
    a = yaml.safe_load(yaml.safe_dump(arch))  # deep copy
    arith = a["arch"]["arithmetic"]
    arith["instances"] = nodes
    arith["meshX"] = nodes
    for level in a["arch"]["storage"]:
        if "meshX" in level:  # per-PE level
            level["instances"] = nodes
            level["meshX"] = nodes
    return a


def run_one(nodes: int, arch: dict, tag: str | None = None) -> Path | None:
    """Run the mapper for one size; return its stats file, or None if it failed.

    `tag` names the output files instead of the node count, so a sweep over some
    OTHER arch knob (see gb_sweep.py) can run many mappings at one node count
    without each one clobbering the last.
    """
    tag = tag or str(nodes)
    work = RESULTS / f"timeloop_{tag}"
    work.mkdir(parents=True, exist_ok=True)
    (work / "arch.yaml").write_text(yaml.safe_dump(scale_arch(arch, nodes),
                                                   sort_keys=False))
    for f in ("problem.yaml", "mapper.yaml"):
        shutil.copy(TIMELOOP / f, work / f)

    print(f"  timeloop: {nodes} PEs ...", end=" ", flush=True)
    proc = subprocess.run(
        ["timeloop-mapper", "mapper.yaml", "arch.yaml", "problem.yaml"],
        cwd=work, capture_output=True, text=True, timeout=900)
    (RESULTS / f"timeloop_{tag}.log").write_text(proc.stdout + proc.stderr)

    stats = work / "timeloop-mapper.stats.txt"
    if not stats.exists():
        print(f"FAILED (see results/timeloop_{tag}.log)")
        return None
    out = RESULTS / f"timeloop_{tag}.stats.txt"
    shutil.copy(stats, out)
    print(f"→ {out.name}")

    # Giving the mapper N PEs does not mean it USES N PEs. If the workload is too
    # small it maps onto fewer and the traffic then describes a machine you aren't
    # simulating -- a 16^3 GEMM on 64 PEs utilizes 16, and emits byte-identical
    # accesses to the 16-PE run. The topology comparison would look fine and mean
    # nothing, so say it out loud.
    used = max((l["instances"] for l in parse_levels(out.read_text())
                if l["instances"] > 1), default=1)
    if used < nodes:
        print(f"     ⚠  mapped onto only {used} of {nodes} PEs — the workload is too "
              f"small to fill this NoC.\n"
              f"        Its traffic describes a {used}-tile machine, so the "
              f"{nodes}-node result is not comparable.\n"
              f"        Scale timeloop/problem.yaml (a 64^3 GEMM fills 64 PEs; the "
              f"shipped 16^3 does not).")
    return out


def main():
    if not shutil.which("timeloop-mapper"):
        sys.exit("✗ timeloop-mapper not on PATH — run inside the tools image.")

    arch = yaml.safe_load((TIMELOOP / "arch.yaml").read_text())
    sizes = sizes_from_configs()
    print(f"  node counts in configs/: {sizes}")

    ok = [n for n in sizes if run_one(n, arch)]
    if not ok:
        sys.exit("✗ Timeloop produced no stats for any size.")
    if len(ok) < len(sizes):
        print(f"  ⚠  no Timeloop stats for {sorted(set(sizes) - set(ok))} — those "
              f"topologies will be skipped in the matrix sweep.")


def _selfcheck():
    arch = yaml.safe_load((TIMELOOP / "arch.yaml").read_text())
    a64 = scale_arch(arch, 64)
    assert a64["arch"]["arithmetic"]["instances"] == 64
    assert a64["arch"]["arithmetic"]["meshX"] == 64
    per_pe = [l for l in a64["arch"]["storage"] if "meshX" in l]
    shared = [l for l in a64["arch"]["storage"] if "meshX" not in l]
    assert per_pe and all(l["instances"] == 64 for l in per_pe), per_pe
    # GlobalBuffer/DRAM are shared: a bigger mesh must not silently multiply them
    assert shared and all(l.get("instances", 1) == 1 for l in shared), shared
    # the template itself is untouched (we deep-copy before mutating)
    assert arch["arch"]["arithmetic"]["instances"] == 16, "scale_arch mutated input"
    print("selfcheck OK")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--selfcheck":
        _selfcheck()
    else:
        main()
