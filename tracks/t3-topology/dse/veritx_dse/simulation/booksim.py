"""veritx_dse.booksim — BookSim2 config generation, execution, and result parsing.

Single source of truth for:
  - Building BookSim config strings (never duplicated)
  - Running BookSim subprocess with proper timeout/error handling
  - Parsing latency/hops/throughput from BookSim stdout
  - Trace stats detection

All functions receive Ctx for logging. All errors are raised as
BookSimError (never sys.exit) so callers can handle failures.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..core.logging import Ctx, log, ok, fail, verbose, debug
from ..model.presets import Topology, count_anynet_edges


# ── Errors ──────────────────────────────────────────────────────────────────

class BookSimError(Exception):
    """Raised when BookSim execution fails."""
    def __init__(self, message: str, returncode: int = -1, stdout: str = "", stderr: str = ""):
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TimeoutError(BookSimError):
    """Raised when BookSim exceeds the time limit."""
    pass


# ── Config builder (single source of truth) ────────────────────────────────

# Default BookSim parameters. Every run starts from this base.
BASE_PARAMS: dict[str, Any] = {
    "num_vcs": 4,
    "vc_buf_size": 8,
    "wait_for_tail_credit": 1,
    "vc_allocator": "islip",
    "sw_allocator": "islip",
    "alloc_iters": 1,
    "credit_delay": 1,
    "routing_delay": 0,
    "vc_alloc_delay": 1,
    "sw_alloc_delay": 1,
    "input_speedup": 1,
    "output_speedup": 1,
    "internal_speedup": 1.0,
    "packet_size": 8,
}


def build_config(
    topo: Topology,
    trace_path: str,
    *,
    sim_type: str = "latency",
    ir: float = 0.05,
    sample_period: int | None = None,
    latency_thres: float = -1.0,
    seed: int | None = None,
    overrides: dict[str, Any] | None = None,
) -> str:
    """Build a complete BookSim config string.

    This is the SINGLE function that generates BookSim configs.
    All other code delegates here.

    CRITICAL ordering: BookSim parses top-to-bottom. k/n must come BEFORE
    topology= so the network is built with correct dimensions.
    Also: NEVER pass "classes" — it creates separate traffic classes with
    split VCs, inflating latency 75x for multi-class traces.
    """
    # Start from base params
    params = dict(BASE_PARAMS)

    # Apply topology-specific overrides first (k, n, c, o, d)
    params.update(topo.params)

    # GEC topologies need special handling
    if topo.needs_noc_latency_zero:
        params["use_noc_latency"] = 0
        # GEC requires deferred routing
        params["routing_delay"] = 1
        # MECS needs num_vcs >= d (one VC sub-range per tap on shared channel)
        d_val = topo.params.get("d", 0)
        if d_val > 0 and params["num_vcs"] < d_val:
            params["num_vcs"] = d_val + 1

    # Traffic source
    trace_abs = str(Path(trace_path).resolve())
    if " " in trace_abs:
        import sys as _sys
        print(f"WARNING: trace path contains spaces — BookSim may fail: {trace_abs}", file=_sys.stderr)
    if sim_type == "latency":
        stats = detect_trace_stats(trace_path)
        # Span-based sampling: trace end + margin. A huge sample_period (the
        # old 10M default) makes the vendored BookSim spin through empty
        # event-queue cycles after the trace drains instead of exiting —
        # every sweep/compare eval then burns its whole timeout. Span+margin
        # exits cleanly once all packets land (verified against the standalone
        # reference binary); callers can still override explicitly.
        sp = sample_period or max(200, stats.max_cycle + 1000)
        params["traffic"] = f"trace({trace_abs})"
        params["sample_period"] = sp
        # For trace-driven mode, use max_samples = 1
        # The sample_period is set to trace_span + 10000, which forces
        # BookSim to run until all events are consumed in one pass
        params["max_samples"] = 1
    else:  # throughput
        params["traffic"] = f"uniform({ir})"
        params["sample_period"] = 1000
        params["max_samples"] = 3

    # Simulation type and thresholds
    params["sim_type"] = sim_type
    # The vendored BookSim lexer reads "-1.0" as integer -1 and then fails
    # with "Unknown integer field: latency_thres" (the field is registered
    # float-only). -1 was meant as "threshold disabled"; the equivalent
    # that actually parses is a threshold larger than any real run (same
    # workaround multi_workload_pareto.py uses vs the 500-cycle default,
    # which would abort long simulations).
    params["latency_thres"] = latency_thres if latency_thres > 0 else 1000000.0

    # Seed (for reproducibility)
    if seed is not None:
        params["seed"] = seed

    # Apply any extra overrides
    if overrides:
        params.update(overrides)

    # Topology and routing MUST come last (after k/n) so BookSim
    # parses dimensions before constructing the network.
    params["topology"] = topo.backend
    # BookSim automatically appends topology suffix to routing function
    # e.g., routing_function=min_adapt + topology=torus -> min_adapt_torus
    # So we just pass the base routing name without the suffix
    params["routing_function"] = topo.routing

    # Handle anynet specially (needs network_file on its own line)
    if topo.backend == "anynet":
        return _build_anynet_config(params, topo)

    # Standard config: one line per param
    lines = [f"{k} = {v};" for k, v in params.items()]
    return "\n".join(lines) + "\n"


def _build_anynet_config(params: dict, topo: Topology) -> str:
    """Build config for anynet topology (needs network_file path)."""
    network_file = topo.params.get("network_file", "")
    lines = [
        f"topology = anynet;",
        f"routing_function = min;",
        f"network_file = {network_file};",
        f"traffic = {params['traffic']};",
        f"num_vcs = {params['num_vcs']};",
        f"vc_buf_size = {params['vc_buf_size']};",
        f"sim_type = {params['sim_type']};",
        f"sample_period = {params['sample_period']};",
        f"max_samples = {params['max_samples']};",
        f"wait_for_tail_credit = {params.get('wait_for_tail_credit', 1)};",
        f"latency_thres = {params.get('latency_thres', 1000000.0)};",
        f"packet_size = {params.get('packet_size', 8)};",
    ]
    return "\n".join(lines) + "\n"


# ── Execution ──────────────────────────────────────────────────────────────

@lru_cache(maxsize=16)
def find_booksim_bin(repo_root: Path) -> Path:
    """Locate the BookSim binary."""
    candidates = [
        repo_root / "third_party" / "booksim2" / "src" / "booksim",
        repo_root / "third_party" / "booksim2" / "build" / "booksim",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(
        f"BookSim binary not found. Tried: {[str(c) for c in candidates]}\n"
        "Build it: cd third_party/booksim2/src && make -j$(nproc)"
    )


def run_booksim(
    ctx: Ctx,
    config: str,
    *,
    repo_root: Path,
    timeout: int = 60,
    label: str = "BookSim",
    runner: Any | None = None,
) -> dict:
    """Run BookSim with the given config string.

    Args:
        runner: Optional callable(cmd, cwd, timeout) -> CompletedProcess.
                Default: subprocess.run. Injectable for testing.

    Returns parsed result dict with at least 'latency' key on success.
    Raises BookSimError on failure, TimeoutError on timeout.
    """
    import time
    if runner is None:
        runner = lambda cmd, cwd, timeout: subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=cwd, stdin=subprocess.DEVNULL,
        )
    scratch = repo_root / "runs" / "booksim"
    scratch.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(dir=scratch))
    try:
        cfg_path = workdir / "sim.cfg"
        cfg_path.write_text(config)

        bin_path = find_booksim_bin(repo_root)
        debug(ctx, f"BookSim config:\n{config}")

        t0 = time.perf_counter()
        r = runner(
            [str(bin_path), str(cfg_path.resolve())],
            cwd=str(workdir.resolve()),
            timeout=timeout,
        )
        wall_time = time.perf_counter() - t0

        result = parse_output(r.stdout)
        result["wall_time_s"] = round(wall_time, 3)
        if "latency" not in result:
            stderr_tail = r.stderr.strip().splitlines()[-10:] if r.stderr else []
            raise BookSimError(
                f"No latency in BookSim output (exit {r.returncode})",
                returncode=r.returncode,
                stdout=r.stdout,
                stderr="\n".join(stderr_tail),
            )
        if result.get("unstable"):
            result["warning"] = "Simulation unstable — latency may be unreliable"
        return result

    except subprocess.TimeoutExpired:
        raise TimeoutError(f"{label} timed out after {timeout}s")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ── Result parsing ──────────────────────────────────────────────────────────

def parse_output(stdout: str) -> dict:
    """Parse BookSim stdout for latency/hops/throughput/completion_time."""
    result = {}
    for line in stdout.splitlines():
        # Completion time (primary metric for trace-driven mode)
        m = re.search(r"Completion time is\s+(\d+)\s+cycles", line)
        if m:
            result["completion_time"] = int(m.group(1))
        # Fallback: Time taken (includes drain, less accurate)
        elif "completion_time" not in result:
            m = re.search(r"Time taken is\s+(\d+)\s+cycles", line)
            if m:
                result["completion_time"] = int(m.group(1))
        # Packet latency stats
        m = re.search(r"Packet latency average\s*=\s*([0-9.eE+\-]+)", line)
        if m:
            result["latency"] = float(m.group(1))
        m = re.search(r"\tp50\s*=\s*([0-9.eE+\-]+)", line)
        if m:
            result["p50"] = float(m.group(1))
        m = re.search(r"\tp95\s*=\s*([0-9.eE+\-]+)", line)
        if m:
            result["p95"] = float(m.group(1))
        m = re.search(r"\tp99\s*=\s*([0-9.eE+\-]+)", line)
        if m:
            result["p99"] = float(m.group(1))
        m = re.search(r"\tpkt_count\s*=\s*(\d+)", line)
        if m:
            result["pkt_count"] = int(m.group(1))
        m = re.search(r"Hops average\s*=\s*([0-9.eE+\-]+)", line)
        if m:
            result["hops"] = float(m.group(1))
        m = re.search(r"Accepted packet rate average\s*=\s*([0-9.eE+\-]+)", line)
        if m:
            result["throughput"] = float(m.group(1))
        if "unstable" in line.lower() or "Too many sample periods" in line:
            result["unstable"] = True
    return result


# ── Trace stats ─────────────────────────────────────────────────────────────

@dataclass
class TraceStats:
    """Parsed statistics about a trace file."""
    max_cycle: int = 0
    num_classes: int = 1
    num_packets: int = 0
    num_srcs: int = 0
    span: int = 1
    ir: float = 0.0

    def to_dict(self) -> dict:
        return {
            "max_cycle": self.max_cycle,
            "num_classes": self.num_classes,
            "num_packets": self.num_packets,
            "num_srcs": self.num_srcs,
            "span": self.span,
            "ir": self.ir,
        }


@lru_cache(maxsize=64)
def detect_trace_stats(trace_path: str) -> TraceStats:
    """Detect trace stats: max_cycle, num_classes, num_packets, srcs, IR.

    This is the SINGLE function for trace analysis. All callers use this.
    Never passes "classes" to BookSim — only counts for display.
    """
    max_cycle = 0
    num_classes = 1
    num_packets = 0
    srcs: set[int] = set()
    try:
        with open(trace_path) as f:
            for line in f:
                if line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 5:
                    c = int(parts[0])
                    src = int(parts[1])
                    cl = int(parts[2])
                    num_packets += 1
                    srcs.add(src)
                    if c > max_cycle:
                        max_cycle = c
                    if cl > 0 and num_classes <= cl:
                        num_classes = cl + 1
    except Exception:
        pass
    span = max_cycle + 1
    ir = num_packets / max(span, 1)
    return TraceStats(
        max_cycle=max_cycle,
        num_classes=num_classes,
        num_packets=num_packets,
        num_srcs=len(srcs),
        span=span,
        ir=ir,
    )


# ── High-level helpers ──────────────────────────────────────────────────────

def run_topology_eval(
    ctx: Ctx,
    topo: Topology,
    trace_path: str,
    *,
    repo_root: Path,
    seed: int | None = None,
    timeout: int = 60,
    sim_type: str = "latency",
    ir: float = 0.05,
) -> dict:
    """Evaluate a single topology on a trace. Returns result dict.

    This is the main entry point for single-topology evaluation.
    Handles config building, execution, and result enrichment.
    """
    config = build_config(
        topo, trace_path,
        sim_type=sim_type, ir=ir, seed=seed,
    )
    result = run_booksim(ctx, config, repo_root=repo_root, timeout=timeout)
    result["name"] = topo.name
    result["topology"] = topo.backend
    result["routing"] = topo.routing
    result["seed"] = seed

    # Enrich with edge count and node count
    n_nodes, n_edges = 0, 0
    if topo.backend == "anynet":
        nf = topo.params.get("network_file", "")
        if nf:
            n_nodes, n_edges = count_anynet_edges(nf)
    else:
        n_edges = topo.edges()
        # Compute node count from topology params
        if topo.backend in ("mesh", "torus"):
            k = topo.params.get("k", 8)
            n = topo.params.get("n", 2)
            n_nodes = k ** n
        elif topo.backend == "flatfly":
            k = topo.params.get("k", 4)
            n_dim = topo.params.get("n", 2)
            c = topo.params.get("c", 4)
            n_nodes = (k ** n_dim) * c
        elif topo.backend == "gec":
            k = topo.params.get("k", 8)
            c = topo.params.get("c", 1)
            n_nodes = k * k * c
    result["nodes"] = n_nodes
    result["edges"] = n_edges

    return result


def run_sweep(
    ctx: Ctx,
    trace_path: str,
    *,
    topos: list[Topology] | None = None,
    repo_root: Path,
    timeout: int = 60,
    sim_type: str = "latency",
    ir: float = 0.05,
) -> list[dict]:
    """Run BookSim on multiple topologies, return list of results.

    Each result: {name, latency, hops, throughput, edges, error}.
    """
    from ..model.presets import SWEEP_TOPOS
    topos = topos or SWEEP_TOPOS
    results = []
    for topo in topos:
        try:
            r = run_topology_eval(
                ctx, topo, trace_path,
                repo_root=repo_root, timeout=timeout,
                sim_type=sim_type, ir=ir,
            )
            results.append(r)
        except TimeoutError:
            results.append({
                "name": topo.name, "topology": topo.backend,
                "error": "timeout", "nodes": 0, "edges": topo.edges(),
            })
        except BookSimError as e:
            results.append({
                "name": topo.name, "topology": topo.backend,
                "error": str(e), "nodes": 0, "edges": topo.edges(),
            })
    return results
