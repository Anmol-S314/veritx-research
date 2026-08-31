#!/usr/bin/env python3
"""Full topology comparison report: Mesh, MECS, Hybrid (GEC-based) plus
CMesh, Flatfly, Fat-tree, Dragonfly, and Torus -- every parametrized
topology this BookSim build supports out of the box (anynet/custom4
excluded: they're not self-contained parametrized topologies, they need
an external netlist/are a fixed research design).

Tables 1/3/4 hold node count AND concentration factor constant across
topologies, not just node count: MECS/Hybrid/CMesh/Flatfly all use
k=4,c=4 (64 terminals, 16 real routers, 4-way concentration each), Mesh
uses k=8,c=1 (also 64 terminals, no concentration), matching Grot et
al.'s HPCA'09 MECS paper (Table 2)'s own 64-terminal setup for these
exact topologies. This matters: an earlier version of this report only
matched total terminal count (e.g. Flatfly at k=2,c=4 = 4 routers vs.
MECS at k=4,c=1 = 16 routers, both "16 terminals"), which gave Flatfly
an artificially low hop count that had nothing to do with the topology
being compared, and inverted the paper's actual finding that MECS beats
flattened butterfly on latency. Fat-tree/Torus use their own natural
~64-terminal configs (the paper doesn't cover them, so there's no
concentration scheme to match); Dragonfly's structural floor is 72
terminals (dragonflynew's node count is a*p*(a*p+1) with a=2p at n=1),
so it's the one exception, clearly labeled.

Radix (k) is intentionally NOT swept for the GEC rows -- fixed per the
scheme above for every run. Routing is one fixed function per topology
(not swept). This still isn't a full replication of the paper's
microarchitecture (no bisection-bandwidth-driven packet_size scaling,
no wormhole/1-VC flow control for MECS/Flatfly) -- see the in-sheet
intro note for what's intentionally simplified.
"""
import re
import subprocess
import sys
from pathlib import Path

from matrix_pad import padded_matrix_path

SRC_DIR = Path(__file__).resolve().parent
ROOT_DIR = SRC_DIR.parent
BOOKSIM = SRC_DIR / "booksim"
OUT_XLSX = ROOT_DIR / "full_topology_comparison.xlsx"

K = 4
O = 1
D = 3  # = k-1, fixed (mesh rows force d=1 instead, see run_one)
NUM_VCS = 2 * D  # =6, same for every GEC row (dor needs >=d, hybrid needs >=2d)
PACKET_SIZE = 5          # used only by Table 2's self-contained concentration sweep
TIMEOUT_SEC = 180

# packet_size (flits) for Tables 1/3/4's Mesh/MECS/Hybrid rows: derived from
# Grot et al. HPCA'09 Table 2's 64-terminal channel widths (Mesh=288 bits,
# MECS=288 bits) for a fixed 576-bit reference payload -- 576/288 = 2 flits.
# This is BookSim's flit-cycle equivalent of the paper giving MECS 2x
# Flatfly's per-channel bandwidth to hold bisection bandwidth constant
# despite MECS having half as many physical channels (see CMESH_TEMPLATE /
# FLATFLY_TEMPLATE below for their own values, 576/576=1 and 576/144=4).
# Without this, MECS's fewer-but-narrower-in-aggregate channels are
# bandwidth-starved relative to Flatfly's many dedicated ones, which is
# exactly backwards from what the paper's MECS design intends.
GEC_PACKET_SIZE = 2

DEFAULT_RATE = 0.05        # GEC synthetic-traffic tables (uniform/skewed/strided, c, vc_buf sweeps)
MATRIX_RATE = 0.01         # workload-matrix table -- these matrices hotspot on the DRAM node;
                           # probed directly at each row's own (k,c) below, 0.01 is stable everywhere

# (topology label, routing_function, mesh flag, hybrid flag, k, c) for Tables 1/3/4.
# k/c per row matches Grot et al. HPCA'09 ("Express Cube Topologies for
# On-Chip Interconnects") Table 2's own 64-terminal configuration: Mesh is
# unconcentrated at a wider radix (k=8,c=1), while MECS and Hybrid use the
# same 4-way concentration (k=4,c=4) as CMesh/Flatfly below. Matching
# concentration -- not just terminal count -- matters: an earlier version of
# this report put Mesh/MECS/Hybrid at c=1 while CMesh/Flatfly used c=4 at
# the same 16-terminal total, which meant Flatfly's network had 4 real
# routers to MECS's 16 -- an artificially low hop count that had nothing to
# do with the topology being compared, and inverted the paper's actual
# finding that MECS beats flattened butterfly on latency.
GEC_TOPOLOGIES = [
    ("Mesh", "dor", 1, 0, 8, 1),
    ("MECS", "dor", 0, 0, 4, 4),
    ("Hybrid", "hybrid", 0, 1, 4, 4),
]

TRAFFIC_SWEEP = [("Uniform", "uniform"), ("Skewed", "transpose"), ("Strided", "tornado")]
C_SWEEP = [1, 4, 6, 8]
VCBUF_SWEEP = [4, 8, 16]

GEMM_FILES = ["qkv_proj.txt", "gate_up_proj.txt", "out_proj.txt", "down_proj.txt"]
INJECTION_SWEEP = [
    ("Attention", ["attention.txt"]),
    ("Per Layer", ["full_layer.txt"]),
    ("GEMM", GEMM_FILES),                 # averaged across the 4 GEMM ops
    ("All Model Combined", ["traffic_matrix.txt"]),
]

GEC_CONFIG_TEMPLATE = """\
topology = gec;
routing_function = {routing_function};
k = {k};
c = {c};
o = {o};
d = {d};
mesh = {mesh};
hybrid = {hybrid};
num_vcs = {num_vcs};
vc_buf_size = {vc_buf_size};
wait_for_tail_credit = 0;
vc_allocator = islip;
sw_allocator = islip;
alloc_iters = 1;
routing_delay = 1;
vc_alloc_delay = 1;
sw_alloc_delay = 1;
credit_delay = 1;
st_prepare_delay = 0;
st_final_delay = 1;
input_speedup = 1;
output_speedup = 1;
internal_speedup = 1.0;
hold_switch_for_packet = 0;
buffer_policy = private;
channel_width = 128;
use_noc_latency = 0;
traffic = {traffic};
packet_size = {packet_size};
injection_rate = {injection_rate};
sim_type = latency;
warmup_periods = 3;
sample_period = 1000;
sim_count = 1;
"""

# Each non-GEC topology, sized and driven identically to the GEC rows so
# Tables 1, 3 and 4 are an actual apples-to-apples comparison: 64 terminals
# (matching MECS/Hybrid's k=4,c=4 -- see GEC_TOPOLOGIES comment above),
# num_vcs=6, packet_size=5, and one shared injection_rate per table -- same
# as GEC_CONFIG_TEMPLATE. Only the routing_function (and the topology's own
# required internal geometry knobs -- k/n/c/x/y/xr/yr, allocator, speedup)
# differ, because the routing algorithm is inherent to each topology and is
# exactly the thing being compared. CMesh and Flatfly both use k=4,n=2,c=4
# (16 real routers, 4-way concentration) -- the same concentration factor
# as MECS/Hybrid, matching Grot et al. HPCA'09 Table 2's own 64-terminal
# setup, where CMesh/FBfly/MECS all share identical 4x4x4 concentration and
# only the inter-router wiring differs. Fat-tree (k=4,n=3) and Torus
# (k=8,n=2) use their own natural configs that land on 64 -- the paper
# doesn't evaluate either, so there's no reference concentration scheme to
# match. Dragonfly is the one exception: dragonflynew's node count is
# a*p*(a*p+1) with a=2p at n=1, so its structural minimum is p=2,n=1 -> 72
# terminals; 64 is not achievable for this topology at all.
CMESH_TEMPLATE = """\
topology = cmesh;
k = 4;
n = 2;
c = 4;
xr = 2;
yr = 2;
x = 4;
y = 4;
routing_function = dor_no_express;
traffic = {traffic};
use_read_write = 0;
use_noc_latency = 0;
num_vcs = 6;
vc_buf_size = {vc_buf_size};
packet_size = 1;
injection_rate = {injection_rate};
sim_type = latency;
warmup_periods = 3;
sample_period = 1000;
sim_count = 1;
"""

FLATFLY_TEMPLATE = """\
num_vcs     = 6;
vc_buf_size = {vc_buf_size};
wait_for_tail_credit = 0;
vc_allocator = islip;
sw_allocator = islip;
alloc_iters  = 1;
credit_delay   = 2;
routing_delay  = 0;
vc_alloc_delay = 1;
sw_alloc_delay = 1;
st_final_delay = 1;
input_speedup     = 1;
output_speedup    = 1;
internal_speedup  = 1.0;
warmup_periods = 3;
sample_period  = 1000;
sim_count      = 1;
traffic        = {traffic};
topology = flatfly;
subnets = 1;
c  = 4;
k  = 4;
n  = 2;
x  = 4;
y  = 4;
xr = 2;
yr = 2;
routing_function = xyyx;
use_read_write = 0;
use_noc_latency = 0;
injection_rate = {injection_rate};
sim_type = latency;
packet_size = 4;
"""

FATTREE_TEMPLATE = """\
hold_switch_for_packet=1;
vc_buf_size = {vc_buf_size};
wait_for_tail_credit = 0;
vc_allocator = separable_input_first;
sw_allocator = separable_input_first;
alloc_iters  = 1;
credit_delay   = 2;
routing_delay  = 0;
vc_alloc_delay = 1;
sw_alloc_delay = 1;
st_final_delay = 1;
input_speedup     = 1;
output_speedup    = 1;
internal_speedup  = 1.0;
warmup_periods = 3;
sim_count          = 1;
sample_period  = 1000;
routing_function = nca;
num_vcs     = 6;
priority = none;
traffic       = {traffic};
injection_rate = {injection_rate};
packet_size = 5;
topology = fattree;
k  = 4;
n  = 3;
sim_type = latency;
"""

DRAGONFLY_TEMPLATE = """\
num_vcs     = 6;
vc_buf_size = {vc_buf_size};
wait_for_tail_credit = 0;
vc_allocator = islip;
sw_allocator = islip;
alloc_iters  = 4;
credit_delay   = 2;
routing_delay  = 0;
vc_alloc_delay = 1;
sw_alloc_delay = 1;
st_final_delay = 1;
input_speedup     = 1;
output_speedup    = 1;
internal_speedup  = 1.7;
warmup_periods = 3;
sim_count          = 1;
sample_period  = 1000;
routing_function = min;
priority = none;
traffic       = {traffic};
injection_rate = {injection_rate};
packet_size = 5;
topology = dragonflynew;
k  = 2;
n  = 1;
sim_type = latency;
"""

TORUS_TEMPLATE = """\
topology = torus;
k = 8;
n = 2;
routing_function = dim_order;
num_vcs = 6;
vc_buf_size = {vc_buf_size};
traffic = {traffic};
packet_size = 5;
injection_rate = {injection_rate};
sim_type = latency;
warmup_periods = 3;
sample_period = 1000;
sim_count = 1;
"""

# (label, template, node_count, routing label for the row caption, traffic values to skip)
# Node counts are 64 everywhere except Dragonfly (structural floor of 72,
# see comment above). 64 and 72 aren't both powers of 2 (72 isn't), so
# Dragonfly still can't run bit-permutation traffic (transpose/"Skewed").
# These same templates/sizes are reused for Table 4 (just a different
# injection_rate=MATRIX_RATE) -- all of them are already >=17 terminals.
OTHER_TOPOLOGIES = [
    ("CMesh", CMESH_TEMPLATE, 64, "dor_no_express", set()),
    ("Flatfly", FLATFLY_TEMPLATE, 64, "xyyx", set()),
    ("Fat-tree", FATTREE_TEMPLATE, 64, "nca", set()),
    ("Dragonfly", DRAGONFLY_TEMPLATE, 72, "min", {"transpose"}),
    ("Torus", TORUS_TEMPLATE, 64, "dim_order", set()),
]

ROW_LABELS = {
    "Mesh": "Mesh (dor, k=8,c=1, 64 nodes)",
    "MECS": "MECS (dor, k=4,c=4, 64 nodes)",
    "Hybrid": "Hybrid (hybrid, k=4,c=4, 64 nodes)",
    "CMesh": "CMesh (dor_no_express, k=4,c=4, 64 nodes)",
    "Flatfly": "Flatfly (xyyx, k=4,c=4, 64 nodes)",
    "Fat-tree": "Fat-tree (nca, 64 nodes)",
    "Dragonfly": "Dragonfly (min, 72 nodes -- structural minimum)",
    "Torus": "Torus (dim_order, 64 nodes)",
}
# Table 2 fixes k=4 for ALL THREE rows (including Mesh -- unlike Tables 1/3/4,
# where Mesh instead uses k=8,c=1 to hit 64 terminals). Node count varies with
# c itself in this table (that's the whole point), so it's shown in the note,
# not baked into each row's label the way ROW_LABELS does above.
ROW_LABELS_C_SWEEP = {
    "Mesh": "Mesh (dor, k=4)",
    "MECS": "MECS (dor, k=4)",
    "Hybrid": "Hybrid (hybrid, k=4)",
}
GEC_ORDER = ["Mesh", "MECS", "Hybrid"]
ALL_ORDER = GEC_ORDER + [t[0] for t in OTHER_TOPOLOGIES]

LATENCY_RE = re.compile(r"^Packet latency average = ([\d.eE+-]+)", re.MULTILINE)
HOPS_RE = re.compile(r"^Hops average = ([\d.eE+-]+)", re.MULTILINE)
UNSTABLE_RE = re.compile(r"unstable", re.IGNORECASE)

_run_log = []  # (topo_label, routing, c, vc_buf, traffic_label, rate, lat, hops, status)


def _run_and_parse(cfg_text, cfg_name):
    cfg_path = SRC_DIR / cfg_name
    cfg_path.write_text(cfg_text)
    try:
        proc = subprocess.run(
            [str(BOOKSIM), str(cfg_path)],
            cwd=str(SRC_DIR), capture_output=True, text=True, timeout=TIMEOUT_SEC,
        )
        out = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        out = ""
    lat_m = LATENCY_RE.findall(out)
    hop_m = HOPS_RE.findall(out)
    lat = float(lat_m[-1]) if lat_m else None
    hops = float(hop_m[-1]) if hop_m else None
    unstable = bool(UNSTABLE_RE.search(out))
    status = "UNSTABLE" if unstable else ("ERROR" if lat is None else "stable")
    return lat, hops, status


def run_one(topo_label, routing_function, mesh_flag, hybrid_flag, c, vc_buf_size,
            traffic_cfg, injection_rate, traffic_label="", log=True, k=K, packet_size=PACKET_SIZE):
    d = 1 if mesh_flag else D
    cfg = GEC_CONFIG_TEMPLATE.format(
        routing_function=routing_function, k=k, c=c, o=O, d=d,
        mesh=mesh_flag, hybrid=hybrid_flag,
        num_vcs=NUM_VCS, vc_buf_size=vc_buf_size,
        traffic=traffic_cfg, packet_size=packet_size, injection_rate=injection_rate,
    )
    lat, hops, status = _run_and_parse(cfg, "_full_cmp_tmp.config")
    if log:
        _run_log.append((topo_label, routing_function, f"k={k},c={c}", vc_buf_size, traffic_label,
                          injection_rate, lat, hops, status))
    return lat, hops, status


SAT_LO = 0.01
SAT_HI = 0.5
SAT_ITERS = 10          # resolution = (SAT_HI-SAT_LO)/2**10 = ~0.00048
SAT_MARGIN = 0.9         # Table 3's vc_buf sweep measures near-saturation ON PURPOSE --
                         # that's where buffer depth actually matters (see main()).
SAT_MARGIN_SAFE = 0.5    # Table 2's concentration sweep measures HERE instead. Latency
                         # right before a saturation cliff is famously nonlinear -- e.g.
                         # Mesh at c=8 goes from 34 cycles at 70% of its own sat_rate to
                         # 165 cycles at 95% of it, even though every one of those points
                         # is "stable." Measuring all four c values at a fixed 90% margin
                         # made c=8 look worse than c=6 (66 vs 60) purely because 90%
                         # landed deeper into c=8's steeper knee -- not because c=8's
                         # network is actually worse at a comparable load. 50% sits well
                         # clear of the knee for all four, so the comparison reflects the
                         # topology, not where each curve happens to bend.


def find_saturation(topo_label, routing_function, mesh_flag, hybrid_flag, c, vc_buf_size,
                     traffic_cfg="uniform", traffic_label=""):
    """Binary-searches the maximum injection_rate this exact config sustains
    without going UNSTABLE, then measures latency/hops at SAT_MARGIN of that
    rate (always comfortably stable). Fixes the problem with reporting
    latency at one fixed rate for a concentration/buffer sweep: once a cell
    goes UNSTABLE, the printed latency is just whatever the sample-period
    average happened to be the instant the 500-cycle guard tripped -- not a
    converged measurement, and not meaningfully comparable to other cells
    (it isn't even guaranteed monotonic in the swept parameter). Since
    BookSim's default seed is fixed (0), this search is fully deterministic
    -- rerunning produces the identical saturation rate every time.
    """
    lo, hi = SAT_LO, SAT_HI
    lat0, hops0, status0 = run_one(topo_label, routing_function, mesh_flag, hybrid_flag,
                                    c, vc_buf_size, traffic_cfg, lo,
                                    traffic_label=f"{traffic_label} (sat-probe floor)", log=False)
    if status0 != "stable":
        # Doesn't even sustain the floor rate -- report that fact plainly
        # rather than a fabricated saturation point.
        _run_log.append((topo_label, routing_function, c, vc_buf_size, traffic_label,
                          lo, lat0, hops0, "UNSTABLE (even at floor rate %.3g)" % lo))
        return None, lat0, hops0, "UNSTABLE"

    for _ in range(SAT_ITERS):
        mid = round((lo + hi) / 2, 6)
        _, _, status = run_one(topo_label, routing_function, mesh_flag, hybrid_flag,
                                c, vc_buf_size, traffic_cfg, mid,
                                traffic_label=f"{traffic_label} (sat-probe)", log=False)
        if status == "stable":
            lo = mid
        else:
            hi = mid

    sat_rate = lo
    measure_rate = round(sat_rate * SAT_MARGIN_SAFE, 6)
    lat, hops, status = run_one(topo_label, routing_function, mesh_flag, hybrid_flag,
                                 c, vc_buf_size, traffic_cfg, measure_rate,
                                 traffic_label=f"{traffic_label} @ {SAT_MARGIN_SAFE:.0%} of sat_rate={sat_rate:.4g}")
    return sat_rate, lat, hops, status


def _binary_search_sat_rate(run_fn):
    """run_fn(rate) -> (lat, hops, status). Returns the max injection_rate
    this config sustains without going UNSTABLE (falls back to SAT_LO if
    even that floor is already unstable, rather than crashing)."""
    lo, hi = SAT_LO, SAT_HI
    _, _, status0 = run_fn(lo)
    if status0 != "stable":
        return lo
    for _ in range(SAT_ITERS):
        mid = round((lo + hi) / 2, 6)
        _, _, status = run_fn(mid)
        if status == "stable":
            lo = mid
        else:
            hi = mid
    return lo


def run_matrix(topo_label, routing_function, mesh_flag, hybrid_flag, c, vc_buf_size,
               filenames, injection_rate, traffic_label, k=K, packet_size=PACKET_SIZE):
    """Runs one or more matrix files (averaging results across them, e.g. the
    4 GEMM ops) at a fixed node count, padding each matrix as needed."""
    nodes = k * k * c
    lats, hopss, statuses = [], [], []
    for fname in filenames:
        matrix_path = padded_matrix_path(ROOT_DIR / fname, nodes)
        traffic_cfg = f"matrix({matrix_path})"
        lat, hops, status = run_one(
            topo_label, routing_function, mesh_flag, hybrid_flag, c, vc_buf_size,
            traffic_cfg, injection_rate, traffic_label=f"{traffic_label}:{fname}", k=k,
            packet_size=packet_size,
        )
        lats.append(lat)
        hopss.append(hops)
        statuses.append(status)

    def avg(vals):
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None

    status = "UNSTABLE" if any(s == "UNSTABLE" for s in statuses) else (
        "ERROR" if any(s == "ERROR" for s in statuses) else "stable")
    return avg(lats), avg(hopss), status


def run_other(topo_label, template, skip_traffic, traffic_cfg, vc_buf_size, traffic_label,
              injection_rate=DEFAULT_RATE, log=True):
    if traffic_cfg in skip_traffic:
        if log:
            _run_log.append((topo_label, "-", "-", vc_buf_size, traffic_label, "-", None, None, "SKIPPED"))
        return None, None, "SKIPPED"
    cfg = template.format(traffic=traffic_cfg, vc_buf_size=vc_buf_size, injection_rate=injection_rate)
    lat, hops, status = _run_and_parse(cfg, "_other_tmp.config")
    if log:
        _run_log.append((topo_label, "-", "-", vc_buf_size, traffic_label, injection_rate, lat, hops, status))
    return lat, hops, status


def run_other_matrix(topo_label, template, node_count, filenames, injection_rate, vc_buf_size, traffic_label):
    """Same idea as run_matrix, but for the non-GEC topology templates
    (which take {traffic}/{vc_buf_size}/{injection_rate} placeholders and
    already have their own fixed k/n/c geometry baked in for node_count)."""
    lats, hopss, statuses = [], [], []
    for fname in filenames:
        matrix_path = padded_matrix_path(ROOT_DIR / fname, node_count)
        traffic_cfg = f"matrix({matrix_path})"
        cfg = template.format(traffic=traffic_cfg, vc_buf_size=vc_buf_size, injection_rate=injection_rate)
        lat, hops, status = _run_and_parse(cfg, "_other_matrix_tmp.config")
        _run_log.append((topo_label, "-", "-", vc_buf_size, f"{traffic_label}:{fname}",
                          injection_rate, lat, hops, status))
        lats.append(lat)
        hopss.append(hops)
        statuses.append(status)

    def avg(vals):
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None

    status = "UNSTABLE" if any(s == "UNSTABLE" for s in statuses) else (
        "ERROR" if any(s == "ERROR" for s in statuses) else "stable")
    return avg(lats), avg(hopss), status


def main():
    if not BOOKSIM.exists():
        sys.exit(f"booksim binary not found at {BOOKSIM} -- run `make` first")

    results = {"traffic": {}, "c": {}, "vcbuf": {}, "injection": {}}
    total = (len(ALL_ORDER) * len(TRAFFIC_SWEEP) + len(GEC_TOPOLOGIES) * len(C_SWEEP)
              + len(ALL_ORDER) * len(VCBUF_SWEEP)
              + len(ALL_ORDER) * len(INJECTION_SWEEP))
    n = 0

    for topo_label, rf, mesh_flag, hybrid_flag, topo_k, topo_c in GEC_TOPOLOGIES:
        results["traffic"][topo_label] = {}
        for label, traffic_cfg in TRAFFIC_SWEEP:
            n += 1
            print(f"[{n:3d}/{total}] traffic  {topo_label:8s} {label:8s} ...", end=" ", flush=True)
            r = run_one(topo_label, rf, mesh_flag, hybrid_flag, topo_c, 8, traffic_cfg, DEFAULT_RATE,
                        traffic_label=label, k=topo_k, packet_size=GEC_PACKET_SIZE)
            print(r, flush=True)
            results["traffic"][topo_label][label] = r

        # Concentration sweep is its own self-contained study (varies c at a
        # fixed k=K for all three GEC rows) -- deliberately NOT topo_k/topo_c.
        results["c"][topo_label] = {}
        for c in C_SWEEP:
            n += 1
            print(f"[{n:3d}/{total}] c-sweep  {topo_label:8s} c={c} (saturation search) ...",
                  end=" ", flush=True)
            r = find_saturation(topo_label, rf, mesh_flag, hybrid_flag, c, 8,
                                 traffic_label=f"c={c}")
            print(r, flush=True)
            results["c"][topo_label][c] = r

        # VC buffer size only matters when the network is near capacity --
        # at a flat low rate with each row's own (possibly tiny) paper-matched
        # packet_size, most rows never queue deep enough for buffer depth to
        # matter at all (Mesh/CMesh came out bit-identical across vb=4/8/16
        # before this fix). So: find this row's own saturation rate at a
        # reference vc_buf_size=8, then sweep vc_buf_size at 90% of that --
        # a load where buffering actually has something to absorb.
        vcbuf_sat = _binary_search_sat_rate(
            lambda rate: run_one(topo_label, rf, mesh_flag, hybrid_flag, topo_c, 8, "uniform",
                                  rate, log=False, k=topo_k, packet_size=GEC_PACKET_SIZE))
        vcbuf_rate = round(vcbuf_sat * SAT_MARGIN, 6)
        results["vcbuf"][topo_label] = {}
        for vb in VCBUF_SWEEP:
            n += 1
            print(f"[{n:3d}/{total}] vcbuf    {topo_label:8s} vb={vb} (@ 90% of sat={vcbuf_sat:.4g}) ...",
                  end=" ", flush=True)
            r = run_one(topo_label, rf, mesh_flag, hybrid_flag, topo_c, vb, "uniform", vcbuf_rate,
                        traffic_label=f"vc_buf={vb} @ 90% sat(vcbuf8)={vcbuf_sat:.4g}",
                        k=topo_k, packet_size=GEC_PACKET_SIZE)
            print(r, flush=True)
            results["vcbuf"][topo_label][vb] = r

        results["injection"][topo_label] = {}
        for label, filenames in INJECTION_SWEEP:
            n += 1
            print(f"[{n:3d}/{total}] injection {topo_label:8s} {label:20s} ...", end=" ", flush=True)
            r = run_matrix(topo_label, rf, mesh_flag, hybrid_flag, topo_c, 8, filenames,
                            MATRIX_RATE, label, k=topo_k, packet_size=GEC_PACKET_SIZE)
            print(r, flush=True)
            results["injection"][topo_label][label] = r

    for topo_label, template, nodes, routing, skip_traffic in OTHER_TOPOLOGIES:
        results["traffic"][topo_label] = {}
        for label, traffic_cfg in TRAFFIC_SWEEP:
            n += 1
            print(f"[{n:3d}/{total}] traffic  {topo_label:8s} {label:8s} ...", end=" ", flush=True)
            r = run_other(topo_label, template, skip_traffic, traffic_cfg, 8, label)
            print(r, flush=True)
            results["traffic"][topo_label][label] = r

        vcbuf_sat = _binary_search_sat_rate(
            lambda rate: run_other(topo_label, template, skip_traffic, "uniform", 8,
                                    "sat-probe", injection_rate=rate, log=False))
        vcbuf_rate = round(vcbuf_sat * SAT_MARGIN, 6)
        results["vcbuf"][topo_label] = {}
        for vb in VCBUF_SWEEP:
            n += 1
            print(f"[{n:3d}/{total}] vcbuf    {topo_label:8s} vb={vb} (@ 90% of sat={vcbuf_sat:.4g}) ...",
                  end=" ", flush=True)
            r = run_other(topo_label, template, skip_traffic, "uniform", vb,
                          f"vc_buf={vb} @ 90% sat(vcbuf8)={vcbuf_sat:.4g}", injection_rate=vcbuf_rate)
            print(r, flush=True)
            results["vcbuf"][topo_label][vb] = r

    for topo_label, template, nodes, routing, skip_traffic in OTHER_TOPOLOGIES:
        results["injection"][topo_label] = {}
        for label, filenames in INJECTION_SWEEP:
            n += 1
            print(f"[{n:3d}/{total}] injection {topo_label:8s} {label:20s} ...", end=" ", flush=True)
            r = run_other_matrix(topo_label, template, nodes, filenames, MATRIX_RATE, 8, label)
            print(r, flush=True)
            results["injection"][topo_label][label] = r

    write_xlsx(results)
    print(f"\nDONE: {OUT_XLSX}")


def write_xlsx(results):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter

    METRICS = ["Latency", "Hops"]

    HEADER_FILL = PatternFill("solid", fgColor="DCE6F1")
    TITLE_FILL = PatternFill("solid", fgColor="1F6F78")
    BOLD = Font(bold=True)
    TITLE_FONT = Font(bold=True, color="FFFFFF", size=12)
    THIN = Side(style="thin", color="C8C8C8")
    BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
    UNSTABLE_FONT = Font(color="B00000", bold=True)
    SKIPPED_FONT = Font(italic=True, color="888888")

    wb = Workbook()
    ws = wb.active
    ws.title = "Report"
    ws.sheet_view.showGridLines = False

    def write_title(row, text, span):
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
        c = ws.cell(row=row, column=1, value=text)
        c.font = TITLE_FONT
        c.fill = TITLE_FILL
        ws.row_dimensions[row].height = 22
        return row + 1

    def write_table(row, title, param_labels, data, row_order, note="", metrics=METRICS, row_labels=None):
        row_labels = row_labels or ROW_LABELS
        n_metrics = len(metrics)
        span = 1 + n_metrics * len(param_labels)
        row = write_title(row, title, span)
        if note:
            ws.cell(row=row, column=1, value=note).font = Font(italic=True, color="555555")
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
            row += 1
        hdr1 = row
        ws.cell(row=hdr1, column=1, value="Topology").font = BOLD
        ws.merge_cells(start_row=hdr1, start_column=1, end_row=hdr1 + 1, end_column=1)
        col = 2
        for plabel in param_labels:
            ws.merge_cells(start_row=hdr1, start_column=col, end_row=hdr1, end_column=col + n_metrics - 1)
            c = ws.cell(row=hdr1, column=col, value=str(plabel))
            c.font = BOLD
            c.fill = HEADER_FILL
            c.alignment = Alignment(horizontal="center")
            for j, m in enumerate(metrics):
                mc = ws.cell(row=hdr1 + 1, column=col + j, value=m)
                mc.font = BOLD
                mc.fill = HEADER_FILL
                mc.alignment = Alignment(horizontal="center")
            col += n_metrics
        data_start = hdr1 + 2
        for i, topo_label in enumerate(row_order):
            r = data_start + i
            ws.cell(row=r, column=1, value=row_labels[topo_label]).font = BOLD
            ws.cell(row=r, column=1).border = BORDER
            col = 2
            for plabel in param_labels:
                *vals, status = data[topo_label][plabel]
                for j, val in enumerate(vals):
                    cell = ws.cell(row=r, column=col + j,
                                    value=round(val, 4) if val is not None else "N/A")
                    cell.border = BORDER
                    if status == "UNSTABLE":
                        cell.font = UNSTABLE_FONT
                    elif status == "SKIPPED":
                        cell.font = SKIPPED_FONT
                col += n_metrics
        data_end = data_start + len(row_order) - 1
        return data_end + 3, data_start, data_end, span

    row = 1
    row = write_title(row, "Full Topology Comparison Report -- Mesh, MECS, Hybrid, "
                            "CMesh, Flatfly, Fat-tree, Dragonfly, Torus", 9)
    row += 1
    intro = (
        "Tables 1, 3 and 4 (all 8 topologies) run at 64 terminals for every topology except "
        f"Dragonfly (see below), num_vcs={NUM_VCS}. Tables 1 and 4 use one shared injection_rate "
        "per table for every cell; Table 3 (VC buffer size) instead runs each row at 90% of its "
        "own saturation rate (found at a reference vc_buf_size=8) -- a flat shared rate meant most "
        "rows never queued deep enough for buffer depth to matter at all. Concentration is matched "
        "too, not just terminal count: MECS, Hybrid, "
        "CMesh and Flatfly all use k=4,c=4 (16 real routers, 4-way concentration each) -- the same "
        "setup Grot et al.'s HPCA'09 MECS paper (Table 2) uses for its own 64-terminal comparison "
        "of these exact topologies. Mesh is unconcentrated at a wider radix (k=8,c=1, also 64 "
        "terminals), matching that paper's Mesh row. Fat-tree (k=4,n=3) and Torus (k=8,n=2) use "
        "their own natural configs that land on 64 -- the paper doesn't evaluate either, so there's "
        "no reference concentration scheme to match, and they keep packet_size=5. "
        "packet_size (flits) is now DELIBERATELY not uniform for Mesh/MECS/Hybrid/CMesh/Flatfly: "
        "Mesh/MECS/Hybrid=2, CMesh=1, Flatfly=4, derived from the paper's Table 2 channel widths at "
        "64 terminals (288/576/144 bits) for a fixed 576-bit reference payload. This is BookSim's "
        "flit-cycle equivalent of the paper's real mechanism -- MECS has fewer, wider 'multidrop' "
        "channels than Flatfly's many dedicated point-to-point ones, so the paper gives MECS 2x the "
        "per-channel bandwidth to keep total bisection bandwidth equal; without that, MECS's channel "
        "count disadvantage makes it look worse than Flatfly for a reason that has nothing to do "
        "with the topology being compared. Only the routing_function otherwise differs across "
        "GEC/CMesh/Flatfly/Fat-tree/Torus (Mesh=dor, MECS=dor, Hybrid=hybrid, CMesh=dor_no_express, "
        "Flatfly=xyyx, Fat-tree=nca, Torus=dim_order) plus each topology's own required internal "
        "geometry knobs (k/n/c/x/y/xr/yr) -- routing algorithm plus this bandwidth-equalizing "
        "packet_size are the two things this comparison is now isolating on. Dragonfly is the sole "
        "size exception: dragonflynew's terminal count is a*p*(a*p+1) with a=2p at n=1, so its "
        "structural minimum is p=2,n=1 = 72 terminals; 64 is not reachable for this topology at all, "
        "and it keeps packet_size=5 (the paper doesn't cover it either). Concentration (Table 2) "
        "stays GEC-only (Mesh/MECS/Hybrid, packet_size=5) since it deliberately sweeps c itself at "
        "a fixed k=4 -- a separate, self-contained study, unrelated to the concentration/bandwidth "
        "matching in Tables 1/3/4. UNSTABLE cells (red) mean BookSim's convergence guard tripped -- "
        "the printed latency is the last valid measurement, not a crash. Grey italic 'N/A' = "
        "skipped: BookSim requires a power-of-2 node count for bit-permutation traffic "
        "(transpose/'Skewed'); 64 satisfies that for every Table 1/3 topology except Dragonfly, "
        "whose 72 = 8*9 doesn't, so that one cell is skipped rather than crashed. This is still not "
        "a full replication of the paper's microarchitecture -- MECS/Flatfly are wormhole (1 VC/port) "
        "in the paper vs. this report's uniform num_vcs=6/islip allocation everywhere -- but it now "
        "isolates the two variables (topology/routing and the bandwidth split the paper's own design "
        "depends on) that its actual 64-terminal MECS-vs-CMesh-vs-Flatfly result comes from."
    )
    ws.cell(row=row, column=1, value=intro).alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
    ws.row_dimensions[row].height = 220
    row += 2

    # Table 1: Traffic pattern sweep -- all 8 topologies
    labels1 = [l for l, _ in TRAFFIC_SWEEP]
    row, *_ = write_table(
        row, "1. Traffic pattern (64 terminals except Dragonfly=72, num_vcs=6, vc_buf_size=8, "
             "injection_rate=%.2f identical for every topology; packet_size per row -- see intro)"
             % DEFAULT_RATE,
        labels1, results["traffic"], ALL_ORDER,
        note="'Skewed' = transpose traffic, 'Strided' = tornado traffic (BookSim's fixed-offset permutation pattern).")

    # Table 2: Concentration (c) sweep -- GEC only, k=4 for all three rows
    # (including Mesh -- unlike Tables 1/3/4, where Mesh uses k=8,c=1 instead).
    # Sat. Rate is the authoritative comparison here: max sustained
    # injection_rate found by binary search, monotonically decreasing in c as
    # expected (more terminals sharing a router = less headroom per node).
    # Latency/Hops are measured at 50% of that rate, not 90% -- latency right
    # before a saturation cliff is highly nonlinear (e.g. Mesh c=8 goes from
    # 34 cycles at 70% of its own sat_rate to 165 cycles at 95%), so a fixed
    # 90% margin made c=8 look worse than c=6 purely because 90% landed
    # deeper into c=8's steeper knee, not because its network is actually
    # worse at a comparable load. 50% sits clear of the knee for all four c
    # values, so Latency/Hops reflect the topology, not knee-position noise.
    labels2 = C_SWEEP
    row, *_ = write_table(
        row, "2. Concentration c -- GEC topologies only, fixed k=4 (uniform traffic, vc_buf_size=8)",
        labels2, results["c"], GEC_ORDER, metrics=["Sat. Rate", "Latency", "Hops"],
        row_labels=ROW_LABELS_C_SWEEP,
        note=f"Terminals per topology = k*k*c = {K}*{K}*c. Sat. Rate = max sustained injection_rate "
             "found by binary search (10 iterations, resolution ~0.0005) -- the reliable, monotonic "
             "comparison. Latency/Hops are measured at 50% of that rate (not 90% -- see code comment "
             "on SAT_MARGIN_SAFE): near a saturation cliff, latency is highly nonlinear, so a fixed "
             "90% margin can make a steeper-kneed config look worse at a load that isn't actually "
             "comparable across different c values. 50% is a converged, stable measurement well clear "
             "of that knee for every c.")

    # Table 3: VC buffer size sweep -- all 8 topologies, each at 90% of its OWN
    # saturation rate (found at a reference vc_buf_size=8), not one shared flat
    # rate. A flat low rate meant most rows never queued deep enough for
    # buffer depth to matter (Mesh/CMesh came out bit-identical across
    # vb=4/8/16); this makes every row's buffer sweep happen under real
    # near-capacity contention instead.
    labels3 = VCBUF_SWEEP
    row, *_ = write_table(
        row, "3. VC buffer size (uniform traffic, 64 terminals except Dragonfly=72, num_vcs=6, "
             "each row at 90% of its own saturation rate found at vc_buf_size=8 -- see All Runs "
             "sheet for each row's exact rate)",
        labels3, results["vcbuf"], ALL_ORDER)

    # Table 4: Injection / workload matrix sweep -- all 8 topologies, reusing the exact
    # same per-topology (k,c) configs as Tables 1/3 (all already >=17 terminals, so the
    # 17-node LLM matrices just get padded up to each row's 64 or 72).
    labels4 = [l for l, _ in INJECTION_SWEEP]
    row, *_ = write_table(
        row, "4. Injection pattern -- LLM workload matrices, all 8 topologies, same sizing as "
             "Tables 1/3 (vc_buf_size=8, injection_rate=%.2f -- identical for every topology)" % MATRIX_RATE,
        labels4, results["injection"], ALL_ORDER,
        note="Attention=attention.txt, Per Layer=full_layer.txt, GEMM=average of qkv/gate_up/out/down "
             "proj matrices, All Model Combined=traffic_matrix.txt. Each 17-node matrix (16 compute + "
             "1 DRAM node) is zero-padded up to that row's terminal count (64, or 72 for Dragonfly); "
             "padding nodes stay idle.")

    ws.column_dimensions["A"].width = 30
    for col in range(2, 10):
        ws.column_dimensions[get_column_letter(col)].width = 12

    # Raw runs sheet
    ws2 = wb.create_sheet("All Runs")
    headers = ["Topology", "Routing", "k,c", "VC Buf Size", "Traffic/Injection",
               "Injection Rate", "Latency", "Hops", "Status"]
    for i, h in enumerate(headers, start=1):
        cell = ws2.cell(row=1, column=i, value=h)
        cell.font = BOLD
        cell.fill = HEADER_FILL
    for r, row_data in enumerate(_run_log, start=2):
        for i, val in enumerate(row_data, start=1):
            cell = ws2.cell(row=r, column=i, value=val)
            if row_data[-1] == "UNSTABLE":
                cell.font = UNSTABLE_FONT
            elif row_data[-1] == "SKIPPED":
                cell.font = SKIPPED_FONT
    ws2.auto_filter.ref = f"A1:I{len(_run_log) + 1}"
    ws2.freeze_panes = "A2"
    widths2 = [10, 20, 5, 12, 22, 14, 12, 10, 10]
    for i, w in enumerate(widths2, start=1):
        ws2.column_dimensions[get_column_letter(i)].width = w

    wb.save(OUT_XLSX)


if __name__ == "__main__":
    main()
