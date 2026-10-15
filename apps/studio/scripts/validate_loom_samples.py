#!/usr/bin/env python3
"""Validate shipped offline Loom project samples against the local v1 schema."""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

STUDIO = Path(__file__).resolve().parents[1]
REPO = STUDIO.parent.parent
SAMPLE_DIR = STUDIO / "fixtures/projects"
REQUIRED = {
    "small-custom.project.json": "small-topology",
    "multi-domain.project.json": "multi-domain",
    "floorplanned.project.json": "floorplan",
    "workload-bound.project.json": "workload",
}

def main() -> None:
    schema = json.loads((REPO / "contracts/loom/v1/project.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    for filename, category in REQUIRED.items():
        path = SAMPLE_DIR / filename
        project = json.loads(path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(project), key=lambda e: list(e.absolute_path))
        if errors:
            first = errors[0]
            where = ".".join(str(part) for part in first.absolute_path) or "$"
            raise SystemExit(f"{filename}: {where}: {first.message}")
        if category == "small-topology" and not (1 <= len(project["nodes"]) <= 8):
            raise SystemExit(f"{filename}: expected a small topology (1-8 nodes)")
        if category == "multi-domain" and not project.get("domains"):
            raise SystemExit(f"{filename}: domain configuration is missing")
        if category == "floorplan" and not project.get("floorplan"):
            raise SystemExit(f"{filename}: floorplan configuration is missing")
        if category == "workload" and not project.get("workload"):
            raise SystemExit(f"{filename}: authored workload is missing")
        print(f"PASS: {filename} ({category}; {len(project['nodes'])} nodes / {len(project['edges'])} edges)")
    print("PASS: all required samples validate offline against local Loom project schema v1")
    print("TRUTH: workload is authored input; floorplan is authored intent; neither implies measured/physical execution")

if __name__ == "__main__":
    main()
