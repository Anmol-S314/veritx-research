"""veritx_dse.pipeline — High-level pipeline orchestration.

Rationale: docs/decisions/modules/cli.md
"""
from __future__ import annotations

import json
import math
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.errors import TraceError
from ..core.logging import Ctx, log, ok, fail, verbose, banner, print_human
from ..simulation.booksim import (
    BookSimError, TimeoutError, detect_trace_stats, run_topology_eval,
    run_sweep, find_booksim_bin, build_config, run_booksim,
)
from ..model.presets import (
    Topology, SWEEP_TOPOS, DENSE_PRESETS, lookup_topo, make_anynet_topo,
    count_anynet_edges, topo_size, anynet_usability,
)

from veritx_dse.core.paths import REPO, RUNS_DIR
from veritx_dse.model.family_registry import spec_for

def _repo_root() -> Path:
    return REPO

def _runs_dir() -> Path:
    return RUNS_DIR

def _experiments_dir() -> Path:
    return _runs_dir() / "experiments"

@dataclass
class CompareResult:
    """Aggregated comparison of topologies."""
    trace: str
    seeds: list[int]
    results: list[dict]
    summary: list[dict]

    def to_dict(self) -> dict:
        return {
            "trace": self.trace,
            "seeds": self.seeds,
            "results": self.results,
            "summary": self.summary,
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
) -> CompareResult:
    """Run multi-seed comparison across topologies.

Rationale: docs/decisions/modules/cli.md
    """
    repo = _repo_root()
    all_results = []
    total = len(topo_specs) * seeds
    t_start = time.time()
    stats: Any = None

    for i, (display_name, topo) in enumerate(topo_specs):
        if spec_for(topo.backend)["rendered_graph"]:
            if stats is None:
                try:
                    stats = detect_trace_stats(trace_path)
                except TraceError:
                    stats = False
            max_node = getattr(stats, "max_node", None) if stats else None
            usable, reason = anynet_usability(topo, max_node)
            if not usable:
                n_nodes, n_edges = topo_size(topo)
                for seed_i in range(seeds):
                    all_results.append({
                        "name": display_name, "topology": topo.backend,
                        "error": f"unusable anynet: {reason}",
                        "nodes": n_nodes, "edges": n_edges,
                        "seed": seed_base + seed_i,
                    })
                log(ctx, f"  {display_name:<16} → SKIPPED ({reason})")
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
                )
                r["name"] = display_name
                all_results.append(r)
                warn_flag = " [UNSTABLE]" if r.get("unstable") else ""
                status = f"{r.get('honest_latency', r['latency']):.2f}c{warn_flag}"
                log(ctx, f"  {display_name:<16} seed={seed:<3} → {status}")
            except TimeoutError:
                n_nodes, n_edges = topo_size(topo)
                all_results.append({
                    "name": display_name, "topology": topo.backend,
                    "error": "timeout", "nodes": n_nodes, "edges": n_edges,
                    "seed": seed,
                })
                log(ctx, f"  {display_name:<16} seed={seed:<3} → timeout")
            except BookSimError as e:
                n_nodes, n_edges = topo_size(topo)
                all_results.append({
                    "name": display_name, "topology": topo.backend,
                    "error": str(e), "nodes": n_nodes, "edges": n_edges,
                    "seed": seed,
                })
                log(ctx, f"  {display_name:<16} seed={seed:<3} → {e}")

    groups: dict[str, list[dict]] = defaultdict(list)
    for r in all_results:
        groups[r["name"]].append(r)

    agg = []
    for display_name, _ in topo_specs:
        runs = groups[display_name]
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
            errs = [r.get("error", "?") for r in runs if "error" in r]
            agg.append({
                "name": display_name, "nodes": nodes, "edges": edges,
                "error": errs[0] if errs else "no valid runs",
                "n": 0,
            })

    return CompareResult(
        trace=trace_path,
        seeds=list(range(seed_base, seed_base + seeds)),
        results=all_results,
        summary=agg,
    )

def print_compare_table(ctx: Ctx, result: CompareResult):
    """Print comparison table to stdout.

Rationale: docs/decisions/modules/cli.md
    """
    ok_rows = [s for s in result.summary if "mean" in s]
    failed = [s for s in result.summary if "error" in s]

    has_unstable = any(s.get("n_unstable", 0) > 0 for s in ok_rows)
    if has_unstable:
        print(f"\n  {'Topology':<16} {'Nodes':>5} {'Edges':>6} {'Mean':>8} {'Std':>7} {'Min':>8} {'Max':>8} {'Runs':>4} {'Unstable':>8}")
        print(f"  {'─' * 78}")
        for s in ok_rows:
            unstable = s.get("n_unstable", 0)
            warn = f" {unstable}/{s['n']}" if unstable else ""
            print(f"  {s['name']:<16} {s['nodes']:>5} {s['edges']:>6} "
                  f"{s['mean']:>7.2f}c {s['std']:>6.2f}c {s['min']:>7.2f}c "
                  f"{s['max']:>7.2f}c {s['n']:>4}{warn:>8}")
        print(f"\n  \033[33mWARNING: Unstable simulations produce unreliable latency numbers.\033[0m")
        print(f"  \033[33mReduce injection rate, increase sample_period, or use fewer seeds.\033[0m")
    else:
        print(f"\n  {'Topology':<16} {'Nodes':>5} {'Edges':>6} {'Mean':>8} {'Std':>7} {'Min':>8} {'Max':>8} {'Runs':>4}")
        print(f"  {'─' * 68}")
        for s in ok_rows:
            print(f"  {s['name']:<16} {s['nodes']:>5} {s['edges']:>6} "
                  f"{s['mean']:>7.2f}c {s['std']:>6.2f}c {s['min']:>7.2f}c "
                  f"{s['max']:>7.2f}c {s['n']:>4}")

    for s in failed:
        print(f"  {s['name']:<16} {str(s['nodes']):>5} {str(s['edges']):>6}   FAIL — {s['error']}")
    if failed:
        print(f"\n  \033[33m{len(failed)} candidate(s) FAILED and are excluded from "
              f"ranking — the winner is valid only among successful runs.\033[0m")

    if len(ok_rows) >= 2:
        agg_sorted = sorted(ok_rows, key=lambda a: a["mean"])
        best = agg_sorted[0]
        worst = agg_sorted[-1]
        delta = (worst["mean"] - best["mean"]) / worst["mean"] * 100 if worst["mean"] > 0 else 0

        sig = ""
        if best["n"] > 1 and worst["n"] > 1:
            pooled_se = math.sqrt(best["std"] ** 2 / best["n"] + worst["std"] ** 2 / worst["n"])
            if pooled_se > 0:
                t_stat = (worst["mean"] - best["mean"]) / pooled_se
                sig = f" (t={t_stat:.1f})" + (" **" if abs(t_stat) > 2 else " *" if abs(t_stat) > 1.5 else " n.s.")

        print("\n  \033[33mUNCERTIFIED LEGACY COMPARISON — the claim below is NOT a "
              "qualified product comparison.\033[0m")
        print("  \033[33mIt carries no comparability verdict (no controlled-dimension "
              "gate). Use the product comparison path for a certified claim.\033[0m")
        print(f"\n  Winner: {best['name']} ({best['mean']:.2f}c ± {best['std']:.2f}c)")
        print(f"  vs {worst['name']}: {delta:.1f}% faster{sig}")

    out_path = _runs_dir() / "booksim" / f"compare_{Path(result.trace).stem}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result.to_dict(), indent=2))
    ok(ctx, f"Results: {out_path}")

def print_sweep_table(ctx: Ctx, results: list[dict], sim_type: str):
    """Print sweep results table."""
    if sim_type == "throughput":
        print(f"\n  {'Topology':<16} {'Nodes':>5} {'Edges':>6} {'Throughput':>10} {'Hops':>7} {'Status':<8}")
    else:
        print(f"\n  {'Topology':<16} {'Nodes':>5} {'Edges':>6} {'Latency':>10} {'Hops':>7} {'Status':<8}")
    print(f"  {'─' * 65}")

    for r in results:
        name = r.get("name", "?")
        nodes = r.get("nodes", "?")
        edges = r.get("edges", "?")
        if "latency" in r:
            lat = f"{r.get('honest_latency', r['latency']):.2f}c"
            hops = f"{r.get('hops', '-'):.1f}" if isinstance(r.get("hops"), (int, float)) else "-"
            tput = f"{r.get('throughput', '-'):.4f}" if isinstance(r.get("throughput"), (int, float)) else "-"
            status = "✓"
        else:
            lat = "-"
            hops = "-"
            tput = "-"
            status = r.get("error", "FAIL")[:6]
        print(f"  {name:<16} {nodes:>5} {edges:>6} {lat:>10} {hops:>7} {tput:>8} {status:<8}")

    valid = [r for r in results if "latency" in r]
    if valid:
        key = lambda r: r.get("honest_latency", r["latency"])
        best = min(valid, key=key)
        worst = max(valid, key=key)
        print(f"\n  Best: {best['name']} ({key(best):.2f}c)")
        print(f"  Worst: {worst['name']} ({key(worst):.2f}c)")
        if key(worst) > 0:
            delta = (key(worst) - key(best)) / key(worst) * 100
            print(f"  Spread: {delta:.1f}%")

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
                print(f"  {k:<25} {v}")
            print(f"\n  Files in {target}:")
            for f in sorted(target.iterdir()):
                size = f.stat().st_size if f.is_file() else 0
                print(f"    {f.name:<30} {size:>8,}B")
        else:
            fail(ctx, f"No manifest in {target}")
        return

    runs = sorted(exp_dir.iterdir(), reverse=True)[:last]
    if not runs:
        fail(ctx, "No runs found")
        return

    print(f"\n\033[1m  VeritX Experiment Runs (last {len(runs)})\033[0m\n")
    print(f"  {'ID':<22} {'Timestamp':<20} {'Dur':>8} {'Model':<20} {'Latency':>10} {'Cert':<6}")
    print(f"  {'─' * 82}")

    for run in runs:
        manifest = run / "manifest.json"
        if manifest.exists():
            try:
                m = json.loads(manifest.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            ts = m.get("timestamp", "?")[:19]
            dur = f"{m.get('duration_s', '?')}s"
            raw_model = m.get("model")
            model = (Path(raw_model).name[:20]
                     if isinstance(raw_model, str) and raw_model else "-")
            _ev = m.get("eval")
            lat = _ev.get("latency", "?") if isinstance(_ev, dict) else "?"
            lat_str = f"{lat:.1f}c" if isinstance(lat, (int, float)) else str(lat)
            cert = m.get("cert", "-")
            if isinstance(cert, dict):
                cert = cert.get("error", "?")[:6]
        else:
            ts, dur, model, lat_str, cert = "?", "?", "?", "?", "?"
        print(f"  {run.name:<22} {ts:<20} {dur:>8} {model:<20} {lat_str:>10} {str(cert):<6}")

def _topology_size(topo) -> dict:
    """(nodes, edges) for a topology, INCLUDING when its run failed.

    An error row used to hardcode `nodes: 0`, which is a false statement about
    the design — the size is a property of the topology, not of the run. For
    an anynet topology the true counts come from the link file.
    """
    edges = topo.edges()
    network_file = (topo.params or {}).get("network_file")
    if network_file:
        try:
            from veritx_dse.model.presets import count_anynet_edges
            nodes, file_edges = count_anynet_edges(str(network_file))
            return {"nodes": nodes, "edges": file_edges}
        except Exception:                                   # noqa: BLE001
            pass
    k = (topo.params or {}).get("k")
    n = (topo.params or {}).get("n", 2)
    if isinstance(k, int) and isinstance(n, int) and k > 0 and n > 0:
        return {"nodes": k ** n, "edges": edges}
    return {"nodes": None, "edges": edges}

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
        print(f"\n  \033[1m{name}\033[0m ({ts})")

        if "summary" in data and isinstance(data["summary"], list):
            print(f"  {'Topology':<16} {'Mean':>8} {'Std':>7} {'Min':>8} {'Max':>8} {'Runs':>4}")
            print(f"  {'─' * 52}")
            for s in data["summary"]:
                if not set(("mean", "std", "min", "max", "n")) <= set(s):
                    reason = s.get("error") or s.get("status") or "incomplete"
                    print(f"  {s.get('name', '?'):<16} {'-':>8} {'-':>7} "
                          f"{'-':>8} {'-':>8} {str(reason)[:24]}")
                    continue
                print(f"  {s['name']:<16} {s['mean']:>7.2f}c {s['std']:>6.2f}c "
                      f"{s['min']:>7.2f}c {s['max']:>7.2f}c {s['n']:>4}")
        elif isinstance(data, list) and all(isinstance(r, dict) for r in data):
            print(f"  {'Topology':<16} {'Latency':>10} {'Hops':>7} {'Status':<8}")
            print(f"  {'─' * 45}")
            for r in data:
                n = r.get("name", "?")
                _lat = r.get("honest_latency", r.get("latency"))
                if "latency" in r and isinstance(_lat, (int, float)):
                    print(f"  {n:<16} {_lat:>9.2f}c {r.get('hops', '-'):>7} {'✓':<8}")
                elif "latency" in r:
                    print(f"  {n:<16} {'-':>10} {'-':>7} {'BADLAT':<8}")
                else:
                    print(f"  {n:<16} {'-':>10} {'-':>7} {r.get('error', 'FAIL')[:8]:<8}")
        else:
            print(f"  {json.dumps(data, indent=None)[:200]}")

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

    def _resolve_run(run_arg: str | None, allow_default: bool):
        if run_arg is None:
            return runs[0] if allow_default and runs else None
        p = Path(run_arg)
        if p.exists():
            return p
        cand = exp_dir / run_arg
        return cand if cand.exists() else None

    both_omitted = run_a is None and run_b is None
    a = _resolve_run(run_a, allow_default=both_omitted)
    b = _resolve_run(run_b, allow_default=both_omitted)

    if a is None:
        fail(ctx, ("No experiment runs found" if both_omitted
                   else f"Run not found: {run_a or run_b}"))
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
                print(f"  {key + '.latency':<30} {latA:>10.2f}c  →  {latB:>10.2f}c  ({sign}{delta:.2f}c / {sign}{pct:.1f}%)")
            else:
                print(f"  {key:<30} {str(vA):>10}  →  {str(vB):>10}")
        elif isinstance(vA, dict) and isinstance(vB, dict):
            for k2 in sorted(set(list(vA.keys()) + list(vB.keys()))):
                print(f"  {key + '.' + k2:<30} {str(vA.get(k2, '—')):>10}  →  {str(vB.get(k2, '—')):>10}")
        else:
            if vA != vB:
                print(f"  {key:<30} {str(vA):>10}  →  {str(vB):>10}  \033[33mCHANGED\033[0m")
            else:
                print(f"  {key:<30} {str(vA):>10}  =  {str(vB):>10}")

    files_a = set(f.name for f in a.iterdir()) if a.exists() else set()
    files_b = set(f.name for f in b.iterdir()) if b.exists() else set()
    only_a = files_a - files_b
    only_b = files_b - files_a
    if only_a or only_b:
        print(f"\n  Files only in {a.name}: {', '.join(sorted(only_a)) or 'none'}")
        print(f"  Files only in {b.name}: {', '.join(sorted(only_b)) or 'none'}")

def generate_latex(ctx: Ctx, json_path: str, caption: str, label: str) -> str:
    """Generate a LaTeX table from compare, pareto, or sweep JSON results."""
    try:
        data = json.loads(Path(json_path).read_text())
    except (json.JSONDecodeError, OSError) as e:
        return f"% Error reading {json_path}: {e}"

    if isinstance(data, list):
        rows = [{**r, "latency": r["honest_latency"]} if "honest_latency" in r else r
                for r in data if isinstance(r, dict)]
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
