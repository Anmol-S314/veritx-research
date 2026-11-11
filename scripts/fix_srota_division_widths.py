#!/usr/bin/env python3
"""Make diagnosed unsigned Verilog division zero-extension explicit.

Never edits the pinned input. The resulting source and a hash-bound change list
are written to a fresh output directory and must be linted and simulated anew.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


DIAGNOSTIC = re.compile(
    r"^%Warning-WIDTHEXPAND: (.+):(\d+):(\d+): Operator DIV expects (\d+) bits on the RHS, "
    r"but RHS's (CONST|VARREF) '([^']+(?:'[^']+)?)' generates (\d+) bits\.$"
)
DIVISION = re.compile(r" / ([A-Za-z_][A-Za-z_0-9]*|\d+'[hbd][0-9a-fA-F_]+);(\s*(?://[^\n]*)?)$")


def fix_divisors(source, diagnostics, source_path):
    lines = source.splitlines(keepends=True)
    changes = []
    seen = set()
    unsigned_inputs = {(name, int(high) + 1) for high, name in re.findall(
        r'\b(?:input|wire)\s+\[(\d+):0\]\s+([A-Za-z_][A-Za-z_0-9]*)\b', source)}
    for diagnostic in diagnostics.splitlines():
        if not diagnostic.startswith('%Warning-'):
            continue
        match = DIAGNOSTIC.fullmatch(diagnostic)
        if not match or Path(match[1]).resolve() != Path(source_path).resolve():
            raise ValueError(f'unreviewed diagnostic: {diagnostic[:200]}')
        _, number, _, width, kind, operand, old_width = match.groups()
        line = int(number) - 1
        width, old_width = int(width), int(old_width)
        if line in seen or not 0 < old_width < width:
            raise ValueError('duplicate diagnostic or invalid extension width')
        seen.add(line)
        original = lines[line]
        division = DIVISION.search(original.rstrip('\n'))
        if not division or division[1] != operand:
            raise ValueError(f'line {line + 1}: diagnosed divisor does not match source')
        # Restrict to unsigned generated telemetry/FIU wires. No signed casts,
        # arbitrary expressions, narrowing, or changes to numerator/result.
        assignment = re.match(r'\s*wire \[(\d+):0\] \w+ = ', original)
        if not assignment or int(assignment[1]) + 1 != width:
            raise ValueError('only matching generated unsigned wire assignments supported')
        if kind == 'CONST' and not operand.startswith(f"{old_width}'"):
            raise ValueError('literal width mismatch')
        if kind == 'VARREF' and (operand, old_width) not in unsigned_inputs:
            raise ValueError('unsigned divisor declaration missing or width mismatch')
        replacement = f"{{{width - old_width}'b0, {operand}}}"
        start, end = division.span(1)
        lines[line] = original[:start] + replacement + original[end:]
        changes.append({'line': line + 1, 'operand': operand, 'kind': kind,
                        'from_bits': old_width, 'to_bits': width,
                        'before': original.rstrip('\n'), 'after': lines[line].rstrip('\n')})
    if not changes:
        raise ValueError('no diagnosed division widths to repair')
    return ''.join(lines), changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('lint_log', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    fixed, changes = fix_divisors(raw.decode(), args.lint_log.read_text(), args.source)
    args.output.mkdir(parents=True, exist_ok=False)
    target = args.output / args.source.name
    target.write_text(fixed)
    record = {'schema': 'srota.explicit-unsigned-divisors/1', 'qualified': False,
              'source': str(args.source), 'source_sha256': hashlib.sha256(raw).hexdigest(),
              'lint_log_sha256': hashlib.sha256(args.lint_log.read_bytes()).hexdigest(),
              'output': str(target), 'output_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
              'changes': changes}
    (args.output / 'width-repairs.json').write_text(json.dumps(record, indent=2) + '\n')
    print(f'explicit_unsigned_divisors={len(changes)} output={target}')


if __name__ == '__main__':
    main()
