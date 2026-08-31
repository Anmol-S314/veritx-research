#!/usr/bin/env python3
"""k=4, d=3, o=1 held fixed (d=k-1 is a hard constraint of pure MECS/
Hybrid at o=1, not an independent variable -- see the "details" block
written into the sheet). Sweeps two genuinely independent things instead:
vc_buf_size and routing_function. Collects latency AND average hop
count. Appends a new sheet to the existing gec_matrix_study.xlsx rather
than overwriting the k-scan sheet already in it.
"""
import re
import subprocess
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
BOOKSIM = SRC_DIR / "booksim"
OUT_XLSX = SRC_DIR.parent / "gec_matrix_study.xlsx"

K = 4
D = 3          # = K - 1, fixed, NOT swept -- see module docstring
O = 1
C = 1
PACKET_SIZE = 5
INJECTION_RATE = 0.05
TRAFFIC = "uniform"
TIMEOUT_SEC = 60

VC_BUF_VALUES = [4, 8, 16, 32]
ROUTING_FUNCTIONS = ["dor", "adaptive_xy_yx", "hybrid"]
NUM_VCS = 2 * D  # =6: satisfies dor's floor (>=d=3), adaptive_xy_yx's and
                 # hybrid's floor (>=2d=6) alike -- same VC budget used
                 # for all three routing functions so the comparison is
                 # fair (no row gets more VCs than another).

CONFIG_TEMPLATE = """\
topology = gec;
routing_function = {routing_function};
k = {k};
c = {c};
o = {o};
d = {d};
mesh = 0;
hybrid = {hybrid_flag};
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


def run_one(routing_function, vc_buf_size):
    # hybrid_gec is registered under routing_function=hybrid and also
    # needs the separate hybrid=1 config flag to build the mesh+MECS
    # layered network; dor/adaptive_xy_yx use the plain MECS build
    # (hybrid=0) and are only distinguished by routing_function itself.
    hybrid_flag = 1 if routing_function == "hybrid" else 0
    cfg = CONFIG_TEMPLATE.format(
        routing_function=routing_function, k=K, c=C, o=O, d=D,
        hybrid_flag=hybrid_flag, num_vcs=NUM_VCS, vc_buf_size=vc_buf_size,
        traffic=TRAFFIC, packet_size=PACKET_SIZE, injection_rate=INJECTION_RATE,
    )
    cfg_path = SRC_DIR / "_sweep_k4_tmp.config"
    cfg_path.write_text(cfg)
    try:
        proc = subprocess.run(
            [str(BOOKSIM), str(cfg_path)],
            cwd=str(SRC_DIR), capture_output=True, text=True, timeout=TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return "TIMEOUT", "TIMEOUT"
    except Exception as exc:  # noqa: BLE001
        return f"ERROR({exc.__class__.__name__})", f"ERROR({exc.__class__.__name__})"
    out = proc.stdout + proc.stderr
    lat_matches = LATENCY_RE.findall(out)
    hop_matches = HOPS_RE.findall(out)
    lat = float(lat_matches[-1]) if lat_matches else "ERROR"
    hops = float(hop_matches[-1]) if hop_matches else "ERROR"
    return lat, hops


def main():
    if not BOOKSIM.exists():
        sys.exit(f"booksim binary not found at {BOOKSIM} -- run `make` first")

    latency = {}
    hops = {}
    for rf in ROUTING_FUNCTIONS:
        for vb in VC_BUF_VALUES:
            print(f"routing={rf:16s} vc_buf_size={vb:3d} ...", end=" ", flush=True)
            lat, hop = run_one(rf, vb)
            print(f"latency={lat} hops={hop}", flush=True)
            latency[(rf, vb)] = lat
            hops[(rf, vb)] = hop

    write_xlsx(latency, hops)
    print(f"\nDONE: {OUT_XLSX}")


def write_xlsx(latency, hops):
    from openpyxl import load_workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    if OUT_XLSX.exists():
        wb = load_workbook(OUT_XLSX)
    else:
        from openpyxl import Workbook
        wb = Workbook()

    sheet_name = "k=4 VCbuf x Routing"
    if sheet_name in wb.sheetnames:
        del wb[sheet_name]
    ws = wb.create_sheet(sheet_name)

    bold = Font(bold=True)
    italic = Font(italic=True, color="555555")
    center = Alignment(horizontal="center", vertical="center")

    # --- Details block ---
    details = [
        "Fixed parameters (not swept):",
        f"  k = {K}   (grid radix, k x k = {K*K} routers)",
        f"  d = {D}   ( = k - 1, a hard constraint of pure MECS/Hybrid at o=1 -- not an independent variable, see below)",
        f"  o = {O}   (one shared MECS express channel per dimension -- 'pure' MECS density)",
        f"  c = {C}   (concentration factor -- terminals = k*k*c = {K*K*C})",
        f"  num_vcs = {NUM_VCS}   ( = 2*d, satisfies dor's floor >=d and adaptive_xy_yx's/hybrid's floor >=2d identically, so all three routing functions get the same VC budget)",
        f"  traffic = {TRAFFIC}, injection_rate = {INJECTION_RATE}, packet_size = {PACKET_SIZE}",
        "",
        "Why d isn't swept here: with o=1 fixed, d = k-1 is forced by GEC's own",
        "config check (o*d must equal k-1) -- it is not an independently tunable",
        "parameter, only a relabeling of k. This sheet instead varies vc_buf_size",
        "(VC queue depth) and routing_function, which ARE independent of k/d/o.",
        "",
        "Routing functions compared:",
        "  dor              -- deterministic dimension-order routing, no congestion awareness, single fixed path per (src,dst).",
        "  adaptive_xy_yx    -- congestion-informed choice of row-first vs column-first, decided once at injection.",
        "  hybrid            -- mesh+MECS hybrid topology; per-hop UGAL-style choice between a mesh step and the MECS express jump, re-evaluated live at every router.",
    ]
    for i, line in enumerate(details, start=1):
        cell = ws.cell(row=i, column=1, value=line)
        if line.startswith("Fixed parameters") or line.startswith("Routing functions"):
            cell.font = bold
        elif line.startswith("Why d"):
            cell.font = italic

    header_row = len(details) + 2

    # --- Latency table ---
    ws.cell(row=header_row, column=1, value="Latency (cycles)").font = bold
    ws.merge_cells(start_row=header_row, start_column=2, end_row=header_row, end_column=1 + len(VC_BUF_VALUES))
    ws.cell(row=header_row, column=2, value="vc_buf_size").font = bold
    ws.cell(row=header_row, column=2).alignment = center
    sub_row = header_row + 1
    ws.cell(row=sub_row, column=1, value="routing_function").font = bold
    for i, vb in enumerate(VC_BUF_VALUES):
        ws.cell(row=sub_row, column=2 + i, value=vb).font = bold
    for r, rf in enumerate(ROUTING_FUNCTIONS):
        row = sub_row + 1 + r
        ws.cell(row=row, column=1, value=rf).font = bold
        for i, vb in enumerate(VC_BUF_VALUES):
            ws.cell(row=row, column=2 + i, value=latency[(rf, vb)])

    # --- Hops table ---
    hops_header_row = sub_row + 1 + len(ROUTING_FUNCTIONS) + 2
    ws.cell(row=hops_header_row, column=1, value="Average hop count").font = bold
    ws.merge_cells(start_row=hops_header_row, start_column=2, end_row=hops_header_row, end_column=1 + len(VC_BUF_VALUES))
    ws.cell(row=hops_header_row, column=2, value="vc_buf_size").font = bold
    ws.cell(row=hops_header_row, column=2).alignment = center
    hops_sub_row = hops_header_row + 1
    ws.cell(row=hops_sub_row, column=1, value="routing_function").font = bold
    for i, vb in enumerate(VC_BUF_VALUES):
        ws.cell(row=hops_sub_row, column=2 + i, value=vb).font = bold
    for r, rf in enumerate(ROUTING_FUNCTIONS):
        row = hops_sub_row + 1 + r
        ws.cell(row=row, column=1, value=rf).font = bold
        for i, vb in enumerate(VC_BUF_VALUES):
            ws.cell(row=row, column=2 + i, value=hops[(rf, vb)])

    ws.column_dimensions["A"].width = 30
    for col in range(2, 2 + len(VC_BUF_VALUES)):
        ws.column_dimensions[get_column_letter(col)].width = 12

    wb.save(OUT_XLSX)


if __name__ == "__main__":
    main()
