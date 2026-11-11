#!/usr/bin/env python3
"""Build the prototype's workload-native-power snapshot.

The workload ablation slice in ``public/data/workload_ablation.json`` carries
latency, hops and throughput but no power model.  The repository keeps a
matching trace replay per workload that ran BookSim with ``sim_power=1`` and a
native technology file.  This script joins those runs into one compact file so
the Curves & Pareto page can show power, area, energy and the power breakdown
for the same workloads and topologies.

Only measured fields are copied.  Values that the model did not produce stay
absent; the page never substitutes zero.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
RUNS = ROOT / "tracks" / "t3-topology" / "runs" / "workload-ablation"
PROTOTYPE = ROOT / "apps" / "studio" / "prototype"
BASE_DOC = PROTOTYPE / "public" / "data" / "workload_ablation.json"
OUT = PROTOTYPE / "public" / "data" / "workload_power.json"
TECH = ROOT / "third_party" / "booksim2" / "src" / "power" / "techfile.txt"

POWER_KEYS = {
    "channel_wire_w": "Channel Wire Power",
    "channel_clock_w": "Channel Clock Power",
    "channel_retiming_w": "Channel Retiming Power",
    "channel_leakage_w": "Channel Leakage Power",
    "input_read_w": "Input Read Power",
    "input_write_w": "Input Write Power",
    "input_leakage_w": "Input Leakage Power",
    "switch_compute_w": "Switch Power",
    "switch_control_w": "Switch Control Power",
    "switch_leakage_w": "Switch Leakage Power",
    "output_dff_w": "Output DFF Power",
    "output_clock_w": "Output Clk Power",
    "output_control_w": "Output Control Power",
}
AREA_KEYS = {
    "channel_mm2": "Channel Area",
    "switch_mm2": "Switch  Area",
    "input_mm2": "Input  Area",
    "output_mm2": "Output  Area",
}
NUM = r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)"


def number(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, re.M)
    return float(match.group(1)) if match else None


def parse_log(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(errors="replace")
    values: dict[str, float | None] = {}
    for key, label in POWER_KEYS.items():
        values[key] = number(rf"^-\s*{re.escape(label)}\s*:\s*{NUM}", text)
    for key, label in AREA_KEYS.items():
        values[key] = number(rf"^-\s*{re.escape(label)}\s*:\s*{NUM}", text)
    values["log_total_power_w"] = number(rf"^-\s*Total Power\s*:\s*{NUM}", text)
    values["log_total_area_mm2"] = number(rf"^-\s*Total Area\s*:\s*{NUM}", text)
    values["log_completion_cycles"] = number(rf"^-\s*Completion Time\s*:\s*{NUM}", text)
    return {key: value for key, value in values.items() if value is not None}


def tech_corner() -> dict:
    text = TECH.read_text(errors="replace") if TECH.exists() else ""
    vdd = number(rf"^Vdd\s*=\s*{NUM}", text)
    temperature = number(r"//\s*([-+]?\d+(?:\.\d+)?)\s*C", text)
    return {
        "vdd_v": vdd,
        "temperature_c": temperature,
        "source": "third_party/booksim2/src/power/techfile.txt",
        "sha256": hashlib.sha256(TECH.read_bytes()).hexdigest() if TECH.exists() else None,
    }


def identity(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate_runs(workloads: set[str], traces: dict[str, str]) -> dict[str, list[tuple[float, Path, dict]]]:
    found: dict[str, list[tuple[float, Path, dict]]] = {workload: [] for workload in workloads}
    for path in sorted(RUNS.glob("*/ablation.json")):
        try:
            doc = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        runs = doc.get("runs") or []
        if not runs:
            continue
        workload = runs[0].get("workload")
        if workload not in workloads:
            continue
        if doc.get("common", {}).get("vc_buf_size") != 8:
            continue
        if doc.get("common", {}).get("overrides", {}).get("sim_power") != "1":
            continue
        if runs[0].get("trace_sha256") != traces.get(workload):
            continue
        powered = [row for row in runs if row.get("native_power_w") is not None]
        if not powered:
            continue
        found[workload].append((path.stat().st_mtime, path, doc))
    return found


def choose(found: dict[str, list[tuple[float, Path, dict]]]) -> dict[str, tuple[Path, dict]]:
    chosen: dict[str, tuple[Path, dict]] = {}
    for workload, candidates in found.items():
        if not candidates:
            continue
        # Prefer a complete twelve-arm native run; otherwise take the most
        # recent run and keep the arms it actually measured.
        candidates.sort(key=lambda item: (
            -sum(1 for row in item[2]["runs"] if row.get("native_power_w") is not None),
            -item[0],
        ))
        _, path, doc = candidates[0]
        chosen[workload] = (path, doc)
    return chosen


def compact_row(run: dict, log: dict, source: str, model: dict) -> dict:
    native = run.get("native_model") or {}
    row = {
        "workload": run["workload"],
        "workload_label": run.get("workload_label"),
        "topology": run["topology"],
        "topology_label": run.get("topology_label"),
        "family": run.get("family"),
        "nodes": run.get("nodes"),
        "vcs": run.get("vcs"),
        "routing": run.get("routing"),
        "vc_buf_size": run.get("vc_buf_size"),
        "status": run.get("status"),
        "qualification": run.get("qualification"),
        "delivered_packets": run.get("delivered_packets"),
        "delivered_flits": run.get("delivered_flits"),
        "effective_packet_size_flits": run.get("effective_packet_size_flits"),
        "completion_cycles": run.get("completion_cycles"),
        "latency_mean": run.get("latency_mean"),
        "latency_p50": run.get("latency_p50"),
        "latency_p95": run.get("latency_p95"),
        "latency_p99": run.get("latency_p99"),
        "hops_avg": run.get("hops_avg"),
        "throughput_packets_per_cycle": run.get("throughput_packets_per_cycle"),
        "throughput_flits_per_cycle": run.get("throughput_flits_per_cycle"),
        "accepted_packet_rate": run.get("accepted_packet_rate"),
        "resource_cost": run.get("resource_cost"),
        "native_power_w": run.get("native_power_w"),
        "native_area_mm2": run.get("native_area_mm2"),
        "native_energy_pj_per_cycle": run.get("native_energy_pj_per_cycle"),
        "total_energy_pj": run.get("total_energy_pj"),
        "power_cycles": run.get("power_cycles"),
        "native_model": {
            "status": native.get("status"),
            "model_id": native.get("model_id"),
            "technology": native.get("technology"),
            "clock_hz": native.get("clock_hz"),
            "clock_rule": native.get("clock_rule"),
            "channel_width_bits": native.get("channel_width_bits"),
            "wire_length_mm_per_latency_cycle": native.get("wire_length_mm_per_latency_cycle"),
            "energy_definition": native.get("energy_definition"),
            "limitations": native.get("limitations"),
        } if native else None,
        "source_path": source,
        "log": run.get("log"),
    }
    row["power_breakdown_w"] = log or None
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    base = json.loads(BASE_DOC.read_text())
    workloads = {item["workload_id"] for item in base["workloads"]}
    traces = {item["workload_id"]: item.get("trace_sha256") for item in base["workloads"]}
    found = candidate_runs(workloads, traces)
    chosen = choose(found)
    missing = sorted(workloads - set(chosen))
    if missing:
        print(f"no native power run for: {', '.join(missing)}", file=sys.stderr)

    workload_meta = {item["workload_id"]: item for item in base["workloads"]}
    topologies: dict[str, dict] = {}
    records: list[dict] = []
    model_ids: set[str] = set()
    for workload in sorted(chosen):
        path, doc = chosen[workload]
        relative = path.relative_to(ROOT).as_posix()
        for topology in doc.get("topologies") or []:
            topologies.setdefault(topology["topology_id"], {
                "topology_id": topology["topology_id"],
                "label": topology["label"],
                "family": topology["family"],
                "nodes": topology.get("nodes"),
            })
        for run in doc["runs"]:
            if run.get("status") != "ok":
                continue
            log_path = path.parent / (run.get("log") or "")
            log = parse_log(log_path)
            model = run.get("native_model") or {}
            if model.get("model_id"):
                model_ids.add(model["model_id"])
            records.append(compact_row(run, log, relative, model))

    first_model = next((row["native_model"] for row in records if row.get("native_model")), {})
    output = {
        "schema": "veritx/workload-power/1",
        "generated_by": "apps/studio/prototype/scripts/build_workload_power.py",
        "generated_from": "tracks/t3-topology/runs/workload-ablation/*/ablation.json (vc_buf_size=8, sim_power=1)",
        "scope": "Measured trace replay with BookSim's native 32nm power/area model. Network only; no compute, DRAM, NIC or silicon calibration. One run per workload; arms within a workload share one trace, binary and seed, but are not resource-equalised.",
        "corner": tech_corner(),
        "model": {
            "technology": first_model.get("technology"),
            "clock_hz": first_model.get("clock_hz"),
            "clock_rule": first_model.get("clock_rule"),
            "channel_width_bits": first_model.get("channel_width_bits"),
            "wire_length_mm_per_latency_cycle": first_model.get("wire_length_mm_per_latency_cycle"),
            "energy_definition": first_model.get("energy_definition"),
            "limitations": first_model.get("limitations"),
            "model_ids": sorted(model_ids),
        },
        "workloads": [
            {
                "workload_id": item["workload_id"],
                "label": item["label"],
                "nodes": item["nodes"],
                "events": item.get("events"),
                "trace_sha256": item.get("trace_sha256"),
                "yaml": item.get("yaml"),
                "trace": item.get("trace"),
                "source_path": chosen[item["workload_id"]][0].relative_to(ROOT).as_posix(),
                "arm_count": sum(1 for row in records if row["workload"] == item["workload_id"]),
            }
            for item in base["workloads"] if item["workload_id"] in chosen
        ],
        "topologies": sorted(topologies.values(), key=lambda item: item["topology_id"]),
        "runs": records,
    }

    if args.no_write:
        print(f"{len(records)} rows, {len(output['workloads'])} workloads")
        return 0
    args.out.write_text(json.dumps(output, indent=1) + "\n")
    print(f"wrote {args.out.relative_to(ROOT)} · {len(records)} rows · {len(output['workloads'])} workloads")
    print(f"model ids: {', '.join(model_ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
