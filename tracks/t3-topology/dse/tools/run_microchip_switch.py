#!/usr/bin/env python3
"""Gen 6-class 16-port switch fabric: a real BookSim topology experiment.

The workload and the port model are AUTHORED and SYNTHETIC. The cycle-level
fabric evaluation is real: one FabricCompiler compilation plus one
FabricEvaluator/BookSim run per topology, using the same certified path as
``tests/test_fabric_evaluator_multiclass_requirements.py``.

This is not a Switchtec model and not a PCIe protocol stack. See
``docs/product/microchip-experiment.md`` for the claim boundary.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

DSE = Path(__file__).resolve().parents[1]
if str(DSE) not in sys.path:
    sys.path.insert(0, str(DSE))

from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.application.fabric_evaluator import (  # noqa: E402
    BACKEND_UNAVAILABLE, EVALUATED, EvaluationOptions, FabricEvaluator,
)
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.model.compile_request_v4 import CompileRequestV4  # noqa: E402
from veritx_dse.model.topology_intent import (  # noqa: E402
    FatTreeIntent, FlatFlyIntent, GecMode, GecTopologyIntent,
)
from veritx_dse.model.srota_intent import SrotaIntent  # noqa: E402
from veritx_dse.product.service import parse_request_doc  # noqa: E402
from veritx_dse.simulation.booksim import find_booksim_bin  # noqa: E402
from veritx_dse.workload.intent_lowering import lower_compile_workload  # noqa: E402

TEMPLATE_REL = "tracks/t3-topology/examples/switch_gen6_class-v4.json"
OUT_DIR_REL = "tracks/t3-topology/data/microchip"
DEFAULT_COMMAND = (
    "PYTHONPATH=tracks/t3-topology/dse "
    "python3 tracks/t3-topology/dse/tools/run_microchip_switch.py"
)
NETWORK_CLOCK_HZ = 1_000_000_000
TIMEOUT_S = 180

#: The five 16-endpoint families. A family the compiler or backend refuses is
#: recorded as a refusal, never silently skipped.
TOPOLOGY_SPECS: tuple[dict[str, Any], ...] = (
    {
        "topology_id": "mesh",
        "label": "4x4 mesh",
        "topology": {"kind": "mesh", "side_length": 4, "concentration": 1},
    },
    {
        "topology_id": "fattree",
        "label": "fat tree (switch radix 4, 2 tiers)",
        "topology": {"kind": "fattree", "switch_radix": 4, "level_count": 2},
    },
    {
        "topology_id": "flatfly",
        "label": "flatfly (radix 4 x 2 dimensions, concentration 1)",
        "topology": {
            "kind": "flatfly", "radix_per_dimension": 4,
            "dimension_count": 2, "concentration": 1,
        },
    },
    {
        "topology_id": "srota",
        "label": "SROTA Plane D (4x4, concentration 1)",
        "topology": {
            "kind": "srota", "side_length": 4, "concentration": 1,
            "mecs_row": True, "mecs_col": True, "drop_latency": 1,
            "planes": ["d"], "island_columns": [],
            "path_shapes": ["column", "row"], "vc_policy": "shape",
            "sidebuf_enable": True, "sidebuf_watermark": 6,
            "tel_period": 4, "tel_latency": 8,
        },
    },
    {
        "topology_id": "gec_mecs",
        "label": "GEC MECS (4x4, one shared channel group per dimension)",
        "topology": {
            "kind": "gec", "mode": "multidrop", "grid_side_length": 4,
            "concentration": 1,
            "express_channel_groups_per_dimension": 1,
            "destinations_per_express_channel": 3,
        },
    },
)

EXPECTED_CLASSES = (
    "incast_ssd0", "multicast_equiv", "read_256k", "read_4k",
    "write_256k", "write_4k",
)

#: Present-only metric keys. Missing keys stay missing; the report names the
#: absence instead of filling a zero.
_METRIC_KEYS = (
    "completion_cycles", "sample_window_cycles", "packet_latency_avg",
    "flit_latency_avg", "p50", "p95", "p99", "honest_latency",
    "pkt_count", "loaded_trace_packets", "injected_trace_packets",
    "delivered_packets", "flits_injected", "flits_accepted",
    "hops", "throughput",
)


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO.resolve()))
    except ValueError:
        return str(path)


def _jsonable(value: Any) -> Any:
    """JSON-safe projection; never invents or rounds a measurement."""
    if isinstance(value, Fraction):
        return {"num": value.numerator, "den": value.denominator}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Path):
        return _rel(value)
    return value


def load_template_doc(*, repo_root: Path = REPO) -> dict[str, Any]:
    path = repo_root / TEMPLATE_REL
    return json.loads(path.read_text(encoding="utf-8"))


def build_request(*, repo_root: Path = REPO) -> CompileRequestV4:
    """Build the template request. This is the mesh-shaped base design."""
    return parse_request_doc(load_template_doc(repo_root=repo_root))


def topology_request(request: CompileRequestV4,
                     topology_id: str) -> CompileRequestV4:
    """Re-declare ONLY the topology authority; the workload is unchanged."""
    if topology_id == "mesh":
        return request
    if topology_id == "fattree":
        return replace(
            request,
            topology=FatTreeIntent(switch_radix=4, level_count=2))
    if topology_id == "flatfly":
        return replace(
            request,
            topology=FlatFlyIntent(radix_per_dimension=4,
                                   dimension_count=2, concentration=1))
    if topology_id == "srota":
        return replace(
            request,
            topology=SrotaIntent(
                side_length=4, concentration=1, mecs_row=True, mecs_col=True,
                drop_latency=1, planes=frozenset({"d"}),
                island_columns=(), path_shapes=frozenset({"row", "column"}),
                vc_policy="shape", sidebuf_enable=True,
                sidebuf_watermark=6, tel_period=4, tel_latency=8))
    if topology_id == "gec_mecs":
        return replace(
            request,
            topology=GecTopologyIntent(
                mode=GecMode.MULTIDROP, grid_side_length=4, concentration=1,
                express_channel_groups_per_dimension=1,
                destinations_per_express_channel=3))
    raise ValueError(f"unknown topology_id {topology_id!r}")


def build_requests(*, repo_root: Path = REPO) -> dict[str, CompileRequestV4]:
    base = build_request(repo_root=repo_root)
    return {spec["topology_id"]: topology_request(base, spec["topology_id"])
            for spec in TOPOLOGY_SPECS}


def workload_summary(request: CompileRequestV4) -> dict[str, Any]:
    by_class: dict[str, dict[str, Any]] = {}
    for profile in request.workload.traffic_profiles:
        row = by_class.setdefault(
            profile.traffic_class,
            {"profiles": 0, "payload_bytes": 0})
        row["profiles"] += 1
        row["payload_bytes"] += profile.payload_bytes
    read_bytes = sum(row["payload_bytes"] for cls, row in by_class.items()
                     if cls.startswith("read_"))
    write_bytes = sum(row["payload_bytes"] for cls, row in by_class.items()
                      if cls.startswith("write_"))
    base = read_bytes + write_bytes
    return {
        "rank_count": request.total_nodes,
        "host_ranks": list(range(0, 8)),
        "ssd_ranks": list(range(8, 16)),
        "profile_count": len(request.workload.traffic_profiles),
        "classes": sorted(by_class),
        "expected_classes": list(EXPECTED_CLASSES),
        "per_class": {
            cls: dict(by_class[cls]) for cls in sorted(by_class)},
        "base_read_bytes": read_bytes,
        "base_write_bytes": write_bytes,
        "base_read_share": (read_bytes / base) if base else None,
        "base_write_share": (write_bytes / base) if base else None,
        "note": (
            "70/30 is exact for the read_* / write_* base classes by "
            "declared payload bytes; the incast and multicast-equivalent "
            "overlay classes are additional."),
    }


def _metric_availability(metrics: dict[str, Any]) -> dict[str, str]:
    missing: dict[str, str] = {}
    if "hops" not in metrics:
        missing["hops"] = (
            "NOT EMITTED: the authenticated BookSim stats carried an empty "
            "hops map; no mean-hop value is claimed.")
    if "throughput" not in metrics:
        missing["throughput"] = (
            "NOT EMITTED: BookSim printed no native throughput key; no "
            "accepted-rate metric is claimed. See derived counters below.")
    return missing


def _derived_rates(metrics: dict[str, Any]) -> dict[str, Any]:
    """Explicit arithmetic on reported counters, labelled as derived."""
    cycles = metrics.get("completion_cycles")
    if not isinstance(cycles, (int, float)) or cycles <= 0:
        return {}
    out: dict[str, Any] = {
        "basis": "derived from reported counters; not a BookSim metric"}
    flits = metrics.get("flits_accepted")
    if isinstance(flits, (int, float)):
        out["accepted_flit_rate_flits_per_cycle"] = flits / cycles
    packets = metrics.get("loaded_trace_packets")
    if isinstance(packets, (int, float)):
        out["loaded_packet_rate_packets_per_cycle"] = packets / cycles
    return out


def _class_metrics(outcome: Any) -> dict[str, Any]:
    performance = outcome.performance_result or {}
    block = performance.get("traffic_class_metrics") or {}
    if not block:
        return {"class_names": [], "classes": [],
                "note": "no digest-bound class block was attached"}
    return {
        "class_names": list(block.get("class_names") or []),
        "flit_width_bits": block.get("flit_width_bits"),
        "classes": _jsonable(block.get("classes") or []),
        "interpretation": (
            "Reported as printed by the BookSim build. The per-class flit "
            "counters reconcile with the aggregate flit total; the "
            "per-class latency pkt_count values do not reconcile with the "
            "aggregate trace-request count or with class volume, so "
            "class-level percentiles are diagnostic only."),
    }


def _evidence_fidelity(outcome: Any) -> dict[str, Any]:
    """Read only the producer/fidelity labels from the evidence artifact."""
    path = getattr(outcome, "evidence_path", None)
    if not path:
        return {}
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(doc, dict):
        return {}
    return {
        "execution_fidelity": doc.get("execution_fidelity"),
        "producer_dirty": doc.get("producer_dirty"),
        "producer_source_revision": doc.get("producer_source_revision"),
        "build_recipe_version": doc.get("build_recipe_version"),
        "seed": doc.get("seed"),
    }


def evaluate_topology(request: CompileRequestV4, spec: dict[str, Any], *,
                      binary: Path, repo_root: Path = REPO,
                      timeout_s: int = TIMEOUT_S,
                      run_dir: Path | None = None) -> dict[str, Any]:
    """Compile and evaluate one topology. Returns evidence, never a guess."""
    entry: dict[str, Any] = {
        "topology_id": spec["topology_id"],
        "label": spec["label"],
        "topology": dict(spec["topology"]),
        "design_hash": request.design_hash(),
    }
    started = time.perf_counter()
    compilation = FabricCompiler().compile(request)
    entry["compilation"] = {
        "status": compilation.status,
        "certificate_overall": getattr(
            getattr(compilation, "certificate", None), "overall", None),
        "error": str(compilation.error) if compilation.error else None,
    }
    if compilation.status != "COMPILED":
        entry.update({
            "status": "COMPILE_REFUSED",
            "reason": str(compilation.error),
            "wall_time_s": round(time.perf_counter() - started, 3),
        })
        return entry

    try:
        lowered = lower_compile_workload(request)
        entry["lowering"] = {
            "classes": list(lowered.classes),
            "operation_count": len(lowered.graph.operations),
        }
        outcome = FabricEvaluator().evaluate(
            compilation, lowered.graph,
            EvaluationOptions(
                binary=binary, repo_root=str(repo_root),
                network_clock_hz=NETWORK_CLOCK_HZ,
                timeout_s=timeout_s,
                run_dir=str(run_dir) if run_dir is not None else None))
    except Exception as exc:                            # noqa: BLE001
        entry.update({
            "status": "EVALUATION_ERROR",
            "reason": f"{type(exc).__name__}: {exc}",
            "wall_time_s": round(time.perf_counter() - started, 3),
        })
        return entry

    entry["status"] = outcome.status
    entry["reason"] = outcome.reason
    entry["backend"] = outcome.backend
    entry["backend_profile"] = outcome.backend_profile
    entry["fidelity_warning"] = outcome.fidelity_warning
    if outcome.status == EVALUATED:
        metrics = {key: outcome.metrics[key] for key in _METRIC_KEYS
                   if key in (outcome.metrics or {})}
        entry["metrics"] = metrics
        entry["metric_availability"] = _metric_availability(metrics)
        entry["derived"] = _derived_rates(metrics)
        entry["class_metrics"] = _class_metrics(outcome)
        entry["evidence"] = {
            "evidence_path": _rel(Path(outcome.evidence_path))
            if outcome.evidence_path else None,
            "raw_evidence_digest": outcome.raw_evidence_digest,
            "stats_digest": outcome.stats_digest,
            "backend_config_hash": outcome.backend_config_hash,
            "backend_input_hash": outcome.backend_input_hash,
            "producer_identity": outcome.producer_identity,
            **_evidence_fidelity(outcome),
        }
        entry["network_traffic_window"] = _jsonable(
            outcome.network_traffic_window)
    entry["wall_time_s"] = round(time.perf_counter() - started, 3)
    return entry


def run_experiment(*, repo_root: Path = REPO, out_dir: Path | None = None,
                   dry_run: bool = False, timeout_s: int = TIMEOUT_S,
                   command: str = DEFAULT_COMMAND) -> dict[str, Any]:
    """Run the five-topology experiment and return a JSON-safe report.

    ``dry_run`` compiles and lowers every topology but never locates or runs
    BookSim. It exists so tests and reviewers can exercise the request path
    without a producer.
    """
    requests = build_requests(repo_root=repo_root)
    base = requests["mesh"]
    result: dict[str, Any] = {
        "schema": "veritx.microchip-experiment/1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "command": command,
        "template": TEMPLATE_REL,
        "experiment": (
            "Hypothetical Gen 6-class 16-port switch fabric: synthetic "
            "host->SSD fan-out replayed through the certified BookSim "
            "fabric path on five 16-endpoint topologies."),
        "scope": {
            "authored": [
                "16 port-proxy ranks (8 hosts 0-7, 8 SSD proxies 8-15)",
                "traffic mix, payload sizes, incast and fan-out classes",
                "topology choices (4x4 mesh, radix-4 2-tier fat tree, "
                "radix-4 x 2-dimension flatfly, SROTA Plane D, GEC MECS)",
            ],
            "real": [
                "FabricCompiler compilation and certificate",
                "BookSim cycle-level packet/flit simulation through the "
                "authenticated FabricEvaluator path",
            ],
            "not_modeled": [
                "PCIe protocol (TLP ordering, config space, credits, FLIT "
                "encoding, electricals)",
                "Switchtec internals or any shipping Microchip product",
                "partition isolation, buffer-depth sensitivity, VC count "
                "sweeps, multicast replication point",
                "absolute PPA or functional safety",
            ],
        },
        "booksim": {
            "network_clock_hz": NETWORK_CLOCK_HZ,
            "timeout_s": timeout_s,
            "binary": None,
            "qualified": None,
        },
        "workload": workload_summary(base),
        "topologies": [],
        "blocker": None,
        "caveats": [
            "The workload is synthetic: it is not a Micron or Switchtec "
            "trace and no Microchip number was measured by us.",
            "Profiles encode the host->SSD issue direction; read "
            "data-return direction is not separately modeled.",
            "The schema has no true multicast primitive; the "
            "'multicast_equiv' class is duplicate unicast.",
            "Per-class latency rows are reported exactly as the BookSim "
            "build printed them. Their pkt_count values do not reconcile "
            "with class flit volume or the aggregate trace-request count, "
            "so class-level percentiles are diagnostics, not validated "
            "class-isolation measurements.",
            "Hops and native throughput were not emitted by this backend "
            "run; they are left absent, not zero-filled.",
            "The 70/30 split is a declared byte mix, not a measured "
            "application mix. Only the host->SSD issue direction is "
            "replayed.",
        ],
    }

    if dry_run:
        result["status"] = "DRY_RUN"
        for spec in TOPOLOGY_SPECS:
            request = requests[spec["topology_id"]]
            compilation = FabricCompiler().compile(request)
            lowered = (lower_compile_workload(request)
                       if compilation.status == "COMPILED" else None)
            result["topologies"].append({
                "topology_id": spec["topology_id"],
                "label": spec["label"],
                "topology": dict(spec["topology"]),
                "design_hash": request.design_hash(),
                "compilation": {
                    "status": compilation.status,
                    "certificate_overall": getattr(
                        getattr(compilation, "certificate", None),
                        "overall", None),
                    "error": str(compilation.error)
                    if compilation.error else None,
                },
                "classes": list(lowered.classes) if lowered else [],
                "status": "DRY_RUN",
            })
        return result

    try:
        binary = find_booksim_bin(repo_root)
    except FileNotFoundError as exc:
        result["status"] = "BLOCKED_BACKEND"
        result["booksim"].update({"binary": None, "qualified": False})
        result["blocker"] = {
            "kind": "BOOKSIM_NOT_FOUND",
            "reason": str(exc),
            "consequence": (
                "No topology was evaluated and no metric was written. "
                "Build the pinned producer and rerun."),
        }
        result["topologies"] = [{
            "topology_id": spec["topology_id"],
            "label": spec["label"],
            "topology": dict(spec["topology"]),
            "status": "NOT_EVALUATED",
            "reason": str(exc),
        } for spec in TOPOLOGY_SPECS]
        return result

    result["booksim"]["binary"] = _rel(binary)
    result["booksim"]["qualified"] = None

    root = out_dir or (repo_root / OUT_DIR_REL)
    # A fresh root per invocation: the evaluator refuses to execute into a
    # directory that already holds another run's artifacts.
    run_root = root / "runs" / datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ")
    result["runs_root"] = _rel(run_root)
    for index, spec in enumerate(TOPOLOGY_SPECS):
        request = requests[spec["topology_id"]]
        entry = evaluate_topology(
            request, spec, binary=binary, repo_root=repo_root,
            timeout_s=timeout_s, run_dir=run_root / spec["topology_id"])
        result["topologies"].append(entry)
        if entry["status"] == BACKEND_UNAVAILABLE:
            result["blocker"] = {
                "kind": "BOOKSIM_UNAVAILABLE_OR_UNQUALIFIED",
                "topology_id": spec["topology_id"],
                "reason": entry.get("reason"),
                "consequence": (
                    "Evaluation did not run. No metrics are reported for "
                    "this or later topologies."),
            }
            result["booksim"]["qualified"] = False
            for remaining in TOPOLOGY_SPECS[index + 1:]:
                result["topologies"].append({
                    "topology_id": remaining["topology_id"],
                    "label": remaining["label"],
                    "topology": dict(remaining["topology"]),
                    "status": "NOT_EVALUATED",
                    "reason": "not attempted after the BookSim blocker",
                })
            break

    statuses = [row["status"] for row in result["topologies"]]
    if result["blocker"] is not None:
        result["status"] = "BLOCKED_BACKEND"
    elif statuses and all(status == EVALUATED for status in statuses):
        result["status"] = "COMPLETED"
    else:
        result["status"] = "INCOMPLETE"
    if result["status"] == "COMPLETED":
        fidelities = {
            row.get("evidence", {}).get("execution_fidelity")
            for row in result["topologies"] if row["status"] == EVALUATED
        }
        if fidelities == {"QUALIFIED"}:
            result["booksim"]["qualified"] = True
            result["booksim"]["qualification_basis"] = (
                "every authenticated BookSim evidence artifact reports "
                "execution_fidelity=QUALIFIED")
        elif None not in fidelities and fidelities:
            result["booksim"]["qualified"] = False
            result["booksim"]["qualification_basis"] = (
                f"evidence execution_fidelity values: {sorted(fidelities)}")
    return result


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "not emitted"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    if isinstance(value, dict) and set(value) == {"num", "den"} \
            and isinstance(value["den"], int) and value["den"]:
        ratio = value["num"] / value["den"]
        if ratio == int(ratio):
            return f"{int(ratio):,}"
        return f"{ratio:,.{digits}f}"
    return str(value)


def _md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Gen 6-class 16-port switch fabric experiment",
        "",
        f"Status: **{result['status']}**  ",
        f"Generated: `{result['generated_at_utc']}`  ",
        f"Command: `{result['command']}`",
        "",
        "This is an AUTHORED hypothetical fabric. It is not Switchtec, not a "
        "PCIe protocol model, and no Microchip number was measured by us.",
        "",
        "## What ran",
        "",
    ]
    booksim = result.get("booksim") or {}
    lines += [
        f"- Template: `{result['template']}`",
        f"- Ranks: {result['workload']['rank_count']} "
        f"(hosts {result['workload']['host_ranks'][0]}-"
        f"{result['workload']['host_ranks'][-1]}, SSDs "
        f"{result['workload']['ssd_ranks'][0]}-"
        f"{result['workload']['ssd_ranks'][-1]})",
        f"- BookSim binary: `{booksim.get('binary') or 'not found'}`",
        f"- Network clock: {_fmt(booksim.get('network_clock_hz'))} Hz; "
        f"per-topology timeout: {_fmt(booksim.get('timeout_s'))} s",
    ]
    if result.get("runs_root"):
        lines.append(
            f"- Local run evidence root: `{result['runs_root']}` "
            f"(gitignored; not part of the committed result)")
    lines.append("")
    wl = result["workload"]
    lines += [
        "## Workload (synthetic)",
        "",
        f"{wl['profile_count']} unicast traffic profiles across "
        f"{len(wl['classes'])} classes. Base read/write mix: "
        f"{_fmt(wl['base_read_share'] * 100, 1)}% read / "
        f"{_fmt(wl['base_write_share'] * 100, 1)}% write by declared "
        f"payload bytes ({wl['base_read_bytes']:,} / "
        f"{wl['base_write_bytes']:,} B).",
        "",
    ]
    rows = [[f"`{cls}`", f"{wl['per_class'][cls]['profiles']:,}",
             f"{wl['per_class'][cls]['payload_bytes']:,}"]
            for cls in wl["classes"]]
    lines += _md_table(["class", "profiles", "declared payload bytes"], rows)
    lines += ["", wl["note"], ""]

    if result.get("blocker"):
        blocker = result["blocker"]
        lines += [
            "## BLOCKED",
            "",
            f"- Kind: `{blocker['kind']}`",
            f"- Reason: {blocker['reason']}",
            f"- Consequence: {blocker['consequence']}",
            "",
        ]

    lines += [
        "## Topology results",
        "",
    ]
    rows = []
    for row in result["topologies"]:
        metrics = row.get("metrics") or {}
        derived = row.get("derived") or {}
        rows.append([
            row["topology_id"],
            row.get("compilation", {}).get("status", "not run"),
            row["status"],
            row.get("backend_profile") or "-",
            _fmt(metrics.get("completion_cycles")),
            _fmt(metrics.get("p50")),
            _fmt(metrics.get("p95")),
            _fmt(metrics.get("p99")),
            _fmt(metrics.get("flits_accepted")),
            _fmt(derived.get("accepted_flit_rate_flits_per_cycle"), 6),
        ])
    lines += _md_table(
        ["topology", "compile", "eval", "BookSim profile", "completion "
         "cycles", "p50 cycles", "p95 cycles", "p99 cycles",
         "flits accepted", "derived accepted flit/cycle"],
        rows)
    lines.append("")

    for row in result["topologies"]:
        lines += [f"### {row['topology_id']} — {row.get('label', '')}", ""]
        if row["status"] != EVALUATED:
            lines += [
                f"Recorded status: `{row['status']}`. "
                f"Reason: {row.get('reason') or 'not recorded'}",
                "",
            ]
            continue
        metrics = row.get("metrics") or {}
        evidence = row.get("evidence") or {}
        lines += [
            f"BookSim profile: `{row.get('backend_profile')}`; design hash "
            f"`{row.get('design_hash', '')[:16]}…`.",
            "",
            f"Producer execution fidelity: "
            f"`{evidence.get('execution_fidelity') or 'not recorded'}` "
            f"(producer revision "
            f"`{(evidence.get('producer_source_revision') or 'unknown')[:12]}`).",
            "",
            f"Completion window: {_fmt(metrics.get('completion_cycles'))} "
            f"cycles. Trace-request percentiles: p50 "
            f"{_fmt(metrics.get('p50'))}, p95 {_fmt(metrics.get('p95'))}, "
            f"p99 {_fmt(metrics.get('p99'))} cycles. Flits accepted: "
            f"{_fmt(metrics.get('flits_accepted'))} of "
            f"{_fmt(metrics.get('flits_injected'))} injected.",
            "",
        ]
        availability = row.get("metric_availability") or {}
        for key, note in availability.items():
            lines += [f"- `{key}`: {note}"]
        if availability:
            lines.append("")
        derived = row.get("derived") or {}
        if derived:
            lines += [
                "Derived (not a BookSim-reported metric): "
                f"{_fmt(derived.get('accepted_flit_rate_flits_per_cycle'), 6)} "
                f"accepted flits/cycle, "
                f"{_fmt(derived.get('loaded_packet_rate_packets_per_cycle'), 6)} "
                "loaded packets/cycle.",
                "",
            ]
        block = row.get("class_metrics") or {}
        class_rows = []
        for cls in block.get("classes") or []:
            lat = cls.get("latency") or {}
            class_rows.append([
                f"`{cls.get('traffic_class')}`",
                _fmt(cls.get("flits_injected")),
                _fmt(cls.get("flits_accepted")),
                _fmt(cls.get("bytes_accepted")),
                _fmt(lat.get("p50")),
                _fmt(lat.get("p95")),
                _fmt(lat.get("p99")),
                _fmt(lat.get("pkt_count")),
            ])
        if class_rows:
            lines += _md_table(
                ["class", "flits injected", "flits accepted",
                 "bytes accepted", "p50 cycles", "p95 cycles", "p99 cycles",
                 "pkt_count"],
                class_rows)
            lines.append("")

    lines += ["## Caveats", ""]
    lines += [f"- {caveat}" for caveat in result.get("caveats") or []]
    lines.append("")
    lines += [
        "## What is real vs synthetic",
        "",
        "- **Real:** the compiler resolved each 16-endpoint topology and the "
        "authenticated BookSim path executed a cycle-level packet/flit "
        "simulation. Completion cycles, packet percentiles and flit "
        "counters above come from that run's digest-bound evidence.",
        "- **Synthetic:** the host/SSD port model, the 70/30 read/write "
        "mix, payload classes, incast pair and multicast-equivalent "
        "duplicate-unicast fan-out. No trace from a real system was used.",
        "- **Derived:** accepted flits/cycle and loaded packets/cycle are "
        "simple arithmetic on reported counters, labelled as such. Hops and "
        "native throughput are absent because this run did not emit them.",
        "",
        "## Do not claim",
        "",
        "- PCIe TLP ordering, config space, credit correctness, FLIT "
        "encoding, compliance, or Gen 6 electricals.",
        "- Switchtec internals or any shipping Microchip product.",
        "- Retimer/SerDes latency.",
        "- Partition isolation; no partition or QoS-isolation experiment ran.",
        "- Buffer-depth, VC-count, or multicast-replication-point sweeps.",
        "- Absolute 3 nm/4 nm PPA, area, or power.",
        "- Functional safety or security.",
        "- CXL or UCIe semantics.",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(result: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "results.json"
    md_path = out_dir / "results.md"
    json_path.write_text(
        json.dumps(_jsonable(result), indent=2, sort_keys=False) + "\n",
        encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gen 6-class 16-port switch fabric BookSim experiment")
    parser.add_argument(
        "--out-dir", type=Path, default=None,
        help=f"output directory (default: {OUT_DIR_REL})")
    parser.add_argument(
        "--timeout-s", type=int, default=TIMEOUT_S,
        help=f"per-topology BookSim timeout (default: {TIMEOUT_S})")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="compile and lower all five topologies; do not run BookSim")
    args = parser.parse_args(argv)

    out_dir = args.out_dir or (REPO / OUT_DIR_REL)
    result = run_experiment(
        repo_root=REPO, out_dir=out_dir, dry_run=args.dry_run,
        timeout_s=args.timeout_s)
    if args.dry_run:
        print(f"status: {result['status']}")
        for row in result["topologies"]:
            print(f"  {row['topology_id']}: "
                  f"{row['compilation']['status']} "
                  f"classes={len(row['classes'])}")
        return 0

    json_path, md_path = write_outputs(result, out_dir)
    print(f"status: {result['status']}")
    for row in result["topologies"]:
        metrics = row.get("metrics") or {}
        print(f"  {row['topology_id']}: {row['status']} "
              f"completion={metrics.get('completion_cycles', 'n/a')} "
              f"p99={metrics.get('p99', 'n/a')}")
    print(f"wrote {_rel(json_path)}")
    print(f"wrote {_rel(md_path)}")
    if result["status"] == "BLOCKED_BACKEND":
        print(f"blocker: {result['blocker']['reason']}", file=sys.stderr)
        return 1
    if result["status"] != "COMPLETED":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
