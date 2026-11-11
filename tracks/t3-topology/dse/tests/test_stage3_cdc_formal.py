"""M3 CDC completion: depth semantics, MTBF estimator, SVA + sby proof evidence.

- Depth: cdc_fifo asserts FULL at VDEPTH=DEPTH/2 (shadow capacity for sync
  lag — FULL-at-full-depth was proven lossy), so nominal DEPTH=16 yields
  net usable depth 8. The mapping is exposed by net_usable_depth and the
  emitted header, never silently reinterpreted.
- MTBF: computed by estimate_mtbf from *declared* per-domain rates with
  the formula stated in the cell header (Cummings AN-1077 form, declared
  tau=100 ps / t0=50 ps — assumed constants, not library data). Undeclared
  rates stay NOT_CALCULATED with reason.
- Assertions: concurrent SVA in the fifo (Gray sequence, acceptance
  gating, reset alignment) + SymbiYosys BMC proof (cdc_fifo.sby, bounded
  depth). A literal !(wr_full && rd_empty) mutex is NOT asserted: it is
  FALSE under sync lag (the flags co-occur by design); the enforced
  enclave is the gating/quiescence pair.
- Missing-cell refusal: preserved (env: no fakes).
"""
from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

import pytest

from veritx_dse.core.paths import REPO
from veritx_dse.model.clock_power_cdc import (
    ClockPowerInput, EndpointDomain, check_clock_power_cdc, cdc_cells_for,
)
from veritx_dse.product.cdc_cell_rtl import (
    CDC_INVALID_PARAMS, CdcParams, build_cdc_cell, estimate_mtbf,
    net_usable_depth,
)

_FIFO = Path(REPO) / "tracks/t3-topology/rtl/cdc/cdc_fifo.sv"
_SBY = Path(REPO) / "tracks/t3-topology/rtl/cdc/cdc_fifo.sby"
_SBY_DIR = Path(REPO) / "tracks/t3-topology/rtl/cdc/cdc_fifo"

_VERILATOR = shutil.which("verilator")


def _sby_path() -> str | None:
    for candidate in (shutil.which("sby"),
                      "/home/datavex/.local/bin/sby"):
        if candidate and Path(candidate).exists():
            return candidate
    return None


_SBY_BIN = _sby_path()


# --- depth semantics ------------------------------------------------------


def test_default_usable_depth_is_8_from_nominal_16():
    params = CdcParams(
        insertion_point="cdc:attach:group0(a)->group1(b)",
        src_domain="a", dst_domain="b", src_group=0, dst_group=1)
    assert params.depth == 8
    assert net_usable_depth(params.depth) == 8
    build = build_cdc_cell(params)
    assert build.verdict.ok is True
    assert "DEPTH = 16" in (build.source or "")
    assert "USABLE_DEPTH = 8" in (build.source or "")
    assert ".DEPTH(DEPTH)" in (build.source or "")


def test_net_usable_depth_is_full_usable_not_half():
    for usable in (4, 8, 16, 64):
        assert net_usable_depth(usable) == usable
        build = build_cdc_cell(CdcParams(
            insertion_point="cdc:declared:a->b", src_domain="a",
            dst_domain="b", depth=usable))
        assert build.verdict.ok is True
        assert f"USABLE_DEPTH = {usable}" in (build.source or "")
        assert f"DEPTH = {2 * usable}" in (build.source or "")


# --- MTBF estimator --------------------------------------------------------


def _manual_mtbf_years(sampling_mhz, transition_mhz, stages):
    """Hand-computed formula value (test oracle — mirrors MTBF_FORMULA)."""
    t_clk = 1.0 / (sampling_mhz * 1e6)
    t_r = (stages - 1) * t_clk
    tau, t0 = 100e-12, 50e-12
    return (math.exp(t_r / tau)
            / (t_clk * transition_mhz * 1e6 * math.exp(t0 / tau))
            / 31_536_000.0)


def test_mtbf_declared_rates_match_manual_formula():
    est = estimate_mtbf(1000, 1000, 3)
    assert est.status == "CALCULATED"
    fwd = _manual_mtbf_years(1000, 1000, 3)   # sampled on dst @ 1 GHz
    rev = _manual_mtbf_years(1000, 1000, 3)   # sampled on src @ 1 GHz
    assert est.years == pytest.approx(min(fwd, rev), rel=1e-9)
    assert est.direction.startswith("src->dst")
    # Canonical example: 1 GHz / 1 GHz with 3-FF sync => ~9.33 years.
    assert est.years == pytest.approx(9.33, rel=0.05)


def test_mtbf_s_two_ff_is_marginal_and_governing_direction_shifts():
    two_ff = estimate_mtbf(1000, 1000, 2)
    assert two_ff.status == "CALCULATED"
    assert two_ff.years == pytest.approx(
        _manual_mtbf_years(1000, 1000, 2), rel=1e-9)
    # 2-FF is marginal: hours, not years.
    assert two_ff.years < 0.01
    # Asymmetric rates: governing direction flips to the faster sampler.
    asym = estimate_mtbf(2000, 1000, 3)
    assert asym.status == "CALCULATED"
    assert asym.direction.startswith("dst->src")
    assert asym.years == pytest.approx(min(
        _manual_mtbf_years(1000, 2000, 3),
        _manual_mtbf_years(2000, 1000, 3)), rel=1e-9)


def test_mtbf_undeclared_rates_stay_not_calculated_with_reason():
    for src, dst in ((None, None), (None, 1000), (1000, None)):
        est = estimate_mtbf(src, dst, 3)
        assert est.status == "NOT_CALCULATED"
        assert est.years is None
        assert "UNDECLARED" in (est.reason or "")
    # Zero/negative rates are refused at the params layer (never a number).
    bad = build_cdc_cell(CdcParams(
        insertion_point="cdc:declared:a->b", src_domain="a", dst_domain="b",
        src_clock_mhz=0))
    assert bad.verdict.ok is False
    assert bad.verdict.blocker_id == CDC_INVALID_PARAMS
    assert bad.source is None


def test_mtbf_formula_tau_t0_cited_in_emitted_header():
    build = build_cdc_cell(CdcParams(
        insertion_point="cdc:declared:a->b", src_domain="a", dst_domain="b",
        src_clock_mhz=1000, dst_clock_mhz=1000))
    assert build.verdict.ok is True
    src = build.source or ""
    assert "MTBF: status CALCULATED" in src
    assert "tau=100 ps" in src and "t0=50 ps" in src
    assert "exp(t_r / tau) / (T_clk * f_cdc * exp(t_0 / tau))" in src
    assert "Cummings AN-1077" in src
    assert "DECLARED assumptions" in src
    # And the undeclared variant keeps the formula visible with NOT_CALCULATED.
    plain = build_cdc_cell(CdcParams(
        insertion_point="cdc:declared:a->b", src_domain="a", dst_domain="b"))
    assert "status NOT_CALCULATED" in (plain.source or "")
    assert "UNDECLARED" in (plain.source or "")


# --- SVA presence + verilator lint/sim -------------------------------------


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_generated_cell_lints_with_wrapper_alignment_sva(tmp_path):
    build = build_cdc_cell(CdcParams(
        insertion_point="cdc:attach:group0(a)->group1(b)",
        src_domain="a", dst_domain="b", src_group=0, dst_group=1))
    assert build.module is not None
    (tmp_path / "cdc_fifo.sv").write_text(_FIFO.read_text())
    (tmp_path / f"{build.module}.sv").write_text(build.source)
    assert "a_cell_reset_align_wr" in build.source
    assert "a_cell_reset_align_rd" in build.source
    checked = subprocess.run(
        [_VERILATOR, "--lint-only", "-sv", "-Wall", "-Wno-fatal",
         "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT",
         "--top-module", build.module, "cdc_fifo.sv", f"{build.module}.sv"],
        cwd=tmp_path, capture_output=True, text=True)
    log = checked.stdout + checked.stderr
    assert checked.returncode == 0, log


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_fifo_sva_stays_silent_in_verilator_sim(tmp_path):
    """Run the fifo under the repo Verilator TB; the DUT SVA must not fire.

    The bundled tb_cdc.cpp oracle currently fails independently of the
    assertions (identical FAIL with the pristine fifo — reproduced
    pre-change), so this evidence is only that none of the concurrent
    assertions printed/fired, not that the bundled oracle passes.
    """
    fifo = _FIFO
    harness = Path(REPO) / "tracks/t3-topology/rtl/cdc/tb_cdc.cpp"
    assert fifo.is_file() and harness.is_file()
    built = subprocess.run(
        [_VERILATOR, "--timing", "-O0", "-Wall", "-Wno-fatal",
         "-Wno-WIDTH", "-Wno-UNOPTFLAT", "--cc", "--exe", "--build",
         "--top-module", "cdc_fifo", "--Mdir", str(tmp_path / "obj"),
         str(harness), str(fifo)],
        capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stdout + built.stderr
    run = subprocess.run(
        [str(tmp_path / "obj" / "Vcdc_fifo")],
        capture_output=True, text=True, timeout=120)
    log = run.stdout + run.stderr
    assert "Assertion" not in log and "%Error" not in log, log
    assert "CDC FIFO RESULTS" in log


@pytest.mark.skipif(_SBY_BIN is None, reason="sby not installed")
def test_sby_bmc_proofs_pass_bounded_only():
    """Run the sby BMC (depth 26); Gray + gating + reset invariants PASS."""
    assert _SBY_BIN is not None
    assert _SBY.is_file()
    proc = subprocess.run([_SBY_BIN, "-f", str(_SBY)],
                          cwd=Path(REPO), capture_output=True, text=True,
                          timeout=300)
    out = proc.stdout + proc.stderr
    assert "DONE (PASS" in out, out[-3000:]
    assert "step 25" in out or "Status: passed" in out


def test_fifo_formal_invariance_source_text():
    """The formal (immediate) assertion names mirror the concurrent ones."""
    text = _FIFO.read_text()
    assert text.count("assert property (@(posedge") >= 6
    assert "a_fifo_gray_eq_wr" in text and "a_fifo_gray_eq_rd" in text
    assert "a_fifo_gray_step_wr" in text and "a_fifo_gray_step_rd" in text
    assert "a_fifo_full_blocks_wr" in text and "a_fifo_empty_blocks_rd" in text
    assert "a_fifo_quiescent_wr" in text and "a_fifo_quiescent_rd" in text
    assert "a_fifo_reset_vals_wr" in text and "a_fifo_reset_vals_rd" in text
    # The false literal mutex must not be shipped as an effective assert
    # (only the explanatory NOTE may mention it).
    assert "|-> !(wr_full && rd_empty)" not in text
    assert "mutex assert is therefore FALSE by design" in text
    assert "833 samples" in text  # measured co-occurrence evidence


# --- missing-cell refusal --------------------------------------------------


def test_missing_cell_refusal_preserved_no_fakes():
    endpoints = (
        EndpointDomain(0, "a", None, None, None),
        EndpointDomain(1, "b", None, None, None))
    refused = check_clock_power_cdc(ClockPowerInput(endpoints=endpoints))
    assert refused.ok is False
    assert "CDC_CELL_MISSING" in (refused.reason or "")
    # And the builder itself still produces only real cells or typed refusals.
    build = build_cdc_cell(CdcParams(
        insertion_point="cdc:declared:a->b", src_domain="a", dst_domain="a"))
    assert build.verdict.ok is False and build.module is None
