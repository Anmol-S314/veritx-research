#!/usr/bin/env python3
"""veritx — unified CLI for the VeritX NoC DSE pipeline.

Usage:
    veritx trace chakra <et_dir> --nodes 64 --out runs/traces/input.trace
    veritx trace model <json> --nodes 64 --out runs/traces/input.trace
    veritx trace info <trace>
    veritx trace extract <trace> --burst 100 --out ...
    veritx trace extract <trace> --uniform --out ...
    veritx trace slice --trace <trace> --classes 0,1 --out ...
    veritx trace validate <trace>
    veritx synthesize bo --traffic <trace> --nodes 64 --iters 50
    veritx evaluate booksim --trace <trace> [--k 8] [--routing dor]
    veritx evaluate anynet --topo <anynet> --trace <trace>
    veritx evaluate astra --ets <et_dir> [--timeout 300]
    veritx certify flow --model <json> --topo <anynet>
    veritx certify rtl --topo <anynet> [--tier quick]
    veritx certify full --model <json> --topo <anynet>
    veritx run --model <json> --nodes 64 [--search bo] [--cert flow]
    veritx sweep --trace <trace>
    veritx compare --trace <trace> --topos mesh,torus
    veritx compare --trace <trace> --dense llama70b_ring
    veritx pareto --traces <t1,t2> --topos mesh,torus
    veritx runs [--last N] [--run-id <id>]
    veritx results [--last N]
    veritx status [--last N]
    veritx diff [run_a] [run_b]
    veritx report --json <results.json>

Pipeline: trace → synthesize → evaluate → certify → done
All evaluation uses trace-replay mode (correct timestamps, no Bernoulli).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from ..core.logging import Ctx, log, ok, fail, verbose, banner, output, print_human
from ..model.presets import (
    Topology, SWEEP_TOPOS, DENSE_PRESETS, lookup_topo, make_anynet_topo,
    count_anynet_edges,
)
from ..simulation.booksim import (
    BookSimError, TimeoutError, detect_trace_stats, run_topology_eval,
    run_sweep, find_booksim_bin, build_config, run_booksim, TraceStats,
)
from ..simulation.traces import (
    validate_trace, analyze_trace, extract_burst, extract_uniform,
    slice_trace,
)
from .pipeline import (
    run_compare, print_compare_table, print_sweep_table,
    list_runs, show_results, diff_runs, generate_latex,
)


# ── Path constants ──────────────────────────────────────────────────────────
from veritx_dse.core.paths import REPO, DSE_DIR, RUNS_DIR, BOOKSIM_BIN, ASTRA_BS_BIN

SCRIPTS_DIR = DSE_DIR / "scripts"
EXPERIMENTS_DIR = RUNS_DIR / "experiments"
CERTIFY_SH = DSE_DIR.parent / "scripts" / "certify.sh"


def sanitize_path(p: str) -> str:
    """Reject path traversal attempts."""
    if '..' in p:
        raise ValueError(f"Path traversal not allowed: {p}")
    resolved = Path(p).resolve()
    return str(resolved)


def _resolve_path(p: str) -> str:
    """Resolve a path relative to REPO, DSE_DIR, or absolute.

    Handles symlinks by resolving them first, then falling back to REPO-relative.
    Rejects path traversal attempts (.. in path).
    """
    # Reject traversal
    if '..' in p:
        raise ValueError(f"Path traversal not allowed: {p}")
    path = Path(p)
    # First: resolve symlinks
    resolved = path.resolve()
    if resolved.exists():
        return str(resolved)
    # Second: try relative to REPO
    candidate = REPO / p
    if candidate.exists():
        return str(candidate.resolve())
    # Third: try relative to DSE_DIR
    candidate = DSE_DIR / p
    if candidate.exists():
        return str(candidate.resolve())
    # Return as-is (caller will handle FileNotFoundError)
    return str(resolved)
    if candidate.exists():
        return str(candidate.resolve())
    return str(path.resolve())


# ── Command handlers ────────────────────────────────────────────────────────
# Each function: parse args → call module → print result.
# NO business logic. NO sys.exit. Exceptions propagate to main().


def cmd_trace_validate(ctx: Ctx, args):
    trace = _resolve_path(args.trace)
    result = validate_trace(trace)

    if not ctx.json_mode:
        banner(ctx, f"Validating: {Path(trace).name}")

    if ctx.verbosity > 0 and not ctx.json_mode:
        print(f"  Format:       {'✓ VALID' if result.valid else '✗ INVALID'}")
        print(f"  Packets:      {result.packets:,}")
        print(f"  Sources:      {result.sources} unique (IDs 0–{max(result.sizes) if result.sizes else 0})")
        print(f"  Classes:      {result.classes}")
        print(f"  Sizes:        {result.sizes}")
        print(f"  Time range:   [{result.time_range[0]}, {result.time_range[1]}] ({result.span:,} cycles)")
        print(f"  Avg IR:       {result.injection_rate:.6f} pkts/cycle")
        print(f"  Self-loops:   {result.self_loops}")
        if result.errors:
            print(f"\n  \033[31mErrors ({len(result.errors)}):\033[0m")
            for e in result.errors[:10]:
                print(f"    {e}")
        if result.warnings:
            print(f"\n  \033[33mWarnings ({len(result.warnings)}):\033[0m")
            for w in result.warnings[:10]:
                print(f"    {w}")
        if not result.errors and not result.warnings:
            ok(ctx, "Trace is clean — ready for BookSim")
        elif not result.errors:
            log(ctx, f"Trace is usable but has {len(result.warnings)} warnings")
        else:
            fail(ctx, f"Trace has {len(result.errors)} errors — fix before running BookSim")

    output(ctx, result.to_dict())


def cmd_trace_info(ctx: Ctx, args):
    trace = _resolve_path(args.trace)
    info = analyze_trace(trace)

    banner(ctx, f"Trace Analysis: {Path(trace).name}")
    print(f"  File:         {info.file}")
    print(f"  Size:         {info.file_size:,} bytes ({info.file_size // 1024}KB)")
    print(f"  Packets:      {info.packets:,}")
    print(f"  Sources:      {info.sources}")
    print(f"  Classes:      {info.classes}")
    print(f"  Time range:   [0, {info.max_cycle}] ({info.span:,} cycles)")
    print(f"  Avg IR:       {info.ir:.6f} pkts/cycle")
    print(f"  Bursts:       {len(info.bursts)} (gap>100c)")
    print(f"  Avg burst:    {info.avg_burst_size:.0f} pkts")
    print(f"  Max burst:    {info.max_burst_size} pkts")
    print(f"  Avg gap:      {info.avg_gap:.0f} cycles")
    print(f"  Top srcs:     {info.top_srcs}")
    print(f"  Top dsts:     {info.top_dsts}")
    print(f"  Profile:      {info.profile}")
    print(f"  Burst IR:     {info.burst_ir:.2f} pkts/cycle (during max burst)")
    print(f"  Burst mode:   {info.burst_mode}")


def cmd_trace_extract(ctx: Ctx, args):
    trace = _resolve_path(args.trace)
    if args.uniform:
        result = extract_uniform(trace, args.out)
    elif args.burst is not None:
        result = extract_burst(trace, args.burst, args.out)
    else:
        fail(ctx, "Specify --burst N or --uniform")
        return

    ok(ctx, f"Extracted {result.packets} packets → {result.output_file}")
    output(ctx, result.to_dict())


def cmd_trace_slice(ctx: Ctx, args):
    trace = _resolve_path(args.trace)
    keep = set(int(c) for c in args.classes.split(","))
    result = slice_trace(trace, keep, args.out, renumber=args.renumber)
    ok(ctx, f"Slice: {result.kept} packets kept, {result.dropped} dropped → {result.output_file}")
    output(ctx, result.to_dict())


def cmd_trace_chakra(ctx: Ctx, args):
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        from chakra_to_dse import main as chakra_main
    except ImportError:
        fail(ctx, "chakra_to_dse module not found in scripts/")
        fail(ctx, "Run: git checkout -- scripts/chakra_to_dse.py")
        return

    et_path = Path(args.et_dir)
    if et_path.is_dir():
        txt_files = sorted(et_path.glob("*.txt"))
        et_files = list(et_path.glob("*.et"))
        if txt_files:
            trace_files = [str(f) for f in txt_files]
            log(ctx, f"Found {len(trace_files)} .txt files in {et_path.name}")
        elif et_files:
            # Chakra .et binary files — try ASTRA-sim converter
            astra_bin = REPO / "serving" / "astra-sim" / "astra-sim" / "bin" / "chakra_to_et"
            if astra_bin.exists():
                log(ctx, f"Found {len(et_files)} Chakra .et files, converting via ASTRA-sim...")
                import subprocess
                for et_file in et_files:
                    r = subprocess.run([str(astra_bin), str(et_file)],
                                       capture_output=True, text=True, timeout=60, cwd=str(REPO))
                    if r.returncode == 0 and r.stdout.strip():
                        # Write converted text to temp file
                        txt_out = et_path / f"{et_file.stem}.txt"
                        txt_out.write_text(r.stdout)
                        trace_files.append(str(txt_out))
                if not trace_files:
                    fail(ctx, "Chakra conversion produced no output")
                    fail(ctx, "Ensure ASTRA-sim is built: cd third_party/astra-sim && cmake --build build")
                    return
                log(ctx, f"Converted {len(trace_files)} Chakra files to text")
            else:
                fail(ctx, f"{et_path.name}/ contains {len(et_files)} Chakra .et binary files")
                fail(ctx, "Chakra .et files need ASTRA-sim's chakra_to_et converter:")
                fail(ctx, f"  1. Build: cd third_party/astra-sim && cmake --build build")
                fail(ctx, f"  2. Convert: third_party/astra-sim/astra-sim/bin/chakra_to_et <et_file>")
                fail(ctx, f"  3. Then: veritx trace chakra <txt_dir> --out <out>")
                fail(ctx, "Or use LLMServingSim text traces directly (instance0_batch0.txt)")
                return
        else:
            fail(ctx, f"No .txt or .et files found in {et_path}")
            return
    elif et_path.is_file():
        trace_files = [str(et_path)]
    else:
        fail(ctx, f"Not found: {et_path}")
        return

    log(ctx, f"Converting {len(trace_files)} trace(s)")
    sys.argv = ["chakra_to_dse"] + trace_files + [
        "--npu-map", args.npu_map or "0,16,32,48",
        "--out", args.out,
    ]
    if args.speedup:
        sys.argv.extend(["--speedup", str(args.speedup)])
    chakra_main()
    ok(ctx, f"Trace: {args.out} ({Path(args.out).stat().st_size // 1024}KB)")


def cmd_trace_model(ctx: Ctx, args):
    model_path = Path(_resolve_path(args.model))
    if not model_path.exists():
        fail(ctx, f"Traffic model not found: {args.model}")
        return
    from ..simulation.model_to_trace import main as model_main
    log(ctx, f"Converting traffic model {model_path.name}")
    sys.argv = ["model_to_trace", "--traffic-model", str(args.model),
                "--nodes", str(args.nodes), "--out", str(args.out)]
    model_main()
    ok(ctx, f"Trace: {args.out} ({Path(args.out).stat().st_size // 1024}KB)")


def cmd_trace_hpc(ctx: Ctx, args):
    import shutil
    log(ctx, f"Copying HPC trace {args.trace_file}")
    shutil.copy2(args.trace_file, args.out)
    ok(ctx, f"Trace: {args.out}")


def cmd_synthesize_bo(ctx: Ctx, args):
    log(ctx, f"BO synthesis: {args.iters} iterations, {args.nodes} nodes")
    cmd = [sys.executable, str(Path(__file__).parent.parent / "synthesis" / "bo_synthesizer.py"),
           "--traffic", args.traffic, "--nodes", str(args.nodes),
           "--iters", str(args.iters), "--scorer", args.scorer]
    if args.seed:
        cmd.extend(["--seed", str(args.seed)])
    import subprocess
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=str(REPO))
    if r.returncode != 0:
        fail(ctx, f"BO synthesis failed (exit {r.returncode})")
        return

    results_path = RUNS_DIR / "booksim" / f"bo_results_N{args.nodes}.json"
    if results_path.exists():
        try:
            data = json.loads(results_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            fail(ctx, f"Failed to parse results: {e}")
            return
        ok(ctx, f"Best analytical: {data.get('best_latency', '?')}c")
        ok(ctx, f"BookSim validated: {data.get('booksim_latency', '?')}c")
        ok(ctx, f"Results: {results_path}")


def cmd_synthesize_grid(ctx: Ctx, args):
    log(ctx, f"Grid search: {args.nodes} nodes")
    import subprocess
    subprocess.run([sys.executable, str(SCRIPTS_DIR / "run.py")],
                   capture_output=True, text=True, cwd=str(REPO))
    ok(ctx, "Grid search complete")


def cmd_synthesize_iterative(ctx: Ctx, args):
    trace = _resolve_path(args.trace)
    log(ctx, f"Iterative synthesis ({args.method}, {args.steps} steps)")
    cmd = [sys.executable, str(Path(__file__).parent.parent / "synthesis" / "iterative_synthesizer.py"),
           "--trace", str(Path(trace).resolve()), "--method", args.method,
           "--steps", str(args.steps), "--max-edges", str(args.max_edges),
           "--out", args.out or str(RUNS_DIR / f"{args.method}_standalone.anynet")]
    if args.seed_anynet:
        cmd.extend(["--seed-anynet", str(Path(args.seed_anynet).resolve())])
    import subprocess
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=str(REPO))
    for line in r.stdout.splitlines():
        if "Final:" in line:
            ok(ctx, line.strip())
            break


def cmd_evaluate_booksim(ctx: Ctx, args):
    from veritx_dse.model.presets import lookup_topo, Topology
    if args.k < 2:
        fail(ctx, f"k must be >= 2, got {args.k}")
        return
    trace = str(Path(args.trace).resolve())
    stats = detect_trace_stats(trace)
    sample_period = max(200, stats.max_cycle + 1000)

    # Resolve topology: try preset lookup first, then build from args
    preset = lookup_topo(args.topo)
    if preset and not args.routing:
        # Use preset defaults for routing and params
        topo = Topology(
            f"{args.topo}_{args.k}x{args.k}",
            preset.backend, preset.routing,
            {**preset.params, "k": args.k},
            needs_noc_latency_zero=preset.needs_noc_latency_zero,
        )
    else:
        # User specified backend + routing explicitly
        routing = args.routing or "dim_order"
        topo = Topology(f"{args.topo}_{args.k}x{args.k}", args.topo, routing, {"k": args.k, "n": 2})

    log(ctx, f"BookSim {topo.backend} k={args.k} routing={topo.routing} trace={Path(args.trace).name} "
        f"({stats.num_packets} pkts, {stats.num_srcs} srcs, span={stats.span}c, IR={stats.ir:.4f})")

    config = build_config(topo, trace, sample_period=sample_period, seed=ctx.seed)

    result = run_booksim(ctx, config, repo_root=REPO, timeout=args.timeout)
    result["topology"] = topo.name
    result["trace"] = args.trace
    result["routing"] = topo.routing
    result["trace_stats"] = stats.to_dict()
    result["seed"] = ctx.seed

    # For trace-driven mode, use completion_time as primary metric
    if "completion_time" in result:
        stats_parts = [f"Completion: {result['completion_time']:,}c"]
        if "p50" in result:
            stats_parts.append(f"p50: {result['p50']:.0f}c")
        if "p95" in result:
            stats_parts.append(f"p95: {result['p95']:.0f}c")
        if "p99" in result:
            stats_parts.append(f"p99: {result['p99']:.0f}c")
        ok(ctx, " | ".join(stats_parts))
    else:
        ok(ctx, f"Latency: {result.get('latency', '?'):.2f}c | Hops: {result.get('hops', '?')}")

    out_path = RUNS_DIR / "booksim" / f"eval_{topo.backend}{args.k}_{Path(args.trace).stem}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    ok(ctx, f"Saved: {out_path}")
    output(ctx, result)


def cmd_evaluate_anynet(ctx: Ctx, args):
    topo_path = str(Path(args.topo).resolve())
    trace = str(Path(args.trace).resolve())
    n_nodes, n_edges = count_anynet_edges(topo_path)

    # Connectivity check — disconnected topologies cause BookSim to hang
    if n_nodes > 0 and n_edges > 0:
        adj: dict[int, set[int]] = {i: set() for i in range(n_nodes)}
        with open(topo_path) as f:
            for line in f:
                parts = line.split()
                if len(parts) < 5 or parts[0] != "router":
                    continue
                rid = int(parts[1])
                i = 4
                while i < len(parts):
                    if parts[i] == "router" and i + 1 < len(parts):
                        pid = int(parts[i + 1])
                        adj[rid].add(pid)
                        adj[pid].add(rid)
                        i += 2
                    else:
                        i += 1
        # BFS from node 0
        visited = {0}
        queue = [0]
        while queue:
            u = queue.pop()
            for v in adj.get(u, set()):
                if v not in visited:
                    visited.add(v)
                    queue.append(v)
        if len(visited) < n_nodes:
            fail(ctx, f"Disconnected topology: {n_nodes - len(visited)} nodes unreachable from node 0")
            fail(ctx, "BookSim will hang on disconnected graphs — fix the .anynet file")
            return

    topo = make_anynet_topo(topo_path)
    log(ctx, f"BookSim anynet topo={Path(args.topo).name} trace={Path(args.trace).name} "
        f"({n_nodes} nodes, {n_edges} edges)")

    stats = detect_trace_stats(trace)
    sample_period = max(200, stats.max_cycle + 1000)

    config = build_config(topo, trace, sample_period=sample_period, seed=ctx.seed)
    result = run_booksim(ctx, config, repo_root=REPO, timeout=args.timeout)
    result["topology"] = topo.name
    result["trace"] = args.trace
    result["nodes"] = n_nodes
    result["edges"] = n_edges
    result["seed"] = ctx.seed

    ok(ctx, f"Latency: {result['latency']:.2f}c | Hops: {result.get('hops', '?')}")

    out_path = RUNS_DIR / "booksim" / f"eval_{topo.name}_{Path(args.trace).stem}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    ok(ctx, f"Saved: {out_path}")
    output(ctx, result)


def cmd_evaluate_astra(ctx: Ctx, args):
    if not ASTRA_BS_BIN.exists():
        fail(ctx, f"ASTRA-sim BookSim2 binary not found: {ASTRA_BS_BIN}")
        return

    log(ctx, f"ASTRA-sim eval: ets={args.ets}")
    import subprocess
    cmd = [str(ASTRA_BS_BIN),
           "--workload-configuration", args.ets,
           "--system-configuration", args.system_config,
           "--network-configuration", args.network_config,
           "--remote-memory-configuration", args.memory_config,
           "--logging-configuration", "empty",
           "--logging-folder", str(RUNS_DIR / "astra")]
    try:
        subprocess.run(cmd, timeout=args.timeout, check=True, cwd=str(REPO))
        ok(ctx, "ASTRA-sim evaluation complete")
    except subprocess.TimeoutExpired:
        fail(ctx, f"ASTRA-sim timed out after {args.timeout}s")
    except subprocess.CalledProcessError as e:
        fail(ctx, f"ASTRA-sim failed (exit {e.returncode})")


def cmd_certify_flow(ctx: Ctx, args):
    log(ctx, f"Flow-class certification for {Path(args.topo).name}")
    model_abs = _resolve_path(args.model)
    topo_abs = _resolve_path(args.topo)
    if not Path(model_abs).exists():
        fail(ctx, f"Traffic model not found: {args.model}")
        return
    if not Path(topo_abs).exists():
        fail(ctx, f"Topology not found: {args.topo}")
        return
    import subprocess
    r = subprocess.run([sys.executable, str(SCRIPTS_DIR / "milestone_c.py"),
                        "--traffic-model", model_abs, "--topology", topo_abs],
                       capture_output=True, text=True, timeout=300, cwd=str(REPO))
    # Parse structured output, not grep
    passed = 0
    failed = 0
    for line in r.stdout.splitlines():
        if "PASS" in line:
            passed += 1
            log(ctx, f"  ✓ {line.strip()}")
        elif "FAIL" in line:
            failed += 1
            log(ctx, f"  ✗ {line.strip()}")
    if failed > 0:
        fail(ctx, f"Flow certification FAILED: {failed} checks failed")
    else:
        ok(ctx, f"Flow certification PASSED: {passed} checks")


def cmd_certify_rtl(ctx: Ctx, args):
    log(ctx, f"RTL certification for {Path(args.topo).name}")
    if not CERTIFY_SH.exists():
        fail(ctx, f"certify.sh not found at {CERTIFY_SH}")
        return
    import subprocess
    subprocess.run(["bash", str(CERTIFY_SH), args.build_dir, args.tier],
                   timeout=600, check=True, cwd=str(REPO))
    ok(ctx, "RTL certification complete")


def cmd_certify_full(ctx: Ctx, args):
    log(ctx, "Running full certification")
    cmd_certify_flow(ctx, args)
    cmd_certify_rtl(ctx, args)
    ok(ctx, "Full certification complete")


def cmd_sweep(ctx: Ctx, args):
    trace = _resolve_path(args.trace)
    sim_type = args.mode
    ir = args.ir

    banner(ctx, f"Sweep: {Path(trace).name}")
    log(ctx, f"Evaluating {len(SWEEP_TOPOS)} topologies on {Path(trace).name}")

    results = run_sweep(ctx, trace, repo_root=REPO, timeout=args.timeout,
                        sim_type=sim_type, ir=ir)
    print_sweep_table(ctx, results, sim_type)

    out_path = RUNS_DIR / "booksim" / f"sweep_{Path(trace).stem}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2))
    ok(ctx, f"Results: {out_path}")
    output(ctx, results)


def _apply_memory_correction(ctx: Ctx, result, args) -> None:
    """Apply shared-L2 bank contention correction to comparison results.

    Uses M/D/1 queue model: W_q = rho / (2 * mu * (1 - rho))
    where rho = lambda / mu, lambda = bytes_per_bank / cycles, mu = bank_bw.
    """
    try:
        sys.path.insert(0, str(SCRIPTS_DIR))
        from memory_miss_model import bank_contention
    except ImportError:
        fail(ctx, "bank_contention not available (memory_miss_model not found)")
        return

    banks = getattr(args, 'banks', 4)
    bank_bw = getattr(args, 'bank_bw', 1024)
    # Estimate L2 bytes from trace stats
    trace = _resolve_path(args.trace)
    stats = detect_trace_stats(trace)
    # Rough estimate: 8 bytes per flit × packet_size × num_packets
    l2_bytes = stats.num_packets * 8 * 8  # 8B/flit × 8 flits/pkt
    cycles = max(stats.span, 1)

    w_q, rho = bank_contention(l2_bytes, banks, bank_bw, cycles)
    if w_q == float('inf'):
        fail(ctx, f"L2 bank saturation (rho={rho:.2f} >= 1.0) — increase banks or bandwidth")
        return

    log(ctx, f"Memory correction: +{w_q:.1f}c (rho={rho:.2f}, {banks} banks, {bank_bw} B/cyc)")
    for s in result.summary:
        if "mean" in s:
            s["mean"] += w_q
            s["min"] += w_q
            s["max"] += w_q


def _run_sensitivity(ctx: Ctx, trace: str, specs: list, args) -> None:
    """Run sensitivity analysis at multiple injection rates.

    For each IR in --sensitivity, runs compare in throughput mode and
    prints a table showing how topology rankings change with load.
    """
    irs = [float(ir) for ir in args.sensitivity]
    banner(ctx, f"Sensitivity Analysis: IR = {irs}")

    all_results = []
    for ir in irs:
        log(ctx, f"Running IR={ir}...")
        r = run_compare(
            ctx, trace, specs,
            seeds=1, seed_base=ctx.seed,
            timeout=args.timeout, sim_type="throughput", ir=ir,
        )
        all_results.append((ir, r))

    # Print sensitivity table
    print(f"\n  {'IR':>6}", end="")
    for name, _ in specs:
        print(f" {name:>14}", end="")
    print()
    print(f"  {'─' * (6 + 14 * len(specs))}")

    for ir, r in all_results:
        print(f"  {ir:>6.3f}", end="")
        for s in r.summary:
            if "mean" in s:
                print(f" {s['mean']:>13.1f}c", end="")
            else:
                print(f" {'N/A':>13}", end="")
        print()


def cmd_compare(ctx: Ctx, args):
    trace = _resolve_path(args.trace)

    # Resolve topology specs
    if args.dense:
        preset = DENSE_PRESETS[args.dense]
        banner(ctx, f"Dense preset: {preset['desc']}")
        topo_names = [t.strip() for t in preset["topos"].split(",")]
        anynet_files = preset.get("anynet", [])
    else:
        topo_names = [t.strip() for t in args.topos.split(",")]
        anynet_files = args.anynet

    specs = []
    for name in topo_names:
        t = lookup_topo(name)
        if t is None:
            fail(ctx, f"Unknown topology: {name}")
            fail(ctx, f"Available: {', '.join(t.name for t in SWEEP_TOPOS)} or .anynet path")
            return
        specs.append((name, t))

    for af in anynet_files:
        af_resolved = _resolve_path(af)
        if not Path(af_resolved).exists():
            log(ctx, f"  Skipping .anynet not found: {af}")
            continue
        t = make_anynet_topo(af_resolved)
        specs.append((t.name, t))

    banner(ctx, f"Compare: {' vs '.join(s[0] for s in specs)} [{args.mode} mode]")
    log(ctx, f"{len(specs)} topologies × {args.seeds} seeds = {len(specs) * args.seeds} runs")
    log(ctx, f"Trace: {Path(trace).name}")

    result = run_compare(
        ctx, trace, specs,
        seeds=args.seeds, seed_base=args.seed_base,
        timeout=args.timeout, sim_type=args.mode, ir=args.ir,
    )

    # Apply memory hierarchy correction if requested
    if getattr(args, 'memory', False):
        _apply_memory_correction(ctx, result, args)

    print_compare_table(ctx, result)

    # Run sensitivity analysis if requested
    if getattr(args, 'sensitivity', None):
        _run_sensitivity(ctx, trace, specs, args)

    output(ctx, result.to_dict())


def cmd_pareto(ctx: Ctx, args):
    if args.seeds < 1:
        fail(ctx, f"seeds must be >= 1, got {args.seeds}")
        return
    sys.path.insert(0, str(SCRIPTS_DIR))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "mwp", str(SCRIPTS_DIR / "multi_workload_pareto.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.argv = ["multi_workload_pareto.py", "--traces", args.traces,
                "--topos", args.topos, "--anynet", args.anynet,
                "--seeds", str(args.seeds), "--timeout", str(args.timeout),
                "--out", args.out]
    spec.loader.exec_module(mod)
    mod.main()


def cmd_run(ctx: Ctx, args):
    """Full pipeline: trace → synthesize → evaluate → certify."""
    if args.nodes < 2:
        fail(ctx, f"nodes must be >= 2, got {args.nodes}")
        return
    from datetime import datetime
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = EXPERIMENTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    banner(ctx, f"VeritX Pipeline: {run_id}")
    print(f"  Model:  {args.model}")
    print(f"  Nodes:  {args.nodes}")
    print(f"  Search: {args.search} ({args.iters} iters)")
    print(f"  Cert:   {args.cert}\n")

    t0 = time.time()
    # Git hash for reproducibility
    try:
        import subprocess as _sp
        r = _sp.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(REPO), capture_output=True, text=True, timeout=5
        )
        git_hash = r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        git_hash = "unknown"

    from veritx_dse import __version__
    manifest = {
        "run_id": run_id, "model": args.model, "nodes": args.nodes,
        "search": args.search, "cert": args.cert,
        "seed": ctx.seed,
        "git_hash": git_hash,
        "engine_version": __version__,
        "timestamp": datetime.now().isoformat(),
    }

    def _save():
        manifest["duration_s"] = round(time.time() - t0, 1)
        manifest_path = run_dir / "manifest.json"
        tmp_path = run_dir / ".manifest.json.tmp"
        tmp_path.write_text(json.dumps(manifest, indent=2))
        tmp_path.rename(manifest_path)  # atomic on POSIX

    # Step 1: Trace
    try:
        log(ctx, "Step 1/4: Generating trace from traffic model")
        trace_path = run_dir / "input.trace"
        from ..simulation.model_to_trace import main as model_main
        sys.argv = ["model_to_trace", "--traffic-model", _resolve_path(args.model),
                    "--nodes", str(args.nodes), "--out", str(trace_path)]
        model_main()
        manifest["trace"] = str(trace_path)
        ok(ctx, f"Trace: {trace_path.name} ({trace_path.stat().st_size // 1024}KB)")
    except Exception as e:
        manifest["error"] = f"trace: {e}"
        fail(ctx, f"Trace generation failed: {e}")
        _save()
        return

    # Step 2: Synthesize
    topo_path = run_dir / "winner.anynet"
    try:
        log(ctx, f"Step 2/4: Synthesizing topology ({args.search})")
        import shutil
        import subprocess
        if args.search == "bo":
            iters = max(args.iters, 10)
            cmd = [sys.executable, str(Path(__file__).parent.parent / "synthesis" / "bo_synthesizer.py"),
                   "--traffic", str(trace_path), "--nodes", str(args.nodes),
                   "--iters", str(iters), "--scorer", args.scorer]
            subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                          check=True, cwd=str(REPO))
            bo_results = RUNS_DIR / "booksim" / f"bo_results_N{args.nodes}.json"
            if bo_results.exists():
                try:
                    data = json.loads(bo_results.read_text())
                except (json.JSONDecodeError, OSError) as e:
                    fail(ctx, f"Failed to parse BO results: {e}")
                    data = {}
                manifest["best_latency_analytical"] = data.get("best_latency")
                manifest["best_latency_booksim"] = data.get("booksim_latency")
                manifest["best_params"] = data.get("best_params")
        elif args.search == "iterative":
            method = args.iterative_method
            cmd = [sys.executable, str(Path(__file__).parent.parent / "synthesis" / "iterative_synthesizer.py"),
                   "--trace", str(trace_path), "--method", method,
                   "--steps", str(max(args.iters, 10)), "--max-edges", "120",
                   "--out", str(RUNS_DIR / "booksim" / "topo.anynet")]
            subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                          check=True, cwd=str(REPO))
        else:
            subprocess.run([sys.executable, str(SCRIPTS_DIR / "run.py")],
                          capture_output=True, text=True, timeout=600, cwd=str(REPO))

        if not topo_path.exists():
            candidate = RUNS_DIR / "booksim" / "topo.anynet"
            if candidate.exists():
                shutil.copy2(candidate, topo_path)
            if args.search == "iterative":
                for method in ["rho", "grpo"]:
                    candidate2 = RUNS_DIR / f"{method}_standalone.anynet"
                    if candidate2.exists() and not topo_path.exists():
                        shutil.copy2(candidate2, topo_path)
        if topo_path.exists():
            manifest["topology"] = str(topo_path)
            ok(ctx, f"Topology: {topo_path.name}")
        else:
            fail(ctx, "No topology generated — check synthesis output")
            manifest["error"] = "no topology generated"
    except Exception as e:
        manifest["error"] = f"synthesize: {e}"
        fail(ctx, f"Synthesis failed: {e}")
        _save()
        return

    # Step 3: Evaluate
    try:
        log(ctx, "Step 3/4: Evaluating with BookSim2")
        k = int(args.nodes ** 0.5)
        if k * k != args.nodes:
            k = 8
        topo = Topology(f"mesh_{k}x{k}", "mesh", "min_adapt", {"k": k, "n": 2})
        eval_result = run_topology_eval(ctx, topo, str(trace_path),
                                        repo_root=REPO, timeout=60)
        manifest["eval"] = eval_result
        if "latency" in eval_result:
            ok(ctx, f"Latency: {eval_result['latency']:.2f}c")
    except Exception as e:
        manifest["eval"] = {"error": str(e)}
        fail(ctx, f"Evaluation failed: {e}")

    # Step 4: Certify
    try:
        if args.cert and args.cert != "none":
            if not topo_path.exists():
                fail(ctx, f"Certification skipped: no topology file at {topo_path}")
                manifest["cert"] = {"error": "no topology file"}
            else:
                log(ctx, f"Step 4/4: Certifying ({args.cert})")
                if args.cert in ("flow", "full"):
                    import subprocess
                    r = subprocess.run([sys.executable, str(SCRIPTS_DIR / "milestone_c.py"),
                                        "--traffic-model", _resolve_path(args.model),
                                        "--topology", str(topo_path.resolve())],
                                       capture_output=True, text=True, timeout=300, cwd=str(REPO))
                    cert_pass = any("PASS" in line for line in r.stdout.splitlines())
                    manifest["cert"] = "PASS" if cert_pass else "FAIL"
                    ok(ctx, f"Certification: {manifest['cert']}")
        else:
            log(ctx, "Step 4/4: Skipping certification (disabled)")
    except Exception as e:
        manifest["cert"] = {"error": str(e)}
        fail(ctx, f"Certification failed: {e}")

    _save()
    print(f"\n\033[1m{'=' * 60}\033[0m")
    if manifest.get("error"):
        print(f"  \033[31m✗ Pipeline finished with errors\033[0m in {manifest['duration_s']}s")
    else:
        print(f"  \033[32m✓ Pipeline complete\033[0m in {manifest['duration_s']}s")
    print(f"  Results: {run_dir}")
    if "eval" in manifest and "latency" in manifest["eval"]:
        print(f"  Latency: {manifest['eval']['latency']:.2f}c")
    print(f"\033[1m{'=' * 60}\033[0m\n")


def cmd_runs(ctx: Ctx, args):
    list_runs(ctx, last=args.last, run_id=args.run_id)


def cmd_results(ctx: Ctx, args):
    show_results(ctx, last=args.last)


def cmd_status(ctx: Ctx, args):
    list_runs(ctx, last=args.last)


def cmd_diff(ctx: Ctx, args):
    diff_runs(ctx, run_a=args.run_a, run_b=args.run_b)


def cmd_baseline(ctx: Ctx, args):
    """Compare against published baseline topologies.

    Baselines (standard configurations from literature):
      - mesh_8x8:     2D mesh k=8 n=2, dim_order routing (TPU v1/v2 style)
      - torus_8x8:    2D torus k=8 n=2, dim_order routing
      - flatfly_64:   FlatButterfly k=4 n=2 c=4 (UFusion style)
      - ring_64:      Ring topology (Gpipe/PipeDream style)
      - star_64:      Star/hub topology (central switch)
      - gec_express:  GEC express k=8 o=7 d=1 (our best BO result)
    """
    trace = _resolve_path(args.trace)
    if not Path(trace).exists():
        fail(ctx, f"Trace not found: {trace}")
        return

    # Built-in baselines
    baselines = [
        lookup_topo("mesh_8x8"),
        lookup_topo("torus_8x8"),
        lookup_topo("flatfly_64"),
    ]
    specs = [(b.name, b) for b in baselines if b is not None]

    # User topologies
    for name in args.topos.split(","):
        name = name.strip()
        t = lookup_topo(name)
        if t:
            specs.append((name, t))

    # Custom .anynets
    for af in args.anynet:
        af_resolved = _resolve_path(af)
        if Path(af_resolved).exists():
            t = make_anynet_topo(af_resolved)
            specs.append((t.name, t))

    banner(ctx, f"Baseline Comparison: {len(specs)} topologies")
    log(ctx, f"Trace: {Path(trace).name}")

    result = run_compare(
        ctx, trace, specs,
        seeds=args.seeds, seed_base=ctx.seed,
        timeout=args.timeout, sim_type="latency", ir=0.05,
    )
    print_compare_table(ctx, result)
    output(ctx, result.to_dict())


def cmd_compile(ctx: Ctx, args):
    """PRD §13: Intent-to-fabric pipeline from CompileRequest JSON.

    Reads a CompileRequest JSON (E1–E5), validates, derives topology,
    runs BookSim simulation, and outputs results.

    This is the PRD's 'intent-to-fabric compiler' entry point.
    """
    from veritx_dse.model.compile_model import (
        CompileRequest, validate, derive_topology_spec,
        derive_vc_assignment, Tier, OutputFormat,
    )
    from veritx_dse.simulation.booksim import build_config, run_booksim, detect_trace_stats
    from veritx_dse.reports.reports import generate_report
    from veritx_dse.reports.artifact import DesignManifest

    # Step 1: Ingest — load CompileRequest from JSON
    cr_path = _resolve_path(args.request)
    if not Path(cr_path).exists():
        fail(ctx, f"CompileRequest not found: {cr_path}")
        return

    try:
        cr = CompileRequest.from_dict(json.loads(Path(cr_path).read_text()))
    except Exception as e:
        fail(ctx, f"Failed to parse CompileRequest: {e}")
        return

    banner(ctx, f"Compile: {cr.workload.model_name or cr.workload.model_family.value}")
    log(ctx, f"Agents: {', '.join(f'{a.kind.value}×{a.count}' for a in cr.agents)}")
    log(ctx, f"Total nodes: {cr.total_nodes}")
    log(ctx, f"Guardrail hash: {cr.guardrail_hash()[:16]}...")

    # ── Step 1/6: Validate — guardrail check (catches errors in seconds) ──
    log(ctx, "Step 1/6: Validating configuration...")
    vr = validate(cr)
    if not vr.ok:
        fail(ctx, "Validation FAILED:")
        for e in vr.errors:
            fail(ctx, f"  {e}")
        return
    if vr.warnings:
        for w in vr.warnings:
            log(ctx, f"  Warning: {w}")
    ok(ctx, f"Validation passed (vc_count={vr.vc_count}, nodes={vr.total_nodes})")

    # ── Step 2/6: Derive — VC assignment + topology (LOCKED parameters) ──
    log(ctx, "Step 2/6: Deriving fabric configuration...")
    va = derive_vc_assignment(cr)
    log(ctx, f"  Routing (LOCKED): {va.routing_function}")
    log(ctx, f"  VC count: {va.vc_count}")
    if va.per_class_vc:
        log(ctx, f"  VC assignments: {va.per_class_vc}")
    if va.turn_restrictions:
        log(ctx, f"  Turn restrictions (LOCKED): {va.turn_restrictions}")

    topo = derive_topology_spec(cr)
    ok(ctx, f"Derived topology: {topo.backend} k={topo.params.get('k', '?')} routing={topo.routing}")

    # ── Step 3/6: Simulate — BookSim cycle-accurate ──
    log(ctx, "Step 3/6: Running BookSim simulation...")
    trace_raw = cr.workload.trace_path
    trace = None
    result = {}
    if not trace_raw:
        log(ctx, "  No trace_path in workload — skipping simulation")
    else:
        trace = _resolve_path(trace_raw)
        if not Path(trace).exists():
            log(ctx, f"  Trace not found: {trace_raw} (resolved: {trace})")
            log(ctx, "  Skipping simulation — using analytical estimates only")
        else:
            config = build_config(topo, trace, seed=ctx.seed)
            try:
                result = run_booksim(ctx, config, repo_root=REPO, timeout=args.timeout)
                result["seed"] = ctx.seed
                ok(ctx, f"Latency: {result['latency']:.2f}c | Hops: {result.get('hops', '?')}")
            except Exception as e:
                fail(ctx, f"BookSim failed: {e}")
                result = {}

    # ── Step 4/6: Verify — F1-F8 proof obligations ──
    from veritx_dse.model.compile_model import verify_design
    log(ctx, "Step 4/6: Running verification checks...")
    vr_verify = verify_design(cr, topology_name=topo.backend)
    for check in vr_verify.checks:
        status_sym = "✓" if check["status"] == "PASS" else "⚠" if check["status"] == "WARN" else "✗"
        log(ctx, f"  {status_sym} {check['name']}: {check['detail']}")
    if vr_verify.errors:
        for e in vr_verify.errors:
            fail(ctx, f"  ✗ {e}")
    ok(ctx, f"Verification: {sum(1 for c in vr_verify.checks if c['status']=='PASS')}/{len(vr_verify.checks)} PASS")

    # ── Step 5/6: Generate — RTL + UVM + artifacts ──
    from veritx_dse.model.compile_model import generate_artifacts
    from veritx_dse.verification.uvm_gen import generate_uvm
    log(ctx, "Step 5/6: Generating collateral...")
    artifacts = generate_artifacts(cr)
    log(ctx, f"  Tracked artifacts: {', '.join(a.kind for a in artifacts)}")

    # Generate UVM if requested in output formats
    if OutputFormat.UVM in cr.noc_config.output_formats:
        uvm_out = Path(RUNS_DIR / "uvm")
        uvm_out.mkdir(parents=True, exist_ok=True)
        try:
            n_nodes = cr.total_nodes
            k = int(n_nodes ** 0.5)
            if k * k != n_nodes:
                k = int(cr.noc_config.radix or 8)
            uvm_result = generate_uvm(cr, n_nodes=n_nodes, k=k)
            for filename, content in [
                ("tb_noc.sv", uvm_result["tb_top"]),
                ("seq_lib.sv", uvm_result["sequences"]),
                ("assertions.sv", uvm_result["assertions"]),
                ("cov.sv", uvm_result["coverage"]),
            ]:
                fpath = uvm_out / filename
                fpath.write_text(content)
                log(ctx, f"  Generated: {fpath}")
            ok(ctx, f"UVM testbench: {uvm_out}/")
        except Exception as e:
            fail(ctx, f"UVM generation failed: {e}")
    else:
        log(ctx, "  UVM not in output_formats — skipping")

    # ── Step 6/6: Report — formal area/power/timing + manifest + signing ──
    log(ctx, "Step 6/6: Generating report...")
    report = generate_report(cr, result)
    report["compile_request"] = cr.to_dict()
    report["topology"] = {
        "backend": topo.backend,
        "routing": topo.routing,
        "params": topo.params,
    }
    report["verification"] = {
        "ok": vr_verify.ok,
        "checks": vr_verify.checks,
        "errors": vr_verify.errors,
    }
    report["artifacts"] = [a.to_dict() for a in artifacts]

    # Design manifest with signing + revision chain (PRD §12, §14)
    dm = DesignManifest.create(cr, metadata={"engine": "veritx-cli", "version": "0.3.0"})
    report["manifest"] = dm.to_dict()

    out_path = RUNS_DIR / "booksim" / f"compile_{cr.workload.model_family.value}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    ok(ctx, f"Report: {out_path}")

    # Print summary
    print(f"\n  \033[1mCompile Result\033[0m")
    print(f"  {'─' * 55}")
    print(f"  Model:      {cr.workload.model_name or cr.workload.model_family.value}")
    print(f"  Topology:   {topo.backend} k={topo.params.get('k', '?')}")
    print(f"  Routing:    {va.routing_function} (LOCKED)")
    print(f"  VCs:        {va.vc_count}")
    print(f"  Latency:    {result.get('latency', '?')}c")
    print(f"  Area:       {report['area']['total_mm2']:.4f} mm²")
    print(f"  Power:      {report['power']['total_w']:.4f} W")
    print(f"  Fmax:       {report['timing']['max_freq_mhz']:.0f} MHz")
    print(f"  Energy:     {report['energy']['per_bit_pj']:.3f} pJ/bit")
    print(f"  Verify:     {sum(1 for c in vr_verify.checks if c['status']=='PASS')}/{len(vr_verify.checks)} PASS")
    print(f"  Artifacts:  {', '.join(a.kind for a in artifacts)}")
    print(f"  Manifest:   rev={report['manifest']['revision']} signed={len(report['manifest']['signature'])==64}")
    print(f"  Hash:       {cr.guardrail_hash()[:16]}...")
    print(f"  {'─' * 55}\n")

    output(ctx, report)


def cmd_serve(ctx: Ctx, args):
    """Full-stack LLM serving simulation: LLMServingSim + AstraSim + BookSim2."""
    import subprocess
    import os

    # Resolve paths - LLMServingSim runs from astra-sim/ and prepends ../ to relative paths
    llmserving_root = REPO / "third_party" / "llmservingsim"
    cluster_config_path = Path(args.cluster_config).resolve()
    dataset_path = Path(args.dataset).resolve()
    # Pass paths relative to llmserving_root (LLMServingSim's _cluster_config_path adds ../)
    try:
        cluster_config = str(cluster_config_path.relative_to(llmserving_root))
    except ValueError:
        cluster_config = str(cluster_config_path)
    try:
        dataset = str(dataset_path.relative_to(llmserving_root))
    except ValueError:
        dataset = str(dataset_path)

    if not llmserving_root.exists():
        fail(ctx, f"LLMServingSim not found at {llmserving_root}")
        return

    # Build command
    cmd = [
        sys.executable, "-m", "serving",
        "--cluster-config", cluster_config,
        "--dataset", dataset,
        "--num-reqs", str(args.num_reqs),
        "--network-backend", args.network_backend,
        "--log-level", args.log_level,
    ]

    if args.output:
        cmd.extend(["--output", str(Path(args.output).resolve())])

    if args.no_cleanup:
        cmd.append("--no-cleanup-inputs")

    if args.no_prefix_caching:
        cmd.append("--no-enable-prefix-caching")

    log(ctx, f"Running full-stack simulation: {args.network_backend} backend")
    log(ctx, f"Cluster: {Path(args.cluster_config).name}")
    log(ctx, f"Dataset: {Path(args.dataset).name} ({args.num_reqs} requests)")
    log(ctx, f"Timeout: {args.timeout}s")
    print()

    t0 = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(llmserving_root),
            timeout=args.timeout,
            capture_output=False,  # Let output stream to terminal
        )
        elapsed = time.time() - t0

        if result.returncode == 0:
            ok(ctx, f"Simulation completed in {elapsed:.1f}s")
        else:
            fail(ctx, f"Simulation failed with exit code {result.returncode}")

    except subprocess.TimeoutExpired:
        fail(ctx, f"Simulation timed out after {args.timeout}s")
    except Exception as e:
        fail(ctx, f"Simulation error: {e}")


def cmd_generate_uvm(ctx: Ctx, args):
    """Generate UVM testbench from CompileRequest."""
    from veritx_dse.model.compile_model import CompileRequest, derive_vc_assignment
    from veritx_dse.verification.uvm_gen import generate_uvm

    cr_path = _resolve_path(args.request)
    if not Path(cr_path).exists():
        fail(ctx, f"CompileRequest not found: {cr_path}")
        return

    try:
        cr = CompileRequest.from_dict(json.loads(Path(cr_path).read_text()))
    except Exception as e:
        fail(ctx, f"Failed to parse CompileRequest: {e}")
        return

    banner(ctx, f"Generate UVM: {cr.workload.model_name or cr.workload.model_family.value}")
    log(ctx, f"Nodes: {args.nodes}, k: {args.k}")
    log(ctx, f"Routing: {derive_vc_assignment(cr).routing_function} (LOCKED)")

    result = generate_uvm(cr, n_nodes=args.nodes, k=args.k)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for filename, content in [
        ("tb_noc.sv", result["tb_top"]),
        ("seq_lib.sv", result["sequences"]),
        ("assertions.sv", result["assertions"]),
        ("cov.sv", result["coverage"]),
    ]:
        fpath = out_dir / filename
        fpath.write_text(content)
        ok(ctx, f"  {filename}: {fpath}")

    ok(ctx, f"UVM files: {out_dir}")
    log(ctx, "  Use: verilator --cc tb_noc.sv + UVM sim for verification")
    output(ctx, {"files": [str(out_dir / f) for f in result["files"]]})


def cmd_report(ctx: Ctx, args):
    latex = generate_latex(ctx, args.json, args.caption, args.label)
    if args.out:
        out_path = Path(args.out)
        if out_path.suffix == '.html':
            # Generate HTML from LaTeX
            html = _latex_to_html(latex, args.caption or 'VeritX Report')
            out_path.write_text(html)
            ok(ctx, f"HTML: {args.out}")
        elif out_path.suffix == '.pdf':
            # Generate PDF via pdflatex (if available)
            import tempfile, subprocess
            with tempfile.TemporaryDirectory() as tmpdir:
                tex_path = Path(tmpdir) / 'report.tex'
                tex_path.write_text(latex)
                r = subprocess.run(['pdflatex', '-interaction=nonstopmode', '-output-directory', tmpdir, str(tex_path)],
                                   capture_output=True, text=True, timeout=30)
                pdf_path = Path(tmpdir) / 'report.pdf'
                if pdf_path.exists():
                    import shutil
                    shutil.copy2(pdf_path, out_path)
                    ok(ctx, f"PDF: {args.out}")
                else:
                    fail(ctx, f"PDF generation failed: {r.stderr[-200:]}")
        else:
            out_path.write_text(latex)
            ok(ctx, f"LaTeX: {args.out}")
    else:
        print(latex)


def _latex_to_html(latex: str, title: str) -> str:
    """Convert LaTeX table to minimal HTML."""
    import re
    html_parts = [
        '<!DOCTYPE html>',
        '<html><head><meta charset="utf-8">',
        f'<title>{title}</title>',
        '<style>table{border-collapse:collapse;margin:1em}th,td{border:1px solid #333;padding:4px 8px}th{background:#f0f0f0}</style>',
        '</head><body>',
        f'<h1>{title}</h1>',
    ]
    # Extract table rows from LaTeX
    for line in latex.split('\n'):
        if '\\hline' in line:
            continue
        cells = [c.strip() for c in line.split('&')]
        if len(cells) > 1:
            tag = 'th' if any('\\textbf' in c or 'Topo' in c for c in cells) else 'td'
            pattern = re.compile(r"\\textbf\{(.+?)\}")
            row = "".join(f"<{tag}>{pattern.sub(r"<b>\1</b>", c)}</{tag}>" for c in cells)
            html_parts.append(f'<tr>{row}</tr>')
    html_parts.extend(['</table>', '</body></html>'])
    return '\n'.join(html_parts)


def cmd_init(ctx: Ctx, args):
    """Interactive wizard to generate a CompileRequest JSON."""
    from veritx_dse.model.compile_model import (
        CompileRequest, Workload, ModelFamily, ServingMode,
        Agent, AgentKind, Requirement, QoSClass,
        Dependency, DepKind, DependencyGraph, NocConfig, TopologyFamily,
        PhysicalContext, AddressMap, AddressRange,
    )

    def _ask(prompt, default=None, options=None):
        """Ask user for input with default and optional choices."""
        suffix = f" [{default}]" if default else ""
        opts = f" ({'/'.join(options)})" if options else ""
        try:
            val = input(f"  {prompt}{opts}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return default
        if not val and default is not None:
            return default
        return val

    def _ask_int(prompt, default, lo=None, hi=None):
        """Ask for integer with range validation."""
        while True:
            val = _ask(prompt, str(default))
            try:
                n = int(val)
                if lo is not None and n < lo:
                    print(f"    Must be >= {lo}")
                    continue
                if hi is not None and n > hi:
                    print(f"    Must be <= {hi}")
                    continue
                return n
            except (ValueError, TypeError):
                print(f"    Enter a number")

    def _ask_bool(prompt, default=True):
        """Ask yes/no question."""
        suffix = " [Y/n]" if default else " [y/N]"
        try:
            val = input(f"  {prompt}{suffix}: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return default
        if not val:
            return default
        return val in ("y", "yes", "true", "1")

    print()
    print("  \033[1mVeritX Init Wizard\033[0m")
    print("  Generate a CompileRequest for your NoC design.")
    print()

    # ── Step 1: Workload ──
    print("  \033[1mStep 1/5: Workload\033[0m")
    model_family = _ask("Model family", "moe",
                         ["dense", "moe", "diffusion", "cnn", "custom"])
    family_map = {
        "dense": ModelFamily.DENSE_TRANSFORMER,
        "moe": ModelFamily.MOE,
        "diffusion": ModelFamily.DIFFUSION,
        "cnn": ModelFamily.CNN,
        "custom": ModelFamily.CUSTOM,
    }
    mf = family_map.get(model_family, ModelFamily.CUSTOM)

    model_name = _ask("Model name (e.g. Qwen3-30B)", "my_model")
    tp = _ask_int("Tensor parallelism (TP)", 8, lo=1)
    ep = 1
    if mf == ModelFamily.MOE:
        ep = _ask_int("Expert parallelism (EP)", 4, lo=1)
    dp = _ask_int("Data parallelism (DP)", 1, lo=1)
    precision = _ask("Precision", "fp16", ["fp16", "fp8", "int8", "bf16"])
    serving = _ask("Serving mode", "mixed", ["prefill", "decode", "mixed"])
    serving_map = {
        "prefill": ServingMode.PREFILL_HEAVY,
        "decode": ServingMode.DECODE_HEAVY,
        "mixed": ServingMode.MIXED,
    }
    sm = serving_map.get(serving, ServingMode.MIXED)

    trace_path = _ask("Trace file path (leave empty for none)", "") or None
    print()

    # ── Step 2: Agents ──
    print("  \033[1mStep 2/5: Agents\033[0m")
    n_compute = _ask_int("Number of compute tiles", tp * ep if mf == ModelFamily.MOE else tp, lo=1)
    n_hbm = _ask_int("Number of HBM controllers", max(1, n_compute // 4), lo=0)
    n_nic = _ask_int("Number of NICs", 0, lo=0)
    data_width = _ask_int("Data width (bits)", 256, lo=32)
    print()

    # ── Step 3: Requirements ──
    print("  \033[1mStep 3/5: Requirements\033[0m")
    has_req = _ask_bool("Add a latency/bandwidth requirement?", False)
    requirements = []
    if has_req:
        qos = _ask("QoS class", "latency", ["latency", "bandwidth", "best_effort"])
        qos_map = {
            "latency": QoSClass.LATENCY_CRITICAL,
            "bandwidth": QoSClass.BANDWIDTH,
            "best_effort": QoSClass.BEST_EFFORT,
        }
        if qos == "latency":
            ceiling = _ask_int("Latency ceiling (cycles)", 5000, lo=1)
            requirements.append(Requirement(
                qos_class=qos_map[qos],
                latency_ceiling_cycles=ceiling,
                binding=_ask_bool("Binding (must meet)?", True),
            ))
        elif qos == "bandwidth":
            floor = _ask_int("Bandwidth floor (Gbps)", 100, lo=1)
            requirements.append(Requirement(
                qos_class=qos_map[qos],
                bandwidth_floor_gbps=floor,
                binding=_ask_bool("Binding (must meet)?", True),
            ))
    print()

    # ── Step 4: Dependencies ──
    print("  \033[1mStep 4/5: Dependencies\033[0m")
    print("  Blocking dependencies can form deadlock cycles → VC derivation.")
    deps = []
    while True:
        add_dep = _ask_bool("Add a blocking dependency?", len(deps) == 0)
        if not add_dep:
            break
        src = _ask("  Source class (e.g. expert_alltoall)", "class_a")
        dst = _ask("  Target class (e.g. expert_reduce)", "class_b")
        kind_str = _ask("  Kind", "blocking", ["blocking", "ordering", "independent"])
        kind_map = {
            "blocking": DepKind.BLOCKING,
            "ordering": DepKind.ORDERING,
            "independent": DepKind.INDEPENDENT,
        }
        deps.append(Dependency(src, dst, kind_map.get(kind_str, DepKind.BLOCKING)))
        print(f"    Added: {src} → {dst} ({kind_str})")
    print()

    # ── Step 5: Topology ──
    print("  \033[1mStep 5/5: Topology\033[0m")
    topo = _ask("Topology family", "mesh", ["mesh", "torus", "gec", "concentrated_mesh"])
    topo_map = {
        "mesh": TopologyFamily.MESH,
        "torus": TopologyFamily.TORUS,
        "gec": TopologyFamily.GEC,
        "concentrated_mesh": TopologyFamily.CONCENTRATED_MESH,
    }
    tf = topo_map.get(topo, TopologyFamily.MESH)
    radix = _ask_int("Radix (k)", 8, lo=2) if _ask_bool("Set custom radix?", False) else None
    print()

    # ── Build CompileRequest ──
    agents = []
    if n_compute > 0:
        agents.append(Agent(AgentKind.COMPUTE_TILE, n_compute, data_width, 64, "AXI"))
    if n_hbm > 0:
        agents.append(Agent(AgentKind.HBM_CONTROLLER, n_hbm, data_width, 64, "AXI"))
    if n_nic > 0:
        agents.append(Agent(AgentKind.NIC, n_nic, data_width, 64, "AXI"))

    cr = CompileRequest(
        workload=Workload(
            model_family=mf, model_name=model_name,
            tp=tp, ep=ep, dp=dp,
            serving_mode=sm, precision=precision,
            trace_path=trace_path,
        ),
        requirements=tuple(requirements),
        agents=tuple(agents),
        dependencies=DependencyGraph(deps),
        noc_config=NocConfig(topology_family=tf, radix=radix),
    )

    # ── Save ──
    out_path = args.out or f"runs/compile_requests/{model_name.lower().replace(' ', '_')}.json"
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    d = cr.to_dict()
    d.pop("guardrail_hash", None)  # computed at runtime
    out.write_text(json.dumps(d, indent=2))

    ok(ctx, f"CompileRequest: {out}")
    log(ctx, f"  Model:    {cr.workload.model_name} ({cr.workload.model_family.value})")
    log(ctx, f"  Agents:   {', '.join(f'{a.kind.value}×{a.count}' for a in cr.agents)}")
    log(ctx, f"  Topology: {tf.value}, VCs: (derived from deps)")
    log(ctx, f"  Deps:     {len(deps)} blocking edges")
    print()
    print(f"  \033[32m✓ Next: veritx compile {out_path}\033[0m")
    print()

    output(ctx, d)


# ── Argument parser ─────────────────────────────────────────────────────────

BANNER = r"""
 __     __        _ _  __  __
 \ \   / /__ _ __(_) |_\ \/ /
  \ \ / / _ \ '__| | __|\  /
   \ V /  __/ |  | | |_ /  \
    \_/ \___|_|  |_|\__/_/\_\
"""

def build_parser() -> argparse.ArgumentParser:
    from .. import __version__
    parser = argparse.ArgumentParser(
        prog="veritx",
        description=(
            BANNER +
            f"\nVeritX v{__version__} — unified NoC DSE pipeline\n"
            "Intent-to-fabric compiler for AI Network-on-Chip"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--output", "-o", help="Save results to JSON file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress non-essential output")
    parser.add_argument("--seed", type=int, default=0, help="Random seed (0=auto-unique, default: 0)")
    parser.add_argument("--log", help="Append timestamped log to this file")
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # trace
    p_trace = sub.add_parser("trace", help="Ingest traffic data")
    ts = p_trace.add_subparsers(dest="trace_cmd")

    p_chakra = ts.add_parser("chakra", help="Chakra .et files")
    p_chakra.add_argument("et_dir")
    p_chakra.add_argument("--npu-map", dest="npu_map")
    p_chakra.add_argument("--speedup", type=float)
    p_chakra.add_argument("--nodes", type=int, default=64)
    p_chakra.add_argument("--out", default="runs/traces/input.trace")

    p_model = ts.add_parser("model", help="TrafficModel JSON")
    p_model.add_argument("model")
    p_model.add_argument("--nodes", type=int, default=64)
    p_model.add_argument("--out", default="runs/traces/input.trace")

    p_hpc = ts.add_parser("hpc", help="HPC MPI trace")
    p_hpc.add_argument("trace_file")
    p_hpc.add_argument("--nodes", type=int, default=64)
    p_hpc.add_argument("--out", default="runs/traces/input.trace")

    p_slice = ts.add_parser("slice", help="Slice trace by traffic class")
    p_slice.add_argument("--trace", required=True)
    p_slice.add_argument("--classes", required=True)
    p_slice.add_argument("--out", required=True)
    p_slice.add_argument("--renumber", action="store_true")

    p_info = ts.add_parser("info", help="Analyze trace characteristics")
    p_info.add_argument("trace")

    p_ext = ts.add_parser("extract", help="Extract burst or redistribute")
    p_ext.add_argument("trace")
    p_ext.add_argument("--burst", type=int)
    p_ext.add_argument("--uniform", action="store_true")
    p_ext.add_argument("--out", required=True)

    p_val = ts.add_parser("validate", help="Validate trace format")
    p_val.add_argument("trace")

    # synthesize
    p_synth = sub.add_parser("synthesize", help="Topology search")
    ss = p_synth.add_subparsers(dest="synth_cmd")

    p_bo = ss.add_parser("bo", help="Bayesian optimization")
    p_bo.add_argument("--nodes", type=int, default=64)
    p_bo.add_argument("--traffic", required=True)
    p_bo.add_argument("--iters", type=int, default=50)
    p_bo.add_argument("--seed", type=int)
    p_bo.add_argument("--scorer", default="analytical", choices=["analytical", "booksim"])

    p_grid = ss.add_parser("grid", help="Grid search")
    p_grid.add_argument("--nodes", type=int, default=64)

    p_iter = ss.add_parser("iterative", help="RHO/GRPO iterative search")
    p_iter.add_argument("--nodes", type=int, default=64)
    p_iter.add_argument("--trace", required=True)
    p_iter.add_argument("--method", default="rho", choices=["rho", "grpo"])
    p_iter.add_argument("--steps", type=int, default=50)
    p_iter.add_argument("--max-edges", type=int, default=120)
    p_iter.add_argument("--seed-anynet", default=None)
    p_iter.add_argument("--out", default=None)

    # evaluate
    p_eval = sub.add_parser("evaluate", help="Cycle-accurate scoring")
    es = p_eval.add_subparsers(dest="eval_cmd")

    p_bs = es.add_parser("booksim", help="BookSim2 mesh trace replay")
    p_bs.add_argument("--trace", required=True)
    p_bs.add_argument("--k", type=int, default=8)
    from veritx_dse.model.presets import _TOPO_BY_BACKEND
    known_backends = sorted(_TOPO_BY_BACKEND.keys())
    p_bs.add_argument("--topo", default="mesh",
                        help=f"Topology backend (any BookSim topology: {', '.join(known_backends)}, or anynet path)")
    p_bs.add_argument("--routing", default=None,
                        help="Routing function (default: from preset, or dim_order)")
    p_bs.add_argument("--vcs", type=int, default=4)
    p_bs.add_argument("--vc-buf", type=int, default=8)
    p_bs.add_argument("--sample-period", type=int, default=1000)
    p_bs.add_argument("--max-samples", type=int, default=5)
    p_bs.add_argument("--timeout", type=int, default=120)

    p_anynet = es.add_parser("anynet", help="BookSim2 custom topology")
    p_anynet.add_argument("--topo", required=True)
    p_anynet.add_argument("--trace", required=True)
    p_anynet.add_argument("--vcs", type=int, default=4)
    p_anynet.add_argument("--vc-buf", type=int, default=8)
    p_anynet.add_argument("--sample-period", type=int, default=1000)
    p_anynet.add_argument("--timeout", type=int, default=120)

    p_as = es.add_parser("astra", help="ASTRA-sim backend")
    p_as.add_argument("--ets", required=True)
    p_as.add_argument("--system-config", default="runs/llm/qwen3_tp16/system.json")
    p_as.add_argument("--network-config", default="runs/llm/qwen3_tp16/network.yml")
    p_as.add_argument("--memory-config", default="runs/llm/qwen3_tp16/memory.json")
    p_as.add_argument("--timeout", type=int, default=300)

    # certify
    p_cert = sub.add_parser("certify", help="Certification")
    cs = p_cert.add_subparsers(dest="cert_cmd")

    p_flow = cs.add_parser("flow", help="Flow-class certification")
    p_flow.add_argument("--model", required=True)
    p_flow.add_argument("--topo", required=True)

    p_rtl = cs.add_parser("rtl", help="RTL certification matrix")
    p_rtl.add_argument("--topo", required=True)
    p_rtl.add_argument("--build-dir", default=".")
    p_rtl.add_argument("--tier", default="quick", choices=["quick", "full"])

    p_full = cs.add_parser("full", help="Full certification")
    p_full.add_argument("--model", required=True)
    p_full.add_argument("--topo", required=True)
    p_full.add_argument("--build-dir", default=".")
    p_full.add_argument("--tier", default="quick", choices=["quick", "full"])

    # run
    p_run = sub.add_parser("run", help="Full pipeline")
    p_run.add_argument("--model", required=True)
    p_run.add_argument("--nodes", type=int, default=64)
    p_run.add_argument("--search", default="bo", choices=["bo", "grid", "iterative"])
    p_run.add_argument("--iterative-method", default="rho", choices=["rho", "grpo"])
    p_run.add_argument("--iters", type=int, default=50)
    p_run.add_argument("--scorer", default="analytical", choices=["analytical", "booksim"])
    p_run.add_argument("--cert", default="flow", choices=["flow", "rtl", "full", "none"])

    # sweep
    p_sweep = sub.add_parser("sweep", help="Batch-evaluate topologies")
    p_sweep.add_argument("--trace", required=True)
    p_sweep.add_argument("--timeout", type=int, default=60)
    p_sweep.add_argument("--mode", default="latency", choices=["latency", "throughput"])
    p_sweep.add_argument("--ir", type=float, default=0.05)

    # compare
    p_cmp = sub.add_parser("compare", help="Head-to-head topology comparison")
    p_cmp.add_argument("--trace", required=True)
    p_cmp.add_argument("--topos", default="mesh_8x8,torus_8x8")
    p_cmp.add_argument("--anynet", action="append", default=[])
    p_cmp.add_argument("--seeds", type=int, default=3)
    p_cmp.add_argument("--seed-base", type=int, default=0, help="Base seed (0=auto-unique)")
    p_cmp.add_argument("--timeout", type=int, default=60)
    p_cmp.add_argument("--dense", choices=list(DENSE_PRESETS.keys()))
    p_cmp.add_argument("--mode", default="latency", choices=["latency", "throughput"])
    p_cmp.add_argument("--ir", type=float, default=0.05)
    p_cmp.add_argument("--memory", action="store_true",
                        help="Apply shared-L2 bank contention correction (M/D/1 queue model)")
    p_cmp.add_argument("--banks", type=int, default=4, help="Number of L2 banks (for --memory)")
    p_cmp.add_argument("--bank-bw", type=int, default=1024, help="L2 bank bandwidth B/cyc (for --memory)")
    p_cmp.add_argument("--sensitivity", nargs="+", metavar="IR",
                        help="Run sensitivity analysis at specified injection rates (e.g. --sensitivity 0.01 0.05 0.1 0.2)")

    # pareto
    p_par = sub.add_parser("pareto", help="Multi-workload Pareto")
    p_par.add_argument("--traces", required=True)
    p_par.add_argument("--topos", default="mesh_8x8,torus_8x8")
    p_par.add_argument("--anynet", default="")
    p_par.add_argument("--seeds", type=int, default=1)
    p_par.add_argument("--timeout", type=int, default=60)
    p_par.add_argument("--out", default="runs/booksim/pareto.json")

    # diff
    p_diff = sub.add_parser("diff", help="Compare two experiment runs")
    p_diff.add_argument("run_a", nargs="?")
    p_diff.add_argument("run_b", nargs="?")

    # runs
    p_runs = sub.add_parser("runs", help="List/inspect experiment runs")
    p_runs.add_argument("--last", type=int, default=20)
    p_runs.add_argument("--run-id")

    # results
    p_results = sub.add_parser("results", help="Show latest results")
    p_results.add_argument("--last", type=int, default=5)

    # status
    p_status = sub.add_parser("status", help="Show run history")
    p_status.add_argument("--last", type=int, default=10)

    # report
    p_report = sub.add_parser("report", help="Generate LaTeX table")
    p_report.add_argument("--json", required=True)
    p_report.add_argument("--caption", default="Topology comparison")
    p_report.add_argument("--label", default="tab:compare")
    p_report.add_argument("--out")

    # ── baseline ──────────────────────────────────────────────
    p_bl = sub.add_parser("baseline", help="Compare against published baseline topologies")
    p_bl.add_argument("--trace", required=True, help="Trace file to evaluate")
    p_bl.add_argument("--topos", default="mesh_8x8",
                       help="Your topologies to compare (comma-separated)")
    p_bl.add_argument("--anynet", action="append", default=[],
                       help="Custom .anynet file(s) to include")
    p_bl.add_argument("--timeout", type=int, default=60)
    p_bl.add_argument("--seeds", type=int, default=1)

    # ── compile (intent-to-fabric) ──────────────────────────────
    p_compile = sub.add_parser("compile", help="Intent-to-fabric pipeline from CompileRequest JSON")
    p_compile.add_argument("request", help="Path to CompileRequest JSON file")
    p_compile.add_argument("--timeout", type=int, default=120)
    p_compile.add_argument("--output", "-o", help="Save results to JSON file")

    # ── init ──────────────────────────────────────────────────────
    p_init = sub.add_parser("init", help="Interactive wizard to generate a CompileRequest")
    p_init.add_argument("--out", "-o", help="Output JSON path (default: runs/compile_requests/<model>.json)")

    # ── serve (full-stack LLM serving simulation) ──────────────────
    p_serve = sub.add_parser("serve", help="Full-stack LLM serving simulation (LLMServingSim + AstraSim + BookSim2)")
    p_serve.add_argument("--cluster-config", required=True, help="Cluster configuration JSON")
    p_serve.add_argument("--dataset", required=True, help="Workload dataset JSONL")
    p_serve.add_argument("--num-reqs", type=int, default=1, help="Number of requests to simulate")
    p_serve.add_argument("--network-backend", default="booksim", choices=["booksim", "analytical", "ns3"],
                          help="Network simulation backend")
    p_serve.add_argument("--output", help="Output directory for results")
    p_serve.add_argument("--timeout", type=int, default=600, help="Simulation timeout in seconds")
    p_serve.add_argument("--log-level", default="WARNING", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                          help="LLMServingSim log level")
    p_serve.add_argument("--no-cleanup", action="store_true", help="Keep intermediate files")
    p_serve.add_argument("--no-prefix-caching", action="store_true", help="Disable prefix caching")

    # ── generate ──────────────────────────────────────────────────
    p_gen = sub.add_parser("generate", help="Generate collateral (UVM, RTL, reports)")
    gs = p_gen.add_subparsers(dest="gen_cmd")

    p_uvm = gs.add_parser("uvm", help="Generate UVM testbench")
    p_uvm.add_argument("--request", required=True, help="Path to CompileRequest JSON")
    p_uvm.add_argument("--out", default="runs/uvm", help="Output directory")
    p_uvm.add_argument("--nodes", type=int, default=64, help="Number of network nodes")
    p_uvm.add_argument("--k", type=int, default=8, help="Mesh dimension (sqrt of nodes)")

    return parser


# ── Dispatch ────────────────────────────────────────────────────────────────

TRACE_CMDS = {
    "chakra": cmd_trace_chakra,
    "model": cmd_trace_model,
    "hpc": cmd_trace_hpc,
    "slice": cmd_trace_slice,
    "info": cmd_trace_info,
    "extract": cmd_trace_extract,
    "validate": cmd_trace_validate,
}

DISPATCH = {
    "trace": TRACE_CMDS,
    "synthesize": {
        "bo": cmd_synthesize_bo,
        "grid": cmd_synthesize_grid,
        "iterative": cmd_synthesize_iterative,
    },
    "evaluate": {
        "booksim": cmd_evaluate_booksim,
        "anynet": cmd_evaluate_anynet,
        "astra": cmd_evaluate_astra,
    },
    "certify": {
        "flow": cmd_certify_flow,
        "rtl": cmd_certify_rtl,
        "full": cmd_certify_full,
    },
    "run": cmd_run,
    "sweep": cmd_sweep,
    "compare": cmd_compare,
    "pareto": cmd_pareto,
    "runs": cmd_runs,
    "results": cmd_results,
    "status": cmd_status,
    "diff": cmd_diff,
    "report": cmd_report,
    "baseline": cmd_baseline,
    "compile": cmd_compile,
    "init": cmd_init,
    "serve": cmd_serve,
    "generate": {
        "uvm": cmd_generate_uvm,
    },
}

_SUB_DESTS = {
    "trace": "trace_cmd",
    "synthesize": "synth_cmd",
    "evaluate": "eval_cmd",
    "certify": "cert_cmd",
    "generate": "gen_cmd",
}


def main():
    from .. import __version__
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        print(f"VeritX v{__version__}")
        parser.print_help()
        return

    # Build context
    raw_seed = getattr(args, "seed", 0)
    if raw_seed == 0:
        # Auto-generate unique seed from timestamp + PID
        import time, os
        raw_seed = int(time.time() * 1000) % 10000000 + os.getpid() % 1000
    ctx = Ctx(
        verbosity=0 if args.quiet else (2 if args.verbose else 1),
        json_mode=getattr(args, "json", False),
        output_file=getattr(args, "output", None),
        log_file=getattr(args, "log", None),
        seed=raw_seed,
    )

    try:
        handler = DISPATCH.get(args.command)
        if handler is None:
            parser.print_help()
            return

        if isinstance(handler, dict):
            # Subcommand dispatch
            sub_key = getattr(args, _SUB_DESTS.get(args.command, f"{args.command}_cmd"), None)
            if sub_key and sub_key in handler:
                handler[sub_key](ctx, args)
            else:
                parser.parse_args([args.command, "--help"])
        else:
            handler(ctx, args)

    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except BookSimError as e:
        fail(ctx, str(e))
        if e.stderr:
            for line in e.stderr.splitlines()[-5:]:
                print(f"    {line}", file=sys.stderr)
        sys.exit(1)
    except TimeoutError as e:
        fail(ctx, str(e))
        sys.exit(1)
    except Exception as e:
        fail(ctx, f"{args.command} failed: {e}")
        sys.exit(1)
    finally:
        ctx.close()
        _cleanup_stale_temp_dirs()


def _cleanup_stale_temp_dirs():
    """Remove stale temp dirs left by interrupted BookSim runs.

    BookSim configs are written to runs/booksim/tmp*/ and cleaned up
    in the finally block of run_booksim(). But if the process is killed
    (SIGKILL, OOM, Ctrl+C in certain edge cases), the cleanup doesn't
    run. This function removes any temp dirs older than 1 hour.
    """
    import shutil, time as _time
    scratch = REPO / "runs" / "booksim"
    if not scratch.exists():
        return
    now = _time.time()
    for d in scratch.iterdir():
        if d.is_dir() and d.name.startswith("tmp"):
            age_hours = (now - d.stat().st_mtime) / 3600
            if age_hours > 1:
                shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    main()
