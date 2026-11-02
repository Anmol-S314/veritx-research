"""Run a workload × topology ablation from the Studio gateway.

The browser never runs BookSim itself. This module validates a bounded
request, invokes the same ``ablate_workloads.py`` runner the CLI uses, and
returns the measured document plus its run directory. Structural axes
(workload, topology, trace, packet size, buffer, VCs) are validated here;
free-form BookSim knobs are limited to safe ``key=value`` pairs.
"""
from __future__ import annotations

import json
import os
import math
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.responses import JSONResponse

from veritx_dse.core.paths import REPO

SCRIPT = REPO / "tracks/t3-topology/scripts/ablate_workloads.py"
CATALOG = REPO / "apps/studio/prototype/public/data/workload_ablation.json"
SENSITIVITY = REPO / "apps/studio/prototype/public/data/design_sensitivity.json"
# Ablation output is WRITTEN, so it cannot live in the install tree: a packaged
# app installs under a root-owned prefix (e.g. /usr/lib/Srota Studio), where the
# user cannot create a run directory and every search fails with a 500 that looks
# like a simulator problem. The desktop sidecar points this at the app data dir;
# a source checkout keeps the repository location.
OUT_ROOT = Path(os.environ.get(
    "VERITX_ABLATION_ROOT",
    str(REPO / "tracks/t3-topology/runs/workload-ablation")))
RESERVED = {"topology", "sim_type", "trace_file", "trace_packet_log",
            "packet_size", "vc_buf_size", "use_noc_latency", "num_vcs", "seed",
            "k", "n", "c", "x", "y", "xr", "yr", "o", "d", "mesh", "hybrid", "subnets", "routing_function"}
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
VALUE_RE = re.compile(r"^[A-Za-z0-9_.+-]+$")
_LOCK = threading.Lock()


def _catalog() -> dict[str, Any]:
    if not CATALOG.exists():
        raise ValueError(f"ablation catalog is missing: {CATALOG.relative_to(REPO)}")
    return json.loads(CATALOG.read_text())


def ablation_catalog() -> dict[str, Any]:
    """Return the same catalog the runner validates, without historical results."""
    catalog = _catalog()
    sensitivity = json.loads(SENSITIVITY.read_text()) if SENSITIVITY.exists() else {}
    depth_values = sorted({
        row["depth"] for row in sensitivity.get("points", [])
        if type(row.get("depth")) is int and row["depth"] > 0
    })
    return {
        "workloads": catalog["workloads"],
        "topologies": catalog["topologies"],
        "defaults": catalog.get("common", {}),
        "knob_dimensions": {
            "vc_buf_size": {
                "values": depth_values,
                "source": "apps/studio/prototype/public/data/design_sensitivity.json",
                "scope": sensitivity.get("scope", "not stated"),
            },
        },
        "scope": "Catalog trace replay; not the currently loaded project revision",
        "override_exclusions": sorted(RESERVED),
        "max_overrides": 32,
    }


def _pick(value: Any, known: set[str], label: str) -> list[str]:
    if value is None:
        # Default to the full catalog so an empty request is still bounded.
        return sorted(known)
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    names = []
    for item in value:
        if not isinstance(item, str) or item not in known:
            raise ValueError(f"unknown {label}: {item!r}; available: {sorted(known)}")
        if item not in names:
            names.append(item)
    return names


def _overrides(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("overrides must be an object of BookSim key=value pairs")
    if len(value) > 32:
        raise ValueError("at most 32 overrides per run")
    out: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise ValueError(f"invalid override key: {key!r}")
        if key in RESERVED:
            raise ValueError(f"{key} is a structural axis; use the dedicated control")
        text = str(item).strip()
        if not VALUE_RE.match(text):
            raise ValueError(f"invalid value for {key}: {item!r}")
        out[key] = text
    return out


def _integer(body: dict, key: str, default: int, low: int, high: int) -> int:
    value = body.get(key, default)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{key} must be an integer between {low} and {high}")
    return value


def run_ablation(body: dict[str, Any] | None) -> Any:
    body = {} if body is None else body
    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"detail": "request must be an object"})
    try:
        catalog = _catalog()
        workloads = _pick(body.get("workloads"), {w["workload_id"] for w in catalog["workloads"]}, "workload")
        topologies = _pick(body.get("topologies"), {t["topology_id"] for t in catalog["topologies"]}, "topology")
        overrides = _overrides(body.get("overrides"))
        packet_size = _integer(body, "packet_size", 5, 1, 1024)
        vc_buf_size = _integer(body, "vc_buf_size", 8, 1, 4096)
        use_noc_latency = _integer(body, "use_noc_latency", 0, 0, 1)
        jobs = _integer(body, "jobs", 6, 1, 16)
        seed = _integer(body, "seed", 1, 0, 2_147_483_647)
        packet_flits = None if body.get("trace_packet_size") is None else _integer(body, "trace_packet_size", 1, 1, 1024)
        burst_window = _integer(body, "burst_window", 0, 0, 1_000_000_000)
        stride = _integer(body, "rank_stride", 1, 1, 1_000_000)
        offset = _integer(body, "rank_offset", 0, 0, 1_000_000)
        scale = body.get("time_scale", 1)
        if type(scale) not in (int, float) or not math.isfinite(scale) or not 0.01 <= scale <= 100:
            raise ValueError("time_scale must be a number between 0.01 and 100")
        counts = {w["nodes"] for w in catalog["workloads"] if w["workload_id"] in workloads}
        if any(math.gcd(stride, count) != 1 for count in counts):
            raise ValueError("rank_stride must be coprime to each selected workload's endpoint count")
    except ValueError as error:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    if not _LOCK.acquire(blocking=False):
        return JSONResponse(status_code=409, content={"detail": "another ablation is already running"})

    try:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        OUT_ROOT.mkdir(parents=True, exist_ok=True)
        out = OUT_ROOT / f"api-{stamp}"
        command = [sys.executable, str(SCRIPT),
                   "--out", str(out),
                   "--workloads", ",".join(workloads),
                   "--topologies", ",".join(topologies),
                   "--packet-size", str(packet_size),
                   "--vc-buf-size", str(vc_buf_size),
                   "--use-noc-latency", str(use_noc_latency),
                   "--jobs", str(jobs),
                   "--seed", str(seed),
                   "--replay-catalog", str(CATALOG),
                   "--time-scale", str(scale), "--burst-window", str(burst_window),
                   "--rank-stride", str(stride), "--rank-offset", str(offset)]
        if packet_flits is not None:
            command += ["--trace-packet-size", str(packet_flits)]
        for key, value in overrides.items():
            command += ["--set", f"{key}={value}"]
        started = datetime.now(timezone.utc)
        try:
            result = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            return JSONResponse(status_code=504, content={
                "detail": "the ablation exceeded its 600 s budget",
                "command": command,
            })
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        document_path = out / "ablation.json"
        if not document_path.exists():
            return JSONResponse(status_code=500, content={
                "detail": "the runner produced no ablation.json",
                "command": command,
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-4000:],
            })
        document = json.loads(document_path.read_text())
        failures = [row for row in document.get("runs", []) if row.get("status") != "ok"]
        return {
            "schema": "veritx/workload-ablation-run/1",
            # Relative to the output root, which is the repository in a source
            # checkout but the app data dir in a packaged build; a REPO-relative
            # path raised ValueError there and turned a completed search into a
            # bare 500.
            "out": str(out.relative_to(OUT_ROOT)),
            "command": command,
            "duration_seconds": elapsed,
            "returncode": result.returncode,
            "failed_cells": len(failures),
            "document": document,
            "stdout": result.stdout[-2000:],
        }
    finally:
        _LOCK.release()
