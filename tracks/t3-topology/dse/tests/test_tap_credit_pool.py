from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from veritx_dse.core.paths import REPO

RTL_DIR = REPO / "tracks" / "t3-topology" / "rtl" / "tap_credit"
POOL = RTL_DIR / "tap_credit_pool.sv"
TB = RTL_DIR / "tb_tap_credit_pool.sv"
FORMAL = RTL_DIR / "tap_credit_formal.sv"
FORMAL_SBY = RTL_DIR / "tap_credit_formal.sby"

EXPECTED_LINES = (
    "PASS: S1 a grant consumes a credit of exactly the (tap, VC) requested",
    "PASS: S2 no cross-tap and no cross-VC credit movement",
    "PASS: S3 a freed credit returns to its own (tap, VC) after the declared latency",
    "PASS: S4 an exhausted (tap, VC) refuses further grants and disturbs no other pair",
    "PASS: S5 taps and VCs are independent, and no alias is reported",
    "PASS: S6 a matured return and same-pair grant are both accounted",
    "status: PASS",
)


@pytest.fixture(scope="module")
def credit_pool_run(tmp_path_factory):
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed; cannot lint/sim the credit pool")
    out = tmp_path_factory.mktemp("tap_credit")
    build = subprocess.run(
        ["verilator", "--binary", "--timing", "-Wall", "-Wno-fatal", "-Wno-WIDTH",
         "-Wno-DECLFILENAME", "--top-module", "tb_tap_credit_pool",
         "--Mdir", str(out), str(POOL), str(TB)],
        capture_output=True, text=True, timeout=900)
    assert build.returncode == 0, build.stdout[-4000:] + build.stderr[-4000:]
    binary = out / "Vtb_tap_credit_pool"
    assert binary.is_file(), binary
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=300)
    return build, run


def test_credit_pool_lints_clean(credit_pool_run):
    build, _ = credit_pool_run
    errors = [line for line in (build.stdout + build.stderr).splitlines()
              if "%Error" in line]
    assert not errors, errors


def test_credit_pool_behaviour_is_proven_by_simulation(credit_pool_run):
    _, run = credit_pool_run
    output = (run.stdout or "") + (run.stderr or "")
    for line in EXPECTED_LINES:
        assert line in output, (line, output[-3000:])
    assert "FAIL:" not in output, output[-3000:]


@pytest.mark.skipif(os.environ.get("VERITX_RUN_FORMAL") != "1",
                    reason="formal proof is slow (minutes); run with VERITX_RUN_FORMAL=1")
def test_credit_pool_invariants_are_formally_proven(tmp_path):
    if shutil.which("sby") is None or shutil.which("yosys") is None \
            or shutil.which("z3") is None:
        pytest.skip("formal toolchain (sby/yosys/z3) not installed")
    work = tmp_path / "formal"
    work.mkdir()
    for src in (POOL, FORMAL, FORMAL_SBY):
        shutil.copy(src, work / src.name)
    run = subprocess.run(["sby", "-f", "tap_credit_formal.sby"], cwd=work,
                         capture_output=True, text=True, timeout=3600)
    assert run.returncode == 0, (run.stdout[-4000:] + run.stderr[-4000:])
    assert "DONE (PASS" in run.stdout, run.stdout[-2000:]
