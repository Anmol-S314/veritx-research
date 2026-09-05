#!/usr/bin/env python3
"""multi_workload_pareto.py — traffic-aware Pareto evaluation.

Evaluates the same topologies across diverse workloads to find
traffic-robust designs. A topology optimized for mcast may be worse
on per-phase Mix — this quantifies it.

Usage:
  python3 multi_workload_pareto.py --traces runs/traces/qwen3_mcast_real.trace,runs/traces/hpc_wrf128_ring.trace --topos mesh_8x8,mecs64 --seeds 1
  python3 multi_workload_pareto.py --traces runs/traces/qwen3_mcast_real.trace,runs/traces/llama_1b_15all_960.trace --anynet runs/booksim/mecs64.anynet,runs/booksim/mot_64.anynet
"""
import argparse, json, sys, re, subprocess, tempfile, statistics
from pathlib import Path
from collections import defaultdict

REPO = Path(__file__).resolve().parents[4]
BOOKSIM_BIN = REPO / "third_party/booksim2/src/booksim"
RUNS_DIR = REPO / "runs"

_SWEEP_TOPOS = [
    ("mesh_8x8",   "mesh",    {"k": 8, "n": 2}, "dim_order"),
    ("torus_8x8",  "torus",   {"k": 8, "n": 2}, "dim_order"),
    ("flatfly_64", "flatfly", {"k": 4, "n": 2, "c": 4, "x": 4, "y": 4, "xr": 2, "yr": 2}, "ran_min"),
    ("gec_express", "gec",    {"k": 8, "c": 1, "o": 7, "d": 1}, "dor"),
    ("gec_mecs",   "gec",     {"k": 8, "c": 1, "o": 1, "d": 7, "vcs": 8}, "dor"),
]

def _parse_lat(output: str):
    m = re.search(r"Packet latency average\s*=\s*([0-9.]+)", output)
    if m: return float(m.group(1))
    return None

def _lookup(name):
    for tname, topo, extra, routing in _SWEEP_TOPOS:
        if tname == name or topo == name:
            return (tname, topo, extra, routing)
    p = Path(name)
    if not p.is_absolute(): p = REPO / name
    if p.exists() and p.suffix == ".anynet":
        return (p.stem, "anynet", {"network_file": str(p.resolve())}, "min")
    return None

def _count_anynet(filepath):
    nodes=set(); edges=set()
    try:
        for line in open(filepath):
            parts=line.strip().split()
            if len(parts)<5 or parts[0]!="router": continue
            rid=int(parts[1]); nodes.add(rid)
            i=4
            while i < len(parts):
                if parts[i]=="router" and i+1 < len(parts):
                    pid=int(parts[i+1]); nodes.add(pid)
                    edges.add((min(rid,pid),max(rid,pid))); i+=2
                else: i+=1
    except: pass
    return len(nodes), len(edges)

def _validate_trace(trace_path):
    """Check trace has diverse src/dst — reject stubs with <5 unique nodes."""
    srcs = set(); dsts = set()
    with open(trace_path) as f:
        for line in f:
            if line.startswith('#'): continue
            parts = line.split()
            if len(parts) >= 4:
                srcs.add(int(parts[1])); dsts.add(int(parts[3]))
    n_unique = len(srcs | dsts)
    if n_unique < 5:
        print(f"  ⚠  Trace {Path(trace_path).name}: only {n_unique} unique nodes (src={len(srcs)}, dst={len(dsts)}) — likely a stub")
    return len(srcs), len(dsts)


def _trace_span(trace_path):
    """Max cycle in trace (span)."""
    m = 0
    try:
        for line in open(trace_path):
            if line.startswith('#'): continue
            p = line.split()
            if len(p) >= 5:
                c = int(p[0])
                if c > m: m = c
    except: pass
    return m

def _detect_classes(trace_path):
    """Auto-detect number of traffic classes from trace file."""
    try:
        with open(trace_path) as f:
            for line in f:
                if line.startswith('#'): continue
                parts = line.split()
                if len(parts) >= 3:
                    cl = int(parts[2])
                    if cl > 0: return cl + 1
    except: pass
    return 1

def eval_once(trace_path, topo_spec, seed=42, timeout=60):
    name, topo, extra, routing = topo_spec
    trace = str(Path(trace_path).resolve())
    _nc = _detect_classes(trace_path)
    span = _trace_span(trace_path)
    # TRUE trace replay (8b19afeb): exact timestamps, full trace.
    # latency_thres must exceed real latency (default 500 aborts) — 1e6.
    # sample window sized so max_samples*period > span + drain.
    sp = max(50000, span + 10000)
    replay_common = [f"latency_thres = 1000000.0;", "sim_type = latency;",
                     f"sample_period = {sp};", "max_samples = 5;",
                     "warmup_periods = 1;", "use_noc_latency = 0;"]
    if topo=="anynet":
        nf=extra["network_file"]; nodes,edges=_count_anynet(nf)
        cfg_lines=[f"topology = anynet;",f"routing_function = min;",f"network_file = {nf};",f"traffic = trace({trace});","num_vcs = 4;","vc_buf_size = 8;","packet_size = 8;"] + replay_common + [f"seed = {seed};"]
    elif topo == "gec":
        k=extra.get("k",8); c=extra.get("c",1); o=extra.get("o",7); d=extra.get("d",1)
        vcs = extra.get("vcs", max(4, d))
        nodes = k*k*c
        # undirected edge count: intra-mesh k*k*2 (if mesh=1) + express row/col
        # full p2p express (d=1): per dim k*C(k,2) links = k*k*(k-1)/2 *2 dims
        if o >= k-1 and d == 1:
            edges = k*k*(k-1)  # row+col complete: 2 * k * C(k,2) = k^2(k-1)
        else:
            # tapped channels: o*d=k-1, per router drives o channels per dim
            edges = nodes * o * 2  # channel taps counted as logical links
        cfg_lines=[f"topology = gec;",f"k = {k};","n = 2;",f"c = {c};",f"o = {o};",f"d = {d};",f"routing_function = {routing};",f"num_vcs = {vcs};","vc_buf_size = 8;","packet_size = 8;",f"traffic = trace({trace});"] + replay_common + [f"seed = {seed};"]
    else:
        if topo in ("mesh","torus"):
            k=extra.get("k",8); n=extra.get("n",2); nodes=k**n; edges=n*k**n
        elif topo=="flatfly":
            k=extra.get("k",4); n=extra.get("n",2); c=extra.get("c",4); nodes=(k**n)*c; edges=nodes//c*(c+(k-1)*n - c)//2
        else: nodes=edges=0
        params={"topology":topo,"routing_function":routing,"num_vcs":4,"vc_buf_size":8,"packet_size":8,"traffic":f"trace({trace})","seed":seed}
        params.update({k2:v for k2,v in extra.items() if k2!="network_file"})
        cfg_lines=[f"{k2} = {v};" for k2,v in params.items()] + replay_common
    workdir=Path(tempfile.mkdtemp(dir=RUNS_DIR/"booksim"))
    try:
        cfg_path=workdir/"cfg.cfg"
        cfg_path.write_text("\n".join(cfg_lines)+"\n")
        r=subprocess.run([str(BOOKSIM_BIN.resolve()), str(cfg_path.resolve())], capture_output=True, text=True, timeout=timeout, cwd=str(workdir), stdin=subprocess.DEVNULL)
        lat=_parse_lat(r.stdout)
        if lat is None:
            # debug: print first 500 chars of stdout
            print(f"    [DEBUG] {name} exit={r.returncode} stdout={r.stdout[:500].replace(chr(10),'|')} stderr={r.stderr[:200]}", flush=True)
            return {"name":name,"topology":topo,"trace":str(trace_path),"trace_name":Path(trace_path).stem,"latency":None,"error":f"exit {r.returncode}","nodes":nodes,"edges":edges,"seed":seed}
        return {"name":name,"topology":topo,"trace":str(trace_path),"trace_name":Path(trace_path).stem,"latency":lat,"nodes":nodes,"edges":edges,"seed":seed}
    except subprocess.TimeoutExpired:
        return {"name":name,"topology":topo,"trace":str(trace_path),"trace_name":Path(trace_path).stem,"latency":None,"error":"timeout","nodes":nodes,"edges":edges,"seed":seed}
    finally:
        import shutil; shutil.rmtree(workdir, ignore_errors=True)

def pareto_front(points, keys):
    """points: list of dicts, keys: list of metric names to minimize. Returns (front, dominated)."""
    front=[]; dominated=[]
    for i,p in enumerate(points):
        dom=False
        for j,q in enumerate(points):
            if i==j: continue
            # q dominates p if q <= p on all keys and < on at least one
            le = all(q[k] <= p[k] for k in keys if q[k] is not None and p[k] is not None)
            lt = any(q[k] < p[k] for k in keys if q[k] is not None and p[k] is not None)
            if le and lt:
                dom=True; break
        (dominated if dom else front).append(p)
    return front, dominated

def main():
    ap=argparse.ArgumentParser(description="Multi-workload Pareto evaluation")
    ap.add_argument("--traces", required=True, help="comma-separated trace files")
    ap.add_argument("--topos", default="mesh_8x8,torus_8x8", help="comma-separated built-in names")
    ap.add_argument("--anynet", default="", help="comma-separated .anynet files")
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--out", default="runs/booksim/pareto.json")
    args=ap.parse_args()

    traces=[t.strip() for t in args.traces.split(",") if t.strip()]
    topo_names=[t.strip() for t in args.topos.split(",") if t.strip()]
    anynets=[a.strip() for a in args.anynet.split(",") if a.strip()]

    specs=[]
    for n in topo_names:
        s=_lookup(n)
        if not s: print(f"unknown topo {n}", file=sys.stderr); sys.exit(1)
        specs.append(s)
    for af in anynets:
        p=Path(af)
        if not p.is_absolute(): p=REPO/af
        if not p.exists(): print(f"anynet not found {af}", file=sys.stderr); sys.exit(1)
        specs.append((p.stem,"anynet",{"network_file":str(p.resolve())},"min"))

    trace_paths=[]
    for t in traces:
        p=Path(t)
        if not p.is_absolute(): p=REPO/t
        if not p.exists(): print(f"trace not found {t}", file=sys.stderr); sys.exit(1)
        trace_paths.append(p)

    print(f"Multi-workload Pareto: {len(specs)} topos × {len(trace_paths)} traces × {args.seeds} seeds = {len(specs)*len(trace_paths)*args.seeds} runs", flush=True)
    print(f"Traces: {', '.join(f'{p.name}({p.stat().st_size//1024}KB,{len(open(p).readlines())}pkts)' for p in trace_paths)}", flush=True)
    print(f"Topos: {', '.join(s[0] for s in specs)}", flush=True)
    # Validate traces
    for tp in trace_paths:
        _validate_trace(str(tp))
    import time
    # Run
    all_results=[]
    total=len(specs)*len(trace_paths)*args.seeds
    done=0
    t_start=time.time()
    for spec in specs:
        for tp in trace_paths:
            for si in range(args.seeds):
                seed=42+si
                done+=1
                print(f"[{done}/{total}] START {spec[0]:<20} {tp.stem:<25} seed={seed} timeout={args.timeout}s ...", flush=True)
                t0=time.time()
                r=eval_once(str(tp), spec, seed=seed, timeout=args.timeout)
                dt=time.time()-t0
                all_results.append(r)
                lat = f"{r['latency']:.2f}c" if r['latency'] is not None else r.get('error','FAIL')
                print(f"[{done}/{total}] DONE  {spec[0]:<20} {tp.stem:<25} seed={seed} → {lat}  ({dt:.1f}s, elapsed {time.time()-t_start:.1f}s)", flush=True)

    # Aggregate per topo per trace (mean over seeds)
    # Build per-topo vector: {name, edges, latency[0], latency[1], ...}
    trace_keys=[p.stem for p in trace_paths]
    by_topo=defaultdict(list)
    for r in all_results: by_topo[r['name']].append(r)
    agg=[]
    for name in [s[0] for s in specs]:
        rec={"name":name}
        runs=by_topo[name]
        # edges from first run
        rec["edges"]=runs[0].get("edges",0)
        rec["nodes"]=runs[0].get("nodes",0)
        ok=True
        for tk in trace_keys:
            vals=[r["latency"] for r in runs if r["trace_name"]==tk and r["latency"] is not None]
            if vals: rec[f"lat_{tk}"]=statistics.mean(vals)
            else: rec[f"lat_{tk}"]=None; ok=False
        # also mean across workloads
        lats=[rec[f"lat_{tk}"] for tk in trace_keys if rec[f"lat_{tk}"] is not None]
        rec["mean_lat"]=statistics.mean(lats) if lats else None
        rec["ok"]=ok
        # For pareto: use per-trace latencies + edges
        agg.append(rec)

    # Pareto on per-trace latencies + edges
    pareto_keys=[f"lat_{tk}" for tk in trace_keys]+["edges"]
    # filter ok only
    ok_agg=[a for a in agg if a["ok"]]
    front, dominated=pareto_front(ok_agg, pareto_keys)

    print("\n=== Pareto Summary ===")
    hdr=f"  {'Topo':<20} {'Edges':>6} " + " ".join(f"{tk[:12]:>10}" for tk in trace_keys) + f" {'Mean':>8} {'Status':>8}"
    print(hdr)
    print("  "+"─"*len(hdr))
    for a in sorted(agg, key=lambda x: x["mean_lat"] or 1e9):
        lats=" ".join(f"{a[f'lat_{tk}']:7.2f}c" if a[f'lat_{tk}'] is not None else "    N/A" for tk in trace_keys)
        mean=f"{a['mean_lat']:.2f}c" if a['mean_lat'] else "N/A"
        status="FRONT" if a in front else "dominated" if a in dominated else "fail"
        print(f"  {a['name']:<20} {a['edges']:>6} {lats} {mean:>8} {status:>8}")

    # Insight: workload sensitivity
    if len(trace_keys)>=2 and len(ok_agg)>=2:
        print("\n=== Traffic-aware insight ===")
        # Find topo that wins on trace0 but loses on trace1
        tk0,t1=trace_keys[0],trace_keys[1]
        best0=min(ok_agg, key=lambda a: a[f"lat_{tk0}"])
        best1=min(ok_agg, key=lambda a: a[f"lat_{t1}"])
        if best0["name"]!=best1["name"]:
            print(f"  Workload-sensitive: {best0['name']} best on {tk0} ({best0[f'lat_{tk0}']:.2f}c) but {best1['name']} best on {t1} ({best1[f'lat_{t1}']:.2f}c)")
            print(f"  → No single topology optimal for all — need Pareto / workload mix weighting")
        else:
            print(f"  Robust: {best0['name']} wins on both workloads — strong Pareto candidate")

    out=Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"traces":trace_keys,"topos":[s[0] for s in specs],"results":all_results,"agg":agg,"front":[f["name"] for f in front],"dominated":[d["name"] for d in dominated]}, indent=2))
    print(f"\nSaved: {out}")

if __name__=="__main__":
    main()
