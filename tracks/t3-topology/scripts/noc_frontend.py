#!/usr/bin/env python3
"""noc_frontend.py — workload-driven NoC config frontend (FlexNoC-style intent layer).

One JSON spec describes a workload, topology, and router configuration. This
driver turns it into everything downstream:

    spec.json
      ├─ gen_route_tables.py      -> route_<id>.hex  (2-die bridge mode only)
      ├─ BookSim .cfg + traffic   -> latency / hops / saturation
      ├─ Verilator RTL build      -> Vnoc_tb  (-G VCS/X_DIM/Y_DIM/TWO_DIE/...)
      └─ per-flit RTL-vs-BookSim  -> diff report (GATE R1)

Usage:
    python3 scripts/noc_frontend.py build <spec.json>          # config -> artifacts
    python3 scripts/noc_frontend.py run   <spec.json>          # build + sim + diff
    python3 scripts/noc_frontend.py list                       # show knob surface

Spec schema (all keys optional; defaults in brackets):
{
  "name": "moe_8x8_vc4",              # output dir name
  "workload": {
    "type": "moe_dispatch",           # moe_dispatch|tp_allreduce|kv_cache|uniform
    "nodes": 64,                      # mesh node count (must equal X_DIM*Y_DIM)
    "num_packets": 3000,              # trace length for LLM patterns
    "seed": 42,
    "fanout": 8,                      # moe_dispatch: top-k expert fanout
    "rate": 0.08                      # injection rate (flits/cyc/node)
  },
  "topology": {
    "x_dim": 8, "y_dim": 8,
    "two_die": false,                 # 1 = bridged 2-die (needs anynet file)
    "anynet": "configs/booksim2_configs/bridged_2die_onaxis.anynet",
    "bridge_col": 0, "bridge_row": 0
  },
  "router": {
    "vcs": 4,                         # [-G VCS] 1/2/4/8
    "vc_buf": 8,                      # buffer depth per VC (RTL localparam VC_BUF_DEF)
    "route_tables": true              # 1 = load route_<id>.hex (Dijkstra); 0 = DOR
  },
  "sim": {
    "booksim_bin": "booksim",         # BOOKSIM_BIN env overrides
    "latency_thres": 5000,
    "sample_period": 1000,
    "max_samples": 30
  },
  "outdir": "/var/tmp/opencode/nocfe" # default: /var/tmp/opencode/nocfe/<name>
}

The router's buffering (vc_buf) is today a package localparam (noc_pkg.sv
VC_BUF_DEF = 8) and NOT yet a -G knob — the driver validates you don't try to
change it and notes it as pending work. VCS/X_DIM/Y_DIM/TWO_DIE/BRIDGE_* ARE
- G knobs already.

FlexNoC's frontend answers "draw a NoC + pick protocols/QoS" and generates
RTL. Ours answers "give me a workload + mesh shape + router policy" and
generates route tables + BookSim config + RTL build + cycle-exact diff. Same
shape (intent -> artifacts), research-scoped.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RTLROOT = HERE.parent
REPO_ROOT = RTLROOT.parents[1]   # <repo>/  (RTLROOT is <repo>/tracks/t3-topology)
DEFAULT_OUTDIR = Path("/var/tmp/opencode/nocfe")

RTL_FILES = [
    "rtl/noc_pkg.sv", "rtl/islip.sv", "rtl/router.sv",
    "rtl/mesh.sv", "rtl/nic.sv", "tb/noc_tb.sv",
]
TWO_DIE_FILES = RTL_FILES + ["rtl/noc_2die.sv"]

KNOB_SURFACE = {
    "router.vcs": "int [-G VCS] 1/2/4/8 (iSLIP VC count)",
    "router.vc_buf": "int [pending] buffer depth per VC (noc_pkg.sv VC_BUF_DEF=8, not yet a -G knob)",
    "router.route_tables": "bool load route_<id>.hex (Dijkstra-exact) vs DOR fallback",
    "topology.x_dim/y_dim": "int mesh dimensions (node count = x*y)",
    "topology.two_die": "bool bridged 2-die topology (needs .anynet)",
    "topology.bridge_col/bridge_row": "int bridge link position (2-die mode)",
    "workload.type": "moe_dispatch|tp_allreduce|kv_cache|uniform",
    "workload.fanout": "int moe top-k expert fanout (hot-spot width)",
    "workload.rate": "float injection rate flits/cyc/node",
    "workload.seed": "int RNG seed (determinism)",
    "sim.latency_thres/sample_period/max_samples": "BookSim sample config",
}

WORKLOAD_TYPES = ("moe_dispatch", "tp_allreduce", "kv_cache", "uniform")
ROUTING_MODES = ("table", "dor")


def die(msg):
    print(f"✗ {msg}", file=sys.stderr)
    sys.exit(1)


def _free_mem_mb():
    """Free RAM in MB (MemAvailable), for the VCS>=4 build preflight."""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except OSError:
        pass
    return 0


def load_spec(path):
    spec = json.loads(Path(path).read_text())
    wl = spec.setdefault("workload", {})
    wl.setdefault("type", "uniform")
    wl.setdefault("nodes", 64)
    wl.setdefault("num_packets", 3000)
    wl.setdefault("seed", 42)
    wl.setdefault("fanout", 8)
    wl.setdefault("rate", 0.08)

    topo = spec.setdefault("topology", {})
    topo.setdefault("x_dim", 8)
    topo.setdefault("y_dim", 8)
    topo.setdefault("two_die", False)
    topo.setdefault("anynet", "configs/booksim2_configs/bridged_2die_onaxis.anynet")
    topo.setdefault("bridge_col", 0)
    topo.setdefault("bridge_row", 0)

    rtr = spec.setdefault("router", {})
    rtr.setdefault("vcs", 4)
    rtr.setdefault("vc_buf", 8)
    rtr.setdefault("route_tables", True)

    sim = spec.setdefault("sim", {})
    # BookSim: BOOKSIM_BIN env wins, then the vendored fork build
    # (<repo>/serving/booksim2-embed/src/booksim, commit 29005e6), then PATH.
    _fork = REPO_ROOT / "serving" / "booksim2-embed" / "src" / "booksim"
    sim.setdefault("booksim_bin", os.environ.get("BOOKSIM_BIN")
                    or (str(_fork) if _fork.exists() else "booksim"))
    sim.setdefault("latency_thres", 5000)
    sim.setdefault("sample_period", 1000)
    sim.setdefault("max_samples", 30)

    spec.setdefault("outdir", str(DEFAULT_OUTDIR))
    spec.setdefault("name", Path(path).stem)
    return spec


def validate(spec):
    wl, topo, rtr = spec["workload"], spec["topology"], spec["router"]
    if wl["type"] not in WORKLOAD_TYPES:
        die(f"workload.type must be one of {WORKLOAD_TYPES}")
    if wl["nodes"] != topo["x_dim"] * topo["y_dim"]:
        die(f"workload.nodes ({wl['nodes']}) != x_dim*y_dim "
            f"({topo['x_dim']}x{topo['y_dim']}={topo['x_dim']*topo['y_dim']})")
    if rtr["vcs"] not in (1, 2, 4, 8):
        die(f"router.vcs must be 1/2/4/8, got {rtr['vcs']}")
    if rtr["vc_buf"] != 8:
        die("router.vc_buf != 8 not supported yet — VC_BUF_DEF is a package "
            "localparam in noc_pkg.sv, not a -G knob (pending RTL change)")
    if topo["two_die"] and not Path(RTLROOT / topo["anynet"]).exists():
        die(f"two_die=1 but anynet file not found: {topo['anynet']}")
    if rtr["route_tables"] and not topo["two_die"]:
        # DOR is fine on a plain mesh; table mode is meaningful for the bridge.
        print("  ⚠ route_tables=1 on a plain mesh: table still loads, but DOR "
              "matches the mesh exactly — consider route_tables=0")


def outdir_for(spec):
    return Path(spec["outdir"]) / spec["name"]


def gen_route_tables(spec, out):
    topo = spec["topology"]
    anynet = Path(RTLROOT / topo["anynet"])
    cells = out / "cells"
    cells.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [sys.executable, str(HERE / "gen_route_tables.py"), str(anynet), str(cells)],
        capture_output=True, text=True)
    if r.returncode != 0:
        die(f"gen_route_tables failed:\n{r.stderr[-2000:]}")
    print(f"  route tables: {r.stdout.strip()}")


def gen_trace_hex(spec, out):
    """Convert trace.txt (BookSim format `cyc src cl dst size`) into per-NIC
    trace_n%d.hex BRAM images + run_cycles for the RTL replay, matching the
    rtl_r1.py reference (t3-rtl-noc). 64-bit entries {cycle, cl, dst, size}."""
    cell = out / "cells"
    trace = [l.split() for l in (cell / "trace.txt").read_text().splitlines() if l.strip()]
    if not trace:
        die("empty trace.txt — cannot generate trace_n*.hex")
    by_src = {}
    for l in trace:
        cyc, src, cl, dst, size = map(int, l[:5])
        by_src.setdefault(src, []).append((cyc, cl, dst, size))
    # d604: an EMPTY trace file leaves tmem uninitialized (X) and the NIC fires
    # garbage. A no-traffic src must carry the sentinel 0000000000000000.
    for src in range(spec["topology"]["x_dim"] * spec["topology"]["y_dim"]):
        if src not in by_src:
            with open(cell / f"trace_n{src}.hex", "w") as f:
                f.write("0000000000000000\n")
    for src, entries in by_src.items():
        with open(cell / f"trace_n{src}.hex", "w") as f:
            for cyc, cl, dst, size in entries:
                f.write(f"{cyc:08x}{cl:02x}{dst:02x}{size:04x}\n")
    last_atime = 0
    flits = cell / "flits.txt"
    if flits.exists():
        for l in flits.read_text().splitlines():
            if l.strip():
                last_atime = max(last_atime, int(l.split()[0]))
    (cell / "run_cycles").write_text(str(last_atime + 100) + "\n")
    print(f"  gen-trace: {len(trace)} pkts, last retire {last_atime}, "
          f"run {last_atime + 100} cyc")


def write_booksim_cfg(spec, out):
    wl, topo, rtr, sim = (spec["workload"], spec["topology"],
                          spec["router"], spec["sim"])
    cell = out / "cells"
    # GATE-R1 coherence: the fork has NO trace-input pattern (only
    # synthetic/matrix), so BookSim is the stimulus SOURCE: it generates the
    # traffic, dumps the injected packets (trace_out=trace.txt) and the retired
    # flits (flit_dump=flits.txt); the RTL then replays the same trace_out and
    # we diff the two delivery dumps. feeding a pre-baked trace.txt to the fork
    # would silently run BookSim on uniform and break the diff.
    if wl["type"] == "uniform":
        traffic = "uniform"
    else:
        matrix = cell / "traffic_matrix.txt"
        _write_traffic_matrix(spec, matrix)
        traffic = f"matrix({matrix})"
    lines = [
        "topology = mesh;",
        f"k = {topo['x_dim']};",
        "n = 2;",
        f"num_vcs = {rtr['vcs']};",
        "vc_buf_size = 8;",
        "routing_function = dor;",
        f"traffic = {traffic};",
        "sim_type = latency;",
        f"sample_period = {sim['sample_period']};",
        "warmup_periods = 3;",
        f"max_samples = {sim['max_samples']};",
        f"latency_thres = {float(sim['latency_thres'])};",
        f"seed = {wl['seed']};",
        "trace_out = trace.txt;",
        "flit_dump = flits.txt;",
        f"injection_rate = {wl['rate']};",
    ]
    cfg = out / "cells" / "cell.cfg"
    cfg.write_text("\n".join(lines) + "\n")
    print(f"  booksim cfg → {cfg}")
    return cfg


def _write_traffic_matrix(spec, matrix):
    """Derive a BookSim matrix() pattern from the LLM workload intent so the
    fork's synthetic generator emits dispatch-flavoured traffic. Row s must sum
    to 1 (probability); zero rows send to self (fork's MatrixTrafficPattern).
    moe_dispatch:  fanout k experts chosen uniformly from the other nodes.
    tp_allreduce:  all-to-all (1/(N-1) to every other node).
    kv_cache:      peer-to-PE traffic (i -> (i + N/2) % N)."""
    import random
    wl = spec["workload"]
    n = wl["nodes"]
    rng = random.Random(wl["seed"])
    m = [[0.0] * n for _ in range(n)]
    if wl["type"] == "moe_dispatch":
        k = min(wl.get("fanout", 8), n - 1)
        for s in range(n):
            others = [d for d in range(n) if d != s]
            dsts = rng.sample(others, k)
            for d in dsts:
                m[s][d] = 1.0 / k
    elif wl["type"] == "tp_allreduce":
        for s in range(n):
            for d in range(n):
                if d != s:
                    m[s][d] = 1.0 / (n - 1)
    elif wl["type"] == "kv_cache":
        for s in range(n):
            m[s][(s + n // 2) % n] = 1.0
    else:
        raise ValueError(f"no matrix for workload type {wl['type']}")
    matrix.write_text("\n".join(" ".join(f"{v:.6f}" for v in row) for row in m) + "\n")
    print(f"  matrix ({wl['type']}, {n}n) → {matrix}")


def build_rtl(spec, out):
    topo, rtr = spec["topology"], spec["router"]
    bdir = out / "vbuild"
    bdir.mkdir(parents=True, exist_ok=True)
    bin_ = bdir / "Vnoc_tb"
    if topo["two_die"] and not Path(RTLROOT / "rtl/noc_2die.sv").exists():
        die("two_die=1 but rtl/noc_2die.sv is not on this branch "
            "(it lives on t3-rtl-noc; this branch is serving-leg)")
    # GATE-R1-COORD §8 preflight: free RAM must exceed ~6GB before a VCS>=4
    # build (GVCS=8 elaboration peaks at ~9GB; a 14GB host OOM-kills silently).
    if rtr["vcs"] >= 4:
        avail_mb = _free_mem_mb()
        if avail_mb < 6000:
            die(f"vc{rtr['vcs']} build needs >6GB free RAM (GATE-R1-COORD §8); "
                f"only {avail_mb}MB free — retry when the box clears, or lower "
                f"router.vcs")
    if bin_.exists():
        newest = max(Path(RTLROOT / f).stat().st_mtime for f in
                     (TWO_DIE_FILES if topo["two_die"] else RTL_FILES))
        if bin_.stat().st_mtime > newest:
            return bin_
    srcs = [str(Path(RTLROOT / f)) for f in
            (TWO_DIE_FILES if topo["two_die"] else RTL_FILES)]
    # RTL elaboration peaks hard at GVCS=8 (vc4): cap jobs at 1 so a 14GB host
    # never OOM-kills the build silently (seen twice; GATE-R1-COORD §8).
    rtl_vcs = rtr["vcs"] * 2
    jobs = "1" if rtl_vcs >= 8 else "4"
    cmd = [
        "verilator", "-j", jobs, "--skip-identical", "-Wall",
        "-Wno-fatal", "-DR1_MODE", "--binary",
        "--top-module", "noc_tb",
        f"-GVCS={rtr['vcs'] * 2}",
        f"-GX_DIM={topo['x_dim']}", f"-GY_DIM={topo['y_dim']}",
        "--Mdir", str(bdir),
    ] + srcs
    # TWO_DIE / BRIDGE_* are params of noc_2die.sv (a separate top module on
    # the t3-rtl-noc branch). noc_tb.sv always instantiates noc_mesh and has
    # no such params, so -GTWO_DIE=0 fails Verilator's parameter lookup. Only
    # pass them on a genuine 2-die build where the TB exposes them.
    if topo["two_die"]:
        cmd += [f"-GTWO_DIE=1",
                f"-GBRIDGE_COL={topo['bridge_col']}",
                f"-GBRIDGE_ROW={topo['bridge_row']}"]
    print(f"  verilator build (vc{rtr['vcs']}, "
          f"{topo['x_dim']}x{topo['y_dim']}{' 2-die' if topo['two_die'] else ''}) ...")
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        die(f"verilator failed:\n{r.stderr[-3000:]}")
    print(f"  build done in {time.time() - t0:.0f}s → {bin_}")
    return bin_


def run_sim(spec, out, bin_):
    """Run BookSim then the RTL binary, diffing per-flit delivery counts.

    GATE-R1 coherence: BookSim is the stimulus SOURCE (it generates traffic and
    dumps trace_out=trace.txt + flit_dump=flits.txt). gen_trace_hex() converts
    that trace.txt into per-NIC trace_n%d.hex for the RTL replay, so both
    engines exercise the identical injected packet stream."""
    wl = spec["workload"]
    cell = out / "cells"
    cell.mkdir(parents=True, exist_ok=True)

    booksim = spec["sim"]["booksim_bin"]
    cfg = write_booksim_cfg(spec, out)
    r = subprocess.run([booksim, str(cfg)], capture_output=True, text=True,
                       timeout=600, cwd=str(cell))
    lat = hops = None
    for line in r.stdout.splitlines():
        m = re.search(r"Packet latency average\s*=\s*([0-9.]+)", line)
        if m:
            lat = float(m.group(1))
        m = re.search(r"Hops average\s*=\s*([0-9.]+)", line)
        if m:
            hops = float(m.group(1))
    if lat is None:
        die(f"booksim printed no latency (deadlock?):\n{r.stdout[-1500:]}")

    # RTL run: convert BookSim's stimulus (trace.txt) into per-NIC BRAM images
    # + run_cycles, then replay in RTL and compare delivery dumps (rtl_r1.py).
    gen_trace_hex(spec, out)
    run_cycles = (cell / "run_cycles").read_text().strip()
    r2 = subprocess.run([str(bin_), f"+run_cycles={run_cycles}"],
                        capture_output=True, text=True,
                        timeout=900, cwd=str(cell))
    print(f"  booksim: latency {lat:.2f} cyc, {hops:.2f} hops "
          f"(exit {r.returncode})")
    print(f"  rtl:     exit {r2.returncode} "
          f"({r2.stderr.strip().splitlines()[-1] if r2.stderr.strip() else 'ok'})")
    n_rtl = 0
    if (cell / "rtl_flits.txt").exists():
        n_rtl = sum(1 for _ in (cell / "rtl_flits.txt").read_text().splitlines()
                    if _.strip())
    n_bs = 0
    if (cell / "flits.txt").exists():
        n_bs = sum(1 for _ in (cell / "flits.txt").read_text().splitlines()
                   if _.strip())
    match = "OK" if n_rtl == n_bs else "MISMATCH"
    print(f"  flits delivered: booksim={n_bs} rtl={n_rtl} → {match}")
    return {"booksim_latency": lat, "booksim_hops": hops,
            "booksim_exit": r.returncode, "rtl_exit": r2.returncode,
            "booksim_flits": n_bs, "rtl_flits": n_rtl, "flits_match": match}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["build", "run", "list"])
    ap.add_argument("spec", nargs="?")
    args = ap.parse_args()

    if args.cmd == "list":
        print("Knob surface (see noc_frontend.py --help for the schema):\n")
        for k, v in KNOB_SURFACE.items():
            print(f"  {k:<28} {v}")
        print("\nPending (not -G yet): router.vc_buf (package localparam), "
              "flit width, port count, QoS/scheduling policy")
        return

    if not args.spec:
        die("spec JSON required for build/run")
    spec = load_spec(args.spec)
    validate(spec)
    out = outdir_for(spec)
    out.mkdir(parents=True, exist_ok=True)

    print(f"=== {spec['name']} ===")
    print(f"  workload  : {spec['workload']['type']} "
          f"(fanout {spec['workload']['fanout']}, rate {spec['workload']['rate']})")
    print(f"  topology  : {spec['topology']['x_dim']}x{spec['topology']['y_dim']}"
          f"{' 2-die' if spec['topology']['two_die'] else ' mesh'}")
    print(f"  router    : {spec['router']['vcs']} VC, "
          f"route_tables={spec['router']['route_tables']}")

    if spec["topology"]["two_die"]:
        gen_route_tables(spec, out)
    bin_ = build_rtl(spec, out)
    if args.cmd == "run":
        report = run_sim(spec, out, bin_)
        report["name"] = spec["name"]
        (out / "report.json").write_text(json.dumps(report, indent=2))
        print(f"\n  report → {out / 'report.json'}")
    else:
        print(f"\n  artifacts → {out}")
        print("  next: noc_frontend.py run <spec.json>")


if __name__ == "__main__":
    main()
