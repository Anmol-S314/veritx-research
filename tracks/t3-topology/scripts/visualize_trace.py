"""
visualize_trace.py -- turns trace.csv (input) + trace_packet_log.csv (output)
pairs from one or more runs into:
  1. a set of PNG charts per run (plain matplotlib, for pasting into docs/slides)
  2. one self-contained HTML report with a tab per run plus a Comparison tab
     (interactive Plotly charts, no server needed -- just open the file)

Works with however many runs you give it -- different topologies, different
traffic sources, different sweep points, whatever "run" means for your
comparison. Each run needs a packets_out.csv (trace_packet_log output); the
input trace.csv is optional per run (skip it if you only have output data).

Usage:
    python visualize_trace.py \
        --run "4x4 Mesh:mesh_trace.csv:mesh_packets_out.csv" \
        --run "GEC MECS:gec_trace.csv:gec_packets_out.csv" \
        --run "Torus (output only)::torus_packets_out.csv" \
        --out report.html \
        --png-dir charts/

    # fully offline (no CDN dependency, larger file):
    python visualize_trace.py --run "..." --out report.html --offline

Input CSV schemas expected (matches TraceTrafficManager / gen_trace.py /
chakra_to_trace.py from earlier in this project):
    trace.csv:       timestamp,src,dst,type,packet_size,transaction_id
    packets_out.csv: packet_id,transaction_id,src,dst,type,packet_size_flits,
                      request_time,injection_time,arrival_time,
                      source_queue_delay,network_latency,total_latency,hops
"""

import argparse
import html
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.offline import get_plotlyjs


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

class Run:
    def __init__(self, name, trace_path, packets_path):
        self.name = name
        self.trace = pd.read_csv(trace_path) if trace_path else None
        self.packets = pd.read_csv(packets_path)
        # normalize whitespace-y column names some CSV writers leave behind
        self.packets.columns = [c.strip() for c in self.packets.columns]
        if self.trace is not None:
            self.trace.columns = [c.strip() for c in self.trace.columns]

    def stats(self):
        p = self.packets
        return {
            "run": self.name,
            "packets": len(p),
            "avg_latency": p["total_latency"].mean(),
            "p50_latency": p["total_latency"].median(),
            "p95_latency": p["total_latency"].quantile(0.95),
            "max_latency": p["total_latency"].max(),
            "avg_hops": p["hops"].mean(),
            "avg_queue_delay": p["source_queue_delay"].mean(),
            "avg_network_latency": p["network_latency"].mean(),
        }


def parse_run_arg(s):
    """'NAME:TRACE_CSV:PACKETS_CSV' or 'NAME::PACKETS_CSV' (no trace.csv)."""
    parts = s.split(":")
    if len(parts) != 3:
        raise ValueError(f"--run must be 'NAME:TRACE_CSV:PACKETS_CSV', got: {s}")
    name, trace_path, packets_path = parts
    return Run(name.strip(), trace_path.strip() or None, packets_path.strip())


# ---------------------------------------------------------------------------
# Per-run figures
# ---------------------------------------------------------------------------

def fig_injection_timeline(run):
    if run.trace is None:
        return None
    fig = px.histogram(run.trace, x="timestamp", nbins=40,
                        title=f"{run.name} -- injection timeline (input trace)")
    fig.update_layout(xaxis_title="cycle", yaxis_title="packets requested", height=350)
    return fig


def fig_traffic_heatmap(run):
    if run.trace is None:
        return None
    pivot = run.trace.groupby(["src", "dst"]).size().reset_index(name="count")
    fig = px.density_heatmap(pivot, x="dst", y="src", z="count",
                              histfunc="sum", nbinsx=pivot["dst"].nunique() or 1,
                              nbinsy=pivot["src"].nunique() or 1,
                              title=f"{run.name} -- src/dst traffic matrix (input trace)",
                              color_continuous_scale="Blues")
    fig.update_layout(height=400)
    return fig


def fig_packet_size_dist(run):
    if run.trace is None:
        return None
    fig = px.histogram(run.trace, x="packet_size",
                        title=f"{run.name} -- requested packet size (flits)")
    fig.update_layout(height=300)
    return fig


def fig_latency_dist(run):
    p = run.packets
    fig = px.histogram(p, x="total_latency", nbins=40,
                        title=f"{run.name} -- total latency distribution (output)")
    fig.add_vline(x=p["total_latency"].mean(), line_dash="dash",
                  annotation_text="mean", line_color="red")
    fig.add_vline(x=p["total_latency"].quantile(0.95), line_dash="dot",
                  annotation_text="p95", line_color="orange")
    fig.update_layout(xaxis_title="cycles", yaxis_title="packets", height=350)
    return fig


def fig_latency_breakdown(run):
    p = run.packets
    fig = go.Figure()
    fig.add_trace(go.Box(y=p["source_queue_delay"], name="source queue delay"))
    fig.add_trace(go.Box(y=p["network_latency"], name="network latency"))
    fig.update_layout(title=f"{run.name} -- where the latency comes from",
                       yaxis_title="cycles", height=350)
    return fig


def fig_hops_dist(run):
    p = run.packets
    counts = p["hops"].value_counts().sort_index()
    fig = px.bar(x=counts.index, y=counts.values,
                 title=f"{run.name} -- hop count distribution")
    fig.update_layout(xaxis_title="hops", yaxis_title="packets", height=300)
    return fig


def fig_latency_over_time(run):
    p = run.packets
    fig = px.scatter(p, x="request_time", y="total_latency",
                      title=f"{run.name} -- latency over the run (congestion buildup)",
                      opacity=0.6)
    fig.update_layout(xaxis_title="request cycle", yaxis_title="total latency (cycles)", height=350)
    return fig


def fig_per_node_load(run):
    p = run.packets
    counts = p["dst"].value_counts().sort_index()
    fig = px.bar(x=counts.index, y=counts.values,
                 title=f"{run.name} -- accepted packets per destination node")
    fig.update_layout(xaxis_title="node", yaxis_title="packets accepted", height=300)
    return fig


PER_RUN_FIGURES = [
    fig_injection_timeline,
    fig_traffic_heatmap,
    fig_packet_size_dist,
    fig_latency_dist,
    fig_latency_breakdown,
    fig_hops_dist,
    fig_latency_over_time,
    fig_per_node_load,
]


# ---------------------------------------------------------------------------
# Comparison figures (across runs)
# ---------------------------------------------------------------------------

def fig_comparison_cdf(runs):
    fig = go.Figure()
    for run in runs:
        s = run.packets["total_latency"].sort_values()
        y = [i / len(s) for i in range(1, len(s) + 1)]
        fig.add_trace(go.Scatter(x=s.values, y=y, mode="lines", name=run.name))
    fig.update_layout(title="Latency CDF -- all runs",
                       xaxis_title="total latency (cycles)", yaxis_title="fraction of packets",
                       height=400)
    return fig


def fig_comparison_bar(all_stats, field, title, ytitle):
    fig = px.bar(all_stats, x="run", y=field, title=title)
    fig.update_layout(yaxis_title=ytitle, height=350)
    return fig


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------

TAB_CSS = """
body { font-family: -apple-system, Helvetica, Arial, sans-serif; margin: 0; background: #fafafa; }
h1 { padding: 20px 24px 0 24px; margin: 0; }
.subtitle { padding: 0 24px 16px 24px; color: #666; }
.tabbar { display: flex; border-bottom: 2px solid #ddd; background: white;
          position: sticky; top: 0; z-index: 10; overflow-x: auto; }
.tabbtn { padding: 12px 20px; cursor: pointer; border: none; background: none;
          font-size: 14px; white-space: nowrap; color: #555; }
.tabbtn:hover { background: #f0f0f0; }
.tabbtn.active { color: #1a1a1a; font-weight: 600; border-bottom: 3px solid #4a7ab5; }
.tabpanel { display: none; padding: 20px 24px; }
.tabpanel.active { display: block; }
.chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.chart-grid > div { background: white; border-radius: 8px; padding: 8px;
                     box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
table.stats { border-collapse: collapse; margin: 16px 0; background: white; }
table.stats th, table.stats td { border: 1px solid #ddd; padding: 8px 14px; text-align: right; }
table.stats th { background: #f0f4f9; text-align: center; }
table.stats td:first-child, table.stats th:first-child { text-align: left; }
@media (max-width: 900px) { .chart-grid { grid-template-columns: 1fr; } }
"""

TAB_JS = """
function showTab(id) {
  document.querySelectorAll('.tabpanel').forEach(function(p) { p.classList.remove('active'); });
  document.querySelectorAll('.tabbtn').forEach(function(b) { b.classList.remove('active'); });
  document.getElementById('panel-' + id).classList.add('active');
  document.getElementById('btn-' + id).classList.add('active');
  window.dispatchEvent(new Event('resize'));  // makes Plotly redraw hidden charts correctly
}
"""


def stats_table_html(all_stats):
    cols = ["run", "packets", "avg_latency", "p50_latency", "p95_latency",
            "max_latency", "avg_hops", "avg_queue_delay", "avg_network_latency"]
    labels = ["Run", "Packets", "Avg latency", "P50 latency", "P95 latency",
              "Max latency", "Avg hops", "Avg queue delay", "Avg net latency"]
    rows = []
    for s in all_stats:
        cells = "".join(
            f"<td>{html.escape(str(s[c]))}</td>" if c == "run"
            else f"<td>{s[c]:.2f}</td>" for c in cols
        )
        rows.append(f"<tr>{cells}</tr>")
    header = "".join(f"<th>{l}</th>" for l in labels)
    return f'<table class="stats"><tr>{header}</tr>{"".join(rows)}</table>'


def build_report(runs, out_path, offline):
    plotlyjs_tag = (
        f"<script>{get_plotlyjs()}</script>" if offline
        else '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>'
    )

    tab_buttons = []
    tab_panels = []

    # per-run tabs
    for i, run in enumerate(runs):
        tab_id = f"run{i}"
        tab_buttons.append(
            f'<button class="tabbtn" id="btn-{tab_id}" '
            f'onclick="showTab(\'{tab_id}\')">{html.escape(run.name)}</button>'
        )
        charts_html = []
        for fig_fn in PER_RUN_FIGURES:
            fig = fig_fn(run)
            if fig is None:
                continue
            div_id = f"{tab_id}-{fig_fn.__name__}"
            charts_html.append(
                f'<div>{fig.to_html(full_html=False, include_plotlyjs=False, div_id=div_id)}</div>'
            )
        tab_panels.append(
            f'<div class="tabpanel" id="panel-{tab_id}">'
            f'<h2>{html.escape(run.name)}</h2>'
            f'{stats_table_html([run.stats()])}'
            f'<div class="chart-grid">{"".join(charts_html)}</div>'
            f'</div>'
        )

    # comparison tab
    all_stats = [r.stats() for r in runs]
    comp_charts = [
        fig_comparison_cdf(runs),
        fig_comparison_bar(pd.DataFrame(all_stats), "avg_latency",
                            "Average total latency by run", "cycles"),
        fig_comparison_bar(pd.DataFrame(all_stats), "p95_latency",
                            "P95 total latency by run", "cycles"),
        fig_comparison_bar(pd.DataFrame(all_stats), "avg_hops",
                            "Average hop count by run", "hops"),
    ]
    comp_html = "".join(
        f'<div>{fig.to_html(full_html=False, include_plotlyjs=False, div_id=f"cmp-{j}")}</div>'
        for j, fig in enumerate(comp_charts)
    )
    tab_buttons.insert(0,
        f'<button class="tabbtn active" id="btn-compare" onclick="showTab(\'compare\')">'
        f'Comparison</button>')
    tab_panels.insert(0,
        f'<div class="tabpanel active" id="panel-compare">'
        f'<h2>Comparison across all runs</h2>'
        f'{stats_table_html(all_stats)}'
        f'<div class="chart-grid">{comp_html}</div>'
        f'</div>')

    html_doc = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Trace comparison report</title>
{plotlyjs_tag}
<style>{TAB_CSS}</style>
</head>
<body>
<h1>Trace comparison report</h1>
<div class="subtitle">{len(runs)} run(s) -- generated by visualize_trace.py</div>
<div class="tabbar">{"".join(tab_buttons)}</div>
{"".join(tab_panels)}
<script>{TAB_JS}</script>
</body>
</html>"""

    Path(out_path).write_text(html_doc)
    print(f"wrote {out_path} ({len(html_doc) / 1024:.0f} KB)")


# ---------------------------------------------------------------------------
# Plain-matplotlib PNGs (for docs/slides, no interactivity needed)
# ---------------------------------------------------------------------------

def write_pngs(runs, png_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    png_dir = Path(png_dir)
    png_dir.mkdir(parents=True, exist_ok=True)

    for run in runs:
        safe_name = "".join(c if c.isalnum() else "_" for c in run.name)
        p = run.packets

        fig, axes = plt.subplots(2, 2, figsize=(11, 8))
        fig.suptitle(run.name)

        axes[0][0].hist(p["total_latency"], bins=40)
        axes[0][0].axvline(p["total_latency"].mean(), color="red", linestyle="--", label="mean")
        axes[0][0].set_title("Total latency distribution")
        axes[0][0].set_xlabel("cycles")
        axes[0][0].legend()

        axes[0][1].boxplot([p["source_queue_delay"], p["network_latency"]],
                            tick_labels=["queue delay", "network latency"])
        axes[0][1].set_title("Latency breakdown")
        axes[0][1].set_ylabel("cycles")

        hop_counts = p["hops"].value_counts().sort_index()
        axes[1][0].bar(hop_counts.index, hop_counts.values)
        axes[1][0].set_title("Hop count distribution")
        axes[1][0].set_xlabel("hops")

        axes[1][1].scatter(p["request_time"], p["total_latency"], alpha=0.5, s=10)
        axes[1][1].set_title("Latency over time")
        axes[1][1].set_xlabel("request cycle")
        axes[1][1].set_ylabel("total latency")

        fig.tight_layout()
        out_file = png_dir / f"{safe_name}_summary.png"
        fig.savefig(out_file, dpi=130)
        plt.close(fig)
        print(f"wrote {out_file}")

    # cross-run comparison PNG
    if len(runs) > 1:
        fig, ax = plt.subplots(figsize=(8, 5))
        for run in runs:
            s = run.packets["total_latency"].sort_values()
            y = [i / len(s) for i in range(1, len(s) + 1)]
            ax.plot(s.values, y, label=run.name)
        ax.set_title("Latency CDF -- all runs")
        ax.set_xlabel("total latency (cycles)")
        ax.set_ylabel("fraction of packets")
        ax.legend()
        fig.tight_layout()
        out_file = png_dir / "comparison_cdf.png"
        fig.savefig(out_file, dpi=130)
        plt.close(fig)
        print(f"wrote {out_file}")


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True,
                     help="'NAME:TRACE_CSV:PACKETS_CSV' (TRACE_CSV may be empty: 'NAME::PACKETS_CSV')")
    ap.add_argument("--out", default="report.html", help="output HTML report path")
    ap.add_argument("--png-dir", default=None, help="if set, also write matplotlib PNGs here")
    ap.add_argument("--offline", action="store_true",
                     help="embed plotly.js inline instead of loading from CDN (larger file, no internet needed)")
    args = ap.parse_args()

    runs = [parse_run_arg(r) for r in args.run]

    build_report(runs, args.out, args.offline)
    if args.png_dir:
        write_pngs(runs, args.png_dir)


if __name__ == "__main__":
    main()
