"""veritx_dse.booksim — BookSim2 config generation, execution, and result parsing.

WHO READS WHAT: `latency` is the stock BookSim average and is REQUIRED — it
is the key the certified evidence path reads. `honest_latency` is the
trace-population average and is carried in the stored stats dict for
comparison only; the certified path does not substitute it.

Rationale: docs/decisions/modules/simulation.md
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

from ..core.errors import BookSimError, TimeoutError, TraceError
from ..core.logging import Ctx, log, ok, fail, verbose, debug
from ..model.presets import Topology, count_anynet_edges

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
    max_samples: int = 1,
    latency_thres: float = -1.0,
    seed: int | None = None,
    overrides: dict[str, Any] | None = None,
) -> str:
    """Build a complete BookSim config string.

Rationale: docs/decisions/modules/simulation.md
    """
    params = dict(BASE_PARAMS)

    params.update(topo.params)

    if topo.needs_noc_latency_zero:
        params["use_noc_latency"] = 0
        params["routing_delay"] = 1
        d_val = topo.params.get("d", 0)
        if d_val > 0 and params["num_vcs"] < d_val:
            params["num_vcs"] = d_val + 1

    trace_abs = str(Path(trace_path).resolve())
    if " " in trace_abs:
        import sys as _sys
        print(f"WARNING: trace path contains spaces — BookSim may fail: {trace_abs}", file=_sys.stderr)
    if sim_type == "latency":
        try:
            stats = detect_trace_stats(trace_path)
            sp = sample_period or max(10000000, stats.max_cycle + 10000)
        except TraceError as e:
            import sys as _sys2
            print(f"WARNING: detect_trace_stats failed for {trace_path}: {e} — "
                  f"using default sample_period", file=_sys2.stderr)
            sp = sample_period or 1000
        params["traffic"] = f"trace({trace_abs})"
        params["sample_period"] = sp
        params["max_samples"] = 1
    else:
        params["traffic"] = f"uniform({ir})"
        params["sample_period"] = 1000
        params["max_samples"] = 3

    params["sim_type"] = sim_type
    params["latency_thres"] = latency_thres

    if seed is not None:
        params["seed"] = seed

    if overrides:
        params.update(overrides)

    params["topology"] = topo.backend
    params["routing_function"] = topo.routing

    if topo.backend == "anynet":
        return _build_anynet_config(params, topo)

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
        f"latency_thres = {params.get('latency_thres', -1.0)};",
        f"packet_size = {params.get('packet_size', 8)};",
    ]
    return "\n".join(lines) + "\n"

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

NUM = r"((?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"

def parse_output(stdout: str) -> dict:
    """Parse BookSim stdout for latency/hops/throughput/completion_time.

Rationale: docs/decisions/modules/simulation.md
    """
    result = {}
    expecting_max = False
    for line in stdout.splitlines():
        m = re.search(r"Completion time is\s+(\d+)\s+cycles", line)
        if m:
            result["completion_time"] = int(m.group(1))
        elif "completion_time" not in result:
            m = re.search(r"Time taken is\s+(\d+)\s+cycles", line)
            if m:
                result["completion_time"] = int(m.group(1))
        m = re.search(rf"Packet latency average\s*=\s*{NUM}", line)
        if m:
            result["latency"] = float(m.group(1))
            expecting_max = True
        if expecting_max:
            if line.startswith("Network latency average"):
                expecting_max = False
            else:
                m2 = re.fullmatch(rf"\tmaximum = ({NUM})", line)
                if m2:
                    v = float(m2.group(1))
                    if v == v and abs(v) != float("inf"):
                        result["max_packet_latency"] = v
                    expecting_max = False
        m = re.search(rf"\tp50\s*=\s*{NUM}", line)
        if m:
            result["p50"] = float(m.group(1))
        m = re.search(rf"\tp95\s*=\s*{NUM}", line)
        if m:
            result["p95"] = float(m.group(1))
        m = re.search(rf"\tp99\s*=\s*{NUM}", line)
        if m:
            result["p99"] = float(m.group(1))
        m = re.search(r"\tpkt_count\s*=\s*(\d+)", line)
        if m:
            result["pkt_count"] = int(m.group(1))
        m = re.search(rf"Hops average\s*=\s*{NUM}", line)
        if m:
            result["hops"] = float(m.group(1))
        m = re.search(rf"Accepted packet rate average\s*=\s*{NUM}", line)
        if m:
            result["throughput"] = float(m.group(1))
        m = re.search(rf"\thonest_avg\s*=\s*{NUM}", line)
        if m:
            result["honest_latency"] = float(m.group(1))
        if "unstable" in line.lower() or "Too many sample periods" in line:
            result["unstable"] = True
        if "Trace replay complete" in line or "drain incomplete" in line:
            result["drain_verdict"] = line.strip()
        m = re.search(r"delivered (\d+) packets", line)
        if m:
            result["delivered"] = int(m.group(1))
        m = re.search(r"VeritX: injected flits total = (\d+)", line)
        if m:
            result["flits_injected"] = int(m.group(1))
        m = re.search(r"VeritX: accepted flits total = (\d+)", line)
        if m:
            result["flits_accepted"] = int(m.group(1))
    return result

@dataclass
class TraceStats:
    """Parsed statistics about a trace file."""
    max_cycle: int = 0
    num_classes: int = 1
    num_packets: int = 0
    num_srcs: int = 0
    max_node: int = 0
    span: int = 1
    ir: float = 0.0

    def to_dict(self) -> dict:
        return {
            "max_cycle": self.max_cycle,
            "num_classes": self.num_classes,
            "num_packets": self.num_packets,
            "num_srcs": self.num_srcs,
            "max_node": self.max_node,
            "span": self.span,
            "ir": self.ir,
        }

@lru_cache(maxsize=64)
def detect_trace_stats(trace_path: str) -> TraceStats:
    """Detect trace stats: max_cycle, num_classes, num_packets, srcs, IR.

Rationale: docs/decisions/modules/simulation.md
    """
    max_cycle = 0
    num_classes = 1
    num_packets = 0
    srcs: set[int] = set()
    max_node = 0
    try:
        with open(trace_path) as f:
            for line_no, line in enumerate(f, 1):
                if line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 5:
                    try:
                        c = int(parts[0])
                        src = int(parts[1])
                        cl = int(parts[2])
                        dst = int(parts[3])
                    except ValueError as e:
                        raise TraceError(
                            f"{trace_path}: line {line_no}: non-integer field: {e}"
                        ) from e
                    num_packets += 1
                    srcs.add(src)
                    max_node = max(max_node, src, dst)
                    if c > max_cycle:
                        max_cycle = c
                    if cl > 0 and num_classes <= cl:
                        num_classes = cl + 1
    except TraceError:
        raise
    except FileNotFoundError as e:
        raise TraceError(f"Trace not found: {trace_path}") from e
    except OSError as e:
        raise TraceError(f"{trace_path}: failed to read trace: {e}") from e
    span = max_cycle + 1
    ir = num_packets / max(span, 1)
    return TraceStats(
        max_cycle=max_cycle,
        num_classes=num_classes,
        num_packets=num_packets,
        num_srcs=len(srcs),
        max_node=max_node,
        span=span,
        ir=ir,
    )

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

    n_nodes, n_edges = 0, 0
    if topo.backend == "anynet":
        nf = topo.params.get("network_file", "")
        if nf:
            n_nodes, n_edges = count_anynet_edges(nf)
    else:
        n_edges = topo.edges()
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
