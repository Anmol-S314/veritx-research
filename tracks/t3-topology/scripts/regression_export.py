#!/usr/bin/env python3
"""PA-23 — Standalone regression review export.

Reads the real dashboard history and writes a self-contained HTML experiment
review table. No Plotly, CDN, or synthetic data are used.

Characteristic latency matches generate_dashboard.py:
the latency at the lowest valid injection rate for each topology.

Usage:
    python3 scripts/regression_export.py
    python3 scripts/regression_export.py --history results/baseline/history.json
    python3 scripts/regression_export.py --out output/regression_review.html
"""

import argparse
import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRACK = HERE.parent
RESULTS = TRACK / "results"
OUTPUT = TRACK / "output"


def load_history(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"History file not found: {path}")
    hist = json.loads(path.read_text())
    if not isinstance(hist, list) or not hist:
        raise ValueError(f"History is empty or invalid: {path}")
    return hist


def topology_names(hist):
    return sorted({t for h in hist for t in h.get("latency", {})})


def delta_pct(current, previous):
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / previous * 100.0


def headline(hist):
    if len(hist) < 2:
        return "First recorded run — no previous baseline is available."

    cur = hist[-1].get("latency", {})
    prev = hist[-2].get("latency", {})
    common = [t for t in cur if cur.get(t) is not None and prev.get(t) not in (None, 0)]
    if not common:
        return "No comparable topology measurements versus the previous run."

    avg = sum(delta_pct(cur[t], prev[t]) for t in common) / len(common)
    if avg > 0:
        return f"Average characteristic latency increased by {avg:.1f}% versus run #{hist[-2].get('run', '?')}."
    if avg < 0:
        return f"Average characteristic latency improved by {abs(avg):.1f}% versus run #{hist[-2].get('run', '?')}."
    return f"Average characteristic latency is unchanged versus run #{hist[-2].get('run', '?')}."


def cell(value, previous):
    if value is None:
        return "<td class='missing'>—</td>"

    d = delta_pct(value, previous)
    text = f"{float(value):.2f}"
    if d is None:
        return f"<td>{text}<span class='unit'> cycles</span></td>"
    if d > 0:
        return f"<td>{text}<span class='delta regression'>▲ {abs(d):.1f}%</span></td>"
    if d < 0:
        return f"<td>{text}<span class='delta improvement'>▼ {abs(d):.1f}%</span></td>"
    return f"<td>{text}<span class='delta neutral'>▬ 0.0%</span></td>"


def render_html(hist, source):
    topos = topology_names(hist)
    rows = []

    for idx in range(len(hist) - 1, -1, -1):
        run = hist[idx]
        prev = hist[idx - 1] if idx else None
        lat = run.get("latency", {})
        prev_lat = prev.get("latency", {}) if prev else {}

        commit = f"{run.get('sha', '')} {run.get('msg', '')}".strip()
        cells = [
            f"<td class='run'>#{html.escape(str(run.get('run', idx + 1)))}</td>",
            f"<td class='date'>{html.escape(str(run.get('date', '')))}</td>",
        ]
        for topo in topos:
            cells.append(cell(lat.get(topo), prev_lat.get(topo)))
        cells.append(f"<td class='commit'>{html.escape(commit)}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")

    head = "".join(f"<th>{html.escape(t)}</th>" for t in topos)
    body = "\n".join(rows)
    latest = hist[-1]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>T3 Regression Review</title>
<style>
:root {{
  --bg:#f5f7fa; --card:#fff; --text:#18212b; --muted:#667085;
  --border:#d9dee7; --head:#263648; --bad:#b42318; --good:#087443;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:32px; background:var(--bg); color:var(--text);
       font:14px Arial, Helvetica, sans-serif; }}
.report {{ max-width:1500px; margin:auto; background:var(--card); border:1px solid var(--border);
           border-radius:10px; padding:28px; box-shadow:0 1px 4px rgba(0,0,0,.06); }}
h1 {{ margin:0 0 6px; font-size:25px; }}
.meta, .method {{ color:var(--muted); margin:5px 0; }}
.summary {{ margin:20px 0; padding:13px 16px; background:#eef3f8; border-left:4px solid #46627f;
            font-weight:600; }}
.table-wrap {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ background:var(--head); color:#fff; text-align:left; padding:11px 10px; white-space:nowrap; }}
td {{ border-bottom:1px solid var(--border); padding:10px; vertical-align:top; white-space:nowrap; }}
tr:nth-child(even) td {{ background:#fafbfd; }}
.run {{ font-weight:700; }}
.date, .commit, .missing {{ color:var(--muted); }}
.delta {{ display:block; margin-top:3px; font-size:12px; font-weight:700; }}
.regression {{ color:var(--bad); }}
.improvement {{ color:var(--good); }}
.neutral {{ color:var(--muted); }}
.unit {{ color:var(--muted); font-size:11px; }}
footer {{ margin-top:18px; color:var(--muted); font-size:12px; }}
@media print {{
  body {{ padding:0; background:#fff; }}
  .report {{ border:0; box-shadow:none; max-width:none; }}
  tr {{ break-inside:avoid; }}
}}
</style>
</head>
<body>
<div class="report">
  <h1>T3 Topology Regression Review</h1>
  <p class="meta">Latest run: #{html.escape(str(latest.get('run', '?')))} ·
     {html.escape(str(latest.get('sha', '')))} · {html.escape(str(latest.get('date', '')))}</p>
  <p class="method">Metric: characteristic latency = latency at the lowest valid injection rate.
     Δ% is relative to the immediately preceding recorded run; lower latency is better.</p>
  <div class="summary">{html.escape(headline(hist))}</div>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Run</th><th>Date</th>{head}<th>Commit</th></tr></thead>
      <tbody>{body}</tbody>
    </table>
  </div>
  <footer>Source: {html.escape(str(source))}. Self-contained export; no Plotly/CDN dependency.</footer>
</div>
</body>
</html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", default=None)
    ap.add_argument("--out", default=str(OUTPUT / "regression_review.html"))
    args = ap.parse_args()

    if args.history:
        history_path = Path(args.history)
    else:
        candidates = [RESULTS / "baseline" / "history.json", RESULTS / "history.json"]
        history_path = next((p for p in candidates if p.exists()), candidates[0])

    hist = load_history(history_path)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(hist, history_path), encoding="utf-8")
    print(f"  regression review → {out}  ({len(hist)} recorded runs)")


if __name__ == "__main__":
    main()
