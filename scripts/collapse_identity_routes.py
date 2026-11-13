#!/usr/bin/env python3
"""Collapse an identity routing ``case`` into a single comparison.

The emitted GEC fabric routes a flit by calling a pure function that is written
as a 74-entry ``case`` where every entry maps a value to itself:

    function automatic int unsigned route_destination(input logic [W-1:0] flit);
      ...
      case (flit[DEST_LSB +: 7])
        7'd0: route_destination = 0;
        ...
        7'd73: route_destination = 73;
        default: route_destination = K*K;
      endcase
    endfunction

That is ``(sel <= 73) ? sel : K*K``. The fabric calls it 159 times, so the
74-way tree is replicated 159 times and no synthesis tool can elaborate the top
in practical time, while Verilator happily amortizes it.

This script proves the case really is an identity over a contiguous range before
touching it, then rewrites the case block as one ternary. It refuses otherwise,
and it fails if any case remains.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

FUNC_OPEN = re.compile(r"^\s*function\b.*?\b(\w+)\s*\(")
CASE_OPEN = re.compile(r"^(\s*)case\s*\((.*)\)\s*$")
ENTRY = re.compile(r"^\s*7'd(\d+)\s*:\s*(\w+)\s*=\s*(\d+)\s*;\s*$")
DEFAULT = re.compile(r"^(\s*)default\s*:\s*(\w+)\s*=\s*(.+);\s*$")


def collapse(text: str) -> tuple[str, list[dict]]:
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    report: list[dict] = []
    i = 0
    while i < len(lines):
        m_open = FUNC_OPEN.match(lines[i])
        if not m_open:
            out.append(lines[i])
            i += 1
            continue

        name = m_open.group(1)
        j = i + 1
        case_at = None
        end_at = None
        while j < len(lines):
            if lines[j].strip() == "endfunction":
                end_at = j
                break
            if CASE_OPEN.match(lines[j]) and case_at is None:
                case_at = j
            j += 1
        if end_at is None or case_at is None:
            out.append(lines[i])
            i += 1
            continue

        # Parse the case block.
        k = case_at + 1
        entries: list[tuple[int, int]] = []
        default_expr = None
        while k < end_at and lines[k].strip() != "endcase":
            m_e = ENTRY.match(lines[k])
            m_d = DEFAULT.match(lines[k])
            if m_e:
                entries.append((int(m_e.group(1)), int(m_e.group(3))))
            elif m_d:
                default_expr = m_d.group(3).strip()
            elif lines[k].strip():
                raise SystemExit(f"{name}: unexpected line in case body: {lines[k]!r}")
            k += 1
        if k >= end_at or lines[k].strip() != "endcase":
            raise SystemExit(f"{name}: unterminated case")

        identity = all(a == b for a, b in entries)
        contiguous = [a for a, _ in entries] == list(range(len(entries)))
        if not (identity and contiguous and default_expr and len(entries) > 8):
            out.append(lines[i])
            i += 1
            continue

        indent = CASE_OPEN.match(lines[case_at]).group(1)
        selector = CASE_OPEN.match(lines[case_at]).group(2).strip()
        top = len(entries) - 1

        out.append(lines[i])                       # function header
        out.extend(lines[i + 1:case_at])           # locals and any preamble
        out.append(f"{indent}// Identity case collapsed: {len(entries)} entries mapped to "
                   f"themselves, so this is one comparison instead of {len(entries)} branches.\n")
        out.append(f"{indent}{name} = ({selector} <= {top}) ? {selector} : {default_expr};\n")
        out.extend(lines[k + 1:end_at + 1])        # endfunction
        report.append({"function": name, "entries": len(entries), "selector": selector,
                       "default": default_expr, "lines": [case_at + 1, k + 1]})
        i = end_at + 1

    result = "".join(out)
    if re.search(r"^\s*case\s*\(", result, re.MULTILINE):
        remaining = [n for n, l in enumerate(result.splitlines(), 1) if re.match(r"^\s*case\s*\(", l)]
        raise SystemExit(f"case statements remain at lines {remaining[:5]}")
    return result, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("dest", type=Path)
    args = ap.parse_args()
    text = args.source.read_text()
    new, report = collapse(text)
    args.dest.write_text(new)
    print(f"{args.source} -> {args.dest}")
    for r in report:
        print(f"  {r['function']}: {r['entries']} identity entries on {r['selector']} "
              f"(lines {r['lines'][0]}-{r['lines'][1]}) -> one comparison, default {r['default']}")
    print(f"  bytes {len(text)} -> {len(new)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
