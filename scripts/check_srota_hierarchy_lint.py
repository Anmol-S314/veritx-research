#!/usr/bin/env python3
"""Strict, bounded lint of actual SROTA cells and their top-level boundary join.

Only unused-signal and generated-code style diagnostics are waived. Width,
missing-port, latch, undriven and combinational-loop diagnostics remain fatal.
This is a partitioned lint gate, never a substitute for integrated simulation.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def lint_command(top, sources):
    return ['/usr/bin/verilator', '--lint-only', '--timing', '-Wall',
            '-Wno-UNUSEDSIGNAL', '-Wno-DECLFILENAME', '-Wno-BLKSEQ',
            '--top-module', top, *map(str, sources)]


def boundary_stub(header):
    # Only the intentionally empty boundary is exempt from undriven checking.
    # Do not drive outputs with zero: that would optimize away real top logic.
    return ('/* verilator lint_off UNDRIVEN */\n' + header +
            '\nendmodule\n/* verilator lint_on UNDRIVEN */\n')


def prepare_output(path):
    path.mkdir(parents=True, exist_ok=True)
    if any(path.iterdir()):
        raise FileExistsError(f'lint output must be empty: {path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('tools', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--top-source', type=Path,
                        help='explicitly pinned corrected top; cell ABIs are still checked')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('srota_stitch', args.tools / 'srota_stitch.py')
    stitch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stitch)
    root = args.root
    top_meta = json.loads((root / 'top/hierarchy-top.json').read_text())
    expected = {cell['router']: cell['binding_sha256'] for cell in top_meta['cells']}
    if set(expected) != set(range(64)):
        raise ValueError('exactly 64 distinct router identities required')
    prepare_output(args.output)
    stubs = []
    jobs = []
    top = args.top_source or root / 'top/CandidateNoCTop.v'
    parents = {}
    for body in stitch.modules(top.read_text()).values():
        for cell in re.findall(r'\bCatalogRouterCell_(\d+)\s+\w+\s*\(', body):
            if int(cell) in parents:
                raise ValueError(f'cell {cell}: duplicate top instance')
            parents[int(cell)] = body
    if set(parents) != set(range(64)):
        raise ValueError('top must instantiate all 64 actual cell boundaries')
    for i in range(64):
        rtl = root / f'cell{i}/CatalogRouterCell_{i}.v'
        meta = json.loads((root / f'cell{i}/cell-{i}.json').read_text())
        name = f'CatalogRouterCell_{i}'
        if meta.get('router') != i or meta.get('binding_sha256') != expected[i]:
            raise ValueError(f'cell {i}: binding mismatch')
        body = stitch.modules(rtl.read_text())[name]
        stitch.check_instance(parents[i], name, body)
        depth = 0
        for token in stitch.tokens(body):
            depth += (token.group() == '(') - (token.group() == ')')
            if token.group() == ';' and depth == 0:
                stubs.append(boundary_stub(body[:token.end()]))
                break
        else:
            raise ValueError(f'cell {i}: no port header')
        jobs.append((name, [rtl, rtl.parent / 'plusarg_reader.v']))
    stub_path = args.output / 'router-boundaries.v'
    stub_path.write_text('\n'.join(stubs))
    jobs.append(('CandidateNoCTop', [top, stub_path, root / 'cell0/plusarg_reader.v']))
    report = {'qualified': False, 'scope': 'strict partitioned lint; integrated simulation not run',
              'waivers': ['UNUSEDSIGNAL', 'DECLFILENAME', 'BLKSEQ', 'UNDRIVEN only in empty ABI stubs'],
              'verilator_sha256': digest('/usr/bin/verilator'), 'results': []}
    report_path = args.output / 'report.json'
    for name, sources in jobs:
        log = args.output / f'{name}.log'
        command = lint_command(name, sources)
        with log.open('xb') as stream:
            proc = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=120)
        report['results'].append({'top': name, 'command': command,
                                  'inputs': {str(p): digest(p) for p in sources},
                                  'exit_code': proc.returncode, 'log': str(log),
                                  'log_sha256': digest(log)})
        report['result'] = 'FAIL' if proc.returncode else 'INCOMPLETE'
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        print(f'STRICT_LINT {name} exit={proc.returncode} log={log}', flush=True)
        if proc.returncode:
            raise SystemExit(proc.returncode)
    report['result'] = 'PASS'
    report_path.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
