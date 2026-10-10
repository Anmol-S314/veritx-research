"""test_rtl_generation.py — the product-path RTL emitter is real and lints.

Pins the seam at ``tracks/t3-topology/scripts/rtlgen/gen_rtl.py``:

  * it emits SystemVerilog by reusing the certified 2-VC emitter
    (``tracks/t3-topology/rtl/mot_htree/gen_rtl_htree.py``), not by faking
    artifacts;
  * the emitted top module passes ``verilator --lint-only``; and
  * requests outside the certified slice (a VC count other than 2, a
    disconnected topology) are refused with a typed reason naming the owning
    stage instead of emitting something unverified.

If verilator is absent the lint test is skipped with its reason, not silently
passed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_TRACK_ROOT = _TESTS_DIR.parents[1]                       # .../tracks/t3-topology
_RTLGEN_DIR = _TRACK_ROOT / "scripts" / "rtlgen"
_GEN_RTL = _RTLGEN_DIR / "gen_rtl.py"
_EMITTER = _TRACK_ROOT / "rtl" / "mot_htree" / "gen_rtl_htree.py"

# The certified mesh / 2-VC case: a row-major 2x2 mesh.
_TINY4_ANYNET = """\
router 0 node 0 router 1 router 2
router 1 node 1 router 0 router 3
router 2 node 2 router 0 router 3
router 3 node 3 router 1 router 2
"""

# Two disjoint 2-node components: no free-class route set exists.
_DISCONNECTED_ANYNET = """\
router 0 node 0 router 1
router 1 node 1 router 0
router 2 node 2 router 3
router 3 node 3 router 2
"""

_EMITTED_FILES = ("noc_pkg.sv", "router.sv", "noc_top.sv", "Makefile",
                  "tb_top.cpp", "meta.json")

# Suppressions mirror the emitter's own Makefile (VERILATOR_FLAGS): the
# generated RTL is intentional here, and -Wno-fatal makes warnings non-fatal
# exactly as the emitter's build target does. No error is suppressed.
_LINT_FLAGS = (
    "--lint-only", "-sv", "-Wall", "-Wno-fatal",
    "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT",
    "--top-module", "noc_top",
)


def _emit(anynet: Path, outdir: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_GEN_RTL), "--anynet", str(anynet),
         "--outdir", str(outdir), *extra],
        capture_output=True, text=True, cwd=str(outdir.parent))


def test_the_seam_and_its_emitter_exist():
    assert _GEN_RTL.is_file(), f"emitter seam missing: {_GEN_RTL}"
    assert _EMITTER.is_file(), f"certified emitter missing: {_EMITTER}"


def test_the_seam_reexports_the_emitters_route_helpers():
    # flow_certifier.py and milestone_c.py guard `from gen_rtl import ...`;
    # the seam must expose the emitter's own helpers so those imports resolve
    # against one implementation instead of degrading to import_unavailable.
    # Run in a subprocess so the sys.path wiring the seam performs does not
    # leak into the rest of the session.
    names = ("dim_order_tables", "up_down_tables", "dijkstra_tables",
             "tree_tables", "cdg_has_cycle", "_best_escape_root",
             "parse_anynet")
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(_RTLGEN_DIR)!r})\n"
        "import gen_rtl\n"
        f"names = {names!r}\n"
        "missing = [n for n in names "
        "if not callable(getattr(gen_rtl, n, None))]\n"
        "assert not missing, missing\n"
        "print('NAMES-OK')\n"
    )
    proc = subprocess.run([sys.executable, "-c", code],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "NAMES-OK" in proc.stdout


def test_the_seam_emits_systemverilog_for_the_certified_mesh(tmp_path):
    anynet = tmp_path / "tiny4.anynet"
    anynet.write_text(_TINY4_ANYNET)
    outdir = tmp_path / "rtl"

    proc = _emit(anynet, outdir)
    assert proc.returncode == 0, proc.stderr
    for name in _EMITTED_FILES:
        assert (outdir / name).is_file(), f"{name} was not emitted"

    meta = json.loads((outdir / "meta.json").read_text())
    assert meta["n"] == 4
    assert meta["vcs"] == 2
    assert meta["tables"] == "auto"
    assert meta["guardrail_hash"]


def test_emitted_top_lints_with_verilator(tmp_path):
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed; cannot lint the emitted RTL")

    anynet = tmp_path / "tiny4.anynet"
    anynet.write_text(_TINY4_ANYNET)
    outdir = tmp_path / "rtl"
    emit = _emit(anynet, outdir)
    assert emit.returncode == 0, emit.stderr

    lint = subprocess.run(
        ["verilator", *_LINT_FLAGS, "noc_pkg.sv", "router.sv", "noc_top.sv"],
        capture_output=True, text=True, cwd=str(outdir))
    assert lint.returncode == 0, lint.stdout + lint.stderr


def test_a_non_two_vc_request_is_refused_with_a_typed_reason(tmp_path):
    anynet = tmp_path / "tiny4.anynet"
    anynet.write_text(_TINY4_ANYNET)
    outdir = tmp_path / "rtl"

    proc = _emit(anynet, outdir, "--num-vc", "3")
    assert proc.returncode == 2
    assert "RTL generation" in proc.stderr
    assert "--num-vc 3" in proc.stderr
    assert not outdir.exists(), "refusing must not emit artifacts"


def test_a_disconnected_topology_is_refused_with_a_typed_reason(tmp_path):
    anynet = tmp_path / "disconnected.anynet"
    anynet.write_text(_DISCONNECTED_ANYNET)
    outdir = tmp_path / "rtl"

    proc = _emit(anynet, outdir)
    assert proc.returncode == 2
    assert "RTL generation" in proc.stderr
    assert "not connected" in proc.stderr
    assert not outdir.exists(), "refusing must not emit artifacts"
