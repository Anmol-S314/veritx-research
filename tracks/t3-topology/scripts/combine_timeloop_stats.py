#!/usr/bin/env python3

from pathlib import Path
import re
import json
import os
from collections import OrderedDict

ROOT = Path(__file__).resolve().parent.parent

CONFIG = os.environ.get("CONFIG", "baseline")
RESULTS = ROOT / "results" / CONFIG

# ------------------------------------------------------------
# Load execution metadata
# ------------------------------------------------------------

execution_file = RESULTS / "execution.json"

if not execution_file.exists():
    print(f"{execution_file} not found.")
    exit(1)

with open(execution_file) as f:
    execution = json.load(f)["operations"]

# ------------------------------------------------------------
# Find operation stats
# ------------------------------------------------------------

stats_files = []

for op in execution:

    stats_path = RESULTS / op["stats_file"]

    if not stats_path.exists():
        print(f"Missing {stats_path}")
        exit(1)

    stats_files.append(
        {
            "name": op["name"],
            "file": stats_path,
            "repeat": op["repeat"],
        }
    )

if not stats_files:
    print("No operation stats found.")
    exit(1)

# ------------------------------------------------------------
# Combined statistics
# ------------------------------------------------------------

levels = OrderedDict()

for item in stats_files:

    op_name = item["name"]
    file = item["file"]
    repeat = item["repeat"]

    current_level = None
    inside_stats = False
    inside_tensor = False

    for line in file.read_text().splitlines():

        # ----------------------------------------------------
        # Beginning of a new memory level
        # ----------------------------------------------------

        m = re.match(r"\s*===\s*(.+?)\s*===", line)

        if m:

            level = m.group(1).strip()

            if level == "__ARITH__":
                current_level = None
            else:

                current_level = level

                if current_level not in levels:

                    levels[current_level] = {
                        "instances": 1,
                        "reads": 0,
                        "fills": 0,
                        "updates": 0,
                    }

            inside_stats = False
            inside_tensor = False
            continue

        if current_level is None:
            continue

        # ----------------------------------------------------
        # Wait until STATS section
        # ----------------------------------------------------

        if line.strip() == "STATS":
            inside_stats = True
            inside_tensor = False
            continue

        if not inside_stats:
            continue

        # ----------------------------------------------------
        # Detect tensor sections (A:, B:, Z:, etc.)
        # ----------------------------------------------------

        if re.match(r"^\s*[A-Za-z0-9_]+\s*:\s*$", line):
            inside_tensor = True
            continue

        if not inside_tensor:
            continue

        # ----------------------------------------------------
        # Parse statistics
        # ----------------------------------------------------

        m = re.search(r"Utilized instances \(max\)\s*:\s*(\d+)", line)

        if m:
            levels[current_level]["instances"] = max(
                levels[current_level]["instances"],
                int(m.group(1)),
            )
            continue

        m = re.search(
            r"Actual scalar reads \(per-instance\)\s*:\s*(\d+)",
            line,
        )

        if m:
            levels[current_level]["reads"] += repeat * int(m.group(1))
            continue

        m = re.search(
            r"Actual scalar fills \(per-instance\)\s*:\s*(\d+)",
            line,
        )

        if m:
            levels[current_level]["fills"] += repeat * int(m.group(1))
            continue

        m = re.search(
            r"Actual scalar updates \(per-instance\)\s*:\s*(\d+)",
            line,
        )

        if m:
            levels[current_level]["updates"] += repeat * int(m.group(1))
            continue
# ------------------------------------------------------------
# Write combined file
# ------------------------------------------------------------

outfile = RESULTS / "timeloop.stats.txt"

with open(outfile, "w") as f:

    f.write("# Combined Timeloop Statistics\n\n")

    for level, data in levels.items():

        f.write(f"=== {level} ===\n")
        f.write(f"Utilized instances (max) : {data['instances']}\n")
        f.write(f"Actual scalar reads (per-instance) : {data['reads']}\n")
        f.write(f"Actual scalar fills (per-instance) : {data['fills']}\n")
        f.write(f"Actual scalar updates (per-instance) : {data['updates']}\n\n")

# ------------------------------------------------------------
# Summary
# ------------------------------------------------------------

unique_operations = len(execution)
total_repeats = sum(op["repeat"] for op in execution)
saved_runs = total_repeats - unique_operations

print()
print("========================================")
print("Timeloop Statistics Combined")
print("========================================")
print(f"Unique operations      : {unique_operations}")
print(f"Scheduled executions   : {total_repeats}")
print(f"Timeloop runs executed : {unique_operations}")
print(f"Timeloop runs saved    : {saved_runs}")
print(f"Configuration          : {CONFIG}")
print(f"Wrote {outfile}")