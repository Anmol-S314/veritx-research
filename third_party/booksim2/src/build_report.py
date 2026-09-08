#!/usr/bin/env python3
"""Reads the raw long-format data already collected in
gec_topology_comparison.xlsx ("Topology Comparison" sheet) and builds a
presentation-ready "Report" sheet on top of it: clean pivoted summary
tables (stable, apples-to-apples comparison points) plus native Excel
charts. Does not re-run any simulation -- purely a reporting layer over
existing results.
"""
from pathlib import Path
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.chart.label import DataLabelList

SRC_DIR = Path(__file__).resolve().parent
XLSX = SRC_DIR.parent / "gec_topology_comparison.xlsx"

TOPOS = ["Mesh", "MECS (dor)", "MECS (adaptive)", "Hybrid"]
TOPO_KEYS = [("Mesh", "dor"), ("MECS", "dor"), ("MECS", "adaptive_xy_yx"), ("Hybrid", "hybrid")]
TRAFFICS = ["uniform", "skewed", "strided"]
VC_BUFS = [2, 4, 8, 16]
RATES = [0.05, 0.15, 0.25]

BLUE = "1F6F78"
HEADER_FILL = PatternFill(start_color="DCE6F1", end_color="DCE6F1", fill_type="solid")
TITLE_FILL = PatternFill(start_color="1F6F78", end_color="1F6F78", fill_type="solid")
BOLD = Font(bold=True)
TITLE_FONT = Font(bold=True, color="FFFFFF", size=12)
THIN = Side(style="thin", color="C8C8C8")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def load_rows():
    wb = load_workbook(XLSX, data_only=True)
    ws = wb["Topology Comparison"]
    rows = []
    header_row = None
    for r in ws.iter_rows(min_row=1, values_only=False):
        vals = [c.value for c in r]
        if vals and vals[0] == "Topology":
            header_row = r[0].row
            continue
        if header_row is None:
            continue
        if vals[0] is None:
            continue
        rows.append(dict(zip(
            ["Topology", "Routing", "Traffic", "VCBuf", "Rate", "Latency", "Hops", "Status"], vals)))
    return wb, rows


def lookup(rows, topo, routing, traffic, vcbuf, rate):
    for r in rows:
        if (r["Topology"] == topo and r["Routing"] == routing and r["Traffic"] == traffic
                and r["VCBuf"] == vcbuf and r["Rate"] == rate):
            return r
    return None


def write_title(ws, row, col, text, span):
    ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + span - 1)
    c = ws.cell(row=row, column=col, value=text)
    c.font = TITLE_FONT
    c.fill = TITLE_FILL
    c.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[row].height = 22
    return row + 1


def write_table_header(ws, row, col, headers):
    for i, h in enumerate(headers):
        c = ws.cell(row=row, column=col + i, value=h)
        c.font = BOLD
        c.fill = HEADER_FILL
        c.border = BORDER
        c.alignment = Alignment(horizontal="center")
    return row + 1


def main():
    wb, rows = load_rows()
    if "Report" in wb.sheetnames:
        del wb["Report"]
    ws = wb.create_sheet("Report", 0)  # first tab
    ws.sheet_view.showGridLines = False

    row = 1
    row = write_title(ws, row, 1, "GEC Topology Comparison -- Report", 8)
    row += 1
    ws.cell(row=row, column=1, value=(
        "Mesh vs. MECS (dor / adaptive_xy_yx) vs. Hybrid mesh+MECS, on a fixed k=4 (16-terminal) "
        "GEC network. Fixed: d=3 (=k-1), o=1, c=1, num_vcs=6 (identical for every routing function). "
        "Full 144-run raw data is in the 'Topology Comparison' tab."
    )).font = Font(italic=True, color="555555")
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
    ws.row_dimensions[row].height = 30
    ws.cell(row=row, column=1).alignment = Alignment(wrap_text=True, vertical="top")
    row += 2

    # ---------------- Table 1: Latency & Hops by Topology x Traffic (rate=0.05, vc_buf=8) ----------------
    t1_start = row
    row = write_title(ws, row, 1, "1. Latency & average hop count, by topology and traffic (rate=0.05, vc_buf=8)", 8)
    hdr_row = write_table_header(ws, row, 1, ["Topology", "uniform (lat)", "skewed (lat)", "strided (lat)",
                                               "uniform (hops)", "skewed (hops)", "strided (hops)"])
    t1_data_start = hdr_row
    for i, (label, (topo, routing)) in enumerate(zip(TOPOS, TOPO_KEYS)):
        r = hdr_row + i
        ws.cell(row=r, column=1, value=label).font = BOLD
        ws.cell(row=r, column=1).border = BORDER
        for j, traffic in enumerate(TRAFFICS):
            rec = lookup(rows, topo, routing, traffic, 8, 0.05)
            ws.cell(row=r, column=2 + j, value=rec["Latency"] if rec else None).border = BORDER
            ws.cell(row=r, column=5 + j, value=rec["Hops"] if rec else None).border = BORDER
    t1_end = hdr_row + len(TOPOS) - 1
    row = t1_end + 3

    # ---------------- Table 2: Latency by Topology x VC buffer size (rate=0.05, uniform) ----------------
    row = write_title(ws, row, 1, "2. Latency vs. VC buffer size, uniform traffic, rate=0.05", 8)
    hdr_row2 = write_table_header(ws, row, 1, ["Topology"] + [f"vc_buf={v}" for v in VC_BUFS])
    t2_data_start = hdr_row2
    for i, (label, (topo, routing)) in enumerate(zip(TOPOS, TOPO_KEYS)):
        r = hdr_row2 + i
        ws.cell(row=r, column=1, value=label).font = BOLD
        ws.cell(row=r, column=1).border = BORDER
        for j, vb in enumerate(VC_BUFS):
            rec = lookup(rows, topo, routing, "uniform", vb, 0.05)
            ws.cell(row=r, column=2 + j, value=rec["Latency"] if rec else None).border = BORDER
    t2_end = hdr_row2 + len(TOPOS) - 1
    row = t2_end + 3

    # ---------------- Table 3: Latency by Topology x Injection rate (vc_buf=8, skewed) ----------------
    row = write_title(ws, row, 1, "3. Latency vs. injection rate, skewed traffic, vc_buf=8 (saturation behavior)", 8)
    hdr_row3 = write_table_header(ws, row, 1, ["Topology"] + [f"rate={rt}" for rt in RATES])
    t3_data_start = hdr_row3
    for i, (label, (topo, routing)) in enumerate(zip(TOPOS, TOPO_KEYS)):
        r = hdr_row3 + i
        ws.cell(row=r, column=1, value=label).font = BOLD
        ws.cell(row=r, column=1).border = BORDER
        for j, rt in enumerate(RATES):
            rec = lookup(rows, topo, routing, "skewed", 8, rt)
            val = rec["Latency"] if rec else None
            cell = ws.cell(row=r, column=2 + j, value=val)
            cell.border = BORDER
            if rec and rec["Status"] == "UNSTABLE":
                cell.font = Font(color="B00000")
    t3_end = hdr_row3 + len(TOPOS) - 1
    row = t3_end + 3

    ws.column_dimensions["A"].width = 20
    for col in range(2, 9):
        ws.column_dimensions[get_column_letter(col)].width = 14

    # ==================== Charts ====================
    chart_anchor_row = row + 1

    # Chart 1: clustered bar, latency by topology grouped by traffic
    bar1 = BarChart()
    bar1.type = "col"
    bar1.grouping = "clustered"
    bar1.title = "Latency by topology and traffic (rate=0.05, vc_buf=8)"
    bar1.y_axis.title = "Packet latency (cycles)"
    bar1.x_axis.title = "Topology"
    data1 = Reference(ws, min_col=2, max_col=4, min_row=t1_data_start - 1, max_row=t1_end)
    cats1 = Reference(ws, min_col=1, min_row=t1_data_start, max_row=t1_end)
    bar1.add_data(data1, titles_from_data=True)
    bar1.set_categories(cats1)
    bar1.height, bar1.width = 8, 16
    ws.add_chart(bar1, f"A{chart_anchor_row}")

    # Chart 2: clustered bar, avg hops by topology grouped by traffic
    bar2 = BarChart()
    bar2.type = "col"
    bar2.grouping = "clustered"
    bar2.title = "Average hop count by topology and traffic (rate=0.05, vc_buf=8)"
    bar2.y_axis.title = "Average hops"
    bar2.x_axis.title = "Topology"
    data2 = Reference(ws, min_col=5, max_col=7, min_row=t1_data_start - 1, max_row=t1_end)
    bar2.add_data(data2, titles_from_data=True)
    bar2.set_categories(cats1)
    bar2.height, bar2.width = 8, 16
    ws.add_chart(bar2, f"J{chart_anchor_row}")

    chart_anchor_row2 = chart_anchor_row + 17

    # Chart 3: line, latency vs vc_buf_size per topology
    line1 = LineChart()
    line1.title = "Latency vs. VC buffer size (uniform traffic, rate=0.05)"
    line1.y_axis.title = "Packet latency (cycles)"
    line1.x_axis.title = "VC buffer size"
    data3 = Reference(ws, min_col=1, max_col=1 + len(VC_BUFS), min_row=t2_data_start, max_row=t2_end)
    line1.add_data(data3, titles_from_data=True, from_rows=True)
    cats3 = Reference(ws, min_col=2, max_col=1 + len(VC_BUFS), min_row=t2_data_start - 1, max_row=t2_data_start - 1)
    line1.set_categories(cats3)
    for s in line1.series:
        s.smooth = False
        s.marker.symbol = "circle"
    line1.height, line1.width = 8, 16
    ws.add_chart(line1, f"A{chart_anchor_row2}")

    # Chart 4: line, latency vs injection rate per topology (skewed traffic)
    line2 = LineChart()
    line2.title = "Latency vs. injection rate, skewed traffic (vc_buf=8)"
    line2.y_axis.title = "Packet latency (cycles)"
    line2.x_axis.title = "Injection rate"
    data4 = Reference(ws, min_col=1, max_col=1 + len(RATES), min_row=t3_data_start, max_row=t3_end)
    line2.add_data(data4, titles_from_data=True, from_rows=True)
    cats4 = Reference(ws, min_col=2, max_col=1 + len(RATES), min_row=t3_data_start - 1, max_row=t3_data_start - 1)
    line2.set_categories(cats4)
    for s in line2.series:
        s.smooth = False
        s.marker.symbol = "circle"
    line2.height, line2.width = 8, 16
    ws.add_chart(line2, f"J{chart_anchor_row2}")

    wb.save(XLSX)
    print(f"DONE: {XLSX}")


if __name__ == "__main__":
    main()
