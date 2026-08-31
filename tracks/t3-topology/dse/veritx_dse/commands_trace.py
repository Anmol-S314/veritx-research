"""veritx_dse.commands_trace — Trace-related CLI commands."""
from __future__ import annotations
import sys
from pathlib import Path
from .logging import Ctx, log, ok, fail, verbose, banner, output


def cmd_trace_validate(ctx: Ctx, args):
    """Validate trace format and sanity-check before expensive BookSim runs."""
    from .traces import validate_trace
    result = validate_trace(args.trace)
    if not result.valid:
        fail(ctx, f"Trace has {len(result.errors)} errors — fix before running BookSim")
        for e in result.errors:
            log(ctx, f"  ✗ {e}")
        return
    banner(ctx, f"Trace: {Path(args.trace).name}")
    log(ctx, f"  Packets:    {result.packets:,}")
    log(ctx, f"  Sources:    {result.sources}")
    log(ctx, f"  Dests:      {result.dests}")
    log(ctx, f"  Classes:    {result.classes}")
    log(ctx, f"  Time:       [{result.time_range[0]}, {result.time_range[1]}]")
    log(ctx, f"  Span:       {result.span:,} cycles")
    log(ctx, f"  IR:         {result.injection_rate:.4f} pkt/node/cycle")
    if result.warnings:
        log(ctx, f"  Warnings:   {len(result.warnings)}")
        if ctx.verbosity > 0 and not ctx.json_mode:
            for w in result.warnings:
                log(ctx, f"  ⚠ {w}")
    if not ctx.json_mode:
        print(f"  \033[32m✓ Trace is usable but has {len(result.warnings)} warnings\033[0m")
    output(ctx, result.to_dict())


def cmd_trace_info(ctx: Ctx, args):
    """Show detailed trace information."""
    from .traces import validate_trace
    result = validate_trace(args.trace)
    if ctx.json_mode:
        output(ctx, result.to_dict())
    else:
        print(f"  File:       {result.file}")
        print(f"  Valid:      {result.valid}")
        print(f"  Packets:    {result.packets:,}")
        print(f"  Sources:    {result.sources}")
        print(f"  Dests:      {result.dests}")
        print(f"  Classes:    {result.classes}")
        print(f"  Sizes:      {result.sizes}")
        print(f"  Time:       [{result.time_range[0]}, {result.time_range[1]}]")
        print(f"  Span:       {result.span:,} cycles")
        print(f"  IR:         {result.injection_rate:.4f}")
        print(f"  Self-loops: {result.self_loops}")
        if result.errors:
            print(f"  Errors:     {len(result.errors)}")
            for e in result.errors:
                print(f"    ✗ {e}")
        if result.warnings:
            print(f"  Warnings:   {len(result.warnings)}")
            for w in result.warnings:
                print(f"    ⚠ {w}")


def cmd_trace_extract(ctx: Ctx, args):
    """Extract uniform traffic matrix from trace."""
    from .traces import extract_uniform
    matrix = extract_uniform(args.trace)
    Path(args.out).write_text(str(matrix))
    ok(ctx, f"Extracted {matrix.shape[0]}x{matrix.shape[1]} matrix → {args.out}")


def cmd_trace_slice(ctx: Ctx, args):
    """Slice trace by class."""
    from .traces import slice_trace_by_class
    classes = [int(c) for c in args.classes.split(",")]
    kept, dropped = slice_trace_by_class(args.trace, args.out, classes, args.renumber)
    ok(ctx, f"Slice: {kept} packets kept, {dropped} dropped → {args.out}")


def cmd_trace_chakra(ctx: Ctx, args):
    """Convert Chakra ET trace to veritx format."""
    from pathlib import Path as P
    et_path = P(args.et_dir)
    if not et_path.exists():
        fail(ctx, f"Path not found: {et_path}")
        return
    if et_path.is_dir():
        et_files = list(et_path.glob("*.et"))
        if not et_files:
            fail(ctx, f"No .et files found in {et_path}")
            fail(ctx, "Expected a directory containing Chakra ET binary files")
            fail(ctx, "Or use 'veritx trace model' to generate from traffic model")
            return
        fail(ctx, f"Found {len(et_files)} .et files but chakra_to_dse expects LLMServingSim TEXT format")
        fail(ctx, "Use 'veritx trace model' to generate from traffic model instead")
        return
    fail(ctx, f"Expected directory, got file: {et_path}")
    fail(ctx, "Chakra ET binary format not supported — use 'veritx trace model'")


def cmd_trace_model(ctx: Ctx, args):
    """Generate trace from traffic model."""
    import json, subprocess, sys
    from pathlib import Path as P
    traffic_model = P(args.model)
    if not traffic_model.exists():
        fail(ctx, f"Traffic model not found: {traffic_model}")
        return
    out = args.out or "runs/traces/input.trace"
    out_path = P(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log(ctx, f"Converting traffic model {traffic_model.name}")
    r = subprocess.run(
        [sys.executable, str(DSE_DIR / "traffic_model_compiler.py"),
         str(traffic_model.resolve()), "--nodes", str(args.nodes),
         "--out", str(out_path.resolve())],
        capture_output=True, text=True, timeout=60, cwd=str(REPO)
    )
    if r.returncode != 0:
        fail(ctx, f"trace failed: {r.stderr.strip()[-200:]}")
        return
    for line in r.stdout.splitlines():
        log(ctx, line)
    ok(ctx, f"Trace written: {out}")


def cmd_trace_hpc(ctx: Ctx, args):
    """Copy HPC trace from built-in library."""
    import shutil, sys
    from pathlib import Path as P
    preset_map = {
        "hpc_wrf": "wrf128_ring.trace",
        "hpc_graph500": "graph500_sparse.trace",
        "hpc_pennant": "pennant_sn默认.trace",
    }
    trace_file = preset_map.get(args.preset)
    if not trace_file:
        fail(ctx, f"Unknown preset: {args.preset}")
        log(ctx, f"Available: {', '.join(preset_map.keys())}")
        return
    src = SCRIPTS_DIR / "gen_llmserv_traces.py"
    out = args.out or f"runs/traces/{args.preset}.trace"
    log(ctx, f"HPC preset {args.preset} → copying")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("gen_trace", src)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main()
        ok(ctx, f"HPC trace: {out}")
    except Exception as e:
        fail(ctx, f"HPC trace generation failed: {e}")


# Re-export for lazy import
def _get_all():
    return {
        "validate": cmd_trace_validate,
        "info": cmd_trace_info,
        "extract": cmd_trace_extract,
        "slice": cmd_trace_slice,
        "chakra": cmd_trace_chakra,
        "model": cmd_trace_model,
        "hpc": cmd_trace_hpc,
    }
