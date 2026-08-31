#!/usr/bin/env python3
"""Compares Mesh, MECS, and Hybrid topologies (with each topology's
applicable routing function(s)) across traffic pattern, VC buffer size,
and injection rate. Fixed: k=4, d=3 (=k-1, held constant -- see the
gec_matrix_study.xlsx sheets for why d isn't swept), o=1, c=1, same
num_vcs for every row so the comparison stays fair.

Writes a fresh, long-format workbook: one row per run, not a merged-
header grid -- four independent sweep factors don't fit cleanly into a
2D cross-tab, and a long table is easy to sort/filter/pivot in Excel.
"""
import re
import subprocess
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
BOOKSIM = SRC_DIR / "booksim"
OUT_XLSX = SRC_DIR.parent / "gec_topology_comparison.xlsx"

K = 4
D = 3            # = K - 1, fixed, not swept
O = 1
C = 1
PACKET_SIZE = 5
NUM_VCS = 2 * D  # =6: same budget for every row (dor needs >=d, hybrid/adaptive_xy_yx need >=2d)
TIMEOUT_SEC = 60

# (label, config traffic value) -- transpose/tornado both require a
# power-of-2 node count; k=4,c=1 -> 16 terminals, satisfies that.
TRAFFIC_VALUES = [("uniform", "uniform"), ("skewed", "transpose"), ("strided", "tornado")]
VC_BUF_VALUES = [2, 4, 8, 16]
INJECTION_RATES = [0.05, 0.15, 0.25]

# (topology label, routing_function, mesh flag, hybrid flag)
TOPOLOGIES = [
    ("Mesh", "dor", 1, 0),
    ("MECS", "dor", 0, 0),
    ("MECS", "adaptive_xy_yx", 0, 0),
    ("Hybrid", "hybrid", 0, 1),
]

CONFIG_TEMPLATE = """\
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

LATENCY_RE = re.compile(r"^Packet latency average = ([\d.]+)", re.MULTILINE)
HOPS_RE = re.compile(r"^Hops average = ([\d.]+)", re.MULTILINE)
UNSTABLE_RE = re.compile(r"unstable", re.IGNORECASE)


def run_one(topo_label, routing_function, mesh_flag, hybrid_flag, traffic_cfg, vc_buf_size, injection_rate):
    d = 1 if mesh_flag else D  # mesh=1 requires o=1,d=1 exactly (separate check from o*d==k-1)
    cfg = CONFIG_TEMPLATE.format(
        routing_function=routing_function, k=K, c=C, o=O, d=d,
        mesh=mesh_flag, hybrid=hybrid_flag,
        num_vcs=NUM_VCS, vc_buf_size=vc_buf_size,
        traffic=traffic_cfg, packet_size=PACKET_SIZE, injection_rate=injection_rate,
    )
    cfg_path = SRC_DIR / "_sweep_cmp_tmp.config"
    cfg_path.write_text(cfg)
    try:
        proc = subprocess.run(
            [str(BOOKSIM), str(cfg_path)],
            cwd=str(SRC_DIR), capture_output=True, text=True, timeout=TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return "TIMEOUT", "TIMEOUT", "TIMEOUT"
    except Exception as exc:  # noqa: BLE001
        tag = f"ERROR({exc.__class__.__name__})"
        return tag, tag, tag
    out = proc.stdout + proc.stderr
    lat_matches = LATENCY_RE.findall(out)
    hop_matches = HOPS_RE.findall(out)
    lat = float(lat_matches[-1]) if lat_matches else "ERROR"
    hops = float(hop_matches[-1]) if hop_matches else "ERROR"
    status = "UNSTABLE" if UNSTABLE_RE.search(out) else "stable"
    return lat, hops, status


def main():
    if not BOOKSIM.exists():
        sys.exit(f"booksim binary not found at {BOOKSIM} -- run `make` first")

    rows = []
    total = len(TOPOLOGIES) * len(TRAFFIC_VALUES) * len(VC_BUF_VALUES) * len(INJECTION_RATES)
    n = 0
    for topo_label, rf, mesh_flag, hybrid_flag in TOPOLOGIES:
        for traffic_label, traffic_cfg in TRAFFIC_VALUES:
            for vb in VC_BUF_VALUES:
                for rate in INJECTION_RATES:
                    n += 1
                    print(f"[{n:3d}/{total}] {topo_label:6s} {rf:16s} {traffic_label:8s} "
                          f"vc_buf={vb:3d} rate={rate:.2f} ...", end=" ", flush=True)
                    lat, hops, status = run_one(topo_label, rf, mesh_flag, hybrid_flag,
                                                 traffic_cfg, vb, rate)
                    print(f"lat={lat} hops={hops} [{status}]", flush=True)
                    rows.append((topo_label, rf, traffic_label, vb, rate, lat, hops, status))

    write_xlsx(rows)
    print(f"\nDONE: {OUT_XLSX}")


def write_xlsx(rows):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Topology Comparison"

    bold = Font(bold=True)
    italic = Font(italic=True, color="555555")
    header_fill = PatternFill(start_color="DCE6F1", end_color="DCE6F1", fill_type="solid")

    details = [
        "Fixed parameters (not swept):",
        f"  k = {K}   (4x4 = {K*K} routers)",
        f"  d = {D}   ( = k - 1, held constant -- see gec_matrix_study.xlsx for why this is not an independent sweep variable)",
        f"  o = {O}, c = {C}   (terminals = k*k*c = {K*K*C})",
        f"  num_vcs = {NUM_VCS}   ( = 2*d, identical for every row regardless of routing function, for a fair comparison)",
        f"  packet_size = {PACKET_SIZE}",
        "",
        "Swept: topology/routing, traffic pattern, vc_buf_size, injection_rate.",
        "'skewed' = transpose traffic, 'strided' = tornado traffic (BookSim's fixed-offset permutation pattern).",
        "adaptive_xy_yx is included as a second MECS routing option (congestion-aware row-vs-column choice, decided once at injection) alongside plain dor, to isolate the effect of routing algorithm from the effect of topology.",
        "UNSTABLE rows: BookSim's own convergence guard tripped (average latency exceeded 500 cycles) -- the printed latency/hops are still the last valid measurement, not a crash.",
    ]
    for i, line in enumerate(details, start=1):
        cell = ws.cell(row=i, column=1, value=line)
        if line.startswith("Fixed") or line.startswith("Swept"):
            cell.font = bold
        elif "not a crash" in line or "isolate the effect" in line:
            cell.font = italic

    header_row = len(details) + 2
    headers = ["Topology", "Routing", "Traffic", "VC Buf Size", "Injection Rate",
               "Packet Latency", "Avg Hops", "Status"]
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=header_row, column=i, value=h)
        c.font = bold
        c.fill = header_fill

    for r, row in enumerate(rows, start=header_row + 1):
        topo, rf, traffic, vb, rate, lat, hops, status = row
        ws.cell(row=r, column=1, value=topo)
        ws.cell(row=r, column=2, value=rf)
        ws.cell(row=r, column=3, value=traffic)
        ws.cell(row=r, column=4, value=vb)
        ws.cell(row=r, column=5, value=rate)
        ws.cell(row=r, column=6, value=lat)
        ws.cell(row=r, column=7, value=hops)
        status_cell = ws.cell(row=r, column=8, value=status)
        if status == "UNSTABLE":
            status_cell.font = Font(color="B00000", bold=True)

    last_row = header_row + len(rows)
    ws.auto_filter.ref = f"A{header_row}:H{last_row}"
    ws.freeze_panes = f"A{header_row + 1}"

    widths = [10, 16, 10, 12, 14, 15, 10, 10]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    wb.save(OUT_XLSX)


if __name__ == "__main__":
    main()
