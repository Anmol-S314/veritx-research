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

``support_reason`` is the same decision as a pure function, so a caller that
knows the SELECTED fabric's measured VC count / family / shared-wire count
(``--selected-vcs``, ``--selected-family``, ``--shared-wires``) can be refused
before a 2-VC emitter is ever run for a fabric measured with another scheme.

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

#: VCs this emitter implements: VC0 free dim-order/up*/down*, VC1 escape.
CERTIFIED_VC_COUNT = 2

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
    ap.add_argument("--selected-vcs", type=int, default=None,
                    help="VC count the selected fabric was measured with; a "
                         "value other than --num-vc is refused")
    ap.add_argument("--selected-family", default=None,
                    help="selected topology family, used only in refusal text")
    ap.add_argument("--shared-wires", type=int, default=0,
                    help="shared (multi-drop) links in the selected fabric; "
                         "any value > 0 is refused")
    ap.add_argument("--tables", choices=["auto", "dijkstra"], default="auto",
                    help="free-class route tables (auto = acyclic-guaranteed)")
    ap.add_argument("--arch", choices=["plane-v2", "legacy-vc"],
                    default="legacy-vc", help="router architecture")
    # M2 OrderingFSM slice (STAGE 1 §4.2 / STAGE 3 §3.5): policy knobs that
    # must reach Verilog, not a fixed 2-VC free/escape assumption. Absent =
    # historical behavior (no patch, byte-identical output).
    ap.add_argument("--ordering", choices=["strong", "relaxed", "raw"],
                    default=None, help="OrderingFSM mode (M2)")
    ap.add_argument("--max-outstanding", type=int, default=None,
                    help="OrderingFSM outstanding bound (M2)")
    ap.add_argument("--split-at", type=int, default=None,
                    help="OrderingFSM split alignment threshold (M2)")
    ap.add_argument("--traffic-class-vc", action="append", default=[],
                    metavar="CLASS=VC",
                    help="traffic-class -> VC reassignment (M2, repeatable)")
    return ap


#: Code on every M2 refusal (mirrors catalog_evaluation).
UNSUPPORTED_STAGE1_REALIZATION = "UNSUPPORTED_STAGE1_REALIZATION"


def _parse_traffic_class_vcs(specs: list[str] | None) -> tuple[tuple[str, int], ...]:
    """Parse ``CLASS=VC`` specs; a malformed spec is an M2 refusal."""
    parsed: list[tuple[str, int]] = []
    for spec in specs or []:
        if "=" not in spec:
            raise RtlGenerationRefusal(
                f"{UNSUPPORTED_STAGE1_REALIZATION}: malformed "
                f"--traffic-class-vc {spec!r} (expected CLASS=VC); no "
                f"OrderingFSM substitute is emitted; "
                f"owner stage = {OWNING_STAGE}; module = OrderingFSM")
        name, _, vc_text = spec.partition("=")
        name = name.strip()
        try:
            vc = int(vc_text)
        except ValueError:
            raise RtlGenerationRefusal(
                f"{UNSUPPORTED_STAGE1_REALIZATION}: malformed "
                f"--traffic-class-vc {spec!r} (VC is not an integer); no "
                f"OrderingFSM substitute is emitted; "
                f"owner stage = {OWNING_STAGE}; module = OrderingFSM")
        if not name:
            raise RtlGenerationRefusal(
                f"{UNSUPPORTED_STAGE1_REALIZATION}: malformed "
                f"--traffic-class-vc {spec!r} (empty class name); no "
                f"OrderingFSM substitute is emitted; "
                f"owner stage = {OWNING_STAGE}; module = OrderingFSM")
        parsed.append((name, vc))
    return tuple(parsed)


def support_reason(*, num_vcs: int = CERTIFIED_VC_COUNT,
                   selected_vcs: int | None = None,
                   selected_family: str | None = None,
                   shared_wires: int = 0,
                   connected: bool | None = None,
                   ordering: str | None = None,
                   max_outstanding: int | None = None,
                   split_at: int | None = None,
                   traffic_class_vcs: tuple[tuple[str, int], ...] | None = None) -> str | None:
    """Typed reason this seam cannot serve the selected fabric, else ``None``.

    The emitter implements ONE scheme: the certified 2-VC free/escape router
    over a connected point-to-point graph, plus the M2 OrderingFSM slice
    (ordering / outstanding / split / class->VC within 2 VCs). A caller
    that knows the SELECTED fabric's measured VC count, family or
    shared-wire count can hand them in so the refusal names the actual
    mismatch instead of silently emitting a 2-VC design for a fabric
    measured with a different scheme.
    """
    label = selected_family or "selected"
    # M2 slice first: an ordering policy outside 2 VCs / on a shared wire
    # names the OrderingFSM, never a free/escape substitute.
    m2_policy = (ordering is not None or max_outstanding is not None
                 or split_at is not None or bool(traffic_class_vcs))
    if m2_policy:
        if max_outstanding is not None and max_outstanding < 1:
            return (f"{UNSUPPORTED_STAGE1_REALIZATION}: "
                    f"max_outstanding={max_outstanding} is not a legal "
                    f"OrderingFSM bound (>=1); no substitute is emitted; "
                    f"owner stage = {OWNING_STAGE}; module = OrderingFSM")
        if split_at is not None and split_at < 1:
            return (f"{UNSUPPORTED_STAGE1_REALIZATION}: "
                    f"split_at={split_at} is not a legal OrderingFSM "
                    f"threshold (>=1); no substitute is emitted; "
                    f"owner stage = {OWNING_STAGE}; module = OrderingFSM")
        if ordering == "relaxed" and max_outstanding is None:
            return (f"{UNSUPPORTED_STAGE1_REALIZATION}: "
                    f"ordering='relaxed' needs --max-outstanding to define "
                    f"the OrderingFSM reorder window; the preview will not "
                    f"invent one; no substitute is emitted; "
                    f"owner stage = {OWNING_STAGE}; module = OrderingFSM")
        for name, vc in (traffic_class_vcs or ()):
            if not 0 <= vc < CERTIFIED_VC_COUNT:
                return (f"{UNSUPPORTED_STAGE1_REALIZATION}: "
                        f"traffic class {name!r} requires VC{vc} but the "
                        f"certified {CERTIFIED_VC_COUNT}-VC scheme has "
                        f"VC0/VC1 only; no >2-VC OrderingFSM substitute is "
                        f"emitted; owner stage = {OWNING_STAGE}; "
                        f"module = OrderingFSM")
        if shared_wires:
            return (f"{UNSUPPORTED_STAGE1_REALIZATION}: selected {label} "
                    f"fabric has {shared_wires} shared (multi-drop) "
                    f"wire(s); the OrderingFSM policy cannot be emitted on "
                    f"shared wires; no substitute is emitted; "
                    f"owner stage = {OWNING_STAGE}; module = OrderingFSM")
    if selected_vcs is not None and selected_vcs != num_vcs:
        return (f"selected {label} fabric was measured with {selected_vcs} VCs; "
                f"this emitter is the certified {num_vcs}-VC free/escape "
                f"scheme, so no matching RTL emitter exists; "
                f"owner stage = {OWNING_STAGE}")
    if num_vcs != CERTIFIED_VC_COUNT:
        return (f"--num-vc {num_vcs}: only the certified {CERTIFIED_VC_COUNT}-VC "
                f"scheme (VC0 free dim-order/up*/down*, VC1 escape) is wired "
                f"here and no matching RTL emitter exists; "
                f"owner stage = {OWNING_STAGE}")
    if shared_wires:
        return (f"selected {label} fabric has {shared_wires} shared "
                f"(multi-drop) wire(s); this emitter is point-to-point only, "
                f"so no matching RTL emitter exists; "
                f"owner stage = {OWNING_STAGE}")
    if connected is False:
        return (f"selected {label} fabric is not connected (disconnected); the "
                f"certified slice needs a connected topology so the escape tree "
                f"spans every router; owner stage = {OWNING_STAGE}")
    return None


def _assert_supported(emitter, args) -> None:
    """Refuse everything outside the certified 2-VC connected-topology slice."""
    traffic_class_vcs = _parse_traffic_class_vcs(args.traffic_class_vc)
    args._traffic_class_vcs = traffic_class_vcs
    reason = support_reason(
        num_vcs=args.num_vc, selected_vcs=args.selected_vcs,
        selected_family=args.selected_family, shared_wires=args.shared_wires,
        ordering=args.ordering, max_outstanding=args.max_outstanding,
        split_at=args.split_at, traffic_class_vcs=traffic_class_vcs)
    if reason is not None:
        raise RtlGenerationRefusal(reason)
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
            support_reason(num_vcs=args.num_vc,
                           selected_family=args.selected_family,
                           connected=False))


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


def _apply_ordering_patch(args) -> None:
    """Reflect the M2 policy in ``noc_pkg.sv`` + ``meta.json``.

    No-op when no M2 knob is declared (byte-identical historical output).
    With knobs: appends ``ORDERING_*`` localparams and the class->VC->table
    map to the package, and records the same struct in ``meta.json``; the
    route tables (RT_MIN/RT_ESC) are unchanged — VC0 selects RT_MIN, VC1
    selects RT_ESC, and ordering_fsm.sv performs the selection.
    """
    traffic_class_vcs = getattr(args, "_traffic_class_vcs", ()) or ()
    if (args.ordering is None and args.max_outstanding is None
            and args.split_at is None and not traffic_class_vcs):
        return
    mode = {"raw": 0, "strong": 1, "relaxed": 2}.get(args.ordering or "raw", 0)
    outdir = Path(args.outdir)
    pkg_path = outdir / "noc_pkg.sv"
    text = pkg_path.read_text()
    table_of_vc = {0: "RT_MIN", 1: "RT_ESC"}
    lines = [
        "  // M2 OrderingFSM slice (STAGE 1 ordering/VC policy).",
        f"  localparam int ORDERING_MODE = {mode};",
        f"  localparam int ORDERING_MAX_OUTSTANDING = {args.max_outstanding if args.max_outstanding is not None else 0};",
        f"  localparam int ORDERING_SPLIT_AT = {args.split_at if args.split_at is not None else 0};",
        f"  localparam int ORDERING_NUM_CLASSES = {len(traffic_class_vcs)};",
    ]
    for idx, (name, vc) in enumerate(sorted(traffic_class_vcs)):
        lines.append(
            f"  // class {idx} {name!r} -> VC{vc} ({table_of_vc[vc]})")
    patch = "\n".join(lines)
    # Insert before the closing endpackage so the package stays valid SV.
    assert text.rstrip().endswith("endpackage")
    head, _ = text.rsplit("endpackage", 1)
    pkg_path.write_text(head + patch + "\nendpackage\n")
    import json
    meta_path = outdir / "meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text())
            meta["ordering_policy"] = {
                "ordering": args.ordering,
                "max_outstanding": args.max_outstanding,
                "split_at": args.split_at,
                "traffic_class_vcs": [
                    {"traffic_class": name, "vc": vc}
                    for name, vc in sorted(traffic_class_vcs)],
            }
            meta["vc_assignment"] = [
                {"traffic_class": name, "vc": vc,
                 "route_table": table_of_vc[vc]}
                for name, vc in sorted(traffic_class_vcs)]
            meta_path.write_text(json.dumps(meta, indent=2) + "\n")
        except (OSError, ValueError):
            pass


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
    _apply_ordering_patch(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
