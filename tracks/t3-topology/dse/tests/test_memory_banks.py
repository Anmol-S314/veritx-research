from __future__ import annotations

import shutil
import subprocess

import pytest

from veritx_dse.core.paths import REPO

RTL_DIR = REPO / "tracks" / "t3-topology" / "rtl" / "multi_seat"
BANKS = RTL_DIR / "memory_banks.sv"
TB = RTL_DIR / "tb_memory_banks.sv"

EXPECTED_LINES = (
    "PASS: S1 bank isolation",
    "PASS: S2 conservation and attribution",
    "PASS: S3 response stable while the consumer stalls",
    "PASS: S4 no protocol error on legal bank ids",
    "PASS: S5 illegal bank id consumed and latched",
    "status: PASS",
)

pytestmark = pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")


@pytest.mark.parametrize("n_banks,bank_w", [(1, 1), (2, 1), (3, 2), (4, 2), (5, 3)])
def test_memory_banks_lints_with_no_warnings(n_banks, bank_w):
    lint = subprocess.run(
        ["verilator", "--lint-only", "-Wall", "--timing", "-sv", "-Wno-DECLFILENAME",
         "--top-module", "memory_banks", f"-GN_BANKS={n_banks}", f"-GBANK_W={bank_w}", str(BANKS)],
        capture_output=True, text=True, timeout=300)
    assert lint.returncode == 0 and "%Warning" not in lint.stderr, lint.stderr[-2000:]


def test_memory_banks_behaviour_is_proven(tmp_path):
    build = subprocess.run(
        ["verilator", "--binary", "--timing", "-Wno-fatal", "-Wno-WIDTH", "-Wno-DECLFILENAME",
         "-Wno-TIMESCALEMOD", "-Wno-BLKSEQ", "--top-module", "tb_memory_banks",
         "--Mdir", str(tmp_path), str(BANKS), str(TB)],
        capture_output=True, text=True, timeout=900)
    assert build.returncode == 0, build.stdout[-3000:] + build.stderr[-3000:]
    sim = subprocess.run([str(tmp_path / "Vtb_memory_banks")], capture_output=True, text=True, timeout=300)
    output = sim.stdout + sim.stderr
    for line in EXPECTED_LINES:
        assert line in output, (line, output[-2000:])
    assert "FAIL:" not in output, output[-2000:]
