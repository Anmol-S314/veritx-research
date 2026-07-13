#!/usr/bin/env python3
"""Generate a self-contained T3 dashboard (single index.html, no server/build).

Local:  python3 scripts/generate_dashboard.py     (or `make dashboard`)
Reads results/topology_sweep.json (+ optional traffic matrix & Timeloop stats),
appends this run's full view-data to results/history.json (capped), and writes
report/t3/index.html using Plotly from a CDN. Every past run is embedded — pick
one from the run selector (or open ?run=<n>) to inspect its matrix / curves /
bottlenecks. The same script runs in CI (dashboard uploaded as a private artifact).
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
        sys.exit(f"  no {p} — run `make timeloop` (or `make sim`) first")
    return json.loads(p.read_text())


def curves(sweep):
    """topology -> sorted [(injection_rate, latency, hops)] (valid points only)."""
    out = {}
    for r in sweep:
        if r.get("latency_cycles") is not None:
            out.setdefault(r["topology"], []).append(
                [r["injection_rate"], r["latency_cycles"], r.get("hops_avg")]
            )
    for t in out:
        out[t].sort()
    return out


def node_counts(sweep):
    """topology -> node count, as recorded by run_experiments."""
    return {r["topology"]: r["nodes"] for r in sweep if r.get("nodes")}


def failures(sweep):
    """topology -> why it produced no plottable data.

    A topology with no valid points is invisible in every panel (curves() drops
    it). Silently omitting it is how a config that Booksim rejected -- usually a
    node count that doesn't match the traffic matrix -- looks exactly like a
    config you never added. Surface it instead.
    """
    ok = {r["topology"] for r in sweep if r.get("latency_cycles") is not None}
    bad = {}
    for r in sweep:
        t = r["topology"]
        if t not in ok and t not in bad:
            bad[t] = r.get("error") or "no data (booksim printed no latency)"
    return bad


def failure_banner(bad):
    if not bad:
        return ""
    rows = "".join(f"<li><b>{t}</b> — {msg}</li>" for t, msg in sorted(bad.items()))
    return (f'<div class="warn"><b>{len(bad)} topology(ies) produced no data and '
            f'are not plotted below:</b><ul>{rows}</ul></div>')


def saturation_point(pts):
    """Injection rate at which latency exceeds 2x zero-load, else None."""
    if len(pts) < 2:
        return None
    zl = pts[0][1]
    for rate, lat, _ in pts:
        if lat > 2.0 * zl:
            return rate
    return None


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


def load_matrices(pattern):
    """{node_count: matrix} for every traffic_matrix_<N>.txt in results/.

    A sweep may now mix 16- and 64-node topologies, each driven by its own
    matrix, so the heatmap panel has to hold more than one. Legacy single-file
    runs (traffic_matrix.txt) still load, keyed by their own dimension.
    """
    out = {}
    for p in sorted(RESULTS.glob(pattern)):
        m = load_matrix(p)
        if m:
            out[str(len(m))] = m          # JSON keys are strings
    legacy = RESULTS / "traffic_matrix.txt"
    if not out and legacy.exists():
        m = load_matrix(legacy)
        if m:
            out[str(len(m))] = m
    return out or None


def load_levels(path):
    p = Path(path)
    if not p.exists():
        return None
    lv = [{"name": l["name"], "accesses": l["accesses"] * l["instances"]}
          for l in parse_levels(p.read_text())]
    return lv or None


def load_all_levels(pattern):
    """{node_count: levels} — each size has its own Timeloop run, so its own
    access breakdown. A 64-PE mapping is not a 16-PE mapping scaled up."""
    out = {}
    for p in sorted(RESULTS.glob(pattern)):
        n = p.name.replace("timeloop_", "").replace(".stats.txt", "")
        lv = load_levels(p)
        if lv and n.isdigit():
            out[n] = lv
    legacy = RESULTS / "timeloop.stats.txt"
    if not out and legacy.exists():
        lv = load_levels(legacy)
        if lv:
            out["_"] = lv          # unknown size; picker falls back to it
    return out or None


def load_energy(pattern):
    """{node_count: energy+area record} written by energy_report.py / area_report.py."""
    out = {}
    for p in sorted(RESULTS.glob(pattern)):
        n = p.name.replace("energy_", "").replace(".json", "")
        if n.isdigit():
            out[n] = json.loads(p.read_text())
    return out or None


def build_record(cur, matrices, levels, nodes=None, energy=None):
    """Everything needed to redraw one run's panels later."""
    hops = {t: [[r, h] for r, _, h in pts if h is not None] for t, pts in cur.items()}
    # Keep "matrix" for the single-size case so old history entries still render.
    one = next(iter(matrices.values())) if matrices and len(matrices) == 1 else None
    # Keep flat "levels" for the single-size case so old history entries render.
    flat = next(iter(levels.values())) if levels and len(levels) == 1 else None
    return {
        **git_info(),
        "latency": characteristic_latency(cur),
        "curves": cur,
        "saturation": {t: saturation_point(pts) for t, pts in cur.items()},
        "hops": {t: pts for t, pts in hops.items() if pts} or None,
        "matrix": one,
        "matrices": matrices or None,
        "nodes": nodes or None,        # topology -> node count, for the legend
        "levels": flat,
        "levelsBySize": levels or None,
        "energyBySize": energy or None,
    }


def update_history(record):
    """Append this run's full record; replace a re-run of the same commit; cap."""
    p = RESULTS / "history.json"
    hist = json.loads(p.read_text()) if p.exists() else []
    hist = [h for h in hist if h.get("sha") != record["sha"]]
    run_no = (hist[-1]["run"] + 1) if hist else 1
    hist.append({"run": run_no, **record})
    hist = hist[-HISTORY_CAP:]
    # ponytail: stores curves+matrix per run — tens of KB at 16 tiles x 20 runs.
    # If matrices get big (64+ tiles) cap matrix history or downsample here.
    p.write_text(json.dumps(hist, separators=(",", ":")))
    return hist


def regression_table(hist):
    topos = sorted({t for h in hist for t in h["latency"]})
    head = "".join(f"<th>{t}</th>" for t in topos)
    rows = ""
    n = len(hist)
    for i, h in enumerate(reversed(hist)):
        idx = n - 1 - i                          # original index into RUNS (row highlight)
        prev = hist[idx - 1] if idx - 1 >= 0 else None
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
        rows += f"<tr id='row{idx}'><td>#{h['run']}</td>{cells}<td class='commit'>{h['sha']} {h['msg']}</td></tr>"
    return f"<table id='regt'><tr><th>Run</th>{head}<th>Commit</th></tr>{rows}</table>"


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


def run_options(hist):
    return "".join(
        f'<option value="{i}"{" selected" if i == len(hist) - 1 else ""}>'
        f'#{h["run"]} · {h["sha"]} {h["msg"]}</option>'
        for i, h in reversed(list(enumerate(hist))))


HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>T3 Topology Dashboard</title>
<script src="__CDN__"></script>
<style>
 :root{--bg:#f8f9fa;--card:#ffffff;--border:#dee2e6;--text:#212529;--sub:#6c757d;--h2:#495057;--note:#adb5bd;--btn:#0d6efd}
 .dark{--bg:#0f1117;--card:#161a23;--border:#232838;--text:#e6e6e6;--sub:#9aa4b2;--h2:#cbd5e0;--note:#718096;--btn:#2b6cb0}
 body{font:14px system-ui,sans-serif;margin:0;background:var(--bg);color:var(--text);transition:background .2s,color .2s}
 header{padding:16px 24px;background:var(--card);border-bottom:2px solid var(--btn);display:flex;justify-content:space-between;align-items:flex-start}
 h1{margin:0;font-size:18px} .sub{color:var(--sub);font-size:13px;margin-top:4px}
 .badge{font-weight:600} .up{color:#cc3b3b} .down{color:#2b8a3e}
 .bar{padding:10px 24px;background:var(--card);border-bottom:1px solid var(--border)}
 .bar label{color:var(--sub);margin-right:8px}
 select{font:13px system-ui;padding:4px 8px;border:1px solid var(--border);border-radius:6px;background:var(--card);color:var(--text);max-width:560px}
 .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:16px 24px}
 .card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:12px;transition:background .2s}
 .card h2{font-size:14px;margin:0 0 8px;color:var(--h2)}
 .full{grid-column:1/3}
 table{border-collapse:collapse;width:100%;font-size:13px}
 th,td{border:1px solid var(--border);padding:5px 8px;text-align:right}
 th:last-child,td.commit{text-align:left} .commit{color:var(--sub);font-family:monospace}
 tr.sel td{background:rgba(43,108,176,.14)}
 .note{color:var(--note);font-style:italic}
 .toggle{background:var(--btn);color:#fff;border:none;border-radius:6px;padding:5px 14px;font-size:12px;cursor:pointer;white-space:nowrap;margin-left:12px}
 .toggle:hover{opacity:.85}
 .warn{margin:12px 24px 0;padding:10px 14px;border-radius:8px;font-size:13px;background:rgba(204,59,59,.10);border:1px solid rgba(204,59,59,.45);color:var(--text)}
 .warn ul{margin:6px 0 0;padding-left:20px} .warn li{margin:2px 0}
 .psub{color:var(--sub);font-weight:400;font-size:12px;margin-left:6px}
</style></head><body>
<header><div><h1>T3 Topology Dashboard</h1>
<div class="sub">Latest: run #__RUN__ · <span class="commit">__SHA__ __MSG__</span> · __DATE__ · <span class="badge">__HEADLINE__</span></div></div>
 <button class="toggle" id="themeToggle">Dark mode</button></header>
<div class="bar"><label>Viewing run:</label><select id="runsel">__OPTIONS__</select><span id="mwrap" style="display:none"><label style="margin-left:18px">NoC size:</label><select id="msel"></select></span></div>
__FAILED__
<div class="grid">
 <div class="card"><h2>Traffic Matrix<span class="psub" id="heatsub"></span></h2><div id="heat"></div></div>
 <div class="card"><h2>Latency vs Injection Rate</h2><div id="lat"></div></div>
 <div class="card"><h2>Hops (energy proxy)</h2><div id="hops"></div></div>
 <div class="card full"><h2>Regression — last __N__ runs</h2>__TABLE__</div>
 <div class="card"><h2>Energy — pJ/compute<span class="psub" id="ensub"></span></h2><div id="en"></div></div>
 <div class="card"><h2>Die Area<span class="psub" id="arsub"></span></h2><div id="ar"></div></div>
 <div class="card full"><h2>Timeloop Access Breakdown (bottlenecks)<span class="psub" id="bottsub"></span></h2><div id="bott"></div></div>
</div>
<script>
const RUNS=__DATA__;
let CUR=RUNS.length-1;
const THEMES={dark:{paper:'#161a23',plot:'#0f1117',font:'#e6e6e6',btn:'#2b6cb0'},light:{paper:'#ffffff',plot:'#f8f9fa',font:'#212529',btn:'#0d6efd'}};
function theme(){return document.body.classList.contains('dark')?'dark':'light'}
function lo(t){return{paper_bgcolor:THEMES[t].paper,plot_bgcolor:THEMES[t].plot,font:{color:THEMES[t].font},margin:{t:10,r:10,b:40,l:50}}}
function note(id,msg){document.getElementById(id).innerHTML="<p class='note'>"+msg+"</p>"}
// Sweeps may mix node counts; an unlabelled legend would invite comparing a
// 16-node mesh against a 64-node one as if they were the same experiment.
function lbl(r,n){const k=r.nodes&&r.nodes[n];return k?n+' ('+k+'n)':n}
function draw(){
  const r=RUNS[CUR]; if(!r)return;
  const t=theme(), ly=lo(t);
  // A run holds one traffic matrix AND one Timeloop breakdown per node count --
  // each size gets its own arch (PEs == tiles) and its own mapping. One picker
  // governs both panels, so they always describe the same machine.
  const mats=r.matrices||(r.matrix?{[r.matrix.length]:r.matrix}:null);
  const lvls=r.levelsBySize||(r.levels?{'_':r.levels}:null);
  const msel=document.getElementById('msel');
  const sizes=[...new Set([...Object.keys(mats||{}),...Object.keys(lvls||{})])]
    .filter(n=>n!=='_').sort((a,b)=>a-b);
  if(msel.dataset.run!==String(CUR)){
    msel.innerHTML=sizes.map(n=>`<option value="${n}">${n} tiles</option>`).join('');
    msel.dataset.run=String(CUR);
  }
  document.getElementById('mwrap').style.display=sizes.length>1?'':'none';
  const N=(sizes.includes(msel.value)?msel.value:sizes[0]);
  if(N)msel.value=N;

  // Neither of these panels is per-topology, and saying so kills the obvious
  // misreading. Timeloop never sees the NoC -- every topology of a given size
  // shares one mapping. And the matrix is deliberately shared: identical traffic
  // is the controlled variable, otherwise a topology could "win" on easier input.
  const same=N?Object.keys(r.nodes||{}).filter(t=>String(r.nodes[t])===String(N)):[];
  const shared=same.length?` — same for all ${same.length} ${N}-node topologies: ${same.join(', ')}`:'';
  document.getElementById('heatsub').textContent=N?`${N} tiles${shared}`:'';
  document.getElementById('bottsub').textContent=N?`${N}-PE mapping${shared}`:'';

  const mat=mats&&(mats[N]||(sizes.length?null:Object.values(mats)[0]));
  if(mat)Plotly.newPlot('heat',[{z:mat,type:'heatmap',colorscale:'YlOrRd'}],
      {...ly,xaxis:{title:'dst tile'},yaxis:{title:'src tile',autorange:'reversed'}},{displayModeBar:false,responsive:true});
  else note('heat','no traffic matrix for this run');
  if(r.curves){
    const maxY=Math.max(...Object.values(r.curves).flat().map(x=>x[1]));
    const latT=Object.entries(r.curves).map(([n,p])=>({x:p.map(x=>x[0]),y:p.map(x=>x[1]),name:lbl(r,n),mode:'lines+markers'}));
    const satT=Object.entries(r.saturation||{}).filter(([_,v])=>v!==null).map(([n,v])=>({x:[v,v],y:[0,maxY],mode:'lines',name:n+' sat',showlegend:false,line:{dash:'dot',width:1,color:THEMES[t].font}}));
    Plotly.newPlot('lat',[...latT,...satT],
      {...ly,xaxis:{title:'injection rate'},yaxis:{title:'latency (cycles)'},legend:{orientation:'h'}},{displayModeBar:false,responsive:true});
  } else note('lat','no sweep data for this run');
  if(r.hops)Plotly.newPlot('hops',Object.entries(r.hops).map(([n,p])=>({x:p.map(x=>x[0]),y:p.map(x=>x[1]),name:lbl(r,n),mode:'lines+markers'})),
    {...ly,xaxis:{title:'injection rate'},yaxis:{title:'avg hops'},legend:{orientation:'h'}},{displayModeBar:false,responsive:true});
  else note('hops','no hops data for this run');
  // Energy + area: also per node count, not per topology. Energy is Timeloop's
  // (built-in PAT model); area is Accelergy's, and it is the only one that prices
  // the routers -- which is the whole point, since they dominate the die.
  const en=(r.energyBySize||{})[N];
  if(en&&en.pj_per_compute){
    const e=Object.entries(en.pj_per_compute).filter(([_,v])=>v>0).sort((a,b)=>b[1]-a[1]);
    document.getElementById('ensub').textContent=
      `${en.energy_uJ} uJ · ${en.cycles} cyc · EDP ${en.edp_uJ_cycles}`;
    Plotly.newPlot('en',[{x:e.map(x=>x[1]),y:e.map(x=>x[0]),type:'bar',orientation:'h',
      marker:{color:THEMES[t].btn}}],
      {...ly,margin:{t:10,r:10,b:40,l:130},xaxis:{title:'pJ / compute'}},
      {displayModeBar:false,responsive:true});
  } else {document.getElementById('ensub').textContent='';note('en','no energy data — run `make energy`')}

  // Area IS per-topology now: routers are priced by radix, so a 5-port mesh
  // router and a 10-port flatfly router no longer cost the same. This is the
  // panel that lets topology trade off against latency -- the Pareto axis.
  const ar=en&&en.area, tp=ar&&ar.topologies;
  if(tp){
    const t2=Object.entries(tp).sort((a,b)=>a[1].total_area_um2-b[1].total_area_um2);
    const lo=t2[0][1].total_area_mm2, hi=t2[t2.length-1][1].total_area_mm2;
    document.getElementById('arsub').textContent=
      `${lo}–${hi} mm² · ${ar.flit_bits}b flits · NoC is ${t2[0][1].noc_share_pct}–${t2[t2.length-1][1].noc_share_pct}% of the die`;
    Plotly.newPlot('ar',[
      {x:t2.map(x=>x[0]),y:t2.map(x=>x[1].noc_um2_total),name:'NoC (routers)',type:'bar',
       customdata:t2.map(x=>[x[1].radix,x[1].routers]),
       hovertemplate:'%{x}<br>NoC %{y:,.0f} um²<br>radix %{customdata[0]}, %{customdata[1]} routers<extra></extra>'},
      {x:t2.map(x=>x[0]),y:t2.map(()=>ar.base_um2),name:'PE array + buffer',type:'bar',
       hovertemplate:'%{y:,.0f} um²<extra></extra>'},
    ],{...ly,barmode:'stack',yaxis:{title:'area (um²)'},legend:{orientation:'h'}},
      {displayModeBar:false,responsive:true});
  } else {document.getElementById('arsub').textContent=''; note('ar','no area data — run `make area`')}

  const lv=lvls&&(lvls[N]||lvls['_']);
  if(lv)Plotly.newPlot('bott',[{x:lv.map(l=>l.accesses),y:lv.map(l=>l.name),type:'bar',orientation:'h',marker:{color:THEMES[t].btn}}],
    {...ly,margin:{t:10,r:10,b:40,l:130},xaxis:{title:'word accesses'}},{displayModeBar:false,responsive:true});
  else note('bott','no Timeloop stats for this run');
  document.querySelectorAll('#regt tr.sel').forEach(x=>x.classList.remove('sel'));
  const row=document.getElementById('row'+CUR); if(row)row.classList.add('sel');
}
document.getElementById('msel').addEventListener('change',draw);
const sel=document.getElementById('runsel');
sel.onchange=()=>{CUR=+sel.value;draw();};
(function(){
  if(localStorage.getItem('theme')==='dark')document.body.classList.add('dark');
  const tog=document.getElementById('themeToggle');
  tog.textContent=theme()==='dark'?'Light mode':'Dark mode';
  tog.onclick=function(){document.body.classList.toggle('dark');const t=theme();localStorage.setItem('theme',t);this.textContent=t==='dark'?'Light mode':'Dark mode';draw();};
  const raw=new URLSearchParams(location.search).get('run');   // absent -> keep latest (not run 0)
  const q=raw==null?-1:+raw;
  if(Number.isInteger(q)&&RUNS[q]){CUR=q;sel.value=q;}
  draw();
})();
</script></body></html>"""


def _selfcheck():
    def mk(sha, run_msg, m_lat):
        pts = [[0.1, m_lat, 1.0], [0.2, m_lat * 3, 2.0]]
        return {"sha": sha, "msg": run_msg, "date": "2026-01-01", "latency": {"mesh4x4": m_lat},
                "curves": {"mesh4x4": pts}, "saturation": {"mesh4x4": 0.2},
                "hops": {"mesh4x4": [[0.1, 1.0], [0.2, 2.0]]},
                "matrix": [[0, m_lat], [m_lat, 0]], "levels": [{"name": "DRAM", "accesses": m_lat}]}
    hist = [{"run": 1, **mk("aaa", "first", 100)}, {"run": 2, **mk("bbb", "second", 80)}]
    opts = run_options(hist)
    assert opts.count("<option") == 2 and 'value="1" selected' in opts, opts   # latest pre-selected
    tbl = regression_table(hist)
    assert "id='row0'" in tbl and "id='row1'" in tbl, tbl                      # every run addressable
    assert "▼20%" in tbl, tbl                                                  # 100->80 shows improvement
    assert "better" in headline(hist), headline(hist)
    assert json.loads(json.dumps(hist))[0]["curves"]["mesh4x4"][0] == [0.1, 100, 1.0]  # embedding round-trips
    mixed = [{"run": 0, "sha": "old", "msg": "legacy", "date": "", "latency": {"mesh4x4": 5}}] + hist
    view = [h for h in mixed if h.get("curves")]
    assert len(view) == 2 and all(h.get("curves") for h in view), view   # latency-only run excluded
    print("selfcheck OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--matrix", default="traffic_matrix_*.txt",
                    help="glob under results/ matching one matrix per node count")
    ap.add_argument("--timeloop-stats", default="timeloop_*.stats.txt",
                    help="glob under results/ matching one stats file per node count")
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()
    if args.selfcheck:
        _selfcheck(); return

    sweep = load_sweep()
    cur = curves(sweep)
    bad = failures(sweep)
    record = build_record(cur, load_matrices(args.matrix),
                          load_all_levels(args.timeloop_stats), node_counts(sweep),
                          load_energy("energy_*.json"))
    hist = update_history(record)
    # Only show runs we can actually render. Pre-feature runs stored latency only
    # (no curves/matrix) — offering them gave empty panels. They stay in history.json
    # (they age out via the cap) but are hidden from the selector + table.
    view = [h for h in hist if h.get("curves")] or hist[-1:]

    html = (HTML
            .replace("__CDN__", PLOTLY_CDN)
            .replace("__RUN__", str(view[-1]["run"]))
            .replace("__SHA__", view[-1]["sha"])
            .replace("__MSG__", view[-1]["msg"])
            .replace("__DATE__", view[-1]["date"])
            .replace("__HEADLINE__", headline(view))
            .replace("__N__", str(len(view)))
            .replace("__OPTIONS__", run_options(view))
            .replace("__TABLE__", regression_table(view))
            .replace("__FAILED__", failure_banner(bad))
            .replace("__DATA__", json.dumps(view, separators=(",", ":"))))

    REPORT.mkdir(parents=True, exist_ok=True)
    out = REPORT / "index.html"
    out.write_text(html)
    print(f"  dashboard → {out}  (run #{hist[-1]['run']}, {len(hist)} runs total, {headline(hist)})")


if __name__ == "__main__":
    main()
