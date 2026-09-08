#!/usr/bin/env python3
"""Build one Excel sheet from results_numvcs.csv: MECS-only, num_vcs vs
injection_rate, latency, with the saturation point (first unstable row per
num_vcs group) highlighted."""
import csv
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

SRC = "/home/sowmith/booksim2/results_numvcs.csv"
OUT = "/home/sowmith/booksim2/mecs_vc_study.xlsx"

with open(SRC) as f:
    rows = list(csv.DictReader(f))

wb = Workbook()
ws = wb.active
ws.title = "MECS num_vcs sweep"

headers = ["topology", "k", "o", "d", "num_vcs", "vc_buf_size",
           "injection_rate", "injected_pkt_rate", "accepted_pkt_rate",
           "latency", "unstable", "saturation_point"]
ws.append(headers)
for cell in ws[1]:
    cell.font = Font(bold=True, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor="4472C4")
    cell.alignment = Alignment(horizontal="center")

sat_fill = PatternFill("solid", fgColor="FFC000")  # orange highlight
sat_font = Font(bold=True)

# group rows by num_vcs, in file order, find first unstable=1 row per group
seen_sat = {}
r = 2
saturation_summary = []
prev_numvcs = None
for row in rows:
    numvcs = row["num_vcs"]
    is_first_unstable = (row["unstable"] == "1" and numvcs not in seen_sat)
    if is_first_unstable:
        seen_sat[numvcs] = row["injection_rate"]
        saturation_summary.append((numvcs, row["injection_rate"], row["latency"]))

    ws.append([
        row["topology"], int(row["k"]), int(row["o"]), int(row["d"]),
        int(row["num_vcs"]), int(row["vc_buf_size"]),
        float(row["injection_rate"]), float(row["injected_pkt_rate"]),
        float(row["accepted_pkt_rate"]), float(row["latency"]),
        int(row["unstable"]),
        "<-- SATURATION POINT" if is_first_unstable else "",
    ])
    if is_first_unstable:
        for c in range(1, len(headers) + 1):
            cell = ws.cell(row=r, column=c)
            cell.fill = sat_fill
            cell.font = sat_font
    r += 1

# column widths
widths = [16, 5, 5, 5, 9, 12, 15, 18, 18, 12, 10, 22]
for i, w in enumerate(widths, start=1):
    ws.column_dimensions[get_column_letter(i)].width = w

ws.freeze_panes = "A2"

# summary sheet
ws2 = wb.create_sheet("Saturation summary")
ws2.append(["num_vcs", "saturation_injection_rate", "latency_at_saturation"])
for cell in ws2[1]:
    cell.font = Font(bold=True, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor="4472C4")
for numvcs, rate, lat in saturation_summary:
    ws2.append([int(numvcs), float(rate), float(lat)])
ws2.column_dimensions["A"].width = 10
ws2.column_dimensions["B"].width = 22
ws2.column_dimensions["C"].width = 20

wb.save(OUT)
print("Wrote", OUT)
print("Saturation points:", saturation_summary)
