"""ramulator.py — Ramulator 2.1 standalone execution backend (Phase 15b).

Rationale: docs/decisions/modules/simulation.md
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from veritx_dse.workload.memory_lowering import MemoryLoweringManifest
from veritx_dse.core.paths import REPO

VENDOR_DIR = REPO / "third_party" / "ramulator2"
VENDOR_PIN = "72427a1bba3771564c4fb0e494ba02242fd1eaa7"
RAMULATOR_VERSION = "2.1.0"

FIDELITY = "MEMORY_CYCLE_SIMULATION"
LOWERER_ID = "veritx_dse.simulation.ramulator/1"

SUPPORTED = {"dram_class": "HBM3", "controller": "HBM34"}
SUPPORTED_MAPPINGS = frozenset(
    {"sequential_bankstriped_v1", "channel_interleaved_v1"})

SUPPORTED_CHANNEL_COUNTS = frozenset({1, 8})

_SUM_STATS = (
    "row_hits", "row_misses", "row_conflicts",
    "read_row_hits", "read_row_misses", "read_row_conflicts",
    "write_row_hits", "write_row_misses", "write_row_conflicts",
    "num_read_reqs", "num_write_reqs",
    "num_read_reqs_served", "num_write_reqs_served",
    "num_write_reqs_coalesced",
    "num_maintenance_reqs", "num_maintenance_reqs_served",
    "read_latency", "write_latency",
    "read_queue_len", "write_queue_len", "queue_len",
)
_MAX_STATS = ("cycles",)
_MEAN_STATS = ("avg_read_latency", "avg_write_latency",
               "read_queue_len_avg", "write_queue_len_avg",
               "queue_len_avg", "priority_queue_len_avg")

_TYPED_STATS: tuple[tuple[str, str, str], ...] = (
    ("cycles", "completion_cycles", "cycles"),
    ("avg_read_latency", "average_read_latency_cycles", "cycles"),
    ("avg_write_latency", "average_write_latency_cycles", "cycles"),
    ("row_hits", "row_hits", "requests"),
    ("row_misses", "row_misses", "requests"),
    ("row_conflicts", "row_conflicts", "requests"),
    ("read_queue_len_avg", "read_queue_len_avg", "requests"),
    ("write_queue_len_avg", "write_queue_len_avg", "requests"),
)

class RamulatorError(ValueError):
    """VeriTX-side misuse (backend not ready, tampered input, bad geometry
    shape) — distinct from backend-run outcomes, which are evidence."""

@dataclass(frozen=True)
class RamulatorBackend:
    """Located, identified backend. Build with discover()."""
    python_exe: str
    package_dir: Path
    ext_path: Path
    version: str = RAMULATOR_VERSION
    commit: str = VENDOR_PIN

    @property
    def ready(self) -> bool:
        return self.ext_path.is_file()

    def binary_hash(self) -> str:
        if not self.ready:
            raise RamulatorError(
                "backend not built — no binary identity available "
                f"(expected extension at {self.ext_path}; build: "
                "cd third_party/ramulator2 && ./build.sh with the target "
                "interpreter)")
        return "sha256:" + hashlib.sha256(
            self.ext_path.read_bytes()).hexdigest()

    def producer(self) -> dict[str, Any]:
        return {"name": "ramulator", "version": self.version,
                "commit_sha": self.commit,
                "binary_sha256": self.binary_hash()}

def discover(python_exe: str | None = None,
             vendor_dir: Path | None = None) -> RamulatorBackend:
    """Locate the backend: interpreter + vendored package + built ext.

    Readiness is explicit (backend.ready) — never implied. The extension
    is interpreter-tagged (cpython-3XX), so the discovering interpreter
    must be the one the bindings were built with.
    """
    exe = python_exe or sys.executable
    vdir = vendor_dir or VENDOR_DIR
    pkg = vdir / "python"
    try:
        tag = subprocess.run(
            [exe, "-c",
             "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))"],
            capture_output=True, text=True, timeout=30)
        suffix = tag.stdout.strip()
    except (OSError, subprocess.SubprocessError) as e:
        raise RamulatorError(
            f"interpreter {exe!r} unusable for backend discovery: {e}")
    if not suffix:
        raise RamulatorError(
            f"interpreter {exe!r} reports no extension suffix")
    ext = pkg / "ramulator" / f"_ramulator{suffix}"
    return RamulatorBackend(python_exe=exe, package_dir=pkg, ext_path=ext)

@dataclass(frozen=True)
class MemoryEvidence:
    """Typed memory evidence for one backend execution (spec §18)."""
    status: str
    producer: dict
    fidelity: str
    memory_artifact_hash: str
    lowering_manifest_hash: str
    backend_input_hash: str
    backend_config_hash: str
    metrics: dict = field(default_factory=dict)
    assumptions: tuple = field(default_factory=tuple)
    semantic_losses: tuple = field(default_factory=tuple)
    failure_reason: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "producer": self.producer,
            "fidelity": self.fidelity,
            "memory_artifact_hash": self.memory_artifact_hash,
            "lowering_manifest_hash": self.lowering_manifest_hash,
            "backend_input_hash": self.backend_input_hash,
            "backend_config_hash": self.backend_config_hash,
            "metrics": self.metrics,
            "assumptions": list(self.assumptions),
            "semantic_losses": list(self.semantic_losses),
            "failure_reason": self.failure_reason, "raw": self.raw,
        }

def manifest_hash(manifest: MemoryLoweringManifest) -> str:
    """Content identity of a lowering manifest (hash-linked evidence)."""
    payload = json.dumps(manifest.to_dict(), sort_keys=True,
                         separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()

def _check_supported(manifest: MemoryLoweringManifest) -> str | None:
    """None when executable under the v1 envelope, else the reason."""
    geo = manifest.geometry
    for key in ("dram_class", "controller"):
        want = SUPPORTED[key]
        got = geo.get(key) if isinstance(geo, dict) else None
        if got != want:
            return (f"{key} {got!r} unsupported in v1 (audited: {want!r}) "
                    "— refusing rather than substituting another memory "
                    "standard")
    if manifest.mapping_algorithm not in SUPPORTED_MAPPINGS:
        return (f"mapping {manifest.mapping_algorithm!r} unsupported — "
                f"audited: {sorted(SUPPORTED_MAPPINGS)}")
    levels = geo.get("levels", {}) if isinstance(geo, dict) else {}
    channels = levels.get("channel", 1)
    if channels not in SUPPORTED_CHANNEL_COUNTS:
        return (f"geometry declares {channels} channels; the audited "
                f"envelope covers {sorted(SUPPORTED_CHANNEL_COUNTS)} — "
                "refusing to drive an unaudited channel count")
    return None

def merge_channel_stats(stats: Any) -> dict[str, Any]:
    """Fold per-channel controller stats into one memory-system view.

    One channel returns its dict unchanged (bit-identical to the v1 path).
    Many channels: counters sum, ``cycles`` takes the max (the drain is
    bounded by the slowest channel), and per-request means are weighted by
    that channel's request count. Nothing is invented: a stat absent from
    every channel stays absent.
    """
    if isinstance(stats, dict):
        return stats
    if not isinstance(stats, list) or not stats:
        return {}
    channels = [c for c in stats if isinstance(c, dict)]
    if not channels:
        return {}
    if len(channels) == 1:
        return channels[0]
    out: dict[str, Any] = {}
    for key in _SUM_STATS:
        vals = [c[key] for c in channels
                if isinstance(c.get(key), (int, float))
                and not isinstance(c.get(key), bool)]
        if vals:
            out[key] = sum(vals)
    for key in _MAX_STATS:
        vals = [c[key] for c in channels
                if isinstance(c.get(key), (int, float))
                and not isinstance(c.get(key), bool)]
        if vals:
            out[key] = max(vals)
    for key in _MEAN_STATS:
        num = den = 0.0
        plain: list[float] = []
        for c in channels:
            v = c.get(key)
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                continue
            plain.append(float(v))
            w = c.get("num_read_reqs", 0) + c.get("num_write_reqs", 0)
            if isinstance(w, (int, float)) and not isinstance(w, bool) and w:
                num += float(v) * w
                den += w
        if den:
            out[key] = num / den
        elif plain:
            out[key] = sum(plain) / len(plain)
    return out

_DRIVER_TEMPLATE = '''"""Generated Ramulator driver (veritx 15b) — do not hand-edit."""
import json
import ramulator

frontend = ramulator.frontend.ReadWriteTrace(
    clock_ratio=4,
    path={trace_path!r},
)
{controller_defs}
mem = ramulator.memory_system.GenericDRAM(
    clock_ratio=1,
    controllers=[{controller_list}],
    channel_mapper=ramulator.channel_mapper.PassThroughChannelMapper(),
)
sim = ramulator.Simulation(frontend, mem)
sim.run()
sim.finalize()
# Machine channel is stats.json (a FILE): supervised_run bounds stdout by
# lines, and the stats block serializes to one long line that capture
# would truncate. stdout stays human log only.
# One entry per controller (channel); a single channel yields a 1-list.
_stats = sim.stats["memory_system"]["controller"]
if isinstance(_stats, dict):
    _stats = [_stats]
with open("stats.json", "w") as f:
    json.dump(_stats, f)
print("RAMULATOR_DONE stats.json")
'''

def _controller_defs(geo: dict[str, Any], channels: int) -> str:
    """One independent controller (with its OWN dram instance) per channel.

    The frontend already carries the channel in ``addr_vec[0]``, and
    GenericDRAM dispatches on exactly that (``channel_id = req.addr_vec[0]``),
    so a channel count is a wiring change here and a geometry change in the
    lowering — never a substitution of another memory standard.
    """
    blocks = []
    for i in range(channels):
        blocks.append(
            f"_ctrl{i} = ramulator.controller.{geo['controller']}(\n"
            f"    dram=ramulator.dram.{geo['dram_class']}(\n"
            f"        org_preset={geo['org_preset']!r},\n"
            f"        timing_preset={geo['timing_preset']!r},\n"
            "    ),\n"
            "    scheduler=ramulator.scheduler.FRFCFS(),\n"
            "    row_policy=ramulator.row_policy.Open(),\n"
            "    addr_mapper=ramulator.addr_mapper."
            "PassThroughAddrMapper(),\n"
            "    refresh_manager=ramulator.refresh_manager.NoRefresh(),\n"
            ")")
    return "\n".join(blocks)

def _metric(value: Any, unit: str) -> dict[str, Any]:
    return {"value": value, "unit": unit}

def _evidence_base(manifest: MemoryLoweringManifest,
                   backend: RamulatorBackend) -> dict[str, Any]:
    return {"producer": backend.producer(), "fidelity": FIDELITY,
            "memory_artifact_hash":
                manifest.to_dict()["source_memory_artifact_hash"],
            "lowering_manifest_hash": manifest_hash(manifest),
            "backend_input_hash": manifest.to_dict()["trace_sha256"],
            "backend_config_hash":
                manifest.to_dict()["backend_config_hash"]}

def _sha256_hex(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()

def _verify_chain(artifact, manifest: MemoryLoweringManifest,
                  trace: Path) -> None:
    """Re-verify every manifest link against its SOURCE (fail closed).

Rationale: docs/decisions/modules/simulation.md
    """
    md = manifest.to_dict()
    if artifact is not None:
        if artifact.artifact_hash != md["source_memory_artifact_hash"]:
            raise RamulatorError(
                "manifest.source_memory_artifact_hash does not match the "
                f"supplied artifact ({md['source_memory_artifact_hash']} "
                f"vs {artifact.artifact_hash}) — refusing to execute "
                "against a substituted artifact")
        if artifact.access_stream_hash != md["access_stream_hash"]:
            raise RamulatorError(
                "manifest.access_stream_hash does not match the supplied "
                "artifact's access stream — refusing to execute")
    from veritx_dse.workload.memory_lowering import (
        backend_config_payload, RamulatorGeometry)
    geo_d = manifest.geometry
    if not isinstance(geo_d, dict) or "dram_class" not in geo_d:
        raise RamulatorError(
            "manifest.geometry is malformed — refusing to generate a "
            "driver from it")
    try:
        geo_obj = RamulatorGeometry.from_dict(geo_d)
    except (KeyError, TypeError, ValueError) as e:
        raise RamulatorError(
            "manifest.geometry does not reconstruct a valid "
            f"RamulatorGeometry ({e}) — refusing to generate a driver")
    recomputed = _sha256_hex(backend_config_payload(
        geo_obj, manifest.mapping_algorithm))
    if recomputed != md["backend_config_hash"]:
        raise RamulatorError(
            "manifest.backend_config_hash does not match the geometry "
            "that generates the driver — refusing to execute (config "
            "identity must be recomputed, not asserted)")
    n_rd = n_wr = 0
    for ln in trace.read_text().splitlines():
        if not ln.strip():
            continue
        parts = ln.split()
        if len(parts) not in (2, 3) or parts[0] not in ("R", "W"):
            raise RamulatorError(
                "trace line does not parse as a ReadWriteTrace record: "
                f"{ln[:60]!r} — refusing to execute")
        if parts[0] == "R":
            n_rd += 1
        else:
            n_wr += 1
    counts = md["counts"]
    if (n_rd, n_wr, n_rd + n_wr) != (
            counts["read_transactions"], counts["write_transactions"],
            counts["transactions"]):
        raise RamulatorError(
            "trace line counts disagree with the manifest's declared "
            f"transaction counts (recounted R={n_rd} W={n_wr} total="
            f"{n_rd + n_wr} vs declared R={counts['read_transactions']} "
            f"W={counts['write_transactions']} "
            f"total={counts['transactions']}) — refusing to execute")

def execute(artifact, manifest: MemoryLoweringManifest,
            trace_path: str | Path, *,
            backend: RamulatorBackend, run_dir: str | Path,
            timeout: float | None = 600) -> MemoryEvidence:
    """Execute a lowered trace and return typed evidence (never None).

Rationale: docs/decisions/modules/simulation.md
    """
    if not backend.ready:
        raise RamulatorError(
            "backend not built — refusing to invent results "
            f"(expected {backend.ext_path}; build with interpreter "
            f"{backend.python_exe}: cd third_party/ramulator2 && "
            "./build.sh)")
    base = _evidence_base(manifest, backend)
    trace = Path(trace_path)
    rundir = Path(run_dir)
    rundir.mkdir(parents=True, exist_ok=True)

    if not trace.is_file():
        raise RamulatorError(f"trace not found: {trace}")
    import hashlib as _hl
    if "sha256:" + _hl.sha256(trace.read_bytes()).hexdigest() != \
            manifest.to_dict()["trace_sha256"]:
        raise RamulatorError(
            f"trace {trace} does not match the manifest's trace_sha256 "
            "— refusing to execute a substituted input")
    _verify_chain(artifact, manifest, trace)

    unsupported = _check_supported(manifest)
    if unsupported is not None:
        return MemoryEvidence(
            status="UNSUPPORTED", failure_reason=unsupported,
            metrics={}, assumptions=(), semantic_losses=(), raw={}, **base)

    geo = manifest.geometry
    channels = int(geo.get("levels", {}).get("channel", 1))
    driver = _DRIVER_TEMPLATE.format(
        trace_path=str(trace.resolve()),
        controller_defs=_controller_defs(geo, channels),
        controller_list=", ".join(f"_ctrl{i}" for i in range(channels)))
    (rundir / "driver.py").write_text(driver)
    stats_path = rundir / "stats.json"
    if stats_path.exists():
        stats_path.unlink()
    import os as _os
    env = dict(_os.environ)
    env["PYTHONPATH"] = str(backend.package_dir) + (
        f":{_os.environ['PYTHONPATH']}" if "PYTHONPATH" in _os.environ
        else "")
    t0 = time.monotonic()
    try:
        from veritx_dse.core.process import supervised_run
        res = supervised_run([backend.python_exe, "driver.py"],
                             cwd=str(rundir), timeout=timeout, env=env)
    except subprocess.TimeoutExpired as e:
        out_blob = getattr(e, "stdout", None)
        if out_blob is None:
            out_blob = getattr(e, "output", None)
        err_blob = getattr(e, "stderr", None)
        for name, blob in (("stdout", out_blob), ("stderr", err_blob)):
            if isinstance(blob, str):
                blob = blob.encode()
            (rundir / f"{name}.log").write_bytes(blob or b"")
        return MemoryEvidence(
            status="EVALUATION_FAILED",
            failure_reason=f"backend timed out after {timeout}s "
                           "(partial debris retained — a timeout is a "
                           "failed evaluation, never an infeasible design)",
            metrics={"wall_time_s": _metric(round(time.monotonic() - t0, 3),
                                            "seconds")},
            assumptions=(), semantic_losses=(),
            raw={"run_dir": str(rundir)}, **base)
    (rundir / "stdout.log").write_text(res.stdout or "")
    (rundir / "stderr.log").write_text(res.stderr or "")
    wall = round(time.monotonic() - t0, 3)
    if res.returncode != 0:
        tail = "\n".join((res.stderr or "").splitlines()[-8:])
        return MemoryEvidence(
            status="EVALUATION_FAILED",
            failure_reason=f"backend exited {res.returncode}: {tail}",
            metrics={"wall_time_s": _metric(wall, "seconds")},
            assumptions=(), semantic_losses=(),
            raw={"run_dir": str(rundir)}, **base)
    stats_path = rundir / "stats.json"
    if not stats_path.is_file():
        return MemoryEvidence(
            status="EVALUATION_FAILED",
            failure_reason="backend produced no stats.json — output "
                           "exists is not evidence",
            metrics={"wall_time_s": _metric(wall, "seconds")},
            assumptions=(), semantic_losses=(),
            raw={"run_dir": str(rundir)}, **base)
    try:
        stats = json.loads(stats_path.read_text())
    except ValueError as e:
        return MemoryEvidence(
            status="EVALUATION_FAILED",
            failure_reason=f"stats.json unparseable ({e})",
            metrics={"wall_time_s": _metric(wall, "seconds")},
            assumptions=(), semantic_losses=(),
            raw={"run_dir": str(rundir)}, **base)
    if not isinstance(stats, dict) and not isinstance(stats, list):
        return MemoryEvidence(
            status="EVALUATION_FAILED",
            failure_reason="stats.json is neither an object nor an array "
                           "— refusing to type metrics from it",
            metrics={"wall_time_s": _metric(wall, "seconds")},
            assumptions=(), semantic_losses=(),
            raw={"run_dir": str(rundir)}, **base)
    merged = merge_channel_stats(stats)
    if not merged:
        return MemoryEvidence(
            status="EVALUATION_FAILED",
            failure_reason="stats.json carries no controller stats — "
                           "refusing to type metrics from nothing",
            metrics={"wall_time_s": _metric(wall, "seconds")},
            assumptions=(), semantic_losses=(),
            raw={"run_dir": str(rundir)}, **base)
    return _verdict(manifest, merged, wall, rundir, base)

def _verdict(manifest: MemoryLoweringManifest, stats: dict,
             wall: float, rundir: Path, base: dict) -> MemoryEvidence:
    """Drain-aware verdict from reconciled counters (the §drain contract)."""
    m = manifest.to_dict()
    tx = manifest.transaction_bytes
    exp_rd = m["counts"]["read_transactions"]
    exp_wr = m["counts"]["write_transactions"]
    acc_rd = stats.get("num_read_reqs")
    acc_wr = stats.get("num_write_reqs")
    sv_rd = stats.get("num_read_reqs_served")
    sv_wr = stats.get("num_write_reqs_served")
    coal_wr = stats.get("num_write_reqs_coalesced")
    metrics: dict[str, Any] = {
        "wall_time_s": _metric(wall, "seconds"),
        "issued_read_transactions": _metric(exp_rd, "requests"),
        "issued_write_transactions": _metric(exp_wr, "requests"),
    }
    for key, name, unit in _TYPED_STATS:
        if key in stats and isinstance(stats[key], (int, float)):
            metrics[name] = _metric(stats[key], unit)
    if isinstance(coal_wr, int) and not isinstance(coal_wr, bool) \
            and coal_wr:
        metrics["coalesced_write_requests"] = _metric(coal_wr, "requests")
    if isinstance(sv_rd, int) and isinstance(sv_wr, int):
        metrics["completed_read_bytes"] = _metric(sv_rd * tx, "bytes")
        metrics["completed_write_bytes"] = _metric(sv_wr * tx, "bytes")
    metrics["generated_requests"] = _metric(exp_rd + exp_wr, "requests")
    metrics["accepted_requests"] = _metric(
        (acc_rd if isinstance(acc_rd, int) else 0)
        + (acc_wr if isinstance(acc_wr, int) else 0), "requests")
    _sv_rd = sv_rd if isinstance(sv_rd, int) else 0
    _sv_wr = sv_wr if isinstance(sv_wr, int) else 0
    _coal = coal_wr if isinstance(coal_wr, int) else 0
    metrics["completed_requests"] = _metric(_sv_rd + _sv_wr + _coal, "requests")
    metrics["outstanding_requests"] = _metric(
        max(0, (exp_rd + exp_wr) - (_sv_rd + _sv_wr + _coal)), "requests")
    try:
        (_acc_ok, short) = _reconcile(exp_rd, exp_wr, acc_rd, acc_wr,
                                      sv_rd, sv_wr, coal_wr)
    except RamulatorError as e:
        return MemoryEvidence(
            status="INCONCLUSIVE", failure_reason=str(e), metrics=metrics,
            assumptions=(), semantic_losses=(),
            raw={"run_dir": str(rundir),
                 "accepted": {"read": acc_rd, "write": acc_wr},
                 "served": {"read": sv_rd, "write": sv_wr}}, **base)
    if short:
        return MemoryEvidence(
            status="INCONCLUSIVE", failure_reason=short, metrics=metrics,
            assumptions=("request_generation: recorded stream "
                         "(see memory artifact assumptions)",
                         "dram_timing: MEMORY_CYCLE_SIMULATION"),
            semantic_losses=(), raw={"run_dir": str(rundir)}, **base)
    return MemoryEvidence(
        status="PASS", failure_reason="", metrics=metrics,
        assumptions=("request_generation: recorded stream "
                     "(see memory artifact assumptions)",
                     "dram_timing: MEMORY_CYCLE_SIMULATION"),
        semantic_losses=(), raw={"run_dir": str(rundir)}, **base)

def _reconcile(exp_rd: int, exp_wr: int, acc_rd: Any, acc_wr: Any,
               sv_rd: Any, sv_wr: Any, coal_wr: Any) -> tuple[bool, str]:
    """(ok, shortfall_reason). Missing counters refuse (never zero-fill).

    Coalesced writes count as completed: the controller absorbs them into
    an already-buffered write (callback fires at absorb time) and reports
    them under num_write_reqs_coalesced — an independent counter that must
    reconcile, not a tautology.
    """
    for name, v in (("num_read_reqs", acc_rd),
                    ("num_write_reqs", acc_wr),
                    ("num_read_reqs_served", sv_rd),
                    ("num_write_reqs_served", sv_wr)):
        if not isinstance(v, int) or isinstance(v, bool):
            raise RamulatorError(
                f"backend omitted counter {name!r} — a missing metric is "
                "not zero (refusing to reconcile against absence)")
    if not isinstance(coal_wr, int) or isinstance(coal_wr, bool):
        raise RamulatorError(
            "backend omitted counter 'num_write_reqs_coalesced'")
    if acc_rd != exp_rd or acc_wr != exp_wr:
        return (False,
                f"backend loss: issued {exp_rd}R/{exp_wr}W but controller "
                f"accepted {acc_rd}R/{acc_wr}W")
    if sv_rd != acc_rd or sv_wr + coal_wr != acc_wr:
        return (False,
                f"drain shortfall: accepted {acc_rd}R/{acc_wr}W but only "
                f"served {sv_rd}R/{sv_wr}W (+{coal_wr} coalesced) at EOF "
                "(ReadWriteTrace reports pre-drain — PASS requires full "
                "drain)")
    return (True, "")
