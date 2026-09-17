"""Tests for pipeline pre-flight guards (2026-09-17 additions).

Regression coverage for the three-leg pipeline failure modes diagnosed in
run 20260916_213026:

  1. BookSim leg: a trace whose size predicts wall time beyond the budget
     is refused BEFORE burning the budget (fast at any scale — the guard
     must not read the trace, only count it).
  2. Timeloop leg: the container-built binary (/usr/local/bin, built by
     the Dockerfile against the image's own sonames) is preferred over the
     vendored host-built binary, whose ABI can never match the container
     (libconfig++.so.11 vs libconfig++9v5).
"""
from veritx_dse.cli.cli import (
    BOOKSIM_PKTS_PER_SEC, booksim_budget_estimate,
    predict_booksim_budget, _pick_timeloop_mapper, _timeloop_env,
)
from veritx_dse.core.paths import REPO


class TestBooksimBudgetGuard:
    def test_packets_per_sec_constant_is_calibrated_value(self):
        assert BOOKSIM_PKTS_PER_SEC == 13_000

    def test_estimate_basic(self):
        est = booksim_budget_estimate(1_300_000)
        assert est["predicted_s"] == 100
        assert est["packets"] == 1_300_000
        assert est["pkts_per_s"] == 13_000

    def test_refuses_when_prediction_exceeds_budget(self):
        est = booksim_budget_estimate(56_141_120, budget_s=600)
        # 56.1M / 13k/s = 4318s >> 600s
        assert est["feasible"] is False
        assert est["predicted_s"] > 600

    def test_allows_small_trace(self):
        est = booksim_budget_estimate(26_880, budget_s=600)
        assert est["feasible"] is True

    def test_predict_uses_manifest_header_not_full_read(self, tmp_path):
        trace = tmp_path / "big.trace"
        trace.write_text("# Generated from traffic model: 99999999999 packets\n")
        est = predict_booksim_budget(trace, budget_s=600)
        assert est["packets"] == 99999999999
        assert est["feasible"] is False

    def test_predict_counts_lines_when_header_missing(self, tmp_path):
        trace = tmp_path / "small.trace"
        trace.write_text("0 0 0 1 4\n1 0 0 2 4\n2 0 0 3 4\n")
        est = predict_booksim_budget(trace, budget_s=600)
        assert est["packets"] == 3
        assert est["feasible"] is True


class TestTimeloopBinPreference:
    def test_prefers_container_built_over_vendored(self, tmp_path):
        usr_local = tmp_path / "usr_local_bin"
        vendored = tmp_path / "third_party_bin"
        usr_local.mkdir(); vendored.mkdir()
        (usr_local / "timeloop-mapper").write_text("#!/bin/sh\n")
        (vendored / "timeloop-mapper").write_text("#!/bin/sh\n")
        picked, provenance = _pick_timeloop_mapper(
            usr_local=usr_local, vendor_bin=vendored)
        assert picked == usr_local / "timeloop-mapper"
        assert "container" in provenance

    def test_falls_back_to_vendored_only_when_alone(self, tmp_path):
        vendored = tmp_path / "third_party_bin"
        vendored.mkdir()
        (vendored / "timeloop-mapper").write_text("#!/bin/sh\n")
        picked, provenance = _pick_timeloop_mapper(
            usr_local=tmp_path / "absent", vendor_bin=vendored)
        assert picked == vendored / "timeloop-mapper"
        assert "vendored" in provenance

    def test_missing_binary_reports_provenance(self, tmp_path):
        picked, provenance = _pick_timeloop_mapper(
            usr_local=tmp_path / "a", vendor_bin=tmp_path / "b")
        assert picked == tmp_path / "b" / "timeloop-mapper"
        assert provenance == "missing"

    def test_real_repo_vendored_binary_exists(self):
        # The picker's fallback leg: the vendored binary is present in the
        # repo (host-built). The container-built one exists only inside the
        # image, so the picker (not this test) decides at runtime.
        assert (REPO / "third_party" / "timeloop" / "bin" / "timeloop-mapper").exists()

    def test_env_follows_provenance_container_clean(self):
        """The 20260917_032223 failure: container mapper + vendored
        LD_LIBRARY_PATH = host libs shadow image libs -> exit 127. The
        env builder must NOT inject the vendored build dir for the
        container-built binary, and must STRIP it if inherited."""
        env = _timeloop_env("container-built (/usr/local/bin)",
                            base={"LD_LIBRARY_PATH": "/some/other:/leak/path"},
                            vendor_libdir="/leak/path")
        assert env["LD_LIBRARY_PATH"] == "/some/other"
        env2 = _timeloop_env("container-built (/usr/local/bin)", base={})
        assert "LD_LIBRARY_PATH" not in env2

    def test_env_follows_provenance_vendored_injects(self):
        """Vendored binary needs its in-tree build dir first on the
        loader path; existing entries are preserved after it."""
        env = _timeloop_env("vendored host-built (third_party/timeloop/bin)",
                            base={"LD_LIBRARY_PATH": "/keep/me"},
                            vendor_libdir="/vendored/build")
        assert env["LD_LIBRARY_PATH"] == "/vendored/build:/keep/me"

    def test_env_missing_provenance_is_conservative(self):
        """Unknown provenance string: treat like container (no injection)
        — the vendored path is the one that can poison the loader."""
        env = _timeloop_env("missing", base={"LD_LIBRARY_PATH": "/x"},
                            vendor_libdir="/vendored/build")
        assert env["LD_LIBRARY_PATH"] == "/x"
