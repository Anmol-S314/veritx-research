#!/usr/bin/env python3

from pathlib import Path
import yaml
import subprocess
import shutil
import glob
import sys

# ------------------------------------------------------------
# Repository paths
# ------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent

TIMELOOP_DIR = ROOT / "timeloop"
CONFIG_FILE = TIMELOOP_DIR / "config.yaml"
PROBLEMS_DIR = TIMELOOP_DIR / "problems"
TEMP_PROBLEM = TIMELOOP_DIR / "temp_problem.yaml"

RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# ------------------------------------------------------------
# Remove previous outputs
# ------------------------------------------------------------

for pattern in (
    "op*.stats.txt",
    "op*.map.txt",
    "op*.map+stats.xml",
    "timeloop.stats.txt",
):
    for f in RESULTS_DIR.glob(pattern):
        f.unlink()

stats_file = TIMELOOP_DIR / "timeloop-mapper.stats.txt"
xml_file   = TIMELOOP_DIR / "timeloop-mapper.map+stats.xml"
map_file   = TIMELOOP_DIR / "timeloop-mapper.map.txt"


# ============================================================
# Load configuration
# ============================================================

def load_config():

    if not CONFIG_FILE.exists():
        print("config.yaml not found.")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


# ============================================================
# Discover available operations
# ============================================================

def discover_operations(enabled_types):

    operations = {}

    for op_type in enabled_types:

        folder = PROBLEMS_DIR / op_type

        if not folder.exists():
            print(f"Warning: {folder} not found.")
            continue

        for file in sorted(folder.glob("*.yaml")):

            operations[file.stem] = file

    return operations


# ============================================================
# Expand schedule
# ============================================================

def build_execution_list(config, operations):

    execution = []

    if "schedule" not in config:
        print("config.yaml has no schedule.")
        sys.exit(1)

    for item in config["schedule"]:

        name = item["op"]
        repeat = item.get("repeat", 1)

        if name not in operations:
            print(f"Unknown operation: {name}")
            sys.exit(1)

        for _ in range(repeat):
            execution.append((name, operations[name]))

    return execution


# ============================================================
# Run one Timeloop operation
# ============================================================

def run_operation(index, op_name, op_path):

    print(f"\nProcessing operation {index}: {op_name}")

    shutil.copy(op_path, TEMP_PROBLEM)

    cmd = [
        "timeloop-mapper",
        "mapper.yaml",
        "arch.yaml",
        "temp_problem.yaml",
    ]

    result = subprocess.run(
        cmd,
        cwd=TIMELOOP_DIR,
    )

    if result.returncode != 0:
        print(f"\nOperation {op_name} failed.")
        sys.exit(1)

    if stats_file.exists():
        shutil.copy(stats_file, RESULTS_DIR / f"op{index}.stats.txt")

    if xml_file.exists():
        shutil.copy(xml_file, RESULTS_DIR / f"op{index}.map+stats.xml")

    if map_file.exists():
        shutil.copy(map_file, RESULTS_DIR / f"op{index}.map.txt")

    print(f"Saved outputs -> op{index}")


# ============================================================
# Main
# ============================================================

def main():

    config = load_config()

    enabled = config.get("enabled", [])

    operations = discover_operations(enabled)

    if len(operations) == 0:
        print("No operations discovered.")
        sys.exit(1)

    execution = build_execution_list(config, operations)

    print("\n========================================")
    print("Timeloop Execution Plan")
    print("========================================")

    for i, (name, _) in enumerate(execution, start=1):
        print(f"{i}. {name}")

    print()

    for i, (name, path) in enumerate(execution, start=1):
        run_operation(i, name, path)

    print(f"\nTotal Timeloop runs : {len(execution)}")


if __name__ == "__main__":
    main()