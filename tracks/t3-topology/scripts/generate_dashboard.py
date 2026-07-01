#!/usr/bin/env python3
"""Generate a self-contained T3 dashboard (single index.html, no server/build).

Local:  python3 scripts/generate_dashboard.py     (or `make dashboard`)
Reads results/topology_sweep.json (+ optional traffic matrix & Timeloop stats),
appends this run to results/history.json (capped), and writes report/t3/index.html
using Plotly from a CDN. The same script runs in CI to publish to GitHub Pages.
"""
import json, subprocess, sys, argparse
from pathlib import Path

HERE = Path(__file__).parent
TRACK = HERE.parent
RESULTS = TRACK / "results"
REPORT = TRACK.parent.parent / "report" / "t3"
HISTORY_CAP = 20
PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"

sys.path.insert(0, str(HERE))
from timeloop_to_matrix import parse_levels  # reuse the Timeloop stats parser


def git_info():
    def g(args, default=""):
        try:
            return subprocess.check_output(args, cwd=TRACK, text=True,
                                           stderr=subprocess.DEVNULL).strip()
        except Exception:
            return default
    return {
        "sha": g(["git", "rev-parse", "--short", "HEAD"], "local"),
        "msg": g(["git", "log", "-1", "--format=%s"], "(uncommitted)")[:60],
        "date": g(["git", "log", "-1", "--format=%cd", "--date=short"], ""),
    }


def load_sweep():
    p = RESULTS / "topology_sweep.json"
    if not p.exists():
        sys.exit(f"  no {p} — run `make sim` first")
    return json.loads(p.read_text())


def curves(sweep):
    """topology -> sorted [(injection_rate, latency)] (valid points only)."""
    out = {}
    for r in sweep:
        if r.get("latency_cycles") is not None:
            out.setdefault(r["topology"], []).append([r["injection_rate"], r["latency_cycles"]])
    for t in out:
        out[t].sort()
    return out


def characteristic_latency(cur):
    """Per topology: zero-load latency = latency at the lowest valid injection rate."""
    return {t: pts[0][1] for t, pts in cur.items() if pts}


def load_matrix(path):
    p = Path(path)
    if not p.exists():
        return None
    rows = []
    for line in p.read_text().splitlines():
        line = line.split("#")[0].strip()
        if line:
            rows.append([float(x) for x in line.split()])
    return rows or None


def load_levels(path):
    p = Path(path)
    if not p.exists():
        return None
    lv = [{"name": l["name"], "accesses": l["accesses"] * l["instances"]}
          for l in parse_levels(p.read_text())]
    return lv or None


def update_history(latency):
    p = RESULTS / "history.json"
    hist = json.loads(p.read_text()) if p.exists() else []
    gi = git_info()
    hist = [h for h in hist if h.get("sha") != gi["sha"]]  # replace re-runs of same commit
    hist.append({"run": (hist[-1]["run"] + 1) if hist else 1, **gi, "latency": latency})
    hist = hist[-HISTORY_CAP:]
    p.write_text(json.dumps(hist, indent=2))
    return hist


def regression_table(hist):
    topos = sorted({t for h in hist for t in h["latency"]})
    head = "".join(f"<th>{t}</th>" for t in topos)
    rows = ""
    for i, h in enumerate(reversed(hist)):
        prev = hist[len(hist) - 2 - i] if (len(hist) - 2 - i) >= 0 else None
        cells = ""
        for t in topos:
            v = h["latency"].get(t)
            if v is None:
                cells += "<td>–</td>"; continue
            delta = ""
            if prev and prev["latency"].get(t):
                d = (v - prev["latency"][t]) / prev["latency"][t] * 100
                arrow = "▲" if d > 0 else ("▼" if d < 0 else "▬")
                cls = "up" if d > 0 else ("down" if d < 0 else "")
                delta = f" <span class='{cls}'>{arrow}{abs(d):.0f}%</span>"
            cells += f"<td>{v:.0f}{delta}</td>"
        rows += f"<tr><td>#{h['run']}</td>{cells}<td class='commit'>{h['sha']} {h['msg']}</td></tr>"
    return f"<table><tr><th>Run</th>{head}<th>Commit</th></tr>{rows}</table>"


def headline(hist):
    if len(hist) < 2:
        return "first run — no baseline yet"
    cur, prev = hist[-1]["latency"], hist[-2]["latency"]
    common = [t for t in cur if cur[t] and prev.get(t)]
    if not common:
        return "no comparable topologies vs previous run"
    d = sum((cur[t] - prev[t]) / prev[t] for t in common) / len(common) * 100
    word = "worse" if d > 0 else ("better" if d < 0 else "unchanged")
    arrow = "▲" if d > 0 else ("▼" if d < 0 else "▬")
    return f"{arrow} {abs(d):.1f}% avg latency vs run #{hist[-2]['run']} ({word})"


HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>T3 Topology Dashboard</title>
<script src="__CDN__"></script>
<style>
 body{font:14px system-ui,sans-serif;margin:0;background:#0f1117;color:#e6e6e6}
 header{padding:16px 24px;background:#161a23;border-bottom:2px solid #2b6cb0}
 h1{margin:0;font-size:18px} .sub{color:#9aa4b2;font-size:13px;margin-top:4px}
 .badge{font-weight:600} .up{color:#f56565} .down{color:#48bb78}
 .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:16px 24px}
 .card{background:#161a23;border:1px solid #232838;border-radius:8px;padding:12px}
 .card h2{font-size:14px;margin:0 0 8px;color:#cbd5e0}
 .full{grid-column:1/3}
 table{border-collapse:collapse;width:100%;font-size:13px}
 th,td{border:1px solid #232838;padding:5px 8px;text-align:right}
 th:last-child,td.commit{text-align:left} .commit{color:#9aa4b2;font-family:monospace}
 .note{color:#718096;font-style:italic}
</style></head><body>
<header><h1>T3 Topology Dashboard</h1>
<div class="sub">Run #__RUN__ · <span class="commit">__SHA__ __MSG__</span> · __DATE__ · <span class="badge">__HEADLINE__</span></div></header>
<div class="grid">
 <div class="card"><h2>Traffic Matrix (this run)</h2><div id="heat">__NOMATRIX__</div></div>
 <div class="card"><h2>Latency vs Injection Rate</h2><div id="lat"></div></div>
 <div class="card full"><h2>Regression — last __N__ runs</h2>__TABLE__</div>
 <div class="card full"><h2>Timeloop Access Breakdown (bottlenecks)</h2><div id="bott">__NOLEVELS__</div></div>
</div>
<script>const D=__DATA__;
const dark={paper_bgcolor:'#161a23',plot_bgcolor:'#161a23',font:{color:'#cbd5e0'},margin:{t:10,r:10,b:40,l:50}};
if(D.matrix)Plotly.newPlot('heat',[{z:D.matrix,type:'heatmap',colorscale:'Viridis'}],
  {...dark,xaxis:{title:'dst tile'},yaxis:{title:'src tile',autorange:'reversed'}},{displayModeBar:false});
Plotly.newPlot('lat',Object.entries(D.curves).map(([t,p])=>({x:p.map(r=>r[0]),y:p.map(r=>r[1]),name:t,mode:'lines+markers'})),
  {...dark,xaxis:{title:'injection rate'},yaxis:{title:'latency (cycles)'},legend:{orientation:'h'}},{displayModeBar:false});
if(D.levels)Plotly.newPlot('bott',[{x:D.levels.map(l=>l.accesses),y:D.levels.map(l=>l.name),type:'bar',orientation:'h',marker:{color:'#2b6cb0'}}],
  {...dark,xaxis:{title:'word accesses'},margin:{t:10,r:10,b:40,l:130}},{displayModeBar:false});
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--matrix", default=str(RESULTS / "traffic_matrix.txt"))
    ap.add_argument("--timeloop-stats", default=str(RESULTS / "timeloop.stats.txt"))
    args = ap.parse_args()

    sweep = load_sweep()
    cur = curves(sweep)
    hist = update_history(characteristic_latency(cur))
    matrix = load_matrix(args.matrix)
    levels = load_levels(args.timeloop_stats)

    data = {"curves": cur, "matrix": matrix, "levels": levels}
    html = (HTML
            .replace("__CDN__", PLOTLY_CDN)
            .replace("__RUN__", str(hist[-1]["run"]))
            .replace("__SHA__", hist[-1]["sha"])
            .replace("__MSG__", hist[-1]["msg"])
            .replace("__DATE__", hist[-1]["date"])
            .replace("__HEADLINE__", headline(hist))
            .replace("__N__", str(len(hist)))
            .replace("__TABLE__", regression_table(hist))
            .replace("__NOMATRIX__", "" if matrix else "<p class='note'>no traffic_matrix.txt — uniform run</p>")
            .replace("__NOLEVELS__", "" if levels else "<p class='note'>no Timeloop stats for this run</p>")
            .replace("__DATA__", json.dumps(data)))

    REPORT.mkdir(parents=True, exist_ok=True)
    out = REPORT / "index.html"
    out.write_text(html)
    print(f"  dashboard → {out}  (run #{hist[-1]['run']}, {headline(hist)})")


if __name__ == "__main__":
    main()
