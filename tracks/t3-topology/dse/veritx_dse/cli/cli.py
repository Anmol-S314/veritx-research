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
    veritx evaluate astra --ets <et_file> [--timeout 300]
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
import os
import re
import sys
import time
from pathlib import Path

from ..core.errors import TraceError, ConfigError, BookSimError, TimeoutError
from ..core.constants import BOOKSIM_SEED, DEFAULT_K, DEFAULT_NODES


from ..core.logging import (
    Ctx, log, ok, fail, verbose, banner, output,
    print_human, emit, diag, early_error,
)
from ..model.presets import (
    Topology, SWEEP_TOPOS, DENSE_PRESETS, lookup_topo, make_anynet_topo,
    count_anynet_edges, check_anynet_connected,
)
from ..simulation.booksim import (
    detect_trace_stats, run_topology_eval,
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
from veritx_dse.core.paths import (
    REPO, DSE_DIR, RUNS_DIR, RESULTS_DIR, TRACK_RUNS_DIR, SYNTH_DIR,
    new_run_dir, BOOKSIM_BIN, ASTRA_BS_BIN, LLMSIM_DIR, CHAKRA_TO_ET,
)

# Tools dir: historical one-off scripts, folded into the package (2026-09-16).
# Import surface is veritx_dse.tools; SCRIPTS_DIR kept as an alias so the
# command handlers below stay untouched.
SCRIPTS_DIR = _THIS_TOOLS_DIR = DSE_DIR / "veritx_dse" / "tools"
EXPERIMENTS_DIR = RUNS_DIR / "experiments"
CERTIFY_SH = DSE_DIR.parent / "scripts" / "certify.sh"

# ── BookSim wall-time budget (calibrated): ~13k packets/s on this host
# (Slice A e2e: 20k pkts ≈ 1.5 s; suite ~9 s for ~117k pkts). Used to
# refuse hopeless budgets BEFORE burning them (run 20260916_213026:
# 56.1M-pkt trace given 600 s — dead on arrival at ~70 min predicted).
BOOKSIM_PKTS_PER_SEC = 13_000

# Timeloop binary homes: the container builds its OWN (ABI matches the
# image); the vendored bin was built on the host (24.04 sonames — cannot
# load in the 22.04 container: 'libconfig++.so.11: cannot open shared').


def _pick_timeloop_mapper(*, usr_local: Path | None = None,
                          vendor_bin: Path | None = None) -> tuple[Path, str]:
    """Pick the timeloop-mapper binary + record its provenance.

    Container-built binary first (its shared libs match the runtime image
    by construction); vendored host-built binary as fallback with a loud
    provenance note. Homes are injectable for tests; defaults resolve at
    CALL time so a monkeypatched REPO redirects the vendored leg.
    """
    c = (usr_local or Path("/usr/local/bin")) / "timeloop-mapper"
    if c.exists():
        return c, "container-built (/usr/local/bin)"
    v = (vendor_bin or REPO / "third_party" / "timeloop" / "bin") / "timeloop-mapper"
    if v.exists():
        return v, "vendored host-built (third_party/timeloop/bin)"
    return v, "missing"


def _timeloop_env(provenance: str, *, base: dict | None = None,
                  vendor_libdir: str | None = None) -> dict:
    """Loader env must MATCH the picked binary's provenance.

    The vendored host-built mapper needs LD_LIBRARY_PATH pointing at the
    in-tree libtimeloop-model.so build dir; the container-built mapper
    must NOT see it — inside a t3 container, /workspace IS the host repo
    mount, so the vendored build dir holds host-built libs (24.04-era
    sonames: libconfig++.so.11, GLIBC_2.38) that shadow the image's own
    /usr/local/lib copy and kill the healthy binary with exit 127
    (reproduced in run 20260917_032223). Environment is execution
    context, not decoration — redesign §4.2.
    """
    env = dict(base if base is not None else os.environ)
    vdir = vendor_libdir or str(REPO / "third_party" / "timeloop" / "build")
    if provenance.startswith("vendored"):
        env["LD_LIBRARY_PATH"] = vdir + ":" + env.get("LD_LIBRARY_PATH", "")
    else:
        keep = [p for p in env.get("LD_LIBRARY_PATH", "").split(":")
                if p and p != vdir]
        if keep:
            env["LD_LIBRARY_PATH"] = ":".join(keep)
        else:
            env.pop("LD_LIBRARY_PATH", None)
    return env


def booksim_budget_estimate(packets: int, budget_s: int = 600) -> dict:
    """Predict BookSim wall time for a packet count and check feasibility."""
    predicted_s = packets / BOOKSIM_PKTS_PER_SEC
    return {
        "packets": packets,
        "pkts_per_s": BOOKSIM_PKTS_PER_SEC,
        "predicted_s": round(predicted_s, 1),
        "budget_s": budget_s,
        "feasible": predicted_s <= budget_s,
    }


def predict_booksim_budget(trace_path: Path, budget_s: int = 600) -> dict:
    """Feasibility estimate from the trace header (cheap: never reads the
    whole file; falls back to a line count when no header is present).

    A packet-count estimate, not a runtime guarantee — but it converts
    'mystery timeout after 10 min' into a number printed before the run.
    """
    n = None
    try:
        with open(trace_path) as f:
            for line in f:
                if not line.startswith("#"):
                    break  # header ends at first packet line
                m = re.search(r":\s*(\d+)\s+packets", line)
                if m:
                    n = int(m.group(1))
                    break
    except OSError:
        pass
    if n is None:
        with open(trace_path) as f:
            n = sum(1 for _ in f)
    return booksim_budget_estimate(n, budget_s=budget_s)
# ASTRA embedded leg packet size (flits). Deliberately ≠ BASE_PARAMS
# packet_size=8 — see _write_anynet_cfg divergence note. Named (not
# inlined) so the next reconciliation is one edit + rerun, not archaeology.
ASTRA_PACKET_SIZE = 64
T3_SCRIPTS_DIR = DSE_DIR.parent / "scripts"   # track-level scripts (chakra gen, astra adapter, energy_report)


def sanitize_path(p: str) -> str:
    """Reject path traversal attempts."""
    if '..' in p:
        raise ValueError(f"Path traversal not allowed: {p}")
    resolved = Path(p).resolve()
    return str(resolved)


def _expand_anynet_files(entries: list[str] | None) -> list[str]:
    """Flatten --anynet args to a file list.

    The flag is repeatable AND each use accepts comma-separated paths
    (mirrors --topos/--traces conventions). Blank segments are dropped.
    Existence is NOT checked here — callers warn-and-continue on missing
    files (compare/baseline proceed with the built-ins).
    """
    files: list[str] = []
    for entry in entries or []:
        files.extend(p.strip() for p in entry.split(",") if p.strip())
    return files


def _eff_timeout(args, default: int) -> int:
    """Resolve effective timeout in seconds.

    Precedence: --timeout flag > VERITX_TIMEOUT env > built-in default.
    Flags default to None precisely so an explicit env can apply without
    editing invocations (batch/CI convenience: VERITX_TIMEOUT=86400 ≈ 24h).
    Values < 1 are rejected — there is deliberately no wait-forever mode:
    hung simulators burn machines silently, and 86400 covers any real run.
    """
    from veritx_dse.core.constants import env_int
    raw = getattr(args, "timeout", None)
    if raw is None:
        return env_int("VERITX_TIMEOUT", default)
    if raw < 1:
        raise ValueError(f"--timeout must be >= 1 second, got {raw}")
    return raw


def _resolve_path(p: str) -> str:
    """Resolve a path relative to REPO, DSE_DIR, or absolute.

    Handles symlinks by resolving them first, then falling back to REPO-relative.
    **Required-input files** (model trace et spec request topo dataset cluster
    config): relative paths may walk up (..) so things like
    `--spec ../product/examples/chiplet_2die.json` from `dse/` work.

    **Asset-helper paths** (serving configs/datasets, --build-dir, --out)
    must stay anchored — those are safety-banded below, not here.
    """
    p = str(p)   # accept Path objects too (callers pass both)
    path = Path(p)
    # First: permit wiki `..` ONLY if the final resolved location sits
    # inside REPO — this is the narrow band that makes `--spec ../product/…`
    # work from `dse/`. Anything that walks up past the repo is rejected.
    prefer = path.resolve()
    if ".." in p:
        # Permit upward-relative paths that, once resolved, land inside REPO.
        # This is how `veritx run --spec ../product/examples/chiplet_2die.json`
        # works when invoked from `tracks/t3-topology/dse/`.
        root = prefer.resolve()
        try:
            root.relative_to(REPO)
            return str(root)
        except ValueError:
            raise ValueError(f"Path traversal not allowed: {p}")   # rejected: outside REPO
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


def _require_file(ctx: Ctx, p: str, what: str, kind: str | None = "model") -> bool:
    """Fail-fast existence gate for user-supplied asset paths.

    Resolves the path, then turns a miss into a precise one-line error with
    a hint from the asset registry instead of a raw OSError three frames
    deep in a subprocess. True = the caller should proceed.
    """
    try:
        resolved = _resolve_path(p)
    except ValueError as e:
        fail(ctx, f"{what} rejected: {e}")
        return False
    if Path(resolved).exists():
        return True
    msg = f"{what} not found: {p}"
    hit = _resolve_asset(Path(p).name, kind) if kind else None
    if hit is not None:
        msg += f" — did you mean {hit.name}?"
    elif kind:
        names = _list_assets(kind)
        if names:
            msg += f" — available: {', '.join(names[:6])}"
    fail(ctx, msg)
    return False


# ── Asset discovery (usability: kill the "what's the full path" friction) ───

# name → (search dirs, extensions tried in order). Dirs are relative to DSE_DIR
# unless absolute. Kept as data so adding an asset class is one line.
_ASSET_KINDS = {
    "trace": (["archive/inputs/traces", "runs/astra", "runs/booksim"], [".trace"]),
    "example": (["examples"], [".json"]),
    "fixture": (["tests/fixtures"], [".et", ".json", ".cfg"]),
    "anynet": (["archive/inputs", "runs/booksim", "scripts/rtlgen"], [".anynet"]),
    # TrafficModel JSONs ONLY (schema: network.flow_classes). CompileRequests
    # live under "request" — --model used to resolve into examples/ and hand
    # model_to_trace a CompileRequest, dying with a bare KeyError('network').
    "model": (["models"], [".json"]),
    "request": (["examples"], [".json"]),
}


def _resolve_asset(name: str, kind: str = "trace") -> Path | None:
    """Resolve an asset by short name (extension optional, substring fallback).

    Order: exact path as given → kind dir + name + ext → kind dir + name →
    unique substring match over the kind's dirs. Returns None when nothing
    matches — the caller decides what 'not found' looks like.
    """
    if kind not in _ASSET_KINDS:
        return None
    dirs, exts = _ASSET_KINDS[kind]
    p = Path(name)
    # 1. Literal path (absolute or DSE/REPO-relative) — existing files win.
    try:
        hit = Path(_resolve_path(name))
        if hit.is_file():
            return hit
    except ValueError:
        return None
    # 2. Kind dirs: name with each extension, then bare name.
    for d in dirs:
        base = Path(d) if Path(d).is_absolute() else DSE_DIR / d
        if not base.is_dir():
            continue
        for ext in exts:
            cand = base / (name if name.endswith(ext) else name + ext)
            if cand.is_file():
                return cand.resolve()
        bare = base / name
        if bare.is_file():
            return bare.resolve()
    # 3. Unique substring match across the kind's dirs.
    needle = name.lower().removesuffix(exts[0]) if exts else name.lower()
    matches: list[Path] = []
    for d in dirs:
        base = Path(d) if Path(d).is_absolute() else DSE_DIR / d
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*")):
            if f.is_file() and needle in f.name.lower():
                matches.append(f.resolve())
    if len(matches) == 1:
        return matches[0]
    return None  # 0 or ambiguous


def _list_assets(kind: str) -> list[str]:
    """Sorted asset names available for a kind (for helpful 'did you mean')."""
    if kind not in _ASSET_KINDS:
        return []
    dirs, _ = _ASSET_KINDS[kind]
    out: list[str] = []
    for d in dirs:
        base = Path(d) if Path(d).is_absolute() else DSE_DIR / d
        if base.is_dir():
            out.extend(f.name for f in sorted(base.iterdir()) if f.is_file())
    return sorted(set(out))


# ── Command handlers ────────────────────────────────────────────────────────
# Each function: parse args → call module → print result.
# NO business logic. NO sys.exit. Exceptions propagate to main().


def cmd_history(ctx: Ctx, args):
    """Cross-run queries the flat `runs`/`results` commands can't do:
    every result row across every sweep, filtered and sorted — the query
    surface the future backend/API will reuse via the same Store class."""
    import os
    from ..core.store import Store
    # VERITX_INDEX_DB relocates the index (tests isolate via it; users can
    # point several checkouts at one index). Repo-local runs/index.db default.
    db = Path(os.environ.get("VERITX_INDEX_DB") or (REPO / "runs" / "index.db"))
    store = Store(db)
    if getattr(args, "reindex", False):
        n = 0
        for root in (REPO / "runs", REPO / "tracks" / "t3-topology" / "results"):
            if root.is_dir():
                n += store.ingest(root)
        log(ctx, f"Indexed {n} rows into {db.name}")
    rows = store.query(
        topology=getattr(args, "topo", None),
        workload=getattr(args, "workload", None),
        status=getattr(args, "status", None),
        min_cycles=getattr(args, "min_cycles", None),
        limit=getattr(args, "limit", 50),
    )
    output(ctx, rows, human_fn=lambda rs: _print_history(ctx, rs))


def _print_history(ctx: Ctx, rows: list):
    if not rows:
        log(ctx, "No indexed rows. Try: veritx history --reindex")
        return
    log(ctx, f"{len(rows)} row(s) (newest first):\n")
    header = f"  {'topology':<14} {'workload':<12} {'cycles':>10} {'exposed':>10} {'status':<28} source"
    log(ctx, header)
    log(ctx, "  " + "-" * (len(header) - 2))
    for r in rows:
        log(ctx, "  {topo:<14} {wl:<12} {cyc:>10} {exp:>10} {st:<28} {src}".format(
            topo=str(r.get("topology") or "-")[:14],
            wl=str(r.get("workload") or "-")[:12],
            cyc=r.get("astrasim_cycles") if r.get("astrasim_cycles") is not None else "-",
            exp=r.get("exposed_comm_cycles") if r.get("exposed_comm_cycles") is not None else "-",
            st=str(r.get("status") or "-")[:28],
            src=str(r.get("source_path") or r.get("traffic") or "-"),
        ))


def cmd_where(ctx: Ctx, args):
    """Resolve an asset by short name → absolute, copy-pasteable path.

    `veritx where test_dynamic` beats remembering inputs/traces/. On a miss,
    list what IS available (a miss should teach, not just fail).
    """
    kind = getattr(args, "kind", None) or "trace"
    hit = _resolve_asset(args.name, kind=kind)
    # UX: the user shouldn't need to know the kind. Default kind first, then
    # every other kind before declaring a miss.
    if hit is None:
        for other in sorted(_ASSET_KINDS):
            if other == kind:
                continue
            hit = _resolve_asset(args.name, kind=other)
            if hit is not None:
                kind = other
                break
    if hit is not None:
        result = {"resolved": str(hit), "kind": kind, "name": args.name}
        if not ctx.json_mode:
            emit(ctx, str(hit))
            rel = Path(hit).relative_to(DSE_DIR) if Path(hit).is_relative_to(DSE_DIR) else hit
            log(ctx, f"{kind}: {rel}")
        output(ctx, result)
        return
    # Miss: show the kind's directory and what's in it.
    available = _list_assets(kind)
    fail(ctx, f"No {kind} matching '{args.name}'.")
    if available:
        log(ctx, f"Available {kind}s:")
        for a in available:
            log(ctx, f"  {a}")
    else:
        log(ctx, f"(no {kind} directories populated — see veritx init)")


def cmd_doctor(ctx: Ctx, args):
    """Self-check battery: run the doctor checks for --level, print the
    report, optionally append the LLM second opinion, optionally dump JSON.

    Exit-code contract (matches the launch-grade rule used everywhere):
    verdict FAIL  -> exit 1 (a failed doctor must fail CI/PTY flows).
    verdict WARN/PASS -> exit 0; warnings are visible, not fatal.
    """
    from ..core.doctor import build_paste_prompt, render, review_with_llm, run_checks
    log(ctx, f"doctor: running {args.level} battery")
    report = run_checks(args.level)
    if args.llm:
        report.llm = review_with_llm(report)
        if report.llm is None:
            # No endpoint configured → the economical manual flow: emit the
            # exact paste-ready prompt (same system prompt + payload the
            # automated adapter would send, so answers are comparable),
            # stored in the JSON dump so the copy never lives in scrollback.
            report.llm = {"model": "manual-paste", "review": None,
                          "paste_prompt": build_paste_prompt(report)}
            log(ctx, "doctor: no LLM endpoint — paste prompt written below "
                     "and to --json-out; paste into any chat LLM")
    out = render(report)
    emit(ctx, out)
    if args.json_out:
        p = Path(args.json_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report.to_dict(), indent=2))
        log(ctx, f"report JSON: {p}")
    elif report.llm and report.llm.get("paste_prompt"):
        # Manual review without a JSON dump: print the prompt so the copy
        # is one action even when the user forgot --json-out.
        emit(ctx, "")
        emit(ctx, "=== LLM paste prompt ===")
        emit(ctx, report.llm["paste_prompt"])
    if report.verdict == "FAIL":
        fail(ctx, "doctor verdict FAIL — see checks marked ✗ above")
        return
    ok(ctx, report.summary())


def cmd_interact(ctx: Ctx, args):
    """Guided entry point: same power as the flat CLI, zero path memorization.

    Non-interactive (EOF / piped) stdin prints the quickstart menu with
    copy-pasteable one-liners and exits 0 — every flow must remain
    scriptable, so 'interactive' only ever ADDS prompts on a TTY.
    """
    import shutil
    interactive = sys.stdin.isatty() and not getattr(args, "no_prompt", False)

    if not interactive:
        # Piped/EOF: the honest menu — what to run next, copy-pasteable.
        emit(ctx, __import__("veritx_dse").__doc__ or "VeritX")
        emit(ctx, "\nCommon next steps (copy-paste; `veritx where` finds any path):\n")
        emit(ctx, "  veritx where test_dynamic            # resolve any asset by short name")
        emit(ctx, "  veritx trace validate <trace>        # is this trace usable?")
        emit(ctx, "  veritx trace info <trace>            # packets, span, profile")
        emit(ctx, "  veritx evaluate booksim --trace <trace> --k 8")
        emit(ctx, "  veritx evaluate astra --ets <workload.et> ...   # cycle-accurate")
        emit(ctx, "  veritx run --traffic-model <examples/*.json>    # full pipeline")
        emit(ctx, "  veritx init                          # scaffold a project")
        emit(ctx, "\n  veritx --help                        # everything else\n")
        return

    # TTY: prompt for an asset, then print the command the user needs.
    kind = getattr(args, "kind", None) or "trace"
    name = input(f"{kind} name (Enter=skip): ").strip()
    if not name:
        emit(ctx, "Nothing resolved — rerun `veritx interact` when ready.")
        return
    hit = _resolve_asset(name, kind=kind)
    if hit is None:
        # Guided browse: a miss is a query with no results, not a pipeline
        # failure — show what IS available and exit 0 (scripted resolution
        # belongs to `veritx where`, which keeps its non-zero contract).
        emit(ctx, f"  No {kind} matching '{name}'. Available:")
        for a in _list_assets(kind):
            emit(ctx, f"    {a}")
        return
    ok(ctx, f"Resolved: {hit}")
    emit(ctx, f"\nTry:\n  veritx trace validate {hit}")
    emit(ctx, f"  veritx evaluate booksim --trace {hit} --k 8")
    if shutil.which("veritx") is None:
        emit(ctx, "\n(Run via: python3 -m veritx_dse.cli ...)")


def cmd_trace_validate(ctx: Ctx, args):
    trace = _resolve_path(args.trace)
    result = validate_trace(trace)

    if not ctx.json_mode:
        banner(ctx, f"Validating: {Path(trace).name}")

    if ctx.verbosity > 0 and not ctx.json_mode:
        emit(ctx, f"  Format:       {'✓ VALID' if result.valid else '✗ INVALID'}")
        emit(ctx, f"  Packets:      {result.packets:,}")
        emit(ctx, f"  Sources:      {result.sources} unique (IDs 0–{max(result.sizes) if result.sizes else 0})")
        emit(ctx, f"  Classes:      {result.classes}")
        emit(ctx, f"  Sizes:        {result.sizes}")
        emit(ctx, f"  Time range:   [{result.time_range[0]}, {result.time_range[1]}] ({result.span:,} cycles)")
        emit(ctx, f"  Avg IR:       {result.injection_rate:.6f} pkts/cycle")
        emit(ctx, f"  Self-loops:   {result.self_loops}")
        if result.errors:
            emit(ctx, f"\n  \033[31mErrors ({len(result.errors)}):\033[0m")
            for e in result.errors[:10]:
                emit(ctx, f"    {e}")
        if result.warnings:
            emit(ctx, f"\n  \033[33mWarnings ({len(result.warnings)}):\033[0m")
            for w in result.warnings[:10]:
                emit(ctx, f"    {w}")
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
    emit(ctx, f"  File:         {info.file}")
    emit(ctx, f"  Size:         {info.file_size:,} bytes ({info.file_size // 1024}KB)")
    emit(ctx, f"  Packets:      {info.packets:,}")
    emit(ctx, f"  Sources:      {info.sources}")
    emit(ctx, f"  Classes:      {info.classes}")
    emit(ctx, f"  Time range:   [0, {info.max_cycle}] ({info.span:,} cycles)")
    emit(ctx, f"  Avg IR:       {info.ir:.6f} pkts/cycle")
    emit(ctx, f"  Bursts:       {len(info.bursts)} (gap>100c)")
    emit(ctx, f"  Avg burst:    {info.avg_burst_size:.0f} pkts")
    emit(ctx, f"  Max burst:    {info.max_burst_size} pkts")
    emit(ctx, f"  Avg gap:      {info.avg_gap:.0f} cycles")
    emit(ctx, f"  Top srcs:     {info.top_srcs}")
    emit(ctx, f"  Top dsts:     {info.top_dsts}")
    emit(ctx, f"  Profile:      {info.profile}")
    emit(ctx, f"  Burst IR:     {info.burst_ir:.2f} pkts/cycle (during max burst)")
    emit(ctx, f"  Burst mode:   {info.burst_mode}")


def cmd_trace_extract(ctx: Ctx, args):
    trace = _resolve_path(args.trace)
    if args.uniform:
        result = extract_uniform(trace, args.out)
    elif args.burst is not None:
        if args.burst < 1:
            fail(ctx, f"--burst needs N >= 1, got {args.burst}")
            return
        result = extract_burst(trace, args.burst, args.out)
    else:
        fail(ctx, "Specify --burst N or --uniform")
        return

    ok(ctx, f"Extracted {result.packets} packets → {result.output_file}")
    output(ctx, result.to_dict())


def cmd_trace_slice(ctx: Ctx, args):
    trace = _resolve_path(args.trace)
    if not Path(trace).exists():
        fail(ctx, f"Trace not found: {trace}")
        return
    keep = set(int(c) for c in args.classes.split(","))
    result = slice_trace(trace, keep, args.out, renumber=args.renumber)
    ok(ctx, f"Slice: {result.kept} packets kept, {result.dropped} dropped → {result.output_file}")
    output(ctx, result.to_dict())


def cmd_trace_chakra(ctx: Ctx, args):
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        from chakra_to_dse import main as chakra_main
    except ImportError:
        fail(ctx, "chakra_to_dse module not found in veritx_dse/tools/")
        fail(ctx, "Run: git checkout -- veritx_dse/tools/chakra_to_dse.py")
        return

    try:
        et_path = Path(_resolve_path(args.et_dir))
    except ValueError as e:
        fail(ctx, f"trace input rejected: {e}")
        return
    if et_path.is_dir():
        txt_files = sorted(et_path.glob("*.txt"))
        et_files = list(et_path.glob("*.et"))
        if txt_files:
            trace_files = [str(f) for f in txt_files]
            log(ctx, f"Found {len(trace_files)} .txt files in {et_path.name}")
        elif et_files:
            # Chakra .et binary files — try ASTRA-sim converter (canonical
            # third_party layout; the old serving/ path died with the re-vendor)
            astra_bin = CHAKRA_TO_ET
            if astra_bin.exists():
                log(ctx, f"Found {len(et_files)} Chakra .et files, converting via ASTRA-sim...")
                import subprocess
                import tempfile
                with tempfile.TemporaryDirectory() as _conv_tmp:
                    for et_file in et_files:
                        # cwd=temp: chakra_to_et inherits astra-sim's default
                        # --logging-folder "log" (CmdLineParser.cc) and would
                        # otherwise create ./log/log.log in the CWD — which,
                        # with cwd=REPO, litters the repo root.
                        r = subprocess.run([str(astra_bin), str(et_file)],
                                           capture_output=True, text=True,
                                           timeout=60, cwd=_conv_tmp)
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
    if getattr(args, "pkt_flits", None):
        sys.argv.extend(["--pkt-flits", str(args.pkt_flits)])
    chakra_main()
    ok(ctx, f"Trace: {args.out} ({Path(args.out).stat().st_size // 1024}KB)")


def cmd_trace_model(ctx: Ctx, args):
    model_path = Path(_resolve_path(args.model))
    if not model_path.exists():
        fail(ctx, f"Traffic model not found: {args.model} (resolved: {model_path})")
        return
    from ..simulation.model_to_trace import LoweringError, main as model_main
    log(ctx, f"Converting traffic model {model_path.name}")
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sys.argv = ["model_to_trace", "--traffic-model", str(model_path),
                "--nodes", str(args.nodes), "--out", str(args.out)]
    try:
        model_main()
    except LoweringError as e:
        # PR C fail-closed: unsupported/corrupt workload semantics refuse to
        # lower — the command fails, no trace sidecar is produced.
        fail(ctx, f"Lowering refused: {e}")
        return
    ok(ctx, f"Trace: {args.out} ({Path(args.out).stat().st_size // 1024}KB)")


def cmd_trace_hpc(ctx: Ctx, args):
    """Install a trace into the runs tree: explicit path, or a name looked
    up in the built-in trace library (dse/archive/inputs/traces)."""
    import shutil
    src = None
    try:
        cand = Path(_resolve_path(args.trace_file))
        if cand.is_file():
            src = cand
    except ValueError:
        src = None
    if src is None:
        src = Path(args.trace_file)
    if not src.is_file():
        lib = DSE_DIR / "archive" / "inputs" / "traces"
        name = args.trace_file if args.trace_file.endswith(".trace") \
            else f"{args.trace_file}.trace"
        candidate = lib / name
        if candidate.is_file():
            src = candidate
        else:
            fail(ctx, f"Trace not found: {args.trace_file}")
            available = sorted(p.name for p in lib.glob("*.trace"))
            if available:
                log(ctx, f"Trace library ({lib.name}/): {', '.join(available)}")
            return
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, out)
    ok(ctx, f"Trace: {out}")


def cmd_synthesize_bo(ctx: Ctx, args):
    if not _require_file(ctx, args.traffic, "traffic trace", kind="trace"):
        return
    if args.iters < 1:
        fail(ctx, f"--iters must be >= 1, got {args.iters}")
        return
    log(ctx, f"BO synthesis: {args.iters} iterations, {args.nodes} nodes")
    cmd = [sys.executable, str(Path(__file__).parent.parent / "synthesis" / "bo_synthesizer.py"),
           "--traffic", _resolve_path(args.traffic), "--nodes", str(args.nodes),
           "--iters", str(args.iters), "--scorer", args.scorer]
    if args.seed:
        cmd.extend(["--seed", str(args.seed)])
    import subprocess
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=_eff_timeout(args, 600), cwd=str(REPO))
    if r.returncode != 0:
        tail = " | ".join(l.strip() for l in (r.stderr or r.stdout).strip().splitlines()[-6:]
                          if l.strip())
        # The synthesizer is a pure library (no sub-processes) — stdout *is*
        # its diagnostics. Surface the traceback, not just the exit code.
        # The synthesizer is a pure library (no sub-processes) — stdout *is*
        # its diagnostics. Surface the traceback if one exists, else a short tail.
        if "Traceback " in (r.stderr or r.stdout):
            body = (r.stderr or r.stdout or "").strip()
            fail(ctx, f"BO synthesis failed (exit {r.returncode}):\n" +
                 "\n".join(line.strip() for line in body.splitlines()[-10:] if line.strip()))
        else:
            tail = " | ".join(l.strip() for l in (r.stderr or r.stdout).strip().splitlines()[-6:]
                              if l.strip())
            fail(ctx, f"BO synthesis failed (exit {r.returncode}): {tail}")

    results_path = SYNTH_DIR / f"bo_results_N{args.nodes}.json"
    if not results_path.exists():
        # Legacy second home (pre-unification repo runs/); pickers scan both.
        _legacy = RUNS_DIR / "booksim" / f"bo_results_N{args.nodes}.json"
        if _legacy.exists():
            results_path = _legacy
    if results_path.exists():
        try:
            data = json.loads(results_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            fail(ctx, f"Failed to parse results: {e}")
            return
        ok(ctx, f"Best analytical: {data.get('best_latency', '?')}c")
        ok(ctx, f"BookSim validated: {data.get('booksim_latency', '?')}c")
        ok(ctx, f"Results: {results_path}")


def cmd_synthesize_iterative(ctx: Ctx, args):
    if not _require_file(ctx, args.trace, "trace", kind="trace"):
        return
    if args.steps < 1:
        fail(ctx, f"--steps must be >= 1, got {args.steps}")
        return
    trace = _resolve_path(args.trace)
    log(ctx, f"Iterative synthesis ({args.method}, {args.steps} steps)")
    cmd = [sys.executable, str(Path(__file__).parent.parent / "synthesis" / "iterative_synthesizer.py"),
           "--trace", str(Path(trace).resolve()), "--method", args.method,
           "--steps", str(args.steps), "--max-edges", str(args.max_edges),
           "--out", args.out or str(SYNTH_DIR / f"{args.method}_standalone.anynet")]
    if args.seed_anynet:
        try:
            seed_anynet = _resolve_path(args.seed_anynet)
        except ValueError as e:
            fail(ctx, f"--seed-anynet rejected: {e}")
            return
        if not Path(seed_anynet).exists():
            fail(ctx, f"--seed-anynet not found: {args.seed_anynet} (resolved: {seed_anynet})")
            return
        cmd.extend(["--seed-anynet", seed_anynet])
    if args.horizon is not None:
        cmd.extend(["--horizon", str(args.horizon)])
    if args.branch is not None:
        cmd.extend(["--branch", str(args.branch)])
    if args.group is not None:
        cmd.extend(["--group", str(args.group)])
    import subprocess
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=_eff_timeout(args, 600), cwd=str(REPO))
    if r.returncode != 0:
        body = (r.stderr or r.stdout or "").strip()
        if "Traceback " in body:
            fail(ctx, f"iterative synthesis failed (exit {r.returncode}):\n" +
                 "\n".join(line.strip() for line in body.splitlines()[-10:] if line.strip()))
        else:
            tail = " | ".join(l.strip() for l in body.splitlines()[-3:] if l.strip())
            fail(ctx, f"iterative synthesis failed (exit {r.returncode}): {tail}")
        return
    for line in r.stdout.splitlines():
        if "Final:" in line:
            ok(ctx, line.strip())
            break
    else:
        fail(ctx, "synthesizer finished but printed no Final line — "
                  "no topology was certified")


def cmd_synthesize_compile(ctx: Ctx, args):
    """Phase 13: requirements-driven fabric compiler.

    Declared E2 requirements become hard constraints over a candidate set
    (from a synthesis results file). Verdicts: FEASIBLE (with Pareto
    evidence) or NO_FEASIBLE_DESIGN (with violation + relaxation evidence).
    Requirements are never silently relaxed; unmeasurable constraints fail
    closed. Both verdicts are real outcomes — only setup errors fail().
    """
    import json as _json

    from veritx_dse.core.errors import VeritXError
    from veritx_dse.synthesis.bridge import compile_from_results_file
    from veritx_dse.synthesis.compiler import (
        CompilerRequest, InvalidCompilerRequest,
    )

    # Parse requirements FIRST: an incoherent spec is deterministic and
    # free to check — it must be reported even when files are also missing,
    # and must never cost an evaluation (fail-fast pattern, cmd_serve ref).
    try:
        request_kwargs = {
            "requirements": _json.loads(args.requirements),
            "search_budget": {"requested_evaluations": args.max_evals},
            "seed_policy": {"seed": args.seed, "replication": 1},
        }
        CompilerRequest(candidates=[{"name": "preflight"}],
                        **{k: v for k, v in request_kwargs.items()})
    except (InvalidCompilerRequest, _json.JSONDecodeError) as e:
        fail(ctx, f"invalid --requirements: {e}")
        return

    if not _require_file(ctx, args.results, "synthesis results", kind=None):
        return
    if not _require_file(ctx, args.trace, "trace", kind="trace"):
        return

    out_path = (SYNTH_DIR / f"compile_verdict_N{args.nodes}.json") \
        if args.out is None else Path(_resolve_path(args.out))
    try:
        out = compile_from_results_file(
            _resolve_path(args.results), request_kwargs,
            trace_path=str(_resolve_path(args.trace)),
            seed=args.seed, timeout=_eff_timeout(args, 600),
            out_path=out_path,
        )
    except InvalidCompilerRequest as e:
        fail(ctx, f"compiler request invalid: {e}")
        return
    except VeritXError as e:
        fail(ctx, f"compiler cannot evaluate candidates: {e}")
        return

    # Report — NO_FEASIBLE_DESIGN is a real verdict (evidence written),
    # not a command failure; only setup/environment errors fail() above.
    scope = out["scope"]
    ok(ctx, f"verdict: {out['verdict']} "
            f"({scope['candidates']} candidates: {scope['feasible']} feasible, "
            f"{scope['constraint_violation']} violated, "
            f"{scope['evaluation_failed']} failed, "
            f"{scope['constraint_unmeasurable']} unmeasurable, "
            f"{scope['pruned']} pruned)")
    if out["verdict"] == "FEASIBLE":
        ok(ctx, f"pareto front: {', '.join(out['pareto']['front'])}")
    else:
        for v in out["violated_constraints"]:
            ok(ctx, f"violated: {v['constraint']['kind']}"
                    f"[{v['constraint']['qos_class']}]"
                    f" bound={v['constraint']['bound']}"
                    f" best_measured={v.get('best_measured')}")
        relax = out["relaxation_information"]
        if relax.get("minimal_ceiling_admitting_best") is not None:
            ok(ctx, "relaxation: tightest ceiling admitting the best "
                    f"measured candidate = {relax['minimal_ceiling_admitting_best']}c")
    ok(ctx, f"evidence: {out.get('output', out_path)}")


def _coerce_set_value(v: str):
    """Coerce a --set value: int > float > bool > raw string.

    BookSim config lines take bare tokens (uniform, islip), so strings
    stay unquoted; "true/false" map to 1/0 for BookSim int fields."""
    s = v.strip()
    if s.lower() in ("true", "yes", "on"):
        return 1
    if s.lower() in ("false", "no", "off"):
        return 0
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _parse_set(ctx, entries) -> dict:
    """Parse repeatable `--set key=value` flags into a BookSim overrides dict.

    Entries whose key is dotted with a system/network/memory prefix
    (ASTRA config overlay) are skipped here — see _split_astra_sets."""
    out = {}
    # CLI-flag spellings map to BookSim keys (so `--set vc-buf=8` and the
    # t3 prompt example `vcs=4,vc-buf=8` land on num_vcs/vc_buf_size, not on
    # unknown `vc-buf` lines BookSim would choke on or ignore).
    _aliases = {"vcs": "num_vcs", "vc-buf": "vc_buf_size",
                "sample-period": "sample_period", "max-samples": "max_samples"}
    for e in entries or []:
        if "=" not in e:
            fail(ctx, f"--set expects key=value, got: {e!r}")
            return {}
        k, v = e.split("=", 1)
        k = k.strip()
        if not k:
            fail(ctx, f"--set expects key=value, got: {e!r}")
            return {}
        if "." in k and k.split(".")[0] in ("system", "network", "memory"):
            continue  # ASTRA overlay key; handled by _split_astra_sets
        k = _aliases.get(k, k).replace("-", "_")
        out[k] = _coerce_set_value(v)
    return out


def _split_astra_sets(ctx, entries) -> dict:
    """Pull `system./network./memory.`-prefixed --set entries for ASTRA overlay.

    Returns {"system": {...}, "network": {...}, "memory": {...}} with
    dotted sub-paths preserved (e.g. network.topology.Name). Malformed
    entries fail loudly — a typo'd overlay key must never vanish silently."""
    out = {"system": {}, "network": {}, "memory": {}}
    for e in entries or []:
        if "=" not in e:
            fail(ctx, f"--set expects key=value, got: {e!r}")
            return {}
        k, v = e.split("=", 1)
        k = k.strip()
        parts = k.split(".")
        if len(parts) >= 2 and parts[0] in out:
            if not ".".join(parts[1:]).strip():
                fail(ctx, f"--set has empty overlay path: {e!r}")
                return {}
            out[parts[0]] [".".join(parts[1:])] = _coerce_set_value(v)
    return {k: v for k, v in out.items() if v}


def _reject_astra_sets(ctx, entries, where: str) -> bool:
    """Refuse system./network./memory. keys where no ASTRA leg exists.

    _parse_set silently skips those keys (they belong to evaluate astra);
    on compare/sweep that silence would eat a typo'd BookSim key without a
    trace. Returns True when it failed."""
    bad = [e for e in entries or []
           if "=" in e and e.split("=", 1)[0].strip().split(".")[0]
           in ("system", "network", "memory")]
    if bad:
        fail(ctx, f"{where} has no ASTRA leg — {bad} only apply to "
                  f"`veritx evaluate astra --set`; refusing to silently drop them")
        return True
    return False


def _sim_overrides(args, names=("vcs", "vc_buf", "sample_period",
                               "max_samples")) -> dict:
    """Collect explicitly-set BookSim knobs into a build_config overrides dict.

    Only non-None flags are forwarded, so topology-derived guards (e.g. the
    GEC/MECS num_vcs auto-raise) and trace-span sample periods survive
    unless the user deliberately overrides them.
    """
    key_map = {"vcs": "num_vcs", "vc_buf": "vc_buf_size",
               "sample_period": "sample_period", "max_samples": "max_samples"}
    return {key_map[n]: getattr(args, n) for n in names
            if getattr(args, n, None) is not None}


def cmd_evaluate_booksim(ctx: Ctx, args):
    from veritx_dse.model.presets import lookup_topo, Topology
    if args.k < 2:
        fail(ctx, f"k must be >= 2, got {args.k}")
        return
    if not _require_file(ctx, args.trace, "trace", kind="trace"):
        return
    trace = _resolve_path(args.trace)
    stats = detect_trace_stats(trace)
    if stats.num_packets == 0:
        fail(ctx, f"trace has no parseable packets: {args.trace} — "
                  "check it with: veritx trace validate <trace>")
        return

    # Resolve topology: try preset lookup first, then build from args
    preset = lookup_topo(args.topo)
    if preset is None and not args.routing:
        # Unknown backend: the old path fed the raw string to BookSim as a
        # topology name and died inside the sim ("Unknown topology",
        # exit -11). Name the choices instead.
        anynet_hint = " (for .anynet files use: veritx evaluate anynet --topo …)" \
            if Path(args.topo).suffix == ".anynet" else ""
        fail(ctx, f"unknown topology '{args.topo}'{anynet_hint} — try a preset "
                  "(mesh_8x8, torus_8x8, flatfly_64, …) or pass --routing to "
                  "force a BookSim backend name")
        return
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

    config = build_config(topo, trace, sample_period=args.sample_period, seed=ctx.seed,
                          overrides={**_sim_overrides(args), **_parse_set(ctx, getattr(args, "set", None))})
    if ctx.failed:
        return

    result = run_booksim(ctx, config, repo_root=REPO, timeout=_eff_timeout(args, 120))
    result["topology"] = topo.name
    result["trace"] = args.trace
    result["routing"] = topo.routing
    result["config"] = config
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

    out_dir = new_run_dir("evaluate", ctx.seed)
    out_path = out_dir / f"eval_{topo.backend}{args.k}.json"
    out_path.write_text(json.dumps(result, indent=2))
    ok(ctx, f"Saved: {out_path}")
    output(ctx, result)


def cmd_evaluate_anynet(ctx: Ctx, args):
    if not _require_file(ctx, args.topo, "topology", kind="anynet"):
        return
    if not _require_file(ctx, args.trace, "trace", kind="trace"):
        return
    topo_path = _resolve_path(args.topo)
    trace = _resolve_path(args.trace)
    n_nodes, n_edges = count_anynet_edges(topo_path)
    if n_nodes == 0:
        if not Path(topo_path).is_file():
            fail(ctx, f"anynet file not found: {args.topo} (resolved: {topo_path})")
        else:
            fail(ctx, f"No routers parsed from {args.topo} (resolved: {topo_path})")
            fail(ctx, "File exists but parses to nothing — not a valid .anynet file")
        return

    # Connectivity check — disconnected topologies cause BookSim to hang.
    # (n_nodes > 0 here, so the helper cannot return the empty-graph case.)
    _conn, _, _nun0 = check_anynet_connected(topo_path)
    if not _conn:
        fail(ctx, f"Disconnected topology: {_nun0} nodes unreachable from node 0")
        fail(ctx, "BookSim will hang on disconnected graphs — fix the .anynet file")
        return

    topo = make_anynet_topo(topo_path)
    log(ctx, f"BookSim anynet topo={Path(args.topo).name} trace={Path(args.trace).name} "
        f"({n_nodes} nodes, {n_edges} edges)")

    config = build_config(topo, trace, sample_period=args.sample_period, seed=ctx.seed,
                          overrides={**_sim_overrides(args, names=("vcs", "vc_buf", "sample_period")),
                                     **_parse_set(ctx, getattr(args, "set", None))})
    if ctx.failed:
        return
    result = run_booksim(ctx, config, repo_root=REPO, timeout=_eff_timeout(args, 120))
    result["topology"] = topo.name
    result["trace"] = args.trace
    result["config"] = config
    result["topology"] = topo.name
    result["trace"] = args.trace
    result["nodes"] = n_nodes
    result["edges"] = n_edges
    result["seed"] = ctx.seed

    ok(ctx, f"Latency: {result['latency']:.2f}c | Hops: {result.get('hops', '?')}")

    out_dir = new_run_dir("evaluate", ctx.seed)
    out_path = out_dir / f"eval_{topo.name}.json"
    out_path.write_text(json.dumps(result, indent=2))
    ok(ctx, f"Saved: {out_path}")
    output(ctx, result)


def _parse_astra_cycles(stdout: str) -> dict:
    """Extract per-rank completion cycles from frontend stdout.

    Lines look like:
      [workload] sys[3] finished, 50310 cycles, exposed communication ...
    Returns {rank: cycles}. Empty dict when nothing parseable (the caller,
    not this helper, decides what that means).
    """
    import re
    per_rank: dict = {}
    for line in stdout.splitlines():
        m = re.search(r"sys\[(\d+)\] finished, (\d+) cycles", line)
        if m:
            per_rank[int(m.group(1))] = int(m.group(2))
    return per_rank


def _parse_astra_exposed(stdout: str) -> dict:
    """Extract per-rank exposed communication cycles from frontend stdout.

    Lines look like:
      [workload] sys[3] finished, 50310 cycles, exposed communication 30310 cycles.
    Returns {rank: exposed}; ranks whose line lacks the field are omitted.
    Pairs with _parse_astra_cycles (same lines, second number).
    """
    import re
    exposed: dict = {}
    for line in stdout.splitlines():
        m = re.search(
            r"sys\[(\d+)\] finished, (\d+) cycles, exposed communication (\d+) cycles",
            line)
        if m:
            exposed[int(m.group(1))] = int(m.group(3))
    return exposed


def _parse_astra_plat(stdout: str) -> dict | None:
    """Parse the frontend's [plat] per-packet summary (last line wins).

    Line shape (emitted by AstraSim_BookSim2 at end of a round):
      [plat] packets=480 avg=23.375 min=19 p50=19 p95=44 p99=44 max=44
             hops_avg=2.875 hops_min=2 hops_max=7
    Values are exact retire-time measurements, not estimates. Returns None
    when the binary predates the feature — the caller reports absence
    honestly rather than fabricating numbers.
    """
    import re
    result = None
    for line in stdout.splitlines():
        if "[plat]" in line:
            fields = dict(re.findall(r"(\w+)=([0-9.eE+-]+)", line))
            if fields:
                result = fields
    return result


def cmd_evaluate_astra(ctx: Ctx, args):
    if not ASTRA_BS_BIN.exists():
        fail(ctx, f"ASTRA-sim BookSim2 binary not found: {ASTRA_BS_BIN}")
        return

    # Workload-path convention (B7): the frontend resolves per-rank workloads
    # as <base>.<rank>.et and treats missing ones as idle (0 cycles, rc=0).
    # A bare base file with no .0.et sibling is almost certainly a mistake;
    # fail fast instead of reporting a silent all-idle "success".
    ets_base = _resolve_path(args.ets)
    if not Path(ets_base).is_file():
        fail(ctx, f"--ets must be an existing workload file, got: {args.ets} "
                   f"(resolved: {ets_base})")
        return
    if not Path(ets_base + ".0.et").exists():
        fail(ctx, f"No per-rank workloads found: expected {ets_base}.<rank>.et "
                   f"(e.g. {Path(ets_base).name}.0.et). The frontend idles ranks "
                   f"without them, so refusing a silent 0-cycle run.")
        return

    log(ctx, f"ASTRA-sim eval: ets={args.ets}")
    import subprocess
    overlay = _split_astra_sets(ctx, getattr(args, "set", None))
    if ctx.failed:
        return
    overlay_dir = None
    sys_cfg, net_cfg, mem_cfg = args.system_config, args.network_config, args.memory_config
    if overlay:
        overlay_dir = new_run_dir("evaluate-astra", ctx.seed)
        cfgs = _apply_astra_overlay(args, overlay, overlay_dir, ctx)
        if cfgs is None:  # _apply_astra_overlay already failed
            return
        sys_cfg, net_cfg, mem_cfg = cfgs
    cmd = [str(ASTRA_BS_BIN),
           "--workload-configuration", ets_base,
           "--system-configuration", sys_cfg,
           "--network-configuration", net_cfg,
           "--remote-memory-configuration", mem_cfg,
           # Embedded mode owns injection: template cfgs carry standalone-style
           # injection_rate (uniform), which self-injects infinite synthetic
           # traffic and spins the run forever. Cfgs stay untouched.
           "--booksim2-extra=injection_rate=0.0",
           "--logging-configuration", "empty",
           "--logging-folder", str(RUNS_DIR / "astra")]
    try:
        sim_timeout = _eff_timeout(args, 300)
        # stdin=DEVNULL: after quiescence the binary prints Waiting and reads
        # the interactive protocol from stdin; EOF exits cleanly. Inheriting a
        # terminal here hangs forever (the historical TimeoutExpired bug).
        proc = subprocess.run(cmd, timeout=sim_timeout, cwd=str(REPO),
                              stdin=subprocess.DEVNULL,
                              capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        fail(ctx, f"ASTRA-sim timed out after {sim_timeout}s")
        return
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.splitlines()[-5:])
        fail(ctx, f"ASTRA-sim failed (exit {proc.returncode}): {tail}")
        return
    per_rank = _parse_astra_cycles(proc.stdout)
    if not per_rank:
        fail(ctx, "ASTRA-sim exited 0 but emitted no parseable "
                   "'sys[i] finished' lines — refusing to report success "
                   "without evidence.")
        return
    # Exposed communication of the slowest rank: that rank gates the
    # collective, so its exposed time is the honest network-attributable
    # number. (Per-packet latency/hops are never emitted in embedded mode —
    # BookSim's DisplayStats doesn't run — so they stay absent here too.)
    exposed = _parse_astra_exposed(proc.stdout)
    slowest = max(per_rank, key=per_rank.get)
    exposed_comm = exposed.get(slowest)
    plat = _parse_astra_plat(proc.stdout)
    result = {
        "backend": "astra-booksim2",
        "ets": args.ets,
        "system_config": sys_cfg,
        "network_config": net_cfg,
        "memory_config": mem_cfg,
        "config_overlay": overlay,
        "cycles": max(per_rank.values()),
        "per_rank_cycles": per_rank,
        "num_ranks": len(per_rank),
        "exposed_comm_cycles": exposed_comm,
        "plat_stats": plat,
        "status": "ok",
    }
    ok(ctx, f"ASTRA-sim: {result['cycles']:,}c over {result['num_ranks']} ranks")
    out_dir = overlay_dir or new_run_dir("evaluate-astra", ctx.seed)
    out_path = out_dir / f"eval_{Path(args.ets).stem}.json"
    out_path.write_text(json.dumps(result, indent=2))
    ok(ctx, f"Saved: {out_path}")
    output(ctx, result)


# ── topology (TopologyIR v0) ─────────────────────────────────────────────

def _load_topology_ir(ctx: Ctx, ir_path: str):
    """Load + validate a TopologyIR file, or fail with the reason."""
    from veritx_dse.model.topology_ir import load as _ir_load
    try:
        return _ir_load(_resolve_path(ir_path))
    except Exception as e:  # TopologyError / OSError — all user-facing
        fail(ctx, f"topology: {e}")
        return None


def cmd_topology_render(ctx: Ctx, args):
    from veritx_dse.model.topology_ir import (
        expand, to_anynet, to_booksim_cfg, to_analytical_yml, render_ascii,
    )
    ir = _load_topology_ir(ctx, args.ir)
    if ir is None:
        return
    fmt = args.format
    m = expand(ir)
    sidecar = None
    if fmt == "ascii":
        text = render_ascii(ir, m)
    elif fmt == "anynet":
        text = to_anynet(ir, m)
    elif fmt == "yml":
        text = to_analytical_yml(ir)
    elif fmt == "json":
        import json as _json
        text = _json.dumps({"name": ir.name, "kind": ir.kind,
                            "nodes": m.nodes,
                            "edges": [list(e) for e in m.edges]}, indent=2) + "\n"
    elif fmt == "cfg":
        if ir.kind in ("star", "switch", "anynet", "custom"):
            if not args.out:
                fail(ctx, f"topology render: format cfg for kind {ir.kind!r} "
                            "needs --out (a links sidecar file is required)")
                return
            sidecar_path = str(Path(args.out).with_name(
                Path(args.out).stem + ".anynet").resolve())
            sidecar = to_anynet(ir, m)
            text = to_booksim_cfg(ir, m, network_file=sidecar_path)
        else:
            text = to_booksim_cfg(ir, m)
    else:
        fail(ctx, f"topology render: unknown format {fmt!r}")
        return
    if args.out:
        out = Path(args.out)
        out.write_text(text)
        if sidecar is not None:
            out.with_name(out.stem + ".anynet").write_text(sidecar)
        ok(ctx, f"Rendered {ir.name} [{fmt}] → {out}")
        return
    emit(ctx, text, end="")


def cmd_topology_stats(ctx: Ctx, args):
    from veritx_dse.model.topology_ir import expand, stats as _ir_stats
    ir = _load_topology_ir(ctx, args.ir)
    if ir is None:
        return
    s = _ir_stats(ir, expand(ir))
    if args.out:
        Path(args.out).write_text(json.dumps(s, indent=2))
        ok(ctx, f"Stats for {ir.name} → {args.out}")
        return
    emit(ctx, f"{s['name']} [{s['kind']}] nodes={s['nodes']} edges={s['edges']} "
                f"avg_degree={s['avg_degree']} diameter={s['diameter']} "
                f"connected={s['connected']}")
    emit(ctx, f"  degree histogram: {s['degree_histogram']}")


def _find_analytical_bin():
    """Resolve the congestion-aware AnalyticalAstra frontend, or None."""
    import os as _os
    env = _os.environ.get("ANALYTICAL_BIN")
    if env and Path(env).is_file():
        return env
    cands = [
        REPO / "third_party" / "astra-sim" / "astra-sim" / "build"
        / "astra_analytical" / "build" / "AnalyticalAstra" / "bin"
        / "AnalyticalAstra",
        REPO / "third_party" / "llmservingsim" / "astra-sim" / "astra-sim"
        / "build" / "astra_analytical" / "build" / "AnalyticalAstra" / "bin"
        / "AnalyticalAstra",
    ]
    for c in cands:
        if c.is_file():
            return str(c)
    return None


def cmd_topology_diff(ctx: Ctx, args):
    """Same IR through BookSim + analytical legs → divergence report.

    Leg A reuses the evaluate-astra invocation contract (injection_rate=0.0
    override, DEVNULL stdin, parseable-lines-or-fail). Leg B runs the
    congestion-aware AnalyticalAstra frontend on the translated yml.
    Analytical yml dims are single-dim only (mirrors serving's aware-engine
    limit); multi-dim IR fails loud here.
    """
    from veritx_dse.model import topology_ir as _tir
    ir = _load_topology_ir(ctx, args.ir)
    if ir is None:
        return
    if ir.dims is not None and len(ir.dims) > 1:
        fail(ctx, "topology diff: analytical leg is single-dim only "
                    "(congestion-aware engine limit, mirrors serving); "
                    "give single-dim dims for multi-dim IR")
        return
    ets_base = _resolve_path(args.ets)
    if not Path(ets_base).is_file():
        # Prefix form (microbenchmarks ship only <base>.<rank>.et, no base
        # file): accept when rank files exist — the per-rank loop below is
        # the real coverage gate.
        if not Path(f"{ets_base}.0.et").exists():
            fail(ctx, f"--ets must be an existing workload file or prefix, got: {args.ets}")
            return
    missing = [r for r in range(ir.nodes)
               if not Path(f"{ets_base}.{r}.et").exists()]
    if missing:
        fail(ctx, f"Missing per-rank workloads for ranks {missing[:8]}" 
                    f"{'…' if len(missing) > 8 else ''} "
                    f"({len(missing)}/{ir.nodes} missing; expected "
                    f"{Path(ets_base).name}.<rank>.et) — refusing a skewed diff.")
        return
    if not ASTRA_BS_BIN.exists():
        fail(ctx, f"ASTRA-sim BookSim2 binary not found: {ASTRA_BS_BIN}")
        return
    ana_bin = _find_analytical_bin()
    if ana_bin is None:
        fail(ctx, "AnalyticalAstra frontend not found (ANALYTICAL_BIN unset "
                    "and no build under third_party/astra-sim) — refusing a "
                    "one-legged diff.")
        return

    out_dir = new_run_dir("topology-diff", ctx.seed)
    (out_dir / "ir.json").write_text(Path(_resolve_path(args.ir)).read_text())
    m = _tir.expand(ir)
    cfg_path = out_dir / "topo.cfg"
    if ir.kind in ("star", "switch", "anynet", "custom"):
        links_path = out_dir / "topo.anynet"
        links_path.write_text(_tir.to_anynet(ir, m))
        cfg_path.write_text(_tir.to_booksim_cfg(
            ir, m, network_file=str(links_path.resolve())))
    else:
        cfg_path.write_text(_tir.to_booksim_cfg(ir, m))
    try:
        yml_path = out_dir / "topo.yml"
        yml_path.write_text(_tir.to_analytical_yml(ir))
    except Exception as e:
        fail(ctx, f"topology diff: {e}")
        return

    # Leg-A configs via the adapter (same files run_astrasim produces).
    try:
        from ..simulation.astrasim_adapter import prepare_astrasim_config_dir
    except ImportError as e:
        fail(ctx, f"topology diff: cannot import astrasim_adapter: {e}")
        return
    leg_a_dir = out_dir / "leg_booksim"
    try:
        cfg_info = prepare_astrasim_config_dir(
            cfg_path, leg_a_dir,
            spec={"model_name": ir.name, "tp_degree": 1, "pp_degree": 1})
    except Exception as e:
        fail(ctx, f"topology diff: adapter failed on translated cfg: {e}")
        return
    if cfg_info.get("total_nodes") != ir.nodes:
        fail(ctx, f"topology diff: adapter counted "
                    f"{cfg_info.get('total_nodes')} nodes for IR with {ir.nodes} — "
                    "refusing to simulate the wrong machine.")
        return
    sys_cfg = _resolve_path(args.system_config) if args.system_config else str(leg_a_dir / "system.json")
    mem_cfg = _resolve_path(args.memory_config) if args.memory_config else str(leg_a_dir / "memory.json")

    import subprocess
    flit_bytes = args.booksim_flit_bytes
    cmd_a = [str(ASTRA_BS_BIN),
             "--workload-configuration", ets_base,
             "--system-configuration", sys_cfg,
             "--network-configuration", str(leg_a_dir / "network.json"),
             "--remote-memory-configuration", mem_cfg,
             f"--booksim2-flit-bytes={flit_bytes}",
             "--booksim2-extra=injection_rate=0.0",
             "--logging-configuration", "empty",
             "--logging-folder", str(RUNS_DIR / "astra")]
    try:
        proc_a = subprocess.run(cmd_a, timeout=_eff_timeout(args, 300),
                                cwd=str(REPO), stdin=subprocess.DEVNULL,
                                capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        fail(ctx, "topology diff: booksim leg timed out")
        return
    if proc_a.returncode != 0:
        tail = "\n".join(proc_a.stderr.splitlines()[-5:])
        fail(ctx, f"topology diff: booksim leg failed (exit {proc_a.returncode}): {tail}")
        return
    per_rank_a = _parse_astra_cycles(proc_a.stdout)
    if not per_rank_a:
        fail(ctx, "topology diff: booksim leg exited 0 with no parseable "
                    "'sys[i] finished' lines.")
        return
    cycles_a = max(per_rank_a.values())
    plat_a = _parse_astra_plat(proc_a.stdout)

    cmd_b = [ana_bin,
             "--workload-configuration", ets_base,
             "--system-configuration", sys_cfg,
             "--network-configuration", str(yml_path),
             "--remote-memory-configuration", mem_cfg,
             "--logging-configuration", "empty",
             # AnalyticalAstra's CmdLineParser also defaults --logging-folder
             # to relative "log/" — same repo-litter mechanism as chakra_to_et.
             "--logging-folder", str(RUNS_DIR / "astra")]
    try:
        proc_b = subprocess.run(cmd_b, timeout=_eff_timeout(args, 300),
                                cwd=str(REPO), stdin=subprocess.DEVNULL,
                                capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        fail(ctx, "topology diff: analytical leg timed out")
        return
    if proc_b.returncode != 0:
        tail = "\n".join((proc_b.stderr + proc_b.stdout).splitlines()[-5:])
        fail(ctx, f"topology diff: analytical leg failed (exit {proc_b.returncode}): {tail}")
        return
    per_rank_b = _parse_astra_cycles(proc_b.stdout)
    if not per_rank_b:
        fail(ctx, "topology diff: analytical leg exited 0 with no parseable "
                    "'sys[i] finished' lines.")
        return
    cycles_b = max(per_rank_b.values())

    divergence = _tir.divergence_report(cycles_a, cycles_b)
    result = {
        "ir": ir.name,
        "kind": ir.kind,
        "nodes": ir.nodes,
        "ets": args.ets,
        "booksim_leg": {"cycles": cycles_a, "num_ranks": len(per_rank_a),
                          "plat_stats": plat_a},
        "analytical_leg": {"cycles": cycles_b, "num_ranks": len(per_rank_b)},
        "divergence": divergence,
        "status": "ok",
    }
    out_path = out_dir / f"diff_{ir.name}.json"
    out_path.write_text(json.dumps(result, indent=2))
    ok(ctx, f"topology diff {ir.name}: booksim={cycles_a:,}c analytical={cycles_b:,}c "
              f"divergence={divergence['divergence_pct']}% ({divergence['verdict']})")
    ok(ctx, f"Saved: {out_path}")
    output(ctx, result)


def _set_dotted(doc: dict, path: str, value) -> None:
    """Set a dotted path inside nested dicts, creating levels as needed."""
    cur = doc
    *parents, leaf = path.split(".")
    for p in parents:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[leaf] = value


def _apply_astra_overlay(args, overlay: dict, out_dir, ctx):
    """Apply --set system./network./memory. entries to run-dir config copies.

    Returns (system_cfg, network_cfg, memory_cfg) paths to pass the binary.
    Templates are never mutated; the patched copies + overlay record live
    in out_dir for provenance."""
    import yaml
    loaders = {
        "system": (args.system_config, json.load, lambda d: json.dumps(d, indent=2)),
        "network": (args.network_config, yaml.safe_load, lambda d: yaml.safe_dump(d, default_flow_style=False)),
        "memory": (args.memory_config, json.load, lambda d: json.dumps(d, indent=2)),
    }
    patched = {}
    for section, sets in overlay.items():
        src, load, dump = loaders[section]
        try:
            src_resolved = _resolve_path(src)
            with open(src_resolved) as f:
                doc = load(f)
        except Exception as e:
            fail(ctx, f"ASTRA overlay: cannot load {section} config {src!r}: {e}")
            return None
        if not isinstance(doc, dict):
            fail(ctx, f"ASTRA overlay: {section} config {src!r} is not a mapping — refusing dotted sets")
            return None
        for path, val in sets.items():
            _set_dotted(doc, path, val)
        suffix = ".yml" if section == "network" else ".json"
        dest = out_dir / f"{section}.overlay{suffix}"
        dest.write_text(dump(doc))
        patched[section] = str(dest)
        log(ctx, f"ASTRA overlay [{section}]: {sets} → {dest.name}")
    return (patched.get("system", args.system_config),
            patched.get("network", args.network_config),
            patched.get("memory", args.memory_config))


def _write_anynet_cfg(anynet_path: Path, num_nodes: int, run_dir: Path) -> Path:
    """Write a minimal BookSim anynet cfg for the ASTRA backend.

    ASTRA's frontend re-parses the cfg through BookSim's config parser and
    embeds it as the network; injection is disabled at run time via
    --booksim2-extra=injection_rate=0.0 (embedded mode owns injection).
    """
    cfg = run_dir / "winner_astra.cfg"
    cfg.write_text(
        "topology = anynet;\n"
        "routing_function = min;\n"
        f"network_file = {anynet_path.resolve()};\n"
        "num_vcs = 4;\n"
        "vc_buf_size = 8;\n"
        # DIVERGENCE (deliberate, do not "fix" silently): every other
        # emitter uses packet_size = 8 (BASE_PARAMS, evaluator presets).
        # The ASTRA leg uses 64-flit packets to match Chakra collective
        # payload granularity in embedded mode. ASTRA-leg cycle counts are
        # therefore NOT comparable to BookSim-compare latencies packet for
        # packet — compare within a backend, or rerun with matching sizes.
        f"packet_size = {ASTRA_PACKET_SIZE};\n"
    )
    return cfg


def _run_astra_leg(ctx: Ctx, run_dir: Path, anynet_path: Path,
                   num_nodes: int, budget: int, msg_size_bytes: int = 16777216) -> dict:
    """ASTRA-sim leg: workload DAG replay on the synthesized topology.

    Regenerates a collective workload trace sized to the winner's node
    count, replicates it to every rank (the frontend resolves per-rank
    files <base>.<rank>.et; missing ranks silently idle), converts the
    anynet to ASTRA configs via simulation/astrasim_adapter.py, and runs the
    built astra_booksim2 binary. Returns a result dict for the manifest.
    """
    if not ASTRA_BS_BIN.exists():
        return {"error": f"astra_booksim2 binary not found: {ASTRA_BS_BIN}"}

    astra_dir = run_dir / "astra"
    astra_dir.mkdir(parents=True, exist_ok=True)

    # 1. Collective workload .et sized to the winner (all-reduce microbench).
    ets_base = astra_dir / "workload.et"
    try:
        sys.path.insert(0, str(T3_SCRIPTS_DIR))
        from generate_chakra_trace import ChakraTraceGenerator
        from pathlib import Path as _P
        gen = ChakraTraceGenerator()
        nodes = gen.build_collective_trace(comm_type="ALL_REDUCE",
                                           msg_size_bytes=msg_size_bytes)
        from generate_chakra_trace import save_chakra_trace
        res = save_chakra_trace(nodes, astra_dir, "workload")
    except Exception as e:
        return {"error": f"workload .et generation failed: {e}"}
    if not Path(res["et_binary"]).exists():
        return {"error": f"workload .et not written: {res['et_binary']}"}
    # Replicate to all ranks — the B7 convention: <base>.<rank>.et
    for rank in range(num_nodes):
        (astra_dir / f"workload.et.{rank}.et").write_bytes(
            Path(res["et_binary"]).read_bytes())

    # 2. ASTRA configs from the winner anynet (adapter copies + sanitizes).
    try:
        from ..simulation.astrasim_adapter import prepare_astrasim_config_dir
        cfg_path = _write_anynet_cfg(anynet_path, num_nodes, astra_dir)
        prepare_astrasim_config_dir(cfg_path, astra_dir,
                                    spec={"model_name": f"N{num_nodes}"})
    except Exception as e:
        return {"error": f"astrasim_adapter failed: {e}"}

    # 3. Run the built frontend (same invocation contract as
    #    cmd_evaluate_astra: embedded injection disabled, stdin=DEVNULL).
    import subprocess
    cmd = [str(ASTRA_BS_BIN),
           "--workload-configuration", str(ets_base),
           "--system-configuration", str(astra_dir / "system.json"),
           "--network-configuration", str(astra_dir / "network.json"),
           "--remote-memory-configuration", str(astra_dir / "memory.json"),
           "--booksim2-extra=injection_rate=0.0",
           "--logging-configuration", "empty",
           "--logging-folder", str(astra_dir / "logs")]
    # stdout/stderr go to files, not pipes: a chatty child would otherwise
    # fill the pipe buffer and deadlock while we "watch" it (the classic
    # Popen trap), and the files double as run-dir artifacts.
    out_path = astra_dir / "proc_stdout.log"
    err_path = astra_dir / "proc_stderr.log"
    try:
        with open(out_path, "w") as out_f, open(err_path, "w") as err_f:
            proc = subprocess.Popen(
                cmd, cwd=str(REPO), stdin=subprocess.DEVNULL,
                stdout=out_f, stderr=err_f, text=True)
            # Liveness instrumentation (redesign §28): init-then-stall with
            # quiet logs was undiagnosable from a bare timeout (run
            # 20260916_213026). Sample ASTRA's own log growth every 30s;
            # kill at the budget with evidence.
            import time as _t
            t0 = _t.monotonic()
            astra_log = astra_dir / "logs" / "log.log"
            last_size, last_change = -1, t0
            while True:
                remaining = budget - (_t.monotonic() - t0)
                if remaining <= 0:
                    proc.kill()
                    proc.wait()
                    return {
                        "error": f"astra-sim timed out after {budget}s",
                        "diagnostics": {
                            "astra_log_bytes_at_kill": last_size,
                            "log_quiet_for_s": round(_t.monotonic() - last_change, 1),
                            "stdout_tail": (out_path.read_text().splitlines()[-10:]
                                            if out_path.exists() else []),
                            "stderr_tail": (err_path.read_text().splitlines()[-10:]
                                            if err_path.exists() else []),
                            "hint": ("no sys[i] finished lines at kill. Measured: "
                                     "64-NPU ring all-reduce of this payload needs "
                                     "~12-40+ min sim wall time (64KiB => 147k "
                                     "cycles in ~4s); raise --timeout, shrink "
                                     "--astra-msg-mb, or run the leg standalone."),
                        },
                    }
                try:
                    rc = proc.wait(timeout=min(30, remaining))
                    break  # exited on its own
                except subprocess.TimeoutExpired:
                    pass
                size = astra_log.stat().st_size if astra_log.exists() else 0
                if size != last_size:
                    last_size, last_change = size, _t.monotonic()
    except Exception as e:
        return {"error": f"astra-sim failed: {e}"}
    out = out_path.read_text() if out_path.exists() else ""
    err = err_path.read_text() if err_path.exists() else ""
    if rc != 0:
        tail = "\n".join((err or "").splitlines()[-5:])
        return {"error": f"astra-sim exit {rc}: {tail}"}
    per_rank = _parse_astra_cycles(out or "")
    if not per_rank:
        return {"error": "astra-sim emitted no parseable sys[i] finished lines",
                "stdout_tail": (out or "").splitlines()[-10:]}
    exposed = _parse_astra_exposed(out or "")
    slowest = max(per_rank, key=per_rank.get)
    return {
        "backend": "astra-booksim2",
        "workload": "allreduce_microbench",
        # Payload provenance (redesign §19): ASTRA cycles are only
        # comparable across runs at the same all-reduce size.
        "msg_size_bytes": msg_size_bytes,
        "num_ranks": len(per_rank),
        "cycles": max(per_rank.values()),
        "exposed_comm_cycles": exposed.get(slowest),
        "per_rank_cycles": per_rank,
        "status": "ok",
    }


def _run_energy_leg(ctx: Ctx, run_dir: Path, budget: int) -> dict:
    """Timeloop energy leg: accelerator-side energy for the track workload.

    Topology-independent (it models the compute fabric, not the NoC), so it
    is recorded once per run and used with the BookSim hops/latency numbers
    for the energy-vs-latency view. Loader env comes from _timeloop_env:
    only the vendored binary gets LD_LIBRARY_PATH (see its docstring for
    the container-poisoning failure this fixes).
    """
    import subprocess
    tl_bin, tl_provenance = _pick_timeloop_mapper()
    tl_dir = DSE_DIR.parent / "timeloop"
    if not tl_bin.exists():
        return {"error": f"timeloop-mapper not found: {tl_bin}"}
    # Provenance in the manifest: which build of timeloop produced the
    # numbers (container ABI matches image; vendored host-built may not).
    need = ["mapper.yaml", "arch.yaml", "problem.yaml"]
    missing = [f for f in need if not (tl_dir / f).exists()]
    if missing:
        return {"error": f"timeloop configs missing: {missing}"}
    env = _timeloop_env(tl_provenance)
    cmd = [str(tl_bin), "mapper.yaml", "arch.yaml", "problem.yaml"]
    try:
        proc = subprocess.run(cmd, cwd=str(tl_dir), env=env,
                              timeout=budget, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        return {"error": f"timeloop-mapper timed out after {budget}s"}
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout).splitlines()[-5:])
        return {"error": f"timeloop-mapper exit {proc.returncode}: {tail}"}
    stats = tl_dir / "timeloop-mapper.stats.txt"
    if not stats.exists():
        return {"error": "timeloop ran but wrote no stats file"}
    try:
        sys.path.insert(0, str(T3_SCRIPTS_DIR))
        from energy_report import parse_energy
        parsed = parse_energy(stats.read_text())
    except Exception as e:
        return {"error": f"energy_report parse failed: {e}"}
    # Copy artifacts into the run dir for provenance.
    import shutil
    for name in ("timeloop-mapper.stats.txt", "timeloop-mapper.map+stats.xml"):
        src = tl_dir / name
        if src.exists():
            shutil.copy2(src, run_dir / name)
    return {**{k: v for k, v in parsed.items() if v is not None},
            "timeloop_binary": tl_provenance,
            "status": "ok"}


def _run_cert_leg(ctx: Ctx, run_dir: Path, trace_path: Path,
                  matrix_path: Path, anynet_path: Path, budget: int) -> dict:
    """Deadlock certificate leg: routing ILP + CDG acyclicity check.

    The flow-class cert (flow_certifier) answers 'are the traffic-model flows
    schedulable?'; this leg answers the structural question 'does the
    routing function on THIS topology have cyclic channel dependencies?' —
    the check custom anynets need before tape-out talk.
    """
    import subprocess
    out_prefix = str(run_dir / "deadlock_cert")
    # The ILP needs a square T over ALL topology nodes. Synthesizers may
    # return more routers than the trace touches (seed supersets), so embed
    # the trace matrix top-left and zero-fill — no traffic to/from extra
    # nodes, routing stays satisfiable, and the CDG covers every channel
    # the topology actually has.
    try:
        from ..synthesis.milp_topology_v2 import load_matrix
        T0 = load_matrix(str(matrix_path))
        n_topo = sum(1 for line in open(anynet_path)
                     if line.split()[:1] == ["router"])
        n = max(n_topo, len(T0))
        compat = run_dir / "matrix_compat.mat"
        rows = []
        for i in range(n):
            row = ([float(x) for x in T0[i]] if i < len(T0) else [0.0] * n)
            row += [0.0] * (n - len(row))
            rows.append(" ".join(f"{v:.6f}" for v in row))
        compat.write_text("\n".join(rows) + "\n")
    except Exception as e:
        return {"error": f"matrix/topology mismatch prep failed: {e}"}
    cmd = [sys.executable, str(SCRIPTS_DIR / "deadlock_routing.py"),
           "--anynet", str(anynet_path),
           "--matrix", str(compat),
           "--out", out_prefix,
           "--method", "booksim",
           "--timeout", str(max(5, budget))]
    # PR D: --method booksim makes the certificate evaluate the routes
    # BookSim's AnyNet actually executes (anynet.cpp Dijkstra + tie-break),
    # closing the cert-MCLB-vs-sim-Dijkstra mismatch. Weighted AnyNet is
    # rejected by the tool (exit 2) — the replica is hop-count-based, so a
    # weighted topology would certify route set A while BookSim runs B.
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=budget + 10, cwd=str(REPO))
    except subprocess.TimeoutExpired:
        return {"error": f"deadlock_routing timed out after {budget}s"}
    if proc.returncode == 2:
        return {"error": f"topology not certifiable: {(proc.stdout or proc.stderr).strip()[:300]}"}
    cert_file = Path(out_prefix + ".json")
    if not cert_file.exists():
        tail = "\n".join((proc.stderr or proc.stdout).splitlines()[-5:])
        return {"error": f"deadlock_routing wrote no certificate: {tail}"}
    try:
        cert = json.loads(cert_file.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return {"error": f"certificate unreadable: {e}"}
    return cert


def cmd_certify_flow(ctx: Ctx, args):
    log(ctx, f"Flow-class certification for {Path(args.topo).name}")
    model_abs = _resolve_path(args.model)
    topo_abs = _resolve_path(args.topo)
    if not Path(model_abs).exists():
        fail(ctx, f"Traffic model not found: {args.model} (resolved: {model_abs})")
        return
    if not Path(topo_abs).exists():
        fail(ctx, f"Topology not found: {args.topo} (resolved: {topo_abs})")
        return
    import subprocess
    r = subprocess.run([sys.executable, str(SCRIPTS_DIR / "flow_certifier.py"),
                        "--traffic-model", model_abs, "--topology", topo_abs],
                       capture_output=True, text=True,
                       timeout=_eff_timeout(args, 300), cwd=str(REPO))
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
    topo_abs = Path(_resolve_path(args.topo))
    if not topo_abs.exists():
        fail(ctx, f"Topology not found: {args.topo} (resolved: {topo_abs})")
        return
    build_path = Path(_resolve_path(args.build_dir))
    if not (build_path / "obj_dir").is_dir():
        # Fail here with guidance — not with a Verilator FATAL from deep
        # inside certify.sh (the old path: "FATAL: ./obj_dir/Vnoc_top missing").
        rtl_root = CERTIFY_SH.parent / "rtlgen"
        avail = sorted(d.name for d in rtl_root.iterdir()
                       if d.is_dir() and (d / "obj_dir").is_dir()) \
            if rtl_root.is_dir() else []
        hint = f" — available: {', '.join(avail[:5])}" if avail else ""
        fail(ctx, f"no obj_dir/ in '{args.build_dir}' — generate RTL first "
                  f"(scripts/rtlgen){hint}")
        return
    import subprocess
    try:
        subprocess.run(["bash", str(CERTIFY_SH), str(build_path), args.tier],
                       capture_output=True, text=True,
                       timeout=_eff_timeout(args, 600), check=True, cwd=str(REPO))
    except subprocess.CalledProcessError as e:
        out = ((e.stderr or "") + "\n" + (e.stdout or "")).strip().splitlines()
        tail = " | ".join(l.strip() for l in out[-8:] if l.strip())
        fail(ctx, f"RTL certification failed (exit {e.returncode}): {tail}")
        return
    ok(ctx, "RTL certification complete")


def cmd_certify_full(ctx: Ctx, args):
    log(ctx, "Running full certification (flow + rtl)")
    cmd_certify_flow(ctx, args)
    cmd_certify_rtl(ctx, args)
    if ctx.failed:
        fail(ctx, "Full certification FAILED — see failing legs above")
    else:
        ok(ctx, "Full certification complete")


def cmd_sweep(ctx: Ctx, args):
    if not _require_file(ctx, args.trace, "trace", kind="trace"):
        return
    trace = _resolve_path(args.trace)
    if detect_trace_stats(trace).num_packets == 0:
        fail(ctx, f"trace has no parseable packets: {args.trace} — "
                   "check it with: veritx trace validate <trace>")
        return
    sim_type = args.mode
    ir = args.ir

    banner(ctx, f"Sweep: {Path(trace).name}")
    log(ctx, f"Evaluating {len(SWEEP_TOPOS)} topologies on {Path(trace).name}")
    overrides = _parse_set(ctx, getattr(args, "set", None))
    if ctx.failed or _reject_astra_sets(ctx, getattr(args, "set", None), "sweep"):
        return
    if overrides:
        log(ctx, f"BookSim overrides: {overrides}")

    results = run_sweep(ctx, trace, repo_root=REPO, timeout=_eff_timeout(args, 60),
                        sim_type=sim_type, ir=ir, overrides=overrides)
    print_sweep_table(ctx, results, sim_type)

    out_dir = new_run_dir("sweep", ctx.seed, root=getattr(args, "out_dir", None))
    out_path = out_dir / "sweep.json"
    out_path.write_text(json.dumps(results, indent=2))
    ok(ctx, f"Results: {out_path}")
    output(ctx, results)


def _apply_memory_correction(ctx: Ctx, result, args) -> None:
    """DEPRECATED (MEMORY-ROADMAP §2 quarantine) — do not call from commands.

    Kept for research import only. The scalar M/D/1 correction added one
    topology-invariant constant to every summary mean (measured +0.0c on
    real traces): ranking-neutral, not system-level memory evidence.
    `cmd_compare` refuses --memory fail-closed before reaching here.
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


def _run_sensitivity(ctx: Ctx, trace: str, specs: list, args, overrides: dict | None = None) -> None:
    """Run sensitivity analysis at multiple injection rates.

    For each IR in --sensitivity, runs compare in throughput mode and
    prints a table showing how topology rankings change with load.
    """
    irs = [float(ir) for ir in args.sensitivity]
    banner(ctx, f"Sensitivity Analysis: IR = {irs}")

    all_results = []
    sens_timeout = _eff_timeout(args, 60)
    if overrides and "injection_rate" in overrides:
        # Loud, not silent: pinning the rate would fake every row identical.
        log(ctx, f"  note: --set injection_rate={overrides['injection_rate']} IGNORED for sensitivity "
                  f"(it would pin all IR rows to one rate); other --set keys still apply")
    for ir in irs:
        log(ctx, f"Running IR={ir}...")
        # --set injection_rate would pin every row to one rate and fake the
        # sweep; drop it so the IR axis is honest, keep everything else.
        sens_over = {k: v for k, v in (overrides or {}).items()
                     if k != "injection_rate"}
        r = run_compare(
            ctx, trace, specs,
            seeds=1, seed_base=ctx.seed,
            timeout=sens_timeout, sim_type="throughput", ir=ir,
            overrides=sens_over,
        )
        all_results.append((ir, r))

    # Print sensitivity table
    emit(ctx, f"\n  {'IR':>6}", end="")
    for name, _ in specs:
        emit(ctx, f" {name:>14}", end="")
    emit(ctx)
    emit(ctx, f"  {'─' * (6 + 14 * len(specs))}")

    for ir, r in all_results:
        emit(ctx, f"  {ir:>6.3f}", end="")
        for s in r.summary:
            if "mean" in s:
                emit(ctx, f" {s['mean']:>13.1f}c", end="")
            else:
                emit(ctx, f" {'N/A':>13}", end="")
        emit(ctx)


def _unique_display(seen: set, name: str) -> str:
    """Disambiguate a display name already present in `seen`.

    Same-stem collisions are real and meaningful: e.g. built-in preset
    `mesh_8x8` (mesh backend, min_adapt) vs custom `mesh_8x8.anynet`
    (anynet backend, min routing, 112 edges). run_compare pools rows by
    display name, so sharing one silently merges two populations into a
    single bogus mean/std row.
    """
    if name not in seen:
        return name
    cand = f"{name}@anynet"
    n = 2
    while cand in seen:
        cand = f"{name}@anynet{n}"
        n += 1
    return cand


def cmd_compare(ctx: Ctx, args):
    if not _require_file(ctx, args.trace, "trace", kind="trace"):
        return
    trace = _resolve_path(args.trace)
    if detect_trace_stats(trace).num_packets == 0:
        fail(ctx, f"trace has no parseable packets: {args.trace} — "
                   "check it with: veritx trace validate <trace>")
        return

    # MEMORY-ROADMAP §2 quarantine: the --memory scalar correction is
    # deprecated and must never silently contaminate a comparison. It added
    # one topology-invariant M/D/1 constant to every mean (measured +0.0c
    # on real traces), so it could not alter rankings — only imply a memory
    # science that was not there. Fail closed BEFORE any simulation burns
    # time; the replacement is an explicit memory backend
    # (docs/MEMORY-ROADMAP.md), not these flags.
    if getattr(args, "memory", False):
        fail(ctx, "--memory scalar correction is deprecated and refused: "
                   "it added the same constant to every topology "
                   "(topology-invariant, ranking-neutral — measured +0.0c) "
                   "and is not valid system-level memory evidence. "
                   "Run the comparison without --memory/--banks/--bank-bw; "
                   "real memory modelling lands via an explicit memory "
                   "backend (see docs/MEMORY-ROADMAP.md).")
        return

    # Resolve topology specs
    if args.dense:
        preset = DENSE_PRESETS[args.dense]
        banner(ctx, f"Dense preset: {preset['desc']}")
        topo_names = [t.strip() for t in preset["topos"].split(",")]
        anynet_files = list(preset.get("anynet", []))
        # A preset no longer discards explicit --topos/--anynet: merge both
        # sources (deduped below). Preset topos already cover the parser
        # defaults, so pure --dense runs are unaffected.
        topo_names += [t.strip() for t in args.topos.split(",") if t.strip()]
        anynet_files += list(args.anynet or [])
    else:
        topo_names = [t.strip() for t in args.topos.split(",")]
        anynet_files = args.anynet

    specs = []
    seen = set()
    for name in topo_names:
        t = lookup_topo(name)
        if t is None:
            fail(ctx, f"Unknown topology: {name}")
            fail(ctx, f"Available: {', '.join(t.name for t in SWEEP_TOPOS)} or .anynet path")
            return
        # Compare canonical names too: alias 'mesh' resolves to mesh_4x4, so
        # a typed alias must collide with the built-in spelling as well.
        if name in seen or t.name in seen:
            log(ctx, f"Skipping duplicate topology: {name} (same preset listed twice)")
            continue
        specs.append((name, t))
        seen.add(name)
        seen.add(t.name)

    for af in _expand_anynet_files(anynet_files):
        af_resolved = _resolve_path(af)
        if not Path(af_resolved).exists():
            log(ctx, f"\033[33mwarn:\033[0m .anynet not found, skipping: {af} (resolved: {af_resolved})")
            continue
        t = make_anynet_topo(af_resolved)
        disp = _unique_display(seen, t.name)
        if disp != t.name:
            log(ctx, f"Name collision: '{t.name}' already listed — tracking custom net as '{disp}'")
        specs.append((disp, t))
        seen.add(disp)
    if not specs:
        fail(ctx, "No valid topologies: every --topos/--anynet entry was unknown or missing")
        return

    banner(ctx, f"Compare: {' vs '.join(s[0] for s in specs)} [{args.mode} mode]")
    log(ctx, f"{len(specs)} topologies × {args.seeds} seeds = {len(specs) * args.seeds} runs")
    log(ctx, f"Trace: {Path(trace).name}")
    overrides = _parse_set(ctx, getattr(args, "set", None))
    if ctx.failed or _reject_astra_sets(ctx, getattr(args, "set", None), "compare"):
        return
    if overrides:
        log(ctx, f"BookSim overrides: {overrides}")

    result = run_compare(
        ctx, trace, specs,
        seeds=args.seeds, seed_base=args.seed_base,
        timeout=_eff_timeout(args, 60), sim_type=args.mode, ir=args.ir,
        overrides=overrides,
    )

    print_compare_table(ctx, result)

    # Persist so the t3 TUI (and any later session) can re-plot/diff this run.
    # --out-dir co-locates guided runs under results/<CONFIG>/compare/.
    try:
        _cmp_dir = new_run_dir("compare", ctx.seed,
                               root=getattr(args, "out_dir", None))
        _cmp_path = _cmp_dir / "compare.json"
        _tmp = _cmp_path.with_suffix(".json.tmp")
        _tmp.write_text(json.dumps(result.to_dict(), indent=2))
        _tmp.rename(_cmp_path)  # atomic on POSIX
        ok(ctx, f"Saved: {_cmp_path}")
    except Exception as e:  # persistence is best-effort; never fail the run
        log(ctx, f"\033[33mwarn:\033[0m could not save compare JSON: {e}")

    # Run sensitivity analysis if requested
    if getattr(args, 'sensitivity', None):
        _run_sensitivity(ctx, trace, specs, args, overrides)

    output(ctx, result.to_dict())


def cmd_pareto(ctx: Ctx, args):
    traces = [t.strip() for t in args.traces.split(",") if t.strip()]
    if not traces:
        fail(ctx, "--traces is empty — pass at least one trace")
        return
    good = []
    for t in traces:
        try:
            rp = _resolve_path(t)
        except ValueError:
            rp = ""
        if rp and Path(rp).exists():
            good.append(t)
        else:
            log(ctx, f"\033[33mwarn:\033[0m skipping missing trace: {t}")
    if not good:
        fail(ctx, "no valid traces — nothing to compare")
        return
    if args.seeds < 1:
        fail(ctx, f"seeds must be >= 1, got {args.seeds}")
        return
    sys.path.insert(0, str(SCRIPTS_DIR))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "mwp", str(SCRIPTS_DIR / "multi_workload_pareto.py"))
    mod = importlib.util.module_from_spec(spec)
    # Explicit --out wins; default = timestamped run dir under results/pareto/.
    _out = str(Path(args.out)) if args.out \
        else str(new_run_dir("pareto", ctx.seed) / "pareto.json")
    # Timeout precedence: --timeout flag > VERITX_TIMEOUT env > "auto"
    # (per-trace packet-derived budget). A flat default here is what turned
    # the 668k-packet serving trace into a table of TIMEOUTs that read like
    # topology failures — see calibration notes 2026-09-16.
    import os as _os
    if getattr(args, "timeout", None) is not None:
        timeout_arg = str(_eff_timeout(args, 60))  # validates >= 1
    elif _os.environ.get("VERITX_TIMEOUT"):
        timeout_arg = _os.environ["VERITX_TIMEOUT"]
    else:
        timeout_arg = "auto"
    sys.argv = ["multi_workload_pareto.py", "--traces", ",".join(good),
                "--topos", args.topos, "--anynet", args.anynet,
                "--seeds", str(args.seeds),
                "--timeout", timeout_arg,
                "--out", _out]
    spec.loader.exec_module(mod)
    mod.main()


def cmd_run(ctx: Ctx, args):
    """Unified pipeline: ingest → matrix → synthesize → evaluate →
    ASTRA replay → energy → certify.

    Exactly one source: --model (traffic model), --spec (product intent),
    --trace (ready DSE trace), or --et (Chakra .et workload). Every source
    funnels into one artifact chain (input.trace + matrix.mat), so every
    synthesizer (bo/iterative/milp), both simulators, and both certificates
    operate on the same data, recorded in a single manifest.
    """
    source_kind = None
    for kind in ("model", "spec", "trace", "et"):
        if getattr(args, kind, None):
            if source_kind:
                fail(ctx, f"--{source_kind} and --{kind} are mutually "
                          "exclusive — pass exactly one source")
                return
            source_kind = kind
    if source_kind is None:
        fail(ctx, "no source given — pass exactly one of "
                  "--model/--spec/--trace/--et")
        return
    if source_kind == "model" and args.nodes < 2:
        fail(ctx, f"nodes must be >= 2, got {args.nodes}")
        return
    if source_kind == "model" and args.search == "bo" \
            and (s := args.nodes ** 0.5) % 1 != 0:
        # BO's analytical scorer seeds an XY grid (√n×√n); a non-square node
        # count dies inside bo_synthesizer with a bare AssertionError.
        import math
        _sq = math.ceil(s) ** 2
        log(ctx, f"note: --nodes {args.nodes} is not a perfect square; "
                 f"BO's grid scorer needs one — bumping to {_sq}")
        args.nodes = _sq
    if args.iters < 1:
        fail(ctx, f"--iters must be >= 1, got {args.iters}")
        return
    # Fail-fast on the source BEFORE creating a run dir / burning budget.
    # getattr: callers (tests) may pass only the source they use.
    _src_path, _src_what, _src_kind = {
        "model": (getattr(args, "model", None), "traffic model", "model"),
        "spec": (getattr(args, "spec", None), "product spec", None),
        "trace": (getattr(args, "trace", None), "trace", "trace"),
        "et": (getattr(args, "et", None), "Chakra workload (.et file or dir)", None),
    }[source_kind]
    # Safety net FIRST: short names resolve through the asset registry, so
    # `--model traffic` or `--model moe_8npu` work like `veritx where`.
    try:
        _resolves = Path(str(_resolve_path(_src_path))).exists()
    except (ValueError, OSError):
        _resolves = False
    if not _resolves and _src_kind:
        hit = _resolve_asset(_src_path, _src_kind)
        if hit is not None:
            _src_path = str(hit)
            setattr(args, source_kind, str(hit))
            log(ctx, f"resolved '{_src_path}' → {hit}")
    if not _require_file(ctx, _src_path, _src_what, kind=_src_kind):
        return
    if source_kind == "model":
        # Schema guard: a CompileRequest passed as --model dies three layers
        # deep with KeyError('network'). Name the mistake and the fix.
        try:
            _peek = json.loads(Path(_resolve_path(_src_path)).read_text())
            if isinstance(_peek, dict) and "workload" in _peek and "network" not in _peek:
                fail(ctx, f"{_src_path} is a CompileRequest, not a TrafficModel — "
                          "use it with `veritx compile` / `veritx generate uvm`; "
                          "TrafficModel JSONs (schema: network.flow_classes) "
                          "live in dse/models/")
                return
        except (OSError, json.JSONDecodeError, ValueError):
            pass  # existence handled above; parse errors surface at ingest
    from datetime import datetime
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = EXPERIMENTS_DIR / run_id
    # Seconds-resolution ids collide when two pipelines start in the same
    # second (e.g. a test fixture racing a manual run): never overwrite.
    _suffix = 0
    while run_dir.exists() and (run_dir / "manifest.json").exists():
        _suffix += 1
        run_dir = EXPERIMENTS_DIR / f"{run_id}_{_suffix:02d}"
    run_id = run_dir.name
    run_dir.mkdir(parents=True, exist_ok=True)

    banner(ctx, f"VeritX Pipeline: {run_id}")
    emit(ctx, f"  Source: {source_kind} ({getattr(args, source_kind)})")
    emit(ctx, f"  Nodes:  {args.nodes}")
    emit(ctx, f"  Search: {args.search} ({args.iters} iters)")
    emit(ctx, f"  Cert:   {args.cert}\n")
    step_budget = _eff_timeout(args, 600)

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

    # Step 1: Ingest — exactly one source → run_dir/input.trace
    trace_path = run_dir / "input.trace"
    manifest["source"] = source_kind
    try:
        if source_kind == "model":
            log(ctx, "Step 1/7: Generating trace from traffic model")
            from ..simulation.model_to_trace import main as model_main
            sys.argv = ["model_to_trace", "--traffic-model", _resolve_path(args.model),
                        "--nodes", str(args.nodes), "--out", str(trace_path)]
            model_main()
        elif source_kind == "spec":
            log(ctx, "Step 1/7: Translating product spec → matrix → trace")
            import subprocess as _sp
            from ..simulation.traces import matrix_to_trace
            prefix = str(run_dir / "spec")
            r = _sp.run([sys.executable,
                         str(DSE_DIR.parent / "product" / "spec_translate.py"),
                         "--spec", _resolve_path(args.spec), "--out", prefix],
                        capture_output=True, text=True,
                        timeout=step_budget, cwd=str(REPO))
            if r.returncode != 0:
                raise RuntimeError(
                    f"spec_translate exit {r.returncode}: "
                    + "\n".join((r.stderr or r.stdout).splitlines()[-3:]))
            manifest["spec_plan"] = prefix + ".plan.json"
            from ..synthesis.milp_topology_v2 import load_matrix
            info = matrix_to_trace(load_matrix(prefix + ".mat"), trace_path)
            if info["scaled"]:
                log(ctx, "  note: per-pair packet cap engaged — matrix traffic "
                         "is relative, not absolute")
        elif source_kind == "trace":
            log(ctx, "Step 1/7: Installing provided trace")
            import shutil
            src = Path(_resolve_path(args.trace))
            if not src.exists():
                raise FileNotFoundError(f"trace not found: {args.trace}")
            shutil.copy2(src, trace_path)
        else:  # et
            log(ctx, "Step 1/7: Converting Chakra .et workload → trace")
            from types import SimpleNamespace as _NS
            npu_map = ",".join(str(i) for i in range(args.nodes))
            cmd_trace_chakra(ctx, _NS(et_dir=args.et, npu_map=npu_map,
                                      speedup=None, out=str(trace_path)))
            if ctx.failed:
                raise RuntimeError(".et conversion failed (see errors above)")
        if not trace_path.exists() or trace_path.stat().st_size == 0:
            raise RuntimeError(f"ingest produced no trace at {trace_path}")
        manifest["trace"] = str(trace_path)
        sz = trace_path.stat().st_size
        ok(ctx, f"Trace: {trace_path.name} ({sz // 1024}KB)" if sz >= 1024
                else f"Trace: {trace_path.name} ({sz}B)")
    except Exception as e:
        manifest["error"] = f"trace: {e}"
        fail(ctx, f"Trace generation failed: {e}")
        _save()
        return

    # Step 2: Traffic matrix — the shared currency of MILP + deadlock cert.
    matrix_path = run_dir / "matrix.mat"
    n_nodes = args.nodes
    try:
        log(ctx, "Step 2/7: Aggregating traffic matrix")
        from ..simulation.traces import aggregate_matrix, save_matrix, trace_num_nodes
        n_nodes = trace_num_nodes(trace_path) or args.nodes
        if source_kind == "model" and args.nodes > n_nodes:
            n_nodes = args.nodes
        T = aggregate_matrix(trace_path, n_nodes)
        save_matrix(T, matrix_path)
        manifest["nodes"] = n_nodes
        manifest["matrix"] = str(matrix_path)
        ok(ctx, f"Matrix: {n_nodes}x{n_nodes} ({matrix_path.name})")
    except Exception as e:
        manifest["error"] = f"matrix: {e}"
        fail(ctx, f"Matrix aggregation failed: {e}")
        _save()
        return

    # Step 3: Synthesize
    topo_path = run_dir / "winner.anynet"
    try:
        log(ctx, f"Step 3/7: Synthesizing topology ({args.search})")
        import shutil
        import subprocess
        if args.search == "bo":
            iters = args.iters  # respect the user's budget — no silent floors
            cmd = [sys.executable, str(Path(__file__).parent.parent / "synthesis" / "bo_synthesizer.py"),
                   "--traffic", str(trace_path), "--nodes", str(n_nodes),
                   "--iters", str(iters), "--scorer", args.scorer]
            try:
                subprocess.run(cmd, capture_output=True, text=True, timeout=step_budget,
                              check=True, cwd=str(REPO))
            except subprocess.CalledProcessError as e:
                # check=True alone reports only "exit status 1" — surface the
                # synthesizer's own diagnostics (same tail convention as
                # cmd_synthesize_bo) so the next failure is actionable.
                out = ((e.stderr or "") + "\n" + (e.stdout or "")).strip().splitlines()
                tail = " | ".join(l.strip() for l in out[-8:] if l.strip())
                fail(ctx, f"Synthesis failed (exit {e.returncode}): {tail}")
                _save()
                return
            bo_results = SYNTH_DIR / f"bo_results_N{n_nodes}.json"
            if not bo_results.exists():
                _legacy = RUNS_DIR / "booksim" / f"bo_results_N{n_nodes}.json"
                if _legacy.exists():
                    bo_results = _legacy
            if bo_results.exists():
                try:
                    data = json.loads(bo_results.read_text())
                except (json.JSONDecodeError, OSError) as e:
                    fail(ctx, f"Failed to parse BO results: {e}")
                    data = {}
                manifest["best_latency_analytical"] = data.get("best_latency")
                manifest["best_latency_booksim"] = data.get("booksim_latency")
                manifest["best_params"] = data.get("best_params")
        elif args.search == "milp":
            # Exact traffic-weighted synthesis on the aggregated matrix
            # (small n → MILP/HiGHS; large n → SA fallback inside the tool).
            # Engine parameters come from the spec plan when the source was
            # --spec (the contract spec_translate writes), else defaults.
            layout, radix, max_len = "grid", 5, 2.0
            extra: list = []
            plan_file = manifest.get("spec_plan")
            if plan_file and Path(plan_file).exists():
                try:
                    ei = json.loads(Path(plan_file).read_text()).get("engine_inputs", {})
                    layout = ei.get("layout") or layout
                    radix = ei.get("radix_max") or radix
                    max_len = ei.get("max_len") or max_len
                    if ei.get("rows") and ei.get("cols"):
                        extra = ["--rows", str(ei["rows"]), "--cols", str(ei["cols"])]
                except (json.JSONDecodeError, OSError) as e:
                    log(ctx, f"  note: spec plan unreadable ({e}) — using defaults")
            cmd = [sys.executable, str(Path(__file__).parent.parent / "synthesis" / "milp_topology_v2.py"),
                   "--matrix", str(matrix_path),
                   "--layout", layout, "--radix", str(radix), "--max_len", str(max_len),
                   # Exact MILP for n<=20 ignores --iters; for larger n it is
                   # the SA iteration budget, passed through 1:1 (no floors).
                   "--iters", str(args.iters),
                   *extra,
                   "--out", str(run_dir / "milp")]
            try:
                subprocess.run(cmd, capture_output=True, text=True, timeout=step_budget,
                              check=True, cwd=str(REPO))
            except subprocess.CalledProcessError as e:
                out = ((e.stderr or "") + "\n" + (e.stdout or "")).strip().splitlines()
                tail = " | ".join(l.strip() for l in out[-8:] if l.strip())
                fail(ctx, f"Synthesis failed (exit {e.returncode}): {tail}")
                _save()
                return
            manifest["solver"] = "milp_topology_v2"
        elif args.search == "iterative":
            method = args.iterative_method
            # Same canonical winner path as BO (SYNTH_DIR = T3 runs/booksim).
            iterative_out = SYNTH_DIR / "topo.anynet"
            iterative_out.parent.mkdir(parents=True, exist_ok=True)
            cmd = [sys.executable, str(Path(__file__).parent.parent / "synthesis" / "iterative_synthesizer.py"),
                   "--trace", str(trace_path), "--method", method,
                   "--steps", str(args.iters), "--max-edges", str(args.max_edges),
                   "--out", str(iterative_out)]
            try:
                subprocess.run(cmd, capture_output=True, text=True, timeout=step_budget,
                              check=True, cwd=str(REPO))
            except subprocess.CalledProcessError as e:
                out = ((e.stderr or "") + "\n" + (e.stdout or "")).strip().splitlines()
                tail = " | ".join(l.strip() for l in out[-8:] if l.strip())
                fail(ctx, f"Synthesis failed (exit {e.returncode}): {tail}")
                _save()
                return
            subprocess.run(cmd, capture_output=True, text=True, timeout=step_budget,
                          check=True, cwd=str(REPO))

        # Candidate locations, in priority order. MILP writes exactly where
        # we point it; BO/iterative land in the canonical synth dir, with
        # the legacy repo-runs home as fallback.
        candidates = [topo_path, run_dir / "milp.anynet",
                      SYNTH_DIR / "topo.anynet",
                      RUNS_DIR / "booksim" / "topo.anynet"]
        if not topo_path.exists():
            for cand in candidates[1:]:
                if cand.exists():
                    shutil.copy2(cand, topo_path)
                    break
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

    # Step 4: Evaluate — the SYNTHESIZED topology, not a mesh.
    # (This used to hardcode Topology("mesh_kxk"), certifying a topology and
    # then reporting latency for an unrelated one.)
    try:
        log(ctx, "Step 4/7: Evaluating with BookSim2")
        budget = predict_booksim_budget(trace_path, budget_s=step_budget)
        manifest["eval_budget"] = budget
        if budget["feasible"]:
            log(ctx, f"  budget: {budget['packets']:,} pkts → "
                     f"~{budget['predicted_s']:.0f}s of {budget['budget_s']}s — OK")
        else:
            raise RuntimeError(
                f"trace too large for the {step_budget}s step budget: "
                f"{budget['packets']:,} packets ≈ {budget['predicted_s']:.0f}s "
                f"at ~{BOOKSIM_PKTS_PER_SEC:,} pkt/s. Options: raise the budget, "
                "slice/decimate the trace, or shrink the model's "
                "invocations_per_batch (the trace is faithful; flit-level "
                "BookSim just cannot chew it in this budget).")
        topo = make_anynet_topo(str(topo_path))
        eval_result = run_topology_eval(ctx, topo, str(trace_path),
                                        repo_root=REPO, timeout=step_budget)
        manifest["eval"] = eval_result
        manifest["eval_topology"] = topo.name
        if "latency" in eval_result:
            ok(ctx, f"Latency: {eval_result['latency']:.2f}c ({topo.name})")
    except Exception as e:
        manifest["eval"] = {"error": str(e)}
        fail(ctx, f"Evaluation failed: {e}")

    # Step 5: ASTRA-sim — workload-DAG replay on the winner topology.
    # Failure here is recorded but does not abort the pipeline (the spine
    # result stands; the leg reports its own error in the manifest).
    try:
        log(ctx, "Step 5/7: ASTRA-sim collective replay on winner")
        # Leg default was sized for 8-NPU smoke tests (16 MiB => ~37M sim
        # packets at k=64); scale it down with the run unless asked.
        astra_msg_mb = getattr(args, "astra_msg_mb", None)
        msg_bytes = (int(round(astra_msg_mb * 1048576))
                     if astra_msg_mb else min(16777216, max(65536, n_nodes * 1024)))
        astra_result = _run_astra_leg(ctx, run_dir, topo_path, n_nodes,
                                      budget=step_budget, msg_size_bytes=msg_bytes)
        manifest["astra"] = astra_result
        if astra_result.get("status") == "ok":
            ok(ctx, f"ASTRA: {astra_result['cycles']:,}c "
                    f"({astra_result['num_ranks']} ranks)")
        else:
            fail(ctx, f"ASTRA leg failed: {astra_result.get('error')}")
            if not astra_msg_mb and n_nodes >= 32:
                log(ctx, "ASTRA payload auto-scaled to "
                     f"{msg_bytes // 1024} KiB (16 MiB needs 30-40+ min sim "
                     "time at this scale). Pass --astra-msg-mb 16 to override.")
    except Exception as e:
        manifest["astra"] = {"error": str(e)}
        fail(ctx, f"ASTRA leg failed: {e}")

    # Step 6: Timeloop — accelerator-side energy for the track workload.
    try:
        log(ctx, "Step 6/7: Timeloop energy model")
        energy_result = _run_energy_leg(ctx, run_dir, budget=step_budget)
        manifest["energy"] = energy_result
        if energy_result.get("status") == "ok":
            ok(ctx, f"Energy: {energy_result.get('energy_uJ')} uJ "
                    f"(energy-delay product {energy_result.get('edp_uJ_cycles')} uJ·cyc)")
        else:
            fail(ctx, f"Energy leg failed: {energy_result.get('error')}")
    except Exception as e:
        manifest["energy"] = {"error": str(e)}
        fail(ctx, f"Energy leg failed: {e}")

    # Step 7: Certify — flow-class cert on the model, plus the structural
    # deadlock (CDG) certificate for the winner topology.
    try:
        if args.cert and args.cert != "none":
            log(ctx, f"Step 7/7: Certifying ({args.cert})")
            # 7a. Deadlock CDG certificate (needs matrix + topology, both of
            # which exist for every source).
            dl = _run_cert_leg(ctx, run_dir, trace_path, matrix_path,
                               topo_path, budget=step_budget)
            manifest["deadlock_cert"] = dl
            if "error" in dl:
                fail(ctx, f"Deadlock cert failed: {dl['error']}")
            elif dl.get("channel_dependency_graph", {}).get("acyclic"):
                ok(ctx, "Deadlock: CDG acyclic → deadlock-free")
            else:
                fail(ctx, "Deadlock: cyclic channel-dependency graph (CDG) — escape VCs required")
            # 7b. Flow-class cert (traffic-model-based).
            if args.cert in ("flow", "full"):
                if source_kind != "model":
                    manifest["cert"] = {"skipped":
                        f"flow cert needs a traffic model; source was {source_kind}"}
                    log(ctx, "  flow cert skipped (no traffic model source)")
                else:
                    import subprocess
                    r = subprocess.run([sys.executable, str(SCRIPTS_DIR / "flow_certifier.py"),
                                        "--traffic-model", _resolve_path(args.model),
                                        "--topology", str(topo_path.resolve())],
                                       capture_output=True, text=True, timeout=step_budget, cwd=str(REPO))
                    cert_pass = any("PASS" in line for line in r.stdout.splitlines())
                    manifest["cert"] = "PASS" if cert_pass else "FAIL"
                    ok(ctx, f"Certification: {manifest['cert']}")
        else:
            log(ctx, "Step 7/7: Skipping certification (disabled)")
    except Exception as e:
        manifest["cert"] = {"error": str(e)}
        fail(ctx, f"Certification failed: {e}")

    _save()
    emit(ctx, f"\n\033[1m{'=' * 60}\033[0m")
    # The spine is trace → matrix → synthesize → eval → cert. Those must
    # all land clean for the pipeline to be "complete". ASTRA (step 5) and
    # energy (step 6) are optional replay/energy legs: their failure is
    # reported inline with a ✗ during the run, but they do not make the
    # overall pipeline "finish with errors" — the spine result stands.
    #
    # Exit contract: a spine that passed is a completed pipeline, even if
    # one or both optional legs were unavailable (missing binary, timeout,
    # env absent). Exit 0 in that case so CI/scripts that only care about
    # topology + eval + cert see a clean signal; scripts that need the
    # optional legs can read manifest["astra"]["status"] / ["energy"]["status"]
    # themselves.
    def _bad(key):
        v = manifest.get(key)
        return isinstance(v, dict) and "error" in v

    _cert = manifest.get("cert")
    _leg_failed = (
        isinstance(manifest.get("astra"), dict)
        and manifest["astra"].get("status") != "ok"
    ) or (
        isinstance(manifest.get("energy"), dict)
        and manifest["energy"].get("status") != "ok"
    )

    spine_ok = not (
        "error" in manifest
        or _bad("eval") or _bad("deadlock_cert") or _bad("cert")
        or _cert == "FAIL"
        or manifest.get("topology") is None
    )

    if not spine_ok:
        emit(ctx, f"  \033[31m✗ Pipeline finished with errors\033[0m "
              f"in {manifest.get('duration_s', 0)}s")
    elif _leg_failed:
        emit(ctx, f"  \033[32m✓ Pipeline complete (partial)\033[0m "
              f"in {manifest.get('duration_s', 0)}s")
        emit(ctx, "  (spine passed; one or both optional legs unavailable)")
    else:
        emit(ctx, f"  \033[32m✓ Pipeline complete\033[0m "
              f"in {manifest.get('duration_s', 0)}s")

    emit(ctx, f"  Results: {run_dir}")
    if "eval" in manifest and "latency" in manifest["eval"]:
        emit(ctx, f"  Latency: {manifest['eval']['latency']:.2f}c")
    _a = manifest.get("astra")
    if isinstance(_a, dict) and _a.get("status") == "ok":
        emit(ctx, f"  ASTRA:   {_a['cycles']:,}c (exposed comm "
              f"{_a.get('exposed_comm_cycles', '-')}c)")
    elif isinstance(_a, dict):
        emit(ctx, f"  ASTRA:   unavailable ({_a.get('error', 'leg failed')})")
    _e = manifest.get("energy")
    if isinstance(_e, dict) and _e.get("status") == "ok":
        emit(ctx, f"  Energy:  {_e.get('energy_uJ')} uJ over {_e.get('cycles')} cycles")
    elif isinstance(_e, dict):
        emit(ctx, f"  Energy:  unavailable ({_e.get('error', 'leg failed')})")
    _d = manifest.get("deadlock_cert")
    if isinstance(_d, dict) and "channel_dependency_graph" in _d:
        emit(ctx, f"  Deadlock: {_d['channel_dependency_graph']['verdict']}")
    emit(ctx, f"\033[1m{'=' * 60}\033[0m\n")

    # Return the spine verdict so `main` can exit 0 on spine-pass even when
    # optional legs failed. The inline leg ✗ lines already told the user what
    # went wrong; the process exit should reflect whether the pipeline itself
    # produced a usable result.
    return 0 if spine_ok else 1


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

    Built-in baselines (standard configurations from literature):
      - mesh_8x8:      2D mesh k=8 n=2, dim_order routing (TPU v1/v2 style)
      - torus_8x8:     2D torus k=8 n=2, dim_order routing
      - flatfly_64:    FlatButterfly k=4 n=2 c=4 (UFusion style)
    Extras available via --topos: gec_express_k8, gec_mecs_k8, gec_mesh_k8,
    fbfly_64, cmesh_64, fattree_k4n3, qtree_64, tree4_64, dragonfly_72,
    mesh_4x4 (see `veritx evaluate booksim --help` for the full preset list).
    """
    if not _require_file(ctx, args.trace, "trace", kind="trace"):
        return
    trace = _resolve_path(args.trace)
    if detect_trace_stats(trace).num_packets == 0:
        fail(ctx, f"trace has no parseable packets: {args.trace} — "
                   "check it with: veritx trace validate <trace>")
        return

    # Built-in baselines
    baselines = [
        lookup_topo("mesh_8x8"),
        lookup_topo("torus_8x8"),
        lookup_topo("flatfly_64"),
    ]
    specs = [(b.name, b) for b in baselines if b is not None]
    seen = {s[0] for s in specs}

    # User topologies (skip names already covered by built-ins — TOPO=all
    # overlaps them, and duplicate display names get pooled into one bogus
    # mean/std row by run_compare's name-grouped aggregation).
    for name in args.topos.split(","):
        name = name.strip()
        if not name:
            continue
        t = lookup_topo(name)
        if t is None:
            fail(ctx, f"Unknown topology: {name}")
            fail(ctx, f"Available: {', '.join(t.name for t in SWEEP_TOPOS)} or .anynet path")
            return
        if name in seen or t.name in seen:
            log(ctx, f"Skipping duplicate topology: {name} (already a built-in baseline)")
            continue
        specs.append((name, t))
        seen.add(name)
        seen.add(t.name)

    # Custom .anynets (missing files warn-and-continue: the built-ins alone
    # are still a valid baseline).
    for af in _expand_anynet_files(args.anynet):
        af_resolved = _resolve_path(af)
        if not Path(af_resolved).exists():
            log(ctx, f"\033[33mwarn:\033[0m .anynet not found, skipping: {af} (resolved: {af_resolved})")
            continue
        t = make_anynet_topo(af_resolved)
        disp = _unique_display(seen, t.name)
        if disp != t.name:
            log(ctx, f"Name collision: '{t.name}' already listed — tracking custom net as '{disp}'")
        specs.append((disp, t))
        seen.add(disp)

    banner(ctx, f"Baseline Comparison: {len(specs)} topologies")
    log(ctx, f"Trace: {Path(trace).name}")

    result = run_compare(
        ctx, trace, specs,
        seeds=args.seeds, seed_base=ctx.seed,
        timeout=_eff_timeout(args, 60), sim_type="latency", ir=0.05,
    )
    print_compare_table(ctx, result)
    out_dir = new_run_dir("baseline", ctx.seed)
    out_path = out_dir / "baseline.json"
    out_path.write_text(json.dumps(result.to_dict(), indent=2))
    ok(ctx, f"Saved: {out_path}")
    output(ctx, result.to_dict())


def cmd_compile(ctx: Ctx, args):
    # Short-name nicety: `veritx compile moe_8npu` resolves the CompileRequest
    # through the asset registry like every other kind.
    if not Path(str(_resolve_path(args.request))).exists():
        hit = _resolve_asset(args.request, "request")
        if hit is not None:
            args.request = str(hit)
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
    if cr.workload.collectives:
        log(ctx, "Collectives: " + ", ".join(
            f"{c.kind.value}/{c.group_size}" for c in cr.workload.collectives))
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
                result = run_booksim(ctx, config, repo_root=REPO, timeout=_eff_timeout(args, 120))
                result["seed"] = ctx.seed
                ok(ctx, f"Latency: {result['latency']:.2f}c | Hops: {result.get('hops', '?')}")
            except Exception as e:
                fail(ctx, f"BookSim failed: {e}")
                result = {}

    # ── Step 4/6: Verify — F1-F8 proof obligations ──
    # Evidence plumbing (Phase-13 precursor): what Step 3 measured is
    # translated to the F-check vocabulary — absent stats produce
    # absent keys (F3/F8 stay NOT_RUN, never read a fabricated zero).
    from veritx_dse.model.compile_model import (
        latency_bound_from_requirements, topology_adjacency, verify_design,
    )
    from veritx_dse.simulation.booksim import evidence_from_result
    evidence = evidence_from_result(result)
    adj = topology_adjacency(topo)
    if adj is not None:
        evidence["topology_adjacency"] = {str(k): sorted(v)
                                          for k, v in adj.items()}
    bound = latency_bound_from_requirements(cr.requirements)
    if bound is not None:
        evidence["latency_bound_cycles"] = bound
    log(ctx, "Step 4/6: Running verification checks...")
    vr_verify = verify_design(cr, topology_name=topo.backend, evidence=evidence)
    for check in vr_verify.checks:
        # Honest display (PR B): only PASS is success; FAIL is failure;
        # NOT_RUN/ASSUMPTION/UNSUPPORTED/INCONCLUSIVE are explicitly not
        # verified — never rendered as a checkmark.
        status_sym = {
            "PASS": "✓", "FAIL": "✗", "NOT_RUN": "◌",
            "ASSUMPTION": "◇", "UNSUPPORTED": "⊘", "INCONCLUSIVE": "?",
        }.get(check["status"], "⚠")
        log(ctx, f"  {status_sym} [{check['status']}] {check['name']}: {check['detail']}")
    if vr_verify.errors:
        for e in vr_verify.errors:
            fail(ctx, f"  ✗ {e}")
    n_pass = sum(1 for c in vr_verify.checks if c["status"] == "PASS")
    ok(ctx, f"Verification: {n_pass}/{len(vr_verify.checks)} PASS"
            f" ({len(vr_verify.checks) - n_pass} not verified)")

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

    # Design manifest with signing + revision chain (PRD §12, §14).
    # PR B signing-mode honesty: the signing key is operator-supplied via
    # VERITX_SIGNING_KEY. Without it the manifest is CHECKSUMMED/UNSIGNED
    # (signature empty, mode recorded) — never signed with a hidden key.
    signing_key = os.environ.get("VERITX_SIGNING_KEY")
    if signing_key:
        dm = DesignManifest.create(cr, secret_key=signing_key,
                                   metadata={"engine": "veritx-cli", "version": "0.3.0"})
    else:
        dm = DesignManifest.create_unsigned(
            cr, metadata={"engine": "veritx-cli", "version": "0.3.0",
                          "signing_mode": "CHECKSUMMED_UNSIGNED"})
    report["manifest"] = dm.to_dict()

    # Canonical home for compile reports (Phase 4c single results home).
    # --output/-o (via Ctx.output_file) still writes the user's copy too.
    out_path = RESULTS_DIR / "compile" / f"compile_{cr.workload.model_family.value}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    ok(ctx, f"Report: {out_path}")

    # Print summary
    emit(ctx, f"\n  \033[1mCompile Result\033[0m")
    emit(ctx, f"  {'─' * 55}")
    emit(ctx, f"  Model:      {cr.workload.model_name or cr.workload.model_family.value}")
    emit(ctx, f"  Topology:   {topo.backend} k={topo.params.get('k', '?')}")
    emit(ctx, f"  Routing:    {va.routing_function} (LOCKED)")
    emit(ctx, f"  VCs:        {va.vc_count}")
    emit(ctx, f"  Latency:    {result.get('latency', '?')}c")
    emit(ctx, f"  Area:       {report['area']['total_mm2']:.4f} mm²")
    emit(ctx, f"  Power:      {report['power']['total_w']:.4f} W")
    emit(ctx, f"  Fmax:       {report['timing']['max_freq_mhz']:.0f} MHz")
    emit(ctx, f"  Energy:     {report['energy']['per_bit_pj']:.3f} pJ/bit")
    emit(ctx, f"  Verify:     {sum(1 for c in vr_verify.checks if c['status']=='PASS')}/{len(vr_verify.checks)} PASS")
    emit(ctx, f"  Artifacts:  {', '.join(a.kind for a in artifacts)}")
    emit(ctx, f"  Manifest:   rev={report['manifest']['revision']} signed={len(report['manifest']['signature'])==64}")
    emit(ctx, f"  Hash:       {cr.guardrail_hash()[:16]}...")
    emit(ctx, f"  {'─' * 55}\n")

    output(ctx, report)


def _locate_serve_path(p: str) -> str:
    """Resolve a config/dataset path for the serving sim (delegates to
    core.serving — the single implementation; kept here for import
    stability of the CLI↔module contract tests)."""
    from veritx_dse.core.serving import locate_serve_path
    return locate_serve_path(p, llmsim_dir=LLMSIM_DIR, repo_dir=REPO,
                             dse_dir=DSE_DIR)


def _build_serve_cmd(args, cluster_config: str, dataset: str) -> list:
    """Assemble the `python -m serving` command line (delegates to
    core.serving — the single implementation; kept here for import
    stability of the CLI↔module contract tests)."""
    from veritx_dse.core.serving import build_serve_cmd
    return build_serve_cmd(args, cluster_config, dataset)


def _probe_serve(args) -> list:
    """Test seam: the exact command cmd_serve would run, without spawning it."""
    return _build_serve_cmd(args,
                            _locate_serve_path(args.cluster_config),
                            _locate_serve_path(args.dataset))


def cmd_serve(ctx: Ctx, args):
    """Full-stack LLM serving simulation: LLMServingSim + AstraSim + BookSim2."""
    import subprocess

    if not LLMSIM_DIR.exists():
        fail(ctx, f"LLMServingSim not found at {LLMSIM_DIR}")
        return

    # Phase 1 T1: refuse invalid executions before spawning. Same search
    # order as the old inline existence checks, now with structured
    # reasons (backend binary, dataset, cluster, parallelism, model
    # fit, converter capability, execution mode). Passing preflight
    # returns the resolved backend binaries for provenance identity.
    from veritx_dse.core.errors import ServingPreflightError
    from veritx_dse.core.serving import (
        fidelity_for_mode,
        mode_for_backend,
        preflight_serve,
        retired_from_csv,
        serving_provenance,
    )
    from veritx_dse.core.errors import ServingResultError
    from veritx_dse.core.runs import binary_identity

    def _resolve_abs(p: str) -> Path:
        for c in (Path(p), LLMSIM_DIR / p, LLMSIM_DIR / "astra-sim" / p):
            if c.exists():
                return c
        return LLMSIM_DIR / p

    try:
        serve_binaries = preflight_serve(
            llmsim_dir=LLMSIM_DIR,
            cluster_path=_resolve_abs(args.cluster_config),
            dataset_path=_resolve_abs(args.dataset),
            network_backend=args.network_backend,
            cycle_accurate=getattr(args, "cycle_accurate", False),
            cli_dtype=getattr(args, "dtype", None),
        )
    except ServingPreflightError as e:
        fail(ctx, str(e))
        return

    # Phase 1 T3: execution identity is decided here, from requested
    # flags — never inferred from stdout wording after the fact.
    network_mode = mode_for_backend(
        args.network_backend, getattr(args, "cycle_accurate", False))
    fidelity = fidelity_for_mode(args.network_backend, network_mode)

    cluster_config = _locate_serve_path(args.cluster_config)
    dataset = _locate_serve_path(args.dataset)

    cmd = _build_serve_cmd(args, cluster_config, dataset)

    log(ctx, f"Running full-stack simulation: {args.network_backend} backend")
    log(ctx, f"Cluster: {Path(args.cluster_config).name}")
    log(ctx, f"Dataset: {Path(args.dataset).name} ({args.num_reqs} requests)")
    serve_timeout = _eff_timeout(args, 600)
    log(ctx, f"Timeout: {serve_timeout}s")
    emit(ctx)

    t0 = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(LLMSIM_DIR),
            timeout=serve_timeout,
            capture_output=False,  # Let output stream to terminal
        )
        elapsed = time.time() - t0

        if result.returncode == 0:
            # Phase 1 T3: exit 0 is necessary but not sufficient. Terminal
            # validation: every requested request retired per the
            # per-request CSV (when --output was given), then emit the
            # machine-readable result identity.
            try:
                retired = None
                if args.output:
                    retired = retired_from_csv(
                        Path(args.output).resolve())
                    if retired != args.num_reqs:
                        raise ServingResultError(
                            "RETIREMENT_MISMATCH",
                            f"serving exited 0 but retired {retired} of "
                            f"{args.num_reqs} requested "
                            f"(csv: {args.output})")
                record = {
                    **serving_provenance(
                        engine="llmservingsim",
                        network_backend=args.network_backend,
                        network_mode=network_mode,
                        semantic_losses=[],
                    ),
                    "fidelity": fidelity,
                    "requests_requested": args.num_reqs,
                    "requests_retired": retired,
                    "backend_binaries": [binary_identity(b)
                                         for b in serve_binaries],
                    "elapsed_wall_s": round(elapsed, 1),
                }
            except (ServingResultError, FileNotFoundError) as e:
                fail(ctx, f"Serving result invalid: {e}")
                return
            output(ctx, record)
            ok(ctx, f"Simulation completed in {elapsed:.1f}s "
                    f"[{network_mode}/{fidelity}]")
        else:
            fail(ctx, f"Simulation failed with exit code {result.returncode} "
                       f"(full simulator output is above — rerun with "
                       f"--log-level DEBUG for backend traces)")

    except subprocess.TimeoutExpired:
        fail(ctx, f"Simulation timed out after {serve_timeout}s")
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
    if not _require_file(ctx, args.json, "results JSON", kind=None):
        return
    args_json = _resolve_path(args.json)
    latex = generate_latex(ctx, args_json, args.caption, args.label)
    if args.out:
        out_path = Path(args.out)
        if out_path.suffix == '.html':
            # Generate HTML from LaTeX
            html = _latex_to_html(latex, args.caption or 'VeritX Report')
            out_path.write_text(html)
            ok(ctx, f"HTML: {args.out}")
        elif out_path.suffix == '.pdf':
            # Generate PDF via pdflatex (if available). The generated table is
            # a LaTeX *fragment* (meant for \input into a paper); wrap it in a
            # minimal document or pdflatex fails with "Environment table
            # undefined" — the fragment alone was never compilable.
            import tempfile, subprocess
            with tempfile.TemporaryDirectory() as tmpdir:
                tex_path = Path(tmpdir) / 'report.tex'
                tex_path.write_text(
                    "\\documentclass{article}\n"
                    "\\begin{document}\n"
                    + latex +
                    "\n\\end{document}\n")
                r = subprocess.run(['pdflatex', '-interaction=nonstopmode', '-output-directory', tmpdir, str(tex_path)],
                                   capture_output=True, text=True, timeout=30)
                pdf_path = Path(tmpdir) / 'report.pdf'
                if pdf_path.exists():
                    import shutil
                    shutil.copy2(pdf_path, out_path)
                    ok(ctx, f"PDF: {args.out}")
                else:
                    # pdflatex -interaction=nonstopmode prints errors on STDOUT,
                    # not stderr — surface whichever stream actually has content.
                    detail = (r.stderr or r.stdout)[-300:]
                    fail(ctx, f"PDF generation failed: {detail}")
        else:
            out_path.write_text(latex)
            ok(ctx, f"LaTeX: {args.out}")
    else:
        emit(ctx, latex)


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
            _bold = r'<b>\1</b>'
            row = "".join(f"<{tag}>{pattern.sub(_bold, c)}</{tag}>" for c in cells)
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

    _wizard_bailed = False

    def _ask(prompt, default=None, options=None):
        """Ask user for input with default and optional choices.

        On a TTY, empty input selects the default when one is given.
        On piped/EOF input, empty stdin selects the default too, BUT
        a non-empty line that does not match a known option (when one
        is provided) is treated as a bailout so scripted runs do not
        silently serialize nonsense defaults.
        """
        suffix = f" [{default}]" if default else ""
        opts = f" ({'/'.join(options)})" if options else ""
        try:
            val = input(f"  {prompt}{opts}{suffix}: ").strip()
        except EOFError:
            # Piped stdin at end: take the default (headless runs depend on it).
            emit(ctx)
            return default
        except KeyboardInterrupt:
            emit(ctx)
            raise
        if not val and default is not None:
            return default
        if options and val and val not in options:
            nonlocal _wizard_bailed
            _wizard_bailed = True
            raise KeyboardInterrupt
        return val

    def _ask_int(prompt, default, lo=None, hi=None):
        """Ask for integer with range validation."""
        while True:
            try:
                val = _ask(prompt, str(default))
            except KeyboardInterrupt:
                nonlocal _wizard_bailed
                _wizard_bailed = True
                raise
            if val is None:
                return default
            try:
                n = int(val)
            except (ValueError, TypeError):
                emit(ctx, f"    Enter a number")
                continue
            if lo is not None and n < lo:
                emit(ctx, f"    Must be >= {lo}")
                continue
            if hi is not None and n > hi:
                emit(ctx, f"    Must be <= {hi}")
                continue
            return n

    def _ask_bool(prompt, default=True):
        """Ask yes/no question.

        A scripted run that sends a non-yes/no token is treated as a
        bailout rather than silently coerced to False. The bailout is
        implemented by raising KeyboardInterrupt so the wizard's top-level
        handler can leave no artifact behind.
        """
        suffix = " [Y/n]" if default else " [y/N]"
        try:
            val = input(f"  {prompt}{suffix}: ").strip().lower()
        except EOFError:
            emit(ctx)
            return default
        except KeyboardInterrupt:
            emit(ctx)
            raise
        if not val:
            return default
        if val not in ("y", "yes", "true", "1", "n", "no", "false", "0"):
            nonlocal _wizard_bailed
            _wizard_bailed = True
            raise KeyboardInterrupt
        return val in ("y", "yes", "true", "1")

    emit(ctx)
    emit(ctx, "  \033[1mVeritX Init Wizard\033[0m")
    emit(ctx, "  Generate a CompileRequest for your NoC design.")
    emit(ctx)

    # ── Step 0: Abort contract ──
    # On a TTY, Ctrl-C is a normal exit. On scripted input, the
    # _ask helpers raise KeyboardInterrupt for bad non-empty tokens;
    # that exception is caught below so the command can leave no JSON
    # behind and exit nonzero, which distinguishes "wizard finished"
    # from "wizard bailed".

    try:
    # ── Step 1: Workload ──
        emit(ctx, "  \033[1mStep 1/5: Workload\033[0m")
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
        emit(ctx)

        # ── Step 2: Agents ──
        emit(ctx, "  \033[1mStep 2/5: Agents\033[0m")
        n_compute = _ask_int("Number of compute tiles", tp * ep if mf == ModelFamily.MOE else tp, lo=1)
        n_hbm = _ask_int("Number of HBM controllers", max(1, n_compute // 4), lo=0)
        n_nic = _ask_int("Number of NICs", 0, lo=0)
        data_width = _ask_int("Data width (bits)", 256, lo=32)
        emit(ctx)

        # ── Step 3: Requirements ──
        emit(ctx, "  \033[1mStep 3/5: Requirements\033[0m")
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
                    latency_ceiling_cycles=ceiling,                    binding=_ask_bool("Binding (must meet)?", True),
                    ))
            elif qos == "bandwidth":
                floor = _ask_int("Bandwidth floor (Gbps)", 100, lo=1)
                requirements.append(Requirement(
                    qos_class=qos_map[qos],
                    bandwidth_floor_gbps=floor,
                    binding=_ask_bool("Binding (must meet)?", True),
                ))
        emit(ctx)

    # ── Step 4: Dependencies ──
        emit(ctx, "  \033[1mStep 4/5: Dependencies\033[0m")
        emit(ctx, "  Blocking dependencies can form deadlock cycles → VC derivation.")
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
            emit(ctx, f"    Added: {src} → {dst} ({kind_str})")
        emit(ctx)

        # ── Step 5: Topology ──
        emit(ctx, "  \033[1mStep 5/5: Topology\033[0m")
        topo = _ask("Topology family", "mesh", ["mesh", "torus", "gec", "concentrated_mesh"])
        topo_map = {
            "mesh": TopologyFamily.MESH,
            "torus": TopologyFamily.TORUS,
            "gec": TopologyFamily.GEC,
            "concentrated_mesh": TopologyFamily.CONCENTRATED_MESH,
        }
        tf = topo_map.get(topo, TopologyFamily.MESH)
        radix = _ask_int("Radix (k)", 8, lo=2) if _ask_bool("Set custom radix?", False) else None
        emit(ctx)

        # ── Build CompileRequest ──
        if _wizard_bailed:
            fail(ctx, "Init wizard aborted — no CompileRequest written")
            return

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
        # Absolute default (Phase 4 follow-up): the old relative f-string
        # landed wherever the caller happened to run from.
        out_path = args.out or str(TRACK_RUNS_DIR / "compile_requests" /
                                   f"{model_name.lower().replace(' ', '_')}.json")
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
        emit(ctx)
        emit(ctx, f"  \033[32m✓ Next: veritx compile {out_path}\033[0m")
        emit(ctx)

        output(ctx, d)
    except KeyboardInterrupt:
        fail(ctx, "Init wizard aborted — no CompileRequest written")
        return


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
    parser.add_argument("--list-commands", action="store_true",
                        help=argparse.SUPPRESS)  # hidden: machine-readable registry dump (Phase 3a)
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # Top-level subcommand list derived from COMMANDS (single source).
    _top_ps = {}
    for _cn, _cm in COMMANDS.items():
        _top_ps[_cn] = sub.add_parser(_cn, help=_cm["help"])
    # trace
    p_trace = _top_ps["trace"]
    ts = p_trace.add_subparsers(dest=_SUB_DESTS["trace"])

    _trace_ps = {}
    for _sn, _sm in COMMANDS["trace"]["subcommands"].items():
        _trace_ps[_sn] = ts.add_parser(_sn, help=_sm["help"])
    p_chakra = _trace_ps["chakra"]
    p_chakra.add_argument("et_dir")
    p_chakra.add_argument("--npu-map", dest="npu_map")
    p_chakra.add_argument("--speedup", type=float)
    p_chakra.add_argument("--nodes", type=int, default=DEFAULT_NODES)
    p_chakra.add_argument("--out", default=str(TRACK_RUNS_DIR / "traces" / "input.trace"))
    p_chakra.add_argument("--pkt-flits", type=int, default=None,
                          help="Flits per packet (default: 16-flit cap). Larger packets cut "
                          "header overhead but raise per-hop latency; smaller ones do the "
                          "reverse. Conservation holds at any setting (last packet trimmed).")

    p_model = _trace_ps["model"]
    p_model.add_argument("model")
    p_model.add_argument("--nodes", type=int, default=DEFAULT_NODES)
    p_model.add_argument("--out", default=str(TRACK_RUNS_DIR / "traces" / "input.trace"))

    p_hpc = _trace_ps["hpc"]
    p_hpc.add_argument("trace_file")
    p_hpc.add_argument("--nodes", type=int, default=DEFAULT_NODES)
    p_hpc.add_argument("--out", default=str(TRACK_RUNS_DIR / "traces" / "input.trace"))

    p_slice = _trace_ps["slice"]
    p_slice.add_argument("--trace", required=True)
    p_slice.add_argument("--classes", required=True)
    p_slice.add_argument("--out", required=True)
    p_slice.add_argument("--renumber", action="store_true")

    p_info = _trace_ps["info"]
    p_info.add_argument("trace")

    p_ext = _trace_ps["extract"]
    p_ext.add_argument("trace")
    p_ext.add_argument("--burst", type=int,
                       help="Copy the FIRST N packets (times shifted to t=0). "
                            "Not the Nth burst — use trace info to size N.")
    p_ext.add_argument("--uniform", action="store_true")
    p_ext.add_argument("--out", required=True)

    p_val = _trace_ps["validate"]
    p_val.add_argument("trace")

    # synthesize
    p_synth = _top_ps["synthesize"]
    ss = p_synth.add_subparsers(dest=_SUB_DESTS["synthesize"])

    _synth_ps = {}
    for _sn, _sm in COMMANDS["synthesize"]["subcommands"].items():
        _synth_ps[_sn] = ss.add_parser(_sn, help=_sm["help"])
    p_bo = _synth_ps["bo"]
    p_bo.add_argument("--nodes", type=int, default=DEFAULT_NODES)
    # --trace alias (Phase 4e vocabulary): every other trace-taking command
    # spells it --trace; --traffic stays working. (--traces/--matrix are
    # genuinely different: multi-file list / matrix file. Not aliases.)
    p_bo.add_argument("--traffic", "--trace", required=True)
    p_bo.add_argument("--iters", type=int, default=50)
    p_bo.add_argument("--seed", type=int)
    p_bo.add_argument("--scorer", default="analytical", choices=["analytical", "booksim"])
    p_bo.add_argument("--timeout", type=int, default=None,
                      help="Subprocess timeout in seconds (default: VERITX_TIMEOUT or 600)")

    p_iter = _synth_ps["iterative"]
    p_iter.add_argument("--trace", required=True)
    p_iter.add_argument("--method", default="rho", choices=["rho", "grpo"])
    p_iter.add_argument("--steps", type=int, default=50)
    p_iter.add_argument("--max-edges", type=int, default=120)
    p_iter.add_argument("--horizon", type=int, default=None,
                        help="RHO lookahead depth (default: 5)")
    p_iter.add_argument("--branch", type=int, default=None,
                        help="RHO rollouts per candidate (default: 5)")
    p_iter.add_argument("--group", type=int, default=None,
                        help="GRPO group size (default: 4)")
    p_iter.add_argument("--seed-anynet", default=None,
                        help="Starting topology; search node count comes from "
                             "this file (default: mesh 8x8 = 64 nodes)")
    p_iter.add_argument("--out", default=None)
    p_iter.add_argument("--timeout", type=int, default=None,
                        help="Subprocess timeout in seconds (default: VERITX_TIMEOUT or 600)")

    p_compile = _synth_ps["compile"]
    p_compile.add_argument("--results", required=True,
                           help="Synthesis results file (SynthResult records from "
                                "bo/iterative/pareto runs) forming the candidate set")
    p_compile.add_argument("--trace", required=True,
                           help="Workload trace used to (re)evaluate every candidate")
    p_compile.add_argument("--requirements", required=True,
                           help="E2 requirements as JSON array, e.g. "
                                "'[\"{\\\"qos_class\\\":\\\"latency_critical\\\","
                                "\\\"latency_ceiling_cycles\\\":5000,"
                                "\\\"binding\\\":true}\"]'")
    p_compile.add_argument("--nodes", type=int, default=DEFAULT_NODES,
                           help="Node count for the verdict filename")
    p_compile.add_argument("--seed", type=int, default=BOOKSIM_SEED,
                           help="BookSim seed (recorded in seed_policy; n=1)")
    p_compile.add_argument("--max-evals", type=int, default=None,
                           help="Declares requested_evaluations budget (recorded, not enforced)")
    p_compile.add_argument("--out", default=None,
                           help="Verdict evidence path (default: SYNTH_DIR/compile_verdict_N<nodes>.json)")
    p_compile.add_argument("--timeout", type=int, default=None,
                           help="Per-candidate evaluation timeout in seconds (default: VERITX_TIMEOUT or 600)")
    p_eval = _top_ps["evaluate"]
    es = p_eval.add_subparsers(dest=_SUB_DESTS["evaluate"])

    _eval_ps = {}
    for _sn, _sm in COMMANDS["evaluate"]["subcommands"].items():
        _eval_ps[_sn] = es.add_parser(_sn, help=_sm["help"])

    p_bs = _eval_ps["booksim"]
    p_bs.add_argument("--trace", required=True)
    p_bs.add_argument("--k", type=int, default=DEFAULT_K)
    from veritx_dse.model.presets import _TOPO_BY_BACKEND
    known_backends = sorted(_TOPO_BY_BACKEND.keys())
    p_bs.add_argument("--topo", default="mesh",
                        help=f"Topology backend (any BookSim topology: {', '.join(known_backends)}, or anynet path)")
    p_bs.add_argument("--routing", default=None,
                        help="Routing function (default: from preset, or dim_order)")
    p_bs.add_argument("--vcs", type=int, default=None,
                        help="Virtual channels (default: topology-derived; GEC/MECS auto-raises)")
    p_bs.add_argument("--vc-buf", type=int, default=None,
                        help="Buffers per VC (default: 8)")
    p_bs.add_argument("--sample-period", type=int, default=None,
                        help="BookSim sample period (default: trace-span-derived)")
    p_bs.add_argument("--max-samples", type=int, default=None,
                        help="BookSim max samples (default: 1 in trace mode)")
    p_bs.add_argument("--set", action="append", default=None, metavar="KEY=VAL",
                        help="BookSim knob override, repeatable (e.g. --set alloc_iters=2 --set arb_type=iSLIP). "
                             "Wins over named flags; recorded in the saved JSON.")
    p_bs.add_argument("--timeout", type=int, default=None,
                               help="BookSim timeout in seconds (default: VERITX_TIMEOUT or 120)")

    p_anynet = _eval_ps["anynet"]
    p_anynet.add_argument("--topo", required=True)
    p_anynet.add_argument("--trace", required=True)
    p_anynet.add_argument("--vcs", type=int, default=None,
                        help="Virtual channels (default: 4)")
    p_anynet.add_argument("--vc-buf", type=int, default=None,
                        help="Buffers per VC (default: 8)")
    p_anynet.add_argument("--sample-period", type=int, default=None,
                        help="BookSim sample period (default: trace-span-derived)")
    p_anynet.add_argument("--set", action="append", default=None, metavar="KEY=VAL",
                        help="BookSim knob override, repeatable (e.g. --set num_vcs=8). "
                             "Wins over named flags; recorded in the saved JSON.")
    p_anynet.add_argument("--timeout", type=int, default=None,
                                   help="BookSim timeout in seconds (default: VERITX_TIMEOUT or 120)")

    p_as = _eval_ps["astra"]
    p_as.add_argument("--ets", required=True,
                        help="Base workload file; per-rank <base>.<rank>.et must exist alongside it")
    p_as.add_argument("--system-config", default=str(TRACK_RUNS_DIR / "llm" / "qwen3_tp16" / "system.json"))
    p_as.add_argument("--network-config", default=str(TRACK_RUNS_DIR / "llm" / "qwen3_tp16" / "network.yml"))
    p_as.add_argument("--memory-config", default=str(TRACK_RUNS_DIR / "llm" / "qwen3_tp16" / "memory.json"))
    p_as.add_argument("--set", action="append", default=None, metavar="SECTION.KEY=VAL",
                        help="ASTRA config overlay, repeatable (e.g. --set system.scheduling-policy=FIFO "
                             "--set network.topology.Name=Ring). Sections: system, network, memory. "
                             "Applied to a run-dir copy; templates untouched; recorded in the saved JSON.")
    p_as.add_argument("--timeout", type=int, default=None,
                               help="ASTRA-sim timeout in seconds (default: VERITX_TIMEOUT or 300)")

    # topology (TopologyIR v0)
    p_topo = _top_ps["topology"]
    ts2 = p_topo.add_subparsers(dest=_SUB_DESTS["topology"])

    _topo_ps = {}
    for _sn, _sm in COMMANDS["topology"]["subcommands"].items():
        _topo_ps[_sn] = ts2.add_parser(_sn, help=_sm["help"])

    p_tr = _topo_ps["render"]
    p_tr.add_argument("--ir", required=True, help="TopologyIR JSON file")
    p_tr.add_argument("--format", default="ascii",
                      choices=["ascii", "anynet", "cfg", "yml", "json"],
                      help="Output format (default: ascii)")
    p_tr.add_argument("--out", default=None,
                      help="Write to file (default: stdout). cfg for anynet kinds requires --out.")

    p_ts = _topo_ps["stats"]
    p_ts.add_argument("--ir", required=True, help="TopologyIR JSON file")
    p_ts.add_argument("--out", default=None,
                      help="Write stats JSON to file (default: print table)")

    p_td = _topo_ps["diff"]
    p_td.add_argument("--ir", required=True, help="TopologyIR JSON file")
    p_td.add_argument("--ets", required=True,
                      help="Base workload file; per-rank <base>.<rank>.et must exist for all IR nodes")
    p_td.add_argument("--system-config", default=None,
                      help="ASTRA system.json (default: generated ring collective)")
    p_td.add_argument("--memory-config", default=None,
                      help="memory json (default: generated minimal)")
    p_td.add_argument("--timeout", type=int, default=None,
                      help="Per-leg timeout in seconds (default: VERITX_TIMEOUT or 300)")
    p_td.add_argument("--booksim-flit-bytes", type=int, default=64,
                      help="Flit size in bytes for the booksim leg (default: 64)")

    # certify
    p_cert = _top_ps["certify"]
    cs = p_cert.add_subparsers(dest=_SUB_DESTS["certify"])

    _cert_ps = {}
    for _sn, _sm in COMMANDS["certify"]["subcommands"].items():
        _cert_ps[_sn] = cs.add_parser(_sn, help=_sm["help"])

    p_flow = _cert_ps["flow"]
    p_flow.add_argument("--model", required=True)
    p_flow.add_argument("--topo", required=True)
    p_flow.add_argument("--timeout", type=int, default=None,
                        help="Subprocess timeout in seconds (default: VERITX_TIMEOUT or 300)")

    p_rtl = _cert_ps["rtl"]
    p_rtl.add_argument("--topo", required=True)
    p_rtl.add_argument("--build-dir", default=".")
    p_rtl.add_argument("--tier", default="quick", choices=["quick", "full"])
    p_rtl.add_argument("--timeout", type=int, default=None,
                       help="Subprocess timeout in seconds (default: VERITX_TIMEOUT or 600)")

    p_full = _cert_ps["full"]
    p_full.add_argument("--model", required=True)
    p_full.add_argument("--topo", required=True)
    p_full.add_argument("--build-dir", default=".")
    p_full.add_argument("--tier", default="quick", choices=["quick", "full"])
    p_full.add_argument("--timeout", type=int, default=None,
                        help="Per-stage timeout in seconds (default: VERITX_TIMEOUT or flow=300/rtl=600)")

    # run
    p_run = _top_ps["run"]
    p_run.add_argument("--model", default=None,
                       help="TrafficModel JSON source (short names resolve, "
                            "e.g. --model traffic or --model moe_8npu; "
                            "bare `veritx where --kind model` lists all)")
    p_run.add_argument("--spec", default=None,
                       help="Product intent spec JSON source (spec_translate) — "
                            "relative paths walk up from the current directory")
    p_run.add_argument("--trace", default=None,
                       help="Ready DSE .trace source (skips ingest conversion)")
    p_run.add_argument("--et", default=None,
                       help="Chakra .et workload source (file or dir)")
    p_run.add_argument("--nodes", type=int, default=DEFAULT_NODES)
    p_run.add_argument("--search", default="bo", choices=["bo", "iterative", "milp"])
    p_run.add_argument("--iterative-method", default="rho", choices=["rho", "grpo"])
    p_run.add_argument("--iters", type=int, default=50)
    p_run.add_argument("--scorer", default="analytical", choices=["analytical", "booksim"])
    p_run.add_argument("--cert", default="flow", choices=["flow", "deadlock", "rtl", "full", "none"])
    p_run.add_argument("--max-edges", type=int, default=120,
                       help="Max edges for synthesized topology")
    p_run.add_argument("--timeout", type=int, default=None,
                       help="Per-step budget in seconds for synthesis/evaluate/"
                            "certify (default: VERITX_TIMEOUT or 600)")
    p_run.add_argument("--astra-msg-mb", type=float, default=None,
                       help="ASTRA leg all-reduce payload in MiB (default: auto "
                            "~nodes KiB, capped 16; 16 MiB at >=32 nodes needs "
                            "30-40+ min of simulated time)")
    p_run.epilog = (
        "sources (exactly one): --model traffic model JSON | --spec product "
        "intent JSON | --trace DSE .trace | --et Chakra .et workload\n\n"
        "examples:\n"
        "  veritx run --model models/traffic_model.json --nodes 16\n"
        "  veritx run --spec product/examples/chiplet_2die.json --search milp\n"
        "  veritx run --et results/chakra_traces/llama7b.et --nodes 16\n"
        "  veritx run --trace runs/astra/input.trace --search iterative --iters 3")

    # sweep
    p_sweep = _top_ps["sweep"]
    p_sweep.add_argument("--trace", required=True)
    p_sweep.add_argument("--timeout", type=int, default=None,
                          help="Per-run timeout in seconds (default: VERITX_TIMEOUT or 60)")
    p_sweep.add_argument("--mode", default="latency", choices=["latency", "throughput"])
    p_sweep.add_argument("--ir", type=float, default=0.05)
    p_sweep.add_argument("--set", action="append", default=None, metavar="KEY=VAL",
                        help="BookSim knob override, repeatable (e.g. --set alloc_iters=2). "
                             "Recorded in sweep.json.")
    p_sweep.add_argument("--out-dir", default=None, metavar="DIR",
                        help="Run-output root (default: results/); t3 passes results/<CONFIG>.")

    # compare
    p_cmp = _top_ps["compare"]
    p_cmp.add_argument("--trace", required=True)
    p_cmp.add_argument("--topos", default="mesh_8x8,torus_8x8")
    p_cmp.add_argument("--anynet", action="append", default=[])
    p_cmp.add_argument("--seeds", type=int, default=3)
    p_cmp.add_argument("--seed-base", type=int, default=0, help="Base seed (0=auto-unique)")
    p_cmp.add_argument("--timeout", type=int, default=None,
                        help="Per-run timeout in seconds (default: VERITX_TIMEOUT or 60)")
    p_cmp.add_argument("--dense", choices=list(DENSE_PRESETS.keys()))
    p_cmp.add_argument("--mode", default="latency", choices=["latency", "throughput"])
    p_cmp.add_argument("--ir", type=float, default=0.05)
    p_cmp.add_argument("--set", action="append", default=None, metavar="KEY=VAL",
                        help="BookSim knob override, repeatable (e.g. --set num_vcs=8 --set vc_buf_size=16). "
                             "Applies to every topology; recorded in compare.json. "
                             "system./network./memory. keys are reserved for ASTRA overlay.")
    p_cmp.add_argument("--memory", action="store_true",
                        help="DEPRECATED and refused (MEMORY-ROADMAP §2): the scalar "
                             "M/D/1 correction was topology-invariant and is not valid "
                             "memory evidence. Passing it fails the command closed.")
    p_cmp.add_argument("--banks", type=int, default=4, help="DEPRECATED with --memory (refused).")
    p_cmp.add_argument("--bank-bw", type=int, default=1024, help="DEPRECATED with --memory (refused).")
    p_cmp.add_argument("--sensitivity", nargs="+", metavar="IR",
                        help="Run sensitivity analysis at specified injection rates (e.g. --sensitivity 0.01 0.05 0.1 0.2)")
    p_cmp.add_argument("--out-dir", default=None, metavar="DIR",
                        help="Run-output root (default: results/); t3 passes results/<CONFIG> "
                             "so guided compares co-locate with their sweep and report.")

    # pareto
    p_par = _top_ps["pareto"]
    p_par.add_argument("--traces", required=True)
    p_par.add_argument("--topos", default="mesh_8x8,torus_8x8")
    p_par.add_argument("--anynet", default="")
    p_par.add_argument("--seeds", type=int, default=1)
    p_par.add_argument("--timeout", type=int, default=None,
                        help="Per-run timeout in seconds (default: VERITX_TIMEOUT or 60)")
    p_par.add_argument("--out", default="",
                       help="Output JSON path (default: results/pareto/<ts>_seed<seeds>/pareto.json)")

    # diff
    p_diff = _top_ps["diff"]
    p_diff.add_argument("run_a", nargs="?")
    p_diff.add_argument("run_b", nargs="?")

    # runs
    p_runs = _top_ps["runs"]
    p_runs.add_argument("--last", type=int, default=20)
    p_runs.add_argument("--run-id")

    # results
    p_results = _top_ps["results"]
    p_results.add_argument("--last", type=int, default=5)

    # status
    # where (usability: resolve any asset by short name)
    p_where = _top_ps["where"]
    p_where.add_argument("name", help="asset name, extension optional (e.g. test_dynamic, moe_8npu)")
    p_where.add_argument("--kind", default="trace",
                         choices=sorted(_ASSET_KINDS), help="asset class (default: trace)")

    # doctor (self-check battery)
    p_doc = _top_ps["doctor"]
    p_doc.add_argument("--level", default="quick", choices=["quick", "deep"],
                       help="quick: seams+bins+anchors (<5s). deep: + tiny live runs "
                            "of every command family (tens of seconds)")
    p_doc.add_argument("--llm", action="store_true",
                       help="append an LLM second opinion on the report + log tail "
                            "(needs VERITX_LLM_BASE_URL / VERITX_LLM_API_KEY; "
                            "advisory only — never changes the verdict)")
    p_doc.add_argument("--json-out", default=None,
                       help="write the full report JSON (incl. log tail + LLM review) "
                            "to this path for the self-improvement loop")

    # history (cross-run queries over the experiment store)
    p_hist = _top_ps["history"]
    p_hist.add_argument("--topo", help="filter by topology")
    p_hist.add_argument("--workload", help="filter by workload")
    p_hist.add_argument("--status", help="filter by status (ok, failed, error: ...)")
    p_hist.add_argument("--min-cycles", type=int, help="astrasim_cycles >= N")
    p_hist.add_argument("--limit", type=int, default=50, help="max rows (default 50)")
    p_hist.add_argument("--reindex", action="store_true",
                        help="re-scan result trees into the index first")

    # interact (usability: guided entry point; EOF-safe, still scriptable)
    p_inter = _top_ps["interact"]
    p_inter.add_argument("--kind", default="trace",
                         choices=sorted(_ASSET_KINDS), help="asset class to prompt for on a TTY")
    p_inter.add_argument("--no-prompt", action="store_true",
                         help="never prompt, even on a TTY")

    p_status = _top_ps["status"]
    p_status.add_argument("--last", type=int, default=10)

    # report
    p_report = _top_ps["report"]
    p_report.add_argument("--json", required=True)
    p_report.add_argument("--caption", default="Topology comparison")
    p_report.add_argument("--label", default="tab:compare")
    p_report.add_argument("--out")

    # ── baseline ──────────────────────────────────────────────
    p_bl = _top_ps["baseline"]
    p_bl.add_argument("--trace", required=True, help="Trace file to evaluate")
    p_bl.add_argument("--topos", default="mesh_8x8",
                       help="Your topologies to compare (comma-separated)")
    p_bl.add_argument("--anynet", action="append", default=[],
                       help="Custom .anynet file(s) to include")
    p_bl.add_argument("--timeout", type=int, default=None,
                       help="Per-run timeout in seconds (default: VERITX_TIMEOUT or 60)")
    p_bl.add_argument("--seeds", type=int, default=1)

    # ── compile (intent-to-fabric) ──────────────────────────────
    p_compile = _top_ps["compile"]
    p_compile.add_argument("request", help="Path to CompileRequest JSON file")
    p_compile.add_argument("--timeout", type=int, default=None,
                            help="BookSim timeout in seconds (default: VERITX_TIMEOUT or 120)")
    p_compile.add_argument("--output", "-o", help="Save results to JSON file")

    # ── init ──────────────────────────────────────────────────────
    p_init = _top_ps["init"]
    p_init.add_argument("--out", "-o", help="Output JSON path (default: runs/compile_requests/<model>.json)")

    # ── serve (full-stack LLM serving simulation) ──────────────────
    p_serve = _top_ps["serve"]
    p_serve.add_argument("--cluster-config", required=True, help="Cluster configuration JSON")
    p_serve.add_argument("--dataset", required=True, help="Workload dataset JSONL")
    p_serve.add_argument("--num-reqs", type=int, default=1, help="Number of requests to simulate")
    p_serve.add_argument("--network-backend", default="booksim", choices=["booksim", "analytical", "ns3"],
                          help="Network simulation backend")
    p_serve.add_argument("--output", help="Output directory for results")
    p_serve.add_argument("--timeout", type=int, default=None, help="Simulation timeout in seconds (default: VERITX_TIMEOUT or 600)")
    p_serve.add_argument("--log-level", default="WARNING", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                         help="LLMServingSim log level (module accepts DEBUG/INFO/WARNING/ERROR)")
    p_serve.add_argument("--no-cleanup", action="store_true", help="Keep intermediate files")
    p_serve.add_argument("--no-prefix-caching", action="store_true", help="Disable prefix caching")
    p_serve.add_argument("--cycle-accurate", action="store_true",
                         help="Full cycle-accurate network simulation via BookSim "
                              "(maps to downstream --no-booksim-replay-only, ~10x slower). "
                              "Required for any congestion/QoS claim; default replay "
                              "mode skips the network.")
    # Scheduler / batching (upstream defaults apply when unset — None means
    # "don't forward", so serving's own defaults stay the source of truth).
    p_serve.add_argument("--max-num-seqs", type=int, default=None)
    p_serve.add_argument("--max-num-batched-tokens", type=int, default=None)
    p_serve.add_argument("--long-prefill-token-threshold", type=int, default=None)
    p_serve.add_argument("--block-size", type=int, default=None)
    p_serve.add_argument("--npu-memory-utilization", type=float, default=None)
    p_serve.add_argument("--log-interval", type=float, default=None)
    p_serve.add_argument("--dtype", default=None,
                         choices=["float16", "bfloat16", "float32", "fp8", "int8"])
    p_serve.add_argument("--kv-cache-dtype", default=None, choices=["auto", "fp8"])
    p_serve.add_argument("--request-routing-policy", default=None,
                         choices=["LOAD", "RR", "RAND", "CUSTOM"])
    p_serve.add_argument("--expert-routing-policy", default=None,
                         choices=["BALANCED", "RR", "RAND", "CUSTOM"])
    p_serve.add_argument("--prefix-storage", default=None, choices=["None", "CPU", "CXL"])
    p_serve.add_argument("--skip-prefill", action="store_true")
    p_serve.add_argument("--save-trace-text", action="store_true")
    p_serve.add_argument("--enable-prefix-sharing", action="store_true")
    p_serve.add_argument("--enable-local-offloading", action="store_true")
    p_serve.add_argument("--enable-attn-offloading", action="store_true")
    p_serve.add_argument("--enable-sub-batch-interleaving", action="store_true")
    p_serve.add_argument("--no-chunked-prefill", action="store_true",
                         help="Disable chunked prefill (upstream default: enabled)")
    p_serve.add_argument("--no-block-copy", action="store_true",
                         help="Disable block-copy trace replay (upstream default: enabled)")
    p_serve.add_argument("--no-reserve-full-isl", action="store_true",
                         help="Allow partial-ISL admission (upstream default reserves full ISL)")

    # ── generate ──────────────────────────────────────────────────
    p_gen = _top_ps["generate"]
    gs = p_gen.add_subparsers(dest=_SUB_DESTS["generate"])

    _gen_ps = {}
    for _sn, _sm in COMMANDS["generate"]["subcommands"].items():
        _gen_ps[_sn] = gs.add_parser(_sn, help=_sm["help"])

    p_uvm = _gen_ps["uvm"]
    p_uvm.add_argument("--request", required=True, help="Path to CompileRequest JSON")
    p_uvm.add_argument("--out", default="runs/uvm", help="Output directory")
    p_uvm.add_argument("--nodes", type=int, default=DEFAULT_NODES, help="Number of network nodes")
    p_uvm.add_argument("--k", type=int, default=DEFAULT_K, help="Mesh dimension (sqrt of nodes)")

    return parser


# ── Canonical command registry (Phase 3a single source) ────────────────────
# Every veritx (sub)command is declared EXACTLY ONCE here. DISPATCH,
# _SUB_DESTS, build_parser(), and `veritx --list-commands` are all derived
# from this table — there is no second list to drift.
#
# t3_mode: how the t3 wrapper treats this veritx command.
#   "forward" = `t3 veritx <cmd> "$@"` passes through losslessly (default).
#   "blocked" = t3 refuses the guided-builder path; direct `veritx <cmd>`
#               still works. Only "evaluate astra" is blocked: the ASTRA
#               frontend is host-built (new glibc/protobuf) and cannot load
#               in-container (old libs) — see t3 cmd_astrasim container guard
#               and _veritx_sub "evaluate astra" builder guard. Run natively
#               from a host checkout instead.
COMMANDS = {
    "trace": {"help": "Ingest traffic data", "t3_mode": "forward",
              "sub_dest": "trace_cmd", "handler": None, "subcommands": {
        "chakra": {"help": "Chakra .et files", "t3_mode": "forward",
                   "handler": cmd_trace_chakra},
        "model": {"help": "TrafficModel JSON", "t3_mode": "forward",
                  "handler": cmd_trace_model},
        "hpc": {"help": "HPC MPI trace", "t3_mode": "forward",
                "handler": cmd_trace_hpc},
        "slice": {"help": "Slice trace by traffic class", "t3_mode": "forward",
                  "handler": cmd_trace_slice},
        "info": {"help": "Analyze trace characteristics", "t3_mode": "forward",
                 "handler": cmd_trace_info},
        "extract": {"help": "Extract burst or redistribute", "t3_mode": "forward",
                    "handler": cmd_trace_extract},
        "validate": {"help": "Validate trace format", "t3_mode": "forward",
                     "handler": cmd_trace_validate},
    }},
    "synthesize": {"help": "Topology search", "t3_mode": "forward",
                   "sub_dest": "synth_cmd", "handler": None, "subcommands": {
        "bo": {"help": "Bayesian optimization", "t3_mode": "forward",
               "handler": cmd_synthesize_bo},
        "iterative": {"help": "RHO/GRPO iterative search", "t3_mode": "forward",
                      "handler": cmd_synthesize_iterative},
        "compile": {"help": "Requirements-driven fabric compiler (Phase 13): "
                            "requirements gate a candidate set; "
                            "FEASIBLE / NO_FEASIBLE_DESIGN verdicts",
                    "t3_mode": "forward",
                    "handler": cmd_synthesize_compile},
    }},
    "evaluate": {"help": "Cycle-accurate scoring", "t3_mode": "forward",
                 "sub_dest": "eval_cmd", "handler": None, "subcommands": {
        "booksim": {"help": "BookSim2 mesh trace replay", "t3_mode": "forward",
                    "handler": cmd_evaluate_booksim},
        "anynet": {"help": "BookSim2 custom topology", "t3_mode": "forward",
                   "handler": cmd_evaluate_anynet},
        "astra": {"help": "ASTRA-sim backend", "t3_mode": "blocked",
                  "handler": cmd_evaluate_astra},
    }},
    "certify": {"help": "Certification", "t3_mode": "forward",
                "sub_dest": "cert_cmd", "handler": None, "subcommands": {
        "flow": {"help": "Flow-class certification", "t3_mode": "forward",
                 "handler": cmd_certify_flow},
        "rtl": {"help": "RTL certification matrix", "t3_mode": "forward",
                "handler": cmd_certify_rtl},
        "full": {"help": "Full certification (flow + rtl; every leg must pass)",
                 "t3_mode": "forward", "handler": cmd_certify_full},
    }},
    "run": {"help": "Full pipeline", "t3_mode": "forward",
            "sub_dest": None, "handler": cmd_run, "subcommands": None},
    "sweep": {"help": "Batch-evaluate topologies", "t3_mode": "forward",
              "sub_dest": None, "handler": cmd_sweep, "subcommands": None},
    "compare": {"help": "Head-to-head topology comparison", "t3_mode": "forward",
                "sub_dest": None, "handler": cmd_compare, "subcommands": None},
    "pareto": {"help": "Multi-workload Pareto", "t3_mode": "forward",
               "sub_dest": None, "handler": cmd_pareto, "subcommands": None},
    "runs": {"help": "List/inspect experiment runs", "t3_mode": "forward",
             "sub_dest": None, "handler": cmd_runs, "subcommands": None},
    "results": {"help": "Show latest results", "t3_mode": "forward",
                "sub_dest": None, "handler": cmd_results, "subcommands": None},
    "where": {"help": "Resolve an asset by short name to an absolute path",
              "t3_mode": "forward",
              "sub_dest": None, "handler": cmd_where, "subcommands": None},
    "doctor": {"help": "Self-check battery: seams, binaries, anchors, live legs; optional LLM review",
               "t3_mode": "forward",
               "sub_dest": None, "handler": cmd_doctor, "subcommands": None},
    "interact": {"help": "Guided quickstart (safe when piped: prints next steps)",
                 "t3_mode": "forward",
                 "sub_dest": None, "handler": cmd_interact, "subcommands": None},
    "history": {"help": "Query past runs across all result JSONs (sqlite index)",
                "t3_mode": "forward",
                "sub_dest": None, "handler": cmd_history, "subcommands": None},
    "status": {"help": "Show run history", "t3_mode": "forward",
               "sub_dest": None, "handler": cmd_status, "subcommands": None},
    "diff": {"help": "Compare two experiment runs", "t3_mode": "forward",
             "sub_dest": None, "handler": cmd_diff, "subcommands": None},
    "report": {"help": "Generate LaTeX table", "t3_mode": "forward",
               "sub_dest": None, "handler": cmd_report, "subcommands": None},
    "baseline": {"help": "Compare against published baseline topologies",
                 "t3_mode": "forward",
                 "sub_dest": None, "handler": cmd_baseline, "subcommands": None},
    "compile": {"help": "Intent-to-fabric pipeline from CompileRequest JSON",
                "t3_mode": "forward",
                "sub_dest": None, "handler": cmd_compile, "subcommands": None},
    "init": {"help": "Interactive wizard to generate a CompileRequest",
             "t3_mode": "forward",
             "sub_dest": None, "handler": cmd_init, "subcommands": None},
    "serve": {"help": "Full-stack LLM serving simulation (LLMServingSim + AstraSim + BookSim2)",
              "t3_mode": "forward",
              "sub_dest": None, "handler": cmd_serve, "subcommands": None},
    "topology": {"help": "TopologyIR: render/stats/diff one fabric across backends",
              "t3_mode": "forward",
              "sub_dest": "topo_cmd", "handler": None, "subcommands": {
        "render": {"help": "Render a TopologyIR file (ascii/anynet/cfg/yml/json)",
                   "t3_mode": "forward", "handler": cmd_topology_render},
        "stats": {"help": "Fabric stats for a TopologyIR file",
                  "t3_mode": "forward", "handler": cmd_topology_stats},
        "diff": {"help": "Same IR through BookSim + analytical legs (divergence report)",
                 "t3_mode": "forward", "handler": cmd_topology_diff},
    }},
    "generate": {"help": "Generate collateral (UVM, RTL, reports)",
                 "t3_mode": "forward",
                 "sub_dest": "gen_cmd", "handler": None, "subcommands": {
        "uvm": {"help": "Generate UVM testbench", "t3_mode": "forward",
                "handler": cmd_generate_uvm},
    }},
}


def _list_commands_data() -> list:
    """Machine-readable command list for `veritx --list-commands` and t3 selfcheck.

    Flat rows: {"name": "trace" | "trace chakra" | ..., "t3_mode": ...}.
    Branch parents ("trace", "synthesize", ...) are included with their own
    t3_mode so t3 can diff both levels from a single source.
    """
    rows = []
    for _c, _m in COMMANDS.items():
        rows.append({"name": _c, "t3_mode": _m["t3_mode"]})
        for _s, _sm in (_m["subcommands"] or {}).items():
            rows.append({"name": f"{_c} {_s}", "t3_mode": _sm["t3_mode"]})
    return rows


# Derived — never edited by hand. Single source is COMMANDS above.
DISPATCH = {
    _c: ({_s: _sm["handler"] for _s, _sm in _m["subcommands"].items()}
         if _m["subcommands"] else _m["handler"])
    for _c, _m in COMMANDS.items()
}

_SUB_DESTS = {
    _c: _m["sub_dest"] for _c, _m in COMMANDS.items() if _m["sub_dest"]
}


def main():
    # Fail fast on missing third-party deps BEFORE any work runs. The CLI
    # executes off PYTHONPATH in environments no installer verified (host
    # shells, the tools container, CI); a missing dist used to surface as a
    # bare ModuleNotFoundError deep inside a command, after simulations had
    # already burned minutes. The requirement list is derived from
    # pyproject.toml (core.deps), never hardcoded here.
    from ..core.deps import missing_distributions
    _missing = missing_distributions()
    if _missing:
        early_error(
            "  ✗ missing Python dependencies: " + ", ".join(_missing) + "\n"
            "    veritx requires everything in dse/pyproject.toml "
            "[project].dependencies.\n"
            "    Fix (native):  pip install -e tracks/t3-topology/dse\n"
            "    Fix (container): rebuild the veritx-tools-base image "
            "(Dockerfile installs the locked deps)."
        )
        sys.exit(1)
    from .. import __version__
    parser = build_parser()
    args = parser.parse_args()

    # Build context first so every output path (including --list-commands
    # and the no-command help) goes through Ctx helpers, never bare print().
    raw_seed = getattr(args, "seed", 0)
    if raw_seed == 0:
        # Auto-generate unique seed from timestamp + PID
        import time, os
        raw_seed = int(time.time() * 1000) % 10000000 + os.getpid() % 1000
    try:
        ctx = Ctx(
            verbosity=0 if args.quiet else (2 if args.verbose else 1),
            json_mode=getattr(args, "json", False),
            output_file=getattr(args, "output", None),
            log_file=getattr(args, "log", None),
            seed=raw_seed,
        )
    except OSError as e:
        # --log with an uncreatable path used to escape as a raw traceback.
        early_error(f"  ✗ --log unusable: {e}")
        sys.exit(1)

    # Hidden machine-readable registry dump (Phase 3a): name + t3_mode per
    # command, one JSON array on stdout (machine-clean). Used by
    # `t3 selfcheck` to fail loudly on drift. Works with or without a
    # subcommand; always exits 0 (no fail() marking).
    if getattr(args, "list_commands", False):
        emit(ctx, json.dumps(_list_commands_data(), indent=2))
        ctx.close()
        return

    if not args.command:
        emit(ctx, f"VeritX v{__version__}")
        parser.print_help()
        ctx.close()
        return

    try:
        handler = DISPATCH.get(args.command)
        if handler is None:
            parser.print_help()
            return

        _exit_override = None
        if isinstance(handler, dict):
            # Subcommand dispatch
            sub_key = getattr(args, _SUB_DESTS.get(args.command, f"{args.command}_cmd"), None)
            if sub_key is None or sub_key not in handler:
                # Parent command with no/invalid subcommand: print help and
                # exit 0 (the normal argparse parent-command behavior).
                parser.parse_args([args.command, "--help"])
                return
            _res = handler[sub_key](ctx, args)
            if args.command == "run" and isinstance(_res, int):
                _exit_override = _res
        else:
            _res = handler(ctx, args)
            if args.command == "run" and isinstance(_res, int):
                _exit_override = _res

    except SystemExit:
        raise
    except KeyboardInterrupt:
        diag(ctx, "\nInterrupted.")
        sys.exit(130)
    except BookSimError as e:
        fail(ctx, str(e))
        if e.stderr:
            for line in e.stderr.splitlines()[-5:]:
                diag(ctx, f"    {line}")
        sys.exit(1)
    except TimeoutError as e:
        fail(ctx, str(e))
        sys.exit(1)
    except Exception as e:
        fail(ctx, f"{args.command} failed: {e}")
        sys.exit(1)
    finally:
        # fail() marks soft errors (missing files, bad args) that handlers
        # recover from and return; the process must still exit nonzero so
        # scripts and CI never read a failed run as success.
        ctx.close()
        _cleanup_stale_temp_dirs()
        if _exit_override is not None:
            sys.exit(_exit_override)
        if ctx.failed and sys.exc_info()[1] is None:
            sys.exit(1)


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
