"""veritx_dse.commands_trace — Trace-related CLI commands."""
from __future__ import annotations
import sys
from pathlib import Path
from ..core.logging import Ctx, log, ok, fail, verbose, banner, output
from ..core.paths import DSE_DIR


def cmd_trace_validate(ctx: Ctx, args):
    """Validate trace format and sanity-check before expensive BookSim runs."""
    from ..simulation.traces import validate_trace
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
    from ..simulation.traces import validate_trace
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
    """Extract a sub-trace: first-N burst (times shifted to t=0) or uniform
    redistribution across the time range."""
    from ..simulation.traces import extract_uniform, _shift_times_to_zero
    src = Path(args.trace)
    if not src.is_file():
        fail(ctx, f"Trace not found: {src}")
        return
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.burst is not None:
        n = args.burst
        if n < 1:
            fail(ctx, f"--burst must be >= 1, got {n}")
            return
        packets = []
        with open(src) as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                p = line.split()
                if len(p) >= 5:
                    packets.append(p)
        if not packets:
            fail(ctx, f"No packets in trace: {src}")
            return
        n = min(n, len(packets))
        with open(out, "w") as fo:
            for p in packets[:n]:
                fo.write(" ".join(p) + "\n")
        _shift_times_to_zero(out)
        ok(ctx, f"Burst extract: first {n} packets (times shifted to t=0) → {out}")
    else:
        result = extract_uniform(str(src), str(out))
        ok(ctx, f"Uniform redistribution: {result.packets} packets, "
                f"spacing {result.spacing} → {out}")


def cmd_trace_slice(ctx: Ctx, args):
    """Slice trace by traffic class."""
    from ..simulation.traces import slice_trace
    src = Path(args.trace)
    if not src.is_file():
        fail(ctx, f"Trace not found: {src}")
        return
    try:
        classes = {int(c) for c in args.classes.split(",") if c.strip()}
    except ValueError:
        fail(ctx, f"--classes must be a comma-separated list of integers, got: {args.classes}")
        return
    result = slice_trace(str(src), classes, args.out, renumber=args.renumber)
    ok(ctx, f"Slice: {result.kept} packets kept, {result.dropped} dropped → {args.out}")


def cmd_trace_chakra(ctx: Ctx, args):
    """Convert Chakra ET trace to veritx format."""
    et_path = Path(args.et_dir)
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
    """Generate a BookSim trace from a unified TrafficModel JSON."""
    import subprocess
    traffic_model = Path(args.model)
    if not traffic_model.exists():
        fail(ctx, f"Traffic model not found: {traffic_model}")
        return
    out = args.out or "runs/traces/input.trace"
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log(ctx, f"Converting traffic model {traffic_model.name}")
    r = subprocess.run(
        [sys.executable, "-m", "veritx_dse.simulation.model_to_trace",
         "--traffic-model", str(traffic_model.resolve()),
         "--nodes", str(args.nodes),
         "--out", str(out_path.resolve())],
        capture_output=True, text=True, timeout=120, cwd=str(DSE_DIR)
    )
    if r.returncode != 0:
        fail(ctx, f"trace model failed: {r.stderr.strip()[-200:]}")
        return
    for line in r.stdout.splitlines():
        log(ctx, line)
    ok(ctx, f"Trace written: {out_path}")


def cmd_trace_hpc(ctx: Ctx, args):
    """Install a trace from the built-in library (dse/inputs/traces) into the
    runs tree. Accepts a library name (e.g. `qwen3_serving_astra`) or an
    explicit path to a .trace file."""
    import shutil
    lib_dir = DSE_DIR / "inputs" / "traces"
    requested = args.trace_file
    if requested.endswith(".trace") and Path(requested).is_file():
        src = Path(requested)
    else:
        name = requested if requested.endswith(".trace") else f"{requested}.trace"
        src = lib_dir / name
        if not src.is_file():
            available = sorted(p.name for p in lib_dir.glob("*.trace"))
            fail(ctx, f"Trace not in library: {name}")
            log(ctx, f"Available: {', '.join(available) if available else '(none)'}")
            return
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, out)
    ok(ctx, f"Installed {src.name} → {out}")


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
