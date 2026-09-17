"""veritx_dse.pipeline — High-level pipeline orchestration.

Composes booksim + traces modules into complete workflows:
  - Full pipeline (trace → synthesize → evaluate → certify)
  - Multi-workload Pareto comparison
  - Run history and diff
  - LaTeX report generation
"""
from __future__ import annotations

import json
import math
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.errors import BookSimError, TimeoutError, TraceError
from ..core.logging import Ctx, log, ok, fail, verbose, banner, emit, diag
from ..simulation.booksim import (
    detect_trace_stats, run_topology_eval,
    run_sweep, find_booksim_bin, build_config, run_booksim, topo_size,
)
from ..model.presets import (
    Topology, SWEEP_TOPOS, DENSE_PRESETS, lookup_topo, make_anynet_topo,
    count_anynet_edges, check_anynet_connected,
)


# ── Path constants ──────────────────────────────────────────────────────────
from veritx_dse.core.paths import REPO, RUNS_DIR, new_run_dir


def _repo_root() -> Path:
    return REPO


def _runs_dir() -> Path:
    return RUNS_DIR

def _experiments_dir() -> Path:
    return _runs_dir() / "experiments"


# ── Compare ─────────────────────────────────────────────────────────────────

@dataclass
class CompareResult:
    """Aggregated comparison of topologies."""
    trace: str
    seeds: list[int]
    results: list[dict]
    summary: list[dict]  # per-topology aggregation
    sim_type: str = "latency"
    ir: float = 0.05
    overrides: dict = field(default_factory=dict)
    # Phase 8: machine-readable ComparisonSpec verdict (None only for
    # callers predating the gate — tests, one-off tools). Consumers must
    # treat a missing verdict as uncertified, never as valid-by-default.
    verdict: dict | None = None

    def to_dict(self) -> dict:
        return {
            "trace": self.trace,
            "seeds": self.seeds,
            "sim_type": self.sim_type,
            "ir": self.ir,
            "overrides": self.overrides,
            "results": self.results,
            "summary": self.summary,
            "verdict": self.verdict,
        }


def run_compare(
    ctx: Ctx,
    trace_path: str,
    topo_specs: list[tuple[str, Topology]],
    *,
    seeds: int = 3,
    seed_base: int = 42,
    timeout: int = 60,
    sim_type: str = "latency",
    ir: float = 0.05,
    overrides: dict | None = None,
    comparison: dict | None = None,
) -> CompareResult:
    """Run multi-seed comparison across topologies.

    topo_specs: list of (display_name, Topology) pairs.
    comparison: optional ComparisonSpec intent dict (§2). When omitted,
        a default intent is used: DESIGN_COMPARISON with no declared
        variables — so any material difference between candidates fails
        closed rather than silently ranking.
    Returns CompareResult with per-topology aggregation + verdict.
    """
    repo = _repo_root()
    all_results = []
    total = len(topo_specs) * seeds
    t_start = time.time()
    # Trace's highest addressed node feeds the anynet size pre-check below
    # (a 4-node net handed a 33-node trace delivers zero packets and
    # measures nothing). Parsed lazily: pure-preset batches never pay for
    # it, and an unreadable trace defers its diagnosis to the real run.
    stats: Any = None

    for i, (display_name, topo) in enumerate(topo_specs):
        # Connectivity pre-check for custom graphs: BookSim hangs on
        # disconnected anynets and can dribble out a near-empty result
        # (e.g. 13 delivered packets) that would otherwise rank as a real
        # number. Skip with an error record — no summary row, no bogus rank.
        if topo.backend == "anynet":
            if stats is None:
                try:
                    stats = detect_trace_stats(trace_path)
                except TraceError:
                    stats = False  # unreadable: the real run reports why
            _nf = (topo.params or {}).get("network_file", "")
            # Three distinct failures, three distinct messages — a missing
            # file (bad glob/typo), a corrupt file (parses to nothing), and
            # a disconnected graph must never collapse into one shrug.
            if not _nf or not Path(_nf).is_file():
                _reason = f"anynet file not found: {_nf or '(topology carries no network_file)'}"
                _conn, _nn, _nun = False, 0, 0
            else:
                _conn, _nn, _nun = check_anynet_connected(_nf)
                _reason = ("file parses to zero routers (invalid .anynet?)" if _nn == 0
                           else f"{_nun} of {_nn} nodes unreachable from node 0")
            if _conn and stats and stats.max_node >= _nn:
                _conn = False
                _reason = (f"trace addresses nodes 0..{stats.max_node} but this anynet "
                           f"has only {_nn} — remap the trace or use a larger net")
            if not _conn:
                _nn2, _ne2 = topo_size(topo)
                for seed_i in range(seeds):
                    all_results.append({
                        "name": display_name, "topology": topo.backend,
                        "error": f"disconnected anynet: {_reason}",
                        "nodes": _nn2, "edges": _ne2, "seed": seed_base + seed_i,
                    })
                log(ctx, f"  {display_name:<16} → SKIPPED ({_reason})")
                continue
        for seed_i in range(seeds):
            seed = seed_base + seed_i
            elapsed = time.time() - t_start
            log(ctx, f"[{i * seeds + seed_i + 1}/{total}] {display_name:<16} seed={seed:<3} ({elapsed:.0f}s elapsed)...")
            try:
                r = run_topology_eval(
                    ctx, topo, trace_path,
                    repo_root=repo, seed=seed, timeout=timeout,
                    sim_type=sim_type, ir=ir,
                    overrides=overrides,
                )
                r["name"] = display_name  # override topo.name with display name
                all_results.append(r)
                warn_flag = " [UNSTABLE]" if r.get("unstable") else ""
                # VeritX: rank on honest latency (arrival - trace timestamp).
                # The stock plat mean is ctime-based: qtime slots go stale
                # across idle gaps, inflating sparse-trace means 100x+.
                status = f"{r.get('honest_latency', r['latency']):.2f}c{warn_flag}"
                log(ctx, f"  {display_name:<16} seed={seed:<3} → {status}")
            except TimeoutError:
                _nn, _ne = topo_size(topo)
                all_results.append({
                    "name": display_name, "topology": topo.backend,
                    "error": "timeout", "nodes": _nn, "edges": _ne, "seed": seed,
                })
                log(ctx, f"  {display_name:<16} seed={seed:<3} → timeout")
            except BookSimError as e:
                _nn, _ne = topo_size(topo)
                all_results.append({
                    "name": display_name, "topology": topo.backend,
                    "error": str(e), "nodes": _nn, "edges": _ne, "seed": seed,
                })
                log(ctx, f"  {display_name:<16} seed={seed:<3} → {e}")

    # Aggregate per topology
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in all_results:
        groups[r["name"]].append(r)

    agg = []
    for display_name, _ in topo_specs:
        runs = groups[display_name]
        # VeritX: prefer honest latency (see above); fall back to plat mean
        # when the binary predates honest_avg (e.g. ASTRA-backed results).
        # None-valued latencies never enter the mean.
        valid = []
        for r in runs:
            if "latency" not in r:
                continue
            v = r.get("honest_latency", r["latency"])
            if isinstance(v, (int, float)):
                valid.append(v)
        nodes = next((r["nodes"] for r in runs if r.get("nodes")), "?") if runs else "?"
        edges = next((r["edges"] for r in runs if r.get("edges")), "?") if runs else "?"
        if valid:
            mean = statistics.mean(valid)
            std = statistics.stdev(valid) if len(valid) > 1 else 0.0
            n_unstable = sum(1 for r in runs if r.get("unstable"))
            agg.append({
                "name": display_name, "nodes": nodes, "edges": edges,
                "mean": mean, "std": std,
                "min": min(valid), "max": max(valid), "n": len(valid),
                "n_unstable": n_unstable,
            })
        else:
            # A failed candidate must stay VISIBLE in the comparison
            # (verified-PRD §15: silent exclusion hides exactly the runs
            # that invalidate the comparison — e.g. a 16-node topology
            # against a 64-node trace failing with out-of-range entries).
            # The entry carries the first error; the printer renders it
            # and the winner selection ignores it (no numeric mean).
            errs = [r.get("error", "?") for r in runs if "error" in r]
            agg.append({
                "name": display_name, "nodes": nodes, "edges": edges,
                "error": errs[0] if errs else "no valid runs",
                "n": 0,
            })

    # ── Phase 8: ComparisonSpec enforcement (fail closed) ─────────────
    # Every candidate row is fingerprinted (legacy adapter marks what it
    # cannot resolve); the verdict gates the winner claim in the printer.
    # Default intent declares nothing, so any material difference between
    # candidates refuses — ranking whatever ran was never valid.
    from ..core.comparison import (
        evaluate_comparability, fingerprint_from_legacy_row, resolve_intent,
    )
    # Default intent = the compare command's declared purpose (§4's own
    # example): "which topology gives lower latency?" — topology is the
    # experimental variable, everything else controlled. Legacy rows
    # carry display-name topology identity only (the adapter marks what
    # it cannot resolve, so vc/packetization/simulator stay unresolved
    # and the verdict uncertified). Any OTHER material difference —
    # node count, workload, seeds — refuses undeclared.
    intent = resolve_intent(comparison) if comparison else resolve_intent({
        "kind": "DESIGN_COMPARISON",
        "objectives": ["latency"],
        "experimental_variables": ["topology"],
        "controlled_dimensions": {},
    })
    fps = [fingerprint_from_legacy_row({**row, "trace": trace_path,
                                        "seed": seed_base})
           for row in agg]
    verdict = evaluate_comparability(fps, intent)
    verdict_dict = {
        "status": verdict.status,
        "comparison_kind": verdict.comparison_kind,
        "experimental_variables": verdict.experimental_variables,
        "differences": verdict.differences,
        "candidates": verdict.candidates,
        "certified": verdict.certified,
    }

    return CompareResult(
        trace=trace_path,
        seeds=list(range(seed_base, seed_base + seeds)),
        results=all_results,
        summary=agg,
        sim_type=sim_type,
        ir=ir,
        overrides=dict(overrides or {}),
        verdict=verdict_dict,
    )


def print_compare_table(ctx: Ctx, result: CompareResult) -> dict:
    """Print comparison table to stdout; return a machine-readable claim.

    Phase 8: the winner is claimed ONLY when the ComparisonSpec verdict
    is COMPARABLE. An INVALID_COMPARISON prints the exact differences
    (diagnostics, not booleans) and the returned claim says so — the
    historical warning-only behavior is enforcement now.
    """
    ok = [s for s in result.summary if "mean" in s]
    failed = [s for s in result.summary if "error" in s]
    verdict = result.verdict or {}
    comparable = verdict.get("status") == "COMPARABLE"

    has_unstable = any(s.get("n_unstable", 0) > 0 for s in ok)
    if has_unstable:
        emit(ctx, f"\n  {'Topology':<16} {'Nodes':>5} {'Edges':>6} {'Mean':>8} {'Std':>7} {'Min':>8} {'Max':>8} {'Runs':>4} {'Unstable':>8}")
        emit(ctx, f"  {'─' * 78}")
        for s in ok:
            unstable = s.get("n_unstable", 0)
            warn = f" {unstable}/{s['n']}" if unstable else ""
            emit(ctx, f"  {s['name']:<16} {s['nodes']:>5} {s['edges']:>6} "
                  f"{s['mean']:>7.2f}c {s['std']:>6.2f}c {s['min']:>7.2f}c "
                  f"{s['max']:>7.2f}c {s['n']:>4}{warn:>8}")
        emit(ctx, f"\n  \033[33mWARNING: Unstable simulations produce unreliable latency numbers.\033[0m")
        emit(ctx, f"  \033[33mReduce injection rate, increase sample_period, or use fewer seeds.\033[0m")
    else:
        emit(ctx, f"\n  {'Topology':<16} {'Nodes':>5} {'Edges':>6} {'Mean':>8} {'Std':>7} {'Min':>8} {'Max':>8} {'Runs':>4}")
        emit(ctx, f"  {'─' * 68}")
        for s in ok:
            emit(ctx, f"  {s['name']:<16} {s['nodes']:>5} {s['edges']:>6} "
                  f"{s['mean']:>7.2f}c {s['std']:>6.2f}c {s['min']:>7.2f}c "
                  f"{s['max']:>7.2f}c {s['n']:>4}")

    # Failed candidates: rendered, never silently dropped. The winner is
    # chosen only among candidates with numeric means.
    for s in failed:
        emit(ctx, f"  {s['name']:<16} {s['nodes']:>5} {s['edges']:>6}   FAIL — {s['error']}")
    if failed:
        emit(ctx, f"\n  \033[33m{len(failed)} candidate(s) FAILED and are excluded from ranking — "
              f"the winner is valid only among successful runs.\033[0m")

    # Winner — only among successfully measured candidates of a COMPARABLE
    # comparison (Phase 8: undeclared differences suppress the claim).
    if verdict.get("status") == "INVALID_COMPARISON":
        emit(ctx, f"\n  \033[31mCOMPARISON REFUSED — no winner is claimed.\033[0m")
        for d in verdict.get("differences", []):
            emit(ctx, f"  \033[31m{d['reason']}: {d['field']} "
                  f"({d.get('left')!r} vs {d.get('right')!r})\033[0m")
        emit(ctx, f"  \033[31mDeclare the differing dimensions as "
              f"experimental_variables in the comparison spec, or compare "
              f"like with like.\033[0m")
    elif len(ok) >= 2:
        agg_sorted = sorted(ok, key=lambda a: a["mean"])
        best = agg_sorted[0]
        worst = agg_sorted[-1]
        delta = (worst["mean"] - best["mean"]) / worst["mean"] * 100 if worst["mean"] > 0 else 0

        sig = ""
        if best["n"] > 1 and worst["n"] > 1:
            pooled_se = math.sqrt(best["std"] ** 2 / best["n"] + worst["std"] ** 2 / worst["n"])
            if pooled_se > 0:
                t_stat = (worst["mean"] - best["mean"]) / pooled_se
                sig = f" (t={t_stat:.1f})" + (" **" if abs(t_stat) > 2 else " *" if abs(t_stat) > 1.5 else " n.s.")

        if best["n"] < 2 or worst["n"] < 2:
            # One seed ⇒ stdev is 0.0 by construction, not measured
            # confidence — print n=1, never a ±0.00 that reads as certainty.
            emit(ctx, f"\n  Winner: {best['name']} ({best['mean']:.2f}c, n=1 — no spread sampled)")
        else:
            emit(ctx, f"\n  Winner: {best['name']} ({best['mean']:.2f}c ± {best['std']:.2f}c)")
        emit(ctx, f"  vs {worst['name']}: {delta:.1f}% faster{sig}")

    # Machine-readable claim (Phase 8): consumers (t3 TUI, compare.json)
    # read this instead of inferring validity from the presence of a
    # winner line. A missing verdict is uncertified by definition.
    winner_claimed = (comparable and len(ok) >= 2)
    return {
        "winner_claimed": winner_claimed,
        "certified": bool(winner_claimed and verdict.get("certified")),
        "verdict_status": verdict.get("status", "UNSPECIFIED"),
    }

    # NOTE: no save here — persistence belongs to the command layer
    # (cmd_compare writes results/compare/<ts>_seed<n>/compare.json); printing
    # must stay side-effect-free or every caller double-writes a run dir.


# ── Sweep ───────────────────────────────────────────────────────────────────

def print_sweep_table(ctx: Ctx, results: list[dict], sim_type: str):
    """Print sweep results table."""
    if sim_type == "throughput":
        emit(ctx, f"\n  {'Topology':<16} {'Nodes':>5} {'Edges':>6} {'Throughput':>10} {'Hops':>7} {'Status':<8}")
    else:
        emit(ctx, f"\n  {'Topology':<16} {'Nodes':>5} {'Edges':>6} {'Latency':>10} {'Hops':>7} {'Status':<8}")
    emit(ctx, f"  {'─' * 65}")

    for r in results:
        name = r.get("name", "?")
        nodes = r.get("nodes", "?")
        edges = r.get("edges", "?")
        if "latency" in r:
            # VeritX: show honest latency (arrival - trace timestamp); the
            # stock plat mean is qtime-based and inflates on sparse traces.
            lat = f"{r.get('honest_latency', r['latency']):.2f}c"
            hops = f"{r.get('hops', '-'):.1f}" if isinstance(r.get("hops"), (int, float)) else "-"
            tput = f"{r.get('throughput', '-'):.4f}" if isinstance(r.get("throughput"), (int, float)) else "-"
            status = "✓"
        else:
            lat = "-"
            hops = "-"
            tput = "-"
            status = r.get("error", "FAIL")[:6]
        emit(ctx, f"  {name:<16} {nodes:>5} {edges:>6} {lat:>10} {hops:>7} {tput:>8} {status:<8}")

    # Summary (ranked on honest latency, same reason as above)
    valid = [r for r in results if "latency" in r]
    if valid:
        key = lambda r: r.get("honest_latency", r["latency"])
        best = min(valid, key=key)
        worst = max(valid, key=key)
        emit(ctx, f"\n  Best: {best['name']} ({key(best):.2f}c)")
        emit(ctx, f"  Worst: {worst['name']} ({key(worst):.2f}c)")
        if key(worst) > 0:
            delta = (key(worst) - key(best)) / key(worst) * 100
            emit(ctx, f"  Spread: {delta:.1f}%")


# ── Run history ─────────────────────────────────────────────────────────────

def list_runs(ctx: Ctx, last: int = 20, run_id: str | None = None):
    """List or inspect past experiment runs."""
    exp_dir = _experiments_dir()
    if not exp_dir.exists():
        fail(ctx, f"No experiments directory yet ({exp_dir}) — run `veritx run` first")
        return

    if run_id:
        target = exp_dir / run_id
        if not target.exists():
            avail = sorted(p.name for p in exp_dir.iterdir() if p.is_dir())[-5:]
            hint = f" — recent: {', '.join(avail)}" if avail else ""
            fail(ctx, f"Run not found: {run_id} (looked in {exp_dir}{hint})")
            return
        manifest_path = target / "manifest.json"
        if manifest_path.exists():
            try:
                m = json.loads(manifest_path.read_text())
            except (json.JSONDecodeError, OSError):
                m = {}
            banner(ctx, f"Run: {run_id}")
            for k, v in m.items():
                emit(ctx, f"  {k:<25} {v}")
            emit(ctx, f"\n  Files in {target}:")
            for f in sorted(target.iterdir()):
                size = f.stat().st_size if f.is_file() else 0
                emit(ctx, f"    {f.name:<30} {size:>8,}B")
        else:
            fail(ctx, f"No manifest in {target}")
        return

    runs = sorted(exp_dir.iterdir(), reverse=True)[:last]
    if not runs:
        fail(ctx, "No runs found")
        return

    emit(ctx, f"\n\033[1m  VeritX Experiment Runs (last {len(runs)})\033[0m\n")
    emit(ctx, f"  {'ID':<22} {'Timestamp':<20} {'Dur':>8} {'Model':<20} {'Latency':>10} {'Cert':<6}")
    emit(ctx, f"  {'─' * 82}")

    for run in runs:
        manifest = run / "manifest.json"
        if manifest.exists():
            try:
                m = json.loads(manifest.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            ts = m.get("timestamp", "?")[:19]
            dur = f"{m.get('duration_s', '?')}s"
            # `model` is None for trace/et/spec sources — Path(None) crashed
            # `veritx runs` with a raw TypeError. Any non-str renders as '-'.
            raw_model = m.get("model")
            model = Path(raw_model).name[:20] if isinstance(raw_model, str) and raw_model else "-"
            lat = m.get("eval", {}).get("latency", "?") if isinstance(m.get("eval"), dict) else "?"
            lat_str = f"{lat:.1f}c" if isinstance(lat, (int, float)) else str(lat)
            cert = m.get("cert", "-")
            if isinstance(cert, dict):
                cert = cert.get("error", "?")[:6]
        else:
            ts, dur, model, lat_str, cert = "?", "?", "?", "?", "?"
        emit(ctx, f"  {run.name:<22} {ts:<20} {dur:>8} {model:<20} {lat_str:>10} {str(cert):<6}")


def show_results(ctx: Ctx, last: int = 5):
    """Show latest comparison/sweep results."""
    booksim_dir = _runs_dir() / "booksim"
    if not booksim_dir.exists():
        fail(ctx, f"No booksim results yet ({booksim_dir}) — run `veritx compare` or `veritx sweep` first")
        return

    jsons = sorted(booksim_dir.glob("compare_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    jsons += sorted(booksim_dir.glob("sweep_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    jsons += sorted(booksim_dir.glob("pareto*.json"), key=lambda f: f.stat().st_mtime, reverse=True)

    if not jsons:
        fail(ctx, f"No results in {booksim_dir}/ (looked for compare_*.json, sweep_*.json, pareto*.json)")
        return

    jsons = jsons[:last]
    for jf in jsons:
        try:
            data = json.loads(jf.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        name = jf.stem
        ts = datetime.fromtimestamp(jf.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        emit(ctx, f"\n  \033[1m{name}\033[0m ({ts})")

        if "summary" in data and isinstance(data["summary"], list):
            emit(ctx, f"  {'Topology':<16} {'Mean':>8} {'Std':>7} {'Min':>8} {'Max':>8} {'Runs':>4}")
            emit(ctx, f"  {'─' * 52}")
            for s in data["summary"]:
                emit(ctx, f"  {s['name']:<16} {s['mean']:>7.2f}c {s['std']:>6.2f}c "
                      f"{s['min']:>7.2f}c {s['max']:>7.2f}c {s['n']:>4}")
        elif isinstance(data, list) and all(isinstance(r, dict) for r in data):
            emit(ctx, f"  {'Topology':<16} {'Latency':>10} {'Hops':>7} {'Status':<8}")
            emit(ctx, f"  {'─' * 45}")
            for r in data:
                n = r.get("name", "?")
                if "latency" in r and isinstance(r.get("honest_latency", r.get("latency")), (int, float)):
                    emit(ctx, f"  {n:<16} {r.get('honest_latency', r['latency']):>9.2f}c {r.get('hops', '-'):>7} {'✓':<8}")
                elif "latency" in r:
                    emit(ctx, f"  {n:<16} {'-':>10} {'-':>7} {'BADLAT':<8}")
                else:
                    emit(ctx, f"  {n:<16} {'-':>10} {'-':>7} {r.get('error', 'FAIL')[:8]:<8}")
        else:
            emit(ctx, f"  {json.dumps(data, indent=None)[:200]}")


# ── Diff ────────────────────────────────────────────────────────────────────

def diff_runs(ctx: Ctx, run_a: str | None = None, run_b: str | None = None):
    """Compare two experiment runs side-by-side."""
    exp_dir = _experiments_dir()
    if not exp_dir.exists():
        fail(ctx, f"No experiments yet ({exp_dir}) — run `veritx run` first")
        return

    runs = sorted(exp_dir.iterdir(), reverse=True)
    if len(runs) < 2:
        fail(ctx, f"Need at least 2 runs to diff, found {len(runs)} in {exp_dir}")
        return

    # Resolve run arguments to actual directories.
    # - A full path or existing dir is used as-is.
    # - A bare run_id is looked up inside the experiments dir.
    # - An omitted side is filled from the newest runs ONLY when both
    #   sides are omitted; otherwise it is an error.
    def _resolve_run(run_arg: str | None, allow_default: bool):
        if run_arg is None:
            if not allow_default:
                return None
            if len(runs) < 1:
                return None
            return runs[0]
        p = Path(run_arg)
        if p.exists():
            return p
        cand = exp_dir / run_arg
        if cand.exists():
            return cand
        return None

    a = _resolve_run(run_a, allow_default=(run_a is None and run_b is None))
    b = _resolve_run(run_b, allow_default=(run_a is None and run_b is None))

    if a is None:
        if run_a is None and run_b is None:
            fail(ctx, "No experiment runs found")
        else:
            fail(ctx, f"Run not found: {run_a or run_b}")
        return 1
    if b is None:
        fail(ctx, f"Run not found: {run_b or run_a}")
        return 1

    def _load(run):
        m = run / "manifest.json"
        if not m.exists():
            return {}
        try:
            return json.loads(m.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    mA = _load(a)
    mB = _load(b)

    if not mA and not mB:
        fail(ctx, f"Neither run has a readable manifest: {a.name}, {b.name}")
        return 1

    banner(ctx, f"Diff: {a.name} vs {b.name}")

    all_keys = sorted(set(list(mA.keys()) + list(mB.keys())))
    for key in all_keys:
        vA = mA.get(key, "—")
        vB = mB.get(key, "—")
        if key == "eval" and isinstance(vA, dict) and isinstance(vB, dict):
            latA = vA.get("latency", "?")
            latB = vB.get("latency", "?")
            if isinstance(latA, (int, float)) and isinstance(latB, (int, float)):
                delta = latB - latA
                pct = delta / latA * 100 if latA else 0
                sign = "+" if delta > 0 else ""
                emit(ctx, f"  {key + '.latency':<30} {latA:>10.2f}c  →  {latB:>10.2f}c  ({sign}{delta:.2f}c / {sign}{pct:.1f}%)")
            else:
                emit(ctx, f"  {key:<30} {str(vA):>10}  →  {str(vB):>10}")
        elif isinstance(vA, dict) and isinstance(vB, dict):
            for k2 in sorted(set(list(vA.keys()) + list(vB.keys()))):
                emit(ctx, f"  {key + '.' + k2:<30} {str(vA.get(k2, '—')):>10}  →  {str(vB.get(k2, '—')):>10}")
        else:
            if vA != vB:
                emit(ctx, f"  {key:<30} {str(vA):>10}  →  {str(vB):>10}  \033[33mCHANGED\033[0m")
            else:
                emit(ctx, f"  {key:<30} {str(vA):>10}  =  {str(vB):>10}")

    files_a = set(f.name for f in a.iterdir()) if a.exists() else set()
    files_b = set(f.name for f in b.iterdir()) if b.exists() else set()
    only_a = files_a - files_b
    only_b = files_b - files_a
    if only_a or only_b:
        emit(ctx, f"\n  Files only in {a.name}: {', '.join(sorted(only_a)) or 'none'}")
        emit(ctx, f"  Files only in {b.name}: {', '.join(sorted(only_b)) or 'none'}")


# ── LaTeX report ────────────────────────────────────────────────────────────

def generate_latex(ctx: Ctx, json_path: str, caption: str, label: str) -> str:
    """Generate a LaTeX table from compare, pareto, or sweep JSON results."""
    try:
        data = json.loads(Path(json_path).read_text())
    except (json.JSONDecodeError, OSError) as e:
        return f"% Error reading {json_path}: {e}"

    if isinstance(data, list):
        # `veritx sweep` output: bare list of per-topology results
        # [{name, latency, hops, edges, ...}]. Prefer honest latency
        # (arrival - trace timestamp) over the qtime-based plat mean.
        rows = [{**r, "latency": r["honest_latency"]} if "honest_latency" in r else r for r in data]
        cols = ["Topology", "Edges", "Latency", "Hops"]
        fields = ["name", "edges", "latency", "hops"]
        mean_key = "latency"
    elif "summary" in data:
        rows = data["summary"]
        cols = ["Topology", "Edges", "Mean", "Std", "Min", "Max"]
        fields = ["name", "edges", "mean", "std", "min", "max"]
        mean_key = "mean"
    elif "agg" in data:
        rows = data["agg"]
        trace_keys = data.get("traces", [])
        cols = ["Topology", "Edges"] + [t[:12] for t in trace_keys] + ["Mean"]
        fields = ["name", "edges"] + [f"lat_{t}" for t in trace_keys] + ["mean_lat"]
        mean_key = "mean_lat"
    else:
        raise ValueError(f"Unknown JSON format in {json_path}")

    if not rows:
        return f"% No rows in {json_path}"

    winner_name = min(rows, key=lambda r: r.get(mean_key, 1e9))["name"]

    ncols = len(cols)
    col_spec = "l" + "r" * (ncols - 1)
    lines = [
        r"\begin{table}[htbp]",
        r"  \centering",
        r"  \caption{" + caption + r"}",
        r"  \label{" + label + r"}",
        f"  \\begin{{tabular}}{{{col_spec}}}",
        "    " + " & ".join(cols) + r" \\",
        "    " + r"\hline",
    ]
    for row in rows:
        vals = []
        for field in fields:
            v = row.get(field, "-")
            if isinstance(v, float):
                vals.append(f"{v:.1f}c" if "lat" in field or field in ("mean", "mean_lat", "std", "min", "max") else str(int(v)))
            elif v is None:
                vals.append("-")
            else:
                vals.append(str(v))
        marker = r" $\star$" if row["name"] == winner_name else ""
        lines.append("    " + " & ".join(vals) + marker + r" \\")
    lines += [
        "    " + r"\hline",
        r"  \end{tabular}",
        r"\end{table}",
    ]

    return "\n".join(lines)
