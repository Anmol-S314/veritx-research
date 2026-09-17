#!/usr/bin/env python3
"""multi_workload_pareto.py — traffic-aware Pareto evaluation.

Evaluates the same topologies across diverse workloads to find
traffic-robust designs. A topology optimized for mcast may be worse
on per-phase Mix — this quantifies it.

Usage:
  python3 multi_workload_pareto.py --traces runs/traces/qwen3_mcast_real.trace,runs/traces/hpc_wrf128_ring.trace --topos mesh_8x8,mecs64 --seeds 1
  python3 multi_workload_pareto.py --traces runs/traces/qwen3_mcast_real.trace,runs/traces/llama_1b_15all_960.trace --anynet runs/booksim/mecs64.anynet,runs/booksim/mot_64.anynet
"""
import argparse, json, os, sys, re, subprocess, tempfile, statistics, math, hashlib
from pathlib import Path
from collections import defaultdict

REPO = Path(__file__).resolve().parents[4]
BOOKSIM_BIN = REPO / "third_party/booksim2/src/booksim"
RUNS_DIR = REPO / "runs"

# ── Auto-timeout budget (per-trace, not flat) ────────────────────────────
# A flat wall-clock cutoff measures the host, not the fabric: a 668k-packet
# serving trace and a 20k-packet slice need wildly different budgets, and a
# cutoff tuned for the small one labels every big-trace run TIMEOUT — the
# failure then reads as a topology property when it is a benchmark property.
# Budget = base + TIME_BUDGET_PER_PKT × packets, floored/clamped.
TIME_BUDGET_BASE_S = 120        # process start, parse, small traces
TIME_BUDGET_PER_PKT_S = 0.005   # ≈ 200 pkts/s; measured BookSim ≈ 10k/s, 2× headroom
TIME_BUDGET_MIN_S = 120
TIME_BUDGET_MAX_S = 1800


def auto_timeout(trace_path) -> int:
    """Wall-clock budget in seconds derived from the trace's packet count.

    Deliberately NOT a model of sim speed: a generous clamp with 2× headroom
    over measured throughput. Honest spin runs (injection>0) still hit the
    clamp instead of burning the machine forever.
    """
    pkts = _count_packets(trace_path)
    budget = TIME_BUDGET_BASE_S + TIME_BUDGET_PER_PKT_S * pkts
    return int(max(TIME_BUDGET_MIN_S, min(TIME_BUDGET_MAX_S, budget)))

# Unified synthesis evaluation machinery (Phase 2a). Script-mode safe:
# dse/ on sys.path first so `veritx_dse.*` resolves when run as a script.
try:
    _DSE_DIR = Path(__file__).resolve().parents[1]
    if str(_DSE_DIR) not in sys.path:
        sys.path.insert(0, str(_DSE_DIR))
except Exception:
    pass
try:
    from veritx_dse.synthesis.evaluator import (
        PARETO_PRESET,
        evaluate_spec,
        parse_latency as _shared_parse_latency,
        trace_span as _shared_trace_span,
    )
    from veritx_dse.synthesis.results import SynthResult as _SynthResult
    from veritx_dse.core.constants import BOOKSIM_SEED, DEFAULT_TIMEOUT, env_int
except Exception:
    try:
        from synthesis.evaluator import (  # type: ignore
            PARETO_PRESET,
            evaluate_spec,
            parse_latency as _shared_parse_latency,
            trace_span as _shared_trace_span,
        )
        from synthesis.results import SynthResult as _SynthResult  # type: ignore
        from veritx_dse.core.constants import BOOKSIM_SEED, DEFAULT_TIMEOUT, env_int  # type: ignore
    except Exception:
        PARETO_PRESET = None  # type: ignore
        evaluate_spec = None  # type: ignore
        _shared_parse_latency = None  # type: ignore
        _shared_trace_span = None  # type: ignore
        _SynthResult = None  # type: ignore
        BOOKSIM_SEED = 42  # type: ignore  # canonical home: core.constants
        DEFAULT_TIMEOUT = 60  # type: ignore
        def env_int(name, default):  # type: ignore
            import os
            raw = os.environ.get(name)
            if raw is None:
                return default
            return int(raw)


def _resolve_input(p: str):
    """Resolve a user-supplied trace/anynet path the way the rest of the CLI
    does: absolute → as-is, else cwd, repo root, then the t3 track dir.
    (Paths typed from tracks/t3-topology used to die with 'not found'
    because only REPO-relative resolution existed.)"""
    path = Path(p)
    if path.is_absolute():
        return path if path.exists() else None
    for base in (Path.cwd(), REPO, REPO / "tracks" / "t3-topology"):
        cand = base / path
        if cand.exists():
            return cand
    return None

_SWEEP_TOPOS = [
    ("mesh_8x8",   "mesh",    {"k": 8, "n": 2}, "dim_order"),
    ("torus_8x8",  "torus",   {"k": 8, "n": 2}, "dim_order"),
    ("flatfly_64", "flatfly", {"k": 4, "n": 2, "c": 4, "x": 4, "y": 4, "xr": 2, "yr": 2}, "ran_min"),
    ("gec_express", "gec",    {"k": 8, "c": 1, "o": 7, "d": 1}, "dor"),
    ("gec_mecs",   "gec",     {"k": 8, "c": 1, "o": 1, "d": 7, "vcs": 8}, "dor"),
]

def _parse_lat(output: str):
    # Prefer honest latency (arrival - trace timestamp). The stock plat
    # mean is ctime-based: qtime slots go stale across idle gaps. Falls
    # back to plat for pre-honest_avg binaries. First phase wins, same as
    # the old plat-only behavior (max_samples>1 prints per phase).
    # Phase 2a: thin wrapper over the shared evaluator parser (identical
    # semantics: honest-first, plat fallback, first-match). Kept because
    # tests import it directly.
    if _shared_parse_latency is not None:
        return _shared_parse_latency(output, prefer_honest=True, use_last_match=False)
    m = re.search(r"\thonest_avg\s*=\s*([0-9.eE+\-]+)", output)
    if m: return float(m.group(1))
    m = re.search(r"Packet latency average\s*=\s*([0-9.]+)", output)
    if m: return float(m.group(1))
    return None

def _lookup(name):
    # Canonical registry first: presets.py is the single source of truth.
    # Falls back to the legacy table for standalone use without install.
    try:
        from veritx_dse.model.presets import lookup_topo
        t = lookup_topo(name)
        if t is not None and t.backend != "anynet":
            params = dict(t.params)
            if t.needs_noc_latency_zero:
                params["use_noc_latency"] = 0
            if t.backend == "gec" and params.get("d", 0) > 0:
                params["num_vcs"] = max(4, params["d"] + 1)
            return (t.name, t.backend, params, t.routing)
    except Exception:
        pass
    for tname, topo, extra, routing in _SWEEP_TOPOS:
        if tname == name or topo == name:
            return (tname, topo, extra, routing)
    p = Path(name)
    if not p.is_absolute(): p = REPO / name
    if p.exists() and p.suffix == ".anynet":
        return (p.stem, "anynet", {"network_file": str(p.resolve())}, "min")
    return None

def _count_anynet(filepath):
    """Thin wrapper over the canonical presets.count_anynet_edges.

    Kept under the local name for backward compat (imported elsewhere).
    Falls back to the legacy inline parser when presets isn't importable.
    """
    try:
        from veritx_dse.model.presets import count_anynet_edges as _cae
        return _cae(filepath)
    except Exception:
        pass
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
    except (OSError, ValueError):
        pass  # unreadable/garbage power report → topology size unknown
    return len(nodes), len(edges)

def _count_packets(trace_path) -> int:
    """Packet count = non-comment, non-blank lines."""
    n = 0
    try:
        with open(trace_path) as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith('#'):
                    n += 1
    except OSError:
        pass  # unreadable → 0 (auto budget falls back to its floor)
    return n


def _file_md5(path) -> str:
    """Streaming md5 for duplicate-trace detection (files can be tens of MB)."""
    h = hashlib.md5()
    try:
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
    except OSError:
        return "unreadable"
    return h.hexdigest()


def _validate_trace(trace_path):
    """Fingerprint a trace: packets, unique/active nodes, max node id.

    Returns a dict recorded into the pareto.json header. The unique-node
    count is a WARNING, not a gate — a genuinely 4-NPU serving trace is a
    legitimate workload — but the active coverage is now written down next
    to every result, so nobody reads a 64-node topology comparison off a
    trace that exercises 4 endpoints (the audit's point #1).
    """
    pkts = 0
    srcs = set(); dsts = set()
    with open(trace_path) as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            pkts += 1
            parts = s.split()
            if len(parts) >= 4:
                try:
                    srcs.add(int(parts[1])); dsts.add(int(parts[3]))
                except ValueError:
                    pass  # malformed line — counted as a packet, not a node
    active = srcs | dsts
    fp = {"path": str(trace_path), "name": Path(trace_path).stem,
          "packets": pkts, "nodes": len(active), "max_node": max(active) if active else -1,
          "srcs": len(srcs), "dsts": len(dsts)}
    if len(active) < 5:
        print(f"  ⚠  Trace {fp['name']}: only {len(active)} unique nodes "
              f"(src={len(srcs)}, dst={len(dsts)}, {pkts} pkts) — results are "
              "about those endpoints, NOT full-fabric topology behavior", flush=True)
    return fp


def _dedupe_traces(trace_paths):
    """Drop byte-identical traces — benchmarking the same file twice under
    two names double-counts it in every average and can fake a Pareto win.
    """
    seen: dict[str, str] = {}
    uniq = []
    for p in trace_paths:
        h = _file_md5(p)
        if h in seen:
            print(f"  ⚠  Duplicate trace: {p.name} is byte-identical to "
                  f"{seen[h]} — skipping (would double-count a workload)", flush=True)
            continue
        seen[h] = p.name
        uniq.append(p)
    return uniq


def _trace_span(trace_path):
    """Max cycle in trace (span).

    Thin wrapper over the shared evaluator span (Phase 2a); kept for
    backward compat. Identical swallow-and-default semantics.
    """
    if _shared_trace_span is not None:
        return _shared_trace_span(trace_path)
    m = 0
    try:
        for line in open(trace_path):
            if line.startswith('#'): continue
            p = line.split()
            if len(p) >= 5:
                c = int(p[0])
                if c > m: m = c
    except (OSError, ValueError):
        pass  # unreadable/garbage trace → span unknown (0)
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
    except (OSError, ValueError):
        pass  # unreadable/garbage trace → single class default
    return 1

def eval_once(trace_path, topo_spec, seed=BOOKSIM_SEED, timeout=None):
    """Evaluate one (trace, topo) pair; return legacy dict + canonical fields.

    Phase 2a: delegates to the shared evaluator with PARETO_PRESET
    (sample_period=max(50000, span+10000), max_samples=5,
    sim_type=latency, honest-first latency key). Signature and legacy keys
    preserved; canonical SynthResult fields (status/backend/provenance/
    extra) merged ADDITIVELY. The pareto.json record boundary therefore
    carries status/error with latency=None on failure (no float sentinel
    was ever used here).
    """
    if evaluate_spec is not None and PARETO_PRESET is not None:
        if timeout is None:
            # Auto budget: scale with the workload so big traces get a fair
            # chance instead of everyone dying at one flat cutoff.
            timeout = auto_timeout(trace_path)
        try:
            (RUNS_DIR / "booksim").mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        try:
            res = evaluate_spec(
                trace_path, topo_spec, seed=seed, timeout=timeout,
                config=PARETO_PRESET, scratch_parent=RUNS_DIR / "booksim",
            )
        except subprocess.TimeoutExpired:
            name0, topo0, _e0, _r0 = topo_spec
            _nn0, _ee0 = _spec_nodes(topo_spec)
            return {"name": name0, "topology": topo0,
                    "trace": str(trace_path), "trace_name": Path(trace_path).stem,
                    "latency": None, "error": "timeout",
                    "nodes": _nn0, "edges": _ee0, "seed": seed,
                    "status": "error", "backend": topo0,
                    "provenance": "multi_workload_pareto+PARETO_PRESET",
                    "extra": {"failure_kind": "timeout"}}
        d = res.to_dict() if hasattr(res, "to_dict") else {}
        # Legacy shape: trace fields + error omitted on success (verbatim).
        out = {
            "name": d.get("name", topo_spec[0]),
            "topology": d.get("topology", topo_spec[1]),
            "trace": str(trace_path),
            "trace_name": Path(trace_path).stem,
            "latency": d.get("latency", None),
            "nodes": d.get("nodes", 0),
            "edges": d.get("edges", 0),
            "seed": seed,
        }
        if d.get("error") is not None:
            out["error"] = d["error"]
            if os.environ.get("VERITX_DEBUG"):
                print(f"    [DEBUG] {out['name']} error={d['error']} "
                      f"status={d.get('status')}", flush=True)
        # Additive canonical fields (do not rename/remove legacy keys).
        out["status"] = d.get("status", "ok")
        out["backend"] = d.get("backend", out["topology"])
        out["provenance"] = d.get("provenance", "multi_workload_pareto+PARETO_PRESET")
        out["extra"] = d.get("extra", {})
        return out
    # Fallback: original inline path (shared evaluator unavailable).
    name, topo, extra, routing = topo_spec
    trace = str(Path(trace_path).resolve())
    _nc = _detect_classes(trace_path)
    span = _trace_span(trace_path)
    # TRUE trace replay (8b19afeb): exact timestamps, full trace.
    # latency_thres must exceed real latency (default 500 aborts) — 1e6.
    # sample window sized so max_samples*period > span + drain.
    sp = max(50000, span + 10000)
    # use_noc_latency lives ONLY on the GEC branch: it forces 1-cycle channels
    # in kncube.cpp, which is correct for GEC taps but understates torus link
    # latency (2c) everywhere else. The canonical builder (simulation/booksim.py)
    # scopes it the same way — keep pareto numbers comparable with compare/.
    replay_common = [f"latency_thres = 1000000.0;", "sim_type = latency;",
                     f"sample_period = {sp};", "max_samples = 5;",
                     "warmup_periods = 1;"]
    # Dimensions from presets.py (single source of truth); the legacy inline
    # table below only runs standalone without an install.
    _size = _canonical_size(name, topo, extra)
    if topo=="anynet":
        nf=extra["network_file"]
        if _size is not None: nodes, edges = _size
        else: nodes,edges=_count_anynet(nf)
        cfg_lines=[f"topology = anynet;",f"routing_function = min;",f"network_file = {nf};",f"traffic = trace({trace});","num_vcs = 4;","vc_buf_size = 8;","packet_size = 8;"] + replay_common + [f"seed = {seed};"]
    elif topo == "gec":
        k=extra.get("k",8); c=extra.get("c",1); o=extra.get("o",7); d=extra.get("d",1)
        vcs = extra.get("vcs", max(4, d))
        if _size is not None: nodes, edges = _size
        else:
            nodes = k*k*c
            # undirected edge count: intra-mesh k*k*2 (if mesh=1) + express row/col
            # full p2p express (d=1): per dim k*C(k,2) links = k*k*(k-1)/2 *2 dims
            if o >= k-1 and d == 1:
                edges = k*k*(k-1)  # row+col complete: 2 * k * C(k,2) = k^2(k-1)
            else:
                # tapped channels: o*d=k-1, per router drives o channels per dim
                edges = nodes * o * 2  # channel taps counted as logical links
        cfg_lines=[f"topology = gec;",f"k = {k};","n = 2;",f"c = {c};",f"o = {o};",f"d = {d};",f"routing_function = {routing};",f"num_vcs = {vcs};","vc_buf_size = 8;","packet_size = 8;",f"traffic = trace({trace});"] + replay_common + ["use_noc_latency = 0;", f"seed = {seed};"]
    else:
        if _size is not None: nodes, edges = _size
        elif topo == "mesh":
            # Canonical mesh: 2*k*(k-1) for 2D (112 for k=8), else
            # n*(k-1)*k^(n-1). Kept here only for standalone use
            # without an install; primary path is _canonical_size above.
            k=extra.get("k",8); n=extra.get("n",2); nodes=k**n; edges=n*(k-1)*k**(n-1) if k>0 else 0
        elif topo == "torus":
            k=extra.get("k",8); n=extra.get("n",2); nodes=k**n; edges=n*k**n
        elif topo=="flatfly":
            k=extra.get("k",4); n=extra.get("n",2); c=extra.get("c",4); nodes=(k**n)*c; edges=nodes//c*(c+(k-1)*n - c)//2
        elif topo=="fly":
            k=extra.get("k",4); n=extra.get("n",3); nodes=k**n; edges=(n-1)*nodes
        elif topo=="cmesh":
            k=extra.get("k",4); n=extra.get("n",2); c=extra.get("c",4); nodes=c*k**n; edges=2*n*k**n
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
            # Debug aid, not user output: gate behind VERITX_DEBUG so normal
            # runs show the SKIP/FAIL line instead of config dumps.
            if os.environ.get("VERITX_DEBUG"):
                print(f"    [DEBUG] {name} exit={r.returncode} stdout={r.stdout[:500].replace(chr(10),'|')} stderr={r.stderr[:200]}", flush=True)
            return {"name":name,"topology":topo,"trace":str(trace_path),"trace_name":Path(trace_path).stem,"latency":None,"error":f"exit {r.returncode}","nodes":nodes,"edges":edges,"seed":seed}
        return {"name":name,"topology":topo,"trace":str(trace_path),"trace_name":Path(trace_path).stem,"latency":lat,"nodes":nodes,"edges":edges,"seed":seed}
    except subprocess.TimeoutExpired:
        return {"name":name,"topology":topo,"trace":str(trace_path),"trace_name":Path(trace_path).stem,"latency":None,"error":"timeout","nodes":nodes,"edges":edges,"seed":seed}
    finally:
        import shutil; shutil.rmtree(workdir, ignore_errors=True)

def _trace_max_node(trace_path):
    """Max node id referenced in src/dst cols — for topo fit checks."""
    m = -1
    try:
        with open(trace_path) as f:
            for line in f:
                if line.startswith('#'): continue
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        m = max(m, int(parts[1]), int(parts[3]))
                    except ValueError:
                        pass
    except OSError:
        pass
    return m


def _canonical_size(name, topo, extra):
    """(nodes, edges) from presets.py — the single source of truth.

    Thin wrapper over :func:`veritx_dse.model.presets.topo_size`:
    Topology-object form when the name resolves in the registry,
    otherwise backend+params-dict form. Returns None when presets isn't
    importable (standalone use); callers then fall back to their legacy
    inline table.
    """
    try:
        from veritx_dse.model.presets import lookup_topo, topo_size
    except Exception:
        return None
    try:
        if topo == "anynet":
            return topo_size(topo, dict(extra))
        t = lookup_topo(name)
        if t is not None and t.backend == topo:
            return topo_size(t)
        return topo_size(topo, dict(extra))
    except Exception:
        return None


def _spec_nodes(spec):
    """(nodes, edges) for a (name, topo, extra, routing) spec; (0, 0) = unknown."""
    name, topo, extra, routing = spec
    size = _canonical_size(name, topo, extra)
    if size is not None:
        return size
    try:
        if topo == "anynet":
            return _count_anynet(extra["network_file"])
        if topo == "gec":
            return extra.get("k", 8) ** 2 * extra.get("c", 1), 0
        if topo == "mesh":
            k, n = extra.get("k", 8), extra.get("n", 2)
            if k > 0:
                return k ** n, n * (k - 1) * k ** (n - 1)
            return k ** n, 0
        if topo == "torus":
            k, n = extra.get("k", 8), extra.get("n", 2)
            return k ** n, n * k ** n
        if topo == "flatfly":
            k, n, c = extra.get("k", 4), extra.get("n", 2), extra.get("c", 4)
            return (k ** n) * c, 0
    except (KeyError, TypeError, ValueError):
        pass
    return 0, 0


_VERDICTS = {"ok": "OK", "timeout": "TIMEOUT", "crash": "CRASH",
             "no_metric": "NO_METRIC", "skipped": "SKIP_INCOMPATIBLE"}


def _classify(r: dict) -> str:
    """One verdict per run — exit status and parse outcome are different
    failures and used to be conflated as FAIL(exit 0).

    Precedence: explicit skip → timeout → crash (exit != 0) → no_metric
    (exit 0 but no parseable latency) → ok.
    """
    if r.get("skipped"):
        return "skipped"
    kind = (r.get("extra") or {}).get("failure_kind")
    if kind == "timeout" or r.get("error") == "timeout":
        return "timeout"
    if r.get("latency") is None:
        rc = (r.get("extra") or {}).get("returncode")
        if rc is None:
            m = re.search(r"exit (-?\d+)", str(r.get("error", "")))
            rc = int(m.group(1)) if m else None
        return "crash" if rc not in (None, 0) else "no_metric"
    return "ok"


def _geomean(vals):
    """Geometric mean of positive floats; None if any is missing."""
    if not vals or any(v is None or v <= 0 for v in vals):
        return None
    return math.exp(sum(math.log(v) for v in vals) / len(vals))


def aggregate(results, topo_names, trace_keys):
    """Pure ranking aggregation for the multi-workload scoreboard.

    The module's deep seam for the audit fixes: classification, per-trace
    normalization, common-successful-set discipline, and the normalized
    geomean — all here, no printing, no IO, so tests and CLI cross the
    same surface.

    Interface:
      results     eval_once-shaped dicts (name, trace_name, latency, …)
      topo_names  display order of topologies (agg rows follow it)
      trace_keys  deduped trace stems
    Returns (agg, meta):
      agg[i]      one record per topology: name, nodes, edges, lat_<trace>
                  (seed-mean), mean_lat (raw arithmetic mean over whatever
                  ran — legacy, kept for pipeline.py tables, NOT a ranking
                  metric), ok (succeeded on every trace), n_common (the
                  common successful trace set), geomean (ranking metric;
                  None unless the topology succeeded on every common trace)
      meta        {"classes": verdict -> ["topo/trace"],
                   "common_ok": set of traces any topology succeeded on,
                   "baseline": trace -> best latency across topologies}

    Why geomean-of-ratios: a raw arithmetic mean lets the biggest-number
    trace dominate the ranking and silently compares different trace
    populations when runs fail. Normalizing per trace (latency / best)
    gives every workload equal influence; the geometric mean of ratios is
    the scale-free mean across workloads. Computing it only over the
    common successful set means every ranked topology is scored on the
    SAME workloads — comparable by construction. A shrunken common set is
    surfaced to the user (main prints it), never silently absorbed.
    """
    classes = defaultdict(list)
    for r in results:
        classes[_classify(r)].append(f"{r['name']}/{r['trace_name']}")

    common_ok = set(trace_keys)
    for tk in trace_keys:
        if not any(r["trace_name"] == tk and r["latency"] is not None
                   for r in results):
            common_ok.discard(tk)
    baseline = {}
    for tk in sorted(common_ok):
        vals = [r["latency"] for r in results
                if r["trace_name"] == tk and r["latency"] is not None]
        baseline[tk] = min(vals)

    by_topo = defaultdict(list)
    for r in results:
        by_topo[r["name"]].append(r)
    agg = []
    for name in topo_names:
        runs = by_topo.get(name, [])
        rec = {"name": name,
               "edges": runs[0].get("edges", 0) if runs else 0,
               "nodes": runs[0].get("nodes", 0) if runs else 0}
        ok = bool(runs)
        for tk in trace_keys:
            vals = [r["latency"] for r in runs
                    if r["trace_name"] == tk and r["latency"] is not None]
            if vals:
                rec[f"lat_{tk}"] = statistics.mean(vals)
            else:
                rec[f"lat_{tk}"] = None
                ok = False
        # Legacy raw mean: population differs per topo when any run failed
        # (kept for pipeline.py tables / diffing; NOT the ranking metric).
        lats = [rec[f"lat_{tk}"] for tk in trace_keys
                if rec[f"lat_{tk}"] is not None]
        rec["mean_lat"] = statistics.mean(lats) if lats else None
        rec["ok"] = ok
        rec["n_common"] = sorted(common_ok)
        if common_ok and all(rec[f"lat_{tk}"] is not None for tk in common_ok):
            rec["geomean"] = _geomean([rec[f"lat_{tk}"] / baseline[tk]
                                       for tk in sorted(common_ok)])
        else:
            rec["geomean"] = None
        agg.append(rec)
    return agg, {"classes": classes, "common_ok": common_ok,
                 "baseline": baseline}


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
    ap.add_argument("--timeout", default=None,
                    help="per-run wall seconds; 'auto' (default) derives a "
                         "per-trace budget from packet count — a flat cutoff "
                         "times out big traces before they finish")
    ap.add_argument("--out", default="runs/booksim/pareto.json")
    args=ap.parse_args()

    traces=[t.strip() for t in args.traces.split(",") if t.strip()]
    topo_names=[t.strip() for t in args.topos.split(",") if t.strip()]
    anynets=[a.strip() for a in args.anynet.split(",") if a.strip()]

    specs=[]
    try:
        from veritx_dse.model.presets import SWEEP_TOPOS as _PRESETS
        _known_topos = ",".join(t.name for t in _PRESETS)
    except Exception:
        _known_topos = ",".join(t[0] for t in _SWEEP_TOPOS)
    for n in topo_names:
        s=_lookup(n)
        if not s:
            print(f"  warn: unknown topo {n} — available: {_known_topos}",
                  file=sys.stderr, flush=True)
            continue
        specs.append(s)
    for af in anynets:
        p=_resolve_input(af)
        if p is None:
            print(f"  warn: anynet not found, skipping: {af}", file=sys.stderr, flush=True)
            continue
        specs.append((p.stem,"anynet",{"network_file":str(p.resolve())},"min"))
    # Dedupe display names (same pooling hazard as veritx compare/): exact
    # duplicates collapse, file-vs-preset same-stem collisions get @anynet.
    _seen_names = {}
    _uniq = []
    for _spec in specs:
        _nm, _tp, _ex, _rt = _spec
        try:
            _key = (_tp, tuple(sorted((k, str(v)) for k, v in _ex.items())), _rt)
        except (AttributeError, TypeError):
            _key = (_tp, _rt)
        if _nm in _seen_names:
            if _seen_names[_nm] == _key:
                print(f"  warn: skipping duplicate topology: {_nm}", flush=True)
                continue
            _n = 2
            _disp = f"{_nm}@anynet"
            while _disp in _seen_names:
                _disp = f"{_nm}@anynet{_n}"
                _n += 1
            print(f"  warn: name collision: '{_nm}' already listed — tracking custom net as '{_disp}'", flush=True)
            _uniq.append((_disp, _tp, _ex, _rt))
            _seen_names[_disp] = _key
        else:
            _seen_names[_nm] = _key
            _uniq.append(_spec)
    specs = _uniq
    if not specs:
        print("  no valid topologies — nothing to compare", file=sys.stderr)
        sys.exit(1)

    trace_paths=[]
    for t in traces:
        p=_resolve_input(t)
        if p is None:
            print(f"  warn: trace not found, skipping: {t}", file=sys.stderr, flush=True)
            continue
        trace_paths.append(p)
    trace_paths=_dedupe_traces(trace_paths)
    if not trace_paths:
        print("  no valid traces — nothing to compare", file=sys.stderr)
        sys.exit(1)

    print(f"Multi-workload Pareto: {len(specs)} topos × {len(trace_paths)} traces × {args.seeds} seeds = {len(specs)*len(trace_paths)*args.seeds} runs", flush=True)
    # Validate traces FIRST: fingerprints drive the coverage warning, the
    # node-fit skip, and the auto timeout budget.
    fingerprints = [_validate_trace(str(tp)) for tp in trace_paths]
    print("Traces: " + ", ".join(
        f"{fp['name']}({fp['packets']}pkts, {fp['nodes']} active nodes)"
        for fp in fingerprints), flush=True)
    print(f"Topos: {', '.join(s[0] for s in specs)}", flush=True)
    # Auto budget preview: flat-cutoff vs per-trace budget is the difference
    # between TIMEOUT meaning 'too slow fabric' and 'too small cutoff'.
    if args.timeout is None or str(args.timeout).strip().lower() == "auto":
        eff_mode = "auto"
        print("Timeout: auto (base "
              f"{TIME_BUDGET_BASE_S}s + {TIME_BUDGET_PER_PKT_S}s/pkt, clamp "
              f"[{TIME_BUDGET_MIN_S},{TIME_BUDGET_MAX_S}]s) → "
              + ", ".join(f"{fp['name']}={auto_timeout(fp['path'])}s"
                          for fp in fingerprints), flush=True)
    else:
        eff_mode = "flat"
        print(f"Timeout: flat {args.timeout}s for every run", flush=True)
    trace_need = {fp["path"]: fp["max_node"] + 1 for fp in fingerprints}
    import time
    # Run
    all_results=[]
    total=len(specs)*len(trace_paths)*args.seeds
    done=0
    t_start=time.time()
    for spec in specs:
        for tp in trace_paths:
            for si in range(args.seeds):
                seed=BOOKSIM_SEED+si
                done+=1
                # A trace addressing nodes the topology doesn't have would run
                # degraded (BookSim skips out-of-range entries) and record junk.
                # Skip up front with the reason instead of burning the run.
                need = trace_need[str(tp)]
                have, have_edges = _spec_nodes(spec)
                if have and need > have:
                    err = f"needs {need} nodes, {spec[0]} has {have}"
                    all_results.append({
                        "name": spec[0], "topology": spec[1],
                        "trace": str(tp), "trace_name": Path(tp).stem,
                        "latency": None, "error": err,
                        "nodes": have, "edges": have_edges, "seed": seed,
                        "skipped": True, "status": "skipped",
                        "extra": {"failure_kind": "skipped_incompatible"},
                    })
                    print(f"[{done}/{total}] SKIP  {spec[0]:<20} {tp.stem:<25} seed={seed:<3} → {err}", flush=True)
                    continue
                eff = args.timeout
                if eff is None or str(eff).strip().lower() == "auto":
                    eff = auto_timeout(str(tp))
                else:
                    eff = int(eff)
                print(f"[{done}/{total}] START {spec[0]:<20} {tp.stem:<25} seed={seed} timeout={eff}s ...", flush=True)
                t0=time.time()
                r=eval_once(str(tp), spec, seed=seed, timeout=eff)
                dt=time.time()-t0
                all_results.append(r)
                verdict = _VERDICTS[_classify(r)]
                lat = f"{r['latency']:.2f}c" if r['latency'] is not None else verdict
                print(f"[{done}/{total}] {verdict:<16} {spec[0]:<20} {tp.stem:<25} seed={seed} → {lat}  ({dt:.1f}s, elapsed {time.time()-t_start:.1f}s)", flush=True)

    # Aggregate per topo per trace (mean over seeds)
    # Build per-topo vector: {name, edges, latency[0], latency[1], ...}
    # Classification audit first: a table mixing OK rows with silent
    # NO_METRIC rows is how scoreboard lies get shipped.
    classes = defaultdict(list)  # class -> ["topo/trace", ...]
    for r in all_results:
        classes[_classify(r)].append(f"{r['name']}/{r['trace_name']}")
    if any(c != "ok" for c in classes):
        print("\n=== Run classification ===")
        for c in ("ok", "timeout", "crash", "no_metric", "skipped"):
            if classes.get(c):
                preview = ", ".join(classes[c][:6])
                more = f" … (+{len(classes[c]) - 6})" if len(classes[c]) > 6 else ""
                print(f"  {_VERDICTS[c]:<18} {len(classes[c]):>3}  {preview}{more}")
        if classes.get("no_metric"):
            print("  ⚠ NO_METRIC = process exited 0 but no latency parsed — "
                  "check the trace/config pair before trusting this table")

    # Ranking math lives in aggregate() — the one seam the tests exercise.
    trace_keys=[p.stem for p in trace_paths]
    agg, agg_meta = aggregate(all_results, [s[0] for s in specs], trace_keys)
    common_ok = agg_meta["common_ok"]
    baseline = agg_meta["baseline"]
    classes = agg_meta["classes"]
    if any(c != "ok" for c in classes):
        print("\n=== Run classification ===")
        for c in ("ok", "timeout", "crash", "no_metric", "skipped"):
            if classes.get(c):
                preview = ", ".join(classes[c][:6])
                more = f" … (+{len(classes[c]) - 6})" if len(classes[c]) > 6 else ""
                print(f"  {_VERDICTS[c]:<18} {len(classes[c]):>3}  {preview}{more}")
        if classes.get("no_metric"):
            print("  ⚠ NO_METRIC = process exited 0 but no latency parsed — "
                  "check the trace/config pair before trusting this table")

    # Pareto on per-trace latencies + edges
    pareto_keys=[f"lat_{tk}" for tk in trace_keys]+["edges"]
    # filter ok only
    ok_agg=[a for a in agg if a["ok"]]
    front, dominated=pareto_front(ok_agg, pareto_keys)

    def _rank(a):
        g = a["geomean"]
        return (g if g is not None else float("inf"), a["edges"])

    print("\n=== Pareto Summary ===")
    hdr=f"  {'Topo':<20} {'Edges':>6} " + " ".join(f"{tk[:12]:>10}" for tk in trace_keys) + f" {'NormGeo':>8} {'RawMean':>9} {'Status':>8}"
    print(hdr)
    print("  "+"─"*len(hdr))
    for a in sorted(agg, key=_rank):
        lats=" ".join(f"{a[f'lat_{tk}']:7.2f}c" if a[f'lat_{tk}'] is not None else "    N/A" for tk in trace_keys)
        g=f"{a['geomean']:.3f}" if a['geomean'] is not None else "N/A"
        mean=f"{a['mean_lat']:.2f}c" if a['mean_lat'] else "N/A"
        status="FRONT" if a in front else "dominated" if a in dominated else "fail"
        print(f"  {a['name']:<20} {a['edges']:>6} {lats} {g:>8} {mean:>9} {status:>8}")
    if common_ok and len(common_ok) < len(trace_keys):
        missing = sorted(set(trace_keys) - common_ok)
        print(f"  ⚠ Ranking/geomean covers {len(common_ok)}/{len(trace_keys)} traces "
              f"(no successful run on: {', '.join(missing)}) — fix or drop "
              "those traces before comparing topologies")

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
    out.write_text(json.dumps({"traces":trace_keys,"topos":[s[0] for s in specs],
                               "trace_fingerprints":fingerprints,
                               "aggregation":{"metric":"geomean of per-trace latency / best-per-trace, over common successful traces",
                                              "common_traces":sorted(common_ok),"baseline":baseline},
                               "results":all_results,"agg":agg,"front":[f["name"] for f in front],"dominated":[d["name"] for d in dominated]}, indent=2))
    print(f"\nSaved: {out}")

if __name__=="__main__":
    main()
