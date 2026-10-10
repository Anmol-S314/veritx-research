#!/usr/bin/env python3
"""gen_rtl.py — the product-path SystemVerilog emitter seam.

Rationale: docs/decisions/modules/tools.md

WHY THIS FILE EXISTS
--------------------
``veritx_dse.application.loom_capability`` marks ``generate.rtl``
NOT_IMPLEMENTED because this path did not exist, and two callers guard an
import of ``gen_rtl`` and fall back to an explicit ``import_unavailable``
verdict:

  * ``veritx_dse/tools/flow_certifier.py`` (its path math reaches here), and
  * ``dse/scripts/milestone_c.py``.

The emitter itself was never missing. The Verilator-verifiable 2-VC certified
NoC generator lives at ``tracks/t3-topology/rtl/mot_htree/gen_rtl_htree.py``;
it was simply not reachable from the product path. This module is the seam.

It does NOT reimplement the emitter. It:

  1. re-exports the emitter's route-table / CDG helpers so the guarded
     ``from gen_rtl import ...`` call sites resolve against the ONE emitter
     instead of degrading to ``import_unavailable``; and
  2. delegates emission to ``gen_rtl_htree.main()``.

What it emits is what that emitter emits: a router, a top, a Makefile and a
C++ testbench, lintable by Verilator.

SUPPORTED SLICE
---------------
The certified 2-VC scheme (``--num-vc 2``) over a CONNECTED topology. A
``--num-vc`` other than 2, a disconnected topology, or a missing emitter is
refused with a typed error naming the owning stage rather than silently
emitting a scheme that was never certified.

Usage:
  python3 gen_rtl.py --anynet mesh.anynet --outdir out/ [--block-k 8]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Layout: <track>/scripts/rtlgen/gen_rtl.py
_HERE = Path(__file__).resolve().parent          # .../tracks/t3-topology/scripts/rtlgen
_TRACK_ROOT = _HERE.parents[1]                    # .../tracks/t3-topology
_DSE_ROOT = _TRACK_ROOT / "dse"                   # .../tracks/t3-topology/dse
_TOOLS_DIR = _DSE_ROOT / "veritx_dse" / "tools"   # holds deadlock_routing.py
_EMITTER_DIR = _TRACK_ROOT / "rtl" / "mot_htree"  # holds gen_rtl_htree.py
_EMITTER_PATH = _EMITTER_DIR / "gen_rtl_htree.py"

#: The stage that owns the capability this seam serves. Named on every refusal
#: so a caller learns who could widen the slice instead of only that it failed.
OWNING_STAGE = "RTL generation"

#: Symbols the two guarded callers import from this module.
_EMITTER_EXPORTS = (
    "dim_order_tables",
    "up_down_tables",
    "dijkstra_tables",
    "tree_tables",
    "cdg_has_cycle",
    "_best_escape_root",
    "parse_anynet",
)

_emitter = None


class RtlGenerationRefusal(RuntimeError):
    """The RTL-generation seam cannot serve this request."""


def _load_emitter():
    """Import the certified 2-VC emitter, wiring the paths it assumes.

    ``gen_rtl_htree.py`` is written to be executed in place; importing it as a
    module must honour its two top-level assumptions. It imports
    ``deadlock_routing`` (which lives under the DSE tools dir), and that module
    imports ``veritx_dse.core.anynet``. Both must resolve to THIS checkout
    rather than to whatever editable install happens to be on ``sys.path``, so
    the three directories are prepended before the emitter's top-level import
    runs.
    """
    global _emitter
    if _emitter is not None:
        return _emitter
    if not _EMITTER_PATH.is_file():
        raise RtlGenerationRefusal(
            f"certified RTL emitter missing: expected {_EMITTER_PATH}; "
            f"owner stage = {OWNING_STAGE}")
    for path in (str(_DSE_ROOT), str(_TOOLS_DIR), str(_EMITTER_DIR)):
        if path not in sys.path:
            sys.path.insert(0, path)
    import gen_rtl_htree  # noqa: E402 — paths are set up immediately above

    _emitter = gen_rtl_htree
    return _emitter


def __getattr__(name: str):
    """Re-export the emitter's helpers lazily.

    A module-level ``from gen_rtl_htree import *`` would make ``import gen_rtl``
    fail hard if the emitter were ever missing, defeating the guarded fallback
    the two callers rely on. Resolving on first attribute access keeps this
    module importable and makes the missing-emitter case surface as the
    ``ImportError`` those guards already handle.
    """
    if name in _EMITTER_EXPORTS:
        return getattr(_load_emitter(), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anynet", required=True,
                    help="BookSim anynet topology file")
    ap.add_argument("--outdir", required=True,
                    help="directory to emit SystemVerilog into")
    ap.add_argument("--limit", type=int, default=0,
                    help="subset to the first N routers (0 = all)")
    ap.add_argument("--buf", type=int, default=8, help="per-port buffer depth")
    ap.add_argument("--block-k", type=int, default=8,
                    help="head-blocked cycles before demotion to escape")
    ap.add_argument("--esc-root", type=int, default=-1,
                    help="escape tree root (-1 = auto-select centre node)")
    ap.add_argument("--num-vc", type=int, default=2,
                    help="virtual channels (only 2 is wired in this slice)")
    ap.add_argument("--tables", choices=["auto", "dijkstra"], default="auto",
                    help="free-class route tables (auto = acyclic-guaranteed)")
    ap.add_argument("--arch", choices=["plane-v2", "legacy-vc"],
                    default="legacy-vc", help="router architecture")
    return ap


def _assert_supported(emitter, args) -> None:
    """Refuse everything outside the certified 2-VC connected-topology slice."""
    if args.num_vc != 2:
        raise RtlGenerationRefusal(
            f"--num-vc {args.num_vc}: only the certified 2-VC scheme "
            f"(VC0 free dim-order/up*/down*, VC1 escape) is wired here; "
            f"owner stage = {OWNING_STAGE}")
    try:
        n, adj = emitter.parse_anynet(str(args.anynet))
    except OSError as exc:
        raise RtlGenerationRefusal(
            f"cannot read anynet {args.anynet}: {exc}; "
            f"owner stage = {OWNING_STAGE}") from exc
    except ValueError as exc:
        raise RtlGenerationRefusal(
            f"{args.anynet}: malformed anynet: {exc}; "
            f"owner stage = {OWNING_STAGE}") from exc
    if emitter.up_down_tables(n, adj, emitter._best_escape_root(n, adj)) is None:
        raise RtlGenerationRefusal(
            f"{args.anynet}: topology is not connected; the certified slice "
            f"needs a connected mesh or a connected up*/down* tree; "
            f"owner stage = {OWNING_STAGE}")


def _emitter_argv(args) -> list[str]:
    """Translate this seam's arguments into the emitter's own argv."""
    return [
        "gen_rtl_htree.py",
        "--anynet", str(args.anynet),
        "--outdir", str(args.outdir),
        "--limit", str(args.limit),
        "--buf", str(args.buf),
        "--block-k", str(args.block_k),
        "--esc-root", str(args.esc_root),
        "--num-vc", str(args.num_vc),
        "--tables", args.tables,
        "--arch", args.arch,
    ]


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        emitter = _load_emitter()
        _assert_supported(emitter, args)
    except RtlGenerationRefusal as exc:
        print(f"REFUSED ({OWNING_STAGE}): {exc}", file=sys.stderr)
        return 2

    saved_argv = sys.argv
    sys.argv = _emitter_argv(args)
    try:
        emitter.main()
    finally:
        sys.argv = saved_argv
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
