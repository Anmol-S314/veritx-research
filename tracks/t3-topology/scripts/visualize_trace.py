#!/usr/bin/env python3
"""
visualize_trace.py -- trace.csv + packets_out.csv pairs -> HTML report (+ optional PNGs).

Backward compatible with the old CLI:
    python visualize_trace.py --run "NAME:TRACE_CSV:PACKETS_CSV" [--run ...] --out report.html [--offline] [--png-dir DIR]

New in this version
  * Completion check: trace packets vs retired packets. Runs that did not drain are flagged
    and EXCLUDED from rankings (their makespan/latency are survivor-biased).
  * Makespan (time to finish the whole trace) and throughput (flits/cycle), the metrics that
    actually decide "which topology is best" for a finite trace. Avg latency alone is dominated
    by source queueing in bursty traffic.
  * Ranking table per comparison, latency-over-time overlay, queue-vs-network split.
  * Per-run: offered-load plot (vs the 1 flit/cycle port limit), binned latency over time,
    src->dst latency heatmap, downsampled scatter (the old one made huge files).
  * Sweep mode: scan a trace_sweep output tree and build a workload x topology summary
    (winners, mean rank, slowdown heatmap, CSV).
        python visualize_trace.py --sweep-root runs/trace_sweep [--config tracks/t3-topology/configs/trace_sweep.yaml]

Assumptions: packets_out.csv contains only retired packets; trace/packets column names as in
the previous version of this script.
"""

import argparse
import html
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

MAX_SCATTER = 5000
FINISHED_PCT = 99.9
RANK_METRICS = [("makespan", True), ("p95_latency", True), ("throughput", False)]  # (col, ascending)
BEST = {"avg_latency": "min", "p50_latency": "min", "p95_latency": "min", "p99_latency": "min",
        "max_latency": "min", "avg_queue_delay": "min", "avg_network_latency": "min",
        "makespan": "min", "throughput": "max", "completion_pct": "max"}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

class Run:
    def __init__(self, name, trace_path, packets_path, nodes=None):
        self.name = name
        self.nodes = nodes
        self.trace = pd.read_csv(trace_path) if trace_path else None
        self.packets = pd.read_csv(packets_path)
        self.packets.columns = [c.strip() for c in self.packets.columns]
        if self.trace is not None:
            self.trace.columns = [c.strip() for c in self.trace.columns]
        self.expected = len(self.trace) if self.trace is not None else None
        self._stats = None

    def flits(self):
        p = self.packets
        if "packet_size_flits" in p.columns:
            return p["packet_size_flits"]
        return pd.Series(1, index=p.index)

    def stats(self):
        if self._stats is not None:
            return self._stats
        p = self.packets
        n = len(p)
        if n == 0:
            raise ValueError(f"{self.name}: packets file has no rows")
        t0, t1 = p["request_time"].min(), p["arrival_time"].max()
        span = max(t1 - t0, 1)
        lat = p["total_latency"]
        comp = 100.0 * n / self.expected if self.expected else float("nan")
        self._stats = {
            "run": self.name, "nodes": self.nodes, "packets": n, "completion_pct": comp,
            "makespan": span, "throughput": float(self.flits().sum()) / span,
            "avg_latency": lat.mean(), "p50_latency": lat.median(),
            "p95_latency": lat.quantile(0.95), "p99_latency": lat.quantile(0.99),
            "max_latency": lat.max(), "avg_hops": p["hops"].mean(),
            "avg_queue_delay": p["source_queue_delay"].mean(),
            "avg_network_latency": p["network_latency"].mean(),
            "queue_share_pct": 100.0 * p["source_queue_delay"].sum() / max(lat.sum(), 1),
            "finished": bool(np.isnan(comp) or comp >= FINISHED_PCT),
        }
        return self._stats


def parse_run_arg(s):
    """'NAME:TRACE_CSV:PACKETS_CSV' or 'NAME::PACKETS_CSV' (no trace.csv)."""
    parts = s.split(":")
    if len(parts) != 3:
        raise ValueError(f"--run must be 'NAME:TRACE_CSV:PACKETS_CSV', got: {s}")
    name, trace_path, packets_path = parts
    return Run(name.strip(), trace_path.strip() or None, packets_path.strip())


def assign_expected(runs):
    """Runs without a trace: expected packet count = max retired among runs with the same node count."""
    groups = {}
    for r in runs:
        groups.setdefault(r.nodes, []).append(r)
    for grp in groups.values():
        ref = max(len(r.packets) for r in grp)
        for r in grp:
            if r.expected is None:
                r.expected = ref
            r._stats = None


def run_warnings(runs):
    w = []
    for r in runs:
        s = r.stats()
        if not s["finished"]:
            w.append(f"{r.name}: only {s['packets']:,} of {r.expected:,} packets retired "
                     f"({s['completion_pct']:.1f}%). Not drained (sample_period too short or network "
                     f"saturated); its makespan/latency are survivor-biased and it is excluded from rankings.")
    if len({r.expected for r in runs}) > 1:
        w.append("Runs have different expected packet counts "
                 f"({sorted({r.expected for r in runs})}): not all runs used the same trace, "
                 "so do not rank them against each other.")
    return w


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _binned(run, bins=60):
    p = run.packets
    t0 = p["request_time"].min()
    span = max(p["request_time"].max() - t0, 1)
    win = max(int(np.ceil(span / bins)), 1)
    d = p.assign(w=(p["request_time"] - t0) // win).groupby("w").agg(
        mean=("total_latency", "mean"),
        p95=("total_latency", lambda x: x.quantile(0.95)),
        queue=("source_queue_delay", "mean"))
    d.index = d.index * win + t0
    return d


def _cdf(values, pts=1500):
    s = np.sort(values.to_numpy())
    n = len(s)
    idx = np.unique(np.linspace(0, n - 1, min(n, pts)).astype(int))
    return s[idx], (idx + 1) / n


# ---------------------------------------------------------------------------
# Per-run figures (each returns a plotly figure or None)
# ---------------------------------------------------------------------------

def fig_injection_timeline(run):
    if run.trace is None:
        return None
    fig = px.histogram(run.trace, x="timestamp", nbins=60,
                       title=f"{run.name} -- injection timeline (input trace)")
    fig.update_layout(xaxis_title="cycle", yaxis_title="packets requested", height=350)
    return fig


def fig_offered_load(run):
    """Per window: busiest single source vs mean node, in flits/cycle. Above 1.0 = injection-port oversubscribed."""
    p = run.packets
    t0 = p["request_time"].min()
    span = max(p["request_time"].max() - t0, 1)
    win = max(int(np.ceil(span / 100)), 1)
    df = pd.DataFrame({"w": (p["request_time"] - t0) // win, "src": p["src"], "f": run.flits()})
    nn = int(max(p["src"].max(), p["dst"].max())) + 1
    peak = df.groupby(["w", "src"])["f"].sum().groupby("w").max() / win
    mean = df.groupby("w")["f"].sum() / (win * nn)
    x = peak.index * win + t0
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=peak.values, mode="lines", name="busiest source"))
    fig.add_trace(go.Scatter(x=x, y=mean.reindex(peak.index).values, mode="lines", name="mean per node"))
    fig.add_hline(y=1.0, line_dash="dot", line_color="red", annotation_text="1 flit/cycle port limit")
    fig.update_layout(title=f"{run.name} -- offered load (from retired packets)",
                      xaxis_title="request cycle", yaxis_title="flits/cycle/node", height=350)
    return fig


def fig_traffic_heatmap(run):
    if run.trace is None:
        return None
    pivot = run.trace.groupby(["src", "dst"]).size().reset_index(name="count")
    fig = px.density_heatmap(pivot, x="dst", y="src", z="count", histfunc="sum",
                             nbinsx=pivot["dst"].nunique() or 1, nbinsy=pivot["src"].nunique() or 1,
                             title=f"{run.name} -- src/dst traffic matrix (input trace)",
                             color_continuous_scale="Blues")
    fig.update_layout(height=400)
    return fig


def fig_latency_heatmap(run):
    p = run.packets
    if max(p["src"].max(), p["dst"].max()) >= 128:
        return None
    m = p.groupby(["src", "dst"])["total_latency"].mean().unstack()
    fig = go.Figure(go.Heatmap(z=m.values, x=m.columns, y=m.index, colorscale="YlOrRd",
                               colorbar=dict(title="cycles")))
    fig.update_layout(title=f"{run.name} -- mean latency by src/dst (where it hurts)",
                      xaxis_title="dst", yaxis_title="src", height=400)
    return fig


def fig_packet_size_dist(run):
    if run.trace is None:
        return None
    fig = px.histogram(run.trace, x="packet_size", title=f"{run.name} -- requested packet size (trace units)")
    fig.update_layout(height=300)
    return fig


def fig_latency_dist(run):
    p = run.packets
    fig = px.histogram(p, x="total_latency", nbins=40, title=f"{run.name} -- total latency distribution (output)")
    fig.add_vline(x=p["total_latency"].mean(), line_dash="dash", annotation_text="mean", line_color="red")
    fig.add_vline(x=p["total_latency"].quantile(0.95), line_dash="dot", annotation_text="p95", line_color="orange")
    fig.update_layout(xaxis_title="cycles", yaxis_title="packets", height=350)
    return fig


def fig_latency_breakdown(run):
    p = run.packets
    fig = go.Figure()
    fig.add_trace(go.Box(y=p["source_queue_delay"], name="source queue delay"))
    fig.add_trace(go.Box(y=p["network_latency"], name="network latency"))
    fig.update_layout(title=f"{run.name} -- where the latency comes from", yaxis_title="cycles", height=350)
    return fig


def fig_hops_dist(run):
    counts = run.packets["hops"].value_counts().sort_index()
    fig = px.bar(x=counts.index, y=counts.values, title=f"{run.name} -- hop count distribution")
    fig.update_layout(xaxis_title="hops", yaxis_title="packets", height=300)
    return fig


def fig_latency_binned(run):
    d = _binned(run)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d.index, y=d["mean"], mode="lines", name="mean latency"))
    fig.add_trace(go.Scatter(x=d.index, y=d["p95"], mode="lines", name="p95 latency"))
    fig.add_trace(go.Scatter(x=d.index, y=d["queue"], mode="lines", name="mean source queue delay"))
    fig.update_layout(title=f"{run.name} -- latency vs request time (congestion buildup)",
                      xaxis_title="request cycle", yaxis_title="cycles", height=350)
    return fig


def fig_latency_scatter(run):
    p = run.packets
    if len(p) > MAX_SCATTER:
        p = p.sample(MAX_SCATTER, random_state=0)
    fig = px.scatter(p, x="request_time", y="total_latency", opacity=0.5,
                     title=f"{run.name} -- per-packet latency (sample of {len(p):,})")
    fig.update_layout(xaxis_title="request cycle", yaxis_title="total latency (cycles)", height=350)
    return fig


def fig_per_node_load(run):
    counts = run.packets["dst"].value_counts().sort_index()
    fig = px.bar(x=counts.index, y=counts.values, title=f"{run.name} -- accepted packets per destination node")
    fig.update_layout(xaxis_title="node", yaxis_title="packets accepted", height=300)
    return fig


PER_RUN_FIGURES = [fig_injection_timeline, fig_offered_load, fig_traffic_heatmap, fig_latency_heatmap,
                   fig_packet_size_dist, fig_latency_dist, fig_latency_breakdown, fig_hops_dist,
                   fig_latency_binned, fig_latency_scatter, fig_per_node_load]


# ---------------------------------------------------------------------------
# Comparison figures
# ---------------------------------------------------------------------------

def fig_comparison_cdf(runs):
    fig = go.Figure()
    for r in runs:
        x, y = _cdf(r.packets["total_latency"])
        fig.add_trace(go.Scatter(x=x, y=y, mode="lines", name=r.name))
    fig.update_layout(title="Latency CDF -- all runs", xaxis_title="total latency (cycles)",
                      yaxis_title="fraction of packets", height=400)
    return fig


def fig_comparison_time(runs):
    fig = go.Figure()
    for r in runs:
        d = _binned(r)
        fig.add_trace(go.Scatter(x=d.index - d.index.min(), y=d["mean"], mode="lines", name=r.name))
    fig.update_layout(title="Mean latency over time -- all runs", xaxis_title="cycles since first request",
                      yaxis_title="mean latency (cycles)", height=400)
    return fig


def fig_comparison_bar(df, field, title, ytitle):
    fig = px.bar(df, x="run", y=field, title=title, color="finished",
                 color_discrete_map={True: "#4a7ab5", False: "#c0504d"})
    fig.update_layout(yaxis_title=ytitle, height=350, showlegend=False)
    return fig


def fig_comparison_split(df):
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df["run"], y=df["avg_queue_delay"], name="source queue"))
    fig.add_trace(go.Bar(x=df["run"], y=df["avg_network_latency"], name="network"))
    fig.update_layout(barmode="stack", title="Average latency split: source queue vs network (cycles)", height=350)
    return fig


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

COLS = ["run", "packets", "completion_pct", "makespan", "throughput", "avg_latency", "p50_latency",
        "p95_latency", "p99_latency", "max_latency", "avg_hops", "avg_queue_delay",
        "avg_network_latency", "queue_share_pct"]
LABELS = ["Run", "Packets", "Completed %", "Makespan (cyc)", "Throughput (flit/cyc)", "Avg lat", "P50", "P95",
          "P99", "Max", "Avg hops", "Avg queue", "Avg net", "Queue share %"]


def _fmt(c, v):
    if c == "run":
        return html.escape(str(v))
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "-"
    if c in ("packets", "makespan"):
        return f"{int(v):,}"
    return f"{v:.2f}"


def stats_table_html(all_stats):
    best = {}
    if len(all_stats) > 1:
        ok = [s for s in all_stats if s["finished"]]
        for c, how in BEST.items():
            vals = [s[c] for s in ok if not pd.isna(s[c])]
            if vals:
                best[c] = min(vals) if how == "min" else max(vals)
    rows = []
    for s in all_stats:
        cells = []
        for c in COLS:
            hl = s["finished"] and c in best and s[c] == best[c]
            style = ' style="background:#dff0d8"' if hl else (' style="color:#c0504d"' if c == "completion_pct" and not s["finished"] else "")
            cells.append(f"<td{style}>{_fmt(c, s[c])}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    head = "".join(f"<th>{l}</th>" for l in LABELS)
    return (f'<table class="stats"><tr>{head}</tr>{"".join(rows)}</table>'
            '<div class="note">Green = best among drained runs. Makespan = last arrival - first request.</div>')


def add_ranks(df):
    """df needs: workload, nodes, finished + metric columns. Ranks within (workload, nodes), drained runs only,
    groups with fewer than 2 drained runs are not ranked."""
    df = df.copy()
    df["nodes"] = pd.to_numeric(df["nodes"]).fillna(-1)
    ok = df[df["finished"]]
    gsize = ok.groupby(["workload", "nodes"])["makespan"].transform("size")
    rank_cols = []
    for c, asc in RANK_METRICS:
        col = "rank_" + c
        df[col] = np.nan
        df.loc[ok.index, col] = ok.groupby(["workload", "nodes"])[c].rank(ascending=asc, method="min")
        df.loc[gsize.index[gsize < 2], col] = np.nan
        rank_cols.append(col)
    df["mean_rank"] = df[rank_cols].mean(axis=1, skipna=False)
    best = ok.groupby(["workload", "nodes"])["makespan"].min().rename("best_makespan")
    df = df.join(best, on=["workload", "nodes"])
    df["slowdown"] = np.where(df["finished"], df["makespan"] / df["best_makespan"], np.nan)
    return df


def ranking_html(all_stats):
    df = pd.DataFrame(all_stats)
    df["workload"] = "w"
    df = add_ranks(df)
    ok = df[df["finished"] & df["mean_rank"].notna()].sort_values("mean_rank")
    if ok.empty:
        return ""
    rows = "".join(
        f"<tr><td>{html.escape(str(r['run']))}</td><td>{int(r['rank_makespan'])}</td>"
        f"<td>{int(r['rank_p95_latency'])}</td><td>{int(r['rank_throughput'])}</td>"
        f"<td>{r['mean_rank']:.2f}</td><td>{r['slowdown']:.2f}x</td></tr>" for _, r in ok.iterrows())
    return ('<h3>Ranking (drained runs)</h3><table class="stats"><tr><th>Run</th><th>Makespan rank</th>'
            '<th>P95 rank</th><th>Throughput rank</th><th>Mean rank</th><th>Makespan vs best</th></tr>'
            f'{rows}</table>')


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

TAB_CSS = """
body { font-family: -apple-system, Helvetica, Arial, sans-serif; margin: 0; background: #fafafa; }
h1 { padding: 20px 24px 0 24px; margin: 0; }
.subtitle { padding: 0 24px 16px 24px; color: #666; }
.tabbar { display: flex; border-bottom: 2px solid #ddd; background: white; position: sticky; top: 0; z-index: 10; overflow-x: auto; }
.tabbtn { padding: 12px 20px; cursor: pointer; border: none; background: none; font-size: 14px; white-space: nowrap; color: #555; }
.tabbtn:hover { background: #f0f0f0; }
.tabbtn.active { color: #1a1a1a; font-weight: 600; border-bottom: 3px solid #4a7ab5; }
.tabpanel { display: none; padding: 20px 24px; }
.tabpanel.active { display: block; }
.chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.chart-grid > div { background: white; border-radius: 8px; padding: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
table.stats { border-collapse: collapse; margin: 16px 0; background: white; }
table.stats th, table.stats td { border: 1px solid #ddd; padding: 6px 12px; text-align: right; }
table.stats th { background: #f0f4f9; text-align: center; }
table.stats td:first-child, table.stats th:first-child { text-align: left; }
.warn { background: #fdecea; border-left: 4px solid #c0504d; padding: 8px 12px; margin: 8px 0; }
.note { color: #666; font-size: 12px; }
@media (max-width: 900px) { .chart-grid { grid-template-columns: 1fr; } }
"""

TAB_JS = """
function showTab(id) {
  document.querySelectorAll('.tabpanel').forEach(function(p) { p.classList.remove('active'); });
  document.querySelectorAll('.tabbtn').forEach(function(b) { b.classList.remove('active'); });
  document.getElementById('panel-' + id).classList.add('active');
  document.getElementById('btn-' + id).classList.add('active');
  window.dispatchEvent(new Event('resize'));
}
"""


def assemble_html(title, subtitle, tabs, offline, out_path):
    plotlyjs_tag = (f"<script>{get_plotlyjs()}</script>" if offline
                    else '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>')
    buttons, panels = [], []
    for i, (label, body) in enumerate(tabs):
        tid, act = f"t{i}", (" active" if i == 0 else "")
        buttons.append(f'<button class="tabbtn{act}" id="btn-{tid}" onclick="showTab(\'{tid}\')">{html.escape(label)}</button>')
        panels.append(f'<div class="tabpanel{act}" id="panel-{tid}">{body}</div>')
    doc = (f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>{plotlyjs_tag}'
           f'<style>{TAB_CSS}</style></head><body><h1>{html.escape(title)}</h1>'
           f'<div class="subtitle">{html.escape(subtitle)}</div><div class="tabbar">{"".join(buttons)}</div>'
           f'{"".join(panels)}<script>{TAB_JS}</script></body></html>')
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(doc)
    print(f"wrote {out_path} ({len(doc) / 1024:.0f} KB)")


def _charts(figs, prefix):
    out = []
    for j, (name, fig) in enumerate(figs):
        if fig is not None:
            out.append(f'<div>{fig.to_html(full_html=False, include_plotlyjs=False, div_id=f"{prefix}-{name}-{j}")}</div>')
    return f'<div class="chart-grid">{"".join(out)}</div>'


def comparison_body(runs, prefix):
    stats = [r.stats() for r in runs]
    df = pd.DataFrame(stats)
    warns = "".join(f'<div class="warn">{html.escape(w)}</div>' for w in run_warnings(runs))
    figs = []
    for name, fn in [("cdf", lambda: fig_comparison_cdf(runs)), ("time", lambda: fig_comparison_time(runs)),
                     ("makespan", lambda: fig_comparison_bar(df, "makespan", "Makespan (cycles to finish the trace)", "cycles")),
                     ("thr", lambda: fig_comparison_bar(df, "throughput", "Throughput (flits/cycle)", "flits/cycle")),
                     ("avg", lambda: fig_comparison_bar(df, "avg_latency", "Average total latency", "cycles")),
                     ("p95", lambda: fig_comparison_bar(df, "p95_latency", "P95 total latency", "cycles")),
                     ("split", lambda: fig_comparison_split(df)),
                     ("hops", lambda: fig_comparison_bar(df, "avg_hops", "Average hop count", "hops"))]:
        figs.append((name, fn()))
    return (f"<h2>Comparison</h2>{warns}{stats_table_html(stats)}{ranking_html(stats)}"
            f"{_charts(figs, prefix)}")


def run_body(run, prefix):
    figs = []
    for fn in PER_RUN_FIGURES:
        try:
            figs.append((fn.__name__, fn(run)))
        except Exception as e:  # one bad chart must not kill the report
            print(f"[warn] {run.name}: {fn.__name__} failed: {e}")
    s = run.stats()
    warns = "".join(f'<div class="warn">{html.escape(w)}</div>' for w in run_warnings([run]) if "retired" in w)
    return f"<h2>{html.escape(run.name)}</h2>{warns}{stats_table_html([s])}{_charts(figs, prefix)}"


# ---------------------------------------------------------------------------
# Standard report (--run)
# ---------------------------------------------------------------------------

def build_report(runs, out_path, offline):
    assign_expected(runs)
    tabs = [("Comparison", comparison_body(runs, "cmp"))]
    for i, r in enumerate(runs):
        tabs.append((r.name, run_body(r, f"run{i}")))
    assemble_html("Trace comparison report", f"{len(runs)} run(s) -- generated by visualize_trace.py",
                  tabs, offline, out_path)


# ---------------------------------------------------------------------------
# Sweep summary (--sweep-root)
# ---------------------------------------------------------------------------

def build_sweep_report(root, config_path, out_path, csv_path, offline):
    root = Path(root)
    topo_meta = {}
    if config_path:
        import yaml
        topo_meta = (yaml.safe_load(open(config_path)) or {}).get("topologies", {}) or {}

    by_wl = {}
    for pk in sorted(root.glob("sim/*/*/packets_out.csv")):
        w, t = pk.parts[-3], pk.parts[-2]
        meta = topo_meta.get(t, {})
        nodes = meta.get("nodes")
        tr = root / "traces" / f"{w}_n{nodes}.csv" if nodes else None
        try:
            run = Run(meta.get("label", t), tr if tr is not None and tr.exists() else None, pk, nodes)
            run.stats()
        except Exception as e:
            print(f"[skip] {pk}: {e}")
            continue
        by_wl.setdefault(w, []).append(run)
    if not by_wl:
        raise SystemExit(f"no sim/*/*/packets_out.csv under {root}")

    rows = []
    for w, runs in by_wl.items():
        assign_expected(runs)
        for r in runs:
            rows.append({"workload": w, **r.stats()})
    df = add_ranks(pd.DataFrame(rows))
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    df.drop(columns=["finished"]).to_csv(csv_path, index=False)
    print(f"wrote {csv_path}")

    # winners
    win_rows = []
    for (w, n), g in df.groupby(["workload", "nodes"]):
        ok = g[g["finished"]]
        dnf = ", ".join(g[~g["finished"]]["run"]) or "-"
        if ok.empty:
            win_rows.append(f"<tr><td>{w}</td><td>{int(n) if n > 0 else '?'}</td><td>{len(g)}</td><td colspan=3>none drained</td><td>{html.escape(dnf)}</td></tr>")
            continue
        a = ok.loc[ok["makespan"].idxmin(), "run"]
        b = ok.loc[ok["p95_latency"].idxmin(), "run"]
        c = ok.loc[ok["throughput"].idxmax(), "run"]
        solo = " (only run)" if len(ok) < 2 else ""
        win_rows.append(f"<tr><td>{w}</td><td>{int(n) if n > 0 else '?'}</td><td>{len(g)}</td><td>{html.escape(a)}{solo}</td>"
                        f"<td>{html.escape(b)}</td><td>{html.escape(c)}</td><td>{html.escape(dnf)}</td></tr>")
    winners = ('<h3>Winner per workload</h3><table class="stats"><tr><th>Workload</th><th>Nodes</th><th>Runs</th>'
               '<th>Best makespan</th><th>Best P95</th><th>Best throughput</th><th>Did not drain</th></tr>'
               f'{"".join(win_rows)}</table>')

    # topology mean rank
    rk = df[df["mean_rank"].notna()]
    top = ""
    if not rk.empty:
        agg = rk.groupby("run").agg(workloads=("workload", "nunique"), wins=("rank_makespan", lambda s: int((s == 1).sum())),
                                    rank_makespan=("rank_makespan", "mean"), rank_p95=("rank_p95_latency", "mean"),
                                    rank_thr=("rank_throughput", "mean"), mean_rank=("mean_rank", "mean")).sort_values("mean_rank")
        trs = "".join(f"<tr><td>{html.escape(str(i))}</td><td>{int(r.workloads)}</td><td>{r.wins}</td><td>{r.rank_makespan:.2f}</td>"
                      f"<td>{r.rank_p95:.2f}</td><td>{r.rank_thr:.2f}</td><td>{r.mean_rank:.2f}</td></tr>" for i, r in agg.iterrows())
        top = ('<h3>Topology ranking across workloads (lower rank = better)</h3><table class="stats"><tr><th>Topology</th>'
               '<th>Workloads ranked</th><th>Makespan wins</th><th>Avg makespan rank</th><th>Avg P95 rank</th>'
               f'<th>Avg throughput rank</th><th>Mean rank</th></tr>{trs}</table>'
               '<div class="note">Ranked only within the same workload and node count, drained runs only. '
               'Averages mix workloads of very different character; read the per-workload rows too.</div>')

    # heatmaps
    df["row"] = df.apply(lambda r: r["workload"] + (f" ({int(r['nodes'])}n)" if r["nodes"] > 0 else ""), axis=1)
    figs = []
    for col, title in [("slowdown", "Makespan slowdown vs best topology (1.0 = best, blank = did not drain)"),
                       ("p95_latency", "P95 latency (cycles)")]:
        piv = df.pivot_table(index="row", columns="run", values=col, aggfunc="first")
        fig = go.Figure(go.Heatmap(z=piv.values, x=piv.columns, y=piv.index, colorscale="RdYlGn_r",
                                   text=np.round(piv.values, 2), texttemplate="%{text}", hoverongaps=False))
        fig.update_layout(title=title, height=max(300, 40 * len(piv) + 150))
        figs.append((col, fig))
    overview = f"<h2>Sweep overview</h2>{winners}{top}{_charts(figs, 'sw')}"

    tabs = [("Overview", overview)]
    for i, (w, runs) in enumerate(by_wl.items()):
        tabs.append((w, comparison_body(runs, f"w{i}")))
    assemble_html("Trace sweep summary", f"{len(by_wl)} workload(s), {len(rows)} run(s) from {root}", tabs, offline, out_path)


# ---------------------------------------------------------------------------
# PNGs
# ---------------------------------------------------------------------------

def write_pngs(runs, png_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    png_dir = Path(png_dir)
    png_dir.mkdir(parents=True, exist_ok=True)
    for run in runs:
        safe = "".join(c if c.isalnum() else "_" for c in run.name)
        p = run.packets
        fig, axes = plt.subplots(2, 2, figsize=(11, 8))
        fig.suptitle(run.name)
        axes[0][0].hist(p["total_latency"], bins=40)
        axes[0][0].axvline(p["total_latency"].mean(), color="red", linestyle="--", label="mean")
        axes[0][0].set_title("Total latency distribution")
        axes[0][0].set_xlabel("cycles")
        axes[0][0].legend()
        axes[0][1].boxplot([p["source_queue_delay"], p["network_latency"]])
        axes[0][1].set_xticks([1, 2])
        axes[0][1].set_xticklabels(["queue delay", "network latency"])
        axes[0][1].set_title("Latency breakdown")
        hc = p["hops"].value_counts().sort_index()
        axes[1][0].bar(hc.index, hc.values)
        axes[1][0].set_title("Hop count distribution")
        axes[1][0].set_xlabel("hops")
        d = _binned(run)
        axes[1][1].plot(d.index, d["mean"], label="mean")
        axes[1][1].plot(d.index, d["p95"], label="p95")
        axes[1][1].set_title("Latency vs request time")
        axes[1][1].set_xlabel("request cycle")
        axes[1][1].legend()
        fig.tight_layout()
        f = png_dir / f"{safe}_summary.png"
        fig.savefig(f, dpi=130)
        plt.close(fig)
        print(f"wrote {f}")
    if len(runs) > 1:
        fig, ax = plt.subplots(figsize=(8, 5))
        for run in runs:
            x, y = _cdf(run.packets["total_latency"])
            ax.plot(x, y, label=run.name)
        ax.set_title("Latency CDF -- all runs")
        ax.set_xlabel("total latency (cycles)")
        ax.set_ylabel("fraction of packets")
        ax.legend()
        fig.tight_layout()
        f = png_dir / "comparison_cdf.png"
        fig.savefig(f, dpi=130)
        plt.close(fig)
        print(f"wrote {f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", help="'NAME:TRACE_CSV:PACKETS_CSV' (TRACE_CSV may be empty)")
    ap.add_argument("--out", default="report.html", help="output HTML report path (for --run)")
    ap.add_argument("--png-dir", default=None)
    ap.add_argument("--offline", action="store_true", help="embed plotly.js inline")
    ap.add_argument("--sweep-root", help="trace_sweep output root (contains sim/<workload>/<topo>/packets_out.csv)")
    ap.add_argument("--config", help="trace_sweep.yaml, for topology labels and node counts (sweep mode)")
    ap.add_argument("--sweep-out", help="sweep summary html (default <root>/reports/summary.html)")
    args = ap.parse_args()
    if not args.run and not args.sweep_root:
        ap.error("give at least one --run or --sweep-root")

    if args.run:
        runs = [parse_run_arg(r) for r in args.run]
        build_report(runs, args.out, args.offline)
        if args.png_dir:
            write_pngs(runs, args.png_dir)
    if args.sweep_root:
        out = args.sweep_out or str(Path(args.sweep_root) / "reports" / "summary.html")
        build_sweep_report(args.sweep_root, args.config, out, str(Path(out).with_suffix(".csv")), args.offline)


if __name__ == "__main__":
    main()