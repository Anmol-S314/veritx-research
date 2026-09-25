"""The independent authority: a hand-authored BookSim configuration.

This module deliberately imports NOTHING from ``veritx_dse``. It authors
its own config from the experiment's declared fabric, chooses its own
(independent) convergence window, runs the vendored binary directly, and
parses the output with its own regexes. If it reused the product's parser
or projector, a defect there would agree with itself — exactly the
failure mode F-0001 exposed.

Independence class of this authority: ``standalone_booksim``. It shares
the BookSim *engine* with the canonical path, so it can catch a
projector that silently changes physics, but not a defect inside BookSim
itself. That limitation is recorded in every report.
"""
from __future__ import annotations

import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: the authority's own convergence window (NOT the product's): a generous
#: single sample that comfortably covers any trace this corpus runs.
_WINDOW_MARGIN = 2000

_LOADED = re.compile(r"Loaded (?:text|binary) trace: (\d+) packets")
_COMPLETION = re.compile(r"Completion time is (\d+) cycles")
_WINDOW = re.compile(r"Time taken is (\d+) cycles")
_INJECTED_FLITS = re.compile(r"VeritX: injected flits total = (\d+)")
_ACCEPTED_FLITS = re.compile(r"VeritX: accepted flits total = (\d+)")
_HOPS = re.compile(r"Hops average = ([0-9.eE+-]+)")
_DRAIN = re.compile(r"injected=(\d+)")


class AuthorityError(RuntimeError):
    """The authority could not produce a measurement — fail closed."""


@dataclass(frozen=True)
class AuthorityResult:
    completion_cycles: int
    sample_window_cycles: int | None
    loaded_packets: int
    injected_packets: int | None
    injected_flits: int | None
    accepted_flits: int | None
    hops_avg: float | None
    returncode: int
    command: tuple[str, ...]
    stderr_tail: str
    config_text: str


def author_mesh_dor_config(*, k: int, num_vcs: int, trace_lines: int,
                           routing_function: str = "dim_order",
                           window_margin: int = _WINDOW_MARGIN) -> str:
    """Author a native-mesh DOR config from declared facts only."""
    if k < 1:
        raise AuthorityError(f"mesh radix must be >= 1, got {k}")
    if num_vcs < 1:
        raise AuthorityError(f"num_vcs must be >= 1, got {num_vcs}")
    sample_period = trace_lines + window_margin
    lines = [
        "topology = mesh;",
        f"k = {k};",
        "n = 2;",
        "use_noc_latency = 1;",
        f"routing_function = {routing_function};",
        f"num_vcs = {num_vcs};",
        "classes = 1;",
        "router = iq;",
        "priority = none;",
        "link_failures = 0;",
        "traffic = trace(workload.trace);",
        f"sample_period = {sample_period};",
        "max_samples = 1;",
        "injection_rate = 0.0;",
        "injection_rate_uses_flits = 1;",
        "injection_process = bernoulli;",
        "sim_type = latency;",
        # BookSim's traffic-manager aborts the whole simulation once the
        # running latency average crosses this threshold (compiled default
        # 500). Aborting is a convergence heuristic, not physics; the
        # authority must measure the same drain the canonical path (which
        # pins 1e15) measures, or packets are silently dropped and
        # conservation compares against a truncated run.
        "latency_thres = 1000000000000000.0;",
        "sim_count = 1;",
        "warmup_periods = 0;",
        "measure_stats = 1;",
        "print_activity = 0;",
        "viewer_trace = 0;",
        "sim_power = 0;",
    ]
    return "\n".join(lines) + "\n"


def parse_authority_output(stdout: str, stderr: str) -> dict:
    """The authority's OWN parser. Never imported from the product."""
    loaded = _LOADED.search(stdout)
    completion = _COMPLETION.search(stdout)
    if loaded is None or completion is None:
        raise AuthorityError(
            "authority output lacks 'Loaded ... trace: N packets' or "
            "'Completion time is N cycles'; refusing to report a "
            "measurement")
    window = _WINDOW.search(stdout)
    injected_flits = _INJECTED_FLITS.search(stdout)
    accepted_flits = _ACCEPTED_FLITS.search(stdout)
    hops = _HOPS.search(stdout)
    drain = _DRAIN.search(stderr or "")
    return {
        "loaded_packets": int(loaded.group(1)),
        "completion_cycles": int(completion.group(1)),
        "sample_window_cycles": int(window.group(1)) if window else None,
        "injected_packets": int(drain.group(1)) if drain else None,
        "injected_flits": int(injected_flits.group(1))
        if injected_flits else None,
        "accepted_flits": int(accepted_flits.group(1))
        if accepted_flits else None,
        "hops_avg": float(hops.group(1)) if hops else None,
    }


def run_standalone(*, spec_fabric, prepared, binary: Path, run_dir: Path,
                   timeout_s: int,
                   window_margin: int = _WINDOW_MARGIN) -> AuthorityResult:
    """Author the config, run the binary directly, parse independently."""
    compute_tiles = spec_fabric.compute_tiles
    k = math.isqrt(compute_tiles)
    if k * k != compute_tiles:
        raise AuthorityError(
            f"mesh requires a square tile count, got {compute_tiles}")
    trace_text = prepared.trace_text
    trace_lines = len([ln for ln in trace_text.splitlines() if ln.strip()])
    config = author_mesh_dor_config(
        k=k, num_vcs=spec_fabric.num_vcs, trace_lines=trace_lines,
        window_margin=window_margin)

    target = Path(run_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / "workload.trace").write_text(trace_text)
    (target / "config.cfg").write_text(config)

    command = (str(binary), "config.cfg")
    try:
        proc = subprocess.run(list(command), cwd=str(target),
                              stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=timeout_s, shell=False)
    except subprocess.TimeoutExpired as exc:
        raise AuthorityError(
            f"standalone BookSim timed out after {timeout_s}s") from exc
    if proc.returncode != 0:
        raise AuthorityError(
            f"standalone BookSim exited {proc.returncode}: "
            f"{(proc.stderr or '')[-300:]}")
    parsed = parse_authority_output(proc.stdout, proc.stderr)
    return AuthorityResult(
        completion_cycles=parsed["completion_cycles"],
        sample_window_cycles=parsed["sample_window_cycles"],
        loaded_packets=parsed["loaded_packets"],
        injected_packets=parsed["injected_packets"],
        injected_flits=parsed["injected_flits"],
        accepted_flits=parsed["accepted_flits"],
        hops_avg=parsed["hops_avg"],
        returncode=proc.returncode, command=command,
        stderr_tail=(proc.stderr or "")[-400:], config_text=config)
