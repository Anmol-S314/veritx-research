"""Candidate trace simulations for the design cockpit.

The cockpit asks a narrow question: if the same requested trace is projected
onto a trace-sized candidate fabric, what does the cycle-level network model
observe?  This module owns that execution boundary.

It deliberately does not accept a free-form config, trace path or command.
The caller names one stored product run (so the trace is resolved through the
run bundle), plus bounded candidate parameters.  One BookSim process per
candidate runs in a self-contained directory under the track's run root.  The
response never claims silicon measurement: every row is labelled
``BOOKSIM_TRACE_REPLAY``.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import statistics
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from veritx_dse.core.errors import InvalidInput
from veritx_dse.core.paths import REPO
from veritx_dse.gateway.errors import Conflict

RUN_ROOT = REPO / "tracks/t3-topology/runs/design-candidates"
SAMPLE_PERIOD_CYCLES = 500
WINDOW_SEMANTICS = (
    "BookSim trace replay; every window is 500 cycles. Queue cycles are the "
    "integral of queued flits at each channel's output, divided by delivered "
    "flits. This is not packet latency and not silicon measurement."
)
_DIRS = {0: (1, 0, "E"), 1: (-1, 0, "W"), 2: (0, 1, "S"), 3: (0, -1, "N")}
_LOCK = threading.Lock()


class CandidateSpec(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    family: Literal["mesh", "torus"] = "mesh"
    side: int = Field(default=9, ge=3, le=12)
    concentration: int = Field(default=1, ge=1, le=4)
    vcs: int = Field(default=1, ge=1, le=8)
    link_width_bits: int = Field(default=128, ge=64, le=512)
    routing: Literal["dim_order", "dor"] = "dim_order"


class DesignSimBody(BaseModel):
    run_id: str = Field(min_length=1, max_length=128)
    candidates: list[CandidateSpec] = Field(min_length=1, max_length=8)
    sample_period_cycles: int = Field(
        default=SAMPLE_PERIOD_CYCLES, ge=100, le=10_000)
    seed: int = Field(default=0, ge=0, le=2_147_483_647)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _guess_classes(trace: Path) -> int:
    classes: set[str] = set()
    for line in trace.read_text(errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith(("#", "%")):
            continue
        fields = line.split()
        if len(fields) == 5:
            classes.add(fields[2])
    return max(1, len(classes))


def _trace_endpoints(trace: Path) -> int:
    """Endpoint seats the trace needs: highest endpoint id plus one.

    Rows are `time src class dst size`; the class column is the one
    _guess_classes reads, so the endpoints are fields 1 and 3.  The seat count
    is measured from the trace rather than assumed, because a 5x5 fabric that
    seats a 25-endpoint trace is legitimate.
    """
    highest = -1
    for line in trace.read_text(errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith(("#", "%")):
            continue
        fields = line.split()
        if len(fields) != 5:
            continue
        try:
            highest = max(highest, int(fields[1]), int(fields[3]))
        except ValueError:
            continue
    return highest + 1


def _resolve_trace(product: Any, roots: tuple[Path, ...], run_id: str) -> Path:
    """Resolve the sealed workload trace through the run bundle only.

    A product run's evidence records its bundle run directory.  The path is
    accepted only when it resolves inside one of the configured store roots;
    the fallback scan is likewise rooted there.  No caller-supplied path
    reaches this function.
    """
    allowed = tuple(Path(root).resolve() for root in roots)
    try:
        evidence = product.run_evidence(run_id)
    except Exception as error:  # product's NOT_FOUND is the only expected one
        raise InvalidInput(f"no such run: {run_id}") from error
    documents = evidence.get("documents", {}) if isinstance(evidence, dict) else {}
    for doc in documents.values():
        if not isinstance(doc, dict):
            continue
        attempt = doc.get("attempt")
        if not isinstance(attempt, dict):
            # Bundle evidence is wrapped as {"evidence": {...}, "attempt": {...}}.
            nested = doc.get("evidence")
            attempt = nested.get("attempt") if isinstance(nested, dict) else None
        run_dir = attempt.get("run_dir") if isinstance(attempt, dict) else None
        if not isinstance(run_dir, str):
            continue
        trace = (Path(run_dir) / "workload.trace").resolve()
        if trace.is_file() and any(trace.is_relative_to(root) for root in allowed):
            return trace
    for root in allowed:
        for candidate in root.rglob("workload.trace"):
            if candidate.parent.name == "run" and run_id in candidate.parts:
                resolved = candidate.resolve()
                if any(resolved.is_relative_to(allowed_root)
                       for allowed_root in allowed):
                    return resolved
    raise InvalidInput(
        f"run {run_id!r} has no readable workload.trace under the store roots")


def _make_topology(family: str, side: int) -> dict[str, Any]:
    routers = {}
    for y in range(side):
        for x in range(side):
            routers[y * side + x] = (x, y)
    at = {coords: rid for rid, coords in routers.items()}
    channels: list[dict[str, Any]] = []
    for rid, (x, y) in routers.items():
        for port, (dx, dy, name) in _DIRS.items():
            nx, ny = x + dx, y + dy
            wrap = False
            if family == "torus":
                nx %= side
                ny %= side
                wrap = (nx, ny) != (x + dx, y + dy)
            if (nx, ny) not in at:
                continue
            channels.append({
                "channel_id": len(channels),
                "src_router": rid,
                "dst_router": at[(nx, ny)],
                "src_port": port,
                "dst_port": port,
                "direction": name,
                "wrap": wrap,
            })
    directed = {(c["src_router"], c["dst_router"]): c for c in channels}
    return {
        "family": family, "side": side, "routers": routers, "at": at,
        "channels": channels, "directed": directed,
    }


def _project(top: dict[str, Any], trace_path: Path) -> tuple[dict[int, int], int, int]:
    """DOR-XY offered channel demand for endpoint i -> router i (row-major)."""
    side = top["side"]
    demand: dict[int, int] = {}
    total_flits = 0
    hops = 0
    for line in trace_path.read_text(errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith(("#", "%")):
            continue
        fields = line.split()
        if len(fields) != 5:
            continue
        src, dst, flits = int(fields[1]), int(fields[3]), int(fields[4])
        if src not in top["routers"] or dst not in top["routers"]:
            raise InvalidInput(
                f"trace endpoint {max(src, dst)} exceeds the candidate's "
                f"{len(top['routers'])} router seats")
        x, y = top["routers"][src]
        tx, ty = top["routers"][dst]
        cur = src
        total_flits += flits
        for axis, target in ((0, tx), (1, ty)):
            current = x if axis == 0 else y
            delta = target - current
            if top["family"] == "torus":
                if delta > side / 2:
                    delta -= side
                elif delta < -side / 2:
                    delta += side
            step = 1 if delta > 0 else -1
            while current != target:
                current = ((current + step) % side
                           if top["family"] == "torus" else current + step)
                if axis == 0:
                    x = current
                else:
                    y = current
                nxt = top["at"][(x % side, y % side)]
                channel = top["directed"][(cur, nxt)]
                demand[channel["channel_id"]] = (
                    demand.get(channel["channel_id"], 0) + flits)
                hops += flits
                cur = nxt
    return demand, total_flits, hops


def _decode(logical: int) -> tuple[int, int]:
    rest = logical % 100_000_000
    return rest // 10_000, rest % 10_000


def _channel_for_port(top: dict[str, Any], router: int, port: int) -> dict[str, Any] | None:
    if port not in _DIRS:
        return None
    x, y = top["routers"][router]
    dx, dy, _ = _DIRS[port]
    nx, ny = x + dx, y + dy
    if top["family"] == "torus":
        nx %= top["side"]
        ny %= top["side"]
    dst = top["at"].get((nx, ny))
    return top["directed"].get((router, dst)) if dst is not None else None


def _read_series(path: Path, top: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    series = json.loads(path.read_text())
    rows = []
    for channel in series["channels"]:
        router, port = _decode(int(channel["logical_channel_id"]))
        certified = _channel_for_port(top, router, port)
        flits = sum(channel["flits_per_window"])
        queue = sum(channel["queue_cycles_per_window"])
        peak = (max(channel["occupancy_max_per_window"])
                if channel.get("occupancy_max_per_window") else None)
        rows.append({
            "logical_channel_id": int(channel["logical_channel_id"]),
            "router": router,
            "port": port,
            "channel_id": certified["channel_id"] if certified else None,
            "route": (f"R{router}→R{certified['dst_router']}"
                      if certified else None),
            "flits": flits,
            "queue_cycles": queue,
            "queue_per_flit": (queue / flits) if flits else None,
            "peak_queued_flits": peak,
        })
    return series, rows


def _parse_stdout(text: str, classes: int) -> dict[str, Any]:
    sections: dict[str, Any] = {}
    for cls in range(classes):
        match = re.search(
            rf"Class {cls}:\s*\n"
            rf"Packet latency average = ([0-9.]+).*?"
            rf"Network latency average = ([0-9.]+).*?"
            rf"Flit latency average = ([0-9.]+)",
            text, re.S)
        if match:
            sections[str(cls)] = {
                "packet_latency": float(match.group(1)),
                "network_latency": float(match.group(2)),
                "flit_latency": float(match.group(3)),
            }
    hops = [float(value) for value in re.findall(r"Hops average = ([0-9.]+)", text)]
    runtime = re.search(r"Total run time ([0-9.]+)", text)
    injected = re.search(r"VeritX: injected flits total = (\d+)", text)
    accepted = re.search(r"VeritX: accepted flits total = (\d+)", text)
    injection_end = re.search(r"All (\d+) cycles", text)
    return {
        "classes": sections,
        "hops": hops,
        "runtime_s": float(runtime.group(1)) if runtime else None,
        "injected_flits": int(injected.group(1)) if injected else None,
        "accepted_flits": int(accepted.group(1)) if accepted else None,
        "trace_injection_cycles": int(injection_end.group(1)) if injection_end else None,
    }


def _config_text(*, candidate: CandidateSpec, trace_name: str,
                  classes: int, trace_hash: str, binary_hash: str,
                  config_hash: str, run_hash: str,
                  sample_period_cycles: int, seed: int) -> str:
    capacity = max(1, candidate.link_width_bits // 128)
    return f"""topology = {candidate.family};
k = {candidate.side};
n = 2;
use_noc_latency = 1;
routing_function = {candidate.routing};
num_vcs = {candidate.vcs};
classes = {classes};
router = iq;
priority = none;
link_failures = 0;
traffic = trace({trace_name});
sample_period = 12424;
max_samples = 1;
injection_rate = 0.0;
injection_rate_uses_flits = 1;
injection_process = bernoulli;
sim_type = latency;
sim_count = 1;
warmup_periods = 0;
measure_stats = 1;
print_activity = 0;
viewer_trace = 0;
sim_power = 0;
seed = {seed};
latency_thres = 1000000000000000.0;
channel_timeseries_output = channel_timeseries.json;
sample_period_cycles = {sample_period_cycles};
run_hash = {run_hash};
run_binary_hash = {binary_hash};
link_capacity_flits_per_cycle = {capacity};
run_input_hashes = {trace_hash},{config_hash};
"""


def _run_one(*, candidate: CandidateSpec, trace: Path, trace_hash: str,
             trace_classes: int, booksim: Path, out_root: Path,
             sample_period_cycles: int, seed: int) -> dict[str, Any]:
    target = out_root / candidate.id
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(trace, target / "workload.trace")
    binary_hash = _sha256(booksim)
    # The prepared identity is the config before the run hash is embedded;
    # the fork only records it, so a deterministic pre-hash is sufficient.
    prepared = _config_text(
        candidate=candidate, trace_name="workload.trace",
        classes=trace_classes, trace_hash=trace_hash,
        binary_hash=binary_hash, config_hash="0" * 64,
        run_hash="0" * 64, sample_period_cycles=sample_period_cycles,
        seed=seed)
    config_hash = hashlib.sha256(prepared.encode()).hexdigest()
    run_hash = hashlib.sha256(json.dumps({
        "run": trace_hash, "config": config_hash, "binary": binary_hash,
        "seed": seed, "sample_period_cycles": sample_period_cycles,
        "candidate": candidate.model_dump(),
    }, sort_keys=True).encode()).hexdigest()
    config = _config_text(
        candidate=candidate, trace_name="workload.trace",
        classes=trace_classes, trace_hash=trace_hash,
        binary_hash=binary_hash, config_hash=config_hash,
        run_hash=run_hash, sample_period_cycles=sample_period_cycles,
        seed=seed)
    (target / "config.cfg").write_text(config)
    completed = subprocess.run(
        [str(booksim), "config.cfg"], cwd=target, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=120, check=False)
    (target / "booksim.stdout.txt").write_text(completed.stdout)
    (target / "booksim.stderr.txt").write_text(completed.stderr)
    series_path = target / "channel_timeseries.json"
    if completed.returncode != 0 or not series_path.is_file():
        detail = (completed.stderr or completed.stdout or "").strip()[-1200:]
        raise InvalidInput(
            f"BookSim failed for {candidate.id!r} "
            f"(exit {completed.returncode}): {detail}")

    top = _make_topology(candidate.family, candidate.side)
    demand, trace_flits, hops = _project(top, trace)
    series, rows = _read_series(series_path, top)
    active = [row for row in rows if row["flits"] > 0]
    pairs = []
    for row in rows:
        if row["channel_id"] is None:
            continue
        projected = demand.get(row["channel_id"], 0)
        if projected or row["flits"]:
            pairs.append((projected, row["flits"]))
    exact = sum(1 for projected, observed in pairs if projected == observed)
    pearson = None
    if len(pairs) > 1:
        projected_values = [p[0] for p in pairs]
        observed_values = [p[1] for p in pairs]
        try:
            pearson = statistics.correlation(projected_values, observed_values)
        except (statistics.StatisticsError, ValueError):
            pearson = None
    top_queue = sorted(
        [row for row in active if row["queue_per_flit"] is not None],
        key=lambda row: row["queue_per_flit"], reverse=True)[:8]
    stats = _parse_stdout(completed.stdout, trace_classes)
    cycles_sampled = (
        sum(series["channels"][0]["window_cycles"])
        if series.get("channels") else 0)
    return {
        "id": candidate.id,
        "spec": candidate.model_dump(),
        "out_dir": str(target.relative_to(REPO)),
        "simulation": {
            "status": "BOOKSIM_TRACE_REPLAY",
            "run_hash": run_hash,
            "config_sha256": config_hash,
            "binary_sha256": binary_hash,
            "returncode": completed.returncode,
            "windows": series.get("num_windows"),
            "cycles_sampled": cycles_sampled,
            "channels": len(rows),
            "active": len(active),
            "stats": stats,
            "top_queue": top_queue,
            "channel_actuals": [
                # Fabric links only: uncertified rows are endpoint
                # injection/ejection, which routerLoad never counts.
                {"router": row["router"], "port": row["port"],
                 "flits": row["flits"],
                 "queue_cycles": row["queue_cycles"]}
                for row in rows
                if row["flits"] > 0 and row["channel_id"] is not None
            ],
            "semantics": WINDOW_SEMANTICS,
        },
        "validation": {
            "compared": len(pairs),
            "exact": exact,
            "pearson": pearson,
            "projected_channel_flits": sum(p[0] for p in pairs),
            "simulated_channel_flits": sum(p[1] for p in pairs),
            "trace_flits": trace_flits,
            "avg_hops": (hops / trace_flits) if trace_flits else None,
            "status": "exact" if pairs and exact == len(pairs) else "mismatch",
        },
        "projection_top": [
            {"channel": channel_id, "flits": flits}
            for channel_id, flits in sorted(
                demand.items(), key=lambda item: item[1], reverse=True)[:8]
        ],
    }


def run_design_simulation(body: DesignSimBody, *, roots: tuple[Path, ...],
                          product: Any, booksim_bin: Path | None) -> dict[str, Any]:
    """Execute the bounded candidate set and return measured replay data."""
    if not _LOCK.acquire(blocking=False):
        raise Conflict("another candidate simulation is already running")
    try:
        booksim = Path(booksim_bin or (REPO / "third_party/booksim2/src/booksim"))
        if not booksim.is_absolute():
            booksim = (REPO / booksim).resolve()
        if not booksim.is_file():
            raise InvalidInput(f"BookSim binary is missing: {booksim}")
        trace = _resolve_trace(product, roots, body.run_id)
        trace_hash = _sha256(trace)
        classes = _guess_classes(trace)
        seats = _trace_endpoints(trace)
        for candidate in body.candidates:
            if candidate.family == "torus" and candidate.vcs < 2:
                raise InvalidInput(
                    f"{candidate.id}: torus dim_order needs at least 2 VCs "
                    "for deadlock freedom")
            if candidate.side ** 2 < seats:
                raise InvalidInput(
                    f"{candidate.id}: {candidate.side}x{candidate.side} has "
                    f"fewer than the trace's {seats} endpoint seats")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        out_root = RUN_ROOT / f"api-{stamp}"
        out_root.mkdir(parents=True, exist_ok=False)
        results = [
            _run_one(
                candidate=candidate, trace=trace, trace_hash=trace_hash,
                trace_classes=classes, booksim=booksim, out_root=out_root,
                sample_period_cycles=body.sample_period_cycles, seed=body.seed)
            for candidate in body.candidates
        ]
        return {
            "contract_version": 1,
            "schema": "veritx/design-candidate-simulation/1",
            "run_id": body.run_id,
            "trace": {
                "path": str(trace.relative_to(REPO)) if trace.is_relative_to(REPO) else str(trace),
                "sha256": trace_hash,
                "classes": classes,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "out_dir": str(out_root.relative_to(REPO)),
            "candidates": results,
            "semantics": WINDOW_SEMANTICS,
        }
    finally:
        _LOCK.release()


__all__ = ["CandidateSpec", "DesignSimBody", "run_design_simulation"]
