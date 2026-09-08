#!/usr/bin/env python3
"""MECS (k=4,c=1,o=1,d=3), num_vcs=3 (=d, 1 VC per tap), vc_buf_size swept,
traffic_matrix.txt. Sheet 1: the requested 0.10-0.90 sweep (every row is
already saturated -- the hotspot in traffic_matrix.txt breaks this network
far below 0.10). Sheet 2: a 0.01-0.09 probe that finds where it actually
transitions, with that row highlighted."""
import csv
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

SRC = "/home/sowmith/booksim2/results_vcbuf_matrix.csv"
OUT = "/home/sowmith/booksim2/mecs_vcbuf_matrix_study.xlsx"

with open(SRC) as f:
    rows = list(csv.DictReader(f))

# low-rate threshold probe results (vc_buf_size=8, from find_matrix_threshold.sh)
threshold_data = [
    (0.01, 0.0103438, 0.0103203, 17.4811, 0),
    (0.02, 0.0200521, 0.0201042, 19.8608, 0),
    (0.03, 0.0289107, 0.0289018, 362.224, 1),
    (0.04, 0.0303906, 0.0293281, 374.102, 1),
    (0.05, 0.0300156, 0.029,     520.758, 1),
    (0.06, 0.0289219, 0.0278281, 557.298, 1),
    (0.07, 0.0317187, 0.029625,  322.773, 1),
    (0.08, 0.031375,  0.0288125, 357.749, 1),
    (0.09, 0.0329687, 0.0305,    338.603, 1),
]

wb = Workbook()
ws = wb.active
ws.title = "0.10-0.90 sweep (all saturated)"

headers = ["topology", "k", "o", "d", "num_vcs", "vc_buf_size",
           "injection_rate", "injected_pkt_rate", "accepted_pkt_rate",
           "latency", "unstable"]
ws.append(["NOTE: every row below is unstable=1. traffic_matrix.txt's"
           " destination-0 hotspot saturates this network well below"
           " injection_rate=0.10 -- see the 'Low-rate threshold' sheet"
           " for where it actually breaks."])
ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
ws["A1"].font = Font(bold=True, color="9C0006")
ws["A1"].fill = PatternFill("solid", fgColor="FFC7CE")
ws.append(headers)
for cell in ws[2]:
    cell.font = Font(bold=True, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor="4472C4")
    cell.alignment = Alignment(horizontal="center")

best_per_buf = {}  # vc_buf_size -> (row_idx, latency) of lowest latency seen
r = 3
for row in rows:
    vcbuf = row["vc_buf_size"]
    lat = float(row["latency"])
    if vcbuf not in best_per_buf or lat < best_per_buf[vcbuf][1]:
        best_per_buf[vcbuf] = (r, lat)
    ws.append([
        row["topology"], int(row["k"]), int(row["o"]), int(row["d"]),
        int(row["num_vcs"]), int(row["vc_buf_size"]),
        float(row["injection_rate"]), float(row["injected_pkt_rate"]),
        float(row["accepted_pkt_rate"]), lat, int(row["unstable"]),
    ])
    r += 1

best_fill = PatternFill("solid", fgColor="FFEB9C")
for vcbuf, (row_idx, _) in best_per_buf.items():
    for c in range(1, len(headers) + 1):
        ws.cell(row=row_idx, column=c).fill = best_fill

widths = [16, 5, 5, 5, 9, 12, 15, 18, 18, 12, 10]
for i, w in enumerate(widths, start=1):
    ws.column_dimensions[get_column_letter(i)].width = w
ws.freeze_panes = "A3"

# sheet 2: low-rate threshold
ws2 = wb.create_sheet("Low-rate threshold")
ws2.append(["injection_rate", "injected_pkt_rate", "accepted_pkt_rate",
            "latency", "unstable"])
for cell in ws2[1]:
    cell.font = Font(bold=True, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor="4472C4")

sat_fill = PatternFill("solid", fgColor="FFC000")
prev_stable = True
r2 = 2
for rate, inj, acc, lat, unstable in threshold_data:
    ws2.append([rate, inj, acc, lat, unstable])
    if unstable == 1 and prev_stable:
        for c in range(1, 6):
            ws2.cell(row=r2, column=c).fill = sat_fill
            ws2.cell(row=r2, column=c).font = Font(bold=True)
        prev_stable = False
    r2 += 1

ws2.append([])
ws2.append(["SATURATION THRESHOLD: between injection_rate=0.02 (stable, "
            "latency~20) and 0.03 (unstable, latency jumps to 362).",
            "", "", "", ""])
ws2["A" + str(r2 + 1)].font = Font(bold=True)

for i, w in enumerate([16, 18, 18, 12, 10], start=1):
    ws2.column_dimensions[get_column_letter(i)].width = w

wb.save(OUT)
print("Wrote", OUT)
