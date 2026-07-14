#!/usr/bin/env python3

from pathlib import Path
import yaml
import subprocess
import shutil
import sys

# ------------------------------------------------------------
# Repository paths
# ------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent

problem_file = ROOT / "timeloop" / "problem.yaml"
temp_problem = ROOT / "timeloop" / "temp_problem.yaml"

results_dir = ROOT / "results"
results_dir.mkdir(exist_ok=True)

# ------------------------------------------------------------
# Remove outputs from previous run
# ------------------------------------------------------------

for pattern in (
    "op*.stats.txt",
    "op*.map.txt",
    "op*.map+stats.xml",
    "timeloop.stats.txt",
):
    for f in results_dir.glob(pattern):
        f.unlink()

stats_file = ROOT / "timeloop" / "timeloop-mapper.stats.txt"
xml_file   = ROOT / "timeloop" / "timeloop-mapper.map+stats.xml"
map_file   = ROOT / "timeloop" / "timeloop-mapper.map.txt"

# ------------------------------------------------------------
# Load multi-operation YAML
# ------------------------------------------------------------

with open(problem_file, "r") as f:
    problems = yaml.safe_load(f)

print("=== Parsing problem.yaml ===\n")

i = 1

while i in problems or str(i) in problems:

    key = i if i in problems else str(i)

    print(f"Processing operation {i}...")

    # --------------------------------------------------------
    # Extract one operation
    # --------------------------------------------------------

    operation = problems[key]

    with open(temp_problem, "w") as f:
        yaml.safe_dump(operation, f, sort_keys=False)

    # --------------------------------------------------------
    # Run Timeloop
    # --------------------------------------------------------

    print("  -> Running Timeloop...")

    cmd = [
        "timeloop-mapper",
        "mapper.yaml",
        "arch.yaml",
        "temp_problem.yaml"
    ]

    result = subprocess.run(
        cmd,
        cwd=ROOT / "timeloop",
    )

    if result.returncode != 0:
        print(f"\nOperation {i} failed.")
        sys.exit(1)

    print("  -> Timeloop completed.")

    # --------------------------------------------------------
    # Save outputs for this operation
    # --------------------------------------------------------

    if stats_file.exists():
        shutil.copy(stats_file, results_dir / f"op{i}.stats.txt")

    if xml_file.exists():
        shutil.copy(xml_file, results_dir / f"op{i}.map+stats.xml")

    if map_file.exists():
        shutil.copy(map_file, results_dir / f"op{i}.map.txt")

    print(f"  -> Saved outputs for operation {i}\n")

    i += 1

print(f"Total operations processed: {i-1}")