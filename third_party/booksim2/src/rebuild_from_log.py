#!/usr/bin/env python3
"""Rebuilds the 'Topology Comparison' sheet from the verified, complete
144-line sweep log (captured in the background-task output, confirmed
correct), because the sheet as originally saved by sweep_gec_compare.py
silently lost 9 of 144 rows (135 unique rows present, no duplicates --
root cause not chased down; rebuilding from the trusted log text is more
reliable than debugging the loss after the fact)."""
import re
from pathlib import Path
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

SRC_DIR = Path(__file__).resolve().parent
XLSX = SRC_DIR.parent / "gec_topology_comparison.xlsx"
LOG_PATH = SRC_DIR / "compare_sweep_log.txt"

LINE_RE = re.compile(
    r"^\[\s*\d+/144\]\s+(\S+)\s+(\S+)\s+(\S+)\s+vc_buf=\s*(\d+)\s+rate=([\d.]+)\s+\.\.\.\s+"
    r"lat=(\S+)\s+hops=(\S+)\s+\[(\S+)\]"
)


def parse_log():
    text = LOG_PATH.read_text()
    rows = []
    for line in text.splitlines():
        m = LINE_RE.match(line.strip())
        if not m:
            continue
        topo, rf, traffic, vb, rate, lat, hops, status = m.groups()
        lat_val = float(lat) if re.match(r"^[\d.]+$", lat) else lat
        hops_val = float(hops) if re.match(r"^[\d.]+$", hops) else hops
        rows.append((topo, rf, traffic, int(vb), float(rate), lat_val, hops_val, status))
    return rows


def main():
    rows = parse_log()
    print(f"parsed {len(rows)} rows from log")
    assert len(rows) == 144, f"expected 144, got {len(rows)}"

    wb = load_workbook(XLSX)
    if "Topology Comparison" in wb.sheetnames:
        del wb["Topology Comparison"]
    ws = wb.create_sheet("Topology Comparison")

    bold = Font(bold=True)
    header_fill = PatternFill(start_color="DCE6F1", end_color="DCE6F1", fill_type="solid")

    details = [
        "Fixed parameters (not swept):",
        "  k = 4   (4x4 = 16 routers)",
        "  d = 3   ( = k - 1, held constant -- see gec_matrix_study.xlsx for why this is not an independent sweep variable)",
        "  o = 1, c = 1   (terminals = k*k*c = 16)",
        "  num_vcs = 6   ( = 2*d, identical for every row regardless of routing function, for a fair comparison)",
        "  packet_size = 5",
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
            cell.font = Font(italic=True, color="555555")

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

    # Move it to be the second sheet (after Report, if present)
    wb.move_sheet("Topology Comparison", offset=-(len(wb.sheetnames) - 2) if "Report" in wb.sheetnames else 0)

    wb.save(XLSX)
    print(f"DONE: rewrote {len(rows)} rows into {XLSX}")


if __name__ == "__main__":
    main()
