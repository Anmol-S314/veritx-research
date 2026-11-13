#!/usr/bin/env python3
"""Rewrite emitted GEC fabric RTL into the subset Yosys can parse.

Two constructs in the emitted fabric stop every non-Verilator tool dead:

1. ``return <expr>;`` inside a function. Yosys reports ``Can't resolve task name
   `return'`` because it parses ``return`` as a task call.
2. ``automatic logic x;`` as a declaration inside a function body. Yosys reports
   ``syntax error, unexpected TOK_AUTOMATIC``.
3. ``$fatal`` inside an ``initial`` block. Yosys reports ``Can't resolve task name
   `$fatal'``. These are elaboration-time parameter-contract checks, so they are
   wrapped in ``ifndef SYNTHESIS`` and stay active for every simulation tool.

Both are syntax-only. ``return e;`` and ``fname = e;`` are equivalent when the
return is the last action on its path, and a function-local declared inside an
``automatic`` function is already automatic, so dropping the keyword changes
nothing semantically.

The rewrite lives in the emitter (``veritx_dse.product.sv_portable``), so the
files the emitter writes are already in this subset; this script is the
standalone CLI over the same function, for text that arrived another way. It
refuses to rewrite a return it cannot prove is in tail position, and fails
loudly if a ``return`` survives outside a comment.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tracks/t3-topology/dse"))
from veritx_dse.product.sv_portable import transform  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("dest", type=Path)
    args = ap.parse_args()
    text = args.source.read_text()
    new, stats = transform(text)
    args.dest.parent.mkdir(parents=True, exist_ok=True)
    args.dest.write_text(new)
    print(f"{args.source} -> {args.dest}")
    print(f"  functions: {', '.join(stats['functions'])}")
    print(f"  case returns rewritten: {stats['case_returns']}")
    print(f"  tail returns rewritten: {stats['tail_returns']}")
    print(f"  automatic locals dropped: {stats['automatic_locals']}")
    print(f"  $fatal blocks guarded with `ifndef SYNTHESIS: {stats['fatal_blocks_guarded']}")
    print(f"  bytes {len(text)} -> {len(new)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
