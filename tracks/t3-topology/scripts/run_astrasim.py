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
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

HERE = Path(__file__).parent
TRACK = HERE.parent
CONFIGS_DIR = TRACK / "configs"
RESULTS_DIR = TRACK / "results"

from astrasim_adapter import prepare_astrasim_config_dir, parse_booksim_cfg
from generate_chakra_trace import ChakraTraceGenerator, save_chakra_trace


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
    # Replicated-trace guard: every rank runs the identical shared .et, so
    # pipeline stage transfers (absolute per-rank P2P src/dst, plus missing
    # RECV pairing) are un-routable in this design. PP>1 needs per-rank
    # sharded traces (future work); until then stages run inline (PP=1).
    if (spec.get("pp_degree", 1) or 1) > 1:
        print(f"  [warn] pp_degree={spec.get('pp_degree')} requested but the shared "
              "replicated trace cannot route P2P stage transfers; forcing PP=1.")
        spec = dict(spec)
        spec["pp_degree"] = 1
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
                            print(f"\n    | {cfg_path.stem}: {_line.rstrip()[:160]}", flush=True)
            finally:
                try:
                    stream.close()
                except OSError:
                    pass
        try:
            _run_log.write_text(f"$ {' '.join(cmd)}\n")
            _proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     stdin=subprocess.DEVNULL, text=True, bufsize=1)
            _t_out = _threading.Thread(target=_pump, args=(_proc.stdout, _out_lines, True), daemon=True)
            _t_err = _threading.Thread(target=_pump, args=(_proc.stderr, _err_lines, False), daemon=True)
            _t_out.start(); _t_err.start()
            _last_beat = _t0
            while True:
                _rc = _proc.poll()
                if _rc is not None:
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
                        f"timed out after {_timeout_s}s (elapsed {_fmt_elapsed(_now - _t0)})" + _tail)
                if _now - _last_beat >= 60:
                    print(f"    ... {cfg_path.stem} still running "
                          f"({_fmt_elapsed(_now - _t0)} elapsed, timeout {_fmt_elapsed(_timeout_s)})",
                          flush=True)
                    _last_beat = _now
                _done.wait(1.0)
                if _proc.poll() is not None:
                    break
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
        # No synthetic fallback: running plain booksim on the template cfg
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
        "workload": f"{spec.get('model_name', 'Model')} (TP={spec.get('tp_degree', 1)}, PP={spec.get('pp_degree', 1)})",
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
        "status": status,
    }


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
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    gen = ChakraTraceGenerator()
    model_key = args.model.lower()
    if model_key in ("all_reduce", "all_to_all", "reduce_scatter", "all_gather"):
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

    out_res_dir = RESULTS_DIR / args.config
    out_res_dir.mkdir(parents=True, exist_ok=True)

    configs = sorted(CONFIGS_DIR.glob("*.cfg"))

    if args.topo:
        configs = [c for c in configs if args.topo in c.stem]
        if not configs:
            raise ValueError(f"--topo '{args.topo}' matched no configs "
                             f"in {CONFIGS_DIR}")

    results = []
    import time as _wtime
    _sweep_t0 = _wtime.time()
    _elapsed_hist: list[float] = []

    def _fmt_dur(s: float) -> str:
        s = int(s)
        return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"

    print(f"=== ASTRA-Sim 2.0 + Chakra ET Workload Runner ===")
    print(f"  Model Workload : {spec.get('model_name', args.model)}")
    print(f"  Message Size   : {spec.get('msg_size_mb', 0.0):.1f} MB per collective call")
    print(f"  Parallelism    : TP={spec.get('tp_degree', 1)}, PP={spec.get('pp_degree', 1)}")
    print(f"  Total Layers   : {spec.get('num_layers', 1)}\n")
    print("  Mode           : single run per topology (embedded injection owns "
          "the rate dimension; the standalone-BookSim IR sweep does not apply)")
    print("  Topologies     :", [c.stem for c in configs])
    print()

    for _idx, cfg in enumerate(configs, 1):
        _topo_t0 = _wtime.time()
        if _elapsed_hist:
            _avg = sum(_elapsed_hist) / len(_elapsed_hist)
            _eta = _avg * (len(configs) - len(results))
            _eta_txt = f" | ETA ~{_fmt_dur(_eta)}"
        else:
            _eta_txt = ""
        print(f"  [{_idx}/{len(configs)}] Running {cfg.stem:<12} ...{_eta_txt}", flush=True)

        # One bad config (missing data file, binary crash) must not kill
        # the other runs. Failures are recorded as status=error with
        # the message — never fabricated, never silent.
        try:
            r = run_astrasim_topology(
                cfg,
                spec,
                args.config
            )
        except Exception as e:  # noqa: BLE001 - record, don't abort sweep
            r = {
                "topology": cfg.stem,
                "workload": f"{spec.get('model_name', 'Model')}",
                "total_nodes": None,
                "astrasim_cycles": None,
                "latency_cycles": None,
                "comm_overhead_pct": None,
                "injection_rate": 0.0,
                "hops_avg": None,
                "traffic": "astrasim(chakra_et)",
                "status": f"error: {type(e).__name__}: {e}",
            }

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
        _topo_elapsed = _wtime.time() - _topo_t0
        _elapsed_hist.append(_topo_elapsed)
        _n_ok = sum(1 for _r in results if _r.get("status") == "ok") + (1 if r.get("status") == "ok" else 0)
        print(f"  [{_idx}/{len(configs)}] {cfg.stem:<12} done in {_fmt_dur(_topo_elapsed)} "
              f"| {latency_text} | {cycles_text} | {r['status']} "
              f"(ok={_n_ok}/{_idx} | sweep {_fmt_dur(_wtime.time() - _sweep_t0)})", flush=True)
        results.append(r)
        # Incremental persistence: a slow/hung topology must not hold the
        # whole sweep's results hostage. The JSON on disk is always the
        # prefix completed so far; a later run overwrites with the full set.
        (out_res_dir / "astrasim_sweep.json").write_text(json.dumps(results, indent=2))
        (out_res_dir / "topology_sweep.json").write_text(json.dumps(results, indent=2))

    out_astrasim_json = out_res_dir / "astrasim_sweep.json"
    out_astrasim_json.write_text(json.dumps(results, indent=2))

    # Also update topology_sweep.json so downstream PA tools (analysis, aggregate, plot, energy) work seamlessly
    out_sweep_json = out_res_dir / "topology_sweep.json"
    out_sweep_json.write_text(json.dumps(results, indent=2))

    print(f"\n  ✓ {len(results)} topology records → {out_astrasim_json}")
    print(f"  ✓ Integrated sweep results → {out_sweep_json}")


if __name__ == "__main__":
    main()

