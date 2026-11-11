#!/usr/bin/env python3
"""Replace the 64 cell implementations with their pin-compatible DPI wrappers."""
import argparse
import hashlib
from pathlib import Path
import re


def prepare(text):
    marker = 'module CatalogRouterCell_0('
    if text.count(marker) != 1:
        raise ValueError('expected exactly one actual cell-definition boundary')
    top = text[:text.index(marker)]
    counts = []
    for i in range(64):
        top, n = re.subn(rf'(?m)(?<!\w)CatalogRouterCell_{i}(\s+\w+\s*\()',
                         rf'srota_cell{i}\1', top)
        if n != 1:
            raise ValueError(f'expected one instance of cell {i}, found {n}')
        counts.append(n)
    if 'CatalogRouterCell_' in top:
        raise ValueError('unmapped implementation module remains in top')
    return top


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('output', type=Path)
    args = p.parse_args()
    result = prepare(args.source.read_text())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result)
    print(f'prepared_top_bytes={args.output.stat().st_size} actual_cells=64 output_sha256={sha(args.output)}')


if __name__ == '__main__':
    main()
