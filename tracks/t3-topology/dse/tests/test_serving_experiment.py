"""PR6 Phase 4 — serving slice verdicts (pure) + goldens (live).

Terminal truth here is retirement + artifacts + process state — never
the liveness classifier, never exit code alone. Replay specs cannot
enter the slice at all (refused at the boundary); replay-as-negative
is additionally pinned at the gate predicate elsewhere.
"""
import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.core.experiment_serving import (
    check_involved_dim_tripwire,
    fabric_evidence,
    run_serving_experiment,
)
from veritx_dse.core.errors import ServingResultError
from veritx_dse.core.spec import SpecError

from veritx_dse.core.paths import REPO  # noqa: E402
LLMSIM = REPO / "third_party" / "llmservingsim"
BOOKSIM_BIN = REPO / "third_party" / "astra-sim" / "astra-sim" / \
    "network_frontend" / "booksim2" / "bin" / "AstraSim_BookSim2"

needs_serving = pytest.mark.skipif(
    not (LLMSIM / "serving" / "__main__.py").exists(),
    reason="LLMServingSim not vendored")
needs_binary = pytest.mark.skipif(not BOOKSIM_BIN.exists(),
                                  reason="AstraSim_BookSim2 not built")


def _spec_dict(**serving_kw):
    serving = {"cluster": "single_tp2_ep2", "dataset": "example",
               "num_reqs": 1}
    serving.update(serving_kw)
    return {
        "name": "pr6t",
        "workload": {"id": "w", "trace": "archive/inputs/traces/x.trace"},
        "system": {"nodes": 1},
        "network": {"topology": "mesh_8x8"},
        "simulation": {"mode": "serving", "timeout_s": 900},
        "serving": serving,
    }


class TestVerdictHelpers:
    def test_fabric_evidence_counts(self):
        err = ("[LEDGER][TOPO] npus=2 dims=2,2\n"
               "[LEDGER][COLL_SUBMIT] x involved_dims=[true,false]\n"
               "[LEDGER][COLL_COMPLETE] y\n"
               "[LEDGER][STATE] z retired_flits=1200 tail_deliveries=9\n")
        ev = fabric_evidence(err)
        assert ev["coll_completes"] == 1
        assert ev["max_retired_flits"] == 1200
        assert ev["submit_vectors"] == [[True, False]]
        assert ev["topo_dims"] == [2, 2]

    def test_tripwire_passes_scoped_multidim(self):
        ev = {"topo_dims": [2, 2],
              "submit_vectors": [[True, False], [True, True]],
              "coll_completes": 2, "max_retired_flits": 5}
        check_involved_dim_tripwire(ev)  # must not raise

    def test_tripwire_fails_fabricated_length(self):
        ev = {"topo_dims": [2, 2],
              "submit_vectors": [[True, True, True, True]],
              "coll_completes": 1, "max_retired_flits": 5}
        with pytest.raises(ServingResultError) as e:
            check_involved_dim_tripwire(ev)
        assert e.value.reason == "FABRICATION_SUSPECT"

    def test_tripwire_fails_unscoped_multidim(self):
        ev = {"topo_dims": [2, 2],
              "submit_vectors": [[True, True]],
              "coll_completes": 1, "max_retired_flits": 5}
        with pytest.raises(ServingResultError) as e:
            check_involved_dim_tripwire(ev)
        assert e.value.reason == "SCOPING_ABSENT"

    def test_tripwire_exempts_single_dim(self):
        ev = {"topo_dims": [2],
              "submit_vectors": [[True, True, True, True]],
              "coll_completes": 1, "max_retired_flits": 5}
        check_involved_dim_tripwire(ev)  # 1-dim: fallback unread, exempt


class TestSliceRefusals:
    def test_non_serving_mode_rejected(self, tmp_path):
        d = _spec_dict()
        d["simulation"] = {"mode": "latency"}
        with pytest.raises(SpecError, match="serving"):
            run_serving_experiment(d, repo=tmp_path)

    def test_replay_spec_rejected(self, tmp_path):
        with pytest.raises(SpecError, match="cycle_accurate"):
            run_serving_experiment(_spec_dict(cycle_accurate=False),
                                   repo=tmp_path)

    def test_non_booksim_rejected(self, tmp_path):
        with pytest.raises(SpecError, match="booksim"):
            run_serving_experiment(_spec_dict(network_backend="analytical"),
                                   repo=tmp_path)

    def test_stochastic_rejected(self, tmp_path):
        d = _spec_dict()
        d["replication"] = {"mode": "stochastic", "seeds": [1, 2]}
        with pytest.raises(SpecError, match="deterministic"):
            run_serving_experiment(d, repo=tmp_path)

    def test_unknown_fixture_rejected(self, tmp_path):
        with pytest.raises(SpecError, match="unknown serving cluster"):
            run_serving_experiment(_spec_dict(cluster="nope"),
                                   repo=tmp_path)

    @needs_serving
    @needs_binary
    def test_preflight_failure_cancels_without_success(
            self, tmp_path, monkeypatch):
        """Invalid execution leaves CANCELLED evidence, never success."""
        import veritx_dse.core.experiment_serving as es
        from veritx_dse.core.errors import ServingPreflightError
        monkeypatch.setattr(es, "preflight_serve",
                            lambda **kw: (_ for _ in ()).throw(
                                ServingPreflightError("CLUSTER_INVALID",
                                                      "boom")))
        monkeypatch.setattr("veritx_dse.core.runs.VERITX_RUNS_DIR",
                            tmp_path / "runs")
        run = run_serving_experiment(_spec_dict(), repo=tmp_path)
        assert run.state == "CANCELLED"
        results = json.loads(
            (run.root / "manifest.json").read_text())["results"]
        assert "CLUSTER_INVALID" in results[0]["error"]


@needs_serving
@needs_binary
class TestFastNegatives:
    """Every verdict arm, without paying for real simulation twice."""

    def _fake_run(self, tmp_path, monkeypatch, csv_rows=None,
                  returncode=0, timeout=False):
        import veritx_dse.core.process as proc

        # Minimal honest fabric evidence: single-dim topology, one
        # collective completed, nonzero retired flits.
        err = ("[LEDGER][TOPO] npus=1 dims=1\n"
               "[LEDGER][COLL_COMPLETE] x\n"
               "[LEDGER][STATE] y retired_flits=64 tail_deliveries=2\n")

        class R:
            wall_time_s = 1.5

        def fake(cmd, **kw):
            csv_path = [a for a in cmd if a.endswith(".csv")]
            if csv_rows is not None and csv_path:
                with open(csv_path[0], "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["instance id", "request id", "arrival",
                                "end_time", "latency", "TTFT", "TPOT",
                                "ITL"])
                    w.writerows(csv_rows)
            if timeout:
                raise subprocess.TimeoutExpired(cmd, 1)
            r = R()
            r.returncode, r.stdout, r.stderr = returncode, "out", err
            return r

        monkeypatch.setattr(proc, "supervised_run", fake)
        monkeypatch.setattr("veritx_dse.core.runs.VERITX_RUNS_DIR",
                            tmp_path / "runs")
        return run_serving_experiment(_spec_dict(), repo=tmp_path)

    def test_exact_retirement_succeeds(self, tmp_path, monkeypatch):
        run = self._fake_run(
            tmp_path, monkeypatch,
            csv_rows=[["0", "0", "100", "1100", "1000", "700", "100",
                       "[100]"]],
            returncode=0)
        assert run.state == "SUCCEEDED"

    def test_retirement_mismatch_fails(self, tmp_path, monkeypatch):
        import veritx_dse.core.process as proc

        def fake(cmd, **kw):
            csv_path = [a for a in cmd if a.endswith(".csv")][0]
            with open(csv_path, "w", newline="") as f:
                f.write("instance id,request id,TTFT,TPOT,ITL\n")
            r = type("R", (), {})()
            r.returncode, r.stdout, r.stderr = 0, "out", "err"
            r.wall_time_s = 1.0
            return r

        monkeypatch.setattr(proc, "supervised_run", fake)
        monkeypatch.setattr("veritx_dse.core.runs.VERITX_RUNS_DIR",
                            tmp_path / "runs")
        d = _spec_dict(num_reqs=2)
        run = run_serving_experiment(d, repo=tmp_path)
        assert run.state == "FAILED"
        results = json.loads(
            (run.root / "manifest.json").read_text())["results"]
        assert results[0]["error"] == "RETIREMENT_MISMATCH"

    def test_nonzero_exit_fails(self, tmp_path, monkeypatch):
        run = self._fake_run(tmp_path, monkeypatch, csv_rows=None,
                             returncode=3)
        assert run.state == "FAILED"

    def test_timeout_fails(self, tmp_path, monkeypatch):
        run = self._fake_run(tmp_path, monkeypatch, timeout=True)
        assert run.state == "FAILED"


def _result(run):
    return json.loads((run.root / "manifest.json").read_text())["results"][0]


@needs_serving
@needs_binary
class TestGoldenA:
    """Single-instance TP/EP>1 under REAL_SIMULATION: fabric activity."""

    def test_single_instance_fabric_golden(self, tmp_path, monkeypatch):
        monkeypatch.setattr("veritx_dse.core.runs.VERITX_RUNS_DIR",
                            tmp_path / "runs")
        run = run_serving_experiment(_spec_dict(), repo=tmp_path)
        assert run.state == "SUCCEEDED"
        res = _result(run)
        assert res["metrics"]["requests_retired"]["value"] == 1
        assert res["provenance"]["network_mode"] == "REAL_SIMULATION"
        assert res["provenance"]["semantic_losses"] == []
        assert res["provenance"]["fidelity"] == "SYSTEM_SERVING_SIMULATION"
        assert res["fabric"]["coll_completes"] >= 1
        assert res["fabric"]["max_retired_flits"] > 0
        assert res["metric_schema"] == 1
        assert res["metrics"]["TTFT"]["unit"] == "ns"
        assert res["metrics"]["sim_clock"]["unit"] == "ns"
        assert res["backend_binaries"][0]["sha256"] is not None
        assert res["cluster_sha256"] is not None
        assert res["dataset_sha256"] is not None


@needs_serving
@needs_binary
class TestGoldenB:
    """Multi-instance DP/TP under REAL_SIMULATION: ownership + retirement."""

    def test_multi_instance_ownership_golden(self, tmp_path, monkeypatch):
        import csv as _csv
        monkeypatch.setattr("veritx_dse.core.runs.VERITX_RUNS_DIR",
                            tmp_path / "runs")
        d = _spec_dict(cluster="multi_dp_tp", num_reqs=2,
                       request_routing_policy="RR")
        d["simulation"] = {"mode": "serving", "timeout_s": 1200}
        run = run_serving_experiment(d, repo=tmp_path)
        assert run.state == "SUCCEEDED"
        res = _result(run)
        assert res["metrics"]["requests_retired"]["value"] == 2
        csv_path = run.root / "artifacts" / "requests.csv"
        with open(csv_path, newline="") as f:
            seen = {r["instance id"] for r in _csv.DictReader(f)}
        # RR over 2 requests guarantees both instances serve: rebinding
        # bugs (all completions credited to instance 0) fail here.
        assert seen == {"0", "1"}, f"ownership broken: {seen}"
        assert res["fabric"]["coll_completes"] >= 1
        assert res["provenance"]["network_mode"] == "REAL_SIMULATION"
