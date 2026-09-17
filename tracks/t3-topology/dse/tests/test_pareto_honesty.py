"""Pareto benchmark honesty fixes (2026-09-16 audit response).

Four fixes, each paired with the audit finding it closes:

1. Auto timeout       -- flat 60s cutoff timed out big traces (668k pkts)
                         before they finished; TIMEOUT then read like a
                         topology property when it was a benchmark property.
2. Result classes     -- FAIL(exit 0) conflated "simulator crashed" with
                         "exited clean but no metric parsed".
3. Duplicate traces   -- byte-identical files under two names double-count
                         a workload in every average.
4. Normalized geomean -- arithmetic means over different per-topo trace
                         populations are not comparable; ranking now uses
                         per-trace normalized scores over the common
                         successful set.

Pure-unit style: no BookSim binary, no subprocesses. The ranking math is
tested through aggregate() -- the same seam the CLI uses -- never by
re-implementing it inside a test (a test that mirrors the implementation
verifies nothing).
"""
import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))


def _load_pareto_module():
    from veritx_dse.core.paths import REPO
    spec = importlib.util.spec_from_file_location(
        "mwp_audit",
        str(Path(REPO) / "tracks/t3-topology/dse/veritx_dse/tools/multi_workload_pareto.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mwp():
    return _load_pareto_module()


def _mk_run(topo, trace, lat):
    return {"name": topo, "trace_name": trace, "latency": lat}


def _agg(mwp, runs, topos, traces):
    return mwp.aggregate(runs, topos, traces)


# -- 1. auto timeout budget ------------------------------------------------

class TestAutoTimeout:
    def test_small_trace_gets_floor(self, mwp, tmp_path):
        p = tmp_path / "small.trace"
        p.write_text("0 0 0 1 4\n100 1 0 2 4\n")
        assert mwp.auto_timeout(str(p)) == mwp.TIME_BUDGET_MIN_S

    def test_scales_with_packets(self, mwp, tmp_path):
        p = tmp_path / "big.trace"
        # 200k pkts -> 120 + 0.005*200000 = 1120s (within clamp)
        p.write_text("\n".join("%d 1 0 2 4" % i for i in range(200_000)) + "\n")
        assert mwp.auto_timeout(str(p)) == 1120

    def test_clamped_at_max(self, mwp, tmp_path):
        p = tmp_path / "huge.trace"
        p.write_text("\n".join("%d 1 0 2 4" % i for i in range(10_000_000)) + "\n")
        assert mwp.auto_timeout(str(p)) == mwp.TIME_BUDGET_MAX_S

    def test_missing_file_falls_to_floor(self, mwp):
        assert mwp.auto_timeout("/nonexistent/trace.file") == mwp.TIME_BUDGET_MIN_S

    def test_budget_covers_audit_case(self, mwp):
        # 668k-packet serving trace: the old flat 60s was ~10x under budget.
        budget = mwp.TIME_BUDGET_BASE_S + mwp.TIME_BUDGET_PER_PKT_S * 668_161
        assert budget > mwp.TIME_BUDGET_MIN_S
        assert mwp.TIME_BUDGET_MIN_S > 60


# -- 2. result classification ----------------------------------------------

class TestClassify:
    def test_ok(self, mwp):
        assert mwp._classify({"latency": 12.5}) == "ok"

    def test_timeout_via_failure_kind(self, mwp):
        r = {"latency": None, "extra": {"failure_kind": "timeout"}}
        assert mwp._classify(r) == "timeout"

    def test_timeout_via_legacy_error(self, mwp):
        assert mwp._classify({"latency": None, "error": "timeout"}) == "timeout"

    def test_exit0_no_metric_is_no_metric(self, mwp):
        # The audit's FAIL(exit 0): rc=0 plus no latency is NOT a crash.
        r = {"latency": None, "error": "no latency in output (exit 0)",
             "extra": {"failure_kind": "no_latency", "returncode": 0}}
        assert mwp._classify(r) == "no_metric"

    def test_nonzero_exit_is_crash(self, mwp):
        r = {"latency": None, "error": "no latency in output (exit 1)",
             "extra": {"failure_kind": "no_latency", "returncode": 1}}
        assert mwp._classify(r) == "crash"

    def test_crash_from_error_string_when_no_rc(self, mwp):
        r = {"latency": None, "error": "booksim died (exit -11)"}
        assert mwp._classify(r) == "crash"

    def test_skip_incompatible(self, mwp):
        assert mwp._classify({"skipped": True, "latency": None}) == "skipped"

    def test_verdict_labels(self, mwp):
        assert set(mwp._VERDICTS.values()) == {
            "OK", "TIMEOUT", "CRASH", "NO_METRIC", "SKIP_INCOMPATIBLE"}


# -- 3. duplicate trace detection ------------------------------------------

class TestDedupeTraces:
    def test_identical_files_collapsed(self, mwp, tmp_path):
        body = "\n".join("%d 1 0 2 4" % i for i in range(100))
        a = tmp_path / "qwen3_20k.trace"; a.write_text(body)
        b = tmp_path / "qwen3_20k_slice.trace"; b.write_text(body)  # same bytes
        out = mwp._dedupe_traces([a, b])
        assert [p.name for p in out] == ["qwen3_20k.trace"]

    def test_different_files_both_kept(self, mwp, tmp_path):
        a = tmp_path / "a.trace"; a.write_text("0 0 0 1 4\n")
        b = tmp_path / "b.trace"; b.write_text("0 0 0 1 4\n100 1 0 2 4\n")
        assert len(mwp._dedupe_traces([a, b])) == 2

    def test_order_preserved(self, mwp, tmp_path):
        a = tmp_path / "a.trace"; a.write_text("0 0 0 1 4\n")
        b = tmp_path / "b.trace"; b.write_text("5 1 0 2 4\n")
        c = tmp_path / "c.trace"; c.write_text("0 0 0 1 4\n")  # dup of a
        out = mwp._dedupe_traces([a, b, c])
        assert [p.name for p in out] == ["a.trace", "b.trace"]


# -- 4. ranking seam: aggregate() -------------------------------------------

class TestAggregate:
    """Classification, normalization, and common-set discipline in one seam."""

    def test_per_trace_latency_is_seed_mean(self, mwp):
        runs = [_mk_run("a", "t1", 10.0), _mk_run("a", "t1", 20.0)]
        agg, _ = _agg(mwp, runs, ["a"], ["t1"])
        assert agg[0]["lat_t1"] == 15.0

    def test_baseline_is_best_per_trace(self, mwp):
        runs = [_mk_run("fast", "t1", 10.0), _mk_run("slow", "t1", 20.0)]
        _, meta = _agg(mwp, runs, ["fast", "slow"], ["t1"])
        assert meta["baseline"]["t1"] == 10.0

    def test_geomean_ranks_faster_topology_first(self, mwp):
        # a wins t1 (10 vs 20) but loses t2 (100 vs 50): a and b tie at
        # geomean sqrt(2) -- each is 2x best on one trace. The strictly
        # slower topo scores sqrt(3*4) and ranks last. Note the geometric
        # mean punishes being bad on ANY trace -- the property the audit
        # wanted; an arithmetic mean over mixed populations hides it.
        runs = [_mk_run("a", "t1", 10.0), _mk_run("b", "t1", 20.0),
                _mk_run("a", "t2", 100.0), _mk_run("b", "t2", 50.0),
                _mk_run("slow", "t1", 30.0), _mk_run("slow", "t2", 200.0)]
        agg, _ = _agg(mwp, runs, ["a", "b", "slow"], ["t1", "t2"])
        by = {r["name"]: r for r in agg}
        assert by["a"]["geomean"] == pytest.approx(2 ** 0.5)
        assert by["b"]["geomean"] == pytest.approx(2 ** 0.5)
        assert by["slow"]["geomean"] == pytest.approx(12 ** 0.5)
        assert agg[-1]["name"] == "slow"

    def test_workload_influence_is_equalized(self, mwp):
        # The audit's point: raw means let the big-number trace dominate.
        # 'a' is 2x best on BOTH traces; normalized score is exactly 2.0
        # regardless of each trace's absolute scale.
        runs = [_mk_run("a", "small", 20.0), _mk_run("a", "huge", 20000.0),
                _mk_run("b", "small", 10.0), _mk_run("b", "huge", 10000.0)]
        agg, _ = _agg(mwp, runs, ["a", "b"], ["small", "huge"])
        assert agg[0]["geomean"] == pytest.approx(2.0)
        assert agg[0]["mean_lat"] != agg[1]["mean_lat"]

    def test_failed_trace_shrinks_common_set(self, mwp):
        # A trace where NO topology succeeded is excluded from ranking --
        # and that shrink is visible in meta + n_common, not silent.
        runs = [_mk_run("a", "t1", 10.0), _mk_run("b", "t1", 20.0),
                _mk_run("a", "big", None), _mk_run("b", "big", None)]
        agg, meta = _agg(mwp, runs, ["a", "b"], ["t1", "big"])
        assert meta["common_ok"] == {"t1"}
        assert all(r["n_common"] == ["t1"] for r in agg)
        assert agg[1]["geomean"] == pytest.approx(2.0)

    def test_partial_failure_geomean_is_none(self, mwp):
        # A topology that failed one common trace gets geomean=None (and
        # last-place ranking), NOT a geomean over its successful subset.
        runs = [_mk_run("a", "t1", 10.0), _mk_run("a", "t2", 10.0),
                _mk_run("b", "t1", 20.0), _mk_run("b", "t2", None)]
        agg, _ = _agg(mwp, runs, ["a", "b"], ["t1", "t2"])
        by = {r["name"]: r for r in agg}
        assert by["b"]["geomean"] is None
        assert by["b"]["ok"] is False
        # legacy raw mean still present for pipeline.py (over t1 only)
        assert by["b"]["mean_lat"] == 20.0

    def test_classification_counts_reach_meta(self, mwp):
        runs = [_mk_run("a", "t1", 10.0),
                {"name": "b", "trace_name": "t1", "latency": None,
                 "error": "timeout"},
                {"name": "b", "trace_name": "t2", "latency": None,
                 "error": "exit 0",
                 "extra": {"failure_kind": "no_latency", "returncode": 0}}]
        _, meta = _agg(mwp, runs, ["a", "b"], ["t1", "t2"])
        assert meta["classes"]["timeout"] == ["b/t1"]
        assert meta["classes"]["no_metric"] == ["b/t2"]
        assert meta["classes"]["ok"] == ["a/t1"]

    def test_empty_results_give_empty_meta(self, mwp):
        agg, meta = _agg(mwp, [], ["a"], ["t1"])
        assert agg[0]["geomean"] is None and agg[0]["ok"] is False
        assert meta["common_ok"] == set() and meta["baseline"] == {}

    def test_agg_keys_survive_for_pipeline(self, mwp):
        # pipeline.py tabulates agg rows via name/edges/lat_*/mean_lat --
        # asserted on aggregate()'s real output, not a hand-built dict.
        runs = [_mk_run("a", "t1", 10.0)]
        agg, _ = _agg(mwp, runs, ["a"], ["t1"])
        for key in ("name", "edges", "nodes", "lat_t1", "mean_lat",
                    "ok", "n_common", "geomean"):
            assert key in agg[0], key


class TestGeomean:
    def test_equal_scores_give_one(self, mwp):
        assert mwp._geomean([1.0, 1.0, 1.0]) == pytest.approx(1.0)

    def test_double_latency_means_score_two(self, mwp):
        assert mwp._geomean([1.0, 2.0]) == pytest.approx(2 ** 0.5)

    def test_none_poisons(self, mwp):
        assert mwp._geomean([1.0, None]) is None

    def test_nonpositive_poisons(self, mwp):
        assert mwp._geomean([1.0, 0.0]) is None

    def test_empty(self, mwp):
        assert mwp._geomean([]) is None


# -- trace fingerprinting ---------------------------------------------------

class TestFingerprint:
    def test_counts_and_nodes(self, mwp, tmp_path):
        p = tmp_path / "fp.trace"
        p.write_text("# comment\n0 0 0 1 4\n100 1 0 16 4\n200 2 0 3 4\n")
        fp = mwp._validate_trace(str(p))
        assert fp["packets"] == 3
        assert fp["nodes"] == 5          # {0,1,2} u {16,1,2,3}
        assert fp["max_node"] == 16

    def test_stub_warning_content(self, mwp, tmp_path, capsys):
        p = tmp_path / "stub.trace"
        p.write_text("\n".join("%d 1 0 2 4" % i for i in range(10)) + "\n")
        fp = mwp._validate_trace(str(p))
        out = capsys.readouterr().out
        assert fp["nodes"] == 2          # src={1}, dst={2}
        assert "NOT full-fabric" in out


class TestModuleSurface:
    def test_new_surface_exists(self, mwp):
        # Precedence cases NOT reachable through aggregate()'s meta:
        # crash-from-string and skip. (ok/timeout/no_metric paths are
        # covered via test_classification_counts_reach_meta -- not
        # re-tested here through the private function alone.)
        assert mwp._classify({"latency": None, "error": "died (exit -11)"}) == "crash"
        assert mwp._classify({"skipped": True}) == "skipped"
        # The public ranking seam exists and is callable.
        agg, meta = mwp.aggregate([], ["a"], ["t1"])
        assert agg and meta["common_ok"] == set()
