#!/usr/bin/env python3
"""ASTRA-Sim 2.0 Experiment Runner for T3 Topologies.

Runs ASTRA-Sim 2.0 with the BookSim 2.0 network backend across T3 topologies
(mesh4x4, torus4x4, fattree16, flatfly16, etc.) driven by dynamic collective
workloads (LLaMA-7B, LLaMA-13B, LLaMA-70B, GPT-3, ResNet-50, custom models, and
microbenchmark collective traces generated as Chakra Execution Traces).

Results are written to results/$(CONFIG)/astrasim_sweep.json and integrated into
results/$(CONFIG)/topology_sweep.json for downstream analysis (analysis.py, aggregate.py, noc_energy_bridge.py).

Usage
-----
    python3 scripts/run_astrasim.py --config baseline --model llama7b
    python3 scripts/run_astrasim.py --config baseline --model llama70b --tp 8 --pp 8
    python3 scripts/run_astrasim.py --selfcheck
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

# sys[N] finished lines arrive twice: the frontend logs each completion once
# with a `[timestamp] [workload] [info]` prefix (stderr-style) and once plain
# (stdout) — sometimes with slightly different cycle counts. The result
# parser max()es them, so display dedupes by sys id, first copy wins.
_SYS_DONE_RE = re.compile(r"sys\[(\d+)\]\s+finished")
_ZERO_DRAIN_RE = re.compile(r"injected=0\b.*draining")
# Ledger markers (frontend emits these iff VERITX_LEDGER=1, which the driver
# below always sets): a submit proves the collective was ISSUED (the old
# no-issue hang class never submits); a completion proves progress.
_COLL_SUBMIT_RE = re.compile(r"\[LEDGER\]\[COLL_SUBMIT\]")
_COLL_DONE_RE = re.compile(r"\[LEDGER\]\[COLL_COMPLETE\]")

# Embedded packetization. The frontend injects ONE wormhole packet per send
# with flits = ceil(bytes / flit_bytes); the frontend default is 8 B, which
# turns a 16 MiB collective into ~2.1M flits in one packet and stalls against
# 8-flit VC buffers. Until packetization is modelled properly (B3
# PacketFormat/lowering), runs use an explicitly recorded coarse override.
_BACKEND_DEFAULT_FLIT_BYTES = 8
_DEFAULT_FLIT_BYTES = 128
_PACKETIZATION_MODEL = "single_wormhole_packet_per_send"
# NOTE: --booksim2-embedded-mtu is the architecturally correct direction
# (bounded packets instead of one message-sized packet) but is currently
# EXPERIMENTAL / BROKEN for large sends: with thousands of fragments the
# frontend stalls at its first cycle. Not wired into runs; B3 packetization
# owns the proper fix.


def _resolve_flit_bytes(env=None) -> int:
    """ASTRASIM_FLIT_BYTES override, else the operational coarse default."""
    raw = (env if env is not None else os.environ).get(
        "ASTRASIM_FLIT_BYTES", str(_DEFAULT_FLIT_BYTES))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError(
            f"ASTRASIM_FLIT_BYTES must be an int, got {raw!r}") from None
    if value <= 0:
        raise ValueError(f"ASTRASIM_FLIT_BYTES must be > 0, got {value}")
    return value


def _packetization_record(flit_bytes: int, message_size_bytes=None,
                          embedded_mtu_flits: int = 0) -> dict:
    """Comparison key for ASTRA rows. Two results differing in any of these
    are NOT equivalent-fidelity comparisons (flit width changes the modeled
    NoC, and an inflated flit only buys simulation speed)."""
    return {
        "packetization_model": _PACKETIZATION_MODEL,
        "flit_bytes": int(flit_bytes),
        "flit_bits": int(flit_bytes) * 8,   # derived display, not authority
        "embedded_mtu_flits": int(embedded_mtu_flits),
        "packetization_fidelity": (
            "backend_default" if flit_bytes == _BACKEND_DEFAULT_FLIT_BYTES
            else "coarse_packetization_override"),
        "message_size_bytes": message_size_bytes,
    }


def _packetization_banner(rec: dict) -> str:
    mtu = rec["embedded_mtu_flits"] or "disabled"
    return (
        "\n  ASTRA packetization:\n"
        f"    message model : {rec['packetization_model']}\n"
        f"    flit bytes    : {rec['flit_bytes']}\n"
        f"    flit width    : {rec['flit_bits']} bits\n"
        f"    MTU           : {mtu}\n"
        f"    fidelity      : {rec['packetization_fidelity']}"
    )



def _stall_update(fresh_text: str, stall_since, issued_since, now: float,
                  limit_s: int, slow_limit_s: int):
    """Backend-stall state machine. Pure function so --selfcheck pins it.

    Two tiers (lesson of 2026-09-14: a healthy 64-rank 16 MB allreduce needs
    ~9 min, and `injected=0` at drain-start is NORMAL — the BookSim uniform
    counter never counts embedded API injection, and a 10 us comp node means
    nothing has injected yet when the drain line prints):
    - no-issue hang (the original class: trace consumed, collective never
      issued): armed on zero-injection drain, trips past limit_s.
    - stuck collective (issued but never completes): trips past slow_limit_s.
    Disarms fully on any rank completion; each COLL_COMPLETE re-arms the
    slow clock (completions are progress). Draining WITH BookSim packets in
    flight never arms. Returns (trip_kind, stall_since, issued_since) with
    trip_kind None | "no-issue" | "stuck".
    """
    if _SYS_DONE_RE.search(fresh_text):
        return None, None, None
    submitted = bool(_COLL_SUBMIT_RE.search(fresh_text))
    completed = bool(_COLL_DONE_RE.search(fresh_text))
    if issued_since is not None and completed:
        issued_since = now  # progress: a collective finished
    if stall_since is None:
        if _ZERO_DRAIN_RE.search(fresh_text):
            stall_since = now
            if submitted:
                issued_since = now
        return None, stall_since, issued_since
    if submitted and issued_since is None:
        issued_since = now  # work was issued: not the no-issue hang class
    if issued_since is None:
        if now - stall_since > limit_s:
            return "no-issue", stall_since, issued_since
    elif now - issued_since > slow_limit_s:
        return "stuck", stall_since, issued_since
    return None, stall_since, issued_since

HERE = Path(__file__).parent
TRACK = HERE.parent
CONFIGS_DIR = TRACK / "configs"
RESULTS_DIR = TRACK / "results"

# astrasim_adapter lives in the package now (scripts/ copy removed).
# This script runs BOTH ways — inside the container (no package on
# sys.path, the ModuleNotFoundError that broke `t3 astrasim` 2026-09-16)
# and on the host — so anchor the package root before importing. The other
# scripts here are imported from $T3_DIR (cwd) as before.
_DSE_ROOT = str(HERE / "dse")
if _DSE_ROOT not in sys.path:
    sys.path.insert(0, _DSE_ROOT)
from veritx_dse.simulation.astrasim_adapter import (
    prepare_astrasim_config_dir, parse_booksim_cfg)
from generate_chakra_trace import ChakraTraceGenerator, save_chakra_trace
from lib.t3log import SweepLogger, log_crash
from lib.t3models import get_model, to_spec


def find_astrasim_bin() -> Optional[str]:
    """Locate the astrasim binary: ASTRASIM_BIN, then the repo-built
    frontend, then PATH.

    A set-but-dangling ASTRASIM_BIN (e.g. pointing at a checkout that was
    moved or deleted) must not masquerade as "unset": warn loudly, fall
    through, and let the refusal message name the real situation if nothing
    is found.
    """
    env_bin = os.environ.get("ASTRASIM_BIN")
    if env_bin:
        if Path(env_bin).exists():
            return env_bin
        print(f"  [warn] ASTRASIM_BIN is set but does not exist: {env_bin} "
              "(stale env from a moved/deleted checkout?) — probing other "
              "locations.")
    repo_bin = (TRACK.parent.parent / "third_party" / "astra-sim" / "astra-sim"
                / "network_frontend" / "booksim2" / "bin" / "AstraSim_BookSim2")
    if repo_bin.is_file() and os.access(repo_bin, os.X_OK):
        return str(repo_bin)
    return shutil.which("astrasim") or shutil.which("astra-sim")


def _parse_plat_line(stdout: str) -> Optional[dict]:
    """Parse the frontend's [plat] per-packet summary (one line, last wins).

    Emitted by AstraSim_BookSim2 at end of each round:
      [plat] packets=480 avg=23.375 min=19 p50=19 p95=44 p99=44 max=44
             hops_avg=2.875 hops_min=2 hops_max=7
    Values are exact retire-time measurements (EmbedTM::PlatStats), not
    estimates. Returns None when the binary predates the feature.
    """
    import re
    result = None
    for line in stdout.splitlines():
        if "[plat]" not in line:
            continue
        fields = dict(re.findall(r"(\w+)=([0-9.eE+-]+)", line))
        if fields:
            result = fields
    return result


def run_astrasim_topology(
    cfg_path: Path,
    spec: Dict[str, Any],
    config_name: str = "baseline"
) -> dict:
    """Run ASTRA-Sim for a single topology config and dynamic workload spec.

    One run per topology: embedded mode injects the Chakra collective packets
    via the frontend API (``--booksim2-extra=injection_rate=0.0``), so the
    standalone-BookSim injection-rate sweep dimension is meaningless here —
    every rate produced identical cycle counts and 6x the wall-clock.
    """
    # Honesty gate FIRST (spec-mandated no-synthetic-fallback): with no
    # binary anywhere, refuse before anything else — including before the PP
    # guard below — so a missing binary is never misreported as a model
    # problem, and no case dirs are prepped for a run that cannot happen.
    # (The late `else` branch stays as TOCTOU cover for a binary deleted
    # mid-flight.) Contract: run_astrasim_topology(any spec, no binary)
    # always raises naming the env (see test_astrasim_spine_contract).
    if not find_astrasim_bin():
        raise RuntimeError(
            "ASTRA-sim binary not found (ASTRASIM_BIN unset and no astrasim "
            "on PATH). Refusing to substitute a synthetic BookSim run: build "
            "the frontend (third_party/astra-sim/build/astra_booksim2/build.sh) "
            "or set ASTRASIM_BIN to "
            ".../network_frontend/booksim2/bin/AstraSim_BookSim2.")
    # Replicated-trace guard: every rank runs the identical shared .et, so
    # pipeline stage transfers (absolute per-rank P2P src/dst, plus missing
    # RECV pairing) are un-routable in this design. PP>1 needs per-rank
    # sharded traces (future work). main() aborts before dispatch; reaching
    # here with PP>1 means a bypass — refuse rather than burn a timeout.
    if (spec.get("pp_degree", 1) or 1) > 1:
        raise RuntimeError(
            f"pp_degree={spec.get('pp_degree')} requires per-rank sharded "
            "traces (not implemented); rerun with --pp 1 for single-stage mode")
    model_name = spec.get("model_name", "workload").lower().replace(" ", "_")

    out_dir = (
        RESULTS_DIR
        / config_name
        / "astrasim"
        / model_name
        / cfg_path.stem
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Prepare ASTRA-Sim system, network, and logical topology configs
    cfg_info = prepare_astrasim_config_dir(cfg_path, out_dir, spec=spec)

    # 2. Generate Chakra Execution Trace DAG (.et and .et.json) for this model
    gen = ChakraTraceGenerator()
    if spec.get("is_collective_microbenchmark"):
        trace_nodes = gen.build_collective_trace(comm_type=spec.get("model_name", "ALL_REDUCE"))
    else:
        trace_nodes = gen.build_model_trace(spec)
    
    chakra_res = save_chakra_trace(trace_nodes, out_dir, model_name, spec=spec)
    et_path = Path(chakra_res["et_binary"])

    # Packetization provenance: the comparison key for ASTRA rows. A coarse
    # flit is a speed knob, not the modeled NoC — record it and say so.
    _comm_sizes = [
        int((n.get("attr") or {}).get("comm_size"))
        for n in trace_nodes
        if n.get("type") == 7 and (n.get("attr") or {}).get("comm_size")
    ]
    packetization = _packetization_record(
        _resolve_flit_bytes(),
        message_size_bytes=max(_comm_sizes, default=None),
    )
    if packetization["packetization_fidelity"] != "backend_default":
        print(_packetization_banner(packetization))

    # The frontend resolves per-rank workloads as <base>.<rank>.et (it logs
    # "idle NPU, treating as empty" otherwise and every sys finishes at 0
    # cycles). Replicate the model trace to all ranks: with TP=1 this is
    # exactly data-parallel semantics (each rank runs full layers, collectives
    # synchronize across ranks). Proper TP/DP sharding of the trace is a
    # modeling decision for later; this proves the execution chain end to end.
    import shutil as _shutil
    _total_ranks = (cfg_info.get("total_nodes", 0) or 0)
    for _rank in range(_total_ranks):
        _shutil.copy(et_path, Path(str(et_path) + f".{_rank}.et"))

    astrasim_bin = find_astrasim_bin()

    if astrasim_bin:
        # Run real ASTRA-Sim binary
        cmd = [
            astrasim_bin,
            "--system-configuration=" + str(out_dir / "system.json"),
            "--network-configuration=" + str(out_dir / "network.json"),
            "--logical-topology-configuration=" + str(out_dir / "logical_topology.json"),
            "--workload-configuration=" + str(et_path),
            "--memory-configuration=" + str(out_dir / "memory.json"),
            "--remote-memory-configuration=" + str(out_dir / "memory.json"),
            # Embedded mode owns injection: the frontend injects collective
            # packets via API. The template cfgs carry standalone-style
            # `injection_rate = 0.1` (uniform); without this override the TM
            # self-injects infinite synthetic traffic and the run spins in
            # router alloc forever. Cfgs stay standalone-capable untouched.
            "--booksim2-extra=injection_rate=0.0",
            # Explicit embedded flit granularity (recorded in the row). See
            # _packetization_record: 8 B makes a 16 MiB send a 2.1M-flit
            # wormhole packet that stalls against 8-flit VC buffers.
            "--booksim2-flit-bytes=" + str(packetization["flit_bytes"]),
        ]
        import time as _time
        import threading as _threading
        _t0 = _time.time()
        _timeout_s = int(os.environ.get("ASTRASIM_TIMEOUT", "1800"))
        # Stream (don't capture-and-block): tee frontend stdout/stderr to
        # run.log live so `tail -f` works, echo key lines, heartbeat every
        # 60s so a 45-min dragonfly doesn't look hung. Full text kept for
        # the cycles/[plat] parse below.
        _run_log = out_dir / "run.log"
        _out_lines: list[str] = []
        _err_lines: list[str] = []
        _echoed_sys: set[str] = set()  # sys ids already echoed (dedupe double-print)
        _lock = _threading.Lock()
        _done = _threading.Event()
        def _fmt_elapsed(s: float) -> str:
            s = int(s)
            return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"
        def _is_interesting(line: str) -> bool:
            # Tight: rank-completion lines (sys[i] finished) + plat summary +
            # node count + errors. Excludes per-rank [statistics] repeats
            # (Wall/GPU/Comm restate the finished line x3).
            if "[plat]" in line or "# of nodes" in line:
                return True
            low = line.lower()
            if "error" in low or "parse error" in low or "assert" in low:
                return True
            return "sys[" in line and "finished" in line
        def _pump(stream, store: list[str], is_stdout: bool):
            try:
                with open(_run_log, "a") as _lf:
                    for _line in iter(stream.readline, ""):
                        with _lock:
                            store.append(_line)
                        try:
                            _lf.write(("[stdout] " if is_stdout else "[stderr] ") + _line)
                            _lf.flush()
                        except OSError:
                            pass
                        if _is_interesting(_line.rstrip()):
                            _stripped = _line.rstrip()
                            _show = True
                            _m = _SYS_DONE_RE.search(_stripped)
                            if _m:
                                with _lock:
                                    if _m.group(1) in _echoed_sys:
                                        _show = False
                                    else:
                                        _echoed_sys.add(_m.group(1))
                            if _show:
                                print(f"\n    | {cfg_path.stem}: {_stripped[:160]}", flush=True)
            finally:
                try:
                    stream.close()
                except OSError:
                    pass
        try:
            _run_log.write_text(f"$ {' '.join(cmd)}\n")
            # VERITX_LEDGER=1: per-collective issue/complete markers on stderr.
            # The stall watchdog below NEEDS them (a submit proves the no-issue
            # hang class is not what we're seeing); volume is lines per
            # collective op, negligible next to sim runtime. Kept out of the
            # live echo by _is_interesting, but persisted in run.log.
            _env = dict(os.environ)
            _env["VERITX_LEDGER"] = "1"
            _proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     stdin=subprocess.DEVNULL, text=True, bufsize=1,
                                     env=_env)
            _t_out = _threading.Thread(target=_pump, args=(_proc.stdout, _out_lines, True), daemon=True)
            _t_err = _threading.Thread(target=_pump, args=(_proc.stderr, _err_lines, False), daemon=True)
            _t_out.start(); _t_err.start()
            _last_beat = 0.0  # non-TTY log throttle (TTY ticks every second)
            # Backend-stall watchdog, two tiers (see _stall_update): the old
            # single trip killed HEALTHY 64-rank runs — a 16 MB allreduce
            # needs ~9 min, and `injected=0` at drain-start is normal there
            # (10 us comp first; the BookSim uniform counter never counts
            # embedded API injection at all). Tier 1 (no-issue hang: nothing
            # ever submitted) keeps the aggressive limit; tier 2 (issued but
            # stuck) gets the slow limit. Both overridable via env.
            _stall_limit = int(os.environ.get("ASTRASIM_STALL_S", "300"))
            _slow_limit = int(os.environ.get("ASTRASIM_SLOW_S", "900"))
            _scanned_out = _scanned_err = 0
            _stall_since = _issued_since = None
            _was_issued = False
            _n_sub = _n_done = 0
            _last_stall_note = 0.0
            try:
                while True:
                    _rc = _proc.poll()
                    if _rc is not None:
                        print()  # clear the live timer line below
                        break
                    _now = _time.time()
                    if _now - _t0 > _timeout_s:
                        _proc.kill()
                        try:
                            _proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            pass
                        _done.set()
                        _tail = ""
                        with _lock:
                            _tail_lines = "".join(_out_lines).splitlines()[-3:]
                        if _tail_lines:
                            _tail = " | stdout-tail: " + " / ".join(_tail_lines)
                        raise TimeoutError(
                            f"\ntimed out after {_timeout_s}s (elapsed {_fmt_elapsed(_now - _t0)})" + _tail)
                    # Stall check (cheap: only lines appended since last poll;
                    # per-stream cursors — one shared index would skip lines in
                    # the slower stream and could trip on a missed finish).
                    with _lock:
                        _fresh = list(_out_lines[_scanned_out:]) + list(_err_lines[_scanned_err:])
                        _scanned_out, _scanned_err = len(_out_lines), len(_err_lines)
                    _freshtxt = "".join(_fresh)
                    _n_sub += len(_COLL_SUBMIT_RE.findall(_freshtxt))
                    _n_done += len(_COLL_DONE_RE.findall(_freshtxt))
                    _was_armed = _stall_since is not None
                    _trip_kind, _stall_since, _issued_since = _stall_update(
                        _freshtxt, _stall_since, _issued_since,
                        _now, _stall_limit, _slow_limit)
                    if _stall_since is not None and not _was_armed:
                        print(f"\n    ! {cfg_path.stem}: backend in zero-injection drain "
                              f"— killing in {_stall_limit}s unless work issues "
                              f"(slow-guard {_slow_limit}s once issued)",
                              flush=True)
                    if _issued_since is not None and not _was_issued:
                        _was_issued = True
                        print(f"\n    | {cfg_path.stem}: collectives issuing "
                              f"({_n_sub} submitted) — awaiting completion "
                              f"(slow-guard {_slow_limit}s)", flush=True)
                    if (_stall_since is not None and _now - _last_stall_note >= 60):
                        _last_stall_note = _now
                        print(f"\n    | {cfg_path.stem}: still running "
                              f"({_n_sub} submitted, {_n_done} completed)",
                              flush=True)
                    if _trip_kind is not None:
                        _proc.kill()
                        try:
                            _proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            pass
                        _done.set()
                        _tail = ""
                        with _lock:
                            _tail_lines = ("".join(_out_lines) + "".join(_err_lines)).splitlines()[-3:]
                        if _tail_lines:
                            _tail = " | stdout-tail: " + " / ".join(_tail_lines)
                        if _trip_kind == "stuck":
                            raise TimeoutError(
                                f"\nbackend stall: {_n_sub} collectives issued but none "
                                f"completed for {_fmt_elapsed(_now - _issued_since)} "
                                f"(slow-guard {_slow_limit}s via ASTRASIM_SLOW_S)" + _tail)
                        raise TimeoutError(
                            f"\nbackend stall: trace injected 0 packets then drained "
                            f"with nothing issued for {_fmt_elapsed(_now - _stall_since)} "
                            f"(limit {_stall_limit}s via ASTRASIM_STALL_S)" + _tail)
                    # Upward timer on one live line (\r, no newline): one line
                    # per topo instead of a heartbeat every minute. Tick every
                    # second on a TTY, every 60 s into logs/pipes (same info,
                    # no spam). The 1s wait below sets the tick cadence.
                    import sys as _sys
                    _is_tty = _sys.stdout.isatty()
                    if _is_tty or _now - _last_beat >= 60:
                        print(f"\r    ... {cfg_path.stem} {_fmt_elapsed(_now - _t0)} / {_fmt_elapsed(_timeout_s)}",
                              end="", flush=True)
                        _last_beat = _now
                    _done.wait(1.0)
                    if _proc.poll() is not None:
                        break
            except KeyboardInterrupt:
                # Don't orphan the sim: kill the child before unwinding (the
                # sweep loop owns persistence; nothing extra to save here).
                _proc.kill()
                try:
                    _proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                raise
            _t_out.join(timeout=10); _t_err.join(timeout=10)
            import types as _types
            res = _types.SimpleNamespace(returncode=_proc.returncode,
                                         stdout="".join(_out_lines), stderr="".join(_err_lines))
        except subprocess.TimeoutExpired as te:
            # Don't fabricate cycles: a timeout means no usable result.
            # Persist partial stdout tail for post-mortem (BookSim prints
            # progress to stdout; the last lines show where it wedged).
            _tail = ""
            if te.stdout:
                _lines = (te.stdout.decode() if isinstance(te.stdout, bytes)
                          else te.stdout).splitlines()
                _tail = " | stdout-tail: " + " / ".join(_lines[-3:])
            raise TimeoutError(
                f"timed out after {te.timeout}s (elapsed { _time.time()-_t0:.0f}s)" + _tail)
        # Frontend reports per-rank: "sys[i] finished, WALL cycles, exposed
        # communication EXPOSED cycles." Take the max WALL across ranks as the
        # workload's total cycles (slowest rank gates the collective), and the
        # exposed comm from that same rank for the overhead ratio.
        # latency_cycles = total cycles: the collective's wall time is its
        # latency, and ranking topologies by it is exactly what comparison
        # analysis.py's zero_load_latency already does. TRUE per-packet
        # latency percentiles + hop counts come from the [plat] line when
        # the binary emits it (plat_stats below); older binaries leave None.
        cycles = None  # Honest default: unknown until the frontend reports it.
        exposed_best = None
        for line in res.stdout.splitlines():
            if "sys[" in line and "finished" in line:
                try:
                    wall = int(line.split("finished,")[1].split("cycles")[0].strip())
                    exp = None
                    if "exposed communication" in line:
                        exp = int(line.split("exposed communication")[1].split("cycles")[0].strip())
                    if cycles is None or wall > cycles:
                        cycles = wall
                        exposed_best = exp
                except (IndexError, ValueError):
                    pass
        if res.returncode == 0 and cycles is not None:
            status = "ok"
            latency = cycles
            comm_overhead_pct = (round(100.0 * exposed_best / cycles, 2)
                                 if exposed_best is not None and cycles else None)
            plat = _parse_plat_line(res.stdout)
        else:
            plat = None
            # Non-zero exit or unparseable output: no usable cycle count.
            # Keep cycles=None (never the 1000 placeholder) and attach the
            # stderr tail so failures are diagnosable, not silent.
            cycles = None
            latency = None
            comm_overhead_pct = None
            _err_tail = ""
            if res.stderr:
                _err_tail = " | stderr: " + " / ".join(res.stderr.splitlines()[-3:])
            _out_tail = ""
            if res.stdout:
                _out_tail = " | stdout-tail: " + " / ".join(res.stdout.splitlines()[-3:])
            status = f"failed (rc={res.returncode}){_err_tail}{_out_tail}"
        # hops_avg: the frontend never reports per-packet hops — stays None
        # (energy_proxy will be NaN for astrasim rows; use cycles for ranking).
        hops_avg = None
    else:
        # No synthetic fallback (TOCTOU twin of the honesty gate at function
        # top: reachable only if the binary vanishes mid-flight): running
        # plain booksim on the template cfg
        # simulates uniform traffic, NOT the chakra workload, and previously
        # reported it as an ASTRA-sim result with status ok. Refuse loudly.
        raise RuntimeError(
            "ASTRA-sim binary not found (ASTRASIM_BIN unset and no astrasim "
            "on PATH). Refusing to substitute a synthetic BookSim run: build "
            "the frontend (third_party/astra-sim/build/astra_booksim2/build.sh) "
            "or set ASTRASIM_BIN to "
            ".../network_frontend/booksim2/bin/AstraSim_BookSim2.")

    return {
        "topology": cfg_path.stem,
        "workload": _workload_tag(spec),
        "total_nodes": cfg_info["total_nodes"],
        "astrasim_cycles": cycles,
        "latency_cycles": latency if latency is not None else None,
        "exposed_comm_cycles": exposed_best,
        "comm_overhead_pct": comm_overhead_pct,
        # Real per-packet measurements from the [plat] frontend line
        # (packets, avg/min/p50/p95/p99/max latency, hop stats). None when
        # the binary predates the feature — never fabricated.
        "plat_stats": plat,
        # Embedded mode: the frontend injects collectives via API; the 0.0
        # records the injection_rate override actually passed to the TM and
        # keeps the row schema stable for PA-01/aggregate/energy consumers.
        "injection_rate": 0.0,
        "hops_avg": hops_avg if status == "ok" else None,
        "traffic": f"astrasim({model_name}_chakra_et)",
        "et_coll_type": _et_coll_type(spec),
        # Comparison key (flit width/model/fidelity); two rows differing here
        # must not be ranked as equivalent-fidelity ASTRA results.
        **packetization,
        "status": status,
    }


def select_cfgdir(config: str, sizes: str = "auto") -> Path:
    """Resolve the topology cfg directory (testable helper).

    Explicit --sizes wins (n16/n64 → configs/<sizes>); 'auto' keeps the
    legacy CONFIG-suffix sniffing (_N64/_N16, else the mixed configs/ dir)
    so existing invocations don't move. Size-honesty rationale: a 16-node
    topo in an N64 config measures nothing comparable.
    """
    sizes = (sizes or "auto").lower()
    if sizes in ("n16", "n64") and (CONFIGS_DIR / sizes).is_dir():
        return CONFIGS_DIR / sizes
    if sizes == "auto":
        if config.upper().endswith("_N64") and (CONFIGS_DIR / "n64").is_dir():
            return CONFIGS_DIR / "n64"
        if config.upper().endswith("_N16") and (CONFIGS_DIR / "n16").is_dir():
            return CONFIGS_DIR / "n16"
    return CONFIGS_DIR


def _merge_sweep(existing: list, new: list) -> list:
    """Merge ASTRA rows into the shared topology_sweep.json content.

    Rules (see _save): new topologies append; an ok row is never replaced
    by a non-ok row. Pure function so --selfcheck can pin it."""
    by_topo = [r.get("topology") for r in existing if isinstance(r, dict)]
    merged = list(existing)
    for r in new:
        if not isinstance(r, dict) or not r.get("topology"):
            continue
        if r["topology"] in by_topo:
            i = by_topo.index(r["topology"])
            if merged[i].get("status") == "ok" and r.get("status") != "ok":
                continue
            merged[i] = r
        else:
            by_topo.append(r["topology"])
            merged.append(r)
    return merged


def _et_coll_type(spec: dict):
    """Normalized collective for microbench specs, else None.

    feeds the row's et_coll_type field, which keeps resume-skips honest:
    pre-fix non-allreduce microbench rows contain ALLREDUCE numbers under a
    bare label, so they must never satisfy a post-fix resume for the same
    label (None never equals a real type). Pure/testable, no I/O.
    """
    if not spec.get("is_collective_microbenchmark"):
        return None
    try:
        if str((TRACK / "dse").resolve()) not in sys.path:
            sys.path.insert(0, str(TRACK / "dse"))
        from veritx_dse.model.presets import normalize_collective as _norm
        return _norm(spec.get("model_name", ""))
    except Exception:
        return None


def _workload_tag(spec: dict) -> str:
    """Display/record workload tag: bare name + parallelism.

    (The old `(as ALL_REDUCE)` substitution suffix is gone: the ET encoder
    now writes the real collective type, so the label means what it says.
    Pre-fix non-allreduce microbench rows are still mislabeled on disk —
    see _et_coll_type, which stops resume from trusting them.)
    """
    name = spec.get("model_name", "Model")
    return (f"{name} (TP={spec.get('tp_degree', 1)}, "
            f"PP={spec.get('pp_degree', 1)})")


def _selfcheck():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tp = Path(td)
        cfg = tp / "mesh4x4.cfg"
        cfg.write_text("topology = mesh;\nk = 4;\nn = 2;\nnum_vcs = 4;\npacket_size = 5;\n")
        out_dir = tp / "out"

        gen = ChakraTraceGenerator()
        spec = gen.resolve_spec("llama7b", num_layers=2)
        res = prepare_astrasim_config_dir(cfg, out_dir, spec=spec)
        assert Path(res["out_dir"]).exists()
        assert (out_dir / "system.json").exists()

    # Merge semantics: shared topology_sweep.json is append/overlay, never
    # clobber. Regression: 40 measured rows were once destroyed by a single
    # failure row written blind over the file.
    _ok40 = [{"topology": f"t{i}", "status": "ok"} for i in range(40)]
    _fail1 = [{"topology": "anynet16", "status": "error: timeout"}]
    _m = _merge_sweep(list(_ok40), _fail1)
    assert len(_m) == 41 and all(r["status"] == "ok" for r in _m[:40]), _m
    _m2 = _merge_sweep([{"topology": "a", "status": "ok"}],
                       [{"topology": "a", "status": "error: x"}])
    assert _m2 == [{"topology": "a", "status": "ok"}], _m2
    _m3 = _merge_sweep([{"topology": "a", "status": "error: x"}],
                       [{"topology": "a", "status": "ok"}])
    assert _m3 == [{"topology": "a", "status": "ok"}], _m3

    # Stall watchdog state machine: arm only on zero-injection drain,
    # disarm on any rank finish, trip past the limit. Draining WITH
    # packets in flight must never arm (legitimately slow). Issued work
    # (ledger submit) moves the run to the slow guard; completions reset it.
    _t, _s, _i = _stall_update("routine chatter\n", None, None, 100.0, 300, 900)
    assert (_t, _s, _i) == (None, None, None), (_t, _s, _i)
    _t, _s, _i = _stall_update("[trace] All 10010 cycles, injected=0 — draining\n",
                               None, None, 100.0, 300, 900)
    assert (_t, _s, _i) == (None, 100.0, None), (_t, _s, _i)
    _t, _s, _i = _stall_update("still quiet\n", 100.0, None, 200.0, 300, 900)
    assert (_t, _s, _i) == (None, 100.0, None), (_t, _s, _i)
    _t, _s, _i = _stall_update("still quiet\n", 100.0, None, 401.0, 300, 900)
    assert (_t, _s, _i) == ("no-issue", 100.0, None), (_t, _s, _i)
    _t, _s, _i = _stall_update("sys[3] finished, 99 cycles\n", 100.0, 200.0, 401.0, 300, 900)
    assert (_t, _s, _i) == (None, None, None), (_t, _s, _i)
    _t, _s, _i = _stall_update("[trace] All 5 cycles, injected=120 — draining\n",
                               None, None, 100.0, 300, 900)
    assert (_t, _s, _i) == (None, None, None), (_t, _s, _i)
    # Issued work switches to the slow guard instead of tripping at 300s.
    _t, _s, _i = _stall_update("[LEDGER][COLL_SUBMIT] rank=0\n", 100.0, None, 200.0, 300, 900)
    assert (_t, _s, _i) == (None, 100.0, 200.0), (_t, _s, _i)
    _t, _s, _i = _stall_update("quiet\n", 100.0, 200.0, 500.0, 300, 900)
    assert (_t, _s, _i) == (None, 100.0, 200.0), (_t, _s, _i)  # 300s would have killed this
    _t, _s, _i = _stall_update("quiet\n", 100.0, 200.0, 1101.0, 300, 900)
    assert (_t, _s, _i) == ("stuck", 100.0, 200.0), (_t, _s, _i)
    # A completion resets the slow clock (progress).
    _t, _s, _i = _stall_update("[LEDGER][COLL_COMPLETE] rank=0\n", 100.0, 200.0, 1000.0, 300, 900)
    assert (_t, _s, _i) == (None, 100.0, 1000.0), (_t, _s, _i)
    # Submit + drain in the same batch arms already-issued.
    _t, _s, _i = _stall_update("[LEDGER][COLL_SUBMIT] r=0\n[trace] All 1 cycles, injected=0 — draining\n",
                               None, None, 100.0, 300, 900)
    assert (_t, _s, _i) == (None, 100.0, 100.0), (_t, _s, _i)

    print("selfcheck OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="baseline", help="configuration name (e.g. baseline)")
    ap.add_argument("--model", default="llama7b", help="model workload name (llama7b, llama13b, llama70b, gpt3, resnet50, all_reduce, etc.)")
    ap.add_argument("--hidden-size", type=int, default=None, help="Override hidden size H")
    ap.add_argument("--ffn-size", type=int, default=None, help="Override FFN size H_ffn")
    ap.add_argument("--num-layers", type=int, default=None, help="Override number of layers L")
    ap.add_argument("--seq-len", type=int, default=None, help="Override sequence length S")
    ap.add_argument("--batch-size", type=int, default=None, help="Override batch size B")
    ap.add_argument("--tp", type=int, default=None, help="Tensor parallelism degree")
    ap.add_argument("--pp", type=int, default=None, help="Pipeline parallelism degree")
    ap.add_argument("--selfcheck", action="store_true", help="Run internal regression selfcheck")
    ap.add_argument("--topo", default=None,
                    help="only run configs whose filename stem contains this substring "
                    "(e.g. --topo mesh4x4 for a single-topology smoke test)")
    ap.add_argument("--sizes", default="auto", choices=("auto", "n16", "n64", "legacy"),
                    help="topology-size family: configs/n16, configs/n64, or the legacy "
                    "mixed configs/ dir. 'auto' sniffs the CONFIG suffix (_N64/_N16, "
                    "legacy fallback) — explicit is better: a chain-suffixed CONFIG "
                    "like baseline_N16_N16_N64 only lands in n64 by accident.")
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    gen = ChakraTraceGenerator()
    model_key = args.model.lower()
    _overrides = {"hidden_size": args.hidden_size, "ffn_size": args.ffn_size,
                  "num_layers": args.num_layers, "seq_len": args.seq_len,
                  "batch_size": args.batch_size, "tp_degree": args.tp,
                  "pp_degree": args.pp}
    _rec = get_model(model_key)
    if _rec is not None:
        # Registry hit (builtins are seeded into workloads/ on first use, so
        # llama7b lands here too). CLI overrides win over registry values so
        # one entry can feed several what-ifs.
        spec = to_spec(_rec, _overrides)
    elif model_key in ("all_reduce", "all_to_all", "reduce_scatter", "all_gather"):
        spec = {
            "model_name": model_key.upper(),
            "is_collective_microbenchmark": True,
            "msg_size_mb": 16.0,
            "num_layers": 1,
            "total_allreduce_calls": 1,
            "total_flops": 1e9,
            "tp_degree": 1,
            "pp_degree": 1,
        }
    else:
        try:
            spec = gen.resolve_spec(
                model_key,
                hidden_size=args.hidden_size,
                ffn_size=args.ffn_size,
                num_layers=args.num_layers,
                seq_len=args.seq_len,
                batch_size=args.batch_size,
                tp_degree=args.tp,
                pp_degree=args.pp,
            )
        except ValueError as e:
            print(f"  ✗ {e}", file=sys.stderr)
            sys.exit(2)

    out_res_dir = RESULTS_DIR / args.config
    out_res_dir.mkdir(parents=True, exist_ok=True)

    # PP gate (fail loudly, never warn-and-degrade): the shared replicated
    # trace cannot route pipeline stage transfers, so a PP>1 model would run
    # 30 minutes under the wrong parallelism and then time out. Abort here
    # in seconds — unless the user explicitly accepts single-stage mode
    # with --pp 1 (documented degradation: stage transfers not modeled).
    _reg_pp = ((_rec.get("pp_degree", 1) or 1) if isinstance(_rec, dict) else 1)
    _eff_pp = (spec.get("pp_degree", 1) or 1)
    if _eff_pp > 1 and args.pp != 1:
        print(f"  \u2717 {spec.get('model_name', args.model)} requests "
              f"pp_degree={spec.get('pp_degree')} but per-rank sharded "
              f"traces are not implemented (shared replicated trace cannot "
              f"route P2P stage transfers).", file=sys.stderr)
        print("    rerun with --pp 1 to accept single-stage mode, or wait "
              "for sharded-trace support.", file=sys.stderr)
        sys.exit(2)
    if _reg_pp > 1 and _eff_pp == 1:
        print(f"  note: single-stage mode (registry asked pp_degree={_reg_pp}, "
              f"--pp 1 accepted); P2P stage transfers not modeled")

    # Size-honest candidates (same rule as run_experiments.py --configs).
    # A 16-node topo in an N64 config measured nothing comparable — and
    # the failure row it wrote once destroyed the shared sweep file.
    # Explicit --sizes wins; 'auto' keeps legacy CONFIG-suffix sniffing.
    _cfgdir = select_cfgdir(args.config, getattr(args, "sizes", "auto"))
    configs = sorted(_cfgdir.glob("*.cfg"))

    if args.topo:
        configs = [c for c in configs if args.topo in c.stem]
        if not configs:
            print(f"  \u2717 --topo '{args.topo}' matched no configs in {_cfgdir} "
                  f"(CONFIG={args.config} routes here; --topo is a filename-substring "
                  f"filter, not a size override)", file=sys.stderr)
            sys.exit(2)

    results = []
    import time as _wtime
    _sweep_t0 = _wtime.time()
    _elapsed_hist: list[float] = []

    def _fmt_dur(s: float) -> str:
        s = int(s)
        return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"

    def _save() -> None:
        # Atomic incremental write: the JSON on disk is always the prefix
        # completed so far — a Ctrl-C'd sweep loses nothing that landed.
        for _name in ("astrasim_sweep.json",):
            _tmp = out_res_dir / f"{_name}.tmp"
            _tmp.write_text(json.dumps(results, indent=2))
            _tmp.rename(out_res_dir / _name)  # atomic on POSIX
        # topology_sweep.json is SHARED with the standalone sweep: MERGE by
        # topology, never overwrite. A blind write here once destroyed 40
        # measured rows with a single failure row. Rules: new keys append;
        # an ok row is never replaced by a non-ok row (a failed ASTRA leg
        # must not clobber good standalone data for the same topo).
        _sweep_json = out_res_dir / "topology_sweep.json"
        try:
            _existing = json.loads(_sweep_json.read_text()) \
                if _sweep_json.exists() else []
            if not isinstance(_existing, list):
                _existing = []
        except (json.JSONDecodeError, OSError):
            _existing = []
        _merged = _merge_sweep(_existing, results)
        _tmp = out_res_dir / "topology_sweep.json.tmp"
        _tmp.write_text(json.dumps(_merged, indent=2))
        _tmp.rename(_sweep_json)  # atomic on POSIX

    # Resume: topos already measured (status ok) skip re-running, so an
    # interrupted sweep picks up where it stopped instead of redoing
    # every (multi-minute) topology.
    _sweep_path = out_res_dir / "astrasim_sweep.json"
    if _sweep_path.exists():
        try:
            _loaded = json.loads(_sweep_path.read_text())
            results = _loaded if isinstance(_loaded, list) else []
        except (json.JSONDecodeError, OSError):
            results = []
    # Skip-set is scoped to the exact workload tag: switching MODEL/TP/PP
    # must not reuse topologies measured under a different workload. The
    # et_coll_type key additionally stops pre-fix mislabeled microbench rows
    # (non-allreduce labels containing allreduce numbers, et_coll_type None)
    # from satisfying a post-fix resume for the same label.
    _wl_tag = _workload_tag(spec)
    _wl_type = _et_coll_type(spec)
    _done = {r.get("topology") for r in results
             if r.get("status") == "ok" and r.get("workload") == _wl_tag
             and r.get("et_coll_type") == _wl_type}

    print(f"=== ASTRA-Sim 2.0 + Chakra ET Workload Runner ===")
    print(f"  Model Workload : {spec.get('model_name', args.model)}")
    print(f"  Message Size   : {spec.get('msg_size_mb', 0.0):.1f} MB per collective call")
    print(f"  Parallelism    : TP={spec.get('tp_degree', 1)}, PP={spec.get('pp_degree', 1)}")
    print(f"  Total Layers   : {spec.get('num_layers', 1)}\n")
    print("  Mode           : single run per topology (embedded injection owns "
          "the rate dimension; the standalone-BookSim IR sweep does not apply)")
    print("  Topologies     :", [c.stem for c in configs])
    _planned_done = _done & {c.stem for c in configs}
    if _planned_done:
        print(f"  resuming: {len(_planned_done)} of {len(configs)} topology(ies) "
              f"already measured in {_sweep_path.name}")
    print("  (each line lands the moment its ASTRA-sim run finishes)")
    print()

    # Structured session log: logs/<sweep_id>/events.ndjson + sweep.log.
    slog = SweepLogger("astrasim", args.config,
                       extra={"model": args.model, "topo": args.topo or "",
                              "workload": _wl_tag})

    _n_new_ok = _n_skip = _n_fail = 0
    _cfg_names = {c.stem for c in configs}
    try:
        for _idx, cfg in enumerate(configs, 1):
            _topo_t0 = _wtime.time()
            if cfg.stem in _done:
                _n_skip += 1
                _skip_line = (f"  [{_idx}/{len(configs)}] {cfg.stem:<12} "
                              f"─ already measured, skip")
                print(_skip_line, flush=True)
                slog.session_log(_skip_line)
                slog.log_event("point", topology=cfg.stem, status="skip")
                continue
            if _elapsed_hist:
                _avg = sum(_elapsed_hist) / len(_elapsed_hist)
                _remaining = 1 + sum(1 for _c in configs[_idx:] if _c.stem not in _done)
                _eta_txt = f" | ETA ~{_fmt_dur(_avg * _remaining)}"
            else:
                _eta_txt = ""
            print(f"  [{_idx}/{len(configs)}] Running {cfg.stem:<12} ...{_eta_txt}", flush=True)
            slog.log_event("run_start", topology=cfg.stem)

            # One bad config (missing data file, binary crash) must not kill
            # the other runs. Failures are recorded as status=error with
            # the message — never fabricated, never silent.
            try:
                r = run_astrasim_topology(
                    cfg,
                    spec,
                    args.config
                )
            except KeyboardInterrupt:
                raise
            except Exception as e:  # noqa: BLE001 - record, don't abort sweep
                r = {
                    "topology": cfg.stem,
                    "workload": _workload_tag(spec),
                    "total_nodes": None,
                    "astrasim_cycles": None,
                    "latency_cycles": None,
                    "comm_overhead_pct": None,
                    "injection_rate": 0.0,
                    "hops_avg": None,
                    "traffic": "astrasim(chakra_et)",
                    "status": f"error: {type(e).__name__}: {e}",
                }

            _topo_elapsed = _wtime.time() - _topo_t0
            _elapsed_hist.append(_topo_elapsed)
            # Replace any stale row for this topology (e.g. a failed run
            # being re-measured) so the JSON keeps one row per topology.
            results = [x for x in results if x.get("topology") != cfg.stem]
            results.append(r)
            _save()  # lands the moment this topo finishes — safe to Ctrl-C
            if r.get("status") == "ok":
                _n_new_ok += 1
                _mark, _color = "✓", "\033[32m"
            else:
                _n_fail += 1
                _mark, _color = "✗", "\033[31m"
            latency_text = (
                f"{r['latency_cycles']:.2f} latency"
                if r["latency_cycles"] is not None
                else "no latency"
            )
            cycles_text = (
                f"{r['astrasim_cycles']:>8} total cycles"
                if r["astrasim_cycles"] is not None
                else "       n/a total cycles"
            )
            # Count only the planned set: with --topo, results also holds
            # rows from other topos — they must not inflate this ratio.
            _n_ok = sum(1 for _r in results
                        if _r.get("status") == "ok" and _r.get("topology") in _cfg_names)
            _done_line = (f"  {_color}{_mark}\033[0m [{_idx}/{len(configs)}] {cfg.stem:<12} done in {_fmt_dur(_topo_elapsed)} "
                          f"| {latency_text} | {cycles_text} | {r['status']} "
                          f"(ok={_n_ok}/{len(configs)} | sweep {_fmt_dur(_wtime.time() - _sweep_t0)})")
            print(_done_line, flush=True)
            slog.session_log(_done_line)
            slog.log_event("point", topology=cfg.stem,
                           status=("ok" if r.get("status") == "ok" else "error"),
                           detail=str(r.get("status")),
                           latency_cycles=r.get("latency_cycles"),
                           astrasim_cycles=r.get("astrasim_cycles"),
                           elapsed_ms=int(_topo_elapsed * 1000))
    except KeyboardInterrupt:
        print("\n  interrupted — partial results saved")
        slog.session_log("interrupted — partial results saved")
        slog.finish("interrupted", {"ok": _n_new_ok, "skipped": _n_skip,
                                    "failed": _n_fail})
    except (OSError, subprocess.SubprocessError) as e:
        log_crash(e)  # frontend missing / crashed out — record, re-raise
        raise

    _save()
    out_astrasim_json = out_res_dir / "astrasim_sweep.json"
    # Also update topology_sweep.json so downstream PA tools (analysis, aggregate, plot, energy) work seamlessly
    out_sweep_json = out_res_dir / "topology_sweep.json"

    print(f"\n  ✓ {len(results)} topology records → {out_astrasim_json}"
          f"  ({_n_new_ok} new, {_n_skip} skipped, {_n_fail} failed)")
    print(f"  ✓ Integrated sweep results → {out_sweep_json}")
    slog.session_log(f"done: {len(results)} records "
                     f"({_n_new_ok} new, {_n_skip} skipped, {_n_fail} failed)")
    slog.finish("done", {"ok": _n_new_ok, "skipped": _n_skip,
                         "failed": _n_fail, "total": len(results)})


if __name__ == "__main__":
    main()

