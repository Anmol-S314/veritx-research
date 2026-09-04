#!/usr/bin/env python3

from pathlib import Path
import yaml
import subprocess
import shutil
import sys
import json
import os

# ------------------------------------------------------------
# Repository paths
# ------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent

TIMELOOP_DIR = ROOT / "timeloop"
EXPERIMENT_CONFIGS_DIR = TIMELOOP_DIR / "experiment_configs"
PROBLEM_LIBRARY_DIR = TIMELOOP_DIR / "problem_library"

TEMP_PROBLEM = TIMELOOP_DIR / "problem.yaml"

config_name = os.environ.get("CONFIG", "baseline")

CONFIG_FILE = EXPERIMENT_CONFIGS_DIR / f"{config_name}.yaml"

RESULTS_DIR = ROOT / "results" / config_name
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

OPERATIONS_DIR = RESULTS_DIR / "operations"

if OPERATIONS_DIR.exists():
    shutil.rmtree(OPERATIONS_DIR)

OPERATIONS_DIR.mkdir(parents=True)

# ------------------------------------------------------------
# Remove previous summary outputs
# ------------------------------------------------------------

for pattern in (
    "*.stats.txt",
    "*.map.txt",
    "*.map+stats.xml",
    "execution.json",
):
    for f in RESULTS_DIR.glob(pattern):
        f.unlink()

stats_file = TIMELOOP_DIR / "timeloop-mapper.stats.txt"
xml_file   = TIMELOOP_DIR / "timeloop-mapper.map+stats.xml"
map_file   = TIMELOOP_DIR / "timeloop-mapper.map.txt"


# ============================================================
# Load experiment configuration
# ============================================================

def load_config():

    if not CONFIG_FILE.exists():
        print(f"Configuration '{config_name}' not found.")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


# ============================================================
# Build execution plan
# ============================================================

def build_execution_plan(config):

    if "schedule" not in config:
        print("No schedule found in configuration.")
        sys.exit(1)

    execution = []

    for item in config["schedule"]:

        execution.append({

            "id": item["id"],

            "problem": item["problem"],

            "repeat": item.get("repeat", 1),

            "params": item.get("params", {}),

        })

    return execution


# ============================================================
# Generate Timeloop problem from template
# ============================================================

def generate_problem(problem_file, params):

    template = PROBLEM_LIBRARY_DIR / problem_file

    if not template.exists():

        print(f"Problem template '{problem_file}' not found.")

        sys.exit(1)

    with open(template) as f:

        problem = yaml.safe_load(f)

    instance = problem["problem"]["instance"]

    for key, value in params.items():

        instance[key] = value

    with open(TEMP_PROBLEM, "w") as f:

        yaml.safe_dump(
            problem,
            f,
            sort_keys=False,
        )
# ============================================================
# Run one Timeloop operation
# ============================================================

def run_operation(op):

    op_id = op["id"]

    print(f"\nProcessing operation: {op_id}")

    generate_problem(
        op["problem"],
        op["params"],
    )

    cmd = [
        "timeloop-mapper",
        "mapper.yaml",
        "arch.yaml",
        "problem.yaml",
    ]

    result = subprocess.run(
        cmd,
        cwd=TIMELOOP_DIR,
    )

    if result.returncode != 0:

        print(f"\nOperation {op_id} failed.")

        sys.exit(1)

    op_dir = OPERATIONS_DIR / op_id
    op_dir.mkdir(parents=True, exist_ok=True)

    if stats_file.exists():
        shutil.copy(stats_file, op_dir / "stats.txt")

    if xml_file.exists():
        shutil.copy(xml_file, op_dir / "map+stats.xml")

    if map_file.exists():
        shutil.copy(map_file, op_dir / "map.txt")

    print(f"Saved outputs -> {op_id}")


# ============================================================
# Generate traffic matrix
# ============================================================

def generate_operation_matrix(op_id):

    print(f"Generating traffic matrix for {op_id}...")

    op_dir = OPERATIONS_DIR / op_id

    stats = op_dir / "stats.txt"
    matrix = op_dir / "traffic_matrix.txt"

    if not stats.exists():

        print(f"Warning: {stats} not found.")

        return

    subprocess.run(
        [
            "python3",
            str(ROOT / "scripts" / "timeloop_to_matrix.py"),
            str(stats),
            "-n",
            "16",
            "-o",
            str(matrix),
        ],
        check=True,
    )


# ============================================================
# Main
# ============================================================

def main():

    print(f"Using configuration: {config_name}")

    config = load_config()

    execution = build_execution_plan(config)

    print("\n========================================")
    print("Timeloop Execution Plan")
    print("========================================")

    execution_json = {
        "operations": []
    }

    for idx, op in enumerate(execution, start=1):

        print(
            f"{idx}. {op['id']} ({op['problem']}, repeat={op['repeat']})"
        )

        execution_json["operations"].append(
            {
                "name": op["id"],
                "repeat": op["repeat"],
                "stats_file": f"operations/{op['id']}/stats.txt",
            }
        )

    with open(RESULTS_DIR / "execution.json", "w") as f:
        json.dump(execution_json, f, indent=4)

    print()

    # --------------------------------------------------------
    # Run every unique operation once
    # --------------------------------------------------------

    for op in execution:

        run_operation(op)

        generate_operation_matrix(op["id"])


    print(f"\nUnique Timeloop runs : {len(execution)}")


if __name__ == "__main__":
    main()