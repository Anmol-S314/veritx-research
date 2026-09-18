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

from ..core.errors import BookSimError, TimeoutError, TraceError
from ..core.logging import Ctx, log, ok, fail, verbose, debug
from ..model.presets import Topology, count_anynet_edges, topo_size as _preset_topo_size


# ── Errors ──────────────────────────────────────────────────────────────────
# Canonical definitions live in veritx_dse.core.errors; re-exported here so
# existing `from veritx_dse.simulation.booksim import BookSimError, TimeoutError`
# keeps working for cli.py / pipeline.py consumers.
__all__ = [
    "BookSimError",
    "TimeoutError",
    "TraceStats",
    "detect_trace_stats",
    "build_config",
    "run_booksim",
    "find_booksim_bin",
    "parse_output",
    "topo_size",
    "run_topology_eval",
    "run_sweep",
]


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
        # detect_trace_stats raises TraceError on unreadable/malformed
        # traces (no silent zero-fallback). Handle it explicitly here so a
        # missing trace still yields a runnable config with a conservative
        # default span — loudly, not silently.
        try:
            stats = detect_trace_stats(trace_path)
            sp = sample_period or max(200, stats.max_cycle + 1000)
        except TraceError as e:
            import sys as _sys2
            print(f"WARNING: detect_trace_stats failed for {trace_path}: {e} — "
                  f"using default sample_period", file=_sys2.stderr)
            sp = sample_period or 1000
        # Span-based sampling: trace end + margin. A huge sample_period (the
        # old 10M default) makes the vendored BookSim spin through empty
        # event-queue cycles after the trace drains instead of exiting —
        # every sweep/compare eval then burns its whole timeout. Span+margin
        # exits cleanly once all packets land (verified against the standalone
        # reference binary); callers can still override explicitly.
        params["traffic"] = f"trace({trace_abs})"
        params["sample_period"] = sp
        # For trace-driven mode, use max_samples = 1
        # The sample_period is set to trace_span + 10000, which forces
        # BookSim to run until all events are consumed in one pass
        params["max_samples"] = 1
    else:  # throughput
        # NOTE: BookSim's UniformRandom pattern ignores the (rate) suffix —
        # the load comes from the separate `injection_rate` param (default
        # 0.1 when unset). Both are emitted so --ir/--sensitivity/--set
        # actually move the operating point.
        params["traffic"] = f"uniform({ir})"
        params["injection_rate"] = ir
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
    # Trace mode always aborts effectively-disabled: Run() drains to
    # completion regardless, so a mid-run abort only corrupts stats — tails
    # ejected after the abort are excluded from plat/accepted counts
    # (seen: 918 tails silently dropped from a torus replay). 1e15 trips
    # never; an explicit latency_thres still overrides (synthetic modes
    # keep the 1e6 saturation guard).
    if latency_thres > 0:
        params["latency_thres"] = latency_thres
    elif sim_type == "latency":
        params["latency_thres"] = 1000000000000000.0
    else:
        params["latency_thres"] = 1000000.0

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
    # Throughput mode only: trace-driven runs must not carry an injection
    # rate (the trace owns injection); build_config only sets the key in
    # throughput mode, so presence here is the mode signal.
    if "injection_rate" in params:
        lines.insert(4, f"injection_rate = {params['injection_rate']};")
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
                Default: core.process.supervised_run — full lifecycle
                ownership (process-group, TERM->KILL escalation, bounded
                capture). Injectable for testing.

    Returns parsed result dict with at least 'latency' key on success.
    Raises BookSimError on failure, TimeoutError on timeout. The timeout
    carries the captured partial stdout/stderr (diagnostics for §27
    "simulator exits before producing output").
    """
    import time
    if runner is None:
        from ..core.process import supervised_run

        def runner(cmd, cwd, timeout):
            return supervised_run(cmd, cwd=cwd, timeout=timeout,
                                  on_timeout="complete")
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
        # PR E (verified-PRD §4/§6.9/§10.4): units are data, and the
        # executable is provenance. Core BookSim metrics are typed at the
        # source — never naked numbers — and the binary identity rides
        # with every result it produced.
        from ..core.runs import binary_identity, metric
        result["metrics"] = {}
        result["booksim_binary"] = binary_identity(bin_path)

        def _typed(key: str, name: str, unit: str, scope: str = "per_packet"):
            if key in result:
                result["metrics"][name] = metric(
                    name, result[key], unit,
                    producer="booksim2", fidelity="NETWORK_SIMULATION",
                    scope=scope)
        # The supervisor ended the child at the budget: a timeout, never a
        # measurement — even if partial stats reached stdout before the
        # kill. Classified before every other verdict so sweeps record
        # "timeout" instead of a zero-delivered/partial-stats error.
        # Type-checked (not getattr): injected runners return plain
        # CompletedProcess/mocks with no supervision contract, and they
        # must take the legacy path unchanged.
        from ..core.process import SupervisedResult
        if isinstance(r, SupervisedResult) and r.timed_out:
            raise TimeoutError(
                f"{label} timed out after {timeout}s",
                returncode=r.returncode, stdout=r.stdout, stderr=r.stderr,
            )
        # Zero packets delivered is a topology/trace mismatch, not a
        # measurement: every latency stat prints "=" and "latency" is
        # legitimately absent. Diagnose loudly instead of leaving callers
        # to trip over the missing key.
        if result.get("delivered", 1) == 0:
            _pkts = result.get("pkt_count")
            raise BookSimError(
                f"{label}: 0 packets delivered"
                + (f" (trace holds {_pkts})" if _pkts else "")
                + " — topology cannot carry this trace (check node addressing/IDs)",
                returncode=r.returncode, stdout=r.stdout, stderr=r.stderr,
            )
        # A parsed latency is only a measurement if the process COMPLETED.
        # A BookSim that die()s mid-Run (deadlock guard, assert) can still
        # have printed a partial-stats latency line; accepting it turned a
        # crashed run into plausible data. Nonzero rc => BookSimError with
        # the parsed partials attached for diagnostics.
        if r.returncode != 0 and ("latency" in result or "completion_time" in result):
            raise BookSimError(
                f"BookSim exited {r.returncode} after printing partial stats "
                f"({ {k: result[k] for k in ('latency', 'completion_time') if k in result} }) "
                "— treating as failure, not a measurement",
                returncode=r.returncode,
                stdout=r.stdout,
                stderr=r.stderr,
            )
        if "latency" not in result:
            stderr_tail = r.stderr.strip().splitlines()[-10:] if r.stderr else []
            # Decode POSIX wait-status signals — "exit -11" is a bug-shaped
            # mystery; "segmentation fault" is actionable.
            _sig = {4: "SIGILL (illegal instruction)", 6: "SIGABRT (abort)",
                    7: "SIGBUS", 8: "SIGFPE (arithmetic)",
                    11: "SIGSEGV (segmentation fault)",
                    13: "SIGPIPE", 15: "SIGTERM"}
            how = _sig.get(-r.returncode) if r.returncode < 0 else None
            cause = f" — crashed with {how}" if how else f" (exit {r.returncode})"
            first_err = next((l for l in stderr_tail
                              if l.strip() and not l.startswith("BookSim")), "")
            detail = f": {first_err.strip()}" if first_err else ""
            raise BookSimError(
                f"No latency in BookSim output{cause}{detail}",
                returncode=r.returncode,
                stdout=r.stdout,
                stderr="\n".join(stderr_tail),
            )
        if result.get("unstable"):
            result["warning"] = "Simulation unstable — latency may be unreliable"
        # Type the core metrics (after all parse/verdict logic; injected
        # runners' plain results type identically since parse_output drove
        # the same keys).
        _typed("completion_time", "completion_time", "cycles", scope="trace")
        _typed("latency", "packet_latency_average", "cycles")
        _typed("p50", "packet_latency_p50", "cycles")
        _typed("p99", "packet_latency_p99", "cycles")
        _typed("hops", "hops_average", "hops")
        _typed("throughput", "accepted_packet_rate", "packets_per_cycle",
               scope="network")
        return result

    except subprocess.TimeoutExpired:
        raise TimeoutError(f"{label} timed out after {timeout}s")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ── Result parsing ──────────────────────────────────────────────────────────

# Number-shaped field value. [0-9.eE+\-]+ would match a bare "-" — BookSim's
# stats module prints "= -" for a stat with no samples (e.g. zero packets
# delivered) — and float("-") then crashes the whole batch.
NUM = r"((?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"


def parse_output(stdout: str) -> dict:
    """Parse BookSim stdout for latency/hops/throughput/completion_time."""
    result = {}
    expecting_max = False
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
        m = re.search(rf"Packet latency average\s*=\s*{NUM}", line)
        if m:
            result["latency"] = float(m.group(1))
            # F8 evidence candidate: the \tmaximum within THIS block
            # (grammar: average, minimum, maximum — before "Network
            # latency average"). Guarded: NaN blocks (packet-less
            # phase/class) never produce the key.
            expecting_max = True
        if expecting_max:
            if line.startswith("Network latency average"):
                expecting_max = False  # block ended with no real max
            else:
                m2 = re.fullmatch(rf"\tmaximum = ({NUM})", line)
                if m2:
                    v = float(m2.group(1))
                    if v == v and abs(v) != float("inf"):  # NaN/inf guard
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
        # F3 evidence: the VeritX fork emits flit TOTALS at the
        # trace-drain-success point (the only point where the counters
        # provably hold the full-run values). Summed over classes by the
        # fork itself; stock BookSim prints none — keys stay absent, so
        # F3 stays NOT_RUN instead of reading a fabricated zero.
        m = re.search(r"VeritX: injected flits total = (\d+)", line)
        if m:
            result["flits_injected"] = int(m.group(1))
        m = re.search(r"VeritX: accepted flits total = (\d+)", line)
        if m:
            result["flits_accepted"] = int(m.group(1))
    return result


def evidence_from_result(result: dict) -> dict:
    """Map a BookSim result to the F-check evidence vocabulary.

    The seam between Step 3 (simulate) and Step 4 (verify): what the
    simulator measured, translated to the keys verify_design consumes.
    Honest-by-construction:

      * absent stats produce ABSENT keys — a stock binary that prints
        no flit totals yields no F3 evidence at all, never a fabricated
        zero (a zero would masquerade as a measured zero)
      * NO derived drop counter: injected - accepted is an arithmetic
        identity, and feeding it to F3's injected == completed + dropped
        would make the check verify nothing. Instead F3 applies
        complete-delivery semantics to a drained run: any gap between
        injected and ejected flits is loss inside the fabric.
      * pkt_count rides along as booksim_pkts_expected for corroboration
    """
    ev: dict = {}
    inj = result.get("flits_injected")
    acc = result.get("flits_accepted")
    if inj is not None and acc is not None:
        ev["booksim_injected_flits"] = int(inj)
        ev["booksim_completed_flits"] = int(acc)
    if result.get("max_packet_latency") is not None:
        ev["max_packet_latency_cycles"] = float(result["max_packet_latency"])
    if result.get("pkt_count") is not None:
        ev["booksim_pkts_expected"] = int(result["pkt_count"])
    return ev


# ── Trace stats ─────────────────────────────────────────────────────────────

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
            "span": self.span,
            "ir": self.ir,
        }


@lru_cache(maxsize=64)
def detect_trace_stats(trace_path: str) -> TraceStats:
    """Detect trace stats: max_cycle, num_classes, num_packets, srcs, IR.

    This is the SINGLE function for trace analysis. All callers use this.
    Never passes "classes" to BookSim — only counts for display.

    Raises TraceError on unreadable/malformed traces instead of silently
    returning zeros — a zeroed span would size sample_period wrong and
    synthesize/evaluate against missing data. An existing-but-empty trace
    (comments only) still returns zeros so callers can report
    "no parseable packets" via ``num_packets == 0``.
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
        raise TraceError(f"Cannot read trace {trace_path}: {e}") from e
    except ValueError as e:
        raise TraceError(f"{trace_path}: malformed trace data: {e}") from e
    except Exception as e:
        raise TraceError(f"{trace_path}: failed to parse trace: {e}") from e
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


# ── High-level helpers ──────────────────────────────────────────────────────

def topo_size(topo: Topology) -> tuple[int, int]:
    """(nodes, edges) for a Topology — delegates to presets.topo_size().

    Single source of truth: all node/edge math lives in
    veritx_dse.model.presets. This wrapper preserves the
    ``topo_size(Topology)`` signature for backward compat.
    """
    return _preset_topo_size(topo)


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
    overrides: dict[str, Any] | None = None,
    runner: Any | None = None,
) -> dict:
    """Evaluate a single topology on a trace. Returns result dict.

    This is the main entry point for single-topology evaluation.
    Handles config building, execution, and result enrichment.
    The rendered BookSim config is stashed on the result ("config") so
    saved JSONs are self-reproducing.
    """
    config = build_config(
        topo, trace_path,
        sim_type=sim_type, ir=ir, seed=seed,
        overrides=overrides,
    )
    result = run_booksim(ctx, config, repo_root=repo_root, timeout=timeout,
                         runner=runner)
    result["name"] = topo.name
    result["topology"] = topo.backend
    result["routing"] = topo.routing
    result["seed"] = seed
    result["config"] = config
    if overrides:
        result["overrides"] = dict(overrides)

    # Enrich with edge count and node count (shared helper so failure
    # records elsewhere carry real dimensions instead of zeros).
    n_nodes, n_edges = topo_size(topo)
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
    overrides: dict[str, Any] | None = None,
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
                overrides=overrides,
            )
            results.append(r)
        except TimeoutError:
            _nn, _ne = topo_size(topo)
            results.append({
                "name": topo.name, "topology": topo.backend,
                "error": "timeout", "nodes": _nn, "edges": _ne,
            })
        except BookSimError as e:
            _nn, _ne = topo_size(topo)
            results.append({
                "name": topo.name, "topology": topo.backend,
                "error": str(e), "nodes": _nn, "edges": _ne,
            })
    return results
