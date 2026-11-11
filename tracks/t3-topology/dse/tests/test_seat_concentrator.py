from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from veritx_dse.core.paths import REPO

RTL_DIR = REPO / "tracks" / "t3-topology" / "rtl" / "multi_seat"
CONCENTRATOR = RTL_DIR / "seat_concentrator.sv"
TB = RTL_DIR / "tb_seat_concentrator.sv"

EXPECTED_LINES = (
    "PASS: S1 round-robin fairness over 2 seats, 8 grants, skew <= 1",
    "PASS: S2 conservation: seat0 sent 4 recv 4, seat1 sent 4 recv 4",
    "PASS: S3 multi-flit packet HEAD/BODY/TAIL kept the wire (no interleaving)",
    "PASS: S4 per-seat response routing: every beat returned to its own seat",
    "PASS: S5 no protocol error",
    "status: PASS",
)


@pytest.fixture(scope="module")
def concentrator_run(tmp_path_factory):
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed; cannot lint/sim the concentrator")
    out = tmp_path_factory.mktemp("seat_concentrator")
    lint = subprocess.run(
        ["verilator", "--lint-only", "--timing", "-sv", "-Wall", "-Wno-fatal",
         "-Wno-WIDTH", "-Wno-DECLFILENAME", "--top-module",
         "tb_seat_concentrator", str(CONCENTRATOR), str(TB)],
        capture_output=True, text=True, timeout=300)
    build = subprocess.run(
        ["verilator", "--binary", "--timing", "-Wall", "-Wno-fatal", "-Wno-WIDTH",
         "-Wno-DECLFILENAME", "--top-module", "tb_seat_concentrator",
         "--Mdir", str(out), str(CONCENTRATOR), str(TB)],
        capture_output=True, text=True, timeout=900)
    assert build.returncode == 0, build.stdout[-4000:] + build.stderr[-4000:]
    binary = out / "Vtb_seat_concentrator"
    assert binary.is_file(), binary
    sim = subprocess.run([str(binary)], capture_output=True, text=True, timeout=300)
    return lint, sim


def test_concentrator_lints_clean(concentrator_run):
    lint, _ = concentrator_run
    errors = [line for line in (lint.stdout + lint.stderr).splitlines()
              if "%Error" in line]
    assert not errors, errors


def test_concentrator_behaviour_is_proven(concentrator_run):
    _, sim = concentrator_run
    output = (sim.stdout or "") + (sim.stderr or "")
    for line in EXPECTED_LINES:
        assert line in output, (line, output[-3000:])
    assert "FAIL:" not in output, output[-3000:]


def test_concentrator_module_is_packaged_with_the_product_rtl():
    assert CONCENTRATOR.is_file()
    source = CONCENTRATOR.read_text()
    assert "module seat_concentrator" in source
    assert "default_nettype none" in source
