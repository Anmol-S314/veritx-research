#!/usr/bin/env python3
"""Run one trace workload against every candidate topology.

Why this exists
---------------
The product's workload documents and the simulator's topology configs are
separate objects, but the older trace runner picks both from one YAML file
(``configs/trace_sweep.yaml``) and inherits each example config's buffer,
packet size and VC count.  That makes a cross-topology comparison an
apples-to-oranges mix of knobs.

This runner keeps the axes separate:

* **Workloads** are trace YAMLs: an arrival process, not a topology.
* **Topologies** are BookSim configs: a fabric, not a workload.
* Every cell is the Cartesian product, run independently.

The comparison pins ``packet_size``, ``vc_buf_size`` and
``use_noc_latency``.  VC count stays at each family's canonical minimum for
deadlock freedom and is recorded per arm; it is not silently equalised
because GEC-MECS structurally needs 6.

Output is ``ablation.json`` plus a per-workload ``summary.md`` and per-run
logs.  Missing or failed cells stay in the output as typed rows.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ablation_evidence import resource_cost, sha256, trace_stats, transform_trace
from native_power import power_evidence, prepare_model

HERE = Path(__file__).resolve().parent
TRACK = HERE.parent
REPO = TRACK.parent.parent
DEFAULT_BOOKSIM = REPO / "third_party" / "booksim2" / "src" / "booksim"
AUDITED_POWER_BOOKSIM = DEFAULT_BOOKSIM.with_name('booksim-shared-power-audited')
BOOKSIM_BASE = REPO / "third_party" / "booksim2"
PROTOTYPE_DATA = REPO / "apps" / "studio" / "prototype" / "public" / "data"

PACKET_SIZE = 5
VC_BUF_SIZE = 8
USE_NOC_LATENCY = 0
# The example configs ship different router pipelines (islip vs
# separable_input_first, 0- vs 1-cycle routing delay, credit_delay 1 vs 2).
# A topology ranking that leaves those free ranks the pipeline, not the
# fabric. Normalise them unless --raw-pipeline is requested; --set can still
# override any key for an explicit sensitivity run.
PIPELINE_OVERRIDES = {
    "credit_delay": "1",
    "routing_delay": "1",
    "vc_alloc_delay": "1",
    "sw_alloc_delay": "1",
    "st_prepare_delay": "0",
    "st_final_delay": "1",
    "input_speedup": "1",
    "output_speedup": "1",
    "internal_speedup": "1.0",
    "vc_allocator": "islip",
    "sw_allocator": "islip",
    "alloc_iters": "1",
    "hold_switch_for_packet": "0",
    "wait_for_tail_credit": "0",
}


@dataclass(frozen=True)
class Workload:
    workload_id: str
    label: str
    yaml: Path | None
    nodes: int
    trace: Path | None = None
    project: str | None = None


@dataclass(frozen=True)
class Topology:
    topology_id: str
    family: str
    label: str
    config: Path
    nodes: int
    vcs: int
    routing: str
    note: str = ""
    support: str = "product"


WORKLOADS = (
    Workload("llm_transformer", "LLM transformer · TP8 × PP8", REPO / "third_party/booksim2/src/examples/ai_workloads/llm_transformer.yaml", 64),
    Workload("moe", "MoE · dispatch/combine", REPO / "third_party/booksim2/src/examples/ai_workloads/moe.yaml", 64),
    Workload("recommendation_system", "Recommendation system", REPO / "third_party/booksim2/src/examples/ai_workloads/recommendation_system.yaml", 64),
    Workload("rnn_lstm", "RNN / LSTM", REPO / "third_party/booksim2/src/examples/ai_workloads/rnn_lstm.yaml", 64),
    Workload("vision_transformer", "Vision transformer", REPO / "third_party/booksim2/src/examples/ai_workloads/vision_transformer.yaml", 64),
    Workload("basic", "Basic example traffic", REPO / "third_party/booksim2/src/examples/workload2.yaml", 64),
    Workload("mixtral-8x7b-64tiles", "Mixtral 8×7B", None, 64,
             trace=REPO / "runs/studio-store/projects/projects/p-0d2849c85ff0/runs/01a13fea-b7f9-784f-82ec-aa8797360460/bundle/analyses/network_completion/run/workload.trace",
             project="Mixtral 8x7B 64-tile dense demo"),
    Workload("mwa-fx-correlator", "MWA FX correlator", None, 64,
             trace=REPO / "runs/studio-store/projects/projects/p-d037b1c85839/runs/01a13fdd-6b4b-71e0-9a14-e6854bb39556/bundle/analyses/network_completion/run/workload.trace",
             project="MWA correlator all-to-all demo"),
    Workload("astr-llm-70b-tp4", "Astr LLM 70B · TP4", None, 64,
             trace=REPO / "runs/studio-store/projects/projects/p-b2ed4e030a8a/runs/01a11c12-4485-7ad2-bd67-1dd089dcc1c4/bundle/analyses/network_completion/run/workload.trace",
             project="Astr LLM 70B · TP4"),
    Workload("llama-3.1-8b-64tiles", "Llama-3.1-8B", None, 64,
             trace=REPO / "runs/studio-store/projects/projects/p-35a65d7b80be/runs/01a11d0d-dec2-76c4-8db6-aa4b96fcfdce/bundle/analyses/network_completion/run/workload.trace",
             project="Llama-3.1-8B · GEC hybrid · 64 endpoints · TP8"),
    Workload("qwen3-moe", "Qwen3 MoE", None, 64,
             trace=REPO / "runs/studio-store/projects/projects/p-72d52e15419d/runs/01a12f43-2c8e-7747-b9b4-2062469b5d1c/bundle/analyses/network_completion/run/workload.trace",
             project="Qwen3-30B-A3B Study"),
)

TOPOLOGIES = (
    Topology("mesh8x8", "MESH", "8×8 mesh", REPO / "third_party/booksim2/src/examples/mesh88_lat", 64, 2, "dor"),
    Topology("torus8x8", "TORUS", "8×8 torus", REPO / "third_party/booksim2/src/examples/torus88", 64, 2, "dim_order"),
    Topology("cmesh", "CONCENTRATED_MESH", "CMesh", REPO / "third_party/booksim2/src/examples/cmeshconfig", 64, 2, "dor_no_express"),
    Topology("fattree", "FAT_TREE", "Fat-tree", REPO / "third_party/booksim2/src/examples/fattree_config", 64, 2, "nca"),
    Topology("flatfly", "FLATFLY", "Flatfly", REPO / "third_party/booksim2/src/examples/flatflyconfig", 64, 2, "xyyx"),
    Topology("srota8x8", "SROTA", "SROTA 8×8", TRACK / "configs/srota64_rowcol.cfg", 64, 4, "o1turn row+column",
             "Scaled from srota16.cfg (k=8, c=1); 64-terminal qualification is not established.",
             "research"),
    Topology("gec_mecs", "GEC_MECS", "GEC MECS", REPO / "third_party/booksim2/src/examples/mecs_gec.config", 64, 6, "dor",
             "", "research"),
    Topology("gec_hybrid", "GEC_HYBRID", "GEC hybrid", REPO / "third_party/booksim2/src/examples/hybrid_gec.config", 64, 6, "hybrid",
             "", "research"),
    Topology("qtree", "QTREE", "QTree", TRACK / "configs/qtree64.cfg", 64, 4, "nca",
             "BookSim-only research fixture; product registry stage EXECUTABLE=NO.",
             "booksim-only"),
    Topology("tree4", "TREE4", "Tree4", TRACK / "configs/tree4_64.cfg", 64, 4, "nca",
             "BookSim-only research fixture; product registry stage EXECUTABLE=NO.",
             "booksim-only"),
    Topology("ring", "RING", "64-node ring", TRACK / "configs/ring64.cfg", 64, 2, "dim_order",
             "BookSim-only test fixture; product registry stage EXECUTABLE=NO.",
             "booksim-only"),
    Topology("fly64", "FLY", "Fly", TRACK / "configs/fly64.cfg", 64, 4, "dest_tag",
             "BookSim-only 4-ary, 3-stage butterfly; product registry stage EXECUTABLE=NO.",
             "booksim-only"),
)


def rel_to_booksim(path: Path) -> str:
    return os.path.relpath(path.resolve(), BOOKSIM_BASE)


def trace_path(workload: Workload, out_root: Path) -> Path:
    suffix = ".csv" if workload.yaml else ".trace"
    return out_root / "traces" / f"{workload.workload_id}_n{workload.nodes}{suffix}"


def _cfg_value(text: str, key: str) -> str | None:
    found = None
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*([^;/\s]+)", re.MULTILINE)
    for match in pattern.finditer(text):
        found = match.group(1).strip()
    return found


def build_config(topology: Topology, trace: Path, packets: Path, dest: Path,
                 packet_size: int, vc_buf_size: int, use_noc_latency: int,
                 overrides: dict[str, str], pipeline: dict[str, str],
                 classes: int = 1) -> Path:
    base = topology.config.read_text()
    lines = [line for line in base.splitlines()
             if not re.match(r"^\s*(trace_file|trace_packet_log|sim_type|traffic|injection_rate)\s*=", line)]
    lines += [
        "",
        "// --- injected by ablate_workloads.py ---",
        "sim_type = trace;",
        f"trace_file = {rel_to_booksim(trace)};",
        f"trace_packet_log = {rel_to_booksim(packets)};",
        f"packet_size = {packet_size};",
        f"vc_buf_size = {vc_buf_size};",
        f"use_noc_latency = {use_noc_latency};",
        f"num_vcs = {topology.vcs};",
    ]
    if classes > 1:
        lines.append(f"classes = {classes};")
    for key, value in {**pipeline, **overrides}.items():
        lines.append(f"{key} = {value};")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n")
    return dest


def read_knobs(path: Path) -> dict[str, str]:
    """Every assignment in the final run config, last value wins."""
    knobs: dict[str, str] = {}
    if not path.exists():
        return knobs
    for line in path.read_text().splitlines():
        line = line.split("//", 1)[0].strip()
        match = re.match(r"^([A-Za-z_][\w.]*)\s*=\s*([^;]+);?\s*$", line)
        if match:
            knobs[match.group(1)] = match.group(2).strip()
    return knobs


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, math.ceil(pct / 100 * len(ordered)) - 1))
    return ordered[rank]


def parse_packets(path: Path) -> dict:
    if not path.exists():
        return {"status": "no_packets_out"}
    latencies: list[float] = []
    hops: list[float] = []
    flits = 0
    sizes: set[int] = set()
    arrival = 0.0
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                latency, hop_count, size_value, arrived = (float(row[key]) for key in ("total_latency", "hops", "packet_size_flits", "arrival_time"))
                if not all(math.isfinite(value) and value >= 0 for value in (latency, hop_count, size_value, arrived)) or not size_value.is_integer() or size_value < 1:
                    raise ValueError("invalid packet metric")
                latencies.append(latency)
                hops.append(hop_count)
                size = int(size_value)
                flits += size
                sizes.add(size)
                arrival = max(arrival, arrived)
            except (KeyError, TypeError, ValueError):
                return {"status": "invalid_packets_out"}
    if not latencies:
        return {"status": "empty_packets_out"}
    delivered = len(latencies)
    mean = sum(latencies) / delivered
    return {
        "status": "ok",
        "delivered_packets": delivered,
        "delivered_flits": flits,
        "effective_packet_size_flits": sorted(sizes),
        "completion_cycles": arrival,
        "latency_mean": mean,
        "latency_p50": _percentile(latencies, 50),
        "latency_p95": _percentile(latencies, 95),
        "latency_p99": _percentile(latencies, 99),
        "hops_avg": sum(hops) / delivered,
        "throughput_packets_per_cycle": delivered / arrival if arrival else None,
        "throughput_flits_per_cycle": flits / arrival if arrival else None,
    }


LOG_PATTERNS = {
    "accepted_packet_rate": r"Accepted packet rate average\s*=\s*([-0-9.e]+)",
    "injected_packet_rate": r"Injected packet rate average\s*=\s*([-0-9.e]+)",
    "booksim_total_seconds": r"Total run time\s+([-0-9.e]+)",
}


def parse_log(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(errors="replace")
    out = {}
    for key, pattern in LOG_PATTERNS.items():
        found = re.findall(pattern, text)
        if found:
            out[key] = float(found[-1])
    out["resource_cost"] = resource_cost(text)
    return out


def trace_power_evidence(text: str, family: str, status: str, returncode: int,
                         model: dict | None) -> dict:
    evidence = power_evidence(text, family, status, returncode, model)
    evidence.update(total_energy_pj=None, power_cycles=None)
    if model is None or status != 'ok' or returncode != 0:
        return evidence
    intervals = re.findall(r'^- Completion Time:\s*([\d.eE+-]+)\s*$', text, re.M)
    cycles = float(intervals[0]) if len(intervals) == 1 else None
    if cycles is None or not math.isfinite(cycles) or cycles <= 0:
        return evidence
    evidence['power_cycles'] = cycles
    if evidence['native_model']['status'] == 'AVAILABLE':
        evidence['total_energy_pj'] = evidence['native_energy_pj_per_cycle'] * cycles
        evidence['native_model']['energy_definition'] = (
            'native total W / model clock Hz * OCN Completion Time * 1e12; '
            'network pJ over the full power-counter interval, not packet-arrival cycles')
    elif evidence['native_model']['status'] == 'UNSUPPORTED':
        # Preserve actual emitted diagnostics without promoting unaudited coverage.
        values = {}
        for key, label in [('power_w', 'Total Power'), ('area_mm2', 'Total Area')]:
            matches = re.findall(rf'^- {label}:\s*([\d.eE+-]+)\s*$', text, re.M)
            value = float(matches[0]) if len(matches) == 1 else None
            if value is None or not math.isfinite(value) or value <= 0:
                return evidence
            values[key] = value
        evidence['native_output'] = {
            **values, 'total_energy_pj': values['power_w'] / model['clock_hz'] * cycles * 1e12,
            'power_cycles': cycles, 'model': model,
            'status': 'INCOMPLETE' if evidence['native_model'].get('coverage_audit', {}).get('status') == 'INCOMPLETE' else 'UNAUDITED',
            'reason': evidence['native_model']['reason'],
            'energy_definition': 'emitted native W / technology clock Hz * OCN Completion Time * 1e12',
        }
    return evidence


def run_cell(workload: Workload, topology: Topology, out_root: Path, booksim: str,
             timeout: int, force: bool, knobs: dict, overrides: dict[str, str],
             pipeline: dict[str, str], trace_info: dict | None = None,
             binary_sha256: str | None = None) -> dict:
    trace = trace_path(workload, out_root)
    cell = out_root / "cells" / workload.workload_id / topology.topology_id
    packets = cell / "packets_out.csv"
    log = cell / "booksim.log"
    cfg = cell / "run.cfg"
    row = {
        "workload": workload.workload_id,
        "workload_label": workload.label,
        "topology": topology.topology_id,
        "topology_label": topology.label,
        "family": topology.family,
        "nodes": topology.nodes,
        "vcs": topology.vcs,
        "routing": topology.routing,
        "packet_size": knobs["packet_size"],
        "vc_buf_size": knobs["vc_buf_size"],
        "use_noc_latency": knobs["use_noc_latency"],
    }
    if workload.nodes != topology.nodes:
        return {**row, "status": "skipped_node_mismatch",
                "note": f"workload needs {workload.nodes} nodes, topology has {topology.nodes}"}
    if not trace.exists():
        return {**row, "status": "no_trace", "note": _display(trace)}
    info = trace_info if trace_info is not None else trace_stats(trace)
    if info.get("max_node") is not None and info["max_node"] >= topology.nodes:
        return {**row, "status": "invalid_trace", "note": "trace endpoint exceeds the fabric"}
    pipeline = {"seed": "1", **pipeline}
    power_requested = int(overrides.get('sim_power', pipeline.get('sim_power',
        _cfg_value(topology.config.read_text(), 'sim_power') or '0'))) > 0
    native_model = prepare_model(REPO, cell, Path(booksim)) if power_requested else None
    if power_requested:
        # The technology path is server-owned, never a browser-supplied path.
        overrides = {**overrides, 'channel_width': '128',
                     'tech_file': str((cell / 'native-model/techfile.txt').resolve())}
    build_config(topology, trace, packets, cfg, knobs["packet_size"],
                 knobs["vc_buf_size"], knobs["use_noc_latency"], overrides, pipeline,
                 info.get("classes", 1))
    merged = read_knobs(cfg)
    row.update({
        "knobs": merged, "trace_sha256": info["trace_sha256"],
        "active_nodes": info["active_nodes"], "expected_network_packets": info["expected_network_packets"],
        "arm_sha256": sha256(topology.config),
        "binary_sha256": binary_sha256 or sha256(Path(booksim)),
        "simulator_seed": int(merged.get("seed", 1)),
        "declared_buffer_flits_per_input": topology.vcs * knobs["vc_buf_size"],
        "packet_size_source": "trace", "qualification": "NOT_ESTABLISHED",
        "execution_scope": "network trace replay; no model compute or DRAM timing",
    })
    identity = {key: row[key] for key in ("trace_sha256", "binary_sha256")}
    identity["config_sha256"] = sha256(cfg)
    if native_model:
        identity['tech_sha256'] = native_model['tech_sha256']
        identity['power_evidence_version'] = 3
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    result_path = cell / "result.json"
    if result_path.is_file() and packets.is_file() and not force:
        try:
            previous = json.loads(result_path.read_text())
        except (OSError, json.JSONDecodeError):
            previous = {}
        if previous.get("execution_fingerprint") == fingerprint and previous.get("status") == "ok" and previous.get("packets_sha256") == sha256(packets):
            return {**previous, **row, "cached": True}
    # Never parse a previous process's packet file after this process fails.
    packets.unlink(missing_ok=True)
    command = [booksim, str(cfg)]
    started = datetime.now(timezone.utc)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, cwd=BOOKSIM_BASE)
        stdout, stderr, rc = result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        stdout, stderr, rc = "", "timeout", -1
    cell.mkdir(parents=True, exist_ok=True)
    log.write_text("$ " + " ".join(command) + "\n" + stdout + ("\n--- stderr ---\n" + stderr if stderr else ""))
    metrics = parse_packets(packets)
    status = metrics.get("status", "no_output")
    if re.search(r"Simulation unstable", stdout + stderr):
        status = "unstable"
    elif rc == -1:
        status = "timeout"
    elif rc != 0:
        status = "failed"
    elif status == "ok" and metrics.get("delivered_packets") != info["expected_network_packets"]:
        status = "incomplete"
    result_row = {**row, **metrics, **parse_log(log),
                  **trace_power_evidence(stdout, topology.family, status, rc, native_model),
                  "status": status, "returncode": rc,
                  "execution_fingerprint": fingerprint,
                  "packets_sha256": sha256(packets) if packets.is_file() else None,
                  "seconds": (datetime.now(timezone.utc) - started).total_seconds(),
                  "log": str(log.relative_to(out_root))}
    temporary = result_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(result_row, indent=2) + "\n")
    temporary.replace(result_path)
    return result_row


def write_summary(path: Path, rows: list[dict], common: dict, workloads: list[Workload]) -> None:
    ok = [row for row in rows if row.get("status") == "ok"]
    lines = [
        "# Workload × topology ablation",
        "",
        f"- Common: packet_size={common['packet_size']}, vc_buf_size={common['vc_buf_size']}, "
        f"use_noc_latency={common['use_noc_latency']}, trace_seed={common.get('seed', '—')}",
        f"- Cells: {len(rows)} attempted, {len(ok)} ok",
        "",
    ]
    for workload in workloads:
        cells = [row for row in rows if row["workload"] == workload.workload_id]
        if not cells:
            continue
        lines += [f"## {workload.label}", "",
                  "| topology | VCs | routing | p50 | p95 | p99 | completion | delivered | hops | status |",
                  "|---|---:|---|---:|---:|---:|---:|---:|---:|---|"]
        for row in sorted(cells, key=lambda item: (item.get("latency_p95") is None,
                                                   item.get("latency_p95") or 0)):
            def fmt(key: str, digits: int = 1) -> str:
                value = row.get(key)
                return f"{value:.{digits}f}" if isinstance(value, (int, float)) else "—"
            lines.append(
                f"| `{row['topology']}` | {row['vcs']} | {row['routing']} | {fmt('latency_p50')} | "
                f"{fmt('latency_p95')} | {fmt('latency_p99')} | {fmt('completion_cycles', 0)} | "
                f"{row.get('delivered_packets', '—')} | {fmt('hops_avg', 2)} | {row['status']} |")
        lines.append("")
    path.write_text("\n".join(lines) + "\n")


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def _pick(spec: str, available: tuple, kind: str):
    if spec.strip().lower() in ("", "all"):
        return list(available)
    key = "workload_id" if kind == "workload" else "topology_id"
    by_id = {getattr(item, key): item for item in available}
    names = list(dict.fromkeys(name.strip() for name in spec.split(",") if name.strip()))
    bad = [name for name in names if name not in by_id]
    if bad:
        raise SystemExit(f"unknown {kind}: {bad}\navailable: {sorted(by_id)}")
    return [by_id[name] for name in names]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=TRACK / "runs" / "workload-ablation")
    parser.add_argument("--booksim", help="explicit simulator path; native-power runs default to booksim-shared-power-audited")
    parser.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 4))
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--seed", type=int, default=1,
                        help="trace-generation seed; fixed so a rerun changes knobs, not traffic")
    parser.add_argument("--replay-catalog", type=Path, help="reuse the catalog's exact traces; do not regenerate traffic")
    parser.add_argument("--trace-packet-size", type=int, help="explicitly rewrite each event's size, in flits")
    parser.add_argument("--time-scale", default="1", help="scale requested injection cycles (0.01–100)")
    parser.add_argument("--burst-window", type=int, default=0, help="coalesce requests into cycle windows; 0 preserves spacing")
    parser.add_argument("--rank-stride", type=int, default=1, help="coprime affine placement stride; does not add active ranks")
    parser.add_argument("--rank-offset", type=int, default=0, help="affine placement offset, modulo fabric endpoints")
    parser.add_argument("--workloads", default="all", help="comma list or 'all'")
    parser.add_argument("--topologies", default="all", help="comma list or 'all'")
    parser.add_argument("--packet-size", type=int, default=PACKET_SIZE)
    parser.add_argument("--vc-buf-size", type=int, default=VC_BUF_SIZE)
    parser.add_argument("--use-noc-latency", type=int, choices=(0, 1), default=USE_NOC_LATENCY)
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VAL",
                        help="extra BookSim override, repeatable (e.g. --set alloc_iters=2); "
                             "recorded per cell. Structural axes are refused.")
    parser.add_argument("--raw-pipeline", action="store_true",
                        help="keep each example config's allocator/delay values instead of "
                             "normalising the router pipeline")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--copy-to-prototype", action="store_true")
    args = parser.parse_args()

    reserved = {"topology", "sim_type", "trace_file", "trace_packet_log",
                "packet_size", "vc_buf_size", "use_noc_latency", "num_vcs", "seed",
                "k", "n", "c", "x", "y", "xr", "yr", "o", "d", "mesh", "hybrid", "subnets", "routing_function"}
    overrides: dict[str, str] = {}
    for item in args.set:
        if "=" not in item:
            parser.error(f"--set expects KEY=VAL, got {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        if key in reserved:
            parser.error(f"--set {key} is a structural axis; use the dedicated flag or the arm table")
        overrides[key] = value.strip()

    if args.booksim is None:
        args.booksim = str(AUDITED_POWER_BOOKSIM if int(overrides.get('sim_power', '0')) > 0 else DEFAULT_BOOKSIM)
        if not Path(args.booksim).is_file():
            parser.error(f"simulator missing: {args.booksim}; build native power with make -C third_party/booksim2/src PROG=booksim-shared-power-audited")

    workloads = _pick(args.workloads, WORKLOADS, "workload")
    topologies = _pick(args.topologies, TOPOLOGIES, "topology")
    knobs = {
        "packet_size": args.packet_size,
        "vc_buf_size": args.vc_buf_size,
        "use_noc_latency": args.use_noc_latency,
    }
    pipeline = {} if args.raw_pipeline else dict(PIPELINE_OVERRIDES)
    pipeline["seed"] = str(args.seed)
    if not 0 <= args.seed <= 2_147_483_647:
        parser.error("seed must be between 0 and 2147483647")
    if not 1 <= args.packet_size <= 1024 or not 1 <= args.vc_buf_size <= 4096 or not 1 <= args.jobs <= 16:
        parser.error("packet size, buffer depth or jobs is outside its supported range")

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    replay = json.loads(args.replay_catalog.read_text()) if args.replay_catalog else None
    replay_workloads = {w["workload_id"]: w for w in replay["workloads"]} if replay else {}
    evidence: dict[str, dict] = {}
    for workload in workloads:
        trace = trace_path(workload, out)
        source = out / "source-traces" / trace.name
        source.parent.mkdir(parents=True, exist_ok=True)
        meta = replay_workloads.get(workload.workload_id) if replay else None
        if replay:
            if not meta or not (meta.get("replay_trace") or meta.get("trace")):
                parser.error(f"no frozen trace for {workload.workload_id} in the replay catalog")
            frozen = Path(meta.get("replay_trace") or meta["trace"])
            frozen = frozen if frozen.is_absolute() else REPO / frozen
            if meta.get("trace_sha256") and sha256(frozen) != meta["trace_sha256"]:
                parser.error(f"frozen trace identity changed for {workload.workload_id}")
            if source.resolve() != frozen.resolve():
                shutil.copy2(frozen, source)
        elif workload.yaml is not None:
            command = [sys.executable, str(HERE / "gen_trace.py"), str(workload.yaml), str(source), "--seed", str(args.seed)]
            subprocess.run(command, check=True)
        elif workload.trace is not None and workload.trace.is_file():
            shutil.copy2(workload.trace, source)
        else:
            parser.error(f"trace source is missing for {workload.workload_id}")
        try:
            stats = transform_trace(source, trace, workload.nodes,
                packet_flits=args.trace_packet_size, time_scale=args.time_scale,
                burst_window=args.burst_window, rank_stride=args.rank_stride, rank_offset=args.rank_offset)
        except ValueError as error:
            parser.error(str(error))
        stats.update({"source_trace_sha256": sha256(source), "replay_trace": _display(trace),
                      "trace_seed": (meta.get("trace_seed", replay.get("common", {}).get("seed"))
                                     if replay and workload.yaml else args.seed if workload.yaml else None)})
        evidence[workload.workload_id] = stats
        print(f"[trace] {workload.workload_id}: {stats['active_nodes']}/{workload.nodes} active; {stats['trace_sha256']}")

    binary_sha256 = sha256(Path(args.booksim))
    cells = [(workload, topology) for workload in workloads for topology in topologies]
    with ThreadPoolExecutor(args.jobs) as pool:
        rows = list(pool.map(lambda pair: run_cell(pair[0], pair[1], out, args.booksim,
                                                  args.timeout, args.force, knobs, overrides, pipeline,
                                                  evidence[pair[0].workload_id], binary_sha256), cells))

    for row in rows:
        print(f"[{row.get('status')}] {row['workload']:24s} {row['topology']:12s}"
              + (f"  p95={row['latency_p95']:.1f}" if row.get("latency_p95") is not None else ""))

    common = {
        **knobs,
        "seed": args.seed,
        "trace_replay": bool(replay),
        "workload_variant": {"packet_flits": args.trace_packet_size, "time_scale": args.time_scale,
                             "burst_window": args.burst_window, "rank_stride": args.rank_stride, "rank_offset": args.rank_offset},
        "comparison_scope": "Network-only; unequal resource budgets; qualification and hardware calibration not established.",
        "overrides": {**pipeline, **overrides},
        "pipeline_normalized": not args.raw_pipeline,
        "note": "VC count is each family's canonical minimum; it is recorded, not equalised.",
    }
    document = {
        "schema": "veritx/workload-ablation/1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "tracks/t3-topology/scripts/ablate_workloads.py",
        "common": common,
        "runs": rows,
    }
    document["workloads"] = []
    for w in workloads:
        stats = evidence[w.workload_id]
        document["workloads"].append({
            **stats,
            "workload_id": w.workload_id,
            "label": w.label,
            "nodes": w.nodes,
            "active_nodes": stats["active_nodes"],
            "events": stats["events"],
            "yaml": _display(w.yaml) if w.yaml else None,
            "trace": _display(w.trace) if w.trace else _display(trace_path(w, out)),
            "project": w.project,
        })
    document["topologies"] = [
        {"topology_id": t.topology_id, "family": t.family, "label": t.label,
         "nodes": t.nodes, "config": str(t.config.relative_to(REPO)), "note": t.note,
         "support": t.support} for t in topologies]
    (out / "ablation.json").write_text(json.dumps(document, indent=2) + "\n")
    write_summary(out / "summary.md", rows, common, workloads)

    failures = [row for row in rows if row.get("status") not in ("ok",)]
    if args.copy_to_prototype:
        PROTOTYPE_DATA.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out / "ablation.json", PROTOTYPE_DATA / "workload_ablation.json")
        print(f"[copy] {PROTOTYPE_DATA / 'workload_ablation.json'}")
    print(f"[done] {len(rows) - len(failures)}/{len(rows)} ok · {_display(out)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
