#!/usr/bin/env python3
"""Populates the MECS / Hybrid / Mesh x Traffic / Radix / C matrix into an
xlsx sheet, matching the layout: row labels in column A, three merged
header blocks (Traffic, Radix(d,k-1), C) each with their own sub-columns.

Run from the src/ directory: python3 sweep_gec_matrix.py
Requires the booksim binary already built (plain, no TRACK_STALLS needed).
"""
import re
import subprocess
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
BOOKSIM = SRC_DIR / "booksim"
OUT_XLSX = SRC_DIR.parent / "gec_matrix_study.xlsx"

PACKET_SIZE = 5
VC_BUF_SIZE = 8
INJECTION_RATE = 0.05
TIMEOUT_SEC = 90

TRAFFIC_MAP = {"Uniform": "uniform", "Skewed": "transpose", "Strided": "tornado"}
RADIX_VALUES = [7, 16, 32, 72]           # read as d; k = d + 1
C_VALUES = [1, 4, 6, 8]
BASELINE_D = 7                            # k=8, used for the Traffic and C blocks
BASELINE_C = 1                            # used for the Traffic and Radix blocks
ROWS = ["MECS", "Hybrid", "Mesh"]

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
warmup_periods = 2;
sample_period = 500;
sim_count = 1;
"""

LATENCY_RE = re.compile(r"^Packet latency average = ([\d.]+)", re.MULTILINE)


def topo_params(row, d, c):
    k = d + 1
    if row == "MECS":
        return dict(routing_function="dor", mesh=0, hybrid=0, o=1, d=d, k=k)
    if row == "Hybrid":
        return dict(routing_function="hybrid", mesh=0, hybrid=1, o=1, d=d, k=k)
    if row == "Mesh":
        # mesh=1 requires o=1,d=1 exactly (its own check, separate from
        # the o*d==k-1 rule used by MECS/Hybrid/express). Same k as the
        # MECS/Hybrid cell for a fair same-node-count comparison.
        return dict(routing_function="dor", mesh=1, hybrid=0, o=1, d=1, k=k)
    raise ValueError(row)


MAX_K = 40  # routers = k*k; d=72 -> k=73 -> 5329 routers, which reliably
            # crashes the whole environment mid-build (observed twice,
            # consistent with a broader WSL-instance instability seen
            # elsewhere this session, not a bug in the config itself) --
            # skip rather than retry indefinitely into the same wall.


def run_one(row, d, c, traffic_key):
    params = topo_params(row, d, c)
    if params["k"] > MAX_K:
        return f"N/A (k={params['k']}, {params['k']**2} routers -- too large for this environment)"
    num_vcs = max(2 * d, 2)
    cfg = CONFIG_TEMPLATE.format(
        routing_function=params["routing_function"],
        k=params["k"], c=c, o=params["o"], d=params["d"],
        mesh=params["mesh"], hybrid=params["hybrid"],
        num_vcs=num_vcs, vc_buf_size=VC_BUF_SIZE,
        traffic=TRAFFIC_MAP[traffic_key],
        packet_size=PACKET_SIZE, injection_rate=INJECTION_RATE,
    )
    cfg_path = SRC_DIR / "_sweep_tmp.config"
    cfg_path.write_text(cfg)
    try:
        proc = subprocess.run(
            [str(BOOKSIM), str(cfg_path)],
            cwd=str(SRC_DIR), capture_output=True, text=True, timeout=TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    except Exception as exc:  # noqa: BLE001 -- one bad cell must never kill the sweep
        return f"ERROR({exc.__class__.__name__})"
    out = proc.stdout + proc.stderr
    matches = LATENCY_RE.findall(out)
    if not matches:
        return "ERROR"
    return float(matches[-1])


def main():
    if not BOOKSIM.exists():
        sys.exit(f"booksim binary not found at {BOOKSIM} -- run `make` first")

    def safe_run(row, d, c, tkey):
        try:
            return run_one(row, d, c, tkey)
        except Exception as exc:  # noqa: BLE001 -- one bad cell must never kill the sweep
            return f"ERROR({exc.__class__.__name__})"

    results = {"traffic": {}, "radix": {}, "c": {}}
    for row in ROWS:
        for tkey in TRAFFIC_MAP:
            print(f"[traffic] {row:6s} {tkey:8s} d={BASELINE_D} c={BASELINE_C} ...", end=" ", flush=True)
            val = safe_run(row, BASELINE_D, BASELINE_C, tkey)
            print(val, flush=True)
            results["traffic"][(row, tkey)] = val
        for d in RADIX_VALUES:
            print(f"[radix]   {row:6s} d={d:3d} c={BASELINE_C} traffic=uniform ...", end=" ", flush=True)
            val = safe_run(row, d, BASELINE_C, "Uniform")
            print(val, flush=True)
            results["radix"][(row, d)] = val
        for c in C_VALUES:
            print(f"[c]       {row:6s} d={BASELINE_D} c={c} traffic=uniform ...", end=" ", flush=True)
            val = safe_run(row, BASELINE_D, c, "Uniform")
            print(val, flush=True)
            results["c"][(row, c)] = val

    write_xlsx(results)
    print(f"\nDONE: {OUT_XLSX}")


def write_xlsx(results):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "GEC Matrix"

    bold = Font(bold=True)
    center = Alignment(horizontal="center", vertical="center")

    # Row 1 merged group headers
    ws.merge_cells("B1:D1"); ws["B1"] = "Traffic"
    ws.merge_cells("E1:H1"); ws["E1"] = "Radix (d, k-1)"
    ws.merge_cells("I1:L1"); ws["I1"] = "C"
    for cell in ("B1", "E1", "I1"):
        ws[cell].font = bold
        ws[cell].alignment = center

    # Row 2 sub-headers
    traffic_cols = list(TRAFFIC_MAP.keys())
    for i, tkey in enumerate(traffic_cols):
        ws.cell(row=2, column=2 + i, value=tkey).font = bold
    for i, d in enumerate(RADIX_VALUES):
        ws.cell(row=2, column=5 + i, value=d).font = bold
    for i, c in enumerate(C_VALUES):
        ws.cell(row=2, column=9 + i, value=c).font = bold

    # Rows 3-5: MECS / Hybrid / Mesh
    for r, row in enumerate(ROWS):
        excel_row = 3 + r
        ws.cell(row=excel_row, column=1, value=row).font = bold
        for i, tkey in enumerate(traffic_cols):
            ws.cell(row=excel_row, column=2 + i, value=results["traffic"][(row, tkey)])
        for i, d in enumerate(RADIX_VALUES):
            ws.cell(row=excel_row, column=5 + i, value=results["radix"][(row, d)])
        for i, c in enumerate(C_VALUES):
            ws.cell(row=excel_row, column=9 + i, value=results["c"][(row, c)])

    for col in range(1, 13):
        ws.column_dimensions[get_column_letter(col)].width = 12

    wb.save(OUT_XLSX)


if __name__ == "__main__":
    main()
